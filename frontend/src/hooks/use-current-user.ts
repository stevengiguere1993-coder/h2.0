"use client";

import { useEffect, useState } from "react";

import { useRouter } from "@/i18n/navigation";
import { getMe, getToken, setToken, type CurrentUser } from "@/lib/auth";

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
