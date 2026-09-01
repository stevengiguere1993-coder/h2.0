"""Smoke — retours Phil 2026-08-31 sur la page Paiements :

1. Les logements VACANTS apparaissent dans loyers/overview (etat
   « vacant », bail_id 0, loyer demandé indicatif, hors totaux).
2. « + Frais » devient frais/crédit : un montant NÉGATIF réduit le
   solde dû ; un montant nul est refusé.
3. Coche « dossier TAL ouvert » sur un bail (PATCH), reflétée dans
   l'overview pour que l'équipe voie le recours sans se relancer.
"""
from __future__ import annotations

from datetime import date

from app.models.immobilier import (
    Bail,
    BailStatus,
    Immeuble,
    Locataire,
    Logement,
    LogementStatus,
)

from .conftest import TestSessionLocal

MOIS = "2026-09"


def _seed(run) -> dict:
    async def _go() -> dict:
        async with TestSessionLocal() as s:
            imm = Immeuble(
                name="Immeuble Vacance",
                address="1 rue des Vacants",
                is_active=True,
            )
            s.add(imm)
            await s.flush()
            occupe = Logement(
                immeuble_id=imm.id,
                numero="101",
                status=LogementStatus.OCCUPE.value,
            )
            vacant = Logement(
                immeuble_id=imm.id,
                numero="102",
                status=LogementStatus.VACANT.value,
                loyer_demande=1234.0,
            )
            horsloc = Logement(
                immeuble_id=imm.id,
                numero="103",
                status=LogementStatus.HORS_LOC.value,
            )
            s.add_all([occupe, vacant, horsloc])
            await s.flush()
            loc = Locataire(full_name="Locataire Vacance")
            s.add(loc)
            await s.flush()
            bail = Bail(
                logement_id=occupe.id,
                locataire_id=loc.id,
                date_debut=date(2026, 8, 1),
                date_fin=date(2027, 6, 30),
                loyer_mensuel=900.0,
                status=BailStatus.ACTIF.value,
            )
            s.add(bail)
            await s.flush()
            out = {
                "immeuble_id": imm.id,
                "vacant_id": vacant.id,
                "horsloc_id": horsloc.id,
                "bail_id": bail.id,
            }
            await s.commit()
            return out

    return run(_go())


def _overview(client, auth_headers, immeuble_id):
    r = client.get(
        f"/api/v1/immobilier/loyers/overview?mois={MOIS}",
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    data = r.json()
    data["rows"] = [
        x for x in data["rows"] if x["immeuble_id"] == immeuble_id
    ]
    return data


def test_vacants_credits_et_tal(client, auth_headers, run):
    ids = _seed(run)

    ov = _overview(client, auth_headers, ids["immeuble_id"])

    # 1) Le logement vacant remonte, le hors-location non.
    vac = [x for x in ov["rows"] if x["etat"] == "vacant"]
    assert [v["logement_id"] for v in vac] == [ids["vacant_id"]]
    v = vac[0]
    assert v["bail_id"] == 0
    assert v["loyer_mensuel"] == 1234.0
    assert v["logement_statut"] == "vacant"
    assert ov["nb_vacants"] >= 1
    # Le loyer demandé du vacant n'entre pas dans l'attendu.
    assert all(
        x["logement_id"] != ids["horsloc_id"] for x in ov["rows"]
    )

    solde_avant = next(
        x for x in ov["rows"] if x["bail_id"] == ids["bail_id"]
    )["solde_total"]

    # 2) Crédit (montant négatif) → accepté, réduit le solde de 100 $.
    r = client.post(
        f"/api/v1/immobilier/baux/{ids['bail_id']}/frais",
        headers=auth_headers,
        json={
            "mois_couvert": f"{MOIS}-01",
            "montant": -100,
            "libelle": "Crédit réno",
        },
    )
    assert r.status_code == 201, r.text
    assert r.json()["montant"] == -100

    ov2 = _overview(client, auth_headers, ids["immeuble_id"])
    ligne = next(
        x for x in ov2["rows"] if x["bail_id"] == ids["bail_id"]
    )
    assert abs((solde_avant - ligne["solde_total"]) - 100) < 0.01
    assert any(f["montant"] == -100 for f in ligne["frais_mois"])

    # Montant nul → refusé.
    r0 = client.post(
        f"/api/v1/immobilier/baux/{ids['bail_id']}/frais",
        headers=auth_headers,
        json={"mois_couvert": f"{MOIS}-01", "montant": 0},
    )
    assert r0.status_code == 422

    # 3) Dossier TAL : coche via PATCH bail, reflétée dans l'overview,
    # puis retirable (null explicite).
    r = client.patch(
        f"/api/v1/immobilier/baux/{ids['bail_id']}",
        headers=auth_headers,
        json={"tal_dossier_ouvert_le": "2026-09-01"},
    )
    assert r.status_code == 200, r.text
    ov3 = _overview(client, auth_headers, ids["immeuble_id"])
    ligne3 = next(
        x for x in ov3["rows"] if x["bail_id"] == ids["bail_id"]
    )
    assert ligne3["tal_dossier_ouvert_le"] == "2026-09-01"

    r = client.patch(
        f"/api/v1/immobilier/baux/{ids['bail_id']}",
        headers=auth_headers,
        json={"tal_dossier_ouvert_le": None},
    )
    assert r.status_code == 200, r.text
    ov4 = _overview(client, auth_headers, ids["immeuble_id"])
    ligne4 = next(
        x for x in ov4["rows"] if x["bail_id"] == ids["bail_id"]
    )
    assert ligne4["tal_dossier_ouvert_le"] is None
