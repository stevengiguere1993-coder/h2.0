"use client";

/**
 * Police du portail, réglable par utilisateur (Steven 2026-11-13 :
 * « les polices et les écritures sont petites. Mettre une police plus
 * grande en général et, dans Paramètres généraux, pouvoir personnaliser
 * sa police »).
 *
 * - Taille : facteur `--echelle-police` posé sur <html>. Les tailles
 *   Tailwind (`text-xs` … `text-4xl`, tailwind.config.ts) et les tailles
 *   en pixels (`text-[11px]`…, globals.css) le multiplient — seul le
 *   texte grossit, pas les marges ni les largeurs.
 * - Famille : `--police-portail` + `data-portal-police` sur <html>
 *   (globals.css), absent = Inter, la police d'origine.
 *
 * Réglage mémorisé côté serveur (`/auth/me/ui-prefs/police`, suit
 * l'utilisateur d'un appareil à l'autre) avec une copie locale qui
 * l'applique dès le chargement. Hors du portail (site public), rien
 * n'est posé : le facteur vaut 1.
 */

import { authedFetch } from "@/lib/auth";

export type TaillePolice = "compacte" | "normale" | "grande" | "tres_grande";
export type FamillePolice = "inter" | "jakarta" | "systeme" | "verdana" | "georgia";
export type ReglagePolice = { taille: TaillePolice; famille: FamillePolice };

export const TAILLES: { cle: TaillePolice; libelle: string; echelle: number; aide: string }[] = [
  { cle: "compacte", libelle: "Compacte", echelle: 1, aide: "L'ancienne taille de Kratos." },
  { cle: "normale", libelle: "Normale", echelle: 1.0625, aide: "Un peu plus grande (par défaut)." },
  { cle: "grande", libelle: "Grande", echelle: 1.125, aide: "Plus confortable à lire." },
  { cle: "tres_grande", libelle: "Très grande", echelle: 1.25, aide: "Pour lire de loin ou sur un petit écran." }
];

export const FAMILLES: { cle: FamillePolice; libelle: string; pile: string | null }[] = [
  { cle: "inter", libelle: "Inter (par défaut)", pile: null },
  {
    cle: "jakarta",
    libelle: "Plus Jakarta Sans",
    pile: "var(--font-display), ui-sans-serif, system-ui, sans-serif"
  },
  {
    cle: "systeme",
    libelle: "Police de l'appareil",
    pile: "system-ui, -apple-system, 'Segoe UI', Roboto, Arial, sans-serif"
  },
  { cle: "verdana", libelle: "Verdana (très lisible)", pile: "Verdana, Geneva, Tahoma, sans-serif" },
  { cle: "georgia", libelle: "Georgia (avec empattements)", pile: "Georgia, 'Times New Roman', serif" }
];

export const POLICE_DEFAUT: ReglagePolice = { taille: "normale", famille: "inter" };

const CLE_LOCALE = "h2-police";
export const CLE_SERVEUR = "police";

/** Valeur quelconque (serveur, localStorage) → réglage valide. */
export function normaliserPolice(v: unknown): ReglagePolice {
  const o = (v && typeof v === "object" ? v : {}) as Record<string, unknown>;
  const taille = TAILLES.some((t) => t.cle === o.taille)
    ? (o.taille as TaillePolice)
    : POLICE_DEFAUT.taille;
  const famille = FAMILLES.some((f) => f.cle === o.famille)
    ? (o.famille as FamillePolice)
    : POLICE_DEFAUT.famille;
  return { taille, famille };
}

export function echelleDe(taille: TaillePolice): number {
  return TAILLES.find((t) => t.cle === taille)?.echelle ?? 1;
}

export function lirePoliceLocale(): ReglagePolice {
  if (typeof window === "undefined") return POLICE_DEFAUT;
  try {
    const raw = window.localStorage.getItem(CLE_LOCALE);
    return raw ? normaliserPolice(JSON.parse(raw)) : POLICE_DEFAUT;
  } catch {
    return POLICE_DEFAUT;
  }
}

function ecrirePoliceLocale(p: ReglagePolice): void {
  try {
    window.localStorage.setItem(CLE_LOCALE, JSON.stringify(p));
  } catch {
    /* stockage indisponible */
  }
}

/** Pose le réglage sur <html> (portail seulement : appelé par le
 *  ThemeProvider, que le site public ne monte pas). */
export function appliquerPolice(p: ReglagePolice): void {
  if (typeof document === "undefined") return;
  const html = document.documentElement;
  html.style.setProperty("--echelle-police", String(echelleDe(p.taille)));
  const pile = FAMILLES.find((f) => f.cle === p.famille)?.pile ?? null;
  if (pile) {
    html.style.setProperty("--police-portail", pile);
    html.dataset.portalPolice = p.famille;
  } else {
    html.style.removeProperty("--police-portail");
    delete html.dataset.portalPolice;
  }
}

/** Lit le réglage du serveur (null = jamais enregistré ou hors ligne). */
export async function chargerPoliceServeur(): Promise<ReglagePolice | null> {
  try {
    const res = await authedFetch(`/api/v1/auth/me/ui-prefs/${CLE_SERVEUR}`);
    if (!res.ok) return null;
    const data = (await res.json()) as { found?: boolean; value?: unknown };
    return data.found ? normaliserPolice(data.value) : null;
  } catch {
    return null;
  }
}

/** Applique, mémorise localement et enregistre sur le serveur. */
export async function enregistrerPolice(p: ReglagePolice): Promise<boolean> {
  appliquerPolice(p);
  ecrirePoliceLocale(p);
  try {
    const res = await authedFetch(`/api/v1/auth/me/ui-prefs/${CLE_SERVEUR}`, {
      method: "PUT",
      body: JSON.stringify({ value: p })
    });
    return res.ok;
  } catch {
    return false;
  }
}

/** Au montage du portail : copie locale tout de suite, puis le serveur
 *  (qui fait foi) dès qu'il répond. */
export async function initialiserPolice(): Promise<void> {
  appliquerPolice(lirePoliceLocale());
  const serveur = await chargerPoliceServeur();
  if (serveur) {
    appliquerPolice(serveur);
    ecrirePoliceLocale(serveur);
  }
}
