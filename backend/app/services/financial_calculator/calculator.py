"""Calculateur — formules + scenarios. Parité 1:1 avec le TS."""

from __future__ import annotations

import math
from typing import Optional

from .types import (
    BAREMES,
    SCENARIO_PARAMS,
    AnalyseInputs,
    AnalyseResultats,
    DepensesDetail,
    FraisDemarrageInputs,
    ScenarioId,
    ScenarioResultat,
)


# ============== Formules de base ==============


def taux_mensuel_canadien(taux_annuel: float) -> float:
    """Taux périodique mensuel effectif (capitalisation semi-annuelle)."""
    return math.pow(1 + taux_annuel / 2, 1 / 6) - 1


def present_value(
    paiement: float, taux_periodique: float, nb_periodes: int
) -> float:
    """PV annuité constante. Si taux=0 → paiement × n."""
    if taux_periodique == 0:
        return paiement * nb_periodes
    return (
        paiement
        * (1 - math.pow(1 + taux_periodique, -nb_periodes))
        / taux_periodique
    )


def hypotheque_rcd(
    revenus_nets: float,
    ratio_couverture_dette: float,
    taux_annuel: float,
    amortissement_annees: int,
) -> tuple[float, float]:
    """Retourne (paiement_hypo_max, hypotheque_max_RCD)."""
    paiement_hypo_max = revenus_nets / ratio_couverture_dette
    paiement_mensuel = paiement_hypo_max / 12
    i = taux_mensuel_canadien(taux_annuel)
    n = amortissement_annees * 12
    hypotheque_max = present_value(paiement_mensuel, i, n)
    return paiement_hypo_max, hypotheque_max


def valeur_tga(revenus_nets: float, tga: float) -> float:
    if tga == 0:
        return 0.0
    return revenus_nets / tga


def concierge(nombre_logements: int) -> float:
    tarif = (
        BAREMES["conciergeHaut"]
        if nombre_logements >= BAREMES["conciergeSeuil"]
        else BAREMES["conciergeBas"]
    )
    return tarif * nombre_logements


def entretien(nombre_logements: int) -> float:
    return BAREMES["entretien"] * nombre_logements


def gestion(revenus_totaux: float, nombre_logements: int) -> float:
    taux = (
        BAREMES["gestionHaut"]
        if nombre_logements >= BAREMES["gestionSeuil"]
        else BAREMES["gestionBas"]
    )
    return revenus_totaux * taux


def wifi_cost(active: bool, nombre_logements: int) -> float:
    if not active:
        return 0.0
    return (
        BAREMES["wifiParLogParMois"] * nombre_logements * 12
        + BAREMES["wifiInternetParMois"] * 12
    )


def thermopompes(unites_ajoutees: int) -> float:
    return BAREMES["thermopompeParUniteParAn"] * unites_ajoutees


def inoccupation(revenus_totaux: float) -> float:
    return revenus_totaux * BAREMES["inoccupationPct"]


# ============== Helpers frais démarrage ==============


def get_courtier_hypo1(f: FraisDemarrageInputs, prix_achat: float) -> float:
    if f.courtierHypo1 is not None:
        return f.courtierHypo1
    return prix_achat * 0.01


def get_courtier_hypo2(
    f: FraisDemarrageInputs, pret_refi: float, scenario_id: ScenarioId
) -> float:
    if scenario_id == "achat":
        return 0.0
    if f.courtierHypo2 is not None:
        return f.courtierHypo2
    return pret_refi * 0.01


def get_interets(
    f: FraisDemarrageInputs,
    prix_achat: float,
    nombre_annees_portage: int,
) -> float:
    if f.interets is not None:
        return f.interets
    return 0.75 * prix_achat * 0.08 * nombre_annees_portage


def get_revenus_nets_portage(
    f: FraisDemarrageInputs,
    revenus_nets_exploitation: float,
    nombre_annees_portage: int,
) -> float:
    if f.revenusNets is not None:
        return f.revenusNets
    return -revenus_nets_exploitation * nombre_annees_portage


# ============== Calcul d'un scénario ==============


def _calculs_avant_frais(
    scenario_id: ScenarioId, inputs: AnalyseInputs
) -> dict:
    params = SCENARIO_PARAMS[scenario_id]
    is_refi = scenario_id != "achat"

    # 1. Revenus
    nb_log_total = inputs.nombreLogements + (
        inputs.logementsAjoutes if is_refi else 0
    )
    revenus_totaux = (
        inputs.nouveauLoyerMoyen * nb_log_total * 12
        if is_refi
        else inputs.revenusAnnuels
    )

    # 2. Dépenses
    energie_ajustee = (
        inputs.energie * (1 - inputs.reductionCoutEnergie)
        if is_refi
        else inputs.energie
    )
    depenses = DepensesDetail(
        inoccupation=inoccupation(revenus_totaux),
        taxesMunicipales=inputs.taxesMunicipales,
        taxesScolaires=inputs.taxesScolaires,
        assurances=inputs.assurances,
        energie=energie_ajustee,
        concierge=concierge(nb_log_total),
        entretien=entretien(nb_log_total),
        gestion=gestion(revenus_totaux, nb_log_total),
        wifi=wifi_cost(inputs.wifi, nb_log_total) if is_refi else 0.0,
        thermopompes=(
            thermopompes(inputs.thermopompesAjoutees) if is_refi else 0.0
        ),
        autres=inputs.autresDepenses,
        total=0.0,
    )
    depenses.total = (
        depenses.inoccupation
        + depenses.taxesMunicipales
        + depenses.taxesScolaires
        + depenses.assurances
        + depenses.energie
        + depenses.concierge
        + depenses.entretien
        + depenses.gestion
        + depenses.wifi
        + depenses.thermopompes
        + depenses.autres
    )

    # 3. Revenus nets
    revenus_nets = revenus_totaux - depenses.total

    # 4. Valeurs
    valeur_eco_tga = valeur_tga(revenus_nets, inputs.tga)
    taux_interet = (
        inputs.tauxInteretRefi if is_refi else inputs.tauxInteretAchat
    )
    paiement_hypo_max, hypotheque_max_rcd = hypotheque_rcd(
        revenus_nets,
        params["ratioCouvertureDette"],
        taux_interet,
        params["amortissementAnnees"],
    )
    valeur_eco_rcd = hypotheque_max_rcd / params["ratioPretValeur"]

    valeur_marchande = inputs.prixAchat
    min_rcd_tga = min(valeur_eco_tga, valeur_eco_rcd)
    valeur_retenue = (
        min_rcd_tga
        if is_refi
        else min(valeur_marchande, min_rcd_tga)
    )
    pret_accorde = valeur_retenue * params["ratioPretValeur"]

    return {
        "id": scenario_id,
        "revenusTotaux": revenus_totaux,
        "depensesNormalisees": depenses,
        "revenusNets": revenus_nets,
        "valeurEconomiqueTGA": valeur_eco_tga,
        "paiementHypoMax": paiement_hypo_max,
        "hypothequeMaxRCD": hypotheque_max_rcd,
        "valeurEconomiqueRCD": valeur_eco_rcd,
        "valeurMarchande": valeur_marchande,
        "valeurRetenue": valeur_retenue,
        "pretAccorde": pret_accorde,
        "tauxInteret": taux_interet,
    }


def calculer_analyse(inputs: AnalyseInputs) -> AnalyseResultats:
    """Calcule les 3 scénarios. Implémentation parité avec le TS.

    prixAcquisition est COMMUN aux 3 scénarios (même immeuble physique
    acheté), basé sur le prêt APH50 (worst-case courtier) et les
    revenus achat (portage).
    """
    achat_calcs = _calculs_avant_frais("achat", inputs)
    schl_calcs = _calculs_avant_frais("schl", inputs)
    aph50_calcs = _calculs_avant_frais("aph50", inputs)

    courtier_hypo1 = get_courtier_hypo1(
        inputs.fraisDemarrage, inputs.prixAchat
    )
    courtier_hypo2 = get_courtier_hypo2(
        inputs.fraisDemarrage, aph50_calcs["pretAccorde"], "aph50"
    )
    interets = get_interets(
        inputs.fraisDemarrage,
        inputs.prixAchat,
        inputs.nombreAnneesPortage,
    )
    revenus_nets_portage = get_revenus_nets_portage(
        inputs.fraisDemarrage,
        achat_calcs["revenusNets"],
        inputs.nombreAnneesPortage,
    )

    f = inputs.fraisDemarrage
    frais_demarrage_total = (
        courtier_hypo1
        + courtier_hypo2
        + f.taxesBienvenue
        + f.evaluateur1
        + f.evaluateur2
        + f.inspection
        + f.avocat
        + f.notaire1
        + f.notaire2
        + f.rapportEfficacite
        + f.fraisDeveloppement
        + f.fraisNegociation
        + f.fraisTravaux
        + interets
        + revenus_nets_portage
    )
    prix_acquisition = inputs.prixAchat + frais_demarrage_total

    def finaliser(c: dict) -> ScenarioResultat:
        params = SCENARIO_PARAMS[c["id"]]
        is_refi = c["id"] != "achat"
        return ScenarioResultat(
            id=c["id"],
            label=params["label"],
            fraisDemarrageTotal=frais_demarrage_total,
            prixAcquisition=prix_acquisition,
            revenusTotaux=c["revenusTotaux"],
            depensesNormalisees=c["depensesNormalisees"],
            revenusNets=c["revenusNets"],
            valeurEconomiqueTGA=c["valeurEconomiqueTGA"],
            paiementHypoMax=c["paiementHypoMax"],
            hypothequeMaxRCD=c["hypothequeMaxRCD"],
            valeurEconomiqueRCD=c["valeurEconomiqueRCD"],
            valeurMarchande=c["valeurMarchande"],
            valeurRetenue=c["valeurRetenue"],
            ratioCouvertureDette=params["ratioCouvertureDette"],
            ratioPretValeur=params["ratioPretValeur"],
            amortissementAnnees=params["amortissementAnnees"],
            tauxInteret=c["tauxInteret"],
            pretAccorde=c["pretAccorde"],
            miseDeFonds=(
                None if is_refi else prix_acquisition - c["pretAccorde"]
            ),
            gainActionnaires=(
                c["pretAccorde"] - prix_acquisition if is_refi else None
            ),
        )

    return AnalyseResultats(
        achat=finaliser(achat_calcs),
        schl=finaliser(schl_calcs),
        aph50=finaliser(aph50_calcs),
        inputsEffectifs=inputs,
    )
