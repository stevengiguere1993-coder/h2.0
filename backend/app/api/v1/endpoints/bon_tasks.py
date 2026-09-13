"""Tâches cochables d'un bon de travail + fusion de bons du même lieu.

Retour 2026-09-12, point 12 :

- un bon porte une liste de TÂCHES à cocher (saisies à la main, ou une
  par bon d'origine lors d'une fusion) ;
- les bons de travail d'un MÊME LIEU peuvent être fusionnés en un seul
  bon : chaque bon absorbé devient une tâche du bon cible, ses lignes
  (heures/matériel) et ses punchs suivent, puis il est annulé avec une
  trace « fusionné dans BT-xxx » ;
- quand TOUTES les tâches d'un bon interne sont cochées, il se classe
  automatiquement « Complété — à refacturer ». Le classement manuel
  reste possible (le PATCH de statut habituel n'est pas touché).

Routes :
    GET    /bons-travail/{bon_id}/tasks
    POST   /bons-travail/{bon_id}/tasks
    PATCH  /bons-travail/{bon_id}/tasks/{task_id}
    DELETE /bons-travail/{bon_id}/tasks/{task_id}
    POST   /bons-travail/{bon_id}/fusionner   (manager+)
"""

import logging
import unicodedata
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select

from app.api.deps import CurrentUser, DBSession
from app.models.bon_item import BonItem
from app.models.bon_task import BonTask
from app.models.bon_travail import BonTravail
from app.models.punch import Punch

log = logging.getLogger(__name__)

router = APIRouter(prefix="/bons-travail", tags=["bon-tasks"])

#: Statuts où un bon peut encore être fusionné / absorber d'autres bons.
_STATUTS_OUVERTS = ("draft", "accepte_a_planifier", "planifie", "sent")

#: Rang d'avancement du cycle interne — après une fusion, le bon cible
#: garde le statut le PLUS AVANCÉ du groupe (un bon déjà planifié ne
#: retombe pas en brouillon parce qu'un nouveau bon l'a absorbé).
_RANG_INTERNE = {"draft": 0, "accepte_a_planifier": 1, "planifie": 2}


def adresse_cle(addr: Optional[str]) -> str:
    """Clé de comparaison d'adresses : casse, accents, espaces et
    ponctuation ignorés — même règle que le frontend."""
    s = unicodedata.normalize("NFD", (addr or "").lower())
    return "".join(c for c in s if c.isalnum() and not unicodedata.combining(c))


class BonTaskCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=500)
    position: int = Field(default=0, ge=0)


class BonTaskUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=500)
    position: Optional[int] = Field(default=None, ge=0)
    done: Optional[bool] = None


class BonTaskRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    bon_id: int
    position: int
    title: str
    done: bool
    done_at: Optional[datetime]
    done_by_user_id: Optional[int]
    source_bon_reference: Optional[str]


class BonFusionPayload(BaseModel):
    source_bon_ids: List[int] = Field(..., min_length=1, max_length=50)


async def _ensure_bon(db, bon_id: int) -> BonTravail:
    record = (
        await db.execute(select(BonTravail).where(BonTravail.id == bon_id))
    ).scalar_one_or_none()
    if record is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Bon de travail not found")
    return record


async def _maybe_autoclasser(db, bon: BonTravail) -> bool:
    """Toutes les tâches cochées → bon interne classé « Complété — à
    refacturer » automatiquement. Jamais de recul, jamais depuis un
    statut terminal ; le classement manuel reste toujours possible."""
    if (bon.kind or "construction") != "interne":
        return False
    if bon.status not in ("accepte_a_planifier", "planifie"):
        return False
    rows = (
        await db.execute(
            select(BonTask.done).where(BonTask.bon_id == bon.id)
        )
    ).scalars().all()
    if rows and all(rows):
        bon.status = "complete_a_refacturer"
        await db.flush()
        return True
    return False


@router.get("/{bon_id}/tasks", response_model=List[BonTaskRead])
async def list_tasks(
    bon_id: int, db: DBSession, _: CurrentUser
) -> List[BonTaskRead]:
    await _ensure_bon(db, bon_id)
    rows = (
        await db.execute(
            select(BonTask)
            .where(BonTask.bon_id == bon_id)
            .order_by(BonTask.position.asc(), BonTask.id.asc())
        )
    ).scalars().all()
    return [BonTaskRead.model_validate(r) for r in rows]


@router.post(
    "/{bon_id}/tasks",
    response_model=BonTaskRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_task(
    bon_id: int, data: BonTaskCreate, db: DBSession, _: CurrentUser
) -> BonTaskRead:
    await _ensure_bon(db, bon_id)
    task = BonTask(
        bon_id=bon_id,
        title=data.title.strip(),
        position=data.position,
    )
    db.add(task)
    await db.flush()
    await db.refresh(task)
    return BonTaskRead.model_validate(task)


@router.patch("/{bon_id}/tasks/{task_id}", response_model=BonTaskRead)
async def update_task(
    bon_id: int,
    task_id: int,
    data: BonTaskUpdate,
    db: DBSession,
    user: CurrentUser,
) -> BonTaskRead:
    """Cocher/décocher ou renommer une tâche. Accessible à tout
    utilisateur authentifié : c'est l'exécutant sur le terrain qui coche."""
    bon = await _ensure_bon(db, bon_id)
    task = (
        await db.execute(
            select(BonTask).where(
                BonTask.id == task_id, BonTask.bon_id == bon_id
            )
        )
    ).scalar_one_or_none()
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Task not found")
    update = data.model_dump(exclude_unset=True)
    if "title" in update and update["title"]:
        task.title = update["title"].strip()
    if "position" in update and update["position"] is not None:
        task.position = update["position"]
    if "done" in update and update["done"] is not None:
        task.done = bool(update["done"])
        if task.done:
            # Moment + auteur de la complétion (même esprit que les
            # tâches de projet : done_at = quand ça a été fait).
            task.done_at = datetime.now(timezone.utc)
            task.done_by_user_id = user.id
        else:
            task.done_at = None
            task.done_by_user_id = None
    await db.flush()
    await _maybe_autoclasser(db, bon)
    await db.refresh(task)
    return BonTaskRead.model_validate(task)


@router.delete(
    "/{bon_id}/tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_task(
    bon_id: int, task_id: int, db: DBSession, _: CurrentUser
) -> None:
    bon = await _ensure_bon(db, bon_id)
    task = (
        await db.execute(
            select(BonTask).where(
                BonTask.id == task_id, BonTask.bon_id == bon_id
            )
        )
    ).scalar_one_or_none()
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Task not found")
    await db.delete(task)
    await db.flush()
    # Supprimer la dernière tâche non cochée peut compléter le bon.
    await _maybe_autoclasser(db, bon)


@router.post("/{bon_id}/fusionner")
async def fusionner_bons(
    bon_id: int,
    payload: BonFusionPayload,
    db: DBSession,
    user: CurrentUser,
) -> dict:
    """Fusionne des bons (même lieu) DANS le bon `bon_id`.

    Pour chaque bon absorbé :
    - il devient une tâche cochable du bon cible (trace : sa référence) ;
    - ses lignes (heures/matériel) et ses punchs sont déplacés ;
    - les photos/achats de son mini-projet porteur suivent le projet du
      bon cible ;
    - il est ANNULÉ avec une note « fusionné dans BT-xxx » (pas de
      suppression : l'historique reste consultable).
    """
    if user.role not in ("owner", "admin", "manager"):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Réservé aux gestionnaires (fusion de bons).",
        )
    target = await _ensure_bon(db, bon_id)
    if target.status not in _STATUTS_OUVERTS:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Le bon cible est « {target.status} » : fusion impossible.",
        )

    source_ids = [
        i for i in dict.fromkeys(payload.source_bon_ids) if i != target.id
    ]
    if not source_ids:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Aucun bon source à fusionner."
        )
    sources = (
        await db.execute(
            select(BonTravail).where(BonTravail.id.in_(source_ids))
        )
    ).scalars().all()
    if len(sources) != len(source_ids):
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Bon source introuvable."
        )
    for s in sources:
        if s.status not in _STATUTS_OUVERTS:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"Le bon {s.reference} est « {s.status} » : "
                "il ne peut plus être fusionné.",
            )

    return await fusionner_dans(db, target, list(sources))


async def fusionner_dans(
    db, target: BonTravail, sources: List[BonTravail]
) -> dict:
    """Cœur de la fusion : absorbe ``sources`` dans ``target``.

    Appelé par l'endpoint /fusionner (fusion manuelle) ET par le hook de
    création des bons (fusion AUTOMATIQUE des bons du même lieu, retour
    2026-09-13 : « ils auraient dû être mergés ensemble »). L'appelant a
    déjà validé statuts et permissions ; ici on ne lève pas.
    """
    now = datetime.now(timezone.utc)
    next_pos = (
        await db.execute(
            select(func.coalesce(func.max(BonTask.position), -1)).where(
                BonTask.bon_id == target.id
            )
        )
    ).scalar_one() + 1

    # Si le bon cible n'a encore aucune tâche, son propre travail devient
    # la première ligne cochable — le bon fusionné liste TOUT ce qu'il y a
    # à faire au même endroit.
    existing = (
        await db.execute(
            select(func.count(BonTask.id)).where(
                BonTask.bon_id == target.id
            )
        )
    ).scalar_one()
    if not existing:
        db.add(
            BonTask(
                bon_id=target.id,
                position=next_pos,
                title=target.title,
                source_bon_reference=target.reference,
            )
        )
        next_pos += 1

    next_item_pos = (
        await db.execute(
            select(func.coalesce(func.max(BonItem.position), -1)).where(
                BonItem.bon_id == target.id
            )
        )
    ).scalar_one() + 1

    merged: list[str] = []
    for s in sources:
        # 1. Le travail du bon absorbé devient cochable sur le bon cible :
        # ses tâches EXISTANTES sont déplacées telles quelles (état de
        # coche conservé) ; s'il n'en avait pas, son titre devient une
        # tâche unique.
        s_tasks = (
            await db.execute(
                select(BonTask)
                .where(BonTask.bon_id == s.id)
                .order_by(BonTask.position.asc(), BonTask.id.asc())
            )
        ).scalars().all()
        if s_tasks:
            for t in s_tasks:
                t.bon_id = target.id
                t.position = next_pos
                if not t.source_bon_reference:
                    t.source_bon_reference = s.reference
                next_pos += 1
        else:
            titre = s.title
            if s.description and s.description.strip():
                titre = f"{s.title} — {s.description.strip()}"
            db.add(
                BonTask(
                    bon_id=target.id,
                    position=next_pos,
                    title=titre[:500],
                    source_bon_reference=s.reference,
                )
            )
            next_pos += 1

        # 2. Ses lignes de refacturation suivent.
        items = (
            await db.execute(
                select(BonItem)
                .where(BonItem.bon_id == s.id)
                .order_by(BonItem.position.asc(), BonItem.id.asc())
            )
        ).scalars().all()
        for it in items:
            it.bon_id = target.id
            it.position = next_item_pos
            next_item_pos += 1

        # 3. Ses punchs (heures pointées) suivent aussi.
        punches = (
            await db.execute(
                select(Punch).where(Punch.bon_travail_id == s.id)
            )
        ).scalars().all()
        for p in punches:
            p.bon_travail_id = target.id

        # 4. Photos + achats du mini-projet porteur → projet du bon cible
        # (seulement les mini-projets kind="bon_travail" : jamais un vrai
        # projet de construction).
        if s.project_id and s.project_id != target.project_id:
            from app.models.project import Project

            sproj = await db.get(Project, s.project_id)
            if sproj is not None and (sproj.kind or "") == "bon_travail":
                if target.project_id is None:
                    # Le mini-projet du 1er bon absorbé devient celui du
                    # bon cible (il porte déjà les photos).
                    target.project_id = sproj.id
                    sproj.name = target.title or f"Bon {target.reference}"
                else:
                    from app.models.achat import Achat
                    from app.models.project_photo import ProjectPhoto

                    photos = (
                        await db.execute(
                            select(ProjectPhoto).where(
                                ProjectPhoto.project_id == sproj.id
                            )
                        )
                    ).scalars().all()
                    for ph in photos:
                        ph.project_id = target.project_id
                    achats = (
                        await db.execute(
                            select(Achat).where(
                                Achat.project_id == sproj.id
                            )
                        )
                    ).scalars().all()
                    for a in achats:
                        a.project_id = target.project_id

        # 5. Le bon cible hérite de ce qui manque + de l'urgence.
        if target.client_id is None and s.client_id is not None:
            target.client_id = s.client_id
        if target.assignee_user_id is None and s.assignee_user_id is not None:
            target.assignee_user_id = s.assignee_user_id
        if s.is_urgent:
            target.is_urgent = True
        if s.work_notes and s.work_notes.strip():
            target.work_notes = (
                f"{target.work_notes}\n\n" if target.work_notes else ""
            ) + f"[{s.reference}] {s.work_notes.strip()}"

        # 6. Trace des deux côtés, puis annulation du bon absorbé.
        target.description = (
            f"{target.description}\n\n" if target.description else ""
        ) + f"— Fusion du bon {s.reference} « {s.title} »"
        s.description = (
            f"{s.description}\n\n" if s.description else ""
        ) + (
            f"[Fusionné dans le bon {target.reference} "
            f"le {now.date().isoformat()}]"
        )
        # Le cycle ne recule pas : un bon absorbé déjà « planifié » tire
        # le bon cible vers ce statut (utile en fusion AUTO où le bon
        # cible vient d'être créé en brouillon).
        if (
            (target.kind or "") == "interne"
            and _RANG_INTERNE.get(s.status, -1)
            > _RANG_INTERNE.get(target.status, -1)
        ):
            target.status = s.status
        s.status = "cancelled"
        merged.append(s.reference)

    # Roll-up du montant cible (mêmes règles que les lignes du bon).
    from app.api.v1.endpoints.bon_items import _recompute_bon_amount

    await db.flush()
    await _recompute_bon_amount(db, target.id)

    return {
        "target_id": target.id,
        "target_reference": target.reference,
        "merged": merged,
        "tasks_total": next_pos,
    }


async def auto_fusionner_meme_lieu(db, bon: BonTravail) -> list[str]:
    """Fusion AUTOMATIQUE à la création (retour 2026-09-13) : les bons
    de travail INTERNES encore ouverts au même lieu et pour le même
    payeur sont absorbés par le bon qui vient d'être créé — le kanban ne
    montre plus deux cartes pour le même endroit, chaque travail devient
    une tâche cochable du bon survivant.

    Prudence : mêmes kind (interne), client facturé, compagnie
    propriétaire ET adresse (comparée sans casse/accents/ponctuation).
    Best-effort : renvoie les références absorbées, ne lève jamais.
    """
    try:
        if (bon.kind or "") != "interne":
            return []
        cle = adresse_cle(bon.address)
        if not cle:
            return []
        candidats = (
            await db.execute(
                select(BonTravail).where(
                    BonTravail.id != bon.id,
                    BonTravail.kind == "interne",
                    BonTravail.status.in_(
                        ("draft", "accepte_a_planifier", "planifie")
                    ),
                )
            )
        ).scalars().all()
        sources = [
            c
            for c in candidats
            if adresse_cle(c.address) == cle
            and (c.client_id or None) == (bon.client_id or None)
            and (c.owner_entreprise_id or None)
            == (bon.owner_entreprise_id or None)
        ]
        if not sources:
            return []
        out = await fusionner_dans(db, bon, sources)
        log.info(
            "Fusion auto : %s absorbe %s (même lieu « %s »)",
            bon.reference, out["merged"], bon.address,
        )
        return list(out["merged"])
    except Exception:  # noqa: BLE001 — la création du bon prime
        log.exception(
            "Fusion auto des bons du même lieu échouée (bon %s)", bon.id
        )
        return []
