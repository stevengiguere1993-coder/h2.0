"""Smoke — report des petits soldes impayés (2026-11-02).

Steven : « parfois les clients reçoivent de très gros montants et de
petits montants sont oubliés de payer, ex. 15 $ sur une facture de
18 000 $ […] pour que tout balance dans QuickBooks et qu'on n'ait pas une
facture en retard pour rien ». Puis : « lorsque nous classons la facture
dans payé, le report devrait se faire automatiquement s'il reste un montant
sur la facture à payer ».

Couvre :
1. facture classée « payée » avec un petit solde → report automatique :
   la facture d'origine est payée, le brouillon du client reçoit la ligne
   « Solde reporté de la facture X » HORS TAXES, et QuickBooks reçoit un
   Payment du solde déposé dans le compte de transit ;
2. « payée » sans aucun paiement enregistré (ancien flux) ou solde
   au-dessus du plafond → rien n'est reporté ;
3. sans brouillon, le report attend et s'ajoute au prochain brouillon du
   client à son ouverture ; la ligne part dans QB avec le produit du
   compte de transit et le code de taxe exonéré, le total QB = Kratos ;
4. ligne retirée du brouillon → le report attend la facture SUIVANTE ;
5. annulation → Payment QB supprimé, ligne retirée, facture d'origine
   rouverte ; refus de QB au report manuel → rien n'est enregistré ;
6. le rapatriement QB → Kratos ne recopie pas le Payment du report comme
   un paiement ; l'état de compte et le PDF tiennent compte du report.

QuickBooks est simulé en mémoire : aucun appel réseau.
"""

from __future__ import annotations

import copy
import uuid
from datetime import date, datetime, timezone
from typing import Any, Dict, Optional

import pytest
from sqlalchemy import delete, select

import app.integrations.quickbooks as qb_mod
import app.services.facture_qbo as fq
import app.services.facture_report_solde as rep_mod
from app.integrations.quickbooks import QuickBooksError
from app.models.audit_log import AuditLog
from app.models.client import Client
from app.models.facture import Facture
from app.models.facture_item import FactureItem
from app.models.facture_report_solde import FactureReportSolde
from app.models.payment import Payment
from app.services.facture_lignes import totaux_facture
from tests.smoke.conftest import TestSessionLocal
from tests.smoke.test_smoke_facture_qbo_miroir_2026_10_14 import (
    QBMiroir,
    _attendre_taches,
)

EMISE_LE = datetime(2026, 9, 15, 14, 0, tzinfo=timezone.utc)
TAXE_VENTE = "5"
TAXE_EXONEREE = "9"


class QBReport(QBMiroir):
    """QBMiroir + compte de transit, produit du report, codes de taxe ; un
    Payment réduit le solde des Invoices qu'il paie ; la taxe n'est
    calculée que sur les lignes au code de taxe de vente."""

    def __init__(self) -> None:
        super().__init__()
        self.comptes: Dict[str, Dict[str, Any]] = {}
        self.refus_paiement: Optional[str] = None

    async def ensure_account(self, *, name, account_type, account_sub_type):
        self.comptes.setdefault(
            name, {"Id": "ACC-TRANSIT", "Name": name, "AccountType": account_type}
        )
        return self.comptes[name]

    async def ensure_item_sur_compte(self, *, name, account_id, description=None):
        return {"Id": "IT-REPORT", "Name": name, "IncomeAccountRef": {"value": account_id}}

    async def query(self, q: str) -> list[Dict[str, Any]]:
        if "FROM TaxCode" in q:
            return [
                {"Id": TAXE_VENTE, "Name": "TPS/TVQ QC - 9,975", "Active": True},
                {"Id": TAXE_EXONEREE, "Name": "Exonéré", "Active": True},
            ]
        return await super().query(q)

    def _recalculer(self, inv: Dict[str, Any], paye: float) -> None:
        lignes = 0.0
        taxables = 0.0
        for li in inv.get("Line") or []:
            if li.get("DetailType") != "SalesItemLineDetail":
                continue
            m = float(li.get("Amount") or 0)
            lignes += m
            code = ((li.get("SalesItemLineDetail") or {}).get("TaxCodeRef") or {}).get("value")
            if code != TAXE_EXONEREE:
                taxables += m
        taxe = round(round(taxables * 0.05, 2) + round(taxables * 0.09975, 2), 2)
        inv["TxnTaxDetail"] = {"TotalTax": taxe}
        inv["TotalAmt"] = round(lignes + taxe, 2)
        inv["Balance"] = round(inv["TotalAmt"] - paye, 2)

    async def create_payment(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        if self.refus_paiement:
            raise QuickBooksError(self.refus_paiement)
        res = await super().create_payment(payload)
        for li in payload.get("Line") or []:
            for lt in li.get("LinkedTxn") or []:
                inv = self.invoices.get(str(lt.get("TxnId")))
                if inv is not None and lt.get("TxnType") == "Invoice":
                    inv["Balance"] = round(float(inv["Balance"]) - float(li["Amount"]), 2)
                    inv["SyncToken"] = str(int(inv["SyncToken"]) + 1)
        return res

    async def delete_payment(self, pid: str) -> bool:
        p = self.payments.get(str(pid))
        if p is None:
            return False
        for li in p.get("Line") or []:
            for lt in li.get("LinkedTxn") or []:
                inv = self.invoices.get(str(lt.get("TxnId")))
                if inv is not None:
                    inv["Balance"] = round(float(inv["Balance"]) + float(li["Amount"]), 2)
        return await super().delete_payment(pid)


@pytest.fixture()
def qb(monkeypatch, run, db_setup):
    faux = QBReport()
    monkeypatch.setattr(fq, "get_qbo", lambda *a, **k: faux)
    monkeypatch.setattr(qb_mod, "get_qbo", lambda *a, **k: faux)
    monkeypatch.setitem(fq.settings.__dict__, "qbo_sales_tax_code", TAXE_VENTE)
    rep_mod._cache_qbo.clear()
    fq._corrections_tentees.clear()
    crees: Dict[str, list[int]] = {"factures": [], "clients": []}
    faux.crees = crees  # type: ignore[attr-defined]
    yield faux
    _attendre_taches(run)

    async def _nettoyer() -> None:
        async with TestSessionLocal() as s:
            fids = crees["factures"]
            if fids:
                await s.execute(
                    delete(FactureReportSolde).where(
                        FactureReportSolde.origine_facture_id.in_(fids)
                    )
                )
                await s.execute(delete(Payment).where(Payment.facture_id.in_(fids)))
                await s.execute(delete(FactureItem).where(FactureItem.facture_id.in_(fids)))
                await s.execute(delete(AuditLog).where(AuditLog.entity_id.in_(fids)))
                await s.execute(delete(Facture).where(Facture.id.in_(fids)))
            if crees["clients"]:
                await s.execute(delete(Client).where(Client.id.in_(crees["clients"])))
            await s.commit()

    run(_nettoyer())
    rep_mod._cache_qbo.clear()
    fq._corrections_tentees.clear()


def _ref() -> str:
    return str(500000 + uuid.uuid4().int % 400000)


def _client(run, qb: QBReport) -> int:
    async def _go() -> int:
        async with TestSessionLocal() as s:
            cl = Client(name=f"Client report {uuid.uuid4().hex[:6]}", qbo_customer_id="C-KRATOS")
            s.add(cl)
            await s.commit()
            qb.crees["clients"].append(cl.id)  # type: ignore[attr-defined]
            return int(cl.id)

    return run(_go())


def _facture(
    run,
    qb: QBReport,
    client_id: int,
    *,
    lignes: list[tuple[str, float]],
    status: str = "sent",
    paye: float = 0.0,
    lier: bool = True,
) -> tuple[int, Optional[str]]:
    """Facture avec ses lignes, un paiement Kratos (déjà dans QB) de
    ``paye`` et, si ``lier``, son Invoice QB."""
    t = totaux_facture([("service", m) for _, m in lignes])
    reference = _ref() if status != "draft" else f"BR-{uuid.uuid4().hex[:8]}"
    iid = qb._id() if lier else None
    pid = qb._id() if (lier and paye) else None

    async def _go() -> int:
        async with TestSessionLocal() as s:
            fa = Facture(
                reference=reference,
                client_id=client_id,
                status=status,
                issued_at=EMISE_LE if status != "draft" else None,
                subtotal=t["subtotal"],
                tps=t["tps"],
                tvq=t["tvq"],
                total=t["total"],
                balance=t["total"],
                qbo_invoice_id=iid,
                qbo_sync_token="0" if iid else None,
            )
            s.add(fa)
            await s.flush()
            for i, (desc, montant) in enumerate(lignes):
                s.add(
                    FactureItem(
                        facture_id=fa.id, position=i, description=desc,
                        quantity=1, unit_price=montant, total=montant, kind="service",
                    )
                )
            if paye:
                s.add(
                    Payment(
                        facture_id=fa.id, amount=paye, method="bank_transfer",
                        paid_at=date(2026, 10, 1), qbo_payment_id=pid,
                    )
                )
            await s.commit()
            qb.crees["factures"].append(fa.id)  # type: ignore[attr-defined]
            return int(fa.id)

    fid = run(_go())
    if iid:
        qb.invoices[iid] = {
            "Id": iid,
            "SyncToken": "0",
            "DocNumber": reference,
            "CustomerRef": {"value": "C-KRATOS", "name": "Client"},
            "TxnDate": "2026-09-15",
            "PrivateNote": fq.MEMO_KRATOS.format(id=fid),
            "Line": [
                {
                    "DetailType": "SalesItemLineDetail",
                    "Amount": m,
                    "Description": d,
                    "SalesItemLineDetail": {
                        "Qty": 1, "UnitPrice": m, "ItemRef": {"value": "IT-1"},
                        "TaxCodeRef": {"value": TAXE_VENTE},
                    },
                }
                for d, m in lignes
            ],
        }
        qb._recalculer(qb.invoices[iid], paye)
        if pid:
            qb.payments[pid] = {
                "Id": pid, "TotalAmt": paye,
                "Line": [{"Amount": paye, "LinkedTxn": [{"TxnId": iid, "TxnType": "Invoice"}]}],
            }
    return fid, iid


def _lire(run, fid: int) -> Facture:
    async def _go() -> Facture:
        async with TestSessionLocal() as s:
            return await s.get(Facture, fid)

    return run(_go())


def _items(run, fid: int) -> list[FactureItem]:
    async def _go() -> list[FactureItem]:
        async with TestSessionLocal() as s:
            return list(
                (
                    await s.execute(
                        select(FactureItem)
                        .where(FactureItem.facture_id == fid)
                        .order_by(FactureItem.position)
                    )
                ).scalars().all()
            )

    return run(_go())


def _reports(run, origine_id: int) -> list[FactureReportSolde]:
    async def _go() -> list[FactureReportSolde]:
        async with TestSessionLocal() as s:
            return list(
                (
                    await s.execute(
                        select(FactureReportSolde).where(
                            FactureReportSolde.origine_facture_id == origine_id
                        )
                    )
                ).scalars().all()
            )

    return run(_go())


# Facture de 18 000 $ (15 655,49 $ HT) : le client paie 17 985 $.
GROS = [("Travaux de rénovation", 15655.49)]


def _montant_paye(lignes) -> float:
    return round(totaux_facture([("service", m) for _, m in lignes])["total"] - 15.0, 2)


# ── 1. Classée « payée » avec un petit solde → report automatique ──────


def test_classer_payee_reporte_le_petit_solde_sur_le_brouillon(
    qb, run, client, auth_headers
):
    cid = _client(run, qb)
    fid, iid = _facture(run, qb, cid, lignes=GROS, paye=_montant_paye(GROS))
    brouillon, _ = _facture(
        run, qb, cid, lignes=[("Phase 2", 1000.0)], status="draft", lier=False
    )
    assert qb.invoices[iid]["Balance"] == 15.0

    r = client.patch(
        f"/api/v1/factures/{fid}", headers=auth_headers, json={"status": "paid"}
    )
    assert r.status_code == 200, r.text
    _attendre_taches(run)

    origine = _lire(run, fid)
    assert origine.status == "paid"
    (rep,) = _reports(run, fid)
    assert float(rep.montant) == 15.0
    assert rep.automatique is True
    assert rep.statut == "applique"
    assert rep.cible_facture_id == brouillon

    # Brouillon : ligne hors taxes ajoutée APRÈS les taxes.
    items = _items(run, brouillon)
    assert [it.kind for it in items] == ["service", "report"]
    assert items[-1].description == f"Solde reporté de la facture {origine.reference}"
    assert float(items[-1].total) == 15.0
    assert items[-1].hors_soumission is True
    b = _lire(run, brouillon)
    assert float(b.subtotal) == 1000.0
    assert float(b.tps) == 50.0 and float(b.tvq) == 99.75
    assert float(b.total) == 1164.75

    # QuickBooks : Payment de 15 $ imputé à l'Invoice d'origine, déposé
    # dans le compte de transit (pas la banque) → Invoice soldée.
    assert rep.qbo_payment_id and rep.qbo_error is None
    pay = qb.payments[rep.qbo_payment_id]
    assert pay["TotalAmt"] == 15.0
    assert pay["DepositToAccountRef"] == {"value": "ACC-TRANSIT"}
    assert pay["Line"][0]["LinkedTxn"] == [{"TxnId": iid, "TxnType": "Invoice"}]
    assert qb.invoices[iid]["Balance"] == 0.0
    assert "Soldes reportés" in qb.comptes

    # Le GET de la facture d'origine : plus rien à reporter.
    r = client.get(f"/api/v1/factures/{fid}/reports-solde", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json()["solde_restant"] == 0.0
    assert r.json()["reportable"] is False
    assert r.json()["reportes"][0]["cible_reference"] == b.reference
    r = client.get(f"/api/v1/factures/{brouillon}/reports-solde", headers=auth_headers)
    assert r.json()["recus"][0]["origine_reference"] == origine.reference


# ── 2. Pas de report sans paiement, ni au-dessus du plafond ────────────


def test_payee_sans_paiement_ou_au_dessus_du_plafond_ne_reporte_rien(
    qb, run, client, auth_headers
):
    cid = _client(run, qb)
    # Petite facture classée payée SANS paiement enregistré : « payée en
    # entier hors Kratos » (ancien flux), pas un oubli de 57 $.
    petite, _ = _facture(run, qb, cid, lignes=[("Réparation", 50.0)], lier=False)
    # Gros solde (500 $) : un vrai impayé, au-dessus du plafond de 100 $.
    gros, _ = _facture(
        run, qb, cid, lignes=GROS, paye=_montant_paye(GROS) - 485.0, lier=False
    )
    for fid in (petite, gros):
        r = client.patch(
            f"/api/v1/factures/{fid}", headers=auth_headers, json={"status": "paid"}
        )
        assert r.status_code == 200, r.text
    _attendre_taches(run)
    assert _reports(run, petite) == []
    assert _reports(run, gros) == []

    # Le bouton refuse aussi au-dessus du plafond, avec le motif.
    r = client.post(f"/api/v1/factures/{gros}/reports-solde", headers=auth_headers)
    assert r.status_code == 409
    assert "maximum reportable" in r.json()["detail"]


# ── 3. Sans brouillon : le report attend la prochaine facture ──────────


def test_report_en_attente_puis_ligne_exoneree_dans_quickbooks(
    qb, run, client, auth_headers
):
    cid = _client(run, qb)
    fid, iid = _facture(run, qb, cid, lignes=GROS, paye=_montant_paye(GROS))

    r = client.post(f"/api/v1/factures/{fid}/reports-solde", headers=auth_headers)
    assert r.status_code == 201, r.text
    assert r.json()["statut"] == "en_attente"
    assert r.json()["automatique"] is False
    assert r.json()["qbo_payment_id"]  # QuickBooks d'abord, dans la requête
    assert _lire(run, fid).status == "paid"
    assert qb.invoices[iid]["Balance"] == 0.0

    # Nouveau brouillon du client : la ligne apparaît à son ouverture.
    brouillon, _ = _facture(
        run, qb, cid, lignes=[("Phase 2", 1000.0)], status="draft", lier=False
    )
    r = client.get(f"/api/v1/factures/{brouillon}", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert float(r.json()["total"]) == 1164.75
    assert [it.kind for it in _items(run, brouillon)] == ["service", "report"]
    # Idempotent : une 2e ouverture n'ajoute rien.
    client.get(f"/api/v1/factures/{brouillon}", headers=auth_headers)
    assert len(_items(run, brouillon)) == 2

    # Envoi dans QuickBooks : produit du compte de transit, code exonéré,
    # total QB = total Kratos (15 $ jamais taxés deux fois).
    async def _pousser() -> None:
        async with TestSessionLocal() as s:
            await fq.sync_facture_to_qbo(s, brouillon, avant_envoi=True)
            await s.commit()

    run(_pousser())
    b = _lire(run, brouillon)
    inv = qb.invoices[b.qbo_invoice_id]
    (svc, rep_ligne) = [li for li in inv["Line"] if li["DetailType"] == "SalesItemLineDetail"]
    assert svc["SalesItemLineDetail"]["TaxCodeRef"] == {"value": TAXE_VENTE}
    assert rep_ligne["Amount"] == 15.0
    assert rep_ligne["SalesItemLineDetail"]["TaxCodeRef"] == {"value": TAXE_EXONEREE}
    assert rep_ligne["SalesItemLineDetail"]["ItemRef"] == {"value": "IT-REPORT"}
    assert "_kratos_report" not in rep_ligne
    assert inv["TotalAmt"] == float(b.total) == 1164.75

    # Le filet « Invoice en retard sur Kratos » ne voit pas d'écart.
    async def _ecarts() -> list:
        async with TestSessionLocal() as s:
            return await fq.factures_en_retard_dans_qb(qb, s)

    assert [e for e in run(_ecarts()) if e["facture_id"] == brouillon] == []


# ── 4. Ligne retirée à la main → attend la facture suivante ────────────


def test_ligne_retiree_attend_la_facture_suivante(qb, run, client, auth_headers):
    cid = _client(run, qb)
    fid, _ = _facture(run, qb, cid, lignes=GROS, paye=_montant_paye(GROS))
    brouillon, _ = _facture(
        run, qb, cid, lignes=[("Phase 2", 1000.0)], status="draft", lier=False
    )
    r = client.post(f"/api/v1/factures/{fid}/reports-solde", headers=auth_headers)
    assert r.status_code == 201, r.text
    ligne = _items(run, brouillon)[-1]
    assert ligne.kind == "report"

    # Son montant ne se modifie pas (il vient de la facture d'origine).
    r = client.patch(
        f"/api/v1/factures/{brouillon}/items/{ligne.id}",
        headers=auth_headers,
        json={"unit_price": 10.0},
    )
    assert r.status_code == 409

    r = client.delete(
        f"/api/v1/factures/{brouillon}/items/{ligne.id}", headers=auth_headers
    )
    assert r.status_code == 204, r.text
    (rep,) = _reports(run, fid)
    assert rep.statut == "en_attente" and rep.facture_exclue_id == brouillon
    assert float(_lire(run, brouillon).total) == 1149.75
    # Rouvrir CE brouillon ne la remet pas ; le suivant la prend.
    client.get(f"/api/v1/factures/{brouillon}", headers=auth_headers)
    assert [it.kind for it in _items(run, brouillon)] == ["service"]
    suivant, _ = _facture(
        run, qb, cid, lignes=[("Phase 3", 200.0)], status="draft", lier=False
    )
    client.get(f"/api/v1/factures/{suivant}", headers=auth_headers)
    assert [it.kind for it in _items(run, suivant)] == ["service", "report"]


# ── 5. Annulation ; refus de QuickBooks ────────────────────────────────


def test_annuler_le_report_rouvre_la_facture_et_retire_le_paiement_qb(
    qb, run, client, auth_headers
):
    cid = _client(run, qb)
    fid, iid = _facture(run, qb, cid, lignes=GROS, paye=_montant_paye(GROS))
    brouillon, _ = _facture(
        run, qb, cid, lignes=[("Phase 2", 1000.0)], status="draft", lier=False
    )
    r = client.post(f"/api/v1/factures/{fid}/reports-solde", headers=auth_headers)
    assert r.status_code == 201, r.text
    rid, pid = r.json()["id"], r.json()["qbo_payment_id"]

    r = client.delete(f"/api/v1/factures/{fid}/reports-solde/{rid}", headers=auth_headers)
    assert r.status_code == 204, r.text
    assert pid not in qb.payments
    assert qb.invoices[iid]["Balance"] == 15.0
    assert _lire(run, fid).status == "sent"
    assert [it.kind for it in _items(run, brouillon)] == ["service"]
    assert float(_lire(run, brouillon).total) == 1149.75
    (rep,) = _reports(run, fid)
    assert rep.statut == "annule"

    # Refus de QB au report manuel : rien n'est enregistré dans Kratos.
    qb.refus_paiement = "QBO 400 : compte de dépôt invalide"
    r = client.post(f"/api/v1/factures/{fid}/reports-solde", headers=auth_headers)
    assert r.status_code == 409
    assert "compte de dépôt invalide" in r.json()["detail"]
    assert _lire(run, fid).status == "sent"
    assert [x.statut for x in _reports(run, fid)] == ["annule"]
    assert [it.kind for it in _items(run, brouillon)] == ["service"]


def test_annulation_refusee_si_le_solde_est_deja_facture(qb, run, client, auth_headers):
    cid = _client(run, qb)
    fid, _ = _facture(run, qb, cid, lignes=GROS, paye=_montant_paye(GROS))
    brouillon, _ = _facture(
        run, qb, cid, lignes=[("Phase 2", 1000.0)], status="draft", lier=False
    )
    r = client.post(f"/api/v1/factures/{fid}/reports-solde", headers=auth_headers)
    rid = r.json()["id"]
    r = client.patch(
        f"/api/v1/factures/{brouillon}", headers=auth_headers, json={"status": "sent"}
    )
    assert r.status_code == 200, r.text
    _attendre_taches(run)
    r = client.delete(f"/api/v1/factures/{fid}/reports-solde/{rid}", headers=auth_headers)
    assert r.status_code == 409
    assert "déjà facturé" in r.json()["detail"]


# ── 6. Rapatriement QB, état de compte, PDF ───────────────────────────


def test_rapatriement_qb_etat_de_compte_et_pdf(qb, run, client, auth_headers):
    cid = _client(run, qb)
    fid, _ = _facture(run, qb, cid, lignes=GROS, paye=_montant_paye(GROS))
    brouillon, _ = _facture(
        run, qb, cid, lignes=[("Phase 2", 1000.0)], status="draft", lier=False
    )
    r = client.post(f"/api/v1/factures/{fid}/reports-solde", headers=auth_headers)
    pid = r.json()["qbo_payment_id"]

    async def _ids() -> set[str]:
        async with TestSessionLocal() as s:
            return await rep_mod.ids_paiements_qb_des_reports(s)

    assert pid in run(_ids())

    # PDF du brouillon : rendu sans erreur.
    from app.services.facture_pdf import render_facture_pdf

    async def _pdf() -> bytes:
        async with TestSessionLocal() as s:
            return await render_facture_pdf(s, brouillon)

    _fa, pdf = run(_pdf())
    assert pdf[:4] == b"%PDF"

    # État de compte du projet : le solde reporté ferme la facture
    # d'origine (ligne dédiée) et n'est dû qu'une fois, sur la suivante.
    from app.models.project import Project
    from app.services.facture_pdf import _build_statement

    async def _releve():
        async with TestSessionLocal() as s:
            pr = Project(name=f"Projet report {uuid.uuid4().hex[:6]}", client_id=cid)
            s.add(pr)
            await s.flush()
            for f in (fid, brouillon):
                (await s.get(Facture, f)).project_id = pr.id
            await s.flush()
            st = await _build_statement(s, pr, include_facture_id=brouillon)
            await s.rollback()
            return st

    st = run(_releve())
    origine, b = _lire(run, fid), _lire(run, brouillon)
    assert st.billed_to_date == round(float(origine.total) + float(b.total), 2)
    assert st.remaining_balance == float(b.total)
    assert any("Solde reporté sur la prochaine facture" in li.label for li in st.lines)

    r = client.get("/api/v1/reports-solde", headers=auth_headers, params={"client_id": cid})
    assert r.status_code == 200, r.text
    assert [x["origine_facture_id"] for x in r.json()] == [fid]


def test_totaux_facture_ajoute_les_reports_apres_les_taxes():
    t = totaux_facture([("service", 1000.0), ("report", 15.0), ("rabais", -100.0)])
    assert t == {
        "subtotal": 900.0, "tps": 45.0, "tvq": 89.78, "reports": 15.0,
        "total": 1049.78,
    }
