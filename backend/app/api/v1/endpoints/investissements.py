"""Volet Investisseur — CRUD investissements + distributions + portefeuille.

Restreint au volet `investisseur` ou aux admins du portail (création).

Modèle d'autorisation :
- Admin/owner peut tout voir, tout créer, tout modifier.
- Investisseur (volet="investisseur" sans role admin) ne voit QUE ses
  propres investissements (filtrage par user_id).
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import and_, func, select

from app.api.deps import CurrentUser, DBSession
from app.models.immobilier import Evaluation, EvaluationKind, Hypotheque, HypothequeStatus, Immeuble
from app.models.investissement import (
    Distribution,
    DistributionType,
    Investissement,
    InvestissementStatus,
)
from app.schemas.investissement import (
    DistributionCreate,
    DistributionRead,
    InvestisseurPortefeuille,
    InvestissementCreate,
    InvestissementRead,
    InvestissementUpdate,
    InvestissementWithKpis,
)


log = logging.getLogger(__name__)
router = APIRouter(prefix="/investissements", tags=["investissements"])


# ── Helpers ─────────────────────────────────────────────────────────────


def _require_volet(user: CurrentUser) -> None:
    """Refuse l'accès si l'utilisateur n'a pas le volet investisseur."""
    volets = getattr(user, "volets", None)
    if volets is None or "investisseur" not in volets:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Volet « Investisseur » non autorisé pour cet utilisateur.",
        )


def _is_admin(user: CurrentUser) -> bool:
    role = getattr(user, "role", "")
    return role in ("owner", "admin")


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ── Investissements CRUD ──────────────────────────────────────────────


@router.get("", response_model=List[InvestissementRead])
async def list_investissements(
    db: DBSession,
    user: CurrentUser,
    user_id: Optional[int] = None,
    immeuble_id: Optional[int] = None,
) -> List[InvestissementRead]:
    """Liste tous les investissements visibles par l'utilisateur courant.

    Non-admin : forcé sur ses propres user_id.
    """
    _require_volet(user)
    q = select(Investissement).order_by(
        Investissement.date_investissement.desc()
    )
    if not _is_admin(user):
        q = q.where(Investissement.user_id == user.id)
    elif user_id is not None:
        q = q.where(Investissement.user_id == user_id)
    if immeuble_id is not None:
        q = q.where(Investissement.immeuble_id == immeuble_id)

    rows = (await db.execute(q)).scalars().all()
    return [InvestissementRead.model_validate(r) for r in rows]


@router.post(
    "",
    response_model=InvestissementRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_investissement(
    payload: InvestissementCreate, db: DBSession, user: CurrentUser
) -> InvestissementRead:
    """Création d'un investissement — réservé admin/owner."""
    _require_volet(user)
    if not _is_admin(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Création d'investissements réservée aux administrateurs.",
        )

    # Vérification cible
    imm = await db.get(Immeuble, payload.immeuble_id)
    if imm is None:
        raise HTTPException(status_code=404, detail="Immeuble introuvable.")

    obj = Investissement(**payload.model_dump())
    obj.created_at = _now()
    obj.updated_at = _now()
    db.add(obj)
    await db.commit()
    await db.refresh(obj)
    return InvestissementRead.model_validate(obj)


@router.get("/{inv_id}", response_model=InvestissementRead)
async def get_investissement(
    inv_id: int, db: DBSession, user: CurrentUser
) -> InvestissementRead:
    _require_volet(user)
    obj = await db.get(Investissement, inv_id)
    if obj is None:
        raise HTTPException(
            status_code=404, detail="Investissement introuvable."
        )
    if not _is_admin(user) and obj.user_id != user.id:
        raise HTTPException(status_code=403, detail="Accès refusé.")
    return InvestissementRead.model_validate(obj)


@router.patch("/{inv_id}", response_model=InvestissementRead)
async def update_investissement(
    inv_id: int,
    payload: InvestissementUpdate,
    db: DBSession,
    user: CurrentUser,
) -> InvestissementRead:
    _require_volet(user)
    if not _is_admin(user):
        raise HTTPException(
            status_code=403,
            detail="Modification réservée aux administrateurs.",
        )
    obj = await db.get(Investissement, inv_id)
    if obj is None:
        raise HTTPException(
            status_code=404, detail="Investissement introuvable."
        )
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(obj, k, v)
    obj.updated_at = _now()
    await db.commit()
    await db.refresh(obj)
    return InvestissementRead.model_validate(obj)


@router.delete(
    "/{inv_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_investissement(
    inv_id: int, db: DBSession, user: CurrentUser
) -> None:
    _require_volet(user)
    if not _is_admin(user):
        raise HTTPException(
            status_code=403,
            detail="Suppression réservée aux administrateurs.",
        )
    obj = await db.get(Investissement, inv_id)
    if obj is None:
        raise HTTPException(
            status_code=404, detail="Investissement introuvable."
        )
    await db.delete(obj)
    await db.commit()


# ── Distributions ─────────────────────────────────────────────────────


@router.get(
    "/{inv_id}/distributions", response_model=List[DistributionRead]
)
async def list_distributions(
    inv_id: int, db: DBSession, user: CurrentUser
) -> List[DistributionRead]:
    _require_volet(user)
    inv = await db.get(Investissement, inv_id)
    if inv is None:
        raise HTTPException(
            status_code=404, detail="Investissement introuvable."
        )
    if not _is_admin(user) and inv.user_id != user.id:
        raise HTTPException(status_code=403, detail="Accès refusé.")

    rows = (
        await db.execute(
            select(Distribution)
            .where(Distribution.investissement_id == inv_id)
            .order_by(Distribution.date_distribution.desc())
        )
    ).scalars().all()
    return [DistributionRead.model_validate(r) for r in rows]


@router.post(
    "/distributions",
    response_model=DistributionRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_distribution(
    payload: DistributionCreate, db: DBSession, user: CurrentUser
) -> DistributionRead:
    _require_volet(user)
    if not _is_admin(user):
        raise HTTPException(
            status_code=403,
            detail="Enregistrement de distribution réservé aux administrateurs.",
        )
    inv = await db.get(Investissement, payload.investissement_id)
    if inv is None:
        raise HTTPException(
            status_code=404, detail="Investissement introuvable."
        )

    obj = Distribution(**payload.model_dump())
    obj.created_at = _now()
    db.add(obj)
    await db.commit()
    await db.refresh(obj)
    return DistributionRead.model_validate(obj)


@router.delete(
    "/distributions/{dist_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_distribution(
    dist_id: int, db: DBSession, user: CurrentUser
) -> None:
    _require_volet(user)
    if not _is_admin(user):
        raise HTTPException(status_code=403, detail="Réservé aux admins.")
    obj = await db.get(Distribution, dist_id)
    if obj is None:
        raise HTTPException(
            status_code=404, detail="Distribution introuvable."
        )
    await db.delete(obj)
    await db.commit()


# ── Portefeuille (vue consolidée) ──────────────────────────────────────


async def _compute_valeur_part(
    db, inv: Investissement, imm: Immeuble
) -> Optional[float]:
    """Estimation valeur courante de la part d'un investisseur.

    = (valeur_immeuble × parts_pct) - (balance_hypothécaire × parts_pct)

    Source de la valeur : dernière Evaluation (toutes catégories), sinon
    valeur municipale, sinon prix d'achat de l'immeuble.
    """
    if inv.parts_pct is None or inv.parts_pct == 0:
        return None
    # Valeur immeuble : l'évaluation de référence prime, sinon la plus
    # récente (même logique que get_financials).
    val = (
        await db.execute(
            select(Evaluation.valeur)
            .where(
                and_(
                    Evaluation.immeuble_id == imm.id,
                    Evaluation.is_reference.is_(True),
                )
            )
            .order_by(Evaluation.date_evaluation.desc())
            .limit(1)
        )
    ).scalar()
    if val is None:
        val = (
            await db.execute(
                select(Evaluation.valeur)
                .where(Evaluation.immeuble_id == imm.id)
                .order_by(Evaluation.date_evaluation.desc())
                .limit(1)
            )
        ).scalar()
    val_municipale = (
        await db.execute(
            select(Evaluation.valeur)
            .where(
                and_(
                    Evaluation.immeuble_id == imm.id,
                    Evaluation.kind == EvaluationKind.MUNICIPALE.value,
                )
            )
            .order_by(Evaluation.date_evaluation.desc())
            .limit(1)
        )
    ).scalar()
    valeur_imm = (
        float(val)
        if val is not None
        else (
            float(val_municipale)
            if val_municipale is not None
            else (float(imm.purchase_price) if imm.purchase_price else None)
        )
    )
    if valeur_imm is None:
        return None

    # Balance = COALESCE(balance_actuelle, montant_initial) : balance
    # jamais saisie ≠ hypothèque à 0 $ (équité gonflée sinon).
    balance_hyp = float(
        (
            await db.execute(
                select(
                    func.coalesce(
                        func.sum(
                            func.coalesce(
                                Hypotheque.balance_actuelle,
                                Hypotheque.montant_initial,
                            )
                        ),
                        0,
                    )
                )
                .where(
                    and_(
                        Hypotheque.immeuble_id == imm.id,
                        Hypotheque.status == HypothequeStatus.ACTIVE.value,
                    )
                )
            )
        ).scalar()
        or 0
    )
    pct = float(inv.parts_pct) / 100.0
    return round((valeur_imm - balance_hyp) * pct, 2)


@router.get("/me/portefeuille", response_model=InvestisseurPortefeuille)
async def get_my_portefeuille(
    db: DBSession, user: CurrentUser
) -> InvestisseurPortefeuille:
    """Vue consolidée du portefeuille de l'investisseur connecté."""
    _require_volet(user)

    investments = (
        await db.execute(
            select(Investissement)
            .where(
                and_(
                    Investissement.user_id == user.id,
                    Investissement.is_visible_to_investor.is_(True),
                )
            )
            .order_by(Investissement.date_investissement.desc())
        )
    ).scalars().all()

    enriched: List[InvestissementWithKpis] = []
    total_capital = 0.0
    total_distrib = 0.0
    total_valeur = 0.0

    for inv in investments:
        imm = await db.get(Immeuble, inv.immeuble_id)
        if imm is None:
            continue
        # Distributions
        dist_rows = (
            await db.execute(
                select(
                    func.coalesce(func.sum(Distribution.montant), 0),
                    func.count(Distribution.id),
                ).where(Distribution.investissement_id == inv.id)
            )
        ).one()
        total_d = float(dist_rows[0] or 0)
        nb_d = int(dist_rows[1] or 0)

        valeur_part = await _compute_valeur_part(db, inv, imm)
        capital = float(inv.montant_investi)

        dpi = round(total_d / capital, 4) if capital > 0 else None
        tvpi = (
            round((total_d + (valeur_part or 0)) / capital, 4)
            if capital > 0
            else None
        )
        # Rendement annualisé approximatif (linéaire, pas IRR)
        years = max(
            (date.today() - inv.date_investissement).days / 365.25, 0.01
        )
        gain = (total_d + (valeur_part or 0)) - capital
        rendement = (
            round((gain / capital) * 100 / years, 2) if capital > 0 else None
        )

        enriched.append(
            InvestissementWithKpis(
                id=inv.id,
                immeuble_id=imm.id,
                immeuble_name=imm.name,
                immeuble_address=imm.address,
                immeuble_cover_photo_url=imm.cover_photo_url,
                montant_investi=capital,
                parts_pct=float(inv.parts_pct),
                date_investissement=inv.date_investissement,
                status=inv.status,
                total_distributions=round(total_d, 2),
                nb_distributions=nb_d,
                valeur_part_courante=valeur_part,
                dpi=dpi,
                tvpi=tvpi,
                rendement_annuel_estime=rendement,
            )
        )
        total_capital += capital
        total_distrib += total_d
        total_valeur += valeur_part or 0

    dpi_g = (
        round(total_distrib / total_capital, 4)
        if total_capital > 0
        else None
    )
    tvpi_g = (
        round((total_distrib + total_valeur) / total_capital, 4)
        if total_capital > 0
        else None
    )

    return InvestisseurPortefeuille(
        user_id=user.id,
        nb_investissements=len(enriched),
        total_capital_investi=round(total_capital, 2),
        total_distributions=round(total_distrib, 2),
        valeur_portefeuille_courante=round(total_valeur, 2),
        dpi_global=dpi_g,
        tvpi_global=tvpi_g,
        investissements=enriched,
    )
