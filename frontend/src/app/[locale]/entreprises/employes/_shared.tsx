"use client";

/**
 * Section « Employés » du pôle Entreprises — éléments partagés par les
 * onglets (Équipe · Tâches · Feuilles de temps · Suivi du temps · Agenda).
 *
 *   - types des réponses de /api/v1/entreprises/employes ;
 *   - contexte `useSectionEmployes()` (équipe chargée une fois dans le
 *     layout, employé sélectionné via ?employe=<user_id>) ;
 *   - helpers de dates / heures (fr-CA) et petits composants communs.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState
} from "react";
import { UserSearch } from "lucide-react";

import { authedFetch } from "@/lib/auth";
import { colorClassesForUser } from "@/lib/profile-colors";

// ── Types API ──────────────────────────────────────────────────────────

export type EvenementOut = {
  id: number;
  title: string;
  description: string | null;
  location: string | null;
  start_at: string;
  end_at: string | null;
  all_day: boolean;
  event_type: string;
  scope: string;
  modifiable: boolean;
};

export type EmployeZoneOut = {
  id: number;
  display_name: string;
  email: string;
  role: string;
  type: "construction" | "autre";
  volets: string[];
  employe_id: number | null;
  profile_color: string | null;
  has_avatar: boolean;
  taches_ouvertes: number;
  taches_terminees_30j: number;
  heures_periode: number;
  feuille_statut: string | null;
  prochain_evenement: EvenementOut | null;
};

// ── Contexte de section ────────────────────────────────────────────────

export type SectionEmployesCtx = {
  equipe: EmployeZoneOut[];
  loading: boolean;
  error: string | null;
  /** Employé courant (?employe=<id>) — null = toute l'équipe. */
  selected: EmployeZoneOut | null;
  /** Id lu dans l'URL, même si l'employé n'est pas (encore) dans la liste. */
  selectedId: number | null;
  setSelected: (id: number | null) => void;
  inclureAdmins: boolean;
  setInclureAdmins: (v: boolean) => void;
  reload: () => Promise<void>;
};

export const SectionEmployesContext = createContext<SectionEmployesCtx>({
  equipe: [],
  loading: true,
  error: null,
  selected: null,
  selectedId: null,
  setSelected: () => {},
  inclureAdmins: false,
  setInclureAdmins: () => {},
  reload: async () => {}
});

export function useSectionEmployes(): SectionEmployesCtx {
  return useContext(SectionEmployesContext);
}

/** Charge l'équipe (GET /entreprises/employes). `loading` n'est vrai que
 *  pour le premier chargement — un `reload()` rafraîchit en silence. */
export function useEmployesEquipe(inclureAdmins: boolean): {
  equipe: EmployeZoneOut[];
  loading: boolean;
  error: string | null;
  reload: () => Promise<void>;
} {
  const [equipe, setEquipe] = useState<EmployeZoneOut[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const loadedOnce = useRef(false);

  const reload = useCallback(async () => {
    if (!loadedOnce.current) setLoading(true);
    setError(null);
    try {
      const r = await authedFetch(
        `/api/v1/entreprises/employes?inclure_admins=${inclureAdmins ? "true" : "false"}`
      );
      if (!r.ok) throw new Error((await r.text()) || `Erreur ${r.status}`);
      setEquipe((await r.json()) as EmployeZoneOut[]);
      loadedOnce.current = true;
    } catch (e) {
      setError((e as Error).message || "Chargement impossible");
    } finally {
      setLoading(false);
    }
  }, [inclureAdmins]);

  useEffect(() => {
    void reload();
  }, [reload]);

  return { equipe, loading, error, reload };
}

// ── Classes communes (variables QG remappées dans les deux thèmes) ─────

export const CARD =
  "rounded-2xl border border-[var(--qg-border)] bg-[var(--qg-card-bg)] p-5";
export const INPUT =
  "w-full rounded-lg border border-[var(--qg-border)] bg-[var(--qg-bg)] px-3 py-2 text-sm text-[var(--qg-text)] outline-none focus:border-[var(--qg-accent)] disabled:opacity-60";
export const LABEL =
  "mb-1 block text-[11px] font-semibold uppercase tracking-wider text-[var(--qg-text-soft)]";
export const BTN_PRIMARY =
  "btn-accent btn-sm inline-flex items-center gap-1.5 disabled:cursor-not-allowed disabled:opacity-40";
export const BTN_GHOST =
  "btn-secondary btn-sm inline-flex items-center gap-1.5 disabled:cursor-not-allowed disabled:opacity-40";
export const ERROR_BOX =
  "rounded-md border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-300";
export const SUCCESS_BOX =
  "rounded-md border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-sm text-emerald-300";

// ── Dates / heures ─────────────────────────────────────────────────────

export const PERIODE_JOURS = 14;

const MOIS = [
  "janvier", "février", "mars", "avril", "mai", "juin",
  "juillet", "août", "septembre", "octobre", "novembre", "décembre"
];

/** « YYYY-MM-DD » → Date locale (évite le décalage UTC d'un `new Date(iso)`). */
export function parseISODate(d: string): Date {
  const [y, m, day] = d.split("-").map((x) => parseInt(x, 10));
  return new Date(y, m - 1, day);
}

/** Date locale → « YYYY-MM-DD ». */
export function ymd(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

export function todayISO(): string {
  return ymd(new Date());
}

export function addDaysISO(d: string, n: number): string {
  const dt = parseISODate(d);
  dt.setDate(dt.getDate() + n);
  return ymd(dt);
}

/** « 6 – 19 octobre 2026 » / « 28 sept. – 11 octobre 2026 ». */
export function formatPeriod(start: string, end: string): string {
  const s = parseISODate(start);
  const e = parseISODate(end);
  const sameYear = s.getFullYear() === e.getFullYear();
  const sameMonth = sameYear && s.getMonth() === e.getMonth();
  if (sameMonth) {
    return `${s.getDate()} – ${e.getDate()} ${MOIS[e.getMonth()]} ${e.getFullYear()}`;
  }
  if (sameYear) {
    return `${s.getDate()} ${MOIS[s.getMonth()]} – ${e.getDate()} ${MOIS[e.getMonth()]} ${e.getFullYear()}`;
  }
  return `${s.getDate()} ${MOIS[s.getMonth()]} ${s.getFullYear()} – ${e.getDate()} ${MOIS[e.getMonth()]} ${e.getFullYear()}`;
}

/** « YYYY-MM-DD » → « lun. 6 oct. ». */
export function formatDateCourte(iso: string): string {
  return parseISODate(iso).toLocaleDateString("fr-CA", {
    weekday: "short",
    day: "numeric",
    month: "short"
  });
}

/** Date complète d'un jour (fr-CA) : « lundi 6 octobre 2026 ». */
export function formatJourLong(d: Date): string {
  return d.toLocaleDateString("fr-CA", {
    weekday: "long",
    day: "numeric",
    month: "long",
    year: "numeric"
  });
}

export function formatHeure(iso: string): string {
  return new Date(iso).toLocaleTimeString("fr-CA", {
    hour: "2-digit",
    minute: "2-digit"
  });
}

/** Heures décimales → « 7 h 30 » (0 → « 0 h 00 », null → « — »). */
export function fmtHm(h: number | null | undefined): string {
  if (h == null) return "—";
  const totalMin = Math.round(h * 60);
  const hh = Math.floor(totalMin / 60);
  const mm = totalMin % 60;
  return `${hh} h ${String(mm).padStart(2, "0")}`;
}

/** Quand d'un événement : « mar. 7 oct. · 09:00 → 10:30 » ou « Toute la
 *  journée » pour les événements all_day. */
export function formatEvenementQuand(ev: {
  start_at: string;
  end_at: string | null;
  all_day: boolean;
}): string {
  const s = new Date(ev.start_at);
  const dateFmt = s.toLocaleDateString("fr-CA", {
    weekday: "short",
    day: "numeric",
    month: "short"
  });
  if (ev.all_day) return `${dateFmt} · toute la journée`;
  const startHm = formatHeure(ev.start_at);
  if (!ev.end_at) return `${dateFmt} · ${startHm}`;
  const e = new Date(ev.end_at);
  const sameDay = e.toDateString() === s.toDateString();
  return sameDay
    ? `${dateFmt} · ${startHm} → ${formatHeure(ev.end_at)}`
    : `${dateFmt} · ${startHm} → ${e.toLocaleDateString("fr-CA", {
        day: "numeric",
        month: "short"
      })} ${formatHeure(ev.end_at)}`;
}

// ── Libellés ───────────────────────────────────────────────────────────

export const TYPES_EVENEMENT: Array<{ value: string; label: string }> = [
  { value: "reunion", label: "Réunion" },
  { value: "tournage", label: "Tournage" },
  { value: "rdv", label: "Rendez-vous" },
  { value: "formation", label: "Formation" },
  { value: "autre", label: "Autre" }
];

/** Libellé d'un type d'événement, y compris ceux de l'agenda Construction
 *  (chantier, visite, livraison, congé…) qui peuvent apparaître ici. */
export function libelleTypeEvenement(t: string): string {
  const connu = TYPES_EVENEMENT.find((o) => o.value === t);
  if (connu) return connu.label;
  const construction: Record<string, string> = {
    chantier: "Chantier",
    visite: "Visite",
    livraison: "Livraison",
    conge: "Congé"
  };
  return construction[t] || "Autre";
}

export const ROLE_LABEL: Record<string, string> = {
  owner: "Propriétaire",
  admin: "Admin",
  manager: "Gestionnaire",
  employee: "Employé"
};

const VOLET_LABEL: Record<string, string> = {
  construction: "Construction",
  entreprises: "Entreprises",
  immobilier: "Immobilier",
  prospection: "Prospection",
  investisseur: "Investisseur",
  developpement_logiciel: "Dév. logiciel",
  comptabilite: "Comptabilité",
  courtage: "Courtage"
};

export function libelleVolet(v: string): string {
  if (VOLET_LABEL[v]) return VOLET_LABEL[v];
  const s = v.replace(/_/g, " ");
  return s.charAt(0).toUpperCase() + s.slice(1);
}

const FEUILLE_STATUT: Record<string, { label: string; cls: string }> = {
  brouillon: { label: "Brouillon", cls: "badge-neutral" },
  soumis: { label: "Soumis", cls: "badge-amber" },
  approuve: { label: "Approuvé", cls: "badge-emerald" },
  vide: { label: "Vide", cls: "badge-neutral" }
};

// ── Composants communs ─────────────────────────────────────────────────

/** Pastille « Construction » / « Autre » (fond coloré, remappé en clair). */
export function TypeEmployeBadge({ type }: { type: string }) {
  const construction = type === "construction";
  return (
    <span className={`badge ${construction ? "badge-sky" : "badge-violet"}`}>
      {construction ? "Construction" : "Autre"}
    </span>
  );
}

/** Statut de feuille de temps (brouillon / soumis / approuvé / vide). */
export function FeuilleStatutBadge({ statut }: { statut: string | null }) {
  const meta = FEUILLE_STATUT[statut || "vide"] || FEUILLE_STATUT.vide;
  return <span className={`badge ${meta.cls}`}>{meta.label}</span>;
}

function initiales(nom: string, email: string): string {
  const parts = nom.trim().split(/\s+/).filter(Boolean);
  if (parts.length >= 2) {
    return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
  }
  if (parts.length === 1 && parts[0]) return parts[0][0].toUpperCase();
  return (email[0] || "?").toUpperCase();
}

/** Avatar : photo de profil si disponible, sinon initiales sur la couleur
 *  de profil (palette src/lib/profile-colors.ts). */
export function EmployeAvatar({
  employe,
  size = 40
}: {
  employe: Pick<
    EmployeZoneOut,
    "id" | "display_name" | "email" | "profile_color" | "has_avatar"
  >;
  size?: number;
}) {
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => {
    let revoke: string | null = null;
    let cancelled = false;
    if (!employe.has_avatar) {
      setUrl(null);
      return;
    }
    void (async () => {
      try {
        const r = await authedFetch(`/api/v1/auth/users/${employe.id}/avatar`);
        if (!r.ok || cancelled) return;
        const blob = await r.blob();
        const u = URL.createObjectURL(blob);
        revoke = u;
        if (!cancelled) setUrl(u);
      } catch {
        /* pas d'avatar → initiales */
      }
    })();
    return () => {
      cancelled = true;
      if (revoke) URL.revokeObjectURL(revoke);
    };
  }, [employe.id, employe.has_avatar]);

  const dim = `${size}px`;
  if (url) {
    return (
      // eslint-disable-next-line @next/next/no-img-element
      <img
        src={url}
        alt=""
        className="flex-shrink-0 rounded-full object-cover"
        style={{ width: dim, height: dim }}
      />
    );
  }
  return (
    <span
      className={`flex flex-shrink-0 items-center justify-center rounded-full font-bold ${colorClassesForUser(
        employe.profile_color
      )}`}
      style={{ width: dim, height: dim, fontSize: `${Math.round(size * 0.38)}px` }}
    >
      {initiales(employe.display_name, employe.email)}
    </span>
  );
}

/** Invite à choisir un employé (onglets qui en exigent un). */
export function InviteChoisirEmploye({ message }: { message: string }) {
  return (
    <div className="rounded-xl border border-[var(--qg-border)] bg-[var(--qg-card-bg)] px-6 py-12 text-center">
      <UserSearch className="mx-auto h-8 w-8 text-[var(--qg-text-faint)]" />
      <p className="mt-3 text-sm text-[var(--qg-text-muted)]">{message}</p>
      <p className="mt-1 text-xs text-[var(--qg-text-soft)]">
        Utilise le sélecteur « Employé » en haut de la section.
      </p>
    </div>
  );
}

/** Chargement centré (même rendu que les pages voisines du pôle). */
export function Chargement() {
  return (
    <div className="flex min-h-[200px] items-center justify-center rounded-xl border border-[var(--qg-border)] bg-[var(--qg-card-bg)]">
      <span className="h-5 w-5 animate-spin rounded-full border-2 border-[var(--qg-accent)] border-t-transparent" />
    </div>
  );
}

/** Lit le détail d'une erreur HTTP (FastAPI : {detail}) pour l'afficher. */
export async function lireErreur(r: Response): Promise<string> {
  const texte = await r.text().catch(() => "");
  try {
    const j = JSON.parse(texte) as { detail?: unknown };
    if (typeof j.detail === "string") return j.detail;
    if (j.detail) return JSON.stringify(j.detail);
  } catch {
    /* pas du JSON */
  }
  return texte || `Erreur ${r.status}`;
}
