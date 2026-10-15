"""Bail de logement OFFICIEL (TAL, formulaire 53000BAIL) — routes.

Préfixe ``/immobilier/tal-bail`` (volet Immobilier, gestionnaires) :

- GET  /etat                       → connexion (sans la clé), schéma actif, compteur du mois, réglages
- GET  /schema                     → schéma actif : champs (types, clés permises, libellés) + gabarit vide
- GET  /schema/versions            → versions téléversées
- POST /schema                     → téléverser un nouveau schéma JSON du TAL (+ diff vs actif), admin
- POST /schema/{id}/activer        → activer une version, admin
- GET  /parametres · PUT /parametres (admin : tarif, défauts, connexion, clé API en écriture seule)
- GET  /preparer?bail_id=          → formulaire pré-rempli + origine + à vérifier + rapport (rien d'écrit)
- POST /transmissions              → brouillon pour un bail (formulaire préparé, surcharges, remplacement)
- GET  /transmissions              → liste (bail_id, dossier_id, statut)
- GET  /transmissions/{id}         → détail avec le formulaire
- PATCH /transmissions/{id}        → remplacer le formulaire (brouillon seulement)
- POST /transmissions/{id}/valider → rapport de validation locale
- POST /transmissions/{id}/generer → {confirme: true} : FRW111 + FRW122, PDF archivé, frais
- POST /transmissions/{id}/relancer→ FRW122 à nouveau avec le même ShortGuid (après échec)
- POST /transmissions/{id}/annuler
- GET  /compteur?mois=AAAA-MM

Règles du contrat (jamais contournées ici) : un appel = un besoin réel de
signature ; pas de génération d'avance ni en lot ; PDF archivé tel quel ;
la clé API ne sort jamais du serveur.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import DBSession, RequireAdminOrOwner, RequireManager
from app.integrations.tal.client import TalApiError
from app.integrations.tal.schema import (
    TYPE_FORMULAIRE,
    charger_schema,
    charger_schema_asset,
    comparer_schemas,
    construire_schema,
    squelette,
)
from app.models.tal_bail import TRANSMISSION_STATUTS, TalSchema, TalTransmission
from app.services import tal_bail as svc
from app.services.audit import log_action
from app.services.automation_state import get_automation_config, set_automation_config

log = logging.getLogger(__name__)

router = APIRouter(prefix="/immobilier/tal-bail", tags=["immobilier-tal-bail"])


# ─── Schemas (API) ─────────────────────────────────────────────────────


class ParametresIn(BaseModel):
    tarif_recharge: Optional[float] = Field(default=None, ge=0, le=10_000)
    frais_auto: Optional[bool] = None
    libelle_frais: Optional[str] = Field(default=None, max_length=255)
    mode_paiement_defaut: Optional[str] = Field(default=None, max_length=40)
    chauffage_defaut: Optional[str] = Field(default=None, max_length=40)
    logement_sans_fumee: Optional[bool] = None
    animaux_defaut: Optional[bool] = None
    province_defaut: Optional[str] = Field(default=None, max_length=40)
    representant_nom: Optional[str] = Field(default=None, max_length=255)
    representant_courriel: Optional[str] = Field(default=None, max_length=320)
    requis: Optional[str] = Field(default=None, max_length=2000)
    # Connexion (table tal_connexion). ``api_key`` : écriture seule —
    # chiffrée aussitôt, jamais renvoyée (le journal d'audit la masque).
    mode: Optional[str] = Field(default=None, max_length=16)
    api_url: Optional[str] = Field(default=None, max_length=500)
    entete_cle: Optional[str] = Field(default=None, max_length=64)
    chemin_frw111: Optional[str] = Field(default=None, max_length=255)
    chemin_frw122: Optional[str] = Field(default=None, max_length=255)
    api_key: Optional[str] = Field(default=None, max_length=4000)
    effacer_cle: Optional[bool] = None


class SchemaUploadIn(BaseModel):
    #: Le JSON du TAL tel quel (clé « schema » dans la requête).
    donnees: Dict[str, Any] = Field(..., alias="schema")
    version: Optional[str] = Field(default=None, max_length=64)
    source: Optional[str] = Field(default=None, max_length=255)
    notes: Optional[str] = None
    activer: bool = False

    model_config = {"populate_by_name": True}


class TransmissionCreateIn(BaseModel):
    bail_id: int
    dossier_id: Optional[int] = None
    #: Surcharges « chemin → valeur » sur le formulaire préparé.
    surcharges: Optional[Dict[str, Any]] = None
    #: Formulaire complet fourni par l'écran (remplace la préparation).
    form: Optional[Dict[str, Any]] = None
    #: Accepter un NOUVEAU formulaire (facturé) pour un bail déjà transmis.
    remplacer: bool = False


class FormIn(BaseModel):
    form: Dict[str, Any]


class GenererIn(BaseModel):
    #: L'utilisateur a vu « 2,99 $, besoin réel de signature » et confirme.
    confirme: bool = False


# ─── Helpers ──────────────────────────────────────────────────────────


def _erreur(exc: svc.TalBailError) -> HTTPException:
    detail: Any = exc.message
    if exc.details is not None:
        detail = {"message": exc.message, "details": exc.details}
    return HTTPException(status_code=exc.http_status, detail=detail)


def _erreur_tal(exc: TalApiError) -> HTTPException:
    return HTTPException(
        status_code=502,
        detail={"message": f"TAL — {exc.etape} : {exc.message}", "etape": exc.etape, "http_status": exc.http_status},
    )


async def _transmission_or_404(db, transmission_id: int) -> TalTransmission:
    t = await db.get(TalTransmission, transmission_id)
    if t is None:
        raise HTTPException(status_code=404, detail="Transmission introuvable.")
    return t


def _champs_schema(schema) -> List[Dict[str, Any]]:
    return [
        {
            "nom": c.nom,
            "groupe": c.groupe,
            "type": c.type,
            "repetable": bool(c.repetable),
            "max_occurrences": c.max_occurrences,
            "nom_domaine": c.nom_domaine,
            "valeurs_possibles": (
                [{"cle": k, "fr": (v.get("fr") if isinstance(v, dict) else str(v)), "en": (v.get("en") if isinstance(v, dict) else None)}
                 for k, v in (c.valeurs_possibles or {}).items()]
                if c.valeurs_possibles else None
            ),
            "label_fr": c.label_fr,
            "label_en": c.label_en,
            "est_booleen": c.est_booleen,
        }
        for c in schema.champs
    ]


async def _parametres_out(db) -> Dict[str, Any]:
    config = await svc.charger_config()
    cx, infos = await svc.charger_connexion(db)
    etat = cx.etat()
    etat.update({
        "cle_posee_le": infos.get("cle_posee_le").isoformat() if infos.get("cle_posee_le") else None,
        "cle_posee_par": infos.get("cle_posee_par"),
        "source_cle": infos.get("source_cle"),
        "coffre_disponible": infos.get("coffre_disponible"),
        "cle_dechiffrable": infos.get("cle_dechiffrable"),
    })
    schema = await charger_schema(db)
    return {
        "config": config,
        "defauts": dict(svc.DEFAUTS),
        "connexion": etat,
        "schema": schema.resume(),
        "cout_tal": svc.COUT_TAL,
        "gratuits_total": svc.GRATUITS_TOTAL,
    }


# ─── État / schéma ─────────────────────────────────────────────────────


@router.get("/etat", summary="État du module (connexion sans la clé, schéma, compteur)")
async def etat(db: DBSession, user: RequireManager, mois: Optional[str] = None) -> Dict[str, Any]:
    out = await _parametres_out(db)
    try:
        out["compteur"] = await svc.compteur(db, mois, config=out["config"])
    except svc.TalBailError as exc:
        raise _erreur(exc) from exc
    return out


@router.get("/schema", summary="Schéma actif : champs, clés permises, gabarit vide")
async def lire_schema(db: DBSession, user: RequireManager) -> Dict[str, Any]:
    schema = await charger_schema(db)
    return {"resume": schema.resume(), "champs": _champs_schema(schema), "gabarit": squelette(schema)}


@router.get("/schema/versions", summary="Versions de schéma téléversées")
async def versions_schema(db: DBSession, user: RequireManager) -> List[Dict[str, Any]]:
    rows = (await db.execute(select(TalSchema).order_by(TalSchema.id.desc()))).scalars().all()
    embarque = charger_schema_asset()
    out = [{
        "id": 0, "version": embarque.version, "source": embarque.source, "nb_champs": len(embarque.champs),
        "actif": not any(r.actif for r in rows), "embarque": True, "created_at": None, "uploaded_by_email": None, "notes": None,
    }]
    out += [{
        "id": r.id, "version": r.version, "source": r.source, "nb_champs": r.nb_champs, "actif": bool(r.actif),
        "embarque": False, "created_at": r.created_at.isoformat() if r.created_at else None,
        "uploaded_by_email": r.uploaded_by_email, "notes": r.notes,
    } for r in rows]
    return out


@router.post("/schema", summary="Téléverser un nouveau schéma TAL (diff vs actif)", status_code=201)
async def televerser_schema(payload: SchemaUploadIn, db: DBSession, user: RequireAdminOrOwner) -> Dict[str, Any]:
    version = (payload.version or "").strip() or f"televerse-{__import__('datetime').date.today().isoformat()}"
    try:
        nouveau = construire_schema(payload.donnees, version=version, source=payload.source or "televersement")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"Schéma refusé : {exc}") from exc
    actif = await charger_schema(db)
    diff = comparer_schemas(actif, nouveau)
    row = TalSchema(
        type_formulaire=TYPE_FORMULAIRE, version=version, source=payload.source,
        json_text=json.dumps(payload.donnees, ensure_ascii=False), nb_champs=len(nouveau.champs),
        actif=False, notes=payload.notes, uploaded_by_email=user.email,
    )
    db.add(row)
    await db.flush()
    if payload.activer:
        for autre in (await db.execute(select(TalSchema).where(TalSchema.actif.is_(True)))).scalars().all():
            autre.actif = False
        row.actif = True
    await log_action(db, user=user, action="tal_bail.schema_televerse", entity_type="tal_schema", entity_id=row.id,
                     details={"version": version, "nb_champs": len(nouveau.champs), "active": payload.activer,
                              "ajoutes": len(diff["champs_ajoutes"]), "retires": len(diff["champs_retires"]), "modifies": len(diff["champs_modifies"])})
    await db.commit()
    return {"id": row.id, "version": version, "actif": bool(row.actif), "resume": nouveau.resume(), "diff": diff}


@router.post("/schema/{schema_id}/activer", summary="Activer une version de schéma (0 = fichier embarqué)")
async def activer_schema(schema_id: int, db: DBSession, user: RequireAdminOrOwner) -> Dict[str, Any]:
    rows = (await db.execute(select(TalSchema))).scalars().all()
    cible = None
    if schema_id != 0:
        cible = next((r for r in rows if r.id == schema_id), None)
        if cible is None:
            raise HTTPException(status_code=404, detail="Version introuvable.")
    for r in rows:
        r.actif = (cible is not None and r.id == cible.id)
    await log_action(db, user=user, action="tal_bail.schema_active", entity_type="tal_schema", entity_id=schema_id or None,
                     details={"version": cible.version if cible else "embarque"})
    await db.commit()
    schema = await charger_schema(db)
    return {"actif": schema.resume()}


# ─── Paramètres ────────────────────────────────────────────────────────


@router.get("/parametres", summary="Réglages (tarif, défauts, connexion sans la clé)")
async def lire_parametres(db: DBSession, user: RequireManager) -> Dict[str, Any]:
    return await _parametres_out(db)


@router.put("/parametres", summary="Enregistrer les réglages (admin)")
async def ecrire_parametres(payload: ParametresIn, db: DBSession, user: RequireAdminOrOwner) -> Dict[str, Any]:
    data = payload.model_dump(exclude_unset=True)
    cles_connexion = {"mode", "api_url", "entete_cle", "chemin_frw111", "chemin_frw122", "api_key", "effacer_cle"}
    connexion = {k: data.pop(k) for k in list(data.keys()) if k in cles_connexion}
    if data:
        actuel = dict(await get_automation_config(svc.CONFIG_KEY) or {})
        for k, v in data.items():
            if v is None:
                actuel.pop(k, None)
            else:
                actuel[k] = v
        await set_automation_config(db, svc.CONFIG_KEY, actuel, user_id=user.id)
    if connexion:
        try:
            await svc.enregistrer_connexion(
                db,
                mode=connexion.get("mode"), api_url=connexion.get("api_url"), entete_cle=connexion.get("entete_cle"),
                chemin_frw111=connexion.get("chemin_frw111"), chemin_frw122=connexion.get("chemin_frw122"),
                api_key=connexion.get("api_key"), effacer_cle=bool(connexion.get("effacer_cle")), user_email=user.email,
            )
        except svc.TalBailError as exc:
            raise _erreur(exc) from exc
    # Audit : jamais la clé — seulement « posée / effacée ».
    await log_action(
        db, user=user, action="tal_bail.parametres", entity_type="automation_setting", entity_id=None,
        details={**{k: v for k, v in data.items()},
                 **{k: v for k, v in connexion.items() if k != "api_key"},
                 "cle_posee": bool(connexion.get("api_key"))},
    )
    await db.commit()
    return await _parametres_out(db)


# ─── Préparation ──────────────────────────────────────────────────────


@router.get("/preparer", summary="Formulaire pré-rempli pour un bail (rien n'est écrit)")
async def preparer(db: DBSession, user: RequireManager, bail_id: int = Query(...)) -> Dict[str, Any]:
    try:
        prep, rapport, ctx, schema, _config = await svc.preparer(db, bail_id, user=user)
    except svc.TalBailError as exc:
        raise _erreur(exc) from exc
    cx, _infos = await svc.charger_connexion(db)
    existantes = (
        await db.execute(select(TalTransmission).where(TalTransmission.bail_id == bail_id).order_by(TalTransmission.id.desc()))
    ).scalars().all()
    return {
        **prep.as_dict(),
        "rapport": rapport.as_dict(),
        "contexte": ctx.resume(),
        "schema_version": schema.version,
        "mode": cx.etat()["mode"],
        "cout_tal": svc.COUT_TAL,
        "transmissions": [svc.resume_transmission(t) for t in existantes],
    }


# ─── Transmissions ────────────────────────────────────────────────────


@router.post("/transmissions", summary="Créer un brouillon de transmission pour un bail", status_code=201)
async def creer_transmission(payload: TransmissionCreateIn, db: DBSession, user: RequireManager) -> Dict[str, Any]:
    try:
        t, rapport = await svc.creer_transmission(
            db, bail_id=payload.bail_id, user=user, dossier_id=payload.dossier_id,
            surcharges=payload.surcharges, form=payload.form, remplacer=payload.remplacer,
        )
    except svc.TalBailError as exc:
        raise _erreur(exc) from exc
    await log_action(db, user=user, action="tal_bail.brouillon", entity_type="tal_transmission", entity_id=t.id,
                     details={"bail_id": t.bail_id, "dossier_id": t.dossier_id, "valide": rapport.valide, "erreurs": len(rapport.erreurs)})
    await db.commit()
    await db.refresh(t)
    return svc.resume_transmission(t, avec_form=True)


@router.get("/transmissions", summary="Lister les transmissions")
async def lister_transmissions(
    db: DBSession, user: RequireManager,
    bail_id: Optional[int] = None, dossier_id: Optional[int] = None, statut: Optional[str] = None,
    immeuble_id: Optional[int] = None, limit: int = Query(default=100, ge=1, le=500),
) -> Dict[str, Any]:
    q = select(TalTransmission).order_by(TalTransmission.id.desc()).limit(limit)
    if bail_id is not None:
        q = q.where(TalTransmission.bail_id == bail_id)
    if dossier_id is not None:
        q = q.where(TalTransmission.dossier_id == dossier_id)
    if immeuble_id is not None:
        q = q.where(TalTransmission.immeuble_id == immeuble_id)
    if statut:
        if statut not in TRANSMISSION_STATUTS:
            raise HTTPException(status_code=422, detail=f"Statut inconnu ({', '.join(TRANSMISSION_STATUTS)}).")
        q = q.where(TalTransmission.statut == statut)
    rows = (await db.execute(q)).scalars().all()
    return {"items": [svc.resume_transmission(t) for t in rows], "total": len(rows)}


@router.get("/transmissions/{transmission_id}", summary="Détail d'une transmission (avec le formulaire)")
async def lire_transmission(transmission_id: int, db: DBSession, user: RequireManager) -> Dict[str, Any]:
    t = await _transmission_or_404(db, transmission_id)
    return svc.resume_transmission(t, avec_form=True)


@router.patch("/transmissions/{transmission_id}", summary="Remplacer le formulaire d'un brouillon")
async def modifier_transmission(transmission_id: int, payload: FormIn, db: DBSession, user: RequireManager) -> Dict[str, Any]:
    t = await _transmission_or_404(db, transmission_id)
    try:
        rapport = await svc.remplacer_formulaire(db, t, payload.form)
    except svc.TalBailError as exc:
        raise _erreur(exc) from exc
    await db.commit()
    await db.refresh(t)
    out = svc.resume_transmission(t, avec_form=True)
    out["rapport"] = rapport.as_dict()
    return out


@router.post("/transmissions/{transmission_id}/valider", summary="Validation locale stricte")
async def valider_transmission(transmission_id: int, db: DBSession, user: RequireManager) -> Dict[str, Any]:
    t = await _transmission_or_404(db, transmission_id)
    rapport = await svc.valider_transmission(db, t)
    await db.commit()
    return rapport.as_dict()


async def _generer(transmission_id: int, db, user, *, confirme: bool, relance: bool) -> Dict[str, Any]:
    if not confirme:
        raise HTTPException(
            status_code=422,
            detail="Confirmation requise : la génération appelle le TAL (2,99 $ par formulaire en mode réel) "
                   "et doit répondre à un besoin réel et immédiat de signature.",
        )
    # Verrou de ligne : deux clics simultanés deviennent séquentiels — le
    # second frappe « déjà transmise » au lieu de payer un 2e formulaire.
    t = (
        await db.execute(select(TalTransmission).where(TalTransmission.id == transmission_id).with_for_update())
    ).scalar_one_or_none()
    if t is None:
        raise HTTPException(status_code=404, detail="Transmission introuvable.")
    if relance and not t.short_guid and t.statut != "echec":
        raise HTTPException(status_code=409, detail="Rien à relancer : cette transmission n'a pas encore été envoyée.")
    try:
        t = await svc.generer(db, t, user=user)
    except svc.TalBailError as exc:
        raise _erreur(exc) from exc
    except TalApiError as exc:
        raise _erreur_tal(exc) from exc
    await db.refresh(t)
    return svc.resume_transmission(t)


@router.post("/transmissions/{transmission_id}/generer", summary="Générer le bail officiel (FRW111 + FRW122)")
async def generer_transmission(transmission_id: int, payload: GenererIn, db: DBSession, user: RequireManager) -> Dict[str, Any]:
    return await _generer(transmission_id, db, user, confirme=payload.confirme, relance=False)


@router.post("/transmissions/{transmission_id}/relancer", summary="Relancer FRW122 avec le même ShortGuid")
async def relancer_transmission(transmission_id: int, payload: GenererIn, db: DBSession, user: RequireManager) -> Dict[str, Any]:
    return await _generer(transmission_id, db, user, confirme=payload.confirme, relance=True)


@router.post("/transmissions/{transmission_id}/annuler", summary="Annuler un brouillon / un échec")
async def annuler_transmission(transmission_id: int, db: DBSession, user: RequireManager) -> Dict[str, Any]:
    t = await _transmission_or_404(db, transmission_id)
    try:
        await svc.annuler(db, t, user=user)
    except svc.TalBailError as exc:
        raise _erreur(exc) from exc
    await db.commit()
    await db.refresh(t)
    return svc.resume_transmission(t)


# ─── Signature interne (eSign) ────────────────────────────────────────


class SignatureIn(BaseModel):
    message: Optional[str] = Field(default=None, max_length=2000)


@router.post("/transmissions/{transmission_id}/signature", summary="Lancer la signature eSign sur le PDF officiel", status_code=201)
async def lancer_signature(transmission_id: int, payload: Optional[SignatureIn], db: DBSession, user: RequireManager) -> Dict[str, Any]:
    t = await _transmission_or_404(db, transmission_id)
    try:
        doc, cree, manquants = await svc.lancer_signature(db, t, user=user, message=(payload.message if payload else None))
    except svc.TalBailError as exc:
        raise _erreur(exc) from exc
    await db.commit()
    etat = await svc.etat_signature(db, doc.id)
    return {"esign_document_id": doc.id, "cree": cree, "url": f"/entreprises/signature/{doc.id}", "sans_courriel": manquants, "signature": etat}


@router.get("/transmissions/{transmission_id}/signature", summary="Suivi de la signature (qui, quand)")
async def lire_signature(transmission_id: int, db: DBSession, user: RequireManager) -> Dict[str, Any]:
    t = await _transmission_or_404(db, transmission_id)
    etat = await svc.etat_signature(db, t.esign_document_id)
    if etat is None:
        raise HTTPException(status_code=404, detail="Aucune signature lancée pour cette transmission.")
    return etat


# ─── Compteur ─────────────────────────────────────────────────────────


@router.get("/compteur", summary="Compteur mensuel (coût TAL estimé, frais refacturés, gratuits restants)")
async def lire_compteur(db: DBSession, user: RequireManager, mois: Optional[str] = None) -> Dict[str, Any]:
    try:
        return await svc.compteur(db, mois)
    except svc.TalBailError as exc:
        raise _erreur(exc) from exc
