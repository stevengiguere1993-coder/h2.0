"""Smoke — tuile « Revenu ce mois » du tableau de bord (Steven, 2026-11-10 :
« une facture peut avoir reçu des paiements différés et se retrouver en
revenu sur plusieurs mois »).

Le revenu d'un mois = paiements reçus dans ce mois (date du paiement),
pas le total des factures marquées payées. Données en 2033 (aucun autre
test n'y écrit), retirées à la fin.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from sqlalchemy import delete

from app.api.v1.endpoints.dashboard import paiements_recus_du_mois
from app.models.client import Client
from app.models.facture import Facture
from app.models.payment import Payment

from tests.smoke.conftest import TestSessionLocal


@pytest.fixture(scope="module")
def donnees(run, db_setup):
    ids: dict = {}

    async def _seed() -> None:
        async with TestSessionLocal() as s:
            client = Client(name="Client revenu du mois 2033")
            s.add(client)
            await s.flush()
            # Payée en décembre, mais réglée par versements sur trois mois.
            f1 = Facture(
                reference="REV-2033-1", client_id=client.id, subtotal=21192,
                total=24365.50, status="paid",
                paid_at=datetime(2033, 12, 5, tzinfo=timezone.utc),
            )
            # Encore ouverte : son versement partiel compte quand même.
            f2 = Facture(
                reference="REV-2033-2", client_id=client.id, subtotal=10000,
                total=11497.50, status="sent",
            )
            s.add_all([f1, f2])
            await s.flush()
            paiements = [
                Payment(facture_id=f1.id, amount=3000, paid_at=date(2033, 10, 5)),
                Payment(facture_id=f1.id, amount=5000, paid_at=date(2033, 10, 31)),
                Payment(facture_id=f1.id, amount=15000, paid_at=date(2033, 11, 1)),
                Payment(facture_id=f1.id, amount=1365.50, paid_at=date(2033, 12, 5)),
                Payment(facture_id=f2.id, amount=2000, paid_at=date(2033, 12, 31)),
            ]
            s.add_all(paiements)
            await s.commit()
            ids.update(client=client.id, factures=[f1.id, f2.id])

    async def _clean() -> None:
        async with TestSessionLocal() as s:
            await s.execute(delete(Payment).where(Payment.facture_id.in_(ids["factures"])))
            await s.execute(delete(Facture).where(Facture.id.in_(ids["factures"])))
            await s.execute(delete(Client).where(Client.id == ids["client"]))
            await s.commit()

    run(_seed())
    yield ids
    run(_clean())


def _revenu(run, jour: date) -> float:
    async def _go() -> float:
        async with TestSessionLocal() as s:
            return await paiements_recus_du_mois(s, jour)

    return run(_go())


def test_chaque_versement_compte_dans_son_mois(run, donnees):
    assert _revenu(run, date(2033, 10, 15)) == pytest.approx(8000)
    assert _revenu(run, date(2033, 11, 30)) == pytest.approx(15000)
    # Décembre : le dernier versement, PAS les 24 365,50 $ de la facture
    # passée à « payée » ce mois-là ; plus le partiel d'une facture ouverte.
    assert _revenu(run, date(2033, 12, 1)) == pytest.approx(3365.50)


def test_mois_sans_paiement(run, donnees):
    assert _revenu(run, date(2033, 9, 10)) == 0
    assert _revenu(run, date(2034, 1, 1)) == 0
