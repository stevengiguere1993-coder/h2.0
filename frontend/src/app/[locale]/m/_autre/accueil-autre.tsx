"use client";

/**
 * Accueil de la zone employés — variante « autre » (employé sans pôle
 * Construction). Pas de punch ni de /mobile/me : prochain événement
 * planifié, tâches personnelles ouvertes et feuille de temps de la
 * période de paie courante.
 */

import { useEffect, useState } from "react";
import {
  Calendar,
  CheckSquare,
  ChevronRight,
  Clock,
  Loader2,
  MapPin
} from "lucide-react";

import { Link } from "@/i18n/navigation";
import { authedFetch } from "@/lib/auth";
import { TASK_STATUS_OPTIONS } from "@/lib/task-config";
import { useZoneEmploye } from "../zone-employe-context";
import {
  EVENT_TYPE_LABELS,
  firstName,
  fmtHm,
  formatDayLong,
  formatEventWhen,
  formatPeriod,
  timesheetStatus,
  type EventMini,
  type MaTache,
  type TimesheetDetail
} from "./shared";

const STATUS_DOT: Record<string, string> = Object.fromEntries(
  TASK_STATUS_OPTIONS.map((o) => [o.value, o.dot])
);

export function AccueilAutre() {
  const { me } = useZoneEmploye();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [nextEvent, setNextEvent] = useState<EventMini | null>(null);
  const [taches, setTaches] = useState<MaTache[]>([]);
  const [feuille, setFeuille] = useState<TimesheetDetail | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError(null);
      const [agendaRes, tachesRes, feuilleRes] = await Promise.allSettled([
        authedFetch("/api/v1/mobile/agenda?days=14"),
        authedFetch("/api/v1/entreprises/mes-taches"),
        authedFetch("/api/v1/timesheets/resolve")
      ]);
      if (cancelled) return;
      let failed = false;

      if (agendaRes.status === "fulfilled" && agendaRes.value.ok) {
        const body = (await agendaRes.value.json()) as unknown;
        const rows = Array.isArray(body) ? (body as EventMini[]) : [];
        const now = Date.now();
        // Premier événement à venir (ou en cours si une fin est connue).
        const upcoming = rows
          .filter((e) => {
            const end = e.end_at ? new Date(e.end_at).getTime() : null;
            return (
              new Date(e.start_at).getTime() >= now ||
              (end != null && end >= now)
            );
          })
          .sort(
            (a, b) =>
              new Date(a.start_at).getTime() - new Date(b.start_at).getTime()
          );
        setNextEvent(upcoming[0] || null);
      } else {
        failed = true;
      }

      if (tachesRes.status === "fulfilled" && tachesRes.value.ok) {
        const body = (await tachesRes.value.json()) as unknown;
        setTaches(Array.isArray(body) ? (body as MaTache[]) : []);
      } else {
        failed = true;
      }

      if (feuilleRes.status === "fulfilled" && feuilleRes.value.ok) {
        setFeuille((await feuilleRes.value.json()) as TimesheetDetail);
      } else {
        failed = true;
      }

      if (cancelled) return;
      if (failed) setError("Certaines informations n'ont pas pu être chargées.");
      setLoading(false);
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, []);

  const today = new Date();
  const name = me?.display_name || me?.email || "";
  const statut = feuille ? timesheetStatus(feuille.status) : null;

  return (
    <>
      <header
        className="sticky top-0 z-30 flex items-center justify-between gap-3 border-b border-brand-800 bg-brand-950/95 px-4 py-3 backdrop-blur"
        style={{ paddingTop: "max(env(safe-area-inset-top), 0.75rem)" }}
      >
        <h1 className="text-base font-bold text-white">Accueil</h1>
      </header>

      <div className="space-y-4 p-4">
        {error ? (
          <p className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
            {error}
          </p>
        ) : null}

        {/* Salutation */}
        <section className="rounded-2xl border border-brand-800 bg-brand-900 p-4">
          <div className="flex items-center gap-3">
            <Avatar name={name || "?"} />
            <div className="min-w-0">
              <p className="text-sm text-accent-500">
                Bonjour, {firstName(me?.display_name) || name}
              </p>
              <p className="mt-0.5 text-xs text-white/50">
                {formatDayLong(today)}
              </p>
            </div>
          </div>
        </section>

        {loading ? (
          <div className="flex items-center justify-center py-10">
            <Loader2 className="h-5 w-5 animate-spin text-white/40" />
          </div>
        ) : (
          <>
            {/* Prochain événement */}
            <section className="rounded-2xl border border-brand-800 bg-brand-900 p-4">
              <p className="flex items-center gap-2 text-xs uppercase tracking-wider text-white/50">
                <Calendar className="h-3.5 w-3.5 text-accent-500" /> Prochain
                événement
              </p>
              <Link
                // eslint-disable-next-line @typescript-eslint/no-explicit-any
                href={"/m/agenda" as any}
                className="mt-2 flex items-center justify-between gap-2"
              >
                {nextEvent ? (
                  <div className="min-w-0">
                    {EVENT_TYPE_LABELS[nextEvent.event_type] ? (
                      <span className="inline-block rounded-full border border-brand-700 bg-brand-950 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-white/60">
                        {EVENT_TYPE_LABELS[nextEvent.event_type]}
                      </span>
                    ) : null}
                    <p className="mt-1 truncate text-sm font-semibold text-white">
                      {nextEvent.title}
                    </p>
                    <p className="mt-0.5 text-xs text-white/50">
                      {formatEventWhen(nextEvent)}
                    </p>
                    {nextEvent.location ? (
                      <p className="mt-0.5 flex items-center gap-1 truncate text-xs text-white/50">
                        <MapPin className="h-3 w-3" /> {nextEvent.location}
                      </p>
                    ) : null}
                  </div>
                ) : (
                  <p className="text-sm text-white/60">
                    Rien de prévu dans les 14 prochains jours.
                  </p>
                )}
                <ChevronRight className="h-4 w-4 flex-shrink-0 text-white/30" />
              </Link>
            </section>

            {/* Mes tâches */}
            <section className="rounded-2xl border border-brand-800 bg-brand-900 p-4">
              <p className="flex items-center gap-2 text-xs uppercase tracking-wider text-white/50">
                <CheckSquare className="h-3.5 w-3.5 text-accent-500" /> Mes
                tâches
              </p>
              <Link
                // eslint-disable-next-line @typescript-eslint/no-explicit-any
                href={"/m/taches" as any}
                className="mt-2 flex items-center justify-between gap-2"
              >
                <div className="min-w-0 flex-1">
                  <p className="text-lg font-bold text-white">
                    {taches.length}{" "}
                    <span className="text-sm font-medium text-white/60">
                      {taches.length === 1 ? "tâche ouverte" : "tâches ouvertes"}
                    </span>
                  </p>
                  {taches.length > 0 ? (
                    <ul className="mt-2 space-y-1.5">
                      {taches.slice(0, 3).map((t) => (
                        <li key={t.id} className="flex items-center gap-2">
                          <span
                            className={`h-2 w-2 flex-shrink-0 rounded-full ${
                              STATUS_DOT[t.status] || "bg-slate-400"
                            }`}
                          />
                          <span className="min-w-0 flex-1 truncate text-sm text-white">
                            {t.title}
                          </span>
                          <span className="flex-shrink-0 text-[11px] text-white/50">
                            {t.entreprise_name}
                          </span>
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="mt-1 text-sm text-white/60">
                      Aucune tâche en cours.
                    </p>
                  )}
                </div>
                <ChevronRight className="h-4 w-4 flex-shrink-0 text-white/30" />
              </Link>
            </section>

            {/* Feuille de temps */}
            <section className="rounded-2xl border border-brand-800 bg-brand-900 p-4">
              <p className="flex items-center gap-2 text-xs uppercase tracking-wider text-white/50">
                <Clock className="h-3.5 w-3.5 text-accent-500" /> Feuille de
                temps
              </p>
              <Link
                // eslint-disable-next-line @typescript-eslint/no-explicit-any
                href={"/m/feuille-de-temps" as any}
                className="mt-2 flex items-center justify-between gap-2"
              >
                {feuille && statut ? (
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <p className="text-lg font-bold text-white">
                        {fmtHm(feuille.total_heures)}
                      </p>
                      <span
                        className={`rounded-full border px-2 py-0.5 text-[10px] font-semibold ${statut.cls}`}
                      >
                        {statut.label}
                      </span>
                    </div>
                    <p className="mt-0.5 text-xs text-white/50">
                      Période du{" "}
                      {formatPeriod(feuille.period_start, feuille.period_end)}
                    </p>
                  </div>
                ) : (
                  <p className="text-sm text-white/60">
                    Feuille de temps indisponible.
                  </p>
                )}
                <ChevronRight className="h-4 w-4 flex-shrink-0 text-white/30" />
              </Link>
            </section>

            {/* Actions rapides */}
            <section className="space-y-3">
              <p className="flex items-center gap-2 text-xs uppercase tracking-wider text-white/50">
                ⚡ Actions rapides
              </p>
              <Link
                // eslint-disable-next-line @typescript-eslint/no-explicit-any
                href={"/m/taches" as any}
                className="flex w-full items-center justify-center gap-2 rounded-xl bg-blue-500 px-5 py-4 text-base font-bold text-white"
              >
                <CheckSquare className="h-5 w-5" /> Mes tâches
              </Link>
              <Link
                // eslint-disable-next-line @typescript-eslint/no-explicit-any
                href={"/m/agenda" as any}
                className="flex w-full items-center justify-center gap-2 rounded-xl bg-violet-500 px-5 py-4 text-base font-bold text-white"
              >
                <Calendar className="h-5 w-5" /> Voir l&apos;agenda
              </Link>
              <Link
                // eslint-disable-next-line @typescript-eslint/no-explicit-any
                href={"/m/feuille-de-temps" as any}
                className="flex w-full items-center justify-center gap-2 rounded-xl bg-accent-500 px-5 py-4 text-base font-bold text-brand-950"
              >
                <Clock className="h-5 w-5" /> Remplir ma feuille de temps
              </Link>
            </section>
          </>
        )}
      </div>
    </>
  );
}

function Avatar({ name }: { name: string }) {
  const initials = name
    .split(/[\s.@]+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((s) => s[0]?.toUpperCase() || "")
    .join("");
  return (
    <span className="flex h-12 w-12 items-center justify-center rounded-full bg-accent-500/20 text-sm font-bold text-accent-500">
      {initials || "?"}
    </span>
  );
}
