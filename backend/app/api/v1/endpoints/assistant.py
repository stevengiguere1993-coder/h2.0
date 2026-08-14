"""Assistant IA Kratos — API de la phase 1 (fondation sans LLM).

Expose le catalogue d'outils et le cycle de vie des cartes d'action :

- ``GET  /assistant/outils`` : le catalogue FILTRÉ selon les permissions
  de page de l'utilisateur courant (c'est ce que le LLM recevra en
  phase 2 comme définitions d'outils) ;
- ``POST /assistant/outils/{id}/executer`` : exécution DIRECTE d'un
  outil de LECTURE seulement (400 si l'outil est en écriture — une
  écriture passe toujours par une carte d'action confirmée) ;
- ``POST /assistant/actions`` : propose une ÉCRITURE — valide les
  paramètres via le mode aperçu du handler (rien n'est écrit), crée la
  ligne ``proposee`` et retourne id + aperçu (la carte) ;
- ``POST /assistant/actions/{id}/confirmer`` : exécute pour vrai (mêmes
  services que la saisie manuelle), statut ``confirmee`` ou ``echouee``
  + erreur, et consigne au journal d'audit avec la mention « par Kratos
  IA au nom de {user} » ;
- ``POST /assistant/actions/{id}/annuler`` ;
- ``GET  /assistant/actions?statut=`` : l'historique de l'utilisateur.

Sécurité : garde d'authentification standard (JWT) ; chaque outil est
en plus soumis à sa permission de PAGE (registre central). Une action
ne peut être confirmée/annulée QUE par l'utilisateur qui l'a proposée,
et sa permission est RE-vérifiée au moment de confirmer (pas seulement
à la proposition — une permission retirée entre-temps bloque).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import CurrentUser, DBSession
from app.models.assistant import STATUTS_ACTION, AssistantAction
from app.services.assistant_catalogue import (
    OUTILS_PAR_ID,
    OutilAssistant,
    ParamsInvalides,
    executer_outil,
    outils_pour_utilisateur,
    utilisateur_a_acces_page,
)
from app.services.audit import log_action

log = logging.getLogger(__name__)
router = APIRouter(prefix="/assistant", tags=["assistant"])


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ── Schémas ─────────────────────────────────────────────────────────


class ExecuterIn(BaseModel):
    """Paramètres d'une exécution directe (outil de lecture)."""

    params: dict = Field(default_factory=dict)


class ProposerActionIn(BaseModel):
    """Proposition d'une écriture (création de carte d'action)."""

    outil: str
    params: dict = Field(default_factory=dict)


class ActionRead(BaseModel):
    id: int
    outil: str
    params: dict
    apercu: str
    statut: str
    resultat: Optional[dict] = None
    erreur: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    executee_le: Optional[datetime] = None


def _action_to_read(a: AssistantAction) -> ActionRead:
    def _loads(raw: Optional[str]) -> Optional[dict]:
        if not raw:
            return None
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {"valeur": parsed}
        except ValueError:
            return None

    return ActionRead(
        id=a.id,
        outil=a.outil,
        params=_loads(a.params_json) or {},
        apercu=a.apercu,
        statut=a.statut,
        resultat=_loads(a.resultat_json),
        erreur=a.erreur,
        created_at=a.created_at,
        updated_at=a.updated_at,
        executee_le=a.executee_le,
    )


# ── Helpers ─────────────────────────────────────────────────────────


def _outil_ou_404(outil_id: str) -> OutilAssistant:
    outil = OUTILS_PAR_ID.get(outil_id)
    if outil is None:
        raise HTTPException(
            status_code=404, detail=f"Outil « {outil_id} » inconnu."
        )
    return outil


async def _exiger_permission(db, user, outil: OutilAssistant) -> None:
    """403 si l'utilisateur n'a pas la page requise par l'outil — le
    catalogue filtré et l'exécution disent toujours la même chose."""
    if not await utilisateur_a_acces_page(db, user, outil.permission):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"Outil « {outil.id} » non autorisé : la page "
                f"« {outil.permission} » n'est pas accessible à ce compte."
            ),
        )


async def _action_de_l_utilisateur(
    db, user, action_id: int
) -> AssistantAction:
    """L'action, si et seulement si elle appartient à l'utilisateur
    courant (sinon 403 — personne ne confirme la carte d'un autre)."""
    action = await db.get(AssistantAction, action_id)
    if action is None:
        raise HTTPException(
            status_code=404, detail=f"Action #{action_id} introuvable."
        )
    if action.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Cette action appartient à un autre utilisateur — seul "
                "son auteur peut la confirmer ou l'annuler."
            ),
        )
    return action


# ── Endpoints ───────────────────────────────────────────────────────


@router.get("/outils", response_model=List[dict])
async def catalogue_outils(db: DBSession, user: CurrentUser) -> List[dict]:
    """Le catalogue d'outils FILTRÉ selon les permissions de page de
    l'utilisateur courant (définitions prêtes pour le LLM de phase 2)."""
    visibles = await outils_pour_utilisateur(db, user)
    return [o.public() for o in visibles]


@router.post("/outils/{outil_id}/executer")
async def executer_outil_lecture(
    outil_id: str,
    payload: ExecuterIn,
    db: DBSession,
    user: CurrentUser,
) -> dict:
    """Exécute DIRECTEMENT un outil de LECTURE et retourne son résultat.

    400 si l'outil est en écriture : toute écriture passe par une carte
    d'action (« POST /assistant/actions ») confirmée par l'humain."""
    outil = _outil_ou_404(outil_id)
    if not outil.lecture:
        raise HTTPException(
            status_code=400,
            detail=(
                f"« {outil.id} » est un outil d'ÉCRITURE : proposer une "
                "action (POST /assistant/actions) puis la confirmer."
            ),
        )
    await _exiger_permission(db, user, outil)
    try:
        return await executer_outil(db, user, outil, payload.params)
    except ParamsInvalides as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.post(
    "/actions",
    response_model=ActionRead,
    status_code=status.HTTP_201_CREATED,
)
async def proposer_action(
    payload: ProposerActionIn,
    db: DBSession,
    user: CurrentUser,
) -> ActionRead:
    """Propose une ÉCRITURE : valide les paramètres via le mode aperçu
    du handler (RIEN n'est écrit) et crée la carte au statut
    ``proposee``. La carte affiche l'aperçu ; l'écriture n'aura lieu
    qu'à la confirmation."""
    outil = _outil_ou_404(payload.outil)
    if outil.lecture:
        raise HTTPException(
            status_code=400,
            detail=(
                f"« {outil.id} » est un outil de LECTURE : l'exécuter "
                "directement (POST /assistant/outils/{id}/executer) — "
                "pas besoin de carte d'action."
            ),
        )
    await _exiger_permission(db, user, outil)

    try:
        apercu_res = await executer_outil(
            db, user, outil, payload.params, apercu_seulement=True
        )
    except ParamsInvalides as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    action = AssistantAction(
        user_id=user.id,
        outil=outil.id,
        params_json=json.dumps(payload.params, default=str),
        apercu=str(apercu_res.get("apercu") or outil.titre),
        statut="proposee",
    )
    db.add(action)
    await db.commit()
    await db.refresh(action)
    return _action_to_read(action)


@router.post("/actions/{action_id}/confirmer", response_model=ActionRead)
async def confirmer_action(
    action_id: int,
    db: DBSession,
    user: CurrentUser,
) -> ActionRead:
    """Exécute l'action POUR VRAI (mêmes services que la saisie
    manuelle). Statut ``confirmee`` + résultat, ou ``echouee`` + erreur
    FR si l'exécution échoue (la réponse porte le statut final).

    La permission de page est RE-vérifiée ici : une permission retirée
    entre la proposition et la confirmation bloque l'exécution."""
    action = await _action_de_l_utilisateur(db, user, action_id)
    if action.statut != "proposee":
        raise HTTPException(
            status_code=400,
            detail=(
                f"Cette action est déjà « {action.statut} » — seule une "
                "action proposée peut être confirmée."
            ),
        )
    outil = OUTILS_PAR_ID.get(action.outil)
    if outil is None or outil.lecture:
        raise HTTPException(
            status_code=400,
            detail=f"Outil « {action.outil} » inconnu ou non exécutable.",
        )
    await _exiger_permission(db, user, outil)

    try:
        params = json.loads(action.params_json or "{}")
    except ValueError:
        params = {}

    try:
        resultat = await executer_outil(db, user, outil, params)
    except Exception as exc:  # noqa: BLE001 — l'échec est un ÉTAT de la carte
        # L'exécution a pu laisser la transaction en vrac : on repart
        # proprement avant d'écrire l'échec sur la carte.
        await db.rollback()
        action = await db.get(AssistantAction, action_id)
        if isinstance(exc, HTTPException):
            action.erreur = str(exc.detail)
        elif isinstance(exc, (ParamsInvalides, ValueError)):
            action.erreur = str(exc)
        else:
            log.exception(
                "assistant: échec inattendu de l'outil %s", outil.id
            )
            action.erreur = "Erreur interne pendant l'exécution de l'outil."
        action.statut = "echouee"
        action.executee_le = _now()
        await db.commit()
        # updated_at est généré côté serveur (onupdate) → refresh avant
        # de sérialiser, sinon accès expiré hors contexte async.
        await db.refresh(action)
        return _action_to_read(action)

    action.statut = "confirmee"
    action.resultat_json = json.dumps(resultat, default=str)
    action.executee_le = _now()
    # Journal d'audit : l'écriture a été faite par l'assistant AU NOM de
    # l'utilisateur (en plus des audits éventuels du service métier).
    await log_action(
        db,
        user=user,
        action="assistant.action_confirmee",
        entity_type="assistant_action",
        entity_id=action.id,
        details={
            "outil": outil.id,
            "apercu": action.apercu,
            "via": f"par Kratos IA au nom de {user.display_name}",
        },
    )
    await db.commit()
    await db.refresh(action)
    return _action_to_read(action)


@router.post("/actions/{action_id}/annuler", response_model=ActionRead)
async def annuler_action(
    action_id: int,
    db: DBSession,
    user: CurrentUser,
) -> ActionRead:
    """Annule une action proposée — RIEN n'a été écrit et rien ne le
    sera. Seul l'auteur de la carte peut l'annuler."""
    action = await _action_de_l_utilisateur(db, user, action_id)
    if action.statut != "proposee":
        raise HTTPException(
            status_code=400,
            detail=(
                f"Cette action est déjà « {action.statut} » — seule une "
                "action proposée peut être annulée."
            ),
        )
    action.statut = "annulee"
    await db.commit()
    await db.refresh(action)
    return _action_to_read(action)


@router.get("/actions", response_model=List[ActionRead])
async def lister_actions(
    db: DBSession,
    user: CurrentUser,
    statut: Optional[str] = None,
    limit: int = 50,
) -> List[ActionRead]:
    """Historique des actions de l'UTILISATEUR COURANT (les cartes des
    autres comptes ne sont jamais visibles), les plus récentes d'abord.
    ``statut`` filtre sur proposee / confirmee / annulee / echouee."""
    q = select(AssistantAction).where(AssistantAction.user_id == user.id)
    if statut is not None:
        if statut not in STATUTS_ACTION:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Statut inconnu « {statut} » — choix : "
                    + ", ".join(STATUTS_ACTION)
                    + "."
                ),
            )
        q = q.where(AssistantAction.statut == statut)
    q = q.order_by(AssistantAction.id.desc()).limit(max(1, min(limit, 200)))
    rows = (await db.execute(q)).scalars().all()
    return [_action_to_read(a) for a in rows]
