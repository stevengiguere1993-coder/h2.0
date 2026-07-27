"""Smoke — facture MENSUELLE ouverte QuickBooks (2026-07-27).

Le « débit différé » voulu par Phil n'existe pas dans l'API Intuit →
équivalent : chaque clic de facturation AJOUTE une ligne à LA facture du
mois du client. Vérifie avec un faux client QBO :

1. premier clic du mois → création (created=True) + ligne en table ;
2. deuxième clic → append sur la MÊME facture (created=False), les
   lignes existantes sont préservées et les champs read-only retirés ;
3. facture payée (Balance < TotalAmt) → nouvelle facture démarrée ;
4. facture envoyée (EmailStatus=EmailSent) → nouvelle facture aussi ;
5. facture supprimée dans QBO (404 object not found) → recréation ;
6. collision de DocNumber (6140) → retry avec numéro incrémenté.
"""
from typing import Any, Dict, List

from sqlalchemy import delete, select

from app.integrations.quickbooks import QuickBooksError
from app.models.qbo_monthly_invoice import QboMonthlyInvoice
from app.services.qbo_monthly_invoice import add_lines_to_monthly_invoice

from tests.smoke.conftest import TestSessionLocal


def _ligne(desc: str, montant: float) -> Dict[str, Any]:
    return {
        "DetailType": "SalesItemLineDetail",
        "Amount": montant,
        "Description": desc,
        "SalesItemLineDetail": {
            "ItemRef": {"value": "1"},
            "Qty": 1,
            "UnitPrice": montant,
            "TaxCodeRef": {"value": "5"},
        },
    }


class FakeQbo:
    """Simule le strict nécessaire de QuickBooksClient : query (DocNumber),
    get_invoice, create_invoice (create + full update)."""

    scope = "entreprise"
    realm_id = "realm-test"

    def __init__(self) -> None:
        self.invoices: Dict[str, Dict[str, Any]] = {}
        self._next_id = 1
        self.doc_numbers_taken: set = set()

    async def query(self, q: str) -> List[Dict[str, Any]]:
        assert "DocNumber" in q
        return [{"DocNumber": inv.get("DocNumber")} for inv in self.invoices.values()]

    async def get_invoice(self, invoice_id: str) -> Dict[str, Any]:
        inv = self.invoices.get(str(invoice_id))
        if inv is None:
            raise QuickBooksError("QBO 400: Object Not Found (code 610)")
        return {"Invoice": dict(inv)}

    async def create_invoice(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        if payload.get("Id"):  # full update
            # Un update ne doit JAMAIS renvoyer les champs read-only
            # qu'on strippe (sinon QBO le refuserait).
            for champ in ("TotalAmt", "Balance", "MetaData", "TxnTaxDetail"):
                assert champ not in payload, f"{champ} envoyé dans l'update"
            inv = self.invoices[str(payload["Id"])]
            inv["Line"] = payload["Line"]
            return {"Invoice": dict(inv)}
        doc = payload.get("DocNumber")
        if doc and doc in self.doc_numbers_taken:
            raise QuickBooksError("Duplicate Document Number Error (code 6140)")
        inv = dict(payload)
        inv["Id"] = str(self._next_id)
        self._next_id += 1
        if doc:
            self.doc_numbers_taken.add(doc)
        inv.setdefault("TotalAmt", sum(l["Amount"] for l in payload["Line"]))
        inv["Balance"] = inv["TotalAmt"]
        inv["EmailStatus"] = "NotSet"
        self.invoices[inv["Id"]] = inv
        return {"Invoice": dict(inv)}


def _purge(run):
    async def _do():
        async with TestSessionLocal() as s:
            await s.execute(delete(QboMonthlyInvoice))
            await s.commit()

    run(_do())


def _add(run, qbo, lines):
    async def _do():
        async with TestSessionLocal() as s:
            out = await add_lines_to_monthly_invoice(
                s,
                qbo,
                scope=qbo.scope,
                customer_id="42",
                lines=lines,
                private_note="Créé par Kratos — test",
            )
            await s.commit()
            return out

    return run(_do())


def _rows(run):
    async def _do():
        async with TestSessionLocal() as s:
            return (
                (await s.execute(select(QboMonthlyInvoice))).scalars().all()
            )

    return run(_do())


def test_premier_clic_cree_la_facture_du_mois(run, db_setup):
    _purge(run)
    qbo = FakeQbo()
    out = _add(run, qbo, [_ligne("Frais de gestion", 100.0)])
    assert out["created"] is True
    assert out["invoice_id"] == "1"
    assert out["doc_number"] == "1000"  # aucune facture → départ à 1000
    rows = _rows(run)
    assert len(rows) == 1
    assert rows[0].realm_id == "realm-test"
    assert rows[0].qbo_invoice_id == "1"
    assert rows[0].mois.day == 1


def test_deuxieme_clic_greffe_sur_la_meme_facture(run, db_setup):
    _purge(run)
    qbo = FakeQbo()
    _add(run, qbo, [_ligne("Frais de gestion", 100.0)])
    out2 = _add(run, qbo, [_ligne("Relocation log. 2", 250.0)])
    assert out2["created"] is False
    assert out2["invoice_id"] == "1"  # même facture
    inv = qbo.invoices["1"]
    assert len(inv["Line"]) == 2  # lignes cumulées
    assert [l["Amount"] for l in inv["Line"]] == [100.0, 250.0]
    assert len(_rows(run)) == 1  # toujours une seule ligne en table


def test_facture_payee_en_demarre_une_nouvelle(run, db_setup):
    _purge(run)
    qbo = FakeQbo()
    _add(run, qbo, [_ligne("Frais de gestion", 100.0)])
    # Paiement (même partiel) appliqué dans QBO → verrou.
    qbo.invoices["1"]["Balance"] = 40.0
    out2 = _add(run, qbo, [_ligne("Frais manuel", 60.0)])
    assert out2["created"] is True
    assert out2["invoice_id"] == "2"
    assert len(qbo.invoices["1"]["Line"]) == 1  # l'ancienne n'a pas bougé
    rows = _rows(run)
    assert len(rows) == 1  # ligne REMPLACÉE (même mois → nouvel id)
    assert rows[0].qbo_invoice_id == "2"


def test_facture_envoyee_en_demarre_une_nouvelle(run, db_setup):
    _purge(run)
    qbo = FakeQbo()
    _add(run, qbo, [_ligne("Frais de gestion", 100.0)])
    qbo.invoices["1"]["EmailStatus"] = "EmailSent"
    out2 = _add(run, qbo, [_ligne("Frais manuel", 60.0)])
    assert out2["created"] is True
    assert out2["invoice_id"] == "2"


def test_facture_supprimee_dans_qbo_est_recreee(run, db_setup):
    _purge(run)
    qbo = FakeQbo()
    _add(run, qbo, [_ligne("Frais de gestion", 100.0)])
    del qbo.invoices["1"]  # supprimée à la main dans QuickBooks
    out2 = _add(run, qbo, [_ligne("Frais manuel", 60.0)])
    assert out2["created"] is True
    assert out2["invoice_id"] == "2"
    assert _rows(run)[0].qbo_invoice_id == "2"


def test_collision_doc_number_retry(run, db_setup):
    _purge(run)
    qbo = FakeQbo()
    qbo.doc_numbers_taken.add("1000")  # 1000 déjà pris → 6140 → retry 1001
    out = _add(run, qbo, [_ligne("Frais de gestion", 100.0)])
    assert out["created"] is True
    assert out["doc_number"] == "1001"
