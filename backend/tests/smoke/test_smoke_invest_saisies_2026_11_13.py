"""Smoke — saisies manuelles d'un investisseur (Steven, 2026-11-13).

« Éric Brabant et Vincent Clark […] ont investi chacun 150 000 $ avant
QB » et « un investisseur peut faire un prêt supplémentaire à la cie :
montant, % remis, calcul des intérêts mensuels ». Les apports hors QB
s'ajoutent au portefeuille et survivent à la synchro QB ; les prêts
calculent leur intérêt simple mensuel.
"""
from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import select

from app.core.security import get_password_hash
from app.models.entreprise import Entreprise, EntreprisePartner
from app.models.invest_portal import InvestFlux, InvestParticipation
from app.models.user import User
from app.services.invest_saisies import (
    interet_mensuel,
    mois_complets,
    net_hors_qbo,
)

from .conftest import TestSessionLocal


def test_calculs_interets():
    assert interet_mensuel(100_000, 6) == 500.0
    assert mois_complets(date(2026, 1, 15), date(2026, 3, 14)) == 1
    assert mois_complets(date(2026, 1, 15), date(2026, 3, 15)) == 2
    assert mois_complets(date(2026, 3, 1), date(2026, 1, 1)) == 0


@pytest.fixture(scope="module")
def ids(run, db_setup) -> dict:
    async def _seed() -> dict:
        async with TestSessionLocal() as s:
            ent = Entreprise(name="INC Saisies Manuelles")
            s.add(ent)
            await s.flush()
            inv = User(
                email="saisies.investisseur@example.com",
                hashed_password=get_password_hash("x"),
                is_active=True,
                is_admin=False,
                role="investisseur",
                first_name="Saisie",
                last_name="Manuelle",
            )
            s.add(inv)
            await s.flush()
            s.add(
                EntreprisePartner(
                    entreprise_id=ent.id,
                    user_id=inv.id,
                    partner_name="Saisie Manuelle",
                    ownership_pct=30,
                )
            )
            await s.commit()
            return {"ent": ent.id, "inv": inv.id}

    return run(_seed())


def test_apport_hors_qbo_et_pret(client, auth_headers, ids, run):
    base = f"/api/v1/invest/admin/investisseurs/{ids['inv']}"
    # Aucune participation persistée au départ : la saisie la crée.
    r = client.post(
        f"{base}/projets/{ids['ent']}/apports-hors-qbo",
        json={
            "montant": 150000,
            "date_flux": "2019-06-01",
            "note": "Mise de fonds avant QuickBooks",
        },
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    projet = next(
        p for p in r.json()["projets"] if p["entreprise_id"] == ids["ent"]
    )
    assert projet["net_hors_qbo"] == 150000
    assert projet["capital_investi_total"] == 150000
    assert len(projet["apports_hors_qbo"]) == 1
    flux_id = projet["apports_hors_qbo"][0]["id"]

    # Modification.
    r = client.patch(
        f"{base}/apports-hors-qbo/{flux_id}",
        json={"type": "apport", "montant": 150000, "date_flux": "2019-07-01"},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text

    # La synchro QB ne purge QUE les flux « qbo ».
    async def _sources() -> list[str]:
        async with TestSessionLocal() as s:
            part = (
                await s.execute(
                    select(InvestParticipation).where(
                        InvestParticipation.user_id == ids["inv"]
                    )
                )
            ).scalar_one()
            s.add(
                InvestFlux(
                    participation_id=part.id,
                    type="apport",
                    montant=1000,
                    date_flux=date(2025, 1, 1),
                    source="qbo",
                )
            )
            await s.commit()
            flux = (
                await s.execute(
                    select(InvestFlux).where(
                        InvestFlux.participation_id == part.id
                    )
                )
            ).scalars().all()
            assert net_hors_qbo(flux) == 150000
            return sorted(f.source for f in flux)

    assert run(_sources()) == ["hors_qbo", "qbo"]

    # Prêt : 50 000 $ à 8 % → 333,33 $/mois.
    r = client.post(
        f"{base}/projets/{ids['ent']}/prets",
        json={"montant": 50000, "taux_annuel_pct": 8, "date_pret": "2026-01-01"},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    projet = next(
        p for p in r.json()["projets"] if p["entreprise_id"] == ids["ent"]
    )
    assert projet["prets_en_cours"] == 50000
    assert projet["interets_mensuels"] == 333.33
    pret_id = projet["prets"][0]["id"]

    # Remboursement daté avant le prêt → 422.
    r = client.patch(
        f"{base}/prets/{pret_id}",
        json={"date_remboursement": "2025-01-01"},
        headers=auth_headers,
    )
    assert r.status_code == 422, r.text

    # Le portail de l'investisseur voit l'apport et le prêt.
    r = client.get(
        f"/api/v1/invest/admin/apercu/{ids['inv']}/portefeuille",
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    pf = r.json()
    assert pf["capital_investi_total"] == 151000
    assert pf["prets_en_cours"] == 50000

    r = client.delete(f"{base}/prets/{pret_id}", headers=auth_headers)
    assert r.status_code == 200, r.text
    r = client.delete(f"{base}/apports-hors-qbo/{flux_id}", headers=auth_headers)
    assert r.status_code == 200, r.text
