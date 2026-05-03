"use client";

import { useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  Clock,
  Filter,
  Loader2,
  Sparkles,
  Target
} from "lucide-react";

import { Link } from "@/i18n/navigation";
import { authedFetch } from "@/lib/auth";
import { QGTopbar } from "../layout";

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

const STATUS_LABELS: Record<string, string> = {
  backlog: "Backlog",
  todo: "À faire",
  in_progress: "En cours",
  waiting: "En attente",
  done: "Terminé"
};

const STATUS_COLORS: Record<string, string> = {
  backlog: "var(--qg-text-soft)",
  todo: "var(--qg-accent)",
  in_progress: "#60a5fa",
  waiting: "#ffaa33",
  done: "#4ade80"
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
        {/* Toggle Mes / Toutes */}
        <div className="mb-3 inline-flex rounded-lg border border-[var(--qg-border)] bg-[var(--qg-card-bg)] p-0.5">
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

        {/* Tableau */}
        <div
          className="overflow-hidden rounded-xl"
          style={{
            backgroundColor: "var(--qg-card-bg)",
            border: "1px solid var(--qg-border)"
          }}
        >
          {error ? (
            <p className="m-4 rounded-md border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-300">
              {error}
            </p>
          ) : null}

          {loading ? (
            <div className="flex min-h-[300px] items-center justify-center">
              <Loader2 className="h-5 w-5 animate-spin text-[var(--qg-accent)]" />
            </div>
          ) : filtered.length === 0 ? (
            <div className="px-6 py-12 text-center">
              <Target className="mx-auto h-8 w-8 text-[var(--qg-text-faint)]" />
              <p className="mt-3 text-sm text-[var(--qg-text-muted)]">
                Aucune tâche pour ces filtres.
              </p>
            </div>
          ) : (
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
                  />
                ))}
              </tbody>
            </table>
          )}
        </div>
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

function AssigneeChip({
  user
}: {
  user: TeamMember | null;
}) {
  if (!user) {
    return (
      <span className="inline-flex items-center text-[11px] text-[var(--qg-text-soft)]">
        Non assigné
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1.5">
      <span
        className="flex h-5 w-5 items-center justify-center rounded-full text-[9px] font-bold"
        style={{ backgroundColor: "var(--qg-accent)", color: "var(--qg-bg)" }}
      >
        {initialsFor(user.full_name)}
      </span>
      <span className="text-[11px] text-[var(--qg-text-muted)]">
        {user.full_name.split(" ")[0]}
      </span>
    </span>
  );
}

function TacheRow({
  t,
  ent,
  team
}: {
  t: Tache;
  ent: Entreprise | undefined;
  team: TeamMember[];
}) {
  const prio = scoreToPriority(t.score);
  const due = dueLabel(t.due_date);
  const statusColor = STATUS_COLORS[t.status] || "var(--qg-text-muted)";
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
        <span
          className="inline-flex items-center gap-1.5 rounded-md px-2 py-0.5 text-[11px] font-semibold"
          style={{
            backgroundColor: statusColor + "1f",
            color: statusColor
          }}
        >
          <span
            className="h-1.5 w-1.5 rounded-full"
            style={{ backgroundColor: statusColor }}
          />
          {STATUS_LABELS[t.status] || t.status}
        </span>
      </td>
      <td className="px-3 py-3 text-[11px] text-[var(--qg-text-muted)]">
        {t.departement || <span className="text-[var(--qg-text-soft)]">—</span>}
      </td>
      <td className="px-3 py-3">
        <AssigneeChip
          user={team.find((u) => u.id === t.assignee_user_id) || null}
        />
      </td>
      <td className="px-3 py-3 text-right">
        {t.due_date ? (
          <span
            className="inline-flex items-center gap-1 text-[11px] font-semibold"
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
          <span className="text-[11px] text-[var(--qg-text-soft)]">—</span>
        )}
      </td>
    </tr>
  );
}
