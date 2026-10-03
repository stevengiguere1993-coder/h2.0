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
  type ImmeubleMini,
  type ImmeubleScope
} from "@/components/immeuble-picker";
import {
  TASK_PRIORITY_OPTIONS,
  TASK_STATUS_OPTIONS
} from "@/lib/task-config";

/**
 * Modal de détails / modification d'une tâche — fiche **complète**
 * partagée par Pipeline et Entreprise. Tout y est édité inline avec
 * auto-save (PATCH au blur ou au change selon le champ) — pas de
 * bouton « Enregistrer ».
 *
 * Champs : titre, statut, priorité, personnes, échéance, immeuble
 * (multi), département, récurrence, ICE (impact / confiance / effort)
 * + score auto-calculé, notes / description.
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
  /** Entreprises concernées : la première est la principale. */
  entreprise_ids?: number[];
  departement: string | null;
  recurrence: string | null;
  impact: number | null;
  confidence: number | null;
  effort: number | null;
  /** Score serveur — read-only (ICE × multiplicateur d'urgence). */
  score: number | null;
};

export type TaskDetailsModalPatch = {
  title?: string;
  notes?: string | null;
  status?: string;
  priority?: string;
  due_date?: string | null;
  assignee_user_ids?: number[];
  immeuble_ids?: number[];
  entreprise_ids?: number[];
  departement?: string | null;
  recurrence?: string | null;
  impact?: number | null;
  confidence?: number | null;
  effort?: number | null;
};

export type TaskEntrepriseMini = { id: number; name: string };

export function TaskDetailsModal({
  task,
  users,
  immeubles,
  immeubleScope,
  entreprises,
  onClose,
  onPatch,
  onImmeublesChanged
}: {
  task: TaskDetailsModalData;
  users: TaskUserMini[];
  immeubles: ImmeubleMini[];
  /** Catalogue des entreprises — affiche le choix (multi) des
   *  entreprises concernées ; la première cochée est la principale. */
  entreprises?: TaskEntrepriseMini[];
  /** Scope du catalogue d'immeubles : entreprise_id ou deal_id. */
  immeubleScope?: ImmeubleScope;
  onClose: () => void;
  onPatch: (patch: TaskDetailsModalPatch) => void | Promise<void>;
  /** Optionnel — appelé après ajout/retrait d'un immeuble dans le
   *  catalogue depuis le bouton « Gérer ». Le parent doit re-fetch
   *  /api/v1/immobilier/immeubles/picker pour rafraîchir la liste affichée. */
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
        className="flex max-h-[calc(100vh-2rem)] w-full max-w-2xl flex-col overflow-hidden rounded-2xl border border-brand-800 bg-brand-950"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="flex flex-shrink-0 items-start justify-between gap-3 border-b border-brand-800 px-6 py-4">
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

        <div className="flex-1 space-y-4 overflow-y-auto px-6 py-4">
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
                  scope={immeubleScope}
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

          {entreprises && entreprises.length > 0 ? (
            <EntreprisesField
              entreprises={entreprises}
              values={task.entreprise_ids || []}
              onChange={(ids) => onPatch({ entreprise_ids: ids })}
            />
          ) : null}

          <div>
            <label className="label">Département</label>
            <input
              type="text"
              value={task.departement || ""}
              onChange={(e) =>
                onPatch({ departement: e.target.value || null })
              }
              placeholder="finance / opérations / RH…"
              className="input"
            />
          </div>

          <div>
            <div className="mb-1.5 flex items-baseline justify-between">
              <span className="block text-sm font-medium text-white">
                ICE (1–10)
              </span>
              <span className="text-[10px] text-white/40">
                Impact × Confiance / Effort × multiplicateur d&apos;urgence
              </span>
            </div>
            <div className="grid gap-2 sm:grid-cols-3">
              <ICEField
                label="Impact"
                value={task.impact}
                onChange={(v) => onPatch({ impact: v })}
              />
              <ICEField
                label="Confiance"
                value={task.confidence}
                onChange={(v) => onPatch({ confidence: v })}
              />
              <ICEField
                label="Effort"
                value={task.effort}
                onChange={(v) => onPatch({ effort: v })}
              />
            </div>
            {task.score != null ? (
              <p className="mt-1.5 text-[11px] text-violet-300">
                Score :{" "}
                <span className="font-bold">{task.score.toFixed(1)}</span>
              </p>
            ) : null}
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

        <footer className="flex flex-shrink-0 items-center justify-end border-t border-brand-800 px-6 py-3">
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

function EntreprisesField({
  entreprises,
  values,
  onChange
}: {
  entreprises: TaskEntrepriseMini[];
  values: number[];
  onChange: (ids: number[]) => void;
}) {
  const [q, setQ] = useState("");
  const needle = q.trim().toLowerCase();
  const visibles = entreprises.filter(
    (e) => values.includes(e.id) || !needle || e.name.toLowerCase().includes(needle)
  );
  const byId = new Map(entreprises.map((e) => [e.id, e.name]));
  function toggle(id: number) {
    if (values.includes(id)) {
      if (values.length === 1) return; // toujours au moins une entreprise
      onChange(values.filter((v) => v !== id));
    } else {
      onChange([...values, id]);
    }
  }
  function principale(id: number) {
    onChange([id, ...values.filter((v) => v !== id)]);
  }
  return (
    <div>
      <label className="label">
        Entreprise(s) concernée(s)
        {values[0] != null ? (
          <span className="ml-1 font-normal text-white/50">· principale : {byId.get(values[0]) || values[0]}</span>
        ) : null}
      </label>
      {entreprises.length > 8 ? (
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Filtrer les entreprises…"
          className="input mb-1 w-full text-xs"
        />
      ) : null}
      <div className="max-h-40 space-y-0.5 overflow-y-auto rounded-lg border border-brand-800 p-1">
        {visibles.map((e) => {
          const on = values.includes(e.id);
          const isMain = values[0] === e.id;
          return (
            <div key={e.id} className="flex items-center gap-2 px-2 py-1 text-sm">
              <input
                type="checkbox"
                checked={on}
                onChange={() => toggle(e.id)}
                className="h-4 w-4 accent-accent-500"
                aria-label={e.name}
              />
              <span className={on ? "text-white" : "text-white/70"}>{e.name}</span>
              {on && !isMain ? (
                <button
                  type="button"
                  onClick={() => principale(e.id)}
                  className="ml-auto text-[10px] text-white/50 underline hover:text-white"
                  title="En faire l'entreprise principale"
                >
                  rendre principale
                </button>
              ) : isMain ? (
                <span className="ml-auto rounded bg-accent-500/20 px-1.5 text-[10px] font-semibold text-accent-500">principale</span>
              ) : null}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function ICEField({
  label,
  value,
  onChange
}: {
  label: string;
  value: number | null;
  onChange: (v: number | null) => void;
}) {
  // State local pour autoriser la saisie progressive sans push à
  // chaque caractère ; commit au blur uniquement.
  const [draft, setDraft] = useState<string>(
    value != null ? String(value) : ""
  );
  useEffect(() => {
    setDraft(value != null ? String(value) : "");
  }, [value]);

  function commit() {
    if (draft.trim() === "") {
      if (value !== null) onChange(null);
      return;
    }
    const v = Number(draft);
    if (Number.isNaN(v) || v < 1 || v > 10) {
      // Annule la saisie invalide et revient au précédent.
      setDraft(value != null ? String(value) : "");
      return;
    }
    if (v !== value) onChange(v);
  }

  return (
    <div>
      <label className="block text-[10px] font-medium text-white/70">
        {label}
      </label>
      <input
        type="number"
        min={1}
        max={10}
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        placeholder="—"
        className="input mt-0.5"
      />
    </div>
  );
}

// Re-export pour clarté côté consumer.
export type { TaskUserMini };

// Loader2 importé pour usage potentiel (états async). Garder dans
// la barrière d'imports même si pas encore utilisé.
void Loader2;
