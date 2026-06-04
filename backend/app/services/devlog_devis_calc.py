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

----------------------------------------------------------------------
Refonte 2026-06 (Phase 2 → Phase 3) — MODULE + chargé de projet GLOBAL
----------------------------------------------------------------------

Un module regroupe UNIQUEMENT des **fonctionnalités**
(``item_kind = feature``) : vue client, heures de dev → coût =
heures × ``taux_dev``. C'est la seule nature d'item filtrée par la
sélection des modules et concernée par la gratuité.

Les **tâches de chargé de projet** (``item_kind = manager_task``) sont
désormais **centralisées et globales** : elles ne sont PLUS rattachées
à un module (``module_id`` NULL) et leur coût s'ajoute TOUJOURS au
total, peu importe la sélection du client. La gestion de projet est une
charge globale du projet, pas une option par fonctionnalité.

Coût interne d'un module = Σ(heures features × taux_dev). Le coût du
chargé de projet (Σ heures tâches × taux_manager) s'ajoute au global,
puis la marge et la commission closer s'appliquent, comme avant.

Leviers (tous **rétrocompatibles**) :

* **Sélection** : un module porte ``selected``. Les **features** d'un
  module NON sélectionné sont exclues du total. Les items SANS module
  (``module_id`` NULL — soumissions legacy, frais fixes, sections
  récurrentes, tâches du chargé de projet) sont TOUJOURS comptés.
* **Coût manager par tâches (GLOBAL)** : si la soumission possède au
  moins un item ``manager_task``, le coût manager =
  Σ(toutes les tâches × taux_manager), SANS filtre de module ni de
  sélection. Sinon (aucun ``manager_task``), on retombe EXACTEMENT sur
  le scalaire historique ``heures_manager × taux_manager``.
* **Gratuité « module → module »** : un module peut porter un
  ``free_when_module_id``. Si le module déclencheur est *sélectionné*,
  ce module devient **gratuit** : son prix CLIENT est 0 (features
  marquées « offert », heures visibles côté interne), mais — voir
  ci-dessous — son COÛT interne reste facturé indirectement. Si le
  déclencheur n'est PAS sélectionné, le module garde son prix normal.
  La gratuité ne touche jamais le chargé de projet (global).

----------------------------------------------------------------------
Refonte 2026-06 (Phase 4) — le CADEAU est RECHARGÉ sur les payants
----------------------------------------------------------------------

Auparavant un module offert était totalement ignoré du calcul : son
coût n'entrait pas dans la Base et son prix client valait 0 — le cadeau
ne coûtait rien à personne. **Ce n'est plus le cas.**

Désormais le coût d'un module offert (Σ heures features × ``taux_dev``)
ENTRE dans la Base comme n'importe quel coût, donc dans le
``Total_final``. Le prix CLIENT du module offert reste 0 (« Offert »),
mais le ``Total_final`` — gonflé par ce coût — est réparti **uniquement
sur les features des modules PAYANTS** (au prorata de leurs coûts dev).
Conséquence : les modules payants « absorbent » le coût du cadeau, leur
prix client augmente, et **la marge est préservée**. Le client paie le
cadeau indirectement, via les modules payants.

Deux notions de coût dev cohabitent donc :

* ``couts_dev``          : Σ coûts dev de TOUTES les features retenues
  (payantes ET offertes) → alimente la Base / le ``Total_final``.
* ``couts_dev_payants``  : Σ coûts dev des SEULES features payantes →
  dénominateur du prorata de répartition client. Les features offertes
  reçoivent un prix client 0 et n'absorbent rien ; ce sont les payantes
  qui se partagent le pool ``couts_dev + cout_manager + closing``
  (offert inclus dans ``couts_dev``).

Invariant CONSERVÉ :

       Σ(prix_features_payantes) + Σ(prix_fixes_client) = Total_final

(les offertes contribuent 0 au prix client mais leur coût est bien dans
le ``Total_final``).

CAS LIMITE « tout offert » — si TOUS les modules retenus sont offerts
(``couts_dev_payants == 0`` alors qu'un coût d'offert existe), aucun
module payant ne peut absorber le cadeau. On ne peut recharger nulle
part sans casser l'invariant ni risquer une division par zéro. Dans ce
seul cas on RETOMBE sur l'ancien comportement : le coût des offerts est
EXCLU de la Base (le cadeau redevient « gratuit pour tout le monde »),
``Total_final`` reste porté par les frais fixes / le manager, pas de
crash.

RÉTROCOMPATIBILITÉ — une soumission SANS modules et SANS ``manager_task``
emprunte exactement le chemin historique : tous les items comptés,
coût manager = ``heures_manager × taux_manager``, mêmes totaux au cent
près. ``modules`` est un paramètre optionnel : les appelants existants
(2 arguments) ne changent pas de comportement.
"""

from decimal import Decimal
from typing import Any, Iterable, Optional


# Tolérance d'arrondi pour les comparaisons finales (cents).
_EPS = 0.01

# Taxes Québec — appliquées sur le total final (qui inclut déjà la
# commission closer et la marge). Le 10% closer reste calculé AVANT
# taxes : l'assiette taxable inclut le closer, et les taxes sont
# appliquées par-dessus.
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
    """Arrondit en évitant les ``-0.00`` cosmétiques."""
    rounded = round(value, ndigits)
    if rounded == 0:
        return 0.0
    return rounded


def _resolve_module_states(
    modules: Optional[Iterable[Any]],
) -> tuple[dict[int, Any], set[int], set[int]]:
    """Calcule l'état de chaque module à partir de la liste fournie.

    Retourne ``(modules_by_id, selected_ids, free_ids)`` où :

    * ``modules_by_id`` : map id → instance module ;
    * ``selected_ids``  : ids des modules ``selected = True`` ;
    * ``free_ids``      : ids des modules gratuits (un module est
      gratuit s'il porte un ``free_when_module_id`` pointant vers un
      module présent ET sélectionné). Un module non sélectionné n'est
      jamais "gratuit" au sens client : il est carrément exclu.
    """
    modules_by_id: dict[int, Any] = {}
    selected_ids: set[int] = set()
    if modules:
        for m in modules:
            mid = getattr(m, "id", None)
            if mid is None:
                continue
            modules_by_id[mid] = m
            # ``selected`` par défaut True (rétrocompat : un module sans
            # attribut explicite est considéré sélectionné).
            if bool(getattr(m, "selected", True)):
                selected_ids.add(mid)

    free_ids: set[int] = set()
    for mid, m in modules_by_id.items():
        if mid not in selected_ids:
            # Module non sélectionné : exclu, pas "gratuit".
            continue
        trigger = getattr(m, "free_when_module_id", None)
        if trigger is None:
            continue
        # Gratuit seulement si le déclencheur existe ET est sélectionné.
        if trigger in selected_ids:
            free_ids.add(mid)

    return modules_by_id, selected_ids, free_ids


def compute_devis(
    soumission: Any,
    items: Iterable[Any],
    modules: Optional[Iterable[Any]] = None,
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
        ``item_kind`` : ``recurring_cost`` / ``feature`` /
        ``manager_task`` / ``fixed_cost``.
    modules
        Iterable optionnel de ``DevlogSoumissionModule``. Sert à
        filtrer par sélection et à appliquer la gratuité « module →
        module ». ``None`` (défaut) = chemin legacy : aucun filtrage,
        tous les items comptés (rétrocompat stricte).

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

    # --- État des modules (sélection + gratuité) ------------------------
    modules_by_id, selected_ids, free_ids = _resolve_module_states(modules)

    def _module_excluded(it: Any) -> bool:
        """Un item est exclu du total s'il appartient à un module connu
        NON sélectionné. Les items sans module (module_id NULL) ou
        rattachés à un module inconnu restent comptés (rétrocompat)."""
        mid = getattr(it, "module_id", None)
        if mid is None:
            return False
        if mid not in modules_by_id:
            # Module référencé mais absent de la liste fournie : on ne
            # peut pas juger -> on compte (comportement legacy sûr).
            return False
        return mid not in selected_ids

    def _module_free(it: Any) -> bool:
        """Un item est gratuit (prix client 0) s'il appartient à un
        module gratuit."""
        mid = getattr(it, "module_id", None)
        if mid is None:
            return False
        return mid in free_ids

    # --- Tri par item_kind ----------------------------------------------
    recurring_items = []
    features = []
    manager_tasks = []
    fixed_costs = []
    for it in items:
        kind = getattr(it, "item_kind", "feature") or "feature"
        if kind == "recurring_cost":
            recurring_items.append(it)
        elif kind == "fixed_cost":
            fixed_costs.append(it)
        elif kind == "manager_task":
            manager_tasks.append(it)
        else:
            # ``feature`` (par défaut)
            features.append(it)

    # ================================================================
    # SECTION 1 — Frais Mensuels Récurrents
    # ================================================================
    # Les sections récurrentes ne sont PAS concernées par les modules :
    # on compte tous les coûts récurrents comme avant.
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

    # Taxes mensuelles — appliquées sur total_client_amount (qui inclut
    # déjà la marge). Le client paie HT + TPS + TVQ chaque mois.
    tps_mensuelle = total_client_recurring * TPS_RATE
    tvq_mensuelle = total_client_recurring * TVQ_RATE
    total_mensuel_client_taxe = total_client_recurring * TPS_TVQ_FACTOR

    recurring_block = {
        "total_owner_cost": _round(total_owner_recurring),
        "total_client_amount": _round(total_client_recurring),
        "marge_amount": _round(marge_rec_amount),
        "marge_pct": _round(marge_rec_pct * 100, 4),
        "items_breakdown": recurring_breakdown,
        # --- Taxes (Québec) -----------------------------------------
        "tps_amount": _round(tps_mensuelle),
        "tvq_amount": _round(tvq_mensuelle),
        "tps_pct": _round(TPS_RATE * 100, 4),
        "tvq_pct": _round(TVQ_RATE * 100, 4),
        "total_client_amount_taxe": _round(total_mensuel_client_taxe),
    }

    # ================================================================
    # SECTION 2 — Frais de Mise en Oeuvre (calcul circulaire)
    # ================================================================
    # Rappel rétrocompat : un item exclu (module non sélectionné) ne
    # contribue PAS à la base et n'apparaît pas dans la vue client.
    #
    # CHANGEMENT 2026-06 (Phase 4) : un item OFFERT (module gratuit)
    # contribue désormais son coût dev à la Base (``couts_dev``), comme
    # un item payant — le cadeau est rechargé. Son prix CLIENT reste 0
    # et il n'absorbe rien dans la répartition : ce sont les features
    # PAYANTES qui se partagent le pool. On suit donc deux totaux :
    #   * ``couts_dev``         : payants + offerts (→ Base / Total_final)
    #   * ``couts_dev_payants`` : payants seuls (→ dénominateur prorata)
    #
    # 1. Coûts internes des features
    couts_dev = 0.0
    couts_dev_payants = 0.0
    feature_costs_internal = []  # (item, heures, cout_dev_brut, free)
    for it in features:
        if _module_excluded(it):
            continue
        heures = _f(getattr(it, "heures", 0))
        free = _module_free(it)
        cout = heures * taux_dev
        # Le coût entre TOUJOURS dans la Base (payant comme offert).
        couts_dev += cout
        if not free:
            couts_dev_payants += cout
        feature_costs_internal.append((it, heures, cout, free))

    # CAS LIMITE « tout offert » : un coût d'offert existe mais AUCUNE
    # feature payante ne peut l'absorber (``couts_dev_payants == 0`` et
    # ``couts_dev > 0``). On ne peut recharger nulle part sans casser
    # l'invariant. On retombe sur l'ANCIEN comportement : le coût des
    # offerts est exclu de la Base (cadeau redevenu gratuit pour tous),
    # ce qui ramène ``couts_dev`` au total payant et évite toute
    # division par zéro ou ``Total_final`` non porté par un prix client.
    if couts_dev_payants <= 0 < couts_dev:
        couts_dev = couts_dev_payants

    # 1bis. Coût manager — GLOBAL : Σ(manager_task.heures × taux_manager)
    # sur TOUTES les tâches du chargé de projet, peu importe leur
    # ``module_id`` et peu importe la sélection des modules. La gestion
    # de projet est une charge globale du projet, indépendante des
    # fonctionnalités choisies par le client. RÉTROCOMPAT : si AUCUN item
    # ``manager_task`` n'existe dans la soumission, on retombe sur le
    # scalaire historique ``heures_manager × taux_manager``.
    manager_tasks_internal = []  # (item, heures, cout_brut, free)
    cout_manager_from_tasks = 0.0
    has_manager_tasks = len(manager_tasks) > 0
    for it in manager_tasks:
        # Pas de filtrage par module ni de gratuité : le chargé de projet
        # est centralisé et toujours compté (free=False par convention).
        heures = _f(getattr(it, "heures", 0))
        cout = heures * taux_manager
        cout_manager_from_tasks += cout
        manager_tasks_internal.append((it, heures, cout, False))

    if has_manager_tasks:
        cout_manager = cout_manager_from_tasks
    else:
        # Chemin LEGACY strict : scalaire global sur la soumission.
        cout_manager = heures_manager * taux_manager

    # 2. Frais fixes — sans module (toujours comptés, rétrocompat).
    frais_fixes_total = 0.0
    fixed_costs_internal = []  # (item, cost_brut)
    for it in fixed_costs:
        if _module_excluded(it):
            continue
        cost = _f(getattr(it, "cost_per_unit", 0))
        frais_fixes_total += cost
        fixed_costs_internal.append((it, cost))

    base = couts_dev + cout_manager + frais_fixes_total

    # 3. Validation
    divisor = 1.0 - (1.0 + marge_init_pct) * closer_pct
    is_invalid = divisor <= 0 or base <= 0

    # Helpers de sérialisation des heures de tâches (vue interne — pas
    # de prix client, jamais facturé directement).
    def _manager_tasks_payload():
        return [
            {
                "id": getattr(it, "id", None),
                "description": getattr(it, "description", ""),
                "heures": _round(heures),
                "module_id": getattr(it, "module_id", None),
                "offert": bool(free),
                "cout_interne": _round(cout),
            }
            for (it, heures, cout, free) in manager_tasks_internal
        ]

    # 4. Résolution circulaire (closing + total_final)
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
                "module_id": getattr(it, "module_id", None),
                "offert": bool(free),
            }
            for (it, heures, _c, free) in feature_costs_internal
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

        # 5. Vue client — répartition proportionnelle
        # Les features PAYANTES absorbent
        # (couts_dev + cout_manager + closing) — ``couts_dev`` inclut
        # désormais le coût des OFFERTS — au prorata de leurs SEULS
        # coûts dev payants (``couts_dev_payants``), puis on applique la
        # marge. Les frais fixes ne portent que la marge. Les features
        # offertes (module gratuit) reçoivent 0 et n'absorbent rien :
        # leur coût est rechargé sur les payantes via le pool.
        features_pool_before_margin = couts_dev + cout_manager + closing
        features_client = []
        for (it, heures, cout, free) in feature_costs_internal:
            if free:
                prix = 0.0
            elif couts_dev_payants > 0:
                part = cout / couts_dev_payants
                prix = (
                    part * features_pool_before_margin
                    * (1.0 + marge_init_pct)
                )
            else:
                prix = 0.0
            features_client.append(
                {
                    "id": getattr(it, "id", None),
                    "description": getattr(it, "description", ""),
                    "heures": _round(heures),
                    "prix_client": _round(prix),
                    "module_id": getattr(it, "module_id", None),
                    "offert": bool(free),
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
    # on absorbe la différence sur la dernière feature NON gratuite pour
    # rester cohérent avec le total affiché.
    if not is_invalid and (features_client or frais_fixes_client):
        sum_client = sum(f["prix_client"] for f in features_client) + sum(
            ff["prix_client"] for ff in frais_fixes_client
        )
        delta = _round(total_final - sum_client)
        if abs(delta) > 0:
            payable_features = [
                f for f in features_client if not f.get("offert")
            ]
            if payable_features:
                payable_features[-1]["prix_client"] = _round(
                    payable_features[-1]["prix_client"] + delta
                )
            elif frais_fixes_client:
                frais_fixes_client[-1]["prix_client"] = _round(
                    frais_fixes_client[-1]["prix_client"] + delta
                )

    # Taxes initiales — appliquées sur total_final (qui inclut déjà
    # commission closer + marge). Le 10% closer reste calculé AVANT
    # taxes : l'assiette taxable inclut le closer.
    tps_initiale = total_final * TPS_RATE
    tvq_initiale = total_final * TVQ_RATE
    total_initial_taxe = total_final * TPS_TVQ_FACTOR

    # --- Détail par module (lecture) ------------------------------------
    # Pour chaque module connu : ses features (heures dev), totaux
    # d'heures, prix client, état ``selected`` et ``offert``. Les tâches
    # du chargé de projet sont désormais GLOBALES (module_id NULL) :
    # ``task_by_module`` reste vide pour les nouvelles soumissions et ne
    # capte que d'éventuelles tâches legacy encore rattachées à un module
    # (total_heures_manager = 0 sinon).
    feature_client_by_id = {
        f.get("id"): f for f in features_client if f.get("id") is not None
    }
    modules_detail = []
    # Indexe heures par module pour features et tâches.
    if modules_by_id:
        feat_by_module: dict[int, list] = {}
        for (it, heures, cout, free) in feature_costs_internal:
            mid = getattr(it, "module_id", None)
            if mid is not None:
                feat_by_module.setdefault(mid, []).append(
                    (it, heures, cout, free)
                )
        task_by_module: dict[int, list] = {}
        for (it, heures, cout, free) in manager_tasks_internal:
            mid = getattr(it, "module_id", None)
            if mid is not None:
                task_by_module.setdefault(mid, []).append(
                    (it, heures, cout, free)
                )
        for mid, m in modules_by_id.items():
            is_selected = mid in selected_ids
            is_free = mid in free_ids
            mod_feats = feat_by_module.get(mid, [])
            mod_tasks = task_by_module.get(mid, [])
            total_heures_dev = sum(h for (_i, h, _c, _f) in mod_feats)
            total_heures_manager = sum(h for (_i, h, _c, _f) in mod_tasks)
            # Prix client du module = somme des prix client de ses
            # features (0 si gratuit ou non sélectionné/exclu).
            prix_client_module = 0.0
            if is_selected and not is_free:
                for (it, _h, _c, _free) in mod_feats:
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
                        for (it, h, _c, _free) in mod_feats
                    ],
                    "manager_tasks": [
                        {
                            "id": getattr(it, "id", None),
                            "description": getattr(it, "description", ""),
                            "heures": _round(h),
                        }
                        for (it, h, _c, _free) in mod_tasks
                    ],
                }
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
        # --- Tâches de chargé de projet (vue interne) ---------------
        "manager_tasks": _manager_tasks_payload(),
        # --- Détail par module (lecture, vide en mode legacy) -------
        "modules": modules_detail,
        # --- Taxes (Québec) -----------------------------------------
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
