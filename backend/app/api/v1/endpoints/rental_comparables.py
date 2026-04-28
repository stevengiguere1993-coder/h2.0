"""Endpoints pour les comparables de loyers — vues agrégées par
quartier × taille × inclusions × état (rénové/standard).

L'utilisateur ne veut PAS les annonces brutes, il veut une moyenne
fiable pour bâtir son analyse financière. Donc on retourne :
- Médiane / P25 / P75 du loyer pour la combinaison demandée
- Avec et sans chauffage/électricité (impact significatif sur le
  loyer net)
- Rénové vs standard

Endpoints :
- GET  /summary?quartier=Plateau&bedrooms=2 → agrégats prêts à
  l'analyse
- GET  /list (admin) → annonces brutes pour debug
- DELETE /cleanup → purge > N jours
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import delete, select

from app.api.deps import CurrentUser, DBSession, RequireOwner
from app.models.rental_listing import RentalListing

log = logging.getLogger(__name__)

router = APIRouter(
    prefix="/prospection/rental-comparables",
    tags=["rental-comparables"],
)


def _percentile(values: list[float], p: float) -> Optional[float]:
    if not values:
        return None
    s = sorted(values)
    k = (len(s) - 1) * p
    f = int(k)
    c = min(f + 1, len(s) - 1)
    if f == c:
        return s[f]
    return s[f] + (s[c] - s[f]) * (k - f)


class StatsRow(BaseModel):
    """Stats pour un sous-ensemble de comparables."""

    count: int
    median: Optional[float] = None
    p25: Optional[float] = None
    p75: Optional[float] = None
    min: Optional[float] = None
    max: Optional[float] = None


class BedroomBreakdown(BaseModel):
    bedrooms: int  # 0=studio, 1, 2, 3, 4+
    pieces_label: str  # "2½ (studio)", "3½", "4½", "5½", "6½+"
    standard: StatsRow
    renovated: StatsRow
    with_heating: StatsRow
    with_electricity: StatsRow


class ComparablesSummary(BaseModel):
    quartier: Optional[str]
    fsa: Optional[str]  # zone code postal (3 char)
    sample_size: int
    fresh_count: int  # < 14 jours
    oldest_at: Optional[datetime] = None
    overall: StatsRow
    by_bedrooms: List[BedroomBreakdown]
    common_inclusions: List[dict]  # [{tag, count, pct}]


def _stats(values: list[float]) -> StatsRow:
    if not values:
        return StatsRow(count=0)
    return StatsRow(
        count=len(values),
        median=_percentile(values, 0.5),
        p25=_percentile(values, 0.25),
        p75=_percentile(values, 0.75),
        min=min(values),
        max=max(values),
    )


def _pieces_label(bedrooms: int) -> str:
    """Convention québécoise : N chambres = (N+2)½ pièces."""
    if bedrooms <= 0:
        return "Studio (1½ – 2½)"
    if bedrooms == 1:
        return "3½ (1 chambre)"
    if bedrooms == 2:
        return "4½ (2 chambres)"
    if bedrooms == 3:
        return "5½ (3 chambres)"
    if bedrooms == 4:
        return "6½ (4 chambres)"
    return f"{bedrooms + 2}½ ({bedrooms} chambres)"


@router.get("/summary", response_model=ComparablesSummary)
async def get_summary(
    db: DBSession,
    _: CurrentUser,
    quartier: Optional[str] = Query(default=None),
    postal_code: Optional[str] = Query(default=None),
    nom_rue: Optional[str] = Query(default=None),
    max_age_days: int = Query(default=30, ge=1, le=90),
) -> ComparablesSummary:
    """Retourne les stats agrégées par chambres × état × inclusions
    pour une zone donnée. À utiliser dans le calculateur d'analyse
    pour pré-remplir le loyer moyen.

    Filtre prioritaire (du plus précis au plus large) :
    1. quartier (forme canonique : « Plateau Mont-Royal »)
    2. postal_code (FSA 3 char : « H2W »)
    3. nom_rue (contient)
    """
    if not (quartier or postal_code or nom_rue):
        raise HTTPException(
            400,
            "Au moins un de quartier, postal_code, nom_rue est requis.",
        )

    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
    stmt = select(RentalListing).where(
        RentalListing.scraped_at >= cutoff,
        RentalListing.price.is_not(None),
    )

    fsa_used: Optional[str] = None
    if quartier:
        stmt = stmt.where(RentalListing.quartier == quartier)
    elif postal_code:
        fsa_used = postal_code.replace(" ", "")[:3].upper()
        from sqlalchemy import func as sa_func

        stmt = stmt.where(
            sa_func.upper(RentalListing.postal_code).like(f"{fsa_used}%")
        )
    elif nom_rue:
        stmt = stmt.where(
            RentalListing.nom_rue.ilike(f"%{nom_rue.strip()}%")
        )

    rows = (await db.execute(stmt)).scalars().all()
    fresh_cutoff = datetime.now(timezone.utc) - timedelta(days=14)

    # Stats globales
    all_prices = [float(r.price) for r in rows if r.price]
    overall = _stats(all_prices)

    # Breakdown par chambres
    by_bed_data: dict[int, list] = {}
    for r in rows:
        if r.bedrooms is None or not r.price:
            continue
        bed_key = min(int(r.bedrooms), 4)  # 4 = 4+
        by_bed_data.setdefault(bed_key, []).append(r)

    by_bedrooms: list[BedroomBreakdown] = []
    for bed in sorted(by_bed_data.keys()):
        bucket = by_bed_data[bed]
        prices = [float(r.price) for r in bucket if r.price]
        prices_std = [
            float(r.price)
            for r in bucket
            if r.price and not r.is_renovated
        ]
        prices_reno = [
            float(r.price)
            for r in bucket
            if r.price and r.is_renovated
        ]
        prices_heat = [
            float(r.price)
            for r in bucket
            if r.price and _has_inclusion(r, "chauffage")
        ]
        prices_elec = [
            float(r.price)
            for r in bucket
            if r.price and _has_inclusion(r, "electricite")
        ]
        by_bedrooms.append(
            BedroomBreakdown(
                bedrooms=bed,
                pieces_label=_pieces_label(bed),
                standard=_stats(prices_std),
                renovated=_stats(prices_reno),
                with_heating=_stats(prices_heat),
                with_electricity=_stats(prices_elec),
            )
        )

    # Inclusions les plus communes
    inclusion_counts: dict[str, int] = {}
    for r in rows:
        if not r.inclusions_json:
            continue
        try:
            tags = json.loads(r.inclusions_json) or []
        except Exception:
            tags = []
        for t in tags:
            inclusion_counts[t] = inclusion_counts.get(t, 0) + 1
    total = len(rows) or 1
    common = sorted(
        inclusion_counts.items(), key=lambda kv: -kv[1]
    )[:8]
    common_inclusions = [
        {
            "tag": tag,
            "count": cnt,
            "pct": round(100 * cnt / total, 1),
        }
        for tag, cnt in common
    ]

    return ComparablesSummary(
        quartier=quartier,
        fsa=fsa_used,
        sample_size=len(rows),
        fresh_count=sum(
            1 for r in rows if r.scraped_at >= fresh_cutoff
        ),
        oldest_at=(
            min(r.scraped_at for r in rows) if rows else None
        ),
        overall=overall,
        by_bedrooms=by_bedrooms,
        common_inclusions=common_inclusions,
    )


def _has_inclusion(r: RentalListing, tag: str) -> bool:
    if not r.inclusions_json:
        return False
    try:
        tags = json.loads(r.inclusions_json) or []
    except Exception:
        return False
    return tag in tags


@router.get(
    "/list",
    summary="Annonces brutes (debug). Limité à 200 lignes.",
)
async def list_listings(
    db: DBSession,
    _: RequireOwner,
    quartier: Optional[str] = Query(default=None),
    bedrooms: Optional[int] = Query(default=None, ge=0, le=10),
    max_age_days: int = Query(default=30, ge=1, le=90),
    limit: int = Query(default=100, ge=1, le=200),
) -> List[dict]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
    stmt = select(RentalListing).where(
        RentalListing.scraped_at >= cutoff
    )
    if quartier:
        stmt = stmt.where(RentalListing.quartier == quartier)
    if bedrooms is not None:
        stmt = stmt.where(RentalListing.bedrooms == bedrooms)
    stmt = stmt.order_by(RentalListing.scraped_at.desc()).limit(limit)
    rows = (await db.execute(stmt)).scalars().all()
    return [
        {
            "id": r.id,
            "source": r.source,
            "source_url": r.source_url,
            "address": r.address,
            "quartier": r.quartier,
            "postal_code": r.postal_code,
            "price": float(r.price) if r.price else None,
            "bedrooms": r.bedrooms,
            "is_renovated": r.is_renovated,
            "inclusions": (
                json.loads(r.inclusions_json)
                if r.inclusions_json
                else []
            ),
            "phone": r.phone,
            "scraped_at": r.scraped_at.isoformat(),
        }
        for r in rows
    ]


@router.delete(
    "/cleanup",
    summary="Supprime les annonces > N jours pour limiter le stockage.",
)
async def cleanup_old_listings(
    db: DBSession,
    _: RequireOwner,
    older_than_days: int = Query(default=30, ge=7, le=365),
) -> dict:
    cutoff = datetime.now(timezone.utc) - timedelta(
        days=older_than_days
    )
    res = await db.execute(
        delete(RentalListing).where(RentalListing.scraped_at < cutoff)
    )
    return {"deleted": res.rowcount or 0, "cutoff": cutoff.isoformat()}
