"""Une dépense QB payée à un client ou un employé ne crée pas de fournisseur."""

from app.services.qbo_cost_pull import _nom_fournisseur_de


def test_vendor_garde_son_nom():
    assert _nom_fournisseur_de({"value": "12", "name": "Rona", "type": "Vendor"}) == "Rona"


def test_type_absent_garde_son_nom():
    assert _nom_fournisseur_de({"value": "12", "name": "BMR"}) == "BMR"


def test_client_et_employe_ignores():
    assert (
        _nom_fournisseur_de(
            {"value": "58", "name": "Alexandre Beaudoin", "type": "Customer"}
        )
        is None
    )
    assert _nom_fournisseur_de({"name": "Jean", "type": "Employee"}) is None


def test_ref_vide():
    assert _nom_fournisseur_de(None) is None
