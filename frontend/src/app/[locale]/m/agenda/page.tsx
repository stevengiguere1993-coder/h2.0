"use client";

import { useEffect, useMemo, useState } from "react";
import { Calendar, ChevronRight, Loader2, MapPin } from "lucide-react";

import { Link } from "@/i18n/navigation";
import { authedFetch } from "@/lib/auth";

type EventMini = {
  id: number;
  title: string;
  description: string | null;
  location: string | null;
  start_at: string;
  end_at: string | null;
  all_day: boolean;
  project_id: number | null;
  event_type: string;
};

function ymd(d: Date): string {
  if (Number.isNaN(d.getTime())) return "0000-00-00";
  // Use local components — la PWA iOS rendrait sinon une date UTC
  // qui décale d'un jour à Montréal.
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

export default function MobileAgenda() {
  const [events, setEvents] = useState<EventMini[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      try {
        const res = await authedFetch("/api/v1/mobile/agenda?days=30");
        if (!res.ok) throw new Error(`http_${res.status}`);
        const body = (await res.json()) as unknown;
        if (!cancelled) {
          // Backend doit renvoyer un tableau ; on durcit pour ne pas
          // planter le render si jamais c'est un objet d'erreur.
          setEvents(Array.isArray(body) ? (body as EventMini[]) : []);
        }
      } catch {
        if (!cancelled) setError("Chargement échoué.");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, []);

  const grouped = useMemo(() => {
    const map = new Map<string, EventMini[]>();
    if (!Array.isArray(events)) return [];
    for (const e of events) {
      if (!e || !e.start_at) continue;
      const d = ymd(new Date(e.start_at));
      if (!map.has(d)) map.set(d, []);
      map.get(d)!.push(e);
    }
    return Array.from(map.entries()).sort(([a], [b]) =>
      a.localeCompare(b)
    );
  }, [events]);

  return (
    <>
      <header
        className="sticky top-0 z-30 border-b border-brand-800 bg-brand-950/95 px-4 py-3 backdrop-blur"
        style={{ paddingTop: "max(env(safe-area-inset-top), 0.75rem)" }}
      >
        <h1 className="text-base font-bold text-white">Agenda</h1>
        <p className="mt-0.5 text-xs text-white/50">30 prochains jours</p>
      </header>

      <div className="p-4">
        {error ? (
          <p className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
            {error}
          </p>
        ) : null}

        {loading ? (
          <div className="flex items-center justify-center py-10">
            <Loader2 className="h-5 w-5 animate-spin text-white/40" />
          </div>
        ) : grouped.length === 0 ? (
          <div className="rounded-2xl border border-dashed border-brand-800 bg-brand-900/40 px-6 py-10 text-center">
            <Calendar className="mx-auto h-8 w-8 text-white/30" />
            <p className="mt-3 text-sm text-white/60">
              Aucun événement prévu.
            </p>
          </div>
        ) : (
          <div className="space-y-5">
            {grouped.map(([d, evs]) => (
              <div key={d}>
                <p className="text-xs font-semibold uppercase tracking-wider text-accent-500">
                  {new Date(d + "T12:00:00").toLocaleDateString("fr-CA", {
                    weekday: "long",
                    day: "numeric",
                    month: "long"
                  })}
                </p>
                <ul className="mt-2 space-y-2">
                  {evs.map((e) => (
                    <EventCard key={e.id} event={e} />
                  ))}
                </ul>
              </div>
            ))}
          </div>
        )}
      </div>
    </>
  );
}

function EventCard({ event: e }: { event: EventMini }) {
  const startHm = new Date(e.start_at).toLocaleTimeString("fr-CA", {
    hour: "2-digit",
    minute: "2-digit"
  });
  const endHm = e.end_at
    ? new Date(e.end_at).toLocaleTimeString("fr-CA", {
        hour: "2-digit",
        minute: "2-digit"
      })
    : null;
  const tone =
    e.event_type === "conge"
      ? "border-rose-500/40 bg-rose-500/10"
      : e.event_type === "chantier"
      ? "border-blue-500/30 bg-blue-500/5"
      : "border-brand-800 bg-brand-900";
  return (
    <li
      className={`flex items-center justify-between gap-2 rounded-xl border px-3 py-3 ${tone}`}
    >
      <Link
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        href={`/m/intervention/${e.id}` as any}
        className="flex min-w-0 flex-1 items-start gap-3"
      >
        <div className="text-center">
          <p className="text-base font-bold text-white">{startHm}</p>
          {endHm ? (
            <p className="text-[10px] text-white/40">{endHm}</p>
          ) : null}
        </div>
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-semibold text-white">
            {e.title}
          </p>
          {e.location ? (
            <p className="mt-0.5 flex items-center gap-1 truncate text-xs text-white/50">
              <MapPin className="h-3 w-3" /> {e.location}
            </p>
          ) : null}
        </div>
      </Link>
      <ChevronRight className="h-4 w-4 text-white/30" />
    </li>
  );
}
