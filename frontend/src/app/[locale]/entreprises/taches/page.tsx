"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  Clock,
  Filter,
  Loader2,
  Target
} from "lucide-react";

import { Link } from "@/i18n/navigation";
import { authedFetch } from "@/lib/auth";
import { QGTopbar } from "../layout";
import { TASK_STATUS_LABEL, TASK_STATUS_OPTIONS } from "@/lib/task-config";

type TachePatch = Partial<
  Pick<Tache, "status" | "assignee_user_id" | "due_date">
>;

type Tache = {
  id: number;
  entreprise_id: number;
  title: string;
  description: string | null;
  departement: string | null;
  status: string;
  impact: number | null;
  confidence: number | null;
  effort: number | null;
  due_date: string | null;
  score: number | null;
  assignee_user_id: number | null;
};

type TeamMember = {
  id: number;
  email: string;
  full_name: string;
};

type Entreprise = {
  id: number;
  name: string;
  color_accent: string;
};

// 4 statuts opérationnels — labels viennent du module partagé
// /lib/task-config. Couleurs hex équivalentes ci-dessous (le
// module utilise des classes Tailwind alors qu'ici on a besoin
// de variables CSS pour des inline-style). Si les classes
// Tailwind du module changent, mettre à jour ces hex aussi.
const STATUS_LABELS: Record<string, string> = TASK_STATUS_LABEL;

const STATUS_COLORS: Record<string, string> = {
  todo: "#8b5cf6",        // violet-500
  a_faire: "#0ea5e9",     // sky-500
  in_progress: "#f59e0b", // amber-500
  done: "#10b981"         // emerald-500
};

const STATUS_DISPLAY_FALLBACK: Record<string, { label: string; color: string }> = {
  backlog: { label: "Backlog", color: "var(--qg-text-soft)" },
  waiting: { label: "En attente", color: "#ffaa33" }
};

function scoreToPriority(score: number | null): {
  label: string;
  color: string;
} {
  if (score == null) return { label: "P4", color: "var(--qg-text-soft)" };
  if (score >= 30) return { label: "P1", color: "#ff5566" };
  if (score >= 15) return { label: "P2", color: "#ffaa33" };
  if (score >= 5) return { label: "P3", color: "#60a5fa" };
  return { label: "P4", color: "var(--qg-text-soft)" };
}

function dueLabel(s: string | null): { text: string; tone: string } {
  if (!s) return { text: "—", tone: "var(--qg-text-soft)" };
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(s);
  if (!m) return { text: s, tone: "var(--qg-text-muted)" };
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const d = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
  const days = Math.round((d.getTime() - today.getTime()) / 86400000);
  const fmt = d.toLocaleDateString("fr-CA", {
    day: "2-digit",
    month: "short"
  });
  if (days < 0) return { text: `${fmt} (${-days}j)`, tone: "#ff5566" };
  if (days === 0) return { text: "Aujourd'hui", tone: "#ffaa33" };
  if (days <= 7) return { text: fmt, tone: "#ffaa33" };
  return { text: fmt, tone: "var(--qg-text-muted)" };
}

export default function MesTachesPage() {
  const [taches, setTaches] = useState<Tache[]>([]);
  const [entreprises, setEntreprises] = useState<Entreprise[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Filtres
  const [scope, setScope] = useState<"all" | "mine">("all");
  const [view, setView] = useState<"table" | "kanban">("table");
  const [filterEntreprise, setFilterEntreprise] = useState<string>("");
  const [filterStatus, setFilterStatus] = useState<string>("open");
  const [filterDept, setFilterDept] = useState<string>("");
  const [filterPriority, setFilterPriority] = useState<string>("");
  const [filterAssignee, setFilterAssignee] = useState<string>("");
  const [team, setTeam] = useState<TeamMember[]>([]);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      setLoading(true);
      setError(null);
      try {
        const tachesUrl = scope === "mine"
          ? "/api/v1/entreprises/taches?mine=true"
          : "/api/v1/entreprises/taches";
        const [tRes, eRes, uRes] = await Promise.all([
          authedFetch(tachesUrl),
          authedFetch("/api/v1/entreprises"),
          authedFetch("/api/v1/entreprises/users/with-volet")
        ]);
        if (cancelled) return;
        if (!tRes.ok) throw new Error(`HTTP ${tRes.status}`);
        if (eRes.ok) {
          setEntreprises((await eRes.json()) as Entreprise[]);
        }
        if (uRes.ok) {
          setTeam((await uRes.json()) as TeamMember[]);
        }
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

  const onUpdate = useCallback(
    async (id: number, patch: TachePatch) => {
      // Optimistic update : on patche localement avant le PATCH HTTP.
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
        setTaches(before); // rollback
        setError(`Échec mise à jour : ${(err as Error).message}`);
      }
    },
    [taches]
  );

  const entById = useMemo(() => {
    const m = new Map<number, Entreprise>();
    entreprises.forEach((e) => m.set(e.id, e));
    return m;
  }, [entreprises]);

  const departements = useMemo(() => {
    const set = new Set<string>();
    taches.forEach((t) => t.departement && set.add(t.departement));
    return Array.from(set).sort();
  }, [taches]);

  const filtered = useMemo(() => {
    return taches
      .filter((t) => {
        if (filterEntreprise && String(t.entreprise_id) !== filterEntreprise)
          return false;
        if (filterStatus === "open" && t.status === "done") return false;
        if (filterStatus !== "" && filterStatus !== "open" && t.status !== filterStatus)
          return false;
        if (filterDept && t.departement !== filterDept) return false;
        if (filterPriority) {
          const p = scoreToPriority(t.score).label;
          if (p !== filterPriority) return false;
        }
        if (filterAssignee) {
          if (filterAssignee === "unassigned") {
            if (t.assignee_user_id != null) return false;
          } else if (String(t.assignee_user_id ?? "") !== filterAssignee) {
            return false;
          }
        }
        return true;
      })
      .sort((a, b) => (b.score ?? -1) - (a.score ?? -1));
  }, [
    taches,
    filterEntreprise,
    filterStatus,
    filterDept,
    filterPriority,
    filterAssignee
  ]);

  const subtitle = `${filtered.length} TÂCHE${filtered.length > 1 ? "S" : ""} · ${
    filtered.filter((t) => scoreToPriority(t.score).label === "P1").length
  } P1 · ${filtered.filter((t) => {
    if (!t.due_date) return false;
    const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(t.due_date);
    if (!m) return false;
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    const d = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
    return d < today;
  }).length} EN RETARD`;

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
        {/* Toggles : Mes / Toutes — Tableau / Kanban */}
        <div className="mb-3 flex flex-wrap items-center gap-2">
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
          <div className="inline-flex rounded-lg border border-[var(--qg-border)] bg-[var(--qg-card-bg)] p-0.5">
            <ScopeButton
              label="Tableau"
              active={view === "table"}
              onClick={() => setView("table")}
            />
            <ScopeButton
              label="Kanban"
              active={view === "kanban"}
              onClick={() => setView("kanban")}
            />
          </div>
        </div>

        {/* Filtres */}
        <div className="mb-5 flex flex-wrap items-center gap-2">
          <Filter className="h-4 w-4 text-[var(--qg-text-soft)]" />
          <FilterSelect
            value={filterEntreprise}
            onChange={setFilterEntreprise}
            options={[
              { value: "", label: "Toutes entreprises" },
              ...entreprises.map((e) => ({
                value: String(e.id),
                label: e.name
              }))
            ]}
          />
          {scope === "all" ? (
            <FilterSelect
              value={filterAssignee}
              onChange={setFilterAssignee}
              options={[
                { value: "", label: "Tous assignés" },
                { value: "unassigned", label: "Non assignées" },
                ...team.map((u) => ({
                  value: String(u.id),
                  label: u.full_name
                }))
              ]}
            />
          ) : null}
          <FilterSelect
            value={filterStatus}
            onChange={setFilterStatus}
            options={[
              { value: "open", label: "Ouvertes" },
              { value: "", label: "Toutes" },
              { value: "todo", label: "À faire" },
              { value: "in_progress", label: "En cours" },
              { value: "waiting", label: "En attente" },
              { value: "done", label: "Terminées" }
            ]}
          />
          {departements.length > 0 ? (
            <FilterSelect
              value={filterDept}
              onChange={setFilterDept}
              options={[
                { value: "", label: "Tous départements" },
                ...departements.map((d) => ({ value: d, label: d }))
              ]}
            />
          ) : null}
          <FilterSelect
            value={filterPriority}
            onChange={setFilterPriority}
            options={[
              { value: "", label: "Toutes priorités" },
              { value: "P1", label: "P1 — Critique" },
              { value: "P2", label: "P2 — Haute" },
              { value: "P3", label: "P3 — Normale" },
              { value: "P4", label: "P4 — Basse / Non scoré" }
            ]}
          />
        </div>

        {/* Erreurs / loading communs aux deux vues */}
        {error ? (
          <p className="mb-3 rounded-md border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-300">
            {error}
          </p>
        ) : null}

        {loading ? (
          <div className="flex min-h-[300px] items-center justify-center rounded-xl border border-[var(--qg-border)] bg-[var(--qg-card-bg)]">
            <Loader2 className="h-5 w-5 animate-spin text-[var(--qg-accent)]" />
          </div>
        ) : filtered.length === 0 ? (
          <div className="rounded-xl border border-[var(--qg-border)] bg-[var(--qg-card-bg)] px-6 py-12 text-center">
            <Target className="mx-auto h-8 w-8 text-[var(--qg-text-faint)]" />
            <p className="mt-3 text-sm text-[var(--qg-text-muted)]">
              Aucune tâche pour ces filtres.
            </p>
          </div>
        ) : view === "kanban" ? (
          <KanbanBoard
            taches={filtered}
            entById={entById}
            team={team}
            onUpdate={onUpdate}
          />
        ) : (
          <div
            className="overflow-hidden rounded-xl"
            style={{
              backgroundColor: "var(--qg-card-bg)",
              border: "1px solid var(--qg-border)"
            }}
          >
            <table className="w-full text-[13px]">
              <thead>
                <tr
                  className="text-[10px] uppercase tracking-wider text-[var(--qg-text-soft)]"
                  style={{ borderBottom: "1px solid var(--qg-border)" }}
                >
                  <th className="px-3 py-2.5 text-left">Prio</th>
                  <th className="px-3 py-2.5 text-right">Score</th>
                  <th className="px-4 py-2.5 text-left">Tâche</th>
                  <th className="px-3 py-2.5 text-left">Entreprise</th>
                  <th className="px-3 py-2.5 text-left">Statut</th>
                  <th className="px-3 py-2.5 text-left">Département</th>
                  <th className="px-3 py-2.5 text-left">Assigné</th>
                  <th className="px-3 py-2.5 text-right">Échéance</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((t) => (
                  <TacheRow
                    key={t.id}
                    t={t}
                    ent={entById.get(t.entreprise_id)}
                    team={team}
                    onUpdate={onUpdate}
                  />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </>
  );
}

// ─── Vue Kanban ────────────────────────────────────────────────────────

const KANBAN_COLUMNS = TASK_STATUS_OPTIONS.map((o) => ({
  id: o.value,
  label: o.label
}));

function KanbanBoard({
  taches,
  entById,
  team,
  onUpdate
}: {
  taches: Tache[];
  entById: Map<number, Entreprise>;
  team: TeamMember[];
  onUpdate: (id: number, patch: TachePatch) => void;
}) {
  const [draggingId, setDraggingId] = useState<number | null>(null);
  const [overCol, setOverCol] = useState<string | null>(null);

  const grouped = KANBAN_COLUMNS.map((c) => ({
    ...c,
    cards: taches.filter((t) => t.status === c.id)
  }));
  return (
    <div className="flex gap-3 overflow-x-auto pb-2">
      {grouped.map((col) => {
        const accent = STATUS_COLORS[col.id] || "var(--qg-text-soft)";
        const isOver = overCol === col.id && draggingId != null;
        return (
          <div
            key={col.id}
            className="flex w-[280px] flex-shrink-0 flex-col rounded-xl border bg-[var(--qg-card-bg)] transition"
            style={{
              borderColor: isOver
                ? "var(--qg-accent)"
                : "var(--qg-border)",
              backgroundColor: isOver
                ? "color-mix(in srgb, var(--qg-accent) 10%, var(--qg-card-bg))"
                : "var(--qg-card-bg)"
            }}
            onDragOver={(e) => {
              if (draggingId != null) {
                e.preventDefault();
                setOverCol(col.id);
              }
            }}
            onDragLeave={() => {
              if (overCol === col.id) setOverCol(null);
            }}
            onDrop={(e) => {
              e.preventDefault();
              if (draggingId != null) {
                const t = taches.find((x) => x.id === draggingId);
                if (t && t.status !== col.id) {
                  onUpdate(draggingId, { status: col.id });
                }
              }
              setDraggingId(null);
              setOverCol(null);
            }}
          >
            <div
              className="flex items-center justify-between border-b border-[var(--qg-border)] px-3 py-2"
            >
              <div className="flex items-center gap-2">
                <span
                  className="h-2 w-2 rounded-full"
                  style={{ backgroundColor: accent }}
                />
                <span className="text-[11px] font-bold uppercase tracking-wider text-[var(--qg-text-muted)]">
                  {col.label}
                </span>
              </div>
              <span className="font-mono text-[10px] text-[var(--qg-text-soft)]">
                {col.cards.length}
              </span>
            </div>
            <ul className="flex-1 space-y-2 overflow-y-auto p-2">
              {col.cards.map((t) => (
                <KanbanCard
                  key={t.id}
                  t={t}
                  ent={entById.get(t.entreprise_id)}
                  team={team}
                  isDragging={draggingId === t.id}
                  onDragStart={() => setDraggingId(t.id)}
                  onDragEnd={() => {
                    setDraggingId(null);
                    setOverCol(null);
                  }}
                />
              ))}
              {col.cards.length === 0 ? (
                <li className="px-2 py-3 text-center text-[10px] text-[var(--qg-text-faint)]">
                  —
                </li>
              ) : null}
            </ul>
          </div>
        );
      })}
    </div>
  );
}

function KanbanCard({
  t,
  ent,
  team,
  isDragging,
  onDragStart,
  onDragEnd
}: {
  t: Tache;
  ent: Entreprise | undefined;
  team: TeamMember[];
  isDragging: boolean;
  onDragStart: () => void;
  onDragEnd: () => void;
}) {
  const prio = scoreToPriority(t.score);
  const due = dueLabel(t.due_date);
  const assignee = team.find((u) => u.id === t.assignee_user_id) || null;
  return (
    <li>
      <div
        draggable
        onDragStart={(e) => {
          e.dataTransfer.effectAllowed = "move";
          // Firefox refuse de démarrer un drag sans payload
          e.dataTransfer.setData("text/plain", String(t.id));
          onDragStart();
        }}
        onDragEnd={onDragEnd}
        className="block cursor-grab rounded-lg border border-[var(--qg-border)] bg-[var(--qg-bg)] p-2.5 transition hover:border-[var(--qg-accent)] active:cursor-grabbing"
        style={{ opacity: isDragging ? 0.4 : 1 }}
      >
        <div className="flex items-center justify-between gap-2">
          <span
            className="rounded px-1.5 py-0.5 text-[9px] font-bold"
            style={{
              backgroundColor: prio.color + "26",
              color: prio.color,
              fontFamily: "var(--font-mono, ui-monospace), monospace"
            }}
          >
            {prio.label}
          </span>
          {t.score != null ? (
            <span
              className="font-mono text-[10px] font-bold text-[var(--qg-accent)]"
            >
              {t.score.toFixed(1)}
            </span>
          ) : null}
        </div>
        <Link
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          href={`/entreprises/${t.entreprise_id}` as any}
          className="mt-1.5 block line-clamp-2 text-[12px] font-medium leading-snug text-[var(--qg-text)] hover:text-[var(--qg-accent)]"
          // Le drag de la carte démarre sur le parent (draggable=true) ;
          // on désactive le drag natif du <a> pour qu'il ne capture pas
          // l'événement avant le parent.
          draggable={false}
        >
          {t.title}
        </Link>
        {ent ? (
          <p className="mt-1.5 flex items-center gap-1 text-[10px] text-[var(--qg-text-muted)]">
            <span
              className="h-1 w-1 rounded-full"
              style={{ backgroundColor: ent.color_accent }}
            />
            <span className="truncate">{ent.name}</span>
          </p>
        ) : null}
        <div className="mt-1.5 flex items-center justify-between text-[10px]">
          <span
            style={{
              color: due.tone,
              fontFamily: "var(--font-mono, ui-monospace), monospace"
            }}
          >
            {due.text}
          </span>
          {assignee ? (
            <span
              className="flex h-4 w-4 items-center justify-center rounded-full font-bold"
              style={{
                backgroundColor: "var(--qg-accent)",
                color: "var(--qg-bg)",
                fontSize: "8px"
              }}
              title={assignee.full_name}
            >
              {assignee.full_name
                .split(/\s+/)
                .filter(Boolean)
                .slice(0, 2)
                .map((p) => p[0]?.toUpperCase() || "")
                .join("")}
            </span>
          ) : null}
        </div>
      </div>
    </li>
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
      className="rounded-md px-3 py-1.5 text-xs font-semibold transition"
      style={{
        backgroundColor: active ? "var(--qg-accent)" : "transparent",
        color: active ? "var(--qg-bg)" : "rgba(245,245,247,0.6)"
      }}
    >
      {label}
    </button>
  );
}

function FilterSelect({
  value,
  onChange,
  options
}: {
  value: string;
  onChange: (v: string) => void;
  options: { value: string; label: string }[];
}) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className="rounded-md px-3 py-1.5 text-[12px] focus:outline-none focus:ring-1"
      style={{
        backgroundColor: "var(--qg-card-bg)",
        color: "var(--qg-text)",
        border: "1px solid var(--qg-border)"
      }}
    >
      {options.map((o) => (
        <option key={o.value} value={o.value} className="bg-[var(--qg-card-bg)]">
          {o.label}
        </option>
      ))}
    </select>
  );
}

function initialsFor(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((p) => p[0]?.toUpperCase() || "")
    .join("");
}

function TacheRow({
  t,
  ent,
  team,
  onUpdate
}: {
  t: Tache;
  ent: Entreprise | undefined;
  team: TeamMember[];
  onUpdate: (id: number, patch: TachePatch) => void;
}) {
  const prio = scoreToPriority(t.score);
  return (
    <tr
      className="hover:bg-[var(--qg-bg-alt)]"
      style={{ borderBottom: "1px solid var(--qg-border-soft)" }}
    >
      <td className="px-3 py-3">
        <span
          className="inline-flex h-6 min-w-[28px] items-center justify-center rounded-md px-2 text-[10px] font-bold"
          style={{
            backgroundColor: prio.color + "26",
            color: prio.color,
            fontFamily: "var(--font-mono, ui-monospace), monospace"
          }}
        >
          {prio.label}
        </span>
      </td>
      <td
        className="px-3 py-3 text-right text-[12px] font-bold tabular-nums"
        style={{
          fontFamily: "var(--font-mono, ui-monospace), monospace",
          color: t.score == null ? "var(--qg-text-soft)" : "var(--qg-accent)"
        }}
      >
        {t.score != null ? t.score.toFixed(1) : "—"}
      </td>
      <td className="px-4 py-3 max-w-[400px]">
        <Link
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          href={`/entreprises/${t.entreprise_id}` as any}
          className="block truncate font-medium text-[var(--qg-text)] hover:text-[var(--qg-accent)]"
        >
          {t.title}
        </Link>
        {t.description ? (
          <p className="mt-0.5 line-clamp-1 text-[11px] text-[var(--qg-text-soft)]">
            {t.description}
          </p>
        ) : null}
      </td>
      <td className="px-3 py-3 text-[12px]">
        {ent ? (
          <span className="inline-flex items-center gap-1.5">
            <span
              className="h-1.5 w-1.5 rounded-full"
              style={{ backgroundColor: ent.color_accent }}
            />
            <span className="text-[var(--qg-text-muted)]">{ent.name}</span>
          </span>
        ) : (
          <span className="text-[var(--qg-text-soft)]">#{t.entreprise_id}</span>
        )}
      </td>
      <td className="px-3 py-3">
        <StatusEditor
          status={t.status}
          onChange={(v) => onUpdate(t.id, { status: v })}
        />
      </td>
      <td className="px-3 py-3 text-[11px] text-[var(--qg-text-muted)]">
        {t.departement || <span className="text-[var(--qg-text-soft)]">—</span>}
      </td>
      <td className="px-3 py-3">
        <AssigneeEditor
          assigneeId={t.assignee_user_id}
          team={team}
          onChange={(v) => onUpdate(t.id, { assignee_user_id: v })}
        />
      </td>
      <td className="px-3 py-3 text-right">
        <DueDateEditor
          value={t.due_date}
          onChange={(v) => onUpdate(t.id, { due_date: v })}
        />
      </td>
    </tr>
  );
}

// ─── Éditeurs inline ────────────────────────────────────────────────────

function StatusEditor({
  status,
  onChange
}: {
  status: string;
  onChange: (v: string) => void;
}) {
  // Fallback de display pour les statuts hors-UI (ex. backlog
  // hérité d'imports Monday non re-classifiés) — on affiche
  // quand même la pastille pour ne pas perdre l'info.
  const fallback = STATUS_DISPLAY_FALLBACK[status];
  const color =
    STATUS_COLORS[status] || fallback?.color || "var(--qg-text-muted)";
  const label = STATUS_LABELS[status] || fallback?.label || status;
  return (
    <span
      className="relative inline-flex items-center gap-1.5 rounded-md px-2 py-0.5 text-[11px] font-semibold"
      style={{ backgroundColor: color + "1f", color }}
    >
      <span
        className="h-1.5 w-1.5 rounded-full"
        style={{ backgroundColor: color }}
      />
      {label}
      <select
        value={status}
        onChange={(e) => onChange(e.target.value)}
        aria-label="Modifier le statut"
        className="absolute inset-0 cursor-pointer opacity-0"
      >
        {Object.entries(STATUS_LABELS).map(([v, label]) => (
          <option key={v} value={v}>
            {label}
          </option>
        ))}
      </select>
    </span>
  );
}

function AssigneeEditor({
  assigneeId,
  team,
  onChange
}: {
  assigneeId: number | null;
  team: TeamMember[];
  onChange: (v: number | null) => void;
}) {
  const user = team.find((u) => u.id === assigneeId) || null;
  return (
    <span className="relative inline-flex items-center gap-1.5">
      {user ? (
        <>
          <span
            className="flex h-5 w-5 items-center justify-center rounded-full text-[9px] font-bold"
            style={{
              backgroundColor: "var(--qg-accent)",
              color: "var(--qg-bg)"
            }}
          >
            {initialsFor(user.full_name)}
          </span>
          <span className="text-[11px] text-[var(--qg-text-muted)]">
            {user.full_name.split(" ")[0]}
          </span>
        </>
      ) : (
        <span className="text-[11px] text-[var(--qg-text-soft)] underline decoration-dotted">
          Non assigné
        </span>
      )}
      <select
        value={assigneeId == null ? "" : String(assigneeId)}
        onChange={(e) => {
          const v = e.target.value;
          onChange(v === "" ? null : Number(v));
        }}
        aria-label="Modifier l'assigné"
        className="absolute inset-0 cursor-pointer opacity-0"
      >
        <option value="">— Non assigné</option>
        {team.map((u) => (
          <option key={u.id} value={u.id}>
            {u.full_name}
          </option>
        ))}
      </select>
    </span>
  );
}

function DueDateEditor({
  value,
  onChange
}: {
  value: string | null;
  onChange: (v: string | null) => void;
}) {
  const due = dueLabel(value);
  // Pour <input type="date">, on a besoin de YYYY-MM-DD strict.
  const ymd = value
    ? (/^(\d{4}-\d{2}-\d{2})/.exec(value)?.[1] ?? "")
    : "";
  return (
    <span className="relative inline-flex items-center gap-1 text-[11px] font-semibold justify-end">
      {value ? (
        <span
          className="inline-flex items-center gap-1"
          style={{
            color: due.tone,
            fontFamily: "var(--font-mono, ui-monospace), monospace"
          }}
        >
          {due.tone === "#ff5566" ? (
            <AlertTriangle className="h-2.5 w-2.5" />
          ) : (
            <Clock className="h-2.5 w-2.5" />
          )}
          {due.text}
        </span>
      ) : (
        <span className="text-[var(--qg-text-soft)] underline decoration-dotted">
          + échéance
        </span>
      )}
      <input
        type="date"
        value={ymd}
        onChange={(e) => onChange(e.target.value || null)}
        aria-label="Modifier l'échéance"
        className="absolute inset-0 cursor-pointer opacity-0"
      />
    </span>
  );
}
