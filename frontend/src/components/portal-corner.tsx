"use client";

import { KratosLogo } from "@/components/kratos-logo";
import { ThemeToggle } from "@/components/theme-toggle";

/**
 * Coin haut-droite des portails internes.
 *
 * Regroupe :
 *  - bouton ThemeToggle (jour/nuit), persisté par utilisateur
 *  - logo Kratos cliquable (retour à l'accueil portail)
 *
 * Drop-in à monter une seule fois par layout de volet (à la racine
 * du <main>). Pas de prop : la taille du Kratos vient de son default
 * (160px) et le toggle se synchronise via ThemeProvider.
 *
 * Mobile : on garde un Kratos à 64px pour ne pas écraser la vue, le
 * toggle en taille standard 32px.
 */
export function PortalCorner({
  kratosSize = 128,
  className = ""
}: {
  /** Taille du logo Kratos en px (default 128 = 3.2× original 40). */
  kratosSize?: number;
  className?: string;
}) {
  return (
    <div
      className={[
        "pointer-events-none fixed right-3 top-3 z-[100] flex items-start gap-2 lg:right-5 lg:top-5",
        className
      ].join(" ")}
      style={{ paddingTop: "env(safe-area-inset-top)" }}
    >
      <div className="pointer-events-auto">
        <ThemeToggle />
      </div>
      <div className="pointer-events-auto">
        <KratosLogo size={kratosSize} floating={false} />
      </div>
    </div>
  );
}
