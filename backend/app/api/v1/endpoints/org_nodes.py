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
from app.models.org_node import OrgNode, OrgVersion


log = logging.getLogger(__name__)
router = APIRouter(prefix="/org-nodes", tags=["org-nodes"])


VALID_KINDS = {"dept", "role", "service", "task", "company", "person"}
VALID_TIERS = {"direction", "adjoint", "adjoint_virtuel"}


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
    #: Version d'organigramme (NULL = « Principal »).
    version_id: Optional[int] = None
    #: Quotes-parts par détenteur : JSON {"<node_id>": pct} (brut — le
    #: frontend le parse pour l'afficher sur les flèches).
    ownership_json: Optional[str] = None
    pos_x: Optional[float] = None
    pos_y: Optional[float] = None
    execution_tier: Optional[str] = None
    state: Optional[str] = None
    state_note: Optional[str] = None
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
    version_id: Optional[int] = None
    kind: str = Field(default="dept", max_length=16)
    label: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    entreprise_id: Optional[int] = None
    assignee_employe_id: Optional[int] = None
    assignee_user_id: Optional[int] = None
    assignee_external_name: Optional[str] = Field(
        default=None, max_length=255
    )
    execution_tier: Optional[str] = None
    state: Optional[str] = None
    state_note: Optional[str] = None


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
    #: Quotes-parts par détenteur : JSON {"<node_id>": pct}.
    ownership_json: Optional[str] = None
    pos_x: Optional[float] = None
    pos_y: Optional[float] = None
    execution_tier: Optional[str] = None
    state: Optional[str] = None
    state_note: Optional[str] = None


@router.get("", response_model=List[OrgNodeRead])
async def list_nodes(
    db: DBSession,
    _: CurrentUser,
    entreprise_id: Optional[int] = Query(default=None),
    version_id: Optional[int] = Query(default=None),
) -> List[OrgNodeRead]:
    stmt = (
        select(OrgNode)
        .where(
            OrgNode.version_id.is_(None)
            if version_id is None
            else OrgNode.version_id == version_id
        )
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
    tier = data.execution_tier if data.execution_tier in VALID_TIERS else None
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
        version_id=data.version_id,
        kind=kind,
        label=data.label.strip(),
        description=data.description,
        entreprise_id=data.entreprise_id,
        assignee_employe_id=data.assignee_employe_id,
        assignee_user_id=data.assignee_user_id,
        assignee_external_name=data.assignee_external_name,
        execution_tier=tier,
    )
    db.add(n)
    await db.commit()
    await db.refresh(n)
    return OrgNodeRead.model_validate(n)


# ─── Versions d'organigramme (retour Phil 2026-08-10) ──────────────────
# Déclarées AVANT /{node_id} pour que « versions » ne soit pas avalé par
# le paramètre de chemin.


class OrgVersionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    created_at: datetime


class OrgVersionCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    #: True = copier les nœuds d'une version existante (None = copier la
    #: version « Principal ») ; False = partir d'une page blanche.
    copy_nodes: bool = True
    copy_from_version_id: Optional[int] = None


@router.get("/versions", response_model=List[OrgVersionRead])
async def list_versions(
    db: DBSession, _: CurrentUser
) -> List[OrgVersionRead]:
    rows = (
        await db.execute(select(OrgVersion).order_by(OrgVersion.id.asc()))
    ).scalars().all()
    return [OrgVersionRead.model_validate(r) for r in rows]


@router.post(
    "/versions",
    response_model=OrgVersionRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_version(
    data: OrgVersionCreate, db: DBSession, _: CurrentUser
) -> OrgVersionRead:
    v = OrgVersion(name=data.name.strip())
    db.add(v)
    await db.flush()
    if data.copy_nodes:
        src = data.copy_from_version_id
        sources = (
            await db.execute(
                select(OrgNode).where(
                    OrgNode.version_id.is_(None)
                    if src is None
                    else OrgNode.version_id == src
                )
            )
        ).scalars().all()
        # 1er passage : cloner sans les liens (il faut les nouveaux ids).
        clones: list = []
        for s in sources:
            c = OrgNode(
                version_id=v.id, parent_id=None, position=s.position,
                kind=s.kind, label=s.label, description=s.description,
                entreprise_id=s.entreprise_id,
                assignee_employe_id=s.assignee_employe_id,
                assignee_user_id=s.assignee_user_id,
                assignee_external_name=s.assignee_external_name,
                pos_x=s.pos_x, pos_y=s.pos_y,
                execution_tier=s.execution_tier, state=s.state,
                state_note=s.state_note,
            )
            db.add(c)
            clones.append((s, c))
        await db.flush()
        mapping = {s.id: c.id for s, c in clones}
        # 2e passage : re-brancher parents, co-détenteurs et quotes-parts
        # sur les ids clonés.
        for s, c in clones:
            if s.parent_id and s.parent_id in mapping:
                c.parent_id = mapping[s.parent_id]
            try:
                co = json.loads(s.co_owner_node_ids or "[]")
            except (TypeError, ValueError):
                co = []
            co2 = [mapping[int(x)] for x in co if int(x) in mapping]
            c.co_owner_node_ids = json.dumps(co2) if co2 else None
            try:
                own = json.loads(s.ownership_json or "{}")
            except (TypeError, ValueError):
                own = {}
            own2 = {
                str(mapping[int(k)]): float(pv)
                for k, pv in own.items()
                if str(k).lstrip("-").isdigit() and int(k) in mapping
            }
            c.ownership_json = json.dumps(own2) if own2 else None
    await db.commit()
    await db.refresh(v)
    return OrgVersionRead.model_validate(v)


@router.delete(
    "/versions/{version_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_version(
    version_id: int, db: DBSession, _: CurrentUser
) -> None:
    v = await db.get(OrgVersion, version_id)
    if v is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Version introuvable."
        )
    # Le FK ondelete=CASCADE n'existe que sur les bases neuves (colonne
    # additive sans contrainte sur les bases existantes) → suppression
    # explicite des nœuds de la version.
    for n in (
        await db.execute(
            select(OrgNode).where(OrgNode.version_id == version_id)
        )
    ).scalars().all():
        await db.delete(n)
    await db.delete(v)
    await db.commit()


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
    if (
        "execution_tier" in payload
        and payload["execution_tier"] is not None
        and payload["execution_tier"] not in VALID_TIERS
    ):
        payload.pop("execution_tier")
    if "co_owner_node_ids" in payload:
        # Stocké en JSON texte ; on filtre l'auto-référence par sûreté.
        ids = [
            int(x) for x in (payload.pop("co_owner_node_ids") or [])
            if int(x) != node_id
        ]
        n.co_owner_node_ids = json.dumps(ids) if ids else None
    if "ownership_json" in payload:
        raw = payload.pop("ownership_json")
        if raw:
            try:
                parsed = json.loads(raw)
                if not isinstance(parsed, dict):
                    raise ValueError("objet attendu")
            except (TypeError, ValueError):
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_ENTITY,
                    "ownership_json invalide (objet JSON attendu).",
                )
            n.ownership_json = raw
        else:
            n.ownership_json = None
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
    execution_tier: Optional[str] = None


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
    "/sync-detention",
    response_model=List[OrgNodeRead],
    summary=(
        "Reconstruit la structure de DÉTENTION depuis les partenaires "
        "des fiches d'entreprises : un nœud par entreprise active et "
        "par actionnaire externe, parent = plus gros détenteur, autres "
        "en co-détenteurs, pourcentages dans la description. Les "
        "positions du canvas sont conservées. Idempotent."
    ),
)
async def sync_detention(
    db: DBSession,
    _: CurrentUser,
    version_id: Optional[int] = Query(default=None),
) -> List[OrgNodeRead]:
    await _sync_detention_impl(db, version_id=version_id)
    await db.commit()
    return [
        OrgNodeRead.model_validate(n) for n in await _all_nodes_sorted(db)
    ]


async def resync_detention_entreprise(db, entreprise_id: int) -> None:
    """Hook « tout est interconnecté » : resynchronise les arêtes de
    détention du nœud PRINCIPAL d'une entreprise depuis ses partenaires
    — appelé à la création d'une entreprise et à la sauvegarde d'un
    partenaire. Best-effort : ne lève jamais (l'organigramme ne doit
    jamais bloquer la sauvegarde métier)."""
    try:
        await _sync_detention_impl(
            db, version_id=None, only_entreprise_id=entreprise_id
        )
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "resync organigramme entreprise %s: %s", entreprise_id, exc
        )


async def _sync_detention_impl(
    db,
    version_id: Optional[int] = None,
    only_entreprise_id: Optional[int] = None,
) -> None:
    from app.models.entreprise import Entreprise, EntreprisePartner
    from app.models.user import User

    nodes = list(
        (
            await db.execute(
                select(OrgNode).where(
                    OrgNode.version_id.is_(None)
                    if version_id is None
                    else OrgNode.version_id == version_id
                )
            )
        ).scalars().all()
    )
    by_ent = {
        n.entreprise_id: n
        for n in nodes
        if n.kind == "company" and n.entreprise_id is not None
    }
    persons = {
        (n.label or "").strip().lower(): n
        for n in nodes
        if n.kind == "person"
    }
    next_pos = max(
        (n.position for n in nodes if n.parent_id is None), default=-1
    ) + 1

    entreprises = (
        await db.execute(
            select(Entreprise)
            .where(Entreprise.is_active.is_(True))
            .order_by(Entreprise.name.asc())
        )
    ).scalars().all()
    ents_by_id = {e.id: e for e in entreprises}
    for e in entreprises:
        if e.id in by_ent:
            continue
        n = OrgNode(
            parent_id=None, position=next_pos, kind="company",
            label=e.name, entreprise_id=e.id, version_id=version_id,
        )
        db.add(n)
        await db.flush()
        by_ent[e.id] = n
        nodes.append(n)
        next_pos += 1

    partners = (
        await db.execute(select(EntreprisePartner))
    ).scalars().all()
    user_ids = {p.user_id for p in partners if p.user_id}
    users = {
        u.id: u
        for u in (
            await db.execute(select(User).where(User.id.in_(user_ids)))
        ).scalars().all()
    } if user_ids else {}

    def _holder_label(p: EntreprisePartner) -> str:
        if p.partner_name:
            return p.partner_name.strip()
        if p.user_id and p.user_id in users:
            return users[p.user_id].display_name
        return f"Partenaire #{p.id}"

    def _creates_cycle(child: OrgNode, new_parent: OrgNode) -> bool:
        # Remonte les parents depuis le candidat : si on retombe sur
        # l'enfant, le rattachement bouclerait l'arbre (ex. détentions
        # croisées A↔B) — on garde alors le lien en co-détention.
        all_by_id = {n.id: n for n in nodes}
        cur: Optional[OrgNode] = new_parent
        guard = 0
        while cur is not None and guard < 500:
            if cur.id == child.id:
                return True
            cur = (
                all_by_id.get(cur.parent_id)
                if cur.parent_id is not None
                else None
            )
            guard += 1
        return False

    par_detenue: dict = {}
    for p in partners:
        if (
            only_entreprise_id is not None
            and p.entreprise_id != only_entreprise_id
        ):
            continue
        if p.entreprise_id in ents_by_id:
            par_detenue.setdefault(p.entreprise_id, []).append(p)

    # Hook ciblé sur une entreprise qui n'a PLUS de partenaires : ses
    # arêtes de détention disparaissent aussi (les partenaires sont la
    # source de vérité de la détention).
    if (
        only_entreprise_id is not None
        and only_entreprise_id not in par_detenue
    ):
        child = by_ent.get(only_entreprise_id)
        if child is not None:
            child.parent_id = None
            child.co_owner_node_ids = None
            child.ownership_json = None
            autres = [
                ligne
                for ligne in (child.description or "").splitlines()
                if not ligne.startswith("Détention : ") and ligne.strip()
            ]
            child.description = "\n".join(autres) or None
        await db.flush()
        return

    for ent_id, plist in par_detenue.items():
        child = by_ent.get(ent_id)
        if child is None:
            continue
        holders = []
        for p in plist:
            if (
                p.partner_entreprise_id
                and p.partner_entreprise_id in by_ent
            ):
                hn = by_ent[p.partner_entreprise_id]
            else:
                lbl = _holder_label(p)
                key = lbl.lower()
                hn = persons.get(key)
                if hn is None:
                    hn = OrgNode(
                        parent_id=None, position=next_pos, kind="person",
                        label=lbl, version_id=version_id,
                    )
                    db.add(hn)
                    await db.flush()
                    persons[key] = hn
                    nodes.append(hn)
                    next_pos += 1
            if hn.id == child.id:
                continue
            holders.append((float(p.ownership_pct or 0.0), hn))
        if not holders:
            continue
        holders.sort(key=lambda t: -t[0])
        # Quotes-parts par détenteur — affichées SUR les flèches.
        own_map = {str(hn.id): pct for pct, hn in holders if pct}
        child.ownership_json = json.dumps(own_map) if own_map else None
        # Ligne « Détention : … » maintenue en tête de description (les
        # notes manuelles en dessous sont conservées).
        detention = " · ".join(
            f"{hn.label} {pct:g} %" if pct else hn.label
            for pct, hn in holders
        )
        autres = [
            ligne
            for ligne in (child.description or "").splitlines()
            if not ligne.startswith("Détention : ") and ligne.strip()
        ]
        child.description = "\n".join(
            ["Détention : " + detention] + autres
        )
        principal = holders[0][1]
        co_ids = [hn.id for _, hn in holders[1:]]
        if not _creates_cycle(child, principal):
            child.parent_id = principal.id
        else:
            co_ids = [principal.id] + co_ids
        co_ids = [
            c
            for c in dict.fromkeys(co_ids)
            if c != child.parent_id and c != child.id
        ]
        child.co_owner_node_ids = json.dumps(co_ids) if co_ids else None

    await db.flush()


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
