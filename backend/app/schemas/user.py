"""
Pydantic schemas for User operations.

These schemas handle validation and serialization for user-related API operations.
"""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field, computed_field


class UserBase(BaseModel):
    """Base user schema with common fields."""

    email: EmailStr


class UserCreate(UserBase):
    """
    Schema for creating a new user.

    Used by POST /auth/register endpoint.
    """

    password: str = Field(
        ...,
        min_length=8,
        max_length=128,
        description="Password must be between 8 and 128 characters",
    )
    is_admin: bool = Field(
        default=False,
        description="Whether the user should have admin privileges",
    )
    role: Optional[str] = Field(
        default=None,
        pattern="^(owner|admin|manager|employee)$",
        description=(
            "Rôle à assigner — si absent, l'employé par défaut; si "
            "`is_admin` est True et `role` vide, on fallback à 'admin'."
        ),
    )


class UserLogin(BaseModel):
    """
    Schema for user login.

    Used by POST /auth/login endpoint.
    """

    email: EmailStr
    password: str


class UserRead(UserBase):
    """
    Schema for reading user data.

    Used in API responses. Does not include sensitive data like password.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    is_active: bool
    is_admin: bool
    role: str = "employee"
    must_change_password: bool = False
    created_at: datetime
    # Préférence visuelle du portail. 'light' (noir sur blanc, défaut)
    # ou 'dark' (blanc sur noir). Persistée par utilisateur en DB.
    theme_preference: str = "light"
    # Accès configurables (capacités) exposés au front pour le gating de
    # pages sensibles — P-05d. Ex. {"telephonie.access": true,
    # "devlog.access": false}. Calculé dans /auth/me.
    access: dict[str, bool] = Field(default_factory=dict)
    # Volets accessibles à l'utilisateur. Calculé côté ORM par la
    # propriété User.volets : combine volets_json + whitelists des
    # volets en développement (entreprises/immobilier/investisseur).
    volets: List[str] = Field(default_factory=list)
    # Profil — Prénom + Nom optionnels. NULL si pas encore renseignés.
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    # True quand l'utilisateur a uploadé une photo de profil. Le
    # binaire est servi via GET /api/v1/auth/me/avatar (ou par id
    # pour les autres). On expose juste le booléen ici pour éviter
    # de transporter les bytes dans chaque /me.
    has_avatar: bool = False
    # Couleur de profil — clé courte (violet, rose, emerald…). NULL =
    # neutre. Sert à teinter la pastille d'assignation côté frontend.
    profile_color: Optional[str] = None
    # Mobile perso (E.164) pour le click-to-call. NULL si non renseigné.
    phone_e164: Optional[str] = None
    # Nom d'affichage dérivé : « Prénom Nom » si renseignés, sinon la
    # partie locale du courriel. La propriété est calculée côté ORM
    # (User.display_name) et lue automatiquement via from_attributes.
    display_name: str = ""


class UserUpdate(BaseModel):
    """
    Schema for updating user data.

    All fields are optional.
    """

    email: Optional[EmailStr] = None
    password: Optional[str] = Field(
        default=None,
        min_length=8,
        max_length=128,
    )
    is_active: Optional[bool] = None
    is_admin: Optional[bool] = None
