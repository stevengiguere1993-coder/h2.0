"""Échéance d'un achat importé de QB = DueDate du Bill (retour Steven
2026-10-17 : factures Rona à payer affichées sans échéance)."""

from datetime import datetime, timezone

from app.services.qbo_cost_pull import _echeance_bill


def test_echeance_reprend_due_date_qb():
    due = _echeance_bill({"TxnDate": "2026-10-01", "DueDate": "2026-11-15"})
    assert due == datetime(2026, 11, 15, 12, 0, tzinfo=timezone.utc)


def test_echeance_sans_due_date_facture_plus_30_jours():
    due = _echeance_bill({"TxnDate": "2026-10-01"})
    assert due == datetime(2026, 10, 31, 12, 0, tzinfo=timezone.utc)


def test_echeance_sans_aucune_date():
    assert _echeance_bill({}) is None
