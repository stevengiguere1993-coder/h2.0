"use client";

import { useMemo, useState } from "react";
import { Plus } from "lucide-react";

import {
  TaskCard,
  type TaskCardData,
  type TaskCardPatch
} from "@/components/task-card";
import { TASK_STATUS_OPTIONS } from "@/lib/task-config";
import type { TaskUserMini } from "@/components/task-pills";

/**
 * Kanban de tâches partagé — utilisé à l'identique par la fiche
 * d'une entreprise et celle d'un deal du Pipeline. Contient :
 *   - les 4 colonnes (todo / a_faire / in_progress / done) issues
 *     du module partagé /lib/task-config ;
 *   - le drag & drop d'une carte vers une autre colonne, qui
 *     déclenche `onPatch(id, { status, position })` ;
 *   - la création inline « + Tâche » par colonne ;
 *   - le rendu des cartes via <TaskCard>, lui aussi partagé.
 *
 * Les pages parents fournissent les données déjà normalisées
 * (TaskBoardItem) + les callbacks. Toute modification de mise en
 * page se fait ici une seule fois, ce qui propage l'effet partout.
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
  onCreate
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
    <div className="mt-3 flex gap-3 overflow-x-auto pb-3">
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
