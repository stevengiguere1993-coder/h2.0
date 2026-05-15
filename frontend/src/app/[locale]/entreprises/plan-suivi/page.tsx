"use client";

import { useEffect, useMemo, useState } from "react";
import {
  Bot,
  CheckCircle2,
  ChevronDown,
  Circle,
  Compass,
  Loader2,
  Pause,
  PlayCircle,
  Search,
  Sparkles,
  Wrench,
  X
} from "lucide-react";

import { authedFetch } from "@/lib/auth";
import { QGTopbar, useEntreprisesLayout } from "../layout";

// --------------------------------------------------------------------------
// Types & constantes
// --------------------------------------------------------------------------

type OrgNode = {
  id: number;
  parent_id: number | null;
  position: number;
  kind: string;
  label: string;
  description: string | null;
  entreprise_id: number | null;
  assignee_external_name: string | null;
  execution_tier: string | null;
  state: string | null;
  state_note: string | null;
};

type State = "planifie" | "en_cours" | "fait" | "bloque" | "non_applicable";

const STATE_ORDER: State[] = [
  "planifie",
  "en_cours",
  "fait",
  "bloque",
  "non_applicable"
];

const STATE_LABEL: Record<string, string> = {
  planifie: "Planifié",
  en_cours: "En cours",
  fait: "Fait",
  bloque: "Bloqué",
  non_applicable: "N/A"
};

const STATE_CLS: Record<string, string> = {
  planifie: "bg-white/5 text-white/60 border-white/15",
  en_cours: "bg-blue-500/15 text-blue-300 border-blue-500/40",
  fait: "bg-emerald-500/15 text-emerald-300 border-emerald-500/40",
  bloque: "bg-rose-500/15 text-rose-300 border-rose-500/40",
  non_applicable: "bg-white/5 text-white/30 border-white/10"
};

// Pôles canoniques attendus au top-level. L'ordre fixe l'affichage.
const POLES_ORDER = [
  "Construction",
  "Développement IA",
  "Gestion immobilière",
  "Acquisition",
  "Gestion d'entreprise",
  "Comptabilité"
];

// --------------------------------------------------------------------------
// Helpers
// --------------------------------------------------------------------------

function norm(s: string): string {
  return s
    .toLowerCase()
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .trim();
}

function poleColor(pole: string): string {
  switch (pole) {
    case "Construction":
      return "bg-amber-500";
    case "Développement IA":
      return "bg-blue-500";
    case "Gestion immobilière":
      return "bg-emerald-500";
    case "Acquisition":
      return "bg-violet-500";
    case "Gestion d'entreprise":
      return "bg-indigo-500";
    case "Comptabilité":
      return "bg-pink-500";
    default:
      return "bg-white/40";
  }
}

// --------------------------------------------------------------------------
// Vision groupe (narratif hardcodé — éditable plus tard via UI)
// --------------------------------------------------------------------------

const VISION_GROUPE = {
  title: "Vision du groupe — mutualisation et efficience",
  paragraphs: [
    "Nous opérons 6 pôles complémentaires (Construction, Développement IA, Gestion immobilière, Acquisition, Gestion d'entreprise, Comptabilité). L'objectif n'est pas que chaque pôle soit étanche — c'est qu'ils se renforcent mutuellement. Une ressource (humaine ou logicielle) bâtie pour un pôle doit profiter aux autres.",
    "Aujourd'hui : 3 propriétaires + 1 prospecteur prêt à devenir bras droit + 2 entreprises de gestion en sous-traitance pour la gestion immobilière + 1 employé prêt à devenir chargé de projet construction. La première priorité est de libérer les owners du day-to-day en promouvant ces 2 ressources.",
    "Trois leviers de mutualisation : (1) l'adjoint administratif sert les 6 pôles ; (2) la comptabilité Francostaffing sert les 6 pôles ; (3) Kratos — adjoint virtuel — automatise les tâches répétitives à travers tous les pôles. La logique est simple : tout ce qui peut être fait une fois pour les 6 ne doit pas être refait 6 fois."
  ],
  hiringPlan: [
    {
      horizon: "0-3 mois",
      action: "Prospecteur → Bras droit / Adjoint administratif",
      why: "Libère les 3 owners du day-to-day. Critique."
    },
    {
      horizon: "0-3 mois",
      action: "Employé → Chargé de projet Construction",
      why: "Libère 1 owner du chantier opérationnel."
    },
    {
      horizon: "3-6 mois",
      action: "Closer Construction (commission)",
      why: "Le CEO ne doit plus closer."
    },
    {
      horizon: "3-6 mois",
      action: "Gestionnaire immobilier (interne ou contrat)",
      why: "Bouche le « tout le reste » vague des sous-traitants gestion."
    },
    {
      horizon: "6-12 mois",
      action: "Analyste acquisition",
      why: "Quand volume de deals le justifie."
    },
    {
      horizon: "6-12 mois",
      action: "Closer Dev IA (commission)",
      why: "Quand pipeline pôle 2 est réel."
    },
    {
      horizon: "12+ mois",
      action: "Chargé de projet Dev IA, prospecteurs additionnels",
      why: "Selon croissance."
    }
  ]
};

// --------------------------------------------------------------------------
// Page
// --------------------------------------------------------------------------

export default function PlanSuiviPage() {
  const { onOpenSidebar } = useEntreprisesLayout();
  const [nodes, setNodes] = useState<OrgNode[]>([]);
  const [loading, setLoading] = useState(true);
  const [seeding, setSeeding] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Filtres
  const [filterState, setFilterState] = useState<string>("all");
  const [filterPole, setFilterPole] = useState<string>("all");
  const [filterTier, setFilterTier] = useState<string>("all");
  const [filterResp, setFilterResp] = useState<string>("all");
  const [search, setSearch] = useState("");

  // Inline note edit
  const [editingNoteFor, setEditingNoteFor] = useState<number | null>(null);
  const [noteDraft, setNoteDraft] = useState("");

  async function loadAll() {
    try {
      const r = await authedFetch("/api/v1/org-nodes");
      if (!r.ok) throw new Error("Chargement impossible");
      setNodes(await r.json());
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erreur");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadAll();
  }, []);

  // Index parent → enfants pour résoudre la chaîne pôle/rôle de chaque tâche.
  const byParent = useMemo(() => {
    const m = new Map<number | null, OrgNode[]>();
    for (const n of nodes) {
      const arr = m.get(n.parent_id) || [];
      arr.push(n);
      m.set(n.parent_id, arr);
    }
    return m;
  }, [nodes]);

  const byId = useMemo(
    () => new Map(nodes.map((n) => [n.id, n])),
    [nodes]
  );

  // Pour chaque nœud, calcule (pôle, rôle) — ancêtres dept/role.
  function ancestry(n: OrgNode): { pole: string | null; role: string | null } {
    let cur: OrgNode | null = n;
    let pole: string | null = null;
    let role: string | null = null;
    while (cur) {
      if (cur.kind === "role" && !role) role = cur.label;
      if ((cur.kind === "dept" || cur.kind === "service") && !pole)
        pole = cur.label;
      cur = cur.parent_id ? byId.get(cur.parent_id) || null : null;
    }
    return { pole, role };
  }

  // Responsable d'une tâche : Kratos pour les `adjoint_virtuel`,
  // sinon l'assignee de la tâche elle-même, sinon celui du rôle
  // ancêtre le plus proche. NULL si rien défini.
  function responsableFor(n: OrgNode): string | null {
    if (n.execution_tier === "adjoint_virtuel") return "Kratos";
    if (n.assignee_external_name) return n.assignee_external_name;
    let cur: OrgNode | null = n.parent_id ? byId.get(n.parent_id) || null : null;
    while (cur) {
      if (cur.assignee_external_name) return cur.assignee_external_name;
      cur = cur.parent_id ? byId.get(cur.parent_id) || null : null;
    }
    return null;
  }

  // Liste des responsables uniques pour alimenter le filtre.
  const responsablesList = useMemo(() => {
    const set = new Set<string>();
    for (const t of nodes) {
      if (t.kind !== "task") continue;
      const r = responsableFor(t);
      if (r) set.add(r);
    }
    return Array.from(set).sort((a, b) => a.localeCompare(b, "fr-CA"));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [nodes, byId]);

  // Toutes les tâches (kind=task) seulement — c'est ce qu'on suit.
  const tasks = useMemo(
    () => nodes.filter((n) => n.kind === "task"),
    [nodes]
  );

  // Filtrage.
  const filteredTasks = useMemo(() => {
    const q = norm(search);
    return tasks.filter((t) => {
      const { pole } = ancestry(t);
      if (filterPole !== "all" && pole !== filterPole) return false;
      if (filterState !== "all") {
        const s = t.state || "planifie";
        if (s !== filterState) return false;
      }
      if (filterTier !== "all") {
        if ((t.execution_tier || "") !== filterTier) return false;
      }
      if (filterResp !== "all") {
        if ((responsableFor(t) || "—") !== filterResp) return false;
      }
      if (q) {
        const hay = norm(
          `${t.label} ${t.state_note || ""} ${responsableFor(t) || ""}`
        );
        if (!hay.includes(q)) return false;
      }
      return true;
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tasks, filterPole, filterState, filterTier, filterResp, search, byId]);

  // Groupement par pôle pour l'affichage.
  const byPole = useMemo(() => {
    const m = new Map<string, OrgNode[]>();
    for (const t of filteredTasks) {
      const { pole } = ancestry(t);
      const key = pole || "Sans pôle";
      const arr = m.get(key) || [];
      arr.push(t);
      m.set(key, arr);
    }
    // Tri selon l'ordre canonique des pôles.
    const ordered: [string, OrgNode[]][] = [];
    for (const p of POLES_ORDER) {
      const list = m.get(p);
      if (list && list.length > 0) ordered.push([p, list]);
    }
    for (const [k, v] of m.entries()) {
      if (!POLES_ORDER.includes(k)) ordered.push([k, v]);
    }
    return ordered;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filteredTasks, byId]);

  // KPI globaux (sur TOUTES les tâches, pas seulement filtrées).
  const kpis = useMemo(() => {
    let fait = 0;
    let enCours = 0;
    let planifie = 0;
    let bloque = 0;
    let na = 0;
    let kratosTotal = 0;
    let kratosFait = 0;
    let postesAPourvoir = 0;
    for (const n of nodes) {
      if (n.kind === "role") {
        const isHire =
          (n.description || "").includes("🪑") ||
          (n.assignee_external_name || "").toLowerCase().includes("à pourvoir") ||
          (n.description || "").toLowerCase().includes("à pourvoir");
        if (isHire) postesAPourvoir += 1;
      }
      if (n.kind !== "task") continue;
      const s = (n.state || "planifie") as State;
      if (s === "fait") fait += 1;
      else if (s === "en_cours") enCours += 1;
      else if (s === "bloque") bloque += 1;
      else if (s === "non_applicable") na += 1;
      else planifie += 1;
      if (n.execution_tier === "adjoint_virtuel") {
        kratosTotal += 1;
        if (s === "fait") kratosFait += 1;
      }
    }
    return { fait, enCours, planifie, bloque, na, kratosTotal, kratosFait, postesAPourvoir };
  }, [nodes]);

  // Progression par pôle.
  const poleProgress = useMemo(() => {
    const m = new Map<string, { total: number; done: number }>();
    for (const t of tasks) {
      const { pole } = ancestry(t);
      const key = pole || "Sans pôle";
      const entry = m.get(key) || { total: 0, done: 0 };
      entry.total += 1;
      if (t.state === "fait" || t.state === "non_applicable") entry.done += 1;
      m.set(key, entry);
    }
    const out: { pole: string; total: number; done: number; pct: number }[] = [];
    for (const p of POLES_ORDER) {
      const e = m.get(p);
      if (e) out.push({ pole: p, ...e, pct: Math.round((e.done / Math.max(1, e.total)) * 100) });
    }
    for (const [k, v] of m.entries()) {
      if (!POLES_ORDER.includes(k))
        out.push({ pole: k, ...v, pct: Math.round((v.done / Math.max(1, v.total)) * 100) });
    }
    return out;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tasks, byId]);

  // --- Actions ---

  async function setState(id: number, newState: State) {
    const prev = nodes;
    setNodes((xs) =>
      xs.map((n) => (n.id === id ? { ...n, state: newState } : n))
    );
    try {
      const r = await authedFetch(`/api/v1/org-nodes/${id}`, {
        method: "PATCH",
        body: JSON.stringify({ state: newState })
      });
      if (!r.ok) throw new Error();
    } catch {
      setNodes(prev);
      setError("Mise à jour de l'état impossible");
    }
  }

  async function saveStateNote(id: number, note: string) {
    const prev = nodes;
    setNodes((xs) =>
      xs.map((n) =>
        n.id === id ? { ...n, state_note: note.trim() || null } : n
      )
    );
    setEditingNoteFor(null);
    try {
      const r = await authedFetch(`/api/v1/org-nodes/${id}`, {
        method: "PATCH",
        body: JSON.stringify({ state_note: note.trim() || null })
      });
      if (!r.ok) throw new Error();
    } catch {
      setNodes(prev);
      setError("Mise à jour de la note impossible");
    }
  }

  async function runSeed() {
    setSeeding(true);
    try {
      const r = await authedFetch(
        "/api/v1/org-nodes/seed-poles-canonical",
        { method: "POST" }
      );
      if (!r.ok) throw new Error("Seed impossible");
      const result = (await r.json()) as {
        created: number;
        reused: number;
        total: number;
      };
      setError(
        `Seed OK — ${result.created} nœuds créés, ${result.reused} déjà présents (${result.total} total).`
      );
      await loadAll();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Seed impossible");
    } finally {
      setSeeding(false);
    }
  }

  // --- Render ---

  const totalTasks = tasks.length;
  const pctDone = totalTasks > 0
    ? Math.round(((kpis.fait + kpis.na) / totalTasks) * 100)
    : 0;
  const pctKratos = kpis.kratosTotal > 0
    ? Math.round((kpis.kratosFait / kpis.kratosTotal) * 100)
    : 0;

  return (
    <div className="min-h-screen bg-brand-950">
      <QGTopbar
        breadcrumbs={[
          { label: "Entreprises", href: "/entreprises" as any },
          { label: "Plan & Suivi" }
        ]}
        onOpenSidebar={onOpenSidebar}
      />

      <div className="mx-auto max-w-6xl px-4 py-6 lg:px-6">
        {/* Vision groupe — hero */}
        <section className="mb-6 rounded-2xl border border-indigo-500/30 bg-gradient-to-br from-indigo-500/10 to-violet-500/10 p-5">
          <div className="flex items-center gap-3">
            <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-indigo-500/20 text-indigo-300">
              <Compass className="h-5 w-5" />
            </span>
            <div>
              <h1 className="text-xl font-bold text-white">
                {VISION_GROUPE.title}
              </h1>
              <p className="text-xs text-white/50">
                Document de référence — pilote le plan canonique des 6 pôles.
              </p>
            </div>
          </div>
          <div className="mt-3 space-y-2 text-sm leading-relaxed text-white/80">
            {VISION_GROUPE.paragraphs.map((p, i) => (
              <p key={i}>{p}</p>
            ))}
          </div>
          {/* Séquence d'embauche */}
          <div className="mt-4 rounded-xl bg-brand-950/40 p-3">
            <p className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-white/50">
              Séquence d'embauche proposée
            </p>
            <ul className="space-y-1.5 text-xs text-white/80">
              {VISION_GROUPE.hiringPlan.map((h, i) => (
                <li key={i} className="flex gap-2">
                  <span className="inline-flex w-20 flex-shrink-0 font-mono text-[10px] text-indigo-300">
                    {h.horizon}
                  </span>
                  <span className="flex-1">
                    <span className="font-semibold text-white">
                      {h.action}
                    </span>
                    <span className="text-white/50"> — {h.why}</span>
                  </span>
                </li>
              ))}
            </ul>
          </div>
        </section>

        {/* KPIs en tête */}
        <section className="mb-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <KpiCard
            label="Avancement global"
            value={`${pctDone}%`}
            sub={`${kpis.fait + kpis.na} / ${totalTasks} tâches`}
            icon={<CheckCircle2 className="h-5 w-5" />}
            color="text-emerald-300"
          />
          <KpiCard
            label="Kratos couvert"
            value={`${pctKratos}%`}
            sub={`${kpis.kratosFait} / ${kpis.kratosTotal} tâches automatisables`}
            icon={<Bot className="h-5 w-5" />}
            color="text-blue-300"
          />
          <KpiCard
            label="Postes à pourvoir"
            value={`${kpis.postesAPourvoir}`}
            sub="Rôles canoniques sans titulaire"
            icon={<Wrench className="h-5 w-5" />}
            color="text-amber-300"
          />
          <KpiCard
            label="Bloqué"
            value={`${kpis.bloque}`}
            sub="Tâches qui attendent quelque chose"
            icon={<Pause className="h-5 w-5" />}
            color={kpis.bloque > 0 ? "text-rose-300" : "text-white/40"}
          />
        </section>

        {/* Progression par pôle */}
        <section className="mb-5 rounded-2xl border border-brand-800 bg-brand-900 p-5">
          <h2 className="mb-3 text-sm font-bold text-white">
            Progression par pôle
          </h2>
          {poleProgress.length === 0 ? (
            <div className="text-sm text-white/40">
              Aucune tâche dans l'organigramme.{" "}
              <button
                type="button"
                onClick={runSeed}
                disabled={seeding}
                className="text-blue-300 underline hover:text-blue-200"
              >
                {seeding ? "Seed en cours…" : "Lancer le seed canonique"}
              </button>
            </div>
          ) : (
            <div className="space-y-2.5">
              {poleProgress.map((p) => (
                <div key={p.pole}>
                  <div className="mb-1 flex items-center justify-between text-xs">
                    <span className="font-semibold text-white">{p.pole}</span>
                    <span className="text-white/50">
                      {p.done} / {p.total} ({p.pct}%)
                    </span>
                  </div>
                  <div className="h-2 overflow-hidden rounded-full bg-brand-800">
                    <div
                      className={`${poleColor(p.pole)} h-full rounded-full transition-all`}
                      style={{ width: `${p.pct}%` }}
                    />
                  </div>
                </div>
              ))}
            </div>
          )}
        </section>

        {/* Banner: pas de seed encore */}
        {!loading && tasks.length === 0 ? (
          <div className="mb-5 flex items-center justify-between gap-3 rounded-xl border border-amber-500/40 bg-amber-500/10 px-4 py-3">
            <div className="text-sm">
              <p className="font-semibold text-amber-200">
                Aucune tâche canonique trouvée.
              </p>
              <p className="text-xs text-amber-200/70">
                Le seed crée la structure complète des 6 pôles (additif et
                idempotent — rien ne sera écrasé).
              </p>
            </div>
            <button
              type="button"
              onClick={runSeed}
              disabled={seeding}
              className="inline-flex items-center gap-1.5 rounded-lg bg-amber-500 px-3 py-1.5 text-sm font-semibold text-brand-950 hover:bg-amber-400 disabled:opacity-60"
            >
              {seeding ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Sparkles className="h-4 w-4" />
              )}
              Lancer le seed
            </button>
          </div>
        ) : null}

        {/* Filtres */}
        <section className="mb-4 flex flex-wrap items-center gap-2">
          <div className="relative flex-1 min-w-[200px]">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-white/40" />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Chercher dans les tâches…"
              className="input pl-9 text-sm"
            />
          </div>
          <select
            value={filterPole}
            onChange={(e) => setFilterPole(e.target.value)}
            className="input text-sm sm:w-48"
          >
            <option value="all">Tous les pôles</option>
            {POLES_ORDER.map((p) => (
              <option key={p} value={p}>
                {p}
              </option>
            ))}
          </select>
          <select
            value={filterState}
            onChange={(e) => setFilterState(e.target.value)}
            className="input text-sm sm:w-40"
          >
            <option value="all">Tous les états</option>
            {STATE_ORDER.map((s) => (
              <option key={s} value={s}>
                {STATE_LABEL[s]}
              </option>
            ))}
          </select>
          <select
            value={filterTier}
            onChange={(e) => setFilterTier(e.target.value)}
            className="input text-sm sm:w-40"
          >
            <option value="all">Tous les tiers</option>
            <option value="direction">Direction</option>
            <option value="adjoint">Adjoint</option>
            <option value="adjoint_virtuel">Kratos</option>
          </select>
          <select
            value={filterResp}
            onChange={(e) => setFilterResp(e.target.value)}
            className="input text-sm sm:w-48"
            title="Filtrer par responsable intérim"
          >
            <option value="all">Tous les responsables</option>
            {responsablesList.map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </select>
        </section>

        {error ? (
          <div className="mb-3 flex items-start justify-between gap-2 rounded-lg border border-blue-500/40 bg-blue-500/10 px-3 py-2 text-sm text-blue-200">
            <span>{error}</span>
            <button
              type="button"
              onClick={() => setError(null)}
              className="text-blue-200/60 hover:text-blue-200"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        ) : null}

        {loading ? (
          <div className="mt-10 flex justify-center">
            <Loader2 className="h-6 w-6 animate-spin text-blue-500" />
          </div>
        ) : (
          <section className="space-y-4">
            {byPole.length === 0 ? (
              <p className="rounded-xl border border-brand-800 bg-brand-900 p-6 text-center text-sm text-white/40">
                Aucune tâche ne correspond aux filtres.
              </p>
            ) : (
              byPole.map(([pole, list]) => (
                <div
                  key={pole}
                  className="rounded-2xl border border-brand-800 bg-brand-900 overflow-hidden"
                >
                  <div className="flex items-center gap-2 border-b border-brand-800 px-4 py-2.5">
                    <span
                      className={`h-2.5 w-2.5 rounded-full ${poleColor(pole)}`}
                    />
                    <h3 className="text-sm font-bold text-white">{pole}</h3>
                    <span className="rounded-full bg-white/5 px-2 text-[10px] font-semibold text-white/50">
                      {list.length}
                    </span>
                  </div>
                  <ul className="divide-y divide-brand-800">
                    {list.map((t) => {
                      const { role } = ancestry(t);
                      const currentState = (t.state || "planifie") as State;
                      const isProposal = (t.description || "").startsWith("💡");
                      const isKratos = t.execution_tier === "adjoint_virtuel";
                      return (
                        <li key={t.id} className="px-4 py-2.5">
                          <div className="flex items-start gap-3">
                            {/* État cliquable */}
                            <StateBadge
                              state={currentState}
                              onChange={(s) => setState(t.id, s)}
                            />
                            <div className="min-w-0 flex-1">
                              <div className="flex flex-wrap items-center gap-1.5">
                                <span className="text-sm text-white">
                                  {t.label}
                                </span>
                                {isKratos ? (
                                  <span className="inline-flex items-center gap-0.5 rounded bg-blue-500/15 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-blue-300">
                                    <Bot className="h-2.5 w-2.5" />
                                    Kratos
                                  </span>
                                ) : null}
                                {t.execution_tier === "direction" ? (
                                  <span className="rounded bg-amber-500/15 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-amber-300">
                                    Direction
                                  </span>
                                ) : null}
                                {isProposal ? (
                                  <span className="rounded bg-violet-500/15 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-violet-300">
                                    💡 Proposition
                                  </span>
                                ) : null}
                              </div>
                              <div className="mt-0.5 flex flex-wrap items-center gap-x-2 text-xs text-white/40">
                                {role ? <span>{role}</span> : null}
                                {(() => {
                                  const resp = responsableFor(t);
                                  if (!resp) return null;
                                  const isKratosResp = resp === "Kratos";
                                  return (
                                    <span
                                      className={`inline-flex items-center gap-0.5 rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${
                                        isKratosResp
                                          ? "bg-blue-500/15 text-blue-300"
                                          : "bg-violet-500/15 text-violet-300"
                                      }`}
                                      title="Responsable intérim"
                                    >
                                      {resp}
                                    </span>
                                  );
                                })()}
                                {t.state_note ? (
                                  <span className="text-emerald-300/80">
                                    · {t.state_note}
                                  </span>
                                ) : null}
                              </div>
                              {/* Inline edit note */}
                              {editingNoteFor === t.id ? (
                                <div className="mt-2 flex gap-1.5">
                                  <input
                                    autoFocus
                                    value={noteDraft}
                                    onChange={(e) => setNoteDraft(e.target.value)}
                                    placeholder="Note (ex. couvert par /app/...)"
                                    className="input flex-1 text-xs"
                                    onKeyDown={(e) => {
                                      if (e.key === "Enter")
                                        void saveStateNote(t.id, noteDraft);
                                      if (e.key === "Escape")
                                        setEditingNoteFor(null);
                                    }}
                                  />
                                  <button
                                    type="button"
                                    onClick={() => void saveStateNote(t.id, noteDraft)}
                                    className="rounded-md bg-blue-500 px-2 py-1 text-xs font-semibold text-white"
                                  >
                                    OK
                                  </button>
                                </div>
                              ) : (
                                <button
                                  type="button"
                                  onClick={() => {
                                    setNoteDraft(t.state_note || "");
                                    setEditingNoteFor(t.id);
                                  }}
                                  className="mt-1 text-[10px] text-white/30 hover:text-white/60"
                                >
                                  {t.state_note ? "Modifier la note" : "+ Ajouter une note"}
                                </button>
                              )}
                            </div>
                          </div>
                        </li>
                      );
                    })}
                  </ul>
                </div>
              ))
            )}
          </section>
        )}
      </div>
    </div>
  );
}

// --------------------------------------------------------------------------
// Composants
// --------------------------------------------------------------------------

function KpiCard({
  label,
  value,
  sub,
  icon,
  color
}: {
  label: string;
  value: string;
  sub: string;
  icon: React.ReactNode;
  color: string;
}) {
  return (
    <div className="rounded-2xl border border-brand-800 bg-brand-900 p-4">
      <div className="flex items-center justify-between">
        <p className="text-[10px] font-semibold uppercase tracking-wider text-white/40">
          {label}
        </p>
        <span className={color}>{icon}</span>
      </div>
      <p className="mt-2 text-2xl font-bold text-white">{value}</p>
      <p className="text-xs text-white/40">{sub}</p>
    </div>
  );
}

function StateBadge({
  state,
  onChange
}: {
  state: State;
  onChange: (s: State) => void;
}) {
  const [open, setOpen] = useState(false);
  const icon: Record<State, React.ReactNode> = {
    planifie: <Circle className="h-3.5 w-3.5" />,
    en_cours: <PlayCircle className="h-3.5 w-3.5" />,
    fait: <CheckCircle2 className="h-3.5 w-3.5" />,
    bloque: <Pause className="h-3.5 w-3.5" />,
    non_applicable: <X className="h-3.5 w-3.5" />
  };
  return (
    <div className="relative flex-shrink-0">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-semibold ${
          STATE_CLS[state] || STATE_CLS.planifie
        }`}
      >
        {icon[state]}
        {STATE_LABEL[state]}
        <ChevronDown className="h-3 w-3 opacity-60" />
      </button>
      {open ? (
        <>
          <button
            type="button"
            aria-label="Fermer"
            onClick={() => setOpen(false)}
            className="fixed inset-0 z-30"
          />
          <div className="absolute left-0 top-full z-40 mt-1 w-40 overflow-hidden rounded-lg border border-brand-800 bg-brand-950 shadow-lg">
            {STATE_ORDER.map((s) => (
              <button
                key={s}
                type="button"
                onClick={() => {
                  onChange(s);
                  setOpen(false);
                }}
                className={`flex w-full items-center gap-2 px-2.5 py-1.5 text-left text-xs hover:bg-brand-900 ${
                  s === state ? "bg-brand-900 text-white" : "text-white/70"
                }`}
              >
                <span className="text-white/60">{icon[s]}</span>
                {STATE_LABEL[s]}
              </button>
            ))}
          </div>
        </>
      ) : null}
    </div>
  );
}
