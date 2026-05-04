"use client";

import { useEffect, useState } from "react";
import { usePathname, useRouter as useNextRouter } from "next/navigation";
import {
  Briefcase,
  Calendar,
  Home,
  Menu,
  ShoppingCart
} from "lucide-react";

import { Link } from "@/i18n/navigation";
import { ConfirmProvider } from "@/components/confirm-dialog";
import { HelpButton } from "@/components/help-button";
import { KratosLogo } from "@/components/kratos-logo";
import { ThemeProvider, type Theme } from "@/components/theme-provider";
import { ThemeToggle } from "@/components/theme-toggle";
import { getToken, getMe, type CurrentUser } from "@/lib/auth";

type Tab = {
  href: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
};

// 5 onglets en bas : Accueil, Agenda, Projets, Achats, Plus.
// Tâches déplacée dans « Plus ». Facturation reste accessible
// uniquement côté bureau (/app/facturation) — la mobile se
// concentre sur les actions terrain (achats, projets, agenda).
const TABS: Tab[] = [
  { href: "/m", label: "Accueil", icon: Home },
  { href: "/m/agenda", label: "Agenda", icon: Calendar },
  { href: "/m/projets", label: "Projets", icon: Briefcase },
  { href: "/m/achats", label: "Achats", icon: ShoppingCart },
  { href: "/m/plus", label: "Plus", icon: Menu }
];

export default function MobileLayout({
  children
}: {
  children: React.ReactNode;
}) {
  const pathname = usePathname() || "";
  const router = useNextRouter();
  const [me, setMe] = useState<CurrentUser | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    const token = getToken();
    if (!token) {
      // Redirect to the locale login; include the intended next URL so
      // we come back here after auth.
      const next = encodeURIComponent(pathname);
      router.replace(`/connexion?next=${next}`);
      return;
    }
    getMe(token)
      .then((u) => {
        setMe(u);
        setReady(true);
      })
      .catch(() => {
        router.replace("/connexion");
      });
  }, [pathname, router]);

  if (!ready) {
    return (
      <main className="flex min-h-screen items-center justify-center bg-brand-950 text-white/70">
        <p className="text-sm">Chargement…</p>
      </main>
    );
  }

  // La nav bottom n'a pas sa place dans le portail Prospection
  // (qui est totalement séparé du portail Construction). Les
  // chemins /m/prospection* doivent rester focalisés.
  const inProspection = pathname.includes("/m/prospection");

  const initialTheme = (me?.theme_preference as Theme) || "light";

  return (
    <ThemeProvider initialTheme={initialTheme}>
    <ConfirmProvider>
    <main className="flex min-h-screen flex-col bg-brand-950 text-white">
      {/* Bandeau global mobile : Kratos cliquable (retour portail) +
          ThemeToggle. Non-sticky volontairement — il scroll avec la
          page pour ne pas chevaucher les en-têtes de pages (qui ont
          leurs propres actions « Partager », « EN SERVICE », etc.).
          L'utilisateur swipe vers le haut pour y revenir au besoin. */}
      <div
        className="flex h-12 items-center justify-between border-b border-brand-800 bg-brand-950/95 px-3"
        style={{ paddingTop: "env(safe-area-inset-top)" }}
      >
        <Link
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          href={"/connexion" as any}
          aria-label="Accueil du portail"
          className="flex items-center"
        >
          <KratosLogo size={28} floating={false} />
        </Link>
        <ThemeToggle />
      </div>

      <div className={inProspection ? "flex-1" : "flex-1 pb-20"}>
        {children}
      </div>

      {inProspection ? null : (
      <nav
        className="fixed bottom-0 left-0 right-0 z-40 border-t border-brand-800 bg-brand-950/95 backdrop-blur"
        style={{ paddingBottom: "env(safe-area-inset-bottom)" }}
      >
        <ul className="flex items-center justify-around">
          {TABS.map((t) => {
            const active =
              t.href === "/m"
                ? pathname.endsWith("/m") || pathname.endsWith("/m/")
                : pathname.includes(t.href);
            const Icon = t.icon;
            return (
              <li key={t.href} className="flex-1">
                <Link
                  // eslint-disable-next-line @typescript-eslint/no-explicit-any
                  href={t.href as any}
                  className={`flex flex-col items-center gap-1 py-2.5 text-[10px] font-medium transition ${
                    active
                      ? "text-accent-500"
                      : "text-white/50 hover:text-white"
                  }`}
                >
                  <Icon className="h-5 w-5" />
                  {t.label}
                </Link>
              </li>
            );
          })}
        </ul>
      </nav>
      )}

      {/* Bouton flottant Aide — placé au-dessus de la nav bottom (≈60px
          + safe-area-inset-bottom). calc() pour suivre le padding iOS. */}
      <HelpButton
        triggerClassName="fixed right-4 z-40 inline-flex items-center gap-1.5 rounded-full bg-accent-500 px-3.5 py-2.5 text-xs font-semibold text-brand-950 shadow-lg ring-1 ring-accent-500/40 hover:bg-accent-400"
        triggerStyle={{
          bottom: "calc(env(safe-area-inset-bottom) + 4.5rem)"
        }}
      />

      {/* Expose current user email in a global for deep pages if needed */}
      <span id="hsi-me" data-email={me?.email || ""} className="hidden" />
    </main>
    </ConfirmProvider>
    </ThemeProvider>
  );
}
