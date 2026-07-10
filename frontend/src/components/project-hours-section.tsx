"use client";

/**
 * Heures pointées sur le projet, PAR EMPLOYÉ (Construction).
 *
 * Demande du partner de Phil (2026-07-10) : suivre qui a punché combien
 * d'heures sur un projet. Rendu dans l'onglet « Récap & finances » de la
 * fiche projet. Chaque employé est dépliable pour voir le détail de ses
 * punchs (date, durée, tâche, approbation).
 * Backend : GET /api/v1/projects/{id}/punches-summary.
 */

import { useEffect, useState } from "react";
import { ChevronDown, ChevronRight, Clock, Loader2 } from "lucide-react";

import { authedFetch } from "@/lib/auth";

type PunchDetail = {
  id: number;
  started_at: string | null;
  ended_at: string | null;
  hours: number;
  task: string | null;
  approved: boolean;
};

type EmployeHours = {
  employe_id: number;
  full_name: string;
  total_hours: number;
  punch_count: number;
  approved_hours: number;
  pending_hours: number;
  last_punch_at: string | null;
  punches: PunchDetail[];
};

type Summary = {
  project_id: number;
  total_hours: number;
  employes: EmployeHours[];
};

function fmtH(n: number): string {
  return `${n.toLocaleString("fr-CA", {
    minimumFractionDigits: 0,
    maximumFractionDigits: 2
  })} h`;
}

function fmtDate(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("fr-CA", {
    day: "2-digit",
    month: "short",
    year: "numeric"
  });
}

export function ProjectHoursSection({ projectId }: { projectId: number }) {
  const [data, setData] = useState<Summary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<number | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await authedFetch(
          `/api/v1/projects/${projectId}/punches-summary`
        );
        if (!res.ok) throw new Error(`http_${res.status}`);
        if (!cancelled) setData((await res.json()) as Summary);
      } catch {
        if (!cancelled) setError("Chargement des heures échoué.");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  return (
    <div className="rounded-xl border border-brand-800 bg-brand-900 p-5">
      <div className="flex items-center justify-between">
        <h3 className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wider text-accent-500">
          <Clock className="h-4 w-4" /> Heures par employé
        </h3>
        {data ? (
          <span className="text-base font-bold text-white">
            {fmtH(data.total_hours)}
          </span>
        ) : null}
      </div>

      {loading ? (
        <div className="mt-4 flex items-center gap-2 text-xs text-white/50">
          <Loader2 className="h-3.5 w-3.5 animate-spin" /> Chargement…
        </div>
      ) : error ? (
        <p className="mt-3 text-xs text-rose-300">{error}</p>
      ) : !data || data.employes.length === 0 ? (
        <p className="mt-3 text-sm text-white/40">
          Aucune heure pointée sur ce projet pour l&apos;instant.
        </p>
      ) : (
        <div className="mt-4 divide-y divide-brand-800">
          {data.employes.map((e) => {
            const expanded = open === e.employe_id;
            return (
              <div key={e.employe_id}>
                <button
                  type="button"
                  onClick={() =>
                    setOpen(expanded ? null : e.employe_id)
                  }
                  className="flex w-full items-center justify-between gap-3 py-2.5 text-left transition hover:bg-brand-800/30"
                >
                  <span className="flex items-center gap-2 text-sm font-semibold text-white">
                    {expanded ? (
                      <ChevronDown className="h-3.5 w-3.5 text-white/40" />
                    ) : (
                      <ChevronRight className="h-3.5 w-3.5 text-white/40" />
                    )}
                    {e.full_name}
                  </span>
                  <span className="flex items-center gap-3 text-xs">
                    {e.pending_hours > 0 ? (
                      <span className="badge badge-amber">
                        {fmtH(e.pending_hours)} à approuver
                      </span>
                    ) : (
                      <span className="badge badge-emerald">Approuvé</span>
                    )}
                    <span className="text-white/50">
                      {e.punch_count} punch{e.punch_count > 1 ? "s" : ""}
                    </span>
                    <span className="w-16 text-right font-mono text-sm font-bold text-white">
                      {fmtH(e.total_hours)}
                    </span>
                  </span>
                </button>
                {expanded ? (
                  <div className="mb-2 overflow-x-auto rounded-lg border border-brand-800 bg-brand-950/60">
                    <table className="w-full text-xs">
                      <thead>
                        <tr className="border-b border-brand-800 text-left text-[10px] uppercase tracking-wider text-white/40">
                          <th className="px-3 py-1.5">Date</th>
                          <th className="px-3 py-1.5">Tâche</th>
                          <th className="px-3 py-1.5 text-right">Heures</th>
                          <th className="px-3 py-1.5">Statut</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-brand-800/60">
                        {e.punches.map((p) => (
                          <tr key={p.id}>
                            <td className="px-3 py-1.5 text-white/70">
                              {fmtDate(p.started_at)}
                            </td>
                            <td className="max-w-[220px] truncate px-3 py-1.5 text-white/70">
                              {p.task || "—"}
                            </td>
                            <td className="px-3 py-1.5 text-right font-mono text-white">
                              {fmtH(p.hours)}
                            </td>
                            <td className="px-3 py-1.5">
                              {p.approved ? (
                                <span className="text-emerald-300">
                                  Approuvé
                                </span>
                              ) : (
                                <span className="text-amber-300">
                                  En attente
                                </span>
                              )}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : null}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
