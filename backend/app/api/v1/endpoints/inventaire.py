"""Inventaire INTERNE — onglet « Inventaire » du catalogue de services
(Steven 2026-10-18). La logique (coût moyen, sortie → achat du projet,
annulation) vit dans ``services/inventaire.py``.

    GET    /inventaire/articles?q=&categorie=&actifs=
                                          articles, stock en main, coût
                                          moyen et valeur
    POST   /inventaire/articles           créer (stock de départ optionnel)
    PATCH  /inventaire/articles/{id}      nom, catégorie, unité, notes,
                                          actif, correction du coût moyen
    DELETE /inventaire/articles/{id}      supprimer (jamais sorti) ou
                                          désactiver (déjà sorti)
    GET    /inventaire/categories         catégories existantes
    POST   /inventaire/articles/{id}/entree
                                          ajouter au stock
    POST   /inventaire/articles/{id}/ajustement
                                          corriger d'après un compte réel
    POST   /inventaire/articles/{id}/sortie
                                          sortir vers un projet → achat
                                          « Inventaire interne » du projet
    GET    /inventaire/sortie-defaut?project_id=
                                          « à refacturer » par défaut
    GET    /inventaire/mouvements?article_id=&project_id=&limit=
                                          historique (plus récent d'abord)
    DELETE /inventaire/mouvements/{id}    annuler une sortie (retour en
                                          stock, achat du projet retiré)
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select

from app.api.deps import CurrentUser, DBSession, RequireManager
from app.models.achat import Achat
from app.models.inventaire import InventaireArticle, InventaireMouvement
from app.models.project import Project
from app.models.user import User
from app.services import inventaire as svc

router = APIRouter(prefix="/inventaire", tags=["inventaire"])


# ───────────────────────────── Schémas ─────────────────────────────

class ArticleRead(BaseModel):
    id: int
    name: str
    categorie: Optional[str] = None
    unit: Optional[str] = None
    quantite: float = 0
    #: Coût unitaire MOYEN hors taxes — chargé au projet à la sortie.
    cout_unitaire: Optional[float] = None
    #: Valeur du stock en main (quantité × coût moyen), hors taxes.
    valeur: Optional[float] = None
    notes: Optional[str] = None
    is_active: bool = True
    updated_at: Optional[datetime] = None


class ArticleCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    categorie: Optional[str] = Field(default=None, max_length=80)
    unit: Optional[str] = Field(default=None, max_length=32)
    notes: Optional[str] = None
    #: Stock de départ (tracé comme une entrée) et son coût unitaire HT.
    quantite: Optional[float] = Field(default=None, ge=0)
    cout_unitaire: Optional[float] = Field(default=None, ge=0)


class ArticleUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    categorie: Optional[str] = Field(default=None, max_length=80)
    unit: Optional[str] = Field(default=None, max_length=32)
    notes: Optional[str] = None
    is_active: Optional[bool] = None
    #: Correction du coût moyen — vaut pour les PROCHAINES sorties ; les
    #: sorties passées gardent le coût chargé à leur projet.
    cout_unitaire: Optional[float] = Field(default=None, ge=0)


class EntreeBody(BaseModel):
    quantite: float = Field(..., gt=0)
    #: Prix unitaire HT payé ; vide = coût moyen inchangé.
    cout_unitaire: Optional[float] = Field(default=None, ge=0)
    note: Optional[str] = Field(default=None, max_length=255)


class AjustementBody(BaseModel):
    #: Quantité réellement comptée.
    quantite: float = Field(..., ge=0)
    note: Optional[str] = Field(default=None, max_length=255)


class SortieBody(BaseModel):
    project_id: int
    quantite: float = Field(..., gt=0)
    #: Coût unitaire HT chargé ; vide = coût moyen de l'article.
    cout_unitaire: Optional[float] = Field(default=None, ge=0)
    #: « À refacturer » ; vide = règle du projet (contrat ou bon de
    #: travail → oui), comme un achat saisi.
    is_billable: Optional[bool] = None
    note: Optional[str] = Field(default=None, max_length=255)


class MouvementRead(BaseModel):
    id: int
    article_id: int
    article_name: str
    unit: Optional[str] = None
    type: str
    #: Variation signée du stock.
    quantite: float
    cout_unitaire: Optional[float] = None
    #: |quantité| × coût, hors taxes.
    montant: Optional[float] = None
    project_id: Optional[int] = None
    project_name: Optional[str] = None
    project_address: Optional[str] = None
    achat_id: Optional[int] = None
    is_billable: Optional[bool] = None
    #: Sortie déjà sur une facture : ne s'annule plus d'ici.
    refacturee: bool = False
    note: Optional[str] = None
    par: Optional[str] = None
    created_at: datetime


class SortieResult(BaseModel):
    article: ArticleRead
    mouvement: MouvementRead
    achat_id: int
    montant: float
    is_billable: bool


class SuppressionResult(BaseModel):
    #: « supprime » (jamais sorti) ou « desactive » (déjà chargé à un
    #: projet : l'historique est gardé).
    action: str


class SortieDefaut(BaseModel):
    is_billable: bool


# ───────────────────────────── Helpers ─────────────────────────────

def _article_read(a: InventaireArticle) -> ArticleRead:
    q = round(float(a.quantite or 0), 3)
    cout = None if a.cout_unitaire is None else float(a.cout_unitaire)
    return ArticleRead(
        id=a.id,
        name=a.name,
        categorie=a.categorie,
        unit=a.unit,
        quantite=q,
        cout_unitaire=cout,
        valeur=None if cout is None else round(q * cout, 2),
        notes=a.notes,
        is_active=bool(a.is_active),
        updated_at=a.updated_at,
    )


async def _get_article(db, article_id: int, *, verrou: bool = False) -> InventaireArticle:
    stmt = select(InventaireArticle).where(InventaireArticle.id == article_id)
    if verrou:
        # Deux sorties simultanées du même article ne peuvent pas vendre
        # deux fois le même stock.
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    a = (await db.execute(stmt)).scalar_one_or_none()
    if a is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Article introuvable.")
    return a


def _texte(v: Optional[str]) -> Optional[str]:
    return (v or "").strip() or None


async def _mouvements_read(db, mvs: list[InventaireMouvement]) -> List[MouvementRead]:
    # Articles relus par id : un mouvement tout juste créé n'a pas sa
    # relation chargée (chargement paresseux interdit en async).
    art_ids = {m.article_id for m in mvs}
    articles = (
        {
            a.id: a
            for a in (
                await db.execute(
                    select(InventaireArticle).where(InventaireArticle.id.in_(art_ids))
                )
            ).scalars()
        }
        if art_ids
        else {}
    )
    achat_ids = {m.achat_id for m in mvs if m.achat_id}
    achats = (
        {
            a.id: a
            for a in (
                await db.execute(select(Achat).where(Achat.id.in_(achat_ids)))
            ).scalars()
        }
        if achat_ids
        else {}
    )
    # Le projet de l'ACHAT fait foi (déplacé depuis la sortie, au besoin).
    proj_ids = {
        (achats[m.achat_id].project_id if m.achat_id in achats else None)
        or m.project_id
        for m in mvs
    } - {None}
    projets = (
        {
            p.id: p
            for p in (
                await db.execute(select(Project).where(Project.id.in_(proj_ids)))
            ).scalars()
        }
        if proj_ids
        else {}
    )
    user_ids = {m.created_by_user_id for m in mvs if m.created_by_user_id}
    users = (
        {
            u.id: u
            for u in (
                await db.execute(select(User).where(User.id.in_(user_ids)))
            ).scalars()
        }
        if user_ids
        else {}
    )
    out: List[MouvementRead] = []
    for m in mvs:
        achat = achats.get(m.achat_id) if m.achat_id else None
        pid = (achat.project_id if achat is not None else None) or m.project_id
        p = projets.get(pid) if pid else None
        q = round(float(m.quantite or 0), 3)
        cout = None if m.cout_unitaire is None else float(m.cout_unitaire)
        u = users.get(m.created_by_user_id) if m.created_by_user_id else None
        art = articles.get(m.article_id)
        out.append(
            MouvementRead(
                id=m.id,
                article_id=m.article_id,
                article_name=art.name if art else "",
                unit=art.unit if art else None,
                type=m.type,
                quantite=q,
                cout_unitaire=cout,
                montant=(
                    float(achat.amount or 0)
                    if achat is not None
                    else (None if cout is None else round(abs(q) * cout, 2))
                ),
                project_id=pid,
                project_name=p.name if p else None,
                project_address=p.address if p else None,
                achat_id=m.achat_id,
                is_billable=bool(achat.is_billable) if achat is not None else None,
                refacturee=bool(achat is not None and achat.invoiced_at is not None),
                note=m.note,
                par=(u.display_name or u.email) if u else None,
                created_at=m.created_at,
            )
        )
    return out


# ───────────────────────────── Articles ─────────────────────────────

@router.get("/articles", response_model=List[ArticleRead])
async def list_articles(
    db: DBSession,
    _: CurrentUser,
    q: Optional[str] = Query(default=None, max_length=120),
    categorie: Optional[str] = Query(default=None, max_length=80),
    actifs: bool = Query(default=True),
) -> List[ArticleRead]:
    stmt = select(InventaireArticle)
    if actifs:
        stmt = stmt.where(InventaireArticle.is_active.is_(True))
    if categorie:
        stmt = stmt.where(InventaireArticle.categorie == categorie)
    if q and q.strip():
        motif = f"%{q.strip().lower()}%"
        stmt = stmt.where(
            or_(
                func.lower(InventaireArticle.name).like(motif),
                func.lower(func.coalesce(InventaireArticle.categorie, "")).like(motif),
                func.lower(func.coalesce(InventaireArticle.notes, "")).like(motif),
            )
        )
    stmt = stmt.order_by(
        func.coalesce(InventaireArticle.categorie, "zzz"), InventaireArticle.name
    )
    return [_article_read(a) for a in (await db.execute(stmt)).scalars().all()]


@router.get("/categories", response_model=List[str])
async def list_categories(db: DBSession, _: CurrentUser) -> List[str]:
    rows = (
        await db.execute(
            select(InventaireArticle.categorie)
            .where(InventaireArticle.categorie.is_not(None))
            .distinct()
        )
    ).scalars().all()
    return sorted({r.strip() for r in rows if r and r.strip()}, key=str.lower)


@router.post("/articles", response_model=ArticleRead, status_code=201)
async def create_article(
    data: ArticleCreate, db: DBSession, user: RequireManager
) -> ArticleRead:
    a = InventaireArticle(
        name=data.name.strip(),
        categorie=_texte(data.categorie),
        unit=_texte(data.unit),
        notes=_texte(data.notes),
        quantite=0,
    )
    db.add(a)
    await db.flush()
    if data.quantite and data.quantite > 0:
        await svc.entrer(
            db, a, data.quantite,
            cout_unitaire=data.cout_unitaire,
            note="Stock de départ",
            user_id=user.id,
        )
    elif data.cout_unitaire is not None:
        a.cout_unitaire = round(float(data.cout_unitaire), 4)
    await db.flush()
    await db.refresh(a)
    return _article_read(a)


@router.patch("/articles/{article_id}", response_model=ArticleRead)
async def update_article(
    article_id: int, data: ArticleUpdate, db: DBSession, _: RequireManager
) -> ArticleRead:
    a = await _get_article(db, article_id)
    fields = data.model_dump(exclude_unset=True)
    if fields.get("name"):
        a.name = fields["name"].strip()
    for k in ("categorie", "unit", "notes"):
        if k in fields:
            setattr(a, k, _texte(fields[k]))
    if fields.get("is_active") is not None:
        a.is_active = bool(fields["is_active"])
    if "cout_unitaire" in fields:
        v = fields["cout_unitaire"]
        a.cout_unitaire = None if v is None else round(float(v), 4)
    await db.flush()
    await db.refresh(a)
    return _article_read(a)


@router.delete("/articles/{article_id}", response_model=SuppressionResult)
async def delete_article(
    article_id: int, db: DBSession, _: RequireManager
) -> SuppressionResult:
    a = await _get_article(db, article_id)
    deja_sorti = (
        await db.execute(
            select(InventaireMouvement.id)
            .where(
                InventaireMouvement.article_id == a.id,
                InventaireMouvement.type == svc.TYPE_SORTIE,
            )
            .limit(1)
        )
    ).first()
    if deja_sorti is not None:
        # Déjà chargé à un projet : l'historique reste lisible.
        a.is_active = False
        await db.flush()
        return SuppressionResult(action="desactive")
    await db.delete(a)
    await db.flush()
    return SuppressionResult(action="supprime")


# ──────────────────────────── Mouvements ────────────────────────────

@router.post("/articles/{article_id}/entree", response_model=ArticleRead)
async def entree(
    article_id: int, data: EntreeBody, db: DBSession, user: RequireManager
) -> ArticleRead:
    a = await _get_article(db, article_id, verrou=True)
    try:
        await svc.entrer(
            db, a, data.quantite,
            cout_unitaire=data.cout_unitaire,
            note=_texte(data.note),
            user_id=user.id,
        )
    except svc.InventaireErreur as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc))
    await db.refresh(a)
    return _article_read(a)


@router.post("/articles/{article_id}/ajustement", response_model=ArticleRead)
async def ajustement(
    article_id: int, data: AjustementBody, db: DBSession, user: RequireManager
) -> ArticleRead:
    a = await _get_article(db, article_id, verrou=True)
    try:
        await svc.ajuster(
            db, a, data.quantite, note=_texte(data.note), user_id=user.id
        )
    except svc.InventaireErreur as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc))
    await db.refresh(a)
    return _article_read(a)


@router.get("/sortie-defaut", response_model=SortieDefaut)
async def sortie_defaut(
    db: DBSession, _: CurrentUser, project_id: int = Query(...)
) -> SortieDefaut:
    p = await db.get(Project, project_id)
    if p is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Projet introuvable.")
    return SortieDefaut(is_billable=await svc.refacturable_par_defaut(db, p))


@router.post("/articles/{article_id}/sortie", response_model=SortieResult)
async def sortie(
    article_id: int, data: SortieBody, db: DBSession, user: RequireManager
) -> SortieResult:
    a = await _get_article(db, article_id, verrou=True)
    p = await db.get(Project, data.project_id)
    if p is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Projet introuvable.")
    try:
        mv, achat = await svc.sortir(
            db, a, p, data.quantite,
            cout_unitaire=data.cout_unitaire,
            is_billable=data.is_billable,
            note=_texte(data.note),
            user_id=user.id,
        )
    except svc.InventaireErreur as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc))
    await db.refresh(a)
    await db.refresh(mv)
    lu = (await _mouvements_read(db, [mv]))[0]
    return SortieResult(
        article=_article_read(a),
        mouvement=lu,
        achat_id=achat.id,
        montant=float(achat.amount or 0),
        is_billable=bool(achat.is_billable),
    )


@router.get("/mouvements", response_model=List[MouvementRead])
async def list_mouvements(
    db: DBSession,
    _: CurrentUser,
    article_id: Optional[int] = Query(default=None),
    project_id: Optional[int] = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
) -> List[MouvementRead]:
    stmt = select(InventaireMouvement)
    if article_id is not None:
        stmt = stmt.where(InventaireMouvement.article_id == article_id)
    if project_id is not None:
        stmt = stmt.where(InventaireMouvement.project_id == project_id)
    stmt = stmt.order_by(
        InventaireMouvement.created_at.desc(), InventaireMouvement.id.desc()
    ).limit(limit)
    mvs = list((await db.execute(stmt)).scalars().all())
    return await _mouvements_read(db, mvs)


@router.delete("/mouvements/{mouvement_id}", response_model=ArticleRead)
async def annuler_mouvement(
    mouvement_id: int, db: DBSession, _: RequireManager
) -> ArticleRead:
    mv = await db.get(InventaireMouvement, mouvement_id)
    if mv is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Mouvement introuvable.")
    a = await _get_article(db, mv.article_id, verrou=True)
    try:
        await svc.annuler_sortie(db, mv)
    except svc.InventaireErreur as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc))
    await db.refresh(a)
    return _article_read(a)
