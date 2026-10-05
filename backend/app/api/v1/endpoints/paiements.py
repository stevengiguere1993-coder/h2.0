"""Paiements fournisseurs par dépôt direct Desjardins ou virement Interac
(Comptabilité → Paiements).

    GET  /api/v1/paiements/moi                              droits + double authentification
    POST /api/v1/paiements/2fa/debut                        clé à scanner (mot de passe redemandé)
    POST /api/v1/paiements/2fa/activer                      active avec un premier code
    POST /api/v1/paiements/2fa/desactiver                   mot de passe + code
    GET  /api/v1/paiements/entreprises                      entreprises, QuickBooks, en attente
    GET  /api/v1/paiements/entreprises/{id}/factures        factures ouvertes dans QuickBooks
    GET  /api/v1/paiements/entreprises/{id}/fournisseurs    fournisseurs QuickBooks
    GET  /api/v1/paiements/entreprises/{id}/comptes         coordonnées de paiement (comptes masqués)
    POST /api/v1/paiements/entreprises/{id}/comptes         compte bancaire ou destinataire Interac (en attente)
    POST /api/v1/paiements/comptes/{id}/approuver           approbateur + double authentification
    POST /api/v1/paiements/comptes/{id}/refuser             approbateur
    POST /api/v1/paiements/comptes/{id}/retirer
    GET  /api/v1/paiements/entreprises/{id}/reglages        réglages des paiements (dépôt direct, approbations)
    PUT  /api/v1/paiements/entreprises/{id}/reglages        approbateur + double authentification
    GET  /api/v1/paiements/entreprises/{id}/lots
    POST /api/v1/paiements/entreprises/{id}/lots            nouveau lot (brouillon)
    GET  /api/v1/paiements/lots/{id}
    PUT  /api/v1/paiements/lots/{id}                        modifier un brouillon
    POST /api/v1/paiements/lots/{id}/soumettre
    POST /api/v1/paiements/lots/{id}/brouillon              remettre en brouillon
    POST /api/v1/paiements/lots/{id}/approuver              approbateur + double authentification
    POST /api/v1/paiements/lots/{id}/refuser                approbateur
    POST /api/v1/paiements/lots/{id}/fichier                approbateur + double authentification
    POST /api/v1/paiements/lots/{id}/transmis               approbateur
    POST /api/v1/paiements/lots/{id}/envoi                  Interac : approbateur + double authentification
    POST /api/v1/paiements/lots/{id}/virements/{fid}/envoye Interac : virement envoyé dans AccèsD (approbateur)
    POST /api/v1/paiements/lots/{id}/virements/{fid}/retirer Interac : retire un virement pas envoyé (approbateur)
    POST /api/v1/paiements/lots/{id}/quickbooks             inscrit les paiements dans QuickBooks
    POST /api/v1/paiements/lots/{id}/annuler
    GET  /api/v1/paiements/entreprises/{id}/journal         journal des paiements

Toutes les routes exigent la page « Comptabilité » du pôle Entreprises
(``page:entreprises.comptabilite``) ; les gestes qui engagent de l'argent
exigent en plus la capacité ``paiements.approuver`` et la double
authentification. Le connecteur IA n'a pas accès à ces routes
(``_ACTION_CHEMINS_INTERDITS`` de ``mcp_server``).
"""

from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional, Type, TypeVar

from fastapi import APIRouter, Body, Depends, HTTPException, Path, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, ValidationError

from app.api.deps import CurrentUser, DBSession
from app.models.user import User
from app.services import paiements_fournisseurs as svc
from app.services.permissions_service import require_capability

router = APIRouter(
    prefix="/paiements",
    tags=["paiements"],
    dependencies=[Depends(require_capability("page:entreprises.comptabilite"))],
)

#: Gestes réservés aux approbateurs (rôle ≥ seuil de la capacité, ou
#: exception individuelle). La double authentification est vérifiée par
#: le service.
Approbateur = Depends(require_capability(svc.CAPACITE_APPROUVER))

M = TypeVar("M", bound=BaseModel)


def _erreur(exc: svc.PaiementErreur) -> JSONResponse:
    return JSONResponse(status_code=exc.statut, content={"detail": exc.message, **exc.extra})


def _valider(modele: Type[M], corps: Any) -> M:
    """Valide le corps avec un message français (nos règles telles quelles,
    sinon le champ en cause)."""
    try:
        return modele.model_validate(corps or {})
    except ValidationError as exc:
        e = (exc.errors() or [{}])[0]
        if e.get("type") == "value_error":
            message = str(e.get("msg") or "").removeprefix("Value error, ")
        else:
            champ = ".".join(str(x) for x in e.get("loc") or ()) or "données"
            message = f"Champ « {champ} » invalide."
        raise HTTPException(422, message or "Données invalides.") from exc


class MotDePasseIn(BaseModel):
    mot_de_passe: str = Field(default="", max_length=256)


class CodeIn(BaseModel):
    code_2fa: str = Field(default="", max_length=12)


class DesactiverIn(BaseModel):
    mot_de_passe: str = Field(default="", max_length=256)
    code_2fa: str = Field(default="", max_length=12)


class ConfirmationIn(BaseModel):
    code_2fa: Optional[str] = Field(default=None, max_length=12)
    commentaire: Optional[str] = Field(default=None, max_length=2000)


class MotifIn(BaseModel):
    motif: Optional[str] = Field(default=None, max_length=2000)


class FichierIn(BaseModel):
    code_2fa: Optional[str] = Field(default=None, max_length=12)
    date_paiement: Optional[date] = None


class EnvoyeIn(BaseModel):
    #: Numéro de référence affiché par AccèsD (facultatif).
    reference: Optional[str] = Field(default=None, max_length=64)


# ── Moi et double authentification ───────────────────────────────────


@router.get("/moi", summary="Droits de paiement et double authentification du compte courant")
async def moi(db: DBSession, user: CurrentUser) -> Dict[str, Any]:
    return await svc.moi(db, user)


@router.post("/2fa/debut", summary="Nouvelle clé de double authentification à scanner")
async def debut_2fa(db: DBSession, user: CurrentUser, corps: Dict[str, Any] = Body(default={})) -> Any:
    donnees = _valider(MotDePasseIn, corps)
    try:
        return await svc.debut_2fa(db, user, donnees.mot_de_passe)
    except svc.PaiementErreur as exc:
        return _erreur(exc)


@router.post("/2fa/activer", summary="Active la double authentification avec un premier code")
async def activer_2fa(db: DBSession, user: CurrentUser, corps: Dict[str, Any] = Body(default={})) -> Any:
    donnees = _valider(CodeIn, corps)
    try:
        return await svc.activer_2fa(db, user, donnees.code_2fa)
    except svc.PaiementErreur as exc:
        return _erreur(exc)


@router.post("/2fa/desactiver", summary="Désactive la double authentification")
async def desactiver_2fa(db: DBSession, user: CurrentUser, corps: Dict[str, Any] = Body(default={})) -> Any:
    donnees = _valider(DesactiverIn, corps)
    try:
        return await svc.desactiver_2fa(db, user, donnees.mot_de_passe, donnees.code_2fa)
    except svc.PaiementErreur as exc:
        return _erreur(exc)


# ── Entreprises, factures, fournisseurs ──────────────────────────────


@router.get("/entreprises", summary="Entreprises : QuickBooks, dépôt direct prêt, en attente")
async def entreprises(db: DBSession, _: CurrentUser) -> List[Dict[str, Any]]:
    return await svc.entreprises(db)


@router.get("/entreprises/{entreprise_id}/factures", summary="Factures fournisseurs à payer (QuickBooks)")
async def factures(entreprise_id: int, db: DBSession, _: CurrentUser) -> Any:
    try:
        return await svc.factures_a_payer(db, entreprise_id)
    except svc.PaiementErreur as exc:
        return _erreur(exc)


@router.get("/entreprises/{entreprise_id}/fournisseurs", summary="Fournisseurs actifs (QuickBooks)")
async def fournisseurs(entreprise_id: int, db: DBSession, _: CurrentUser) -> Any:
    try:
        return await svc.fournisseurs(db, entreprise_id)
    except svc.PaiementErreur as exc:
        return _erreur(exc)


# ── Coordonnées bancaires des fournisseurs ───────────────────────────


@router.get("/entreprises/{entreprise_id}/comptes", summary="Coordonnées bancaires des fournisseurs (masquées)")
async def comptes(entreprise_id: int, db: DBSession, _: CurrentUser) -> Any:
    try:
        return await svc.comptes(db, entreprise_id)
    except svc.PaiementErreur as exc:
        return _erreur(exc)


@router.post("/entreprises/{entreprise_id}/comptes", summary="Saisit des coordonnées bancaires (à approuver)")
async def proposer_compte(
    entreprise_id: int, db: DBSession, user: CurrentUser, corps: Dict[str, Any] = Body(...)
) -> Any:
    donnees = _valider(svc.CompteIn, corps)
    try:
        return await svc.proposer_compte(db, entreprise_id, user, donnees)
    except svc.PaiementErreur as exc:
        return _erreur(exc)


@router.post("/comptes/{compte_id}/approuver", summary="Approuve des coordonnées bancaires")
async def approuver_compte(
    compte_id: int, db: DBSession, user: User = Approbateur, corps: Dict[str, Any] = Body(default={})
) -> Any:
    donnees = _valider(ConfirmationIn, corps)
    try:
        return await svc.approuver_compte(db, compte_id, user, donnees.code_2fa)
    except svc.PaiementErreur as exc:
        return _erreur(exc)


@router.post("/comptes/{compte_id}/refuser", summary="Refuse des coordonnées bancaires")
async def refuser_compte(
    compte_id: int, db: DBSession, user: User = Approbateur, corps: Dict[str, Any] = Body(default={})
) -> Any:
    donnees = _valider(MotifIn, corps)
    try:
        return await svc.refuser_compte(db, compte_id, user, donnees.motif or "")
    except svc.PaiementErreur as exc:
        return _erreur(exc)


@router.post("/comptes/{compte_id}/retirer", summary="Retire des coordonnées bancaires")
async def retirer_compte(compte_id: int, db: DBSession, user: CurrentUser) -> Any:
    try:
        return await svc.retirer_compte(db, compte_id, user)
    except svc.PaiementErreur as exc:
        return _erreur(exc)


@router.post("/comptes/{compte_id}/reveler", summary="Numéro de compte complet (approbateur, double authentification)")
async def reveler_compte(
    compte_id: int, db: DBSession, user: User = Approbateur, corps: Dict[str, Any] = Body(default={})
) -> Any:
    donnees = _valider(ConfirmationIn, corps)
    try:
        return await svc.reveler_compte(db, compte_id, user, donnees.code_2fa)
    except svc.PaiementErreur as exc:
        return _erreur(exc)


# ── Réglages des paiements ────────────────────────────────────────────


@router.get("/entreprises/{entreprise_id}/reglages", summary="Réglages des paiements de l'entreprise (dépôt direct, approbations)")
async def reglages(entreprise_id: int, db: DBSession, _: CurrentUser) -> Any:
    try:
        return await svc.reglages(db, entreprise_id)
    except svc.PaiementErreur as exc:
        return _erreur(exc)


@router.put("/entreprises/{entreprise_id}/reglages", summary="Modifie les réglages des paiements")
async def modifier_reglages(
    entreprise_id: int, db: DBSession, user: User = Approbateur, corps: Dict[str, Any] = Body(...)
) -> Any:
    donnees = _valider(svc.ReglagesIn, corps)
    try:
        return await svc.modifier_reglages(db, entreprise_id, user, donnees)
    except svc.PaiementErreur as exc:
        return _erreur(exc)


# ── Lots ──────────────────────────────────────────────────────────────


@router.get("/entreprises/{entreprise_id}/lots", summary="Lots de paiement de l'entreprise")
async def lots(
    entreprise_id: int,
    db: DBSession,
    _: CurrentUser,
    statut: Optional[str] = Query(default=None, max_length=16),
    limit: int = Query(default=50, ge=1, le=200),
) -> Any:
    try:
        return await svc.lots(db, entreprise_id, statut=statut, limit=limit)
    except svc.PaiementErreur as exc:
        return _erreur(exc)


@router.post("/entreprises/{entreprise_id}/lots", summary="Nouveau lot de paiement (brouillon)")
async def creer_lot(
    entreprise_id: int, db: DBSession, user: CurrentUser, corps: Dict[str, Any] = Body(...)
) -> Any:
    donnees = _valider(svc.LotIn, corps)
    try:
        return await svc.creer_lot(db, entreprise_id, user, donnees)
    except svc.PaiementErreur as exc:
        return _erreur(exc)


@router.get("/lots/{lot_id}", summary="Détail d'un lot de paiement")
async def detail_lot(lot_id: int, db: DBSession, user: CurrentUser) -> Any:
    try:
        return await svc.detail_lot(db, lot_id, user)
    except svc.PaiementErreur as exc:
        return _erreur(exc)


@router.put("/lots/{lot_id}", summary="Modifie un lot en brouillon")
async def modifier_lot(lot_id: int, db: DBSession, user: CurrentUser, corps: Dict[str, Any] = Body(...)) -> Any:
    donnees = _valider(svc.LotIn, corps)
    try:
        return await svc.modifier_lot(db, lot_id, user, donnees)
    except svc.PaiementErreur as exc:
        return _erreur(exc)


@router.post("/lots/{lot_id}/soumettre", summary="Soumet un lot aux approbateurs")
async def soumettre(lot_id: int, db: DBSession, user: CurrentUser) -> Any:
    try:
        return await svc.soumettre(db, lot_id, user)
    except svc.PaiementErreur as exc:
        return _erreur(exc)


@router.post("/lots/{lot_id}/brouillon", summary="Remet un lot en brouillon (efface les approbations)")
async def remettre_en_brouillon(lot_id: int, db: DBSession, user: CurrentUser) -> Any:
    try:
        return await svc.remettre_en_brouillon(db, lot_id, user)
    except svc.PaiementErreur as exc:
        return _erreur(exc)


@router.post("/lots/{lot_id}/approuver", summary="Approuve un lot de paiement")
async def approuver(
    lot_id: int, db: DBSession, user: User = Approbateur, corps: Dict[str, Any] = Body(default={})
) -> Any:
    donnees = _valider(ConfirmationIn, corps)
    try:
        return await svc.approuver(db, lot_id, user, donnees.code_2fa, donnees.commentaire)
    except svc.PaiementErreur as exc:
        return _erreur(exc)


@router.post("/lots/{lot_id}/refuser", summary="Refuse un lot de paiement")
async def refuser(
    lot_id: int, db: DBSession, user: User = Approbateur, corps: Dict[str, Any] = Body(default={})
) -> Any:
    donnees = _valider(ConfirmationIn, corps)
    try:
        return await svc.refuser(db, lot_id, user, donnees.commentaire or "")
    except svc.PaiementErreur as exc:
        return _erreur(exc)


@router.post("/lots/{lot_id}/fichier", summary="Crée (ou redonne) le fichier de dépôt direct du lot")
async def fichier(
    lot_id: int, db: DBSession, user: User = Approbateur, corps: Dict[str, Any] = Body(default={})
) -> Any:
    donnees = _valider(FichierIn, corps)
    try:
        return await svc.creer_fichier(db, lot_id, user, donnees.code_2fa, donnees.date_paiement)
    except svc.PaiementErreur as exc:
        return _erreur(exc)


@router.post("/lots/{lot_id}/transmis", summary="Indique que le fichier a été transmis dans AccèsD")
async def transmis(lot_id: int, db: DBSession, user: User = Approbateur) -> Any:
    try:
        return await svc.marquer_transmis(db, lot_id, user)
    except svc.PaiementErreur as exc:
        return _erreur(exc)


@router.post("/lots/{lot_id}/envoi", summary="Prépare l'envoi des virements Interac d'un lot approuvé")
async def preparer_envoi(
    lot_id: int, db: DBSession, user: User = Approbateur, corps: Dict[str, Any] = Body(default={})
) -> Any:
    donnees = _valider(ConfirmationIn, corps)
    try:
        return await svc.preparer_envoi(db, lot_id, user, donnees.code_2fa)
    except svc.PaiementErreur as exc:
        return _erreur(exc)


@router.post(
    "/lots/{lot_id}/virements/{fournisseur_id}/envoye",
    summary="Indique que le virement Interac d'un fournisseur a été envoyé dans AccèsD",
)
async def virement_envoye(
    lot_id: int,
    db: DBSession,
    fournisseur_id: str = Path(max_length=64),
    user: User = Approbateur,
    corps: Dict[str, Any] = Body(default={}),
) -> Any:
    donnees = _valider(EnvoyeIn, corps)
    try:
        return await svc.marquer_envoye(db, lot_id, user, fournisseur_id, donnees.reference)
    except svc.PaiementErreur as exc:
        return _erreur(exc)


@router.post(
    "/lots/{lot_id}/virements/{fournisseur_id}/retirer",
    summary="Retire du lot un virement Interac pas encore envoyé",
)
async def retirer_virement(
    lot_id: int,
    db: DBSession,
    fournisseur_id: str = Path(max_length=64),
    user: User = Approbateur,
    corps: Dict[str, Any] = Body(default={}),
) -> Any:
    donnees = _valider(MotifIn, corps)
    try:
        return await svc.retirer_virement(db, lot_id, user, fournisseur_id, donnees.motif or "")
    except svc.PaiementErreur as exc:
        return _erreur(exc)


@router.post("/lots/{lot_id}/quickbooks", summary="Inscrit les paiements du lot dans QuickBooks")
async def quickbooks(lot_id: int, db: DBSession, user: CurrentUser) -> Any:
    try:
        return await svc.enregistrer_qbo(db, lot_id, user)
    except svc.PaiementErreur as exc:
        return _erreur(exc)


@router.post("/lots/{lot_id}/annuler", summary="Annule un lot de paiement")
async def annuler(lot_id: int, db: DBSession, user: CurrentUser, corps: Dict[str, Any] = Body(default={})) -> Any:
    donnees = _valider(MotifIn, corps)
    try:
        return await svc.annuler(db, lot_id, user, donnees.motif)
    except svc.PaiementErreur as exc:
        return _erreur(exc)


@router.get("/entreprises/{entreprise_id}/journal", summary="Journal des paiements de l'entreprise")
async def journal(
    entreprise_id: int, db: DBSession, _: CurrentUser, limit: int = Query(default=100, ge=1, le=500)
) -> Any:
    try:
        return await svc.journal(db, entreprise_id, limit=limit)
    except svc.PaiementErreur as exc:
        return _erreur(exc)
