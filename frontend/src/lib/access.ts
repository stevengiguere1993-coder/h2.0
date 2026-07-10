// Accès aux pages (refonte permissions 2026-07).
//
// Le backend est la source de vérité : /auth/me renvoie le dict `access`
// complet ({ "volet:x": bool, "page:<key>": bool, "<capacité>": bool }) et
// /permissions/access-map fournit le mapping route → clé de page (dérivé du
// registre central backend — AUCUNE duplication de règles côté client).
//
// Philosophie FAIL-OPEN : si l'access-map n'est pas chargeable, si le chemin
// ne matche aucune entrée, ou si la clé manque dans `access` (vieux backend
// pendant un déploiement), on laisse passer — le comportement historique.
// On ne bloque QUE sur un refus explicite (access["page:x"] === false).

import { authedFetch, type CurrentUser, type UserRole } from "@/lib/auth";
import { hasMinRole } from "@/lib/auth";

export type AccessMapEntry = {
  key: string;
  volet: string;
  routes: string[];
};

let _mapPromise: Promise<AccessMapEntry[] | null> | null = null;

/** Charge l'access-map une fois par session d'onglet (cache module). */
export function getAccessMap(): Promise<AccessMapEntry[] | null> {
  if (!_mapPromise) {
    _mapPromise = (async () => {
      try {
        const res = await authedFetch("/api/v1/permissions/access-map");
        if (!res.ok) return null;
        const entries = (await res.json()) as AccessMapEntry[];
        // Tri par longueur de route décroissante une fois pour toutes :
        // le matching prend le préfixe le PLUS LONG (ex. /app/clients
        // gagne sur /app pour /app/clients/5).
        return entries;
      } catch {
        return null;
      }
    })();
  }
  return _mapPromise;
}

/** Retire un éventuel préfixe de locale (/en, /fr) du pathname. */
export function stripLocale(pathname: string): string {
  const m = pathname.match(/^\/(en|fr)(\/.*|$)/);
  if (m) return m[2] || "/";
  return pathname;
}

/** Clé de page correspondant au chemin (préfixe le plus long), ou null si
 *  le chemin n'est régi par aucune entrée du registre. */
export function matchPageKey(
  map: AccessMapEntry[],
  pathname: string
): string | null {
  const path = stripLocale(pathname);
  let best: { key: string; len: number } | null = null;
  for (const entry of map) {
    for (const route of entry.routes) {
      if (path === route || path.startsWith(route + "/")) {
        if (!best || route.length > best.len) {
          best = { key: entry.key, len: route.length };
        }
      }
    }
  }
  return best ? best.key : null;
}

/**
 * L'utilisateur peut-il voir la page `pageKey` ?
 * Source : `user.access["page:<key>"]` (calculé par le backend). Fallback
 * (clé absente = déploiement en cours / vieux token) : seuil de rôle local
 * si fourni, sinon on laisse passer.
 */
export function canSeePage(
  user: CurrentUser | null,
  pageKey: string,
  fallbackMinRole?: UserRole
): boolean {
  if (!user) return false;
  const v = user.access?.[`page:${pageKey}`];
  if (typeof v === "boolean") return v;
  if (fallbackMinRole) return hasMinRole(user, fallbackMinRole);
  return true;
}

/** L'utilisateur a-t-il la capacité (action) ? Même philosophie fail-open
 *  avec fallback de rôle optionnel. */
export function canDo(
  user: CurrentUser | null,
  capability: string,
  fallbackMinRole?: UserRole
): boolean {
  if (!user) return false;
  const v = user.access?.[capability];
  if (typeof v === "boolean") return v;
  if (fallbackMinRole) return hasMinRole(user, fallbackMinRole);
  return true;
}
