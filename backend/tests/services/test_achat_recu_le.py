"""« Reçu le » d'un achat suit la date de facture (retour 2026-10-16)."""

from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.services.achat_payment import apply_payment_defaults


class _DbSansFournisseur:
    async def execute(self, *_a, **_k):  # pragma: no cover - non appelé
        raise AssertionError("pas de requête attendue")


def _achat(**kw):
    base = dict(
        payment_method="bill_to_pay",
        received_at=None,
        invoice_date=None,
        status="received",
        paid_at=None,
        due_at=None,
        fournisseur_id=None,
    )
    base.update(kw)
    return SimpleNamespace(**base)


@pytest.mark.asyncio
async def test_recu_le_prend_la_date_de_facture():
    a = _achat(invoice_date=date(2026, 8, 13))
    await apply_payment_defaults(_DbSansFournisseur(), a)
    assert a.received_at.date() == date(2026, 8, 13)
    # L'échéance part de la facture (30 j par défaut), comme dans QB.
    assert a.due_at.date() == date(2026, 9, 12)


@pytest.mark.asyncio
async def test_paye_le_suit_la_date_de_facture():
    a = _achat(payment_method="cheque", invoice_date=date(2026, 8, 13))
    await apply_payment_defaults(_DbSansFournisseur(), a)
    assert a.status == "paid"
    assert a.paid_at.date() == date(2026, 8, 13)


@pytest.mark.asyncio
async def test_sans_date_de_facture_reste_aujourdhui():
    a = _achat(payment_method="cheque")
    avant = datetime.now(timezone.utc) - timedelta(seconds=5)
    await apply_payment_defaults(_DbSansFournisseur(), a)
    assert a.received_at >= avant


@pytest.mark.asyncio
async def test_recu_le_explicite_respecte():
    explicite = datetime(2026, 8, 20, 15, tzinfo=timezone.utc)
    a = _achat(
        payment_method="cheque",
        invoice_date=date(2026, 8, 13),
        received_at=explicite,
    )
    await apply_payment_defaults(_DbSansFournisseur(), a)
    assert a.received_at == explicite
