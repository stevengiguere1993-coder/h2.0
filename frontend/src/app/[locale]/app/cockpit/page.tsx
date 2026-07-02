"use client";

import { useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  Briefcase,
  CheckCircle2,
  ClipboardCheck,
  DollarSign,
  FileText,
  Loader2,
  Moon
} from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { Link } from "@/i18n/navigation";
import { useAppLayout } from "../layout";
import { authedFetch } from "@/lib/auth";
import { useCurrentUser } from "@/hooks/use-current-user";

// ── Types (miroir de GET /cockpit/overview et /punch/live) ─────────────

type CockpitProject = {
  id: number;
  name: string;
  client_name: string | null;
  address: string | null;
  status: string;
  responsible_user_id: number | null;
  responsible_name: string | null;
  budget: number | null;
  soumission_total: number | null;
  spent_achats: number;
  spent_labor: number;
  hours: number;
  phase_name: string | null;
  late_phase_name: string | null;
  late_days: number;
  awaiting_signature: boolean;
  has_signed_bon: boolean;
  correction_bon_draft: boolean;
  correction_status: string;
  last_activity_at: string | null;
  workers_now: string[];
};

type CockpitBon = {
  id: number;
  reference: string;
  title: string;
  address: string | null;
  status: string;
  is_urgent: boolean;
  executant_type: string | null;
  amount: number | null;
  age_days: number;
  hours: number;
  workers_now: string[];
};

type CockpitPO = {
  id: number;
  reference: string;
  fournisseur_name: string | null;
  amount_max: number | null;
  sent_at: string | null;
};

type Overview = {
  projects: CockpitProject[];
  bons: CockpitBon[];
  po_sent: CockpitPO[];
};

type LiveWorker = {
  employe_id: number;
  employe_name: string;
  punch_started_at: string | null;
  punch_project_id: number | null;
  punch_project_name: string | null;
  punch_bon_id: number | null;
  punch_bon_title: string | null;
  punch_task: string | null;
  planned_project_id: number | null;
  planned_project_name: string | null;
  planned_phase_name: string | null;
};

const PROJECT_STATUS_LABELS: Record<string, string> = {
  planned: "À planifier",
  ready_to_start: "En attente",
  in_progress: "En cours",
  suspended: "Suspendu",
  correction: "Correction"
};

const PROJECT_STATUS_BG: Record<string, string> = {
  planned: "bg-white/10 text-white/70",
  ready_to_start: "bg-violet-500/15 text-violet-300",
  in_progress: "bg-blue-500/15 text-blue-300",
  suspended: "bg-amber-500/15 text-amber-300",
  correction: "bg-rose-500/15 text-rose-300"
};

const BON_STATUS_LABELS: Record<string, string> = {
  draft: "Brouillon",
  accepte_a_planifier: "Accepté à planifier",
  planifie: "Planifié",
  complete_a_refacturer: "À refacturer",
  sent: "Envoyé",
  signed: "Signé"
};

// Un chantier « dort » après 5 jours sans punch ni achat.
const SLEEP_DAYS = 5;

// ── File d'attente d'actions ────────────────────────────────────────────

type ActionItem = {
  key: string;
  type: string;
  verb: string;
  label: string;
  sub: string;
  meta: string;
  href: string;
  prio: number;
};

const ACTION_TYPES: {
  id: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  pill: string;
}[] = [
  {
    id: "urgence",
    label: "Urgences",
    icon: AlertTriangle,
    pill: "bg-rose-500/15 text-rose-300"
  },
  {
    id: "signature",
    label: "Signatures",
    icon: FileText,
    pill: "bg-rose-500/15 text-rose-300"
  },
  {
    id: "argent",
    label: "Argent",
    icon: DollarSign,
    pill: "bg-amber-500/15 text-amber-300"
  },
  {
    id: "classifier",
    label: "À classifier",
    icon: ClipboardCheck,
    pill: "bg-amber-500/15 text-amber-300"
  },
  {
    id: "suivi",
    label: "Suivi",
    icon: Moon,
    pill: "bg-white/10 text-white/60"
  }
];

const ACTION_TYPE_MAP = Object.fromEntries(
  ACTION_TYPES.map((t) => [t.id, t])
);

function money(n: number | null | undefined): string {
  if (n == null || !Number.isFinite(n)) return "—";
  return `${n.toLocaleString("fr-CA", {
    minimumFractionDigits: 0,
    maximumFractionDigits: 0
  })} $`;
}

function sinceLabel(iso: string, now: Date): string {
  const start = new Date(iso);
  const mins = Math.max(
    0,
    Math.floor((now.getTime() - start.getTime()) / 60000)
  );
  const h = Math.floor(mins / 60);
  const m = mins % 60;
  return h > 0 ? `${h} h ${String(m).padStart(2, "0")}` : `${m} min`;
}

function daysSince(iso: string | null, now: Date): number | null {
  if (!iso) return null;
  return Math.floor(
    (now.getTime() - new Date(iso).getTime()) / (24 * 3600 * 1000)
  );
}

export default function CockpitPage() {
  const { onOpenSidebar } = useAppLayout();
  const { user } = useCurrentUser();
  const [data, setData] = useState<Overview | null>(null);
  const [live, setLive] = useState<LiveWorker[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null);
  const [now, setNow] = useState(() => new Date());
  const [scope, setScope] = useState<"all" | "mine">("all");
  const [actionFilter, setActionFilter] = useState<string | null>(null);
  const [showAllActions, setShowAllActions] = useState(false);

  useEffect(() => {
    let cancelled = false;
    async function tick() {
      try {
        const [ovRes, liveRes] = await Promise.all([
          authedFetch("/api/v1/cockpit/overview"),
          authedFetch("/api/v1/punch/live")
        ]);
        if (cancelled) return;
        if (!ovRes.ok) throw new Error(`HTTP ${ovRes.status}`);
        setData((await ovRes.json()) as Overview);
        if (liveRes.ok) setLive((await liveRes.json()) as LiveWorker[]);
        setUpdatedAt(new Date());
        setNow(new Date());
        setError(null);
      } catch (e) {
        if (!cancelled && !data) setError((e as Error).message);
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    void tick();
    const t = setInterval(tick, 45_000);
    return () => {
      cancelled = true;
      clearInterval(t);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const projects = useMemo(() => {
    const all = data?.projects || [];
    if (scope === "mine" && user?.id) {
      return all.filter((p) => p.responsible_user_id === user.id);
    }
    return all;
  }, [data, scope, user?.id]);
  const bons = data?.bons || [];
  const poSent = data?.po_sent || [];

  // ── Dérivés « À l'action » ────────────────────────────────────────────
  const urgentBons = bons.filter(
    (b) => b.is_urgent && b.status !== "complete_a_refacturer"
  );
  const aClassifier = bons.filter(
    (b) => !b.executant_type || b.executant_type === "a_classifier"
  );
  const aRefacturer = bons.filter(
    (b) => b.status === "complete_a_refacturer"
  );
  const sigToSend = projects.filter((p) => p.correction_bon_draft);
  const sigWaiting = projects.filter((p) => p.awaiting_signature);
  const sleeping = projects.filter((p) => {
    if (p.status !== "in_progress" && p.status !== "correction") return false;
    const d = daysSince(p.last_activity_at, now);
    return d === null || d >= SLEEP_DAYS;
  });
  const latePhases = projects.filter((p) => p.late_days > 0);

  const punched = live.filter((w) => w.punch_started_at);
  const plannedOnly = live.filter((w) => !w.punch_started_at);

  // File d'attente unique : chaque ligne = UNE action à poser (verbe +
  // contexte), triée par priorité. Bien plus scannable que des listes
  // par catégorie.
  const actions: ActionItem[] = [
    ...urgentBons.map((b) => ({
      key: `u${b.id}`,
      type: "urgence",
      verb: "Traiter l'urgence",
      label: b.title,
      sub: b.address || b.reference,
      meta: b.age_days > 0 ? `${b.age_days} j` : "aujourd'hui",
      href: `/app/bons/${b.id}`,
      prio: 0
    })),
    ...sigToSend.map((p) => ({
      key: `s${p.id}`,
      type: "signature",
      verb: "Envoyer pour signature",
      label: p.name,
      sub: p.client_name || p.address || "Bon de correction prêt",
      meta: "",
      href: `/app/projets/${p.id}`,
      prio: 1
    })),
    ...sigWaiting.map((p) => ({
      key: `w${p.id}`,
      type: "signature",
      verb: "Relancer le client",
      label: p.name,
      sub: "Bon envoyé, pas encore signé",
      meta: "",
      href: `/app/projets/${p.id}`,
      prio: 2
    })),
    ...aRefacturer.map((b) => ({
      key: `r${b.id}`,
      type: "argent",
      verb: "Refacturer",
      label: b.title,
      sub:
        b.amount != null && b.amount > 0
          ? `${money(b.amount)} à charger`
          : "Montant à saisir sur le bon",
      meta: `complété · ${b.age_days} j`,
      href: `/app/bons/${b.id}`,
      prio: 3
    })),
    ...poSent.map((po) => ({
      key: `p${po.id}`,
      type: "argent",
      verb: "Récupérer la facture",
      label: po.reference,
      sub: `${po.fournisseur_name || "Fournisseur —"} · max ${money(po.amount_max)}`,
      meta: "",
      href: `/app/po/${po.id}`,
      prio: 4
    })),
    ...aClassifier.map((b) => ({
      key: `c${b.id}`,
      type: "classifier",
      verb: "Choisir l'exécutant",
      label: b.title,
      sub: b.address || b.reference,
      meta: b.age_days > 0 ? `${b.age_days} j` : "aujourd'hui",
      href: `/app/bons/${b.id}`,
      prio: 5
    })),
    ...sleeping.map((p) => {
      const d = daysSince(p.last_activity_at, now);
      return {
        key: `z${p.id}`,
        type: "suivi",
        verb: "Vérifier le chantier",
        label: p.name,
        sub:
          d === null
            ? "Aucun punch ni achat enregistré"
            : `Aucune activité depuis ${d} j`,
        meta: "",
        href: `/app/projets/${p.id}`,
        prio: 6
      };
    }),
    ...latePhases.map((p) => ({
      key: `l${p.id}`,
      type: "suivi",
      verb: "Livrer ou replanifier",
      label: p.name,
      sub: `Dernière phase (${p.late_phase_name || "—"}) finie depuis ${p.late_days} j`,
      meta: "",
      href: `/app/projets/${p.id}`,
      prio: 7
    }))
  ].sort((a, b) => a.prio - b.prio);

  const actionCount = actions.length;
  const typeCounts: Record<string, number> = {};
  for (const a of actions) {
    typeCounts[a.type] = (typeCounts[a.type] || 0) + 1;
  }
  const filteredActions = actionFilter
    ? actions.filter((a) => a.type === actionFilter)
    : actions;
  const shownActions = showAllActions
    ? filteredActions
    : filteredActions.slice(0, 10);

  return (
    <>
      <AppTopbar
        breadcrumbs={[
          { label: "Construction", href: "/app" },
          { label: "Vue d'ensemble" }
        ]}
        onOpenSidebar={onOpenSidebar}
      />

      <div className="p-4 pb-24 lg:p-6 lg:pb-24">
        <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
          <div>
            <h1 className="text-2xl font-bold text-white">Vue d&apos;ensemble</h1>
            <p className="mt-1 text-sm text-white/60">
              Le cockpit du chargé de projet : qui est où, ce qui demande une
              action, et la santé de chaque chantier.
            </p>
          </div>
          <div className="flex items-center gap-2">
            <div className="inline-flex gap-1 rounded-lg bg-brand-900 p-1">
              {(
                [
                  { id: "all" as const, label: "Tous" },
                  { id: "mine" as const, label: "Mes projets" }
                ]
              ).map((t) => (
                <button
                  key={t.id}
                  type="button"
                  onClick={() => setScope(t.id)}
                  className={`rounded-md px-3 py-1.5 text-xs font-semibold transition ${
                    scope === t.id
                      ? "bg-accent-500 text-brand-950"
                      : "text-white/60 hover:text-white"
                  }`}
                >
                  {t.label}
                </button>
              ))}
            </div>
            {updatedAt ? (
              <span className="text-[10px] text-white/40">
                Mis à jour à{" "}
                {updatedAt.toLocaleTimeString("fr-CA", {
                  hour: "2-digit",
                  minute: "2-digit"
                })}
              </span>
            ) : null}
          </div>
        </div>

        {loading ? (
          <div className="flex min-h-[40vh] items-center justify-center">
            <Loader2 className="h-6 w-6 animate-spin text-accent-500" />
          </div>
        ) : error ? (
          <p className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-4 py-2 text-sm text-rose-300">
            {error}
          </p>
        ) : (
          <div className="space-y-5">
            {/* ── Le pouls : temps réel + compteurs ── */}
            <section className="rounded-xl border border-brand-800 bg-brand-900 p-4">
              <h2 className="flex flex-wrap items-center gap-2 text-sm font-semibold uppercase tracking-wider text-white/70">
                <span className="relative flex h-2.5 w-2.5">
                  <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-60" />
                  <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-emerald-500" />
                </span>
                En direct
                <span className="rounded-full bg-emerald-500/15 px-2 py-0.5 text-[10px] font-bold text-emerald-300">
                  {punched.length} pointé{punched.length > 1 ? "s" : ""}
                </span>
                {plannedOnly.length > 0 ? (
                  <span className="rounded-full bg-amber-500/15 px-2 py-0.5 text-[10px] font-bold text-amber-300">
                    {plannedOnly.length} prévu
                    {plannedOnly.length > 1 ? "s" : ""} non pointé
                    {plannedOnly.length > 1 ? "s" : ""}
                  </span>
                ) : null}
              </h2>
              {live.length === 0 ? (
                <p className="mt-2 text-sm text-white/40">
                  Personne n&apos;est pointé ni prévu sur un chantier en ce
                  moment.
                </p>
              ) : (
                <div className="mt-3 flex flex-wrap gap-2">
                  {live.map((w) => {
                    const active = !!w.punch_started_at;
                    const site =
                      w.punch_project_name ||
                      w.punch_bon_title ||
                      w.punch_task ||
                      w.planned_project_name ||
                      "—";
                    return (
                      <span
                        key={w.employe_id}
                        className={`inline-flex items-center gap-2 rounded-full border px-3 py-1.5 text-xs ${
                          active
                            ? "border-emerald-500/40 bg-emerald-500/[0.08] text-white"
                            : "border-brand-800 bg-brand-950 text-white/60"
                        }`}
                      >
                        <span
                          className={`h-1.5 w-1.5 rounded-full ${
                            active ? "bg-emerald-400" : "bg-gray-400/60"
                          }`}
                        />
                        <span className="font-semibold">{w.employe_name}</span>
                        <span className="text-white/50">·</span>
                        <span className="max-w-[14rem] truncate">{site}</span>
                        {active ? (
                          <span className="text-white/50">
                            {sinceLabel(w.punch_started_at as string, now)}
                          </span>
                        ) : (
                          <span className="text-amber-300/90">pas pointé</span>
                        )}
                      </span>
                    );
                  })}
                </div>
              )}

              <div className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
                <StatTile
                  label="Projets actifs"
                  value={projects.length}
                  tone="sky"
                />
                <StatTile
                  label="Bons ouverts"
                  value={bons.length}
                  tone="sky"
                />
                <StatTile
                  label="Urgences"
                  value={urgentBons.length}
                  tone={urgentBons.length ? "rose" : "muted"}
                />
                <StatTile
                  label="Signatures"
                  value={sigToSend.length + sigWaiting.length}
                  tone={sigToSend.length + sigWaiting.length ? "rose" : "muted"}
                />
                <StatTile
                  label="À refacturer"
                  value={aRefacturer.length}
                  tone={aRefacturer.length ? "amber" : "muted"}
                />
                <StatTile
                  label="PO à convertir"
                  value={poSent.length}
                  tone={poSent.length ? "amber" : "muted"}
                />
              </div>
            </section>

            {/* ── À l'action ── */}
            <section className="rounded-xl border border-brand-800 bg-brand-900 p-4">
              <h2 className="text-sm font-semibold uppercase tracking-wider text-white/70">
                À l&apos;action{" "}
                <span className="ml-1 rounded-full bg-accent-500/20 px-2 py-0.5 text-[10px] font-bold text-accent-300">
                  {actionCount}
                </span>
              </h2>
              {actionCount === 0 ? (
                <p className="mt-2 flex items-center gap-2 text-sm text-emerald-300">
                  <CheckCircle2 className="h-4 w-4" /> Rien en attente — tout
                  roule.
                </p>
              ) : (
                <>
                  {/* Filtres rapides par type d'action */}
                  <div className="mt-3 flex flex-wrap gap-1.5">
                    <button
                      type="button"
                      onClick={() => setActionFilter(null)}
                      className={`rounded-full px-3 py-1 text-[11px] font-semibold transition ${
                        actionFilter === null
                          ? "bg-accent-500 text-brand-950"
                          : "bg-brand-950 text-white/60 hover:text-white"
                      }`}
                    >
                      Tout ({actionCount})
                    </button>
                    {ACTION_TYPES.filter((t) => typeCounts[t.id]).map((t) => (
                      <button
                        key={t.id}
                        type="button"
                        onClick={() =>
                          setActionFilter(
                            actionFilter === t.id ? null : t.id
                          )
                        }
                        className={`rounded-full px-3 py-1 text-[11px] font-semibold transition ${
                          actionFilter === t.id
                            ? "bg-accent-500 text-brand-950"
                            : "bg-brand-950 text-white/60 hover:text-white"
                        }`}
                      >
                        {t.label} ({typeCounts[t.id]})
                      </button>
                    ))}
                  </div>

                  {/* File d'attente : une ligne = une action à poser */}
                  <div className="mt-3 space-y-1.5">
                    {shownActions.map((a) => {
                      const t = ACTION_TYPE_MAP[a.type];
                      const Icon = t.icon;
                      return (
                        <Link
                          key={a.key}
                          // eslint-disable-next-line @typescript-eslint/no-explicit-any
                          href={a.href as any}
                          className="flex items-center gap-3 rounded-lg border border-brand-800 bg-brand-950 px-3 py-2.5 transition hover:border-accent-500"
                        >
                          <span
                            className={`flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-lg ${t.pill}`}
                          >
                            <Icon className="h-4 w-4" />
                          </span>
                          <span className="min-w-0 flex-1">
                            <span className="block truncate text-sm">
                              <span className="font-semibold text-white">
                                {a.verb}
                              </span>
                              <span className="text-white/60">
                                {" "}
                                — {a.label}
                              </span>
                            </span>
                            <span className="block truncate text-[11px] text-white/45">
                              {a.sub}
                            </span>
                          </span>
                          {a.meta ? (
                            <span className="flex-shrink-0 whitespace-nowrap text-[11px] text-white/40">
                              {a.meta}
                            </span>
                          ) : null}
                        </Link>
                      );
                    })}
                  </div>
                  {filteredActions.length > shownActions.length ? (
                    <button
                      type="button"
                      onClick={() => setShowAllActions(true)}
                      className="mt-2 text-xs font-semibold text-accent-400 hover:text-accent-300"
                    >
                      Voir les {filteredActions.length - shownActions.length}{" "}
                      autres →
                    </button>
                  ) : showAllActions && filteredActions.length > 10 ? (
                    <button
                      type="button"
                      onClick={() => setShowAllActions(false)}
                      className="mt-2 text-xs font-semibold text-white/50 hover:text-white"
                    >
                      Réduire
                    </button>
                  ) : null}
                </>
              )}
            </section>

            {/* ── Santé des projets ── */}
            <section className="rounded-xl border border-brand-800 bg-brand-900">
              <div className="border-b border-brand-800 px-4 py-3">
                <h2 className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wider text-white/70">
                  <Briefcase className="h-4 w-4" /> Projets en cours (
                  {projects.length})
                </h2>
              </div>
              {projects.length === 0 ? (
                <p className="px-4 py-6 text-sm text-white/40">
                  Aucun projet actif{scope === "mine" ? " qui t'est assigné" : ""}.
                </p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead className="border-b border-brand-800 bg-brand-950/50 text-left text-[11px] uppercase tracking-wider text-white/50">
                      <tr>
                        <th className="px-3 py-2">Projet</th>
                        <th className="px-3 py-2">Statut</th>
                        <th className="w-56 px-3 py-2">Budget vs réel</th>
                        <th className="px-3 py-2 text-right">Heures</th>
                        <th className="px-3 py-2">Phase</th>
                        <th className="px-3 py-2">Signature</th>
                        <th className="px-3 py-2">Sur place</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-brand-800">
                      {projects.map((p) => (
                        <ProjectRow key={p.id} p={p} />
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </section>

            {/* ── Bons de travail actifs ── */}
            <section className="rounded-xl border border-brand-800 bg-brand-900">
              <div className="border-b border-brand-800 px-4 py-3">
                <h2 className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wider text-white/70">
                  <ClipboardCheck className="h-4 w-4" /> Bons de travail
                  ouverts ({bons.length})
                </h2>
              </div>
              {bons.length === 0 ? (
                <p className="px-4 py-6 text-sm text-white/40">
                  Aucun bon de travail ouvert.
                </p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead className="border-b border-brand-800 bg-brand-950/50 text-left text-[11px] uppercase tracking-wider text-white/50">
                      <tr>
                        <th className="px-3 py-2">Bon</th>
                        <th className="px-3 py-2">Statut</th>
                        <th className="px-3 py-2">Exécutant</th>
                        <th className="px-3 py-2 text-right">Montant</th>
                        <th className="px-3 py-2 text-right">Âge</th>
                        <th className="px-3 py-2 text-right">Heures</th>
                        <th className="px-3 py-2">Sur place</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-brand-800">
                      {bons.map((b) => (
                        <BonRow key={b.id} b={b} />
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </section>
          </div>
        )}
      </div>
    </>
  );
}

// ── Sous-composants ─────────────────────────────────────────────────────

function StatTile({
  label,
  value,
  tone
}: {
  label: string;
  value: number;
  tone: "sky" | "rose" | "amber" | "muted";
}) {
  const tones: Record<string, string> = {
    sky: "border-sky-500/30 bg-sky-500/10 text-sky-300",
    rose: "border-rose-500/30 bg-rose-500/10 text-rose-300",
    amber: "border-amber-500/30 bg-amber-500/10 text-amber-300",
    muted: "border-brand-800 bg-brand-950 text-white/50"
  };
  return (
    <div className={`rounded-lg border p-3 ${tones[tone]}`}>
      <p className="text-2xl font-bold leading-none">{value}</p>
      <p className="mt-1 text-[11px] font-medium opacity-80">{label}</p>
    </div>
  );
}

function ProjectRow({ p }: { p: CockpitProject }) {
  const budgetRef = p.budget ?? p.soumission_total;
  const spent = p.spent_achats + p.spent_labor;
  const pct =
    budgetRef && budgetRef > 0
      ? Math.round((spent / budgetRef) * 100)
      : null;
  const barTone =
    pct === null
      ? "bg-white/20"
      : pct > 100
        ? "bg-rose-500"
        : pct >= 80
          ? "bg-amber-500"
          : "bg-emerald-500";
  return (
    <tr className="hover:bg-brand-800/30">
      <td className="px-3 py-2">
        <Link
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          href={`/app/projets/${p.id}` as any}
          className="font-semibold text-white hover:text-accent-400"
        >
          {p.name}
        </Link>
        <p className="text-[11px] text-white/50">
          {p.client_name || p.address || "—"}
          {p.responsible_name ? ` · ${p.responsible_name}` : ""}
        </p>
      </td>
      <td className="px-3 py-2">
        <span
          className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${
            PROJECT_STATUS_BG[p.status] || "bg-white/10 text-white/70"
          }`}
        >
          {PROJECT_STATUS_LABELS[p.status] || p.status}
        </span>
      </td>
      <td className="px-3 py-2">
        <div className="flex items-center justify-between gap-2 text-[11px]">
          <span className="font-semibold text-white">{money(spent)}</span>
          <span className="text-white/50">
            {budgetRef ? `/ ${money(budgetRef)}` : "budget —"}
            {pct !== null ? ` · ${pct} %` : ""}
          </span>
        </div>
        <div className="mt-1 h-1.5 w-full overflow-hidden rounded-full bg-brand-950">
          <div
            className={`h-full rounded-full ${barTone}`}
            style={{
              width: `${pct === null ? 0 : Math.min(pct, 100)}%`
            }}
          />
        </div>
      </td>
      <td className="px-3 py-2 text-right text-white/80">
        {p.hours ? `${p.hours.toLocaleString("fr-CA")} h` : "—"}
      </td>
      <td className="px-3 py-2 text-[11px]">
        {p.phase_name ? (
          <span className="text-white/80">{p.phase_name}</span>
        ) : p.late_days > 0 ? (
          <span className="text-amber-300">
            {p.late_phase_name || "Phase"} +{p.late_days} j
          </span>
        ) : (
          <span className="text-white/40">—</span>
        )}
      </td>
      <td className="px-3 py-2">
        {p.has_signed_bon ? (
          <span className="rounded-md bg-emerald-500/15 px-1.5 py-0.5 text-[10px] font-semibold text-emerald-300">
            Signé
          </span>
        ) : p.awaiting_signature ? (
          <span className="rounded-md bg-rose-500/20 px-1.5 py-0.5 text-[10px] font-semibold text-rose-300">
            À signer
          </span>
        ) : p.correction_bon_draft ? (
          <span className="rounded-md bg-gray-400/20 px-1.5 py-0.5 text-[10px] font-semibold text-gray-500">
            Bon à envoyer
          </span>
        ) : (
          <span className="text-[11px] text-white/30">—</span>
        )}
      </td>
      <td className="px-3 py-2 text-[11px]">
        {p.workers_now.length > 0 ? (
          <span className="inline-flex items-center gap-1.5 text-emerald-300">
            <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />
            {p.workers_now.join(", ")}
          </span>
        ) : (
          <span className="text-white/30">—</span>
        )}
      </td>
    </tr>
  );
}

function BonRow({ b }: { b: CockpitBon }) {
  return (
    <tr className={b.is_urgent ? "bg-rose-500/[0.05]" : "hover:bg-brand-800/30"}>
      <td className="px-3 py-2">
        <Link
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          href={`/app/bons/${b.id}` as any}
          className="font-semibold text-white hover:text-accent-400"
        >
          {b.is_urgent ? (
            <span className="mr-1.5 text-rose-400">⚠</span>
          ) : null}
          {b.title}
        </Link>
        <p className="text-[11px] text-white/50">
          {b.address || b.reference}
        </p>
      </td>
      <td className="px-3 py-2">
        <span className="rounded-full bg-white/10 px-2 py-0.5 text-[10px] font-semibold text-white/70">
          {BON_STATUS_LABELS[b.status] || b.status}
        </span>
      </td>
      <td className="px-3 py-2 text-[11px]">
        {b.executant_type === "sous_traitant" ? (
          <span className="text-orange-300">Sous-traitant</span>
        ) : b.executant_type === "nos_hommes" ? (
          <span className="text-sky-300">Nos hommes</span>
        ) : (
          <span className="font-semibold text-amber-300">À classifier</span>
        )}
      </td>
      <td className="px-3 py-2 text-right font-semibold text-white">
        {money(b.amount)}
      </td>
      <td
        className={`px-3 py-2 text-right text-[11px] ${
          b.age_days >= 14 ? "font-semibold text-amber-300" : "text-white/60"
        }`}
      >
        {b.age_days} j
      </td>
      <td className="px-3 py-2 text-right text-white/80">
        {b.hours ? `${b.hours.toLocaleString("fr-CA")} h` : "—"}
      </td>
      <td className="px-3 py-2 text-[11px]">
        {b.workers_now.length > 0 ? (
          <span className="inline-flex items-center gap-1.5 text-emerald-300">
            <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />
            {b.workers_now.join(", ")}
          </span>
        ) : (
          <span className="text-white/30">—</span>
        )}
      </td>
    </tr>
  );
}
