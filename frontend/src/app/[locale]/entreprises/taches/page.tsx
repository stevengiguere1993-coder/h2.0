"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  ChevronDown,
  ChevronUp,
  Loader2,
  Repeat,
  Target,
  X
} from "lucide-react";

import { authedFetch } from "@/lib/auth";
import { useCurrentUser } from "@/hooks/use-current-user";
import { Link } from "@/i18n/navigation";
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
  created_at?: string;
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
  created_at?: string;
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
  const { user: currentUser } = useCurrentUser();
  const [tachesEnt, setTachesEnt] = useState<TacheEnt[]>([]);
  const [tachesDeal, setTachesDeal] = useState<TacheDeal[]>([]);
  const [entreprises, setEntreprises] = useState<Entreprise[]>([]);
  const [deals, setDeals] = useState<Deal[]>([]);
  const [users, setUsers] = useState<TaskUserMini[]>([]);
  const [immeubles, setImmeubles] = useState<ImmeubleMini[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [scope, setScope] = useState<"all" | "mine">("mine");
  // Ouverture directe en vue Cartes via ?view=cartes (raccourci / app
  // « Mes tâches »). Lu côté client ; le TaskBoard ne monte qu'après le
  // chargement (donc window est dispo) → defaultView correct d'entrée.
  const forceCartes =
    typeof window !== "undefined" &&
    new URLSearchParams(window.location.search).get("view") === "cartes";
  // Modale de choix entreprise / deal lors de la création d'une
  // tâche depuis le bouton « + Nouvelle tâche » du TaskBoard.
  // Quand non-null, contient le statut cible (todo / a_faire …) et
  // se résoud via la promesse stockée dans `createResolverRef`.
  const [pendingCreate, setPendingCreate] = useState<{
    status: string;
    name: string;
  } | null>(null);
  const createResolverRef = useRef<((id: number | null) => void) | null>(
    null
  );

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
        // En mode « Mes tâches », filtre les tâches de deals
        // (l'endpoint deals/{id}/tasks ne supporte pas `mine` côté
        // serveur, donc on filtre côté client). Inclut le user comme
        // primary ET comme co-assignee.
        let dealTasksFlat = dealTaskLists.flat();
        if (scope === "mine" && currentUser?.id) {
          const myId = currentUser.id;
          dealTasksFlat = dealTasksFlat.filter((t) => {
            const ids = t.assignee_user_ids || [];
            if (t.assignee_user_id === myId) return true;
            return ids.includes(myId);
          });
        }
        if (!cancelled) setTachesDeal(dealTasksFlat);
      } catch (err) {
        if (!cancelled) setError((err as Error).message);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [scope, currentUser?.id]);

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

  // Préfixe pour rendre les ids uniques entre les séquences
  // entreprise / deal indépendantes.
  const DEAL_ID_OFFSET = 10_000_000;
  const boardIdFor = (owner: TaskOwner, realId: number): number =>
    owner.kind === "entreprise" ? realId : DEAL_ID_OFFSET + realId;

  /** Crée une tâche pour un owner choisi (entreprise ou deal).
   *  Retourne le board id (préfixé) pour que le TaskBoard puisse
   *  ouvrir la fiche détaillée. */
  async function createTacheFor(
    owner: TaskOwner,
    status: string,
    name: string
  ): Promise<number | null> {
    try {
      if (owner.kind === "entreprise") {
        const res = await authedFetch("/api/v1/entreprises/taches", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            entreprise_id: owner.id,
            title: name,
            status
          })
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const created = (await res.json()) as TacheEnt;
        setTachesEnt((prev) => [...prev, created]);
        return boardIdFor(owner, created.id);
      }
      const res = await authedFetch(
        `/api/v1/prospection/deals/${owner.id}/tasks`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ name, status })
        }
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const created = (await res.json()) as TacheDeal;
      setTachesDeal((prev) => [...prev, created]);
      return boardIdFor(owner, created.id);
    } catch (err) {
      setError(`Création échouée : ${(err as Error).message}`);
      return null;
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
  // L'offset est défini plus haut (boardIdFor / DEAL_ID_OFFSET).
  const toBoardId = boardIdFor;
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
    // toBoardId est un alias stable (= boardIdFor), pas de re-render
    // induit par sa référence.
    // eslint-disable-next-line react-hooks/exhaustive-deps
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
        created_at: t.created_at,
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
        created_at: t.created_at,
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
        {/* Briefing IA — bascule entre vue globale (toutes entreprises)
            et vue scopée à l'utilisateur connecté selon le toggle
            « Toutes / Mes tâches » ci-dessous. */}
        <GlobalBriefingCard entreprises={entreprises} scope={scope} />

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
            defaultView={forceCartes ? "cartes" : "kanban"}
            currentUserId={currentUser?.id ?? null}
            immeubles={immeubles}
            onImmeublesChanged={() => void reloadImmeubles()}
            showNewTaskButton
            newTaskLabel="+ Nouvelle tâche"
            title="Toutes les tâches"
            extraColumn={extraColumn}
            headerSlot={
              <Link
                // eslint-disable-next-line @typescript-eslint/no-explicit-any
                href={"/entreprises/taches/recurrentes" as any}
                className="inline-flex items-center gap-1.5 rounded-lg bg-violet-400 px-3 py-1.5 text-xs font-semibold text-brand-950 shadow hover:bg-violet-300"
                title="Gérer les modèles de tâches récurrentes"
              >
                <Repeat className="h-3.5 w-3.5" />
                Modèles récurrents
              </Link>
            }
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
            // Demande d'abord à quelle entreprise / deal rattacher la
            // tâche (sinon elle ne serait liée à rien). Ouvre une
            // modale ; le promise se résoud avec l'id board créé.
            onCreate={(status, name) =>
              new Promise<number | null>((resolve) => {
                createResolverRef.current = resolve;
                setPendingCreate({ status, name });
              })
            }
          />
        )}
      </div>

      {pendingCreate ? (
        <CreateTaskOwnerModal
          status={pendingCreate.status}
          name={pendingCreate.name}
          entreprises={entreprises}
          deals={deals}
          onCancel={() => {
            createResolverRef.current?.(null);
            createResolverRef.current = null;
            setPendingCreate(null);
          }}
          onConfirm={async (owner, finalName) => {
            const boardId = await createTacheFor(
              owner,
              pendingCreate.status,
              finalName
            );
            createResolverRef.current?.(boardId);
            createResolverRef.current = null;
            setPendingCreate(null);
          }}
        />
      ) : null}
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
  entreprises,
  scope
}: {
  entreprises: Entreprise[];
  scope: "all" | "mine";
}) {
  // Briefing — soit global cross-entreprise, soit filtré aux
  // tâches assignées à l'utilisateur connecté (scope="mine").
  // Cache backend distinct par scope.
  const [brief, setBrief] = useState<DailyBriefing | null>(null);
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [expanded, setExpanded] = useState(true);
  const [error, setError] = useState<string | null>(null);

  async function load(force: boolean) {
    if (entreprises.length === 0) {
      setBrief(null);
      setLoading(false);
      return;
    }
    if (force) setGenerating(true);
    else setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams();
      params.set("scope", scope);
      if (force) params.set("force", "true");
      const url = `/api/v1/entreprises/global-pulse?${params.toString()}`;
      const r = await authedFetch(url);
      if (!r.ok) {
        const txt = await r.text().catch(() => "");
        throw new Error(`HTTP ${r.status}${txt ? ` — ${txt.slice(0, 200)}` : ""}`);
      }
      const data = (await r.json()) as DailyBriefing | null;
      setBrief(data);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
      setGenerating(false);
    }
  }

  useEffect(() => {
    void load(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [entreprises.length, scope]);

  const lime = "var(--qg-accent)";

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
            ✦ Briefing IA —{" "}
            {scope === "mine" ? "mes tâches" : "toutes entreprises & deals"}
          </h2>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => void load(true)}
            disabled={generating}
            title="Regénérer le briefing global"
            className="rounded-md border border-brand-700 bg-brand-900 px-2.5 py-1 text-[10px] font-semibold text-white/60 hover:text-white disabled:opacity-50"
          >
            {generating ? "…" : "Regénérer"}
          </button>
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
      ) : brief ? (
        <div className="mt-3">
          <h3 className="text-base font-bold text-white">
            {brief.headline}
          </h3>
          <p className="mt-1 text-[10px] text-white/40">
            Généré le{" "}
            {new Date(brief.created_at).toLocaleString("fr-CA", {
              dateStyle: "medium",
              timeStyle: "short"
            })}
            {brief.provider ? ` · ${brief.provider}` : ""}
            {brief.model_used ? ` · ${brief.model_used}` : ""}
          </p>
          <p className="mt-2 whitespace-pre-line text-sm leading-relaxed text-white/80">
            {brief.summary_text}
          </p>
          {brief.highlights && brief.highlights.length > 0 ? (
            <ul className="mt-3 space-y-1">
              {brief.highlights.map((h, i) => (
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
          {error ? (
            <p className="mt-3 rounded-md border border-rose-500/40 bg-rose-500/10 px-2 py-1 text-[11px] text-rose-300">
              {error}
            </p>
          ) : null}
        </div>
      ) : error ? (
        <p className="mt-3 rounded-md border border-rose-500/40 bg-rose-500/10 px-2 py-1 text-[11px] text-rose-300">
          {error}
        </p>
      ) : (
        <p className="mt-3 text-xs text-white/60">
          Aucun briefing disponible. Cliquez « Regénérer » pour
          produire un résumé matinal cross-entreprise.
        </p>
      )}
    </section>
  );
}

// ─── Modale : choix entreprise / deal lors d'une création depuis
//     la vue agrégée. Évite que la tâche reste orpheline. ─────────

function CreateTaskOwnerModal({
  status,
  name: initialName,
  entreprises,
  deals,
  onCancel,
  onConfirm
}: {
  status: string;
  name: string;
  entreprises: Entreprise[];
  deals: Deal[];
  onCancel: () => void;
  onConfirm: (owner: TaskOwner, name: string) => void | Promise<void>;
}) {
  const [name, setName] = useState(initialName);
  const [ownerKeyValue, setOwnerKeyValue] = useState<string>("");
  const [busy, setBusy] = useState(false);

  const owner = useMemo(() => parseOwnerKey(ownerKeyValue), [ownerKeyValue]);

  async function submit() {
    if (!owner) return;
    const trimmed = name.trim();
    if (!trimmed) return;
    setBusy(true);
    try {
      await onConfirm(owner, trimmed);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/70 p-4 pt-16"
      onClick={onCancel}
    >
      <div
        className="w-full max-w-md rounded-2xl border border-brand-800 bg-brand-950 p-5 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-3 flex items-center justify-between">
          <h3 className="text-sm font-bold uppercase tracking-wider text-white/80">
            Nouvelle tâche
          </h3>
          <button
            type="button"
            onClick={onCancel}
            aria-label="Fermer"
            className="rounded-md p-1 text-white/40 hover:bg-white/5 hover:text-white"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <p className="mb-3 text-[11px] text-white/50">
          Statut : <span className="text-white/80">{status}</span>
        </p>

        <label className="block text-[11px] font-semibold uppercase tracking-wider text-white/50">
          Titre
        </label>
        <input
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
          autoFocus
          className="mt-1 w-full rounded-md border border-brand-800 bg-brand-900 px-3 py-2 text-sm text-white focus:border-accent-500 focus:outline-none"
          placeholder="Nom de la tâche…"
        />

        <label className="mt-4 block text-[11px] font-semibold uppercase tracking-wider text-white/50">
          Entreprise ou Deal*
        </label>
        <select
          value={ownerKeyValue}
          onChange={(e) => setOwnerKeyValue(e.target.value)}
          className="mt-1 w-full rounded-md border border-brand-800 bg-brand-900 px-3 py-2 text-sm text-white focus:border-accent-500 focus:outline-none"
        >
          <option value="">— Choisir —</option>
          {entreprises.length > 0 ? (
            <optgroup label="Entreprises">
              {entreprises.map((e) => (
                <option
                  key={`ent:${e.id}`}
                  value={ownerKey({ kind: "entreprise", id: e.id })}
                >
                  {e.name}
                </option>
              ))}
            </optgroup>
          ) : null}
          {deals.length > 0 ? (
            <optgroup label="Deals (Pipeline)">
              {deals.map((d) => (
                <option
                  key={`deal:${d.id}`}
                  value={ownerKey({ kind: "deal", id: d.id })}
                >
                  {d.address}
                </option>
              ))}
            </optgroup>
          ) : null}
        </select>
        <p className="mt-1 text-[10px] text-white/40">
          La tâche sera rattachée à cette fiche. Sans choix, la
          création est annulée.
        </p>

        <div className="mt-5 flex items-center justify-end gap-2">
          <button
            type="button"
            onClick={onCancel}
            className="rounded-md border border-brand-700 bg-brand-900 px-3 py-1.5 text-xs text-white/70 hover:text-white"
          >
            Annuler
          </button>
          <button
            type="button"
            onClick={() => void submit()}
            disabled={!owner || !name.trim() || busy}
            className="btn-accent text-xs disabled:cursor-not-allowed disabled:opacity-50"
          >
            {busy ? "Création…" : "Créer"}
          </button>
        </div>
      </div>
    </div>
  );
}

function parseOwnerKey(key: string): TaskOwner | null {
  const [kind, idStr] = key.split(":");
  const id = Number(idStr);
  if (!Number.isFinite(id)) return null;
  if (kind === "entreprise" || kind === "deal") {
    return { kind, id };
  }
  return null;
}
