"use client";

import {
  createContext,
  useContext,
  useEffect,
  useState
} from "react";
import { usePathname } from "next/navigation";
import {
  BarChart3,
  Briefcase,
  ChevronDown,
  ChevronRight,
  ExternalLink,
  Home,
  LayoutGrid,
  Loader2,
  LogOut,
  Menu,
  Settings,
  Sparkles,
  Target,
  X
} from "lucide-react";

import { Link } from "@/i18n/navigation";
import { ConfirmProvider } from "@/components/confirm-dialog";
import { HelpButton } from "@/components/help-button";
import { PortalCorner } from "@/components/portal-corner";
import { QGCommandBar } from "@/components/qg-command-bar";
import { ThemeProvider, type Theme } from "@/components/theme-provider";
import { useCurrentUser } from "@/hooks/use-current-user";
import { authedFetch } from "@/lib/auth";

type NavItem = {
  href: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  badge?: string | number;
};

type EntrepriseLite = {
  id: number;
  name: string;
  color_accent: string;
  health_label?: "good" | "warn" | "risk";
};

type Ctx = {
  onOpenSidebar: () => void;
  entreprises: EntrepriseLite[];
};
const ctx = createContext<Ctx>({
  onOpenSidebar: () => {},
  entreprises: []
});

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
  const [entreprises, setEntreprises] = useState<EntrepriseLite[]>([]);
  const [openTasksCount, setOpenTasksCount] = useState<number>(0);
  const pathname = usePathname() || "";

  useEffect(() => {
    if (loading || !user) return;
    let cancelled = false;
    void (async () => {
      try {
        const [healthRes, statsRes] = await Promise.all([
          authedFetch("/api/v1/entreprises/health"),
          authedFetch("/api/v1/entreprises/stats/overview")
        ]);
        if (cancelled) return;
        if (healthRes.ok) {
          const data = await healthRes.json();
          setEntreprises(
            Array.isArray(data)
              ? data.map((e: { id: number; name: string; color_accent: string; health_label: "good" | "warn" | "risk" }) => ({
                  id: e.id,
                  name: e.name,
                  color_accent: e.color_accent,
                  health_label: e.health_label
                }))
              : []
          );
        }
        if (statsRes.ok) {
          const s = await statsRes.json();
          setOpenTasksCount(Number(s?.taches_open) || 0);
        }
      } catch {
        /* silent */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [loading, user]);

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-[var(--qg-bg)]">
        <Loader2 className="h-6 w-6 animate-spin text-[var(--qg-accent)]" />
      </div>
    );
  }
  if (!user) return null;

  const initialTheme = (user.theme_preference as Theme) || "light";
  const allowed = (user.volets || []).includes("entreprises");

  const NAVIGATION: NavItem[] = [
    { href: "/entreprises", label: "Vue d'ensemble", icon: Home },
    { href: "/entreprises/dashboards", label: "Tableaux de bord", icon: LayoutGrid },
    {
      href: "/entreprises/taches",
      label: "Tâches",
      icon: Target,
      badge: openTasksCount || undefined
    },
    { href: "/entreprises/resumes", label: "Résumés IA", icon: Sparkles },
    { href: "/entreprises/vision", label: "Vision & Stratégie", icon: BarChart3 },
    { href: "/entreprises/comparatif", label: "Comparatif", icon: BarChart3 },
    { href: "/entreprises/projets", label: "Projets", icon: Briefcase }
  ];

  const REGLAGES: NavItem[] = [
    { href: "/entreprises/reglages", label: "Réglages", icon: Settings }
  ];

  function isActive(href: string) {
    if (href === "/entreprises")
      return pathname.endsWith("/entreprises");
    return pathname.includes(href);
  }

  return (
    <ThemeProvider initialTheme={initialTheme}>
      <div
        className="flex min-h-screen text-[var(--qg-text)]"
        style={{
          backgroundColor: "var(--qg-bg)",
          fontFamily:
            "var(--font-geist-sans, ui-sans-serif), system-ui, sans-serif"
        }}
        data-qg="true"
      >
        {sidebarOpen ? (
          <button
            type="button"
            aria-label="Fermer"
            onClick={() => setSidebarOpen(false)}
            className="fixed inset-0 z-40 bg-black/70 backdrop-blur-sm lg:hidden"
          />
        ) : null}

        <aside
          className={`fixed inset-y-0 left-0 z-50 w-60 flex-col transition-transform lg:static lg:flex lg:translate-x-0 ${
            sidebarOpen
              ? "flex translate-x-0"
              : "hidden -translate-x-full"
          }`}
          style={{
            backgroundColor: "var(--qg-sidebar-bg)",
            borderRight: "1px solid var(--qg-border)"
          }}
        >
          {/* Logo Q + QG */}
          <div
            className="flex items-center justify-between px-5 py-5"
            style={{ borderBottom: "1px solid var(--qg-border)" }}
          >
            <Link href="/entreprises" className="flex items-center gap-2">
              <span
                className="flex h-8 w-8 items-center justify-center rounded-md font-bold text-[var(--qg-bg)]"
                style={{
                  backgroundColor: "var(--qg-accent)",
                  fontFamily: "var(--font-fraunces, Georgia, serif)"
                }}
              >
                Q
              </span>
              <span className="text-base font-bold tracking-wide text-[var(--qg-text)]">
                QG
              </span>
            </Link>
            <button
              type="button"
              onClick={() => setSidebarOpen(false)}
              className="rounded-md p-2 text-[var(--qg-text-muted)] hover:bg-[var(--qg-bg-alt)] hover:text-[var(--qg-text)] lg:hidden"
              aria-label="Fermer"
            >
              <X className="h-5 w-5" />
            </button>
          </div>

          <nav className="flex-1 space-y-6 overflow-y-auto px-3 py-5">
            <SidebarSection title="Navigation">
              {NAVIGATION.map((item) => (
                <SidebarLink
                  key={item.href}
                  item={item}
                  active={isActive(item.href)}
                  onClick={() => setSidebarOpen(false)}
                />
              ))}
            </SidebarSection>

            {entreprises.length > 0 ? (
              <SidebarSection title="Mes entreprises">
                {entreprises.slice(0, 8).map((e) => {
                  const dot =
                    e.health_label === "risk"
                      ? "#ff5566"
                      : e.health_label === "warn"
                      ? "#ffaa33"
                      : "#4ade80";
                  return (
                    <Link
                      key={e.id}
                      // eslint-disable-next-line @typescript-eslint/no-explicit-any
                      href={`/entreprises/${e.id}` as any}
                      onClick={() => setSidebarOpen(false)}
                      className={`flex items-center gap-2.5 rounded-md px-3 py-1.5 text-[13px] transition ${
                        pathname.includes(`/entreprises/${e.id}`)
                          ? "bg-[var(--qg-bg-alt)] text-[var(--qg-text)]"
                          : "text-[var(--qg-text-muted)] hover:bg-[var(--qg-bg-alt)] hover:text-[var(--qg-text)]"
                      }`}
                    >
                      <span
                        className="h-1.5 w-1.5 rounded-full flex-shrink-0"
                        style={{ backgroundColor: dot }}
                      />
                      <span className="truncate">{e.name}</span>
                    </Link>
                  );
                })}
                {entreprises.length > 8 ? (
                  <Link
                    // eslint-disable-next-line @typescript-eslint/no-explicit-any
                    href={"/entreprises" as any}
                    className="flex items-center gap-2.5 rounded-md px-3 py-1.5 text-[12px] text-[var(--qg-text-soft)] hover:text-[var(--qg-text-muted)]"
                  >
                    <span className="h-1.5 w-1.5 rounded-full bg-[var(--qg-text-soft)]" />
                    + {entreprises.length - 8} autres
                  </Link>
                ) : null}
              </SidebarSection>
            ) : null}

            <SidebarSection title="Réglages">
              {REGLAGES.map((item) => (
                <SidebarLink
                  key={item.href}
                  item={item}
                  active={isActive(item.href)}
                  onClick={() => setSidebarOpen(false)}
                />
              ))}
            </SidebarSection>
          </nav>

          <div
            className="px-3 py-4"
            style={{ borderTop: "1px solid var(--qg-border)" }}
          >
            {user.email ? (
              <p
                className="mb-2 truncate px-3 text-[10px] text-[var(--qg-text-soft)]"
                title={user.email}
              >
                {user.email}
              </p>
            ) : null}
            <Link
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
              href={"/connexion" as any}
              className="mb-1 flex items-center gap-2.5 rounded-md px-3 py-1.5 text-[12px] text-[var(--qg-text-muted)] hover:bg-[var(--qg-bg-alt)] hover:text-[var(--qg-text)]"
            >
              <Home className="h-3.5 w-3.5" />
              Accueil portail
            </Link>
            <button
              type="button"
              onClick={signOut}
              className="flex w-full items-center gap-2.5 rounded-md px-3 py-1.5 text-[12px] text-[var(--qg-text-muted)] hover:bg-[var(--qg-bg-alt)] hover:text-[var(--qg-text)]"
            >
              <LogOut className="h-3.5 w-3.5" />
              Se déconnecter
            </button>
          </div>
        </aside>

        <div className="flex min-w-0 flex-1 flex-col">
          <ctx.Provider
            value={{
              onOpenSidebar: () => setSidebarOpen(true),
              entreprises
            }}
          >
            <ConfirmProvider>
              <main className="flex-1 overflow-x-hidden">
                {allowed ? children : <NoAccess />}
              </main>
              <PortalCorner />
              {allowed ? <QGCommandBar /> : null}
              <HelpButton />
            </ConfirmProvider>
          </ctx.Provider>
        </div>
      </div>
    </ThemeProvider>
  );
}

function SidebarSection({
  title,
  children
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <p className="mb-2 px-3 text-[10px] font-bold uppercase tracking-[0.12em] text-[var(--qg-text-soft)]">
        {title}
      </p>
      <ul className="space-y-0.5">{children}</ul>
    </div>
  );
}

function SidebarLink({
  item,
  active,
  onClick
}: {
  item: NavItem;
  active: boolean;
  onClick?: () => void;
}) {
  return (
    <li>
      <Link
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        href={item.href as any}
        onClick={onClick}
        className={`flex items-center gap-2.5 rounded-md px-3 py-1.5 text-[13px] font-medium transition ${
          active
            ? "bg-[var(--qg-bg-alt)] text-[var(--qg-text)]"
            : "text-[var(--qg-text-muted)] hover:bg-[var(--qg-bg-alt)] hover:text-[var(--qg-text)]"
        }`}
      >
        <item.icon
          className={`h-4 w-4 flex-shrink-0 ${
            active ? "text-[var(--qg-accent)]" : ""
          }`}
        />
        <span className="flex-1">{item.label}</span>
        {item.badge ? (
          <span
            className="rounded-full px-1.5 py-0.5 text-[9px] font-bold text-[var(--qg-bg)]"
            style={{ backgroundColor: "var(--qg-accent)" }}
          >
            {item.badge}
          </span>
        ) : null}
      </Link>
    </li>
  );
}

function NoAccess() {
  return (
    <div className="mx-auto mt-20 max-w-md rounded-2xl border border-rose-500/40 bg-rose-500/5 p-6 text-center">
      <h2 className="text-lg font-bold text-white">Accès refusé</h2>
      <p className="mt-2 text-sm text-white/60">
        Ton compte n&apos;a pas accès au volet « Gestion d&apos;entreprises ».
      </p>
    </div>
  );
}

// Topbar QG-style — greeting Fraunces italic + métadonnées mono
export function QGTopbar({
  greeting,
  subtitle,
  rightSlot
}: {
  greeting: React.ReactNode;
  subtitle?: React.ReactNode;
  rightSlot?: React.ReactNode;
}) {
  const { onOpenSidebar } = useEntreprisesLayout();
  return (
    <header
      className="sticky top-0 z-30 flex min-h-[80px] items-center gap-3 px-5 py-4 lg:px-8"
      style={{
        backgroundColor: "var(--qg-bg-95)",
        backdropFilter: "blur(8px)",
        borderBottom: "1px solid var(--qg-border)"
      }}
    >
      <button
        type="button"
        onClick={onOpenSidebar}
        className="rounded-md p-2 text-[var(--qg-text-muted)] hover:bg-[var(--qg-bg-alt)] hover:text-[var(--qg-text)] lg:hidden"
        aria-label="Ouvrir la barre latérale"
      >
        <Menu className="h-5 w-5" />
      </button>
      <div className="min-w-0 flex-1">
        <h1
          className="text-[22px] font-bold leading-tight text-[var(--qg-text)] sm:text-[26px]"
          style={{ fontFamily: "var(--font-fraunces, Georgia, serif)" }}
        >
          {greeting}
        </h1>
        {subtitle ? (
          <p
            className="mt-1 text-[10px] uppercase tracking-[0.18em] text-[var(--qg-text-soft)]"
            style={{ fontFamily: "var(--font-mono, ui-monospace), monospace" }}
          >
            {subtitle}
          </p>
        ) : null}
      </div>
      {rightSlot ? (
        <div className="flex items-center gap-2">{rightSlot}</div>
      ) : null}
    </header>
  );
}

// Topbar simple pour les pages détail (breadcrumbs comme avant)
export function EntreprisesTopbar({
  breadcrumbs,
  rightSlot
}: {
  breadcrumbs: { label: string; href?: string }[];
  rightSlot?: React.ReactNode;
}) {
  const { onOpenSidebar } = useEntreprisesLayout();
  return (
    <header
      className="sticky top-0 z-30 flex h-16 items-center gap-3 px-4 lg:px-6"
      style={{
        backgroundColor: "var(--qg-bg-95)",
        backdropFilter: "blur(8px)",
        borderBottom: "1px solid var(--qg-border)"
      }}
    >
      <button
        type="button"
        onClick={onOpenSidebar}
        className="rounded-md p-2 text-[var(--qg-text-muted)] hover:bg-[var(--qg-bg-alt)] hover:text-[var(--qg-text)] lg:hidden"
        aria-label="Ouvrir la barre latérale"
      >
        <Menu className="h-5 w-5" />
      </button>
      <nav className="flex min-w-0 flex-1 items-center gap-2">
        {breadcrumbs.map((c, i) => {
          const isLast = i === breadcrumbs.length - 1;
          const cls = `truncate text-sm font-medium ${
            isLast
              ? "text-[var(--qg-text)]"
              : c.href
              ? "text-[var(--qg-text-muted)] hover:text-[var(--qg-accent)]"
              : "text-[var(--qg-text-soft)]"
          }`;
          return (
            <span key={i} className="flex items-center gap-2">
              {i > 0 ? (
                <ChevronRight className="h-3.5 w-3.5 text-[var(--qg-text-faint)]" />
              ) : null}
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
