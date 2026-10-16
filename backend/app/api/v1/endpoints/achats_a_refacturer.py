"""Page « À refacturer » — achats qui risquent de ne jamais être
refacturés (Steven 2026-10-16). Détection : ``services/achats_a_refacturer``.

Rien n'est modifié automatiquement : la page signale, l'humain décide —
« Refacturer » (verse l'achat sur une facture neuve ou existante du
projet) ou « Ne pas refacturer » (dispense tracée : qui, quand,
pourquoi). Réservé aux admins et owners.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import DBSession, RequireAdminRole
from app.models.achat import Achat
from app.models.bon_travail import BonTravail
from app.models.facture import Facture, FactureStatus
from app.models.fournisseur import Fournisseur
from app.models.project import Project
from app.models.sous_traitant import SousTraitant
from app.models.user import User
from app.services import achats_a_refacturer as svc

router = APIRouter(prefix="/achats-a-refacturer", tags=["achats-a-refacturer"])

#: Factures auxquelles on peut encore ajouter une ligne.
_FACTURE_MODIFIABLE = (
    FactureStatus.DRAFT.value,
    FactureStatus.SENT.value,
    FactureStatus.OVERDUE.value,
)


class LigneARefacturer(BaseModel):
    achat_id: int
    motif: str
    description: Optional[str] = None
    fournisseur: Optional[str] = None
    supplier_invoice_number: Optional[str] = None
    invoice_date: Optional[str] = None
    ajoute_le: Optional[datetime] = None
    montant: float = 0
    montant_refacturable: float = 0
    regle: str = ""
    project_id: Optional[int] = None
    project_name: Optional[str] = None
    project_address: Optional[str] = None
    bon_id: Optional[int] = None
    bon_reference: Optional[str] = None
    bon_titre: Optional[str] = None
    facture_id: Optional[int] = None
    facture_reference: Optional[str] = None
    facture_date: Optional[datetime] = None


class ListeARefacturer(BaseModel):
    compte: int
    total_refacturable: float
    lignes: list[LigneARefacturer]


class Compte(BaseModel):
    compte: int


class Dispense(BaseModel):
    achat_id: int
    description: Optional[str] = None
    fournisseur: Optional[str] = None
    montant: float = 0
    project_id: Optional[int] = None
    project_name: Optional[str] = None
    dispense_le: Optional[datetime] = None
    dispense_par: Optional[str] = None
    raison: Optional[str] = None


class NePasRefacturerRequest(BaseModel):
    raison: str = Field(..., min_length=3, max_length=2000)


class FactureCible(BaseModel):
    id: int
    reference: str
    status: str
    is_final: bool
    total: Optional[float] = None
    created_at: Optional[datetime] = None


class FacturerRequest(BaseModel):
    achat_ids: list[int] = Field(..., min_length=1, max_length=200)
    #: Facture existante du même projet ; absent = nouvelle facture
    #: brouillon.
    facture_id: Optional[int] = None


class FacturerResult(BaseModel):
    facture_id: int
    facture_reference: str
    nouvelle: bool
    lignes_ajoutees: int


async def _noms(db, achats: list[Achat]) -> tuple[dict, dict]:
    f_ids = {a.fournisseur_id for a in achats if a.fournisseur_id}
    s_ids = {a.sous_traitant_id for a in achats if a.sous_traitant_id}
    fourn: dict[int, str] = {}
    st: dict[int, str] = {}
    if f_ids:
        fourn = {
            int(i): n
            for i, n in (
                await db.execute(
                    select(Fournisseur.id, Fournisseur.name).where(
                        Fournisseur.id.in_(f_ids)
                    )
                )
            ).all()
        }
    if s_ids:
        st = {
            int(i): n
            for i, n in (
                await db.execute(
                    select(SousTraitant.id, SousTraitant.full_name).where(
                        SousTraitant.id.in_(s_ids)
                    )
                )
            ).all()
        }
    return fourn, st


def _fournisseur(a: Achat, fourn: dict, st: dict) -> Optional[str]:
    if a.fournisseur_id and a.fournisseur_id in fourn:
        return fourn[a.fournisseur_id]
    if a.sous_traitant_id and a.sous_traitant_id in st:
        return st[a.sous_traitant_id]
    return None


@router.get("", response_model=ListeARefacturer, summary="Achats à refacturer")
async def lister(db: DBSession, _: RequireAdminRole) -> ListeARefacturer:
    lignes = await svc.detecter(db)
    fourn, st = await _noms(db, [l["achat"] for l in lignes])
    out: list[LigneARefacturer] = []
    for l in lignes:
        a: Achat = l["achat"]
        proj: Optional[Project] = l["project"]
        out.append(
            LigneARefacturer(
                achat_id=int(a.id),
                motif=l["motif"],
                description=a.description,
                fournisseur=_fournisseur(a, fourn, st),
                supplier_invoice_number=a.supplier_invoice_number,
                invoice_date=a.invoice_date.isoformat() if a.invoice_date else None,
                ajoute_le=svc._utc(a.created_at),
                montant=float(a.amount or 0),
                montant_refacturable=float(l["montant_refacturable"] or 0),
                regle=l["regle"],
                project_id=int(a.project_id) if a.project_id else None,
                project_name=proj.name if proj else None,
                project_address=proj.address if proj else None,
                bon_id=l["bon_id"],
                bon_reference=l["bon_reference"],
                bon_titre=l["bon_titre"],
                facture_id=l["facture_id"],
                facture_reference=l["facture_reference"],
                facture_date=l["facture_date"],
            )
        )
    return ListeARefacturer(
        compte=len(out),
        total_refacturable=round(sum(l.montant_refacturable for l in out), 2),
        lignes=out,
    )


@router.get("/compte", response_model=Compte, summary="Nombre d'achats à refacturer")
async def compte(db: DBSession, _: RequireAdminRole) -> Compte:
    return Compte(compte=await svc.compter(db))


@router.get(
    "/dispenses",
    response_model=list[Dispense],
    summary="Historique des achats qu'on a autorisé à ne pas refacturer",
)
async def dispenses(
    db: DBSession, _: RequireAdminRole, limit: int = 200
) -> list[Dispense]:
    achats = (
        await db.execute(
            select(Achat)
            .where(Achat.refacturation_dispense_at.is_not(None))
            .order_by(Achat.refacturation_dispense_at.desc())
            .limit(max(1, min(limit, 1000)))
        )
    ).scalars().all()
    fourn, st = await _noms(db, list(achats))
    pids = {a.project_id for a in achats if a.project_id}
    uids = {
        a.refacturation_dispense_par_user_id
        for a in achats
        if a.refacturation_dispense_par_user_id
    }
    projets = {}
    if pids:
        projets = {
            int(i): n
            for i, n in (
                await db.execute(
                    select(Project.id, Project.name).where(Project.id.in_(pids))
                )
            ).all()
        }
    users = {}
    if uids:
        users = {
            int(u.id): u.display_name
            for u in (
                await db.execute(select(User).where(User.id.in_(uids)))
            ).scalars().all()
        }
    return [
        Dispense(
            achat_id=int(a.id),
            description=a.description,
            fournisseur=_fournisseur(a, fourn, st),
            montant=float(a.amount or 0),
            project_id=a.project_id,
            project_name=projets.get(int(a.project_id or 0)),
            dispense_le=svc._utc(a.refacturation_dispense_at),
            dispense_par=users.get(int(a.refacturation_dispense_par_user_id or 0)),
            raison=a.refacturation_dispense_raison,
        )
        for a in achats
    ]


async def _achat(db, achat_id: int) -> Achat:
    a = await db.get(Achat, achat_id)
    if a is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Achat introuvable.")
    return a


def _flip_qbo(a: Achat, billable: bool) -> None:
    """Case FACTURABLE de la dépense QB liée — même réflexe que la fiche
    achat quand on (dé)coche « à refacturer »."""
    if a.qbo_bill_id or a.qbo_purchase_id:
        import asyncio

        from app.services.achat_qbo import flip_qbo_billable_now

        asyncio.create_task(flip_qbo_billable_now(int(a.id), billable))


@router.post(
    "/{achat_id}/ne-pas-refacturer",
    response_model=Compte,
    summary="Autorise explicitement qu'un achat ne soit pas refacturé",
)
async def ne_pas_refacturer(
    achat_id: int,
    data: NePasRefacturerRequest,
    db: DBSession,
    user: RequireAdminRole,
) -> Compte:
    a = await _achat(db, achat_id)
    if a.invoiced_at is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Cet achat est déjà refacturé."
        )
    a.is_billable = False
    a.billable_manual = True
    a.refacturation_dispense_at = datetime.now(timezone.utc)
    a.refacturation_dispense_par_user_id = int(user.id)
    a.refacturation_dispense_raison = data.raison.strip()
    await db.commit()
    _flip_qbo(a, False)
    return Compte(compte=await svc.compter(db))


@router.post(
    "/{achat_id}/retablir",
    response_model=Compte,
    summary="Annule une dispense : l'achat redevient à refacturer",
)
async def retablir(achat_id: int, db: DBSession, _: RequireAdminRole) -> Compte:
    a = await _achat(db, achat_id)
    if a.refacturation_dispense_at is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Aucune dispense sur cet achat."
        )
    a.is_billable = True
    a.billable_manual = True
    a.refacturation_dispense_at = None
    a.refacturation_dispense_par_user_id = None
    a.refacturation_dispense_raison = None
    await db.commit()
    if a.invoiced_at is None:
        _flip_qbo(a, True)
    return Compte(compte=await svc.compter(db))


@router.get(
    "/{achat_id}/factures",
    response_model=list[FactureCible],
    summary="Factures du projet de l'achat auxquelles on peut l'ajouter",
)
async def factures_cibles(
    achat_id: int, db: DBSession, _: RequireAdminRole
) -> list[FactureCible]:
    a = await _achat(db, achat_id)
    if not a.project_id:
        return []
    rows = (
        await db.execute(
            select(Facture)
            .where(
                Facture.project_id == a.project_id,
                Facture.status.in_(_FACTURE_MODIFIABLE),
            )
            .order_by(Facture.created_at.desc())
        )
    ).scalars().all()
    return [
        FactureCible(
            id=int(f.id),
            reference=f.reference,
            status=f.status,
            is_final=bool(f.is_final),
            total=float(f.total) if f.total is not None else None,
            created_at=f.created_at,
        )
        for f in rows
    ]


@router.post(
    "/facturer",
    response_model=FacturerResult,
    summary="Verse des achats sur une facture (neuve ou existante) du projet",
)
async def facturer(
    data: FacturerRequest, db: DBSession, user: RequireAdminRole
) -> FacturerResult:
    from app.api.v1.endpoints.facture_import import (
        ImportRequest,
        import_into_facture,
    )
    from app.services.numbering import provisional_facture_reference

    achats = (
        await db.execute(select(Achat).where(Achat.id.in_(data.achat_ids)))
    ).scalars().all()
    if len(achats) != len(set(data.achat_ids)):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Achat introuvable.")
    pids = {a.project_id for a in achats}
    if None in pids or len(pids) != 1:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Les achats doivent appartenir à un même projet.",
        )
    if any(a.invoiced_at is not None for a in achats):
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Un de ces achats est déjà refacturé."
        )
    project_id = int(pids.pop())

    nouvelle = data.facture_id is None
    if nouvelle:
        proj = await db.get(Project, project_id)
        if proj is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Projet introuvable.")
        client_id = proj.client_id
        if client_id is None:
            bon = (
                await db.execute(
                    select(BonTravail)
                    .where(BonTravail.project_id == project_id)
                    .order_by(BonTravail.id)
                )
            ).scalars().first()
            client_id = bon.client_id if bon is not None else None
        fa = Facture(
            reference=provisional_facture_reference(),
            client_id=client_id,
            project_id=project_id,
            status=FactureStatus.DRAFT.value,
        )
        db.add(fa)
        await db.flush()
    else:
        fa = await db.get(Facture, data.facture_id)
        if fa is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Facture introuvable.")
        if fa.project_id != project_id:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Cette facture n'appartient pas au projet de l'achat.",
            )
        if fa.status not in _FACTURE_MODIFIABLE:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Facture payée ou annulée : on ne peut plus y ajouter de ligne.",
            )

    fid = int(fa.id)
    ref = fa.reference
    # Une dispense posée puis levée à la main : la sélection explicite
    # fait autorité (import_into_facture remet is_billable à True).
    for a in achats:
        a.refacturation_dispense_at = None
        a.refacturation_dispense_par_user_id = None
        a.refacturation_dispense_raison = None
    res = await import_into_facture(
        fid,
        ImportRequest(include_achats=True, achat_ids=list(data.achat_ids)),
        db,
        user,
    )
    await db.commit()
    return FacturerResult(
        facture_id=fid,
        facture_reference=ref,
        nouvelle=nouvelle,
        lignes_ajoutees=res.added,
    )
