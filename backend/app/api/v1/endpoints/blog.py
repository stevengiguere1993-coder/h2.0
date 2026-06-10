"""
Read-only public endpoints for the blog/SEO articles.
"""

from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from app.api.deps import DBSession
from app.models.seo_article import SeoArticle


router = APIRouter(prefix="/blog", tags=["blog"])


class ArticleSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    slug: str
    locale: str
    title: str
    excerpt: Optional[str]
    target_city: Optional[str]
    target_service: Optional[str]
    published_at: Optional[str] = None


class ArticleFull(ArticleSummary):
    meta_description: str
    content_md: str
    keywords: Optional[str] = None


@router.get(
    "",
    response_model=List[ArticleSummary],
    summary="List public SEO articles",
)
async def list_articles(
    db: DBSession,
    locale: str = Query(default="fr", pattern="^(fr|en)$"),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    service: Optional[str] = Query(default=None, max_length=64),
    city: Optional[str] = Query(default=None, max_length=120),
) -> List[ArticleSummary]:
    stmt = (
        select(SeoArticle)
        .where(SeoArticle.published.is_(True))
        .where(SeoArticle.locale == locale)
    )
    # Filtres optionnels — utilisés par les pages géo pour relier leurs
    # articles (même service / même ville).
    if service:
        stmt = stmt.where(SeoArticle.target_service == service)
    if city:
        stmt = stmt.where(SeoArticle.target_city == city)
    stmt = (
        stmt.order_by(
            SeoArticle.published_at.desc().nulls_last(),
            SeoArticle.created_at.desc(),
        )
        .offset(skip)
        .limit(limit)
    )
    rows = (await db.execute(stmt)).scalars().all()
    return [
        ArticleSummary(
            id=r.id,
            slug=r.slug,
            locale=r.locale,
            title=r.title,
            excerpt=r.excerpt,
            target_city=r.target_city,
            target_service=r.target_service,
            published_at=r.published_at.isoformat() if r.published_at else None,
        )
        for r in rows
    ]


class ArticleSitemapEntry(BaseModel):
    slug: str
    locale: str
    published_at: Optional[str] = None


@router.get(
    "/sitemap",
    response_model=List[ArticleSitemapEntry],
    summary="All published article slugs for the XML sitemap",
)
async def sitemap_articles(db: DBSession) -> List[ArticleSitemapEntry]:
    # Charge léger (slug + locale + date) de TOUS les articles publiés,
    # toutes locales. Consommé par frontend/src/app/sitemap.ts pour que
    # chaque /blog/{slug} soit découvrable par Google.
    stmt = (
        select(
            SeoArticle.slug, SeoArticle.locale, SeoArticle.published_at
        )
        .where(SeoArticle.published.is_(True))
        .order_by(SeoArticle.published_at.desc().nulls_last())
    )
    rows = (await db.execute(stmt)).all()
    return [
        ArticleSitemapEntry(
            slug=slug,
            locale=locale,
            published_at=pub.isoformat() if pub else None,
        )
        for slug, locale, pub in rows
    ]


@router.get(
    "/{slug}",
    response_model=ArticleFull,
    summary="Get a public SEO article by slug",
)
async def get_article(slug: str, db: DBSession) -> ArticleFull:
    stmt = select(SeoArticle).where(
        SeoArticle.slug == slug, SeoArticle.published.is_(True)
    )
    r = (await db.execute(stmt)).scalar_one_or_none()
    if r is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    return ArticleFull(
        id=r.id,
        slug=r.slug,
        locale=r.locale,
        title=r.title,
        excerpt=r.excerpt,
        target_city=r.target_city,
        target_service=r.target_service,
        published_at=r.published_at.isoformat() if r.published_at else None,
        meta_description=r.meta_description,
        content_md=r.content_md,
        keywords=r.keywords,
    )
