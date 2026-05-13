"use client";

import { useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  ArrowDownAZ,
  ChevronRight,
  GripVertical,
  Loader2,
  Plus,
  Sparkles,
  TrendingUp
} from "lucide-react";

import { Link } from "@/i18n/navigation";
import { authedFetch } from "@/lib/auth";
import { QGTopbar, useEntreprisesLayout } from "./layout";
import { useCurrentUser } from "@/hooks/use-current-user";

// ───────────────────────────────────────────────────────────────────────
// Types
// ───────────────────────────────────────────────────────────────────────

type StatsOverview = {
  entreprises_count: number;
  taches_open: number;
  taches_in_progress: number;
  taches_urgent: number;
  taches_done_30d: number;
  avg_score_open: number | null;
};

type EntrepriseHealth = {
  entreprise_id: number;
  name: string;
  color_accent: string;
  type: string;
  description: string | null;
  health_score: number;
  health_label: "good" | "warn" | "risk";
  taches_open: number;
  taches_done: number;
  taches_total: number;
  taches_overdue: number;
  taches_urgent: number;
  last_briefing_headline: string | null;
};

type DailyBriefing = {
  id: number;
  entreprise_id: number;
  period_start: string;
  headline: string;
  summary_text: string;
  highlights: string[];
  provider: string | null;
  model_used: string | null;
  created_at: string;
};

const TYPE_LABELS: Record<string, string> = {
  gestion: "Gestion",
  construction: "Construction",
  immobilier: "Immobilier",
  autre: "Autre"
};

const FRENCH_DAYS = [
  "DIMANCHE", "LUNDI", "MARDI", "MERCREDI",
  "JEUDI", "VENDREDI", "SAMEDI"
];
const FRENCH_MONTHS = [
  "JANV.", "FÉVR.", "MARS", "AVR.", "MAI", "JUIN",
  "JUIL.", "AOÛT", "SEPT.", "OCT.", "NOV.", "DÉC."
];

function formatDateBadge(d: Date): string {
  return `${FRENCH_DAYS[d.getDay()]} · ${String(d.getDate()).padStart(2, "0")} ${FRENCH_MONTHS[d.getMonth()]} ${d.getFullYear()}`;
}

function firstName(email?: string): string {
  if (!email) return "à toi";
  const local = email.split("@")[0] || "";
  if (!local) return "à toi";
  // Ex. "sgiguere" → "Steven"  (on ne sait pas, on prend la 1ère lettre)
  // Mieux : extrait le prénom depuis full_name si présent. Ici on
  // n'a que email donc on prend le local part avec capitale.
  const cleaned = local.replace(/[._-]+/g, " ").trim();
  const word = cleaned.split(" ")[0] || cleaned;
  return word.charAt(0).toUpperCase() + word.slice(1);
}

// ───────────────────────────────────────────────────────────────────────
// Page
// ───────────────────────────────────────────────────────────────────────

export default function EntreprisesDashboard() {
  const { user } = useCurrentUser();
  const {
    entreprises: layoutEntreprises,
    reorderEntreprises
  } = useEntreprisesLayout();
  const [stats, setStats] = useState<StatsOverview | null>(null);
  const [health, setHealth] = useState<EntrepriseHealth[]>([]);
  const [topBriefing, setTopBriefing] = useState<DailyBriefing | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [alphaSort, setAlphaSort] = useState(false);
  const [dragId, setDragId] = useState<number | null>(null);

  // Ordre des entreprises pour la table : manuel (via DB) ou alpha.
  const orderedHealth = useMemo(() => {
    if (health.length === 0) return health;
    if (alphaSort) {
      return [...health].sort((a, b) =>
        (a.name || "").localeCompare(b.name || "", "fr", {
          sensitivity: "base"
        })
      );
    }
    // Ordre manuel : on suit l'ordre de layoutEntreprises (qui reflète
    // l'ordre persisté en DB).
    const indexById = new Map(
      layoutEntreprises.map((e, i) => [e.id, i] as const)
    );
    return [...health].sort((a, b) => {
      const ia = indexById.get(a.entreprise_id) ?? 9999;
      const ib = indexById.get(b.entreprise_id) ?? 9999;
      return ia - ib;
    });
  }, [health, alphaSort, layoutEntreprises]);

  function handleDrop(targetId: number) {
    const did = dragId;
    setDragId(null);
    if (did == null || did === targetId) return;
    // Reconstruit l'ordre demandé en se basant sur layoutEntreprises.
    const ids = layoutEntreprises.map((e) => e.id);
    const fromIdx = ids.indexOf(did);
    const toIdx = ids.indexOf(targetId);
    if (fromIdx < 0 || toIdx < 0) return;
    ids.splice(fromIdx, 1);
    ids.splice(toIdx, 0, did);
    void reorderEntreprises(ids);
  }

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      setLoading(true);
      setError(null);
      try {
        const [statsRes, healthRes] = await Promise.all([
          authedFetch("/api/v1/entreprises/stats/overview"),
          authedFetch("/api/v1/entreprises/health")
        ]);
        if (cancelled) return;
        if (!healthRes.ok) {
          if (healthRes.status === 403) {
            throw new Error(
              "Accès refusé — ton compte n'a pas le volet Gestion d'entreprises."
            );
          }
          throw new Error(`HTTP ${healthRes.status}`);
        }
        const h = (await healthRes.json()) as EntrepriseHealth[];
        const s = statsRes.ok
          ? ((await statsRes.json()) as StatsOverview)
          : null;
        setHealth(h);
        setStats(s);

        // Briefing du jour : si une entreprise est marquée comme
        // « mère » du groupe (is_parent_company), son briefing
        // couvre toutes les entreprises actives → on l'affiche en
        // priorité. Sinon : on prend l'entreprise avec le score de
        // santé le plus bas (la plus à risque) en fallback.
        let targetId: number | null = null;
        try {
          const r = await authedFetch(
            "/api/v1/entreprises?limit=200"
          );
          if (r.ok) {
            const all = (await r.json()) as Array<{
              id: number;
              is_parent_company?: boolean;
              is_active?: boolean;
            }>;
            const parent = all.find(
              (x) => x.is_parent_company && x.is_active !== false
            );
            if (parent) targetId = parent.id;
          }
        } catch {
          /* fallback below */
        }
        if (targetId == null) {
          const sorted = [...h].sort(
            (a, b) => a.health_score - b.health_score
          );
          const target = sorted[0];
          if (target) targetId = target.entreprise_id;
        }
        if (targetId != null) {
          const r = await authedFetch(
            `/api/v1/entreprises/${targetId}/daily-pulse`
          );
          if (!cancelled && r.ok) {
            const data = (await r.json()) as DailyBriefing | null;
            setTopBriefing(data);
          }
        }
      } catch (err) {
        if (!cancelled) setError((err as Error).message);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const today = new Date();
  const greetingName = firstName(user?.email);
  const totalEntreprises = layoutEntreprises.length || stats?.entreprises_count || 0;
  const alertsCount = useMemo(() => {
    return health.reduce(
      (sum, e) => sum + (e.taches_overdue || 0) + (e.health_label === "risk" ? 1 : 0),
      0
    );
  }, [health]);

  const subtitle = (
    <>
      {formatDateBadge(today)}
      {totalEntreprises > 0 ? (
        <>{" · "}{totalEntreprises} ENTREPRISE{totalEntreprises > 1 ? "S" : ""}</>
      ) : null}
      {alertsCount > 0 ? (
        <>{" · "}<span className="text-[#ff5566]">{alertsCount} ALERTE{alertsCount > 1 ? "S" : ""} ACTIVE{alertsCount > 1 ? "S" : ""}</span></>
      ) : null}
    </>
  );

  return (
    <>
      <QGTopbar
        greeting={
          <>
            Bonjour,{" "}
            <span
              className="italic"
              style={{
                color: "var(--qg-accent)",
                fontFamily: "var(--font-fraunces, Georgia, serif)"
              }}
            >
              {greetingName}
            </span>
          </>
        }
        subtitle={subtitle}
        rightSlot={
          <>
            <CTAButton href="/entreprises/taches" variant="secondary">
              <Sparkles className="h-3.5 w-3.5" />
              Briefing complet
            </CTAButton>
            <CTAButton href="/entreprises/taches" variant="primary">
              <Plus className="h-3.5 w-3.5" />
              Nouvelle tâche
            </CTAButton>
          </>
        }
      />

      <div className="px-5 py-6 lg:px-8">
        {error ? (
          <p className="mb-4 rounded-md border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-300">
            {error}
          </p>
        ) : null}

        {/* 4 KPI cards */}
        <section className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <KpiCard
            label="Tâches ouvertes · Global"
            value={
              loading
                ? "…"
                : (stats?.taches_open ?? 0).toLocaleString("fr-CA")
            }
            sub={
              stats && stats.taches_in_progress > 0
                ? `${stats.taches_in_progress} en cours`
                : "—"
            }
            tone="info"
            href="/entreprises/taches"
          />
          <KpiCard
            label="Urgentes · 7 prochains jours"
            value={
              loading
                ? "…"
                : (stats?.taches_urgent ?? 0).toLocaleString("fr-CA")
            }
            sub={
              stats && stats.taches_urgent > 0
                ? "À prioriser cette semaine"
                : "Aucune urgence"
            }
            tone={stats && stats.taches_urgent > 0 ? "warning" : "muted"}
            href="/entreprises/taches?filter=urgent"
          />
          <KpiCard
            label="Terminées · 30 derniers jours"
            value={
              loading
                ? "…"
                : (stats?.taches_done_30d ?? 0).toLocaleString("fr-CA")
            }
            sub="Productivité"
            tone="success"
            href="/entreprises/taches?filter=done"
          />
          <KpiCard
            label="Score moyen · Tâches ouvertes"
            value={
              loading
                ? "…"
                : stats?.avg_score_open != null
                ? stats.avg_score_open.toFixed(1)
                : "—"
            }
            sub="ICE × urgence"
            tone="lime"
            href="/entreprises/taches"
          />
        </section>

        {/* État des entreprises + Briefing */}
        <section className="mt-8 grid grid-cols-1 gap-5 xl:grid-cols-[1.6fr_1fr]">
          <div
            className="rounded-xl"
            style={{
              backgroundColor: "var(--qg-card-bg)",
              border: "1px solid var(--qg-border)"
            }}
          >
            <div className="flex items-center justify-between px-5 pt-5">
              <h2
                className="text-[18px] font-bold text-[var(--qg-text)]"
                style={{
                  fontFamily: "var(--font-fraunces, Georgia, serif)"
                }}
              >
                Mes{" "}
                <span className="italic" style={{ color: "var(--qg-accent)" }}>
                  entreprises
                </span>
              </h2>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => setAlphaSort((v) => !v)}
                  title={
                    alphaSort
                      ? "Retour à l'ordre manuel (drag & drop)"
                      : "Trier par ordre alphabétique"
                  }
                  className={`inline-flex items-center gap-1 rounded-md border px-2 py-1 text-[11px] font-semibold transition ${
                    alphaSort
                      ? "border-[var(--qg-accent)] bg-[var(--qg-bg-alt)] text-[var(--qg-accent)]"
                      : "border-[var(--qg-border)] text-[var(--qg-text-soft)] hover:bg-[var(--qg-bg-alt)]"
                  }`}
                >
                  <ArrowDownAZ className="h-3.5 w-3.5" />
                  {alphaSort ? "Tri A–Z" : "Trier A–Z"}
                </button>
                <Link
                  // eslint-disable-next-line @typescript-eslint/no-explicit-any
                  href={"/entreprises/taches" as any}
                  className="text-[11px] text-[var(--qg-text-soft)] hover:text-[var(--qg-accent)]"
                >
                  Voir tout →
                </Link>
              </div>
            </div>
            {!alphaSort ? (
              <p className="px-5 pt-1 text-[10px] text-[var(--qg-text-soft)]">
                Glisse-déplace une ligne pour réordonner. Cliquer A–Z
                pour passer en tri alphabétique.
              </p>
            ) : null}

            {loading ? (
              <div className="flex min-h-[200px] items-center justify-center">
                <Loader2 className="h-5 w-5 animate-spin text-[var(--qg-accent)]" />
              </div>
            ) : health.length === 0 ? (
              <EmptyEntreprises />
            ) : (
              <table className="mt-4 w-full text-[13px]">
                <thead>
                  <tr
                    className="text-[10px] uppercase tracking-wider text-[var(--qg-text-soft)]"
                    style={{ borderBottom: "1px solid var(--qg-border)" }}
                  >
                    {!alphaSort ? (
                      <th className="w-6 px-2 py-2.5"></th>
                    ) : null}
                    <th className="px-5 py-2.5 text-left font-semibold">
                      Entreprise · Domaine
                    </th>
                    <th className="px-3 py-2.5 text-left font-semibold">
                      Santé
                    </th>
                    <th className="px-3 py-2.5 text-right font-semibold">
                      Tâches
                    </th>
                    <th className="w-8 px-3 py-2.5"></th>
                  </tr>
                </thead>
                <tbody>
                  {orderedHealth.map((e) => (
                    <EntrepriseRow
                      key={e.entreprise_id}
                      e={e}
                      draggable={!alphaSort}
                      isDragging={dragId === e.entreprise_id}
                      onDragStart={() => setDragId(e.entreprise_id)}
                      onDragEnd={() => setDragId(null)}
                      onDragOver={(ev) => ev.preventDefault()}
                      onDrop={() => handleDrop(e.entreprise_id)}
                    />
                  ))}
                </tbody>
              </table>
            )}
          </div>

          <BriefingCard briefing={topBriefing} loading={loading} />
        </section>
      </div>
    </>
  );
}

// ───────────────────────────────────────────────────────────────────────
// Sub-components
// ───────────────────────────────────────────────────────────────────────

function CTAButton({
  href,
  children,
  variant
}: {
  href: string;
  children: React.ReactNode;
  variant: "primary" | "secondary";
}) {
  const isPrimary = variant === "primary";
  return (
    <Link
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      href={href as any}
      className={`inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-[12px] font-bold transition ${
        isPrimary
          ? ""
          : "border border-[var(--qg-border)] bg-[var(--qg-card-bg)] text-[var(--qg-text-muted)] hover:border-[var(--qg-text-faint)] hover:text-[var(--qg-text)]"
      }`}
      style={
        isPrimary
          ? {
              backgroundColor: "var(--qg-accent)",
              color: "var(--qg-bg)",
              boxShadow: "0 0 24px -8px rgba(212,255,58,0.5)"
            }
          : undefined
      }
    >
      {children}
    </Link>
  );
}

function KpiCard({
  label,
  value,
  sub,
  tone,
  href
}: {
  label: string;
  value: string;
  sub: string;
  tone: "info" | "warning" | "success" | "muted" | "lime";
  /** Si défini, la carte devient cliquable (Link) → page filtrée. */
  href?: string;
}) {
  const toneColor =
    tone === "warning"
      ? "#ffaa33"
      : tone === "success"
      ? "#4ade80"
      : tone === "lime"
      ? "var(--qg-accent)"
      : tone === "info"
      ? "#60a5fa"
      : "var(--qg-text-soft)";
  const Wrapper: React.ElementType = href ? Link : "div";
  const wrapperProps: Record<string, unknown> = href
    ? // eslint-disable-next-line @typescript-eslint/no-explicit-any
      { href: href as any }
    : {};
  return (
    <Wrapper
      {...wrapperProps}
      className={`rounded-xl px-5 py-5 ${
        href ? "transition hover:border-accent-500" : ""
      }`}
      style={{
        backgroundColor: "var(--qg-card-bg)",
        border: "1px solid var(--qg-border)"
      }}
    >
      <p className="text-[10px] uppercase tracking-[0.16em] text-[var(--qg-text-soft)]">
        {label}
      </p>
      <p
        className="mt-2 text-[28px] font-bold leading-tight text-[var(--qg-text)] sm:text-[32px]"
        style={{
          fontFamily: "var(--font-fraunces, Georgia, serif)"
        }}
      >
        {value}
      </p>
      <p
        className="mt-1.5 inline-flex items-center gap-1 text-[11px]"
        style={{ color: toneColor }}
      >
        ▲ {sub}
      </p>
    </Wrapper>
  );
}

function EntrepriseRow({
  e,
  draggable,
  isDragging,
  onDragStart,
  onDragEnd,
  onDragOver,
  onDrop
}: {
  e: EntrepriseHealth;
  draggable?: boolean;
  isDragging?: boolean;
  onDragStart?: () => void;
  onDragEnd?: () => void;
  onDragOver?: (ev: React.DragEvent) => void;
  onDrop?: () => void;
}) {
  const initials = e.name
    .split(" ")
    .map((w) => w[0])
    .filter(Boolean)
    .slice(0, 2)
    .join("")
    .toUpperCase();
  const barColor =
    e.health_label === "risk"
      ? "#ff5566"
      : e.health_label === "warn"
      ? "#ffaa33"
      : "#4ade80";
  const overdueAlert = e.taches_overdue > 0;
  return (
    <tr
      draggable={!!draggable}
      onDragStart={onDragStart}
      onDragEnd={onDragEnd}
      onDragOver={onDragOver}
      onDrop={onDrop}
      className={`text-[13px] hover:bg-[var(--qg-bg-alt)] ${
        isDragging ? "opacity-40" : ""
      } ${draggable ? "cursor-grab active:cursor-grabbing" : ""}`}
      style={{ borderBottom: "1px solid var(--qg-border-soft)" }}
    >
      {draggable ? (
        <td className="w-6 px-2 py-3 text-center text-[var(--qg-text-soft)]">
          <GripVertical className="inline-block h-3.5 w-3.5" />
        </td>
      ) : null}
      <td className="px-5 py-3">
        <Link
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          href={`/entreprises/${e.entreprise_id}` as any}
          className="flex items-center gap-3"
        >
          <span
            className="flex h-8 w-8 items-center justify-center rounded-md text-[10px] font-bold uppercase"
            style={{
              backgroundColor: e.color_accent + "26",
              color: e.color_accent
            }}
          >
            {initials || "—"}
          </span>
          <span className="min-w-0">
            <span className="block truncate font-semibold text-[var(--qg-text)]">
              {e.name}
            </span>
            <span className="block truncate text-[10px] uppercase tracking-wider text-[var(--qg-text-soft)]">
              {TYPE_LABELS[e.type] || e.type}
              {e.description ? ` · ${e.description.slice(0, 40)}` : ""}
            </span>
          </span>
        </Link>
      </td>
      <td className="px-3 py-3">
        <div className="flex items-center gap-3">
          <div
            className="h-1 w-20 overflow-hidden rounded-full"
            style={{ backgroundColor: "var(--qg-border)" }}
          >
            <div
              className="h-full rounded-full transition-all"
              style={{
                width: `${Math.max(8, e.health_score)}%`,
                backgroundColor: barColor
              }}
            />
          </div>
          <span
            className="text-[12px] font-semibold tabular-nums"
            style={{
              color: barColor,
              fontFamily: "var(--font-mono, ui-monospace), monospace"
            }}
          >
            {e.health_score}
          </span>
        </div>
      </td>
      <td className="px-3 py-3 text-right">
        {overdueAlert ? (
          <span className="inline-flex items-center gap-1 rounded-md border border-[#ff5566]/40 bg-[#ff5566]/10 px-1.5 py-0.5 text-[11px] font-semibold text-[#ff5566]">
            <AlertTriangle className="h-2.5 w-2.5" />
            {e.taches_open} <span className="opacity-50">/ {e.taches_total}</span>
          </span>
        ) : (
          <span
            className="text-[12px] tabular-nums text-[var(--qg-text-muted)]"
            style={{ fontFamily: "var(--font-mono, ui-monospace), monospace" }}
          >
            {e.taches_open}
            <span className="text-[var(--qg-text-soft)]"> / {e.taches_total}</span>
          </span>
        )}
      </td>
      <td className="px-3 py-3 text-right text-[var(--qg-text-faint)]">
        <ChevronRight className="inline h-4 w-4" />
      </td>
    </tr>
  );
}

function EmptyEntreprises() {
  return (
    <div className="px-6 py-12 text-center">
      <p className="text-sm text-[var(--qg-text-muted)]">
        Aucune entreprise. Crée-en une depuis le menu de gauche.
      </p>
    </div>
  );
}

function BriefingCard({
  briefing,
  loading
}: {
  briefing: DailyBriefing | null;
  loading: boolean;
}) {
  return (
    <aside
      className="rounded-xl"
      style={{
        backgroundColor: "var(--qg-card-bg)",
        border: "1px solid var(--qg-border)"
      }}
    >
      <div className="flex items-baseline justify-between px-5 pt-5">
        <h2
          className="text-[18px] font-bold text-[var(--qg-text)]"
          style={{ fontFamily: "var(--font-fraunces, Georgia, serif)" }}
        >
          Briefing{" "}
          <span className="italic" style={{ color: "var(--qg-accent)" }}>
            du jour
          </span>
        </h2>
        {briefing ? (
          <span
            className="text-[10px] uppercase tracking-wider text-[var(--qg-text-soft)]"
            style={{ fontFamily: "var(--font-mono, ui-monospace), monospace" }}
          >
            {new Date(briefing.created_at).toLocaleTimeString("fr-CA", {
              hour: "2-digit",
              minute: "2-digit"
            })}
          </span>
        ) : null}
      </div>

      <div className="px-5 pb-5 pt-3">
        <div className="mb-3 flex items-center gap-2 text-[10px] uppercase tracking-wider">
          <span className="relative flex h-2 w-2">
            <span
              className="absolute inline-flex h-full w-full animate-ping rounded-full opacity-60"
              style={{ backgroundColor: "var(--qg-accent)" }}
            />
            <span
              className="relative inline-flex h-2 w-2 rounded-full"
              style={{ backgroundColor: "var(--qg-accent)" }}
            />
          </span>
          <span className="font-bold" style={{ color: "var(--qg-accent)" }}>
            Analyse IA
          </span>
          {briefing?.provider ? (
            <>
              <span className="text-[var(--qg-text-faint)]">·</span>
              <span className="text-[var(--qg-text-muted)]">{briefing.provider}</span>
            </>
          ) : null}
        </div>

        {loading ? (
          <p className="text-[13px] text-[var(--qg-text-soft)]">Chargement…</p>
        ) : !briefing ? (
          <div className="rounded-md border border-dashed border-[var(--qg-border)] p-4 text-center text-[12px] text-[var(--qg-text-soft)]">
            Aucun briefing aujourd&apos;hui. Ouvre une entreprise pour
            en générer un.
          </div>
        ) : (
          <>
            <p className="mb-2 text-[14px] font-semibold leading-snug text-[var(--qg-text)]">
              {briefing.headline}
            </p>
            <p className="text-[13px] leading-relaxed text-[var(--qg-text-muted)]">
              {briefing.summary_text}
            </p>
            {briefing.highlights && briefing.highlights.length > 0 ? (
              <ul className="mt-4 space-y-2">
                {briefing.highlights.map((h, i) => (
                  <HighlightBullet key={i} text={h} index={i} />
                ))}
              </ul>
            ) : null}
            <Link
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
              href={`/entreprises/${briefing.entreprise_id}` as any}
              className="mt-4 inline-flex items-center gap-1 text-[11px] font-semibold"
              style={{ color: "var(--qg-accent)" }}
            >
              Voir l&apos;entreprise →
            </Link>
          </>
        )}
      </div>
    </aside>
  );
}

function HighlightBullet({ text, index }: { text: string; index: number }) {
  // Cycle 3 tons : risque (rose), opportunité (lime), synergie (info)
  const tones = [
    { icon: "⚠", color: "#ff5566", label: "Risque" },
    { icon: "⚡", color: "var(--qg-accent)", label: "Opportunité" },
    { icon: "◎", color: "#60a5fa", label: "Synergie" }
  ] as const;
  const tone = tones[index % tones.length];
  return (
    <li
      className="flex items-start gap-2.5 rounded-md p-2.5"
      style={{
        backgroundColor: tone.color + "0d",
        border: `1px solid ${tone.color}26`
      }}
    >
      <span
        className="mt-0.5 flex h-4 w-4 flex-shrink-0 items-center justify-center rounded-full text-[10px]"
        style={{
          backgroundColor: tone.color + "26",
          color: tone.color
        }}
      >
        {tone.icon}
      </span>
      <div className="min-w-0 flex-1">
        <p className="text-[12px] leading-relaxed text-[var(--qg-text)]">
          {text}
        </p>
        <p
          className="mt-0.5 text-[9px] uppercase tracking-[0.12em] font-bold"
          style={{ color: tone.color }}
        >
          {tone.label}
        </p>
      </div>
    </li>
  );
}
