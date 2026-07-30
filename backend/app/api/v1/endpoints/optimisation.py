"""Endpoints « Projets - Optimisation » (pôle Gestion d'entreprise).

  GET    /api/v1/optimisation/projets                 liste + tuiles
  POST   /api/v1/optimisation/projets                 crée (+ seed locataires)
  GET    /api/v1/optimisation/projets/{id}            détail + réels locatifs
  PATCH  /api/v1/optimisation/projets/{id}
  DELETE /api/v1/optimisation/projets/{id}
  POST   /api/v1/optimisation/projets/{id}/budget-lignes
  PATCH  /api/v1/optimisation/budget-lignes/{lid}
  DELETE /api/v1/optimisation/budget-lignes/{lid}
  GET    /api/v1/optimisation/projets/{id}/qbo-depenses   dépensé réel QBO
  GET    /api/v1/optimisation/qbo-comptes?scope=…         plan comptable
  POST   /api/v1/optimisation/projets/{id}/negos
  POST   /api/v1/optimisation/projets/{id}/importer-locataires
  PATCH  /api/v1/optimisation/negos/{nid}
  DELETE /api/v1/optimisation/negos/{nid}

QuickBooks : LECTURE SEULE (rapports + plan comptable). Les erreurs QBO
ne cassent jamais la page — elles reviennent en champ ``erreur``.
"""
from __future__ import annotations

import json
import logging
from datetime import date
from typing import Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.api.deps import CurrentUser, DBSession
from app.models.entreprise import Entreprise
from app.models.immobilier import (
    Bail,
    BailStatus,
    DepenseImmeuble,
    Immeuble,
    Locataire,
    Logement,
)
from app.models.optimisation import (
    OptimisationBudgetLigne,
    OptimisationNego,
    OptimisationProjet,
)

log = logging.getLogger(__name__)
router = APIRouter(prefix="/optimisation", tags=["optimisation"])

#: « parti » et « depart_prevu » retirés (retours Phil) — la sortie du
#: locataire se lit dans « Entente conclue » + le type d'entente.
_NEGO_STATUTS = (
    "en_place", "a_contacter", "en_discussion", "entente", "reste",
)

_TYPES_ENTENTE = ("cash_for_raise", "cash_for_keys", "renovation", "autre")


# ── Schémas ──────────────────────────────────────────────────────


class BudgetLigneRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    projet_id: int
    nom: str
    budget_montant: float
    qbo_accounts_json: Optional[str]
    qbo_financement_accounts_json: Optional[str] = None
    comptant_disponible: Optional[float] = None
    position: int


class NegoRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    projet_id: int
    locataire_id: Optional[int]
    nom_locataire: str
    logement_label: Optional[str]
    loyer_actuel: Optional[float]
    statut: str
    type_entente: Optional[str]
    entente: Optional[str]
    montant_entente: Optional[float]
    date_cible: Optional[date]
    events_json: Optional[str]
    recherche_json: Optional[str] = None
    position: int


class ProjetListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    entreprise_id: int
    immeuble_id: int
    status: str
    date_debut: Optional[date]
    entreprise_nom: str = ""
    immeuble_nom: str = ""
    budget_total: float = 0.0
    nb_negos: int = 0


class ProjetRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    entreprise_id: int
    immeuble_id: int
    status: str
    date_debut: Optional[date]
    qbo_scope: Optional[str]
    qbo_bank_account_id: Optional[str] = None
    qbo_bank_account_name: Optional[str] = None
    rentabilite_depuis: Optional[date] = None
    objectif_revenus_mensuels: Optional[float]
    objectif_depenses_mensuelles: Optional[float]
    objectif_revenus_annuels: Optional[float] = None
    objectif_depenses_annuelles: Optional[float] = None
    objectifs_json: Optional[str]
    notes: Optional[str]
    entreprise_nom: str = ""
    immeuble_nom: str = ""
    #: Réels tirés de la Gestion locative (baux actifs / dépenses).
    revenus_actuels_mensuels: float = 0.0
    depenses_actuelles_mensuelles: float = 0.0
    nb_logements: int = 0
    #: Revenus mensuels reconstitués depuis les baux (dates de début/fin)
    #: — [{"mois": "2026-01", "montant": 4200.0}], du début du projet à
    #: aujourd'hui (max 24 mois).
    revenus_historique: List[Dict[str, object]] = Field(default_factory=list)
    budget_lignes: List[BudgetLigneRead] = Field(default_factory=list)
    negos: List[NegoRead] = Field(default_factory=list)


class ProjetCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    entreprise_id: int
    immeuble_id: int
    date_debut: Optional[date] = None
    qbo_scope: Optional[str] = Field(default=None, max_length=32)
    #: Retour Phil : on n'importe PLUS les locataires à la création —
    #: ça se fait ensuite depuis la section Négociations (choix à la
    #: pièce). Le drapeau reste pour l'API/MCP.
    importer_locataires: bool = False


class ProjetUpdate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=255)
    status: Optional[str] = Field(default=None, pattern=r"^(actif|termine)$")
    date_debut: Optional[date] = None
    qbo_scope: Optional[str] = Field(default=None, max_length=32)
    qbo_bank_account_id: Optional[str] = Field(default=None, max_length=64)
    qbo_bank_account_name: Optional[str] = Field(default=None, max_length=255)
    rentabilite_depuis: Optional[date] = None
    objectif_revenus_mensuels: Optional[float] = None
    objectif_depenses_mensuelles: Optional[float] = None
    objectif_revenus_annuels: Optional[float] = None
    objectif_depenses_annuelles: Optional[float] = None
    objectifs_json: Optional[str] = Field(default=None, max_length=20_000)
    notes: Optional[str] = None


class BudgetLigneCreate(BaseModel):
    nom: str = Field(..., min_length=1, max_length=255)
    budget_montant: float = 0
    qbo_accounts_json: Optional[str] = Field(default=None, max_length=20_000)


class BudgetLigneUpdate(BaseModel):
    nom: Optional[str] = Field(default=None, max_length=255)
    budget_montant: Optional[float] = None
    qbo_accounts_json: Optional[str] = Field(default=None, max_length=20_000)
    qbo_financement_accounts_json: Optional[str] = Field(
        default=None, max_length=20_000
    )
    comptant_disponible: Optional[float] = None
    position: Optional[int] = None


class NegoCreate(BaseModel):
    nom_locataire: str = Field(..., min_length=1, max_length=255)
    locataire_id: Optional[int] = None
    logement_label: Optional[str] = Field(default=None, max_length=64)
    loyer_actuel: Optional[float] = None


class NegoUpdate(BaseModel):
    statut: Optional[str] = None
    type_entente: Optional[str] = None
    #: Préparation de la négo (JSON : emploi, employeur, réseaux…).
    recherche_json: Optional[str] = Field(default=None, max_length=20_000)
    entente: Optional[str] = None
    montant_entente: Optional[float] = None
    date_cible: Optional[date] = None
    #: Ajoute un événement daté à la timeline (append, jamais d'écrasement).
    add_event: Optional[str] = Field(default=None, max_length=2000)
    add_event_date: Optional[date] = None


# ── Helpers ──────────────────────────────────────────────────────


async def _projet_or_404(db, projet_id: int) -> OptimisationProjet:
    row = (
        await db.execute(
            select(OptimisationProjet).where(
                OptimisationProjet.id == projet_id
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Projet introuvable.")
    return row


def _mois_range(debut: date, fin: date, cap: int = 24) -> List[date]:
    """Premiers du mois de ``debut`` à ``fin`` inclus (bornés aux
    ``cap`` derniers mois)."""
    out: List[date] = []
    cur = date(debut.year, debut.month, 1)
    stop = date(fin.year, fin.month, 1)
    while cur <= stop:
        out.append(cur)
        cur = (
            date(cur.year + 1, 1, 1)
            if cur.month == 12
            else date(cur.year, cur.month + 1, 1)
        )
    return out[-cap:]


async def _revenus_historique(
    db, immeuble_id: int, debut: Optional[date]
) -> List[Dict[str, object]]:
    """Revenus mensuels reconstitués : pour chaque mois depuis le début
    du projet, somme des loyers des baux couvrant ce mois (d'après leurs
    dates — si tous les loyers rentrent)."""
    today = date.today()
    start = debut or today
    if start > today:
        return []
    baux = (
        await db.execute(
            select(Bail.loyer_mensuel, Bail.date_debut, Bail.date_fin)
            .join(Logement, Logement.id == Bail.logement_id)
            .where(Logement.immeuble_id == immeuble_id)
        )
    ).all()
    out: List[Dict[str, object]] = []
    for premier in _mois_range(start, today):
        fin_mois = (
            date(premier.year + 1, 1, 1)
            if premier.month == 12
            else date(premier.year, premier.month + 1, 1)
        )
        total = 0.0
        for loyer, d1, d2 in baux:
            if d1 and d1 >= fin_mois:
                continue  # bail pas encore commencé ce mois-là
            if d2 and d2 < premier:
                continue  # bail déjà terminé
            total += float(loyer or 0)
        out.append(
            {"mois": premier.strftime("%Y-%m"), "montant": round(total, 2)}
        )
    return out


async def _reels_locatifs(db, immeuble_id: int) -> tuple[float, float]:
    """(revenus mensuels des baux ACTIFS, dépenses mensuelles courantes
    de l'immeuble). Dépenses = mensuelles + annuelles/12 — le rythme de
    croisière, sans les ponctuelles."""
    baux = (
        await db.execute(
            select(Bail.loyer_mensuel)
            .join(Logement, Logement.id == Bail.logement_id)
            .where(
                Logement.immeuble_id == immeuble_id,
                Bail.status == BailStatus.ACTIF.value,
            )
        )
    ).scalars().all()
    revenus = float(sum(float(x or 0) for x in baux))

    deps = (
        await db.execute(
            select(DepenseImmeuble.montant, DepenseImmeuble.frequence).where(
                DepenseImmeuble.immeuble_id == immeuble_id
            )
        )
    ).all()
    depenses = 0.0
    for montant, freq in deps:
        m = float(montant or 0)
        if freq == "mensuel":
            depenses += m
        elif freq == "annuel":
            depenses += m / 12.0
    return revenus, round(depenses, 2)


async def _baux_actifs_immeuble(db, immeuble_id: int):
    """[(locataire, bail, logement)] des baux actifs de l'immeuble."""
    return (
        await db.execute(
            select(Locataire, Bail, Logement)
            .join(Bail, Bail.locataire_id == Locataire.id)
            .join(Logement, Logement.id == Bail.logement_id)
            .where(
                Logement.immeuble_id == immeuble_id,
                Bail.status == BailStatus.ACTIF.value,
            )
        )
    ).all()


async def _seed_negos(
    db,
    projet: OptimisationProjet,
    locataire_ids: Optional[List[int]] = None,
) -> int:
    """Crée une négo par locataire actif de l'immeuble qui n'en a pas
    déjà une sur ce projet. ``locataire_ids`` restreint l'import à une
    sélection (modal « Importer »). Retourne le nombre créé."""
    existants = {
        x
        for x in (
            await db.execute(
                select(OptimisationNego.locataire_id).where(
                    OptimisationNego.projet_id == projet.id
                )
            )
        ).scalars().all()
        if x is not None
    }
    rows = await _baux_actifs_immeuble(db, projet.immeuble_id)
    pos = len(existants)
    created = 0
    for loc, bail, lg in rows:
        if loc.id in existants:
            continue
        if locataire_ids is not None and loc.id not in locataire_ids:
            continue
        existants.add(loc.id)
        db.add(
            OptimisationNego(
                projet_id=projet.id,
                locataire_id=loc.id,
                nom_locataire=loc.full_name or f"Locataire #{loc.id}",
                logement_label=lg.numero,
                loyer_actuel=float(bail.loyer_mensuel or 0) or None,
                position=pos,
            )
        )
        pos += 1
        created += 1
    return created


async def _projet_read(db, p: OptimisationProjet) -> ProjetRead:
    ent = (
        await db.execute(select(Entreprise).where(Entreprise.id == p.entreprise_id))
    ).scalar_one_or_none()
    imm = (
        await db.execute(select(Immeuble).where(Immeuble.id == p.immeuble_id))
    ).scalar_one_or_none()
    lignes = (
        await db.execute(
            select(OptimisationBudgetLigne)
            .where(OptimisationBudgetLigne.projet_id == p.id)
            .order_by(
                OptimisationBudgetLigne.position.asc(),
                OptimisationBudgetLigne.id.asc(),
            )
        )
    ).scalars().all()
    negos = (
        await db.execute(
            select(OptimisationNego)
            .where(OptimisationNego.projet_id == p.id)
            .order_by(OptimisationNego.position.asc(), OptimisationNego.id.asc())
        )
    ).scalars().all()
    revenus, depenses = await _reels_locatifs(db, p.immeuble_id)
    nb_logements = len(
        (
            await db.execute(
                select(Logement.id).where(
                    Logement.immeuble_id == p.immeuble_id
                )
            )
        ).scalars().all()
    )
    historique = await _revenus_historique(db, p.immeuble_id, p.date_debut)
    out = ProjetRead.model_validate(p)
    out.entreprise_nom = ent.name if ent else ""
    out.immeuble_nom = (imm.name or imm.address) if imm else ""
    out.revenus_actuels_mensuels = revenus
    out.depenses_actuelles_mensuelles = depenses
    out.nb_logements = nb_logements
    out.revenus_historique = historique
    out.budget_lignes = [BudgetLigneRead.model_validate(x) for x in lignes]
    out.negos = [NegoRead.model_validate(x) for x in negos]
    return out


# ── Projets ──────────────────────────────────────────────────────


@router.get("/projets", response_model=List[ProjetListItem])
async def list_projets(db: DBSession, _: CurrentUser) -> List[ProjetListItem]:
    rows = (
        await db.execute(
            select(OptimisationProjet).order_by(
                OptimisationProjet.status.asc(),  # actifs avant terminés
                OptimisationProjet.id.asc(),
            )
        )
    ).scalars().all()
    ents = {
        e.id: e.name
        for e in (await db.execute(select(Entreprise))).scalars().all()
    }
    imms = {
        i.id: (i.name or i.address)
        for i in (await db.execute(select(Immeuble))).scalars().all()
    }
    out: List[ProjetListItem] = []
    for p in rows:
        item = ProjetListItem.model_validate(p)
        item.entreprise_nom = ents.get(p.entreprise_id, "")
        item.immeuble_nom = imms.get(p.immeuble_id, "")
        montants = (
            await db.execute(
                select(OptimisationBudgetLigne.budget_montant).where(
                    OptimisationBudgetLigne.projet_id == p.id
                )
            )
        ).scalars().all()
        item.budget_total = float(sum(float(x or 0) for x in montants))
        item.nb_negos = len(
            (
                await db.execute(
                    select(OptimisationNego.id).where(
                        OptimisationNego.projet_id == p.id
                    )
                )
            ).scalars().all()
        )
        out.append(item)
    return out


@router.post(
    "/projets", response_model=ProjetRead, status_code=status.HTTP_201_CREATED
)
async def create_projet(
    data: ProjetCreate, db: DBSession, user: CurrentUser
) -> ProjetRead:
    ent = (
        await db.execute(
            select(Entreprise).where(Entreprise.id == data.entreprise_id)
        )
    ).scalar_one_or_none()
    if ent is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Entreprise introuvable.")
    imm = (
        await db.execute(
            select(Immeuble).where(Immeuble.id == data.immeuble_id)
        )
    ).scalar_one_or_none()
    if imm is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Immeuble introuvable.")

    p = OptimisationProjet(
        name=data.name.strip(),
        entreprise_id=data.entreprise_id,
        immeuble_id=data.immeuble_id,
        date_debut=data.date_debut or date.today(),
        qbo_scope=data.qbo_scope,
        created_by_user_id=user.id,
    )
    db.add(p)
    await db.flush()
    if data.importer_locataires:
        await _seed_negos(db, p)
    await db.commit()
    await db.refresh(p)
    return await _projet_read(db, p)


@router.get("/projets/{projet_id}", response_model=ProjetRead)
async def get_projet(projet_id: int, db: DBSession, _: CurrentUser) -> ProjetRead:
    p = await _projet_or_404(db, projet_id)
    return await _projet_read(db, p)


@router.patch("/projets/{projet_id}", response_model=ProjetRead)
async def update_projet(
    projet_id: int, data: ProjetUpdate, db: DBSession, _: CurrentUser
) -> ProjetRead:
    p = await _projet_or_404(db, projet_id)
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(p, k, v)
    await db.commit()
    await db.refresh(p)
    return await _projet_read(db, p)


@router.delete("/projets/{projet_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_projet(projet_id: int, db: DBSession, _: CurrentUser) -> None:
    p = await _projet_or_404(db, projet_id)
    await db.delete(p)
    await db.commit()


# ── Budget ───────────────────────────────────────────────────────


@router.post(
    "/projets/{projet_id}/budget-lignes",
    response_model=BudgetLigneRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_budget_ligne(
    projet_id: int, data: BudgetLigneCreate, db: DBSession, _: CurrentUser
) -> BudgetLigneRead:
    await _projet_or_404(db, projet_id)
    nb = len(
        (
            await db.execute(
                select(OptimisationBudgetLigne.id).where(
                    OptimisationBudgetLigne.projet_id == projet_id
                )
            )
        ).scalars().all()
    )
    ligne = OptimisationBudgetLigne(
        projet_id=projet_id,
        nom=data.nom.strip(),
        budget_montant=data.budget_montant,
        qbo_accounts_json=data.qbo_accounts_json,
        position=nb,
    )
    db.add(ligne)
    await db.commit()
    await db.refresh(ligne)
    return BudgetLigneRead.model_validate(ligne)


@router.patch("/budget-lignes/{ligne_id}", response_model=BudgetLigneRead)
async def update_budget_ligne(
    ligne_id: int, data: BudgetLigneUpdate, db: DBSession, _: CurrentUser
) -> BudgetLigneRead:
    ligne = (
        await db.execute(
            select(OptimisationBudgetLigne).where(
                OptimisationBudgetLigne.id == ligne_id
            )
        )
    ).scalar_one_or_none()
    if ligne is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Ligne introuvable.")
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(ligne, k, v)
    await db.commit()
    await db.refresh(ligne)
    return BudgetLigneRead.model_validate(ligne)


@router.delete(
    "/budget-lignes/{ligne_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_budget_ligne(
    ligne_id: int, db: DBSession, _: CurrentUser
) -> None:
    ligne = (
        await db.execute(
            select(OptimisationBudgetLigne).where(
                OptimisationBudgetLigne.id == ligne_id
            )
        )
    ).scalar_one_or_none()
    if ligne is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Ligne introuvable.")
    await db.delete(ligne)
    await db.commit()


# ── QuickBooks (lecture seule) ───────────────────────────────────


class QboDepensesOut(BaseModel):
    par_ligne: Dict[int, float] = Field(default_factory=dict)
    #: Financement encaissé par enveloppe (comptes d'entrée d'argent).
    financement_par_ligne: Dict[int, float] = Field(default_factory=dict)
    #: Solde courant du compte bancaire du projet (None si non choisi).
    solde_bancaire: Optional[float] = None
    #: Rentabilité de la compagnie depuis ``rentabilite_depuis`` (ou
    #: depuis la création) : {"revenus", "depenses", "net"}.
    rentabilite: Optional[Dict[str, float]] = None
    erreur: Optional[str] = None


@router.get(
    "/projets/{projet_id}/qbo-depenses", response_model=QboDepensesOut
)
async def qbo_depenses(
    projet_id: int, db: DBSession, _: CurrentUser
) -> QboDepensesOut:
    """Dépensé réel par ligne de budget (somme des comptes QBO mappés,
    du début du projet à aujourd'hui). Ne casse jamais : les problèmes
    QBO reviennent dans ``erreur``."""
    from app.services.qbo_optimisation import (
        depenses_par_compte,
        rentabilite as _rentabilite,
        solde_compte,
    )

    p = await _projet_or_404(db, projet_id)
    if not p.qbo_scope:
        return QboDepensesOut(
            erreur="Aucune connexion QuickBooks choisie pour ce projet "
            "(réglages du projet)."
        )
    lignes = (
        await db.execute(
            select(OptimisationBudgetLigne).where(
                OptimisationBudgetLigne.projet_id == projet_id
            )
        )
    ).scalars().all()
    try:
        totaux = await depenses_par_compte(
            p.qbo_scope,
            p.date_debut.isoformat() if p.date_debut else None,
            date.today().isoformat(),
        )
    except Exception as exc:  # noqa: BLE001 — message propre à l'UI
        log.info("qbo-depenses projet #%s: %s", projet_id, exc)
        return QboDepensesOut(erreur=str(exc))

    def _somme(raw: Optional[str]) -> float:
        try:
            comptes = json.loads(raw or "[]")
        except Exception:  # noqa: BLE001
            return 0.0
        return sum(
            float(totaux.get(str(c.get("id")), 0.0)) for c in comptes
        )

    par_ligne: Dict[int, float] = {}
    financement: Dict[int, float] = {}
    for ligne in lignes:
        par_ligne[ligne.id] = round(_somme(ligne.qbo_accounts_json), 2)
        # Les entrées d'argent sortent tantôt en crédit (négatif) tantôt
        # en positif selon le type de compte → on garde la magnitude.
        financement[ligne.id] = round(
            abs(_somme(ligne.qbo_financement_accounts_json)), 2
        )

    solde = None
    if p.qbo_bank_account_id:
        try:
            solde = await solde_compte(p.qbo_scope, p.qbo_bank_account_id)
        except Exception as exc:  # noqa: BLE001 — jamais bloquant
            log.info("solde bancaire projet #%s: %s", projet_id, exc)

    # Rentabilité de la compagnie : depuis la date choisie, sinon depuis
    # la création du fichier comptable (QBO accepte une date très basse).
    rent = None
    try:
        rent = await _rentabilite(
            p.qbo_scope,
            (p.rentabilite_depuis or date(2000, 1, 1)).isoformat(),
            date.today().isoformat(),
        )
    except Exception as exc:  # noqa: BLE001 — jamais bloquant
        log.info("rentabilité projet #%s: %s", projet_id, exc)

    return QboDepensesOut(
        par_ligne=par_ligne,
        financement_par_ligne=financement,
        solde_bancaire=solde,
        rentabilite=rent,
    )


class QboComptesOut(BaseModel):
    comptes: List[Dict[str, str]] = Field(default_factory=list)
    erreur: Optional[str] = None


@router.get("/qbo-comptes", response_model=QboComptesOut)
async def qbo_comptes(
    _: CurrentUser,
    scope: str = Query(...),
    kind: str = Query(
        default="depense", pattern=r"^(depense|financement|banque)$"
    ),
) -> QboComptesOut:
    """Plan comptable de la connexion ``scope``, par famille :
    ``depense`` (enveloppes), ``financement`` (entrées d'argent) ou
    ``banque`` (compte dont on affiche le solde)."""
    from app.services.qbo_optimisation import lister_comptes_depense

    try:
        comptes = await lister_comptes_depense(scope, kind)
    except Exception as exc:  # noqa: BLE001
        return QboComptesOut(erreur=str(exc))
    return QboComptesOut(comptes=comptes)


# ── Négociations ─────────────────────────────────────────────────


@router.post(
    "/projets/{projet_id}/negos",
    response_model=NegoRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_nego(
    projet_id: int, data: NegoCreate, db: DBSession, _: CurrentUser
) -> NegoRead:
    await _projet_or_404(db, projet_id)
    nb = len(
        (
            await db.execute(
                select(OptimisationNego.id).where(
                    OptimisationNego.projet_id == projet_id
                )
            )
        ).scalars().all()
    )
    n = OptimisationNego(
        projet_id=projet_id,
        locataire_id=data.locataire_id,
        nom_locataire=data.nom_locataire.strip(),
        logement_label=data.logement_label,
        loyer_actuel=data.loyer_actuel,
        position=nb,
    )
    db.add(n)
    await db.commit()
    await db.refresh(n)
    return NegoRead.model_validate(n)


class ImporterLocatairesIn(BaseModel):
    #: None = tous les locataires actifs ; sinon la sélection du modal.
    locataire_ids: Optional[List[int]] = None


@router.get("/projets/{projet_id}/locataires-disponibles")
async def locataires_disponibles(
    projet_id: int, db: DBSession, _: CurrentUser
) -> List[dict]:
    """Locataires à bail actif de l'immeuble, avec indication de ceux
    déjà suivis — alimente le modal « Importer des locataires »."""
    p = await _projet_or_404(db, projet_id)
    deja = {
        x
        for x in (
            await db.execute(
                select(OptimisationNego.locataire_id).where(
                    OptimisationNego.projet_id == p.id
                )
            )
        ).scalars().all()
        if x is not None
    }
    rows = await _baux_actifs_immeuble(db, p.immeuble_id)
    out = []
    vus: set[int] = set()
    for loc, bail, lg in rows:
        if loc.id in vus:
            continue
        vus.add(loc.id)
        out.append(
            {
                "locataire_id": loc.id,
                "nom": loc.full_name or f"Locataire #{loc.id}",
                "logement": lg.numero,
                "loyer": float(bail.loyer_mensuel or 0) or None,
                "deja_suivi": loc.id in deja,
            }
        )
    out.sort(key=lambda x: (x["logement"] or "", x["nom"]))
    return out


@router.post("/projets/{projet_id}/importer-locataires")
async def importer_locataires(
    projet_id: int,
    db: DBSession,
    _: CurrentUser,
    data: Optional[ImporterLocatairesIn] = None,
) -> dict:
    """Importe les locataires choisis (ou tous) — n'ajoute que les
    manquants, ne touche pas aux négos existantes."""
    p = await _projet_or_404(db, projet_id)
    created = await _seed_negos(
        db, p, data.locataire_ids if data else None
    )
    await db.commit()
    return {"created": created}


@router.patch("/negos/{nego_id}", response_model=NegoRead)
async def update_nego(
    nego_id: int, data: NegoUpdate, db: DBSession, _: CurrentUser
) -> NegoRead:
    n = (
        await db.execute(
            select(OptimisationNego).where(OptimisationNego.id == nego_id)
        )
    ).scalar_one_or_none()
    if n is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Négo introuvable.")
    payload = data.model_dump(exclude_unset=True)
    ev_texte = payload.pop("add_event", None)
    ev_date = payload.pop("add_event_date", None)
    if "statut" in payload and payload["statut"] not in _NEGO_STATUTS:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "Statut invalide."
        )
    if payload.get("type_entente") and payload["type_entente"] not in _TYPES_ENTENTE:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "Type d'entente invalide."
        )
    for k, v in payload.items():
        setattr(n, k, v)
    if ev_texte and ev_texte.strip():
        try:
            events = json.loads(n.events_json or "[]")
            if not isinstance(events, list):
                events = []
        except Exception:  # noqa: BLE001
            events = []
        events.append(
            {
                "date": (ev_date or date.today()).isoformat(),
                "texte": ev_texte.strip(),
            }
        )
        n.events_json = json.dumps(events)[:50_000]
    await db.commit()
    await db.refresh(n)
    return NegoRead.model_validate(n)


@router.delete("/negos/{nego_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_nego(nego_id: int, db: DBSession, _: CurrentUser) -> None:
    n = (
        await db.execute(
            select(OptimisationNego).where(OptimisationNego.id == nego_id)
        )
    ).scalar_one_or_none()
    if n is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Négo introuvable.")
    await db.delete(n)
    await db.commit()
