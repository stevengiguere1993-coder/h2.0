"use client";

/**
 * Garde d'accès aux pages (permissions v2, 2026-07-24).
 *
 * Monté dans les layouts de pôle autour de {children}. À chaque navigation :
 * matche le chemin courant contre le registre central (access-map backend),
 * puis vérifie `user.access["page:<key>"]` (calculé par /auth/me : volet du
 * pôle + seuil de rôle configurable + exceptions individuelles).
 *
 * FAIL-OPEN : pendant le chargement, sans access-map, pour un chemin non
 * régi ou une clé absente → laisse passer (comportement historique). On ne
 * bloque QUE sur un refus explicite (false).
 *
 * Refus sur la RACINE d'un pôle (ex. /entreprises refusée mais Feuille de
 * temps permise) → redirection automatique vers la PREMIÈRE page accessible
 * du pôle — un employé « une seule page » atterrit toujours au bon endroit.
 * Refus sur une page profonde → écran « Accès non autorisé » avec un bouton
 * vers sa première page accessible (pas de redirect : zéro risque de boucle).
 */

import { useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import { Lock } from "lucide-react";

import { Link, useRouter } from "@/i18n/navigation";
import { useCurrentUser } from "@/hooks/use-current-user";
import {
  firstAllowedPath,
  getAccessMap,
  matchPageKey,
  stripLocale
} from "@/lib/access";

export function AccessGuard({ children }: { children: React.ReactNode }) {
  const { user } = useCurrentUser();
  const pathname = usePathname();
  const router = useRouter();
  const [denied, setDenied] = useState(false);
  const [fallback, setFallback] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      // Pas d'utilisateur (le layout gère l'auth) ou access absent
      // (rétrocompat pendant un déploiement) → fail-open.
      if (!user?.access || Object.keys(user.access).length === 0) {
        setDenied(false);
        return;
      }
      const map = await getAccessMap();
      if (cancelled) return;
      if (!map) {
        setDenied(false);
        return;
      }
      const key = matchPageKey(map, pathname);
      if (!key) {
        setDenied(false);
        return;
      }
      if (user.access[`page:${key}`] !== false) {
        setDenied(false);
        return;
      }
      // Page refusée — où renvoyer l'utilisateur dans ce pôle ?
      const entry = map.find((e) => e.key === key);
      const target = entry
        ? firstAllowedPath(user, map, entry.volet)
        : null;
      // Racine du pôle (1re entrée de son volet dans le registre, chemin
      // exact) → on redirige direct vers sa première page accessible.
      const path = stripLocale(pathname);
      const rootEntry = entry
        ? map.find((e) => e.volet === entry.volet)
        : null;
      const isVoletRoot =
        entry &&
        rootEntry &&
        entry.key === rootEntry.key &&
        entry.routes.includes(path);
      if (isVoletRoot && target) {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        router.replace(target as any);
        return;
      }
      setFallback(target);
      setDenied(true);
    })();
    return () => {
      cancelled = true;
    };
  }, [user, pathname, router]);

  if (denied) {
    return (
      <div className="flex min-h-[70vh] flex-col items-center justify-center gap-4 p-6 text-center">
        <span className="flex h-14 w-14 items-center justify-center rounded-2xl bg-rose-500/10 text-rose-400">
          <Lock className="h-7 w-7" />
        </span>
        <div>
          <h1 className="text-xl font-bold text-white">
            Accès non autorisé
          </h1>
          <p className="mt-1 max-w-sm text-sm text-white/60">
            Ton compte n&apos;a pas accès à cette page. Si tu penses que
            c&apos;est une erreur, parles-en à ton gestionnaire.
          </p>
        </div>
        <div className="flex items-center gap-2">
          {fallback ? (
            <button
              type="button"
              className="btn-accent text-sm"
              onClick={() => {
                // eslint-disable-next-line @typescript-eslint/no-explicit-any
                router.replace(fallback as any);
              }}
            >
              Aller à mes pages
            </button>
          ) : null}
          <Link
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            href={"/" as any}
            className="btn-secondary text-sm"
          >
            Retour au portail
          </Link>
        </div>
      </div>
    );
  }

  return <>{children}</>;
}
