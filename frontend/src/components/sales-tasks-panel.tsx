"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  BellRing,
  CalendarCheck2,
  CheckSquare,
  Loader2,
  Plus,
  ShoppingBag,
  Square,
  Trash2
} from "lucide-react";

import { authedFetch } from "@/lib/auth";
import { useConfirm } from "@/components/confirm-dialog";

type TaskKind = "suivi" | "commander_materiel" | "rappel_rdv" | "autre";
type Recurrence = "none" | "daily" | "weekly" | "monthly";

export type SalesTask = {
  id: number;
  kind: TaskKind;
  title: string;
  notes: string | null;
  color: string | null;
  contact_request_id: number | null;
  client_id: number | null;
  due_date: string;
  all_day: boolean;
  due_time: string | null;
  recurrence: Recurrence;
  done: boolean;
  done_at: string | null;
  created_at: string;
  assignee_ids: number[];
};

type Employe = { id: number; name: string; avatar_url?: string | null };

const KIND_LABELS: Record<TaskKind, string> = {
  suivi: "Suivi",
  commander_materiel: "Commander matériel",
  rappel_rdv: "Rappel rendez-vous",
  autre: "Autre"
};

const KIND_ICONS: Record<
  TaskKind,
  React.ComponentType<{ className?: string }>
> = {
  suivi: CalendarCheck2,
  commander_materiel: ShoppingBag,
  rappel_rdv: BellRing,
  autre: Square
};

const COLORS = [
  "#3b82f6", // blue
  "#a855f7", // purple
  "#22c55e", // green
  "#84cc16", // lime
  "#f59e0b", // amber
  "#ef4444", // red
  "#0ea5e9", // sky
  "#64748b" // slate
];

function today(): string {
  const d = new Date();
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

export function SalesTasksPanel({
  clientId,
  contactRequestId
}: {
  clientId?: number | null;
  contactRequestId?: number | null;
}) {
  const confirm = useConfirm();
  const [tasks, setTasks] = useState<SalesTask[]>([]);
  const [employes, setEmployes] = useState<Employe[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [modalOpen, setModalOpen] = useState(false);

  const scopeQS = useMemo(() => {
    const p = new URLSearchParams();
    if (clientId) p.set("client_id", String(clientId));
    if (contactRequestId)
      p.set("contact_request_id", String(contactRequestId));
    return p.toString();
  }, [clientId, contactRequestId]);

  const load = useCallback(async () => {
    if (!clientId && !contactRequestId) return;
    setLoading(true);
    setError(null);
    try {
      const [tRes, eRes] = await Promise.all([
        authedFetch(`/api/v1/sales-tasks?${scopeQS}`),
        authedFetch(`/api/v1/employes?limit=200`)
      ]);
      if (!tRes.ok) throw new Error(`http_${tRes.status}`);
      setTasks((await tRes.json()) as SalesTask[]);
      if (eRes.ok) setEmployes((await eRes.json()) as Employe[]);
    } catch {
      setError("Chargement des tâches échoué.");
    } finally {
      setLoading(false);
    }
  }, [clientId, contactRequestId, scopeQS]);

  useEffect(() => {
    void load();
  }, [load]);

  async function toggleDone(task: SalesTask) {
    const next = !task.done;
    setTasks((xs) =>
      xs.map((x) => (x.id === task.id ? { ...x, done: next } : x))
    );
    try {
      await authedFetch(`/api/v1/sales-tasks/${task.id}`, {
        method: "PATCH",
        body: JSON.stringify({ done: next })
      });
    } catch {
      setTasks((xs) =>
        xs.map((x) => (x.id === task.id ? { ...x, done: task.done } : x))
      );
    }
  }

  async function remove(id: number) {
    if (!(await confirm("Supprimer cette tâche ?"))) return;
    try {
      await authedFetch(`/api/v1/sales-tasks/${id}`, { method: "DELETE" });
      setTasks((xs) => xs.filter((x) => x.id !== id));
    } catch {
      setError("Suppression échouée.");
    }
  }

  return (
    <section className="rounded-xl border border-brand-800 bg-brand-900 p-5">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-accent-500">
          Tâches
        </h2>
        <button
          type="button"
          onClick={() => setModalOpen(true)}
          className="btn-accent text-xs"
        >
          <Plus className="mr-1.5 h-3.5 w-3.5" /> Ajouter une tâche
        </button>
      </div>

      {error ? (
        <p className="mt-3 text-sm text-rose-300">{error}</p>
      ) : null}

      <div className="mt-4">
        {loading ? (
          <div className="flex items-center justify-center py-6">
            <Loader2 className="h-5 w-5 animate-spin text-white/40" />
          </div>
        ) : tasks.length === 0 ? (
          <p className="rounded-lg border border-dashed border-brand-800 bg-brand-950/40 px-4 py-6 text-center text-xs text-white/50">
            Aucune tâche.
          </p>
        ) : (
          <ul className="space-y-2">
            {tasks.map((t) => {
              const Icon = KIND_ICONS[t.kind] || Square;
              const assignees = employes.filter((e) =>
                t.assignee_ids.includes(e.id)
              );
              return (
                <li
                  key={t.id}
                  className="flex items-start gap-3 rounded-lg border border-brand-800 bg-brand-950 p-3"
                  style={{
                    borderLeftColor: t.color || "#3b82f6",
                    borderLeftWidth: "3px"
                  }}
                >
                  <button
                    type="button"
                    onClick={() => toggleDone(t)}
                    className="mt-0.5 text-white/60 hover:text-accent-500"
                    aria-label={t.done ? "Marquer à faire" : "Marquer fait"}
                  >
                    {t.done ? (
                      <CheckSquare className="h-4 w-4 text-emerald-400" />
                    ) : (
                      <Square className="h-4 w-4" />
                    )}
                  </button>
                  <div className="flex-1 min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <Icon className="h-3.5 w-3.5 text-white/60" />
                      <p
                        className={`text-sm font-semibold ${
                          t.done ? "text-white/40 line-through" : "text-white"
                        }`}
                      >
                        {t.title}
                      </p>
                      <span className="rounded bg-white/5 px-1.5 py-0.5 text-[10px] uppercase text-white/50">
                        {KIND_LABELS[t.kind] || t.kind}
                      </span>
                      {t.recurrence !== "none" ? (
                        <span className="rounded bg-accent-500/10 px-1.5 py-0.5 text-[10px] uppercase text-accent-400">
                          ↻ {t.recurrence}
                        </span>
                      ) : null}
                    </div>
                    <p className="mt-1 text-xs text-white/50">
                      {t.due_date}
                      {!t.all_day && t.due_time ? ` · ${t.due_time}` : ""}
                    </p>
                    {assignees.length > 0 ? (
                      <div className="mt-1 flex flex-wrap gap-1">
                        {assignees.map((a) => (
                          <span
                            key={a.id}
                            className="inline-flex items-center gap-1 rounded-full bg-white/5 px-2 py-0.5 text-[10px] text-white/70"
                          >
                            {a.name}
                          </span>
                        ))}
                      </div>
                    ) : null}
                    {t.notes ? (
                      <p className="mt-1 text-xs text-white/50">
                        {t.notes}
                      </p>
                    ) : null}
                  </div>
                  <button
                    type="button"
                    onClick={() => remove(t.id)}
                    className="rounded-md p-1 text-white/40 hover:bg-rose-500/10 hover:text-rose-300"
                    aria-label="Supprimer"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </div>

      {modalOpen ? (
        <CreateTaskModal
          employes={employes}
          clientId={clientId}
          contactRequestId={contactRequestId}
          onClose={() => setModalOpen(false)}
          onCreated={(t) => {
            setTasks((xs) => [...xs, t]);
            setModalOpen(false);
          }}
        />
      ) : null}
    </section>
  );
}

function CreateTaskModal({
  employes,
  clientId,
  contactRequestId,
  onClose,
  onCreated
}: {
  employes: Employe[];
  clientId?: number | null;
  contactRequestId?: number | null;
  onClose: () => void;
  onCreated: (t: SalesTask) => void;
}) {
  const [kind, setKind] = useState<TaskKind>("suivi");
  const [title, setTitle] = useState("");
  const [notes, setNotes] = useState("");
  const [color, setColor] = useState<string | null>(null);
  const [dueDate, setDueDate] = useState(today());
  const [allDay, setAllDay] = useState(true);
  const [dueTime, setDueTime] = useState("09:00");
  const [recurrence, setRecurrence] = useState<Recurrence>("none");
  const [assignees, setAssignees] = useState<number[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit() {
    if (!title.trim()) {
      setError("Titre requis.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const res = await authedFetch("/api/v1/sales-tasks", {
        method: "POST",
        body: JSON.stringify({
          kind,
          title: title.trim(),
          notes: notes.trim() || null,
          color,
          client_id: clientId || null,
          contact_request_id: contactRequestId || null,
          due_date: dueDate,
          all_day: allDay,
          due_time: allDay ? null : dueTime,
          recurrence,
          assignee_ids: assignees
        })
      });
      if (!res.ok) {
        const txt = await res.text();
        throw new Error(txt.slice(0, 240) || `http_${res.status}`);
      }
      const created = (await res.json()) as SalesTask;
      onCreated(created);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4"
      onClick={() => (!busy ? onClose() : null)}
    >
      <div
        className="max-h-[90vh] w-full max-w-lg overflow-y-auto rounded-2xl border border-brand-800 bg-brand-950 p-6"
        onClick={(e) => e.stopPropagation()}
      >
        <h3 className="text-lg font-bold text-white">Créer une tâche</h3>
        <div className="mt-5 space-y-4">
          <div>
            <label className="label">Type</label>
            <select
              value={kind}
              onChange={(e) => setKind(e.target.value as TaskKind)}
              className="input"
            >
              {(
                [
                  "suivi",
                  "commander_materiel",
                  "rappel_rdv",
                  "autre"
                ] as TaskKind[]
              ).map((k) => (
                <option key={k} value={k}>
                  {KIND_LABELS[k]}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label className="label">Titre *</label>
            <input
              type="text"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              className="input"
              autoFocus
              placeholder="Ex. Rappeler Jean pour confirmation"
            />
          </div>

          <div>
            <label className="label">Couleur</label>
            <div className="mt-2 flex flex-wrap gap-2">
              <button
                type="button"
                onClick={() => setColor(null)}
                className={`rounded-md border px-2 py-1 text-xs ${
                  color === null
                    ? "border-accent-500 bg-accent-500/10 text-white"
                    : "border-brand-800 text-white/60"
                }`}
              >
                Auto
              </button>
              {COLORS.map((c) => (
                <button
                  key={c}
                  type="button"
                  onClick={() => setColor(c)}
                  className={`h-7 w-7 rounded-md border-2 ${
                    color === c ? "border-white" : "border-transparent"
                  }`}
                  style={{ backgroundColor: c }}
                  aria-label={`Couleur ${c}`}
                />
              ))}
            </div>
          </div>

          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <label className="label">Date</label>
              <input
                type="date"
                value={dueDate}
                onChange={(e) => setDueDate(e.target.value)}
                className="input"
              />
            </div>
            <div>
              <label className="label">Récurrence</label>
              <select
                value={recurrence}
                onChange={(e) => setRecurrence(e.target.value as Recurrence)}
                className="input"
              >
                <option value="none">Aucune</option>
                <option value="daily">Quotidien</option>
                <option value="weekly">Hebdomadaire</option>
                <option value="monthly">Mensuel</option>
              </select>
            </div>
          </div>

          <div>
            <label className="inline-flex cursor-pointer items-center gap-2 text-sm text-white/80">
              <input
                type="checkbox"
                checked={allDay}
                onChange={(e) => setAllDay(e.target.checked)}
                className="h-4 w-4 accent-accent-500"
              />
              Journée complète
            </label>
            {!allDay ? (
              <div className="mt-2">
                <label className="label">Heure</label>
                <input
                  type="time"
                  value={dueTime}
                  onChange={(e) => setDueTime(e.target.value)}
                  className="input sm:w-40"
                />
              </div>
            ) : null}
          </div>

          <div>
            <label className="label">Assigné à</label>
            <div className="mt-2 flex flex-wrap gap-2">
              {employes.length === 0 ? (
                <p className="text-xs text-white/50">
                  Aucun employé enregistré.
                </p>
              ) : (
                employes.map((e) => {
                  const selected = assignees.includes(e.id);
                  return (
                    <button
                      key={e.id}
                      type="button"
                      onClick={() =>
                        setAssignees((xs) =>
                          selected ? xs.filter((x) => x !== e.id) : [...xs, e.id]
                        )
                      }
                      className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs ${
                        selected
                          ? "border-accent-500 bg-accent-500/15 text-white"
                          : "border-brand-800 text-white/70 hover:border-brand-700"
                      }`}
                    >
                      {e.name}
                    </button>
                  );
                })
              )}
            </div>
          </div>

          <div>
            <label className="label">Notes</label>
            <textarea
              rows={2}
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              className="input"
            />
          </div>

          {error ? <p className="text-sm text-rose-300">{error}</p> : null}
        </div>

        <div className="mt-6 flex items-center justify-end gap-3">
          <button
            type="button"
            onClick={onClose}
            disabled={busy}
            className="btn-secondary text-sm"
          >
            Annuler
          </button>
          <button
            type="button"
            onClick={submit}
            disabled={busy}
            className="btn-accent text-sm disabled:opacity-60"
          >
            {busy ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" /> Création…
              </>
            ) : (
              "Créer la tâche"
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
