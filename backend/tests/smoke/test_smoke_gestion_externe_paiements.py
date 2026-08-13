"""Smoke — la GESTION EXTERNE dans la page Paiements (2026-08-13).

Retour Phil : « ceux-ci devraient aussi être dans la page paiement
générale ». On vérifie les deux moitiés de la règle :

- ``/loyers/overview`` (suivi OPÉRATIONNEL : relances, renouvellements,
  dépôts) continue d'ignorer la gestion externe ;
- ``/loyers/externes`` (AFFICHAGE) la remonte, avec les mêmes états que
  l'interne et le manquant du mois.
"""
from __future__ import annotations

from datetime import date, timedelta


def _mois_courant() -> str:
    return date.today().strftime("%Y-%m")


def test_externes_visibles_en_paiements_mais_hors_overview(
    client, auth_headers, run
):
    from app.models.immobilier import Immeuble, Logement, LogementStatus

    from .conftest import TestSessionLocal

    async def _seed():
        async with TestSessionLocal() as s:
            imm = Immeuble(
                name="Tour Déléguée",
                address="9 rue Externe",
                is_active=True,
                gestion_externe=True,
            )
            s.add(imm)
            await s.flush()
            occupe = Logement(
                immeuble_id=imm.id,
                numero="EXT-1",
                status=LogementStatus.OCCUPE.value,
                loyer_demande=800.0,
            )
            vacant = Logement(
                immeuble_id=imm.id,
                numero="EXT-2",
                status=LogementStatus.VACANT.value,
            )
            s.add_all([occupe, vacant])
            await s.commit()
            return {
                "immeuble": imm.id,
                "occupe": occupe.id,
                "vacant": vacant.id,
            }

    ids = run(_seed())
    mois = _mois_courant()

    # 1. Le suivi interne ne doit RIEN voir de cet immeuble.
    ov = client.get(
        f"/api/v1/immobilier/loyers/overview?mois={mois}",
        headers=auth_headers,
    ).json()
    assert all(r["immeuble_id"] != ids["immeuble"] for r in ov["rows"])

    # 2. La vue portefeuille externe le remonte — logement occupé
    #    seulement (rien n'est attendu d'un vacant).
    ext = client.get(
        f"/api/v1/immobilier/loyers/externes?mois={mois}",
        headers=auth_headers,
    )
    assert ext.status_code == 200, ext.text
    rows = {r["logement_id"]: r for r in ext.json()["rows"]}
    assert ids["vacant"] not in rows
    ligne = rows[ids["occupe"]]
    assert ligne["immeuble_id"] == ids["immeuble"]
    assert ligne["loyer_mensuel"] == 800.0
    # États alignés sur l'interne (jamais « a_confirmer »).
    assert ligne["etat"] in ("retard", "attente")
    assert ligne["solde_total"] == 800.0

    # 3. Paiement PARTIEL : le manquant du mois reste visible.
    r = client.post(
        "/api/v1/immobilier/paiements-externes",
        headers=auth_headers,
        json={"logement_id": ids["occupe"], "mois": mois, "montant": 300},
    )
    assert r.status_code == 201, r.text
    ligne = {
        x["logement_id"]: x
        for x in client.get(
            f"/api/v1/immobilier/loyers/externes?mois={mois}",
            headers=auth_headers,
        ).json()["rows"]
    }[ids["occupe"]]
    assert ligne["etat"] == "partiel"
    assert ligne["montant_paye"] == 300.0
    assert ligne["solde_total"] == 500.0

    # 4. La sous-page de l'immeuble raconte la même chose.
    sous_page = client.get(
        f"/api/v1/immobilier/immeubles/{ids['immeuble']}"
        f"/paiements-externes?mois={mois}",
        headers=auth_headers,
    ).json()
    par_log = {x["logement_id"]: x for x in sous_page["rows"]}
    assert par_log[ids["occupe"]]["etat"] == "partiel"
    assert par_log[ids["occupe"]]["solde_total"] == 500.0
    assert par_log[ids["vacant"]]["etat"] == "aucun"


def test_echeances_suivent_la_fenetre_reglable(client, auth_headers, run):
    """La fenêtre d'avis du bandeau Paiements suit le réglage « Suivis
    annuels » — avant, 183 jours en dur contredisaient la page
    Renouvellements."""
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
                name="Immeuble Fenêtre",
                address="12 rue Fenêtre",
                is_active=True,
            )
            s.add(imm)
            await s.flush()
            lg = Logement(
                immeuble_id=imm.id,
                numero="F-1",
                status=LogementStatus.OCCUPE.value,
            )
            loc = Locataire(full_name="Fenêtre Smoke")
            s.add_all([lg, loc])
            await s.flush()
            # Fin dans ~7 mois : hors fenêtre à 6 mois, dedans à 9 mois.
            b = Bail(
                logement_id=lg.id,
                locataire_id=loc.id,
                date_debut=date.today() - timedelta(days=150),
                date_fin=date.today() + timedelta(days=215),
                loyer_mensuel=1000.0,
                status=BailStatus.ACTIF.value,
            )
            s.add(b)
            await s.commit()
            return b.id

    bail_id = run(_seed())

    def _statut() -> str | None:
        rows = client.get(
            "/api/v1/immobilier/baux/echeances", headers=auth_headers
        ).json()["rows"]
        for r in rows:
            if r["bail_id"] == bail_id:
                return r["statut"]
        return None

    def _config(mois_avant: int) -> None:
        client.put(
            "/api/v1/immobilier/suivis-config",
            headers=auth_headers,
            json={
                "renouvellement_mois_avant": mois_avant,
                "assurance_bascule_mois": 1,
                "releve31_bascule_mois": 2,
            },
        )

    try:
        _config(6)  # ouverture à 180 j → 215 j restants = pas encore
        assert _statut() in (None, "a_venir")
        _config(9)  # ouverture à 270 j → la fenêtre est ouverte
        assert _statut() == "a_envoyer"
    finally:
        _config(6)
