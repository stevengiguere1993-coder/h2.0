"""Smoke — le reçu d'un achat suit TOUJOURS dans QuickBooks, et un achat
supprimé dans Kratos disparaît de QuickBooks (Steven, 2026-11-04).

Cas réels : A-520 et A-462 (Amazon) poussés dans QB à la création, PDF
téléversé 14 s plus tard → jamais joint dans QB ; #539 supprimé dans
Kratos → dépense QB orpheline.

Faux QuickBooks, aucun appel réseau. Couvre :
1. achat créé (auto-push → Purchase sans pièce), PDF arrivé APRÈS → la
   pièce est jointe en fond ; une re-synchro ne la renvoie pas ;
2. reçu REMPLACÉ → nouvelle pièce, l'ancienne retirée de QB ;
   reçu SUPPRIMÉ → la pièce quitte QB ;
3. synchro d'un achat qui a déjà son reçu → pièce jointe à la création,
   pas une 2ᵉ fois à la re-synchro ;
4. reçu divisé → UNE pièce sur la transaction, l'Id sur chaque part ;
5. rattrapage (filet horaire) : QB porte déjà une pièce (achat d'avant la
   colonne) → reliée, pas doublée ; QB n'en a pas → téléversée ; achat
   déjà marqué → ignoré ;
6. suppression d'un achat → la dépense QB (et sa pièce) est supprimée ;
   refus QB → 409 et rien n'est supprimé ; transaction partagée → QB
   intact.
"""

from __future__ import annotations

import base64
import copy
import hashlib
import hmac
import json
import uuid
from datetime import date
from typing import Any, Dict, List

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.models.achat import Achat
from app.services.achat_piece_qbo import rattraper_pieces_qbo
from app.services.achat_qbo import sync_achat_to_qbo

from .conftest import TestSessionLocal
from .test_smoke_achat_divise_2026_10_30 import (  # noqa: F401 — fixture
    PDF,
    _achats,
    _attendre,
    _corps,
    _FauxQB,
    chantiers,
)

PDF2 = b"%PDF-1.4 recu remplace"


class _FauxQBPieces(_FauxQB):
    """Le faux QB du reçu divisé + les pièces jointes (Attachable) :
    téléversement, liste, retrait, et paiements de facture."""

    def __init__(self, **kw: Any) -> None:
        super().__init__(**kw)
        self.attachables: Dict[str, Dict[str, Any]] = {}
        self.pieces_retirees: List[str] = []
        self.paiements_supprimes: List[str] = []

    async def upload_attachment(self, **kw: Any) -> Dict[str, Any]:
        self.pieces.append(kw)
        aid = self._next("ATT")
        self.attachables[aid] = {
            "Id": aid,
            "FileName": kw["file_name"],
            "ContentType": kw["content_type"],
            "AttachableRef": [
                {"EntityRef": {"type": kw["entity_type"], "value": kw["entity_id"]}}
            ],
        }
        return {"AttachableResponse": [{"Attachable": {"Id": aid}}]}

    def deposer_piece_dans_qb(self, type_qb: str, id_qb: str) -> str:
        """Une pièce déposée directement dans QuickBooks (ou jointe à la
        création avant la colonne qbo_attachable_id)."""
        aid = self._next("QBATT")
        self.attachables[aid] = {
            "Id": aid,
            "FileName": "recu-qb.pdf",
            "ContentType": "application/pdf",
            "AttachableRef": [{"EntityRef": {"type": type_qb, "value": id_qb}}],
        }
        return aid

    async def query_all(self, sql: str, **_: Any) -> List[Dict[str, Any]]:
        if "attachable" in sql.lower():
            return [copy.deepcopy(a) for a in self.attachables.values()]
        return []

    async def delete_attachable(self, attachable_id: str) -> bool:
        self.pieces_retirees.append(attachable_id)
        return self.attachables.pop(attachable_id, None) is not None

    async def delete_bill_payment(self, bp_id: str) -> bool:
        self.paiements_supprimes.append(bp_id)
        return True


@pytest.fixture()
def faux_qb(monkeypatch, chantiers) -> _FauxQBPieces:
    fake = _FauxQBPieces(
        parent_id=chantiers["parent"],
        jobs={
            chantiers["job_a"]: f"Chantier A {chantiers['tag']}",
            chantiers["job_b"]: f"Chantier B {chantiers['tag']}",
        },
    )
    monkeypatch.setattr("app.services.achat_qbo.get_qbo", lambda *a, **k: fake)
    monkeypatch.setattr("app.services.achat_piece_qbo.get_qbo", lambda *a, **k: fake)
    monkeypatch.setattr(
        "app.services.achat_suppression_qbo.get_qbo", lambda *a, **k: fake
    )
    monkeypatch.setattr(
        "app.api.v1.endpoints.qbo_webhook.get_qbo", lambda *a, **k: fake
    )
    monkeypatch.setattr(settings, "qbo_purchase_tax_code", "5")
    return fake


def _achat_simple(ch: dict, **extra: Any) -> Dict[str, Any]:
    """Le corps exact de l'achat A-520 (fiche Kratos, carte CC Steven)."""
    base: Dict[str, Any] = {
        "status": "received",
        "project_id": ch["a"],
        "fournisseur_id": ch["fournisseur"],
        "kind": "material",
        "description": "poignee de porte",
        "amount": 49.99,
        "amount_tps": 2.5,
        "amount_tvq": 4.99,
        "amount_taxes": 7.49,
        "is_billable": False,
        "payment_method": "cc_steven",
        "invoice_date": "2026-10-14",
    }
    base.update(extra)
    return base


def _creer(client, auth_headers, run, faux_qb, ch: dict, **extra: Any) -> dict:
    """Crée l'achat par l'API et attend son auto-push (Purchase créée,
    SANS pièce : le reçu n'est pas encore là)."""
    avant = len(faux_qb.purchases)
    res = client.post("/api/v1/achats", headers=auth_headers, json=_achat_simple(ch, **extra))
    assert res.status_code == 201, res.text
    body = res.json()
    _attendre(run, lambda: len(faux_qb.purchases) == avant + 1)
    _attendre(run, lambda: _achats(run, [body["id"]])[0].qbo_bill_id is not None)
    return body


def _televerser(client, auth_headers, achat_id: int, contenu: bytes = PDF) -> None:
    up = client.post(
        f"/api/v1/achats/{achat_id}/receipt", headers=auth_headers,
        files={"file": ("recu.pdf", contenu, "application/pdf")},
    )
    assert up.status_code == 204, up.text


def _inserer_achat(run, ch: dict, **champs: Any) -> int:
    """Un achat écrit directement en base (stock existant)."""
    async def _go() -> int:
        async with TestSessionLocal() as s:
            a = Achat(
                fournisseur_id=ch["fournisseur"],
                project_id=ch["a"],
                description="Stock existant",
                amount=100.0,
                amount_taxes=14.98,
                amount_tps=5.0,
                amount_tvq=9.98,
                invoice_date=date(2026, 10, 20),
                status="paid",
                payment_method="cc_steven",
                kind="material",
                receipt_image=PDF,
                receipt_image_content_type="application/pdf",
            )
            for k, v in champs.items():
                setattr(a, k, v)
            s.add(a)
            await s.commit()
            return int(a.id)

    return run(_go())


def _purchase_qb(faux_qb: _FauxQBPieces, doc: str) -> str:
    """Une dépense QB existante (poussée avant la colonne, ou importée)."""
    pid = faux_qb._next("P")
    faux_qb.purchases[pid] = {
        "Id": pid, "SyncToken": "0", "DocNumber": doc, "TotalAmt": 114.98,
        "Balance": 0.0, "Line": [],
    }
    return pid


# ── 1) A-520 : PDF arrivé après l'auto-push → joint quand même ────────


def test_pdf_arrive_apres_la_creation_suit_dans_qb(
    client, auth_headers, run, chantiers, faux_qb
):
    ach = _creer(client, auth_headers, run, faux_qb, chantiers)
    assert faux_qb.pieces == []  # poussé sans reçu, comme A-520
    purchase_id = _achats(run, [ach["id"]])[0].qbo_bill_id

    _televerser(client, auth_headers, ach["id"])
    _attendre(run, lambda: len(faux_qb.pieces) == 1)
    piece = faux_qb.pieces[0]
    assert (piece["entity_type"], piece["entity_id"]) == ("Purchase", purchase_id)
    assert piece["file_name"] == f"facture-A{ach['id']}.pdf"
    assert piece["content"] == PDF
    a = _achats(run, [ach["id"]])[0]
    assert a.qbo_attachable_id in faux_qb.attachables
    fiche = client.get(f"/api/v1/achats/{ach['id']}", headers=auth_headers).json()
    assert fiche["qbo_attachable_id"] == a.qbo_attachable_id

    # Re-synchro : la pièce est déjà là, on ne la renvoie pas.
    res = client.post(f"/api/v1/achats/{ach['id']}/qbo/sync", headers=auth_headers)
    assert res.status_code == 200, res.text
    assert res.json()["receipt_attached"] is False
    assert len(faux_qb.pieces) == 1
    # Bouton « joindre maintenant » : rien à faire non plus.
    r = client.post(f"/api/v1/achats/{ach['id']}/qbo/piece", headers=auth_headers)
    assert r.status_code == 200 and r.json()["statut"] == "deja"
    assert len(faux_qb.pieces) == 1


# ── 2) Remplacement et suppression du reçu ────────────────────────────


def test_recu_remplace_puis_supprime_suit_dans_qb(
    client, auth_headers, run, chantiers, faux_qb
):
    ach = _creer(client, auth_headers, run, faux_qb, chantiers)
    _televerser(client, auth_headers, ach["id"])
    _attendre(run, lambda: len(faux_qb.pieces) == 1)
    premiere = _achats(run, [ach["id"]])[0].qbo_attachable_id

    _televerser(client, auth_headers, ach["id"], PDF2)
    _attendre(run, lambda: len(faux_qb.pieces) == 2)
    assert faux_qb.pieces[1]["content"] == PDF2
    seconde = _achats(run, [ach["id"]])[0].qbo_attachable_id
    assert seconde != premiere and seconde in faux_qb.attachables
    assert premiere in faux_qb.pieces_retirees and premiere not in faux_qb.attachables

    sup = client.delete(f"/api/v1/achats/{ach['id']}/receipt", headers=auth_headers)
    assert sup.status_code == 204, sup.text
    _attendre(run, lambda: seconde in faux_qb.pieces_retirees)
    a = _achats(run, [ach["id"]])[0]
    assert a.qbo_attachable_id is None and a.receipt_image_content_type is None
    assert faux_qb.attachables == {}


# ── 3) Reçu déjà là à la synchro → joint à la création, une seule fois ─


def test_synchro_avec_recu_joint_une_seule_fois(run, chantiers, faux_qb):
    aid = _inserer_achat(run, chantiers)

    async def _sync() -> dict:
        async with TestSessionLocal() as s:
            r = await sync_achat_to_qbo(s, aid)
            await s.commit()
            return r

    r1 = run(_sync())
    assert r1["receipt_attached"] is True and len(faux_qb.pieces) == 1
    a = _achats(run, [aid])[0]
    assert a.qbo_attachable_id in faux_qb.attachables
    r2 = run(_sync())
    assert r2["receipt_attached"] is False and len(faux_qb.pieces) == 1


# ── 4) Reçu divisé : une pièce, l'Id sur chaque part ──────────────────


def test_recu_divise_une_piece_pour_le_groupe(
    client, auth_headers, run, chantiers, faux_qb
):
    res = client.post("/api/v1/achats/divise", headers=auth_headers, json=_corps(chantiers))
    assert res.status_code == 201, res.text
    tete, autre = res.json()["parts"]
    _attendre(run, lambda: len(faux_qb.bills) == 1)
    bill_id = next(iter(faux_qb.bills))

    _televerser(client, auth_headers, tete["id"])
    _attendre(run, lambda: len(faux_qb.pieces) == 1)
    assert (faux_qb.pieces[0]["entity_type"], faux_qb.pieces[0]["entity_id"]) == ("Bill", bill_id)
    parts = _achats(run, [tete["id"], autre["id"]])
    assert {p.qbo_attachable_id for p in parts} == set(faux_qb.attachables)

    # Re-synchro par l'autre part : rien de plus.
    res = client.post(f"/api/v1/achats/{autre['id']}/qbo/sync", headers=auth_headers)
    assert res.status_code == 200 and len(faux_qb.pieces) == 1


# ── 5) Rattrapage du stock existant ───────────────────────────────────


def test_rattrapage_relie_ou_televerse_sans_doubler(run, chantiers, faux_qb):
    tag = uuid.uuid4().hex[:6]
    # a) poussé avant la colonne : QB porte déjà la pièce → reliée.
    p_a = _purchase_qb(faux_qb, f"RA-{tag}")
    deja = faux_qb.deposer_piece_dans_qb("Purchase", p_a)
    a_id = _inserer_achat(run, chantiers, qbo_bill_id=p_a, qbo_doc_number=f"RA-{tag}")
    # b) jamais jointe (A-520) → téléversée.
    p_b = _purchase_qb(faux_qb, f"RB-{tag}")
    b_id = _inserer_achat(run, chantiers, qbo_bill_id=p_b, qbo_doc_number=f"RB-{tag}")
    # c) déjà marquée → ignorée.
    p_c = _purchase_qb(faux_qb, f"RC-{tag}")
    c_id = _inserer_achat(
        run, chantiers, qbo_bill_id=p_c, qbo_doc_number=f"RC-{tag}", qbo_attachable_id="ATT-x",
    )
    # d) pas de transaction QB → rien à faire, pas d'erreur.
    d_id = _inserer_achat(run, chantiers)

    out = run(rattraper_pieces_qbo(limit=50))
    assert out["erreurs"] == 0
    assert out["relies"] >= 1 and out["joints"] >= 1
    a, b, c, d = _achats(run, [a_id, b_id, c_id, d_id])
    assert a.qbo_attachable_id == deja
    assert b.qbo_attachable_id in faux_qb.attachables and b.qbo_attachable_id != deja
    assert c.qbo_attachable_id == "ATT-x"
    assert d.qbo_attachable_id is None
    assert [p["entity_id"] for p in faux_qb.pieces] == [p_b]

    # Second passage : plus rien à faire.
    out2 = run(rattraper_pieces_qbo(limit=50))
    assert out2["joints"] == 0 and out2["relies"] == 0
    assert len(faux_qb.pieces) == 1


# ── 6) Suppression d'un achat → la dépense QB disparaît ───────────────


def test_supprimer_l_achat_supprime_la_depense_qb(
    client, auth_headers, run, chantiers, faux_qb
):
    ach = _creer(client, auth_headers, run, faux_qb, chantiers)
    _televerser(client, auth_headers, ach["id"])
    _attendre(run, lambda: len(faux_qb.pieces) == 1)
    purchase_id = _achats(run, [ach["id"]])[0].qbo_bill_id
    piece_id = _achats(run, [ach["id"]])[0].qbo_attachable_id

    sup = client.delete(f"/api/v1/achats/{ach['id']}", headers=auth_headers)
    assert sup.status_code in (200, 204), sup.text
    assert _achats(run, [ach["id"]]) == []
    assert purchase_id not in faux_qb.purchases
    assert piece_id in faux_qb.pieces_retirees


def test_refus_qb_bloque_la_suppression(
    client, auth_headers, run, chantiers, faux_qb, monkeypatch
):
    ach = _creer(client, auth_headers, run, faux_qb, chantiers)
    purchase_id = _achats(run, [ach["id"]])[0].qbo_bill_id

    async def _refus(_pid: str) -> bool:
        return False

    monkeypatch.setattr(faux_qb, "delete_purchase", _refus)
    sup = client.delete(f"/api/v1/achats/{ach['id']}", headers=auth_headers)
    assert sup.status_code == 409, sup.text
    assert "QuickBooks" in sup.json()["detail"]
    assert len(_achats(run, [ach["id"]])) == 1
    assert purchase_id in faux_qb.purchases


def test_transaction_partagee_reste_dans_qb(
    client, auth_headers, run, chantiers, faux_qb
):
    """Facture fractionnée importée de QB : deux achats (un par projet),
    même dépense QB, sans groupe → supprimer l'un ne touche pas QB."""
    tag = uuid.uuid4().hex[:6]
    pid = _purchase_qb(faux_qb, f"FR-{tag}")
    un = _inserer_achat(run, chantiers, qbo_bill_id=pid, qbo_doc_number=f"FR-{tag}")
    deux = _inserer_achat(run, chantiers, qbo_bill_id=pid, qbo_doc_number=f"FR-{tag}")

    sup = client.delete(f"/api/v1/achats/{un}", headers=auth_headers)
    assert sup.status_code in (200, 204), sup.text
    assert pid in faux_qb.purchases
    assert len(_achats(run, [deux])) == 1

    # Dernier achat de la transaction → elle part.
    sup = client.delete(f"/api/v1/achats/{deux}", headers=auth_headers)
    assert sup.status_code in (200, 204), sup.text
    assert pid not in faux_qb.purchases


# ── 7) Sens inverse : supprimée dans QuickBooks → disparaît de Kratos ──


def _webhook(client, monkeypatch, entites: List[Dict[str, str]]) -> None:
    """Un événement Intuit signé (base64(HMAC-SHA256(corps, jeton)))."""
    monkeypatch.setattr(settings, "qbo_webhook_verifier_token", "jeton-smoke")
    # Realm de la compagnie Construction : d'autres smoke tests laissent
    # des connexions QB « 9130 » en base ; sans realm configuré, le webhook
    # les prendrait pour d'autres compagnies et ignorerait l'événement.
    monkeypatch.setattr(settings, "qbo_realm_id", "9130")
    corps = json.dumps(
        {"eventNotifications": [{"realmId": "9130", "dataChangeEvent": {"entities": entites}}]}
    ).encode()
    sig = base64.b64encode(hmac.new(b"jeton-smoke", corps, hashlib.sha256).digest()).decode()
    r = client.post(
        "/api/v1/qbo/webhook", content=corps,
        headers={"intuit-signature": sig, "content-type": "application/json"},
    )
    assert r.status_code == 200, r.text


def test_depense_supprimee_dans_qb_disparait_de_kratos(
    client, auth_headers, run, chantiers, faux_qb, monkeypatch
):
    ach = _creer(client, auth_headers, run, faux_qb, chantiers)
    pid = _achats(run, [ach["id"]])[0].qbo_bill_id

    # Événement rejoué / transaction toujours là → rien ne bouge.
    _webhook(client, monkeypatch, [{"name": "Purchase", "id": pid, "operation": "Delete"}])
    assert len(_achats(run, [ach["id"]])) == 1

    # Supprimée pour de bon dans QB → l'achat disparaît de Kratos.
    faux_qb.purchases.pop(pid)
    _webhook(client, monkeypatch, [{"name": "Purchase", "id": pid, "operation": "Delete"}])
    _attendre(run, lambda: _achats(run, [ach["id"]]) == [])
    audit = client.get(
        "/api/v1/audit", headers=auth_headers,
        params={"entity_type": "achats", "entity_id": ach["id"], "action": "achats.deleted"},
    ).json()
    assert any(
        e["user_email"] is None and "quickbooks" in e["details_json"] for e in audit
    )


def test_achat_refacture_est_annule_pas_supprime(
    client, auth_headers, run, chantiers, faux_qb, monkeypatch
):
    from datetime import datetime, timezone

    tag = uuid.uuid4().hex[:6]
    pid = _purchase_qb(faux_qb, f"RF-{tag}")
    aid = _inserer_achat(
        run, chantiers, qbo_bill_id=pid, qbo_doc_number=f"RF-{tag}",
        invoiced_at=datetime(2026, 10, 26, tzinfo=timezone.utc),
    )
    faux_qb.purchases.pop(pid)
    _webhook(client, monkeypatch, [{"name": "Purchase", "id": pid, "operation": "Delete"}])
    _attendre(run, lambda: _achats(run, [aid])[0].status == "cancelled")
    a = _achats(run, [aid])[0]
    assert a.qbo_bill_id is None and a.qbo_attachable_id is None
