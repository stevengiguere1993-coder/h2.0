/**
 * Calculateur d'investissement immobilier multi-logements (Québec).
 *
 * Compare 3 scénarios de financement :
 * - Achat conventionnel
 * - Refinancement SCHL
 * - Refinancement APH 50 (programme Solutions abordables 50 % efficacité)
 *
 * Toutes les formules sont en TypeScript pur, sans dépendance, pour
 * pouvoir être testées en isolation.
 */

export type ScenarioId = "achat" | "schl" | "aph50";

/** Inputs saisis par l'utilisateur dans le wizard. */
export interface AnalyseInputs {
  // Étape 1 — identification
  adresse: string;
  prixAchat: number;
  nombreLogements: number;

  // Étape 2 — revenus / dépenses actuels
  revenusAnnuels: number;
  taxesMunicipales: number;
  taxesScolaires: number;
  assurances: number;
  energie: number;
  autresDepenses: number;

  // Étape 3 — hypothèses refinancement
  logementsAjoutes: number;
  thermopompesAjoutees: number;
  wifi: boolean;
  reductionCoutEnergie: number; // 0 à 1, ex 0.3 = 30% de moins
  nouveauLoyerMoyen: number;
  nombreAnneesPortage: number;

  // Étape 4 — frais de démarrage (modifiables, calculés par défaut)
  fraisDemarrage: FraisDemarrageInputs;

  // Étape 5 — paramètres financiers
  tga: number; // ex 0.04 = 4%
  tauxInteretAchat: number;
  tauxInteretRefi: number;
}

export interface FraisDemarrageInputs {
  /** Si null/undefined, calculé : 1% du prix d'achat. */
  courtierHypo1?: number;
  /** Si null, calculé : 1% du prêt refi (par scénario). */
  courtierHypo2?: number;
  taxesBienvenue: number;
  evaluateur1: number;
  evaluateur2: number;
  inspection: number;
  avocat: number;
  notaire1: number;
  notaire2: number;
  rapportEfficacite: number;
  fraisDeveloppement: number;
  fraisNegociation: number;
  fraisTravaux: number;
  /**
   * Si non défini : `0.75 × prixAchat × 0.08 × nombreAnneesPortage`.
   * Représente les intérêts encourus pendant la période de portage
   * (acquisition → refinancement).
   */
  interets?: number;
  /**
   * Si non défini : `-revenusNetsExploitation × nombreAnneesPortage`.
   * Représente la consommation des revenus nets pendant le portage
   * (négatif = on absorbe ces revenus, ils ne sortent pas du compte).
   */
  revenusNets?: number;
}

/** Résultat de UN scénario. */
export interface ScenarioResultat {
  id: ScenarioId;
  label: string;

  // Frais
  fraisDemarrageTotal: number;
  prixAcquisition: number;

  // Revenus / dépenses
  revenusTotaux: number;
  depensesNormalisees: DepensesDetail;
  revenusNets: number;

  // Valeurs économiques
  valeurEconomiqueTGA: number;
  paiementHypoMax: number;
  hypothequeMaxRCD: number;
  valeurEconomiqueRCD: number;
  valeurMarchande: number; // achat seulement
  valeurRetenue: number;

  // Financement
  ratioCouvertureDette: number;
  ratioPretValeur: number;
  amortissementAnnees: number;
  tauxInteret: number;
  pretAccorde: number;

  // Sortie clé selon scénario
  miseDeFonds: number | null; // achat seulement (null pour refi)
  gainActionnaires: number | null; // refi seulement (null pour achat)
}

/** Détail des dépenses normalisées (utile pour debug + UI). */
export interface DepensesDetail {
  inoccupation: number;
  taxesMunicipales: number;
  taxesScolaires: number;
  assurances: number;
  energie: number;
  concierge: number;
  entretien: number;
  gestion: number;
  wifi: number;
  thermopompes: number;
  autres: number;
  total: number;
}

/** Résultats de l'analyse pour les 3 scénarios. */
export interface AnalyseResultats {
  achat: ScenarioResultat;
  schl: ScenarioResultat;
  aph50: ScenarioResultat;
  /** Inputs effectifs utilisés (avec defaults appliqués). */
  inputsEffectifs: AnalyseInputs;
}
