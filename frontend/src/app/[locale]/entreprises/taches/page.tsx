"use client";

import { useEffect, useMemo, useState } from "react";
import { Loader2, Target } from "lucide-react";

import { authedFetch } from "@/lib/auth";
import { QGTopbar } from "../layout";
import { TaskBoard, type TaskBoardItem } from "@/components/task-board";
import type { TaskUserMini } from "@/components/task-pills";
import type { ImmeubleMini } from "@/components/immeuble-picker";

/**
 * Vue agrégée « Tâches » du volet Gestion d'entreprise — toutes les
 * tâches de toutes les entreprises dans une seule vue. Reprend
 * intégralement la structure visuelle et fonctionnelle de
 * <TaskBoard> (cartes Kanban / vue Tableau / pastilles dot+label /
 * pastille P · score / fiche détaillée modal partagée). Seules
 * différences :
 *   - Bandeau au-dessus avec un toggle « Toutes / Mes tâches »
 *     (filtre par défaut sur l'utilisateur courant).
 *   - Filtre supplémentaire « Entreprise » (la sidebar du TaskBoard
 *     filtre déjà sur Personne / Priorité / Échéance / Immeuble /
 *     Statut).
 *   - Pas de « + Nouvelle tâche » ici (créer une tâche se fait
 *     depuis la fiche d'une entreprise).
 *   - Footer de carte affiche le badge de l'entreprise propriétaire
 *     (puisque la vue est cross-entreprise).
 */

type Tache = {
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

type Entreprise = {
  id: number;
  name: string;
  color_accent: string;
};

export default function MesTachesPage() {
  const [taches, setTaches] = useState<Tache[]>([]);
  const [entreprises, setEntreprises] = useState<Entreprise[]>([]);
  const [users, setUsers] = useState<TaskUserMini[]>([]);
  const [immeubles, setImmeubles] = useState<ImmeubleMini[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Filtres niveau page : portée + entreprise. Le reste (statut,
  // priorité, personne, échéance, immeuble) est dans <TaskBoard>.
  const [scope, setScope] = useState<"all" | "mine">("all");
  const [filterEntreprise, setFilterEntreprise] = useState<string>("");

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
        const [tRes, eRes, uRes, iRes] = await Promise.all([
          authedFetch(tachesUrl),
          authedFetch("/api/v1/entreprises"),
          authedFetch("/api/v1/users"),
          authedFetch("/api/v1/immobilier/immeubles/picker")
        ]);
        if (cancelled) return;
        if (!tRes.ok) throw new Error(`HTTP ${tRes.status}`);
        if (eRes.ok) setEntreprises((await eRes.json()) as Entreprise[]);
        if (uRes.ok) {
          const all = (await uRes.json()) as Array<
            TaskUserMini & { volets?: string[] }
          >;
          setUsers(
            all.filter((u) => (u.volets || []).includes("entreprises"))
          );
        }
        if (iRes.ok) setImmeubles((await iRes.json()) as ImmeubleMini[]);
        setTaches((await tRes.json()) as Tache[]);
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

  async function patchTache(id: number, patch: Partial<Tache>) {
    const before = taches;
    setTaches((prev) =>
      prev.map((t) => (t.id === id ? { ...t, ...patch } : t))
    );
    try {
      const res = await authedFetch(
        `/api/v1/entreprises/taches/${id}`,
        {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(patch)
        }
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const updated = (await res.json()) as Tache;
      setTaches((prev) =>
        prev.map((t) => (t.id === id ? { ...t, ...updated } : t))
      );
    } catch (err) {
      setTaches(before);
      setError(`Échec mise à jour : ${(err as Error).message}`);
    }
  }

  async function deleteTache(id: number) {
    const before = taches;
    setTaches((prev) => prev.filter((t) => t.id !== id));
    try {
      const res = await authedFetch(
        `/api/v1/entreprises/taches/${id}`,
        { method: "DELETE" }
      );
      if (!res.ok && res.status !== 204) throw new Error();
    } catch {
      setTaches(before);
      setError("Suppression échouée.");
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

  const immeubleNameById = useMemo(
    () => new Map(immeubles.map((i) => [i.id, i.name] as const)),
    [immeubles]
  );

  // Application du filtre Entreprise (les autres filtres vivent dans
  // <TaskBoard>).
  const filteredTaches = useMemo(() => {
    if (!filterEntreprise) return taches;
    return taches.filter(
      (t) => String(t.entreprise_id) === filterEntreprise
    );
  }, [taches, filterEntreprise]);

  // Tache → TaskBoardItem. Footer = badge de l'entreprise
  // propriétaire (utile en vue cross-entreprise pour distinguer
  // d'un coup d'œil à qui appartient chaque tâche).
  const boardItems: TaskBoardItem[] = useMemo(
    () =>
      filteredTaches.map((t) => {
        const ent = entById.get(t.entreprise_id);
        return {
          id: t.id,
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
          footer: ent ? (
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
          ) : null
        };
      }),
    [filteredTaches, entById, immeubleNameById]
  );

  const subtitle = `${filteredTaches.length} TÂCHE${
    filteredTaches.length > 1 ? "S" : ""
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
        {/* Bandeau filtres niveau page : portée + entreprise. */}
        <div className="mb-4 flex flex-wrap items-center gap-2">
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
          <select
            value={filterEntreprise}
            onChange={(e) => setFilterEntreprise(e.target.value)}
            className="rounded-md border border-brand-800 bg-brand-900 px-2 py-1.5 text-xs text-white focus:border-accent-500 focus:outline-none"
          >
            <option value="">Toutes les entreprises</option>
            {entreprises.map((e) => (
              <option key={e.id} value={String(e.id)}>
                {e.name}
              </option>
            ))}
          </select>
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
        ) : filteredTaches.length === 0 ? (
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
            onPatch={(taskId, patch) => {
              const out: Partial<Tache> = {};
              if (patch.title !== undefined) out.title = patch.title;
              if (patch.notes !== undefined) out.description = patch.notes;
              if (patch.status !== undefined) out.status = patch.status;
              if (patch.priority !== undefined) out.priority = patch.priority;
              if (patch.due_date !== undefined) out.due_date = patch.due_date;
              if (patch.assignee_user_ids !== undefined) {
                out.assignee_user_ids = patch.assignee_user_ids;
                out.assignee_user_id =
                  patch.assignee_user_ids[0] ?? null;
              }
              if (patch.immeuble_ids !== undefined) {
                out.immeuble_ids = patch.immeuble_ids;
              }
              if (patch.departement !== undefined)
                out.departement = patch.departement;
              if (patch.recurrence !== undefined)
                out.recurrence = patch.recurrence;
              if (patch.impact !== undefined) out.impact = patch.impact;
              if (patch.confidence !== undefined)
                out.confidence = patch.confidence;
              if (patch.effort !== undefined) out.effort = patch.effort;
              void patchTache(taskId, out);
            }}
            onDelete={(taskId) => void deleteTache(taskId)}
            // Pas de onCreate effectif — la création se fait dans la
            // fiche d'une entreprise (showNewTaskButton=false rend
            // le bouton invisible). On fournit quand même un stub
            // pour respecter le contrat de TaskBoard.
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
