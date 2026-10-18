"""Bloc-notes de la zone employés (Steven, bug 13, 2026-10-18).

    GET    /bloc-notes                — mes notes (vue=mienne), celles que
                                        j'ai envoyées (vue=envoyees) ou, pour
                                        un admin / propriétaire, toutes
                                        (vue=tous) ou celles d'un employé
                                        (user_id=…)
    GET    /bloc-notes/resume         — compteurs pour les badges (non lues,
                                        ouvertes) + droit d'envoi
    GET    /bloc-notes/destinataires  — admin / propriétaire : à qui envoyer
    POST   /bloc-notes                — écrire une note pour soi ou, admin /
                                        propriétaire, l'envoyer à un ou
                                        plusieurs employés (notification)
    POST   /bloc-notes/tout-lu        — marquer mes notes comme lues
    PATCH  /bloc-notes/{id}           — modifier le texte (auteur / admin)
                                        ou cocher « fait » (destinataire aussi)
    DELETE /bloc-notes/{id}           — auteur / admin

Transverse : aucune garde de pôle, tout compte connecté a son bloc-notes
(un employé Construction comme un employé « autre »). Seuls les admins et
propriétaires écrivent dans le bloc-notes de quelqu'un d'autre.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Dict, Iterable, List, Optional

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select, update

from app.api.deps import CurrentUser, DBSession
from app.models.bloc_note import BlocNote
from app.models.employe import Employe
from app.models.user import User

log = logging.getLogger(__name__)

router = APIRouter(prefix="/bloc-notes", tags=["bloc-notes"])

#: Vues de la liste.
VUES = ("mienne", "envoyees", "tous")

#: Type de notification envoyée au destinataire (cloche + push).
NOTIFICATION_KIND = "bloc_note"

#: Page mobile du bloc-notes (href des notifications).
HREF_BLOC_NOTES = "/m/notes"


# ── Schémas ─────────────────────────────────────────────────────────────


class BlocNoteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    titre: Optional[str]
    contenu: str
    echeance: Optional[date]
    fait: bool
    fait_le: Optional[datetime]
    #: NULL = pas encore ouverte par le destinataire (« Nouveau »).
    lu_le: Optional[datetime]
    created_at: datetime
    updated_at: datetime
    destinataire_user_id: int
    destinataire_nom: str
    auteur_user_id: Optional[int]
    auteur_nom: Optional[str]
    #: Raccourcis pour l'UI, calculés pour l'utilisateur connecté.
    pour_moi: bool
    de_moi: bool
    peut_modifier: bool
    peut_supprimer: bool


class BlocNoteIn(BaseModel):
    contenu: str = Field(min_length=1, max_length=5000)
    titre: Optional[str] = Field(default=None, max_length=255)
    echeance: Optional[date] = None
    #: Vide / absent = mon propre bloc-notes. Plusieurs ids = une note par
    #: employé (admin / propriétaire seulement).
    destinataire_user_ids: Optional[List[int]] = None


class BlocNoteUpdate(BaseModel):
    """Champs optionnels ; ``null`` explicite efface le titre / l'échéance."""

    contenu: Optional[str] = Field(default=None, max_length=5000)
    titre: Optional[str] = Field(default=None, max_length=255)
    echeance: Optional[date] = None
    fait: Optional[bool] = None


class ResumeOut(BaseModel):
    non_lues: int
    ouvertes: int
    peut_envoyer: bool


class DestinataireOut(BaseModel):
    id: int
    nom: str
    email: str
    role: str
    est_moi: bool


# ── Droits ──────────────────────────────────────────────────────────────


def peut_envoyer(user: User) -> bool:
    """Admin ou propriétaire : écrit dans le bloc-notes de n'importe qui
    et voit tous les blocs-notes (demande de Steven : « admin / proprio
    peut envoyer à n'importe qui »)."""
    return user.role in ("owner", "admin")


def _peut_voir(user: User, note: BlocNote) -> bool:
    return (
        note.destinataire_user_id == user.id
        or note.auteur_user_id == user.id
        or peut_envoyer(user)
    )


def _peut_modifier(user: User, note: BlocNote) -> bool:
    """Texte, titre, échéance et suppression : l'auteur ou un admin."""
    return note.auteur_user_id == user.id or peut_envoyer(user)


# ── Helpers ─────────────────────────────────────────────────────────────


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _noms_affichage(db, user_ids: Iterable[Optional[int]]) -> Dict[int, str]:
    """« Prénom Nom » du profil, sinon le nom de la fiche Employé
    Construction (même courriel), sinon la partie locale du courriel —
    même logique que la liste des utilisateurs."""
    ids = {i for i in user_ids if i is not None}
    if not ids:
        return {}
    users = (
        await db.execute(select(User).where(User.id.in_(ids)))
    ).scalars().all()
    return await _noms_pour(db, users)


async def _noms_pour(db, users: List[User]) -> Dict[int, str]:
    emails = {u.email.lower() for u in users if u.email}
    fiches: Dict[str, str] = {}
    if emails:
        rows = (
            await db.execute(
                select(Employe.email, Employe.full_name).where(
                    func.lower(Employe.email).in_(emails)
                )
            )
        ).all()
        fiches = {(e or "").lower(): fn for e, fn in rows if fn}
    noms: Dict[int, str] = {}
    for u in users:
        if u.first_name or u.last_name:
            noms[u.id] = u.display_name
        else:
            noms[u.id] = fiches.get((u.email or "").lower()) or u.display_name
    return noms


def _vers_out(note: BlocNote, user: User, noms: Dict[int, str]) -> BlocNoteOut:
    return BlocNoteOut(
        id=note.id,
        titre=note.titre,
        contenu=note.contenu,
        echeance=note.echeance,
        fait=bool(note.fait),
        fait_le=note.fait_le,
        lu_le=note.lu_le,
        created_at=note.created_at,
        updated_at=note.updated_at,
        destinataire_user_id=note.destinataire_user_id,
        destinataire_nom=noms.get(note.destinataire_user_id, "—"),
        auteur_user_id=note.auteur_user_id,
        auteur_nom=(
            noms.get(note.auteur_user_id) if note.auteur_user_id is not None else None
        ),
        pour_moi=(note.destinataire_user_id == user.id),
        de_moi=(note.auteur_user_id == user.id),
        peut_modifier=_peut_modifier(user, note),
        peut_supprimer=_peut_modifier(user, note),
    )


async def _sortir(db, notes: List[BlocNote], user: User) -> List[BlocNoteOut]:
    ids: set[Optional[int]] = set()
    for n in notes:
        ids.add(n.destinataire_user_id)
        ids.add(n.auteur_user_id)
    noms = await _noms_affichage(db, ids)
    return [_vers_out(n, user, noms) for n in notes]


def _cle_tri(note: BlocNote):
    """Ouvertes d'abord ; échéance la plus proche en tête (sans échéance
    ensuite) ; puis la plus récente."""
    return (
        1 if note.fait else 0,
        0 if note.echeance is not None else 1,
        note.echeance or date.max,
        -(note.created_at.timestamp() if note.created_at else 0),
    )


async def _charger(db, note_id: int, user: User) -> BlocNote:
    note = await db.get(BlocNote, note_id)
    if note is None or not _peut_voir(user, note):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Note introuvable.")
    return note


# ── Lecture ─────────────────────────────────────────────────────────────


@router.get("", response_model=List[BlocNoteOut])
async def lister_notes(
    db: DBSession,
    user: CurrentUser,
    vue: str = Query(default="mienne", description="mienne | envoyees | tous"),
    user_id: Optional[int] = Query(
        default=None,
        description="Bloc-notes d'un employé donné (admin / propriétaire).",
    ),
    include_fait: bool = Query(default=False),
) -> List[BlocNoteOut]:
    """Mon bloc-notes par défaut. ``vue=envoyees`` : ce que j'ai écrit dans
    le bloc-notes des autres. ``vue=tous`` / ``user_id`` : réservés aux
    admins et propriétaires, qui voient tous les blocs-notes."""
    vue = (vue or "mienne").strip().lower()
    if vue not in VUES:
        raise HTTPException(422, f"Vue inconnue : {', '.join(VUES)}.")
    stmt = select(BlocNote)
    if user_id is not None:
        if user_id != user.id and not peut_envoyer(user):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "Seuls les administrateurs et propriétaires voient le "
                "bloc-notes des autres.",
            )
        stmt = stmt.where(BlocNote.destinataire_user_id == user_id)
    elif vue == "envoyees":
        stmt = stmt.where(
            BlocNote.auteur_user_id == user.id,
            BlocNote.destinataire_user_id != user.id,
        )
    elif vue == "tous":
        if not peut_envoyer(user):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "Seuls les administrateurs et propriétaires voient tous "
                "les blocs-notes.",
            )
    else:
        stmt = stmt.where(BlocNote.destinataire_user_id == user.id)
    if not include_fait:
        stmt = stmt.where(BlocNote.fait.is_(False))
    rows = list((await db.execute(stmt)).scalars().all())
    rows.sort(key=_cle_tri)
    return await _sortir(db, rows, user)


@router.get("/resume", response_model=ResumeOut)
async def resume_notes(db: DBSession, user: CurrentUser) -> ResumeOut:
    """Compteurs de MON bloc-notes pour les badges du menu Plus et de
    l'accueil : notes jamais ouvertes et notes encore à faire."""
    ouvertes = (
        await db.execute(
            select(func.count(BlocNote.id)).where(
                BlocNote.destinataire_user_id == user.id,
                BlocNote.fait.is_(False),
            )
        )
    ).scalar_one()
    non_lues = (
        await db.execute(
            select(func.count(BlocNote.id)).where(
                BlocNote.destinataire_user_id == user.id,
                BlocNote.fait.is_(False),
                BlocNote.lu_le.is_(None),
            )
        )
    ).scalar_one()
    return ResumeOut(
        non_lues=int(non_lues or 0),
        ouvertes=int(ouvertes or 0),
        peut_envoyer=peut_envoyer(user),
    )


@router.get("/destinataires", response_model=List[DestinataireOut])
async def lister_destinataires(
    db: DBSession, user: CurrentUser
) -> List[DestinataireOut]:
    """Comptes actifs à qui un admin / propriétaire peut envoyer une
    note, triés par nom."""
    if not peut_envoyer(user):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Seuls les administrateurs et propriétaires peuvent envoyer "
            "une note à quelqu'un d'autre.",
        )
    users = (
        await db.execute(select(User).where(User.is_active.is_(True)))
    ).scalars().all()
    noms = await _noms_pour(db, list(users))
    out = [
        DestinataireOut(
            id=u.id,
            nom=noms.get(u.id) or u.display_name,
            email=u.email,
            role=u.role,
            est_moi=(u.id == user.id),
        )
        for u in users
    ]
    out.sort(key=lambda d: (not d.est_moi, d.nom.lower()))
    return out


# ── Écriture ────────────────────────────────────────────────────────────


@router.post(
    "", response_model=List[BlocNoteOut], status_code=status.HTTP_201_CREATED
)
async def creer_notes(
    body: BlocNoteIn, db: DBSession, user: CurrentUser
) -> List[BlocNoteOut]:
    """Écrit une note dans mon bloc-notes ou, pour un admin / propriétaire,
    dans celui d'un ou plusieurs employés (une note par destinataire,
    chacun notifié : cloche + push). Retourne les notes créées."""
    contenu = body.contenu.strip()
    if not contenu:
        raise HTTPException(
            422, "La note est vide."
        )
    titre = (body.titre or "").strip() or None
    cibles = list(dict.fromkeys(body.destinataire_user_ids or [])) or [user.id]
    if any(c != user.id for c in cibles) and not peut_envoyer(user):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Seuls les administrateurs et propriétaires peuvent envoyer "
            "une note à quelqu'un d'autre.",
        )
    comptes = {
        u.id: u
        for u in (
            await db.execute(select(User).where(User.id.in_(cibles)))
        ).scalars().all()
    }
    introuvables = [c for c in cibles if c not in comptes or not comptes[c].is_active]
    if introuvables:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "Employé introuvable ou inactif : "
            + ", ".join(str(c) for c in introuvables)
            + ".",
        )

    now = _now()
    notes: List[BlocNote] = []
    for cible in cibles:
        note = BlocNote(
            destinataire_user_id=cible,
            auteur_user_id=user.id,
            titre=titre,
            contenu=contenu,
            echeance=body.echeance,
            # Ma propre note n'a rien de « nouveau » pour moi.
            lu_le=now if cible == user.id else None,
        )
        db.add(note)
        notes.append(note)
    await db.flush()
    for note in notes:
        await db.refresh(note)

    autres = [n for n in notes if n.destinataire_user_id != user.id]
    if autres:
        noms = await _noms_affichage(db, [user.id])
        auteur = noms.get(user.id) or user.display_name
        apercu = titre or contenu
        if len(apercu) > 200:
            apercu = apercu[:197].rstrip() + "…"
        for note in autres:
            try:
                from app.services.notifications import notify

                await notify(
                    db,
                    user_id=note.destinataire_user_id,
                    kind=NOTIFICATION_KIND,
                    title=f"Note de {auteur}",
                    body=apercu,
                    href=HREF_BLOC_NOTES,
                )
            except Exception as exc:  # noqa: BLE001 — jamais bloquant
                log.warning("notification bloc-notes échouée : %s", exc)
    await db.commit()
    return await _sortir(db, notes, user)


@router.post("/tout-lu")
async def tout_lu(db: DBSession, user: CurrentUser) -> dict:
    """Le destinataire a ouvert son bloc-notes : plus rien de « Nouveau »."""
    res = await db.execute(
        update(BlocNote)
        .where(
            BlocNote.destinataire_user_id == user.id,
            BlocNote.lu_le.is_(None),
        )
        .values(lu_le=_now())
    )
    await db.flush()
    return {"updated": res.rowcount or 0}


@router.patch("/{note_id}", response_model=BlocNoteOut)
async def modifier_note(
    note_id: int, body: BlocNoteUpdate, db: DBSession, user: CurrentUser
) -> BlocNoteOut:
    """Cocher / décocher « fait » (destinataire, auteur ou admin) ; changer
    le texte, le titre ou l'échéance (auteur ou admin seulement)."""
    note = await _charger(db, note_id, user)
    champs = body.model_fields_set
    if champs & {"contenu", "titre", "echeance"} and not _peut_modifier(user, note):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Cette note t'a été envoyée : seul son auteur ou un "
            "administrateur peut en changer le texte. Tu peux la cocher.",
        )
    if "contenu" in champs:
        contenu = (body.contenu or "").strip()
        if not contenu:
            raise HTTPException(
                422, "La note est vide."
            )
        note.contenu = contenu
    if "titre" in champs:
        note.titre = (body.titre or "").strip() or None
    if "echeance" in champs:
        note.echeance = body.echeance
    if "fait" in champs and body.fait is not None and bool(body.fait) != bool(note.fait):
        note.fait = bool(body.fait)
        note.fait_le = _now() if body.fait else None
    if note.destinataire_user_id == user.id and note.lu_le is None:
        note.lu_le = _now()
    await db.flush()
    await db.refresh(note)
    return (await _sortir(db, [note], user))[0]


@router.delete("/{note_id}", status_code=status.HTTP_204_NO_CONTENT)
async def supprimer_note(
    note_id: int, db: DBSession, user: CurrentUser
) -> None:
    note = await _charger(db, note_id, user)
    if not _peut_modifier(user, note):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Cette note t'a été envoyée : seul son auteur ou un "
            "administrateur peut la supprimer. Coche-la plutôt comme faite.",
        )
    await db.delete(note)
    await db.flush()
