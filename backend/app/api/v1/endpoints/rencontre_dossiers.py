"""Tableau des dossiers suivis en rencontres + consignes à Kratos.

  GET    /api/v1/rencontres/dossiers                 tableau (filtres)
  POST   /api/v1/rencontres/dossiers                 crée un dossier à la main
  GET    /api/v1/rencontres/dossiers/ordre-du-jour   ordre du jour des dossiers ouverts
  POST   /api/v1/rencontres/dossiers/analyser        analyse les rencontres en attente
  POST   /api/v1/rencontres/dossiers/reanalyser      remet des rencontres « à analyser »
  GET    /api/v1/rencontres/dossiers/doublons        paires proposées + fusions récentes
  POST   /api/v1/rencontres/dossiers/doublons/verifier
  POST   /api/v1/rencontres/dossiers/doublons/{id}/fusionner
  POST   /api/v1/rencontres/dossiers/doublons/{id}/separer
  GET    /api/v1/rencontres/dossiers/{id}            fiche + historique
  PATCH  /api/v1/rencontres/dossiers/{id}
  DELETE /api/v1/rencontres/dossiers/{id}
  POST   /api/v1/rencontres/dossiers/{id}/fusionner
  POST   /api/v1/rencontres/dossiers/{id}/defusionner
  GET    /api/v1/rencontres/consignes
  POST   /api/v1/rencontres/consignes
  PATCH  /api/v1/rencontres/consignes/{id}
  DELETE /api/v1/rencontres/consignes/{id}

Tout est réservé à qui voit la page « entreprises.rencontres ». Le
routeur est inclus AVANT celui des rencontres (``/rencontres/{id}``).
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.api.deps import CurrentUser, DBSession
from app.models.rencontre_dossier import (
    PORTEES_CONSIGNE,
    STATUTS_DOSSIER,
    RencontreConsigne,
    RencontreDossier,
    RencontreDossierDoublon,
)
from app.services import rencontre_consignes as consignes_svc
from app.services import rencontre_dossiers as svc

log = logging.getLogger(__name__)
router = APIRouter(prefix="/rencontres", tags=["rencontres"])

_PAGE = "entreprises.rencontres"


async def _garde(db, user) -> None:
    from app.services.assistant_catalogue import utilisateur_a_acces_page

    if not await utilisateur_a_acces_page(db, user, _PAGE):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Accès à la page Rencontres requis."
        )


async def _dossier_ou_404(db, dossier_id: int) -> RencontreDossier:
    d = await db.get(RencontreDossier, dossier_id)
    if d is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Dossier introuvable.")
    return d


def _statut_valide(v: Optional[str]) -> Optional[str]:
    if v is None:
        return None
    if v not in STATUTS_DOSSIER:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Statut inconnu : " + ", ".join(STATUTS_DOSSIER) + ".",
        )
    return v


# ── Schémas ─────────────────────────────────────────────────────────


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DossierCreate(_Strict):
    titre: str = Field(..., min_length=1, max_length=255)
    statut: Optional[str] = None
    entreprise_id: Optional[int] = None
    contexte: Optional[str] = Field(default=None, max_length=255)
    responsable: Optional[str] = Field(default=None, max_length=255)
    dernier_etat: Optional[str] = Field(default=None, max_length=4000)
    prochaine_action: Optional[str] = Field(default=None, max_length=2000)
    echeance: Optional[str] = Field(default=None, max_length=255)
    echeance_date: Optional[date] = None


class DossierUpdate(_Strict):
    titre: Optional[str] = Field(default=None, min_length=1, max_length=255)
    statut: Optional[str] = None
    entreprise_id: Optional[int] = None
    contexte: Optional[str] = Field(default=None, max_length=255)
    responsable: Optional[str] = Field(default=None, max_length=255)
    dernier_etat: Optional[str] = Field(default=None, max_length=4000)
    prochaine_action: Optional[str] = Field(default=None, max_length=2000)
    echeance: Optional[str] = Field(default=None, max_length=255)
    echeance_date: Optional[date] = None


class FusionnerIn(_Strict):
    dans_id: int


class FusionDoublonIn(_Strict):
    #: Dossier gardé ; par défaut celui qui a le plus d'historique.
    garder_id: Optional[int] = None


class ReanalyserIn(_Strict):
    #: Vide = toutes les rencontres.
    rencontre_ids: Optional[List[int]] = None


class ConsigneCreate(_Strict):
    texte: str = Field(..., min_length=3, max_length=2000)
    portee: str = Field(default="tout")


class ConsigneUpdate(_Strict):
    texte: Optional[str] = Field(default=None, min_length=3, max_length=2000)
    portee: Optional[str] = None
    actif: Optional[bool] = None


# ── Tableau ─────────────────────────────────────────────────────────


@router.get(
    "/dossiers",
    summary=(
        "Tableau des dossiers suivis en rencontres (statut, dernier état, "
        "prochaine action, dernière discussion)"
    ),
)
async def lister_dossiers(
    db: DBSession,
    user: CurrentUser,
    statut: Optional[str] = Query(default=None),
    entreprise_id: Optional[int] = Query(default=None),
    responsable: Optional[str] = Query(default=None, max_length=255),
    inclure_regles: bool = Query(default=False),
    a_relancer: bool = Query(default=False),
) -> dict:
    await _garde(db, user)
    return await svc.lister(
        db,
        statut=_statut_valide(statut),
        entreprise_id=entreprise_id,
        responsable=responsable,
        inclure_regles=inclure_regles,
        a_relancer=a_relancer,
    )


@router.post("/dossiers", status_code=status.HTTP_201_CREATED)
async def creer_dossier(
    data: DossierCreate, db: DBSession, user: CurrentUser
) -> dict:
    await _garde(db, user)
    d = RencontreDossier(
        titre=data.titre.strip(),
        statut=_statut_valide(data.statut) or "en_cours",
        entreprise_id=data.entreprise_id,
        contexte=(data.contexte or "").strip() or None,
        responsable=(data.responsable or "").strip() or None,
        dernier_etat=(data.dernier_etat or "").strip() or None,
        prochaine_action=(data.prochaine_action or "").strip() or None,
        echeance=(data.echeance or "").strip() or None,
        echeance_date=data.echeance_date,
        source="manuel",
        created_by_user_id=user.id,
    )
    db.add(d)
    await db.commit()
    await db.refresh(d)
    return await svc.detail(db, d)


@router.get(
    "/dossiers/ordre-du-jour",
    summary="Ordre du jour de la prochaine rencontre à partir des dossiers ouverts",
)
async def ordre_du_jour(
    db: DBSession,
    user: CurrentUser,
    entreprise_id: Optional[int] = Query(default=None),
) -> dict:
    await _garde(db, user)
    return await svc.ordre_du_jour(db, entreprise_id=entreprise_id)


@router.post(
    "/dossiers/analyser",
    summary=(
        "Analyse les rencontres dont les dossiers ne sont pas à jour. "
        "Par défaut quelques-unes par appel (rappeler tant que "
        "« restantes » > 0) ; « en_fond=true » lance toute la course en "
        "arrière-plan et répond tout de suite (suivre « analyse » dans "
        "GET /rencontres/dossiers)"
    ),
)
async def analyser(
    db: DBSession,
    user: CurrentUser,
    en_fond: bool = Query(default=False),
) -> dict:
    await _garde(db, user)
    if en_fond:
        # L'écran passe par ici : un appel à l'IA par rencontre dépasse
        # vite le délai du proxy (30 s) — la course tourne en fond et
        # l'écran se rafraîchit.
        lancee = svc.planifier_analyse()
        return {
            "en_fond": True,
            "lancee": lancee,
            "ia_absente": not svc.is_configured(),
            "restantes": len(await svc.rencontres_a_analyser(db)),
            "analyse": svc.etat_analyse(),
        }
    res = await svc.analyser_en_attente(db)
    await db.commit()
    return res


@router.post(
    "/dossiers/reanalyser",
    summary=(
        "Remet des rencontres (toutes par défaut) « à analyser », par "
        "exemple après une nouvelle consigne ; enchaîner avec /analyser"
    ),
)
async def reanalyser(
    db: DBSession, user: CurrentUser, data: Optional[ReanalyserIn] = None
) -> dict:
    await _garde(db, user)
    n = await svc.marquer_a_reanalyser(
        db, data.rencontre_ids if data else None
    )
    await db.commit()
    return {"rencontres_a_analyser": n}


# ── Doublons ────────────────────────────────────────────────────────


@router.get(
    "/dossiers/doublons",
    summary="Doublons possibles à trancher et dernières fusions (à défaire au besoin)",
)
async def lister_doublons(db: DBSession, user: CurrentUser) -> dict:
    await _garde(db, user)
    return {
        "proposes": await svc.doublons_proposes(db),
        "fusions_recentes": await svc.fusions_recentes(db),
    }


@router.post(
    "/dossiers/doublons/verifier",
    summary="Lance la passe de doublons (fusion d'office des certains, liste des douteux)",
)
async def verifier_doublons(db: DBSession, user: CurrentUser) -> dict:
    await _garde(db, user)
    if svc.analyse_en_cours():
        # La lecture des rencontres tient le verrou et finit elle-même
        # par la passe de doublons : ne pas faire attendre l'écran.
        return {"occupe": True, "fusionnes": [], "proposes": 0}
    res = await svc.verifier_doublons(db, avec_ia=True)
    await db.commit()
    return res


async def _doublon_ou_404(db, doublon_id: int) -> RencontreDossierDoublon:
    row = await db.get(RencontreDossierDoublon, doublon_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Doublon introuvable.")
    return row


@router.post("/dossiers/doublons/{doublon_id}/fusionner")
async def fusionner_doublon(
    doublon_id: int,
    db: DBSession,
    user: CurrentUser,
    data: Optional[FusionDoublonIn] = None,
) -> dict:
    await _garde(db, user)
    row = await _doublon_ou_404(db, doublon_id)
    a = await _dossier_ou_404(db, row.dossier_a_id)
    b = await _dossier_ou_404(db, row.dossier_b_id)
    a = await svc.racine(db, a)
    b = await svc.racine(db, b)
    if a.id == b.id:
        row.statut = "fusionne"
        row.decide_le = datetime.now(timezone.utc)
        await db.commit()
        return await svc.detail(db, a)
    garder = data.garder_id if data else None
    if garder is not None and garder not in (a.id, b.id):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "« garder_id » doit être l'un des deux dossiers de la paire.",
        )
    gagnant = (
        (a if garder == a.id else b)
        if garder is not None
        else await svc.choisir_gagnant(db, [a, b])
    )
    perdant = b if gagnant.id == a.id else a
    await svc.fusionner(
        db, perdant, gagnant, auto=False, raison=row.raison or "Fusion à la main"
    )
    await db.commit()
    return await svc.detail(db, gagnant)


@router.post("/dossiers/doublons/{doublon_id}/separer")
async def separer_doublon(
    doublon_id: int, db: DBSession, user: CurrentUser
) -> dict:
    """Garde les deux dossiers séparés : la paire n'est plus jamais
    proposée ni fusionnée d'office."""
    await _garde(db, user)
    row = await _doublon_ou_404(db, doublon_id)
    row.statut = "separes"
    row.decide_le = datetime.now(timezone.utc)
    await db.commit()
    return {"ok": True, "id": row.id, "statut": row.statut}


# ── Fiche ───────────────────────────────────────────────────────────


@router.get(
    "/dossiers/{dossier_id}",
    summary="Fiche d'un dossier : historique rencontre par rencontre, tâches, fusions",
)
async def lire_dossier(dossier_id: int, db: DBSession, user: CurrentUser) -> dict:
    await _garde(db, user)
    d = await _dossier_ou_404(db, dossier_id)
    out = await svc.detail(db, d)
    if d.fusionne_dans_id is not None:
        vivant = await svc.racine(db, d)
        out["fusionne_dans"] = {"id": vivant.id, "titre": vivant.titre}
    return out


_IDENTITE = ("titre", "entreprise_id", "contexte", "responsable")
_ETAT = ("statut", "dernier_etat", "prochaine_action", "echeance", "echeance_date")


@router.patch("/dossiers/{dossier_id}")
async def modifier_dossier(
    dossier_id: int, data: DossierUpdate, db: DBSession, user: CurrentUser
) -> dict:
    """Une correction à la main est RETENUE : l'IA ne réécrit plus un
    titre, un responsable, une entreprise ou un contexte saisis ici, et
    un état saisi ici tient jusqu'à la prochaine rencontre qui reparle
    du dossier. L'ancien titre devient un alias (rattachement)."""
    await _garde(db, user)
    d = await _dossier_ou_404(db, dossier_id)
    champs = data.model_dump(exclude_unset=True)
    if "statut" in champs:
        _statut_valide(champs["statut"])
        if champs["statut"] is None:
            champs.pop("statut")
    if "titre" in champs:
        if not champs["titre"] or not champs["titre"].strip():
            champs.pop("titre")
    manuels = svc._manuels(d)
    etat_touche = False
    for cle, val in champs.items():
        if isinstance(val, str):
            val = val.strip() or None
        if cle == "titre":
            if val != d.titre:
                ancien = d.titre
                d.titre = val
                svc._ajoute_alias(d, ancien)
                manuels.add("titre")
            continue
        if getattr(d, cle) == val:
            continue
        setattr(d, cle, val)
        if cle in _IDENTITE:
            manuels.add(cle)
        elif cle in _ETAT:
            etat_touche = True
    d.champs_manuels_json = json.dumps(sorted(manuels)) if manuels else None
    if etat_touche:
        d.etat_manuel_le = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(d)
    return await svc.detail(db, d)


@router.delete("/dossiers/{dossier_id}")
async def supprimer_dossier(
    dossier_id: int,
    db: DBSession,
    user: CurrentUser,
    retenir: bool = Query(
        default=True,
        description=(
            "Ajoute la consigne « ne pas suivre ce dossier » pour qu'il "
            "ne revienne pas à la prochaine analyse."
        ),
    ),
) -> dict:
    await _garde(db, user)
    d = await _dossier_ou_404(db, dossier_id)
    titre = d.titre
    source = d.source
    # Les dossiers fusionnés dans celui-ci partent avec lui.
    for e in await svc._absorbes(db, d):
        await svc.supprimer(db, e)
    await svc.supprimer(db, d)
    consigne_id = None
    if retenir and source == "ia":
        c = await consignes_svc.ajouter(
            db,
            texte=f"Ne pas suivre de dossier « {titre} » (retiré du tableau).",
            portee="dossiers",
            user_id=user.id,
        )
        consigne_id = c.id
    await db.commit()
    return {"ok": True, "consigne_id": consigne_id}


@router.post("/dossiers/{dossier_id}/fusionner")
async def fusionner_dossier(
    dossier_id: int, data: FusionnerIn, db: DBSession, user: CurrentUser
) -> dict:
    await _garde(db, user)
    perdant = await _dossier_ou_404(db, dossier_id)
    gagnant = await svc.racine(db, await _dossier_ou_404(db, data.dans_id))
    if perdant.fusionne_dans_id is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Ce dossier est déjà fusionné dans un autre."
        )
    if perdant.id == gagnant.id:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Un dossier ne peut pas être fusionné dans lui-même.",
        )
    await svc.fusionner(db, perdant, gagnant, auto=False, raison="Fusion à la main")
    await db.commit()
    return await svc.detail(db, gagnant)


@router.post("/dossiers/{dossier_id}/defusionner")
async def defusionner_dossier(
    dossier_id: int, db: DBSession, user: CurrentUser
) -> dict:
    await _garde(db, user)
    d = await _dossier_ou_404(db, dossier_id)
    if d.fusionne_dans_id is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Ce dossier n'est pas fusionné."
        )
    await svc.defusionner(db, d)
    await db.commit()
    return await svc.detail(db, d)


# ── Consignes ───────────────────────────────────────────────────────


def _portee_valide(v: str) -> str:
    if v not in PORTEES_CONSIGNE:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Portée inconnue : " + ", ".join(PORTEES_CONSIGNE) + ".",
        )
    return v


@router.get(
    "/consignes",
    summary=(
        "Consignes à Kratos : demandes de modification retenues et "
        "appliquées aux résumés, au tableau des dossiers et aux réponses"
    ),
)
async def lister_consignes(db: DBSession, user: CurrentUser) -> dict:
    await _garde(db, user)
    rows = (
        await db.execute(
            select(RencontreConsigne).order_by(RencontreConsigne.id.desc())
        )
    ).scalars().all()
    return {
        "consignes": [consignes_svc.public(c) for c in rows],
        "portees": [
            {"cle": "tout", "libelle": "Partout"},
            {"cle": "resumes", "libelle": "Résumés et rapports"},
            {"cle": "dossiers", "libelle": "Tableau des dossiers"},
        ],
    }


@router.post("/consignes", status_code=status.HTTP_201_CREATED)
async def ajouter_consigne(
    data: ConsigneCreate, db: DBSession, user: CurrentUser
) -> dict:
    await _garde(db, user)
    c = await consignes_svc.ajouter(
        db,
        texte=data.texte,
        portee=_portee_valide(data.portee),
        user_id=user.id,
    )
    await db.commit()
    await db.refresh(c)
    return consignes_svc.public(c)


async def _consigne_ou_404(db, consigne_id: int) -> RencontreConsigne:
    c = await db.get(RencontreConsigne, consigne_id)
    if c is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Consigne introuvable.")
    return c


@router.patch("/consignes/{consigne_id}")
async def modifier_consigne(
    consigne_id: int, data: ConsigneUpdate, db: DBSession, user: CurrentUser
) -> dict:
    await _garde(db, user)
    c = await _consigne_ou_404(db, consigne_id)
    if data.texte is not None:
        c.texte = data.texte.strip()
    if data.portee is not None:
        c.portee = _portee_valide(data.portee)
    if data.actif is not None:
        c.actif = data.actif
    await db.commit()
    await db.refresh(c)
    return consignes_svc.public(c)


@router.delete("/consignes/{consigne_id}")
async def supprimer_consigne(
    consigne_id: int, db: DBSession, user: CurrentUser
) -> dict:
    await _garde(db, user)
    c = await _consigne_ou_404(db, consigne_id)
    await db.delete(c)
    await db.commit()
    return {"ok": True}
