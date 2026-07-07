"""Garde-fou de schéma — empêche le retour du bug de FK cassée (P-02).

Contexte : une FK `DepenseImmeuble.immeuble_id → immeubles.id` (table
inexistante ; la vraie s'appelle `imm_immeubles`) faisait échouer TOUT
`Base.metadata.create_all()` (NoReferencedTableError), donc `init_db`
plantait en silence à chaque boot pendant ~26 jours. Ces tests figent
l'invariant : aucune FK du modèle ne doit pointer vers une table absente.
"""
from __future__ import annotations

from app.db.base import Base
# Importer l'app enregistre tous les modèles sur `Base.metadata`.
from tests.smoke.conftest import _stub_unresolved_fk_targets


def test_immeuble_depenses_fk_points_to_real_table() -> None:
    """La FK réparée cible bien `imm_immeubles` (le bug exact du P-02)."""
    from app.models.immobilier import DepenseImmeuble

    fks = list(DepenseImmeuble.__table__.c.immeuble_id.foreign_keys)
    assert fks, "immeuble_id devrait porter une clé étrangère"
    target_table = fks[0].target_fullname.split(".")[0]
    assert target_table == "imm_immeubles", (
        f"FK cassée : immeuble_depenses.immeuble_id pointe vers "
        f"'{target_table}' au lieu de 'imm_immeubles'"
    )


def test_no_foreign_key_points_to_missing_table() -> None:
    """Garde générale : `create_all` ne doit avoir besoin d'AUCUN stub.

    `_stub_unresolved_fk_targets()` ajoute une table factice pour chaque
    cible de FK introuvable et retourne la liste des tables stubbées. Après
    correction, plus aucune FK n'est orpheline → il ne stubbe rien → []."""
    stubbed = _stub_unresolved_fk_targets()
    assert stubbed == [], (
        f"Des FK pointent vers des tables inexistantes : {stubbed}. "
        f"Une FK cassée ferait replanter init_db en prod (cf. P-02)."
    )
