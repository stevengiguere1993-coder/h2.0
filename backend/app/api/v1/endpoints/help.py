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

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, update

from app.api.deps import CurrentUser, DBSession, RequireOwner
from app.integrations.ai import Message, chat
from app.integrations.ai._base import AIProviderError, AIProviderUnavailable
from app.models.help_request import HelpRequest, HelpRequestKind, HelpRequestStatus
from app.models.voice import Call
from app.services import aide_connaissances as kb


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


class SignalementLieOut(BaseModel):
    id: int
    status: str
    statut_libelle: str
    section: Optional[str] = None
    message: str
    resolution_notes: Optional[str] = None
    created_at: datetime
    traite_le: Optional[datetime] = None


class LivraisonOut(BaseModel):
    date: str
    sujet: str


class AskOut(BaseModel):
    id: int
    answer: str
    # Ce que l'assistant a trouvé, affiché tel quel sous la réponse :
    # un problème déjà réglé reste visible même si l'IA le résume mal.
    signalements: List[SignalementLieOut] = []
    livraisons: List[LivraisonOut] = []


class SimilairesOut(BaseModel):
    signalements: List[SignalementLieOut] = []
    livraisons: List[LivraisonOut] = []


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
    section: Optional[str] = None
    rejected_at: Optional[datetime] = None
    traite_le: Optional[datetime] = None
    traite_par: Optional[str] = None


class MonSignalementOut(BaseModel):
    """Vue « Mes signalements » du déclarant (sans user agent ni
    courriel)."""

    id: int
    status: str
    statut_libelle: str
    message: str
    section: Optional[str] = None
    context_url: Optional[str] = None
    resolution_notes: Optional[str] = None
    created_at: datetime
    traite_le: Optional[datetime] = None


class ReportPatch(BaseModel):
    status: Optional[str] = None  # accepted | rejected | resolved | pending
    resolution_notes: Optional[str] = None
    section: Optional[str] = Field(default=None, max_length=64)


class BulkAction(BaseModel):
    ids: List[int]
    action: str  # accept | reject | resolve
    # Note commune facultative (ex. « réglé dans la livraison du 13 »),
    # posée sur chaque signalement qui n'en a pas déjà une.
    resolution_notes: Optional[str] = None


# ------------------------------ Question (cascade IA gratuite) ------------------------------

SYSTEM_PROMPT = """Tu es l'assistant du Centre d'aide de Kratos, le portail \
interne de Horizon Services Immobiliers (Montréal, Québec : construction et \
rénovation, gestion immobilière, prospection, entreprises). Le propriétaire \
est Steven.

TON RÔLE
- Expliquer comment fonctionne une chose dans Kratos et dire si un problème \
est DÉJÀ CONNU, EN COURS ou DÉJÀ RÉGLÉ, pour éviter de signaler à nouveau un \
bug déjà corrigé.
- Réponds en français québécois, concis et concret (5 à 10 lignes), et \
oriente vers la bonne page quand tu la connais.

COMMENT RÉPONDRE
- Appuie-toi D'ABORD sur le CONTEXTE fourni avec la question : \
signalements déjà faits (avec statut, date et note de traitement), \
livraisons datées (corrections et nouveautés mises en ligne) et notes de \
fonctionnement. Ce contexte est la vérité ; tes connaissances générales ne \
le sont pas.
- Si un signalement semblable est « réglé », dis-le en premier avec son \
numéro, sa date et la note ; s'il est « accepté », dis que c'est connu et \
prévu ; s'il est « refusé », donne la raison de la note. Si une livraison \
correspond, cite sa date et ce qu'elle a changé, et suggère de recharger la \
page (ou de vider le cache de l'application) si la personne voit encore \
l'ancien comportement.
- Si rien dans le contexte ne correspond, dis clairement que tu ne trouves \
rien là-dessus et propose l'onglet « Signaler un bug ». N'invente JAMAIS une \
page, un bouton ou une fonctionnalité.
- Termine par « Réponse indicative ».

VOLETS DU PORTAIL : Construction (/app : punch, projets, soumissions, PO, \
achats, factures, agenda, paie), Immobilier (/immobilier : immeubles, \
logements, baux, locataires, loyers, hypothèques, gestion locative), \
Entreprises (/entreprises : comptabilité, rencontres, employés, feuilles de \
temps), Prospection, Communication (téléphonie, textos), Développement \
logiciel, Zone employés mobile (/m), Espace investisseur.

APPELS
On peut te transmettre des appels qui mentionnent les mots-clés de la \
question (volet téléphonie). Utilise-les seulement s'ils sont pertinents et \
cite l'Appel #ID.

RENCONTRES
On peut aussi te transmettre des passages des rencontres (réunions \
d'équipe, conseils d'actionnaires). Pour « a-t-on parlé de X » ou « où en \
est le dossier Y », réponds à partir d'eux en citant la Rencontre #ID et \
sa date ; la recherche complète est sur Entreprises → Rencontres \
(« Demander à Kratos »)."""


def _sig_out(s: "kb.SignalementLie") -> SignalementLieOut:
    return SignalementLieOut(
        id=s.id,
        status=s.status,
        statut_libelle=s.statut_libelle,
        section=s.section,
        message=s.message,
        resolution_notes=s.resolution_notes,
        created_at=s.created_at,
        traite_le=s.traite_le,
    )


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

    # Base de connaissances : signalements déjà faits (statut + note),
    # livraisons datées, notes de fonctionnement du dépôt.
    try:
        signalements = await kb.chercher_signalements(db, body.question, limite=6)
    except Exception as exc:  # noqa: BLE001
        log.warning("help: recherche des signalements impossible: %s", exc)
        signalements = []
    livraisons = kb.chercher_livraisons(body.question, limite=10)
    notes = kb.chercher_notes(body.question, limite=2)

    # Appels qui mentionnent les mots-clés de la question — permet de
    # répondre à « est-ce qu'on a parlé de X avec Y ? ».
    try:
        call_matches = await _find_calls_for_question(db, body.question)
    except Exception as exc:  # noqa: BLE001
        log.warning("help: call search failed: %s", exc)
        call_matches = []

    blocs: list[str] = []
    section = kb.section_depuis_url(body.context_url)
    if section:
        blocs.append(f"La personne pose sa question depuis la section : {section}.")
    connaissances = kb.contexte_ia(signalements, livraisons, notes)
    blocs.append(
        "CONTEXTE :\n" + connaissances
        if connaissances
        else "CONTEXTE : aucun signalement, aucune livraison ni note ne "
        "correspond aux mots de la question."
    )
    if call_matches:
        blocs.append(
            "APPELS QUI MENTIONNENT CES MOTS :\n"
            + "\n\n---\n".join(_format_call_for_context(c) for c in call_matches)
        )
    # Rencontres (2026-11-13) : « a-t-on discuté de X, où en est le
    # dossier Y » — passages des rencontres qui couvrent la question,
    # seulement pour qui voit la page Rencontres (conseils
    # d'actionnaires).
    try:
        from app.services.assistant_catalogue import utilisateur_a_acces_page
        from app.services.rencontre_recherche import contexte_pour_assistant

        if await utilisateur_a_acces_page(db, user, "entreprises.rencontres"):
            rencontres_ctx = await contexte_pour_assistant(
                db, body.question, limite=6
            )
            if rencontres_ctx:
                blocs.append(
                    "PASSAGES DES RENCONTRES QUI EN PARLENT (ordre "
                    "chronologique, la plus récente fait foi) :\n"
                    + rencontres_ctx
                )
    except Exception as exc:  # noqa: BLE001
        log.warning("help: recherche rencontres échouée: %s", exc)
    blocs.append(f"Question de l'utilisateur : {body.question}")
    user_content = "\n\n".join(blocs)

    # Cascade IA gratuite : Groq en priorité (gratuit/rapide), repli
    # automatique Gemini puis Anthropic via app.integrations.ai.chat().
    try:
        res = await chat(
            messages=[Message(role="user", content=user_content)],
            system=SYSTEM_PROMPT,
            prefer="groq",
            max_tokens=900,
            temperature=0.2,
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
        section=section,
    )
    db.add(rec)
    await db.commit()
    await db.refresh(rec)
    return AskOut(
        id=rec.id,
        answer=answer,
        signalements=[_sig_out(s) for s in signalements],
        livraisons=[LivraisonOut(date=l.date, sujet=l.sujet) for l in livraisons],
    )


@router.get(
    "/similaires",
    response_model=SimilairesOut,
    summary="Signalements et livraisons semblables à un texte (déjà réglé ?)",
)
async def similaires(
    db: DBSession,
    _: CurrentUser,
    q: str = Query(min_length=2, max_length=4000),
) -> SimilairesOut:
    """Sert l'onglet « Signaler un bug » : avant d'envoyer, la personne
    voit les signalements semblables (réglés, en cours, refusés) et les
    corrections déjà livrées."""
    signalements = await kb.chercher_signalements(db, q, limite=5)
    livraisons = kb.chercher_livraisons(q, limite=5)
    return SimilairesOut(
        signalements=[_sig_out(s) for s in signalements],
        livraisons=[LivraisonOut(date=l.date, sujet=l.sujet) for l in livraisons],
    )


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
        resolution_notes=rec.resolution_notes,
        section=rec.section or kb.section_depuis_url(rec.context_url),
        rejected_at=rec.rejected_at,
        traite_le=kb.date_traitement(rec),
        traite_par=rec.traite_par,
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
        section=kb.section_depuis_url(context_url),
    )
    db.add(rec)
    await db.commit()
    await db.refresh(rec)
    return _serialize_report(rec)


@router.get(
    "/mes-signalements",
    response_model=List[MonSignalementOut],
    summary="Mes signalements : statut, note et date de traitement",
)
async def mes_signalements(db: DBSession, user: CurrentUser) -> List[MonSignalementOut]:
    rows = (
        await db.execute(
            select(HelpRequest)
            .where(HelpRequest.kind == HelpRequestKind.BUG.value)
            .where(HelpRequest.user_id == user.id)
            .order_by(HelpRequest.created_at.desc())
            .limit(200)
        )
    ).scalars().all()
    return [
        MonSignalementOut(
            id=r.id,
            status=r.status,
            statut_libelle=kb.STATUT_LIBELLE.get(r.status, r.status),
            message=r.message,
            section=r.section or kb.section_depuis_url(r.context_url),
            context_url=r.context_url,
            resolution_notes=r.resolution_notes,
            created_at=r.created_at,
            traite_le=kb.date_traitement(r),
        )
        for r in rows
    ]


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


_STATUTS_DECISION = {
    HelpRequestStatus.ACCEPTED.value: "accepté",
    HelpRequestStatus.REJECTED.value: "refusé",
    HelpRequestStatus.RESOLVED.value: "réglé",
}

KIND_NOTIF_BUG = "bug_traite"


def _appliquer_statut(rec: HelpRequest, new_status: str, par, now: datetime) -> bool:
    """Pose le statut et les dates d'historique. Renvoie vrai si le
    statut a changé (une notification au déclarant est alors due)."""
    if rec.status == new_status:
        return False
    rec.status = new_status
    if new_status == HelpRequestStatus.ACCEPTED.value and rec.accepted_at is None:
        rec.accepted_at = now
    if new_status == HelpRequestStatus.RESOLVED.value:
        rec.resolved_at = now
    if new_status == HelpRequestStatus.REJECTED.value:
        rec.rejected_at = now
    if new_status == HelpRequestStatus.PENDING.value:
        rec.traite_le = None
        rec.traite_par = None
    else:
        rec.traite_le = now
        rec.traite_par = getattr(par, "email", None)
    if not rec.section:
        rec.section = kb.section_depuis_url(rec.context_url)
    return True


async def _notifier_declarant(db, rec: HelpRequest, par) -> None:
    """Cloche (et push) au déclarant : signalement accepté, refusé ou
    réglé, avec la note. Pas de notification à soi-même."""
    verbe = _STATUTS_DECISION.get(rec.status)
    if verbe is None or rec.user_id is None:
        return
    if par is not None and getattr(par, "id", None) == rec.user_id:
        return
    from app.services.notifications import notify

    extrait = " ".join(rec.message.split())
    if len(extrait) > 90:
        extrait = extrait[:90] + "…"
    lignes = [f"« {extrait} »"]
    if rec.section:
        lignes.append(f"Section : {rec.section}")
    if rec.resolution_notes:
        lignes.append(f"Note : {rec.resolution_notes.strip()[:300]}")
    chemin = kb.chemin_sans_langue(rec.context_url)
    if not chemin or chemin == "/":
        chemin = "/app"
    try:
        await notify(
            db,
            user_id=rec.user_id,
            kind=KIND_NOTIF_BUG,
            title=f"Ton signalement #{rec.id} a été {verbe}",
            body="\n".join(lignes),
            href=f"{chemin}?aide=mes-signalements",
        )
    except Exception:  # noqa: BLE001 — jamais bloquant pour le triage
        log.exception("help: notification du déclarant impossible (#%s)", rec.id)


@router.patch(
    "/reports/{report_id}",
    response_model=ReportOut,
    summary="Changer le statut d'un bug (owner)",
)
async def patch_report(
    report_id: int,
    body: ReportPatch,
    db: DBSession,
    owner: RequireOwner,
) -> ReportOut:
    """Accepter, refuser, régler (ou remettre en attente) un signalement,
    avec note et section. Le déclarant reçoit une notification à chaque
    décision (accepté / refusé / réglé), note comprise.

    Pour Claude Code : après avoir livré la correction d'un bug, faire
    ``PATCH`` avec ``status=resolved``, ``resolution_notes`` (ce qui a été
    corrigé, date de livraison) et ``section``."""
    rec = (
        await db.execute(
            select(HelpRequest).where(HelpRequest.id == report_id)
        )
    ).scalar_one_or_none()
    if rec is None or rec.kind != HelpRequestKind.BUG.value:
        raise HTTPException(status_code=404, detail="Bug introuvable")

    now = datetime.now(timezone.utc)

    # La note et la section d'abord : la notification les reprend.
    if body.resolution_notes is not None:
        # Vide → null (effacement)
        rec.resolution_notes = body.resolution_notes.strip() or None
    if body.section is not None:
        rec.section = body.section.strip() or None

    change = False
    if body.status is not None:
        new_status = body.status.lower().strip()
        if new_status not in (
            HelpRequestStatus.ACCEPTED.value,
            HelpRequestStatus.REJECTED.value,
            HelpRequestStatus.RESOLVED.value,
            HelpRequestStatus.PENDING.value,
        ):
            raise HTTPException(status_code=400, detail="Statut invalide")
        change = _appliquer_statut(rec, new_status, owner, now)

    if change:
        await _notifier_declarant(db, rec, owner)
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
    owner: RequireOwner,
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
    note = (body.resolution_notes or "").strip() or None
    rows = (
        await db.execute(
            select(HelpRequest)
            .where(HelpRequest.id.in_(body.ids))
            .where(HelpRequest.kind == HelpRequestKind.BUG.value)
        )
    ).scalars().all()
    updated = 0
    for rec in rows:
        if note and not rec.resolution_notes:
            rec.resolution_notes = note
        if _appliquer_statut(rec, new_status, owner, now):
            await _notifier_declarant(db, rec, owner)
        updated += 1
    await db.commit()
    return {"updated": updated}


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
    item, puis appelle PATCH .../reports/{id} avec status=resolved,
    resolution_notes et section pour marquer chaque bug livré (le
    déclarant en est notifié).
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
