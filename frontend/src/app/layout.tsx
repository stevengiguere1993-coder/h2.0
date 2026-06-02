import type { Metadata, Viewport } from "next";
import localFont from "next/font/local";
import "./globals.css";

import { PwaRegister } from "@/components/pwa-register";

// Polices self-hostées (sous-ensemble latin, fichiers variables) plutôt
// que next/font/google : le build Render n'a pas accès à
// fonts.gstatic.com, donc le téléchargement au build échouait. Les
// woff2 vivent dans ./fonts et sont servis depuis l'app — zéro requête
// réseau au build comme au runtime.
const inter = localFont({
  src: "./fonts/inter-normal.woff2",
  variable: "--font-sans",
  display: "swap",
  weight: "100 900"
});

const display = localFont({
  src: "./fonts/jakarta-normal.woff2",
  variable: "--font-display",
  display: "swap",
  weight: "200 800"
});

// Fonts QG (volet Entreprises) — serif italique pour les titres,
// mono pour les chiffres/timestamps. Fichier variable normal + italic.
const fraunces = localFont({
  src: [
    { path: "./fonts/fraunces-normal.woff2", style: "normal", weight: "100 900" },
    { path: "./fonts/fraunces-italic.woff2", style: "italic", weight: "100 900" }
  ],
  variable: "--font-fraunces",
  display: "swap"
});

const mono = localFont({
  src: "./fonts/mono-normal.woff2",
  variable: "--font-mono",
  display: "swap",
  weight: "100 800"
});

export const metadata: Metadata = {
  metadataBase: new URL(
    process.env.NEXT_PUBLIC_SITE_URL || "https://immohorizon.com"
  ),
  manifest: "/manifest.webmanifest",
  appleWebApp: {
    capable: true,
    statusBarStyle: "black-translucent",
    title: "Horizon"
  },
  icons: {
    icon: [
      { url: "/pwa/icon-192.png", sizes: "192x192", type: "image/png" },
      { url: "/pwa/icon-512.png", sizes: "512x512", type: "image/png" }
    ],
    apple: [{ url: "/pwa/apple-touch-icon.png", sizes: "180x180" }]
  }
};

export const viewport: Viewport = {
  themeColor: "#0b0d10",
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover"
};

export default function RootLayout({
  children
}: {
  children: React.ReactNode;
}) {
  return (
    <html
      className={`${inter.variable} ${display.variable} ${fraunces.variable} ${mono.variable}`}
    >
      <body>
        {children}
        <PwaRegister />
      </body>
    </html>
  );
}
