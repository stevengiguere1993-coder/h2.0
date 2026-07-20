"use client";

import {
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState
} from "react";
import { usePathname } from "next/navigation";
import {
  Building2,
  Calendar,
  Check,
  ChevronDown,
  ChevronRight,
  ChevronUp,
  GripVertical,
  Plus,
  Search
} from "lucide-react";

import {
  TaskCard,
  type TaskCardData,
  type TaskCardPatch
} from "@/components/task-card";
import { useConfirm } from "@/components/confirm-dialog";
import {
  TASK_PRIORITY_OPTIONS,
  TASK_STATUS_OPTIONS,
  scoreToPTier
} from "@/lib/task-config";
import {
  AssigneePicker,
  DatePill,
  PillPicker,
  UserInitialDot,
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
  /** Horodatage de création (ISO) — utilisé pour trier la vue Cartes
   *  par ordre de création (la plus récente en haut). */
  created_at?: string | null;
  /** Horodatage de complétion (ISO) — trie les cartes terminées (dernière
   *  cochée en haut). */
  completed_at?: string | null;
  /** Position DB réelle (≠ `position` qui est dérivé du score pour le
   *  kanban). Porte l'ordre manuel du drag & drop de la vue Cartes. */
  dbPosition?: number | null;
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
  showNewTaskButton = true,
  headerSlot,
  defaultView = "kanban",
  currentUserId
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
  /** Bouton(s) custom rendus à droite de « Nouvelle tâche » dans
   *  le header de la section. Utilisé par la fiche entreprise pour
   *  afficher un raccourci vers les modèles récurrents. */
  headerSlot?: React.ReactNode;
  /** Vue par défaut. « cartes » = vue façon Google Keep (Mes tâches). */
  defaultView?: "kanban" | "list" | "cartes";
  /** Utilisateur courant — pour auto-assigner les notes créées en vue
   *  Cartes (ajout zéro friction). */
  currentUserId?: number | null;
}) {
  const [view, setView] = useState<"kanban" | "list" | "cartes">(defaultView);
  // La vue « Cartes » (façon Keep) est réservée au mobile. Sur desktop on
  // n'affiche pas le bouton et on retombe sur Kanban (la vue prioritaire),
  // même si defaultView="cartes" (ex. raccourci « Mes tâches »).
  const [isMobile, setIsMobile] = useState(false);
  useEffect(() => {
    const mq = window.matchMedia("(max-width: 768px)");
    const sync = () => setIsMobile(mq.matches);
    sync();
    mq.addEventListener("change", sync);
    return () => mq.removeEventListener("change", sync);
  }, []);
  const effectiveView =
    view === "cartes" && !isMobile ? "kanban" : view;
  const [detailTaskId, setDetailTaskId] = useState<number | null>(null);
  // Recherche libre (titre / notes / immeuble / département) — filtre
  // textuel additif aux pickers.
  const [search, setSearch] = useState("");
  const [criteria, setCriteria] = useState<
    Record<CriterionKey, CriterionState>
  >(DEFAULT_FILTERS);

  // Si l'utilisateur passe un critère sur « Trier », s'assure qu'aucun
  // autre n'est déjà sur « Trier » (un seul tri actif à la fois).
  function setCriterion(key: CriterionKey, s: CriterionState) {
    setCriteria((prev) => {
      const next = { ...prev, [key]: s };
      if (s.kind === "sort" || s.kind === "sort_asc") {
        for (const k of Object.keys(next) as CriterionKey[]) {
          const kind = next[k].kind;
          if (k !== key && (kind === "sort" || kind === "sort_asc")) {
            next[k] = { kind: "all" };
          }
        }
      }
      return next;
    });
  }

  const confirm = useConfirm();
  // Demande une confirmation avant toute suppression de tâche
  // (kanban + tableau). Centralisé ici pour que tous les parents
  // (entreprises, prospection, vue cross-volet) en bénéficient
  // sans dupliquer la logique. Retient le titre pour l'afficher.
  async function handleDeleteWithConfirm(taskId: number) {
    const t = tasks.find((x) => x.id === taskId);
    const title = t?.title?.trim();
    const ok = await confirm({
      title: title
        ? `Supprimer la tâche « ${title} » ?`
        : "Supprimer cette tâche ?",
      description: "Cette action est définitive.",
      confirmLabel: "Supprimer",
      destructive: true
    });
    if (!ok) return;
    onDelete(taskId);
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
    let filtered = applyFilters(tasks, criteria, extraColumn);
    const q = search.trim().toLowerCase();
    if (q) {
      filtered = filtered.filter((t) => {
        return (
          t.title.toLowerCase().includes(q) ||
          (t.notes || "").toLowerCase().includes(q) ||
          (t.departement || "").toLowerCase().includes(q) ||
          (t.immeubleLabels || []).some((l) =>
            l.toLowerCase().includes(q)
          )
        );
      });
    }
    return sortTasks(filtered, criteria, users, immeubles, extraColumn);
  }, [tasks, criteria, users, immeubles, extraColumn, search]);

  const sortActive = (Object.values(criteria) as CriterionState[]).some(
    (c) => c.kind === "sort" || c.kind === "sort_asc"
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
          {showNewTaskButton && effectiveView !== "cartes" ? (
            <button
              type="button"
              onClick={() => void handleNewTask()}
              className="btn-accent btn-sm inline-flex items-center"
            >
              <Plus className="mr-1 h-3.5 w-3.5" />
              {newTaskLabel}
            </button>
          ) : null}
          {effectiveView !== "cartes" ? headerSlot : null}
        </div>
        <div className="inline-flex rounded-lg border border-brand-800 bg-brand-900 p-0.5">
          {isMobile ? (
            <button
              type="button"
              onClick={() => setView("cartes")}
              className={`mr-0.5 rounded-md px-3 py-1.5 text-xs font-semibold transition ${
                view === "cartes"
                  ? "bg-accent-500 text-brand-950 shadow"
                  : "border border-brand-700 bg-brand-950/40 text-white hover:bg-brand-950/70"
              }`}
            >
              Cartes
            </button>
          ) : null}
          <button
            type="button"
            onClick={() => setView("list")}
            className={`ml-0.5 rounded-md px-3 py-1.5 text-xs font-semibold transition ${
              view === "list"
                ? "bg-accent-500 text-brand-950 shadow"
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
                ? "bg-accent-500 text-brand-950 shadow"
                : "border border-brand-700 bg-brand-950/40 text-white hover:bg-brand-950/70"
            }`}
          >
            Kanban
          </button>
        </div>
      </div>

      {effectiveView === "cartes" ? null : (
      <div className="mb-4 flex flex-wrap items-center gap-3 rounded-lg border border-brand-800 bg-brand-900/40 px-3 py-2">
        <label className="relative inline-flex items-center">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-white/40" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Rechercher…"
            className="w-56 rounded-md border border-brand-800 bg-brand-900 py-1 pl-8 pr-2 text-xs text-white placeholder:text-white/30 focus:border-accent-500 focus:outline-none"
          />
        </label>
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
        <CriterionPicker
          label="Création"
          state={criteria.created}
          onChange={(s) => setCriterion("created", s)}
          values={[]}
          sortLabel="Plus récente en haut"
          sortAscLabel="La plus vieille en haut"
        />
      </div>
      )}

      {effectiveView === "cartes" ? (
        <TaskKeepView
          tasks={sortedTasks}
          users={users}
          onPatch={onPatch}
          onOpenDetails={(id) => setDetailTaskId(id)}
          onCreate={onCreate}
          currentUserId={currentUserId ?? null}
        />
      ) : effectiveView === "kanban" ? (
        <KanbanView
          tasks={sortedTasks}
          users={users}
          onPatch={onPatch}
          onDelete={(id) => void handleDeleteWithConfirm(id)}
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
  | "extra"
  | "created";

type CriterionState =
  | { kind: "all" }
  | { kind: "sort" }
  // Tri inversé (ex. Création : « la plus vieille en haut ») — offert
  // seulement par les pickers qui passent `sortAscLabel`.
  | { kind: "sort_asc" }
  | { kind: "filter"; value: string };

const DEFAULT_FILTERS: Record<CriterionKey, CriterionState> = {
  status: { kind: "all" },
  person: { kind: "all" },
  priority: { kind: "all" },
  due_date: { kind: "all" },
  immeuble: { kind: "all" },
  extra: { kind: "all" },
  created: { kind: "all" }
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
  values,
  sortLabel,
  sortAscLabel
}: {
  label: string;
  state: CriterionState;
  onChange: (s: CriterionState) => void;
  /** Valeurs concrètes filtrables (label affiché, value envoyée). */
  values: Array<{ value: string; label: string }>;
  /** Libellé de l'option de tri (défaut « Trier »). */
  sortLabel?: string;
  /** Si fourni, ajoute l'option de tri INVERSÉ (ex. « La plus vieille
   *  en haut »). */
  sortAscLabel?: string;
}) {
  // Encode l'état sur une seule clé string pour le <select>.
  const current =
    state.kind === "all"
      ? "__all"
      : state.kind === "sort"
        ? "__sort"
        : state.kind === "sort_asc"
          ? "__sort_asc"
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
          else if (v === "__sort_asc") onChange({ kind: "sort_asc" });
          else onChange({ kind: "filter", value: v.slice(2) });
        }}
        className="rounded-md border border-brand-800 bg-brand-900 px-2 py-1 text-xs text-white focus:border-accent-500 focus:outline-none"
      >
        <option value="__all">Tous</option>
        <option value="__sort">{sortLabel || "Trier"}</option>
        {sortAscLabel ? (
          <option value="__sort_asc">{sortAscLabel}</option>
        ) : null}
        {values.length > 0 ? (
          <option disabled value="__sep">
            ──────────
          </option>
        ) : null}
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
    (k) =>
      filters[k].kind === "sort" || filters[k].kind === "sort_asc"
  );
  if (!sortKey) return tasks;
  const ascending = filters[sortKey].kind === "sort_asc";

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
    if (sortKey === "created") {
      if (ascending) {
        // La plus VIEILLE en haut ; sans date de création → en bas.
        return t.created_at ? Date.parse(t.created_at) : Infinity;
      }
      // Plus récente EN HAUT : clé négative → ordre croissant = desc réel.
      return -(t.created_at ? Date.parse(t.created_at) : 0);
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

  // ── Repli de la colonne « Terminé » ───────────────────────────────
  // Les complétées s'accumulent : par défaut on montre les 5 plus
  // récentes ; UN SEUL geste (chevron d'en-tête ou pastille) déplie
  // TOUTES les terminées, et re-clic ramène à 5. État mémorisé par
  // kanban (clé = chemin de la page).
  const RECENT_DONE = 5;
  const pathname = usePathname();
  const doneKey = `kratos.taskBoard.doneCollapse.${pathname}`;
  const [doneShowAll, setDoneShowAll] = useState(false);

  useEffect(() => {
    try {
      const raw = window.localStorage.getItem(doneKey);
      const s = raw ? JSON.parse(raw) : {};
      setDoneShowAll(!!s.showAll);
    } catch {
      /* localStorage indisponible → défauts */
    }
  }, [doneKey]);

  function persistDone(showAll: boolean) {
    try {
      window.localStorage.setItem(doneKey, JSON.stringify({ showAll }));
    } catch {
      /* ignore */
    }
  }

  // Touch-drag support pour mobile : HTML5 dnd ne fonctionne pas avec
  // les events tactiles. On émule un long-press → drag → drop via les
  // events `onTouch*` posés sur chaque card, avec `elementFromPoint`
  // pour détecter au-dessus de quelle colonne se trouve le doigt.
  const touchRef = useRef<{
    id: number;
    startX: number;
    startY: number;
    dragMode: boolean;
    longPressTimer: number | null;
  } | null>(null);

  function onCardTouchStart(e: React.TouchEvent, taskId: number) {
    // Ignore le touch s'il provient d'un élément interactif (bouton,
    // select, input) à l'intérieur de la carte : on laisse l'élément
    // gérer son tap normalement.
    const target = e.target as HTMLElement;
    if (target.closest("button, select, input, textarea, a")) return;
    const t = e.touches[0];
    if (!t) return;
    if (touchRef.current?.longPressTimer) {
      window.clearTimeout(touchRef.current.longPressTimer);
    }
    touchRef.current = {
      id: taskId,
      startX: t.clientX,
      startY: t.clientY,
      dragMode: false,
      longPressTimer: window.setTimeout(() => {
        const ref = touchRef.current;
        if (ref?.id === taskId) {
          ref.dragMode = true;
          setDragId(taskId);
          if ("vibrate" in navigator) {
            try {
              navigator.vibrate(30);
            } catch {
              /* iOS sans vibrate */
            }
          }
        }
      }, 350)
    };
  }

  function onCardTouchMove(e: React.TouchEvent) {
    const ref = touchRef.current;
    if (!ref) return;
    const t = e.touches[0];
    if (!t) return;
    const dx = t.clientX - ref.startX;
    const dy = t.clientY - ref.startY;
    if (!ref.dragMode) {
      // Mouvement avant l'activation du long-press → annule (l'utilisateur
      // est en train de scroller, pas de drag).
      if (Math.hypot(dx, dy) > 10) {
        if (ref.longPressTimer) window.clearTimeout(ref.longPressTimer);
        touchRef.current = null;
      }
      return;
    }
    // En mode drag : empêche le scroll et suit le doigt.
    e.preventDefault();
    const el = document.elementFromPoint(t.clientX, t.clientY);
    let parent: HTMLElement | null = el as HTMLElement | null;
    while (parent && !parent.dataset?.kanbanStatus) {
      parent = parent.parentElement;
    }
    setHoverCol(parent?.dataset.kanbanStatus || null);
  }

  function onCardTouchEnd() {
    const ref = touchRef.current;
    if (!ref) {
      return;
    }
    if (ref.longPressTimer) window.clearTimeout(ref.longPressTimer);
    if (ref.dragMode && hoverCol) {
      handleDrop(hoverCol);
    } else {
      setDragId(null);
      setHoverCol(null);
    }
    touchRef.current = null;
  }

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

  const renderCard = (t: TaskBoardItem) => (
    <div
      key={t.id}
      onTouchStart={(e) => onCardTouchStart(e, t.id)}
      onTouchMove={onCardTouchMove}
      onTouchEnd={onCardTouchEnd}
      onTouchCancel={onCardTouchEnd}
      style={{ touchAction: dragId === t.id ? "none" : "auto" }}
    >
      <TaskCard
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
    </div>
  );

  return (
    <div className="flex gap-3 overflow-x-auto pb-3">
      {TASK_STATUS_OPTIONS.map((col) => {
        const list = byStatus[col.value] || [];
        const isHover = hoverCol === col.value;
        // Colonne « Terminé » : par défaut (ordre positionnel) on
        // inverse pour montrer les dernières cochées d'abord. ⚠️ PAS
        // quand un tri utilisateur est actif (`sorted`) — l'inversion
        // écrasait « Plus récente en haut » (bug Phil 2026-07-20).
        const isDone = col.value === "done";
        const ordered = isDone && !sorted ? [...list].reverse() : list;
        const foldable = isDone && ordered.length > RECENT_DONE;
        const visible =
          foldable && !doneShowAll
            ? ordered.slice(0, RECENT_DONE)
            : ordered;
        const hiddenCount =
          foldable && !doneShowAll ? ordered.length - RECENT_DONE : 0;
        return (
          <div
            key={col.value}
            data-kanban-status={col.value}
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
                <span className="flex items-center gap-1.5">
                  <span className="rounded-md bg-brand-950 px-2 py-0.5 text-xs font-semibold text-white/70">
                    {list.length}
                  </span>
                  {isDone && list.length > RECENT_DONE ? (
                    <button
                      type="button"
                      onClick={() => {
                        const n = !doneShowAll;
                        setDoneShowAll(n);
                        persistDone(n);
                      }}
                      title={
                        doneShowAll
                          ? "Réduire aux 5 récentes"
                          : "Voir toutes les terminées"
                      }
                      aria-label={
                        doneShowAll
                          ? "Réduire la colonne Terminé"
                          : "Voir toutes les terminées"
                      }
                      className="rounded p-0.5 text-white/40 hover:bg-white/10 hover:text-white"
                    >
                      {doneShowAll ? (
                        <ChevronUp className="h-3.5 w-3.5" />
                      ) : (
                        <ChevronDown className="h-3.5 w-3.5" />
                      )}
                    </button>
                  ) : null}
                </span>
              </div>
            </div>

            <div className="flex-1 space-y-2 p-3">
              <>
                  {list.length === 0 && adding !== col.value ? (
                    <p className="py-8 text-center text-xs text-white/40">
                      Aucune tâche
                    </p>
                  ) : null}

                  {visible.map((t) => renderCard(t))}

                  {hiddenCount > 0 ? (
                    <button
                      type="button"
                      onClick={() => {
                        setDoneShowAll(true);
                        persistDone(true);
                      }}
                      className="flex w-full items-center justify-center gap-1.5 rounded-md bg-brand-950 px-3 py-1.5 text-xs font-semibold text-white/70 transition hover:text-white"
                    >
                      <ChevronDown className="h-3.5 w-3.5" />
                      Voir les {hiddenCount} plus ancienne
                      {hiddenCount > 1 ? "s" : ""}
                    </button>
                  ) : null}

                  {foldable && doneShowAll ? (
                    <button
                      type="button"
                      onClick={() => {
                        setDoneShowAll(false);
                        persistDone(false);
                      }}
                      className="flex w-full items-center justify-center gap-1.5 rounded-md bg-brand-950 px-3 py-1.5 text-xs font-semibold text-white/70 transition hover:text-white"
                    >
                      <ChevronUp className="h-3.5 w-3.5" />
                      Réduire aux {RECENT_DONE} récentes
                    </button>
                  ) : null}

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
              </>
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
      {/* min-w-[1080px] : sur mobile la table déborde, le wrapper
          permet le scroll horizontal pour voir toutes les colonnes
          (même UX que la version web). */}
      <table className="w-full min-w-[1080px] text-[13px]">
        <thead>
          <tr
            className="text-[10px] font-semibold uppercase tracking-wider text-white/40"
            style={{ borderBottom: "1px solid rgba(100,116,139,0.35)" }}
          >
            <th className="w-[88px] px-3 py-3 text-left">P · Score</th>
            <th className="px-4 py-3 text-left">Tâche</th>
            {extraColumn ? (
              <th
                className="px-3 py-3 text-center"
                style={
                  extraColumn.width ? { width: extraColumn.width } : undefined
                }
              >
                {extraColumn.label}
              </th>
            ) : null}
            <th className="w-[180px] px-3 py-3 text-center">Immeuble</th>
            <th className="w-[120px] px-3 py-3 text-center">Statut</th>
            <th className="w-[110px] px-3 py-3 text-center">Priorité</th>
            <th className="w-[120px] px-3 py-3 text-center">Personnes</th>
            <th className="w-[110px] px-3 py-3 text-center">Échéance</th>
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
                      ? "bg-accent-500/10"
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
                  <td className="px-3 py-2.5 text-center">
                    {extraColumn.render(t)}
                  </td>
                ) : null}
                <td className="px-3 py-2.5 text-center">
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
                  className="px-3 py-2.5 text-center"
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
                  className="px-3 py-2.5 text-center"
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
                  className="px-3 py-2.5 text-center"
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
                  className="px-3 py-2.5 text-center"
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

// ── Vue « Cartes » (façon Google Keep) ─────────────────────────────────
// Cartes colorées par DEPARTEMENT, case ronde a faire/fait, ajout zero
// friction (« Prendre une note… » → auto-assignee au createur). Les chips
// (priorite / echeance / assigne) n'apparaissent QUE s'ils sont remplis →
// un collegue habitue a Keep ne voit qu'un titre + une case. Les terminees
// se replient en bas.

// Couleur de la carte = STATUT (fond très pâle, non dominant). Alignée sur
// les pastilles de TASK_STATUS_OPTIONS (À venir / À faire / En traitement /
// En attente / Terminé).
const STATUS_COLORS: Record<string, string> = {
  todo: "#8B5CF6", // À venir — violet
  a_faire: "#0EA5E9", // À faire — sky
  in_progress: "#F59E0B", // En traitement — amber
  waiting: "#D946EF", // En attente — fuchsia
  done: "#10B981", // Terminé — emerald
  backlog: "#64748B" // (legacy) — slate
};

function statusHue(status?: string | null): string {
  return STATUS_COLORS[(status || "").trim()] || "#64748B";
}

function keepDueLabel(s: string): string {
  const d = new Date(s + "T00:00:00");
  if (Number.isNaN(d.getTime())) return s;
  return d.toLocaleDateString("fr-CA", { day: "numeric", month: "short" });
}

function KeepCard({
  task, userById, onPatch, onOpenDetails, currentUserId, onDragStart,
  isDragging, registerRef
}: {
  task: TaskBoardItem;
  userById: Map<number, TaskUserMini>;
  onPatch: (taskId: number, patch: TaskBoardPatch) => void;
  onOpenDetails: (id: number) => void;
  currentUserId: number | null;
  /** Fourni → carte réordonnable (poignée affichée). Démarre le drag. */
  onDragStart?: (id: number, e: React.PointerEvent) => void;
  isDragging?: boolean;
  /** Enregistre l'élément DOM de la carte (pour l'animation FLIP). */
  registerRef?: (id: number, el: HTMLElement | null) => void;
}) {
  const done = task.status === "done";
  const hue = statusHue(task.status);
  // On masque son propre avatar (comme Keep : tes notes n'affichent pas ton
  // visage). En vue « Toutes », seuls les avatars des autres restent → signal.
  const assignees = (task.assignee_user_ids || [])
    .filter((id) => id !== currentUserId)
    .map((id) => userById.get(id))
    .filter((u): u is TaskUserMini => Boolean(u));
  // Pastille de priorité — pour toute priorité réelle (urgent → faible),
  // pas seulement urgent/élevé. Rien pour « non assigné ».
  const PRIO: Record<string, { c: string; l: string }> = {
    urgent: { c: "#F43F5E", l: "Urgent" },
    eleve: { c: "#F97316", l: "Élevé" },
    moyenne: { c: "#EAB308", l: "Moyenne" },
    faible: { c: "#84CC16", l: "Faible" }
  };
  const prio = PRIO[(task.priority || "").trim()] || null;
  const hasChips =
    Boolean(task.due_date) || Boolean(prio) || assignees.length > 0;

  return (
    <div
      data-keep-id={task.id}
      ref={registerRef ? (el) => registerRef(Number(task.id), el) : undefined}
      style={{
        // Fond TRÈS pâle selon le statut (non dominant) + fine bordure ; le
        // texte passe par les variables --qg-* qui basculent clair/sombre →
        // lisible dans les deux thèmes (le portail entreprises tourne clair).
        background: hue + "14",
        border: "1px solid " + hue + (isDragging ? "" : "29"),
        // Carte « soulevée » qui flotte au-dessus + suit le doigt
        // (transform posé impérativement). pointerEvents:none → la carte
        // sous le doigt est détectable. Pas de transition pendant le drag.
        boxShadow: isDragging
          ? "0 10px 24px rgba(0,0,0,0.28)"
          : "none",
        zIndex: isDragging ? 50 : undefined,
        position: isDragging ? "relative" : undefined,
        pointerEvents: isDragging ? "none" : undefined,
        transition: isDragging ? "none" : undefined,
        borderRadius: 12,
        padding: "10px 12px",
        marginBottom: 10,
        breakInside: "avoid"
      }}
    >
      <div style={{ display: "flex", alignItems: "flex-start", gap: 10 }}>
        <button
          type="button"
          onClick={() => onPatch(task.id, { status: done ? "a_faire" : "done" })}
          aria-label={done ? "Marquer a faire" : "Marquer termine"}
          style={{
            width: 18, height: 18, borderRadius: "50%",
            border: "1.5px solid " + hue,
            background: done ? hue : "transparent",
            flex: "0 0 auto", marginTop: 2, padding: 0, cursor: "pointer",
            display: "inline-flex", alignItems: "center", justifyContent: "center"
          }}
        >
          {done ? <Check className="h-3 w-3" style={{ color: "#fff" }} /> : null}
        </button>
        <button
          type="button"
          onClick={() => onOpenDetails(task.id)}
          style={{
            flex: 1, textAlign: "left", background: "none", border: "none",
            padding: 0, cursor: "pointer", fontSize: 14, lineHeight: 1.35,
            color: done ? "var(--qg-text-soft)" : "var(--qg-text)",
            textDecoration: done ? "line-through" : "none"
          }}
        >
          {task.title || "Sans titre"}
        </button>
        {onDragStart ? (
          <button
            type="button"
            aria-label="Réordonner"
            onPointerDown={(e) => onDragStart(Number(task.id), e)}
            onClick={(e) => e.stopPropagation()}
            style={{
              flex: "0 0 auto", marginTop: 1, padding: 2,
              background: "none", border: "none", cursor: "grab",
              touchAction: "none", color: "var(--qg-text-soft)",
              display: "inline-flex"
            }}
          >
            <GripVertical className="h-4 w-4" />
          </button>
        ) : null}
      </div>
      {hasChips ? (
        <div
          style={{
            display: "flex", flexWrap: "wrap", alignItems: "center",
            gap: 10, marginTop: 8, paddingLeft: 28
          }}
        >
          {prio ? (
            <span style={{ display: "inline-flex", alignItems: "center", gap: 4, fontSize: 11, fontWeight: 500, color: "var(--qg-text-muted)" }}>
              <span style={{ width: 7, height: 7, borderRadius: "50%", background: prio.c }} />
              {prio.l}
            </span>
          ) : null}
          {task.due_date ? (
            <span style={{ display: "inline-flex", alignItems: "center", gap: 4, fontSize: 11, color: "var(--qg-text-muted)" }}>
              <Calendar className="h-3 w-3" />
              {keepDueLabel(task.due_date)}
            </span>
          ) : null}
          {assignees.map((u) => (
            <UserInitialDot key={u.id} user={u} size={19} />
          ))}
        </div>
      ) : null}
    </div>
  );
}

function TaskKeepView({
  tasks, users, onPatch, onOpenDetails, onCreate, currentUserId
}: {
  tasks: TaskBoardItem[];
  users: TaskUserMini[];
  onPatch: (taskId: number, patch: TaskBoardPatch) => void;
  onOpenDetails: (id: number) => void;
  onCreate: (
    status: string,
    name: string
  ) => Promise<number | null> | number | null;
  currentUserId: number | null;
}) {
  const [draft, setDraft] = useState("");
  const [showDone, setShowDone] = useState(false);
  const userById = useMemo(
    () => new Map(users.map((u) => [u.id, u])),
    [users]
  );

  // Vue Cartes (mobile) → masque le bouton flottant « Demander à Kratos »
  // pour une expérience épurée façon Keep. Règle CSS dans globals.css
  // (body[data-hide-kratos] cible [aria-label="Ouvrir Kratos"]).
  useEffect(() => {
    document.body.dataset.hideKratos = "1";
    return () => {
      delete document.body.dataset.hideKratos;
    };
  }, []);
  // Ordre des cartes : position manuelle (drag & drop) ascendante, puis
  // création décroissante (la plus récente en haut). Les tâches jamais
  // déplacées partagent la position par défaut → triées par date.
  const sortForCartes = (a: TaskBoardItem, b: TaskBoardItem) => {
    const pa = a.dbPosition ?? 0;
    const pb = b.dbPosition ?? 0;
    if (pa !== pb) return pa - pb;
    const ta = a.created_at ? Date.parse(a.created_at) : 0;
    const tb = b.created_at ? Date.parse(b.created_at) : 0;
    if (tb !== ta) return tb - ta;
    return (Number(b.id) || 0) - (Number(a.id) || 0);
  };
  // Terminées : triées par date de complétion décroissante → la dernière
  // cochée (marquée terminée) tout en haut, pour la retrouver/décocher vite
  // (ex. clic accidentel sur la case). Fallback création desc si pas de date.
  const byCompletedDesc = (a: TaskBoardItem, b: TaskBoardItem) => {
    const ca = a.completed_at ? Date.parse(a.completed_at) : 0;
    const cb = b.completed_at ? Date.parse(b.completed_at) : 0;
    if (cb !== ca) return cb - ca;
    const ta = a.created_at ? Date.parse(a.created_at) : 0;
    const tb = b.created_at ? Date.parse(b.created_at) : 0;
    if (tb !== ta) return tb - ta;
    return (Number(b.id) || 0) - (Number(a.id) || 0);
  };
  const activeBase = tasks
    .filter((t) => t.status !== "done")
    .slice()
    .sort(sortForCartes);
  const done = tasks
    .filter((t) => t.status === "done")
    .slice()
    .sort(byCompletedDesc);

  // ── Drag & drop (réordonner façon Keep) ────────────────────────────
  // Pointer Events (tactile + souris) → pas de lib. Pendant le drag on
  // suit un ordre local (`dragOrder` = liste d'ids) ; au drop on persiste
  // la `position` (index) des cartes déplacées.
  const [dragId, setDragId] = useState<number | null>(null);
  const [dragOrder, setDragOrder] = useState<number[] | null>(null);
  // Refs DOM des cartes (pour l'animation FLIP) + état impératif du drag.
  const cardEls = useRef<Map<number, HTMLElement>>(new Map());
  const firstTops = useRef<Map<number, number>>(new Map());
  const grabOffset = useRef(0); // doigt ↔ haut de la carte au grab
  const dragTranslate = useRef(0); // translateY courant de la carte tenue

  const registerCard = (id: number, el: HTMLElement | null) => {
    if (el) cardEls.current.set(id, el);
    else cardEls.current.delete(id);
  };

  let activeDisplayed = activeBase;
  if (dragOrder) {
    const byId = new Map(activeBase.map((t) => [Number(t.id), t]));
    const ordered: TaskBoardItem[] = [];
    for (const id of dragOrder) {
      const t = byId.get(id);
      if (t) ordered.push(t);
    }
    for (const t of activeBase) {
      if (!dragOrder.includes(Number(t.id))) ordered.push(t);
    }
    activeDisplayed = ordered;
  }

  // FLIP : avant un réordonnancement on mémorise la position de chaque carte
  // (sauf celle qu'on tient), puis on les anime de l'ancienne vers la
  // nouvelle position → elles glissent au lieu de sauter d'un coup.
  function captureFirstTops() {
    firstTops.current.clear();
    cardEls.current.forEach((el, id) => {
      if (id === dragId) return;
      firstTops.current.set(id, el.getBoundingClientRect().top);
    });
  }
  useLayoutEffect(() => {
    if (firstTops.current.size === 0) return;
    const moved: HTMLElement[] = [];
    cardEls.current.forEach((el, id) => {
      const firstTop = firstTops.current.get(id);
      if (firstTop == null) return;
      const delta = firstTop - el.getBoundingClientRect().top;
      if (!delta) return;
      el.style.transition = "none";
      el.style.transform = `translateY(${delta}px)`;
      moved.push(el);
    });
    if (moved.length) {
      void document.body.offsetHeight; // un seul reflow forcé
      for (const el of moved) {
        el.style.transition = "transform 170ms ease";
        el.style.transform = "";
      }
    }
    firstTops.current.clear();
  }, [dragOrder]);

  function handleDragStart(id: number, e: React.PointerEvent) {
    const el = cardEls.current.get(id);
    grabOffset.current = el ? e.clientY - el.getBoundingClientRect().top : 0;
    dragTranslate.current = 0;
    setDragId(id);
    setDragOrder(activeBase.map((t) => Number(t.id)));
    try {
      (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
    } catch {
      /* ignore */
    }
  }
  function handleDragMove(e: React.PointerEvent) {
    if (dragId == null) return;
    // 1) La carte tenue suit le doigt. flowTop = sa position réelle sans le
    //    transform courant → recalculée à chaque move, ce qui corrige
    //    automatiquement le saut de créneau après un réordonnancement.
    const dEl = cardEls.current.get(dragId);
    if (dEl) {
      const flowTop = dEl.getBoundingClientRect().top - dragTranslate.current;
      const t = e.clientY - grabOffset.current - flowTop;
      dragTranslate.current = t;
      dEl.style.transform = `translateY(${t}px)`;
    }
    // 2) Index d'insertion = nombre de cartes (HORS celle qu'on tient) dont
    //    le milieu vertical est au-dessus du doigt. Stable car indépendant de
    //    la position de la carte tenue → pas d'oscillation/flash. On ne
    //    réordonne (et anime via FLIP) que si l'ordre change réellement.
    if (!dragOrder) return;
    const others = dragOrder.filter((id) => id !== dragId);
    let insertAt = others.length;
    for (let i = 0; i < others.length; i++) {
      const el = cardEls.current.get(others[i]);
      if (!el) continue;
      const r = el.getBoundingClientRect();
      if (e.clientY < r.top + r.height / 2) {
        insertAt = i;
        break;
      }
    }
    const next = [
      ...others.slice(0, insertAt),
      dragId,
      ...others.slice(insertAt)
    ];
    const changed =
      next.length !== dragOrder.length ||
      next.some((id, i) => id !== dragOrder[i]);
    if (!changed) return;
    captureFirstTops();
    setDragOrder(next);
  }
  function handleDragEnd() {
    const dEl = dragId != null ? cardEls.current.get(dragId) : null;
    if (dEl) {
      dEl.style.transition = "";
      dEl.style.transform = "";
    }
    if (dragId != null && dragOrder) {
      dragOrder.forEach((id, idx) => {
        const t = activeBase.find((x) => Number(x.id) === id);
        if (t && (t.dbPosition ?? 0) !== idx) {
          onPatch(id, { position: idx });
        }
      });
    }
    dragTranslate.current = 0;
    firstTops.current.clear();
    setDragId(null);
    setDragOrder(null);
  }

  async function quickAdd() {
    const name = draft.trim();
    if (!name) return;
    setDraft("");
    const id = await onCreate("a_faire", name);
    if (typeof id === "number" && currentUserId) {
      onPatch(id, { assignee_user_ids: [currentUserId] });
    }
  }

  return (
    <div>
      <div
        style={{
          display: "flex", alignItems: "center", gap: 10,
          background: "var(--qg-card-bg)",
          border: "1px solid var(--qg-border)",
          borderRadius: 12, padding: "10px 14px", marginBottom: 16
        }}
      >
        <Plus className="h-4 w-4 text-white/40" />
        <input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              void quickAdd();
            }
          }}
          enterKeyHint="done"
          placeholder="Prendre une note… (Entrée pour ajouter)"
          className="placeholder:text-brand-300"
          style={{
            flex: 1, background: "none", border: "none", outline: "none",
            color: "var(--qg-text)", fontSize: 14
          }}
        />
      </div>

      {activeBase.length === 0 ? (
        <p className="rounded-xl border border-dashed border-brand-800 bg-brand-900/40 px-6 py-10 text-center text-sm text-white/50">
          Aucune tâche en cours. Écris une note ci-dessus pour commencer.
        </p>
      ) : (
        <div
          onPointerMove={handleDragMove}
          onPointerUp={handleDragEnd}
          onPointerCancel={handleDragEnd}
          style={{ display: "flex", flexDirection: "column" }}
        >
          {activeDisplayed.map((t) => (
            <KeepCard
              key={t.id}
              task={t}
              userById={userById}
              onPatch={onPatch}
              onOpenDetails={onOpenDetails}
              currentUserId={currentUserId}
              onDragStart={handleDragStart}
              isDragging={dragId === Number(t.id)}
              registerRef={registerCard}
            />
          ))}
        </div>
      )}

      {done.length > 0 ? (
        <div style={{ marginTop: 18 }}>
          <button
            type="button"
            onClick={() => setShowDone((v) => !v)}
            className="inline-flex items-center gap-1.5 text-sm text-white/60 hover:text-white/90"
          >
            {showDone ? (
              <ChevronDown className="h-4 w-4" />
            ) : (
              <ChevronRight className="h-4 w-4" />
            )}
            Terminé · {done.length}
          </button>
          {showDone ? (
            <div style={{ columnWidth: "240px", columnGap: "12px", marginTop: 12 }}>
              {done.map((t) => (
                <KeepCard
                  key={t.id}
                  task={t}
                  userById={userById}
                  onPatch={onPatch}
                  onOpenDetails={onOpenDetails}
                  currentUserId={currentUserId}
                />
              ))}
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
