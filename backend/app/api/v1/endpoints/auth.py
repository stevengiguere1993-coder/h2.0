"""
Authentication endpoints.

Handles user login, registration, and profile retrieval.
"""

from typing import Annotated, Optional

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Response,
    UploadFile,
    status,
)
from fastapi.security import OAuth2PasswordRequestForm

from app.api.deps import CurrentAdmin, CurrentUser, DBSession
from app.schemas.token import Token
from app.schemas.user import UserCreate, UserRead
from app.services.auth import AuthService


router = APIRouter(prefix="/auth", tags=["authentication"])


@router.post(
    "/login",
    response_model=Token,
    summary="User login",
    description="Authenticate with email and password to receive an access token.",
)
async def login(
    db: DBSession,
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    remember_me: Annotated[bool, Form()] = False,
) -> Token:
    """
    Authenticate user and return access token.

    Uses OAuth2 password flow with email as username.

    - **username**: User's email address
    - **password**: User's password
    - **remember_me**: when True, the access token is valid for 12 h
      instead of the default short window (~30 min)
    """
    auth_service = AuthService(db)
    token = await auth_service.login(
        email=form_data.username,
        password=form_data.password,
        remember_me=remember_me,
    )

    if token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return token


@router.post(
    "/register",
    response_model=UserRead,
    status_code=status.HTTP_201_CREATED,
    summary="Register new user (admin only)",
    description="Create a new user account. Requires admin privileges.",
)
async def register(
    user_data: UserCreate,
    db: DBSession,
    current_admin: CurrentAdmin,
) -> UserRead:
    """
    Register a new user (admin only).

    Only administrators can create new user accounts.

    - **email**: Unique email address
    - **password**: Password (min 8 characters)
    - **is_admin**: Whether to grant admin privileges
    """
    auth_service = AuthService(db)
    user = await auth_service.register(user_data)

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered",
        )

    # Envoi du courriel d'accueil avec le mdp temporaire. Best-effort —
    # si le mailer n'est pas configuré ou tombe, on log et on continue.
    try:
        from app.services.welcome_email import send_welcome_email

        await send_welcome_email(
            to_email=user.email,
            temporary_password=user_data.password,
            role=user.role,
            created_by=current_admin.email,
        )
    except Exception:
        pass

    return UserRead.model_validate(user)


@router.get(
    "/me",
    response_model=UserRead,
    summary="Get current user",
    description="Retrieve the profile of the currently authenticated user.",
)
async def get_me(current_user: CurrentUser) -> UserRead:
    """
    Get current authenticated user's profile.

    Returns the user information associated with the provided access token.
    """
    return UserRead.model_validate(current_user)


# ---------- Password change (self-service) ----------

from pydantic import BaseModel, Field
from sqlalchemy import select

from app.core.security import get_password_hash, verify_password
from app.models.user import User


class PasswordChange(BaseModel):
    """Self-service password change. `current_password` is bypassable
    only when the user is on a forced first-login change."""

    current_password: str = Field(..., min_length=1, max_length=128)
    new_password: str = Field(..., min_length=8, max_length=128)


class MailerStatus(BaseModel):
    ready: bool
    tenant_configured: bool
    client_id_configured: bool
    client_secret_configured: bool
    sender_configured: bool
    sender: Optional[str] = None
    last_test_sent: Optional[bool] = None
    last_test_error: Optional[str] = None


@router.get(
    "/mailer-status",
    response_model=MailerStatus,
    summary="Diagnostique: est-ce que le mailer Microsoft Graph est configuré ?",
)
async def mailer_status(
    _: CurrentAdmin,
    test_to: Optional[str] = None,
) -> MailerStatus:
    """Admins can hit this to verify that Azure credentials are set
    and (optionally) that an actual send works. Pass ?test_to=email
    to try sending a small test email."""
    from app.core.config import settings as app_settings
    from app.integrations.email_graph import get_mailer

    mailer = get_mailer()
    out = MailerStatus(
        ready=mailer.ready,
        tenant_configured=bool(app_settings.azure_tenant_id),
        client_id_configured=bool(app_settings.azure_client_id),
        client_secret_configured=bool(app_settings.azure_client_secret),
        sender_configured=bool(app_settings.mail_from_email),
        sender=app_settings.mail_from_email,
    )
    if test_to and mailer.ready:
        try:
            await mailer.send(
                to=[test_to],
                subject="Test Horizon — mailer OK",
                html_body=(
                    "<p>Ce courriel confirme que l'intégration Microsoft "
                    "Graph est fonctionnelle pour Horizon.</p>"
                ),
                internal=True,
            )
            out.last_test_sent = True
        except Exception as exc:
            out.last_test_sent = False
            out.last_test_error = str(exc)[:500]
    return out


class ThemePreferenceUpdate(BaseModel):
    """Préférence visuelle du portail interne. 'light' = noir sur blanc,
    'dark' = blanc sur noir. Aucun effet sur la landing publique."""

    theme: str = Field(..., pattern="^(light|dark)$")


@router.patch(
    "/me/theme",
    response_model=UserRead,
    summary="Met à jour la préférence de thème de l'utilisateur courant",
)
async def update_my_theme(
    body: ThemePreferenceUpdate,
    db: DBSession,
    current_user: CurrentUser,
) -> UserRead:
    u = (
        await db.execute(select(User).where(User.id == current_user.id))
    ).scalar_one()
    u.theme_preference = body.theme
    await db.flush()
    await db.refresh(u)
    return UserRead.model_validate(u)


# ---------- Profil utilisateur (Prénom / Nom / Photo) ----------


#: Palette autorisée pour la couleur de profil. Clés courtes ;
#: leur traduction Tailwind est gérée côté frontend.
PROFILE_COLOR_PATTERN = (
    r"^(violet|rose|pink|red|orange|amber|yellow|lime|green|"
    r"emerald|teal|cyan|sky|blue|indigo|fuchsia|slate)$"
)


class ProfileUpdate(BaseModel):
    """Mise à jour du profil — Prénom, Nom, et couleur de profil.
    La photo passe par /me/avatar (multipart)."""

    first_name: Optional[str] = Field(default=None, max_length=100)
    last_name: Optional[str] = Field(default=None, max_length=100)
    # `None` explicite (à différencier d'« absent ») permet à
    # l'utilisateur de revenir au neutre. Pydantic v2 + exclude_unset
    # garde la nuance.
    profile_color: Optional[str] = Field(
        default=None, pattern=PROFILE_COLOR_PATTERN
    )
    # Mobile perso pour le click-to-call (chaîne vide = effacer). On
    # accepte un format libre (514-961-9015, (514) 961-9015…) et on
    # normalise en E.164 côté serveur.
    phone_e164: Optional[str] = Field(default=None, max_length=32)


def _normalize_phone_e164(raw: str) -> str:
    """Normalise un numéro NANP en E.164 (+1XXXXXXXXXX). Tolérant aux
    espaces / parenthèses / tirets. Renvoie '' si vide/inexploitable."""
    s = (raw or "").strip()
    if not s:
        return ""
    if s.startswith("+"):
        digits = "".join(c for c in s[1:] if c.isdigit())
        return f"+{digits}" if digits else ""
    digits = "".join(c for c in s if c.isdigit())
    if len(digits) == 10:
        return f"+1{digits}"
    if len(digits) == 11 and digits.startswith("1"):
        return f"+{digits}"
    if len(digits) >= 8:
        return f"+{digits}"
    return ""


@router.patch(
    "/me/profile",
    response_model=UserRead,
    summary="Mettre à jour mon profil (prénom + nom)",
)
async def update_my_profile(
    body: ProfileUpdate,
    db: DBSession,
    current_user: CurrentUser,
) -> UserRead:
    u = (
        await db.execute(select(User).where(User.id == current_user.id))
    ).scalar_one()
    # On accepte la chaîne vide → NULL (l'utilisateur peut effacer son
    # prénom ou nom). exclude_unset garantit qu'on ne remet pas les
    # champs absents à NULL par accident.
    fields = body.model_dump(exclude_unset=True)
    # Le numéro de mobile est normalisé en E.164 (et '' => NULL).
    if "phone_e164" in fields:
        raw = fields.pop("phone_e164")
        u.phone_e164 = _normalize_phone_e164(raw) or None
    for k, v in fields.items():
        if v == "":
            v = None
        elif isinstance(v, str):
            v = v.strip()
        setattr(u, k, v)
    await db.flush()
    await db.refresh(u)
    return UserRead.model_validate(u)


# Limite raisonnable côté serveur — Render a un body limit aussi mais
# on coupe avant pour donner une erreur claire.
MAX_AVATAR_BYTES = 4 * 1024 * 1024  # 4 Mo
ALLOWED_AVATAR_TYPES = {"image/jpeg", "image/png", "image/webp"}


@router.post(
    "/me/avatar",
    response_model=UserRead,
    summary="Uploader ma photo de profil",
)
async def upload_my_avatar(
    db: DBSession,
    current_user: CurrentUser,
    file: UploadFile = File(...),
) -> UserRead:
    if file.content_type not in ALLOWED_AVATAR_TYPES:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            "Format non supporté — JPEG, PNG ou WEBP uniquement.",
        )
    data = await file.read()
    if len(data) > MAX_AVATAR_BYTES:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"Image trop grosse — max {MAX_AVATAR_BYTES // 1024 // 1024} Mo.",
        )
    u = (
        await db.execute(select(User).where(User.id == current_user.id))
    ).scalar_one()
    u.avatar_image = data
    u.avatar_content_type = file.content_type
    await db.flush()
    await db.refresh(u)
    return UserRead.model_validate(u)


@router.delete(
    "/me/avatar",
    response_model=UserRead,
    summary="Retirer ma photo de profil",
)
async def delete_my_avatar(
    db: DBSession,
    current_user: CurrentUser,
) -> UserRead:
    u = (
        await db.execute(select(User).where(User.id == current_user.id))
    ).scalar_one()
    u.avatar_image = None
    u.avatar_content_type = None
    await db.flush()
    await db.refresh(u)
    return UserRead.model_validate(u)


@router.get(
    "/me/avatar",
    summary="Récupérer ma photo de profil",
    responses={
        200: {"content": {"image/*": {}}},
        404: {"description": "Aucune photo"},
    },
)
async def get_my_avatar(
    db: DBSession,
    current_user: CurrentUser,
) -> Response:
    u = (
        await db.execute(select(User).where(User.id == current_user.id))
    ).scalar_one()
    if not u.avatar_image:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Aucune photo")
    return Response(
        content=u.avatar_image,
        media_type=u.avatar_content_type or "image/jpeg",
        headers={"Cache-Control": "private, max-age=300"},
    )


@router.get(
    "/users/{user_id}/avatar",
    summary="Récupérer la photo de profil d'un autre utilisateur",
    responses={
        200: {"content": {"image/*": {}}},
        404: {"description": "Aucune photo"},
    },
)
async def get_user_avatar(
    user_id: int,
    db: DBSession,
    _: CurrentUser,
) -> Response:
    u = (
        await db.execute(select(User).where(User.id == user_id))
    ).scalar_one_or_none()
    if u is None or not u.avatar_image:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Aucune photo")
    return Response(
        content=u.avatar_image,
        media_type=u.avatar_content_type or "image/jpeg",
        headers={"Cache-Control": "private, max-age=300"},
    )


@router.post(
    "/change-password",
    response_model=UserRead,
    summary="Change my own password",
)
async def change_password(
    body: PasswordChange,
    db: DBSession,
    current_user: CurrentUser,
) -> UserRead:
    u = (
        await db.execute(select(User).where(User.id == current_user.id))
    ).scalar_one()
    if not verify_password(body.current_password, u.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Mot de passe actuel incorrect.",
        )
    if body.new_password == body.current_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Le nouveau mot de passe doit être différent.",
        )
    u.hashed_password = get_password_hash(body.new_password)
    u.must_change_password = False
    await db.flush()
    await db.refresh(u)
    return UserRead.model_validate(u)
