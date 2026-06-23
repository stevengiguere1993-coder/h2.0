// Layout du raccourci « Mes tâches » — server component pour exposer
// `metadata` (la metadata API de Next ne marche pas dans un Client
// Component).
//
// PWA dédiée INSTALLABLE comme une application distincte : son manifest
// (/mes-taches/manifest.webmanifest) déclare son propre nom (« Mes
// tâches ») et son icône. La page cliente redirige immédiatement vers
// la vue Cartes de Mes tâches (/<locale>/entreprises/taches?view=cartes),
// si bien qu'ouvrir l'app mène DIRECTEMENT au tableau de cartes.
//
// Le manifest est calqué sur le pattern de /telephonie (sous-app
// installable séparée du portail Horizon principal).

import type { Metadata, Viewport } from "next";

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
  return <>{children}</>;
}
