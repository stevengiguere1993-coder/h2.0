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
    # Bail ÉCHU sans avis → « echu » (visible, à corriger) ; avec avis
    # dans le système → reste « envoye ».
    assert c.fenetre_renouvellement(-10, avis_envoye=False) == "echu"
    assert c.fenetre_renouvellement(-10, avis_envoye=True) == "envoye"


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
        "assurance_inclut_au_mois": False,
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


def test_bail_au_mois_et_reconduction(client, auth_headers, run):
    """Bail AU MOIS : hors du suivi des renouvellements (même échu) et du
    suivi des assurances (défaut) ; « Reconduire tel quel » roule la date
    de fin d'un an sans toucher au reste."""
    from datetime import date, timedelta

    from app.models.immobilier import (
        Bail,
        BailStatus,
        Immeuble,
        Locataire,
        Logement,
        LogementStatus,
    )

    from .conftest import TestSessionLocal

    async def _seed():
        async with TestSessionLocal() as s:
            imm = Immeuble(
                name="Maison de chambres", address="1 rue Chambre",
                is_active=True,
            )
            s.add(imm)
            await s.flush()
            lg = Logement(
                immeuble_id=imm.id, numero="CH-1",
                status=LogementStatus.OCCUPE.value,
                location_en_chambres=True,
            )
            loc = Locataire(full_name="Chambreur Smoke")
            s.add_all([lg, loc])
            await s.flush()
            # Bail au mois ÉCHU (date_fin passée) — ne doit PAS apparaître.
            b1 = Bail(
                logement_id=lg.id, locataire_id=loc.id,
                date_debut=date.today() - timedelta(days=400),
                date_fin=date.today() - timedelta(days=30),
                loyer_mensuel=500.0,
                status=BailStatus.ACTIF.value,
                au_mois=True,
            )
            # Bail annuel dans la fenêtre — sert au test de reconduction.
            lg2 = Logement(
                immeuble_id=imm.id, numero="CH-2",
                status=LogementStatus.OCCUPE.value,
            )
            loc2 = Locataire(full_name="Annuel Smoke")
            s.add_all([lg2, loc2])
            await s.flush()
            b2 = Bail(
                logement_id=lg2.id, locataire_id=loc2.id,
                date_debut=date.today() - timedelta(days=250),
                date_fin=date.today() + timedelta(days=115),
                loyer_mensuel=900.0,
                status=BailStatus.ACTIF.value,
            )
            s.add_all([b1, b2])
            await s.commit()
            return {"au_mois": b1.id, "annuel": b2.id,
                    "fin_annuel": b2.date_fin}

    ids = run(_seed())

    # Renouvellements : le bail au mois (échu !) est absent, l'annuel présent.
    rows = client.get(
        "/api/v1/immobilier/renouvellements/overview", headers=auth_headers
    ).json()
    par_bail = {r["bail_id"]: r for r in rows}
    assert ids["au_mois"] not in par_bail
    assert ids["annuel"] in par_bail

    # Assurances : le chambreur est absent par défaut…
    rows = client.get(
        "/api/v1/immobilier/assurances/overview", headers=auth_headers
    ).json()["rows"]
    noms = {r["locataire_nom"] for r in rows}
    assert "Chambreur Smoke" not in noms
    assert "Annuel Smoke" in noms
    # … mais revient si le réglage l'inclut.
    client.put(
        "/api/v1/immobilier/suivis-config",
        headers=auth_headers,
        json={
            "renouvellement_mois_avant": 6,
            "assurance_bascule_mois": 1,
            "releve31_bascule_mois": 2,
            "assurance_inclut_au_mois": True,
        },
    )
    rows = client.get(
        "/api/v1/immobilier/assurances/overview", headers=auth_headers
    ).json()["rows"]
    assert "Chambreur Smoke" in {r["locataire_nom"] for r in rows}
    client.put(
        "/api/v1/immobilier/suivis-config",
        headers=auth_headers,
        json={
            "renouvellement_mois_avant": 6,
            "assurance_bascule_mois": 1,
            "releve31_bascule_mois": 2,
            "assurance_inclut_au_mois": False,
        },
    )

    # Reconduction tacite : date_fin +1 an, même jour.
    r = client.post(
        f"/api/v1/immobilier/baux/{ids['annuel']}/reconduire",
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    d = r.json()
    fin = ids["fin_annuel"]
    assert d["ancienne_date_fin"] == fin.isoformat()
    assert d["nouvelle_date_fin"] == fin.replace(year=fin.year + 1).isoformat()
