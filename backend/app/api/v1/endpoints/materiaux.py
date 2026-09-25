"""Catalogue de MATÉRIAUX — prix par magasin, comparatif, import Excel
(retour 2026-09-25).

    GET    /magasins                      liste des détaillants
    POST   /magasins                      créer un détaillant
    PATCH  /magasins/{id}                 renommer / activer / site web

    GET    /materiaux?q=&categorie=&magasin_id=&actifs=
                                          matériaux + offres par magasin +
                                          meilleur prix
    POST   /materiaux                     créer un matériau
    PATCH  /materiaux/{id}                modifier (nom, catégorie, unité…)
    DELETE /materiaux/{id}                désactiver
    PUT    /materiaux/{id}/offres/{magasin_id}
                                          poser / corriger le prix d'un
                                          magasin (rabais, fin de rabais,
                                          lien) — historisé
    DELETE /materiaux/{id}/offres/{magasin_id}
    GET    /materiaux/{id}/historique     prix observés (tendance)
    GET    /materiaux/categories          catégories existantes
    POST   /materiaux/import-xlsx         importer un classeur (voir
                                          services/materiaux_import.py)
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, File, HTTPException, Query, UploadFile, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentUser, DBSession, RequireManager
from app.models.materiau import (
    Magasin,
    Materiau,
    MateriauOffre,
    MateriauPrixHistorique,
)
from app.services.materiaux_import import (
    canonical_store,
    import_rows,
    norm_key,
    parse_workbook,
)

router = APIRouter(tags=["materiaux"])


# ───────────────────────────── Schémas ─────────────────────────────

class MagasinRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    website: Optional[str] = None
    color: Optional[str] = None
    is_active: bool = True


class MagasinCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    website: Optional[str] = Field(default=None, max_length=255)
    color: Optional[str] = Field(default=None, max_length=6)


class MagasinUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    website: Optional[str] = Field(default=None, max_length=255)
    color: Optional[str] = Field(default=None, max_length=6)
    is_active: Optional[bool] = None


class OffreRead(BaseModel):
    magasin_id: int
    magasin_name: str
    unit_price: Optional[float] = None
    regular_price: Optional[float] = None
    on_sale: bool = False
    sale_end: Optional[date] = None
    #: Rabais encore valide aujourd'hui (on_sale et fin non dépassée).
    sale_active: bool = False
    url: Optional[str] = None
    sku: Optional[str] = None
    source: str = "manuel"
    observed_at: Optional[datetime] = None
    note: Optional[str] = None


class OffreUpsert(BaseModel):
    unit_price: Optional[float] = Field(default=None, ge=0)
    regular_price: Optional[float] = Field(default=None, ge=0)
    on_sale: bool = False
    sale_end: Optional[date] = None
    url: Optional[str] = Field(default=None, max_length=500)
    sku: Optional[str] = Field(default=None, max_length=64)
    note: Optional[str] = Field(default=None, max_length=255)


class MateriauRead(BaseModel):
    id: int
    name: str
    categorie: Optional[str] = None
    unit: Optional[str] = None
    notes: Optional[str] = None
    is_active: bool = True
    updated_at: Optional[datetime] = None
    offres: List[OffreRead] = []
    #: Meilleur prix courant (parmi les offres avec prix) et son magasin.
    best_price: Optional[float] = None
    best_magasin_id: Optional[int] = None
    best_magasin_name: Optional[str] = None
    #: Vrai si le meilleur prix vient d'un prix d'archive sans date.
    best_is_archive: bool = False


class MateriauCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    categorie: Optional[str] = Field(default=None, max_length=80)
    unit: Optional[str] = Field(default=None, max_length=32)
    notes: Optional[str] = None


class MateriauUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    categorie: Optional[str] = Field(default=None, max_length=80)
    unit: Optional[str] = Field(default=None, max_length=32)
    notes: Optional[str] = None
    is_active: Optional[bool] = None


class HistoriqueRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    magasin_id: int
    unit_price: float
    regular_price: Optional[float] = None
    on_sale: bool = False
    sale_end: Optional[date] = None
    source: str
    observed_at: Optional[datetime] = None
    note: Optional[str] = None
    created_at: datetime


class ImportResult(BaseModel):
    lignes: int
    magasins_crees: int
    materiaux_crees: int
    offres_creees: int
    offres_mises_a_jour: int
    offres_inchangees: int
    offres_conservees_manuel: int


# ───────────────────────────── Helpers ─────────────────────────────

def _offre_read(o: MateriauOffre, magasins: dict[int, Magasin]) -> OffreRead:
    today = date.today()
    sale_active = bool(o.on_sale) and (o.sale_end is None or o.sale_end >= today)
    m = magasins.get(o.magasin_id)
    return OffreRead(
        magasin_id=o.magasin_id,
        magasin_name=(m.name if m else f"#{o.magasin_id}"),
        unit_price=(float(o.unit_price) if o.unit_price is not None else None),
        regular_price=(float(o.regular_price) if o.regular_price is not None else None),
        on_sale=bool(o.on_sale),
        sale_end=o.sale_end,
        sale_active=sale_active,
        url=o.url, sku=o.sku, source=o.source, observed_at=o.observed_at,
        note=o.note,
    )


def _materiau_read(m: Materiau, magasins: dict[int, Magasin]) -> MateriauRead:
    offres = [
        _offre_read(o, magasins)
        for o in sorted(m.offres, key=lambda x: (x.unit_price is None, float(x.unit_price or 0)))
        if magasins.get(o.magasin_id) is None or magasins[o.magasin_id].is_active
    ]
    priced = [o for o in offres if o.unit_price is not None]
    best = min(priced, key=lambda o: o.unit_price) if priced else None
    return MateriauRead(
        id=m.id, name=m.name, categorie=m.categorie, unit=m.unit, notes=m.notes,
        is_active=m.is_active, updated_at=m.updated_at, offres=offres,
        best_price=(best.unit_price if best else None),
        best_magasin_id=(best.magasin_id if best else None),
        best_magasin_name=(best.magasin_name if best else None),
        best_is_archive=bool(best and best.source == "import" and best.observed_at is None),
    )


async def _magasins_map(db) -> dict[int, Magasin]:
    return {m.id: m for m in (await db.execute(select(Magasin))).scalars().all()}


async def _get_materiau(db, materiau_id: int) -> Materiau:
    m = (
        await db.execute(
            select(Materiau)
            .options(selectinload(Materiau.offres))
            .where(Materiau.id == materiau_id)
        )
    ).scalar_one_or_none()
    if m is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Matériau introuvable.")
    return m


# ───────────────────────────── Magasins ─────────────────────────────

@router.get("/magasins", response_model=List[MagasinRead])
async def list_magasins(db: DBSession, _: CurrentUser) -> List[MagasinRead]:
    rows = (
        await db.execute(select(Magasin).order_by(Magasin.is_active.desc(), Magasin.name.asc()))
    ).scalars().all()
    return [MagasinRead.model_validate(r) for r in rows]


@router.post("/magasins", response_model=MagasinRead, status_code=201)
async def create_magasin(data: MagasinCreate, db: DBSession, _: RequireManager) -> MagasinRead:
    name = canonical_store(data.name) or data.name.strip()
    existing = (
        await db.execute(select(Magasin).where(func.lower(Magasin.name) == name.lower()))
    ).scalar_one_or_none()
    if existing is not None:
        if not existing.is_active:
            existing.is_active = True
            await db.flush()
        return MagasinRead.model_validate(existing)
    m = Magasin(name=name, website=(data.website or None), color=(data.color or None))
    db.add(m)
    await db.flush()
    return MagasinRead.model_validate(m)


@router.patch("/magasins/{magasin_id}", response_model=MagasinRead)
async def update_magasin(
    magasin_id: int, data: MagasinUpdate, db: DBSession, _: RequireManager
) -> MagasinRead:
    m = (await db.execute(select(Magasin).where(Magasin.id == magasin_id))).scalar_one_or_none()
    if m is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Magasin introuvable.")
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(m, k, v.strip() if isinstance(v, str) else v)
    await db.flush()
    return MagasinRead.model_validate(m)


# ───────────────────────────── Matériaux ─────────────────────────────

@router.get("/materiaux/categories", response_model=List[str])
async def list_categories(db: DBSession, _: CurrentUser) -> List[str]:
    rows = (
        await db.execute(
            select(Materiau.categorie)
            .where(Materiau.categorie.is_not(None), Materiau.is_active.is_(True))
            .distinct()
            .order_by(Materiau.categorie.asc())
        )
    ).scalars().all()
    return [r for r in rows if r]


@router.get("/materiaux", response_model=List[MateriauRead])
async def list_materiaux(
    db: DBSession,
    _: CurrentUser,
    q: Optional[str] = Query(default=None, max_length=120),
    categorie: Optional[str] = Query(default=None, max_length=80),
    magasin_id: Optional[int] = Query(default=None),
    actifs: bool = Query(default=True),
    limit: int = Query(default=500, ge=1, le=2000),
) -> List[MateriauRead]:
    stmt = select(Materiau).options(selectinload(Materiau.offres))
    if actifs:
        stmt = stmt.where(Materiau.is_active.is_(True))
    if categorie:
        stmt = stmt.where(Materiau.categorie == categorie)
    if q:
        stmt = stmt.where(Materiau.name_key.contains(norm_key(q)))
    if magasin_id:
        stmt = stmt.where(
            Materiau.id.in_(
                select(MateriauOffre.materiau_id).where(MateriauOffre.magasin_id == magasin_id)
            )
        )
    stmt = stmt.order_by(Materiau.categorie.asc().nulls_last(), Materiau.name.asc()).limit(limit)
    rows = (await db.execute(stmt)).scalars().unique().all()
    magasins = await _magasins_map(db)
    return [_materiau_read(m, magasins) for m in rows]


@router.post("/materiaux", response_model=MateriauRead, status_code=201)
async def create_materiau(data: MateriauCreate, db: DBSession, _: CurrentUser) -> MateriauRead:
    key = norm_key(data.name)
    existing = (
        await db.execute(
            select(Materiau).options(selectinload(Materiau.offres)).where(Materiau.name_key == key)
        )
    ).scalar_one_or_none()
    if existing is not None:
        if not existing.is_active:
            existing.is_active = True
            await db.flush()
        return _materiau_read(existing, await _magasins_map(db))
    m = Materiau(
        name=data.name.strip(), name_key=key[:255],
        categorie=(data.categorie or None), unit=(data.unit or None),
        notes=(data.notes or None),
    )
    db.add(m)
    await db.flush()
    m = await _get_materiau(db, m.id)
    return _materiau_read(m, await _magasins_map(db))


@router.patch("/materiaux/{materiau_id}", response_model=MateriauRead)
async def update_materiau(
    materiau_id: int, data: MateriauUpdate, db: DBSession, _: CurrentUser
) -> MateriauRead:
    m = await _get_materiau(db, materiau_id)
    fields = data.model_dump(exclude_unset=True)
    if "name" in fields and fields["name"]:
        m.name = fields["name"].strip()
        m.name_key = norm_key(m.name)[:255]
    for k in ("categorie", "unit", "notes", "is_active"):
        if k in fields:
            v = fields[k]
            setattr(m, k, (v.strip() or None) if isinstance(v, str) else v)
    await db.flush()
    return _materiau_read(m, await _magasins_map(db))


@router.delete("/materiaux/{materiau_id}", status_code=204)
async def deactivate_materiau(materiau_id: int, db: DBSession, _: CurrentUser) -> None:
    m = await _get_materiau(db, materiau_id)
    m.is_active = False
    await db.flush()


@router.put("/materiaux/{materiau_id}/offres/{magasin_id}", response_model=MateriauRead)
async def upsert_offre(
    materiau_id: int, magasin_id: int, data: OffreUpsert, db: DBSession, _: CurrentUser
) -> MateriauRead:
    """Pose ou corrige le prix d'un magasin (source = manuel). Chaque
    changement de prix alimente l'historique."""
    m = await _get_materiau(db, materiau_id)
    mag = (await db.execute(select(Magasin).where(Magasin.id == magasin_id))).scalar_one_or_none()
    if mag is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Magasin introuvable.")
    off = next((o for o in m.offres if o.magasin_id == magasin_id), None)
    now = datetime.now(timezone.utc)
    if off is None:
        off = MateriauOffre(materiau_id=m.id, magasin_id=magasin_id, source="manuel")
        db.add(off)
        m.offres.append(off)
    changed = (
        off.unit_price is None
        or data.unit_price is None
        or abs(float(off.unit_price) - float(data.unit_price)) >= 0.005
        or bool(off.on_sale) != data.on_sale
        or off.sale_end != data.sale_end
    )
    off.unit_price = data.unit_price
    off.regular_price = data.regular_price
    off.on_sale = bool(data.on_sale)
    off.sale_end = data.sale_end
    if data.url is not None:
        off.url = data.url.strip() or None
    if data.sku is not None:
        off.sku = data.sku.strip() or None
    if data.note is not None:
        off.note = data.note.strip() or None
    off.source = "manuel"
    off.observed_at = now
    if changed and data.unit_price is not None:
        db.add(MateriauPrixHistorique(
            materiau_id=m.id, magasin_id=magasin_id, unit_price=float(data.unit_price),
            regular_price=data.regular_price, on_sale=bool(data.on_sale),
            sale_end=data.sale_end, source="manuel", observed_at=now,
            note=(off.note or None),
        ))
    await db.flush()
    m = await _get_materiau(db, m.id)
    return _materiau_read(m, await _magasins_map(db))


@router.delete("/materiaux/{materiau_id}/offres/{magasin_id}", response_model=MateriauRead)
async def delete_offre(
    materiau_id: int, magasin_id: int, db: DBSession, _: CurrentUser
) -> MateriauRead:
    m = await _get_materiau(db, materiau_id)
    off = next((o for o in m.offres if o.magasin_id == magasin_id), None)
    if off is not None:
        m.offres.remove(off)
        await db.delete(off)
        await db.flush()
    m = await _get_materiau(db, m.id)
    return _materiau_read(m, await _magasins_map(db))


@router.get("/materiaux/{materiau_id}/historique", response_model=List[HistoriqueRead])
async def historique(materiau_id: int, db: DBSession, _: CurrentUser) -> List[HistoriqueRead]:
    await _get_materiau(db, materiau_id)
    rows = (
        await db.execute(
            select(MateriauPrixHistorique)
            .where(MateriauPrixHistorique.materiau_id == materiau_id)
            .order_by(MateriauPrixHistorique.created_at.desc())
            .limit(200)
        )
    ).scalars().all()
    return [HistoriqueRead.model_validate(r) for r in rows]


@router.post("/materiaux/import-xlsx", response_model=ImportResult)
async def import_xlsx(
    db: DBSession, _: RequireManager, file: UploadFile = File(...)
) -> ImportResult:
    """Importe un classeur Excel de matériaux (onglets « liste » avec
    MATÉRIAUX / DÉTAILLANT / PRIX UNITAIRE, ou « matrice » magasins en
    colonnes). Idempotent."""
    name = (file.filename or "").lower()
    if not name.endswith((".xlsx", ".xlsm")):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Fichier .xlsx attendu.")
    content = await file.read()
    if len(content) > 15 * 1024 * 1024:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Fichier trop volumineux (15 Mo max).")
    try:
        rows = parse_workbook(content)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Classeur illisible : {exc}")
    if not rows:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Aucune ligne de matériau reconnue (attendu : colonnes MATÉRIAUX / "
            "DÉTAILLANT / PRIX UNITAIRE, ou magasins en colonnes).",
        )
    stats = await import_rows(db, rows, source_label=(file.filename or "fichier"))
    return ImportResult(**stats)
