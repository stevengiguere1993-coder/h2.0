"""Smoke — factures Kratos « envoyées » dans QuickBooks (2026-10-16).

Steven : 19 tâches « Review Invoice 126, 127, 131… » dans « Nécessite
votre attention » de QuickBooks, pour des factures déjà envoyées depuis
Kratos. Cause : le flux QB « Get unsent invoice reminder » (facture créée
ou modifiée ET état d'envoi « Non envoyé » → tâche). Les Invoices que
Kratos crée n'avaient pas d'état d'envoi.

Couvre :
1. une facture émise part dans QB marquée envoyée, avec le courriel du
   client ;
2. la mise à jour d'une Invoice « Non envoyé » la passe à envoyée, sans
   remplacer le courriel déjà dans QB ;
3. QB refuse l'état d'envoi → la facture part quand même sans lui ;
4. filet horaire : les Invoices encore « Non envoyé » sont marquées par
   une mise à jour d'en-tête (lignes, total, solde, date intacts), les
   déjà envoyées et les brouillons laissés tranquilles, un refus QB pas
   retenté sans fin.

QuickBooks est simulé en mémoire : aucun appel réseau.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import select

import app.services.facture_qbo as fq
from app.integrations.quickbooks import QuickBooksError
from app.models.client import Client
from app.models.facture import Facture
from tests.smoke.conftest import TestSessionLocal
from tests.smoke.test_smoke_facture_qbo_miroir_2026_10_14 import (  # noqa: F401
    QBMiroir,
    _base,
    _seed,
    _sync,
    qb,
)


def _courriel_client(run, fid: int, email: Optional[str]) -> None:
    async def _go() -> None:
        async with TestSessionLocal() as s:
            fa = (await s.execute(select(Facture).where(Facture.id == fid))).scalar_one()
            cl = (await s.execute(select(Client).where(Client.id == fa.client_id))).scalar_one()
            cl.email = email
            await s.commit()

    run(_go())


def _non_envoyee(qb: QBMiroir, iid: str, *, courriel: bool = True) -> None:
    """L'Invoice telle que Kratos la créait avant : « Non envoyé »."""
    inv = qb.invoices[iid]
    inv["EmailStatus"] = "NotSet"
    if not courriel:
        inv.pop("BillEmail", None)


def test_facture_emise_creee_dans_qb_marquee_envoyee(qb, run):
    ref = str(_base() + 126)
    fid, _ = _seed(run, qb, reference=ref, lignes=[("Travaux", 1000.0)], lier=False)
    _courriel_client(run, fid, "client@example.com")

    _sync(run, fid)

    [creation] = qb.creations
    assert creation["EmailStatus"] == "EmailSent"
    assert creation["BillEmail"] == {"Address": "client@example.com"}


def test_mise_a_jour_passe_l_invoice_a_envoyee(qb, run):
    ref = str(_base() + 127)
    fid, iid = _seed(run, qb, reference=ref, lignes=[("Travaux", 131.53)])
    _non_envoyee(qb, iid)
    _courriel_client(run, fid, "autre@example.com")

    _sync(run, fid)

    inv = qb.invoices[iid]
    assert inv["EmailStatus"] == "EmailSent"
    # Le courriel déjà dans QB reste.
    assert inv["BillEmail"] == {"Address": "samuel@example.com"}
    assert not qb.creations


def test_mise_a_jour_ajoute_le_courriel_client_s_il_manque(qb, run):
    ref = str(_base() + 131)
    fid, iid = _seed(run, qb, reference=ref, lignes=[("Travaux", 126.47)])
    _non_envoyee(qb, iid, courriel=False)
    _courriel_client(run, fid, "client@example.com")

    _sync(run, fid)

    inv = qb.invoices[iid]
    assert inv["EmailStatus"] == "EmailSent"
    assert inv["BillEmail"] == {"Address": "client@example.com"}


def test_qb_refuse_l_etat_envoye_la_facture_part_quand_meme(qb, run, monkeypatch):
    ref = str(_base() + 130)
    fid, _ = _seed(run, qb, reference=ref, lignes=[("Travaux", 500.0)], lier=False)
    origine = qb.create_invoice

    async def _refuse(payload):
        if payload.get("EmailStatus"):
            raise QuickBooksError(
                "QBO 400 : Email Address is required for EmailStatus (2050)"
            )
        return await origine(payload)

    monkeypatch.setattr(qb, "create_invoice", _refuse)

    res = _sync(run, fid)

    assert res["qbo_invoice_id"]
    [creation] = qb.creations
    assert "EmailStatus" not in creation
    assert creation["DocNumber"] == ref


def test_filet_marque_envoyees_les_invoices_non_envoyees(qb, run):
    base = _base()
    fid_a, iid_a = _seed(run, qb, reference=str(base + 134), lignes=[("A", 280.0)])
    fid_b, iid_b = _seed(run, qb, reference=str(base + 132), lignes=[("B", 12763.0)])
    _, iid_c = _seed(run, qb, reference=str(base + 129), lignes=[("C", 1522.0)])
    _, iid_d = _seed(
        run, qb, reference=str(base + 900), lignes=[("D", 10.0)], status="draft"
    )
    _non_envoyee(qb, iid_a, courriel=False)
    _non_envoyee(qb, iid_b)
    _non_envoyee(qb, iid_d)
    _courriel_client(run, fid_a, "azad@example.com")
    # Paiement partiel déjà imputé dans QB : il doit rester.
    qb.payer_dans_qb(iid_b, 1000.0)
    avant = {
        iid: {
            k: qb.invoices[iid].get(k)
            for k in ("Line", "TotalAmt", "Balance", "TxnDate", "DueDate", "PrivateNote")
        }
        for iid in (iid_a, iid_b)
    }

    res = run(fq.marquer_factures_envoyees_dans_qb())

    assert sorted(res["marquees"]) == sorted([str(base + 134), str(base + 132)])
    assert res["echecs"] == {}
    for iid in (iid_a, iid_b):
        inv = qb.invoices[iid]
        assert inv["EmailStatus"] == "EmailSent"
        for k, v in avant[iid].items():
            assert inv.get(k) == v, k
    assert qb.invoices[iid_a]["BillEmail"] == {"Address": "azad@example.com"}
    assert qb.invoices[iid_b]["BillEmail"] == {"Address": "samuel@example.com"}
    # En-tête seulement : aucune ligne ni montant renvoyé.
    for corps in qb.mises_a_jour:
        assert corps["sparse"] is True
        assert set(corps) <= {"Id", "SyncToken", "sparse", "EmailStatus", "BillEmail"}
    # Déjà envoyée, brouillon : pas touchées.
    touchees = {c["Id"] for c in qb.mises_a_jour}
    assert iid_c not in touchees and iid_d not in touchees
    assert qb.invoices[iid_d]["EmailStatus"] == "NotSet"

    # Deuxième passage : plus rien à faire.
    n = len(qb.mises_a_jour)
    res = run(fq.marquer_factures_envoyees_dans_qb())
    assert res["marquees"] == [] and len(qb.mises_a_jour) == n


def test_filet_ne_retente_pas_un_refus(qb, run, monkeypatch):
    ref = str(_base() + 136)
    _, iid = _seed(run, qb, reference=ref, lignes=[("Travaux", 7265.0)])
    _non_envoyee(qb, iid)
    fq._marquages_envoi_refuses.clear()
    appels = []

    async def _refuse(payload):
        appels.append(payload)
        raise QuickBooksError("QBO 400 : refus (6000)")

    monkeypatch.setattr(qb, "create_invoice", _refuse)

    res = run(fq.marquer_factures_envoyees_dans_qb())
    assert ref in res["echecs"]
    res = run(fq.marquer_factures_envoyees_dans_qb())
    assert res["echecs"] == {}
    assert len(appels) == 1
    fq._marquages_envoi_refuses.clear()


def test_filet_n_insiste_pas_si_qb_ignore_l_etat(qb, run, monkeypatch):
    ref = str(_base() + 138)
    _, iid = _seed(run, qb, reference=ref, lignes=[("Travaux", 296.86)])
    _non_envoyee(qb, iid)
    fq._marquages_envoi_refuses.clear()
    origine = qb.create_invoice

    async def _ignore(payload):
        rep = await origine({k: v for k, v in payload.items() if k != "EmailStatus"})
        return rep

    monkeypatch.setattr(qb, "create_invoice", _ignore)

    res = run(fq.marquer_factures_envoyees_dans_qb())
    assert ref in res["echecs"] and res["marquees"] == []
    n = len(qb.mises_a_jour)
    run(fq.marquer_factures_envoyees_dans_qb())
    assert len(qb.mises_a_jour) == n
    fq._marquages_envoi_refuses.clear()
