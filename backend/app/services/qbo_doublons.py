"""Comptabilité → « Clients en double » dans QuickBooks (Steven, 2026-10-18).

« J'ai plusieurs doublons de clients dans plusieurs entreprises, pas
seulement dans Horizon, et je vais devoir utiliser les noms exacts qui se
retrouvent dans QB. »

Intuit n'offre PAS la fusion de clients par API. La vraie fusion (tout
l'historique passe sous une seule fiche, aucun montant ne change) se fait
dans l'écran de QuickBooks : on renomme le doublon au nom d'affichage
EXACT de la fiche gardée et QuickBooks propose de fusionner. Kratos fait
le reste, pour chaque compagnie QuickBooks connectée :

- ``compagnies`` : une entrée par compagnie (realm), et les entreprises
  dont le QuickBooks n'est pas encore connecté ;
- ``analyser`` : doublons probables (même nom, même numéro d'entreprise,
  nom presque identique) et paires à vérifier (même courriel, téléphone
  ou adresse), avec le nom exact de chaque fiche, ce qui bloque la fusion
  (sous-clients, projets) et ce que Kratos y relie ;
- ``apercu`` / ``desactiver`` : une fiche sans vente, paiement ni
  soumission est simplement désactivée par l'API ;
- ``suivre_fusion`` : après la fusion (bouton « C'est fait », ou webhook
  « Merge » d'Intuit), Kratos remet ses liens sur la fiche gardée et
  prend son nom exact. Sans ça le doublon reviendrait : les flux de
  Kratos retrouvent le client QuickBooks par son NOM (``ensure_customer``)
  et la fiche fusionnée n'existe plus sous ce nom.
"""

from __future__ import annotations

import difflib
import logging
import re
import unicodedata
from collections import defaultdict
from datetime import datetime, timezone
from itertools import combinations
from typing import Any, Callable, Dict, Iterable, List, Optional, Set, Tuple

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.integrations.quickbooks import (
    QuickBooksError,
    QuickBooksReconnexionRequise,
    ou_reconnecter,
)
from app.models.client import Client
from app.models.entreprise import Entreprise
from app.models.immobilier import Immeuble
from app.models.qbo_connection import QBO_CONNECTION_SCOPES, QboConnection
from app.models.qbo_monthly_invoice import QboMonthlyInvoice
from app.models.qbo_token import QboToken
from app.models.timesheet import TimesheetCompany

log = logging.getLogger(__name__)

SCOPE_CONSTRUCTION = "construction"
_POLES = {
    "construction": "Construction",
    "entreprise": "Gestion d'entreprise",
    "immobilier": "Immobilier",
}

#: Formes juridiques et articles ignorés pour comparer deux noms
#: (« Les Constructions ABC inc. » = « Constructions ABC »).
_MOTS_IGNORES = frozenset(
    {
        "inc", "incorporee", "incorporated", "ltee", "limitee", "ltd",
        "limited", "llc", "corp", "corporation", "enr", "senc", "sencrl",
        "senrl", "sec", "cie", "co", "le", "la", "les", "the",
    }
)
#: Numéro d'entreprise dans un nom (« 9520-8955 Québec inc. »).
_RE_NUMERO = re.compile(r"(?<!\d)(\d{4})[\s-]?(\d{4})(?!\d)")
#: Suffixe que QuickBooks ajoute au nom d'une fiche désactivée.
_RE_SUPPRIME = re.compile(r"\s*\((?:deleted|supprim[ée]e?s?)\)\s*$", re.IGNORECASE)
#: Au-delà, un courriel, téléphone ou adresse partagé est celui d'un
#: propriétaire ou d'un comptable (plusieurs compagnies), pas un doublon.
MAX_PARTAGE = 4
#: « Nom presque identique » : faute de frappe, lettre ou « s » en trop.
SEUIL_NOM_PROCHE = 0.9
LONGUEUR_MIN_PROCHE = 8
#: Un bloc de comparaison plus gros (même début de nom) est sauté :
#: comparer chaque paire coûterait trop cher pour un gain douteux.
_BLOC_MAX = 300

#: Ce qui fait qu'une fiche n'est pas « vide » : ventes, paiements,
#: soumissions (requêtes ``CustomerRef`` acceptées par QuickBooks).
TYPES_VENTES: Tuple[Tuple[str, str], ...] = (
    ("Invoice", "factures"),
    ("Payment", "paiements"),
    ("CreditMemo", "notes de crédit"),
    ("SalesReceipt", "reçus de vente"),
    ("RefundReceipt", "remboursements"),
    ("Estimate", "soumissions"),
)
_SINGULIERS = {
    "factures": "facture",
    "paiements": "paiement",
    "notes de crédit": "note de crédit",
    "reçus de vente": "reçu de vente",
    "remboursements": "remboursement",
    "soumissions": "soumission",
}


def _compte(n: int, libelle: str) -> str:
    """« 1 facture », « 3 factures »."""
    return f"{n} {_SINGULIERS.get(libelle, libelle) if n == 1 else libelle}"


def _montant(x: float) -> str:
    """« 16 115,64 $ »."""
    return f"{x:,.2f}".replace(",", " ").replace(".", ",") + " $"


class DoublonErreur(Exception):
    def __init__(self, message: str, statut: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.statut = statut


def _motif(exc: Exception) -> str:
    """Motif lisible d'une erreur QuickBooks (« QBO refus : <motif> — »)."""
    msg = str(exc)
    if msg.startswith("QBO refus : "):
        return msg[len("QBO refus : "):].split(" — ", 1)[0].strip()
    return msg[:300]


def _erreur_qb(exc: Exception, scope: str) -> DoublonErreur:
    if isinstance(exc, QuickBooksReconnexionRequise):
        return DoublonErreur(
            f"QuickBooks demande une reconnexion : {ou_reconnecter(scope)}.", 503
        )
    return DoublonErreur(f"QuickBooks a répondu : {_motif(exc)}", 502)


def ou_connecter(scope: str) -> str:
    """Où connecter, dans Kratos, le QuickBooks d'un scope."""
    if scope.startswith("inc:"):
        return (
            "Paramètres → Gestion documentaire Drive → « Reçus QuickBooks → "
            "Drive », bouton « Connecter QuickBooks » de l'entreprise"
        )
    return ou_reconnecter(scope)


def scope_valide(scope: str) -> bool:
    return (
        scope == SCOPE_CONSTRUCTION
        or scope in QBO_CONNECTION_SCOPES
        or bool(re.fullmatch(r"inc:\d{1,10}", scope or ""))
    )


def _hote(environment: Optional[str]) -> str:
    return (
        "https://app.sandbox.qbo.intuit.com"
        if (environment or "").lower() == "sandbox"
        else "https://app.qbo.intuit.com"
    )


def lien_client_qb(
    environment: Optional[str], realm_id: Optional[str], customer_id: Any
) -> str:
    """Fiche du client dans QuickBooks, sur la BONNE compagnie : sans
    ``deeplinkcompanyid``, QuickBooks ouvrirait cet id dans la compagnie
    déjà affichée, où il désigne un autre client."""
    url = f"{_hote(environment)}/app/customerdetail?nameId={customer_id}"
    if realm_id:
        url += f"&deeplinkcompanyid={realm_id}"
    return url


# ──────────────────────────────────────────────────────────────────────
# Compagnies QuickBooks
# ──────────────────────────────────────────────────────────────────────


async def _connexions(db: AsyncSession) -> List[Dict[str, Any]]:
    """Toutes les connexions QuickBooks enregistrées : Construction
    (qbo_tokens id=1, sinon les variables d'env) puis qbo_connections."""
    tok = (
        await db.execute(select(QboToken).where(QboToken.id == 1))
    ).scalar_one_or_none()
    realm = (tok.realm_id if tok else None) or settings.qbo_realm_id
    refresh = (tok.refresh_token if tok else None) or settings.qbo_refresh_token
    out: List[Dict[str, Any]] = [
        {
            "scope": SCOPE_CONSTRUCTION,
            "realm_id": str(realm) if realm else None,
            "environment": (
                (tok.environment if tok else None) or settings.quickbooks_env or ""
            ).lower(),
            "company_name": tok.company_name if tok else None,
            "connectee": bool(realm and refresh),
            "reconnexion_requise": bool(tok and tok.reconnect_required_at),
        }
    ]
    for c in (
        await db.execute(select(QboConnection).order_by(QboConnection.id.asc()))
    ).scalars().all():
        out.append(
            {
                "scope": c.scope,
                "realm_id": str(c.realm_id) if c.realm_id else None,
                "environment": (c.environment or settings.quickbooks_env or "").lower(),
                "company_name": c.company_name,
                "connectee": bool(c.realm_id and c.refresh_token),
                "reconnexion_requise": bool(c.reconnect_required_at),
            }
        )
    return out


async def _realms_des_modules(db: AsyncSession) -> Dict[str, Optional[str]]:
    """Compagnie (realm) de chaque module de Kratos qui garde un lien vers
    un client QuickBooks. Un id client n'a de sens que dans SA compagnie :
    le client 58 d'Horizon n'est pas le client 58 d'une INC."""
    par_scope = {c["scope"]: c for c in await _connexions(db)}

    def realm(scope: str) -> Optional[str]:
        c = par_scope.get(scope)
        return c["realm_id"] if c and c["connectee"] else None

    return {
        # Fiches clients (factures, soumissions, bons, projets) : Construction.
        "clients": realm(SCOPE_CONSTRUCTION),
        # Frais de gestion des immeubles : Immobilier, sinon Entreprise.
        "immeubles": realm("immobilier") or realm("entreprise"),
        # Refacturation des heures (feuille de temps) : Entreprise.
        "feuille_de_temps": realm("entreprise"),
    }


async def compagnies(db: AsyncSession) -> Dict[str, Any]:
    """Une entrée par compagnie QuickBooks connectée (plusieurs pôles ou
    INC peuvent pointer la même), et les entreprises actives dont le
    QuickBooks n'est pas connecté à Kratos."""
    conns = await _connexions(db)
    entreprises = (
        await db.execute(
            select(Entreprise).order_by(Entreprise.position.asc(), Entreprise.id.asc())
        )
    ).scalars().all()
    noms = {e.id: e.name for e in entreprises}
    rang_inc = {f"inc:{e.id}": i for i, e in enumerate(entreprises)}
    par_scope = {c["scope"]: c for c in conns}

    def libelle(scope: str) -> str:
        if scope in _POLES:
            return _POLES[scope]
        m = re.fullmatch(r"inc:(\d+)", scope)
        return noms.get(int(m.group(1)), scope) if m else scope

    def rang(c: Dict[str, Any]) -> Tuple[int, int]:
        s = c["scope"]
        if s in _POLES:
            return (list(_POLES).index(s), 0)
        return (len(_POLES), rang_inc.get(s, 10**6))

    par_realm: Dict[str, Dict[str, Any]] = {}
    for c in sorted(conns, key=rang):
        if not c["connectee"]:
            continue
        e = par_realm.get(c["realm_id"])
        if e is None:
            e = par_realm[c["realm_id"]] = {
                "scope": c["scope"],
                "realm_id": c["realm_id"],
                "nom": (c["company_name"] or "").strip() or libelle(c["scope"]),
                "environment": c["environment"],
                "reconnexion_requise": c["reconnexion_requise"],
                "ou_reconnecter": (
                    ou_reconnecter(c["scope"]) if c["reconnexion_requise"] else None
                ),
                "utilisee_par": [],
            }
        elif e["reconnexion_requise"] and not c["reconnexion_requise"]:
            # Une autre connexion, vivante, vers la même compagnie : on lit par elle.
            e.update(scope=c["scope"], reconnexion_requise=False, ou_reconnecter=None)
        if libelle(c["scope"]) not in e["utilisee_par"]:
            e["utilisee_par"].append(libelle(c["scope"]))

    non_connectees: List[Dict[str, Any]] = []
    for ent in entreprises:
        if not ent.is_active:
            continue
        scope = (ent.qbo_scope or "").strip() or f"inc:{ent.id}"
        c = par_scope.get(scope)
        if c and c["connectee"]:
            e = par_realm.get(c["realm_id"])
            if e is not None and ent.name not in e["utilisee_par"]:
                e["utilisee_par"].append(ent.name)
            continue
        non_connectees.append(
            {"entreprise_id": ent.id, "nom": ent.name, "ou_connecter": ou_connecter(scope)}
        )
    return {"compagnies": list(par_realm.values()), "non_connectees": non_connectees}


async def _client_qb(scope: str) -> Any:
    """Client QuickBooks prêt pour ``scope``, sinon une erreur qui dit où
    le connecter."""
    if not scope_valide(scope):
        raise DoublonErreur("Compagnie QuickBooks inconnue.", 404)
    from app.integrations.quickbooks import get_qbo

    qbo = get_qbo(scope)
    await qbo._load_refresh_from_db()  # noqa: SLF001
    if not qbo.ready:
        raise DoublonErreur(
            f"Ce QuickBooks n'est pas connecté à Kratos : {ou_connecter(scope)}.", 503
        )
    return qbo


# ──────────────────────────────────────────────────────────────────────
# Regroupement des doublons (fonctions pures)
# ──────────────────────────────────────────────────────────────────────


def _sans_accents(s: str) -> str:
    base = unicodedata.normalize("NFKD", s or "")
    return "".join(c for c in base if not unicodedata.combining(c))


def normaliser_nom(nom: Optional[str]) -> str:
    """Minuscules, sans accents, « & » = « et », sans ponctuation
    (« S.E.N.C. » = « senc »)."""
    s = _sans_accents(nom or "").lower().replace("&", " et ").replace(".", "")
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def cle_nom(nom: Optional[str]) -> str:
    """Clé de comparaison d'un nom : ses mots, sans formes juridiques ni
    articles, en ordre alphabétique (« Tremblay, Jean » = « Jean
    Tremblay », « 9520-8955 Québec inc. » = « 9520-8955 Quebec Inc »)."""
    mots = normaliser_nom(nom).split()
    utiles = [m for m in mots if m not in _MOTS_IGNORES]
    return " ".join(sorted(utiles or mots))


def numeros(*textes: Optional[str]) -> Set[str]:
    """Numéros d'entreprise (« 9520-8955 ») présents dans les textes."""
    return {f"{a}-{b}" for t in textes for a, b in _RE_NUMERO.findall(t or "")}


def sans_suffixe_supprime(nom: Optional[str]) -> str:
    """Nom d'une fiche désactivée sans le « (deleted) » de QuickBooks."""
    return _RE_SUPPRIME.sub("", nom or "").strip()


def _courriels(row: Dict[str, Any]) -> Set[str]:
    brut = (row.get("PrimaryEmailAddr") or {}).get("Address") or ""
    return {a.strip().lower() for a in re.split(r"[,;\s]+", brut) if "@" in a}


def _telephones(row: Dict[str, Any]) -> Set[str]:
    out: Set[str] = set()
    for champ in ("PrimaryPhone", "Mobile"):
        chiffres = re.sub(r"\D", "", (row.get(champ) or {}).get("FreeFormNumber") or "")
        if len(chiffres) == 11 and chiffres.startswith("1"):
            chiffres = chiffres[1:]
        if len(chiffres) == 10:
            out.add(chiffres)
    return out


def _tel_lisible(chiffres: str) -> str:
    return f"{chiffres[:3]} {chiffres[3:6]}-{chiffres[6:]}"


def _adresse(row: Dict[str, Any]) -> Optional[Tuple[str, str]]:
    """(clé, libellé) de l'adresse de facturation : numéro civique + code
    postal (sinon ville, sinon la ligne entière). None sans numéro."""
    addr = row.get("BillAddr") or {}
    ligne = str(addr.get("Line1") or "").strip()
    civique = re.match(r"\s*(\d+)", ligne)
    if not civique:
        return None
    postal = re.sub(r"\s", "", str(addr.get("PostalCode") or "")).upper()
    ville = normaliser_nom(addr.get("City"))
    suite = postal or ville or normaliser_nom(ligne)
    return f"{civique.group(1)}|{suite}", ligne


def _parent_id(row: Dict[str, Any]) -> str:
    return str((row.get("ParentRef") or {}).get("value") or "")


def _uniques(valeurs: Iterable[str]) -> List[str]:
    vus: List[str] = []
    for v in valeurs:
        if v not in vus:
            vus.append(v)
    return vus


class _Ensembles:
    """Union-find : deux fiches reliées, même de proche en proche, sont
    dans le même groupe."""

    def __init__(self, n: int) -> None:
        self.p = list(range(n))

    def racine(self, i: int) -> int:
        while self.p[i] != i:
            self.p[i] = self.p[self.p[i]]
            i = self.p[i]
        return i

    def unir(self, a: int, b: int) -> None:
        ra, rb = self.racine(a), self.racine(b)
        if ra != rb:
            self.p[max(ra, rb)] = min(ra, rb)


def regrouper(
    rows: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """(doublons probables, paires à vérifier) parmi les clients
    PRINCIPAUX : un sous-client ou un projet suit son parent et bloque la
    fusion, il n'en est pas un doublon. Chaque entrée : ``ids`` (Id
    QuickBooks, du plus ancien au plus récent) et ``raisons``."""
    principaux = [r for r in rows if r.get("Id") and not _parent_id(r)]
    principaux.sort(
        key=lambda r: (str((r.get("MetaData") or {}).get("CreateTime") or ""), str(r["Id"]))
    )
    n = len(principaux)
    ens = _Ensembles(n)
    fortes: List[Tuple[int, str]] = []  # (une fiche du lien, raison)

    def relier(cles: Dict[str, List[int]], libelle: Callable[[str], str]) -> None:
        for cle, idx in cles.items():
            idx = sorted(set(idx))
            for j in idx[1:]:
                ens.unir(idx[0], j)
                fortes.append((idx[0], libelle(cle)))

    # 1) Même nom : nom d'affichage ou nom de compagnie.
    par_nom: Dict[str, List[int]] = defaultdict(list)
    for i, r in enumerate(principaux):
        for k in {cle_nom(r.get("DisplayName")), cle_nom(r.get("CompanyName"))}:
            if k:
                par_nom[k].append(i)
    relier(par_nom, lambda _k: "même nom")

    # 2) Même numéro d'entreprise (« 9520-8955 Québec inc. » et
    #    « 9520-8955 Millen & Legendre »).
    par_num: Dict[str, List[int]] = defaultdict(list)
    for i, r in enumerate(principaux):
        for num in numeros(r.get("DisplayName"), r.get("CompanyName")):
            par_num[num].append(i)
    relier(par_num, lambda k: f"même numéro d'entreprise ({k})")

    # 3) Nom presque identique. Comparé par blocs (même début ou même fin
    #    de clé) ; jamais deux noms dont les chiffres diffèrent (deux
    #    compagnies à numéro, deux adresses voisines).
    cles = [cle_nom(r.get("DisplayName")) for r in principaux]
    blocs: Dict[str, List[int]] = defaultdict(list)
    for i, k in enumerate(cles):
        if len(k) >= LONGUEUR_MIN_PROCHE:
            blocs["d" + k[:3]].append(i)
            blocs["f" + k[-3:]].append(i)
    deja: Set[Tuple[int, int]] = set()
    for idx in blocs.values():
        if len(idx) > _BLOC_MAX:
            continue
        for a, b in combinations(idx, 2):
            if (a, b) in deja or ens.racine(a) == ens.racine(b):
                continue
            deja.add((a, b))
            ka, kb = cles[a], cles[b]
            if re.findall(r"\d+", ka) != re.findall(r"\d+", kb):
                continue
            sm = difflib.SequenceMatcher(None, ka, kb)
            if (
                sm.real_quick_ratio() >= SEUIL_NOM_PROCHE
                and sm.quick_ratio() >= SEUIL_NOM_PROCHE
                and sm.ratio() >= SEUIL_NOM_PROCHE
            ):
                ens.unir(a, b)
                fortes.append((a, "nom presque identique"))

    # Signaux plus faibles : même courriel, téléphone, adresse.
    faibles: Dict[Tuple[int, int], List[str]] = defaultdict(list)

    def signaler(cles_: Dict[str, List[int]], libelle: Callable[[str], str]) -> None:
        for cle, idx in cles_.items():
            idx = sorted(set(idx))
            if not 2 <= len(idx) <= MAX_PARTAGE:
                continue
            for a, b in combinations(idx, 2):
                faibles[(a, b)].append(libelle(cle))

    par_courriel: Dict[str, List[int]] = defaultdict(list)
    par_tel: Dict[str, List[int]] = defaultdict(list)
    par_adresse: Dict[str, List[int]] = defaultdict(list)
    libelles_adresse: Dict[str, str] = {}
    for i, r in enumerate(principaux):
        for c in _courriels(r):
            par_courriel[c].append(i)
        for t in _telephones(r):
            par_tel[t].append(i)
        adr = _adresse(r)
        if adr:
            par_adresse[adr[0]].append(i)
            libelles_adresse.setdefault(adr[0], adr[1])
    signaler(par_courriel, lambda k: f"même courriel ({k})")
    signaler(par_tel, lambda k: f"même téléphone ({_tel_lisible(k)})")
    signaler(par_adresse, lambda k: f"même adresse ({libelles_adresse[k]})")

    membres: Dict[int, List[int]] = defaultdict(list)
    for i in range(n):
        membres[ens.racine(i)].append(i)
    raisons: Dict[int, List[str]] = defaultdict(list)
    for i, lib in fortes:
        raisons[ens.racine(i)].append(lib)
    a_verifier: List[Dict[str, Any]] = []
    for (a, b), libs in sorted(faibles.items()):
        ra = ens.racine(a)
        if ra == ens.racine(b):
            # Dans un même groupe probable : la raison le renforce.
            raisons[ra].extend(libs)
        else:
            a_verifier.append(
                {"ids": [str(principaux[a]["Id"]), str(principaux[b]["Id"])], "raisons": _uniques(libs)}
            )
    groupes = [
        {"ids": [str(principaux[i]["Id"]) for i in idx], "raisons": _uniques(raisons[r])}
        for r, idx in membres.items()
        if len(idx) >= 2
    ]
    return groupes, a_verifier


# ──────────────────────────────────────────────────────────────────────
# Analyse d'une compagnie
# ──────────────────────────────────────────────────────────────────────


def _fiche(row: Dict[str, Any], *, environment: str, realm_id: str) -> Dict[str, Any]:
    addr = row.get("BillAddr") or {}
    adresse = ", ".join(
        str(p).strip()
        for p in (addr.get("Line1"), addr.get("City"), addr.get("PostalCode"))
        if p and str(p).strip()
    )
    solde = row.get("BalanceWithJobs")
    if solde is None:
        solde = row.get("Balance")
    try:
        solde = round(float(solde or 0), 2)
    except (TypeError, ValueError):
        solde = 0.0
    tel = (row.get("PrimaryPhone") or {}).get("FreeFormNumber") or (
        row.get("Mobile") or {}
    ).get("FreeFormNumber")
    personne = " ".join(
        str(p).strip() for p in (row.get("GivenName"), row.get("FamilyName")) if p
    )
    return {
        "id": str(row.get("Id")),
        # Nom EXACT de QuickBooks : c'est lui qu'on colle pour fusionner.
        "nom": row.get("DisplayName") or "",
        "compagnie": (row.get("CompanyName") or "").strip() or None,
        "personne": personne or None,
        "courriel": (row.get("PrimaryEmailAddr") or {}).get("Address") or None,
        "telephone": tel or None,
        "adresse": adresse or None,
        "solde": solde,
        "actif": bool(row.get("Active", True)),
        "cree_le": str((row.get("MetaData") or {}).get("CreateTime") or "")[:10] or None,
        "sous_clients": [],
        "kratos": [],
        "lien_qb": lien_client_qb(environment, realm_id, row.get("Id")),
    }


def _ajouter_sous_clients(
    fiches: Dict[str, Dict[str, Any]], rows: List[Dict[str, Any]]
) -> None:
    """Sous-clients et projets de chaque fiche : QuickBooks refuse de
    fusionner une fiche qui en porte (il faut les détacher d'abord)."""
    for r in rows:
        f = fiches.get(_parent_id(r))
        if f is not None:
            f["sous_clients"].append(
                {
                    "id": str(r.get("Id")),
                    "nom": r.get("DisplayName") or "",
                    "projet": bool(r.get("IsProject")),
                }
            )


async def _relier_kratos(
    db: AsyncSession, realm_id: Optional[str], fiches: Dict[str, Dict[str, Any]]
) -> None:
    """Ce que Kratos relie à chaque fiche, dans CETTE compagnie."""
    if not fiches or not realm_id:
        return
    realms = await _realms_des_modules(db)
    ids = list(fiches)
    par_nom: Dict[str, str] = {}
    for fid, f in fiches.items():
        k = (f["nom"] or "").strip().lower()
        if k:
            par_nom.setdefault(k, fid)

    def ajouter(fid: str, ref: Dict[str, Any]) -> None:
        fiches[fid]["kratos"].append(ref)

    if realm_id == realms["clients"]:
        rows = (
            await db.execute(
                select(Client.id, Client.name, Client.qbo_customer_id).where(
                    or_(
                        Client.qbo_customer_id.in_(ids),
                        func.lower(func.trim(Client.name)).in_(list(par_nom)),
                    )
                )
            )
        ).all()
        for cid, nom, lien in rows:
            lien = (lien or "").strip()
            if lien in fiches:
                ajouter(lien, {"type": "client", "id": cid, "nom": nom, "detail": "fiche client Kratos"})
            elif not lien and par_nom.get((nom or "").strip().lower()):
                ajouter(
                    par_nom[(nom or "").strip().lower()],
                    {
                        "type": "client",
                        "id": cid,
                        "nom": nom,
                        "detail": "fiche client Kratos du même nom, pas encore reliée",
                    },
                )
    if realm_id == realms["immeubles"]:
        for iid, nom, lien in (
            await db.execute(
                select(Immeuble.id, Immeuble.name, Immeuble.qbo_customer_id).where(
                    Immeuble.qbo_customer_id.in_(ids)
                )
            )
        ).all():
            ajouter(str(lien), {"type": "immeuble", "id": iid, "nom": nom, "detail": "immeuble, frais de gestion"})
    if realm_id == realms["feuille_de_temps"]:
        for tid, label, lien in (
            await db.execute(
                select(
                    TimesheetCompany.id, TimesheetCompany.label, TimesheetCompany.qbo_customer_id
                ).where(
                    or_(
                        TimesheetCompany.qbo_customer_id.in_(ids),
                        and_(
                            TimesheetCompany.qbo_customer_id.is_(None),
                            func.lower(func.trim(TimesheetCompany.label)).in_(list(par_nom)),
                        ),
                    )
                )
            )
        ).all():
            lien = (lien or "").strip()
            if lien in fiches:
                ajouter(lien, {"type": "feuille_de_temps", "id": tid, "nom": label, "detail": "compagnie de la feuille de temps"})
            elif not lien and par_nom.get((label or "").strip().lower()):
                ajouter(
                    par_nom[(label or "").strip().lower()],
                    {
                        "type": "feuille_de_temps",
                        "id": tid,
                        "nom": label,
                        "detail": "compagnie de la feuille de temps (client retrouvé par son nom)",
                    },
                )


def _groupe(
    entree: Dict[str, Any], fiches: Dict[str, Dict[str, Any]]
) -> Dict[str, Any]:
    membres = [fiches[i] for i in entree["ids"] if i in fiches]
    return {
        "cle": "-".join(sorted(entree["ids"])),
        "raisons": entree["raisons"],
        "fiches": membres,
        # Suggestion : la plus ancienne (les ids arrivent dans cet ordre).
        "suggestion": membres[0]["id"] if membres else None,
    }


async def _noms_kratos_differents(
    db: AsyncSession, rows: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Fiches clients Kratos reliées à un client QuickBooks qui porte un
    autre nom. Kratos retrouve le client QuickBooks par son NOM à chaque
    facture : un nom différent peut faire créer un doublon."""
    par_id = {str(r.get("Id")): r for r in rows}
    out: List[Dict[str, Any]] = []
    for cid, nom, lien in (
        await db.execute(
            select(Client.id, Client.name, Client.qbo_customer_id).where(
                Client.qbo_customer_id.is_not(None)
            )
        )
    ).all():
        r = par_id.get(str(lien).strip())
        if r is None:
            continue
        qb = r.get("DisplayName") or ""
        if (nom or "").strip() != qb.strip():
            out.append(
                {"client_id": cid, "nom_kratos": nom, "nom_quickbooks": qb, "qbo_customer_id": str(lien)}
            )
    out.sort(key=lambda d: (d["nom_kratos"] or "").lower())
    return out


async def _lire_clients(qbo: Any, scope: str) -> List[Dict[str, Any]]:
    try:
        return await qbo.query_all("SELECT * FROM Customer")
    except QuickBooksError as exc:
        raise _erreur_qb(exc, scope) from exc


async def analyser(db: AsyncSession, scope: str) -> Dict[str, Any]:
    """Doublons probables et paires à vérifier d'une compagnie."""
    qbo = await _client_qb(scope)
    realm = str(qbo.realm_id or "")
    rows = await _lire_clients(qbo, scope)
    groupes, paires = regrouper(rows)
    utiles = {i for g in groupes + paires for i in g["ids"]}
    fiches = {
        str(r.get("Id")): _fiche(r, environment=qbo.env, realm_id=realm)
        for r in rows
        if str(r.get("Id")) in utiles
    }
    _ajouter_sous_clients(fiches, rows)
    await _relier_kratos(db, realm, fiches)
    realms = await _realms_des_modules(db)
    principaux = sorted(
        ({"id": str(r.get("Id")), "nom": r.get("DisplayName") or ""} for r in rows if not _parent_id(r)),
        key=lambda c: c["nom"].lower(),
    )
    sortie_groupes = [_groupe(g, fiches) for g in groupes]
    sortie_groupes.sort(key=lambda g: (g["fiches"][0]["nom"] if g["fiches"] else "").lower())
    return {
        "scope": scope,
        "realm_id": realm,
        "clients_lus": len(principaux),
        "groupes": sortie_groupes,
        "a_verifier": [_groupe(p, fiches) for p in paires],
        "clients": principaux,
        "noms_kratos": (
            await _noms_kratos_differents(db, rows) if realm and realm == realms["clients"] else []
        ),
    }


async def groupe_choisi(db: AsyncSession, scope: str, ids: List[str]) -> Dict[str, Any]:
    """Deux fiches (ou plus) choisies à la main : même présentation qu'un
    groupe détecté (« 9520 » et « Millen » n'ont rien en commun pour la
    détection, Steven les sait identiques)."""
    ids = _uniques(str(i).strip() for i in ids if str(i).strip())
    if len(ids) < 2:
        raise DoublonErreur("Choisis deux clients différents.", 422)
    qbo = await _client_qb(scope)
    realm = str(qbo.realm_id or "")
    rows = await _lire_clients(qbo, scope)
    par_id = {str(r.get("Id")): r for r in rows}
    manquants = [i for i in ids if i not in par_id]
    if manquants:
        raise DoublonErreur("Client introuvable dans QuickBooks (inactif ou supprimé).", 404)
    ordre = sorted(
        ids, key=lambda i: (str((par_id[i].get("MetaData") or {}).get("CreateTime") or ""), i)
    )
    fiches = {i: _fiche(par_id[i], environment=qbo.env, realm_id=realm) for i in ordre}
    _ajouter_sous_clients(fiches, rows)
    await _relier_kratos(db, realm, fiches)
    return _groupe({"ids": ordre, "raisons": ["choisis à la main"]}, fiches)


# ──────────────────────────────────────────────────────────────────────
# Fiche vide → désactivation par l'API
# ──────────────────────────────────────────────────────────────────────


async def _apercu(qbo: Any, scope: str, customer_id: str) -> Dict[str, Any]:
    safe = str(customer_id).replace("'", "''")
    try:
        cust = await qbo.read_customer(customer_id)
    except QuickBooksError as exc:
        raise _erreur_qb(exc, scope) from exc
    if not cust:
        raise DoublonErreur("Client introuvable dans QuickBooks.", 404)
    compteurs: Dict[str, int] = {}
    inconnus: List[str] = []
    for entite, libelle in TYPES_VENTES:
        try:
            compteurs[libelle] = await qbo.count(
                f"SELECT COUNT(*) FROM {entite} WHERE CustomerRef = '{safe}'"
            )
        except QuickBooksReconnexionRequise as exc:
            raise _erreur_qb(exc, scope) from exc
        except QuickBooksError:
            inconnus.append(libelle)
    rows = await _lire_clients(qbo, scope)
    enfants = [
        {"id": str(r.get("Id")), "nom": r.get("DisplayName") or "", "projet": bool(r.get("IsProject"))}
        for r in rows
        if _parent_id(r) == str(customer_id)
    ]
    try:
        solde = round(float(cust.get("BalanceWithJobs", cust.get("Balance")) or 0), 2)
    except (TypeError, ValueError):
        solde = 0.0
    actif = bool(cust.get("Active", True))
    return {
        "id": str(cust.get("Id")),
        "nom": cust.get("DisplayName") or "",
        "actif": actif,
        "solde": solde,
        "compteurs": compteurs,
        "inconnus": inconnus,
        "sous_clients": enfants,
        # Vide = rien à déplacer : la désactiver revient à la fusionner.
        "vide": actif
        and not inconnus
        and not enfants
        and abs(solde) < 0.005
        and all(v == 0 for v in compteurs.values()),
    }


async def apercu(db: AsyncSession, scope: str, customer_id: str) -> Dict[str, Any]:
    """Ce que porte une fiche : ventes, paiements, soumissions, solde,
    sous-clients. ``vide`` : Kratos peut la désactiver lui-même."""
    qbo = await _client_qb(scope)
    return await _apercu(qbo, scope, customer_id)


async def _lire_actif(qbo: Any, scope: str, customer_id: str) -> Optional[Dict[str, Any]]:
    """La fiche si elle est encore active dans QuickBooks, sinon None."""
    try:
        cust = await qbo.read_customer(customer_id)
    except QuickBooksError as exc:
        raise _erreur_qb(exc, scope) from exc
    return cust if cust and cust.get("Active", True) else None


async def desactiver(
    db: AsyncSession,
    scope: str,
    *,
    source_id: str,
    cible_id: str,
    nom_source: Optional[str] = None,
) -> Dict[str, Any]:
    """Désactive par l'API une fiche VIDE (rien à déplacer), puis Kratos
    suit comme pour une fusion. Une fiche qui porte quoi que ce soit se
    fusionne dans QuickBooks : la désactiver laisserait son historique à
    part."""
    if str(source_id) == str(cible_id):
        raise DoublonErreur("La fiche à garder et le doublon sont la même fiche.", 422)
    qbo = await _client_qb(scope)
    cible = await _lire_actif(qbo, scope, cible_id)
    if cible is None:
        raise DoublonErreur("La fiche à garder n'est plus active dans QuickBooks.", 409)
    ap = await _apercu(qbo, scope, source_id)
    if not ap["vide"]:
        porte = [_compte(n, lib) for lib, n in ap["compteurs"].items() if n]
        if ap["sous_clients"]:
            porte.append(f"{len(ap['sous_clients'])} sous-client(s) ou projet(s)")
        if abs(ap["solde"]) >= 0.005:
            porte.append(f"un solde de {_montant(ap['solde'])}")
        if ap["inconnus"]:
            porte.append("des transactions que Kratos n'a pas pu compter")
        if not ap["actif"]:
            porte = ["elle est déjà inactive"]
        raise DoublonErreur(
            f"« {ap['nom']} » n'est pas vide ({', '.join(porte)}) : fusionne-la "
            "dans QuickBooks pour que son historique passe sous la fiche gardée.",
            409,
        )
    try:
        await qbo.deactivate_customer(source_id)
    except QuickBooksError as exc:
        raise _erreur_qb(exc, scope) from exc
    suivi = await suivre_fusion(
        db,
        realm_id=str(qbo.realm_id or ""),
        source_id=str(source_id),
        cible_id=str(cible_id),
        nom_source=nom_source or ap["nom"],
        nom_cible=cible.get("DisplayName") or "",
    )
    return {"desactivee": True, **suivi}


# ──────────────────────────────────────────────────────────────────────
# Après la fusion : Kratos suit
# ──────────────────────────────────────────────────────────────────────


async def fusion_faite(
    db: AsyncSession,
    scope: str,
    *,
    source_id: str,
    cible_id: str,
    nom_source: Optional[str] = None,
) -> Dict[str, Any]:
    """Bouton « C'est fait » : constate dans QuickBooks que le doublon a
    disparu (inactif) et que la fiche gardée est active, puis remet les
    liens de Kratos sur la fiche gardée. Une fusion faite dans l'autre
    sens est suivie dans ce sens-là."""
    if str(source_id) == str(cible_id):
        raise DoublonErreur("La fiche à garder et le doublon sont la même fiche.", 422)
    qbo = await _client_qb(scope)
    source = await _lire_actif(qbo, scope, source_id)
    cible = await _lire_actif(qbo, scope, cible_id)
    sens_inverse = False
    if source is not None and cible is not None:
        raise DoublonErreur(
            f"La fusion n'est pas encore faite : « {source.get('DisplayName')} » est "
            "toujours active dans QuickBooks. Ouvre-la, Modifier, remplace le nom "
            f"d'affichage par « {cible.get('DisplayName')} », Enregistrer, puis Oui.",
            409,
        )
    if source is None and cible is None:
        raise DoublonErreur(
            "Les deux fiches sont inactives dans QuickBooks : réactive celle à garder.",
            409,
        )
    if cible is None:
        # Le nom a été changé dans l'autre sens : c'est la « source » qui reste.
        sens_inverse = True
        source_id, cible_id, cible = cible_id, source_id, source
        nom_source = None
    if not nom_source:
        try:
            ancienne = await qbo.read_customer(source_id)
        except QuickBooksError:
            ancienne = None
        nom_source = sans_suffixe_supprime((ancienne or {}).get("DisplayName"))
    suivi = await suivre_fusion(
        db,
        realm_id=str(qbo.realm_id or ""),
        source_id=str(source_id),
        cible_id=str(cible_id),
        nom_source=nom_source,
        nom_cible=cible.get("DisplayName") or "",
    )
    return {"sens_inverse": sens_inverse, **suivi}


async def suivre_fusion(
    db: AsyncSession,
    *,
    realm_id: str,
    source_id: str,
    cible_id: str,
    nom_source: Optional[str],
    nom_cible: str,
) -> Dict[str, Any]:
    """Remet sur la fiche gardée (``cible_id``) tout ce que Kratos reliait
    au doublon disparu (``source_id``), dans cette compagnie : fiches
    clients (lien + nom exact), immeubles (frais de gestion), compagnies
    de la feuille de temps, factures mensuelles ouvertes. Idempotent.

    Les fiches et compagnies SANS lien qui portent le nom du doublon sont
    reliées aussi : elles retrouvaient leur client QuickBooks par ce nom,
    qui n'existe plus."""
    realms = await _realms_des_modules(db)
    nom_src = sans_suffixe_supprime(nom_source).lower()
    clients: List[str] = []
    immeubles: List[str] = []
    compagnies_ft: List[str] = []
    avertissements: List[str] = []
    factures_mensuelles = 0

    if realm_id and realm_id == realms["clients"]:
        conds = [Client.qbo_customer_id == source_id]
        if nom_src:
            conds.append(func.lower(func.trim(Client.name)) == nom_src)
        for cl in (await db.execute(select(Client).where(or_(*conds)))).scalars().all():
            lien = (cl.qbo_customer_id or "").strip()
            if lien and lien not in (source_id, cible_id):
                avertissements.append(
                    f"La fiche client Kratos « {cl.name} » porte le nom du doublon mais "
                    "est reliée à un autre client QuickBooks : laissée telle quelle."
                )
                continue
            cl.qbo_customer_id = cible_id
            if nom_cible and cl.name != nom_cible:
                cl.name = nom_cible[:255]
            clients.append(cl.name)
        if clients:
            await db.flush()
            lies = (
                await db.execute(select(Client.id).where(Client.qbo_customer_id == cible_id))
            ).scalars().all()
            if len(lies) > 1:
                avertissements.append(
                    f"Kratos a maintenant {len(lies)} fiches clients pour « {nom_cible} » : "
                    "leurs projets et factures restent sur chacune."
                )

    if realm_id and realm_id == realms["immeubles"]:
        for imm in (
            await db.execute(select(Immeuble).where(Immeuble.qbo_customer_id == source_id))
        ).scalars().all():
            imm.qbo_customer_id = cible_id
            imm.qbo_customer_name = nom_cible[:255] or None
            immeubles.append(imm.name)

    if realm_id and realm_id == realms["feuille_de_temps"]:
        conds = [TimesheetCompany.qbo_customer_id == source_id]
        if nom_src:
            conds.append(
                and_(
                    TimesheetCompany.qbo_customer_id.is_(None),
                    func.lower(func.trim(TimesheetCompany.label)) == nom_src,
                )
            )
        for comp in (
            await db.execute(select(TimesheetCompany).where(or_(*conds)))
        ).scalars().all():
            comp.qbo_customer_id = cible_id
            comp.qbo_customer_name = nom_cible[:255] or None
            compagnies_ft.append(comp.label)

    if realm_id:
        maintenant = datetime.now(timezone.utc)
        for fm in (
            await db.execute(
                select(QboMonthlyInvoice).where(
                    QboMonthlyInvoice.realm_id == realm_id,
                    QboMonthlyInvoice.qbo_customer_id == source_id,
                )
            )
        ).scalars().all():
            deja = (
                await db.execute(
                    select(QboMonthlyInvoice.id).where(
                        QboMonthlyInvoice.realm_id == realm_id,
                        QboMonthlyInvoice.qbo_customer_id == cible_id,
                        QboMonthlyInvoice.mois == fm.mois,
                    )
                )
            ).scalar_one_or_none()
            if deja is not None:
                # La fiche gardée a déjà sa facture du mois : les prochaines
                # lignes y vont ; celle du doublon reste dans QuickBooks.
                await db.delete(fm)
            else:
                fm.qbo_customer_id = cible_id
                fm.updated_at = maintenant
            factures_mensuelles += 1

    await db.flush()
    log.info(
        "Fusion QuickBooks suivie (realm %s) : %s → %s, %d client(s), %d immeuble(s), "
        "%d compagnie(s), %d facture(s) mensuelle(s)",
        realm_id, source_id, cible_id, len(clients), len(immeubles),
        len(compagnies_ft), factures_mensuelles,
    )
    return {
        "source": {"id": source_id, "nom": sans_suffixe_supprime(nom_source) or None},
        "cible": {"id": cible_id, "nom": nom_cible},
        "clients_kratos": clients,
        "immeubles": immeubles,
        "compagnies_feuille_de_temps": compagnies_ft,
        "factures_mensuelles": factures_mensuelles,
        "avertissements": avertissements,
    }


async def suivre_fusion_webhook(
    db: AsyncSession, *, realm_id: str, source_id: str, cible_id: str
) -> Dict[str, Any]:
    """Webhook Intuit « Merge » d'un client (``deletedId`` → ``id``),
    pour n'importe quelle compagnie connectée : même suivi que le bouton
    « C'est fait », les noms relus dans QuickBooks."""
    scope = next(
        (
            c["scope"]
            for c in await _connexions(db)
            if c["connectee"] and c["realm_id"] == str(realm_id)
        ),
        None,
    )
    if scope is None:
        return {"ignore": "compagnie non connectée"}
    from app.integrations.quickbooks import get_qbo

    qbo = get_qbo(scope)
    await qbo._load_refresh_from_db()  # noqa: SLF001
    cible = await qbo.read_customer(cible_id)
    source = await qbo.read_customer(source_id)
    return await suivre_fusion(
        db,
        realm_id=str(realm_id),
        source_id=str(source_id),
        cible_id=str(cible_id),
        nom_source=sans_suffixe_supprime((source or {}).get("DisplayName")),
        nom_cible=(cible or {}).get("DisplayName") or "",
    )


async def aligner_nom_kratos(db: AsyncSession, client_id: int) -> Dict[str, Any]:
    """« Prendre le nom QuickBooks » : la fiche client Kratos prend le nom
    d'affichage exact de son client QuickBooks (Construction). Rien n'est
    renvoyé à QuickBooks, qui a déjà ce nom."""
    cl = await db.get(Client, client_id)
    if cl is None or not cl.qbo_customer_id:
        raise DoublonErreur("Fiche client introuvable ou pas reliée à QuickBooks.", 404)
    qbo = await _client_qb(SCOPE_CONSTRUCTION)
    cust = await _lire_actif(qbo, SCOPE_CONSTRUCTION, cl.qbo_customer_id)
    if cust is None:
        raise DoublonErreur("Le client QuickBooks relié n'est plus actif.", 409)
    ancien = cl.name
    cl.name = (cust.get("DisplayName") or cl.name)[:255]
    await db.flush()
    return {"client_id": cl.id, "ancien_nom": ancien, "nom": cl.name}
