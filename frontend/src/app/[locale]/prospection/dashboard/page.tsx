"use client";

import { useEffect, useMemo, useState } from "react";
import {
  Activity,
  ArrowUpRight,
  Building2,
  CheckCircle2,
  Loader2,
  MapPin,
  Sparkles,
  Target,
  TrendingUp
} from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { authedFetch } from "@/lib/auth";
import { PageDriveSection } from "@/components/drive/PageDriveSection";
import { useProspectionLayout } from "../layout";

type DashboardStats = {
  total_leads: number;
  by_status: Record<string, number>;
  by_kind: Record<string, number>;
  avg_score: number;
  high_score_count: number;
  converted_count: number;
  conversion_rate: number;
  leads_per_week: { week: string; count: number }[];
  score_distribution: { bucket: string; count: number }[];
  top_cities: { city: string; count: number }[];
};

const STATUS_LABEL: Record<string, string> = {
  a_visiter: "À visiter",
  visite: "Visité",
  a_contacter: "À contacter",
  contacte: "Contacté",
  hot_lead: "🔥 Hot Lead",
  cold_lead: "🧊 Cold Lead",
  a_recontacter: "📅 À recontacter",
  soumissionne: "Soumissionné",
  converti: "Converti",
  perdu: "Perdu"
};

const STATUS_COLOR: Record<string, string> = {
  a_visiter: "bg-emerald-500",
  visite: "bg-blue-500",
  a_contacter: "bg-amber-500",
  contacte: "bg-violet-500",
  soumissionne: "bg-pink-500",
  converti: "bg-green-500",
  perdu: "bg-rose-500"
};

const KIND_LABEL: Record<string, string> = {
  multilogement: "Multi-logement",
  terrain: "Terrain",
  semi_commercial: "Semi-commercial",
  autre: "Autre"
};

const BUCKET_COLOR: Record<string, string> = {
  "70-100": "bg-emerald-500",
  "50-69": "bg-amber-500",
  "30-49": "bg-blue-500",
  "0-29": "bg-brand-700"
};

export default function ProspectionDashboardPage() {
  const { onOpenSidebar } = useProspectionLayout();
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const res = await authedFetch(
          "/api/v1/prospection/dashboard/stats"
        );
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = (await res.json()) as DashboardStats;
        if (!cancelled) setStats(data);
      } catch (e) {
        if (!cancelled) setError((e as Error).message);
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, []);

  const maxStatusCount = useMemo(() => {
    if (!stats) return 1;
    return Math.max(...Object.values(stats.by_status), 1);
  }, [stats]);

  const maxWeekCount = useMemo(() => {
    if (!stats || stats.leads_per_week.length === 0) return 1;
    return Math.max(...stats.leads_per_week.map((w) => w.count), 1);
  }, [stats]);

  const maxBucketCount = useMemo(() => {
    if (!stats) return 1;
    return Math.max(...stats.score_distribution.map((b) => b.count), 1);
  }, [stats]);

  const maxCityCount = useMemo(() => {
    if (!stats || stats.top_cities.length === 0) return 1;
    return Math.max(...stats.top_cities.map((c) => c.count), 1);
  }, [stats]);

  return (
    <>
      <AppTopbar
        breadcrumbs={[
          { label: "Prospection", href: "/prospection" },
          { label: "Dashboard" }
        ]}
        onOpenSidebar={onOpenSidebar}
      />

      <div className="p-4 lg:p-6">
        <h1 className="text-2xl font-bold text-white">
          Dashboard Prospection
        </h1>
        <p className="mt-1 text-sm text-white/60">
          Vue d&apos;ensemble du pipeline et de la qualité des leads
          captés en mode drive-by.
        </p>

        <PageDriveSection
          pageKey="page:prospection:dashboard"
          pole="Prospection"
          label="Tableau de bord"
          route="/prospection/dashboard"
          className="mt-4"
        />

        {error ? (
          <p className="mt-4 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-300">
            {error}
          </p>
        ) : null}

        {loading ? (
          <div className="flex min-h-[40vh] items-center justify-center">
            <Loader2 className="h-6 w-6 animate-spin text-accent-500" />
          </div>
        ) : !stats ? null : (
          <>
            {/* KPI cards */}
            <div className="mt-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <KpiCard
                icon={<MapPin className="h-4 w-4" />}
                label="Total leads"
                value={stats.total_leads.toLocaleString("fr-CA")}
                tone="neutral"
              />
              <KpiCard
                icon={<Sparkles className="h-4 w-4" />}
                label="Score moyen"
                value={stats.avg_score.toFixed(1)}
                hint={
                  stats.avg_score >= 60
                    ? "Excellent pipeline"
                    : stats.avg_score >= 40
                      ? "Pipeline moyen"
                      : "À étoffer"
                }
                tone={
                  stats.avg_score >= 60
                    ? "good"
                    : stats.avg_score >= 40
                      ? "warn"
                      : "bad"
                }
              />
              <KpiCard
                icon={<Target className="h-4 w-4" />}
                label="High-score (≥70)"
                value={stats.high_score_count.toLocaleString("fr-CA")}
                hint={
                  stats.total_leads
                    ? `${Math.round(
                        (stats.high_score_count /
                          stats.total_leads) *
                          100
                      )}% du pipeline`
                    : undefined
                }
                tone="good"
              />
              <KpiCard
                icon={<CheckCircle2 className="h-4 w-4" />}
                label="Convertis"
                value={stats.converted_count.toLocaleString("fr-CA")}
                hint={`Taux de conversion ${(
                  stats.conversion_rate * 100
                ).toFixed(1)}%`}
                tone={
                  stats.conversion_rate >= 0.2
                    ? "good"
                    : stats.conversion_rate >= 0.1
                      ? "warn"
                      : "bad"
                }
              />
            </div>

            {/* Pipeline (status) */}
            <section className="mt-6 rounded-2xl border border-brand-800 bg-brand-900 p-5">
              <header className="mb-4 flex items-center gap-2">
                <Activity className="h-4 w-4 text-accent-500" />
                <h2 className="text-sm font-semibold text-white">
                  Pipeline par statut
                </h2>
              </header>
              <ul className="space-y-2">
                {Object.entries(STATUS_LABEL).map(([k, label]) => {
                  const n = stats.by_status[k] || 0;
                  const pct = (n / maxStatusCount) * 100;
                  return (
                    <li key={k} className="flex items-center gap-3">
                      <span className="w-32 shrink-0 text-xs text-white/70">
                        {label}
                      </span>
                      <div className="relative flex-1">
                        <div className="h-5 rounded-md bg-brand-950" />
                        <div
                          className={`absolute inset-y-0 left-0 rounded-md ${STATUS_COLOR[k]} opacity-80`}
                          style={{ width: `${pct}%` }}
                        />
                      </div>
                      <span className="w-10 shrink-0 text-right text-xs tabular-nums text-white/80">
                        {n}
                      </span>
                    </li>
                  );
                })}
              </ul>
            </section>

            <div className="mt-6 grid gap-6 lg:grid-cols-2">
              {/* Leads par semaine */}
              <section className="rounded-2xl border border-brand-800 bg-brand-900 p-5">
                <header className="mb-4 flex items-center gap-2">
                  <TrendingUp className="h-4 w-4 text-accent-500" />
                  <h2 className="text-sm font-semibold text-white">
                    Leads ajoutés par semaine
                  </h2>
                </header>
                {stats.leads_per_week.length === 0 ? (
                  <p className="text-xs text-white/40">
                    Pas encore de données.
                  </p>
                ) : (
                  <div className="flex items-end gap-1.5 overflow-x-auto pb-2">
                    {stats.leads_per_week.map((w) => {
                      const h = Math.max(
                        4,
                        (w.count / maxWeekCount) * 120
                      );
                      return (
                        <div
                          key={w.week}
                          className="group relative flex flex-col items-center"
                          style={{ minWidth: 18 }}
                          title={`${w.week} : ${w.count}`}
                        >
                          <span className="mb-1 text-[10px] text-white/40 group-hover:text-white">
                            {w.count}
                          </span>
                          <div
                            className="w-full rounded-t bg-emerald-500/40 transition group-hover:bg-emerald-500"
                            style={{ height: h }}
                          />
                          <span className="mt-1 -rotate-45 text-[9px] text-white/40">
                            {w.week.split("-W")[1]}
                          </span>
                        </div>
                      );
                    })}
                  </div>
                )}
              </section>

              {/* Score distribution */}
              <section className="rounded-2xl border border-brand-800 bg-brand-900 p-5">
                <header className="mb-4 flex items-center gap-2">
                  <Sparkles className="h-4 w-4 text-accent-500" />
                  <h2 className="text-sm font-semibold text-white">
                    Distribution des scores
                  </h2>
                </header>
                <ul className="space-y-2">
                  {[...stats.score_distribution]
                    .reverse()
                    .map((b) => {
                      const pct = (b.count / maxBucketCount) * 100;
                      return (
                        <li
                          key={b.bucket}
                          className="flex items-center gap-3"
                        >
                          <span className="w-16 shrink-0 text-xs text-white/70">
                            {b.bucket}
                          </span>
                          <div className="relative flex-1">
                            <div className="h-5 rounded-md bg-brand-950" />
                            <div
                              className={`absolute inset-y-0 left-0 rounded-md ${BUCKET_COLOR[b.bucket]} opacity-80`}
                              style={{ width: `${pct}%` }}
                            />
                          </div>
                          <span className="w-10 shrink-0 text-right text-xs tabular-nums text-white/80">
                            {b.count}
                          </span>
                        </li>
                      );
                    })}
                </ul>
              </section>
            </div>

            <div className="mt-6 grid gap-6 lg:grid-cols-2">
              {/* Top villes */}
              <section className="rounded-2xl border border-brand-800 bg-brand-900 p-5">
                <header className="mb-4 flex items-center gap-2">
                  <MapPin className="h-4 w-4 text-accent-500" />
                  <h2 className="text-sm font-semibold text-white">
                    Top villes
                  </h2>
                </header>
                {stats.top_cities.length === 0 ? (
                  <p className="text-xs text-white/40">
                    Pas encore de données.
                  </p>
                ) : (
                  <ul className="space-y-2">
                    {stats.top_cities.map((c) => {
                      const pct = (c.count / maxCityCount) * 100;
                      return (
                        <li
                          key={c.city}
                          className="flex items-center gap-3"
                        >
                          <span className="w-32 shrink-0 truncate text-xs text-white/70">
                            {c.city}
                          </span>
                          <div className="relative flex-1">
                            <div className="h-5 rounded-md bg-brand-950" />
                            <div
                              className="absolute inset-y-0 left-0 rounded-md bg-emerald-500/60"
                              style={{ width: `${pct}%` }}
                            />
                          </div>
                          <span className="w-10 shrink-0 text-right text-xs tabular-nums text-white/80">
                            {c.count}
                          </span>
                        </li>
                      );
                    })}
                  </ul>
                )}
              </section>

              {/* Par type */}
              <section className="rounded-2xl border border-brand-800 bg-brand-900 p-5">
                <header className="mb-4 flex items-center gap-2">
                  <Building2 className="h-4 w-4 text-accent-500" />
                  <h2 className="text-sm font-semibold text-white">
                    Répartition par type
                  </h2>
                </header>
                <ul className="space-y-2">
                  {Object.entries(KIND_LABEL).map(([k, label]) => {
                    const n = stats.by_kind[k] || 0;
                    const pct = stats.total_leads
                      ? (n / stats.total_leads) * 100
                      : 0;
                    return (
                      <li key={k} className="flex items-center gap-3">
                        <span className="w-32 shrink-0 text-xs text-white/70">
                          {label}
                        </span>
                        <div className="relative flex-1">
                          <div className="h-5 rounded-md bg-brand-950" />
                          <div
                            className="absolute inset-y-0 left-0 rounded-md bg-violet-500/60"
                            style={{ width: `${pct}%` }}
                          />
                        </div>
                        <span className="w-16 shrink-0 text-right text-xs tabular-nums text-white/80">
                          {n} ({pct.toFixed(0)}%)
                        </span>
                      </li>
                    );
                  })}
                </ul>
              </section>
            </div>
          </>
        )}
      </div>
    </>
  );
}

function KpiCard({
  icon,
  label,
  value,
  hint,
  tone
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  hint?: string;
  tone: "neutral" | "good" | "warn" | "bad";
}) {
  const toneClass: Record<string, string> = {
    neutral: "text-white",
    good: "text-emerald-300",
    warn: "text-amber-300",
    bad: "text-rose-300"
  };
  return (
    <div className="kpi-card">
      <div className="flex items-center gap-2 text-[11px] uppercase tracking-wider text-white/50">
        {icon}
        {label}
      </div>
      <p className={`mt-2 text-2xl font-bold tabular-nums ${toneClass[tone]}`}>
        {value}
      </p>
      {hint ? (
        <p className="mt-1 flex items-center gap-1 text-[11px] text-white/50">
          <ArrowUpRight className="h-3 w-3" />
          {hint}
        </p>
      ) : null}
    </div>
  );
}
