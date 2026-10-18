"""Zone employés (Steven, 2026-10-04).

Deux routeurs, tous deux sous la garde du pôle Entreprises :

- ``/entreprises/employes`` — la section « Employés » du pôle (gestionnaires
  et plus) : l'équipe, le suivi d'ensemble du temps travaillé et l'agenda
  d'un employé (meetings, tournages…), que l'employé retrouve dans sa zone
  employés (app mobile et site).
- ``/entreprises/mes-taches`` — les tâches PERSONNELLES d'un employé dans la
  zone employés : il voit celles qui lui sont assignées, s'en crée pour
  l'une de nos entreprises, les classe (statut, priorité, échéance) et
  supprime celles qu'il a créées lui-même.

Les tâches restent des ``EntrepriseTache`` (mêmes données que le tableau
« Tâches » du QG et que l'import dans la feuille de temps) ; les événements
restent des ``AgendaEvent`` (scope « entreprises » : l'agenda d'un employé
« autre » n'est pas relié à celui de Construction, qui n'en voit qu'un bloc
« Indisponible »).
"""

from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta, timezone
from typing import Dict, List, Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select

from app.api.deps import CurrentUser, DBSession, RequireManager
from app.models.agenda_event import AgendaEvent
from app.models.employe import Employe
from app.models.entreprise import Entreprise
from app.models.entreprise_tache import EntrepriseTache, TacheStatus
from app.models.entreprise_tache_assignee import EntrepriseTacheAssignee
from app.models.punch import Punch
from app.models.timesheet import (
    TIMESHEET_DAYS,
    Timesheet,
    TimesheetCompany,
    TimesheetEntry,
    TimesheetUserCompany,
)
from app.models.user import User

log = logging.getLogger(__name__)

router_admin = APIRouter(prefix="/entreprises/employes", tags=["zone-employes"])
router_mes_taches = APIRouter(
    prefix="/entreprises/mes-taches", tags=["zone-employes"]
)

#: Fuseau des journées de travail (heure de Montréal).
TZ_LOCAL = ZoneInfo("America/Toronto")

#: Scope des événements planifiés depuis la section Employés. Distinct de
#: « construction » : l'agenda d'un employé « autre » n'est pas relié à
#: celui de Construction (Steven 2026-10-04).
SCOPE_ZONE = "entreprises"

#: Types d'événements qu'un gestionnaire planifie pour un employé.
TYPES_EVENEMENT = ("reunion", "tournage", "rdv", "formation", "autre")

#: Rôles listés dans la section Employés. Les propriétaires n'y figurent
#: pas (ce sont eux qui gèrent) ; les admins seulement sur demande.
ROLES_EQUIPE = ("employee", "manager")

_ORDRE_STATUTS = {
    TacheStatus.IN_PROGRESS.value: 0,
    TacheStatus.A_FAIRE.value: 1,
    TacheStatus.WAITING.value: 2,
    TacheStatus.TODO.value: 3,
    TacheStatus.BACKLOG.value: 4,
    TacheStatus.DONE.value: 5,
}


# ── Helpers ─────────────────────────────────────────────────────────────


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: Optional[datetime]) -> Optional[datetime]:
    """SQLite (tests) rend des datetimes naïfs ; Postgres des aware. On
    compare toujours en UTC."""
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _periode_courante() -> date:
    """Début de la période de paie courante (même alignement que la
    feuille de temps)."""
    from app.api.v1.endpoints.timesheets import _period_start_for

    return _period_start_for(_now().date())


async def _employes_par_email(db, emails: List[str]) -> Dict[str, Employe]:
    """Fiches Employé (Construction) actives, indexées par courriel en
    minuscules — le lien User ↔ Employe est le courriel."""
    cles = sorted({(e or "").lower() for e in emails if e})
    if not cles:
        return {}
    rows = (
        await db.execute(
            select(Employe).where(
                func.lower(Employe.email).in_(cles), Employe.active.is_(True)
            )
        )
    ).scalars().all()
    return {(e.email or "").lower(): e for e in rows}


def _type_employe(user: User, employe: Optional[Employe]) -> str:
    """« construction » = accès au pôle Construction ou fiche Employé ;
    sinon « autre » (ex. vidéo / marketing en Entreprises)."""
    if employe is not None or user.has_volet("construction"):
        return "construction"
    return "autre"


async def _utilisateurs_equipe(db, inclure_admins: bool) -> List[User]:
    roles = list(ROLES_EQUIPE) + (["admin"] if inclure_admins else [])
    rows = (
        await db.execute(
            select(User).where(User.is_active.is_(True), User.role.in_(roles))
        )
    ).scalars().all()
    return sorted(rows, key=lambda u: (u.display_name or u.email or "").lower())


async def _taches_par_assigne(db, user_ids: List[int]) -> Dict[int, List[EntrepriseTache]]:
    """Toutes les tâches (ouvertes ou non) où chaque utilisateur est
    assigné principal OU co-assigné."""
    if not user_ids:
        return {}
    via_join = (
        await db.execute(
            select(EntrepriseTacheAssignee.tache_id, EntrepriseTacheAssignee.user_id).where(
                EntrepriseTacheAssignee.user_id.in_(user_ids)
            )
        )
    ).all()
    ids_join = {tid for tid, _ in via_join}
    rows = (
        await db.execute(
            select(EntrepriseTache).where(
                or_(
                    EntrepriseTache.assignee_user_id.in_(user_ids),
                    EntrepriseTache.id.in_(ids_join or {-1}),
                )
            )
        )
    ).scalars().all()
    par_tache: Dict[int, set] = {}
    for tid, uid in via_join:
        par_tache.setdefault(tid, set()).add(uid)
    out: Dict[int, List[EntrepriseTache]] = {uid: [] for uid in user_ids}
    for t in rows:
        cibles = set(par_tache.get(t.id, set()))
        if t.assignee_user_id is not None:
            cibles.add(t.assignee_user_id)
        for uid in cibles:
            if uid in out:
                out[uid].append(t)
    return out


def _heures_feuilles_par_jour(
    sheets: List[Timesheet], entries: List[TimesheetEntry]
) -> Dict[int, Dict[date, float]]:
    """{user_id: {jour: heures}} à partir des cases de la grille (la grille
    d'une feuille « par tâche » en est dérivée, donc même source)."""
    par_feuille = {s.id: s for s in sheets}
    out: Dict[int, Dict[date, float]] = {}
    for e in entries:
        s = par_feuille.get(e.timesheet_id)
        if s is None or not e.hours:
            continue
        jour = s.period_start + timedelta(days=int(e.day_index))
        cumul = out.setdefault(s.user_id, {})
        cumul[jour] = cumul.get(jour, 0.0) + float(e.hours)
    return out


async def _feuilles_dans_plage(db, user_ids: List[int], debut: date, fin: date):
    if not user_ids:
        return [], []
    sheets = (
        await db.execute(
            select(Timesheet).where(
                Timesheet.user_id.in_(user_ids),
                Timesheet.period_start <= fin,
                Timesheet.period_end >= debut,
            )
        )
    ).scalars().all()
    if not sheets:
        return [], []
    entries = (
        await db.execute(
            select(TimesheetEntry).where(
                TimesheetEntry.timesheet_id.in_([s.id for s in sheets])
            )
        )
    ).scalars().all()
    return sheets, entries


# ── Schémas : section Employés ──────────────────────────────────────────


class EvenementOut(BaseModel):
    id: int
    title: str
    description: Optional[str] = None
    location: Optional[str] = None
    start_at: datetime
    end_at: Optional[datetime] = None
    all_day: bool = False
    event_type: str
    scope: str
    #: Modifiable depuis la section Employés (planifié ici, scope zone).
    modifiable: bool = False


class EmployeZoneOut(BaseModel):
    id: int
    display_name: str
    email: str
    role: str
    #: « construction » (punch, projets) ou « autre » (agenda, tâches,
    #: feuille de temps).
    type: str
    volets: List[str]
    employe_id: Optional[int] = None
    profile_color: Optional[str] = None
    has_avatar: bool = False
    taches_ouvertes: int = 0
    taches_terminees_30j: int = 0
    #: Heures de la feuille de temps de la période de paie courante.
    heures_periode: float = 0.0
    feuille_statut: Optional[str] = None
    prochain_evenement: Optional[EvenementOut] = None


class SuiviTempsLigne(BaseModel):
    user_id: int
    display_name: str
    type: str
    heures_feuille: float
    heures_punch: float
    heures_total: float
    jours_travailles: int
    taches_terminees: int
    taches_ouvertes: int


class SuiviTempsOut(BaseModel):
    debut: date
    fin: date
    lignes: List[SuiviTempsLigne]
    total_heures: float


class EvenementIn(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: Optional[str] = None
    location: Optional[str] = Field(default=None, max_length=500)
    start_at: datetime
    end_at: Optional[datetime] = None
    all_day: bool = False
    event_type: str = Field(default="reunion", max_length=32)


class EvenementPatch(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=255)
    description: Optional[str] = None
    location: Optional[str] = Field(default=None, max_length=500)
    start_at: Optional[datetime] = None
    end_at: Optional[datetime] = None
    all_day: Optional[bool] = None
    event_type: Optional[str] = Field(default=None, max_length=32)


def _evenement_out(e: AgendaEvent) -> EvenementOut:
    return EvenementOut(
        id=e.id,
        title=e.title,
        description=e.description,
        location=e.location,
        start_at=e.start_at,
        end_at=e.end_at,
        all_day=bool(e.all_day),
        event_type=e.event_type or "autre",
        scope=e.scope or "construction",
        modifiable=(e.scope == SCOPE_ZONE),
    )


def _valider_type(t: str) -> str:
    t = (t or "").strip().lower()
    if t not in TYPES_EVENEMENT:
        raise HTTPException(
            422,
            f"Type d'événement invalide : {', '.join(TYPES_EVENEMENT)}.",
        )
    return t


def _valider_plage(start_at: datetime, end_at: Optional[datetime]) -> None:
    if end_at is not None and end_at <= start_at:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "La fin doit suivre le début."
        )


async def _charger_employe_zone(db, user_id: int) -> tuple[User, Optional[Employe]]:
    u = await db.get(User, user_id)
    if u is None or not u.is_active:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Employé introuvable.")
    emp = (await _employes_par_email(db, [u.email])).get((u.email or "").lower())
    return u, emp


# ── Section Employés : équipe ───────────────────────────────────────────


@router_admin.get("", response_model=List[EmployeZoneOut])
async def lister_equipe(
    db: DBSession,
    _: RequireManager,
    inclure_admins: bool = Query(default=False),
) -> List[EmployeZoneOut]:
    """L'équipe vue par un gestionnaire : chaque compte employé (et
    gestionnaire) avec son type, ses tâches ouvertes, les heures de sa
    feuille de la période courante et son prochain événement."""
    users = await _utilisateurs_equipe(db, inclure_admins)
    if not users:
        return []
    ids = [u.id for u in users]
    employes = await _employes_par_email(db, [u.email for u in users])
    taches = await _taches_par_assigne(db, ids)
    il_y_a_30j = _now() - timedelta(days=30)

    debut = _periode_courante()
    fin = debut + timedelta(days=TIMESHEET_DAYS - 1)
    sheets, entries = await _feuilles_dans_plage(db, ids, debut, fin)
    heures = _heures_feuilles_par_jour(sheets, entries)
    statut_feuille = {s.user_id: s.status for s in sheets if s.period_start == debut}

    now = _now()
    emp_ids = [e.id for e in employes.values()]
    evenements = (
        await db.execute(
            select(AgendaEvent)
            .where(
                AgendaEvent.start_at >= now,
                AgendaEvent.start_at <= now + timedelta(days=90),
                or_(
                    AgendaEvent.assignee_user_id.in_(ids),
                    AgendaEvent.assignee_id.in_(emp_ids or [-1]),
                ),
            )
            .order_by(AgendaEvent.start_at.asc())
        )
    ).scalars().all()
    emp_vers_user = {
        e.id: u.id for u in users for e in [employes.get((u.email or "").lower())] if e
    }
    prochain: Dict[int, AgendaEvent] = {}
    for ev in evenements:
        uid = ev.assignee_user_id or emp_vers_user.get(ev.assignee_id or -1)
        if uid is not None and uid not in prochain:
            prochain[uid] = ev

    out: List[EmployeZoneOut] = []
    for u in users:
        emp = employes.get((u.email or "").lower())
        mes_taches = taches.get(u.id, [])
        ouvertes = sum(1 for t in mes_taches if t.status != TacheStatus.DONE.value)
        terminees = sum(
            1
            for t in mes_taches
            if t.status == TacheStatus.DONE.value
            and t.completed_at is not None
            and _aware(t.completed_at) >= il_y_a_30j
        )
        ev = prochain.get(u.id)
        out.append(
            EmployeZoneOut(
                id=u.id,
                display_name=u.display_name or u.email,
                email=u.email,
                role=u.role,
                type=_type_employe(u, emp),
                volets=list(u.volets),
                employe_id=emp.id if emp else None,
                profile_color=u.profile_color,
                has_avatar=u.has_avatar,
                taches_ouvertes=ouvertes,
                taches_terminees_30j=terminees,
                heures_periode=round(sum(heures.get(u.id, {}).values()), 2),
                feuille_statut=statut_feuille.get(u.id),
                prochain_evenement=_evenement_out(ev) if ev else None,
            )
        )
    return out


@router_admin.get("/suivi-temps", response_model=SuiviTempsOut)
async def suivi_temps(
    db: DBSession,
    _: RequireManager,
    debut: Optional[date] = Query(default=None),
    fin: Optional[date] = Query(default=None),
    inclure_admins: bool = Query(default=False),
) -> SuiviTempsOut:
    """Suivi d'ensemble du temps travaillé par employé sur une plage de
    dates : heures des feuilles de temps (pôle Entreprises) + heures de
    punch (Construction), jours travaillés, tâches terminées et ouvertes.
    Sans plage → la période de paie courante."""
    if debut is None or fin is None:
        debut = _periode_courante()
        fin = debut + timedelta(days=TIMESHEET_DAYS - 1)
    if fin < debut:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Plage de dates invalide.")
    if (fin - debut).days > 400:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Plage limitée à 400 jours.")

    users = await _utilisateurs_equipe(db, inclure_admins)
    ids = [u.id for u in users]
    employes = await _employes_par_email(db, [u.email for u in users])
    sheets, entries = await _feuilles_dans_plage(db, ids, debut, fin)
    heures_feuille = _heures_feuilles_par_jour(sheets, entries)

    # Punches Construction (fiche Employé liée par courriel).
    heures_punch: Dict[int, Dict[date, float]] = {}
    emp_vers_user = {
        employes[(u.email or "").lower()].id: u.id
        for u in users
        if (u.email or "").lower() in employes
    }
    if emp_vers_user:
        # Journées locales (Montréal) : un punch de 21 h compte pour le
        # jour où il a été fait, pas pour le lendemain UTC.
        d0 = datetime.combine(debut, time.min, tzinfo=TZ_LOCAL)
        d1 = datetime.combine(fin + timedelta(days=1), time.min, tzinfo=TZ_LOCAL)
        punches = (
            await db.execute(
                select(Punch).where(
                    Punch.employe_id.in_(list(emp_vers_user)),
                    Punch.ended_at.is_not(None),
                    Punch.started_at >= d0,
                    Punch.started_at < d1,
                )
            )
        ).scalars().all()
        for p in punches:
            uid = emp_vers_user.get(p.employe_id)
            if uid is None or not p.hours:
                continue
            jour = _aware(p.started_at).astimezone(TZ_LOCAL).date()
            cumul = heures_punch.setdefault(uid, {})
            cumul[jour] = cumul.get(jour, 0.0) + float(p.hours)

    taches = await _taches_par_assigne(db, ids)
    t0 = datetime.combine(debut, time.min, tzinfo=TZ_LOCAL)
    t1 = datetime.combine(fin + timedelta(days=1), time.min, tzinfo=TZ_LOCAL)

    lignes: List[SuiviTempsLigne] = []
    total = 0.0
    for u in users:
        hf = {j: h for j, h in heures_feuille.get(u.id, {}).items() if debut <= j <= fin}
        hp = heures_punch.get(u.id, {})
        somme_f = round(sum(hf.values()), 2)
        somme_p = round(sum(hp.values()), 2)
        mes_taches = taches.get(u.id, [])
        terminees = sum(
            1
            for t in mes_taches
            if t.status == TacheStatus.DONE.value
            and t.completed_at is not None
            and t0 <= _aware(t.completed_at) < t1
        )
        ouvertes = sum(1 for t in mes_taches if t.status != TacheStatus.DONE.value)
        jours = {j for j, h in hf.items() if h > 0} | {j for j, h in hp.items() if h > 0}
        total += somme_f + somme_p
        lignes.append(
            SuiviTempsLigne(
                user_id=u.id,
                display_name=u.display_name or u.email,
                type=_type_employe(u, employes.get((u.email or "").lower())),
                heures_feuille=somme_f,
                heures_punch=somme_p,
                heures_total=round(somme_f + somme_p, 2),
                jours_travailles=len(jours),
                taches_terminees=terminees,
                taches_ouvertes=ouvertes,
            )
        )
    return SuiviTempsOut(debut=debut, fin=fin, lignes=lignes, total_heures=round(total, 2))


# ── Section Employés : agenda d'un employé ──────────────────────────────


@router_admin.get("/{user_id}/agenda", response_model=List[EvenementOut])
async def agenda_employe(
    user_id: int,
    db: DBSession,
    _: RequireManager,
    debut: Optional[datetime] = Query(default=None),
    fin: Optional[datetime] = Query(default=None),
) -> List[EvenementOut]:
    """Événements d'un employé (assignés à son compte ou à sa fiche
    Construction) qui chevauchent la plage. Sans plage → les 60 prochains
    jours."""
    u, emp = await _charger_employe_zone(db, user_id)
    debut = debut or (_now() - timedelta(days=1))
    fin = fin or (debut + timedelta(days=60))
    if fin <= debut:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Plage invalide.")
    cibles = [AgendaEvent.assignee_user_id == u.id]
    if emp is not None:
        cibles.append(AgendaEvent.assignee_id == emp.id)
    rows = (
        await db.execute(
            select(AgendaEvent)
            .where(
                or_(*cibles),
                AgendaEvent.start_at < fin,
                or_(AgendaEvent.end_at > debut, AgendaEvent.end_at.is_(None)),
                AgendaEvent.start_at >= debut - timedelta(days=1),
            )
            .order_by(AgendaEvent.start_at.asc())
        )
    ).scalars().all()
    return [_evenement_out(e) for e in rows]


@router_admin.post(
    "/{user_id}/agenda",
    response_model=EvenementOut,
    status_code=status.HTTP_201_CREATED,
)
async def planifier_evenement(
    user_id: int, body: EvenementIn, db: DBSession, user: RequireManager
) -> EvenementOut:
    """Met un meeting, un tournage… dans l'agenda de l'employé. Il le voit
    dans sa zone employés et reçoit une notification (cloche + push)."""
    cible, _emp = await _charger_employe_zone(db, user_id)
    event_type = _valider_type(body.event_type)
    _valider_plage(body.start_at, body.end_at)
    ev = AgendaEvent(
        title=body.title.strip(),
        description=body.description,
        location=body.location,
        start_at=body.start_at,
        end_at=body.end_at,
        all_day=body.all_day,
        scope=SCOPE_ZONE,
        event_type=event_type,
        assignee_user_id=cible.id,
    )
    db.add(ev)
    await db.flush()
    await db.refresh(ev)
    try:
        from app.services.notifications import notify

        quand = ev.start_at.strftime("%Y-%m-%d %H:%M")
        await notify(
            db,
            user_id=cible.id,
            kind="agenda.planifie",
            title=f"À ton agenda : {ev.title}",
            body=f"{quand}" + (f" · {ev.location}" if ev.location else ""),
            href="/m/agenda",
        )
    except Exception as exc:  # noqa: BLE001 — la notification est best-effort
        log.warning("notification agenda zone employés échouée : %s", exc)
    await db.commit()
    return _evenement_out(ev)


async def _evenement_zone(db, event_id: int) -> AgendaEvent:
    ev = await db.get(AgendaEvent, event_id)
    if ev is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Événement introuvable.")
    if ev.scope != SCOPE_ZONE:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Cet événement appartient à l'agenda de Construction : "
            "modifie-le depuis cet agenda.",
        )
    return ev


@router_admin.patch("/agenda/{event_id}", response_model=EvenementOut)
async def modifier_evenement(
    event_id: int, body: EvenementPatch, db: DBSession, _: RequireManager
) -> EvenementOut:
    ev = await _evenement_zone(db, event_id)
    data = body.model_dump(exclude_unset=True)
    if "event_type" in data and data["event_type"] is not None:
        data["event_type"] = _valider_type(data["event_type"])
    if "title" in data and data["title"] is not None:
        data["title"] = data["title"].strip()
    for k, v in data.items():
        setattr(ev, k, v)
    _valider_plage(ev.start_at, ev.end_at)
    await db.commit()
    await db.refresh(ev)
    return _evenement_out(ev)


@router_admin.delete("/agenda/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
async def supprimer_evenement(event_id: int, db: DBSession, _: RequireManager) -> None:
    ev = await _evenement_zone(db, event_id)
    await db.delete(ev)
    await db.commit()


# ── Mes tâches (zone employés) ──────────────────────────────────────────


class MaTacheOut(BaseModel):
    id: int
    title: str
    description: Optional[str] = None
    status: str
    priority: str
    due_date: Optional[date] = None
    completed_at: Optional[datetime] = None
    entreprise_id: int
    entreprise_name: str
    entreprise_color: Optional[str] = None
    created_by_user_id: Optional[int] = None
    created_at: datetime
    updated_at: datetime
    position: int = 0
    assignee_user_ids: List[int] = Field(default_factory=list)
    #: L'employé peut supprimer SES tâches (créées par lui) ; celles qu'un
    #: gestionnaire lui a assignées se terminent, ne se suppriment pas.
    peut_supprimer: bool = False


class EntrepriseChoixOut(BaseModel):
    id: int
    name: str
    color_accent: Optional[str] = None


_PRIORITES = r"^(non_assigne|urgent|eleve|moyenne|faible)$"
_STATUTS = r"^(todo|a_faire|in_progress|waiting|done)$"


class MaTacheCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    entreprise_id: int
    description: Optional[str] = None
    due_date: Optional[date] = None
    priority: str = Field(default="non_assigne", pattern=_PRIORITES)
    status: str = Field(default=TacheStatus.A_FAIRE.value, pattern=_STATUTS)


class MaTacheUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=255)
    description: Optional[str] = None
    status: Optional[str] = Field(default=None, pattern=_STATUTS)
    priority: Optional[str] = Field(default=None, pattern=_PRIORITES)
    due_date: Optional[date] = None
    entreprise_id: Optional[int] = None
    position: Optional[int] = None


async def _entreprises_choisissables(db, user: User) -> List[Entreprise]:
    """Nos entreprises pour lesquelles l'employé peut se créer une tâche :
    celles de ses compagnies assignées dans la feuille de temps si un
    gestionnaire en a posé, sinon toutes les entreprises actives."""
    assignees = (
        await db.execute(
            select(TimesheetCompany.entreprise_id)
            .join(
                TimesheetUserCompany,
                TimesheetUserCompany.company_id == TimesheetCompany.id,
            )
            .where(
                TimesheetUserCompany.user_id == user.id,
                TimesheetCompany.entreprise_id.is_not(None),
            )
        )
    ).scalars().all()
    stmt = select(Entreprise).where(Entreprise.is_active.is_(True))
    if assignees:
        stmt = stmt.where(Entreprise.id.in_(list(assignees)))
    rows = (await db.execute(stmt)).scalars().all()
    return sorted(rows, key=lambda e: (e.position or 0, (e.name or "").lower()))


async def _ma_tache_ou_404(db, tache_id: int, user: User) -> EntrepriseTache:
    t = await db.get(EntrepriseTache, tache_id)
    if t is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tâche introuvable.")
    if t.assignee_user_id != user.id:
        co = (
            await db.execute(
                select(EntrepriseTacheAssignee.tache_id).where(
                    EntrepriseTacheAssignee.tache_id == t.id,
                    EntrepriseTacheAssignee.user_id == user.id,
                )
            )
        ).first()
        if co is None:
            # Même réponse qu'une tâche inexistante : on ne révèle pas les
            # tâches des autres.
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Tâche introuvable.")
    return t


def _peut_supprimer(t: EntrepriseTache, user: User) -> bool:
    return t.created_by_user_id == user.id or user.has_min_role("manager")


async def _ma_tache_out(db, t: EntrepriseTache, user: User, ent: Optional[Entreprise] = None) -> MaTacheOut:
    if ent is None:
        ent = await db.get(Entreprise, t.entreprise_id)
    assignes = (
        await db.execute(
            select(EntrepriseTacheAssignee.user_id).where(
                EntrepriseTacheAssignee.tache_id == t.id
            )
        )
    ).scalars().all()
    ids = list(dict.fromkeys(([t.assignee_user_id] if t.assignee_user_id else []) + list(assignes)))
    return MaTacheOut(
        id=t.id,
        title=t.title,
        description=t.description,
        status=t.status,
        priority=t.priority or "non_assigne",
        due_date=t.due_date,
        completed_at=t.completed_at,
        entreprise_id=t.entreprise_id,
        entreprise_name=ent.name if ent else "",
        entreprise_color=getattr(ent, "color_accent", None) if ent else None,
        created_by_user_id=t.created_by_user_id,
        created_at=t.created_at,
        updated_at=t.updated_at,
        position=int(t.position or 0),
        assignee_user_ids=ids,
        peut_supprimer=_peut_supprimer(t, user),
    )


@router_mes_taches.get("", response_model=List[MaTacheOut])
async def mes_taches(
    db: DBSession,
    user: CurrentUser,
    include_done: bool = Query(default=False),
) -> List[MaTacheOut]:
    """Les tâches de l'employé connecté (assigné principal ou co-assigné),
    classées : en traitement, à faire, en attente, à venir, puis terminées
    (si demandées)."""
    par_user = await _taches_par_assigne(db, [user.id])
    rows = par_user.get(user.id, [])
    if not include_done:
        rows = [t for t in rows if t.status != TacheStatus.DONE.value]
    rows.sort(
        key=lambda t: (
            _ORDRE_STATUTS.get(t.status, 9),
            t.due_date or date.max,
            int(t.position or 0),
            -t.id,
        )
    )
    ent_ids = {t.entreprise_id for t in rows}
    ents = {}
    if ent_ids:
        ents = {
            e.id: e
            for e in (
                await db.execute(select(Entreprise).where(Entreprise.id.in_(ent_ids)))
            ).scalars().all()
        }
    return [await _ma_tache_out(db, t, user, ents.get(t.entreprise_id)) for t in rows]


@router_mes_taches.get("/entreprises", response_model=List[EntrepriseChoixOut])
async def entreprises_pour_mes_taches(db: DBSession, user: CurrentUser) -> List[EntrepriseChoixOut]:
    rows = await _entreprises_choisissables(db, user)
    return [
        EntrepriseChoixOut(id=e.id, name=e.name, color_accent=getattr(e, "color_accent", None))
        for e in rows
    ]


@router_mes_taches.post("", response_model=MaTacheOut, status_code=status.HTTP_201_CREATED)
async def creer_ma_tache(body: MaTacheCreate, db: DBSession, user: CurrentUser) -> MaTacheOut:
    """L'employé se crée une tâche pour l'une de nos entreprises ; elle lui
    est assignée et il pourra la supprimer."""
    choix = {e.id: e for e in await _entreprises_choisissables(db, user)}
    ent = choix.get(body.entreprise_id)
    if ent is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Cette entreprise n'est pas disponible pour tes tâches.",
        )
    t = EntrepriseTache(
        entreprise_id=ent.id,
        title=body.title.strip(),
        description=body.description,
        status=body.status,
        priority=body.priority,
        due_date=body.due_date,
        assignee_user_id=user.id,
        created_by_user_id=user.id,
        completed_at=_now() if body.status == TacheStatus.DONE.value else None,
    )
    db.add(t)
    await db.flush()
    db.add(EntrepriseTacheAssignee(tache_id=t.id, user_id=user.id))
    await db.commit()
    await db.refresh(t)
    return await _ma_tache_out(db, t, user, ent)


@router_mes_taches.patch("/{tache_id}", response_model=MaTacheOut)
async def modifier_ma_tache(
    tache_id: int, body: MaTacheUpdate, db: DBSession, user: CurrentUser
) -> MaTacheOut:
    """Classer sa tâche : statut, priorité, échéance, entreprise, titre…"""
    t = await _ma_tache_ou_404(db, tache_id, user)
    data = body.model_dump(exclude_unset=True)
    if "entreprise_id" in data and data["entreprise_id"] is not None:
        choix = {e.id for e in await _entreprises_choisissables(db, user)}
        if data["entreprise_id"] not in choix:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Cette entreprise n'est pas disponible pour tes tâches.",
            )
    if "title" in data and data["title"] is not None:
        data["title"] = data["title"].strip()
    nouveau_statut = data.get("status")
    if nouveau_statut == TacheStatus.DONE.value and t.status != TacheStatus.DONE.value:
        t.completed_at = _now()
    elif nouveau_statut is not None and nouveau_statut != TacheStatus.DONE.value:
        t.completed_at = None
    for k, v in data.items():
        setattr(t, k, v)
    await db.commit()
    await db.refresh(t)
    return await _ma_tache_out(db, t, user)


@router_mes_taches.delete("/{tache_id}", status_code=status.HTTP_204_NO_CONTENT)
async def supprimer_ma_tache(tache_id: int, db: DBSession, user: CurrentUser) -> None:
    """Supprime une tâche que l'employé s'est créée. Une tâche assignée par
    un gestionnaire ne se supprime pas d'ici (on la termine)."""
    t = await _ma_tache_ou_404(db, tache_id, user)
    if not _peut_supprimer(t, user):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Cette tâche t'a été assignée par un gestionnaire : marque-la "
            "terminée plutôt que de la supprimer.",
        )
    await db.delete(t)
    await db.commit()
