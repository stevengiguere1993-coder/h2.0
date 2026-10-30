"""Reçu divisé entre plusieurs projets (Steven 2026-10-30) : helpers purs.

- répartition au prorata, dernière part absorbe l'arrondi, sommes exactes ;
- ventilation HT / taxes / TPS / TVQ par part à partir des TTC saisis ;
- validations (deux projets distincts, parts > 0, somme = total ± 0,02) ;
- mémo privé QB qui liste les parts ; montants du groupe pour la taxe.
"""

from types import SimpleNamespace

import pytest

from app.services.achat_divise import (
    DivisionErreur,
    montants_groupe,
    repartir,
    valider_parts,
    ventiler_parts,
)
from app.services.achat_qbo import _private_note


def _part(project_id: int, total: float) -> SimpleNamespace:
    return SimpleNamespace(project_id=project_id, total=total)


def test_repartir_somme_exacte_et_dernier_absorbe_l_arrondi():
    assert repartir(100.0, [1, 1, 1]) == [33.33, 33.33, 33.34]
    assert repartir(1000.0, [600, 400]) == [600.0, 400.0]
    assert repartir(0.01, [50, 50]) == [0.01, 0.0]
    assert repartir(10.0, [0, 0]) == [0.0, 10.0]
    assert repartir(10.0, []) == []
    assert round(sum(repartir(149.75, [689.85, 459.9])), 2) == 149.75


def test_ventilation_deux_projets_60_40():
    parts = ventiler_parts(
        amount=1000.0,
        amount_taxes=149.75,
        amount_tps=50.0,
        amount_tvq=99.75,
        totals=[689.85, 459.90],
    )
    assert [p["total"] for p in parts] == [689.85, 459.9]
    assert [p["amount"] for p in parts] == [600.0, 400.0]
    assert [p["amount_taxes"] for p in parts] == [89.85, 59.9]
    assert [p["amount_tps"] for p in parts] == [30.0, 20.0]
    assert [p["amount_tvq"] for p in parts] == [59.85, 39.9]
    # Chaque part retombe sur son TTC ; le groupe sur le reçu.
    for p in parts:
        assert round(p["amount"] + p["amount_taxes"], 2) == p["total"]
    assert round(sum(p["amount"] for p in parts), 2) == 1000.0
    assert round(sum(p["amount_taxes"] for p in parts), 2) == 149.75


def test_ventilation_trois_parts_inegales_sommes_exactes():
    parts = ventiler_parts(
        amount=87.0,
        amount_taxes=13.03,
        amount_tps=4.35,
        amount_tvq=8.68,
        totals=[33.33, 33.33, 33.37],
    )
    assert round(sum(p["amount"] for p in parts), 2) == 87.0
    assert round(sum(p["amount_taxes"] for p in parts), 2) == 13.03
    assert round(sum(p["amount_tps"] for p in parts), 2) == 4.35
    assert round(sum(p["amount_tvq"] for p in parts), 2) == 8.68
    for p in parts:
        assert p["amount"] > 0 and p["amount_taxes"] >= 0


def test_ventilation_ecart_d_arrondi_reporte_sur_la_derniere_part():
    # 1 149,75 $ saisis en 574,88 + 574,86 (1 cent de moins) → accepté,
    # la dernière part passe à 574,87.
    parts = ventiler_parts(
        amount=1000.0, amount_taxes=149.75, amount_tps=None, amount_tvq=None,
        totals=[574.88, 574.86],
    )
    assert [p["total"] for p in parts] == [574.88, 574.87]
    assert parts[0]["amount_tps"] is None and parts[1]["amount_tvq"] is None
    assert round(sum(p["amount"] for p in parts), 2) == 1000.0


def test_ventilation_sans_taxes():
    parts = ventiler_parts(
        amount=200.0, amount_taxes=None, amount_tps=None, amount_tvq=None,
        totals=[150.0, 50.0],
    )
    assert [p["amount"] for p in parts] == [150.0, 50.0]
    assert all(p["amount_taxes"] is None for p in parts)


def test_ventilation_refuse_une_somme_qui_ne_retombe_pas():
    with pytest.raises(DivisionErreur) as exc:
        ventiler_parts(
            amount=1000.0, amount_taxes=149.75, amount_tps=50.0,
            amount_tvq=99.75, totals=[600.0, 400.0],
        )
    assert "à répartir" in str(exc.value)


def test_validation_des_parts():
    valider_parts([_part(1, 10.0), _part(2, 5.0)])
    with pytest.raises(DivisionErreur, match="au moins deux projets"):
        valider_parts([_part(1, 10.0)])
    with pytest.raises(DivisionErreur, match="qu'une fois"):
        valider_parts([_part(1, 10.0), _part(1, 5.0)])
    with pytest.raises(DivisionErreur, match="supérieur à 0"):
        valider_parts([_part(1, 10.0), _part(2, 0.0)])


def test_memo_prive_liste_les_parts_et_les_projets():
    tete = SimpleNamespace(id=12, supplier_invoice_number="RD-1")
    autre = SimpleNamespace(id=13, supplier_invoice_number="RD-1")
    note = _private_note(tete, None, "Chantier A, Chantier B", [tete, autre])
    assert note.startswith("Source: Horizon h2.0 Achat #12")
    assert "Parts: #12, #13" in note
    assert "Projets: Chantier A, Chantier B" in note
    # Achat simple : forme historique inchangée.
    simple = _private_note(tete, "PO-7", "Chantier A")
    assert simple == (
        "Source: Horizon h2.0 Achat #12 | PO source: PO-7 | "
        "Facture fournisseur: RD-1 | Projet: Chantier A"
    )


def test_montants_du_groupe():
    a = SimpleNamespace(amount=600.0, amount_taxes=89.85, amount_tps=30.0, amount_tvq=59.85)
    b = SimpleNamespace(amount=400.0, amount_taxes=59.9, amount_tps=20.0, amount_tvq=39.9)
    m = montants_groupe([a, b])
    assert (m.amount, m.amount_taxes, m.amount_tps, m.amount_tvq) == (
        1000.0, 149.75, 50.0, 99.75,
    )
    # Une part sans ventilation TPS/TVQ → ventilation du groupe inconnue
    # (recalculée au push) ; taxes connues dès qu'une part en porte.
    c = SimpleNamespace(amount=100.0, amount_taxes=None, amount_tps=None, amount_tvq=None)
    m2 = montants_groupe([a, c])
    assert m2.amount == 700.0 and m2.amount_taxes == 89.85
    assert m2.amount_tps is None and m2.amount_tvq is None
    assert montants_groupe([c]).amount_taxes is None
