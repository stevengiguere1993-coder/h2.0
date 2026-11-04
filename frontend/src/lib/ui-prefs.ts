"use client";

/**
 * États d'interface mémorisés PAR UTILISATEUR, côté serveur
 * (`/api/v1/auth/me/ui-prefs/{cle}`).
 *
 * Steven, 2026-10-30 : une colonne de kanban ouverte reste ouverte
 * jusqu'à ce qu'il la referme (et inversement), peu importe la
 * connexion — après une déconnexion ou sur un autre appareil. Le
 * serveur fait foi ; le localStorage n'est qu'un cache (clé préfixée
 * par l'id de l'utilisateur, pour un poste partagé) qui évite le
 * clignotement des colonnes en attendant la réponse.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import { authedFetch, getToken } from "@/lib/auth";

/** Id de l'utilisateur lu dans le JWT (`sub`), sans appel réseau. */
function userIdDuJeton(): string | null {
  const token = getToken();
  if (!token) return null;
  try {
    const payload = token.split(".")[1];
    const json = JSON.parse(
      atob(payload.replace(/-/g, "+").replace(/_/g, "/"))
    ) as { sub?: unknown };
    return json.sub != null ? String(json.sub) : null;
  } catch {
    return null;
  }
}

function cleCache(cle: string): string | null {
  const uid = userIdDuJeton();
  return uid ? `hsi_ui_pref:${uid}:${cle}` : null;
}

function lireListe(raw: string | null): string[] | null {
  if (raw === null) return null;
  try {
    const parsed = JSON.parse(raw) as unknown;
    return Array.isArray(parsed) ? parsed.map(String) : null;
  } catch {
    return null;
  }
}

function lireCache(cle: string): string[] | null {
  const k = cleCache(cle);
  if (!k) return null;
  try {
    return lireListe(window.localStorage.getItem(k));
  } catch {
    return null;
  }
}

function ecrireCache(cle: string, ids: string[]): void {
  const k = cleCache(cle);
  if (!k) return;
  try {
    window.localStorage.setItem(k, JSON.stringify(ids));
  } catch {
    /* localStorage indisponible — non bloquant */
  }
}

async function enregistrer(cle: string, ids: string[]): Promise<void> {
  try {
    await authedFetch(`/api/v1/auth/me/ui-prefs/${encodeURIComponent(cle)}`, {
      method: "PUT",
      body: JSON.stringify({ value: ids })
    });
  } catch {
    /* hors ligne : le cache local garde l'état, le prochain clic resynchronise */
  }
}

/**
 * Colonnes repliées d'un kanban, mémorisées par utilisateur.
 *
 * @param cle       identifiant de l'état (`kanban.crm`, …).
 * @param defaut    colonnes repliées tant que l'utilisateur n'a rien choisi.
 * @param ancienneCle ancienne clé localStorage (avant 2026-10-30) : son
 *   contenu est repris et poussé au serveur à la première visite.
 */
export function useColonnesRepliees(
  cle: string,
  defaut: readonly string[],
  ancienneCle?: string
): [Set<string>, (id: string) => void] {
  const [replies, setReplies] = useState<Set<string>>(
    () => new Set(defaut)
  );
  // Un clic avant la réponse du serveur l'emporte sur cette réponse.
  const touche = useRef(false);

  useEffect(() => {
    let annule = false;
    const cache = lireCache(cle);
    if (cache) setReplies(new Set(cache));
    (async () => {
      try {
        const res = await authedFetch(
          `/api/v1/auth/me/ui-prefs/${encodeURIComponent(cle)}`
        );
        if (!res.ok || annule || touche.current) return;
        const body = (await res.json()) as { found?: boolean; value?: unknown };
        if (annule || touche.current) return;
        if (body.found && Array.isArray(body.value)) {
          const ids = body.value.map(String);
          setReplies(new Set(ids));
          ecrireCache(cle, ids);
          return;
        }
        // Rien au serveur : reprendre l'ancien choix de ce navigateur
        // (ou le cache) pour ne pas perdre ce que l'utilisateur avait déjà.
        let ancien: string[] | null = cache;
        if (!ancien && ancienneCle) {
          try {
            ancien = lireListe(window.localStorage.getItem(ancienneCle));
          } catch {
            ancien = null;
          }
        }
        if (ancien) {
          setReplies(new Set(ancien));
          ecrireCache(cle, ancien);
          void enregistrer(cle, ancien);
        }
      } catch {
        /* réseau : on garde le cache ou les défauts */
      }
    })();
    return () => {
      annule = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cle]);

  const courant = useRef(replies);
  courant.current = replies;
  // Les enregistrements partent l'un après l'autre : deux clics rapides
  // ne peuvent pas arriver au serveur dans le désordre.
  const file = useRef<Promise<void>>(Promise.resolve());

  const basculer = useCallback(
    (id: string) => {
      touche.current = true;
      const next = new Set(courant.current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      courant.current = next;
      setReplies(next);
      const ids = Array.from(next);
      ecrireCache(cle, ids);
      file.current = file.current.then(() => enregistrer(cle, ids));
    },
    [cle]
  );

  return [replies, basculer];
}
