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
export function splitFromTotal(ttc: number): {
  ht: number;
  tps: number;
  tvq: number;
  taxes: number;
} {
  const ht = Math.round((ttc / TAX_FACTOR) * 100) / 100;
  const tps = Math.round(ht * TPS_RATE * 100) / 100;
  // La TVQ absorbe l'arrondi pour que ht + tps + tvq === ttc au cent près.
  const tvq = Math.round((ttc - ht - tps) * 100) / 100;
  return { ht, tps, tvq, taxes: Math.round((tps + tvq) * 100) / 100 };
}
