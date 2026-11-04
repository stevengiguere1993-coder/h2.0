"""Vue d'ensemble des dépenses de la construction (Entreprises →
Dépenses construction, Steven 2026-10-03, bug 14).

    GET /api/v1/depenses-construction?debut=&fin=             dépenses, heures, coût/h vs entrées de fonds
    GET /api/v1/depenses-construction/quickbooks?debut=&fin=  P&L QuickBooks de la construction ramené aux heures

Lecture seule. Page « Dépenses construction » du pôle Entreprises
(``page:entreprises.depenses_construction_dev``, en développement :
propriétaires seulement par défaut). Calculs :
``app/services/depenses_construction.py``.
"""

from __future__ import annotations

from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.api.deps import DBSession
from app.services import depenses_construction as svc
from app.services.permissions_service import require_capability

router = APIRouter(
    prefix="/depenses-construction",
    tags=["depenses-construction"],
    dependencies=[
        Depends(require_capability("page:entreprises.depenses_construction_dev"))
    ],
)


class CategorieOut(BaseModel):
    cle: str
    libelle: str
    montant: float
    par_heure: Optional[float] = None
    part_pct: float


class _Chiffres(BaseModel):
    """Dépenses hors taxes, heures et entrées de fonds d'une période."""

    heures: float
    main_oeuvre: float
    materiaux: float
    sous_traitants: float
    frais_generaux: float
    achats: float
    achats_ttc: float
    depenses: float
    cout_heure: Optional[float] = None
    cout_main_oeuvre_heure: Optional[float] = None
    entrees_ttc: float
    entrees_ht: float
    entrees_heure: Optional[float] = None
    ecart_heure: Optional[float] = None
    resultat: float


class MoisOut(_Chiffres):
    mois: str
    debut: date
    fin: date


class VueEnsembleOut(_Chiffres):
    debut: date
    fin: date
    employes: int
    nb_paiements: int
    categories: List[CategorieOut]
    mois: List[MoisOut]


class PosteQboOut(BaseModel):
    nom: str
    montant: float


class MoisQboOut(BaseModel):
    mois: Optional[str] = None
    libelle: str
    depenses: float
    revenus: float
    heures: float
    cout_heure: Optional[float] = None


class VueQuickBooksOut(BaseModel):
    debut: date
    fin: date
    connecte: bool
    erreur: Optional[str] = None
    heures: float
    depenses: float
    revenus: float
    cout_heure: Optional[float] = None
    revenus_heure: Optional[float] = None
    postes: List[PosteQboOut]
    mois: List[MoisQboOut]


def _periode(debut: Optional[date], fin: Optional[date]) -> tuple[date, date]:
    try:
        return svc.periode(debut, fin)
    except svc.PeriodeInvalide as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("", response_model=VueEnsembleOut)
async def vue_ensemble(
    db: DBSession,
    debut: Optional[date] = Query(default=None),
    fin: Optional[date] = Query(default=None),
) -> VueEnsembleOut:
    """Dépenses de la construction (main-d'œuvre, matériaux,
    sous-traitants, shop et frais généraux), heures punchées, coût à
    l'heure et entrées de fonds hors taxes, au total et par mois. Par
    défaut : les 12 derniers mois."""
    d, f = _periode(debut, fin)
    return VueEnsembleOut(**await svc.vue_ensemble(db, d, f))


@router.get("/quickbooks", response_model=VueQuickBooksOut)
async def vue_quickbooks(
    db: DBSession,
    debut: Optional[date] = Query(default=None),
    fin: Optional[date] = Query(default=None),
) -> VueQuickBooksOut:
    """Toutes les dépenses du QuickBooks de la construction (paie, loyer,
    assurances, véhicules…) ramenées aux heures punchées dans Kratos.
    QuickBooks non connecté → ``connecte: false``, jamais d'erreur."""
    d, f = _periode(debut, fin)
    return VueQuickBooksOut(**await svc.vue_quickbooks(db, d, f))
