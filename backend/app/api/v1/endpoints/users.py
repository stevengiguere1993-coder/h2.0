"""User management — owner-only.

    GET    /api/v1/users                   — list all users
    POST   /api/v1/users                   — create a user (admin/owner)
    PATCH  /api/v1/users/{id}/role         — change role
    PATCH  /api/v1/users/{id}/volets       — change accessible volets
    POST   /api/v1/users/{id}/deactivate   — disable account
    POST   /api/v1/users/{id}/activate     — re-enable account
    GET    /api/v1/users/{id}/projects     — project members for this user
    PUT    /api/v1/users/{id}/projects     — set assigned projects (bulk)
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy import delete, func, insert, select

from app.api.deps import CurrentUser, DBSession, RequireAdminRole, RequireOwner
from app.core.security import get_password_hash
from app.models.employe import Employe
from app.models.project import Project
from app.models.project_member import ProjectMember
from app.models.user import (
    DEFAULT_VOLETS,
    User,
    UserRole,
    VALID_VOLETS,
)

log = logging.getLogger(__name__)

TEMPORARY_PASSWORD = "Horizon"


router = APIRouter(prefix="/users", tags=["users-admin"])


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    email: str
    is_active: bool
    is_admin: bool
    role: str
    created_at: datetime
    # Tiré de la table Employe (match sur email, insensible à la casse).
    # Sert à afficher « Olivier Therrien » plutôt que l'adresse email
    # partout dans l'UI (équipe projet, sélecteurs, etc.).
    full_name: Optional[str] = None
    # Volets accessibles (construction / prospection).
    volets: List[str] = Field(default_factory=lambda: list(DEFAULT_VOLETS))
    can_assign_others: bool = False
    # Profil utilisateur — affichage dans les pastilles d'assignation,
    # listes, etc. Le frontend utilise display_name + profile_color +
    # has_avatar pour rendre une pastille personnalisée.
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    display_name: str = ""
    profile_color: Optional[str] = None
    has_avatar: bool = False


async def _user_full_names(db, users: List[User]) -> dict[int, str]:
    if not users:
        return {}
    emails = {u.email.lower() for u in users if u.email}
    if not emails:
        return {}
    rows = (
        await db.execute(
            select(Employe.email, Employe.full_name).where(
                func.lower(Employe.email).in_(emails)
            )
        )
    ).all()
    by_email = {(e or "").lower(): fn for e, fn in rows if fn}
    return {
        u.id: by_email[u.email.lower()]
        for u in users
        if u.email and u.email.lower() in by_email
    }


def _user_read(u: User, full_name: Optional[str]) -> UserRead:
    return UserRead(
        id=u.id,
        email=u.email,
        is_active=u.is_active,
        is_admin=u.is_admin,
        role=u.role,
        created_at=u.created_at,
        full_name=full_name,
        volets=u.volets,
        can_assign_others=bool(getattr(u, "can_assign_others", False)),
        # Profil — propage les nouveaux champs sinon les sélecteurs
        # d'assignation retombent sur l'email faute de display_name.
        first_name=u.first_name,
        last_name=u.last_name,
        display_name=u.display_name,
        profile_color=u.profile_color,
        has_avatar=u.has_avatar,
    )


def _validate_volets(volets: List[str]) -> List[str]:
    """Normalise + valide la liste de volets. Retire les doublons et
    les valeurs inconnues. Doit contenir au moins un volet."""
    cleaned = sorted({v for v in volets if v in VALID_VOLETS})
    if not cleaned:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Au moins un volet requis parmi {list(VALID_VOLETS)}.",
        )
    return cleaned


class RoleUpdate(BaseModel):
    role: str = Field(..., pattern="^(owner|admin|manager|employee)$")


class VoletsUpdate(BaseModel):
    volets: List[str] = Field(
        ...,
        description="Liste des volets accessibles : construction, prospection",
    )


class UserCreate(BaseModel):
    """Création directe d'un compte (sans création d'Employe associé).
    Utilisé pour ajouter un prospecteur, un manager qui n'est pas un
    travailleur de chantier, etc.

    Le mot de passe temporaire « Horizon » est appliqué + courriel
    d'accueil envoyé. L'utilisateur sera forcé de changer son mdp à
    sa première connexion.
    """

    email: EmailStr
    full_name: Optional[str] = Field(default=None, max_length=255)
    role: str = Field(
        default=UserRole.EMPLOYEE.value,
        pattern="^(owner|admin|manager|employee)$",
    )
    volets: List[str] = Field(
        default_factory=lambda: list(DEFAULT_VOLETS),
        description="Volets accessibles (construction / prospection).",
    )


class UserCreatedRead(UserRead):
    """Réponse à POST /users : inclut le diagnostic d'envoi du mail."""

    welcome_email_sent: bool = False
    welcome_email_error: Optional[str] = None


class ProjectAssignments(BaseModel):
    project_ids: List[int]


class ProjectMini(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    address: Optional[str] = None
    status: Optional[str] = None


@router.get("", response_model=List[UserRead])
async def list_users(db: DBSession, _: CurrentUser) -> List[UserRead]:
    """Liste plate de tous les utilisateurs.

    Accessible à tout utilisateur connecté — les sélecteurs
    d'assignation (Pipeline, agenda, etc.) en ont besoin pour
    afficher la liste des coéquipiers. Les données retournées
    sont basiques (identifiant, courriel, profil) ; aucun secret
    n'est exposé. Les actions de création/modification/suppression
    restent réservées aux owners ou admins.
    """
    rows = (
        await db.execute(select(User).order_by(User.email.asc()))
    ).scalars().all()
    names = await _user_full_names(db, list(rows))
    return [_user_read(r, names.get(r.id)) for r in rows]


@router.post(
    "",
    response_model=UserCreatedRead,
    status_code=status.HTTP_201_CREATED,
    summary="Crée un compte utilisateur (mot de passe temporaire « Horizon »)",
)
async def create_user(
    data: UserCreate, db: DBSession, admin: RequireAdminRole
) -> UserCreatedRead:
    email_norm = data.email.lower().strip()
    existing = (
        await db.execute(select(User).where(User.email == email_norm))
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Un compte existe déjà pour ce courriel.",
        )

    volets = _validate_volets(data.volets)

    u = User(
        email=email_norm,
        hashed_password=get_password_hash(TEMPORARY_PASSWORD),
        is_active=True,
        is_admin=data.role in (UserRole.OWNER.value, UserRole.ADMIN.value),
        role=data.role,
        must_change_password=True,
        volets_json=json.dumps(volets),
    )
    db.add(u)
    await db.flush()

    # Crée aussi un Employe « miroir » si le full_name est fourni —
    # permet de réutiliser le UserRead.full_name sans logique parallèle.
    if data.full_name:
        emp = Employe(email=email_norm, full_name=data.full_name)
        db.add(emp)
        await db.flush()

    welcome_email_sent = False
    welcome_email_error: Optional[str] = None
    try:
        from app.services.welcome_email import send_welcome_email

        welcome_email_sent = await send_welcome_email(
            to_email=email_norm,
            temporary_password=TEMPORARY_PASSWORD,
            full_name=data.full_name,
            role=data.role,
            created_by=admin.email,
        )
        if not welcome_email_sent:
            welcome_email_error = (
                "Mailer non disponible (Azure Graph non configuré "
                "ou courriel invalide)."
            )
    except Exception as exc:
        log.exception("welcome email failed: %s", exc)
        welcome_email_error = f"Erreur mailer : {exc}"

    out = UserCreatedRead(
        id=u.id,
        email=u.email,
        is_active=u.is_active,
        is_admin=u.is_admin,
        role=u.role,
        created_at=u.created_at,
        full_name=data.full_name,
        volets=u.volets,
        welcome_email_sent=welcome_email_sent,
        welcome_email_error=welcome_email_error,
    )
    return out


@router.patch("/{user_id}/role", response_model=UserRead)
async def update_role(
    user_id: int,
    data: RoleUpdate,
    db: DBSession,
    owner: RequireOwner,
) -> UserRead:
    u = (
        await db.execute(select(User).where(User.id == user_id))
    ).scalar_one_or_none()
    if u is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    # Owners can't demote themselves to prevent locking out the account.
    if u.id == owner.id and data.role != UserRole.OWNER.value:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Tu ne peux pas rétrograder ton propre compte.",
        )
    u.role = data.role
    # Keep the legacy is_admin flag in sync so old code paths still work.
    u.is_admin = data.role in (UserRole.OWNER.value, UserRole.ADMIN.value)
    await db.flush()
    await db.refresh(u)
    return _user_read(u, None)


@router.patch("/{user_id}/volets", response_model=UserRead)
async def update_volets(
    user_id: int,
    data: VoletsUpdate,
    db: DBSession,
    _: RequireAdminRole,
) -> UserRead:
    u = (
        await db.execute(select(User).where(User.id == user_id))
    ).scalar_one_or_none()
    if u is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    cleaned = _validate_volets(data.volets)
    u.volets_json = json.dumps(cleaned)
    await db.flush()
    await db.refresh(u)
    return _user_read(u, None)


class CanAssignUpdate(BaseModel):
    can_assign_others: bool


@router.patch("/{user_id}/can-assign-others", response_model=UserRead)
async def update_can_assign_others(
    user_id: int,
    data: CanAssignUpdate,
    db: DBSession,
    _: RequireOwner,
) -> UserRead:
    """Toggle la permission spéciale d'assigner des RDV agenda à
    d'autres utilisateurs (cas : un employé prospecteur qui a besoin
    de planifier des RDV pour son boss). Owner uniquement."""
    u = (
        await db.execute(select(User).where(User.id == user_id))
    ).scalar_one_or_none()
    if u is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    u.can_assign_others = bool(data.can_assign_others)
    await db.flush()
    await db.refresh(u)
    return _user_read(u, None)


@router.post("/{user_id}/deactivate", response_model=UserRead)
async def deactivate(
    user_id: int,
    db: DBSession,
    owner: RequireOwner,
) -> UserRead:
    if user_id == owner.id:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Tu ne peux pas te désactiver."
        )
    u = (
        await db.execute(select(User).where(User.id == user_id))
    ).scalar_one_or_none()
    if u is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    u.is_active = False
    await db.flush()
    await db.refresh(u)
    return UserRead.model_validate(u)


@router.post("/{user_id}/activate", response_model=UserRead)
async def activate(
    user_id: int,
    db: DBSession,
    _: RequireOwner,
) -> UserRead:
    u = (
        await db.execute(select(User).where(User.id == user_id))
    ).scalar_one_or_none()
    if u is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    u.is_active = True
    await db.flush()
    await db.refresh(u)
    return UserRead.model_validate(u)


# ---------- Password management (admin / owner) ----------

class SetPasswordBody(BaseModel):
    """Admin sets a user's password directly. If `must_change` is True,
    the user is forced to change it at next login. `send_email` envoie
    automatiquement un courriel d'accueil avec le nouveau mot de passe."""

    password: str = Field(..., min_length=8, max_length=128)
    must_change: bool = Field(default=True)
    send_email: bool = Field(default=True)


class SetPasswordResponse(UserRead):
    """Réponse à set-password : on étend UserRead avec le diagnostic
    d'envoi du courriel (utile pour distinguer un mailer KO d'une
    réinitialisation réussie côté UI)."""

    welcome_email_sent: bool = False
    welcome_email_error: Optional[str] = None


@router.post("/{user_id}/set-password", response_model=SetPasswordResponse)
async def set_password(
    user_id: int,
    body: SetPasswordBody,
    db: DBSession,
    admin: RequireAdminRole,
) -> SetPasswordResponse:
    u = (
        await db.execute(select(User).where(User.id == user_id))
    ).scalar_one_or_none()
    if u is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    u.hashed_password = get_password_hash(body.password)
    u.must_change_password = body.must_change
    await db.flush()
    await db.refresh(u)

    welcome_email_sent = False
    welcome_email_error: Optional[str] = None
    if body.send_email and u.email:
        try:
            from app.services.welcome_email import send_welcome_email

            welcome_email_sent = await send_welcome_email(
                to_email=u.email,
                temporary_password=body.password,
                role=u.role,
                created_by=admin.email,
            )
            if not welcome_email_sent:
                welcome_email_error = (
                    "Mailer non disponible (Azure Graph non configuré, "
                    "courriel invalide, ou échec d'envoi). Voir logs."
                )
        except Exception as exc:
            log.exception("set-password welcome email failed: %s", exc)
            welcome_email_error = f"Erreur mailer : {str(exc)[:200]}"
    elif body.send_email and not u.email:
        welcome_email_error = "L'utilisateur n'a pas d'adresse courriel."

    base = _user_read(u, None)
    return SetPasswordResponse(
        **base.model_dump(),
        welcome_email_sent=welcome_email_sent,
        welcome_email_error=welcome_email_error,
    )


@router.delete(
    "/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Supprimer définitivement un compte utilisateur (owner)",
)
async def delete_user(
    user_id: int,
    db: DBSession,
    owner: RequireOwner,
) -> None:
    """Hard-delete : supprime la ligne. Les FK pointant vers ce user
    (ProjectMember, Notifications, AuditLog, AvailabilitySlot, feed
    iCal…) sont géré·es par les ON DELETE de leurs propres déclarations
    (CASCADE ou SET NULL).

    Sécurités :
      - Un owner ne peut pas se supprimer lui-même
      - On bloque la suppression du dernier owner actif (sinon plus
        personne ne peut gérer les rôles)
    """
    if user_id == owner.id:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Tu ne peux pas supprimer ton propre compte.",
        )
    u = (
        await db.execute(select(User).where(User.id == user_id))
    ).scalar_one_or_none()
    if u is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")

    if u.role == UserRole.OWNER.value:
        # Compte les autres owners actifs encore présents.
        from sqlalchemy import func

        remaining = (
            await db.execute(
                select(func.count(User.id)).where(
                    User.role == UserRole.OWNER.value,
                    User.is_active.is_(True),
                    User.id != user_id,
                )
            )
        ).scalar_one()
        if int(remaining or 0) == 0:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Impossible de supprimer le dernier propriétaire actif. "
                "Crée un autre owner d'abord.",
            )

    await db.delete(u)
    await db.flush()


@router.post("/{user_id}/force-password-change", response_model=UserRead)
async def force_password_change(
    user_id: int,
    db: DBSession,
    _: RequireAdminRole,
) -> UserRead:
    """Just flips the must_change_password flag without rotating the
    password. Used when an admin wants to invite a user to update an
    expired password without choosing a new one for them."""
    u = (
        await db.execute(select(User).where(User.id == user_id))
    ).scalar_one_or_none()
    if u is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    u.must_change_password = True
    await db.flush()
    await db.refresh(u)
    return UserRead.model_validate(u)


@router.get("/{user_id}/projects", response_model=List[ProjectMini])
async def get_user_projects(
    user_id: int,
    db: DBSession,
    _: RequireOwner,
) -> List[ProjectMini]:
    stmt = (
        select(Project)
        .join(ProjectMember, ProjectMember.project_id == Project.id)
        .where(ProjectMember.user_id == user_id)
        .order_by(Project.name.asc())
    )
    rows = (await db.execute(stmt)).scalars().all()
    return [ProjectMini.model_validate(r) for r in rows]


@router.put("/{user_id}/projects", response_model=List[int])
async def set_user_projects(
    user_id: int,
    data: ProjectAssignments,
    db: DBSession,
    _: RequireOwner,
) -> List[int]:
    """Replace the user's project assignments with the given set.
    Returns the IDs persisted."""
    u = (
        await db.execute(select(User).where(User.id == user_id))
    ).scalar_one_or_none()
    if u is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")

    # Validate all project ids exist so we don't silently accept typos.
    if data.project_ids:
        existing = (
            await db.execute(
                select(Project.id).where(Project.id.in_(data.project_ids))
            )
        ).all()
        existing_ids = {int(r[0]) for r in existing}
        unknown = set(data.project_ids) - existing_ids
        if unknown:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"Projet(s) inconnu(s): {sorted(unknown)}",
            )

    # Wipe and reinsert — simpler than computing a diff for a handful of rows.
    await db.execute(
        delete(ProjectMember).where(ProjectMember.user_id == user_id)
    )
    if data.project_ids:
        await db.execute(
            insert(ProjectMember),
            [
                {"user_id": user_id, "project_id": pid}
                for pid in set(data.project_ids)
            ],
        )
    await db.flush()
    return list(set(data.project_ids))
