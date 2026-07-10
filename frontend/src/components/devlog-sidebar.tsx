"use client";

import { usePathname } from "next/navigation";
import {
  Calendar,
  Clock,
  FileSignature,
  FileText,
  FolderKanban,
  HardHat,
  Home,
  Receipt,
  Trello,
  Users,
  X
} from "lucide-react";

import { Link } from "@/i18n/navigation";
import { HorizonLogo } from "@/components/horizon-logo";
import { SidebarFooter } from "@/components/sidebar-footer";
import { useCurrentUser } from "@/hooks/use-current-user";
import { useNavAccess } from "@/hooks/use-nav-access";

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
      { href: "/dev-logiciel/leads", label: "CRM", icon: Trello },
      {
        href: "/dev-logiciel/soumissions",
        label: "Soumissions",
        icon: FileText
      },
      {
        href: "/dev-logiciel/contrats",
        label: "Contrats",
        icon: FileSignature
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
        href: "/dev-logiciel/agenda",
        label: "Agenda",
        icon: Calendar
      },
      {
        href: "/dev-logiciel/heures",
        label: "Heures",
        icon: Clock
      },
      {
        href: "/dev-logiciel/sous-traitants",
        label: "Sous-traitants",
        icon: HardHat
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
  onClose
}: {
  open: boolean;
  onClose: () => void;
  // Conservés dans la signature pour ne pas casser les appels existants —
  // le footer unifié (SidebarFooter) gère user + signOut lui-même.
  userEmail?: string;
  onSignOut?: () => void;
}) {
  const pathname = usePathname();
  const { user } = useCurrentUser();
  // Filtre d'accès par page (refonte permissions) — fail-open si l'accès
  // n'est pas chargé. Le layout garde déjà l'entrée du pôle (owner/admin).
  const canSeeHref = useNavAccess(user);
  const visibleSections = DEVLOG_SECTIONS.map((s) => ({
    ...s,
    items: s.items.filter((it) => canSeeHref(it.href))
  })).filter((s) => s.items.length > 0);

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
        className={`fixed inset-y-0 left-0 z-50 w-64 flex-col border-r border-brand-800 bg-brand-950 transition-transform lg:static lg:flex lg:translate-x-0 ${
          open ? "flex translate-x-0" : "hidden -translate-x-full"
        }`}
      >
        <div className="flex items-center justify-between border-b border-brand-800 px-4 py-4">
          <Link href={"/dev-logiciel" as any} className="flex items-center gap-2">
            <HorizonLogo className="h-16 w-auto object-contain" />
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
              <p className="px-2 py-1 text-[10px] font-semibold uppercase tracking-wider text-accent-500">
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
                            ? "bg-brand-900 text-white"
                            : "text-white/70 hover:bg-brand-900 hover:text-white"
                        }`}
                      >
                        <Icon
                          className={`h-4 w-4 flex-shrink-0 ${
                            active ? "text-accent-500" : ""
                          }`}
                        />
                        {it.label}
                      </Link>
                    </li>
                  );
                })}
              </ul>
            </div>
          ))}

        </nav>

        <SidebarFooter onNavigate={onClose} />
      </aside>
    </>
  );
}
