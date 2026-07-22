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
from app.models.timesheet import (
    TIMESHEET_DAYS,
    Timesheet,
    TimesheetCompany,
    TimesheetEntry,
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
                is_active=True,
            )
        )
    await db.flush()


def _effective_rate(company: TimesheetCompany, ts: Timesheet) -> float:
    if company.taux_refacturation is not None:
        return float(company.taux_refacturation)
    return float(ts.taux_refacturation or 0.0)


# ── Schémas ────────────────────────────────────────────────────────────


class CompanyOut(BaseModel):
    id: int
    label: str
    position: int
    taux_refacturation: Optional[float] = None
    is_active: bool
    refacturable: bool = True


class CompanyCreate(BaseModel):
    label: str = Field(min_length=1, max_length=160)
    taux_refacturation: Optional[float] = None
    position: Optional[int] = None
    refacturable: bool = True


class CompanyUpdate(BaseModel):
    label: Optional[str] = Field(default=None, max_length=160)
    taux_refacturation: Optional[float] = None
    is_active: Optional[bool] = None
    position: Optional[int] = None
    refacturable: Optional[bool] = None


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
    refacturable: bool = True
    jours: List[float]
    total: float
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
    total_heures: float
    montant_paie: float
    total_refacturation: float


class EntryIn(BaseModel):
    company_id: int
    day_index: int = Field(ge=0, le=TIMESHEET_DAYS - 1)
    hours: float = Field(ge=0)


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


# ── Compagnies (liste partagée) ────────────────────────────────────────


@router.get("/companies", response_model=List[CompanyOut])
async def list_companies(
    db: DBSession,
    user: CurrentUser,
    include_inactive: bool = Query(default=False),
) -> List[CompanyOut]:
    await _ensure_seed(db)
    q = select(TimesheetCompany)
    if not (include_inactive and _is_manager(user)):
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
    await db.commit()
    return CompanyOut(
        id=c.id,
        label=c.label,
        position=c.position,
        taux_refacturation=c.taux_refacturation,
        is_active=c.is_active,
        refacturable=bool(getattr(c, "refacturable", True)),
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
    grid: Dict[int, List[float]] = {
        c.id: [0.0] * TIMESHEET_DAYS for c in companies
    }
    for e in entries:
        if e.company_id in grid and 0 <= e.day_index < TIMESHEET_DAYS:
            grid[e.company_id][e.day_index] = float(e.hours or 0.0)

    notes: Dict[str, str] = {}
    if ts.notes_json:
        try:
            notes = json.loads(ts.notes_json) or {}
        except Exception:  # noqa: BLE001
            notes = {}

    lignes: List[LigneOut] = []
    totaux_jour = [0.0] * TIMESHEET_DAYS
    total_heures = 0.0
    total_refac = 0.0
    for c in companies:
        jours = grid[c.id]
        tot = round(sum(jours), 2)
        refacturable = bool(getattr(c, "refacturable", True))
        rate = _effective_rate(c, ts) if refacturable else 0.0
        refac = round(tot * rate, 2)
        for i in range(TIMESHEET_DAYS):
            totaux_jour[i] += jours[i]
        total_heures += tot
        total_refac += refac
        lignes.append(
            LigneOut(
                company_id=c.id,
                label=c.label,
                taux_refacturation=rate,
                refacturable=refacturable,
                jours=jours,
                total=tot,
                refacturation=refac,
                note=notes.get(str(c.id), ""),
            )
        )
    totaux_jour = [round(x, 2) for x in totaux_jour]
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
    can_edit = manager or (is_self and ts.status != "approuve")
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
        taux_refacturation=float(ts.taux_refacturation or 0.0),
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
    if ts.status == "approuve":
        raise HTTPException(
            status_code=409,
            detail="Feuille approuvée — demande à un gestionnaire de la rouvrir.",
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
    seen = set()
    for e in payload.entries:
        if e.hours <= 0:
            continue
        key = (e.company_id, e.day_index)
        if key in seen:
            continue
        seen.add(key)
        db.add(
            TimesheetEntry(
                timesheet_id=ts.id,
                company_id=e.company_id,
                day_index=e.day_index,
                hours=float(e.hours),
            )
        )
    if payload.notes is not None:
        ts.notes_json = json.dumps(payload.notes, ensure_ascii=False)
    # Toute édition d'une feuille soumise la repasse en brouillon
    # (l'employé re-soumet ensuite).
    if ts.status == "soumis" and not _is_manager(user):
        ts.status = "brouillon"
        ts.submitted_at = None
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
    # Un gestionnaire peut tout rouvrir ; l'employé peut rouvrir sa feuille
    # tant qu'elle n'est pas approuvée.
    if not _is_manager(user):
        if ts.user_id != user.id or ts.status == "approuve":
            raise HTTPException(status_code=403, detail="Accès refusé")
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
