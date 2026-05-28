"use client";

import { useEffect, useMemo, useState } from "react";
import {
  Briefcase,
  Clock,
  Code2,
  FileText,
  Loader2,
  Receipt,
  TrendingUp,
  Trello,
  Users
} from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { Link } from "@/i18n/navigation";
import { authedFetch } from "@/lib/auth";
import { useDevlogLayout } from "./layout";

type Lead = { id: number; status: string; created_at: string };
type Soumission = {
  id: number;
  status: string;
  amount: number | null;
  created_at: string;
};
type Client = { id: number; status: string };
type Project = { id: number; status: string };
type Invoice = {
  id: number;
  status: string;
  amount: number | null;
  due_date: string | null;
  issued_date: string | null;
};
type TimeEntry = {
  id: number;
  work_date: string;
  hours: number;
};

type Period = "7d" | "30d" | "month" | "quarter" | "year";

const PERIOD_LABELS: Record<Period, string> = {
  "7d": "7 jours",
  "30d": "30 jours",
  month: "Ce mois",
  quarter: "Trimestre",
  year: "Année"
};

function periodStart(p: Period): Date {
  const d = new Date();
  d.setHours(0, 0, 0, 0);
  if (p === "7d") {
    d.setDate(d.getDate() - 6);
  } else if (p === "30d") {
    d.setDate(d.getDate() - 29);
  } else if (p === "month") {
    d.setDate(1);
  } else if (p === "quarter") {
    const m = d.getMonth();
    d.setMonth(m - (m % 3));
    d.setDate(1);
  } else if (p === "year") {
    d.setMonth(0);
    d.setDate(1);
  }
  return d;
}

function fmtMoney(n: number): string {
  return n.toLocaleString("fr-CA", {
    style: "currency",
    currency: "CAD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2
  });
}

function dayKey(s: string): string {
  return s.slice(0, 10);
}

export default function DevlogHomePage() {
  const { onOpenSidebar } = useDevlogLayout();
  const [leads, setLeads] = useState<Lead[]>([]);
  const [soumissions, setSoumissions] = useState<Soumission[]>([]);
  const [clients, setClients] = useState<Client[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [invoices, setInvoices] = useState<Invoice[]>([]);
  const [entries, setEntries] = useState<TimeEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [period, setPeriod] = useState<Period>("30d");

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [lr, sr, cr, pr, ir, er] = await Promise.all([
          authedFetch("/api/v1/devlog/leads"),
          authedFetch("/api/v1/devlog/soumissions"),
          authedFetch("/api/v1/devlog/clients"),
          authedFetch("/api/v1/devlog/projects"),
          authedFetch("/api/v1/devlog/invoices"),
          authedFetch("/api/v1/devlog/time-entries")
        ]);
        if (cancelled) return;
        if (lr.ok) setLeads(await lr.json());
        if (sr.ok) setSoumissions(await sr.json());
        if (cr.ok) setClients(await cr.json());
        if (pr.ok) setProjects(await pr.json());
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

  const from = useMemo(() => periodStart(period), [period]);

  // ---- KPIs principaux ----
  const activeLeads = leads.filter(
    (l) => l.status !== "gagne" && l.status !== "perdu"
  ).length;

  const inPeriod = (s: { created_at: string }) =>
    new Date(s.created_at) >= from;

  const soumissionsEnvoyees = soumissions.filter(
    (s) => s.status === "envoyee" && inPeriod(s)
  );
  const soumissionsEnvoyeesTotal = soumissionsEnvoyees.reduce(
    (sum, s) => sum + (s.amount || 0),
    0
  );
  const soumissionsAcceptees = soumissions.filter(
    (s) => s.status === "acceptee" && inPeriod(s)
  );
  const soumissionsAccepteesTotal = soumissionsAcceptees.reduce(
    (sum, s) => sum + (s.amount || 0),
    0
  );

  const totalSoumissions = soumissions.filter(inPeriod).length;
  const conversionRate =
    totalSoumissions > 0
      ? Math.round((soumissionsAcceptees.length / totalSoumissions) * 100)
      : 0;
  const avgDeal =
    soumissionsAcceptees.length > 0
      ? soumissionsAccepteesTotal / soumissionsAcceptees.length
      : 0;

  // ---- KPI bas ----
  const activeProjects = projects.filter(
    (p) => p.status === "en_cours" || p.status === "en_attente"
  ).length;

  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const monthStart = new Date(today.getFullYear(), today.getMonth(), 1);
  const weekStart = new Date(today);
  weekStart.setDate(today.getDate() - today.getDay());

  const revenuMois = invoices
    .filter(
      (i) =>
        i.status === "payee" &&
        i.issued_date &&
        new Date(i.issued_date) >= monthStart
    )
    .reduce((sum, i) => sum + (i.amount || 0), 0);

  const heuresSemaine = entries
    .filter((e) => new Date(e.work_date) >= weekStart)
    .reduce((sum, e) => sum + (e.hours || 0), 0);

  const unpaidInvoices = invoices.filter((i) => i.status === "envoyee");
  const unpaidTotal = unpaidInvoices.reduce(
    (sum, i) => sum + (i.amount || 0),
    0
  );
  const lateInvoices = unpaidInvoices.filter(
    (i) => i.due_date && new Date(i.due_date) < today
  );
  const lateTotal = lateInvoices.reduce(
    (sum, i) => sum + (i.amount || 0),
    0
  );

  // ---- Graphique simple : barres par jour sur la période ----
  const chartDays = useMemo(() => {
    const days: { date: string; sent: number; won: number }[] = [];
    const cursor = new Date(from);
    while (cursor <= today) {
      days.push({
        date: cursor.toISOString().slice(0, 10),
        sent: 0,
        won: 0
      });
      cursor.setDate(cursor.getDate() + 1);
    }
    const byKey = new Map(days.map((d) => [d.date, d]));
    for (const s of soumissions) {
      const k = dayKey(s.created_at);
      const d = byKey.get(k);
      if (!d) continue;
      if (s.status === "envoyee") d.sent += s.amount || 0;
      if (s.status === "acceptee") d.won += s.amount || 0;
    }
    return days;
  }, [from, soumissions, today]);

  const chartMax = Math.max(
    1,
    ...chartDays.map((d) => Math.max(d.sent, d.won))
  );

  return (
    <div className="min-h-screen bg-brand-950">
      <AppTopbar
        breadcrumbs={[{ label: "Développement logiciel" }]}
        onOpenSidebar={onOpenSidebar}
      />

      <div className="mx-auto max-w-6xl px-4 py-6 lg:px-6">
        <header className="flex items-start justify-between gap-3">
          <div className="flex items-center gap-3">
            <span className="flex h-12 w-12 items-center justify-center rounded-xl bg-blue-500/15 text-blue-400">
              <Code2 className="h-6 w-6" />
            </span>
            <div>
              <h1 className="text-xl font-bold text-white">Accueil — Dév. logiciel</h1>
              <p className="text-sm text-white/60">
                Vue d&apos;ensemble du pôle pour la période sélectionnée.
              </p>
            </div>
          </div>
          {/* Sélecteur de période — pattern Construction. */}
          <div className="hidden gap-1 rounded-lg border border-brand-800 bg-brand-900 p-1 sm:flex">
            {(Object.keys(PERIOD_LABELS) as Period[]).map((p) => (
              <button
                key={p}
                type="button"
                onClick={() => setPeriod(p)}
                className={`rounded-md px-2.5 py-1 text-xs font-semibold transition ${
                  period === p
                    ? "bg-blue-500 text-white"
                    : "text-white/60 hover:bg-brand-800 hover:text-white"
                }`}
              >
                {PERIOD_LABELS[p]}
              </button>
            ))}
          </div>
        </header>

        {loading ? (
          <div className="mt-10 flex justify-center">
            <Loader2 className="h-6 w-6 animate-spin text-blue-500" />
          </div>
        ) : (
          <>
            {/* Tuiles principales */}
            <div className="mt-6 grid gap-3 sm:grid-cols-3">
              <BigTile
                href="/dev-logiciel/leads"
                icon={Users}
                tone="sky"
                label="Leads actifs"
                value={String(activeLeads)}
                sub="dans le pipeline"
              />
              <BigTile
                href="/dev-logiciel/soumissions"
                icon={FileText}
                tone="blue"
                label="Soumissions envoyées"
                value={fmtMoney(soumissionsEnvoyeesTotal)}
                sub={`${soumissionsEnvoyees.length} sur la période`}
              />
              <BigTile
                href="/dev-logiciel/soumissions"
                icon={TrendingUp}
                tone="emerald"
                label="Ventes acceptées"
                value={fmtMoney(soumissionsAccepteesTotal)}
                sub={`${soumissionsAcceptees.length} sur la période`}
              />
            </div>

            {/* Mini stats */}
            <div className="mt-3 grid gap-3 sm:grid-cols-3">
              <MiniStat
                label="Taux de conversion"
                value={`${conversionRate} %`}
              />
              <MiniStat
                label="Transaction moyenne"
                value={fmtMoney(avgDeal)}
              />
              <MiniStat
                label="Soumissions sur la période"
                value={String(totalSoumissions)}
              />
            </div>

            {/* Graphique soumissions vs ventes */}
            <div className="mt-6 rounded-2xl border border-brand-800 bg-brand-900 p-5">
              <div className="flex items-center justify-between">
                <h2 className="text-sm font-semibold uppercase tracking-wider text-blue-300">
                  Soumissions vs ventes — {PERIOD_LABELS[period]}
                </h2>
                <div className="flex items-center gap-3 text-[11px]">
                  <span className="inline-flex items-center gap-1.5 text-white/60">
                    <span className="h-2 w-2 rounded-full bg-blue-400" />
                    Envoyées
                  </span>
                  <span className="inline-flex items-center gap-1.5 text-white/60">
                    <span className="h-2 w-2 rounded-full bg-emerald-400" />
                    Acceptées
                  </span>
                </div>
              </div>
              <div className="mt-4 flex h-32 items-end gap-1">
                {chartDays.map((d) => (
                  <div
                    key={d.date}
                    title={`${d.date} — Env. ${fmtMoney(d.sent)} · Acc. ${fmtMoney(d.won)}`}
                    className="flex flex-1 items-end gap-0.5"
                  >
                    <div
                      className="flex-1 rounded-t-sm bg-blue-500/70"
                      style={{
                        height: `${(d.sent / chartMax) * 100}%`,
                        minHeight: d.sent > 0 ? "2px" : 0
                      }}
                    />
                    <div
                      className="flex-1 rounded-t-sm bg-emerald-500/70"
                      style={{
                        height: `${(d.won / chartMax) * 100}%`,
                        minHeight: d.won > 0 ? "2px" : 0
                      }}
                    />
                  </div>
                ))}
              </div>
            </div>

            {/* Alerte impayés en retard */}
            {lateInvoices.length > 0 ? (
              <div className="mt-4 rounded-xl border border-rose-500/40 bg-rose-500/10 px-4 py-3 text-sm text-rose-300">
                <strong>{lateInvoices.length} facture(s) en retard</strong> —
                total : {fmtMoney(lateTotal)}.{" "}
                <Link
                  href={"/dev-logiciel/facturation" as any}
                  className="underline hover:text-white"
                >
                  Voir la facturation
                </Link>
              </div>
            ) : null}

            {/* 4 KPI cards bas */}
            <div className="mt-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <KpiCard
                href="/dev-logiciel/facturation"
                icon={Receipt}
                label="Factures impayées"
                value={fmtMoney(unpaidTotal)}
                sub={`${unpaidInvoices.length} en attente`}
                tone={lateInvoices.length > 0 ? "rose" : "blue"}
              />
              <KpiCard
                href="/dev-logiciel/facturation"
                icon={TrendingUp}
                label="Revenu ce mois"
                value={fmtMoney(revenuMois)}
                tone="emerald"
              />
              <KpiCard
                href="/dev-logiciel/projets"
                icon={Briefcase}
                label="Projets actifs"
                value={String(activeProjects)}
                tone="violet"
              />
              <KpiCard
                href="/dev-logiciel/heures"
                icon={Clock}
                label="Heures cette semaine"
                value={`${heuresSemaine.toLocaleString("fr-CA", {
                  maximumFractionDigits: 1
                })} h`}
                tone="amber"
              />
            </div>

            {/* Raccourcis */}
            <div className="mt-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <Shortcut
                href="/dev-logiciel/leads"
                icon={Trello}
                label="CRM"
                sub="Pipeline du closer"
              />
              <Shortcut
                href="/dev-logiciel/soumissions"
                icon={FileText}
                label="Soumissions"
                sub="Devis envoyés"
              />
              <Shortcut
                href="/dev-logiciel/projets"
                icon={Briefcase}
                label="Projets"
                sub="Suivi des dévs"
              />
              <Shortcut
                href="/dev-logiciel/heures"
                icon={Clock}
                label="Heures"
                sub="Saisie & total"
              />
            </div>
          </>
        )}
      </div>
    </div>
  );
}

function BigTile({
  href,
  icon: Icon,
  tone,
  label,
  value,
  sub
}: {
  href: string;
  icon: React.ComponentType<{ className?: string }>;
  tone: "sky" | "blue" | "emerald";
  label: string;
  value: string;
  sub?: string;
}) {
  const toneCls =
    tone === "sky"
      ? "bg-sky-500/15 text-sky-300"
      : tone === "blue"
      ? "bg-blue-500/15 text-blue-300"
      : "bg-emerald-500/15 text-emerald-300";
  return (
    <Link
      href={href as any}
      className="group flex items-center gap-4 rounded-2xl border border-brand-800 bg-brand-900 p-5 transition hover:border-blue-500/60 hover:bg-brand-800"
    >
      <span className={`flex h-12 w-12 items-center justify-center rounded-xl ${toneCls}`}>
        <Icon className="h-6 w-6" />
      </span>
      <div className="min-w-0 flex-1">
        <p className="text-xs uppercase tracking-wide text-white/50">
          {label}
        </p>
        <p className="mt-0.5 text-2xl font-bold text-white">{value}</p>
        {sub ? <p className="text-xs text-white/40">{sub}</p> : null}
      </div>
    </Link>
  );
}

function MiniStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-brand-800 bg-brand-900 p-4">
      <p className="text-xs uppercase tracking-wide text-white/50">
        {label}
      </p>
      <p className="mt-1 text-xl font-bold text-white">{value}</p>
    </div>
  );
}

function KpiCard({
  href,
  icon: Icon,
  label,
  value,
  sub,
  tone
}: {
  href: string;
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  value: string;
  sub?: string;
  tone: "blue" | "emerald" | "violet" | "amber" | "rose";
}) {
  const toneCls = {
    blue: "text-blue-300",
    emerald: "text-emerald-300",
    violet: "text-violet-300",
    amber: "text-amber-300",
    rose: "text-rose-300"
  }[tone];
  return (
    <Link
      href={href as any}
      className="group rounded-xl border border-brand-800 bg-brand-900 p-4 transition hover:border-blue-500/60"
    >
      <Icon className={`h-5 w-5 ${toneCls}`} />
      <p className="mt-2 text-[11px] uppercase tracking-wide text-white/50">
        {label}
      </p>
      <p className={`mt-1 text-lg font-bold ${toneCls}`}>{value}</p>
      {sub ? <p className="text-[11px] text-white/40">{sub}</p> : null}
    </Link>
  );
}

function Shortcut({
  href,
  icon: Icon,
  label,
  sub
}: {
  href: string;
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  sub: string;
}) {
  return (
    <Link
      href={href as any}
      className="group flex items-center gap-3 rounded-xl border border-brand-800 bg-brand-900 p-4 transition hover:border-blue-500/60 hover:bg-brand-800"
    >
      <span className="flex h-10 w-10 items-center justify-center rounded-lg bg-blue-500/15 text-blue-400 group-hover:bg-blue-500 group-hover:text-white">
        <Icon className="h-5 w-5" />
      </span>
      <div>
        <p className="text-sm font-semibold text-white">{label}</p>
        <p className="text-xs text-white/50">{sub}</p>
      </div>
    </Link>
  );
}
