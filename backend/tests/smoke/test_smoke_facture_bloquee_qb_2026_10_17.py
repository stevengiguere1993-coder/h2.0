"""Smoke — facture retenue si QuickBooks la refuse (2026-10-17).

Steven : « Si une facture bloque en envoi à QB, par exemple à cause de son
numéro, ne pas envoyer cette facture au client. La laisser dans brouillon
et mettre une notification dessus. »

Avant : le courriel partait d'abord, QuickBooks recevait la facture
ensuite, en arrière-plan. Un refus de QB (facture 160 : article
« catégorie ») ou un numéro changé par QB arrivait trop tard : le client
avait déjà la facture.

Couvre :
1. QuickBooks refuse → rien ne part au client (409), la facture reste en
   brouillon avec son numéro, le motif lisible est posé sur sa fiche et
   les admins sont prévenus dans la cloche Kratos, une seule fois par
   motif ; une fois le problème réglé, le renvoi passe : QuickBooks
   d'abord, le courriel ensuite, sous le même numéro ;
2. numéro déjà pris dans QB par une autre facture → remplacé AVANT le PDF
   et le courriel (objet et pièce jointe au nouveau numéro) ;
3. connexion QuickBooks rompue → facture retenue, motif de reconnexion ;
4. renvoi d'une facture déjà envoyée que QB refuse de mettre à jour →
   rien ne part, statut et dates inchangés ;
5. courriel en échec après QB → le lien QB reste, le renvoi met à jour la
   même Invoice (pas de doublon) ;
6. facture d'acompte envoyée seule à la signature → retenue de même ;
7. QuickBooks non branché (staging) → envoi comme avant ;
8. le bouton « Envoyer vers QuickBooks » d'un brouillon ne dit plus
   « synchronisée ».

QuickBooks est simulé en mémoire : aucun appel réseau.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, Optional

import pytest
from sqlalchemy import delete, select, update

import app.integrations.quickbooks as qb_mod
import app.services.facture_qbo as fq
import app.services.facture_send as service
from app.integrations.quickbooks import QuickBooksReconnexionRequise
from app.models.audit_log import AuditLog
from app.models.client import Client
from app.models.facture import Facture, FactureStatus
from app.models.facture_item import FactureItem
from app.models.notification import Notification
from app.models.numbering_counter import NumberingCounter
from app.services.numbering import is_provisional_facture_reference
from tests.smoke.conftest import TestSessionLocal
from tests.smoke.test_smoke_facture_qbo_miroir_2026_10_14 import QBMiroir

#: Refus de la facture 160 (ligne « Matériaux » sur une catégorie QB), tel
#: que QuickBooksError le formule.
REFUS_CATEGORIE = (
    "QBO refus : Dans cette opération, un élément est configuré comme une "
    "catégorie au lieu d'un produit ou d'un service — QBO POST /invoice "
    "failed: 400 (intuit_tid=1-6710abc) {'Fault': {'Error': [{'code': '2500'}]}}"
)


class FakeMailer:
    ready = True
    sender = "facturation@immohorizon.com"

    def __init__(self, journal: list[str]) -> None:
        self.journal = journal
        self.sent: list[dict] = []
        self.erreur: Optional[str] = None

    async def send(self, **kw: Any) -> None:
        if self.erreur:
            raise RuntimeError(self.erreur)
        self.journal.append("courriel")
        self.sent.append(kw)


@pytest.fixture()
def envoi(monkeypatch, run, db_setup, seeded_users):
    """QuickBooks en mémoire, courriel et PDF simulés. `journal` garde
    l'ordre des écritures QB et des courriels."""
    journal: list[str] = []
    qb = QBMiroir()
    create_invoice = qb.create_invoice

    async def _create_invoice(payload: Dict[str, Any]) -> Dict[str, Any]:
        res = await create_invoice(payload)
        journal.append("quickbooks")
        return res

    qb.create_invoice = _create_invoice  # type: ignore[method-assign]
    monkeypatch.setattr(fq, "get_qbo", lambda *a, **k: qb)
    monkeypatch.setattr(qb_mod, "get_qbo", lambda *a, **k: qb)
    monkeypatch.setitem(fq.settings.__dict__, "qbo_sales_tax_code", "5")

    mailer = FakeMailer(journal)
    rendus: list[str] = []

    async def _rendu(db, facture_id, include_statement=False):
        fa = await db.get(Facture, facture_id)
        rendus.append(fa.reference)
        return fa, b"%PDF-1.4"

    monkeypatch.setattr(service, "get_mailer", lambda: mailer)
    monkeypatch.setattr(service, "render_facture_pdf", _rendu)

    crees: Dict[str, list[int]] = {"factures": [], "clients": []}

    async def _compteur() -> Optional[int]:
        async with TestSessionLocal() as s:
            return (
                await s.execute(
                    select(NumberingCounter.next_facture_number).where(
                        NumberingCounter.id == 1
                    )
                )
            ).scalar_one_or_none()

    avant = run(_compteur())
    yield {"qb": qb, "mailer": mailer, "journal": journal, "rendus": rendus, "crees": crees}

    async def _nettoyer() -> None:
        async with TestSessionLocal() as s:
            fids = crees["factures"]
            if fids:
                await s.execute(delete(FactureItem).where(FactureItem.facture_id.in_(fids)))
                await s.execute(delete(AuditLog).where(AuditLog.entity_id.in_(fids), AuditLog.entity_type == "facture"))
                await s.execute(delete(Facture).where(Facture.id.in_(fids)))
            if crees["clients"]:
                await s.execute(delete(Client).where(Client.id.in_(crees["clients"])))
            await s.execute(
                delete(Notification).where(Notification.kind == service.KIND_ENVOI_BLOQUE)
            )
            if avant is not None:
                await s.execute(
                    update(NumberingCounter)
                    .where(NumberingCounter.id == 1)
                    .values(next_facture_number=avant)
                )
            await s.commit()

    run(_nettoyer())


def _base() -> int:
    """Plage de numéros propre à chaque test (la base est partagée)."""
    return 400000 + (uuid.uuid4().int % 800) * 1000


def _brouillon(
    run,
    env: dict,
    *,
    reference: Optional[str] = None,
    status: str = FactureStatus.DRAFT.value,
    compteur: Optional[int] = None,
) -> int:
    async def _go() -> int:
        async with TestSessionLocal() as s:
            tag = uuid.uuid4().hex[:6]
            cl = Client(
                name=f"Michael Villiard {tag}",
                email=f"{tag}@example.com",
                qbo_customer_id="C-KRATOS",
            )
            s.add(cl)
            await s.flush()
            fa = Facture(
                reference=reference or f"BR-{tag}",
                client_id=cl.id,
                status=status,
                subtotal=1000.0,
                total=1149.75,
                balance=1149.75,
            )
            s.add(fa)
            await s.flush()
            s.add(
                FactureItem(
                    facture_id=fa.id,
                    position=0,
                    description="Matériaux",
                    quantity=1,
                    unit_price=1000.0,
                    total=1000.0,
                    kind="materiaux",
                )
            )
            if compteur is not None:
                row = (
                    await s.execute(select(NumberingCounter).where(NumberingCounter.id == 1))
                ).scalar_one_or_none()
                if row is None:
                    s.add(NumberingCounter(id=1, next_facture_number=compteur))
                else:
                    row.next_facture_number = compteur
            await s.commit()
            env["crees"]["clients"].append(cl.id)
            env["crees"]["factures"].append(fa.id)
            return int(fa.id)

    return run(_go())


def _facture(run, fid: int) -> Facture:
    async def _go() -> Facture:
        async with TestSessionLocal() as s:
            return (await s.execute(select(Facture).where(Facture.id == fid))).scalar_one()

    return run(_go())


def _notifications(run, fid: int) -> list[Notification]:
    async def _go() -> list[Notification]:
        async with TestSessionLocal() as s:
            return list(
                (
                    await s.execute(
                        select(Notification).where(
                            Notification.kind == service.KIND_ENVOI_BLOQUE,
                            Notification.href == f"/app/facturation/{fid}",
                        )
                    )
                ).scalars()
            )

    return run(_go())


def _envoyer(client, auth_headers, fid: int, **body: Any):
    return client.post(
        f"/api/v1/factures/{fid}/send",
        json={"to": ["client@example.com"], **body},
        headers=auth_headers,
    )


def _invoices_de(qb: QBMiroir, fid: int) -> list[Dict[str, Any]]:
    return [
        i for i in qb.invoices.values()
        if i.get("PrivateNote") == fq.MEMO_KRATOS.format(id=fid)
    ]


# ── 1) Refus de QuickBooks ─────────────────────────────────────────


def test_motif_court_sans_detail_technique():
    assert service.motif_court(REFUS_CATEGORIE) == (
        "Dans cette opération, un élément est configuré comme une catégorie "
        "au lieu d'un produit ou d'un service"
    )
    assert service.motif_court("La facture doit être liée à un client.") == (
        "La facture doit être liée à un client."
    )
    assert service.motif_court(None) == ""


def test_refus_qb_rien_ne_part_et_le_brouillon_porte_le_motif(
    envoi, run, client, auth_headers
):
    qb, mailer = envoi["qb"], envoi["mailer"]
    qb.erreur_creation = REFUS_CATEGORIE
    fid = _brouillon(run, envoi, compteur=_base() + 165)

    r = _envoyer(client, auth_headers, fid)

    assert r.status_code == 409, r.text
    detail = r.json()["detail"]
    assert "non envoyée au client" in detail
    assert "catégorie au lieu d'un produit" in detail
    assert "intuit_tid" not in detail
    assert "reste en brouillon" in detail
    # Rien n'est parti au client.
    assert mailer.sent == []
    fa = _facture(run, fid)
    assert fa.status == FactureStatus.DRAFT.value
    assert fa.issued_at is None
    assert fa.qbo_invoice_id is None
    assert "catégorie au lieu d'un produit" in (fa.qbo_sync_error or "")
    # Le numéro attribué à l'envoi est gardé (le message le cite) : le
    # prochain envoi reprend le même.
    numero = fa.reference
    assert not is_provisional_facture_reference(numero)
    assert f"Facture {numero} non envoyée" in detail
    # Cloche des admins (une notification par admin) : de quoi retrouver
    # la facture et le motif.
    notifs = _notifications(run, fid)
    assert notifs
    assert len({n.user_id for n in notifs}) == len(notifs)
    for n in notifs:
        assert n.title == (
            f"Facture {numero} non envoyée au client : refusée par QuickBooks"
        )
        assert "Michael Villiard" in n.body
        assert "catégorie au lieu d'un produit" in n.body
        assert "intuit_tid" not in n.body

    # Même refus au nouvel essai : même numéro, pas de 2e notification.
    r = _envoyer(client, auth_headers, fid)
    assert r.status_code == 409, r.text
    assert _facture(run, fid).reference == numero
    assert len(_notifications(run, fid)) == len(notifs)
    assert mailer.sent == []

    # Problème réglé : QuickBooks d'abord, le courriel ensuite, même numéro.
    qb.erreur_creation = None
    envoi["journal"].clear()
    r = _envoyer(client, auth_headers, fid)
    assert r.status_code == 200, r.text
    assert envoi["journal"] == ["quickbooks", "courriel"]
    fa = _facture(run, fid)
    assert fa.status == FactureStatus.SENT.value
    assert fa.reference == numero
    assert fa.qbo_sync_error is None
    assert qb.invoices[fa.qbo_invoice_id]["DocNumber"] == numero
    assert len(_invoices_de(qb, fid)) == 1
    assert mailer.sent[-1]["subject"].startswith(f"Facture {numero} ")
    assert mailer.sent[-1]["attachments"][0].name == f"facture-{numero}.pdf"


def test_numero_pris_dans_qb_change_avant_le_courriel(envoi, run, client, auth_headers):
    qb, mailer = envoi["qb"], envoi["mailer"]
    b = _base()
    # Numéro choisi au crayon, déjà pris dans QB par la facture d'un autre.
    qb.ajouter(str(b + 152))
    fid = _brouillon(run, envoi, reference=str(b + 152), compteur=b + 153)

    r = _envoyer(client, auth_headers, fid, subject=f"Facture {b + 152} — chantier 158")

    assert r.status_code == 200, r.text
    nouveau = r.json()["reference"]
    assert nouveau != str(b + 152)
    fa = _facture(run, fid)
    assert qb.invoices[fa.qbo_invoice_id]["DocNumber"] == nouveau
    # Le client reçoit le numéro de QuickBooks : PDF, objet, pièce jointe.
    assert envoi["rendus"] == [nouveau]
    assert mailer.sent[-1]["subject"] == f"Facture {nouveau} — chantier 158"
    assert mailer.sent[-1]["attachments"][0].name == f"facture-{nouveau}.pdf"
    assert f"Numéro changé de {b + 152} à {nouveau}" in (fa.internal_notes or "")


def test_connexion_qb_rompue_retient_la_facture(envoi, run, client, auth_headers):
    qb, mailer = envoi["qb"], envoi["mailer"]

    async def _expiree(**kw: Any) -> Dict[str, Any]:
        raise QuickBooksReconnexionRequise(
            "Connexion QuickBooks expirée : Intuit refuse le jeton enregistré. "
            "Un administrateur doit la reconnecter dans Paramètres → "
            "Comptabilité, bouton « Reconnecter ». (détail: invalid_grant)"
        )

    qb.ensure_customer = _expiree  # type: ignore[method-assign]
    fid = _brouillon(run, envoi, compteur=_base() + 170)

    r = _envoyer(client, auth_headers, fid)

    assert r.status_code == 409, r.text
    assert mailer.sent == []
    fa = _facture(run, fid)
    assert fa.status == FactureStatus.DRAFT.value
    assert "Connexion QuickBooks expirée" in (fa.qbo_sync_error or "")


def test_quickbooks_branche_mais_jamais_connecte(envoi, run, client, auth_headers):
    qb, mailer = envoi["qb"], envoi["mailer"]
    qb.ready = False
    qb.client_id, qb.client_secret = "app-intuit", "secret"  # type: ignore[attr-defined]
    fid = _brouillon(run, envoi, compteur=_base() + 175)

    r = _envoyer(client, auth_headers, fid)

    assert r.status_code == 409, r.text
    assert "QuickBooks n'est pas configuré" in r.json()["detail"]
    assert mailer.sent == []
    assert _facture(run, fid).status == FactureStatus.DRAFT.value


# ── 2) Renvoi d'une facture déjà envoyée ───────────────────────────


def test_renvoi_refuse_par_qb_garde_statut_et_dates(envoi, run, client, auth_headers):
    qb, mailer = envoi["qb"], envoi["mailer"]
    fid = _brouillon(run, envoi, compteur=_base() + 180)
    assert _envoyer(client, auth_headers, fid).status_code == 200
    avant = _facture(run, fid)
    nb_courriels = len(mailer.sent)

    qb.erreurs_maj.append(
        "QBO refus : Business Validation Error — QBO POST /invoice failed: 400 "
        "(intuit_tid=1-xyz) {}"
    )
    r = _envoyer(client, auth_headers, fid)

    assert r.status_code == 409, r.text
    assert "non renvoyée au client" in r.json()["detail"]
    assert len(mailer.sent) == nb_courriels
    fa = _facture(run, fid)
    assert fa.status == FactureStatus.SENT.value
    assert fa.issued_at == avant.issued_at
    assert fa.due_at == avant.due_at
    assert fa.reference == avant.reference
    assert "Business Validation Error" in (fa.qbo_sync_error or "")
    notifs = _notifications(run, fid)
    assert notifs
    assert all("non renvoyée au client" in n.title for n in notifs)


# ── 3) Courriel en échec après QuickBooks ──────────────────────────


def test_courriel_en_echec_apres_qb_garde_le_lien(envoi, run, client, auth_headers):
    qb, mailer = envoi["qb"], envoi["mailer"]
    mailer.erreur = "Graph 503"
    fid = _brouillon(run, envoi, compteur=_base() + 185)

    r = _envoyer(client, auth_headers, fid)

    assert r.status_code == 400, r.text
    assert "déjà dans QuickBooks" in r.json()["detail"]
    fa = _facture(run, fid)
    assert fa.status == FactureStatus.DRAFT.value
    assert fa.qbo_invoice_id
    numero = fa.reference

    mailer.erreur = None
    r = _envoyer(client, auth_headers, fid)
    assert r.status_code == 200, r.text
    fa = _facture(run, fid)
    assert fa.status == FactureStatus.SENT.value
    assert fa.reference == numero
    # La même Invoice est mise à jour : jamais deux factures dans QB.
    assert len(_invoices_de(qb, fid)) == 1
    assert len(qb.creations) == 1


# ── 4) Facture d'acompte envoyée seule à la signature ──────────────


def test_acompte_automatique_retenu_si_qb_refuse(envoi, run):
    from app.api.v1.endpoints.public_soumission import _auto_send_deposit_facture

    qb, mailer = envoi["qb"], envoi["mailer"]
    qb.erreur_creation = REFUS_CATEGORIE
    fid = _brouillon(run, envoi, compteur=_base() + 190)

    run(_auto_send_deposit_facture(fid))

    assert mailer.sent == []
    fa = _facture(run, fid)
    assert fa.status == FactureStatus.DRAFT.value
    assert "catégorie" in (fa.qbo_sync_error or "")
    assert _notifications(run, fid)

    qb.erreur_creation = None
    run(_auto_send_deposit_facture(fid))
    assert len(mailer.sent) == 1
    fa = _facture(run, fid)
    assert fa.status == FactureStatus.SENT.value
    assert qb.invoices[fa.qbo_invoice_id]["DocNumber"] == fa.reference


# ── 5) QuickBooks non branché (staging) ────────────────────────────


def test_sans_quickbooks_la_facture_part_comme_avant(
    envoi, run, client, auth_headers, monkeypatch
):
    """Staging : aucune clé QuickBooks (render.yaml), le vrai client QB
    n'est pas prêt → envoi direct, aucun motif posé."""
    real = qb_mod.QuickBooksClient()
    assert not real.client_id
    monkeypatch.setattr(fq, "get_qbo", lambda *a, **k: real)
    monkeypatch.setattr(qb_mod, "get_qbo", lambda *a, **k: real)
    mailer = envoi["mailer"]
    fid = _brouillon(run, envoi, compteur=_base() + 195)

    r = _envoyer(client, auth_headers, fid)

    assert r.status_code == 200, r.text
    assert len(mailer.sent) == 1
    fa = _facture(run, fid)
    assert fa.status == FactureStatus.SENT.value
    assert not is_provisional_facture_reference(fa.reference)
    assert fa.qbo_sync_error is None
    assert _notifications(run, fid) == []


# ── 6) Bouton « Envoyer vers QuickBooks » d'un brouillon ───────────


def test_bouton_quickbooks_sur_un_brouillon(envoi, run, client, auth_headers):
    fid = _brouillon(run, envoi, compteur=_base() + 199)

    r = client.post(f"/api/v1/factures/{fid}/qbo/sync", headers=auth_headers)

    assert r.status_code == 409, r.text
    assert "Brouillon" in r.json()["detail"]
    assert envoi["qb"].creations == []
