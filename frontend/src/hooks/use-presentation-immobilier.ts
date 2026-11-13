"use client";

import { useEffect, useState } from "react";

import { authedFetch } from "@/lib/auth";

/**
 * Présentation d'Immobilier — interrupteur de retour (Steven, 2026-11-13 :
 * « avant de mettre tout en place, on s'assure de pouvoir backer à l'état
 * actuel si c'est trop difficile d'utilisation »).
 *
 * Les écrans actuels restent dans le code ; chaque lot de la refonte lit
 * ce réglage pour choisir entre l'écran actuel et le nouveau. Le réglage
 * est commun à l'équipe (Paramètres → Immobilier → « Présentation
 * d'Immobilier », admin) : GET /api/v1/immobilier/presentation.
 *
 * `actif[lot]` vrai = nouvelle présentation. La dernière réponse est
 * gardée dans le navigateur pour que le menu ne clignote pas au
 * chargement ; sans réponse ni copie, c'est le défaut du serveur.
 */

export type LotPresentation = "menu" | "loyers" | "baux" | "fiches" | "suivis";

export type PresentationImmobilier = Record<LotPresentation, boolean>;

const LOTS: LotPresentation[] = ["menu", "loyers", "baux", "fiches", "suivis"];

/** Ce que le serveur répond sans réglage : nouvelle présentation pour
 *  les lots LIVRÉS seulement. À tenir à jour avec `LOTS[].livre` de
 *  `backend/app/services/immobilier_presentation.py`. */
const DEFAUT: PresentationImmobilier = {
  menu: true,
  loyers: true,
  baux: true,
  fiches: false,
  suivis: false
};

const CLE_CACHE = "h2-immo-presentation";
/** Au-delà, une page qui s'ouvre relit le réglage (un admin a pu le
 *  changer pendant que l'onglet restait ouvert). */
const FRAICHEUR_MS = 60_000;

let memoire: PresentationImmobilier | null = null;
let recuDuServeur = false;
let dernierChargement = 0;
let enCours: Promise<void> | null = null;
const abonnes = new Set<() => void>();

function normaliser(brut: unknown): PresentationImmobilier {
  const source = (brut && typeof brut === "object" ? brut : {}) as Record<
    string,
    unknown
  >;
  const propre = { ...DEFAUT };
  for (const lot of LOTS) {
    if (typeof source[lot] === "boolean") propre[lot] = source[lot] as boolean;
  }
  return propre;
}

function lireCache(): PresentationImmobilier | null {
  if (typeof window === "undefined") return null;
  try {
    const brut = window.localStorage.getItem(CLE_CACHE);
    return brut ? normaliser(JSON.parse(brut)) : null;
  } catch {
    return null;
  }
}

function ecrireCache(valeur: PresentationImmobilier) {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(CLE_CACHE, JSON.stringify(valeur));
  } catch {
    /* stockage indisponible : on relira le serveur */
  }
}

function prevenir() {
  abonnes.forEach((f) => f());
}

function charger(): Promise<void> {
  if (enCours) return enCours;
  enCours = (async () => {
    try {
      const r = await authedFetch("/api/v1/immobilier/presentation");
      if (r.ok) {
        const corps = (await r.json()) as { actif?: unknown };
        memoire = normaliser(corps.actif);
        ecrireCache(memoire);
        recuDuServeur = true;
      }
    } catch {
      /* hors ligne : on garde la dernière valeur connue */
    } finally {
      dernierChargement = Date.now();
      enCours = null;
      prevenir();
    }
  })();
  return enCours;
}

/** À appeler après un changement du réglage (page de Paramètres) : tous
 *  les écrans ouverts suivent sans recharger. */
export function majPresentationImmobilier(actif: unknown) {
  memoire = normaliser(actif);
  ecrireCache(memoire);
  recuDuServeur = true;
  dernierChargement = Date.now();
  prevenir();
}

export function usePresentationImmobilier(): PresentationImmobilier & {
  /** Faux tant que ni le serveur ni la copie locale n'ont répondu. */
  pret: boolean;
} {
  const [, rafraichir] = useState(0);

  useEffect(() => {
    const f = () => rafraichir((n) => n + 1);
    abonnes.add(f);
    if (memoire === null) {
      memoire = lireCache();
      if (memoire !== null) f();
    }
    if (!recuDuServeur || Date.now() - dernierChargement > FRAICHEUR_MS) {
      void charger();
    }
    return () => {
      abonnes.delete(f);
    };
  }, []);

  return {
    ...(memoire ?? DEFAUT),
    pret: recuDuServeur || memoire !== null || dernierChargement > 0
  };
}

/** Nom d'une page selon la présentation montrée : `nouveau` avec le menu
 *  de la refonte (« Loyers »), `actuel` sinon (« Paiements »). Le titre,
 *  le fil d'Ariane et le menu disent ainsi toujours le même mot. */
export function useNomPageImmobilier(actuel: string, nouveau: string): string {
  const { menu } = usePresentationImmobilier();
  return menu ? nouveau : actuel;
}
