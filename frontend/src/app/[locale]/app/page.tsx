"use client";

import { useEffect, useState } from "react";
import {
  AlertTriangle,
  Briefcase,
  Clock,
  DollarSign,
  FileText,
  Loader2,
  TrendingUp,
  Users
} from "lucide-react";

import { Link } from "@/i18n/navigation";
import { AppTopbar } from "@/components/app-topbar";
import { useAppLayout } from "./layout";
import { useCurrentUser } from "@/hooks/use-current-user";
import { authedFetch } from "@/lib/auth";

type Kpis = {
  unpaid_total: number;
  unpaid_count: number;
  overdue_total: number;
  overdue_count: number;
  revenue_this_month: number;
  active_projects: number;
  hours_this_week: number;
  new_prospects_7d: number;
  open_soumissions_count: number;
  open_soumissions_total: number;
};

function money(n: number): string {
  return new Intl.NumberFormat("fr-CA", {
    style: "currency",
    currency: "CAD",
    maximumFractionDigits: 0
  }).format(n);
}

export default function AppHome() {
  const { user } = useCurrentUser();
  const { onOpenSidebar } = useAppLayout();
  const [kpis, setKpis] = useState<Kpis | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const res = await authedFetch("/api/v1/dashboard/kpis");
        if (!res.ok) throw new Error(`http_${res.status}`);
        if (!cancelled) setKpis((await res.json()) as Kpis);
      } catch {
        if (!cancelled) setError("KPIs indisponibles.");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, []);

  const shortcuts: { label: string; href: string; desc: string }[] = [
    { label: "Nouveau prospect", href: "/app/crm", desc: "Ajouter manuellement un prospect au pipeline." },
    { label: "Créer une soumission", href: "/app/soumissions", desc: "Générer et envoyer un devis." },
    { label: "Planifier un chantier", href: "/app/agenda", desc: "Ajouter un événement à l'agenda équipe." },
    { label: "Voir les punches", href: "/app/punch", desc: "Approuver les entrées de la semaine." }
  ];

  return (
    <>
      <AppTopbar
        breadcrumbs={[{ label: "Accueil" }]}
        onOpenSidebar={onOpenSidebar}
      />

      <div className="p-4 lg:p-8">
        <header>
          <p className="text-sm text-white/50">Bonjour</p>
          <h1 className="text-2xl font-bold text-white">
            {user?.email?.split("@")[0] || "Horizon"}
          </h1>
        </header>

        {error ? (
          <p className="mt-4 rounded-lg border border-rose-500/40 bg-rose-500/10 px-4 py-2 text-sm text-rose-300">
            {error}
          </p>
        ) : null}

        {/* Primary KPIs */}
        <section className="mt-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <KpiCard
            href="/app/facturation"
            icon={DollarSign}
            iconClass="text-rose-400"
            label="Factures impayées"
            value={loading ? "…" : money(kpis?.unpaid_total || 0)}
            hint={
              loading
                ? " "
                : kpis && kpis.unpaid_count > 0
                ? `${kpis.unpaid_count} factures — dont ${money(
                    kpis.overdue_total
                  )} en retard`
                : "Aucune impayée"
            }
            alert={
              kpis && kpis.overdue_count > 0
                ? `${kpis.overdue_count} en retard`
                : null
            }
          />
          <KpiCard
            href="/app/facturation"
            icon={TrendingUp}
            iconClass="text-emerald-400"
            label="Revenu ce mois"
            value={loading ? "…" : money(kpis?.revenue_this_month || 0)}
            hint="Factures payées (mois courant)"
          />
          <KpiCard
            href="/app/projets"
            icon={Briefcase}
            iconClass="text-accent-500"
            label="Chantiers actifs"
            value={loading ? "…" : String(kpis?.active_projects ?? 0)}
            hint="En cours"
          />
          <KpiCard
            href="/app/punch/gestion"
            icon={Clock}
            iconClass="text-blue-400"
            label="Heures cette semaine"
            value={
              loading
                ? "…"
                : `${(kpis?.hours_this_week || 0).toFixed(1)} h`
            }
            hint="Punches terminés (lun.–dim.)"
          />
        </section>

        {/* Secondary KPIs */}
        <section className="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          <KpiCard
            href="/app/crm"
            icon={Users}
            iconClass="text-emerald-400"
            label="Nouveaux prospects"
            value={loading ? "…" : String(kpis?.new_prospects_7d ?? 0)}
            hint="7 derniers jours"
            small
          />
          <KpiCard
            href="/app/soumissions"
            icon={FileText}
            iconClass="text-blue-400"
            label="Soumissions en attente"
            value={loading ? "…" : String(kpis?.open_soumissions_count ?? 0)}
            hint={
              loading
                ? " "
                : `${money(kpis?.open_soumissions_total || 0)} potentiels`
            }
            small
          />
          {kpis && kpis.overdue_count > 0 ? (
            <Link
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
              href={"/app/facturation" as any}
              className="group flex items-center gap-3 rounded-xl border border-rose-500/40 bg-rose-500/10 p-5 transition hover:bg-rose-500/20"
            >
              <AlertTriangle className="h-6 w-6 shrink-0 text-rose-300" />
              <div>
                <p className="text-sm font-semibold text-white">
                  {kpis.overdue_count} facture
                  {kpis.overdue_count > 1 ? "s" : ""} en retard
                </p>
                <p className="mt-0.5 text-xs text-rose-200">
                  {money(kpis.overdue_total)} dû — relances envoyées
                  automatiquement.
                </p>
              </div>
            </Link>
          ) : null}
        </section>

        {/* Shortcuts */}
        <section className="mt-10">
          <h2 className="text-sm font-semibold uppercase tracking-wider text-accent-500">
            Raccourcis
          </h2>
          <div className="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {shortcuts.map((s) => (
              <Link
                key={s.label}
                // eslint-disable-next-line @typescript-eslint/no-explicit-any
                href={s.href as any}
                className="group rounded-xl border border-brand-800 bg-brand-900 p-5 transition hover:border-accent-500"
              >
                <h3 className="text-base font-semibold text-white group-hover:text-accent-500">
                  {s.label}
                </h3>
                <p className="mt-1 text-sm text-white/60">{s.desc}</p>
              </Link>
            ))}
          </div>
        </section>
      </div>
    </>
  );
}

function KpiCard({
  href,
  icon: Icon,
  iconClass,
  label,
  value,
  hint,
  alert,
  small
}: {
  href: string;
  icon: React.ComponentType<{ className?: string }>;
  iconClass: string;
  label: string;
  value: string;
  hint: string;
  alert?: string | null;
  small?: boolean;
}) {
  return (
    <Link
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      href={href as any}
      className="group rounded-xl border border-brand-800 bg-brand-900 p-5 transition hover:border-accent-500"
    >
      <div className="flex items-center justify-between">
        <span className="text-xs font-medium uppercase tracking-wider text-white/50">
          {label}
        </span>
        <Icon className={`h-5 w-5 ${iconClass}`} />
      </div>
      <p
        className={`mt-3 font-bold text-white ${
          small ? "text-2xl" : "text-3xl"
        }`}
      >
        {value === "…" ? (
          <Loader2 className="h-6 w-6 animate-spin text-white/40" />
        ) : (
          value
        )}
      </p>
      <p className="mt-1 text-xs text-white/50">{hint}</p>
      {alert ? (
        <p className="mt-2 rounded-md bg-rose-500/15 px-2 py-0.5 text-[10px] font-semibold text-rose-300">
          {alert}
        </p>
      ) : null}
    </Link>
  );
}
