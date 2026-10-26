"""Position GPS prise au punch (Steven, 2026-10-26) : format « début|fin »."""

from app.services.punch_geo import ajouter_fin, normaliser, position


def test_position_arrondie_a_6_decimales():
    assert position(45.5016889, -73.567256) == "45.501689,-73.567256"


def test_position_absente_ou_invalide():
    assert position(None, -73.5) is None
    assert position(45.5, None) is None
    # Hors limites ou (0, 0) : un appareil qui n'a pas vraiment de position.
    assert position(91.0, 0.0) is None
    assert position(45.5, 181.0) is None
    assert position(0.0, 0.0) is None


def test_normaliser_le_texte_de_l_app():
    assert normaliser(" 45.5016889,-73.567256 ") == "45.501689,-73.567256"
    assert normaliser(None) is None
    assert normaliser("") is None
    assert normaliser("abc") is None
    assert normaliser("45.5") is None
    assert normaliser("45.5,x") is None


def test_ajouter_fin_garde_le_debut():
    assert ajouter_fin("45.5,-73.5", "45.6,-73.6") == "45.5,-73.5|45.6,-73.6"
    # Début inconnu : la fin reste à droite du séparateur, jamais prise
    # pour le début.
    assert ajouter_fin(None, "45.6,-73.6") == "|45.6,-73.6"
    # Pas de fin reçue : rien ne change.
    assert ajouter_fin("45.5,-73.5", None) == "45.5,-73.5"
    assert ajouter_fin(None, None) is None
    # Une fin déjà posée (double arrêt) est remplacée, pas empilée.
    assert ajouter_fin("45.5,-73.5|1.0,1.0", "45.6,-73.6") == "45.5,-73.5|45.6,-73.6"
