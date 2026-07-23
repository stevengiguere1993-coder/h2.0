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


async def _revenus_tous_mois(db) -> Dict[tuple, float]:
    """Revenus locatifs encaissés par (immeuble, mois) — tous les mois
    confondus. Sert au solde des mois manqués + au mois affiché."""
    out: Dict[tuple, float] = {}
    rows = (
        await db.execute(
            select(
                Logement.immeuble_id,
                PaiementLoyer.mois_couvert,
                func.sum(PaiementLoyer.montant),
            )
            .join(Bail, Bail.id == PaiementLoyer.bail_id)
            .join(Logement, Logement.id == Bail.logement_id)
            .group_by(Logement.immeuble_id, PaiementLoyer.mois_couvert)
        )
    ).all()
    for iid, mo, mt in rows:
        key = (int(iid), mo)
        out[key] = out.get(key, 0.0) + float(mt or 0.0)
    rows2 = (
        await db.execute(
            select(
                Logement.immeuble_id,
                PaiementExterne.mois_couvert,
                func.sum(PaiementExterne.montant),
            )
            .join(Logement, Logement.id == PaiementExterne.logement_id)
            .group_by(Logement.immeuble_id, PaiementExterne.mois_couvert)
        )
    ).all()
    for iid, mo, mt in rows2:
        key = (int(iid), mo)
        out[key] = out.get(key, 0.0) + float(mt or 0.0)
    return out


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
    #: Dernier mois déjà facturé (tous mois confondus) — dashboard.
    derniere_facture_mois: Optional[str] = None
    #: 1er du mois à partir duquel on facture ("YYYY-MM-01").
    frais_gestion_depuis: Optional[str] = None
    #: Solde cumulé des transactions à facturer (revenus jamais
    #: facturés, jusqu'au mois précédent inclus).
    solde: float = 0.0
    #: Une transaction = (mois de revenus jamais facturé) avec le
    #: montant calculé — s'ajoute au panier de facture côté UI.
    a_facturer: List[Dict[str, Any]] = []


class HistoriqueOut(BaseModel):
    facture_id: int
    immeuble_id: int
    immeuble_name: str
    mois: str
    label: str
    montant: float
    doc_number: Optional[str] = None
    created_at: Optional[str] = None


class OverviewOut(BaseModel):
    mois: str
    mois_label: str
    rows: List[ImmeubleRow]
    nb_factures: int
    nb_a_facturer: int
    historique: List[HistoriqueOut] = []


class ImmeublePatch(BaseModel):
    frais_gestion_actif: Optional[bool] = None
    frais_gestion_pct: Optional[float] = Field(default=None, ge=0, le=100)
    frais_gestion_depuis: Optional[date] = None
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
    revenus_tous = await _revenus_tous_mois(db)
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
    # Tous les couples (immeuble, mois) déjà facturés — pour repérer les
    # mois MANQUÉS (revenus jamais facturés).
    factures_tous = {
        (int(iid), fm)
        for iid, fm in (
            await db.execute(
                select(
                    FactureGestion.immeuble_id,
                    FactureGestion.mois_couvert,
                )
            )
        ).all()
    }
    # Facturable = jusqu'au mois EN COURS inclus (retour Phil 2026-07-22 :
    # les loyers de juillet rentrent début juillet — il doit pouvoir les
    # facturer sans attendre le 1er août). L'UI marque le mois en cours
    # d'un badge « mois en cours » (revenus encore susceptibles de bouger).
    dernier_mois_facturable = datetime.now(timezone.utc).date().replace(
        day=1
    )
    derniers = {
        int(iid): dm
        for iid, dm in (
            await db.execute(
                select(
                    FactureGestion.immeuble_id,
                    func.max(FactureGestion.mois_couvert),
                ).group_by(FactureGestion.immeuble_id)
            )
        ).all()
    }
    rows: List[ImmeubleRow] = []
    nb_f = 0
    nb_a = 0
    for imm in immeubles:
        actif = bool(getattr(imm, "frais_gestion_actif", False))
        pct = float(getattr(imm, "frais_gestion_pct", None) or DEFAULT_PCT)
        rev = round(revenus_tous.get((imm.id, m), 0.0), 2)
        f = factures.get(imm.id)
        # Solde des mois manqués : revenus enregistrés, jamais facturés,
        # jusqu'au mois précédent inclus, à partir de « facturer depuis ».
        depuis = getattr(imm, "frais_gestion_depuis", None)
        solde = 0.0
        manques: List[Dict[str, Any]] = []
        if actif:
            for (iid, mo), montant_rev in revenus_tous.items():
                if iid != imm.id or montant_rev <= 0:
                    continue
                if mo > dernier_mois_facturable:
                    continue
                if depuis and mo < depuis:
                    continue
                if (imm.id, mo) in factures_tous:
                    continue
                mnt = round(montant_rev * pct / 100.0, 2)
                solde += mnt
                manques.append(
                    {
                        "mois": mo.isoformat(),
                        "label": f"{MOIS_FR[mo.month - 1]} {mo.year}",
                        "revenus": round(montant_rev, 2),
                        "montant": mnt,
                    }
                )
            manques.sort(key=lambda x: x["mois"])
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
                derniere_facture_mois=(
                    f"{MOIS_FR[derniers[imm.id].month - 1]} "
                    f"{derniers[imm.id].year}"
                    if imm.id in derniers
                    else None
                ),
                frais_gestion_depuis=(
                    depuis.isoformat() if depuis else None
                ),
                solde=round(solde, 2),
                a_facturer=manques,
            )
        )
    # Historique des dernières factures créées (checklist « fait »).
    noms = {imm.id: imm.name for imm in immeubles}
    historique = [
        HistoriqueOut(
            facture_id=f.id,
            immeuble_id=f.immeuble_id,
            immeuble_name=noms.get(f.immeuble_id, f"Immeuble {f.immeuble_id}"),
            mois=f.mois_couvert.isoformat(),
            label=(
                f"{MOIS_FR[f.mois_couvert.month - 1]} {f.mois_couvert.year}"
            ),
            montant=float(f.montant or 0.0),
            doc_number=f.qbo_doc_number,
            created_at=(f.created_at.isoformat() if f.created_at else None),
        )
        for f in (
            await db.execute(
                select(FactureGestion)
                .order_by(FactureGestion.created_at.desc())
                .limit(30)
            )
        ).scalars().all()
    ]

    return OverviewOut(
        mois=m.isoformat(),
        mois_label=f"{MOIS_FR[m.month - 1]} {m.year}",
        rows=rows,
        nb_factures=nb_f,
        nb_a_facturer=nb_a,
        historique=historique,
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
    if payload.frais_gestion_depuis is not None:
        imm.frais_gestion_depuis = payload.frais_gestion_depuis.replace(
            day=1
        )
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


class LigneGroupeIn(BaseModel):
    immeuble_id: int
    mois: date
    #: Montant FINAL de la ligne — modifiable à la main dans le panier.
    montant: float = Field(gt=0)


class FacturerGroupeIn(BaseModel):
    qbo_customer_id: str = Field(min_length=1)
    lignes: List[LigneGroupeIn] = Field(min_length=1)


class FacturerGroupeOut(BaseModel):
    ok: bool
    invoice_id: Optional[str] = None
    doc_number: Optional[str] = None
    total: float = 0.0
    nb_lignes: int = 0


@router.post("/facturer-groupe", response_model=FacturerGroupeOut)
async def facturer_groupe(
    payload: FacturerGroupeIn, db: DBSession, user: CurrentUser
) -> FacturerGroupeOut:
    """Crée UNE facture QuickBooks pour un client avec PLUSIEURS lignes
    de frais de gestion (le « panier » de la page) — montants finaux
    fournis par l'UI (modifiables à la main). Coche chaque
    (immeuble, mois) dans la checklist."""
    if not _is_manager(user):
        raise HTTPException(status_code=403, detail="Réservé aux gestionnaires")

    # Validation des lignes + collecte des infos (immeuble, revenus, pct).
    revenus_tous = await _revenus_tous_mois(db)
    factures_tous = {
        (int(iid), fm)
        for iid, fm in (
            await db.execute(
                select(
                    FactureGestion.immeuble_id,
                    FactureGestion.mois_couvert,
                )
            )
        ).all()
    }
    details: List[Dict[str, Any]] = []
    vus: set = set()
    for ligne in payload.lignes:
        imm = await db.get(Immeuble, ligne.immeuble_id)
        if not imm:
            raise HTTPException(status_code=404, detail="Immeuble introuvable")
        if str(imm.qbo_customer_id or "") != payload.qbo_customer_id:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"« {imm.name} » n'est pas associé à ce client "
                    "QuickBooks — une facture = un seul client."
                ),
            )
        m = ligne.mois.replace(day=1)
        if (imm.id, m) in factures_tous or (imm.id, m) in vus:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"« {imm.name} » — {MOIS_FR[m.month - 1]} {m.year} "
                    "est déjà facturé."
                ),
            )
        vus.add((imm.id, m))
        details.append(
            {
                "imm": imm,
                "mois": m,
                "montant": round(float(ligne.montant), 2),
                "revenus": round(revenus_tous.get((imm.id, m), 0.0), 2),
                "pct": float(
                    getattr(imm, "frais_gestion_pct", None) or DEFAULT_PCT
                ),
            }
        )

    # Code de taxe partagé (même QuickBooks que la feuille de temps).
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

    total = round(sum(d["montant"] for d in details), 2)
    try:
        item = await qbo.ensure_item(
            "Frais de gestion",
            description="Frais de gestion immobilière mensuels",
        )
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
            "CustomerRef": {"value": payload.qbo_customer_id},
            "TxnDate": datetime.now(timezone.utc).date().isoformat(),
            "GlobalTaxCalculation": "TaxExcluded",
            "Line": [
                {
                    "DetailType": "SalesItemLineDetail",
                    "Amount": d["montant"],
                    "Description": (
                        f"Frais de gestion {d['pct']:g} % — revenus "
                        f"locatifs de {MOIS_FR[d['mois'].month - 1]} "
                        f"{d['mois'].year} ({d['revenus']:.2f} $) — "
                        f"{d['imm'].name}"
                    ),
                    "SalesItemLineDetail": {
                        "ItemRef": {"value": str(item["Id"])},
                        "Qty": 1,
                        "UnitPrice": d["montant"],
                        "TaxCodeRef": {"value": tax_code_id},
                    },
                }
                for d in details
            ],
            "PrivateNote": "Créé par Kratos — frais de gestion mensuels",
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

    now = datetime.now(timezone.utc)
    for d in details:
        db.add(
            FactureGestion(
                immeuble_id=d["imm"].id,
                mois_couvert=d["mois"],
                revenus=d["revenus"],
                pct=d["pct"],
                montant=d["montant"],
                qbo_invoice_id=invoice_id,
                qbo_doc_number=doc_number,
                created_by_user_id=user.id,
                created_at=now,
            )
        )
    await db.commit()
    log.info(
        "Facture gestion groupée QBO %s — %d lignes (%.2f $)",
        doc_number or invoice_id, len(details), total,
    )
    return FacturerGroupeOut(
        ok=True,
        invoice_id=invoice_id,
        doc_number=doc_number,
        total=total,
        nb_lignes=len(details),
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
