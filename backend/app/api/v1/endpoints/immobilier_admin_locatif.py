"""Admin locative (Phil 2026-11-10) — routes.

Préfixe ``/immobilier/admin-locative`` (volet Immobilier, gestionnaires) :

- GET  /contacts?q=&inclure_archives=   → carnet de cette section (locateurs, locataires, cautions hors système)
- POST /contacts · PATCH /contacts/{id} · DELETE /contacts/{id} (retire du carnet, sans supprimer)
- GET  /avis                            → avis de renouvellement (TAL-806) hors système + suivi de la réponse
- POST /avis                            → préparer un avis (brouillon + PDF officiel)
- GET  /avis/{id} · PATCH /avis/{id}    → brouillon seulement
- POST /avis/{id}/envoyer               → envoi au locataire (lien de réponse en ligne) — daté du jour
- POST /avis/{id}/annuler
- GET  /registre?annee=AAAA             → tous les baux officiels générés (qui, pour quel immeuble, quand)
                                          + résumé par mois de ce que le TAL devrait facturer

Les baux indépendants eux-mêmes restent sous ``/immobilier/tal-bail``
(``/independants``, ``/transmissions/{id}``…).
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.api.deps import DBSession, RequireManager
from app.models.admin_locatif import AdmLocAvis, AdmLocContact
from app.models.immobilier import ImmDocument
from app.services import admin_locatif as svc
from app.services import tal_bail as tal
from app.services.audit import log_action

log = logging.getLogger(__name__)

router = APIRouter(prefix="/immobilier/admin-locative", tags=["immobilier-admin-locative"])


def _erreur(exc: svc.AdminLocatifError) -> HTTPException:
    return HTTPException(status_code=exc.http_status, detail=exc.message)


# ─── Contacts ─────────────────────────────────────────────────────────


class ContactIn(BaseModel):
    nom: Optional[str] = Field(default=None, max_length=255)
    telephone: Optional[str] = Field(default=None, max_length=40)
    courriel: Optional[str] = Field(default=None, max_length=320)
    adresse: Optional[str] = Field(default=None, max_length=500)
    role: Optional[str] = Field(default=None, max_length=16)
    notes: Optional[str] = Field(default=None, max_length=4000)
    actif: Optional[bool] = None


async def _contact_or_404(db, contact_id: int) -> AdmLocContact:
    c = await db.get(AdmLocContact, contact_id)
    if c is None:
        raise HTTPException(status_code=404, detail="Contact introuvable.")
    return c


@router.get("/contacts", summary="Carnet de contacts de l'Admin locative")
async def lister_contacts(
    db: DBSession, user: RequireManager,
    q: Optional[str] = None, inclure_archives: bool = False,
) -> Dict[str, Any]:
    rows = await svc.lister_contacts(db, q=q, inclure_archives=inclure_archives)
    return {"items": [svc.resume_contact(c) for c in rows], "total": len(rows)}


@router.post("/contacts", summary="Ajouter un contact", status_code=201)
async def creer_contact(payload: ContactIn, db: DBSession, user: RequireManager) -> Dict[str, Any]:
    try:
        c = await svc.creer_contact(db, user=user, champs=payload.model_dump(exclude_unset=True))
    except svc.AdminLocatifError as exc:
        raise _erreur(exc) from exc
    await log_action(db, user=user, action="admin_locatif.contact_cree", entity_type="adm_loc_contact", entity_id=c.id,
                     details={"nom": c.nom, "role": c.role})
    await db.commit()
    await db.refresh(c)
    return svc.resume_contact(c)


@router.patch("/contacts/{contact_id}", summary="Modifier un contact")
async def modifier_contact(contact_id: int, payload: ContactIn, db: DBSession, user: RequireManager) -> Dict[str, Any]:
    c = await _contact_or_404(db, contact_id)
    try:
        await svc.modifier_contact(db, c, payload.model_dump(exclude_unset=True))
    except svc.AdminLocatifError as exc:
        raise _erreur(exc) from exc
    await db.commit()
    await db.refresh(c)
    return svc.resume_contact(c)


@router.delete("/contacts/{contact_id}", summary="Retirer un contact du carnet (sans le supprimer)")
async def archiver_contact(contact_id: int, db: DBSession, user: RequireManager) -> Dict[str, Any]:
    c = await _contact_or_404(db, contact_id)
    await svc.modifier_contact(db, c, {"actif": False})
    await log_action(db, user=user, action="admin_locatif.contact_retire", entity_type="adm_loc_contact", entity_id=c.id,
                     details={"nom": c.nom})
    await db.commit()
    await db.refresh(c)
    return svc.resume_contact(c)


# ─── Avis de renouvellement ───────────────────────────────────────────


class AvisIn(BaseModel):
    libelle: Optional[str] = Field(default=None, max_length=255)
    locateur_nom: Optional[str] = Field(default=None, max_length=255)
    locateur_adresse: Optional[str] = Field(default=None, max_length=500)
    locateur_telephone: Optional[str] = Field(default=None, max_length=40)
    locateur_courriel: Optional[str] = Field(default=None, max_length=320)
    locataire_nom: Optional[str] = Field(default=None, max_length=255)
    locataire_courriel: Optional[str] = Field(default=None, max_length=320)
    logement_adresse: Optional[str] = Field(default=None, max_length=500)
    logement_numero: Optional[str] = Field(default=None, max_length=32)
    logement_ville: Optional[str] = Field(default=None, max_length=128)
    bail_date_debut: Optional[date] = None
    bail_date_fin: Optional[date] = None
    loyer_actuel: Optional[float] = Field(default=None, ge=0, le=1_000_000)
    modif_mode: Optional[str] = Field(default=None, max_length=16)
    nouveau_loyer: Optional[float] = Field(default=None, ge=0, le=1_000_000)
    hausse_montant: Optional[float] = Field(default=None, ge=0, le=1_000_000)
    hausse_pct: Optional[float] = Field(default=None, ge=0, le=1000)
    nouvelle_date_debut: Optional[date] = None
    nouvelle_date_fin: Optional[date] = None
    autres_modifications: Optional[str] = Field(default=None, max_length=4000)


class EnvoyerAvisIn(BaseModel):
    #: Courriel du locataire pour CET envoi (défaut : celui de l'avis).
    courriel: Optional[str] = Field(default=None, max_length=320)


async def _avis_or_404(db, avis_id: int) -> AdmLocAvis:
    a = await db.get(AdmLocAvis, avis_id)
    if a is None:
        raise HTTPException(status_code=404, detail="Avis introuvable.")
    return a


async def _avis_out(db, a: AdmLocAvis) -> Dict[str, Any]:
    doc = await db.get(ImmDocument, a.document_id) if a.document_id else None
    return svc.resume_avis(a, doc)


@router.get("/avis", summary="Avis de renouvellement hors système, avec le suivi de la réponse")
async def lister_avis(db: DBSession, user: RequireManager, inclure_annules: bool = False) -> Dict[str, Any]:
    items = await svc.lister_avis(db, inclure_annules=inclure_annules)
    await db.commit()   # délai d'un mois dépassé → « réputé accepté » enregistré
    return {"items": items, "total": len(items), "aujourd_hui": svc.aujourd_hui().isoformat()}


@router.post("/avis", summary="Préparer un avis de renouvellement (brouillon + PDF officiel TAL-806)", status_code=201)
async def creer_avis(payload: AvisIn, db: DBSession, user: RequireManager) -> Dict[str, Any]:
    try:
        a = await svc.creer_avis(db, user=user, champs=payload.model_dump(exclude_unset=True, mode="json"))
    except svc.AdminLocatifError as exc:
        raise _erreur(exc) from exc
    await log_action(db, user=user, action="admin_locatif.avis_cree", entity_type="adm_loc_avis", entity_id=a.id,
                     details={"adresse": svc.adresse_avis(a), "document_id": a.document_id})
    await db.commit()
    await db.refresh(a)
    return await _avis_out(db, a)


@router.get("/avis/{avis_id}", summary="Détail d'un avis")
async def lire_avis(avis_id: int, db: DBSession, user: RequireManager) -> Dict[str, Any]:
    a = await _avis_or_404(db, avis_id)
    await svc.actualiser_delais(db, [a])
    await db.commit()
    await db.refresh(a)
    return await _avis_out(db, a)


@router.patch("/avis/{avis_id}", summary="Modifier un avis (brouillon seulement)")
async def modifier_avis(avis_id: int, payload: AvisIn, db: DBSession, user: RequireManager) -> Dict[str, Any]:
    a = await _avis_or_404(db, avis_id)
    try:
        await svc.modifier_avis(db, a, user=user, champs=payload.model_dump(exclude_unset=True, mode="json"))
    except svc.AdminLocatifError as exc:
        raise _erreur(exc) from exc
    await db.commit()
    await db.refresh(a)
    return await _avis_out(db, a)


@router.post("/avis/{avis_id}/envoyer", summary="Envoyer l'avis au locataire (réponse en ligne) — daté du jour")
async def envoyer_avis(avis_id: int, payload: Optional[EnvoyerAvisIn], db: DBSession, user: RequireManager) -> Dict[str, Any]:
    """Geste MANUEL, destinataire explicite : rien ne part tout seul."""
    a = await _avis_or_404(db, avis_id)
    try:
        res = await svc.envoyer_avis(db, a, user=user, courriel=(payload.courriel if payload else None))
    except svc.AdminLocatifError as exc:
        raise _erreur(exc) from exc
    await db.refresh(a)
    out = await _avis_out(db, a)
    out["envoi"] = res
    return out


@router.post("/avis/{avis_id}/annuler", summary="Annuler un avis (le lien envoyé cesse de fonctionner)")
async def annuler_avis(avis_id: int, db: DBSession, user: RequireManager) -> Dict[str, Any]:
    a = await _avis_or_404(db, avis_id)
    try:
        await svc.annuler_avis(db, a, user=user)
    except svc.AdminLocatifError as exc:
        raise _erreur(exc) from exc
    await db.commit()
    await db.refresh(a)
    return await _avis_out(db, a)


# ─── Registre des baux officiels et coût du TAL ───────────────────────


@router.get("/registre", summary="Baux officiels générés (qui, immeuble, quand) et coût mensuel attendu du TAL")
async def lire_registre(
    db: DBSession, user: RequireManager,
    annee: Optional[int] = Query(default=None, ge=2024, le=2100),
) -> Dict[str, Any]:
    return await tal.registre(db, annee)


__all__: List[str] = ["router"]
