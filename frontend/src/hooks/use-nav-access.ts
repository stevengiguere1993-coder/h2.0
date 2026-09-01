"use client";

// Filtre de navigation par accès de page (refonte permissions 2026-07).
//
// `useNavAccess(user)` renvoie `canSeeHref(href)` : les sidebars l'ajoutent
// À CÔTÉ de leur filtre de rôle historique (canSee/minRole) pour masquer les
// items dont la page est explicitement refusée à l'utilisateur. Fail-open :
// sans access, sans map ou pour un href non régi → visible (le filtre de
// rôle historique continue de s'appliquer).

import { useCallback, useEffect, useState } from "react";

import type { CurrentUser } from "@/lib/auth";
import {
  getAccessMap,
  matchPageKey,
  type AccessMapEntry,
} from "@/lib/access";

export function useNavAccess(
  user: CurrentUser | null
): (href: string) => boolean {
  const etat = useNavAccessEtat(user);
  return useCallback((href: string) => etat(href) !== false, [etat]);
}

/**
 * Verdict TERNAIRE du backend pour un href (fix Olivier Terrien,
 * 2026-09-02 : une exception « allow » de la page Permissions doit
 * rendre le lien visible MÊME sous le plancher de rôle historique) :
 *   true  → page explicitement PERMISE (l'emporte sur le rôle) ;
 *   false → explicitement refusée (cacher) ;
 *   null  → inconnu/non régi (le filtre de rôle historique décide).
 */
export function useNavAccessEtat(
  user: CurrentUser | null
): (href: string) => boolean | null {
  const [map, setMap] = useState<AccessMapEntry[] | null>(null);

  useEffect(() => {
    let cancelled = false;
    void getAccessMap().then((m) => {
      if (!cancelled) setMap(m);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  return useCallback(
    (href: string) => {
      if (!user?.access || Object.keys(user.access).length === 0)
        return null;
      if (!map) return null;
      const key = matchPageKey(map, href);
      if (!key) return null;
      const v = user.access[`page:${key}`];
      if (v === true) return true;
      if (v === false) return false;
      return null;
    },
    [user, map]
  );
}
