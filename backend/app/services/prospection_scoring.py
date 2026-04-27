"""Scoring automatique des leads de prospection.

Le score est un entier 0-100 calculé à partir des données enrichies
sur le lead (nb logements, valeur, propriétaire, type, etc.).

Profil cible Horizon :
- Multi-logements 4-20 portes (zone optimale 6-12)
- Bâtiments 30+ ans (besoin de rénovation)
- Propriétaires corporations (décisions d'investissement, budgets)
- Région Montréal + Rive-Sud (couverte par nos sources de données)

Tags : étiquettes texte stockées sur le lead pour faciliter le tri.
On en émet entre 0 et 6 par lead. Stockés en JSON-string dans la
colonne `tags`.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import List, Tuple

from app.models.prospection_lead import (
    ProspectionLead,
    ProspectionLeadKind,
    ProspectionOwnerKind,
)


def _score_nb_logements(n: int | None) -> Tuple[int, str | None]:
    """Le sweet spot Horizon est 6-12 portes (assez gros pour un
    contrat juteux, mais pas trop pour gérer)."""
    if n is None:
        return 0, None
    if 6 <= n <= 12:
        return 30, "sweet-spot"
    if 4 <= n <= 5:
        return 22, "petit-multi"
    if 13 <= n <= 20:
        return 24, "moyen-multi"
    if n >= 21:
        return 14, "gros-multi"
    if n <= 3:
        return 6, None
    return 0, None


def _score_age(annee: int | None) -> Tuple[int, str | None]:
    """Vieux bâtiments = plus de besoin en rénovation."""
    if annee is None:
        return 0, None
    age = datetime.now(timezone.utc).year - annee
    if age >= 60:
        return 18, "tres-vieux"
    if age >= 40:
        return 14, "vieux"
    if age >= 25:
        return 10, "mature"
    if age >= 10:
        return 4, None
    return 0, "neuf"


def _score_owner(lead: ProspectionLead) -> Tuple[int, List[str]]:
    """Corporations = décisions d'affaires, donc plus probables d'avoir
    le budget pour de la rénovation. Particulier identifié = aussi
    valable. Inconnu = on ne peut rien démarcher."""
    tags: List[str] = []
    if lead.owner_kind == ProspectionOwnerKind.CORPORATION.value:
        score = 18
        tags.append("corp")
        if lead.owner_neq:
            tags.append("neq-connu")
            score += 4
    elif lead.owner_kind == ProspectionOwnerKind.PARTICULIER.value:
        score = 10
        if lead.owner_email or lead.owner_phone:
            score += 4
            tags.append("contact-direct")
    else:
        score = 0
        tags.append("proprio-inconnu")
    return score, tags


def _score_kind(kind: str) -> int:
    if kind == ProspectionLeadKind.MULTILOGEMENT.value:
        return 14
    if kind == ProspectionLeadKind.SEMI_COMMERCIAL.value:
        return 8
    if kind == ProspectionLeadKind.TERRAIN.value:
        return 4
    return 0


def _score_completeness(lead: ProspectionLead) -> int:
    """Un lead bien renseigné est plus actionnable. Petit boost."""
    pts = 0
    if (lead.address or "").strip():
        pts += 2
    if (lead.notes or "").strip():
        pts += 2
    if lead.matricule:
        pts += 2
    if lead.valeur_fonciere:
        pts += 2
    return pts


def compute_score(lead: ProspectionLead) -> Tuple[int, List[str]]:
    """Calcule (score, tags) pour un lead.

    Le score est plafonné à 100. Les tags sont dédupliqués et limités
    à 6 entrées max pour rester lisibles dans l'UI.
    """
    score = 0
    tags: List[str] = []

    s, tag = _score_nb_logements(lead.nb_logements)
    score += s
    if tag:
        tags.append(tag)

    s, tag = _score_age(lead.annee_construction)
    score += s
    if tag:
        tags.append(tag)

    s, tags_owner = _score_owner(lead)
    score += s
    tags.extend(tags_owner)

    score += _score_kind(lead.kind)
    score += _score_completeness(lead)

    if lead.priority and lead.priority >= 4:
        score += 4
        tags.append("priorite-haute")

    # Plafond
    score = max(0, min(100, score))

    # Dédup + limit
    seen: set[str] = set()
    deduped: List[str] = []
    for t in tags:
        if t and t not in seen:
            seen.add(t)
            deduped.append(t)
        if len(deduped) >= 6:
            break

    return score, deduped


def apply_score(lead: ProspectionLead) -> None:
    """Recalcule score+tags et les écrit sur l'instance du lead.
    Pas de DB flush ici — l'appelant doit await db.flush() si besoin.
    """
    score, tags = compute_score(lead)
    lead.score = score
    lead.tags = json.dumps(tags) if tags else None


def parse_tags(raw: str | None) -> List[str]:
    """Désérialise la colonne `tags` (JSON-string) en list de strings.
    Robuste : retourne [] si null, vide ou JSON invalide."""
    if not raw:
        return []
    try:
        v = json.loads(raw)
        if isinstance(v, list):
            return [str(x) for x in v]
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    return []
