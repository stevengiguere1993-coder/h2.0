"""Smoke — « importer la séparation de factures » (Steven, bug 9 du
2026-10-06, page /app/achats).

Une facture fournisseur / dépense FRACTIONNÉE dans QuickBooks (plusieurs
projets, ou un projet + une part hors projet) entre dans Kratos comme
dans QB : un achat PAR projet, chacun avec SA part ; la part non imputée
à un projet Kratos (client mère, autre client, aucun client) reste dans
QuickBooks. Couvre :

1. pull des coûts (Bills + Purchases, montants TTC) : facture A / B /
   hors projet → deux achats, rien pour la part hors projet ; dépense
   A / hors projet → un achat à la part de A ; total QB mémorisé ;
2. idempotence : un second passage ne change rien ;
3. réparation d'un achat importé EN BLOC avant le correctif : ramené à
   la part de son projet (sans osciller au passage suivant), ou divisé
   en une part par projet ;
4. import des Bills (sync-from-qbo, HT + taxes) : HT par projet, taxes
   au prorata de TOUTES les lignes, part hors projet laissée dans QB ;
   facture sans aucun projet → laissée dans QB ;
5. GET /achats/{id}/parts : les parts d'une même transaction QB, le
   total QB et ce qui est resté dans QuickBooks.

Client QuickBooks factice : aucun appel réseau.
"""

from __future__ import annotations

import re
import uuid
from typing import Any, Dict, List, Optional

import pytest
from sqlalchemy import select

from app.integrations.quickbooks import QuickBooksError
from app.models.achat import Achat
from app.models.client import Client
from app.models.project import Project

from .conftest import TestSessionLocal

TOTAL = 1149.75  # 1 000 $ HT + 149,75 $ de taxes (TPS + TVQ)
TAXES = 149.75


# ── Double QuickBooks ────────────────────────────────────────────────


class _FauxQB:
    """Compagnie QB factice : des Bills, des Purchases et des Vendors.
    Les requêtes paginées (Customer) échouent exprès : le pull les
    traite comme un QB sans sous-clients à réparer."""

    ready = True
    realm_id = "9130"

    def __init__(
        self,
        bills: Optional[List[Dict[str, Any]]] = None,
        purchases: Optional[List[Dict[str, Any]]] = None,
        vendors: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        self.bills = list(bills or [])
        self.purchases = list(purchases or [])
        self.vendors = {str(v["Id"]): v for v in (vendors or [])}

    async def _load_refresh_from_db(self) -> None:
        return None

    async def query(self, sql: str) -> List[Dict[str, Any]]:
        if "FROM Bill " in sql:
            return [dict(b) for b in self.bills]
        if "FROM Purchase " in sql:
            return [dict(p) for p in self.purchases]
        if "FROM Vendor " in sql:
            m = re.search(r"Id = '([^']+)'", sql)
            v = self.vendors.get(m.group(1)) if m else None
            return [dict(v)] if v else []
        return []

    async def query_all(self, sql: str) -> List[Dict[str, Any]]:
        raise QuickBooksError("double de test : pas de requête paginée")

    async def list_attachables(self) -> List[Dict[str, Any]]:
        return []


def _ligne(
    montant: float,
    *,
    job: Optional[str] = None,
    classe: Optional[str] = None,
    desc: Optional[str] = None,
) -> Dict[str, Any]:
    detail: Dict[str, Any] = {"AccountRef": {"value": "60", "name": "Matériaux"}}
    if job:
        detail["CustomerRef"] = {"value": job}
    if classe:
        detail["ClassRef"] = {"name": classe}
    line: Dict[str, Any] = {
        "Amount": montant,
        "DetailType": "AccountBasedExpenseLineDetail",
        "AccountBasedExpenseLineDetail": detail,
    }
    if desc:
        line["Description"] = desc
    return line


def _bill(
    bid: str,
    lignes: List[Dict[str, Any]],
    total: float,
    *,
    vendor: tuple,
    taxes: Optional[float] = None,
    doc: Optional[str] = None,
) -> Dict[str, Any]:
    b: Dict[str, Any] = {
        "Id": bid,
        "SyncToken": "0",
        "TxnDate": "2026-10-10",
        "DueDate": "2026-11-09",
        "DocNumber": doc or f"F-{bid}",
        "TotalAmt": total,
        "Balance": total,  # non payée
        "VendorRef": {"value": vendor[0], "name": vendor[1]},
        "Line": lignes,
    }
    if taxes is not None:
        b["TxnTaxDetail"] = {"TotalTax": taxes}
    return b


def _purchase(
    pid: str, lignes: List[Dict[str, Any]], total: float, *, vendor: tuple
) -> Dict[str, Any]:
    return {
        "Id": pid,
        "SyncToken": "0",
        "TxnDate": "2026-10-11",
        "DocNumber": f"D-{pid}",
        "TotalAmt": total,
        "PaymentType": "CreditCard",
        "AccountRef": {"value": "CC-1", "name": "Carte"},
        "EntityRef": {"value": vendor[0], "name": vendor[1], "type": "Vendor"},
        "Line": lignes,
    }


# ── Données Kratos ───────────────────────────────────────────────────


@pytest.fixture()
def chantiers(run, db_setup) -> dict:
    """Un client et deux chantiers reliés à leur sous-client QB."""
    tag = uuid.uuid4().hex[:8]

    async def _go() -> dict:
        async with TestSessionLocal() as s:
            cl = Client(name=f"Client séparation {tag}", qbo_customer_id=f"C-{tag}")
            s.add(cl)
            await s.flush()
            a = Project(
                name=f"Chantier A {tag}",
                client_id=cl.id,
                address=f"{tag} rue des Parts A",
                qbo_job_id=f"JA-{tag}",
            )
            b = Project(
                name=f"Chantier B {tag}",
                client_id=cl.id,
                address=f"{tag} rue des Parts B",
                qbo_job_id=f"JB-{tag}",
            )
            s.add_all([a, b])
            await s.commit()
            return {
                "tag": tag,
                "a": a.id,
                "b": b.id,
                "job_a": a.qbo_job_id,
                "job_b": b.qbo_job_id,
                "vendor": (f"V-{tag}", f"Rona Legendre {tag}"),
            }

    return run(_go())


def _achats(run, **where) -> List[Achat]:
    async def _go() -> List[Achat]:
        async with TestSessionLocal() as s:
            stmt = select(Achat).order_by(Achat.id)
            for col, val in where.items():
                stmt = stmt.where(getattr(Achat, col) == val)
            return list((await s.execute(stmt)).scalars().all())

    return run(_go())


def _seed_achat(run, **champs) -> int:
    async def _go() -> int:
        async with TestSessionLocal() as s:
            base = dict(kind="material", is_billable=False, markup_percent=0)
            base.update(champs)
            a = Achat(**base)
            s.add(a)
            await s.commit()
            return a.id

    return run(_go())


def _f(v) -> Optional[float]:
    return None if v is None else float(v)


# ── 1-2) Pull des coûts : import par parts, idempotent ──────────────


def test_pull_couts_facture_fractionnee_une_part_par_projet(
    client, auth_headers, run, chantiers, monkeypatch
):
    tag, ja, jb = chantiers["tag"], chantiers["job_a"], chantiers["job_b"]
    vend = chantiers["vendor"]
    facture = _bill(
        f"B1-{tag}",
        [
            _ligne(600, job=ja, desc="Bois chantier A"),
            _ligne(300, job=jb, desc="Gypse chantier B"),
            _ligne(100, desc="Outillage atelier"),  # hors projet
        ],
        TOTAL,
        vendor=vend,
        taxes=TAXES,
    )
    depense = _purchase(
        f"P1-{tag}",
        [_ligne(600, job=ja, desc="Vis et ancrages"), _ligne(400, desc="Essence camion")],
        TOTAL,
        vendor=vend,
    )
    faux = _FauxQB(bills=[facture], purchases=[depense])
    monkeypatch.setattr(
        "app.integrations.quickbooks.get_qbo", lambda scope="construction": faux
    )

    r = client.post("/api/v1/qbo/pull-costs?dry_run=false", headers=auth_headers)
    assert r.status_code == 200, r.text
    stats = r.json()
    assert stats["bills_imported"] == 1
    assert stats["purchases_imported"] == 1
    assert stats["split_multi_projets"] == 1  # la facture (A + B)
    assert stats["parts_partielles"] == 2  # facture ET dépense ont une part hors projet
    assert stats["reduits_part_projet"] == 0

    part_a, part_b = round(TOTAL * 0.6, 2), round(TOTAL * 0.3, 2)

    parts = _achats(run, qbo_bill_id=f"B1-{tag}")
    assert [p.project_id for p in parts] == [chantiers["a"], chantiers["b"]]
    assert [_f(p.amount) for p in parts] == [part_a, part_b]
    assert all(p.amount_taxes is None for p in parts)  # montants TTC (pull-costs)
    assert all(_f(p.qbo_txn_total) == TOTAL for p in parts)
    assert [p.description for p in parts] == ["Bois chantier A", "Gypse chantier B"]
    assert all(p.status == "received" and p.payment_method == "bill_to_pay" for p in parts)
    assert all(p.supplier_invoice_number == f"F-B1-{tag}" for p in parts)
    assert len({p.fournisseur_id for p in parts}) == 1 and parts[0].fournisseur_id

    seule = _achats(run, qbo_purchase_id=f"P1-{tag}")
    assert len(seule) == 1
    assert seule[0].project_id == chantiers["a"]
    assert _f(seule[0].amount) == part_a
    assert _f(seule[0].qbo_txn_total) == TOTAL
    assert seule[0].status == "paid" and seule[0].payment_method == "cc"

    # Second passage : rien ne bouge (ni nouvel achat, ni montant ramené
    # au total, ni nouvelle division).
    r2 = client.post("/api/v1/qbo/pull-costs?dry_run=false", headers=auth_headers)
    assert r2.status_code == 200, r2.text
    stats2 = r2.json()
    assert stats2["bills_imported"] == 0 and stats2["purchases_imported"] == 0
    assert stats2["split_multi_projets"] == 0
    assert stats2["parts_partielles"] == 0
    assert stats2["reduits_part_projet"] == 0
    apres = _achats(run, qbo_bill_id=f"B1-{tag}")
    assert [(p.id, _f(p.amount)) for p in apres] == [(p.id, _f(p.amount)) for p in parts]
    seule2 = _achats(run, qbo_purchase_id=f"P1-{tag}")
    assert [(p.id, _f(p.amount)) for p in seule2] == [(seule[0].id, part_a)]

    # 5) Les parts vues depuis la fiche d'un achat.
    r3 = client.get(f"/api/v1/achats/{parts[1].id}/parts", headers=auth_headers)
    assert r3.status_code == 200, r3.text
    corps = r3.json()
    assert corps["qbo_id"] == f"B1-{tag}"
    assert corps["qbo_doc_number"] == f"F-B1-{tag}"
    assert corps["qbo_total"] == TOTAL
    assert [p["id"] for p in corps["parts"]] == [parts[0].id, parts[1].id]
    assert [p["project_id"] for p in corps["parts"]] == [chantiers["a"], chantiers["b"]]
    assert [p["total"] for p in corps["parts"]] == [part_a, part_b]
    assert corps["total_kratos"] == round(part_a + part_b, 2)
    assert corps["reste_qb"] == round(TOTAL - part_a - part_b, 2)
    assert corps["reste_qb"] == pytest.approx(114.975, abs=0.011)

    r4 = client.get(f"/api/v1/achats/{seule[0].id}/parts", headers=auth_headers)
    assert r4.status_code == 200, r4.text
    corps4 = r4.json()
    assert len(corps4["parts"]) == 1
    assert corps4["qbo_total"] == TOTAL
    assert corps4["reste_qb"] == round(TOTAL - part_a, 2)


# ── 3) Réparation des achats importés en bloc avant le correctif ────


def test_pull_couts_repare_les_achats_importes_en_bloc(
    client, auth_headers, run, chantiers, monkeypatch
):
    tag, ja, jb = chantiers["tag"], chantiers["job_a"], chantiers["job_b"]
    vend = chantiers["vendor"]
    # Dépense A / hors projet importée EN BLOC (au total) avant le correctif.
    id_bloc_dep = _seed_achat(
        run,
        project_id=chantiers["a"],
        description="Dépense en bloc",
        amount=TOTAL,
        status="paid",
        payment_method="cc",
        qbo_purchase_id=f"P2-{tag}",
        qbo_doc_number=f"D-P2-{tag}",
        supplier_invoice_number=f"D-P2-{tag}",
    )
    # Facture A / B importée EN BLOC sur A.
    id_bloc_fac = _seed_achat(
        run,
        project_id=chantiers["a"],
        description="Facture en bloc",
        amount=1000.0,
        status="received",
        payment_method="bill_to_pay",
        qbo_bill_id=f"B2-{tag}",
        qbo_doc_number=f"F-B2-{tag}",
        supplier_invoice_number=f"F-B2-{tag}",
    )
    faux = _FauxQB(
        bills=[
            _bill(
                f"B2-{tag}",
                [_ligne(600, job=ja, desc="Portes A"), _ligne(400, job=jb, desc="Portes B")],
                1000.0,
                vendor=vend,
            )
        ],
        purchases=[
            _purchase(
                f"P2-{tag}",
                [_ligne(600, job=ja, desc="Béton A"), _ligne(400, desc="Café bureau")],
                TOTAL,
                vendor=vend,
            )
        ],
    )
    monkeypatch.setattr(
        "app.integrations.quickbooks.get_qbo", lambda scope="construction": faux
    )

    r = client.post("/api/v1/qbo/pull-costs?dry_run=false", headers=auth_headers)
    assert r.status_code == 200, r.text
    stats = r.json()
    assert stats["reduits_part_projet"] == 1  # la dépense, ramenée à la part de A
    assert stats["split_multi_projets"] == 1  # la facture, divisée A / B
    assert stats["parts_partielles"] == 1
    assert stats["bills_imported"] == 0 and stats["purchases_imported"] == 0

    dep = _achats(run, qbo_purchase_id=f"P2-{tag}")
    assert [d.id for d in dep] == [id_bloc_dep]  # même achat, pas recréé
    assert _f(dep[0].amount) == round(TOTAL * 0.6, 2)
    assert _f(dep[0].qbo_txn_total) == TOTAL
    assert dep[0].project_id == chantiers["a"]
    assert dep[0].status == "paid"

    fac = _achats(run, qbo_bill_id=f"B2-{tag}")
    assert len(fac) == 2
    assert fac[0].id == id_bloc_fac
    assert [(p.project_id, _f(p.amount)) for p in fac] == [
        (chantiers["a"], 600.0),
        (chantiers["b"], 400.0),
    ]
    assert all(_f(p.qbo_txn_total) == 1000.0 for p in fac)
    assert all(p.status == "received" for p in fac)
    assert [p.description for p in fac] == ["Portes A", "Portes B"]

    # Deux passages de plus : aucune oscillation (part → total → part…).
    for _ in range(2):
        rn = client.post("/api/v1/qbo/pull-costs?dry_run=false", headers=auth_headers)
        assert rn.status_code == 200, rn.text
        sn = rn.json()
        assert sn["reduits_part_projet"] == 0
        assert sn["split_multi_projets"] == 0
        assert sn["parts_partielles"] == 0
        dep_n = _achats(run, qbo_purchase_id=f"P2-{tag}")
        assert [(d.id, _f(d.amount)) for d in dep_n] == [(id_bloc_dep, round(TOTAL * 0.6, 2))]
        fac_n = _achats(run, qbo_bill_id=f"B2-{tag}")
        assert [(p.id, _f(p.amount)) for p in fac_n] == [(p.id, _f(p.amount)) for p in fac]


# ── 4) Import des Bills (sync-from-qbo, HT + taxes) ─────────────────


def test_sync_from_qbo_facture_fractionnee_ht_et_taxes(
    client, auth_headers, run, chantiers, monkeypatch
):
    from app.services import achat_qbo_pull

    tag, ja, jb = chantiers["tag"], chantiers["job_a"], chantiers["job_b"]
    vend = chantiers["vendor"]
    fractionnee = _bill(
        f"B3-{tag}",
        [
            _ligne(600, job=ja, desc="Bois A"),
            _ligne(300, job=jb, desc="Gypse B"),
            _ligne(100, desc="Atelier"),  # hors projet
        ],
        TOTAL,
        vendor=vend,
        taxes=TAXES,
    )
    sans_projet = _bill(
        f"B4-{tag}", [_ligne(250, desc="Papeterie")], 287.44, vendor=vend, taxes=37.44
    )
    faux = _FauxQB(
        bills=[fractionnee, sans_projet],
        vendors=[{"Id": vend[0], "DisplayName": vend[1]}],
    )
    # get_qbo est importé au niveau du module dans ce service.
    monkeypatch.setattr(achat_qbo_pull, "get_qbo", lambda scope="construction": faux)

    r = client.post("/api/v1/achats/sync-from-qbo", headers=auth_headers)
    assert r.status_code == 200, r.text
    stats = r.json()
    assert stats["imported"] == 1
    assert stats["split_multi_projets"] == 1
    assert stats["parts_partielles"] == 1
    assert stats["skipped_unlinked"] == 1  # la facture sans projet reste dans QB
    assert stats["total_qbo_bills"] == 2

    parts = _achats(run, qbo_bill_id=f"B3-{tag}")
    assert [(p.project_id, _f(p.amount), _f(p.amount_taxes)) for p in parts] == [
        (chantiers["a"], 600.0, round(TAXES * 0.6, 2)),
        (chantiers["b"], 300.0, round(TAXES * 0.3, 2)),
    ]
    assert all(_f(p.qbo_txn_total) == TOTAL for p in parts)
    assert [p.description for p in parts] == ["Bois A", "Gypse B"]
    assert all(p.status == "received" and p.payment_method == "bill_to_pay" for p in parts)
    assert all(p.due_at is not None for p in parts)
    assert _achats(run, qbo_bill_id=f"B4-{tag}") == []

    # Second passage : la facture est connue, rien ne s'ajoute.
    r2 = client.post("/api/v1/achats/sync-from-qbo", headers=auth_headers)
    assert r2.status_code == 200, r2.text
    stats2 = r2.json()
    assert stats2["imported"] == 0
    assert stats2["skipped_existing"] == 1
    assert stats2["skipped_unlinked"] == 1
    assert [p.id for p in _achats(run, qbo_bill_id=f"B3-{tag}")] == [p.id for p in parts]

    # /parts : total QB, part restée dans QB (HT 100 $ + ses taxes).
    r3 = client.get(f"/api/v1/achats/{parts[0].id}/parts", headers=auth_headers)
    assert r3.status_code == 200, r3.text
    corps = r3.json()
    assert corps["qbo_total"] == TOTAL
    assert [p["id"] for p in corps["parts"]] == [p.id for p in parts]
    assert corps["total_kratos"] == round(sum(p["total"] for p in corps["parts"]), 2)
    assert corps["reste_qb"] == pytest.approx(114.975, abs=0.011)


# ── 5) /parts d'un achat né dans Kratos ─────────────────────────────


def test_parts_achat_sans_lien_qb(client, auth_headers, run, chantiers):
    aid = _seed_achat(
        run,
        project_id=chantiers["a"],
        description="Reçu saisi dans Kratos",
        amount=50.0,
        amount_taxes=7.49,
        status="paid",
        payment_method="cc_steven",
    )
    r = client.get(f"/api/v1/achats/{aid}/parts", headers=auth_headers)
    assert r.status_code == 200, r.text
    corps = r.json()
    assert corps["qbo_id"] is None
    assert corps["qbo_total"] is None
    assert corps["reste_qb"] is None
    assert corps["total_kratos"] == 57.49
    assert [p["id"] for p in corps["parts"]] == [aid]

    assert client.get("/api/v1/achats/987654321/parts", headers=auth_headers).status_code == 404
