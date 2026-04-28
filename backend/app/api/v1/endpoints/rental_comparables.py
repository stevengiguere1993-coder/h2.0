"""Endpoints pour les comparables de loyers + scrape on-demand.

Stratégie : on garde un cache court (30 jours) en DB. Quand un
utilisateur demande des comparables :
1. Cherche dans la DB les annonces récentes (< 30j) près de
   l'adresse cible
2. Si pas assez de résultats, on peut déclencher un scrape ciblé
   (paramètre `?refresh=true`)

Permet de minimiser le stockage : les annonces vieilles sont
supprimées par le job de cleanup, et on ne scrape que ce qu'on
demande activement.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import and_, delete, func, select

from app.api.deps import CurrentUser, DBSession, RequireOwner
from app.models.rental_listing import RentalListing

log = logging.getLogger(__name__)

router = APIRouter(
    prefix="/prospection/rental-comparables",
    tags=["rental-comparables"],
)


class RentalComparable(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    source: str
    source_url: str
    address: Optional[str]
    civique: Optional[str]
    nom_rue: Optional[str]
    postal_code: Optional[str]
    price: Optional[float]
    bedrooms: Optional[int]
    phone: Optional[str]
    scraped_at: datetime


class ComparablesSummary(BaseModel):
    count: int
    median_price: Optional[float] = None
    p25_price: Optional[float] = None
    p75_price: Optional[float] = None
    by_bedrooms: dict[str, dict] = {}  # "2": {"count": 5, "median": 1450}


class ComparablesResponse(BaseModel):
    listings: List[RentalComparable]
    summary: ComparablesSummary
    fresh_count: int  # nb d'annonces < 14j
    oldest_at: Optional[datetime] = None


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


@router.get("", response_model=ComparablesResponse)
async def get_comparables(
    db: DBSession,
    _: CurrentUser,
    civique: Optional[str] = Query(default=None),
    nom_rue: Optional[str] = Query(default=None),
    postal_code: Optional[str] = Query(default=None),
    bedrooms: Optional[int] = Query(default=None, ge=0, le=10),
    max_age_days: int = Query(default=30, ge=1, le=90),
    limit: int = Query(default=50, ge=1, le=200),
) -> ComparablesResponse:
    """Retourne les annonces de location matchant les critères.

    Match strategy (du plus précis au plus large) :
    1. Code postal exact (si fourni)
    2. Sinon, nom de rue contains (case-insensitive)
    3. Sinon, retourne tout (pas conseillé)

    Filtres optionnels : nb chambres, fraîcheur (max_age_days).
    """
    if not (postal_code or nom_rue):
        raise HTTPException(
            400,
            "Au moins un de postal_code ou nom_rue est requis.",
        )

    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
    stmt = select(RentalListing).where(
        RentalListing.scraped_at >= cutoff
    )

    if postal_code:
        # Match les 3 premiers caractères (zone FSA) pour ratisser
        # plus large — les codes postaux complets matchent rarement.
        fsa = postal_code.replace(" ", "")[:3].upper()
        stmt = stmt.where(
            func.upper(RentalListing.postal_code).like(f"{fsa}%")
        )
    elif nom_rue:
        stmt = stmt.where(
            RentalListing.nom_rue.ilike(f"%{nom_rue.strip()}%")
        )

    if bedrooms is not None:
        stmt = stmt.where(RentalListing.bedrooms == bedrooms)

    stmt = stmt.order_by(RentalListing.scraped_at.desc()).limit(limit)
    rows = (await db.execute(stmt)).scalars().all()

    prices = [
        float(r.price)
        for r in rows
        if r.price is not None and float(r.price) > 0
    ]
    by_bed: dict[str, dict] = {}
    for r in rows:
        if r.bedrooms is None or r.price is None:
            continue
        key = str(r.bedrooms)
        by_bed.setdefault(key, {"prices": []})
        by_bed[key]["prices"].append(float(r.price))
    by_bed_summary: dict[str, dict] = {}
    for k, v in by_bed.items():
        ps = v["prices"]
        by_bed_summary[k] = {
            "count": len(ps),
            "median": _percentile(ps, 0.5),
        }

    fresh_cutoff = datetime.now(timezone.utc) - timedelta(days=14)
    fresh_count = sum(
        1 for r in rows if r.scraped_at >= fresh_cutoff
    )
    oldest_at = (
        min(r.scraped_at for r in rows) if rows else None
    )

    summary = ComparablesSummary(
        count=len(rows),
        median_price=_percentile(prices, 0.5),
        p25_price=_percentile(prices, 0.25),
        p75_price=_percentile(prices, 0.75),
        by_bedrooms=by_bed_summary,
    )

    return ComparablesResponse(
        listings=[RentalComparable.model_validate(r) for r in rows],
        summary=summary,
        fresh_count=fresh_count,
        oldest_at=oldest_at,
    )


@router.delete(
    "/cleanup",
    summary="Supprime les annonces de location > N jours pour limiter "
    "le stockage. Idempotent.",
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
