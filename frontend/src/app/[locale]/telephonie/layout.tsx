// Layout du volet Téléphonie — server component pour pouvoir exposer
// `metadata` (Next.js metadata API ne supporte pas les Client Components).
//
// La PWA Téléphonie est INSTALLABLE comme une application distincte :
// son manifest dédié (/telephonie/manifest.webmanifest) déclare un
// scope limité à /telephonie, son propre nom (« Horizon Téléphone »)
// et ses propres shortcuts (dial pad, messages). Côté DOM, le client
// shell remplace dynamiquement le <link rel="manifest"> par celui de
// la téléphonie tant qu'on est sur cet écran.
//
// Le shell interactif (sidebar, contexts, VoiceConsole, etc.) vit
// dans _client-shell.tsx pour rester "use client".

import type { Metadata, Viewport } from "next";

import { TelephonieClientShell } from "./_client-shell";

export { useTelephonieLayout } from "./_client-shell";
export type { TelephonieSection } from "./_client-shell";

export const metadata: Metadata = {
  title: "Horizon Téléphone",
  description:
    "Téléphonie Horizon Services Immobiliers — appels, SMS, dial pad, secrétaire IA.",
  manifest: "/telephonie/manifest.webmanifest",
  appleWebApp: {
    capable: true,
    statusBarStyle: "black-translucent",
    title: "Horizon Tél"
  }
};

export const viewport: Viewport = {
  themeColor: "#0b3a36",
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover"
};

export default function TelephonieLayout({
  children
}: {
  children: React.ReactNode;
}) {
  return <TelephonieClientShell>{children}</TelephonieClientShell>;
}
