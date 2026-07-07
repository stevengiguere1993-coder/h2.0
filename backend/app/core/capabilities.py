"""Registre des capacités configurables (permissions gérables depuis
Paramètres → Permissions).

Chaque capacité a un **rôle minimum requis par défaut** = le comportement
actuellement codé en dur. Ce défaut est semé dans la table
``role_permissions`` au démarrage (idempotent, ne réécrase jamais un choix
de l'owner). L'owner peut ensuite ajuster le rôle minimum depuis l'UI, et le
garde ``require_capability`` le lit dynamiquement.

⚠️ Ne déclarer ici QUE des capacités effectivement branchées sur un endpoint
via ``require_capability("<id>")`` — sinon la grille afficherait un
interrupteur sans effet. Ajouter une capacité = 1 entrée ici + brancher
l'endpoint correspondant. Les 4 rôles hiérarchiques (owner>admin>manager>
employee) restent le socle ; « qui peut » = seuil (rôle minimum).
"""
from __future__ import annotations

from dataclasses import dataclass

from app.models.user import ROLE_RANK

#: Rôles valides, du plus bas au plus haut (pour l'UI + validation).
ROLES_ASCENDING = ["employee", "manager", "admin", "owner"]


@dataclass(frozen=True)
class Capability:
    """Une action dont le rôle minimum requis est configurable."""

    id: str
    label: str
    description: str
    category: str
    default_min_role: str


#: Catalogue des capacités configurables. Démarre par les ACTIONS SENSIBLES
#: (choix de Phil) ; l'accès aux pôles viendra dans un second temps.
CAPABILITIES: list[Capability] = [
    Capability(
        id="project.delete",
        label="Supprimer un projet",
        description=(
            "Effacer définitivement un projet de construction (action "
            "destructive, irréversible côté utilisateur)."
        ),
        category="Projets",
        default_min_role="manager",
    ),
]

CAPABILITIES_BY_ID: dict[str, Capability] = {c.id: c for c in CAPABILITIES}


def is_valid_role(role: str) -> bool:
    return role in ROLE_RANK
