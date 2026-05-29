"""Endpoints pour le bouton « Aide ».

- POST /api/v1/help/ask : poser une question, réponse via la cascade
  IA gratuite (Groq préféré, repli Gemini puis Anthropic)
- POST /api/v1/help/reports : signaler un bug (toute personne logée)
- GET  /api/v1/help/reports : liste des bugs (owner only)
- PATCH /api/v1/help/reports/{id} : accepter/rejeter/résoudre (owner)
- POST /api/v1/help/reports/bulk : actions en lot (owner)
- GET  /api/v1/help/reports/accepted : bugs acceptés en attente de
  correction. Endpoint pratique pour Claude Code : « lis les bugs
  acceptés », l'agent fetch et marque resolved après livraison.
"""

import logging
import re
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, update

from app.api.deps import CurrentUser, DBSession, RequireOwner
from app.integrations.ai import Message, chat
from app.integrations.ai._base import AIProviderError, AIProviderUnavailable
from app.models.help_request import HelpRequest, HelpRequestKind, HelpRequestStatus
from app.models.voice import Call


# Mots à 4+ lettres considérés non-pertinents pour la recherche
# d'appels — évite de matcher l'univers entier sur des questions
# pleines de connecteurs ou de verbes très courants.
_STOPWORDS_FR = {
    "avec", "sans", "pour", "dans", "vous", "nous", "leur", "leurs",
    "elle", "elles", "cette", "cela", "celui", "celle", "ceux", "celles",
    "alors", "donc", "mais", "comme", "quand", "quoi", "quel", "quels",
    "quelle", "quelles", "tout", "tous", "toute", "toutes", "plus",
    "moins", "encore", "déjà", "deja", "très", "tres", "bien", "peut",
    "peux", "veut", "veux", "faire", "fait", "faites", "savoir", "sais",
    "voir", "voici", "voilà", "voila", "été", "ete", "était", "etait",
    "sont", "suis", "est-ce", "est",
}


async def _find_calls_for_question(
    db, question: str, limit: int = 5
) -> List[Call]:
    """Recherche les appels potentiellement liés à la question posée
    à l'aide. Extrait les mots significatifs (4+ lettres, hors
    stopwords), puis LIKE sur lead_name / lead_reason /
    verbatim_transcript / voicemail_transcription. Trié desc."""
    words = re.findall(r"\b\w{4,}\b", question.lower())
    keywords = [
        w for w in words if w not in _STOPWORDS_FR
    ][:8]
    if not keywords:
        return []
    clauses = []
    for w in keywords:
        like = f"%{w}%"
        clauses.append(Call.lead_name.ilike(like))
        clauses.append(Call.lead_reason.ilike(like))
        clauses.append(Call.verbatim_transcript.ilike(like))
        clauses.append(Call.voicemail_transcription.ilike(like))
    cond = clauses[0]
    for c in clauses[1:]:
        cond = cond | c
    rows = (
        await db.execute(
            select(Call)
            .where(cond)
            .order_by(Call.started_at.desc())
            .limit(limit)
        )
    ).scalars().all()
    return list(rows)


def _format_call_for_context(call: Call) -> str:
    """Représentation textuelle compacte d'un appel pour l'inclure
    dans le contexte LLM. On limite la longueur du verbatim pour ne
    pas exploser le prompt."""
    parts = [
        f"Appel #{call.id} · "
        f"{call.started_at.strftime('%Y-%m-%d %H:%M')} · "
        f"{call.from_e164} → {call.to_e164}"
    ]
    if call.lead_name:
        parts.append(f"Contact : {call.lead_name}")
    if call.intent:
        parts.append(f"Intent : {call.intent}")
    if call.lead_reason:
        parts.append(f"Raison : {call.lead_reason}")
    verb = (call.verbatim_transcript or "").strip()
    if verb:
        if len(verb) > 600:
            verb = verb[:600] + "…"
        parts.append(f"Verbatim : {verb}")
    vm = (call.voicemail_transcription or "").strip()
    if vm:
        if len(vm) > 400:
            vm = vm[:400] + "…"
        parts.append(f"Boîte vocale : {vm}")
    return "\n".join(parts)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/help", tags=["help"])


# ------------------------------ Schemas ------------------------------


class AskIn(BaseModel):
    question: str = Field(min_length=2, max_length=4000)
    context_url: Optional[str] = Field(default=None, max_length=500)


class AskOut(BaseModel):
    id: int
    answer: str


class ReportIn(BaseModel):
    message: str = Field(min_length=2, max_length=4000)
    context_url: Optional[str] = Field(default=None, max_length=500)
    user_agent: Optional[str] = Field(default=None, max_length=500)


class ReportOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    user_email: Optional[str]
    kind: str
    status: str
    message: str
    ai_response: Optional[str]
    context_url: Optional[str]
    user_agent: Optional[str]
    created_at: datetime
    accepted_at: Optional[datetime]
    resolved_at: Optional[datetime]
    has_screenshot: bool = False
    resolution_notes: Optional[str] = None


class ReportPatch(BaseModel):
    status: Optional[str] = None  # accepted | rejected | resolved
    resolution_notes: Optional[str] = None


class BulkAction(BaseModel):
    ids: List[int]
    action: str  # accept | reject | resolve


# ------------------------------ Question (cascade IA gratuite) ------------------------------

SYSTEM_PROMPT = """Tu es l'assistant du Centre d'aide de Kratos, le portail \
interne de Horizon Services Immobiliers (Montréal, Québec — construction et \
rénovation, RBQ 5868-5991-01). Le propriétaire est Steven ; les employés qui \
te consultent sont notamment Jérôme et Gabriel.

RÔLE
- Tu aides les employés et le bureau à utiliser le portail. Réponds en \
français québécois, ton concis et pragmatique, et oriente toujours vers la \
bonne page.
- Si l'utilisateur décrit une vraie anomalie (bug, erreur, page cassée), \
suggère le bouton « Signaler un bug » du Centre d'aide pour faire monter le \
sujet à Steven.
- N'invente jamais une page ou une fonctionnalité qui n'existe pas. Si tu ne \
sais pas, dis-le clairement et propose de signaler un bug.
- Tes réponses sont indicatives ; termine en le rappelant (« Réponse \
indicative »).

LE PORTAIL KRATOS (découpé en volets)

Punch / Temps
- /app/punch : démarrer ou terminer un punch. On choisit un projet OU un \
prospect, puis une tâche ; la géolocalisation est capturée au punch. Versions \
mobiles sous /m/*.
- Les heures travaillées s'affichent en heures/minutes (ex. « 7 h 53 »).
- /app/punch/gestion (admin) : vue par semaine, mois ou période de paie ; \
approbation des punchs ; saisie manuelle d'un temps.
- /app/paie : rapport de paie, où les heures sont en décimal (pour la paie).

Construction
- Pipeline des contacts : new → contacted → rdv_prevu → qualified → quoted → \
won / lost / spam.
- Projets et planification par phases : on assigne des employés ou des \
sous-traitants à une phase.
- Sous-traitant payé à l'heure : cocher « payé à l'heure » + indiquer le \
nombre de travailleurs ; son coût entre alors dans le « Coût projeté – main \
d'œuvre ». Les sous-traitants au forfait sont exclus de ce calcul.
- Bons de commande (PO) : /app/po. Plus : soumissions (devis), \
achats/dépenses, facturation. Un PO est une autorisation d'achat \
(planification, sans impact comptable) ; quand la facture fournisseur arrive, \
on convertit le PO en Achat (qui pousse dans QuickBooks comme Bill ou Purchase \
selon le mode de paiement).
- Paramètres : numérotation QB, comptes QB, employés, sous-traitants.

Autres volets (mentionne-les seulement si pertinents) : prospection, \
immobilier, gestion locative, courtage, développement logiciel (devlog).

CONTEXTE FOURNI
On peut te transmettre quelques appels récents qui mentionnent les mots-clés \
de la question (volet téléphonie). Utilise-les seulement s'ils sont \
pertinents, et cite l'Appel #ID si tu t'appuies sur leur contenu."""


@router.post(
    "/ask",
    response_model=AskOut,
    summary="Poser une question à l'assistant du Centre d'aide",
)
async def ask(
    body: AskIn,
    db: DBSession,
    user: CurrentUser,
) -> AskOut:
    # L'assistant passe par la cascade IA gratuite (Groq préféré, repli
    # automatique Gemini puis Anthropic). Aucune clé Anthropic n'est
    # requise : il suffit qu'un fournisseur soit configuré.

    # Pré-recherche les appels qui mentionnent les mots-clés de la
    # question — permet de répondre à « est-ce qu'on a parlé de X avec
    # Y ? » en se basant sur les verbatim et transcriptions réels
    # stockés dans le volet téléphonie.
    try:
        call_matches = await _find_calls_for_question(db, body.question)
    except Exception as exc:  # noqa: BLE001
        log.warning("help: call search failed: %s", exc)
        call_matches = []

    if call_matches:
        calls_ctx = "\n\n---\n".join(
            _format_call_for_context(c) for c in call_matches
        )
        user_content = (
            "Voici quelques appels récents qui mentionnent les mots-clés "
            "de la question. Utilise-les si pertinents pour répondre, "
            "ignore-les sinon. Cite les Appel #ID si tu t'appuies sur "
            "leur contenu.\n\n"
            f"{calls_ctx}\n\n---\n\n"
            f"Question de l'utilisateur : {body.question}"
        )
    else:
        user_content = body.question

    # Cascade IA gratuite : Groq en priorité (gratuit/rapide), repli
    # automatique Gemini puis Anthropic via app.integrations.ai.chat().
    try:
        res = await chat(
            messages=[Message(role="user", content=user_content)],
            system=SYSTEM_PROMPT,
            prefer="groq",
            max_tokens=1024,
            temperature=0.3,
        )
        answer = (res.text or "").strip() or "(réponse vide)"
    except AIProviderUnavailable as e:
        # Aucun fournisseur (Groq / Gemini / Anthropic) n'est configuré.
        log.warning("help_ask: aucun provider IA configuré: %s", e)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "L'assistant n'est pas configuré : aucune clé d'IA "
                "(GROQ_API_KEY, GEMINI_API_KEY ou ANTHROPIC_API_KEY) "
                "n'est définie. Tu peux quand même signaler un bug."
            ),
        )
    except AIProviderError as e:
        # Erreur d'un provider (HTTP, quota, parsing). Détail tronqué
        # pour informer l'utilisateur, trace complète côté serveur.
        log.exception("help_ask_provider_error: %s", e)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Assistant IA : {str(e)[:200]}",
        )
    except Exception as e:  # pragma: no cover
        log.exception("help_ask_failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur assistant : {str(e)[:200]}",
        )

    rec = HelpRequest(
        user_id=user.id,
        user_email=user.email,
        kind=HelpRequestKind.QUESTION.value,
        status=HelpRequestStatus.ANSWERED.value,
        message=body.question,
        ai_response=answer,
        context_url=body.context_url,
    )
    db.add(rec)
    await db.commit()
    await db.refresh(rec)
    return AskOut(id=rec.id, answer=answer)


# ------------------------------ Bug reports ------------------------------


def _serialize_report(rec: HelpRequest) -> ReportOut:
    """ReportOut + flag `has_screenshot` calculé à la volée (le
    blob lui-même n'est jamais inclus — accessible via l'endpoint
    dédié `/reports/{id}/screenshot`)."""
    return ReportOut(
        id=rec.id,
        user_email=rec.user_email,
        kind=rec.kind,
        status=rec.status,
        message=rec.message,
        ai_response=rec.ai_response,
        context_url=rec.context_url,
        user_agent=rec.user_agent,
        created_at=rec.created_at,
        accepted_at=rec.accepted_at,
        resolved_at=rec.resolved_at,
        has_screenshot=rec.screenshot_blob is not None,
        resolution_notes=getattr(rec, "resolution_notes", None),
    )


_ALLOWED_SCREENSHOT_TYPES = {
    "image/jpeg",
    "image/jpg",
    "image/png",
    "image/webp",
    "image/heic",
    "image/heif",
    "image/gif",
}
_MAX_SCREENSHOT_BYTES = 4 * 1024 * 1024  # 4 MB


@router.post(
    "/reports",
    response_model=ReportOut,
    status_code=status.HTTP_201_CREATED,
    summary="Signaler un bug ou une demande (avec capture optionnelle)",
)
async def create_report(
    db: DBSession,
    user: CurrentUser,
    message: str = Form(..., min_length=2, max_length=4000),
    context_url: Optional[str] = Form(default=None, max_length=500),
    user_agent: Optional[str] = Form(default=None, max_length=500),
    screenshot: Optional[UploadFile] = File(default=None),
) -> ReportOut:
    """Endpoint multipart pour permettre l'attachement d'une
    capture d'écran. Les anciens clients qui envoyaient du JSON
    sont aussi compatibles : FastAPI accepte les formes mixtes
    quand les Form/File sont optionnels (tant que `Content-Type`
    est multipart/form-data côté client)."""
    blob: Optional[bytes] = None
    content_type: Optional[str] = None
    if screenshot is not None and screenshot.filename:
        ct = (screenshot.content_type or "").lower()
        if ct not in _ALLOWED_SCREENSHOT_TYPES:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Format d'image non supporté ({ct or 'inconnu'}). "
                    "Formats acceptés : JPEG, PNG, WebP, HEIC, GIF."
                ),
            )
        data = await screenshot.read()
        if len(data) > _MAX_SCREENSHOT_BYTES:
            raise HTTPException(
                status_code=413,
                detail="Image trop lourde (max 4 MB).",
            )
        blob = data
        content_type = ct
    rec = HelpRequest(
        user_id=user.id,
        user_email=user.email,
        kind=HelpRequestKind.BUG.value,
        status=HelpRequestStatus.PENDING.value,
        message=message,
        context_url=context_url,
        user_agent=user_agent,
        screenshot_blob=blob,
        screenshot_content_type=content_type,
    )
    db.add(rec)
    await db.commit()
    await db.refresh(rec)
    return _serialize_report(rec)


@router.get(
    "/reports/{report_id}/screenshot",
    summary="Télécharger la capture d'écran d'un signalement",
)
async def get_report_screenshot(
    report_id: int, db: DBSession, _: RequireOwner
):
    rec = await db.get(HelpRequest, report_id)
    if rec is None or not rec.screenshot_blob:
        raise HTTPException(
            status_code=404, detail="Capture introuvable."
        )
    from fastapi.responses import Response

    return Response(
        content=rec.screenshot_blob,
        media_type=rec.screenshot_content_type or "image/png",
    )


@router.get(
    "/reports",
    response_model=List[ReportOut],
    summary="Lister les bugs (owner seulement)",
)
async def list_reports(
    db: DBSession,
    _: RequireOwner,
    status_filter: Optional[str] = None,
) -> List[ReportOut]:
    stmt = (
        select(HelpRequest)
        .where(HelpRequest.kind == HelpRequestKind.BUG.value)
        .order_by(HelpRequest.created_at.desc())
        .limit(500)
    )
    if status_filter:
        stmt = stmt.where(HelpRequest.status == status_filter)
    rows = (await db.execute(stmt)).scalars().all()
    return [_serialize_report(r) for r in rows]


@router.patch(
    "/reports/{report_id}",
    response_model=ReportOut,
    summary="Changer le statut d'un bug (owner)",
)
async def patch_report(
    report_id: int,
    body: ReportPatch,
    db: DBSession,
    _: RequireOwner,
) -> ReportOut:
    rec = (
        await db.execute(
            select(HelpRequest).where(HelpRequest.id == report_id)
        )
    ).scalar_one_or_none()
    if rec is None or rec.kind != HelpRequestKind.BUG.value:
        raise HTTPException(status_code=404, detail="Bug introuvable")

    now = datetime.now(timezone.utc)

    if body.status is not None:
        new_status = body.status.lower().strip()
        if new_status not in (
            HelpRequestStatus.ACCEPTED.value,
            HelpRequestStatus.REJECTED.value,
            HelpRequestStatus.RESOLVED.value,
            HelpRequestStatus.PENDING.value,
        ):
            raise HTTPException(status_code=400, detail="Statut invalide")

        rec.status = new_status
        if new_status == HelpRequestStatus.ACCEPTED.value and rec.accepted_at is None:
            rec.accepted_at = now
        if new_status == HelpRequestStatus.RESOLVED.value:
            rec.resolved_at = now

    if body.resolution_notes is not None:
        # Vide → null (effacement)
        rec.resolution_notes = body.resolution_notes.strip() or None

    await db.commit()
    await db.refresh(rec)
    return _serialize_report(rec)


@router.post(
    "/reports/bulk",
    summary="Actions en lot sur plusieurs bugs (owner)",
)
async def bulk_reports(
    body: BulkAction,
    db: DBSession,
    _: RequireOwner,
) -> dict:
    if not body.ids:
        return {"updated": 0}
    action = body.action.lower().strip()
    mapping = {
        "accept": HelpRequestStatus.ACCEPTED.value,
        "reject": HelpRequestStatus.REJECTED.value,
        "resolve": HelpRequestStatus.RESOLVED.value,
    }
    if action not in mapping:
        raise HTTPException(status_code=400, detail="Action invalide")

    new_status = mapping[action]
    now = datetime.now(timezone.utc)
    values: dict = {"status": new_status}
    if action == "accept":
        values["accepted_at"] = now
    elif action == "resolve":
        values["resolved_at"] = now

    res = await db.execute(
        update(HelpRequest)
        .where(HelpRequest.id.in_(body.ids))
        .where(HelpRequest.kind == HelpRequestKind.BUG.value)
        .values(**values)
    )
    await db.commit()
    return {"updated": res.rowcount or 0}


@router.get(
    "/reports/accepted",
    response_model=List[ReportOut],
    summary="Bugs acceptés à régler — pratique pour Claude Code",
)
async def accepted_reports(
    db: DBSession,
    _: RequireOwner,
) -> List[ReportOut]:
    """Liste les bugs en statut `accepted` (acceptés mais non résolus).

    Idée : quand Steven revient parler à Claude Code, il dit « regarde
    les bugs acceptés ». L'agent appelle cet endpoint, traite chaque
    item, puis appelle PATCH .../reports/{id} avec status=resolved
    pour marquer chaque bug livré.
    """
    rows = (
        await db.execute(
            select(HelpRequest)
            .where(HelpRequest.kind == HelpRequestKind.BUG.value)
            .where(HelpRequest.status == HelpRequestStatus.ACCEPTED.value)
            .order_by(HelpRequest.accepted_at.asc().nulls_last())
        )
    ).scalars().all()
    return [_serialize_report(r) for r in rows]
