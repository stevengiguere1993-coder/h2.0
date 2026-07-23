"""Endpoints Feuille de temps — pôle Gestion d'entreprise.

Scalable multi-employés : chaque employé ne voit/édite que ses propres
feuilles ; les gestionnaires (manager/admin/owner) voient, approuvent et
gèrent celles de tout le monde, ainsi que la liste partagée des compagnies.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, or_, select

from app.api.deps import CurrentUser, DBSession
from app.integrations.quickbooks import QuickBooksError, get_qbo
from app.models.automation_setting import AutomationSetting
from app.models.timesheet import (
    TIMESHEET_DAYS,
    Timesheet,
    TimesheetCompany,
    TimesheetEntry,
    TimesheetReglement,
    TimesheetUserRate,
)
from app.models.user import User

log = logging.getLogger("timesheets")

router = APIRouter(prefix="/timesheets", tags=["timesheets"])

# Lundi de référence pour aligner les périodes bi-hebdomadaires.
ANCHOR_MONDAY = date(2026, 6, 1)

# Liste initiale des compagnies (reprise du fichier Excel). (label, taux)
SEED_COMPANIES: List[tuple] = [
    ("MGV Investissements", 11.0),
    ("MGV Développement", 11.0),
    ("Horizon Construction Signature", 11.0),
    ("Horizon Services Immobiliers", 11.0),
    ("8900 St-Hubert", 33.0),
    ("9417-1287", 33.0),
    ("9520-8955 Millen & Legendre", 33.0),
    ("Immo BGVM", 11.0),
    ("BGV", 11.0),
    ("Immobilier Meuser 1", 11.0),
    ("Immeuble DI Meuser", 11.0),
    ("Groupe Meuser Investissements", 11.0),
    ("Les Entreprises Michael Villiard", 11.0),
    ("Giguère Capital", 11.0),
]


# ── Helpers ────────────────────────────────────────────────────────────


def _is_manager(user: User) -> bool:
    try:
        return bool(user.has_min_role("manager"))
    except Exception:  # noqa: BLE001
        return bool(getattr(user, "is_admin", False)) or user.role in (
            "owner",
            "admin",
            "manager",
        )


def _period_start_for(d: date) -> date:
    """Début de la période bi-hebdomadaire (alignée sur ANCHOR_MONDAY)."""
    block = (d - ANCHOR_MONDAY).days // TIMESHEET_DAYS
    return ANCHOR_MONDAY + timedelta(days=block * TIMESHEET_DAYS)


def _today() -> date:
    return datetime.now(timezone.utc).date()


async def _ensure_seed(db) -> None:
    """Crée la liste de compagnies par défaut si la table est vide."""
    count = (
        await db.execute(select(func.count(TimesheetCompany.id)))
    ).scalar() or 0
    if count:
        return
    for i, (label, taux) in enumerate(SEED_COMPANIES):
        db.add(
            TimesheetCompany(
                label=label,
                position=i,
                taux_refacturation=taux,
                heures_nr_autorisees=(label == "MGV Développement"),
                is_active=True,
            )
        )
    await db.flush()


def _line_rate(
    ts: Timesheet, ov: Optional[TimesheetUserRate]
) -> tuple[float, str]:
    """Taux effectif d'une ligne : (taux, source).

    Le taux de refacturation de la feuille s'applique à TOUTES les
    compagnies ; un override (employé, compagnie) posé à la main sur la
    feuille le remplace ligne par ligne (retour Phil 2026-07-22 — les
    taux au niveau compagnie n'existent plus). ``source`` vaut
    "employe" | "defaut".
    """
    if ov is not None and ov.taux_refacturation is not None:
        return float(ov.taux_refacturation), "employe"
    return float(ts.taux_refacturation or 0.0), "defaut"


async def _load_user_rates(
    db, user_id: int
) -> Dict[int, TimesheetUserRate]:
    rows = (
        await db.execute(
            select(TimesheetUserRate).where(
                TimesheetUserRate.user_id == user_id
            )
        )
    ).scalars().all()
    return {r.company_id: r for r in rows}


# ── Schémas ────────────────────────────────────────────────────────────


class CompanyOut(BaseModel):
    id: int
    label: str
    position: int
    taux_refacturation: Optional[float] = None
    is_active: bool
    refacturable: bool = True
    heures_nr_autorisees: bool = False
    qbo_customer_id: Optional[str] = None
    qbo_customer_name: Optional[str] = None


class CompanyCreate(BaseModel):
    label: str = Field(min_length=1, max_length=160)
    taux_refacturation: Optional[float] = None
    position: Optional[int] = None
    refacturable: bool = True
    heures_nr_autorisees: bool = False
    qbo_customer_id: Optional[str] = None
    qbo_customer_name: Optional[str] = None


class CompanyUpdate(BaseModel):
    label: Optional[str] = Field(default=None, max_length=160)
    taux_refacturation: Optional[float] = None
    is_active: Optional[bool] = None
    position: Optional[int] = None
    refacturable: Optional[bool] = None
    heures_nr_autorisees: Optional[bool] = None
    #: Client QuickBooks associé ("" = revenir à l'auto par nom).
    qbo_customer_id: Optional[str] = None
    qbo_customer_name: Optional[str] = None


class ReorderIn(BaseModel):
    ids: List[int]


class EmployeeOut(BaseModel):
    id: int
    name: str
    email: Optional[str] = None
    role: str


class TimesheetSummary(BaseModel):
    id: Optional[int] = None
    user_id: int
    employee_name: str
    period_start: str
    period_end: str
    status: str
    total_heures: float
    montant_paie: float
    total_refacturation: float
    taux_horaire: float


class LigneOut(BaseModel):
    company_id: int
    label: str
    taux_refacturation: float
    #: D'où vient le taux effectif : "employe" | "defaut".
    taux_source: str = "defaut"
    #: Override brut (employé, compagnie) — pour l'éditeur de taux.
    taux_perso: Optional[float] = None
    #: Heures refacturables (bloc 1 de la grille), par jour.
    jours: List[float]
    #: Heures NON refacturables (bloc 2 de la grille), par jour.
    jours_nr: List[float]
    #: La compagnie accepte-t-elle des heures non refacturables ?
    nr_autorise: bool = False
    total: float
    total_refact: float
    total_non_refact: float
    refacturation: float
    note: str = ""


class TimesheetDetail(BaseModel):
    id: int
    user_id: int
    employee_name: str
    employee_email: Optional[str] = None
    period_start: str
    period_end: str
    jours_dates: List[str]
    taux_horaire: float
    taux_refacturation: float
    status: str
    submitted_at: Optional[str] = None
    approved_at: Optional[str] = None
    approved_by: Optional[str] = None
    is_self: bool
    can_edit: bool
    can_approve: bool
    is_manager: bool
    lignes: List[LigneOut]
    totaux_jour: List[float]
    totaux_jour_nr: List[float]
    total_heures: float
    montant_paie: float
    total_refacturation: float


class EntryIn(BaseModel):
    company_id: int
    day_index: int = Field(ge=0, le=TIMESHEET_DAYS - 1)
    hours: float = Field(ge=0)
    refacturable: bool = True


class EntriesReplace(BaseModel):
    entries: List[EntryIn] = []
    notes: Optional[Dict[str, str]] = None


class TimesheetCreate(BaseModel):
    period_start: Optional[date] = None
    user_id: Optional[int] = None


class TimesheetPatch(BaseModel):
    taux_horaire: Optional[float] = Field(default=None, ge=0)
    taux_refacturation: Optional[float] = Field(default=None, ge=0)
    notes: Optional[Dict[str, str]] = None


class UserRateIn(BaseModel):
    """Remplace l'override (employé, compagnie). Les deux champs à NULL =
    suppression de l'override (retour à l'héritage compagnie/feuille)."""

    user_id: int
    company_id: int
    taux_refacturation: Optional[float] = Field(default=None, ge=0)
    refacturable: Optional[bool] = None


REGLEMENT_KINDS = ("paie", "refacturation")


class ReglementIn(BaseModel):
    kind: str
    user_id: int
    company_id: Optional[int] = None
    montant: float = Field(gt=0)
    date_reglement: Optional[date] = None
    note: Optional[str] = Field(default=None, max_length=500)


class ReglementOut(BaseModel):
    id: int
    kind: str
    user_id: int
    employee_name: str = ""
    company_id: Optional[int] = None
    company_label: Optional[str] = None
    montant: float
    date_reglement: str
    note: Optional[str] = None
    created_by: Optional[str] = None


class DashboardCompanyRow(BaseModel):
    company_id: int
    label: str
    heures: float
    due: float
    regle: float
    solde: float


class DashboardEmployee(BaseModel):
    user_id: int
    name: str
    total_heures: float
    paie_due: float
    paie_reglee: float
    paie_solde: float
    refac_due: float
    refac_reglee: float
    refac_solde: float
    companies: List[DashboardCompanyRow]


class AApprouverOut(BaseModel):
    timesheet_id: int
    user_id: int
    employee_name: str
    period_start: str
    period_end: str
    total_heures: float
    montant_paie: float
    submitted_at: Optional[str] = None


class DashboardOut(BaseModel):
    employees: List[DashboardEmployee]
    total_paie_solde: float
    total_refac_solde: float
    reglements: List[ReglementOut]
    #: Feuilles SOUMISES en attente d'approbation (onglet Paies).
    a_approuver: List[AApprouverOut] = []


# ── Compagnies (liste partagée) ────────────────────────────────────────


@router.get("/companies", response_model=List[CompanyOut])
async def list_companies(
    db: DBSession,
    user: CurrentUser,
    include_inactive: bool = Query(default=False),
) -> List[CompanyOut]:
    # Réservé aux gestionnaires : la liste expose les taux par compagnie
    # et les clients QuickBooks associés. La grille d'un employé, elle,
    # vient de /resolve (labels seulement).
    if not _is_manager(user):
        raise HTTPException(status_code=403, detail="Réservé aux gestionnaires")
    await _ensure_seed(db)
    q = select(TimesheetCompany)
    if not include_inactive:
        q = q.where(TimesheetCompany.is_active.is_(True))
    q = q.order_by(TimesheetCompany.position, TimesheetCompany.id)
    rows = (await db.execute(q)).scalars().all()
    return [
        CompanyOut(
            id=c.id,
            label=c.label,
            position=c.position,
            taux_refacturation=c.taux_refacturation,
            is_active=c.is_active,
            refacturable=bool(getattr(c, "refacturable", True)),
        heures_nr_autorisees=bool(getattr(c, "heures_nr_autorisees", False)),
        qbo_customer_id=getattr(c, "qbo_customer_id", None),
        qbo_customer_name=getattr(c, "qbo_customer_name", None),
        )
        for c in rows
    ]


@router.post("/companies", response_model=CompanyOut)
async def create_company(
    payload: CompanyCreate, db: DBSession, user: CurrentUser
) -> CompanyOut:
    if not _is_manager(user):
        raise HTTPException(status_code=403, detail="Réservé aux gestionnaires")
    await _ensure_seed(db)
    pos = payload.position
    if pos is None:
        maxpos = (
            await db.execute(select(func.max(TimesheetCompany.position)))
        ).scalar()
        pos = (maxpos or 0) + 1
    c = TimesheetCompany(
        label=payload.label.strip(),
        position=pos,
        taux_refacturation=payload.taux_refacturation,
        is_active=True,
        refacturable=payload.refacturable,
        heures_nr_autorisees=payload.heures_nr_autorisees,
        qbo_customer_id=(payload.qbo_customer_id or None),
        qbo_customer_name=(payload.qbo_customer_name or None),
    )
    db.add(c)
    await db.flush()
    await db.commit()
    return CompanyOut(
        id=c.id,
        label=c.label,
        position=c.position,
        taux_refacturation=c.taux_refacturation,
        is_active=c.is_active,
        refacturable=bool(getattr(c, "refacturable", True)),
        heures_nr_autorisees=bool(getattr(c, "heures_nr_autorisees", False)),
        qbo_customer_id=getattr(c, "qbo_customer_id", None),
        qbo_customer_name=getattr(c, "qbo_customer_name", None),
    )


@router.patch("/companies/{company_id}", response_model=CompanyOut)
async def update_company(
    company_id: int,
    payload: CompanyUpdate,
    db: DBSession,
    user: CurrentUser,
) -> CompanyOut:
    if not _is_manager(user):
        raise HTTPException(status_code=403, detail="Réservé aux gestionnaires")
    c = await db.get(TimesheetCompany, company_id)
    if not c:
        raise HTTPException(status_code=404, detail="Compagnie introuvable")
    if payload.label is not None:
        c.label = payload.label.strip()
    if payload.taux_refacturation is not None:
        c.taux_refacturation = payload.taux_refacturation
    if payload.is_active is not None:
        c.is_active = payload.is_active
    if payload.position is not None:
        c.position = payload.position
    if payload.refacturable is not None:
        c.refacturable = payload.refacturable
    if payload.heures_nr_autorisees is not None:
        c.heures_nr_autorisees = payload.heures_nr_autorisees
    if payload.qbo_customer_id is not None:
        c.qbo_customer_id = payload.qbo_customer_id or None
        c.qbo_customer_name = payload.qbo_customer_name or None
    await db.commit()
    return CompanyOut(
        id=c.id,
        label=c.label,
        position=c.position,
        taux_refacturation=c.taux_refacturation,
        is_active=c.is_active,
        refacturable=bool(getattr(c, "refacturable", True)),
        heures_nr_autorisees=bool(getattr(c, "heures_nr_autorisees", False)),
        qbo_customer_id=getattr(c, "qbo_customer_id", None),
        qbo_customer_name=getattr(c, "qbo_customer_name", None),
    )


@router.delete("/companies/{company_id}")
async def delete_company(
    company_id: int, db: DBSession, user: CurrentUser
) -> dict:
    if not _is_manager(user):
        raise HTTPException(status_code=403, detail="Réservé aux gestionnaires")
    c = await db.get(TimesheetCompany, company_id)
    if not c:
        raise HTTPException(status_code=404, detail="Compagnie introuvable")
    # Désactivation (soft delete) : les heures déjà saisies restent valides.
    c.is_active = False
    await db.commit()
    return {"ok": True}


@router.post("/companies/reorder")
async def reorder_companies(
    payload: ReorderIn, db: DBSession, user: CurrentUser
) -> dict:
    if not _is_manager(user):
        raise HTTPException(status_code=403, detail="Réservé aux gestionnaires")
    for pos, cid in enumerate(payload.ids):
        c = await db.get(TimesheetCompany, cid)
        if c:
            c.position = pos
    await db.commit()
    return {"ok": True}


# ── Employés (sélecteur gestionnaire) ──────────────────────────────────


@router.get("/employees", response_model=List[EmployeeOut])
async def list_employees(db: DBSession, user: CurrentUser) -> List[EmployeeOut]:
    if not _is_manager(user):
        raise HTTPException(status_code=403, detail="Réservé aux gestionnaires")
    rows = (
        await db.execute(
            select(User).where(User.is_active.is_(True))
        )
    ).scalars().all()
    rows = sorted(rows, key=lambda u: (u.display_name or u.email or "").lower())
    return [
        EmployeeOut(
            id=u.id,
            name=u.display_name or u.email or f"Utilisateur {u.id}",
            email=u.email,
            role=u.role,
        )
        for u in rows
    ]


# ── Construction du détail d'une feuille ───────────────────────────────


async def _load_companies_for(
    db, ts: Timesheet
) -> List[TimesheetCompany]:
    """Compagnies actives + toute compagnie inactive déjà utilisée dans la
    feuille (pour ne pas perdre d'heures saisies sur une compagnie retirée)."""
    used_ids = set(
        (
            await db.execute(
                select(TimesheetEntry.company_id).where(
                    TimesheetEntry.timesheet_id == ts.id
                )
            )
        ).scalars().all()
    )
    if used_ids:
        q = select(TimesheetCompany).where(
            or_(
                TimesheetCompany.is_active.is_(True),
                TimesheetCompany.id.in_(used_ids),
            )
        )
    else:
        q = select(TimesheetCompany).where(
            TimesheetCompany.is_active.is_(True)
        )
    rows = (await db.execute(q)).scalars().all()
    return sorted(rows, key=lambda c: (c.position, c.id))


async def _build_detail(
    db, ts: Timesheet, user: User
) -> TimesheetDetail:
    companies = await _load_companies_for(db, ts)
    entries = (
        await db.execute(
            select(TimesheetEntry).where(
                TimesheetEntry.timesheet_id == ts.id
            )
        )
    ).scalars().all()
    grid_r: Dict[int, List[float]] = {
        c.id: [0.0] * TIMESHEET_DAYS for c in companies
    }
    grid_n: Dict[int, List[float]] = {
        c.id: [0.0] * TIMESHEET_DAYS for c in companies
    }
    for e in entries:
        tgt = grid_r if getattr(e, "refacturable", True) else grid_n
        if e.company_id in tgt and 0 <= e.day_index < TIMESHEET_DAYS:
            tgt[e.company_id][e.day_index] = float(e.hours or 0.0)

    notes: Dict[str, str] = {}
    if ts.notes_json:
        try:
            notes = json.loads(ts.notes_json) or {}
        except Exception:  # noqa: BLE001
            notes = {}

    overrides = await _load_user_rates(db, ts.user_id)
    # CONFIDENTIALITÉ : les taux et montants de REFACTURATION (ce que
    # Phil facture aux compagnies) ne concernent que les gestionnaires —
    # un employé qui consulte SA feuille ne les reçoit pas (masqués à 0
    # côté serveur, panneau caché côté écran). Il voit sa paie.
    manager_view = _is_manager(user)
    lignes: List[LigneOut] = []
    totaux_jour = [0.0] * TIMESHEET_DAYS
    totaux_jour_nr = [0.0] * TIMESHEET_DAYS
    total_heures = 0.0
    total_refac = 0.0
    for c in companies:
        jr = grid_r[c.id]
        jn = grid_n[c.id]
        # Compagnie INTERNE : toutes ses heures sont non refacturables —
        # d'anciennes heures « refacturables » sont basculées dans le
        # bloc NR (retour Phil 2026-07-22).
        if bool(getattr(c, "heures_nr_autorisees", False)):
            jn = [round(jn[i] + jr[i], 2) for i in range(TIMESHEET_DAYS)]
            jr = [0.0] * TIMESHEET_DAYS
        tot_r = round(sum(jr), 2)
        tot_n = round(sum(jn), 2)
        ov = overrides.get(c.id)
        rate, source = _line_rate(ts, ov)
        if not manager_view:
            rate, source, ov = 0.0, "defaut", None
        refac = round(tot_r * rate, 2)
        for i in range(TIMESHEET_DAYS):
            totaux_jour[i] += jr[i]
            totaux_jour_nr[i] += jn[i]
        total_heures += tot_r + tot_n
        total_refac += refac
        lignes.append(
            LigneOut(
                company_id=c.id,
                label=c.label,
                taux_refacturation=rate,
                taux_source=source,
                taux_perso=(ov.taux_refacturation if ov else None),
                jours=jr,
                jours_nr=jn,
                nr_autorise=bool(getattr(c, "heures_nr_autorisees", False)),
                total=round(tot_r + tot_n, 2),
                total_refact=tot_r,
                total_non_refact=tot_n,
                refacturation=refac,
                note=notes.get(str(c.id), ""),
            )
        )
    totaux_jour = [round(x, 2) for x in totaux_jour]
    totaux_jour_nr = [round(x, 2) for x in totaux_jour_nr]
    total_heures = round(total_heures, 2)
    total_refac = round(total_refac, 2)
    montant_paie = round(total_heures * float(ts.taux_horaire or 0.0), 2)

    employee = await db.get(User, ts.user_id)
    emp_name = (
        (employee.display_name or employee.email) if employee else
        f"Utilisateur {ts.user_id}"
    )
    approver_name = None
    if ts.approved_by_user_id:
        ap = await db.get(User, ts.approved_by_user_id)
        if ap:
            approver_name = ap.display_name or ap.email

    is_self = ts.user_id == user.id
    manager = _is_manager(user)
    # Une feuille SOUMISE est figée pour l'employé (retour Phil
    # 2026-07-22) — seul un gestionnaire peut la modifier/rouvrir.
    can_edit = manager or (is_self and ts.status == "brouillon")
    can_approve = manager

    jours_dates = [
        (ts.period_start + timedelta(days=i)).isoformat()
        for i in range(TIMESHEET_DAYS)
    ]

    return TimesheetDetail(
        id=ts.id,
        user_id=ts.user_id,
        employee_name=emp_name,
        employee_email=(employee.email if employee else None),
        period_start=ts.period_start.isoformat(),
        period_end=ts.period_end.isoformat(),
        jours_dates=jours_dates,
        taux_horaire=float(ts.taux_horaire or 0.0),
        taux_refacturation=(
            float(ts.taux_refacturation or 0.0) if manager_view else 0.0
        ),
        status=ts.status,
        submitted_at=(ts.submitted_at.isoformat() if ts.submitted_at else None),
        approved_at=(ts.approved_at.isoformat() if ts.approved_at else None),
        approved_by=approver_name,
        is_self=is_self,
        can_edit=can_edit,
        can_approve=can_approve,
        is_manager=manager,
        lignes=lignes,
        totaux_jour=totaux_jour,
        totaux_jour_nr=totaux_jour_nr,
        total_heures=total_heures,
        montant_paie=montant_paie,
        total_refacturation=total_refac,
    )


async def _get_or_create(
    db, target_user_id: int, period_start: date
) -> Timesheet:
    period_start = _period_start_for(period_start)
    period_end = period_start + timedelta(days=TIMESHEET_DAYS - 1)
    existing = (
        await db.execute(
            select(Timesheet).where(
                Timesheet.user_id == target_user_id,
                Timesheet.period_start == period_start,
            )
        )
    ).scalar_one_or_none()
    if existing:
        return existing
    # Taux par défaut : ceux de la dernière feuille de l'employé, sinon 11/33.
    last = (
        await db.execute(
            select(Timesheet)
            .where(Timesheet.user_id == target_user_id)
            .order_by(Timesheet.period_start.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    ts = Timesheet(
        user_id=target_user_id,
        period_start=period_start,
        period_end=period_end,
        taux_horaire=(float(last.taux_horaire) if last else 11.0),
        taux_refacturation=(float(last.taux_refacturation) if last else 33.0),
        status="brouillon",
    )
    db.add(ts)
    await db.flush()
    return ts


# ── Résolution / lecture ───────────────────────────────────────────────


@router.get("/resolve", response_model=TimesheetDetail)
async def resolve_timesheet(
    db: DBSession,
    user: CurrentUser,
    period_start: Optional[date] = Query(default=None),
    user_id: Optional[int] = Query(default=None),
) -> TimesheetDetail:
    """Récupère (ou crée) la feuille de l'employé pour une période donnée.

    Sans ``user_id`` → la sienne. Sans ``period_start`` → période courante.
    Un employé ne peut résoudre que ses propres feuilles.
    """
    await _ensure_seed(db)
    target = user.id
    if user_id is not None and user_id != user.id:
        if not _is_manager(user):
            raise HTTPException(status_code=403, detail="Accès refusé")
        target = user_id
    ps = period_start or _period_start_for(_today())
    ts = await _get_or_create(db, target, ps)
    await db.commit()
    return await _build_detail(db, ts, user)


@router.get("/team", response_model=List[TimesheetSummary])
async def team_overview(
    db: DBSession,
    user: CurrentUser,
    period_start: Optional[date] = Query(default=None),
) -> List[TimesheetSummary]:
    """Vue gestionnaire : une ligne par employé pour la période (feuille
    existante ou non)."""
    if not _is_manager(user):
        raise HTTPException(status_code=403, detail="Réservé aux gestionnaires")
    await _ensure_seed(db)
    ps = _period_start_for(period_start or _today())
    pe = ps + timedelta(days=TIMESHEET_DAYS - 1)
    employees = (
        await db.execute(select(User).where(User.is_active.is_(True)))
    ).scalars().all()
    employees = sorted(
        employees, key=lambda u: (u.display_name or u.email or "").lower()
    )
    sheets = (
        await db.execute(
            select(Timesheet).where(Timesheet.period_start == ps)
        )
    ).scalars().all()
    by_user = {s.user_id: s for s in sheets}
    out: List[TimesheetSummary] = []
    for emp in employees:
        s = by_user.get(emp.id)
        if s:
            detail = await _build_detail(db, s, user)
            out.append(
                TimesheetSummary(
                    id=s.id,
                    user_id=emp.id,
                    employee_name=(emp.display_name or emp.email or ""),
                    period_start=ps.isoformat(),
                    period_end=pe.isoformat(),
                    status=s.status,
                    total_heures=detail.total_heures,
                    montant_paie=detail.montant_paie,
                    total_refacturation=detail.total_refacturation,
                    taux_horaire=float(s.taux_horaire or 0.0),
                )
            )
        else:
            out.append(
                TimesheetSummary(
                    id=None,
                    user_id=emp.id,
                    employee_name=(emp.display_name or emp.email or ""),
                    period_start=ps.isoformat(),
                    period_end=pe.isoformat(),
                    status="vide",
                    total_heures=0.0,
                    montant_paie=0.0,
                    total_refacturation=0.0,
                    taux_horaire=0.0,
                )
            )
    return out


@router.get("", response_model=List[TimesheetSummary])
async def list_timesheets(
    db: DBSession,
    user: CurrentUser,
    user_id: Optional[int] = Query(default=None),
) -> List[TimesheetSummary]:
    """Historique des feuilles (les siennes, ou celles d'un employé si
    gestionnaire)."""
    target = user.id
    if user_id is not None and user_id != user.id:
        if not _is_manager(user):
            raise HTTPException(status_code=403, detail="Accès refusé")
        target = user_id
    sheets = (
        await db.execute(
            select(Timesheet)
            .where(Timesheet.user_id == target)
            .order_by(Timesheet.period_start.desc())
        )
    ).scalars().all()
    out: List[TimesheetSummary] = []
    for s in sheets:
        detail = await _build_detail(db, s, user)
        out.append(
            TimesheetSummary(
                id=s.id,
                user_id=s.user_id,
                employee_name=detail.employee_name,
                period_start=s.period_start.isoformat(),
                period_end=s.period_end.isoformat(),
                status=s.status,
                total_heures=detail.total_heures,
                montant_paie=detail.montant_paie,
                total_refacturation=detail.total_refacturation,
                taux_horaire=float(s.taux_horaire or 0.0),
            )
        )
    return out


# ── Taux par employé × compagnie ───────────────────────────────────────


@router.post("/user-rates")
async def upsert_user_rate(
    payload: UserRateIn, db: DBSession, user: CurrentUser
) -> dict:
    """Pose (ou retire) le taux de refacturation propre à un couple
    (employé, compagnie). Les deux champs à NULL = suppression."""
    if not _is_manager(user):
        raise HTTPException(status_code=403, detail="Réservé aux gestionnaires")
    if not await db.get(User, payload.user_id):
        raise HTTPException(status_code=404, detail="Employé introuvable")
    if not await db.get(TimesheetCompany, payload.company_id):
        raise HTTPException(status_code=404, detail="Compagnie introuvable")
    ov = (
        await db.execute(
            select(TimesheetUserRate).where(
                TimesheetUserRate.user_id == payload.user_id,
                TimesheetUserRate.company_id == payload.company_id,
            )
        )
    ).scalar_one_or_none()
    if payload.taux_refacturation is None and payload.refacturable is None:
        if ov:
            await db.delete(ov)
    elif ov:
        ov.taux_refacturation = payload.taux_refacturation
        ov.refacturable = payload.refacturable
    else:
        db.add(
            TimesheetUserRate(
                user_id=payload.user_id,
                company_id=payload.company_id,
                taux_refacturation=payload.taux_refacturation,
                refacturable=payload.refacturable,
            )
        )
    await db.commit()
    return {"ok": True}


# ── Dashboard soldes (paie + refacturation) ────────────────────────────


def _reglement_out(
    r: TimesheetReglement,
    users: Dict[int, User],
    companies: Dict[int, TimesheetCompany],
) -> ReglementOut:
    emp = users.get(r.user_id)
    comp = companies.get(r.company_id) if r.company_id else None
    creator = users.get(r.created_by_user_id) if r.created_by_user_id else None
    return ReglementOut(
        id=r.id,
        kind=r.kind,
        user_id=r.user_id,
        employee_name=(
            (emp.display_name or emp.email or "") if emp else ""
        ),
        company_id=r.company_id,
        company_label=(comp.label if comp else None),
        montant=float(r.montant or 0.0),
        date_reglement=r.date_reglement.isoformat(),
        note=r.note,
        created_by=(
            (creator.display_name or creator.email) if creator else None
        ),
    )


@router.get("/dashboard", response_model=DashboardOut)
async def timesheet_dashboard(
    db: DBSession, user: CurrentUser
) -> DashboardOut:
    """Soldes cumulés par employé : paie due et refacturation due par
    compagnie, moins les règlements enregistrés.

    ⚠️ Seules les feuilles APPROUVÉES comptent dans les dûs/soldes
    (retour Phil 2026-07-22) : rien n'apparaît tant que la feuille n'a
    pas été soumise PUIS approuvée. Les feuilles soumises en attente
    sont listées dans ``a_approuver``."""
    if not _is_manager(user):
        raise HTTPException(status_code=403, detail="Réservé aux gestionnaires")
    await _ensure_seed(db)

    sheets = (
        await db.execute(
            select(Timesheet).where(Timesheet.status == "approuve")
        )
    ).scalars().all()
    sheets_by_id = {s.id: s for s in sheets}
    companies = {
        c.id: c
        for c in (await db.execute(select(TimesheetCompany))).scalars().all()
    }
    overrides = {
        (o.user_id, o.company_id): o
        for o in (
            await db.execute(select(TimesheetUserRate))
        ).scalars().all()
    }
    sums = (
        await db.execute(
            select(
                TimesheetEntry.timesheet_id,
                TimesheetEntry.company_id,
                TimesheetEntry.refacturable,
                func.sum(TimesheetEntry.hours),
            ).group_by(
                TimesheetEntry.timesheet_id,
                TimesheetEntry.company_id,
                TimesheetEntry.refacturable,
            )
        )
    ).all()

    # Paie = TOUTES les heures × taux horaire de la feuille ; refacturation
    # = heures refacturables seulement × taux effectif (perso → défaut).
    hours_by_user: Dict[int, float] = {}
    paie_due: Dict[int, float] = {}
    comp_hours: Dict[tuple, float] = {}
    comp_due: Dict[tuple, float] = {}
    for ts_id, cid, refc, h in sums:
        ts = sheets_by_id.get(ts_id)
        if not ts or cid not in companies or not h:
            continue
        h = float(h)
        uid = ts.user_id
        hours_by_user[uid] = hours_by_user.get(uid, 0.0) + h
        paie_due[uid] = (
            paie_due.get(uid, 0.0) + h * float(ts.taux_horaire or 0.0)
        )
        if refc and not bool(
            getattr(companies[cid], "heures_nr_autorisees", False)
        ):
            rate, _src = _line_rate(ts, overrides.get((uid, cid)))
            key = (uid, cid)
            comp_hours[key] = comp_hours.get(key, 0.0) + h
            comp_due[key] = comp_due.get(key, 0.0) + h * rate

    regs = (
        await db.execute(
            select(TimesheetReglement).order_by(
                TimesheetReglement.date_reglement.desc(),
                TimesheetReglement.id.desc(),
            )
        )
    ).scalars().all()
    paie_reglee: Dict[int, float] = {}
    refac_reglee: Dict[int, float] = {}
    comp_reglee: Dict[tuple, float] = {}
    for r in regs:
        m = float(r.montant or 0.0)
        if r.kind == "paie":
            paie_reglee[r.user_id] = paie_reglee.get(r.user_id, 0.0) + m
        else:
            refac_reglee[r.user_id] = refac_reglee.get(r.user_id, 0.0) + m
            if r.company_id:
                key = (r.user_id, r.company_id)
                comp_reglee[key] = comp_reglee.get(key, 0.0) + m

    user_ids = (
        set(hours_by_user)
        | set(paie_reglee)
        | set(refac_reglee)
        | {r.user_id for r in regs}
    )
    users: Dict[int, User] = {}
    if user_ids or regs:
        wanted = set(user_ids) | {
            r.created_by_user_id for r in regs if r.created_by_user_id
        }
        if wanted:
            for u in (
                await db.execute(select(User).where(User.id.in_(wanted)))
            ).scalars().all():
                users[u.id] = u

    employees: List[DashboardEmployee] = []
    for uid in user_ids:
        emp = users.get(uid)
        comp_keys = [
            k for k in (set(comp_hours) | set(comp_reglee)) if k[0] == uid
        ]
        comp_keys.sort(
            key=lambda k: (
                companies[k[1]].position if k[1] in companies else 999,
                k[1],
            )
        )
        rows: List[DashboardCompanyRow] = []
        for k in comp_keys:
            cid = k[1]
            due = round(comp_due.get(k, 0.0), 2)
            regle = round(comp_reglee.get(k, 0.0), 2)
            if not due and not regle:
                continue
            rows.append(
                DashboardCompanyRow(
                    company_id=cid,
                    label=(
                        companies[cid].label
                        if cid in companies
                        else f"Compagnie {cid}"
                    ),
                    heures=round(comp_hours.get(k, 0.0), 2),
                    due=due,
                    regle=regle,
                    solde=round(due - regle, 2),
                )
            )
        p_due = round(paie_due.get(uid, 0.0), 2)
        p_reg = round(paie_reglee.get(uid, 0.0), 2)
        r_due = round(sum(r.due for r in rows), 2)
        r_reg = round(refac_reglee.get(uid, 0.0), 2)
        employees.append(
            DashboardEmployee(
                user_id=uid,
                name=(
                    (emp.display_name or emp.email)
                    if emp
                    else f"Utilisateur {uid}"
                ),
                total_heures=round(hours_by_user.get(uid, 0.0), 2),
                paie_due=p_due,
                paie_reglee=p_reg,
                paie_solde=round(p_due - p_reg, 2),
                refac_due=r_due,
                refac_reglee=r_reg,
                refac_solde=round(r_due - r_reg, 2),
                companies=rows,
            )
        )
    employees.sort(key=lambda e: e.name.lower())

    # Feuilles soumises en attente d'approbation (cliquables dans Paies).
    a_approuver: List[AApprouverOut] = []
    soumises = (
        await db.execute(
            select(Timesheet)
            .where(Timesheet.status == "soumis")
            .order_by(Timesheet.period_start)
        )
    ).scalars().all()
    for s in soumises:
        d = await _build_detail(db, s, user)
        a_approuver.append(
            AApprouverOut(
                timesheet_id=s.id,
                user_id=s.user_id,
                employee_name=d.employee_name,
                period_start=s.period_start.isoformat(),
                period_end=s.period_end.isoformat(),
                total_heures=d.total_heures,
                montant_paie=d.montant_paie,
                submitted_at=(
                    s.submitted_at.isoformat() if s.submitted_at else None
                ),
            )
        )

    return DashboardOut(
        employees=employees,
        total_paie_solde=round(sum(e.paie_solde for e in employees), 2),
        total_refac_solde=round(sum(e.refac_solde for e in employees), 2),
        reglements=[
            _reglement_out(r, users, companies) for r in regs[:100]
        ],
        a_approuver=a_approuver,
    )


@router.post("/reglements", response_model=ReglementOut)
async def create_reglement(
    payload: ReglementIn, db: DBSession, user: CurrentUser
) -> ReglementOut:
    """Enregistre un règlement (paie versée ou refacturation encaissée) —
    le solde du dashboard diminue d'autant."""
    if not _is_manager(user):
        raise HTTPException(status_code=403, detail="Réservé aux gestionnaires")
    if payload.kind not in REGLEMENT_KINDS:
        raise HTTPException(status_code=422, detail="kind invalide")
    emp = await db.get(User, payload.user_id)
    if not emp:
        raise HTTPException(status_code=404, detail="Employé introuvable")
    comp = None
    if payload.company_id is not None:
        comp = await db.get(TimesheetCompany, payload.company_id)
        if not comp:
            raise HTTPException(status_code=404, detail="Compagnie introuvable")
    if payload.kind == "refacturation" and comp is None:
        raise HTTPException(
            status_code=422,
            detail="Une refacturation se règle par compagnie",
        )
    r = TimesheetReglement(
        kind=payload.kind,
        user_id=payload.user_id,
        company_id=payload.company_id,
        montant=float(payload.montant),
        date_reglement=payload.date_reglement or _today(),
        note=(payload.note or None),
        created_by_user_id=user.id,
    )
    db.add(r)
    await db.flush()
    await db.commit()
    return _reglement_out(
        r,
        {emp.id: emp, user.id: user},
        ({comp.id: comp} if comp else {}),
    )


class ReglementUpdate(BaseModel):
    montant: Optional[float] = Field(default=None, gt=0)
    date_reglement: Optional[date] = None
    note: Optional[str] = Field(default=None, max_length=500)


@router.patch("/reglements/{reglement_id}", response_model=ReglementOut)
async def update_reglement(
    reglement_id: int,
    payload: ReglementUpdate,
    db: DBSession,
    user: CurrentUser,
) -> ReglementOut:
    """Corrige un règlement (montant / date / note) — le solde du
    dashboard suit automatiquement."""
    if not _is_manager(user):
        raise HTTPException(status_code=403, detail="Réservé aux gestionnaires")
    r = await db.get(TimesheetReglement, reglement_id)
    if not r:
        raise HTTPException(status_code=404, detail="Règlement introuvable")
    if payload.montant is not None:
        r.montant = float(payload.montant)
    if payload.date_reglement is not None:
        r.date_reglement = payload.date_reglement
    if payload.note is not None:
        r.note = payload.note.strip() or None
    await db.commit()
    emp = await db.get(User, r.user_id)
    comp = (
        await db.get(TimesheetCompany, r.company_id) if r.company_id else None
    )
    return _reglement_out(
        r,
        {u.id: u for u in [emp, user] if u},
        ({comp.id: comp} if comp else {}),
    )


@router.delete("/reglements/{reglement_id}")
async def delete_reglement(
    reglement_id: int, db: DBSession, user: CurrentUser
) -> dict:
    if not _is_manager(user):
        raise HTTPException(status_code=403, detail="Réservé aux gestionnaires")
    r = await db.get(TimesheetReglement, reglement_id)
    if not r:
        raise HTTPException(status_code=404, detail="Règlement introuvable")
    await db.delete(r)
    await db.commit()
    return {"ok": True}


# ── Facturation QuickBooks (connexion Gestion d'entreprise) ────────────

#: Clé AutomationSetting du réglage de facturation feuille de temps
#: (config_json = {"tax_code_id": "...", "tax_code_name": "..."}).
TIMESHEET_QBO_SETTING_KEY = "timesheet_qbo"


async def _load_ts_qbo_setting(db) -> Dict[str, str]:
    row = await db.get(AutomationSetting, TIMESHEET_QBO_SETTING_KEY)
    if not row or not row.config_json:
        return {}
    try:
        return json.loads(row.config_json) or {}
    except Exception:  # noqa: BLE001
        return {}


class QboOptionsOut(BaseModel):
    connected: bool
    error: Optional[str] = None
    customers: List[Dict[str, str]] = []
    tax_codes: List[Dict[str, str]] = []
    tax_code_id: Optional[str] = None
    tax_code_name: Optional[str] = None


class QboOptionsIn(BaseModel):
    tax_code_id: Optional[str] = None
    tax_code_name: Optional[str] = None


@router.get("/qbo-options", response_model=QboOptionsOut)
async def timesheet_qbo_options(
    db: DBSession, user: CurrentUser
) -> QboOptionsOut:
    """Listes pour configurer la facturation : clients réels + codes de
    taxe du QuickBooks de Gestion d'entreprise, et le code de taxe
    choisi (obligatoire pour les compagnies canadiennes)."""
    if not _is_manager(user):
        raise HTTPException(status_code=403, detail="Réservé aux gestionnaires")
    setting = await _load_ts_qbo_setting(db)
    qbo = get_qbo("entreprise")
    await qbo._load_refresh_from_db()  # noqa: SLF001
    if not qbo.ready:
        return QboOptionsOut(
            connected=False,
            tax_code_id=setting.get("tax_code_id"),
            tax_code_name=setting.get("tax_code_name"),
        )
    customers: List[Dict[str, str]] = []
    tax_codes: List[Dict[str, str]] = []
    error: Optional[str] = None
    try:
        rows = await qbo.query(
            "SELECT Id, DisplayName FROM Customer WHERE Active = true "
            "ORDERBY DisplayName MAXRESULTS 1000"
        )
        customers = [
            {"id": str(r.get("Id")), "name": str(r.get("DisplayName") or "")}
            for r in rows
            if r.get("Id")
        ]
        tc_rows = await qbo.query("SELECT * FROM TaxCode MAXRESULTS 100")
        tax_codes = [
            {"id": str(r.get("Id")), "name": str(r.get("Name") or "")}
            for r in tc_rows
            if r.get("Id") and r.get("Active") is not False
        ]
    except QuickBooksError as exc:
        error = str(exc)
    return QboOptionsOut(
        connected=True,
        error=error,
        customers=customers,
        tax_codes=tax_codes,
        tax_code_id=setting.get("tax_code_id"),
        tax_code_name=setting.get("tax_code_name"),
    )


@router.post("/qbo-options", response_model=QboOptionsOut)
async def timesheet_qbo_options_save(
    payload: QboOptionsIn, db: DBSession, user: CurrentUser
) -> QboOptionsOut:
    if not _is_manager(user):
        raise HTTPException(status_code=403, detail="Réservé aux gestionnaires")
    row = await db.get(AutomationSetting, TIMESHEET_QBO_SETTING_KEY)
    cfg = {
        "tax_code_id": (payload.tax_code_id or "").strip() or None,
        "tax_code_name": (payload.tax_code_name or "").strip() or None,
    }
    if row is None:
        db.add(
            AutomationSetting(
                key=TIMESHEET_QBO_SETTING_KEY,
                enabled=True,
                config_json=json.dumps(cfg, ensure_ascii=False),
                updated_by_user_id=user.id,
            )
        )
    else:
        row.config_json = json.dumps(cfg, ensure_ascii=False)
        row.updated_by_user_id = user.id
    await db.commit()
    return QboOptionsOut(
        connected=True,
        tax_code_id=cfg["tax_code_id"],
        tax_code_name=cfg["tax_code_name"],
    )


class FactureQboIn(BaseModel):
    user_id: int
    company_id: int


class FactureQboOut(BaseModel):
    ok: bool
    invoice_id: Optional[str] = None
    doc_number: Optional[str] = None
    montant: float = 0.0
    heures: float = 0.0
    taux: float = 0.0


@router.post("/facturer-qbo", response_model=FactureQboOut)
async def facturer_solde_qbo(
    payload: FactureQboIn, db: DBSession, user: CurrentUser
) -> FactureQboOut:
    """Crée une facture dans le QuickBooks de GESTION D'ENTREPRISE pour le
    solde de refacturation (employé, compagnie) : client QBO = le nom de
    la compagnie, ligne = heures × taux. Puis enregistre automatiquement
    le règlement « refacturation » → le solde du dashboard tombe à 0."""
    if not _is_manager(user):
        raise HTTPException(status_code=403, detail="Réservé aux gestionnaires")
    emp = await db.get(User, payload.user_id)
    if not emp:
        raise HTTPException(status_code=404, detail="Employé introuvable")
    comp = await db.get(TimesheetCompany, payload.company_id)
    if not comp:
        raise HTTPException(status_code=404, detail="Compagnie introuvable")

    # Dû cumulé (heures refacturables × taux effectif par feuille) − déjà
    # refacturé = solde à facturer. Même calcul que le dashboard.
    sheets = (
        await db.execute(
            select(Timesheet).where(
                Timesheet.user_id == payload.user_id,
                Timesheet.status == "approuve",
            )
        )
    ).scalars().all()
    ov = (
        await db.execute(
            select(TimesheetUserRate).where(
                TimesheetUserRate.user_id == payload.user_id,
                TimesheetUserRate.company_id == payload.company_id,
            )
        )
    ).scalar_one_or_none()
    heures = 0.0
    due = 0.0
    if sheets:
        by_id = {s.id: s for s in sheets}
        sums = (
            await db.execute(
                select(
                    TimesheetEntry.timesheet_id,
                    func.sum(TimesheetEntry.hours),
                )
                .where(
                    TimesheetEntry.timesheet_id.in_(by_id.keys()),
                    TimesheetEntry.company_id == payload.company_id,
                    TimesheetEntry.refacturable.is_(True),
                )
                .group_by(TimesheetEntry.timesheet_id)
            )
        ).all()
        for ts_id, h in sums:
            ts = by_id.get(ts_id)
            if not ts or not h:
                continue
            rate, _src = _line_rate(ts, ov)
            heures += float(h)
            due += float(h) * rate
    regle = 0.0
    for r in (
        await db.execute(
            select(TimesheetReglement).where(
                TimesheetReglement.user_id == payload.user_id,
                TimesheetReglement.company_id == payload.company_id,
                TimesheetReglement.kind == "refacturation",
            )
        )
    ).scalars().all():
        regle += float(r.montant or 0.0)
    solde = round(due - regle, 2)
    if solde <= 0 or heures <= 0:
        raise HTTPException(
            status_code=409, detail="Rien à facturer — le solde est à zéro."
        )
    taux_moyen = round(due / heures, 2)
    # Quantité facturée = heures non encore refacturées (solde ÷ taux
    # moyen) ; sans règlement partiel = exactement les heures cumulées.
    qty = round(solde / taux_moyen, 2) if taux_moyen else 0.0
    montant = round(qty * taux_moyen, 2)

    qbo = get_qbo("entreprise")
    await qbo._load_refresh_from_db()  # noqa: SLF001 — charge realm/token
    if not qbo.ready:
        raise HTTPException(
            status_code=503,
            detail=(
                "Le QuickBooks de Gestion d'entreprise n'est pas connecté. "
                "Va dans Paramètres → Comptabilité → « QuickBooks — autres "
                "pôles » et connecte la carte Gestion d'entreprise."
            ),
        )

    # Code de taxe OBLIGATOIRE (les compagnies QBO canadiennes refusent
    # une facture sans taux de TPS/TVQ — erreur 6000 vue chez Phil).
    setting = await _load_ts_qbo_setting(db)
    tax_code_id = (setting.get("tax_code_id") or "").strip()
    if not tax_code_id:
        raise HTTPException(
            status_code=422,
            detail=(
                "QuickBooks exige un code de taxe sur les factures. "
                "Ouvre le bouton « Compagnies » de la feuille de temps et "
                "choisis le code de taxe (ex. TPS/TVQ QC) dans la section "
                "Facturation QuickBooks."
            ),
        )

    emp_name = emp.display_name or emp.email or f"Employé {emp.id}"
    try:
        # Client QBO : celui associé à la compagnie dans le modal
        # Compagnies, sinon retrouvé/créé par nom.
        if comp.qbo_customer_id:
            customer_ref = str(comp.qbo_customer_id)
        else:
            customer = await qbo.ensure_customer(display_name=comp.label)
            customer_ref = str(customer["Id"])
        item = await qbo.ensure_item(
            "Heures", description="Heures de main-d'oeuvre refacturées"
        )

        # Numéro de facture : quand QBO a « numéros d'opération
        # personnalisés » activé, l'API laisse le DocNumber VIDE si on
        # n'en fournit pas (vu chez Phil). On calcule donc le prochain
        # numéro nous-mêmes (max numérique des factures récentes + 1).
        next_num: Optional[str] = None
        try:
            rows = await qbo.query(
                "SELECT DocNumber FROM Invoice "
                "ORDERBY MetaData.CreateTime DESC MAXRESULTS 100"
            )
            nums = [
                int(str(r.get("DocNumber")))
                for r in rows
                if str(r.get("DocNumber") or "").isdigit()
            ]
            next_num = str(max(nums) + 1) if nums else "1000"
        except QuickBooksError:
            next_num = None  # QBO choisira (ou laissera vide)

        base_payload = {
            "CustomerRef": {"value": customer_ref},
            "TxnDate": _today().isoformat(),
            "GlobalTaxCalculation": "TaxExcluded",
            "Line": [
                {
                    "DetailType": "SalesItemLineDetail",
                    "Amount": montant,
                    "Description": (
                        f"Heures de {emp_name} — "
                        f"{qty:g} h × {taux_moyen:.2f} $/h"
                    ),
                    "SalesItemLineDetail": {
                        "ItemRef": {"value": str(item["Id"])},
                        "Qty": qty,
                        "UnitPrice": taux_moyen,
                        "TaxCodeRef": {"value": tax_code_id},
                    },
                }
            ],
            "PrivateNote": (
                "Créé par Kratos — refacturation feuille de temps "
                f"({emp_name})"
            ),
        }
        # Collision de numéro (erreur 6140 « en double ») → on incrémente
        # et on réessaie (max 3 fois).
        tries = 0
        while True:
            body = dict(base_payload)
            if next_num:
                body["DocNumber"] = next_num
            try:
                inv = await qbo.create_invoice(body)
                break
            except QuickBooksError as exc:
                msg = str(exc)
                if (
                    next_num
                    and tries < 3
                    and ("6140" in msg or "uplicate" in msg or "double" in msg)
                ):
                    tries += 1
                    next_num = str(int(next_num) + 1)
                    continue
                raise
    except QuickBooksError as exc:
        raise HTTPException(
            status_code=502, detail=f"QuickBooks a refusé la facture : {exc}"
        )
    invoice = inv.get("Invoice") or inv
    invoice_id = str(invoice.get("Id") or "")
    doc_number = str(invoice.get("DocNumber") or "") or None

    db.add(
        TimesheetReglement(
            kind="refacturation",
            user_id=payload.user_id,
            company_id=payload.company_id,
            montant=montant,
            date_reglement=_today(),
            note=(
                f"Facture QuickBooks #{doc_number or invoice_id} — "
                f"{qty:g} h × {taux_moyen:.2f} $/h ({emp_name})"
            ),
            created_by_user_id=user.id,
        )
    )
    await db.commit()
    log.info(
        "Facture QBO %s créée pour %s / %s (%.2f $)",
        doc_number or invoice_id, emp_name, comp.label, montant,
    )
    return FactureQboOut(
        ok=True,
        invoice_id=invoice_id or None,
        doc_number=doc_number,
        montant=montant,
        heures=qty,
        taux=taux_moyen,
    )


@router.get("/{timesheet_id}", response_model=TimesheetDetail)
async def get_timesheet(
    timesheet_id: int, db: DBSession, user: CurrentUser
) -> TimesheetDetail:
    ts = await db.get(Timesheet, timesheet_id)
    if not ts:
        raise HTTPException(status_code=404, detail="Feuille introuvable")
    if not (_is_manager(user) or ts.user_id == user.id):
        raise HTTPException(status_code=403, detail="Accès refusé")
    return await _build_detail(db, ts, user)


# ── Mutations ──────────────────────────────────────────────────────────


def _assert_editable(ts: Timesheet, user: User) -> None:
    manager = _is_manager(user)
    if manager:
        return
    if ts.user_id != user.id:
        raise HTTPException(status_code=403, detail="Accès refusé")
    if ts.status != "brouillon":
        raise HTTPException(
            status_code=409,
            detail=(
                "Feuille soumise ou approuvée — demande à un gestionnaire "
                "de la rouvrir pour la modifier."
            ),
        )


@router.patch("/{timesheet_id}", response_model=TimesheetDetail)
async def patch_timesheet(
    timesheet_id: int,
    payload: TimesheetPatch,
    db: DBSession,
    user: CurrentUser,
) -> TimesheetDetail:
    ts = await db.get(Timesheet, timesheet_id)
    if not ts:
        raise HTTPException(status_code=404, detail="Feuille introuvable")
    _assert_editable(ts, user)
    # Seul un gestionnaire modifie les taux ; l'employé édite ses notes.
    if payload.taux_horaire is not None:
        if not _is_manager(user):
            raise HTTPException(
                status_code=403, detail="Taux modifiable par un gestionnaire"
            )
        ts.taux_horaire = payload.taux_horaire
    if payload.taux_refacturation is not None:
        if not _is_manager(user):
            raise HTTPException(
                status_code=403, detail="Taux modifiable par un gestionnaire"
            )
        ts.taux_refacturation = payload.taux_refacturation
    if payload.notes is not None:
        ts.notes_json = json.dumps(payload.notes, ensure_ascii=False)
    await db.commit()
    return await _build_detail(db, ts, user)


@router.put("/{timesheet_id}/entries", response_model=TimesheetDetail)
async def replace_entries(
    timesheet_id: int,
    payload: EntriesReplace,
    db: DBSession,
    user: CurrentUser,
) -> TimesheetDetail:
    ts = await db.get(Timesheet, timesheet_id)
    if not ts:
        raise HTTPException(status_code=404, detail="Feuille introuvable")
    _assert_editable(ts, user)
    # Remplacement complet de la grille.
    await db.execute(
        delete(TimesheetEntry).where(
            TimesheetEntry.timesheet_id == ts.id
        )
    )
    # Compagnies INTERNES (MGV Développement par défaut) : toutes leurs
    # heures sont non refacturables — on force le flag ; et les heures NR
    # ne sont permises que sur ces compagnies.
    nr_ok = {
        c.id
        for c in (
            await db.execute(select(TimesheetCompany))
        ).scalars().all()
        if bool(getattr(c, "heures_nr_autorisees", False))
    }
    seen = set()
    for e in payload.entries:
        if e.hours <= 0:
            continue
        if not e.refacturable and e.company_id not in nr_ok:
            continue
        if e.refacturable and e.company_id in nr_ok:
            e.refacturable = False
        key = (e.company_id, e.day_index, bool(e.refacturable))
        if key in seen:
            continue
        seen.add(key)
        db.add(
            TimesheetEntry(
                timesheet_id=ts.id,
                company_id=e.company_id,
                day_index=e.day_index,
                refacturable=bool(e.refacturable),
                hours=float(e.hours),
            )
        )
    if payload.notes is not None:
        ts.notes_json = json.dumps(payload.notes, ensure_ascii=False)
    await db.commit()
    return await _build_detail(db, ts, user)


@router.post("/{timesheet_id}/submit", response_model=TimesheetDetail)
async def submit_timesheet(
    timesheet_id: int, db: DBSession, user: CurrentUser
) -> TimesheetDetail:
    ts = await db.get(Timesheet, timesheet_id)
    if not ts:
        raise HTTPException(status_code=404, detail="Feuille introuvable")
    if not (_is_manager(user) or ts.user_id == user.id):
        raise HTTPException(status_code=403, detail="Accès refusé")
    ts.status = "soumis"
    ts.submitted_at = datetime.now(timezone.utc)
    await db.commit()
    return await _build_detail(db, ts, user)


@router.post("/{timesheet_id}/approve", response_model=TimesheetDetail)
async def approve_timesheet(
    timesheet_id: int, db: DBSession, user: CurrentUser
) -> TimesheetDetail:
    if not _is_manager(user):
        raise HTTPException(status_code=403, detail="Réservé aux gestionnaires")
    ts = await db.get(Timesheet, timesheet_id)
    if not ts:
        raise HTTPException(status_code=404, detail="Feuille introuvable")
    ts.status = "approuve"
    ts.approved_at = datetime.now(timezone.utc)
    ts.approved_by_user_id = user.id
    if not ts.submitted_at:
        ts.submitted_at = datetime.now(timezone.utc)
    await db.commit()
    return await _build_detail(db, ts, user)


@router.post("/{timesheet_id}/reopen", response_model=TimesheetDetail)
async def reopen_timesheet(
    timesheet_id: int, db: DBSession, user: CurrentUser
) -> TimesheetDetail:
    ts = await db.get(Timesheet, timesheet_id)
    if not ts:
        raise HTTPException(status_code=404, detail="Feuille introuvable")
    # Rouvrir = GESTIONNAIRE seulement : une feuille soumise est figée
    # pour l'employé (retour Phil 2026-07-22).
    if not _is_manager(user):
        raise HTTPException(status_code=403, detail="Réservé aux gestionnaires")
    ts.status = "brouillon"
    ts.submitted_at = None
    ts.approved_at = None
    ts.approved_by_user_id = None
    await db.commit()
    return await _build_detail(db, ts, user)


@router.delete("/{timesheet_id}")
async def delete_timesheet(
    timesheet_id: int, db: DBSession, user: CurrentUser
) -> dict:
    ts = await db.get(Timesheet, timesheet_id)
    if not ts:
        raise HTTPException(status_code=404, detail="Feuille introuvable")
    if not _is_manager(user):
        if ts.user_id != user.id or ts.status == "approuve":
            raise HTTPException(status_code=403, detail="Accès refusé")
    await db.execute(
        delete(TimesheetEntry).where(TimesheetEntry.timesheet_id == ts.id)
    )
    await db.delete(ts)
    await db.commit()
    return {"ok": True}
