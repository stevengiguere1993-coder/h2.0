"""Registre des courtiers — API (Prospection, Phil 2026-10-14).

Phil : « un registre des courtiers où je vais regarder sur Centris toutes
les 20 logements et plus à vendre, aller chercher le contact du courtier,
me construire une liste des courtiers qui vendent des gros parcs, et leur
envoyer un courriel personnalisé — une façon de se faire remarquer. »

Routes (préfixe /prospection/courtiers — enregistré AVANT
/prospection/{lead_id} dans router.py) :
- GET    ""                → liste filtrée + statistiques
- POST   ""                → fiche saisie à la main
- GET    /parametres       → réglages (seuil, gabarit, expéditeur…)
- PUT    /parametres       → enregistrer les réglages (admin / owner)
- POST   /scan             → construire / mettre à jour le registre
                             (tâche de fond : annonces connues, fiches
                             d'analyse, Centris via le VPS)
- GET    /scan/{job_id}    → état du scan
- POST   /apercu           → aperçu rendu du courriel (courtier ou exemple)
- POST   /envoyer          → courriel de présentation à N courtiers, ou
                             envoi de test à une adresse
- GET    /export.csv       → export CSV du registre
- GET    /{id}             → fiche + annonces + journal
- PATCH  /{id}             → modifier la fiche
- DELETE /{id}             → supprimer
- POST   /{id}/contacts    → ajouter une entrée au journal (appel, réponse…)

Rien ne part sans un clic humain : aucun cron n'appelle /envoyer.
"""

from __future__ import annotations

import asyncio
import csv
import io
import logging
import secrets
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import case, delete, func, select

from app.api.deps import DBSession, RequireAdminOrOwner, RequireManager
from app.models.prospection_courtier import (
    COURTIER_STATUTS,
    ProspectionCourtier,
    ProspectionCourtierAnnonce,
    ProspectionCourtierContact,
)
from app.services import prospection_courtiers as svc
from app.services.audit import log_action
from app.services.automation_state import get_automation_config, set_automation_config

log = logging.getLogger(__name__)

router = APIRouter(prefix="/prospection/courtiers", tags=["prospection-courtiers"])

CANAUX = ("courriel", "telephone", "rencontre", "autre")
DIRECTIONS = ("sortant", "entrant")
VARIABLES_GABARIT = [
    {"cle": "prenom", "aide": "Prénom du courtier"},
    {"cle": "nom", "aide": "Nom complet du courtier"},
    {"cle": "agence", "aide": "Agence / bannière"},
    {"cle": "adresse", "aide": "Adresse de sa plus grosse annonce active"},
    {"cle": "ville", "aide": "Ville de cette annonce"},
    {"cle": "nb_logements", "aide": "Nombre de logements de cette annonce"},
    {"cle": "prix", "aide": "Prix demandé de cette annonce"},
    {"cle": "seuil", "aide": "Seuil de logements du registre (Paramètres)"},
    {"cle": "signature", "aide": "Signature (Paramètres)"},
]
_MAX_ENVOIS_PAR_APPEL = 50


# ─── Schémas ─────────────────────────────────────────────────────────


class AnnonceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    centris_listing_id: Optional[int] = None
    lead_analysis_id: Optional[int] = None
    mls_id: Optional[str] = None
    source_url: str
    adresse: Optional[str] = None
    ville: Optional[str] = None
    nb_units: Optional[int] = None
    prix: Optional[float] = None
    vue_le: Optional[datetime] = None
    active: bool = True


class ContactOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    annonce_id: Optional[int] = None
    date: datetime
    canal: str
    direction: str
    sujet: Optional[str] = None
    contenu: Optional[str] = None
    auteur_email: Optional[str] = None


class CourtierOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    nom: str
    agence: Optional[str] = None
    courriel: Optional[str] = None
    telephone: Optional[str] = None
    cellulaire: Optional[str] = None
    site_web: Optional[str] = None
    secteur: Optional[str] = None
    langue: str = "fr"
    source: str
    statut: str
    notes: Optional[str] = None
    premier_vu_le: Optional[datetime] = None
    dernier_vu_le: Optional[datetime] = None
    dernier_contact_le: Optional[datetime] = None
    prochaine_relance_le: Optional[date] = None
    nb_relances: int = 0
    created_at: datetime
    updated_at: datetime
    # Agrégats calculés
    nb_annonces: int = 0
    nb_annonces_actives: int = 0
    max_logements: Optional[int] = None
    nb_contacts: int = 0


class CourtierDetail(CourtierOut):
    annonces: List[AnnonceOut] = []
    contacts: List[ContactOut] = []


class CourtierCreate(BaseModel):
    nom: str = Field(min_length=2, max_length=255)
    agence: Optional[str] = Field(default=None, max_length=255)
    courriel: Optional[str] = Field(default=None, max_length=320)
    telephone: Optional[str] = Field(default=None, max_length=50)
    cellulaire: Optional[str] = Field(default=None, max_length=50)
    site_web: Optional[str] = Field(default=None, max_length=500)
    secteur: Optional[str] = Field(default=None, max_length=255)
    langue: Optional[str] = Field(default=None, max_length=8)
    statut: Optional[str] = None
    notes: Optional[str] = None


class CourtierPatch(BaseModel):
    nom: Optional[str] = Field(default=None, min_length=2, max_length=255)
    agence: Optional[str] = Field(default=None, max_length=255)
    courriel: Optional[str] = Field(default=None, max_length=320)
    telephone: Optional[str] = Field(default=None, max_length=50)
    cellulaire: Optional[str] = Field(default=None, max_length=50)
    site_web: Optional[str] = Field(default=None, max_length=500)
    secteur: Optional[str] = Field(default=None, max_length=255)
    langue: Optional[str] = Field(default=None, max_length=8)
    statut: Optional[str] = None
    notes: Optional[str] = None
    prochaine_relance_le: Optional[date] = None


class ContactIn(BaseModel):
    canal: str = "courriel"
    direction: str = "sortant"
    sujet: Optional[str] = Field(default=None, max_length=255)
    contenu: Optional[str] = None
    date: Optional[datetime] = None
    annonce_id: Optional[int] = None


class StatsOut(BaseModel):
    total: int = 0
    par_statut: Dict[str, int] = {}
    avec_courriel: int = 0
    sans_courriel: int = 0
    relances_dues: int = 0
    annonces: int = 0
    annonces_actives: int = 0


class ListeOut(BaseModel):
    items: List[CourtierOut]
    total: int
    stats: StatsOut


class ParametresIn(BaseModel):
    seuil_logements: Optional[int] = Field(default=None, ge=1, le=1000)
    pages_centris: Optional[int] = Field(default=None, ge=1, le=10)
    max_details_par_scan: Optional[int] = Field(default=None, ge=0, le=200)
    relance_jours: Optional[int] = Field(default=None, ge=1, le=365)
    sujet: Optional[str] = Field(default=None, max_length=255)
    corps_html: Optional[str] = None
    signature: Optional[str] = None
    from_email: Optional[str] = Field(default=None, max_length=320)
    from_name: Optional[str] = Field(default=None, max_length=255)
    reply_to: Optional[str] = Field(default=None, max_length=320)


class ParametresOut(BaseModel):
    config: Dict[str, Any]
    defauts: Dict[str, Any]
    variables: List[Dict[str, str]]
    mailer_pret: bool


class ScanIn(BaseModel):
    #: Lire Centris via le VPS de scraping (plus long). False = seulement
    #: ce que Kratos connaît déjà (annonces reçues, fiches d'analyse).
    vps: bool = True


class ScanStart(BaseModel):
    job_id: str
    status: str
    deja_en_cours: bool = False


class ApercuIn(BaseModel):
    courtier_id: Optional[int] = None
    sujet: Optional[str] = None
    corps_html: Optional[str] = None


class ApercuOut(BaseModel):
    sujet: str
    corps_html: str
    to: Optional[str] = None
    annonce: Optional[AnnonceOut] = None
    exemple: bool = False


class EnvoiIn(BaseModel):
    courtier_ids: List[int] = []
    sujet: Optional[str] = None
    corps_html: Optional[str] = None
    #: Adresse de test : le gabarit part à cette adresse avec un courtier
    #: d'exemple ; aucune fiche n'est touchée.
    test_vers: Optional[str] = Field(default=None, max_length=320)


class EnvoiOut(BaseModel):
    envoyes: int
    echecs: List[Dict[str, Any]]
    test: bool = False


# ─── Helpers ─────────────────────────────────────────────────────────


def _agregats_subqueries():
    ann = (
        select(
            ProspectionCourtierAnnonce.courtier_id.label("cid"),
            func.count().label("nb"),
            func.sum(
                case((ProspectionCourtierAnnonce.active.is_(True), 1), else_=0)
            ).label("nb_actives"),
            func.max(ProspectionCourtierAnnonce.nb_units).label("max_u"),
        )
        .group_by(ProspectionCourtierAnnonce.courtier_id)
        .subquery()
    )
    ctc = (
        select(
            ProspectionCourtierContact.courtier_id.label("cid"),
            func.count().label("nb"),
        )
        .group_by(ProspectionCourtierContact.courtier_id)
        .subquery()
    )
    return ann, ctc


def _to_out(row: ProspectionCourtier, nb, nb_actives, max_u, nb_ctc) -> CourtierOut:
    out = CourtierOut.model_validate(row)
    out.nb_annonces = int(nb or 0)
    out.nb_annonces_actives = int(nb_actives or 0)
    out.max_logements = int(max_u) if max_u is not None else None
    out.nb_contacts = int(nb_ctc or 0)
    return out


async def _charger_out(db, courtier_id: int) -> Optional[CourtierOut]:
    ann, ctc = _agregats_subqueries()
    row = (
        await db.execute(
            select(ProspectionCourtier, ann.c.nb, ann.c.nb_actives, ann.c.max_u, ctc.c.nb)
            .outerjoin(ann, ann.c.cid == ProspectionCourtier.id)
            .outerjoin(ctc, ctc.c.cid == ProspectionCourtier.id)
            .where(ProspectionCourtier.id == courtier_id)
        )
    ).first()
    if row is None:
        return None
    return _to_out(*row)


async def _get_or_404(db, courtier_id: int) -> ProspectionCourtier:
    c = await db.get(ProspectionCourtier, courtier_id)
    if c is None:
        raise HTTPException(404, "Courtier introuvable.")
    return c


def _nettoyer_statut(s: Optional[str]) -> Optional[str]:
    if s is None:
        return None
    if s not in COURTIER_STATUTS:
        raise HTTPException(
            422, f"Statut inconnu « {s} » (attendu : {', '.join(COURTIER_STATUTS)})."
        )
    return s


async def _stats(db) -> StatsOut:
    rows = (
        await db.execute(
            select(ProspectionCourtier.statut, func.count()).group_by(
                ProspectionCourtier.statut
            )
        )
    ).all()
    par_statut = {s: 0 for s in COURTIER_STATUTS}
    total = 0
    for s, n in rows:
        par_statut[s] = int(n)
        total += int(n)
    avec_courriel = int(
        (
            await db.execute(
                select(func.count()).select_from(ProspectionCourtier).where(
                    ProspectionCourtier.courriel.is_not(None),
                    ProspectionCourtier.courriel != "",
                )
            )
        ).scalar_one()
        or 0
    )
    today = datetime.now(timezone.utc).date()
    relances = int(
        (
            await db.execute(
                select(func.count()).select_from(ProspectionCourtier).where(
                    ProspectionCourtier.prochaine_relance_le.is_not(None),
                    ProspectionCourtier.prochaine_relance_le <= today,
                    ProspectionCourtier.statut.in_(("contacte", "repondu")),
                )
            )
        ).scalar_one()
        or 0
    )
    nb_ann, nb_act = (
        await db.execute(
            select(
                func.count(),
                func.sum(
                    case((ProspectionCourtierAnnonce.active.is_(True), 1), else_=0)
                ),
            ).select_from(ProspectionCourtierAnnonce)
        )
    ).one()
    return StatsOut(
        total=total,
        par_statut=par_statut,
        avec_courriel=avec_courriel,
        sans_courriel=max(0, total - avec_courriel),
        relances_dues=relances,
        annonces=int(nb_ann or 0),
        annonces_actives=int(nb_act or 0),
    )


# ─── Liste / création ────────────────────────────────────────────────


@router.get("", response_model=ListeOut, summary="Registre des courtiers")
async def lister_courtiers(
    db: DBSession,
    user: RequireManager,
    q: Optional[str] = Query(default=None, max_length=120),
    statut: Optional[str] = Query(default=None),
    agence: Optional[str] = Query(default=None, max_length=120),
    avec_courriel: Optional[bool] = Query(default=None),
    min_annonces: int = Query(default=0, ge=0),
    relance_due: bool = Query(default=False),
    limit: int = Query(default=500, ge=1, le=2000),
    offset: int = Query(default=0, ge=0),
) -> ListeOut:
    ann, ctc = _agregats_subqueries()
    stmt = (
        select(ProspectionCourtier, ann.c.nb, ann.c.nb_actives, ann.c.max_u, ctc.c.nb)
        .outerjoin(ann, ann.c.cid == ProspectionCourtier.id)
        .outerjoin(ctc, ctc.c.cid == ProspectionCourtier.id)
    )
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(
            ProspectionCourtier.nom.ilike(like)
            | ProspectionCourtier.agence.ilike(like)
            | ProspectionCourtier.courriel.ilike(like)
            | ProspectionCourtier.secteur.ilike(like)
            | ProspectionCourtier.telephone.ilike(like)
        )
    if statut:
        stmt = stmt.where(ProspectionCourtier.statut == _nettoyer_statut(statut))
    if agence:
        stmt = stmt.where(ProspectionCourtier.agence.ilike(f"%{agence.strip()}%"))
    if avec_courriel is True:
        stmt = stmt.where(
            ProspectionCourtier.courriel.is_not(None), ProspectionCourtier.courriel != ""
        )
    elif avec_courriel is False:
        stmt = stmt.where(
            (ProspectionCourtier.courriel.is_(None)) | (ProspectionCourtier.courriel == "")
        )
    if min_annonces > 0:
        stmt = stmt.where(func.coalesce(ann.c.nb, 0) >= min_annonces)
    if relance_due:
        today = datetime.now(timezone.utc).date()
        stmt = stmt.where(
            ProspectionCourtier.prochaine_relance_le.is_not(None),
            ProspectionCourtier.prochaine_relance_le <= today,
        )
    total = int(
        (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
        or 0
    )
    stmt = (
        stmt.order_by(
            func.coalesce(ann.c.max_u, 0).desc(),
            func.coalesce(ann.c.nb, 0).desc(),
            ProspectionCourtier.nom.asc(),
        )
        .limit(limit)
        .offset(offset)
    )
    rows = (await db.execute(stmt)).all()
    items = [_to_out(*r) for r in rows]
    return ListeOut(items=items, total=total, stats=await _stats(db))


@router.post("", response_model=CourtierOut, status_code=201, summary="Ajouter un courtier")
async def creer_courtier(
    payload: CourtierCreate, db: DBSession, user: RequireManager
) -> CourtierOut:
    cle = svc.normaliser_cle(payload.nom)
    if len(cle) < 3:
        raise HTTPException(422, "Nom trop court.")
    existant = (
        await db.execute(
            select(ProspectionCourtier).where(ProspectionCourtier.cle_dedup == cle)
        )
    ).scalar_one_or_none()
    if existant is not None:
        raise HTTPException(
            409, f"Ce courtier existe déjà dans le registre (#{existant.id} — {existant.nom})."
        )
    maintenant = datetime.now(timezone.utc)
    c = ProspectionCourtier(
        nom=payload.nom.strip(),
        agence=(payload.agence or "").strip() or None,
        courriel=((payload.courriel or "").strip().lower() or None),
        telephone=(payload.telephone or "").strip() or None,
        cellulaire=(payload.cellulaire or "").strip() or None,
        site_web=(payload.site_web or "").strip() or None,
        secteur=(payload.secteur or "").strip() or None,
        langue=(payload.langue or "fr").strip()[:8] or "fr",
        source="manuel",
        statut=_nettoyer_statut(payload.statut) or "a_contacter",
        notes=payload.notes,
        cle_dedup=cle,
        premier_vu_le=maintenant,
        dernier_vu_le=maintenant,
    )
    db.add(c)
    await db.flush()
    await log_action(
        db, user=user, action="prospection.courtier.cree",
        entity_type="prospection_courtier", entity_id=c.id,
        details={"nom": c.nom, "agence": c.agence},
    )
    out = await _charger_out(db, c.id)
    assert out is not None
    return out


# ─── Paramètres (déclarés AVANT /{id}) ───────────────────────────────


async def _parametres_out(config: Optional[Dict[str, Any]] = None) -> ParametresOut:
    from app.integrations.email_graph import get_mailer

    try:
        pret = bool(get_mailer().ready)
    except Exception:  # noqa: BLE001
        pret = False
    return ParametresOut(
        config=config if config is not None else await svc.charger_config(),
        defauts=dict(svc.DEFAUTS),
        variables=VARIABLES_GABARIT,
        mailer_pret=pret,
    )


@router.get("/parametres", response_model=ParametresOut, summary="Réglages du registre")
async def lire_parametres(user: RequireManager) -> ParametresOut:
    return await _parametres_out()


@router.put("/parametres", response_model=ParametresOut, summary="Enregistrer les réglages")
async def ecrire_parametres(
    payload: ParametresIn, db: DBSession, user: RequireAdminOrOwner
) -> ParametresOut:
    actuel = dict(await get_automation_config(svc.CONFIG_KEY) or {})
    for k, v in payload.model_dump(exclude_unset=True).items():
        if v is None:
            actuel.pop(k, None)
        else:
            actuel[k] = v
    await set_automation_config(db, svc.CONFIG_KEY, actuel, user_id=user.id)
    await log_action(
        db, user=user, action="prospection.courtiers.parametres",
        entity_type="automation_setting", entity_id=None,
        details={
            k: (v if k != "corps_html" else f"{len(str(v))} car.")
            for k, v in actuel.items()
        },
    )
    await db.flush()
    # Réponse bâtie sur ce qu'on vient d'écrire : la relecture passerait
    # par une autre session et ne verrait pas la transaction en cours.
    return await _parametres_out(svc.fusionner_config(actuel))


# ─── Scan (tâche de fond) ────────────────────────────────────────────


_SCAN_JOBS: Dict[str, dict] = {}
_SCAN_JOBS_MAX = 50
_SCAN_JOBS_TTL_S = 3600.0


def _session_factory_jobs():
    """Indirection pour les tests (remplacée par la base de test)."""
    from app.db.session import AsyncSessionLocal

    return AsyncSessionLocal


def _purger_jobs() -> None:
    now = time.monotonic()
    for k in [
        k for k, j in _SCAN_JOBS.items()
        if now - j["_t0"] > _SCAN_JOBS_TTL_S and j.get("status") != "en_cours"
    ]:
        _SCAN_JOBS.pop(k, None)
    while len(_SCAN_JOBS) > _SCAN_JOBS_MAX:
        _SCAN_JOBS.pop(next(iter(_SCAN_JOBS)), None)


def _job_en_cours() -> Optional[dict]:
    for j in _SCAN_JOBS.values():
        if j.get("status") == "en_cours":
            return j
    return None


async def _scan_worker(job_id: str, user_id: Optional[int], utiliser_vps: bool) -> None:
    job = _SCAN_JOBS.get(job_id)
    if job is None:
        return
    try:
        from app.models.user import User

        factory = _session_factory_jobs()
        config = await svc.charger_config()
        async with factory() as db:
            def _progres(msg: str) -> None:
                job["etape"] = msg

            rapport = await svc.scan(
                db, config=config, utiliser_vps=utiliser_vps, progres=_progres
            )
            user = await db.get(User, user_id) if user_id else None
            details = {k: v for k, v in rapport.items() if k != "erreurs"}
            details["nb_erreurs"] = len(rapport.get("erreurs") or [])
            await log_action(
                db, user=user, action="prospection.courtiers.scan",
                entity_type="prospection_courtier", entity_id=None,
                details=details,
            )
            await db.commit()
        job["resultat"] = rapport
        job["status"] = "termine"
        job["etape"] = "Terminé"
    except Exception as exc:  # noqa: BLE001
        log.exception("scan courtiers %s en échec", job_id)
        job["status"] = "erreur"
        job["erreur"] = f"{type(exc).__name__}: {str(exc)[:400]}"
    finally:
        job["termine_a"] = datetime.now(timezone.utc).isoformat()


@router.post("/scan", response_model=ScanStart, summary="Construire / mettre à jour le registre")
async def lancer_scan(payload: ScanIn, user: RequireManager) -> ScanStart:
    _purger_jobs()
    deja = _job_en_cours()
    if deja is not None:
        return ScanStart(job_id=deja["job_id"], status="en_cours", deja_en_cours=True)
    job_id = secrets.token_urlsafe(12)
    uid = getattr(user, "id", None)
    _SCAN_JOBS[job_id] = {
        "job_id": job_id,
        "status": "en_cours",
        "user_id": uid,
        "vps": bool(payload.vps),
        "etape": "Démarrage…",
        "demarre_a": datetime.now(timezone.utc).isoformat(),
        "termine_a": None,
        "resultat": None,
        "erreur": None,
        "_t0": time.monotonic(),
    }
    _SCAN_JOBS[job_id]["_task"] = asyncio.create_task(
        _scan_worker(job_id, uid, bool(payload.vps))
    )
    return ScanStart(job_id=job_id, status="en_cours")


@router.get("/scan/{job_id}", summary="État d'un scan")
async def etat_scan(job_id: str, user: RequireManager) -> dict:
    job = _SCAN_JOBS.get(job_id)
    if job is None:
        raise HTTPException(
            404, "Scan introuvable (le serveur a peut-être redémarré). Relance le scan."
        )
    out = {k: v for k, v in job.items() if not k.startswith("_")}
    out["duree_s"] = round(time.monotonic() - job["_t0"], 1)
    return out


# ─── Aperçu / envoi ──────────────────────────────────────────────────


@router.post("/apercu", response_model=ApercuOut, summary="Aperçu du courriel rendu")
async def apercu_courriel(
    payload: ApercuIn, db: DBSession, user: RequireManager
) -> ApercuOut:
    config = await svc.charger_config()
    sujet = payload.sujet if payload.sujet is not None else str(config["sujet"])
    corps = (
        payload.corps_html if payload.corps_html is not None else str(config["corps_html"])
    )
    if payload.courtier_id is None:
        ctx = svc.contexte_courtier(
            svc.EXEMPLE_COURTIER, svc.EXEMPLE_ANNONCE, config  # type: ignore[arg-type]
        )
        return ApercuOut(
            sujet=svc.rendre(sujet, ctx), corps_html=svc.rendre(corps, ctx),
            to=None, annonce=None, exemple=True,
        )
    c = await _get_or_404(db, payload.courtier_id)
    annonce = await svc.meilleure_annonce(db, c)
    ctx = svc.contexte_courtier(c, annonce, config)
    return ApercuOut(
        sujet=svc.rendre(sujet, ctx),
        corps_html=svc.rendre(corps, ctx),
        to=c.courriel,
        annonce=AnnonceOut.model_validate(annonce) if annonce else None,
        exemple=False,
    )


@router.post("/envoyer", response_model=EnvoiOut, summary="Envoyer le courriel de présentation")
async def envoyer_courriels(
    payload: EnvoiIn, db: DBSession, user: RequireManager
) -> EnvoiOut:
    config = await svc.charger_config()
    sujet = payload.sujet if payload.sujet is not None else str(config["sujet"])
    corps = (
        payload.corps_html if payload.corps_html is not None else str(config["corps_html"])
    )
    if payload.test_vers:
        res = await svc.envoyer_test(
            vers=payload.test_vers, sujet=sujet, corps_html=corps, config=config
        )
        if not res["ok"]:
            raise HTTPException(502, res["erreur"] or "Envoi de test impossible.")
        return EnvoiOut(envoyes=1, echecs=[], test=True)
    ids = list(dict.fromkeys(payload.courtier_ids))
    if not ids:
        raise HTTPException(400, "Aucun courtier sélectionné.")
    if len(ids) > _MAX_ENVOIS_PAR_APPEL:
        raise HTTPException(
            400, f"Maximum {_MAX_ENVOIS_PAR_APPEL} courtiers par envoi — fais plusieurs lots."
        )
    envoyes = 0
    echecs: List[Dict[str, Any]] = []
    for cid in ids:
        c = await db.get(ProspectionCourtier, cid)
        if c is None:
            echecs.append({"id": cid, "nom": None, "erreur": "Courtier introuvable."})
            continue
        if c.statut == "ignorer":
            echecs.append(
                {"id": cid, "nom": c.nom, "erreur": "Statut « Ignorer » — non envoyé."}
            )
            continue
        annonce = await svc.meilleure_annonce(db, c)
        res = await svc.envoyer_presentation(
            db, user=user, courtier=c, sujet=sujet, corps_html=corps,
            config=config, annonce=annonce,
        )
        if res["ok"]:
            envoyes += 1
        else:
            echecs.append({"id": cid, "nom": c.nom, "erreur": res["erreur"]})
    await db.flush()
    return EnvoiOut(envoyes=envoyes, echecs=echecs)


# ─── Export CSV ──────────────────────────────────────────────────────


@router.get("/export.csv", summary="Exporter le registre (CSV)")
async def exporter_csv(db: DBSession, user: RequireManager) -> Response:
    ann, ctc = _agregats_subqueries()
    rows = (
        await db.execute(
            select(ProspectionCourtier, ann.c.nb, ann.c.nb_actives, ann.c.max_u, ctc.c.nb)
            .outerjoin(ann, ann.c.cid == ProspectionCourtier.id)
            .outerjoin(ctc, ctc.c.cid == ProspectionCourtier.id)
            .order_by(ProspectionCourtier.nom.asc())
        )
    ).all()
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow([
        "Nom", "Agence", "Courriel", "Téléphone", "Cellulaire", "Secteur", "Statut",
        "Source", "Annonces", "Annonces actives", "Max logements", "Dernier vu",
        "Dernier contact", "Prochaine relance", "Notes",
    ])
    for c, nb, nb_act, max_u, _nb_ctc in rows:
        w.writerow([
            c.nom, c.agence or "", c.courriel or "", c.telephone or "", c.cellulaire or "",
            c.secteur or "", c.statut, c.source, int(nb or 0), int(nb_act or 0),
            int(max_u) if max_u is not None else "",
            c.dernier_vu_le.date().isoformat() if c.dernier_vu_le else "",
            c.dernier_contact_le.date().isoformat() if c.dernier_contact_le else "",
            c.prochaine_relance_le.isoformat() if c.prochaine_relance_le else "",
            (c.notes or "").replace("\r", " ").replace("\n", " "),
        ])
    nom = f"registre-courtiers-{datetime.now(timezone.utc).date().isoformat()}.csv"
    return Response(
        content=("﻿" + buf.getvalue()).encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{nom}"'},
    )


# ─── Fiche ───────────────────────────────────────────────────────────


@router.get("/{courtier_id}", response_model=CourtierDetail, summary="Fiche d'un courtier")
async def lire_courtier(
    courtier_id: int, db: DBSession, user: RequireManager
) -> CourtierDetail:
    base = await _charger_out(db, courtier_id)
    if base is None:
        raise HTTPException(404, "Courtier introuvable.")
    annonces = (
        await db.execute(
            select(ProspectionCourtierAnnonce)
            .where(ProspectionCourtierAnnonce.courtier_id == courtier_id)
            .order_by(
                ProspectionCourtierAnnonce.active.desc(),
                ProspectionCourtierAnnonce.nb_units.desc().nullslast(),
            )
        )
    ).scalars().all()
    contacts = (
        await db.execute(
            select(ProspectionCourtierContact)
            .where(ProspectionCourtierContact.courtier_id == courtier_id)
            .order_by(
                ProspectionCourtierContact.date.desc(), ProspectionCourtierContact.id.desc()
            )
        )
    ).scalars().all()
    return CourtierDetail(
        **base.model_dump(),
        annonces=[AnnonceOut.model_validate(a) for a in annonces],
        contacts=[ContactOut.model_validate(k) for k in contacts],
    )


@router.patch("/{courtier_id}", response_model=CourtierOut, summary="Modifier un courtier")
async def modifier_courtier(
    courtier_id: int, payload: CourtierPatch, db: DBSession, user: RequireManager
) -> CourtierOut:
    c = await _get_or_404(db, courtier_id)
    data = payload.model_dump(exclude_unset=True)
    if "statut" in data:
        data["statut"] = _nettoyer_statut(data["statut"]) or c.statut
    if "nom" in data and data["nom"]:
        nouveau = data["nom"].strip()
        cle = svc.normaliser_cle(nouveau)
        if len(cle) < 3:
            raise HTTPException(422, "Nom trop court.")
        autre = (
            await db.execute(
                select(ProspectionCourtier).where(
                    ProspectionCourtier.cle_dedup == cle, ProspectionCourtier.id != c.id
                )
            )
        ).scalar_one_or_none()
        if autre is not None:
            raise HTTPException(
                409, f"Un autre courtier porte déjà ce nom (#{autre.id} — {autre.nom})."
            )
        c.nom = nouveau
        c.cle_dedup = cle
        data.pop("nom")
    if "courriel" in data and data["courriel"] is not None:
        data["courriel"] = data["courriel"].strip().lower() or None
    for k, v in data.items():
        if isinstance(v, str):
            v = v.strip() or None
        setattr(c, k, v)
    if not c.langue:
        c.langue = "fr"
    await db.flush()
    await log_action(
        db, user=user, action="prospection.courtier.modifie",
        entity_type="prospection_courtier", entity_id=c.id,
        details={"champs": sorted(payload.model_dump(exclude_unset=True).keys())},
    )
    out = await _charger_out(db, c.id)
    assert out is not None
    return out


@router.delete("/{courtier_id}", status_code=204, summary="Supprimer un courtier")
async def supprimer_courtier(
    courtier_id: int, db: DBSession, user: RequireManager
) -> Response:
    c = await _get_or_404(db, courtier_id)
    await db.execute(
        delete(ProspectionCourtierContact).where(
            ProspectionCourtierContact.courtier_id == courtier_id
        )
    )
    await db.execute(
        delete(ProspectionCourtierAnnonce).where(
            ProspectionCourtierAnnonce.courtier_id == courtier_id
        )
    )
    await log_action(
        db, user=user, action="prospection.courtier.supprime",
        entity_type="prospection_courtier", entity_id=c.id,
        details={"nom": c.nom, "agence": c.agence},
    )
    await db.delete(c)
    await db.flush()
    return Response(status_code=204)


@router.post(
    "/{courtier_id}/contacts", response_model=CourtierDetail, status_code=201,
    summary="Ajouter une entrée au journal des contacts",
)
async def ajouter_contact(
    courtier_id: int, payload: ContactIn, db: DBSession, user: RequireManager
) -> CourtierDetail:
    c = await _get_or_404(db, courtier_id)
    if payload.canal not in CANAUX:
        raise HTTPException(422, f"Canal inconnu (attendu : {', '.join(CANAUX)}).")
    if payload.direction not in DIRECTIONS:
        raise HTTPException(422, "Direction attendue : sortant ou entrant.")
    quand = payload.date or datetime.now(timezone.utc)
    if quand.tzinfo is None:
        quand = quand.replace(tzinfo=timezone.utc)
    if payload.annonce_id is not None:
        a = await db.get(ProspectionCourtierAnnonce, payload.annonce_id)
        if a is None or a.courtier_id != c.id:
            raise HTTPException(422, "Annonce inconnue pour ce courtier.")
    db.add(
        ProspectionCourtierContact(
            courtier_id=c.id, annonce_id=payload.annonce_id, date=quand,
            canal=payload.canal, direction=payload.direction,
            sujet=(payload.sujet or "").strip() or None, contenu=payload.contenu,
            auteur_email=getattr(user, "email", None),
        )
    )
    config = await svc.charger_config()
    if payload.direction == "entrant":
        if c.statut in ("a_contacter", "contacte"):
            c.statut = "repondu"
        c.prochaine_relance_le = None
    else:
        if c.dernier_contact_le is not None:
            c.nb_relances = int(c.nb_relances or 0) + 1
        c.dernier_contact_le = quand
        if c.statut == "a_contacter":
            c.statut = "contacte"
        c.prochaine_relance_le = (
            quand + timedelta(days=int(config.get("relance_jours") or 14))
        ).date()
    await db.flush()
    await log_action(
        db, user=user, action="prospection.courtier.contact_journalise",
        entity_type="prospection_courtier", entity_id=c.id,
        details={
            "canal": payload.canal, "direction": payload.direction, "sujet": payload.sujet
        },
    )
    return await lire_courtier(courtier_id, db, user)
