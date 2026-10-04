"""Smoke — agenda de l'app mobile (Steven, 2026-10-04).

Un admin met un meeting ou un tournage dans l'agenda d'un employé depuis
le site ; l'employé le voit dans son app mobile. Un employé sans fiche
Employe (ex. vidéo / marketing) ne voit QUE ses événements, jamais tout
l'agenda de la compagnie.
"""

from datetime import datetime, timedelta, timezone


def _event(client, auth_headers, **extra) -> dict:
    start = datetime.now(timezone.utc) + timedelta(days=2)
    payload = {
        "title": "Événement smoke",
        "start_at": start.isoformat(),
        "end_at": (start + timedelta(hours=2)).isoformat(),
        **extra,
    }
    resp = client.post("/api/v1/agenda", headers=auth_headers, json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_mobile_agenda_montre_ses_evenements_seulement(
    client, auth_headers, employee_headers, employee_id
):
    tournage = _event(
        client,
        auth_headers,
        title="Tournage vidéo smoke",
        event_type="tournage",
        assignee_user_id=employee_id,
    )
    commun = _event(client, auth_headers, title="Chantier sans assigné smoke")

    resp = client.get("/api/v1/mobile/agenda?days=30", headers=employee_headers)
    assert resp.status_code == 200, resp.text
    ids = {e["id"] for e in resp.json()}
    assert tournage["id"] in ids
    # Pas de fiche Employe → pas d'événements communs de la compagnie.
    assert commun["id"] not in ids
    vu = next(e for e in resp.json() if e["id"] == tournage["id"])
    assert vu["event_type"] == "tournage"
