"""Relevés 31 (Revenu Québec) — page « Renouvellements & Relevés 31 ».

Obligation annuelle du locateur : produire un RL-31 pour chaque logement
OCCUPÉ au 31 décembre et en remettre copie au(x) locataire(s) avant le
dernier jour de FÉVRIER. Kratos ne produit pas le relevé officiel (ça se
fait dans le service en ligne de Revenu Québec) ; il fournit :

    GET   /immobilier/releves31?annee=AAAA   — la liste des logements
          occupés au 31 déc + locataire + données à saisir chez RQ,
          jointe au suivi (statut / numéro / copie PDF).
    PATCH /immobilier/releves31/{annee}/{logement_id}   — statut, numéro
          de relevé, notes (upsert).
    POST  /immobilier/releves31/{annee}/{logement_id}/pdf — téléverse la
          copie du relevé (→ ImmDocument type « releve31 », consultable
          et envoyable par courriel avec suivi d'ouverture).
"""

from __future__ import annotations

from datetime import date
from typing import List, Optional

from fastapi import APIRouter, File, HTTPException, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import CurrentUser, DBSession
from app.models.immobilier import (
    Bail,
    BailStatus,
    Immeuble,
    Locataire,
    Logement,
    LogementStatus,
    Releve31,
)

router = APIRouter(prefix="/immobilier", tags=["immobilier-releves31"])

_STATUTS = {"a_produire", "produit", "remis"}


def _require_volet(user: CurrentUser) -> None:
    volets = getattr(user, "volets", None)
    if volets is None or "immobilier" not in volets:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Volet « Gestion immobilière » non autorisé.",
        )


class Releve31Row(BaseModel):
    annee: int
    logement_id: int
    logement_numero: Optional[str] = None
    immeuble_id: Optional[int] = None
    immeuble_name: Optional[str] = None
    immeuble_adresse: Optional[str] = None
    bail_id: Optional[int] = None
    locataire_id: Optional[int] = None
    locataire_nom: Optional[str] = None
    locataire_email: Optional[str] = None
    # Assurance locataire : dernière confirmation (> 12 mois = à refaire).
    assurance_confirmee_le: Optional[date] = None
    loyer_31_dec: Optional[float] = None
    # Suivi
    statut: str = "a_produire"
    numero_releve: Optional[str] = None
    notes: Optional[str] = None
    document_id: Optional[int] = None


class Releve31Overview(BaseModel):
    annee: int
    echeance: date  # dernier jour de février de annee+1
    rows: List[Releve31Row] = []
    nb_a_produire: int = 0
    nb_produits: int = 0
    nb_remis: int = 0


class Releve31Update(BaseModel):
    statut: Optional[str] = Field(default=None, max_length=16)
    numero_releve: Optional[str] = Field(default=None, max_length=32)
    notes: Optional[str] = None


def _fin_fevrier(annee: int) -> date:
    """Dernier jour de février de ``annee + 1`` (échéance du RL-31)."""
    an = annee + 1
    bissextile = an % 4 == 0 and (an % 100 != 0 or an % 400 == 0)
    return date(an, 2, 29 if bissextile else 28)


async def _occupations_31_dec(db, annee: int) -> List[dict]:
    """Logements occupés au 31 décembre de ``annee`` : bail couvrant
    cette date (peu importe qu'il soit terminé depuis), immeubles actifs
    hors gestion externe (le gestionnaire tiers produit ses relevés)."""
    dec31 = date(annee, 12, 31)
    immeubles = {
        im.id: im
        for im in (
            await db.execute(
                select(Immeuble).where(
                    Immeuble.is_active.is_(True),
                    Immeuble.gestion_externe.isnot(True),
                )
            )
        ).scalars().all()
    }
    if not immeubles:
        return []
    logements = {
        lg.id: lg
        for lg in (
            await db.execute(
                select(Logement).where(
                    Logement.immeuble_id.in_(list(immeubles.keys())),
                    Logement.status != LogementStatus.HORS_LOC.value,
                )
            )
        ).scalars().all()
    }
    if not logements:
        return []
    baux = (
        await db.execute(
            select(Bail).where(
                Bail.logement_id.in_(list(logements.keys())),
                Bail.date_debut <= dec31,
                Bail.date_fin >= dec31,
                Bail.status != BailStatus.PROPOSE.value,
            ).order_by(Bail.date_debut.asc())
        )
    ).scalars().all()
    # Un bail par logement (le plus récent couvrant le 31 déc).
    bail_par_logement: dict[int, Bail] = {}
    for b in baux:
        bail_par_logement[b.logement_id] = b
    loc_ids = {b.locataire_id for b in bail_par_logement.values()}
    locataires = {}
    if loc_ids:
        for lo in (
            await db.execute(
                select(Locataire).where(Locataire.id.in_(list(loc_ids)))
            )
        ).scalars().all():
            locataires[lo.id] = lo

    out: List[dict] = []
    for lg_id, b in bail_par_logement.items():
        lg = logements[lg_id]
        im = immeubles.get(lg.immeuble_id)
        lo = locataires.get(b.locataire_id)
        out.append(
            {
                "logement": lg,
                "immeuble": im,
                "bail": b,
                "locataire": lo,
            }
        )
    out.sort(
        key=lambda o: (
            o["immeuble"].name if o["immeuble"] else "",
            str(o["logement"].numero or ""),
        )
    )
    return out


@router.get("/releves31", response_model=Releve31Overview)
async def releves31_overview(
    db: DBSession, user: CurrentUser, annee: Optional[int] = None
) -> Releve31Overview:
    _require_volet(user)
    today = date.today()
    # Année fiscale « en cours » : jusqu'à fin février on travaille
    # encore sur l'année précédente (échéance du RL-31).
    if annee is None:
        annee = today.year - 1 if today.month <= 2 else today.year
    occupations = await _occupations_31_dec(db, annee)

    suivis = {
        r.logement_id: r
        for r in (
            await db.execute(
                select(Releve31).where(Releve31.annee == annee)
            )
        ).scalars().all()
    }

    rows: List[Releve31Row] = []
    for o in occupations:
        lg, im, b, lo = (
            o["logement"], o["immeuble"], o["bail"], o["locataire"],
        )
        suivi = suivis.get(lg.id)
        rows.append(
            Releve31Row(
                annee=annee,
                logement_id=lg.id,
                logement_numero=lg.numero,
                immeuble_id=im.id if im else None,
                immeuble_name=im.name if im else None,
                immeuble_adresse=(
                    f"{im.address}, {im.city}" if im and im.city else
                    (im.address if im else None)
                ),
                bail_id=b.id,
                locataire_id=lo.id if lo else None,
                locataire_nom=lo.full_name if lo else None,
                locataire_email=lo.email if lo else None,
                assurance_confirmee_le=(
                    lo.assurance_confirmee_le if lo else None
                ),
                loyer_31_dec=float(b.loyer_mensuel or 0),
                statut=suivi.statut if suivi else "a_produire",
                numero_releve=suivi.numero_releve if suivi else None,
                notes=suivi.notes if suivi else None,
                document_id=suivi.document_id if suivi else None,
            )
        )
    return Releve31Overview(
        annee=annee,
        echeance=_fin_fevrier(annee),
        rows=rows,
        nb_a_produire=sum(1 for r in rows if r.statut == "a_produire"),
        nb_produits=sum(1 for r in rows if r.statut == "produit"),
        nb_remis=sum(1 for r in rows if r.statut == "remis"),
    )


async def _upsert(db, annee: int, logement_id: int) -> Releve31:
    obj = (
        await db.execute(
            select(Releve31).where(
                Releve31.annee == annee,
                Releve31.logement_id == logement_id,
            )
        )
    ).scalar_one_or_none()
    if obj is None:
        lg = await db.get(Logement, logement_id)
        if lg is None:
            raise HTTPException(
                status_code=404, detail="Logement introuvable."
            )
        obj = Releve31(
            annee=annee,
            logement_id=logement_id,
            immeuble_id=lg.immeuble_id,
        )
        db.add(obj)
        await db.flush()
    return obj


@router.patch(
    "/releves31/{annee}/{logement_id}", response_model=Releve31Row
)
async def update_releve31(
    annee: int,
    logement_id: int,
    payload: Releve31Update,
    db: DBSession,
    user: CurrentUser,
) -> Releve31Row:
    _require_volet(user)
    if payload.statut is not None and payload.statut not in _STATUTS:
        raise HTTPException(status_code=422, detail="Statut invalide.")
    obj = await _upsert(db, annee, logement_id)
    data = payload.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(obj, k, v)
    # Coller un numéro de relevé = il a été produit chez Revenu Québec.
    if data.get("numero_releve") and obj.statut == "a_produire":
        obj.statut = "produit"
    await db.commit()
    await db.refresh(obj)
    lg = await db.get(Logement, logement_id)
    return Releve31Row(
        annee=annee,
        logement_id=logement_id,
        logement_numero=lg.numero if lg else None,
        statut=obj.statut,
        numero_releve=obj.numero_releve,
        notes=obj.notes,
        document_id=obj.document_id,
    )


@router.post(
    "/releves31/{annee}/{logement_id}/pdf", response_model=Releve31Row
)
async def upload_releve31_pdf(
    annee: int,
    logement_id: int,
    db: DBSession,
    user: CurrentUser,
    file: UploadFile = File(...),
) -> Releve31Row:
    """Téléverse la copie PDF du relevé (émise par Revenu Québec) —
    conservée dans imm_documents (type « releve31 ») : visible dans la
    fiche du locataire/logement et envoyable par courriel avec suivi
    d'ouverture. Statut → « produit » (l'envoi le passera à « remis »)."""
    _require_volet(user)
    data = await file.read()
    if not data or not data[:5].startswith(b"%PDF-"):
        raise HTTPException(status_code=400, detail="Le fichier doit être un PDF.")
    if len(data) > 15_000_000:
        raise HTTPException(status_code=400, detail="PDF trop volumineux (max 15 Mo).")

    obj = await _upsert(db, annee, logement_id)

    # Bail/locataire couvrant le 31 décembre pour rattacher le document.
    dec31 = date(annee, 12, 31)
    bail = (
        await db.execute(
            select(Bail).where(
                Bail.logement_id == logement_id,
                Bail.date_debut <= dec31,
                Bail.date_fin >= dec31,
                Bail.status != BailStatus.PROPOSE.value,
            ).order_by(Bail.date_debut.desc())
        )
    ).scalars().first()

    from app.api.v1.endpoints.immobilier_documents import save_document

    doc = await save_document(
        db,
        bail_id=bail.id if bail else None,
        locataire_id=bail.locataire_id if bail else None,
        immeuble_id=obj.immeuble_id,
        doc_type="releve31",
        titre=f"Relevé 31 — {annee}",
        params={"annee": annee, "logement_id": logement_id},
        pdf=data,
        created_by_email=getattr(user, "email", None),
    )
    obj.document_id = doc.id
    obj.bail_id = bail.id if bail else None
    obj.locataire_id = bail.locataire_id if bail else None
    if obj.statut == "a_produire":
        obj.statut = "produit"
    await db.commit()
    await db.refresh(obj)
    return Releve31Row(
        annee=annee,
        logement_id=logement_id,
        statut=obj.statut,
        numero_releve=obj.numero_releve,
        notes=obj.notes,
        document_id=obj.document_id,
    )
