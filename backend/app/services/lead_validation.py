"""Validation post-extraction des fiches LeadAnalysis (Phase A3).

Pour chaque `LeadAnalysis` qu'on vient d'extraire (couche 1, 2 ou 3),
on lance une passe de validation qui :

  1. Vérifie que les champs numériques tombent dans des bornes
     plausibles (un asking_price à 30 $ ou 200 M $ est suspect).
  2. Détecte les divergences entre la couche 1 (parser local) et la
     couche 2 (Gemini) quand les deux ont produit une valeur — écart
     relatif > 20 % sur un champ numérique.
  3. Retourne une liste structurée de warnings :

        [{
           "field": "asking_price",
           "severity": "info" | "warning" | "error",
           "message": "Asking price hors bornes : 30 $",
           "source_local": 30,
           "source_gemini": 750000,
           "source_claude": null
        }, ...]

Les warnings sont stockés dans la nouvelle colonne JSONB
``lead_analyses.validation_warnings`` (cf. db/session.py) et affichés
côté frontend (panneau « Validation » dans la fiche + indicateur
amber/red à côté du badge sur la card kanban).

API :

    validate_extraction(
        analysis,
        per_source_values=...,    # optionnel : dict {field: {local, gemini, claude}}
    ) -> list[dict]

`per_source_values` est rempli par le pipeline d'extraction (voir
`lead_extraction.py` qui retourne désormais ce dict dans
`ExtractionResult.per_source_values`). Quand on n'a que les valeurs
fusionnées (ex. au moment d'un appel manuel pour revalider une fiche
déjà sauvegardée), on peut omettre cet argument — seules les bornes
seront vérifiées, pas les divergences.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple


# ── Bornes numériques (min, max) par champ ──────────────────────────
#
# Bornes calibrées pour les immeubles multi-logements québécois 4+
# portes. Au-delà → ``warning`` (valeur très inhabituelle) ; sous le
# minimum → ``warning`` également. Le seul ``error`` est l'asking_price
# (un prix < 50 k$ ou > 50 M$ sur ce type d'actif est forcément faux).
_NUMERIC_BOUNDS: Dict[str, Tuple[float, float, str]] = {
    # field: (min, max, severity_if_out_of_range)
    "asking_price":     (50_000,    50_000_000, "error"),
    "nb_logements":     (1,         100,        "warning"),
    "taxes_municipales": (500,      500_000,    "warning"),
    "taxes_scolaires":   (100,      100_000,    "warning"),
    "assurances":        (500,      50_000,     "warning"),
    "energie":           (1_000,    100_000,    "warning"),
}


# Champs numériques pour lesquels on vérifie aussi la divergence
# locale ↔ Gemini (écart relatif > 20 %).
_DIVERGENCE_FIELDS: Tuple[str, ...] = (
    "asking_price",
    "nb_logements",
    "revenus_bruts",
    "taxes_municipales",
    "taxes_scolaires",
    "assurances",
    "energie",
    "evaluation_municipale",
    "superficie_terrain",
    "superficie_batiment",
    "annee_construction",
)

# Seuil de divergence relatif (20 %).
_DIVERGENCE_THRESHOLD = 0.20


def _to_float(v: Any) -> Optional[float]:
    """Convertit en float si possible, sinon None. Tolère
    ``Decimal`` (sortie SQLAlchemy ``Numeric``) et les strings."""
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _format_money(v: float) -> str:
    """Format CAD compact : ``50 000 $``."""
    n = round(v)
    sign = "-" if n < 0 else ""
    abs_str = str(abs(n))
    with_sep = ""
    for i, c in enumerate(reversed(abs_str)):
        if i > 0 and i % 3 == 0:
            with_sep = " " + with_sep
        with_sep = c + with_sep
    return f"{sign}{with_sep} $"


def _format_value(field: str, v: float) -> str:
    """Format human-friendly pour les messages de warning."""
    if field in (
        "asking_price",
        "revenus_bruts",
        "taxes_municipales",
        "taxes_scolaires",
        "assurances",
        "energie",
        "evaluation_municipale",
    ):
        return _format_money(v)
    if field == "nb_logements":
        return f"{int(v)}"
    if field == "annee_construction":
        return f"{int(v)}"
    return f"{v:g}"


# Libellé français court par champ — sert dans les messages utilisateur.
_FIELD_LABELS: Dict[str, str] = {
    "asking_price":         "prix demandé",
    "nb_logements":         "nombre de logements",
    "revenus_bruts":        "revenus bruts",
    "taxes_municipales":    "taxes municipales",
    "taxes_scolaires":      "taxes scolaires",
    "assurances":           "assurances",
    "energie":              "énergie",
    "evaluation_municipale": "évaluation municipale",
    "superficie_terrain":   "superficie terrain",
    "superficie_batiment":  "superficie bâtiment",
    "annee_construction":   "année construction",
}


def _label(field: str) -> str:
    return _FIELD_LABELS.get(field, field)


def _check_bounds(
    field: str,
    value: float,
    extras: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """Vérifie que ``value`` est dans les bornes définies pour
    ``field``. Retourne un warning dict ou None."""
    bounds = _NUMERIC_BOUNDS.get(field)
    if bounds is None:
        return None
    lo, hi, severity = bounds
    if value < lo or value > hi:
        return {
            "field": field,
            "severity": severity,
            "message": (
                f"{_label(field).capitalize()} hors bornes plausibles : "
                f"{_format_value(field, value)} "
                f"(attendu entre {_format_value(field, lo)} et "
                f"{_format_value(field, hi)})."
            ),
            **extras,
        }
    return None


def _check_revenus_vs_price(
    revenus: float,
    price: float,
    extras: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """Revenus bruts annuels doivent rester < 50 % du prix d'achat.
    Au-delà : revenus aberrants par rapport au prix (probable confusion
    mensuel / annuel ou mauvaise unité)."""
    if price <= 0:
        return None
    if revenus < 0:
        return {
            "field": "revenus_bruts",
            "severity": "warning",
            "message": (
                f"Revenus bruts négatifs : "
                f"{_format_value('revenus_bruts', revenus)}."
            ),
            **extras,
        }
    if revenus > price * 0.5:
        return {
            "field": "revenus_bruts",
            "severity": "warning",
            "message": (
                f"Revenus bruts ({_format_value('revenus_bruts', revenus)}) "
                f"> 50 % du prix demandé "
                f"({_format_value('asking_price', price)}). Vérifier — "
                "valeur probablement mensuelle ou mauvaise unité."
            ),
            **extras,
        }
    return None


def _check_divergence(
    field: str,
    local_v: Any,
    gemini_v: Any,
) -> Optional[Dict[str, Any]]:
    """Vérifie l'écart relatif entre la valeur du parser local et
    celle de Gemini sur un même champ. Renvoie un warning si > 20 %."""
    a = _to_float(local_v)
    b = _to_float(gemini_v)
    if a is None or b is None:
        return None
    # On évite la division par 0 ; si les deux valeurs sont 0,
    # pas de divergence.
    denom = max(abs(a), abs(b))
    if denom == 0:
        return None
    diff = abs(a - b) / denom
    if diff <= _DIVERGENCE_THRESHOLD:
        return None
    return {
        "field": field,
        "severity": "warning",
        "message": (
            f"Divergence sur {_label(field)} : "
            f"local = {_format_value(field, a)}, "
            f"Gemini = {_format_value(field, b)} "
            f"(écart {diff * 100:.0f} %). Vérifier manuellement."
        ),
        "source_local": a,
        "source_gemini": b,
    }


def validate_extraction(
    analysis: Any,
    per_source_values: Optional[Dict[str, Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """Valide les champs d'une ``LeadAnalysis`` après extraction.

    Arguments :
        analysis : instance ORM ``LeadAnalysis`` (les bornes sont
            vérifiées sur les champs finalement persistés).
        per_source_values : ``{field: {"local": x, "gemini": y,
            "claude": z}}``. Quand le pipeline d'extraction a vu les
            deux couches, on peut détecter les divergences. Si
            absent, seules les bornes sont vérifiées.

    Retourne la liste des warnings (peut être vide). L'ordre est
    stable (par champ, errors avant warnings avant info).
    """
    warnings: List[Dict[str, Any]] = []
    per_src = per_source_values or {}

    # ── Bornes par champ ─────────────────────────────────────────
    for field in _NUMERIC_BOUNDS.keys():
        v = _to_float(getattr(analysis, field, None))
        if v is None:
            continue
        # Annexes utilisées pour le tooltip côté UI (valeurs par
        # couche, quand le pipeline les a fournies).
        src = per_src.get(field, {}) or {}
        extras = {
            "source_local": _to_float(src.get("local")),
            "source_gemini": _to_float(src.get("gemini")),
            "source_claude": _to_float(src.get("claude")),
        }
        w = _check_bounds(field, v, extras)
        if w is not None:
            warnings.append(w)

    # ── Règle spéciale : revenus_bruts vs asking_price ──────────
    price = _to_float(getattr(analysis, "asking_price", None))
    revenus = _to_float(getattr(analysis, "revenus_bruts", None))
    if revenus is not None and price is not None:
        src = per_src.get("revenus_bruts", {}) or {}
        extras = {
            "source_local": _to_float(src.get("local")),
            "source_gemini": _to_float(src.get("gemini")),
            "source_claude": _to_float(src.get("claude")),
        }
        w = _check_revenus_vs_price(revenus, price, extras)
        if w is not None:
            warnings.append(w)

    # ── Divergences local ↔ Gemini ─────────────────────────────
    for field in _DIVERGENCE_FIELDS:
        src = per_src.get(field)
        if not src:
            continue
        w = _check_divergence(field, src.get("local"), src.get("gemini"))
        if w is not None:
            warnings.append(w)

    # Tri stable : errors d'abord, puis warnings, puis infos. Au
    # sein d'une sévérité, par champ.
    _sev_order = {"error": 0, "warning": 1, "info": 2}
    warnings.sort(
        key=lambda w: (_sev_order.get(w.get("severity"), 99), w.get("field", ""))
    )
    return warnings


def summarize_severity(
    warnings: List[Dict[str, Any]],
) -> Optional[str]:
    """Retourne la sévérité maximale présente dans la liste, ou None
    si aucune entrée. Utile pour résumer en un mot l'état d'une fiche
    (« error » > « warning » > « info »).
    """
    if not warnings:
        return None
    for sev in ("error", "warning", "info"):
        if any(w.get("severity") == sev for w in warnings):
            return sev
    return None
