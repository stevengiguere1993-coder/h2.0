"use client";

import { useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import {
  BarChart3,
  Building2,
  Calculator,
  Calendar,
  Home,
  Layers,
  LogOut,
  Map,
  MapPin,
  Plus,
  Settings,
  Smartphone,
  Sun,
  Trello,
  UserCircle,
  X
} from "lucide-react";

import { Link } from "@/i18n/navigation";
import { authedFetch, type UserRole } from "@/lib/auth";
import { useCurrentUser } from "@/hooks/use-current-user";
import { AccountBadge } from "@/components/account-badge";

type DealLite = { id: number; address: string };

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
        icon: Map,
        minRole: "employee"
      },
      {
        href: "/prospection/leads",
        label: "Suivi de leads",
        icon: Trello,
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
        href: "/prospection/analyse",
        label: "Analyses financières",
        icon: Calculator,
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
        }>;
        if (!cancelled)
          setDeals(arr.map((d) => ({ id: d.id, address: d.address })));
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

  function handleDealDrop(droppedOnId: number) {
    if (dragDealId == null || dragDealId === droppedOnId) return;
    const ids = deals.map((d) => d.id);
    const fromIdx = ids.indexOf(dragDealId);
    const toIdx = ids.indexOf(droppedOnId);
    if (fromIdx < 0 || toIdx < 0) return;
    ids.splice(fromIdx, 1);
    ids.splice(toIdx, 0, dragDealId);
    setDragDealId(null);
    void reorderDeals(ids);
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
      const created = (await r.json()) as { id: number; address: string };
      setDeals((xs) => [
        ...xs,
        { id: created.id, address: created.address }
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
    return pathname.includes(href);
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
                <p className="text-[10px] font-semibold uppercase tracking-wider text-emerald-500/80">
                  {section.label}
                </p>
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

              {/* Liste dynamique des deals sous la section Pipeline. */}
              {section.label === "Pipeline" ? (
                <ul className="mt-0.5 space-y-0.5">
                  {deals.length === 0 ? (
                    <li className="px-2.5 py-1.5 text-[11px] text-white/40">
                      Aucun deal — clique sur + pour en créer un.
                    </li>
                  ) : null}
                  {deals.map((d) => {
                    const dragging = dragDealId === d.id;
                    const onPath = pathname.includes(
                      `/prospection/pipeline/${d.id}`
                    );
                    return (
                      <li key={d.id}>
                        <div
                          draggable
                          onDragStart={(ev) => {
                            // Évite que le navigateur tente de drag
                            // l'URL du <Link> enfant — on contrôle le
                            // payload nous-mêmes.
                            ev.dataTransfer.setData("text/plain", String(d.id));
                            ev.dataTransfer.effectAllowed = "move";
                            setDragDealId(d.id);
                          }}
                          onDragEnd={() => setDragDealId(null)}
                          onDragOver={(ev) => {
                            if (dragDealId != null) ev.preventDefault();
                          }}
                          onDrop={(ev) => {
                            ev.preventDefault();
                            ev.stopPropagation();
                            handleDealDrop(d.id);
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
                      </li>
                    );
                  })}
                </ul>
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
