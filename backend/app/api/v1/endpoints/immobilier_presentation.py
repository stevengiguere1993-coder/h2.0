"""Refonte d'Immobilier — interrupteur de présentation et page « Aujourd'hui ».

    GET  /immobilier/presentation   réglage courant (tout compte connecté)
    PUT  /immobilier/presentation   changer un ou plusieurs lots (admin)
    GET  /immobilier/aujourdhui     la liste de choses à faire du jour

Le réglage est lu par tout compte connecté (le menu d'Immobilier en a
besoin avant d'afficher quoi que ce soit) ; seul un admin le change.
« Aujourd'hui » est gardé par le volet Immobilier, comme les vues qu'il
réunit.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from app.api.deps import CurrentUser, DBSession, RequireAdminRole, require_volet
from app.models.immobilier import Immeuble
from app.services import immobilier_aujourdhui as auj
from app.services import immobilier_presentation as pres
from app.services.punch_diner import aujourd_hui_local

log = logging.getLogger(__name__)

#: Réglage : aucun volet exigé (lecture), rôle admin (écriture).
router = APIRouter(prefix="/immobilier", tags=["immobilier-presentation"])
#: « Aujourd'hui » : volet Immobilier.
router_aujourdhui = APIRouter(
    prefix="/immobilier",
    tags=["immobilier-presentation"],
    dependencies=[Depends(require_volet("immobilier"))],
)


# ── Interrupteur de présentation ───────────────────────────────────────


class LotPresentation(BaseModel):
    cle: str
    titre: str
    description: str
    #: Les écrans de ce lot sont livrés ; sinon le réglage est sans effet.
    livre: bool
    #: Réglage : vrai = nouvelle présentation, faux = présentation actuelle.
    nouvelle: bool


class PresentationOut(BaseModel):
    lots: List[LotPresentation]
    #: Ce que les écrans montrent : vrai seulement pour un lot livré ET
    #: réglé sur la nouvelle présentation.
    actif: Dict[str, bool]
    modifie_le: Optional[datetime] = None
    modifie_par: Optional[str] = None


class PresentationIn(BaseModel):
    """Un booléen par lot à changer (vrai = nouvelle présentation). Les
    lots absents ne bougent pas ; une clé inconnue est refusée."""

    model_config = ConfigDict(extra="forbid")

    menu: Optional[bool] = None
    loyers: Optional[bool] = None
    baux: Optional[bool] = None
    fiches: Optional[bool] = None
    suivis: Optional[bool] = None


@router.get("/presentation", response_model=PresentationOut)
async def lire_presentation(db: DBSession, _: CurrentUser) -> PresentationOut:
    """Quelle présentation d'Immobilier est montrée, lot par lot."""
    return PresentationOut(**(await pres.etat(db)))


@router.put("/presentation", response_model=PresentationOut)
async def changer_presentation(
    payload: PresentationIn, db: DBSession, admin: RequireAdminRole
) -> PresentationOut:
    """Passe un ou plusieurs lots à la nouvelle présentation (vrai) ou
    revient à la présentation actuelle (faux). Commun à toute l'équipe,
    effet immédiat, aucune donnée touchée."""
    changements = {
        cle: valeur
        for cle, valeur in payload.model_dump().items()
        if valeur is not None
    }
    if not changements:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Aucun lot à changer : envoyer au moins une clé parmi "
            + ", ".join(pres.CLES)
            + ".",
        )
    await pres.enregistrer(db, changements, user_id=admin.id)
    await db.commit()
    return PresentationOut(**(await pres.etat(db)))


# ── Page « Aujourd'hui » ───────────────────────────────────────────────


class LigneAujourdhui(BaseModel):
    cle: str
    nb: int
    titre: str
    detail: Optional[str] = None
    #: "urgent" | "attention" | "info"
    ton: str
    href: str
    bouton: str = "Voir"


class AujourdhuiOut(BaseModel):
    jour: date
    lignes: List[LigneAujourdhui]
    #: Ce qui presse (pastille rouge du menu) : loyers à encaisser, avis
    #: de renouvellement en retard, bons de travail urgents.
    nb_urgent: int = 0
    #: Sujets vérifiés où il n'y a rien à faire.
    rien_a_signaler: List[str] = []
    #: Sujets qui n'ont pas pu être lus (la page le dit au lieu de les
    #: passer sous silence).
    indisponibles: List[str] = []


#: Statuts d'un bon de travail interne encore ouvert.
_BONS_OUVERTS = {"accepte_a_planifier", "planifie"}


@router_aujourdhui.get("/aujourdhui", response_model=AujourdhuiOut)
async def aujourdhui(
    db: DBSession,
    user: CurrentUser,
    entreprise_id: Optional[int] = None,
) -> AujourdhuiOut:
    """Tout ce qui demande une action aujourd'hui dans Immobilier, en une
    liste : loyers à encaisser, avis de renouvellement, baux signés à
    importer, logements à louer, bons de travail ouverts, dépôts à
    rendre, preuves d'assurance et consentements à relancer.

    Chaque compte vient de la vue de la page où la ligne mène (mêmes
    règles, mêmes exclusions : gestion externe, immeubles visibles).
    ``entreprise_id`` restreint aux immeubles d'une entreprise.
    """
    from app.api.v1.endpoints import immobilier as immo
    from app.api.v1.endpoints import immobilier_assurances as immo_ass
    from app.api.v1.endpoints import immobilier_locations as immo_loc

    c = auj.Chiffres()
    today = aujourd_hui_local()

    #: Immeubles de l'entreprise, pour filtrer les vues qui n'ont pas de
    #: paramètre ``entreprise_id``.
    imm_entreprise: Optional[set[int]] = None
    if entreprise_id is not None:
        imm_entreprise = {
            row[0]
            for row in (
                await db.execute(
                    select(Immeuble.id).where(
                        Immeuble.owner_entreprise_id == int(entreprise_id)
                    )
                )
            ).all()
        }

    def _dans_entreprise(immeuble_id: Optional[int]) -> bool:
        if imm_entreprise is None:
            return True
        return immeuble_id is not None and immeuble_id in imm_entreprise

    async def _lire(cle: str, lecture) -> None:
        """Une vue illisible ne fait pas tomber la page : la ligne est
        marquée indisponible et les autres sont servies."""
        try:
            await lecture()
        except HTTPException:
            raise
        except Exception:  # noqa: BLE001
            log.exception("Aujourd'hui : lecture « %s » impossible", cle)
            c.indisponibles.append(cle)
            try:
                await db.rollback()
            except Exception:  # noqa: BLE001
                pass

    async def _loyers() -> None:
        lo = await immo.loyers_overview(
            db=db, user=user, mois=None, entreprise_id=entreprise_id
        )
        dus = [r for r in lo.rows if r.etat in ("retard", "partiel")]
        c.loyers_nb = len(dus)
        c.loyers_total = round(sum(float(r.solde_total or 0) for r in dus), 2)

    async def _avis() -> None:
        ech = await immo.baux_echeances(
            db=db,
            user=user,
            entreprise_id=entreprise_id,
            immeuble_id=None,
            horizon_jours=45,
        )
        c.avis_en_retard = ech.nb_en_retard
        c.avis_a_envoyer = ech.nb_a_envoyer
        a_faire = [r for r in ech.rows if r.statut in ("en_retard", "a_envoyer")]
        if len(a_faire) == 1:
            r = a_faire[0]
            c.avis_qui = f"{r.locataire}, log. {r.logement}"

    async def _baux_a_importer() -> None:
        sans = await immo.baux_sans_document(
            db=db, user=user, entreprise_id=entreprise_id, immeuble_id=None
        )
        c.baux_a_importer = sans.nb
        c.baux_a_importer_immeubles = len({r.immeuble_id for r in sans.rows})
        if sans.nb == 1:
            r = sans.rows[0]
            c.baux_a_importer_qui = f"{r.locataire}, log. {r.logement}"

    async def _a_louer() -> None:
        loc = await immo_loc.locations_overview(
            db=db, user=user, entreprise_id=entreprise_id, immeuble_id=None
        )
        c.a_louer = loc.nb_a_louer + loc.nb_affiches
        partis = [
            (today - r.date_depart).days
            for r in loc.rows
            if r.statut in ("avis_recu", "annonce_publiee")
            and r.date_depart is not None
            and r.date_depart <= today
        ]
        c.a_louer_jours_max = max(partis) if partis else None

    async def _bons() -> None:
        bons = await immo.list_gestion_immo_bons(db=db, user=user)
        ouverts = [
            b
            for b in bons
            if b.status in _BONS_OUVERTS and _dans_entreprise(b.immeuble_id)
        ]
        c.bons_ouverts = len(ouverts)
        c.bons_urgents = sum(1 for b in ouverts if b.is_urgent)

    async def _depots() -> None:
        dep = await immo.depots_overview(
            db=db, user=user, entreprise_id=entreprise_id, immeuble_id=None
        )
        c.depots_nb = dep.nb_a_rendre
        c.depots_total = float(dep.total_a_rendre or 0)

    async def _assurances() -> None:
        ass = await immo_ass.assurances_overview(db=db, user=user)
        seuil = datetime.now(timezone.utc) - timedelta(
            days=auj.JOURS_RELANCE_ASSURANCE
        )
        c.assurances_a_relancer = sum(
            1
            for r in ass.rows
            if r.statut != "ok"
            and r.derniere_demande_le is not None
            and _avant(r.derniere_demande_le, seuil)
            and _dans_entreprise(r.immeuble_id)
        )

    async def _consentements() -> None:
        con = await immo_ass.consentements_overview(db=db, user=user)
        seuil = datetime.now(timezone.utc) - timedelta(
            days=auj.JOURS_RELANCE_CONSENTEMENT
        )
        c.consentements_a_relancer = sum(
            1
            for r in con.rows
            if r.statut in ("envoye", "ouvert")
            and r.envoye_le is not None
            and _avant(r.envoye_le, seuil)
            and _dans_entreprise(r.immeuble_id)
        )

    await _lire("loyers", _loyers)
    await _lire("renouvellements", _avis)
    await _lire("baux_a_importer", _baux_a_importer)
    await _lire("a_louer", _a_louer)
    await _lire("bons_travail", _bons)
    await _lire("depots", _depots)
    await _lire("assurances", _assurances)
    await _lire("consentements", _consentements)

    lignes, rien = auj.composer(c)
    return AujourdhuiOut(
        jour=today,
        lignes=[LigneAujourdhui(**ligne.__dict__) for ligne in lignes],
        nb_urgent=auj.nb_urgent(c),
        rien_a_signaler=rien,
        indisponibles=[auj.LIBELLES.get(cle, cle) for cle in c.indisponibles],
    )


def _avant(moment: datetime, seuil: datetime) -> bool:
    """``moment`` est-il antérieur à ``seuil`` ? Tolère une date sans
    fuseau (SQLite, anciennes lignes) : lue comme UTC."""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment < seuil
