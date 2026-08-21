"""Smoke — photos d'un bon de travail par la route GÉNÉRIQUE (2026-08-21).

Bug rapporté par le chargé de projet construction : « je ne suis pas
capable de mettre de photo dans mes bons ». Cause : la page des bons
construction appelait les routes IMMOBILIER, qui exigent le volet
immobilier et ne connaissent que les bons gestion immo. Un utilisateur
construction recevait un 403 — et l'écran l'avalait.

Ces tests verrouillent :
1. un utilisateur SANS volet immobilier (l'employé de test : volets par
   défaut = construction…) peut téléverser par la route générique, et
   reçoit bien 403 par la route immobilier — c'est exactement le trou ;
2. un bon CONSTRUCTION (pas interne) accepte des photos ;
3. le cycle complet : liste, octets, format refusé, suppression.
"""
from __future__ import annotations

import uuid

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def _creer_bon(client, headers, *, kind: str | None) -> int:
    payload = {
        "title": f"Photos smoke {kind or 'construction'}",
        "address": "12 rue de la Photo",
        "reference": f"BT-PH-{uuid.uuid4().hex[:10]}",
    }
    if kind:
        payload["kind"] = kind
    r = client.post("/api/v1/bons-travail", headers=headers, json=payload)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _upload(client, headers, url: str, *, ct: str = "image/png"):
    return client.post(
        url, headers=headers, files={"file": ("avant.png", PNG, ct)}
    )


def test_employe_construction_sans_volet_immobilier_peut_joindre_une_photo(
    client, auth_headers, employee_headers
):
    """Le trou d'origine. L'employé de test a les volets par défaut
    (construction, prospection, dev logiciel) — PAS immobilier."""
    bon_id = _creer_bon(client, auth_headers, kind="interne")

    # Route IMMOBILIER : 403 — c'est ce que le chargé de projet subissait.
    r_immo = _upload(
        client, employee_headers,
        f"/api/v1/immobilier/bons-travail/{bon_id}/photos",
    )
    assert r_immo.status_code == 403, r_immo.text

    # Route GÉNÉRIQUE : ça passe.
    r = _upload(client, employee_headers, f"/api/v1/bons-travail/{bon_id}/photos")
    assert r.status_code == 201, r.text
    assert r.json()["photo_id"]

    # Et il voit sa photo.
    liste = client.get(
        f"/api/v1/bons-travail/{bon_id}/photos", headers=employee_headers
    )
    assert liste.status_code == 200, liste.text
    assert len(liste.json()) == 1


def test_un_bon_construction_accepte_des_photos(client, auth_headers):
    """Avant, la section Photos n'existait QUE pour les bons internes,
    et la route immobilier répondait 404 pour un bon construction."""
    bon_id = _creer_bon(client, auth_headers, kind=None)  # construction
    r = _upload(client, auth_headers, f"/api/v1/bons-travail/{bon_id}/photos")
    assert r.status_code == 201, r.text


def test_cycle_complet_liste_octets_format_suppression(client, auth_headers):
    bon_id = _creer_bon(client, auth_headers, kind="interne")
    base = f"/api/v1/bons-travail/{bon_id}/photos"

    # Format refusé : message explicite, pas un succès silencieux.
    bad = _upload(client, auth_headers, base, ct="text/plain")
    assert bad.status_code == 415, bad.text
    assert "Format" in bad.text

    photo_id = _upload(client, auth_headers, base).json()["photo_id"]

    # Les octets reviennent avec le bon type MIME.
    img = client.get(f"{base}/{photo_id}", headers=auth_headers)
    assert img.status_code == 200
    assert img.headers["content-type"].startswith("image/png")
    assert img.content == PNG

    # Une photo d'un AUTRE bon n'est pas servie par cet id (pas d'accès
    # par id deviné).
    autre = _creer_bon(client, auth_headers, kind="interne")
    assert client.get(
        f"/api/v1/bons-travail/{autre}/photos/{photo_id}", headers=auth_headers
    ).status_code == 404

    # Suppression, puis liste vide.
    assert client.delete(
        f"{base}/{photo_id}", headers=auth_headers
    ).status_code == 204
    assert client.get(base, headers=auth_headers).json() == []
