"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Briefcase,
  Calendar,
  CheckSquare,
  Loader2,
  Plus,
  Search,
  UserCircle,
  Users
} from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { Link } from "@/i18n/navigation";
import { useAppLayout } from "../layout";
import { authedFetch } from "@/lib/auth";

type Employe = {
  id: number;
  full_name: string;
  email: string | null;
  role: string | null;
  active: boolean;
};

type Project = {
  id: number;
  name: string;
  status: string;
  start_date: string | null;
  end_date: string | null;
};

type Phase = {
  id: number;
  project_id: number;
  name: string;
  position: number;
  start_date: string | null;
  duration_days: number | null;
  assignee_employe_id: number | null;
  assignee_sous_traitant_id: number | null;
  assignee_employe_ids?: number[];
  assignee_sous_traitant_ids?: number[];
};

type AgendaEvent = {
  id: number;
  title: string;
  location: string | null;
  start_at: string;
  end_at: string | null;
  project_id: number | null;
  assignee_id: number | null;
  event_type: string;
};

type ProjectTask = {
  id: number;
  project_id: number;
  phase_id: number | null;
  title: string;
  description: string | null;
  due_date: string | null;
  done: boolean;
  assignee_id: number | null;
  assignee_employe_ids?: number[];
};

function fmtDate(s: string | null): string {
  if (!s) return "";
  try {
    return new Date(s).toLocaleDateString("fr-CA", {
      day: "2-digit",
      month: "short"
    });
  } catch {
    return s;
  }
}

function addDays(iso: string, days: number): string {
  const d = new Date(iso);
  d.setDate(d.getDate() + days);
  return d.toISOString().slice(0, 10);
}

export default function AssignationsPage() {
  const { onOpenSidebar } = useAppLayout();
  const [employes, setEmployes] = useState<Employe[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [phases, setPhases] = useState<Phase[]>([]);
  const [events, setEvents] = useState<AgendaEvent[]>([]);
  const [tasksByProject, setTasksByProject] = useState<
    Map<number, ProjectTask[]>
  >(new Map());
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [q, setQ] = useState("");
  const [selectedEmpId, setSelectedEmpId] = useState<number | null>(null);
  const [busyPhaseId, setBusyPhaseId] = useState<number | null>(null);
  const [showInactive, setShowInactive] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [empRes, prRes, phRes, evRes] = await Promise.all([
        authedFetch("/api/v1/employes?limit=500&volet=construction"),
        authedFetch("/api/v1/projects?limit=500"),
        authedFetch("/api/v1/phases"),
        authedFetch("/api/v1/agenda?limit=1000")
      ]);
      if (!empRes.ok) throw new Error();
      setEmployes((await empRes.json()) as Employe[]);
      setProjects(prRes.ok ? ((await prRes.json()) as Project[]) : []);
      setPhases(phRes.ok ? ((await phRes.json()) as Phase[]) : []);
      setEvents(evRes.ok ? ((await evRes.json()) as AgendaEvent[]) : []);
    } catch {
      setError("Chargement échoué.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  // Lazy-load tasks per project as needed (on selection of an employee).
  useEffect(() => {
    if (!selectedEmpId) return;
    const projectsToFetch = Array.from(
      new Set(
        phases
          .filter(
            (ph) =>
              (ph.assignee_employe_ids || []).includes(selectedEmpId) ||
              ph.assignee_employe_id === selectedEmpId
          )
          .map((ph) => ph.project_id)
      )
    ).filter((pid) => !tasksByProject.has(pid));
    if (projectsToFetch.length === 0) return;
    Promise.all(
      projectsToFetch.map(async (pid) => {
        const r = await authedFetch(`/api/v1/projects/${pid}/tasks`);
        if (!r.ok) return [pid, [] as ProjectTask[]] as const;
        const rows = (await r.json()) as ProjectTask[];
        return [pid, rows] as const;
      })
    ).then((pairs) => {
      setTasksByProject((prev) => {
        const next = new Map(prev);
        for (const [pid, rows] of pairs) next.set(pid, rows);
        return next;
      });
    });
  }, [selectedEmpId, phases, tasksByProject]);

  const projectById = useMemo(() => {
    const m = new Map<number, Project>();
    for (const p of projects) m.set(p.id, p);
    return m;
  }, [projects]);

  const visibleEmployes = useMemo(() => {
    const s = q.trim().toLowerCase();
    return employes
      .filter((e) => (showInactive ? true : e.active))
      .filter(
        (e) =>
          !s ||
          e.full_name.toLowerCase().includes(s) ||
          (e.email || "").toLowerCase().includes(s)
      )
      .sort((a, b) => a.full_name.localeCompare(b.full_name));
  }, [employes, q, showInactive]);

  const assignmentCount = useCallback(
    (empId: number) => {
      const phasesCount = phases.filter(
        (ph) =>
          (ph.assignee_employe_ids || []).includes(empId) ||
          ph.assignee_employe_id === empId
      ).length;
      const eventsCount = events.filter(
        (ev) => ev.assignee_id === empId
      ).length;
      return phasesCount + eventsCount;
    },
    [phases, events]
  );

  const selectedEmp = useMemo(
    () => employes.find((e) => e.id === selectedEmpId) || null,
    [employes, selectedEmpId]
  );

  const empPhases = useMemo(() => {
    if (!selectedEmpId) return [];
    return phases
      .filter(
        (ph) =>
          (ph.assignee_employe_ids || []).includes(selectedEmpId) ||
          ph.assignee_employe_id === selectedEmpId
      )
      .sort((a, b) =>
        (a.start_date || "9999").localeCompare(b.start_date || "9999")
      );
  }, [phases, selectedEmpId]);

  const empEvents = useMemo(() => {
    if (!selectedEmpId) return [];
    return events
      .filter((ev) => ev.assignee_id === selectedEmpId)
      .sort((a, b) => a.start_at.localeCompare(b.start_at));
  }, [events, selectedEmpId]);

  const empTasks = useMemo(() => {
    if (!selectedEmpId) return [];
    const out: ProjectTask[] = [];
    for (const rows of tasksByProject.values()) {
      for (const t of rows) {
        if (
          t.assignee_id === selectedEmpId ||
          (t.assignee_employe_ids || []).includes(selectedEmpId)
        ) {
          if (!t.done) out.push(t);
        }
      }
    }
    return out.sort((a, b) =>
      (a.due_date || "9999").localeCompare(b.due_date || "9999")
    );
  }, [tasksByProject, selectedEmpId]);

  async function reassignPhase(phase: Phase, newEmployeId: number | null) {
    setBusyPhaseId(phase.id);
    try {
      const currentIds = new Set(
        phase.assignee_employe_ids ||
          (phase.assignee_employe_id ? [phase.assignee_employe_id] : [])
      );
      if (selectedEmpId) currentIds.delete(selectedEmpId);
      if (newEmployeId) currentIds.add(newEmployeId);
      const nextIds = Array.from(currentIds);
      const res = await authedFetch(
        `/api/v1/projects/${phase.project_id}/phases/${phase.id}`,
        {
          method: "PATCH",
          body: JSON.stringify({ assignee_employe_ids: nextIds })
        }
      );
      if (!res.ok) throw new Error();
      const updated = (await res.json()) as Phase;
      setPhases((prev) => prev.map((p) => (p.id === phase.id ? updated : p)));
    } catch {
      setError("Réassignation échouée.");
    } finally {
      setBusyPhaseId(null);
    }
  }

  async function removeFromPhase(phase: Phase) {
    if (!selectedEmpId) return;
    if (
      !window.confirm(
        `Retirer ${selectedEmp?.full_name} de la phase « ${phase.name} » ?`
      )
    )
      return;
    await reassignPhase(phase, null);
  }

  return (
    <>
      <AppTopbar
        breadcrumbs={[
          { label: "Administration", href: "/app" },
          { label: "Assignations" }
        ]}
        onOpenSidebar={onOpenSidebar}
      />

      <div className="p-4 lg:p-6">
        <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
          <div>
            <h1 className="text-2xl font-bold text-white">Assignations</h1>
            <p className="mt-1 text-sm text-white/60">
              Vue d&apos;ensemble par employé. Sélectionne quelqu&apos;un
              pour voir ses phases, tâches et événements — et réassigner
              au besoin.
            </p>
          </div>
        </div>

        {error ? (
          <p className="mb-3 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-300">
            {error}
          </p>
        ) : null}

        {loading ? (
          <div className="flex min-h-[40vh] items-center justify-center">
            <Loader2 className="h-6 w-6 animate-spin text-accent-500" />
          </div>
        ) : (
          <div className="grid gap-4 lg:grid-cols-[320px_1fr]">
            {/* Employee list */}
            <aside className="rounded-xl border border-brand-800 bg-brand-900">
              <div className="border-b border-brand-800 p-3">
                <div className="relative">
                  <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-white/40" />
                  <input
                    type="search"
                    value={q}
                    onChange={(e) => setQ(e.target.value)}
                    placeholder="Rechercher un employé…"
                    className="w-full rounded-md border border-brand-800 bg-brand-950 py-1.5 pl-8 pr-2 text-sm text-white placeholder:text-white/40"
                  />
                </div>
                <label className="mt-2 flex items-center gap-2 text-[11px] text-white/60">
                  <input
                    type="checkbox"
                    checked={showInactive}
                    onChange={(e) => setShowInactive(e.target.checked)}
                    className="rounded border-brand-700"
                  />
                  Afficher les employés inactifs
                </label>
              </div>
              <ul className="max-h-[70vh] overflow-y-auto">
                {visibleEmployes.length === 0 ? (
                  <li className="p-4 text-center text-xs text-white/40">
                    Aucun employé.
                  </li>
                ) : (
                  visibleEmployes.map((emp) => {
                    const count = assignmentCount(emp.id);
                    const selected = emp.id === selectedEmpId;
                    return (
                      <li key={emp.id}>
                        <button
                          type="button"
                          onClick={() => setSelectedEmpId(emp.id)}
                          className={`flex w-full items-center gap-3 border-b border-brand-800/60 px-3 py-2.5 text-left transition ${
                            selected
                              ? "bg-accent-500/10"
                              : "hover:bg-brand-800/40"
                          }`}
                        >
                          <UserCircle
                            className={`h-5 w-5 shrink-0 ${
                              emp.active ? "text-accent-500" : "text-white/30"
                            }`}
                          />
                          <div className="min-w-0 flex-1">
                            <p
                              className={`truncate text-sm ${
                                emp.active ? "text-white" : "text-white/40"
                              } ${selected ? "font-semibold" : ""}`}
                            >
                              {emp.full_name}
                              {!emp.active ? " (inactif)" : ""}
                            </p>
                            <p className="text-[11px] text-white/50">
                              {count} assignation{count !== 1 ? "s" : ""}
                            </p>
                          </div>
                          {count > 0 ? (
                            <span className="rounded-full bg-accent-500/15 px-2 py-0.5 text-[10px] font-bold text-accent-300">
                              {count}
                            </span>
                          ) : null}
                        </button>
                      </li>
                    );
                  })
                )}
              </ul>
            </aside>

            {/* Detail pane */}
            <main className="rounded-xl border border-brand-800 bg-brand-900 p-4 lg:p-5">
              {!selectedEmp ? (
                <div className="flex min-h-[40vh] flex-col items-center justify-center gap-3 text-center text-white/50">
                  <Users className="h-10 w-10 text-white/20" />
                  <p className="text-sm">
                    Sélectionne un employé à gauche pour voir ses
                    assignations.
                  </p>
                </div>
              ) : (
                <div>
                  <header className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                      <h2 className="text-xl font-bold text-white">
                        {selectedEmp.full_name}
                      </h2>
                      <p className="mt-0.5 text-xs text-white/50">
                        {selectedEmp.email || "—"}
                        {selectedEmp.role ? ` · ${selectedEmp.role}` : ""}
                        {!selectedEmp.active ? " · INACTIF" : ""}
                      </p>
                    </div>
                    <Link
                      // eslint-disable-next-line @typescript-eslint/no-explicit-any
                      href={`/app/employes` as any}
                      className="text-xs text-white/60 underline decoration-dotted hover:text-accent-500"
                    >
                      Ouvrir la fiche employé
                    </Link>
                  </header>

                  <section className="mt-5">
                    <h3 className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-white/50">
                      <Briefcase className="h-3.5 w-3.5 text-accent-500" />
                      Phases de chantier ({empPhases.length})
                    </h3>
                    {empPhases.length === 0 ? (
                      <p className="mt-2 text-sm text-white/40">
                        Aucune phase assignée.
                      </p>
                    ) : (
                      <ul className="mt-2 space-y-2">
                        {empPhases.map((ph) => {
                          const proj = projectById.get(ph.project_id);
                          const endISO =
                            ph.start_date && ph.duration_days
                              ? addDays(ph.start_date, ph.duration_days - 1)
                              : null;
                          const coassignees =
                            ph.assignee_employe_ids || [];
                          return (
                            <li
                              key={ph.id}
                              className="rounded-lg border border-brand-800 bg-brand-950 px-3 py-2.5"
                            >
                              <div className="flex items-start justify-between gap-3">
                                <div className="min-w-0">
                                  <Link
                                    // eslint-disable-next-line @typescript-eslint/no-explicit-any
                                    href={`/app/projets/${ph.project_id}` as any}
                                    className="text-sm font-semibold text-white hover:text-accent-400"
                                  >
                                    {proj?.name || `Projet #${ph.project_id}`}
                                  </Link>
                                  <p className="mt-0.5 text-xs text-white/70">
                                    Phase : {ph.name}
                                  </p>
                                  <p className="mt-0.5 text-[11px] text-white/50">
                                    {ph.start_date
                                      ? `${fmtDate(ph.start_date)}${
                                          endISO
                                            ? ` → ${fmtDate(endISO)}`
                                            : ""
                                        }`
                                      : "Non planifiée"}
                                    {ph.duration_days
                                      ? ` · ${ph.duration_days}j`
                                      : ""}
                                  </p>
                                  {coassignees.length > 1 ? (
                                    <p className="mt-0.5 text-[10px] text-white/40">
                                      + {coassignees.length - 1} autre
                                      {coassignees.length - 1 > 1 ? "s" : ""}{" "}
                                      personne
                                      {coassignees.length - 1 > 1 ? "s" : ""}{" "}
                                      sur cette phase
                                    </p>
                                  ) : null}
                                </div>
                                <div className="flex shrink-0 flex-col items-end gap-1">
                                  <select
                                    value=""
                                    disabled={busyPhaseId === ph.id}
                                    onChange={(e) => {
                                      const v = e.target.value;
                                      if (!v) return;
                                      reassignPhase(ph, Number(v));
                                    }}
                                    className="rounded-md border border-brand-800 bg-brand-900 px-2 py-1 text-[11px] text-white disabled:opacity-50"
                                  >
                                    <option value="">
                                      Réassigner à…
                                    </option>
                                    {employes
                                      .filter((e) => e.id !== selectedEmpId)
                                      .map((e) => (
                                        <option key={e.id} value={e.id}>
                                          {e.full_name}
                                        </option>
                                      ))}
                                  </select>
                                  <button
                                    type="button"
                                    onClick={() => removeFromPhase(ph)}
                                    disabled={busyPhaseId === ph.id}
                                    className="text-[10px] text-rose-300 hover:text-rose-200 disabled:opacity-50"
                                  >
                                    Retirer de la phase
                                  </button>
                                </div>
                              </div>
                            </li>
                          );
                        })}
                      </ul>
                    )}
                  </section>

                  <section className="mt-6">
                    <h3 className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-white/50">
                      <CheckSquare className="h-3.5 w-3.5 text-accent-500" />
                      Tâches en cours ({empTasks.length})
                    </h3>
                    {empTasks.length === 0 ? (
                      <p className="mt-2 text-sm text-white/40">
                        Aucune tâche ouverte.
                      </p>
                    ) : (
                      <ul className="mt-2 space-y-1.5">
                        {empTasks.map((t) => {
                          const proj = projectById.get(t.project_id);
                          return (
                            <li
                              key={t.id}
                              className="flex items-start justify-between gap-2 rounded-md border border-brand-800 bg-brand-950 px-3 py-2 text-xs"
                            >
                              <div className="min-w-0">
                                <p className="text-white">{t.title}</p>
                                <p className="mt-0.5 text-[10px] text-white/50">
                                  {proj?.name || `Projet #${t.project_id}`}
                                  {t.due_date
                                    ? ` · échéance ${fmtDate(t.due_date)}`
                                    : ""}
                                </p>
                              </div>
                              <Link
                                // eslint-disable-next-line @typescript-eslint/no-explicit-any
                                href={`/app/projets/${t.project_id}` as any}
                                className="shrink-0 text-[10px] text-white/40 underline decoration-dotted hover:text-accent-400"
                              >
                                Ouvrir
                              </Link>
                            </li>
                          );
                        })}
                      </ul>
                    )}
                  </section>

                  <section className="mt-6">
                    <h3 className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-white/50">
                      <Calendar className="h-3.5 w-3.5 text-accent-500" />
                      Événements agenda ({empEvents.length})
                    </h3>
                    {empEvents.length === 0 ? (
                      <p className="mt-2 text-sm text-white/40">
                        Aucun événement assigné.
                      </p>
                    ) : (
                      <ul className="mt-2 space-y-1.5">
                        {empEvents.slice(0, 20).map((ev) => (
                          <li
                            key={ev.id}
                            className="rounded-md border border-brand-800 bg-brand-950 px-3 py-2 text-xs"
                          >
                            <p className="text-white">{ev.title}</p>
                            <p className="mt-0.5 text-[10px] text-white/50">
                              {fmtDate(ev.start_at)}
                              {ev.location ? ` · ${ev.location}` : ""}
                            </p>
                          </li>
                        ))}
                        {empEvents.length > 20 ? (
                          <li className="text-[10px] text-white/30">
                            + {empEvents.length - 20} événement
                            {empEvents.length - 20 > 1 ? "s" : ""} de plus
                          </li>
                        ) : null}
                      </ul>
                    )}
                  </section>

                  <section className="mt-6 rounded-lg border border-dashed border-brand-800 bg-brand-950/60 p-3">
                    <p className="text-xs text-white/60">
                      <Plus className="mr-1 inline h-3 w-3 text-accent-500" />
                      Besoin de créer une tâche pour cet employé ? Ouvre
                      le projet concerné et ajoute la tâche depuis l&apos;onglet
                      Planification — elle apparaîtra ici automatiquement.
                    </p>
                  </section>
                </div>
              )}
            </main>
          </div>
        )}
      </div>
    </>
  );
}
