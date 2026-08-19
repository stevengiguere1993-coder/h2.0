"""Smoke — cycle de vie du logement (retours Phil 2026-08-19).

Trois choses que Phil a relevées en testant :

1. un logement restait « réservé » alors que le candidat avait été
   retiré — le statut est DÉRIVÉ des baux mais STOCKÉ, donc il se périme
   dès qu'une transition oublie de le recalculer ;
2. « occupé » ne disait pas qu'un départ était acté pour le 31 août —
   or ce n'est pas le même état, c'est celui-là qu'il faut relouer ;
3. après la date de départ, le locataire ne doit plus être rattaché aux
   loyers du logement.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

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


def test_statut_perime_est_recale_au_demarrage(run, db_setup):
    """Un bail PROPOSÉ dont la date de début est PASSÉE ne réserve plus
    rien : le logement doit redevenir vacant. C'est exactement l'état
    trouvé en prod (bail proposé de 2024 sur un logement « réservé »).
    """
    from app.services.locatif_depart import (
        recaler_tous_les_statuts_logements,
    )

    async def _seed() -> int:
        async with TestSessionLocal() as s:
            imm = Immeuble(
                name="Immeuble Statut Perime", address="20 rue Statut",
                city="Montréal", is_active=True,
            )
            s.add(imm)
            await s.flush()
            lg = Logement(
                immeuble_id=imm.id, numero="1",
                # Statut PÉRIMÉ, posé à la main comme en prod.
                status=LogementStatus.RESERVE.value,
            )
            loc = Locataire(full_name="Candidat Retire")
            s.add_all([lg, loc])
            await s.flush()
            s.add(
                Bail(
                    logement_id=lg.id, locataire_id=loc.id,
                    date_debut=date.today() - timedelta(days=400),
                    date_fin=date.today() - timedelta(days=35),
                    loyer_mensuel=900.0,
                    status=BailStatus.PROPOSE.value,
                )
            )
            await s.commit()
            return lg.id

    lg_id = run(_seed())

    async def _recaler() -> str:
        async with TestSessionLocal() as s:
            await recaler_tous_les_statuts_logements(s)
        async with TestSessionLocal() as s:
            lg = await s.get(Logement, lg_id)
            return lg.status

    assert run(_recaler()) == LogementStatus.VACANT.value


def test_libere_le_ne_repose_que_sur_un_depart_acte(run, db_setup):
    """⚠️ Une fin de bail n'est PAS un départ : au Québec le bail se
    reconduit tacitement. Seul un dossier de relocation ouvert libère le
    logement — sinon Kratos annoncerait des vacances imaginaires pour
    tous les baux qui arrivent à échéance.
    """
    from app.services.locatif_depart import libere_le

    async def _seed() -> dict:
        async with TestSessionLocal() as s:
            imm = Immeuble(
                name="Immeuble Libere Le", address="22 rue Depart",
                city="Montréal", is_active=True,
            )
            s.add(imm)
            await s.flush()
            ids = {}
            for numero, avec_dossier in (("1", False), ("2", True)):
                lg = Logement(
                    immeuble_id=imm.id, numero=numero,
                    status=LogementStatus.OCCUPE.value,
                )
                loc = Locataire(full_name=f"Locataire {numero}")
                s.add_all([lg, loc])
                await s.flush()
                b = Bail(
                    logement_id=lg.id, locataire_id=loc.id,
                    date_debut=date.today() - timedelta(days=300),
                    date_fin=date(2026, 8, 31),
                    loyer_mensuel=1000.0,
                    status=BailStatus.ACTIF.value,
                )
                s.add(b)
                await s.flush()
                if avec_dossier:
                    s.add(
                        LocationDossier(
                            logement_id=lg.id, bail_id=b.id,
                            statut=LocationDossierStatut.AVIS_RECU.value,
                            date_depart=date(2026, 8, 31),
                        )
                    )
                ids[numero] = lg.id
            await s.commit()
            return ids

    ids = run(_seed())

    async def _lire() -> tuple:
        async with TestSessionLocal() as s:
            return (
                await libere_le(s, ids["1"]),
                await libere_le(s, ids["2"]),
            )

    sans_dossier, avec_dossier = run(_lire())
    assert sans_dossier is None, (
        "un bail qui arrive à échéance n'annonce PAS une vacance"
    )
    assert avec_dossier == date(2026, 8, 31)


@pytest.mark.parametrize("solde_du", [False, True])
def test_locataire_parti_disparait_des_loyers(
    client, auth_headers, run, solde_du
):
    """Après la date de départ, le locataire n'est plus rattaché aux
    loyers du logement (retour Phil) — SAUF s'il doit encore de
    l'argent : effacer une dette parce que le bail est fini serait pire
    que le laisser apparaître.
    """
    fin = date.today().replace(day=1) - timedelta(days=1)  # fin du mois passé

    async def _seed() -> dict:
        async with TestSessionLocal() as s:
            imm = Immeuble(
                name=f"Immeuble Parti {solde_du}", address="24 rue Parti",
                city="Montréal", is_active=True,
            )
            s.add(imm)
            await s.flush()
            lg = Logement(
                immeuble_id=imm.id, numero="1",
                status=LogementStatus.VACANT.value,
            )
            loc = Locataire(full_name="Ancien Locataire")
            s.add_all([lg, loc])
            await s.flush()
            b = Bail(
                logement_id=lg.id, locataire_id=loc.id,
                date_debut=fin - timedelta(days=364),
                date_fin=fin,
                loyer_mensuel=1000.0,
                status=BailStatus.TERMINE.value,
            )
            s.add(b)
            await s.flush()
            if not solde_du:
                from datetime import datetime, timezone

                from app.models.immobilier import PaiementLoyer

                mois = fin.replace(day=1)
                s.add(
                    PaiementLoyer(
                        bail_id=b.id, mois_couvert=mois, montant=1000.0,
                        paye_le=mois,
                        created_at=datetime.now(timezone.utc),
                    )
                )
            await s.commit()
            return {"immeuble_id": imm.id, "bail_id": b.id}

    ids = run(_seed())
    mois_courant = date.today().strftime("%Y-%m")
    r = client.get(
        f"/api/v1/immobilier/loyers/overview?mois={mois_courant}"
        f"&immeuble_id={ids['immeuble_id']}",
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    presents = [x["bail_id"] for x in r.json()["rows"]]
    if solde_du:
        assert ids["bail_id"] in presents, (
            "une dette doit rester visible même après le départ"
        )
    else:
        assert ids["bail_id"] not in presents, (
            "un locataire parti et à jour ne doit plus apparaître"
        )


def test_annuler_depart_refuse_si_candidat_retenu(client, auth_headers, run):
    """Le geste inverse de « mettre fin au bail ». Il doit être REFUSÉ
    dès qu'un candidat est retenu : annuler mettrait deux locataires sur
    la même unité. Le refus dit quoi faire plutôt que de se contenter de
    bloquer.
    """
    async def _seed(statut: str) -> dict:
        async with TestSessionLocal() as s:
            imm = Immeuble(
                name=f"Immeuble Annul {statut}", address="26 rue Annul",
                city="Montréal", is_active=True,
            )
            s.add(imm)
            await s.flush()
            lg = Logement(
                immeuble_id=imm.id, numero="1",
                status=LogementStatus.OCCUPE.value,
            )
            loc = Locataire(full_name="Locataire Hesitant")
            s.add_all([lg, loc])
            await s.flush()
            b = Bail(
                logement_id=lg.id, locataire_id=loc.id,
                date_debut=date.today() - timedelta(days=200),
                date_fin=date.today() + timedelta(days=100),
                loyer_mensuel=1000.0,
                status=BailStatus.RESILIE.value,
            )
            s.add(b)
            await s.flush()
            s.add(
                LocationDossier(
                    logement_id=lg.id, bail_id=b.id, statut=statut,
                    date_depart=date.today() + timedelta(days=20),
                )
            )
            await s.commit()
            return {"bail_id": b.id, "logement_id": lg.id}

    # (a) Candidat retenu → refus explicite.
    engage = run(_seed(LocationDossierStatut.CANDIDAT_RETENU.value))
    r = client.post(
        f"/api/v1/immobilier/baux/{engage['bail_id']}/annuler-depart",
        headers=auth_headers,
    )
    assert r.status_code == 409, r.text
    assert "candidat" in r.text.lower()

    # (b) Départ simplement annoncé → l'annulation passe, le bail
    # redevient actif et le logement occupé.
    libre = run(_seed(LocationDossierStatut.AVIS_RECU.value))
    r2 = client.post(
        f"/api/v1/immobilier/baux/{libre['bail_id']}/annuler-depart",
        headers=auth_headers,
    )
    assert r2.status_code == 200, r2.text
    data = r2.json()
    assert data["bail_reactive"] is True
    assert data["logement_statut"] == LogementStatus.OCCUPE.value

    # Et le logement ne se dit plus « libre le … ».
    from app.services.locatif_depart import libere_le

    async def _lire():
        async with TestSessionLocal() as s:
            return await libere_le(s, libre["logement_id"])

    assert run(_lire()) is None


def test_annuler_depart_sans_depart_en_cours(client, auth_headers, run):
    """Sur un bail sans départ acté, l'annulation n'a aucun sens — 409
    plutôt qu'un succès silencieux qui ne ferait rien."""
    async def _seed() -> int:
        async with TestSessionLocal() as s:
            imm = Immeuble(
                name="Immeuble Sans Depart", address="28 rue Calme",
                city="Montréal", is_active=True,
            )
            s.add(imm)
            await s.flush()
            lg = Logement(
                immeuble_id=imm.id, numero="1",
                status=LogementStatus.OCCUPE.value,
            )
            loc = Locataire(full_name="Locataire Tranquille")
            s.add_all([lg, loc])
            await s.flush()
            b = Bail(
                logement_id=lg.id, locataire_id=loc.id,
                date_debut=date.today() - timedelta(days=100),
                date_fin=date.today() + timedelta(days=200),
                loyer_mensuel=1000.0, status=BailStatus.ACTIF.value,
            )
            s.add(b)
            await s.flush()
            await s.commit()
            return b.id

    bail_id = run(_seed())
    r = client.post(
        f"/api/v1/immobilier/baux/{bail_id}/annuler-depart",
        headers=auth_headers,
    )
    assert r.status_code == 409, r.text
