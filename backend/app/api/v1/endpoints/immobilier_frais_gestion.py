"""Frais de gestion mensuels — page /immobilier/frais-gestion.

Pour chaque immeuble SOUS CONTRAT de gestion (case cochée + % défini),
on facture chaque mois X % des revenus locatifs du MOIS PRÉCÉDENT au
propriétaire (client QuickBooks associé à l'immeuble). La table
``imm_factures_gestion`` (1 ligne max par immeuble × mois) sert de
checklist « facturé / à faire ».

Revenus du mois = paiements de loyers encaissés (baux internes) +
paiements cochés en gestion externe, pour ``mois_couvert`` = ce mois.
QuickBooks : connexion « immobilier », sinon « entreprise » (même
compagnie chez Phil) ; code de taxe partagé (réglage ``timesheet_qbo``).
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.api.deps import CurrentUser, DBSession
from app.integrations.quickbooks import QuickBooksError, get_qbo
from app.models.automation_setting import AutomationSetting
from app.models.immobilier import (
    Bail,
    FactureGestion,
    Immeuble,
    Logement,
    PaiementExterne,
    PaiementLoyer,
)
from app.models.user import User

log = logging.getLogger("immobilier.frais_gestion")

router = APIRouter(
    prefix="/immobilier/frais-gestion", tags=["immobilier-frais-gestion"]
)

DEFAULT_PCT = 10.0

MOIS_FR = [
    "janvier", "février", "mars", "avril", "mai", "juin", "juillet",
    "août", "septembre", "octobre", "novembre", "décembre",
]


def _is_manager(user: User) -> bool:
    try:
        return bool(user.has_min_role("manager"))
    except Exception:  # noqa: BLE001
        return user.role in ("owner", "admin", "manager")


def _mois_precedent(d: date) -> date:
    premier = d.replace(day=1)
    fin_prec = premier.replace(day=1)
    # Reculer d'un jour depuis le 1er du mois courant = dernier jour du
    # mois précédent, puis 1er de ce mois-là.
    from datetime import timedelta

    prec = fin_prec - timedelta(days=1)
    return prec.replace(day=1)


async def _revenus_par_immeuble(db, mois: date) -> Dict[int, float]:
    """Revenus locatifs encaissés par immeuble pour ``mois`` (1er du
    mois) : loyers des baux internes + paiements de gestion externe."""
    out: Dict[int, float] = {}
    rows = (
        await db.execute(
            select(
                Logement.immeuble_id, func.sum(PaiementLoyer.montant)
            )
            .join(Bail, Bail.id == PaiementLoyer.bail_id)
            .join(Logement, Logement.id == Bail.logement_id)
            .where(PaiementLoyer.mois_couvert == mois)
            .group_by(Logement.immeuble_id)
        )
    ).all()
    for iid, m in rows:
        out[int(iid)] = out.get(int(iid), 0.0) + float(m or 0.0)
    rows2 = (
        await db.execute(
            select(
                Logement.immeuble_id, func.sum(PaiementExterne.montant)
            )
            .join(Logement, Logement.id == PaiementExterne.logement_id)
            .where(PaiementExterne.mois_couvert == mois)
            .group_by(Logement.immeuble_id)
        )
    ).all()
    for iid, m in rows2:
        out[int(iid)] = out.get(int(iid), 0.0) + float(m or 0.0)
    return out


# ── Schémas ────────────────────────────────────────────────────────────


class FactureOut(BaseModel):
    id: int
    revenus: float
    pct: float
    montant: float
    qbo_doc_number: Optional[str] = None
    created_at: Optional[str] = None


class ImmeubleRow(BaseModel):
    immeuble_id: int
    name: str
    address: Optional[str] = None
    frais_gestion_actif: bool
    frais_gestion_pct: float
    qbo_customer_id: Optional[str] = None
    qbo_customer_name: Optional[str] = None
    revenus: float
    montant_estime: float
    facture: Optional[FactureOut] = None


class OverviewOut(BaseModel):
    mois: str
    mois_label: str
    rows: List[ImmeubleRow]
    nb_factures: int
    nb_a_facturer: int


class ImmeublePatch(BaseModel):
    frais_gestion_actif: Optional[bool] = None
    frais_gestion_pct: Optional[float] = Field(default=None, ge=0, le=100)
    #: "" = retirer l'association.
    qbo_customer_id: Optional[str] = None
    qbo_customer_name: Optional[str] = None


class FacturerIn(BaseModel):
    immeuble_id: int
    mois: date


class FacturerOut(BaseModel):
    ok: bool
    invoice_id: Optional[str] = None
    doc_number: Optional[str] = None
    revenus: float = 0.0
    pct: float = 0.0
    montant: float = 0.0


# ── Endpoints ──────────────────────────────────────────────────────────


@router.get("", response_model=OverviewOut)
async def overview(
    db: DBSession,
    user: CurrentUser,
    mois: Optional[date] = Query(default=None),
) -> OverviewOut:
    """Checklist du mois : tous les immeubles actifs, leur réglage de
    contrat, les revenus du mois demandé (défaut = mois précédent) et la
    facture si déjà créée."""
    if not _is_manager(user):
        raise HTTPException(status_code=403, detail="Réservé aux gestionnaires")
    m = (
        mois.replace(day=1)
        if mois
        else _mois_precedent(datetime.now(timezone.utc).date())
    )
    immeubles = (
        await db.execute(
            select(Immeuble)
            .where(Immeuble.is_active.is_(True))
            .order_by(Immeuble.name)
        )
    ).scalars().all()
    revenus = await _revenus_par_immeuble(db, m)
    factures = {
        f.immeuble_id: f
        for f in (
            await db.execute(
                select(FactureGestion).where(
                    FactureGestion.mois_couvert == m
                )
            )
        ).scalars().all()
    }
    rows: List[ImmeubleRow] = []
    nb_f = 0
    nb_a = 0
    for imm in immeubles:
        actif = bool(getattr(imm, "frais_gestion_actif", False))
        pct = float(getattr(imm, "frais_gestion_pct", None) or DEFAULT_PCT)
        rev = round(revenus.get(imm.id, 0.0), 2)
        f = factures.get(imm.id)
        if actif and f:
            nb_f += 1
        elif actif:
            nb_a += 1
        rows.append(
            ImmeubleRow(
                immeuble_id=imm.id,
                name=imm.name,
                address=imm.address,
                frais_gestion_actif=actif,
                frais_gestion_pct=pct,
                qbo_customer_id=getattr(imm, "qbo_customer_id", None),
                qbo_customer_name=getattr(imm, "qbo_customer_name", None),
                revenus=rev,
                montant_estime=round(rev * pct / 100.0, 2),
                facture=(
                    FactureOut(
                        id=f.id,
                        revenus=float(f.revenus or 0.0),
                        pct=float(f.pct or 0.0),
                        montant=float(f.montant or 0.0),
                        qbo_doc_number=f.qbo_doc_number,
                        created_at=(
                            f.created_at.isoformat() if f.created_at else None
                        ),
                    )
                    if f
                    else None
                ),
            )
        )
    return OverviewOut(
        mois=m.isoformat(),
        mois_label=f"{MOIS_FR[m.month - 1]} {m.year}",
        rows=rows,
        nb_factures=nb_f,
        nb_a_facturer=nb_a,
    )


@router.patch("/immeubles/{immeuble_id}")
async def patch_immeuble(
    immeuble_id: int,
    payload: ImmeublePatch,
    db: DBSession,
    user: CurrentUser,
) -> dict:
    if not _is_manager(user):
        raise HTTPException(status_code=403, detail="Réservé aux gestionnaires")
    imm = await db.get(Immeuble, immeuble_id)
    if not imm:
        raise HTTPException(status_code=404, detail="Immeuble introuvable")
    if payload.frais_gestion_actif is not None:
        imm.frais_gestion_actif = payload.frais_gestion_actif
    if payload.frais_gestion_pct is not None:
        imm.frais_gestion_pct = payload.frais_gestion_pct
    if payload.qbo_customer_id is not None:
        imm.qbo_customer_id = payload.qbo_customer_id or None
        imm.qbo_customer_name = payload.qbo_customer_name or None
    await db.commit()
    return {"ok": True}


@router.post("/facturer", response_model=FacturerOut)
async def facturer(
    payload: FacturerIn, db: DBSession, user: CurrentUser
) -> FacturerOut:
    """Crée la facture QuickBooks des frais de gestion (X % des revenus
    du mois demandé) et coche le mois dans la checklist."""
    if not _is_manager(user):
        raise HTTPException(status_code=403, detail="Réservé aux gestionnaires")
    imm = await db.get(Immeuble, payload.immeuble_id)
    if not imm:
        raise HTTPException(status_code=404, detail="Immeuble introuvable")
    if not bool(getattr(imm, "frais_gestion_actif", False)):
        raise HTTPException(
            status_code=409,
            detail="Coche d'abord le contrat de gestion sur cet immeuble.",
        )
    m = payload.mois.replace(day=1)
    existing = (
        await db.execute(
            select(FactureGestion).where(
                FactureGestion.immeuble_id == imm.id,
                FactureGestion.mois_couvert == m,
            )
        )
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(
            status_code=409,
            detail="Déjà facturé pour ce mois (voir la checklist).",
        )
    revenus = round(
        (await _revenus_par_immeuble(db, m)).get(imm.id, 0.0), 2
    )
    pct = float(getattr(imm, "frais_gestion_pct", None) or DEFAULT_PCT)
    montant = round(revenus * pct / 100.0, 2)
    if montant <= 0:
        raise HTTPException(
            status_code=409,
            detail=(
                "Aucun revenu locatif enregistré pour "
                f"{MOIS_FR[m.month - 1]} {m.year} sur cet immeuble."
            ),
        )
    if not imm.qbo_customer_id:
        raise HTTPException(
            status_code=422,
            detail=(
                "Choisis le client QuickBooks (le propriétaire) de cet "
                "immeuble dans la colonne « Client QBO »."
            ),
        )

    # Code de taxe : même réglage que la facturation feuille de temps
    # (même compagnie QuickBooks).
    tax_code_id = ""
    setting = await db.get(AutomationSetting, "timesheet_qbo")
    if setting and setting.config_json:
        try:
            tax_code_id = (
                (json.loads(setting.config_json) or {}).get("tax_code_id")
                or ""
            ).strip()
        except Exception:  # noqa: BLE001
            tax_code_id = ""
    if not tax_code_id:
        raise HTTPException(
            status_code=422,
            detail=(
                "QuickBooks exige un code de taxe : choisis-le dans "
                "Gestion d'entreprise → Feuille de temps → Facturation → "
                "Réglages QuickBooks (même QuickBooks)."
            ),
        )

    # Connexion QBO : immobilier, sinon entreprise (même compagnie).
    qbo = get_qbo("immobilier")
    await qbo._load_refresh_from_db()  # noqa: SLF001
    if not qbo.ready:
        qbo = get_qbo("entreprise")
        await qbo._load_refresh_from_db()  # noqa: SLF001
    if not qbo.ready:
        raise HTTPException(
            status_code=503,
            detail=(
                "Aucun QuickBooks connecté pour le locatif — va dans "
                "Paramètres → Comptabilité → « QuickBooks — autres "
                "pôles »."
            ),
        )

    mois_label = f"{MOIS_FR[m.month - 1]} {m.year}"
    try:
        item = await qbo.ensure_item(
            "Frais de gestion",
            description="Frais de gestion immobilière mensuels",
        )
        # Numéro de facture calculé (les compagnies avec numéros
        # personnalisés laissent le champ vide sinon).
        next_num: Optional[str] = None
        try:
            nums_rows = await qbo.query(
                "SELECT DocNumber FROM Invoice "
                "ORDERBY MetaData.CreateTime DESC MAXRESULTS 100"
            )
            nums = [
                int(str(r.get("DocNumber")))
                for r in nums_rows
                if str(r.get("DocNumber") or "").isdigit()
            ]
            next_num = str(max(nums) + 1) if nums else "1000"
        except QuickBooksError:
            next_num = None
        base_payload: Dict[str, Any] = {
            "CustomerRef": {"value": str(imm.qbo_customer_id)},
            "TxnDate": datetime.now(timezone.utc).date().isoformat(),
            "GlobalTaxCalculation": "TaxExcluded",
            "Line": [
                {
                    "DetailType": "SalesItemLineDetail",
                    "Amount": montant,
                    "Description": (
                        f"Frais de gestion {pct:g} % — revenus locatifs "
                        f"de {mois_label} ({revenus:.2f} $) — {imm.name}"
                    ),
                    "SalesItemLineDetail": {
                        "ItemRef": {"value": str(item["Id"])},
                        "Qty": 1,
                        "UnitPrice": montant,
                        "TaxCodeRef": {"value": tax_code_id},
                    },
                }
            ],
            "PrivateNote": (
                f"Créé par Kratos — frais de gestion {imm.name}, "
                f"revenus {mois_label}"
            ),
        }
        tries = 0
        while True:
            body = dict(base_payload)
            if next_num:
                body["DocNumber"] = next_num
            try:
                inv = await qbo.create_invoice(body)
                break
            except QuickBooksError as exc:
                msg = str(exc)
                if (
                    next_num
                    and tries < 3
                    and ("6140" in msg or "uplicate" in msg or "double" in msg)
                ):
                    tries += 1
                    next_num = str(int(next_num) + 1)
                    continue
                raise
    except QuickBooksError as exc:
        raise HTTPException(
            status_code=502, detail=f"QuickBooks a refusé la facture : {exc}"
        )
    invoice = inv.get("Invoice") or inv
    invoice_id = str(invoice.get("Id") or "") or None
    doc_number = str(invoice.get("DocNumber") or "") or None

    db.add(
        FactureGestion(
            immeuble_id=imm.id,
            mois_couvert=m,
            revenus=revenus,
            pct=pct,
            montant=montant,
            qbo_invoice_id=invoice_id,
            qbo_doc_number=doc_number,
            created_by_user_id=user.id,
            created_at=datetime.now(timezone.utc),
        )
    )
    await db.commit()
    log.info(
        "Facture gestion QBO %s — %s %s (%.2f $)",
        doc_number or invoice_id, imm.name, mois_label, montant,
    )
    return FacturerOut(
        ok=True,
        invoice_id=invoice_id,
        doc_number=doc_number,
        revenus=revenus,
        pct=pct,
        montant=montant,
    )


@router.delete("/factures/{facture_id}")
async def delete_facture(
    facture_id: int, db: DBSession, user: CurrentUser
) -> dict:
    """Décoche un mois (ex. facture supprimée dans QuickBooks) — la
    ligne redevient « à facturer »."""
    if not _is_manager(user):
        raise HTTPException(status_code=403, detail="Réservé aux gestionnaires")
    f = await db.get(FactureGestion, facture_id)
    if not f:
        raise HTTPException(status_code=404, detail="Facture introuvable")
    await db.delete(f)
    await db.commit()
    return {"ok": True}
