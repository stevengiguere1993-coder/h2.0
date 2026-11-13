"""Codes d'accès d'un immeuble — porte d'entrée, lock box, garage, alarme,
boîte aux lettres, Wi-Fi… (bug mvilliard 2026-10-17 sur la fiche
/immobilier/immeubles/19 : « ajouter un endroit pour code de porte, code
lock box et autre code relié à l'immeuble »).

Une liste de codes par immeuble (libellé, code, note facultative),
modifiable depuis la fiche et visible par quiconque voit l'immeuble
(mêmes règles de visibilité que la fiche : employé affecté ou manager+).
Les écritures sont journalisées par le middleware d'audit ; la lecture
IA passe par ``kratos_list_entities(immeuble_codes)``.

Codes de porte d'un LOGEMENT (Steven 2026-11-10 : « ajouter un endroit
dans les logements […] il faut mettre les codes des portes quelque part
pour avoir accès au besoin ») : même table, ``logement_id`` renseigné.
La fiche de l'immeuble ne liste que ses propres codes (``logement_id``
NULL) sauf ``?inclure_logements=true`` ; la fiche du logement a ses
routes ``/logements/{id}/codes`` (mêmes règles de visibilité que
l'immeuble du logement).

Partage contrôlé (Steven 2026-11-13, « je ne peux pas donner accès au
code à tous mes employés ») : ajout, modification et retrait réservés aux
gestionnaires (manager+) ; les listes CACHENT la valeur du code
(``code_masque``) et un employé n'y voit que les codes qu'on lui a
partagés (``app/services/codes_acces.py``, routes ``/codes-acces``).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import func, select

from app.api.deps import CurrentUser, DBSession
from app.core.permissions import visible_immeuble_ids
from app.models.code_acces import ImmeubleCodePhoto
from app.models.immobilier import Immeuble, ImmeubleCode, Logement
from app.schemas.immobilier import (
    ImmeubleCodeCreate,
    ImmeubleCodePhotoRead,
    ImmeubleCodeRead,
    ImmeubleCodeUpdate,
)
from app.services import codes_acces as svc

router = APIRouter(prefix="/immobilier", tags=["immobilier-codes"])


def _require_volet(user: CurrentUser) -> None:
    volets = getattr(user, "volets", None)
    if volets is None or "immobilier" not in volets:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Volet « Immobilier » non autorisé pour cet utilisateur.",
        )


def _require_gestionnaire(user) -> None:
    if not svc.peut_gerer(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Seul un gestionnaire peut ajouter ou modifier les codes "
                "d'accès. Demande-lui de te partager le code."
            ),
        )


async def lire_codes(
    db, codes: list[ImmeubleCode], *, reveler: bool = False
) -> List[ImmeubleCodeRead]:
    """Codes + métadonnées de leurs photos ; valeur cachée sauf
    ``reveler``."""
    ids = [c.id for c in codes]
    photos: dict[int, list[ImmeubleCodePhotoRead]] = {}
    if ids:
        rows = (
            await db.execute(
                select(ImmeubleCodePhoto)
                .where(ImmeubleCodePhoto.code_id.in_(ids))
                .order_by(ImmeubleCodePhoto.id.asc())
            )
        ).scalars().all()
        for ph in rows:
            photos.setdefault(ph.code_id, []).append(
                ImmeubleCodePhotoRead.model_validate(ph)
            )
    out = []
    for c in codes:
        out.append(
            ImmeubleCodeRead(
                id=c.id,
                immeuble_id=c.immeuble_id,
                logement_id=c.logement_id,
                libelle=c.libelle,
                code=c.code if reveler else None,
                code_masque=not reveler,
                note=c.note,
                type_code=c.type_code,
                emplacement=c.emplacement,
                photos=photos.get(c.id, []),
                position=c.position or 0,
                created_by_email=c.created_by_email,
                created_at=c.created_at,
                updated_at=c.updated_at,
            )
        )
    return out


async def _immeuble_visible_ou_404(db, user, immeuble_id: int) -> Immeuble:
    """L'immeuble existe ET l'utilisateur le voit (employé affecté ou
    manager+) — un code de porte ne se devine pas par énumération."""
    imm = await db.get(Immeuble, immeuble_id)
    if imm is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Immeuble {immeuble_id} introuvable.",
        )
    visibles = await visible_immeuble_ids(db, user)
    if visibles is not None and imm.id not in visibles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Accès à cet immeuble non autorisé.",
        )
    return imm


async def _code_ou_404(db, immeuble_id: int, code_id: int) -> ImmeubleCode:
    obj = await db.get(ImmeubleCode, code_id)
    if obj is None or obj.immeuble_id != immeuble_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Code introuvable pour cet immeuble.",
        )
    return obj


async def _liste(
    db,
    user,
    immeuble_id: int,
    *,
    logement_id: Optional[int] = None,
    inclure_logements: bool = False,
) -> List[ImmeubleCodeRead]:
    if logement_id is not None:
        # Par logement seulement : un logement déplacé vers une autre
        # fiche d'immeuble garde ses codes.
        q = select(ImmeubleCode).where(ImmeubleCode.logement_id == logement_id)
    else:
        q = select(ImmeubleCode).where(ImmeubleCode.immeuble_id == immeuble_id)
        if not inclure_logements:
            q = q.where(ImmeubleCode.logement_id.is_(None))
    rows = list(
        (
            await db.execute(
                q.order_by(ImmeubleCode.position.asc(), ImmeubleCode.id.asc())
            )
        ).scalars().all()
    )
    # Employé : seulement les codes qu'on lui a partagés.
    visibles = await svc.codes_visibles(db, user, rows)
    return await lire_codes(db, [c for c in rows if c.id in visibles])


async def _creer(
    db,
    user,
    immeuble_id: int,
    payload: ImmeubleCodeCreate,
    logement_id: Optional[int] = None,
) -> ImmeubleCodeRead:
    q = select(func.coalesce(func.max(ImmeubleCode.position), -1)).where(
        ImmeubleCode.immeuble_id == immeuble_id
    )
    q = q.where(
        ImmeubleCode.logement_id == logement_id
        if logement_id is not None
        else ImmeubleCode.logement_id.is_(None)
    )
    derniere = (await db.execute(q)).scalar_one()
    obj = ImmeubleCode(
        immeuble_id=immeuble_id,
        logement_id=logement_id,
        libelle=payload.libelle,
        code=payload.code,
        note=(payload.note or "").strip() or None,
        type_code=payload.type_code,
        emplacement=(payload.emplacement or "").strip() or None,
        position=int(derniere if derniere is not None else -1) + 1,
        created_by_email=getattr(user, "email", None),
    )
    now = datetime.now(timezone.utc)
    obj.created_at = now
    obj.updated_at = now
    db.add(obj)
    await db.commit()
    await db.refresh(obj)
    return (await lire_codes(db, [obj], reveler=True))[0]


async def _modifier(db, obj: ImmeubleCode, payload: ImmeubleCodeUpdate):
    data = payload.model_dump(exclude_unset=True)
    for champ in ("note", "emplacement"):
        if champ in data:
            data[champ] = (data[champ] or "").strip() or None
    for k, v in data.items():
        setattr(obj, k, v)
    obj.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(obj)
    return (await lire_codes(db, [obj], reveler=True))[0]


async def _logement_visible_ou_404(db, user, logement_id: int) -> Logement:
    lg = await db.get(Logement, logement_id)
    if lg is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Logement {logement_id} introuvable.",
        )
    await _immeuble_visible_ou_404(db, user, lg.immeuble_id)
    return lg


async def _code_logement_ou_404(db, logement_id: int, code_id: int) -> ImmeubleCode:
    obj = await db.get(ImmeubleCode, code_id)
    if obj is None or obj.logement_id != logement_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Code introuvable pour ce logement.",
        )
    return obj


@router.get(
    "/immeubles/{immeuble_id}/codes",
    response_model=List[ImmeubleCodeRead],
    summary="Codes d'accès de l'immeuble (porte, lock box, garage…)",
)
async def list_codes_immeuble(
    immeuble_id: int,
    db: DBSession,
    user: CurrentUser,
    inclure_logements: bool = False,
) -> List[ImmeubleCodeRead]:
    """Codes de l'immeuble ; ``inclure_logements`` ajoute ceux de ses
    logements (``logement_id`` renseigné)."""
    _require_volet(user)
    await _immeuble_visible_ou_404(db, user, immeuble_id)
    return await _liste(
        db, user, immeuble_id, inclure_logements=inclure_logements
    )


@router.post(
    "/immeubles/{immeuble_id}/codes",
    response_model=ImmeubleCodeRead,
    status_code=status.HTTP_201_CREATED,
    summary="Ajoute un code d'accès à l'immeuble",
)
async def create_code_immeuble(
    immeuble_id: int,
    payload: ImmeubleCodeCreate,
    db: DBSession,
    user: CurrentUser,
) -> ImmeubleCodeRead:
    _require_volet(user)
    _require_gestionnaire(user)
    await _immeuble_visible_ou_404(db, user, immeuble_id)
    return await _creer(db, user, immeuble_id, payload)


@router.patch(
    "/immeubles/{immeuble_id}/codes/{code_id}",
    response_model=ImmeubleCodeRead,
    summary="Modifie un code d'accès (libellé, code, note, ordre)",
)
async def update_code_immeuble(
    immeuble_id: int,
    code_id: int,
    payload: ImmeubleCodeUpdate,
    db: DBSession,
    user: CurrentUser,
) -> ImmeubleCodeRead:
    _require_volet(user)
    _require_gestionnaire(user)
    await _immeuble_visible_ou_404(db, user, immeuble_id)
    obj = await _code_ou_404(db, immeuble_id, code_id)
    return await _modifier(db, obj, payload)


@router.delete(
    "/immeubles/{immeuble_id}/codes/{code_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Retire un code d'accès de l'immeuble",
)
async def delete_code_immeuble(
    immeuble_id: int, code_id: int, db: DBSession, user: CurrentUser
) -> None:
    _require_volet(user)
    _require_gestionnaire(user)
    await _immeuble_visible_ou_404(db, user, immeuble_id)
    obj = await _code_ou_404(db, immeuble_id, code_id)
    await db.delete(obj)
    await db.commit()


# ─── Codes de porte d'un logement ─────────────────────────────────────


@router.get(
    "/logements/{logement_id}/codes",
    response_model=List[ImmeubleCodeRead],
    summary="Codes de porte du logement (porte de l'unité, lock box…)",
)
async def list_codes_logement(
    logement_id: int, db: DBSession, user: CurrentUser
) -> List[ImmeubleCodeRead]:
    _require_volet(user)
    lg = await _logement_visible_ou_404(db, user, logement_id)
    return await _liste(db, user, lg.immeuble_id, logement_id=logement_id)


@router.post(
    "/logements/{logement_id}/codes",
    response_model=ImmeubleCodeRead,
    status_code=status.HTTP_201_CREATED,
    summary="Ajoute un code de porte au logement",
)
async def create_code_logement(
    logement_id: int,
    payload: ImmeubleCodeCreate,
    db: DBSession,
    user: CurrentUser,
) -> ImmeubleCodeRead:
    _require_volet(user)
    _require_gestionnaire(user)
    lg = await _logement_visible_ou_404(db, user, logement_id)
    return await _creer(db, user, lg.immeuble_id, payload, logement_id)


@router.patch(
    "/logements/{logement_id}/codes/{code_id}",
    response_model=ImmeubleCodeRead,
    summary="Modifie un code de porte du logement",
)
async def update_code_logement(
    logement_id: int,
    code_id: int,
    payload: ImmeubleCodeUpdate,
    db: DBSession,
    user: CurrentUser,
) -> ImmeubleCodeRead:
    _require_volet(user)
    _require_gestionnaire(user)
    await _logement_visible_ou_404(db, user, logement_id)
    obj = await _code_logement_ou_404(db, logement_id, code_id)
    return await _modifier(db, obj, payload)


@router.delete(
    "/logements/{logement_id}/codes/{code_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Retire un code de porte du logement",
)
async def delete_code_logement(
    logement_id: int, code_id: int, db: DBSession, user: CurrentUser
) -> None:
    _require_volet(user)
    _require_gestionnaire(user)
    await _logement_visible_ou_404(db, user, logement_id)
    obj = await _code_logement_ou_404(db, logement_id, code_id)
    await db.delete(obj)
    await db.commit()
