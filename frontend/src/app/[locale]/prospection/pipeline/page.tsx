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
import {
  PROFILE_COLOR_PILL,
  DEFAULT_PILL_CLASS
} from "@/lib/profile-colors";

// ─── Priorités du DEAL (au niveau de la carte entière) ────────────
type DealPriority =
  | "urgent"
  | "eleve"
  | "moyenne"
  | "a_venir"
  | "termine"
  | "abandonne";

const DEAL_PRIORITIES: {
  value: DealPriority;
  label: string;
  dot: string;
}[] = [
  { value: "urgent", label: "Urgent ⚠️", dot: "bg-rose-500" },
  { value: "eleve", label: "Élevé", dot: "bg-orange-500" },
  { value: "moyenne", label: "Moyenne", dot: "bg-amber-400" },
  { value: "a_venir", label: "À venir", dot: "bg-white/40" },
  { value: "termine", label: "Terminé", dot: "bg-emerald-500" },
  { value: "abandonne", label: "Abandonné", dot: "bg-slate-500" }
];

const DEAL_PRIORITY_RANK: Record<DealPriority, number> = {
  urgent: 0,
  eleve: 1,
  moyenne: 2,
  a_venir: 3,
  termine: 4,
  abandonne: 5
};

const DEAL_PRIORITY_DOT: Record<DealPriority, string> = {
  urgent: "bg-rose-500",
  eleve: "bg-orange-500",
  moyenne: "bg-amber-400",
  a_venir: "bg-white/40",
  termine: "bg-emerald-500",
  abandonne: "bg-slate-500"
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
    border: "border-violet-400/60",
    bg: "bg-violet-400/5",
    label: "text-violet-200",
    dragOverBg: "bg-violet-400/15",
    pill: "bg-violet-500 text-white"
  },
  a_faire: {
    border: "border-sky-400/70",
    bg: "bg-sky-500/10",
    label: "text-sky-300",
    dragOverBg: "bg-sky-500/20",
    pill: "bg-sky-500 text-white"
  },
  en_traitement: {
    border: "border-amber-400/70",
    bg: "bg-amber-500/10",
    label: "text-amber-300",
    dragOverBg: "bg-amber-500/20",
    pill: "bg-amber-500 text-brand-950"
  },
  termine: {
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

// Pastilles pleines style Monday — chaque axe (statut / priorité /
// date butoir) doit avoir des teintes distinctes pour éviter qu'on
// les confonde quand 4 pastilles s'alignent sur la même tâche.
//
// Statut : violet / sky / amber / emerald  (saturés)
// Priorité : rose-700 / orange-500 / yellow-400 / lime-500
// Date butoir : teal / yellow-200 / orange-700 / red-700
const TASK_PRIORITY_PILL: Record<TaskPriority, string> = {
  // urgent : rouge profond — différent du rose vif de la date « en
  // retard » (ci-dessous) pour ne pas confondre.
  urgent: "bg-red-700 text-white",
  eleve: "bg-orange-500 text-white",
  // moyenne : jaune saturé. La date 7-14 j utilise yellow-200 (pâle)
  // pour ne pas se confondre avec.
  moyenne: "bg-yellow-400 text-brand-950",
  // faible : vert lime, distinct du vert emerald (statut Terminé).
  faible: "bg-lime-500 text-brand-950"
};

// Rang utilisé pour trier les tâches dans un même groupe de statut :
// urgent en haut, faible en bas.
const TASK_PRIORITY_RANK: Record<TaskPriority, number> = {
  urgent: 0,
  eleve: 1,
  moyenne: 2,
  faible: 3
};

type Task = {
  id: number;
  deal_id: number;
  name: string;
  notes: string | null;
  // Champ legacy = primary (= premier de la liste). On garde pour
  // compat ; la source de vérité est la liste.
  assignee_user_id: number | null;
  assignee_user_ids: number[];
  status: TaskStatus;
  priority: TaskPriority;
  due_date: string | null;
  position: number;
  created_at: string;
  updated_at: string;
};

type UserMini = {
  id: number;
  email: string;
  volets: string[];
  display_name?: string;
  first_name?: string | null;
  last_name?: string | null;
  profile_color?: string | null;
  has_avatar?: boolean;
};

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
          // Une seule ligne horizontale qui scrolle vers la droite —
          // chaque carte garde une largeur fixe pour qu'on puisse
          // empiler beaucoup de deals sans rétrécir leur contenu.
          // L'utilisateur scrolle latéralement pour voir tous les
          // deals (style Monday/Trello en mode rangée unique).
          //
          // On insère une fine ligne noire verticale juste avant le
          // premier deal « Terminé » pour visuellement séparer ce
          // qui est encore en cours du reste.
          <div className="flex items-stretch gap-3 overflow-x-auto pb-3">
            {deals.map((d, i) => {
              const prev = i > 0 ? deals[i - 1] : null;
              const showDoneSeparator =
                d.priority === "termine" &&
                (prev == null || prev.priority !== "termine");
              return (
                <div key={d.id} className="contents">
                  {showDoneSeparator ? (
                    <div
                      className="mx-1 w-px flex-shrink-0 self-stretch bg-black"
                      aria-hidden="true"
                    />
                  ) : null}
                  <div className="w-72 flex-shrink-0">
                    <DealCard
                      deal={d}
                      users={users}
                      onChangePriority={(p) => changeDealPriority(d.id, p)}
                      onChangeAddress={(a) => changeDealAddress(d.id, a)}
                      onRemove={() => removeDeal(d)}
                    />
                  </div>
                </div>
              );
            })}
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
    // Tri dans chaque groupe : urgent → faible, puis position pour
    // les tâches de même priorité (l'ordre manuel par drag-drop
    // reste respecté à priorité égale).
    for (const k of Object.keys(groups) as TaskStatus[]) {
      groups[k].sort((a, b) => {
        const ra = TASK_PRIORITY_RANK[a.priority] ?? 99;
        const rb = TASK_PRIORITY_RANK[b.priority] ?? 99;
        if (ra !== rb) return ra - rb;
        return a.position - b.position;
      });
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
      {/* Header carte — adresse éditable inline (prend toute la
          largeur, plus de pastille priorité à droite). */}
      <div>
        {editingName ? (
          <AutoGrowTextarea
            value={draftName}
            onChange={setDraftName}
            onCommit={() => {
              const v = draftName.trim();
              setEditingName(false);
              if (v && v !== deal.address) onChangeAddress(v);
              else setDraftName(deal.address);
            }}
            autoFocus
            className="w-full resize-none rounded border border-accent-500 bg-brand-950 px-1.5 py-1 text-sm font-semibold text-white focus:outline-none"
          />
        ) : (
          <button
            type="button"
            onClick={() => setEditingName(true)}
            // break-words : le titre s'enroule sur plusieurs lignes
            // dès qu'il dépasse la largeur de la carte (ex. adresse
            // longue avec nom de rue + ville). Plus de truncate.
            className="block w-full rounded px-1.5 py-1 text-left text-sm font-semibold text-white break-words hover:bg-white/5"
            title="Cliquer pour modifier l'adresse"
          >
            {deal.address}
          </button>
        )}
      </div>

      {/* Bandeau d'action — la priorité du deal est maintenant au
          milieu, entre le compteur de tâches (gauche) et la
          poubelle (droite). */}
      <div className="mt-3 flex items-center justify-between gap-2 text-[10px] text-white/40">
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
        <DealPriorityPicker
          value={deal.priority}
          onChange={onChangePriority}
        />
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
        <div className="mt-3 space-y-2.5 border-y border-brand-800 py-3">
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
      {/* Première ligne : nom (éditable inline, retour à la ligne
          auto si trop long) + boutons. textarea + auto-resize via
          le hook ci-dessous, plutôt qu'un <input> qui truncate. */}
      <div className="flex items-start gap-1.5">
        <AutoGrowTextarea
          value={task.name}
          onChange={(v) => onPatch({ name: v })}
          onCommit={(v) => {
            const trimmed = v.trim();
            if (trimmed && trimmed !== task.name) {
              onPatch({ name: trimmed });
            }
          }}
          // Bordure gris normal (slate-500/40) : assez visible pour
          // signaler le champ éditable, sans crier comme noir plein.
          // Hover/focus le mettent en accent-500. Léger gras
          // (font-medium) pour bien démarquer le titre du reste.
          className="min-w-0 flex-1 resize-none rounded border border-slate-500/40 bg-transparent px-1 py-0.5 text-xs font-medium text-white hover:border-slate-400/60 focus:border-accent-500 focus:outline-none"
        />
        {/* Boutons empilés verticalement : note au-dessus, poubelle
            en-dessous (demande utilisateur). */}
        <div className="flex flex-shrink-0 flex-col items-center gap-0.5">
          <button
            type="button"
            onClick={() => setShowNotes((v) => !v)}
            className={`rounded p-1 ${
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
            className="rounded p-1 text-white/40 hover:bg-rose-500/15 hover:text-rose-300"
            title="Supprimer la tâche"
            aria-label="Supprimer"
          >
            <Trash2 className="h-3 w-3" />
          </button>
        </div>
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

      {/* Pastilles style Monday : assigné(s) / statut / priorité / échéance.
          Chaque pastille porte un petit libellé gris pâle au-dessus
          (Personnes / Statut / Priorité / Date butoire). */}
      <div className="mt-1.5 grid grid-cols-2 gap-1.5">
        <PillField label="Personnes">
          <AssigneePicker
            users={users}
            values={task.assignee_user_ids || []}
            onChange={(ids) =>
              onPatch({
                assignee_user_ids: ids,
                assignee_user_id: ids[0] ?? null
              })
            }
          />
        </PillField>
        <PillField label="Statut">
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
        </PillField>
        <PillField label="Priorité">
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
        </PillField>
        <PillField label="Date butoire">
          <DatePill
            value={task.due_date}
            onChange={(d) => onPatch({ due_date: d })}
          />
        </PillField>
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

/**
 * Wrapper d'une pastille dans la grille 2x2 des tâches : libellé
 * gris pâle au-dessus (Personnes / Statut / Priorité / Date
 * butoire) puis la pastille en-dessous.
 */
function PillField({
  label,
  children
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="min-w-0">
      <p className="mb-0.5 truncate px-0.5 text-[9px] font-medium uppercase tracking-wider text-white/40">
        {label}
      </p>
      {children}
    </div>
  );
}

/**
 * Textarea qui s'agrandit automatiquement à la hauteur de son
 * contenu (style « note »). Sur la première ligne il est aussi
 * petit qu'un input ; sitôt qu'on dépasse la largeur, le texte
 * passe à la ligne et la zone grandit en conséquence.
 *
 * Utilisé pour le nom de tâche dans le Pipeline — un input simple
 * truncate-rait le texte qui dépasse, alors qu'on veut tout voir.
 */
function AutoGrowTextarea({
  value,
  onChange,
  onCommit,
  className,
  autoFocus
}: {
  value: string;
  onChange: (v: string) => void;
  onCommit?: (v: string) => void;
  className?: string;
  autoFocus?: boolean;
}) {
  const ref = useRef<HTMLTextAreaElement | null>(null);

  // Resync la hauteur à chaque changement de valeur.
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${el.scrollHeight}px`;
  }, [value]);

  return (
    <textarea
      ref={ref}
      rows={1}
      autoFocus={autoFocus}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      onBlur={(e) => onCommit?.(e.target.value)}
      onKeyDown={(e) => {
        // Enter (sans Shift) commit + blur — on ne veut pas saisir
        // un retour à la ligne explicite dans un nom de tâche.
        if (e.key === "Enter" && !e.shiftKey) {
          e.preventDefault();
          (e.target as HTMLTextAreaElement).blur();
        }
      }}
      className={className}
      style={{ overflow: "hidden" }}
    />
  );
}

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
 * Picker multi-personnes Monday-style. Affiche les avatars empilés
 * (jusqu'à 3) + le nom du primary, ou un compteur « +N » si plus
 * d'assignés. Au clic, ouvre la liste des users — chaque ligne est
 * cliquable pour toggle (ajout / retrait). Une croix permet aussi
 * de retirer un assigné directement depuis sa pastille.
 */
function AssigneePicker({
  users,
  values,
  onChange
}: {
  users: UserMini[];
  values: number[];
  onChange: (ids: number[]) => void;
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

  const assigned = values
    .map((id) => users.find((u) => u.id === id))
    .filter((u): u is UserMini => Boolean(u));
  const primary = assigned[0];
  const extras = assigned.length - 1;

  function toggle(uid: number) {
    if (values.includes(uid)) {
      onChange(values.filter((v) => v !== uid));
    } else {
      onChange([...values, uid]);
    }
  }

  return (
    <div ref={wrapRef} className="relative">
      {/* Container gris pâle qui héberge les chips. Reste toujours
          visible (style Monday : on identifie tout de suite que
          c'est la zone « personnes assignées »). Les chips
          empruntent la couleur de chaque personne — le container
          NE prend PAS la couleur. */}
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-label="Personne(s) assignée(s)"
        // justify-center : qu'il y ait 1 ou 5 chips, l'ensemble
        // est toujours centré horizontalement dans le rectangle.
        className="inline-flex w-full items-center justify-center gap-1 rounded bg-brand-800 px-1.5 py-1 text-[10px] font-semibold text-white/60 hover:bg-brand-700"
      >
        {assigned.length === 0 ? (
          <span className="px-0.5">+ Personne</span>
        ) : (
          <span className="flex flex-wrap items-center justify-center gap-1">
            {assigned.map((u) => (
              <span
                key={u.id}
                className={`inline-flex items-center gap-1 rounded-full px-1 py-0.5 text-[9px] font-bold ${userPillCls(u)}`}
                title={userDisplayName(u)}
              >
                <UserAvatarBadge user={u} size={12} />
                <span className="leading-none">{userInitials(u)}</span>
              </span>
            ))}
          </span>
        )}
      </button>
      {open ? (
        <div className="absolute left-0 right-0 z-30 mt-1 max-h-72 min-w-[200px] overflow-y-auto rounded-lg border border-brand-800 bg-brand-950 p-1 shadow-lg">
          {/* Liste des assignés courants — clic pour retirer */}
          {assigned.length > 0 ? (
            <div className="mb-1 space-y-1 border-b border-brand-800 pb-1">
              {assigned.map((u) => (
                <button
                  key={u.id}
                  type="button"
                  onClick={() => toggle(u.id)}
                  className={`flex w-full items-center gap-1.5 rounded px-2 py-1 text-left text-[10px] font-semibold ring-2 ring-white/40 ${userPillCls(u)} hover:opacity-90`}
                  title="Cliquer pour retirer"
                >
                  <UserAvatarBadge user={u} size={14} />
                  <span className="flex-1 truncate">
                    {userDisplayName(u)}
                  </span>
                  <span className="text-[10px] opacity-80">×</span>
                </button>
              ))}
            </div>
          ) : null}

          {/* Tous les autres users — clic pour ajouter */}
          <div className="space-y-1">
            {users
              .filter((u) => !values.includes(u.id))
              .map((u) => (
                <button
                  key={u.id}
                  type="button"
                  onClick={() => toggle(u.id)}
                  className={`flex w-full items-center gap-1.5 rounded px-2 py-1 text-left text-[10px] font-semibold ${userPillCls(u)} opacity-80 hover:opacity-100`}
                >
                  <UserAvatarBadge user={u} size={14} />
                  <span className="truncate">
                    {userDisplayName(u)}
                  </span>
                </button>
              ))}
            {users.length === values.length && values.length > 0 ? (
              <p className="px-2 py-1 text-[10px] text-white/40">
                Toute l&apos;équipe est assignée.
              </p>
            ) : null}
          </div>
        </div>
      ) : null}
    </div>
  );
}

function userDisplayName(u: UserMini): string {
  if (u.display_name) return u.display_name;
  const fn = (u.first_name || "").trim();
  const ln = (u.last_name || "").trim();
  if (fn || ln) return `${fn} ${ln}`.trim();
  return u.email.split("@")[0];
}

function userInitials(u: UserMini): string {
  const fn = (u.first_name || "").trim();
  const ln = (u.last_name || "").trim();
  if (fn || ln) {
    return `${fn[0] || ""}${ln[0] || ""}`.toUpperCase() || "?";
  }
  const local = u.email.split("@")[0];
  return (local[0] || "?").toUpperCase();
}

function userPillCls(u: UserMini): string {
  const c = u.profile_color;
  if (c && (PROFILE_COLOR_PILL as Record<string, string>)[c]) {
    return PROFILE_COLOR_PILL[c as keyof typeof PROFILE_COLOR_PILL];
  }
  return DEFAULT_PILL_CLASS;
}

/**
 * Petit rond avatar — photo si disponible (chargée via authedFetch
 * pour pouvoir envoyer le Bearer token), sinon initiales.
 */
function UserAvatarBadge({
  user,
  size = 14
}: {
  user: UserMini;
  size?: number;
}) {
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => {
    let revoke: string | null = null;
    (async () => {
      if (!user.has_avatar) {
        setUrl(null);
        return;
      }
      try {
        const r = await authedFetch(
          `/api/v1/auth/users/${user.id}/avatar`
        );
        if (!r.ok) return;
        const blob = await r.blob();
        const u = URL.createObjectURL(blob);
        revoke = u;
        setUrl(u);
      } catch {
        /* ignore */
      }
    })();
    return () => {
      if (revoke) URL.revokeObjectURL(revoke);
    };
  }, [user.id, user.has_avatar]);

  const dim = `${size}px`;
  if (url) {
    return (
      // eslint-disable-next-line @next/next/no-img-element
      <img
        src={url}
        alt=""
        className="flex-shrink-0 rounded-full object-cover"
        style={{ width: dim, height: dim }}
      />
    );
  }
  return (
    <span
      className="flex flex-shrink-0 items-center justify-center rounded-full bg-white/20 text-[8px] font-bold"
      style={{ width: dim, height: dim }}
    >
      {userInitials(user)}
    </span>
  );
}

/**
 * Pastille date butoir — petit rectangle noir à coins arrondis, plus
 * compact que les autres pastilles. Pas de couleur dépendante du
 * délai (l'utilisateur a explicitement demandé de retirer ça pour
 * un look uniforme style Monday). Au clic, ouvre un input date masqué.
 */
function DatePill({
  value,
  onChange
}: {
  value: string | null;
  onChange: (d: string | null) => void;
}) {
  const inputRef = useRef<HTMLInputElement | null>(null);

  function open() {
    const el = inputRef.current;
    if (!el) return;
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
        // pill-date-invert : noir sur thème clair, blanc sur thème
        // dark — défini dans globals.css. rounded-full = forme
        // capsule (rectangle aux extrémités demi-cercle). w-full
        // pour s'aligner sur la largeur des autres pastilles.
        className="pill-date-invert inline-flex w-full items-center justify-center rounded-full px-2 py-1 text-[10px] font-semibold"
      >
        {formatted || "+ Date"}
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
