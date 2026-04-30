"use client";

import { useState } from "react";
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
  Settings,
  Smartphone,
  Sun,
  Trello,
  UserCircle,
  X
} from "lucide-react";

import { Link } from "@/i18n/navigation";
import { type UserRole } from "@/lib/auth";
import { useCurrentUser } from "@/hooks/use-current-user";

type NavItem = {
  href: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  minRole?: UserRole;
};

// Tous les volets opérationnels sont accessibles aux employés
// (un prospecteur a besoin de la carte, des leads, de l'agenda…).
// Seul Paramètres reste réservé aux managers+.
const PROSPECTION_NAV: NavItem[] = [
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
  },
  { href: "/prospection", label: "Carte", icon: Map, minRole: "employee" },
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
  },
  {
    href: "/prospection/parametres",
    label: "Paramètres",
    icon: Settings,
    minRole: "manager"
  },
  // Phase 3+ : campagnes
  // { href: "/prospection/campagnes", label: "Campagnes", icon: Mail },
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
  const visible = PROSPECTION_NAV.filter((i) => canSee(role, i.minRole));

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
          <p className="px-2 py-1 text-[10px] font-semibold uppercase tracking-wider text-emerald-500/80">
            Prospection
          </p>
          <ul className="space-y-0.5">
            {visible.map((it) => {
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
          <div className="flex items-center gap-2 px-2.5 py-1.5 text-xs text-white/60">
            <UserCircle className="h-4 w-4" />
            <span className="truncate">{userEmail || "—"}</span>
          </div>
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
