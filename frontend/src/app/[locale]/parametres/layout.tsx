"use client";

/**
 * Layout neutre du hub Paramètres unifié (`/parametres`).
 *
 * Pôle-neutre : pas de sidebar spécifique à un pôle — le hub est le
 * point d'entrée unique des réglages, accessible identiquement depuis
 * tous les pôles. Fournit le thème + la garde d'authentification
 * (calqué sur le layout `app`).
 */

import { Loader2 } from "lucide-react";

import { ThemeProvider, type Theme } from "@/components/theme-provider";
import { useCurrentUser } from "@/hooks/use-current-user";

export default function ParametresLayout({
  children
}: {
  children: React.ReactNode;
}) {
  const { user, loading } = useCurrentUser();

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-brand-950">
        <Loader2 className="h-6 w-6 animate-spin text-accent-500" />
      </div>
    );
  }
  if (!user) return null;

  const initialTheme = (user.theme_preference as Theme) || "light";

  return (
    <ThemeProvider initialTheme={initialTheme}>
      <div className="min-h-screen bg-brand-950">{children}</div>
    </ThemeProvider>
  );
}
