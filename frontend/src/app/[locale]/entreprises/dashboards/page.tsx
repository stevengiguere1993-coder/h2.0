"use client";

import { useEffect, useMemo, useState } from "react";
import {
  AlarmClock,
  AlertTriangle,
  ArrowDownRight,
  ArrowUpRight,
  CheckCircle2,
  FileWarning,
  Loader2,
  Minus,
  RefreshCw
} from "lucide-react";

import { PageDriveSection } from "@/components/drive/PageDriveSection";
import { authedFetch } from "@/lib/auth";
import { Link } from "@/i18n/navigation";
import { QGTopbar } from "../layout";

/**
 * Tableau de bord exécutif cross-entreprise.
 *
 * Différent de « Vue d'ensemble » qui liste les entreprises avec
 * leur santé : ici on agrège les KPI consolidés (revenus / EBITDA /
 * trésorerie / tâches), une heatmap revenu par entreprise × 12
 * mois, des alertes actionnables, la répartition de santé, et la
 * vélocité de complétion 30 jours.
 *
 * Couleurs : tout passe par les variables de thème `--qg-*` pour
 * rester lisible en mode jour comme en mode nuit.
 */

type DashKPI = {
  label: string;
  value: number;
  previous: number | null;
  unit: string;
  format: "currency" | "count" | "percent";
};

type DashAlert = {
  severity: "high" | "medium" | "low";
  icon: string;
  title: string;
  detail: string | null;
  entreprise_id: number | null;
  entreprise_name: string | null;
  href: string | null;
};

type DashHeatmapCell = {
  year_month: string;
  revenu: number | null;
  ebitda: number | null;
};

type DashHeatmapRow = {
  entreprise_id: number;
  name: string;
  color_accent: string;
  cells: DashHeatmapCell[];
};

type DashHealthBucket = { label: "good" | "warn" | "risk"; count: number };

type DashVelocityPoint = {
  date: string;
  created: number;
  completed: number;
};

type DashboardExec = {
  generated_at: string;
  kpis: DashKPI[];
  alerts: DashAlert[];
  heatmap_months: string[];
  heatmap_rows: DashHeatmapRow[];
  health_buckets: DashHealthBucket[];
  velocity: DashVelocityPoint[];
};

function fmtCurrency(n: number): string {
  if (Math.abs(n) >= 1_000_000)
    return `${(n / 1_000_000).toFixed(1)} M$`;
  if (Math.abs(n) >= 1_000) return `${(n / 1_000).toFixed(0)} k$`;
  return `${Math.round(n)} $`;
}

function fmtCount(n: number): string {
  return Math.round(n).toLocaleString("fr-CA");
}

function fmtKPI(v: number, fmt: DashKPI["format"]): string {
  if (fmt === "currency") return fmtCurrency(v);
  if (fmt === "percent") return `${v.toFixed(1)} %`;
  return fmtCount(v);
}

function fmtMonth(s: string): string {
  // "YYYY-MM" → "Jan", "Fév", etc.
  const [y, m] = s.split("-").map(Number);
  return new Date(y, m - 1, 1).toLocaleString("fr-CA", { month: "short" });
}

const ICON_MAP: Record<string, React.ComponentType<{ className?: string }>> = {
  AlarmClock,
  AlertTriangle,
  FileWarning
};

const HEALTH_LABEL: Record<DashHealthBucket["label"], { label: string; color: string }> =
  {
    good: { label: "Saine", color: "bg-emerald-500" },
    warn: { label: "À surveiller", color: "bg-amber-500" },
    risk: { label: "À risque", color: "bg-rose-500" }
  };

// Cartes / sections : fond + bordure de thème.
const CARD_STYLE: React.CSSProperties = {
  backgroundColor: "var(--qg-card-bg)",
  borderColor: "var(--qg-border)"
};

export default function DashboardsPage() {
  const [data, setData] = useState<DashboardExec | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    setErr(null);
    try {
      const r = await authedFetch("/api/v1/entreprises/dashboard/exec");
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      setData((await r.json()) as DashboardExec);
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
  }, []);

  return (
    <>
      <QGTopbar
        greeting={
          <>
            Tableau{" "}
            <span
              className="italic"
              style={{
                color: "var(--qg-accent)",
                fontFamily: "var(--font-display, ui-sans-serif, system-ui, sans-serif)"
              }}
            >
              de bord
            </span>
          </>
        }
        subtitle="Cockpit exécutif — KPIs consolidés, alertes, heatmap"
        rightSlot={
          <button
            type="button"
            onClick={() => void load()}
            disabled={loading}
            className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--qg-border)] bg-[var(--qg-bg-alt)] px-3 py-1.5 text-xs text-[var(--qg-text)] hover:bg-[var(--qg-bg)] disabled:opacity-50"
          >
            <RefreshCw
              className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`}
            />
            Rafraîchir
          </button>
        }
      />

      <div className="px-5 py-6 lg:px-8">
        <PageDriveSection
          pageKey="page:entreprises:dashboards"
          pole="Gestion d'entreprises"
          label="Tableaux de bord"
          route="/entreprises/dashboards"
        />
        {err ? (
          <p className="mb-4 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-600">
            {err}
          </p>
        ) : null}

        {data === null ? (
          <p
            className="py-12 text-center text-sm"
            style={{ color: "var(--qg-text-soft)" }}
          >
            <Loader2 className="mr-2 inline h-4 w-4 animate-spin" />
            Chargement du cockpit…
          </p>
        ) : (
          <>
            <KPIStrip kpis={data.kpis} />
            <div className="mt-6 grid gap-4 lg:grid-cols-3">
              <HealthOverview buckets={data.health_buckets} />
              <AlertsPanel alerts={data.alerts} />
            </div>
            <HeatmapPanel
              months={data.heatmap_months}
              rows={data.heatmap_rows}
            />
            <VelocityPanel points={data.velocity} />
            <p
              className="mt-6 text-center text-[10px]"
              style={{ color: "var(--qg-text-soft)" }}
            >
              Généré {new Date(data.generated_at).toLocaleString("fr-CA")}
            </p>
          </>
        )}
      </div>
    </>
  );
}

// ─── KPI strip ─────────────────────────────────────────────────────

function KPIStrip({ kpis }: { kpis: DashKPI[] }) {
  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
      {kpis.map((k, i) => {
        const delta =
          k.previous != null && k.previous !== 0
            ? ((k.value - k.previous) / Math.abs(k.previous)) * 100
            : null;
        const deltaIsGood =
          delta !== null && (k.format === "count" && k.label.includes("ouvertes")
            ? delta < 0   // moins de tâches ouvertes = bon
            : delta > 0);
        // Couleurs lisibles en mode jour ET nuit (shades médium).
        const deltaColor =
          delta === null || delta === 0
            ? "var(--qg-text-soft)"
            : deltaIsGood
              ? "#10b981"
              : "#f43f5e";
        return (
          <div
            key={i}
            className="rounded-2xl border p-4 shadow-card"
            style={CARD_STYLE}
          >
            <p
              className="text-[10px] uppercase tracking-wider"
              style={{ color: "var(--qg-text-soft)" }}
            >
              {k.label}
            </p>
            <p
              className="mt-1 text-2xl font-bold"
              style={{
                color: "var(--qg-text)",
                fontFamily: "var(--font-display, ui-sans-serif, system-ui, sans-serif)"
              }}
            >
              {fmtKPI(k.value, k.format)}
            </p>
            {delta !== null ? (
              <p
                className="mt-1 inline-flex items-center gap-1 text-[11px] font-semibold"
                style={{ color: deltaColor }}
              >
                {delta > 0.5 ? (
                  <ArrowUpRight className="h-3 w-3" />
                ) : delta < -0.5 ? (
                  <ArrowDownRight className="h-3 w-3" />
                ) : (
                  <Minus className="h-3 w-3" />
                )}
                {delta > 0 ? "+" : ""}
                {delta.toFixed(1)} %
              </p>
            ) : (
              <p
                className="mt-1 text-[11px]"
                style={{ color: "var(--qg-text-soft)" }}
              >
                {k.previous === null ? "—" : "vs précédent"}
              </p>
            )}
          </div>
        );
      })}
    </div>
  );
}

// ─── Santé répartition ─────────────────────────────────────────────

function HealthOverview({ buckets }: { buckets: DashHealthBucket[] }) {
  const total = buckets.reduce((s, b) => s + b.count, 0);
  return (
    <section className="rounded-2xl border p-5" style={CARD_STYLE}>
      <h2
        className="text-sm font-semibold uppercase tracking-wider"
        style={{ color: "var(--qg-accent)" }}
      >
        ✦ Santé du portefeuille
      </h2>
      <p className="mt-0.5 text-xs" style={{ color: "var(--qg-text-soft)" }}>
        Répartition des entreprises actives par état actuel.
      </p>
      <div className="mt-4 space-y-2">
        {buckets.map((b) => {
          const meta = HEALTH_LABEL[b.label];
          const pct = total > 0 ? (b.count / total) * 100 : 0;
          return (
            <div key={b.label}>
              <div className="flex items-center justify-between text-xs">
                <span style={{ color: "var(--qg-text-muted)" }}>
                  {meta.label}
                </span>
                <span
                  className="font-mono"
                  style={{ color: "var(--qg-text)" }}
                >
                  {b.count}
                </span>
              </div>
              <div
                className="mt-1 h-2 overflow-hidden rounded-full"
                style={{ backgroundColor: "var(--qg-bg-alt)" }}
              >
                <div
                  className={`h-full ${meta.color} transition-all`}
                  style={{ width: `${pct}%` }}
                />
              </div>
            </div>
          );
        })}
      </div>
      <Link
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        href={"/entreprises" as any}
        className="mt-4 inline-flex items-center text-[11px] hover:underline"
        style={{ color: "var(--qg-accent)" }}
      >
        → Voir le détail par entreprise
      </Link>
    </section>
  );
}

// ─── Alertes ───────────────────────────────────────────────────────

function AlertsPanel({ alerts }: { alerts: DashAlert[] }) {
  return (
    <section
      className="rounded-2xl border p-5 lg:col-span-2"
      style={CARD_STYLE}
    >
      <h2
        className="text-sm font-semibold uppercase tracking-wider"
        style={{ color: "var(--qg-accent)" }}
      >
        ⚠ Alertes actionnables
      </h2>
      <p className="mt-0.5 text-xs" style={{ color: "var(--qg-text-soft)" }}>
        À traiter en priorité — modèles en retard, tâches très en retard,
        snapshots manquants.
      </p>
      {alerts.length === 0 ? (
        <p className="mt-4 inline-flex items-center gap-2 rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-xs text-emerald-600">
          <CheckCircle2 className="h-3.5 w-3.5" />
          Aucune alerte. Tout est sous contrôle.
        </p>
      ) : (
        <ul className="mt-4 space-y-2">
          {alerts.map((a, i) => {
            const Icon = ICON_MAP[a.icon] || AlertTriangle;
            // Styles lisibles en mode jour ET nuit.
            const sevStyle: React.CSSProperties =
              a.severity === "high"
                ? {
                    borderColor: "rgba(244,63,94,0.4)",
                    backgroundColor: "rgba(244,63,94,0.1)",
                    color: "#e11d48"
                  }
                : a.severity === "medium"
                  ? {
                      borderColor: "rgba(245,158,11,0.45)",
                      backgroundColor: "rgba(245,158,11,0.1)",
                      color: "#d97706"
                    }
                  : {
                      borderColor: "var(--qg-border)",
                      backgroundColor: "var(--qg-bg-alt)",
                      color: "var(--qg-text-muted)"
                    };
            const inner = (
              <div
                className="flex items-start gap-3 rounded-lg border px-3 py-2"
                style={sevStyle}
              >
                <Icon className="mt-0.5 h-4 w-4 flex-shrink-0" />
                <div className="min-w-0 flex-1">
                  <p className="text-xs font-bold">{a.title}</p>
                  {a.detail ? (
                    <p className="mt-0.5 truncate text-[11px] opacity-80">
                      {a.detail}
                    </p>
                  ) : null}
                  {a.entreprise_name ? (
                    <p className="mt-0.5 text-[10px] opacity-60">
                      {a.entreprise_name}
                    </p>
                  ) : null}
                </div>
              </div>
            );
            return (
              <li key={i}>
                {a.href ? (
                  <Link
                    // eslint-disable-next-line @typescript-eslint/no-explicit-any
                    href={a.href as any}
                    className="block"
                  >
                    {inner}
                  </Link>
                ) : (
                  inner
                )}
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

// ─── Heatmap revenus ───────────────────────────────────────────────

function HeatmapPanel({
  months,
  rows
}: {
  months: string[];
  rows: DashHeatmapRow[];
}) {
  // Échelle de couleur : 0 → max revenu sur la fenêtre.
  const max = useMemo(() => {
    let m = 0;
    for (const r of rows) {
      for (const c of r.cells) {
        if ((c.revenu || 0) > m) m = c.revenu || 0;
      }
    }
    return m;
  }, [rows]);

  function cellStyle(rev: number | null): React.CSSProperties {
    if (rev === null) return { backgroundColor: "var(--qg-bg-alt)" };
    if (max === 0) return { backgroundColor: "var(--qg-card-bg)" };
    const ratio = Math.max(0, Math.min(1, rev / max));
    // Vert d'intensité proportionnelle — lisible sur fond clair ou sombre.
    return {
      backgroundColor: `rgba(16, 185, 129, ${0.12 + ratio * 0.78})`
    };
  }

  return (
    <section className="mt-6 rounded-2xl border p-5" style={CARD_STYLE}>
      <h2
        className="text-sm font-semibold uppercase tracking-wider"
        style={{ color: "var(--qg-accent)" }}
      >
        ▦ Heatmap revenus · 12 mois
      </h2>
      <p className="mt-0.5 text-xs" style={{ color: "var(--qg-text-soft)" }}>
        Plus la cellule est verte, plus le revenu mensuel est élevé pour
        cette entreprise.
      </p>
      {rows.length === 0 ? (
        <p className="mt-4 text-xs" style={{ color: "var(--qg-text-soft)" }}>
          Aucune entreprise active.
        </p>
      ) : (
        <div className="mt-4 overflow-x-auto">
          <table className="w-full min-w-[720px] text-[11px]">
            <thead>
              <tr>
                <th
                  className="sticky left-0 z-10 py-2 pr-2 text-left font-semibold"
                  style={{
                    backgroundColor: "var(--qg-card-bg)",
                    color: "var(--qg-text-soft)"
                  }}
                >
                  Entreprise
                </th>
                {months.map((m) => (
                  <th
                    key={m}
                    className="px-1 py-2 text-center font-mono text-[10px]"
                    style={{ color: "var(--qg-text-soft)" }}
                  >
                    {fmtMonth(m)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.entreprise_id}>
                  <td
                    className="sticky left-0 z-10 py-1.5 pr-2 font-semibold"
                    style={{
                      backgroundColor: "var(--qg-card-bg)",
                      color: "var(--qg-text-muted)"
                    }}
                  >
                    <Link
                      // eslint-disable-next-line @typescript-eslint/no-explicit-any
                      href={`/entreprises/${r.entreprise_id}` as any}
                      className="inline-flex items-center gap-1.5 hover:text-[var(--qg-accent)]"
                    >
                      <span
                        className="h-2 w-2 rounded-full"
                        style={{ backgroundColor: r.color_accent }}
                      />
                      {r.name}
                    </Link>
                  </td>
                  {r.cells.map((c) => (
                    <td key={c.year_month} className="px-1 py-1">
                      <div
                        className="rounded px-1 py-0.5 text-center text-[10px] font-mono"
                        style={{
                          ...cellStyle(c.revenu),
                          color: "var(--qg-text)"
                        }}
                        title={
                          c.revenu !== null
                            ? `${c.year_month} · ${fmtCurrency(c.revenu)}`
                            : `${c.year_month} · sans donnée`
                        }
                      >
                        {c.revenu !== null
                          ? fmtCurrency(c.revenu).replace(" $", "")
                          : "—"}
                      </div>
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

// ─── Vélocité tâches 30j ───────────────────────────────────────────

function VelocityPanel({ points }: { points: DashVelocityPoint[] }) {
  const max = Math.max(
    1,
    ...points.map((p) => Math.max(p.created, p.completed))
  );
  const totalCreated = points.reduce((s, p) => s + p.created, 0);
  const totalCompleted = points.reduce((s, p) => s + p.completed, 0);
  return (
    <section className="mt-6 rounded-2xl border p-5" style={CARD_STYLE}>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <h2
            className="text-sm font-semibold uppercase tracking-wider"
            style={{ color: "var(--qg-accent)" }}
          >
            ↗ Vélocité · 30 jours
          </h2>
          <p
            className="mt-0.5 text-xs"
            style={{ color: "var(--qg-text-soft)" }}
          >
            Tâches créées vs terminées par jour.
          </p>
        </div>
        <div
          className="flex items-baseline gap-3 text-[11px]"
          style={{ color: "var(--qg-text-muted)" }}
        >
          <span>
            <span
              className="mr-1 inline-block h-2 w-2 rounded-full"
              style={{ backgroundColor: "rgb(167 139 250)" }}
            />
            Créées : <span className="font-mono">{totalCreated}</span>
          </span>
          <span>
            <span className="mr-1 inline-block h-2 w-2 rounded-full bg-emerald-400" />
            Terminées : <span className="font-mono">{totalCompleted}</span>
          </span>
        </div>
      </div>

      <div className="mt-4 flex h-32 items-end gap-[2px]">
        {points.map((p) => (
          <div
            key={p.date}
            className="relative flex h-full flex-1 flex-col justify-end"
            title={`${p.date} · ${p.created} créées · ${p.completed} terminées`}
          >
            <div
              className="w-full rounded-t bg-emerald-400"
              style={{
                height: `${(p.completed / max) * 100}%`,
                minHeight: p.completed > 0 ? 2 : 0
              }}
            />
            <div
              className="w-full rounded-t bg-violet-400"
              style={{
                height: `${(p.created / max) * 100}%`,
                minHeight: p.created > 0 ? 2 : 0,
                opacity: 0.45
              }}
            />
          </div>
        ))}
      </div>
      <div
        className="mt-1 flex justify-between text-[9px]"
        style={{ color: "var(--qg-text-soft)" }}
      >
        <span>il y a 30j</span>
        <span>aujourd&apos;hui</span>
      </div>
    </section>
  );
}
