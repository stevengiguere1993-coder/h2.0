"use client";

import { useEffect, useMemo, useState } from "react";
import {
  Calendar as CalendarIcon,
  ChevronLeft,
  ChevronRight,
  Loader2,
  Plus,
  Trash2
} from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { AddressInput } from "@/components/address-input";
import { useAppLayout } from "../layout";
import { authedFetch } from "@/lib/auth";

type AgendaEvent = {
  id: number;
  title: string;
  description: string | null;
  location: string | null;
  start_at: string;
  end_at: string | null;
  all_day: boolean;
  project_id: number | null;
  assignee_id: number | null;
  event_type: string;
  created_at: string;
};

type Project = { id: number; name: string; status: string };
type Employe = { id: number; full_name: string };

const TYPE_LABELS: Record<string, string> = {
  chantier: "Chantier",
  visite: "Visite",
  reunion: "Réunion",
  livraison: "Livraison",
  autre: "Autre"
};

const TYPE_CLASS: Record<string, string> = {
  chantier: "bg-accent-500/20 text-accent-300 border-accent-500/40",
  visite: "bg-blue-500/20 text-blue-300 border-blue-500/40",
  reunion: "bg-violet-500/20 text-violet-300 border-violet-500/40",
  livraison: "bg-emerald-500/20 text-emerald-300 border-emerald-500/40",
  autre: "bg-white/10 text-white/70 border-white/20"
};

const WEEKDAYS = ["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"];
const MONTHS = [
  "Janvier",
  "Février",
  "Mars",
  "Avril",
  "Mai",
  "Juin",
  "Juillet",
  "Août",
  "Septembre",
  "Octobre",
  "Novembre",
  "Décembre"
];

function monthLabel(d: Date): string {
  return `${MONTHS[d.getMonth()]} ${d.getFullYear()}`;
}

function isoLocal(d: Date): string {
  // Format YYYY-MM-DDTHH:MM for <input type="datetime-local">
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(
    d.getHours()
  )}:${pad(d.getMinutes())}`;
}

function sameDay(a: Date, b: Date): boolean {
  return (
    a.getFullYear() === b.getFullYear() &&
    a.getMonth() === b.getMonth() &&
    a.getDate() === b.getDate()
  );
}

function buildMonthGrid(ref: Date): Date[] {
  // Returns 42 dates (6 weeks × 7 days) covering the month ref is in.
  // Monday-first week.
  const first = new Date(ref.getFullYear(), ref.getMonth(), 1);
  const firstWeekday = (first.getDay() + 6) % 7; // Mon=0 ... Sun=6
  const start = new Date(first);
  start.setDate(1 - firstWeekday);
  return Array.from({ length: 42 }, (_, i) => {
    const d = new Date(start);
    d.setDate(start.getDate() + i);
    return d;
  });
}

function fmtTime(iso: string): string {
  const d = new Date(iso);
  return `${String(d.getHours()).padStart(2, "0")}:${String(
    d.getMinutes()
  ).padStart(2, "0")}`;
}

export default function AgendaPage() {
  const { onOpenSidebar } = useAppLayout();
  const [ref, setRef] = useState(() => new Date());
  const [view, setView] = useState<"month" | "list">("month");

  const [events, setEvents] = useState<AgendaEvent[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [employes, setEmployes] = useState<Employe[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Filters
  const [fType, setFType] = useState("");
  const [fProject, setFProject] = useState("");
  const [fAssignee, setFAssignee] = useState("");

  // Modal state
  const [modal, setModal] = useState<AgendaEvent | { date: Date } | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const [evRes, prRes, empRes] = await Promise.all([
          authedFetch("/api/v1/agenda?limit=500"),
          authedFetch("/api/v1/projects?limit=200"),
          authedFetch("/api/v1/employes?limit=200")
        ]);
        if (!evRes.ok) throw new Error(`http_${evRes.status}`);
        const evs = (await evRes.json()) as AgendaEvent[];
        const prs = prRes.ok ? ((await prRes.json()) as Project[]) : [];
        const emps = empRes.ok ? ((await empRes.json()) as Employe[]) : [];
        if (!cancelled) {
          setEvents(evs);
          setProjects(prs);
          setEmployes(emps);
        }
      } catch {
        if (!cancelled) setError("Impossible de charger l'agenda.");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, []);

  const filteredEvents = useMemo(() => {
    return events.filter((e) => {
      if (fType && e.event_type !== fType) return false;
      if (fProject && String(e.project_id || "") !== fProject) return false;
      if (fAssignee && String(e.assignee_id || "") !== fAssignee) return false;
      return true;
    });
  }, [events, fType, fProject, fAssignee]);

  const grid = useMemo(() => buildMonthGrid(ref), [ref]);

  const eventsByDay = useMemo(() => {
    const map = new Map<string, AgendaEvent[]>();
    for (const e of filteredEvents) {
      const d = new Date(e.start_at);
      const key = d.toDateString();
      const arr = map.get(key) || [];
      arr.push(e);
      map.set(key, arr);
    }
    // Sort each day by time
    for (const arr of map.values()) {
      arr.sort(
        (a, b) => new Date(a.start_at).getTime() - new Date(b.start_at).getTime()
      );
    }
    return map;
  }, [filteredEvents]);

  function upsertEvent(saved: AgendaEvent) {
    setEvents((xs) => {
      const idx = xs.findIndex((x) => x.id === saved.id);
      if (idx === -1) return [...xs, saved];
      const next = xs.slice();
      next[idx] = saved;
      return next;
    });
  }

  function removeEvent(id: number) {
    setEvents((xs) => xs.filter((x) => x.id !== id));
  }

  return (
    <>
      <AppTopbar
        breadcrumbs={[{ label: "Construction", href: "/app" }, { label: "Agenda" }]}
        onOpenSidebar={onOpenSidebar}
        rightSlot={
          <button
            type="button"
            onClick={() => setModal({ date: new Date() })}
            className="btn-accent text-sm"
          >
            <Plus className="mr-1.5 h-4 w-4" />
            Nouvel événement
          </button>
        }
      />

      <div className="p-4 lg:p-6">
        {error ? (
          <p className="mb-4 rounded-lg border border-rose-500/40 bg-rose-500/10 px-4 py-2 text-sm text-rose-300">
            {error}
          </p>
        ) : null}

        {/* Controls */}
        <div className="mb-4 flex flex-wrap items-center gap-3">
          <div className="flex items-center gap-1 rounded-lg border border-brand-800 bg-brand-900 p-1">
            <button
              type="button"
              onClick={() => {
                const d = new Date(ref);
                d.setMonth(d.getMonth() - 1);
                setRef(d);
              }}
              className="rounded-md p-1.5 text-white/70 hover:bg-brand-800 hover:text-white"
              aria-label="Mois précédent"
            >
              <ChevronLeft className="h-4 w-4" />
            </button>
            <span className="min-w-[140px] px-2 text-center text-sm font-semibold text-white">
              {monthLabel(ref)}
            </span>
            <button
              type="button"
              onClick={() => {
                const d = new Date(ref);
                d.setMonth(d.getMonth() + 1);
                setRef(d);
              }}
              className="rounded-md p-1.5 text-white/70 hover:bg-brand-800 hover:text-white"
              aria-label="Mois suivant"
            >
              <ChevronRight className="h-4 w-4" />
            </button>
          </div>

          <button
            type="button"
            onClick={() => setRef(new Date())}
            className="btn-secondary text-xs"
          >
            Aujourd&apos;hui
          </button>

          <div className="ml-auto flex flex-wrap items-center gap-2">
            <select
              value={view}
              onChange={(e) => setView(e.target.value as "month" | "list")}
              className="input w-28"
            >
              <option value="month">Mois</option>
              <option value="list">Liste</option>
            </select>
            <select
              value={fType}
              onChange={(e) => setFType(e.target.value)}
              className="input w-36"
            >
              <option value="">Tous les types</option>
              {Object.entries(TYPE_LABELS).map(([k, v]) => (
                <option key={k} value={k}>
                  {v}
                </option>
              ))}
            </select>
            <select
              value={fProject}
              onChange={(e) => setFProject(e.target.value)}
              className="input w-40"
            >
              <option value="">Tous les projets</option>
              {projects.map((p) => (
                <option key={p.id} value={String(p.id)}>
                  {p.name}
                </option>
              ))}
            </select>
            <select
              value={fAssignee}
              onChange={(e) => setFAssignee(e.target.value)}
              className="input w-40"
            >
              <option value="">Toute l&apos;équipe</option>
              {employes.map((e) => (
                <option key={e.id} value={String(e.id)}>
                  {e.full_name}
                </option>
              ))}
            </select>
          </div>
        </div>

        {loading ? (
          <div className="flex min-h-[40vh] items-center justify-center">
            <Loader2 className="h-6 w-6 animate-spin text-accent-500" />
          </div>
        ) : view === "month" ? (
          <MonthView
            grid={grid}
            ref={ref}
            eventsByDay={eventsByDay}
            onDayClick={(d) => setModal({ date: d })}
            onEventClick={(e) => setModal(e)}
          />
        ) : (
          <ListView
            events={filteredEvents}
            onEventClick={(e) => setModal(e)}
          />
        )}
      </div>

      {modal ? (
        <EventModal
          seed={modal}
          projects={projects}
          employes={employes}
          onClose={() => setModal(null)}
          onSaved={(e) => {
            upsertEvent(e);
            setModal(null);
          }}
          onDeleted={(id) => {
            removeEvent(id);
            setModal(null);
          }}
        />
      ) : null}
    </>
  );
}

function MonthView({
  grid,
  ref,
  eventsByDay,
  onDayClick,
  onEventClick
}: {
  grid: Date[];
  ref: Date;
  eventsByDay: Map<string, AgendaEvent[]>;
  onDayClick: (d: Date) => void;
  onEventClick: (e: AgendaEvent) => void;
}) {
  const today = new Date();
  return (
    <div className="overflow-hidden rounded-xl border border-brand-800 bg-brand-900">
      <div className="grid grid-cols-7 border-b border-brand-800 text-xs font-semibold text-white/50">
        {WEEKDAYS.map((w) => (
          <div key={w} className="px-3 py-2 text-center uppercase tracking-wider">
            {w}
          </div>
        ))}
      </div>
      <div className="grid grid-cols-7">
        {grid.map((d, i) => {
          const inMonth = d.getMonth() === ref.getMonth();
          const isToday = sameDay(d, today);
          const dayEvents = eventsByDay.get(d.toDateString()) || [];
          return (
            <div
              key={i}
              onClick={() => {
                const at = new Date(d);
                at.setHours(9, 0, 0, 0);
                onDayClick(at);
              }}
              className={`min-h-[96px] cursor-pointer border-b border-r border-brand-800 p-1.5 transition hover:bg-brand-800/50 ${
                inMonth ? "bg-brand-900" : "bg-brand-950/50"
              }`}
            >
              <div className="flex items-center justify-between">
                <span
                  className={`inline-flex h-6 w-6 items-center justify-center rounded-full text-xs ${
                    isToday
                      ? "bg-accent-500 font-bold text-brand-950"
                      : inMonth
                      ? "text-white/80"
                      : "text-white/30"
                  }`}
                >
                  {d.getDate()}
                </span>
                {dayEvents.length > 3 ? (
                  <span className="text-[10px] text-white/40">
                    +{dayEvents.length - 3}
                  </span>
                ) : null}
              </div>
              <div className="mt-1 space-y-0.5">
                {dayEvents.slice(0, 3).map((e) => (
                  <button
                    key={e.id}
                    type="button"
                    onClick={(ev) => {
                      ev.stopPropagation();
                      onEventClick(e);
                    }}
                    className={`block w-full truncate rounded border px-1 py-0.5 text-left text-[10px] font-medium ${
                      TYPE_CLASS[e.event_type] || TYPE_CLASS.autre
                    }`}
                  >
                    {!e.all_day ? `${fmtTime(e.start_at)} ` : ""}
                    {e.title}
                  </button>
                ))}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function ListView({
  events,
  onEventClick
}: {
  events: AgendaEvent[];
  onEventClick: (e: AgendaEvent) => void;
}) {
  if (events.length === 0) {
    return (
      <div className="mx-auto mt-16 max-w-md rounded-2xl border border-dashed border-brand-800 bg-brand-900/40 p-10 text-center">
        <CalendarIcon className="mx-auto h-10 w-10 text-accent-500" />
        <h2 className="mt-4 text-lg font-semibold text-white">Aucun événement</h2>
        <p className="mt-2 text-sm text-white/60">
          Ajoute un événement avec le bouton en haut à droite.
        </p>
      </div>
    );
  }
  const sorted = events
    .slice()
    .sort(
      (a, b) => new Date(a.start_at).getTime() - new Date(b.start_at).getTime()
    );
  // Group by date (YYYY-MM-DD)
  const groups = new Map<string, AgendaEvent[]>();
  for (const e of sorted) {
    const key = new Date(e.start_at).toDateString();
    const arr = groups.get(key) || [];
    arr.push(e);
    groups.set(key, arr);
  }
  return (
    <div className="space-y-5">
      {Array.from(groups.entries()).map(([key, list]) => (
        <div key={key} className="rounded-xl border border-brand-800 bg-brand-900">
          <div className="border-b border-brand-800 px-4 py-2 text-xs font-semibold uppercase tracking-wider text-accent-500">
            {new Date(key).toLocaleDateString("fr-CA", {
              weekday: "long",
              day: "numeric",
              month: "long"
            })}
          </div>
          <ul className="divide-y divide-brand-800">
            {list.map((e) => (
              <li
                key={e.id}
                onClick={() => onEventClick(e)}
                className="flex cursor-pointer items-center justify-between gap-3 px-4 py-3 hover:bg-brand-800/50"
              >
                <div className="min-w-0">
                  <p className="truncate text-sm font-semibold text-white">
                    {e.title}
                  </p>
                  <p className="truncate text-xs text-white/50">
                    {e.all_day
                      ? "Toute la journée"
                      : `${fmtTime(e.start_at)}${
                          e.end_at ? ` – ${fmtTime(e.end_at)}` : ""
                        }`}
                    {e.location ? ` · ${e.location}` : ""}
                  </p>
                </div>
                <span
                  className={`shrink-0 rounded-md border px-2 py-0.5 text-[10px] font-semibold ${
                    TYPE_CLASS[e.event_type] || TYPE_CLASS.autre
                  }`}
                >
                  {TYPE_LABELS[e.event_type] || e.event_type}
                </span>
              </li>
            ))}
          </ul>
        </div>
      ))}
    </div>
  );
}

function EventModal({
  seed,
  projects,
  employes,
  onClose,
  onSaved,
  onDeleted
}: {
  seed: AgendaEvent | { date: Date };
  projects: Project[];
  employes: Employe[];
  onClose: () => void;
  onSaved: (e: AgendaEvent) => void;
  onDeleted: (id: number) => void;
}) {
  const existing = "id" in seed ? (seed as AgendaEvent) : null;
  const initialStart = existing
    ? isoLocal(new Date(existing.start_at))
    : isoLocal(seed.date);
  const initialEnd = existing?.end_at ? isoLocal(new Date(existing.end_at)) : "";

  const [title, setTitle] = useState(existing?.title || "");
  const [description, setDescription] = useState(existing?.description || "");
  const [location, setLocation] = useState(existing?.location || "");
  const [startAt, setStartAt] = useState(initialStart);
  const [endAt, setEndAt] = useState(initialEnd);
  const [allDay, setAllDay] = useState(existing?.all_day ?? false);
  const [type, setType] = useState(existing?.event_type || "chantier");
  const [projectId, setProjectId] = useState(
    existing?.project_id ? String(existing.project_id) : ""
  );
  const [assigneeId, setAssigneeId] = useState(
    existing?.assignee_id ? String(existing.assignee_id) : ""
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function save(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!title.trim()) {
      setError("Le titre est requis.");
      return;
    }
    if (!startAt) {
      setError("La date de début est requise.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const payload: Record<string, unknown> = {
        title: title.trim(),
        description: description.trim() || null,
        location: location.trim() || null,
        start_at: new Date(startAt).toISOString(),
        end_at: endAt ? new Date(endAt).toISOString() : null,
        all_day: allDay,
        event_type: type,
        project_id: projectId ? Number(projectId) : null,
        assignee_id: assigneeId ? Number(assigneeId) : null
      };
      const res = await authedFetch(
        existing
          ? `/api/v1/agenda/${existing.id}`
          : "/api/v1/agenda",
        {
          method: existing ? "PATCH" : "POST",
          body: JSON.stringify(payload)
        }
      );
      if (!res.ok) {
        const txt = await res.text();
        throw new Error(txt.slice(0, 240) || `http_${res.status}`);
      }
      const saved = (await res.json()) as AgendaEvent;
      onSaved(saved);
    } catch (err) {
      setError(`Sauvegarde échouée : ${(err as Error).message}`);
      setBusy(false);
    }
  }

  async function remove() {
    if (!existing) return;
    if (!confirm(`Supprimer l'événement « ${existing.title} » ?`)) return;
    setBusy(true);
    try {
      const res = await authedFetch(`/api/v1/agenda/${existing.id}`, {
        method: "DELETE"
      });
      if (!res.ok) throw new Error();
      onDeleted(existing.id);
    } catch {
      setError("Suppression échouée.");
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
          {existing ? "Modifier l'événement" : "Nouvel événement"}
        </h3>

        <div className="mt-5 space-y-4">
          <div>
            <label className="label" htmlFor="ev_title">
              Titre <span className="text-rose-400">*</span>
            </label>
            <input
              id="ev_title"
              type="text"
              required
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              className="input"
              placeholder="Ex. Livraison matériaux Tremblay"
            />
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <label className="label" htmlFor="ev_start">
                Début <span className="text-rose-400">*</span>
              </label>
              <input
                id="ev_start"
                type="datetime-local"
                required
                value={startAt}
                onChange={(e) => setStartAt(e.target.value)}
                className="input"
              />
            </div>
            <div>
              <label className="label" htmlFor="ev_end">
                Fin
              </label>
              <input
                id="ev_end"
                type="datetime-local"
                value={endAt}
                onChange={(e) => setEndAt(e.target.value)}
                className="input"
              />
            </div>
          </div>

          <label className="flex items-center gap-2 text-sm text-white/80">
            <input
              type="checkbox"
              checked={allDay}
              onChange={(e) => setAllDay(e.target.checked)}
            />
            Toute la journée
          </label>

          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <label className="label" htmlFor="ev_type">
                Type
              </label>
              <select
                id="ev_type"
                value={type}
                onChange={(e) => setType(e.target.value)}
                className="input"
              >
                {Object.entries(TYPE_LABELS).map(([k, v]) => (
                  <option key={k} value={k}>
                    {v}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="label" htmlFor="ev_project">
                Projet
              </label>
              <select
                id="ev_project"
                value={projectId}
                onChange={(e) => setProjectId(e.target.value)}
                className="input"
              >
                <option value="">—</option>
                {projects.map((p) => (
                  <option key={p.id} value={String(p.id)}>
                    {p.name}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <div>
            <label className="label" htmlFor="ev_assignee">
              Assigné à
            </label>
            <select
              id="ev_assignee"
              value={assigneeId}
              onChange={(e) => setAssigneeId(e.target.value)}
              className="input"
            >
              <option value="">—</option>
              {employes.map((e) => (
                <option key={e.id} value={String(e.id)}>
                  {e.full_name}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label className="label" htmlFor="ev_location">
              Lieu
            </label>
            <AddressInput
              id="ev_location"
              value={location}
              onChange={setLocation}
              placeholder="Adresse du chantier, bureau…"
            />
          </div>

          <div>
            <label className="label" htmlFor="ev_desc">
              Description
            </label>
            <textarea
              id="ev_desc"
              rows={3}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              className="input"
              placeholder="Notes, consignes, personnes invitées…"
            />
          </div>
        </div>

        {error ? (
          <p className="mt-3 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
            {error}
          </p>
        ) : null}

        <div className="mt-6 flex items-center justify-between gap-3">
          {existing ? (
            <button
              type="button"
              onClick={remove}
              disabled={busy}
              className="inline-flex items-center gap-2 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2.5 text-sm font-medium text-rose-300 hover:bg-rose-500/20"
            >
              <Trash2 className="h-4 w-4" />
              Supprimer
            </button>
          ) : (
            <span />
          )}
          <div className="flex items-center gap-3">
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
              disabled={busy || !title.trim() || !startAt}
              className="btn-accent text-sm disabled:opacity-60"
            >
              {busy ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  Sauvegarde…
                </>
              ) : existing ? (
                "Enregistrer"
              ) : (
                "Créer"
              )}
            </button>
          </div>
        </div>
      </form>
    </div>
  );
}
