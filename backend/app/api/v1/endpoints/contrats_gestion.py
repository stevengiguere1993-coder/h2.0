"""Endpoints authentifiés — Contrats de gestion (onglet fiche immeuble).

    GET    /contrats-gestion?immeuble_id=X      liste (onglet)
    POST   /contrats-gestion                    créer un brouillon auto-rempli
    GET    /contrats-gestion/template           gabarit courant
    PUT    /contrats-gestion/template           éditer le gabarit (admin+)
    GET    /contrats-gestion/{id}               détail (+ corps rendu)
    PATCH  /contrats-gestion/{id}               éditer les champs (brouillon)
    POST   /contrats-gestion/{id}/send          envoyer pour signature
    GET    /contrats-gestion/{id}/pdf           PDF (aperçu)
    GET    /contrats-gestion/{id}/signed-pdf    PDF signé immuable
    DELETE /contrats-gestion/{id}               supprimer (brouillon)

Les routes littérales (`/template`) sont déclarées AVANT `/{contrat_id}`
pour ne pas être capturées par le paramètre entier.
"""

from __future__ import annotations

from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict

from app.api.deps import CurrentUser, DBSession, RequireManager
from app.models.contrat_gestion import (
    ContratGestion,
    ContratGestionStatus,
    ContratGestionTemplate,
)
from app.models.user import User
from app.services.permissions_service import require_capability
from app.services.audit import log_action
from app.services.contrat_gestion_pdf import (
    contrat_pdf_filename,
    render_contrat_pdf,
)
from app.services.contrat_gestion_send import (
    ContratGestionSendError,
    send_to_mandataire,
)
from app.services.contrat_gestion_service import (
    autofill_values,
    get_template_markdown,
    resolve_body_markdown,
)
from sqlalchemy import select
from sqlalchemy.orm import undefer

router = APIRouter(prefix="/contrats-gestion", tags=["contrats-gestion"])


# --------------------------- Schemas ---------------------------


_EDITABLE_FIELDS = (
    "compagnie", "siege_social", "representant_nom", "representant_titre",
    "immeubles_adresses", "district_judiciaire", "mandant_courriel",
    "lieu_signature", "caution_requise", "caution_nom",
    "mandataire_nom", "mandataire_courriel", "corps_template_override",
)


class ContratCreate(BaseModel):
    immeuble_id: int


class ContratUpdate(BaseModel):
    compagnie: Optional[str] = None
    siege_social: Optional[str] = None
    representant_nom: Optional[str] = None
    representant_titre: Optional[str] = None
    immeubles_adresses: Optional[str] = None
    district_judiciaire: Optional[str] = None
    mandant_courriel: Optional[str] = None
    lieu_signature: Optional[str] = None
    caution_requise: Optional[bool] = None
    caution_nom: Optional[str] = None
    mandataire_nom: Optional[str] = None
    mandataire_courriel: Optional[str] = None
    # Gabarit propre à ce contrat (négociation). `null` = réinitialiser
    # au gabarit global. Non fourni = inchangé.
    corps_template_override: Optional[str] = None


class ContratRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    immeuble_id: int
    entreprise_id: Optional[int]
    compagnie: Optional[str]
    siege_social: Optional[str]
    representant_nom: Optional[str]
    representant_titre: Optional[str]
    immeubles_adresses: Optional[str]
    district_judiciaire: Optional[str]
    mandant_courriel: Optional[str]
    lieu_signature: Optional[str]
    caution_requise: bool
    caution_nom: Optional[str]
    mandataire_nom: Optional[str] = None
    mandataire_courriel: Optional[str] = None
    status: str
    sent_at: Optional[str] = None
    opened_at: Optional[str] = None
    open_count: int = 0
    mandataire_signed_at: Optional[str] = None
    mandataire_signed_name: Optional[str] = None
    signed_at: Optional[str] = None
    signed_name: Optional[str] = None
    has_signed_pdf: bool = False
    has_custom_body: bool = False
    sign_url: Optional[str] = None


class ContratDetail(ContratRead):
    body_markdown: str = ""
    # Gabarit propre au contrat (RAW, avec placeholders), ou null si on
    # utilise le gabarit global. Pour l'éditeur de personnalisation.
    custom_template_markdown: Optional[str] = None


class TemplateRead(BaseModel):
    corps_markdown: str


class TemplateUpdate(BaseModel):
    corps_markdown: str


# --------------------------- Helpers ---------------------------


def _iso(dt) -> Optional[str]:
    return dt.isoformat() if dt is not None else None


async def _load(db, contrat_id: int) -> ContratGestion:
    contrat = (
        await db.execute(
            select(ContratGestion).where(ContratGestion.id == contrat_id)
        )
    ).scalar_one_or_none()
    if contrat is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Contrat introuvable.")
    return contrat


def _to_read(contrat: ContratGestion) -> ContratRead:
    from app.services.public_links import public_base

    base = public_base()
    # Le lien copiable reflète l'étape courante : signature MGV en
    # attente → lien Mandataire ; sinon → lien Mandant (s'il existe).
    sign_url = None
    if (
        contrat.status == ContratGestionStatus.ATTENTE_MGV.value
        and contrat.mandataire_signature_token
    ):
        sign_url = f"{base}/sign-contrat-gestion/{contrat.mandataire_signature_token}"
    elif contrat.signature_token:
        sign_url = f"{base}/sign-contrat-gestion/{contrat.signature_token}"
    return ContratRead(
        id=contrat.id,
        immeuble_id=contrat.immeuble_id,
        entreprise_id=contrat.entreprise_id,
        compagnie=contrat.compagnie,
        siege_social=contrat.siege_social,
        representant_nom=contrat.representant_nom,
        representant_titre=contrat.representant_titre,
        immeubles_adresses=contrat.immeubles_adresses,
        district_judiciaire=contrat.district_judiciaire,
        mandant_courriel=contrat.mandant_courriel,
        lieu_signature=contrat.lieu_signature,
        caution_requise=contrat.caution_requise,
        caution_nom=contrat.caution_nom,
        mandataire_nom=contrat.mandataire_nom,
        mandataire_courriel=contrat.mandataire_courriel,
        status=contrat.status,
        sent_at=_iso(contrat.sent_at),
        opened_at=_iso(contrat.opened_at),
        open_count=contrat.open_count or 0,
        mandataire_signed_at=_iso(contrat.mandataire_signed_at),
        mandataire_signed_name=contrat.mandataire_signed_name,
        signed_at=_iso(contrat.signed_at),
        signed_name=contrat.signed_name,
        has_signed_pdf=contrat.signed_pdf_blob is not None,
        has_custom_body=bool(
            (contrat.corps_template_override or "").strip()
        ),
        sign_url=sign_url,
    )


# --------------------------- Liste & création ---------------------------


@router.get("", response_model=list[ContratRead], summary="Liste (par immeuble)")
async def list_contrats(
    db: DBSession,
    _: CurrentUser,
    immeuble_id: int = Query(...),
) -> list[ContratRead]:
    rows = (
        await db.execute(
            select(ContratGestion)
            .where(ContratGestion.immeuble_id == immeuble_id)
            .order_by(ContratGestion.id.desc())
        )
    ).scalars().all()
    return [_to_read(c) for c in rows]


@router.post(
    "",
    response_model=ContratDetail,
    status_code=status.HTTP_201_CREATED,
    summary="Créer un brouillon auto-rempli",
)
async def create_contrat(
    data: ContratCreate,
    db: DBSession,
    user: RequireManager,
) -> ContratDetail:
    values = await autofill_values(db, data.immeuble_id)
    if not values:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Immeuble introuvable.")
    contrat = ContratGestion(
        immeuble_id=data.immeuble_id,
        entreprise_id=values.get("entreprise_id"),
        compagnie=values.get("compagnie"),
        siege_social=values.get("siege_social"),
        representant_nom=values.get("representant_nom"),
        representant_titre=values.get("representant_titre"),
        immeubles_adresses=values.get("immeubles_adresses"),
        district_judiciaire=values.get("district_judiciaire"),
        mandant_courriel=values.get("mandant_courriel"),
        lieu_signature=values.get("lieu_signature"),
        caution_nom=values.get("representant_nom"),
        mandataire_nom=values.get("mandataire_nom"),
        mandataire_courriel=values.get("mandataire_courriel"),
        status=ContratGestionStatus.BROUILLON.value,
    )
    db.add(contrat)
    await db.flush()
    await db.refresh(contrat)
    try:
        await log_action(
            db, user=user, action="contrat_gestion.created",
            entity_type="contrat_gestion", entity_id=contrat.id,
            details={"immeuble_id": data.immeuble_id},
        )
    except Exception:
        pass
    await db.commit()
    body = await resolve_body_markdown(db, contrat)
    return ContratDetail(
        **_to_read(contrat).model_dump(),
        body_markdown=body,
        custom_template_markdown=contrat.corps_template_override,
    )


# --------------------------- Gabarit (avant /{id}) ---------------------------


@router.get("/template", response_model=TemplateRead, summary="Gabarit courant")
async def get_template(db: DBSession, _: CurrentUser) -> TemplateRead:
    return TemplateRead(corps_markdown=await get_template_markdown(db))


@router.put(
    "/template", response_model=TemplateRead, summary="Éditer le gabarit (admin+)"
)
async def put_template(
    data: TemplateUpdate,
    db: DBSession,
    user: Annotated[
        User, Depends(require_capability("contrat_gestion.template_edit"))
    ],
) -> TemplateRead:
    body = (data.corps_markdown or "").strip()
    if len(body) < 50:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Le gabarit du contrat est trop court.",
        )
    tpl = (
        await db.execute(
            select(ContratGestionTemplate).where(ContratGestionTemplate.id == 1)
        )
    ).scalar_one_or_none()
    if tpl is None:
        tpl = ContratGestionTemplate(id=1, corps_markdown=data.corps_markdown)
        db.add(tpl)
    else:
        tpl.corps_markdown = data.corps_markdown
    tpl.updated_by_user_id = user.id
    await db.flush()
    try:
        await log_action(
            db, user=user, action="contrat_gestion.template_updated",
            entity_type="contrat_gestion_template", entity_id=1,
            details={"length": len(data.corps_markdown)},
        )
    except Exception:
        pass
    await db.commit()
    return TemplateRead(corps_markdown=tpl.corps_markdown)


# --------------------------- Détail / édition ---------------------------


@router.get("/{contrat_id}", response_model=ContratDetail, summary="Détail")
async def get_contrat(
    contrat_id: int, db: DBSession, _: CurrentUser
) -> ContratDetail:
    contrat = await _load(db, contrat_id)
    body = await resolve_body_markdown(db, contrat)
    return ContratDetail(
        **_to_read(contrat).model_dump(),
        body_markdown=body,
        custom_template_markdown=contrat.corps_template_override,
    )


@router.patch("/{contrat_id}", response_model=ContratDetail, summary="Éditer")
async def update_contrat(
    contrat_id: int, data: ContratUpdate, db: DBSession, user: RequireManager
) -> ContratDetail:
    contrat = await _load(db, contrat_id)
    if contrat.status == ContratGestionStatus.SIGNE.value:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Contrat déjà signé — non modifiable.",
        )
    payload = data.model_dump(exclude_unset=True)
    for field in _EDITABLE_FIELDS:
        if field in payload:
            setattr(contrat, field, payload[field])
    await db.flush()
    await db.refresh(contrat)
    await db.commit()
    body = await resolve_body_markdown(db, contrat)
    return ContratDetail(
        **_to_read(contrat).model_dump(),
        body_markdown=body,
        custom_template_markdown=contrat.corps_template_override,
    )


@router.post(
    "/{contrat_id}/send",
    response_model=ContratRead,
    summary="Envoyer pour signature (au Mandataire MGV d'abord)",
)
async def send_contrat(
    contrat_id: int, db: DBSession, user: RequireManager
) -> ContratRead:
    contrat = await _load(db, contrat_id)
    if contrat.status == ContratGestionStatus.SIGNE.value:
        raise HTTPException(status.HTTP_409_CONFLICT, "Contrat déjà signé.")
    try:
        contrat = await send_to_mandataire(db, contrat_id)
    except ContratGestionSendError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
    try:
        await log_action(
            db, user=user, action="contrat_gestion.sent",
            entity_type="contrat_gestion", entity_id=contrat.id,
            details={"to_mandataire": contrat.mandataire_courriel},
        )
    except Exception:
        pass
    await db.commit()
    return _to_read(contrat)


@router.get("/{contrat_id}/pdf", summary="PDF (aperçu)")
async def contrat_pdf(contrat_id: int, db: DBSession, _: CurrentUser) -> Response:
    contrat = await _load(db, contrat_id)
    body = await resolve_body_markdown(db, contrat)
    pdf_bytes = render_contrat_pdf(contrat, body)
    filename = contrat_pdf_filename(contrat)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


@router.get("/{contrat_id}/signed-pdf", summary="PDF signé immuable")
async def contrat_signed_pdf(
    contrat_id: int, db: DBSession, _: CurrentUser
) -> Response:
    contrat = (
        await db.execute(
            select(ContratGestion)
            .where(ContratGestion.id == contrat_id)
            .options(
                undefer(ContratGestion.signature_image),
                undefer(ContratGestion.mandataire_signature_image),
            )
        )
    ).scalar_one_or_none()
    if contrat is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Contrat introuvable.")
    if contrat.signed_pdf_blob:
        filename = contrat_pdf_filename(contrat, signed=True)
        return Response(
            content=contrat.signed_pdf_blob,
            media_type="application/pdf",
            headers={"Content-Disposition": f'inline; filename="{filename}"'},
        )
    # Repli : régénère si signé mais blob manquant (lazy).
    if contrat.signed_at is not None:
        from app.services.contrat_gestion_pdf import generate_signed_contrat_pdf

        body = await resolve_body_markdown(db, contrat)
        pdf_bytes = generate_signed_contrat_pdf(contrat, body)
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={
                "Content-Disposition": (
                    f'inline; filename="{contrat_pdf_filename(contrat, signed=True)}"'
                )
            },
        )
    raise HTTPException(status.HTTP_409_CONFLICT, "Contrat pas encore signé.")


@router.delete(
    "/{contrat_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Supprimer"
)
async def delete_contrat(
    contrat_id: int,
    db: DBSession,
    user: Annotated[
        User, Depends(require_capability("contrat_gestion.delete"))
    ],
) -> Response:
    # Suppression autorisée à tout statut (y compris signé) — le
    # frontend demande une confirmation renforcée pour un contrat signé.
    # Le PDF signé reste, le cas échéant, archivé dans Drive.
    contrat = await _load(db, contrat_id)
    was_signed = contrat.status == ContratGestionStatus.SIGNE.value
    await db.delete(contrat)
    try:
        await log_action(
            db, user=user, action="contrat_gestion.deleted",
            entity_type="contrat_gestion", entity_id=contrat_id,
            details={"was_signed": was_signed},
        )
    except Exception:
        pass
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
