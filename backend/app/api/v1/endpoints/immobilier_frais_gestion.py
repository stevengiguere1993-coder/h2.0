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
    LocationDossier,
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
    #: Frais de relocation au contrat (logement complet / chambre).
    frais_relocation_logement: Optional[float] = None
    frais_relocation_chambre: Optional[float] = None
    qbo_customer_id: Optional[str] = None
    qbo_customer_name: Optional[str] = None
    revenus: float
    montant_estime: float
    facture: Optional[FactureOut] = None
    #: Dernier mois déjà facturé (tous mois confondus) — dashboard.
    derniere_facture_mois: Optional[str] = None
    #: 1er du mois à partir duquel on facture ("YYYY-MM-01").
    frais_gestion_depuis: Optional[str] = None
    #: Solde cumulé des transactions FACTURABLES (mois terminés jamais
    #: facturés + compléments de loyers payés en retard).
    solde: float = 0.0
    #: Montant du mois EN COURS (visible mais pas encore facturable).
    a_venir: float = 0.0
    #: Transactions du client : type "mois" (mois terminé jamais
    #: facturé), "complement" (loyers arrivés après la facture du mois)
    #: ou "en_cours" (mois courant, facturable le 1er du mois suivant).
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
    #: True = ligne « complément » (loyers payés après la facture du mois).
    complement: bool = False
    #: 'gestion' | 'relocation' | 'manuel'.
    type_ligne: str = "gestion"


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
    frais_relocation_logement: Optional[float] = Field(default=None, ge=0)
    frais_relocation_chambre: Optional[float] = Field(default=None, ge=0)
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
    # Revenus DÉJÀ FACTURÉS par (immeuble, mois) — sommés, car un mois
    # peut porter plusieurs lignes (facture + compléments de loyers
    # payés en retard). Le delta avec les revenus enregistrés donne les
    # compléments à facturer. Lignes 'gestion' seulement : les frais de
    # relocation/manuels (revenus 0) ne doivent pas marquer un mois
    # comme « déjà facturé ».
    factures_sommes: Dict[tuple, float] = {}
    for iid, fm, frev in (
        await db.execute(
            select(
                FactureGestion.immeuble_id,
                FactureGestion.mois_couvert,
                func.sum(FactureGestion.revenus),
            )
            .where(FactureGestion.type_ligne == "gestion")
            .group_by(
                FactureGestion.immeuble_id, FactureGestion.mois_couvert
            )
        )
    ).all():
        factures_sommes[(int(iid), fm)] = float(frev or 0.0)
    # Relocations abouties (« reloué ») par immeuble — un frais fixe au
    # contrat (tarif logement complet vs chambre) est facturable dès que
    # le dossier aboutit, s'il n'a pas déjà été facturé.
    reloc_par_immeuble: Dict[int, list] = {}
    for dossier, logement in (
        await db.execute(
            select(LocationDossier, Logement)
            .join(Logement, Logement.id == LocationDossier.logement_id)
            .where(LocationDossier.statut == "reloue")
        )
    ).all():
        reloc_par_immeuble.setdefault(int(logement.immeuble_id), []).append(
            (dossier, logement)
        )
    dossiers_factures = {
        int(did)
        for (did,) in (
            await db.execute(
                select(FactureGestion.relocation_dossier_id).where(
                    FactureGestion.relocation_dossier_id.is_not(None)
                )
            )
        ).all()
    }
    # Retour Phil 2026-07-23 : le mois EN COURS est VISIBLE (badge) mais
    # ne se facture qu'à partir du 1er du mois suivant — d'autres loyers
    # peuvent encore rentrer.
    premier_mois_courant = datetime.now(timezone.utc).date().replace(day=1)
    if premier_mois_courant.month == 12:
        prochain_mois = premier_mois_courant.replace(
            year=premier_mois_courant.year + 1, month=1
        )
    else:
        prochain_mois = premier_mois_courant.replace(
            month=premier_mois_courant.month + 1
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
        # Transactions du client : mois terminés jamais facturés (solde),
        # compléments (loyers payés APRÈS la facture du mois) et mois en
        # cours (visible, facturable le 1er du mois suivant).
        depuis = getattr(imm, "frais_gestion_depuis", None)
        solde = 0.0
        a_venir = 0.0
        manques: List[Dict[str, Any]] = []
        if actif:
            for (iid, mo), montant_rev in revenus_tous.items():
                if iid != imm.id or montant_rev <= 0:
                    continue
                if mo > premier_mois_courant:
                    continue
                if depuis and mo < depuis:
                    continue
                rev_facture = factures_sommes.get((imm.id, mo))
                if rev_facture is None:
                    rev_a_facturer = round(montant_rev, 2)
                    tx_type = "mois"
                else:
                    # Mois déjà facturé : seul le delta (loyers arrivés
                    # depuis) reste facturable, en « complément ».
                    rev_a_facturer = round(montant_rev - rev_facture, 2)
                    tx_type = "complement"
                if rev_a_facturer <= 0.005:
                    continue
                mnt = round(rev_a_facturer * pct / 100.0, 2)
                if mnt <= 0:
                    continue
                en_cours = mo >= premier_mois_courant
                if en_cours:
                    tx_type = "en_cours"
                    a_venir += mnt
                else:
                    solde += mnt
                manques.append(
                    {
                        "mois": mo.isoformat(),
                        "label": f"{MOIS_FR[mo.month - 1]} {mo.year}",
                        "revenus": rev_a_facturer,
                        "montant": mnt,
                        "type": tx_type,
                        "facturable": not en_cours,
                        "facturable_des": (
                            prochain_mois.isoformat() if en_cours else None
                        ),
                    }
                )
            # Frais de relocation : dossiers « reloué » pas encore
            # facturés, au tarif du contrat (chambre vs logement).
            frais_log = float(
                getattr(imm, "frais_relocation_logement", None) or 0.0
            )
            frais_ch = float(
                getattr(imm, "frais_relocation_chambre", None) or 0.0
            )
            for dossier, logement in reloc_par_immeuble.get(imm.id, []):
                if dossier.id in dossiers_factures:
                    continue
                en_chambres = bool(
                    getattr(logement, "location_en_chambres", False)
                )
                frais = frais_ch if en_chambres else frais_log
                if frais <= 0:
                    continue
                quand = dossier.reloue_le
                if depuis and quand and quand.replace(day=1) < depuis:
                    continue
                unite = ("ch. " if en_chambres else "log. ") + str(
                    logement.numero
                )
                lbl = f"Relocation {unite}"
                if quand:
                    lbl += (
                        f" · reloué le {quand.day} "
                        f"{MOIS_FR[quand.month - 1]}"
                    )
                solde += frais
                manques.append(
                    {
                        "mois": (
                            quand.isoformat()
                            if quand
                            else premier_mois_courant.isoformat()
                        ),
                        "label": lbl,
                        "revenus": 0.0,
                        "montant": round(frais, 2),
                        "type": "relocation",
                        "facturable": True,
                        "facturable_des": None,
                        "dossier_id": dossier.id,
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
                frais_relocation_logement=(
                    float(imm.frais_relocation_logement)
                    if getattr(imm, "frais_relocation_logement", None)
                    is not None
                    else None
                ),
                frais_relocation_chambre=(
                    float(imm.frais_relocation_chambre)
                    if getattr(imm, "frais_relocation_chambre", None)
                    is not None
                    else None
                ),
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
                a_venir=round(a_venir, 2),
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
                getattr(f, "libelle", None)
                if getattr(f, "type_ligne", "gestion") != "gestion"
                and getattr(f, "libelle", None)
                else (
                    f"{MOIS_FR[f.mois_couvert.month - 1]} "
                    f"{f.mois_couvert.year}"
                )
            ),
            montant=float(f.montant or 0.0),
            doc_number=f.qbo_doc_number,
            created_at=(f.created_at.isoformat() if f.created_at else None),
            complement=bool(getattr(f, "est_complement", False)),
            type_ligne=getattr(f, "type_ligne", None) or "gestion",
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
    if payload.frais_relocation_logement is not None:
        imm.frais_relocation_logement = payload.frais_relocation_logement
    if payload.frais_relocation_chambre is not None:
        imm.frais_relocation_chambre = payload.frais_relocation_chambre
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
    if m >= datetime.now(timezone.utc).date().replace(day=1):
        raise HTTPException(
            status_code=409,
            detail=(
                "Le mois en cours n'est pas encore facturable — attends "
                "le 1er du mois suivant."
            ),
        )
    existing = (
        await db.execute(
            select(FactureGestion)
            .where(
                FactureGestion.immeuble_id == imm.id,
                FactureGestion.mois_couvert == m,
            )
            .limit(1)
        )
    ).scalars().first()
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
    #: Ligne « gestion » : 1er du mois de revenus facturé. Absent pour
    #: les lignes relocation/manuel.
    mois: Optional[date] = None
    #: Ligne « relocation » : dossier de relocation abouti à facturer.
    dossier_id: Optional[int] = None
    #: Ligne « manuel » : description libre du frais.
    libelle: Optional[str] = Field(default=None, max_length=255)
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


def _desc_ligne(d: Dict[str, Any]) -> str:
    """Description QuickBooks d'une ligne du panier selon son type."""
    if d["type_ligne"] == "relocation":
        return f"Frais de relocation — {d['libelle']} — {d['imm'].name}"
    if d["type_ligne"] == "manuel":
        return f"{d['libelle']} — {d['imm'].name}"
    mois_label = f"{MOIS_FR[d['mois'].month - 1]} {d['mois'].year}"
    if d["complement"]:
        return (
            f"Complément — frais de gestion {d['pct']:g} % — loyers "
            f"additionnels de {mois_label} ({d['revenus']:.2f} $) — "
            f"{d['imm'].name}"
        )
    return (
        f"Frais de gestion {d['pct']:g} % — revenus locatifs de "
        f"{mois_label} ({d['revenus']:.2f} $) — {d['imm'].name}"
    )


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
    factures_sommes: Dict[tuple, float] = {}
    for iid, fm, frev in (
        await db.execute(
            select(
                FactureGestion.immeuble_id,
                FactureGestion.mois_couvert,
                func.sum(FactureGestion.revenus),
            )
            .where(FactureGestion.type_ligne == "gestion")
            .group_by(
                FactureGestion.immeuble_id, FactureGestion.mois_couvert
            )
        )
    ).all():
        factures_sommes[(int(iid), fm)] = float(frev or 0.0)
    dossiers_factures = {
        int(did)
        for (did,) in (
            await db.execute(
                select(FactureGestion.relocation_dossier_id).where(
                    FactureGestion.relocation_dossier_id.is_not(None)
                )
            )
        ).all()
    }
    premier_mois_courant = datetime.now(timezone.utc).date().replace(day=1)
    details: List[Dict[str, Any]] = []
    vus: set = set()
    vus_dossiers: set = set()
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

        # ── Ligne RELOCATION : frais fixe au contrat, dossier abouti. ──
        if ligne.dossier_id is not None:
            dossier = await db.get(LocationDossier, ligne.dossier_id)
            if not dossier or dossier.statut != "reloue":
                raise HTTPException(
                    status_code=404,
                    detail="Dossier de relocation introuvable ou pas abouti.",
                )
            logement = await db.get(Logement, dossier.logement_id)
            if not logement or int(logement.immeuble_id) != imm.id:
                raise HTTPException(
                    status_code=422,
                    detail=(
                        "Ce dossier de relocation n'appartient pas à "
                        f"« {imm.name} »."
                    ),
                )
            if (
                dossier.id in dossiers_factures
                or dossier.id in vus_dossiers
            ):
                raise HTTPException(
                    status_code=409,
                    detail=(
                        f"La relocation du {logement.numero} "
                        f"({imm.name}) est déjà facturée."
                    ),
                )
            vus_dossiers.add(dossier.id)
            en_chambres = bool(
                getattr(logement, "location_en_chambres", False)
            )
            unite = ("ch. " if en_chambres else "log. ") + str(
                logement.numero
            )
            quand = dossier.reloue_le
            lib = f"Relocation {unite}"
            if quand:
                lib += (
                    f" · reloué le {quand.day} {MOIS_FR[quand.month - 1]} "
                    f"{quand.year}"
                )
            details.append(
                {
                    "imm": imm,
                    "mois": (quand or premier_mois_courant).replace(day=1),
                    "montant": round(float(ligne.montant), 2),
                    "revenus": 0.0,
                    "complement": False,
                    "type_ligne": "relocation",
                    "dossier_id": dossier.id,
                    "libelle": lib,
                    "pct": 0.0,
                }
            )
            continue

        # ── Ligne MANUELLE : frais libre saisi dans le panier. ──
        if ligne.libelle is not None and ligne.mois is None:
            lib = ligne.libelle.strip()
            if not lib:
                raise HTTPException(
                    status_code=422,
                    detail="Décris le frais manuel (libellé vide).",
                )
            details.append(
                {
                    "imm": imm,
                    "mois": premier_mois_courant,
                    "montant": round(float(ligne.montant), 2),
                    "revenus": 0.0,
                    "complement": False,
                    "type_ligne": "manuel",
                    "dossier_id": None,
                    "libelle": lib,
                    "pct": 0.0,
                }
            )
            continue

        # ── Ligne GESTION : X % des revenus du mois. ──
        if ligne.mois is None:
            raise HTTPException(
                status_code=422,
                detail="Ligne invalide : mois manquant.",
            )
        m = ligne.mois.replace(day=1)
        if m >= premier_mois_courant:
            if m.month == 12:
                prochain = m.replace(year=m.year + 1, month=1)
            else:
                prochain = m.replace(month=m.month + 1)
            raise HTTPException(
                status_code=409,
                detail=(
                    f"« {imm.name} » — {MOIS_FR[m.month - 1]} {m.year} "
                    "est le mois en cours : d'autres loyers peuvent "
                    "encore rentrer. Facturable à partir du 1er "
                    f"{MOIS_FR[prochain.month - 1]}."
                ),
            )
        if (imm.id, m) in vus:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"« {imm.name} » — {MOIS_FR[m.month - 1]} {m.year} "
                    "apparaît deux fois dans le panier."
                ),
            )
        rev_total = round(revenus_tous.get((imm.id, m), 0.0), 2)
        rev_facture = factures_sommes.get((imm.id, m))
        if rev_facture is None:
            revenus_ligne = rev_total
            complement = False
        else:
            # Mois déjà facturé : seul le delta (loyers payés depuis la
            # facture) est facturable → ligne « complément ».
            revenus_ligne = round(rev_total - rev_facture, 2)
            complement = True
            if revenus_ligne <= 0.005:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        f"« {imm.name} » — {MOIS_FR[m.month - 1]} "
                        f"{m.year} est déjà entièrement facturé."
                    ),
                )
        vus.add((imm.id, m))
        details.append(
            {
                "imm": imm,
                "mois": m,
                "montant": round(float(ligne.montant), 2),
                "revenus": revenus_ligne,
                "complement": complement,
                "type_ligne": "gestion",
                "dossier_id": None,
                "libelle": None,
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
                    "Description": _desc_ligne(d),
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
                est_complement=d["complement"],
                type_ligne=d["type_ligne"],
                relocation_dossier_id=d["dossier_id"],
                libelle=d["libelle"],
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
