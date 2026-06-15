"use client";

/**
 * Distribution des tâches — matrice RACI.
 *
 * Lignes = activités regroupées par pôle. Colonnes = personnes
 * (partenaires + employés). Chaque cellule cycle R → A → C → I → vide
 * au clic, et s'enregistre automatiquement.
 */

import { useCallback, useEffect, useState } from "react";
import { Plus, Pencil, Trash2, X, Loader2, Grid3x3 } from "lucide-react";

import { authedFetch } from "@/lib/auth";

type Person = {
  id: number;
  name: string;
  subtitle?: string | null;
  position: number;
};
type Activity = {
  id: number;
  pole: string;
  label: string;
  position: number;
};
type Cell = { activity_id: number; person_id: number; value: string };
type Board = { people: Person[]; activities: Activity[]; cells: Cell[] };

const INPUT =
  "w-full rounded-lg border border-[var(--qg-border)] bg-[var(--qg-card-bg)] " +
  "px-3 py-2 text-sm outline-none focus:border-[var(--qg-accent)]";

const CYCLE = ["", "R", "A", "C", "I"];

const RACI_META: Record<
  string,
  { bg: string; label: string; full: string }
> = {
  R: { bg: "#2563eb", label: "R", full: "Réalise (Responsible)" },
  A: { bg: "#e11d48", label: "A", full: "Approuve / Autorité (Accountable)" },
  C: { bg: "#d97706", label: "C", full: "Consulté (Consulted)" },
  I: { bg: "#64748b", label: "I", full: "Informé (Informed)" }
};

const POLE_SUGGESTIONS = [
  "Gestion locative",
  "Construction",
  "Acquisition / Prospection",
  "Développement logiciel",
  "Comptabilité",
  "Administration",
  "Gestion d'entreprise"
];

export default function DistributionTachesPage() {
  const [board, setBoard] = useState<Board | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [personModal, setPersonModal] = useState<Person | "new" | null>(null);
  const [activityModal, setActivityModal] = useState<
    Activity | "new" | null
  >(null);

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
    // Optimiste
    const others = board.cells.filter(
      (c) => !(c.activity_id === activityId && c.person_id === personId)
    );
    setBoard({
      ...board,
      cells: next
        ? [...others, { activity_id: activityId, person_id: personId, value: next }]
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
      void load(); // resync en cas d'échec
    }
  }

  async function deletePerson(p: Person) {
    if (!confirm(`Supprimer la colonne « ${p.name} » ?`)) return;
    await authedFetch(`/api/v1/raci/people/${p.id}`, { method: "DELETE" });
    void load();
  }
  async function deleteActivity(a: Activity) {
    if (!confirm(`Supprimer la tâche « ${a.label} » ?`)) return;
    await authedFetch(`/api/v1/raci/activities/${a.id}`, { method: "DELETE" });
    void load();
  }

  // Regroupe les activités par pôle (déjà triées côté serveur).
  const groups: { pole: string; items: Activity[] }[] = [];
  board?.activities.forEach((a) => {
    const last = groups[groups.length - 1];
    if (last && last.pole === a.pole) last.items.push(a);
    else groups.push({ pole: a.pole, items: [a] });
  });

  const people = board?.people || [];

  return (
    <div className="space-y-4">
      {/* En-tête */}
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
            onClick={() => setActivityModal("new")}
            className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--qg-border)] bg-[var(--qg-card-bg)] px-3 py-2 text-sm hover:border-[var(--qg-accent)]"
          >
            <Plus className="h-4 w-4" /> Tâche
          </button>
          <button
            type="button"
            onClick={() => setPersonModal("new")}
            className="inline-flex items-center gap-1.5 rounded-lg bg-[var(--qg-accent)] px-3 py-2 text-sm font-semibold text-white hover:opacity-90"
          >
            <Plus className="h-4 w-4" /> Personne
          </button>
        </div>
      </div>

      {/* Légende */}
      <div className="flex flex-wrap items-center gap-3 rounded-xl border border-[var(--qg-border)] bg-[var(--qg-card-bg)] px-4 py-2.5 text-xs">
        {Object.entries(RACI_META).map(([k, m]) => (
          <span key={k} className="inline-flex items-center gap-1.5">
            <span
              className="grid h-5 w-5 place-items-center rounded text-[11px] font-bold text-white"
              style={{ background: m.bg }}
            >
              {m.label}
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
      ) : people.length === 0 && groups.length === 0 ? (
        <div className="rounded-xl border border-dashed border-[var(--qg-border)] px-6 py-12 text-center text-sm text-[var(--qg-text-muted)]">
          Commence par ajouter une <strong>personne</strong> (colonne) et une{" "}
          <strong>tâche</strong> (ligne).
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
                      <div className="text-[10px] font-normal text-[var(--qg-text-muted)]">
                        {p.subtitle}
                      </div>
                    ) : null}
                    <div className="mt-1 flex justify-center gap-1 opacity-0 transition group-hover:opacity-100">
                      <button
                        type="button"
                        onClick={() => setPersonModal(p)}
                        className="rounded p-0.5 text-[var(--qg-text-faint)] hover:text-[var(--qg-accent)]"
                        title="Renommer"
                      >
                        <Pencil className="h-3 w-3" />
                      </button>
                      <button
                        type="button"
                        onClick={() => void deletePerson(p)}
                        className="rounded p-0.5 text-[var(--qg-text-faint)] hover:text-rose-400"
                        title="Supprimer"
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
                <ActivityGroup
                  key={g.pole || "_"}
                  pole={g.pole}
                  items={g.items}
                  peopleCount={people.length}
                >
                  {g.items.map((a) => (
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
                              {meta ? meta.label : ""}
                            </button>
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                </ActivityGroup>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {personModal ? (
        <PersonModal
          person={personModal === "new" ? null : personModal}
          onClose={() => setPersonModal(null)}
          onSaved={() => {
            setPersonModal(null);
            void load();
          }}
        />
      ) : null}
      {activityModal ? (
        <ActivityModal
          activity={activityModal === "new" ? null : activityModal}
          onClose={() => setActivityModal(null)}
          onSaved={() => {
            setActivityModal(null);
            void load();
          }}
        />
      ) : null}
    </div>
  );
}

function ActivityGroup({
  pole,
  peopleCount,
  children
}: {
  pole: string;
  items: Activity[];
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

function PersonModal({
  person,
  onClose,
  onSaved
}: {
  person: Person | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [name, setName] = useState(person?.name || "");
  const [subtitle, setSubtitle] = useState(person?.subtitle || "");
  const [busy, setBusy] = useState(false);

  async function save() {
    if (!name.trim()) return;
    setBusy(true);
    try {
      const url = person
        ? `/api/v1/raci/people/${person.id}`
        : "/api/v1/raci/people";
      await authedFetch(url, {
        method: person ? "PUT" : "POST",
        body: JSON.stringify({ name: name.trim(), subtitle: subtitle.trim() || null })
      });
      onSaved();
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal title={person ? "Modifier la personne" : "Nouvelle personne"} onClose={onClose}>
      <label className="mb-1 block text-xs text-[var(--qg-text-muted)]">Nom</label>
      <input
        className={INPUT}
        value={name}
        onChange={(e) => setName(e.target.value)}
        placeholder="Ex. Olivier, Steven…"
        autoFocus
      />
      <label className="mb-1 mt-3 block text-xs text-[var(--qg-text-muted)]">
        Sous-titre (pôle / rôle, optionnel)
      </label>
      <input
        className={INPUT}
        value={subtitle}
        onChange={(e) => setSubtitle(e.target.value)}
        placeholder="Ex. Construction, Comptabilité…"
      />
      <ModalActions busy={busy} onSave={() => void save()} onClose={onClose} />
    </Modal>
  );
}

function ActivityModal({
  activity,
  onClose,
  onSaved
}: {
  activity: Activity | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [pole, setPole] = useState(activity?.pole || "");
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
        body: JSON.stringify({ pole: pole.trim(), label: label.trim() })
      });
      onSaved();
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal title={activity ? "Modifier la tâche" : "Nouvelle tâche"} onClose={onClose}>
      <label className="mb-1 block text-xs text-[var(--qg-text-muted)]">Pôle</label>
      <input
        className={INPUT}
        value={pole}
        onChange={(e) => setPole(e.target.value)}
        placeholder="Ex. Gestion locative"
        list="raci-poles"
        autoFocus
      />
      <datalist id="raci-poles">
        {POLE_SUGGESTIONS.map((p) => (
          <option key={p} value={p} />
        ))}
      </datalist>
      <label className="mb-1 mt-3 block text-xs text-[var(--qg-text-muted)]">
        Tâche / responsabilité
      </label>
      <input
        className={INPUT}
        value={label}
        onChange={(e) => setLabel(e.target.value)}
        placeholder="Ex. Encaisser les loyers"
      />
      <ModalActions busy={busy} onSave={() => void save()} onClose={onClose} />
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
