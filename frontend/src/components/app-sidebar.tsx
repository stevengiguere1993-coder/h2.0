"use client";

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
  LogOut,
  ShoppingCart,
  Truck,
  UserCircle,
  Users,
  X
} from "lucide-react";

import { Link } from "@/i18n/navigation";

type NavItem = {
  href: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
};

const CONSTRUCTION_NAV: NavItem[] = [
  { href: "/app", label: "Accueil", icon: Home },
  { href: "/app/crm", label: "CRM / Prospects", icon: Users },
  { href: "/app/soumissions", label: "Soumissions", icon: FileText },
  { href: "/app/projets", label: "Projets", icon: Briefcase },
  { href: "/app/agenda", label: "Agenda", icon: Calendar },
  { href: "/app/bons", label: "Bons de travail", icon: ClipboardCheck },
  { href: "/app/punch", label: "Punch / Temps", icon: Clock },
  { href: "/app/facturation", label: "Facturation", icon: DollarSign },
  { href: "/app/achats", label: "Achats / PO", icon: ShoppingCart }
];

const RESOURCES_NAV: NavItem[] = [
  { href: "/app/employes", label: "Employés", icon: UserCircle },
  { href: "/app/sous-traitants", label: "Sous-traitants", icon: HardHat },
  { href: "/app/fournisseurs", label: "Fournisseurs", icon: Truck }
];

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
              {CONSTRUCTION_NAV.map((item) => {
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

          <div>
            <p className="mb-2 px-3 text-xs font-semibold uppercase tracking-wider text-accent-500">
              Ressources
            </p>
            <ul className="space-y-0.5">
              {RESOURCES_NAV.map((item) => {
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
