/**
 * Suffixe du numéro civique dans une adresse libre (Steven, bug 12 du
 * 2026-10-05 : « mettre possibilité de mettre des suffixes quand on crée
 * une adresse »).
 *
 * L'adresse reste UNE chaîne (« 8900A Rue Lajeunesse, Montréal, QC,
 * H2M 1S2 ») : la base, QuickBooks, les PDF et les lecteurs de numéro
 * civique (comparables, rôle d'évaluation : ils prennent les chiffres de
 * tête du premier mot) n'ont rien à changer. Ces fonctions sont une
 * « loupe » sur cette chaîne : lire le suffixe collé au numéro civique,
 * et en poser un autre sans toucher au reste.
 *
 * Formes reconnues, collées au numéro : lettres (8900A, 8900AB), ½
 * (8900½), tiret + 1 à 3 signes (8900-A, 8900-12). Au plus 4 signes :
 * « 3-8900 Rue X » (unité devant, format Postes Canada) ou
 * « 8900-8902 » (plage) ne sont PAS lus comme un suffixe.
 */

export const SUFFIXE_CIVIQUE_MAX = 4;

const RE_CIVIQUE = /^(\d+)([A-Za-z0-9½-]{1,4})?(?=[\s,]|$)/;

export type CiviqueDecompose = {
  /** Chiffres du numéro civique (« 8900 »). */
  numero: string;
  /** Suffixe collé au numéro (« A », « ½ », « -2 ») ou chaîne vide. */
  suffixe: string;
  /** Tout ce qui suit le premier mot (« Rue X, Montréal… »), espace inclus. */
  reste: string;
};

/** Décompose une adresse qui commence par un numéro civique ; null si
 *  elle ne commence pas par des chiffres (lieu nommé, rue seule, vide). */
export function decomposerCivique(adresse: string): CiviqueDecompose | null {
  const m = RE_CIVIQUE.exec(adresse ?? "");
  if (!m) return null;
  return {
    numero: m[1],
    suffixe: m[2] ?? "",
    reste: adresse.slice(m[0].length)
  };
}

/** Normalise ce que l'utilisateur tape dans la case « Suffixe » : sans
 *  espace, « 1/2 » → « ½ », lettres en majuscules, 4 signes au plus,
 *  seulement des lettres, chiffres, ½ et tirets (toujours relisible par
 *  `decomposerCivique`). */
export function nettoyerSuffixeCivique(brut: string): string {
  return (brut ?? "")
    .replace(/\s+/g, "")
    .replace(/1\/2/g, "½")
    .replace(/[^A-Za-z0-9½-]/g, "")
    .slice(0, SUFFIXE_CIVIQUE_MAX)
    .toUpperCase();
}

/** Pose `suffixe` sur le numéro civique de `adresse` (en remplaçant
 *  celui qui s'y trouve déjà). Adresse sans numéro civique → inchangée. */
export function appliquerSuffixeCivique(adresse: string, suffixe: string): string {
  const d = decomposerCivique(adresse);
  if (!d) return adresse;
  return `${d.numero}${nettoyerSuffixeCivique(suffixe)}${d.reste}`;
}
