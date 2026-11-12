"""Smoke — Projets - Optimisation (Phil 2026-11-12).

1. « Je veux pouvoir avoir des actifs à court terme à lier à Frais de développement,
   car c'est une retenue de la banque » : un actif à court terme se lie au financement
   d'une enveloppe ; son solde (argent encore retenu par le prêteur) se SOUSTRAIT du
   financé, et le détail le lit en entrée d'argent (mise en retenue −, libération +).
   Cas réel 1660 Saint-Clément : mise de fonds de 30 000 $ retenue, 15 000 $ libérés
   avec un déboursé de 60 000 $ → financé 45 000 $, argent disponible 0 $.
2. « Dans cashflow je devrais pouvoir choisir les catégories qui s'y retrouvent » :
   les catégories retirées sortent des revenus, des dépenses, de l'écart et du détail.
QuickBooks est simulé : aucun appel réseau.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List

import app.integrations.quickbooks as qb_mod
import app.services.qbo_optimisation as opti

from .test_smoke_optimisation_budget_2026_09_24 import _FauxQbo, _FauxQboRapport, _ligne, _projet

PLAN = [
    {"id": "3", "name": "Frais de développement", "fully_qualified_name": "Frais professionnels:Frais de développement",
     "account_type": "Fixed Asset", "classification": "Asset"},
    {"id": "8", "name": "Déboursés - Frais de développement",
     "fully_qualified_name": "Hypothèque/Prêt Peakhill:Déboursés - Frais de développement",
     "account_type": "Long Term Liability", "classification": "Liability"},
    {"id": "52", "name": "Retenue - Frais de développement",
     "fully_qualified_name": "Mise de fonds retenue sur les déboursés progressifs:Retenue - Frais de développement",
     "account_type": "Other Current Asset", "classification": "Asset"},
    {"id": "16", "name": "Déboursés - Travaux", "fully_qualified_name": "Hypothèque/Prêt Peakhill:Déboursés - Travaux",
     "account_type": "Long Term Liability", "classification": "Liability"},
]


def _financer(client, auth_headers, lid: int, comptes: List[str]) -> None:
    r = client.patch(
        f"/api/v1/optimisation/budget-lignes/{lid}", headers=auth_headers,
        json={"qbo_financement_accounts_json": json.dumps([{"id": c, "name": c} for c in comptes])},
    )
    assert r.status_code == 200, r.text


def test_les_actifs_a_court_terme_se_lient_au_financement(run, monkeypatch):
    faux = _FauxQbo({"FROM Account": []})
    monkeypatch.setattr(qb_mod, "get_qbo", lambda scope="construction": faux)
    run(opti.lister_comptes_depense("inc:1", "financement"))
    sql = faux.sql[-1]
    assert "'Other Current Asset'" in sql and "'Long Term Liability'" in sql and "'Equity'" in sql
    assert "'Bank'" not in sql and "'Fixed Asset'" not in sql


def test_retenue_de_la_banque_soustraite_du_finance(client, auth_headers, run, monkeypatch):
    pid = _projet(client, auth_headers, run)
    dev = _ligne(client, auth_headers, pid, "Frais de développement", compte="3")
    travaux = _ligne(client, auth_headers, pid, "Travaux")
    _financer(client, auth_headers, dev, ["8", "52"])       # le prêt tiré + la retenue
    _financer(client, auth_headers, travaux, ["16"])        # un prêt seul : rien ne change
    assert client.patch(f"/api/v1/optimisation/projets/{pid}", headers=auth_headers,
                        json={"qbo_scope": "inc:test"}).status_code == 200

    async def _totaux(scope, d1, d2):
        # Bilan : prêt tiré 60 000 ; retenue 30 000 − 15 000 libérés = 15 000 ; dépensé 75 000.
        return {"3": 75000.0, "8": 60000.0, "52": 15000.0, "16": 146228.22}

    async def _cashflow(scope, d1, d2, hypotheque_account_id=None, **k):
        return {"mois": [], "total": {"revenus": 0, "depenses": 0, "hypotheque": 0, "ecart": 0, "details": []}}

    async def _plan(scope, kind="depense"):
        return PLAN

    monkeypatch.setattr(opti, "depenses_par_compte", _totaux)
    monkeypatch.setattr(opti, "cashflow_mensuel", _cashflow)
    monkeypatch.setattr(opti, "lister_comptes_depense", _plan)
    d = client.get(f"/api/v1/optimisation/projets/{pid}/qbo-depenses", headers=auth_headers).json()
    assert d["erreur"] is None and d["par_ligne"][str(dev)] == 75000.0
    # Financé = prêt tiré − argent encore retenu par la banque.
    assert d["financement_par_ligne"][str(dev)] == 45000.0
    assert d["retenu_par_ligne"] == {str(dev): 15000.0}
    assert d["financement_par_ligne"][str(travaux)] == 146228.22
    assert d["noms_comptes"]["52"].endswith("Retenue - Frais de développement")
    # Argent disponible de l'écran : comptant 30 000 + financé 45 000 − dépensé 75 000 = 0.
    assert 30000 + d["financement_par_ligne"][str(dev)] - d["par_ligne"][str(dev)] == 0

    # Plan comptable illisible : on retombe sur l'ancien calcul (aucune retenue reconnue), sans planter.
    async def _panne(scope, kind="depense"):
        raise RuntimeError("QuickBooks indisponible")

    monkeypatch.setattr(opti, "lister_comptes_depense", _panne)
    d = client.get(f"/api/v1/optimisation/projets/{pid}/qbo-depenses", headers=auth_headers).json()
    assert d["erreur"] is None and d["financement_par_ligne"][str(dev)] == 75000.0 and d["retenu_par_ligne"] == {}


def test_detail_du_finance_la_retenue_se_lit_en_entree_d_argent(run, monkeypatch):
    """Écritures réelles du 1660 Saint-Clément : la mise de fonds part en retenue (débit de
    l'actif), puis la banque verse 80 % du prêt et libère 20 % de la retenue (crédits)."""
    faux = _FauxQbo({
        "FROM Account WHERE Id IN": [{"Id": "8", "Classification": "Liability"}, {"Id": "52", "Classification": "Asset"}],
        "FROM Purchase": [
            {"Id": "18", "TxnDate": "2026-10-13", "TotalAmt": 463936.42, "PrivateNote": "Mise de fonds - Notaire",
             "Line": [{"Amount": 30000, "Description": "Mise de fond retenu sur frais dev",
                       "AccountBasedExpenseLineDetail": {"AccountRef": {"value": "52"}}}]},
        ],
        "FROM Deposit": [
            {"Id": "27", "TxnDate": "2026-11-12", "TotalAmt": 291732.82, "PrivateNote": "Funds transfer received",
             "Line": [
                 {"Amount": 60000, "Description": "80 % des frais de dév.", "DepositLineDetail": {"AccountRef": {"value": "8"}}},
                 {"Amount": 15000, "Description": "20 % des frais de dév.", "DepositLineDetail": {"AccountRef": {"value": "52"}}},
             ]},
        ],
    })
    monkeypatch.setattr(qb_mod, "get_qbo", lambda scope="construction": faux)

    fin = {r["txn_id"]: r for r in run(opti.transactions_depenses("inc:1", {"8", "52"}, "2026-07-01", "2026-11-12", financement=True))}
    assert fin["18"]["montant_impute"] == -30000.0, "argent MIS en retenue chez le prêteur"
    assert fin["27"]["montant_impute"] == 75000.0 and [l["montant"] for l in fin["27"]["lignes"]] == [60000.0, 15000.0]
    # La somme du détail retombe sur le financé affiché : 60 000 − 15 000 encore retenus.
    assert sum(r["montant_impute"] for r in fin.values()) == 45000.0
    # Hors financement (détail d'une enveloppe de dépense), un actif garde son sens naturel.
    dep = {r["txn_id"]: r for r in run(opti.transactions_depenses("inc:1", {"52"}, "2026-07-01", "2026-11-12"))}
    assert dep["18"]["montant_impute"] == 30000.0 and dep["27"]["montant_impute"] == -15000.0


def test_endpoint_du_detail_passe_le_volet(client, auth_headers, run, monkeypatch):
    pid = _projet(client, auth_headers, run)
    lid = _ligne(client, auth_headers, pid, "Frais de développement", compte="3")
    _financer(client, auth_headers, lid, ["8", "52"])
    assert client.patch(f"/api/v1/optimisation/projets/{pid}", headers=auth_headers,
                        json={"qbo_scope": "inc:test"}).status_code == 200
    appels: List[tuple] = []

    async def _detail(scope, comptes, d1, d2, **k):
        appels.append((set(comptes), k))
        return []

    monkeypatch.setattr(opti, "transactions_depenses", _detail)
    base = f"/api/v1/optimisation/projets/{pid}/qbo-lignes/{lid}/transactions"
    assert client.get(base, headers=auth_headers).status_code == 200
    assert client.get(base + "?volet=financement", headers=auth_headers).status_code == 200
    assert appels == [({"3"}, {}), ({"8", "52"}, {"financement": True})]


# ─── Cashflow : catégories choisies ───────────────────────────────────


def _pnl() -> Dict[str, Any]:
    def cells(*vals):
        return [{"value": v} for v in vals]

    def compte(nom, cid, *vals):
        return {"type": "Data", "ColData": [{"value": nom, "id": cid}, *cells(*vals)]}

    cols = [
        {"ColTitle": "", "ColType": "Account"},
        {"ColTitle": "Oct 2026", "ColType": "Money",
         "MetaData": [{"Name": "StartDate", "Value": "2026-10-01"}, {"Name": "EndDate", "Value": "2026-10-31"}]},
        {"ColTitle": "Nov 1-12, 2026", "ColType": "Money",
         "MetaData": [{"Name": "StartDate", "Value": "2026-11-01"}, {"Name": "EndDate", "Value": "2026-11-12"}]},
        {"ColTitle": "Total", "ColType": "Money"},
    ]
    return {
        "Columns": {"Column": cols},
        "Rows": {"Row": [
            {"group": "Income", "Rows": {"Row": [compte("Revenus de location", "10", "1000.00", "1000.00", "2000.00")]},
             "Summary": {"ColData": cells("Total Income", "1000.00", "1000.00", "2000.00")}},
            {"group": "Expenses", "Rows": {"Row": [compte("Taxes foncières", "20", "300.00", "0.00", "300.00")]},
             "Summary": {"ColData": cells("Total Expenses", "300.00", "0.00", "300.00")}},
            {"group": "OtherExpenses", "Rows": {"Row": [compte("Amortissement", "30", "100.00", "100.00", "200.00")]},
             "Summary": {"ColData": cells("Total Other Expenses", "100.00", "100.00", "200.00")}},
            {"group": "NetIncome", "Summary": {"ColData": cells("Net Income", "600.00", "900.00", "1500.00")}},
        ]},
    }


def test_cashflow_categories_retirees(run, monkeypatch):
    faux = _FauxQboRapport(_pnl())
    monkeypatch.setattr(qb_mod, "get_qbo", lambda scope="construction": faux)

    tout = run(opti.cashflow_mensuel("inc:1", "2026-10-01", "2026-11-12"))
    assert [(m["revenus"], m["depenses"], m["ecart"]) for m in tout["mois"]] == [(1000.0, 400.0, 600.0), (1000.0, 100.0, 900.0)]
    assert tout["total"]["ecart"] == 1500.0 and tout["exclues"] == []

    # L'amortissement n'est pas une sortie d'argent : retiré, il sort des dépenses, de l'écart et du détail.
    sans = run(opti.cashflow_mensuel("inc:1", "2026-10-01", "2026-11-12", exclus={"30"}))
    assert [(m["revenus"], m["depenses"], m["ecart"]) for m in sans["mois"]] == [(1000.0, 300.0, 700.0), (1000.0, 0.0, 1000.0)]
    assert (sans["total"]["revenus"], sans["total"]["depenses"], sans["total"]["ecart"]) == (2000.0, 300.0, 1700.0)
    assert [d["nom"] for d in sans["total"]["details"]] == ["Revenus de location", "Taxes foncières"]
    assert [d["nom"] for d in sans["mois"][1]["details"]] == ["Revenus de location"]
    assert sans["exclues"] == [{"nom": "Amortissement", "compte_id": "30", "type": "depense", "montant": 200.0}]

    # Un revenu retiré baisse les revenus et l'écart d'autant.
    sans_loyers = run(opti.cashflow_mensuel("inc:1", "2026-10-01", "2026-11-12", exclus={"10", "30"}))
    assert [(m["revenus"], m["depenses"], m["ecart"]) for m in sans_loyers["mois"]] == [(0.0, 300.0, -300.0), (0.0, 0.0, 0.0)]
    assert sans_loyers["total"]["ecart"] == -300.0 and len(sans_loyers["exclues"]) == 2
    # Un id inconnu ne change rien.
    assert run(opti.cashflow_mensuel("inc:1", "2026-10-01", "2026-11-12", exclus={"999"}))["total"]["ecart"] == 1500.0


def test_choix_des_categories_enregistre_et_applique(client, auth_headers, run, monkeypatch):
    pid = _projet(client, auth_headers, run)
    assert client.patch(f"/api/v1/optimisation/projets/{pid}", headers=auth_headers,
                        json={"qbo_scope": "inc:test"}).status_code == 200
    vus: List[Dict[str, Any]] = []

    async def _totaux(scope, d1, d2):
        return {}

    async def _cashflow(scope, d1, d2, hypotheque_account_id=None, **k):
        vus.append(k)
        return {"mois": [], "total": {"revenus": 0, "depenses": 0, "hypotheque": 0, "ecart": 0, "details": []}, "exclues": []}

    async def _plan(scope, kind="depense"):
        return []

    monkeypatch.setattr(opti, "depenses_par_compte", _totaux)
    monkeypatch.setattr(opti, "cashflow_mensuel", _cashflow)
    monkeypatch.setattr(opti, "lister_comptes_depense", _plan)
    url = f"/api/v1/optimisation/projets/{pid}/qbo-depenses"
    # Par défaut : tout le résultat, comme avant (aucun filtre passé).
    assert client.get(url, headers=auth_headers).status_code == 200 and vus == [{}]
    r = client.patch(f"/api/v1/optimisation/projets/{pid}", headers=auth_headers,
                     json={"cashflow_exclus_json": json.dumps(["30", "31"])})
    assert r.status_code == 200 and json.loads(r.json()["cashflow_exclus_json"]) == ["30", "31"]
    assert client.get(url, headers=auth_headers).status_code == 200 and vus[-1] == {"exclus": {"30", "31"}}
    # Tout recoché : la liste vide ne filtre plus rien.
    assert client.patch(f"/api/v1/optimisation/projets/{pid}", headers=auth_headers,
                        json={"cashflow_exclus_json": "[]"}).status_code == 200
    assert client.get(url, headers=auth_headers).status_code == 200 and vus[-1] == {}
