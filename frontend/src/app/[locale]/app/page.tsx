"use client";

import { useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  Briefcase,
  Clock,
  DollarSign,
  FileText,
  Loader2,
  Percent,
  Timer,
  TrendingUp,
  Users
} from "lucide-react";

import { Link } from "@/i18n/navigation";
import { AppTopbar } from "@/components/app-topbar";
import { useAppLayout } from "./layout";
import { useCurrentUser } from "@/hooks/use-current-user";
import { authedFetch } from "@/lib/auth";

type TimeseriesPoint = {
  date: string;
  soumissions: number;
  ventes: number;
};

type Kpis = {
  start_date: string;
  end_date: string;
  unpaid_total: number;
  unpaid_count: number;
  overdue_total: number;
  overdue_count: number;
  revenue_this_month: number;
  revenue_this_month_mode: "paid" | "issued";
  prospects_count: number;
  soumissions_sent_total: number;
  soumissions_sent_count: number;
  ventes_total: number;
  ventes_count: number;
  conversion_rate: number;
  avg_transaction: number;
  time_to_sale_days: number;
  active_projects: number;
  hours_this_week: number;
  new_prospects_7d: number;
  open_soumissions_count: number;
  open_soumissions_total: number;
  timeseries: TimeseriesPoint[];
};

function money(n: number): string {
  return new Intl.NumberFormat("fr-CA", {
    style: "currency",
    currency: "CAD",
    maximumFractionDigits: 0
  }).format(n);
}

function yyyyMmDd(d: Date): string {
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

type PeriodPreset = "7d" | "30d" | "month" | "quarter" | "year" | "custom";

function presetRange(preset: PeriodPreset): { start: string; end: string } {
  const today = new Date();
  const end = yyyyMmDd(today);
  if (preset === "7d") {
    const s = new Date(today);
    s.setDate(s.getDate() - 6);
    return { start: yyyyMmDd(s), end };
  }
  if (preset === "30d") {
    const s = new Date(today);
    s.setDate(s.getDate() - 29);
    return { start: yyyyMmDd(s), end };
  }
  if (preset === "month") {
    const s = new Date(today.getFullYear(), today.getMonth(), 1);
    return { start: yyyyMmDd(s), end };
  }
  if (preset === "quarter") {
    const qStart = Math.floor(today.getMonth() / 3) * 3;
    const s = new Date(today.getFullYear(), qStart, 1);
    return { start: yyyyMmDd(s), end };
  }
  // year
  const s = new Date(today.getFullYear(), 0, 1);
  return { start: yyyyMmDd(s), end };
}

export default function AppHome() {
  const { user } = useCurrentUser();
  const { onOpenSidebar } = useAppLayout();
  const [kpis, setKpis] = useState<Kpis | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [preset, setPreset] = useState<PeriodPreset>("month");
  const [range, setRange] = useState(() => presetRange("month"));

  useEffect(() => {
    if (preset !== "custom") setRange(presetRange(preset));
  }, [preset]);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      try {
        const q = new URLSearchParams({
          start_date: range.start,
          end_date: range.end
        });
        const res = await authedFetch(`/api/v1/dashboard/kpis?${q.toString()}`);
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
  }, [range.start, range.end]);

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
        <header className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <p className="text-sm text-white/50">Bonjour</p>
            <h1 className="text-2xl font-bold text-white">
              {user?.email?.split("@")[0] || "Horizon"}
            </h1>
          </div>
          <PeriodPicker
            preset={preset}
            range={range}
            onPreset={setPreset}
            onRange={(r) => {
              setPreset("custom");
              setRange(r);
            }}
          />
        </header>

        {error ? (
          <p className="mt-4 rounded-lg border border-rose-500/40 bg-rose-500/10 px-4 py-2 text-sm text-rose-300">
            {error}
          </p>
        ) : null}

        {/* Headline: prospects / soumissions envoyées / ventes */}
        <section className="mt-8 grid gap-4 sm:grid-cols-3">
          <BigTile
            label="Prospects"
            value={loading ? "…" : String(kpis?.prospects_count ?? 0)}
            sub="Nouveaux dans la période"
            icon={Users}
            href="/app/crm"
            tone="sky"
          />
          <BigTile
            label="Soumissions envoyées"
            value={loading ? "…" : money(kpis?.soumissions_sent_total || 0)}
            sub={
              kpis
                ? `${kpis.soumissions_sent_count} soumission${
                    kpis.soumissions_sent_count > 1 ? "s" : ""
                  }`
                : " "
            }
            icon={FileText}
            href="/app/soumissions"
            tone="amber"
          />
          <BigTile
            label="Ventes"
            value={loading ? "…" : money(kpis?.ventes_total || 0)}
            sub={
              kpis
                ? `${kpis.ventes_count} job${kpis.ventes_count > 1 ? "s" : ""}`
                : " "
            }
            icon={TrendingUp}
            href="/app/soumissions"
            tone="emerald"
          />
        </section>

        {/* Secondary metrics row */}
        <section className="mt-4 grid gap-4 sm:grid-cols-3">
          <MiniStat
            icon={Percent}
            label="Taux de conversion"
            value={loading ? "…" : `${(kpis?.conversion_rate ?? 0).toFixed(1)} %`}
            hint="Ventes / soumissions envoyées"
          />
          <MiniStat
            icon={DollarSign}
            label="Transaction moyenne"
            value={loading ? "…" : money(kpis?.avg_transaction ?? 0)}
            hint="Ventes dans la période"
          />
          <MiniStat
            icon={Timer}
            label="Temps avant vente"
            value={
              loading
                ? "…"
                : `${(kpis?.time_to_sale_days ?? 0).toFixed(1)} jours`
            }
            hint="Contact → acceptation"
          />
        </section>

        {/* Chart */}
        <section className="mt-4 rounded-xl border border-brand-800 bg-brand-900 p-5">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold uppercase tracking-wider text-accent-500">
              Soumissions envoyées vs ventes
            </h2>
            <div className="flex items-center gap-3 text-xs text-white/60">
              <LegendDot color="bg-accent-500" label="Soumissions" />
              <LegendDot color="bg-sky-400" label="Ventes" />
            </div>
          </div>
          <DualBarChart
            loading={loading}
            points={kpis?.timeseries || []}
          />
        </section>

        {/* Cash flow / ops grid */}
        <section className="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
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
                ? `${kpis.unpaid_count} envoyée${
                    kpis.unpaid_count > 1 ? "s" : ""
                  }${
                    kpis.overdue_count > 0
                      ? ` · ${money(kpis.overdue_total)} en retard`
                      : ""
                  }`
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
            hint={
              kpis?.revenue_this_month_mode === "issued"
                ? "Facturé ce mois (aucune réglée)"
                : "Factures payées (mois courant)"
            }
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

        {kpis && kpis.overdue_count > 0 ? (
          <Link
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            href={"/app/facturation" as any}
            className="mt-4 flex items-center gap-3 rounded-xl border border-rose-500/40 bg-rose-500/10 p-5 transition hover:bg-rose-500/20"
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

function PeriodPicker({
  preset,
  range,
  onPreset,
  onRange
}: {
  preset: PeriodPreset;
  range: { start: string; end: string };
  onPreset: (p: PeriodPreset) => void;
  onRange: (r: { start: string; end: string }) => void;
}) {
  const presets: { id: PeriodPreset; label: string }[] = [
    { id: "7d", label: "7 j" },
    { id: "30d", label: "30 j" },
    { id: "month", label: "Mois" },
    { id: "quarter", label: "Trim." },
    { id: "year", label: "Année" }
  ];
  return (
    <div className="flex flex-col items-start gap-2 sm:flex-row sm:items-center">
      <div className="flex rounded-lg border border-brand-800 bg-brand-900 p-1 text-xs">
        {presets.map((p) => (
          <button
            key={p.id}
            type="button"
            onClick={() => onPreset(p.id)}
            className={`rounded-md px-3 py-1.5 font-semibold transition ${
              preset === p.id
                ? "bg-accent-500 text-brand-950"
                : "text-white/70 hover:text-white"
            }`}
          >
            {p.label}
          </button>
        ))}
      </div>
      <div className="flex items-center gap-2 text-xs text-white/60">
        <input
          type="date"
          value={range.start}
          onChange={(e) => onRange({ ...range, start: e.target.value })}
          className="rounded-md border border-brand-800 bg-brand-900 px-2 py-1 text-white"
        />
        <span>→</span>
        <input
          type="date"
          value={range.end}
          onChange={(e) => onRange({ ...range, end: e.target.value })}
          className="rounded-md border border-brand-800 bg-brand-900 px-2 py-1 text-white"
        />
      </div>
    </div>
  );
}


function BigTile({
  label,
  value,
  sub,
  icon: Icon,
  href,
  tone
}: {
  label: string;
  value: string;
  sub: string;
  icon: React.ComponentType<{ className?: string }>;
  href: string;
  tone: "sky" | "amber" | "emerald";
}) {
  const toneMap: Record<string, string> = {
    sky: "text-sky-400",
    amber: "text-accent-500",
    emerald: "text-emerald-400"
  };
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
        <Icon className={`h-5 w-5 ${toneMap[tone]}`} />
      </div>
      <p className="mt-3 text-3xl font-bold text-white">
        {value === "…" ? (
          <Loader2 className="h-6 w-6 animate-spin text-white/40" />
        ) : (
          value
        )}
      </p>
      <p className="mt-1 text-xs text-white/50">{sub}</p>
    </Link>
  );
}

function MiniStat({
  icon: Icon,
  label,
  value,
  hint
}: {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  value: string;
  hint: string;
}) {
  return (
    <div className="rounded-xl border border-brand-800 bg-brand-900 p-5">
      <div className="flex items-center justify-between">
        <span className="text-xs font-medium uppercase tracking-wider text-white/50">
          {label}
        </span>
        <Icon className="h-4 w-4 text-white/50" />
      </div>
      <p className="mt-2 text-xl font-bold text-white">{value}</p>
      <p className="mt-1 text-xs text-white/50">{hint}</p>
    </div>
  );
}

function LegendDot({ color, label }: { color: string; label: string }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className={`h-2.5 w-2.5 rounded-full ${color}`} />
      {label}
    </span>
  );
}

function DualBarChart({
  loading,
  points
}: {
  loading: boolean;
  points: TimeseriesPoint[];
}) {
  if (loading) {
    return (
      <div className="flex h-40 items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-white/40" />
      </div>
    );
  }
  if (points.length === 0) {
    return (
      <p className="mt-6 text-center text-sm text-white/50">
        Aucune donnée pour cette période.
      </p>
    );
  }
  const max = Math.max(
    1,
    ...points.map((p) => Math.max(p.soumissions, p.ventes))
  );
  const barGroupWidth = 100 / points.length;
  return (
    <div className="mt-5">
      <svg
        viewBox="0 0 100 60"
        preserveAspectRatio="none"
        className="h-48 w-full"
      >
        {points.map((p, i) => {
          const x = i * barGroupWidth;
          const soumH = (p.soumissions / max) * 56;
          const venteH = (p.ventes / max) * 56;
          const w = barGroupWidth * 0.4;
          return (
            <g key={p.date}>
              <rect
                x={x + barGroupWidth * 0.08}
                y={58 - soumH}
                width={w}
                height={soumH}
                fill="#d89b3c"
                opacity={0.9}
              />
              <rect
                x={x + barGroupWidth * 0.52}
                y={58 - venteH}
                width={w}
                height={venteH}
                fill="#38bdf8"
                opacity={0.9}
              />
            </g>
          );
        })}
        <line x1="0" y1="58" x2="100" y2="58" stroke="#1f2937" strokeWidth="0.3" />
      </svg>
      <div className="mt-1 flex justify-between text-[10px] text-white/40">
        <span>{points[0]?.date}</span>
        <span>{points[points.length - 1]?.date}</span>
      </div>
    </div>
  );
}

function KpiCard({
  href,
  icon: Icon,
  iconClass,
  label,
  value,
  hint,
  alert
}: {
  href: string;
  icon: React.ComponentType<{ className?: string }>;
  iconClass: string;
  label: string;
  value: string;
  hint: string;
  alert?: string | null;
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
      <p className="mt-3 text-2xl font-bold text-white">
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
