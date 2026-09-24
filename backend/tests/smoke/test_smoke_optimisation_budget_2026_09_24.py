"""Smoke — Projets - Optimisation, section Budget (Phil 2026-09-24).

1. Le menu ⚙ propose TOUT le plan comptable (kind « tous ») ;
3. l'ordre des enveloppes se choisit (POST …/budget-lignes/ordre) ;
4. le détail d'une enveloppe montre les ÉCRITURES DE JOURNAL (ex. le
   8 076 d'« Acquisition ») et liste un compte de bilan sans borne de
   début (son total est un solde) ;
5. qbo-depenses renvoie le nom COMPLET des comptes suivis pour titrer
   les enveloppes avec la catégorie entière.
QuickBooks est simulé : aucun appel réseau.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List

import app.integrations.quickbooks as qb_mod
import app.services.qbo_optimisation as opti

from .test_smoke_optimisation import _seed_immeuble


class _FauxQbo:
    """Client QuickBooks minimal : répond aux requêtes par motif."""

    ready = True

    def __init__(self, reponses: Dict[str, List[Dict[str, Any]]]):
        self.reponses = reponses
        self.sql: List[str] = []

    async def query(self, sql: str) -> List[Dict[str, Any]]:
        self.sql.append(sql)
        for motif, rows in self.reponses.items():
            if motif in sql:
                return rows
        return []

    async def list_attachables(self) -> List[Dict[str, Any]]:
        return self.reponses.get("__attachables__", [])


def test_plan_comptable_complet(run, monkeypatch):
    faux = _FauxQbo(
        {
            "FROM Account": [
                {"Id": "1", "Name": "Desjardins", "FullyQualifiedName": "Desjardins",
                 "AccountType": "Bank", "Classification": "Asset"},
                {"Id": "12", "Name": "Taxes de bienvenue",
                 "FullyQualifiedName": "Acquisition:Taxes de bienvenue",
                 "AccountType": "Fixed Asset", "Classification": "Asset"},
                {"Id": "77", "Name": "Frais bancaire",
                 "FullyQualifiedName": "Frais de détention:Frais bancaire",
                 "AccountType": "Expense", "Classification": "Expense"},
            ]
        }
    )
    monkeypatch.setattr(qb_mod, "get_qbo", lambda scope="construction": faux)

    tous = run(opti.lister_comptes_depense("inc:1", "tous"))
    assert [c["id"] for c in tous] == ["12", "1", "77"], "tri par nom complet"
    assert "AccountType IN" not in faux.sql[-1], "aucun filtre de type"
    assert tous[2]["fully_qualified_name"] == "Frais de détention:Frais bancaire"

    run(opti.lister_comptes_depense("inc:1", "depense"))
    assert "AccountType IN ('Expense'" in faux.sql[-1], "famille filtrée comme avant"


def test_detail_enveloppe_ecritures_de_journal(run, monkeypatch):
    """Acquisition (compte de bilan) : 8 076 passés par écriture de
    journal AVANT la date de début du projet → visibles quand même ;
    une facture d'un compte de dépense datée d'avant reste exclue."""
    faux = _FauxQbo(
        {
            "FROM Account WHERE Id IN": [
                {"Id": "12", "Classification": "Asset"},
                {"Id": "77", "Classification": "Expense"},
            ],
            "FROM Bill": [
                {"Id": "B1", "TxnDate": "2025-12-15", "TotalAmt": 100,
                 "VendorRef": {"name": "Vieux fournisseur"},
                 "Line": [{"Amount": 100, "AccountBasedExpenseLineDetail":
                           {"AccountRef": {"value": "77"}}}]},
                {"Id": "B2", "TxnDate": "2026-02-01", "TotalAmt": 250,
                 "DocNumber": "F-250",
                 "VendorRef": {"name": "Banque"},
                 "Line": [{"Amount": 250, "AccountBasedExpenseLineDetail":
                           {"AccountRef": {"value": "77"}}}]},
            ],
            "FROM JournalEntry": [
                {"Id": "501", "TxnDate": "2025-11-30", "TotalAmt": 8076,
                 "DocNumber": "EJ-1", "PrivateNote": "Clôture d'achat",
                 "Line": [
                     {"Amount": 8076, "Description": "Taxes de bienvenue",
                      "JournalEntryLineDetail": {
                          "PostingType": "Debit",
                          "AccountRef": {"value": "12"},
                          "Entity": {"EntityRef": {"name": "Notaire Tremblay"}}}},
                     {"Amount": 8076, "JournalEntryLineDetail": {
                         "PostingType": "Credit",
                         "AccountRef": {"value": "99"}}},
                 ]},
                {"Id": "502", "TxnDate": "2026-03-01", "TotalAmt": 50,
                 "Line": [
                     {"Amount": 50, "Description": "Correction",
                      "JournalEntryLineDetail": {
                          "PostingType": "Credit",
                          "AccountRef": {"value": "12"}}},
                     {"Amount": 50, "JournalEntryLineDetail": {
                         "PostingType": "Debit",
                         "AccountRef": {"value": "99"}}},
                 ]},
                {"Id": "503", "TxnDate": "2026-03-02", "TotalAmt": 10,
                 "Line": [{"Amount": 10, "JournalEntryLineDetail": {
                     "PostingType": "Debit", "AccountRef": {"value": "99"}}}]},
                # Le cas de Phil : 3 éléments (3 factures) dans UNE écriture.
                {"Id": "504", "TxnDate": "2026-07-27", "TotalAmt": 8076,
                 "DocNumber": "1",
                 "Line": [
                     {"Amount": 3000, "Description": "Inspection du bâtiment",
                      "JournalEntryLineDetail": {
                          "PostingType": "Debit", "AccountRef": {"value": "12"},
                          "Entity": {"EntityRef": {"name": "Inspecteur Roy"}}}},
                     {"Amount": 4000, "Description": "Notaire",
                      "JournalEntryLineDetail": {
                          "PostingType": "Debit", "AccountRef": {"value": "12"}}},
                     {"Amount": 1076, "Description": "Évaluation",
                      "JournalEntryLineDetail": {
                          "PostingType": "Debit", "AccountRef": {"value": "12"}}},
                     {"Amount": 8076, "JournalEntryLineDetail": {
                         "PostingType": "Credit", "AccountRef": {"value": "99"}}},
                 ]},
            ],
            "__attachables__": [
                {"Id": "A1", "FileName": "acte.pdf", "ContentType": "application/pdf",
                 "AttachableRef": [{"EntityRef": {"type": "JournalEntry", "value": "501"}}]},
            ],
        }
    )
    monkeypatch.setattr(qb_mod, "get_qbo", lambda scope="construction": faux)

    rows = run(
        opti.transactions_depenses("inc:1", {"12", "77"}, "2026-01-01", "2026-09-24")
    )
    cles = [(r["txn_type"], r["txn_id"]) for r in rows]
    assert ("journalentry", "501") in cles, "écriture de journal d'avant le projet (bilan)"
    assert ("journalentry", "502") in cles
    assert ("journalentry", "503") not in cles, "ne touche pas l'enveloppe"
    assert ("bill", "B2") in cles
    assert ("bill", "B1") not in cles, "compte de dépense : borné au début du projet"
    je = next(r for r in rows if r["txn_id"] == "501")
    assert je["montant_impute"] == 8076.0
    assert je["fournisseur"] == "Notaire Tremblay"
    assert je["description"] == "Clôture d'achat"
    assert je["doc_number"] == "EJ-1"
    assert [p["att_id"] for p in je["pieces"]] == ["A1"]
    assert [l["montant"] for l in je["lignes"]] == [8076.0]
    corr = next(r for r in rows if r["txn_id"] == "502")
    assert corr["montant_impute"] == -50.0, "crédit = retrait de l'enveloppe"
    assert corr["fournisseur"] is None and corr["description"] == "Correction"
    # 3 éléments → 3 sous-lignes, rien d'ambigu sur la ligne principale.
    trois = next(r for r in rows if r["txn_id"] == "504")
    assert trois["montant_impute"] == 8076.0
    assert trois["fournisseur"] is None and trois["description"] is None
    assert [(l["description"], l["fournisseur"], l["montant"]) for l in trois["lignes"]] == [
        ("Inspection du bâtiment", "Inspecteur Roy", 3000.0),
        ("Notaire", None, 4000.0),
        ("Évaluation", None, 1076.0),
    ]
    # Un compte de bilan dans l'enveloppe → les requêtes ne bornent pas
    # le début (le total affiché est un solde à la date de fin).
    assert all("TxnDate >=" not in q for q in faux.sql if "FROM Bill" in q)
    # Tri : plus récent en premier.
    assert [r["date"] for r in rows] == sorted((r["date"] for r in rows), reverse=True)

    # Enveloppe 100 % dépenses → borne de début conservée, comme avant.
    faux.sql.clear()
    rows2 = run(
        opti.transactions_depenses("inc:1", {"77"}, "2026-01-01", "2026-09-24")
    )
    assert [r["txn_id"] for r in rows2] == ["B2"]
    assert all("TxnDate >= '2026-01-01'" in q for q in faux.sql if "FROM Bill" in q)


def _projet(client, auth_headers, run) -> int:
    from app.models.entreprise import Entreprise

    from .conftest import TestSessionLocal

    async def _ent():
        async with TestSessionLocal() as s:
            e = Entreprise(name="INC Budget 2026-09-24")
            s.add(e)
            await s.commit()
            return e.id

    ent_id = run(_ent())
    imm_id = _seed_immeuble(run)
    r = client.post(
        "/api/v1/optimisation/projets",
        headers=auth_headers,
        json={
            "name": "Opti budget 2026-09-24",
            "entreprise_id": ent_id,
            "immeuble_id": imm_id,
            "date_debut": "2026-01-01",
        },
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _ligne(client, auth_headers, pid, nom, compte=None) -> int:
    body = {"nom": nom, "budget_montant": 0}
    if compte:
        body["qbo_accounts_json"] = json.dumps([{"id": compte, "name": nom}])
    r = client.post(
        f"/api/v1/optimisation/projets/{pid}/budget-lignes",
        headers=auth_headers, json=body,
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_ordre_des_enveloppes(client, auth_headers, run):
    pid = _projet(client, auth_headers, run)
    a = _ligne(client, auth_headers, pid, "Acquisition")
    b = _ligne(client, auth_headers, pid, "Frais bancaire")
    c = _ligne(client, auth_headers, pid, "Taxes de bienvenue")
    lu = client.get(f"/api/v1/optimisation/projets/{pid}", headers=auth_headers).json()
    # ⚠️ Banc SQLite : les FK ON DELETE CASCADE ne sont pas appliquées et
    # l'id d'un projet supprimé par un autre test est réutilisé → des
    # lignes orphelines peuvent précéder les nôtres. On raisonne donc sur
    # la liste RÉELLE du projet (en prod, Postgres cascade et n'a pas ce
    # problème).
    ids0 = [l["id"] for l in lu["budget_lignes"]]
    assert [i for i in ids0 if i in (a, b, c)] == [a, b, c], "ordre de création"

    # « Taxes de bienvenue en premier ».
    voulu = [c] + [i for i in ids0 if i != c]
    r = client.post(
        f"/api/v1/optimisation/projets/{pid}/budget-lignes/ordre",
        headers=auth_headers, json={"ids": voulu},
    )
    assert r.status_code == 200, r.text
    assert [l["id"] for l in r.json()["budget_lignes"]] == voulu
    assert [l["position"] for l in r.json()["budget_lignes"]] == list(range(len(voulu)))
    lu = client.get(f"/api/v1/optimisation/projets/{pid}", headers=auth_headers).json()
    assert [l["id"] for l in lu["budget_lignes"]] == voulu, "persisté"

    # Liste incomplète, doublon ou ligne d'un autre projet → refus.
    for ids in (voulu[:-1], voulu + [voulu[0]], voulu + [999_999]):
        r = client.post(
            f"/api/v1/optimisation/projets/{pid}/budget-lignes/ordre",
            headers=auth_headers, json={"ids": ids},
        )
        assert r.status_code == 422, (ids, r.text)
    assert client.post(
        "/api/v1/optimisation/projets/999999/budget-lignes/ordre",
        headers=auth_headers, json={"ids": [a]},
    ).status_code == 404


def test_qbo_depenses_noms_complets(client, auth_headers, run, monkeypatch):
    pid = _projet(client, auth_headers, run)
    lid = _ligne(client, auth_headers, pid, "Frais bancaire", compte="77")
    _ligne(client, auth_headers, pid, "Détention sans compte")
    r = client.patch(
        f"/api/v1/optimisation/projets/{pid}",
        headers=auth_headers, json={"qbo_scope": "inc:test"},
    )
    assert r.status_code == 200, r.text

    async def _totaux(scope, d1, d2):
        return {"77": 123.45}

    async def _cashflow(scope, d1, d2, hypotheque_account_id=None):
        return {"mois": [], "total": {"revenus": 0, "depenses": 0,
                                      "hypotheque": 0, "ecart": 0, "details": []}}

    appels: List[str] = []

    async def _plan(scope, kind="depense"):
        appels.append(kind)
        return [
            {"id": "77", "name": "Frais bancaire",
             "fully_qualified_name": "Frais de détention:Frais bancaire",
             "account_type": "Expense", "classification": "Expense"},
            {"id": "12", "name": "Taxes de bienvenue",
             "fully_qualified_name": "Acquisition:Taxes de bienvenue",
             "account_type": "Fixed Asset", "classification": "Asset"},
        ]

    monkeypatch.setattr(opti, "depenses_par_compte", _totaux)
    monkeypatch.setattr(opti, "cashflow_mensuel", _cashflow)
    monkeypatch.setattr(opti, "lister_comptes_depense", _plan)

    q = client.get(
        f"/api/v1/optimisation/projets/{pid}/qbo-depenses", headers=auth_headers,
    )
    assert q.status_code == 200, q.text
    d = q.json()
    assert d["erreur"] is None
    assert d["par_ligne"][str(lid)] == 123.45
    # Seuls les comptes SUIVIS sont renvoyés, avec leur nom complet.
    assert d["noms_comptes"] == {"77": "Frais de détention:Frais bancaire"}
    assert appels == ["tous"]

    # Le nom complet devient le titre de l'enveloppe (PATCH fait par
    # l'écran) — le nom stocké est bien modifiable.
    r = client.patch(
        f"/api/v1/optimisation/budget-lignes/{lid}",
        headers=auth_headers,
        json={"nom": "Frais de détention : Frais bancaire",
              "qbo_accounts_json": json.dumps(
                  [{"id": "77", "name": "Frais de détention : Frais bancaire"}])},
    )
    assert r.status_code == 200 and r.json()["nom"] == "Frais de détention : Frais bancaire"


def test_compte_parent_avec_ecritures_propres():
    """Structure réelle d'un rapport QBO : un compte PARENT qui a ses
    propres écritures porte le montant sur l'EN-TÊTE de sa section (ses
    sous-comptes ont leurs lignes). Phil 2026-09-24 : « je ne vois pas un
    frais bancaire de 5,95 $ classé comme dépense » → il était posté sur
    le parent et ignoré par les 3 parseurs."""
    from app.services.qbo_optimisation import (
        _comptes_par_colonne,
        _soldes_par_compte_colonnes,
        _walk_rows,
    )

    section_depenses = {
        "Header": {"ColData": [{"value": "Dépenses"}, {"value": ""}, {"value": ""}]},
        "Rows": {"Row": [
            {
                "Header": {"ColData": [
                    {"value": "Frais de détention", "id": "80"},
                    {"value": "5.95"}, {"value": "5.95"},
                ]},
                "Rows": {"Row": [
                    {"ColData": [{"value": "Frais bancaire", "id": "81"},
                                 {"value": "100.00"}, {"value": "100.00"}],
                     "type": "Data"},
                ]},
                "Summary": {"ColData": [{"value": "Total Frais de détention"},
                                        {"value": "105.95"}, {"value": "105.95"}]},
                "type": "Section",
            },
            {
                # Parent SANS écriture propre : en-tête vide → rien.
                "Header": {"ColData": [{"value": "Travaux", "id": "90"},
                                       {"value": ""}, {"value": ""}]},
                "Rows": {"Row": [
                    {"ColData": [{"value": "Plomberie", "id": "91"},
                                 {"value": "1000.00"}, {"value": "1000.00"}],
                     "type": "Data"},
                ]},
                "Summary": {"ColData": [{"value": "Total Travaux"},
                                        {"value": "1000.00"}, {"value": "1000.00"}]},
                "type": "Section",
            },
        ]},
        "Summary": {"ColData": [{"value": "Total Dépenses"},
                                {"value": "1105.95"}, {"value": "1105.95"}]},
        "type": "Section",
        "group": "Expenses",
    }

    totaux: dict = {}
    _walk_rows([section_depenses], totaux)
    assert totaux == {"80": 5.95, "81": 100.0, "91": 1000.0}

    comptes: list = []
    _comptes_par_colonne([section_depenses], comptes)
    assert {(c["nom"], c["compte_id"], c["type"], c["vals"][0]) for c in comptes} == {
        ("Frais de détention", "80", "depense", 5.95),
        ("Frais bancaire", "81", "depense", 100.0),
        ("Plomberie", "91", "depense", 1000.0),
    }

    soldes: dict = {}
    _soldes_par_compte_colonnes([section_depenses], soldes)
    assert soldes["80"] == {"nom": "Frais de détention", "vals": [5.95, 5.95]}
    assert "90" in soldes and soldes["90"]["vals"] == [0.0, 0.0]


def test_detail_financement_depots_virements(run, monkeypatch):
    """« Financé » cliquable (Phil 2026-09-24) : sur un compte de PASSIF
    (prêt), un dépôt ou un virement tiré = +, un remboursement (paiement
    ou débit d'écriture) = −. Les pièces suivent le dépôt."""
    faux = _FauxQbo(
        {
            "FROM Account WHERE Id IN": [
                {"Id": "200", "Classification": "Liability"},
            ],
            "FROM Deposit": [
                {"Id": "D1", "TxnDate": "2026-02-10", "TotalAmt": 50000,
                 "PrivateNote": "Déboursé du prêt",
                 "Line": [{"Amount": 50000, "DepositLineDetail": {
                     "AccountRef": {"value": "200"},
                     "Entity": {"name": "Desjardins"}}}]},
            ],
            "FROM Transfer": [
                {"Id": "T1", "TxnDate": "2026-03-05", "Amount": 5000,
                 "FromAccountRef": {"value": "200", "name": "Marge"},
                 "ToAccountRef": {"value": "1", "name": "Compte courant"}},
            ],
            "FROM JournalEntry": [
                {"Id": "J1", "TxnDate": "2026-04-01", "TotalAmt": 1000,
                 "Line": [
                     {"Amount": 1000, "Description": "Remboursement capital",
                      "JournalEntryLineDetail": {
                          "PostingType": "Debit", "AccountRef": {"value": "200"}}},
                     {"Amount": 1000, "JournalEntryLineDetail": {
                         "PostingType": "Credit", "AccountRef": {"value": "1"}}},
                 ]},
            ],
            "FROM Purchase": [
                {"Id": "P1", "TxnDate": "2026-05-01", "TotalAmt": 2000,
                 "EntityRef": {"name": "Desjardins"},
                 "Line": [{"Amount": 2000, "AccountBasedExpenseLineDetail":
                           {"AccountRef": {"value": "200"}}}]},
            ],
            "__attachables__": [
                {"Id": "A9", "FileName": "contrat-pret.pdf",
                 "ContentType": "application/pdf",
                 "AttachableRef": [{"EntityRef": {"type": "Deposit", "value": "D1"}}]},
            ],
        }
    )
    monkeypatch.setattr(qb_mod, "get_qbo", lambda scope="construction": faux)

    rows = run(
        opti.transactions_depenses("inc:1", {"200"}, "2026-01-01", "2026-09-24")
    )
    par_id = {r["txn_id"]: r for r in rows}
    assert set(par_id) == {"D1", "T1", "J1", "P1"}
    assert par_id["D1"]["montant_impute"] == 50000.0
    assert par_id["D1"]["txn_type"] == "deposit"
    assert par_id["D1"]["fournisseur"] == "Desjardins"
    assert par_id["D1"]["description"] == "Déboursé du prêt"
    assert [p["att_id"] for p in par_id["D1"]["pieces"]] == ["A9"]
    assert par_id["T1"]["montant_impute"] == 5000.0, "crédit sur le passif = tiré"
    assert par_id["T1"]["montant_total"] == 5000.0
    assert par_id["T1"]["lignes"][0]["description"] == "Virement : Marge → Compte courant"
    assert par_id["J1"]["montant_impute"] == -1000.0, "débit sur le passif = remboursé"
    assert par_id["P1"]["montant_impute"] == -2000.0, "paiement = remboursé"
    # Compte de bilan → aucune borne de début dans les requêtes.
    assert all("TxnDate >=" not in q for q in faux.sql if "FROM Deposit" in q)


def test_endpoint_volet_financement(client, auth_headers, run, monkeypatch):
    """L'endpoint du détail choisit les comptes du volet demandé."""
    pid = _projet(client, auth_headers, run)
    lid = _ligne(client, auth_headers, pid, "Travaux", compte="77")
    r = client.patch(
        f"/api/v1/optimisation/budget-lignes/{lid}",
        headers=auth_headers,
        json={"qbo_financement_accounts_json": json.dumps(
            [{"id": "200", "name": "Prêt"}])},
    )
    assert r.status_code == 200, r.text
    assert client.patch(
        f"/api/v1/optimisation/projets/{pid}",
        headers=auth_headers, json={"qbo_scope": "inc:test"},
    ).status_code == 200

    appels: List[set] = []

    async def _faux_detail(scope, comptes, d1, d2):
        appels.append(set(comptes))
        return []

    monkeypatch.setattr(opti, "transactions_depenses", _faux_detail)
    base = f"/api/v1/optimisation/projets/{pid}/qbo-lignes/{lid}/transactions"
    assert client.get(base, headers=auth_headers).status_code == 200
    assert client.get(base + "?volet=financement", headers=auth_headers).status_code == 200
    assert appels == [{"77"}, {"200"}]
    assert client.get(base + "?volet=autre", headers=auth_headers).status_code == 422
