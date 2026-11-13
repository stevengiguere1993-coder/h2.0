"""Smoke — Centre d'aide fiable et historique des bugs (Steven, 2026-11-13).

« Beaucoup de bugs qui reviennent et qui sont déjà réglés […] pouvoir
poser une question sur un fonctionnement et avoir la réponse » (point 11),
et « une section historique : bug accepté ou refusé avec la note, date de
la gestion, notification au déclarant » (point 18).
"""
from __future__ import annotations

import pytest
from sqlalchemy import select

from app.core.security import create_access_token, get_password_hash
from app.models.notification import Notification
from app.models.user import User
from app.services import aide_connaissances as kb

from .conftest import TestSessionLocal


# ── Base de connaissances (pur) ─────────────────────────────────────────


def test_mots_cles_sans_accents_ni_mots_vides():
    mots = kb.mots_cles("Comment trier les numéros des Chambres ?")
    assert "numero" in mots and "chambre" in mots
    assert "comment" not in mots


def test_section_depuis_url():
    assert kb.section_depuis_url("/fr/immobilier/gestion/12") == "Immobilier · Gestion locative"
    assert kb.section_depuis_url("/en/entreprises/comptabilite/x") == "Entreprises · Comptabilité"
    assert kb.section_depuis_url("/fr/dev-logiciel/leads") == "Développement logiciel"
    assert kb.section_depuis_url("/m/punch") == "Zone employés (mobile)"
    assert kb.section_depuis_url("/fr") is None
    assert kb.section_depuis_url(None) is None


def test_journal_des_livraisons_retrouve_une_correction_livree():
    # Le tri naturel des numéros de logement a été livré le 2026-09-28 :
    # le re-signaler doit faire remonter cette livraison.
    trouves = kb.chercher_livraisons("les numéros de chambre 10 et 11 ne sont pas triés")
    assert any("tri naturel" in l.sujet for l in trouves), trouves


# ── API ─────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def owner_headers(run) -> dict:
    async def _seed() -> int:
        async with TestSessionLocal() as s:
            u = (
                await s.execute(select(User).where(User.email == "owner.aide@example.com"))
            ).scalar_one_or_none()
            if u is None:
                u = User(
                    email="owner.aide@example.com",
                    hashed_password=get_password_hash("x"),
                    is_active=True,
                    is_admin=True,
                    role="owner",
                )
                s.add(u)
                await s.commit()
                await s.refresh(u)
            return u.id

    uid = run(_seed())
    return {"Authorization": f"Bearer {create_access_token(subject=str(uid))}"}


def _signaler(client, headers, message, url="/fr/immobilier/gestion/logements/4"):
    r = client.post(
        "/api/v1/help/reports",
        headers=headers,
        data={"message": message, "context_url": url},
    )
    assert r.status_code == 201, r.text
    return r.json()


def test_historique_et_notification_au_declarant(
    client, employee_headers, employee_id, owner_headers, run
):
    rep = _signaler(client, employee_headers, "Le solde du locataire Tremblay ne se recalcule pas")
    assert rep["section"] == "Immobilier · Gestion locative"

    # Refus avec note : historique daté + notification au déclarant.
    r = client.patch(
        f"/api/v1/help/reports/{rep['id']}",
        headers=owner_headers,
        json={"status": "rejected", "resolution_notes": "Le paiement avait été saisi deux fois."},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "rejected"
    assert body["rejected_at"] and body["traite_le"]
    assert body["traite_par"] == "owner.aide@example.com"

    async def _notifs():
        async with TestSessionLocal() as s:
            return (
                await s.execute(
                    select(Notification)
                    .where(Notification.user_id == employee_id)
                    .where(Notification.kind == "bug_traite")
                )
            ).scalars().all()

    notifs = run(_notifs())
    assert len(notifs) == 1
    assert "refusé" in notifs[0].title
    assert "deux fois" in (notifs[0].body or "")
    assert notifs[0].href == "/immobilier/gestion/logements/4?aide=mes-signalements"

    # Même statut renvoyé : pas de seconde notification.
    client.patch(
        f"/api/v1/help/reports/{rep['id']}", headers=owner_headers, json={"status": "rejected"}
    )
    assert len(run(_notifs())) == 1

    # Le déclarant voit son historique.
    r = client.get("/api/v1/help/mes-signalements", headers=employee_headers)
    assert r.status_code == 200, r.text
    mien = next(x for x in r.json() if x["id"] == rep["id"])
    assert mien["statut_libelle"] == "refusé"
    assert mien["resolution_notes"] == "Le paiement avait été saisi deux fois."
    assert mien["traite_le"]


def test_lot_regle_avec_note_commune(client, employee_headers, owner_headers):
    a = _signaler(client, employee_headers, "Impossible de joindre une photo au bon de travail")
    r = client.post(
        "/api/v1/help/reports/bulk",
        headers=owner_headers,
        json={"ids": [a["id"]], "action": "resolve", "resolution_notes": "Corrigé le 13 novembre."},
    )
    assert r.status_code == 200, r.text
    rows = client.get("/api/v1/help/reports", headers=owner_headers).json()
    regle = next(x for x in rows if x["id"] == a["id"])
    assert regle["status"] == "resolved"
    assert regle["resolution_notes"] == "Corrigé le 13 novembre."
    assert regle["resolved_at"] and regle["traite_le"]


def test_similaires_fait_remonter_un_bug_deja_regle(client, employee_headers, owner_headers):
    a = _signaler(client, employee_headers, "Le PDF du bail signé ne se télécharge pas, erreur 404")
    client.patch(
        f"/api/v1/help/reports/{a['id']}",
        headers=owner_headers,
        json={"status": "resolved", "resolution_notes": "Lien de téléchargement corrigé."},
    )
    r = client.get(
        "/api/v1/help/similaires",
        headers=employee_headers,
        params={"q": "je ne peux pas télécharger le PDF du bail"},
    )
    assert r.status_code == 200, r.text
    sig = r.json()["signalements"]
    assert sig and sig[0]["id"] == a["id"]
    assert sig[0]["statut_libelle"] == "réglé"
    assert sig[0]["resolution_notes"] == "Lien de téléchargement corrigé."


def test_contexte_ia_mentionne_statut_note_et_livraison():
    sig = kb.SignalementLie(
        id=7, status="resolved", statut_libelle="réglé", section="Immobilier",
        message="Tri des chambres", resolution_notes="Tri naturel livré.",
        created_at=__import__("datetime").datetime(2026, 9, 22),
        traite_le=__import__("datetime").datetime(2026, 9, 28), score=2,
    )
    txt = kb.contexte_ia([sig], [kb.Livraison("2026-09-28", "tri naturel")], [])
    assert "Signalement #7 (réglé le 2026-09-28" in txt
    assert "Tri naturel livré." in txt
    assert "2026-09-28 : tri naturel" in txt


def test_accepter_veut_dire_regle(client, employee_headers, owner_headers, run):
    """Steven : « lorsque je clique sur accepté un signalement de bug, cela
    veut dire qu'il a été réglé »."""
    a = _signaler(client, employee_headers, "Le bouton exporter ne fait rien sur Safari")
    r = client.patch(
        f"/api/v1/help/reports/{a['id']}", headers=owner_headers, json={"status": "accepted"}
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "resolved" and r.json()["resolved_at"]

    b = _signaler(client, employee_headers, "La page des achats charge sans fin")
    client.post(
        "/api/v1/help/reports/bulk",
        headers=owner_headers,
        json={"ids": [b["id"]], "action": "accept"},
    )
    rows = client.get("/api/v1/help/reports", headers=owner_headers).json()
    assert next(x for x in rows if x["id"] == b["id"])["status"] == "resolved"


def test_migration_acceptes_deviennent_regles(client, employee_headers, owner_headers, run):
    from datetime import datetime, timezone

    from app.db.session import ensure_bugs_acceptes_regles
    from app.models.help_request import HelpRequest

    a = _signaler(client, employee_headers, "Ancien bug accepté avant le 13 novembre")
    quand = datetime(2026, 10, 1, tzinfo=timezone.utc)

    async def _poser():
        async with TestSessionLocal() as s:
            rec = await s.get(HelpRequest, a["id"])
            rec.status = "accepted"
            rec.accepted_at = quand
            await s.commit()

    run(_poser())
    run(ensure_bugs_acceptes_regles())

    async def _lire():
        async with TestSessionLocal() as s:
            return await s.get(HelpRequest, a["id"], populate_existing=True)

    rec = run(_lire())
    assert rec.status == "resolved"
    assert rec.resolved_at is not None and rec.traite_le is not None
