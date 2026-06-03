"use client";

import { useEffect, useMemo, useState } from "react";
import {
  Activity,
  AlertCircle,
  CalendarClock,
  CheckCircle2,
  Clock,
  Loader2,
  Phone,
  Sparkles,
  Target,
  TrendingUp,
  Trophy,
  UserCircle
} from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { PageDriveSection } from "@/components/drive/PageDriveSection";
import { authedFetch } from "@/lib/auth";
import { useAppLayout } from "../../layout";

type ProspectorStats = {
  user_id: number;
  total_calls: number;
  total_emails: number;
  total_visits: number;
  reached: number;
  interested: number;
  won: number;
  lost: number;
  avg_response_rate: number;
  conversion_rate: number;
};

type CrmDashboard = {
  period_days: number;
  total_leads: number;
  new_leads: number;
  by_status: Record<string, number>;
  avg_time_to_first_contact_hours: number | null;
  follow_ups_count: number;
  overdue_count: number;
  upcoming_count: number;
  leads_per_week: { week: string; count: number }[];
  per_prospector: ProspectorStats[];
  sla_breach_count?: number;
  sla_threshold_hours?: number;
};

type UserRead = {
  id: number;
  email: string;
  first_name?: string | null;
  last_name?: string | null;
};

const STATUS_LABEL: Record<string, string> = {
  new: "Nouveau",
  contacted: "Contacté",
  qualified: "Qualifié",
  quoted: "Soumis",
  won: "Gagné",
  lost: "Perdu",
  spam: "Spam"
};

const STATUS_COLOR: Record<string, string> = {
  new: "bg-blue-500",
  contacted: "bg-violet-500",
  qualified: "bg-amber-500",
  quoted: "bg-pink-500",
  won: "bg-emerald-500",
  lost: "bg-rose-500",
  spam: "bg-brand-700"
};

export default function CrmDashboardPage() {
  const { onOpenSidebar } = useAppLayout();
  const [stats, setStats] = useState<CrmDashboard | null>(null);
  const [users, setUsers] = useState<UserRead[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [period, setPeriod] = useState(90);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const [r1, r2] = await Promise.all([
          authedFetch(
            `/api/v1/follow-ups/dashboard/crm?period_days=${period}`
          ),
          authedFetch("/api/v1/users")
        ]);
        if (!r1.ok) throw new Error(`HTTP ${r1.status}`);
        if (!cancelled) {
          setStats((await r1.json()) as CrmDashboard);
          if (r2.ok) {
            setUsers((await r2.json()) as UserRead[]);
          }
        }
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
  }, [period]);

  const userMap = useMemo(() => {
    const m: Record<number, UserRead> = {};
    for (const u of users) m[u.id] = u;
    return m;
  }, [users]);

  const maxStatus = useMemo(() => {
    if (!stats) return 1;
    return Math.max(...Object.values(stats.by_status), 1);
  }, [stats]);

  const maxWeek = useMemo(() => {
    if (!stats || stats.leads_per_week.length === 0) return 1;
    return Math.max(...stats.leads_per_week.map((w) => w.count), 1);
  }, [stats]);

  function userLabel(uid: number): string {
    const u = userMap[uid];
    if (!u) return `User #${uid}`;
    if (u.first_name || u.last_name)
      return `${u.first_name || ""} ${u.last_name || ""}`.trim();
    return u.email;
  }

  return (
    <>
      <AppTopbar
        breadcrumbs={[
          { label: "CRM", href: "/app/crm" },
          { label: "Dashboard" }
        ]}
        onOpenSidebar={onOpenSidebar}
        rightSlot={
          <select
            value={period}
            onChange={(e) => setPeriod(Number(e.target.value))}
            className="rounded-md border border-brand-700 bg-brand-900 px-2 py-1 text-xs text-white"
          >
            <option value="30">30 jours</option>
            <option value="90">90 jours</option>
            <option value="180">6 mois</option>
            <option value="365">12 mois</option>
          </select>
        }
      />

      <div className="p-4 lg:p-6">
        <h1 className="text-2xl font-bold text-white">
          Dashboard CRM
        </h1>
        <p className="mt-1 text-sm text-white/60">
          Volume de leads, conversion et performance par prospecteur
          sur les {period} derniers jours.
        </p>

        <PageDriveSection
          pageKey="page:app:crm-dashboard"
          pole="Construction"
          label="CRM — Tableau de bord"
          route="/app/crm/dashboard"
          className="mt-6"
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
              <Kpi
                icon={<UserCircle className="h-4 w-4" />}
                label="Total leads"
                value={stats.total_leads.toLocaleString("fr-CA")}
                hint={`${stats.new_leads} nouveaux non traités`}
                tone={stats.new_leads > 0 ? "warn" : "good"}
              />
              <Kpi
                icon={<Activity className="h-4 w-4" />}
                label="Suivis (période)"
                value={stats.follow_ups_count.toLocaleString(
                  "fr-CA"
                )}
                hint={
                  stats.total_leads
                    ? `${(
                        stats.follow_ups_count / stats.total_leads
                      ).toFixed(1)} par lead`
                    : undefined
                }
                tone="neutral"
              />
              <Kpi
                icon={<AlertCircle className="h-4 w-4" />}
                label="En retard"
                value={stats.overdue_count.toLocaleString("fr-CA")}
                hint={
                  stats.overdue_count > 0
                    ? "Action requise"
                    : "Tout à jour"
                }
                tone={stats.overdue_count > 0 ? "bad" : "good"}
              />
              <Kpi
                icon={<Clock className="h-4 w-4" />}
                label="Temps 1er contact"
                value={
                  stats.avg_time_to_first_contact_hours != null
                    ? `${stats.avg_time_to_first_contact_hours.toFixed(0)} h`
                    : "—"
                }
                hint={
                  stats.avg_time_to_first_contact_hours != null
                    ? stats.avg_time_to_first_contact_hours < 4
                      ? "Excellent"
                      : stats.avg_time_to_first_contact_hours < 24
                        ? "Bon"
                        : "À améliorer"
                    : undefined
                }
                tone={
                  stats.avg_time_to_first_contact_hours != null
                    ? stats.avg_time_to_first_contact_hours < 4
                      ? "good"
                      : stats.avg_time_to_first_contact_hours < 24
                        ? "warn"
                        : "bad"
                    : "neutral"
                }
              />
            </div>

            {/* SLA breach banner */}
            {stats.sla_breach_count != null &&
            stats.sla_breach_count > 0 ? (
              <div className="mt-4 flex items-center gap-3 rounded-lg border border-rose-500/40 bg-rose-500/10 px-4 py-3">
                <AlertCircle className="h-5 w-5 shrink-0 text-rose-300" />
                <div className="flex-1">
                  <p className="text-sm font-bold text-rose-200">
                    SLA dépassé : {stats.sla_breach_count} lead
                    {stats.sla_breach_count > 1 ? "s" : ""} non
                    contacté{stats.sla_breach_count > 1 ? "s" : ""}{" "}
                    après {stats.sla_threshold_hours || 4} h
                  </p>
                  <p className="mt-0.5 text-xs text-rose-200/70">
                    Action requise : assigne et appelle ces prospects
                    avant qu&apos;ils refroidissent.
                  </p>
                </div>
              </div>
            ) : null}

            {/* Pipeline + leads/sem */}
            <div className="mt-6 grid gap-6 lg:grid-cols-2">
              <section className="rounded-2xl border border-brand-800 bg-brand-900 p-5">
                <h2 className="mb-4 flex items-center gap-2 text-sm font-semibold text-white">
                  <Activity className="h-4 w-4 text-accent-500" />
                  Pipeline par statut
                </h2>
                <ul className="space-y-2">
                  {Object.entries(STATUS_LABEL).map(([k, label]) => {
                    const n = stats.by_status[k] || 0;
                    const pct = (n / maxStatus) * 100;
                    return (
                      <li key={k} className="flex items-center gap-3">
                        <span className="w-24 shrink-0 text-xs text-white/70">
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

              <section className="rounded-2xl border border-brand-800 bg-brand-900 p-5">
                <h2 className="mb-4 flex items-center gap-2 text-sm font-semibold text-white">
                  <TrendingUp className="h-4 w-4 text-accent-500" />
                  Leads par semaine
                </h2>
                {stats.leads_per_week.length === 0 ? (
                  <p className="text-xs text-white/40">
                    Pas encore de données.
                  </p>
                ) : (
                  <div className="flex items-end gap-1.5 overflow-x-auto pb-2">
                    {stats.leads_per_week.map((w) => {
                      const h = Math.max(
                        4,
                        (w.count / maxWeek) * 120
                      );
                      return (
                        <div
                          key={w.week}
                          className="group flex flex-col items-center"
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
            </div>

            {/* Per-prospector leaderboard */}
            <section className="mt-6 rounded-2xl border border-brand-800 bg-brand-900 p-5">
              <h2 className="mb-4 flex items-center gap-2 text-sm font-semibold text-white">
                <Trophy className="h-4 w-4 text-accent-500" />
                Performance par prospecteur
              </h2>
              {stats.per_prospector.length === 0 ? (
                <p className="text-xs text-white/40">
                  Aucun suivi journalisé sur la période.
                </p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead className="text-left text-[10px] uppercase tracking-wider text-white/50">
                      <tr>
                        <th className="px-2 py-2">Prospecteur</th>
                        <th className="px-2 py-2 text-right">Appels</th>
                        <th className="px-2 py-2 text-right">
                          Courriels
                        </th>
                        <th className="px-2 py-2 text-right">Visites</th>
                        <th className="px-2 py-2 text-right">
                          Joints
                        </th>
                        <th className="px-2 py-2 text-right">
                          Intéressés
                        </th>
                        <th className="px-2 py-2 text-right">Gagnés</th>
                        <th className="px-2 py-2 text-right">Perdus</th>
                        <th className="px-2 py-2 text-right">
                          Tx réponse
                        </th>
                        <th className="px-2 py-2 text-right">
                          Conversion
                        </th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-brand-800">
                      {stats.per_prospector.map((p, idx) => (
                        <tr key={p.user_id}>
                          <td className="px-2 py-2 text-white">
                            {idx === 0 ? (
                              <Trophy className="mr-1 inline h-3 w-3 text-amber-400" />
                            ) : null}
                            {userLabel(p.user_id)}
                          </td>
                          <td className="px-2 py-2 text-right tabular-nums text-white/80">
                            {p.total_calls}
                          </td>
                          <td className="px-2 py-2 text-right tabular-nums text-white/80">
                            {p.total_emails}
                          </td>
                          <td className="px-2 py-2 text-right tabular-nums text-white/80">
                            {p.total_visits}
                          </td>
                          <td className="px-2 py-2 text-right tabular-nums text-emerald-300">
                            {p.reached}
                          </td>
                          <td className="px-2 py-2 text-right tabular-nums text-amber-300">
                            {p.interested}
                          </td>
                          <td className="px-2 py-2 text-right tabular-nums font-bold text-emerald-300">
                            {p.won}
                          </td>
                          <td className="px-2 py-2 text-right tabular-nums text-rose-300">
                            {p.lost}
                          </td>
                          <td className="px-2 py-2 text-right tabular-nums text-white/80">
                            {(p.avg_response_rate * 100).toFixed(0)}%
                          </td>
                          <td
                            className={`px-2 py-2 text-right tabular-nums font-bold ${
                              p.conversion_rate >= 0.3
                                ? "text-emerald-300"
                                : p.conversion_rate >= 0.15
                                  ? "text-amber-300"
                                  : "text-rose-300"
                            }`}
                          >
                            {(p.conversion_rate * 100).toFixed(0)}%
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </section>
          </>
        )}
      </div>
    </>
  );
}

function Kpi({
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
  const c: Record<string, string> = {
    neutral: "text-white",
    good: "text-emerald-300",
    warn: "text-amber-300",
    bad: "text-rose-300"
  };
  return (
    <div className="rounded-2xl border border-brand-800 bg-brand-900 p-4">
      <div className="flex items-center gap-2 text-[11px] uppercase tracking-wider text-white/50">
        {icon}
        {label}
      </div>
      <p className={`mt-2 text-2xl font-bold tabular-nums ${c[tone]}`}>
        {value}
      </p>
      {hint ? (
        <p className="mt-1 text-[11px] text-white/50">{hint}</p>
      ) : null}
    </div>
  );
}
