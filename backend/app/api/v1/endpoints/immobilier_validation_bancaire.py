"""Validation bancaire des loyers (QuickBooks, LECTURE SEULE) — API.

2e validation des loyers posée PAR-DESSUS le suivi manuel existant
(décision Phil + partenaires 2026-08-14, sans IA) :

- Paramètres (manager+) : activer la feature, régler « alerte après N
  jours », découvrir les comptes « Loyer à remettre - X » du plan
  comptable et confirmer l'immeuble suggéré, lancer la synchro ;
- Pôle locatif (tout utilisateur du volet) : état des pastilles
  (✓✓ « Validé banque » / ⚠ « Payé — sans trace bancaire »), encart
  « Encaissés non marqués », confirmation d'un rapprochement ambigu
  (qui apprend l'alias payeur).

⚠️ Ce module n'ÉCRIT JAMAIS dans QuickBooks — voir
``services/qbo_validation_loyers.py``. Aucun courriel, aucun LLM.
"""
from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.api.deps import CurrentUser, DBSession
from app.models.immobilier import Immeuble
from app.models.qbo_loyers import QboCompteLoyer, QboTransactionLoyer
from app.services.qbo_validation_loyers import (
    DEFAUT_ALERTE_JOURS,
    VALIDATION_KEY,
    confirmer_transaction,
    decouvrir_comptes,
    etat_validation,
    get_validation_config,
    rapprocher_compte,
    synchroniser_transactions,
)

log = logging.getLogger(__name__)

router = APIRouter(
    prefix="/immobilier/validation-bancaire",
    tags=["immobilier-validation-bancaire"],
)


def _require_manager(user) -> None:
    if not user.has_min_role("manager"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Réservé aux gestionnaires.",
        )


# ── Schémas ────────────────────────────────────────────────────────────


class CompteRead(BaseModel):
    id: int
    qbo_account_id: str
    qbo_account_name: str
    immeuble_id: Optional[int] = None
    suggestion_immeuble_id: Optional[int] = None
    suggestion_score: Optional[float] = None
    actif: bool = True
    derniere_synchro_le: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class ImmeubleOption(BaseModel):
    id: int
    name: str


class ConfigRead(BaseModel):
    active: bool
    alerte_jours: int
    comptes: List[CompteRead]
    #: Immeubles proposables (actifs, hors gestion externe).
    immeubles: List[ImmeubleOption]


class ConfigWrite(BaseModel):
    active: bool
    alerte_jours: int = Field(
        default=DEFAUT_ALERTE_JOURS, ge=1, le=60,
        description="⚠ « sans trace bancaire » après N jours.",
    )


class CompteWrite(BaseModel):
    immeuble_id: Optional[int] = None
    actif: bool = True


class ConfirmerBody(BaseModel):
    bail_id: int
    #: 1er du mois couvert (défaut : mois de la date de la transaction).
    mois_couvert: Optional[date] = None


class SyncResult(BaseModel):
    ok: bool = True
    comptes: int = 0
    importees: int = 0
    mises_a_jour: int = 0


# ── Paramètres (manager+) ──────────────────────────────────────────────


async def _immeubles_options(db) -> List[ImmeubleOption]:
    rows = (
        await db.execute(
            select(Immeuble)
            .where(
                Immeuble.is_active.is_(True),
                Immeuble.gestion_externe.isnot(True),
            )
            .order_by(Immeuble.name)
        )
    ).scalars().all()
    return [ImmeubleOption(id=i.id, name=i.name) for i in rows]


async def _config_read(db) -> ConfigRead:
    cfg = await get_validation_config()
    comptes = (
        await db.execute(
            select(QboCompteLoyer).order_by(QboCompteLoyer.qbo_account_name)
        )
    ).scalars().all()
    return ConfigRead(
        active=cfg["active"],
        alerte_jours=cfg["alerte_jours"],
        comptes=[CompteRead.model_validate(c) for c in comptes],
        immeubles=await _immeubles_options(db),
    )


@router.get("/config", response_model=ConfigRead)
async def get_config(db: DBSession, user: CurrentUser) -> ConfigRead:
    return await _config_read(db)


@router.put("/config", response_model=ConfigRead)
async def put_config(
    payload: ConfigWrite, db: DBSession, user: CurrentUser
) -> ConfigRead:
    _require_manager(user)
    from app.services.automation_state import set_automation_config

    await set_automation_config(
        db,
        VALIDATION_KEY,
        {"active": payload.active, "alerte_jours": payload.alerte_jours},
        user_id=user.id,
    )
    await db.commit()
    log.info(
        "Validation bancaire loyers : active=%s alerte_jours=%s par %s",
        payload.active, payload.alerte_jours, user.email,
    )
    return await _config_read(db)


@router.post("/comptes/decouvrir", response_model=ConfigRead)
async def decouvrir(db: DBSession, user: CurrentUser) -> ConfigRead:
    """Interroge le plan comptable QBO (lecture seule) et met à jour la
    liste des comptes « Loyer à remettre - X » + les suggestions."""
    _require_manager(user)
    try:
        await decouvrir_comptes(db)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:  # noqa: BLE001 — erreur QBO lisible
        raise HTTPException(
            status_code=502,
            detail=f"Lecture du plan comptable QuickBooks échouée : {exc}",
        )
    await db.commit()
    return await _config_read(db)


@router.put("/comptes/{compte_id}", response_model=CompteRead)
async def put_compte(
    compte_id: int,
    payload: CompteWrite,
    db: DBSession,
    user: CurrentUser,
) -> CompteRead:
    """Confirme (ou retire) l'immeuble d'un compte découvert + son
    interrupteur. Les transactions déjà importées suivent le nouveau
    mapping et sont re-rapprochées."""
    _require_manager(user)
    compte = await db.get(QboCompteLoyer, compte_id)
    if compte is None:
        raise HTTPException(status_code=404, detail="Compte introuvable.")
    if payload.immeuble_id is not None:
        imm = await db.get(Immeuble, payload.immeuble_id)
        if imm is None:
            raise HTTPException(
                status_code=404, detail="Immeuble introuvable."
            )
        if imm.gestion_externe:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Immeuble en gestion externe — la perception est "
                    "déléguée, la validation bancaire ne s'y applique pas."
                ),
            )
    compte.immeuble_id = payload.immeuble_id
    compte.actif = payload.actif
    # Les transactions déjà importées suivent le mapping.
    for txn in (
        await db.execute(
            select(QboTransactionLoyer).where(
                QboTransactionLoyer.compte_id == compte.id
            )
        )
    ).scalars().all():
        txn.immeuble_id = compte.immeuble_id
    await db.flush()
    if compte.immeuble_id is not None:
        await rapprocher_compte(db, compte)
    await db.commit()
    await db.refresh(compte)
    return CompteRead.model_validate(compte)


@router.post("/sync", response_model=SyncResult)
async def sync_maintenant(db: DBSession, user: CurrentUser) -> SyncResult:
    """« Synchroniser maintenant » — importe les écritures publiées des
    comptes mappés (fenêtre glissante) et rejoue le rapprochement."""
    _require_manager(user)
    try:
        stats = await synchroniser_transactions(db)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    await db.commit()
    return SyncResult(ok=True, **stats)


# ── Pôle locatif : état + confirmation ─────────────────────────────────


@router.get("/etat")
async def etat(
    db: DBSession, user: CurrentUser, mois: Optional[str] = None
) -> Dict[str, Any]:
    """État de la 2e validation pour un mois (pastilles + encarts).
    Feature inactive → ``{"active": false}`` et rien d'autre."""
    if mois:
        try:
            month_start = datetime.strptime(
                mois + "-01", "%Y-%m-%d"
            ).date()
        except ValueError:
            raise HTTPException(
                status_code=400, detail="Format mois attendu : YYYY-MM."
            )
    else:
        month_start = date.today().replace(day=1)
    return await etat_validation(db, month_start)


@router.post("/transactions/{txn_id}/confirmer")
async def confirmer(
    txn_id: int,
    payload: ConfirmerBody,
    db: DBSession,
    user: CurrentUser,
) -> Dict[str, Any]:
    """Confirme le bail d'une transaction ambiguë/non rapprochée. La
    confirmation apprend l'alias payeur — le mois suivant, la même
    provenance se rapproche toute seule."""
    txn = await db.get(QboTransactionLoyer, txn_id)
    if txn is None:
        raise HTTPException(
            status_code=404, detail="Transaction introuvable."
        )
    from app.models.immobilier import Bail, Logement

    bail = await db.get(Bail, payload.bail_id)
    if bail is None:
        raise HTTPException(status_code=404, detail="Bail introuvable.")
    logement = await db.get(Logement, bail.logement_id)
    if (
        txn.immeuble_id is not None
        and (logement is None or logement.immeuble_id != txn.immeuble_id)
    ):
        raise HTTPException(
            status_code=400,
            detail=(
                "Ce bail n'appartient pas à l'immeuble de la "
                "transaction (compte QuickBooks)."
            ),
        )
    await confirmer_transaction(
        db, txn, payload.bail_id, payload.mois_couvert
    )
    await db.commit()
    return {
        "ok": True,
        "txn_id": txn.id,
        "bail_id": txn.bail_id,
        "mois_couvert": (
            txn.mois_couvert.isoformat() if txn.mois_couvert else None
        ),
        "statut": txn.statut,
    }
