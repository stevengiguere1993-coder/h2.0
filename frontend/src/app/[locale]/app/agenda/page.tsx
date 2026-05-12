"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
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
import { Link } from "@/i18n/navigation";
import { useAppLayout } from "../layout";
import { authedFetch } from "@/lib/auth";
import { useConfirm } from "@/components/confirm-dialog";

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
  // Volet auquel appartient l'event. Construction par défaut (legacy).
  // Si "prospection" : event masqué en bloc opaque « Indisponible » ici.
  scope?: "construction" | "prospection";
  lead_id?: number | null;
  assignee_user_id?: number | null;
};

/**
 * Masque un event Prospection en bloc opaque pour la vue Construction.
 * Préserve les timestamps + assignations pour qu'il s'affiche au bon
 * endroit, mais efface tous les détails (titre, description, lieu,
 * lien projet/lead).
 */
function maskProspectionEvent(e: AgendaEvent): AgendaEvent {
  if (e.scope !== "prospection") return e;
  return {
    ...e,
    title: "Indisponible",
    description: null,
    location: null,
    project_id: null,
    lead_id: null,
    event_type: "busy"
  };
}

type Project = {
  id: number;
  name: string;
  status: string;
  start_date: string | null;
  end_date: string | null;
  address?: string | null;
  members?: Array<{ employe_id: number }> | null;
};
type Employe = { id: number; full_name: string };
type Phase = {
  id: number;
  project_id: number;
  name: string;
  position: number;
  start_date: string | null;
  start_time: string | null;
  duration_days: number | null;
  assignee_employe_id: number | null;
  assignee_sous_traitant_id: number | null;
  assignee_employe_ids?: number[];
  assignee_sous_traitant_ids?: number[];
};

const TYPE_LABELS: Record<string, string> = {
  chantier: "Chantier",
  visite: "Visite",
  reunion: "Réunion",
  livraison: "Livraison",
  conge: "Congé / vacances",
  busy: "Indisponible",
  autre: "Autre"
};

/**
 * Couleur déterministe et bien spread pour chaque projet.
 *
 * Utilise le « golden ratio conjugate » comme multiplicateur sur
 * project_id pour distribuer les teintes uniformément sur le cercle
 * chromatique. Conséquence : deux projets différents (même IDs
 * consécutifs) auront toujours des couleurs visuellement distinctes,
 * et la couleur d'un projet reste stable d'une session à l'autre.
 */
function projectColor(projectId: number | null | undefined): {
  hue: number;
  bg: string; // bande pleine, lisible sur fond clair ou sombre
  border: string; // contour plus foncé
  text: string; // texte sur la bande (blanc cassé pour contraste)
  solid: string; // couleur pleine (events ponctuels, légende)
} {
  if (!projectId) {
    return {
      hue: 0,
      bg: "rgb(71, 85, 105)", // slate-600
      border: "rgb(51, 65, 85)", // slate-700
      text: "#ffffff",
      solid: "rgb(71, 85, 105)"
    };
  }
  // 137.508 = 360 / phi → spread maximal des teintes (golden ratio).
  // On évite les rouges (340°-360° et 0°-20°) qui sont réservés aux
  // non-disponibilités (congés, busy). On replie cette plage sur le
  // reste du cercle (320° de plage utile : 20° → 340°).
  const raw = (projectId * 137.508) % 320;
  const hue = Math.floor(20 + raw);
  return {
    hue,
    bg: `hsl(${hue}, 65%, 42%)`, // saturé, lisible sur blanc et noir
    border: `hsl(${hue}, 70%, 32%)`,
    text: "#ffffff",
    solid: `hsl(${hue}, 65%, 50%)`
  };
}

const TYPE_CLASS: Record<string, string> = {
  chantier: "bg-accent-500/20 text-accent-300 border-accent-500/40",
  conge: "bg-orange-500/20 text-orange-300 border-orange-500/40",
  visite: "bg-blue-500/20 text-blue-300 border-blue-500/40",
  reunion: "bg-violet-500/20 text-violet-300 border-violet-500/40",
  livraison: "bg-emerald-500/20 text-emerald-300 border-emerald-500/40",
  // Bloc opaque (event Prospection masqué). Gris neutre + curseur
  // par défaut (pas cliquable, géré dans onEventClick).
  busy: "bg-brand-800/70 text-white/40 border-white/15 cursor-default",
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

// Parse "YYYY-MM-DD" en Date locale (sinon JS prend UTC minuit, ce qui
// décale la date d'un jour à Montréal).
function parseLocalDate(s: string): Date {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(s);
  if (m) {
    return new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
  }
  return new Date(s);
}

// Monday of the ISO week containing `d`, at local midnight.
function mondayOf(d: Date): Date {
  const m = new Date(d.getFullYear(), d.getMonth(), d.getDate());
  const w = (m.getDay() + 6) % 7; // Mon=0 ... Sun=6
  m.setDate(m.getDate() - w);
  return m;
}

// Difference in whole days between two dates (ignoring DST).
function diffDays(a: Date, b: Date): number {
  const MS = 24 * 60 * 60 * 1000;
  const da = new Date(a.getFullYear(), a.getMonth(), a.getDate()).getTime();
  const db = new Date(b.getFullYear(), b.getMonth(), b.getDate()).getTime();
  return Math.round((db - da) / MS);
}

function dayLabel(d: Date): string {
  const s = d.toLocaleDateString("fr-CA", {
    weekday: "long",
    day: "numeric",
    month: "long",
    year: "numeric"
  });
  return s.charAt(0).toUpperCase() + s.slice(1);
}

function timelineRangeLabel(ref: Date, span: number): string {
  const start = mondayOf(ref);
  const end = new Date(start);
  end.setDate(end.getDate() + span - 1);
  const fmt = (d: Date) =>
    d.toLocaleDateString("fr-CA", {
      day: "numeric",
      month: "short"
    });
  return `${fmt(start)} → ${fmt(end)}`;
}

export default function AgendaPage() {
  const { onOpenSidebar } = useAppLayout();
  const [ref, setRef] = useState(() => new Date());
  // Le `view` est persisté dans l'URL (?view=month) pour que le back
  // navigateur restaure la même vue après être allé sur un projet.
  const [view, setView] = useState<
    "day" | "week" | "month" | "list" | "by-project" | "by-person"
  >(() => {
    if (typeof window === "undefined") return "month";
    const v = new URLSearchParams(window.location.search).get("view");
    if (
      v === "day" ||
      v === "week" ||
      v === "month" ||
      v === "list" ||
      v === "by-project" ||
      v === "by-person"
    ) {
      return v;
    }
    return "month";
  });

  // Quand le user change de vue, on met à jour l'URL (replaceState
  // pour ne pas polluer le back-stack — le back ramène à la page
  // d'origine, pas à la vue précédente).
  useEffect(() => {
    if (typeof window === "undefined") return;
    const url = new URL(window.location.href);
    if (url.searchParams.get("view") !== view) {
      url.searchParams.set("view", view);
      window.history.replaceState(null, "", url.toString());
    }
  }, [view]);
  // Timeline span (days) for the Gantt-like views.
  const [spanDays, setSpanDays] = useState<7 | 14 | 28>(14);

  const [events, setEvents] = useState<AgendaEvent[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [employes, setEmployes] = useState<Employe[]>([]);
  const [phases, setPhases] = useState<Phase[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Filters
  const [fType, setFType] = useState("");
  const [fProject, setFProject] = useState("");
  const [fAssignee, setFAssignee] = useState("");

  // Modal state
  // Modal de création/édition. Pour les nouvelles créations on peut
  // pré-remplir l'employé assigné (depuis la grille « Par personne »
  // par exemple).
  const [modal, setModal] = useState<
    | AgendaEvent
    | { date: Date; assigneeId?: number | null }
    | null
  >(null);

  // Projets dont les phases / événements sont déployés dans la vue
  // mois. Par défaut tout est replié — le calendrier ne montre que les
  // bandes de chantier (« 🛠️ Cuisine Quévillon »). Click sur la bande
  // → on ajoute le project_id au set → les phases/events de ce projet
  // s'affichent. Re-click → on retire → tout se replie.
  const [expandedProjects, setExpandedProjects] = useState<Set<number>>(
    new Set()
  );
  const toggleProject = useCallback((projectId: number) => {
    setExpandedProjects((prev) => {
      const next = new Set(prev);
      if (next.has(projectId)) next.delete(projectId);
      else next.add(projectId);
      return next;
    });
  }, []);

  // Capture le geste « back » mobile (swipe) quand la modal est ouverte :
  // au lieu de naviguer vers la page précédente (qui pourrait être
  // /app/projets), on ferme la modal d'abord. On push une entrée
  // d'historique à l'ouverture, et on écoute popstate.
  useEffect(() => {
    if (!modal) return;
    if (typeof window === "undefined") return;
    const stateMarker = { __agendaModal: Date.now() };
    window.history.pushState(stateMarker, "");
    const onPop = () => {
      // popstate déclenché par le swipe/back → on ferme la modal
      // sans laisser le browser naviguer vers la page précédente.
      setModal(null);
    };
    window.addEventListener("popstate", onPop);
    return () => {
      window.removeEventListener("popstate", onPop);
      // Si la modal a été fermée par un autre chemin (close button,
      // save), on retire le marqueur d'historique pour ne pas laisser
      // de back-stack pollué.
      if (window.history.state && window.history.state.__agendaModal === stateMarker.__agendaModal) {
        window.history.back();
      }
    };
  }, [modal]);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const [evRes, prRes, empRes, phRes] = await Promise.all([
          authedFetch("/api/v1/agenda?limit=500"),
          authedFetch("/api/v1/projects?limit=200"),
          authedFetch("/api/v1/employes?limit=200&volet=construction"),
          authedFetch("/api/v1/phases")
        ]);
        if (!evRes.ok) throw new Error(`http_${evRes.status}`);
        const rawEvs = (await evRes.json()) as AgendaEvent[];
        // Masque les events Prospection en blocs opaques (privacy
        // inter-volet : la Construction voit qu'il y a un blocage de
        // calendrier mais sans détails).
        const evs = rawEvs.map(maskProspectionEvent);
        const prs = prRes.ok ? ((await prRes.json()) as Project[]) : [];
        const emps = empRes.ok ? ((await empRes.json()) as Employe[]) : [];
        const phs = phRes.ok ? ((await phRes.json()) as Phase[]) : [];
        if (!cancelled) {
          setEvents(evs);
          setProjects(prs);
          setEmployes(emps);
          setPhases(phs);
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

  // Phases du projet → événements virtuels (read-only) qui apparaissent
  // dans toutes les vues calendrier/list/timeline. Permet de voir la
  // planification du projet dans l'agenda chantier global, pas seulement
  // dans l'onglet Planification du projet.
  const phaseAsEvents = useMemo<AgendaEvent[]>(() => {
    return phases
      .filter((p) => p.start_date && p.duration_days && p.duration_days > 0)
      .map((p) => {
        // Bornes de jour pour les phases « journée complète ». Si
        // start_time est défini, la phase est un créneau horaire :
        // duration_days en jours-travail (8 h = 1 jour).
        const dur = Math.max(0.125, Number(p.duration_days) || 1);
        const t = (p.start_time || "00:00:00").slice(0, 8);
        const sMs = new Date(`${p.start_date!}T${t}`).getTime();
        const eMs =
          p.start_time != null
            ? sMs + dur * 8 * 3_600_000
            : sMs + dur * 86_400_000;
        const s = new Date(sMs);
        const e = new Date(eMs);
        return {
          id: -p.id, // négatif pour ne pas collisionner avec events réels
          title: `📐 ${p.name}`,
          description: null,
          location: null,
          start_at: s.toISOString(),
          end_at: e.toISOString(),
          all_day: p.start_time == null,
          project_id: p.project_id,
          assignee_id:
            p.assignee_employe_id != null
              ? p.assignee_employe_id
              : null,
          event_type: "phase",
          created_at: s.toISOString()
        } as AgendaEvent;
      });
  }, [phases]);

  const filteredEvents = useMemo(() => {
    return [...events, ...phaseAsEvents].filter((e) => {
      if (fType && e.event_type !== fType) return false;
      if (fProject && String(e.project_id || "") !== fProject) return false;
      if (fAssignee && String(e.assignee_id || "") !== fAssignee) return false;
      return true;
    });
  }, [events, phaseAsEvents, fType, fProject, fAssignee]);

  const grid = useMemo(() => buildMonthGrid(ref), [ref]);

  // For each day, figure out which projects span it (start_date ≤ day ≤ end_date).
  // Active projects are drawn as a colored band at the top of the day cell so
  // the team sees at a glance "there's a project running — need to assign
  // people".
  const projectsByDay = useMemo(() => {
    const map = new Map<string, Project[]>();
    // Les bandes « projet » représentent une plage de chantier. On ne
    // les affiche que quand le filtre type est vide (Tous les types) ou
    // explicitement « chantier » — sinon ça pollue la vue quand on
    // cherche juste ses visites ou ses réunions.
    if (fType && fType !== "chantier") return map;
    // Quand on filtre sur un assigné en particulier, on cache aussi
    // les bandes : elles ne tiennent pas compte de qui est sur quel
    // projet, juste les dates, donc les laisser créerait de fausses
    // alertes rouges sur des projets qui ne concernent pas la
    // personne sélectionnée.
    if (fAssignee) return map;
    const active = projects.filter(
      (p) =>
        p.start_date &&
        p.end_date &&
        (!fProject || String(p.id) === fProject) &&
        p.status !== "archived" &&
        p.status !== "done"
    );
    for (const d of grid) {
      const key = d.toDateString();
      const hits: Project[] = [];
      for (const p of active) {
        // start_date / end_date sont des dates pures (YYYY-MM-DD), il
        // faut les parser en local sinon UTC midnight les recule d'un
        // jour à Montréal (UTC-4/5).
        const ds = parseLocalDate(p.start_date as string);
        const de = parseLocalDate(p.end_date as string);
        const dd = new Date(d.getFullYear(), d.getMonth(), d.getDate());
        if (dd >= ds && dd <= de) hits.push(p);
      }
      if (hits.length > 0) map.set(key, hits);
    }
    return map;
  }, [grid, projects, fProject, fType, fAssignee]);

  // Has the project any assigned employee?  A project band is shown in red
  // when there's still nobody assigned (signal to the user: "assigne une
  // équipe !").  ProjectMember rows aren't exposed on the list endpoint
  // today — we fall back to checking events linked to the project.
  const projectHasTeam = useMemo(() => {
    const map = new Map<number, boolean>();
    for (const p of projects) {
      const hasMembers = (p.members?.length || 0) > 0;
      const hasAssignedEvent = events.some(
        (e) => e.project_id === p.id && e.assignee_id
      );
      // Une phase assignée (à un employé ou un sous-traitant) compte
      // aussi : le projet a au moins une ressource prévue, donc on
      // n'affiche plus la bande rouge ⚠️.
      const hasAssignedPhase = phases.some(
        (ph) =>
          ph.project_id === p.id &&
          ((ph.assignee_employe_ids && ph.assignee_employe_ids.length > 0) ||
            (ph.assignee_sous_traitant_ids &&
              ph.assignee_sous_traitant_ids.length > 0) ||
            ph.assignee_employe_id ||
            ph.assignee_sous_traitant_id)
      );
      map.set(
        p.id,
        hasMembers || hasAssignedEvent || hasAssignedPhase
      );
    }
    return map;
  }, [projects, events, phases]);

  // On sépare événements « mono-jour » (rendus dans la case) des
  // événements « multi-jours » (rendus en bande continue qui traverse
  // les cases, comme les phases de chantier). Les all_day qui couvrent
  // exactement un jour restent dans la case — pas la peine d'en faire
  // une bande.
  const { eventsByDay, multiDayEventsByDay } = useMemo(() => {
    const single = new Map<string, AgendaEvent[]>();
    const multi = new Map<string, AgendaEvent[]>();
    for (const e of filteredEvents) {
      const s = new Date(e.start_at);
      const endRaw = e.end_at ? new Date(e.end_at) : s;
      const sDay = new Date(
        s.getFullYear(),
        s.getMonth(),
        s.getDate()
      );
      const eDay = new Date(
        endRaw.getFullYear(),
        endRaw.getMonth(),
        endRaw.getDate()
      );
      if (sDay.getTime() === eDay.getTime()) {
        const key = sDay.toDateString();
        const arr = single.get(key) || [];
        arr.push(e);
        single.set(key, arr);
      } else {
        // Chaque jour couvert pointe vers cet event pour l'algo de
        // placement en bandes par semaine.
        const cursor = new Date(sDay);
        while (cursor.getTime() <= eDay.getTime()) {
          const key = cursor.toDateString();
          const arr = multi.get(key) || [];
          arr.push(e);
          multi.set(key, arr);
          cursor.setDate(cursor.getDate() + 1);
        }
      }
    }
    for (const arr of single.values()) {
      arr.sort(
        (a, b) =>
          new Date(a.start_at).getTime() - new Date(b.start_at).getTime()
      );
    }
    return { eventsByDay: single, multiDayEventsByDay: multi };
  }, [filteredEvents]);

  function upsertEvent(saved: AgendaEvent) {
    // Si l'event sauvegardé est un Prospection event (ce qui ne devrait
    // pas arriver depuis la modal Construction, mais sécurité), on le
    // masque avant de le rebrancher dans la liste.
    const masked = maskProspectionEvent(saved);
    setEvents((xs) => {
      const idx = xs.findIndex((x) => x.id === masked.id);
      if (idx === -1) return [...xs, masked];
      const next = xs.slice();
      next[idx] = masked;
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
                if (view === "day") {
                  d.setDate(d.getDate() - 1);
                } else if (view === "week") {
                  d.setDate(d.getDate() - 7);
                } else if (view === "by-project" || view === "by-person") {
                  d.setDate(d.getDate() - spanDays);
                } else {
                  d.setMonth(d.getMonth() - 1);
                }
                setRef(d);
              }}
              className="rounded-md p-1.5 text-white/70 hover:bg-brand-800 hover:text-white"
              aria-label="Période précédente"
            >
              <ChevronLeft className="h-4 w-4" />
            </button>
            <span className="min-w-[180px] px-2 text-center text-sm font-semibold text-white">
              {view === "day"
                ? dayLabel(ref)
                : view === "week"
                  ? timelineRangeLabel(ref, 7)
                  : view === "by-project" || view === "by-person"
                    ? timelineRangeLabel(ref, spanDays)
                    : monthLabel(ref)}
            </span>
            <button
              type="button"
              onClick={() => {
                const d = new Date(ref);
                if (view === "day") {
                  d.setDate(d.getDate() + 1);
                } else if (view === "week") {
                  d.setDate(d.getDate() + 7);
                } else if (view === "by-project" || view === "by-person") {
                  d.setDate(d.getDate() + spanDays);
                } else {
                  d.setMonth(d.getMonth() + 1);
                }
                setRef(d);
              }}
              className="rounded-md p-1.5 text-white/70 hover:bg-brand-800 hover:text-white"
              aria-label="Période suivante"
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
              onChange={(e) =>
                setView(
                  e.target.value as
                    | "month"
                    | "list"
                    | "by-project"
                    | "by-person"
                )
              }
              className="input w-40"
            >
              <option value="day">Journalier</option>
              <option value="week">Hebdomadaire</option>
              <option value="month">Mois</option>
              <option value="list">Liste</option>
              <option value="by-project">Par chantier</option>
              <option value="by-person">Par personne</option>
            </select>
            {view === "by-project" ? (
              <select
                value={String(spanDays)}
                onChange={(e) =>
                  setSpanDays(Number(e.target.value) as 7 | 14 | 28)
                }
                className="input w-28"
              >
                <option value="7">7 jours</option>
                <option value="14">14 jours</option>
                <option value="28">28 jours</option>
              </select>
            ) : null}
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
        ) : view === "day" || view === "week" ? (
          <TimeGridView
            ref={ref}
            days={view === "day" ? 1 : 7}
            events={filteredEvents}
            onSlotClick={(d) => setModal({ date: d })}
            onEventClick={(e) =>
              e.event_type === "busy"
                ? null
                : e.event_type === "phase" && e.project_id
                ? window.location.assign(
                    `/app/projets/${e.project_id}#planification`
                  )
                : setModal(e)
            }
          />
        ) : view === "month" ? (
          <MonthView
            grid={grid}
            ref={ref}
            eventsByDay={eventsByDay}
            multiDayEventsByDay={multiDayEventsByDay}
            projectsByDay={projectsByDay}
            projectHasTeam={projectHasTeam}
            expandedProjects={expandedProjects}
            onToggleProject={toggleProject}
            onDayClick={(d) => setModal({ date: d })}
            onEventClick={(e) =>
              e.event_type === "busy"
                ? null
                : e.event_type === "phase" && e.project_id
                ? window.location.assign(
                    `/app/projets/${e.project_id}#planification`
                  )
                : setModal(e)
            }
          />
        ) : view === "list" ? (
          <ListView
            events={filteredEvents}
            onEventClick={(e) =>
              e.event_type === "busy"
                ? null
                : e.event_type === "phase" && e.project_id
                ? window.location.assign(
                    `/app/projets/${e.project_id}#planification`
                  )
                : setModal(e)
            }
          />
        ) : view === "by-person" ? (
          // Vue « Par personne » : grille hebdomadaire complète de
          // l'équipe (chaque ligne = un employé, chaque colonne = un
          // jour). Style PlanOps : blocs d'assignation colorés par
          // chantier, « Libre » quand vide, sommaire heures en bas.
          <WeeklyTeamGridView
            ref={ref}
            employes={employes}
            events={filteredEvents}
            phases={phases}
            projects={projects}
            onCellClick={(employeId, date) =>
              setModal({ date, assigneeId: employeId })
            }
            onEventClick={(e) =>
              e.event_type === "busy"
                ? null
                : e.event_type === "phase" && e.project_id
                ? window.location.assign(
                    `/app/projets/${e.project_id}#planification`
                  )
                : setModal(e)
            }
          />
        ) : (
          <TimelineView
            mode="project"
            ref={ref}
            spanDays={spanDays}
            events={filteredEvents}
            phases={phases}
            projects={projects}
            employes={employes}
            onEventClick={(e) =>
              e.event_type === "busy"
                ? null
                : e.event_type === "phase" && e.project_id
                ? window.location.assign(
                    `/app/projets/${e.project_id}#planification`
                  )
                : setModal(e)
            }
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
  multiDayEventsByDay,
  projectsByDay,
  projectHasTeam,
  expandedProjects,
  onToggleProject,
  onDayClick,
  onEventClick
}: {
  grid: Date[];
  ref: Date;
  eventsByDay: Map<string, AgendaEvent[]>;
  multiDayEventsByDay: Map<string, AgendaEvent[]>;
  projectsByDay: Map<string, Project[]>;
  projectHasTeam: Map<number, boolean>;
  expandedProjects: Set<number>;
  onToggleProject: (projectId: number) => void;
  onDayClick: (d: Date) => void;
  onEventClick: (e: AgendaEvent) => void;
}) {
  const today = new Date();

  // Découpe la grille en 6 semaines pour dessiner des bandes de projet
  // continues qui traversent plusieurs cases (style Google Calendar).
  // Un projet qui dépasse le dimanche est scindé en 2 bandes — une par
  // semaine. Les chevauchements sont placés sur des pistes distinctes
  // via un algo glouton.
  const weeks = Array.from({ length: 6 }, (_, w) =>
    grid.slice(w * 7, w * 7 + 7)
  );

  // Unifie les bandes hebdomadaires : chantiers (phases de projet)
  // ET événements agenda multi-jours partagent le même système de
  // pistes, avec des couleurs différentes selon le type. Permet de
  // les empiler proprement quand ils se chevauchent.
  type WeekBar =
    | {
        kind: "project";
        key: string;
        project: Project;
        startCol: number;
        endCol: number;
        track: number;
      }
    | {
        kind: "event";
        key: string;
        event: AgendaEvent;
        startCol: number;
        endCol: number;
        track: number;
      };

  const weeksWithBars = weeks.map((week) => {
    type Span = { startCol: number; endCol: number };
    const projectSpans = new Map<number, Span & { project: Project }>();
    const eventSpans = new Map<number, Span & { event: AgendaEvent }>();
    for (let i = 0; i < 7; i++) {
      const d = week[i];
      const key = d.toDateString();
      for (const p of projectsByDay.get(key) || []) {
        const ex = projectSpans.get(p.id);
        if (!ex) {
          projectSpans.set(p.id, { project: p, startCol: i, endCol: i });
        } else {
          ex.endCol = i;
        }
      }
      for (const ev of multiDayEventsByDay.get(key) || []) {
        // Si l'event est lié à un projet et que ce projet n'est PAS
        // dépliée, on cache la bande individuelle — seule la bande
        // chantier reste visible. Click sur la bande → expand.
        if (
          ev.project_id != null &&
          !expandedProjects.has(ev.project_id)
        ) {
          continue;
        }
        const ex = eventSpans.get(ev.id);
        if (!ex) {
          eventSpans.set(ev.id, { event: ev, startCol: i, endCol: i });
        } else {
          ex.endCol = i;
        }
      }
    }

    type Candidate =
      | { kind: "project"; project: Project; startCol: number; endCol: number }
      | { kind: "event"; event: AgendaEvent; startCol: number; endCol: number };

    const candidates: Candidate[] = [
      ...Array.from(projectSpans.values()).map((s) => ({
        kind: "project" as const,
        project: s.project,
        startCol: s.startCol,
        endCol: s.endCol
      })),
      ...Array.from(eventSpans.values()).map((s) => ({
        kind: "event" as const,
        event: s.event,
        startCol: s.startCol,
        endCol: s.endCol
      }))
    ].sort((a, b) =>
      a.startCol !== b.startCol
        ? a.startCol - b.startCol
        : a.endCol - b.endCol
    );

    const trackEnds: number[] = [];
    const placed: WeekBar[] = [];
    for (const c of candidates) {
      let t = -1;
      for (let i = 0; i < trackEnds.length; i++) {
        if (trackEnds[i] < c.startCol) {
          t = i;
          break;
        }
      }
      if (t === -1) {
        t = trackEnds.length;
        trackEnds.push(c.endCol);
      } else {
        trackEnds[t] = c.endCol;
      }
      if (c.kind === "project") {
        placed.push({
          kind: "project",
          key: `p-${c.project.id}`,
          project: c.project,
          startCol: c.startCol,
          endCol: c.endCol,
          track: t
        });
      } else {
        placed.push({
          kind: "event",
          key: `e-${c.event.id}`,
          event: c.event,
          startCol: c.startCol,
          endCol: c.endCol,
          track: t
        });
      }
    }
    return { week, bars: placed, trackCount: trackEnds.length };
  });

  const BAR_HEIGHT = 18;
  const BAR_GAP = 2;
  const BAR_TOP_OFFSET = 30; // sous la pastille de date

  return (
    <div className="overflow-hidden rounded-xl border border-brand-800 bg-brand-900">
      <div className="grid grid-cols-7 border-b border-brand-800 text-xs font-semibold text-white/50">
        {WEEKDAYS.map((w) => (
          <div key={w} className="px-3 py-2 text-center uppercase tracking-wider">
            {w}
          </div>
        ))}
      </div>
      {weeksWithBars.map(({ week, bars, trackCount }, wIdx) => {
        const reservedBarsHeight =
          trackCount > 0 ? trackCount * (BAR_HEIGHT + BAR_GAP) : 0;
        return (
          <div key={wIdx} className="relative grid grid-cols-7">
            {week.map((d, i) => {
              const inMonth = d.getMonth() === ref.getMonth();
              const isToday = sameDay(d, today);
              const allDayEvents = eventsByDay.get(d.toDateString()) || [];
              // Cache les events liés à un projet replié — seuls les
              // events sans projet (réunions, RDV externes) ou ceux
              // dont le projet est déplié restent visibles inline.
              const dayEvents = allDayEvents.filter(
                (e) =>
                  e.project_id == null ||
                  expandedProjects.has(e.project_id)
              );
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

                  {reservedBarsHeight > 0 ? (
                    <div style={{ height: `${reservedBarsHeight}px` }} />
                  ) : null}

                  <div className="mt-1 space-y-0.5">
                    {dayEvents.slice(0, 3).map((e) => {
                      // Couleur du chantier prioritaire — si l'event
                      // est rattaché à un projet, on prend la teinte
                      // unique du projet (cohérent avec les bandes
                      // multi-jours et le reste du calendrier).
                      const pc = e.project_id
                        ? projectColor(e.project_id)
                        : null;
                      const cls = pc
                        ? "block w-full overflow-hidden rounded border px-1 py-0.5 text-left text-[10px] font-medium leading-tight"
                        : `block w-full overflow-hidden rounded border px-1 py-0.5 text-left text-[10px] font-medium leading-tight ${
                            TYPE_CLASS[e.event_type] || TYPE_CLASS.autre
                          }`;
                      const style = pc
                        ? {
                            backgroundColor: pc.bg,
                            borderColor: pc.border,
                            color: pc.text
                          }
                        : undefined;
                      return (
                        <button
                          key={e.id}
                          type="button"
                          onClick={(ev) => {
                            ev.stopPropagation();
                            onEventClick(e);
                          }}
                          title={`${e.title}${
                            !e.all_day ? ` — ${fmtTime(e.start_at)}` : ""
                          }${e.location ? ` · ${e.location}` : ""}`}
                          className={cls}
                          style={style}
                        >
                          <span className="block truncate font-semibold">
                            {e.title}
                          </span>
                          {!e.all_day ? (
                            <span className="block text-[9px] opacity-80">
                              {fmtTime(e.start_at)}
                              {e.end_at ? `–${fmtTime(e.end_at)}` : ""}
                            </span>
                          ) : null}
                        </button>
                      );
                    })}
                  </div>
                </div>
              );
            })}

            {bars.map((bar) => {
              const leftPct = (bar.startCol / 7) * 100;
              const widthPct = ((bar.endCol - bar.startCol + 1) / 7) * 100;
              const top =
                BAR_TOP_OFFSET + bar.track * (BAR_HEIGHT + BAR_GAP);
              const style: React.CSSProperties = {
                left: `calc(${leftPct}% + 2px)`,
                width: `calc(${widthPct}% - 4px)`,
                top: `${top}px`,
                height: `${BAR_HEIGHT}px`
              };

              if (bar.kind === "project") {
                const hasTeam =
                  projectHasTeam.get(bar.project.id) ?? false;
                // Couleur stable et unique par chantier (HSL spread
                // par golden ratio sur project_id). Le marqueur ⚠️
                // signale toujours l'absence d'équipe assignée.
                const c = projectColor(bar.project.id);
                const expanded = expandedProjects.has(bar.project.id);
                return (
                  <button
                    key={bar.key}
                    type="button"
                    onClick={(ev) => {
                      ev.stopPropagation();
                      onToggleProject(bar.project.id);
                    }}
                    title={
                      (expanded
                        ? "Cliquer pour replier"
                        : "Cliquer pour voir les phases & événements") +
                      ` — ${bar.project.name}` +
                      (hasTeam ? "" : " · aucune équipe assignée")
                    }
                    className="absolute z-[2] flex items-center gap-1 overflow-hidden rounded-md border px-1.5 text-left text-[10px] font-bold shadow-sm transition hover:opacity-90"
                    style={{
                      ...style,
                      backgroundColor: c.bg,
                      borderColor: c.border,
                      color: c.text
                    }}
                  >
                    <span className="flex-shrink-0">
                      {expanded ? "▼" : "▶"}
                    </span>
                    <span className="truncate">
                      {hasTeam ? "🛠️" : "⚠️"} {bar.project.name}
                    </span>
                  </button>
                );
              }

              // Événement multi-jours — couleur du chantier si lié à
              // un projet (même couleur que la bande). Sinon couleur
              // par event_type (livraison violet, inspection rouge…).
              const ev = bar.event;
              const projColor = ev.project_id
                ? projectColor(ev.project_id)
                : null;
              const typeClass = projColor
                ? ""
                : TYPE_CLASS[ev.event_type] || TYPE_CLASS.autre;
              return (
                <button
                  key={bar.key}
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    onEventClick(ev);
                  }}
                  title={`${ev.title}${
                    ev.location ? ` · ${ev.location}` : ""
                  }`}
                  className={`absolute z-[2] flex items-center overflow-hidden rounded-md border px-1.5 text-left text-[10px] font-medium shadow-sm ${typeClass}`}
                  style={
                    projColor
                      ? {
                          ...style,
                          backgroundColor: projColor.bg,
                          borderColor: projColor.border,
                          color: projColor.text
                        }
                      : style
                  }
                >
                  <span className="truncate">
                    {!ev.all_day ? `${fmtTime(ev.start_at)} ` : ""}
                    {ev.title}
                  </span>
                </button>
              );
            })}
          </div>
        );
      })}
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
  seed:
    | AgendaEvent
    | { date: Date; assigneeId?: number | null };
  projects: Project[];
  employes: Employe[];
  onClose: () => void;
  onSaved: (e: AgendaEvent) => void;
  onDeleted: (id: number) => void;
}) {
  const existing = "id" in seed ? (seed as AgendaEvent) : null;
  const seedDate = "id" in seed ? null : (seed as { date: Date }).date;
  const seedAssignee =
    "id" in seed
      ? null
      : (seed as { assigneeId?: number | null }).assigneeId ?? null;
  const initialStart = existing
    ? isoLocal(new Date(existing.start_at))
    : isoLocal(seedDate || new Date());
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
    existing?.assignee_id
      ? String(existing.assignee_id)
      : seedAssignee
        ? String(seedAssignee)
        : ""
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
    if (!(await confirm(`Supprimer l'événement « ${existing.title} » ?`))) return;
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
                onChange={(e) => {
                  const newId = e.target.value;
                  setProjectId(newId);
                  // Pré-remplit le lieu avec l'adresse du projet
                  // sélectionné — sauf si l'utilisateur a déjà saisi
                  // quelque chose à la main.
                  if (newId && !location.trim()) {
                    const p = projects.find((x) => String(x.id) === newId);
                    if (p?.address) setLocation(p.address);
                  }
                }}
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

// ---------------------------------------------------------------------------
// TimelineView — Gantt-style grouping by project or by person.
// Shows each event / project phase as a horizontal bar spanning its date
// range. Clicking an event bar opens the edit modal; clicking a phase bar
// navigates to the project's phase planner.
// ---------------------------------------------------------------------------

type TimelineItem = {
  key: string;
  kind: "event" | "phase";
  title: string;
  subtitle: string;
  startIdx: number;
  endIdx: number;
  accent: string; // tailwind background classes
  raw?: AgendaEvent;
  href?: string;
  onClick?: () => void;
};

type TimelineRow = {
  key: string;
  label: string;
  sublabel?: string;
  tone?: string;
  items: TimelineItem[];
};

function assignTracks(items: TimelineItem[]): {
  placed: Array<TimelineItem & { track: number }>;
  trackCount: number;
} {
  const sorted = [...items].sort((a, b) =>
    a.startIdx !== b.startIdx
      ? a.startIdx - b.startIdx
      : a.endIdx - b.endIdx
  );
  const tracksLastEnd: number[] = [];
  const placed: Array<TimelineItem & { track: number }> = [];
  for (const it of sorted) {
    let t = -1;
    for (let i = 0; i < tracksLastEnd.length; i++) {
      if (tracksLastEnd[i] < it.startIdx) {
        t = i;
        break;
      }
    }
    if (t === -1) {
      t = tracksLastEnd.length;
      tracksLastEnd.push(it.endIdx);
    } else {
      tracksLastEnd[t] = it.endIdx;
    }
    placed.push({ ...it, track: t });
  }
  return { placed, trackCount: Math.max(1, tracksLastEnd.length) };
}

function eventAccent(type: string): string {
  switch (type) {
    case "chantier":
      return "bg-accent-500/80 border-accent-400 text-brand-950";
    case "visite":
      return "bg-blue-500/80 border-blue-400 text-white";
    case "reunion":
      return "bg-violet-500/80 border-violet-400 text-white";
    case "livraison":
      return "bg-emerald-500/80 border-emerald-400 text-white";
    case "conge":
      return "bg-orange-500/80 border-orange-400 text-white";
    default:
      return "bg-white/20 border-white/30 text-white";
  }
}

// ─── Vue « Par personne » : grille hebdomadaire équipe × jours ──────
//
// Inspirée du visuel PlanOps. Chaque ligne = un employé, chaque
// colonne = un jour de la semaine en cours. Dans la cellule on liste
// les blocs d'assignation : phases (multi-jour) et événements ponctuels
// où cet employé est dans `assignee_id`/`assignee_employe_ids`. Si
// rien → « Libre » en gris. Click sur cellule vide → modal pour
// assigner à un chantier existant ou créer un événement distinct.
//
// Ligne « Sommaire » en bas : total heures par jour (somme
// duration des phases + 8h all-day events). Cost ajouté plus tard.

function WeeklyTeamGridView({
  ref: refDate,
  employes,
  events,
  phases,
  projects,
  onCellClick,
  onEventClick
}: {
  ref: Date;
  employes: Employe[];
  events: AgendaEvent[];
  phases: Phase[];
  projects: Project[];
  onCellClick: (employeId: number, date: Date) => void;
  onEventClick: (event: AgendaEvent) => void;
}) {
  // Calcule les 7 jours de la semaine (lundi → dimanche) qui
  // contiennent refDate.
  const week = useMemo(() => {
    const monday = new Date(refDate);
    const dow = monday.getDay(); // 0=dim, 1=lun…
    const offset = dow === 0 ? -6 : 1 - dow;
    monday.setDate(monday.getDate() + offset);
    monday.setHours(0, 0, 0, 0);
    const days: Date[] = [];
    for (let i = 0; i < 7; i++) {
      const d = new Date(monday);
      d.setDate(monday.getDate() + i);
      days.push(d);
    }
    return days;
  }, [refDate]);

  const projectById = useMemo(() => {
    const m = new Map<number, Project>();
    projects.forEach((p) => m.set(p.id, p));
    return m;
  }, [projects]);

  function dayLabel(d: Date): string {
    const dow = d.toLocaleDateString("fr-CA", { weekday: "short" });
    const day = d.getDate();
    const month = d.toLocaleDateString("fr-CA", { month: "short" });
    return `${dow} ${day} ${month}`;
  }

  function isSameDay(a: Date, b: Date): boolean {
    return (
      a.getFullYear() === b.getFullYear() &&
      a.getMonth() === b.getMonth() &&
      a.getDate() === b.getDate()
    );
  }

  function fmtTimeShort(iso: string): string {
    const d = new Date(iso);
    const h = String(d.getHours()).padStart(2, "0");
    const m = String(d.getMinutes()).padStart(2, "0");
    return `${h}:${m}`;
  }

  // Pour un employé donné et un jour, retourne les phases actives
  // (qui couvrent ce jour) + les events qui démarrent ce jour-là où
  // cet employé est assigné.
  function blocksFor(empId: number, day: Date): Array<
    | {
        kind: "phase";
        phase: Phase;
        project: Project | null;
      }
    | { kind: "event"; event: AgendaEvent }
  > {
    const out: Array<
      | { kind: "phase"; phase: Phase; project: Project | null }
      | { kind: "event"; event: AgendaEvent }
    > = [];
    // Phases : assignée ET range couvre ce jour
    for (const p of phases) {
      const ids = p.assignee_employe_ids || [];
      const single =
        p.assignee_employe_id != null ? [p.assignee_employe_id] : [];
      const all = [...ids, ...single];
      if (!all.includes(empId)) continue;
      if (!p.start_date || !p.duration_days) continue;
      const ps = new Date(p.start_date);
      ps.setHours(0, 0, 0, 0);
      const pe = new Date(ps);
      pe.setDate(pe.getDate() + (p.duration_days - 1));
      pe.setHours(23, 59, 59, 999);
      const t = day.getTime();
      if (t >= ps.getTime() && t <= pe.getTime()) {
        out.push({
          kind: "phase",
          phase: p,
          project: projectById.get(p.project_id) || null
        });
      }
    }
    // Events : démarre ce jour ET assigné à cet employé
    for (const e of events) {
      if (e.assignee_id !== empId) continue;
      const s = new Date(e.start_at);
      if (!isSameDay(s, day)) continue;
      out.push({ kind: "event", event: e });
    }
    return out;
  }

  // Sommaire : somme des heures par jour pour TOUTE l'équipe
  function dayTotalHours(day: Date): number {
    let total = 0;
    for (const emp of employes) {
      for (const b of blocksFor(emp.id, day)) {
        if (b.kind === "phase") {
          total += 8; // jour ouvrable standard
        } else {
          const ev = b.event;
          if (ev.all_day) total += 8;
          else if (ev.end_at) {
            const ms =
              new Date(ev.end_at).getTime() -
              new Date(ev.start_at).getTime();
            total += Math.max(0, ms / 3_600_000);
          } else {
            total += 1;
          }
        }
      }
    }
    return Math.round(total * 10) / 10;
  }

  if (employes.length === 0) {
    return (
      <div className="rounded-xl border border-dashed border-brand-800 bg-brand-900/40 px-6 py-10 text-center text-sm text-white/60">
        Aucun employé — ajoute des membres d&apos;équipe pour voir leur
        planning ici.
      </div>
    );
  }

  return (
    <div className="overflow-x-auto rounded-xl border border-brand-800">
      <div
        className="grid min-w-[900px] divide-y divide-brand-800 bg-brand-900"
        style={{ gridTemplateColumns: "180px repeat(7, 1fr)" }}
      >
        {/* Header row */}
        <div
          className="bg-brand-950 px-3 py-2 text-[10px] font-bold uppercase tracking-wider text-white/40"
          style={{ gridColumn: 1 }}
        >
          Employé
        </div>
        {week.map((d, i) => (
          <div
            key={i}
            className="bg-brand-950 px-2 py-2 text-center text-[11px] font-semibold text-white/70"
          >
            {dayLabel(d)}
          </div>
        ))}

        {/* Rows */}
        {employes.map((emp) => (
          <div key={emp.id} className="contents">
            <div className="border-r border-brand-800 bg-brand-900/60 px-3 py-2 text-sm font-medium text-white">
              {emp.full_name}
            </div>
            {week.map((d, i) => {
              const blocks = blocksFor(emp.id, d);
              const unavailEvents = blocks
                .filter((b) => b.kind === "event")
                .map((b) => (b as { kind: "event"; event: AgendaEvent }).event)
                .filter((ev) =>
                  [
                    "conge",
                    "congé",
                    "indispo",
                    "busy",
                    "absent",
                    "vacances"
                  ].includes((ev.event_type || "").toLowerCase())
                );
              const cellUnavail = unavailEvents.length > 0;
              const cellClassName = cellUnavail
                ? "flex min-h-[64px] flex-col gap-1 border-r-2 border-red-700 px-1.5 py-1.5 text-left transition"
                : "flex min-h-[64px] flex-col gap-1 border-r border-brand-800 px-1.5 py-1.5 text-left transition hover:bg-brand-800/30";
              // Hachures diagonales rouges en CSS pour signaler la
              // case indisponible (pattern repeating-linear-gradient).
              const cellStyle: React.CSSProperties | undefined = cellUnavail
                ? {
                    backgroundImage:
                      "repeating-linear-gradient(45deg, rgba(185,28,28,0.45) 0px, rgba(185,28,28,0.45) 6px, rgba(127,29,29,0.55) 6px, rgba(127,29,29,0.55) 12px)",
                    border: "2px solid rgb(185, 28, 28)"
                  }
                : undefined;
              return (
                <button
                  key={i}
                  type="button"
                  onClick={() => {
                    if (blocks.length === 0) {
                      const at = new Date(d);
                      at.setHours(8, 0, 0, 0);
                      onCellClick(emp.id, at);
                    }
                  }}
                  className={cellClassName}
                  style={cellStyle}
                >
                  {blocks.length === 0 ? (
                    <span className="text-xs italic text-white/30">
                      Libre
                    </span>
                  ) : (
                    blocks.map((b, idx) => {
                      if (b.kind === "phase") {
                        const c = projectColor(b.phase.project_id);
                        return (
                          <span
                            key={`p-${b.phase.id}-${idx}`}
                            className="block rounded px-1.5 py-1 text-[10px] font-semibold leading-tight"
                            style={{
                              backgroundColor: c.bg,
                              color: c.text,
                              border: `1px solid ${c.border}`
                            }}
                            title={`${b.phase.name}${
                              b.project ? ` · ${b.project.name}` : ""
                            }`}
                          >
                            <span className="block">📐 {b.phase.name}</span>
                            {b.project ? (
                              <span className="block text-[9px] opacity-80">
                                {b.project.name}
                              </span>
                            ) : null}
                          </span>
                        );
                      }
                      const ev = b.event;
                      // Non-disponibilité : congés, indispo, busy → rouge
                      // unifié peu importe le scope (l'employé est tout
                      // simplement indisponible).
                      const isUnavail = [
                        "conge",
                        "congé",
                        "indispo",
                        "busy",
                        "absent",
                        "vacances"
                      ].includes((ev.event_type || "").toLowerCase());
                      const c =
                        !isUnavail && ev.project_id
                          ? projectColor(ev.project_id)
                          : null;
                      const style = isUnavail
                        ? {
                            // Sur la case hachurée rouge, on garde
                            // juste le texte blanc en gras (pas de
                            // fond pour ne pas masquer le pattern).
                            backgroundColor: "transparent",
                            color: "#ffffff",
                            textShadow: "0 1px 2px rgba(0,0,0,0.7)",
                            border: "none"
                          }
                        : c
                          ? {
                              backgroundColor: c.bg,
                              color: c.text,
                              border: `1px solid ${c.border}`
                            }
                          : {
                              backgroundColor: "rgb(71, 85, 105)",
                              color: "#ffffff",
                              border: "1px solid rgb(51, 65, 85)"
                            };
                      return (
                        <span
                          key={`e-${ev.id}-${idx}`}
                          onClick={(clickEv) => {
                            clickEv.stopPropagation();
                            onEventClick(ev);
                          }}
                          className="block cursor-pointer rounded px-1.5 py-1 text-[10px] font-semibold leading-tight hover:opacity-90"
                          style={style}
                          title={
                            isUnavail
                              ? `Indisponible — ${ev.title}`
                              : ev.title
                          }
                        >
                          <span className="block">
                            {isUnavail
                              ? "🚫"
                              : ev.all_day
                                ? "⏰"
                                : `${fmtTimeShort(ev.start_at)}${
                                    ev.end_at
                                      ? " - " + fmtTimeShort(ev.end_at)
                                      : ""
                                  }`}
                          </span>
                          <span className="block truncate">
                            {ev.title}
                          </span>
                        </span>
                      );
                    })
                  )}
                </button>
              );
            })}
          </div>
        ))}

        {/* Sommaire row */}
        <div className="border-t-2 border-brand-700 bg-brand-950 px-3 py-2 text-[11px] font-bold uppercase tracking-wider text-accent-500">
          Sommaire
        </div>
        {week.map((d, i) => {
          const h = dayTotalHours(d);
          return (
            <div
              key={i}
              className="border-t-2 border-r border-brand-700 bg-brand-950 px-2 py-2 text-center text-[11px] font-semibold text-accent-300"
            >
              {h > 0 ? `${h}h` : <span className="text-white/20">—</span>}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function TimelineView({
  mode,
  ref,
  spanDays,
  events,
  phases,
  projects,
  employes,
  onEventClick
}: {
  mode: "project" | "person";
  ref: Date;
  spanDays: number;
  events: AgendaEvent[];
  phases: Phase[];
  projects: Project[];
  employes: Employe[];
  onEventClick: (e: AgendaEvent) => void;
}) {
  const start = useMemo(() => mondayOf(ref), [ref]);
  const days = useMemo(
    () =>
      Array.from({ length: spanDays }, (_, i) => {
        const d = new Date(start);
        d.setDate(start.getDate() + i);
        return d;
      }),
    [start, spanDays]
  );
  const endExclusive = useMemo(() => {
    const d = new Date(start);
    d.setDate(d.getDate() + spanDays);
    return d;
  }, [start, spanDays]);

  const projectById = useMemo(() => {
    const m = new Map<number, Project>();
    for (const p of projects) m.set(p.id, p);
    return m;
  }, [projects]);
  const employeById = useMemo(() => {
    const m = new Map<number, Employe>();
    for (const e of employes) m.set(e.id, e);
    return m;
  }, [employes]);

  function clampIdx(d: Date): number {
    const i = diffDays(start, d);
    return Math.max(0, Math.min(spanDays - 1, i));
  }

  function eventToItem(e: AgendaEvent): TimelineItem | null {
    const s = new Date(e.start_at);
    const endRaw = e.end_at ? new Date(e.end_at) : new Date(e.start_at);
    if (endRaw < start || s >= endExclusive) return null;
    const emp = e.assignee_id ? employeById.get(e.assignee_id) : null;
    const proj = e.project_id ? projectById.get(e.project_id) : null;
    const sub =
      mode === "project"
        ? emp
          ? `${TYPE_LABELS[e.event_type] || "Événement"} · ${emp.full_name}`
          : TYPE_LABELS[e.event_type] || "Événement"
        : proj
          ? `${TYPE_LABELS[e.event_type] || "Événement"} · ${proj.name}`
          : TYPE_LABELS[e.event_type] || "Événement";
    return {
      key: `e-${e.id}`,
      kind: "event",
      title: e.title,
      subtitle: sub,
      startIdx: clampIdx(s),
      endIdx: clampIdx(endRaw),
      accent: eventAccent(e.event_type),
      raw: e,
      onClick: () => onEventClick(e)
    };
  }

  function phaseToItem(p: Phase): TimelineItem | null {
    if (!p.start_date || !p.duration_days || p.duration_days <= 0) return null;
    const s = parseLocalDate(p.start_date);
    const e = new Date(s);
    e.setDate(e.getDate() + p.duration_days - 1);
    if (e < start || s >= endExclusive) return null;
    const proj = projectById.get(p.project_id);
    const empIds =
      p.assignee_employe_ids && p.assignee_employe_ids.length > 0
        ? p.assignee_employe_ids
        : p.assignee_employe_id
          ? [p.assignee_employe_id]
          : [];
    const empNames = empIds
      .map((id) => employeById.get(id)?.full_name)
      .filter(Boolean) as string[];
    const empLabel =
      empNames.length > 2
        ? `${empNames.slice(0, 2).join(", ")} +${empNames.length - 2}`
        : empNames.join(", ");
    const sub =
      mode === "project"
        ? empLabel
          ? `Phase · ${empLabel}`
          : "Phase"
        : proj
          ? `Phase · ${proj.name}`
          : "Phase";
    return {
      key: `p-${p.id}`,
      kind: "phase",
      title: p.name,
      subtitle: sub,
      startIdx: clampIdx(s),
      endIdx: clampIdx(e),
      accent: "bg-fuchsia-500/80 border-fuchsia-400 text-white",
      href: `/app/projets/${p.project_id}`
    };
  }

  const rows: TimelineRow[] = useMemo(() => {
    const rowMap = new Map<string, TimelineRow>();
    const ensureRow = (key: string, label: string, sublabel?: string) => {
      const existing = rowMap.get(key);
      if (existing) return existing;
      const r: TimelineRow = { key, label, sublabel, items: [] };
      rowMap.set(key, r);
      return r;
    };

    if (mode === "project") {
      for (const ev of events) {
        const item = eventToItem(ev);
        if (!item) continue;
        const key = ev.project_id ? `proj-${ev.project_id}` : "proj-none";
        const label = ev.project_id
          ? projectById.get(ev.project_id)?.name || `Projet #${ev.project_id}`
          : "Sans chantier";
        ensureRow(key, label).items.push(item);
      }
      for (const ph of phases) {
        const item = phaseToItem(ph);
        if (!item) continue;
        const key = `proj-${ph.project_id}`;
        const label =
          projectById.get(ph.project_id)?.name || `Projet #${ph.project_id}`;
        const sub = projectById.get(ph.project_id)?.status || undefined;
        ensureRow(key, label, sub).items.push(item);
      }
    } else {
      for (const ev of events) {
        const item = eventToItem(ev);
        if (!item) continue;
        const key = ev.assignee_id ? `emp-${ev.assignee_id}` : "emp-none";
        const label = ev.assignee_id
          ? employeById.get(ev.assignee_id)?.full_name ||
            `Employé #${ev.assignee_id}`
          : "Non-assigné";
        ensureRow(key, label).items.push(item);
      }
      for (const ph of phases) {
        const item = phaseToItem(ph);
        if (!item) continue;
        // Multi-assignation : on émet une barre par employé assigné
        // pour que tous apparaissent dans la vue « Par personne ».
        const employeIds =
          ph.assignee_employe_ids && ph.assignee_employe_ids.length > 0
            ? ph.assignee_employe_ids
            : ph.assignee_employe_id
              ? [ph.assignee_employe_id]
              : [];
        if (employeIds.length === 0) {
          ensureRow("emp-none", "Non-assigné").items.push(item);
        } else {
          for (const empId of employeIds) {
            const key = `emp-${empId}`;
            const label =
              employeById.get(empId)?.full_name || `Employé #${empId}`;
            ensureRow(key, label).items.push({
              ...item,
              key: `${item.key}-e${empId}`
            });
          }
        }
      }
    }

    const arr = Array.from(rowMap.values());
    arr.sort((a, b) => {
      if (a.key === "proj-none" || a.key === "emp-none") return 1;
      if (b.key === "proj-none" || b.key === "emp-none") return -1;
      return a.label.localeCompare(b.label);
    });
    return arr;
    // eventToItem / phaseToItem close over deps listed below; exhaustive-deps
    // doesn't track inner function captures so we enumerate the real deps.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    mode,
    events,
    phases,
    projectById,
    employeById,
    start,
    endExclusive,
    spanDays,
    onEventClick
  ]);

  const today = new Date();
  const todayIdx = diffDays(start, today);
  const todayInRange = todayIdx >= 0 && todayIdx < spanDays;

  if (rows.length === 0) {
    return (
      <div className="rounded-2xl border border-dashed border-brand-800 bg-brand-900/40 px-6 py-14 text-center">
        <CalendarIcon className="mx-auto h-8 w-8 text-white/30" />
        <p className="mt-3 text-sm text-white/60">
          Aucun événement ni phase sur cette période.
        </p>
      </div>
    );
  }

  const gridCols = `200px repeat(${spanDays}, minmax(44px, 1fr))`;

  return (
    <div className="overflow-x-auto rounded-xl border border-brand-800 bg-brand-900">
      <div className="min-w-[720px]">
        {/* Header row */}
        <div
          className="sticky top-0 z-10 grid border-b border-brand-800 bg-brand-900/95 text-xs"
          style={{ gridTemplateColumns: gridCols }}
        >
          <div className="px-3 py-2 font-semibold text-white/50 uppercase tracking-wider">
            {mode === "project" ? "Chantier" : "Personne"}
          </div>
          {days.map((d, i) => {
            const isToday = sameDay(d, today);
            const isWeekend = d.getDay() === 0 || d.getDay() === 6;
            return (
              <div
                key={i}
                className={`border-l border-brand-800 px-1.5 py-2 text-center ${
                  isWeekend ? "bg-brand-950/40" : ""
                } ${isToday ? "text-accent-400" : "text-white/60"}`}
              >
                <p className="text-[10px] uppercase">{WEEKDAYS[(d.getDay() + 6) % 7]}</p>
                <p className="text-[11px] font-semibold">
                  {d.getDate()}
                </p>
              </div>
            );
          })}
        </div>

        {/* Rows */}
        {rows.map((row) => {
          const { placed, trackCount } = assignTracks(row.items);
          const rowHeight = Math.max(1, trackCount) * 34 + 10;
          return (
            <div
              key={row.key}
              className="grid border-b border-brand-800"
              style={{ gridTemplateColumns: gridCols }}
            >
              <div className="flex min-w-0 flex-col justify-center border-r border-brand-800 px-3 py-2">
                <p className="truncate text-sm font-semibold text-white">
                  {row.label}
                </p>
                {row.sublabel ? (
                  <p className="truncate text-[11px] text-white/50">
                    {row.sublabel}
                  </p>
                ) : null}
              </div>
              <div
                className="relative"
                style={{
                  gridColumn: `2 / span ${spanDays}`,
                  height: `${rowHeight}px`
                }}
              >
                {/* Day column grid background */}
                <div
                  className="pointer-events-none absolute inset-0 grid"
                  style={{
                    gridTemplateColumns: `repeat(${spanDays}, minmax(0, 1fr))`
                  }}
                >
                  {days.map((d, i) => {
                    const isWeekend = d.getDay() === 0 || d.getDay() === 6;
                    return (
                      <div
                        key={i}
                        className={`border-l border-brand-800/60 ${
                          isWeekend ? "bg-brand-950/30" : ""
                        }`}
                      />
                    );
                  })}
                </div>
                {/* Today vertical line */}
                {todayInRange ? (
                  <div
                    className="pointer-events-none absolute top-0 bottom-0 z-[1] w-px bg-accent-500/70"
                    style={{
                      left: `calc(${(todayIdx + 0.5) / spanDays} * 100%)`
                    }}
                  />
                ) : null}
                {/* Items */}
                {placed.map((it) => {
                  const left = (it.startIdx / spanDays) * 100;
                  const width =
                    ((it.endIdx - it.startIdx + 1) / spanDays) * 100;
                  const top = it.track * 34 + 5;
                  const content = (
                    <div className="flex h-full min-w-0 items-center gap-1 px-2">
                      <span className="truncate text-[11px] font-semibold">
                        {it.title}
                      </span>
                      <span className="truncate text-[10px] opacity-80">
                        {it.subtitle}
                      </span>
                    </div>
                  );
                  const className = `absolute z-[2] rounded-md border shadow-sm transition hover:brightness-110 ${it.accent}`;
                  const style = {
                    left: `${left}%`,
                    width: `calc(${width}% - 4px)`,
                    top: `${top}px`,
                    height: "28px"
                  } as React.CSSProperties;
                  if (it.onClick) {
                    return (
                      <button
                        key={it.key}
                        type="button"
                        onClick={it.onClick}
                        className={`${className} cursor-pointer text-left`}
                        style={style}
                        title={`${it.title} — ${it.subtitle}`}
                      >
                        {content}
                      </button>
                    );
                  }
                  if (it.href) {
                    return (
                      <Link
                        key={it.key}
                        // eslint-disable-next-line @typescript-eslint/no-explicit-any
                        href={it.href as any}
                        className={className}
                        style={style}
                        title={`${it.title} — ${it.subtitle}`}
                      >
                        {content}
                      </Link>
                    );
                  }
                  return (
                    <div
                      key={it.key}
                      className={className}
                      style={style}
                      title={`${it.title} — ${it.subtitle}`}
                    >
                      {content}
                    </div>
                  );
                })}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// TimeGridView — classic day/week calendar with hourly rows.
// Used by the "Journalier" (days=1) and "Hebdomadaire" (days=7) views.
// ---------------------------------------------------------------------------

const HOUR_START = 6;
const HOUR_END = 22; // exclusive — renders 06:00..22:00 (16 rows)
const ROW_HEIGHT = 48; // px per hour

function TimeGridView({
  ref,
  days,
  events,
  onSlotClick,
  onEventClick
}: {
  ref: Date;
  days: 1 | 7;
  events: AgendaEvent[];
  onSlotClick: (d: Date) => void;
  onEventClick: (e: AgendaEvent) => void;
}) {
  const start = useMemo(() => {
    if (days === 7) return mondayOf(ref);
    return new Date(ref.getFullYear(), ref.getMonth(), ref.getDate());
  }, [ref, days]);

  const dayList = useMemo(
    () =>
      Array.from({ length: days }, (_, i) => {
        const d = new Date(start);
        d.setDate(start.getDate() + i);
        return d;
      }),
    [start, days]
  );

  const hours = useMemo(
    () =>
      Array.from({ length: HOUR_END - HOUR_START }, (_, i) => HOUR_START + i),
    []
  );

  // Split events into timed vs all-day (or multi-day) for the "All-day" strip.
  type PlacedEvent = AgendaEvent & {
    dayIdx: number;
    startMin: number; // minutes from HOUR_START
    endMin: number;
  };
  type AllDayBar = {
    e: AgendaEvent;
    startIdx: number; // 0..days-1
    endIdx: number;
  };

  const { timed, allDay } = useMemo(() => {
    const t: PlacedEvent[] = [];
    const a: AllDayBar[] = [];
    const rangeEnd = new Date(start);
    rangeEnd.setDate(rangeEnd.getDate() + days);
    for (const ev of events) {
      const s = new Date(ev.start_at);
      const e = ev.end_at ? new Date(ev.end_at) : new Date(ev.start_at);
      if (e < start || s >= rangeEnd) continue;
      const sameLocalDay =
        s.toDateString() === e.toDateString() && !ev.all_day;
      if (ev.all_day || !sameLocalDay) {
        const sIdx = Math.max(0, diffDays(start, s));
        const eIdx = Math.min(days - 1, diffDays(start, e));
        a.push({ e: ev, startIdx: sIdx, endIdx: eIdx });
        continue;
      }
      const dIdx = diffDays(start, s);
      if (dIdx < 0 || dIdx >= days) continue;
      const startMin =
        (s.getHours() - HOUR_START) * 60 + s.getMinutes();
      const endMin =
        (e.getHours() - HOUR_START) * 60 + e.getMinutes();
      // Clamp visible range: HOUR_START..HOUR_END.
      const clampedStart = Math.max(0, startMin);
      const clampedEnd = Math.max(
        clampedStart + 15,
        Math.min((HOUR_END - HOUR_START) * 60, endMin)
      );
      t.push({
        ...ev,
        dayIdx: dIdx,
        startMin: clampedStart,
        endMin: clampedEnd
      });
    }
    return { timed: t, allDay: a };
  }, [events, start, days]);

  // Place overlapping timed events side-by-side within the same day column.
  type LaidOut = PlacedEvent & { col: number; colCount: number };
  const laidOut: LaidOut[] = useMemo(() => {
    const out: LaidOut[] = [];
    for (let d = 0; d < days; d++) {
      const dayEvents = timed
        .filter((ev) => ev.dayIdx === d)
        .sort((a, b) =>
          a.startMin !== b.startMin
            ? a.startMin - b.startMin
            : a.endMin - b.endMin
        );
      // Group into clusters of overlapping events, then assign columns.
      type Cluster = { items: LaidOut[]; endMax: number };
      let cluster: Cluster | null = null;
      const clusters: Cluster[] = [];
      for (const ev of dayEvents) {
        if (cluster && ev.startMin < cluster.endMax) {
          cluster.items.push({ ...ev, col: 0, colCount: 1 });
          cluster.endMax = Math.max(cluster.endMax, ev.endMin);
        } else {
          cluster = {
            items: [{ ...ev, col: 0, colCount: 1 }],
            endMax: ev.endMin
          };
          clusters.push(cluster);
        }
      }
      for (const c of clusters) {
        // Assign each item to the first column whose last event ended
        // before this one starts.
        const trackEnds: number[] = [];
        for (const it of c.items) {
          let tIdx = -1;
          for (let i = 0; i < trackEnds.length; i++) {
            if (trackEnds[i] <= it.startMin) {
              tIdx = i;
              break;
            }
          }
          if (tIdx === -1) {
            tIdx = trackEnds.length;
            trackEnds.push(it.endMin);
          } else {
            trackEnds[tIdx] = it.endMin;
          }
          it.col = tIdx;
        }
        const count = trackEnds.length;
        for (const it of c.items) it.colCount = count;
        out.push(...c.items);
      }
    }
    return out;
  }, [timed, days]);

  // Pack all-day bars into vertical tracks so qu'ils ne s'empilent
  // pas l'un par-dessus l'autre. Algo identique aux clusters timed :
  // la première bande qui peut tenir dans une track la prend, sinon
  // on en crée une nouvelle.
  type AllDayLaidOut = AllDayBar & { track: number };
  const allDayLaidOut: AllDayLaidOut[] = useMemo(() => {
    const sorted = [...allDay].sort((a, b) =>
      a.startIdx !== b.startIdx
        ? a.startIdx - b.startIdx
        : a.endIdx - b.endIdx
    );
    const tracksEnd: number[] = []; // dernier endIdx (inclusif) par track
    const out: AllDayLaidOut[] = [];
    for (const bar of sorted) {
      let t = -1;
      for (let i = 0; i < tracksEnd.length; i++) {
        if (tracksEnd[i] < bar.startIdx) {
          t = i;
          break;
        }
      }
      if (t === -1) {
        t = tracksEnd.length;
        tracksEnd.push(bar.endIdx);
      } else {
        tracksEnd[t] = bar.endIdx;
      }
      out.push({ ...bar, track: t });
    }
    return out;
  }, [allDay]);

  const allDayTrackCount = useMemo(
    () => allDayLaidOut.reduce((m, b) => Math.max(m, b.track + 1), 0),
    [allDayLaidOut]
  );

  const today = new Date();
  const todayCol = diffDays(start, today);
  const todayInRange = todayCol >= 0 && todayCol < days;
  const nowMin =
    (today.getHours() - HOUR_START) * 60 + today.getMinutes();
  const nowInRange = nowMin >= 0 && nowMin <= (HOUR_END - HOUR_START) * 60;

  const gridCols = `56px repeat(${days}, minmax(0, 1fr))`;
  const bodyHeight = (HOUR_END - HOUR_START) * ROW_HEIGHT;

  function slotFromClick(dayIdx: number, e: React.MouseEvent) {
    const rect = (e.currentTarget as HTMLElement).getBoundingClientRect();
    const y = e.clientY - rect.top;
    const totalMin = Math.max(0, Math.min(bodyHeight, y)) *
      (60 / ROW_HEIGHT);
    const hour = Math.floor(totalMin / 60) + HOUR_START;
    const minute = Math.round((totalMin % 60) / 30) * 30; // snap 30 min
    const d = new Date(dayList[dayIdx]);
    d.setHours(hour, minute, 0, 0);
    onSlotClick(d);
  }

  return (
    <div className="overflow-x-auto rounded-xl border border-brand-800 bg-brand-900">
      <div className="min-w-[560px]">
        {/* Header: day labels */}
        <div
          className="grid border-b border-brand-800 text-xs"
          style={{ gridTemplateColumns: gridCols }}
        >
          <div />
          {dayList.map((d, i) => {
            const isToday = sameDay(d, today);
            return (
              <div
                key={i}
                className={`border-l border-brand-800 px-2 py-2 text-center ${
                  isToday ? "text-accent-400" : "text-white/60"
                }`}
              >
                <p className="text-[10px] uppercase">
                  {WEEKDAYS[(d.getDay() + 6) % 7]}
                </p>
                <p
                  className={`text-sm ${
                    isToday ? "font-bold text-accent-400" : "text-white"
                  }`}
                >
                  {d.getDate()}
                </p>
              </div>
            );
          })}
        </div>

        {/* All-day strip — bandes empilées en tracks pour éviter le
            chevauchement quand 2 phases couvrent le même jour. */}
        {allDay.length > 0 ? (
          <div
            className="grid border-b border-brand-800 bg-brand-900/60"
            style={{ gridTemplateColumns: gridCols }}
          >
            <div className="flex items-start justify-end px-2 py-1 text-[10px] uppercase tracking-wider text-white/40">
              Toute
            </div>
            <div
              className="relative py-1"
              style={{
                gridColumn: `2 / span ${days}`,
                height: `${4 + allDayTrackCount * 26}px`
              }}
            >
              <div
                className="absolute inset-0 grid"
                style={{
                  gridTemplateColumns: `repeat(${days}, minmax(0, 1fr))`
                }}
              >
                {dayList.map((_, i) => (
                  <div key={i} className="border-l border-brand-800/60" />
                ))}
              </div>
              {allDayLaidOut.map(({ e, startIdx, endIdx, track }, k) => {
                const left = (startIdx / days) * 100;
                const width = ((endIdx - startIdx + 1) / days) * 100;
                const top = 2 + track * 26;
                const pc = e.project_id
                  ? projectColor(e.project_id)
                  : null;
                const baseCls =
                  "absolute z-[2] overflow-hidden rounded-md border px-2 py-0.5 text-left text-[11px] font-semibold shadow-sm hover:brightness-110";
                return (
                  <button
                    key={`ad-${e.id}-${k}`}
                    type="button"
                    onClick={() => onEventClick(e)}
                    className={
                      pc
                        ? baseCls
                        : `${baseCls} ${eventAccent(e.event_type)}`
                    }
                    style={
                      pc
                        ? {
                            left: `calc(${left}% + 2px)`,
                            width: `calc(${width}% - 4px)`,
                            top: `${top}px`,
                            height: "22px",
                            backgroundColor: pc.bg,
                            borderColor: pc.border,
                            color: pc.text
                          }
                        : {
                            left: `calc(${left}% + 2px)`,
                            width: `calc(${width}% - 4px)`,
                            top: `${top}px`,
                            height: "22px"
                          }
                    }
                    title={e.title}
                  >
                    <span className="truncate block">{e.title}</span>
                  </button>
                );
              })}
            </div>
          </div>
        ) : null}

        {/* Body: hour rows × day columns */}
        <div
          className="grid"
          style={{ gridTemplateColumns: gridCols }}
        >
          {/* Hour labels */}
          <div className="border-r border-brand-800">
            {hours.map((h) => (
              <div
                key={h}
                className="flex items-start justify-end pr-2 pt-0.5 text-[10px] text-white/40"
                style={{ height: `${ROW_HEIGHT}px` }}
              >
                {String(h).padStart(2, "0")}:00
              </div>
            ))}
          </div>
          {/* Day columns */}
          {dayList.map((d, i) => {
            const isToday = sameDay(d, today);
            return (
              <div
                key={i}
                onClick={(e) => slotFromClick(i, e)}
                className={`relative cursor-pointer border-l border-brand-800 ${
                  isToday ? "bg-accent-500/5" : ""
                }`}
                style={{ height: `${bodyHeight}px` }}
              >
                {/* Hour lines */}
                {hours.map((h, idx) => (
                  <div
                    key={h}
                    className="pointer-events-none absolute left-0 right-0 border-t border-brand-800/60"
                    style={{ top: `${idx * ROW_HEIGHT}px` }}
                  />
                ))}
                {/* Half-hour lines (dashed, lighter) */}
                {hours.map((h, idx) => (
                  <div
                    key={`half-${h}`}
                    className="pointer-events-none absolute left-0 right-0 border-t border-dashed border-brand-800/30"
                    style={{ top: `${idx * ROW_HEIGHT + ROW_HEIGHT / 2}px` }}
                  />
                ))}
                {/* Now line */}
                {todayInRange && todayCol === i && nowInRange ? (
                  <div
                    className="pointer-events-none absolute left-0 right-0 z-[3] flex items-center"
                    style={{
                      top: `${(nowMin / 60) * ROW_HEIGHT}px`
                    }}
                  >
                    <span className="h-1.5 w-1.5 rounded-full bg-accent-500" />
                    <span className="h-px flex-1 bg-accent-500" />
                  </div>
                ) : null}
                {/* Events */}
                {laidOut
                  .filter((ev) => ev.dayIdx === i)
                  .map((ev) => {
                    const top = (ev.startMin / 60) * ROW_HEIGHT;
                    const height = Math.max(
                      22,
                      ((ev.endMin - ev.startMin) / 60) * ROW_HEIGHT - 2
                    );
                    const colWidth = 100 / ev.colCount;
                    const left = ev.col * colWidth;
                    const width = colWidth;
                    const pc = ev.project_id
                      ? projectColor(ev.project_id)
                      : null;
                    const baseCls =
                      "absolute z-[2] overflow-hidden rounded-md border text-left shadow-sm hover:brightness-110";
                    return (
                      <button
                        key={`ev-${ev.id}`}
                        type="button"
                        onClick={(evt) => {
                          evt.stopPropagation();
                          onEventClick(ev);
                        }}
                        className={
                          pc
                            ? baseCls
                            : `${baseCls} ${eventAccent(ev.event_type)}`
                        }
                        style={
                          pc
                            ? {
                                top: `${top}px`,
                                height: `${height}px`,
                                left: `calc(${left}% + 2px)`,
                                width: `calc(${width}% - 4px)`,
                                backgroundColor: pc.bg,
                                borderColor: pc.border,
                                color: pc.text
                              }
                            : {
                                top: `${top}px`,
                                height: `${height}px`,
                                left: `calc(${left}% + 2px)`,
                                width: `calc(${width}% - 4px)`
                              }
                        }
                        title={`${ev.title} — ${fmtTime(ev.start_at)}${
                          ev.end_at ? ` → ${fmtTime(ev.end_at)}` : ""
                        }`}
                      >
                        <div className="px-1.5 py-0.5">
                          <p className="truncate text-[11px] font-semibold leading-tight">
                            {ev.title}
                          </p>
                          <p className="truncate text-[10px] opacity-80">
                            {fmtTime(ev.start_at)}
                            {ev.end_at ? ` → ${fmtTime(ev.end_at)}` : ""}
                          </p>
                        </div>
                      </button>
                    );
                  })}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
