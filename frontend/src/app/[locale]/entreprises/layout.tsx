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
  Plus,
  Settings,
  Sparkles,
  Target,
  X
} from "lucide-react";

import { Link } from "@/i18n/navigation";
import { ConfirmProvider } from "@/components/confirm-dialog";
import { HelpButton } from "@/components/help-button";
import { KratosLogo } from "@/components/kratos-logo";
import { ThemeToggle } from "@/components/theme-toggle";
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
  const [addEntOpen, setAddEntOpen] = useState(false);
  const [newEntName, setNewEntName] = useState("");
  const [newEntBusy, setNewEntBusy] = useState(false);
  const [newEntErr, setNewEntErr] = useState<string | null>(null);

  async function createEntreprise() {
    const name = newEntName.trim();
    if (name.length < 1) return;
    setNewEntBusy(true);
    setNewEntErr(null);
    try {
      const res = await authedFetch("/api/v1/entreprises", {
        method: "POST",
        body: JSON.stringify({ name })
      });
      if (!res.ok) {
        const t = await res.text().catch(() => "");
        throw new Error(`HTTP ${res.status} ${t.slice(0, 200)}`);
      }
      const created = (await res.json()) as { id: number };
      setNewEntName("");
      setAddEntOpen(false);
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      window.location.assign(`/entreprises/${created.id}` as any);
    } catch (e) {
      setNewEntErr((e as Error).message);
    } finally {
      setNewEntBusy(false);
    }
  }
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
              ? data.map((e: { entreprise_id?: number; id?: number; name: string; color_accent: string; health_label: "good" | "warn" | "risk" }) => ({
                  // L'endpoint /health retourne `entreprise_id` ; legacy `id` gardé en fallback.
                  id: (e.entreprise_id ?? e.id) as number,
                  name: e.name,
                  color_accent: e.color_accent,
                  health_label: e.health_label
                })).filter((e) => Number.isFinite(e.id))
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
  // Le volet Gestion d'entreprise est restreint aux owners pour
  // l'instant — l'assignation des tâches utilise les users (pas les
  // employés) et certains modules ne sont pas prêts pour les autres
  // rôles. Dès qu'on aura clarifié employés vs users, on rouvrira aux
  // admins/managers.
  const allowed =
    (user.volets || []).includes("entreprises") && user.role === "owner";

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

            <SidebarSection
              title="Mes entreprises"
              action={
                <button
                  type="button"
                  onClick={() => setAddEntOpen(true)}
                  title="Ajouter une entreprise"
                  className="rounded p-0.5 text-[var(--qg-text-soft)] hover:bg-[var(--qg-bg-alt)] hover:text-[var(--qg-text)]"
                >
                  <Plus className="h-3.5 w-3.5" />
                </button>
              }
            >
              {entreprises.length === 0 ? (
                <li className="px-3 py-1.5 text-[11px] text-[var(--qg-text-soft)]">
                  Aucune entreprise. Clique sur + pour en créer une.
                </li>
              ) : null}
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
              {/* Kratos + ThemeToggle intégrés dans QGTopbar/EntreprisesTopbar */}
              {allowed ? <QGCommandBar /> : null}
              <HelpButton />
              {addEntOpen ? (
                <div
                  className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm p-4"
                  onClick={() => !newEntBusy && setAddEntOpen(false)}
                >
                  <div
                    className="w-full max-w-md rounded-2xl border p-5 shadow-2xl"
                    style={{
                      backgroundColor: "var(--qg-card-bg)",
                      borderColor: "var(--qg-border)"
                    }}
                    onClick={(e) => e.stopPropagation()}
                  >
                    <h3
                      className="text-base font-bold"
                      style={{ color: "var(--qg-text)" }}
                    >
                      Nouvelle entreprise
                    </h3>
                    <p
                      className="mt-1 text-xs"
                      style={{ color: "var(--qg-text-muted)" }}
                    >
                      Crée une fiche entreprise. Tu pourras ajouter NEQ,
                      type, partenaires et tâches après.
                    </p>
                    <label
                      className="mt-4 block text-[11px] font-semibold uppercase tracking-wider"
                      style={{ color: "var(--qg-text-soft)" }}
                    >
                      Nom de l'entreprise
                    </label>
                    <input
                      autoFocus
                      type="text"
                      value={newEntName}
                      onChange={(e) => setNewEntName(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") void createEntreprise();
                        if (e.key === "Escape" && !newEntBusy)
                          setAddEntOpen(false);
                      }}
                      className="mt-1 w-full rounded-md border px-3 py-2 text-sm focus:outline-none focus:ring-1"
                      style={{
                        backgroundColor: "var(--qg-bg)",
                        color: "var(--qg-text)",
                        borderColor: "var(--qg-border)"
                      }}
                      placeholder="Ex. 8900 St-Hubert Inc."
                    />
                    {newEntErr ? (
                      <p className="mt-2 text-[11px] text-rose-500">
                        {newEntErr}
                      </p>
                    ) : null}
                    <div className="mt-4 flex justify-end gap-2">
                      <button
                        type="button"
                        onClick={() => setAddEntOpen(false)}
                        disabled={newEntBusy}
                        className="rounded-md border px-3 py-1.5 text-xs font-semibold disabled:opacity-50"
                        style={{
                          color: "var(--qg-text-muted)",
                          borderColor: "var(--qg-border)"
                        }}
                      >
                        Annuler
                      </button>
                      <button
                        type="button"
                        onClick={() => void createEntreprise()}
                        disabled={newEntBusy || newEntName.trim().length < 1}
                        className="rounded-md bg-violet-500 px-3 py-1.5 text-xs font-semibold text-white hover:bg-violet-400 disabled:opacity-50"
                      >
                        {newEntBusy ? "Création…" : "Créer"}
                      </button>
                    </div>
                  </div>
                </div>
              ) : null}
            </ConfirmProvider>
          </ctx.Provider>
        </div>
      </div>
    </ThemeProvider>
  );
}

function SidebarSection({
  title,
  children,
  action
}: {
  title: string;
  children: React.ReactNode;
  action?: React.ReactNode;
}) {
  return (
    <div>
      <div className="mb-2 flex items-center justify-between px-3">
        <p className="text-[10px] font-bold uppercase tracking-[0.12em] text-[var(--qg-text-soft)]">
          {title}
        </p>
        {action ? <div className="flex items-center">{action}</div> : null}
      </div>
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
      className="sticky top-0 z-30 px-5 lg:px-8"
      style={{
        backgroundColor: "var(--qg-bg-95)",
        backdropFilter: "blur(8px)",
        borderBottom: "1px solid var(--qg-border)",
        paddingTop: "calc(env(safe-area-inset-top) + 1rem)",
        paddingBottom: "1rem"
      }}
    >
      {/* Ligne 1 : menu (mobile) + greeting + ThemeToggle + Kratos */}
      <div className="flex min-h-[64px] items-center gap-2 lg:min-h-[120px] lg:gap-3">
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
        {/* Desktop : rightSlot inline avec greeting */}
        {rightSlot ? (
          <div className="hidden lg:flex items-center gap-2">{rightSlot}</div>
        ) : null}
        <ThemeToggle />
        <div className="lg:hidden">
          <KratosLogo size={64} floating={false} />
        </div>
        <div className="hidden lg:block">
          <KratosLogo size={144} floating={false} />
        </div>
      </div>

      {/* Ligne 2 mobile : rightSlot (Briefing complet, Nouvelle tâche…)
          sur sa propre rangée pour ne pas chevaucher le greeting. */}
      {rightSlot ? (
        <div className="flex items-center gap-2 overflow-x-auto pt-2 lg:hidden">
          {rightSlot}
        </div>
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
      className="sticky top-0 z-30 px-4 lg:px-6"
      style={{
        backgroundColor: "var(--qg-bg-95)",
        backdropFilter: "blur(8px)",
        borderBottom: "1px solid var(--qg-border)",
        paddingTop: "env(safe-area-inset-top)"
      }}
    >
      {/* Ligne 1 : menu + breadcrumbs + ThemeToggle + Kratos */}
      <div className="flex min-h-[64px] items-center gap-2 lg:min-h-[152px] lg:gap-3">
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
              <span key={i} className="flex items-center gap-2 min-w-0">
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
          <div className="hidden lg:flex items-center gap-2">{rightSlot}</div>
        ) : null}
        <ThemeToggle />
        <div className="lg:hidden">
          <KratosLogo size={64} floating={false} />
        </div>
        <div className="hidden lg:block">
          <KratosLogo size={144} floating={false} />
        </div>
      </div>

      {/* Ligne 2 mobile : rightSlot sous les breadcrumbs */}
      {rightSlot ? (
        <div className="flex items-center gap-2 overflow-x-auto pb-2 lg:hidden">
          {rightSlot}
        </div>
      ) : null}
    </header>
  );
}
