"""Smoke — brief du matin par courriel (Phil 2026-10-15).

La routine claude.ai ne peut pas compter sur le connecteur MCP ; Kratos
envoie donc lui-même le digest chaque matin. On vérifie, sans réseau :
- destinataires = propriétaires d'une clé API active (ou liste configurée) ;
- le courriel porte le sujet daté et le digest de l'utilisateur ;
- l'heure d'envoi est respectée (avant : rien ; après : un envoi) et le
  verrou quotidien (claim) est honoré ;
- la route d'envoi manuel (admin) répond et envoie ;
- l'automatisation est dans le catalogue et dans le hub.
"""
from __future__ import annotations

from datetime import datetime

import pytest

from app.services import brief_matin
from tests.smoke.conftest import TestSessionLocal


class FakeMailer:
    ready = True

    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send(self, to, subject, html_body, **kw):
        self.sent.append({"to": list(to), "subject": subject, "html": html_body})


@pytest.fixture()
def fake_mailer(monkeypatch) -> FakeMailer:
    fake = FakeMailer()
    monkeypatch.setattr("app.integrations.email_graph.get_mailer", lambda: fake)
    return fake


def test_sujet_et_html():
    d = datetime(2026, 10, 15, 4, 30, tzinfo=brief_matin.FUSEAU)
    assert brief_matin.sujet_du_jour(d) == "Kratos — brief du jeudi 15 octobre 2026"
    html = brief_matin.construire_html(
        "État de Kratos au 2026-10-15.\nGestion locative : 22 en retard <test>\nEntreprises : 46 tâches ouvertes.",
        "Philippe", d,
    )
    assert "Bonjour Philippe" in html
    assert "<strong>État de Kratos au 2026-10-15.</strong>" in html
    assert "<li>Gestion locative : 22 en retard &lt;test&gt;</li>" in html
    assert "<li>Entreprises : 46 tâches ouvertes.</li>" in html


def test_est_du():
    lundi_4h29 = datetime(2026, 10, 12, 4, 29, tzinfo=brief_matin.FUSEAU)
    lundi_4h30 = datetime(2026, 10, 12, 4, 30, tzinfo=brief_matin.FUSEAU)
    samedi_9h = datetime(2026, 10, 17, 9, 0, tzinfo=brief_matin.FUSEAU)
    assert brief_matin.est_du(lundi_4h29, 4, 30, True) is False
    assert brief_matin.est_du(lundi_4h30, 4, 30, True) is True
    assert brief_matin.est_du(samedi_9h, 4, 30, True) is False
    assert brief_matin.est_du(samedi_9h, 4, 30, False) is True


def test_destinataires_et_envoi(run, db_setup, seeded_users, fake_mailer, monkeypatch):
    """L'admin du smoke a une clé API active (fixture api_key_headers) :
    il reçoit le brief ; la liste configurée prend le dessus si fournie."""
    from app.models.api_key import ApiKey
    from app.models.user import User
    from sqlalchemy import select

    async def _digest(db, user):
        return f"État de Kratos au 2026-10-15.\nTest pour {user.email}"

    monkeypatch.setattr("app.services.user_ai.digest_pour_utilisateur", _digest)

    async def _etat():
        async with TestSessionLocal() as s:
            cles = (await s.execute(select(ApiKey).where(ApiKey.is_active.is_(True)))).scalars().all()
            proprietaires = {c.user_id for c in cles}
            users = await brief_matin.destinataires(s, {})
            rapport = await brief_matin.envoyer_brief(
                s, quand=datetime(2026, 10, 15, 4, 31, tzinfo=brief_matin.FUSEAU), config={}
            )
            await s.rollback()
            # Liste configurée : un seul destinataire explicite.
            admin = (await s.execute(select(User).where(User.id.in_(proprietaires)))).scalars().first()
            users2 = await brief_matin.destinataires(s, {"destinataires": [admin.email.upper()]})
            return proprietaires, [u.id for u in users], rapport, [u.email for u in users2], admin.email

    proprietaires, ids, rapport, emails2, admin_email = run(_etat())
    assert proprietaires, "le smoke doit avoir au moins une clé API active"
    assert set(ids) == proprietaires
    assert rapport["envoyes"] == len(ids) and not rapport["erreurs"]
    assert fake_mailer.sent[0]["subject"] == "Kratos — brief du jeudi 15 octobre 2026"
    assert "Test pour" in fake_mailer.sent[0]["html"]
    assert emails2 == [admin_email]


def test_envoyer_si_du_respecte_heure_et_verrou(run, db_setup, seeded_users, fake_mailer, monkeypatch):
    async def _digest(db, user):
        return "État de Kratos.\nRien à signaler."

    monkeypatch.setattr("app.services.user_ai.digest_pour_utilisateur", _digest)
    monkeypatch.setattr("app.db.session.AsyncSessionLocal", TestSessionLocal)
    reservations: list = []

    async def _claim(db, job, min_s):
        reservations.append((job, min_s))
        return len(reservations) == 1  # première réservation OK, la 2e refusée

    monkeypatch.setattr("app.services.cron_guard.claim_cron_run", _claim)

    avant = datetime(2026, 10, 15, 4, 0, tzinfo=brief_matin.FUSEAU)
    apres = datetime(2026, 10, 15, 4, 45, tzinfo=brief_matin.FUSEAU)
    assert run(brief_matin.envoyer_si_du(avant)) is None
    assert reservations == []
    r1 = run(brief_matin.envoyer_si_du(apres))
    assert r1 is not None and r1["envoyes"] >= 1
    assert reservations == [("brief_matin", 20 * 3600)]
    assert run(brief_matin.envoyer_si_du(apres)) is None  # déjà envoyé aujourd'hui
    assert len(fake_mailer.sent) == r1["envoyes"]


def test_route_et_catalogue(client, auth_headers, employee_headers, fake_mailer, monkeypatch):
    async def _digest(db, user):
        return "État de Kratos.\nRoute manuelle."

    monkeypatch.setattr("app.services.user_ai.digest_pour_utilisateur", _digest)
    r = client.post("/api/v1/automations/brief-matin/envoyer", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json()["envoyes"] >= 1
    assert any("Route manuelle" in m["html"] for m in fake_mailer.sent)
    assert client.post("/api/v1/automations/brief-matin/envoyer", headers=employee_headers).status_code == 403

    hub = client.get("/api/v1/automations", headers=auth_headers).json()
    entree = next(a for a in hub if a["key"] == "brief_matin")
    assert entree["category"] == "rapport" and entree["enabled"] is True
    assert {p["key"] for p in entree["params"]} == {"heure", "minute"}
