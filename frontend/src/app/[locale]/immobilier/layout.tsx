"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState
} from "react";
import { usePathname } from "next/navigation";
import {
  AlertTriangle,
  Building2,
  Check,
  ChevronDown,
  ClipboardList,
  Home,
  Loader2,
  LogOut,
  Menu,
  Pencil,
  Plus,
  Sparkles,
  Trash2,
  Users,
  Wrench,
  X
} from "lucide-react";

import { Link } from "@/i18n/navigation";
import { ConfirmProvider } from "@/components/confirm-dialog";
import { HorizonLogo } from "@/components/horizon-logo";
import { HelpButton } from "@/components/help-button";
import { KratosLogo } from "@/components/kratos-logo";
import { ThemeToggle } from "@/components/theme-toggle";
import { ThemeProvider, type Theme } from "@/components/theme-provider";
import { useCurrentUser } from "@/hooks/use-current-user";
import { authedFetch } from "@/lib/auth";

type NavItem = {
  href: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
};

const NAV: NavItem[] = [
  { href: "/immobilier", label: "Vue d'ensemble", icon: Building2 },
  { href: "/immobilier/immeubles", label: "Immeubles", icon: Building2 },
  { href: "/immobilier/locataires", label: "Locataires", icon: Users },
  { href: "/immobilier/baux", label: "Baux & paiements", icon: ClipboardList },
  { href: "/immobilier/renouvellements", label: "Renouvellements", icon: ClipboardList },
  { href: "/immobilier/maintenance", label: "Maintenance", icon: Wrench }
];

// ─── Context : entreprise active dans le volet immobilier ────────────

type EntrepriseLite = { id: number; name: string; color_accent: string };

type Ctx = {
  onOpenSidebar: () => void;
  // Entreprise active = celle dont on gère le portefeuille immobilier.
  // null = vue « Toutes les entreprises ».
  currentEntrepriseId: number | null;
  setCurrentEntrepriseId: (id: number | null) => void;
  entreprises: EntrepriseLite[];
  refreshEntreprises: () => Promise<void>;
};

const ctx = createContext<Ctx>({
  onOpenSidebar: () => {},
  currentEntrepriseId: null,
  setCurrentEntrepriseId: () => {},
  entreprises: [],
  refreshEntreprises: async () => {}
});

export function useImmobilierLayout() {
  return useContext(ctx);
}

const STORAGE_KEY = "h2-immo-entreprise-id";

export default function ImmobilierLayout({
  children
}: {
  children: React.ReactNode;
}) {
  const { user, loading, signOut } = useCurrentUser();
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const pathname = usePathname() || "";

  // Contexte « entreprise active » (persistant dans localStorage).
  const [currentEntrepriseId, _setEntrepriseId] = useState<number | null>(null);
  const [entreprises, setEntreprises] = useState<EntrepriseLite[]>([]);

  const setCurrentEntrepriseId = useCallback((id: number | null) => {
    _setEntrepriseId(id);
    if (typeof window !== "undefined") {
      try {
        if (id == null) window.localStorage.removeItem(STORAGE_KEY);
        else window.localStorage.setItem(STORAGE_KEY, String(id));
      } catch {
        /* ignore */
      }
    }
  }, []);

  // Hydrate depuis localStorage au mount
  useEffect(() => {
    if (typeof window === "undefined") return;
    try {
      const raw = window.localStorage.getItem(STORAGE_KEY);
      if (raw) {
        const n = Number(raw);
        if (Number.isFinite(n) && n > 0) _setEntrepriseId(n);
      }
    } catch {
      /* ignore */
    }
  }, []);

  const refreshEntreprises = useCallback(async () => {
    try {
      const res = await authedFetch("/api/v1/entreprises");
      if (!res.ok) return;
      const data = (await res.json()) as Array<{
        id: number;
        name: string;
        color_accent: string;
      }>;
      setEntreprises(
        data.map((e) => ({
          id: e.id,
          name: e.name,
          color_accent: e.color_accent
        }))
      );
    } catch {
      /* silent */
    }
  }, []);

  useEffect(() => {
    if (!user) return;
    void refreshEntreprises();
  }, [user, refreshEntreprises]);

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-brand-950">
        <Loader2 className="h-6 w-6 animate-spin text-sky-300" />
      </div>
    );
  }
  if (!user) return null;

  const initialTheme = (user.theme_preference as Theme) || "light";
  const allowed = (user.volets || []).includes("immobilier");

  function isActive(href: string) {
    if (href === "/immobilier")
      return pathname.endsWith("/immobilier");
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
            sidebarOpen ? "flex translate-x-0" : "hidden -translate-x-full"
          }`}
        >
          <div className="flex items-center justify-between border-b border-brand-800 px-4 py-4">
            <Link href="/immobilier" className="flex items-center gap-2">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <HorizonLogo className="h-9 w-auto object-contain" />
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

          {/* Sélecteur d'entreprise active (contexte du portefeuille) */}
          <EntrepriseSelector
            entreprises={entreprises}
            currentId={currentEntrepriseId}
            onChange={setCurrentEntrepriseId}
            onAdded={refreshEntreprises}
          />

          <nav className="flex-1 space-y-6 overflow-y-auto px-3 py-5">
            <div>
              <p className="mb-2 flex items-center gap-1.5 px-3 text-xs font-semibold uppercase tracking-wider text-sky-300">
                <Sparkles className="h-3 w-3" />
                Gestion immobilière
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
                            ? "bg-sky-500/15 text-sky-200"
                            : "text-white/70 hover:bg-brand-900 hover:text-white"
                        }`}
                      >
                        <item.icon
                          className={`h-4 w-4 flex-shrink-0 ${
                            active ? "text-sky-300" : ""
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
              <p className="mb-2 truncate px-3 text-xs text-white/50" title={user.email}>
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
            value={{
              onOpenSidebar: () => setSidebarOpen(true),
              currentEntrepriseId,
              setCurrentEntrepriseId,
              entreprises,
              refreshEntreprises
            }}
          >
            <ConfirmProvider>
              <main className="flex-1 overflow-x-hidden">
                {allowed ? children : <NoAccess />}
              </main>
              {/* Kratos + ThemeToggle intégrés dans ImmobilierTopbar */}
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
      <h2 className="text-lg font-bold text-white">Accès refusé</h2>
      <p className="mt-2 text-sm text-white/60">
        Ton compte n&apos;a pas accès au volet « Gestion immobilière ».
      </p>
    </div>
  );
}

export function ImmobilierTopbar({
  breadcrumbs,
  rightSlot
}: {
  breadcrumbs: { label: string; href?: string }[];
  rightSlot?: React.ReactNode;
}) {
  const { onOpenSidebar } = useImmobilierLayout();
  return (
    <header className="sticky top-0 z-30 flex min-h-[152px] items-center gap-3 border-b border-brand-800 bg-brand-950/95 px-4 backdrop-blur lg:px-6">
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
            isLast ? "text-white" : c.href ? "text-white/60 hover:text-sky-300" : "text-white/50"
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
      {rightSlot ? <div className="flex items-center gap-2">{rightSlot}</div> : null}
      <ThemeToggle />
      <KratosLogo size={144} floating={false} />
    </header>
  );
}

// ─── Sélecteur d'entreprise active dans la sidebar ─────────────────────

function EntrepriseSelector({
  entreprises,
  currentId,
  onChange,
  onAdded
}: {
  entreprises: EntrepriseLite[];
  currentId: number | null;
  onChange: (id: number | null) => void;
  onAdded: () => Promise<void>;
}) {
  const [open, setOpen] = useState(false);
  const [showCreate, setShowCreate] = useState(false);
  const [counts, setCounts] = useState<Record<number, number>>({});
  const [deleting, setDeleting] = useState<number | null>(null);
  const current = entreprises.find((e) => e.id === currentId) || null;

  // Charge le nb d'immeubles par entreprise pour signaler celles qui
  // sont vides (pas de portefeuille immobilier).
  async function loadCounts() {
    try {
      const res = await authedFetch(
        "/api/v1/immobilier/entreprises-counts"
      );
      if (!res.ok) return;
      const data = (await res.json()) as Array<{
        entreprise_id: number;
        nb_immeubles: number;
      }>;
      const map: Record<number, number> = {};
      for (const r of data) map[r.entreprise_id] = r.nb_immeubles;
      setCounts(map);
    } catch {
      /* silent */
    }
  }
  useEffect(() => {
    void loadCounts();
  }, [entreprises.length]);

  async function renameEntreprise(e: EntrepriseLite) {
    const name = window.prompt(`Nouveau nom pour « ${e.name} » :`, e.name);
    const trimmed = name?.trim();
    if (!trimmed || trimmed === e.name) return;
    try {
      const res = await authedFetch(`/api/v1/entreprises/${e.id}`, {
        method: "PATCH",
        body: JSON.stringify({ name: trimmed })
      });
      if (!res.ok) {
        alert((await res.text()).slice(0, 240) || `HTTP ${res.status}`);
        return;
      }
      await onAdded(); // refresh la liste
    } catch (err) {
      alert((err as Error).message);
    }
  }

  async function deleteEntreprise(e: EntrepriseLite) {
    const nb = counts[e.id] ?? 0;
    const warn =
      nb > 0
        ? `\n\n⚠ Cette entreprise détient ${nb} immeuble${nb > 1 ? "s" : ""}. La suppression retirera l'ownership et toutes les données liées (tâches, finance, etc.).`
        : "";
    if (
      !confirm(
        `Supprimer définitivement l'entreprise « ${e.name} » ?${warn}`
      )
    )
      return;
    setDeleting(e.id);
    try {
      const res = await authedFetch(`/api/v1/entreprises/${e.id}`, {
        method: "DELETE"
      });
      if (!res.ok && res.status !== 204) {
        const t = await res.text();
        alert(t.slice(0, 240) || `HTTP ${res.status}`);
        return;
      }
      // Si on supprime l'entreprise active, retombe sur « Toutes ».
      if (currentId === e.id) onChange(null);
      await onAdded(); // refresh la liste
      void loadCounts();
    } catch (err) {
      alert((err as Error).message);
    } finally {
      setDeleting(null);
    }
  }

  return (
    <div className="border-b border-brand-800 px-3 py-3">
      <p className="mb-1.5 px-1 text-[10px] font-semibold uppercase tracking-wider text-white/40">
        Suivi pour
      </p>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center justify-between gap-2 rounded-lg border border-brand-700 bg-brand-900 px-3 py-2 text-left text-sm transition hover:border-sky-400/50"
      >
        {current ? (
          <span className="flex min-w-0 items-center gap-2">
            <span
              className="h-2 w-2 flex-shrink-0 rounded-full"
              style={{ backgroundColor: current.color_accent }}
            />
            <span className="truncate font-bold text-white">
              {current.name}
            </span>
          </span>
        ) : (
          <span className="text-white/70">Toutes les entreprises</span>
        )}
        <ChevronDown
          className={`h-4 w-4 flex-shrink-0 text-white/50 transition ${
            open ? "rotate-180" : ""
          }`}
        />
      </button>
      {open ? (
        <div className="mt-1 max-h-72 overflow-y-auto rounded-lg border border-brand-700 bg-brand-950 py-1 shadow-2xl">
          <button
            type="button"
            onClick={() => {
              onChange(null);
              setOpen(false);
            }}
            className={`flex w-full items-center justify-between px-3 py-2 text-left text-sm transition hover:bg-brand-900 ${
              currentId == null ? "bg-sky-500/10 text-sky-200" : "text-white/80"
            }`}
          >
            <span>Toutes les entreprises</span>
            {currentId == null ? <Check className="h-3.5 w-3.5" /> : null}
          </button>
          {entreprises.length > 0 ? (
            <div className="my-1 border-t border-brand-800" />
          ) : null}
          {entreprises.map((e) => {
            const nb = counts[e.id] ?? 0;
            const isCurrent = currentId === e.id;
            return (
              <div
                key={e.id}
                className={`group flex items-center gap-1 px-1.5 py-0.5 transition hover:bg-brand-900 ${
                  isCurrent ? "bg-sky-500/10" : ""
                }`}
              >
                <button
                  type="button"
                  onClick={() => {
                    onChange(e.id);
                    setOpen(false);
                  }}
                  className={`flex min-w-0 flex-1 items-center justify-between gap-2 rounded px-1.5 py-1.5 text-left text-sm ${
                    isCurrent ? "text-sky-200" : "text-white/80"
                  }`}
                >
                  <span className="flex min-w-0 items-center gap-2">
                    <span
                      className="h-2 w-2 flex-shrink-0 rounded-full"
                      style={{ backgroundColor: e.color_accent }}
                    />
                    <span className="truncate">{e.name}</span>
                  </span>
                  <span className="flex flex-shrink-0 items-center gap-1.5">
                    <span
                      className={`rounded-full px-1.5 py-0.5 font-mono text-[10px] ${
                        nb === 0
                          ? "bg-white/5 text-white/40"
                          : "bg-sky-500/20 text-sky-200"
                      }`}
                      title={
                        nb === 0
                          ? "Aucun immeuble détenu"
                          : `${nb} immeuble${nb > 1 ? "s" : ""} détenu${nb > 1 ? "s" : ""}`
                      }
                    >
                      {nb}
                    </span>
                    {isCurrent ? (
                      <Check className="h-3.5 w-3.5" />
                    ) : null}
                  </span>
                </button>
                <button
                  type="button"
                  onClick={(ev) => {
                    ev.stopPropagation();
                    void renameEntreprise(e);
                  }}
                  className="flex-shrink-0 rounded p-1.5 text-white/30 opacity-0 transition hover:text-sky-300 group-hover:opacity-100"
                  title="Renommer cette entreprise"
                >
                  <Pencil className="h-3.5 w-3.5" />
                </button>
                <button
                  type="button"
                  onClick={(ev) => {
                    ev.stopPropagation();
                    void deleteEntreprise(e);
                  }}
                  disabled={deleting === e.id}
                  className="flex-shrink-0 rounded p-1.5 text-white/30 opacity-0 transition hover:text-rose-300 group-hover:opacity-100 disabled:opacity-50"
                  title="Supprimer cette entreprise"
                >
                  {deleting === e.id ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <Trash2 className="h-3.5 w-3.5" />
                  )}
                </button>
              </div>
            );
          })}
          <div className="my-1 border-t border-brand-800" />
          <button
            type="button"
            onClick={() => {
              setOpen(false);
              setShowCreate(true);
            }}
            className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm text-emerald-300 transition hover:bg-emerald-500/10"
          >
            <Plus className="h-3.5 w-3.5" />
            Nouvelle entreprise
          </button>
        </div>
      ) : null}

      {showCreate ? (
        <CreateEntrepriseModal
          onClose={() => setShowCreate(false)}
          onCreated={async (id) => {
            setShowCreate(false);
            await onAdded();
            onChange(id);
          }}
        />
      ) : null}
    </div>
  );
}

function CreateEntrepriseModal({
  onClose,
  onCreated
}: {
  onClose: () => void;
  onCreated: (id: number) => void | Promise<void>;
}) {
  const [name, setName] = useState("");
  const [neq, setNeq] = useState("");
  const [type, setType] = useState("immobiliere");
  const [color, setColor] = useState("#0ea5e9");
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setErr(null);
    try {
      const res = await authedFetch("/api/v1/entreprises", {
        method: "POST",
        body: JSON.stringify({
          name: name.trim(),
          neq: neq.trim() || null,
          type,
          color_accent: color,
          is_active: true
        })
      });
      if (!res.ok) {
        const t = await res.text();
        throw new Error(t.slice(0, 240) || `HTTP ${res.status}`);
      }
      const data = (await res.json()) as { id: number };
      await onCreated(data.id);
    } catch (e2) {
      setErr((e2 as Error).message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 z-[100] flex items-start justify-center overflow-y-auto bg-black/70 p-4 backdrop-blur-sm">
      <div className="my-8 w-full max-w-md rounded-2xl border border-brand-800 bg-brand-950 shadow-2xl">
        <div className="border-b border-brand-800 px-5 py-3">
          <h2 className="text-sm font-bold uppercase tracking-wider text-sky-300">
            Nouvelle entreprise propriétaire
          </h2>
        </div>
        <form onSubmit={submit} className="grid gap-3 p-5">
          <div>
            <label className="label">Nom</label>
            <input
              required
              value={name}
              onChange={(ev) => setName(ev.target.value)}
              className="input"
              placeholder="ex. Immo BGV inc."
            />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="label">NEQ (optionnel)</label>
              <input
                value={neq}
                onChange={(ev) => setNeq(ev.target.value)}
                className="input font-mono"
                maxLength={32}
              />
            </div>
            <div>
              <label className="label">Type</label>
              <select
                value={type}
                onChange={(ev) => setType(ev.target.value)}
                className="input"
              >
                <option value="immobiliere">Société immobilière</option>
                <option value="gestion">Société de gestion</option>
                <option value="investissement">Investissement</option>
                <option value="autre">Autre</option>
              </select>
            </div>
          </div>
          <div>
            <label className="label">Couleur</label>
            <div className="flex items-center gap-2">
              <input
                type="color"
                value={color}
                onChange={(ev) => setColor(ev.target.value)}
                className="h-9 w-12 cursor-pointer rounded-lg border border-white/15 bg-transparent"
              />
              <input
                value={color}
                onChange={(ev) => setColor(ev.target.value)}
                pattern="^#[0-9a-fA-F]{6}$"
                className="input flex-1 font-mono text-sm"
              />
            </div>
          </div>

          {err ? (
            <p className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
              <AlertTriangle className="mr-1.5 inline h-3.5 w-3.5" />
              {err}
            </p>
          ) : null}

          <div className="flex items-center justify-end gap-2 border-t border-brand-800 pt-3">
            <button type="button" onClick={onClose} className="btn-secondary text-sm">
              Annuler
            </button>
            <button
              type="submit"
              disabled={saving || !name.trim()}
              className="btn-accent inline-flex items-center text-sm disabled:opacity-60"
            >
              {saving ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                "Créer & sélectionner"
              )}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
