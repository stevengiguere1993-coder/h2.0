"""Gestion locative → Financement (Phil 2026-10-16) — routes.

Préfixe ``/immobilier/financement`` (volet Immobilier, gestionnaires) :

Rent roll et pièces d'un immeuble
- GET  /immeubles/{id}/rent-roll?fmt=json|pdf|xlsx|csv&inclure_paralleles=1&dossier_id=
- GET  /immeubles/{id}/documents             → pièces disponibles (sans PDF)
- GET  /immeubles/{id}/baux-paralleles       → baux parallèles (sous-location…)
- POST /baux-paralleles · PATCH /baux-paralleles/{bail_id}

Dossiers de financement
- GET  /dossiers?immeuble_id= · POST /dossiers · GET /dossiers/{id} · PATCH · DELETE
- POST /dossiers/{id}/pieces · POST /dossiers/{id}/pieces/defaut · PATCH /pieces/{id} · DELETE /pieces/{id}
- POST /dossiers/{id}/journal
- PUT  /dossiers/{id}/projection
- GET  /dossiers/{id}/rent-roll?fmt=         (réglages du dossier : parallèles, projection)
- GET  /dossiers/{id}/paquet.pdf?documents=1,2&rent_roll=1

Garde-fou : les montants exportés viennent des baux enregistrés ; la
projection est une colonne à part, marquée « estimation ».
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import CurrentUser, DBSession
from app.core.permissions import visible_immeuble_ids
from app.models.financement import (
    FINANCEMENT_STATUTS,
    FINANCEMENT_TYPES,
    JOURNAL_TYPES,
    PIECE_TYPES,
    Financement,
    FinancementJournal,
    FinancementPiece,
)
from app.models.immobilier import (
    BAIL_PARALLELE_TYPES,
    Bail,
    BailStatus,
    Immeuble,
    Locataire,
    Logement,
    est_bail_parallele,
)
from app.schemas.immobilier import BailCreate, BailRead
from app.services import financement as svc
from app.services.audit import log_action

log = logging.getLogger(__name__)

router = APIRouter(prefix="/immobilier/financement", tags=["immobilier-financement"])


def _require_volet(user: CurrentUser) -> None:
    volets = getattr(user, "volets", None)
    if volets is None or "immobilier" not in volets:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Volet « Immobilier » non autorisé.")


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _immeuble_ou_404(db, user, immeuble_id: int) -> Immeuble:
    im = await db.get(Immeuble, immeuble_id)
    if im is None:
        raise HTTPException(status_code=404, detail="Immeuble introuvable.")
    visibles = await visible_immeuble_ids(db, user)
    if visibles is not None and im.id not in visibles:
        raise HTTPException(status_code=403, detail="Immeuble non autorisé.")
    return im


async def _dossier_ou_404(db, user, dossier_id: int) -> Financement:
    fin = await db.get(Financement, dossier_id)
    if fin is None:
        raise HTTPException(status_code=404, detail="Dossier de financement introuvable.")
    await _immeuble_ou_404(db, user, fin.immeuble_id)
    return fin


async def _pieces(db, financement_id: int) -> list[FinancementPiece]:
    return (
        await db.execute(
            select(FinancementPiece).where(FinancementPiece.financement_id == financement_id)
            .order_by(FinancementPiece.ordre, FinancementPiece.id)
        )
    ).scalars().all()


def _fichier(contenu: bytes, media: str, nom: str) -> Response:
    return Response(
        content=contenu, media_type=media,
        headers={"Content-Disposition": f'attachment; filename="{nom}"', "Cache-Control": "no-store"},
    )


def _nom_sur(s: str) -> str:
    import re

    return re.sub(r"[^A-Za-z0-9_-]+", "-", s or "").strip("-")[:60] or "immeuble"


async def _reponse_rent_roll(rr: svc.RentRoll, fmt: str, *, preteur: Optional[str] = None) -> Any:
    fmt = (fmt or "json").lower()
    base = f"kratos_rent-roll_{_nom_sur(rr.immeuble['nom'])}_{rr.a_date.isoformat()}"
    if fmt == "json":
        return rr.as_dict()
    if fmt == "pdf":
        return _fichier(svc.rent_roll_pdf(rr, preteur=preteur), "application/pdf", f"{base}.pdf")
    colonnes, rows = svc.rent_roll_tableau(rr)
    from app.api.v1.endpoints.immobilier_exports import _csv_bytes, _xlsx_bytes

    if fmt == "xlsx":
        return _fichier(
            _xlsx_bytes(rows, colonnes, "Rent roll"),
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", f"{base}.xlsx",
        )
    if fmt == "csv":
        return _fichier(_csv_bytes(rows, colonnes), "text/csv; charset=utf-8", f"{base}.csv")
    raise HTTPException(status_code=400, detail="Format attendu : fmt=json, pdf, xlsx ou csv.")


# ─── Rent roll + pièces ───────────────────────────────────────────────


@router.get("/immeubles/{immeuble_id}/rent-roll", summary="Rent roll d'un immeuble (json, pdf, xlsx, csv)")
async def rent_roll_immeuble(
    immeuble_id: int, db: DBSession, user: CurrentUser,
    fmt: str = "json", inclure_standards: bool = True, inclure_paralleles: bool = True,
    dossier_id: Optional[int] = None, a_date: Optional[date] = None,
) -> Any:
    _require_volet(user)
    await _immeuble_ou_404(db, user, immeuble_id)
    projection = None
    preteur = None
    if dossier_id is not None:
        fin = await _dossier_ou_404(db, user, dossier_id)
        if fin.immeuble_id != immeuble_id:
            raise HTTPException(status_code=422, detail="Ce dossier n'est pas celui de cet immeuble.")
        inclure_standards = bool(fin.inclure_standards)
        inclure_paralleles = bool(fin.inclure_paralleles)
        projection = svc._charger_projection(fin.projection_json) if fin.projection_json else None
        preteur = fin.preteur
    if not inclure_standards and not inclure_paralleles:
        raise HTTPException(status_code=422, detail="Choisis au moins une catégorie de baux (standards ou parallèles).")
    try:
        rr = await svc.rent_roll(
            db, immeuble_id, inclure_standards=inclure_standards, inclure_paralleles=inclure_paralleles,
            projection=projection, a_date=a_date,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return await _reponse_rent_roll(rr, fmt, preteur=preteur)


@router.get("/immeubles/{immeuble_id}/documents", summary="Pièces de l'immeuble (sans le PDF)")
async def documents_immeuble(immeuble_id: int, db: DBSession, user: CurrentUser) -> Dict[str, Any]:
    _require_volet(user)
    await _immeuble_ou_404(db, user, immeuble_id)
    docs = await svc.documents_immeuble(db, immeuble_id)
    return {"items": docs, "total": len(docs)}


# ─── Baux parallèles ──────────────────────────────────────────────────


class LocataireInline(BaseModel):
    full_name: str = Field(..., min_length=2, max_length=255)
    email: Optional[str] = Field(default=None, max_length=320)
    phone: Optional[str] = Field(default=None, max_length=50)
    ancienne_adresse: Optional[str] = Field(default=None, max_length=500)
    date_naissance: Optional[date] = None


class BailParalleleIn(BaseModel):
    logement_id: int
    locataire_id: Optional[int] = None
    locataire: Optional[LocataireInline] = None
    parallele_type: str = Field(default="sous_location", max_length=24)
    parallele_locateur: str = Field(..., min_length=2, max_length=255)
    parallele_locateur_courriel: Optional[str] = Field(default=None, max_length=320)
    parallele_locateur_telephone: Optional[str] = Field(default=None, max_length=32)
    parallele_note: Optional[str] = None
    date_debut: date
    date_fin: date
    loyer_mensuel: float = Field(..., ge=0)
    depot_garantie: Optional[float] = Field(default=None, ge=0)
    chauffage_inclus: bool = False
    eau_chaude_inclus: bool = False
    electricite_inclus: bool = False
    internet_inclus: bool = False
    au_mois: Optional[bool] = None
    jour_echeance: int = 1
    #: « parallele » = déjà signé, en vigueur ; « propose » = à faire signer
    #: (bail officiel TAL + eSign, ou import du PDF signé).
    statut: str = Field(default="parallele", max_length=16)
    notes: Optional[str] = None


class BailParallelePatch(BaseModel):
    parallele_type: Optional[str] = Field(default=None, max_length=24)
    parallele_locateur: Optional[str] = Field(default=None, max_length=255)
    parallele_locateur_courriel: Optional[str] = Field(default=None, max_length=320)
    parallele_locateur_telephone: Optional[str] = Field(default=None, max_length=32)
    parallele_note: Optional[str] = None
    date_debut: Optional[date] = None
    date_fin: Optional[date] = None
    loyer_mensuel: Optional[float] = Field(default=None, ge=0)
    depot_garantie: Optional[float] = Field(default=None, ge=0)
    chauffage_inclus: Optional[bool] = None
    eau_chaude_inclus: Optional[bool] = None
    electricite_inclus: Optional[bool] = None
    internet_inclus: Optional[bool] = None
    au_mois: Optional[bool] = None
    jour_echeance: Optional[int] = None
    #: parallele | propose | termine | resilie
    statut: Optional[str] = Field(default=None, max_length=16)
    notes: Optional[str] = None


def _bail_parallele_out(b: Bail, lg: Optional[Logement], lo: Optional[Locataire]) -> Dict[str, Any]:
    d = BailRead.model_validate(b).model_dump(mode="json")
    d.update({
        "logement_numero": lg.numero if lg else None,
        "immeuble_id": lg.immeuble_id if lg else None,
        "locataire_nom": lo.full_name if lo else None,
        "locataire_email": lo.email if lo else None,
        "locataire_categorie": (getattr(lo, "categorie", None) or "standard") if lo else None,
        "type_label": svc.PARALLELE_TYPE_LABELS.get(b.parallele_type or "", b.parallele_type or ""),
        "en_vigueur": b.status == BailStatus.PARALLELE.value,
        "echu": bool(b.date_fin and b.date_fin < date.today() and not b.au_mois and b.status == BailStatus.PARALLELE.value),
    })
    return d


@router.get("/immeubles/{immeuble_id}/baux-paralleles", summary="Baux parallèles d'un immeuble")
async def lister_baux_paralleles(immeuble_id: int, db: DBSession, user: CurrentUser, inclure_termines: bool = False) -> Dict[str, Any]:
    _require_volet(user)
    await _immeuble_ou_404(db, user, immeuble_id)
    rows = (
        await db.execute(
            select(Bail, Logement).join(Logement, Logement.id == Bail.logement_id)
            .where(Logement.immeuble_id == immeuble_id, Bail.categorie == "parallele")
            .order_by(Bail.date_debut.desc(), Bail.id.desc())
        )
    ).all()
    loc_ids = {b.locataire_id for b, _ in rows if b.locataire_id}
    locs: dict[int, Locataire] = {}
    if loc_ids:
        for lo in (await db.execute(select(Locataire).where(Locataire.id.in_(loc_ids)))).scalars().all():
            locs[lo.id] = lo
    items = []
    for b, lg in rows:
        if not inclure_termines and b.status in (BailStatus.TERMINE.value, BailStatus.RESILIE.value):
            continue
        items.append(_bail_parallele_out(b, lg, locs.get(b.locataire_id)))
    return {"items": items, "total": len(items), "types": svc.PARALLELE_TYPE_LABELS}


@router.post("/baux-paralleles", summary="Créer un bail parallèle (sous-location, bail principal…)", status_code=201)
async def creer_bail_parallele(payload: BailParalleleIn, db: DBSession, user: CurrentUser) -> Dict[str, Any]:
    """Vrai contrat, vraies parties, vrai montant — hors du quotidien : il
    coexiste avec le bail standard de l'unité et n'entre dans aucun suivi
    (paiements, relances, renouvellements, dépôts, kanban)."""
    _require_volet(user)
    lg = await db.get(Logement, payload.logement_id)
    if lg is None:
        raise HTTPException(status_code=404, detail="Logement introuvable.")
    await _immeuble_ou_404(db, user, lg.immeuble_id)
    if payload.parallele_type not in BAIL_PARALLELE_TYPES:
        raise HTTPException(status_code=422, detail=f"Type de bail parallèle inconnu ({', '.join(BAIL_PARALLELE_TYPES)}).")
    if payload.statut not in (BailStatus.PARALLELE.value, BailStatus.PROPOSE.value):
        raise HTTPException(status_code=422, detail="Statut initial : « parallele » (en vigueur) ou « propose » (à signer).")
    if payload.date_fin <= payload.date_debut:
        raise HTTPException(status_code=422, detail="La fin du bail doit être après son début.")
    now = _now()
    if payload.locataire_id is not None:
        lo = await db.get(Locataire, payload.locataire_id)
        if lo is None:
            raise HTTPException(status_code=404, detail="Locataire introuvable.")
    elif payload.locataire is not None:
        lo = Locataire(
            full_name=payload.locataire.full_name.strip(), email=(payload.locataire.email or "").strip() or None,
            phone=(payload.locataire.phone or "").strip() or None,
            ancienne_adresse=(payload.locataire.ancienne_adresse or "").strip() or None,
            date_naissance=payload.locataire.date_naissance,
            # Occupant d'un bail parallèle : hors des listes du quotidien.
            categorie="parallele",
        )
        lo.created_at = now
        lo.updated_at = now
        db.add(lo)
        await db.flush()
    else:
        raise HTTPException(status_code=422, detail="Indique un locataire existant ou les coordonnées du nouvel occupant.")

    from app.api.v1.endpoints.immobilier import _creer_bail

    bail_payload = BailCreate(
        logement_id=lg.id, locataire_id=lo.id, date_debut=payload.date_debut, date_fin=payload.date_fin,
        loyer_mensuel=payload.loyer_mensuel, depot_garantie=payload.depot_garantie,
        chauffage_inclus=payload.chauffage_inclus, eau_chaude_inclus=payload.eau_chaude_inclus,
        electricite_inclus=payload.electricite_inclus, internet_inclus=payload.internet_inclus,
        status=payload.statut, notes=payload.notes, au_mois=payload.au_mois, jour_echeance=payload.jour_echeance or 1,
        categorie="parallele", parallele_type=payload.parallele_type,
        parallele_locateur=payload.parallele_locateur.strip(),
        parallele_locateur_courriel=(payload.parallele_locateur_courriel or "").strip() or None,
        parallele_locateur_telephone=(payload.parallele_locateur_telephone or "").strip() or None,
        parallele_note=payload.parallele_note,
    )
    bail = await _creer_bail(db, bail_payload, lg, user, relocation_facturable=False)
    await log_action(
        db, user=user, action="financement.bail_parallele_cree", entity_type="baux", entity_id=bail.id,
        details={"logement_id": lg.id, "locataire_id": lo.id, "type": payload.parallele_type,
                 "locateur": payload.parallele_locateur, "statut": payload.statut, "loyer": payload.loyer_mensuel},
    )
    await db.commit()
    await db.refresh(bail)
    return _bail_parallele_out(bail, lg, lo)


@router.patch("/baux-paralleles/{bail_id}", summary="Modifier un bail parallèle")
async def modifier_bail_parallele(bail_id: int, payload: BailParallelePatch, db: DBSession, user: CurrentUser) -> Dict[str, Any]:
    _require_volet(user)
    bail = await db.get(Bail, bail_id)
    if bail is None or not est_bail_parallele(bail):
        raise HTTPException(status_code=404, detail="Bail parallèle introuvable.")
    lg = await db.get(Logement, bail.logement_id)
    if lg is not None:
        await _immeuble_ou_404(db, user, lg.immeuble_id)
    data = payload.model_dump(exclude_unset=True)
    statut = data.pop("statut", None)
    if "parallele_type" in data and data["parallele_type"] not in BAIL_PARALLELE_TYPES:
        raise HTTPException(status_code=422, detail="Type de bail parallèle inconnu.")
    if data.get("jour_echeance") is None:
        data.pop("jour_echeance", None)
    for k, v in data.items():
        setattr(bail, k, v)
    if bail.date_fin and bail.date_debut and bail.date_fin <= bail.date_debut:
        raise HTTPException(status_code=422, detail="La fin du bail doit être après son début.")
    if statut is not None:
        if statut == BailStatus.ACTIF.value:
            statut = BailStatus.PARALLELE.value
        if statut not in (BailStatus.PARALLELE.value, BailStatus.PROPOSE.value, BailStatus.TERMINE.value, BailStatus.RESILIE.value):
            raise HTTPException(status_code=422, detail="Statut : parallele, propose, termine ou resilie.")
        bail.status = statut
    bail.updated_at = _now()
    await db.flush()
    from app.services.locatif_depart import recaler_statut_logement

    await recaler_statut_logement(db, bail.logement_id)
    await log_action(db, user=user, action="financement.bail_parallele_modifie", entity_type="baux", entity_id=bail.id,
                     details={**{k: (str(v) if isinstance(v, date) else v) for k, v in data.items()}, "statut": statut})
    await db.commit()
    await db.refresh(bail)
    lo = await db.get(Locataire, bail.locataire_id) if bail.locataire_id else None
    return _bail_parallele_out(bail, lg, lo)


# ─── Dossiers ─────────────────────────────────────────────────────────


class DossierIn(BaseModel):
    immeuble_id: int
    titre: Optional[str] = Field(default=None, max_length=255)
    type: str = Field(default="refinancement", max_length=24)
    preteur: Optional[str] = Field(default=None, max_length=255)
    courtier: Optional[str] = Field(default=None, max_length=255)
    hypotheque_id: Optional[int] = None
    montant_demande: Optional[float] = Field(default=None, ge=0)
    taux_pct: Optional[float] = Field(default=None, ge=0, le=100)
    terme_mois: Optional[int] = Field(default=None, ge=1, le=600)
    amortissement_mois: Optional[int] = Field(default=None, ge=1, le=600)
    date_depot: Optional[date] = None
    date_echeance: Optional[date] = None
    inclure_standards: bool = True
    inclure_paralleles: bool = True
    notes: Optional[str] = None
    #: Créer la checklist standard du type de dossier.
    pieces_defaut: bool = True


class DossierPatch(BaseModel):
    titre: Optional[str] = Field(default=None, max_length=255)
    type: Optional[str] = Field(default=None, max_length=24)
    preteur: Optional[str] = Field(default=None, max_length=255)
    courtier: Optional[str] = Field(default=None, max_length=255)
    hypotheque_id: Optional[int] = None
    montant_demande: Optional[float] = Field(default=None, ge=0)
    taux_pct: Optional[float] = Field(default=None, ge=0, le=100)
    terme_mois: Optional[int] = Field(default=None, ge=1, le=600)
    amortissement_mois: Optional[int] = Field(default=None, ge=1, le=600)
    statut: Optional[str] = Field(default=None, max_length=16)
    date_depot: Optional[date] = None
    date_reponse: Optional[date] = None
    date_echeance: Optional[date] = None
    inclure_standards: Optional[bool] = None
    inclure_paralleles: Optional[bool] = None
    notes: Optional[str] = None


class PieceIn(BaseModel):
    type: str = Field(default="autre", max_length=32)
    libelle: str = Field(..., min_length=1, max_length=255)
    requis: bool = True
    document_id: Optional[int] = None
    notes: Optional[str] = None


class PiecePatch(BaseModel):
    type: Optional[str] = Field(default=None, max_length=32)
    libelle: Optional[str] = Field(default=None, max_length=255)
    requis: Optional[bool] = None
    ordre: Optional[int] = None
    document_id: Optional[int] = None
    envoye: Optional[bool] = None
    notes: Optional[str] = None


class JournalIn(BaseModel):
    type: str = Field(default="note", max_length=16)
    texte: str = Field(..., min_length=1)


class ProjectionIn(BaseModel):
    logements: Dict[str, Any] = Field(default_factory=dict)
    hypotheses: Dict[str, Any] = Field(default_factory=dict)


async def _detail(db, user, fin: Financement) -> Dict[str, Any]:
    pieces = await _pieces(db, fin.id)
    journal = (
        await db.execute(
            select(FinancementJournal).where(FinancementJournal.financement_id == fin.id)
            .order_by(FinancementJournal.created_at.desc(), FinancementJournal.id.desc())
        )
    ).scalars().all()
    projection = svc._charger_projection(fin.projection_json) if fin.projection_json else None
    rr = await svc.rent_roll(
        db, fin.immeuble_id, inclure_standards=bool(fin.inclure_standards),
        inclure_paralleles=bool(fin.inclure_paralleles), projection=projection,
    )
    im = await db.get(Immeuble, fin.immeuble_id)
    return {
        **svc.resume_financement(fin, pieces=pieces),
        "immeuble_nom": im.name if im else None,
        "pieces": [svc.resume_piece(p) for p in pieces],
        "journal": [svc.resume_journal(j) for j in journal],
        "tableau_de_bord": await svc.tableau_de_bord(db, fin, rr, pieces),
        "rent_roll": rr.as_dict(),
        "types": list(FINANCEMENT_TYPES),
        "statuts": list(FINANCEMENT_STATUTS),
        "types_pieces": list(PIECE_TYPES),
    }


@router.get("/dossiers", summary="Dossiers de financement")
async def lister_dossiers(db: DBSession, user: CurrentUser, immeuble_id: Optional[int] = None, statut: Optional[str] = None) -> Dict[str, Any]:
    _require_volet(user)
    q = select(Financement).order_by(Financement.updated_at.desc(), Financement.id.desc())
    if immeuble_id is not None:
        await _immeuble_ou_404(db, user, immeuble_id)
        q = q.where(Financement.immeuble_id == immeuble_id)
    if statut:
        q = q.where(Financement.statut == statut)
    rows = (await db.execute(q)).scalars().all()
    visibles = await visible_immeuble_ids(db, user)
    if visibles is not None:
        rows = [r for r in rows if r.immeuble_id in visibles]
    noms: dict[int, str] = {}
    imm_ids = {r.immeuble_id for r in rows}
    if imm_ids:
        for im in (await db.execute(select(Immeuble).where(Immeuble.id.in_(imm_ids)))).scalars().all():
            noms[im.id] = im.name
    pieces_par_dossier: dict[int, list[FinancementPiece]] = {}
    if rows:
        for p in (
            await db.execute(select(FinancementPiece).where(FinancementPiece.financement_id.in_([r.id for r in rows])))
        ).scalars().all():
            pieces_par_dossier.setdefault(p.financement_id, []).append(p)
    items = []
    for r in rows:
        d = svc.resume_financement(r, pieces=pieces_par_dossier.get(r.id, []))
        d["immeuble_nom"] = noms.get(r.immeuble_id)
        items.append(d)
    return {"items": items, "total": len(items), "types": list(FINANCEMENT_TYPES), "statuts": list(FINANCEMENT_STATUTS)}


@router.post("/dossiers", summary="Ouvrir un dossier de financement", status_code=201)
async def creer_dossier(payload: DossierIn, db: DBSession, user: CurrentUser) -> Dict[str, Any]:
    _require_volet(user)
    im = await _immeuble_ou_404(db, user, payload.immeuble_id)
    if payload.type not in FINANCEMENT_TYPES:
        raise HTTPException(status_code=422, detail=f"Type de dossier inconnu ({', '.join(FINANCEMENT_TYPES)}).")
    titre = (payload.titre or "").strip() or f"{payload.type.capitalize()} — {im.name}{' — ' + payload.preteur if payload.preteur else ''}"
    fin = Financement(
        immeuble_id=im.id, hypotheque_id=payload.hypotheque_id, titre=titre[:255], type=payload.type,
        preteur=(payload.preteur or "").strip() or None, courtier=(payload.courtier or "").strip() or None,
        montant_demande=payload.montant_demande, taux_pct=payload.taux_pct, terme_mois=payload.terme_mois,
        amortissement_mois=payload.amortissement_mois, date_depot=payload.date_depot, date_echeance=payload.date_echeance,
        inclure_standards=payload.inclure_standards, inclure_paralleles=payload.inclure_paralleles,
        notes=payload.notes, created_by_email=getattr(user, "email", None),
    )
    fin.created_at = _now()
    fin.updated_at = _now()
    db.add(fin)
    await db.flush()
    if payload.pieces_defaut:
        rr = await svc.rent_roll(db, im.id, inclure_paralleles=payload.inclure_paralleles)
        for p in svc.pieces_defaut(payload.type, avec_paralleles=bool(rr.paralleles) and payload.inclure_paralleles):
            db.add(FinancementPiece(financement_id=fin.id, **p))
        # Projection de départ = les loyers des baux (source « bail »).
        fin.projection_json = json.dumps(svc.projection_defaut(rr), ensure_ascii=False)
    db.add(FinancementJournal(financement_id=fin.id, type="statut", texte="Dossier ouvert (préparation).", auteur_email=getattr(user, "email", None)))
    await log_action(db, user=user, action="financement.dossier_cree", entity_type="imm_financement", entity_id=fin.id,
                     details={"immeuble_id": im.id, "type": payload.type, "preteur": payload.preteur, "montant": payload.montant_demande})
    await db.commit()
    await db.refresh(fin)
    return await _detail(db, user, fin)


@router.get("/dossiers/{dossier_id}", summary="Détail d'un dossier (pièces, journal, tableau de bord, rent roll)")
async def lire_dossier(dossier_id: int, db: DBSession, user: CurrentUser) -> Dict[str, Any]:
    _require_volet(user)
    fin = await _dossier_ou_404(db, user, dossier_id)
    return await _detail(db, user, fin)


@router.patch("/dossiers/{dossier_id}", summary="Modifier un dossier (statut, prêteur, montants, dates)")
async def modifier_dossier(dossier_id: int, payload: DossierPatch, db: DBSession, user: CurrentUser) -> Dict[str, Any]:
    _require_volet(user)
    fin = await _dossier_ou_404(db, user, dossier_id)
    data = payload.model_dump(exclude_unset=True)
    if "type" in data and data["type"] not in FINANCEMENT_TYPES:
        raise HTTPException(status_code=422, detail="Type de dossier inconnu.")
    ancien_statut = fin.statut
    if "statut" in data:
        if data["statut"] not in FINANCEMENT_STATUTS:
            raise HTTPException(status_code=422, detail=f"Statut inconnu ({', '.join(FINANCEMENT_STATUTS)}).")
        if data["statut"] == "envoye" and fin.date_depot is None and "date_depot" not in data:
            data["date_depot"] = date.today()
        if data["statut"] in ("approuve", "refuse") and fin.date_reponse is None and "date_reponse" not in data:
            data["date_reponse"] = date.today()
    for k, v in data.items():
        setattr(fin, k, v)
    fin.updated_at = _now()
    if "statut" in data and data["statut"] != ancien_statut:
        db.add(FinancementJournal(financement_id=fin.id, type="statut", texte=f"Statut : {ancien_statut} → {data['statut']}.", auteur_email=getattr(user, "email", None)))
    await log_action(db, user=user, action="financement.dossier_modifie", entity_type="imm_financement", entity_id=fin.id,
                     details={k: (str(v) if isinstance(v, date) else v) for k, v in data.items()})
    await db.commit()
    await db.refresh(fin)
    return await _detail(db, user, fin)


@router.delete("/dossiers/{dossier_id}", summary="Supprimer un dossier", status_code=204)
async def supprimer_dossier(dossier_id: int, db: DBSession, user: CurrentUser) -> Response:
    _require_volet(user)
    fin = await _dossier_ou_404(db, user, dossier_id)
    await log_action(db, user=user, action="financement.dossier_supprime", entity_type="imm_financement", entity_id=fin.id,
                     details={"titre": fin.titre, "statut": fin.statut})
    await db.delete(fin)
    await db.commit()
    return Response(status_code=204)


# ─── Pièces ───────────────────────────────────────────────────────────


@router.post("/dossiers/{dossier_id}/pieces", summary="Ajouter une pièce à la checklist", status_code=201)
async def ajouter_piece(dossier_id: int, payload: PieceIn, db: DBSession, user: CurrentUser) -> Dict[str, Any]:
    _require_volet(user)
    fin = await _dossier_ou_404(db, user, dossier_id)
    if payload.type not in PIECE_TYPES:
        raise HTTPException(status_code=422, detail=f"Type de pièce inconnu ({', '.join(PIECE_TYPES)}).")
    if payload.document_id is not None:
        permis = {d["id"] for d in await svc.documents_immeuble(db, fin.immeuble_id)}
        if payload.document_id not in permis:
            raise HTTPException(status_code=422, detail="Ce document n'appartient pas à cet immeuble.")
    existantes = await _pieces(db, fin.id)
    p = FinancementPiece(
        financement_id=fin.id, type=payload.type, libelle=payload.libelle.strip(), requis=payload.requis,
        ordre=(max([x.ordre for x in existantes], default=-1) + 1), document_id=payload.document_id, notes=payload.notes,
    )
    p.created_at = _now()
    p.updated_at = _now()
    db.add(p)
    fin.updated_at = _now()
    await db.commit()
    await db.refresh(p)
    return svc.resume_piece(p)


@router.post("/dossiers/{dossier_id}/pieces/defaut", summary="(Re)créer la checklist standard du type de dossier")
async def pieces_defaut(dossier_id: int, db: DBSession, user: CurrentUser) -> Dict[str, Any]:
    _require_volet(user)
    fin = await _dossier_ou_404(db, user, dossier_id)
    existantes = {(p.type, p.libelle) for p in await _pieces(db, fin.id)}
    rr = await svc.rent_roll(db, fin.immeuble_id, inclure_paralleles=bool(fin.inclure_paralleles))
    ajoutees = 0
    for p in svc.pieces_defaut(fin.type, avec_paralleles=bool(rr.paralleles) and bool(fin.inclure_paralleles)):
        if (p["type"], p["libelle"]) in existantes:
            continue
        db.add(FinancementPiece(financement_id=fin.id, **p))
        ajoutees += 1
    await db.commit()
    return {"ajoutees": ajoutees, "pieces": [svc.resume_piece(p) for p in await _pieces(db, fin.id)]}


@router.patch("/pieces/{piece_id}", summary="Modifier une pièce (fournie, envoyée, document)")
async def modifier_piece(piece_id: int, payload: PiecePatch, db: DBSession, user: CurrentUser) -> Dict[str, Any]:
    _require_volet(user)
    p = await db.get(FinancementPiece, piece_id)
    if p is None:
        raise HTTPException(status_code=404, detail="Pièce introuvable.")
    fin = await _dossier_ou_404(db, user, p.financement_id)
    data = payload.model_dump(exclude_unset=True)
    envoye = data.pop("envoye", None)
    if "type" in data and data["type"] not in PIECE_TYPES:
        raise HTTPException(status_code=422, detail="Type de pièce inconnu.")
    if data.get("document_id") is not None:
        permis = {d["id"] for d in await svc.documents_immeuble(db, fin.immeuble_id)}
        if data["document_id"] not in permis:
            raise HTTPException(status_code=422, detail="Ce document n'appartient pas à cet immeuble.")
    for k, v in data.items():
        setattr(p, k, v)
    if envoye is not None:
        p.envoye_le = _now() if envoye else None
    p.updated_at = _now()
    fin.updated_at = _now()
    await db.commit()
    await db.refresh(p)
    return svc.resume_piece(p)


@router.delete("/pieces/{piece_id}", summary="Retirer une pièce", status_code=204)
async def supprimer_piece(piece_id: int, db: DBSession, user: CurrentUser) -> Response:
    _require_volet(user)
    p = await db.get(FinancementPiece, piece_id)
    if p is None:
        raise HTTPException(status_code=404, detail="Pièce introuvable.")
    await _dossier_ou_404(db, user, p.financement_id)
    await db.delete(p)
    await db.commit()
    return Response(status_code=204)


# ─── Journal, projection, exports du dossier ─────────────────────────


@router.post("/dossiers/{dossier_id}/journal", summary="Ajouter une entrée au journal", status_code=201)
async def ajouter_journal(dossier_id: int, payload: JournalIn, db: DBSession, user: CurrentUser) -> Dict[str, Any]:
    _require_volet(user)
    fin = await _dossier_ou_404(db, user, dossier_id)
    if payload.type not in JOURNAL_TYPES:
        raise HTTPException(status_code=422, detail=f"Type inconnu ({', '.join(JOURNAL_TYPES)}).")
    j = FinancementJournal(financement_id=fin.id, type=payload.type, texte=payload.texte.strip(), auteur_email=getattr(user, "email", None))
    db.add(j)
    fin.updated_at = _now()
    await db.commit()
    await db.refresh(j)
    return svc.resume_journal(j)


@router.put("/dossiers/{dossier_id}/projection", summary="Enregistrer la projection pro forma (estimation)")
async def enregistrer_projection(dossier_id: int, payload: ProjectionIn, db: DBSession, user: CurrentUser) -> Dict[str, Any]:
    _require_volet(user)
    fin = await _dossier_ou_404(db, user, dossier_id)
    logs: Dict[str, Any] = {}
    for k, v in (payload.logements or {}).items():
        if not isinstance(v, dict):
            continue
        try:
            loyer = round(float(v.get("loyer")), 2) if v.get("loyer") not in (None, "") else None
        except (TypeError, ValueError):
            raise HTTPException(status_code=422, detail=f"Loyer projeté invalide pour le logement {k}.")
        if loyer is not None and loyer < 0:
            raise HTTPException(status_code=422, detail="Un loyer projeté ne peut pas être négatif.")
        logs[str(k)] = {"loyer": loyer, "source": str(v.get("source") or "manuel")[:24], "note": (str(v.get("note") or "")[:255] or None)}
    hyp = {}
    try:
        vac = payload.hypotheses.get("vacance_pct")
        hyp["vacance_pct"] = max(0.0, min(100.0, float(vac))) if vac not in (None, "") else 0.0
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail="Taux de vacance invalide.")
    fin.projection_json = json.dumps({"logements": logs, "hypotheses": hyp}, ensure_ascii=False)
    fin.updated_at = _now()
    await log_action(db, user=user, action="financement.projection", entity_type="imm_financement", entity_id=fin.id,
                     details={"nb_logements": len(logs), "vacance_pct": hyp.get("vacance_pct")})
    await db.commit()
    await db.refresh(fin)
    return await _detail(db, user, fin)


@router.get("/dossiers/{dossier_id}/rent-roll", summary="Rent roll du dossier (réglages du dossier)")
async def rent_roll_dossier(dossier_id: int, db: DBSession, user: CurrentUser, fmt: str = "json", projection: bool = True) -> Any:
    _require_volet(user)
    fin = await _dossier_ou_404(db, user, dossier_id)
    proj = svc._charger_projection(fin.projection_json) if (projection and fin.projection_json) else None
    rr = await svc.rent_roll(
        db, fin.immeuble_id, inclure_standards=bool(fin.inclure_standards),
        inclure_paralleles=bool(fin.inclure_paralleles), projection=proj,
    )
    return await _reponse_rent_roll(rr, fmt, preteur=fin.preteur)


@router.get("/dossiers/{dossier_id}/paquet.pdf", summary="Paquet PDF : rent roll + pièces choisies")
async def paquet_dossier(
    dossier_id: int, db: DBSession, user: CurrentUser,
    documents: str = Query(default="", description="Identifiants de documents séparés par des virgules, dans l'ordre"),
    rent_roll: bool = True, projection: bool = False,
) -> Response:
    _require_volet(user)
    fin = await _dossier_ou_404(db, user, dossier_id)
    ids: List[int] = []
    for part in (documents or "").split(","):
        part = part.strip()
        if part:
            try:
                ids.append(int(part))
            except ValueError:
                raise HTTPException(status_code=422, detail=f"Identifiant de document invalide : {part}")
    en_tete = None
    if rent_roll:
        proj = svc._charger_projection(fin.projection_json) if (projection and fin.projection_json) else None
        rr = await svc.rent_roll(
            db, fin.immeuble_id, inclure_standards=bool(fin.inclure_standards),
            inclure_paralleles=bool(fin.inclure_paralleles), projection=proj,
        )
        en_tete = svc.rent_roll_pdf(rr, preteur=fin.preteur)
    if not ids and en_tete is None:
        raise HTTPException(status_code=422, detail="Choisis au moins une pièce ou le rent roll.")
    pdf, rapport = await svc.paquet_pdf(db, fin.immeuble_id, ids, en_tete_pdf=en_tete)
    if not pdf or pdf[:5] != b"%PDF-":
        raise HTTPException(status_code=422, detail="Aucune pièce PDF lisible dans la sélection.")
    await log_action(db, user=user, action="financement.paquet_genere", entity_type="imm_financement", entity_id=fin.id,
                     details={"documents": ids, "rent_roll": rent_roll, "projection": projection, "rapport": rapport})
    await db.commit()
    im = await db.get(Immeuble, fin.immeuble_id)
    nom = f"kratos_dossier-financement_{_nom_sur(im.name if im else str(fin.immeuble_id))}_{date.today().isoformat()}.pdf"
    r = _fichier(pdf, "application/pdf", nom)
    r.headers["X-Kratos-Paquet"] = json.dumps(rapport, ensure_ascii=False)[:1500]
    return r
