"""API pour les analyses de leads immobiliers.

Endpoints :
    POST   /lead-analyses/extract   multipart : urls + text + files
                                    → crée une (ou plusieurs) fiche(s)
    GET    /lead-analyses           liste paginée + filtres
    GET    /lead-analyses/{id}      détail
    PATCH  /lead-analyses/{id}      MAJ partielle (édition fiche)
    DELETE /lead-analyses/{id}      suppression (cascade attachments)
    POST   /lead-analyses/{id}/convert-to-lead  → ProspectionLead
    GET    /lead-analyses/{id}/attachments/{att_id}  blob inline

Restreint au volet `prospection`.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import (
    APIRouter,
    File,
    Form,
    HTTPException,
    Response,
    UploadFile,
    status,
)
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select

from app.api.deps import CurrentUser, DBSession
from app.models.lead_analysis import (
    LeadAnalysis,
    LeadAnalysisAttachment,
    LeadAnalysisStatus,
)
from app.models.prospection_lead import (
    ProspectionLead,
    ProspectionLeadKind,
    ProspectionLeadStatus,
    ProspectionOwnerKind,
)
from app.services.lead_extraction import extract_lead_info


log = logging.getLogger(__name__)
router = APIRouter(prefix="/lead-analyses", tags=["lead-analyses"])


_MAX_FILE_BYTES = 10 * 1024 * 1024  # 10 MB / fichier


def _require_prospection(user: CurrentUser) -> None:
    """Restreint au volet prospection. Backward-compat : volets vide
    → on accepte (anciens users sans volets_json)."""
    volets = getattr(user, "volets", None) or []
    if volets and "prospection" not in volets:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Volet « Prospection » non autorisé.",
        )


# ── Schémas Pydantic ───────────────────────────────────────────────


class AttachmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    filename: str
    content_type: str
    size_bytes: int


class LeadAnalysisRead(BaseModel):
    """Détail complet d'une analyse — utilisé par la fiche."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    status: str
    position: int

    address: Optional[str] = None
    city: Optional[str] = None
    postal_code: Optional[str] = None
    province: Optional[str] = None
    asking_price: Optional[float] = None
    nb_logements: Optional[int] = None
    typology_json: Optional[str] = None
    revenus_bruts: Optional[float] = None
    taxes_municipales: Optional[float] = None
    taxes_scolaires: Optional[float] = None
    assurances: Optional[float] = None
    energie: Optional[float] = None
    depenses_autres: Optional[float] = None
    annee_construction: Optional[int] = None

    superficie_terrain: Optional[float] = None
    superficie_batiment: Optional[float] = None
    evaluation_municipale: Optional[float] = None
    description: Optional[str] = None
    courtier_nom: Optional[str] = None
    courtier_contact: Optional[str] = None
    type_batiment: Optional[str] = None
    nb_stationnements: Optional[int] = None

    source_urls: Optional[str] = None
    source_text: Optional[str] = None

    loyers_projetes_json: Optional[str] = None
    loyers_max_abordabilite_json: Optional[str] = None
    travaux_estimes: Optional[float] = None
    nb_logements_ajoutes: Optional[int] = None
    nb_thermopompes_ajoutees: Optional[int] = None
    ajout_wifi: Optional[bool] = None
    reduction_energie_pct: Optional[float] = None
    taux_interet_refi_pct: Optional[float] = None
    duree_projet_annees: Optional[int] = None
    frais_developpement: Optional[float] = None
    frais_negociations: Optional[float] = None

    analysis_results_json: Optional[str] = None
    best_refi_amount: Optional[float] = None
    notes: Optional[str] = None
    converted_to_lead_id: Optional[int] = None

    created_at: datetime
    updated_at: datetime

    attachments: List[AttachmentRead] = Field(default_factory=list)


class LeadAnalysisListItem(BaseModel):
    """Vue compacte pour la liste/kanban (sans le JSON détaillé)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    status: str
    position: int
    address: Optional[str]
    city: Optional[str]
    asking_price: Optional[float]
    nb_logements: Optional[int]
    annee_construction: Optional[int]
    best_refi_amount: Optional[float]
    type_batiment: Optional[str]
    converted_to_lead_id: Optional[int]
    created_at: datetime
    attachments_count: int = 0


class LeadAnalysisUpdate(BaseModel):
    """Tous les champs éditables — la fiche envoie un patch partiel."""

    status: Optional[str] = Field(
        default=None,
        pattern=r"^(a_analyser|decision_en_attente|interessant|abandonne)$",
    )
    position: Optional[int] = None

    address: Optional[str] = Field(default=None, max_length=500)
    city: Optional[str] = Field(default=None, max_length=120)
    postal_code: Optional[str] = Field(default=None, max_length=16)
    province: Optional[str] = Field(default=None, max_length=8)
    asking_price: Optional[float] = None
    nb_logements: Optional[int] = None
    typology_json: Optional[str] = None
    revenus_bruts: Optional[float] = None
    taxes_municipales: Optional[float] = None
    taxes_scolaires: Optional[float] = None
    assurances: Optional[float] = None
    energie: Optional[float] = None
    depenses_autres: Optional[float] = None
    annee_construction: Optional[int] = None

    superficie_terrain: Optional[float] = None
    superficie_batiment: Optional[float] = None
    evaluation_municipale: Optional[float] = None
    description: Optional[str] = None
    courtier_nom: Optional[str] = Field(default=None, max_length=255)
    courtier_contact: Optional[str] = Field(default=None, max_length=255)
    type_batiment: Optional[str] = Field(default=None, max_length=64)
    nb_stationnements: Optional[int] = None

    loyers_projetes_json: Optional[str] = None
    loyers_max_abordabilite_json: Optional[str] = None
    travaux_estimes: Optional[float] = None
    nb_logements_ajoutes: Optional[int] = None
    nb_thermopompes_ajoutees: Optional[int] = None
    ajout_wifi: Optional[bool] = None
    reduction_energie_pct: Optional[float] = None
    taux_interet_refi_pct: Optional[float] = None
    duree_projet_annees: Optional[int] = None
    frais_developpement: Optional[float] = None
    frais_negociations: Optional[float] = None

    notes: Optional[str] = None


class ExtractResult(BaseModel):
    """Réponse de l'endpoint extract — peut créer plusieurs leads
    si Claude détecte plusieurs immeubles distincts."""

    created: List[LeadAnalysisListItem]
    warnings: List[str] = Field(default_factory=list)
    model_used: Optional[str] = None


class ConvertResult(BaseModel):
    lead_id: int


# ── Helpers ────────────────────────────────────────────────────────


def _to_list_item(rec: LeadAnalysis, attachments_count: int) -> LeadAnalysisListItem:
    return LeadAnalysisListItem(
        id=rec.id,
        status=rec.status,
        position=rec.position,
        address=rec.address,
        city=rec.city,
        asking_price=float(rec.asking_price) if rec.asking_price is not None else None,
        nb_logements=rec.nb_logements,
        annee_construction=rec.annee_construction,
        best_refi_amount=(
            float(rec.best_refi_amount)
            if rec.best_refi_amount is not None
            else None
        ),
        type_batiment=rec.type_batiment,
        converted_to_lead_id=rec.converted_to_lead_id,
        created_at=rec.created_at,
        attachments_count=attachments_count,
    )


def _map_extracted_to_lead(data: dict) -> dict:
    """Convertit le JSON renvoyé par Claude en kwargs pour LeadAnalysis."""
    out: dict = {}
    # Fields scalaires directs.
    scalar_fields = (
        "address", "city", "postal_code", "province",
        "asking_price", "nb_logements", "revenus_bruts",
        "taxes_municipales", "taxes_scolaires", "assurances",
        "energie", "depenses_autres", "annee_construction",
        "superficie_terrain", "superficie_batiment",
        "evaluation_municipale", "description",
        "courtier_nom", "courtier_contact", "type_batiment",
        "nb_stationnements",
    )
    for f in scalar_fields:
        v = data.get(f)
        if v == "" or v == "null":
            v = None
        if v is not None:
            out[f] = v
    # Typology sub-dict → JSON serialized.
    typology = data.get("typology")
    if isinstance(typology, dict) and typology:
        out["typology_json"] = json.dumps(typology)
    return out


# ── Endpoints ──────────────────────────────────────────────────────


@router.post(
    "/extract",
    response_model=ExtractResult,
    status_code=status.HTTP_201_CREATED,
    summary="Extraire et créer une ou plusieurs fiches depuis sources.",
)
async def extract_and_create(
    db: DBSession,
    user: CurrentUser,
    urls: Optional[str] = Form(default=None),
    text: Optional[str] = Form(default=None),
    files: List[UploadFile] = File(default=[]),
) -> ExtractResult:
    """Reçoit un mix d'URLs (séparées par newline), de texte brut et
    de fichiers. Lance l'extraction Claude. Crée une `LeadAnalysis`
    par immeuble distinct détecté (en pratique presque toujours 1)
    + une `LeadAnalysisAttachment` par fichier."""
    _require_prospection(user)

    url_list = [u.strip() for u in (urls or "").splitlines() if u.strip()]

    # Lit les fichiers en bytes (limite 10 MB chacun).
    file_blobs: list[tuple[str, str, bytes]] = []
    for f in files or []:
        if not f or not f.filename:
            continue
        data = await f.read()
        if len(data) > _MAX_FILE_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"Fichier {f.filename} trop lourd (max 10 MB).",
            )
        file_blobs.append(
            (
                f.filename,
                (f.content_type or "application/octet-stream").lower(),
                data,
            )
        )

    if not url_list and not (text and text.strip()) and not file_blobs:
        raise HTTPException(
            status_code=400, detail="Aucune source fournie."
        )

    try:
        res = await extract_lead_info(
            urls=url_list, text=text, files=file_blobs
        )
    except Exception as exc:  # noqa: BLE001
        log.exception("Extraction Claude failed")
        raise HTTPException(
            status_code=502, detail=f"Échec de l'extraction IA : {exc!s}"
        ) from exc

    created_records: list[LeadAnalysis] = []
    # On stocke l'URL et le texte d'origine sur la 1re fiche créée
    # (la fusion intelligente côté Claude regroupe normalement).
    src_url_str = "\n".join(url_list) if url_list else None
    src_text = (text or "").strip() or None

    now = datetime.now(timezone.utc)
    for idx, item in enumerate(res.data or []):
        kwargs = _map_extracted_to_lead(item)
        rec = LeadAnalysis(
            status=LeadAnalysisStatus.A_ANALYSER.value,
            source_urls=src_url_str if idx == 0 else None,
            source_text=src_text if idx == 0 else None,
            extracted_json=json.dumps(item, ensure_ascii=False)[:50_000],
            created_by_user_id=getattr(user, "id", None),
            **kwargs,
        )
        rec.created_at = now
        rec.updated_at = now
        db.add(rec)
        await db.flush()

        # Attache les fichiers seulement sur la 1re fiche (sinon on
        # duplique du gros blob inutilement).
        if idx == 0:
            for filename, content_type, blob in file_blobs:
                att = LeadAnalysisAttachment(
                    lead_analysis_id=rec.id,
                    filename=filename[:255],
                    content_type=content_type[:64],
                    size_bytes=len(blob),
                    blob=blob,
                )
                db.add(att)

        created_records.append(rec)

    # Cas dégénéré : Claude n'a rien retourné mais il y avait des
    # sources. On crée quand même une fiche vide pour ne pas perdre
    # l'effort de l'utilisateur (il pourra remplir à la main).
    if not created_records and (url_list or src_text or file_blobs):
        rec = LeadAnalysis(
            status=LeadAnalysisStatus.A_ANALYSER.value,
            source_urls=src_url_str,
            source_text=src_text,
            extracted_json=None,
            created_by_user_id=getattr(user, "id", None),
            notes="Extraction IA n'a retourné aucun champ — à compléter manuellement.",
        )
        rec.created_at = now
        rec.updated_at = now
        db.add(rec)
        await db.flush()
        for filename, content_type, blob in file_blobs:
            att = LeadAnalysisAttachment(
                lead_analysis_id=rec.id,
                filename=filename[:255],
                content_type=content_type[:64],
                size_bytes=len(blob),
                blob=blob,
            )
            db.add(att)
        created_records.append(rec)

    await db.commit()
    for rec in created_records:
        await db.refresh(rec)

    out_items: List[LeadAnalysisListItem] = []
    for rec in created_records:
        cnt = (
            await db.execute(
                select(func.count(LeadAnalysisAttachment.id)).where(
                    LeadAnalysisAttachment.lead_analysis_id == rec.id
                )
            )
        ).scalar_one()
        out_items.append(_to_list_item(rec, int(cnt or 0)))

    return ExtractResult(
        created=out_items,
        warnings=res.warnings,
        model_used=res.model_used,
    )


@router.get(
    "",
    response_model=List[LeadAnalysisListItem],
    summary="Liste des analyses (kanban / tableau).",
)
async def list_analyses(
    db: DBSession,
    user: CurrentUser,
    status_filter: Optional[str] = None,
    q: Optional[str] = None,
    limit: int = 200,
) -> List[LeadAnalysisListItem]:
    _require_prospection(user)

    stmt = select(LeadAnalysis).order_by(
        LeadAnalysis.status.asc(),
        LeadAnalysis.position.asc(),
        LeadAnalysis.created_at.desc(),
    )
    if status_filter:
        stmt = stmt.where(LeadAnalysis.status == status_filter)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(
            (LeadAnalysis.address.ilike(like))
            | (LeadAnalysis.city.ilike(like))
            | (LeadAnalysis.description.ilike(like))
        )
    stmt = stmt.limit(min(max(limit, 1), 500))
    rows = (await db.execute(stmt)).scalars().all()

    # Compte les attachments en 1 query batch (LEFT JOIN count).
    counts_stmt = (
        select(
            LeadAnalysisAttachment.lead_analysis_id,
            func.count(LeadAnalysisAttachment.id),
        )
        .where(
            LeadAnalysisAttachment.lead_analysis_id.in_([r.id for r in rows])
            if rows
            else False
        )
        .group_by(LeadAnalysisAttachment.lead_analysis_id)
    )
    cnt_rows = (await db.execute(counts_stmt)).all() if rows else []
    counts = {lid: int(c) for lid, c in cnt_rows}

    return [_to_list_item(r, counts.get(r.id, 0)) for r in rows]


@router.get(
    "/{analysis_id}",
    response_model=LeadAnalysisRead,
    summary="Détail d'une analyse (fiche complète).",
)
async def get_analysis(
    analysis_id: int, db: DBSession, user: CurrentUser
) -> LeadAnalysisRead:
    _require_prospection(user)
    rec = await db.get(LeadAnalysis, analysis_id)
    if rec is None:
        raise HTTPException(404, "Analyse introuvable.")
    atts = (
        await db.execute(
            select(LeadAnalysisAttachment)
            .where(LeadAnalysisAttachment.lead_analysis_id == analysis_id)
            .order_by(LeadAnalysisAttachment.id.asc())
        )
    ).scalars().all()

    out = LeadAnalysisRead.model_validate(rec)
    out.attachments = [AttachmentRead.model_validate(a) for a in atts]
    return out


@router.patch(
    "/{analysis_id}",
    response_model=LeadAnalysisRead,
    summary="Mise à jour partielle (édition fiche).",
)
async def update_analysis(
    analysis_id: int,
    payload: LeadAnalysisUpdate,
    db: DBSession,
    user: CurrentUser,
) -> LeadAnalysisRead:
    _require_prospection(user)
    rec = await db.get(LeadAnalysis, analysis_id)
    if rec is None:
        raise HTTPException(404, "Analyse introuvable.")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(rec, k, v)
    rec.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(rec)
    return await get_analysis(analysis_id, db, user)


@router.delete(
    "/{analysis_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_analysis(
    analysis_id: int, db: DBSession, user: CurrentUser
) -> None:
    _require_prospection(user)
    rec = await db.get(LeadAnalysis, analysis_id)
    if rec is None:
        return None
    await db.delete(rec)
    await db.commit()


@router.post(
    "/{analysis_id}/convert-to-lead",
    response_model=ConvertResult,
    summary="Convertit l'analyse en ProspectionLead (pipeline officiel).",
)
async def convert_to_lead(
    analysis_id: int, db: DBSession, user: CurrentUser
) -> ConvertResult:
    """Crée un `ProspectionLead` à partir de la fiche d'analyse.
    Idempotent : si déjà converti, retourne l'id existant."""
    _require_prospection(user)
    rec = await db.get(LeadAnalysis, analysis_id)
    if rec is None:
        raise HTTPException(404, "Analyse introuvable.")
    if rec.converted_to_lead_id:
        return ConvertResult(lead_id=rec.converted_to_lead_id)

    lead = ProspectionLead(
        name=rec.address or f"Lead #{rec.id}",
        kind=ProspectionLeadKind.MULTILOGEMENT.value,
        status=ProspectionLeadStatus.A_CONTACTER.value,
        address=rec.address,
        city=rec.city,
        postal_code=rec.postal_code,
        notes=(
            f"Créé depuis l'analyse #{rec.id}\n"
            + (rec.description or "")
        )[:5000] or None,
        nb_logements=rec.nb_logements,
        annee_construction=rec.annee_construction,
        valeur_fonciere=(
            float(rec.evaluation_municipale)
            if rec.evaluation_municipale is not None
            else None
        ),
        owner_kind=ProspectionOwnerKind.INCONNU.value,
        created_by_user_id=getattr(user, "id", None),
    )
    db.add(lead)
    await db.flush()
    rec.converted_to_lead_id = lead.id
    rec.updated_at = datetime.now(timezone.utc)
    await db.commit()
    return ConvertResult(lead_id=lead.id)


@router.get(
    "/{analysis_id}/attachments/{attachment_id}",
    summary="Sert un fichier joint en inline.",
)
async def get_attachment(
    analysis_id: int,
    attachment_id: int,
    db: DBSession,
    user: CurrentUser,
):
    _require_prospection(user)
    att = await db.get(LeadAnalysisAttachment, attachment_id)
    if att is None or att.lead_analysis_id != analysis_id:
        raise HTTPException(404, "Fichier introuvable.")
    return Response(
        content=att.blob,
        media_type=att.content_type or "application/octet-stream",
        headers={
            "Content-Disposition": (
                f'inline; filename="{att.filename}"'
            )
        },
    )
