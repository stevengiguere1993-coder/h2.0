"""Endpoints CRUD pour l'organigramme.

  GET    /api/v1/org-nodes              liste plate (l'UI reconstruit
                                        l'arbre)
  POST   /api/v1/org-nodes              crée un nœud
  GET    /api/v1/org-nodes/{id}         détail
  PATCH  /api/v1/org-nodes/{id}         édite (label, parent, assignee,
                                        entreprise, position, ...)
  DELETE /api/v1/org-nodes/{id}         supprime (cascade sur enfants)
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select

from app.api.deps import CurrentUser, DBSession
from app.models.org_node import OrgNode


log = logging.getLogger(__name__)
router = APIRouter(prefix="/org-nodes", tags=["org-nodes"])


VALID_KINDS = {"dept", "role", "service", "task", "company"}


class OrgNodeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    parent_id: Optional[int]
    position: int
    kind: str
    label: str
    description: Optional[str]
    entreprise_id: Optional[int]
    assignee_employe_id: Optional[int]
    assignee_user_id: Optional[int]
    assignee_external_name: Optional[str]
    co_owner_node_ids: List[int] = []
    pos_x: Optional[float] = None
    pos_y: Optional[float] = None
    created_at: datetime
    updated_at: datetime

    @field_validator("co_owner_node_ids", mode="before")
    @classmethod
    def _parse_co_owners(cls, v: object) -> List[int]:
        # En base : JSON texte (ou NULL). En sortie API : liste d'ints.
        if not v:
            return []
        if isinstance(v, list):
            return [int(x) for x in v]
        try:
            parsed = json.loads(v)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return []
        return [int(x) for x in parsed] if isinstance(parsed, list) else []


class OrgNodeCreate(BaseModel):
    parent_id: Optional[int] = None
    position: Optional[int] = None
    kind: str = Field(default="dept", max_length=16)
    label: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    entreprise_id: Optional[int] = None
    assignee_employe_id: Optional[int] = None
    assignee_user_id: Optional[int] = None
    assignee_external_name: Optional[str] = Field(
        default=None, max_length=255
    )


class OrgNodeMove(BaseModel):
    """Re-parente et réordonne un nœud (drag-and-drop)."""

    parent_id: Optional[int] = None
    position: int = Field(..., ge=0)


class OrgNodeUpdate(BaseModel):
    parent_id: Optional[int] = None
    position: Optional[int] = None
    kind: Optional[str] = Field(default=None, max_length=16)
    label: Optional[str] = Field(default=None, min_length=1, max_length=255)
    description: Optional[str] = None
    entreprise_id: Optional[int] = None
    assignee_employe_id: Optional[int] = None
    assignee_user_id: Optional[int] = None
    assignee_external_name: Optional[str] = Field(
        default=None, max_length=255
    )
    co_owner_node_ids: Optional[List[int]] = None
    pos_x: Optional[float] = None
    pos_y: Optional[float] = None


@router.get("", response_model=List[OrgNodeRead])
async def list_nodes(
    db: DBSession,
    _: CurrentUser,
    entreprise_id: Optional[int] = Query(default=None),
) -> List[OrgNodeRead]:
    stmt = (
        select(OrgNode)
        .order_by(OrgNode.parent_id.asc().nulls_first(), OrgNode.position.asc())
    )
    if entreprise_id is not None:
        stmt = stmt.where(OrgNode.entreprise_id == entreprise_id)
    rows = (await db.execute(stmt)).scalars().all()
    return [OrgNodeRead.model_validate(r) for r in rows]


@router.post(
    "", response_model=OrgNodeRead, status_code=status.HTTP_201_CREATED
)
async def create_node(
    data: OrgNodeCreate, db: DBSession, _: CurrentUser
) -> OrgNodeRead:
    kind = data.kind if data.kind in VALID_KINDS else "dept"
    # Position auto si non fournie : max(siblings) + 1
    if data.position is None:
        sibling = (
            await db.execute(
                select(OrgNode)
                .where(OrgNode.parent_id.is_(data.parent_id))
                if data.parent_id is None
                else select(OrgNode).where(OrgNode.parent_id == data.parent_id)
            )
        ).scalars().all()
        pos = max((s.position for s in sibling), default=-1) + 1
    else:
        pos = int(data.position)
    n = OrgNode(
        parent_id=data.parent_id,
        position=pos,
        kind=kind,
        label=data.label.strip(),
        description=data.description,
        entreprise_id=data.entreprise_id,
        assignee_employe_id=data.assignee_employe_id,
        assignee_user_id=data.assignee_user_id,
        assignee_external_name=data.assignee_external_name,
    )
    db.add(n)
    await db.commit()
    await db.refresh(n)
    return OrgNodeRead.model_validate(n)


@router.get("/{node_id}", response_model=OrgNodeRead)
async def get_node(
    node_id: int, db: DBSession, _: CurrentUser
) -> OrgNodeRead:
    n = (
        await db.execute(select(OrgNode).where(OrgNode.id == node_id))
    ).scalar_one_or_none()
    if n is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Nœud introuvable.")
    return OrgNodeRead.model_validate(n)


@router.patch("/{node_id}", response_model=OrgNodeRead)
async def update_node(
    node_id: int,
    data: OrgNodeUpdate,
    db: DBSession,
    _: CurrentUser,
) -> OrgNodeRead:
    n = (
        await db.execute(select(OrgNode).where(OrgNode.id == node_id))
    ).scalar_one_or_none()
    if n is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Nœud introuvable.")
    payload = data.model_dump(exclude_unset=True)
    if "kind" in payload and payload["kind"] not in VALID_KINDS:
        payload.pop("kind")
    if "co_owner_node_ids" in payload:
        # Stocké en JSON texte ; on filtre l'auto-référence par sûreté.
        ids = [
            int(x) for x in (payload.pop("co_owner_node_ids") or [])
            if int(x) != node_id
        ]
        n.co_owner_node_ids = json.dumps(ids) if ids else None
    for k, v in payload.items():
        setattr(n, k, v)
    await db.commit()
    await db.refresh(n)
    return OrgNodeRead.model_validate(n)


@router.delete("/{node_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_node(
    node_id: int, db: DBSession, _: CurrentUser
) -> None:
    n = (
        await db.execute(select(OrgNode).where(OrgNode.id == node_id))
    ).scalar_one_or_none()
    if n is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Nœud introuvable.")
    await db.delete(n)
    await db.commit()


class RoleSuggestion(BaseModel):
    label: str
    kind: str
    description: Optional[str] = None


@router.post(
    "/{node_id}/suggest-roles",
    response_model=List[RoleSuggestion],
    summary=(
        "Suggère les rôles / départements / tâches manquants d'une "
        "entreprise selon son but. Ne persiste rien — l'utilisateur "
        "ajoute ensuite les suggestions retenues."
    ),
)
async def suggest_roles_for_node(
    node_id: int, db: DBSession, _: CurrentUser
) -> List[RoleSuggestion]:
    from app.services.org_role_suggester import suggest_roles

    try:
        suggestions = await suggest_roles(db, node_id)
    except ValueError as exc:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, str(exc)
        ) from exc
    return [RoleSuggestion(**s) for s in suggestions]


async def _all_nodes_sorted(db) -> List[OrgNode]:
    return list(
        (
            await db.execute(
                select(OrgNode).order_by(
                    OrgNode.parent_id.asc().nulls_first(),
                    OrgNode.position.asc(),
                )
            )
        )
        .scalars()
        .all()
    )


@router.post(
    "/{node_id}/move",
    response_model=List[OrgNodeRead],
    summary=(
        "Re-parente et réordonne un nœud (drag-and-drop). Renvoie "
        "l'organigramme complet à jour."
    ),
)
async def move_node(
    node_id: int,
    data: OrgNodeMove,
    db: DBSession,
    _: CurrentUser,
) -> List[OrgNodeRead]:
    all_nodes = (await db.execute(select(OrgNode))).scalars().all()
    by_id = {n.id: n for n in all_nodes}
    node = by_id.get(node_id)
    if node is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Nœud introuvable.")

    new_parent = data.parent_id
    if new_parent == node_id:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Un nœud ne peut pas être son propre parent.",
        )
    if new_parent is not None and new_parent not in by_id:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Parent cible introuvable."
        )

    # Anti-boucle : le nouveau parent ne doit pas être un descendant du
    # nœud déplacé.
    if new_parent is not None:
        children_of: dict = {}
        for n in all_nodes:
            children_of.setdefault(n.parent_id, []).append(n.id)
        stack = list(children_of.get(node_id, []))
        descendants = set()
        while stack:
            cur = stack.pop()
            if cur in descendants:
                continue
            descendants.add(cur)
            stack.extend(children_of.get(cur, []))
        if new_parent in descendants:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Déplacement invalide : créerait une boucle.",
            )

    old_parent = node.parent_id

    # Nouveaux frères (même parent cible), hors le nœud déplacé, triés.
    siblings = sorted(
        (
            n
            for n in all_nodes
            if n.parent_id == new_parent and n.id != node_id
        ),
        key=lambda n: n.position,
    )
    pos = max(0, min(data.position, len(siblings)))
    siblings.insert(pos, node)
    node.parent_id = new_parent
    for i, s in enumerate(siblings):
        s.position = i

    # Recompacte l'ancien parent si le nœud a changé de branche.
    if old_parent != new_parent:
        old_sibs = sorted(
            (
                n
                for n in all_nodes
                if n.parent_id == old_parent and n.id != node_id
            ),
            key=lambda n: n.position,
        )
        for i, s in enumerate(old_sibs):
            s.position = i

    await db.commit()
    return [OrgNodeRead.model_validate(n) for n in await _all_nodes_sorted(db)]


@router.post(
    "/import-entreprises",
    response_model=List[OrgNodeRead],
    summary=(
        "Crée un nœud « entreprise » (kind=company) pour chaque "
        "entreprise pas encore présente dans l'organigramme. "
        "Idempotent : les entreprises déjà importées sont ignorées."
    ),
)
async def import_entreprises(
    db: DBSession, _: CurrentUser
) -> List[OrgNodeRead]:
    from app.models.entreprise import Entreprise

    nodes = (await db.execute(select(OrgNode))).scalars().all()
    already = {
        n.entreprise_id
        for n in nodes
        if n.kind == "company" and n.entreprise_id is not None
    }
    entreprises = (
        await db.execute(
            select(Entreprise).order_by(Entreprise.name.asc())
        )
    ).scalars().all()

    pos = max(
        (n.position for n in nodes if n.parent_id is None), default=-1
    ) + 1
    for e in entreprises:
        if e.id in already:
            continue
        db.add(
            OrgNode(
                parent_id=None,
                position=pos,
                kind="company",
                label=e.name,
                entreprise_id=e.id,
            )
        )
        pos += 1

    await db.commit()
    return [OrgNodeRead.model_validate(n) for n in await _all_nodes_sorted(db)]


@router.post(
    "/seed-default",
    response_model=List[OrgNodeRead],
    summary=(
        "Seed l'organigramme initial du groupe MGV Investissements "
        "(basé sur le schéma papier). Erreur si des nœuds existent déjà."
    ),
)
async def seed_default_org(
    db: DBSession,
    _: CurrentUser,
    force: bool = Query(default=False),
) -> List[OrgNodeRead]:
    """Crée la structure de départ : 6 branches top-level
    (Construction, Dev logiciel, Gestion Immo, Prospection, Dev Immo /
    Aguci, Comptabilité) avec leurs rôles et tâches. Lie aux entreprises
    par NOM (matching insensible à la casse) quand possible.

    `force=true` efface l'existant avant de seed (DANGER : supprime
    toutes les hiérarchies actuelles)."""
    from app.models.entreprise import Entreprise

    existing_count = len(
        (await db.execute(select(OrgNode))).scalars().all()
    )
    if existing_count > 0 and not force:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            (
                f"L'organigramme contient déjà {existing_count} nœud(s). "
                "Utilise `?force=true` pour tout remplacer."
            ),
        )

    if force and existing_count > 0:
        # Supprime tout (cascade gère les enfants).
        roots = (
            await db.execute(
                select(OrgNode).where(OrgNode.parent_id.is_(None))
            )
        ).scalars().all()
        for r in roots:
            await db.delete(r)
        await db.flush()

    # Lookup entreprises par nom (case-insensitive, sans accents).
    entreprises_rows = (
        await db.execute(select(Entreprise))
    ).scalars().all()

    def _norm(s: str) -> str:
        s = (s or "").strip().lower()
        for a, b in (
            ("é", "e"), ("è", "e"), ("ê", "e"),
            ("à", "a"), ("â", "a"),
            ("ô", "o"), ("ç", "c"),
        ):
            s = s.replace(a, b)
        return s

    def find_ent(*candidates: str) -> Optional[int]:
        norm_cands = [_norm(c) for c in candidates if c]
        for e in entreprises_rows:
            n = _norm(e.name)
            for c in norm_cands:
                if c in n or n in c:
                    return e.id
        return None

    # Structure à seeder. Chaque tuple :
    #   (label, kind, entreprise_id_or_None, assignee_external_or_None,
    #    children_list)
    # Children récursifs même format.
    structure = [
        # ── 1. Construction ─────────────────────────────────
        (
            "Construction",
            "dept",
            find_ent("Construction", "MGV Construction", "Horizon Construction"),
            None,
            [
                ("Chargé de projet", "role", None, None, []),
                ("Closer / Soumissionnaire", "role", None, None, []),
                ("Sous-traitants", "role", None, "Sous-traitants externes", []),
            ],
        ),
        # ── 2. Dev logiciel ─────────────────────────────────
        (
            "Dev logiciel",
            "dept",
            find_ent("Développement", "MGV Développement", "MC"),
            None,
            [
                (
                    "Développeur",
                    "role",
                    None,
                    "Freelance ou Phil",
                    [],
                ),
                ("Acquisition", "role", None, None, []),
                ("E-payable", "task", None, None, []),
                ("E-recevable", "task", None, None, []),
            ],
        ),
        # ── 3. Gestion Immo ─────────────────────────────────
        (
            "Gestion Immo",
            "dept",
            find_ent("Gestion Immo", "MGV", "Horizon"),
            "Steven",
            [
                ("Kyle / Kario", "role", None, "Kyle / Kario", []),
                ("Communication", "role", None, None, []),
                ("Gestion des loyers", "role", None, None, []),
                (
                    "Réception des loyers",
                    "role",
                    None,
                    None,
                    [
                        ("Augmentation", "task", None, None, []),
                        ("Réparation", "task", None, None, []),
                        ("Bris", "task", None, None, []),
                    ],
                ),
            ],
        ),
        # ── 4. Prospection ──────────────────────────────────
        (
            "Prospection",
            "dept",
            find_ent("Prospection"),
            "Steven",
            [
                (
                    "Prospecteur",
                    "role",
                    None,
                    "Zach",
                    [],
                ),
                (
                    "Acquisition",
                    "role",
                    None,
                    None,
                    [
                        ("Analyse", "task", None, None, []),
                        ("Étude lead", "task", None, None, []),
                        ("Screening Centris", "task", None, None, []),
                        ("Cold call", "task", None, None, []),
                    ],
                ),
            ],
        ),
        # ── 5. Dev Immo / Aguci ─────────────────────────────
        (
            "Dev Immo / Aguci",
            "dept",
            find_ent("Aguci", "Dev Immo"),
            None,
            [
                ("Dev logiciel", "role", None, None, []),
                ("Dev Prospection", "role", None, None, []),
                ("Ouvrir inc", "task", None, None, []),
                ("Desjardins", "task", None, None, []),
                ("Marge crédit", "task", None, None, []),
                ("Convention actionnaire", "task", None, None, []),
            ],
        ),
        # ── 6. Comptabilité (service partagé) ───────────────
        (
            "Comptabilité",
            "service",
            None,
            None,
            [
                ("Gestion taxes", "task", None, None, []),
                ("Payable", "task", None, None, []),
                ("Recevable", "task", None, None, []),
                ("Tenue de livres", "task", None, None, []),
            ],
        ),
    ]

    created: List[OrgNode] = []

    async def _create_recursive(
        items: list, parent_id: Optional[int], depth: int
    ) -> None:
        for i, (label, kind, ent_id, ext, children) in enumerate(items):
            node = OrgNode(
                parent_id=parent_id,
                position=i,
                kind=kind,
                label=label,
                entreprise_id=ent_id,
                assignee_external_name=ext,
            )
            db.add(node)
            await db.flush()
            created.append(node)
            if children:
                await _create_recursive(children, node.id, depth + 1)

    await _create_recursive(structure, None, 0)
    await db.commit()
    return [OrgNodeRead.model_validate(n) for n in created]
