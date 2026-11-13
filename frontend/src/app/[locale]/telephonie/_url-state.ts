"use client";

// État de navigation du volet Communications GARDÉ DANS L'URL.
//
// Retour de Steven (2026-11-13, point 15) : sur le téléphone, toucher un
// appel ou un texto ouvrait le détail sans pouvoir revenir à la page
// précédente — la section, le détail d'appel et la conversation ouverte
// vivaient dans un simple état React, donc le bouton « retour » du
// téléphone quittait le volet au lieu de refermer le détail.
//
// Désormais chaque écran est une entrée d'historique :
//   ?section=appels           section affichée (sidebar)
//   ?call=123                 détail d'un appel (tiroir)
//   ?fil=+15145551234         conversation texto ouverte
//   ?nouveau=1                composition d'un nouveau texto
//   ?filtre=manques           journal filtré sur les appels manqués
//   ?sms=456                  lien de notification → résolu en ?fil=
//
// On passe par l'API History native (Next.js 15 la synchronise avec son
// routeur) : pas de rechargement, et « retour » ramène à l'écran d'avant.

import { useEffect, useState } from "react";

const NAV_EVENT = "kratos:telephonie-nav";
// Marqueur posé sur les entrées d'historique créées par le volet : si
// l'entrée courante en porte un, « retour » reste dans le volet.
const STATE_KEY = "kratosTelephonie";

type Update = Record<string, string | null | undefined>;

function currentSearch(): string {
  return typeof window === "undefined" ? "" : window.location.search;
}

/** Paramètres de l'URL courante, re-rendus à chaque navigation. */
export function useTelephonieUrl(): URLSearchParams {
  const [search, setSearch] = useState<string>(currentSearch);
  useEffect(() => {
    const sync = () => setSearch(currentSearch());
    sync();
    window.addEventListener("popstate", sync);
    window.addEventListener(NAV_EVENT, sync);
    return () => {
      window.removeEventListener("popstate", sync);
      window.removeEventListener(NAV_EVENT, sync);
    };
  }, []);
  return new URLSearchParams(search);
}

function buildUrl(update: Update, reset: boolean): string {
  const params = reset
    ? new URLSearchParams()
    : new URLSearchParams(window.location.search);
  for (const [k, v] of Object.entries(update)) {
    if (v === null || v === undefined || v === "") params.delete(k);
    else params.set(k, v);
  }
  const qs = params.toString();
  return `${window.location.pathname}${qs ? `?${qs}` : ""}`;
}

/**
 * Ouvre un écran du volet (nouvelle entrée d'historique, sauf `replace`).
 * `reset` repart d'une URL vide (changement de section).
 */
export function navigateTelephonie(
  update: Update,
  opts: { replace?: boolean; reset?: boolean } = {}
): void {
  if (typeof window === "undefined") return;
  const url = buildUrl(update, !!opts.reset);
  const here = `${window.location.pathname}${window.location.search}`;
  if (url === here) return;
  if (opts.replace) {
    const prev = (window.history.state as Record<string, unknown>) || {};
    window.history.replaceState({ ...prev }, "", url);
  } else {
    window.history.pushState({ [STATE_KEY]: true }, "", url);
  }
  window.dispatchEvent(new Event(NAV_EVENT));
}

/**
 * Referme un écran : revient en arrière si on l'a ouvert depuis le volet
 * (le bouton « retour » du téléphone fait alors la même chose), sinon
 * (arrivée directe par un lien de notification) retire les paramètres
 * sans quitter la page.
 */
export function closeTelephonie(update: Update): void {
  if (typeof window === "undefined") return;
  const st = window.history.state as Record<string, unknown> | null;
  if (st && st[STATE_KEY]) {
    window.history.back();
    return;
  }
  navigateTelephonie(update, { replace: true });
}
