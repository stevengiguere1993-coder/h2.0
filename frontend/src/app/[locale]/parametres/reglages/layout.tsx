"use client";

import { usePathname } from "next/navigation";
import { Building2, Calendar, Users } from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { Link } from "@/i18n/navigation";
import { useAppLayout } from "../layout";

type Tab = {
  href: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
};

const TABS: Tab[] = [
  { href: "/parametres/reglages/entreprises", label: "Entreprises", icon: Building2 },
  { href: "/parametres/reglages/calendriers", label: "Calendriers", icon: Calendar },
  { href: "/parametres/reglages/equipe", label: "Équipe", icon: Users }
];

export default function ReglagesLayout({
  children
}: {
  children: React.ReactNode;
}) {
  const pathname = usePathname() || "";
  const { onOpenSidebar } = useAppLayout();

  function isActive(href: string) {
    return pathname.includes(href);
  }

  return (
    <>
      <AppTopbar
        breadcrumbs={[
          { label: "Paramètres", href: "/parametres" },
          { label: "Gestion d'entreprises" }
        ]}
        onOpenSidebar={onOpenSidebar}
      />
      <nav
        className="flex items-center gap-1 overflow-x-auto px-4 lg:px-6"
        style={{
          backgroundColor: "var(--qg-bg)",
          borderBottom: "1px solid var(--qg-border)"
        }}
      >
        {TABS.map((t) => {
          const active = isActive(t.href);
          const Icon = t.icon;
          return (
            <Link
              key={t.href}
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
              href={t.href as any}
              className="relative inline-flex items-center gap-2 px-4 py-3 text-sm font-medium transition"
              style={{
                color: active ? "var(--qg-accent)" : "var(--qg-text-muted)",
                borderBottom: active
                  ? "2px solid var(--qg-accent)"
                  : "2px solid transparent",
                marginBottom: "-1px"
              }}
            >
              <Icon className="h-4 w-4" />
              <span>{t.label}</span>
            </Link>
          );
        })}
      </nav>
      <div>{children}</div>
    </>
  );
}
