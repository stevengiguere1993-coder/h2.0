"use client";

import { useEffect, useState } from "react";
import { Calculator, Loader2, Plus, Trash2 } from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { useConfirm } from "@/components/confirm-dialog";
import { Link } from "@/i18n/navigation";
import { authedFetch } from "@/lib/auth";
import { useProspectionLayout } from "../layout";

type AnalyseSummary = {
  id: number;
  lead_id: number | null;
  name: string;
  created_at: string;
  updated_at: string;
  prix_achat: number | null;
  nombre_logements: number | null;
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
    year: "numeric",
    month: "short",
    day: "numeric"
  });
}

export default function AnalysesListPage() {
  const { onOpenSidebar } = useProspectionLayout();
  const confirm = useConfirm();
  const [analyses, setAnalyses] = useState<AnalyseSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const res = await authedFetch("/api/v1/prospection/analyses");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setAnalyses(await res.json());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erreur de chargement");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
  }, []);

  async function handleDelete(a: AnalyseSummary) {
    const ok = await confirm({
      title: "Supprimer cette analyse ?",
      description: `« ${a.name} » sera supprimée définitivement.`,
      confirmLabel: "Supprimer",
      destructive: true
    });
    if (!ok) return;
    const res = await authedFetch(`/api/v1/prospection/analyses/${a.id}`, {
      method: "DELETE"
    });
    if (res.ok) {
      setAnalyses((prev) => prev.filter((x) => x.id !== a.id));
    }
  }

  return (
    <>
      <AppTopbar
        breadcrumbs={[
          { label: "Prospection", href: "/prospection" },
          { label: "Analyses financières" }
        ]}
        onOpenSidebar={onOpenSidebar}
        rightSlot={
          <Link
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            href={"/prospection/analyse/nouveau" as any}
            className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-500 px-3 py-1.5 text-sm font-semibold text-brand-950 hover:bg-emerald-400"
          >
            <Plus className="h-4 w-4" /> Nouvelle analyse
          </Link>
        }
      />

      <div className="px-4 py-6 lg:px-6">
        <div className="mb-4 flex items-center gap-2 text-white">
          <Calculator className="h-5 w-5 text-emerald-400" />
          <h1 className="text-xl font-bold">Analyses financières</h1>
          <span className="ml-2 rounded-full bg-emerald-500/10 px-2 py-0.5 text-xs text-emerald-300">
            {analyses.length}
          </span>
        </div>

        <p className="mb-4 max-w-2xl text-sm text-white/60">
          Calculateur multi-logements (Québec) : Achat conventionnel,
          Refinancement SCHL et APH 50. Compare la mise de fonds requise
          au gain d&apos;equity créé par les 3 stratégies.
        </p>

        {loading ? (
          <div className="flex items-center gap-2 text-sm text-white/50">
            <Loader2 className="h-4 w-4 animate-spin" /> Chargement…
          </div>
        ) : error ? (
          <div className="rounded-lg border border-red-500/40 bg-red-500/10 p-4 text-sm text-red-300">
            {error}
          </div>
        ) : analyses.length === 0 ? (
          <div className="rounded-xl border border-dashed border-brand-800 bg-brand-900/40 p-10 text-center">
            <Calculator className="mx-auto h-10 w-10 text-emerald-400/60" />
            <h2 className="mt-3 text-base font-semibold text-white">
              Aucune analyse pour l&apos;instant
            </h2>
            <p className="mt-1 text-sm text-white/60">
              Lance ta première analyse financière pour comparer les
              scénarios d&apos;acquisition.
            </p>
            <Link
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
              href={"/prospection/analyse/nouveau" as any}
              className="mt-4 inline-flex items-center gap-1.5 rounded-lg bg-emerald-500 px-3 py-2 text-sm font-semibold text-brand-950 hover:bg-emerald-400"
            >
              <Plus className="h-4 w-4" /> Nouvelle analyse
            </Link>
          </div>
        ) : (
          <div className="overflow-hidden rounded-xl border border-brand-800">
            <table className="min-w-full divide-y divide-brand-800 text-sm">
              <thead className="bg-brand-900/60 text-left text-xs uppercase tracking-wider text-white/50">
                <tr>
                  <th className="px-4 py-3">Nom</th>
                  <th className="px-4 py-3 text-right">Prix</th>
                  <th className="px-4 py-3 text-right">Logements</th>
                  <th className="px-4 py-3 text-right">MDF achat</th>
                  <th className="px-4 py-3 text-right">Gain SCHL</th>
                  <th className="px-4 py-3 text-right">Gain APH50</th>
                  <th className="px-4 py-3">Créée</th>
                  <th className="px-4 py-3" />
                </tr>
              </thead>
              <tbody className="divide-y divide-brand-800/60 bg-brand-950">
                {analyses.map((a) => (
                  <tr key={a.id} className="hover:bg-brand-900/50">
                    <td className="px-4 py-3">
                      <Link
                        // eslint-disable-next-line @typescript-eslint/no-explicit-any
                        href={`/prospection/analyse/${a.id}` as any}
                        className="font-medium text-emerald-300 hover:text-emerald-200"
                      >
                        {a.name}
                      </Link>
                    </td>
                    <td className="px-4 py-3 text-right tabular-nums text-white/80">
                      {fmt$(a.prix_achat)}
                    </td>
                    <td className="px-4 py-3 text-right tabular-nums text-white/80">
                      {a.nombre_logements ?? "—"}
                    </td>
                    <td className="px-4 py-3 text-right tabular-nums text-white/80">
                      {fmt$(a.achat_mise_de_fonds)}
                    </td>
                    <td
                      className={`px-4 py-3 text-right tabular-nums ${
                        (a.schl_gain_actionnaires ?? 0) >= 0
                          ? "text-emerald-300"
                          : "text-red-300"
                      }`}
                    >
                      {fmt$(a.schl_gain_actionnaires)}
                    </td>
                    <td
                      className={`px-4 py-3 text-right tabular-nums ${
                        (a.aph50_gain_actionnaires ?? 0) >= 0
                          ? "text-emerald-300"
                          : "text-red-300"
                      }`}
                    >
                      {fmt$(a.aph50_gain_actionnaires)}
                    </td>
                    <td className="px-4 py-3 text-white/60">
                      {fmtDate(a.created_at)}
                    </td>
                    <td className="px-4 py-3 text-right">
                      <button
                        type="button"
                        onClick={() => handleDelete(a)}
                        className="rounded-md p-1.5 text-white/40 hover:bg-red-500/10 hover:text-red-300"
                        aria-label="Supprimer"
                      >
                        <Trash2 className="h-4 w-4" />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </>
  );
}
