"""Smoke — hub Rencontres v2 (2026-07-28).

Import unifié (texte collé, fichier .txt, transcript Teams .vtt) et
conversion des action items du résumé IA en tâches Kratos. L'audio
(transcription Gemini) et l'archivage Drive ne sont pas testés ici
(dépendances externes) — le parser VTT l'est en pur.
"""
from __future__ import annotations

import io
import json

from app.services.rencontre_import import detecter_type, parse_vtt

VTT_TEAMS = """WEBVTT

6a05cbc7-1111-2222-3333-444455556666/19-0
00:00:03.120 --> 00:00:06.000
<v Philippe Meuser>Bonjour tout le monde, on commence.</v>

6a05cbc7-1111-2222-3333-444455556666/19-1
00:00:06.500 --> 00:00:09.000
<v Philippe Meuser>Premier point : le budget.</v>

2
00:00:09.500 --> 00:00:12.000
<v Steven Giguere>Merci</v>
"""


def test_parse_vtt_teams():
    txt = parse_vtt(VTT_TEAMS)
    # Interlocuteurs conservés, répliques consécutives fusionnées.
    assert txt == (
        "Philippe Meuser : Bonjour tout le monde, on commence. "
        "Premier point : le budget.\n"
        "Steven Giguere : Merci"
    )


def test_parse_vtt_sans_speakers():
    brut = "WEBVTT\n\n1\n00:00:01.000 --> 00:00:02.000\nAllo\n\n" \
        "2\n00:00:02.000 --> 00:00:03.000\nDeuxième ligne ici\n"
    assert parse_vtt(brut) == "Allo\nDeuxième ligne ici"


def test_detecter_type():
    assert detecter_type("reunion.vtt", "text/vtt") == "vtt"
    assert detecter_type("notes.txt", "text/plain") == "texte"
    assert detecter_type("Voice 001.m4a", "audio/mp4") == "audio"
    # Samsung partage parfois en video/mp4 ou octet-stream → audio.
    assert detecter_type("Voice 002.m4a", "video/mp4") == "audio"
    assert detecter_type("enregistrement", "application/octet-stream") == "audio"


def test_import_texte_colle(client, auth_headers):
    r = client.post(
        "/api/v1/rencontres/importer",
        headers=auth_headers,
        data={
            "texte": "Phil : on lance le projet X.\nSteven : d'accord.",
            "title": "Comité smoke",
            "meeting_date": "2026-07-28",
        },
    )
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["title"] == "Comité smoke"
    assert d["source"] == "texte"
    assert len(d["sections"]) == 1
    assert "projet X" in d["sections"][0]["transcript"]


def test_import_fichier_vtt(client, auth_headers):
    r = client.post(
        "/api/v1/rencontres/importer",
        headers=auth_headers,
        files={"file": ("reunion.vtt", io.BytesIO(VTT_TEAMS.encode()), "text/vtt")},
    )
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["source"] == "teams"
    assert d["title"] == "reunion"  # nom du fichier sans extension
    assert "Philippe Meuser :" in d["sections"][0]["transcript"]
    # Les timestamps et cue ids ne doivent PAS survivre.
    assert "-->" not in d["sections"][0]["transcript"]


def test_import_vide_cree_rencontre_notes(client, auth_headers):
    r = client.post(
        "/api/v1/rencontres/importer",
        headers=auth_headers,
        data={"title": "Notes à la main"},
    )
    assert r.status_code == 201, r.text
    assert r.json()["source"] == "notes"


def test_actions_vers_taches(client, auth_headers, run):
    from app.models.entreprise import Entreprise

    from .conftest import TestSessionLocal

    async def _seed():
        async with TestSessionLocal() as s:
            e = Entreprise(name="Entreprise Smoke Rencontres")
            s.add(e)
            await s.commit()
            return e.id

    ent_id = run(_seed())

    r = client.post(
        "/api/v1/rencontres/importer",
        headers=auth_headers,
        data={
            "texte": "On doit envoyer la soumission.",
            "title": "Suivi actions",
            "entreprise_ids": json.dumps([ent_id]),
        },
    )
    assert r.status_code == 201, r.text
    rid = r.json()["id"]

    t = client.post(
        f"/api/v1/rencontres/{rid}/actions-vers-taches",
        headers=auth_headers,
        json={
            "entreprise_id": ent_id,
            "actions": [
                {"title": "Envoyer la soumission", "description": "Avant vendredi"},
                {"title": "Relancer le client"},
            ],
        },
    )
    assert t.status_code == 200, t.text
    assert t.json()["created"] == 2

    # Les tâches existent vraiment, rattachées à l'entreprise, avec le
    # contexte de la rencontre dans la description.
    lst = client.get(
        f"/api/v1/entreprises/taches?entreprise_id={ent_id}",
        headers=auth_headers,
    )
    assert lst.status_code == 200, lst.text
    titres = {x["title"] for x in lst.json()}
    assert "Envoyer la soumission" in titres
    assert "Relancer le client" in titres

    # Entreprise inconnue → 404 propre.
    bad = client.post(
        f"/api/v1/rencontres/{rid}/actions-vers-taches",
        headers=auth_headers,
        json={"entreprise_id": 999999, "actions": [{"title": "x"}]},
    )
    assert bad.status_code == 404
