"""
FastAPI Dependencies for authentication and authorization.

These dependencies handle token validation and user retrieval
for protected endpoints.

Mode APERÇU « voir comme cet utilisateur » (lecture seule) : un admin/owner
peut obtenir, via ``POST /users/{id}/apercu``, un jeton émis AU NOM d'un
autre utilisateur (``sub`` = l'utilisateur regardé) qui porte en plus la
revendication ``apercu_par`` = id de l'admin qui regarde. ``get_current_user``
reconnaît ce jeton, expose l'id de l'admin dans ``request.state.apercu_par``
(lu par ``apercu_par_de``, consommé par ``/auth/me``) et REFUSE toute
méthode HTTP autre que GET/HEAD/OPTIONS (403) : un aperçu ne peut jamais
modifier des données, peu importe les droits de l'utilisateur regardé.
"""

from typing import Annotated, Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import verify_token
from app.db.session import get_db
from app.models.user import User
from app.repositories.user import UserRepository


# OAuth2 scheme for Bearer token authentication
oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl="/api/v1/auth/login",
    auto_error=True,
)


#: Méthodes HTTP permises à un jeton d'APERÇU — lecture seule stricte.
#: Tout le reste (POST, PUT, PATCH, DELETE…) est refusé en 403 avant même
#: d'atteindre l'endpoint, quels que soient les droits de l'utilisateur
#: regardé.
APERCU_METHODES_LECTURE = frozenset({"GET", "HEAD", "OPTIONS"})


async def get_current_user(
    request: Request,
    token: Annotated[str, Depends(oauth2_scheme)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    """
    Dependency to get the current authenticated user.

    Validates the JWT token and returns the corresponding user.

    Mode APERÇU (lecture seule) : si le jeton porte la revendication
    ``apercu_par`` — jeton émis par ``POST /users/{id}/apercu`` pour qu'un
    admin/owner voie Kratos « comme » un autre utilisateur —, l'utilisateur
    retourné est bien l'utilisateur REGARDÉ (``sub``), l'id de l'admin qui
    regarde est posé dans ``request.state.apercu_par`` (lu par
    ``apercu_par_de``), et toute méthode autre que GET/HEAD/OPTIONS est
    refusée (403). Un aperçu ne peut donc JAMAIS écrire, même si
    l'utilisateur regardé en aurait le droit.

    Args:
        request: Requête courante (méthode HTTP + état par requête)
        token: JWT access token from Authorization header
        db: Database session

    Returns:
        The authenticated User

    Raises:
        HTTPException: 401 if token is invalid or user not found ;
            403 si un jeton d'aperçu tente autre chose qu'une lecture
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    # Decode and validate token — payload COMPLET : il faut lire les
    # revendications au-delà de ``sub`` pour reconnaître un jeton d'aperçu.
    payload = verify_token(token)
    if payload is None:
        raise credentials_exception

    user_id_str = payload.get("sub")
    if user_id_str is None:
        raise credentials_exception

    try:
        user_id = int(user_id_str)
    except (TypeError, ValueError):
        raise credentials_exception

    # Get user from database
    user_repo = UserRepository(db)
    user = await user_repo.get_by_id(user_id)

    if user is None:
        raise credentials_exception

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account is inactive",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Jeton d'APERÇU « voir comme » : on mémorise QUI regarde (pour
    # /auth/me et le bandeau frontend) et on verrouille en lecture seule.
    # ``is not None`` (et pas la vérité booléenne) : un ``apercu_par``
    # présent, même farfelu, ne doit jamais faire retomber le jeton dans
    # le mode normal (avec droits d'écriture).
    apercu_par = payload.get("apercu_par")
    if apercu_par is not None:
        try:
            request.state.apercu_par = int(apercu_par)
        except (TypeError, ValueError):
            raise credentials_exception
        if request.method.upper() not in APERCU_METHODES_LECTURE:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "Mode aperçu (lecture seule) : impossible de modifier "
                    "des données en voyant Kratos comme un autre "
                    "utilisateur. Quitte l'aperçu pour agir."
                ),
            )

    return user


def apercu_par_de(request: Request) -> Optional[int]:
    """Id de l'admin/owner qui regarde Kratos « comme » l'utilisateur
    courant (mode aperçu lecture seule), posé par ``get_current_user``
    quand le jeton porte ``apercu_par`` ; ``None`` hors aperçu (jeton
    normal, ou endpoint qui ne passe pas par ``get_current_user``)."""
    return getattr(request.state, "apercu_par", None)


async def get_current_admin(
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    """Legacy admin guard — accepts owner or admin roles.

    Kept for backward compatibility; new code should prefer the
    role-specific deps below (RequireManager, RequireAdmin, RequireOwner).
    """
    if not (current_user.is_admin or current_user.role in ("owner", "admin")):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required",
        )
    return current_user


# --- Role-based guards (phase A/B) ---


def _require_min_role(min_role: str):
    async def check(
        current_user: Annotated[User, Depends(get_current_user)],
    ) -> User:
        if not current_user.has_min_role(min_role):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Permissions insuffisantes.",
            )
        return current_user
    return check


get_current_manager = _require_min_role("manager")
get_current_admin_role = _require_min_role("admin")
get_current_owner = _require_min_role("owner")


async def get_current_admin_or_owner(
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    """Guard dédié au pôle Dev Logiciel — admin ou owner uniquement.

    Diffère de ``get_current_admin_role`` (qui partage le message générique
    « Permissions insuffisantes. ») par un libellé explicite côté UI :
    le pôle est réservé à l'équipe interne (Phil et Steven).
    """
    if current_user.role not in ("owner", "admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Accès réservé aux administrateurs",
        )
    return current_user


def require_volet(*volets: str):
    """Garde d'accès PAR PÔLE (volet) — permissions v2 (2026-07-24).

    Fabrique une dépendance FastAPI qui exige que l'utilisateur courant ait
    accès à AU MOINS UN des volets donnés : volet coché (``User.has_volet``,
    owner/admin = tous) OU exception individuelle qui accorde le volet ou
    une de ses pages (``user_access_overrides``) — les MÊMES règles que
    ``compute_access``, pour que ce que l'UI affiche soit toujours servi
    par l'API. Plusieurs volets = ressource partagée entre pôles (ex. bons
    de travail : construction OU immobilier). À appliquer à l'inclusion des
    routeurs métier (``dependencies=[Depends(require_volet("prospection"))]``).
    """

    async def check(
        current_user: Annotated[User, Depends(get_current_user)],
        db: Annotated[AsyncSession, Depends(get_db)],
    ) -> User:
        from app.services.access_service import user_has_volet_access

        if not await user_has_volet_access(db, current_user, *volets):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Accès au pôle non autorisé.",
            )
        return current_user

    return check


# Type aliases for cleaner dependency injection
CurrentUser = Annotated[User, Depends(get_current_user)]
CurrentAdmin = Annotated[User, Depends(get_current_admin)]
RequireManager = Annotated[User, Depends(get_current_manager)]
RequireAdminRole = Annotated[User, Depends(get_current_admin_role)]
RequireAdminOrOwner = Annotated[User, Depends(get_current_admin_or_owner)]
RequireOwner = Annotated[User, Depends(get_current_owner)]
DBSession = Annotated[AsyncSession, Depends(get_db)]
