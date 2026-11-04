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
- nom déjà porté par une autre fiche, active ou non — client, mais
  aussi fournisseur ou employé, QuickBooks exigeant un nom d'affichage
  unique entre les trois → 409 (QuickBooks le refuserait avec un message
  obscur) ; même vérification à la réactivation, QuickBooks retirant
  alors le suffixe « (supprimé) » ;
- parent introuvable, inactif, projet QuickBooks (un projet n'a pas de
  sous-clients), la fiche elle-même ou un de ses propres sous-clients
  → 422 ; plus de cinq niveaux → 422 ;
- rendre inactive une fiche qui a des sous-clients actifs, un solde, ou
  que Kratos utilise (client, projet, immeuble, compagnie de la feuille
  de temps) → 409 sauf ``forcer`` (QuickBooks désactive les sous-clients
  avec leur parent et refuse un solde non nul) ;
- ``simuler`` : tout est validé et décrit, rien n'est écrit.

Chaque modification est UNE mise à jour « sparse » sur le SyncToken relu
(exigence QuickBooks), journalisée par le journal automatique des
écritures (``audit_middleware``, simulation comprise, le corps masqué
montrant ``simuler``) ; la réponse rend la fiche avant et après. Rien
n'est copié en base : QuickBooks reste la seule source ; les liens de
Kratos vers la fiche (``liens_kratos``) sont seulement LUS.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from datetime import date, timedelta
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

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

#: Erreurs de l'intégration QuickBooks à traduire en réponse HTTP :
#: refus d'Intuit, reconnexion requise, ou connexion non configurée
#: (``RuntimeError`` de ``QuickBooksClient._refresh``).
_ERREURS_QB: Tuple[type, ...] = (qbo_mod.QuickBooksError, RuntimeError)


class ClientQboErreur(Exception):
    """Erreur à renvoyer telle quelle au client HTTP (statut + détail).
    ``detail`` est TOUJOURS un objet ``{"message": …, …}``."""

    def __init__(self, statut: int, message: str, **extra: Any) -> None:
        super().__init__(message)
        self.statut = statut
        self.message = message
        self.extra = extra

    @property
    def detail(self) -> Dict[str, Any]:
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
    ou = qbo_mod.ou_reconnecter(compagnie)
    if isinstance(exc, RuntimeError):
        return ClientQboErreur(
            503,
            f"QuickBooks ({compagnie}) n'est pas connecté à Kratos : "
            f"{_motif(exc)}. Pour connecter : {ou}.",
        )
    if isinstance(exc, qbo_mod.QuickBooksReconnexionRequise):
        return ClientQboErreur(
            503,
            f"QuickBooks ({compagnie}) demande une reconnexion : "
            f"{_motif(exc)}. {ou}.",
        )
    return ClientQboErreur(
        502,
        f"QuickBooks ({compagnie}) a refusé : {_motif(exc)}. Au besoin : {ou}.",
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
    except _ERREURS_QB as exc:
        raise _erreur_qb(exc, compagnie)
    return [r for r in rows if isinstance(r, dict) and r.get("Id") is not None]


async def _fiche_courante(
    qbo: Any, compagnie: str, customer_id: str, par_id: Dict[str, Dict[str, Any]]
) -> Dict[str, Any]:
    row = par_id.get(customer_id)
    if row is None:
        try:
            row = await qbo.get_customer_any(customer_id)
        except _ERREURS_QB as exc:
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


def _descendants(par_id: Dict[str, Dict[str, Any]], customer_id: str) -> List[str]:
    """Ids de tous les sous-clients, à tous les niveaux (sans boucle)."""
    out: List[str] = []
    vus: Set[str] = {customer_id}
    a_voir = [customer_id]
    while a_voir:
        cur = a_voir.pop()
        for i, r in par_id.items():
            if parent_de(r) == cur and i not in vus:
                vus.add(i)
                out.append(i)
                a_voir.append(i)
    return out


async def liens_kratos(
    db: Optional[AsyncSession], customer_id: str
) -> Optional[Dict[str, Any]]:
    """Ce que Kratos relie à ce client QuickBooks : fiches clients
    (``qbo_customer_id``), projets (sous-client ``qbo_job_id``),
    immeubles, compagnies de la feuille de temps, factures mensuelles.
    ``None`` sans session (lien non consulté)."""
    if db is None:
        return None
    from app.models.client import Client
    from app.models.immobilier import Immeuble
    from app.models.project import Project
    from app.models.qbo_monthly_invoice import QboMonthlyInvoice
    from app.models.timesheet import TimesheetCompany

    cid = str(customer_id)
    clients = (
        await db.execute(
            select(Client.id, Client.name)
            .where(Client.qbo_customer_id == cid)
            .order_by(Client.id)
        )
    ).all()
    projets = (
        await db.execute(
            select(Project.id, Project.name)
            .where(Project.qbo_job_id == cid)
            .order_by(Project.id)
        )
    ).all()
    immeubles = (
        await db.execute(
            select(Immeuble.id, Immeuble.name)
            .where(Immeuble.qbo_customer_id == cid)
            .order_by(Immeuble.id)
        )
    ).all()
    compagnies = (
        await db.execute(
            select(TimesheetCompany.id, TimesheetCompany.label)
            .where(TimesheetCompany.qbo_customer_id == cid)
            .order_by(TimesheetCompany.id)
        )
    ).all()
    factures_mensuelles = (
        await db.execute(
            select(func.count())
            .select_from(QboMonthlyInvoice)
            .where(QboMonthlyInvoice.qbo_customer_id == cid)
        )
    ).scalar_one()
    out = {
        "clients": [{"id": i, "nom": n} for i, n in clients],
        "projets": [{"id": i, "nom": n} for i, n in projets],
        "immeubles": [{"id": i, "nom": n} for i, n in immeubles],
        "compagnies_feuille_de_temps": [{"id": i, "nom": n} for i, n in compagnies],
        "factures_mensuelles": int(factures_mensuelles or 0),
    }
    out["utilise_par_kratos"] = any(
        out[k] for k in ("clients", "projets", "immeubles", "compagnies_feuille_de_temps")
    ) or out["factures_mensuelles"] > 0
    return out


async def lire(
    compagnie: str, customer_id: str, db: Optional[AsyncSession] = None
) -> Dict[str, Any]:
    """Une fiche, même inactive, avec ses sous-clients directs et les
    liens que Kratos garde vers elle."""
    compagnie = compagnie_valide(compagnie)
    qbo = _client(compagnie)
    tous = await _tous(qbo, compagnie)
    par_id = {str(r["Id"]): r for r in tous}
    row = await _fiche_courante(qbo, compagnie, customer_id, par_id)
    out = fiche(row)
    out["compagnie"] = compagnie
    out["sous_clients"] = [_resume(r) for r in _sous_clients(tous, customer_id)]
    out["liens_kratos"] = await liens_kratos(db, customer_id)
    return out


# ── Inventaire des transactions ─────────────────────────────────────


#: Clés de colonnes du rapport « TransactionList » (le « ColKey » de
#: QuickBooks). Selon la compagnie, ``ColType`` porte cette clé OU le type
#: de donnée (« Date », « String », « Money ») et les titres sont en
#: français : voir ``_cle_colonne``.
CLES_RAPPORT: Set[str] = {
    "tx_date", "txn_type", "doc_num", "is_no_post", "name", "memo",
    "account_name", "other_account", "subt_nat_amount", "subt_amount",
    "subt_nat_home_amount", "amount", "debit_amt", "credit_amt",
    "klass_name", "dept_name", "pmt_mthd", "due_date", "cust_msg",
    "create_date", "last_mod_date", "term_name", "item_name", "quantity",
    "rate", "tax_amount", "net_amount", "home_amount",
}


def _norm_titre(s: str) -> str:
    """minuscules, sans accents, ponctuation → espace, espaces aplatis."""
    s = "".join(
        c
        for c in unicodedata.normalize("NFD", (s or "").lower())
        if unicodedata.category(c) != "Mn"
    )
    return " ".join(re.sub(r"[^a-z0-9]+", " ", s).split())


def _cle_colonne(col: Dict[str, Any]) -> str:
    """Clé d'une colonne du rapport : ``MetaData`` ColKey quand il est
    là, sinon ``ColType`` quand il porte une clé connue (et non un type
    de donnée), sinon le titre reconnu (français ou anglais), sinon le
    titre normalisé. Le rapport réel d'Horizon (compagnie en français)
    n'a pas « tx_date » dans ``ColType`` : sans ce repli, toutes les
    lignes sortaient à null (constat du 2026-11-04 sur la fiche 270)."""
    for m in col.get("MetaData") or []:
        if isinstance(m, dict) and str(m.get("Name") or "").lower() == "colkey":
            v = str(m.get("Value") or "").strip().lower()
            if v:
                return v
    ctype = str(col.get("ColType") or "").strip().lower()
    if ctype in CLES_RAPPORT:
        return ctype
    titre = _norm_titre(str(col.get("ColTitle") or ""))
    if "date" in titre:
        return "tx_date"
    if "type" in titre:
        return "txn_type"
    if titre in ("nom", "name", "client", "customer", "nom du client", "customer name"):
        return "name"
    if "memo" in titre or "description" in titre or titre in ("note", "notes"):
        return "memo"
    if "montant" in titre or "amount" in titre or titre == "total":
        return "subt_nat_amount"
    if titre == "debit":
        return "debit_amt"
    if titre == "credit":
        return "credit_amt"
    if "compte" in titre or "account" in titre:
        return "account_name"
    if titre in ("no", "n", "num", "numero", "number", "ref") or titre.startswith("num"):
        return "doc_num"
    return titre or ctype


def _montant(raw: Any) -> Optional[float]:
    """Montant d'une cellule de rapport, dans les deux locales que
    QuickBooks sert : « 1,350.00 » et « 1 350,00 $ » (espace, souvent
    insécable, pour les milliers ; virgule décimale), négatifs entre
    parenthèses. ``None`` quand la cellule n'est pas un nombre."""
    s = str(raw if raw is not None else "").strip()
    if not s:
        return None
    negatif = s.startswith("(") and s.endswith(")")
    if negatif:
        s = s[1:-1]
    s = s.replace("$", "")
    for espace in (" ", "\u00a0", "\u202f"):
        s = s.replace(espace, "")
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        s = s.replace(",", ".") if re.search(r",\d{1,2}$", s) else s.replace(",", "")
    try:
        v = float(s)
    except ValueError:
        return None
    return -v if negatif else v


def colonnes_rapport(rapport: Dict[str, Any]) -> List[str]:
    """Le format RÉEL des colonnes reçues (« titre|ColType|clé retenue »),
    renvoyé avec l'inventaire pour comprendre un rapport mal lu sans
    accès aux réponses de QuickBooks."""
    return [
        f"{c.get('ColTitle') or ''}|{c.get('ColType') or ''}|{_cle_colonne(c)}"
        for c in ((rapport.get("Columns") or {}).get("Column") or [])
        if isinstance(c, dict)
    ]


def lignes_rapport(rapport: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Lignes de données d'un rapport QuickBooks « TransactionList »
    (colonnes repérées par ``_cle_colonne`` ; id de la transaction porté
    par la cellule du type ; sections imbriquées parcourues, lignes de
    total ignorées)."""
    colonnes = [
        _cle_colonne(c)
        for c in ((rapport.get("Columns") or {}).get("Column") or [])
        if isinstance(c, dict)
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
        for cle, cellule in zip(colonnes, cellules):
            if not isinstance(cellule, dict):
                continue
            d.setdefault(cle, cellule.get("value"))
            if cle == "txn_type" and cellule.get("id"):
                txn_id = str(cellule["id"])
            elif cle == "doc_num" and cellule.get("id") and not txn_id:
                txn_id = str(cellule["id"])
        montant: Optional[float] = None
        for k in ("subt_nat_amount", "subt_amount", "subt_nat_home_amount", "amount"):
            if d.get(k) not in (None, ""):
                montant = _montant(d[k])
                if montant is not None:
                    break
        if montant is None and (d.get("debit_amt") or d.get("credit_amt")):
            montant = (_montant(d.get("debit_amt")) or 0.0) - (
                _montant(d.get("credit_amt")) or 0.0
            )
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


async def inventaire(
    compagnie: str, customer_id: str, db: Optional[AsyncSession] = None
) -> Dict[str, Any]:
    """Ce que porte une fiche : nombre de transactions par type (requêtes
    ``COUNT`` de QuickBooks), liste des transactions du rapport
    « TransactionList » filtré sur le client (toutes dates), sous-clients,
    liens Kratos. ``vide`` est vrai quand la fiche ne porte rien, faux
    quand elle porte quelque chose, et ``null`` quand l'inventaire est
    incomplet (un comptage ou le rapport refusé : voir ``notes``). Sert
    à vérifier qu'une fiche est vide avant de la désactiver, et à garder
    l'état d'une fiche avant une fusion."""
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
        except _ERREURS_QB as exc:  # noqa: BLE001
            comptes[libelle] = None
            notes.append(f"{libelle} : comptage refusé ({_motif(exc)})")

    lignes: List[Dict[str, Any]] = []
    colonnes: List[str] = []
    try:
        rapport = await qbo.report(
            "TransactionList",
            customer=customer_id,
            start_date="2000-01-01",
            end_date=(date.today() + timedelta(days=366)).isoformat(),
        )
        colonnes = colonnes_rapport(rapport)
        lignes = lignes_rapport(rapport)
    except _ERREURS_QB as exc:  # noqa: BLE001
        notes.append(f"rapport TransactionList refusé ({_motif(exc)})")

    connus = sum(n for n in comptes.values() if n)
    sous = _sous_clients(tous, customer_id)
    if lignes or connus or sous:
        vide: Optional[bool] = False
    elif notes:
        vide = None  # rien vu, mais l'inventaire est incomplet
    else:
        vide = True
    return {
        "compagnie": compagnie,
        "fiche": fiche(row),
        "sous_clients": [_resume(r) for r in sous],
        "liens_kratos": await liens_kratos(db, customer_id),
        "transactions_par_type": comptes,
        "nb_transactions": len(lignes),
        "transactions": lignes,
        "colonnes_rapport": colonnes,
        "vide": vide,
        "notes": notes,
    }


# ── Modification ────────────────────────────────────────────────────


def _nom_cle(nom: Optional[str]) -> str:
    return " ".join((nom or "").split()).casefold()


def _porteur_du_nom(
    tous: Iterable[Dict[str, Any]], nom: str, *, sauf: str
) -> Optional[Dict[str, Any]]:
    """Une AUTRE fiche client (active ou non) portant ce nom d'affichage."""
    cle = _nom_cle(nom)
    for r in tous:
        if str(r.get("Id")) != sauf and _nom_cle(r.get("DisplayName")) == cle:
            return r
    return None


async def _nom_pris_ailleurs(qbo: Any, nom: str) -> Optional[Dict[str, Any]]:
    """Fournisseur ou employé (actif ou non) portant ce nom : QuickBooks
    exige un nom d'affichage unique entre clients, fournisseurs et
    employés. Une requête refusée est ignorée (QuickBooks tranchera)."""
    safe = nom.replace("'", "''")
    for entite, libelle in (("Vendor", "fournisseur"), ("Employee", "employé")):
        try:
            rows = await qbo.query(
                f"SELECT * FROM {entite} WHERE Active IN (true, false) "
                f"AND DisplayName = '{safe}' MAXRESULTS 1"
            )
        except _ERREURS_QB:  # noqa: BLE001
            continue
        if rows:
            r = rows[0]
            return {
                "type": libelle,
                "Id": str(r.get("Id")),
                "DisplayName": r.get("DisplayName"),
                "Active": bool(r.get("Active", True)),
            }
    return None


async def _refuser_si_nom_pris(
    qbo: Any, tous: List[Dict[str, Any]], nom: str, *, sauf: str, contexte: str
) -> None:
    autre = _porteur_du_nom(tous, nom, sauf=sauf)
    if autre:
        raise ClientQboErreur(
            409,
            f"{contexte} « {nom} » : ce nom est déjà porté par la fiche client "
            f"#{autre.get('Id')} ({'active' if autre.get('Active', True) else 'inactive'}). "
            "QuickBooks le refuserait : l'API ne fusionne pas deux fiches. "
            "Pour fusionner, renomme le doublon à ce nom exact dans l'écran "
            "de QuickBooks, qui proposera la fusion.",
            fiche=_resume(autre),
        )
    ailleurs = await _nom_pris_ailleurs(qbo, nom)
    if ailleurs:
        raise ClientQboErreur(
            409,
            f"{contexte} « {nom} » : ce nom est déjà porté par le "
            f"{ailleurs['type']} #{ailleurs['Id']} "
            f"({'actif' if ailleurs['Active'] else 'inactif'}). QuickBooks exige "
            "un nom d'affichage unique entre clients, fournisseurs et employés.",
            fiche=ailleurs,
        )


def _ancetres(par_id: Dict[str, Dict[str, Any]], customer_id: str) -> List[str]:
    """Ids des parents, du plus proche à la racine (garde-fou contre une
    boucle de données)."""
    out: List[str] = []
    cur = parent_de(par_id.get(customer_id))
    while cur and cur not in out and cur != customer_id and len(out) < 50:
        out.append(cur)
        cur = parent_de(par_id.get(cur))
    return out


def _profondeur(
    par_id: Dict[str, Dict[str, Any]], customer_id: str, _vus: Optional[Set[str]] = None
) -> int:
    """Nombre de niveaux SOUS la fiche (0 sans sous-client), borné contre
    une boucle de données."""
    vus = set(_vus or ()) | {customer_id}
    enfants = [
        i for i, r in par_id.items() if parent_de(r) == customer_id and i not in vus
    ]
    if not enfants or len(vus) > NIVEAU_MAX + 2:
        return 0
    return 1 + max(_profondeur(par_id, e, vus) for e in enfants)


def _liens_lisibles(liens: Dict[str, Any]) -> str:
    morceaux = []
    for cle, libelle in (
        ("clients", "client"),
        ("projets", "projet"),
        ("immeubles", "immeuble"),
        ("compagnies_feuille_de_temps", "compagnie de la feuille de temps"),
    ):
        for l in liens.get(cle) or []:
            morceaux.append(f"{libelle} #{l['id']} ({l['nom']})")
    if liens.get("factures_mensuelles"):
        morceaux.append(f"{liens['factures_mensuelles']} facture(s) mensuelle(s)")
    return ", ".join(morceaux)


async def modifier(
    compagnie: str,
    customer_id: str,
    changements: Dict[str, Any],
    db: Optional[AsyncSession] = None,
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
    liens = await liens_kratos(db, customer_id)

    corps: Dict[str, Any] = {}
    faits: List[Dict[str, Any]] = []
    avertissements: List[str] = []
    nom_courant = " ".join(str(courant.get("DisplayName") or "").split())

    # Nom d'affichage.
    if "nom" in changements:
        nom = " ".join(str(changements.get("nom") or "").split())
        if not nom:
            raise ClientQboErreur(422, "`nom` est vide.")
        if ":" in nom:
            raise ClientQboErreur(
                422, "QuickBooks réserve « : » au chemin des sous-clients."
            )
        if nom != nom_courant:
            await _refuser_si_nom_pris(
                qbo, tous, nom, sauf=customer_id, contexte="Renommer en"
            )
            corps["DisplayName"] = nom[:100]
            faits.append(
                {"champ": "nom", "de": courant.get("DisplayName"), "a": nom[:100]}
            )
            if liens and liens["utilise_par_kratos"]:
                avertissements.append(
                    "Kratos relie cette fiche (" + _liens_lisibles(liens) + ") : "
                    "ses flux retrouvent le client QuickBooks par son nom, vérifie "
                    "que le nouveau nom reste celui de la fiche Kratos."
                )

    # Actif / inactif.
    actif = changements.get("actif")
    if actif is not None and bool(actif) != bool(courant.get("Active", True)):
        nom_final = corps.get("DisplayName") or nom_courant
        if actif:
            base = RE_SUPPRIME.sub("", nom_final)
            await _refuser_si_nom_pris(
                qbo, tous, base, sauf=customer_id,
                contexte="Réactivée, la fiche reprendrait le nom",
            )
        else:
            sous_actifs = [
                par_id[i] for i in _descendants(par_id, customer_id)
                if par_id[i].get("Active", True)
            ]
            solde = _num(courant.get("BalanceWithJobs"))
            if solde is None:
                solde = _num(courant.get("Balance")) or 0.0
            if liens and liens["utilise_par_kratos"] and not forcer:
                raise ClientQboErreur(
                    409,
                    "Kratos utilise cette fiche (" + _liens_lisibles(liens) + ") : "
                    "la rendre inactive casserait ces liens (Kratos la "
                    "réactiverait ou en créerait une autre au prochain envoi). "
                    "Relie d'abord Kratos à la fiche gardée, ou passe `forcer`.",
                    liens_kratos=liens,
                )
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
                    "un solde : QuickBooks peut refuser, ou rendre les "
                    "sous-clients inactifs avec le parent."
                )
            if liens and liens["utilise_par_kratos"]:
                avertissements.append(
                    "Désactivation forcée d'une fiche que Kratos utilise ("
                    + _liens_lisibles(liens) + ")."
                )
            deja = _porteur_du_nom(tous, f"{nom_final} (supprimé)", sauf=customer_id) \
                or _porteur_du_nom(tous, f"{nom_final} (deleted)", sauf=customer_id)
            if deja:
                avertissements.append(
                    f"Une fiche inactive porte déjà « {deja.get('DisplayName')} » "
                    f"(#{deja.get('Id')}) : QuickBooks, qui ajoute ce suffixe aux "
                    "fiches inactives, peut refuser."
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
        if parent.get("IsProject"):
            raise ClientQboErreur(
                422,
                f"#{parent_id} ({parent.get('DisplayName')}) est un projet "
                "QuickBooks : un projet n'a pas de sous-clients.",
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
            if liens and liens["projets"]:
                avertissements.append(
                    "Kratos relie des projets à ce sous-client ("
                    + _liens_lisibles(liens) + ") : son filet horaire le replace "
                    "sous le client QuickBooks mémorisé sur la fiche client du "
                    "projet si ce n'est pas celui-ci."
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
        "liens_kratos": liens,
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

    actifs_avant = {
        i for i in _descendants(par_id, customer_id) if par_id[i].get("Active", True)
    }
    try:
        maj = await qbo.update_customer_fields(customer_id, **corps)
    except _ERREURS_QB as exc:
        raise _erreur_qb(exc, compagnie)
    apres: Optional[Dict[str, Any]] = None
    try:
        if corps.get("Active") is False and actifs_avant:
            # Désactivation d'un parent : QuickBooks peut avoir rendu les
            # sous-clients inactifs avec lui — on le constate et on le dit.
            relus = {str(r["Id"]): r for r in await _tous(qbo, compagnie)}
            apres = relus.get(customer_id)
            resultat["sous_clients_desactives"] = [
                _resume(relus[i]) for i in sorted(actifs_avant, key=int)
                if i in relus and not relus[i].get("Active", True)
            ]
        else:
            apres = await qbo.get_customer_any(customer_id)
    except _ERREURS_QB:  # noqa: BLE001
        apres = None
    resultat["apres"] = fiche(apres or maj)
    log.info(
        "Client QuickBooks %s (%s) modifié : %s%s",
        customer_id,
        compagnie,
        ", ".join(f"{f['champ']} {f.get('de')!r} → {f.get('a')!r}" for f in faits),
        (
            " ; sous-clients rendus inactifs : "
            + ", ".join(s["Id"] for s in resultat["sous_clients_desactives"])
            if resultat.get("sous_clients_desactives")
            else ""
        ),
    )
    return resultat
