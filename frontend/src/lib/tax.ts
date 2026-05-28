// Taxes Québec : TPS 5 % + TVQ 9,975 %.
// Le facteur 1,14975 convertit un montant TTC en HT (et inversement),
// cohérent avec le backend (project_finances / facture_pdf).
export const TPS_RATE = 0.05;
export const TVQ_RATE = 0.09975;
export const TAX_FACTOR = 1 + TPS_RATE + TVQ_RATE; // 1.14975

/**
 * Décompose un montant total (TTC) en HT + taxes, en supposant des
 * taxes québécoises standard (TPS + TVQ). Le HT sert d'assiette à la
 * majoration lors de la refacturation client ; les taxes sont
 * recalculées à la fin de la facture client.
 */
export function splitFromTotal(ttc: number): { ht: number; taxes: number } {
  const ht = Math.round((ttc / TAX_FACTOR) * 100) / 100;
  const taxes = Math.round((ttc - ht) * 100) / 100;
  return { ht, taxes };
}
