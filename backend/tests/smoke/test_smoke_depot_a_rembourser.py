"""Smoke — alerte de remboursement du dépôt de garantie.

Demande de Phil (2026-08-19) : « mon employé vient les mettre lorsque
c'est loué, mais il oublie tout le temps de venir l'enlever à la fin…
à la minute où il est sorti, ça met une alerte comme dans Paiements ».

Deux décisions qu'il a lui-même tranchées et que ces tests protègent :

- **pas de verrou** à la relocation (« ça peut être un petit peu
  gossant ») — l'oubli se rattrape par une alerte, pas par une porte
  fermée ;
- **tous les logements n'ont pas de dépôt** — sans dépôt, aucune ligne.

Et une nuance à laquelle Phil tenait dès juillet : la fin d'un bail
n'est PAS un départ (reconduction tacite). Un dépôt n'est dû que quand
le locataire est vraiment parti.
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


def _seed(nom: str, *, depot, statut_bail, dossier_statut, depart):
    async def _s() -> dict:
        async with TestSessionLocal() as s:
            imm = Immeuble(
                name=nom, address="70 rue Depot", city="Montréal",
                is_active=True,
            )
            s.add(imm)
            await s.flush()
            lg = Logement(
                immeuble_id=imm.id, numero="1",
                status=LogementStatus.VACANT.value,
            )
            lo = Locataire(full_name=f"Parti {nom}")
            s.add_all([lg, lo])
            await s.flush()
            b = Bail(
                logement_id=lg.id, locataire_id=lo.id,
                date_debut=date.today() - timedelta(days=400),
                date_fin=date.today() - timedelta(days=10),
                loyer_mensuel=1000.0, status=statut_bail,
                depot_garantie=depot,
            )
            s.add(b)
            await s.flush()
            if dossier_statut is not None:
                s.add(
                    LocationDossier(
                        logement_id=lg.id, bail_id=b.id,
                        statut=dossier_statut, date_depart=depart,
                    )
                )
            await s.commit()
            return {"immeuble_id": imm.id, "bail_id": b.id}

    return _s


def _statut(client, auth_headers, ids) -> str | None:
    r = client.get(
        f"/api/v1/immobilier/depots/overview?immeuble_id={ids['immeuble_id']}",
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    ligne = next(
        (x for x in r.json()["rows"] if x["bail_id"] == ids["bail_id"]), None
    )
    return ligne["statut"] if ligne else None


def test_depart_acte_et_passe_rend_le_depot_du(client, auth_headers, run):
    """Le cas que Phil voulait attraper : le locataire est parti, le
    logement n'est pas encore reloué, et le dépôt dort chez nous.

    Avant, l'alerte attendait la RELOCATION — donc des semaines pendant
    lesquelles l'argent du locataire restait chez nous sans que rien ne
    le signale.
    """
    ids = run(_seed(
        "Depot Parti", depot=250.0,
        statut_bail=BailStatus.TERMINE.value,
        dossier_statut=LocationDossierStatut.ANNONCE_PUBLIEE.value,
        depart=date.today() - timedelta(days=5),
    )())
    assert _statut(client, auth_headers, ids) == "a_rendre"


def test_depart_a_venir_ne_declenche_rien(client, auth_headers, run):
    """Un départ annoncé pour plus tard ne rend pas le dépôt dû : le
    locataire est encore là."""
    ids = run(_seed(
        "Depot Futur", depot=250.0,
        statut_bail=BailStatus.RESILIE.value,
        dossier_statut=LocationDossierStatut.AVIS_RECU.value,
        depart=date.today() + timedelta(days=20),
    )())
    assert _statut(client, auth_headers, ids) != "a_rendre"


def test_depart_annule_ne_declenche_rien(client, auth_headers, run):
    """Dossier annulé = le locataire est resté. Réclamer son dépôt
    serait une erreur — et l'alerte crierait pour rien."""
    ids = run(_seed(
        "Depot Annule", depot=250.0,
        statut_bail=BailStatus.TERMINE.value,
        dossier_statut=LocationDossierStatut.ANNULE.value,
        depart=date.today() - timedelta(days=5),
    )())
    assert _statut(client, auth_headers, ids) != "a_rendre"


def test_bail_fini_sans_depart_acte_ne_declenche_rien(
    client, auth_headers, run
):
    """⚠️ La nuance de juillet : une fin de bail n'est PAS un départ. Au
    Québec le bail se reconduit tacitement — sans départ acté, le
    locataire est probablement encore là."""
    ids = run(_seed(
        "Depot Echu", depot=250.0,
        statut_bail=BailStatus.TERMINE.value,
        dossier_statut=None, depart=None,
    )())
    assert _statut(client, auth_headers, ids) != "a_rendre"


def test_sans_depot_aucune_ligne_a_rendre(client, auth_headers, run):
    """« Il n'y a pas toutes les unités qui vont avoir besoin d'un dépôt
    de sécurité » (Phil). Sans dépôt, rien à rembourser."""
    ids = run(_seed(
        "Depot Absent", depot=None,
        statut_bail=BailStatus.TERMINE.value,
        dossier_statut=LocationDossierStatut.ANNONCE_PUBLIEE.value,
        depart=date.today() - timedelta(days=5),
    )())
    assert _statut(client, auth_headers, ids) != "a_rendre"
