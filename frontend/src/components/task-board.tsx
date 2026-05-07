"use client";

import { useMemo, useState } from "react";
import { Plus } from "lucide-react";

import {
  TaskCard,
  type TaskCardData,
  type TaskCardPatch
} from "@/components/task-card";
import {
  TASK_PRIORITY_OPTIONS,
  TASK_STATUS_OPTIONS
} from "@/lib/task-config";
import type { TaskUserMini } from "@/components/task-pills";
import {
  AssigneePicker,
  DatePill,
  PillPicker
} from "@/components/task-pills";

/**
 * Section « Tâches » partagée — utilisée à l'identique par la fiche
 * d'une entreprise et celle d'un deal du Pipeline. Contient :
 *
 *   - Le **titre « Tâches »** + bouton « + Nouvelle tâche » (qui
 *     délègue au parent l'ouverture de sa propre modale, le cas
 *     échéant — Entreprise a une modale riche, Pipeline pas).
 *   - Un **toggle Tableau / Kanban** pour basculer la présentation.
 *   - La **vue Tableau** : liste plate compacte (statut éditable
 *     inline, click row → ouvre la fiche).
 *   - La **vue Kanban** : 4 colonnes (todo / a_faire / in_progress
 *     / done) issues du module partagé /lib/task-config, avec
 *     drag-drop entre colonnes, création inline « + Tâche » par
 *     colonne, et bouton « Déplacer » optionnel.
 *
 * Toute évolution visuelle ou fonctionnelle se fait à un seul
 * endroit, ce qui propage l'effet à toutes les sections « Tâches »
 * de l'app.
 */

export type TaskBoardItem = TaskCardData & {
  position?: number;
  // Footer libre rendu sous les pastilles (utilisé par l'entreprise
  // pour les badges score / récurrence / département).
  footer?: React.ReactNode;
};

export function TaskBoard({
  tasks,
  users,
  onPatch,
  onDelete,
  onOpenDetails,
  onMove,
  onCreate,
  onNewTask,
  title = "Tâches",
  newTaskLabel = "Nouvelle tâche"
}: {
  tasks: TaskBoardItem[];
  users: TaskUserMini[];
  /** Patch générique : statut, priorité, échéance, personnes, position. */
  onPatch: (
    taskId: number,
    patch: TaskCardPatch & { position?: number }
  ) => void;
  onDelete: (taskId: number) => void;
  onOpenDetails: (taskId: number) => void;
  /** Bouton « Déplacer » sous la poubelle. Si non fourni, l'icône
   *  n'apparaît pas. */
  onMove?: (taskId: number) => void;
  /** Création inline (titre seul). Le statut = la colonne où
   *  l'utilisateur a cliqué « + Tâche ». */
  onCreate: (status: string, name: string) => void;
  /** Optionnel — bouton « + Nouvelle tâche » en haut de la section.
   *  Le parent ouvre généralement une modale plus riche
   *  (description, ICE, récurrence pour Entreprise). Si absent, le
   *  bouton n'est pas rendu. */
  onNewTask?: () => void;
  /** Titre de la section (par défaut « Tâches »). */
  title?: string;
  newTaskLabel?: string;
}) {
  const [view, setView] = useState<"kanban" | "list">("kanban");

  return (
    <div className="mt-6">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <h2 className="text-sm font-semibold uppercase tracking-wider text-white/50">
            {title}
          </h2>
          {onNewTask ? (
            <button
              type="button"
              onClick={onNewTask}
              className="btn-accent inline-flex items-center text-xs"
            >
              <Plus className="mr-1 h-3.5 w-3.5" />
              {newTaskLabel}
            </button>
          ) : null}
        </div>
        <div className="inline-flex rounded-lg border border-brand-800 bg-brand-900 p-0.5">
          <button
            type="button"
            onClick={() => setView("list")}
            className="rounded-md px-3 py-1.5 text-xs font-semibold transition"
            style={{
              backgroundColor:
                view === "list" ? "#a78bfa" : "transparent",
              color:
                view === "list" ? "#0a0a0b" : "rgba(245,245,247,0.6)"
            }}
          >
            Tableau
          </button>
          <button
            type="button"
            onClick={() => setView("kanban")}
            className="rounded-md px-3 py-1.5 text-xs font-semibold transition"
            style={{
              backgroundColor:
                view === "kanban" ? "#a78bfa" : "transparent",
              color:
                view === "kanban" ? "#0a0a0b" : "rgba(245,245,247,0.6)"
            }}
          >
            Kanban
          </button>
        </div>
      </div>

      {view === "kanban" ? (
        <KanbanView
          tasks={tasks}
          users={users}
          onPatch={onPatch}
          onDelete={onDelete}
          onOpenDetails={onOpenDetails}
          onMove={onMove}
          onCreate={onCreate}
        />
      ) : (
        <TaskListView
          tasks={tasks}
          users={users}
          onPatch={onPatch}
          onOpenDetails={onOpenDetails}
        />
      )}
    </div>
  );
}

// ─── Kanban ────────────────────────────────────────────────────────

function KanbanView({
  tasks,
  users,
  onPatch,
  onDelete,
  onOpenDetails,
  onMove,
  onCreate
}: {
  tasks: TaskBoardItem[];
  users: TaskUserMini[];
  onPatch: (
    taskId: number,
    patch: TaskCardPatch & { position?: number }
  ) => void;
  onDelete: (taskId: number) => void;
  onOpenDetails: (taskId: number) => void;
  onMove?: (taskId: number) => void;
  onCreate: (status: string, name: string) => void;
}) {
  const [dragId, setDragId] = useState<number | null>(null);
  const [hoverCol, setHoverCol] = useState<string | null>(null);
  const [adding, setAdding] = useState<string | null>(null);
  const [newName, setNewName] = useState("");

  const byStatus = useMemo(() => {
    const map: Record<string, TaskBoardItem[]> = Object.fromEntries(
      TASK_STATUS_OPTIONS.map((s) => [s.value, [] as TaskBoardItem[]])
    );
    for (const t of tasks) {
      const target = map[t.status] ? t.status : "a_faire";
      (map[target] ||= []).push(t);
    }
    for (const k of Object.keys(map)) {
      map[k].sort(
        (a, b) => (a.position ?? 0) - (b.position ?? 0)
      );
    }
    return map;
  }, [tasks]);

  function handleDrop(targetStatus: string) {
    const id = dragId;
    setDragId(null);
    setHoverCol(null);
    if (id == null) return;
    const t = tasks.find((x) => x.id === id);
    if (!t || t.status === targetStatus) return;
    const sameStatus = tasks.filter((x) => x.status === targetStatus);
    const newPos =
      sameStatus.length > 0
        ? Math.max(...sameStatus.map((x) => x.position ?? 0)) + 1000
        : 1000;
    onPatch(t.id, { status: targetStatus, position: newPos });
  }

  function commitCreate(status: string) {
    const v = newName.trim();
    setAdding(null);
    setNewName("");
    if (v) onCreate(status, v);
  }

  return (
    <div className="flex gap-3 overflow-x-auto pb-3">
      {TASK_STATUS_OPTIONS.map((col) => {
        const list = byStatus[col.value] || [];
        const isHover = hoverCol === col.value;
        return (
          <div
            key={col.value}
            onDragOver={(e) => {
              e.preventDefault();
              setHoverCol(col.value);
            }}
            onDragLeave={() =>
              setHoverCol((c) => (c === col.value ? null : c))
            }
            onDrop={(e) => {
              e.preventDefault();
              handleDrop(col.value);
            }}
            className={`flex w-72 flex-shrink-0 flex-col rounded-xl border bg-brand-900 ${
              isHover ? "border-accent-500" : "border-brand-800"
            }`}
          >
            <div className="border-b border-brand-800 px-3 py-2">
              <div className="flex items-center justify-between">
                <h3 className="inline-flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-white">
                  <span
                    className={`h-1.5 w-1.5 rounded-full ${col.dot}`}
                  />
                  {col.label}
                </h3>
                <span className="rounded-md bg-brand-950 px-2 py-0.5 text-xs font-semibold text-white/70">
                  {list.length}
                </span>
              </div>
            </div>

            <div className="flex-1 space-y-2 p-3">
              {list.length === 0 && adding !== col.value ? (
                <p className="py-8 text-center text-xs text-white/40">
                  Aucune tâche
                </p>
              ) : null}

              {list.map((t) => (
                <TaskCard
                  key={t.id}
                  task={t}
                  users={users}
                  onPatch={(p) => onPatch(t.id, p)}
                  onDelete={(ev) => {
                    ev.stopPropagation();
                    ev.preventDefault();
                    onDelete(t.id);
                  }}
                  onOpenDetails={() => onOpenDetails(t.id)}
                  onMove={onMove ? () => onMove(t.id) : undefined}
                  draggable
                  dragging={dragId === t.id}
                  onDragStart={() => setDragId(t.id)}
                  onDragEnd={() => {
                    setDragId(null);
                    setHoverCol(null);
                  }}
                  footer={t.footer}
                />
              ))}

              {adding === col.value ? (
                <input
                  autoFocus
                  type="text"
                  value={newName}
                  onChange={(e) => setNewName(e.target.value)}
                  onBlur={() => commitCreate(col.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") commitCreate(col.value);
                    if (e.key === "Escape") {
                      setAdding(null);
                      setNewName("");
                    }
                  }}
                  placeholder="Nom de la tâche…"
                  className="w-full rounded border border-brand-800 bg-brand-950 px-2 py-1 text-xs text-white focus:border-accent-500 focus:outline-none"
                />
              ) : (
                <button
                  type="button"
                  onClick={() => {
                    setAdding(col.value);
                    setNewName("");
                  }}
                  className="flex w-full items-center justify-center gap-1 rounded border border-dashed border-brand-700 px-2 py-1.5 text-[11px] text-white/40 hover:border-accent-500 hover:text-accent-400"
                >
                  <Plus className="h-3 w-3" /> Tâche
                </button>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ─── Vue Tableau ───────────────────────────────────────────────────

function TaskListView({
  tasks,
  users,
  onPatch,
  onOpenDetails
}: {
  tasks: TaskBoardItem[];
  users: TaskUserMini[];
  onPatch: (
    taskId: number,
    patch: TaskCardPatch & { position?: number }
  ) => void;
  onOpenDetails: (taskId: number) => void;
}) {
  const sorted = useMemo(
    () =>
      [...tasks].sort(
        (a, b) => (a.position ?? 0) - (b.position ?? 0)
      ),
    [tasks]
  );

  if (sorted.length === 0) {
    return (
      <div className="rounded-xl border border-brand-800 bg-brand-900/60 px-6 py-12 text-center">
        <p className="text-sm text-white/50">Aucune tâche</p>
      </div>
    );
  }

  return (
    <div className="overflow-hidden rounded-xl border border-brand-800 bg-brand-900/60">
      <table className="w-full text-[13px]">
        <thead>
          <tr
            className="text-[10px] uppercase tracking-wider text-white/50"
            style={{ borderBottom: "1px solid rgba(255,255,255,0.06)" }}
          >
            <th className="px-4 py-2.5 text-left">Tâche</th>
            <th className="px-3 py-2.5 text-left">Statut</th>
            <th className="px-3 py-2.5 text-left">Priorité</th>
            <th className="px-3 py-2.5 text-left">Personnes</th>
            <th className="px-3 py-2.5 text-right">Échéance</th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((t) => (
            <tr
              key={t.id}
              onClick={() => onOpenDetails(t.id)}
              className="cursor-pointer hover:bg-white/5"
              style={{ borderBottom: "1px solid rgba(255,255,255,0.04)" }}
            >
              <td className="max-w-[420px] px-4 py-3">
                <p className="truncate font-medium text-white">
                  {t.title}
                </p>
                {t.immeubleLabels && t.immeubleLabels.length > 0 ? (
                  <p className="mt-0.5 truncate text-[11px] text-white/85">
                    {t.immeubleLabels.join(", ")}
                  </p>
                ) : null}
                {t.footer ? (
                  <div className="mt-1">{t.footer}</div>
                ) : null}
              </td>
              <td
                className="px-3 py-3"
                onClick={(e) => e.stopPropagation()}
              >
                <PillPicker
                  options={TASK_STATUS_OPTIONS.map((o) => ({
                    value: o.value,
                    label: o.label,
                    cls: o.pill
                  }))}
                  value={t.status}
                  onChange={(v) => onPatch(t.id, { status: v })}
                  ariaLabel="Statut"
                />
              </td>
              <td
                className="px-3 py-3"
                onClick={(e) => e.stopPropagation()}
              >
                <PillPicker
                  options={TASK_PRIORITY_OPTIONS.map((o) => ({
                    value: o.value,
                    label: o.label,
                    cls: o.pill
                  }))}
                  value={t.priority || "non_assigne"}
                  onChange={(v) => onPatch(t.id, { priority: v })}
                  ariaLabel="Priorité"
                />
              </td>
              <td
                className="px-3 py-3"
                onClick={(e) => e.stopPropagation()}
              >
                <AssigneePicker
                  users={users}
                  values={t.assignee_user_ids || []}
                  onChange={(ids) =>
                    onPatch(t.id, { assignee_user_ids: ids })
                  }
                />
              </td>
              <td
                className="px-3 py-3 text-right"
                onClick={(e) => e.stopPropagation()}
              >
                <DatePill
                  value={t.due_date}
                  onChange={(d) => onPatch(t.id, { due_date: d })}
                />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

