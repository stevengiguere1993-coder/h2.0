/**
 * Tri NATUREL des numéros de logement — retour partenaire 2026-09-28 :
 * « quand on entre les numéros 1-2-3, lorsqu'on arrive à 10 il se place
 * après le 1 et pas après le 9 ». Les suites de chiffres se comparent en
 * nombres : 1, 2, 9, 10, 11, 101-A, 101-B, A, B. À utiliser PARTOUT où
 * une liste est triée par numéro côté client (le serveur applique la
 * même règle dans ses listes).
 */
export function compareNumero(
  a: string | number | null | undefined,
  b: string | number | null | undefined
): number {
  return String(a ?? "").localeCompare(String(b ?? ""), "fr", {
    numeric: true,
    sensitivity: "base"
  });
}
