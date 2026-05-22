"""Calcul du devis « devis_dev » du pôle Développement logiciel.

Le devis est composé de deux blocs facturés séparément :

1. **Frais Mensuels Récurrents** (hébergement, support, abonnements,
   maintenance) — facturés en montant mensuel unique côté client.

       Total_mensuel_client = Σ(items.cost_per_unit) × (1 + marge_rec)

   La marge mensuelle s'applique à la somme des coûts ; aucune
   commission closer n'est prélevée (paiement récurrent, donc pas de
   commission par convention).

2. **Frais de Mise en Oeuvre** (développement initial) — facturés en
   un seul one-shot. Le calcul est *circulaire* : la commission du
   closer s'applique au total final (toutes marges incluses), ce qui
   force la résolution algébrique fermée suivante.

       Coûts_dev_total = Σ(feature_i.heures × taux_dev)
       Coût_manager   = heures_manager × taux_manager
       Frais_fixes    = Σ(frais_fixe_j.cost_per_unit)
       Base = Coûts_dev_total + Coût_manager + Frais_fixes

       closing = Total_final × commission_closer
       Total_avant_marge = Base + closing
       Total_final      = (Base + closing) × (1 + marge_initiale)

       ⇒ closing = (1+marge) × closer_pct × Base /
                   (1 - (1+marge) × closer_pct)
       ⇒ Total_final = Base × (1+marge) /
                       (1 - (1+marge) × closer_pct)

   Si ``(1+marge) × closer_pct >= 1`` la formule diverge — on renvoie
   ``is_invalid = True`` et tous les montants à 0 pour que l'UI puisse
   afficher une erreur compréhensible.

Vue client (mise en oeuvre) : on répartit ``Coût_manager + closing``
proportionnellement aux features (au prorata des heures), puis on
applique la marge ; les frais fixes ne portent que la marge (le closer
et le manager ne s'imputent pas à eux). Conséquence vérifiable :

       Σ(prix_features_client) + Σ(prix_fixes_client) = Total_final
"""

from decimal import Decimal
from typing import Any, Iterable


# Tolérance d'arrondi pour les comparaisons finales (cents).
_EPS = 0.01


def _f(value: Any, default: float = 0.0) -> float:
    """Convertit Decimal / int / str / None en ``float`` sûr."""
    if value is None:
        return default
    if isinstance(value, Decimal):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _round(value: float, ndigits: int = 2) -> float:
    """Arrondit en évitant les ``-0.00`` cosmétiques."""
    rounded = round(value, ndigits)
    if rounded == 0:
        return 0.0
    return rounded


def compute_devis(
    soumission: Any,
    items: Iterable[Any],
) -> dict:
    """Calcule la décomposition d'un devis « devis_dev ».

    Paramètres
    ----------
    soumission
        Une instance ``DevlogSoumission`` (lecture seule). On lit
        ``marge_recurrente_pct``, ``marge_initiale_pct``,
        ``commission_closer_pct``, ``taux_dev_horaire``,
        ``taux_manager_horaire``, ``heures_manager``.
    items
        Iterable d'items (``DevlogSoumissionItem``) — on regroupe par
        ``item_kind`` : ``recurring_cost`` / ``feature`` / ``fixed_cost``.

    Retour
    ------
    Dictionnaire structuré (cf. ``DevisPreview`` côté schémas).
    """
    # --- Paramètres avec defaults ---------------------------------------
    marge_rec_pct = _f(soumission.marge_recurrente_pct, 50.0) / 100.0
    marge_init_pct = _f(soumission.marge_initiale_pct, 50.0) / 100.0
    closer_pct = _f(soumission.commission_closer_pct, 10.0) / 100.0
    taux_dev = _f(soumission.taux_dev_horaire, 75.0)
    taux_manager = _f(soumission.taux_manager_horaire, 80.0)
    heures_manager = _f(soumission.heures_manager, 0.0)

    # --- Tri par item_kind ----------------------------------------------
    recurring_items = []
    features = []
    fixed_costs = []
    for it in items:
        kind = getattr(it, "item_kind", "feature") or "feature"
        if kind == "recurring_cost":
            recurring_items.append(it)
        elif kind == "fixed_cost":
            fixed_costs.append(it)
        else:
            # ``feature`` (par défaut)
            features.append(it)

    # ================================================================
    # SECTION 1 — Frais Mensuels Récurrents
    # ================================================================
    recurring_breakdown = []
    total_owner_recurring = 0.0
    for it in recurring_items:
        cost = _f(getattr(it, "cost_per_unit", 0))
        total_owner_recurring += cost
        recurring_breakdown.append(
            {
                "id": getattr(it, "id", None),
                "description": getattr(it, "description", ""),
                "cost_per_unit": _round(cost),
            }
        )
    total_client_recurring = total_owner_recurring * (1 + marge_rec_pct)
    marge_rec_amount = total_client_recurring - total_owner_recurring

    recurring_block = {
        "total_owner_cost": _round(total_owner_recurring),
        "total_client_amount": _round(total_client_recurring),
        "marge_amount": _round(marge_rec_amount),
        "marge_pct": _round(marge_rec_pct * 100, 4),
        "items_breakdown": recurring_breakdown,
    }

    # ================================================================
    # SECTION 2 — Frais de Mise en Oeuvre (calcul circulaire)
    # ================================================================
    # 1. Coûts internes
    couts_dev = 0.0
    feature_costs_internal = []  # (item, cout_dev_brut)
    for it in features:
        heures = _f(getattr(it, "heures", 0))
        cout = heures * taux_dev
        couts_dev += cout
        feature_costs_internal.append((it, heures, cout))

    cout_manager = heures_manager * taux_manager
    frais_fixes_total = 0.0
    fixed_costs_internal = []  # (item, cost_brut)
    for it in fixed_costs:
        cost = _f(getattr(it, "cost_per_unit", 0))
        frais_fixes_total += cost
        fixed_costs_internal.append((it, cost))

    base = couts_dev + cout_manager + frais_fixes_total

    # 2. Validation
    divisor = 1.0 - (1.0 + marge_init_pct) * closer_pct
    is_invalid = divisor <= 0 or base <= 0

    # 3. Résolution circulaire (closing + total_final)
    if is_invalid:
        total_final = 0.0
        closing = 0.0
        total_avant_marge = 0.0
        total_apres_marge = 0.0
        marge_init_amount = 0.0
        features_client = [
            {
                "id": getattr(it, "id", None),
                "description": getattr(it, "description", ""),
                "heures": _round(heures),
                "prix_client": 0.0,
            }
            for (it, heures, _c) in feature_costs_internal
        ]
        frais_fixes_client = [
            {
                "id": getattr(it, "id", None),
                "description": getattr(it, "description", ""),
                "cost_per_unit": _round(cost),
                "prix_client": 0.0,
            }
            for (it, cost) in fixed_costs_internal
        ]
    else:
        total_final = base * (1.0 + marge_init_pct) / divisor
        closing = (
            (1.0 + marge_init_pct) * closer_pct * base / divisor
        )
        total_avant_marge = base + closing
        total_apres_marge = total_final  # alias humain
        marge_init_amount = total_final - total_avant_marge

        # 4. Vue client — répartition proportionnelle
        # Les features absorbent (couts_dev + cout_manager + closing)
        # au prorata de leurs coûts dev internes, puis on applique la
        # marge. Les frais fixes ne portent que la marge.
        features_pool_before_margin = couts_dev + cout_manager + closing
        features_client = []
        for (it, heures, cout) in feature_costs_internal:
            if couts_dev > 0:
                part = cout / couts_dev
            else:
                part = 0.0
            prix = part * features_pool_before_margin * (1.0 + marge_init_pct)
            features_client.append(
                {
                    "id": getattr(it, "id", None),
                    "description": getattr(it, "description", ""),
                    "heures": _round(heures),
                    "prix_client": _round(prix),
                }
            )

        frais_fixes_client = []
        for (it, cost) in fixed_costs_internal:
            prix = cost * (1.0 + marge_init_pct)
            frais_fixes_client.append(
                {
                    "id": getattr(it, "id", None),
                    "description": getattr(it, "description", ""),
                    "cost_per_unit": _round(cost),
                    "prix_client": _round(prix),
                }
            )

    # Vérification d'invariance : la somme des prix clients doit égaler
    # le total final (à 1 cent près). Si l'écart est plus grand qu'EPS,
    # on absorbe la différence sur la dernière feature pour rester
    # cohérent avec le total affiché.
    if not is_invalid and (features_client or frais_fixes_client):
        sum_client = sum(f["prix_client"] for f in features_client) + sum(
            ff["prix_client"] for ff in frais_fixes_client
        )
        delta = _round(total_final - sum_client)
        if abs(delta) > 0 and features_client:
            features_client[-1]["prix_client"] = _round(
                features_client[-1]["prix_client"] + delta
            )
        elif abs(delta) > 0 and frais_fixes_client:
            frais_fixes_client[-1]["prix_client"] = _round(
                frais_fixes_client[-1]["prix_client"] + delta
            )

    initial_block = {
        "couts_dev": _round(couts_dev),
        "cout_manager": _round(cout_manager),
        "frais_fixes_total": _round(frais_fixes_total),
        "base": _round(base),
        "closing": _round(closing),
        "total_avant_marge": _round(total_avant_marge),
        "total_apres_marge": _round(total_apres_marge),
        "total_final": _round(total_final),
        "marge_amount": _round(marge_init_amount),
        "marge_pct": _round(marge_init_pct * 100, 4),
        "closer_pct": _round(closer_pct * 100, 4),
        "taux_dev_horaire": _round(taux_dev),
        "taux_manager_horaire": _round(taux_manager),
        "heures_manager": _round(heures_manager),
        "features_client": features_client,
        "frais_fixes_client": frais_fixes_client,
    }

    return {
        "is_invalid": is_invalid,
        "recurring": recurring_block,
        "initial": initial_block,
    }
