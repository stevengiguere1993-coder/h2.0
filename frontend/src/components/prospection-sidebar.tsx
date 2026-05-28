"use client";

import { useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import {
  BarChart3,
  Building2,
  Calendar,
  Home,
  Layers,
  LogOut,
  Map as MapIcon,
  MapPin,
  Plus,
  Settings,
  Smartphone,
  Sparkles,
  Sun,
  Trello,
  UserCircle,
  X
} from "lucide-react";

import { Link } from "@/i18n/navigation";
import { authedFetch, type UserRole } from "@/lib/auth";
import { useCurrentUser } from "@/hooks/use-current-user";
import { AccountBadge } from "@/components/account-badge";

type DealLite = {
  id: number;
  address: string;
  /** Priorité utilisée comme statut d'archivage : 'termine' /
   *  'abandonne' → range le deal dans le sous-dossier correspondant.
   *  Toute autre valeur (urgent, eleve, moyenne, a_venir, etc.) →
   *  liste principale. */
  priority: string;
};

type NavItem = {
  href: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  minRole?: UserRole;
};

type NavSection = {
  label: string;
  items: NavItem[];
};

// Sidebar Prospection découpée en sections (style Monday/Notion).
// Tous les items opérationnels restent accessibles aux employés ;
// seul Paramètres exige manager+.
const PROSPECTION_SECTIONS: NavSection[] = [
  {
    label: "Accueil",
    items: [
      {
        href: "/prospection/aujourdhui",
        label: "Aujourd'hui",
        icon: Sun,
        minRole: "employee"
      },
      {
        href: "/prospection/agenda",
        label: "Agenda",
        icon: Calendar,
        minRole: "employee"
      }
    ]
  },
  {
    label: "Prospection",
    items: [
      {
        href: "/prospection",
        label: "Carte",
        icon: MapIcon,
        minRole: "employee"
      },
      {
        href: "/prospection/leads",
        label: "Suivi de leads",
        icon: Trello,
        minRole: "employee"
      },
      {
        href: "/prospection/analyses-leads",
        label: "Analyses des leads",
        icon: Sparkles,
        minRole: "employee"
      },
      {
        href: "/prospection/immeubles-mtl",
        label: "Rôles fonciers",
        icon: Building2,
        minRole: "employee"
      },
      {
        href: "/prospection/lists",
        label: "Listes (segments)",
        icon: Layers,
        minRole: "employee"
      },

      {
        href: "/prospection/dashboard",
        label: "Dashboard",
        icon: BarChart3,
        minRole: "employee"
      }
    ]
  },
  // Section « Pipeline » — la liste des deals est rendue
  // dynamiquement dans le composant, comme la section « Mes
  // entreprises » du volet Gestion d'entreprises. Cette entrée
  // statique n'est qu'un fallback / lien header. La logique de
  // rendu est dans <ProspectionSidebar> directement.
  {
    label: "Pipeline",
    items: []
  },
  {
    label: "Ressources",
    items: [
      {
        href: "/prospection/parametres",
        label: "Paramètres",
        icon: Settings,
        minRole: "manager"
      }
    ]
  }
];

const ROLE_RANK: Record<UserRole, number> = {
  employee: 1,
  manager: 2,
  admin: 3,
  owner: 4
};

function canSee(role: UserRole | undefined, min: UserRole = "manager") {
  return ROLE_RANK[role || "employee"] >= ROLE_RANK[min];
}

export function ProspectionSidebar({
  open,
  onClose,
  userEmail,
  onSignOut
}: {
  open: boolean;
  onClose: () => void;
  userEmail?: string;
  onSignOut: () => void;
}) {
  const pathname = usePathname();
  const { user } = useCurrentUser();
  const role = (user?.role as UserRole | undefined) || "employee";
  // Filtre chaque section selon les rôles. La section « Pipeline »
  // est conservée même si vide (la liste de deals est dynamique).
  const visibleSections = PROSPECTION_SECTIONS.map((s) => ({
    ...s,
    items: s.items.filter((i) => canSee(role, i.minRole))
  })).filter(
    (s) => s.items.length > 0 || s.label === "Pipeline"
  );

  // Liste des deals — fetchée pour alimenter la section Pipeline
  // (analogue de « Mes entreprises » dans la sidebar Entreprises).
  const [deals, setDeals] = useState<DealLite[]>([]);
  // ID en cours de drag pour la réorganisation de l'ordre.
  const [dragDealId, setDragDealId] = useState<number | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const r = await authedFetch("/api/v1/prospection/deals");
        if (!r.ok) return;
        const arr = (await r.json()) as Array<{
          id: number;
          address: string;
          priority?: string;
        }>;
        if (!cancelled)
          setDeals(
            arr.map((d) => ({
              id: d.id,
              address: d.address,
              priority: d.priority || "moyenne"
            }))
          );
      } catch {
        /* ignore — affiche simplement 0 deal */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [pathname]);

  async function reorderDeals(ids: number[]) {
    setDeals((prev) => {
      const byId = new Map(prev.map((d) => [d.id, d]));
      const sorted = ids
        .map((id) => byId.get(id))
        .filter((d): d is DealLite => Boolean(d));
      for (const d of prev) {
        if (!ids.includes(d.id)) sorted.push(d);
      }
      return sorted;
    });
    try {
      await authedFetch("/api/v1/prospection/deals/reorder", {
        method: "POST",
        body: JSON.stringify({ ids })
      });
    } catch {
      /* ignore — l'UI montrera le bon ordre au prochain reload */
    }
  }

  /** Drop handler — copie exacte du pattern Mes entreprises
   *  (`handleDragEntreprise`) qui marche sans crash. Sync, simple,
   *  pas de setTimeout. */
  function handleDealDrop(
    droppedOnId: number,
    target: "active" | "termine" | "abandonne"
  ) {
    if (dragDealId == null) return;
    const dragged = deals.find((d) => d.id === dragDealId);
    if (!dragged) {
      setDragDealId(null);
      return;
    }

    // Drop sur l'en-tête d'un dossier d'archive : patch priorité.
    if (target === "termine" || target === "abandonne") {
      void patchDealPriority(dragDealId, target);
      setDragDealId(null);
      return;
    }

    // Drop sur la liste principale, deal traîné déjà archivé →
    // réactive.
    if (
      dragged.priority === "termine" ||
      dragged.priority === "abandonne"
    ) {
      void patchDealPriority(dragDealId, "moyenne");
      setDragDealId(null);
      return;
    }

    // Drop sur un autre deal actif → réordonne.
    if (dragDealId === droppedOnId) {
      setDragDealId(null);
      return;
    }
    const ids = deals.map((d) => d.id);
    const fromIdx = ids.indexOf(dragDealId);
    const toIdx = ids.indexOf(droppedOnId);
    if (fromIdx < 0 || toIdx < 0) {
      setDragDealId(null);
      return;
    }
    ids.splice(fromIdx, 1);
    ids.splice(toIdx, 0, dragDealId);
    setDragDealId(null);
    void reorderDeals(ids);
  }

  async function patchDealPriority(dealId: number, priority: string) {
    const prev = deals;
    setDeals((xs) =>
      xs.map((d) => (d.id === dealId ? { ...d, priority } : d))
    );
    try {
      const r = await authedFetch(
        `/api/v1/prospection/deals/${dealId}`,
        { method: "PATCH", body: JSON.stringify({ priority }) }
      );
      if (!r.ok) throw new Error();
    } catch {
      setDeals(prev);
    }
  }

  async function createDeal() {
    const address = window.prompt(
      "Adresse du nouveau deal (ex. 5640 Salaberry) ?"
    );
    if (!address || !address.trim()) return;
    try {
      const r = await authedFetch("/api/v1/prospection/deals", {
        method: "POST",
        body: JSON.stringify({
          address: address.trim(),
          priority: "moyenne"
        })
      });
      if (!r.ok) return;
      const created = (await r.json()) as {
        id: number;
        address: string;
        priority?: string;
      };
      setDeals((xs) => [
        ...xs,
        {
          id: created.id,
          address: created.address,
          priority: created.priority || "moyenne"
        }
      ]);
    } catch {
      /* ignore */
    }
  }

  function isActive(href: string) {
    if (href === "/prospection") {
      return (
        pathname === "/prospection" ||
        pathname === "/fr/prospection" ||
        pathname === "/en/prospection"
      );
    }
    // Strip le préfixe locale : /fr/prospection/leads → /prospection/leads
    const stripped = pathname.replace(/^\/(fr|en)/, "");
    return stripped === href || stripped.startsWith(href + "/");
  }

  return (
    <>
      {open ? (
        <button
          type="button"
          aria-label="Close sidebar"
          onClick={onClose}
          className="fixed inset-0 z-40 bg-black/70 backdrop-blur-sm lg:hidden"
        />
      ) : null}

      <aside
        className={`fixed inset-y-0 left-0 z-50 w-64 flex-col border-r border-emerald-900/40 bg-brand-950 transition-transform lg:static lg:flex lg:translate-x-0 ${
          open ? "flex translate-x-0" : "hidden -translate-x-full"
        }`}
      >
        <div className="flex items-center justify-between border-b border-emerald-900/40 px-4 py-4">
          <Link href="/prospection" className="flex items-center gap-2">
            <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-emerald-500/15 text-emerald-400">
              <MapPin className="h-5 w-5" />
            </span>
            <span className="flex flex-col leading-tight">
              <span className="text-sm font-bold text-white">
                Prospection
              </span>
              <span className="text-[10px] uppercase tracking-wider text-emerald-400/80">
                Horizon
              </span>
            </span>
          </Link>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md p-1 text-white/40 hover:bg-brand-900 hover:text-white lg:hidden"
            aria-label="Close menu"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <nav className="flex-1 overflow-y-auto px-2 py-3">
          {visibleSections.map((section, idx) => (
            <div key={section.label} className={idx === 0 ? "" : "mt-4"}>
              <div className="flex items-center justify-between px-2 py-1">
                {section.label === "Pipeline" ? (
                  <Link
                    // eslint-disable-next-line @typescript-eslint/no-explicit-any
                    href={"/prospection/pipeline" as any}
                    onClick={onClose}
                    className="text-[10px] font-semibold uppercase tracking-wider text-emerald-500/80 transition hover:text-emerald-300"
                  >
                    {section.label}
                  </Link>
                ) : (
                  <p className="text-[10px] font-semibold uppercase tracking-wider text-emerald-500/80">
                    {section.label}
                  </p>
                )}
                {section.label === "Pipeline" ? (
                  <button
                    type="button"
                    onClick={createDeal}
                    title="Ajouter un deal"
                    className="rounded p-0.5 text-white/40 hover:bg-brand-900 hover:text-white"
                  >
                    <Plus className="h-3.5 w-3.5" />
                  </button>
                ) : null}
              </div>
              <ul className="space-y-0.5">
                {section.items.map((it) => {
                  const Icon = it.icon;
                  const active = isActive(it.href);
                  return (
                    <li key={it.href}>
                      <Link
                        // eslint-disable-next-line @typescript-eslint/no-explicit-any
                        href={it.href as any}
                        onClick={onClose}
                        className={`flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-sm transition ${
                          active
                            ? "bg-emerald-500/15 text-emerald-300"
                            : "text-white/70 hover:bg-brand-900 hover:text-white"
                        }`}
                      >
                        <Icon className="h-4 w-4" />
                        {it.label}
                      </Link>
                    </li>
                  );
                })}
              </ul>

              {/* Liste dynamique des deals sous la section Pipeline,
                  + 2 sous-dossiers archivés (Terminé / Abandonné). */}
              {section.label === "Pipeline" ? (
                <PipelineDealsList
                  deals={deals}
                  pathname={pathname}
                  onClose={onClose}
                  dragDealId={dragDealId}
                  setDragDealId={setDragDealId}
                  onDrop={(droppedOnId, target) =>
                    handleDealDrop(droppedOnId, target)
                  }
                />
              ) : null}
            </div>
          ))}

          <div className="mt-6 border-t border-brand-800 pt-3">
            <p className="px-2 py-1 text-[10px] font-semibold uppercase tracking-wider text-white/40">
              Mode mobile
            </p>
            <Link
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
              href={"/m/prospection" as any}
              onClick={onClose}
              className="flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-sm text-white/70 hover:bg-brand-900 hover:text-white"
            >
              <Smartphone className="h-4 w-4" />
              Drive-by (PWA)
            </Link>
          </div>

          <div className="mt-6 border-t border-brand-800 pt-3">
            <Link
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
              href={"/connexion" as any}
              onClick={onClose}
              className="flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-sm text-white/70 hover:bg-brand-900 hover:text-white"
            >
              <Home className="h-4 w-4" />
              Accueil du portail
            </Link>
          </div>
        </nav>

        <div className="border-t border-brand-800 px-2 py-3">
          <AccountBadge />
          <Link
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            href={"/profil" as any}
            onClick={onClose}
            className="mt-1 flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-sm text-white/70 hover:bg-brand-900 hover:text-white"
          >
            <UserCircle className="h-4 w-4" />
            Mon profil
          </Link>
          <button
            type="button"
            onClick={onSignOut}
            className="mt-1 flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-sm text-white/70 hover:bg-brand-900 hover:text-white"
          >
            <LogOut className="h-4 w-4" />
            Déconnexion
          </button>
        </div>
      </aside>
    </>
  );
}

/**
 * Sous-composant : la liste des deals dans la sidebar Pipeline,
 * découpée en :
 *   - liste principale (priority != termine, abandonne)
 *   - sous-dossier collapsible « Terminé » (priority = termine)
 *   - sous-dossier collapsible « Abandonné » (priority = abandonne)
 *
 * Drag & drop :
 *   - sur un deal de la liste principale → réordonne ; et si le deal
 *     traîné venait d'un dossier d'archive, on le réactive
 *     (priority = moyenne) en plus.
 *   - sur l'en-tête d'un dossier → archive le deal traîné
 *     (priority = termine ou abandonne).
 */
/**
 * Extrait l'ID du deal courant à partir du pathname Next.js.
 * Match strict sur le segment numérique pour éviter le bug de
 * substring matching (ex. deal #420 surligné quand on est sur
 * deal #2420). Retourne null si on n'est pas sur une page deal.
 */
function currentPipelineDealId(pathname: string): number | null {
  const m = pathname.match(/\/prospection\/pipeline\/(\d+)(?:\/|$)/);
  return m ? Number(m[1]) : null;
}

function PipelineDealsList({
  deals,
  pathname,
  onClose,
  dragDealId,
  setDragDealId,
  onDrop
}: {
  deals: DealLite[];
  pathname: string;
  onClose: () => void;
  dragDealId: number | null;
  setDragDealId: (id: number | null) => void;
  /** Drop unifié : `target` = "active" si lâché sur la liste
   *  principale, "termine" / "abandonne" sur l'en-tête d'un dossier. */
  onDrop: (
    droppedOnId: number,
    target: "active" | "termine" | "abandonne"
  ) => void;
}) {
  const [openTermine, setOpenTermine] = useState(false);
  const [openAbandonne, setOpenAbandonne] = useState(false);
  const activeDealId = currentPipelineDealId(pathname);

  const active = deals.filter(
    (d) => d.priority !== "termine" && d.priority !== "abandonne"
  );
  const termine = [...deals.filter((d) => d.priority === "termine")].sort(
    (a, b) => a.address.localeCompare(b.address, "fr-CA")
  );
  const abandonne = [
    ...deals.filter((d) => d.priority === "abandonne")
  ].sort((a, b) => a.address.localeCompare(b.address, "fr-CA"));

  return (
    <>
      {/* Liste principale (active) — mirror exact du pattern
          Mes entreprises : drop appelle juste le parent, qui
          consolide la logique. */}
      {active.length === 0 ? (
        <p className="px-2.5 py-1.5 text-[11px] text-white/40">
          Aucun deal — clique sur + pour en créer un.
        </p>
      ) : null}
      {active.map((d) => {
        const dragging = dragDealId === d.id;
        // Match segment-aware : compare l'ID extrait du pathname
        // strictement à d.id. Évite que /pipeline/2420 surligne
        // aussi le deal #420 (cf. bug fixé en PR #430 sur la
        // sidebar principale).
        const onPath = activeDealId === d.id;
        return (
          <div
            key={d.id}
            draggable
            onDragStart={(ev) => {
              try {
                ev.dataTransfer.setData("text/plain", String(d.id));
                ev.dataTransfer.effectAllowed = "move";
              } catch {
                /* ignore */
              }
              setDragDealId(d.id);
            }}
            onDragEnd={() => setDragDealId(null)}
            onDragOver={(ev) => {
              if (dragDealId != null) ev.preventDefault();
            }}
            onDrop={(ev) => {
              ev.preventDefault();
              ev.stopPropagation();
              onDrop(d.id, "active");
            }}
            className={dragging ? "opacity-50" : ""}
          >
            <Link
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
              href={`/prospection/pipeline/${d.id}` as any}
              onClick={onClose}
              draggable={false}
              className={`flex items-center gap-2.5 rounded-lg px-2.5 py-1.5 text-[13px] transition ${
                onPath
                  ? "bg-emerald-500/15 text-emerald-300"
                  : "text-white/70 hover:bg-brand-900 hover:text-white"
              }`}
            >
              <span className="h-1.5 w-1.5 flex-shrink-0 rounded-full bg-emerald-400/80" />
              <span className="truncate">{d.address}</span>
            </Link>
          </div>
        );
      })}

      <ArchiveFolder
        label="Terminé"
        target="termine"
        deals={termine}
        open={openTermine}
        setOpen={setOpenTermine}
        pathname={pathname}
        onClose={onClose}
        dragDealId={dragDealId}
        setDragDealId={setDragDealId}
        onDrop={onDrop}
      />

      <ArchiveFolder
        label="Abandonné"
        target="abandonne"
        deals={abandonne}
        open={openAbandonne}
        setOpen={setOpenAbandonne}
        pathname={pathname}
        onClose={onClose}
        dragDealId={dragDealId}
        setDragDealId={setDragDealId}
        onDrop={onDrop}
      />
    </>
  );
}

function ArchiveFolder({
  label,
  target,
  deals,
  open,
  setOpen,
  pathname,
  onClose,
  dragDealId,
  setDragDealId,
  onDrop
}: {
  label: string;
  target: "termine" | "abandonne";
  deals: DealLite[];
  open: boolean;
  setOpen: (v: boolean) => void;
  pathname: string;
  onClose: () => void;
  dragDealId: number | null;
  setDragDealId: (id: number | null) => void;
  onDrop: (
    droppedOnId: number,
    target: "active" | "termine" | "abandonne"
  ) => void;
}) {
  const activeDealId = currentPipelineDealId(pathname);
  return (
    <div
      className="mt-2"
      onDragOver={(ev) => {
        if (dragDealId != null) ev.preventDefault();
      }}
      onDrop={(ev) => {
        ev.preventDefault();
        ev.stopPropagation();
        if (dragDealId != null) {
          onDrop(dragDealId, target);
          setOpen(true);
        }
      }}
    >
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="ml-3 flex w-[calc(100%-0.75rem)] items-center gap-1.5 rounded-md px-2 py-1 text-left text-[11px] font-medium text-white/40 transition hover:bg-brand-900 hover:text-white/70"
      >
        <span className="text-[8px] opacity-70">{open ? "▼" : "▶"}</span>
        <span className="flex-1">{label}</span>
        <span className="rounded-full bg-white/5 px-1.5 text-[10px] font-bold text-white/50">
          {deals.length}
        </span>
      </button>
      {open ? (
        <div className="mt-0.5 space-y-0.5 pl-2">
          {deals.length === 0 ? (
            <p className="px-2.5 py-1 text-[11px] text-white/40">
              Glisse un deal ici pour l&apos;archiver.
            </p>
          ) : null}
          {deals.map((d) => {
            // Match segment-aware — cf. PipelineDealsList.
            const onPath = activeDealId === d.id;
            const dragging = dragDealId === d.id;
            return (
              <div
                key={d.id}
                draggable
                onDragStart={(ev) => {
                  try {
                    ev.dataTransfer.setData("text/plain", String(d.id));
                    ev.dataTransfer.effectAllowed = "move";
                  } catch {
                    /* ignore */
                  }
                  setDragDealId(d.id);
                }}
                onDragEnd={() => setDragDealId(null)}
                className={dragging ? "opacity-50" : ""}
              >
                <Link
                  // eslint-disable-next-line @typescript-eslint/no-explicit-any
                  href={`/prospection/pipeline/${d.id}` as any}
                  onClick={onClose}
                  draggable={false}
                  className={`flex items-center gap-2.5 rounded-md px-2.5 py-1 text-[12px] transition ${
                    onPath
                      ? "bg-emerald-500/15 text-emerald-300"
                      : "text-white/50 hover:bg-brand-900 hover:text-white/80"
                  }`}
                >
                  <span className="h-1 w-1 flex-shrink-0 rounded-full bg-white/30" />
                  <span className="truncate">{d.address}</span>
                </Link>
              </div>
            );
          })}
        </div>
      ) : null}
    </div>
  );
}