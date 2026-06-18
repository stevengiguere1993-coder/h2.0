"""Moteur de calcul des soumissions « devis_dev ».

REFONTE 2026-06 — INVARIANT « prix de ligne autonome »
======================================================
Le prix CLIENT de chaque ligne (module, fonctionnalité directe, frais
fixe) ne dépend QUE de ses propres heures. Décocher un module ne change
le prix d'AUCUNE autre ligne. Fini la répartition proportionnelle d'un
pool $ (gestionnaire / cadeaux) sur les modules cochés, qui faisait
varier le prix des autres lignes au gré de la sélection.

Frais mensuels récurrents
-------------------------
    Total_mensuel_client = Σ(items.cost_per_unit) × (1 + marge_rec)
La marge mensuelle s'applique à la somme des coûts ; aucune commission
closer (paiement récurrent).

Investissement initial (mise en oeuvre)
---------------------------------------
* **Gestion de projet = pourcentage baked-in.** On ne traite plus le
  coût du chargé de projet comme un montant fixe redistribué. On le
  convertit en un pourcentage ``pm_pct`` = (coût manager global) /
  (coût dev de TOUTES les features de la soumission). Ce pourcentage est
  une CONSTANTE de la soumission (numérateur et dénominateur indépendants
  de la sélection client) : on l'applique aux heures propres de chaque
  ligne. Résultat : la gestion de projet devient proportionnelle au scope
  automatiquement, et retirer un module n'affecte aucune autre ligne.
  Aucune ligne « gestion de projet » nue côté client.

* **Marge + closer par ligne.** On applique à chaque ligne le facteur
      K = (1 + marge_init) / (1 - (1 + marge_init) × closer_pct)
  qui intègre la marge initiale et la commission closer (résolution
  circulaire : le closer est un % du total final). Comme K est linéaire,
  Σ(prix des lignes) = Total_final exactement.

* **Sélection.** Un module porte ``selected`` ; les features d'un module
  NON sélectionné sont exclues (ni base, ni vue client). Les items sans
  module (``module_id`` NULL) — « fonctionnalités directes / Autres
  fonctionnalités », frais fixes — sont toujours comptés.

* **Gratuité « module → module » (cadeau).** Un module peut porter
  ``free_when_module_id``. Si le module déclencheur est SÉLECTIONNÉ, ce
  module devient « offert » (prix client 0, listé « Offert »). Le COÛT
  d'un module « giftable » (qui porte un ``free_when_module_id``) est
  BAKÉ en permanence dans le bloc « fonctionnalités directes » (ligne
  stable), JAMAIS redistribué sur les modules payants. Conséquence
  voulue : si le client décoche le module déclencheur, le module offert
  redevient payant et est facturé via sa PROPRE ligne — en plus du coût
  déjà baké dans les fonctionnalités directes (double), de sorte que le
  prix des fonctionnalités directes ne bouge jamais.

* **Frais fixes** : prix = coût × K (stables, indépendants de la
  sélection).

RÉTROCOMPATIBILITÉ — une soumission SANS modules et SANS ``manager_task``
emprunte le chemin legacy : tous les items comptés, coût manager =
``heures_manager`` scalaire × ``taux_manager``. ``modules=None`` (défaut)
=> aucun filtrage. Les totaux agrégés (couts_dev, cout_manager, base,
total_final) restent identiques à l'ancien moteur sur ce chemin.
"""

from decimal import Decimal
from typing import Any, Iterable, Optional


# Tolérance d'arrondi pour les comparaisons finales (cents).
_EPS = 0.01

# Taxes Québec — appliquées sur le total final (qui inclut déjà la
# commission closer et la marge).
TPS_RATE = 0.05
TVQ_RATE = 0.09975
TPS_TVQ_FACTOR = 1.0 + TPS_RATE + TVQ_RATE  # 1.14975


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
    rounded = round(_f(value), ndigits)
    if rounded == 0:
        return 0.0
    return rounded


def _resolve_module_states(modules: Optional[Iterable[Any]]):
    """Retourne ``(modules_by_id, selected_ids, free_ids, giftable_ids)``.

    * ``selected_ids`` : modules ``selected = True`` ;
    * ``free_ids`` : modules OFFERTS (un ``free_when_module_id`` pointant
      vers un module présent ET sélectionné, le module lui-même étant
      sélectionné) ;
    * ``giftable_ids`` : modules qui PORTENT un ``free_when_module_id``
      pointant vers un module présent — indépendamment de l'état du
      déclencheur. Leur coût est baké dans les fonctionnalités directes.
    """
    modules_by_id: dict[int, Any] = {}
    selected_ids: set[int] = set()
    if modules:
        for m in modules:
            mid = getattr(m, "id", None)
            if mid is None:
                continue
            modules_by_id[mid] = m
            if getattr(m, "selected", True):
                selected_ids.add(mid)

    free_ids: set[int] = set()
    giftable_ids: set[int] = set()
    for mid, m in modules_by_id.items():
        trigger = getattr(m, "free_when_module_id", None)
        if trigger is None or trigger not in modules_by_id:
            continue
        giftable_ids.add(mid)
        # Offert (prix client 0) seulement si CE module est sélectionné
        # ET le déclencheur est sélectionné.
        if mid in selected_ids and trigger in selected_ids:
            free_ids.add(mid)
    return modules_by_id, selected_ids, free_ids, giftable_ids


def compute_devis(
    soumission: Any,
    items: Iterable[Any],
    modules: Optional[Iterable[Any]] = None,
) -> dict:
    """Calcule la décomposition d'un devis « devis_dev ».

    ``modules=None`` => chemin legacy (aucun filtrage de sélection ni
    gratuité ; coût manager = scalaire ``heures_manager``).
    """
    # --- Paramètres avec defaults ---------------------------------------
    marge_rec_pct = _f(soumission.marge_recurrente_pct, 50.0) / 100.0
    marge_init_pct = _f(soumission.marge_initiale_pct, 50.0) / 100.0
    closer_pct = _f(soumission.commission_closer_pct, 10.0) / 100.0
    taux_dev = _f(soumission.taux_dev_horaire, 75.0)
    taux_manager = _f(soumission.taux_manager_horaire, 80.0)
    heures_manager = _f(soumission.heures_manager, 0.0)

    modules_by_id, selected_ids, free_ids, giftable_ids = (
        _resolve_module_states(modules)
    )

    def _module_excluded(it: Any) -> bool:
        mid = getattr(it, "module_id", None)
        if mid is None or mid not in modules_by_id:
            return False
        return mid not in selected_ids

    def _module_free(it: Any) -> bool:
        mid = getattr(it, "module_id", None)
        if mid is None:
            return False
        return mid in free_ids

    # --- Tri par item_kind ----------------------------------------------
    recurring_items, features, manager_tasks, fixed_costs = [], [], [], []
    for it in items:
        kind = getattr(it, "item_kind", "feature") or "feature"
        if kind == "recurring_cost":
            recurring_items.append(it)
        elif kind == "fixed_cost":
            fixed_costs.append(it)
        elif kind == "manager_task":
            manager_tasks.append(it)
        else:
            features.append(it)

    # ================================================================
    # SECTION 1 — Frais Mensuels Récurrents (inchangé)
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
    tps_mensuelle = total_client_recurring * TPS_RATE
    tvq_mensuelle = total_client_recurring * TVQ_RATE
    total_mensuel_client_taxe = total_client_recurring * TPS_TVQ_FACTOR
    recurring_block = {
        "total_owner_cost": _round(total_owner_recurring),
        "total_client_amount": _round(total_client_recurring),
        "marge_amount": _round(marge_rec_amount),
        "marge_pct": _round(marge_rec_pct * 100, 4),
        "items_breakdown": recurring_breakdown,
        "tps_amount": _round(tps_mensuelle),
        "tvq_amount": _round(tvq_mensuelle),
        "tps_pct": _round(TPS_RATE * 100, 4),
        "tvq_pct": _round(TVQ_RATE * 100, 4),
        "total_client_amount_taxe": _round(total_mensuel_client_taxe),
    }

    # ================================================================
    # SECTION 2 — Investissement initial (prix de ligne autonome)
    # ================================================================

    # 1. Coût manager GLOBAL → converti en pourcentage baked-in.
    has_manager_tasks = len(manager_tasks) > 0
    manager_tasks_internal = []  # (item, heures, cout, free=False)
    cout_manager_global = 0.0
    for it in manager_tasks:
        heures = _f(getattr(it, "heures", 0))
        cout = heures * taux_manager
        cout_manager_global += cout
        manager_tasks_internal.append((it, heures, cout, False))
    if not has_manager_tasks:
        cout_manager_global = heures_manager * taux_manager

    # Coût dev de TOUTES les features (dénominateur du %, indépendant de
    # la sélection) — c'est ce qui rend ``pm_pct`` stable.
    couts_dev_all = sum(
        _f(getattr(it, "heures", 0)) * taux_dev for it in features
    )
    pm_pct = (cout_manager_global / couts_dev_all) if couts_dev_all > 0 else 0.0
    pm_factor = 1.0 + pm_pct

    # 2. Classement des features + coûts.
    couts_dev_paying_raw = 0.0  # features payantes sélectionnées (dev brut)
    gift_raw = 0.0              # dev brut des features de modules giftables
    feature_costs_internal = []  # (it, heures, dev_raw, status, offert)
    for it in features:
        heures = _f(getattr(it, "heures", 0))
        dev_raw = heures * taux_dev
        mid = getattr(it, "module_id", None)
        excluded = _module_excluded(it)
        offert = _module_free(it)
        if mid in giftable_ids:
            # Coût baké en permanence dans les fonctionnalités directes.
            gift_raw += dev_raw
        if excluded:
            status = "exclu"
        elif offert:
            status = "offert"
        else:
            status = "pay"
            couts_dev_paying_raw += dev_raw
        feature_costs_internal.append((it, heures, dev_raw, status, offert))

    # 3. Frais fixes (sans module, toujours comptés).
    frais_fixes_total = 0.0
    fixed_costs_internal = []  # (item, cost)
    for it in fixed_costs:
        if _module_excluded(it):
            continue
        cost = _f(getattr(it, "cost_per_unit", 0))
        frais_fixes_total += cost
        fixed_costs_internal.append((it, cost))

    # Reporting cohérent : couts_dev (brut payant + cadeau baké),
    # cout_manager (part baked-in correspondante), base.
    couts_dev_report = couts_dev_paying_raw + gift_raw
    cout_manager_report = couts_dev_report * pm_pct
    # Cas dégénéré : aucune feature mais un coût manager existe → on le
    # bascule en frais fixe pour ne pas le perdre (rare).
    extra_manager_fixed = 0.0
    if couts_dev_all <= 0 and cout_manager_global > 0:
        extra_manager_fixed = cout_manager_global
    base = (
        couts_dev_report * pm_factor
        + frais_fixes_total
        + extra_manager_fixed
    )

    divisor = 1.0 - (1.0 + marge_init_pct) * closer_pct
    is_invalid = divisor <= 0 or base <= 0
    K = ((1.0 + marge_init_pct) / divisor) if not is_invalid else 0.0

    def _manager_tasks_payload():
        return [
            {
                "id": getattr(it, "id", None),
                "description": getattr(it, "description", ""),
                "heures": _round(heures),
                "module_id": getattr(it, "module_id", None),
                "offert": False,
                "cout_interne": _round(cout),
            }
            for (it, heures, cout, _free) in manager_tasks_internal
        ]

    # 4. Totaux circulaires.
    if is_invalid:
        total_final = closing = total_avant_marge = 0.0
        total_apres_marge = marge_init_amount = 0.0
        features_client = [
            {
                "id": getattr(it, "id", None),
                "description": getattr(it, "description", ""),
                "heures": _round(heures),
                "prix_client": 0.0,
                "module_id": getattr(it, "module_id", None),
                "offert": bool(offert),
            }
            for (it, heures, _d, status, offert) in feature_costs_internal
            if status != "exclu"
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
        total_final = base * K
        closing = (1.0 + marge_init_pct) * closer_pct * base / divisor
        total_avant_marge = base + closing
        total_apres_marge = total_final
        marge_init_amount = total_final - total_avant_marge

        # Prix client par ligne — fonction des SEULES heures de la ligne.
        features_client = []
        for (it, heures, dev_raw, status, offert) in feature_costs_internal:
            if status == "exclu":
                continue
            prix = 0.0 if status != "pay" else dev_raw * pm_factor * K
            features_client.append(
                {
                    "id": getattr(it, "id", None),
                    "description": getattr(it, "description", ""),
                    "heures": _round(heures),
                    "prix_client": _round(prix),
                    "module_id": getattr(it, "module_id", None),
                    "offert": bool(offert),
                }
            )

        # Cadeau (modules giftables) baké dans les fonctionnalités
        # DIRECTES (module_id NULL). Réparti au prorata des heures des
        # features directes payantes ; à défaut, ligne directe synthétique.
        gift_client = gift_raw * pm_factor * K
        if gift_client > 0:
            direct = [
                f
                for f in features_client
                if f.get("module_id") is None
                and not f.get("offert")
            ]
            direct_dev = sum(
                _f(d.get("heures")) for d in direct
            )
            if direct and direct_dev > 0:
                running = 0.0
                for d in direct[:-1]:
                    part = (_f(d.get("heures")) / direct_dev) * gift_client
                    running += _round(part)
                    d["prix_client"] = _round(d["prix_client"] + part)
                direct[-1]["prix_client"] = _round(
                    direct[-1]["prix_client"] + (gift_client - running)
                )
            else:
                # Aucune feature directe : ligne synthétique stable.
                features_client.append(
                    {
                        "id": None,
                        "description": "Mise en place et inclusions",
                        "heures": 0.0,
                        "prix_client": _round(gift_client),
                        "module_id": None,
                        "offert": False,
                    }
                )

        frais_fixes_client = []
        for (it, cost) in fixed_costs_internal:
            frais_fixes_client.append(
                {
                    "id": getattr(it, "id", None),
                    "description": getattr(it, "description", ""),
                    "cost_per_unit": _round(cost),
                    "prix_client": _round(cost * K),
                }
            )

    # Absorption du résidu d'arrondi sur la dernière ligne payante pour
    # garantir Σ(prix client) == total_final au cent près.
    if not is_invalid and (features_client or frais_fixes_client):
        sum_client = sum(f["prix_client"] for f in features_client) + sum(
            ff["prix_client"] for ff in frais_fixes_client
        )
        delta = _round(total_final - sum_client)
        if abs(delta) > 0:
            payable = [
                f
                for f in features_client
                if not f.get("offert") and f["prix_client"] > 0
            ]
            if payable:
                payable[-1]["prix_client"] = _round(
                    payable[-1]["prix_client"] + delta
                )
            elif frais_fixes_client:
                frais_fixes_client[-1]["prix_client"] = _round(
                    frais_fixes_client[-1]["prix_client"] + delta
                )

    tps_initiale = total_final * TPS_RATE
    tvq_initiale = total_final * TVQ_RATE
    total_initial_taxe = total_final * TPS_TVQ_FACTOR

    # --- Détail par module (lecture) ------------------------------------
    feature_client_by_id = {
        f.get("id"): f for f in features_client if f.get("id") is not None
    }
    modules_detail = []
    if modules_by_id:
        feat_by_module: dict[int, list] = {}
        for (it, heures, dev_raw, status, offert) in feature_costs_internal:
            mid = getattr(it, "module_id", None)
            if mid is not None:
                feat_by_module.setdefault(mid, []).append(
                    (it, heures, dev_raw, status, offert)
                )
        task_by_module: dict[int, list] = {}
        for (it, heures, cout, _free) in manager_tasks_internal:
            mid = getattr(it, "module_id", None)
            if mid is not None:
                task_by_module.setdefault(mid, []).append(
                    (it, heures, cout)
                )
        for mid, m in modules_by_id.items():
            is_selected = mid in selected_ids
            is_free = mid in free_ids
            mod_feats = feat_by_module.get(mid, [])
            mod_tasks = task_by_module.get(mid, [])
            total_heures_dev = sum(h for (_i, h, _d, _s, _o) in mod_feats)
            total_heures_manager = sum(h for (_i, h, _c) in mod_tasks)
            prix_client_module = 0.0
            if is_selected and not is_free:
                for (it, _h, _d, _s, _o) in mod_feats:
                    fc = feature_client_by_id.get(getattr(it, "id", None))
                    if fc is not None:
                        prix_client_module += fc.get("prix_client", 0.0)
            modules_detail.append(
                {
                    "id": mid,
                    "name": getattr(m, "name", None),
                    "selected": is_selected,
                    "offert": is_free,
                    "free_when_module_id": getattr(
                        m, "free_when_module_id", None
                    ),
                    "total_heures_dev": _round(total_heures_dev),
                    "total_heures_manager": _round(total_heures_manager),
                    "prix_client": _round(prix_client_module),
                    "features": [
                        {
                            "id": getattr(it, "id", None),
                            "description": getattr(it, "description", ""),
                            "heures": _round(h),
                        }
                        for (it, h, _d, _s, _o) in mod_feats
                    ],
                    "manager_tasks": [
                        {
                            "id": getattr(it, "id", None),
                            "description": getattr(it, "description", ""),
                            "heures": _round(h),
                        }
                        for (it, h, _c) in mod_tasks
                    ],
                }
            )

    initial_block = {
        "couts_dev": _round(couts_dev_report),
        "cout_manager": _round(cout_manager_report + extra_manager_fixed),
        "pm_pct": _round(pm_pct * 100, 4),
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
        "manager_tasks": _manager_tasks_payload(),
        "modules": modules_detail,
        "tps_amount": _round(tps_initiale),
        "tvq_amount": _round(tvq_initiale),
        "tps_pct": _round(TPS_RATE * 100, 4),
        "tvq_pct": _round(TVQ_RATE * 100, 4),
        "total_final_taxe": _round(total_initial_taxe),
    }

    return {
        "is_invalid": is_invalid,
        "recurring": recurring_block,
        "initial": initial_block,
    }
