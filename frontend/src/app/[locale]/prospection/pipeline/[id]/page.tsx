"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useParams } from "next/navigation";
import { ArrowLeft, Loader2, MapPin, Plus, Trash2 } from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { authedFetch } from "@/lib/auth";
import { Link, useRouter } from "@/i18n/navigation";
import { useConfirm } from "@/components/confirm-dialog";
import { useProspectionLayout } from "../../layout";
import {
  AutoGrowTextarea,
  type TaskUserMini
} from "@/components/task-pills";
import { TaskCard } from "@/components/task-card";
import { TaskDetailsModal } from "@/components/task-details-modal";
import { TASK_STATUS_OPTIONS } from "@/lib/task-config";

/**
 * Fiche d'un Deal — analogue de /entreprises/[id]/page.tsx. Header
 * avec l'adresse éditable + tâches en kanban (4 colonnes À venir /
 * À faire / En traitement / Terminé). Mêmes composants partagés
 * (TaskCard, TaskDetailsModal) que les tâches d'entreprise — la
 * mise en page est strictement identique.
 */

type Deal = {
  id: number;
  address: string;
  priority: string;
  created_at: string;
  updated_at: string;
};

type Task = {
  id: number;
  deal_id: number;
  name: string;
  notes: string | null;
  assignee_user_id: number | null;
  assignee_user_ids: number[];
  status: string;
  priority: string;
  due_date: string | null;
  position: number;
  created_at: string;
  updated_at: string;
};

export default function DealDetailPage() {
  const { onOpenSidebar } = useProspectionLayout();
  const params = useParams();
  const router = useRouter();
  const confirm = useConfirm();
  const dealId = Number(params?.id);

  const [deal, setDeal] = useState<Deal | null>(null);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [users, setUsers] = useState<TaskUserMini[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [editingName, setEditingName] = useState(false);
  const [draftName, setDraftName] = useState("");
  const [adding, setAdding] = useState<string | null>(null);
  const [newName, setNewName] = useState("");
  const [dragId, setDragId] = useState<number | null>(null);
  const [hoverCol, setHoverCol] = useState<string | null>(null);
  const [detailTaskId, setDetailTaskId] = useState<number | null>(null);

  const load = useCallback(async () => {
    if (!Number.isFinite(dealId) || dealId <= 0) return;
    setLoading(true);
    try {
      const [dRes, tRes, uRes] = await Promise.all([
        authedFetch(`/api/v1/prospection/deals/${dealId}`),
        authedFetch(`/api/v1/prospection/deals/${dealId}/tasks`),
        authedFetch("/api/v1/users")
      ]);
      if (!dRes.ok) throw new Error("Deal introuvable");
      const d = (await dRes.json()) as Deal;
      setDeal(d);
      setDraftName(d.address);
      if (tRes.ok) setTasks((await tRes.json()) as Task[]);
      if (uRes.ok) {
        const all = (await uRes.json()) as Array<
          TaskUserMini & { volets?: string[] }
        >;
        setUsers(
          all.filter((u) => (u.volets || []).includes("prospection"))
        );
      }
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, [dealId]);

  useEffect(() => {
    void load();
  }, [load]);

  async function patchDeal(patch: Partial<Deal>) {
    if (!deal) return;
    const prev = deal;
    setDeal({ ...deal, ...patch });
    try {
      const r = await authedFetch(
        `/api/v1/prospection/deals/${deal.id}`,
        { method: "PATCH", body: JSON.stringify(patch) }
      );
      if (!r.ok) throw new Error();
    } catch {
      setDeal(prev);
      setError("Mise à jour échouée.");
    }
  }

  async function removeDeal() {
    if (!deal) return;
    const ok = await confirm({
      title: `Supprimer le deal « ${deal.address} » ?`,
      description:
        "Cette action est irréversible. Toutes les tâches du deal seront aussi supprimées.",
      confirmLabel: "Supprimer",
      destructive: true
    });
    if (!ok) return;
    try {
      const r = await authedFetch(`/api/v1/prospection/deals/${deal.id}`, {
        method: "DELETE"
      });
      if (!r.ok && r.status !== 204) throw new Error();
      router.replace("/prospection/pipeline" as never);
    } catch {
      setError("Suppression échouée.");
    }
  }

  async function patchTask(taskId: number, patch: Partial<Task>) {
    const prev = tasks;
    setTasks((xs) =>
      xs.map((x) => (x.id === taskId ? { ...x, ...patch } : x))
    );
    try {
      const r = await authedFetch(
        `/api/v1/prospection/deals/${dealId}/tasks/${taskId}`,
        { method: "PATCH", body: JSON.stringify(patch) }
      );
      if (!r.ok) throw new Error();
      const updated = (await r.json()) as Task;
      setTasks((xs) =>
        xs.map((x) => (x.id === updated.id ? updated : x))
      );
    } catch {
      setTasks(prev);
      setError("Mise à jour de la tâche échouée.");
    }
  }

  async function createTask(status: string) {
    if (!newName.trim()) {
      setAdding(null);
      return;
    }
    try {
      const r = await authedFetch(
        `/api/v1/prospection/deals/${dealId}/tasks`,
        {
          method: "POST",
          body: JSON.stringify({ name: newName.trim(), status })
        }
      );
      if (!r.ok) throw new Error();
      const created = (await r.json()) as Task;
      setTasks((xs) => [...xs, created]);
    } catch {
      setError("Création de tâche échouée.");
    } finally {
      setNewName("");
      setAdding(null);
    }
  }

  async function deleteTask(t: Task) {
    const prev = tasks;
    setTasks((xs) => xs.filter((x) => x.id !== t.id));
    try {
      const r = await authedFetch(
        `/api/v1/prospection/deals/${dealId}/tasks/${t.id}`,
        { method: "DELETE" }
      );
      if (!r.ok && r.status !== 204) throw new Error();
    } catch {
      setTasks(prev);
    }
  }

  function handleColDrop(targetStatus: string) {
    if (dragId == null) return;
    const t = tasks.find((x) => x.id === dragId);
    setDragId(null);
    setHoverCol(null);
    if (!t || t.status === targetStatus) return;
    const sameStatus = tasks.filter((x) => x.status === targetStatus);
    const newPos =
      sameStatus.length > 0
        ? Math.max(...sameStatus.map((x) => x.position)) + 1000
        : 1000;
    void patchTask(t.id, { status: targetStatus, position: newPos });
  }

  const tasksByStatus = useMemo(() => {
    const map: Record<string, Task[]> = Object.fromEntries(
      TASK_STATUS_OPTIONS.map((s) => [s.value, [] as Task[]])
    );
    for (const t of tasks) {
      const target = map[t.status] ? t.status : "a_faire";
      (map[target] ||= []).push(t);
    }
    for (const k of Object.keys(map)) {
      map[k].sort((a, b) => a.position - b.position);
    }
    return map;
  }, [tasks]);

  if (!Number.isFinite(dealId) || dealId <= 0) {
    return (
      <div className="p-6 text-sm text-white/60">Deal introuvable.</div>
    );
  }

  if (loading) {
    return (
      <>
        <AppTopbar
          breadcrumbs={[
            { label: "Prospection", href: "/prospection" },
            { label: "Pipeline", href: "/prospection/pipeline" }
          ]}
          onOpenSidebar={onOpenSidebar}
        />
        <div className="flex min-h-[60vh] items-center justify-center">
          <Loader2 className="h-6 w-6 animate-spin text-accent-500" />
        </div>
      </>
    );
  }

  if (!deal) {
    return (
      <div className="p-6">
        <p className="text-sm text-rose-300">
          {error || "Deal introuvable."}
        </p>
      </div>
    );
  }

  return (
    <>
      <AppTopbar
        breadcrumbs={[
          { label: "Prospection", href: "/prospection" },
          { label: "Pipeline", href: "/prospection/pipeline" },
          { label: deal.address }
        ]}
        onOpenSidebar={onOpenSidebar}
      />

      <div className="p-4 lg:p-6">
        <Link
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          href={"/prospection/pipeline" as any}
          className="inline-flex items-center text-xs text-white/60 hover:text-emerald-300"
        >
          <ArrowLeft className="mr-1 h-3.5 w-3.5" />
          Retour au pipeline
        </Link>

        <header className="mt-4 flex items-start gap-3">
          <span className="mt-0.5 flex h-10 w-10 items-center justify-center rounded-xl bg-emerald-500/15 text-emerald-400">
            <MapPin className="h-5 w-5" />
          </span>
          <div className="flex-1">
            {editingName ? (
              <AutoGrowTextarea
                autoFocus
                value={draftName}
                onChange={setDraftName}
                onCommit={() => {
                  const v = draftName.trim();
                  setEditingName(false);
                  if (v && v !== deal.address) patchDeal({ address: v });
                  else setDraftName(deal.address);
                }}
                className="w-full resize-none rounded border border-emerald-500 bg-brand-950 px-2 py-1.5 text-2xl font-bold text-white focus:outline-none"
              />
            ) : (
              <button
                type="button"
                onClick={() => setEditingName(true)}
                className="block w-full break-words rounded px-1 py-1 text-left text-2xl font-bold text-white hover:bg-white/5"
                title="Cliquer pour modifier l'adresse"
              >
                {deal.address}
              </button>
            )}
            <p className="mt-1 text-xs text-white/50">
              Ajouté le{" "}
              {new Date(deal.created_at).toLocaleDateString("fr-CA", {
                day: "2-digit",
                month: "long",
                year: "numeric"
              })}
            </p>
          </div>
          <div className="flex flex-col items-end gap-1.5">
            <div className="rounded-md bg-brand-900 px-3 py-2 text-sm">
              <span className="text-white/50">Tâches </span>
              <span className="font-bold text-white">{tasks.length}</span>
            </div>
            <button
              type="button"
              onClick={removeDeal}
              title="Supprimer ce deal"
              aria-label="Supprimer le deal"
              className="rounded-md p-1.5 text-white/40 transition hover:bg-rose-500/15 hover:text-rose-300"
            >
              <Trash2 className="h-4 w-4" />
            </button>
          </div>
        </header>

        {error ? (
          <p className="mt-4 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-300">
            {error}
          </p>
        ) : null}

        {/* Tâches — kanban identique à celui d'une entreprise. */}
        <div className="mt-6">
          <h2 className="text-sm font-semibold uppercase tracking-wider text-white/50">
            Tâches
          </h2>
          <div className="mt-3 flex gap-3 overflow-x-auto pb-3">
            {TASK_STATUS_OPTIONS.map((col) => {
              const list = tasksByStatus[col.value] || [];
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
                    handleColDrop(col.value);
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
                        task={{
                          id: t.id,
                          title: t.name,
                          status: t.status,
                          priority: t.priority || "non_assigne",
                          due_date: t.due_date,
                          assignee_user_ids: t.assignee_user_ids || [],
                          hasNote: Boolean(t.notes)
                        }}
                        users={users}
                        onPatch={(patch) => {
                          const out: Partial<Task> = {};
                          if (patch.title !== undefined)
                            out.name = patch.title;
                          if (patch.status !== undefined)
                            out.status = patch.status;
                          if (patch.priority !== undefined)
                            out.priority = patch.priority;
                          if (patch.due_date !== undefined)
                            out.due_date = patch.due_date;
                          if (patch.assignee_user_ids !== undefined) {
                            out.assignee_user_ids = patch.assignee_user_ids;
                            out.assignee_user_id =
                              patch.assignee_user_ids[0] ?? null;
                          }
                          void patchTask(t.id, out);
                        }}
                        onDelete={(ev) => {
                          ev.stopPropagation();
                          ev.preventDefault();
                          void deleteTask(t);
                        }}
                        onOpenDetails={() => setDetailTaskId(t.id)}
                        draggable
                        dragging={dragId === t.id}
                        onDragStart={() => setDragId(t.id)}
                        onDragEnd={() => {
                          setDragId(null);
                          setHoverCol(null);
                        }}
                      />
                    ))}

                    {adding === col.value ? (
                      <input
                        autoFocus
                        type="text"
                        value={newName}
                        onChange={(e) => setNewName(e.target.value)}
                        onBlur={() => createTask(col.value)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter") createTask(col.value);
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
        </div>
      </div>

      {detailTaskId !== null
        ? (() => {
            const t = tasks.find((x) => x.id === detailTaskId);
            if (!t) return null;
            return (
              <TaskDetailsModal
                task={{
                  id: t.id,
                  title: t.name,
                  notes: t.notes || "",
                  status: t.status,
                  priority: t.priority || "non_assigne",
                  due_date: t.due_date,
                  assignee_user_ids: t.assignee_user_ids || []
                }}
                users={users}
                onClose={() => setDetailTaskId(null)}
                onPatch={(patch) => {
                  const out: Partial<Task> = {};
                  if (patch.title !== undefined) out.name = patch.title;
                  if (patch.notes !== undefined) out.notes = patch.notes;
                  if (patch.status !== undefined)
                    out.status = patch.status;
                  if (patch.priority !== undefined)
                    out.priority = patch.priority;
                  if (patch.due_date !== undefined)
                    out.due_date = patch.due_date;
                  if (patch.assignee_user_ids !== undefined) {
                    out.assignee_user_ids = patch.assignee_user_ids;
                    out.assignee_user_id =
                      patch.assignee_user_ids[0] ?? null;
                  }
                  void patchTask(t.id, out);
                }}
              />
            );
          })()
        : null}
    </>
  );
}
