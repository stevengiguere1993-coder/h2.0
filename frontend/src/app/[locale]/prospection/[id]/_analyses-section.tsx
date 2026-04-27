"use client";

import { useEffect, useState } from "react";
import { Calculator, Loader2, Plus } from "lucide-react";

import { Link } from "@/i18n/navigation";
import { authedFetch } from "@/lib/auth";

type AnalyseSummary = {
  id: number;
  lead_id: number | null;
  name: string;
  created_at: string;
  prix_achat: number | null;
  achat_mise_de_fonds: number | null;
  schl_gain_actionnaires: number | null;
  aph50_gain_actionnaires: number | null;
};

function fmt$(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  return n.toLocaleString("fr-CA", {
    style: "currency",
    currency: "CAD",
    maximumFractionDigits: 0
  });
}

function fmtDate(iso: string): string {
  return new Date(iso).toLocaleDateString("fr-CA", {
    day: "numeric",
    month: "short",
    year: "numeric"
  });
}

export function AnalysesSection({ leadId }: { leadId: number }) {
  const [analyses, setAnalyses] = useState<AnalyseSummary[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancel = false;
    void (async () => {
      setLoading(true);
      try {
        const res = await authedFetch(
          `/api/v1/prospection/analyses?lead_id=${leadId}`
        );
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = (await res.json()) as AnalyseSummary[];
        if (!cancel) setAnalyses(data);
      } catch {
        if (!cancel) setAnalyses([]);
      } finally {
        if (!cancel) setLoading(false);
      }
    })();
    return () => {
      cancel = true;
    };
  }, [leadId]);

  return (
    <section className="rounded-xl border border-brand-800 bg-brand-900 p-5">
      <div className="flex items-center justify-between gap-2">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-accent-500">
          Analyses financières
        </h2>
        <Link
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          href={`/prospection/analyse/nouveau?lead_id=${leadId}` as any}
          className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-500 px-2.5 py-1 text-xs font-semibold text-brand-950 hover:bg-emerald-400"
        >
          <Plus className="h-3.5 w-3.5" /> Nouvelle
        </Link>
      </div>

      {loading ? (
        <div className="mt-3 flex items-center gap-2 text-sm text-white/50">
          <Loader2 className="h-4 w-4 animate-spin" /> Chargement…
        </div>
      ) : analyses.length === 0 ? (
        <p className="mt-3 text-sm text-white/50">
          Aucune analyse pour ce lead. Lance une simulation pour
          comparer Achat / SCHL / APH 50.
        </p>
      ) : (
        <ul className="mt-3 space-y-2">
          {analyses.map((a) => (
            <li key={a.id}>
              <Link
                // eslint-disable-next-line @typescript-eslint/no-explicit-any
                href={`/prospection/analyse/${a.id}` as any}
                className="flex flex-wrap items-center gap-3 rounded-lg border border-brand-800 bg-brand-950 px-3 py-2 text-sm hover:border-emerald-700/60 hover:bg-brand-900"
              >
                <Calculator className="h-4 w-4 text-emerald-400" />
                <span className="flex-1 truncate text-white">{a.name}</span>
                <span className="text-xs text-white/50">
                  {fmtDate(a.created_at)}
                </span>
                <span className="hidden tabular-nums text-white/70 sm:inline">
                  Prix {fmt$(a.prix_achat)}
                </span>
                <span className="hidden tabular-nums text-white/70 md:inline">
                  MDF {fmt$(a.achat_mise_de_fonds)}
                </span>
                <span
                  className={`hidden tabular-nums md:inline ${
                    (a.aph50_gain_actionnaires ?? 0) >= 0
                      ? "text-emerald-300"
                      : "text-red-300"
                  }`}
                >
                  APH50 {fmt$(a.aph50_gain_actionnaires)}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
