"use client";

import { useEffect, useMemo, useState } from "react";
import { CheckSquare, Loader2, Square } from "lucide-react";

import { authedFetch } from "@/lib/auth";

type Task = {
  id: number;
  project_id: number;
  project_name: string | null;
  phase_id: number | null;
  phase_name: string | null;
  title: string;
  description: string | null;
  due_date: string | null;
  done: boolean;
  done_at: string | null;
};

function fmtDate(s: string | null): string {
  if (!s) return "";
  try {
    return new Date(s).toLocaleDateString("fr-CA", {
      day: "2-digit",
      month: "short"
    });
  } catch {
    return s;
  }
}

function isOverdue(due: string | null): boolean {
  if (!due) return false;
  const d = new Date(due);
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  return d < today;
}

export default function MobileTaches() {
  const [items, setItems] = useState<Task[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showDone, setShowDone] = useState(false);
  const [toggling, setToggling] = useState<Set<number>>(new Set());

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      try {
        const url = `/api/v1/mobile/tasks?include_done=${showDone}`;
        const res = await authedFetch(url);
        if (!res.ok) throw new Error();
        if (!cancelled) setItems((await res.json()) as Task[]);
      } catch {
        if (!cancelled) setError("Chargement échoué.");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, [showDone]);

  async function toggle(task: Task) {
    setToggling((prev) => new Set(prev).add(task.id));
    try {
      const res = await authedFetch(
        `/api/v1/mobile/tasks/${task.id}/toggle`,
        { method: "POST" }
      );
      if (!res.ok) throw new Error();
      const updated = (await res.json()) as Task;
      setItems((prev) => {
        if (!showDone && updated.done) {
          return prev.filter((t) => t.id !== updated.id);
        }
        return prev.map((t) =>
          t.id === updated.id
            ? { ...t, done: updated.done, done_at: updated.done_at }
            : t
        );
      });
    } catch {
      setError("Impossible de mettre à jour la tâche.");
    } finally {
      setToggling((prev) => {
        const next = new Set(prev);
        next.delete(task.id);
        return next;
      });
    }
  }

  const groups = useMemo(() => {
    const by = new Map<number, { name: string; tasks: Task[] }>();
    for (const t of items) {
      const key = t.project_id;
      if (!by.has(key)) {
        by.set(key, { name: t.project_name || `Projet #${key}`, tasks: [] });
      }
      by.get(key)!.tasks.push(t);
    }
    return Array.from(by.entries()).map(([project_id, v]) => ({
      project_id,
      name: v.name,
      tasks: v.tasks
    }));
  }, [items]);

  return (
    <>
      <header
        className="sticky top-0 z-30 border-b border-brand-800 bg-brand-950/95 px-4 py-3 backdrop-blur"
        style={{ paddingTop: "max(env(safe-area-inset-top), 0.75rem)" }}
      >
        <h1 className="text-base font-bold text-white">Mes tâches</h1>
        <p className="mt-0.5 text-[11px] text-white/50">
          Tâches assignées à toi.
        </p>
        <label className="mt-3 flex items-center gap-2 text-xs text-white/70">
          <input
            type="checkbox"
            checked={showDone}
            onChange={(e) => setShowDone(e.target.checked)}
            className="h-4 w-4 rounded border-brand-700 bg-brand-900 text-accent-500 focus:ring-accent-500"
          />
          Afficher les tâches terminées
        </label>
      </header>

      <div className="p-4">
        {error ? (
          <p className="mb-3 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
            {error}
          </p>
        ) : null}

        {loading ? (
          <div className="flex items-center justify-center py-10">
            <Loader2 className="h-5 w-5 animate-spin text-white/40" />
          </div>
        ) : groups.length === 0 ? (
          <div className="rounded-2xl border border-dashed border-brand-800 bg-brand-900/40 px-6 py-10 text-center">
            <CheckSquare className="mx-auto h-8 w-8 text-white/30" />
            <p className="mt-3 text-sm text-white/60">
              {showDone
                ? "Aucune tâche pour l’instant."
                : "Aucune tâche en cours. 🎉"}
            </p>
          </div>
        ) : (
          <div className="space-y-5">
            {groups.map((g) => (
              <section key={g.project_id}>
                <h2 className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-white/40">
                  {g.name}
                </h2>
                <ul className="space-y-2">
                  {g.tasks.map((t) => {
                    const busy = toggling.has(t.id);
                    const overdue = !t.done && isOverdue(t.due_date);
                    return (
                      <li
                        key={t.id}
                        className={`flex items-start gap-3 rounded-xl border px-3 py-3 ${
                          t.done
                            ? "border-brand-800 bg-brand-900/50"
                            : "border-brand-800 bg-brand-900"
                        }`}
                      >
                        <button
                          type="button"
                          onClick={() => toggle(t)}
                          disabled={busy}
                          className="mt-0.5 shrink-0 text-accent-500 disabled:opacity-50"
                          aria-label={
                            t.done ? "Marquer à faire" : "Marquer terminée"
                          }
                        >
                          {busy ? (
                            <Loader2 className="h-5 w-5 animate-spin" />
                          ) : t.done ? (
                            <CheckSquare className="h-5 w-5" />
                          ) : (
                            <Square className="h-5 w-5 text-white/40" />
                          )}
                        </button>
                        <div className="min-w-0 flex-1">
                          <p
                            className={`text-sm ${
                              t.done
                                ? "text-white/40 line-through"
                                : "text-white"
                            }`}
                          >
                            {t.title}
                          </p>
                          {t.description ? (
                            <p className="mt-0.5 whitespace-pre-wrap text-xs text-white/60">
                              {t.description}
                            </p>
                          ) : null}
                          <div className="mt-1 flex flex-wrap items-center gap-2 text-[11px]">
                            {t.phase_name ? (
                              <span className="rounded-full border border-brand-700 bg-brand-900 px-2 py-0.5 text-white/60">
                                {t.phase_name}
                              </span>
                            ) : null}
                            {t.due_date ? (
                              <span
                                className={
                                  overdue
                                    ? "rounded-full border border-rose-500/40 bg-rose-500/10 px-2 py-0.5 text-rose-300"
                                    : "rounded-full border border-brand-700 bg-brand-900 px-2 py-0.5 text-white/60"
                                }
                              >
                                {overdue ? "En retard · " : "Échéance "}
                                {fmtDate(t.due_date)}
                              </span>
                            ) : null}
                          </div>
                        </div>
                      </li>
                    );
                  })}
                </ul>
              </section>
            ))}
          </div>
        )}
      </div>
    </>
  );
}
