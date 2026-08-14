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
"""
from __future__ import annotations

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
    QboCompteLoyer,
    QboTransactionLoyer,
)
from app.services.qbo_validation_loyers import (
    VALIDATION_KEY,
    confirmer_transaction,
    decouvrir_comptes,
    etat_validation,
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


def _map_compte(run, qbo_account_id: str, nom: str, immeuble_id: int) -> int:
    """Compte découvert + confirmé (comme le ferait Paramètres)."""

    async def _do() -> int:
        async with TestSessionLocal() as s:
            c = QboCompteLoyer(
                qbo_account_id=qbo_account_id,
                qbo_account_name=nom,
                immeuble_id=immeuble_id,
                actif=True,
                created_at=datetime.now(timezone.utc),
            )
            s.add(c)
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
