"use client";

/**
 * Layout du hub Paramètres unifié (`/parametres`) et de TOUTES ses pages.
 *
 * Pôle-neutre : aucun changement de pôle quand on entre dans un réglage
 * (Phil 2026-10-04 : « en cliquant sur les paramètres depuis Gestion
 * d'entreprises, je me suis retrouvé dans Construction »). Habillage
 * commun : barre latérale des réglages (sections du hub) + lien « Retour
 * à <pôle> » vers l'endroit d'où l'on vient. Fournit le thème, la garde
 * d'authentification et le contexte `useAppLayout` (bouton menu mobile
 * de l'AppTopbar des pages).
 */

import { createContext, useContext, useEffect, useMemo, useState } from "react";
import { usePathname } from "next/navigation";
import { ArrowLeft, Loader2, Settings, X } from "lucide-react";

import { Link } from "@/i18n/navigation";
import { ThemeProvider, type Theme } from "@/components/theme-provider";
import { useCurrentUser } from "@/hooks/use-current-user";
import { origineParametres } from "@/lib/parametres-origine";
import { sectionsVisibles } from "./sections";

type AppLayoutCtx = { onOpenSidebar: () => void };
const ctx = createContext<AppLayoutCtx>({ onOpenSidebar: () => {} });

/** Même nom que dans le layout Construction : les pages déplacées ici
 *  gardent leur `const { onOpenSidebar } = useAppLayout();`. */
export function useAppLayout() {
  return useContext(ctx);
}

export default function ParametresLayout({
  children
}: {
  children: React.ReactNode;
}) {
  const { user, loading } = useCurrentUser();
  const [open, setOpen] = useState(false);
  const pathname = usePathname() || "";
  const [origine, setOrigine] = useState(() => origineParametres(null));
  useEffect(() => {
    setOrigine(origineParametres(window.sessionStorage));
  }, []);
  useEffect(() => {
    setOpen(false);
  }, [pathname]);
  const sections = useMemo(() => (user ? sectionsVisibles(user) : []), [user]);

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-brand-950">
        <Loader2 className="h-6 w-6 animate-spin text-accent-500" />
      </div>
    );
  }
  if (!user) return null;

  const initialTheme = (user.theme_preference as Theme) || "light";
  const sansLocale = pathname.replace(/^\/(en|fr)(?=\/)/, "");

  const nav = (
    <nav className="flex h-full flex-col">
      <div className="border-b border-brand-800 px-3 py-3">
        <a
          href={origine.href}
          className="flex items-center gap-2 rounded-lg px-2 py-1.5 text-sm text-white/70 hover:bg-brand-900 hover:text-white"
        >
          <ArrowLeft className="h-4 w-4" /> Retour à {origine.label}
        </a>
        <Link
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          href={"/parametres" as any}
          className={`mt-1 flex items-center gap-2 rounded-lg px-2 py-1.5 text-sm font-semibold ${
            sansLocale === "/parametres" ? "bg-brand-900 text-accent-500" : "text-white hover:bg-brand-900"
          }`}
        >
          <Settings className="h-4 w-4" /> Paramètres
        </Link>
      </div>
      <div className="flex-1 overflow-y-auto px-3 py-3">
        {sections.map((s) => (
          <div key={s.key} className="mb-4">
            <p className="mb-1 flex items-center gap-1.5 px-2 text-[10px] font-bold uppercase tracking-wider text-accent-400">
              <s.icon className="h-3.5 w-3.5" /> {s.label}
            </p>
            {s.cards.map((c) => {
              const cible = c.href.split("?")[0];
              const actif = sansLocale === cible || sansLocale.startsWith(cible + "/");
              return (
                <Link
                  key={c.href}
                  // eslint-disable-next-line @typescript-eslint/no-explicit-any
                  href={c.href as any}
                  className={`flex items-center gap-2 rounded-lg px-2 py-1.5 text-sm ${
                    actif ? "bg-brand-900 text-accent-500" : "text-white/70 hover:bg-brand-900 hover:text-white"
                  }`}
                >
                  <c.icon className="h-4 w-4 shrink-0" />
                  <span className="truncate">{c.title}</span>
                </Link>
              );
            })}
          </div>
        ))}
      </div>
    </nav>
  );

  return (
    <ThemeProvider initialTheme={initialTheme}>
      <div className="flex min-h-screen bg-brand-950">
        <aside className="hidden w-64 shrink-0 border-r border-brand-800 bg-brand-950 lg:sticky lg:top-0 lg:block lg:h-screen">
          {nav}
        </aside>
        {open ? (
          <div className="fixed inset-0 z-40 lg:hidden">
            <div className="absolute inset-0 bg-black/60" onClick={() => setOpen(false)} />
            <aside className="absolute inset-y-0 left-0 w-72 border-r border-brand-800 bg-brand-950">
              <button
                type="button"
                onClick={() => setOpen(false)}
                className="absolute right-2 top-2 rounded-md p-1.5 text-white/70 hover:text-white"
                aria-label="Fermer"
              >
                <X className="h-5 w-5" />
              </button>
              {nav}
            </aside>
          </div>
        ) : null}
        <div className="min-w-0 flex-1">
          <ctx.Provider value={{ onOpenSidebar: () => setOpen(true) }}>{children}</ctx.Provider>
        </div>
      </div>
    </ThemeProvider>
  );
}
