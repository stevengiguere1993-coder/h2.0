"use client";

import { useEffect, useMemo, useState } from "react";
import {
  Check,
  ChevronLeft,
  ChevronRight,
  Download,
  Loader2,
  Plus,
  Trash2,
  Users
} from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { Link } from "@/i18n/navigation";
import { useAppLayout } from "../../layout";
import { authedFetch } from "@/lib/auth";
import { projectLabel } from "@/lib/project";
import { useConfirm } from "@/components/confirm-dialog";

type Employe = { id: number; full_name: string; email: string | null };
type Project = { id: number; name: string; address?: string | null };
type Prospect = { id: number; name: string; status: string };

type Punch = {
  id: number;
  employe_id: number;
  project_id: number | null;
  contact_request_id: number | null;
  started_at: string;
  ended_at: string | null;
  hours: number | string | null;
  task: string | null;
  geolocation: string | null;
  approved: boolean;
  notes: string | null;
};

function pad(n: number): string {
  return String(n).padStart(2, "0");
}

function isoLocal(d: Date): string {
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(
    d.getDate()
  )}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function fmtDateTime(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleString("fr-CA", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit"
  });
}

function weekStartOf(d: Date): Date {
  const copy = new Date(d);
  copy.setHours(0, 0, 0, 0);
  const day = copy.getDay();
  const diff = (day + 6) % 7; // Monday = 0
  copy.setDate(copy.getDate() - diff);
  return copy;
}

function monthStartOf(d: Date): Date {
  const copy = new Date(d.getFullYear(), d.getMonth(), 1);
  copy.setHours(0, 0, 0, 0);
  return copy;
}

function monthEndOf(d: Date): Date {
  // 1er du mois suivant — exclusif
  return new Date(d.getFullYear(), d.getMonth() + 1, 1);
}

function calendarStartOf(monthStart: Date): Date {
  // Lundi de la semaine qui contient le 1er du mois
  return weekStartOf(monthStart);
}

function sameDay(a: Date, b: Date): boolean {
  return (
    a.getFullYear() === b.getFullYear() &&
    a.getMonth() === b.getMonth() &&
    a.getDate() === b.getDate()
  );
}

function shortISO(d: Date): string {
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

const MONTH_NAMES = [
  "janvier", "février", "mars", "avril", "mai", "juin",
  "juillet", "août", "septembre", "octobre", "novembre", "décembre"
];

type ViewMode = "week" | "month" | "payperiod";

// ---------------------------------------------------------------------------
// Périodes de paie — alignées sur l'ancre côté backend (punch_ops.py).
// Cycle de 14 jours samedi → vendredi. Ancre : période finissant le
// vendredi 2026-05-02. Toute autre période = ancre ± N × 14 jours.
// ---------------------------------------------------------------------------
const PAYROLL_ANCHOR_END = new Date(2026, 4, 2); // 2 mai 2026 (mois 0-based = avril+1=mai)
const PAYROLL_PERIOD_DAYS = 14;

function payPeriodForDate(d: Date): { start: Date; end: Date } {
  const ms = d.getTime() - PAYROLL_ANCHOR_END.getTime();
  const dayMs = 24 * 60 * 60 * 1000;
  const deltaDays = Math.round(ms / dayMs);
  const cycles = Math.round(deltaDays / PAYROLL_PERIOD_DAYS);
  const end = new Date(PAYROLL_ANCHOR_END);
  end.setDate(end.getDate() + cycles * PAYROLL_PERIOD_DAYS);
  end.setHours(23, 59, 59, 999);
  const start = new Date(end);
  start.setDate(start.getDate() - (PAYROLL_PERIOD_DAYS - 1));
  start.setHours(0, 0, 0, 0);
  return { start, end };
}

function shiftPayPeriod(end: Date, deltaCycles: number): Date {
  const next = new Date(end);
  next.setDate(next.getDate() + deltaCycles * PAYROLL_PERIOD_DAYS);
  return next;
}

function fmtFr(d: Date): string {
  return d.toLocaleDateString("fr-CA", {
    day: "2-digit",
    month: "short"
  });
}

// Affiche des heures décimales en « h/min » (ex. 7.89 → « 7 h 53 »),
// plus lisible qu'un décimal pour un relevé de temps.
function fmtHm(h: number): string {
  const totalMin = Math.round((h || 0) * 60);
  const hh = Math.floor(totalMin / 60);
  const mm = totalMin % 60;
  return `${hh} h ${String(mm).padStart(2, "0")}`;
}

export default function PunchGestionPage() {
  const confirm = useConfirm();
  const { onOpenSidebar } = useAppLayout();

  const [viewMode, setViewMode] = useState<ViewMode>("week");
  const [weekStart, setWeekStart] = useState(() => weekStartOf(new Date()));
  const [monthStart, setMonthStart] = useState(() => monthStartOf(new Date()));
  const [payPeriodEnd, setPayPeriodEnd] = useState<Date>(
    () => payPeriodForDate(new Date()).end
  );
  // En vue mois : si une journée est cliquée, on filtre la liste sur
  // ce jour seulement. Null = tout le mois affiché.
  const [selectedDay, setSelectedDay] = useState<Date | null>(null);
  const [punches, setPunches] = useState<Punch[]>([]);
  const [employes, setEmployes] = useState<Employe[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [prospects, setProspects] = useState<Prospect[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [modal, setModal] = useState<null | Punch | { fresh: true }>(null);
  const [filterEmploye, setFilterEmploye] = useState("");

  const weekEnd = useMemo(() => {
    const d = new Date(weekStart);
    d.setDate(d.getDate() + 7);
    return d;
  }, [weekStart]);

  // Période active selon le mode courant. En vue mois avec un jour
  // sélectionné : période = ce jour seulement.
  const period = useMemo<{ start: Date; end: Date }>(() => {
    if (viewMode === "month") {
      if (selectedDay) {
        const start = new Date(selectedDay);
        start.setHours(0, 0, 0, 0);
        const end = new Date(start);
        end.setDate(end.getDate() + 1);
        return { start, end };
      }
      return { start: monthStart, end: monthEndOf(monthStart) };
    }
    if (viewMode === "payperiod") {
      const pp = payPeriodForDate(payPeriodEnd);
      // end exclusif (jour suivant 00:00) pour le filtre standard
      const exclusiveEnd = new Date(pp.end);
      exclusiveEnd.setHours(0, 0, 0, 0);
      exclusiveEnd.setDate(exclusiveEnd.getDate() + 1);
      return { start: pp.start, end: exclusiveEnd };
    }
    return { start: weekStart, end: weekEnd };
  }, [viewMode, weekStart, weekEnd, monthStart, selectedDay, payPeriodEnd]);

  // Liste des semaines candidates pour le menu déroulant : 26 derniers
  // lundis + 4 lundis à venir (couvre 6 mois passés + 1 mois futur).
  const weekOptions = useMemo<Date[]>(() => {
    const today = weekStartOf(new Date());
    const out: Date[] = [];
    for (let i = -4; i <= 26; i++) {
      const d = new Date(today);
      d.setDate(d.getDate() - i * 7);
      out.push(d);
    }
    return out; // ordre : du futur vers le passé
  }, []);

  // Liste des périodes de paie candidates : 13 passées + 4 à venir.
  const payPeriodOptions = useMemo<Date[]>(() => {
    const current = payPeriodForDate(new Date()).end;
    const out: Date[] = [];
    for (let i = -4; i <= 13; i++) {
      out.push(shiftPayPeriod(current, -i));
    }
    return out;
  }, []);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const [pRes, eRes, prRes, csRes] = await Promise.all([
          authedFetch("/api/v1/punch?limit=500"),
          authedFetch("/api/v1/employes?limit=500&volet=construction"),
          authedFetch("/api/v1/projects?limit=500"),
          authedFetch("/api/v1/contact?limit=500")
        ]);
        if (!pRes.ok) throw new Error(`http_${pRes.status}`);
        const ps = (await pRes.json()) as Punch[];
        const es = eRes.ok ? ((await eRes.json()) as Employe[]) : [];
        const prs = prRes.ok ? ((await prRes.json()) as Project[]) : [];
        const css = csRes.ok ? ((await csRes.json()) as Prospect[]) : [];
        if (cancelled) return;
        setPunches(ps);
        setEmployes(es);
        setProjects(prs);
        setProspects(css);
      } catch {
        if (!cancelled) setError("Impossible de charger les punches.");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, []);

  const empById = useMemo(() => {
    const m = new Map<number, Employe>();
    employes.forEach((e) => m.set(e.id, e));
    return m;
  }, [employes]);

  const projById = useMemo(() => {
    const m = new Map<number, Project>();
    projects.forEach((p) => m.set(p.id, p));
    return m;
  }, [projects]);

  const prospById = useMemo(() => {
    const m = new Map<number, Prospect>();
    prospects.forEach((c) => m.set(c.id, c));
    return m;
  }, [prospects]);

  const visible = useMemo(() => {
    return punches
      .filter((p) => {
        const d = new Date(p.started_at);
        if (d < period.start || d >= period.end) return false;
        if (filterEmploye && String(p.employe_id) !== filterEmploye) return false;
        return true;
      })
      .sort(
        (a, b) =>
          new Date(b.started_at).getTime() - new Date(a.started_at).getTime()
      );
  }, [punches, period, filterEmploye]);

  // Pour chaque jour ISO : liste des employés ayant pointé ce jour
  // (avec leur cumul d'heures et la liste de leurs punches du jour).
  // Respecte le filtre employé courant. Trié par nom d'employé.
  const entriesByDay = useMemo(() => {
    type Entry = {
      employeId: number;
      name: string;
      hours: number;
      punches: Punch[];
    };
    const byDay = new Map<string, Map<number, Entry>>();
    for (const p of punches) {
      if (filterEmploye && String(p.employe_id) !== filterEmploye) continue;
      const d = new Date(p.started_at);
      const key = shortISO(d);
      let dayMap = byDay.get(key);
      if (!dayMap) {
        dayMap = new Map();
        byDay.set(key, dayMap);
      }
      let entry = dayMap.get(p.employe_id);
      if (!entry) {
        entry = {
          employeId: p.employe_id,
          name:
            empById.get(p.employe_id)?.full_name ||
            `#${p.employe_id}`,
          hours: 0,
          punches: []
        };
        dayMap.set(p.employe_id, entry);
      }
      entry.hours += p.hours != null ? Number(p.hours) : 0;
      entry.punches.push(p);
    }
    // Aplatit + trie par nom dans chaque jour
    const out = new Map<string, Entry[]>();
    for (const [k, m] of byDay) {
      const list = Array.from(m.values()).sort((a, b) =>
        a.name.localeCompare(b.name, "fr")
      );
      out.set(k, list);
    }
    return out;
  }, [punches, filterEmploye, empById]);

  const totalHours = useMemo(
    () =>
      visible.reduce(
        (sum, p) => sum + (p.hours != null ? Number(p.hours) : 0),
        0
      ),
    [visible]
  );

  function upsert(p: Punch) {
    setPunches((xs) => {
      const i = xs.findIndex((x) => x.id === p.id);
      if (i === -1) return [...xs, p];
      const n = xs.slice();
      n[i] = p;
      return n;
    });
  }

  async function toggleApprove(p: Punch) {
    try {
      const res = await authedFetch(`/api/v1/punch/${p.id}`, {
        method: "PATCH",
        body: JSON.stringify({ approved: !p.approved })
      });
      if (!res.ok) throw new Error();
      upsert((await res.json()) as Punch);
    } catch {
      setError("Approbation échouée.");
    }
  }

  async function remove(p: Punch) {
    if (!(await confirm(`Supprimer le punch du ${fmtDateTime(p.started_at)} ?`)))
      return;
    try {
      const res = await authedFetch(`/api/v1/punch/${p.id}`, {
        method: "DELETE"
      });
      if (!res.ok && res.status !== 204) throw new Error();
      setPunches((xs) => xs.filter((x) => x.id !== p.id));
    } catch {
      setError("Suppression échouée.");
    }
  }

  return (
    <>
      <AppTopbar
        breadcrumbs={[{ label: "Construction", href: "/app" }, { label: "Punch / Temps", href: "/app/punch" }, { label: "Gestion" }]}
        onOpenSidebar={onOpenSidebar}
        rightSlot={
          <div className="flex items-center gap-2">
            <Link
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
              href={"/app/punch/sous-traitants" as any}
              className="btn-secondary text-sm"
            >
              <Users className="mr-1.5 h-4 w-4" /> Sous-traitants
            </Link>
            <Link
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
              href={"/app/paie" as any}
              className="btn-secondary text-sm"
            >
              <Download className="mr-1.5 h-4 w-4" /> Rapport de paie
            </Link>
            <button
              type="button"
              onClick={() => setModal({ fresh: true })}
              className="btn-accent text-sm"
            >
              <Plus className="mr-1.5 h-4 w-4" /> Nouveau punch
            </button>
          </div>
        }
      />

      <div className="p-4 lg:p-6">
        {error ? (
          <p className="mb-4 rounded-lg border border-rose-500/40 bg-rose-500/10 px-4 py-2 text-sm text-rose-300">
            {error}
          </p>
        ) : null}

        <div className="mb-4 flex flex-wrap items-center gap-3">
          <Link
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            href={"/app/punch" as any}
            className="btn-secondary text-xs"
          >
            ← Vue employé
          </Link>

          {/* Toggle Semaine / Mois / Période de paie */}
          <div className="inline-flex items-center rounded-lg border border-brand-800 bg-brand-900 p-1">
            {(["week", "month", "payperiod"] as const).map((m) => (
              <button
                key={m}
                type="button"
                onClick={() => {
                  setViewMode(m);
                  setSelectedDay(null);
                }}
                className={`rounded-md px-3 py-1 text-xs font-semibold transition ${
                  viewMode === m
                    ? "bg-accent-500 text-brand-950"
                    : "text-white/70 hover:bg-brand-800 hover:text-white"
                }`}
              >
                {m === "week"
                  ? "Semaine"
                  : m === "month"
                  ? "Mois"
                  : "Période de paie"}
              </button>
            ))}
          </div>

          {/* Navigation période — varie selon le mode */}
          {viewMode === "week" ? (
            <>
              <div className="flex items-center gap-1 rounded-lg border border-brand-800 bg-brand-900 p-1">
                <button
                  type="button"
                  onClick={() => {
                    const d = new Date(weekStart);
                    d.setDate(d.getDate() - 7);
                    setWeekStart(d);
                  }}
                  className="rounded-md p-1.5 text-white/70 hover:bg-brand-800 hover:text-white"
                  aria-label="Semaine précédente"
                >
                  <ChevronLeft className="h-4 w-4" />
                </button>
                {/* Menu déroulant : sélection directe d'une semaine */}
                <select
                  value={shortISO(weekStart)}
                  onChange={(e) => {
                    const [y, mo, da] = e.target.value
                      .split("-")
                      .map(Number);
                    setWeekStart(new Date(y, mo - 1, da));
                  }}
                  className="min-w-[200px] cursor-pointer rounded-md bg-transparent px-2 text-center text-sm font-semibold text-white hover:bg-brand-800 focus:outline-none"
                  title="Choisir une semaine"
                >
                  {weekOptions.map((w) => {
                    const end = new Date(w);
                    end.setDate(end.getDate() + 6);
                    return (
                      <option
                        key={shortISO(w)}
                        value={shortISO(w)}
                        className="bg-brand-950 text-white"
                      >
                        Sem. {shortISO(w)} → {shortISO(end)}
                      </option>
                    );
                  })}
                </select>
                <button
                  type="button"
                  onClick={() => {
                    const d = new Date(weekStart);
                    d.setDate(d.getDate() + 7);
                    setWeekStart(d);
                  }}
                  className="rounded-md p-1.5 text-white/70 hover:bg-brand-800 hover:text-white"
                  aria-label="Semaine suivante"
                >
                  <ChevronRight className="h-4 w-4" />
                </button>
              </div>
              <button
                type="button"
                onClick={() => setWeekStart(weekStartOf(new Date()))}
                className="btn-secondary text-xs"
              >
                Cette semaine
              </button>
            </>
          ) : viewMode === "month" ? (
            <>
              <div className="flex items-center gap-1 rounded-lg border border-brand-800 bg-brand-900 p-1">
                <button
                  type="button"
                  onClick={() => {
                    const d = new Date(monthStart);
                    d.setMonth(d.getMonth() - 1);
                    setMonthStart(monthStartOf(d));
                    setSelectedDay(null);
                  }}
                  className="rounded-md p-1.5 text-white/70 hover:bg-brand-800 hover:text-white"
                  aria-label="Mois précédent"
                >
                  <ChevronLeft className="h-4 w-4" />
                </button>
                <span className="min-w-[160px] px-2 text-center text-sm font-semibold text-white">
                  {MONTH_NAMES[monthStart.getMonth()]}{" "}
                  {monthStart.getFullYear()}
                </span>
                <button
                  type="button"
                  onClick={() => {
                    const d = new Date(monthStart);
                    d.setMonth(d.getMonth() + 1);
                    setMonthStart(monthStartOf(d));
                    setSelectedDay(null);
                  }}
                  className="rounded-md p-1.5 text-white/70 hover:bg-brand-800 hover:text-white"
                  aria-label="Mois suivant"
                >
                  <ChevronRight className="h-4 w-4" />
                </button>
              </div>
              <button
                type="button"
                onClick={() => {
                  setMonthStart(monthStartOf(new Date()));
                  setSelectedDay(null);
                }}
                className="btn-secondary text-xs"
              >
                Ce mois
              </button>
              {selectedDay ? (
                <button
                  type="button"
                  onClick={() => setSelectedDay(null)}
                  className="rounded-md border border-accent-500/40 bg-accent-500/10 px-2 py-1 text-xs text-accent-300 hover:bg-accent-500/20"
                  title="Réinitialiser le jour sélectionné"
                >
                  ✕ {shortISO(selectedDay)}
                </button>
              ) : null}
            </>
          ) : (
            // viewMode === "payperiod"
            <>
              <div className="flex items-center gap-1 rounded-lg border border-brand-800 bg-brand-900 p-1">
                <button
                  type="button"
                  onClick={() =>
                    setPayPeriodEnd(shiftPayPeriod(payPeriodEnd, -1))
                  }
                  className="rounded-md p-1.5 text-white/70 hover:bg-brand-800 hover:text-white"
                  aria-label="Période précédente"
                >
                  <ChevronLeft className="h-4 w-4" />
                </button>
                {/* Menu déroulant : sélection directe d'une période de paie */}
                <select
                  value={shortISO(payPeriodEnd)}
                  onChange={(e) => {
                    const [y, mo, da] = e.target.value
                      .split("-")
                      .map(Number);
                    setPayPeriodEnd(new Date(y, mo - 1, da));
                  }}
                  className="min-w-[230px] cursor-pointer rounded-md bg-transparent px-2 text-center text-sm font-semibold text-white hover:bg-brand-800 focus:outline-none"
                  title="Choisir une période de paie"
                >
                  {payPeriodOptions.map((end) => {
                    const pp = payPeriodForDate(end);
                    return (
                      <option
                        key={shortISO(pp.end)}
                        value={shortISO(pp.end)}
                        className="bg-brand-950 text-white"
                      >
                        Paie {fmtFr(pp.start)} → {fmtFr(pp.end)}
                      </option>
                    );
                  })}
                </select>
                <button
                  type="button"
                  onClick={() =>
                    setPayPeriodEnd(shiftPayPeriod(payPeriodEnd, +1))
                  }
                  className="rounded-md p-1.5 text-white/70 hover:bg-brand-800 hover:text-white"
                  aria-label="Période suivante"
                >
                  <ChevronRight className="h-4 w-4" />
                </button>
              </div>
              <button
                type="button"
                onClick={() =>
                  setPayPeriodEnd(payPeriodForDate(new Date()).end)
                }
                className="btn-secondary text-xs"
              >
                Période courante
              </button>
            </>
          )}

          <select
            value={filterEmploye}
            onChange={(e) => setFilterEmploye(e.target.value)}
            className="input ml-auto w-48"
          >
            <option value="">Tous les employés</option>
            {employes.map((e) => (
              <option key={e.id} value={String(e.id)}>
                {e.full_name}
              </option>
            ))}
          </select>

          <div className="rounded-md bg-brand-900 px-3 py-2 text-sm">
            <span className="text-white/50">Total </span>
            <span className="font-bold text-white">
              {fmtHm(totalHours)}
            </span>
          </div>
        </div>

        {/* Calendrier mensuel — uniquement en vue Mois */}
        {viewMode === "month" ? (
          <MonthCalendar
            monthStart={monthStart}
            entriesByDay={entriesByDay}
            selectedDay={selectedDay}
            onSelectDay={(d) =>
              setSelectedDay((cur) =>
                cur && sameDay(cur, d) ? null : d
              )
            }
            onSelectPunch={(p) => setModal(p)}
          />
        ) : null}

        {loading ? (
          <div className="flex min-h-[40vh] items-center justify-center">
            <Loader2 className="h-6 w-6 animate-spin text-accent-500" />
          </div>
        ) : visible.length === 0 ? (
          <p className="mt-4 rounded-2xl border border-dashed border-brand-800 bg-brand-900/40 px-6 py-10 text-center text-sm text-white/60">
            {viewMode === "month"
              ? selectedDay
                ? `Aucun punch le ${shortISO(selectedDay)}.`
                : "Aucun punch ce mois-ci."
              : viewMode === "payperiod"
              ? "Aucun punch pour cette période de paie."
              : "Aucun punch pour cette semaine."}
          </p>
        ) : (
          <div className="mt-4 overflow-x-auto rounded-xl border border-brand-800 bg-brand-900">
            <table className="w-full text-sm">
              <thead className="border-b border-brand-800 text-left text-xs uppercase tracking-wider text-white/50">
                <tr>
                  <th className="px-4 py-3">Employé</th>
                  <th className="px-4 py-3">Cible</th>
                  <th className="px-4 py-3">Début</th>
                  <th className="px-4 py-3">Fin</th>
                  <th className="px-4 py-3 text-right">Heures</th>
                  <th className="px-4 py-3">Tâche</th>
                  <th className="px-4 py-3 text-center">Approuvé</th>
                  <th className="px-4 py-3"></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-brand-800">
                {visible.map((p) => {
                  const emp = empById.get(p.employe_id);
                  const proj = p.project_id ? projById.get(p.project_id) : null;
                  const prospect = p.contact_request_id
                    ? prospById.get(p.contact_request_id)
                    : null;
                  const target = proj
                    ? `Projet — ${proj.name}`
                    : prospect
                    ? `Prospect — ${prospect.name}`
                    : "Administration";
                  return (
                    <tr
                      key={p.id}
                      onClick={() => setModal(p)}
                      className="cursor-pointer hover:bg-brand-800/50"
                    >
                      <td className="px-4 py-3 font-semibold text-white">
                        {emp?.full_name || `#${p.employe_id}`}
                      </td>
                      <td className="px-4 py-3 text-white/70">{target}</td>
                      <td className="px-4 py-3 text-white/70">
                        {fmtDateTime(p.started_at)}
                      </td>
                      <td className="px-4 py-3 text-white/70">
                        {p.ended_at ? fmtDateTime(p.ended_at) : (
                          <span className="text-accent-500">EN COURS</span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-right font-semibold text-white">
                        {p.hours != null ? fmtHm(Number(p.hours)) : "—"}
                      </td>
                      <td className="px-4 py-3 text-xs text-white/60">
                        <span className="line-clamp-1">{p.task || "—"}</span>
                      </td>
                      <td className="px-4 py-3 text-center">
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            toggleApprove(p);
                          }}
                          className={`rounded-md px-2 py-1 text-[10px] font-semibold ${
                            p.approved
                              ? "bg-emerald-500/20 text-emerald-300 hover:bg-emerald-500/30"
                              : "bg-white/5 text-white/50 hover:bg-white/10"
                          }`}
                        >
                          {p.approved ? (
                            <span className="inline-flex items-center gap-1">
                              <Check className="h-3 w-3" />
                              Approuvé
                            </span>
                          ) : (
                            "À approuver"
                          )}
                        </button>
                      </td>
                      <td className="px-4 py-3 text-right">
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            remove(p);
                          }}
                          className="text-rose-400 hover:text-rose-300"
                          aria-label="Supprimer"
                        >
                          <Trash2 className="h-4 w-4" />
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {modal ? (
        <PunchModal
          seed={modal}
          employes={employes}
          projects={projects}
          prospects={prospects}
          onClose={() => setModal(null)}
          onSaved={(p) => {
            upsert(p);
            setModal(null);
          }}
        />
      ) : null}
    </>
  );
}

function PunchModal({
  seed,
  employes,
  projects,
  prospects,
  onClose,
  onSaved
}: {
  seed: Punch | { fresh: true };
  employes: Employe[];
  projects: Project[];
  prospects: Prospect[];
  onClose: () => void;
  onSaved: (p: Punch) => void;
}) {
  const existing = "id" in seed ? seed : null;
  const [employeId, setEmployeId] = useState(
    existing ? String(existing.employe_id) : ""
  );
  const [target, setTarget] = useState(
    existing
      ? existing.project_id
        ? `p-${existing.project_id}`
        : existing.contact_request_id
        ? `c-${existing.contact_request_id}`
        : ""
      : ""
  );
  const [startedAt, setStartedAt] = useState(
    existing ? isoLocal(new Date(existing.started_at)) : isoLocal(new Date())
  );
  const [endedAt, setEndedAt] = useState(
    existing?.ended_at ? isoLocal(new Date(existing.ended_at)) : ""
  );
  const [task, setTask] = useState(existing?.task || "");
  const [notes, setNotes] = useState(existing?.notes || "");
  const [approved, setApproved] = useState(existing?.approved ?? false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const computedHours = useMemo(() => {
    if (!startedAt || !endedAt) return null;
    const ms =
      new Date(endedAt).getTime() - new Date(startedAt).getTime();
    if (ms < 0) return null;
    return Math.round((ms / 3600_000) * 100) / 100;
  }, [startedAt, endedAt]);

  async function save(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!employeId) {
      setError("Choisis un employé.");
      return;
    }
    if (!startedAt) {
      setError("Date de début requise.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const payload: Record<string, unknown> = {
        employe_id: Number(employeId),
        started_at: new Date(startedAt).toISOString(),
        ended_at: endedAt ? new Date(endedAt).toISOString() : null,
        hours: computedHours,
        task: task.trim() || null,
        notes: notes.trim() || null,
        approved,
        project_id: target.startsWith("p-") ? Number(target.slice(2)) : null,
        contact_request_id: target.startsWith("c-")
          ? Number(target.slice(2))
          : null
      };

      const res = await authedFetch(
        existing ? `/api/v1/punch/${existing.id}` : "/api/v1/punch",
        {
          method: existing ? "PATCH" : "POST",
          body: JSON.stringify(payload)
        }
      );
      if (!res.ok) {
        const txt = await res.text();
        throw new Error(txt.slice(0, 240) || `http_${res.status}`);
      }
      onSaved((await res.json()) as Punch);
    } catch (err) {
      setError((err as Error).message);
      setBusy(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/70 p-4"
      onClick={() => (!busy ? onClose() : null)}
    >
      <form
        onSubmit={save}
        onClick={(e) => e.stopPropagation()}
        className="mt-10 w-full max-w-xl rounded-2xl border border-brand-800 bg-brand-950 p-6 shadow-2xl"
      >
        <h3 className="text-lg font-bold text-white">
          {existing ? "Modifier le punch" : "Nouveau punch (saisie manuelle)"}
        </h3>
        <p className="mt-1 text-xs text-white/60">
          Pour un employé qui a oublié de pointer ou un ajustement rétro.
        </p>

        <div className="mt-5 space-y-4">
          <div>
            <label htmlFor="p_emp" className="label">
              Employé <span className="text-rose-400">*</span>
            </label>
            <select
              id="p_emp"
              value={employeId}
              onChange={(e) => setEmployeId(e.target.value)}
              required
              className="input"
            >
              <option value="">— Sélectionner —</option>
              {employes.map((e) => (
                <option key={e.id} value={String(e.id)}>
                  {e.full_name}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label htmlFor="p_target" className="label">
              Projet ou prospect
            </label>
            <select
              id="p_target"
              value={target}
              onChange={(e) => setTarget(e.target.value)}
              className="input"
            >
              <option value="">— Administration —</option>
              {projects.length > 0 ? (
                <optgroup label="Projets">
                  {projects.map((p) => (
                    <option key={`p-${p.id}`} value={`p-${p.id}`}>
                      {projectLabel(p)}
                    </option>
                  ))}
                </optgroup>
              ) : null}
              {prospects.length > 0 ? (
                <optgroup label="Prospects">
                  {prospects.map((c) => (
                    <option key={`c-${c.id}`} value={`c-${c.id}`}>
                      {c.name}
                    </option>
                  ))}
                </optgroup>
              ) : null}
            </select>
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <label htmlFor="p_start" className="label">
                Début <span className="text-rose-400">*</span>
              </label>
              <input
                id="p_start"
                type="datetime-local"
                required
                value={startedAt}
                onChange={(e) => setStartedAt(e.target.value)}
                className="input"
              />
            </div>
            <div>
              <label htmlFor="p_end" className="label">Fin</label>
              <input
                id="p_end"
                type="datetime-local"
                value={endedAt}
                onChange={(e) => setEndedAt(e.target.value)}
                className="input"
              />
            </div>
          </div>

          <div className="rounded-md bg-brand-900 px-3 py-2 text-sm">
            <span className="text-white/50">Heures calculées : </span>
            <span className="font-semibold text-white">
              {computedHours != null ? fmtHm(computedHours) : "—"}
            </span>
          </div>

          {existing?.geolocation ? (
            <GeolocationDisplay raw={existing.geolocation} />
          ) : null}

          <div>
            <label htmlFor="p_task" className="label">Tâche</label>
            <input
              id="p_task"
              type="text"
              value={task}
              onChange={(e) => setTask(e.target.value)}
              placeholder="Ex. Démolition cuisine"
              className="input"
            />
          </div>

          <div>
            <label htmlFor="p_notes" className="label">Notes</label>
            <textarea
              id="p_notes"
              rows={2}
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              className="input"
            />
          </div>

          <label className="flex items-center gap-2 text-sm text-white/80">
            <input
              type="checkbox"
              checked={approved}
              onChange={(e) => setApproved(e.target.checked)}
            />
            Approuver ce punch pour la paie
          </label>
        </div>

        {error ? (
          <p className="mt-3 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
            {error}
          </p>
        ) : null}

        <div className="mt-6 flex items-center justify-end gap-3">
          <button
            type="button"
            onClick={onClose}
            disabled={busy}
            className="btn-secondary text-sm"
          >
            Annuler
          </button>
          <button
            type="submit"
            disabled={busy}
            className="btn-accent text-sm disabled:opacity-60"
          >
            {busy ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" /> Sauvegarde…
              </>
            ) : existing ? (
              "Enregistrer"
            ) : (
              "Créer le punch"
            )}
          </button>
        </div>
      </form>
    </div>
  );
}


// ---------------------------------------------------------------------------
// GeolocationDisplay — parse "lat,lng[|lat,lng]" + reverse-geocode via Photon
// ---------------------------------------------------------------------------

function GeolocationDisplay({ raw }: { raw: string }) {
  const parts = raw.split("|");
  const start = parseLatLng(parts[0]);
  const end = parts.length > 1 ? parseLatLng(parts[1]) : null;
  if (!start) return null;
  return (
    <div className="rounded-md border border-brand-800 bg-brand-900 px-3 py-2 text-sm">
      <p className="text-xs uppercase tracking-wider text-white/50">
        📍 Lieu du punch
      </p>
      <div className="mt-1 space-y-2">
        <GeoLine label="Début" geo={start} />
        {end ? <GeoLine label="Fin" geo={end} /> : null}
      </div>
    </div>
  );
}

function GeoLine({
  label,
  geo
}: {
  label: string;
  geo: { lat: number; lng: number };
}) {
  const [address, setAddress] = useState<string | null>(null);
  const [loadingAddr, setLoadingAddr] = useState(true);

  useEffect(() => {
    let cancelled = false;
    async function reverse() {
      try {
        const res = await fetch(
          `https://photon.komoot.io/reverse?lon=${geo.lng}&lat=${geo.lat}&lang=fr`
        );
        if (!res.ok) throw new Error();
        const data = (await res.json()) as {
          features?: Array<{
            properties?: {
              housenumber?: string;
              street?: string;
              city?: string;
              state?: string;
              postcode?: string;
              name?: string;
            };
          }>;
        };
        const props = data.features?.[0]?.properties;
        if (!props) {
          if (!cancelled) setAddress(null);
          return;
        }
        const line1 = [props.housenumber, props.street]
          .filter(Boolean)
          .join(" ");
        const line2 = [props.city, props.state, props.postcode]
          .filter(Boolean)
          .join(", ");
        const formatted =
          [line1, line2].filter(Boolean).join(" · ") ||
          props.name ||
          null;
        if (!cancelled) setAddress(formatted);
      } catch {
        if (!cancelled) setAddress(null);
      } finally {
        if (!cancelled) setLoadingAddr(false);
      }
    }
    void reverse();
    return () => {
      cancelled = true;
    };
  }, [geo.lat, geo.lng]);

  const mapsUrl = `https://www.google.com/maps?q=${geo.lat},${geo.lng}`;
  return (
    <div className="text-xs">
      <div className="flex items-baseline gap-2">
        <span className="w-12 shrink-0 text-white/50">{label} :</span>
        <div className="min-w-0 flex-1">
          {loadingAddr ? (
            <span className="text-white/40">Recherche de l&apos;adresse…</span>
          ) : address ? (
            <a
              href={mapsUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="text-white hover:text-accent-300 hover:underline"
              title="Ouvrir dans Google Maps"
            >
              {address}{" "}
              <span className="text-[10px] text-accent-400">↗ Maps</span>
            </a>
          ) : (
            <a
              href={mapsUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="text-accent-300 hover:underline"
            >
              {geo.lat.toFixed(5)}, {geo.lng.toFixed(5)}{" "}
              <span className="text-[10px]">↗ Maps</span>
            </a>
          )}
          <p className="text-[10px] text-white/40">
            <span className="font-mono">
              {geo.lat.toFixed(5)}, {geo.lng.toFixed(5)}
            </span>
          </p>
        </div>
      </div>
    </div>
  );
}

function parseLatLng(s: string): { lat: number; lng: number } | null {
  if (!s) return null;
  const [latStr, lngStr] = s.split(",");
  const lat = Number(latStr);
  const lng = Number(lngStr);
  if (!Number.isFinite(lat) || !Number.isFinite(lng)) return null;
  return { lat, lng };
}


// ---------------------------------------------------------------------------
// MonthCalendar — grille 6×7 lun→dim. Chaque case liste les employés
// qui ont pointé ce jour-là avec leur cumul d'heures.
//   - Clic sur le numéro du jour (zone vide ou en-tête de case)
//     → filtre la liste sur ce jour seulement.
//   - Clic sur une ligne employé → ouvre le punch (modale d'édition).
//     Si l'employé a plusieurs punches le même jour, on ouvre le
//     plus tôt — l'utilisateur peut filtrer pour voir les autres.
// ---------------------------------------------------------------------------

type CalendarEntry = {
  employeId: number;
  name: string;
  hours: number;
  punches: Punch[];
};

function MonthCalendar({
  monthStart,
  entriesByDay,
  selectedDay,
  onSelectDay,
  onSelectPunch
}: {
  monthStart: Date;
  entriesByDay: Map<string, CalendarEntry[]>;
  selectedDay: Date | null;
  onSelectDay: (d: Date) => void;
  onSelectPunch: (p: Punch) => void;
}) {
  const calStart = calendarStartOf(monthStart);
  const today = new Date();
  today.setHours(0, 0, 0, 0);

  // 6 rangées × 7 colonnes = 42 cases
  const cells: Date[] = [];
  for (let i = 0; i < 42; i++) {
    const d = new Date(calStart);
    d.setDate(d.getDate() + i);
    cells.push(d);
  }

  const dayLabels = ["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"];

  return (
    <div className="rounded-xl border border-brand-800 bg-brand-900 p-3">
      <div className="grid grid-cols-7 gap-1">
        {dayLabels.map((l) => (
          <div
            key={l}
            className="px-2 py-1 text-center text-[10px] font-semibold uppercase tracking-wider text-white/40"
          >
            {l}
          </div>
        ))}
        {cells.map((d) => {
          const inMonth = d.getMonth() === monthStart.getMonth();
          const key = shortISO(d);
          const entries = entriesByDay.get(key) || [];
          const dayTotal = entries.reduce((s, e) => s + e.hours, 0);
          const isToday = sameDay(d, today);
          const isSelected = selectedDay && sameDay(d, selectedDay);
          return (
            <div
              key={key}
              className={`flex min-h-[110px] flex-col rounded-md border text-left transition ${
                isSelected
                  ? "border-accent-500 bg-accent-500/10"
                  : isToday
                  ? "border-accent-500/40 bg-brand-950"
                  : "border-brand-800 bg-brand-950/60"
              } ${inMonth ? "" : "opacity-30"}`}
            >
              <button
                type="button"
                onClick={() => onSelectDay(d)}
                className="flex items-center justify-between border-b border-brand-800/60 px-2 py-1.5 transition hover:bg-brand-800/40"
                title="Filtrer la liste sur cette journée"
              >
                <span
                  className={`text-xs ${
                    isToday
                      ? "font-bold text-accent-300"
                      : "font-semibold text-white/70"
                  }`}
                >
                  {d.getDate()}
                </span>
                {dayTotal > 0 ? (
                  <span className="text-[10px] font-bold text-emerald-300">
                    {fmtHm(dayTotal)}
                  </span>
                ) : null}
              </button>
              <div className="flex-1 space-y-0.5 overflow-hidden p-1">
                {entries.length === 0 ? (
                  <span className="block px-1 text-[10px] text-white/20">
                    —
                  </span>
                ) : (
                  entries.slice(0, 4).map((e) => {
                    const firstPunch = e.punches
                      .slice()
                      .sort(
                        (a, b) =>
                          new Date(a.started_at).getTime() -
                          new Date(b.started_at).getTime()
                      )[0];
                    return (
                      <button
                        key={`${key}-${e.employeId}`}
                        type="button"
                        onClick={(ev) => {
                          ev.stopPropagation();
                          if (firstPunch) onSelectPunch(firstPunch);
                        }}
                        className="flex w-full items-center justify-between gap-1 rounded px-1.5 py-0.5 text-left transition hover:bg-accent-500/15"
                        title={`Ouvrir le punch de ${e.name}`}
                      >
                        <span className="truncate text-[10px] font-medium text-white">
                          {e.name.split(" ")[0]}
                        </span>
                        <span className="flex-shrink-0 text-[10px] font-semibold text-emerald-300">
                          {fmtHm(e.hours)}
                        </span>
                      </button>
                    );
                  })
                )}
                {entries.length > 4 ? (
                  <button
                    type="button"
                    onClick={(ev) => {
                      ev.stopPropagation();
                      onSelectDay(d);
                    }}
                    className="block w-full px-1.5 py-0.5 text-left text-[10px] text-white/50 hover:text-accent-300"
                  >
                    +{entries.length - 4} autres…
                  </button>
                ) : null}
              </div>
            </div>
          );
        })}
      </div>
      <p className="mt-2 text-[10px] text-white/40">
        Clique le numéro de la journée pour filtrer la liste, ou un
        nom pour ouvrir le punch correspondant.
      </p>
    </div>
  );
}
