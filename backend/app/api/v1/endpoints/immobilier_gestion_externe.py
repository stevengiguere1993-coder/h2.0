"""Suivi d'un immeuble en GESTION EXTERNE (retour Phil 2026-07-22).

La compagnie de gestion perçoit les loyers et refacture les travaux ;
Kratos garde un miroir de leur rapport :

    Paiements PAR LOGEMENT (pas de locataire connu) :
      GET    /immobilier/immeubles/{id}/paiements-externes?mois=YYYY-MM
      POST   /immobilier/paiements-externes {logement_id, mois, montant?}
      DELETE /immobilier/paiements-externes/{logement_id}?mois=YYYY-MM

    FACTURES PONCTUELLES (ex. 350 $ de plomberie pour l'app. 3 — jamais
    récurrentes, rattachées optionnellement à un logement) :
      GET    /immobilier/immeubles/{id}/factures-externes?annee=AAAA
      POST   /immobilier/immeubles/{id}/factures-externes
      PUT    /immobilier/factures-externes/{id}
      DELETE /immobilier/factures-externes/{id}
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import CurrentUser, DBSession
from app.models.immobilier import (
    Bail,
    BailStatus,
    FactureExterne,
    Logement,
    PaiementExterne,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/immobilier", tags=["immobilier-gestion-externe"])


def _require_volet(user: CurrentUser) -> None:
    volets = getattr(user, "volets", None)
    if volets is None or "immobilier" not in volets:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Volet « Gestion immobilière » non autorisé.",
        )


def _parse_mois(mois: str) -> date:
    try:
        return datetime.strptime(mois + "-01", "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(
            status_code=400, detail="Format mois attendu : YYYY-MM."
        )


# ─── Paiements par logement ────────────────────────────────────────────


class PaiementExterneRow(BaseModel):
    logement_id: int
    logement_numero: str
    logement_status: str
    loyer_attendu: Optional[float] = None
    paye: bool = False
    # "paye" | "partiel" | "a_confirmer" | "aucun" (rien attendu — vacant…)
    etat: str = "aucun"
    #: CUMUL des montants reçus pour le mois (paiements partiels
    #: possibles — retour Phil 2026-07-22).
    montant: Optional[float] = None
    paye_le: Optional[date] = None


class PaiementExterneOverview(BaseModel):
    mois: str
    rows: List[PaiementExterneRow] = []
    total_attendu: float = 0.0
    total_recu: float = 0.0
    nb_payes: int = 0
    nb_impayes: int = 0


@router.get(
    "/immeubles/{immeuble_id}/paiements-externes",
    response_model=PaiementExterneOverview,
)
async def paiements_externes_overview(
    immeuble_id: int,
    db: DBSession,
    user: CurrentUser,
    mois: Optional[str] = None,
) -> PaiementExterneOverview:
    _require_volet(user)
    month_start = (
        _parse_mois(mois)
        if mois
        else datetime.now(timezone.utc).date().replace(day=1)
    )
    logements = (
        await db.execute(
            select(Logement).where(Logement.immeuble_id == immeuble_id)
        )
    ).scalars().all()
    log_ids = [lg.id for lg in logements]

    # Loyer attendu par logement : bail actif si présent (il peut y en
    # avoir même en gestion externe), sinon loyer demandé si occupé.
    loyer_par_logement: dict[int, Optional[float]] = {}
    if log_ids:
        for b in (
            await db.execute(
                select(Bail).where(
                    Bail.logement_id.in_(log_ids),
                    Bail.status == BailStatus.ACTIF.value,
                )
            )
        ).scalars().all():
            loyer_par_logement[b.logement_id] = float(b.loyer_mensuel or 0)
    for lg in logements:
        if lg.id not in loyer_par_logement:
            loyer_par_logement[lg.id] = (
                float(lg.loyer_demande)
                if lg.status == "occupe" and lg.loyer_demande is not None
                else None
            )

    paiements: dict[int, PaiementExterne] = {}
    if log_ids:
        for p in (
            await db.execute(
                select(PaiementExterne).where(
                    PaiementExterne.logement_id.in_(log_ids),
                    PaiementExterne.mois_couvert == month_start,
                )
            )
        ).scalars().all():
            paiements[p.logement_id] = p

    rows: List[PaiementExterneRow] = []
    total_attendu = total_recu = 0.0
    nb_payes = nb_impayes = 0
    for lg in sorted(logements, key=lambda x: x.numero or ""):
        attendu = loyer_par_logement.get(lg.id)
        p = paiements.get(lg.id)
        recu = (
            float(p.montant)
            if p is not None and p.montant is not None
            else ((attendu or 0.0) if p is not None else 0.0)
        )
        if attendu:
            total_attendu += attendu
        total_recu += recu
        # État : cumul reçu vs attendu (partiels possibles).
        if p is not None and (attendu is None or recu >= attendu - 0.005):
            etat = "paye"
            nb_payes += 1
        elif p is not None:
            etat = "partiel"
            nb_impayes += 1
        elif attendu:
            etat = "a_confirmer"
            nb_impayes += 1
        else:
            etat = "aucun"
        rows.append(
            PaiementExterneRow(
                logement_id=lg.id,
                logement_numero=lg.numero,
                logement_status=lg.status,
                loyer_attendu=attendu,
                paye=etat == "paye",
                etat=etat,
                montant=round(recu, 2) if p is not None else None,
                paye_le=p.paye_le if p is not None else None,
            )
        )
    # Impayés en premier, partiels ensuite, payés en bas.
    ordre = {"a_confirmer": 0, "partiel": 1, "paye": 2, "aucun": 3}
    rows.sort(
        key=lambda r: (ordre.get(r.etat, 9), r.logement_numero or "")
    )
    return PaiementExterneOverview(
        mois=month_start.strftime("%Y-%m"),
        rows=rows,
        total_attendu=round(total_attendu, 2),
        total_recu=round(total_recu, 2),
        nb_payes=nb_payes,
        nb_impayes=nb_impayes,
    )


class PaiementExterneCreate(BaseModel):
    logement_id: int
    mois: str
    montant: Optional[float] = Field(default=None, ge=0)


@router.post(
    "/paiements-externes",
    response_model=PaiementExterneRow,
    status_code=status.HTTP_201_CREATED,
)
async def marquer_paiement_externe(
    payload: PaiementExterneCreate, db: DBSession, user: CurrentUser
) -> PaiementExterneRow:
    """Enregistre un montant reçu — s'AJOUTE au cumul du mois (paiements
    partiels possibles). Sans montant : le mois est réputé payé au
    complet (loyer attendu)."""
    _require_volet(user)
    month_start = _parse_mois(payload.mois)
    lg = await db.get(Logement, payload.logement_id)
    if lg is None:
        raise HTTPException(status_code=404, detail="Logement introuvable.")
    existing = (
        await db.execute(
            select(PaiementExterne).where(
                PaiementExterne.logement_id == lg.id,
                PaiementExterne.mois_couvert == month_start,
            )
        )
    ).scalars().first()
    today = date.today()
    if existing is None:
        existing = PaiementExterne(
            logement_id=lg.id,
            mois_couvert=month_start,
            created_by_email=getattr(user, "email", None),
            created_at=datetime.now(timezone.utc),
        )
        db.add(existing)
    if payload.montant is not None:
        existing.montant = round(
            float(existing.montant or 0) + payload.montant, 2
        )
    else:
        existing.montant = None  # payé au complet (= loyer attendu)
    existing.paye_le = today
    await db.commit()
    return PaiementExterneRow(
        logement_id=lg.id,
        logement_numero=lg.numero,
        logement_status=lg.status,
        loyer_attendu=None,
        paye=True,
        etat="paye",
        montant=(
            float(existing.montant)
            if existing.montant is not None
            else None
        ),
        paye_le=today,
    )


@router.delete(
    "/paiements-externes/{logement_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def annuler_paiement_externe(
    logement_id: int, mois: str, db: DBSession, user: CurrentUser
) -> None:
    """Erreur de saisie : le mois redevient impayé pour ce logement."""
    _require_volet(user)
    month_start = _parse_mois(mois)
    rows = (
        await db.execute(
            select(PaiementExterne).where(
                PaiementExterne.logement_id == logement_id,
                PaiementExterne.mois_couvert == month_start,
            )
        )
    ).scalars().all()
    for r in rows:
        await db.delete(r)
    await db.commit()


# ─── Factures ponctuelles ──────────────────────────────────────────────


class FactureExterneRead(BaseModel):
    id: int
    immeuble_id: int
    logement_id: Optional[int] = None
    logement_numero: Optional[str] = None
    date_facture: date
    montant: float
    fournisseur: Optional[str] = None
    description: Optional[str] = None


class FactureExterneWrite(BaseModel):
    date_facture: date
    montant: float = Field(..., gt=0)
    fournisseur: Optional[str] = Field(default=None, max_length=160)
    description: Optional[str] = None
    logement_id: Optional[int] = None


class RollupLogementFactures(BaseModel):
    logement_id: Optional[int] = None
    logement_numero: str
    total: float
    nb: int


class FacturesExternesOverview(BaseModel):
    annee: int
    rows: List[FactureExterneRead] = []
    total_annee: float = 0.0
    par_logement: List[RollupLogementFactures] = []


def _fact_read(f: FactureExterne, numero: Optional[str]) -> FactureExterneRead:
    return FactureExterneRead(
        id=f.id,
        immeuble_id=f.immeuble_id,
        logement_id=f.logement_id,
        logement_numero=numero,
        date_facture=f.date_facture,
        montant=float(f.montant or 0),
        fournisseur=f.fournisseur,
        description=f.description,
    )


@router.get(
    "/immeubles/{immeuble_id}/factures-externes",
    response_model=FacturesExternesOverview,
)
async def factures_externes_overview(
    immeuble_id: int,
    db: DBSession,
    user: CurrentUser,
    annee: Optional[int] = None,
) -> FacturesExternesOverview:
    _require_volet(user)
    annee = annee or date.today().year
    rows = (
        await db.execute(
            select(FactureExterne)
            .where(
                FactureExterne.immeuble_id == immeuble_id,
                FactureExterne.date_facture >= date(annee, 1, 1),
                FactureExterne.date_facture <= date(annee, 12, 31),
            )
            .order_by(
                FactureExterne.date_facture.desc(), FactureExterne.id.desc()
            )
        )
    ).scalars().all()
    numeros = {
        lg.id: lg.numero
        for lg in (
            await db.execute(
                select(Logement).where(Logement.immeuble_id == immeuble_id)
            )
        ).scalars().all()
    }
    rollup: dict[Optional[int], RollupLogementFactures] = {}
    total = 0.0
    for f in rows:
        m = float(f.montant or 0)
        total += m
        key = f.logement_id
        if key not in rollup:
            rollup[key] = RollupLogementFactures(
                logement_id=key,
                logement_numero=(
                    numeros.get(key, f"#{key}") if key else "Immeuble (commun)"
                ),
                total=0.0,
                nb=0,
            )
        rollup[key].total = round(rollup[key].total + m, 2)
        rollup[key].nb += 1
    return FacturesExternesOverview(
        annee=annee,
        rows=[_fact_read(f, numeros.get(f.logement_id)) for f in rows],
        total_annee=round(total, 2),
        par_logement=sorted(
            rollup.values(), key=lambda r: -r.total
        ),
    )


@router.post(
    "/immeubles/{immeuble_id}/factures-externes",
    response_model=FactureExterneRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_facture_externe(
    immeuble_id: int,
    payload: FactureExterneWrite,
    db: DBSession,
    user: CurrentUser,
) -> FactureExterneRead:
    _require_volet(user)
    numero = None
    if payload.logement_id is not None:
        lg = await db.get(Logement, payload.logement_id)
        if lg is None or lg.immeuble_id != immeuble_id:
            raise HTTPException(
                status_code=400,
                detail="Logement invalide pour cet immeuble.",
            )
        numero = lg.numero
    obj = FactureExterne(
        immeuble_id=immeuble_id,
        logement_id=payload.logement_id,
        date_facture=payload.date_facture,
        montant=payload.montant,
        fournisseur=(payload.fournisseur or "").strip() or None,
        description=(payload.description or "").strip() or None,
        created_by_email=getattr(user, "email", None),
    )
    db.add(obj)
    await db.commit()
    await db.refresh(obj)
    return _fact_read(obj, numero)


@router.put(
    "/factures-externes/{facture_id}", response_model=FactureExterneRead
)
async def update_facture_externe(
    facture_id: int,
    payload: FactureExterneWrite,
    db: DBSession,
    user: CurrentUser,
) -> FactureExterneRead:
    _require_volet(user)
    obj = await db.get(FactureExterne, facture_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Facture introuvable.")
    numero = None
    if payload.logement_id is not None:
        lg = await db.get(Logement, payload.logement_id)
        if lg is None or lg.immeuble_id != obj.immeuble_id:
            raise HTTPException(
                status_code=400,
                detail="Logement invalide pour cet immeuble.",
            )
        numero = lg.numero
    obj.logement_id = payload.logement_id
    obj.date_facture = payload.date_facture
    obj.montant = payload.montant
    obj.fournisseur = (payload.fournisseur or "").strip() or None
    obj.description = (payload.description or "").strip() or None
    await db.commit()
    await db.refresh(obj)
    return _fact_read(obj, numero)


@router.delete(
    "/factures-externes/{facture_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_facture_externe(
    facture_id: int, db: DBSession, user: CurrentUser
) -> None:
    _require_volet(user)
    obj = await db.get(FactureExterne, facture_id)
    if obj is not None:
        await db.delete(obj)
        await db.commit()
