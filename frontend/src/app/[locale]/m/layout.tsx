"use client";

import { useEffect, useState } from "react";
import { usePathname, useRouter as useNextRouter } from "next/navigation";
import {
  Calendar,
  ClipboardList,
  Home,
  Menu,
  Users
} from "lucide-react";

import { Link } from "@/i18n/navigation";
import { getToken, getMe, type CurrentUser } from "@/lib/auth";

type Tab = {
  href: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
};

const TABS: Tab[] = [
  { href: "/m", label: "Accueil", icon: Home },
  { href: "/m/agenda", label: "Agenda", icon: Calendar },
  { href: "/m/ops", label: "Ops", icon: ClipboardList },
  { href: "/m/clients", label: "Clients", icon: Users },
  { href: "/m/plus", label: "Plus", icon: Menu }
];

export default function MobileLayout({
  children
}: {
  children: React.ReactNode;
}) {
  const pathname = usePathname() || "";
  const router = useNextRouter();
  const [me, setMe] = useState<CurrentUser | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    const token = getToken();
    if (!token) {
      // Redirect to the locale login; include the intended next URL so
      // we come back here after auth.
      const next = encodeURIComponent(pathname);
      router.replace(`/connexion?next=${next}`);
      return;
    }
    getMe(token)
      .then((u) => {
        setMe(u);
        setReady(true);
      })
      .catch(() => {
        router.replace("/connexion");
      });
  }, [pathname, router]);

  if (!ready) {
    return (
      <main className="flex min-h-screen items-center justify-center bg-brand-950 text-white/70">
        <p className="text-sm">Chargement…</p>
      </main>
    );
  }

  return (
    <main className="flex min-h-screen flex-col bg-brand-950 text-white">
      <div className="flex-1 pb-20">{children}</div>

      <nav
        className="fixed bottom-0 left-0 right-0 z-40 border-t border-brand-800 bg-brand-950/95 backdrop-blur"
        style={{ paddingBottom: "env(safe-area-inset-bottom)" }}
      >
        <ul className="flex items-center justify-around">
          {TABS.map((t) => {
            const active =
              t.href === "/m"
                ? pathname.endsWith("/m") || pathname.endsWith("/m/")
                : pathname.includes(t.href);
            const Icon = t.icon;
            return (
              <li key={t.href} className="flex-1">
                <Link
                  // eslint-disable-next-line @typescript-eslint/no-explicit-any
                  href={t.href as any}
                  className={`flex flex-col items-center gap-1 py-2.5 text-[10px] font-medium transition ${
                    active
                      ? "text-accent-500"
                      : "text-white/50 hover:text-white"
                  }`}
                >
                  <Icon className="h-5 w-5" />
                  {t.label}
                </Link>
              </li>
            );
          })}
        </ul>
      </nav>

      {/* Expose current user email in a global for deep pages if needed */}
      <span id="hsi-me" data-email={me?.email || ""} className="hidden" />
    </main>
  );
}
