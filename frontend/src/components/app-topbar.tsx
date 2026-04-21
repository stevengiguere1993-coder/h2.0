"use client";

import { Menu, Search } from "lucide-react";

import { Link } from "@/i18n/navigation";

type Crumb = { label: string; href?: string };

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
  return (
    <header className="sticky top-0 z-30 flex h-16 items-center gap-3 border-b border-brand-800 bg-brand-950/95 px-4 backdrop-blur lg:px-6">
      <button
        type="button"
        onClick={onOpenSidebar}
        className="rounded-md p-2 text-white/80 hover:bg-brand-900 hover:text-white lg:hidden"
        aria-label="Open sidebar"
      >
        <Menu className="h-5 w-5" />
      </button>

      <nav aria-label="Breadcrumb" className="flex min-w-0 flex-1 items-center gap-2">
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
            <span key={i} className="flex items-center gap-2">
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

      {onSearch ? (
        <div className="relative hidden min-w-[220px] md:block">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-white/40" />
          <input
            type="search"
            placeholder={searchPlaceholder || "Rechercher…"}
            onChange={(e) => onSearch(e.target.value)}
            className="w-full rounded-lg border border-brand-800 bg-brand-900 py-2 pl-9 pr-3 text-sm text-white placeholder:text-white/40 focus:border-accent-500 focus:outline-none focus:ring-2 focus:ring-accent-500/40"
          />
        </div>
      ) : null}

      {rightSlot ? <div className="flex items-center gap-2">{rightSlot}</div> : null}
    </header>
  );
}
