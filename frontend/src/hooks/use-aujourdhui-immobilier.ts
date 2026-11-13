"use client";

import { useCallback, useEffect, useState } from "react";

import { authedFetch } from "@/lib/auth";

/**
 * « Aujourd'hui » d'Immobilier (refonte, lot 1) : la liste de choses à
 * faire servie par GET /api/v1/immobilier/aujourdhui.
 *
 * Lue à deux endroits : la page « Aujourd'hui » et la pastille du menu.
 * La réponse est gardée en mémoire par entreprise pour que les deux ne
 * fassent qu'une seule lecture ; chaque appelant dit la fraîcheur qu'il
 * exige (la page : quelques secondes ; le menu : quelques minutes).
 */

export type LigneAujourdhui = {
  cle: string;
  nb: number;
  titre: string;
  detail: string | null;
  ton: "urgent" | "attention" | "info";
  href: string;
  bouton: string;
};

export type Aujourdhui = {
  jour: string;
  lignes: LigneAujourdhui[];
  nb_urgent: number;
  rien_a_signaler: string[];
  indisponibles: string[];
};

type Entree = { quand: number; data: Aujourdhui };

const cache = new Map<string, Entree>();
const enCours = new Map<string, Promise<void>>();
const erreurs = new Map<string, string>();
const abonnes = new Set<() => void>();

function cle(entrepriseId: number | null): string {
  return entrepriseId == null ? "toutes" : String(entrepriseId);
}

function charger(entrepriseId: number | null): Promise<void> {
  const k = cle(entrepriseId);
  const deja = enCours.get(k);
  if (deja) return deja;
  const p = (async () => {
    try {
      const url =
        entrepriseId != null
          ? `/api/v1/immobilier/aujourdhui?entreprise_id=${entrepriseId}`
          : "/api/v1/immobilier/aujourdhui";
      const r = await authedFetch(url);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      cache.set(k, { quand: Date.now(), data: (await r.json()) as Aujourdhui });
      erreurs.delete(k);
    } catch (e) {
      erreurs.set(k, (e as Error).message);
    } finally {
      enCours.delete(k);
      abonnes.forEach((f) => f());
    }
  })();
  enCours.set(k, p);
  return p;
}

export function useAujourdhuiImmobilier(
  entrepriseId: number | null,
  {
    actif = true,
    fraicheurMs
  }: {
    /** Faux = ne rien lire (présentation actuelle, accès refusé…). */
    actif?: boolean;
    /** Âge maximal accepté de la réponse gardée en mémoire. */
    fraicheurMs: number;
  }
): {
  data: Aujourdhui | null;
  erreur: string | null;
  chargement: boolean;
  recharger: () => void;
} {
  const [, rafraichir] = useState(0);
  const k = cle(entrepriseId);

  useEffect(() => {
    if (!actif) return;
    const f = () => rafraichir((n) => n + 1);
    abonnes.add(f);
    const entree = cache.get(k);
    if (!entree || Date.now() - entree.quand > fraicheurMs) {
      void charger(entrepriseId);
    }
    return () => {
      abonnes.delete(f);
    };
  }, [actif, entrepriseId, fraicheurMs, k]);

  const recharger = useCallback(() => {
    void charger(entrepriseId);
  }, [entrepriseId]);

  return {
    data: actif ? (cache.get(k)?.data ?? null) : null,
    erreur: actif ? (erreurs.get(k) ?? null) : null,
    chargement: actif && enCours.has(k),
    recharger
  };
}
