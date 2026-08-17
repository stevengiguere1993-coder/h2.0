"""Smoke — Validation bancaire des loyers via QuickBooks (2026-08-14).

2e validation SANS IA, QuickBooks en LECTURE SEULE : l'adjointe publie
les encaissements au compte « Loyer à remettre - {immeuble} » ; Kratos
lit, rapproche de façon déterministe et pose ✓✓ / ⚠ dans le locatif.

Vérifie avec un faux client QBO (aucun réseau) :
1. découverte des comptes + immeuble AUTO-SUGGÉRÉ par similarité ;
2. synchro IDEMPOTENTE (même écriture rejouée = une seule ligne) ;
3. rapprochement : un seul candidat plausible → auto ; deux baux au
   même loyer → « ambigu » SANS pronostic ;
4. confirmer un ambigu apprend l'ALIAS payeur → le mois suivant, la
   même provenance se rapproche toute seule (et la confirmation
   manuelle n'est jamais écrasée par la synchro) ;
5. feature INACTIVE → l'état ne sort RIEN (zéro bruit) ;
6. feature active → ✓✓ « valide » quand paiement marqué + transaction
   rapprochée ; ⚠ « sans_trace » quand marqué payé depuis > N jours
   sans trace bancaire ; encart « encaissés non marqués » rempli.

v2 (retours Phil 2026-08-14) :
7. compte relié à PLUSIEURS immeubles → candidats = UNION des baux ;
8. compte « tous les immeubles » (fiducie) + payeur extrait du mémo
   Interac réel « Virement Interac de /X / » qui départage ;
9. classification par TYPE (jamais par signe) : dépôt en négatif
   (représentation d'un compte de passif) quand même importé ; virement
   de remise sortant ignoré proprement ; type inconnu rapporté — avec le
   RAPPORT de synchro détaillé par compte ;
10. suggestion MULTI-immeubles (« 9085 Millen & 710 Legendre » suggère
    les deux) + nom fiducie → suggestion « tous » ;
11. paiement MULTI-MOIS : 2 mois de retard à 650 $ réglés par un
    virement de 1 300 $ → rapproché aux deux mois (✓✓ sur chacun une
    fois marqués payés) ; le même montant avec DEUX baux candidats →
    ambigu, zéro pronostic ; le fil bancaire liste tout.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List

from sqlalchemy import delete, select

from app.models.immobilier import (
    Bail,
    BailStatus,
    Immeuble,
    Locataire,
    Logement,
    PaiementLoyer,
)
from app.models.qbo_loyers import (
    QboAliasPayeur,
    QboCompteImmeuble,
    QboCompteLoyer,
    QboTransactionLoyer,
)
from app.services.qbo_validation_loyers import (
    VALIDATION_KEY,
    _mois_suiv,
    _parse_montant,
    confirmer_transaction,
    decouvrir_comptes,
    etat_validation,
    lister_transactions,
    parse_general_ledger,
    synchroniser_transactions,
)

from tests.smoke.conftest import TestSessionLocal

AUJOURDHUI = datetime.now(timezone.utc).date()
MOIS_COURANT = AUJOURDHUI.replace(day=1)


# ── Faux client QuickBooks (lecture seule) ──────────────────────────────


class FakeQbo:
    """Simule le strict nécessaire : query (plan comptable) + report
    (GeneralLedger filtré par compte)."""

    scope = "immobilier"
    realm_id = "realm-test"

    def __init__(
        self,
        accounts: List[Dict[str, Any]] | None = None,
        gl_par_compte: Dict[str, List[Dict[str, Any]]] | None = None,
    ) -> None:
        self.accounts = accounts or []
        #: {qbo_account_id: [écritures]} — cf. ``_gl_report``.
        self.gl_par_compte = gl_par_compte or {}
        self.reports_demandes: List[str] = []

    async def query(self, sql: str) -> List[Dict[str, Any]]:
        assert "Account" in sql
        return list(self.accounts)

    async def report(self, name: str, **params: str) -> Dict[str, Any]:
        assert name == "GeneralLedger"
        compte = str(params.get("account") or "")
        self.reports_demandes.append(compte)
        return _gl_report(self.gl_par_compte.get(compte, []))


def _gl_report(ecritures: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Construit un rapport GeneralLedger minimal : une section (le
    compte) avec une ligne Data par écriture."""
    lignes = [
        {
            "type": "Data",
            "ColData": [
                {"value": e["date"]},
                {"value": e.get("type", "Deposit"), "id": e["id"]},
                {"value": e.get("doc", "")},
                {"value": e.get("nom", "")},
                {"value": e.get("memo", "")},
                {"value": str(e["montant"])},
            ],
        }
        for e in ecritures
    ]
    return {
        "Columns": {
            "Column": [
                {"ColTitle": "Date", "ColType": "tx_date"},
                {"ColTitle": "Type de transaction", "ColType": "txn_type"},
                {"ColTitle": "N°", "ColType": "doc_num"},
                {"ColTitle": "Nom", "ColType": "name"},
                {"ColTitle": "Note", "ColType": "memo"},
                {"ColTitle": "Montant", "ColType": "subt_nat_amount"},
            ]
        },
        "Rows": {
            "Row": [
                {
                    "type": "Section",
                    "Header": {"ColData": [{"value": "Loyer à remettre"}]},
                    "Rows": {"Row": lignes},
                    "Summary": {"ColData": [{"value": "Total"}]},
                }
            ]
        },
    }


# ── Helpers seed / purge ────────────────────────────────────────────────


def _purge(run):
    async def _do():
        async with TestSessionLocal() as s:
            await s.execute(delete(QboTransactionLoyer))
            await s.execute(delete(QboAliasPayeur))
            await s.execute(delete(QboCompteImmeuble))
            await s.execute(delete(QboCompteLoyer))
            await s.commit()

    run(_do())


def _set_config(run, *, active: bool, jours: int = 5):
    async def _do():
        async with TestSessionLocal() as s:
            from app.services.automation_state import set_automation_config

            await set_automation_config(
                s, VALIDATION_KEY, {"active": active, "alerte_jours": jours}
            )
            await s.commit()

    run(_do())


def _seed_immeuble(
    run,
    *,
    name: str,
    address: str,
    baux: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Immeuble + un logement/locataire/bail par entrée de ``baux``
    ({"loyer": float, "nom": str}). Retourne les ids."""

    async def _do() -> Dict[str, Any]:
        async with TestSessionLocal() as s:
            imm = Immeuble(
                name=name,
                address=address,
                city="Montréal",
                is_active=True,
                gestion_externe=False,
            )
            s.add(imm)
            await s.flush()
            out: Dict[str, Any] = {"immeuble_id": imm.id, "baux": []}
            for i, b in enumerate(baux, start=1):
                lg = Logement(immeuble_id=imm.id, numero=str(100 + i))
                s.add(lg)
                await s.flush()
                loc = Locataire(full_name=b["nom"])
                s.add(loc)
                await s.flush()
                bail = Bail(
                    logement_id=lg.id,
                    locataire_id=loc.id,
                    date_debut=AUJOURDHUI - timedelta(days=400),
                    date_fin=AUJOURDHUI + timedelta(days=330),
                    loyer_mensuel=b["loyer"],
                    status=BailStatus.ACTIF.value,
                )
                s.add(bail)
                await s.flush()
                out["baux"].append(
                    {
                        "bail_id": bail.id,
                        "logement_id": lg.id,
                        "locataire_id": loc.id,
                        "loyer": b["loyer"],
                    }
                )
            await s.commit()
            return out

    return run(_do())


def _map_compte(
    run,
    qbo_account_id: str,
    nom: str,
    immeuble_ids,
    *,
    tous: bool = False,
) -> int:
    """Compte découvert + confirmé (comme le ferait Paramètres) — relié
    à UN, PLUSIEURS immeubles (liens N-N) ou à TOUS (fiducie)."""
    if isinstance(immeuble_ids, int):
        immeuble_ids = [immeuble_ids]

    async def _do() -> int:
        async with TestSessionLocal() as s:
            c = QboCompteLoyer(
                qbo_account_id=qbo_account_id,
                qbo_account_name=nom,
                tous_les_immeubles=tous,
                actif=True,
                created_at=datetime.now(timezone.utc),
            )
            s.add(c)
            await s.flush()
            for iid in immeuble_ids or []:
                s.add(
                    QboCompteImmeuble(
                        compte_id=c.id,
                        immeuble_id=iid,
                        created_at=datetime.now(timezone.utc),
                    )
                )
            await s.commit()
            return c.id

    return run(_do())


def _sync(run, qbo: FakeQbo) -> Dict[str, int]:
    async def _do():
        async with TestSessionLocal() as s:
            stats = await synchroniser_transactions(s, qbo)
            await s.commit()
            return stats

    return run(_do())


def _txns(run) -> list:
    async def _do():
        async with TestSessionLocal() as s:
            return (
                (
                    await s.execute(
                        select(QboTransactionLoyer).order_by(
                            QboTransactionLoyer.date_txn
                        )
                    )
                ).scalars().all()
            )

    return run(_do())


def _etat(run, mois: date) -> Dict[str, Any]:
    async def _do():
        async with TestSessionLocal() as s:
            return await etat_validation(s, mois)

    return run(_do())


def _marquer_paye(
    run, bail_id: int, mois: date, montant: float, paye_le: date
) -> None:
    async def _do():
        async with TestSessionLocal() as s:
            p = PaiementLoyer(
                bail_id=bail_id,
                mois_couvert=mois,
                montant=montant,
                paye_le=paye_le,
            )
            p.created_at = datetime.now(timezone.utc)
            s.add(p)
            await s.commit()

    run(_do())


# ── 1) Découverte + auto-suggestion du mapping ─────────────────────────


def test_decouverte_comptes_et_suggestion_immeuble(run, db_setup):
    _purge(run)
    # Adresse UNIQUE à ce test (le n° civique 8900 est déjà semé par
    # d'autres smoke tests — deux immeubles ex æquo = pas de suggestion).
    seed = _seed_immeuble(
        run,
        name="7734, Rue Saint-Vallier, Montréal",
        address="7734, Rue Saint-Vallier",
        baux=[{"loyer": 800.0, "nom": "Jean Dupont"}],
    )
    autre = _seed_immeuble(
        run,
        name="123, Rue Ontario Est",
        address="123, Rue Ontario Est",
        baux=[{"loyer": 950.0, "nom": "Marie Roy"}],
    )
    qbo = FakeQbo(
        accounts=[
            {"Id": "45", "Name": "Loyer à remettre - 7734 St-Vallier"},
            {"Id": "46", "Name": "Réparations et entretien"},
            {"Id": "47", "Name": "Revenus de loyers"},
        ]
    )

    async def _do():
        async with TestSessionLocal() as s:
            comptes = await decouvrir_comptes(s, qbo)
            await s.commit()
            return comptes

    comptes = run(_do())
    # Seul le compte « Loyer à remettre - … » est retenu (insensible
    # casse/accents), et l'immeuble suggéré est le bon (pas Ontario).
    assert len(comptes) == 1
    c = comptes[0]
    assert c.qbo_account_id == "45"
    assert c.immeuble_id is None  # jamais appliqué sans confirmation
    assert c.suggestion_immeuble_id == seed["immeuble_id"]
    assert c.suggestion_immeuble_id != autre["immeuble_id"]


# ── 2) Synchro idempotente ─────────────────────────────────────────────


def test_synchro_idempotente_par_txn_id(run, db_setup):
    _purge(run)
    seed = _seed_immeuble(
        run,
        name="45, Avenue du Parc",
        address="45, Avenue du Parc",
        baux=[{"loyer": 700.0, "nom": "Luc Talbot"}],
    )
    _map_compte(run, "60", "Loyer à remettre - 45 du Parc",
                seed["immeuble_id"])
    ecriture = {
        "date": MOIS_COURANT.isoformat(),
        "id": "D-1001",
        "type": "Deposit",
        "nom": "Luc Talbot",
        "memo": "Virement Interac",
        "montant": 700.0,
    }
    qbo = FakeQbo(gl_par_compte={"60": [ecriture]})

    stats1 = _sync(run, qbo)
    assert stats1["importees"] == 1
    stats2 = _sync(run, qbo)  # fenêtre glissante rejouée
    assert stats2["importees"] == 0
    rows = _txns(run)
    assert len(rows) == 1  # même qbo_txn_id deux fois = UNE ligne
    assert rows[0].qbo_txn_id == "D-1001"
    assert float(rows[0].montant) == 700.0


# ── 3) Rapprochement : unique → auto ; deux baux au même loyer → ambigu ─


def test_rapprochement_unique_auto_et_ambigu_sans_pronostic(run, db_setup):
    _purge(run)
    seed = _seed_immeuble(
        run,
        name="200, Rue Beaubien",
        address="200, Rue Beaubien",
        baux=[
            {"loyer": 825.0, "nom": "Jean Dupont"},
            {"loyer": 825.0, "nom": "Marie Roy"},
            {"loyer": 1240.0, "nom": "Paul Girard"},
        ],
    )
    _map_compte(run, "70", "Loyer à remettre - 200 Beaubien",
                seed["immeuble_id"])
    qbo = FakeQbo(
        gl_par_compte={
            "70": [
                # 1240 $ : un SEUL bail plausible → rapproché auto.
                {
                    "date": MOIS_COURANT.isoformat(),
                    "id": "D-1",
                    "nom": "",
                    "memo": "Dépôt guichet",
                    "montant": 1240.0,
                },
                # 825 $, payeur inconnu : DEUX baux plausibles → ambigu,
                # aucun pronostic.
                {
                    "date": MOIS_COURANT.isoformat(),
                    "id": "D-2",
                    "nom": "",
                    "memo": "Transfert entrant",
                    "montant": 825.0,
                },
                # 825 $ mais le payeur nomme Marie Roy → départage.
                {
                    "date": MOIS_COURANT.isoformat(),
                    "id": "D-3",
                    "nom": "Marie Roy",
                    "memo": "",
                    "montant": 825.0,
                },
            ]
        }
    )
    _sync(run, qbo)
    rows = {t.qbo_txn_id: t for t in _txns(run)}

    girard = next(
        b for b in seed["baux"] if b["loyer"] == 1240.0
    )
    assert rows["D-1"].statut == "rapproche"
    assert rows["D-1"].bail_id == girard["bail_id"]
    assert rows["D-1"].mois_couvert == MOIS_COURANT
    assert rows["D-1"].rapproche_par == "auto"

    assert rows["D-2"].statut == "ambigu"
    assert rows["D-2"].bail_id is None  # pas de pronostic
    assert rows["D-2"].mois_couvert is None

    roy = seed["baux"][1]
    assert rows["D-3"].statut == "rapproche"
    assert rows["D-3"].bail_id == roy["bail_id"]


# ── 4) Confirmer un ambigu apprend l'alias → auto le mois suivant ──────


def test_confirmation_apprend_alias_et_rapproche_mois_suivant(run, db_setup):
    _purge(run)
    seed = _seed_immeuble(
        run,
        name="310, Rue Masson",
        address="310, Rue Masson",
        baux=[
            {"loyer": 900.0, "nom": "Jean Dupont"},
            {"loyer": 900.0, "nom": "Marie Roy"},
        ],
    )
    _map_compte(run, "80", "Loyer à remettre - 310 Masson",
                seed["immeuble_id"])
    mois_prec = (MOIS_COURANT - timedelta(days=1)).replace(day=1)
    provenance = {"nom": "CIE 9876 QC INC", "memo": "Virement no 4411"}
    qbo = FakeQbo(
        gl_par_compte={
            "80": [
                {"date": mois_prec.isoformat(), "id": "D-10",
                 "montant": 900.0, **provenance},
            ]
        }
    )
    _sync(run, qbo)
    txn = _txns(run)[0]
    assert txn.statut == "ambigu"  # deux baux à 900 $, payeur inconnu

    # Un humain confirme : c'est le bail de Marie Roy.
    roy = seed["baux"][1]

    async def _confirmer():
        async with TestSessionLocal() as s:
            t = await s.get(QboTransactionLoyer, txn.id)
            await confirmer_transaction(s, t, roy["bail_id"])
            await s.commit()

    run(_confirmer())

    # L'alias est appris (texte normalisé, sans les nos de référence).
    async def _aliases():
        async with TestSessionLocal() as s:
            return (
                (await s.execute(select(QboAliasPayeur))).scalars().all()
            )

    aliases = run(_aliases())
    assert len(aliases) == 1
    assert aliases[0].bail_id == roy["bail_id"]
    assert "cie" in aliases[0].texte_normalise
    assert "4411" not in aliases[0].texte_normalise  # chiffres retirés

    # Mois suivant : MÊME provenance (autre no de virement) → la synchro
    # rejoue la fenêtre (la confirmation manuelle n'est pas écrasée) et
    # rapproche la nouvelle écriture TOUTE SEULE.
    qbo.gl_par_compte["80"].append(
        {"date": MOIS_COURANT.isoformat(), "id": "D-11",
         "montant": 900.0, "nom": "CIE 9876 QC INC",
         "memo": "Virement no 5522"}
    )
    _sync(run, qbo)
    rows = {t.qbo_txn_id: t for t in _txns(run)}
    assert rows["D-10"].statut == "rapproche"
    assert rows["D-10"].rapproche_par == "manuel"  # jamais écrasé
    assert rows["D-10"].bail_id == roy["bail_id"]
    assert rows["D-11"].statut == "rapproche"
    assert rows["D-11"].rapproche_par == "auto"
    assert rows["D-11"].bail_id == roy["bail_id"]
    assert rows["D-11"].mois_couvert == MOIS_COURANT


# ── 5) Feature inactive → zéro bruit ───────────────────────────────────


def test_etat_vide_quand_feature_inactive(run, db_setup):
    _purge(run)
    _set_config(run, active=False)
    seed = _seed_immeuble(
        run,
        name="77, Rue Chambord",
        address="77, Rue Chambord",
        baux=[{"loyer": 650.0, "nom": "Luc Talbot"}],
    )
    _map_compte(run, "90", "Loyer à remettre - 77 Chambord",
                seed["immeuble_id"])
    qbo = FakeQbo(
        gl_par_compte={
            "90": [
                {"date": MOIS_COURANT.isoformat(), "id": "D-20",
                 "nom": "Luc Talbot", "memo": "", "montant": 650.0},
            ]
        }
    )
    _sync(run, qbo)
    # La transaction EST rapprochée et le mois n'est PAS marqué payé —
    # mais la feature est inactive : rien ne sort.
    etat = _etat(run, MOIS_COURANT)
    assert etat["active"] is False
    assert etat["validations"] == []
    assert etat["encaisses_non_marques"] == []
    assert etat["a_traiter"] == []


# ── 6) Feature active : ✓✓ / ⚠ / encart ────────────────────────────────


def test_etat_valide_sans_trace_et_encaisses_non_marques(run, db_setup):
    _purge(run)
    _set_config(run, active=True, jours=5)
    seed = _seed_immeuble(
        run,
        name="500, Rue Bélanger",
        address="500, Rue Bélanger",
        baux=[
            {"loyer": 780.0, "nom": "Jean Dupont"},
            {"loyer": 1105.0, "nom": "Marie Roy"},
        ],
    )
    _map_compte(run, "95", "Loyer à remettre - 500 Bélanger",
                seed["immeuble_id"])
    dupont, roy = seed["baux"]

    # Dupont : marqué payé il y a 10 jours, AUCUNE trace bancaire → ⚠.
    _marquer_paye(
        run, dupont["bail_id"], MOIS_COURANT, 780.0,
        AUJOURDHUI - timedelta(days=10),
    )
    # Roy : transaction bancaire rapprochée, PAS encore marquée payée
    # → encart « encaissés non marqués ».
    qbo = FakeQbo(
        gl_par_compte={
            "95": [
                {"date": MOIS_COURANT.isoformat(), "id": "D-30",
                 "nom": "Marie Roy", "memo": "", "montant": 1105.0},
            ]
        }
    )
    _sync(run, qbo)

    etat = _etat(run, MOIS_COURANT)
    assert etat["active"] is True
    par_bail = {v["bail_id"]: v for v in etat["validations"]}
    assert par_bail[dupont["bail_id"]]["statut"] == "sans_trace"
    encaisses = etat["encaisses_non_marques"]
    assert [e["bail_id"] for e in encaisses] == [roy["bail_id"]]
    assert encaisses[0]["montant"] == 1105.0
    assert encaisses[0]["locataire_name"] == "Marie Roy"

    # Roy est ensuite marquée payée (1re validation) → ✓✓ « valide »
    # avec la trace QBO, et l'encart se vide.
    _marquer_paye(
        run, roy["bail_id"], MOIS_COURANT, 1105.0, AUJOURDHUI
    )
    etat2 = _etat(run, MOIS_COURANT)
    par_bail2 = {v["bail_id"]: v for v in etat2["validations"]}
    assert par_bail2[roy["bail_id"]]["statut"] == "valide"
    assert par_bail2[roy["bail_id"]]["montant"] == 1105.0
    assert etat2["encaisses_non_marques"] == []


# ── 7) v2 : un compte QBO → PLUSIEURS immeubles (union des baux) ───────


def _mois_avant(m: date, n: int) -> date:
    """1er du mois, n mois avant m."""
    y, mo = m.year, m.month - n
    while mo < 1:
        mo += 12
        y -= 1
    return date(y, mo, 1)


def test_compte_multi_immeubles_union_des_baux(run, db_setup):
    _purge(run)
    a = _seed_immeuble(
        run,
        name="9085, Rue Millen",
        address="9085, Rue Millen",
        baux=[{"loyer": 745.0, "nom": "Alice Fortin"}],
    )
    b = _seed_immeuble(
        run,
        name="710, Rue Legendre",
        address="710, Rue Legendre",
        baux=[{"loyer": 995.0, "nom": "Bruno Caron"}],
    )
    # UN compte QBO pour les DEUX immeubles (réalité du terrain).
    _map_compte(
        run, "200", "9085 Millen & 710 Legendre - Loyer à remettre",
        [a["immeuble_id"], b["immeuble_id"]],
    )
    qbo = FakeQbo(
        gl_par_compte={
            "200": [
                {"date": MOIS_COURANT.isoformat(), "id": "D-100",
                 "nom": "", "memo": "Dépôt", "montant": 745.0},
                {"date": MOIS_COURANT.isoformat(), "id": "D-101",
                 "nom": "", "memo": "Dépôt", "montant": 995.0},
            ]
        }
    )
    _sync(run, qbo)
    rows = {t.qbo_txn_id: t for t in _txns(run)}
    # Chaque dépôt se rapproche au bail de SON immeuble (union des
    # candidats), et la transaction hérite de l'immeuble du bail.
    assert rows["D-100"].statut == "rapproche"
    assert rows["D-100"].bail_id == a["baux"][0]["bail_id"]
    assert rows["D-100"].immeuble_id == a["immeuble_id"]
    assert rows["D-101"].statut == "rapproche"
    assert rows["D-101"].bail_id == b["baux"][0]["bail_id"]
    assert rows["D-101"].immeuble_id == b["immeuble_id"]


# ── 8) v2 : compte fiducie « tous les immeubles » + payeur Interac ─────


def test_compte_tous_les_immeubles_et_payeur_interac(run, db_setup):
    _purge(run)
    a = _seed_immeuble(
        run,
        name="4521, Rue Papineau",
        address="4521, Rue Papineau",
        baux=[{"loyer": 815.0, "nom": "Drissa Kone"}],
    )
    bimm = _seed_immeuble(
        run,
        name="6660, Rue Cartier",
        address="6660, Rue Cartier",
        baux=[{"loyer": 815.0, "nom": "Marie Tremblay"}],
    )
    # Compte fiducie : reçoit les virements de TOUS les locataires —
    # aucun lien fin, la case « tous » suffit.
    _map_compte(
        run, "210", "Fonds en Fiducie – Loyers à Remettre", [], tous=True
    )
    qbo = FakeQbo(
        gl_par_compte={
            "210": [
                # Mémo Interac RÉEL : le payeur est entre les « / ».
                {"date": MOIS_COURANT.isoformat(), "id": "D-110",
                 "nom": "",
                 "memo": "Virement Interac de /DRISSA KONE / ",
                 "montant": 815.0},
                # Même montant, payeur inconnu : DEUX baux (dans DEUX
                # immeubles) plausibles → ambigu, zéro pronostic.
                {"date": MOIS_COURANT.isoformat(), "id": "D-111",
                 "nom": "", "memo": "Transfert entrant",
                 "montant": 815.0},
            ]
        }
    )
    _sync(run, qbo)
    rows = {t.qbo_txn_id: t for t in _txns(run)}

    # Payeur extrait du mémo (strip des « / » et espaces), et le nom
    # départage les deux baux à 815 $ malgré la casse différente.
    assert rows["D-110"].payeur == "DRISSA KONE"
    assert rows["D-110"].statut == "rapproche"
    assert rows["D-110"].bail_id == a["baux"][0]["bail_id"]
    assert rows["D-110"].immeuble_id == a["immeuble_id"]

    assert rows["D-111"].statut == "ambigu"
    assert rows["D-111"].bail_id is None
    assert rows["D-111"].immeuble_id is None  # fiducie : inconnu

    # L'état propose les baux candidats des DEUX immeubles internes.
    _set_config(run, active=True)
    etat = _etat(run, MOIS_COURANT)
    ambigues = [
        t for t in etat["a_traiter"] if t["statut"] == "ambigu"
    ]
    assert len(ambigues) == 1
    cand_ids = {c["bail_id"] for c in ambigues[0]["candidats"]}
    assert a["baux"][0]["bail_id"] in cand_ids
    assert bimm["baux"][0]["bail_id"] in cand_ids


# ── 9) v2 : classification par TYPE + rapport de synchro détaillé ──────


def test_classification_par_type_et_rapport_detaille(run, db_setup):
    _purge(run)
    seed = _seed_immeuble(
        run,
        name="3033, Rue Sherbrooke Est",
        address="3033, Rue Sherbrooke Est",
        baux=[{"loyer": 650.0, "nom": "Luc Talbot"}],
    )
    _map_compte(run, "220", "Loyer à remettre - 3033 Sherbrooke",
                seed["immeuble_id"])
    qbo = FakeQbo(
        gl_par_compte={
            "220": [
                # Dépôt en NÉGATIF : représentation d'un compte de
                # PASSIF (crédit) — la cause du « 0 importée ». Le TYPE
                # dit « entrée », le montant passe en valeur absolue.
                {"date": MOIS_COURANT.isoformat(), "id": "D-120",
                 "type": "Deposit", "nom": "Luc Talbot", "memo": "",
                 "montant": -650.0},
                # Virement de remise SORTANT : jamais un loyer —
                # ignoré proprement (raison « sortie_argent »), mais
                # conservé pour le fil bancaire.
                {"date": MOIS_COURANT.isoformat(), "id": "T-121",
                 "type": "Transfer", "nom": "",
                 "memo": "Paiement internet à /8900 St-Hub/loyer Août",
                 "montant": -650.0},
                # Type inconnu : écarté, mais RAPPORTÉ avec son libellé.
                {"date": MOIS_COURANT.isoformat(), "id": "E-122",
                 "type": "Estimate", "nom": "", "memo": "",
                 "montant": 100.0},
                # Montant nul : écarté (raison « montant_nul »).
                {"date": MOIS_COURANT.isoformat(), "id": "D-123",
                 "type": "Deposit", "nom": "", "memo": "",
                 "montant": 0.0},
            ]
        }
    )
    stats = _sync(run, qbo)

    # Totaux : 1 entrée importée, 3 ignorées (sortie + nul + inconnu).
    assert stats["comptes"] == 1
    assert stats["importees"] == 1
    assert stats["ignorees"] == 3
    detail = stats["details"][0]
    assert detail["compte_nom"] == "Loyer à remettre - 3033 Sherbrooke"
    assert detail["lues"] == 4
    assert detail["importees"] == 1
    assert detail["raisons"]["sortie_argent"] == 1
    assert detail["raisons"]["montant_nul"] == 1
    assert detail["raisons"]["type_non_reconnu"] == 1
    assert detail["types_non_reconnus"] == ["Estimate"]

    rows = {t.qbo_txn_id: t for t in _txns(run)}
    # Le dépôt négatif est importé en valeur absolue ET rapproché.
    assert float(rows["D-120"].montant) == 650.0
    assert rows["D-120"].sens == "entree"
    assert rows["D-120"].statut == "rapproche"
    assert rows["D-120"].bail_id == seed["baux"][0]["bail_id"]
    # La sortie est conservée mais IGNORÉE (jamais candidate).
    assert rows["T-121"].sens == "sortie"
    assert rows["T-121"].statut == "ignoree"
    assert rows["T-121"].ignore_raison == "sortie_argent"
    assert rows["T-121"].bail_id is None
    # Le type inconnu et le montant nul ne sont PAS persistés.
    assert "E-122" not in rows and "D-123" not in rows

    # Rejouer la fenêtre : rien de neuf, l'entrée est « déjà importée ».
    stats2 = _sync(run, qbo)
    assert stats2["importees"] == 0
    d2 = stats2["details"][0]
    assert d2["raisons"]["deja_importee"] == 1
    assert d2["raisons"]["sortie_argent"] == 1  # re-lue, toujours ignorée
    assert len(_txns(run)) == 2  # aucune ligne dupliquée

    # La sortie ne sort JAMAIS dans l'état (ni encart ni à traiter).
    _set_config(run, active=True)
    etat = _etat(run, MOIS_COURANT)
    assert all(
        t["txn_id"] != rows["T-121"].id for t in etat["a_traiter"]
    )

    # …mais le FIL BANCAIRE la montre, avec sa raison.
    async def _fil():
        async with TestSessionLocal() as s:
            return await lister_transactions(s)

    fil = run(_fil())
    par_id = {t["txn_id"]: t for t in fil["transactions"]}
    assert par_id[rows["T-121"].id]["statut"] == "ignoree"
    assert par_id[rows["T-121"].id]["ignore_raison"] == "sortie_argent"
    assert par_id[rows["D-120"].id]["statut"] == "rapproche"
    assert par_id[rows["D-120"].id]["locataire_name"] == "Luc Talbot"


# ── 10) v2 : suggestion multi-immeubles + fiducie → « tous » ───────────


def test_suggestion_multi_immeubles_et_fiducie(run, db_setup):
    import json

    _purge(run)
    # Adresses UNIQUES à ce test (la base est partagée entre les smoke
    # tests — un doublon d'adresse rendrait la paire indiscernable et
    # annulerait la suggestion, comme voulu en prod).
    a = _seed_immeuble(
        run,
        name="4747, Rue Fabre",
        address="4747, Rue Fabre",
        baux=[{"loyer": 700.0, "nom": "Jean Dupont"}],
    )
    b = _seed_immeuble(
        run,
        name="1225, Rue Jarry Est",
        address="1225, Rue Jarry Est",
        baux=[{"loyer": 800.0, "nom": "Marie Roy"}],
    )
    qbo = FakeQbo(
        accounts=[
            {"Id": "230",
             "Name": "4747 Fabre & 1225 Jarry - Loyer à remettre"},
            {"Id": "231",
             "Name": "Fonds en Fiducie – Loyers à Remettre"},
        ]
    )

    async def _do():
        async with TestSessionLocal() as s:
            comptes = await decouvrir_comptes(s, qbo)
            await s.commit()
            return {
                c.qbo_account_id: {
                    "sugg": json.loads(c.suggestion_immeubles_json or "[]"),
                    "tous": bool(c.suggestion_tous),
                }
                for c in comptes
            }

    res = run(_do())
    # Le nom qui cite deux adresses suggère LES DEUX immeubles.
    assert set(res["230"]["sugg"]) == {a["immeuble_id"], b["immeuble_id"]}
    assert res["230"]["tous"] is False
    # Le nom générique fiducie ne suggère rien… sauf la case « tous ».
    assert res["231"]["sugg"] == []
    assert res["231"]["tous"] is True


# ── 11) v2 : paiement multi-mois (2 mois de retard d'un coup) ──────────


def test_paiement_multi_mois_rapproche_et_valide_chaque_mois(run, db_setup):
    _purge(run)
    _set_config(run, active=True, jours=5)
    seed = _seed_immeuble(
        run,
        name="1188, Rue Wolfe",
        address="1188, Rue Wolfe",
        baux=[{"loyer": 650.0, "nom": "Karim Ouali"}],
    )
    bail = seed["baux"][0]
    _map_compte(run, "240", "Loyer à remettre - 1188 Wolfe",
                seed["immeuble_id"])

    # Historique : tout est réglé SAUF les 2 derniers mois échus (m-2 et
    # m-1) — le locataire a sauté deux mois.
    m_2 = _mois_avant(MOIS_COURANT, 2)
    m_1 = _mois_avant(MOIS_COURANT, 1)
    for n in range(3, 13):
        _marquer_paye(
            run, bail["bail_id"], _mois_avant(MOIS_COURANT, n), 650.0,
            AUJOURDHUI - timedelta(days=30 * n),
        )

    # Virement de rattrapage : 2 × 650 $ = 1 300 $.
    qbo = FakeQbo(
        gl_par_compte={
            "240": [
                {"date": MOIS_COURANT.isoformat(), "id": "D-130",
                 "nom": "Karim Ouali", "memo": "", "montant": 1300.0},
            ]
        }
    )
    _sync(run, qbo)
    txn = _txns(run)[0]
    # Rapproché aux DEUX mois échus consécutifs impayés (dette la plus
    # ancienne d'abord — déterministe).
    assert txn.statut == "rapproche"
    assert txn.bail_id == bail["bail_id"]
    assert txn.mois_couvert == m_2
    assert txn.mois_couvert_fin == m_1

    # L'encart « encaissés non marqués » sort UNE ligne PAR mois couvert.
    etat0 = _etat(run, MOIS_COURANT)
    mois_encart = [
        e["mois_couvert"]
        for e in etat0["encaisses_non_marques"]
        if e["bail_id"] == bail["bail_id"]
    ]
    assert mois_encart == [m_2.isoformat(), m_1.isoformat()]

    # Une fois les deux mois marqués payés (1re validation), la pastille
    # ✓✓ s'affiche sur CHACUN des mois couverts.
    _marquer_paye(run, bail["bail_id"], m_2, 650.0, AUJOURDHUI)
    _marquer_paye(run, bail["bail_id"], m_1, 650.0, AUJOURDHUI)
    for mois in (m_2, m_1):
        etat = _etat(run, mois)
        par_bail = {v["bail_id"]: v for v in etat["validations"]}
        assert par_bail[bail["bail_id"]]["statut"] == "valide"

    # STABILITÉ : rejouer la synchro après avoir marqué payé ne défait
    # PAS le rapprochement (les mois ne sont plus « impayés », mais un
    # rapprochement auto posé reste posé tant que l'écriture ne change
    # pas dans QuickBooks).
    _sync(run, qbo)
    txn2 = _txns(run)[0]
    assert txn2.statut == "rapproche"
    assert txn2.mois_couvert == m_2
    assert txn2.mois_couvert_fin == m_1

    # Le fil bancaire porte les mois couverts + le ✓✓ (tous marqués).
    async def _fil():
        async with TestSessionLocal() as s:
            return await lister_transactions(s)

    fil = run(_fil())
    ligne = next(
        t for t in fil["transactions"] if t["txn_id"] == txn.id
    )
    assert ligne["mois_couverts"] == [m_2.isoformat(), m_1.isoformat()]
    assert ligne["valide"] is True


def test_paiement_multi_mois_deux_baux_candidats_ambigu(run, db_setup):
    _purge(run)
    seed = _seed_immeuble(
        run,
        name="2244, Rue Logan",
        address="2244, Rue Logan",
        baux=[
            {"loyer": 650.0, "nom": "Jean Dupont"},
            {"loyer": 650.0, "nom": "Marie Roy"},
        ],
    )
    _map_compte(run, "250", "Loyer à remettre - 2244 Logan",
                seed["immeuble_id"])
    # Les DEUX baux ont les 2 mêmes mois échus impayés (le reste réglé).
    for b in seed["baux"]:
        for n in range(3, 13):
            _marquer_paye(
                run, b["bail_id"], _mois_avant(MOIS_COURANT, n), 650.0,
                AUJOURDHUI - timedelta(days=30 * n),
            )
    # 1 300 $ sans payeur : deux baux plausibles → ambigu, ZÉRO
    # pronostic (ni bail ni mois).
    qbo = FakeQbo(
        gl_par_compte={
            "250": [
                {"date": MOIS_COURANT.isoformat(), "id": "D-140",
                 "nom": "", "memo": "Dépôt guichet", "montant": 1300.0},
            ]
        }
    )
    _sync(run, qbo)
    txn = _txns(run)[0]
    assert txn.statut == "ambigu"
    assert txn.bail_id is None
    assert txn.mois_couvert is None
    assert txn.mois_couvert_fin is None


# ── Locale fr-CA + rapports servis en Débit/Crédit ──────────────────────
# La synchro du 2026-08-14 a lu 116 lignes et en a écarté 116 pour
# « montant nul » : la compagnie QBO est francophone et son GL ne sort
# pas dans le format anglo du parseur d'origine.


def test_parse_montant_bi_locale():
    # Anglo (référence)
    assert _parse_montant("650.00") == 650.0
    assert _parse_montant("1,350.00") == 1350.0
    assert _parse_montant("-425.5") == -425.5
    # fr-CA : virgule décimale, milliers en espace (souvent insécable),
    # symbole dollar, négatif comptable entre parenthèses.
    assert _parse_montant("650,00") == 650.0
    assert _parse_montant("1 350,00") == 1350.0
    assert _parse_montant("1 350,00 $") == 1350.0
    assert _parse_montant("1 350,00") == 1350.0
    assert _parse_montant("(650,00)") == -650.0
    # Milliers anglo sans décimales — la virgule n'est PAS une décimale.
    assert _parse_montant("1,350") == 1350.0
    # Déchets → 0, jamais d'exception.
    assert _parse_montant("") == 0.0
    assert _parse_montant(None) == 0.0
    assert _parse_montant("n/a") == 0.0


def _gl_report_debit_credit() -> Dict[str, Any]:
    """Rapport GL comme le sert une compagnie fr-CA dont les colonnes
    sont Débit / Crédit (aucune colonne Montant)."""
    return {
        "Columns": {
            "Column": [
                {"ColTitle": "Date", "ColType": "tx_date"},
                {"ColTitle": "Type de transaction", "ColType": "txn_type"},
                {"ColTitle": "N°", "ColType": "doc_num"},
                {"ColTitle": "Nom", "ColType": "name"},
                {"ColTitle": "Note", "ColType": "memo"},
                {"ColTitle": "Débit", "ColType": "debt_home_amt"},
                {"ColTitle": "Crédit", "ColType": "credit_home_amt"},
            ]
        },
        "Rows": {
            "Row": [
                {
                    "type": "Section",
                    "Header": {"ColData": [{"value": "Fiducie"}]},
                    "Rows": {
                        "Row": [
                            {
                                "type": "Data",
                                "ColData": [
                                    {"value": AUJOURDHUI.isoformat()},
                                    {"value": "Dépôt", "id": "D-900"},
                                    {"value": ""},
                                    {"value": ""},
                                    {"value": "Virement Interac de /ANNA ROY /"},
                                    {"value": ""},
                                    {"value": "1 350,00"},
                                ],
                            },
                            {
                                "type": "Data",
                                "ColData": [
                                    {"value": AUJOURDHUI.isoformat()},
                                    {"value": "Virement", "id": "V-901"},
                                    {"value": ""},
                                    {"value": "MGV"},
                                    {"value": "Remise du mois"},
                                    {"value": "650,00"},
                                    {"value": ""},
                                ],
                            },
                        ]
                    },
                    "Summary": {"ColData": [{"value": "Total"}]},
                }
            ]
        },
    }


def test_parse_gl_debit_credit_fr_ca():
    entrees, ecartees = parse_general_ledger(_gl_report_debit_credit())
    assert ecartees["lues"] == 2
    assert ecartees["montant_nul"] == 0
    par_id = {e["txn_id"]: e for e in entrees}
    # Crédit 1 350,00 (fr-CA) = encaissement de 1350 $.
    depot = par_id["D-900"]
    assert depot["sens"] == "entree"
    assert depot["montant"] == 1350.0
    assert depot["payeur"] == "ANNA ROY"
    # Débit 650,00 = remise (sortie), classée par TYPE « Virement ».
    remise = par_id["V-901"]
    assert remise["sens"] == "sortie"
    assert remise["montant"] == 650.0
    # L'instrumentation expose le format réel pour le rapport.
    assert any("Débit|" in c for c in ecartees["colonnes"])
    assert ecartees["exemple"][1] == "Dépôt"


class FakeQboColonneMontantSupprimee(FakeQbo):
    """Reproduit le comportement observé en prod le 2026-08-17 : QBO
    honore la liste `columns` mais en SUPPRIME `subt_nat_amount`
    (locale fr-CA) → réponse sans aucune colonne de montant. Le rappel
    SANS `columns` sert le format par défaut, ici en Débit/Crédit."""

    async def report(self, name: str, **params: str) -> Dict[str, Any]:
        assert name == "GeneralLedger"
        self.reports_demandes.append(str(params.get("account") or ""))
        if params.get("columns"):
            # 5 colonnes honorées, montant supprimé — ColTypes
            # GÉNÉRIQUES comme en vrai (Date/String), pas tx_date.
            return {
                "Columns": {
                    "Column": [
                        {"ColTitle": "Date", "ColType": "Date"},
                        {"ColTitle": "Type d'opération", "ColType": "String"},
                        {"ColTitle": "N°", "ColType": "String"},
                        {"ColTitle": "Nom", "ColType": "String"},
                        {"ColTitle": "Mémo/description", "ColType": "String"},
                    ]
                },
                "Rows": {
                    "Row": [
                        {
                            "type": "Section",
                            "Rows": {
                                "Row": [
                                    {
                                        "type": "Data",
                                        "ColData": [
                                            {"value": AUJOURDHUI.isoformat()},
                                            {"value": "Dépôt", "id": "D-950"},
                                            {"value": ""},
                                            {"value": ""},
                                            {"value": "Virement Interac de /LEA GIRARD /"},
                                        ],
                                    }
                                ]
                            },
                        }
                    ]
                },
            }
        return _gl_report_debit_credit_defaut()


def _gl_report_debit_credit_defaut() -> Dict[str, Any]:
    """Le MÊME dépôt, servi par le rappel sans `columns` : format par
    défaut fr-CA avec Débit/Crédit et montant « 650,00 »."""
    return {
        "Columns": {
            "Column": [
                {"ColTitle": "Date", "ColType": "Date"},
                {"ColTitle": "Type d'opération", "ColType": "String"},
                {"ColTitle": "N°", "ColType": "String"},
                {"ColTitle": "Nom", "ColType": "String"},
                {"ColTitle": "Mémo/description", "ColType": "String"},
                {"ColTitle": "Débit", "ColType": "Money"},
                {"ColTitle": "Crédit", "ColType": "Money"},
            ]
        },
        "Rows": {
            "Row": [
                {
                    "type": "Section",
                    "Rows": {
                        "Row": [
                            {
                                "type": "Data",
                                "ColData": [
                                    {"value": AUJOURDHUI.isoformat()},
                                    {"value": "Dépôt", "id": "D-950"},
                                    {"value": ""},
                                    {"value": ""},
                                    {"value": "Virement Interac de /LEA GIRARD /"},
                                    {"value": ""},
                                    {"value": "650,00"},
                                ],
                            }
                        ]
                    },
                }
            ]
        },
    }


def test_sync_repli_sans_columns_quand_montant_supprime(run, db_setup):
    """La synchro détecte « 100 % montants nuls », rappelle le GL sans
    `columns` et importe avec le format par défaut Débit/Crédit."""
    _purge(run)
    _set_config(run, active=True)
    seed = _seed_immeuble(
        run,
        name="1647 Desautels",
        address="1647, Rue Desautels",
        baux=[{"loyer": 650.0, "nom": "Léa Girard"}],
    )
    _map_compte(
        run, "77", "1647 Desautels - Loyers à remettre", seed["immeuble_id"]
    )
    qbo = FakeQboColonneMontantSupprimee()
    stats = _sync(run, qbo)
    # Deux appels pour le compte : l'initial (montant supprimé) + le
    # repli sans columns.
    assert qbo.reports_demandes == ["77", "77"]
    assert stats["importees"] == 1
    txn = _txns(run)[0]
    assert float(txn.montant) == 650.0
    assert txn.sens == "entree"
    assert txn.payeur == "LEA GIRARD"


# ── v6 : dédup fiducie/sous-comptes, préfixe Interac, partiels ──────────


def test_dedup_fiducie_parent_compte_specifique_gagne(run, db_setup):
    """La fiducie est le compte PARENT : son GL inclut les écritures des
    sous-comptes → la même écriture arrivait DEUX fois. La dédup garde
    la ligne du compte SPÉCIFIQUE (l'immeuble est connu) et la fiducie
    ne réimporte pas."""
    _purge(run)
    _set_config(run, active=True)
    seed = _seed_immeuble(
        run,
        name="8900 St-Hubert",
        address="8900, Rue Saint-Hubert",
        baux=[{"loyer": 650.0, "nom": "John-Munster Dupont"}],
    )
    _map_compte(
        run, "22", "8900 St-Hubert - Loyers à remettre", seed["immeuble_id"]
    )
    _map_compte(run, "18", "Fonds en Fiducie", [], tous=True)
    ecriture = {
        "date": MOIS_COURANT.isoformat(),
        "id": "D-800",
        "memo": "Virement Interac de /JOHN-MUNSTER D /",
        "montant": 650.0,
    }
    # Le parent sert la MÊME écriture que le sous-compte.
    qbo = FakeQbo(gl_par_compte={"22": [ecriture], "18": [ecriture]})
    stats = _sync(run, qbo)
    assert stats["importees"] == 1
    txns = _txns(run)
    assert len(txns) == 1
    assert txns[0].qbo_account_id == "22"  # compte spécifique
    assert txns[0].statut == "rapproche"
    # Resynchro : toujours une seule ligne, zéro doublon fusionné.
    stats2 = _sync(run, qbo)
    assert stats2["importees"] == 0
    assert len(_txns(run)) == 1


def test_payeur_interac_tronque_et_paiement_partiel(run, db_setup):
    """Payeurs Interac TRONQUÉS (~14 caractères, constaté en prod) :
    « FRANCOIS PAQUE » désigne François Paquette par PRÉFIXE — ça
    départage deux baux au même loyer. Et un paiement PARTIEL (200 $
    sur 425 $) se rapproche quand le payeur désigne un seul bail."""
    _purge(run)
    _set_config(run, active=True)
    seed = _seed_immeuble(
        run,
        name="44 Kenny-Sud",
        address="44, Rue Kennedy Sud",
        baux=[
            {"loyer": 500.0, "nom": "François Paquette"},
            {"loyer": 500.0, "nom": "Rodolphe Tallard"},
            {"loyer": 425.0, "nom": "Xiao Yu Cao"},
        ],
    )
    _map_compte(
        run, "26", "44 Kenny-Sud - Loyers à remettre", seed["immeuble_id"]
    )
    qbo = FakeQbo(
        gl_par_compte={
            "26": [
                # Deux baux à 500 $ — le préfixe tronqué départage.
                {"date": MOIS_COURANT.isoformat(), "id": "D-810",
                 "memo": "Virement Interac de /FRANCOIS PAQUE /",
                 "montant": 500.0},
                # Partiel : 200 $ sur un loyer de 425 $, payeur unique.
                {"date": MOIS_COURANT.isoformat(), "id": "D-811",
                 "memo": "Virement Interac de /XIAO YU CAO /",
                 "montant": 200.0},
            ]
        }
    )
    _sync(run, qbo)
    txns = {t.qbo_txn_id: t for t in _txns(run)}
    # Même ordre que la liste passée à _seed_immeuble.
    paquette, _tallard, cao = seed["baux"]
    assert txns["D-810"].statut == "rapproche"
    assert txns["D-810"].bail_id == paquette["bail_id"]
    assert txns["D-811"].statut == "rapproche"
    assert txns["D-811"].bail_id == cao["bail_id"]
    assert txns["D-811"].mois_couvert == MOIS_COURANT


# ── v7 : suggestions IA (pré-sélection, jamais d'auto-validation) ───────


def test_suggestion_ia_pre_selectionne_sans_valider(run, db_setup, monkeypatch):
    """Deux baux au même loyer, payeur inconnu de Kratos (conjoint) →
    ambigu. L'IA SUGGÈRE un bail (stocké, exposé au fil), mais le statut
    reste « ambigu » tant qu'un humain n'a pas confirmé. Un bail hors
    candidats proposé par l'IA est REJETÉ (garde-fou)."""
    import app.services.qbo_validation_ia as ia_mod

    _purge(run)
    _set_config(run, active=True)
    seed = _seed_immeuble(
        run,
        name="8900 St-Hubert",
        address="8900, Rue Saint-Hubert",
        baux=[
            {"loyer": 750.0, "nom": "Maritza Alejandra Perez"},
            {"loyer": 750.0, "nom": "Mario Barette"},
        ],
    )
    _map_compte(
        run, "31", "8900 St-Hubert - Loyers à remettre", seed["immeuble_id"]
    )
    maritza, _mario = seed["baux"]

    class FauxResultat:
        provider = "fake"

        def __init__(self, text: str) -> None:
            self.text = text

    async def faux_complete(**kwargs):
        # L'IA choisit le bail de Maritza + propose aussi un bail
        # inexistant (999999) qui doit être écarté par le garde-fou.
        txn_ids = [
            e["txn_id"]
            for e in json.loads(
                kwargs["prompt"].split(
                    "## Transactions à rapprocher (avec leurs candidats)\n"
                )[1].rsplit("\n\nRetourne", 1)[0]
            )
        ]
        return FauxResultat(
            json.dumps(
                [
                    {
                        "txn_id": txn_ids[0],
                        "bail_id": maritza["bail_id"],
                        "confiance": 0.85,
                    },
                    {"txn_id": -1, "bail_id": 999999, "confiance": 0.9},
                ]
            )
        )

    monkeypatch.setattr(ia_mod, "is_configured", lambda: True)
    monkeypatch.setattr(ia_mod, "complete", faux_complete)

    qbo = FakeQbo(
        gl_par_compte={
            "31": [
                {"date": MOIS_COURANT.isoformat(), "id": "D-970",
                 "memo": "Virement Interac de /J TREMBLAY /",
                 "montant": 750.0},
            ]
        }
    )
    stats = _sync(run, qbo)
    assert stats["suggestions_ia"] == 1
    txn = _txns(run)[0]
    assert txn.statut == "ambigu"  # l'IA ne valide JAMAIS
    assert txn.suggestion_bail_id == maritza["bail_id"]
    assert float(txn.suggestion_confiance) == 0.85

    # Le fil bancaire expose la suggestion pour la pré-sélection UI.
    async def _fil():
        async with TestSessionLocal() as s:
            return await lister_transactions(s)

    data = run(_fil())
    ligne = data["transactions"][0]
    assert ligne["suggestion_bail_id"] == maritza["bail_id"]


def test_trop_paye_et_faute_de_frappe_bancaire(run, db_setup):
    """Deux cas RÉELS des captures Phil 2026-08-17 :
    - « MEHREZ DHOUIB » 850 $ sur un loyer de 600 $ (trop-payé) : le nom
      désigne UN locataire → rapproché malgré le montant atypique ;
    - « MARIO BARETTE » (faute de frappe bancaire, un seul R) pour
      Mario Barrette, deux baux au même loyer → la similarité départage."""
    _purge(run)
    _set_config(run, active=True)
    seed = _seed_immeuble(
        run,
        name="8900 St-Hubert",
        address="8900, Rue Saint-Hubert",
        baux=[
            {"loyer": 600.0, "nom": "Mehrez Dhouib"},
            {"loyer": 750.0, "nom": "Mario Barrette"},
            {"loyer": 750.0, "nom": "Maritza Rivera"},
        ],
    )
    _map_compte(
        run, "40", "8900 St-Hubert - Loyers à remettre", seed["immeuble_id"]
    )
    qbo = FakeQbo(
        gl_par_compte={
            "40": [
                {"date": MOIS_COURANT.isoformat(), "id": "D-990",
                 "memo": "Virement Interac de /MEHREZ DHOUIB /",
                 "montant": 850.0},
                {"date": MOIS_COURANT.isoformat(), "id": "D-991",
                 "memo": "Virement Interac de /MARIO BARETTE /",
                 "montant": 750.0},
            ]
        }
    )
    _sync(run, qbo)
    txns = {t.qbo_txn_id: t for t in _txns(run)}
    mehrez, mario, _maritza = seed["baux"]
    assert txns["D-990"].statut == "rapproche"
    assert txns["D-990"].bail_id == mehrez["bail_id"]
    assert txns["D-990"].mois_couvert == MOIS_COURANT
    assert txns["D-991"].statut == "rapproche"
    assert txns["D-991"].bail_id == mario["bail_id"]


def test_imputation_mois_deja_couvert_glisse_au_suivant(run, db_setup):
    """LE cas des captures Phil 2026-08-17 : le loyer de juillet est
    payé début juillet, puis le loyer d'AOÛT est payé le 31 juillet.
    Sans garde, les deux s'imputaient à juillet (montant == loyer) et
    août restait « sans trace ». Avec la garde : un mois couvert par
    une transaction bancaire n'accepte plus d'imputation — le paiement
    du 31 juillet glisse sur août. + « MARITZA ALEJAN » (2e prénom
    inconnu de Kratos) départage deux baux au même loyer."""
    _purge(run)
    _set_config(run, active=True)
    mois_prec = (MOIS_COURANT - timedelta(days=1)).replace(day=1)
    seed = _seed_immeuble(
        run,
        name="8900 St-Hubert",
        address="8900, Rue Saint-Hubert",
        baux=[
            {"loyer": 650.0, "nom": "Oscar Ngando"},
            {"loyer": 750.0, "nom": "Maritza Rivera"},
            {"loyer": 750.0, "nom": "Mario Barrette"},
        ],
    )
    _map_compte(
        run, "50", "8900 St-Hubert - Loyers à remettre", seed["immeuble_id"]
    )
    oscar, maritza, _mario = seed["baux"]
    # Les mois antérieurs sont réglés (marqués payés par l'employé) —
    # comme en prod : la seule dette possible est le mois courant.
    deux_mois_avant = (mois_prec - timedelta(days=1)).replace(day=1)
    _marquer_paye(
        run, oscar["bail_id"], deux_mois_avant, 650.0,
        deux_mois_avant + timedelta(days=2),
    )
    _marquer_paye(
        run, oscar["bail_id"], mois_prec, 650.0,
        mois_prec + timedelta(days=2),
    )
    fin_mois_prec = _mois_suiv(mois_prec) - timedelta(days=1)
    qbo = FakeQbo(
        gl_par_compte={
            "50": [
                # Loyer du mois précédent, payé au début du mois.
                {"date": mois_prec.isoformat(), "id": "D-1100",
                 "memo": "Virement Interac de /OSCAR NGANDO M/",
                 "montant": 650.0},
                # Loyer du mois COURANT, payé le dernier jour du mois
                # précédent → doit glisser sur le mois courant.
                {"date": fin_mois_prec.isoformat(), "id": "D-1101",
                 "memo": "Virement Interac de /OSCAR NGANDO M/",
                 "montant": 650.0},
                # 2e prénom inconnu de Kratos, deux baux à 750 $.
                {"date": MOIS_COURANT.isoformat(), "id": "D-1102",
                 "memo": "Virement Interac de /MARITZA ALEJAN/",
                 "montant": 750.0},
            ]
        }
    )
    _sync(run, qbo)
    txns = {t.qbo_txn_id: t for t in _txns(run)}
    assert txns["D-1100"].bail_id == oscar["bail_id"]
    assert txns["D-1100"].mois_couvert == mois_prec
    assert txns["D-1101"].bail_id == oscar["bail_id"]
    assert txns["D-1101"].mois_couvert == MOIS_COURANT  # a glissé ✓
    assert txns["D-1102"].statut == "rapproche"
    assert txns["D-1102"].bail_id == maritza["bail_id"]


def test_alignement_sur_le_paiement_marque_par_l_employe(run, db_setup):
    """Cas 8900 (captures Phil, 2e vague) : le compte QBO est NEUF —
    aucune transaction de juin pour couvrir juillet. L'employé a marqué
    juillet payé (début juillet) ET août payé (1er août). L'Interac du
    31 juillet est le loyer d'AOÛT : il doit s'aligner sur le paiement
    marqué le plus proche (± 5 jours), pas sur le mois de la date. Et
    forcer=True : une resynchro CORRIGE une imputation antérieure."""
    _purge(run)
    _set_config(run, active=True)
    mois_prec = (MOIS_COURANT - timedelta(days=1)).replace(day=1)
    seed = _seed_immeuble(
        run,
        name="8900 St-Hubert",
        address="8900, Rue Saint-Hubert",
        baux=[{"loyer": 650.0, "nom": "Norbert Yotshi"}],
    )
    _map_compte(
        run, "60", "8900 St-Hubert - Loyers à remettre", seed["immeuble_id"]
    )
    norbert = seed["baux"][0]
    # L'employé marque juillet payé (2 juillet) et août payé (1er août).
    _marquer_paye(
        run, norbert["bail_id"], mois_prec, 650.0,
        mois_prec + timedelta(days=1),
    )
    _marquer_paye(
        run, norbert["bail_id"], MOIS_COURANT, 650.0, MOIS_COURANT
    )
    fin_mois_prec = _mois_suiv(mois_prec) - timedelta(days=1)
    qbo = FakeQbo(
        gl_par_compte={
            "60": [
                # SEULE transaction du compte neuf : l'Interac du 31
                # juillet — c'est le loyer d'août (marqué le 1er août).
                {"date": fin_mois_prec.isoformat(), "id": "D-1200",
                 "memo": "Virement Interac de /NORBERT YOTSHI/",
                 "montant": 650.0},
            ]
        }
    )
    _sync(run, qbo)
    txn = _txns(run)[0]
    assert txn.bail_id == norbert["bail_id"]
    assert txn.mois_couvert == MOIS_COURANT  # aligné sur le marquage ✓
    # Resynchro : stable (forcer=True ne fait pas flip-flopper).
    _sync(run, qbo)
    txn = _txns(run)[0]
    assert txn.statut == "rapproche"
    assert txn.mois_couvert == MOIS_COURANT
