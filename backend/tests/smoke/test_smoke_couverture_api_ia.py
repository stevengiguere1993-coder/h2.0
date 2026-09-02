"""Cliquet « IA au courant de tout » (demande Phil 2026-09-02).

Toute NOUVELLE table du modèle doit être une décision consciente
d'exposition via la clé API / le connecteur MCP — pas un oubli. Une
table inconnue de ``TABLES_COUVERTES`` fait échouer la suite avec la
marche à suivre, pour TOUTES les sessions qui travaillent sur Kratos.
"""
from __future__ import annotations

import app.models  # noqa: F401 — enregistre toutes les tables
from app.core.api_ia_couverture import TABLES_COUVERTES
from app.db.base import Base


def test_toute_nouvelle_table_est_exposee_via_la_cle():
    actuelles = set(Base.metadata.tables.keys())
    nouvelles = sorted(actuelles - TABLES_COUVERTES)
    assert not nouvelles, (
        "Nouvelles tables SANS exposition déclarée pour la clé API/MCP : "
        f"{nouvelles}. Règle Phil (2026-09-02) : chaque fonctionnalité "
        "doit être disponible via le connecteur sans qu'il le demande. "
        "1) Les écritures sont déjà journalisées automatiquement ; "
        "2) branche la LECTURE (registres _LIST_ENTITIES/_DETAIL_ENTITIES "
        "d'activity.py ou outil MCP dédié) ; 3) ajoute la table à "
        "app/core/api_ia_couverture.py."
    )


def test_les_tables_couvertes_existent_encore():
    """Une table retirée du modèle doit aussi sortir de la liste —
    garde la liste honnête."""
    actuelles = set(Base.metadata.tables.keys())
    fantomes = sorted(TABLES_COUVERTES - actuelles)
    assert not fantomes, (
        f"Tables listées dans api_ia_couverture mais disparues du "
        f"modèle : {fantomes} — retire-les de la liste."
    )
