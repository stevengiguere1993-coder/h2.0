"""Override de fiche sur les intérêts de portage (Phil 2026-10-12, 1660
Saint-Clément) : la composition affichait l'override (130 030 $) mais le
moteur recalculait toujours la formule → MDF du moteur ≠ composition
(« recalcul requis » sans issue). Un override ou un masquage de
« interets » / « interets_balance_vente » doit être respecté."""
from __future__ import annotations

from app.services.lead_analysis_finance import compute_all
from tests.services.test_lead_analysis_trace import _inputs


def test_override_interets_respecte():
    sans = compute_all(_inputs())
    formule = sans.frais_demarrage.interets
    assert formule > 130_030.0
    avec = compute_all(_inputs(frais_demarrage_overrides={"interets": 130_030.0}))
    assert avec.frais_demarrage.interets == 130_030.0
    # Les intérêts sont 100 % cash : la MDF baisse exactement de l'écart.
    assert abs((sans.mdf_preteur_b - avec.mdf_preteur_b) - (formule - 130_030.0)) < 0.05
    # La composition (cash) et le moteur disent la même chose.
    assert abs(avec.cout_projet["cash_total"] - round(avec.mdf_preteur_b, 2)) < 0.05


def test_masquage_interets_respecte():
    res = compute_all(_inputs(frais_masques=["interets"]))
    assert res.frais_demarrage.interets == 0.0


def test_override_interets_balance_vente_respecte():
    res = compute_all(
        _inputs(
            balance_vente_montant=100_000.0,
            balance_vente_taux_pct=0.06,
            frais_demarrage_overrides={"interets_balance_vente": 5_000.0},
        )
    )
    assert res.frais_demarrage.interets_balance_vente == 5_000.0
