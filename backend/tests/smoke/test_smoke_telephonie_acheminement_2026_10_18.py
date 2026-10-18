"""Smoke test API — heures d'appel personnelles et règles d'acheminement
(téléphonie, bug 19 du 2026-10-18).

Couvre, sans réseau (SQLite, Twilio remplacé par un double) :

1. ``/voice/call-hours/me`` (tout utilisateur) : lecture, remplacement
   atomique, validations (heure illisible, plage vide, fuseau inconnu),
   puis l'effet réel sur la disponibilité (``is_user_available_now`` /
   ``filter_users_available_now``) y compris une plage qui passe minuit.
2. ``/voice/call-hours`` (admin) : vue d'équipe et édition d'un tiers.
3. ``/voice/routing-rules`` (admin) : options de l'éditeur, validations,
   création, aperçu « qui sonnerait maintenant ? » avec et sans chantier,
   respect des heures personnelles (et ``respect_hours=false``), règle
   propre à un chantier qui prime sur la règle générale, mode simultané,
   suppression.
4. Cascade de sonnerie dans la file d'attente : la 1re étape sonne tout
   de suite, l'étape suivante part quand toutes les jambes de l'étape
   courante ont échoué (webhook ``/twilio/queue-agent-status``), et la
   boîte vocale ne vient qu'après la dernière étape.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from app.api.v1.endpoints import voice as voice_ep
from app.integrations.voice.call_routing_rules import SUBJECT_LABELS
from app.integrations.voice.routing import (
    filter_users_available_now,
    is_user_available_now,
)
from app.models.project import Project
from app.models.user import User
from app.models.voice import Call, PhoneNumber, VoiceRoutingRule, VoiceUserCallHours
from tests.smoke.conftest import TestSessionLocal

API = "/api/v1/voice"
TZ = ZoneInfo("America/Montreal")

EMPLOYEE_PHONE = "+15145550123"
LINE_E164 = "+15145550199"
OFFICE_E164 = "+15145550177"


def _montreal_now() -> datetime:
    return datetime.now(TZ)


def _at(day_of_week: int, hour: int, minute: int = 0) -> datetime:
    """Un instant (aware, Montréal) tombant le ``day_of_week`` demandé
    (0 = lundi) de la semaine en cours, à l'heure donnée."""
    now = _montreal_now()
    base = now + timedelta(days=(day_of_week - now.weekday()) % 7)
    return base.replace(hour=hour, minute=minute, second=0, microsecond=0)


# ─────────────────────────────────────────────────────────────────────
# 1) Mes heures d'appel (employé) + effet sur la disponibilité
# ─────────────────────────────────────────────────────────────────────


def test_mes_heures_appel_employe(client, run, employee_headers, employee_id, admin_id):
    # Aucune plage au départ → joignable en tout temps.
    r = client.get(f"{API}/call-hours/me", headers=employee_headers)
    assert r.status_code == 200, r.text
    assert r.json() == []

    async def _dispo(uid: int, when: datetime) -> bool:
        async with TestSessionLocal() as db:
            return await is_user_available_now(db, uid, now=when)

    assert run(_dispo(employee_id, _at(2, 3, 0))) is True

    # Validations.
    bad = [
        ({"hours": [{"day_of_week": 1, "open_time": "25:00", "close_time": "17:00"}]}, "invalide"),
        ({"hours": [{"day_of_week": 1, "open_time": "9h", "close_time": "17:00"}]}, "invalide"),
        ({"hours": [{"day_of_week": 1, "open_time": "09:00", "close_time": "09:00"}]}, "différente"),
        (
            {"hours": [{"day_of_week": 1, "open_time": "09:00", "close_time": "17:00", "timezone": "Mars/Olympus"}]},
            "Fuseau",
        ),
    ]
    for payload, fragment in bad:
        r = client.put(f"{API}/call-hours/me", headers=employee_headers, json=payload)
        assert r.status_code == 400, r.text
        assert fragment in r.json()["detail"]
    r = client.put(
        f"{API}/call-hours/me",
        headers=employee_headers,
        json={"hours": [{"day_of_week": 7, "open_time": "09:00", "close_time": "17:00"}]},
    )
    assert r.status_code == 422, r.text

    # Lundi → vendredi, 8 h à 17 h (envoyées dans le désordre : triées en retour).
    hours = [
        {"day_of_week": d, "open_time": "08:00", "close_time": "17:00"}
        for d in (4, 2, 0, 3, 1)
    ]
    r = client.put(f"{API}/call-hours/me", headers=employee_headers, json={"hours": hours})
    assert r.status_code == 200, r.text
    rows = r.json()
    assert [x["day_of_week"] for x in rows] == [0, 1, 2, 3, 4]
    assert all(x["user_id"] == employee_id for x in rows)
    assert rows[0]["open_time"] == "08:00" and rows[0]["close_time"] == "17:00"
    assert rows[0]["timezone"] == "America/Montreal"

    r = client.get(f"{API}/call-hours/me", headers=employee_headers)
    assert r.status_code == 200
    assert len(r.json()) == 5

    # Disponibilité réelle : mercredi 10 h oui, mercredi 18 h non, dimanche non.
    assert run(_dispo(employee_id, _at(2, 10, 0))) is True
    assert run(_dispo(employee_id, _at(2, 18, 0))) is False
    assert run(_dispo(employee_id, _at(6, 10, 0))) is False
    # L'admin n'a aucune plage → toujours joignable.
    assert run(_dispo(admin_id, _at(6, 3, 0))) is True

    async def _filtre(when: datetime) -> list[int]:
        async with TestSessionLocal() as db:
            return await filter_users_available_now(
                db, [employee_id, admin_id, employee_id], now=when
            )

    # Ordre conservé, doublon retiré, employé sauté hors de ses heures.
    assert run(_filtre(_at(2, 10, 0))) == [employee_id, admin_id]
    assert run(_filtre(_at(6, 10, 0))) == [admin_id]

    # Un employé ne voit pas la vue d'équipe (admin seulement).
    r = client.get(f"{API}/call-hours", headers=employee_headers)
    assert r.status_code == 403, r.text
    r = client.put(
        f"{API}/call-hours/{admin_id}", headers=employee_headers, json={"hours": []}
    )
    assert r.status_code == 403, r.text


def test_heures_appel_equipe_admin(client, run, auth_headers, employee_id, admin_id):
    r = client.get(f"{API}/call-hours", headers=auth_headers)
    assert r.status_code == 200, r.text
    par_user = {row["user_id"]: row for row in r.json()}
    assert employee_id in par_user and admin_id in par_user
    emp = par_user[employee_id]
    assert emp["always_available"] is False
    assert len(emp["hours"]) == 5
    assert emp["email"] == "smoke-employe@example.com"
    adm = par_user[admin_id]
    assert adm["always_available"] is True and adm["available_now"] is True
    assert adm["hours"] == []

    # Édition d'un tiers : plage de nuit qui passe minuit (22 h → 6 h), 7 j/7.
    nuit = [
        {"day_of_week": d, "open_time": "22:00", "close_time": "06:00"} for d in range(7)
    ]
    r = client.put(
        f"{API}/call-hours/{employee_id}", headers=auth_headers, json={"hours": nuit}
    )
    assert r.status_code == 200, r.text
    assert len(r.json()) == 7

    async def _dispo(when: datetime) -> bool:
        async with TestSessionLocal() as db:
            return await is_user_available_now(db, employee_id, now=when)

    assert run(_dispo(_at(2, 23, 30))) is True
    assert run(_dispo(_at(3, 2, 0))) is True  # après minuit, même plage
    assert run(_dispo(_at(2, 12, 0))) is False

    r = client.put(
        f"{API}/call-hours/999999", headers=auth_headers, json={"hours": nuit}
    )
    assert r.status_code == 404, r.text

    # Retour à « aucune plage » (joignable en tout temps) pour la suite.
    r = client.put(
        f"{API}/call-hours/{employee_id}", headers=auth_headers, json={"hours": []}
    )
    assert r.status_code == 200 and r.json() == []

    async def _compte() -> int:
        async with TestSessionLocal() as db:
            rows = (
                await db.execute(
                    select(VoiceUserCallHours).where(
                        VoiceUserCallHours.user_id == employee_id
                    )
                )
            ).scalars().all()
            return len(rows)

    assert run(_compte()) == 0


# ─────────────────────────────────────────────────────────────────────
# 2) Règles d'acheminement (admin)
# ─────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def acheminement_seed(run, employee_id, admin_id) -> dict:
    """Une ligne, un chantier dont l'employé est responsable, un
    téléphone sur l'employé."""

    async def _seed() -> dict:
        async with TestSessionLocal() as db:
            emp = await db.get(User, employee_id)
            emp.phone_e164 = EMPLOYEE_PHONE
            pn = PhoneNumber(
                e164=LINE_E164,
                provider="twilio",
                label="Ligne smoke 19",
                forward_to_e164="+15145550100",
                followup_forward_e164="+15145550155",
                active=True,
            )
            project = Project(
                name="Chantier smoke 19",
                address="19 rue du Test, Montréal",
                status="in_progress",
                responsible_user_id=employee_id,
            )
            db.add_all([pn, project])
            await db.flush()
            ids = {"phone_number_id": pn.id, "project_id": project.id}
            await db.commit()
            return ids

    return run(_seed())


def test_regles_acheminement_admin(
    client, run, auth_headers, employee_headers, employee_id, admin_id, acheminement_seed
):
    project_id = acheminement_seed["project_id"]
    phone_number_id = acheminement_seed["phone_number_id"]

    # Réservé aux admins.
    r = client.get(f"{API}/routing-rules", headers=employee_headers)
    assert r.status_code == 403, r.text

    # Options de l'éditeur.
    r = client.get(f"{API}/routing-rules/options", headers=auth_headers)
    assert r.status_code == 200, r.text
    opts = r.json()
    assert {s["key"] for s in opts["subjects"]} >= {
        "suivi_projet", "nouveau_client", "urgence_locataire", "demande_locataire", "general"
    }
    assert {k["key"] for k in opts["target_kinds"]} >= {
        "project_responsible", "project_members", "user", "line_default", "e164"
    }
    assert [m["key"] for m in opts["modes"]] == ["cascade", "simultane"]
    users = {u["id"]: u for u in opts["users"]}
    assert users[employee_id]["phone_e164"] == EMPLOYEE_PHONE
    assert users[employee_id]["available_now"] is True
    assert users[employee_id]["has_hours"] is False
    projects = {p["id"]: p for p in opts["projects"]}
    assert projects[project_id]["responsible_user_id"] == employee_id
    assert projects[project_id]["responsible_name"] == users[employee_id]["display_name"]
    assert any(n["id"] == phone_number_id for n in opts["phone_numbers"])

    # Validations à la création.
    cas = [
        ({"subject": "pizza", "targets": [{"kind": "e164", "e164": OFFICE_E164}]}, 400, "Sujet inconnu"),
        ({"subject": "suivi_projet", "mode": "random", "targets": [{"kind": "e164", "e164": OFFICE_E164}]}, 400, "Mode inconnu"),
        ({"subject": "suivi_projet", "targets": []}, 400, "au moins une personne"),
        ({"subject": "suivi_projet", "targets": [{"kind": "user"}]}, 400, "utilisateur"),
        ({"subject": "suivi_projet", "targets": [{"kind": "user", "user_id": 999999}]}, 400, "introuvable"),
        ({"subject": "suivi_projet", "targets": [{"kind": "e164", "e164": "514-ABC"}]}, 400, "invalide"),
        ({"subject": "suivi_projet", "project_id": 999999, "targets": [{"kind": "e164", "e164": OFFICE_E164}]}, 404, "project_not_found"),
        ({"subject": "suivi_projet", "phone_number_id": 999999, "targets": [{"kind": "e164", "e164": OFFICE_E164}]}, 404, "phone_number_not_found"),
    ]
    for payload, code, fragment in cas:
        r = client.post(f"{API}/routing-rules", headers=auth_headers, json=payload)
        assert r.status_code == code, (payload, r.text)
        assert fragment.lower() in str(r.json()["detail"]).lower(), (payload, r.text)

    # Règle GÉNÉRALE « suivi de projet » : responsable du chantier, puis
    # l'admin (sans téléphone), puis le bureau — l'un après l'autre.
    generale = {
        "subject": "suivi_projet",
        "label": "Suivi de chantier (toutes les lignes)",
        "mode": "cascade",
        "step_timeout_sec": 15,
        "targets": [
            {"kind": "project_responsible"},
            {"kind": "user", "user_id": admin_id},
            {"kind": "e164", "e164": "514 555 0177", "label": "Bureau"},
            {"kind": "e164", "e164": OFFICE_E164},  # doublon → retiré
        ],
    }
    r = client.post(f"{API}/routing-rules", headers=auth_headers, json=generale)
    assert r.status_code == 201, r.text
    rule = r.json()
    rule_id = rule["id"]
    assert rule["subject_label"] == SUBJECT_LABELS["suivi_projet"]
    assert rule["project_id"] is None and rule["project_name"] is None
    assert rule["mode"] == "cascade" and rule["step_timeout_sec"] == 15
    assert rule["respect_hours"] is True and rule["active"] is True
    assert [t["kind"] for t in rule["targets"]] == ["project_responsible", "user", "e164"]
    assert rule["targets"][0]["display"] == "Responsable du chantier"
    assert rule["targets"][1]["user_id"] == admin_id
    assert rule["targets"][2]["e164"] == OFFICE_E164
    assert rule["targets"][2]["display"] == f"Bureau ({OFFICE_E164})"

    r = client.get(f"{API}/routing-rules", headers=auth_headers)
    assert r.status_code == 200
    assert any(x["id"] == rule_id for x in r.json())
    r = client.get(
        f"{API}/routing-rules", headers=auth_headers,
        params={"phone_number_id": phone_number_id},
    )
    assert any(x["id"] == rule_id for x in r.json())

    # Aperçu SANS chantier : le responsable ne peut pas être résolu, l'admin
    # n'a pas de téléphone → seul le bureau sonne.
    r = client.get(
        f"{API}/routing-rules/preview", headers=auth_headers,
        params={"subject": "suivi_projet"},
    )
    assert r.status_code == 200, r.text
    apercu = r.json()
    assert apercu["rule"]["id"] == rule_id
    assert apercu["project_id"] is None
    plan = apercu["plan"]
    assert plan["mode"] == "cascade" and plan["step_timeout_sec"] == 15
    cibles = plan["targets"]
    assert cibles[0]["skipped"] == "aucun chantier reconnu pour cet appel"
    assert cibles[1]["skipped"] == "aucun téléphone dans son profil"
    assert cibles[2]["skipped"] is None and cibles[2]["destinations"] == [OFFICE_E164]
    assert plan["steps"] == [[OFFICE_E164]]
    assert "Sans règle" in apercu["fallback"]

    # Aperçu AVEC chantier : le responsable (l'employé) sonne en premier.
    r = client.get(
        f"{API}/routing-rules/preview", headers=auth_headers,
        params={"subject": "suivi_projet", "project_id": project_id},
    )
    assert r.status_code == 200, r.text
    apercu = r.json()
    assert apercu["project_name"] == "Chantier smoke 19"
    cibles = apercu["plan"]["targets"]
    assert cibles[0]["skipped"] is None
    assert cibles[0]["user_id"] == employee_id
    assert cibles[0]["label"].startswith("Responsable du chantier : ")
    assert cibles[0]["destinations"] == [EMPLOYEE_PHONE]
    assert apercu["plan"]["steps"] == [[EMPLOYEE_PHONE], [OFFICE_E164]]

    # Heures personnelles : l'employé n'est joignable qu'un autre jour → sauté.
    autre_jour = (_montreal_now().weekday() + 3) % 7
    r = client.put(
        f"{API}/call-hours/{employee_id}", headers=auth_headers,
        json={"hours": [{"day_of_week": autre_jour, "open_time": "09:00", "close_time": "10:00"}]},
    )
    assert r.status_code == 200, r.text
    r = client.get(
        f"{API}/routing-rules/preview", headers=auth_headers,
        params={"subject": "suivi_projet", "project_id": project_id},
    )
    cibles = r.json()["plan"]["targets"]
    assert cibles[0]["skipped"] == "hors de ses heures d'appel"
    assert r.json()["plan"]["steps"] == [[OFFICE_E164]]

    # … sauf si la règle ignore les heures (respect_hours = false).
    r = client.put(
        f"{API}/routing-rules/{rule_id}", headers=auth_headers,
        json={**generale, "respect_hours": False},
    )
    assert r.status_code == 200, r.text
    assert r.json()["respect_hours"] is False
    r = client.get(
        f"{API}/routing-rules/preview", headers=auth_headers,
        params={"subject": "suivi_projet", "project_id": project_id},
    )
    assert r.json()["plan"]["steps"] == [[EMPLOYEE_PHONE], [OFFICE_E164]]

    # Règle PROPRE AU CHANTIER : prime sur la générale pour ce chantier,
    # tous en même temps. (L'employé redevient joignable en tout temps.)
    r = client.put(
        f"{API}/call-hours/{employee_id}", headers=auth_headers, json={"hours": []}
    )
    assert r.status_code == 200, r.text
    r = client.post(
        f"{API}/routing-rules", headers=auth_headers,
        json={
            "subject": "suivi_projet",
            "project_id": project_id,
            "mode": "simultane",
            "step_timeout_sec": 99,  # borné
            "targets": [
                {"kind": "user", "user_id": employee_id, "label": "Chef de chantier"},
                {"kind": "line_default"},
            ],
        },
    )
    assert r.status_code == 201, r.text
    chantier = r.json()
    assert chantier["project_name"] == "Chantier smoke 19"
    assert chantier["step_timeout_sec"] == 45
    assert chantier["targets"][0]["display"] == "Chef de chantier"
    r = client.get(
        f"{API}/routing-rules/preview", headers=auth_headers,
        params={
            "subject": "suivi_projet", "project_id": project_id,
            "phone_number_id": phone_number_id,
        },
    )
    assert r.status_code == 200, r.text
    apercu = r.json()
    assert apercu["rule"]["id"] == chantier["id"]
    # Une seule étape (simultané) : l'employé + les numéros « suivi » de la ligne.
    assert apercu["plan"]["steps"] == [[EMPLOYEE_PHONE, "+15145550155"]]
    # La règle générale reste celle des autres chantiers / sans chantier.
    r = client.get(
        f"{API}/routing-rules/preview", headers=auth_headers,
        params={"subject": "suivi_projet"},
    )
    assert r.json()["rule"]["id"] == rule_id

    # Désactivée → ignorée par l'aperçu.
    r = client.put(
        f"{API}/routing-rules/{chantier['id']}", headers=auth_headers,
        json={
            "subject": "suivi_projet", "project_id": project_id, "active": False,
            "targets": [{"kind": "user", "user_id": employee_id}],
        },
    )
    assert r.status_code == 200 and r.json()["active"] is False
    r = client.get(
        f"{API}/routing-rules/preview", headers=auth_headers,
        params={"subject": "suivi_projet", "project_id": project_id},
    )
    assert r.json()["rule"]["id"] == rule_id

    # Aucun sujet inconnu, aucun chantier inconnu.
    r = client.get(
        f"{API}/routing-rules/preview", headers=auth_headers, params={"subject": "pizza"}
    )
    assert r.status_code == 400
    r = client.get(
        f"{API}/routing-rules/preview", headers=auth_headers,
        params={"subject": "suivi_projet", "project_id": 999999},
    )
    assert r.status_code == 404

    # Sujet sans règle → aperçu « flux historique » seulement.
    r = client.get(
        f"{API}/routing-rules/preview", headers=auth_headers,
        params={"subject": "urgence_locataire"},
    )
    assert r.status_code == 200
    assert r.json()["rule"] is None and r.json()["plan"] is None
    assert "24 h" in r.json()["fallback"]

    # Suppression.
    for rid in (chantier["id"], rule_id):
        r = client.delete(f"{API}/routing-rules/{rid}", headers=auth_headers)
        assert r.status_code == 204, r.text
    r = client.delete(f"{API}/routing-rules/{rule_id}", headers=auth_headers)
    assert r.status_code == 404
    r = client.put(
        f"{API}/routing-rules/{rule_id}", headers=auth_headers, json=generale
    )
    assert r.status_code == 404
    r = client.get(f"{API}/routing-rules", headers=auth_headers)
    assert all(x["id"] not in (rule_id, chantier["id"]) for x in r.json())

    async def _reste() -> int:
        async with TestSessionLocal() as db:
            return len((await db.execute(select(VoiceRoutingRule))).scalars().all())

    assert run(_reste()) == 0

    # Remise à zéro des heures de l'employé pour les tests suivants.
    r = client.put(
        f"{API}/call-hours/{employee_id}", headers=auth_headers, json={"hours": []}
    )
    assert r.status_code == 200


# ─────────────────────────────────────────────────────────────────────
# 3) Cascade de sonnerie dans la file d'attente (webhook Twilio simulé)
# ─────────────────────────────────────────────────────────────────────


class _FauxTwilio:
    """Double du provider : origine des jambes numérotées, mémorise les
    redirections TwiML, accepte toute signature."""

    def __init__(self) -> None:
        self.jambes: list[dict] = []
        self.redirections: list[tuple[str, str]] = []
        self.raccroches: list[str] = []

    async def initiate_outbound_call(
        self, *, from_e164, to_e164, twiml_url, status_callback_url, timeout_sec
    ) -> str:
        sid = f"CA-jambe-{len(self.jambes) + 1}"
        self.jambes.append(
            {
                "sid": sid,
                "from": from_e164,
                "to": to_e164,
                "twiml_url": twiml_url,
                "status_url": status_callback_url,
                "timeout": timeout_sec,
            }
        )
        return sid

    async def update_call_twiml(self, call_sid: str, url: str) -> None:
        self.redirections.append((call_sid, url))

    async def end_call(self, call_sid: str) -> None:
        self.raccroches.append(call_sid)

    def validate_webhook_signature(self, url, params, sig) -> bool:  # noqa: ANN001
        return True

    def build_say_and_enqueue(self, *, say, lang, queue_name, action_url) -> str:
        return (
            f'<Response><Say language="{lang}">{say}</Say>'
            f'<Enqueue action="{action_url}">{queue_name}</Enqueue></Response>'
        )


def test_cascade_file_attente(client, run, monkeypatch, acheminement_seed):
    faux = _FauxTwilio()

    async def _params_sans_signature(request):  # noqa: ANN001
        form = await request.form()
        return {k: str(v) for k, v in form.items()}

    monkeypatch.setattr(voice_ep, "_validate_twilio_signature", _params_sans_signature)
    monkeypatch.setattr(voice_ep, "_twilio_provider", lambda: faux)

    steps = [["+15145550101"], ["+15145550102", "client:user_7"], ["+15145550103"]]

    async def _demarrer() -> tuple[int, str]:
        async with TestSessionLocal() as db:
            call = Call(
                phone_number_id=acheminement_seed["phone_number_id"],
                provider_sid="CA-parent-smoke-19",
                direction="inbound",
                status="in-progress",
                from_e164="+15145550000",
                to_e164=LINE_E164,
                lang="fr-CA",
                intent="suivi_projet",
            )
            db.add(call)
            await db.flush()
            twiml = await voice_ep._start_queue_transfer(
                db,
                faux,
                call=call,
                targets=[d for step in steps for d in step],
                say="Un instant.",
                lang="fr-CA",
                steps=steps,
                step_timeout_sec=15,
            )
            call_id = call.id
            await db.commit()
            return call_id, twiml or ""

    call_id, twiml = run(_demarrer())
    assert "<Enqueue" in twiml and f"lea-{call_id}" in twiml
    # Seule la 1re étape sonne.
    assert [j["to"] for j in faux.jambes] == ["+15145550101"]
    assert faux.jambes[0]["from"] == LINE_E164
    assert faux.jambes[0]["timeout"] == 15
    assert f"call_id={call_id}" in faux.jambes[0]["status_url"]

    async def _etat() -> tuple[dict, Call]:
        async with TestSessionLocal() as db:
            call = await db.get(Call, call_id)
            return json.loads(call.dial_state_json or "{}"), call

    state, call = run(_etat())
    assert state["pending_steps"] == steps[1:]
    assert state["step_timeout_sec"] == 15
    assert state["legs"] == {"CA-jambe-1": "pending"}
    assert call.forwarded_to_e164 and len(call.forwarded_to_e164) <= 20

    def _statut(sid: str, statut: str) -> None:
        r = client.post(
            f"{API}/twilio/queue-agent-status",
            params={"call_id": call_id},
            data={"CallSid": sid, "CallStatus": statut},
        )
        assert r.status_code == 204, r.text

    # Statut intermédiaire → rien ne change.
    _statut("CA-jambe-1", "ringing")
    assert len(faux.jambes) == 1

    # 1re étape sans réponse → la 2e étape part (2 jambes), pas de boîte vocale.
    _statut("CA-jambe-1", "no-answer")
    assert [j["to"] for j in faux.jambes] == ["+15145550101", "+15145550102", "client:user_7"]
    assert faux.redirections == []
    state, _ = run(_etat())
    assert state["legs"] == {
        "CA-jambe-1": "done", "CA-jambe-2": "pending", "CA-jambe-3": "pending"
    }
    assert state["targets"]["CA-jambe-3"] == "client:user_7"
    assert state["pending_steps"] == [["+15145550103"]]
    assert state.get("outcome") is None

    # Une des deux jambes échoue : l'autre sonne encore → on attend.
    _statut("CA-jambe-2", "busy")
    assert len(faux.jambes) == 3 and faux.redirections == []
    # La seconde aussi → 3e (dernière) étape.
    _statut("CA-jambe-3", "no-answer")
    assert [j["to"] for j in faux.jambes][-1] == "+15145550103"
    assert faux.redirections == []
    state, _ = run(_etat())
    assert state["pending_steps"] == []
    assert state["legs"]["CA-jambe-4"] == "pending"

    # Dernière étape sans réponse → boîte vocale (redirection de l'appelant)
    # + lead de rappel.
    _statut("CA-jambe-4", "no-answer")
    assert len(faux.jambes) == 4
    assert len(faux.redirections) == 1
    sid, url = faux.redirections[0]
    assert sid == "CA-parent-smoke-19"
    assert "queue-timeout" in url and f"call_id={call_id}" in url
    state, call = run(_etat())
    assert state["outcome"] == "no-answer"
    assert "RAPPEL REQUIS" in (call.lead_reason or "")
    assert call.contact_request_id is not None

    # Un statut tardif n'origine plus rien et ne redirige pas deux fois.
    _statut("CA-jambe-4", "completed")
    assert len(faux.jambes) == 4 and len(faux.redirections) == 1
