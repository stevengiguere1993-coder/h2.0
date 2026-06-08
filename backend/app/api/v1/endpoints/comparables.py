"""Comparables de vente (« comps ») — module Prospection.

L'utilisateur cherche des ventes comparables pour un secteur (rue /
municipalité / région) afin d'évaluer la valeur marchande d'un
immeuble cible. Trois sources alimentent la table `sold_comparables` :

- "manual"  : saisie manuelle (toujours fiable, jamais purgée par un
  scrape).
- "numeriq" : scrapé depuis le journal des ventes via le VPS Hetzner
  (best-effort — l'endpoint VPS peut ne pas exister encore).
- "registre": import du registre foncier (futur).

Chaque comparable est croisé avec `mtl_property_units` via `search_key`
(« <civique>|<rue normalisée> ») pour enrichir automatiquement
matricule, nb de logements, année de construction, superficie du
terrain et libellé d'utilisation.

Endpoints :
- GET    ""        → recherche filtrée (+ refresh scrape optionnel)
- POST   /manual   → ajoute un comparable saisi à la main
- DELETE /{id}     → supprime un comparable
- GET    /health   → état du cache + du lien VPS
"""

from __future__ import annotations

import json
import logging
import os
from datetime import date, datetime, timezone
from typing import List, Optional, Tuple

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, DBSession
from app.integrations import scraping_proxy
from app.integrations.roles_evaluation.montreal import make_search_key
from app.models.montreal_property_unit import MontrealPropertyUnit
from app.models.sold_comparable import SoldComparable
from app.services.audit import log_action

log = logging.getLogger(__name__)

router = APIRouter(
    prefix="/prospection/comparables",
    tags=["comparables"],
)


# --------------------------- Schemas ---------------------------


class ComparableRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    matricule: Optional[str] = None
    civique: Optional[str] = None
    nom_rue: Optional[str] = None
    municipalite: Optional[str] = None
    region: Optional[str] = None
    address_full: Optional[str] = None
    price: Optional[float] = None
    date_sold: Optional[date] = None
    nb_logement: Optional[int] = None
    annee_construction: Optional[int] = None
    superficie_terrain: Optional[float] = None
    libelle_utilisation: Optional[str] = None
    source: str
    source_url: Optional[str] = None
    created_by_email: Optional[str] = None
    created_at: Optional[datetime] = None


class ListResponse(BaseModel):
    total: int
    comparables: List[ComparableRead]


class ManualComparableIn(BaseModel):
    matricule: Optional[str] = None
    civique: Optional[str] = None
    nom_rue: str = Field(..., min_length=1, max_length=255)
    municipalite: Optional[str] = None
    region: Optional[str] = Field(
        default=None,
        pattern="^(mtl-island|laval|rive-sud|rive-nord)$",
    )
    address_full: Optional[str] = None
    price: float = Field(..., ge=0)
    date_sold: date
    nb_logement: Optional[int] = Field(default=None, ge=0)
    annee_construction: Optional[int] = Field(
        default=None, ge=1700, le=2100
    )
    superficie_terrain: Optional[float] = Field(default=None, ge=0)
    libelle_utilisation: Optional[str] = None
    source_url: Optional[str] = None


class HealthResponse(BaseModel):
    cache_count: int
    vps_url_set: bool
    vps_key_set: bool
    vps_reachable: bool
    journal_source_configured: bool


# --------------------------- Helpers ---------------------------


def _to_read(c: SoldComparable) -> ComparableRead:
    d = ComparableRead.model_validate(c)
    if c.price is not None:
        d.price = float(c.price)
    if c.superficie_terrain is not None:
        d.superficie_terrain = float(c.superficie_terrain)
    return d


def _parse_civic_street(address: str) -> Tuple[Optional[str], Optional[str]]:
    """Extrait (civique, rue brute) d'une adresse libre type
    « 4520 Boulevard Saint-Laurent ». Retourne (None, None) si on ne
    peut pas isoler un numéro civique."""
    parts = (address or "").strip().split(maxsplit=1)
    if len(parts) < 2:
        return None, None
    civic_raw, rue = parts[0], parts[1]
    import re

    m = re.match(r"^(\d+)", civic_raw)
    if not m:
        return None, None
    return m.group(1), rue


def _compute_search_key(
    civique: Optional[str], nom_rue: Optional[str]
) -> Optional[str]:
    """Clé de jointure avec `mtl_property_units`. Nécessite un civique
    ET une rue ; sinon on ne peut pas croiser de façon fiable."""
    if not civique or not nom_rue:
        return None
    civic = str(civique).strip()
    import re

    m = re.match(r"^(\d+)", civic)
    if not m:
        return None
    return make_search_key(m.group(1), nom_rue)


async def _find_unit(
    db: AsyncSession,
    *,
    matricule: Optional[str] = None,
    civique: Optional[str] = None,
    nom_rue: Optional[str] = None,
) -> Optional[MontrealPropertyUnit]:
    """Trouve l'unité du rôle d'évaluation à croiser.

    NB : `search_key` n'est PAS renseignée lors de l'import en masse des
    rôles, donc on ne peut pas matcher dessus. On matche directement sur
    les colonnes réellement remplies :
    - par `matricule` (exact) si on l'a (ex. choisi via l'autocomplete) ;
    - sinon par `civique_debut` (exact) + `nom_rue` (sous-chaîne, comme
      l'autocomplete d'adresse).
    En cas de copropriété (plusieurs unités à la même adresse), on retient
    celle qui porte le plus de logements (l'immeuble principal)."""
    stmt = None
    if matricule:
        stmt = select(MontrealPropertyUnit).where(
            MontrealPropertyUnit.matricule == matricule.strip()
        )
    elif civique and nom_rue:
        civic = str(civique).strip()
        stmt = (
            select(MontrealPropertyUnit)
            .where(
                MontrealPropertyUnit.civique_debut == civic,
                MontrealPropertyUnit.nom_rue.ilike(f"%{nom_rue.strip()}%"),
            )
            .order_by(MontrealPropertyUnit.nombre_logement.desc().nullslast())
        )
    if stmt is None:
        return None
    return (await db.execute(stmt)).scalars().first()


def _enrich_from_unit(
    c: SoldComparable, unit: Optional[MontrealPropertyUnit]
) -> None:
    """Remplit les champs manquants du comparable depuis l'unité du
    rôle d'évaluation. N'écrase JAMAIS une valeur déjà présente
    (ex. saisie manuelle de l'utilisateur)."""
    if unit is None:
        return
    if not c.matricule:
        c.matricule = unit.matricule
    if c.nb_logement is None and unit.nombre_logement is not None:
        c.nb_logement = unit.nombre_logement
    if c.annee_construction is None and unit.annee_construction is not None:
        c.annee_construction = unit.annee_construction
    if c.superficie_terrain is None and unit.superficie_terrain is not None:
        c.superficie_terrain = float(unit.superficie_terrain)
    if not c.libelle_utilisation and unit.libelle_utilisation:
        c.libelle_utilisation = unit.libelle_utilisation
    if not c.municipalite and unit.municipalite:
        c.municipalite = unit.municipalite
    if not c.region and unit.region:
        c.region = unit.region


# --------------------------- Endpoints ---------------------------


@router.get("", response_model=ListResponse)
async def list_comparables(
    db: DBSession,
    current_user: CurrentUser,
    address: Optional[str] = Query(default=None),
    matricule: Optional[str] = Query(default=None),
    nom_rue_contains: Optional[str] = Query(default=None),
    municipalite: Optional[str] = Query(default=None),
    region: Optional[str] = Query(
        default=None,
        pattern="^(mtl-island|laval|rive-sud|rive-nord)$",
    ),
    min_price: Optional[float] = Query(default=None, ge=0),
    max_price: Optional[float] = Query(default=None, ge=0),
    min_logements: Optional[int] = Query(default=None, ge=0),
    max_logements: Optional[int] = Query(default=None, ge=0),
    min_annee: Optional[int] = Query(default=None, ge=1700),
    max_annee: Optional[int] = Query(default=None, le=2100),
    sold_since: Optional[date] = Query(default=None),
    refresh: bool = Query(default=False),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> ListResponse:
    """Recherche des comparables de vente pour un secteur.

    Détermination du secteur (du plus précis au plus large) :
    1. `matricule` → on lit l'unité du rôle pour récupérer
       rue / municipalité / région.
    2. `address` → on extrait civique + rue, on tente un match dans le
       rôle pour récupérer le secteur (rue / municipalité / région).
    3. `nom_rue_contains` / `municipalite` / `region` directs.

    Si `refresh=True` et que le VPS est configuré, on tente un scrape
    Numériq pour rafraîchir le cache avant de répondre (best-effort —
    ne fait jamais planter la recherche).
    """
    # 1) Détermine le secteur de recherche.
    sector_nom_rue: Optional[str] = None
    sector_municipalite: Optional[str] = municipalite
    sector_region: Optional[str] = region

    if matricule:
        unit = (
            await db.execute(
                select(MontrealPropertyUnit).where(
                    MontrealPropertyUnit.matricule == matricule
                )
            )
        ).scalar_one_or_none()
        if unit is not None:
            sector_nom_rue = unit.nom_rue
            sector_municipalite = sector_municipalite or unit.municipalite
            sector_region = sector_region or unit.region
    elif address:
        civic, rue = _parse_civic_street(address)
        if rue:
            sector_nom_rue = rue
            unit = await _find_unit(db, civique=civic, nom_rue=rue)
            if unit is not None:
                sector_nom_rue = unit.nom_rue or sector_nom_rue
                sector_municipalite = (
                    sector_municipalite or unit.municipalite
                )
                sector_region = sector_region or unit.region

    # nom_rue_contains direct prime sur le secteur déduit si fourni.
    rue_filter = nom_rue_contains or sector_nom_rue

    # 2) Refresh : scrape Numériq best-effort.
    if refresh and scraping_proxy.vps_available():
        try:
            items = await scraping_proxy.scrape_numeriq_comparables(
                nom_rue=rue_filter,
                municipalite=sector_municipalite,
                region=sector_region,
                limit=50,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("numeriq scrape failed: %s", exc)
            items = None
        if items:
            await _upsert_scraped(db, items, sector_region)

    # 3) Query la table avec tous les filtres.
    filters = []
    if rue_filter:
        filters.append(
            SoldComparable.nom_rue.ilike(f"%{rue_filter.strip()}%")
        )
    if sector_municipalite:
        filters.append(
            SoldComparable.municipalite == sector_municipalite.strip()
        )
    if sector_region:
        filters.append(SoldComparable.region == sector_region)
    if min_price is not None:
        filters.append(SoldComparable.price >= min_price)
    if max_price is not None:
        filters.append(SoldComparable.price <= max_price)
    if min_logements is not None:
        filters.append(SoldComparable.nb_logement >= min_logements)
    if max_logements is not None:
        filters.append(SoldComparable.nb_logement <= max_logements)
    if min_annee is not None:
        filters.append(SoldComparable.annee_construction >= min_annee)
    if max_annee is not None:
        filters.append(SoldComparable.annee_construction <= max_annee)
    if sold_since is not None:
        filters.append(SoldComparable.date_sold >= sold_since)

    stmt = select(SoldComparable)
    for f in filters:
        stmt = stmt.where(f)
    stmt = (
        stmt.order_by(
            SoldComparable.date_sold.desc().nullslast(),
            SoldComparable.price.desc().nullslast(),
        )
        .offset(offset)
        .limit(limit)
    )
    rows = (await db.execute(stmt)).scalars().all()

    count_stmt = select(func.count()).select_from(SoldComparable)
    for f in filters:
        count_stmt = count_stmt.where(f)
    total = int((await db.execute(count_stmt)).scalar() or 0)

    await log_action(
        db,
        user=current_user,
        action="comparables.search",
        entity_type="comparable",
        details={
            "nom_rue": rue_filter,
            "municipalite": sector_municipalite,
            "region": sector_region,
            "matricule": matricule,
            "refresh": refresh,
            "results": len(rows),
        },
    )

    return ListResponse(
        total=total,
        comparables=[_to_read(r) for r in rows],
    )


async def _upsert_scraped(
    db: AsyncSession,
    items: List[dict],
    fallback_region: Optional[str],
) -> None:
    """Insère les comparables scrapés en BD (dédup par
    address_full + date_sold + price), puis croise chacun avec
    `mtl_property_units` pour l'enrichir. Best-effort : une erreur sur
    un item ne bloque pas les autres."""
    for item in items:
        try:
            address_full = (item.get("address") or "").strip() or None
            civique = (item.get("civique") or "").strip() or None
            nom_rue = (item.get("nom_rue") or "").strip() or None
            municipalite = (item.get("municipalite") or "").strip() or None
            region = (item.get("region") or "").strip() or fallback_region

            price = item.get("price")
            try:
                price = float(price) if price is not None else None
            except (TypeError, ValueError):
                price = None

            date_sold: Optional[date] = None
            raw_date = item.get("date_sold")
            if raw_date:
                try:
                    date_sold = date.fromisoformat(str(raw_date)[:10])
                except (TypeError, ValueError):
                    date_sold = None

            # Dédup : address_full + date_sold + price.
            existing = (
                await db.execute(
                    select(SoldComparable).where(
                        and_(
                            SoldComparable.address_full == address_full,
                            SoldComparable.date_sold == date_sold,
                            SoldComparable.price == price,
                        )
                    )
                )
            ).scalars().first()
            if existing is not None:
                continue

            search_key = _compute_search_key(civique, nom_rue)
            comp = SoldComparable(
                civique=civique,
                nom_rue=nom_rue,
                municipalite=municipalite,
                region=region,
                address_full=address_full,
                search_key=search_key,
                price=price,
                date_sold=date_sold,
                source="numeriq",
                source_url=(item.get("source_url") or None),
                raw_json=json.dumps(
                    item.get("raw") or item, default=str
                ),
                fetched_at=datetime.now(timezone.utc),
            )
            unit = await _find_unit(db, civique=civique, nom_rue=nom_rue)
            _enrich_from_unit(comp, unit)
            db.add(comp)
        except Exception as exc:  # noqa: BLE001
            log.warning("skip malformed comparable: %s", exc)
            continue
    try:
        await db.flush()
    except Exception as exc:  # noqa: BLE001
        log.warning("flush of scraped comparables failed: %s", exc)


@router.post(
    "/manual",
    response_model=ComparableRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_manual(
    body: ManualComparableIn,
    db: DBSession,
    current_user: CurrentUser,
) -> ComparableRead:
    """Ajoute un comparable saisi à la main. On calcule la search_key
    et on croise avec le rôle d'évaluation pour auto-enrichir les
    champs laissés vides (nb logements, année, superficie, libellé)."""
    search_key = _compute_search_key(body.civique, body.nom_rue)
    address_full = body.address_full
    if not address_full:
        parts = [
            (body.civique or "").strip(),
            (body.nom_rue or "").strip(),
        ]
        address_full = " ".join(p for p in parts if p) or None

    comp = SoldComparable(
        matricule=body.matricule,
        civique=body.civique,
        nom_rue=body.nom_rue,
        municipalite=body.municipalite,
        region=body.region,
        address_full=address_full,
        search_key=search_key,
        price=body.price,
        date_sold=body.date_sold,
        nb_logement=body.nb_logement,
        annee_construction=body.annee_construction,
        superficie_terrain=body.superficie_terrain,
        libelle_utilisation=body.libelle_utilisation,
        source="manual",
        source_url=body.source_url,
        created_by_email=current_user.email,
    )

    unit = await _find_unit(
        db,
        matricule=body.matricule,
        civique=body.civique,
        nom_rue=body.nom_rue,
    )
    _enrich_from_unit(comp, unit)

    db.add(comp)
    await db.flush()
    await db.refresh(comp)

    await log_action(
        db,
        user=current_user,
        action="comparables.create_manual",
        entity_type="comparable",
        entity_id=comp.id,
        details={
            "address_full": comp.address_full,
            "price": float(comp.price) if comp.price is not None else None,
            "date_sold": (
                comp.date_sold.isoformat() if comp.date_sold else None
            ),
        },
    )

    return _to_read(comp)


@router.delete("/{comparable_id}")
async def delete_comparable(
    comparable_id: int,
    db: DBSession,
    current_user: CurrentUser,
) -> dict:
    """Supprime un comparable. Suppression réelle assumée : c'est
    l'outil personnel de l'utilisateur sur SES données saisies."""
    comp = (
        await db.execute(
            select(SoldComparable).where(
                SoldComparable.id == comparable_id
            )
        )
    ).scalar_one_or_none()
    if comp is None:
        raise HTTPException(404, "Comparable introuvable")

    await db.delete(comp)
    await db.flush()

    await log_action(
        db,
        user=current_user,
        action="comparables.delete",
        entity_type="comparable",
        entity_id=comparable_id,
        details={"address_full": comp.address_full},
    )

    return {"deleted": comparable_id}


@router.get("/health", response_model=HealthResponse)
async def comparables_health(
    db: DBSession,
    _: CurrentUser,
) -> HealthResponse:
    """État du cache de comparables + du lien VPS (scraping Numériq)."""
    cache_count = int(
        (
            await db.execute(
                select(func.count()).select_from(SoldComparable)
            )
        ).scalar()
        or 0
    )

    vps_url_set = bool(scraping_proxy.VPS_URL)
    vps_key_set = bool(scraping_proxy.VPS_KEY)
    vps_reachable = False
    if vps_url_set and vps_key_set:
        try:
            vps_reachable = await scraping_proxy.is_vps_healthy()
        except Exception:  # noqa: BLE001
            vps_reachable = False

    return HealthResponse(
        cache_count=cache_count,
        vps_url_set=vps_url_set,
        vps_key_set=vps_key_set,
        vps_reachable=vps_reachable,
        journal_source_configured=bool(
            os.environ.get("NUMERIQ_USERNAME")
        ),
    )
