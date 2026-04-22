"""Permission helpers — pick which rows a user can see based on role.

owner / admin / manager see everything.
employee sees only:
  - projects they are a member of (via project_members)
  - other records (factures, soumissions, bons, achats) linked to those
    projects
  - their own agenda events, punches, leave requests
"""

from __future__ import annotations

from typing import Optional, Set

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.project_member import ProjectMember
from app.models.user import User


async def visible_project_ids(
    db: AsyncSession, user: User
) -> Optional[Set[int]]:
    """Return the set of project IDs the user can see.

    Returns ``None`` for managers+ (meaning "no restriction, see all").
    Returns a possibly-empty set for employees.
    """
    if user.has_min_role("manager"):
        return None
    rows = (
        await db.execute(
            select(ProjectMember.project_id).where(
                ProjectMember.user_id == user.id
            )
        )
    ).all()
    return {int(r[0]) for r in rows}


def is_manager_plus(user: User) -> bool:
    return user.has_min_role("manager")


def is_admin_plus(user: User) -> bool:
    return user.has_min_role("admin")


def is_owner(user: User) -> bool:
    return user.has_min_role("owner")
