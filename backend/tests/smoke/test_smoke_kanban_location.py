"""Smoke — kanban Locations (retours Phil 2026-08-19).

« J'ai un candidat retenu sur une relocation et je peux quand même pas
le mettre dans bail envoyé » — et « des fois ça enlève des candidats
retenus ».

Une seule cause : reculer une carte sur « Candidat retenu » détachait le
bail créé à la conversion, alors que le bail, lui, survivait. Le dossier
se retrouvait avec un candidat retenu, un bail orphelin, et un garde-fou
qui répondait « convertis le candidat d'abord ». Impasse.

Constaté en prod : dossier 24 en « candidat retenu », nouveau_bail_id
vide, et un bail proposé orphelin sur le même logement.
"""
from __future__ import annotations

from datetime import date, timedelta

from app.models.immobilier import (
    Bail,
    BailStatus,
    Immeuble,
    Locataire,
    LocationDossier,
    LocationDossierStatut,
    Logement,
    LogementStatus,
)

from .conftest import TestSessionLocal


def _seeder(nom: str, statut: str, lier: bool):
    async def _seed() -> dict:
        async with TestSessionLocal() as s:
            imm = Immeuble(
                name=nom, address="40 rue Kanban", city="Montréal",
                is_active=True,
            )
            s.add(imm)
            await s.flush()
            lg = Logement(
                immeuble_id=imm.id, numero="1",
                status=LogementStatus.VACANT.value,
            )
            loc = Locataire(full_name="Candidat Retenu")
            s.add_all([lg, loc])
            await s.flush()
            b = Bail(
                logement_id=lg.id, locataire_id=loc.id,
                date_debut=date.today() + timedelta(days=15),
                date_fin=date.today() + timedelta(days=380),
                loyer_mensuel=1200.0,
                status=BailStatus.PROPOSE.value,
            )
            s.add(b)
            await s.flush()
            d = LocationDossier(
                logement_id=lg.id, statut=statut,
                nouveau_bail_id=(b.id if lier else None),
            )
            s.add(d)
            await s.flush()
            await s.commit()
            return {"dossier_id": d.id, "bail_id": b.id, "lg_id": lg.id}

    return _seed


def test_reculer_sur_candidat_retenu_garde_le_bail(
    client, auth_headers, run
):
    """Revenir à « Candidat retenu » ne renie pas le candidat : il est
    toujours retenu, son bail existe toujours. Le lien doit survivre."""
    ids = run(_seeder(
        "Kanban Recul", LocationDossierStatut.BAIL_A_ENVOYER.value, True
    )())
    r = client.patch(
        f"/api/v1/immobilier/locations/{ids['dossier_id']}",
        headers=auth_headers,
        json={"statut": LocationDossierStatut.CANDIDAT_RETENU.value},
    )
    assert r.status_code == 200, r.text
    assert r.json()["nouveau_bail_id"] == ids["bail_id"], (
        "reculer sur « candidat retenu » ne doit PAS détacher le bail"
    )

    # Et on peut repartir vers l'avant — c'est l'impasse d'origine.
    r2 = client.patch(
        f"/api/v1/immobilier/locations/{ids['dossier_id']}",
        headers=auth_headers,
        json={"statut": LocationDossierStatut.BAIL_ENVOYE.value},
    )
    assert r2.status_code == 200, r2.text


def test_bail_orphelin_est_rattache_au_lieu_de_bloquer(
    client, auth_headers, run
):
    """L'état trouvé en prod : candidat retenu, lien perdu, bail proposé
    orphelin. Avancer doit RÉPARER, pas refuser."""
    ids = run(_seeder(
        "Kanban Orphelin",
        LocationDossierStatut.CANDIDAT_RETENU.value,
        False,
    )())
    r = client.patch(
        f"/api/v1/immobilier/locations/{ids['dossier_id']}",
        headers=auth_headers,
        json={"statut": LocationDossierStatut.BAIL_A_ENVOYER.value},
    )
    assert r.status_code == 200, r.text
    assert r.json()["nouveau_bail_id"] == ids["bail_id"]


def test_reculer_avant_le_candidat_detache_bien(client, auth_headers, run):
    """En revanche, revenir AVANT le candidat retenu abandonne le
    candidat : là, le lien doit bien tomber — sinon le dossier garderait
    un lien fantôme."""
    ids = run(_seeder(
        "Kanban Abandon", LocationDossierStatut.BAIL_A_ENVOYER.value, True
    )())
    r = client.patch(
        f"/api/v1/immobilier/locations/{ids['dossier_id']}",
        headers=auth_headers,
        json={"statut": LocationDossierStatut.VISITES.value},
    )
    assert r.status_code == 200, r.text
    assert r.json()["nouveau_bail_id"] is None


def test_un_bail_revendique_par_un_autre_dossier_n_est_pas_vole(
    client, auth_headers, run
):
    """La réparation reste prudente : un bail déjà rattaché à un autre
    dossier ACTIF ne doit jamais être récupéré — deux dossiers
    pointeraient sur le même bail."""
    ids = run(_seeder(
        "Kanban Vol", LocationDossierStatut.CANDIDAT_RETENU.value, False
    )())

    async def _revendiquer() -> int:
        async with TestSessionLocal() as s:
            autre = LocationDossier(
                logement_id=ids["lg_id"],
                statut=LocationDossierStatut.BAIL_ENVOYE.value,
                nouveau_bail_id=ids["bail_id"],
            )
            s.add(autre)
            await s.commit()
            return autre.id

    run(_revendiquer())
    r = client.patch(
        f"/api/v1/immobilier/locations/{ids['dossier_id']}",
        headers=auth_headers,
        json={"statut": LocationDossierStatut.BAIL_A_ENVOYER.value},
    )
    assert r.status_code == 422, r.text
    assert "candidat retenu" in r.text.lower()
