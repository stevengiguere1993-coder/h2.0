"""Smoke — bloc-notes de la zone employés (Steven, bug 13, 2026-10-18).

« Bloc note (tâches) que employés voit et admin / proprio. Admin proprio
peut envoyer à n'importe qui… dans la zone employé. »

Un employé s'écrit des notes dans son bloc-notes (zone employés, menu
Plus), les coche et supprime les siennes ; un admin ou un propriétaire
envoie une note à n'importe quel employé (notification cloche + push),
voit tous les blocs-notes et peut modifier ou supprimer ce qu'il a
envoyé ; l'employé qui reçoit une note peut la cocher mais pas l'effacer.
"""
from __future__ import annotations

import pytest
from sqlalchemy import select

from app.core.api_ia_couverture import TABLES_COUVERTES
from app.core.security import create_access_token, get_password_hash
from app.models.notification import Notification
from app.models.user import User

from tests.smoke.conftest import TestSessionLocal

COLLEGUE_EMAIL = "collegue.bloc@example.com"


@pytest.fixture(scope="module")
def collegue(run) -> dict:
    """Second employé (Construction par défaut), pour les envois multiples
    et les cloisonnements."""

    async def _seed():
        async with TestSessionLocal() as s:
            u = User(
                email=COLLEGUE_EMAIL,
                hashed_password=get_password_hash("x" * 12),
                is_active=True,
                is_admin=False,
                role="employee",
                first_name="Carl",
                last_name="Collègue",
            )
            s.add(u)
            await s.commit()
            return {"id": u.id}

    ids = run(_seed())
    token = create_access_token(subject=str(ids["id"]))
    return {**ids, "headers": {"Authorization": f"Bearer {token}"}}


def _ids(resp) -> set[int]:
    return {n["id"] for n in resp.json()}


# ── Mon bloc-notes ──────────────────────────────────────────────────────


def test_employe_gere_ses_propres_notes(client, employee_headers, employee_id):
    h = employee_headers

    r = client.post(
        "/api/v1/bloc-notes",
        headers=h,
        json={"contenu": "  Rappeler le fournisseur de gypse ", "titre": " Gypse "},
    )
    assert r.status_code == 201, r.text
    notes = r.json()
    assert len(notes) == 1
    note = notes[0]
    assert note["contenu"] == "Rappeler le fournisseur de gypse"
    assert note["titre"] == "Gypse"
    assert note["destinataire_user_id"] == employee_id
    assert note["auteur_user_id"] == employee_id
    assert note["pour_moi"] is True and note["de_moi"] is True
    assert note["peut_modifier"] is True and note["peut_supprimer"] is True
    assert note["fait"] is False
    # Ma propre note n'est pas « nouvelle » pour moi.
    assert note["lu_le"] is not None

    r = client.get("/api/v1/bloc-notes", headers=h)
    assert r.status_code == 200, r.text
    assert note["id"] in _ids(r)

    # Modifier le texte + mettre une échéance, puis cocher.
    r = client.patch(
        f"/api/v1/bloc-notes/{note['id']}",
        headers=h,
        json={"contenu": "Rappeler le fournisseur de gypse (prix)", "echeance": "2026-10-20"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["contenu"] == "Rappeler le fournisseur de gypse (prix)"
    assert r.json()["echeance"] == "2026-10-20"

    r = client.patch(f"/api/v1/bloc-notes/{note['id']}", headers=h, json={"fait": True})
    assert r.status_code == 200, r.text
    assert r.json()["fait"] is True and r.json()["fait_le"] is not None
    # Faite → disparaît de la liste par défaut, revient avec include_fait.
    assert note["id"] not in _ids(client.get("/api/v1/bloc-notes", headers=h))
    assert note["id"] in _ids(
        client.get("/api/v1/bloc-notes?include_fait=true", headers=h)
    )
    # Décocher remet à faire.
    r = client.patch(f"/api/v1/bloc-notes/{note['id']}", headers=h, json={"fait": False})
    assert r.json()["fait"] is False and r.json()["fait_le"] is None

    # Effacer le titre avec un null explicite.
    r = client.patch(f"/api/v1/bloc-notes/{note['id']}", headers=h, json={"titre": None})
    assert r.status_code == 200, r.text
    assert r.json()["titre"] is None

    # Note vide refusée.
    r = client.post("/api/v1/bloc-notes", headers=h, json={"contenu": "   "})
    assert r.status_code == 422, r.text

    # Je supprime la mienne.
    r = client.delete(f"/api/v1/bloc-notes/{note['id']}", headers=h)
    assert r.status_code == 204, r.text
    assert note["id"] not in _ids(
        client.get("/api/v1/bloc-notes?include_fait=true", headers=h)
    )


def test_employe_ne_peut_pas_envoyer_ni_voir_les_autres(
    client, employee_headers, collegue, admin_id
):
    h = employee_headers
    r = client.post(
        "/api/v1/bloc-notes",
        headers=h,
        json={"contenu": "Pour toi", "destinataire_user_ids": [collegue["id"]]},
    )
    assert r.status_code == 403, r.text
    assert client.get("/api/v1/bloc-notes?vue=tous", headers=h).status_code == 403
    assert (
        client.get(f"/api/v1/bloc-notes?user_id={collegue['id']}", headers=h).status_code
        == 403
    )
    assert client.get("/api/v1/bloc-notes/destinataires", headers=h).status_code == 403
    # Son propre bloc-notes par user_id reste permis.
    assert (
        client.get(f"/api/v1/bloc-notes?user_id={admin_id}", headers=h).status_code == 403
    )
    r = client.get("/api/v1/bloc-notes/resume", headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["peut_envoyer"] is False


# ── Envoi par un admin / propriétaire ───────────────────────────────────


def test_admin_envoie_une_note_a_des_employes(
    client, auth_headers, employee_headers, employee_id, collegue, admin_id, run
):
    # Les destinataires possibles : comptes actifs, moi en premier.
    r = client.get("/api/v1/bloc-notes/destinataires", headers=auth_headers)
    assert r.status_code == 200, r.text
    dest = r.json()
    assert dest[0]["est_moi"] is True and dest[0]["id"] == admin_id
    par_id = {d["id"]: d for d in dest}
    assert par_id[collegue["id"]]["nom"] == "Carl Collègue"
    assert employee_id in par_id

    r = client.post(
        "/api/v1/bloc-notes",
        headers=auth_headers,
        json={
            "titre": "Clés du 8900",
            "contenu": "Passer chercher les clés au bureau avant 8 h.",
            "echeance": "2026-10-21",
            "destinataire_user_ids": [employee_id, collegue["id"], employee_id],
        },
    )
    assert r.status_code == 201, r.text
    creees = r.json()
    # Doublon dédoublonné : une note par destinataire.
    assert sorted(n["destinataire_user_id"] for n in creees) == sorted(
        [employee_id, collegue["id"]]
    )
    pour_employe = next(n for n in creees if n["destinataire_user_id"] == employee_id)
    assert pour_employe["auteur_user_id"] == admin_id
    assert pour_employe["pour_moi"] is False and pour_employe["de_moi"] is True
    assert pour_employe["lu_le"] is None  # pas encore ouverte par l'employé

    # L'employé la voit, « nouvelle », ne peut ni la modifier ni la supprimer…
    h = employee_headers
    r = client.get("/api/v1/bloc-notes/resume", headers=h)
    assert r.json()["non_lues"] == 1 and r.json()["ouvertes"] >= 1
    r = client.get("/api/v1/bloc-notes", headers=h)
    recue = next(n for n in r.json() if n["id"] == pour_employe["id"])
    assert recue["pour_moi"] is True and recue["de_moi"] is False
    assert recue["peut_modifier"] is False and recue["peut_supprimer"] is False
    assert recue["auteur_nom"]  # nom de l'admin affiché
    r = client.patch(
        f"/api/v1/bloc-notes/{recue['id']}", headers=h, json={"contenu": "Hé"}
    )
    assert r.status_code == 403, r.text
    assert client.delete(f"/api/v1/bloc-notes/{recue['id']}", headers=h).status_code == 403

    # …et il a reçu une notification (cloche ; push best-effort sans VAPID).
    async def _notifs():
        async with TestSessionLocal() as s:
            rows = (
                await s.execute(
                    select(Notification).where(
                        Notification.user_id == employee_id,
                        Notification.kind == "bloc_note",
                    )
                )
            ).scalars().all()
            return [(n.title, n.body, n.href) for n in rows]

    notifs = run(_notifs())
    assert len(notifs) == 1, notifs
    assert notifs[0][0].startswith("Note de ")
    assert notifs[0][1] == "Clés du 8900"
    assert notifs[0][2] == "/m/notes"

    # Il ouvre son bloc-notes : plus rien de nouveau.
    r = client.post("/api/v1/bloc-notes/tout-lu", headers=h)
    assert r.status_code == 200 and r.json()["updated"] == 1
    assert client.get("/api/v1/bloc-notes/resume", headers=h).json()["non_lues"] == 0
    r = client.get("/api/v1/bloc-notes", headers=h)
    assert next(n for n in r.json() if n["id"] == recue["id"])["lu_le"] is not None

    # Il peut la cocher.
    r = client.patch(f"/api/v1/bloc-notes/{recue['id']}", headers=h, json={"fait": True})
    assert r.status_code == 200, r.text
    assert r.json()["fait"] is True

    # Le collègue ne voit pas la note de l'employé.
    r = client.get("/api/v1/bloc-notes?include_fait=true", headers=collegue["headers"])
    assert recue["id"] not in _ids(r)
    assert client.patch(
        f"/api/v1/bloc-notes/{recue['id']}", headers=collegue["headers"], json={"fait": True}
    ).status_code == 404

    # L'admin revoit ce qu'il a envoyé, tout le monde, ou un employé donné.
    r = client.get("/api/v1/bloc-notes?vue=envoyees&include_fait=true", headers=auth_headers)
    assert {n["id"] for n in creees} <= _ids(r)
    r = client.get("/api/v1/bloc-notes?vue=tous&include_fait=true", headers=auth_headers)
    assert {n["id"] for n in creees} <= _ids(r)
    r = client.get(
        f"/api/v1/bloc-notes?user_id={collegue['id']}", headers=auth_headers
    )
    assert _ids(r) == {n["id"] for n in creees if n["destinataire_user_id"] == collegue["id"]}
    # Son propre bloc-notes n'a pas la note envoyée aux autres.
    assert not ({n["id"] for n in creees} & _ids(client.get("/api/v1/bloc-notes", headers=auth_headers)))

    # L'admin corrige puis supprime ce qu'il a envoyé.
    autre = next(n for n in creees if n["destinataire_user_id"] == collegue["id"])
    r = client.patch(
        f"/api/v1/bloc-notes/{autre['id']}",
        headers=auth_headers,
        json={"contenu": "Clés au bureau avant 7 h 30.", "echeance": None},
    )
    assert r.status_code == 200, r.text
    assert r.json()["contenu"] == "Clés au bureau avant 7 h 30." and r.json()["echeance"] is None
    for n in creees:
        assert client.delete(f"/api/v1/bloc-notes/{n['id']}", headers=auth_headers).status_code == 204

    # Destinataire inconnu → 404 ; vue inconnue → 422.
    r = client.post(
        "/api/v1/bloc-notes",
        headers=auth_headers,
        json={"contenu": "x", "destinataire_user_ids": [999999]},
    )
    assert r.status_code == 404, r.text
    assert client.get("/api/v1/bloc-notes?vue=bidon", headers=auth_headers).status_code == 422


def test_tri_ouvertes_puis_echeance(client, employee_headers):
    h = employee_headers
    sans = client.post("/api/v1/bloc-notes", headers=h, json={"contenu": "sans échéance"}).json()[0]
    loin = client.post(
        "/api/v1/bloc-notes", headers=h, json={"contenu": "loin", "echeance": "2030-01-01"}
    ).json()[0]
    proche = client.post(
        "/api/v1/bloc-notes", headers=h, json={"contenu": "proche", "echeance": "2026-11-01"}
    ).json()[0]
    faite = client.post("/api/v1/bloc-notes", headers=h, json={"contenu": "faite"}).json()[0]
    client.patch(f"/api/v1/bloc-notes/{faite['id']}", headers=h, json={"fait": True})
    ordre = [n["id"] for n in client.get("/api/v1/bloc-notes?include_fait=true", headers=h).json()]
    assert ordre.index(proche["id"]) < ordre.index(loin["id"]) < ordre.index(sans["id"])
    assert ordre.index(sans["id"]) < ordre.index(faite["id"])
    for n in (sans, loin, proche, faite):
        client.delete(f"/api/v1/bloc-notes/{n['id']}", headers=h)


# ── IA au courant de tout ───────────────────────────────────────────────


def test_bloc_notes_exposees_a_la_cle_api(client, auth_headers, employee_id, api_key_headers):
    assert "bloc_notes" in TABLES_COUVERTES

    from app.api.v1.endpoints.activity import _DETAIL_ENTITIES, _resolve_list_spec
    from app.api.v1.endpoints.mcp_server import _LIST_GENERIC_CHOICES
    from app.services.entity_serializers import serialize_entity

    spec = _resolve_list_spec("bloc_notes")
    assert spec is not None and spec.entity_type == "bloc_note"
    assert _resolve_list_spec("bloc_note") is spec
    assert "bloc_note" in _DETAIL_ENTITIES
    assert "bloc_notes" in _LIST_GENERIC_CHOICES

    note = client.post(
        "/api/v1/bloc-notes",
        headers=auth_headers,
        json={"titre": "Vérifier l'échafaudage", "contenu": "Côté nord, avant lundi.",
              "destinataire_user_ids": [employee_id]},
    ).json()[0]

    # Liste générique par clé d'API (clé sans scopes = lecture tous pôles).
    r = client.get("/api/v1/activity/entities/bloc_notes", headers=api_key_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["entity_type"] == "bloc_note" and body["pole"] == "construction"
    item = next(i for i in body["items"] if i["id"] == note["id"])
    assert item["label"] == "Vérifier l'échafaudage"
    assert item["status"] == "a_faire" and item["is_completed"] is False
    assert item["destinataire_user_id"] == employee_id

    class _Obj:
        pass

    o = _Obj()
    o.id, o.titre, o.contenu, o.fait = 7, None, "x" * 100, True
    o.destinataire_user_id, o.auteur_user_id, o.echeance, o.updated_at = 1, 2, None, None
    data = serialize_entity("bloc_note", o, level="summary")
    assert data["label"].endswith("…") and len(data["label"]) <= 80
    assert data["status"] == "fait" and data["is_completed"] is True

    client.delete(f"/api/v1/bloc-notes/{note['id']}", headers=auth_headers)
