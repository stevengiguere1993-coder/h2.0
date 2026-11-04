"""Smoke — « Envoyer rapport » d'une rencontre (Steven, 2026-10-29).

Le rapport part de la boîte de l'utilisateur CONNECTÉ (jamais d'info@),
les réponses lui reviennent, le corps reprend le résumé IA (pas le
transcript brut) et l'envoi est tracé sur la fiche.
"""
from __future__ import annotations

import json

from tests.smoke.conftest import ADMIN_EMAIL, TestSessionLocal


class FakeMailer:
    ready = True
    sender = "info@exemple.com"

    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send(self, to, subject, html_body, **kw):
        self.sent.append({"to": list(to), "subject": subject, "html": html_body, **kw})


def _seed_rencontre(run) -> int:
    from app.models.rencontre import Rencontre, RencontreSection

    async def _go():
        async with TestSessionLocal() as s:
            r = Rencontre(
                title="Conseil Horizon",
                global_summary="On accélère la construction.",
                attendees="Steven, Phil",
            )
            s.add(r)
            await s.flush()
            s.add(
                RencontreSection(
                    rencontre_id=r.id,
                    title="Budget",
                    transcript="SECRET-TRANSCRIPT",
                    ai_summary_json=json.dumps(
                        {
                            "summary": "Budget revu à la hausse.",
                            "decisions": ["Approuver <le> budget"],
                            "action_items": [
                                {"title": "Appeler la banque", "owner": "Steven", "due": "vendredi"}
                            ],
                        }
                    ),
                )
            )
            await s.commit()
            return r.id

    return run(_go())


def test_envoi_depuis_la_boite_de_l_utilisateur(client, auth_headers, run, monkeypatch):
    fake = FakeMailer()
    monkeypatch.setattr("app.integrations.email_graph.get_mailer", lambda: fake)
    rid = _seed_rencontre(run)

    r = client.post(
        f"/api/v1/rencontres/{rid}/envoyer",
        headers=auth_headers,
        json={
            "to": ["phil@exemple.com", "PHIL@exemple.com"],
            "cc": ["phil@exemple.com", "comptable@exemple.com"],
            "message": "Voici le rapport.",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["de"] == ADMIN_EMAIL
    assert body["a"] == ["phil@exemple.com"]
    assert body["cc"] == ["comptable@exemple.com"]

    assert len(fake.sent) == 1
    m = fake.sent[0]
    assert m["from_email"] == ADMIN_EMAIL
    assert m["reply_to"] == ADMIN_EMAIL
    assert m["subject"].startswith("Rapport de rencontre — Conseil Horizon")
    assert "Budget revu à la hausse." in m["html"]
    assert "Appeler la banque" in m["html"]
    assert "Approuver &lt;le&gt; budget" in m["html"]
    assert "Voici le rapport." in m["html"]
    assert "SECRET-TRANSCRIPT" not in m["html"]

    d = client.get(f"/api/v1/rencontres/{rid}", headers=auth_headers).json()
    envois = json.loads(d["envois_json"])
    assert envois[-1]["a"] == ["phil@exemple.com"]
    assert envois[-1]["de"] == ADMIN_EMAIL


def test_envoi_refuse_adresse_invalide_et_sans_destinataire(client, auth_headers, run, monkeypatch):
    fake = FakeMailer()
    monkeypatch.setattr("app.integrations.email_graph.get_mailer", lambda: fake)
    rid = _seed_rencontre(run)

    r = client.post(
        f"/api/v1/rencontres/{rid}/envoyer",
        headers=auth_headers,
        json={"to": ["pas-un-courriel"]},
    )
    assert r.status_code == 422
    r = client.post(
        f"/api/v1/rencontres/{rid}/envoyer",
        headers=auth_headers,
        json={"to": ["  "]},
    )
    assert r.status_code == 422
    assert fake.sent == []


def test_refus_graph_ne_bascule_pas_sur_info(client, auth_headers, run, monkeypatch):
    import httpx

    class MailerRefus(FakeMailer):
        async def send(self, to, subject, html_body, **kw):
            req = httpx.Request("POST", "https://graph.microsoft.com")
            raise httpx.HTTPStatusError(
                "refus", request=req, response=httpx.Response(404, request=req)
            )

    monkeypatch.setattr("app.integrations.email_graph.get_mailer", lambda: MailerRefus())
    rid = _seed_rencontre(run)
    r = client.post(
        f"/api/v1/rencontres/{rid}/envoyer",
        headers=auth_headers,
        json={"to": ["phil@exemple.com"]},
    )
    assert r.status_code == 502
    assert ADMIN_EMAIL in r.json()["detail"]
