"use client";

import { useEffect, useRef, useState } from "react";
import { Loader2, X } from "lucide-react";

import {
  AssigneePicker,
  type TaskUserMini
} from "@/components/task-pills";
import {
  ImmeublePicker,
  ManageImmeublesButton,
  type ImmeubleMini
} from "@/components/immeuble-picker";
import {
  TASK_PRIORITY_OPTIONS,
  TASK_STATUS_OPTIONS
} from "@/lib/task-config";

/**
 * Modal de détails / modification d'une tâche — version simplifiée
 * commune au Pipeline des deals et au kanban Entreprise (l'Entreprise
 * a aussi sa propre TacheModal pour les champs avancés ICE /
 * récurrence ; cette modal-ci se concentre sur les champs de base
 * qui apparaissent aussi sur la carte).
 *
 * Champs : titre, notes/description, statut, priorité, personnes
 * assignées, échéance. Tout est édité inline + auto-save (PATCH au
 * blur ou au change selon le champ).
 */
export type TaskDetailsModalData = {
  id: number;
  title: string;
  notes: string;
  status: string;
  priority: string;
  due_date: string | null;
  assignee_user_ids: number[];
  immeuble_ids: number[];
};

export type TaskDetailsModalPatch = {
  title?: string;
  notes?: string | null;
  status?: string;
  priority?: string;
  due_date?: string | null;
  assignee_user_ids?: number[];
  immeuble_ids?: number[];
};

export function TaskDetailsModal({
  task,
  users,
  immeubles,
  onClose,
  onPatch,
  onImmeublesChanged
}: {
  task: TaskDetailsModalData;
  users: TaskUserMini[];
  immeubles: ImmeubleMini[];
  onClose: () => void;
  onPatch: (patch: TaskDetailsModalPatch) => void | Promise<void>;
  /** Optionnel — appelé après ajout/retrait d'un immeuble dans le
   *  catalogue depuis le bouton « Gérer ». Le parent doit re-fetch
   *  /api/v1/immeubles/picker pour rafraîchir la liste affichée. */
  onImmeublesChanged?: () => void;
}) {
  const [title, setTitle] = useState(task.title);
  const [notes, setNotes] = useState(task.notes);
  const titleRef = useRef<HTMLTextAreaElement | null>(null);

  // Resync si le parent met à jour la tâche (les autres pastilles
  // poussent un patch et reviennent vers nous).
  useEffect(() => {
    setTitle(task.title);
    setNotes(task.notes);
  }, [task.id, task.title, task.notes]);

  // ESC pour fermer.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  // Resize auto du titre sur changement.
  useEffect(() => {
    const el = titleRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${el.scrollHeight}px`;
  }, [title]);

  function commitTitle() {
    const v = title.trim();
    if (v && v !== task.title) onPatch({ title: v });
    else if (!v) setTitle(task.title);
  }
  function commitNotes() {
    if (notes !== task.notes) onPatch({ notes: notes || null });
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4"
      onClick={onClose}
    >
      <div
        className="w-full max-w-2xl rounded-2xl border border-brand-800 bg-brand-950 p-6"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="flex items-start justify-between gap-3">
          <h3 className="text-base font-semibold text-white/60">
            Détails de la tâche
          </h3>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md p-1 text-white/60 hover:bg-brand-900 hover:text-white"
            aria-label="Fermer"
          >
            <X className="h-4 w-4" />
          </button>
        </header>

        <div className="mt-4 space-y-4">
          <div>
            <label className="label">Titre</label>
            <textarea
              ref={titleRef}
              rows={1}
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              onBlur={commitTitle}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  (e.target as HTMLTextAreaElement).blur();
                }
              }}
              className="input resize-none"
              style={{ overflow: "hidden" }}
            />
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <label className="label">Statut</label>
              <select
                value={task.status}
                onChange={(e) => onPatch({ status: e.target.value })}
                className="input"
              >
                {TASK_STATUS_OPTIONS.map((s) => (
                  <option key={s.value} value={s.value}>
                    {s.label}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="label">Priorité</label>
              <select
                value={task.priority || "non_assigne"}
                onChange={(e) => onPatch({ priority: e.target.value })}
                className="input"
              >
                {TASK_PRIORITY_OPTIONS.map((p) => (
                  <option key={p.value} value={p.value}>
                    {p.label}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="label">Personnes</label>
              <AssigneePicker
                users={users}
                values={task.assignee_user_ids}
                onChange={(ids) => onPatch({ assignee_user_ids: ids })}
                variant="modal"
              />
            </div>
            <div>
              <label className="label">Échéance</label>
              <input
                type="date"
                value={task.due_date || ""}
                onChange={(e) =>
                  onPatch({ due_date: e.target.value || null })
                }
                className="input"
              />
            </div>
          </div>

          <div>
            <div className="mb-1.5 flex items-center justify-between gap-2">
              <span className="block text-sm font-medium text-white">
                Immeuble
              </span>
              {onImmeublesChanged ? (
                <ManageImmeublesButton
                  immeubles={immeubles}
                  onChanged={onImmeublesChanged}
                />
              ) : null}
            </div>
            <ImmeublePicker
              immeubles={immeubles}
              values={task.immeuble_ids}
              onChange={(ids) => onPatch({ immeuble_ids: ids })}
              variant="modal"
            />
          </div>

          <div>
            <label className="label">Notes</label>
            <textarea
              rows={6}
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              onBlur={commitNotes}
              placeholder="Notes / description…"
              className="input"
            />
          </div>
        </div>

        <footer className="mt-5 flex items-center justify-end">
          <button
            type="button"
            onClick={onClose}
            className="btn-accent text-sm"
          >
            Fermer
          </button>
        </footer>
      </div>
    </div>
  );
}

// Re-export pour clarté côté consumer.
export type { TaskUserMini };

// Loader2 importé pour usage potentiel (états async). Garder dans
// la barrière d'imports même si pas encore utilisé.
void Loader2;
