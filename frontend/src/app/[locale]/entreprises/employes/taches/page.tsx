"use client";

/**
 * Onglet « Tâches » — le tableau <TaskBoard> du QG, filtré sur l'employé
 * sélectionné (?employe=<id>) ou sur toute l'équipe. Les tâches sont les
 * EntrepriseTache partagées avec le tableau « Tâches » du pôle : créer ici
 * = assigner à l'employé, qui la retrouve dans sa zone employés.
 */

import { useEffect, useMemo, useState } from "react";

import { authedFetch } from "@/lib/auth";
import { useCurrentUser } from "@/hooks/use-current-user";
import {
  TaskBoard,
  type ExtraColumnConfig,
  type TaskBoardItem,
  type TaskBoardPatch
} from "@/components/task-board";
import type { TaskUserMini } from "@/components/task-pills";
import {
  Chargement,
  ERROR_BOX,
  INPUT,
  LABEL,
  lireErreur,
  useSectionEmployes
} from "../_shared";

type TacheEnt = {
  id: number;
  entreprise_id: number;
  created_at?: string;
  completed_at?: string | null;
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
  entreprise_ids?: number[];
  position: number;
};

type Entreprise = {
  id: number;
  name: string;
  color_accent: string;
  is_active?: boolean;
};

function assignes(t: TacheEnt): number[] {
  const ids = new Set(t.assignee_user_ids || []);
  if (t.assignee_user_id != null) ids.add(t.assignee_user_id);
  return [...ids];
}

export default function TachesEmployesPage() {
  const { user: me } = useCurrentUser();
  const { equipe, loading: equipeLoading, selected, selectedId, reload } =
    useSectionEmployes();

  const [taches, setTaches] = useState<TacheEnt[]>([]);
  const [entreprises, setEntreprises] = useState<Entreprise[]>([]);
  const [users, setUsers] = useState<TaskUserMini[]>([]);
  const [entrepriseNouvelle, setEntrepriseNouvelle] = useState<number | null>(
    null
  );
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Catalogues (une fois) : entreprises actives + utilisateurs.
  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const [eRes, uRes] = await Promise.all([
          authedFetch("/api/v1/entreprises"),
          authedFetch("/api/v1/users")
        ]);
        if (cancelled) return;
        if (eRes.ok) {
          const actives = ((await eRes.json()) as Entreprise[]).filter(
            (e) => e.is_active !== false
          );
          setEntreprises(actives);
          setEntrepriseNouvelle((cur) => cur ?? actives[0]?.id ?? null);
        }
        if (uRes.ok) setUsers((await uRes.json()) as TaskUserMini[]);
      } catch {
        /* les tâches restent utilisables sans catalogue */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  // Tâches : chargées une fois, filtrées côté client — le filtre serveur
  // `assignee_user_id` ne voit que l'assigné principal, pas les
  // co-assignés.
  useEffect(() => {
    let cancelled = false;
    void (async () => {
      setLoading(true);
      setError(null);
      try {
        const r = await authedFetch("/api/v1/entreprises/taches");
        if (!r.ok) throw new Error(await lireErreur(r));
        if (!cancelled) setTaches((await r.json()) as TacheEnt[]);
      } catch (e) {
        if (!cancelled) setError((e as Error).message);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const idsEquipe = useMemo(() => new Set(equipe.map((e) => e.id)), [equipe]);
  const entById = useMemo(
    () => new Map(entreprises.map((e) => [e.id, e] as const)),
    [entreprises]
  );

  const visibles = useMemo(() => {
    if (selectedId != null)
      return taches.filter((t) => assignes(t).includes(selectedId));
    return taches.filter((t) => assignes(t).some((id) => idsEquipe.has(id)));
  }, [taches, selectedId, idsEquipe]);

  const badgeEntreprise = (entrepriseId: number) => {
    const ent = entById.get(entrepriseId);
    if (!ent) return null;
    return (
      <span className="badge badge-neutral" title={`Entreprise : ${ent.name}`}>
        <span
          className="h-1.5 w-1.5 rounded-full"
          style={{ backgroundColor: ent.color_accent }}
        />
        <span className="max-w-[140px] truncate">{ent.name}</span>
      </span>
    );
  };

  const items: TaskBoardItem[] = useMemo(
    () =>
      visibles.map((t) => ({
        id: t.id,
        created_at: t.created_at,
        completed_at: t.completed_at,
        dbPosition: t.position,
        title: t.title,
        status: t.status,
        priority: t.priority || "non_assigne",
        due_date: t.due_date,
        assignee_user_ids: assignes(t),
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
        entreprise_ids: t.entreprise_ids || [t.entreprise_id],
        footer: badgeEntreprise(t.entreprise_id)
      })),
    // badgeEntreprise ne dépend que d'entById.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [visibles, entById]
  );

  const entrepriseParTache = useMemo(
    () => new Map(taches.map((t) => [t.id, t.entreprise_id] as const)),
    [taches]
  );

  const extraColumn: ExtraColumnConfig = useMemo(
    () => ({
      label: "Entreprise",
      width: "200px",
      render: (item) => {
        const eid = entrepriseParTache.get(item.id);
        return eid != null ? badgeEntreprise(eid) : null;
      },
      filterValues: entreprises.map((e) => ({
        value: String(e.id),
        label: e.name
      })),
      getGroupId: (item) => {
        const eid = entrepriseParTache.get(item.id);
        return eid != null ? String(eid) : null;
      }
    }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [entreprises, entrepriseParTache, entById]
  );

  async function patchTache(taskId: number, patch: TaskBoardPatch) {
    const body: Record<string, unknown> = {};
    if (patch.title !== undefined) body.title = patch.title;
    if (patch.notes !== undefined) body.description = patch.notes;
    if (patch.status !== undefined) body.status = patch.status;
    if (patch.priority !== undefined) body.priority = patch.priority;
    if (patch.due_date !== undefined) body.due_date = patch.due_date;
    if (patch.assignee_user_ids !== undefined) {
      body.assignee_user_ids = patch.assignee_user_ids;
      body.assignee_user_id = patch.assignee_user_ids[0] ?? null;
    }
    if (patch.immeuble_ids !== undefined) body.immeuble_ids = patch.immeuble_ids;
    if (patch.entreprise_ids !== undefined)
      body.entreprise_ids = patch.entreprise_ids;
    if (patch.departement !== undefined) body.departement = patch.departement;
    if (patch.recurrence !== undefined) body.recurrence = patch.recurrence;
    if (patch.impact !== undefined) body.impact = patch.impact;
    if (patch.confidence !== undefined) body.confidence = patch.confidence;
    if (patch.effort !== undefined) body.effort = patch.effort;
    if (patch.position !== undefined) body.position = patch.position;
    if (Object.keys(body).length === 0) return;

    const before = taches;
    setTaches((prev) =>
      prev.map((t) => (t.id === taskId ? { ...t, ...body } : t))
    );
    try {
      const r = await authedFetch(`/api/v1/entreprises/taches/${taskId}`, {
        method: "PATCH",
        body: JSON.stringify(body)
      });
      if (!r.ok) throw new Error(await lireErreur(r));
      const updated = (await r.json()) as TacheEnt;
      setTaches((prev) => prev.map((t) => (t.id === taskId ? updated : t)));
      if (patch.status !== undefined || patch.assignee_user_ids !== undefined)
        void reload();
    } catch (e) {
      setTaches(before);
      setError(`Échec de la mise à jour : ${(e as Error).message}`);
    }
  }

  async function deleteTache(taskId: number) {
    const before = taches;
    setTaches((prev) => prev.filter((t) => t.id !== taskId));
    try {
      const r = await authedFetch(`/api/v1/entreprises/taches/${taskId}`, {
        method: "DELETE"
      });
      if (!r.ok && r.status !== 204) throw new Error(await lireErreur(r));
      void reload();
    } catch (e) {
      setTaches(before);
      setError(`Suppression échouée : ${(e as Error).message}`);
    }
  }

  async function createTache(status: string, name: string): Promise<number | null> {
    if (!selected) {
      setError(
        "Choisis d'abord un employé dans le sélecteur pour lui assigner la nouvelle tâche."
      );
      return null;
    }
    if (entrepriseNouvelle == null) {
      setError("Choisis l'entreprise des nouvelles tâches avant de créer.");
      return null;
    }
    setError(null);
    try {
      const r = await authedFetch("/api/v1/entreprises/taches", {
        method: "POST",
        body: JSON.stringify({
          title: name,
          entreprise_id: entrepriseNouvelle,
          status,
          assignee_user_ids: [selected.id]
        })
      });
      if (!r.ok) throw new Error(await lireErreur(r));
      const created = (await r.json()) as TacheEnt;
      setTaches((prev) => [...prev, created]);
      void reload();
      return created.id;
    } catch (e) {
      setError(`Création échouée : ${(e as Error).message}`);
      return null;
    }
  }

  const titre = selected
    ? `Tâches de ${selected.display_name}`
    : "Tâches de l'équipe";

  return (
    <div className="px-5 py-6 lg:px-8">
      <div className="mb-4 flex flex-wrap items-end gap-3">
        <div className="min-w-[220px]">
          <label htmlFor="entreprise-nouvelles-taches" className={LABEL}>
            Entreprise des nouvelles tâches
          </label>
          <select
            id="entreprise-nouvelles-taches"
            value={entrepriseNouvelle ?? ""}
            onChange={(e) =>
              setEntrepriseNouvelle(e.target.value ? Number(e.target.value) : null)
            }
            className={INPUT}
          >
            {entreprises.length === 0 ? (
              <option value="">Aucune entreprise active</option>
            ) : null}
            {entreprises.map((e) => (
              <option key={e.id} value={e.id}>
                {e.name}
              </option>
            ))}
          </select>
        </div>
        <p className="pb-2 text-xs text-[var(--qg-text-muted)]">
          {selected
            ? `Une tâche créée ici est assignée à ${selected.display_name}, qui la retrouve dans sa zone employés.`
            : "Sélectionne un employé pour pouvoir lui créer des tâches. Sans sélection, tu vois les tâches de toute l'équipe."}
        </p>
      </div>

      {error ? <p className={`mb-3 ${ERROR_BOX}`}>{error}</p> : null}

      {loading || equipeLoading ? (
        <Chargement />
      ) : (
        <TaskBoard
          tasks={items}
          users={users}
          immeubles={[]}
          onPatch={(id, patch) => void patchTache(id, patch)}
          onDelete={(id) => void deleteTache(id)}
          onCreate={createTache}
          entreprises={entreprises.map((e) => ({ id: e.id, name: e.name }))}
          extraColumn={extraColumn}
          title={titre}
          newTaskLabel="+ Nouvelle tâche"
          defaultView="kanban"
          currentUserId={me?.id ?? null}
        />
      )}
    </div>
  );
}
