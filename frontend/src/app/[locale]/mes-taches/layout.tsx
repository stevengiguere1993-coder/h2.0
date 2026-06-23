// Layout de l'app « Mes tâches » — server component pour exposer
// `metadata` (la metadata API de Next ne marche pas dans un Client
// Component).
//
// PWA dédiée INSTALLABLE comme une application distincte (pattern de
// /telephonie) : son manifest (/mes-taches/manifest.webmanifest) a un
// `id`/`scope` propres (« /mes-taches ») → le navigateur la voit comme
// une app séparée d'Horizon, avec sa propre icône. La page rend
// directement la vue Cartes de Mes tâches.
//
// On enveloppe dans ThemeProvider (thème clair du portail) + ConfirmProvider
// (utilisé par le TaskBoard) car ce volet n'hérite pas du layout
// /entreprises.

import type { Metadata, Viewport } from "next";

import { ConfirmProvider } from "@/components/confirm-dialog";
import { ThemeProvider } from "@/components/theme-provider";

export const metadata: Metadata = {
  title: "Mes tâches",
  description: "Mes tâches Horizon — vue Cartes façon Google Keep.",
  manifest: "/mes-taches/manifest.webmanifest",
  appleWebApp: {
    capable: true,
    statusBarStyle: "default",
    title: "Mes tâches"
  }
};

export const viewport: Viewport = {
  themeColor: "#7c3aed",
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover"
};

export default function MesTachesAppLayout({
  children
}: {
  children: React.ReactNode;
}) {
  return (
    <ThemeProvider>
      <ConfirmProvider>{children}</ConfirmProvider>
    </ThemeProvider>
  );
}
