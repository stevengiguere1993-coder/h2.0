"""Moteur d'analyse financière pour les leads (Phase 3 de l'analyse).

Réplique **exactement** la mécanique des 2 calculateurs Excel :
  - `CALCULATEUR_OFFICIEL.xlsm` (col D = SCHL Efficacité énergétique 50 pts)
  - `CALCULATEUR_OFFICIEL_APH_SELECT.xlsm` (col D = SCHL Abord + Eff 100 pts)

La spec complète est dans `lead_analysis_spec.md`. Tests unitaires
dans `tests/services/test_lead_analysis_finance.py` (cas Saint-Joseph).

Architecture :
    inputs (dict)
        ↓
    compute_typology_aggregates → H13, abord/PDM split (APH SELECT)
        ↓
    compute_each_scenario(achat, schl, aph_50, aph_100) → revenus, dépenses,
                                                          valeur éco, financement
        ↓
    compute_frais_demarrage → L4..L19 → B5
        ↓
    compute_final_outcomes → MDF, équité, best_refi
        ↓
    {full_results, best_refi_amount, best_refi_program}
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional


# ─── Barème des dépenses normalisées (K35..K44 dans l'Excel) ──────

BAREME: Dict[str, float] = {
    "concierge_lt12":  215.0,
    "concierge_gte12": 365.0,
    "entretien":       610.0,
    "gestion_lt12":    0.0425,
    "gestion_gte12":   0.05,
    "wifi_par_log":    5.0,
    "internet_fixe":   120.0,
    "thermopompe":     190.0,
}


# ─── Frais fixes (L7..L13) ─────────────────────────────────────────

FRAIS_FIXES: Dict[str, float] = {
    "evaluateur":         1500.0,
    "evaluateur_2":       1500.0,
    "inspection":         1700.0,
    "avocat":             4000.0,
    "notaire":            1600.0,
    "notaire_2":          1600.0,
    "rapport_efficacite": 4500.0,
}


# ─── Configurations par scénario (R50, R57, R59 dans Excel) ──────

@dataclass(frozen=True)
class ScenarioConfig:
    name: str
    label: str
    ltv: float        # ratio prêt/valeur
    amort_annees: int
    rcd: float        # ratio couverture de dette


SCENARIO_ACHAT = ScenarioConfig(
    name="achat", label="Achat conventionnel",
    ltv=0.75, amort_annees=25, rcd=1.20,
)
SCENARIO_REFI_SCHL = ScenarioConfig(
    name="refi_schl", label="SCHL standard",
    ltv=0.85, amort_annees=35, rcd=1.30,
)
SCENARIO_REFI_APH_50 = ScenarioConfig(
    name="refi_aph_50",
    label="SCHL Efficacité énergétique (50 pts)",
    ltv=0.85, amort_annees=40, rcd=1.10,
)
SCENARIO_REFI_APH_100 = ScenarioConfig(
    name="refi_aph_100",
    label="SCHL Abordabilité + Efficacité (100 pts)",
    ltv=0.95, amort_annees=50, rcd=1.10,
)

REFI_SCENARIOS: List[ScenarioConfig] = [
    SCENARIO_REFI_SCHL, SCENARIO_REFI_APH_50, SCENARIO_REFI_APH_100,
]


# ─── Helpers ───────────────────────────────────────────────────────


def taxes_bienvenue_mtl(prix_achat: float) -> float:
    """Taxes de bienvenue de Montréal (tiers progressifs 2024-2025).
    Cf. L6 dans l'Excel."""
    if prix_achat <= 0:
        return 0.0
    brackets = [
        (61_500,    0.005),
        (307_800,   0.010),
        (552_300,   0.015),
        (1_104_700, 0.020),
        (2_136_500, 0.025),
        (3_113_000, 0.035),
        (math.inf,  0.040),
    ]
    taxe = 0.0
    seuil_bas = 0.0
    for seuil_haut, taux in brackets:
        if prix_achat <= seuil_haut:
            taxe += (prix_achat - seuil_bas) * taux
            return taxe
        taxe += (seuil_haut - seuil_bas) * taux
        seuil_bas = seuil_haut
    return taxe  # never reached


def pv_canadian(
    rate_annual: float, n_months: int, payment_monthly: float
) -> float:
    """Valeur actualisée d'un flux de paiements mensuels avec
    intérêt composé semestriellement (convention canadienne).

    Réplique exactement Excel `PV((1+rate/2)^(1/6)-1, n*12, pmt/12)`.
    Retourne une valeur **négative** quand le paiement est positif
    (cf. Excel), donc on l'inverse pour la consommer en `hypothèque
    maximale = -PV(...)`.
    """
    if n_months <= 0:
        return 0.0
    if rate_annual == 0:
        return -payment_monthly * n_months
    rate_monthly = (1 + rate_annual / 2) ** (1 / 6) - 1
    if rate_monthly == 0:
        return -payment_monthly * n_months
    factor = (1 - (1 + rate_monthly) ** (-n_months)) / rate_monthly
    return -payment_monthly * factor


def pmt_canadian(
    rate_annual: float, n_months: int, principal: float
) -> float:
    """Paiement mensuel pour un prêt avec intérêt composé
    semestriellement (convention canadienne). Inverse de `pv_canadian`.

    Réplique Excel `PMT((1+rate/2)^(1/6)-1, n*12, -principal)`.
    Retourne une valeur **positive** = paiement mensuel à débourser.
    """
    if n_months <= 0 or principal <= 0:
        return 0.0
    if rate_annual == 0:
        return principal / n_months
    rate_monthly = (1 + rate_annual / 2) ** (1 / 6) - 1
    if rate_monthly == 0:
        return principal / n_months
    return principal * rate_monthly / (1 - (1 + rate_monthly) ** (-n_months))


# ─── Agrégats de typologie ─────────────────────────────────────────


@dataclass
class TypologyAggregates:
    h13_loyer_pondere: float        # = Σ (G[t] × H[t]) / nb_total
    nb_abordables: int              # ceil(0.40 × nb_total)
    nb_pdm: int                     # nb_total - nb_abordables
    nouveau_loyer_moyen_pdm: float  # algo: unités les plus chères


def compute_typology_aggregates(
    typologie: Dict[str, int],
    typologie_prix: Dict[str, float],
    nb_total: int,
) -> TypologyAggregates:
    """Calcule H13, nb_abordables, nouveau_loyer_moyen_pdm.

    `typologie` = { "2.5": 0, "3.5": 4, "4.5": 4, ... }
    `typologie_prix` = { "3.5": 1400, "4.5": 1600, ... } (uniquement
    pour les types avec quantité > 0).
    """
    if nb_total <= 0:
        return TypologyAggregates(0.0, 0, 0, 0.0)

    # H13 = moyenne pondérée des loyers.
    # On ne divise que par les unités QUI ONT UN PRIX SAISI — sinon
    # les unités sans prix font baisser artificiellement la moyenne
    # (cas : utilisateur saisit le prix pour 8 × 4.5 mais oublie
    # 4 × 5.5 → la moyenne tombait à 16800/12 = 1400 au lieu de
    # 16800/8 = 2100). Si TOUTES les typos ont un prix, le résultat
    # est strictement identique à total/nb_total.
    total_loyers = 0.0
    nb_with_price = 0
    for typo, qty in typologie.items():
        if qty <= 0:
            continue
        prix = float(typologie_prix.get(typo, 0) or 0)
        if prix > 0:
            total_loyers += qty * prix
            nb_with_price += qty
    h13 = (
        total_loyers / nb_with_price if nb_with_price > 0 else 0.0
    )

    # APH SELECT : nombre abordables = ceil(40 % × total)
    nb_abordables = math.ceil(0.40 * nb_total)
    nb_pdm = nb_total - nb_abordables

    # Loyer moyen PDM : on prend les unités les plus chères en
    # premier, jusqu'à atteindre nb_pdm. Moyenne pondérée du résultat.
    nouveau_loyer_pdm = 0.0
    if nb_pdm > 0:
        sorted_typos = sorted(
            [
                (typo, qty, float(typologie_prix.get(typo, 0) or 0))
                for typo, qty in typologie.items()
                if qty > 0
            ],
            key=lambda x: x[2],
            reverse=True,
        )
        restant = nb_pdm
        total_loyers_pdm = 0.0
        for _typo, qty, prix in sorted_typos:
            pris = min(restant, qty)
            total_loyers_pdm += pris * prix
            restant -= pris
            if restant == 0:
                break
        nouveau_loyer_pdm = (
            total_loyers_pdm / nb_pdm if nb_pdm > 0 else 0.0
        )

    return TypologyAggregates(
        h13_loyer_pondere=h13,
        nb_abordables=int(nb_abordables),
        nb_pdm=int(nb_pdm),
        nouveau_loyer_moyen_pdm=nouveau_loyer_pdm,
    )


# ─── Calcul des dépenses normalisées (R35..R46) ───────────────────


@dataclass
class DepensesBreakdown:
    inoccupation: float
    taxes_municipales: float
    taxes_scolaires: float
    assurances: float
    energie: float
    concierge: float
    entretien: float
    gestion: float
    wifi: float
    thermopompes: float
    autres: float

    @property
    def total(self) -> float:
        return (
            self.inoccupation + self.taxes_municipales + self.taxes_scolaires
            + self.assurances + self.energie + self.concierge
            + self.entretien + self.gestion + self.wifi
            + self.thermopompes + self.autres
        )


def compute_depenses_for_scenario(
    *,
    is_refi: bool,
    is_aph: bool,
    nb_log: int,
    revenus_totaux: float,
    taxes_municipales: float,
    taxes_scolaires: float,
    assurances: float,
    energie_base: float,
    reduction_energie_pct: float,
    depenses_autres: float,
    wifi_ajoute: bool,
    nb_thermopompes_ajoutees: int,
    taux_inoccupation_pct: float,
) -> DepensesBreakdown:
    """Calcule R35..R45 pour un scénario donné.

    `is_refi` : True pour SCHL/APH (vs achat).
    `is_aph`  : True pour les programmes APH (Efficacité énergétique),
                False pour SCHL standard. Détermine si les
                thermopompes sont incluses dans les dépenses.

    Différences :
      - Énergie : multipliée par (1 - reduction_pct) en refi.
      - WIFI    : ajouté en refi si wifi_ajoute (SCHL + APH).
      - Thermopompes : **uniquement en APH** (efficacité énergétique).
        Dans l'Excel R44 col C (SCHL) = D5×J43 avec J43 vide → 0.
        R44 col D (APH 50) = D5×K43 avec K43 = 190 $/thermopompe.
    """
    inoccupation = taux_inoccupation_pct * revenus_totaux

    concierge_par_log = (
        BAREME["concierge_lt12"] if nb_log < 12 else BAREME["concierge_gte12"]
    )
    concierge = concierge_par_log * nb_log
    entretien = nb_log * BAREME["entretien"]
    gestion_pct = (
        BAREME["gestion_lt12"] if nb_log < 12 else BAREME["gestion_gte12"]
    )
    gestion = gestion_pct * revenus_totaux

    if is_refi:
        energie = energie_base * (1.0 - reduction_energie_pct)
        wifi = (
            BAREME["wifi_par_log"] * nb_log * 12 + BAREME["internet_fixe"] * 12
            if wifi_ajoute
            else 0.0
        )
        # Thermopompes UNIQUEMENT en APH (pas SCHL standard).
        thermopompes = (
            nb_thermopompes_ajoutees * BAREME["thermopompe"]
            if is_aph
            else 0.0
        )
    else:
        energie = energie_base
        wifi = 0.0
        thermopompes = 0.0

    return DepensesBreakdown(
        inoccupation=inoccupation,
        taxes_municipales=taxes_municipales,
        taxes_scolaires=taxes_scolaires,
        assurances=assurances,
        energie=energie,
        concierge=concierge,
        entretien=entretien,
        gestion=gestion,
        wifi=wifi,
        thermopompes=thermopompes,
        autres=depenses_autres,
    )


# ─── Calcul de la valeur économique + financement par scénario ────


@dataclass
class ScenarioResult:
    config: ScenarioConfig
    nb_log: int
    loyer_mois: float
    revenus_totaux: float
    depenses: DepensesBreakdown
    revenus_net: float
    valeur_eco_tga: float
    hyp_max_tga: float
    paiement_hyp_max: float
    hyp_max_rcd: float
    valeur_eco_rcd: float
    valeur_marchande: Optional[float]
    hyp_max_vm: Optional[float]
    valeur_retenue: float
    financement: float
    # Paiement mensuel actuel sur le `financement` au `taux_interet`
    # du scénario, amortissement = `config.amort_annees` × 12 mois.
    paiement_mensuel_actuel: float = 0.0
    # Cashflow annuel = revenus_net − (paiement_mensuel_actuel × 12).
    # Représente ce qu'il reste en poche chaque année après le service
    # de la dette, en supposant qu'on emprunte le plein `financement`.
    cashflow_annuel: float = 0.0
    mdf_necessaire: Optional[float] = None
    equite_a_la_fin: Optional[float] = None


def compute_scenario(
    *,
    config: ScenarioConfig,
    nb_log: int,
    loyer_mois: float,
    revenus_totaux: float,
    depenses: DepensesBreakdown,
    tga: float,
    taux_interet: float,
    valeur_marchande: Optional[float] = None,
) -> ScenarioResult:
    """Calcule valeur économique + financement pour un scénario."""
    revenus_net = revenus_totaux - depenses.total

    # Valeur éco TGA (R54)
    valeur_eco_tga = revenus_net / tga if tga > 0 else 0.0
    hyp_max_tga = valeur_eco_tga * config.ltv

    # Valeur éco RCD (R61 → R63 → R62)
    paiement_hyp_max = (
        revenus_net / config.rcd if config.rcd > 0 else 0.0
    )
    hyp_max_rcd = -pv_canadian(
        rate_annual=taux_interet,
        n_months=config.amort_annees * 12,
        payment_monthly=paiement_hyp_max / 12.0,
    )
    valeur_eco_rcd = (
        hyp_max_rcd / config.ltv if config.ltv > 0 else 0.0
    )

    # Valeur marchande (R65) — uniquement pour la colonne Achat
    hyp_max_vm: Optional[float] = None
    if valeur_marchande is not None:
        hyp_max_vm = valeur_marchande * config.ltv

    # Valeur retenue (R68) :
    #   - Achat : min(valeur_marchande, valeur_eco_rcd, valeur_eco_tga)
    #   - Refi  : min(valeur_eco_rcd, valeur_eco_tga)
    eco_min = min(valeur_eco_rcd, valeur_eco_tga)
    if valeur_marchande is not None:
        valeur_retenue = min(valeur_marchande, eco_min)
    else:
        valeur_retenue = eco_min

    # Financement total (R69)
    financement = valeur_retenue * config.ltv

    # Paiement mensuel actuel sur le `financement` (au taux du
    # scénario, amortissement = config.amort_annees) + cashflow.
    paiement_mensuel_actuel = pmt_canadian(
        rate_annual=taux_interet,
        n_months=config.amort_annees * 12,
        principal=financement,
    )
    cashflow_annuel = revenus_net - paiement_mensuel_actuel * 12.0

    return ScenarioResult(
        config=config,
        nb_log=nb_log,
        loyer_mois=loyer_mois,
        revenus_totaux=revenus_totaux,
        depenses=depenses,
        revenus_net=revenus_net,
        valeur_eco_tga=valeur_eco_tga,
        hyp_max_tga=hyp_max_tga,
        paiement_hyp_max=paiement_hyp_max,
        hyp_max_rcd=hyp_max_rcd,
        valeur_eco_rcd=valeur_eco_rcd,
        valeur_marchande=valeur_marchande,
        hyp_max_vm=hyp_max_vm,
        valeur_retenue=valeur_retenue,
        financement=financement,
        paiement_mensuel_actuel=paiement_mensuel_actuel,
        cashflow_annuel=cashflow_annuel,
    )


# ─── Frais de démarrage (L4..L19) ──────────────────────────────────


@dataclass
class FraisDemarrage:
    courtier_hypothecaire_1: float
    courtier_hypothecaire_2: float
    taxes_bienvenue: float
    evaluateur: float
    evaluateur_2: float
    inspection: float
    avocat: float
    notaire: float
    notaire_2: float
    rapport_efficacite: float
    frais_developpement: float
    frais_negociations: float
    frais_travaux: float
    interets: float
    revenus_nets_pendant_projet: float

    @property
    def total(self) -> float:
        return sum(
            [
                self.courtier_hypothecaire_1,
                self.courtier_hypothecaire_2,
                self.taxes_bienvenue,
                self.evaluateur,
                self.evaluateur_2,
                self.inspection,
                self.avocat,
                self.notaire,
                self.notaire_2,
                self.rapport_efficacite,
                self.frais_developpement,
                self.frais_negociations,
                self.frais_travaux,
                self.interets,
                self.revenus_nets_pendant_projet,
            ]
        )


def compute_frais_demarrage(
    *,
    prix_achat: float,
    duree_projet_annees: int,
    revenus_net_achat: float,
    financement_aph_100: float,
    mdf_preteur_b_pct: float,
    taux_interet_preteur_b_projet: float,
    frais_developpement: float = 0.0,
    frais_negociations: float = 0.0,
    frais_travaux: float = 0.0,
) -> FraisDemarrage:
    """Calcule L4..L19. `financement_aph_100` est utilisé pour le
    courtier hyp. 2 (1 % du financement APH 100 pts, le plus généreux).
    L17 = intérêts pendant projet
        ((1 - mdf_preteur_b_pct) × prix × taux_interet_preteur_b_projet × durée).
    L18 = revenus nets pendant projet (négatif si net négatif)."""
    return FraisDemarrage(
        courtier_hypothecaire_1=0.01 * prix_achat,
        courtier_hypothecaire_2=0.01 * financement_aph_100,
        taxes_bienvenue=taxes_bienvenue_mtl(prix_achat),
        evaluateur=FRAIS_FIXES["evaluateur"],
        evaluateur_2=FRAIS_FIXES["evaluateur_2"],
        inspection=FRAIS_FIXES["inspection"],
        avocat=FRAIS_FIXES["avocat"],
        notaire=FRAIS_FIXES["notaire"],
        notaire_2=FRAIS_FIXES["notaire_2"],
        rapport_efficacite=FRAIS_FIXES["rapport_efficacite"],
        frais_developpement=frais_developpement,
        frais_negociations=frais_negociations,
        frais_travaux=frais_travaux,
        # L17 : (1 - mdf_preteur_b_pct) × prix × taux_interet_preteur_b_projet × durée
        interets=(1 - mdf_preteur_b_pct) * prix_achat * taux_interet_preteur_b_projet * duree_projet_annees,
        # L18 : -revenus_net_achat × durée (négatif = pas de revenu
        # pendant le projet, donc coût)
        revenus_nets_pendant_projet=-revenus_net_achat * duree_projet_annees,
    )


# ─── Pipeline complet ──────────────────────────────────────────────


@dataclass
class FinanceInputs:
    """Inputs unifiés pour les 2 calculateurs."""

    # B3..B14 (auto-importés + défauts)
    adresse: str = ""
    prix_achat: float = 0.0
    nombre_logements: int = 0
    revenus_annuels: float = 0.0
    taxes_municipales: float = 0.0
    taxes_scolaires: float = 0.0
    assurances: float = 0.0
    energie: float = 0.0
    depenses_autres: float = 0.0
    tga: float = 0.04
    taux_interet_achat: float = 0.04

    # D4..D9 (manuel + défauts)
    nb_logements_ajoutes: int = 0
    nb_thermopompes_ajoutees: int = 0
    wifi_ajoute: bool = True
    reduction_energie_pct: float = 0.0
    taux_interet_refi: float = 0.0

    # Typologie (G6..G12 auto, H6..H12 manuel)
    typologie: Dict[str, int] = field(default_factory=dict)
    typologie_prix: Dict[str, float] = field(default_factory=dict)

    # L (frais)
    duree_projet_annees: int = 2
    frais_developpement: float = 0.0
    frais_negociations: float = 0.0
    frais_travaux: float = 0.0

    # APH SELECT only (manuel)
    nouveau_loyer_abordable: float = 0.0

    # MDF prêteur B (en fraction, ex. 0.25 pour 25 %). Modifiable
    # selon le prêteur (peut monter à 0.35).
    mdf_preteur_b_pct: float = 0.25

    # Taux d'intérêt du prêteur B pendant la phase chantier
    # (8 % typique 2024-2025). Utilisé pour calculer L17 — intérêts
    # de portage pendant projet.
    taux_interet_preteur_b_projet: float = 0.08

    # Taux d'inoccupation hypothèse SCHL standard (3 %). Varie selon
    # le marché (Montréal centre vs régions). Appliqué aux revenus
    # totaux pour calculer la perte de loyer R35.
    taux_inoccupation_pct: float = 0.03

    # Overrides manuels des postes de frais de démarrage. Dict
    # `{ "evaluateur": 1800, "inspection": 2000, ... }` — chaque clé
    # présente remplace la valeur calculée par défaut. Keys autorisées
    # = attributs de `FraisDemarrage` dataclass.
    frais_demarrage_overrides: Dict[str, float] = field(default_factory=dict)

    # Liste des postes de frais de démarrage finançables par prêteur B.
    # Pour ces postes, on paie seulement `mdf_preteur_b_pct` en cash,
    # le reste s'ajoute au prêt. Défaut : rapport_efficacite,
    # frais_developpement, frais_travaux.
    frais_demarrage_financables: list[str] = field(default_factory=list)


@dataclass
class FinanceResults:
    """Sortie consolidée du moteur (3 scénarios refi + achat)."""

    inputs: FinanceInputs
    typology: TypologyAggregates
    frais_demarrage: FraisDemarrage
    prix_acquisition: float
    # MDF si on finance avec un prêteur B (privé, hypothèque
    # conventionnelle 75 % LTV) : 25 % du prix d'achat + frais
    # de démarrage. Plus simple à comprendre que le MDF basé
    # sur la valeur économique retenue (cf. `achat.mdf_necessaire`).
    mdf_preteur_b: float

    achat: ScenarioResult
    refi_schl: ScenarioResult
    refi_aph_50: ScenarioResult
    # None si pas d'abordabilité applicable (calculateur officiel).
    refi_aph_100: Optional[ScenarioResult]

    best_refi_amount: float
    best_refi_program: str

    def to_dict(self) -> dict:
        """Pour persistance JSON dans `LeadAnalysis.analysis_results_json`."""
        mdf_pct = (
            self.inputs.mdf_preteur_b_pct
            if self.inputs.mdf_preteur_b_pct is not None
            else 0.25
        )
        return {
            "frais_demarrage": _dataclass_to_dict(self.frais_demarrage),
            "frais_demarrage_total": self.frais_demarrage.total,
            "prix_acquisition": self.prix_acquisition,
            "mdf_preteur_b": self.mdf_preteur_b,
            # Composantes du MDF prêteur B (pour breakdown UI) :
            #   mdf_pct_prix_achat (X % × prix d'achat)
            # + frais_demarrage.total
            # = mdf_preteur_b
            "mdf_preteur_b_pct": mdf_pct,
            "taux_interet_preteur_b_projet": self.inputs.taux_interet_preteur_b_projet,
            "taux_inoccupation_pct": self.inputs.taux_inoccupation_pct,
            # Alias conservé pour rétrocompat UI front-end.
            "mdf_25pct_prix_achat": mdf_pct * self.inputs.prix_achat,
            "mdf_pct_prix_achat": mdf_pct * self.inputs.prix_achat,
            "prix_achat": self.inputs.prix_achat,
            "frais_demarrage_financables": list(
                self.inputs.frais_demarrage_financables or []
            ),
            "typology": {
                "h13_loyer_pondere": self.typology.h13_loyer_pondere,
                "nb_abordables": self.typology.nb_abordables,
                "nb_pdm": self.typology.nb_pdm,
                "nouveau_loyer_moyen_pdm": self.typology.nouveau_loyer_moyen_pdm,
            },
            "scenarios": {
                "achat": _scenario_to_dict(self.achat),
                "refi_schl": _scenario_to_dict(self.refi_schl),
                "refi_aph_50": _scenario_to_dict(self.refi_aph_50),
                "refi_aph_100": (
                    _scenario_to_dict(self.refi_aph_100)
                    if self.refi_aph_100 is not None
                    else None
                ),
            },
            "best_refi": {
                "amount": self.best_refi_amount,
                "program": self.best_refi_program,
            },
        }


def _dataclass_to_dict(d) -> dict:
    return {k: v for k, v in d.__dict__.items()}


def _scenario_to_dict(r: ScenarioResult) -> dict:
    return {
        "name": r.config.name,
        "label": r.config.label,
        "ltv": r.config.ltv,
        "amort_annees": r.config.amort_annees,
        "rcd": r.config.rcd,
        "nb_log": r.nb_log,
        "loyer_mois": r.loyer_mois,
        "revenus_totaux": r.revenus_totaux,
        "depenses_total": r.depenses.total,
        "depenses": _dataclass_to_dict(r.depenses),
        "revenus_net": r.revenus_net,
        "valeur_eco_tga": r.valeur_eco_tga,
        "valeur_eco_rcd": r.valeur_eco_rcd,
        "valeur_marchande": r.valeur_marchande,
        "valeur_retenue": r.valeur_retenue,
        "financement": r.financement,
        "paiement_mensuel_actuel": r.paiement_mensuel_actuel,
        "cashflow_annuel": r.cashflow_annuel,
        "mdf_necessaire": r.mdf_necessaire,
        "equite_a_la_fin": r.equite_a_la_fin,
    }


def compute_all(inputs: FinanceInputs, use_aph_select: bool = True) -> FinanceResults:
    """Pipeline complet d'analyse financière.

    `use_aph_select=True` (défaut) : calcule aussi le scénario
    APH 100 pts (avec abordabilité). Sinon seuls SCHL + APH 50 sont
    calculés (et `refi_aph_100` est dupliqué de `refi_aph_50` comme
    valeur de secours).

    Étapes :
      1. Agrégats de typologie (H13, abord/PDM)
      2. Scénario Achat (sans frais démarrage)
      3. Scénarios refi (sans frais démarrage)
      4. Frais de démarrage (L4..L19, basé sur achat + refi_aph_100)
      5. Prix d'acquisition = prix_achat + frais_demarrage.total
      6. MDF achat / équité refi
      7. Best refi
    """
    typo = compute_typology_aggregates(
        inputs.typologie, inputs.typologie_prix, inputs.nombre_logements
    )

    # ── Étape 1 : Scénario Achat ─────────────────────────────────
    nb_log_achat = inputs.nombre_logements
    loyer_mois_achat = (
        inputs.revenus_annuels / 12.0 / nb_log_achat
        if nb_log_achat > 0
        else 0.0
    )
    depenses_achat = compute_depenses_for_scenario(
        is_refi=False,
        is_aph=False,
        nb_log=nb_log_achat,
        revenus_totaux=inputs.revenus_annuels,
        taxes_municipales=inputs.taxes_municipales,
        taxes_scolaires=inputs.taxes_scolaires,
        assurances=inputs.assurances,
        energie_base=inputs.energie,
        reduction_energie_pct=inputs.reduction_energie_pct,
        depenses_autres=inputs.depenses_autres,
        wifi_ajoute=inputs.wifi_ajoute,
        nb_thermopompes_ajoutees=inputs.nb_thermopompes_ajoutees,
        taux_inoccupation_pct=inputs.taux_inoccupation_pct,
    )
    achat = compute_scenario(
        config=SCENARIO_ACHAT,
        nb_log=nb_log_achat,
        loyer_mois=loyer_mois_achat,
        revenus_totaux=inputs.revenus_annuels,
        depenses=depenses_achat,
        tga=inputs.tga,
        taux_interet=inputs.taux_interet_achat,
        valeur_marchande=inputs.prix_achat,
    )

    # ── Étape 2 : Scénarios refi (sans abordabilité) ─────────────
    # Nb logements après refi
    nb_log_refi = inputs.nombre_logements + inputs.nb_logements_ajoutes

    # D8 OFFICIEL : loyer moyen = H13 (auto)
    nouveau_loyer_moyen = typo.h13_loyer_pondere

    # Revenus refi standards (SCHL et APH 50) : tous au nouveau loyer.
    revenus_refi_std = nouveau_loyer_moyen * nb_log_refi * 12.0
    loyer_mois_refi_std = nouveau_loyer_moyen

    # Dépenses SCHL standard : pas de thermopompes (is_aph=False).
    depenses_schl = compute_depenses_for_scenario(
        is_refi=True,
        is_aph=False,
        nb_log=nb_log_refi,
        revenus_totaux=revenus_refi_std,
        taxes_municipales=inputs.taxes_municipales,
        taxes_scolaires=inputs.taxes_scolaires,
        assurances=inputs.assurances,
        energie_base=inputs.energie,
        reduction_energie_pct=inputs.reduction_energie_pct,
        depenses_autres=inputs.depenses_autres,
        wifi_ajoute=inputs.wifi_ajoute,
        nb_thermopompes_ajoutees=inputs.nb_thermopompes_ajoutees,
        taux_inoccupation_pct=inputs.taux_inoccupation_pct,
    )
    # Dépenses APH 50 : avec thermopompes (is_aph=True).
    depenses_aph_50 = compute_depenses_for_scenario(
        is_refi=True,
        is_aph=True,
        nb_log=nb_log_refi,
        revenus_totaux=revenus_refi_std,
        taxes_municipales=inputs.taxes_municipales,
        taxes_scolaires=inputs.taxes_scolaires,
        assurances=inputs.assurances,
        energie_base=inputs.energie,
        reduction_energie_pct=inputs.reduction_energie_pct,
        depenses_autres=inputs.depenses_autres,
        wifi_ajoute=inputs.wifi_ajoute,
        nb_thermopompes_ajoutees=inputs.nb_thermopompes_ajoutees,
        taux_inoccupation_pct=inputs.taux_inoccupation_pct,
    )
    refi_schl = compute_scenario(
        config=SCENARIO_REFI_SCHL,
        nb_log=nb_log_refi,
        loyer_mois=loyer_mois_refi_std,
        revenus_totaux=revenus_refi_std,
        depenses=depenses_schl,
        tga=inputs.tga,
        taux_interet=inputs.taux_interet_refi,
        valeur_marchande=None,
    )
    refi_aph_50 = compute_scenario(
        config=SCENARIO_REFI_APH_50,
        nb_log=nb_log_refi,
        loyer_mois=loyer_mois_refi_std,
        revenus_totaux=revenus_refi_std,
        depenses=depenses_aph_50,
        tga=inputs.tga,
        taux_interet=inputs.taux_interet_refi,
        valeur_marchande=None,
    )

    # ── Étape 3 : Scénario APH 100 pts (avec abordabilité) ───────
    if use_aph_select and typo.nb_abordables > 0:
        revenus_aph_100 = (
            typo.nb_abordables * inputs.nouveau_loyer_abordable
            + typo.nb_pdm * typo.nouveau_loyer_moyen_pdm
        ) * 12.0
        loyer_mois_aph_100 = (
            revenus_aph_100 / 12.0 / nb_log_refi if nb_log_refi > 0 else 0.0
        )
        depenses_aph_100 = compute_depenses_for_scenario(
            is_refi=True,
            is_aph=True,
            nb_log=nb_log_refi,
            revenus_totaux=revenus_aph_100,
            taxes_municipales=inputs.taxes_municipales,
            taxes_scolaires=inputs.taxes_scolaires,
            assurances=inputs.assurances,
            energie_base=inputs.energie,
            reduction_energie_pct=inputs.reduction_energie_pct,
            depenses_autres=inputs.depenses_autres,
            wifi_ajoute=inputs.wifi_ajoute,
            nb_thermopompes_ajoutees=inputs.nb_thermopompes_ajoutees,
            taux_inoccupation_pct=inputs.taux_inoccupation_pct,
        )
        refi_aph_100 = compute_scenario(
            config=SCENARIO_REFI_APH_100,
            nb_log=nb_log_refi,
            loyer_mois=loyer_mois_aph_100,
            revenus_totaux=revenus_aph_100,
            depenses=depenses_aph_100,
            tga=inputs.tga,
            taux_interet=inputs.taux_interet_refi,
            valeur_marchande=None,
        )
    else:
        # Pas d'abordabilité possible — on garde refi_aph_50 comme
        # « best APH » disponible et refi_aph_100 reste à None.
        refi_aph_100 = None  # type: ignore

    # ── Étape 4 : Frais de démarrage ─────────────────────────────
    # L5 (courtier hyp. 2) utilise le financement du « best APH »
    # disponible — APH 100 si abord, sinon APH 50 (= comportement
    # du calculateur OFFICIEL où col D = APH 50).
    financement_best_aph = (
        refi_aph_100.financement
        if refi_aph_100 is not None
        else refi_aph_50.financement
    )
    frais = compute_frais_demarrage(
        prix_achat=inputs.prix_achat,
        duree_projet_annees=inputs.duree_projet_annees,
        revenus_net_achat=achat.revenus_net,
        financement_aph_100=financement_best_aph,
        mdf_preteur_b_pct=inputs.mdf_preteur_b_pct,
        taux_interet_preteur_b_projet=inputs.taux_interet_preteur_b_projet,
        frais_developpement=inputs.frais_developpement,
        frais_negociations=inputs.frais_negociations,
        frais_travaux=inputs.frais_travaux,
    )
    # Overrides manuels : pour chaque clé fournie par l'utilisateur,
    # on remplace la valeur calculée par sa saisie. Permet d'ajuster
    # les frais sans casser les défauts pour les autres postes.
    if inputs.frais_demarrage_overrides:
        for k, v in inputs.frais_demarrage_overrides.items():
            if v is None:
                continue
            if hasattr(frais, k):
                setattr(frais, k, float(v))
    prix_acquisition = inputs.prix_achat + frais.total
    # MDF avec prêteur B = X % prix achat + frais démarrage cash. X
    # est `mdf_preteur_b_pct` (défaut 25 %, parfois 35 %).
    # Certains postes de frais sont FINANÇABLES par le prêteur B :
    # pour ceux-là, on paie seulement X % en cash (le reste est
    # ajouté au prêt). Les autres postes sont payés 100 % cash.
    mdf_pct = (
        inputs.mdf_preteur_b_pct
        if inputs.mdf_preteur_b_pct is not None
        else 0.25
    )
    financables = set(inputs.frais_demarrage_financables or [])
    frais_cash_total = 0.0
    for k, v in frais.__dict__.items():
        amount = float(v or 0)
        if k in financables:
            frais_cash_total += amount * mdf_pct
        else:
            frais_cash_total += amount
    mdf_preteur_b = mdf_pct * inputs.prix_achat + frais_cash_total

    # ── Étape 5 : MDF achat / équité refi ────────────────────────
    achat.mdf_necessaire = prix_acquisition - achat.financement
    refi_schl.equite_a_la_fin = refi_schl.financement - prix_acquisition
    refi_aph_50.equite_a_la_fin = refi_aph_50.financement - prix_acquisition
    if refi_aph_100 is not None:
        refi_aph_100.equite_a_la_fin = (
            refi_aph_100.financement - prix_acquisition
        )

    # ── Étape 6 : Best refi ──────────────────────────────────────
    candidates = [refi_schl, refi_aph_50]
    if refi_aph_100 is not None:
        candidates.append(refi_aph_100)
    best = max(candidates, key=lambda s: s.equite_a_la_fin or 0.0)
    best_amount = best.equite_a_la_fin or 0.0
    best_program = best.config.label

    return FinanceResults(
        inputs=inputs,
        typology=typo,
        frais_demarrage=frais,
        prix_acquisition=prix_acquisition,
        mdf_preteur_b=mdf_preteur_b,
        achat=achat,
        refi_schl=refi_schl,
        refi_aph_50=refi_aph_50,
        refi_aph_100=refi_aph_100,
        best_refi_amount=best_amount,
        best_refi_program=best_program,
    )