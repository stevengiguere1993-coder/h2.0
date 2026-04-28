"use client";

import { usePathname } from "next/navigation";
import {
  Cog,
  Database,
  Plug,
  RefreshCw,
  Users
} from "lucide-react";

import { Link } from "@/i18n/navigation";
import { hasMinRole, type UserRole } from "@/lib/auth";
import { useCurrentUser } from "@/hooks/use-current-user";

type Tab = {
  href: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  minRole?: UserRole;
};

const TABS: Tab[] = [
  {
    href: "/prospection/parametres",
    label: "Préférences",
    icon: Cog
  },
  {
    href: "/prospection/parametres/connexions",
    label: "Connexions",
    icon: Plug
  },
  {
    href: "/prospection/parametres/utilisateurs",
    label: "Utilisateurs",
    icon: Users,
    minRole: "owner"
  },
  {
    href: "/prospection/parametres/sources",
    label: "Sources de données",
    icon: Database,
    minRole: "owner"
  },
  {
    href: "/prospection/parametres/outils",
    label: "Outils admin",
    icon: RefreshCw,
    minRole: "admin"
  }
];

export default function ProspectionParametresLayout({
  children
}: {
  children: React.ReactNode;
}) {
  const pathname = usePathname();
  const { user } = useCurrentUser();

  const visible = TABS.filter((t) => hasMinRole(user, t.minRole || "manager"));

  function isActive(href: string): boolean {
    // Le tab Préférences est l'index — actif uniquement si pathname
    // termine par /parametres (pas un sous-chemin).
    const trimmed = pathname.replace(/^\/(en|fr)/, "");
    if (href === "/prospection/parametres") {
      return trimmed === "/prospection/parametres";
    }
    return trimmed.startsWith(href);
  }

  return (
    <div>
      <nav className="sticky top-16 z-20 -mx-4 mb-2 flex gap-1 overflow-x-auto border-b border-brand-800 bg-brand-950/95 px-4 py-2 backdrop-blur lg:-mx-6 lg:px-6">
        {visible.map((t) => {
          const Icon = t.icon;
          const active = isActive(t.href);
          return (
            <Link
              key={t.href}
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
              href={t.href as any}
              className={`inline-flex shrink-0 items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm transition ${
                active
                  ? "bg-emerald-500/15 text-emerald-300"
                  : "text-white/60 hover:bg-brand-900 hover:text-white"
              }`}
            >
              <Icon className="h-4 w-4" />
              {t.label}
            </Link>
          );
        })}
      </nav>
      {children}
    </div>
  );
}
