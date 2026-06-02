"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { ArrowLeft, Loader2, MapPin, Pencil, Trash2 } from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { authedFetch } from "@/lib/auth";
import { Link, useRouter } from "@/i18n/navigation";
import { useConfirm } from "@/components/confirm-dialog";
import { EntityDriveSection } from "@/components/drive/EntityDriveSection";
import { LeadAnalysisSummary } from "@/components/lead-analysis-summary";
import { LeadAnalysisDetailModal } from "@/components/leads/LeadAnalysisDetailModal";
import { NDASection } from "@/components/nda-section";
import { OfferSection } from "@/components/offer-section";
import { useProspectionLayout } from "../../layout";
import {
  AutoGrowTextarea,
  type TaskUserMini
} from "@/components/task-pills";
import { TaskBoard, type TaskBoardItem } from "@/components/task-board";
import type { ImmeubleMini } from "@/components/immeuble-picker";

/**
 * Fiche d'un Deal — analogue de /entreprises/[id]/page.tsx. Header
 * avec l'adresse éditable + section Tâches rendue par le composant
 * partagé <TaskBoard> — strictement identique à la section Tâches
 * d'une entreprise. Toute modification de mise en page se fait dans
 * /components/task-board.tsx et profite aux deux pages.
 */

type Deal = {
  id: number;
  address: string;
  priority: string;
  drive_folder_url: string | null;
  lead_analysis_id: number | null;
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
  immeuble_ids: number[];
  departement: string | null;
  recurrence: string | null;
  impact: number | null;
  confidence: number | null;
  effort: number | null;
  score: number | null;
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
  const [immeubles, setImmeubles] = useState<ImmeubleMini[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [editingName, setEditingName] = useState(false);
  const [draftName, setDraftName] = useState("");
  const [moveTask, setMoveTask] = useState<Task | null>(null);
  // Modal d'analyse ouvert SUR PLACE (par-dessus la page du Deal).
  // Phil clique sur « Ouvrir la fiche complète » dans <LeadAnalysisSummary>
  // -> on set cet id et le modal s'affiche en overlay, sans navigation.
  const [detailAnalysisId, setDetailAnalysisId] = useState<number | null>(null);

  const load = useCallback(async () => {
    if (!Number.isFinite(dealId) || dealId <= 0) return;
    setLoading(true);
    try {
      const [dRes, tRes, uRes, iRes] = await Promise.all([
        authedFetch(`/api/v1/prospection/deals/${dealId}`),
        authedFetch(`/api/v1/prospection/deals/${dealId}/tasks`),
        authedFetch("/api/v1/users"),
        authedFetch(`/api/v1/immobilier/immeubles/picker?deal_id=${dealId}`)
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
      if (iRes.ok) setImmeubles((await iRes.json()) as ImmeubleMini[]);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, [dealId]);

  useEffect(() => {
    void load();
  }, [load]);

  async function reloadImmeubles() {
    try {
      const r = await authedFetch(`/api/v1/immobilier/immeubles/picker?deal_id=${dealId}`);
      if (r.ok) setImmeubles((await r.json()) as ImmeubleMini[]);
    } catch {
      /* l'erreur est déjà signalée par le dialog. */
    }
  }

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

  async function renameDeal() {
    if (!deal) return;
    const next = window.prompt(
      "Nouvelle adresse du deal :",
      deal.address
    );
    if (next == null) return;
    const v = next.trim();
    if (!v || v === deal.address) return;
    await patchDeal({ address: v });
    setDraftName(v);
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

  async function createTask(
    status: string,
    name: string
  ): Promise<number | null> {
    try {
      const r = await authedFetch(
        `/api/v1/prospection/deals/${dealId}/tasks`,
        {
          method: "POST",
          body: JSON.stringify({ name, status })
        }
      );
      if (!r.ok) throw new Error();
      const created = (await r.json()) as Task;
      setTasks((xs) => [...xs, created]);
      return created.id;
    } catch {
      setError("Création de tâche échouée.");
      return null;
    }
  }

  async function deleteTaskById(taskId: number) {
    const prev = tasks;
    setTasks((xs) => xs.filter((x) => x.id !== taskId));
    try {
      const r = await authedFetch(
        `/api/v1/prospection/deals/${dealId}/tasks/${taskId}`,
        { method: "DELETE" }
      );
      if (!r.ok && r.status !== 204) throw new Error();
    } catch {
      setTasks(prev);
    }
  }

  // Adaptateur Task → TaskBoardItem. <TaskBoard> attend une shape
  // neutre (title / hasNote) ; ici on traduit la shape native du
  // backend Pipeline (name / notes).
  const immeubleNameById = new Map(
    immeubles.map((i) => [i.id, i.name] as const)
  );
  const boardItems: TaskBoardItem[] = tasks.map((t) => ({
    id: t.id,
    title: t.name,
    status: t.status,
    priority: t.priority || "non_assigne",
    due_date: t.due_date,
    assignee_user_ids: t.assignee_user_ids || [],
    hasNote: Boolean(t.notes),
    notes: t.notes,
    position: t.position,
    immeuble_ids: t.immeuble_ids || [],
    departement: t.departement,
    recurrence: t.recurrence,
    impact: t.impact,
    confidence: t.confidence,
    effort: t.effort,
    score: t.score,
    immeubleLabels: (t.immeuble_ids || [])
      .map((id) => immeubleNameById.get(id))
      .filter((n): n is string => Boolean(n))
  }));

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
            <div className="flex items-center gap-1">
              <button
                type="button"
                onClick={renameDeal}
                title="Renommer le deal"
                aria-label="Renommer le deal"
                className="rounded-md p-1.5 text-white/40 transition hover:bg-violet-500/15 hover:text-violet-300"
              >
                <Pencil className="h-4 w-4" />
              </button>
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
          </div>
        </header>

        {error ? (
          <p className="mt-4 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-300">
            {error}
          </p>
        ) : null}

        {deal?.lead_analysis_id ? (
          (() => {
            const analysisId = deal.lead_analysis_id;
            return (
              <LeadAnalysisSummary
                id={analysisId}
                fromDealId={dealId}
                onOpenDetail={() => setDetailAnalysisId(analysisId)}
              />
            );
          })()
        ) : null}

        {/* Documents Drive du deal (après le résumé d'analyse s'il existe,
            sinon en haut sous le header) */}
        {deal ? (
          <EntityDriveSection entityType="ProspectionDeal" entityId={dealId} />
        ) : null}

        <OfferSection dealId={dealId} />

        <NDASection dealId={dealId} />

        <TaskBoard
          tasks={boardItems}
          users={users}
          immeubles={immeubles}
          immeubleScope={{ deal_id: dealId }}
          onImmeublesChanged={() => void reloadImmeubles()}
          onPatch={(taskId, patch) => {
            const out: Partial<Task> = {};
            if (patch.title !== undefined) out.name = patch.title;
            if (patch.notes !== undefined) out.notes = patch.notes;
            if (patch.status !== undefined) out.status = patch.status;
            if (patch.priority !== undefined) out.priority = patch.priority;
            if (patch.due_date !== undefined) out.due_date = patch.due_date;
            if (patch.position !== undefined) out.position = patch.position;
            if (patch.assignee_user_ids !== undefined) {
              out.assignee_user_ids = patch.assignee_user_ids;
              out.assignee_user_id = patch.assignee_user_ids[0] ?? null;
            }
            if (patch.immeuble_ids !== undefined) {
              out.immeuble_ids = patch.immeuble_ids;
            }
            if (patch.departement !== undefined) out.departement = patch.departement;
            if (patch.impact !== undefined) out.impact = patch.impact;
            if (patch.confidence !== undefined) out.confidence = patch.confidence;
            if (patch.effort !== undefined) out.effort = patch.effort;
            void patchTask(taskId, out);
          }}
          onDelete={(taskId) => void deleteTaskById(taskId)}
          onMove={(taskId) => {
            const t = tasks.find((x) => x.id === taskId);
            if (t) setMoveTask(t);
          }}
          onCreate={(status, name) => createTask(status, name)}
        />
      </div>

      {moveTask ? (
        <MoveTaskToDealDialog
          task={moveTask}
          currentDealId={dealId}
          onClose={() => setMoveTask(null)}
          onMoved={() => {
            // La tâche est partie sur un autre deal — on la retire
            // de la liste locale.
            setTasks((xs) => xs.filter((x) => x.id !== moveTask.id));
            setMoveTask(null);
          }}
        />
      ) : null}

      {/* Modal d'analyse en overlay sur la page du Deal — évite la
          navigation vers /analyses-leads (où le lead n'apparaît plus
          puisqu'il a été converti). Phil reste dans le contexte du
          Deal et voit la fiche par-dessus. */}
      {detailAnalysisId != null ? (
        <LeadAnalysisDetailModal
          analysisId={detailAnalysisId}
          open
          onClose={() => setDetailAnalysisId(null)}
          onAfterUpdate={() => {
            // Le résumé <LeadAnalysisSummary> refait son fetch au
            // remount, mais ses chiffres principaux peuvent avoir
            // changé. On force un re-render léger via setState
            // (load() ferait trop : nouvelles tâches, etc.).
            // Note : le résumé écoute déjà `id` ; pour le refresh
            // visuel après save, c'est suffisant.
          }}
        />
      ) : null}
    </>
  );
}

/**
 * Dialogue qui demande le deal cible pour déplacer une tâche.
 * Liste les autres deals (sauf le courant) et patche
 * ProspectionDealTask.deal_id côté serveur.
 */
function MoveTaskToDealDialog({
  task,
  currentDealId,
  onClose,
  onMoved
}: {
  task: Task;
  currentDealId: number;
  onClose: () => void;
  onMoved: () => void;
}) {
  const [list, setList] = useState<Deal[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const res = await authedFetch("/api/v1/prospection/deals");
        if (!res.ok) throw new Error();
        const all = (await res.json()) as Deal[];
        setList(all.filter((d) => d.id !== currentDealId));
      } catch {
        setErr("Impossible de charger la liste des deals.");
      } finally {
        setLoading(false);
      }
    })();
  }, [currentDealId]);

  async function move(targetId: number) {
    setBusy(true);
    setErr(null);
    try {
      const res = await authedFetch(
        `/api/v1/prospection/deals/${currentDealId}/tasks/${task.id}`,
        {
          method: "PATCH",
          body: JSON.stringify({ deal_id: targetId })
        }
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      onMoved();
    } catch (e) {
      setErr((e as Error).message || "Déplacement échoué.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4"
      onClick={() => (!busy ? onClose() : null)}
    >
      <div
        className="w-full max-w-md rounded-2xl border border-brand-800 bg-brand-950 p-5"
        onClick={(e) => e.stopPropagation()}
      >
        <h3 className="text-base font-bold text-white">
          Déplacer « {task.name} »
        </h3>
        <p className="mt-1 text-xs text-white/50">
          Choisis le deal vers lequel déplacer la tâche.
        </p>

        {loading ? (
          <div className="flex items-center justify-center py-8">
            <Loader2 className="h-5 w-5 animate-spin text-accent-500" />
          </div>
        ) : list.length === 0 ? (
          <p className="mt-4 rounded-md border border-dashed border-brand-800 bg-brand-900/40 px-3 py-3 text-center text-xs text-white/50">
            Aucun autre deal — créez-en un dans Pipeline.
          </p>
        ) : (
          <ul className="mt-4 max-h-72 space-y-1 overflow-y-auto">
            {list.map((d) => (
              <li key={d.id}>
                <button
                  type="button"
                  onClick={() => move(d.id)}
                  disabled={busy}
                  className="flex w-full items-center gap-2 rounded-lg border border-brand-800 bg-brand-900 px-3 py-2 text-left text-sm text-white hover:border-emerald-500/50 hover:bg-emerald-500/10 disabled:opacity-50"
                >
                  <MapPin className="h-3.5 w-3.5 flex-shrink-0 text-emerald-400" />
                  <span className="truncate">{d.address}</span>
                </button>
              </li>
            ))}
          </ul>
        )}

        {err ? (
          <p className="mt-3 rounded-md border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
            {err}
          </p>
        ) : null}

        <div className="mt-4 flex items-center justify-end">
          <button
            type="button"
            onClick={onClose}
            disabled={busy}
            className="btn-secondary text-sm"
          >
            Annuler
          </button>
        </div>
      </div>
    </div>
  );
}

