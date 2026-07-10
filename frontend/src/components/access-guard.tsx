"use client";

/**
 * Garde d'accès aux pages (refonte permissions 2026-07).
 *
 * Monté dans les layouts de pôle autour de {children}. À chaque navigation :
 * matche le chemin courant contre le registre central (access-map backend),
 * puis vérifie `user.access["page:<key>"]` (calculé par /auth/me : volet du
 * pôle + seuil de rôle configurable + exceptions individuelles).
 *
 * FAIL-OPEN : pendant le chargement, sans access-map, pour un chemin non
 * régi ou une clé absente → laisse passer (comportement historique). On ne
 * bloque QUE sur un refus explicite (false) → écran « Accès non autorisé »
 * à la place du contenu (pas de redirect : zéro risque de boucle).
 */

import { useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import { Lock } from "lucide-react";

import { Link } from "@/i18n/navigation";
import { useCurrentUser } from "@/hooks/use-current-user";
import { getAccessMap, matchPageKey } from "@/lib/access";

export function AccessGuard({ children }: { children: React.ReactNode }) {
  const { user } = useCurrentUser();
  const pathname = usePathname();
  const [denied, setDenied] = useState(false);

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
      setDenied(user.access[`page:${key}`] === false);
    })();
    return () => {
      cancelled = true;
    };
  }, [user, pathname]);

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
        <Link
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          href={"/" as any}
          className="btn-secondary text-sm"
        >
          Retour au portail
        </Link>
      </div>
    );
  }

  return <>{children}</>;
}
