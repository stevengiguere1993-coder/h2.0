"""Smoke — courriel à la technicienne comptable (Steven 2026-11-04).

À chaque nouveau projet, la technicienne comptable reçoit le nom du
sous-client QuickBooks à convertir en projet. Le réglage (activer /
couper + courriel destinataire) vit dans Paramètres ; avant tout
enregistrement, la variable BOOKKEEPER_EMAIL sert de repli.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services import project_qbo_notify as pqn
from tests.smoke.conftest import TestSessionLocal

URL = "/api/v1/automations/projet-qbo-alerte"


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
    monkeypatch.setattr(pqn, "get_mailer", lambda: fake)
    monkeypatch.setattr(
        "app.services.automation_state.AsyncSessionLocal", TestSessionLocal
    )
    return fake


def test_repli_variable_tant_que_rien_n_est_enregistre(monkeypatch):
    monkeypatch.setattr(pqn.settings, "bookkeeper_email", "")
    assert pqn.reglage_depuis_config({}) == {
        "actif": False, "destinataire": "", "source": "aucun",
    }
    monkeypatch.setattr(pqn.settings, "bookkeeper_email", " tech@ex.ca ")
    assert pqn.reglage_depuis_config({}) == {
        "actif": True, "destinataire": "tech@ex.ca", "source": "variable",
    }
    # Une fois enregistré dans Paramètres, la page fait foi (même coupée).
    assert pqn.reglage_depuis_config({"actif": False, "destinataire": "a@b.ca"}) == {
        "actif": False, "destinataire": "a@b.ca", "source": "parametres",
    }


def test_courriel_echappe_et_essai():
    sujet, corps = pqn.construire_courriel("12 rue <A>", "Client & fils")
    assert sujet == "À convertir en projet QuickBooks : 12 rue <A>"
    assert "12 rue &lt;A&gt;" in corps and "Client &amp; fils" in corps
    assert "Courriel d'essai" not in corps
    sujet, corps = pqn.construire_courriel("x", "y", essai=True)
    assert sujet.startswith("[Essai] ") and "Courriel d'essai" in corps


def test_reglage_par_api_et_envoi(client, auth_headers, employee_headers, fake_mailer, run, monkeypatch):
    monkeypatch.setattr(pqn.settings, "bookkeeper_email", "")
    assert client.get(URL, headers=employee_headers).status_code == 403
    assert client.put(URL, headers=employee_headers, json={"actif": True, "destinataire": "t@ex.ca"}).status_code == 403
    r = client.get(URL, headers=auth_headers)
    assert r.status_code == 200 and r.json()["actif"] is False

    # Validation : courriel invalide, activation sans courriel.
    assert client.put(URL, headers=auth_headers, json={"actif": False, "destinataire": "pas-un-courriel"}).status_code == 422
    assert client.put(URL, headers=auth_headers, json={"actif": True, "destinataire": ""}).status_code == 422

    r = client.put(URL, headers=auth_headers, json={"actif": True, "destinataire": " tech@ex.ca "})
    assert r.status_code == 200
    assert r.json() == {"actif": True, "destinataire": "tech@ex.ca", "source": "parametres"}
    assert client.get(URL, headers=auth_headers).json()["destinataire"] == "tech@ex.ca"

    projet = SimpleNamespace(id=42, address="5 rue du Test", name="Projet", client_id=None)

    async def _notifier():
        async with TestSessionLocal() as s:
            return await pqn.notify_new_project_for_qbo(s, projet)

    assert run(_notifier()) is True
    assert fake_mailer.sent[-1]["to"] == ["tech@ex.ca"]
    assert fake_mailer.sent[-1]["subject"].endswith("5 rue du Test")

    # Courriel d'essai.
    r = client.post(f"{URL}/essai", headers=auth_headers)
    assert r.status_code == 200 and r.json()["envoye_a"] == "tech@ex.ca"
    assert fake_mailer.sent[-1]["subject"].startswith("[Essai]")

    # Coupé : plus d'envoi automatique, destinataire conservé.
    n = len(fake_mailer.sent)
    assert client.put(URL, headers=auth_headers, json={"actif": False, "destinataire": "tech@ex.ca"}).status_code == 200
    assert run(_notifier()) is False
    assert len(fake_mailer.sent) == n

    # Au catalogue du hub, réglé ailleurs (pas de bascule dans le hub).
    hub = client.get("/api/v1/automations", headers=auth_headers).json()
    entree = next(a for a in hub if a["key"] == "projet_qbo_alerte")
    assert entree["controllable"] is False
