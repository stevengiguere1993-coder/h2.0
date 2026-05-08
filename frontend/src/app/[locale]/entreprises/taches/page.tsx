"use client";

import { useEffect, useMemo, useState } from "react";
import { ChevronDown, ChevronUp, Loader2, Target } from "lucide-react";

import { authedFetch } from "@/lib/auth";
import { QGTopbar } from "../layout";
import {
  TaskBoard,
  type TaskBoardItem,
  type ExtraColumnConfig
} from "@/components/task-board";
import type { TaskUserMini } from "@/components/task-pills";
import type { ImmeubleMini } from "@/components/immeuble-picker";

/**
 * Vue agrégée « Tâches » sous Navigation — toutes les tâches de
 * toutes les entreprises ET de tous les deals du Pipeline. Reprend
 * intégralement la structure visuelle et fonctionnelle de
 * <TaskBoard> (cartes Kanban / vue Tableau / pastilles dot+label /
 * pastille P · score / fiche détaillée modal partagée).
 *
 *   - Bandeau au-dessus avec un toggle « Toutes / Mes tâches »
 *     (filtre par défaut sur l'utilisateur courant).
 *   - Briefing IA en haut (le plus récent toutes entreprises
 *     confondues), même look que la fiche entreprise.
 *   - Pas de « + Nouvelle tâche » ici (création depuis la fiche
 *     d'une entreprise ou d'un deal).
 *   - Colonne « Entreprise / Deal » dans le tableau (avec
 *     filtre/tri) ; même info en footer dans le kanban.
 */

type TacheEnt = {
  id: number;
  entreprise_id: number;
  title: string;
  description: string | null;
  departement: string | null;
  status: string;
  priority: string;
  impact: number | null;
  confidence: number | null;
  effort: number | null;
  due_date: string | null;
  recurrence: string | null;
  score: number | null;
  assignee_user_id: number | null;
  assignee_user_ids: number[];
  immeuble_ids: number[];
  position: number;
};

type TacheDeal = {
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
};

type Entreprise = {
  id: number;
  name: string;
  color_accent: string;
  is_active?: boolean;
};

type Deal = {
  id: number;
  address: string;
  priority: string;
};

type DailyBriefing = {
  id: number;
  entreprise_id: number;
  period_start: string;
  period_end: string;
  headline: string;
  summary_text: string;
  highlights: string[];
  model_used: string | null;
  provider: string | null;
  created_at: string;
};

/** Source d'une tâche, encodé dans son groupId pour la colonne
 *  « Entreprise / Deal » (ex. "ent:42", "deal:7"). Permet de router
 *  patch/delete vers la bonne API. */
type TaskOwner =
  | { kind: "entreprise"; id: number }
  | { kind: "deal"; id: number };

function ownerKey(o: TaskOwner): string {
  return `${o.kind}:${o.id}`;
}

export default function MesTachesPage() {
  const [tachesEnt, setTachesEnt] = useState<TacheEnt[]>([]);
  const [tachesDeal, setTachesDeal] = useState<TacheDeal[]>([]);
  const [entreprises, setEntreprises] = useState<Entreprise[]>([]);
  const [deals, setDeals] = useState<Deal[]>([]);
  const [users, setUsers] = useState<TaskUserMini[]>([]);
  const [immeubles, setImmeubles] = useState<ImmeubleMini[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [scope, setScope] = useState<"all" | "mine">("all");

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      setLoading(true);
      setError(null);
      try {
        const tachesUrl =
          scope === "mine"
            ? "/api/v1/entreprises/taches?mine=true"
            : "/api/v1/entreprises/taches";
        const [tRes, eRes, dRes, uRes, iRes] = await Promise.all([
          authedFetch(tachesUrl),
          authedFetch("/api/v1/entreprises"),
          authedFetch("/api/v1/prospection/deals"),
          authedFetch("/api/v1/users"),
          authedFetch("/api/v1/immobilier/immeubles/picker")
        ]);
        if (cancelled) return;
        if (!tRes.ok) throw new Error(`HTTP ${tRes.status}`);
        // Exclut les entreprises fermées (is_active=false) et les
        // deals archivés (priority termine/abandonne) — leurs
        // tâches n'apparaissent pas dans la vue agrégée.
        const allEntreprises = eRes.ok
          ? ((await eRes.json()) as Entreprise[])
          : [];
        const activeEntreprises = allEntreprises.filter(
          (e) => e.is_active !== false
        );
        const activeEntIds = new Set(activeEntreprises.map((e) => e.id));
        setEntreprises(activeEntreprises);
        const allDeals = dRes.ok ? ((await dRes.json()) as Deal[]) : [];
        const activeDeals = allDeals.filter(
          (d) => d.priority !== "termine" && d.priority !== "abandonne"
        );
        if (!cancelled) setDeals(activeDeals);
        if (uRes.ok) {
          const all = (await uRes.json()) as Array<
            TaskUserMini & { volets?: string[] }
          >;
          // Pas de filtre par volet : la vue est cross-volet.
          setUsers(all);
        }
        if (iRes.ok) setImmeubles((await iRes.json()) as ImmeubleMini[]);
        const allTachesEnt = (await tRes.json()) as TacheEnt[];
        setTachesEnt(
          allTachesEnt.filter((t) => activeEntIds.has(t.entreprise_id))
        );

        // Tâches des deals — pas d'endpoint global, on agrège par
        // deal actif en parallèle. Les deals archivés
        // (Terminé/Abandonné) ne sont pas interrogés.
        const dealTaskLists = await Promise.all(
          activeDeals.map(async (d) => {
            try {
              const r = await authedFetch(
                `/api/v1/prospection/deals/${d.id}/tasks`
              );
              if (!r.ok) return [] as TacheDeal[];
              return (await r.json()) as TacheDeal[];
            } catch {
              return [] as TacheDeal[];
            }
          })
        );
        if (!cancelled) setTachesDeal(dealTaskLists.flat());
      } catch (err) {
        if (!cancelled) setError((err as Error).message);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [scope]);

  // En mode « Mes tâches » côté deal, filtrage client-side.
  // L'utilisateur courant est implicite dans le filtre serveur des
  // entreprises ; pour les deals il faut comparer aux assignees. On
  // n'a pas l'id courant ici, mais le serveur a déjà filtré pour
  // l'ent — pour l'instant les tâches de deal sont gardées telles
  // quelles. (Un /me serait nécessaire pour un vrai filtre miroir.)

  async function patchTache(
    owner: TaskOwner,
    taskId: number,
    patch: Record<string, unknown>
  ) {
    if (owner.kind === "entreprise") {
      const before = tachesEnt;
      setTachesEnt((prev) =>
        prev.map((t) => (t.id === taskId ? { ...t, ...patch } : t))
      );
      try {
        const res = await authedFetch(
          `/api/v1/entreprises/taches/${taskId}`,
          {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(patch)
          }
        );
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const updated = (await res.json()) as TacheEnt;
        setTachesEnt((prev) =>
          prev.map((t) => (t.id === taskId ? { ...t, ...updated } : t))
        );
      } catch (err) {
        setTachesEnt(before);
        setError(`Échec mise à jour : ${(err as Error).message}`);
      }
    } else {
      const before = tachesDeal;
      setTachesDeal((prev) =>
        prev.map((t) => (t.id === taskId ? { ...t, ...patch } : t))
      );
      try {
        const res = await authedFetch(
          `/api/v1/prospection/deals/${owner.id}/tasks/${taskId}`,
          {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(patch)
          }
        );
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const updated = (await res.json()) as TacheDeal;
        setTachesDeal((prev) =>
          prev.map((t) => (t.id === taskId ? { ...t, ...updated } : t))
        );
      } catch (err) {
        setTachesDeal(before);
        setError(`Échec mise à jour : ${(err as Error).message}`);
      }
    }
  }

  async function deleteTache(owner: TaskOwner, taskId: number) {
    if (owner.kind === "entreprise") {
      const before = tachesEnt;
      setTachesEnt((prev) => prev.filter((t) => t.id !== taskId));
      try {
        const res = await authedFetch(
          `/api/v1/entreprises/taches/${taskId}`,
          { method: "DELETE" }
        );
        if (!res.ok && res.status !== 204) throw new Error();
      } catch {
        setTachesEnt(before);
        setError("Suppression échouée.");
      }
    } else {
      const before = tachesDeal;
      setTachesDeal((prev) => prev.filter((t) => t.id !== taskId));
      try {
        const res = await authedFetch(
          `/api/v1/prospection/deals/${owner.id}/tasks/${taskId}`,
          { method: "DELETE" }
        );
        if (!res.ok && res.status !== 204) throw new Error();
      } catch {
        setTachesDeal(before);
        setError("Suppression échouée.");
      }
    }
  }

  async function reloadImmeubles() {
    try {
      const r = await authedFetch("/api/v1/immobilier/immeubles/picker");
      if (r.ok) setImmeubles((await r.json()) as ImmeubleMini[]);
    } catch {
      /* ignore */
    }
  }

  const entById = useMemo(() => {
    const m = new Map<number, Entreprise>();
    entreprises.forEach((e) => m.set(e.id, e));
    return m;
  }, [entreprises]);

  const dealById = useMemo(() => {
    const m = new Map<number, Deal>();
    deals.forEach((d) => m.set(d.id, d));
    return m;
  }, [deals]);

  const immeubleNameById = useMemo(
    () => new Map(immeubles.map((i) => [i.id, i.name] as const)),
    [immeubles]
  );

  // Pour rendre les ids uniques (les séquences entreprise/deal sont
  // indépendantes), on préfixe : entreprise → +0, deal → +10_000_000.
  // Cet offset reste interne au board ; toute API réelle reçoit
  // l'id original via le owner.
  const DEAL_ID_OFFSET = 10_000_000;
  const toBoardId = (owner: TaskOwner, realId: number): number =>
    owner.kind === "entreprise" ? realId : DEAL_ID_OFFSET + realId;
  const fromBoardId = (boardId: number): { id: number; isDeal: boolean } =>
    boardId >= DEAL_ID_OFFSET
      ? { id: boardId - DEAL_ID_OFFSET, isDeal: true }
      : { id: boardId, isDeal: false };

  // Map : board id → owner réel
  const ownerByBoardId = useMemo(() => {
    const m = new Map<number, TaskOwner>();
    tachesEnt.forEach((t) =>
      m.set(toBoardId({ kind: "entreprise", id: t.entreprise_id }, t.id), {
        kind: "entreprise",
        id: t.entreprise_id
      })
    );
    tachesDeal.forEach((t) =>
      m.set(toBoardId({ kind: "deal", id: t.deal_id }, t.id), {
        kind: "deal",
        id: t.deal_id
      })
    );
    return m;
  }, [tachesEnt, tachesDeal]);

  const ownerBadge = (owner: TaskOwner | null) => {
    if (!owner) return null;
    if (owner.kind === "entreprise") {
      const ent = entById.get(owner.id);
      if (!ent) return null;
      return (
        <span
          className="inline-flex items-center gap-1 rounded-full bg-white/5 px-1.5 py-0.5 text-[9px] font-medium text-white/60"
          title={`Entreprise : ${ent.name}`}
        >
          <span
            className="h-1.5 w-1.5 rounded-full"
            style={{ backgroundColor: ent.color_accent }}
          />
          <span className="truncate max-w-[140px]">{ent.name}</span>
        </span>
      );
    }
    const deal = dealById.get(owner.id);
    if (!deal) return null;
    return (
      <span
        className="inline-flex items-center gap-1 rounded-full bg-violet-500/10 px-1.5 py-0.5 text-[9px] font-medium text-violet-200"
        title={`Deal : ${deal.address}`}
      >
        <span className="h-1.5 w-1.5 rounded-full bg-violet-400" />
        <span className="truncate max-w-[140px]">{deal.address}</span>
      </span>
    );
  };

  // Mappage TacheEnt | TacheDeal → TaskBoardItem unifié.
  const boardItems: TaskBoardItem[] = useMemo(() => {
    const items: TaskBoardItem[] = [];
    tachesEnt.forEach((t) => {
      const owner: TaskOwner = { kind: "entreprise", id: t.entreprise_id };
      items.push({
        id: toBoardId(owner, t.id),
        title: t.title,
        status: t.status,
        priority: t.priority || "non_assigne",
        due_date: t.due_date,
        assignee_user_ids: t.assignee_user_ids || [],
        hasNote: Boolean(t.description),
        notes: t.description,
        departement: t.departement,
        recurrence: t.recurrence,
        impact: t.impact,
        confidence: t.confidence,
        effort: t.effort,
        score: t.score,
        position: t.score != null ? -Math.round(t.score * 1000) : 0,
        immeuble_ids: t.immeuble_ids || [],
        immeubleLabels: (t.immeuble_ids || [])
          .map((id) => immeubleNameById.get(id))
          .filter((n): n is string => Boolean(n)),
        footer: ownerBadge(owner)
      });
    });
    tachesDeal.forEach((t) => {
      const owner: TaskOwner = { kind: "deal", id: t.deal_id };
      items.push({
        id: toBoardId(owner, t.id),
        title: t.name,
        status: t.status,
        priority: t.priority || "non_assigne",
        due_date: t.due_date,
        assignee_user_ids: t.assignee_user_ids || [],
        hasNote: Boolean(t.notes),
        notes: t.notes,
        departement: t.departement,
        recurrence: t.recurrence,
        impact: t.impact,
        confidence: t.confidence,
        effort: t.effort,
        score: t.score,
        position: t.score != null ? -Math.round(t.score * 1000) : 0,
        immeuble_ids: t.immeuble_ids || [],
        immeubleLabels: (t.immeuble_ids || [])
          .map((id) => immeubleNameById.get(id))
          .filter((n): n is string => Boolean(n)),
        footer: ownerBadge(owner)
      });
    });
    return items;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tachesEnt, tachesDeal, entById, dealById, immeubleNameById]);

  // Configuration de la colonne « Entreprise / Deal » : permet
  // filtre/tri via le picker standard de TaskBoard.
  const extraColumn: ExtraColumnConfig = useMemo(() => {
    const filterValues: Array<{ value: string; label: string }> = [];
    entreprises.forEach((e) =>
      filterValues.push({
        value: ownerKey({ kind: "entreprise", id: e.id }),
        label: e.name
      })
    );
    deals.forEach((d) =>
      filterValues.push({
        value: ownerKey({ kind: "deal", id: d.id }),
        label: d.address
      })
    );
    return {
      label: "Entreprise / Deal",
      width: "200px",
      render: (item) => ownerBadge(ownerByBoardId.get(item.id) ?? null),
      filterValues,
      getGroupId: (item) => {
        const owner = ownerByBoardId.get(item.id);
        return owner ? ownerKey(owner) : null;
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [entreprises, deals, ownerByBoardId]);

  const subtitle = `${boardItems.length} TÂCHE${
    boardItems.length > 1 ? "S" : ""
  }`;

  return (
    <>
      <QGTopbar
        greeting={
          <>
            Mes{" "}
            <span
              className="italic"
              style={{
                color: "var(--qg-accent)",
                fontFamily: "var(--font-fraunces, Georgia, serif)"
              }}
            >
              tâches
            </span>
          </>
        }
        subtitle={subtitle}
      />

      <div className="px-5 py-6 lg:px-8">
        {/* Briefing IA — agrégé sur toutes les entreprises. */}
        <GlobalBriefingCard entreprises={entreprises} />

        {/* Bandeau filtres niveau page : portée. Le filtre par
            entreprise/deal est dans la barre d'outils du TaskBoard. */}
        <div className="mb-4 mt-4 flex flex-wrap items-center gap-2">
          <div className="inline-flex rounded-lg border border-[var(--qg-border)] bg-[var(--qg-card-bg)] p-0.5">
            <ScopeButton
              label="Toutes les tâches"
              active={scope === "all"}
              onClick={() => setScope("all")}
            />
            <ScopeButton
              label="Mes tâches"
              active={scope === "mine"}
              onClick={() => setScope("mine")}
            />
          </div>
        </div>

        {error ? (
          <p className="mb-3 rounded-md border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-300">
            {error}
          </p>
        ) : null}

        {loading ? (
          <div className="flex min-h-[300px] items-center justify-center rounded-xl border border-[var(--qg-border)] bg-[var(--qg-card-bg)]">
            <Loader2 className="h-5 w-5 animate-spin text-[var(--qg-accent)]" />
          </div>
        ) : boardItems.length === 0 ? (
          <div className="rounded-xl border border-[var(--qg-border)] bg-[var(--qg-card-bg)] px-6 py-12 text-center">
            <Target className="mx-auto h-8 w-8 text-[var(--qg-text-faint)]" />
            <p className="mt-3 text-sm text-[var(--qg-text-muted)]">
              Aucune tâche pour ces filtres.
            </p>
          </div>
        ) : (
          <TaskBoard
            tasks={boardItems}
            users={users}
            immeubles={immeubles}
            onImmeublesChanged={() => void reloadImmeubles()}
            showNewTaskButton={false}
            title="Toutes les tâches"
            extraColumn={extraColumn}
            onPatch={(boardId, patch) => {
              const owner = ownerByBoardId.get(boardId);
              if (!owner) return;
              const { id: realId } = fromBoardId(boardId);
              if (owner.kind === "entreprise") {
                const out: Record<string, unknown> = {};
                if (patch.title !== undefined) out.title = patch.title;
                if (patch.notes !== undefined) out.description = patch.notes;
                if (patch.status !== undefined) out.status = patch.status;
                if (patch.priority !== undefined)
                  out.priority = patch.priority;
                if (patch.due_date !== undefined)
                  out.due_date = patch.due_date;
                if (patch.assignee_user_ids !== undefined) {
                  out.assignee_user_ids = patch.assignee_user_ids;
                  out.assignee_user_id =
                    patch.assignee_user_ids[0] ?? null;
                }
                if (patch.immeuble_ids !== undefined)
                  out.immeuble_ids = patch.immeuble_ids;
                if (patch.departement !== undefined)
                  out.departement = patch.departement;
                if (patch.recurrence !== undefined)
                  out.recurrence = patch.recurrence;
                if (patch.impact !== undefined) out.impact = patch.impact;
                if (patch.confidence !== undefined)
                  out.confidence = patch.confidence;
                if (patch.effort !== undefined) out.effort = patch.effort;
                void patchTache(owner, realId, out);
              } else {
                // Côté deal le titre est `name` (pas `title`).
                const out: Record<string, unknown> = {};
                if (patch.title !== undefined) out.name = patch.title;
                if (patch.notes !== undefined) out.notes = patch.notes;
                if (patch.status !== undefined) out.status = patch.status;
                if (patch.priority !== undefined)
                  out.priority = patch.priority;
                if (patch.due_date !== undefined)
                  out.due_date = patch.due_date;
                if (patch.assignee_user_ids !== undefined) {
                  out.assignee_user_ids = patch.assignee_user_ids;
                  out.assignee_user_id =
                    patch.assignee_user_ids[0] ?? null;
                }
                if (patch.immeuble_ids !== undefined)
                  out.immeuble_ids = patch.immeuble_ids;
                if (patch.departement !== undefined)
                  out.departement = patch.departement;
                if (patch.recurrence !== undefined)
                  out.recurrence = patch.recurrence;
                if (patch.impact !== undefined) out.impact = patch.impact;
                if (patch.confidence !== undefined)
                  out.confidence = patch.confidence;
                if (patch.effort !== undefined) out.effort = patch.effort;
                void patchTache(owner, realId, out);
              }
            }}
            onDelete={(boardId) => {
              const owner = ownerByBoardId.get(boardId);
              if (!owner) return;
              const { id: realId } = fromBoardId(boardId);
              void deleteTache(owner, realId);
            }}
            // Pas de onCreate effectif — la création se fait dans la
            // fiche d'une entreprise ou d'un deal.
            onCreate={() => null}
          />
        )}
      </div>
    </>
  );
}

function ScopeButton({
  label,
  active,
  onClick
}: {
  label: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="rounded-md px-3 py-1 text-[11px] font-semibold transition"
      style={{
        backgroundColor: active ? "var(--qg-accent)" : "transparent",
        color: active ? "var(--qg-bg)" : "var(--qg-text-muted)"
      }}
    >
      {label}
    </button>
  );
}

// ─── Briefing IA — vue globale ──────────────────────────────────────
//
// Pas d'endpoint global dédié : on agrège les briefings existants
// (un par entreprise, idempotent par jour) et on affiche le plus
// récent — avec un sélecteur si plusieurs sont disponibles. Même
// look que <DailyPulseCard> de la fiche entreprise.

function GlobalBriefingCard({
  entreprises
}: {
  entreprises: Entreprise[];
}) {
  const [briefings, setBriefings] = useState<
    Array<{ ent: Entreprise; brief: DailyBriefing }>
  >([]);
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState(true);
  const [activeEntId, setActiveEntId] = useState<number | null>(null);

  useEffect(() => {
    if (entreprises.length === 0) {
      setBriefings([]);
      setLoading(false);
      return;
    }
    let cancelled = false;
    void (async () => {
      setLoading(true);
      try {
        const results = await Promise.all(
          entreprises.map(async (e) => {
            try {
              const r = await authedFetch(
                `/api/v1/entreprises/${e.id}/daily-pulse`
              );
              if (!r.ok) return null;
              const data = (await r.json()) as DailyBriefing | null;
              return data ? { ent: e, brief: data } : null;
            } catch {
              return null;
            }
          })
        );
        if (cancelled) return;
        const list = results.filter(
          (x): x is { ent: Entreprise; brief: DailyBriefing } => x !== null
        );
        // Ordre : briefing le plus récent en tête.
        list.sort((a, b) =>
          b.brief.created_at.localeCompare(a.brief.created_at)
        );
        setBriefings(list);
        setActiveEntId((prev) =>
          prev != null && list.some((x) => x.ent.id === prev)
            ? prev
            : list[0]?.ent.id ?? null
        );
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [entreprises]);

  const lime = "var(--qg-accent)";
  const active =
    briefings.find((x) => x.ent.id === activeEntId) ?? briefings[0] ?? null;

  return (
    <section
      className="overflow-hidden rounded-2xl border bg-brand-900 p-5"
      style={{ borderColor: lime + "44" }}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-2">
          <span className="relative flex h-2.5 w-2.5" title="IA active">
            <span
              className="absolute inline-flex h-full w-full animate-ping rounded-full opacity-60"
              style={{ backgroundColor: lime }}
            />
            <span
              className="relative inline-flex h-2.5 w-2.5 rounded-full"
              style={{ backgroundColor: lime }}
            />
          </span>
          <h2
            className="text-xs font-bold uppercase tracking-wider"
            style={{ color: lime }}
          >
            ✦ Briefing IA du jour
          </h2>
        </div>
        <div className="flex items-center gap-2">
          {briefings.length > 1 ? (
            <select
              value={activeEntId ?? ""}
              onChange={(e) => setActiveEntId(Number(e.target.value))}
              className="rounded-md border border-brand-700 bg-brand-900 px-2 py-1 text-[11px] text-white/80 focus:border-accent-500 focus:outline-none"
              title="Choisir l'entreprise"
            >
              {briefings.map(({ ent }) => (
                <option key={ent.id} value={ent.id}>
                  {ent.name}
                </option>
              ))}
            </select>
          ) : null}
          <button
            type="button"
            onClick={() => setExpanded((v) => !v)}
            title={expanded ? "Réduire" : "Étendre"}
            aria-label={expanded ? "Réduire le briefing" : "Étendre le briefing"}
            className="rounded-md border border-brand-700 bg-brand-900 p-1 text-white/60 transition hover:text-white"
          >
            {expanded ? (
              <ChevronUp className="h-3.5 w-3.5" />
            ) : (
              <ChevronDown className="h-3.5 w-3.5" />
            )}
          </button>
        </div>
      </div>

      {!expanded ? null : loading ? (
        <p className="mt-3 text-xs text-white/40">Chargement…</p>
      ) : active ? (
        <div className="mt-3">
          <p className="text-[10px] uppercase tracking-wider text-white/40">
            <span
              className="mr-1.5 inline-block h-2 w-2 rounded-full align-middle"
              style={{ backgroundColor: active.ent.color_accent }}
            />
            {active.ent.name}
          </p>
          <h3 className="mt-1 text-base font-bold text-white">
            {active.brief.headline}
          </h3>
          <p className="mt-1 text-[10px] text-white/40">
            Généré le{" "}
            {new Date(active.brief.created_at).toLocaleString("fr-CA", {
              dateStyle: "medium",
              timeStyle: "short"
            })}
            {active.brief.provider ? ` · ${active.brief.provider}` : ""}
            {active.brief.model_used ? ` · ${active.brief.model_used}` : ""}
          </p>
          <p className="mt-2 whitespace-pre-line text-sm leading-relaxed text-white/80">
            {active.brief.summary_text}
          </p>
          {active.brief.highlights && active.brief.highlights.length > 0 ? (
            <ul className="mt-3 space-y-1">
              {active.brief.highlights.map((h, i) => (
                <li
                  key={i}
                  className="flex items-start gap-2 text-xs text-white/70"
                >
                  <span style={{ color: lime }}>•</span>
                  <span>{h}</span>
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : (
        <p className="mt-3 text-xs text-white/60">
          Aucun briefing disponible. Générez-en un depuis la fiche d&apos;une
          entreprise.
        </p>
      )}
    </section>
  );
}
