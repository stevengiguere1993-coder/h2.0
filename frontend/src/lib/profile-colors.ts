/**
 * Palette de couleurs de profil.
 *
 * Chaque couleur a une clé courte (stockée en base dans
 * users.profile_color) et un set de classes Tailwind pour rendre
 * les pastilles d'assignation, l'avatar fallback, etc. La palette
 * est volontairement large pour qu'une équipe de 10 personnes ait
 * toujours des couleurs distinctes.
 */

export type ProfileColor =
  | "violet"
  | "rose"
  | "pink"
  | "red"
  | "orange"
  | "amber"
  | "yellow"
  | "lime"
  | "green"
  | "emerald"
  | "teal"
  | "cyan"
  | "sky"
  | "blue"
  | "indigo"
  | "fuchsia"
  | "slate";

/** Classes appliquées au fond de la pastille assignée. */
export const PROFILE_COLOR_PILL: Record<ProfileColor, string> = {
  violet: "bg-violet-500 text-white",
  rose: "bg-rose-500 text-white",
  pink: "bg-pink-500 text-white",
  red: "bg-red-500 text-white",
  orange: "bg-orange-500 text-white",
  amber: "bg-amber-400 text-brand-950",
  yellow: "bg-yellow-400 text-brand-950",
  lime: "bg-lime-400 text-brand-950",
  green: "bg-green-500 text-white",
  emerald: "bg-emerald-500 text-white",
  teal: "bg-teal-500 text-white",
  cyan: "bg-cyan-500 text-brand-950",
  sky: "bg-sky-500 text-white",
  blue: "bg-blue-500 text-white",
  indigo: "bg-indigo-500 text-white",
  fuchsia: "bg-fuchsia-500 text-white",
  slate: "bg-slate-500 text-white"
};

/** Classes pour le swatch dans le sélecteur (rond plein). */
export const PROFILE_COLOR_SWATCH: Record<ProfileColor, string> = {
  violet: "bg-violet-500",
  rose: "bg-rose-500",
  pink: "bg-pink-500",
  red: "bg-red-500",
  orange: "bg-orange-500",
  amber: "bg-amber-400",
  yellow: "bg-yellow-400",
  lime: "bg-lime-400",
  green: "bg-green-500",
  emerald: "bg-emerald-500",
  teal: "bg-teal-500",
  cyan: "bg-cyan-500",
  sky: "bg-sky-500",
  blue: "bg-blue-500",
  indigo: "bg-indigo-500",
  fuchsia: "bg-fuchsia-500",
  slate: "bg-slate-500"
};

export const PROFILE_COLORS: { value: ProfileColor; label: string }[] = [
  { value: "violet", label: "Violet" },
  { value: "rose", label: "Rose" },
  { value: "pink", label: "Pink" },
  { value: "red", label: "Rouge" },
  { value: "orange", label: "Orange" },
  { value: "amber", label: "Ambre" },
  { value: "yellow", label: "Jaune" },
  { value: "lime", label: "Lime" },
  { value: "green", label: "Vert" },
  { value: "emerald", label: "Émeraude" },
  { value: "teal", label: "Sarcelle" },
  { value: "cyan", label: "Cyan" },
  { value: "sky", label: "Ciel" },
  { value: "blue", label: "Bleu" },
  { value: "indigo", label: "Indigo" },
  { value: "fuchsia", label: "Fuchsia" },
  { value: "slate", label: "Ardoise" }
];

/** Classes par défaut quand l'utilisateur n'a pas choisi de couleur. */
export const DEFAULT_PILL_CLASS = "bg-brand-800 text-white/70";

export function colorClassesForUser(
  color: string | null | undefined
): string {
  if (!color) return DEFAULT_PILL_CLASS;
  if ((PROFILE_COLOR_PILL as Record<string, string>)[color]) {
    return PROFILE_COLOR_PILL[color as ProfileColor];
  }
  return DEFAULT_PILL_CLASS;
}
