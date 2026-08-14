"""Validation bancaire des loyers (QuickBooks, LECTURE SEULE) — API.

2e validation des loyers posée PAR-DESSUS le suivi manuel existant
(décision Phil + partenaires 2026-08-14, sans IA) :

- Paramètres (manager+) : activer la feature, régler « alerte après N
  jours », découvrir les comptes « Loyer à remettre - X » du plan
  comptable et confirmer le ou LES immeubles suggérés (un compte peut
  couvrir plusieurs immeubles, ou tous — fiducie), lancer la synchro
  (retour = rapport détaillé par compte) ;
- Pôle locatif (tout utilisateur du volet) : état des pastilles
  (✓✓ « Validé banque » / ⚠ « Payé — sans trace bancaire »), encart
  « Encaissés non marqués », FIL BANCAIRE (visualiseur des transactions
  synchronisées, sans appel QBO), confirmation d'un rapprochement
  ambigu (qui apprend l'alias payeur).

⚠️ Ce module n'ÉCRIT JAMAIS dans QuickBooks — voir
``services/qbo_validation_loyers.py``. Aucun courriel, aucun LLM.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import CurrentUser, DBSession
from app.models.immobilier import Immeuble
from app.models.qbo_loyers import (
    QboCompteImmeuble,
    QboCompteLoyer,
    QboTransactionLoyer,
)
from app.services.qbo_validation_loyers import (
    DEFAUT_ALERTE_JOURS,
    VALIDATION_KEY,
    confirmer_transaction,
    decouvrir_comptes,
    etat_validation,
    get_validation_config,
    immeubles_du_compte,
    liens_par_compte,
    lister_transactions,
    rapprocher_compte,
    suggestion_a_la_volee,
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
    #: Immeubles CONFIRMÉS (lien N-N — un compte peut en couvrir
    #: plusieurs). Vide + ``tous_les_immeubles`` = compte fiducie.
    immeuble_ids: List[int] = []
    tous_les_immeubles: bool = False
    #: Suggestions automatiques (liste — « 9085 Millen & 710 Legendre »
    #: suggère les deux) + case « tous » pour un nom générique fiducie.
    suggestion_immeuble_ids: List[int] = []
    suggestion_tous: bool = False
    suggestion_score: Optional[float] = None
    actif: bool = True
    derniere_synchro_le: Optional[datetime] = None


def _compte_read(
    c: QboCompteLoyer, liens: dict[int, List[int]]
) -> CompteRead:
    import json

    try:
        sugg = json.loads(c.suggestion_immeubles_json or "[]")
        if not isinstance(sugg, list):
            sugg = []
    except ValueError:
        sugg = []
    return CompteRead(
        id=c.id,
        qbo_account_id=c.qbo_account_id,
        qbo_account_name=c.qbo_account_name,
        immeuble_ids=liens.get(c.id, []),
        tous_les_immeubles=bool(c.tous_les_immeubles),
        suggestion_immeuble_ids=[int(i) for i in sugg],
        suggestion_tous=bool(c.suggestion_tous),
        suggestion_score=c.suggestion_score,
        actif=bool(c.actif),
        derniere_synchro_le=c.derniere_synchro_le,
    )


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
    #: Immeubles reliés (multi-sélection). Ignoré si
    #: ``tous_les_immeubles`` est coché.
    immeuble_ids: List[int] = []
    tous_les_immeubles: bool = False
    actif: bool = True


class ConfirmerBody(BaseModel):
    bail_id: int
    #: 1er du mois couvert (défaut : mois de la date de la transaction).
    mois_couvert: Optional[date] = None


class SyncRaisons(BaseModel):
    """Ventilation des lignes ignorées d'un compte."""

    sortie_argent: int = 0
    montant_nul: int = 0
    deja_importee: int = 0
    type_non_reconnu: int = 0


class SyncCompteDetail(BaseModel):
    """Rapport de synchro d'UN compte — « 0 importée » sans explication
    est inacceptable (retour Phil 2026-08-14)."""

    compte_id: int
    compte_nom: str
    lues: int = 0
    importees: int = 0
    mises_a_jour: int = 0
    ignorees: int = 0
    raisons: SyncRaisons = SyncRaisons()
    #: Libellés des types d'écriture non reconnus (à rapporter tels
    #: quels pour qu'on puisse les ajouter à la classification).
    types_non_reconnus: List[str] = []
    erreur: Optional[str] = None


class SyncCompteIgnore(BaseModel):
    """Compte SAUTÉ par la synchro (désactivé / sans immeuble) — listé
    dans le rapport parce que « 0 importée » vient souvent de là : le
    compte qui contient les transactions n'est simplement pas lu."""

    compte_id: int
    compte_nom: str
    raison: str


class SyncResult(BaseModel):
    ok: bool = True
    comptes: int = 0
    importees: int = 0
    mises_a_jour: int = 0
    ignorees: int = 0
    details: List[SyncCompteDetail] = []
    comptes_ignores: List[SyncCompteIgnore] = []


# ── Paramètres (manager+) ──────────────────────────────────────────────


async def _immeubles_mappables(db) -> List[Immeuble]:
    return list(
        (
            await db.execute(
                select(Immeuble)
                .where(
                    Immeuble.is_active.is_(True),
                    Immeuble.gestion_externe.isnot(True),
                )
                .order_by(Immeuble.name)
            )
        ).scalars().all()
    )


async def _config_read(db) -> ConfigRead:
    cfg = await get_validation_config()
    comptes = (
        await db.execute(
            select(QboCompteLoyer).order_by(QboCompteLoyer.qbo_account_name)
        )
    ).scalars().all()
    liens = await liens_par_compte(db)
    imms = await _immeubles_mappables(db)
    reads: List[CompteRead] = []
    for c in comptes:
        r = _compte_read(c, liens)
        # Compte découvert avant que la suggestion « tous » /
        # multi-immeubles existe → fiche muette : on recalcule à la
        # lecture (rien n'est persisté) pour que la case fiducie et les
        # immeubles proposés apparaissent quand même.
        sugg = suggestion_a_la_volee(c, liens, imms)
        if sugg:
            r.suggestion_immeuble_ids = sugg["immeuble_ids"]
            r.suggestion_tous = sugg["tous"]
            r.suggestion_score = sugg["score"]
        reads.append(r)
    return ConfigRead(
        active=cfg["active"],
        alerte_jours=cfg["alerte_jours"],
        comptes=reads,
        immeubles=[ImmeubleOption(id=i.id, name=i.name) for i in imms],
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
    """Confirme (ou retire) le ou LES immeubles d'un compte découvert
    (+ la case « tous les immeubles internes » et son interrupteur).
    Les transactions déjà importées suivent le nouveau mapping et sont
    re-rapprochées — sauf les confirmations manuelles."""
    _require_manager(user)
    compte = await db.get(QboCompteLoyer, compte_id)
    if compte is None:
        raise HTTPException(status_code=404, detail="Compte introuvable.")

    # « Tous les immeubles » désactive la sélection fine.
    voulu = [] if payload.tous_les_immeubles else list(
        dict.fromkeys(payload.immeuble_ids)
    )
    for iid in voulu:
        imm = await db.get(Immeuble, iid)
        if imm is None:
            raise HTTPException(
                status_code=404, detail=f"Immeuble {iid} introuvable."
            )
        if imm.gestion_externe:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Immeuble en gestion externe — la perception est "
                    "déléguée, la validation bancaire ne s'y applique pas."
                ),
            )

    compte.tous_les_immeubles = payload.tous_les_immeubles
    compte.immeuble_id = None  # legacy 1-1 neutralisé (lien N-N ci-bas)
    compte.actif = payload.actif

    # Liens N-N : diff idempotent (on ne touche pas aux liens conservés).
    liens_actuels = {
        l.immeuble_id: l
        for l in (
            await db.execute(
                select(QboCompteImmeuble).where(
                    QboCompteImmeuble.compte_id == compte.id
                )
            )
        ).scalars().all()
    }
    for iid, lien in liens_actuels.items():
        if iid not in voulu:
            await db.delete(lien)
    for iid in voulu:
        if iid not in liens_actuels:
            db.add(
                QboCompteImmeuble(
                    compte_id=compte.id,
                    immeuble_id=iid,
                    created_at=datetime.now(timezone.utc),
                )
            )
    await db.flush()

    # Les transactions non confirmées manuellement suivent le mapping :
    # immeuble connu d'avance seulement quand le compte n'en couvre
    # qu'un ; sinon il sera dérivé du bail au re-rapprochement.
    liens = await liens_par_compte(db)
    imm_ids = await immeubles_du_compte(db, compte, liens)
    immeuble_defaut = imm_ids[0] if len(imm_ids) == 1 else None
    for txn in (
        await db.execute(
            select(QboTransactionLoyer).where(
                QboTransactionLoyer.compte_id == compte.id
            )
        )
    ).scalars().all():
        if txn.rapproche_par != "manuel":
            txn.immeuble_id = immeuble_defaut
            # Compte plus mappé du tout → les rapprochements auto
            # n'ont plus de base : on les remet à zéro.
            if not imm_ids and txn.statut in ("rapproche", "ambigu"):
                txn.statut = "non_rapproche"
                txn.bail_id = None
                txn.mois_couvert = None
                txn.mois_couvert_fin = None
                txn.rapproche_par = None
    await db.flush()
    if imm_ids:
        # Re-mapping = les candidats changent → on rejoue TOUT le
        # rapprochement auto (le manuel n'est jamais écrasé).
        await rapprocher_compte(db, compte, liens=liens, forcer=True)
    await db.commit()
    await db.refresh(compte)
    return _compte_read(compte, await liens_par_compte(db))


@router.post("/sync", response_model=SyncResult)
async def sync_maintenant(db: DBSession, user: CurrentUser) -> SyncResult:
    """« Synchroniser maintenant » — importe les écritures publiées des
    comptes mappés (fenêtre glissante) et rejoue le rapprochement.
    Retour = RAPPORT DÉTAILLÉ par compte (lues / importées / mises à
    jour / ignorées + raisons), affiché dans Paramètres."""
    _require_manager(user)
    try:
        stats = await synchroniser_transactions(db)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    await db.commit()
    return SyncResult(ok=True, **stats)


# ── Fil bancaire (visualiseur — lecture de la base, zéro appel QBO) ────


@router.get("/transactions")
async def fil_bancaire(
    db: DBSession,
    user: CurrentUser,
    immeuble_id: Optional[int] = None,
    statut: Optional[str] = None,
) -> Dict[str, Any]:
    """Fil des transactions synchronisées (90 jours, tri date desc) avec
    leur rapprochement — pour la modale « Voir le fil bancaire »
    (Paramètres + encart Paiements). Filtres simples par immeuble et
    par statut. Ne fait AUCUN appel QuickBooks."""
    if statut and statut not in (
        "rapproche", "ambigu", "non_rapproche", "ignoree"
    ):
        raise HTTPException(
            status_code=400,
            detail=(
                "Statut inconnu — attendu : rapproche, ambigu, "
                "non_rapproche ou ignoree."
            ),
        )
    return await lister_transactions(
        db, immeuble_id=immeuble_id, statut=statut
    )


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
    if txn.statut == "ignoree":
        raise HTTPException(
            status_code=400,
            detail=(
                "Sortie d'argent (virement de remise, dépense…) — "
                "jamais un loyer, pas de rapprochement possible."
            ),
        )
    from app.models.immobilier import Bail, Logement

    bail = await db.get(Bail, payload.bail_id)
    if bail is None:
        raise HTTPException(status_code=404, detail="Bail introuvable.")
    logement = await db.get(Logement, bail.logement_id)
    # Le bail doit appartenir à un des immeubles COUVERTS par le compte
    # de la transaction (liens N-N, ou tous les internes — fiducie).
    compte = await db.get(QboCompteLoyer, txn.compte_id)
    imm_autorises = (
        await immeubles_du_compte(db, compte) if compte else []
    )
    if logement is None or (
        imm_autorises and logement.immeuble_id not in imm_autorises
    ):
        raise HTTPException(
            status_code=400,
            detail=(
                "Ce bail n'appartient pas aux immeubles couverts par "
                "le compte QuickBooks de la transaction."
            ),
        )
    txn.immeuble_id = logement.immeuble_id
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
