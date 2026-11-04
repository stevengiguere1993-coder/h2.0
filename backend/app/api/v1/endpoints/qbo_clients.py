"""Clients (Customers) QuickBooks : liste, fiche, transactions, modification.

Steven 2026-11-03 : le connecteur Claude doit pouvoir lire TOUS les
Customers QuickBooks, actifs et inactifs, avec au minimum Id,
DisplayName, Active, Balance et ParentRef. Lu en direct dans QuickBooks
(aucune copie en base). Réservé admin / propriétaire. Exposé au
connecteur par ``kratos_lire`` (GET) et listé dans ``kratos_api_catalogue``.

Steven 2026-11-04 (« passe par le lien Kratos ») : le nettoyage des
clients en double se fait depuis Kratos. S'ajoutent la fiche d'un client
(même inactif), l'inventaire de ses transactions et la MODIFICATION
d'une fiche (nom, client mère, actif, facturer avec le parent) —
``POST /qbo/customers/{id}/modifier``, actionnable par ``kratos_action``.
L'API Intuit ne fusionne pas deux fiches : voir
``app/services/qbo_clients_modif`` (garde-fous, simulation).
"""

from __future__ import annotations

import re
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Path, Query
from pydantic import BaseModel, ConfigDict, Field

from app.api.deps import DBSession, RequireAdminOrOwner
from app.integrations import quickbooks as qbo_mod
from app.services import qbo_clients_modif as modif

router = APIRouter(prefix="/qbo", tags=["quickbooks-clients"])

#: Compagnies QuickBooks connues de Kratos (scope de ``get_qbo``).
_COMPAGNIE_RE = re.compile(r"^(construction|entreprise|immobilier|inc:\d+)$")


class QboRef(BaseModel):
    value: Optional[str] = None
    name: Optional[str] = None


class QboClient(BaseModel):
    Id: str
    DisplayName: Optional[str] = None
    Active: bool
    Balance: float = 0.0
    BalanceWithJobs: Optional[float] = None
    ParentRef: Optional[QboRef] = None
    Job: bool = False
    Level: Optional[int] = None
    FullyQualifiedName: Optional[str] = None
    CompanyName: Optional[str] = None
    PrimaryEmailAddr: Optional[str] = None
    PrimaryPhone: Optional[str] = None


class QboClientsPage(BaseModel):
    compagnie: str
    total: int
    actifs: int
    inactifs: int
    offset: int
    limit: int
    restant: int
    clients: list[QboClient]


def _num(v: Any) -> Optional[float]:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _client(c: dict[str, Any]) -> QboClient:
    parent = c.get("ParentRef")
    return QboClient(
        Id=str(c.get("Id")),
        DisplayName=c.get("DisplayName"),
        Active=bool(c.get("Active", True)),
        Balance=_num(c.get("Balance")) or 0.0,
        BalanceWithJobs=_num(c.get("BalanceWithJobs")),
        ParentRef=(
            QboRef(value=parent.get("value"), name=parent.get("name"))
            if isinstance(parent, dict)
            else None
        ),
        Job=bool(c.get("Job", False)),
        Level=c.get("Level"),
        FullyQualifiedName=c.get("FullyQualifiedName"),
        CompanyName=c.get("CompanyName"),
        PrimaryEmailAddr=(c.get("PrimaryEmailAddr") or {}).get("Address"),
        PrimaryPhone=(c.get("PrimaryPhone") or {}).get("FreeFormNumber"),
    )


async def _lister(
    compagnie: str, statut: str, recherche: Optional[str], offset: int, limit: int
) -> QboClientsPage:
    compagnie = compagnie.strip().lower()
    if not _COMPAGNIE_RE.match(compagnie):
        raise HTTPException(
            422,
            "`compagnie` doit être construction, entreprise, immobilier "
            "ou inc:<id d'entreprise>.",
        )
    # Sans filtre sur Active, QuickBooks ne renvoie que les actifs.
    where = {
        "tous": "Active IN (true, false)",
        "actifs": "Active = true",
        "inactifs": "Active = false",
    }[statut]
    try:
        brut = await qbo_mod.get_qbo(compagnie).query_all(
            f"SELECT * FROM Customer WHERE {where} ORDERBY Id"
        )
    except qbo_mod.QuickBooksError as exc:
        raise HTTPException(
            502,
            f"QuickBooks ({compagnie}) a refusé la lecture : {str(exc)[:300]}. "
            f"Au besoin : {qbo_mod.ou_reconnecter(compagnie)}.",
        )
    clients = [_client(c) for c in brut if isinstance(c, dict)]
    if recherche:
        r = recherche.strip().lower()
        clients = [
            c for c in clients
            if r in (c.FullyQualifiedName or c.DisplayName or "").lower()
            or r in (c.CompanyName or "").lower()
            or r in (c.PrimaryEmailAddr or "").lower()
        ]
    page = clients[offset : offset + limit]
    actifs = sum(1 for c in clients if c.Active)
    return QboClientsPage(
        compagnie=compagnie,
        total=len(clients),
        actifs=actifs,
        inactifs=len(clients) - actifs,
        offset=offset,
        limit=limit,
        restant=max(0, len(clients) - offset - len(page)),
        clients=page,
    )


@router.get(
    "/customers",
    response_model=QboClientsPage,
    summary="Liste des clients (Customers) QuickBooks, actifs et inactifs",
)
async def lister_customers_qbo(
    _: RequireAdminOrOwner,
    compagnie: str = Query(
        "construction",
        description="construction | entreprise | immobilier | inc:<id>",
    ),
    statut: str = Query("tous", pattern="^(tous|actifs|inactifs)$"),
    recherche: Optional[str] = Query(None, description="Filtre sur le nom / courriel"),
    offset: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=1000),
) -> QboClientsPage:
    """Tous les Customers de la compagnie QuickBooks (clients ET
    sous-clients / projets : ``ParentRef`` renseigné, ``Job`` vrai), lus
    en direct. Paginé par ``offset`` / ``limit`` (``restant`` = suite)."""
    return await _lister(compagnie, statut, recherche, offset, limit)


@router.get(
    "/clients",
    response_model=QboClientsPage,
    summary="Liste des clients QuickBooks (alias de /qbo/customers)",
)
async def lister_clients_qbo(
    _: RequireAdminOrOwner,
    compagnie: str = Query("construction"),
    statut: str = Query("tous", pattern="^(tous|actifs|inactifs)$"),
    recherche: Optional[str] = Query(None),
    offset: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=1000),
) -> QboClientsPage:
    return await _lister(compagnie, statut, recherche, offset, limit)


# ── Fiche, transactions, modification (2026-11-04) ─────────────────

_ID_QB = Path(..., pattern=r"^\d{1,20}$", description="Id QuickBooks du client")
_COMPAGNIE_Q = Query(
    "construction", description="construction | entreprise | immobilier | inc:<id>"
)


def _http(exc: modif.ClientQboErreur) -> HTTPException:
    return HTTPException(exc.statut, exc.detail)


class ModifierClientIn(BaseModel):
    """Changements à appliquer à une fiche ; un champ absent n'est pas
    touché, un champ inconnu est refusé (422). Tout est validé avant
    l'envoi (voir le service)."""

    model_config = ConfigDict(extra="forbid")

    nom: Optional[str] = Field(
        None, max_length=100, description="Nouveau nom d'affichage (DisplayName)"
    )
    actif: Optional[bool] = Field(
        None, description="true = réactiver, false = rendre inactive (« supprimer »)"
    )
    parent_id: Optional[str] = Field(
        None,
        max_length=32,
        description="Id du client mère sous lequel déplacer la fiche (sous-client)",
    )
    facturer_avec_parent: Optional[bool] = Field(
        None, description="« Facturer avec le client parent » (sous-client seulement)"
    )
    forcer: bool = Field(
        False,
        description=(
            "Désactiver malgré des sous-clients actifs ou un solde "
            "(QuickBooks tranche)"
        ),
    )
    simuler: bool = Field(
        False, description="Valider et décrire les changements sans rien écrire"
    )


@router.get(
    "/customers/{customer_id}",
    summary="Une fiche client QuickBooks (même inactive) et ses sous-clients",
)
async def lire_customer_qbo(
    _: RequireAdminOrOwner,
    db: DBSession,
    customer_id: str = _ID_QB,
    compagnie: str = _COMPAGNIE_Q,
) -> dict[str, Any]:
    """Fiche complète (nom, parent, actif, soldes, SyncToken, dates),
    liste de ses sous-clients directs, actifs et inactifs, et liens que
    Kratos garde vers elle (clients, projets, immeubles, compagnies de la
    feuille de temps, factures mensuelles)."""
    try:
        return await modif.lire(compagnie, customer_id, db=db)
    except modif.ClientQboErreur as exc:
        raise _http(exc) from exc


@router.get(
    "/customers/{customer_id}/transactions",
    summary="Transactions d'un client QuickBooks (inventaire, toutes dates)",
)
async def transactions_customer_qbo(
    _: RequireAdminOrOwner,
    db: DBSession,
    customer_id: str = _ID_QB,
    compagnie: str = _COMPAGNIE_Q,
) -> dict[str, Any]:
    """Nombre de transactions par type (factures, paiements, notes de
    crédit, reçus de vente, remboursements, soumissions, temps), liste
    du rapport « TransactionList » filtré sur le client, sous-clients,
    liens Kratos, et ``vide`` : vrai quand la fiche ne porte rien, faux
    quand elle porte quelque chose, null quand l'inventaire est incomplet
    (voir ``notes``). À lire avant de rendre une fiche inactive, et pour
    garder l'état d'une fiche avant une fusion."""
    try:
        return await modif.inventaire(compagnie, customer_id, db=db)
    except modif.ClientQboErreur as exc:
        raise _http(exc) from exc


@router.post(
    "/customers/{customer_id}/modifier",
    summary=(
        "Modifier une fiche client QuickBooks : nom, client mère, actif / "
        "inactif, facturer avec le parent"
    ),
)
async def modifier_customer_qbo(
    body: ModifierClientIn,
    _: RequireAdminOrOwner,
    db: DBSession,
    customer_id: str = _ID_QB,
    compagnie: str = _COMPAGNIE_Q,
) -> dict[str, Any]:
    """Une seule mise à jour « sparse » dans QuickBooks, après les
    garde-fous : 409 si le nom est déjà porté par une autre fiche, un
    fournisseur ou un employé (l'API Intuit ne fusionne pas ; la fusion
    se fait dans l'écran de QuickBooks en renommant le doublon au nom
    exact de la fiche gardée), 422 si le client mère est introuvable,
    inactif, un projet QuickBooks ou un de ses propres sous-clients, 409
    pour rendre inactive une fiche à solde, avec des sous-clients actifs
    ou que Kratos utilise (sauf ``forcer``), 503 si QuickBooks n'est pas
    connecté. ``simuler`` décrit sans écrire. Renvoie la fiche avant et
    après, la liste des changements, les avertissements et, après une
    désactivation forcée, les sous-clients rendus inactifs avec elle."""
    try:
        return await modif.modifier(
            compagnie, customer_id, body.model_dump(exclude_none=True), db=db
        )
    except modif.ClientQboErreur as exc:
        raise _http(exc) from exc
