"use client";

import { useEffect, useState } from "react";
import {
  BarChart3,
  Building2,
  Loader2,
  Target,
  TrendingDown,
  TrendingUp
} from "lucide-react";

import { PageDriveSection } from "@/components/drive/PageDriveSection";
import { Link } from "@/i18n/navigation";
import { authedFetch } from "@/lib/auth";
import { EntreprisesTopbar } from "../layout";

type Summary = {
  entreprise_id: number;
  name: string;
  color_accent: string;
  last_month?: string | null;
  revenu_ttm?: number | null;
  ebitda_ttm?: number | null;
  tresorerie_courante?: number | null;
  valorisation_courante?: number | null;
  target_valuation?: number | null;
  progress_pct?: number | null;
};

function fmtCurrency(n: number | null | undefined): string {
  if (n == null) return "—";
  return new Intl.NumberFormat("fr-CA", {
    style: "currency",
    currency: "CAD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2
  }).format(n);
}

export default function ComparatifPage() {
  const [list, setList] = useState<Summary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sortBy, setSortBy] = useState<
    "name" | "revenu" | "ebitda" | "tresorerie" | "valo" | "progress"
  >("revenu");

  useEffect(() => {
    let cancelled = false;
    authedFetch("/api/v1/entreprises/finance/summaries")
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((d) => {
        if (!cancelled) setList(d as Summary[]);
      })
      .catch((e) => {
        if (!cancelled) setError((e as Error).message);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const sorted = list
    ? [...list].sort((a, b) => {
        if (sortBy === "name") return a.name.localeCompare(b.name);
        if (sortBy === "revenu")
          return (b.revenu_ttm || 0) - (a.revenu_ttm || 0);
        if (sortBy === "ebitda")
          return (b.ebitda_ttm || 0) - (a.ebitda_ttm || 0);
        if (sortBy === "tresorerie")
          return (b.tresorerie_courante || 0) - (a.tresorerie_courante || 0);
        if (sortBy === "valo")
          return (b.valorisation_courante || 0) - (a.valorisation_courante || 0);
        if (sortBy === "progress")
          return (b.progress_pct || 0) - (a.progress_pct || 0);
        return 0;
      })
    : null;

  const totals = list
    ? list.reduce(
        (acc, s) => ({
          revenu: acc.revenu + (s.revenu_ttm || 0),
          ebitda: acc.ebitda + (s.ebitda_ttm || 0),
          tresorerie: acc.tresorerie + (s.tresorerie_courante || 0),
          valo: acc.valo + (s.valorisation_courante || 0),
          target: acc.target + (s.target_valuation || 0)
        }),
        { revenu: 0, ebitda: 0, tresorerie: 0, valo: 0, target: 0 }
      )
    : null;

  return (
    <>
      <EntreprisesTopbar
        breadcrumbs={[
          { label: "Gestion d'entreprises", href: "/entreprises" },
          { label: "Comparatif portefeuille" }
        ]}
      />
      <div className="p-4 lg:p-6">
        <PageDriveSection
          pageKey="page:entreprises:comparatif"
          pole="Gestion d'entreprises"
          label="Comparatif"
          route="/entreprises/comparatif"
        />
        <header className="flex items-start gap-3">
          <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-violet-500/15 text-violet-300">
            <BarChart3 className="h-5 w-5" />
          </span>
          <div>
            <h1
              className="text-2xl font-bold text-white"
              style={{ fontFamily: "var(--font-fraunces, Georgia, serif)" }}
            >
              Comparatif portefeuille
            </h1>
            <p className="mt-1 text-sm text-white/60">
              Vue côté à côte : revenu TTM, EBITDA, trésorerie, valorisation,
              progression vers cible.
            </p>
          </div>
        </header>

        {error ? (
          <p className="mt-4 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
            {error}
          </p>
        ) : null}

        {totals ? (
          <section className="mt-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <KpiTotal
              label="Revenu cumulé (12m)"
              value={fmtCurrency(totals.revenu)}
              icon={TrendingUp}
              tone="emerald"
            />
            <KpiTotal
              label="EBITDA cumulé (12m)"
              value={fmtCurrency(totals.ebitda)}
              icon={TrendingUp}
              tone="violet"
            />
            <KpiTotal
              label="Trésorerie totale"
              value={fmtCurrency(totals.tresorerie)}
              icon={Building2}
              tone="sky"
            />
            <KpiTotal
              label="Valorisation totale"
              value={fmtCurrency(totals.valo)}
              sub={
                totals.target > 0
                  ? `Cible ${fmtCurrency(totals.target)}`
                  : undefined
              }
              icon={Target}
              tone="amber"
            />
          </section>
        ) : null}

        <section className="mt-6">
          {sorted === null ? (
            <p className="text-xs text-white/50">
              <Loader2 className="mr-1 inline h-3 w-3 animate-spin" /> Chargement…
            </p>
          ) : sorted.length === 0 ? (
            <p className="rounded-lg border border-brand-800 bg-brand-900 px-4 py-3 text-sm text-white/60">
              Aucune entreprise active.
            </p>
          ) : (
            <div className="overflow-hidden rounded-2xl border border-brand-800 bg-brand-900">
              <table className="w-full text-left text-sm">
                <thead className="border-b border-brand-800 bg-brand-950 text-[10px] uppercase tracking-wider text-white/50">
                  <tr>
                    <ThSort
                      label="Entreprise"
                      active={sortBy === "name"}
                      onClick={() => setSortBy("name")}
                    />
                    <ThSort
                      label="Revenu (12m)"
                      active={sortBy === "revenu"}
                      onClick={() => setSortBy("revenu")}
                      align="right"
                    />
                    <ThSort
                      label="EBITDA (12m)"
                      active={sortBy === "ebitda"}
                      onClick={() => setSortBy("ebitda")}
                      align="right"
                    />
                    <ThSort
                      label="Trésorerie"
                      active={sortBy === "tresorerie"}
                      onClick={() => setSortBy("tresorerie")}
                      align="right"
                    />
                    <ThSort
                      label="Valorisation"
                      active={sortBy === "valo"}
                      onClick={() => setSortBy("valo")}
                      align="right"
                    />
                    <ThSort
                      label="Progression cible"
                      active={sortBy === "progress"}
                      onClick={() => setSortBy("progress")}
                      align="right"
                    />
                  </tr>
                </thead>
                <tbody className="divide-y divide-brand-800">
                  {sorted.map((s) => (
                    <tr key={s.entreprise_id} className="hover:bg-brand-950/50">
                      <td className="px-4 py-2.5">
                        <Link
                          // eslint-disable-next-line @typescript-eslint/no-explicit-any
                          href={`/entreprises/${s.entreprise_id}/pilotage` as any}
                          className="flex items-center gap-3"
                        >
                          <span
                            className="h-7 w-7 flex-shrink-0 rounded-md"
                            style={{ backgroundColor: s.color_accent }}
                          />
                          <div>
                            <div className="font-bold text-white">
                              {s.name}
                            </div>
                            <div className="text-[10px] text-white/40">
                              {s.last_month || "aucune donnée"}
                            </div>
                          </div>
                        </Link>
                      </td>
                      <td className="px-4 py-2.5 text-right font-mono text-xs text-emerald-300">
                        {fmtCurrency(s.revenu_ttm)}
                      </td>
                      <td
                        className={`px-4 py-2.5 text-right font-mono text-xs ${
                          (s.ebitda_ttm || 0) >= 0
                            ? "text-violet-300"
                            : "text-rose-300"
                        }`}
                      >
                        {fmtCurrency(s.ebitda_ttm)}
                      </td>
                      <td className="px-4 py-2.5 text-right font-mono text-xs text-sky-300">
                        {fmtCurrency(s.tresorerie_courante)}
                      </td>
                      <td className="px-4 py-2.5 text-right font-mono text-xs text-amber-200">
                        {fmtCurrency(s.valorisation_courante)}
                      </td>
                      <td className="px-4 py-2.5 text-right">
                        <ProgressBar pct={s.progress_pct} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      </div>
    </>
  );
}

function ThSort({
  label,
  active,
  onClick,
  align = "left"
}: {
  label: string;
  active: boolean;
  onClick: () => void;
  align?: "left" | "right";
}) {
  return (
    <th className={`px-4 py-2.5 text-${align}`}>
      <button
        type="button"
        onClick={onClick}
        className={`hover:text-white ${active ? "text-violet-300" : "text-white/50"}`}
      >
        {label} {active ? "↓" : ""}
      </button>
    </th>
  );
}

function ProgressBar({ pct }: { pct: number | null | undefined }) {
  if (pct == null) return <span className="text-white/40">—</span>;
  const clamped = Math.min(100, Math.max(0, pct));
  const tone =
    pct >= 80 ? "bg-emerald-400" : pct >= 50 ? "bg-amber-400" : "bg-rose-400";
  return (
    <div className="inline-flex items-center gap-2">
      <div className="h-1.5 w-20 overflow-hidden rounded-full bg-brand-800">
        <div
          className={`h-full rounded-full ${tone}`}
          style={{ width: `${clamped}%` }}
        />
      </div>
      <span className="font-mono text-xs text-white/70">
        {pct.toFixed(0)}%
      </span>
    </div>
  );
}

function KpiTotal({
  label,
  value,
  sub,
  icon: Icon,
  tone
}: {
  label: string;
  value: string;
  sub?: string;
  icon: React.ComponentType<{ className?: string }>;
  tone: "emerald" | "violet" | "sky" | "amber";
}) {
  const cls: Record<typeof tone, string> = {
    emerald: "bg-emerald-500/15 text-emerald-300",
    violet: "bg-violet-500/15 text-violet-300",
    sky: "bg-sky-500/15 text-sky-300",
    amber: "bg-amber-500/15 text-amber-300"
  };
  void TrendingDown;
  return (
    <div className="rounded-2xl border border-brand-800 bg-brand-900 p-4">
      <div className="flex items-center justify-between">
        <span className="text-[10px] font-semibold uppercase tracking-wider text-white/50">
          {label}
        </span>
        <span
          className={`flex h-8 w-8 items-center justify-center rounded-lg ${cls[tone]}`}
        >
          <Icon className="h-4 w-4" />
        </span>
      </div>
      <div className="mt-3 text-2xl font-bold text-white">{value}</div>
      {sub ? <div className="mt-1 text-xs text-white/50">{sub}</div> : null}
    </div>
  );
}
