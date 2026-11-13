"""Smoke — une tâche de fond qui relit la base part APRÈS l'enregistrement.

Cause de deux échecs au hasard dans la CI (2026-11-13, « la tâche de fond n'a pas
abouti », journal : « Auto-push QBO achat N a échoué (silencieux): Achat N
introuvable ») : à la création d'un achat, l'envoi vers QuickBooks était lancé AVANT
le commit de la requête. La tâche ouvre sa propre session : si elle lisait la base
avant le commit, elle ne voyait pas l'achat et abandonnait en silence (en production,
l'achat attendait alors le filet horaire). Même course à la modification (QuickBooks
recevait les anciennes valeurs), au paiement (« non payé ») et à la conversion d'un
bon de commande (tâche exécutée avant le commit, à tous les coups).

Ces tests rendent la course CERTAINE (le commit de fin de requête est ralenti) et
verrouillent le correctif : ``app.core.apres_commit.lancer_apres_commit``.
Faux QuickBooks, aucun appel réseau.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid

import pytest
from sqlalchemy import text

from app.core import apres_commit
from app.core.apres_commit import en_attente, lancer_apres_commit, lancer_en_fond
from app.db.session import get_db
from app.main import app as fastapi_app
from app.models.purchase_order import PurchaseOrder, PurchaseOrderStatus

from .conftest import TestSessionLocal
from .test_smoke_achat_divise_2026_10_30 import (  # noqa: F401 — fixtures
    _achats,
    _attendre,
    _lignes,
    _simple,
    chantiers,
    faux_qb,
)


@pytest.fixture()
def commit_lent():
    """``with commit_lent(): client.post(...)`` — ralentit le commit de fin de requête
    pour l'appel visé : une tâche de fond lancée avant le commit a tout le temps de
    lire la base. La course devient certaine au lieu de rare."""
    original = fastapi_app.dependency_overrides[get_db]

    async def _get_db_lent():
        async with TestSessionLocal() as session:
            try:
                yield session
                await asyncio.sleep(0.15)
                await session.commit()
            except Exception:
                await session.rollback()
                raise
            finally:
                await session.close()

    @contextlib.contextmanager
    def _activer():
        fastapi_app.dependency_overrides[get_db] = _get_db_lent
        try:
            yield
        finally:
            fastapi_app.dependency_overrides[get_db] = original

    yield _activer
    fastapi_app.dependency_overrides[get_db] = original


def _echecs_silencieux(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records if "introuvable" in r.getMessage() or "échoué" in r.getMessage()]


# ─── Les quatre envois QuickBooks d'un achat ──────────────────────────


def test_achat_cree_part_dans_qb_apres_le_commit(client, auth_headers, run, chantiers, faux_qb, commit_lent, caplog):
    caplog.set_level(logging.INFO)
    with commit_lent():
        res = client.post("/api/v1/achats", headers=auth_headers, json=_simple(chantiers))
    assert res.status_code == 201, res.text
    aid = res.json()["id"]
    _attendre(run, lambda: len(faux_qb.creations) >= 1)
    assert _echecs_silencieux(caplog) == []
    assert [t for t, _ in faux_qb.creations] == ["Purchase"]
    _attendre(run, lambda: _achats(run, [aid])[0].qbo_bill_id is not None)


def test_achat_modifie_pousse_les_nouvelles_valeurs(client, auth_headers, run, chantiers, faux_qb, commit_lent, caplog):
    """Avant le correctif, la tâche relisait l'achat d'AVANT la modification :
    QuickBooks recevait l'ancien montant, sans erreur visible."""
    caplog.set_level(logging.INFO)
    res = client.post("/api/v1/achats", headers=auth_headers, json=_simple(chantiers))
    assert res.status_code == 201, res.text
    aid = res.json()["id"]
    _attendre(run, lambda: _achats(run, [aid])[0].qbo_bill_id is not None)
    achat_qb = next(iter(faux_qb.purchases.values()))
    assert [ln["Amount"] for ln in _lignes(achat_qb)] == [1000.0]

    with commit_lent():
        r = client.patch(
            f"/api/v1/achats/{aid}", headers=auth_headers,
            json={"amount": 1200.0, "amount_taxes": 179.7, "amount_tps": 60.0, "amount_tvq": 119.7},
        )
    assert r.status_code == 200, r.text
    _attendre(run, lambda: len(faux_qb.updates) >= 1)
    assert _echecs_silencieux(caplog) == []
    # La mise à jour partie dans QB porte le NOUVEAU montant.
    assert [ln["Amount"] for ln in _lignes(faux_qb.updates[-1][1])] == [1200.0]
    _attendre(run, lambda: [ln["Amount"] for ln in _lignes(next(iter(faux_qb.purchases.values())))] == [1200.0])
    assert len(faux_qb.creations) == 1, "une modification ne crée jamais une 2e transaction"


def test_marquer_paye_cree_le_paiement_dans_qb(client, auth_headers, run, chantiers, faux_qb, commit_lent):
    """Avant le correctif, la tâche voyait parfois l'achat encore « non payé » et
    ne créait pas le paiement de facture dans QuickBooks."""
    corps = _simple(chantiers, payment_method="bill_to_pay", status="received")
    corps["supplier_invoice_number"] = f"MP-{chantiers['tag']}"
    res = client.post("/api/v1/achats", headers=auth_headers, json=corps)
    assert res.status_code == 201, res.text
    aid = res.json()["id"]
    _attendre(run, lambda: _achats(run, [aid])[0].qbo_bill_id is not None)
    assert [t for t, _ in faux_qb.creations] == ["Bill"]

    with commit_lent():
        mp = client.post(
            f"/api/v1/achats/{aid}/mark-paid", headers=auth_headers,
            json={"payment_method": "cc_steven", "paid_at": "2026-10-29T15:00:00Z"},
        )
    assert mp.status_code == 200, mp.text
    _attendre(run, lambda: len(faux_qb.bill_payments) == 1 and bool(_achats(run, [aid])[0].qbo_bill_payment_id))
    achat = _achats(run, [aid])[0]
    assert achat.status == "paid" and achat.qbo_bill_payment_id == faux_qb.bill_payments[0]["Id"]
    assert faux_qb.bill_payments[0]["TotalAmt"] == 1149.75


def test_bon_de_commande_converti_part_dans_qb(client, auth_headers, run, chantiers, faux_qb, caplog):
    """Sans ralentir le commit : la tâche de fond s'exécutait AVANT le commit de la
    requête, donc « Achat introuvable » à tous les coups."""
    caplog.set_level(logging.INFO)
    ch = chantiers

    async def _po() -> int:
        async with TestSessionLocal() as s:
            po = PurchaseOrder(
                reference=f"PO-{uuid.uuid4().hex[:10]}", fournisseur_id=ch["fournisseur"], project_id=ch["a"],
                description="Vis et quincaillerie", amount_max=250.0, payment_method="cc_steven",
                status=PurchaseOrderStatus.SENT.value,
            )
            s.add(po)
            await s.commit()
            return po.id

    po_id = run(_po())
    res = client.post(
        f"/api/v1/purchase-orders/{po_id}/convert-to-achat", headers=auth_headers,
        json={"amount": 230.0, "supplier_invoice_number": f"PO-{ch['tag']}", "invoice_date": "2026-11-12"},
    )
    assert res.status_code == 200, res.text
    aid = res.json()["id"]
    _attendre(run, lambda: len(faux_qb.creations) >= 1)
    assert _echecs_silencieux(caplog) == []
    _attendre(run, lambda: _achats(run, [aid])[0].qbo_bill_id is not None)
    # Avec defer_sync, rien ne part (le reçu sera joint avant le push manuel).
    po2 = run(_po())
    res = client.post(
        f"/api/v1/purchase-orders/{po2}/convert-to-achat?defer_sync=true", headers=auth_headers,
        json={"amount": 80.0, "supplier_invoice_number": f"PO2-{ch['tag']}"},
    )
    assert res.status_code == 200, res.text
    run(asyncio.sleep(0.1))
    assert len(faux_qb.creations) == 1


# ─── Règles de lancer_apres_commit ────────────────────────────────────


def test_regles_de_lancement(run):
    journal: list[str] = []

    async def _tache(nom: str) -> None:
        journal.append(nom)

    async def _scenario() -> None:
        # 1. Rien avant le commit ; au commit, les tâches partent dans l'ordre demandé.
        async with TestSessionLocal() as db:
            await db.execute(text("SELECT 1"))
            lancer_apres_commit(db, lambda: _tache("a"))
            lancer_apres_commit(db, lambda: _tache("b"))
            assert en_attente(db) == 2
            await asyncio.sleep(0.05)
            assert journal == []
            await db.commit()
            assert en_attente(db) == 0
            await asyncio.sleep(0.02)
            assert journal == ["a", "b"]
            # Un 2e commit de la même session ne relance rien.
            await db.execute(text("SELECT 1"))
            await db.commit()
            await asyncio.sleep(0.02)
            assert journal == ["a", "b"]

        # 2. Rollback : rien n'a été enregistré, rien ne part — même si un commit suit.
        async with TestSessionLocal() as db:
            await db.execute(text("SELECT 1"))
            lancer_apres_commit(db, lambda: _tache("annulee"))
            await db.rollback()
            assert en_attente(db) == 0
            await db.execute(text("SELECT 1"))
            await db.commit()

        # 3. Session fermée sans commit : rien ne part.
        async with TestSessionLocal() as db:
            await db.execute(text("SELECT 1"))
            lancer_apres_commit(db, lambda: _tache("fermee"))
        await asyncio.sleep(0.02)
        assert journal == ["a", "b"]

        # 4. SAVEPOINT libéré ou annulé : on attend le commit de la transaction englobante.
        async with TestSessionLocal() as db:
            await db.execute(text("SELECT 1"))
            lancer_apres_commit(db, lambda: _tache("c"))
            async with db.begin_nested():
                await db.execute(text("SELECT 1"))
            await asyncio.sleep(0.02)
            assert journal == ["a", "b"] and en_attente(db) == 1
            with pytest.raises(RuntimeError):
                async with db.begin_nested():
                    raise RuntimeError("annule le savepoint")
            assert en_attente(db) == 1
            await db.commit()
            await asyncio.sleep(0.02)
            assert journal == ["a", "b", "c"]

        # 5. Aucune transaction en cours (tout est déjà validé) : la tâche part tout de suite.
        async with TestSessionLocal() as db:
            assert not db.in_transaction()
            lancer_apres_commit(db, lambda: _tache("d"))
            assert en_attente(db) == 0
            await asyncio.sleep(0.02)
            assert journal == ["a", "b", "c", "d"]

    run(_scenario())


def test_tache_referencee_et_erreur_journalisee(run, caplog):
    async def _scenario() -> None:
        feu_vert = asyncio.Event()

        async def _longue() -> None:
            await feu_vert.wait()

        tache = lancer_en_fond(_longue)
        assert tache is not None and tache in apres_commit._EN_VOL, "référencée tant qu'elle tourne"
        feu_vert.set()
        await tache
        await asyncio.sleep(0)
        assert tache not in apres_commit._EN_VOL

        # Une tâche qui plante ne casse rien : l'erreur est journalisée.
        async def _plante() -> None:
            raise ValueError("boum")

        await lancer_en_fond(_plante)

    with caplog.at_level(logging.ERROR, logger="app.core.apres_commit"):
        run(_scenario())
    assert any("Tâche de fond lancée après commit" in r.getMessage() for r in caplog.records)
