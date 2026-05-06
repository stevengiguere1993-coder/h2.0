"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  ChevronDown,
  ChevronUp,
  Loader2,
  Plus,
  StickyNote,
  Trash2
} from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { authedFetch } from "@/lib/auth";
import { useConfirm } from "@/components/confirm-dialog";
import { useProspectionLayout } from "../layout";

// ─── Priorités du DEAL (au niveau de la carte entière) ────────────
type DealPriority =
  | "urgent"
  | "eleve"
  | "moyenne"
  | "en_attente"
  | "a_venir"
  | "termine";

const DEAL_PRIORITIES: {
  value: DealPriority;
  label: string;
  dot: string;
}[] = [
  { value: "urgent", label: "Urgent ⚠️", dot: "bg-rose-500" },
  { value: "eleve", label: "Élevé", dot: "bg-orange-500" },
  { value: "moyenne", label: "Moyenne", dot: "bg-amber-400" },
  { value: "en_attente", label: "En attente", dot: "bg-sky-400" },
  { value: "a_venir", label: "À venir", dot: "bg-white/40" },
  { value: "termine", label: "Terminé", dot: "bg-emerald-500" }
];

const DEAL_PRIORITY_RANK: Record<DealPriority, number> = {
  urgent: 0,
  eleve: 1,
  moyenne: 2,
  en_attente: 3,
  a_venir: 4,
  termine: 5
};

const DEAL_PRIORITY_DOT: Record<DealPriority, string> = {
  urgent: "bg-rose-500",
  eleve: "bg-orange-500",
  moyenne: "bg-amber-400",
  en_attente: "bg-sky-400",
  a_venir: "bg-white/40",
  termine: "bg-emerald-500"
};

type Deal = {
  id: number;
  address: string;
  priority: DealPriority;
  created_at: string;
  updated_at: string;
};

// ─── Statuts et priorités de TÂCHES ───────────────────────────────
type TaskStatus = "a_venir" | "a_faire" | "en_traitement" | "termine";
type TaskPriority = "urgent" | "eleve" | "moyenne" | "faible";

const TASK_STATUSES: { value: TaskStatus; label: string }[] = [
  { value: "a_venir", label: "À venir" },
  { value: "a_faire", label: "À faire" },
  { value: "en_traitement", label: "En traitement" },
  { value: "termine", label: "Terminé" }
];

// Style Monday-like : chaque groupe de statut a sa propre teinte —
// bordure vive et fond pastel pour qu'on identifie au coup d'œil
// dans quel état est une tâche.
const STATUS_STYLE: Record<
  TaskStatus,
  {
    border: string;
    bg: string;
    label: string;
    dragOverBg: string;
    pill: string; // pastille pleine pour le picker dans la tâche
  }
> = {
  a_venir: {
    // Rose pâle (pas rouge) — teinte pink-300/200, fond très clair.
    border: "border-pink-300/50",
    bg: "bg-pink-300/5",
    label: "text-pink-200",
    dragOverBg: "bg-pink-300/15",
    pill: "bg-pink-400 text-white"
  },
  a_faire: {
    // Bleu
    border: "border-sky-400/70",
    bg: "bg-sky-500/10",
    label: "text-sky-300",
    dragOverBg: "bg-sky-500/20",
    pill: "bg-sky-500 text-white"
  },
  en_traitement: {
    // Jaune/orange
    border: "border-amber-400/70",
    bg: "bg-amber-500/10",
    label: "text-amber-300",
    dragOverBg: "bg-amber-500/20",
    pill: "bg-amber-500 text-brand-950"
  },
  termine: {
    // Vert
    border: "border-emerald-400/70",
    bg: "bg-emerald-500/10",
    label: "text-emerald-300",
    dragOverBg: "bg-emerald-500/20",
    pill: "bg-emerald-500 text-white"
  }
};

const TASK_PRIORITIES: {
  value: TaskPriority;
  label: string;
  emoji?: string;
}[] = [
  { value: "urgent", label: "Urgent ⚠️" },
  { value: "eleve", label: "Élevé" },
  { value: "moyenne", label: "Moyenne" },
  { value: "faible", label: "Faible" }
];

const TASK_PRIORITY_LABEL: Record<TaskPriority, string> = {
  urgent: "Urgent ⚠️",
  eleve: "Élevé",
  moyenne: "Moyenne",
  faible: "Faible"
};

// Pastilles pleines style Monday — fond saturé, texte qui contraste.
const TASK_PRIORITY_PILL: Record<TaskPriority, string> = {
  urgent: "bg-rose-500 text-white",
  eleve: "bg-orange-500 text-white",
  moyenne: "bg-amber-400 text-brand-950",
  faible: "bg-slate-500 text-white"
};

type Task = {
  id: number;
  deal_id: number;
  name: string;
  notes: string | null;
  assignee_user_id: number | null;
  status: TaskStatus;
  priority: TaskPriority;
  due_date: string | null;
  position: number;
  created_at: string;
  updated_at: string;
};

type UserMini = { id: number; email: string; volets: string[] };

export default function ProspectionPipelinePage() {
  const { onOpenSidebar } = useProspectionLayout();
  const confirm = useConfirm();
  const [deals, setDeals] = useState<Deal[]>([]);
  const [users, setUsers] = useState<UserMini[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [modalOpen, setModalOpen] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [dRes, uRes] = await Promise.all([
        authedFetch("/api/v1/prospection/deals"),
        authedFetch("/api/v1/users")
      ]);
      if (!dRes.ok) throw new Error(`HTTP ${dRes.status}`);
      const dealsRaw = (await dRes.json()) as Deal[];
      setDeals(sortDeals(dealsRaw));
      if (uRes.ok) {
        const all = (await uRes.json()) as UserMini[];
        // Garde les users qui ont accès à Prospection.
        setUsers(all.filter((u) => u.volets?.includes("prospection")));
      }
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function changeDealPriority(id: number, priority: DealPriority) {
    // MAJ optimiste + re-tri immédiat (la carte saute à la bonne
    // place pendant que le serveur valide).
    const prev = deals;
    setDeals((xs) =>
      sortDeals(xs.map((d) => (d.id === id ? { ...d, priority } : d)))
    );
    try {
      const res = await authedFetch(`/api/v1/prospection/deals/${id}`, {
        method: "PATCH",
        body: JSON.stringify({ priority })
      });
      if (!res.ok) throw new Error();
    } catch {
      setDeals(prev);
      setError("Mise à jour de la priorité échouée.");
    }
  }

  async function changeDealAddress(id: number, address: string) {
    const prev = deals;
    setDeals((xs) =>
      xs.map((d) => (d.id === id ? { ...d, address } : d))
    );
    try {
      const res = await authedFetch(`/api/v1/prospection/deals/${id}`, {
        method: "PATCH",
        body: JSON.stringify({ address })
      });
      if (!res.ok) throw new Error();
    } catch {
      setDeals(prev);
      setError("Mise à jour de l'adresse échouée.");
    }
  }

  async function removeDeal(deal: Deal) {
    if (
      !(await confirm({
        title: `Retirer le deal « ${deal.address} » ?`,
        description: "Cette action ne peut pas être annulée.",
        confirmLabel: "Retirer",
        destructive: true
      }))
    ) {
      return;
    }
    const prev = deals;
    setDeals((xs) => xs.filter((d) => d.id !== deal.id));
    try {
      const res = await authedFetch(
        `/api/v1/prospection/deals/${deal.id}`,
        { method: "DELETE" }
      );
      if (!res.ok && res.status !== 204) throw new Error();
    } catch {
      setDeals(prev);
      setError("Suppression échouée.");
    }
  }

  return (
    <>
      <AppTopbar
        breadcrumbs={[
          { label: "Prospection", href: "/prospection" },
          { label: "Pipeline des deals" }
        ]}
        onOpenSidebar={onOpenSidebar}
        rightSlot={
          <button
            type="button"
            onClick={() => setModalOpen(true)}
            className="btn-accent text-sm"
          >
            <Plus className="mr-1.5 h-4 w-4" /> Ajouter un deal
          </button>
        }
      />

      <div className="p-4 lg:p-6">
        {error ? (
          <p className="mb-4 rounded-lg border border-rose-500/40 bg-rose-500/10 px-4 py-2 text-sm text-rose-300">
            {error}
          </p>
        ) : null}

        {loading ? (
          <div className="flex min-h-[40vh] items-center justify-center">
            <Loader2 className="h-6 w-6 animate-spin text-accent-500" />
          </div>
        ) : deals.length === 0 ? (
          <EmptyState onAdd={() => setModalOpen(true)} />
        ) : (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {deals.map((d) => (
              <DealCard
                key={d.id}
                deal={d}
                users={users}
                onChangePriority={(p) => changeDealPriority(d.id, p)}
                onChangeAddress={(a) => changeDealAddress(d.id, a)}
                onRemove={() => removeDeal(d)}
              />
            ))}
          </div>
        )}
      </div>

      {modalOpen ? (
        <AddDealModal
          onClose={() => setModalOpen(false)}
          onCreated={(d) => {
            setDeals((xs) => sortDeals([...xs, d]));
            setModalOpen(false);
          }}
        />
      ) : null}
    </>
  );
}

function sortDeals(arr: Deal[]): Deal[] {
  return [...arr].sort((a, b) => {
    const ra = DEAL_PRIORITY_RANK[a.priority] ?? 99;
    const rb = DEAL_PRIORITY_RANK[b.priority] ?? 99;
    if (ra !== rb) return ra - rb;
    return new Date(b.created_at).getTime() - new Date(a.created_at).getTime();
  });
}

// ════════════════════════════════════════════════════════════════════
// Carte d'un deal — adresse, priorité, et liste de tâches groupées
// ════════════════════════════════════════════════════════════════════
function DealCard({
  deal,
  users,
  onChangePriority,
  onChangeAddress,
  onRemove
}: {
  deal: Deal;
  users: UserMini[];
  onChangePriority: (p: DealPriority) => void;
  onChangeAddress: (address: string) => void;
  onRemove: () => void;
}) {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [loadingTasks, setLoadingTasks] = useState(true);
  const [collapsed, setCollapsed] = useState(false);
  const [adding, setAdding] = useState<TaskStatus | null>(null);
  const [newName, setNewName] = useState("");
  const [dragId, setDragId] = useState<number | null>(null);
  const [dragOverStatus, setDragOverStatus] = useState<TaskStatus | null>(
    null
  );
  // Édition inline du nom du deal (adresse).
  const [editingName, setEditingName] = useState(false);
  const [draftName, setDraftName] = useState(deal.address);
  useEffect(() => {
    setDraftName(deal.address);
  }, [deal.address]);

  const loadTasks = useCallback(async () => {
    setLoadingTasks(true);
    try {
      const res = await authedFetch(
        `/api/v1/prospection/deals/${deal.id}/tasks`
      );
      if (!res.ok) throw new Error();
      setTasks((await res.json()) as Task[]);
    } catch {
      /* silent — l'UI montre 0 tâche */
    } finally {
      setLoadingTasks(false);
    }
  }, [deal.id]);

  useEffect(() => {
    void loadTasks();
  }, [loadTasks]);

  const tasksByStatus = useMemo(() => {
    const groups: Record<TaskStatus, Task[]> = {
      a_venir: [],
      a_faire: [],
      en_traitement: [],
      termine: []
    };
    for (const t of tasks) groups[t.status]?.push(t);
    for (const k of Object.keys(groups) as TaskStatus[]) {
      groups[k].sort((a, b) => a.position - b.position);
    }
    return groups;
  }, [tasks]);

  async function patchTask(id: number, patch: Partial<Task>) {
    const prev = tasks;
    setTasks((xs) =>
      xs.map((t) => (t.id === id ? { ...t, ...patch } : t))
    );
    try {
      const res = await authedFetch(
        `/api/v1/prospection/deals/${deal.id}/tasks/${id}`,
        {
          method: "PATCH",
          body: JSON.stringify(patch)
        }
      );
      if (!res.ok) throw new Error();
      const updated = (await res.json()) as Task;
      setTasks((xs) => xs.map((t) => (t.id === updated.id ? updated : t)));
    } catch {
      setTasks(prev);
    }
  }

  async function createTask(status: TaskStatus) {
    if (!newName.trim()) {
      setAdding(null);
      return;
    }
    try {
      const res = await authedFetch(
        `/api/v1/prospection/deals/${deal.id}/tasks`,
        {
          method: "POST",
          body: JSON.stringify({ name: newName.trim(), status })
        }
      );
      if (!res.ok) throw new Error();
      const created = (await res.json()) as Task;
      setTasks((xs) => [...xs, created]);
    } catch {
      /* silent */
    } finally {
      setNewName("");
      setAdding(null);
    }
  }

  async function deleteTask(task: Task) {
    const prev = tasks;
    setTasks((xs) => xs.filter((t) => t.id !== task.id));
    try {
      const res = await authedFetch(
        `/api/v1/prospection/deals/${deal.id}/tasks/${task.id}`,
        { method: "DELETE" }
      );
      if (!res.ok && res.status !== 204) throw new Error();
    } catch {
      setTasks(prev);
    }
  }

  // Drop sur un groupe = changer le status de la tâche draggée + la
  // mettre en bas du nouveau groupe (position = max+1000).
  function handleDrop(target: TaskStatus) {
    if (dragId == null) return;
    const t = tasks.find((x) => x.id === dragId);
    setDragId(null);
    setDragOverStatus(null);
    if (!t) return;
    if (t.status === target) return; // pas de move si même statut
    const sameStatus = tasks.filter((x) => x.status === target);
    const newPos =
      sameStatus.length > 0
        ? Math.max(...sameStatus.map((x) => x.position)) + 1000
        : 1000;
    void patchTask(t.id, { status: target, position: newPos });
  }

  return (
    <div className="rounded-xl border border-brand-800 bg-brand-900 p-4 shadow-sm">
      {/* Header carte — adresse éditable inline */}
      <div className="flex items-start justify-between gap-2">
        {editingName ? (
          <input
            autoFocus
            type="text"
            value={draftName}
            onChange={(e) => setDraftName(e.target.value)}
            onBlur={() => {
              const v = draftName.trim();
              setEditingName(false);
              if (v && v !== deal.address) onChangeAddress(v);
              else setDraftName(deal.address);
            }}
            onKeyDown={(e) => {
              if (e.key === "Enter") (e.target as HTMLInputElement).blur();
              if (e.key === "Escape") {
                setDraftName(deal.address);
                setEditingName(false);
              }
            }}
            className="min-w-0 flex-1 rounded border border-accent-500 bg-brand-950 px-1.5 py-1 text-sm font-semibold text-white focus:outline-none"
          />
        ) : (
          <button
            type="button"
            onClick={() => setEditingName(true)}
            className="min-w-0 flex-1 truncate rounded px-1.5 py-1 text-left text-sm font-semibold text-white hover:bg-white/5"
            title="Cliquer pour modifier l'adresse"
          >
            {deal.address}
          </button>
        )}
        <DealPriorityPicker
          value={deal.priority}
          onChange={onChangePriority}
        />
      </div>

      {/* Bandeau d'action */}
      <div className="mt-3 flex items-center justify-between text-[10px] text-white/40">
        <button
          type="button"
          onClick={() => setCollapsed((v) => !v)}
          className="inline-flex items-center gap-1 rounded p-1 hover:bg-white/5"
          title={collapsed ? "Afficher les tâches" : "Masquer les tâches"}
        >
          {collapsed ? (
            <ChevronDown className="h-3.5 w-3.5" />
          ) : (
            <ChevronUp className="h-3.5 w-3.5" />
          )}
          <span>
            {tasks.length} tâche{tasks.length > 1 ? "s" : ""}
          </span>
        </button>
        <button
          type="button"
          onClick={onRemove}
          className="rounded p-1 hover:bg-rose-500/15 hover:text-rose-300"
          title="Retirer du pipeline"
          aria-label="Retirer"
        >
          <Trash2 className="h-3.5 w-3.5" />
        </button>
      </div>

      {/* Liste des tâches groupées */}
      {!collapsed ? (
        <div className="mt-3 space-y-2.5 border-t border-brand-800 pt-3">
          {loadingTasks ? (
            <p className="text-center text-[11px] text-white/40">
              Chargement…
            </p>
          ) : (
            TASK_STATUSES.map((s) => {
              const list = tasksByStatus[s.value];
              const isDragOver = dragOverStatus === s.value;
              const style = STATUS_STYLE[s.value];
              return (
                <div
                  key={s.value}
                  onDragOver={(e) => {
                    e.preventDefault();
                    setDragOverStatus(s.value);
                  }}
                  onDragLeave={() =>
                    setDragOverStatus((cur) =>
                      cur === s.value ? null : cur
                    )
                  }
                  onDrop={() => handleDrop(s.value)}
                  className={`rounded-lg border-2 p-2 transition ${style.border} ${
                    isDragOver ? style.dragOverBg : style.bg
                  }`}
                >
                  <div className="mb-1.5 flex items-center justify-between px-0.5">
                    <p
                      className={`text-[10px] font-bold uppercase tracking-wider ${style.label}`}
                    >
                      {s.label}
                      <span className="ml-1 opacity-60">
                        ({list.length})
                      </span>
                    </p>
                    <button
                      type="button"
                      onClick={() => {
                        setAdding(s.value);
                        setNewName("");
                      }}
                      className={`rounded p-0.5 ${style.label} hover:bg-white/10`}
                      title="Ajouter une tâche"
                      aria-label="Ajouter une tâche"
                    >
                      <Plus className="h-3 w-3" />
                    </button>
                  </div>
                  <ul className="space-y-1.5">
                    {list.map((t) => (
                      <TaskRow
                        key={t.id}
                        task={t}
                        users={users}
                        onPatch={(p) => patchTask(t.id, p)}
                        onDelete={() => deleteTask(t)}
                        onDragStart={() => setDragId(t.id)}
                        onDragEnd={() => {
                          setDragId(null);
                          setDragOverStatus(null);
                        }}
                        dragging={dragId === t.id}
                      />
                    ))}
                  </ul>

                  {adding === s.value ? (
                    <div className="mt-1 px-1">
                      <input
                        autoFocus
                        type="text"
                        value={newName}
                        onChange={(e) => setNewName(e.target.value)}
                        onBlur={() => createTask(s.value)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter") createTask(s.value);
                          if (e.key === "Escape") {
                            setAdding(null);
                            setNewName("");
                          }
                        }}
                        placeholder="Nom de la tâche…"
                        className="w-full rounded border border-brand-800 bg-brand-950 px-2 py-1 text-xs text-white focus:border-accent-500 focus:outline-none"
                      />
                    </div>
                  ) : null}
                </div>
              );
            })
          )}
        </div>
      ) : null}
    </div>
  );
}

// ─── Ligne d'une tâche ─────────────────────────────────────────────
function TaskRow({
  task,
  users,
  onPatch,
  onDelete,
  onDragStart,
  onDragEnd,
  dragging
}: {
  task: Task;
  users: UserMini[];
  onPatch: (p: Partial<Task>) => void;
  onDelete: () => void;
  onDragStart: () => void;
  onDragEnd: () => void;
  dragging: boolean;
}) {
  const [showNotes, setShowNotes] = useState(false);
  const [notesDraft, setNotesDraft] = useState(task.notes || "");
  // Re-sync si la note change côté serveur (re-fetch).
  useEffect(() => {
    setNotesDraft(task.notes || "");
  }, [task.notes]);

  const overdue =
    task.due_date && task.status !== "termine"
      ? new Date(task.due_date + "T23:59:59") < new Date()
      : false;

  return (
    <li
      draggable
      onDragStart={(e) => {
        // Empêche le drag depuis les inputs (sinon select/input
        // déclenchent le drag sur mobile).
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
      className={`rounded-md border bg-brand-950 px-2 py-1.5 ${
        dragging
          ? "border-accent-500 opacity-60"
          : "border-brand-800"
      }`}
    >
      {/* Première ligne : nom (éditable inline) + boutons */}
      <div className="flex items-center gap-1.5">
        <input
          type="text"
          value={task.name}
          onChange={(e) => onPatch({ name: e.target.value })}
          onBlur={(e) => {
            const v = e.target.value.trim();
            if (v && v !== task.name) onPatch({ name: v });
          }}
          className="min-w-0 flex-1 truncate rounded border border-transparent bg-transparent px-1 py-0.5 text-xs text-white hover:border-brand-800 focus:border-accent-500 focus:outline-none"
        />
        <button
          type="button"
          onClick={() => setShowNotes((v) => !v)}
          className={`flex-shrink-0 rounded p-1 ${
            task.notes
              ? "text-amber-300 hover:bg-amber-500/15"
              : "text-white/40 hover:bg-white/5"
          }`}
          title={task.notes ? "Voir / éditer les notes" : "Ajouter une note"}
          aria-label="Notes"
        >
          <StickyNote className="h-3 w-3" />
        </button>
        <button
          type="button"
          onClick={onDelete}
          className="flex-shrink-0 rounded p-1 text-white/40 hover:bg-rose-500/15 hover:text-rose-300"
          title="Supprimer la tâche"
          aria-label="Supprimer"
        >
          <Trash2 className="h-3 w-3" />
        </button>
      </div>

      {/* Notes : zone repliable */}
      {showNotes ? (
        <div className="mt-1.5">
          <textarea
            value={notesDraft}
            onChange={(e) => setNotesDraft(e.target.value)}
            onBlur={() => {
              if (notesDraft !== (task.notes || "")) {
                onPatch({ notes: notesDraft || null });
              }
            }}
            rows={3}
            placeholder="Notes…"
            className="w-full rounded border border-brand-800 bg-brand-900 px-2 py-1 text-xs text-white focus:border-accent-500 focus:outline-none"
          />
        </div>
      ) : null}

      {/* Pastilles style Monday : assigné / statut / priorité / échéance */}
      <div className="mt-1.5 grid grid-cols-2 gap-1">
        <AssigneePill
          users={users}
          value={task.assignee_user_id}
          onChange={(uid) => onPatch({ assignee_user_id: uid })}
        />
        <PillPicker
          options={TASK_STATUSES.map((s) => ({
            value: s.value,
            label: s.label,
            cls: STATUS_STYLE[s.value].pill
          }))}
          value={task.status}
          onChange={(v) => onPatch({ status: v as TaskStatus })}
          ariaLabel="Statut"
        />
        <PillPicker
          options={TASK_PRIORITIES.map((p) => ({
            value: p.value,
            label: p.label,
            cls: TASK_PRIORITY_PILL[p.value]
          }))}
          value={task.priority}
          onChange={(v) => onPatch({ priority: v as TaskPriority })}
          ariaLabel="Priorité"
        />
        <DatePill
          value={task.due_date}
          overdue={overdue}
          onChange={(d) => onPatch({ due_date: d })}
        />
      </div>

      {overdue ? (
        <p className="mt-1 inline-flex items-center gap-1 text-[10px] font-semibold text-rose-300">
          <AlertTriangle className="h-3 w-3" />
          En retard
        </p>
      ) : null}
    </li>
  );
}

// ─── Sélecteur de priorité d'un deal ───────────────────────────────
function DealPriorityPicker({
  value,
  onChange
}: {
  value: DealPriority;
  onChange: (p: DealPriority) => void;
}) {
  return (
    <div className="relative">
      <select
        value={value}
        onChange={(e) => onChange(e.target.value as DealPriority)}
        className="cursor-pointer appearance-none rounded-md border border-brand-800 bg-brand-950 py-1 pl-6 pr-2 text-[11px] font-semibold text-white focus:border-accent-500 focus:outline-none"
        aria-label="Priorité"
      >
        {DEAL_PRIORITIES.map((p) => (
          <option key={p.value} value={p.value}>
            {p.label}
          </option>
        ))}
      </select>
      <span
        className={`pointer-events-none absolute left-1.5 top-1/2 h-2 w-2 -translate-y-1/2 rounded-full ${DEAL_PRIORITY_DOT[value]}`}
      />
    </div>
  );
}

// ─── Modal "Ajouter un deal" ──────────────────────────────────────
function AddDealModal({
  onClose,
  onCreated
}: {
  onClose: () => void;
  onCreated: (d: Deal) => void;
}) {
  const [address, setAddress] = useState("");
  const [priority, setPriority] = useState<DealPriority>("moyenne");
  const [submitting, setSubmitting] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function submit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!address.trim()) {
      setErr("L'adresse est requise.");
      return;
    }
    setSubmitting(true);
    setErr(null);
    try {
      const res = await authedFetch("/api/v1/prospection/deals", {
        method: "POST",
        body: JSON.stringify({ address: address.trim(), priority })
      });
      if (!res.ok) {
        const txt = await res.text().catch(() => "");
        throw new Error(`HTTP ${res.status} ${txt.slice(0, 120)}`);
      }
      onCreated((await res.json()) as Deal);
    } catch (e) {
      setErr((e as Error).message || "Création échouée.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4"
      onClick={() => (!submitting ? onClose() : null)}
    >
      <form
        onClick={(e) => e.stopPropagation()}
        onSubmit={submit}
        className="w-full max-w-md rounded-2xl border border-brand-800 bg-brand-950 p-5"
      >
        <h2 className="text-base font-bold text-white">Ajouter un deal</h2>
        <p className="mt-1 text-xs text-white/50">
          Saisis l&apos;adresse de l&apos;immeuble et choisis sa priorité.
        </p>

        <div className="mt-4 space-y-3">
          <div>
            <label className="label">Adresse de l&apos;immeuble</label>
            <input
              type="text"
              value={address}
              onChange={(e) => setAddress(e.target.value)}
              placeholder="Ex. 1234 rue Saint-Hubert, Montréal"
              className="input"
              autoFocus
              disabled={submitting}
            />
          </div>
          <div>
            <label className="label">Priorité</label>
            <select
              value={priority}
              onChange={(e) => setPriority(e.target.value as DealPriority)}
              className="input"
              disabled={submitting}
            >
              {DEAL_PRIORITIES.map((p) => (
                <option key={p.value} value={p.value}>
                  {p.label}
                </option>
              ))}
            </select>
          </div>
        </div>

        {err ? (
          <p className="mt-3 rounded-md border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
            {err}
          </p>
        ) : null}

        <div className="mt-5 flex items-center justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            disabled={submitting}
            className="btn-secondary text-sm"
          >
            Annuler
          </button>
          <button
            type="submit"
            disabled={submitting}
            className="btn-accent text-sm disabled:opacity-60"
          >
            {submitting ? (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            ) : (
              <Plus className="mr-1.5 h-4 w-4" />
            )}
            Ajouter le deal
          </button>
        </div>
      </form>
    </div>
  );
}

function EmptyState({ onAdd }: { onAdd: () => void }) {
  return (
    <div className="mx-auto mt-12 max-w-md rounded-2xl border border-dashed border-brand-800 bg-brand-900/40 p-10 text-center">
      <h2 className="text-lg font-semibold text-white">
        Aucun deal pour l&apos;instant
      </h2>
      <p className="mt-2 text-sm text-white/60">
        Ajoute ta première opportunité — adresse + priorité — et elle
        apparaîtra ici dans l&apos;ordre, du plus urgent au moins urgent.
      </p>
      <button
        type="button"
        onClick={onAdd}
        className="btn-accent mt-5 text-sm"
      >
        <Plus className="mr-1.5 h-4 w-4" /> Ajouter un deal
      </button>
    </div>
  );
}

// Empêche le warning "unused var" pour la table de labels exportée
// (utilisée dans les futures vues filtrées par priorité de tâche).
export const _TASK_PRIORITY_LABEL = TASK_PRIORITY_LABEL;

// ─── Composants Monday-like ───────────────────────────────────────

type PillOption = {
  value: string;
  label: string;
  cls: string; // Classes Tailwind appliquées au fond + texte de la pastille
};

/**
 * Pastille pleine style Monday : la valeur courante est affichée
 * comme un bouton coloré ; au clic, un petit menu flottant montre
 * toutes les options sous forme de pastilles. Chaque option, au clic,
 * applique + ferme.
 */
function PillPicker({
  options,
  value,
  onChange,
  ariaLabel
}: {
  options: PillOption[];
  value: string;
  onChange: (v: string) => void;
  ariaLabel?: string;
}) {
  const [open, setOpen] = useState(false);
  const wrapRef = useRef<HTMLDivElement | null>(null);

  // Ferme le menu si on clique ailleurs.
  useEffect(() => {
    if (!open) return;
    function onClick(e: MouseEvent) {
      if (
        wrapRef.current &&
        !wrapRef.current.contains(e.target as Node)
      ) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, [open]);

  const current = options.find((o) => o.value === value) ?? options[0];

  return (
    <div ref={wrapRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-label={ariaLabel}
        className={`inline-flex w-full items-center justify-center rounded px-2 py-1 text-[10px] font-semibold ${current.cls}`}
      >
        <span className="truncate">{current.label}</span>
      </button>
      {open ? (
        <div className="absolute left-0 right-0 z-30 mt-1 min-w-[140px] space-y-1 rounded-lg border border-brand-800 bg-brand-950 p-1 shadow-lg">
          {options.map((o) => (
            <button
              key={o.value}
              type="button"
              onClick={() => {
                onChange(o.value);
                setOpen(false);
              }}
              className={`block w-full rounded px-2 py-1 text-left text-[10px] font-semibold ${o.cls} ${
                o.value === value
                  ? "ring-2 ring-white/60"
                  : "opacity-90 hover:opacity-100"
              }`}
            >
              {o.label}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}

/**
 * Pastille « personne assignée » — avatar en initiales + courte
 * étiquette. Au clic, ouvre la liste des users (avec « Personne »
 * pour désassigner).
 */
function AssigneePill({
  users,
  value,
  onChange
}: {
  users: UserMini[];
  value: number | null;
  onChange: (uid: number | null) => void;
}) {
  const [open, setOpen] = useState(false);
  const wrapRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!open) return;
    function onClick(e: MouseEvent) {
      if (
        wrapRef.current &&
        !wrapRef.current.contains(e.target as Node)
      ) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, [open]);

  const current = value ? users.find((u) => u.id === value) : null;
  const localPart = current ? current.email.split("@")[0] : "";
  const initials = localPart
    ? localPart
        .split(/[._-]/)
        .map((s) => s[0])
        .filter(Boolean)
        .slice(0, 2)
        .join("")
        .toUpperCase()
    : "";

  return (
    <div ref={wrapRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-label="Personne assignée"
        className={`inline-flex w-full items-center justify-center gap-1 rounded px-2 py-1 text-[10px] font-semibold ${
          current
            ? "bg-violet-500 text-white"
            : "bg-brand-800 text-white/60"
        }`}
      >
        {current ? (
          <>
            <span className="flex h-3.5 w-3.5 items-center justify-center rounded-full bg-white/20 text-[8px] font-bold">
              {initials || "?"}
            </span>
            <span className="truncate">{localPart}</span>
          </>
        ) : (
          <span>+ Personne</span>
        )}
      </button>
      {open ? (
        <div className="absolute left-0 right-0 z-30 mt-1 max-h-56 min-w-[160px] space-y-1 overflow-y-auto rounded-lg border border-brand-800 bg-brand-950 p-1 shadow-lg">
          <button
            type="button"
            onClick={() => {
              onChange(null);
              setOpen(false);
            }}
            className="block w-full rounded px-2 py-1 text-left text-[10px] font-semibold text-white/60 hover:bg-white/5"
          >
            — Personne —
          </button>
          {users.map((u) => (
            <button
              key={u.id}
              type="button"
              onClick={() => {
                onChange(u.id);
                setOpen(false);
              }}
              className={`block w-full rounded px-2 py-1 text-left text-[10px] font-semibold ${
                u.id === value
                  ? "bg-violet-500 text-white"
                  : "text-white hover:bg-white/5"
              }`}
            >
              {u.email.split("@")[0]}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}

/**
 * Pastille date butoir — affiche la date formatée (ou « Date butoir »
 * si vide). Au clic, ouvre un input date masqué.
 */
function DatePill({
  value,
  overdue,
  onChange
}: {
  value: string | null;
  overdue: boolean;
  onChange: (d: string | null) => void;
}) {
  const inputRef = useRef<HTMLInputElement | null>(null);

  function open() {
    const el = inputRef.current;
    if (!el) return;
    // showPicker est dispo Chrome/Edge ; fallback en focus + clic.
    const anyEl = el as HTMLInputElement & { showPicker?: () => void };
    if (typeof anyEl.showPicker === "function") {
      try {
        anyEl.showPicker();
        return;
      } catch {
        /* fallback */
      }
    }
    el.focus();
    el.click();
  }

  const formatted = value
    ? new Date(value + "T12:00:00").toLocaleDateString("fr-CA", {
        day: "2-digit",
        month: "short"
      })
    : null;

  return (
    <div className="relative">
      <button
        type="button"
        onClick={open}
        aria-label="Date butoir"
        className={`inline-flex w-full items-center justify-center gap-1 rounded px-2 py-1 text-[10px] font-semibold ${
          overdue
            ? "bg-rose-500 text-white"
            : value
              ? "bg-emerald-500/80 text-white"
              : "bg-brand-800 text-white/60"
        }`}
      >
        {formatted || "+ Date butoir"}
      </button>
      <input
        ref={inputRef}
        type="date"
        value={value || ""}
        onChange={(e) => onChange(e.target.value || null)}
        className="pointer-events-none absolute inset-0 h-full w-full opacity-0"
      />
    </div>
  );
}
