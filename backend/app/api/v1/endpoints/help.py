"""Endpoints pour le bouton « Aide ».

- POST /api/v1/help/ask : poser une question, réponse via Claude API
- POST /api/v1/help/reports : signaler un bug (toute personne logée)
- GET  /api/v1/help/reports : liste des bugs (owner only)
- PATCH /api/v1/help/reports/{id} : accepter/rejeter/résoudre (owner)
- POST /api/v1/help/reports/bulk : actions en lot (owner)
- GET  /api/v1/help/reports/accepted : bugs acceptés en attente de
  correction. Endpoint pratique pour Claude Code : « lis les bugs
  acceptés », l'agent fetch et marque resolved après livraison.
"""

from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, update

from app.api.deps import CurrentUser, DBSession, RequireOwner
from app.core.config import settings
from app.models.help_request import HelpRequest, HelpRequestKind, HelpRequestStatus

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


class ReportPatch(BaseModel):
    status: str  # accepted | rejected | resolved


class BulkAction(BaseModel):
    ids: List[int]
    action: str  # accept | reject | resolve


# ------------------------------ Question (Claude API) ------------------------------

SYSTEM_PROMPT = """Tu es l'assistant d'aide intégré à h2.0, le logiciel de \
gestion de chantiers de Horizon Services Immobiliers (Montréal, Québec, \
construction et rénovation, RBQ 5868-5991-01).

Tu aides les employés et le bureau à naviguer le logiciel. Réponds en \
français québécois, ton concis et pragmatique. Si tu ne sais pas, dis-le \
clairement et propose à la personne d'utiliser le bouton « Signaler un \
bug » pour faire monter la question à Steven.

Sections principales du logiciel :
- Construction : projets (chantiers), phases, tâches, agenda, punch
- Ventes : prospects, soumissions (devis), contacts, factures
- Achats : POs (bons de commande, autorisations internes) et Achats \
(transactions réelles avec impact comptable QuickBooks)
- Paramètres : numérotation QB, comptes QB, employés, sous-traitants

Workflow PO → Achat : un PO est une autorisation d'achat (planification, \
sans impact comptable). Quand l'employé revient avec sa facture \
fournisseur, on convertit le PO en Achat (qui pousse dans QuickBooks \
comme Bill ou Purchase selon le mode de paiement).
"""


@router.post(
    "/ask",
    response_model=AskOut,
    summary="Poser une question à l'assistant Claude",
)
async def ask(
    body: AskIn,
    db: DBSession,
    user: CurrentUser,
) -> AskOut:
    if not settings.anthropic_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Assistant désactivé : ANTHROPIC_API_KEY n'est pas "
                "configuré. Tu peux quand même signaler un bug."
            ),
        )

    # Import paresseux pour ne pas planter au démarrage si la lib bouge.
    import anthropic

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    try:
        msg = client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=1024,
            system=[
                {
                    "type": "text",
                    "text": SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": body.question}],
        )
        answer_parts = [b.text for b in msg.content if b.type == "text"]
        answer = "\n".join(answer_parts).strip() or "(réponse vide)"
    except anthropic.APIError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Claude API : {e.message[:200]}",
        )
    except Exception as e:  # pragma: no cover
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


@router.post(
    "/reports",
    response_model=ReportOut,
    status_code=status.HTTP_201_CREATED,
    summary="Signaler un bug ou une demande",
)
async def create_report(
    body: ReportIn,
    db: DBSession,
    user: CurrentUser,
) -> ReportOut:
    rec = HelpRequest(
        user_id=user.id,
        user_email=user.email,
        kind=HelpRequestKind.BUG.value,
        status=HelpRequestStatus.PENDING.value,
        message=body.message,
        context_url=body.context_url,
        user_agent=body.user_agent,
    )
    db.add(rec)
    await db.commit()
    await db.refresh(rec)
    return ReportOut.model_validate(rec)


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
    return [ReportOut.model_validate(r) for r in rows]


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

    new_status = body.status.lower().strip()
    if new_status not in (
        HelpRequestStatus.ACCEPTED.value,
        HelpRequestStatus.REJECTED.value,
        HelpRequestStatus.RESOLVED.value,
        HelpRequestStatus.PENDING.value,
    ):
        raise HTTPException(status_code=400, detail="Statut invalide")

    now = datetime.now(timezone.utc)
    rec.status = new_status
    if new_status == HelpRequestStatus.ACCEPTED.value and rec.accepted_at is None:
        rec.accepted_at = now
    if new_status == HelpRequestStatus.RESOLVED.value:
        rec.resolved_at = now
    await db.commit()
    await db.refresh(rec)
    return ReportOut.model_validate(rec)


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
    return [ReportOut.model_validate(r) for r in rows]
