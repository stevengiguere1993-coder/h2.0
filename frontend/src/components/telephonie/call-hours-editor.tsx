"use client";

// Heures d'appel PERSONNELLES (téléphonie, bug 19 du 2026-10-18).
//
// Une personne qui peut être appelée choisit quand un appel transféré
// (secrétaire Léa, règle d'acheminement, responsable de dossier) peut la
// faire sonner. Aucune plage = joignable en tout temps ; dès qu'une plage
// existe, hors plage l'appel passe à la personne suivante de la règle
// (ou à la boîte vocale).
//
// - CallHoursEditor : l'éditeur (Mon profil, et Téléphonie → Acheminement
//   quand un admin règle les heures d'un membre de l'équipe) ;
// - MyCallHoursCard : la carte « Mes heures d'appel » des pages profil
//   (charge et enregistre /api/v1/voice/call-hours/me elle-même).

import { useEffect, useState } from "react";
import { CheckCircle2, Clock, Loader2, Plus, X } from "lucide-react";

import { authedFetch } from "@/lib/auth";

export type CallHoursRow = {
  id?: number;
  user_id?: number;
  day_of_week: number;
  open_time: string;
  close_time: string;
  timezone?: string;
};

export type CallHoursInput = {
  day_of_week: number;
  open_time: string;
  close_time: string;
  timezone: string;
};

export const CALL_HOURS_TZ = "America/Montreal";
export const DAY_LABELS = [
  "Lundi",
  "Mardi",
  "Mercredi",
  "Jeudi",
  "Vendredi",
  "Samedi",
  "Dimanche"
];
const DAY_SHORT = ["lun", "mar", "mer", "jeu", "ven", "sam", "dim"];
const WEEKDAYS_EN = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

type Range = { open: string; close: string };
type DayState = { enabled: boolean; ranges: Range[] };

function toMinutes(hm: string): number {
  const [h, m] = hm.split(":").map((x) => Number(x) || 0);
  return h * 60 + m;
}

/** Jour (0 = lundi) et minutes de l'heure courante à Montréal. */
function montrealNow(): { dow: number; minutes: number } {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: CALL_HOURS_TZ,
    weekday: "short",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23"
  }).formatToParts(new Date());
  const get = (t: string) => parts.find((p) => p.type === t)?.value || "";
  const dow = WEEKDAYS_EN.indexOf(get("weekday"));
  return {
    dow: dow < 0 ? 0 : dow,
    minutes: (Number(get("hour")) || 0) * 60 + (Number(get("minute")) || 0)
  };
}

/** « Joignable maintenant ? » — même règle que le serveur : aucune plage
 *  = toujours ; une plage qui finit avant son début déborde sur le
 *  lendemain (vendredi 22:00 → 02:00 = jusqu'à samedi 2 h). */
export function isAvailableNow(rows: CallHoursRow[]): boolean {
  if (rows.length === 0) return true;
  const { dow, minutes } = montrealNow();
  return rows.some((r) => {
    const o = toMinutes(r.open_time);
    const c = toMinutes(r.close_time);
    if (c <= o) {
      return (
        (r.day_of_week === dow && minutes >= o) ||
        ((r.day_of_week + 1) % 7 === dow && minutes <= c)
      );
    }
    return r.day_of_week === dow && minutes >= o && minutes <= c;
  });
}

/** Résumé lisible : « lun–ven 08:00–17:00 · sam 09:00–12:00 ». */
export function summarizeCallHours(rows: CallHoursRow[]): string {
  if (rows.length === 0) return "Joignable en tout temps";
  const sigs: (string | null)[] = DAY_LABELS.map((_, d) => {
    const day = rows
      .filter((r) => r.day_of_week === d)
      .sort((a, b) => toMinutes(a.open_time) - toMinutes(b.open_time))
      .map((r) => `${r.open_time}–${r.close_time}`);
    return day.length ? day.join(", ") : null;
  });
  const parts: string[] = [];
  let d = 0;
  while (d < 7) {
    const sig = sigs[d];
    if (!sig) {
      d++;
      continue;
    }
    let e = d;
    while (e + 1 < 7 && sigs[e + 1] === sig) e++;
    parts.push(
      `${e > d ? `${DAY_SHORT[d]}–${DAY_SHORT[e]}` : DAY_SHORT[d]} ${sig}`
    );
    d = e + 1;
  }
  return parts.join(" · ");
}

function daysFromRows(rows: CallHoursRow[]): DayState[] {
  return DAY_LABELS.map((_, dow) => {
    const ranges = rows
      .filter((r) => r.day_of_week === dow)
      .sort((a, b) => toMinutes(a.open_time) - toMinutes(b.open_time))
      .map((r) => ({ open: r.open_time, close: r.close_time }));
    return ranges.length
      ? { enabled: true, ranges }
      : { enabled: false, ranges: [{ open: "08:00", close: "17:00" }] };
  });
}

function rowsFromDays(days: DayState[]): CallHoursInput[] {
  const out: CallHoursInput[] = [];
  days.forEach((d, dow) => {
    if (!d.enabled) return;
    for (const r of d.ranges) {
      out.push({
        day_of_week: dow,
        open_time: r.open,
        close_time: r.close,
        timezone: CALL_HOURS_TZ
      });
    }
  });
  return out;
}

export function CallHoursEditor({
  hours,
  onSave,
  saving = false,
  selfView = true
}: {
  hours: CallHoursRow[];
  /** Reçoit la liste COMPLÈTE des plages ([] = joignable en tout temps). */
  onSave: (rows: CallHoursInput[]) => void | Promise<void>;
  saving?: boolean;
  /** true : « tu » (Mon profil) ; false : vue admin d'un membre. */
  selfView?: boolean;
}) {
  const [restricted, setRestricted] = useState(hours.length > 0);
  const [days, setDays] = useState<DayState[]>(() => daysFromRows(hours));
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setRestricted(hours.length > 0);
    setDays(daysFromRows(hours));
    setError(null);
  }, [hours]);

  const patchDay = (dow: number, patch: Partial<DayState>) =>
    setDays((prev) => prev.map((d, i) => (i === dow ? { ...d, ...patch } : d)));

  const patchRange = (dow: number, idx: number, patch: Partial<Range>) =>
    setDays((prev) =>
      prev.map((d, i) =>
        i === dow
          ? {
              ...d,
              ranges: d.ranges.map((r, j) =>
                j === idx ? { ...r, ...patch } : r
              )
            }
          : d
      )
    );

  const preview = restricted ? rowsFromDays(days) : [];
  const nowOk = isAvailableNow(preview);

  async function save() {
    setError(null);
    if (!restricted) {
      await onSave([]);
      return;
    }
    const rows = rowsFromDays(days);
    if (rows.length === 0) {
      setError(
        "Coche au moins un jour, ou choisis « Joignable en tout temps »."
      );
      return;
    }
    const vide = rows.find((r) => r.open_time === r.close_time);
    if (vide) {
      setError(
        `${DAY_LABELS[vide.day_of_week]} : une plage doit finir à une autre heure que son début.`
      );
      return;
    }
    await onSave(rows);
  }

  const toi = selfView ? "tu es" : "la personne est";

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          onClick={() => setRestricted(false)}
          className={`rounded-lg border px-3 py-1.5 text-xs font-semibold transition ${
            !restricted
              ? "border-teal-500/50 bg-teal-500/15 text-teal-200"
              : "border-brand-800 bg-brand-950 text-white/60 hover:text-white"
          }`}
        >
          Joignable en tout temps
        </button>
        <button
          type="button"
          onClick={() => setRestricted(true)}
          className={`rounded-lg border px-3 py-1.5 text-xs font-semibold transition ${
            restricted
              ? "border-teal-500/50 bg-teal-500/15 text-teal-200"
              : "border-brand-800 bg-brand-950 text-white/60 hover:text-white"
          }`}
        >
          Seulement pendant ces plages
        </button>
      </div>

      {restricted ? (
        <>
          <div className="flex flex-wrap items-center gap-2 text-[11px] text-white/50">
            <span>Raccourcis :</span>
            <button
              type="button"
              onClick={() =>
                setDays(
                  DAY_LABELS.map((_, dow) => ({
                    enabled: dow < 5,
                    ranges: [{ open: "08:00", close: "17:00" }]
                  }))
                )
              }
              className="rounded-md border border-brand-800 bg-brand-950 px-2 py-1 text-white/70 hover:text-white"
            >
              Lun–ven, 8 h à 17 h
            </button>
            <button
              type="button"
              onClick={() =>
                setDays((prev) =>
                  prev.map((d, i) =>
                    i === 0 || !d.enabled
                      ? d
                      : { ...d, ranges: prev[0].ranges.map((r) => ({ ...r })) }
                  )
                )
              }
              className="rounded-md border border-brand-800 bg-brand-950 px-2 py-1 text-white/70 hover:text-white"
            >
              Copier lundi sur les jours cochés
            </button>
          </div>

          <div className="space-y-2">
            {days.map((d, dow) => (
              <div
                key={dow}
                className="rounded-lg border border-brand-800 bg-brand-950 px-3 py-2 text-sm sm:flex sm:items-start sm:gap-3"
              >
                <label className="flex items-center gap-2 pt-1 text-white/80 sm:w-28 sm:shrink-0">
                  <input
                    type="checkbox"
                    checked={d.enabled}
                    onChange={(e) =>
                      patchDay(dow, { enabled: e.target.checked })
                    }
                    className="h-3.5 w-3.5"
                  />
                  {DAY_LABELS[dow]}
                </label>
                {d.enabled ? (
                  <div className="mt-1.5 flex flex-1 flex-col gap-1.5 sm:mt-0">
                    {d.ranges.map((r, idx) => (
                      <div
                        key={idx}
                        className="flex flex-wrap items-center gap-x-2 gap-y-1"
                      >
                        <span className="flex items-center gap-2">
                          <input
                            type="time"
                            value={r.open}
                            onChange={(e) =>
                              patchRange(dow, idx, { open: e.target.value })
                            }
                            className="rounded-md border border-brand-800 bg-brand-900 px-2 py-1 text-white"
                            aria-label={`${DAY_LABELS[dow]} : début`}
                          />
                          <span className="text-white/40">→</span>
                          <input
                            type="time"
                            value={r.close}
                            onChange={(e) =>
                              patchRange(dow, idx, { close: e.target.value })
                            }
                            className="rounded-md border border-brand-800 bg-brand-900 px-2 py-1 text-white"
                            aria-label={`${DAY_LABELS[dow]} : fin`}
                          />
                          {d.ranges.length > 1 ? (
                            <button
                              type="button"
                              onClick={() =>
                                patchDay(dow, {
                                  ranges: d.ranges.filter((_, j) => j !== idx)
                                })
                              }
                              className="rounded p-1 text-white/50 hover:bg-brand-900 hover:text-rose-300"
                              aria-label="Retirer cette plage"
                              title="Retirer cette plage"
                            >
                              <X className="h-3.5 w-3.5" />
                            </button>
                          ) : null}
                        </span>
                        {r.close &&
                        r.open &&
                        toMinutes(r.close) < toMinutes(r.open) ? (
                          <span className="text-[11px] text-white/50">
                            (finit le lendemain)
                          </span>
                        ) : null}
                      </div>
                    ))}
                    <button
                      type="button"
                      onClick={() =>
                        patchDay(dow, {
                          ranges: [
                            ...d.ranges,
                            { open: "13:00", close: "17:00" }
                          ]
                        })
                      }
                      className="inline-flex w-fit items-center gap-1 text-[11px] text-teal-300 hover:text-teal-200"
                    >
                      <Plus className="h-3 w-3" /> Ajouter une plage
                    </button>
                  </div>
                ) : (
                  <span className="mt-1 block text-[11px] text-white/40 sm:mt-0 sm:pt-1">
                    pas d&apos;appel transféré ce jour-là
                  </span>
                )}
              </div>
            ))}
          </div>
          <p className="text-[11px] text-white/50">
            Heure de Montréal. Une plage qui finit avant son début se termine le
            lendemain (ex. 22:00 → 02:00).
          </p>
        </>
      ) : (
        <p className="text-[11px] text-white/50">
          Les appels transférés peuvent sonner à n&apos;importe quelle heure.
        </p>
      )}

      {error ? (
        <p className="rounded-md border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
          {error}
        </p>
      ) : null}

      <div className="flex flex-wrap items-center justify-between gap-2">
        <span
          className={`inline-flex items-center gap-1.5 text-xs ${
            nowOk ? "text-emerald-300" : "text-amber-300"
          }`}
        >
          <Clock className="h-3.5 w-3.5" />
          {nowOk
            ? `En ce moment, ${toi} joignable.`
            : `En ce moment, ${toi} hors de ces heures : l'appel passe à la personne suivante.`}
        </span>
        <button
          type="button"
          onClick={() => void save()}
          disabled={saving}
          className="inline-flex items-center rounded-md border border-teal-500/40 bg-teal-500/10 px-3 py-1.5 text-xs font-semibold text-teal-200 hover:bg-teal-500/20 disabled:opacity-60"
        >
          {saving ? (
            <Loader2 className="mr-1 h-3 w-3 animate-spin" />
          ) : (
            <CheckCircle2 className="mr-1 h-3 w-3" />
          )}
          Enregistrer
        </button>
      </div>
    </div>
  );
}

/** Message d'erreur lisible d'une réponse API (detail FastAPI). */
export async function apiError(res: Response): Promise<string> {
  try {
    const j = (await res.json()) as { detail?: unknown };
    if (typeof j?.detail === "string") return j.detail;
    if (Array.isArray(j?.detail) && j.detail.length) {
      const first = j.detail[0] as { msg?: string };
      if (first?.msg) return first.msg;
    }
  } catch {
    /* corps non JSON */
  }
  return `Erreur ${res.status}`;
}

/** Carte « Mes heures d'appel » des pages profil (bureau et zone employés). */
export function MyCallHoursCard({
  variant = "desktop"
}: {
  variant?: "desktop" | "mobile";
}) {
  const [hours, setHours] = useState<CallHoursRow[] | null>(null);
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const r = await authedFetch("/api/v1/voice/call-hours/me");
        if (!r.ok) throw new Error(await apiError(r));
        const rows = (await r.json()) as CallHoursRow[];
        if (!cancelled) setHours(rows);
      } catch (e) {
        if (!cancelled) {
          setHours([]);
          setErr((e as Error).message || "Chargement impossible.");
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  async function save(rows: CallHoursInput[]) {
    setSaving(true);
    setMsg(null);
    setErr(null);
    try {
      const r = await authedFetch("/api/v1/voice/call-hours/me", {
        method: "PUT",
        body: JSON.stringify({ hours: rows })
      });
      if (!r.ok) throw new Error(await apiError(r));
      setHours((await r.json()) as CallHoursRow[]);
      setMsg(
        rows.length
          ? "Heures d'appel enregistrées."
          : "Enregistré : tu es joignable en tout temps."
      );
    } catch (e) {
      setErr((e as Error).message || "Échec de l'enregistrement.");
    } finally {
      setSaving(false);
    }
  }

  const mobile = variant === "mobile";
  return (
    <section
      className={`rounded-2xl border border-brand-800 bg-brand-900 ${
        mobile ? "p-4" : "p-5"
      }`}
    >
      {mobile ? (
        <p className="flex items-center gap-2 text-xs uppercase tracking-wider text-white/50">
          <Clock className="h-3.5 w-3.5" /> Mes heures d&apos;appel
        </p>
      ) : (
        <h2 className="text-sm font-semibold uppercase tracking-wider text-accent-500">
          Mes heures d&apos;appel
        </h2>
      )}
      <p className="mt-1 text-xs text-white/50">
        Quand un appel t&apos;est transféré (secrétaire Léa, suivi de chantier,
        responsable de dossier), il ne te sonne que pendant ces plages. Hors
        plage, il passe à la personne suivante ou en boîte vocale. C&apos;est
        ton mobile inscrit au profil qui sonne.
      </p>
      <div className="mt-4">
        {hours === null ? (
          <Loader2 className="h-4 w-4 animate-spin text-white/40" />
        ) : (
          <CallHoursEditor hours={hours} onSave={save} saving={saving} />
        )}
      </div>
      {msg ? (
        <p className="mt-3 rounded-md border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-xs text-emerald-300">
          {msg}
        </p>
      ) : null}
      {err ? (
        <p className="mt-3 rounded-md border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
          {err}
        </p>
      ) : null}
    </section>
  );
}
