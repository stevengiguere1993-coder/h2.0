"""Liste des clients (Customers) QuickBooks — lecture seule.

Steven 2026-11-03 : le connecteur Claude doit pouvoir lire TOUS les
Customers QuickBooks, actifs et inactifs, avec au minimum Id,
DisplayName, Active, Balance et ParentRef. Lu en direct dans QuickBooks
(aucune écriture, aucune copie en base). Réservé admin / propriétaire.
Exposé au connecteur par ``kratos_lire`` (GET) et listé dans
``kratos_api_catalogue``.
"""

from __future__ import annotations

import re
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.api.deps import RequireAdminOrOwner
from app.integrations import quickbooks as qbo_mod

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
