"use client";

import { useEffect, useState } from "react";

import { useRouter } from "@/i18n/navigation";
import {
  getMe,
  getToken,
  isApercu,
  localePrefix,
  setToken,
  stopApercu,
  type CurrentUser
} from "@/lib/auth";

export function useCurrentUser(): {
  user: CurrentUser | null;
  loading: boolean;
  signOut: () => void;
} {
  const router = useRouter();
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const token = getToken();
    if (!token) {
      setLoading(false);
      router.replace("/connexion");
      return;
    }
    getMe(token)
      .then((u) => setUser(u))
      .catch(() => {
        // Aperçu « voir comme » : c'est le jeton d'aperçu (2 h) qui est
        // expiré/invalide, pas la session de l'admin. On restaure son jeton
        // et on le ramène sur la page des comptes (même sortie que la
        // branche 401 d'authedFetch) au lieu de le déconnecter.
        if (isApercu()) {
          stopApercu();
          window.location.assign(
            `${localePrefix()}/app/utilisateurs?apercu=expire`
          );
          return;
        }
        setToken(null);
        router.replace("/connexion");
      })
      .finally(() => setLoading(false));
  }, [router]);

  function signOut() {
    setToken(null);
    setUser(null);
    router.replace("/connexion");
  }

  return { user, loading, signOut };
}
