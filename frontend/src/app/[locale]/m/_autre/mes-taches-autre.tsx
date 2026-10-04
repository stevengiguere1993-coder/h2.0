"use client";

/**
 * Mes tâches — variante « autre » de la zone employés.
 *
 * L'employé voit les tâches Gestion d'entreprises qui lui sont assignées
 * (par un gestionnaire ou par lui-même), s'en crée pour l'une de nos
 * entreprises, les classe (statut, priorité, échéance) et supprime celles
 * qu'il a créées. Mêmes données que le tableau « Tâches » du QG.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Building2,
  CheckSquare,
  ChevronDown,
  ChevronUp,
  Loader2,
  Lock,
  Plus,
  Trash2,
  X
} from "lucide-react";

import { authedFetch } from "@/lib/auth";
import { useConfirm } from "@/components/confirm-dialog";
import {
  TASK_PRIORITY_OPTIONS,
  TASK_STATUS_LABEL,
  TASK_STATUS_OPTIONS,
  type TaskPriorityValue,
  type TaskStatusValue
} from "@/lib/task-config";
import {
  fmtDate,
  isOverdue,
  readApiError,
  type EntrepriseChoix,
  type MaTache
} from "./shared";

// Ordre des sections (celui du backend) ; « Terminées » seulement quand
// l'employé le demande.
const SECTIONS: TaskStatusValue[] = [
  "in_progress",
  "a_faire",
  "waiting",
  "todo",
  "done"
];

const SECTION_LABEL: Record<TaskStatusValue, string> = {
  ...TASK_STATUS_LABEL,
  done: "Terminées"
};

const STATUS_DOT: Record<string, string> = Object.fromEntries(
  TASK_STATUS_OPTIONS.map((o) => [o.value, o.dot])
);

const PRIORITY_META: Record<string, { label: string; dot: string }> =
  Object.fromEntries(
    TASK_PRIORITY_OPTIONS.map((o) => [o.value, { label: o.label, dot: o.dot }])
  );

type Transition = { label: string; to: TaskStatusValue; primary?: boolean };

function transitionsFor(status: string): Transition[] {
  switch (status) {
    case "in_progress":
      return [
        { label: "Terminer", to: "done", primary: true },
        { label: "En attente", to: "waiting" }
      ];
    case "waiting":
      return [
        { label: "Reprendre", to: "in_progress", primary: true },
        { label: "Terminer", to: "done" }
      ];
    case "done":
      return [{ label: "Rouvrir", to: "a_faire" }];
    default:
      // a_faire / todo
      return [
        { label: "Commencer", to: "in_progress", primary: true },
        { label: "Terminer", to: "done" }
      ];
  }
}

const FIELD =
  "mt-1 w-full rounded-lg border border-brand-800 bg-brand-950 px-3 py-2.5 text-sm text-white";
const LABEL = "text-xs font-medium uppercase tracking-wider text-white/60";

export function MesTachesAutre() {
  const confirm = useConfirm();
  const [items, setItems] = useState<MaTache[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showDone, setShowDone] = useState(false);
  const [busy, setBusy] = useState<Set<number>>(new Set());
  const [expanded, setExpanded] = useState<number | null>(null);
  const [creating, setCreating] = useState(false);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const res = await authedFetch(
          `/api/v1/entreprises/mes-taches?include_done=${showDone}`
        );
        if (!res.ok) throw new Error(`http_${res.status}`);
        const body = (await res.json()) as unknown;
        if (!cancelled) setItems(Array.isArray(body) ? (body as MaTache[]) : []);
      } catch {
        if (!cancelled) setError("Chargement échoué.");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [showDone]);

  const setBusyFor = (id: number, on: boolean) =>
    setBusy((prev) => {
      const next = new Set(prev);
      if (on) next.add(id);
      else next.delete(id);
      return next;
    });

  const patch = useCallback(
    async (
      task: MaTache,
      body: Partial<
        Pick<MaTache, "status" | "priority" | "due_date" | "title">
      >
    ) => {
      setBusyFor(task.id, true);
      setError(null);
      try {
        const res = await authedFetch(
          `/api/v1/entreprises/mes-taches/${task.id}`,
          { method: "PATCH", body: JSON.stringify(body) }
        );
        if (!res.ok) {
          throw new Error(
            await readApiError(res, "Impossible de mettre à jour la tâche.")
          );
        }
        const updated = (await res.json()) as MaTache;
        setItems((prev) => {
          if (!showDone && updated.status === "done") {
            return prev.filter((t) => t.id !== updated.id);
          }
          return prev.map((t) => (t.id === updated.id ? updated : t));
        });
      } catch (e) {
        setError(
          e instanceof Error && e.message
            ? e.message
            : "Impossible de mettre à jour la tâche."
        );
      } finally {
        setBusyFor(task.id, false);
      }
    },
    [showDone]
  );

  async function remove(task: MaTache) {
    const ok = await confirm({
      title: "Supprimer cette tâche ?",
      description: task.title,
      confirmLabel: "Supprimer"
    });
    if (!ok) return;
    setBusyFor(task.id, true);
    setError(null);
    try {
      const res = await authedFetch(
        `/api/v1/entreprises/mes-taches/${task.id}`,
        { method: "DELETE" }
      );
      if (!res.ok) {
        throw new Error(
          await readApiError(res, "Impossible de supprimer la tâche.")
        );
      }
      setItems((prev) => prev.filter((t) => t.id !== task.id));
    } catch (e) {
      setError(
        e instanceof Error && e.message
          ? e.message
          : "Impossible de supprimer la tâche."
      );
    } finally {
      setBusyFor(task.id, false);
    }
  }

  const sections = useMemo(() => {
    const by = new Map<string, MaTache[]>();
    for (const t of items) {
      if (!by.has(t.status)) by.set(t.status, []);
      by.get(t.status)!.push(t);
    }
    return SECTIONS.filter((s) => by.has(s)).map((s) => ({
      status: s,
      tasks: by.get(s)!
    }));
  }, [items]);

  return (
    <>
      <header
        className="sticky top-0 z-30 border-b border-brand-800 bg-brand-950/95 px-4 py-3 backdrop-blur"
        style={{ paddingTop: "max(env(safe-area-inset-top), 0.75rem)" }}
      >
        <div className="flex items-start justify-between gap-3">
          <div>
            <h1 className="text-base font-bold text-white">Mes tâches</h1>
            <p className="mt-0.5 text-[11px] text-white/50">
              Tes tâches pour nos entreprises.
            </p>
          </div>
          <button
            type="button"
            onClick={() => setCreating((v) => !v)}
            className="inline-flex items-center gap-1.5 rounded-full bg-accent-500 px-3 py-1.5 text-xs font-semibold text-brand-950"
          >
            {creating ? (
              <X className="h-3.5 w-3.5" />
            ) : (
              <Plus className="h-3.5 w-3.5" />
            )}
            {creating ? "Fermer" : "Nouvelle tâche"}
          </button>
        </div>
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

        {creating ? (
          <NouvelleTacheForm
            onCreated={(t) => {
              setItems((prev) => [t, ...prev]);
              setCreating(false);
            }}
            onCancel={() => setCreating(false)}
          />
        ) : null}

        {loading ? (
          <div className="flex items-center justify-center py-10">
            <Loader2 className="h-5 w-5 animate-spin text-white/40" />
          </div>
        ) : sections.length === 0 ? (
          <div className="rounded-2xl border border-dashed border-brand-800 bg-brand-900/40 px-6 py-10 text-center">
            <CheckSquare className="mx-auto h-8 w-8 text-white/30" />
            <p className="mt-3 text-sm text-white/60">
              {showDone
                ? "Aucune tâche pour l’instant."
                : "Aucune tâche en cours. 🎉"}
            </p>
            <p className="mt-1 text-xs text-white/50">
              Crée-toi une tâche avec « Nouvelle tâche ».
            </p>
          </div>
        ) : (
          <div className="space-y-5">
            {sections.map((g) => (
              <section key={g.status}>
                <h2 className="mb-2 flex items-center gap-2 text-[11px] font-semibold uppercase tracking-wider text-white/50">
                  <span
                    className={`h-2 w-2 rounded-full ${STATUS_DOT[g.status]}`}
                  />
                  {SECTION_LABEL[g.status]}
                  <span className="text-white/40">· {g.tasks.length}</span>
                </h2>
                <ul className="space-y-2">
                  {g.tasks.map((t) => (
                    <TacheCard
                      key={t.id}
                      task={t}
                      busy={busy.has(t.id)}
                      expanded={expanded === t.id}
                      onToggle={() =>
                        setExpanded((cur) => (cur === t.id ? null : t.id))
                      }
                      onPatch={(body) => void patch(t, body)}
                      onDelete={() => void remove(t)}
                    />
                  ))}
                </ul>
              </section>
            ))}
          </div>
        )}
      </div>
    </>
  );
}

function TacheCard({
  task: t,
  busy,
  expanded,
  onToggle,
  onPatch,
  onDelete
}: {
  task: MaTache;
  busy: boolean;
  expanded: boolean;
  onToggle: () => void;
  onPatch: (
    body: Partial<Pick<MaTache, "status" | "priority" | "due_date">>
  ) => void;
  onDelete: () => void;
}) {
  const done = t.status === "done";
  const overdue = !done && isOverdue(t.due_date);
  const prio = PRIORITY_META[t.priority];

  return (
    <li
      className={`rounded-xl border px-3 py-3 ${
        done ? "border-brand-800 bg-brand-900/40" : "border-brand-800 bg-brand-900"
      }`}
    >
      <button
        type="button"
        onClick={onToggle}
        className="flex w-full items-start gap-3 text-left"
        aria-expanded={expanded}
      >
        <div className="min-w-0 flex-1">
          <p
            className={`text-sm font-semibold ${
              done ? "text-white/40 line-through" : "text-white"
            }`}
          >
            {t.title}
          </p>
          {t.description ? (
            <p className="mt-0.5 whitespace-pre-wrap text-xs text-white/60">
              {t.description}
            </p>
          ) : null}
          <div className="mt-1.5 flex flex-wrap items-center gap-2 text-[11px]">
            <span className="inline-flex items-center gap-1.5 rounded-full border border-brand-700 bg-brand-950 px-2 py-0.5 text-white/60">
              <span
                className="h-2 w-2 rounded-full"
                style={{ backgroundColor: t.entreprise_color || "#94a3b8" }}
              />
              {t.entreprise_name}
            </span>
            {prio && t.priority !== "non_assigne" ? (
              <span className="inline-flex items-center gap-1.5 text-white/60">
                <span className={`h-2 w-2 rounded-full ${prio.dot}`} />
                {prio.label}
              </span>
            ) : null}
            {t.due_date ? (
              <span
                className={
                  overdue
                    ? "rounded-full border border-rose-500/40 bg-rose-500/10 px-2 py-0.5 text-rose-300"
                    : "rounded-full border border-brand-700 bg-brand-950 px-2 py-0.5 text-white/60"
                }
              >
                {overdue ? "En retard · " : "Échéance "}
                {fmtDate(t.due_date)}
              </span>
            ) : null}
          </div>
        </div>
        {busy ? (
          <Loader2 className="mt-0.5 h-4 w-4 flex-shrink-0 animate-spin text-white/40" />
        ) : expanded ? (
          <ChevronUp className="mt-0.5 h-4 w-4 flex-shrink-0 text-white/40" />
        ) : (
          <ChevronDown className="mt-0.5 h-4 w-4 flex-shrink-0 text-white/40" />
        )}
      </button>

      {/* Changement de statut : toujours visible, un geste. */}
      <div className="mt-3 flex flex-wrap items-center gap-2">
        {transitionsFor(t.status).map((tr) => (
          <button
            key={tr.to}
            type="button"
            disabled={busy}
            onClick={() => onPatch({ status: tr.to })}
            className={
              tr.primary
                ? "rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-2.5 py-1.5 text-[11px] font-semibold text-emerald-300 disabled:opacity-50"
                : "rounded-lg border border-brand-700 bg-brand-950 px-2.5 py-1.5 text-[11px] font-semibold text-white/70 disabled:opacity-50"
            }
          >
            {tr.label}
          </button>
        ))}
        <span className="flex-1" />
        {t.peut_supprimer ? (
          <button
            type="button"
            disabled={busy}
            onClick={onDelete}
            aria-label="Supprimer la tâche"
            className="rounded-lg border border-rose-500/40 bg-rose-500/10 p-1.5 text-rose-300 disabled:opacity-50"
          >
            <Trash2 className="h-4 w-4" />
          </button>
        ) : (
          <span
            className="inline-flex items-center gap-1 text-[10px] text-white/40"
            title="Cette tâche t'a été assignée par un gestionnaire : termine-la plutôt que de la supprimer."
          >
            <Lock className="h-3 w-3" /> Assignée par un gestionnaire
          </span>
        )}
      </div>

      {expanded ? (
        <div className="mt-3 grid grid-cols-2 gap-3 border-t border-brand-800 pt-3">
          <div>
            <label className={LABEL}>Priorité</label>
            <select
              value={t.priority}
              disabled={busy}
              onChange={(e) =>
                onPatch({ priority: e.target.value as TaskPriorityValue })
              }
              className={FIELD}
            >
              {TASK_PRIORITY_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className={LABEL}>Échéance</label>
            <input
              type="date"
              value={t.due_date || ""}
              disabled={busy}
              onChange={(e) => onPatch({ due_date: e.target.value || null })}
              className={FIELD}
            />
          </div>
        </div>
      ) : null}
    </li>
  );
}

function NouvelleTacheForm({
  onCreated,
  onCancel
}: {
  onCreated: (t: MaTache) => void;
  onCancel: () => void;
}) {
  const [entreprises, setEntreprises] = useState<EntrepriseChoix[] | null>(
    null
  );
  const [title, setTitle] = useState("");
  const [entrepriseId, setEntrepriseId] = useState<string>("");
  const [priority, setPriority] = useState<TaskPriorityValue>("moyenne");
  const [dueDate, setDueDate] = useState("");
  const [description, setDescription] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const res = await authedFetch(
          "/api/v1/entreprises/mes-taches/entreprises"
        );
        if (!res.ok) throw new Error(`http_${res.status}`);
        const body = (await res.json()) as unknown;
        const rows = Array.isArray(body) ? (body as EntrepriseChoix[]) : [];
        if (cancelled) return;
        setEntreprises(rows);
        // Une seule entreprise possible → présélectionnée.
        if (rows.length === 1) setEntrepriseId(String(rows[0].id));
      } catch {
        if (!cancelled) {
          setEntreprises([]);
          setError("Impossible de charger les entreprises.");
        }
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, []);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!title.trim() || !entrepriseId) return;
    setSaving(true);
    setError(null);
    try {
      const res = await authedFetch("/api/v1/entreprises/mes-taches", {
        method: "POST",
        body: JSON.stringify({
          title: title.trim(),
          entreprise_id: Number(entrepriseId),
          priority,
          due_date: dueDate || null,
          description: description.trim() || null
        })
      });
      if (!res.ok) {
        throw new Error(await readApiError(res, "Création impossible."));
      }
      onCreated((await res.json()) as MaTache);
    } catch (err) {
      setError(
        err instanceof Error && err.message ? err.message : "Création impossible."
      );
    } finally {
      setSaving(false);
    }
  }

  const canSubmit = !!title.trim() && !!entrepriseId && !saving;

  return (
    <form
      onSubmit={submit}
      className="mb-4 space-y-3 rounded-2xl border border-accent-500/40 bg-brand-900 p-4"
    >
      <p className="flex items-center gap-2 text-xs uppercase tracking-wider text-white/50">
        <Plus className="h-3.5 w-3.5 text-accent-500" /> Nouvelle tâche
      </p>
      {error ? (
        <p className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
          {error}
        </p>
      ) : null}
      <div>
        <label className={LABEL}>Titre</label>
        <input
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="Ex. : Monter la vidéo du projet…"
          maxLength={255}
          required
          className={FIELD}
        />
      </div>
      <div>
        <label className={LABEL}>Entreprise</label>
        {entreprises === null ? (
          <p className="mt-1 flex items-center gap-2 text-xs text-white/50">
            <Loader2 className="h-3.5 w-3.5 animate-spin" /> Chargement…
          </p>
        ) : entreprises.length === 0 ? (
          <p className="mt-1 flex items-center gap-2 text-xs text-white/60">
            <Building2 className="h-3.5 w-3.5" /> Aucune entreprise disponible
            — demande à un gestionnaire.
          </p>
        ) : (
          <select
            value={entrepriseId}
            onChange={(e) => setEntrepriseId(e.target.value)}
            required
            className={FIELD}
          >
            {entreprises.length > 1 ? (
              <option value="">Choisir…</option>
            ) : null}
            {entreprises.map((en) => (
              <option key={en.id} value={en.id}>
                {en.name}
              </option>
            ))}
          </select>
        )}
      </div>
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className={LABEL}>Priorité</label>
          <select
            value={priority}
            onChange={(e) => setPriority(e.target.value as TaskPriorityValue)}
            className={FIELD}
          >
            {TASK_PRIORITY_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className={LABEL}>Échéance</label>
          <input
            type="date"
            value={dueDate}
            onChange={(e) => setDueDate(e.target.value)}
            className={FIELD}
          />
        </div>
      </div>
      <div>
        <label className={LABEL}>Description (facultatif)</label>
        <textarea
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          rows={2}
          className={FIELD}
        />
      </div>
      <div className="flex items-center justify-end gap-2 pt-1">
        <button
          type="button"
          onClick={onCancel}
          className="rounded-lg border border-brand-700 bg-brand-950 px-3 py-2 text-xs font-semibold text-white/70"
        >
          Annuler
        </button>
        <button
          type="submit"
          disabled={!canSubmit}
          className="inline-flex items-center gap-1.5 rounded-lg bg-accent-500 px-3 py-2 text-xs font-semibold text-brand-950 disabled:opacity-50"
        >
          {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
          Créer la tâche
        </button>
      </div>
    </form>
  );
}
