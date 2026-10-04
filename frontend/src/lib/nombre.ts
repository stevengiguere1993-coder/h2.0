/**
 * Lecture tolérante d'un nombre saisi à la main (Phil 2026-10-03 :
 * « autoriser les . et les virgules avant les cents »).
 *
 *   "2818,02"      → 2818.02   (virgule décimale, usage québécois)
 *   "2 818,02 $"   → 2818.02   (espaces / symbole ignorés)
 *   "1,234.56"     → 1234.56   (les deux présents : le DERNIER est la décimale)
 *   "1.234,56"     → 1234.56
 *   "1,234,567"    → 1234567   (plusieurs virgules = milliers)
 *   ""             → NaN       (vide ≠ zéro : à tester avant d'enregistrer)
 */
export function parseNombre(v: string | number | null | undefined): number {
  if (v == null) return NaN;
  if (typeof v === "number") return v;
  let s = v.replace(/[\s $%]/g, "").trim();
  if (s === "") return NaN;
  const virgules = (s.match(/,/g) || []).length;
  const points = (s.match(/\./g) || []).length;
  if (virgules && points) {
    // Le dernier séparateur rencontré est la décimale, l'autre = milliers.
    const decimale = s.lastIndexOf(",") > s.lastIndexOf(".") ? "," : ".";
    const milliers = decimale === "," ? "." : ",";
    s = s.split(milliers).join("");
    if (decimale === ",") s = s.replace(",", ".");
  } else if (virgules > 1) {
    s = s.split(",").join("");
  } else if (points > 1) {
    s = s.split(".").join("");
  } else if (virgules === 1) {
    s = s.replace(",", ".");
  }
  const n = Number(s);
  return Number.isFinite(n) ? n : NaN;
}

/** Comme parseNombre, mais vide / invalide → null (pour les champs
 *  facultatifs envoyés à l'API). */
export function nombreOuNull(v: string | null | undefined): number | null {
  const n = parseNombre(v);
  return Number.isNaN(n) ? null : n;
}
