"use client";

import { Menu, Search } from "lucide-react";
import { useEffect, useState } from "react";

import { Link } from "@/i18n/navigation";
import { GlobalSearch } from "@/components/global-search";
import { KratosLogo } from "@/components/kratos-logo";
import { NotificationBell } from "@/components/notification-bell";
import { ThemeToggle } from "@/components/theme-toggle";

type Crumb = { label: string; href?: string };

function useIsMobile(breakpointPx = 640): boolean {
  const [isMobile, setIsMobile] = useState(false);
  useEffect(() => {
    if (typeof window === "undefined") return;
    const mq = window.matchMedia(`(max-width: ${breakpointPx - 1}px)`);
    const update = () => setIsMobile(mq.matches);
    update();
    mq.addEventListener("change", update);
    return () => mq.removeEventListener("change", update);
  }, [breakpointPx]);
  return isMobile;
}

export function AppTopbar({
  breadcrumbs,
  onOpenSidebar,
  rightSlot,
  searchPlaceholder,
  onSearch
}: {
  breadcrumbs: Crumb[];
  onOpenSidebar: () => void;
  rightSlot?: React.ReactNode;
  searchPlaceholder?: string;
  onSearch?: (query: string) => void;
}) {
  const isMobile = useIsMobile();
  const kratosSize = isMobile ? 56 : 144;

  return (
    <header className="sticky top-0 z-30 border-b border-brand-800 bg-brand-950/95 px-4 backdrop-blur lg:px-6">
      {/* Ligne 1 : menu + breadcrumb + Kratos. Sur mobile la deuxième
          ligne héberge les actions pour éviter le chevauchement. */}
      <div className="flex min-h-[64px] items-center gap-3 lg:min-h-[152px]">
        <button
          type="button"
          onClick={onOpenSidebar}
          className="rounded-md p-2 text-white/80 hover:bg-brand-900 hover:text-white lg:hidden"
          aria-label="Open sidebar"
        >
          <Menu className="h-5 w-5" />
        </button>

        <nav
          aria-label="Breadcrumb"
          className="flex min-w-0 flex-1 items-center gap-2"
        >
          {breadcrumbs.map((c, i) => {
            const isLast = i === breadcrumbs.length - 1;
            const labelClass = `truncate text-sm font-medium ${
              isLast
                ? "text-white"
                : c.href
                ? "text-white/60 hover:text-accent-500"
                : "text-white/50"
            }`;
            return (
              <span key={i} className="flex items-center gap-2 min-w-0">
                {i > 0 ? <span className="text-white/30">/</span> : null}
                {!isLast && c.href ? (
                  <Link
                    // eslint-disable-next-line @typescript-eslint/no-explicit-any
                    href={c.href as any}
                    className={labelClass}
                  >
                    {c.label}
                  </Link>
                ) : (
                  <span className={labelClass}>{c.label}</span>
                )}
              </span>
            );
          })}
        </nav>

        {/* Actions desktop : tout sur la même ligne */}
        <div className="hidden lg:flex items-center gap-3">
          <ThemeToggle />
          <NotificationBell />
          {onSearch ? (
            <div className="relative min-w-[220px]">
              <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-white/40" />
              <input
                type="search"
                placeholder={searchPlaceholder || "Filtrer…"}
                onChange={(e) => onSearch(e.target.value)}
                className="w-full rounded-lg border border-brand-800 bg-brand-900 py-2 pl-9 pr-3 text-sm text-white placeholder:text-white/40 focus:border-accent-500 focus:outline-none focus:ring-2 focus:ring-accent-500/40"
              />
            </div>
          ) : (
            <GlobalSearch />
          )}
          {rightSlot ? (
            <div className="flex items-center gap-2">{rightSlot}</div>
          ) : null}
        </div>

        {/* Kratos : taille réduite sur mobile, statique à droite */}
        <KratosLogo size={kratosSize} floating={false} />
      </div>

      {/* Ligne 2 mobile : actions sur leur propre rangée pour éviter
          que le breadcrumb, les icônes et le bouton primaire ne se
          chevauchent. Scroll horizontal si vraiment trop de boutons. */}
      <div className="flex items-center gap-2 overflow-x-auto pb-2 lg:hidden">
        <ThemeToggle />
        <NotificationBell />
        {onSearch ? (
          <div className="relative flex-1 min-w-[140px]">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-white/40" />
            <input
              type="search"
              placeholder={searchPlaceholder || "Filtrer…"}
              onChange={(e) => onSearch(e.target.value)}
              className="w-full rounded-lg border border-brand-800 bg-brand-900 py-1.5 pl-9 pr-3 text-sm text-white placeholder:text-white/40 focus:border-accent-500 focus:outline-none focus:ring-2 focus:ring-accent-500/40"
            />
          </div>
        ) : (
          <div className="flex-1 min-w-0">
            <GlobalSearch />
          </div>
        )}
        {rightSlot ? (
          <div className="flex flex-shrink-0 items-center gap-2">
            {rightSlot}
          </div>
        ) : null}
      </div>
    </header>
  );
}
