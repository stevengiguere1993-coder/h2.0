"use client";

import { createContext, useContext, useState } from "react";
import { usePathname } from "next/navigation";
import {
  Briefcase,
  ExternalLink,
  Home,
  Loader2,
  LogOut,
  Menu,
  Sparkles,
  X
} from "lucide-react";

import { Link } from "@/i18n/navigation";
import { ConfirmProvider } from "@/components/confirm-dialog";
import { HelpButton } from "@/components/help-button";
import { ThemeProvider, type Theme } from "@/components/theme-provider";
import { useCurrentUser } from "@/hooks/use-current-user";

type NavItem = {
  href: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
};

// Navigation initiale — sera étoffée au fur et à mesure
// (Tableau de bord, Mes tâches, Statistiques, Paramètres…).
const NAV: NavItem[] = [
  { href: "/entreprises", label: "Entreprises", icon: Briefcase },
  { href: "/entreprises/import-monday", label: "Import Monday", icon: ExternalLink }
];

type Ctx = { onOpenSidebar: () => void };
const ctx = createContext<Ctx>({ onOpenSidebar: () => {} });

export function useEntreprisesLayout() {
  return useContext(ctx);
}

export default function EntreprisesLayout({
  children
}: {
  children: React.ReactNode;
}) {
  const { user, loading, signOut } = useCurrentUser();
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const pathname = usePathname() || "";

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-brand-950">
        <Loader2 className="h-6 w-6 animate-spin text-violet-300" />
      </div>
    );
  }
  if (!user) return null;

  const initialTheme = (user.theme_preference as Theme) || "light";
  const allowed = (user.volets || []).includes("entreprises");

  function isActive(href: string) {
    if (href === "/entreprises")
      return pathname.endsWith("/entreprises");
    return pathname.includes(href);
  }

  return (
    <ThemeProvider initialTheme={initialTheme}>
      <div className="flex min-h-screen bg-brand-950">
        {sidebarOpen ? (
          <button
            type="button"
            aria-label="Fermer"
            onClick={() => setSidebarOpen(false)}
            className="fixed inset-0 z-40 bg-black/70 backdrop-blur-sm lg:hidden"
          />
        ) : null}

        <aside
          className={`fixed inset-y-0 left-0 z-50 w-64 flex-col border-r border-brand-800 bg-brand-950 transition-transform lg:static lg:flex lg:translate-x-0 ${
            sidebarOpen
              ? "flex translate-x-0"
              : "hidden -translate-x-full"
          }`}
        >
          <div className="flex items-center justify-between border-b border-brand-800 px-4 py-4">
            <Link href="/entreprises" className="flex items-center gap-2">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src="/logo.png"
                alt="Horizon"
                className="h-9 w-auto object-contain"
              />
            </Link>
            <button
              type="button"
              onClick={() => setSidebarOpen(false)}
              className="rounded-md p-2 text-white/70 hover:bg-brand-900 hover:text-white lg:hidden"
              aria-label="Fermer"
            >
              <X className="h-5 w-5" />
            </button>
          </div>

          <nav className="flex-1 space-y-6 overflow-y-auto px-3 py-5">
            <div>
              <p className="mb-2 flex items-center gap-1.5 px-3 text-xs font-semibold uppercase tracking-wider text-violet-300">
                <Sparkles className="h-3 w-3" />
                Gestion d&apos;entreprises
              </p>
              <ul className="space-y-0.5">
                {NAV.map((item) => {
                  const active = isActive(item.href);
                  return (
                    <li key={item.href}>
                      <Link
                        // eslint-disable-next-line @typescript-eslint/no-explicit-any
                        href={item.href as any}
                        onClick={() => setSidebarOpen(false)}
                        className={`flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition ${
                          active
                            ? "bg-violet-500/15 text-violet-200"
                            : "text-white/70 hover:bg-brand-900 hover:text-white"
                        }`}
                      >
                        <item.icon
                          className={`h-4 w-4 flex-shrink-0 ${
                            active ? "text-violet-300" : ""
                          }`}
                        />
                        <span>{item.label}</span>
                      </Link>
                    </li>
                  );
                })}
              </ul>
            </div>

            <div className="mt-6 border-t border-brand-800 pt-3">
              <Link
                // eslint-disable-next-line @typescript-eslint/no-explicit-any
                href={"/connexion" as any}
                className="flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-sm text-white/70 hover:bg-brand-900 hover:text-white"
              >
                <Home className="h-4 w-4" />
                Accueil du portail
              </Link>
            </div>
          </nav>

          <div className="border-t border-brand-800 px-3 py-4">
            {user.email ? (
              <p
                className="mb-2 truncate px-3 text-xs text-white/50"
                title={user.email}
              >
                {user.email}
              </p>
            ) : null}
            <button
              type="button"
              onClick={signOut}
              className="flex w-full items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium text-white/70 transition hover:bg-brand-900 hover:text-white"
            >
              <LogOut className="h-4 w-4" />
              <span>Se déconnecter</span>
            </button>
          </div>
        </aside>

        <div className="flex min-w-0 flex-1 flex-col">
          <ctx.Provider
            value={{ onOpenSidebar: () => setSidebarOpen(true) }}
          >
            <ConfirmProvider>
              <main className="flex-1 overflow-x-hidden">
                {allowed ? (
                  children
                ) : (
                  <NoAccess />
                )}
              </main>
              <HelpButton />
            </ConfirmProvider>
          </ctx.Provider>
        </div>
      </div>
    </ThemeProvider>
  );
}

function NoAccess() {
  return (
    <div className="mx-auto mt-20 max-w-md rounded-2xl border border-rose-500/40 bg-rose-500/5 p-6 text-center">
      <h2 className="text-lg font-bold text-white">
        Accès refusé
      </h2>
      <p className="mt-2 text-sm text-white/60">
        Ton compte n&apos;a pas accès au volet « Gestion
        d&apos;entreprises ».
      </p>
    </div>
  );
}

// Topbar minimal pour les pages enfants — remplace AppTopbar du
// volet Construction qui pollue le breadcrumb avec « Construction ».
export function EntreprisesTopbar({
  breadcrumbs,
  rightSlot
}: {
  breadcrumbs: { label: string; href?: string }[];
  rightSlot?: React.ReactNode;
}) {
  const { onOpenSidebar } = useEntreprisesLayout();
  return (
    <header className="sticky top-0 z-30 flex h-16 items-center gap-3 border-b border-brand-800 bg-brand-950/95 px-4 backdrop-blur lg:px-6">
      <button
        type="button"
        onClick={onOpenSidebar}
        className="rounded-md p-2 text-white/80 hover:bg-brand-900 hover:text-white lg:hidden"
        aria-label="Ouvrir la barre latérale"
      >
        <Menu className="h-5 w-5" />
      </button>
      <nav className="flex min-w-0 flex-1 items-center gap-2">
        {breadcrumbs.map((c, i) => {
          const isLast = i === breadcrumbs.length - 1;
          const cls = `truncate text-sm font-medium ${
            isLast
              ? "text-white"
              : c.href
              ? "text-white/60 hover:text-violet-300"
              : "text-white/50"
          }`;
          return (
            <span key={i} className="flex items-center gap-2">
              {i > 0 ? <span className="text-white/30">/</span> : null}
              {!isLast && c.href ? (
                <Link
                  // eslint-disable-next-line @typescript-eslint/no-explicit-any
                  href={c.href as any}
                  className={cls}
                >
                  {c.label}
                </Link>
              ) : (
                <span className={cls}>{c.label}</span>
              )}
            </span>
          );
        })}
      </nav>
      {rightSlot ? (
        <div className="flex items-center gap-2">{rightSlot}</div>
      ) : null}
    </header>
  );
}
