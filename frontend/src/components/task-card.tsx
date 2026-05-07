"use client";

import { useEffect } from "react";
import { ArrowRightLeft, Building2, StickyNote, Trash2 } from "lucide-react";

import {
  AssigneePicker,
  AutoGrowTextarea,
  DatePill,
  PillPicker,
  type TaskUserMini
} from "@/components/task-pills";
import {
  TASK_PRIORITY_OPTIONS,
  TASK_STATUS_OPTIONS,
  scoreToPTier
} from "@/lib/task-config";

/**
 * Carte de tâche partagée — utilisée à l'identique par le Pipeline
 * et le kanban d'une entreprise. Esthétique 2026 :
 *
 *   - Barre d'accent latérale (3 px) colorée selon le P-tier (P1 →
 *     rouge, P2 → ambre, P3 → bleu, P4 → gris) : repère visuel
 *     instantané de l'urgence sans imposer de couleur sur tout le
 *     fond de la carte.
 *   - Titre prominent + ligne secondaire compacte « P · score »
 *     suivie de l'immeuble.
 *   - Une seule rangée de pastilles fonctionnelles (Statut · Priorité
 *     · Personnes · Échéance), sans labels redondants — la couleur
 *     et le contenu suffisent à les identifier.
 *   - Actions (note / supprimer / déplacer) regroupées en haut à
 *     droite, en hover discret.
 */
export type TaskCardData = {
  id: number;
  title: string;
  status: string;
  priority: string;
  due_date: string | null;
  assignee_user_ids: number[];
  hasNote: boolean;
  immeubleLabels?: string[];
  score?: number | null;
};

export type TaskCardPatch = {
  title?: string;
  status?: string;
  priority?: string;
  due_date?: string | null;
  assignee_user_ids?: number[];
  immeuble_ids?: number[];
};

export function TaskCard({
  task,
  users,
  onPatch,
  onDelete,
  onOpenDetails,
  onMove,
  draggable = false,
  dragging = false,
  onDragStart,
  onDragEnd,
  footer
}: {
  task: TaskCardData;
  users: TaskUserMini[];
  onPatch: (patch: TaskCardPatch) => void;
  onDelete: (e: React.MouseEvent) => void;
  onOpenDetails: () => void;
  onMove?: () => void;
  draggable?: boolean;
  dragging?: boolean;
  onDragStart?: () => void;
  onDragEnd?: () => void;
  footer?: React.ReactNode;
}) {
  const tier = scoreToPTier(task.score);
  const hasScore = task.score != null;
  const hasImmeubles =
    task.immeubleLabels && task.immeubleLabels.length > 0;
  // Couleur de la barre d'accent latérale = couleur du statut (pas
  // du P-tier). Le P-tier reste visible via la pastille « P · score ».
  const statusOption =
    TASK_STATUS_OPTIONS.find((o) => o.value === task.status) ??
    TASK_STATUS_OPTIONS[1];

  return (
    <div
      draggable={draggable}
      onDragStart={(e) => {
        if (!draggable || !onDragStart) return;
        const tag = (e.target as HTMLElement).tagName;
        if (
          tag === "INPUT" ||
          tag === "SELECT" ||
          tag === "TEXTAREA" ||
          tag === "BUTTON"
        ) {
          e.preventDefault();
          return;
        }
        e.dataTransfer.effectAllowed = "move";
        onDragStart();
      }}
      onDragEnd={onDragEnd}
      className={`group relative rounded-xl border bg-brand-950 transition ${
        dragging
          ? "border-accent-500 opacity-60"
          : "border-brand-800 hover:border-brand-700"
      }`}
    >
      {/* Barre d'accent latérale colorée par statut. Pas
          d'overflow-hidden sur le parent (sinon les dropdowns des
          pickers étaient clippés). pointer-events-none pour ne pas
          intercepter les clics. */}
      <span
        aria-hidden
        className={`pointer-events-none absolute inset-y-0 left-0 w-[3px] rounded-l-xl ${statusOption.dot}`}
      />

      <div className="relative px-3 py-2.5 pl-[14px]">
        {/* Première ligne : titre + actions inline (compact, hover-révélé) */}
        <div className="flex items-start gap-1.5">
          <AutoGrowTextarea
            value={task.title}
            onChange={(v) => onPatch({ title: v })}
            onCommit={(v) => {
              const trimmed = v.trim();
              if (trimmed && trimmed !== task.title) {
                onPatch({ title: trimmed });
              }
            }}
            className="min-w-0 flex-1 resize-none rounded border border-transparent bg-transparent px-0.5 py-0 text-[13px] font-semibold leading-tight text-white focus:border-accent-500 focus:outline-none"
          />
          <div className="flex flex-shrink-0 items-center gap-0 opacity-60 transition group-hover:opacity-100">
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                onOpenDetails();
              }}
              className={`rounded p-1 ${
                task.hasNote
                  ? "text-amber-300 hover:bg-amber-500/15"
                  : "text-white/50 hover:bg-white/5"
              }`}
              title="Détails de la tâche"
              aria-label="Détails"
            >
              <StickyNote className="h-3 w-3" />
            </button>
            <button
              type="button"
              onClick={onDelete}
              className="rounded p-1 text-white/50 hover:bg-rose-500/15 hover:text-rose-300"
              title="Supprimer la tâche"
              aria-label="Supprimer"
            >
              <Trash2 className="h-3 w-3" />
            </button>
            {onMove ? (
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  onMove();
                }}
                className="rounded p-1 text-white/50 hover:bg-violet-500/15 hover:text-violet-300"
                title="Déplacer"
                aria-label="Déplacer"
              >
                <ArrowRightLeft className="h-3 w-3" />
              </button>
            ) : null}
          </div>
        </div>

        {/* Métadonnée : pastille P · score + immeuble (s'il y en a) */}
        <div className="mt-1 flex items-center gap-1.5 px-0.5">
          <span
            className={`inline-flex items-center gap-0.5 rounded-full px-1.5 py-0 text-[9px] font-bold leading-4 ${tier.pill}`}
            title={`${tier.label} — ${tier.description}${
              hasScore ? ` (score ${(task.score as number).toFixed(1)})` : ""
            }`}
          >
            {tier.label}
            {hasScore ? (
              <span className="opacity-90">
                · {(task.score as number).toFixed(1)}
              </span>
            ) : null}
          </span>
          {hasImmeubles ? (
            <span
              className="inline-flex min-w-0 items-center gap-1 truncate text-[10px] text-white/55"
              title={(task.immeubleLabels || []).join(", ")}
            >
              <Building2 className="h-2.5 w-2.5 flex-shrink-0" />
              <span className="truncate">
                {(task.immeubleLabels || []).join(", ")}
              </span>
            </span>
          ) : null}
        </div>

        {/* Pastilles compactes en une seule rangée. Sans labels — la
            couleur et le contenu désignent la nature de chaque champ.
            Wrap auto si le contenu déborde (ex. plusieurs avatars). */}
        <div className="mt-2 flex flex-wrap items-center gap-1">
          <PillPicker
            options={TASK_STATUS_OPTIONS.map((o) => ({
              value: o.value,
              label: o.label,
              cls: o.pill
            }))}
            value={task.status}
            onChange={(v) => onPatch({ status: v })}
            ariaLabel="Statut"
          />
          <PillPicker
            options={TASK_PRIORITY_OPTIONS.map((o) => ({
              value: o.value,
              label: o.label,
              cls: o.pill
            }))}
            value={task.priority || "non_assigne"}
            onChange={(v) => onPatch({ priority: v })}
            ariaLabel="Priorité"
          />
          <AssigneePicker
            users={users}
            values={task.assignee_user_ids || []}
            onChange={(ids) => onPatch({ assignee_user_ids: ids })}
          />
          <DatePill
            value={task.due_date}
            onChange={(d) => onPatch({ due_date: d })}
          />
        </div>

        {footer ? <div className="mt-1.5">{footer}</div> : null}
      </div>
    </div>
  );
}

/** Petit hook utilitaire — détecte un click hors d'un ref pour
 *  fermer un menu. Réutilisé dans les pickers. */
export function useClickOutside(
  ref: React.RefObject<HTMLElement>,
  onOutside: () => void
) {
  useEffect(() => {
    function handler(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        onOutside();
      }
    }
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [ref, onOutside]);
}
