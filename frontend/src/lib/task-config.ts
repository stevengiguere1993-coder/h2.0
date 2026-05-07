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
  // Pastille pleine — fallback / compat. Style 2026 préféré : dot.
  pill: string;
  // Petit point coloré pour le rendu dot+label sur les cartes /
  // tableau (style Linear / Notion).
  dot: string;
}> = [
  {
    value: "non_assigne",
    label: "Non-assigné",
    pill: "bg-slate-500 text-white",
    dot: "bg-slate-400"
  },
  {
    value: "urgent",
    label: "Urgent",
    pill: "bg-red-700 text-white",
    dot: "bg-rose-500"
  },
  {
    value: "eleve",
    label: "Élevé",
    pill: "bg-orange-500 text-white",
    dot: "bg-orange-500"
  },
  {
    value: "moyenne",
    label: "Moyenne",
    pill: "bg-yellow-400 text-brand-950",
    dot: "bg-yellow-400"
  },
  {
    value: "faible",
    label: "Faible",
    pill: "bg-lime-500 text-brand-950",
    dot: "bg-lime-500"
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

// ─── Classement P1 → P4 dérivé du score ICE × urgence ─────────────
//
// Le score est calculé serveur-side : (impact × confiance / effort)
// × multiplicateur d'urgence (5 si en retard, 3 si ≤ 7j, 2 si ≤ 14j,
// 1.5 si ≤ 30j, 1 sinon). Cette fonction transpose le score numérique
// en pastille de priorité (P1 critique → P4 basse) avec sa couleur.

export type PScoreTier = {
  label: "P1" | "P2" | "P3" | "P4";
  // Pastille compacte « P1 · 56 » sur les cartes / tableaux. Ton
  // doux + ring coloré — lisible sur fond clair comme sombre.
  pill: string;
  // Petite barre d'accent latérale sur la carte (3 px).
  accent: string;
  description: string;
};

export function scoreToPTier(score: number | null | undefined): PScoreTier {
  if (score == null) {
    return {
      label: "P4",
      pill: "bg-slate-500/15 text-slate-300 ring-1 ring-slate-500/30",
      accent: "bg-slate-500/60",
      description: "Non évaluée"
    };
  }
  if (score >= 30) {
    return {
      label: "P1",
      pill: "bg-rose-500/15 text-rose-400 ring-1 ring-rose-500/40",
      accent: "bg-rose-500",
      description: "Critique"
    };
  }
  if (score >= 15) {
    return {
      label: "P2",
      pill: "bg-amber-500/15 text-amber-400 ring-1 ring-amber-500/40",
      accent: "bg-amber-500",
      description: "Haute"
    };
  }
  if (score >= 5) {
    return {
      label: "P3",
      pill: "bg-sky-500/15 text-sky-400 ring-1 ring-sky-500/40",
      accent: "bg-sky-500",
      description: "Normale"
    };
  }
  return {
    label: "P4",
    pill: "bg-slate-500/15 text-slate-300 ring-1 ring-slate-500/30",
    accent: "bg-slate-500/60",
    description: "Basse"
  };
}
