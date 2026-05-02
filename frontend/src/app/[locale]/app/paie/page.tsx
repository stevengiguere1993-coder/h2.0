"use client";

import { useCallback, useEffect, useState } from "react";
import {
  AlertTriangle,
  ChevronLeft,
  ChevronRight,
  Download,
  Loader2,
  RefreshCw,
  Wallet
} from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { useAppLayout } from "../layout";
import { authedFetch } from "@/lib/auth";

type Row = {
  employe_id: number;
  employe_name: string;
  hours_week_1: number;
  hours_week_2: number;
  total_hours: number;
  pending_hours: number;
};

type Report = {
  period_start: string;
  week_1_end: string;
  week_2_start: string;
  period_end: string;
  cutoff_date: string;
  pay_date: string;
  days_until_cutoff: number;
  days_until_pay: number;
  rows: Row[];
  total_hours: number;
  total_pending_hours: number;
};

function fmtDate(s: string): string {
  // YYYY-MM-DD → "26 avr. 2026"
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(s);
  if (!m) return s;
  const d = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
  return d.toLocaleDateString("fr-CA", {
    day: "numeric",
    month: "short",
    year: "numeric"
  });
}

function fmtDateShort(s: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(s);
  if (!m) return s;
  const d = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
  return d.toLocaleDateString("fr-CA", {
    day: "numeric",
    month: "short"
  });
}

function shiftPeriodEnd(currentEnd: string, days: number): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(currentEnd);
  if (!m) return currentEnd;
  const d = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
  d.setDate(d.getDate() + days);
  const y = d.getFullYear();
  const mo = String(d.getMonth() + 1).padStart(2, "0");
  const da = String(d.getDate()).padStart(2, "0");
  return `${y}-${mo}-${da}`;
}

// Construit une liste de fins de période (ISO YYYY-MM-DD) centrée
// sur `currentEnd`. 4 périodes futures + 13 passées = 18 entrées,
// du futur vers le passé, pour le menu déroulant de sélection.
function buildPeriodOptions(currentEnd: string): string[] {
  const out: string[] = [];
  for (let i = 4; i >= -13; i--) {
    out.push(shiftPeriodEnd(currentEnd, i * 14));
  }
  return out;
}

function periodLabel(periodEnd: string): string {
  // « Paie 19 avr. → 02 mai » à partir de la fin de période ISO
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(periodEnd);
  if (!m) return periodEnd;
  const end = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
  const start = new Date(end);
  start.setDate(start.getDate() - 13);
  const fmt = (d: Date) =>
    d.toLocaleDateString("fr-CA", { day: "2-digit", month: "short" });
  return `Paie ${fmt(start)} → ${fmt(end)}`;
}

export default function PaiePage() {
  const { onOpenSidebar } = useAppLayout();
  const [report, setReport] = useState<Report | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [periodEnd, setPeriodEnd] = useState<string | null>(null);
  // Pas d'override par défaut → backend retourne la période courante / à venir

  const load = useCallback(async (override: string | null) => {
    setLoading(true);
    setError(null);
    try {
      const url = override
        ? `/api/v1/punch/payroll/bi-weekly?period_end=${override}`
        : "/api/v1/punch/payroll/bi-weekly";
      const res = await authedFetch(url);
      if (!res.ok) {
        const txt = await res.text().catch(() => "");
        throw new Error(`HTTP ${res.status} ${txt.slice(0, 120)}`);
      }
      setReport((await res.json()) as Report);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load(periodEnd);
  }, [load, periodEnd]);

  function downloadCsv() {
    if (!report) return;
    const url = `/api/v1/punch/payroll/bi-weekly.csv?period_end=${report.period_end}`;
    // Backend retourne le CSV avec Content-Disposition. authedFetch
    // ajoute le bearer token, donc on doit fetch puis créer un blob.
    (async () => {
      try {
        const res = await authedFetch(url);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const blob = await res.blob();
        const link = document.createElement("a");
        link.href = URL.createObjectURL(blob);
        link.download = `paie-${report.period_start}_au_${report.period_end}.csv`;
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
      } catch (err) {
        setError((err as Error).message);
      }
    })();
  }

  return (
    <>
      <AppTopbar
        breadcrumbs={[
          { label: "Construction", href: "/app" },
          { label: "Paie" }
        ]}
        onOpenSidebar={onOpenSidebar}
      />

      <div className="p-4 lg:p-6">
        <div className="flex flex-wrap items-baseline justify-between gap-3">
          <div>
            <h1 className="flex items-center gap-2 text-2xl font-bold text-white">
              <Wallet className="h-6 w-6 text-accent-500" />
              Paie bi-hebdomadaire
            </h1>
            <p className="mt-1 text-sm text-white/60">
              Périodes de 14 jours (samedi → vendredi). Versement le
              mercredi suivant. Coupure pour ajustements le lundi
              avant le versement.
            </p>
          </div>
          {report ? (
            <div className="flex flex-wrap items-center gap-2">
              <div className="flex items-center gap-1 rounded-lg border border-brand-800 bg-brand-900 p-1">
                <button
                  type="button"
                  onClick={() =>
                    setPeriodEnd(shiftPeriodEnd(report.period_end, -14))
                  }
                  className="rounded-md p-1.5 text-white/70 hover:bg-brand-800 hover:text-white"
                  title="Période précédente"
                >
                  <ChevronLeft className="h-4 w-4" />
                </button>
                {/* Menu déroulant : sélection directe d'une période de paie */}
                <select
                  value={report.period_end}
                  onChange={(e) => setPeriodEnd(e.target.value)}
                  className="min-w-[230px] cursor-pointer rounded-md bg-transparent px-2 text-center text-sm font-semibold text-white hover:bg-brand-800 focus:outline-none"
                  title="Choisir une période de paie"
                >
                  {buildPeriodOptions(report.period_end).map((opt) => (
                    <option
                      key={opt}
                      value={opt}
                      className="bg-brand-950 text-white"
                    >
                      {periodLabel(opt)}
                    </option>
                  ))}
                </select>
                <button
                  type="button"
                  onClick={() =>
                    setPeriodEnd(shiftPeriodEnd(report.period_end, 14))
                  }
                  className="rounded-md p-1.5 text-white/70 hover:bg-brand-800 hover:text-white"
                  title="Période suivante"
                >
                  <ChevronRight className="h-4 w-4" />
                </button>
              </div>
              <button
                type="button"
                onClick={() => setPeriodEnd(null)}
                className="btn-secondary text-xs"
                title="Période courante"
              >
                Aujourd&apos;hui
              </button>
              <button
                type="button"
                onClick={() => load(periodEnd)}
                className="rounded-md p-2 text-white/60 hover:bg-brand-800 hover:text-white"
                title="Rafraîchir"
              >
                <RefreshCw className="h-4 w-4" />
              </button>
            </div>
          ) : null}
        </div>

        {error ? (
          <p className="mt-4 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-300">
            {error}
          </p>
        ) : null}

        {loading ? (
          <div className="flex min-h-[40vh] items-center justify-center">
            <Loader2 className="h-6 w-6 animate-spin text-accent-500" />
          </div>
        ) : report ? (
          <div className="mt-6 space-y-6">
            {/* Encadré dates clés */}
            <div className="grid gap-3 sm:grid-cols-3">
              <KeyDateCard
                label="Période de paie"
                primary={`${fmtDateShort(report.period_start)} → ${fmtDateShort(report.period_end)}`}
                sub="14 jours · samedi → vendredi"
                tone="accent"
              />
              <KeyDateCard
                label="Coupure (ajustements)"
                primary={fmtDate(report.cutoff_date)}
                sub={
                  report.days_until_cutoff > 0
                    ? `Dans ${report.days_until_cutoff} jour${report.days_until_cutoff > 1 ? "s" : ""}`
                    : report.days_until_cutoff === 0
                      ? "Aujourd'hui — c'est ta dernière chance"
                      : `Coupure dépassée (il y a ${-report.days_until_cutoff} jour${-report.days_until_cutoff > 1 ? "s" : ""})`
                }
                tone={
                  report.days_until_cutoff < 0
                    ? "danger"
                    : report.days_until_cutoff <= 1
                      ? "warning"
                      : "default"
                }
              />
              <KeyDateCard
                label="Versement"
                primary={fmtDate(report.pay_date)}
                sub={
                  report.days_until_pay > 0
                    ? `Dans ${report.days_until_pay} jour${report.days_until_pay > 1 ? "s" : ""}`
                    : report.days_until_pay === 0
                      ? "Aujourd'hui"
                      : `Effectué (il y a ${-report.days_until_pay} jour${-report.days_until_pay > 1 ? "s" : ""})`
                }
                tone="default"
              />
            </div>

            {/* Alerte heures en attente */}
            {report.total_pending_hours > 0 ? (
              <div className="flex items-start gap-3 rounded-lg border border-amber-500/40 bg-amber-500/10 px-4 py-3 text-sm text-amber-200">
                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                <div>
                  <p className="font-semibold">
                    {report.total_pending_hours.toFixed(2)} h en attente
                    d&apos;approbation
                  </p>
                  <p className="mt-0.5 text-[12px] text-amber-300/80">
                    Va dans <span className="font-mono">/app/punch</span> pour
                    approuver les heures avant la coupure du{" "}
                    {fmtDate(report.cutoff_date)}.
                  </p>
                </div>
              </div>
            ) : null}

            {/* Tableau employés */}
            <div className="overflow-hidden rounded-xl border border-brand-800 bg-brand-900">
              <table className="w-full text-sm">
                <thead className="border-b border-brand-800 bg-brand-950/50 text-left text-[11px] uppercase tracking-wider text-white/50">
                  <tr>
                    <th className="px-3 py-2">Employé</th>
                    <th className="px-3 py-2 text-right">
                      Sem. 1
                      <span className="block text-[10px] font-normal normal-case text-white/40">
                        {fmtDateShort(report.period_start)} →{" "}
                        {fmtDateShort(report.week_1_end)}
                      </span>
                    </th>
                    <th className="px-3 py-2 text-right">
                      Sem. 2
                      <span className="block text-[10px] font-normal normal-case text-white/40">
                        {fmtDateShort(report.week_2_start)} →{" "}
                        {fmtDateShort(report.period_end)}
                      </span>
                    </th>
                    <th className="px-3 py-2 text-right">Total</th>
                    <th className="px-3 py-2 text-right">
                      <span className="text-amber-400">En attente</span>
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-brand-800">
                  {report.rows.length === 0 ? (
                    <tr>
                      <td
                        colSpan={5}
                        className="px-3 py-6 text-center text-xs text-white/50"
                      >
                        Aucune heure punchée pour cette période.
                      </td>
                    </tr>
                  ) : (
                    report.rows.map((r) => (
                      <tr key={r.employe_id} className="hover:bg-brand-800/30">
                        <td className="px-3 py-2 font-semibold text-white">
                          {r.employe_name}
                        </td>
                        <td className="px-3 py-2 text-right tabular-nums text-white/85">
                          {r.hours_week_1.toFixed(2)} h
                        </td>
                        <td className="px-3 py-2 text-right tabular-nums text-white/85">
                          {r.hours_week_2.toFixed(2)} h
                        </td>
                        <td className="px-3 py-2 text-right tabular-nums font-semibold text-white">
                          {r.total_hours.toFixed(2)} h
                        </td>
                        <td className="px-3 py-2 text-right tabular-nums">
                          {r.pending_hours > 0 ? (
                            <span className="text-amber-300">
                              {r.pending_hours.toFixed(2)} h
                            </span>
                          ) : (
                            <span className="text-white/30">—</span>
                          )}
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
                {report.rows.length > 0 ? (
                  <tfoot className="border-t-2 border-brand-800 bg-brand-950/40">
                    <tr>
                      <td className="px-3 py-2 text-[11px] uppercase tracking-wider text-white/60">
                        Totaux
                      </td>
                      <td className="px-3 py-2 text-right tabular-nums text-white/70">
                        {report.rows
                          .reduce((s, r) => s + r.hours_week_1, 0)
                          .toFixed(2)}{" "}
                        h
                      </td>
                      <td className="px-3 py-2 text-right tabular-nums text-white/70">
                        {report.rows
                          .reduce((s, r) => s + r.hours_week_2, 0)
                          .toFixed(2)}{" "}
                        h
                      </td>
                      <td className="px-3 py-2 text-right tabular-nums font-bold text-white">
                        {report.total_hours.toFixed(2)} h
                      </td>
                      <td className="px-3 py-2 text-right tabular-nums">
                        {report.total_pending_hours > 0 ? (
                          <span className="font-semibold text-amber-300">
                            {report.total_pending_hours.toFixed(2)} h
                          </span>
                        ) : (
                          <span className="text-white/30">—</span>
                        )}
                      </td>
                    </tr>
                  </tfoot>
                ) : null}
              </table>
            </div>

            {/* Bouton CSV */}
            <div className="flex flex-wrap items-center justify-between gap-3">
              <p className="text-[11px] text-white/50">
                Format CSV : <span className="font-mono">nom_employe</span>,{" "}
                <span className="font-mono">heures_semaine_1</span>,{" "}
                <span className="font-mono">heures_semaine_2</span> — prêt
                pour EmployeurD.
              </p>
              <button
                type="button"
                onClick={downloadCsv}
                disabled={report.rows.length === 0}
                className="btn-accent text-sm disabled:opacity-50"
              >
                <Download className="mr-2 h-4 w-4" />
                Télécharger CSV
              </button>
            </div>
          </div>
        ) : null}
      </div>
    </>
  );
}

function KeyDateCard({
  label,
  primary,
  sub,
  tone
}: {
  label: string;
  primary: string;
  sub: string;
  tone: "default" | "accent" | "warning" | "danger";
}) {
  const cls =
    tone === "accent"
      ? "border-accent-500/40 bg-accent-500/5"
      : tone === "warning"
        ? "border-amber-500/40 bg-amber-500/5"
        : tone === "danger"
          ? "border-rose-500/40 bg-rose-500/5"
          : "border-brand-800 bg-brand-900";
  const subCls =
    tone === "warning"
      ? "text-amber-300"
      : tone === "danger"
        ? "text-rose-300"
        : "text-white/50";
  return (
    <div className={`rounded-xl border p-4 ${cls}`}>
      <p className="text-[10px] uppercase tracking-wider text-white/50">
        {label}
      </p>
      <p className="mt-1 text-base font-bold text-white">{primary}</p>
      <p className={`mt-0.5 text-[11px] ${subCls}`}>{sub}</p>
    </div>
  );
}
