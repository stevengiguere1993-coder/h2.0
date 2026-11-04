"""Fiches clients QuickBooks par l'API : détail, inventaire des
transactions, modification (nom, parent, actif, facturer avec le parent).

Steven (2026-11-03) : clients en double dans le QuickBooks d'Horizon,
factures réparties entre les doublons ; les corrections de fiches
doivent passer par Kratos et son connecteur (« passe par le lien
Kratos »), pas par l'écran de QuickBooks.

Ce que l'API Intuit permet sur un Customer : le renommer, le rendre
actif ou inactif, le déplacer sous un autre client mère, cocher
« Facturer avec le client parent ». Ce qu'elle ne permet PAS : fusionner
deux fiches. Un nom déjà porté est refusé (Duplicate Name Exists, code
6240) ; la fusion se fait dans l'écran de QuickBooks, en renommant le
doublon au nom EXACT de la fiche gardée — QuickBooks propose alors de
fusionner, et tout l'historique passe sous la fiche gardée.

Garde-fous, vérifiés AVANT tout envoi à QuickBooks :
- nom déjà porté par une autre fiche, active ou non → 409 (QuickBooks le
  refuserait avec un message obscur) ; même vérification à la
  réactivation, QuickBooks retirant alors le suffixe « (supprimé) » ;
- parent introuvable, inactif, la fiche elle-même ou un de ses propres
  sous-clients → 422 ; plus de cinq niveaux → 422 ;
- rendre inactive une fiche qui a des sous-clients actifs ou un solde →
  409 sauf ``forcer`` (QuickBooks désactive les sous-clients avec leur
  parent et refuse un solde non nul) ;
- ``simuler`` : tout est validé et décrit, rien n'est écrit.

Chaque modification est UNE mise à jour « sparse » sur le SyncToken relu
(exigence QuickBooks), journalisée par le journal automatique des
écritures (``audit_middleware``) ; la réponse rend la fiche avant et
après. Rien n'est copié en base : QuickBooks reste la seule source.
"""

from __future__ import annotations

import logging
import re
from datetime import date, timedelta
from typing import Any, Dict, Iterable, List, Optional, Tuple

from app.integrations import quickbooks as qbo_mod

log = logging.getLogger(__name__)

#: Compagnies QuickBooks connues de Kratos (scope de ``get_qbo``).
COMPAGNIE_RE = re.compile(r"^(construction|entreprise|immobilier|inc:\d+)$")

#: Suffixe que QuickBooks ajoute au nom d'une fiche rendue inactive, et
#: retire quand on la réactive.
RE_SUPPRIME = re.compile(r"\s*\((?:deleted|supprim[ée]e?s?)\)\s*$", re.IGNORECASE)

#: QuickBooks accepte cinq niveaux de sous-clients (niveau 0 à 4).
NIVEAU_MAX = 4

#: Types de transactions que QuickBooks laisse compter par client
#: (``WHERE CustomerRef = …``), avec leur libellé.
TYPES_TRANSACTIONS: Tuple[Tuple[str, str], ...] = (
    ("Invoice", "factures"),
    ("Payment", "paiements"),
    ("CreditMemo", "notes_de_credit"),
    ("SalesReceipt", "recus_de_vente"),
    ("RefundReceipt", "remboursements"),
    ("Estimate", "soumissions"),
    ("TimeActivity", "temps"),
)


class ClientQboErreur(Exception):
    """Erreur à renvoyer telle quelle au client HTTP (statut + détail)."""

    def __init__(self, statut: int, message: str, **extra: Any) -> None:
        super().__init__(message)
        self.statut = statut
        self.message = message
        self.extra = extra

    @property
    def detail(self) -> Any:
        if not self.extra:
            return self.message
        return {"message": self.message, **self.extra}


# ── Lecture ─────────────────────────────────────────────────────────


def compagnie_valide(compagnie: str) -> str:
    compagnie = (compagnie or "").strip().lower()
    if not COMPAGNIE_RE.match(compagnie):
        raise ClientQboErreur(
            422,
            "`compagnie` doit être construction, entreprise, immobilier "
            "ou inc:<id d'entreprise>.",
        )
    return compagnie


def _client(compagnie: str) -> Any:
    return qbo_mod.get_qbo(compagnie_valide(compagnie))


def _motif(exc: Exception) -> str:
    """Motif lisible d'une erreur QuickBooks (« QBO refus : <motif> — … »)."""
    msg = str(exc)
    if msg.startswith("QBO refus : "):
        return msg[len("QBO refus : "):].split(" — ", 1)[0].strip()
    return msg[:300]


def _erreur_qb(exc: Exception, compagnie: str) -> ClientQboErreur:
    return ClientQboErreur(
        502,
        f"QuickBooks ({compagnie}) a refusé : {_motif(exc)}. "
        f"Au besoin : {qbo_mod.ou_reconnecter(compagnie)}.",
    )


def _num(v: Any) -> Optional[float]:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def parent_de(row: Optional[Dict[str, Any]]) -> str:
    return str(((row or {}).get("ParentRef") or {}).get("value") or "")


def fiche(row: Dict[str, Any]) -> Dict[str, Any]:
    """Vue normalisée d'un Customer QuickBooks (tous les champs utiles au
    nettoyage des doublons, dont le SyncToken et les dates)."""
    parent = row.get("ParentRef") if isinstance(row.get("ParentRef"), dict) else None
    meta = row.get("MetaData") if isinstance(row.get("MetaData"), dict) else {}
    return {
        "Id": str(row.get("Id")),
        "DisplayName": row.get("DisplayName"),
        "FullyQualifiedName": row.get("FullyQualifiedName"),
        "Active": bool(row.get("Active", True)),
        "Job": bool(row.get("Job", False)),
        "ParentRef": (
            {"value": str(parent.get("value")), "name": parent.get("name")}
            if parent and parent.get("value") is not None
            else None
        ),
        "BillWithParent": bool(row.get("BillWithParent", False)),
        "IsProject": bool(row.get("IsProject", False)),
        "Level": row.get("Level"),
        "Balance": _num(row.get("Balance")) or 0.0,
        "BalanceWithJobs": _num(row.get("BalanceWithJobs")),
        "SyncToken": row.get("SyncToken"),
        "CompanyName": row.get("CompanyName"),
        "PrimaryEmailAddr": (row.get("PrimaryEmailAddr") or {}).get("Address"),
        "PrimaryPhone": (row.get("PrimaryPhone") or {}).get("FreeFormNumber"),
        "Notes": row.get("Notes"),
        "CreateTime": meta.get("CreateTime"),
        "LastUpdatedTime": meta.get("LastUpdatedTime"),
    }


def _resume(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "Id": str(row.get("Id")),
        "DisplayName": row.get("DisplayName"),
        "Active": bool(row.get("Active", True)),
        "Balance": _num(row.get("Balance")) or 0.0,
        "ParentRef": parent_de(row) or None,
    }


async def _tous(qbo: Any, compagnie: str) -> List[Dict[str, Any]]:
    """Tous les clients et sous-clients, actifs ET inactifs."""
    try:
        rows = await qbo.all_customers_any()
    except qbo_mod.QuickBooksError as exc:
        raise _erreur_qb(exc, compagnie)
    return [r for r in rows if isinstance(r, dict) and r.get("Id") is not None]


async def _fiche_courante(
    qbo: Any, compagnie: str, customer_id: str, par_id: Dict[str, Dict[str, Any]]
) -> Dict[str, Any]:
    row = par_id.get(customer_id)
    if row is None:
        try:
            row = await qbo.get_customer_any(customer_id)
        except qbo_mod.QuickBooksError as exc:
            raise _erreur_qb(exc, compagnie)
    if not row:
        raise ClientQboErreur(
            404, f"Client QuickBooks {customer_id} introuvable ({compagnie})."
        )
    return row


def _sous_clients(
    tous: Iterable[Dict[str, Any]], customer_id: str
) -> List[Dict[str, Any]]:
    return sorted(
        (r for r in tous if parent_de(r) == customer_id),
        key=lambda r: (not bool(r.get("Active", True)), str(r.get("DisplayName") or "")),
    )


async def lire(compagnie: str, customer_id: str) -> Dict[str, Any]:
    """Une fiche, même inactive, avec ses sous-clients directs."""
    compagnie = compagnie_valide(compagnie)
    qbo = _client(compagnie)
    tous = await _tous(qbo, compagnie)
    par_id = {str(r["Id"]): r for r in tous}
    row = await _fiche_courante(qbo, compagnie, customer_id, par_id)
    out = fiche(row)
    out["compagnie"] = compagnie
    out["sous_clients"] = [_resume(r) for r in _sous_clients(tous, customer_id)]
    return out


# ── Inventaire des transactions ─────────────────────────────────────


def lignes_rapport(rapport: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Lignes de données d'un rapport QuickBooks « TransactionList »
    (colonnes repérées par leur ``ColType``, id de la transaction porté
    par la colonne du type)."""
    colonnes = [
        ((c.get("ColType") or "").strip(), (c.get("ColTitle") or "").strip())
        for c in ((rapport.get("Columns") or {}).get("Column") or [])
    ]
    brutes: List[List[Dict[str, Any]]] = []

    def _parcourir(rows: Any) -> None:
        for r in rows or []:
            if not isinstance(r, dict):
                continue
            if r.get("ColData") and (r.get("type") or "Data") == "Data":
                brutes.append(r["ColData"])
            sous = (r.get("Rows") or {}).get("Row")
            if sous:
                _parcourir(sous)

    _parcourir((rapport.get("Rows") or {}).get("Row"))

    lignes: List[Dict[str, Any]] = []
    for cellules in brutes:
        d: Dict[str, Any] = {}
        txn_id: Optional[str] = None
        for (ctype, ctitre), cellule in zip(colonnes, cellules):
            if not isinstance(cellule, dict):
                continue
            val = cellule.get("value")
            d[ctype or ctitre.lower()] = val
            if ctype == "txn_type" and cellule.get("id"):
                txn_id = str(cellule["id"])
        montant: Optional[float] = None
        for k in ("subt_nat_amount", "subt_amount", "subt_nat_home_amount", "amount"):
            if d.get(k) not in (None, ""):
                montant = _num(d[k])
                if montant is not None:
                    break
        lignes.append(
            {
                "date": d.get("tx_date"),
                "type": d.get("txn_type"),
                "id": txn_id,
                "numero": d.get("doc_num"),
                "nom": d.get("name"),
                "memo": d.get("memo"),
                "compte": d.get("account_name"),
                "montant": montant,
            }
        )
    return lignes


async def inventaire(compagnie: str, customer_id: str) -> Dict[str, Any]:
    """Ce que porte une fiche : nombre de transactions par type (requêtes
    ``COUNT`` de QuickBooks), liste des transactions du rapport
    « TransactionList » filtré sur le client (toutes dates), sous-clients.
    Sert à vérifier qu'une fiche est vide avant de la désactiver, et à
    garder l'état d'une fiche avant une fusion."""
    compagnie = compagnie_valide(compagnie)
    qbo = _client(compagnie)
    tous = await _tous(qbo, compagnie)
    par_id = {str(r["Id"]): r for r in tous}
    row = await _fiche_courante(qbo, compagnie, customer_id, par_id)

    comptes: Dict[str, Optional[int]] = {}
    notes: List[str] = []
    for entite, libelle in TYPES_TRANSACTIONS:
        try:
            comptes[libelle] = await qbo.count(
                f"SELECT COUNT(*) FROM {entite} WHERE CustomerRef = '{customer_id}'"
            )
        except qbo_mod.QuickBooksError as exc:  # noqa: BLE001
            comptes[libelle] = None
            notes.append(f"{libelle} : comptage refusé ({_motif(exc)})")

    lignes: List[Dict[str, Any]] = []
    try:
        rapport = await qbo.report(
            "TransactionList",
            customer=customer_id,
            start_date="2000-01-01",
            end_date=(date.today() + timedelta(days=366)).isoformat(),
        )
        lignes = lignes_rapport(rapport)
    except qbo_mod.QuickBooksError as exc:  # noqa: BLE001
        notes.append(f"rapport TransactionList refusé ({_motif(exc)})")

    connus = sum(n for n in comptes.values() if n)
    sous = _sous_clients(tous, customer_id)
    return {
        "compagnie": compagnie,
        "fiche": fiche(row),
        "sous_clients": [_resume(r) for r in sous],
        "transactions_par_type": comptes,
        "nb_transactions": len(lignes),
        "transactions": lignes,
        "vide": not lignes and connus == 0 and not sous,
        "notes": notes,
    }


# ── Modification ────────────────────────────────────────────────────


def _nom_cle(nom: Optional[str]) -> str:
    return " ".join((nom or "").split()).casefold()


def _porteur_du_nom(
    tous: Iterable[Dict[str, Any]], nom: str, *, sauf: str
) -> Optional[Dict[str, Any]]:
    """Une AUTRE fiche (active ou non) portant ce nom d'affichage."""
    cle = _nom_cle(nom)
    for r in tous:
        if str(r.get("Id")) != sauf and _nom_cle(r.get("DisplayName")) == cle:
            return r
    return None


def _ancetres(par_id: Dict[str, Dict[str, Any]], customer_id: str) -> List[str]:
    """Ids des parents, du plus proche à la racine (garde-fou contre une
    boucle de données)."""
    out: List[str] = []
    cur = parent_de(par_id.get(customer_id))
    while cur and cur not in out and len(out) < 50:
        out.append(cur)
        cur = parent_de(par_id.get(cur))
    return out


def _profondeur(par_id: Dict[str, Dict[str, Any]], customer_id: str) -> int:
    """Nombre de niveaux SOUS la fiche (0 sans sous-client)."""
    enfants = [i for i, r in par_id.items() if parent_de(r) == customer_id]
    if not enfants:
        return 0
    return 1 + max(_profondeur(par_id, e) for e in enfants)


async def modifier(
    compagnie: str, customer_id: str, changements: Dict[str, Any]
) -> Dict[str, Any]:
    """Applique les changements demandés (nom, actif, parent_id,
    facturer_avec_parent) en UNE mise à jour sparse, après les
    garde-fous décrits en tête de module. ``simuler`` n'écrit rien."""
    compagnie = compagnie_valide(compagnie)
    qbo = _client(compagnie)
    tous = await _tous(qbo, compagnie)
    par_id = {str(r["Id"]): r for r in tous}
    courant = await _fiche_courante(qbo, compagnie, customer_id, par_id)
    simuler = bool(changements.get("simuler"))
    forcer = bool(changements.get("forcer"))

    corps: Dict[str, Any] = {}
    faits: List[Dict[str, Any]] = []
    avertissements: List[str] = []

    # Nom d'affichage.
    nom = " ".join(str(changements.get("nom") or "").split())
    if nom:
        if ":" in nom:
            raise ClientQboErreur(
                422, "QuickBooks réserve « : » au chemin des sous-clients."
            )
        if nom != (courant.get("DisplayName") or ""):
            autre = _porteur_du_nom(tous, nom, sauf=customer_id)
            if autre:
                raise ClientQboErreur(
                    409,
                    f"Le nom « {nom} » est déjà porté par la fiche "
                    f"#{autre.get('Id')} ({'active' if autre.get('Active', True) else 'inactive'}). "
                    "QuickBooks le refuserait : l'API ne fusionne pas deux "
                    "fiches. Pour fusionner, renomme le doublon à ce nom "
                    "exact dans l'écran de QuickBooks, qui proposera la fusion.",
                    fiche=_resume(autre),
                )
            corps["DisplayName"] = nom[:100]
            faits.append(
                {"champ": "nom", "de": courant.get("DisplayName"), "a": nom[:100]}
            )

    # Actif / inactif.
    actif = changements.get("actif")
    if actif is not None and bool(actif) != bool(courant.get("Active", True)):
        if actif:
            base = RE_SUPPRIME.sub(
                "", corps.get("DisplayName") or str(courant.get("DisplayName") or "")
            )
            autre = _porteur_du_nom(tous, base, sauf=customer_id)
            if autre:
                raise ClientQboErreur(
                    409,
                    f"Réactivée, la fiche reprendrait le nom « {base} », déjà "
                    f"porté par la fiche #{autre.get('Id')}. QuickBooks le "
                    "refuserait par l'API ; dans l'écran de QuickBooks, la "
                    "réactivation proposera de fusionner les deux fiches.",
                    fiche=_resume(autre),
                )
        else:
            sous_actifs = [
                r for r in _sous_clients(tous, customer_id) if r.get("Active", True)
            ]
            solde = _num(courant.get("BalanceWithJobs"))
            if solde is None:
                solde = _num(courant.get("Balance")) or 0.0
            if sous_actifs and not forcer:
                raise ClientQboErreur(
                    409,
                    f"La fiche a {len(sous_actifs)} sous-client(s) actif(s) : "
                    "QuickBooks les rendrait inactifs avec elle. Déplace-les "
                    "ou désactive-les d'abord, ou passe `forcer`.",
                    sous_clients=[_resume(r) for r in sous_actifs],
                )
            if abs(solde) >= 0.005 and not forcer:
                raise ClientQboErreur(
                    409,
                    f"La fiche a un solde de {solde:.2f} $ : QuickBooks refuse "
                    "de rendre inactive une fiche avec un solde. Règle le "
                    "solde d'abord, ou passe `forcer` pour laisser QuickBooks "
                    "trancher.",
                )
            if sous_actifs or abs(solde) >= 0.005:
                avertissements.append(
                    "Désactivation forcée malgré des sous-clients actifs ou "
                    "un solde : QuickBooks peut refuser."
                )
        corps["Active"] = bool(actif)
        faits.append(
            {"champ": "actif", "de": bool(courant.get("Active", True)), "a": bool(actif)}
        )

    # Client mère.
    parent_id = changements.get("parent_id")
    if parent_id is not None:
        parent_id = str(parent_id).strip()
        if not parent_id:
            raise ClientQboErreur(
                422,
                "Retirer le client mère (ramener une fiche au premier niveau) "
                "n'est pas pris en charge par l'API QuickBooks.",
            )
        if parent_id == customer_id:
            raise ClientQboErreur(422, "Une fiche ne peut pas être son propre parent.")
        parent = par_id.get(parent_id)
        if parent is None:
            raise ClientQboErreur(
                422, f"Client mère #{parent_id} introuvable dans {compagnie}."
            )
        if not parent.get("Active", True):
            raise ClientQboErreur(
                422,
                f"Le client mère #{parent_id} ({parent.get('DisplayName')}) est "
                "inactif : réactive-le d'abord.",
            )
        if customer_id in _ancetres(par_id, parent_id):
            raise ClientQboErreur(
                422,
                f"#{parent_id} est un sous-client de #{customer_id} : "
                "impossible de l'en faire le parent.",
            )
        if parent_id != parent_de(courant):
            niveau_parent = len(_ancetres(par_id, parent_id))
            if niveau_parent + 1 + _profondeur(par_id, customer_id) > NIVEAU_MAX:
                raise ClientQboErreur(
                    422,
                    "QuickBooks n'accepte que cinq niveaux de sous-clients : "
                    "ce déplacement en ferait davantage.",
                )
            corps["ParentRef"] = {"value": parent_id}
            corps["Job"] = True
            faits.append(
                {
                    "champ": "parent",
                    "de": parent_de(courant) or None,
                    "a": parent_id,
                    "nom_parent": parent.get("DisplayName"),
                }
            )

    # Facturer avec le client parent.
    fap = changements.get("facturer_avec_parent")
    if fap is not None:
        if not (corps.get("ParentRef") or parent_de(courant)):
            raise ClientQboErreur(
                422,
                "« Facturer avec le client parent » ne s'applique qu'à un "
                "sous-client.",
            )
        if courant.get("IsProject"):
            raise ClientQboErreur(
                422, "Un projet QuickBooks ne porte pas ce réglage."
            )
        if bool(fap) != bool(courant.get("BillWithParent", False)):
            corps["BillWithParent"] = bool(fap)
            if "ParentRef" not in corps:
                # QuickBooks veut ParentRef + Job avec BillWithParent.
                corps["ParentRef"] = {"value": parent_de(courant)}
                corps["Job"] = True
            faits.append(
                {
                    "champ": "facturer_avec_parent",
                    "de": bool(courant.get("BillWithParent", False)),
                    "a": bool(fap),
                }
            )

    resultat: Dict[str, Any] = {
        "compagnie": compagnie,
        "simule": simuler,
        "changements": faits,
        "avertissements": avertissements,
        "avant": fiche(courant),
        "apres": None,
    }
    if not faits:
        resultat["apres"] = fiche(courant)
        resultat["note"] = "Rien à changer : la fiche est déjà dans cet état."
        return resultat
    if simuler:
        resultat["note"] = "Simulation : rien n'a été envoyé à QuickBooks."
        resultat["corps"] = corps
        return resultat

    try:
        maj = await qbo.update_customer_fields(customer_id, **corps)
    except qbo_mod.QuickBooksError as exc:
        raise _erreur_qb(exc, compagnie)
    try:
        apres = await qbo.get_customer_any(customer_id)
    except qbo_mod.QuickBooksError:  # noqa: BLE001
        apres = None
    resultat["apres"] = fiche(apres or maj)
    log.info(
        "Client QuickBooks %s (%s) modifié : %s",
        customer_id,
        compagnie,
        ", ".join(f"{f['champ']} {f.get('de')!r} → {f.get('a')!r}" for f in faits),
    )
    return resultat
