"""Smoke — agenda de l'app mobile (Steven, 2026-10-04).

Un admin met un meeting ou un tournage dans l'agenda d'un employé depuis
le site ; l'employé le voit dans son app mobile. Un employé sans fiche
Employe (ex. vidéo / marketing) ne voit QUE ses événements, jamais tout
l'agenda de la compagnie. Un employé de Construction voit ses événements
et les consignes de chantier sans assigné, pas celles des autres.
"""

import json
import uuid
from datetime import datetime, timedelta, timezone

from app.core.security import create_access_token, get_password_hash
from app.models.employe import Employe
from app.models.user import User

from .conftest import TestSessionLocal


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


def _seed_user(run, *, volets: list[str], with_employe: bool) -> dict:
    """Crée un User (rôle employee) et, si demandé, sa fiche Employe liée
    par courriel. Courriel UNIQUE : la base smoke est partagée par toute
    la session, on ne touche pas aux comptes seedés par le conftest."""
    email = f"smoke-agenda-{uuid.uuid4().hex[:10]}@example.com"

    async def _go() -> dict:
        async with TestSessionLocal() as s:
            u = User(
                email=email,
                hashed_password=get_password_hash("smoke-agenda-x"),
                is_active=True,
                is_admin=False,
                role="employee",
                volets_json=json.dumps(volets),
            )
            s.add(u)
            await s.flush()
            emp_id = None
            if with_employe:
                e = Employe(full_name=f"Smoke {email[:12]}", email=email, active=True)
                s.add(e)
                await s.flush()
                emp_id = e.id
            await s.commit()
            return {"user_id": u.id, "employe_id": emp_id}

    ids = run(_go())
    token = create_access_token(subject=str(ids["user_id"]))
    ids["headers"] = {"Authorization": f"Bearer {token}"}
    return ids


def _agenda_ids(client, headers) -> set[int]:
    resp = client.get("/api/v1/mobile/agenda?days=30", headers=headers)
    assert resp.status_code == 200, resp.text
    return {e["id"] for e in resp.json()}


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


def test_mobile_agenda_construction_vs_autre_pole(client, auth_headers, run):
    chantier = _seed_user(run, volets=["construction"], with_employe=True)
    collegue = _seed_user(run, volets=["construction"], with_employe=True)
    video = _seed_user(run, volets=["entreprises"], with_employe=False)

    mien_fiche = _event(
        client, auth_headers, title="Ma visite", assignee_id=chantier["employe_id"]
    )
    mien_compte = _event(
        client,
        auth_headers,
        title="Ma réunion",
        event_type="reunion",
        assignee_user_id=chantier["user_id"],
    )
    mien_prospection = _event(
        client,
        auth_headers,
        title="Mon RDV prospection",
        scope="prospection",
        assignee_id=chantier["employe_id"],
    )
    commun_chantier = _event(client, auth_headers, title="Livraison chantier")
    commun_prospection = _event(
        client, auth_headers, title="Blitz prospection", scope="prospection"
    )
    du_collegue = _event(
        client, auth_headers, title="Visite collègue", assignee_id=collegue["employe_id"]
    )
    tournage_video = _event(
        client,
        auth_headers,
        title="Tournage marketing",
        event_type="tournage",
        assignee_user_id=video["user_id"],
    )

    # Employé de Construction : ses événements (fiche, compte, même en
    # scope prospection s'ils lui sont assignés) + consignes chantier
    # communes. Jamais ceux du collègue, ni la prospection sans assigné,
    # ni le tournage de l'employé vidéo.
    vus = _agenda_ids(client, chantier["headers"])
    assert {mien_fiche["id"], mien_compte["id"], mien_prospection["id"]} <= vus
    assert commun_chantier["id"] in vus
    assert commun_prospection["id"] not in vus
    assert du_collegue["id"] not in vus
    assert tournage_video["id"] not in vus

    # Employé vidéo (compte sans fiche, autre pôle) : son tournage, rien
    # d'autre — même pas les consignes chantier communes.
    vus_video = _agenda_ids(client, video["headers"])
    assert vus_video == {tournage_video["id"]}

    # L'écran d'accueil (/mobile/me) applique la même visibilité :
    # le prochain événement de l'employé vidéo est son tournage.
    me = client.get("/api/v1/mobile/me", headers=video["headers"])
    assert me.status_code == 200, me.text
    assert me.json()["employe"] is None
    assert me.json()["next_event"]["id"] == tournage_video["id"]

    me_chantier = client.get("/api/v1/mobile/me", headers=chantier["headers"])
    assert me_chantier.status_code == 200, me_chantier.text
    prochain = me_chantier.json()["next_event"]
    assert prochain is not None
    assert prochain["id"] not in {
        du_collegue["id"],
        commun_prospection["id"],
        tournage_video["id"],
    }
