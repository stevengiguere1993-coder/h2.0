/**
 * Numéros de logements à créer d'un coup (fiche logement, mode
 * « Plusieurs d'un coup »). Deux façons de les donner :
 *  - une suite « du n° X au n° Y », avec un texte facultatif avant
 *    (préfixe, « A- » → A-1, A-2…) ou après (suffixe, « B » → 1B, 2B…) ;
 *  - une liste tapée ou collée (virgules, points-virgules ou retours à
 *    la ligne).
 * Les doublons (même numéro à la casse ou à la ponctuation près) sont
 * retirés, et on plafonne à 300 numéros. Pure, testée à part.
 */

export const LOGEMENTS_LOT_MAX = 300;

export type LotNumerosParams = {
  mode: "plage" | "liste";
  de: string;
  a: string;
  prefixe: string;
  suffixe: string;
  liste: string;
};

/** Clé de doublon : minuscule, sans ponctuation ni espace (même règle
 *  que le serveur, `_cle_numero`). */
export function cleNumero(numero: string): string {
  return numero.trim().toLowerCase().replace(/[^a-z0-9]/g, "");
}

export function numerosDuLot(p: LotNumerosParams): string[] {
  const vus = new Set<string>();
  const out: string[] = [];
  const ajouter = (n: string) => {
    const t = n.trim();
    const k = cleNumero(t);
    if (!t || !k || vus.has(k) || out.length >= LOGEMENTS_LOT_MAX) return;
    vus.add(k);
    out.push(t);
  };
  if (p.mode === "liste") {
    p.liste.split(/[\n,;]+/).forEach(ajouter);
    return out;
  }
  const de = parseInt(p.de, 10);
  const a = parseInt(p.a, 10);
  if (Number.isNaN(de) || Number.isNaN(a) || a < de) return out;
  const prefixe = p.prefixe.trim();
  const suffixe = p.suffixe.trim();
  for (let n = de; n <= a && out.length < LOGEMENTS_LOT_MAX; n++) {
    ajouter(`${prefixe}${n}${suffixe}`);
  }
  return out;
}

/** Aperçu « A-1, A-2, A-3… » pour illustrer un préfixe/suffixe. */
export function exempleNumeros(prefixe: string, suffixe: string, de = 1): string {
  const p = prefixe.trim();
  const s = suffixe.trim();
  return [de, de + 1, de + 2].map((n) => `${p}${n}${s}`).join(", ") + "…";
}

/*
 * Suffixe du numéro d'UN logement (Steven, 2026-10-26 : « on devrait
 * retrouver le lieu pour mettre des suffixes, ex. 976 - A, le A séparé du
 * numéro de porte »). Le numéro reste UNE chaîne en base, « 976-A »,
 * comme les « 8906-C » déjà saisis : la liste, le tri naturel et la
 * détection de doublons (`cleNumero`) n'ont rien à changer. Le
 * formulaire montre deux cases (Numéro, Suffixe) ; ces fonctions les
 * séparent à l'ouverture et les recollent à l'enregistrement.
 */

export const SUFFIXE_LOGEMENT_MAX = 4;

/** Numéro de porte en chiffres, tiret, puis 1 à 4 lettres ou chiffres
 *  dont au moins une lettre : « 976-A », « 8906-C », « 12-B2 ». Pas
 *  « 3-8900 » (unité devant le civique) ni « 976-2 », qui restent tels
 *  quels dans la case Numéro. */
const RE_NUMERO_SUFFIXE = /^(\d+)-([A-Za-z0-9]{1,4})$/;

/** Ce que l'utilisateur tape dans la case « Suffixe » : lettres et
 *  chiffres seulement, en majuscules, 4 signes au plus. */
export function nettoyerSuffixeLogement(brut: string): string {
  return (brut ?? "")
    .replace(/[^A-Za-z0-9]/g, "")
    .slice(0, SUFFIXE_LOGEMENT_MAX)
    .toUpperCase();
}

/** Recolle les deux cases : « 976 » + « A » → « 976-A » ; sans suffixe,
 *  le numéro tel quel (espaces de bord retirés). La casse du suffixe est
 *  gardée (la case met en majuscules ce qu'on tape) : rouvrir puis
 *  enregistrer un « 8906-c » existant ne le change pas. */
export function composerNumeroLogement(numero: string, suffixe: string): string {
  const n = (numero ?? "").trim();
  const s = (suffixe ?? "")
    .replace(/[^A-Za-z0-9]/g, "")
    .slice(0, SUFFIXE_LOGEMENT_MAX);
  if (!s) return n;
  if (!n) return s;
  return `${n.replace(/[\s-]+$/, "")}-${s}`;
}

/** Sépare un numéro enregistré en ses deux cases ; un numéro d'une
 *  autre forme (« 101 », « A-1 », « 976A ») va entier dans Numéro. */
export function decomposerNumeroLogement(numero: string): {
  numero: string;
  suffixe: string;
} {
  const t = (numero ?? "").trim();
  const m = RE_NUMERO_SUFFIXE.exec(t);
  if (!m || !/[A-Za-z]/.test(m[2])) return { numero: t, suffixe: "" };
  return { numero: m[1], suffixe: m[2] };
}
