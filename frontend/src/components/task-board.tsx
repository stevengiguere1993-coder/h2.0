"use client";

import { useMemo, useState } from "react";
import { Building2, Plus } from "lucide-react";

import {
  TaskCard,
  type TaskCardData,
  type TaskCardPatch
} from "@/components/task-card";
import {
  TASK_PRIORITY_OPTIONS,
  TASK_STATUS_OPTIONS,
  scoreToPTier
} from "@/lib/task-config";
import {
  AssigneePicker,
  DatePill,
  PillPicker,
  type TaskUserMini
} from "@/components/task-pills";
import {
  TaskDetailsModal,
  type TaskDetailsModalPatch
} from "@/components/task-details-modal";
import type {
  ImmeubleMini,
  ImmeubleScope
} from "@/components/immeuble-picker";

/**
 * Section « Tâches » partagée — utilisée à l'identique par la fiche
 * d'une entreprise et celle d'un deal du Pipeline. Contient :
 *
 *   - Le **titre « Tâches »** + bouton « + Nouvelle tâche ».
 *   - Le **sélecteur de tri** (personne / priorité / échéance /
 *     immeuble).
 *   - Le **toggle Tableau / Kanban**.
 *   - La **vue Tableau** : liste plate compacte (statut / priorité /
 *     personnes / échéance éditables inline, click row → ouvre la
 *     fiche).
 *   - La **vue Kanban** : 5 colonnes (todo / a_faire / in_progress /
 *     waiting / done) issues de /lib/task-config, drag-drop, création inline
 *     « + Tâche » par colonne, bouton « Déplacer » optionnel.
 *   - **La fiche détaillée** (TaskDetailsModal) — strictement
 *     identique pour tous les volets, pas de slot extras.
 *
 * Toute évolution visuelle ou fonctionnelle de la section « Tâches »
 * se fait dans ce composant — propage à tous les volets qui le
 * consomment.
 */

export type TaskBoardItem = TaskCardData & {
  position?: number;
  /** Notes / description complète — alimente la TaskDetailsModal. */
  notes?: string | null;
  /** Liste brute des immeubles liés à la tâche — alimente le picker
   *  dans la TaskDetailsModal. `immeubleLabels` reste utilisé pour
   *  l'affichage compact sur la carte. */
  immeuble_ids?: number[];
  /** Champs avancés — alimentent la TaskDetailsModal partagée. */
  departement?: string | null;
  recurrence?: string | null;
  impact?: number | null;
  confidence?: number | null;
  effort?: number | null;
  score?: number | null;
  /** Footer libre rendu sous les pastilles de la carte (utilisé par
   *  l'entreprise pour les badges score / récurrence / département). */
  footer?: React.ReactNode;
};

export type TaskBoardPatch = TaskCardPatch & {
  notes?: string | null;
  position?: number;
  departement?: string | null;
  recurrence?: string | null;
  impact?: number | null;
  confidence?: number | null;
  effort?: number | null;
};

export type ExtraColumnConfig = {
  label: string;
  width?: string;
  render: (task: TaskBoardItem) => React.ReactNode;
  /** Valeurs concrètes filtrables ; active le picker si présent. */
  filterValues?: Array<{ value: string; label: string }>;
  /** Map tâche → id de groupe (doit matcher une `filterValues.value`).
   *  Retourne null pour les tâches sans groupe. */
  getGroupId?: (task: TaskBoardItem) => string | null;
};

export function TaskBoard({
  tasks,
  users,
  immeubles,
  immeubleScope,
  onPatch,
  onDelete,
  onMove,
  onCreate,
  onImmeublesChanged,
  extraColumn,
  title = "Tâches",
  newTaskLabel = "Nouvelle tâche",
  showNewTaskButton = true
}: {
  tasks: TaskBoardItem[];
  users: TaskUserMini[];
  immeubles: ImmeubleMini[];
  /** Scope du catalogue d'immeubles : entreprise_id ou deal_id. */
  immeubleScope?: ImmeubleScope;
  /** Patch d'une tâche — appelé pour toute édition (statut, priorité,
   *  échéance, personnes, immeubles, position, notes, titre). */
  onPatch: (taskId: number, patch: TaskBoardPatch) => void;
  onDelete: (taskId: number) => void;
  /** Bouton « Déplacer » sur la carte. Optionnel. */
  onMove?: (taskId: number) => void;
  /** Création de tâche depuis le bouton « + Nouvelle tâche » en haut
   *  ou « + Tâche » au pied d'une colonne du kanban. La page parent
   *  fait l'appel API et retourne l'id créé pour qu'on puisse ouvrir
   *  immédiatement la fiche détaillée. */
  onCreate: (
    status: string,
    name: string
  ) => Promise<number | null> | number | null;
  /** Re-fetch du catalogue d'immeubles (après ajout / retrait via le
   *  bouton « Gérer » du picker dans la modal). */
  onImmeublesChanged?: () => void;
  /** Colonne optionnelle insérée entre « Tâche » et « Immeuble »
   *  dans la vue Tableau. Utilisé par la vue cross-entreprise pour
   *  afficher l'entreprise (ou le deal) propriétaire de chaque
   *  tâche. Si `filterValues` + `getGroupId` sont fournis, un
   *  sélecteur de filtre/tri est ajouté à la barre d'outils. */
  extraColumn?: ExtraColumnConfig;
  title?: string;
  newTaskLabel?: string;
  showNewTaskButton?: boolean;
}) {
  const [view, setView] = useState<"kanban" | "list">("kanban");
  const [detailTaskId, setDetailTaskId] = useState<number | null>(null);
  const [criteria, setCriteria] = useState<
    Record<CriterionKey, CriterionState>
  >(DEFAULT_FILTERS);

  // Si l'utilisateur passe un critère sur « Trier », s'assure qu'aucun
  // autre n'est déjà sur « Trier » (un seul tri actif à la fois).
  function setCriterion(key: CriterionKey, s: CriterionState) {
    setCriteria((prev) => {
      const next = { ...prev, [key]: s };
      if (s.kind === "sort") {
        for (const k of Object.keys(next) as CriterionKey[]) {
          if (k !== key && next[k].kind === "sort") {
            next[k] = { kind: "all" };
          }
        }
      }
      return next;
    });
  }

  async function handleNewTask() {
    // Crée une tâche placeholder dans la première colonne (« À faire »)
    // puis ouvre directement sa fiche pour que l'utilisateur puisse
    // lui donner un vrai nom + remplir les autres champs.
    const id = await onCreate("a_faire", "Nouvelle tâche");
    if (typeof id === "number") setDetailTaskId(id);
  }

  async function handleColumnCreate(status: string, name: string) {
    await onCreate(status, name);
  }

  const sortedTasks = useMemo(() => {
    const filtered = applyFilters(tasks, criteria, extraColumn);
    return sortTasks(filtered, criteria, users, immeubles, extraColumn);
  }, [tasks, criteria, users, immeubles, extraColumn]);

  const sortActive = (Object.values(criteria) as CriterionState[]).some(
    (c) => c.kind === "sort"
  );

  const statusOptions = useMemo(
    () =>
      TASK_STATUS_OPTIONS.map((s) => ({
        value: s.value,
        label: s.label
      })),
    []
  );
  const personOptions = useMemo(
    () => [
      { value: "none", label: "— Non assigné" },
      ...users.map((u) => ({
        value: String(u.id),
        label:
          [u.first_name, u.last_name].filter(Boolean).join(" ").trim() ||
          u.email ||
          `User #${u.id}`
      }))
    ],
    [users]
  );
  const priorityOptions = useMemo(
    () =>
      [
        { value: "urgent", label: "Urgent" },
        { value: "eleve", label: "Élevé" },
        { value: "moyenne", label: "Moyenne" },
        { value: "faible", label: "Faible" },
        { value: "non_assigne", label: "Non-assigné" }
      ],
    []
  );
  const immeubleOptions = useMemo(
    () => [
      { value: "none", label: "— Aucun" },
      ...immeubles.map((i) => ({ value: String(i.id), label: i.name }))
    ],
    [immeubles]
  );

  const detailTask =
    detailTaskId != null
      ? tasks.find((t) => t.id === detailTaskId) || null
      : null;

  return (
    <div className="mt-6">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-3">
          <h2 className="text-sm font-semibold uppercase tracking-wider text-white/50">
            {title}
          </h2>
          {showNewTaskButton ? (
            <button
              type="button"
              onClick={() => void handleNewTask()}
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
            className={`rounded-md px-3 py-1.5 text-xs font-semibold transition ${
              view === "list"
                ? "bg-violet-400 text-brand-950 shadow"
                : "border border-brand-700 bg-brand-950/40 text-white hover:bg-brand-950/70"
            }`}
          >
            Tableau
          </button>
          <button
            type="button"
            onClick={() => setView("kanban")}
            className={`ml-0.5 rounded-md px-3 py-1.5 text-xs font-semibold transition ${
              view === "kanban"
                ? "bg-violet-400 text-brand-950 shadow"
                : "border border-brand-700 bg-brand-950/40 text-white hover:bg-brand-950/70"
            }`}
          >
            Kanban
          </button>
        </div>
      </div>

      <div className="mb-4 flex flex-wrap items-center gap-3 rounded-lg border border-brand-800 bg-brand-900/40 px-3 py-2">
        <CriterionPicker
          label="Statut"
          state={criteria.status}
          onChange={(s) => setCriterion("status", s)}
          values={statusOptions}
        />
        <CriterionPicker
          label="Personne"
          state={criteria.person}
          onChange={(s) => setCriterion("person", s)}
          values={personOptions}
        />
        <CriterionPicker
          label="Priorité"
          state={criteria.priority}
          onChange={(s) => setCriterion("priority", s)}
          values={priorityOptions}
        />
        <CriterionPicker
          label="Échéance"
          state={criteria.due_date}
          onChange={(s) => setCriterion("due_date", s)}
          values={DUE_FILTER_OPTIONS}
        />
        <CriterionPicker
          label="Immeuble"
          state={criteria.immeuble}
          onChange={(s) => setCriterion("immeuble", s)}
          values={immeubleOptions}
        />
        {extraColumn?.filterValues && extraColumn.filterValues.length > 0 ? (
          <CriterionPicker
            label={extraColumn.label}
            state={criteria.extra}
            onChange={(s) => setCriterion("extra", s)}
            values={extraColumn.filterValues}
          />
        ) : null}
      </div>

      {view === "kanban" ? (
        <KanbanView
          tasks={sortedTasks}
          users={users}
          onPatch={onPatch}
          onDelete={onDelete}
          onOpenDetails={(id) => setDetailTaskId(id)}
          onMove={onMove}
          onCreate={(s, n) => void handleColumnCreate(s, n)}
          sorted={sortActive}
        />
      ) : (
        <TaskListView
          tasks={sortedTasks}
          users={users}
          onPatch={onPatch}
          onOpenDetails={(id) => setDetailTaskId(id)}
          extraColumn={extraColumn}
        />
      )}

      {detailTask ? (
        <TaskDetailsModal
          task={{
            id: detailTask.id,
            title: detailTask.title,
            notes: detailTask.notes ?? "",
            status: detailTask.status,
            priority: detailTask.priority || "non_assigne",
            due_date: detailTask.due_date,
            assignee_user_ids: detailTask.assignee_user_ids || [],
            immeuble_ids: detailTask.immeuble_ids || [],
            departement: detailTask.departement ?? null,
            recurrence: detailTask.recurrence ?? null,
            impact: detailTask.impact ?? null,
            confidence: detailTask.confidence ?? null,
            effort: detailTask.effort ?? null,
            score: detailTask.score ?? null
          }}
          users={users}
          immeubles={immeubles}
          immeubleScope={immeubleScope}
          onImmeublesChanged={onImmeublesChanged}
          onClose={() => setDetailTaskId(null)}
          onPatch={(patch: TaskDetailsModalPatch) => {
            onPatch(detailTask.id, patch as TaskBoardPatch);
          }}
        />
      ) : null}
    </div>
  );
}

// ─── Tri + filtres ─────────────────────────────────────────────────
// Pour chaque critère (Personne / Priorité / Échéance / Immeuble) un
// seul sélecteur expose à la fois :
//   - « Tous / Toutes »  → ne fait rien
//   - « Trier »          → utilise ce critère pour trier (un seul à
//                          la fois)
//   - une valeur précise → filtre la liste à cette valeur (cumulatif
//                          avec les autres critères filtrés)

type CriterionKey =
  | "status"
  | "person"
  | "priority"
  | "due_date"
  | "immeuble"
  | "extra";

type CriterionState =
  | { kind: "all" }
  | { kind: "sort" }
  | { kind: "filter"; value: string };

const DEFAULT_FILTERS: Record<CriterionKey, CriterionState> = {
  status: { kind: "all" },
  person: { kind: "all" },
  priority: { kind: "all" },
  due_date: { kind: "all" },
  immeuble: { kind: "all" },
  extra: { kind: "all" }
};

const PRIORITY_RANK: Record<string, number> = {
  urgent: 0,
  eleve: 1,
  moyenne: 2,
  faible: 3,
  non_assigne: 4
};

const DUE_FILTER_OPTIONS: Array<{ value: string; label: string }> = [
  { value: "overdue", label: "En retard" },
  { value: "today", label: "Aujourd'hui" },
  { value: "this_week", label: "Cette semaine" },
  { value: "no_date", label: "Sans échéance" }
];

function CriterionPicker({
  label,
  state,
  onChange,
  values
}: {
  label: string;
  state: CriterionState;
  onChange: (s: CriterionState) => void;
  /** Valeurs concrètes filtrables (label affiché, value envoyée). */
  values: Array<{ value: string; label: string }>;
}) {
  // Encode l'état sur une seule clé string pour le <select>.
  const current =
    state.kind === "all"
      ? "__all"
      : state.kind === "sort"
        ? "__sort"
        : `v:${state.value}`;
  return (
    <label className="inline-flex items-center gap-1.5 text-xs text-white/60">
      <span>{label}&nbsp;:</span>
      <select
        value={current}
        onChange={(e) => {
          const v = e.target.value;
          if (v === "__all") onChange({ kind: "all" });
          else if (v === "__sort") onChange({ kind: "sort" });
          else onChange({ kind: "filter", value: v.slice(2) });
        }}
        className="rounded-md border border-brand-800 bg-brand-900 px-2 py-1 text-xs text-white focus:border-accent-500 focus:outline-none"
      >
        <option value="__all">Tous</option>
        <option value="__sort">Trier</option>
        <option disabled value="__sep">
          ──────────
        </option>
        {values.map((o) => (
          <option key={o.value} value={`v:${o.value}`}>
            {o.label}
          </option>
        ))}
      </select>
    </label>
  );
}

function isSameDate(a: string, b: Date): boolean {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(a);
  if (!m) return false;
  return (
    Number(m[1]) === b.getFullYear() &&
    Number(m[2]) === b.getMonth() + 1 &&
    Number(m[3]) === b.getDate()
  );
}

function applyFilters(
  tasks: TaskBoardItem[],
  filters: Record<CriterionKey, CriterionState>,
  extraColumn?: ExtraColumnConfig
): TaskBoardItem[] {
  const today = new Date();
  const inAWeek = new Date();
  inAWeek.setDate(today.getDate() + 7);

  return tasks.filter((t) => {
    // Statut
    const fs = filters.status;
    if (fs.kind === "filter") {
      if (t.status !== fs.value) return false;
    }
    // Personne
    const fp = filters.person;
    if (fp.kind === "filter") {
      const ids = t.assignee_user_ids || [];
      if (fp.value === "none" ? ids.length > 0 : !ids.includes(Number(fp.value)))
        return false;
    }
    // Priorité
    const fpr = filters.priority;
    if (fpr.kind === "filter") {
      if ((t.priority || "non_assigne") !== fpr.value) return false;
    }
    // Échéance — buckets temporels.
    const fd = filters.due_date;
    if (fd.kind === "filter") {
      const d = t.due_date;
      if (fd.value === "no_date") {
        if (d) return false;
      } else if (!d) {
        return false;
      } else {
        const due = new Date(d);
        if (fd.value === "overdue") {
          if (due >= new Date(today.toDateString())) return false;
        } else if (fd.value === "today") {
          if (!isSameDate(d, today)) return false;
        } else if (fd.value === "this_week") {
          if (due < new Date(today.toDateString()) || due > inAWeek)
            return false;
        }
      }
    }
    // Immeuble
    const fi = filters.immeuble;
    if (fi.kind === "filter") {
      const ids = t.immeuble_ids || [];
      if (fi.value === "none" ? ids.length > 0 : !ids.includes(Number(fi.value)))
        return false;
    }
    // Colonne extra (ex. Entreprise / Deal en vue cross-volet)
    const fx = filters.extra;
    if (fx.kind === "filter" && extraColumn?.getGroupId) {
      const id = extraColumn.getGroupId(t);
      if (fx.value === "none" ? id != null : id !== fx.value) return false;
    }
    return true;
  });
}

function sortTasks(
  tasks: TaskBoardItem[],
  filters: Record<CriterionKey, CriterionState>,
  users: TaskUserMini[],
  immeubles: ImmeubleMini[],
  extraColumn?: ExtraColumnConfig
): TaskBoardItem[] {
  const sortKey = (Object.keys(filters) as CriterionKey[]).find(
    (k) => filters[k].kind === "sort"
  );
  if (!sortKey) return tasks;

  const userName = new Map(
    users.map(
      (u) =>
        [
          u.id,
          (u.last_name || u.first_name || u.email || "").toLowerCase()
        ] as const
    )
  );
  const immeubleName = new Map(
    immeubles.map((i) => [i.id, i.name.toLowerCase()] as const)
  );

  // Rang des statuts pour le tri (todo → done en flux normal).
  const statusRank: Record<string, number> = {
    todo: 0,
    a_faire: 1,
    in_progress: 2,
    waiting: 3,
    done: 4
  };

  function keyOf(t: TaskBoardItem): string | number {
    if (sortKey === "status") {
      return statusRank[t.status] ?? 99;
    }
    if (sortKey === "person") {
      const id = (t.assignee_user_ids || [])[0];
      return id != null ? userName.get(id) ?? "zzz" : "zzz";
    }
    if (sortKey === "priority") {
      return PRIORITY_RANK[t.priority] ?? 99;
    }
    if (sortKey === "due_date") {
      return t.due_date || "9999-99-99";
    }
    if (sortKey === "immeuble") {
      const id = (t.immeuble_ids || [])[0];
      return id != null ? immeubleName.get(id) ?? "zzz" : "zzz";
    }
    if (sortKey === "extra" && extraColumn?.getGroupId) {
      const id = extraColumn.getGroupId(t);
      if (id == null) return "zzz";
      // Tri sur le label affiché (plus naturel pour l'utilisateur).
      const found = (extraColumn.filterValues || []).find(
        (v) => v.value === id
      );
      return (found?.label || id).toLowerCase();
    }
    return 0;
  }

  return [...tasks].sort((a, b) => {
    const ka = keyOf(a);
    const kb = keyOf(b);
    if (ka < kb) return -1;
    if (ka > kb) return 1;
    return 0;
  });
}

// ─── Kanban ────────────────────────────────────────────────────────

function KanbanView({
  tasks,
  users,
  onPatch,
  onDelete,
  onOpenDetails,
  onMove,
  onCreate,
  sorted
}: {
  tasks: TaskBoardItem[];
  users: TaskUserMini[];
  onPatch: (taskId: number, patch: TaskBoardPatch) => void;
  onDelete: (taskId: number) => void;
  onOpenDetails: (taskId: number) => void;
  onMove?: (taskId: number) => void;
  onCreate: (status: string, name: string) => void;
  /** Si vrai, l'ordre du tableau a déjà été imposé par le parent
   *  (tri utilisateur) — on n'écrase pas avec un tri par position. */
  sorted: boolean;
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
    if (!sorted) {
      for (const k of Object.keys(map)) {
        map[k].sort(
          (a, b) => (a.position ?? 0) - (b.position ?? 0)
        );
      }
    }
    return map;
  }, [tasks, sorted]);

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
  onOpenDetails,
  extraColumn
}: {
  tasks: TaskBoardItem[];
  users: TaskUserMini[];
  onPatch: (taskId: number, patch: TaskBoardPatch) => void;
  onOpenDetails: (taskId: number) => void;
  /** Colonne optionnelle insérée entre « Tâche » et « Immeuble »
   *  pour des contextes spécifiques (ex. la vue cross-entreprise
   *  affiche le nom de l'entreprise propriétaire). */
  extraColumn?: ExtraColumnConfig;
}) {
  // Le parent (TaskBoard) trie déjà selon les critères choisis ; on
  // n'écrase pas l'ordre. Si aucun tri actif, l'ordre source est la
  // position.
  const [dragId, setDragId] = useState<number | null>(null);
  const [hoverId, setHoverId] = useState<number | null>(null);

  if (tasks.length === 0) {
    return (
      <div className="rounded-xl border border-brand-800 bg-brand-900/60 px-6 py-12 text-center">
        <p className="text-sm text-white/50">Aucune tâche</p>
      </div>
    );
  }

  function handleDrop(targetId: number) {
    const id = dragId;
    setDragId(null);
    setHoverId(null);
    if (id == null || id === targetId) return;
    const target = tasks.find((t) => t.id === targetId);
    if (!target) return;
    // Insère la tâche déplacée juste avant la cible : nouvelle
    // position = position cible − 1. Le backend va trier par
    // position et on évite ainsi d'avoir à renuméroter en cascade.
    const newPos = (target.position ?? 0) - 1;
    onPatch(id, { position: newPos });
  }

  return (
    <div className="overflow-x-auto rounded-xl border border-brand-800 bg-brand-900/40">
      <table className="w-full min-w-[480px] text-[13px]">
        <thead>
          <tr
            className="text-[10px] font-semibold uppercase tracking-wider text-white/40"
            style={{ borderBottom: "1px solid rgba(100,116,139,0.35)" }}
          >
            <th className="w-[80px] px-2 py-3 text-left sm:w-[88px] sm:px-3">P · Score</th>
            <th className="px-3 py-3 text-left sm:px-4">Tâche</th>
            {extraColumn ? (
              <th
                className="hidden px-3 py-3 text-center sm:table-cell"
                style={
                  extraColumn.width ? { width: extraColumn.width } : undefined
                }
              >
                {extraColumn.label}
              </th>
            ) : null}
            <th className="hidden w-[180px] px-3 py-3 text-center md:table-cell">Immeuble</th>
            <th className="w-[110px] px-2 py-3 text-center sm:w-[120px] sm:px-3">Statut</th>
            <th className="hidden w-[110px] px-3 py-3 text-center md:table-cell">Priorité</th>
            <th className="hidden w-[120px] px-3 py-3 text-center md:table-cell">Personnes</th>
            <th className="hidden w-[110px] px-3 py-3 text-center sm:table-cell">Échéance</th>
          </tr>
        </thead>
        <tbody>
          {tasks.map((t) => {
            const dragging = dragId === t.id;
            const hover = hoverId === t.id && dragId !== null && dragId !== t.id;
            return (
              <tr
                key={t.id}
                draggable
                onDragStart={(e) => {
                  // Bloque le drag s'il vient d'un widget interactif.
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
                  setDragId(t.id);
                }}
                onDragOver={(e) => {
                  e.preventDefault();
                  if (dragId !== null) setHoverId(t.id);
                }}
                onDragLeave={() =>
                  setHoverId((id) => (id === t.id ? null : id))
                }
                onDrop={(e) => {
                  e.preventDefault();
                  handleDrop(t.id);
                }}
                onDragEnd={() => {
                  setDragId(null);
                  setHoverId(null);
                }}
                onClick={() => onOpenDetails(t.id)}
                className={`relative cursor-pointer transition ${
                  dragging
                    ? "opacity-50"
                    : hover
                      ? "bg-violet-500/10"
                      : "hover:bg-white/[0.03]"
                }`}
                style={{
                  borderBottom: "1px solid rgba(100,116,139,0.18)"
                }}
              >
                <td className="px-2 py-2.5 sm:px-3">
                  {(() => {
                    const tier = scoreToPTier(t.score);
                    const hasScore = t.score != null;
                    return (
                      <span
                        className={`relative inline-flex items-center gap-1 overflow-hidden rounded-full pl-2.5 pr-2 py-0.5 text-[10px] font-bold ${tier.pill}`}
                        title={`${tier.label} — ${tier.description}${
                          hasScore
                            ? ` (score ${(t.score as number).toFixed(1)})`
                            : ""
                        }`}
                      >
                        <span
                          aria-hidden
                          className={`absolute inset-y-0 left-0 w-[3px] ${tier.accent}`}
                        />
                        {tier.label}
                        {hasScore ? (
                          <span className="opacity-90">
                            · {(t.score as number).toFixed(1)}
                          </span>
                        ) : null}
                      </span>
                    );
                  })()}
                </td>
                <td className="max-w-[420px] px-3 py-2.5 sm:px-4">
                  <p className="truncate font-medium leading-tight text-white">
                    {t.title}
                  </p>
                  {t.footer ? (
                    <div className="mt-1">{t.footer}</div>
                  ) : null}
                </td>
                {extraColumn ? (
                  <td className="hidden px-3 py-2.5 text-center sm:table-cell">
                    {extraColumn.render(t)}
                  </td>
                ) : null}
                <td className="hidden px-3 py-2.5 text-center md:table-cell">
                  {t.immeubleLabels && t.immeubleLabels.length > 0 ? (
                    <span
                      className="inline-flex max-w-full items-center gap-1 truncate text-[11px] text-white/70"
                      title={t.immeubleLabels.join(", ")}
                    >
                      <Building2 className="h-3 w-3 flex-shrink-0 text-emerald-400/80" />
                      <span className="truncate">
                        {t.immeubleLabels.join(", ")}
                      </span>
                    </span>
                  ) : (
                    <span className="text-[11px] text-white/25">—</span>
                  )}
                </td>
                <td
                  className="px-2 py-2.5 text-center sm:px-3"
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
                  className="hidden px-3 py-2.5 text-center md:table-cell"
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
                  className="hidden px-3 py-2.5 text-center md:table-cell"
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
                  className="hidden px-3 py-2.5 text-center sm:table-cell"
                  onClick={(e) => e.stopPropagation()}
                >
                  <DatePill
                    value={t.due_date}
                    onChange={(d) => onPatch(t.id, { due_date: d })}
                  />
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
