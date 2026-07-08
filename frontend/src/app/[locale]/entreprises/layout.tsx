"use client";

import {
  createContext,
  useContext,
  useEffect,
  useState
} from "react";
import { usePathname } from "next/navigation";
import {
  ArrowDownAZ,
  BarChart3,
  Brain,
  Briefcase,
  Calendar,
  ChevronDown,
  ChevronRight,
  Clock,
  Compass,
  Contact as ContactIcon,
  CreditCard,
  ExternalLink,
  Home,
  Grid3x3,
  LayoutGrid,
  Loader2,
  LogOut,
  Menu,
  Plus,
  Settings,
  Target,
  Users,
  X
} from "lucide-react";

import { Link } from "@/i18n/navigation";
import { ConfirmProvider } from "@/components/confirm-dialog";
import { HelpButton } from "@/components/help-button";
import { HorizonLogo } from "@/components/horizon-logo";
import { KratosLogo } from "@/components/kratos-logo";
import { ThemeToggle } from "@/components/theme-toggle";
import { KratosFloating } from "@/components/kratos-floating";
import { QGCommandBar } from "@/components/qg-command-bar";
import { ThemeProvider, type Theme } from "@/components/theme-provider";
import { useCurrentUser } from "@/hooks/use-current-user";
import { authedFetch } from "@/lib/auth";

type NavItem = {
  href: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  badge?: string | number;
  // Décalage visuel en sous-item (« Tâches récurrentes » sous « Tâches »).
  indent?: boolean;
};

type EntrepriseLite = {
  id: number;
  name: string;
  color_accent: string;
  health_label?: "good" | "warn" | "risk";
  is_active: boolean;
  is_parent_company?: boolean;
};

type Ctx = {
  onOpenSidebar: () => void;
  entreprises: EntrepriseLite[];
  reorderEntreprises: (ids: number[]) => Promise<void>;
};
const ctx = createContext<Ctx>({
  onOpenSidebar: () => {},
  entreprises: [],
  reorderEntreprises: async () => {}
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
  // Accès au coffre « Abonnements » — l'onglet n'apparaît que pour les
  // utilisateurs autorisés (proprio + liste nominative).
  const [vaultAccess, setVaultAccess] = useState(false);
  const [addEntOpen, setAddEntOpen] = useState(false);
  // Toggle « tri alphabétique » dans la sidebar — purement visuel,
  // n'écrase pas les positions sauvegardées en DB.
  const [alphaSort, setAlphaSort] = useState(false);
  const [newEntName, setNewEntName] = useState("");
  const [newEntBusy, setNewEntBusy] = useState(false);
  const [newEntErr, setNewEntErr] = useState<string | null>(null);
  // ID en cours de drag pour l'ordre des entreprises dans la sidebar.
  const [dragId, setDragId] = useState<number | null>(null);

  async function reorderEntreprises(ids: number[]) {
    // MAJ optimiste : on réordonne le state localement, puis on
    // pousse côté serveur. En cas d'échec, on n'affiche pas d'erreur
    // bloquante — l'ordre reviendra au prochain reload.
    setEntreprises((prev) => {
      const byId = new Map(prev.map((e) => [e.id, e]));
      const sorted = ids
        .map((id) => byId.get(id))
        .filter((e): e is EntrepriseLite => Boolean(e));
      // Conserve les éventuels items hors `ids` à la fin (failsafe).
      for (const e of prev) {
        if (!ids.includes(e.id)) sorted.push(e);
      }
      return sorted;
    });
    try {
      await authedFetch("/api/v1/entreprises/reorder", {
        method: "POST",
        body: JSON.stringify({ ids })
      });
    } catch {
      /* ignore — l'UI montrera le bon ordre au prochain reload */
    }
  }

  /** Archive ou réactive une entreprise. `target` = "fermee" → met
   *  is_active=false (range dans le dossier Fermée). "active" →
   *  remet is_active=true. */
  async function archiveEntreprise(
    id: number,
    target: "fermee" | "active"
  ) {
    const wantActive = target === "active";
    const prev = entreprises;
    setEntreprises((xs) =>
      xs.map((e) =>
        e.id === id ? { ...e, is_active: wantActive } : e
      )
    );
    try {
      const r = await authedFetch(`/api/v1/entreprises/${id}`, {
        method: "PATCH",
        body: JSON.stringify({ is_active: wantActive })
      });
      if (!r.ok) throw new Error();
    } catch {
      setEntreprises(prev);
    }
  }

  function handleDragEntreprise(droppedOnId: number) {
    if (dragId == null || dragId === droppedOnId) return;
    // Si l'entreprise traînée est archivée, on la réactive en plus
    // de la déposer dans la liste principale.
    const dragged = entreprises.find((e) => e.id === dragId);
    const target = entreprises.find((e) => e.id === droppedOnId);
    if (dragged && !dragged.is_active && target && target.is_active) {
      void archiveEntreprise(dragId, "active");
      setDragId(null);
      return;
    }
    const ids = entreprises.map((e) => e.id);
    const fromIdx = ids.indexOf(dragId);
    const toIdx = ids.indexOf(droppedOnId);
    if (fromIdx < 0 || toIdx < 0) return;
    ids.splice(fromIdx, 1);
    ids.splice(toIdx, 0, dragId);
    setDragId(null);
    void reorderEntreprises(ids);
  }

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
        const [healthRes, statsRes, vaultRes] = await Promise.all([
          authedFetch(
            "/api/v1/entreprises/health?include_archived=true"
          ),
          authedFetch("/api/v1/entreprises/stats/overview"),
          authedFetch("/api/v1/subscriptions/vault-status")
        ]);
        if (cancelled) return;
        if (vaultRes.ok) {
          const v = await vaultRes.json();
          setVaultAccess(!!v?.has_access);
        }
        if (healthRes.ok) {
          const data = await healthRes.json();
          setEntreprises(
            Array.isArray(data)
              ? data.map((e: { entreprise_id?: number; id?: number; name: string; color_accent: string; health_label: "good" | "warn" | "risk"; is_active?: boolean }) => ({
                  // L'endpoint /health retourne `entreprise_id` ; legacy `id` gardé en fallback.
                  id: (e.entreprise_id ?? e.id) as number,
                  name: e.name,
                  color_accent: e.color_accent,
                  health_label: e.health_label,
                  is_active: e.is_active !== false
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
  // Le volet Gestion d'entreprise est ouvert aux owners ET admins
  // (« accès total » dans la définition des rôles). Reste fermé aux
  // managers/employés tant que certains modules ne sont pas prêts pour
  // ces rôles (l'assignation des tâches utilise les users, pas les
  // employés).
  const allowed =
    (user.volets || []).includes("entreprises") &&
    (user.role === "owner" || user.role === "admin");

  const NAVIGATION: NavItem[] = [
    { href: "/entreprises", label: "Entreprises", icon: Briefcase },
    { href: "/entreprises/dashboards", label: "Tableaux de bord", icon: LayoutGrid },
    {
      href: "/entreprises/taches",
      label: "Tâches",
      icon: Target,
      badge: openTasksCount || undefined
    },
    { href: "/entreprises/kratos", label: "Kratos · Cerveau", icon: Brain },
    { href: "/entreprises/rencontres", label: "Rencontres", icon: Calendar },
    { href: "/entreprises/feuille-de-temps", label: "Feuille de temps", icon: Clock },
    { href: "/entreprises/organigramme", label: "Organigramme", icon: Users },
    {
      href: "/entreprises/distribution-taches",
      label: "Distribution des tâches",
      icon: Grid3x3
    },
    { href: "/entreprises/vision", label: "Vision & Stratégie", icon: BarChart3 },
    { href: "/entreprises/comparatif", label: "Comparatif", icon: BarChart3 },
    { href: "/entreprises/projets", label: "Projets", icon: Briefcase },
    { href: "/entreprises/contacts", label: "Contacts", icon: ContactIcon },
    ...(vaultAccess
      ? [
          {
            href: "/entreprises/abonnements",
            label: "Abonnements",
            icon: CreditCard
          }
        ]
      : [])
  ];

  const REGLAGES: NavItem[] = [
    { href: "/parametres", label: "Réglages", icon: Settings }
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
              <HorizonLogo className="h-16 w-auto object-contain" />
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

            {/* La liste « Mes entreprises » était ici. Retirée :
                trop de bruit dans la sidebar. On accède désormais
                aux entreprises individuelles via la page
                /entreprises (lien « Entreprises » ci-dessus). */}

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
              entreprises,
              reorderEntreprises
            }}
          >
            <ConfirmProvider>
              <main className="flex-1 overflow-x-hidden">
                {allowed ? children : <NoAccess />}
              </main>
              {/* Kratos + ThemeToggle intégrés dans QGTopbar/EntreprisesTopbar */}
              {allowed ? <QGCommandBar /> : null}
              {allowed ? <KratosFloating /> : null}
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
        <p className="text-xs font-semibold uppercase tracking-wider text-[var(--qg-accent)]">
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
        className={`flex items-center gap-3 rounded-lg py-2 text-sm font-medium transition ${
          item.indent ? "pl-9 pr-3 text-[13px]" : "px-3"
        } ${
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
            className="rounded-full px-1.5 py-0.5 text-[9px] font-bold text-[var(--qg-accent-ink)]"
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
          <h1 className="text-2xl font-bold leading-tight text-[var(--qg-text)]">
            {greeting}
          </h1>
          {subtitle ? (
            <p className="mt-1 text-xs uppercase tracking-wider text-[var(--qg-text-soft)]">
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


/**
 * Sous-composant : la liste des entreprises dans la sidebar Mes
 * entreprises, découpée en :
 *   - liste principale (is_active = true)
 *   - sous-dossier collapsible « Fermée » (is_active = false), trié
 *     alphabétiquement
 *
 * Drag & drop :
 *   - drop sur une entreprise active → réordonne. Si l'entreprise
 *     traînée venait du dossier Fermée, le parent la réactive
 *     automatiquement avant le drop.
 *   - drop sur l'en-tête « Fermée » → archive l'entreprise.
 */
function EntrepriseListWithFolder({
  entreprises,
  alphaSort,
  pathname,
  onClose,
  dragId,
  setDragId,
  onReorderDrop,
  onArchive
}: {
  entreprises: EntrepriseLite[];
  /** Si `true`, la liste active est triée alphabétiquement à
   *  l'affichage (l'ordre manuel reste préservé en DB). */
  alphaSort: boolean;
  pathname: string;
  onClose: () => void;
  dragId: number | null;
  setDragId: (id: number | null) => void;
  onReorderDrop: (droppedOnId: number) => void;
  onArchive: (id: number, target: "fermee" | "active") => void;
}) {
  const [openClosed, setOpenClosed] = useState(false);
  const active = (() => {
    const arr = entreprises.filter((e) => e.is_active);
    return alphaSort
      ? [...arr].sort((a, b) => a.name.localeCompare(b.name, "fr-CA"))
      : arr;
  })();
  const closed = [...entreprises.filter((e) => !e.is_active)].sort(
    (a, b) => a.name.localeCompare(b.name, "fr-CA")
  );

  function startDrag(ev: React.DragEvent, id: number) {
    try {
      ev.dataTransfer.setData("text/plain", String(id));
      ev.dataTransfer.effectAllowed = "move";
    } catch {
      /* ignore */
    }
    setDragId(id);
  }

  return (
    <>
      {active.length === 0 ? (
        <li className="px-3 py-1.5 text-[11px] text-[var(--qg-text-soft)]">
          Aucune entreprise. Clique sur + pour en créer une.
        </li>
      ) : null}
      {active.map((e) => {
        const dot =
          e.health_label === "risk"
            ? "#fb7185"
            : e.health_label === "warn"
              ? "#fbbf24"
              : "#4ade80";
        const dragging = dragId === e.id;
        return (
          <div
            key={e.id}
            draggable
            onDragStart={(ev) => startDrag(ev, e.id)}
            onDragEnd={() => setDragId(null)}
            onDragOver={(ev) => {
              if (dragId != null) ev.preventDefault();
            }}
            onDrop={(ev) => {
              ev.preventDefault();
              ev.stopPropagation();
              onReorderDrop(e.id);
            }}
            className={dragging ? "opacity-50" : ""}
          >
            <Link
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
              href={`/entreprises/${e.id}` as any}
              onClick={onClose}
              draggable={false}
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
          </div>
        );
      })}

      <div
        className="mt-2"
        onDragOver={(ev) => {
          if (dragId != null) ev.preventDefault();
        }}
        onDrop={(ev) => {
          ev.preventDefault();
          ev.stopPropagation();
          if (dragId != null) {
            onArchive(dragId, "fermee");
            setDragId(null);
            setOpenClosed(true);
          }
        }}
      >
        <button
          type="button"
          onClick={() => setOpenClosed(!openClosed)}
          className="ml-3 flex w-[calc(100%-0.75rem)] items-center gap-1.5 rounded-md px-2 py-1 text-left text-[11px] font-medium text-[var(--qg-text-faint)] transition hover:bg-[var(--qg-bg-alt)] hover:text-[var(--qg-text-muted)]"
        >
          <span className="text-[8px] opacity-70">{openClosed ? "▼" : "▶"}</span>
          <span className="flex-1">Fermée</span>
          <span className="rounded-full bg-white/5 px-1.5 text-[10px] font-bold text-[var(--qg-text-soft)]">
            {closed.length}
          </span>
        </button>
        {openClosed ? (
          <div className="mt-0.5 space-y-0.5 pl-2">
            {closed.length === 0 ? (
              <p className="px-2.5 py-1 text-[11px] text-[var(--qg-text-soft)]">
                Glisse une entreprise ici pour la fermer.
              </p>
            ) : null}
            {closed.map((e) => {
              const dragging = dragId === e.id;
              return (
                <div
                  key={e.id}
                  draggable
                  onDragStart={(ev) => startDrag(ev, e.id)}
                  onDragEnd={() => setDragId(null)}
                  className={dragging ? "opacity-50" : ""}
                >
                  <Link
                    // eslint-disable-next-line @typescript-eslint/no-explicit-any
                    href={`/entreprises/${e.id}` as any}
                    onClick={onClose}
                    draggable={false}
                    className={`flex items-center gap-2.5 rounded-md px-2.5 py-1 text-[12px] transition ${
                      pathname.includes(`/entreprises/${e.id}`)
                        ? "bg-[var(--qg-bg-alt)] text-[var(--qg-text)]"
                        : "text-[var(--qg-text-soft)] hover:bg-[var(--qg-bg-alt)] hover:text-[var(--qg-text-muted)]"
                    }`}
                  >
                    <span className="h-1 w-1 flex-shrink-0 rounded-full bg-[var(--qg-text-faint)]" />
                    <span className="truncate">{e.name}</span>
                  </Link>
                </div>
              );
            })}
          </div>
        ) : null}
      </div>
    </>
  );
}
