"""Fusion de deux fiches d'immeuble (retour Steven 2026-10-29).

« Le 710 Legendre et le 9085 Millen ont une hypothèque conjointe, mais le
calcul est en deux coups. C'est un 12 logements avec deux adresses de six
appartements : permettre de fusionner leur fiche, comme un seul
immeuble. » La fiche « source » est absorbée par la fiche « cible » (voir
``app.services.immeuble_fusion``) : tout y est rattaché, l'adresse de la
source devient l'adresse secondaire de la cible, puis la source est
supprimée. Réservé à qui peut supprimer un immeuble ; les deux fiches
doivent être visibles par l'utilisateur. Un aperçu (GET) dit ce qui sera
déplacé avant de confirmer (POST).
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import CurrentUser, DBSession
from app.api.v1.endpoints.immobilier import _immeuble_to_read
from app.core.permissions import visible_immeuble_ids
from app.models.immobilier import Immeuble
from app.models.user import User
from app.schemas.immobilier import (
    FusionImmeublesApercu,
    FusionImmeublesOptions,
    FusionImmeublesResultat,
)
from app.services.immeuble_fusion import FusionImpossible, apercu_fusion, fusionner
from app.services.permissions_service import require_capability

log = logging.getLogger(__name__)

router = APIRouter(prefix="/immobilier", tags=["immobilier-fusion"])

PeutSupprimer = Annotated[User, Depends(require_capability("immeuble.delete"))]


def _require_volet(user: CurrentUser) -> None:
    volets = getattr(user, "volets", None)
    if volets is None or "immobilier" not in volets:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Volet « Immobilier » non autorisé pour cet utilisateur.",
        )


async def _immeuble_visible_ou_404(db, user, immeuble_id: int) -> Immeuble:
    imm = await db.get(Immeuble, immeuble_id)
    if imm is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Immeuble {immeuble_id} introuvable.",
        )
    visibles = await visible_immeuble_ids(db, user)
    if visibles is not None and imm.id not in visibles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Accès à cet immeuble non autorisé.",
        )
    return imm


async def _paire(db, user, cible_id: int, source_id: int) -> tuple[Immeuble, Immeuble]:
    _require_volet(user)
    if cible_id == source_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Un immeuble ne se fusionne pas avec lui-même.",
        )
    cible = await _immeuble_visible_ou_404(db, user, cible_id)
    source = await _immeuble_visible_ou_404(db, user, source_id)
    return cible, source


@router.get(
    "/immeubles/{immeuble_id}/fusion/apercu",
    response_model=FusionImmeublesApercu,
    summary="Aperçu d'une fusion : ce que l'immeuble source apporterait à celui-ci",
)
async def apercu_fusion_immeubles(
    immeuble_id: int,
    db: DBSession,
    user: PeutSupprimer,
    source_immeuble_id: int = Query(
        ..., description="Immeuble qui serait absorbé par {immeuble_id}."
    ),
) -> FusionImmeublesApercu:
    cible, source = await _paire(db, user, immeuble_id, source_immeuble_id)
    return FusionImmeublesApercu(**await apercu_fusion(db, cible, source))


@router.post(
    "/immeubles/{immeuble_id}/fusion",
    response_model=FusionImmeublesResultat,
    summary="Fusionner un autre immeuble dans celui-ci (la source est supprimée)",
)
async def fusionner_immeubles(
    immeuble_id: int,
    payload: FusionImmeublesOptions,
    db: DBSession,
    user: PeutSupprimer,
) -> FusionImmeublesResultat:
    cible, source = await _paire(db, user, immeuble_id, payload.source_immeuble_id)
    try:
        resume = await fusionner(
            db,
            cible,
            source,
            prefixe_numeros=payload.prefixe_numeros,
            exclure_hypotheques=payload.exclure_hypotheques,
            purchase_price=payload.purchase_price,
        )
    except FusionImpossible as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    except Exception:
        await db.rollback()
        raise
    log.info(
        "fusion immeubles par %s : #%s absorbé par #%s",
        getattr(user, "email", "?"), resume["immeuble_supprime_id"], cible.id,
    )
    return FusionImmeublesResultat(immeuble=_immeuble_to_read(cible), **resume)
