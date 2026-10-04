"use client";

/**
 * Layout du mode dev (`/dev`). Monte le ThemeProvider pour que la
 * page suive la préférence jour / nuit de l'utilisateur comme le
 * reste du portail (calqué sur le layout `parametres`). La garde
 * d'accès reste dans la page.
 */

import { ThemeProvider, type Theme } from "@/components/theme-provider";
import { useCurrentUser } from "@/hooks/use-current-user";

export default function DevLayout({
  children
}: {
  children: React.ReactNode;
}) {
  const { user } = useCurrentUser();
  const initialTheme = (user?.theme_preference as Theme) || undefined;

  return <ThemeProvider initialTheme={initialTheme}>{children}</ThemeProvider>;
}
