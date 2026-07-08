"use client";

// Vue d'ensemble des Insights IA — toutes entreprises confondues.
// Le copilote « qui agit » : affiche ce que l'IA a détecté (risques /
// opportunités) et permet de transformer une action suggérée en tâche
// d'entreprise réelle d'un clic (l'insight passe alors « in_action »).

import { useEffect, useState } from "react";
import { Loader2, Plus, Sparkles, Check } from "lucide-react";

import { authedFetch } from "@/lib/auth";

type Insight = {
  id: number;
  entreprise_id: number;
  type: string;
  status: string;
  title: string;
  body: string;
  confidence: number | null;
  suggested_actions: string[];
  estimated_impact_label: string | null;
  created_at: string;
};

export function InsightsOverviewCard() {
  const [insights, setInsights] = useState<Insight[]>([]);
  const [loading, setLoading] = useState(true);
  // id d'insight en cours de création de tâche (pour le spinner local)
  const [busyId, setBusyId] = useState<number | null>(null);
  // insights pour lesquels une tâche vient d'être créée (feedback)
  const [doneIds, setDoneIds] = useState<Set<number>>(new Set());

  async function load() {
    setLoading(true);
    try {
      const res = await authedFetch("/api/v1/entreprises/insights");
      if (res.ok) {
        setInsights((await res.json()) as Insight[]);
      }
    } catch {
      /* silent */
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
  }, []);

  async function createTask(insightId: number, title: string) {
    setBusyId(insightId);
    try {
      const res = await authedFetch(
        `/api/v1/entreprises/insights/${insightId}/create-task`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ title })
        }
      );
      if (res.ok) {
        setDoneIds((prev) => new Set(prev).add(insightId));
      }
    } catch {
      /* silent */
    } finally {
      setBusyId(null);
    }
  }

  return (
    <section
      className="mt-8 rounded-xl"
      style={{
        backgroundColor: "var(--qg-card-bg)",
        border: "1px solid var(--qg-border)"
      }}
    >
      <div className="flex items-center justify-between px-5 pt-5">
        <h2
          className="text-[18px] font-bold text-[var(--qg-text)]"
          style={{ fontFamily: "var(--font-display, ui-sans-serif, system-ui, sans-serif)" }}
        >
          Insights{" "}
          <span className="italic" style={{ color: "var(--qg-accent)" }}>
            IA
          </span>
        </h2>
        <span
          className="inline-flex items-center gap-1 text-[10px] uppercase tracking-wider text-[var(--qg-text-soft)]"
        >
          <Sparkles className="h-3 w-3" style={{ color: "var(--qg-accent)" }} />
          Toutes entreprises
        </span>
      </div>

      <div className="px-5 pb-5 pt-3">
        {loading ? (
          <div className="flex min-h-[80px] items-center justify-center">
            <Loader2 className="h-5 w-5 animate-spin text-[var(--qg-accent)]" />
          </div>
        ) : insights.length === 0 ? (
          <div className="rounded-md border border-dashed border-[var(--qg-border)] p-4 text-center text-[12px] text-[var(--qg-text-soft)]">
            Aucun insight ouvert. L&apos;IA n&apos;a rien à signaler pour
            l&apos;instant.
          </div>
        ) : (
          <ul className="space-y-3">
            {insights.map((ins) => (
              <li
                key={ins.id}
                className="rounded-md p-3"
                style={{
                  backgroundColor: "var(--qg-bg-alt)",
                  border: "1px solid var(--qg-border-soft)"
                }}
              >
                <p className="text-[13px] font-semibold text-[var(--qg-text)]">
                  {ins.title}
                </p>
                {ins.body ? (
                  <p className="mt-1 text-[12px] leading-relaxed text-[var(--qg-text-muted)]">
                    {ins.body}
                  </p>
                ) : null}

                {ins.suggested_actions.length > 0 ? (
                  <div className="mt-2.5 flex flex-wrap gap-2">
                    {ins.suggested_actions.map((action, i) => (
                      <button
                        key={i}
                        type="button"
                        disabled={busyId === ins.id || doneIds.has(ins.id)}
                        onClick={() => void createTask(ins.id, action)}
                        className="inline-flex items-center gap-1 rounded-md border border-[var(--qg-accent)]/40 bg-[var(--qg-accent)]/10 px-2 py-1 text-[11px] font-semibold text-[var(--qg-accent)] transition hover:bg-[var(--qg-accent)]/20 disabled:opacity-50"
                        title="Créer une tâche d'entreprise à partir de cette action"
                      >
                        {doneIds.has(ins.id) ? (
                          <Check className="h-3 w-3" />
                        ) : busyId === ins.id ? (
                          <Loader2 className="h-3 w-3 animate-spin" />
                        ) : (
                          <Plus className="h-3 w-3" />
                        )}
                        {action}
                      </button>
                    ))}
                  </div>
                ) : null}

                {doneIds.has(ins.id) ? (
                  <p className="mt-2 text-[10px] font-semibold uppercase tracking-wider text-[var(--qg-accent)]">
                    Tâche créée ✓
                  </p>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}
