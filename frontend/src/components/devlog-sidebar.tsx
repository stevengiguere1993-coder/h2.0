"use client";

import { usePathname } from "next/navigation";
import {
  Clock,
  Code2,
  FileText,
  FolderKanban,
  Home,
  LogOut,
  Receipt,
  Trello,
  UserCircle,
  Users,
  X
} from "lucide-react";

import { Link } from "@/i18n/navigation";
import { AccountBadge } from "@/components/account-badge";

type NavItem = {
  href: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
};

type NavSection = {
  label: string;
  items: NavItem[];
};

const DEVLOG_SECTIONS: NavSection[] = [
  {
    label: "Pôle",
    items: [
      { href: "/dev-logiciel", label: "Accueil", icon: Home }
    ]
  },
  {
    label: "Closer",
    items: [
      { href: "/dev-logiciel/leads", label: "Pipeline (leads)", icon: Trello },
      {
        href: "/dev-logiciel/soumissions",
        label: "Soumissions",
        icon: FileText
      },
      { href: "/dev-logiciel/clients", label: "Clients", icon: Users }
    ]
  },
  {
    label: "Livraison",
    items: [
      {
        href: "/dev-logiciel/projets",
        label: "Projets",
        icon: FolderKanban
      },
      {
        href: "/dev-logiciel/heures",
        label: "Heures",
        icon: Clock
      }
    ]
  },
  {
    label: "Finances",
    items: [
      {
        href: "/dev-logiciel/facturation",
        label: "Facturation",
        icon: Receipt
      }
    ]
  }
];

export function DevlogSidebar({
  open,
  onClose,
  onSignOut
}: {
  open: boolean;
  onClose: () => void;
  userEmail?: string;
  onSignOut: () => void;
}) {
  const pathname = usePathname();

  function isActive(href: string) {
    if (href === "/dev-logiciel") {
      return /\/dev-logiciel\/?$/.test(pathname);
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
        className={`fixed inset-y-0 left-0 z-50 w-64 flex-col border-r border-blue-900/40 bg-brand-950 transition-transform lg:static lg:flex lg:translate-x-0 ${
          open ? "flex translate-x-0" : "hidden -translate-x-full"
        }`}
      >
        <div className="flex items-center justify-between border-b border-blue-900/40 px-4 py-4">
          <Link href={"/dev-logiciel" as any} className="flex items-center gap-2">
            <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-blue-500/15 text-blue-400">
              <Code2 className="h-5 w-5" />
            </span>
            <span className="flex flex-col leading-tight">
              <span className="text-sm font-bold text-white">
                Dév. logiciel
              </span>
              <span className="text-[10px] uppercase tracking-wider text-blue-400/80">
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
          {DEVLOG_SECTIONS.map((section, idx) => (
            <div key={section.label} className={idx === 0 ? "" : "mt-4"}>
              <p className="px-2 py-1 text-[10px] font-semibold uppercase tracking-wider text-blue-500/80">
                {section.label}
              </p>
              <ul className="space-y-0.5">
                {section.items.map((it) => {
                  const Icon = it.icon;
                  const active = isActive(it.href);
                  return (
                    <li key={it.href}>
                      <Link
                        href={it.href as any}
                        onClick={onClose}
                        className={`flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-sm transition ${
                          active
                            ? "bg-blue-500/15 text-blue-300"
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
            </div>
          ))}

          <div className="mt-6 border-t border-brand-800 pt-3">
            <Link
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
