"""Smoke — « Louer indéfiniment (chambre) » (retour Phil 2026-08-13).

Le flag ``Logement.location_en_chambres`` (libellé UI « Louer
indéfiniment (chambre) ») pilote désormais le BAIL :
  - un bail créé sur un logement flaggé naît AU MOIS ;
  - un bail au mois n'apparaît jamais dans /baux/echeances ni dans le
    suivi des renouvellements ;
  - cocher le flag sur le logement bascule ses baux en cours au mois.
"""
from __future__ import annotations

from datetime import date, timedelta


def _seed_immeuble(run, numeros: list[str], en_chambres: bool) -> dict:
    """Crée un immeuble + N logements et rend {numero: logement_id}."""
    from app.models.immobilier import (
        Immeuble,
        Locataire,
        Logement,
        LogementStatus,
    )

    from .conftest import TestSessionLocal

    async def _go():
        async with TestSessionLocal() as s:
            imm = Immeuble(
                name="Maison Indefinie",
                address="7 rue Perpetuelle",
                is_active=True,
            )
            s.add(imm)
            await s.flush()
            ids = {}
            for num in numeros:
                lg = Logement(
                    immeuble_id=imm.id,
                    numero=num,
                    status=LogementStatus.VACANT.value,
                    location_en_chambres=en_chambres,
                )
                s.add(lg)
                await s.flush()
                ids[num] = lg.id
            loc = Locataire(full_name=f"Locataire {numeros[0]}")
            s.add(loc)
            await s.flush()
            ids["_locataire"] = loc.id
            ids["_immeuble"] = imm.id
            await s.commit()
            return ids

    return run(_go())


def _au_mois_en_base(run, bail_id: int):
    from app.models.immobilier import Bail

    from .conftest import TestSessionLocal

    async def _go():
        async with TestSessionLocal() as s:
            return (await s.get(Bail, bail_id)).au_mois

    return run(_go())


def test_bail_cree_sur_logement_indefini_est_au_mois(
    client, auth_headers, run
):
    """Logement flaggé → le bail créé dessus est AU MOIS, même si l'appel
    ne le demande pas (la source de vérité est le logement)."""
    ids = _seed_immeuble(run, ["IND-1"], en_chambres=True)

    r = client.post(
        "/api/v1/immobilier/baux",
        headers=auth_headers,
        json={
            "logement_id": ids["IND-1"],
            "locataire_id": ids["_locataire"],
            "date_debut": str(date.today() - timedelta(days=30)),
            "date_fin": str(date.today() + timedelta(days=120)),
            "loyer_mensuel": 620.0,
            "status": "actif",
        },
    )
    assert r.status_code in (200, 201), r.text
    bail = r.json()
    assert bail["au_mois"] is True
    assert _au_mois_en_base(run, bail["id"]) is True


def test_bail_au_mois_absent_des_echeances(client, auth_headers, run):
    """Deux baux dans la MÊME fenêtre d'avis : celui du logement
    « louer indéfiniment » est absent, l'annuel est présent."""
    ind = _seed_immeuble(run, ["IND-2"], en_chambres=True)
    ann = _seed_immeuble(run, ["ANN-2"], en_chambres=False)

    fin = str(date.today() + timedelta(days=120))  # fenêtre ouverte
    baux = {}
    for tag, seed, numero in (
        ("indefini", ind, "IND-2"),
        ("annuel", ann, "ANN-2"),
    ):
        r = client.post(
            "/api/v1/immobilier/baux",
            headers=auth_headers,
            json={
                "logement_id": seed[numero],
                "locataire_id": seed["_locataire"],
                "date_debut": str(date.today() - timedelta(days=245)),
                "date_fin": fin,
                "loyer_mensuel": 700.0,
                "status": "actif",
            },
        )
        assert r.status_code in (200, 201), r.text
        baux[tag] = r.json()["id"]

    ech = client.get(
        "/api/v1/immobilier/baux/echeances", headers=auth_headers
    )
    assert ech.status_code == 200, ech.text
    vus = {row["bail_id"] for row in ech.json()["rows"]}
    assert baux["indefini"] not in vus
    assert baux["annuel"] in vus

    # Même règle côté hub Renouvellements.
    ren = client.get(
        "/api/v1/immobilier/renouvellements/overview", headers=auth_headers
    )
    assert ren.status_code == 200, ren.text
    vus_ren = {row["bail_id"] for row in ren.json()}
    assert baux["indefini"] not in vus_ren
    assert baux["annuel"] in vus_ren


def test_cocher_le_flag_bascule_les_baux_en_cours(
    client, auth_headers, run
):
    """Le logement devient « louer indéfiniment » APRÈS coup : ses baux
    actif + proposé passent au mois. Décocher ne retouche à rien."""
    seed = _seed_immeuble(run, ["SWAP-1"], en_chambres=False)

    r = client.post(
        "/api/v1/immobilier/baux",
        headers=auth_headers,
        json={
            "logement_id": seed["SWAP-1"],
            "locataire_id": seed["_locataire"],
            "date_debut": str(date.today() - timedelta(days=60)),
            "date_fin": str(date.today() + timedelta(days=120)),
            "loyer_mensuel": 800.0,
            "status": "actif",
        },
    )
    assert r.status_code in (200, 201), r.text
    bail_id = r.json()["id"]
    assert not r.json()["au_mois"]

    p = client.patch(
        f"/api/v1/immobilier/logements/{seed['SWAP-1']}",
        headers=auth_headers,
        json={"location_en_chambres": True},
    )
    assert p.status_code == 200, p.text
    assert p.json()["location_en_chambres"] is True
    assert _au_mois_en_base(run, bail_id) is True

    # Décocher : le bail garde son « au mois » (le gestionnaire décide).
    p2 = client.patch(
        f"/api/v1/immobilier/logements/{seed['SWAP-1']}",
        headers=auth_headers,
        json={"location_en_chambres": False},
    )
    assert p2.status_code == 200, p2.text
    assert _au_mois_en_base(run, bail_id) is True


def test_suivi_baux_expose_le_flag(client, auth_headers, run):
    """La page Baux reçoit le flag du logement (elle s'en sert pour le
    modal de création)."""
    seed = _seed_immeuble(run, ["SUIVI-1"], en_chambres=True)
    r = client.get("/api/v1/immobilier/suivi-baux", headers=auth_headers)
    assert r.status_code == 200, r.text
    par_log = {row["logement_id"]: row for row in r.json()}
    assert par_log[seed["SUIVI-1"]]["logement_en_chambres"] is True
