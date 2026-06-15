"use client";

/**
 * Distribution des tâches — matrice RACI.
 *
 * Lignes = tâches regroupées par PÔLE (gérable). Colonnes = comptes
 * Kratos. Chaque cellule cycle R → A → C → I → vide au clic et
 * s'enregistre automatiquement.
 */

import { useCallback, useEffect, useState } from "react";
import { Plus, Pencil, Trash2, X, Loader2, Grid3x3, Layers } from "lucide-react";

import { authedFetch } from "@/lib/auth";

type Pole = { id: number; label: string; position: number };
type Person = {
  id: number;
  user_id?: number | null;
  name: string;
  subtitle?: string | null;
  position: number;
};
type Activity = { id: number; pole: string; label: string; position: number };
type Cell = { activity_id: number; person_id: number; value: string };
type Board = {
  poles: Pole[];
  people: Person[];
  activities: Activity[];
  cells: Cell[];
};
type AvailableUser = {
  user_id: number;
  name: string;
  subtitle?: string | null;
};

const INPUT =
  "w-full rounded-lg border border-[var(--qg-border)] bg-[var(--qg-card-bg)] " +
  "px-3 py-2 text-sm outline-none focus:border-[var(--qg-accent)]";

const CYCLE = ["", "R", "A", "C", "I"];

// Libellés 100 % français (aucun terme anglais).
const RACI_META: Record<string, { bg: string; full: string }> = {
  R: { bg: "#2563eb", full: "Réalise" },
  A: { bg: "#e11d48", full: "Autorité" },
  C: { bg: "#d97706", full: "Consulté" },
  I: { bg: "#64748b", full: "Informé" }
};

export default function DistributionTachesPage() {
  const [board, setBoard] = useState<Board | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [personOpen, setPersonOpen] = useState(false);
  const [activityModal, setActivityModal] = useState<
    Activity | "new" | null
  >(null);
  const [poleManagerOpen, setPoleManagerOpen] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await authedFetch("/api/v1/raci");
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      setBoard((await r.json()) as Board);
      setError(null);
    } catch (e) {
      setError(`Chargement échoué : ${(e as Error).message}`);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const cellKey = (a: number, p: number) => `${a}:${p}`;
  const cellMap = new Map<string, string>();
  board?.cells.forEach((c) =>
    cellMap.set(cellKey(c.activity_id, c.person_id), c.value)
  );

  async function cycleCell(activityId: number, personId: number) {
    if (!board) return;
    const cur = cellMap.get(cellKey(activityId, personId)) || "";
    const next = CYCLE[(CYCLE.indexOf(cur) + 1) % CYCLE.length];
    const others = board.cells.filter(
      (c) => !(c.activity_id === activityId && c.person_id === personId)
    );
    setBoard({
      ...board,
      cells: next
        ? [
            ...others,
            { activity_id: activityId, person_id: personId, value: next }
          ]
        : others
    });
    try {
      await authedFetch("/api/v1/raci/cell", {
        method: "PUT",
        body: JSON.stringify({
          activity_id: activityId,
          person_id: personId,
          value: next || null
        })
      });
    } catch {
      void load();
    }
  }

  async function deletePerson(p: Person) {
    if (!confirm(`Retirer la colonne « ${p.name} » ?`)) return;
    await authedFetch(`/api/v1/raci/people/${p.id}`, { method: "DELETE" });
    void load();
  }
  async function deleteActivity(a: Activity) {
    if (!confirm(`Supprimer la tâche « ${a.label} » ?`)) return;
    await authedFetch(`/api/v1/raci/activities/${a.id}`, { method: "DELETE" });
    void load();
  }

  // Groupes ordonnés selon la liste de pôles ; activités orphelines à la fin.
  const poles = board?.poles || [];
  const people = board?.people || [];
  const groups: { pole: string; items: Activity[] }[] = [];
  const byPole = new Map<string, Activity[]>();
  board?.activities.forEach((a) => {
    const arr = byPole.get(a.pole) || [];
    arr.push(a);
    byPole.set(a.pole, arr);
  });
  poles.forEach((pl) => {
    groups.push({ pole: pl.label, items: byPole.get(pl.label) || [] });
    byPole.delete(pl.label);
  });
  byPole.forEach((items, pole) => groups.push({ pole, items }));

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="flex items-center gap-2 text-xl font-bold">
            <Grid3x3 className="h-5 w-5 text-[var(--qg-accent)]" />
            Distribution des tâches
          </h1>
          <p className="text-sm text-[var(--qg-text-muted)]">
            Matrice RACI — qui fait quoi, par pôle. Clique une cellule pour
            cycler R → A → C → I.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={() => setPoleManagerOpen(true)}
            className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--qg-border)] bg-[var(--qg-card-bg)] px-3 py-2 text-sm hover:border-[var(--qg-accent)]"
          >
            <Layers className="h-4 w-4" /> Pôles
          </button>
          <button
            type="button"
            onClick={() => setActivityModal("new")}
            className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--qg-border)] bg-[var(--qg-card-bg)] px-3 py-2 text-sm hover:border-[var(--qg-accent)]"
          >
            <Plus className="h-4 w-4" /> Tâche
          </button>
          <button
            type="button"
            onClick={() => setPersonOpen(true)}
            className="inline-flex items-center gap-1.5 rounded-lg bg-[var(--qg-accent)] px-3 py-2 text-sm font-semibold text-white hover:opacity-90"
          >
            <Plus className="h-4 w-4" /> Personne
          </button>
        </div>
      </div>

      {/* Légende — français uniquement */}
      <div className="flex flex-wrap items-center gap-3 rounded-xl border border-[var(--qg-border)] bg-[var(--qg-card-bg)] px-4 py-2.5 text-xs">
        {Object.entries(RACI_META).map(([k, m]) => (
          <span key={k} className="inline-flex items-center gap-1.5">
            <span
              className="grid h-5 w-5 place-items-center rounded text-[11px] font-bold text-white"
              style={{ background: m.bg }}
            >
              {k}
            </span>
            <span className="text-[var(--qg-text-muted)]">{m.full}</span>
          </span>
        ))}
      </div>

      {loading ? (
        <div className="flex items-center gap-2 py-12 text-sm text-[var(--qg-text-muted)]">
          <Loader2 className="h-4 w-4 animate-spin" /> Chargement…
        </div>
      ) : error ? (
        <p className="py-8 text-center text-sm text-rose-400">{error}</p>
      ) : people.length === 0 ? (
        <div className="rounded-xl border border-dashed border-[var(--qg-border)] px-6 py-12 text-center text-sm text-[var(--qg-text-muted)]">
          Ajoute une <strong>personne</strong> (un compte Kratos) et une{" "}
          <strong>tâche</strong> pour commencer.
        </div>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-[var(--qg-border)]">
          <table className="w-full border-collapse text-sm">
            <thead>
              <tr className="bg-[var(--qg-card-bg)]">
                <th className="sticky left-0 z-20 min-w-[16rem] border-b border-r border-[var(--qg-border)] bg-[var(--qg-card-bg)] p-2 text-left text-xs font-semibold uppercase tracking-wider text-[var(--qg-text-muted)]">
                  Pôle / Tâche
                </th>
                {people.map((p) => (
                  <th
                    key={p.id}
                    className="group min-w-[7rem] border-b border-l border-[var(--qg-border)] p-2 text-center align-top"
                  >
                    <div className="font-semibold">{p.name}</div>
                    {p.subtitle ? (
                      <div className="text-[10px] font-normal capitalize text-[var(--qg-text-muted)]">
                        {p.subtitle}
                      </div>
                    ) : null}
                    <div className="mt-1 flex justify-center opacity-0 transition group-hover:opacity-100">
                      <button
                        type="button"
                        onClick={() => void deletePerson(p)}
                        className="rounded p-0.5 text-[var(--qg-text-faint)] hover:text-rose-400"
                        title="Retirer"
                      >
                        <Trash2 className="h-3 w-3" />
                      </button>
                    </div>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {groups.map((g) => (
                <RaciGroup
                  key={g.pole || "_"}
                  pole={g.pole}
                  peopleCount={people.length}
                >
                  {g.items.length === 0 ? (
                    <tr>
                      <td
                        colSpan={people.length + 1}
                        className="border-b border-[var(--qg-border)] px-2 py-1.5 text-[11px] italic text-[var(--qg-text-faint)]"
                      >
                        Aucune tâche dans ce pôle.
                      </td>
                    </tr>
                  ) : (
                    g.items.map((a) => (
                      <tr key={a.id} className="group">
                        <td className="sticky left-0 z-10 border-b border-r border-[var(--qg-border)] bg-[var(--qg-bg)] p-2 align-top">
                          <div className="flex items-start justify-between gap-2">
                            <span className="leading-snug">{a.label}</span>
                            <span className="flex shrink-0 gap-1 opacity-0 transition group-hover:opacity-100">
                              <button
                                type="button"
                                onClick={() => setActivityModal(a)}
                                className="rounded p-0.5 text-[var(--qg-text-faint)] hover:text-[var(--qg-accent)]"
                                title="Modifier"
                              >
                                <Pencil className="h-3 w-3" />
                              </button>
                              <button
                                type="button"
                                onClick={() => void deleteActivity(a)}
                                className="rounded p-0.5 text-[var(--qg-text-faint)] hover:text-rose-400"
                                title="Supprimer"
                              >
                                <Trash2 className="h-3 w-3" />
                              </button>
                            </span>
                          </div>
                        </td>
                        {people.map((p) => {
                          const v = cellMap.get(cellKey(a.id, p.id)) || "";
                          const meta = v ? RACI_META[v] : null;
                          return (
                            <td
                              key={p.id}
                              className="border-b border-l border-[var(--qg-border)] p-1 text-center"
                            >
                              <button
                                type="button"
                                onClick={() => void cycleCell(a.id, p.id)}
                                className="mx-auto grid h-8 w-8 place-items-center rounded text-xs font-bold transition hover:ring-2 hover:ring-[var(--qg-accent)]/40"
                                style={
                                  meta
                                    ? { background: meta.bg, color: "#fff" }
                                    : { background: "transparent" }
                                }
                                title={meta ? meta.full : "Vide — clique pour R"}
                              >
                                {v}
                              </button>
                            </td>
                          );
                        })}
                      </tr>
                    ))
                  )}
                </RaciGroup>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {personOpen ? (
        <PersonPicker
          onClose={() => setPersonOpen(false)}
          onSaved={() => {
            setPersonOpen(false);
            void load();
          }}
        />
      ) : null}
      {activityModal ? (
        <ActivityModal
          activity={activityModal === "new" ? null : activityModal}
          poles={poles}
          onClose={() => setActivityModal(null)}
          onSaved={() => {
            setActivityModal(null);
            void load();
          }}
        />
      ) : null}
      {poleManagerOpen ? (
        <PoleManager
          poles={poles}
          onClose={() => setPoleManagerOpen(false)}
          onChanged={() => void load()}
        />
      ) : null}
    </div>
  );
}

function RaciGroup({
  pole,
  peopleCount,
  children
}: {
  pole: string;
  peopleCount: number;
  children: React.ReactNode;
}) {
  return (
    <>
      <tr>
        <td
          colSpan={peopleCount + 1}
          className="sticky left-0 border-b border-[var(--qg-border)] bg-[var(--qg-card-bg)] px-2 py-1.5 text-[11px] font-bold uppercase tracking-wider text-[var(--qg-accent)]"
        >
          {pole || "Sans pôle"}
        </td>
      </tr>
      {children}
    </>
  );
}

function PersonPicker({
  onClose,
  onSaved
}: {
  onClose: () => void;
  onSaved: () => void;
}) {
  const [users, setUsers] = useState<AvailableUser[] | null>(null);
  const [busy, setBusy] = useState<number | null>(null);

  useEffect(() => {
    void (async () => {
      const r = await authedFetch("/api/v1/raci/available-users");
      setUsers(r.ok ? ((await r.json()) as AvailableUser[]) : []);
    })();
  }, []);

  async function add(u: AvailableUser) {
    setBusy(u.user_id);
    try {
      await authedFetch("/api/v1/raci/people", {
        method: "POST",
        body: JSON.stringify({ user_id: u.user_id })
      });
      onSaved();
    } finally {
      setBusy(null);
    }
  }

  return (
    <Modal title="Ajouter une personne" onClose={onClose}>
      <p className="mb-3 text-xs text-[var(--qg-text-muted)]">
        Seuls les détenteurs d'un compte Kratos peuvent être des colonnes.
      </p>
      {users === null ? (
        <div className="flex items-center gap-2 py-6 text-sm text-[var(--qg-text-muted)]">
          <Loader2 className="h-4 w-4 animate-spin" /> Chargement…
        </div>
      ) : users.length === 0 ? (
        <p className="py-6 text-center text-sm text-[var(--qg-text-muted)]">
          Tous les comptes sont déjà dans la matrice.
        </p>
      ) : (
        <div className="max-h-72 space-y-1.5 overflow-y-auto">
          {users.map((u) => (
            <button
              key={u.user_id}
              type="button"
              onClick={() => void add(u)}
              disabled={busy !== null}
              className="flex w-full items-center justify-between rounded-lg border border-[var(--qg-border)] px-3 py-2 text-left text-sm hover:border-[var(--qg-accent)] disabled:opacity-50"
            >
              <span>
                <span className="font-medium">{u.name}</span>
                {u.subtitle ? (
                  <span className="ml-2 text-xs capitalize text-[var(--qg-text-muted)]">
                    {u.subtitle}
                  </span>
                ) : null}
              </span>
              {busy === u.user_id ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Plus className="h-4 w-4 text-[var(--qg-accent)]" />
              )}
            </button>
          ))}
        </div>
      )}
    </Modal>
  );
}

function ActivityModal({
  activity,
  poles,
  onClose,
  onSaved
}: {
  activity: Activity | null;
  poles: Pole[];
  onClose: () => void;
  onSaved: () => void;
}) {
  const [pole, setPole] = useState(activity?.pole || poles[0]?.label || "");
  const [label, setLabel] = useState(activity?.label || "");
  const [busy, setBusy] = useState(false);

  async function save() {
    if (!label.trim()) return;
    setBusy(true);
    try {
      const url = activity
        ? `/api/v1/raci/activities/${activity.id}`
        : "/api/v1/raci/activities";
      await authedFetch(url, {
        method: activity ? "PUT" : "POST",
        body: JSON.stringify({ pole, label: label.trim() })
      });
      onSaved();
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      title={activity ? "Modifier la tâche" : "Nouvelle tâche"}
      onClose={onClose}
    >
      <label className="mb-1 block text-xs text-[var(--qg-text-muted)]">
        Pôle
      </label>
      <select
        className={INPUT}
        value={pole}
        onChange={(e) => setPole(e.target.value)}
      >
        {poles.map((p) => (
          <option key={p.id} value={p.label}>
            {p.label}
          </option>
        ))}
        {pole && !poles.some((p) => p.label === pole) ? (
          <option value={pole}>{pole}</option>
        ) : null}
      </select>
      <label className="mb-1 mt-3 block text-xs text-[var(--qg-text-muted)]">
        Tâche / responsabilité
      </label>
      <input
        className={INPUT}
        value={label}
        onChange={(e) => setLabel(e.target.value)}
        placeholder="Ex. Encaisser les loyers"
        autoFocus
      />
      <ModalActions busy={busy} onSave={() => void save()} onClose={onClose} />
    </Modal>
  );
}

function PoleManager({
  poles,
  onClose,
  onChanged
}: {
  poles: Pole[];
  onClose: () => void;
  onChanged: () => void;
}) {
  const [newLabel, setNewLabel] = useState("");
  const [busy, setBusy] = useState(false);

  async function addPole() {
    if (!newLabel.trim()) return;
    setBusy(true);
    try {
      await authedFetch("/api/v1/raci/poles", {
        method: "POST",
        body: JSON.stringify({ label: newLabel.trim() })
      });
      setNewLabel("");
      onChanged();
    } finally {
      setBusy(false);
    }
  }
  async function renamePole(p: Pole) {
    const v = prompt("Renommer le pôle :", p.label);
    if (!v || !v.trim() || v.trim() === p.label) return;
    await authedFetch(`/api/v1/raci/poles/${p.id}`, {
      method: "PUT",
      body: JSON.stringify({ label: v.trim() })
    });
    onChanged();
  }
  async function deletePole(p: Pole) {
    if (!confirm(`Supprimer le pôle « ${p.label} » ?`)) return;
    await authedFetch(`/api/v1/raci/poles/${p.id}`, { method: "DELETE" });
    onChanged();
  }

  return (
    <Modal title="Gérer les pôles" onClose={onClose}>
      <div className="mb-3 space-y-1.5">
        {poles.map((p) => (
          <div
            key={p.id}
            className="flex items-center justify-between rounded-lg border border-[var(--qg-border)] px-3 py-2 text-sm"
          >
            <span>{p.label}</span>
            <span className="flex gap-1">
              <button
                type="button"
                onClick={() => void renamePole(p)}
                className="rounded p-1 text-[var(--qg-text-faint)] hover:text-[var(--qg-accent)]"
                title="Renommer"
              >
                <Pencil className="h-3.5 w-3.5" />
              </button>
              <button
                type="button"
                onClick={() => void deletePole(p)}
                className="rounded p-1 text-[var(--qg-text-faint)] hover:text-rose-400"
                title="Supprimer"
              >
                <Trash2 className="h-3.5 w-3.5" />
              </button>
            </span>
          </div>
        ))}
      </div>
      <div className="flex gap-2">
        <input
          className={INPUT}
          value={newLabel}
          onChange={(e) => setNewLabel(e.target.value)}
          placeholder="Nouveau pôle…"
          onKeyDown={(e) => {
            if (e.key === "Enter") void addPole();
          }}
        />
        <button
          type="button"
          onClick={() => void addPole()}
          disabled={busy}
          className="inline-flex shrink-0 items-center gap-1 rounded-lg bg-[var(--qg-accent)] px-3 py-2 text-sm font-semibold text-white hover:opacity-90 disabled:opacity-50"
        >
          <Plus className="h-4 w-4" /> Ajouter
        </button>
      </div>
    </Modal>
  );
}

function Modal({
  title,
  onClose,
  children
}: {
  title: string;
  onClose: () => void;
  children: React.ReactNode;
}) {
  return (
    <div className="fixed inset-0 z-[1000] flex items-center justify-center bg-black/50 p-3">
      <div className="w-full max-w-md rounded-2xl border border-[var(--qg-border)] bg-[var(--qg-bg)] p-5">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-base font-semibold">{title}</h2>
          <button
            type="button"
            onClick={onClose}
            className="rounded p-1 text-[var(--qg-text-faint)] hover:bg-[var(--qg-card-bg)]"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}

function ModalActions({
  busy,
  onSave,
  onClose
}: {
  busy: boolean;
  onSave: () => void;
  onClose: () => void;
}) {
  return (
    <div className="mt-5 flex justify-end gap-2">
      <button
        type="button"
        onClick={onClose}
        className="rounded-lg border border-[var(--qg-border)] px-3 py-2 text-sm hover:border-[var(--qg-accent)]"
      >
        Annuler
      </button>
      <button
        type="button"
        onClick={onSave}
        disabled={busy}
        className="inline-flex items-center gap-1.5 rounded-lg bg-[var(--qg-accent)] px-4 py-2 text-sm font-semibold text-white hover:opacity-90 disabled:opacity-50"
      >
        {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
        Enregistrer
      </button>
    </div>
  );
}
