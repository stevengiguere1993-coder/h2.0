"""API pour les analyses de leads immobiliers.

Endpoints :
    POST   /lead-analyses/extract   multipart : urls + text + files
                                    → crée une (ou plusieurs) fiche(s)
    GET    /lead-analyses           liste paginée + filtres
    GET    /lead-analyses/{id}      détail
    PATCH  /lead-analyses/{id}      MAJ partielle (édition fiche)
    DELETE /lead-analyses/{id}      suppression (cascade attachments)
    POST   /lead-analyses/{id}/convert-to-lead  → ProspectionLead
    POST   /lead-analyses/{id}/convert-to-deal  → ProspectionDeal (Pipeline)
    GET    /lead-analyses/{id}/attachments/{att_id}  blob inline

Restreint au volet `prospection`.
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import List, Optional

from app.core.config import settings

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
from app.models.prospection_deal import ProspectionDeal
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
    tga_pct: Optional[float] = None
    taux_interet_achat_pct: Optional[float] = None
    duree_projet_annees: Optional[int] = None
    frais_developpement: Optional[float] = None
    frais_negociations: Optional[float] = None

    analysis_results_json: Optional[str] = None
    best_refi_amount: Optional[float] = None
    best_refi_program: Optional[str] = None
    mdf_preteur_b: Optional[float] = None
    mdf_preteur_b_pct: Optional[float] = None
    frais_demarrage_overrides_json: Optional[str] = None
    frais_demarrage_financables_json: Optional[str] = None
    notes: Optional[str] = None
    converted_to_lead_id: Optional[int] = None
    converted_to_deal_id: Optional[int] = None

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
    best_refi_program: Optional[str] = None
    mdf_preteur_b: Optional[float] = None
    type_batiment: Optional[str]
    converted_to_lead_id: Optional[int]
    converted_to_deal_id: Optional[int] = None
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
    tga_pct: Optional[float] = None
    taux_interet_achat_pct: Optional[float] = None
    duree_projet_annees: Optional[int] = None
    frais_developpement: Optional[float] = None
    frais_negociations: Optional[float] = None

    mdf_preteur_b_pct: Optional[float] = None
    frais_demarrage_overrides_json: Optional[str] = None
    frais_demarrage_financables_json: Optional[str] = None

    notes: Optional[str] = None


class ExtractResult(BaseModel):
    """Réponse de l'endpoint extract — peut créer plusieurs leads
    si Claude détecte plusieurs immeubles distincts."""

    created: List[LeadAnalysisListItem]
    warnings: List[str] = Field(default_factory=list)
    model_used: Optional[str] = None


class ConvertResult(BaseModel):
    lead_id: int


class ConvertDealResult(BaseModel):
    deal_id: int


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
        best_refi_program=rec.best_refi_program,
        mdf_preteur_b=(
            float(rec.mdf_preteur_b)
            if rec.mdf_preteur_b is not None
            else None
        ),
        type_batiment=rec.type_batiment,
        converted_to_lead_id=rec.converted_to_lead_id,
        converted_to_deal_id=rec.converted_to_deal_id,
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


# Défauts appliqués à la création d'une fiche `LeadAnalysis`
# pour pré-remplir les champs manuels d'analyse financière.
# Modifiables ensuite par l'utilisateur dans la fiche.
def _parse_financables(raw: Optional[str]) -> list[str]:
    """Décode la liste JSON des clés finançables. Si invalide ou
    None, retourne les défauts (rapport efficacité, dev, travaux)."""
    DEFAULT = ["rapport_efficacite", "frais_developpement", "frais_travaux"]
    if not raw:
        return DEFAULT
    try:
        v = json.loads(raw)
        if isinstance(v, list):
            return [str(x) for x in v if isinstance(x, str)]
    except Exception:  # noqa: BLE001
        pass
    return DEFAULT


DEFAULTS_NEW_ANALYSIS: dict = {
    "nb_logements_ajoutes": 0,
    "nb_thermopompes_ajoutees": 0,
    "reduction_energie_pct": 0,
    "taux_interet_refi_pct": 3.75,
    "duree_projet_annees": 2,
    "tga_pct": 4.0,
    "taux_interet_achat_pct": 4.0,
    "ajout_wifi": True,
    "loyers_max_abordabilite_json": json.dumps({"abordable": 1090}),
    "mdf_preteur_b_pct": 25.0,
    # Frais finançables par défaut (modifiable par l'utilisateur) :
    # rapport d'efficacité énergétique, frais de développement,
    # travaux estimés. Les autres postes (courtier, notaire, etc.)
    # sont payés 100 % cash sauf si on les coche.
    "frais_demarrage_financables_json": json.dumps([
        "rapport_efficacite",
        "frais_developpement",
        "frais_travaux",
    ]),
}


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
        # Applique les défauts pour les champs manuels d'analyse
        # avant les valeurs extraites (les extraites ne touchent
        # jamais ces champs de toute façon).
        kwargs = {**DEFAULTS_NEW_ANALYSIS, **kwargs}
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
            **DEFAULTS_NEW_ANALYSIS,
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


@router.post(
    "/{analysis_id}/convert-to-deal",
    response_model=ConvertDealResult,
    summary="Convertit l'analyse en ProspectionDeal (Pipeline).",
)
async def convert_to_deal(
    analysis_id: int, db: DBSession, user: CurrentUser
) -> ConvertDealResult:
    """Crée un `ProspectionDeal` à partir de la fiche d'analyse.
    Idempotent : si déjà converti, retourne l'id existant.

    Le deal créé est lié à la fiche d'analyse via `lead_analysis_id`
    pour que la page detail du deal puisse afficher la fiche
    complète."""
    _require_prospection(user)
    rec = await db.get(LeadAnalysis, analysis_id)
    if rec is None:
        raise HTTPException(404, "Analyse introuvable.")
    if rec.converted_to_deal_id:
        return ConvertDealResult(deal_id=rec.converted_to_deal_id)

    deal = ProspectionDeal(
        address=rec.address or f"Deal #{rec.id}",
        priority="moyenne",
        lead_analysis_id=rec.id,
    )
    db.add(deal)
    await db.flush()
    rec.converted_to_deal_id = deal.id
    rec.updated_at = datetime.now(timezone.utc)
    await db.commit()
    return ConvertDealResult(deal_id=deal.id)


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


# ── Analyse financière (Phase 3b) ──────────────────────────────────


class RunAnalysisResult(BaseModel):
    """Réponse de l'endpoint run-financial-analysis."""
    best_refi_amount: float
    best_refi_program: str
    analysis_results: dict


@router.post(
    "/{analysis_id}/run-financial-analysis",
    response_model=RunAnalysisResult,
    summary="Lance le moteur de calcul financier (réplique Excel).",
)
async def run_financial_analysis(
    analysis_id: int, db: DBSession, user: CurrentUser
) -> RunAnalysisResult:
    """Lit les champs du `LeadAnalysis`, lance le moteur de calcul
    (réplique exacte des 2 calculateurs Excel), persiste le résultat
    en JSON, met à jour `best_refi_amount` + `best_refi_program`,
    et bascule le statut en `decision_en_attente`."""
    _require_prospection(user)
    rec = await db.get(LeadAnalysis, analysis_id)
    if rec is None:
        raise HTTPException(404, "Analyse introuvable.")

    from app.services.lead_analysis_finance import FinanceInputs, compute_all

    # Désérialise les loyers projetés (typologie_prix) depuis le JSON
    # stocké dans `loyers_projetes_json` : { "3.5": 1400, "4.5": 1600 }
    loyers_projetes: dict = {}
    if rec.loyers_projetes_json:
        try:
            loyers_projetes = json.loads(rec.loyers_projetes_json) or {}
        except Exception:  # noqa: BLE001
            loyers_projetes = {}

    typologie: dict = {}
    if rec.typology_json:
        try:
            raw = json.loads(rec.typology_json)
            if isinstance(raw, dict):
                typologie = {str(k): int(v or 0) for k, v in raw.items()}
        except Exception:  # noqa: BLE001
            typologie = {}

    # Loyer abordable (APH SELECT) — stocké comme premier item du JSON
    # `loyers_max_abordabilite_json` (clé arbitraire « abordable »).
    loyer_abord = 0.0
    if rec.loyers_max_abordabilite_json:
        try:
            d = json.loads(rec.loyers_max_abordabilite_json) or {}
            loyer_abord = float(d.get("abordable", 0) or 0)
        except Exception:  # noqa: BLE001
            loyer_abord = 0.0

    # Overrides manuels des frais de démarrage (saisis par l'utilisateur
    # depuis l'UI). Dict { "evaluateur": 1800, ... }.
    frais_overrides: dict = {}
    if rec.frais_demarrage_overrides_json:
        try:
            j = json.loads(rec.frais_demarrage_overrides_json) or {}
            if isinstance(j, dict):
                frais_overrides = {
                    k: float(v)
                    for k, v in j.items()
                    if v is not None and isinstance(v, (int, float, str))
                    and str(v).replace(".", "", 1).replace("-", "", 1).isdigit()
                }
        except Exception:  # noqa: BLE001
            frais_overrides = {}

    inputs = FinanceInputs(
        adresse=rec.address or "",
        prix_achat=float(rec.asking_price or 0),
        nombre_logements=int(rec.nb_logements or 0),
        revenus_annuels=float(rec.revenus_bruts or 0),
        taxes_municipales=float(rec.taxes_municipales or 0),
        taxes_scolaires=float(rec.taxes_scolaires or 0),
        assurances=float(rec.assurances or 0),
        energie=float(rec.energie or 0),
        depenses_autres=float(rec.depenses_autres or 0),
        tga=float(rec.tga_pct or 4.0) / 100.0,
        taux_interet_achat=float(rec.taux_interet_achat_pct or 4.0) / 100.0,
        nb_logements_ajoutes=int(rec.nb_logements_ajoutes or 0),
        nb_thermopompes_ajoutees=int(rec.nb_thermopompes_ajoutees or 0),
        wifi_ajoute=bool(rec.ajout_wifi) if rec.ajout_wifi is not None else True,
        reduction_energie_pct=float(rec.reduction_energie_pct or 0) / 100.0,
        taux_interet_refi=float(rec.taux_interet_refi_pct or 0) / 100.0,
        typologie=typologie,
        typologie_prix=loyers_projetes,
        duree_projet_annees=int(rec.duree_projet_annees or 2),
        frais_developpement=float(rec.frais_developpement or 0),
        frais_negociations=float(rec.frais_negociations or 0),
        frais_travaux=float(rec.travaux_estimes or 0),
        nouveau_loyer_abordable=loyer_abord,
        mdf_preteur_b_pct=(
            float(rec.mdf_preteur_b_pct) / 100.0
            if rec.mdf_preteur_b_pct is not None
            else 0.25
        ),
        frais_demarrage_overrides=frais_overrides,
        frais_demarrage_financables=_parse_financables(
            rec.frais_demarrage_financables_json
        ),
    )

    use_aph = loyer_abord > 0 and inputs.nombre_logements > 0
    results = compute_all(inputs, use_aph_select=use_aph)
    results_dict = results.to_dict()

    rec.analysis_results_json = json.dumps(results_dict)[:50_000]
    rec.best_refi_amount = results.best_refi_amount
    rec.best_refi_program = results.best_refi_program
    rec.mdf_preteur_b = results.mdf_preteur_b
    # Auto-bascule en « Décision en attente » comme spécifié.
    if rec.status == LeadAnalysisStatus.A_ANALYSER.value:
        rec.status = LeadAnalysisStatus.DECISION_EN_ATTENTE.value
    rec.updated_at = datetime.now(timezone.utc)
    await db.commit()

    return RunAnalysisResult(
        best_refi_amount=results.best_refi_amount,
        best_refi_program=results.best_refi_program,
        analysis_results=results_dict,
    )


# ─── Estimation IA des dépenses manquantes ─────────────────────────


class EstimateExpensesResponse(BaseModel):
    """Estimations heuristiques (avec IA si disponible) des dépenses
    d'opération d'un immeuble pour pré-remplir les champs manquants."""

    taxes_municipales: Optional[float] = None
    taxes_scolaires: Optional[float] = None
    assurances: Optional[float] = None
    source: str  # "ai" | "heuristic"
    note: Optional[str] = None


def _heuristic_estimate_expenses(
    *,
    asking_price: Optional[float],
    nb_logements: Optional[int],
    revenus_bruts: Optional[float],
    city: Optional[str],
) -> EstimateExpensesResponse:
    """Estimation pure-code basée sur des ratios marché Québec usuels.
    Sert de fallback si Claude est indisponible.

    Ratios appliqués (immeubles à logements Québec, 2024-2025) :
      - Taxes municipales ≈ 0.75 % du prix d'achat (Montréal+couronne)
      - Taxes scolaires    ≈ 0.10 % du prix d'achat (Centre de services)
      - Assurances         ≈ 250 $/logement/an, plancher 1 200 $/an
    """
    price = float(asking_price or 0)
    nb = int(nb_logements or 0)
    tm = round(price * 0.0075, 2) if price > 0 else None
    ts = round(price * 0.0010, 2) if price > 0 else None
    if nb > 0:
        ass = round(max(1_200.0, nb * 250.0), 2)
    elif price > 0:
        ass = round(max(1_200.0, price * 0.0015), 2)
    else:
        ass = None
    return EstimateExpensesResponse(
        taxes_municipales=tm,
        taxes_scolaires=ts,
        assurances=ass,
        source="heuristic",
        note=(
            "Estimations ratios marché Québec : taxes muni 0.75 % du prix, "
            "taxes scolaires 0.10 %, assurances 250 $/logement (plancher "
            "1 200 $/an). À valider avec le rôle d'évaluation."
        ),
    )


async def _ai_estimate_expenses(
    rec: LeadAnalysis,
) -> Optional[EstimateExpensesResponse]:
    """Demande à Gemini une estimation des dépenses manquantes en
    fonction de l'adresse, du prix, du nombre de logements et de
    l'évaluation municipale. Retourne None si Gemini indisponible
    (le caller fera le fallback heuristique).

    Migration Claude → Gemini : tier gratuit Google AI Studio
    (1500 req/jour) — couvre largement les besoins d'estimation."""
    if not settings.gemini_api_key:
        return None
    import google.generativeai as genai

    prompt = (
        "Tu es un expert en immobilier locatif Québec. Estime les "
        "dépenses d'opération annuelles MANQUANTES pour cet immeuble "
        "(en CAD/an). Retourne UNIQUEMENT un JSON strict avec les "
        "clés taxes_municipales (float|null), taxes_scolaires "
        "(float|null), assurances (float|null), note (string).\n\n"
        "Règles : utilise les barèmes municipaux de la ville fournie "
        "(Montréal ≈ 0.7-0.85 % du prix, banlieue ≈ 0.6-0.75 %, "
        "Québec-ville 1 %), taxes scolaires ≈ 0.10-0.13 % du prix, "
        "assurances ≈ 200-300 $/logement avec plancher 1 200 $. Si une "
        "info est déjà fournie, ne la remplace pas (retourne null pour "
        "elle).\n\n"
        f"Adresse : {rec.address or 'inconnue'}, "
        f"{rec.city or 'ville inconnue'}\n"
        f"Prix demandé : {rec.asking_price or 'inconnu'} $\n"
        f"Nombre de logements : {rec.nb_logements or 'inconnu'}\n"
        f"Revenus bruts annuels : {rec.revenus_bruts or 'inconnu'} $\n"
        f"Évaluation municipale : {rec.evaluation_municipale or 'inconnue'} $\n"
        f"Année construction : {rec.annee_construction or 'inconnue'}\n"
        "Déjà saisis (ne pas remplacer) : "
        f"taxes_muni={rec.taxes_municipales}, "
        f"taxes_scolaires={rec.taxes_scolaires}, "
        f"assurances={rec.assurances}"
    )

    estimate_model = os.environ.get(
        "LEAD_EXTRACTION_MODEL", "gemini-2.0-flash"
    )

    try:
        genai.configure(api_key=settings.gemini_api_key)
        model = genai.GenerativeModel(
            estimate_model,
            generation_config=genai.GenerationConfig(
                response_mime_type="application/json",
                max_output_tokens=500,
            ),
        )
        response = await model.generate_content_async(prompt)
    except Exception as exc:  # noqa: BLE001
        log.warning("AI estimate expenses failed: %s", exc)
        return None

    raw = (response.text or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```\s*$", "", raw)
    try:
        parsed = json.loads(raw)
    except Exception:  # noqa: BLE001
        return None

    def _num(v):
        try:
            return float(v) if v is not None else None
        except (ValueError, TypeError):
            return None

    return EstimateExpensesResponse(
        taxes_municipales=_num(parsed.get("taxes_municipales")),
        taxes_scolaires=_num(parsed.get("taxes_scolaires")),
        assurances=_num(parsed.get("assurances")),
        source="ai",
        note=str(parsed.get("note") or "")[:500],
    )


@router.post(
    "/{lead_id}/estimate-expenses",
    response_model=EstimateExpensesResponse,
    summary="Estime taxes muni/scol/assurances manquantes (IA + fallback)",
)
async def estimate_expenses(
    lead_id: int,
    db: DBSession,
    user: CurrentUser,
) -> EstimateExpensesResponse:
    _require_prospection(user)
    rec = (
        await db.execute(
            select(LeadAnalysis).where(LeadAnalysis.id == lead_id)
        )
    ).scalar_one_or_none()
    if rec is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Lead introuvable.")

    ai = await _ai_estimate_expenses(rec)
    if ai is not None:
        return ai
    return _heuristic_estimate_expenses(
        asking_price=float(rec.asking_price) if rec.asking_price else None,
        nb_logements=rec.nb_logements,
        revenus_bruts=float(rec.revenus_bruts) if rec.revenus_bruts else None,
        city=rec.city,
    )


# ─── Endpoint diagnostic d'extraction URL ────────────────────────


class DebugExtractRequest(BaseModel):
    url: str = Field(..., max_length=2000)


@router.post(
    "/debug-extract-url",
    summary=(
        "Diagnostic : montre ce que l'extracteur envoie à Gemini pour "
        "une URL, et la réponse JSON brute"
    ),
)
async def debug_extract_url(
    data: DebugExtractRequest,
    user: CurrentUser,
):
    """Renvoie le texte stripé envoyé à Gemini + la réponse brute,
    pour comprendre pourquoi une URL ne s'extrait pas."""
    _require_prospection(user)
    from app.services.lead_extraction import (
        _fetch_url_text,
        SYSTEM_PROMPT,
        SCHEMA_GUIDE,
        EXTRACTION_MODEL,
    )

    fetched = await _fetch_url_text(data.url)
    # Coupé pour ne pas exploser la réponse JSON.
    preview = fetched[:8000]

    if not settings.gemini_api_key:
        return {
            "preview_text_first_8k": preview,
            "fetched_total_len": len(fetched),
            "model_used": None,
            "raw_response": "(IA non configurée)",
        }

    import google.generativeai as genai

    try:
        genai.configure(api_key=settings.gemini_api_key)
        model = genai.GenerativeModel(
            EXTRACTION_MODEL,
            system_instruction=SYSTEM_PROMPT,
            generation_config=genai.GenerationConfig(
                response_mime_type="application/json",
                max_output_tokens=4000,
            ),
        )
        response = await model.generate_content_async(
            [
                fetched,
                (
                    "Extrais maintenant les infos selon le schéma "
                    "ci-dessous.\n\n" + SCHEMA_GUIDE
                ),
            ]
        )
        raw = (response.text or "").strip()
    except Exception as exc:  # noqa: BLE001
        return {
            "preview_text_first_8k": preview,
            "fetched_total_len": len(fetched),
            "model_used": EXTRACTION_MODEL,
            "raw_response": f"ERREUR : {type(exc).__name__}: {exc}",
        }

    return {
        "preview_text_first_8k": preview,
        "fetched_total_len": len(fetched),
        "model_used": EXTRACTION_MODEL,
        "raw_response": raw,
    }
