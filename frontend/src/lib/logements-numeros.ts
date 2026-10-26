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
