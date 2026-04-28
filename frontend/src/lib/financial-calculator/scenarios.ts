import {
  getCourtierHypo1,
  getCourtierHypo2,
  getInterets,
  getRevenusNetsPortage,
  SCENARIO_PARAMS,
} from "./defaults";
import {
  concierge,
  entretien,
  gestion,
  hypothequeRCD,
  inoccupation,
  thermopompes,
  valeurTGA,
  wifi,
} from "./formulas";
import type {
  AnalyseInputs,
  AnalyseResultats,
  DepensesDetail,
  ScenarioId,
  ScenarioResultat,
} from "./types";

/**
 * Calculs intermédiaires d'un scénario, AVANT que les frais
 * communs soient appliqués. Permet de calculer les pretsAccordés
 * des 3 scénarios en parallèle puis de bâtir le frais_demarrage
 * commun (qui dépend du prêt APH50, le plus élevé).
 */
interface ScenarioCalcsAvantFrais {
  id: ScenarioId;
  revenusTotaux: number;
  depensesNormalisees: DepensesDetail;
  revenusNets: number;
  valeurEconomiqueTGA: number;
  paiementHypoMax: number;
  hypothequeMaxRCD: number;
  valeurEconomiqueRCD: number;
  valeurMarchande: number;
  valeurRetenue: number;
  pretAccorde: number;
  tauxInteret: number;
}

function calculsAvantFrais(
  scenarioId: ScenarioId,
  inputs: AnalyseInputs,
): ScenarioCalcsAvantFrais {
  const params = SCENARIO_PARAMS[scenarioId];
  const isRefi = scenarioId !== "achat";

  // 1. Revenus
  const nombreLogementsTotal =
    inputs.nombreLogements + (isRefi ? inputs.logementsAjoutes : 0);
  const revenusTotaux = isRefi
    ? inputs.nouveauLoyerMoyen * nombreLogementsTotal * 12
    : inputs.revenusAnnuels;

  // 2. Dépenses normalisées
  const energieAjustee = isRefi
    ? inputs.energie * (1 - inputs.reductionCoutEnergie)
    : inputs.energie;

  const depenses: DepensesDetail = {
    inoccupation: inoccupation(revenusTotaux),
    taxesMunicipales: inputs.taxesMunicipales,
    taxesScolaires: inputs.taxesScolaires,
    assurances: inputs.assurances,
    energie: energieAjustee,
    concierge: concierge(nombreLogementsTotal),
    entretien: entretien(nombreLogementsTotal),
    gestion: gestion(revenusTotaux, nombreLogementsTotal),
    wifi: isRefi ? wifi(inputs.wifi, nombreLogementsTotal) : 0,
    thermopompes: isRefi ? thermopompes(inputs.thermopompesAjoutees) : 0,
    autres: inputs.autresDepenses,
    total: 0,
  };
  depenses.total =
    depenses.inoccupation +
    depenses.taxesMunicipales +
    depenses.taxesScolaires +
    depenses.assurances +
    depenses.energie +
    depenses.concierge +
    depenses.entretien +
    depenses.gestion +
    depenses.wifi +
    depenses.thermopompes +
    depenses.autres;

  // 3. Revenus nets
  const revenusNets = revenusTotaux - depenses.total;

  // 4. TGA + RCD + valeur retenue + prêt
  const valeurEconomiqueTGA = valeurTGA(revenusNets, inputs.tga);

  const tauxInteret = isRefi
    ? inputs.tauxInteretRefi
    : inputs.tauxInteretAchat;
  const { paiementHypoMax, hypothequeMaxRCD } = hypothequeRCD(
    revenusNets,
    params.ratioCouvertureDette,
    tauxInteret,
    params.amortissementAnnees,
  );
  const valeurEconomiqueRCD = hypothequeMaxRCD / params.ratioPretValeur;

  const valeurMarchande = inputs.prixAchat;
  const minRcdTga = Math.min(valeurEconomiqueTGA, valeurEconomiqueRCD);
  const valeurRetenue = isRefi
    ? minRcdTga
    : Math.min(valeurMarchande, minRcdTga);

  const pretAccorde = valeurRetenue * params.ratioPretValeur;

  return {
    id: scenarioId,
    revenusTotaux,
    depensesNormalisees: depenses,
    revenusNets,
    valeurEconomiqueTGA,
    paiementHypoMax,
    hypothequeMaxRCD,
    valeurEconomiqueRCD,
    valeurMarchande,
    valeurRetenue,
    pretAccorde,
    tauxInteret,
  };
}

/**
 * Calcule les 3 scénarios.
 *
 * Pipeline :
 *   1. Calcule les revenus, dépenses, valeur retenue et prêt accordé
 *      pour chacun des 3 scénarios (calculsAvantFrais).
 *   2. Calcule UN frais_demarrage commun aux 3, basé sur :
 *      - courtierHypo2 = 1 % du prêt APH50 (worst-case, le plus élevé)
 *      - revenusNetsPortage = -revenusNets achat × nbAnneesPortage
 *      Ces frais représentent l'acquisition PHYSIQUE de l'immeuble,
 *      qui est la même quel que soit le plan de refinancement.
 *   3. Pour chaque scénario : prixAcquisition = prixAchat + frais
 *      (commun), MDF (achat) ou gain (refi).
 */
export function calculerAnalyse(inputs: AnalyseInputs): AnalyseResultats {
  // Étape 1 — calculs intermédiaires des 3 scénarios
  const achatCalcs = calculsAvantFrais("achat", inputs);
  const schlCalcs = calculsAvantFrais("schl", inputs);
  const aph50Calcs = calculsAvantFrais("aph50", inputs);

  // Étape 2 — frais_demarrage commun (même acquisition pour les 3)
  const courtierHypo1 = getCourtierHypo1(
    inputs.fraisDemarrage,
    inputs.prixAchat,
  );
  // courtierHypo2 = 1% du prêt APH50 (worst-case). Si l'utilisateur
  // override la valeur, on l'utilise telle quelle.
  const courtierHypo2 = getCourtierHypo2(
    inputs.fraisDemarrage,
    aph50Calcs.pretAccorde,
    "aph50",
  );
  const interets = getInterets(
    inputs.fraisDemarrage,
    inputs.prixAchat,
    inputs.nombreAnneesPortage,
  );
  // revenusNetsPortage utilise les revenus nets ACHAT (pas refi),
  // car c'est la période avant le refi.
  const revenusNetsPortage = getRevenusNetsPortage(
    inputs.fraisDemarrage,
    achatCalcs.revenusNets,
    inputs.nombreAnneesPortage,
  );

  const fraisDemarrageTotal =
    courtierHypo1 +
    courtierHypo2 +
    inputs.fraisDemarrage.taxesBienvenue +
    inputs.fraisDemarrage.evaluateur1 +
    inputs.fraisDemarrage.evaluateur2 +
    inputs.fraisDemarrage.inspection +
    inputs.fraisDemarrage.avocat +
    inputs.fraisDemarrage.notaire1 +
    inputs.fraisDemarrage.notaire2 +
    inputs.fraisDemarrage.rapportEfficacite +
    inputs.fraisDemarrage.fraisDeveloppement +
    inputs.fraisDemarrage.fraisNegociation +
    inputs.fraisDemarrage.fraisTravaux +
    interets +
    revenusNetsPortage;

  const prixAcquisition = inputs.prixAchat + fraisDemarrageTotal;

  // Étape 3 — finalise chaque scénario avec frais commun
  function finaliser(c: ScenarioCalcsAvantFrais): ScenarioResultat {
    const params = SCENARIO_PARAMS[c.id];
    const isRefi = c.id !== "achat";
    return {
      id: c.id,
      label: params.label,
      fraisDemarrageTotal,
      prixAcquisition,
      revenusTotaux: c.revenusTotaux,
      depensesNormalisees: c.depensesNormalisees,
      revenusNets: c.revenusNets,
      valeurEconomiqueTGA: c.valeurEconomiqueTGA,
      paiementHypoMax: c.paiementHypoMax,
      hypothequeMaxRCD: c.hypothequeMaxRCD,
      valeurEconomiqueRCD: c.valeurEconomiqueRCD,
      valeurMarchande: c.valeurMarchande,
      valeurRetenue: c.valeurRetenue,
      ratioCouvertureDette: params.ratioCouvertureDette,
      ratioPretValeur: params.ratioPretValeur,
      amortissementAnnees: params.amortissementAnnees,
      tauxInteret: c.tauxInteret,
      pretAccorde: c.pretAccorde,
      miseDeFonds: !isRefi ? prixAcquisition - c.pretAccorde : null,
      gainActionnaires: isRefi ? c.pretAccorde - prixAcquisition : null,
    };
  }

  return {
    achat: finaliser(achatCalcs),
    schl: finaliser(schlCalcs),
    aph50: finaliser(aph50Calcs),
    inputsEffectifs: inputs,
  };
}
