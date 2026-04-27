import type {
  AnalyseInputs,
  FraisDemarrageInputs,
  ScenarioId,
} from "./types";

/**
 * Barèmes de dépenses normalisées (constantes Québec multi-logements).
 * Source : pratiques d'évaluation économique standard utilisées par
 * les prêteurs SCHL / APH.
 */

export const BAREMES = {
  /** Concierge ($/log/an). Seuil à 12 logements. */
  conciergeBas: 215,
  conciergeHaut: 365,
  conciergeSeuil: 12,

  /** Entretien ($/log/an), constant. */
  entretien: 610,

  /** Gestion (% des revenus). Seuil à 12 logements. */
  gestionBas: 0.0425,
  gestionHaut: 0.05,
  gestionSeuil: 12,

  /** WIFI : 5$/log/mois + 120$/mois internet. */
  wifiParLogParMois: 5,
  wifiInternetParMois: 120,

  /** Thermopompe ($/unité ajoutée/an). */
  thermopompeParUniteParAn: 190,

  /** Inoccupation + mauvaise créance (% des revenus). */
  inoccupationPct: 0.03,
} as const;

/** Paramètres financiers par scénario. */
export const SCENARIO_PARAMS: Record<
  ScenarioId,
  {
    label: string;
    ratioCouvertureDette: number;
    ratioPretValeur: number;
    amortissementAnnees: number;
  }
> = {
  achat: {
    label: "Achat conventionnel",
    ratioCouvertureDette: 1.2,
    ratioPretValeur: 0.75,
    amortissementAnnees: 25,
  },
  schl: {
    label: "Refinancement SCHL",
    ratioCouvertureDette: 1.3,
    ratioPretValeur: 0.85,
    amortissementAnnees: 35,
  },
  aph50: {
    label: "Refinancement APH 50",
    ratioCouvertureDette: 1.1,
    ratioPretValeur: 0.85,
    amortissementAnnees: 40,
  },
} as const;

/** Defaults pour chaque champ d'inputs (utile pour init du wizard). */
export const INPUTS_DEFAULTS: AnalyseInputs = {
  adresse: "",
  prixAchat: 0,
  nombreLogements: 0,
  revenusAnnuels: 0,
  taxesMunicipales: 0,
  taxesScolaires: 0,
  assurances: 0,
  energie: 0,
  autresDepenses: 0,
  logementsAjoutes: 0,
  thermopompesAjoutees: 0,
  wifi: false,
  reductionCoutEnergie: 0,
  nouveauLoyerMoyen: 0,
  nombreAnneesPortage: 2,
  fraisDemarrage: {
    courtierHypo1: undefined, // calculé
    courtierHypo2: undefined, // calculé par scénario
    taxesBienvenue: 0,
    evaluateur1: 1500,
    evaluateur2: 1500,
    inspection: 1700,
    avocat: 4000,
    notaire1: 1600,
    notaire2: 1600,
    rapportEfficacite: 4500,
    fraisDeveloppement: 60000,
    fraisNegociation: 60000,
    fraisTravaux: 60000,
    interets: undefined, // calculé
    revenusNets: undefined, // calculé
  },
  tga: 0.04,
  tauxInteretAchat: 0.04,
  tauxInteretRefi: 0.0375,
};

/**
 * Calcule la valeur effective de courtierHypo1 :
 * 1 % du prix d'achat si non fourni explicitement.
 */
export function getCourtierHypo1(
  frais: FraisDemarrageInputs,
  prixAchat: number,
): number {
  if (frais.courtierHypo1 !== undefined && frais.courtierHypo1 !== null) {
    return frais.courtierHypo1;
  }
  return prixAchat * 0.01;
}

/**
 * Calcule la valeur effective de courtierHypo2 :
 * 1 % du prêt de refinancement si non fourni.
 * Pour le scénario achat, retourne 0 (pas de refi).
 */
export function getCourtierHypo2(
  frais: FraisDemarrageInputs,
  pretRefi: number,
  scenarioId: ScenarioId,
): number {
  if (scenarioId === "achat") return 0;
  if (frais.courtierHypo2 !== undefined && frais.courtierHypo2 !== null) {
    return frais.courtierHypo2;
  }
  return pretRefi * 0.01;
}

/**
 * Intérêts pendant la période de portage :
 * `0.75 × prixAchat × 0.08 × nombreAnneesPortage`.
 *
 * Hypothèse : 75 % du prix est financé pendant le portage à 8 % de
 * coût annuel total (intérêts + frais).
 */
export function getInterets(
  frais: FraisDemarrageInputs,
  prixAchat: number,
  nombreAnneesPortage: number,
): number {
  if (frais.interets !== undefined && frais.interets !== null) {
    return frais.interets;
  }
  return 0.75 * prixAchat * 0.08 * nombreAnneesPortage;
}

/**
 * « Revenus nets » pendant le portage (terme du formulaire — c'est
 * en fait les revenus consommés, donc un coût). Si non fourni :
 * `-revenusNetsExploitation × nombreAnneesPortage`.
 *
 * Note : revenusNetsExploitation est calculé en amont, on le passe
 * en argument plutôt que de re-calculer.
 */
export function getRevenusNetsPortage(
  frais: FraisDemarrageInputs,
  revenusNetsExploitation: number,
  nombreAnneesPortage: number,
): number {
  if (frais.revenusNets !== undefined && frais.revenusNets !== null) {
    return frais.revenusNets;
  }
  return -revenusNetsExploitation * nombreAnneesPortage;
}
