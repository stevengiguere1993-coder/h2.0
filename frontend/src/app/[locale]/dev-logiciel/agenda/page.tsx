"use client";

import { useEffect, useMemo, useState } from "react";
import {
  CalendarClock,
  Clock,
  FileText,
  FolderKanban,
  Loader2,
  Receipt,
  Search
} from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { Link } from "@/i18n/navigation";
import { authedFetch } from "@/lib/auth";
import { PageDriveSection } from "@/components/drive/PageDriveSection";
import { useDevlogLayout } from "../layout";

// L'agenda du pôle Dév logiciel agrège dans une vue chronologique
// unique TOUTES les dates clés du pôle :
//   - Début / échéance de projet
//   - Échéance de soumission (envoyée, statut soumission)
//   - Émission et échéance de facture
//   - Saisie d'heures (regroupée par jour)
//
// Pas de modèle agenda dédié — on lit l'existant et on projette.

type Project = {
  id: number;
  name: string;
  status: string;
  start_date: string | null;
  due_date: string | null;
};
type Soumission = {
  id: number;
  title: string;
  status: string;
  created_at: string;
};
type Invoice = {
  id: number;
  number: string | null;
  amount: number | null;
  status: string;
  issued_date: string | null;
  due_date: string | null;
};
type TimeEntry = {
  id: number;
  work_date: string;
  hours: number;
};

type EventKind = "projet_debut" | "projet_echeance" | "soumission" | "facture_emise" | "facture_due" | "heures";

type AgendaEvent = {
  id: string;
  date: string; // ISO YYYY-MM-DD
  kind: EventKind;
  title: string;
  subtitle?: string;
  href?: string;
};

const KIND_META: Record<EventKind, { label: string; cls: string; icon: React.ReactNode }> = {
  projet_debut: {
    label: "Début projet",
    cls: "bg-blue-500/15 text-blue-300 border-blue-500/40",
    icon: <FolderKanban className="h-3 w-3" />
  },
  projet_echeance: {
    label: "Échéance projet",
    cls: "bg-amber-500/15 text-amber-300 border-amber-500/40",
    icon: <FolderKanban className="h-3 w-3" />
  },
  soumission: {
    label: "Soumission",
    cls: "bg-violet-500/15 text-violet-300 border-violet-500/40",
    icon: <FileText className="h-3 w-3" />
  },
  facture_emise: {
    label: "Facture émise",
    cls: "bg-emerald-500/15 text-emerald-300 border-emerald-500/40",
    icon: <Receipt className="h-3 w-3" />
  },
  facture_due: {
    label: "Échéance facture",
    cls: "bg-rose-500/15 text-rose-300 border-rose-500/40",
    icon: <Receipt className="h-3 w-3" />
  },
  heures: {
    label: "Heures",
    cls: "bg-white/5 text-white/60 border-white/15",
    icon: <Clock className="h-3 w-3" />
  }
};

function fmtAmount(n: number | null): string {
  if (n == null) return "—";
  return n.toLocaleString("fr-CA", {
    style: "currency",
    currency: "CAD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2
  });
}

function fmtDateLong(s: string): string {
  const d = new Date(s);
  if (Number.isNaN(d.getTime())) return s;
  return d.toLocaleDateString("fr-CA", {
    weekday: "long",
    day: "numeric",
    month: "long",
    year: "numeric"
  });
}

export default function DevlogAgendaPage() {
  const { onOpenSidebar } = useDevlogLayout();
  const [projects, setProjects] = useState<Project[]>([]);
  const [soumissions, setSoumissions] = useState<Soumission[]>([]);
  const [invoices, setInvoices] = useState<Invoice[]>([]);
  const [entries, setEntries] = useState<TimeEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [kinds, setKinds] = useState<Set<EventKind>>(
    new Set<EventKind>([
      "projet_debut",
      "projet_echeance",
      "soumission",
      "facture_emise",
      "facture_due",
      "heures"
    ])
  );

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [pr, sr, ir, er] = await Promise.all([
          authedFetch("/api/v1/devlog/projects"),
          authedFetch("/api/v1/devlog/soumissions"),
          authedFetch("/api/v1/devlog/invoices"),
          authedFetch("/api/v1/devlog/time-entries")
        ]);
        if (cancelled) return;
        if (pr.ok) setProjects(await pr.json());
        if (sr.ok) setSoumissions(await sr.json());
        if (ir.ok) setInvoices(await ir.json());
        if (er.ok) setEntries(await er.json());
      } catch {
        /* silencieux */
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  // Construit tous les événements à partir des données.
  const allEvents = useMemo<AgendaEvent[]>(() => {
    const out: AgendaEvent[] = [];
    for (const p of projects) {
      if (p.start_date) {
        out.push({
          id: `p-start-${p.id}`,
          date: p.start_date.slice(0, 10),
          kind: "projet_debut",
          title: p.name,
          subtitle: "Démarrage du projet",
          href: `/dev-logiciel/projets/${p.id}`
        });
      }
      if (p.due_date) {
        out.push({
          id: `p-due-${p.id}`,
          date: p.due_date.slice(0, 10),
          kind: "projet_echeance",
          title: p.name,
          subtitle: "Livraison prévue",
          href: `/dev-logiciel/projets/${p.id}`
        });
      }
    }
    for (const s of soumissions) {
      out.push({
        id: `s-${s.id}`,
        date: s.created_at.slice(0, 10),
        kind: "soumission",
        title: s.title,
        subtitle: `Statut : ${s.status}`,
        href: `/dev-logiciel/soumissions/${s.id}`
      });
    }
    for (const i of invoices) {
      if (i.issued_date) {
        out.push({
          id: `i-em-${i.id}`,
          date: i.issued_date.slice(0, 10),
          kind: "facture_emise",
          title: i.number ?? `Facture #${i.id}`,
          subtitle: `Émise — ${fmtAmount(i.amount)}`,
          href: "/dev-logiciel/facturation"
        });
      }
      if (i.due_date && i.status !== "payee" && i.status !== "annulee") {
        out.push({
          id: `i-due-${i.id}`,
          date: i.due_date.slice(0, 10),
          kind: "facture_due",
          title: i.number ?? `Facture #${i.id}`,
          subtitle: `Échéance — ${fmtAmount(i.amount)}`,
          href: "/dev-logiciel/facturation"
        });
      }
    }
    // Heures groupées par jour pour éviter le bruit.
    const byDay = new Map<string, number>();
    for (const e of entries) {
      const k = e.work_date.slice(0, 10);
      byDay.set(k, (byDay.get(k) || 0) + (e.hours || 0));
    }
    for (const [day, hours] of byDay.entries()) {
      out.push({
        id: `h-${day}`,
        date: day,
        kind: "heures",
        title: `${hours.toLocaleString("fr-CA")} h saisies`,
        subtitle: "Total équipe",
        href: "/dev-logiciel/heures"
      });
    }
    return out;
  }, [projects, soumissions, invoices, entries]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return allEvents
      .filter((e) => kinds.has(e.kind))
      .filter((e) =>
        q
          ? `${e.title} ${e.subtitle ?? ""}`
              .toLowerCase()
              .includes(q)
          : true
      )
      .sort((a, b) => (a.date < b.date ? 1 : -1));
  }, [allEvents, kinds, search]);

  // Groupe par date.
  const groupedByDate = useMemo(() => {
    const m = new Map<string, AgendaEvent[]>();
    for (const e of filtered) {
      const arr = m.get(e.date) || [];
      arr.push(e);
      m.set(e.date, arr);
    }
    return Array.from(m.entries()).sort((a, b) => (a[0] < b[0] ? 1 : -1));
  }, [filtered]);

  function toggleKind(k: EventKind) {
    setKinds((prev) => {
      const next = new Set(prev);
      if (next.has(k)) next.delete(k);
      else next.add(k);
      return next;
    });
  }

  const today = new Date().toISOString().slice(0, 10);

  return (
    <div className="min-h-screen bg-brand-950">
      <AppTopbar
        breadcrumbs={[
          { label: "Développement logiciel", href: "/dev-logiciel" as any },
          { label: "Agenda" }
        ]}
        onOpenSidebar={onOpenSidebar}
        searchPlaceholder="Chercher dans l'agenda…"
        onSearch={setSearch}
      />

      <div className="mx-auto max-w-4xl px-4 py-5 lg:px-6">
        <header className="mb-4 flex items-center gap-3">
          <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-accent-500/15 text-accent-500">
            <CalendarClock className="h-5 w-5" />
          </span>
          <div>
            <h1 className="text-xl font-bold text-white">Agenda du pôle</h1>
            <p className="text-xs text-white/50">
              Toutes les dates clés agrégées — projets, soumissions, factures, heures.
            </p>
          </div>
        </header>

        <PageDriveSection
          pageKey="page:dev-logiciel:agenda"
          pole="Développement logiciel"
          label="Agenda"
          route="/dev-logiciel/agenda"
          className="mb-4"
        />

        {/* Filtres par type */}
        <div className="mb-4 flex flex-wrap items-center gap-2">
          <div className="relative flex-1 min-w-[200px]">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-white/40" />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Chercher…"
              className="input pl-9 text-sm"
            />
          </div>
          <div className="flex flex-wrap items-center gap-1">
            {(Object.entries(KIND_META) as [EventKind, typeof KIND_META[EventKind]][]).map(
              ([k, meta]) => (
                <button
                  key={k}
                  type="button"
                  onClick={() => toggleKind(k)}
                  className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide transition ${
                    kinds.has(k)
                      ? meta.cls
                      : "border-white/10 bg-white/0 text-white/30"
                  }`}
                >
                  {meta.icon}
                  {meta.label}
                </button>
              )
            )}
          </div>
        </div>

        {loading ? (
          <div className="mt-10 flex justify-center">
            <Loader2 className="h-6 w-6 animate-spin text-accent-500" />
          </div>
        ) : groupedByDate.length === 0 ? (
          <p className="rounded-xl border border-brand-800 bg-brand-900 p-6 text-center text-sm text-white/40">
            Aucun événement à afficher.
          </p>
        ) : (
          <div className="space-y-3">
            {groupedByDate.map(([date, events]) => (
              <section
                key={date}
                className={`rounded-2xl border bg-brand-900 ${
                  date === today
                    ? "border-accent-500/60 ring-1 ring-accent-500/30"
                    : "border-brand-800"
                }`}
              >
                <header className="flex items-center justify-between border-b border-brand-800 px-4 py-2">
                  <span className="text-sm font-semibold text-white">
                    {fmtDateLong(date)}
                  </span>
                  {date === today ? (
                    <span className="rounded-full bg-accent-500/15 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-accent-500">
                      Aujourd'hui
                    </span>
                  ) : (
                    <span className="text-[10px] uppercase tracking-wide text-white/30">
                      {events.length} évén.
                    </span>
                  )}
                </header>
                <ul className="divide-y divide-brand-800">
                  {events.map((e) => {
                    const meta = KIND_META[e.kind];
                    const content = (
                      <div className="flex items-center gap-3 px-4 py-2.5">
                        <span
                          className={`inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide ${meta.cls}`}
                        >
                          {meta.icon}
                          {meta.label}
                        </span>
                        <div className="min-w-0 flex-1">
                          <p className="truncate text-sm font-semibold text-white">
                            {e.title}
                          </p>
                          {e.subtitle ? (
                            <p className="text-xs text-white/50">
                              {e.subtitle}
                            </p>
                          ) : null}
                        </div>
                      </div>
                    );
                    return (
                      <li key={e.id}>
                        {e.href ? (
                          <Link
                            // eslint-disable-next-line @typescript-eslint/no-explicit-any
                            href={e.href as any}
                            className="block hover:bg-brand-800/50"
                          >
                            {content}
                          </Link>
                        ) : (
                          content
                        )}
                      </li>
                    );
                  })}
                </ul>
              </section>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
