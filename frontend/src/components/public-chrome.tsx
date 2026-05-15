"use client";

import { usePathname } from "next/navigation";

import { SiteHeader } from "@/components/site-header";
import { SiteFooter } from "@/components/site-footer";

/**
 * Wrapper qui n'affiche le header/footer publics QUE sur les routes
 * publiques (landing). Sur les volets internes du portail (/app, /m,
 * /entreprises, /immobilier, /prospection, /investisseur, /dev,
 * /changer-mot-de-passe) on ne montre rien — chaque volet a son propre
 * chrome (sidebar + topbar).
 */

const PORTAL_PREFIXES = [
  "/app",
  "/m",
  "/entreprises",
  "/immobilier",
  "/prospection",
  "/investisseur",
  "/dev",
  "/dev-logiciel",
  "/changer-mot-de-passe",
  "/profil"
];

function stripLocale(pathname: string): string {
  // Le préfixe locale est `as-needed` : "/" ou "/fr/..." (default fr,
  // pas de prefix) ou "/en/..." (anglais explicite). On strip le
  // segment locale s'il existe pour matcher contre PORTAL_PREFIXES.
  const m = /^\/(fr|en)(\/.*)?$/.exec(pathname);
  if (m) return m[2] || "/";
  return pathname || "/";
}

function isPortalRoute(pathname: string): boolean {
  const p = stripLocale(pathname);
  return PORTAL_PREFIXES.some(
    (prefix) => p === prefix || p.startsWith(prefix + "/")
  );
}

export function PublicChrome({ children }: { children: React.ReactNode }) {
  const pathname = usePathname() || "/";
  const portal = isPortalRoute(pathname);
  if (portal) {
    // Pas de chrome public — le volet rend le sien.
    return <>{children}</>;
  }
  return (
    <>
      <SiteHeader />
      <main className="flex-1">{children}</main>
      <SiteFooter />
    </>
  );
}
