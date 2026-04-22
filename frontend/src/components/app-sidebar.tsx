"use client";

import { useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import {
  Briefcase,
  Calendar,
  ClipboardCheck,
  Clock,
  DollarSign,
  FileText,
  HardHat,
  Home,
  Contact,
  LogOut,
  Palmtree,
  ShieldCheck,
  ShoppingCart,
  Truck,
  UserCircle,
  Users,
  X
} from "lucide-react";

import { Link } from "@/i18n/navigation";
import { authedFetch, type UserRole } from "@/lib/auth";
import { useCurrentUser } from "@/hooks/use-current-user";

type NavItem = {
  href: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  /** Minimum role required to see this item. Default: manager. */
  minRole?: UserRole;
};

const CONSTRUCTION_NAV: NavItem[] = [
  { href: "/app", label: "Accueil", icon: Home, minRole: "employee" },
  { href: "/app/crm", label: "CRM / Prospects", icon: Users, minRole: "manager" },
  { href: "/app/clients", label: "Clients", icon: Contact, minRole: "manager" },
  { href: "/app/soumissions", label: "Soumissions", icon: FileText, minRole: "manager" },
  { href: "/app/projets", label: "Projets", icon: Briefcase, minRole: "employee" },
  { href: "/app/agenda", label: "Agenda", icon: Calendar, minRole: "employee" },
  { href: "/app/bons", label: "Bons de travail", icon: ClipboardCheck, minRole: "manager" },
  { href: "/app/punch", label: "Punch / Temps", icon: Clock, minRole: "manager" },
  { href: "/app/facturation", label: "Facturation", icon: DollarSign, minRole: "manager" },
  { href: "/app/achats", label: "Achats / PO", icon: ShoppingCart, minRole: "manager" }
];

const RESOURCES_NAV: NavItem[] = [
  { href: "/app/employes", label: "Employés", icon: UserCircle, minRole: "admin" },
  { href: "/app/sous-traitants", label: "Sous-traitants", icon: HardHat, minRole: "admin" },
  { href: "/app/fournisseurs", label: "Fournisseurs", icon: Truck, minRole: "admin" },
  { href: "/app/services-catalogue", label: "Catalogue services", icon: ClipboardCheck, minRole: "manager" },
  { href: "/app/conges", label: "Congés", icon: Palmtree, minRole: "manager" },
  { href: "/app/utilisateurs", label: "Utilisateurs", icon: ShieldCheck, minRole: "owner" }
];

const ROLE_RANK: Record<UserRole, number> = {
  owner: 4,
  admin: 3,
  manager: 2,
  employee: 1
};

function canSee(role: UserRole | undefined, min: UserRole = "manager") {
  if (!role) return false;
  return ROLE_RANK[role] >= ROLE_RANK[min];
}

export function AppSidebar({
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
  const [pendingLeaves, setPendingLeaves] = useState(0);
  const { user } = useCurrentUser();
  const role = (user?.role as UserRole | undefined) || "employee";

  // Filter nav items based on the signed-in user's role.
  const visibleConstruction = CONSTRUCTION_NAV.filter((i) =>
    canSee(role, i.minRole)
  );
  const visibleResources = RESOURCES_NAV.filter((i) =>
    canSee(role, i.minRole)
  );

  useEffect(() => {
    let cancelled = false;
    async function poll() {
      try {
        const res = await authedFetch("/api/v1/leaves/pending-count");
        if (!res.ok) return;
        const n = (await res.json()) as number;
        if (!cancelled) setPendingLeaves(Number(n) || 0);
      } catch {
        /* ignore */
      }
    }
    void poll();
    // Refresh every 2 minutes so admins see new requests without reload.
    const t = setInterval(poll, 120_000);
    return () => {
      cancelled = true;
      clearInterval(t);
    };
  }, []);

  function isActive(href: string) {
    if (href === "/app")
      return pathname === "/app" || pathname === "/fr/app" || pathname === "/en/app";
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
        className={`fixed inset-y-0 left-0 z-50 w-64 flex-col border-r border-brand-800 bg-brand-950 transition-transform lg:static lg:flex lg:translate-x-0 ${
          open ? "flex translate-x-0" : "hidden -translate-x-full"
        }`}
      >
        <div className="flex items-center justify-between border-b border-brand-800 px-4 py-4">
          <Link href="/app" className="flex items-center gap-2">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src="/logo.png"
              alt="Horizon"
              className="h-9 w-auto object-contain"
            />
          </Link>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md p-2 text-white/70 hover:bg-brand-900 hover:text-white lg:hidden"
            aria-label="Close sidebar"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <nav className="flex-1 space-y-6 overflow-y-auto px-3 py-5">
          <div>
            <p className="mb-2 px-3 text-xs font-semibold uppercase tracking-wider text-accent-500">
              Construction
            </p>
            <ul className="space-y-0.5">
              {visibleConstruction.map((item) => {
                const active = isActive(item.href);
                return (
                  <li key={item.href}>
                    {/* eslint-disable-next-line @typescript-eslint/no-explicit-any */}
                    <Link
                      href={item.href as any}
                      onClick={onClose}
                      className={`flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition ${
                        active
                          ? "bg-brand-900 text-white"
                          : "text-white/70 hover:bg-brand-900 hover:text-white"
                      }`}
                    >
                      <item.icon
                        className={`h-4 w-4 flex-shrink-0 ${
                          active ? "text-accent-500" : ""
                        }`}
                      />
                      <span>{item.label}</span>
                    </Link>
                  </li>
                );
              })}
            </ul>
          </div>

          <div className={visibleResources.length === 0 ? "hidden" : ""}>
            <p className="mb-2 px-3 text-xs font-semibold uppercase tracking-wider text-accent-500">
              Ressources
            </p>
            <ul className="space-y-0.5">
              {visibleResources.map((item) => {
                const active = isActive(item.href);
                const badge =
                  item.href === "/app/conges" && pendingLeaves > 0
                    ? pendingLeaves
                    : null;
                return (
                  <li key={item.href}>
                    {/* eslint-disable-next-line @typescript-eslint/no-explicit-any */}
                    <Link
                      href={item.href as any}
                      onClick={onClose}
                      className={`flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition ${
                        active
                          ? "bg-brand-900 text-white"
                          : "text-white/70 hover:bg-brand-900 hover:text-white"
                      }`}
                    >
                      <item.icon
                        className={`h-4 w-4 flex-shrink-0 ${
                          active ? "text-accent-500" : ""
                        }`}
                      />
                      <span className="flex-1">{item.label}</span>
                      {badge ? (
                        <span className="rounded-full bg-rose-500 px-2 py-0.5 text-[10px] font-bold text-white">
                          {badge}
                        </span>
                      ) : null}
                    </Link>
                  </li>
                );
              })}
            </ul>
          </div>
        </nav>

        <div className="border-t border-brand-800 px-3 py-4">
          {userEmail ? (
            <p
              className="mb-2 truncate px-3 text-xs text-white/50"
              title={userEmail}
            >
              {userEmail}
            </p>
          ) : null}
          <button
            type="button"
            onClick={onSignOut}
            className="flex w-full items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium text-white/70 transition hover:bg-brand-900 hover:text-white"
          >
            <LogOut className="h-4 w-4" />
            <span>Se déconnecter</span>
          </button>
        </div>
      </aside>
    </>
  );
}
