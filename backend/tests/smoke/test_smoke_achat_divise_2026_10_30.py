"""Smoke — reçu DIVISÉ entre plusieurs projets, miroir dans QuickBooks
(Steven, 2026-10-30 : « une coche pour dire que deux projets différents
sont touchés par la facture et séparer le montant qui va dans chacun ;
miroir dans QB, enregistré sur plusieurs projets »).

Faux QuickBooks, aucun appel réseau. Couvre :
1. POST /achats/divise → un achat par projet (HT, taxes, TPS, TVQ au
   prorata du TTC de la part), liés par groupe_id ; le push automatique
   crée UN Bill à DEUX lignes (CustomerRef = projet de la part, taxes du
   reçu entier) dont l'Id est posé sur les deux parts ;
2. re-push d'une part → mise à jour du même Bill (deux lignes), jamais
   une 2e transaction ; /parts ; dédoublonnage inoffensif ;
3. mark-paid sur une part → les deux parts payées, UNE BillPayment du
   total du groupe ;
4. reçu téléversé sur une part → présent sur l'autre ;
5. suppression d'une part → le Bill est réécrit avec la part restante ;
6. mode « carte de crédit » → UNE dépense (Purchase) à deux lignes ;
7. saisies invalides refusées (somme, projets) ;
8. (contestation 2026-10-30) toute transaction QB déjà liée est mise à
   jour en ENTIER (jamais « sparse », dont QuickBooks ignore les lignes —
   le faux QB se comporte comme la vraie compagnie) et les lignes
   renvoyées sont vérifiées ; annulation d'une part → sa ligne sort de la
   facture QB tout de suite et la part perd son lien ; refus QB → 409,
   rien n'est annulé ; une part ne prend pas le projet d'une sœur ;
   dédup : un doublon simple est absorbé par le groupe (jamais une part
   supprimée), deux groupes identiques → le plus ancien reste, deux
   groupes différents → rien ; « à refacturer » et heures par part ;
   paiement d'une part → statut du groupe ; webhook sur toutes les parts.
"""

from __future__ import annotations

import asyncio
import copy
import uuid
from typing import Any, Dict, List, Optional

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.integrations.quickbooks import QuickBooksError
from app.models.achat import Achat
from app.models.client import Client
from app.models.fournisseur import Fournisseur
from app.models.project import Project
from app.models.qbo_account_map import QboAccountMap
from app.services.achat_dedupe import dedupe_achats
from app.services.achat_qbo import (
    AchatSyncError,
    push_bill_payment_to_qbo,
    sync_achat_to_qbo,
)

from .conftest import TestSessionLocal

PDF = b"%PDF-1.4 recu divise smoke"

TAXES = {
    "10": {"Id": "10", "Name": "TPS (CTI)", "RateValue": 5},
    "11": {"Id": "11", "Name": "TVQ (RTI)", "RateValue": 9.975},
}
CODE_TPS_TVQ = {
    "Id": "5",
    "Name": "TPS/TVQ QC - 9,975",
    "PurchaseTaxRateList": {
        "TaxRateDetail": [
            {"TaxRateRef": {"value": "10"}},
            {"TaxRateRef": {"value": "11"}},
        ]
    },
}


class _FauxQB:
    """Double de QuickBooks pour le push d'un achat : fournisseurs,
    clients / sous-clients, comptes, taxes, Bill / Purchase / BillPayment,
    pièces jointes. Mémorise créations et mises à jour."""

    ready = True
    realm_id = "9130"

    def __init__(self, *, parent_id: str, jobs: Dict[str, str]) -> None:
        self.parent_id = parent_id
        # Sous-clients QB (projets) : id → nom.
        self.jobs = jobs
        self.vendors: Dict[str, Dict[str, Any]] = {}
        self.bills: Dict[str, Dict[str, Any]] = {}
        self.purchases: Dict[str, Dict[str, Any]] = {}
        self.bill_payments: List[Dict[str, Any]] = []
        self.creations: List[tuple] = []
        self.updates: List[tuple] = []
        self.pieces: List[Dict[str, Any]] = []
        self._seq = 100
        self._marque = uuid.uuid4().hex[:4]
        #: Simule une compagnie qui ignore les lignes même en mise à jour
        #: complète (pour prouver que le push détecte l'écart).
        self.ignorer_lignes = False
        #: Message d'erreur à renvoyer à toute mise à jour (facture payée,
        #: rapprochée…).
        self.erreur_maj: Optional[str] = None

    def _next(self, prefix: str) -> str:
        self._seq += 1
        return f"{prefix}{self._marque}-{self._seq}"

    async def _load_refresh_from_db(self) -> None:
        return None

    # ── Référentiels ──
    async def ensure_vendor(self, *, display_name: str, **_: Any) -> Dict[str, Any]:
        v = next((v for v in self.vendors.values() if v["DisplayName"] == display_name), None)
        if v is None:
            v = {"Id": self._next("V"), "DisplayName": display_name}
            self.vendors[v["Id"]] = v
        return v

    async def ensure_customer(self, *, display_name: str, **_: Any) -> Dict[str, Any]:
        return {"Id": self.parent_id, "DisplayName": display_name}

    async def get_customer(self, customer_id: str) -> Optional[Dict[str, Any]]:
        name = self.jobs.get(customer_id)
        if name is None:
            return None
        return {
            "Id": customer_id,
            "DisplayName": name,
            "FullyQualifiedName": f"Client:{name}",
            "ParentRef": {"value": self.parent_id},
            "Active": True,
        }

    async def find_subcustomers(self, parent_id: str) -> List[Dict[str, Any]]:
        return [await self.get_customer(j) for j in self.jobs]

    async def ensure_class(self, *, name: str) -> Optional[Dict[str, Any]]:
        return {"Id": "K-construction", "Name": name}

    async def ensure_payment_method(self, *, name: str) -> Dict[str, Any]:
        return {"Id": "PM-cc", "Name": name}

    async def find_account_by_name(self, name: str) -> Optional[Dict[str, Any]]:
        return {
            "Matériaux": {"Id": "60", "Name": "Matériaux", "AccountType": "Cost of Goods Sold"},
            "Visa Steven": {"Id": "41", "Name": "Visa Steven", "AccountType": "Credit Card"},
        }.get(name)

    async def first_expense_account(self) -> Optional[Dict[str, Any]]:
        return {"Id": "60", "Name": "Matériaux"}

    async def get_tax_code(self, code_id: str) -> Optional[Dict[str, Any]]:
        return CODE_TPS_TVQ if code_id == "5" else None

    async def get_tax_rate(self, rate_id: str) -> Optional[Dict[str, Any]]:
        return TAXES.get(rate_id)

    # ── Recherches anti-doublon ──
    async def find_txn_by_docnumber(self, entity: str, doc_number: str) -> Optional[Dict[str, Any]]:
        rows = self.bills if entity == "Bill" else self.purchases
        return next((copy.deepcopy(t) for t in rows.values() if t.get("DocNumber") == doc_number), None)

    async def find_existing_bill(self, **_: Any) -> Optional[Dict[str, Any]]:
        return None

    async def find_existing_purchase(self, **_: Any) -> Optional[Dict[str, Any]]:
        return None

    async def query(self, sql: str) -> List[Dict[str, Any]]:
        if "FROM Purchase" in sql and "DocNumber = '" in sql:
            doc = sql.split("DocNumber = '", 1)[1].split("'", 1)[0]
            return [copy.deepcopy(p) for p in self.purchases.values() if p.get("DocNumber") == doc]
        return []

    # ── Transactions ──
    @staticmethod
    def _total(payload: Dict[str, Any]) -> float:
        net = sum(float(ln["Amount"]) for ln in payload["Line"])
        tax = float((payload.get("TxnTaxDetail") or {}).get("TotalTax") or 0)
        return round(net + tax, 2)

    def _store(self, store: Dict[str, Dict[str, Any]], payload: Dict[str, Any], prefix: str) -> Dict[str, Any]:
        txn = copy.deepcopy(payload)
        txn["Id"] = self._next(prefix)
        txn["SyncToken"] = "0"
        txn["TotalAmt"] = self._total(payload)
        txn["Balance"] = txn["TotalAmt"]
        store[txn["Id"]] = txn
        return copy.deepcopy(txn)

    def _update(self, store: Dict[str, Dict[str, Any]], payload: Dict[str, Any]) -> Dict[str, Any]:
        cur = store.get(str(payload.get("Id")))
        if cur is None:
            raise QuickBooksError("Object Not Found : Something you're trying to use has been made inactive (id)")
        if self.erreur_maj:
            raise QuickBooksError(self.erreur_maj)
        if str(payload.get("SyncToken")) != str(cur["SyncToken"]):
            raise QuickBooksError("Stale Object Error : SyncToken")
        p = copy.deepcopy(payload)
        paye = round(float(cur["TotalAmt"]) - float(cur["Balance"]), 2)
        if p.get("sparse") or self.ignorer_lignes:
            # Comme la vraie compagnie (Invoice 120, 2026-10-14) : une mise
            # à jour « sparse » accepte la requête mais laisse les LIGNES
            # telles quelles.
            p.pop("Line", None)
            p.pop("TxnTaxDetail", None)
        else:
            # Mise à jour complète : jamais de champ calculé dans le corps.
            for champ in ("TotalAmt", "Balance", "MetaData"):
                assert champ not in p, f"{champ} renvoyé dans la mise à jour complète"
        cur.update({k: v for k, v in p.items() if k != "sparse"})
        cur["SyncToken"] = str(int(cur["SyncToken"]) + 1)
        cur["TotalAmt"] = self._total(cur)
        cur["Balance"] = round(cur["TotalAmt"] - paye, 2)
        return copy.deepcopy(cur)

    async def get_bill(self, bill_id: str) -> Dict[str, Any]:
        if bill_id not in self.bills:
            raise QuickBooksError("Object Not Found : Bill")
        return copy.deepcopy(self.bills[bill_id])

    async def get_purchase(self, purchase_id: str) -> Dict[str, Any]:
        if purchase_id not in self.purchases:
            raise QuickBooksError("Object Not Found : Purchase")
        return copy.deepcopy(self.purchases[purchase_id])

    async def create_bill(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        self.creations.append(("Bill", copy.deepcopy(payload)))
        return self._store(self.bills, payload, "B")

    async def update_bill(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        self.updates.append(("Bill", copy.deepcopy(payload)))
        return self._update(self.bills, payload)

    async def delete_bill(self, bill_id: str) -> bool:
        return self.bills.pop(bill_id, None) is not None

    async def create_purchase(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        self.creations.append(("Purchase", copy.deepcopy(payload)))
        return self._store(self.purchases, payload, "P")

    async def update_purchase(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        self.updates.append(("Purchase", copy.deepcopy(payload)))
        return self._update(self.purchases, payload)

    async def delete_purchase(self, purchase_id: str) -> bool:
        return self.purchases.pop(purchase_id, None) is not None

    async def create_bill_payment(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        bp = {**copy.deepcopy(payload), "Id": self._next("BP")}
        self.bill_payments.append(bp)
        for ligne in payload["Line"]:
            for lien in ligne["LinkedTxn"]:
                b = self.bills[lien["TxnId"]]
                b["Balance"] = round(b["Balance"] - float(ligne["Amount"]), 2)
        return bp

    async def upload_attachment(self, **kw: Any) -> Dict[str, Any]:
        self.pieces.append(kw)
        return {"AttachableResponse": [{"Attachable": {"Id": "att-1"}}]}


# ── Fixtures ─────────────────────────────────────────────────────────


@pytest.fixture()
def chantiers(run, db_setup) -> dict:
    """Un client, deux chantiers reliés à leur sous-client QB, un
    fournisseur classé « Matériaux », le mapping des comptes QB."""
    tag = uuid.uuid4().hex[:8]

    async def _go() -> dict:
        async with TestSessionLocal() as s:
            cl = Client(name=f"Client divisé {tag}", qbo_customer_id=f"C-{tag}")
            s.add(cl)
            await s.flush()
            a = Project(
                name=f"Chantier A {tag}", client_id=cl.id,
                address=f"{tag} rue Division A", qbo_job_id=f"JA-{tag}",
            )
            b = Project(
                name=f"Chantier B {tag}", client_id=cl.id,
                address=f"{tag} rue Division B", qbo_job_id=f"JB-{tag}",
            )
            f = Fournisseur(
                name=f"Rona Division {tag}", qbo_expense_account="Matériaux",
                payment_terms_days=30,
            )
            s.add_all([a, b, f])
            await s.flush()
            await s.merge(
                QboAccountMap(
                    id=1, default_expense_account="Matériaux",
                    cc_steven_account="Visa Steven",
                )
            )
            await s.commit()
            return {
                "tag": tag, "client": cl.id, "a": a.id, "b": b.id,
                "job_a": a.qbo_job_id, "job_b": b.qbo_job_id,
                "fournisseur": f.id, "parent": f"C-{tag}",
            }

    return run(_go())


@pytest.fixture()
def faux_qb(monkeypatch, chantiers) -> _FauxQB:
    fake = _FauxQB(
        parent_id=chantiers["parent"],
        jobs={
            chantiers["job_a"]: f"Chantier A {chantiers['tag']}",
            chantiers["job_b"]: f"Chantier B {chantiers['tag']}",
        },
    )
    # get_qbo est importé au niveau du module dans achat_qbo.
    monkeypatch.setattr("app.services.achat_qbo.get_qbo", lambda *a, **k: fake)
    # Code de taxe d'achat configuré → lignes HT + TxnTaxDetail exact.
    monkeypatch.setattr(settings, "qbo_purchase_tax_code", "5")
    return fake


def _achats(run, ids: List[int]) -> List[Achat]:
    async def _go() -> List[Achat]:
        async with TestSessionLocal() as s:
            return list(
                (await s.execute(select(Achat).where(Achat.id.in_(ids)).order_by(Achat.id)))
                .scalars().all()
            )

    return run(_go())


def _corps(ch: dict, **extra: Any) -> Dict[str, Any]:
    base: Dict[str, Any] = {
        "fournisseur_id": ch["fournisseur"],
        "description": "Bois traité et gypse",
        "amount": 1000.0,
        "amount_taxes": 149.75,
        "amount_tps": 50.0,
        "amount_tvq": 99.75,
        "supplier_invoice_number": f"RD-{ch['tag']}",
        "invoice_date": "2026-10-28",
        "payment_method": "bill_to_pay",
        "status": "received",
        "kind": "material",
        "parts": [
            {"project_id": ch["a"], "total": 689.85},
            {"project_id": ch["b"], "total": 459.90},
        ],
    }
    base.update(extra)
    return base


def _attendre(run, cond, essais: int = 100) -> None:
    """Laisse tourner les tâches de fond (asyncio.create_task) jusqu'à ce
    que ``cond()`` soit vraie."""
    for _ in range(essais):
        if cond():
            return
        run(asyncio.sleep(0.02))
    assert cond(), "la tâche de fond n'a pas abouti"


def _f(v) -> Optional[float]:
    return None if v is None else float(v)


def _lignes(txn: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [
        ln for ln in txn["Line"]
        if ln.get("DetailType") == "AccountBasedExpenseLineDetail"
    ]


# ── 1-2) Création divisée → UN Bill à deux lignes ; re-push ; /parts ──


def test_recu_divise_deux_projets_un_bill_deux_lignes(
    client, auth_headers, run, chantiers, faux_qb
):
    ch = chantiers
    res = client.post(
        "/api/v1/achats/divise", headers=auth_headers,
        json=_corps(ch, is_billable=True, markup_percent=10),
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert len(body["parts"]) == 2
    tete, autre = body["parts"]
    assert body["groupe_id"] == tete["id"]
    assert tete["groupe_id"] == autre["groupe_id"] == tete["id"]
    assert (tete["project_id"], autre["project_id"]) == (ch["a"], ch["b"])
    # Montants au prorata du TTC de chaque part (60 % / 40 %), sommes exactes.
    assert (tete["amount"], tete["amount_taxes"], tete["amount_tps"], tete["amount_tvq"]) == (
        600.0, 89.85, 30.0, 59.85,
    )
    assert (autre["amount"], autre["amount_taxes"], autre["amount_tps"], autre["amount_tvq"]) == (
        400.0, 59.9, 20.0, 39.9,
    )
    for p in body["parts"]:
        assert p["status"] == "received"
        assert p["is_billable"] is True and p["billable_manual"] is True
        assert p["supplier_invoice_number"] == f"RD-{ch['tag']}"
        assert p["payment_method"] == "bill_to_pay"
        assert p["due_at"] is not None

    # Push automatique (tâche de fond, après le commit) : UN Bill.
    _attendre(run, lambda: len(faux_qb.creations) >= 1)
    assert [t for t, _ in faux_qb.creations] == ["Bill"]
    bill = next(iter(faux_qb.bills.values()))
    lignes = _lignes(bill)
    assert len(lignes) == 2
    assert [ln["Amount"] for ln in lignes] == [600.0, 400.0]
    assert [ln["AccountBasedExpenseLineDetail"]["CustomerRef"]["value"] for ln in lignes] == [
        ch["job_a"], ch["job_b"],
    ]
    assert all(ln["AccountBasedExpenseLineDetail"]["BillableStatus"] == "Billable" for ln in lignes)
    assert all(ln["AccountBasedExpenseLineDetail"]["ClassRef"]["value"] == "K-construction" for ln in lignes)
    assert all(ln["AccountBasedExpenseLineDetail"]["AccountRef"]["value"] == "60" for ln in lignes)
    assert f"Chantier A {ch['tag']}" in lignes[0]["Description"]
    assert f"Chantier B {ch['tag']}" in lignes[1]["Description"]
    # Taxes du reçu ENTIER, total QB = TTC du reçu.
    assert bill["TxnTaxDetail"]["TotalTax"] == 149.75
    assert [tl["Amount"] for tl in bill["TxnTaxDetail"]["TaxLine"]] == [50.0, 99.75]
    assert bill["TotalAmt"] == 1149.75
    assert bill["DocNumber"] == f"RD-{ch['tag']}"
    assert bill["PrivateNote"].startswith(f"Source: Horizon h2.0 Achat #{tete['id']}")
    assert f"Parts: #{tete['id']}, #{autre['id']}" in bill["PrivateNote"]
    assert f"Projets: Chantier A {ch['tag']}, Chantier B {ch['tag']}" in bill["PrivateNote"]

    # L'Id QB est posé sur les DEUX parts.
    parts = _achats(run, [tete["id"], autre["id"]])
    assert [p.qbo_bill_id for p in parts] == [bill["Id"], bill["Id"]]
    assert [p.qbo_doc_number for p in parts] == [bill["DocNumber"]] * 2

    # Re-push par l'AUTRE part → mise à jour du MÊME Bill, deux lignes,
    # aucune 2e création.
    async def _repush() -> dict:
        async with TestSessionLocal() as s:
            out = await sync_achat_to_qbo(s, autre["id"])
            await s.commit()
            return out

    out = run(_repush())
    assert out["qbo_bill_id"] == bill["Id"]
    assert sorted(out["parts"]) == [tete["id"], autre["id"]]
    assert len(faux_qb.creations) == 1
    assert [t for t, _ in faux_qb.updates] == ["Bill"]
    maj = faux_qb.updates[-1][1]
    # Mise à jour COMPLÈTE (jamais sparse : QB ignorerait les lignes), sans
    # champ calculé, avec le SyncToken relu.
    assert maj["Id"] == bill["Id"] and maj.get("sparse") is False
    assert "TotalAmt" not in maj and "Balance" not in maj
    assert maj["SyncToken"] == "0"
    assert [ln["Amount"] for ln in _lignes(maj)] == [600.0, 400.0]
    assert len(faux_qb.bills) == 1

    # /parts : origine Kratos, deux parts, total = somme, rien resté dans QB.
    pr = client.get(f"/api/v1/achats/{autre['id']}/parts", headers=auth_headers)
    assert pr.status_code == 200, pr.text
    pj = pr.json()
    assert pj["origine"] == "kratos" and pj["groupe_id"] == tete["id"]
    assert [p["id"] for p in pj["parts"]] == [tete["id"], autre["id"]]
    assert pj["total_kratos"] == 1149.75 and pj["qbo_total"] == 1149.75
    assert pj["reste_qb"] is None
    assert pj["qbo_id"] == bill["Id"]

    # Dédoublonnage : même fournisseur + même n° de facture + même Id QB,
    # mais parts d'un même reçu → jamais fusionnées.
    async def _dedupe() -> int:
        async with TestSessionLocal() as s:
            n = await dedupe_achats(s)
            await s.commit()
            return n

    run(_dedupe())
    assert len(_achats(run, [tete["id"], autre["id"]])) == 2
    assert len(faux_qb.bills) == 1

    # Liste : les deux parts exposent groupe_id (badge « divisée »).
    lst = client.get("/api/v1/achats?limit=500", headers=auth_headers)
    assert lst.status_code == 200
    par_id = {a["id"]: a for a in lst.json()}
    assert par_id[tete["id"]]["groupe_id"] == par_id[autre["id"]]["groupe_id"] == tete["id"]


# ── 3) Paiement : tout le groupe, UNE BillPayment du total ───────────


def test_mark_paid_sur_une_part_paie_tout_le_groupe(
    client, auth_headers, run, chantiers, faux_qb
):
    res = client.post("/api/v1/achats/divise", headers=auth_headers, json=_corps(chantiers))
    assert res.status_code == 201, res.text
    tete, autre = res.json()["parts"]
    _attendre(run, lambda: len(faux_qb.bills) == 1)
    bill_id = next(iter(faux_qb.bills))

    mp = client.post(
        f"/api/v1/achats/{autre['id']}/mark-paid", headers=auth_headers,
        json={"payment_method": "cc_steven", "paid_at": "2026-10-29T15:00:00Z"},
    )
    assert mp.status_code == 200, mp.text
    _attendre(run, lambda: len(faux_qb.bill_payments) >= 1)
    parts = _achats(run, [tete["id"], autre["id"]])
    assert [p.status for p in parts] == ["paid", "paid"]
    assert [p.payment_method for p in parts] == ["cc_steven", "cc_steven"]
    assert all(p.paid_at is not None and p.due_at is None for p in parts)
    # UNE BillPayment du total du reçu, mémorisée sur les deux parts.
    assert len(faux_qb.bill_payments) == 1
    bp = faux_qb.bill_payments[0]
    assert bp["TotalAmt"] == 1149.75
    assert bp["Line"][0]["LinkedTxn"][0]["TxnId"] == bill_id
    assert faux_qb.bills[bill_id]["Balance"] == 0
    assert [p.qbo_bill_payment_id for p in parts] == [bp["Id"], bp["Id"]]

    # Idempotent : un 2e push de paiement ne crée rien.
    async def _again() -> dict:
        async with TestSessionLocal() as s:
            out = await push_bill_payment_to_qbo(s, tete["id"])
            await s.commit()
            return out

    assert run(_again())["qbo_bill_payment_id"] == bp["Id"]
    assert len(faux_qb.bill_payments) == 1


# ── 4) Reçu commun ; 5) suppression d'une part ───────────────────────


def test_recu_copie_et_suppression_d_une_part(
    client, auth_headers, run, chantiers, faux_qb
):
    res = client.post("/api/v1/achats/divise", headers=auth_headers, json=_corps(chantiers))
    assert res.status_code == 201, res.text
    tete, autre = res.json()["parts"]
    _attendre(run, lambda: len(faux_qb.bills) == 1)
    bill_id = next(iter(faux_qb.bills))

    up = client.post(
        f"/api/v1/achats/{tete['id']}/receipt", headers=auth_headers,
        files={"file": ("recu.pdf", PDF, "application/pdf")},
    )
    assert up.status_code == 204, up.text
    dl = client.get(f"/api/v1/achats/{autre['id']}/receipt", headers=auth_headers)
    assert dl.status_code == 200 and dl.content == PDF
    fiche = client.get(f"/api/v1/achats/{autre['id']}", headers=auth_headers)
    assert fiche.json()["has_receipt_image"] is True

    # Supprimer la part B : le Bill est réécrit avec la seule part A.
    sup = client.delete(f"/api/v1/achats/{autre['id']}", headers=auth_headers)
    assert sup.status_code in (200, 204), sup.text
    assert _achats(run, [autre["id"]]) == []
    assert len(faux_qb.bills) == 1
    bill = faux_qb.bills[bill_id]
    assert [ln["Amount"] for ln in _lignes(bill)] == [600.0]
    assert bill["TxnTaxDetail"]["TotalTax"] == 89.85
    assert bill["TotalAmt"] == 689.85
    reste = _achats(run, [tete["id"]])[0]
    assert reste.qbo_bill_id == bill_id
    pr = client.get(f"/api/v1/achats/{tete['id']}/parts", headers=auth_headers).json()
    assert len(pr["parts"]) == 1 and pr["total_kratos"] == 689.85


# ── 6) Mode carte de crédit → UNE dépense (Purchase) à deux lignes ──


def test_recu_divise_paye_par_carte_une_depense_deux_lignes(
    client, auth_headers, run, chantiers, faux_qb
):
    ch = chantiers
    res = client.post(
        "/api/v1/achats/divise", headers=auth_headers,
        json=_corps(ch, payment_method="cc_steven", supplier_invoice_number=f"CC-{ch['tag']}"),
    )
    assert res.status_code == 201, res.text
    parts = res.json()["parts"]
    assert all(p["status"] == "paid" and p["paid_at"] for p in parts)
    _attendre(run, lambda: len(faux_qb.creations) >= 1)
    assert [t for t, _ in faux_qb.creations] == ["Purchase"]
    dep = next(iter(faux_qb.purchases.values()))
    assert dep["PaymentType"] == "CreditCard" and dep["AccountRef"]["value"] == "41"
    assert dep["PaymentMethodRef"]["value"] == "PM-cc"
    lignes = _lignes(dep)
    assert [ln["Amount"] for ln in lignes] == [600.0, 400.0]
    assert [ln["AccountBasedExpenseLineDetail"]["CustomerRef"]["value"] for ln in lignes] == [
        ch["job_a"], ch["job_b"],
    ]
    # Projets sans soumission : non refacturables par défaut → NotBillable.
    assert all(ln["AccountBasedExpenseLineDetail"]["BillableStatus"] == "NotBillable" for ln in lignes)
    assert dep["TotalAmt"] == 1149.75
    ids = [p["id"] for p in parts]
    assert [a.qbo_bill_id for a in _achats(run, ids)] == [dep["Id"]] * 2
    assert len(faux_qb.pieces) == 0  # pas de reçu téléversé


# ── 7) Saisies invalides ─────────────────────────────────────────────


def test_divisions_invalides_refusees(client, auth_headers, chantiers, faux_qb):
    ch = chantiers
    # Somme des parts ≠ total du reçu.
    r = client.post(
        "/api/v1/achats/divise", headers=auth_headers,
        json=_corps(ch, parts=[{"project_id": ch["a"], "total": 600.0}, {"project_id": ch["b"], "total": 400.0}]),
    )
    assert r.status_code == 422 and "à répartir" in r.text
    # Un seul projet.
    r = client.post(
        "/api/v1/achats/divise", headers=auth_headers,
        json=_corps(ch, parts=[{"project_id": ch["a"], "total": 1149.75}]),
    )
    assert r.status_code == 422
    # Deux fois le même projet.
    r = client.post(
        "/api/v1/achats/divise", headers=auth_headers,
        json=_corps(ch, parts=[{"project_id": ch["a"], "total": 600.0}, {"project_id": ch["a"], "total": 549.75}]),
    )
    assert r.status_code == 422 and "qu'une fois" in r.text
    # Projet inexistant.
    r = client.post(
        "/api/v1/achats/divise", headers=auth_headers,
        json=_corps(ch, parts=[{"project_id": ch["a"], "total": 600.0}, {"project_id": 99999999, "total": 549.75}]),
    )
    assert r.status_code == 422 and "introuvable" in r.text
    # Rien n'a été créé ni poussé.
    assert faux_qb.creations == []


# ── 8) Contestation de la conception (2026-10-30) ────────────────────


def _simple(ch: dict, **extra: Any) -> Dict[str, Any]:
    """Un achat SIMPLE qui ressemble au reçu divisé (même fournisseur,
    même n° de facture, même total) — le doublon type."""
    base: Dict[str, Any] = {
        "fournisseur_id": ch["fournisseur"],
        "project_id": ch["a"],
        "description": "Bois traité et gypse (ressaisi)",
        "amount": 1000.0,
        "amount_taxes": 149.75,
        "amount_tps": 50.0,
        "amount_tvq": 99.75,
        "supplier_invoice_number": f"RD-{ch['tag']}",
        "invoice_date": "2026-10-28",
        "payment_method": "cc_steven",
        "status": "paid",
        "kind": "material",
    }
    base.update(extra)
    return base


def _dedupe(run) -> int:
    async def _go() -> int:
        async with TestSessionLocal() as s:
            n = await dedupe_achats(s)
            await s.commit()
            return n

    return run(_go())


def _creer_groupe(client, auth_headers, run, faux_qb, corps: dict) -> tuple:
    res = client.post("/api/v1/achats/divise", headers=auth_headers, json=corps)
    assert res.status_code == 201, res.text
    tete, autre = res.json()["parts"]
    _attendre(run, lambda: any(a.qbo_bill_id for a in _achats(run, [tete["id"]])))
    return tete, autre


def test_annuler_une_part_retire_sa_ligne_et_son_lien(
    client, auth_headers, run, chantiers, faux_qb
):
    tete, autre = _creer_groupe(client, auth_headers, run, faux_qb, _corps(chantiers))
    bill_id = next(iter(faux_qb.bills))

    r = client.patch(
        f"/api/v1/achats/{autre['id']}", headers=auth_headers, json={"status": "cancelled"},
    )
    assert r.status_code == 200, r.text
    bill = faux_qb.bills[bill_id]
    # La facture QB n'a plus que la ligne de la part A, au bon total.
    assert [ln["Amount"] for ln in _lignes(bill)] == [600.0]
    assert bill["TotalAmt"] == 689.85
    a, b = _achats(run, [tete["id"], autre["id"]])
    assert a.qbo_bill_id == bill_id and a.status == "received"
    assert b.status == "cancelled"
    assert b.qbo_bill_id is None and b.qbo_doc_number is None and b.qbo_sync_token is None
    # /parts : la part annulée est listée mais exclue du total.
    pj = client.get(f"/api/v1/achats/{tete['id']}/parts", headers=auth_headers).json()
    assert [(p["id"], p["status"]) for p in pj["parts"]] == [
        (tete["id"], "received"), (autre["id"], "cancelled"),
    ]
    assert pj["total_kratos"] == 689.85 and pj["qbo_total"] == 689.85

    # Réactiver la part : elle revient dans la facture QB et reprend le lien.
    r = client.patch(
        f"/api/v1/achats/{autre['id']}", headers=auth_headers, json={"status": "received"},
    )
    assert r.status_code == 200, r.text
    _attendre(run, lambda: _achats(run, [autre["id"]])[0].qbo_bill_id == bill_id)
    bill = faux_qb.bills[bill_id]
    assert sorted(ln["Amount"] for ln in _lignes(bill)) == [400.0, 600.0]
    assert bill["TotalAmt"] == 1149.75
    assert len(faux_qb.bills) == 1


def test_refus_quickbooks_bloque_l_annulation_et_la_suppression(
    client, auth_headers, run, chantiers, faux_qb
):
    tete, autre = _creer_groupe(client, auth_headers, run, faux_qb, _corps(chantiers))
    bill_id = next(iter(faux_qb.bills))
    faux_qb.erreur_maj = (
        "Business Validation Error: You cannot change this transaction because it has payments applied"
    )

    r = client.patch(
        f"/api/v1/achats/{autre['id']}", headers=auth_headers, json={"status": "cancelled"},
    )
    assert r.status_code == 409, r.text
    assert "verrouillée dans QuickBooks" in r.json()["detail"]
    r = client.delete(f"/api/v1/achats/{autre['id']}", headers=auth_headers)
    assert r.status_code == 409, r.text
    # Rien n'a bougé : part toujours active et liée, facture QB intacte.
    b = _achats(run, [autre["id"]])[0]
    assert b.status == "received" and b.qbo_bill_id == bill_id
    assert [ln["Amount"] for ln in _lignes(faux_qb.bills[bill_id])] == [600.0, 400.0]
    assert faux_qb.bills[bill_id]["TotalAmt"] == 1149.75


def test_une_part_ne_prend_pas_le_projet_d_une_soeur(
    client, auth_headers, run, chantiers, faux_qb
):
    tete, autre = _creer_groupe(client, auth_headers, run, faux_qb, _corps(chantiers))
    r = client.patch(
        f"/api/v1/achats/{autre['id']}", headers=auth_headers,
        json={"project_id": chantiers["a"]},
    )
    assert r.status_code == 409, r.text
    assert "déjà une part" in r.json()["detail"]
    assert _achats(run, [autre["id"]])[0].project_id == chantiers["b"]


def test_qb_qui_ignore_les_lignes_est_detecte(
    client, auth_headers, run, chantiers, faux_qb
):
    tete, autre = _creer_groupe(client, auth_headers, run, faux_qb, _corps(chantiers))
    bill_id = next(iter(faux_qb.bills))
    faux_qb.ignorer_lignes = True

    # Suppression de la part B : la mise à jour « passe » (200 QB) mais la
    # facture garde ses deux lignes → écart détecté → 409, rien supprimé.
    r = client.delete(f"/api/v1/achats/{autre['id']}", headers=auth_headers)
    assert r.status_code == 409, r.text
    assert "n'a pas repris les lignes" in r.json()["detail"]
    assert len(_achats(run, [tete["id"], autre["id"]])) == 2
    assert all(a.status == "received" for a in _achats(run, [tete["id"], autre["id"]]))

    # Montant d'une part modifié : la facture QB garde ses anciennes lignes
    # → le re-push le dit (le lien QB reste posé, jamais de doublon).
    r = client.patch(f"/api/v1/achats/{tete['id']}", headers=auth_headers, json={"amount": 700.0})
    assert r.status_code == 200, r.text

    async def _repush() -> None:
        async with TestSessionLocal() as s:
            await sync_achat_to_qbo(s, tete["id"])

    with pytest.raises(AchatSyncError, match="n'a pas repris les lignes"):
        run(_repush())
    assert all(a.qbo_bill_id == bill_id for a in _achats(run, [tete["id"], autre["id"]]))
    assert [ln["Amount"] for ln in _lignes(faux_qb.bills[bill_id])] == [600.0, 400.0]


def test_dedup_un_doublon_simple_est_absorbe_par_le_groupe(
    client, auth_headers, run, chantiers, faux_qb
):
    ch = chantiers
    tete, autre = _creer_groupe(client, auth_headers, run, faux_qb, _corps(ch))
    bill_id = next(iter(faux_qb.bills))

    # Le même reçu ressaisi comme achat SIMPLE, payé par carte : au score
    # de l'ancienne dédup il aurait gagné et supprimé la part A.
    res = client.post("/api/v1/achats", headers=auth_headers, json=_simple(ch))
    assert res.status_code == 201, res.text
    doublon = res.json()["id"]
    for _ in range(50):
        run(asyncio.sleep(0.02))
    # Son push est REFUSÉ : la facture QB à ce numéro est déjà celle du
    # groupe → aucune dépense créée dans QB, doublon sans lien.
    assert faux_qb.purchases == {}
    assert _achats(run, [doublon])[0].qbo_bill_id is None

    assert _dedupe(run) >= 1
    assert _achats(run, [doublon]) == []
    a, b = _achats(run, [tete["id"], autre["id"]])
    # Le groupe reste entier, lié à SA facture ; il hérite de l'état de
    # paiement réel du doublon.
    assert (a.qbo_bill_id, b.qbo_bill_id) == (bill_id, bill_id)
    assert (a.status, b.status) == ("paid", "paid")
    assert (a.payment_method, b.payment_method) == ("cc_steven", "cc_steven")
    assert (a.amount, b.amount) == (600.0, 400.0)
    # La facture du groupe reste intacte.
    assert bill_id in faux_qb.bills
    assert [ln["Amount"] for ln in _lignes(faux_qb.bills[bill_id])] == [600.0, 400.0]


def test_dedup_deux_groupes_identiques_le_plus_ancien_reste(
    client, auth_headers, run, chantiers, faux_qb
):
    ch = chantiers
    t1, a1 = _creer_groupe(client, auth_headers, run, faux_qb, _corps(ch))
    bill_id = next(iter(faux_qb.bills))
    # Le même reçu divisé saisi une 2e fois : son push est REFUSÉ (la
    # facture QB au même n° appartient déjà au premier groupe) → aucun
    # doublon dans QB, groupe 2 sans lien.
    res = client.post("/api/v1/achats/divise", headers=auth_headers, json=_corps(ch))
    assert res.status_code == 201, res.text
    t2, a2 = res.json()["parts"]
    for _ in range(50):
        run(asyncio.sleep(0.02))
    assert len(faux_qb.bills) == 1 and faux_qb.purchases == {}
    assert all(a.qbo_bill_id is None for a in _achats(run, [t2["id"], a2["id"]]))

    assert _dedupe(run) >= 2
    assert _achats(run, [t2["id"], a2["id"]]) == []
    restes = _achats(run, [t1["id"], a1["id"]])
    assert [(a.project_id, a.amount, a.qbo_bill_id) for a in restes] == [
        (ch["a"], 600.0, bill_id), (ch["b"], 400.0, bill_id),
    ]
    assert len(faux_qb.bills) == 1


def test_dedup_deux_groupes_differents_restent_intacts(
    client, auth_headers, run, chantiers, faux_qb
):
    ch = chantiers
    t1, a1 = _creer_groupe(client, auth_headers, run, faux_qb, _corps(ch))
    res = client.post(
        "/api/v1/achats/divise", headers=auth_headers,
        json=_corps(ch, parts=[{"project_id": ch["a"], "total": 500.0}, {"project_id": ch["b"], "total": 649.75}]),
    )
    assert res.status_code == 201, res.text
    t2, a2 = res.json()["parts"]
    for _ in range(50):
        run(asyncio.sleep(0.02))
    assert _dedupe(run) == 0
    assert len(_achats(run, [t1["id"], a1["id"], t2["id"], a2["id"]])) == 4


def test_refacturable_et_heures_par_part(client, auth_headers, run, chantiers, faux_qb):
    ch = chantiers
    res = client.post(
        "/api/v1/achats/divise", headers=auth_headers,
        json=_corps(
            ch, hours=10, kind="sub_invoice",
            parts=[
                {"project_id": ch["a"], "total": 689.85, "is_billable": True},
                {"project_id": ch["b"], "total": 459.90},
            ],
        ),
    )
    assert res.status_code == 201, res.text
    a, b = res.json()["parts"]
    # Heures au prorata (6 h / 4 h), jamais recopiées entières.
    assert (a["hours"], b["hours"]) == (6.0, 4.0)
    # Part A : choix explicite (verrou) ; part B : défaut du projet (sans
    # soumission → non refacturable), sans verrou.
    assert (a["is_billable"], a["billable_manual"]) == (True, True)
    assert (b["is_billable"], b["billable_manual"]) == (False, False)
    _attendre(run, lambda: len(faux_qb.bills) == 1)
    lignes = _lignes(next(iter(faux_qb.bills.values())))
    assert [ln["AccountBasedExpenseLineDetail"]["BillableStatus"] for ln in lignes] == [
        "Billable", "NotBillable",
    ]
    # Total HT absent → message français (plus de 422 pydantic anglais).
    r = client.post("/api/v1/achats/divise", headers=auth_headers, json=_corps(ch, amount=0))
    assert r.status_code == 422 and "total de la facture" in r.json()["detail"]
    r = client.post(
        "/api/v1/achats/divise", headers=auth_headers,
        json=_corps(ch, parts=[{"project_id": ch["a"], "total": 1149.75}, {"project_id": ch["b"], "total": 0}]),
    )
    assert r.status_code == 422 and "supérieur à 0" in r.json()["detail"]


def test_payer_une_part_par_la_fiche_paie_le_groupe(
    client, auth_headers, run, chantiers, faux_qb
):
    tete, autre = _creer_groupe(client, auth_headers, run, faux_qb, _corps(chantiers))
    r = client.patch(
        f"/api/v1/achats/{autre['id']}", headers=auth_headers,
        json={"status": "paid", "payment_method": "cc_steven", "paid_at": "2026-10-29T15:00:00Z"},
    )
    assert r.status_code == 200, r.text
    a, b = _achats(run, [tete["id"], autre["id"]])
    assert (a.status, b.status) == ("paid", "paid")
    assert (a.payment_method, b.payment_method) == ("cc_steven", "cc_steven")
    assert a.paid_at is not None


def test_webhook_reflete_la_date_sur_toutes_les_parts(run, chantiers, faux_qb, client, auth_headers):
    from datetime import date as _date

    from app.api.v1.endpoints.qbo_webhook import _apply_reverse_sync

    tete, autre = _creer_groupe(client, auth_headers, run, faux_qb, _corps(chantiers))
    bill_id = next(iter(faux_qb.bills))
    faux_qb.bills[bill_id]["TxnDate"] = "2026-10-25"

    async def _go() -> None:
        async with TestSessionLocal() as s:
            await _apply_reverse_sync(s, faux_qb, None, "Bill", bill_id)
            await s.commit()

    run(_go())
    assert [a.invoice_date for a in _achats(run, [tete["id"], autre["id"]])] == [
        _date(2026, 10, 25), _date(2026, 10, 25),
    ]
