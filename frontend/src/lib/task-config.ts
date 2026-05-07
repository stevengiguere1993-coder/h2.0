/**
 * Configuration partagée des tâches (statut + priorité) — source
 * unique pour le Pipeline des deals (Prospection > Acquisition) et
 * le suivi des tâches d'entreprise (Gestion d'entreprises).
 *
 * Quand on change ici la couleur ou le label d'une priorité ou
 * d'un statut, les deux vues sont mises à jour ensemble. Plus de
 * dérive possible entre Pipeline et Entreprise.
 */

// ─── Statuts (les 4 colonnes du kanban) ──────────────────────────

export type TaskStatusValue =
  | "todo"           // À venir
  | "a_faire"        // À faire
  | "in_progress"    // En traitement
  | "done";          // Terminé

export const TASK_STATUS_OPTIONS: Array<{
  value: TaskStatusValue;
  label: string;
  // Pastille pleine (bg + text) — utilisée dans la pastille
  // « Statut » de la carte de tâche.
  pill: string;
  // Pastille du picker côté Pipeline (équivalent — gardé pour
  // compat de la version inline du Pipeline).
  dot: string;
}> = [
  {
    value: "todo",
    label: "À venir",
    pill: "bg-violet-500 text-white",
    dot: "bg-violet-500"
  },
  {
    value: "a_faire",
    label: "À faire",
    pill: "bg-sky-500 text-white",
    dot: "bg-sky-500"
  },
  {
    value: "in_progress",
    label: "En traitement",
    pill: "bg-amber-500 text-brand-950",
    dot: "bg-amber-500"
  },
  {
    value: "done",
    label: "Terminé",
    pill: "bg-emerald-500 text-white",
    dot: "bg-emerald-500"
  }
];

// Lookup par clé pour les écrans qui n'ont besoin que d'un label.
export const TASK_STATUS_LABEL: Record<TaskStatusValue, string> =
  Object.fromEntries(
    TASK_STATUS_OPTIONS.map((o) => [o.value, o.label])
  ) as Record<TaskStatusValue, string>;

// ─── Priorités ────────────────────────────────────────────────────

export type TaskPriorityValue =
  | "non_assigne"
  | "urgent"
  | "eleve"
  | "moyenne"
  | "faible";

export const TASK_PRIORITY_OPTIONS: Array<{
  value: TaskPriorityValue;
  label: string;
  pill: string;
}> = [
  {
    value: "non_assigne",
    label: "Non-assigné",
    pill: "bg-slate-500 text-white"
  },
  {
    value: "urgent",
    label: "Urgent ⚠️",
    pill: "bg-red-700 text-white"
  },
  {
    value: "eleve",
    label: "Élevé",
    pill: "bg-orange-500 text-white"
  },
  {
    value: "moyenne",
    label: "Moyenne",
    pill: "bg-yellow-400 text-brand-950"
  },
  {
    value: "faible",
    label: "Faible",
    pill: "bg-lime-500 text-brand-950"
  }
];

export const TASK_PRIORITY_LABEL: Record<TaskPriorityValue, string> =
  Object.fromEntries(
    TASK_PRIORITY_OPTIONS.map((o) => [o.value, o.label])
  ) as Record<TaskPriorityValue, string>;

export const TASK_PRIORITY_PILL: Record<TaskPriorityValue, string> =
  Object.fromEntries(
    TASK_PRIORITY_OPTIONS.map((o) => [o.value, o.pill])
  ) as Record<TaskPriorityValue, string>;

// Rang utilisé pour trier les tâches dans un même groupe de statut :
// urgent en haut, non-assigné en bas.
export const TASK_PRIORITY_RANK: Record<TaskPriorityValue, number> = {
  urgent: 0,
  eleve: 1,
  moyenne: 2,
  faible: 3,
  non_assigne: 4
};
