"use client";

import { useEffect } from "react";
import { ArrowRightLeft, StickyNote, Trash2 } from "lucide-react";

import {
  AssigneePicker,
  AutoGrowTextarea,
  DatePill,
  PillField,
  PillPicker,
  type TaskUserMini
} from "@/components/task-pills";
import {
  TASK_PRIORITY_OPTIONS,
  TASK_STATUS_OPTIONS
} from "@/lib/task-config";

/**
 * Carte de tâche partagée — utilisée par le Pipeline des deals
 * (Prospection > Acquisition > pipeline > deal > tâches) ET par
 * le kanban d'une entreprise (Gestion d'entreprises). Le rendu est
 * identique partout : title + boutons (note/poubelle/déplacer) +
 * 4 PillFields (Personnes / Statut / Priorité / Échéance).
 *
 * Les données sources peuvent avoir des shapes différents (Pipeline
 * = `name + notes`, Entreprise = `title + description`). On accepte
 * une shape neutre `TaskCardData` qui agrège les champs communs ;
 * chaque page fait l'adaptation au moment de passer la tâche.
 */
export type TaskCardData = {
  id: number;
  title: string;
  status: string;
  priority: string;
  due_date: string | null;
  assignee_user_ids: number[];
  // True si la tâche a une note/description non vide — pour
  // teinter l'icône note en jaune comme indicateur visuel.
  hasNote: boolean;
  // Libellés des immeubles liés à la tâche — affichés sous le titre
  // (laissé vide si aucun immeuble lié).
  immeubleLabels?: string[];
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
  /** Click sur l'icône bloc-note → ouvre la fiche détaillée. */
  onOpenDetails: () => void;
  /** Optionnel — bouton « Déplacer » sous la poubelle. Affiché si
   *  fourni (Entreprise oui, Pipeline non par défaut). */
  onMove?: () => void;
  draggable?: boolean;
  dragging?: boolean;
  onDragStart?: () => void;
  onDragEnd?: () => void;
  /** Optionnel — petit footer ajouté en bas (score / récurrence / etc.) */
  footer?: React.ReactNode;
}) {
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
      className={`group block rounded-lg border bg-brand-950 p-2 ${
        dragging ? "border-accent-500 opacity-60" : "border-brand-800"
      }`}
    >
      {/* Première ligne : titre éditable + boutons empilés */}
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
          // Style « heading » : semibold, pas de bordure visible au
          // repos, focus accent au clic. Identique entre Pipeline
          // et Entreprise.
          className="min-w-0 flex-1 resize-none rounded border border-transparent bg-transparent px-1 py-0.5 text-sm font-semibold text-white focus:border-accent-500 focus:outline-none"
        />
        <div className="flex flex-shrink-0 flex-col items-center gap-0.5">
          {/* Note/Détails — ouvre la fiche complète. L'icône passe
              en jaune si la tâche a déjà une note. */}
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              onOpenDetails();
            }}
            className={`rounded p-1 ${
              task.hasNote
                ? "text-amber-300 hover:bg-amber-500/15"
                : "text-white/40 hover:bg-white/5"
            }`}
            title="Détails de la tâche"
            aria-label="Détails"
          >
            <StickyNote className="h-3 w-3" />
          </button>
          <button
            type="button"
            onClick={onDelete}
            className="rounded p-1 text-white/40 hover:bg-rose-500/15 hover:text-rose-300"
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
              className="rounded p-1 text-white/40 hover:bg-violet-500/15 hover:text-violet-300"
              title="Déplacer"
              aria-label="Déplacer"
            >
              <ArrowRightLeft className="h-3 w-3" />
            </button>
          ) : null}
        </div>
      </div>

      {/* Immeuble(s) lié(s) — affichés en clair sous le titre, juste
          avant les pastilles. text-white est inversé en quasi-noir
          dans le thème portail clair (cf. globals.css), donc le texte
          se lit naturellement dans les deux thèmes. Rien n'est rendu
          si la tâche n'est rattachée à aucun immeuble. */}
      {task.immeubleLabels && task.immeubleLabels.length > 0 ? (
        <p className="mt-1 px-1 text-[11px] font-medium text-white/85">
          {task.immeubleLabels.join(", ")}
        </p>
      ) : null}

      {/* 4 pastilles : Personnes / Statut / Priorité / Échéance.
          Identique partout — les options viennent du module partagé
          /lib/task-config. */}
      <div className="mt-1.5 grid grid-cols-2 gap-1.5">
        <PillField label="Personnes">
          <AssigneePicker
            users={users}
            values={task.assignee_user_ids || []}
            onChange={(ids) => onPatch({ assignee_user_ids: ids })}
          />
        </PillField>
        <PillField label="Statut">
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
        </PillField>
        <PillField label="Priorité">
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
        </PillField>
        <PillField label="Échéance">
          <DatePill
            value={task.due_date}
            onChange={(d) => onPatch({ due_date: d })}
          />
        </PillField>
      </div>

      {footer ? <div className="mt-2">{footer}</div> : null}
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

