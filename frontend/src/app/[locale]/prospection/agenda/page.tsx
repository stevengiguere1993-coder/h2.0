"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Calendar,
  ChevronLeft,
  ChevronRight,
  Clock,
  Loader2,
  Lock,
  Phone,
  Plus,
  X
} from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { authedFetch } from "@/lib/auth";
import { useCurrentUser } from "@/hooks/use-current-user";
import { useProspectionLayout } from "../layout";

type UnifiedEvent = {
  id: number;
  title: string;
  location: string | null;
  description: string | null;
  start_at: string;
  end_at: string | null;
  all_day: boolean;
  scope: "construction" | "prospection";
  event_type: string;
  project_id: number | null;
  lead_id: number | null;
  assignee_id: number | null;
  assignee_user_id: number | null;
  is_opaque: boolean;
};

type LeadMini = {
  id: number;
  name: string;
  address: string | null;
};

type UserMini = {
  id: number;
  email: string;
  full_name: string | null;
};

const DAYS_FR = ["Dim", "Lun", "Mar", "Mer", "Jeu", "Ven", "Sam"];
const MONTHS_FR = [
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

function startOfWeek(d: Date): Date {
  const out = new Date(d);
  const dow = out.getDay();
  out.setDate(out.getDate() - dow);
  out.setHours(0, 0, 0, 0);
  return out;
}

function addDays(d: Date, n: number): Date {
  const out = new Date(d);
  out.setDate(out.getDate() + n);
  return out;
}

function fmtTime(iso: string): string {
  return new Date(iso).toLocaleTimeString("fr-CA", {
    hour: "2-digit",
    minute: "2-digit"
  });
}

function fmtDateLong(d: Date): string {
  return `${d.getDate()} ${MONTHS_FR[d.getMonth()].toLowerCase()} ${d.getFullYear()}`;
}

export default function ProspectionAgendaPage() {
  const { onOpenSidebar } = useProspectionLayout();
  const { user: me } = useCurrentUser();
  const [refDate, setRefDate] = useState<Date>(() => new Date());
  const [events, setEvents] = useState<UnifiedEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState<Date | null>(null);
  const [editing, setEditing] = useState<UnifiedEvent | null>(null);

  // Pour les owner/admin : permettre de consulter l'agenda d'un autre
  // user (mais on commence avec son propre agenda).
  const [users, setUsers] = useState<UserMini[]>([]);
  const [viewUserId, setViewUserId] = useState<number | null>(null);
  const isAdmin = !!me?.is_admin;

  const weekStart = useMemo(() => startOfWeek(refDate), [refDate]);
  const days = useMemo(
    () => Array.from({ length: 7 }, (_, i) => addDays(weekStart, i)),
    [weekStart]
  );

  const load = useCallback(async () => {
    if (!me) return;
    setLoading(true);
    setError(null);
    try {
      const from = weekStart.toISOString();
      const to = addDays(weekStart, 7).toISOString();
      const targetId = viewUserId ?? me.id;
      const url =
        `/api/v1/agenda/unified?scope=prospection` +
        `&from=${encodeURIComponent(from)}&to=${encodeURIComponent(to)}` +
        `&user_id=${targetId}`;
      const res = await authedFetch(url);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setEvents((await res.json()) as UnifiedEvent[]);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erreur");
    } finally {
      setLoading(false);
    }
  }, [me, weekStart, viewUserId]);

  useEffect(() => {
    void load();
  }, [load]);

  // Charge la liste d'users si admin (pour le sélecteur d'agenda).
  useEffect(() => {
    if (!isAdmin) return;
    void (async () => {
      try {
        const res = await authedFetch("/api/v1/users");
        if (!res.ok) return;
        const data = (await res.json()) as Array<UserMini & {
          volets: string[];
        }>;
        // Filtre aux users avec accès Prospection
        const prospUsers = data.filter((u) =>
          u.volets.includes("prospection")
        );
        setUsers(prospUsers);
      } catch {
        /* ignore */
      }
    })();
  }, [isAdmin]);

  function eventsForDay(day: Date): UnifiedEvent[] {
    const dayKey = day.toDateString();
    return events
      .filter((e) => new Date(e.start_at).toDateString() === dayKey)
      .sort(
        (a, b) =>
          new Date(a.start_at).getTime() - new Date(b.start_at).getTime()
      );
  }

  return (
    <>
      <AppTopbar
        breadcrumbs={[
          { label: "Prospection", href: "/prospection" },
          { label: "Agenda" }
        ]}
        onOpenSidebar={onOpenSidebar}
        rightSlot={
          <button
            type="button"
            onClick={() => setShowCreate(new Date())}
            className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-500 px-3 py-1.5 text-sm font-semibold text-brand-950 hover:bg-emerald-400"
          >
            <Plus className="h-4 w-4" /> Nouveau RDV
          </button>
        }
      />

      <div className="px-4 py-6 lg:px-6">
        <header className="mb-4 flex flex-wrap items-center gap-3">
          <h1 className="flex items-center gap-2 text-xl font-bold text-white">
            <Calendar className="h-5 w-5 text-emerald-400" />
            Agenda Prospection
          </h1>

          <div className="ml-auto flex items-center gap-2">
            <button
              type="button"
              onClick={() => setRefDate(addDays(refDate, -7))}
              className="rounded-md border border-brand-800 p-1.5 text-white/70 hover:bg-brand-900"
              aria-label="Semaine précédente"
            >
              <ChevronLeft className="h-4 w-4" />
            </button>
            <button
              type="button"
              onClick={() => setRefDate(new Date())}
              className="rounded-md border border-brand-800 px-2 py-1 text-xs text-white/70 hover:bg-brand-900"
            >
              Aujourd&apos;hui
            </button>
            <button
              type="button"
              onClick={() => setRefDate(addDays(refDate, 7))}
              className="rounded-md border border-brand-800 p-1.5 text-white/70 hover:bg-brand-900"
              aria-label="Semaine suivante"
            >
              <ChevronRight className="h-4 w-4" />
            </button>
          </div>
        </header>

        <div className="mb-3 flex flex-wrap items-center gap-3">
          <p className="text-sm text-white/70">
            Semaine du {fmtDateLong(weekStart)} —{" "}
            {fmtDateLong(addDays(weekStart, 6))}
          </p>
          {isAdmin && users.length > 0 ? (
            <select
              value={viewUserId ?? me?.id ?? 0}
              onChange={(e) =>
                setViewUserId(Number(e.target.value) || null)
              }
              className="rounded-md border border-brand-800 bg-brand-900 px-2 py-1 text-xs text-white"
            >
              {me ? (
                <option value={me.id}>Mon agenda</option>
              ) : null}
              {users
                .filter((u) => u.id !== me?.id)
                .map((u) => (
                  <option key={u.id} value={u.id}>
                    {u.full_name || u.email}
                  </option>
                ))}
            </select>
          ) : null}
        </div>

        <div className="mb-3 flex flex-wrap gap-3 text-xs text-white/50">
          <Legend tone="prospection" label="RDV Prospection (clair)" />
          <Legend tone="opaque" label="Construction / autre (opaque)" />
        </div>

        {loading ? (
          <p className="flex items-center gap-2 text-sm text-white/50">
            <Loader2 className="h-4 w-4 animate-spin" /> Chargement…
          </p>
        ) : error ? (
          <p className="rounded-lg border border-rose-500/40 bg-rose-500/10 p-3 text-sm text-rose-300">
            {error}
          </p>
        ) : (
          <div className="grid grid-cols-1 gap-3 md:grid-cols-7">
            {days.map((d, i) => (
              <DayColumn
                key={d.toISOString()}
                day={d}
                events={eventsForDay(d)}
                onEmptySlot={() => setShowCreate(d)}
                onEventClick={(ev) =>
                  ev.is_opaque ? null : setEditing(ev)
                }
              />
            ))}
          </div>
        )}
      </div>

      {showCreate ? (
        <EventModal
          initialDate={showCreate}
          onClose={() => setShowCreate(null)}
          onSaved={() => {
            setShowCreate(null);
            void load();
          }}
        />
      ) : null}

      {editing ? (
        <EventModal
          existing={editing}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null);
            void load();
          }}
        />
      ) : null}
    </>
  );
}

function Legend({
  tone,
  label
}: {
  tone: "prospection" | "opaque";
  label: string;
}) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span
        className={`h-3 w-3 rounded ${
          tone === "prospection"
            ? "bg-emerald-500/70"
            : "border border-white/30 bg-brand-800/80"
        }`}
      />
      {label}
    </span>
  );
}

function DayColumn({
  day,
  events,
  onEmptySlot,
  onEventClick
}: {
  day: Date;
  events: UnifiedEvent[];
  onEmptySlot: () => void;
  onEventClick: (ev: UnifiedEvent) => void;
}) {
  const isToday = new Date().toDateString() === day.toDateString();
  return (
    <div
      className={`rounded-xl border p-2 ${
        isToday
          ? "border-emerald-500/50 bg-emerald-500/5"
          : "border-brand-800 bg-brand-900/40"
      }`}
    >
      <header className="mb-2 flex items-baseline justify-between px-1">
        <span
          className={`text-[10px] font-semibold uppercase tracking-wider ${
            isToday ? "text-emerald-400" : "text-white/50"
          }`}
        >
          {DAYS_FR[day.getDay()]}
        </span>
        <span
          className={`text-base font-bold ${
            isToday ? "text-emerald-300" : "text-white/80"
          }`}
        >
          {day.getDate()}
        </span>
      </header>

      <div className="space-y-1.5">
        {events.length === 0 ? (
          <button
            type="button"
            onClick={onEmptySlot}
            className="block w-full rounded-md border border-dashed border-brand-800 py-3 text-center text-[11px] text-white/30 hover:border-emerald-700/60 hover:text-emerald-300"
          >
            + ajouter
          </button>
        ) : (
          events.map((ev) => (
            <EventCard key={ev.id} ev={ev} onClick={() => onEventClick(ev)} />
          ))
        )}
      </div>
    </div>
  );
}

function EventCard({
  ev,
  onClick
}: {
  ev: UnifiedEvent;
  onClick: () => void;
}) {
  if (ev.is_opaque) {
    return (
      <div
        className="cursor-default rounded-md border border-white/10 bg-brand-800/60 px-2 py-1.5 text-[11px] text-white/40"
        title="Plage occupée par un autre volet — détails masqués"
      >
        <div className="flex items-center gap-1.5">
          <Lock className="h-3 w-3" />
          <span className="font-medium">Indisponible</span>
        </div>
        <p className="mt-0.5 tabular-nums">
          {fmtTime(ev.start_at)}
          {ev.end_at ? ` – ${fmtTime(ev.end_at)}` : ""}
        </p>
      </div>
    );
  }
  const Icon = ev.event_type === "appel" ? Phone : Clock;
  return (
    <button
      type="button"
      onClick={onClick}
      className="block w-full rounded-md border border-emerald-700/40 bg-emerald-500/10 px-2 py-1.5 text-left text-[11px] text-emerald-100 hover:border-emerald-500 hover:bg-emerald-500/20"
    >
      <div className="flex items-center gap-1.5">
        <Icon className="h-3 w-3 text-emerald-300" />
        <span className="font-semibold">{ev.title}</span>
      </div>
      <p className="mt-0.5 tabular-nums text-emerald-300/80">
        {fmtTime(ev.start_at)}
        {ev.end_at ? ` – ${fmtTime(ev.end_at)}` : ""}
      </p>
      {ev.location ? (
        <p className="mt-0.5 truncate text-white/60">{ev.location}</p>
      ) : null}
    </button>
  );
}

// -------------------- Event modal --------------------

function toLocalInput(iso: string | Date): string {
  const d = typeof iso === "string" ? new Date(iso) : iso;
  const off = d.getTimezoneOffset();
  const local = new Date(d.getTime() - off * 60 * 1000);
  return local.toISOString().slice(0, 16);
}

function EventModal({
  existing,
  initialDate,
  onClose,
  onSaved
}: {
  existing?: UnifiedEvent;
  initialDate?: Date;
  onClose: () => void;
  onSaved: () => void;
}) {
  const { user: me } = useCurrentUser();
  const isEdit = !!existing;
  const baseDate =
    existing
      ? new Date(existing.start_at)
      : initialDate
      ? new Date(
          initialDate.getFullYear(),
          initialDate.getMonth(),
          initialDate.getDate(),
          9,
          0,
          0
        )
      : new Date();

  const [title, setTitle] = useState(existing?.title || "");
  const [location, setLocation] = useState(existing?.location || "");
  const [description, setDescription] = useState(
    existing?.description || ""
  );
  const [eventType, setEventType] = useState(
    existing?.event_type || "rdv"
  );
  const [startAt, setStartAt] = useState(toLocalInput(baseDate));
  const [endAt, setEndAt] = useState(
    existing?.end_at
      ? toLocalInput(existing.end_at)
      : toLocalInput(
          new Date(baseDate.getTime() + 60 * 60 * 1000)
        )
  );
  const [leads, setLeads] = useState<LeadMini[]>([]);
  const [leadId, setLeadId] = useState<number | "">(
    existing?.lead_id ?? ""
  );
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Charge la liste des leads pour le picker
  useEffect(() => {
    void (async () => {
      try {
        const res = await authedFetch("/api/v1/prospection?limit=200");
        if (!res.ok) return;
        const data = (await res.json()) as LeadMini[];
        setLeads(data);
      } catch {
        /* ignore */
      }
    })();
  }, []);

  async function submit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!title.trim()) {
      setError("Le titre est requis.");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const payload = {
        title: title.trim(),
        location: location.trim() || null,
        description: description.trim() || null,
        start_at: new Date(startAt).toISOString(),
        end_at: endAt ? new Date(endAt).toISOString() : null,
        scope: "prospection",
        event_type: eventType,
        lead_id: leadId === "" ? null : Number(leadId),
        // L'event est assigné au user qui le crée (côté Prospection
        // les prospecteurs n'ont pas forcément de ligne Employe).
        // Côté Construction on continue d'utiliser assignee_id (Employe).
        assignee_user_id:
          existing?.assignee_user_id ?? me?.id ?? null
      };
      const url = isEdit
        ? `/api/v1/agenda/${existing!.id}`
        : "/api/v1/agenda";
      const method = isEdit ? "PATCH" : "POST";
      const res = await authedFetch(url, {
        method,
        body: JSON.stringify(payload)
      });
      if (!res.ok) {
        const t = await res.text();
        throw new Error(t.slice(0, 240) || `HTTP ${res.status}`);
      }
      onSaved();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erreur");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleDelete() {
    if (!existing) return;
    if (!window.confirm("Supprimer ce RDV ?")) return;
    const res = await authedFetch(`/api/v1/agenda/${existing.id}`, {
      method: "DELETE"
    });
    if (res.ok) onSaved();
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4 backdrop-blur-sm">
      <div className="w-full max-w-md rounded-2xl border border-brand-800 bg-brand-950 p-6">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-base font-bold text-white">
            {isEdit ? "Modifier le RDV" : "Nouveau RDV Prospection"}
          </h2>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md p-1 text-white/40 hover:bg-brand-900 hover:text-white"
            aria-label="Fermer"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <form onSubmit={submit} className="space-y-3">
          <Field label="Titre" required>
            <input
              type="text"
              required
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="Appel propriétaire 4520 St-Laurent"
              className="w-full rounded-lg border border-brand-800 bg-brand-900 px-3 py-2 text-sm text-white"
            />
          </Field>

          <Field label="Type">
            <select
              value={eventType}
              onChange={(e) => setEventType(e.target.value)}
              className="w-full rounded-lg border border-brand-800 bg-brand-900 px-3 py-2 text-sm text-white"
            >
              <option value="rdv">Rendez-vous</option>
              <option value="appel">Appel</option>
              <option value="visite">Visite</option>
              <option value="reunion">Réunion</option>
            </select>
          </Field>

          <div className="grid grid-cols-2 gap-3">
            <Field label="Début">
              <input
                type="datetime-local"
                value={startAt}
                onChange={(e) => setStartAt(e.target.value)}
                className="w-full rounded-lg border border-brand-800 bg-brand-900 px-3 py-2 text-sm text-white"
              />
            </Field>
            <Field label="Fin">
              <input
                type="datetime-local"
                value={endAt}
                onChange={(e) => setEndAt(e.target.value)}
                className="w-full rounded-lg border border-brand-800 bg-brand-900 px-3 py-2 text-sm text-white"
              />
            </Field>
          </div>

          <Field label="Lieu">
            <input
              type="text"
              value={location}
              onChange={(e) => setLocation(e.target.value)}
              placeholder="Adresse, Zoom, téléphone…"
              className="w-full rounded-lg border border-brand-800 bg-brand-900 px-3 py-2 text-sm text-white"
            />
          </Field>

          <Field label="Lead lié (optionnel)">
            <select
              value={leadId}
              onChange={(e) =>
                setLeadId(
                  e.target.value === "" ? "" : Number(e.target.value)
                )
              }
              className="w-full rounded-lg border border-brand-800 bg-brand-900 px-3 py-2 text-sm text-white"
            >
              <option value="">— aucun —</option>
              {leads.map((l) => (
                <option key={l.id} value={l.id}>
                  {l.name}
                  {l.address ? ` (${l.address})` : ""}
                </option>
              ))}
            </select>
          </Field>

          <Field label="Notes">
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={3}
              className="w-full rounded-lg border border-brand-800 bg-brand-900 px-3 py-2 text-sm text-white"
            />
          </Field>

          {error ? (
            <p className="text-sm text-rose-300">{error}</p>
          ) : null}

          <div className="flex items-center gap-2 pt-2">
            <button
              type="submit"
              disabled={submitting}
              className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-500 px-4 py-2 text-sm font-semibold text-brand-950 hover:bg-emerald-400 disabled:opacity-50"
            >
              {submitting ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : null}
              {isEdit ? "Enregistrer" : "Créer le RDV"}
            </button>
            <button
              type="button"
              onClick={onClose}
              className="rounded-lg border border-brand-800 px-3 py-2 text-sm text-white/80 hover:bg-brand-900"
            >
              Annuler
            </button>
            {isEdit ? (
              <button
                type="button"
                onClick={handleDelete}
                className="ml-auto rounded-lg border border-rose-500/40 px-3 py-2 text-sm text-rose-300 hover:bg-rose-500/10"
              >
                Supprimer
              </button>
            ) : null}
          </div>
        </form>
      </div>
    </div>
  );
}

function Field({
  label,
  children,
  required
}: {
  label: string;
  children: React.ReactNode;
  required?: boolean;
}) {
  return (
    <label className="block">
      <span className="block text-xs font-semibold uppercase tracking-wider text-white/50">
        {label}
        {required ? <span className="ml-1 text-rose-400">*</span> : null}
      </span>
      <div className="mt-1">{children}</div>
    </label>
  );
}
