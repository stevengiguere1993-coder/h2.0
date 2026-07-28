"""Smoke — fenêtres réglables des SUIVIS ANNUELS (2026-07-28).

Retour Phil : « à partir de quand tu switch pour à confirmer / à
produire ? ». On vérifie la LOGIQUE pure (pas d'accès DB) + l'aller-retour
GET/PUT de la config.
"""
from __future__ import annotations

from datetime import date

from app.services.locatif_suivis import SuivisConfig


def test_fenetre_renouvellement_reglable():
    c = SuivisConfig(renouvellement_mois_avant=6)
    assert c.fenetre_renouvellement(60, avis_envoye=False) == "imminente"
    assert c.fenetre_renouvellement(150, avis_envoye=False) == "a_envoyer"
    assert c.fenetre_renouvellement(200, avis_envoye=False) == "hors_fenetre"
    assert c.fenetre_renouvellement(150, avis_envoye=True) == "envoye"
    # Fenêtre élargie à 8 mois → 200 j (~6,6 mois) devient « à envoyer ».
    c8 = SuivisConfig(renouvellement_mois_avant=8)
    assert c8.fenetre_renouvellement(200, avis_envoye=False) == "a_envoyer"


def test_statut_assurance_bascule_janvier():
    c = SuivisConfig(assurance_bascule_mois=1)
    today = date.today()
    # Confirmée l'an dernier (avant le 1er janvier de cette année) → à
    # reconfirmer ; confirmée cette année → ok ; jamais → jamais.
    an_dernier = date(today.year - 1, 6, 1)
    cette_annee = date(today.year, 1, 15)
    assert c.statut_assurance(an_dernier) == "a_reconfirmer"
    assert c.statut_assurance(cette_annee) == "ok"
    assert c.statut_assurance(None) == "jamais"


def test_annee_releve31_bascule():
    c = SuivisConfig(releve31_bascule_mois=2)
    # Jan/Fév → année précédente ; à partir de mars → année courante.
    assert c.annee_releve31_defaut(date(2026, 1, 15)) == 2025
    assert c.annee_releve31_defaut(date(2026, 2, 28)) == 2025
    assert c.annee_releve31_defaut(date(2026, 3, 1)) == 2026


def test_valeurs_hors_bornes_ignorees():
    from app.services.locatif_suivis import parse_suivis

    c = parse_suivis(
        {
            "renouvellement_mois_avant": 99,
            "assurance_bascule_mois": 0,
            "releve31_bascule_mois": "abc",
        }
    )
    assert c.renouvellement_mois_avant == 6  # défaut
    assert c.assurance_bascule_mois == 1  # défaut
    assert c.releve31_bascule_mois == 2  # défaut


def test_config_aller_retour(client, auth_headers):
    r = client.put(
        "/api/v1/immobilier/suivis-config",
        headers=auth_headers,
        json={
            "renouvellement_mois_avant": 8,
            "assurance_bascule_mois": 3,
            "releve31_bascule_mois": 1,
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["renouvellement_mois_avant"] == 8

    g = client.get(
        "/api/v1/immobilier/suivis-config", headers=auth_headers
    )
    assert g.status_code == 200, g.text
    assert g.json() == {
        "renouvellement_mois_avant": 8,
        "assurance_bascule_mois": 3,
        "releve31_bascule_mois": 1,
    }

    # Remise aux défauts pour ne pas polluer les autres tests.
    client.put(
        "/api/v1/immobilier/suivis-config",
        headers=auth_headers,
        json={
            "renouvellement_mois_avant": 6,
            "assurance_bascule_mois": 1,
            "releve31_bascule_mois": 2,
        },
    )
