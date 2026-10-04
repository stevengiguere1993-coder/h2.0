/**
 * Zone employés « autre » (/m) — helpers partagés par l'accueil, les
 * tâches personnelles et la feuille de temps : formats fr-CA, libellés et
 * types des réponses d'API. Volontairement sans JSX.
 */

// ── Types d'API ────────────────────────────────────────────────────────

/** GET /mobile/agenda — événement de l'employé connecté. */
export type EventMini = {
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

/** GET /entreprises/mes-taches — tâche personnelle (MaTacheOut). */
export type MaTache = {
  id: number;
  title: string;
  description: string | null;
  status: string;
  priority: string;
  due_date: string | null;
  completed_at: string | null;
  entreprise_id: number;
  entreprise_name: string;
  entreprise_color: string | null;
  created_by_user_id: number | null;
  created_at: string;
  updated_at: string;
  position: number;
  assignee_user_ids: number[];
  peut_supprimer: boolean;
};

/** GET /entreprises/mes-taches/entreprises — entreprise choisissable. */
export type EntrepriseChoix = {
  id: number;
  name: string;
  color_accent: string | null;
};

/** Sous-ensemble de TimesheetDetail utile à la zone employés. */
export type TimesheetDetail = {
  id: number;
  user_id: number;
  period_start: string;
  period_end: string;
  jours_dates: string[];
  status: string;
  is_self: boolean;
  can_edit: boolean;
  can_approve: boolean;
  is_manager: boolean;
  lignes: Array<{ company_id: number; label: string; total: number }>;
  total_heures: number;
  mode_taches?: boolean;
  taches?: Array<{
    id: number;
    day_index: number;
    company_id: number;
    company_label: string;
    entreprise_tache_id?: number | null;
    title: string;
    hours: number;
  }>;
};

// ── Libellés ───────────────────────────────────────────────────────────

/** Types d'événements affichés en étiquette (agenda Construction +
 *  événements planifiés depuis la section Employés du QG). */
export const EVENT_TYPE_LABELS: Record<string, string> = {
  reunion: "Réunion",
  tournage: "Tournage",
  visite: "Visite",
  livraison: "Livraison",
  conge: "Congé",
  rdv: "Rendez-vous",
  formation: "Formation",
  autre: "Autre"
};

/** Types planifiés depuis la section Employés : pas d'intervention
 *  Construction derrière, la carte agenda reste informative. */
export const ZONE_EVENT_TYPES: ReadonlySet<string> = new Set([
  "reunion",
  "tournage",
  "rdv",
  "formation",
  "autre"
]);

/** Statut d'une feuille de temps → libellé + classes de badge (toutes
 *  remappées pour le thème clair dans globals.css). */
export const TIMESHEET_STATUS: Record<string, { label: string; cls: string }> =
  {
    brouillon: {
      label: "Brouillon",
      cls: "border-brand-700 bg-brand-900 text-white/70"
    },
    soumis: {
      label: "Soumise",
      cls: "border-amber-500/40 bg-amber-500/10 text-amber-300"
    },
    approuve: {
      label: "Approuvée",
      cls: "border-emerald-500/40 bg-emerald-500/10 text-emerald-300"
    }
  };

export function timesheetStatus(status: string): { label: string; cls: string } {
  return (
    TIMESHEET_STATUS[status] || {
      label: status || "—",
      cls: "border-brand-700 bg-brand-900 text-white/70"
    }
  );
}

// ── Dates ──────────────────────────────────────────────────────────────

const MONTHS_LONG = [
  "janvier",
  "février",
  "mars",
  "avril",
  "mai",
  "juin",
  "juillet",
  "août",
  "septembre",
  "octobre",
  "novembre",
  "décembre"
];

/** « YYYY-MM-DD » → Date LOCALE (new Date("2026-10-06") serait UTC et
 *  reculerait d'un jour à Montréal). */
export function parseISO(d: string): Date {
  const [y, m, day] = d.split("-").map((x) => parseInt(x, 10));
  return new Date(y, m - 1, day);
}

export function toISODate(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

export function addDaysISO(iso: string, n: number): string {
  const dt = parseISO(iso);
  dt.setDate(dt.getDate() + n);
  return toISODate(dt);
}

/** « 6 – 19 octobre 2026 » / « 28 sept. – 11 octobre 2026 ». */
export function formatPeriod(start: string, end: string): string {
  const s = parseISO(start);
  const e = parseISO(end);
  const sameYear = s.getFullYear() === e.getFullYear();
  const sameMonth = sameYear && s.getMonth() === e.getMonth();
  if (sameMonth) {
    return `${s.getDate()} – ${e.getDate()} ${MONTHS_LONG[e.getMonth()]} ${e.getFullYear()}`;
  }
  if (sameYear) {
    return `${s.getDate()} ${MONTHS_LONG[s.getMonth()]} – ${e.getDate()} ${MONTHS_LONG[e.getMonth()]} ${e.getFullYear()}`;
  }
  return `${s.getDate()} ${MONTHS_LONG[s.getMonth()]} ${s.getFullYear()} – ${e.getDate()} ${MONTHS_LONG[e.getMonth()]} ${e.getFullYear()}`;
}

/** « lun. 6 oct. » à partir d'une date ISO (jour). */
export function fmtDayShort(iso: string): string {
  return parseISO(iso).toLocaleDateString("fr-CA", {
    weekday: "short",
    day: "numeric",
    month: "short"
  });
}

/** « 06 oct. » pour une échéance ; vide si absente. */
export function fmtDate(iso: string | null): string {
  if (!iso) return "";
  return parseISO(iso).toLocaleDateString("fr-CA", {
    day: "2-digit",
    month: "short"
  });
}

export function isOverdue(due: string | null): boolean {
  if (!due) return false;
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  return parseISO(due) < today;
}

export function formatDayLong(d: Date): string {
  return d.toLocaleDateString("fr-CA", {
    weekday: "long",
    day: "numeric",
    month: "long",
    year: "numeric"
  });
}

/** « mar. 7 oct. · 09:00 → 10:30 » (événement) ; « Journée » si all-day. */
export function formatEventWhen(e: {
  start_at: string;
  end_at: string | null;
  all_day: boolean;
}): string {
  const s = new Date(e.start_at);
  const dateFmt = s.toLocaleDateString("fr-CA", {
    weekday: "short",
    day: "numeric",
    month: "short"
  });
  if (e.all_day) return `${dateFmt} · Journée`;
  const startHm = s.toLocaleTimeString("fr-CA", {
    hour: "2-digit",
    minute: "2-digit"
  });
  if (!e.end_at) return `${dateFmt} · ${startHm}`;
  const end = new Date(e.end_at);
  const endHm = end.toLocaleTimeString("fr-CA", {
    hour: "2-digit",
    minute: "2-digit"
  });
  return end.toDateString() === s.toDateString()
    ? `${dateFmt} · ${startHm} → ${endHm}`
    : `${dateFmt} · ${startHm} …`;
}

// ── Nombres / textes ───────────────────────────────────────────────────

/** Heures décimales → « 7 h 30 » (plus lisible qu'un décimal). */
export function fmtHm(h: number | null | undefined): string {
  if (h == null) return "—";
  const totalMin = Math.round(h * 60);
  const hh = Math.floor(totalMin / 60);
  const mm = totalMin % 60;
  return `${hh} h ${String(mm).padStart(2, "0")}`;
}

export function firstName(full: string | undefined | null): string {
  if (!full) return "";
  return full.split(" ")[0] || full;
}

/** Message d'erreur lisible à partir d'une réponse FastAPI
 *  ({ detail: "…" } ou liste d'erreurs de validation). */
export async function readApiError(
  res: Response,
  fallback: string
): Promise<string> {
  try {
    const txt = await res.text();
    if (!txt) return fallback;
    try {
      const body = JSON.parse(txt) as { detail?: unknown };
      if (typeof body.detail === "string") return body.detail;
      if (Array.isArray(body.detail)) {
        const msgs = body.detail
          .map((d) =>
            d && typeof d === "object" && "msg" in d
              ? String((d as { msg: unknown }).msg)
              : ""
          )
          .filter(Boolean);
        if (msgs.length) return msgs.join(" · ");
      }
    } catch {
      /* texte brut */
    }
    return txt.length > 200 ? fallback : txt;
  } catch {
    return fallback;
  }
}
