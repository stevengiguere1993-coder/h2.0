"""Reçus → QuickBooks, saisie « en miroir » (pôle Entreprises, Steven 2026-10-04).

    GET  /api/v1/recus-qbo/entreprises                   entreprises + connexion QuickBooks
    GET  /api/v1/recus-qbo/entreprises/{id}/choix        listes du formulaire, lues dans QB
    POST /api/v1/recus-qbo/entreprises/{id}/envoyer      crée la Dépense / Facture + photo
    POST /api/v1/recus-qbo/saisies/{id}/photo            renvoie seulement la photo
    GET  /api/v1/recus-qbo/journal                       derniers envois (trace minimale)

Le reçu n'est pas gardé dans Kratos : il vit dans QuickBooks et la copie de
nuit (``qbo_recus_drive``) le range dans le Drive. Toutes les routes exigent
la page « Comptabilité » du pôle (``page:entreprises.comptabilite``, onglet
« Nouveau reçu ») en plus de l'accès au pôle : c'est une écriture comptable,
et la section est réservée aux propriétaires tant qu'elle est en
développement.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from app.api.deps import CurrentUser, DBSession
from app.services import recu_qbo_saisie as svc
from app.services.permissions_service import require_capability

router = APIRouter(
    prefix="/recus-qbo",
    tags=["recus-qbo"],
    dependencies=[Depends(require_capability("page:entreprises.comptabilite"))],
)


def _erreur(exc: svc.SaisieErreur) -> JSONResponse:
    return JSONResponse(
        status_code=exc.statut, content={"detail": exc.message, **exc.extra}
    )


def _message_validation(exc: ValidationError) -> str:
    """Première erreur du formulaire, en français : nos règles (« Value
    error, … ») telles quelles, sinon le champ en cause."""
    erreurs = exc.errors()
    if not erreurs:
        return "Reçu invalide."
    e = erreurs[0]
    if e.get("type") == "value_error":
        return str(e.get("msg") or "").removeprefix("Value error, ") or "Reçu invalide."
    champ = ".".join(str(x) for x in e.get("loc") or ()) or "reçu"
    return f"Champ « {champ} » invalide."


async def _lire_fichier(fichier: UploadFile) -> svc.FichierRecu:
    contenu = await fichier.read()
    return svc.verifier_fichier(fichier.filename, fichier.content_type, contenu)


@router.get("/entreprises", summary="Entreprises et leur compagnie QuickBooks")
async def entreprises(db: DBSession, _: CurrentUser) -> List[Dict[str, Any]]:
    return await svc.entreprises(db)


@router.get(
    "/entreprises/{entreprise_id}/choix",
    summary="Listes du formulaire de reçu, lues dans le QuickBooks de l'entreprise",
)
async def choix(entreprise_id: int, db: DBSession, _: CurrentUser) -> Any:
    try:
        return await svc.choix(db, entreprise_id)
    except svc.SaisieErreur as exc:
        return _erreur(exc)


@router.post(
    "/entreprises/{entreprise_id}/envoyer",
    summary="Crée la dépense (payée) ou la facture fournisseur (à payer) dans QuickBooks, photo jointe",
)
async def envoyer(
    entreprise_id: int,
    db: DBSession,
    user: CurrentUser,
    donnees: str = Form(..., description="Champs du reçu (JSON, cf. RecuIn)"),
    fichier: Optional[UploadFile] = File(default=None),
) -> Any:
    try:
        recu = svc.RecuIn.model_validate_json(donnees)
    except ValidationError as exc:
        raise HTTPException(422, _message_validation(exc)) from exc
    try:
        piece = await _lire_fichier(fichier) if fichier is not None else None
        return await svc.envoyer(
            db, entreprise_id=entreprise_id, user=user, recu=recu, fichier=piece
        )
    except svc.SaisieErreur as exc:
        return _erreur(exc)


@router.post(
    "/saisies/{saisie_id}/photo",
    summary="Joint (de nouveau) la photo d'un reçu déjà créé dans QuickBooks",
)
async def reprendre_photo(
    saisie_id: int,
    db: DBSession,
    _: CurrentUser,
    fichier: UploadFile = File(...),
) -> Any:
    try:
        piece = await _lire_fichier(fichier)
        return await svc.reprendre_photo(db, saisie_id=saisie_id, fichier=piece)
    except svc.SaisieErreur as exc:
        return _erreur(exc)


@router.get("/journal", summary="Derniers reçus envoyés à QuickBooks (trace minimale)")
async def journal(
    db: DBSession,
    _: CurrentUser,
    entreprise_id: Optional[int] = Query(default=None),
    limit: int = Query(default=30, ge=1, le=200),
) -> List[Dict[str, Any]]:
    return await svc.journal(db, entreprise_id=entreprise_id, limit=limit)
