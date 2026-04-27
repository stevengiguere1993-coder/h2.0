/**
 * Formules financières utilisées par le calculateur d'analyse.
 * Toutes pures, testables en isolation.
 */

import { BAREMES } from "./defaults";

/**
 * Taux périodique mensuel effectif (capitalisation semi-annuelle —
 * la convention canadienne pour les hypothèques).
 *
 * Formule :
 *   taux_mensuel = (1 + taux_annuel/2)^(1/6) - 1
 *
 * Exemple : 4 % annuel → ~0.330589 % mensuel effectif.
 */
export function tauxMensuelCanadien(tauxAnnuel: number): number {
  return Math.pow(1 + tauxAnnuel / 2, 1 / 6) - 1;
}

/**
 * Valeur actuelle d'une annuité (PV) — formule classique.
 *
 * PV = paiement × (1 - (1+i)^(-n)) / i
 *
 * Avec :
 * - paiement   : paiement périodique
 * - i          : taux périodique
 * - n          : nombre de périodes
 *
 * Si i = 0, retombe sur paiement × n.
 */
export function presentValue(
  paiement: number,
  tauxPeriodique: number,
  nbPeriodes: number,
): number {
  if (tauxPeriodique === 0) {
    return paiement * nbPeriodes;
  }
  return (
    (paiement * (1 - Math.pow(1 + tauxPeriodique, -nbPeriodes))) /
    tauxPeriodique
  );
}

/**
 * Hypothèque maximum permise par un revenu net donné, selon le
 * ratio de couverture de la dette (RCD).
 *
 * Étapes :
 *   paiement_hypo_max_annuel = revenus_nets / RCD
 *   paiement_hypo_max_mensuel = paiement_annuel / 12
 *   nb_periodes = amortissement_annees × 12
 *   PV = présent value du paiement mensuel sur n périodes au taux
 *        mensuel effectif canadien.
 *
 * Retourne :
 *   - paiementHypoMax : paiement annuel maximum (revenus / RCD)
 *   - hypothequeMaxRCD : montant maximum du prêt
 */
export function hypothequeRCD(
  revenusNets: number,
  ratioCouvertureDette: number,
  tauxAnnuel: number,
  amortissementAnnees: number,
): { paiementHypoMax: number; hypothequeMaxRCD: number } {
  const paiementHypoMax = revenusNets / ratioCouvertureDette;
  const paiementMensuel = paiementHypoMax / 12;
  const i = tauxMensuelCanadien(tauxAnnuel);
  const n = amortissementAnnees * 12;
  const hypothequeMaxRCD = presentValue(paiementMensuel, i, n);
  return { paiementHypoMax, hypothequeMaxRCD };
}

/**
 * Valeur économique selon TGA (Taux global d'actualisation).
 *
 * Convention : valeur = revenus nets / TGA. Un TGA de 4 % donne donc
 * une valeur 25× les revenus nets.
 */
export function valeurTGA(revenusNets: number, tga: number): number {
  if (tga === 0) return 0;
  return revenusNets / tga;
}

/**
 * Concierge ($/an) selon le nombre de logements.
 * - ≤ 11 logements : 215 $/log/an
 * - ≥ 12 logements : 365 $/log/an
 */
export function concierge(nombreLogements: number): number {
  const tarif =
    nombreLogements >= BAREMES.conciergeSeuil
      ? BAREMES.conciergeHaut
      : BAREMES.conciergeBas;
  return tarif * nombreLogements;
}

/**
 * Entretien ($/an) — 610 $/log constant.
 */
export function entretien(nombreLogements: number): number {
  return BAREMES.entretien * nombreLogements;
}

/**
 * Frais de gestion (% des revenus) selon le nombre de logements.
 */
export function gestion(
  revenusTotaux: number,
  nombreLogements: number,
): number {
  const taux =
    nombreLogements >= BAREMES.gestionSeuil
      ? BAREMES.gestionHaut
      : BAREMES.gestionBas;
  return revenusTotaux * taux;
}

/**
 * Service WIFI ($/an) — 5 $/log/mois + 120 $/mois internet.
 */
export function wifi(
  active: boolean,
  nombreLogements: number,
): number {
  if (!active) return 0;
  return (
    BAREMES.wifiParLogParMois * nombreLogements * 12 +
    BAREMES.wifiInternetParMois * 12
  );
}

/**
 * Coût des thermopompes ajoutées ($/an) — 190 $/unité.
 */
export function thermopompes(unitesAjoutees: number): number {
  return BAREMES.thermopompeParUniteParAn * unitesAjoutees;
}

/**
 * Inoccupation + mauvaise créance ($/an) — 3 % des revenus.
 */
export function inoccupation(revenusTotaux: number): number {
  return revenusTotaux * BAREMES.inoccupationPct;
}
