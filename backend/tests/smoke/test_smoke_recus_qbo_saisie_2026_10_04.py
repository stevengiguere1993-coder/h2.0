"""Smoke — saisie des reçus « en miroir » de QuickBooks (Steven, 2026-10-04).

Formulaire « Reçus » du pôle Entreprises : on choisit l'inc, on remplit
les champs de l'écran Dépense / Facture fournisseur de QB, et Kratos crée
la transaction dans le QuickBooks de l'inc, photo jointe. Le reçu n'est
pas gardé dans Kratos (la copie de nuit le range dans le Drive) ; seule
une trace minimale reste (qui, quand, numéro QB, clé d'envoi).

Client QuickBooks factice : aucun appel réseau.
"""
from __future__ import annotations

import json
import uuid
from datetime import date
from typing import Any, Dict, List, Optional

import pytest

from app.core.security import create_access_token, get_password_hash
from app.integrations.quickbooks import QuickBooksError
from app.models.entreprise import Entreprise
from app.models.qbo_connection import QboConnection
from app.models.recu_qbo_saisi import RecuQboSaisi
from app.models.user import User
from app.services.recu_qbo_saisie import RecuIn, SaisieErreur, taxes_du_recu, ventiler

from .conftest import TestSessionLocal

PDF = b"%PDF-1.4 recu smoke"
JOUR = "2026-10-03"

TAXES = {
    "10": {"Id": "10", "Name": "TPS (CTI)", "RateValue": 5},
    "11": {"Id": "11", "Name": "TVQ (RTI)", "RateValue": 9.975},
    "12": {"Id": "12", "Name": "Exonéré", "RateValue": 0},
}
CODES = [
    {
        "Id": "5",
        "Name": "TPS/TVQ QC - 9,975",
        "PurchaseTaxRateList": {
            "TaxRateDetail": [
                {"TaxRateRef": {"value": "10"}},
                {"TaxRateRef": {"value": "11"}},
            ]
        },
    },
    {
        "Id": "6",
        "Name": "Exonéré",
        "PurchaseTaxRateList": {"TaxRateDetail": [{"TaxRateRef": {"value": "12"}}]},
    },
    # Code de VENTE seulement : pas proposé sur un reçu.
    {"Id": "7", "Name": "Vente seulement", "SalesTaxRateList": {"TaxRateDetail": []}},
]
COMPTES = [
    {"Id": "35", "Name": "Desjardins", "FullyQualifiedName": "Desjardins", "AccountType": "Bank"},
    {"Id": "41", "Name": "Visa Steven", "FullyQualifiedName": "Visa Steven", "AccountType": "Credit Card"},
    {"Id": "60", "Name": "Fournitures", "FullyQualifiedName": "Fournitures", "AccountType": "Expense", "AcctNum": "5200"},
    {"Id": "61", "Name": "Matériaux", "FullyQualifiedName": "Coûts:Matériaux", "AccountType": "Cost of Goods Sold"},
    {"Id": "62", "Name": "Outillage", "FullyQualifiedName": "Outillage", "AccountType": "Fixed Asset"},
    {"Id": "90", "Name": "Comptes fournisseurs", "FullyQualifiedName": "Comptes fournisseurs", "AccountType": "Accounts Payable"},
]


class _FakeQbo:
    ready = True
    realm_id = "9130"

    def __init__(self) -> None:
        self.vendors: List[Dict[str, Any]] = [
            {"Id": "56", "DisplayName": "Rona"},
            {"Id": "57", "DisplayName": "Ébénisterie Côté"},
            {"Id": "58", "DisplayName": "Bureau en Gros"},
        ]
        self.purchases: List[Dict[str, Any]] = [
            {
                "Id": "300",
                "TxnDate": "2026-09-20",
                "TotalAmt": 50.0,
                "EntityRef": {"value": "56", "name": "Rona", "type": "Vendor"},
                "AccountRef": {"value": "41"},
                "PaymentMethodRef": {"value": "2"},
                "Line": [
                    {
                        "DetailType": "AccountBasedExpenseLineDetail",
                        "Amount": 43.49,
                        "AccountBasedExpenseLineDetail": {
                            "AccountRef": {"value": "61"},
                            "TaxCodeRef": {"value": "5"},
                        },
                    }
                ],
            }
        ]
        self.bills: List[Dict[str, Any]] = []
        self.creations: List[tuple] = []
        self.pieces: List[Dict[str, Any]] = []
        self.refuser_taxes_exactes = False
        self.refuser_piece = False

    # ── Lectures ──
    async def query_all(self, sql: str) -> List[Dict[str, Any]]:
        if "FROM Vendor" in sql:
            return list(self.vendors)
        if "FROM Account" in sql:
            return list(COMPTES)
        if "FROM PaymentMethod" in sql:
            return [{"Id": "2", "Name": "Carte de crédit"}, {"Id": "1", "Name": "Virement"}]
        if "FROM Term" in sql:
            return [{"Id": "3", "Name": "Net 30", "DueDays": 30}]
        if "FROM TaxCode" in sql:
            return list(CODES)
        if "FROM TaxRate" in sql:
            return list(TAXES.values())
        return []

    async def query(self, sql: str) -> List[Dict[str, Any]]:
        rows = self.purchases if "FROM Purchase" in sql else self.bills if "FROM Bill" in sql else []
        if "TxnDate = '" in sql:
            jour = sql.split("TxnDate = '", 1)[1][:10]
            return [r for r in rows if r.get("TxnDate") == jour]
        return sorted(rows, key=lambda r: r.get("TxnDate") or "", reverse=True)

    async def get_account(self, account_id: str) -> Optional[Dict[str, Any]]:
        return next((dict(a) for a in COMPTES if a["Id"] == account_id), None)

    async def get_tax_code(self, code_id: str) -> Optional[Dict[str, Any]]:
        return next((c for c in CODES if c["Id"] == code_id), None)

    async def get_tax_rate(self, rate_id: str) -> Optional[Dict[str, Any]]:
        return TAXES.get(rate_id)

    async def find_vendor_by_name(self, name: str) -> Optional[Dict[str, Any]]:
        return next((v for v in self.vendors if v["DisplayName"] == name), None)

    async def get_purchase(self, txn_id: str) -> Dict[str, Any]:
        return next(p for p in self.purchases if p["Id"] == txn_id)

    async def get_bill(self, txn_id: str) -> Dict[str, Any]:
        return next(b for b in self.bills if b["Id"] == txn_id)

    # ── Écritures ──
    async def create_vendor(self, *, display_name: str, **_: Any) -> Dict[str, Any]:
        v = {"Id": str(100 + len(self.vendors)), "DisplayName": display_name}
        self.vendors.append(v)
        return v

    def _total(self, payload: Dict[str, Any]) -> float:
        net = sum(float(ln["Amount"]) for ln in payload["Line"])
        tax = float((payload.get("TxnTaxDetail") or {}).get("TotalTax") or 0)
        return round(net + tax, 2)

    def _nom(self, ref: Optional[Dict[str, Any]]) -> Optional[str]:
        if not ref:
            return None
        return next((v["DisplayName"] for v in self.vendors if v["Id"] == ref["value"]), None)

    async def create_purchase(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        if self.refuser_taxes_exactes and "TxnTaxDetail" in payload:
            raise QuickBooksError("QBO refus : Invalid tax rate id — QBO POST /purchase failed: 400")
        self.creations.append(("Purchase", json.loads(json.dumps(payload))))
        txn = {**payload, "Id": str(500 + len(self.creations)), "TotalAmt": self._total(payload)}
        if payload.get("EntityRef"):
            txn["EntityRef"] = {**payload["EntityRef"], "name": self._nom(payload["EntityRef"])}
        self.purchases.append(txn)
        return txn

    async def create_bill(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        self.creations.append(("Bill", json.loads(json.dumps(payload))))
        txn = {
            **payload,
            "Id": str(800 + len(self.creations)),
            "TotalAmt": self._total(payload),
            "VendorRef": {**payload["VendorRef"], "name": self._nom(payload["VendorRef"])},
        }
        self.bills.append(txn)
        return txn

    async def upload_attachment(self, **kw: Any) -> Dict[str, Any]:
        if self.refuser_piece:
            raise QuickBooksError("QBO upload failed: 500 {}")
        self.pieces.append(kw)
        return {"AttachableResponse": [{"Attachable": {"Id": "att-1"}}]}


@pytest.fixture()
def fake_qbo(monkeypatch) -> _FakeQbo:
    fake = _FakeQbo()
    # get_qbo est importé LOCALEMENT dans le service : patcher la source suffit.
    monkeypatch.setattr("app.integrations.quickbooks.get_qbo", lambda scope: fake)
    return fake


@pytest.fixture()
def inc(run) -> Dict[str, Any]:
    """Une inc avec SA compagnie QuickBooks connectée (scope inc:{id})."""

    async def _seed() -> Dict[str, Any]:
        async with TestSessionLocal() as s:
            e = Entreprise(name=f"9999-{uuid.uuid4().hex[:4]} Québec inc.")
            s.add(e)
            await s.flush()
            s.add(
                QboConnection(
                    scope=f"inc:{e.id}",
                    refresh_token="rt-smoke",
                    realm_id="9130",
                    environment="sandbox",
                    company_name="Inc Smoke",
                )
            )
            await s.commit()
            return {"id": e.id, "name": e.name}

    return run(_seed())


def _recu(**extra: Any) -> Dict[str, Any]:
    base = {
        "cle_envoi": uuid.uuid4().hex,
        "type": "paye",
        "date_recu": JOUR,
        "fournisseur_id": "56",
        "compte_paiement_id": "41",
        "mode_paiement_id": "2",
        "categorie_id": "61",
        "code_taxe_id": "5",
        "total": 114.98,
        "taxes": [{"taux_id": "10", "montant": 5.0}, {"taux_id": "11", "montant": 9.98}],
    }
    base.update(extra)
    return base


def _envoyer(client, headers, ent_id: int, recu: Dict[str, Any], *, photo: bool = True):
    files = {"fichier": ("scan.pdf", PDF, "application/pdf")} if photo else None
    return client.post(
        f"/api/v1/recus-qbo/entreprises/{ent_id}/envoyer",
        headers=headers,
        data={"donnees": json.dumps(recu)},
        files=files,
    )


# ── Calculs ──────────────────────────────────────────────────────────


def test_ventilation_du_total_tps_tvq():
    ht, taxes = ventiler(114.98, [5, 9.975])
    assert ht == 100.0
    assert taxes == [5.0, 9.98]
    assert round(ht + sum(taxes), 2) == 114.98
    # Un écart d'arrondi est absorbé par la dernière taxe : total exact.
    ht, taxes = ventiler(10.0, [5, 9.975])
    assert round(ht + sum(taxes), 2) == 10.0
    # Exonéré / sans code : tout est hors taxes.
    assert ventiler(80.0, [0]) == (80.0, [0.0])
    assert ventiler(80.0, []) == (80.0, [])


def test_taxes_saisies_controlees():
    taux = [("10", 5.0), ("11", 9.975)]
    ht, lignes = taxes_du_recu(114.98, taux, None)
    assert ht == 100.0 and [m for _, _, m in lignes] == [5.0, 9.98]
    # Un reçu sans taxes avec le code TPS/TVQ : QBO les ajouterait → refusé.
    with pytest.raises(SaisieErreur):
        taxes_du_recu(100.0, taux, [])
    # Taxes plus grandes que le total : refusé.
    with pytest.raises(SaisieErreur):
        taxes_du_recu(10.0, taux, RecuIn.model_validate(_recu(total=10.0, taxes=[{"taux_id": "10", "montant": 11}])).taxes)


def test_facture_a_payer_exige_un_fournisseur():
    with pytest.raises(ValueError):
        RecuIn.model_validate(_recu(type="a_payer", fournisseur_id=None))


# ── API ─────────────────────────────────────────────────────────────


def test_liste_des_entreprises_et_connexion(client, auth_headers, inc):
    r = client.get("/api/v1/recus-qbo/entreprises", headers=auth_headers)
    assert r.status_code == 200, r.text
    ligne = next(x for x in r.json() if x["entreprise_id"] == inc["id"])
    assert ligne["qbo_connectee"] is True
    assert ligne["qbo_scope"] == f"inc:{inc['id']}"
    assert ligne["qbo_company_name"] == "Inc Smoke"


def test_choix_lus_dans_quickbooks(client, auth_headers, inc, fake_qbo):
    r = client.get(f"/api/v1/recus-qbo/entreprises/{inc['id']}/choix", headers=auth_headers)
    assert r.status_code == 200, r.text
    c = r.json()
    # Fournisseurs triés sans tenir compte des accents.
    assert [f["nom"] for f in c["fournisseurs"]] == ["Bureau en Gros", "Ébénisterie Côté", "Rona"]
    # Comptes de paiement : cartes puis banques ; jamais les autres types.
    assert [(x["id"], x["type"]) for x in c["comptes_paiement"]] == [("41", "carte"), ("35", "banque")]
    # Catégories groupées comme QB ; pas de compte fournisseurs.
    groupes = {x["id"]: x["groupe"] for x in c["categories"]}
    assert groupes == {"60": "Dépenses", "61": "Coût des produits vendus", "62": "Autres comptes"}
    assert next(x for x in c["categories"] if x["id"] == "60")["numero"] == "5200"
    # Codes de taxe d'ACHAT seulement ; TPS/TVQ par défaut.
    codes = {x["id"]: x for x in c["codes_taxe"]}
    assert set(codes) == {"5", "6"}
    assert codes["5"]["defaut"] is True and codes["6"]["defaut"] is False
    assert [t["pourcent"] for t in codes["5"]["taux"]] == [5.0, 9.975]
    # Habitudes : la dernière dépense Rona préremplit catégorie, taxe, carte.
    assert c["habitudes"]["56"] == {
        "type": "paye",
        "categorie_id": "61",
        "code_taxe_id": "5",
        "compte_paiement_id": "41",
        "mode_paiement_id": "2",
    }
    assert [m["nom"] for m in c["modes_paiement"]] == ["Carte de crédit", "Virement"]
    assert c["modalites"] == [{"id": "3", "nom": "Net 30", "jours": 30}]


def test_depense_payee_creee_avec_taxes_exactes_et_photo(client, auth_headers, inc, fake_qbo, run):
    recu = _recu(reference="F-1234", memo="Vis et colle")
    r = _envoyer(client, auth_headers, inc["id"], recu)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["statut"] == "envoye" and out["photo_jointe"] is True
    assert out["txn_type"] == "Purchase"
    assert out["fournisseur"] == "Rona" and out["montant"] == 114.98 and out["date"] == JOUR
    assert out["lien_qbo"].startswith("https://app.sandbox.qbo.intuit.com/app/expense?txnId=")
    assert "deeplinkcompanyid=9130" in out["lien_qbo"]

    entite, payload = fake_qbo.creations[-1]
    assert entite == "Purchase"
    assert payload["PaymentType"] == "CreditCard"  # carte de crédit choisie
    assert payload["AccountRef"] == {"value": "41"}
    assert payload["EntityRef"] == {"value": "56", "type": "Vendor"}
    assert payload["PaymentMethodRef"] == {"value": "2"}
    assert payload["DocNumber"] == "F-1234"
    assert payload["TxnDate"] == JOUR
    assert payload["GlobalTaxCalculation"] == "TaxExcluded"
    ligne = payload["Line"][0]
    assert ligne["Amount"] == 100.0  # hors taxes
    assert ligne["AccountBasedExpenseLineDetail"] == {
        "AccountRef": {"value": "61"},
        "TaxCodeRef": {"value": "5"},
    }
    taxe = payload["TxnTaxDetail"]
    assert taxe["TotalTax"] == 14.98
    assert [(t["TaxLineDetail"]["TaxRateRef"]["value"], t["Amount"]) for t in taxe["TaxLine"]] == [
        ("10", 5.0),
        ("11", 9.98),
    ]
    assert "Vis et colle" in payload["PrivateNote"]
    assert "Saisi dans Kratos par" in payload["PrivateNote"]

    # Photo jointe à CETTE transaction, nommée comme la copie Drive la nommera.
    piece = fake_qbo.pieces[-1]
    assert piece["entity_type"] == "Purchase" and piece["entity_id"] == out["txn_id"]
    assert piece["file_name"] == "2026-10-03 Rona 114,98$.pdf"
    assert piece["content"] == PDF

    # Trace minimale : ni montant ni fournisseur, juste qui / quoi / quand.
    async def _trace():
        async with TestSessionLocal() as s:
            return await s.get(RecuQboSaisi, out["saisie_id"])

    t = run(_trace())
    assert t.statut == "envoye" and t.txn_id == out["txn_id"] and t.realm_id == "9130"
    assert t.entreprise_id == inc["id"] and t.user_id is not None

    # Même clé (double-clic) : le premier résultat, aucune 2e dépense.
    n = len(fake_qbo.creations)
    r2 = _envoyer(client, auth_headers, inc["id"], recu)
    assert r2.status_code == 200, r2.text
    assert r2.json()["deja_envoye"] is True and r2.json()["txn_id"] == out["txn_id"]
    assert len(fake_qbo.creations) == n


def test_doublon_dans_quickbooks_demande_confirmation(client, auth_headers, inc, fake_qbo):
    fake_qbo.purchases.append(
        {"Id": "301", "TxnDate": JOUR, "TotalAmt": 114.98, "EntityRef": {"value": "56", "name": "Rona"}}
    )
    recu = _recu()
    r = _envoyer(client, auth_headers, inc["id"], recu)
    assert r.status_code == 409, r.text
    assert r.json()["doublon"]["txn_id"] == "301"
    assert r.json()["doublon"]["fournisseur"] == "Rona"
    assert r.json()["doublon"]["lien_qbo"].endswith("/app/expense?txnId=301&deeplinkcompanyid=9130")
    assert fake_qbo.creations == []
    # « Envoyer quand même » avec la MÊME clé : la clé a été libérée.
    r2 = _envoyer(client, auth_headers, inc["id"], {**recu, "forcer_doublon": True})
    assert r2.status_code == 200, r2.text
    assert len(fake_qbo.creations) == 1


def test_autre_fournisseur_meme_montant_n_est_pas_un_doublon(client, auth_headers, inc, fake_qbo):
    fake_qbo.purchases.append(
        {"Id": "302", "TxnDate": JOUR, "TotalAmt": 114.98, "EntityRef": {"value": "58", "name": "Bureau en Gros"}}
    )
    r = _envoyer(client, auth_headers, inc["id"], _recu())
    assert r.status_code == 200, r.text


def test_fournisseur_inconnu_part_sans_beneficiaire_nom_nd(client, auth_headers, inc, fake_qbo):
    r = _envoyer(
        client,
        auth_headers,
        inc["id"],
        _recu(fournisseur_id=None, compte_paiement_id="35", mode_paiement_id=None, total=20.0, taxes=None),
    )
    assert r.status_code == 200, r.text
    _, payload = fake_qbo.creations[-1]
    assert "EntityRef" not in payload
    assert payload["PaymentType"] == "Cash"  # compte bancaire
    # Taxes calculées depuis le total quand le formulaire ne les envoie pas.
    assert round(payload["Line"][0]["Amount"] + payload["TxnTaxDetail"]["TotalTax"], 2) == 20.0
    assert fake_qbo.pieces[-1]["file_name"] == "2026-10-03 ND 20,00$.pdf"


def test_facture_a_payer_nouveau_fournisseur(client, auth_headers, inc, fake_qbo):
    recu = _recu(
        type="a_payer",
        fournisseur_id=None,
        nouveau_fournisseur="Plomberie Roy",
        compte_paiement_id=None,
        mode_paiement_id=None,
        modalite_id="3",
        date_echeance="2026-11-02",
        code_taxe_id="6",
        taxes=[{"taux_id": "12", "montant": 0}],
        total=450.0,
    )
    r = _envoyer(client, auth_headers, inc["id"], recu)
    assert r.status_code == 200, r.text
    assert r.json()["txn_type"] == "Bill"
    assert r.json()["lien_qbo"].startswith("https://app.sandbox.qbo.intuit.com/app/bill?txnId=")
    entite, payload = fake_qbo.creations[-1]
    assert entite == "Bill"
    nouveau = next(v for v in fake_qbo.vendors if v["DisplayName"] == "Plomberie Roy")
    assert payload["VendorRef"] == {"value": nouveau["Id"]}
    assert payload["SalesTermRef"] == {"value": "3"}
    assert payload["DueDate"] == "2026-11-02"
    assert payload["Line"][0]["Amount"] == 450.0
    assert "TxnTaxDetail" not in payload  # exonéré : aucune taxe
    assert "AccountRef" not in payload and "PaymentType" not in payload
    assert fake_qbo.pieces[-1]["file_name"] == "2026-10-03 Plomberie Roy 450,00$.pdf"


def test_facture_a_payer_sans_fournisseur_refusee(client, auth_headers, inc, fake_qbo):
    r = _envoyer(
        client, auth_headers, inc["id"], _recu(type="a_payer", fournisseur_id=None, compte_paiement_id=None)
    )
    assert r.status_code == 422, r.text
    assert "fournisseur" in r.json()["detail"]
    assert fake_qbo.creations == []


def test_compte_de_paiement_doit_etre_banque_ou_carte(client, auth_headers, inc, fake_qbo):
    r = _envoyer(client, auth_headers, inc["id"], _recu(compte_paiement_id="60"))
    assert r.status_code == 422, r.text
    assert fake_qbo.creations == []


def test_taxes_exactes_refusees_repli_calcul_qbo(client, auth_headers, inc, fake_qbo):
    fake_qbo.refuser_taxes_exactes = True
    r = _envoyer(client, auth_headers, inc["id"], _recu())
    assert r.status_code == 200, r.text
    _, payload = fake_qbo.creations[-1]
    assert "TxnTaxDetail" not in payload
    assert payload["Line"][0]["Amount"] == 100.0


def test_photo_refusee_puis_reprise_seule(client, auth_headers, inc, fake_qbo):
    fake_qbo.refuser_piece = True
    r = _envoyer(client, auth_headers, inc["id"], _recu())
    assert r.status_code == 200, r.text
    out = r.json()
    # La dépense est créée ; la photo est à reprendre.
    assert out["statut"] == "photo_a_reprendre" and out["erreur_photo"]
    assert len(fake_qbo.creations) == 1

    fake_qbo.refuser_piece = False
    r2 = client.post(
        f"/api/v1/recus-qbo/saisies/{out['saisie_id']}/photo",
        headers=auth_headers,
        files={"fichier": ("scan.pdf", PDF, "application/pdf")},
    )
    assert r2.status_code == 200, r2.text
    assert r2.json()["statut"] == "envoye"
    assert fake_qbo.pieces[-1]["entity_id"] == out["txn_id"]
    assert len(fake_qbo.creations) == 1  # aucune deuxième dépense

    journal = client.get(
        f"/api/v1/recus-qbo/journal?entreprise_id={inc['id']}", headers=auth_headers
    ).json()
    assert journal[0]["saisie_id"] == out["saisie_id"]
    assert journal[0]["statut"] == "envoye"
    assert journal[0]["entreprise"] == inc["name"]
    assert journal[0]["par"]
    assert journal[0]["lien_qbo"]


def test_format_de_fichier_refuse(client, auth_headers, inc, fake_qbo):
    r = client.post(
        f"/api/v1/recus-qbo/entreprises/{inc['id']}/envoyer",
        headers=auth_headers,
        data={"donnees": json.dumps(_recu())},
        files={"fichier": ("page.html", b"<html>", "text/html")},
    )
    assert r.status_code == 415, r.text
    assert fake_qbo.creations == []


def test_inc_sans_quickbooks(client, auth_headers, fake_qbo, run):
    async def _seed() -> int:
        async with TestSessionLocal() as s:
            e = Entreprise(name=f"Sans QB {uuid.uuid4().hex[:4]}")
            s.add(e)
            await s.commit()
            return e.id

    ent_id = run(_seed())
    r = client.get(f"/api/v1/recus-qbo/entreprises/{ent_id}/choix", headers=auth_headers)
    assert r.status_code == 409, r.text
    assert "QuickBooks" in r.json()["detail"]


def test_page_reservee_a_la_direction_par_defaut(client, run, inc, fake_qbo):
    """Un employé qui a le pôle Entreprises mais pas la page « Reçus »
    (seuil admin par défaut) ne peut ni lire les listes ni envoyer."""

    async def _seed() -> int:
        async with TestSessionLocal() as s:
            u = User(
                email=f"smoke-recus-{uuid.uuid4().hex[:8]}@example.com",
                hashed_password=get_password_hash("smoke-recus-x"),
                is_active=True,
                is_admin=False,
                role="employee",
                volets_json=json.dumps(["entreprises"]),
            )
            s.add(u)
            await s.commit()
            return u.id

    headers = {"Authorization": f"Bearer {create_access_token(subject=str(run(_seed())))}"}
    r = client.get(f"/api/v1/recus-qbo/entreprises/{inc['id']}/choix", headers=headers)
    # Refus de la PAGE (le pôle, lui, est accordé).
    assert r.status_code == 403 and r.json()["detail"] != "Accès au pôle non autorisé.", r.text
    assert _envoyer(client, headers, inc["id"], _recu()).status_code == 403
    assert fake_qbo.creations == []


def test_trace_sans_montant_ni_fournisseur():
    colonnes = set(RecuQboSaisi.__table__.columns.keys())
    assert not colonnes & {"montant", "total", "fournisseur", "fichier", "contenu"}
    assert date  # import utilisé
