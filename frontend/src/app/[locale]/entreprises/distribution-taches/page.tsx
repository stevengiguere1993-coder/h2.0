"use client";

/**
 * Distribution des tâches — matrice RACI.
 *
 * Hiérarchie : Pôle → (sous-section) → Tâches. Colonnes = comptes Kratos.
 * Cellule : clic = cycle R → A → C → I → vide (auto-save). Les tâches se
 * réordonnent / se déplacent entre pôles et sous-sections par glisser-
 * déposer.
 */

import { useCallback, useEffect, useState } from "react";
import {
  Plus,
  Pencil,
  Trash2,
  X,
  Loader2,
  Grid3x3,
  Layers,
  GripVertical,
  Upload
} from "lucide-react";

import { authedFetch } from "@/lib/auth";

type Pole = { id: number; label: string; position: number };
type Subsection = { id: number; pole: string; label: string; position: number };
type Person = {
  id: number;
  user_id?: number | null;
  name: string;
  subtitle?: string | null;
  position: number;
};
type Activity = {
  id: number;
  pole: string;
  subsection: string;
  label: string;
  position: number;
};
type Cell = { activity_id: number; person_id: number; value: string };
type Board = {
  poles: Pole[];
  subsections: Subsection[];
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

const RACI_META: Record<string, { bg: string; full: string }> = {
  R: { bg: "#2563eb", full: "Réalise" },
  A: { bg: "#e11d48", full: "Autorise" },
  C: { bg: "#d97706", full: "Consulté" },
  I: { bg: "#64748b", full: "Informé" }
};

// Couleur distincte par pôle (cycle) pour séparer visuellement les groupes.
const POLE_PALETTE = [
  "#2563eb",
  "#16a34a",
  "#d97706",
  "#db2777",
  "#7c3aed",
  "#0891b2",
  "#dc2626",
  "#0d9488",
  "#9333ea",
  "#ca8a04"
];
const PERSON_COL = "w-36 min-w-[9rem] max-w-[9rem]";

export default function DistributionTachesPage() {
  const [board, setBoard] = useState<Board | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [personOpen, setPersonOpen] = useState(false);
  const [activityModal, setActivityModal] = useState<
    Activity | "new" | null
  >(null);
  const [poleManagerOpen, setPoleManagerOpen] = useState(false);
  const [importOpen, setImportOpen] = useState(false);
  const [filterPersonId, setFilterPersonId] = useState<number | "">("");
  const [filterRole, setFilterRole] = useState<
    "" | "R" | "A" | "C" | "I"
  >("");

  const [dragId, setDragId] = useState<number | null>(null);

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

  function persistOrder(acts: Activity[]) {
    void authedFetch("/api/v1/raci/activities/reorder", {
      method: "PUT",
      body: JSON.stringify({
        items: acts.map((a) => ({
          id: a.id,
          pole: a.pole,
          subsection: a.subsection || ""
        }))
      })
    }).catch(() => void load());
  }

  // Déplace la tâche `dragId` dans (pole, subsection), avant `beforeId`
  // (ou en fin de groupe si null). Réécrit l'ordre + persiste.
  function moveTo(
    pole: string,
    subsection: string,
    beforeId: number | null
  ) {
    if (!board || dragId == null || dragId === beforeId) return;
    const moving = board.activities.find((a) => a.id === dragId);
    if (!moving) return;
    const rest = board.activities.filter((a) => a.id !== dragId);
    const updated = { ...moving, pole, subsection };
    let idx: number;
    if (beforeId != null) {
      idx = rest.findIndex((a) => a.id === beforeId);
      if (idx < 0) idx = rest.length;
    } else {
      idx = rest.length;
      for (let i = rest.length - 1; i >= 0; i--) {
        if (
          rest[i].pole === pole &&
          (rest[i].subsection || "") === (subsection || "")
        ) {
          idx = i + 1;
          break;
        }
      }
    }
    rest.splice(idx, 0, updated);
    setBoard({ ...board, activities: rest });
    persistOrder(rest);
    setDragId(null);
  }

  const poles = board?.poles || [];
  const subsections = board?.subsections || [];
  const people = board?.people || [];

  function tasksOf(pole: string, sub: string): Activity[] {
    return (board?.activities || []).filter(
      (a) => a.pole === pole && (a.subsection || "") === (sub || "")
    );
  }

  // ── Filtre : par personne ET/OU par rôle (global) ──
  const filtering = filterPersonId !== "" || filterRole !== "";
  function taskPasses(aId: number): boolean {
    if (!filtering) return true;
    if (filterPersonId !== "") {
      const v = cellMap.get(cellKey(aId, filterPersonId as number)) || "";
      if (!v) return false;
      if (filterRole && v !== filterRole) return false;
      return true;
    }
    // Aucune personne choisie + rôle choisi : tâches où QUELQU'UN a ce rôle.
    return people.some(
      (pp) => (cellMap.get(cellKey(aId, pp.id)) || "") === filterRole
    );
  }

  function poleColor(label: string): string {
    const pl = poles.find((p) => p.label === label);
    const key = pl
      ? pl.id
      : Array.from(label).reduce((a, c) => a + c.charCodeAt(0), 0);
    return POLE_PALETTE[key % POLE_PALETTE.length];
  }

  // Construit l'ordre d'affichage : pôles → tâches directes → sous-sections.
  type Row =
    | { kind: "pole"; pole: string }
    | { kind: "sub"; pole: string; sub: string }
    | { kind: "task"; activity: Activity };
  const rows: Row[] = [];
  const seenPoles = new Set<string>();

  function emitPole(poleLabel: string) {
    const direct = tasksOf(poleLabel, "").filter((a) => taskPasses(a.id));
    const subGroups = subsections
      .filter((su) => su.pole === poleLabel)
      .map((su) => ({
        label: su.label,
        items: tasksOf(poleLabel, su.label).filter((a) => taskPasses(a.id))
      }));
    const visibleSubs = filtering
      ? subGroups.filter((g) => g.items.length > 0)
      : subGroups;
    if (filtering && direct.length === 0 && visibleSubs.length === 0) return;
    rows.push({ kind: "pole", pole: poleLabel });
    direct.forEach((a) => rows.push({ kind: "task", activity: a }));
    visibleSubs.forEach((g) => {
      rows.push({ kind: "sub", pole: poleLabel, sub: g.label });
      g.items.forEach((a) => rows.push({ kind: "task", activity: a }));
    });
  }

  poles.forEach((pl) => {
    seenPoles.add(pl.label);
    emitPole(pl.label);
  });
  // Pôles orphelins (tâches dont le pôle n'existe plus dans la liste).
  Array.from(
    new Set(
      (board?.activities || [])
        .map((a) => a.pole)
        .filter((pl) => pl && !seenPoles.has(pl))
    )
  ).forEach((pl) => emitPole(pl));

  const taskRowsCount = rows.filter((r) => r.kind === "task").length;
  const colCount = people.length + 1;

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="flex items-center gap-2 text-xl font-bold">
            <Grid3x3 className="h-5 w-5 text-[var(--qg-accent)]" />
            Distribution des tâches
          </h1>
          <p className="text-sm text-[var(--qg-text-muted)]">
            Matrice RACI — qui fait quoi, par pôle. Glisse une tâche pour la
            déplacer ; clique une cellule pour cycler R → A → C → I.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={() => setPoleManagerOpen(true)}
            className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--qg-border)] bg-[var(--qg-card-bg)] px-3 py-2 text-sm hover:border-[var(--qg-accent)]"
          >
            <Layers className="h-4 w-4" /> Pôles & sous-sections
          </button>
          <button
            type="button"
            onClick={() => setImportOpen(true)}
            className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--qg-border)] bg-[var(--qg-card-bg)] px-3 py-2 text-sm hover:border-[var(--qg-accent)]"
          >
            <Upload className="h-4 w-4" /> Importer
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

      {people.length > 0 ? (
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <span className="text-[var(--qg-text-muted)]">Filtrer :</span>
          <select
            value={filterPersonId}
            onChange={(e) =>
              setFilterPersonId(e.target.value ? Number(e.target.value) : "")
            }
            className="rounded-lg border border-[var(--qg-border)] bg-[var(--qg-card-bg)] px-2 py-1.5 outline-none focus:border-[var(--qg-accent)]"
          >
            <option value="">Toutes les personnes</option>
            {people.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
          <select
            value={filterRole}
            onChange={(e) =>
              setFilterRole(e.target.value as "" | "R" | "A" | "C" | "I")
            }
            className="rounded-lg border border-[var(--qg-border)] bg-[var(--qg-card-bg)] px-2 py-1.5 outline-none focus:border-[var(--qg-accent)]"
          >
            <option value="">
              {filterPersonId !== "" ? "Tous ses rôles" : "Tous les rôles"}
            </option>
            <option value="R">Réalise (R)</option>
            <option value="A">Autorité (A)</option>
            <option value="C">Consulté (C)</option>
            <option value="I">Informé (I)</option>
          </select>
          {filterPersonId !== "" || filterRole !== "" ? (
            <button
              type="button"
              onClick={() => {
                setFilterPersonId("");
                setFilterRole("");
              }}
              className="rounded-lg border border-[var(--qg-border)] px-2 py-1.5 text-[var(--qg-text-muted)] hover:border-[var(--qg-accent)]"
            >
              Réinitialiser
            </button>
          ) : null}
        </div>
      ) : null}

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
          <table className="w-full table-fixed border-collapse text-sm">
            <thead>
              <tr className="bg-[var(--qg-card-bg)]">
                <th className="sticky left-0 z-20 w-[22rem] min-w-[22rem] border-b-2 border-r border-[var(--qg-border)] bg-[var(--qg-card-bg)] p-2.5 text-left text-xs font-semibold uppercase tracking-wider text-[var(--qg-text-muted)]">
                  Pôle / Tâche
                </th>
                {people.map((p) => (
                  <th
                    key={p.id}
                    className={"group border-b-2 border-l border-[var(--qg-border)] bg-[var(--qg-card-bg)] p-2 text-center align-top " + PERSON_COL}
                  >
                    <div className="truncate font-semibold" title={p.name}>
                      {p.name}
                    </div>
                    {p.subtitle ? (
                      <div className="truncate text-[10px] font-normal capitalize text-[var(--qg-text-muted)]">
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
              {taskRowsCount === 0 && filtering ? (
                <tr>
                  <td
                    colSpan={colCount}
                    className="px-4 py-10 text-center text-sm text-[var(--qg-text-muted)]"
                  >
                    Aucune tâche pour ce filtre.
                  </td>
                </tr>
              ) : null}
              {rows.map((row, ri) => {
                if (row.kind === "pole") {
                  const col = poleColor(row.pole);
                  return (
                    <tr
                      key={`pole-${row.pole}-${ri}`}
                      onDragOver={(e) => {
                        if (dragId != null) e.preventDefault();
                      }}
                      onDrop={() => moveTo(row.pole, "", null)}
                    >
                      <td
                        colSpan={colCount}
                        className="sticky left-0 border-y border-[var(--qg-border)] px-3 py-2 text-xs font-bold uppercase tracking-wider"
                        style={{
                          color: col,
                          background: col + "1f",
                          borderLeft: "4px solid " + col
                        }}
                      >
                        <span className="inline-flex items-center gap-2">
                          <span
                            className="inline-block h-2 w-2 rounded-full"
                            style={{ background: col }}
                          />
                          {row.pole || "Sans pôle"}
                        </span>
                      </td>
                    </tr>
                  );
                }
                if (row.kind === "sub") {
                  const col = poleColor(row.pole);
                  return (
                    <tr
                      key={`sub-${row.pole}-${row.sub}-${ri}`}
                      onDragOver={(e) => {
                        if (dragId != null) e.preventDefault();
                      }}
                      onDrop={() => moveTo(row.pole, row.sub, null)}
                    >
                      <td
                        colSpan={colCount}
                        className="sticky left-0 border-b border-[var(--qg-border)] py-1.5 pl-7 pr-2 text-[11px] font-bold uppercase tracking-wide"
                        style={{
                          borderLeft: "4px solid " + col + "99",
                          background: col + "0d",
                          color: col
                        }}
                      >
                        <span className="opacity-50">↳</span> {row.sub}
                      </td>
                    </tr>
                  );
                }
                const a = row.activity;
                const col = poleColor(a.pole);
                return (
                  <tr
                    key={a.id}
                    className={"group transition hover:bg-[var(--qg-card-bg)] " + (dragId === a.id ? "opacity-40" : "")}
                    draggable
                    onDragStart={() => setDragId(a.id)}
                    onDragEnd={() => setDragId(null)}
                    onDragOver={(e) => {
                      if (dragId != null) e.preventDefault();
                    }}
                    onDrop={() => moveTo(a.pole, a.subsection || "", a.id)}
                  >
                    <td
                      className="sticky left-0 z-10 border-b border-r border-[var(--qg-border)] bg-[var(--qg-bg)] p-2 align-top group-hover:bg-[var(--qg-card-bg)]"
                      style={{ borderLeft: "4px solid " + col + "40" }}
                    >
                      <div className="flex items-start gap-1.5">
                        <GripVertical className="mt-0.5 h-3.5 w-3.5 shrink-0 cursor-grab text-[var(--qg-text-faint)]" />
                        <span className="flex-1 leading-snug">{a.label}</span>
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
                            className={
                              "group/cell mx-auto grid h-9 w-9 place-items-center rounded-lg text-sm font-bold shadow-sm transition hover:scale-105 " +
                              (meta
                                ? ""
                                : "border border-[var(--qg-border)] hover:border-[var(--qg-accent)] hover:bg-[var(--qg-accent)]/10")
                            }
                            style={meta ? { background: meta.bg, color: "#fff" } : {}}
                            title={meta ? meta.full : "Clique pour assigner R, A, C ou I"}
                          >
                            {meta ? (
                              v
                            ) : (
                              <span className="text-base font-normal text-[var(--qg-text-faint)] opacity-0 transition group-hover/cell:opacity-100">
                                +
                              </span>
                            )}
                          </button>
                        </td>
                      );
                    })}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {personOpen ? (
        <PersonPicker
          people={people}
          onClose={() => setPersonOpen(false)}
          onSaved={() => {
            setPersonOpen(false);
            void load();
          }}
          onChanged={() => void load()}
        />
      ) : null}
      {activityModal ? (
        <ActivityModal
          activity={activityModal === "new" ? null : activityModal}
          poles={poles}
          subsections={subsections}
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
          subsections={subsections}
          onClose={() => setPoleManagerOpen(false)}
          onChanged={() => void load()}
        />
      ) : null}
      {importOpen ? (
        <ImportModal
          poles={poles}
          onClose={() => setImportOpen(false)}
          onSaved={() => {
            setImportOpen(false);
            void load();
          }}
        />
      ) : null}
    </div>
  );
}

function ImportModal({
  poles,
  onClose,
  onSaved
}: {
  poles: Pole[];
  onClose: () => void;
  onSaved: () => void;
}) {
  const [defaultPole, setDefaultPole] = useState(poles[0]?.label || "");
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [fileBusy, setFileBusy] = useState(false);

  async function handleFile(e: React.ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0];
    if (!f) return;
    setFileBusy(true);
    try {
      const form = new FormData();
      form.append("file", f);
      form.append("default_pole", defaultPole);
      const r = await authedFetch("/api/v1/raci/activities/import-file", {
        method: "POST",
        body: form
      });
      if (!r.ok) {
        alert((await r.text()).slice(0, 200) || `Échec (HTTP ${r.status}).`);
        return;
      }
      const d = (await r.json()) as { created?: number };
      alert(`${d.created || 0} tâche(s) importée(s).`);
      onSaved();
    } catch (err) {
      alert((err as Error).message);
    } finally {
      setFileBusy(false);
      e.target.value = "";
    }
  }

  const parsed = text
    .split(/\r?\n/)
    .map((l) => l.trim())
    .filter(Boolean)
    .map((line) => {
      // Accepte le collage Excel (tabulation), le format « > » ou « | ».
      const sep = line.includes("\t")
        ? "\t"
        : line.includes(">")
          ? ">"
          : line.includes("|")
            ? "|"
            : null;
      const parts = sep
        ? line.split(sep).map((x) => x.trim())
        : [line.trim()];
      if (parts.length >= 3) {
        return {
          pole: parts[0] || defaultPole,
          subsection: parts[1],
          label: parts.slice(2).join(" > ")
        };
      }
      if (parts.length === 2) {
        return { pole: parts[0] || defaultPole, subsection: "", label: parts[1] };
      }
      return { pole: defaultPole, subsection: "", label: parts[0] };
    })
    .filter((it) => it.label);

  async function submit() {
    if (parsed.length === 0) return;
    setBusy(true);
    try {
      await authedFetch("/api/v1/raci/activities/bulk", {
        method: "POST",
        body: JSON.stringify({ items: parsed })
      });
      onSaved();
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal title="Importer des tâches" onClose={onClose}>
      <p className="mb-2 text-xs text-[var(--qg-text-muted)]">
        Une tâche par ligne. Format :{" "}
        <code className="rounded bg-[var(--qg-card-bg)] px-1">
          Pôle &gt; Sous-section &gt; Tâche
        </code>{" "}
        (les deux premiers sont optionnels). Tu peux aussi coller 3
        colonnes depuis Excel. Les pôles / sous-sections manquants
        seront créés — tu pourras tout ajuster ensuite.
      </p>
      <label className="mb-1 block text-xs text-[var(--qg-text-muted)]">
        Pôle par défaut (lignes sans pôle)
      </label>
      <select
        className={INPUT}
        value={defaultPole}
        onChange={(e) => setDefaultPole(e.target.value)}
      >
        {poles.map((p) => (
          <option key={p.id} value={p.label}>
            {p.label}
          </option>
        ))}
      </select>
      <label className="mb-1 mt-3 block text-xs text-[var(--qg-text-muted)]">
        Importer un fichier (.xlsx, .csv, .txt)
      </label>
      <input
        type="file"
        accept=".xlsx,.xlsm,.csv,.txt,text/csv"
        onChange={(e) => void handleFile(e)}
        disabled={fileBusy}
        className="block w-full text-xs text-[var(--qg-text-muted)] file:mr-3 file:rounded-lg file:border-0 file:bg-[var(--qg-accent)] file:px-3 file:py-1.5 file:text-sm file:font-semibold file:text-white hover:file:opacity-90"
      />
      {fileBusy ? (
        <p className="mt-1 flex items-center gap-1.5 text-xs text-[var(--qg-text-muted)]">
          <Loader2 className="h-3 w-3 animate-spin" /> Import du fichier…
        </p>
      ) : null}

      <div className="my-3 flex items-center gap-2 text-[11px] uppercase tracking-wider text-[var(--qg-text-faint)]">
        <span className="h-px flex-1 bg-[var(--qg-border)]" />
        ou colle ci-dessous
        <span className="h-px flex-1 bg-[var(--qg-border)]" />
      </div>

      <textarea
        className={INPUT + " min-h-[160px] font-mono text-xs"}
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder={
          "Gestion locative > Encaissement > Encaisser les loyers\n" +
          "Gestion locative > Relancer les retards\n" +
          "Préparer les états financiers"
        }
        autoFocus
      />
      <p className="mt-2 text-xs text-[var(--qg-text-muted)]">
        {parsed.length} tâche{parsed.length > 1 ? "s" : ""} détectée
        {parsed.length > 1 ? "s" : ""}.
      </p>
      <div className="mt-4 flex justify-end gap-2">
        <button
          type="button"
          onClick={onClose}
          className="rounded-lg border border-[var(--qg-border)] px-3 py-2 text-sm hover:border-[var(--qg-accent)]"
        >
          Annuler
        </button>
        <button
          type="button"
          onClick={() => void submit()}
          disabled={busy || parsed.length === 0}
          className="inline-flex items-center gap-1.5 rounded-lg bg-[var(--qg-accent)] px-4 py-2 text-sm font-semibold text-white hover:opacity-90 disabled:opacity-50"
        >
          {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
          Importer {parsed.length || ""}
        </button>
      </div>
    </Modal>
  );
}

function PersonPicker({
  people,
  onClose,
  onSaved,
  onChanged
}: {
  people: Person[];
  onClose: () => void;
  onSaved: () => void;
  onChanged: () => void;
}) {
  const [users, setUsers] = useState<AvailableUser[] | null>(null);
  const [busy, setBusy] = useState<number | null>(null);

  const loadUsers = useCallback(async () => {
    const r = await authedFetch("/api/v1/raci/available-users");
    setUsers(r.ok ? ((await r.json()) as AvailableUser[]) : []);
  }, []);

  useEffect(() => {
    void loadUsers();
  }, [loadUsers]);

  async function add(u: AvailableUser) {
    setBusy(u.user_id);
    try {
      await authedFetch("/api/v1/raci/people", {
        method: "POST",
        body: JSON.stringify({ user_id: u.user_id })
      });
      onChanged();
      await loadUsers();
    } finally {
      setBusy(null);
    }
  }

  async function remove(per: Person) {
    setBusy(-per.id);
    try {
      await authedFetch(`/api/v1/raci/people/${per.id}`, {
        method: "DELETE"
      });
      onChanged();
      await loadUsers();
    } finally {
      setBusy(null);
    }
  }

  return (
    <Modal title="Personnes (colonnes)" onClose={onClose}>
      <p className="mb-3 text-xs text-[var(--qg-text-muted)]">
        Seuls les détenteurs d'un compte Kratos peuvent être des colonnes.
      </p>

      {people.length > 0 ? (
        <div className="mb-3">
          <div className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-[var(--qg-text-muted)]">
            Dans la matrice
          </div>
          <div className="space-y-1.5">
            {people.map((per) => (
              <div
                key={per.id}
                className="flex items-center justify-between rounded-lg border border-[var(--qg-border)] px-3 py-2 text-sm"
              >
                <span>
                  <span className="font-medium">{per.name}</span>
                  {per.subtitle ? (
                    <span className="ml-2 text-xs capitalize text-[var(--qg-text-muted)]">
                      {per.subtitle}
                    </span>
                  ) : null}
                </span>
                <button
                  type="button"
                  onClick={() => void remove(per)}
                  disabled={busy !== null}
                  className="rounded p-1 text-[var(--qg-text-faint)] hover:text-rose-400 disabled:opacity-50"
                  title="Retirer cette colonne"
                >
                  {busy === -per.id ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <Trash2 className="h-4 w-4" />
                  )}
                </button>
              </div>
            ))}
          </div>
        </div>
      ) : null}

      <div className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-[var(--qg-text-muted)]">
        Ajouter
      </div>
      {users === null ? (
        <div className="flex items-center gap-2 py-6 text-sm text-[var(--qg-text-muted)]">
          <Loader2 className="h-4 w-4 animate-spin" /> Chargement…
        </div>
      ) : users.length === 0 ? (
        <p className="py-6 text-center text-sm text-[var(--qg-text-muted)]">
          Tous les comptes sont déjà dans la matrice.
        </p>
      ) : (
        <div className="max-h-60 space-y-1.5 overflow-y-auto">
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
  subsections,
  onClose,
  onSaved
}: {
  activity: Activity | null;
  poles: Pole[];
  subsections: Subsection[];
  onClose: () => void;
  onSaved: () => void;
}) {
  const [pole, setPole] = useState(activity?.pole || poles[0]?.label || "");
  const [subsection, setSubsection] = useState(activity?.subsection || "");
  const [label, setLabel] = useState(activity?.label || "");
  const [busy, setBusy] = useState(false);

  const subsForPole = subsections.filter((s) => s.pole === pole);

  async function save() {
    if (!label.trim()) return;
    setBusy(true);
    try {
      const url = activity
        ? `/api/v1/raci/activities/${activity.id}`
        : "/api/v1/raci/activities";
      await authedFetch(url, {
        method: activity ? "PUT" : "POST",
        body: JSON.stringify({ pole, subsection, label: label.trim() })
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
        onChange={(e) => {
          setPole(e.target.value);
          setSubsection("");
        }}
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
        Sous-section (optionnel)
      </label>
      <select
        className={INPUT}
        value={subsection}
        onChange={(e) => setSubsection(e.target.value)}
      >
        <option value="">— Aucune (directe au pôle) —</option>
        {subsForPole.map((s) => (
          <option key={s.id} value={s.label}>
            {s.label}
          </option>
        ))}
        {subsection && !subsForPole.some((s) => s.label === subsection) ? (
          <option value={subsection}>{subsection}</option>
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
  subsections,
  onClose,
  onChanged
}: {
  poles: Pole[];
  subsections: Subsection[];
  onClose: () => void;
  onChanged: () => void;
}) {
  const [newPole, setNewPole] = useState("");
  const [newSub, setNewSub] = useState<Record<number, string>>({});
  // Copies locales pour un glisser-déposer fluide (optimiste).
  const [localPoles, setLocalPoles] = useState<Pole[]>(poles);
  const [localSubs, setLocalSubs] = useState<Subsection[]>(subsections);
  const [dragPole, setDragPole] = useState<number | null>(null);
  const [dragSub, setDragSub] = useState<{ id: number; pole: string } | null>(
    null
  );

  useEffect(() => setLocalPoles(poles), [poles]);
  useEffect(() => setLocalSubs(subsections), [subsections]);

  async function addPole() {
    if (!newPole.trim()) return;
    await authedFetch("/api/v1/raci/poles", {
      method: "POST",
      body: JSON.stringify({ label: newPole.trim() })
    });
    setNewPole("");
    onChanged();
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
  function dropPole(targetId: number) {
    if (dragPole == null || dragPole === targetId) return;
    const arr = [...localPoles];
    const from = arr.findIndex((p) => p.id === dragPole);
    if (from < 0) return;
    const moving = arr.splice(from, 1)[0];
    let to = arr.findIndex((p) => p.id === targetId);
    if (to < 0) to = arr.length;
    arr.splice(to, 0, moving);
    setLocalPoles(arr);
    setDragPole(null);
    void authedFetch("/api/v1/raci/poles/reorder", {
      method: "PUT",
      body: JSON.stringify({ ids: arr.map((p) => p.id) })
    }).then(() => onChanged());
  }

  async function addSub(pole: string, pid: number) {
    const v = (newSub[pid] || "").trim();
    if (!v) return;
    await authedFetch("/api/v1/raci/subsections", {
      method: "POST",
      body: JSON.stringify({ pole, label: v })
    });
    setNewSub((s) => ({ ...s, [pid]: "" }));
    onChanged();
  }
  async function renameSub(s: Subsection) {
    const v = prompt("Renommer la sous-section :", s.label);
    if (!v || !v.trim() || v.trim() === s.label) return;
    await authedFetch(`/api/v1/raci/subsections/${s.id}`, {
      method: "PUT",
      body: JSON.stringify({ pole: s.pole, label: v.trim() })
    });
    onChanged();
  }
  async function deleteSub(s: Subsection) {
    if (!confirm(`Supprimer la sous-section « ${s.label} » ?`)) return;
    await authedFetch(`/api/v1/raci/subsections/${s.id}`, {
      method: "DELETE"
    });
    onChanged();
  }
  function dropSub(target: Subsection) {
    if (
      !dragSub ||
      dragSub.pole !== target.pole ||
      dragSub.id === target.id
    )
      return;
    const inPole = localSubs.filter((s) => s.pole === target.pole);
    const others = localSubs.filter((s) => s.pole !== target.pole);
    const from = inPole.findIndex((s) => s.id === dragSub.id);
    if (from < 0) return;
    const moving = inPole.splice(from, 1)[0];
    let to = inPole.findIndex((s) => s.id === target.id);
    if (to < 0) to = inPole.length;
    inPole.splice(to, 0, moving);
    setLocalSubs([...others, ...inPole]);
    setDragSub(null);
    void authedFetch("/api/v1/raci/subsections/reorder", {
      method: "PUT",
      body: JSON.stringify({ ids: inPole.map((s) => s.id) })
    }).then(() => onChanged());
  }

  return (
    <Modal title="Pôles & sous-sections" onClose={onClose}>
      <p className="mb-2 text-xs text-[var(--qg-text-muted)]">
        Glisse les pôles (et leurs sous-sections) pour changer l'ordre — il se
        reflète aussitôt dans la matrice.
      </p>
      <div className="max-h-[60vh] space-y-2 overflow-y-auto">
        {localPoles.map((p) => (
          <div
            key={p.id}
            draggable
            onDragStart={() => setDragPole(p.id)}
            onDragEnd={() => setDragPole(null)}
            onDragOver={(e) => {
              if (dragPole != null) e.preventDefault();
            }}
            onDrop={() => dropPole(p.id)}
            className={
              "rounded-lg border border-[var(--qg-border)] p-2 " +
              (dragPole === p.id ? "opacity-40" : "")
            }
          >
            <div className="flex items-center justify-between text-sm font-semibold">
              <span className="flex items-center gap-1.5">
                <GripVertical className="h-4 w-4 cursor-grab text-[var(--qg-text-faint)]" />
                {p.label}
              </span>
              <span className="flex gap-1">
                <button
                  type="button"
                  onClick={() => void renamePole(p)}
                  className="rounded p-1 text-[var(--qg-text-faint)] hover:text-[var(--qg-accent)]"
                  title="Renommer le pôle"
                >
                  <Pencil className="h-3.5 w-3.5" />
                </button>
                <button
                  type="button"
                  onClick={() => void deletePole(p)}
                  className="rounded p-1 text-[var(--qg-text-faint)] hover:text-rose-400"
                  title="Supprimer le pôle"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </span>
            </div>
            <div className="mt-1.5 space-y-1 pl-3">
              {localSubs
                .filter((s) => s.pole === p.label)
                .map((s) => (
                  <div
                    key={s.id}
                    draggable
                    onDragStart={(e) => {
                      e.stopPropagation();
                      setDragSub({ id: s.id, pole: s.pole });
                    }}
                    onDragEnd={() => setDragSub(null)}
                    onDragOver={(e) => {
                      if (dragSub) {
                        e.preventDefault();
                        e.stopPropagation();
                      }
                    }}
                    onDrop={(e) => {
                      e.stopPropagation();
                      dropSub(s);
                    }}
                    className={
                      "flex items-center justify-between rounded text-xs text-[var(--qg-text-muted)] " +
                      (dragSub?.id === s.id ? "opacity-40" : "")
                    }
                  >
                    <span className="flex items-center gap-1">
                      <GripVertical className="h-3 w-3 cursor-grab text-[var(--qg-text-faint)]" />
                      ↳ {s.label}
                    </span>
                    <span className="flex gap-1">
                      <button
                        type="button"
                        onClick={() => void renameSub(s)}
                        className="rounded p-0.5 hover:text-[var(--qg-accent)]"
                        title="Renommer"
                      >
                        <Pencil className="h-3 w-3" />
                      </button>
                      <button
                        type="button"
                        onClick={() => void deleteSub(s)}
                        className="rounded p-0.5 hover:text-rose-400"
                        title="Supprimer"
                      >
                        <Trash2 className="h-3 w-3" />
                      </button>
                    </span>
                  </div>
                ))}
              <div className="flex gap-1.5 pt-1">
                <input
                  className={INPUT + " py-1 text-xs"}
                  value={newSub[p.id] || ""}
                  onChange={(e) =>
                    setNewSub((s) => ({ ...s, [p.id]: e.target.value }))
                  }
                  placeholder="Nouvelle sous-section…"
                  onKeyDown={(e) => {
                    if (e.key === "Enter") void addSub(p.label, p.id);
                  }}
                />
                <button
                  type="button"
                  onClick={() => void addSub(p.label, p.id)}
                  className="shrink-0 rounded-lg border border-[var(--qg-border)] px-2 text-xs hover:border-[var(--qg-accent)]"
                >
                  <Plus className="h-3.5 w-3.5" />
                </button>
              </div>
            </div>
          </div>
        ))}
      </div>
      <div className="mt-3 flex gap-2 border-t border-[var(--qg-border)] pt-3">
        <input
          className={INPUT}
          value={newPole}
          onChange={(e) => setNewPole(e.target.value)}
          placeholder="Nouveau pôle…"
          onKeyDown={(e) => {
            if (e.key === "Enter") void addPole();
          }}
        />
        <button
          type="button"
          onClick={() => void addPole()}
          className="inline-flex shrink-0 items-center gap-1 rounded-lg bg-[var(--qg-accent)] px-3 py-2 text-sm font-semibold text-white hover:opacity-90"
        >
          <Plus className="h-4 w-4" /> Pôle
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
