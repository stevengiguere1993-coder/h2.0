"""Saisie d'un reçu « en miroir » de QuickBooks (pôle Entreprises).

Demande Steven (2026-10-04) : un endroit pour ajouter nos reçus, on
choisit la compagnie concernée, on entre le fournisseur, le montant, la
façon dont ça a été payé ou si c'est une facture à payer, avec exactement
les mêmes choix que QuickBooks. Le reçu part dans QuickBooks ; il n'est
pas enregistré dans Kratos puisque la copie de nuit le récupère et le
range dans le Drive.

Décisions (proposition acceptée le 2026-10-04) :

- Les listes du formulaire (fournisseurs, comptes de paiement,
  catégories, modes de paiement, modalités, codes de taxe) sont lues EN
  DIRECT dans le QuickBooks de l'inc : mêmes choix que QB, rien à
  entretenir dans Kratos. La compagnie suit le réglage de l'inc
  (``qbo_recus_drive.scope_de`` : la sienne ou celle d'Horizon).
- « Payé » → Dépense QB (Purchase) ; « À payer » → Facture fournisseur
  (Bill), qui exige un fournisseur. Sans fournisseur, la Dépense part sans
  bénéficiaire et la copie Drive la nomme « ND ».
- Montants : on saisit le TOTAL du reçu. La ligne part HORS TAXES et les
  taxes EXACTES du reçu partent en TxnTaxDetail sur les taux d'ACHAT du
  code choisi (même méthode que les achats Construction, ``achat_qbo`` :
  QBO n'honore pas « taxes incluses » sur une Purchase). Si QBO refuse les
  lignes de taxe explicites, on le laisse calculer (repli, ~1 cent).
- Trace minimale dans Kratos (``recus_qbo_saisis``) : qui, quand, numéro
  QB et la clé d'envoi du formulaire, qui bloque un double envoi. Avant
  de créer, on cherche dans QB une dépense du même jour, même total, même
  fournisseur : si elle existe, on demande confirmation.
- Copie vers le Drive : la nuit, par la copie existante (aucun appel au
  Drive ici).
"""

from __future__ import annotations

import asyncio
import logging
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, List, Literal, Optional, Sequence, Tuple

from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.entreprise import Entreprise
from app.models.qbo_connection import QboConnection
from app.models.qbo_token import QboToken
from app.models.recu_qbo_saisi import RecuQboSaisi
from app.models.user import User

# Formats et taille acceptés = ceux que la copie de nuit sait ranger dans
# le Drive : un reçu joint dans un autre format resterait dans QuickBooks.
from app.services.qbo_recus_drive import (
    _CTYPE_EXT,
    _MAX_OCTETS,
    SCOPE_CONSTRUCTION,
    infos_transaction,
    nom_fichier,
    scope_de,
)

log = logging.getLogger(__name__)

TYPE_PAYE = "paye"
TYPE_A_PAYER = "a_payer"

#: Types de compte QB proposés comme « compte de paiement » d'une Dépense
#: (mêmes choix que le menu de QB) → type affiché.
TYPES_COMPTE_PAIEMENT: Dict[str, str] = {"Bank": "banque", "Credit Card": "carte"}

#: Catégories proposées sur la ligne, par groupe, dépenses d'abord (QB
#: accepte aussi un actif ou un passif sur une ligne de dépense).
GROUPES_CATEGORIES: List[Tuple[str, Tuple[str, ...]]] = [
    ("Dépenses", ("Expense",)),
    ("Coût des produits vendus", ("Cost of Goods Sold",)),
    ("Autres dépenses", ("Other Expense",)),
    (
        "Autres comptes",
        (
            "Fixed Asset",
            "Other Asset",
            "Other Current Asset",
            "Other Current Liability",
            "Long Term Liability",
            "Equity",
        ),
    ),
]

#: Taux de la TPS et de la TVQ : le code qui porte les deux est proposé
#: par défaut (compagnies du Québec).
TAUX_TPS = 5.0
TAUX_TVQ = 9.975

#: Transactions récentes lues pour retrouver les habitudes d'un
#: fournisseur (dernière catégorie, code de taxe, compte de paiement…).
TRANSACTIONS_HABITUDES = 300

#: Un envoi resté « en_cours » plus longtemps est considéré abandonné
#: (onglet fermé, serveur redémarré) : la même clé peut être renvoyée.
ENVOI_ABANDONNE_APRES = timedelta(minutes=2)

#: Types de fichiers acceptés (sous-ensemble de ceux de la copie de nuit).
TYPES_FICHIER: Dict[str, str] = {
    **_CTYPE_EXT,
    "image/jpg": ".jpg",
    "image/heif": ".heic",
}


# ──────────────────────────────────────────────────────────────────────
# Erreurs
# ──────────────────────────────────────────────────────────────────────


class SaisieErreur(Exception):
    """Erreur présentable telle quelle à l'utilisateur."""

    def __init__(self, message: str, statut: int = 422, **extra: Any) -> None:
        super().__init__(message)
        self.message = message
        self.statut = statut
        self.extra = extra


class DoublonQbo(SaisieErreur):
    """Une dépense du même jour, même total, même fournisseur existe déjà."""

    def __init__(self, transaction: Dict[str, Any]) -> None:
        super().__init__(
            "Une dépense du même jour et du même montant existe déjà dans "
            "QuickBooks. Vérifie qu'il ne s'agit pas du même reçu.",
            statut=409,
            doublon=transaction,
        )


def message_qbo(exc: Exception) -> str:
    """Motif lisible d'une erreur QuickBooks (le client met « QBO refus :
    <motif> — » en tête quand QBO en donne un)."""
    msg = str(exc)
    if msg.startswith("QBO refus : "):
        return msg[len("QBO refus : "):].split(" — ", 1)[0].strip()
    return msg[:300]


# ──────────────────────────────────────────────────────────────────────
# Données du formulaire
# ──────────────────────────────────────────────────────────────────────


class TaxeIn(BaseModel):
    """Montant d'une taxe du reçu, sur un taux d'achat du code choisi."""

    taux_id: str = Field(min_length=1, max_length=64)
    montant: float = Field(ge=0)


class RecuIn(BaseModel):
    """Champs de l'écran Dépense / Facture fournisseur de QuickBooks."""

    #: Clé générée par le formulaire, une par reçu (anti double envoi).
    cle_envoi: str = Field(min_length=8, max_length=64)
    type: Literal["paye", "a_payer"]
    date_recu: date
    #: Fournisseur QB existant…
    fournisseur_id: Optional[str] = Field(default=None, max_length=64)
    #: …ou nom d'un nouveau fournisseur, créé dans QB à l'envoi. Les deux
    #: vides = fournisseur inconnu (« ND »), permis seulement si payé.
    nouveau_fournisseur: Optional[str] = Field(default=None, max_length=100)
    #: Payé : compte Banque ou Carte de crédit d'où sort l'argent.
    compte_paiement_id: Optional[str] = Field(default=None, max_length=64)
    mode_paiement_id: Optional[str] = Field(default=None, max_length=64)
    #: À payer : modalités et/ou échéance.
    modalite_id: Optional[str] = Field(default=None, max_length=64)
    date_echeance: Optional[date] = None
    categorie_id: str = Field(min_length=1, max_length=64)
    code_taxe_id: Optional[str] = Field(default=None, max_length=64)
    #: Total du reçu, taxes comprises.
    total: float = Field(gt=0, le=10_000_000)
    #: Taxes du reçu (une par taux du code). Absentes = calculées.
    taxes: Optional[List[TaxeIn]] = Field(default=None, max_length=10)
    reference: Optional[str] = Field(default=None, max_length=21)
    description: Optional[str] = Field(default=None, max_length=4000)
    memo: Optional[str] = Field(default=None, max_length=1000)
    #: Envoyer même si une dépense semblable existe déjà dans QB.
    forcer_doublon: bool = False

    @field_validator(
        "fournisseur_id",
        "nouveau_fournisseur",
        "compte_paiement_id",
        "mode_paiement_id",
        "modalite_id",
        "code_taxe_id",
        "reference",
        "description",
        "memo",
        mode="before",
    )
    @classmethod
    def _vide_devient_none(cls, v: Any) -> Any:
        if isinstance(v, str):
            v = v.strip()
            return v or None
        return v

    @model_validator(mode="after")
    def _coherence(self) -> "RecuIn":
        if self.fournisseur_id and self.nouveau_fournisseur:
            raise ValueError("Choisis un fournisseur existant OU un nouveau, pas les deux.")
        if self.type == TYPE_PAYE and not self.compte_paiement_id:
            raise ValueError("Choisis le compte de paiement (banque ou carte de crédit).")
        if self.type == TYPE_A_PAYER and not (self.fournisseur_id or self.nouveau_fournisseur):
            raise ValueError(
                "Une facture à payer exige un fournisseur : QuickBooks la refuse sans."
            )
        if self.date_echeance and self.date_echeance < self.date_recu:
            raise ValueError("L'échéance précède la date de la facture.")
        return self


@dataclass
class FichierRecu:
    nom: str
    type_contenu: str
    contenu: bytes


def verifier_fichier(nom: Optional[str], type_contenu: Optional[str], contenu: bytes) -> FichierRecu:
    """Photo ou PDF du reçu : formats et taille que la copie Drive accepte."""
    ct = (type_contenu or "").lower().split(";")[0].strip()
    if ct not in TYPES_FICHIER:
        raise SaisieErreur(
            "Format non supporté. Joins une photo (JPG, PNG, WEBP, HEIC) ou un PDF.",
            statut=415,
        )
    if not contenu:
        raise SaisieErreur("Le fichier du reçu est vide.", statut=400)
    if len(contenu) > _MAX_OCTETS:
        raise SaisieErreur(
            f"Fichier trop gros (plus de {_MAX_OCTETS // (1024 * 1024)} Mo).",
            statut=413,
        )
    return FichierRecu(nom=nom or "recu", type_contenu=ct, contenu=contenu)


# ──────────────────────────────────────────────────────────────────────
# Calculs purs
# ──────────────────────────────────────────────────────────────────────


def cents(x: float) -> float:
    """Arrondi au cent, demi vers le haut (9,975 → 9,98)."""
    return float(Decimal(str(x)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def ventiler(total: float, pourcents: Sequence[float]) -> Tuple[float, List[float]]:
    """(hors taxes, [taxe par taux]) d'un total taxes comprises.

    Chaque taxe = HT × taux, arrondie au cent ; la dernière taxe non nulle
    absorbe l'écart d'arrondi pour que HT + taxes = total exactement.
    Le formulaire fait le même calcul (et l'utilisateur peut corriger).
    """
    total = cents(total)
    somme = sum(p for p in pourcents if p > 0)
    if somme <= 0:
        return total, [0.0 for _ in pourcents]
    ht = cents(total / (1 + somme / 100))
    montants = [cents(ht * p / 100) if p > 0 else 0.0 for p in pourcents]
    ecart = cents(total - ht - sum(montants))
    if ecart:
        dernier = max(i for i, p in enumerate(pourcents) if p > 0)
        montants[dernier] = cents(montants[dernier] + ecart)
    return ht, montants


def _cle_tri(nom: str) -> str:
    base = unicodedata.normalize("NFKD", nom or "")
    return "".join(c for c in base if not unicodedata.combining(c)).casefold()


def _ref(obj: Optional[Dict[str, Any]]) -> Optional[str]:
    v = (obj or {}).get("value")
    return str(v) if v not in (None, "") else None


def lien_qbo(env: Optional[str], realm_id: Optional[str], txn_type: Optional[str], txn_id: Optional[str]) -> Optional[str]:
    """Lien vers la transaction dans QuickBooks (ouvre la bonne compagnie)."""
    if not (txn_type and txn_id):
        return None
    page = {"Purchase": "expense", "Bill": "bill"}.get(txn_type)
    if not page:
        return None
    hote = (
        "https://app.sandbox.qbo.intuit.com"
        if (env or "").lower() == "sandbox"
        else "https://app.qbo.intuit.com"
    )
    url = f"{hote}/app/{page}?txnId={txn_id}"
    if realm_id:
        url += f"&deeplinkcompanyid={realm_id}"
    return url


# ──────────────────────────────────────────────────────────────────────
# Entreprises et connexion QuickBooks
# ──────────────────────────────────────────────────────────────────────


async def _connexions(db: AsyncSession) -> Tuple[Dict[str, QboConnection], Optional[QboToken]]:
    conns = {
        c.scope: c
        for c in (
            await db.execute(select(QboConnection).where(QboConnection.scope.like("inc:%")))
        ).scalars().all()
    }
    tok = (await db.execute(select(QboToken).where(QboToken.id == 1))).scalar_one_or_none()
    return conns, tok


def _etat_connexion(
    scope: str, conns: Dict[str, QboConnection], tok: Optional[QboToken]
) -> Dict[str, Any]:
    if scope == SCOPE_CONSTRUCTION:
        return {
            "connectee": bool(tok and tok.refresh_token and tok.realm_id),
            "company_name": (getattr(tok, "company_name", None) if tok else None)
            or "Horizon (Construction)",
            "realm_id": tok.realm_id if tok else None,
            "environment": (getattr(tok, "environment", None) if tok else None)
            or settings.quickbooks_env,
        }
    c = conns.get(scope)
    return {
        "connectee": bool(c and c.realm_id and c.refresh_token),
        "company_name": c.company_name if c else None,
        "realm_id": c.realm_id if c else None,
        "environment": (c.environment if c else None) or settings.quickbooks_env,
    }


async def entreprises(db: AsyncSession) -> List[Dict[str, Any]]:
    """Entreprises actives et leur compagnie QuickBooks (sans appel externe)."""
    conns, tok = await _connexions(db)
    ents = (
        await db.execute(
            select(Entreprise)
            .where(Entreprise.is_active.is_(True))
            .order_by(Entreprise.position.asc(), Entreprise.id.asc())
        )
    ).scalars().all()
    out: List[Dict[str, Any]] = []
    for e in ents:
        scope = scope_de(e)
        etat = _etat_connexion(scope, conns, tok)
        out.append(
            {
                "entreprise_id": e.id,
                "name": e.name,
                "qbo_scope": scope,
                "qbo_connectee": etat["connectee"],
                "qbo_company_name": etat["company_name"],
            }
        )
    return out


async def _entreprise_connectee(db: AsyncSession, entreprise_id: int) -> Tuple[Entreprise, str, Dict[str, Any]]:
    e = await db.get(Entreprise, entreprise_id)
    if e is None or not e.is_active:
        raise SaisieErreur("Entreprise introuvable.", statut=404)
    scope = scope_de(e)
    conns, tok = await _connexions(db)
    etat = _etat_connexion(scope, conns, tok)
    if not etat["connectee"]:
        raise SaisieErreur(
            "QuickBooks n'est pas connecté pour cette entreprise. Connecte-le "
            "dans Paramètres → Drive → Reçus QuickBooks.",
            statut=409,
        )
    return e, scope, etat


# ──────────────────────────────────────────────────────────────────────
# Listes du formulaire (lues dans QuickBooks)
# ──────────────────────────────────────────────────────────────────────


def _codes_taxe_achat(
    codes: List[Dict[str, Any]], taux: Dict[str, Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Codes de taxe utilisables sur un achat, avec leurs taux d'ACHAT."""
    out: List[Dict[str, Any]] = []
    for c in codes:
        details = ((c.get("PurchaseTaxRateList") or {}).get("TaxRateDetail")) or []
        lignes: List[Dict[str, Any]] = []
        for d in details:
            rid = _ref(d.get("TaxRateRef"))
            if not rid:
                continue
            r = taux.get(rid) or {}
            try:
                pourcent = float(r.get("RateValue") or 0)
            except (TypeError, ValueError):
                pourcent = 0.0
            lignes.append(
                {
                    "id": rid,
                    "nom": r.get("Name") or (d.get("TaxRateRef") or {}).get("name") or "Taxe",
                    "pourcent": pourcent,
                }
            )
        if not lignes:
            continue
        out.append({"id": str(c.get("Id")), "nom": c.get("Name") or "", "taux": lignes})
    out.sort(key=lambda x: _cle_tri(x["nom"]))
    # Défaut : le code TPS + TVQ (les compagnies sont au Québec).
    for x in out:
        valeurs = sorted(t["pourcent"] for t in x["taux"] if t["pourcent"] > 0)
        x["defaut"] = valeurs == [TAUX_TPS, TAUX_TVQ]
    if sum(1 for x in out if x["defaut"]) > 1:
        premier = next(x for x in out if x["defaut"])
        for x in out:
            x["defaut"] = x is premier
    return out


def _habitudes(purchases: List[Dict[str, Any]], bills: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Dernière saisie de chaque fournisseur, pour préremplir le formulaire
    comme QB le ferait : catégorie, code de taxe, compte et mode de
    paiement (Dépense) ou modalités (Facture)."""
    lignes: List[Tuple[str, str, Dict[str, Any]]] = []
    for p in purchases:
        ent = p.get("EntityRef") or {}
        if (ent.get("type") or "Vendor") != "Vendor":
            continue
        vid = _ref(ent)
        if vid:
            lignes.append((str(p.get("TxnDate") or ""), "Purchase", p))
    for b in bills:
        vid = _ref(b.get("VendorRef"))
        if vid:
            lignes.append((str(b.get("TxnDate") or ""), "Bill", b))
    lignes.sort(key=lambda x: x[0], reverse=True)
    out: Dict[str, Dict[str, Any]] = {}
    for _, kind, t in lignes:
        vid = _ref(t.get("EntityRef") if kind == "Purchase" else t.get("VendorRef"))
        if not vid or vid in out:
            continue
        ligne = next(
            (
                ln.get("AccountBasedExpenseLineDetail")
                for ln in t.get("Line") or []
                if ln.get("DetailType") == "AccountBasedExpenseLineDetail"
            ),
            None,
        )
        if not ligne:
            continue
        h: Dict[str, Any] = {
            "type": TYPE_PAYE if kind == "Purchase" else TYPE_A_PAYER,
            "categorie_id": _ref(ligne.get("AccountRef")),
            "code_taxe_id": _ref(ligne.get("TaxCodeRef")),
        }
        if kind == "Purchase":
            h["compte_paiement_id"] = _ref(t.get("AccountRef"))
            h["mode_paiement_id"] = _ref(t.get("PaymentMethodRef"))
        else:
            h["modalite_id"] = _ref(t.get("SalesTermRef"))
        out[vid] = h
    return out


async def choix(db: AsyncSession, entreprise_id: int) -> Dict[str, Any]:
    """Listes du formulaire pour une entreprise, lues dans son QuickBooks."""
    from app.integrations.quickbooks import QuickBooksError, get_qbo

    e, scope, etat = await _entreprise_connectee(db, entreprise_id)
    qbo = get_qbo(scope)

    async def _facultatif(sql: str) -> List[Dict[str, Any]]:
        # Modalités, modes de paiement, taxes : une compagnie sans ces
        # fonctions ne doit pas bloquer le formulaire.
        try:
            return await qbo.query_all(sql)
        except QuickBooksError as exc:
            log.warning("Reçus QB (%s) : %s → %s", scope, sql, exc)
            return []

    async def _recentes(entite: str) -> List[Dict[str, Any]]:
        try:
            return await qbo.query(
                f"SELECT * FROM {entite} ORDERBY TxnDate DESC MAXRESULTS {TRANSACTIONS_HABITUDES}"
            )
        except QuickBooksError as exc:
            log.warning("Reçus QB (%s) : %s récentes → %s", scope, entite, exc)
            return []

    try:
        (
            vendors,
            comptes,
            modes,
            termes,
            codes,
            taux,
            purchases,
            bills,
        ) = await asyncio.gather(
            qbo.query_all("SELECT * FROM Vendor WHERE Active = true"),
            qbo.query_all("SELECT * FROM Account WHERE Active = true"),
            _facultatif("SELECT * FROM PaymentMethod WHERE Active = true"),
            _facultatif("SELECT * FROM Term WHERE Active = true"),
            _facultatif("SELECT * FROM TaxCode WHERE Active = true"),
            _facultatif("SELECT * FROM TaxRate"),
            _recentes("Purchase"),
            _recentes("Bill"),
        )
    except QuickBooksError as exc:
        raise SaisieErreur(
            f"QuickBooks ne répond pas : {message_qbo(exc)}", statut=502
        ) from exc
    except RuntimeError as exc:  # client non configuré (clés Intuit absentes)
        raise SaisieErreur(f"QuickBooks n'est pas configuré : {exc}", statut=409) from exc

    fournisseurs = sorted(
        (
            {"id": str(v.get("Id")), "nom": (v.get("DisplayName") or "").strip()}
            for v in vendors
            if v.get("Id") and (v.get("DisplayName") or "").strip()
        ),
        key=lambda x: _cle_tri(x["nom"]),
    )

    def _compte(a: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "id": str(a.get("Id")),
            "nom": (a.get("FullyQualifiedName") or a.get("Name") or "").strip(),
            "numero": (a.get("AcctNum") or "").strip() or None,
        }

    comptes_paiement = sorted(
        (
            {**_compte(a), "type": TYPES_COMPTE_PAIEMENT[a.get("AccountType")]}
            for a in comptes
            if a.get("Id") and a.get("AccountType") in TYPES_COMPTE_PAIEMENT
        ),
        key=lambda x: (x["type"] != "carte", _cle_tri(x["nom"])),
    )
    categories: List[Dict[str, Any]] = []
    for groupe, types in GROUPES_CATEGORIES:
        categories.extend(
            sorted(
                (
                    {**_compte(a), "groupe": groupe}
                    for a in comptes
                    if a.get("Id") and a.get("AccountType") in types
                ),
                key=lambda x: (x["numero"] or "", _cle_tri(x["nom"])),
            )
        )
    taux_par_id = {str(t.get("Id")): t for t in taux if t.get("Id")}

    return {
        "entreprise": {
            "entreprise_id": e.id,
            "name": e.name,
            "qbo_scope": scope,
            "qbo_company_name": etat["company_name"],
        },
        "fournisseurs": fournisseurs,
        "comptes_paiement": comptes_paiement,
        "categories": categories,
        "modes_paiement": sorted(
            (
                {"id": str(m.get("Id")), "nom": (m.get("Name") or "").strip()}
                for m in modes
                if m.get("Id")
            ),
            key=lambda x: _cle_tri(x["nom"]),
        ),
        "modalites": [
            {
                "id": str(t.get("Id")),
                "nom": (t.get("Name") or "").strip(),
                "jours": t.get("DueDays"),
            }
            for t in termes
            if t.get("Id")
        ],
        "codes_taxe": _codes_taxe_achat(codes, taux_par_id),
        "habitudes": _habitudes(purchases, bills),
    }


# ──────────────────────────────────────────────────────────────────────
# Envoi vers QuickBooks
# ──────────────────────────────────────────────────────────────────────


async def _taux_du_code(qbo: Any, code_taxe_id: str) -> List[Tuple[str, float]]:
    """[(taux_id, pourcent)] des taux d'ACHAT d'un code de taxe QB."""
    code = await qbo.get_tax_code(str(code_taxe_id))
    if not code:
        raise SaisieErreur("Code de taxe introuvable dans QuickBooks.")
    details = ((code.get("PurchaseTaxRateList") or {}).get("TaxRateDetail")) or []
    out: List[Tuple[str, float]] = []
    for d in details:
        rid = _ref(d.get("TaxRateRef"))
        if not rid:
            continue
        r = await qbo.get_tax_rate(rid)
        try:
            pourcent = float((r or {}).get("RateValue") or 0)
        except (TypeError, ValueError):
            pourcent = 0.0
        out.append((rid, pourcent))
    if not out:
        raise SaisieErreur("Ce code de taxe ne s'applique pas aux achats dans QuickBooks.")
    return out


def taxes_du_recu(
    total: float, taux: List[Tuple[str, float]], saisies: Optional[List[TaxeIn]]
) -> Tuple[float, List[Tuple[str, float, float]]]:
    """(hors taxes, [(taux_id, pourcent, montant)]) du reçu.

    Taxes saisies → contrôlées (taux du code, total plus grand) ; sinon
    calculées depuis le total. Un code qui applique des taxes avec des
    taxes à zéro est refusé : QBO les ajouterait par-dessus le total."""
    total = cents(total)
    if saisies is None:
        ht, montants = ventiler(total, [p for _, p in taux])
        return ht, [(rid, p, m) for (rid, p), m in zip(taux, montants)]
    par_id = {s.taux_id: cents(s.montant) for s in saisies}
    inconnus = set(par_id) - {rid for rid, _ in taux}
    if inconnus:
        raise SaisieErreur("Une taxe saisie ne correspond pas au code de taxe choisi.")
    lignes = [(rid, p, par_id.get(rid, 0.0)) for rid, p in taux]
    somme = cents(sum(m for _, _, m in lignes))
    if somme >= total:
        raise SaisieErreur("Les taxes dépassent le total du reçu.")
    if any(m > 0 for _, p, m in lignes if p <= 0):
        raise SaisieErreur("Ce code de taxe n'applique pas de taxe : mets les taxes à zéro.")
    if somme == 0 and any(p > 0 for _, p in taux):
        raise SaisieErreur(
            "Ce code de taxe applique des taxes. Si le reçu n'en a pas, "
            "choisis le code « Exonéré » (ou « Détaxé »)."
        )
    return cents(total - somme), lignes


def construire_transaction(
    recu: RecuIn,
    *,
    vendor_id: Optional[str],
    type_compte_paiement: Optional[str],
    ht: float,
    taxes: List[Tuple[str, float, float]],
    note: str,
) -> Tuple[str, Dict[str, Any]]:
    """(« Purchase » | « Bill », payload QBO) du reçu."""
    detail: Dict[str, Any] = {"AccountRef": {"value": recu.categorie_id}}
    if recu.code_taxe_id:
        detail["TaxCodeRef"] = {"value": recu.code_taxe_id}
    ligne: Dict[str, Any] = {
        "DetailType": "AccountBasedExpenseLineDetail",
        "Amount": cents(ht),
        "AccountBasedExpenseLineDetail": detail,
    }
    if recu.description:
        ligne["Description"] = recu.description[:4000]
    payload: Dict[str, Any] = {
        "TxnDate": recu.date_recu.isoformat(),
        "Line": [ligne],
        "PrivateNote": note[:4000],
    }
    if recu.reference:
        payload["DocNumber"] = recu.reference[:21]
    if recu.code_taxe_id:
        # Ligne HORS taxes + taxes exactes du reçu (cf. en-tête).
        payload["GlobalTaxCalculation"] = "TaxExcluded"
        lignes_taxe = [t for t in taxes if t[2] > 0]
        if lignes_taxe:
            payload["TxnTaxDetail"] = {
                "TotalTax": cents(sum(m for _, _, m in lignes_taxe)),
                "TaxLine": [
                    {
                        "Amount": m,
                        "DetailType": "TaxLineDetail",
                        "TaxLineDetail": {
                            "TaxRateRef": {"value": rid},
                            "PercentBased": True,
                            "TaxPercent": p,
                            "NetAmountTaxable": cents(ht),
                        },
                    }
                    for rid, p, m in lignes_taxe
                ],
            }
    if recu.type == TYPE_PAYE:
        payload["AccountRef"] = {"value": recu.compte_paiement_id}
        payload["PaymentType"] = "CreditCard" if type_compte_paiement == "carte" else "Cash"
        if vendor_id:
            payload["EntityRef"] = {"value": vendor_id, "type": "Vendor"}
        if recu.mode_paiement_id:
            payload["PaymentMethodRef"] = {"value": recu.mode_paiement_id}
        return "Purchase", payload
    payload["VendorRef"] = {"value": vendor_id}
    if recu.modalite_id:
        payload["SalesTermRef"] = {"value": recu.modalite_id}
    if recu.date_echeance:
        payload["DueDate"] = recu.date_echeance.isoformat()
    return "Bill", payload


async def chercher_doublon(
    qbo: Any,
    *,
    jour: date,
    total: float,
    vendor_id: Optional[str],
    fournisseur_nouveau: bool = False,
) -> Optional[Dict[str, Any]]:
    """Dépense ou facture fournisseur du même jour et du même total dont
    le fournisseur est le même, ou inconnu (« ND ») d'un des deux côtés.

    ``fournisseur_nouveau`` : le fournisseur n'existe pas encore dans QB,
    seule une dépense sans fournisseur peut alors être le même reçu."""
    total = cents(total)
    for entite in ("Purchase", "Bill"):
        rows = await qbo.query(
            f"SELECT * FROM {entite} WHERE TxnDate = '{jour.isoformat()}' MAXRESULTS 1000"
        )
        for r in rows:
            try:
                montant = cents(float(r.get("TotalAmt") or 0))
            except (TypeError, ValueError):
                continue
            if montant != total:
                continue
            ref = r.get("VendorRef") if entite == "Bill" else r.get("EntityRef")
            autre = _ref(ref)
            if autre and (fournisseur_nouveau or (vendor_id and autre != vendor_id)):
                continue
            infos = infos_transaction(entite, r)
            return {
                "txn_type": entite,
                "txn_id": str(r.get("Id") or ""),
                "date": jour.isoformat(),
                "fournisseur": infos["fournisseur"],
                "montant": infos["montant"],
                "reference": r.get("DocNumber"),
            }
    return None


def _est_taux_refuse(exc: Exception) -> bool:
    msg = str(exc).lower()
    return "invalid tax rate" in msg or "taux de taxe non valide" in msg


async def _creer(qbo: Any, entite: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    from app.integrations.quickbooks import QuickBooksError

    creer = qbo.create_purchase if entite == "Purchase" else qbo.create_bill
    try:
        return await creer(payload)
    except QuickBooksError as exc:
        if _est_taux_refuse(exc) and payload.pop("TxnTaxDetail", None) is not None:
            # Même repli que les achats Construction : QBO calcule la taxe
            # sur le hors-taxes (au plus un cent d'écart).
            log.warning("Reçu QB : taxes exactes refusées → calcul QBO (%s)", exc)
            return await creer(payload)
        raise


async def _joindre(
    qbo: Any, entite: str, txn: Dict[str, Any], fichier: FichierRecu
) -> Optional[str]:
    """Joint la photo à la transaction. Renvoie l'erreur (texte) ou None.

    Nommée comme la copie Drive la nommera (« 2026-10-03 Rona 2134,02$.pdf »)."""
    infos = infos_transaction(entite, txn)
    jour = infos["date"] or date.today()
    ext = TYPES_FICHIER.get(fichier.type_contenu, ".pdf")
    nom = nom_fichier(jour, infos["fournisseur"], infos["montant"], ext)
    try:
        await qbo.upload_attachment(
            entity_type=entite,
            entity_id=str(txn.get("Id")),
            file_name=nom,
            content_type=fichier.type_contenu,
            content=fichier.contenu,
        )
        return None
    except Exception as exc:  # noqa: BLE001 — la dépense est créée, on garde la main
        log.warning("Reçu QB : pièce jointe refusée (%s %s) : %s", entite, txn.get("Id"), exc)
        return message_qbo(exc)


def _maintenant() -> datetime:
    return datetime.now(timezone.utc)


def _age(trace: RecuQboSaisi) -> timedelta:
    t = trace.updated_at or trace.created_at
    if t is None:
        return timedelta(0)
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return _maintenant() - t


def _resultat(trace: RecuQboSaisi, etat: Dict[str, Any], *, deja: bool = False) -> Dict[str, Any]:
    return {
        "saisie_id": trace.id,
        "statut": trace.statut,
        "txn_type": trace.txn_type,
        "txn_id": trace.txn_id,
        "lien_qbo": lien_qbo(etat.get("environment"), trace.realm_id, trace.txn_type, trace.txn_id),
        "photo_jointe": trace.statut == "envoye",
        "erreur_photo": trace.detail if trace.statut == "photo_a_reprendre" else None,
        "deja_envoye": deja,
    }


async def envoyer(
    db: AsyncSession,
    *,
    entreprise_id: int,
    user: User,
    recu: RecuIn,
    fichier: Optional[FichierRecu],
) -> Dict[str, Any]:
    """Crée la Dépense ou la Facture fournisseur dans le QuickBooks de
    l'inc, joint la photo, et garde la trace minimale."""
    from app.integrations.quickbooks import QuickBooksError, get_qbo

    _, scope, etat = await _entreprise_connectee(db, entreprise_id)

    # 1) Clé d'envoi : un deuxième clic renvoie le premier résultat.
    trace = (
        await db.execute(select(RecuQboSaisi).where(RecuQboSaisi.cle_envoi == recu.cle_envoi))
    ).scalar_one_or_none()
    if trace is not None:
        if trace.statut != "en_cours":
            return _resultat(trace, etat, deja=True)
        if _age(trace) < ENVOI_ABANDONNE_APRES:
            raise SaisieErreur("Ce reçu est déjà en cours d'envoi.", statut=409)
        trace.updated_at = _maintenant()  # envoi abandonné : on le reprend
        await db.commit()
    else:
        trace = RecuQboSaisi(
            cle_envoi=recu.cle_envoi,
            entreprise_id=entreprise_id,
            qbo_scope=scope,
            realm_id=etat.get("realm_id"),
            statut="en_cours",
            user_id=user.id,
        )
        db.add(trace)
        try:
            await db.commit()
        except IntegrityError as exc:  # même clé envoyée au même instant
            await db.rollback()
            raise SaisieErreur("Ce reçu est déjà en cours d'envoi.", statut=409) from exc

    qbo: Any = None
    try:
        qbo = get_qbo(scope)
        resultat = await _envoyer_dans_qbo(qbo, recu, user)
    except Exception as exc:
        # Rien n'a été créé dans QuickBooks : la clé est libérée pour un
        # nouvel essai (corrigé, ou « envoyer quand même »).
        await db.rollback()
        await db.delete(trace)
        await db.commit()
        if isinstance(exc, DoublonQbo):
            d = exc.extra["doublon"]
            d["lien_qbo"] = lien_qbo(
                etat.get("environment"),
                getattr(qbo, "realm_id", None) or etat.get("realm_id"),
                d.get("txn_type"),
                d.get("txn_id"),
            )
        if isinstance(exc, SaisieErreur):
            raise
        if isinstance(exc, QuickBooksError):
            raise SaisieErreur(
                f"QuickBooks a refusé le reçu : {message_qbo(exc)}", statut=502
            ) from exc
        if isinstance(exc, RuntimeError):
            raise SaisieErreur(f"QuickBooks n'est pas configuré : {exc}", statut=409) from exc
        raise

    entite, txn = resultat
    trace.txn_type = entite
    trace.txn_id = str(txn.get("Id") or "")
    trace.realm_id = getattr(qbo, "realm_id", None) or trace.realm_id
    trace.statut = "envoye"
    trace.detail = None
    if fichier is not None:
        erreur = await _joindre(qbo, entite, txn, fichier)
        if erreur:
            trace.statut = "photo_a_reprendre"
            trace.detail = erreur[:1000]
    else:
        trace.statut = "photo_a_reprendre"
        trace.detail = "Aucune photo jointe."
    await db.commit()
    out = _resultat(trace, etat)
    infos = infos_transaction(entite, txn)
    out["fournisseur"] = infos["fournisseur"]
    out["montant"] = infos["montant"]
    out["date"] = infos["date"].isoformat() if infos["date"] else None
    return out


async def _envoyer_dans_qbo(qbo: Any, recu: RecuIn, user: User) -> Tuple[str, Dict[str, Any]]:
    # Compte de paiement : vérifié dans QB (banque ou carte, actif).
    type_compte: Optional[str] = None
    if recu.type == TYPE_PAYE:
        compte = await qbo.get_account(str(recu.compte_paiement_id))
        type_compte = TYPES_COMPTE_PAIEMENT.get((compte or {}).get("AccountType") or "")
        if not compte or not type_compte or compte.get("Active") is False:
            raise SaisieErreur(
                "Le compte de paiement doit être un compte bancaire ou une "
                "carte de crédit actif dans QuickBooks."
            )

    # Taxes du reçu.
    if recu.code_taxe_id:
        ht, taxes = taxes_du_recu(recu.total, await _taux_du_code(qbo, recu.code_taxe_id), recu.taxes)
    else:
        if recu.taxes and any(t.montant > 0 for t in recu.taxes):
            raise SaisieErreur("Choisis le code de taxe des taxes saisies.")
        ht, taxes = cents(recu.total), []

    # Fournisseur : existant, ou nouveau (réutilise celui qui porte déjà ce
    # nom dans QB ; sinon il est créé APRÈS le contrôle des doublons).
    vendor_id = recu.fournisseur_id
    a_creer: Optional[str] = None
    if recu.nouveau_fournisseur:
        existant = await qbo.find_vendor_by_name(recu.nouveau_fournisseur)
        if existant and existant.get("Id"):
            vendor_id = str(existant["Id"])
        else:
            a_creer = recu.nouveau_fournisseur

    if not recu.forcer_doublon:
        doublon = await chercher_doublon(
            qbo,
            jour=recu.date_recu,
            total=recu.total,
            vendor_id=vendor_id,
            fournisseur_nouveau=bool(a_creer),
        )
        if doublon:
            raise DoublonQbo(doublon)

    if a_creer:
        cree = await qbo.create_vendor(display_name=a_creer)
        vendor_id = str(cree.get("Id") or "") or None
        if not vendor_id:
            raise SaisieErreur("QuickBooks n'a pas créé le fournisseur.", statut=502)

    note = " | ".join(
        x for x in (recu.memo, f"Saisi dans Kratos par {user.display_name}") if x
    )
    entite, payload = construire_transaction(
        recu,
        vendor_id=vendor_id,
        type_compte_paiement=type_compte,
        ht=ht,
        taxes=taxes,
        note=note,
    )
    txn = await _creer(qbo, entite, payload)
    if not txn.get("Id"):
        raise SaisieErreur("QuickBooks n'a pas renvoyé la transaction créée.", statut=502)
    return entite, txn


async def reprendre_photo(
    db: AsyncSession, *, saisie_id: int, fichier: FichierRecu
) -> Dict[str, Any]:
    """Renvoie seulement la photo d'un reçu dont la transaction existe."""
    from app.integrations.quickbooks import QuickBooksError, get_qbo

    trace = await db.get(RecuQboSaisi, saisie_id)
    if trace is None or not trace.txn_id or not trace.txn_type:
        raise SaisieErreur("Reçu introuvable.", statut=404)
    if trace.statut == "envoye":
        raise SaisieErreur("La photo de ce reçu est déjà jointe dans QuickBooks.", statut=409)
    conns, tok = await _connexions(db)
    etat = _etat_connexion(trace.qbo_scope, conns, tok)
    qbo = get_qbo(trace.qbo_scope)
    try:
        lire = qbo.get_purchase if trace.txn_type == "Purchase" else qbo.get_bill
        txn = await lire(trace.txn_id)
    except QuickBooksError as exc:
        raise SaisieErreur(
            f"Transaction introuvable dans QuickBooks : {message_qbo(exc)}", statut=502
        ) from exc
    erreur = await _joindre(qbo, trace.txn_type, txn, fichier)
    if erreur:
        trace.detail = erreur[:1000]
        await db.commit()
        raise SaisieErreur(f"QuickBooks a refusé la photo : {erreur}", statut=502)
    trace.statut = "envoye"
    trace.detail = None
    await db.commit()
    return _resultat(trace, etat)


async def journal(
    db: AsyncSession, *, entreprise_id: Optional[int] = None, limit: int = 30
) -> List[Dict[str, Any]]:
    """Derniers reçus envoyés (trace minimale) avec le lien QuickBooks."""
    q = select(RecuQboSaisi).where(RecuQboSaisi.statut != "en_cours")
    if entreprise_id is not None:
        q = q.where(RecuQboSaisi.entreprise_id == entreprise_id)
    rows = (
        await db.execute(q.order_by(RecuQboSaisi.created_at.desc(), RecuQboSaisi.id.desc()).limit(limit))
    ).scalars().all()
    if not rows:
        return []
    ent_ids = sorted({r.entreprise_id for r in rows if r.entreprise_id})
    user_ids = sorted({r.user_id for r in rows if r.user_id})
    noms_ent = {
        e.id: e.name
        for e in (
            await db.execute(select(Entreprise).where(Entreprise.id.in_(ent_ids)))
        ).scalars().all()
    }
    users = {
        u.id: u.display_name
        for u in (await db.execute(select(User).where(User.id.in_(user_ids)))).scalars().all()
    }
    conns, tok = await _connexions(db)
    out: List[Dict[str, Any]] = []
    for r in rows:
        etat = _etat_connexion(r.qbo_scope, conns, tok)
        out.append(
            {
                "saisie_id": r.id,
                "entreprise_id": r.entreprise_id,
                "entreprise": noms_ent.get(r.entreprise_id or 0),
                "txn_type": r.txn_type,
                "txn_id": r.txn_id,
                "statut": r.statut,
                "detail": r.detail,
                "par": users.get(r.user_id or 0),
                "envoye_le": r.created_at.isoformat() if r.created_at else None,
                "lien_qbo": lien_qbo(etat.get("environment"), r.realm_id, r.txn_type, r.txn_id),
            }
        )
    return out
