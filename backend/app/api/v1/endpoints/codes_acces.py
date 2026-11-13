"""Partage contrôlé des codes d'accès (Steven 2026-11-13).

Routes ouvertes à tout compte connecté (un employé de Construction n'a
pas forcément le volet Immobilier) ; chaque route vérifie elle-même le
droit : gestionnaire (manager+) ou partage actif.

- ``GET  /codes-acces/moi`` : mes accès en cours (page « Mes codes »).
- ``GET  /codes-acces/bons/{id}`` : les codes du lieu d'un BT que je peux
  voir (bloc « Accès » de la fiche du BT).
- ``POST /codes-acces/codes/{id}/afficher`` : la valeur, journalisée.
- Photos de l'emplacement : ``GET|POST|DELETE /codes-acces/codes/{id}/photos``.
- Gestionnaires : ``GET|POST /codes-acces/partages``,
  ``POST /codes-acces/partages/{id}/retirer``, ``GET /codes-acces/consultations``,
  ``GET /codes-acces/contexte`` (employés, BT ouverts, projets en cours).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import List, Optional

from fastapi import APIRouter, File, Form, HTTPException, Response, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import or_, select

from app.api.deps import CurrentUser, DBSession
from app.api.v1.endpoints.immobilier_codes import lire_codes
from app.models.bon_travail import BonTravail
from app.models.code_acces import (
    CodeAccesConsultation,
    CodeAccesPartage,
    ImmeubleCodePhoto,
)
from app.models.immobilier import Immeuble, ImmeubleCode, Logement
from app.models.project import Project
from app.models.user import User
from app.schemas.immobilier import ImmeubleCodePhotoRead, ImmeubleCodeRead
from app.services import codes_acces as svc

router = APIRouter(prefix="/codes-acces", tags=["codes-acces"])

PHOTO_MAX_OCTETS = 10 * 1024 * 1024


def _gestionnaire(user) -> None:
    if not svc.peut_gerer(user):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Réservé aux gestionnaires (rôle gestionnaire et plus).",
        )


async def _code_ou_404(db, code_id: int) -> ImmeubleCode:
    c = await db.get(ImmeubleCode, code_id)
    if c is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Code introuvable.")
    return c


# ─── Schémas ───────────────────────────────────────────────────────────


class PartageCreate(BaseModel):
    user_ids: List[int] = Field(..., min_length=1, max_length=50)
    immeuble_id: Optional[int] = None
    logement_id: Optional[int] = None
    #: Un seul code ; vide = tous les codes du logement / de l'immeuble.
    code_id: Optional[int] = None
    mode: str = Field(..., pattern="^(jours|date|bt|projet)$")
    jours: Optional[int] = Field(default=None, ge=1, le=svc.JOURS_MAX)
    fin_le: Optional[date] = None
    bon_travail_id: Optional[int] = None
    project_id: Optional[int] = None
    motif: Optional[str] = Field(default=None, max_length=2000)
    #: Cloche + texto à l'employé (le texto ne contient jamais le code).
    notifier: bool = True


class PartageRead(BaseModel):
    id: int
    user_id: int
    user_nom: Optional[str] = None
    immeuble_id: int
    logement_id: Optional[int] = None
    code_id: Optional[int] = None
    lieu: str
    portee: str
    mode: str
    fin_le: Optional[datetime] = None
    fin_texte: str
    bon_travail_id: Optional[int] = None
    bon_reference: Optional[str] = None
    project_id: Optional[int] = None
    projet_nom: Optional[str] = None
    motif: Optional[str] = None
    accorde_par_email: Optional[str] = None
    actif: bool
    raison_fin: Optional[str] = None
    ferme_le: Optional[datetime] = None
    created_at: datetime


class MonAcces(BaseModel):
    partage: PartageRead
    codes: List[ImmeubleCodeRead]


# ─── Sérialisation ─────────────────────────────────────────────────────


async def _lire_partages(db, etats: list[svc.EtatPartage]) -> List[PartageRead]:
    ps = [e.partage for e in etats]
    uids = {p.user_id for p in ps}
    bt_ids = {p.bon_travail_id for p in ps if p.bon_travail_id}
    pj_ids = {p.project_id for p in ps if p.project_id}
    code_ids = {p.code_id for p in ps if p.code_id}
    noms: dict[int, str] = {}
    if uids:
        for u in (await db.execute(select(User).where(User.id.in_(uids)))).scalars():
            noms[u.id] = u.display_name
    refs: dict[int, str] = {}
    if bt_ids:
        for i, r in (
            await db.execute(
                select(BonTravail.id, BonTravail.reference).where(BonTravail.id.in_(bt_ids))
            )
        ).all():
            refs[int(i)] = r
    pjs: dict[int, str] = {}
    if pj_ids:
        for i, n in (
            await db.execute(select(Project.id, Project.name).where(Project.id.in_(pj_ids)))
        ).all():
            pjs[int(i)] = n
    libelles: dict[int, str] = {}
    if code_ids:
        for i, lib in (
            await db.execute(
                select(ImmeubleCode.id, ImmeubleCode.libelle).where(
                    ImmeubleCode.id.in_(code_ids)
                )
            )
        ).all():
            libelles[int(i)] = lib
    lieux: dict[tuple, str] = {}
    out = []
    for e in etats:
        p = e.partage
        cle = (p.immeuble_id, p.logement_id)
        if cle not in lieux:
            lieux[cle] = await svc.lieu_texte(db, p.immeuble_id, p.logement_id)
        if p.code_id:
            portee = f"Code « {libelles.get(p.code_id, p.code_id)} »"
        elif p.logement_id:
            portee = "Codes du logement et de l'immeuble"
        else:
            portee = "Tous les codes de l'immeuble"
        out.append(
            PartageRead(
                id=p.id,
                user_id=p.user_id,
                user_nom=noms.get(p.user_id),
                immeuble_id=p.immeuble_id,
                logement_id=p.logement_id,
                code_id=p.code_id,
                lieu=lieux[cle],
                portee=portee,
                mode=p.mode,
                fin_le=svc._aware(p.fin_le),
                fin_texte=svc.fin_texte(
                    p,
                    bt_ref=refs.get(p.bon_travail_id or -1),
                    projet=pjs.get(p.project_id or -1),
                ),
                bon_travail_id=p.bon_travail_id,
                bon_reference=refs.get(p.bon_travail_id or -1),
                project_id=p.project_id,
                projet_nom=pjs.get(p.project_id or -1),
                motif=p.motif,
                accorde_par_email=p.accorde_par_email,
                actif=e.actif,
                raison_fin=None if e.actif else e.raison,
                ferme_le=svc._aware(p.ferme_le),
                created_at=svc._aware(p.created_at) or p.created_at,
            )
        )
    return out


# ─── Employé : mes codes ───────────────────────────────────────────────


@router.get("/moi", response_model=List[MonAcces], summary="Mes accès aux codes en cours")
async def mes_codes(db: DBSession, user: CurrentUser) -> List[MonAcces]:
    etats = [e for e in await svc.etats_partages(db, user_id=user.id) if e.actif]
    lus = await _lire_partages(db, etats)
    out = []
    for e, pr in zip(etats, lus):
        codes = await svc.codes_du_partage(db, e.partage)
        out.append(MonAcces(partage=pr, codes=await lire_codes(db, codes)))
    return out


@router.get(
    "/bons/{bon_id}",
    summary="Codes du lieu d'un BT que je peux voir",
)
async def codes_du_bon(bon_id: int, db: DBSession, user: CurrentUser) -> dict:
    bon = await db.get(BonTravail, bon_id)
    if bon is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Bon introuvable.")
    immeuble_id, logement_id = bon.immeuble_id, bon.logement_id
    if logement_id is not None and immeuble_id is None:
        lg = await db.get(Logement, logement_id)
        immeuble_id = lg.immeuble_id if lg is not None else None
    gestion = svc.peut_gerer(user)
    vide = {
        "gestionnaire": gestion,
        "immeuble_id": immeuble_id,
        "logement_id": logement_id,
        "codes": [],
        "partages": [],
        "fin_texte": None,
    }
    if immeuble_id is None:
        return vide
    q = select(ImmeubleCode).where(
        or_(
            ImmeubleCode.logement_id == logement_id
            if logement_id is not None
            else ImmeubleCode.id == -1,
            (ImmeubleCode.immeuble_id == immeuble_id)
            & ImmeubleCode.logement_id.is_(None),
        )
    ).order_by(
        ImmeubleCode.logement_id.is_(None).desc(),
        ImmeubleCode.position.asc(),
        ImmeubleCode.id.asc(),
    )
    codes = list((await db.execute(q)).scalars().all())
    visibles = await svc.codes_visibles(db, user, codes)
    out = dict(vide)
    out["codes"] = [
        c.model_dump(mode="json")
        for c in await lire_codes(db, [c for c in codes if c.id in visibles])
    ]
    if gestion:
        etats = await svc.etats_partages(db, bon_travail_id=bon.id)
        out["partages"] = [
            p.model_dump(mode="json") for p in await _lire_partages(db, etats)
        ]
    else:
        partages = [p for p in visibles.values() if p is not None]
        if partages:
            p = partages[0]
            out["fin_texte"] = svc.fin_texte(p, bt_ref=bon.reference)
    return out


@router.post(
    "/codes/{code_id}/afficher",
    summary="Valeur d'un code (consultation journalisée)",
)
async def afficher(code_id: int, db: DBSession, user: CurrentUser) -> dict:
    c = await _code_ou_404(db, code_id)
    valeur = await svc.afficher_code(db, user, c)
    if valeur is None:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Ce code ne t'est pas partagé (ou ton accès est terminé).",
        )
    await db.commit()
    return {"id": c.id, "code": valeur}


# ─── Photos de l'emplacement ───────────────────────────────────────────


@router.get(
    "/codes/{code_id}/photos",
    response_model=List[ImmeubleCodePhotoRead],
    summary="Photos de l'emplacement d'un code",
)
async def lister_photos(code_id: int, db: DBSession, user: CurrentUser):
    c = await _code_ou_404(db, code_id)
    if not await svc.peut_voir_emplacement(db, user, c):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Code non partagé.")
    rows = (
        await db.execute(
            select(ImmeubleCodePhoto)
            .where(ImmeubleCodePhoto.code_id == c.id)
            .order_by(ImmeubleCodePhoto.id.asc())
        )
    ).scalars().all()
    return [ImmeubleCodePhotoRead.model_validate(r) for r in rows]


@router.post(
    "/codes/{code_id}/photos",
    response_model=ImmeubleCodePhotoRead,
    status_code=status.HTTP_201_CREATED,
    summary="Ajoute une photo de l'emplacement (gestionnaires)",
)
async def ajouter_photo(
    code_id: int,
    db: DBSession,
    user: CurrentUser,
    file: UploadFile = File(...),
    caption: Optional[str] = Form(default=None),
):
    _gestionnaire(user)
    c = await _code_ou_404(db, code_id)
    ct = (file.content_type or "").lower()
    if not ct.startswith("image/"):
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Une photo (image) seulement."
        )
    blob = await file.read()
    if not blob:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Fichier vide.")
    if len(blob) > PHOTO_MAX_OCTETS:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Photo de plus de 10 Mo."
        )
    ph = ImmeubleCodePhoto(
        code_id=c.id,
        image=blob,
        content_type=ct,
        caption=(caption or "").strip()[:500] or None,
        uploaded_by_email=user.email,
        created_at=svc.maintenant(),
    )
    db.add(ph)
    await db.commit()
    await db.refresh(ph)
    return ImmeubleCodePhotoRead.model_validate(ph)


@router.get("/codes/{code_id}/photos/{photo_id}", summary="Image d'une photo")
async def voir_photo(code_id: int, photo_id: int, db: DBSession, user: CurrentUser):
    c = await _code_ou_404(db, code_id)
    if not await svc.peut_voir_emplacement(db, user, c):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Code non partagé.")
    row = (
        await db.execute(
            select(ImmeubleCodePhoto.image, ImmeubleCodePhoto.content_type).where(
                ImmeubleCodePhoto.id == photo_id, ImmeubleCodePhoto.code_id == c.id
            )
        )
    ).first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Photo introuvable.")
    return Response(
        content=row[0],
        media_type=row[1],
        headers={"Cache-Control": "private, no-store"},
    )


@router.delete(
    "/codes/{code_id}/photos/{photo_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Retire une photo (gestionnaires)",
)
async def retirer_photo(code_id: int, photo_id: int, db: DBSession, user: CurrentUser):
    _gestionnaire(user)
    ph = await db.get(ImmeubleCodePhoto, photo_id)
    if ph is None or ph.code_id != code_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Photo introuvable.")
    await db.delete(ph)
    await db.commit()


# ─── Gestionnaires : partages ──────────────────────────────────────────


@router.get(
    "/partages",
    response_model=List[PartageRead],
    summary="Accès partagés (en cours par défaut)",
)
async def lister_partages(
    db: DBSession,
    user: CurrentUser,
    immeuble_id: Optional[int] = None,
    logement_id: Optional[int] = None,
    user_id: Optional[int] = None,
    bon_travail_id: Optional[int] = None,
    actifs: bool = True,
):
    _gestionnaire(user)
    etats = await svc.etats_partages(
        db,
        user_id=user_id,
        immeuble_id=immeuble_id if logement_id is None else None,
        logement_id=logement_id,
        bon_travail_id=bon_travail_id,
        ouverts_seulement=actifs,
        limite=300,
    )
    if logement_id is not None:
        lg = await db.get(Logement, logement_id)
        imm = lg.immeuble_id if lg is not None else None
        etats = [
            e
            for e in etats
            if e.partage.logement_id == logement_id
            or (e.partage.logement_id is None and e.partage.immeuble_id == imm)
        ]
    if actifs:
        etats = [e for e in etats if e.actif]
    return await _lire_partages(db, etats)


@router.post(
    "/partages",
    response_model=List[PartageRead],
    status_code=status.HTTP_201_CREATED,
    summary="Partage des codes à un ou plusieurs employés",
)
async def creer_partage(payload: PartageCreate, db: DBSession, user: CurrentUser):
    _gestionnaire(user)
    try:
        crees = await svc.accorder(
            db,
            par=user,
            user_ids=payload.user_ids,
            immeuble_id=payload.immeuble_id,
            logement_id=payload.logement_id,
            code_id=payload.code_id,
            mode=payload.mode,
            jours=payload.jours,
            fin_le=payload.fin_le,
            bon_travail_id=payload.bon_travail_id,
            project_id=payload.project_id,
            motif=payload.motif,
            notifier=payload.notifier,
        )
    except svc.PartageInvalide as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))
    await db.commit()
    etats = await svc.etats_partages(db, ouverts_seulement=False, limite=5000)
    ids = {p.id for p in crees}
    return await _lire_partages(db, [e for e in etats if e.partage.id in ids])


@router.post(
    "/partages/{partage_id}/retirer",
    response_model=PartageRead,
    summary="Retire un accès avant sa fin",
)
async def retirer_partage(partage_id: int, db: DBSession, user: CurrentUser):
    _gestionnaire(user)
    p = await db.get(CodeAccesPartage, partage_id)
    if p is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Accès introuvable.")
    await svc.fermer(db, p, motif="retire", par_email=user.email)
    await db.commit()
    await db.refresh(p)
    return (await _lire_partages(db, [svc.EtatPartage(p, False, p.ferme_motif)]))[0]


@router.get("/consultations", summary="Journal : qui a affiché quel code")
async def consultations(
    db: DBSession,
    user: CurrentUser,
    code_id: Optional[int] = None,
    immeuble_id: Optional[int] = None,
    logement_id: Optional[int] = None,
    limit: int = 100,
) -> list[dict]:
    _gestionnaire(user)
    q = select(CodeAccesConsultation, ImmeubleCode.libelle).join(
        ImmeubleCode, ImmeubleCode.id == CodeAccesConsultation.code_id
    )
    if code_id is not None:
        q = q.where(CodeAccesConsultation.code_id == code_id)
    if logement_id is not None:
        q = q.where(ImmeubleCode.logement_id == logement_id)
    elif immeuble_id is not None:
        q = q.where(ImmeubleCode.immeuble_id == immeuble_id)
    q = q.order_by(CodeAccesConsultation.created_at.desc()).limit(max(1, min(limit, 500)))
    out = []
    for c, lib in (await db.execute(q)).all():
        out.append(
            {
                "id": c.id,
                "code_id": c.code_id,
                "libelle": lib,
                "user_id": c.user_id,
                "user_email": c.user_email,
                "via": c.via,
                "created_at": (svc._aware(c.created_at) or c.created_at).isoformat(),
            }
        )
    return out


@router.get("/contexte", summary="Employés, BT ouverts et projets pour un partage")
async def contexte(
    db: DBSession,
    user: CurrentUser,
    immeuble_id: Optional[int] = None,
    logement_id: Optional[int] = None,
) -> dict:
    _gestionnaire(user)
    if logement_id is not None and immeuble_id is None:
        lg = await db.get(Logement, logement_id)
        immeuble_id = lg.immeuble_id if lg is not None else None
    users = (
        await db.execute(
            select(User).where(User.is_active.is_(True)).order_by(User.email.asc())
        )
    ).scalars().all()
    employes = [
        {
            "id": u.id,
            "nom": u.display_name,
            "role": u.role,
            # Un gestionnaire voit déjà tous les codes.
            "voit_deja": svc.peut_gerer(u),
        }
        for u in users
        if u.role != "investisseur"
    ]
    bons = []
    if immeuble_id is not None:
        conds = [BonTravail.immeuble_id == immeuble_id]
        if logement_id is not None:
            conds.append(BonTravail.logement_id == logement_id)
        rows = (
            await db.execute(
                select(BonTravail)
                .where(or_(*conds), BonTravail.status.notin_(list(svc.BT_TERMINES)))
                .order_by(BonTravail.created_at.desc())
                .limit(50)
            )
        ).scalars().all()
        bons = [
            {
                "id": b.id,
                "reference": b.reference,
                "title": b.title,
                "assignee_user_id": b.assignee_user_id,
                "logement_id": b.logement_id,
            }
            for b in rows
        ]
    projets = [
        {"id": p.id, "name": p.name, "address": p.address}
        for p in (
            await db.execute(
                select(Project)
                .where(Project.status.notin_(list(svc.PROJET_TERMINES)))
                .order_by(Project.name.asc())
                .limit(300)
            )
        ).scalars().all()
    ]
    imm = await db.get(Immeuble, immeuble_id) if immeuble_id is not None else None
    return {
        "immeuble_id": immeuble_id,
        "logement_id": logement_id,
        "adresse": imm.address if imm is not None else None,
        "employes": employes,
        "bons": bons,
        "projets": projets,
    }
