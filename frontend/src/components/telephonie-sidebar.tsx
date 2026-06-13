"use client";

// Sidebar dédiée au volet Téléphonie — navigation verticale.
//
// Les sections (Tableau de bord, Appels, Messages, Numéros, Filtres,
// Heures, Roadmap) vivent dans cette sidebar. Le menu horizontal en
// haut de la page a été retiré pour cohérence avec les autres volets
// (Construction, Prospection).

import {
  Clock,
  Filter,
  Home,
  LogOut,
  MessageSquare,
  Phone,
  PhoneCall,
  Sparkles,
  TrendingUp,
  UserCircle,
  X,
  Zap
} from "lucide-react";

import { useEffect, useState } from "react";

import { AccountBadge } from "@/components/account-badge";
import { HorizonLogo } from "@/components/horizon-logo";
import { Link } from "@/i18n/navigation";
import { authedFetch } from "@/lib/auth";

import type { TelephonieSection } from "@/app/[locale]/telephonie/_client-shell";

const SECTIONS: {
  key: TelephonieSection;
  label: string;
  icon: typeof Home;
}[] = [
  { key: "dashboard", label: "Tableau de bord", icon: Home },
  { key: "appels", label: "Appels", icon: PhoneCall },
  { key: "messages", label: "Messages", icon: MessageSquare },
  { key: "numeros", label: "Numéros & routage", icon: Phone },
  { key: "filtres", label: "Filtres anti-spam", icon: Filter },
  { key: "heures", label: "Heures d'ouverture", icon: Clock }
];

export function TelephonieSidebar({
  open,
  onClose,
  userEmail: _userEmail,
  onSignOut,
  section,
  onSectionChange,
  showAcquisition = false
}: {
  open: boolean;
  onClose: () => void;
  userEmail?: string;
  onSignOut: () => void;
  section: TelephonieSection;
  onSectionChange: (s: TelephonieSection) => void;
  showAcquisition?: boolean;
}) {
  // Badge « messages vocaux non lus » sur l'onglet Appels — basé sur les
  // notifications voicemail_received non lues (s'efface quand l'appel est
  // consulté via la cloche). Sondage léger toutes les 60 s.
  const [vmUnread, setVmUnread] = useState(0);
  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const r = await authedFetch(
          "/api/v1/notifications/unread-count?kind=voicemail_received"
        );
        if (!r.ok) return;
        const n = (await r.json()) as number;
        if (!cancelled) setVmUnread(Number(n) || 0);
      } catch {
        /* ignore */
      }
    }
    void load();
    const t = setInterval(load, 60_000);
    return () => {
      cancelled = true;
      clearInterval(t);
    };
  }, [section]);

  return (
    <>
      {open ? (
        <button
          type="button"
          aria-label="Close sidebar"
          onClick={onClose}
          className="fixed inset-0 z-40 bg-black/40 backdrop-blur-sm lg:hidden"
        />
      ) : null}

      <aside
        className={`fixed inset-y-0 left-0 z-50 w-64 flex-col border-r border-brand-800 bg-brand-950 transition-transform lg:static lg:flex lg:translate-x-0 ${
          open ? "flex translate-x-0" : "hidden -translate-x-full"
        }`}
      >
        <div className="flex items-center justify-between border-b border-brand-800 px-4 py-4">
          <Link
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            href={"/telephonie" as any}
            className="flex items-center gap-2"
          >
            <HorizonLogo className="h-28 w-auto object-contain" />
          </Link>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md p-2 text-white/70 hover:bg-brand-900 hover:text-white lg:hidden"
            aria-label="Close sidebar"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <nav className="flex-1 overflow-y-auto px-3 py-4">
          <div className="mb-3 flex items-center gap-2 px-2 text-[10px] font-bold uppercase tracking-wider text-teal-300">
            <PhoneCall className="h-3 w-3" />
            Communications
          </div>

          <ul className="space-y-0.5">
            {SECTIONS.map((s) => {
              const Icon = s.icon;
              const active = section === s.key;
              const badge = s.key === "appels" ? vmUnread : 0;
              return (
                <li key={s.key}>
                  <button
                    type="button"
                    onClick={() => onSectionChange(s.key)}
                    className={`flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-sm transition ${
                      active
                        ? "bg-teal-500/15 text-teal-200 font-semibold"
                        : "text-white/70 hover:bg-brand-900 hover:text-white"
                    }`}
                  >
                    <Icon className="h-4 w-4" />
                    <span className="flex-1 text-left">{s.label}</span>
                    {badge > 0 ? (
                      <span
                        className="inline-flex h-5 min-w-[20px] items-center justify-center rounded-full bg-amber-500 px-1.5 text-[10px] font-bold text-brand-950"
                        title={`${badge} message(s) vocal(aux) non lu(s)`}
                      >
                        {badge > 99 ? "99+" : badge}
                      </span>
                    ) : null}
                  </button>
                </li>
              );
            })}
          </ul>

          {showAcquisition ? (
            <div className="mt-6 border-t border-brand-800 pt-3">
              <div className="mb-2 flex items-center gap-2 px-2 text-[10px] font-bold uppercase tracking-wider text-violet-300">
                <Sparkles className="h-3 w-3" />
                Acquisition
              </div>
              <ul className="space-y-0.5">
                {[
                  {
                    key: "acquisition" as TelephonieSection,
                    label: "Tableau acquisition",
                    icon: TrendingUp
                  },
                  {
                    key: "automatisations" as TelephonieSection,
                    label: "Automatisations",
                    icon: Zap
                  }
                ].map((s) => {
                  const Icon = s.icon;
                  const active = section === s.key;
                  return (
                    <li key={s.key}>
                      <button
                        type="button"
                        onClick={() => onSectionChange(s.key)}
                        className={`flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-sm transition ${
                          active
                            ? "bg-violet-500/15 text-violet-200 font-semibold"
                            : "text-white/70 hover:bg-brand-900 hover:text-white"
                        }`}
                      >
                        <Icon className="h-4 w-4" />
                        <span className="flex-1 text-left">{s.label}</span>
                      </button>
                    </li>
                  );
                })}
              </ul>
            </div>
          ) : null}

          <div className="mt-6 border-t border-brand-800 pt-3">
            <Link
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
              href={"/connexion" as any}
              onClick={onClose}
              className="flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-sm text-white/70 hover:bg-brand-900 hover:text-white"
            >
              <Home className="h-4 w-4" />
              Retour au sélecteur de portail
            </Link>
          </div>
        </nav>

        <div className="border-t border-brand-800 px-3 py-4">
          <AccountBadge />
          <Link
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            href={"/profil" as any}
            onClick={onClose}
            className="flex w-full items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium text-white/70 transition hover:bg-brand-900 hover:text-white"
          >
            <UserCircle className="h-4 w-4" />
            <span>Mon profil</span>
          </Link>
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
