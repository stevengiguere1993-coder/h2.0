"""Catalogue centralisé des capacités d'une clé d'API, ORGANISÉ PAR PÔLE.

Une clé d'API (``krts_...``) ne peut faire QUE ce que ses ``scopes``
autorisent, pôle par pôle. Ce module est la SOURCE DE VÉRITÉ unique :

  - la liste des pôles (slugs stables) et leur libellé FR, alignée sur la
    constante ``POLES_KRATOS`` du frontend (page Réglages → Drive) ;
  - pour chaque pôle, la liste de ses capacités ``{id, label_fr,
    description, category, risk}``.

Format d'un scope : ``<pole>:<capability>`` (ex. ``devlog:activity:read``,
``prospection:tasks:create``). Le préfixe est TOUJOURS le slug du pôle.

Extensibilité : ajouter une capacité = ajouter une entrée dans ``CAPABILITIES``
(et, pour un nouveau pôle, dans ``POLES``). Elle apparaît automatiquement
dans le catalogue exposé par l'API et donc dans l'UI (interrupteurs groupés
par pôle), sans autre changement.

Rétrocompatibilité CRITIQUE : une clé SANS ``scopes`` (NULL / liste vide),
ou portant l'ancien scope global ``activity:read``, est traitée comme
« lecture de TOUS les pôles ». Voir ``key_has_scope`` / ``readable_poles``.
"""

from __future__ import annotations

from typing import Optional

# ── Pôles (slugs stables ↔ libellés FR de POLES_KRATOS) ────────────
#
# Les slugs sont l'identité technique (préfixe des scopes, jamais
# affichée). Les libellés FR sont EXACTEMENT ceux de POLES_KRATOS côté
# frontend (frontend/.../parametres/drive/page.tsx) pour la cohérence
# avec la gestion du Drive « Afficher Drive sur les pages ».

#: Pôles exposant des capacités d'API, dans l'ordre d'affichage.
POLES: list[dict[str, str]] = [
    {"slug": "prospection", "label_fr": "Prospection"},
    {"slug": "devlog", "label_fr": "Développement logiciel"},
    {"slug": "construction", "label_fr": "Construction"},
    {"slug": "entreprise", "label_fr": "Gestion d'entreprises"},
    {"slug": "immobilier", "label_fr": "Gestion immobilière"},
    {"slug": "comptabilite", "label_fr": "Comptabilité"},
]

#: Slugs valides (lookup rapide).
POLE_SLUGS: tuple[str, ...] = tuple(p["slug"] for p in POLES)

#: slug → libellé FR.
POLE_LABELS: dict[str, str] = {p["slug"]: p["label_fr"] for p in POLES}


# ── Capacités par pôle ─────────────────────────────────────────────
#
# `category` : "lecture" ou "ecriture" (groupe l'UI / colore sobrement).
# `risk`     : "faible" | "moyen" (indicatif, pour l'utilisateur).
# `coming_soon` : True = capacité déclarée mais NON encore implémentée
#                  (affichée désactivée dans l'UI, jamais accordée).

def _activity_read(pole_slug: str, pole_label: str) -> dict:
    return {
        "id": f"{pole_slug}:activity:read",
        "pole": pole_slug,
        "label_fr": "Lire l'activité",
        "description": (
            f"Lire l'activité du pôle {pole_label} "
            "(tâches complétées / créées / modifiées, journal d'audit)."
        ),
        "category": "lecture",
        "risk": "faible",
        "coming_soon": False,
    }


def _tasks_create(pole_slug: str, pole_label: str) -> dict:
    return {
        "id": f"{pole_slug}:tasks:create",
        "pole": pole_slug,
        "label_fr": "Créer une tâche",
        "description": (
            f"Créer une tâche dans le pôle {pole_label}. La tâche peut être "
            "assignée à N'IMPORTE QUEL membre de l'équipe (par courriel, nom "
            "ou identifiant) ; par défaut elle revient au propriétaire de la "
            "clé."
        ),
        "category": "ecriture",
        "risk": "moyen",
        "coming_soon": False,
    }


def _tasks_update(pole_slug: str, pole_label: str) -> dict:
    return {
        "id": f"{pole_slug}:tasks:update",
        "pole": pole_slug,
        "label_fr": "Modifier une tâche",
        "description": (
            f"Modifier N'IMPORTE QUELLE tâche du pôle {pole_label} (pas "
            "seulement celles du propriétaire de la clé) : statut, titre, "
            "description, assigné (n'importe quel membre), échéance, priorité."
        ),
        "category": "ecriture",
        "risk": "moyen",
        "coming_soon": False,
    }


def _tasks_move(pole_slug: str, pole_label: str) -> dict:
    return {
        "id": f"{pole_slug}:tasks:move",
        "pole": pole_slug,
        "label_fr": "Déplacer une tâche",
        "description": (
            f"Déplacer N'IMPORTE QUELLE tâche du pôle {pole_label} d'une "
            "colonne / étape à une autre (changer son statut kanban), et "
            "ajuster sa position dans la colonne si applicable."
        ),
        "category": "ecriture",
        "risk": "moyen",
        "coming_soon": False,
    }


def _tasks_read(pole_slug: str, pole_label: str) -> dict:
    return {
        "id": f"{pole_slug}:tasks:read",
        "pole": pole_slug,
        "label_fr": "Lire le détail d'une tâche",
        "description": (
            f"Lire le JSON détaillé d'une tâche du pôle {pole_label} "
            "par son identifiant (description, statut, assigné, échéance, "
            "priorité, dates)."
        ),
        "category": "lecture",
        "risk": "faible",
        "coming_soon": False,
    }


#: Capacités de LECTURE DÉTAIL spécifiques à une entité métier d'un pôle,
#: au-delà des tâches. Chaque entrée donne accès au JSON complet (niveau
#: « full ») d'une entité par son id, via l'API REST (``GET
#: /activity/entities/...``) et les outils MCP (``kratos_get_*``).
def _detail_read(
    cap_id: str, pole_slug: str, label_fr: str, description: str
) -> dict:
    return {
        "id": cap_id,
        "pole": pole_slug,
        "label_fr": label_fr,
        "description": description,
        "category": "lecture",
        "risk": "faible",
        "coming_soon": False,
    }


#: Capacités de LECTURE D'ENSEMBLE (liste) d'une entité métier d'un pôle :
#: lister TOUTES les entités d'un type (deals du pipeline, analyses de
#: leads, soumissions, projets, entreprises…), pas une seule par id. Donne
#: une vue de liste paginée (résumés) via l'API REST (``GET
#: /activity/entities/{type}``) et les outils MCP (``kratos_list_*``). Une
#: clé qui peut lire l'activité d'un pôle (``<pole>:activity:read``, donc
#: aussi une clé sans scopes en rétrocompat) peut lister ses entités ;
#: cette capacité dédiée existe pour un contrôle plus fin si souhaité.
def _list_read(
    cap_id: str, pole_slug: str, label_fr: str, description: str
) -> dict:
    return {
        "id": cap_id,
        "pole": pole_slug,
        "label_fr": label_fr,
        "description": description,
        "category": "lecture",
        "risk": "faible",
        "coming_soon": False,
    }


#: Pôles qui portent des tâches lisibles / écrivables par clé d'API
#: (alignés sur les modèles de tâches sérialisables). Les autres pôles
#: n'ont pas (encore) d'entité « tâche » exposée par clé d'API. Pour
#: CHACUN de ces pôles on déclare : tasks:read, tasks:create,
#: tasks:update, tasks:move.
_TASK_POLES: tuple[str, ...] = (
    "devlog",
    "entreprise",
    "prospection",
    "construction",
)


def _build_capabilities() -> list[dict]:
    caps: list[dict] = []
    for pole in POLES:
        slug, label = pole["slug"], pole["label_fr"]
        caps.append(_activity_read(slug, label))
        caps.append(_tasks_create(slug, label))
        if slug in _TASK_POLES:
            caps.append(_tasks_read(slug, label))
            caps.append(_tasks_update(slug, label))
            caps.append(_tasks_move(slug, label))
    # Lecture détail des entités métier de plus haut niveau (au-delà des
    # tâches) — JSON complet par id, exposé en REST + MCP.
    caps.append(
        _detail_read(
            "devlog:soumissions:read",
            "devlog",
            "Lire le détail d'une soumission",
            (
                "Lire le JSON détaillé d'une soumission (devis) du pôle "
                "Développement logiciel par son id : client/lead, statut, "
                "modules + fonctionnalités + tâches du chargé de projet, "
                "montants (HT, TPS, TVQ, TTC), taux, dates, lien public."
            ),
        )
    )
    caps.append(
        _detail_read(
            "prospection:deals:read",
            "prospection",
            "Lire le détail d'un deal",
            (
                "Lire le JSON détaillé d'un deal du Pipeline Prospection "
                "par son id : adresse, étape pipeline, et données clés de "
                "l'analyse financière liée si disponibles."
            ),
        )
    )
    caps.append(
        _detail_read(
            "entreprise:read",
            "entreprise",
            "Lire le détail d'une entreprise",
            (
                "Lire le JSON détaillé d'une entreprise du pôle Gestion "
                "d'entreprises par son id : nom, type, NEQ, contact "
                "principal, description, statut."
            ),
        )
    )
    # Lecture DÉTAIL d'une analyse de lead (fiche d'analyse financière du
    # pôle Prospection) par son id : adresse, étape kanban, statut, chiffres
    # clés (prix, logements, MdF, refi…), dates.
    caps.append(
        _detail_read(
            "prospection:analyses:read",
            "prospection",
            "Lire le détail d'une analyse de lead",
            (
                "Lire le JSON détaillé d'une analyse de lead (fiche d'analyse "
                "financière) du pôle Prospection par son id : adresse, étape "
                "kanban, statut (en cours / converti), chiffres clés (prix "
                "demandé, nombre de logements, revenus, mise de fonds prêteur "
                "B, refinancement…), dates."
            ),
        )
    )
    # ── Capacités de LECTURE D'ENSEMBLE (liste) par pôle ──────────────
    #
    # Vue de liste / d'ensemble : lister TOUTES les entités principales
    # d'un pôle (résumés paginés), pas une seule par id. Couvre les deals
    # du pipeline et les analyses de leads (Prospection), et l'entité
    # principale des autres pôles.
    caps.append(
        _list_read(
            "prospection:deals:list",
            "prospection",
            "Lister les deals du pipeline",
            (
                "Lister les deals du Pipeline Prospection (vue d'ensemble) : "
                "adresse, étape pipeline, et chiffres clés de l'analyse liée. "
                "Filtrable par étape. Résumés paginés (limite raisonnable)."
            ),
        )
    )
    caps.append(
        _list_read(
            "prospection:analyses:list",
            "prospection",
            "Lister les analyses de leads",
            (
                "Lister les analyses de leads du pôle Prospection (vue "
                "d'ensemble), avec leur statut kanban. Filtrable par statut "
                "(p. ex. « en cours »). Résumés paginés (limite raisonnable)."
            ),
        )
    )
    caps.append(
        _list_read(
            "devlog:soumissions:list",
            "devlog",
            "Lister les soumissions",
            (
                "Lister les soumissions (devis) du pôle Développement "
                "logiciel (vue d'ensemble) : titre, client/lead, statut, "
                "montant. Résumés paginés (limite raisonnable)."
            ),
        )
    )
    caps.append(
        _list_read(
            "devlog:projects:list",
            "devlog",
            "Lister les projets de développement",
            (
                "Lister les projets du pôle Développement logiciel (vue "
                "d'ensemble) : nom, statut, échéance. Résumés paginés "
                "(limite raisonnable)."
            ),
        )
    )
    caps.append(
        _list_read(
            "entreprise:list",
            "entreprise",
            "Lister les entreprises",
            (
                "Lister les entreprises du pôle Gestion d'entreprises (vue "
                "d'ensemble) : nom, type, NEQ, statut. Résumés paginés "
                "(limite raisonnable)."
            ),
        )
    )
    caps.append(
        _list_read(
            "construction:projects:list",
            "construction",
            "Lister les projets (chantiers)",
            (
                "Lister les projets / chantiers du pôle Construction (vue "
                "d'ensemble) : nom, adresse, statut. Résumés paginés "
                "(limite raisonnable)."
            ),
        )
    )
    # Capacité SPÉCIFIQUE au Développement logiciel, déclarée mais
    # « à venir » : brouillon de soumission. NON implémentée dans ce lot
    # → marquée coming_soon (jamais accordée, affichée désactivée).
    caps.append(
        {
            "id": "devlog:soumissions:draft",
            "pole": "devlog",
            "label_fr": "Créer un brouillon de soumission",
            "description": (
                "Préparer un brouillon de soumission (devis) du pôle "
                "Développement logiciel. À venir — pas encore disponible."
            ),
            "category": "ecriture",
            "risk": "moyen",
            "coming_soon": True,
        }
    )
    return caps


#: Catalogue complet des capacités (toutes pôles confondues).
CAPABILITIES: list[dict] = _build_capabilities()

#: id → capacité (lookup rapide).
CAPABILITIES_BY_ID: dict[str, dict] = {c["id"]: c for c in CAPABILITIES}

#: Ensemble des ids de capacités RÉELLEMENT accordables (hors coming_soon).
GRANTABLE_SCOPE_IDS: frozenset[str] = frozenset(
    c["id"] for c in CAPABILITIES if not c["coming_soon"]
)

#: Ancien scope global de lecture (rétrocompat) — lit tous les pôles.
LEGACY_GLOBAL_READ = "activity:read"


# ── Logique d'autorisation (rétrocompatible) ───────────────────────


def _normalize(scopes: Optional[list[str]]) -> Optional[list[str]]:
    """Retourne la liste de scopes nettoyée, ou None si « pas de scopes
    explicites » (→ rétrocompat : accès lecture tous pôles)."""
    if not scopes:
        return None
    cleaned = [s for s in scopes if isinstance(s, str) and s.strip()]
    if not cleaned:
        return None
    return cleaned


def key_has_scope(scopes: Optional[list[str]], required: str) -> bool:
    """La clé porte-t-elle la capacité ``required`` (ex. ``devlog:tasks:create``) ?

    Règles de rétrocompatibilité :
      - clé SANS scopes (NULL/[]/que des entrées vides) → accès LECTURE de
        TOUS les pôles (``<pole>:activity:read`` pour tout pôle), mais
        AUCUNE capacité d'écriture ;
      - ancien scope global ``activity:read`` présent → idem (lecture tous
        pôles), les autres scopes éventuels s'ajoutent normalement.
    """
    norm = _normalize(scopes)

    # Rétrocompat : aucune liste explicite = lecture de tous les pôles.
    if norm is None:
        return required.endswith(":activity:read")

    if required in norm:
        return True

    # Ancien scope global de lecture → couvre toute lecture de pôle.
    if required.endswith(":activity:read") and LEGACY_GLOBAL_READ in norm:
        return True

    return False


def readable_poles(scopes: Optional[list[str]]) -> set[str]:
    """Ensemble des slugs de pôles dont la clé peut LIRE l'activité.

    Rétrocompat : clé sans scopes (ou avec l'ancien ``activity:read``)
    = TOUS les pôles."""
    norm = _normalize(scopes)
    if norm is None or LEGACY_GLOBAL_READ in norm:
        return set(POLE_SLUGS)
    out: set[str] = set()
    for slug in POLE_SLUGS:
        if f"{slug}:activity:read" in norm:
            out.add(slug)
    return out


def sanitize_scopes(scopes: Optional[list[str]]) -> list[str]:
    """Filtre une liste de scopes reçue du client : ne garde QUE des ids
    de capacités réellement accordables (existantes et non coming_soon),
    sans doublon, dans l'ordre du catalogue. Tout scope inconnu / à venir
    est silencieusement écarté (on ne peut pas accorder ce qui n'existe pas)."""
    if not scopes:
        return []
    wanted = {s for s in scopes if isinstance(s, str)}
    return [c["id"] for c in CAPABILITIES
            if c["id"] in wanted and c["id"] in GRANTABLE_SCOPE_IDS]


def catalog() -> dict:
    """Catalogue prêt à exposer côté API : pôles + capacités groupées."""
    by_pole: dict[str, list[dict]] = {slug: [] for slug in POLE_SLUGS}
    for c in CAPABILITIES:
        by_pole.setdefault(c["pole"], []).append(c)
    return {
        "poles": [
            {
                "slug": p["slug"],
                "label_fr": p["label_fr"],
                "capabilities": by_pole.get(p["slug"], []),
            }
            for p in POLES
        ],
        "legacy_global_read": LEGACY_GLOBAL_READ,
    }