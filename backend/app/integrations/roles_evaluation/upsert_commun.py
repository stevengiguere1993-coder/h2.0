"""Colonnes de l'UPSERT ``ON CONFLICT (matricule)`` partagées par l'import
du rôle de la Ville de Montréal et par l'import provincial MAMH.

Ce que NOUS ajoutons sur une unité (propriétaires collectés sur EvalWeb,
marquage « logement social ») ne vient pas des fichiers de rôle : un
ré-import ne doit jamais l'effacer. Avant, ``excluded.owners_json`` valait
NULL (colonne absente de l'INSERT) et chaque ré-import remettait à zéro
les propriétaires collectés (constat 2026-09-28). L'arrondissement, lui,
est complété : la nouvelle valeur si le fichier en fournit une, sinon
celle déjà en base (dérivée du dataset Adresses civiques).
"""
from __future__ import annotations

from typing import Any, Dict

from sqlalchemy import func

from app.models.montreal_property_unit import MontrealPropertyUnit

#: Colonnes que l'import ne touche jamais (données collectées par nous).
COLONNES_CONSERVEES = frozenset(
    {"owners_json", "owners_fetched_at", "logement_social"}
)
#: Colonnes complétées : nouvelle valeur si fournie, sinon l'existante.
COLONNES_COMPLETEES = frozenset({"arrondissement"})


def colonnes_upsert(stmt: Any) -> Dict[str, Any]:
    """``set_`` de ``on_conflict_do_update`` pour ``stmt`` (un
    ``pg_insert(MontrealPropertyUnit)``)."""
    table = MontrealPropertyUnit.__table__
    cols: Dict[str, Any] = {}
    for c in table.columns:
        if c.name == "matricule" or c.name in COLONNES_CONSERVEES:
            continue
        if c.name in COLONNES_COMPLETEES:
            cols[c.name] = func.coalesce(stmt.excluded[c.name], table.c[c.name])
        else:
            cols[c.name] = stmt.excluded[c.name]
    return cols
