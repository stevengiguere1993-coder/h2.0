"use client";

import { use, useEffect, useState } from "react";
import {
  AlertTriangle,
  ArrowLeft,
  CheckCircle2,
  DollarSign,
  FileCheck,
  Loader2,
  Pencil,
  Play,
  Plus,
  Repeat,
  Save,
  Target,
  Trash2,
  TrendingUp,
  X
} from "lucide-react";

import { Link } from "@/i18n/navigation";
import { authedFetch } from "@/lib/auth";
import { EntreprisesTopbar } from "../../layout";

// ── Types ──────────────────────────────────────────────────────────────

type Entreprise = {
  id: number;
  name: string;
  color_accent: string;
};

type TacheTemplate = {
  id: number;
  entreprise_id: number;
  title: string;
  description?: string | null;
  departement?: string | null;
  impact?: number | null;
  confidence?: number | null;
  effort?: number | null;
  every_n: number;
  unit: string;
  lead_days: number;
  next_due: string;
  is_active: boolean;
  nb_materialized: number;
  last_materialized_at?: string | null;
};

type Snapshot = {
  id: number;
  entreprise_id: number;
  year_month: string;
  revenu?: number | null;
  depenses?: number | null;
  ebitda?: number | null;
  resultat_net?: number | null;
  tresorerie?: number | null;
  dette_long_terme?: number | null;
  valorisation_estimee?: number | null;
  source: string;
  notes?: string | null;
};

type ValuePlanDriver = {
  key: string;
  label: string;
  current?: number | null;
  target?: number | null;
  unit?: string | null;
};

type ValuePlan = {
  id: number;
  entreprise_id: number;
  target_valuation: number;
  target_date: string;
  multiple_ebitda?: number | null;
  multiple_revenu?: number | null;
  drivers: ValuePlanDriver[];
  these?: string | null;
  is_active: boolean;
};

type Milestone = {
  id: number;
  plan_id: number;
  label: string;
  target_date: string;
  target_value?: number | null;
  metric?: string | null;
  status: string;
  achieved_date?: string | null;
  achieved_value?: number | null;
};

// ── Helpers ────────────────────────────────────────────────────────────

const FREQ_UNITS = [
  { value: "jour", label: "jour(s)" },
  { value: "semaine", label: "semaine(s)" },
  { value: "mois", label: "mois" },
  { value: "annee", label: "année(s)" }
];

function fmtCurrency(n: number | null | undefined): string {
  if (n == null) return "—";
  return new Intl.NumberFormat("fr-CA", {
    style: "currency",
    currency: "CAD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2
  }).format(n);
}

function fmtPct(n: number | null | undefined): string {
  if (n == null) return "—";
  return `${n.toFixed(1)}%`;
}

function todayMonth(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-01`;
}

// ── Page ───────────────────────────────────────────────────────────────

export default function PilotagePage({
  params
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const entrepriseId = Number(id);

  const [ent, setEnt] = useState<Entreprise | null>(null);
  const [section, setSection] = useState<
    "recurrence" | "finance" | "value"
  >("recurrence");

  useEffect(() => {
    let cancelled = false;
    authedFetch(`/api/v1/entreprises/${entrepriseId}`)
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => {
        if (!cancelled && d) setEnt(d as Entreprise);
      });
    return () => {
      cancelled = true;
    };
  }, [entrepriseId]);

  return (
    <>
      <EntreprisesTopbar
        breadcrumbs={[
          { label: "Gestion d'entreprises", href: "/entreprises" },
          {
            label: ent?.name || "Entreprise",
            href: `/entreprises/${entrepriseId}`
          },
          { label: "Pilotage" }
        ]}
      />
      <div className="p-4 lg:p-6">
        <Link
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          href={`/entreprises/${entrepriseId}` as any}
          className="inline-flex items-center text-xs text-white/50 hover:text-violet-300"
        >
          <ArrowLeft className="mr-1 h-3.5 w-3.5" /> Retour à la fiche
        </Link>

        <header className="mt-3 flex items-start gap-3">
          <span
            className="h-10 w-10 flex-shrink-0 rounded-xl"
            style={{ backgroundColor: ent?.color_accent || "#7c3aed" }}
          />
          <div>
            <h1
              className="text-2xl font-bold text-white"
              style={{ fontFamily: "var(--font-display, ui-sans-serif, system-ui, sans-serif)" }}
            >
              Pilotage{ent ? ` · ${ent.name}` : ""}
            </h1>
            <p className="mt-1 text-sm text-white/60">
              Tâches récurrentes, finance mensuelle, plan de valorisation.
            </p>
          </div>
        </header>

        {/* Sections nav (sub-tabs) */}
        <nav
          className="mt-6 flex items-center gap-1 overflow-x-auto"
          style={{ borderBottom: "1px solid var(--qg-border)" }}
        >
          <SectionTab
            id="recurrence"
            label="Tâches récurrentes"
            icon={Repeat}
            active={section === "recurrence"}
            onClick={() => setSection("recurrence")}
          />
          <SectionTab
            id="finance"
            label="Finance"
            icon={DollarSign}
            active={section === "finance"}
            onClick={() => setSection("finance")}
          />
          <SectionTab
            id="value"
            label="Plan de valeur"
            icon={Target}
            active={section === "value"}
            onClick={() => setSection("value")}
          />
        </nav>

        <div className="mt-5">
          {section === "recurrence" ? (
            <RecurrenceSection entrepriseId={entrepriseId} />
          ) : null}
          {section === "finance" ? (
            <FinanceSection entrepriseId={entrepriseId} />
          ) : null}
          {section === "value" ? (
            <ValuePlanSection entrepriseId={entrepriseId} />
          ) : null}
        </div>
      </div>
    </>
  );
}

function SectionTab({
  label,
  icon: Icon,
  active,
  onClick
}: {
  id: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="inline-flex items-center gap-1.5 px-4 py-2 text-sm font-medium transition"
      style={{
        color: active ? "var(--qg-accent)" : "rgba(245,245,247,0.6)",
        borderBottom: active ? "2px solid var(--qg-accent)" : "2px solid transparent",
        marginBottom: "-1px"
      }}
    >
      <Icon className="h-4 w-4" />
      {label}
    </button>
  );
}

// ─── RECURRENCE ────────────────────────────────────────────────────────

function RecurrenceSection({ entrepriseId }: { entrepriseId: number }) {
  const [list, setList] = useState<TacheTemplate[] | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [showCompliance, setShowCompliance] = useState(false);
  const [running, setRunning] = useState(false);
  const [runMsg, setRunMsg] = useState<string | null>(null);

  async function reload() {
    const res = await authedFetch(
      `/api/v1/entreprises/${entrepriseId}/tache-templates`
    );
    if (res.ok) setList((await res.json()) as TacheTemplate[]);
  }
  useEffect(() => {
    void reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [entrepriseId]);

  async function runMaterialize() {
    setRunning(true);
    setRunMsg(null);
    try {
      const res = await authedFetch(
        "/api/v1/entreprises/tache-templates/run-materialize",
        { method: "POST" }
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const d = (await res.json()) as { taches_created: number };
      setRunMsg(
        `${d.taches_created} tâche${d.taches_created > 1 ? "s" : ""} créée${
          d.taches_created > 1 ? "s" : ""
        } à partir des templates dus.`
      );
      void reload();
    } catch (e) {
      setRunMsg((e as Error).message);
    } finally {
      setRunning(false);
    }
  }

  async function toggleActive(t: TacheTemplate) {
    await authedFetch(`/api/v1/entreprises/tache-templates/${t.id}`, {
      method: "PATCH",
      body: JSON.stringify({ is_active: !t.is_active })
    });
    void reload();
  }

  async function remove(t: TacheTemplate) {
    if (!confirm(`Supprimer le template « ${t.title} » ?`)) return;
    await authedFetch(`/api/v1/entreprises/tache-templates/${t.id}`, {
      method: "DELETE"
    });
    void reload();
  }

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm text-white/60">
          Définis des tâches qui se créent automatiquement (TPS/TVQ trimestrielle,
          rapprochement bancaire mensuel, etc.). Le cron vérifie chaque jour.
        </p>
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={() => setShowCompliance(true)}
            className="inline-flex items-center gap-1.5 rounded-lg border border-emerald-400/30 bg-emerald-500/10 px-3 py-1.5 text-xs font-semibold text-emerald-200 hover:bg-emerald-500/20"
          >
            <FileCheck className="h-3.5 w-3.5" />
            Compliance Québec
          </button>
          <button
            type="button"
            onClick={runMaterialize}
            disabled={running}
            className="btn-secondary inline-flex items-center text-xs disabled:opacity-60"
          >
            {running ? (
              <>
                <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                Exécution…
              </>
            ) : (
              <>
                <Play className="mr-1.5 h-3.5 w-3.5" />
                Matérialiser maintenant
              </>
            )}
          </button>
          <button
            type="button"
            onClick={() => setShowCreate(true)}
            className="btn-accent inline-flex items-center text-xs"
          >
            <Plus className="mr-1.5 h-3.5 w-3.5" />
            Nouveau template
          </button>
        </div>
      </div>

      {runMsg ? (
        <p className="mb-4 rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-xs text-emerald-300">
          <CheckCircle2 className="mr-1.5 inline h-3.5 w-3.5" />
          {runMsg}
        </p>
      ) : null}

      {list === null ? (
        <Loading />
      ) : list.length === 0 ? (
        <Empty msg="Aucun template récurrent. Crée-en un pour automatiser." />
      ) : (
        <ul className="space-y-2">
          {list.map((t) => (
            <li
              key={t.id}
              className="rounded-xl border border-brand-800 bg-brand-900 p-4"
            >
              <div className="flex items-start gap-3">
                <span className="mt-0.5 flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-lg bg-violet-500/15 text-violet-300">
                  <Repeat className="h-4 w-4" />
                </span>
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <h3 className="truncate text-sm font-bold text-white">
                      {t.title}
                    </h3>
                    {!t.is_active ? (
                      <span className="rounded-full border border-white/15 px-1.5 py-0.5 text-[10px] uppercase text-white/50">
                        Désactivé
                      </span>
                    ) : null}
                  </div>
                  <p className="mt-0.5 text-[11px] text-white/50">
                    Tous les {t.every_n} {t.unit}
                    {t.departement ? ` · ${t.departement}` : ""}
                    {" · prochain "}
                    <span className="text-white/70">{t.next_due}</span>
                    {" · lead "}
                    <span>{t.lead_days}j</span>
                  </p>
                  {t.description ? (
                    <p className="mt-1 text-xs text-white/60">{t.description}</p>
                  ) : null}
                  <p className="mt-2 text-[10px] text-white/40">
                    {t.nb_materialized} matérialisation
                    {t.nb_materialized > 1 ? "s" : ""}
                    {t.last_materialized_at
                      ? ` · dernière ${new Date(
                          t.last_materialized_at
                        ).toLocaleString("fr-CA")}`
                      : ""}
                  </p>
                </div>
                <div className="flex items-center gap-1">
                  <button
                    type="button"
                    onClick={() => toggleActive(t)}
                    className="rounded-lg border border-white/15 bg-brand-950 px-2 py-1 text-[10px] text-white/70 hover:text-white"
                    title={t.is_active ? "Désactiver" : "Activer"}
                  >
                    {t.is_active ? "Pause" : "Activer"}
                  </button>
                  <button
                    type="button"
                    onClick={() => remove(t)}
                    className="rounded-lg border border-white/15 bg-brand-950 p-1.5 text-white/40 hover:border-rose-400/50 hover:text-rose-300"
                    title="Supprimer"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}

      {showCreate ? (
        <CreateTemplateModal
          entrepriseId={entrepriseId}
          onClose={() => setShowCreate(false)}
          onSaved={() => {
            setShowCreate(false);
            void reload();
          }}
        />
      ) : null}

      {showCompliance ? (
        <ComplianceImportModal
          entrepriseId={entrepriseId}
          onClose={() => setShowCompliance(false)}
          onSaved={(msg) => {
            setShowCompliance(false);
            setRunMsg(msg);
            void reload();
          }}
        />
      ) : null}
    </div>
  );
}

type ComplianceItem = {
  code: string;
  label: string;
  description: string;
  departement: string;
  every_n: number;
  unit: string;
  lead_days: number;
};

function ComplianceImportModal({
  entrepriseId,
  onClose,
  onSaved
}: {
  entrepriseId: number;
  onClose: () => void;
  onSaved: (msg: string) => void;
}) {
  const [catalog, setCatalog] = useState<ComplianceItem[] | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [importing, setImporting] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    authedFetch(
      "/api/v1/entreprises/tache-templates/compliance-catalog"
    )
      .then((r) => (r.ok ? r.json() : []))
      .then((d) => {
        if (cancelled) return;
        const list = d as ComplianceItem[];
        setCatalog(list);
        // Présélection raisonnable : tout ce qui est mensuel ou trimestriel.
        const presel = new Set(
          list
            .filter(
              (c) =>
                (c.unit === "mois" && c.every_n <= 3) ||
                c.code === "req_annuel"
            )
            .map((c) => c.code)
        );
        setSelected(presel);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const grouped = (catalog || []).reduce<Record<string, ComplianceItem[]>>(
    (acc, c) => {
      (acc[c.departement] = acc[c.departement] || []).push(c);
      return acc;
    },
    {}
  );

  function toggle(code: string) {
    const next = new Set(selected);
    if (next.has(code)) next.delete(code);
    else next.add(code);
    setSelected(next);
  }

  async function submit() {
    if (selected.size === 0) return;
    setImporting(true);
    setErr(null);
    try {
      const res = await authedFetch(
        `/api/v1/entreprises/${entrepriseId}/tache-templates/import-compliance`,
        {
          method: "POST",
          body: JSON.stringify({ codes: [...selected] })
        }
      );
      if (!res.ok) {
        const t = await res.text();
        throw new Error(t.slice(0, 240) || `HTTP ${res.status}`);
      }
      const d = (await res.json()) as {
        created: number;
        skipped: string[];
      };
      const skipMsg =
        d.skipped.length > 0
          ? ` · ${d.skipped.length} déjà présent${d.skipped.length > 1 ? "s" : ""}`
          : "";
      onSaved(
        `${d.created} template${d.created > 1 ? "s" : ""} compliance importé${
          d.created > 1 ? "s" : ""
        }${skipMsg}.`
      );
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setImporting(false);
    }
  }

  return (
    <ModalShell title="Importer compliance Québec" onClose={onClose}>
      <p className="mb-3 text-xs text-white/60">
        Sélectionne les obligations qui s&apos;appliquent à cette entreprise.
        Les templates sont créés avec une 1ère échéance le 1er du mois prochain
        (ajustable ensuite). Idempotent : les titres déjà présents sont ignorés.
      </p>

      {catalog === null ? (
        <Loading />
      ) : (
        <div className="max-h-96 space-y-4 overflow-y-auto pr-1">
          {Object.entries(grouped).map(([dept, items]) => (
            <div key={dept}>
              <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-wider text-emerald-300">
                {dept}
              </p>
              <ul className="space-y-1">
                {items.map((c) => (
                  <li
                    key={c.code}
                    className={`flex cursor-pointer items-start gap-2 rounded-lg border p-2.5 text-sm transition ${
                      selected.has(c.code)
                        ? "border-emerald-400/40 bg-emerald-500/10"
                        : "border-brand-800 bg-brand-950 hover:border-white/20"
                    }`}
                    onClick={() => toggle(c.code)}
                  >
                    <input
                      type="checkbox"
                      checked={selected.has(c.code)}
                      onChange={() => toggle(c.code)}
                      className="mt-0.5 h-4 w-4 accent-emerald-500"
                    />
                    <div className="min-w-0 flex-1">
                      <p className="font-bold text-white">{c.label}</p>
                      <p className="mt-0.5 text-[11px] text-white/60">
                        {c.description}
                      </p>
                      <p className="mt-1 text-[10px] text-white/40">
                        Tous les {c.every_n} {c.unit} · lead {c.lead_days}j
                      </p>
                    </div>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      )}

      {err ? (
        <p className="mt-3 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
          <AlertTriangle className="mr-1.5 inline h-3.5 w-3.5" />
          {err}
        </p>
      ) : null}

      <div className="mt-4 flex items-center justify-between border-t border-brand-800 pt-3">
        <span className="text-xs text-white/50">
          {selected.size} sélectionnée{selected.size > 1 ? "s" : ""}
        </span>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={onClose}
            className="btn-secondary text-sm"
          >
            Annuler
          </button>
          <button
            type="button"
            onClick={submit}
            disabled={importing || selected.size === 0}
            className="btn-accent inline-flex items-center text-sm disabled:opacity-60"
          >
            {importing ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                Import…
              </>
            ) : (
              <>
                <FileCheck className="mr-2 h-4 w-4" />
                Importer la sélection
              </>
            )}
          </button>
        </div>
      </div>
    </ModalShell>
  );
}

function CreateTemplateModal({
  entrepriseId,
  onClose,
  onSaved
}: {
  entrepriseId: number;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [form, setForm] = useState({
    title: "",
    description: "",
    departement: "",
    every_n: "1",
    unit: "mois",
    lead_days: "7",
    next_due: todayMonth()
  });
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setErr(null);
    try {
      const body: Record<string, unknown> = {
        entreprise_id: entrepriseId,
        title: form.title.trim(),
        every_n: Number(form.every_n) || 1,
        unit: form.unit,
        lead_days: Number(form.lead_days) || 0,
        next_due: form.next_due,
        is_active: true
      };
      if (form.description.trim()) body.description = form.description.trim();
      if (form.departement.trim()) body.departement = form.departement.trim();
      const res = await authedFetch(
        "/api/v1/entreprises/tache-templates",
        {
          method: "POST",
          body: JSON.stringify(body)
        }
      );
      if (!res.ok) {
        const t = await res.text();
        throw new Error(t.slice(0, 240) || `HTTP ${res.status}`);
      }
      onSaved();
    } catch (e2) {
      setErr((e2 as Error).message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <ModalShell title="Nouveau template récurrent" onClose={onClose}>
      <form onSubmit={submit} className="grid gap-4">
        <div>
          <label className="label">Titre</label>
          <input
            required
            value={form.title}
            onChange={(e) => setForm({ ...form, title: e.target.value })}
            className="input"
            placeholder="ex. Faire la TPS/TVQ trimestrielle"
          />
        </div>
        <div>
          <label className="label">Description (optionnel)</label>
          <textarea
            value={form.description}
            onChange={(e) =>
              setForm({ ...form, description: e.target.value })
            }
            rows={2}
            className="input"
            placeholder="Comment exécuter la tâche, liens utiles…"
          />
        </div>
        <div>
          <label className="label">Département (optionnel)</label>
          <input
            value={form.departement}
            onChange={(e) =>
              setForm({ ...form, departement: e.target.value })
            }
            className="input"
            placeholder="ex. Compta, RH, Marketing"
          />
        </div>
        <div className="grid grid-cols-3 gap-2">
          <div>
            <label className="label">Tous les</label>
            <input
              type="number"
              min={1}
              value={form.every_n}
              onChange={(e) => setForm({ ...form, every_n: e.target.value })}
              className="input"
            />
          </div>
          <div>
            <label className="label">Unité</label>
            <select
              value={form.unit}
              onChange={(e) => setForm({ ...form, unit: e.target.value })}
              className="input"
            >
              {FREQ_UNITS.map((u) => (
                <option key={u.value} value={u.value}>
                  {u.label}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="label">Lead (jours)</label>
            <input
              type="number"
              min={0}
              value={form.lead_days}
              onChange={(e) =>
                setForm({ ...form, lead_days: e.target.value })
              }
              className="input"
            />
          </div>
        </div>
        <div>
          <label className="label">Première échéance</label>
          <input
            type="date"
            required
            value={form.next_due}
            onChange={(e) => setForm({ ...form, next_due: e.target.value })}
            className="input"
          />
        </div>

        {err ? (
          <p className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
            <AlertTriangle className="mr-1.5 inline h-3.5 w-3.5" />
            {err}
          </p>
        ) : null}

        <div className="flex items-center justify-end gap-2 border-t border-brand-800 pt-4">
          <button type="button" onClick={onClose} className="btn-secondary text-sm">
            Annuler
          </button>
          <button
            type="submit"
            disabled={saving || !form.title.trim()}
            className="btn-accent inline-flex items-center text-sm disabled:opacity-60"
          >
            {saving ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                Création…
              </>
            ) : (
              "Créer"
            )}
          </button>
        </div>
      </form>
    </ModalShell>
  );
}

// ─── FINANCE ───────────────────────────────────────────────────────────

function FinanceSection({ entrepriseId }: { entrepriseId: number }) {
  const [snapshots, setSnapshots] = useState<Snapshot[] | null>(null);
  const [showAdd, setShowAdd] = useState(false);

  async function reload() {
    const res = await authedFetch(
      `/api/v1/entreprises/${entrepriseId}/finance/snapshots?months=24`
    );
    if (res.ok) setSnapshots((await res.json()) as Snapshot[]);
  }
  useEffect(() => {
    void reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [entrepriseId]);

  // Compute mini stats
  const stats = (() => {
    if (!snapshots || snapshots.length === 0) return null;
    const last = snapshots[snapshots.length - 1];
    const ttm = snapshots.slice(-12);
    const sumRev = ttm.reduce((a, s) => a + (s.revenu || 0), 0);
    const sumEbt = ttm.reduce((a, s) => a + (s.ebitda || 0), 0);
    return {
      lastMonth: last.year_month,
      revenuTtm: sumRev,
      ebitdaTtm: sumEbt,
      tresorerie: last.tresorerie,
      valorisation: last.valorisation_estimee
    };
  })();

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm text-white/60">
          Suivi mensuel : revenu, dépenses, EBITDA, trésorerie, valorisation
          estimée. Saisis manuellement ou importe depuis QBO (à venir).
        </p>
        <button
          type="button"
          onClick={() => setShowAdd(true)}
          className="btn-accent inline-flex items-center text-xs"
        >
          <Plus className="mr-1.5 h-3.5 w-3.5" />
          Saisir un mois
        </button>
      </div>

      {stats ? (
        <section className="mb-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Kpi
            label="Revenu (12 mois glissants)"
            value={fmtCurrency(stats.revenuTtm)}
            icon={DollarSign}
            tone="emerald"
          />
          <Kpi
            label="EBITDA (12 mois)"
            value={fmtCurrency(stats.ebitdaTtm)}
            icon={TrendingUp}
            tone="violet"
          />
          <Kpi
            label="Trésorerie"
            value={fmtCurrency(stats.tresorerie)}
            sub={`au ${stats.lastMonth}`}
            icon={DollarSign}
            tone="sky"
          />
          <Kpi
            label="Valorisation estimée"
            value={fmtCurrency(stats.valorisation)}
            sub={`au ${stats.lastMonth}`}
            icon={Target}
            tone="amber"
          />
        </section>
      ) : null}

      {/* Mini graphique inline (sparkline SVG) */}
      {snapshots && snapshots.length > 1 ? (
        <FinanceMiniChart snapshots={snapshots} />
      ) : null}

      {snapshots === null ? (
        <Loading />
      ) : snapshots.length === 0 ? (
        <Empty msg="Aucun snapshot financier. Saisis le premier mois." />
      ) : (
        <div className="mt-5 overflow-hidden rounded-2xl border border-brand-800 bg-brand-900">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-brand-800 bg-brand-950 text-[10px] uppercase tracking-wider text-white/50">
              <tr>
                <th className="px-3 py-2">Mois</th>
                <th className="px-3 py-2 text-right">Revenu</th>
                <th className="px-3 py-2 text-right">Dépenses</th>
                <th className="px-3 py-2 text-right">EBITDA</th>
                <th className="px-3 py-2 text-right">Trésorerie</th>
                <th className="px-3 py-2 text-right">Valorisation</th>
                <th className="px-3 py-2">Source</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-brand-800">
              {[...snapshots].reverse().map((s) => (
                <tr key={s.id}>
                  <td className="px-3 py-1.5 text-xs text-white">
                    {s.year_month.slice(0, 7)}
                  </td>
                  <td className="px-3 py-1.5 text-right text-xs">
                    {fmtCurrency(s.revenu)}
                  </td>
                  <td className="px-3 py-1.5 text-right text-xs text-white/60">
                    {fmtCurrency(s.depenses)}
                  </td>
                  <td
                    className={`px-3 py-1.5 text-right text-xs ${
                      (s.ebitda || 0) >= 0 ? "text-emerald-300" : "text-rose-300"
                    }`}
                  >
                    {fmtCurrency(s.ebitda)}
                  </td>
                  <td className="px-3 py-1.5 text-right text-xs text-sky-300">
                    {fmtCurrency(s.tresorerie)}
                  </td>
                  <td className="px-3 py-1.5 text-right text-xs text-amber-200">
                    {fmtCurrency(s.valorisation_estimee)}
                  </td>
                  <td className="px-3 py-1.5 text-[10px] uppercase text-white/40">
                    {s.source}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {showAdd ? (
        <SnapshotModal
          entrepriseId={entrepriseId}
          onClose={() => setShowAdd(false)}
          onSaved={() => {
            setShowAdd(false);
            void reload();
          }}
        />
      ) : null}
    </div>
  );
}

function FinanceMiniChart({ snapshots }: { snapshots: Snapshot[] }) {
  const data = snapshots.map((s) => ({
    month: s.year_month.slice(0, 7),
    revenu: s.revenu || 0,
    ebitda: s.ebitda || 0
  }));
  const maxRev = Math.max(...data.map((d) => d.revenu), 1);
  const w = 600;
  const h = 80;
  const step = data.length > 1 ? w / (data.length - 1) : 0;

  function pointsFor(key: "revenu" | "ebitda"): string {
    return data
      .map((d, i) => {
        const x = i * step;
        const v = d[key];
        const y = h - (Math.max(v, 0) / maxRev) * (h - 10) - 5;
        return `${x.toFixed(1)},${y.toFixed(1)}`;
      })
      .join(" ");
  }

  return (
    <div className="rounded-xl border border-brand-800 bg-brand-900 p-3">
      <p className="mb-2 text-[10px] font-semibold uppercase tracking-wider text-white/50">
        Évolution {data.length} mois — <span className="text-emerald-300">revenu</span>{" "}
        / <span className="text-violet-300">EBITDA</span>
      </p>
      <svg
        viewBox={`0 0 ${w} ${h}`}
        className="h-20 w-full"
        preserveAspectRatio="none"
      >
        <polyline
          fill="none"
          stroke="#34d399"
          strokeWidth="2"
          points={pointsFor("revenu")}
        />
        <polyline
          fill="none"
          stroke="#a78bfa"
          strokeWidth="2"
          points={pointsFor("ebitda")}
        />
      </svg>
    </div>
  );
}

function SnapshotModal({
  entrepriseId,
  onClose,
  onSaved
}: {
  entrepriseId: number;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [form, setForm] = useState({
    year_month: todayMonth(),
    revenu: "",
    depenses: "",
    ebitda: "",
    tresorerie: "",
    valorisation_estimee: ""
  });
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setErr(null);
    try {
      const body: Record<string, unknown> = {
        entreprise_id: entrepriseId,
        year_month: form.year_month,
        source: "manuel"
      };
      ["revenu", "depenses", "ebitda", "tresorerie", "valorisation_estimee"].forEach(
        (k) => {
          const v = (form as Record<string, string>)[k];
          if (v !== "") body[k] = Number(v);
        }
      );
      const res = await authedFetch(
        `/api/v1/entreprises/${entrepriseId}/finance/snapshots`,
        { method: "PUT", body: JSON.stringify(body) }
      );
      if (!res.ok) {
        const t = await res.text();
        throw new Error(t.slice(0, 240) || `HTTP ${res.status}`);
      }
      onSaved();
    } catch (e2) {
      setErr((e2 as Error).message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <ModalShell title="Snapshot financier" onClose={onClose}>
      <form onSubmit={submit} className="grid gap-3">
        <div>
          <label className="label">Mois</label>
          <input
            type="date"
            required
            value={form.year_month}
            onChange={(e) =>
              setForm({ ...form, year_month: e.target.value })
            }
            className="input"
          />
          <p className="mt-1 text-[10px] text-white/40">
            La date sera arrondie au 1er du mois.
          </p>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <NumField
            label="Revenu"
            value={form.revenu}
            onChange={(v) => setForm({ ...form, revenu: v })}
          />
          <NumField
            label="Dépenses"
            value={form.depenses}
            onChange={(v) => setForm({ ...form, depenses: v })}
          />
          <NumField
            label="EBITDA"
            value={form.ebitda}
            onChange={(v) => setForm({ ...form, ebitda: v })}
          />
          <NumField
            label="Trésorerie"
            value={form.tresorerie}
            onChange={(v) => setForm({ ...form, tresorerie: v })}
          />
          <NumField
            label="Valorisation estimée"
            value={form.valorisation_estimee}
            onChange={(v) =>
              setForm({ ...form, valorisation_estimee: v })
            }
          />
        </div>

        {err ? (
          <p className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
            {err}
          </p>
        ) : null}

        <div className="flex items-center justify-end gap-2 border-t border-brand-800 pt-3">
          <button type="button" onClick={onClose} className="btn-secondary text-sm">
            Annuler
          </button>
          <button
            type="submit"
            disabled={saving}
            className="btn-accent inline-flex items-center text-sm disabled:opacity-60"
          >
            {saving ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                Enregistrement…
              </>
            ) : (
              <>
                <Save className="mr-2 h-4 w-4" />
                Enregistrer
              </>
            )}
          </button>
        </div>
      </form>
    </ModalShell>
  );
}

function NumField({
  label,
  value,
  onChange
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <div>
      <label className="label">{label}</label>
      <input
        type="number"
        step="0.01"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="input"
        placeholder="—"
      />
    </div>
  );
}

// ─── VALUE PLAN ────────────────────────────────────────────────────────

function ValuePlanSection({ entrepriseId }: { entrepriseId: number }) {
  const [plan, setPlan] = useState<ValuePlan | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [milestones, setMilestones] = useState<Milestone[]>([]);
  const [showEdit, setShowEdit] = useState(false);
  const [showMilestone, setShowMilestone] = useState(false);

  async function reload() {
    const res = await authedFetch(
      `/api/v1/entreprises/${entrepriseId}/value-plan`
    );
    setLoaded(true);
    if (res.ok) {
      const p = (await res.json()) as ValuePlan | null;
      setPlan(p);
      if (p) {
        const ms = await authedFetch(
          `/api/v1/entreprises/value-plans/${p.id}/milestones`
        );
        if (ms.ok) setMilestones((await ms.json()) as Milestone[]);
      } else {
        setMilestones([]);
      }
    }
  }
  useEffect(() => {
    void reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [entrepriseId]);

  if (!loaded) return <Loading />;

  const targetYear = plan?.target_date
    ? new Date(plan.target_date).getFullYear()
    : null;

  return (
    <div>
      {!plan ? (
        <div className="rounded-2xl border border-dashed border-brand-800 bg-brand-900/40 p-8 text-center">
          <Target className="mx-auto h-10 w-10 text-white/30" />
          <h3 className="mt-3 text-sm font-bold text-white">
            Aucun plan de valeur défini
          </h3>
          <p className="mt-1 text-xs text-white/60">
            Définis une cible de valorisation et la date pour la mesurer.
          </p>
          <button
            type="button"
            onClick={() => setShowEdit(true)}
            className="btn-accent mt-4 inline-flex items-center text-sm"
          >
            <Plus className="mr-2 h-4 w-4" /> Créer un plan
          </button>
        </div>
      ) : (
        <>
          <div className="rounded-2xl border border-brand-800 bg-brand-900 p-5">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <p className="text-[10px] uppercase tracking-wider text-white/50">
                  Objectif valorisation {targetYear || ""}
                </p>
                <p
                  className="mt-1 text-3xl font-bold text-white"
                  style={{ fontFamily: "var(--font-display, ui-sans-serif, system-ui, sans-serif)" }}
                >
                  {fmtCurrency(plan.target_valuation)}
                </p>
                <p className="mt-1 text-xs text-white/50">
                  Cible : {plan.target_date}
                  {plan.multiple_ebitda
                    ? ` · ${plan.multiple_ebitda}× EBITDA`
                    : plan.multiple_revenu
                    ? ` · ${plan.multiple_revenu}× revenu`
                    : ""}
                </p>
              </div>
              <button
                type="button"
                onClick={() => setShowEdit(true)}
                className="btn-secondary inline-flex items-center text-xs"
              >
                <Pencil className="mr-1.5 h-3.5 w-3.5" /> Modifier
              </button>
            </div>

            {plan.these ? (
              <p className="mt-4 border-t border-brand-800 pt-3 text-sm text-white/70">
                {plan.these}
              </p>
            ) : null}

            {plan.drivers && plan.drivers.length > 0 ? (
              <div className="mt-4 grid gap-2 sm:grid-cols-2">
                {plan.drivers.map((d) => {
                  const pct =
                    d.target && d.target > 0 && d.current != null
                      ? Math.min(100, (d.current / d.target) * 100)
                      : 0;
                  return (
                    <div
                      key={d.key}
                      className="rounded-lg border border-brand-800 bg-brand-950 p-3"
                    >
                      <p className="text-[11px] font-semibold text-white/70">
                        {d.label}
                      </p>
                      <p className="mt-1 text-xs text-white">
                        {d.current ?? "—"} / {d.target ?? "—"}
                        {d.unit ? ` ${d.unit}` : ""}
                      </p>
                      <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-brand-800">
                        <div
                          className="h-full rounded-full bg-violet-400"
                          style={{ width: `${pct}%` }}
                        />
                      </div>
                    </div>
                  );
                })}
              </div>
            ) : null}
          </div>

          <section className="mt-5">
            <div className="mb-3 flex items-center justify-between">
              <h3 className="text-sm font-semibold uppercase tracking-wider text-violet-300">
                Jalons
              </h3>
              <button
                type="button"
                onClick={() => setShowMilestone(true)}
                className="btn-secondary inline-flex items-center text-xs"
              >
                <Plus className="mr-1.5 h-3.5 w-3.5" /> Ajouter
              </button>
            </div>

            {milestones.length === 0 ? (
              <Empty msg="Aucun jalon. Décompose la cible en étapes mesurables." />
            ) : (
              <ul className="space-y-2">
                {milestones.map((m) => (
                  <li
                    key={m.id}
                    className="flex items-center gap-3 rounded-xl border border-brand-800 bg-brand-900 p-3"
                  >
                    <div
                      className={`flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-lg text-xs font-bold ${
                        m.status === "atteint"
                          ? "bg-emerald-500/15 text-emerald-300"
                          : m.status === "manque"
                          ? "bg-rose-500/15 text-rose-300"
                          : m.status === "en_cours"
                          ? "bg-amber-500/15 text-amber-300"
                          : "bg-white/10 text-white/60"
                      }`}
                    >
                      {m.status === "atteint" ? "✓" : "·"}
                    </div>
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm font-bold text-white">
                        {m.label}
                      </p>
                      <p className="text-[11px] text-white/50">
                        Cible {m.target_date}
                        {m.target_value
                          ? ` · ${fmtCurrency(m.target_value)}`
                          : ""}
                        {m.metric ? ` · ${m.metric}` : ""}
                      </p>
                    </div>
                    <span className="rounded-full bg-brand-950 px-2 py-0.5 text-[10px] uppercase text-white/60">
                      {m.status}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </>
      )}

      {showEdit ? (
        <ValuePlanModal
          entrepriseId={entrepriseId}
          plan={plan}
          onClose={() => setShowEdit(false)}
          onSaved={() => {
            setShowEdit(false);
            void reload();
          }}
        />
      ) : null}

      {showMilestone && plan ? (
        <MilestoneModal
          planId={plan.id}
          onClose={() => setShowMilestone(false)}
          onSaved={() => {
            setShowMilestone(false);
            void reload();
          }}
        />
      ) : null}
    </div>
  );
}

function ValuePlanModal({
  entrepriseId,
  plan,
  onClose,
  onSaved
}: {
  entrepriseId: number;
  plan: ValuePlan | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [form, setForm] = useState({
    target_valuation: plan ? String(plan.target_valuation) : "",
    target_date: plan?.target_date || "",
    multiple_ebitda: plan?.multiple_ebitda ? String(plan.multiple_ebitda) : "",
    multiple_revenu: plan?.multiple_revenu ? String(plan.multiple_revenu) : "",
    these: plan?.these || ""
  });
  const [drivers, setDrivers] = useState<ValuePlanDriver[]>(
    plan?.drivers || []
  );
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  function addDriver() {
    setDrivers([
      ...drivers,
      { key: `d${drivers.length}`, label: "", current: null, target: null, unit: "" }
    ]);
  }
  function removeDriver(i: number) {
    setDrivers(drivers.filter((_, idx) => idx !== i));
  }
  function updateDriver(i: number, patch: Partial<ValuePlanDriver>) {
    setDrivers(drivers.map((d, idx) => (idx === i ? { ...d, ...patch } : d)));
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setErr(null);
    try {
      const body: Record<string, unknown> = {
        entreprise_id: entrepriseId,
        target_valuation: Number(form.target_valuation),
        target_date: form.target_date,
        is_active: true,
        drivers: drivers.map((d) => ({
          key: d.key,
          label: d.label,
          current: d.current ?? null,
          target: d.target ?? null,
          unit: d.unit || null
        }))
      };
      if (form.multiple_ebitda) body.multiple_ebitda = Number(form.multiple_ebitda);
      if (form.multiple_revenu) body.multiple_revenu = Number(form.multiple_revenu);
      if (form.these.trim()) body.these = form.these.trim();

      const url = plan
        ? `/api/v1/entreprises/value-plans/${plan.id}`
        : "/api/v1/entreprises/value-plans";
      const res = await authedFetch(url, {
        method: plan ? "PATCH" : "POST",
        body: JSON.stringify(body)
      });
      if (!res.ok) {
        const t = await res.text();
        throw new Error(t.slice(0, 240) || `HTTP ${res.status}`);
      }
      onSaved();
    } catch (e2) {
      setErr((e2 as Error).message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <ModalShell
      title={plan ? "Modifier le plan de valeur" : "Créer le plan de valeur"}
      onClose={onClose}
    >
      <form onSubmit={submit} className="grid gap-4">
        <div className="grid grid-cols-2 gap-3">
          <NumField
            label="Valorisation cible (CAD)"
            value={form.target_valuation}
            onChange={(v) => setForm({ ...form, target_valuation: v })}
          />
          <div>
            <label className="label">Date cible</label>
            <input
              type="date"
              required
              value={form.target_date}
              onChange={(e) =>
                setForm({ ...form, target_date: e.target.value })
              }
              className="input"
            />
          </div>
          <NumField
            label="Multiple EBITDA"
            value={form.multiple_ebitda}
            onChange={(v) => setForm({ ...form, multiple_ebitda: v })}
          />
          <NumField
            label="Multiple revenu"
            value={form.multiple_revenu}
            onChange={(v) => setForm({ ...form, multiple_revenu: v })}
          />
        </div>

        <div>
          <label className="label">Thèse / stratégie</label>
          <textarea
            value={form.these}
            onChange={(e) => setForm({ ...form, these: e.target.value })}
            rows={3}
            className="input"
            placeholder="Pourquoi cette cible est atteignable…"
          />
        </div>

        <div>
          <div className="mb-2 flex items-center justify-between">
            <label className="label mb-0">Drivers de valeur</label>
            <button
              type="button"
              onClick={addDriver}
              className="text-xs text-violet-300 hover:text-violet-200"
            >
              + Ajouter
            </button>
          </div>
          {drivers.length === 0 ? (
            <p className="text-[11px] text-white/40">
              Ex. Marge EBITDA, ARR, churn, NPS — métriques qui propulsent la valo.
            </p>
          ) : (
            <ul className="space-y-2">
              {drivers.map((d, i) => (
                <li
                  key={i}
                  className="grid grid-cols-12 items-center gap-2 rounded-lg border border-brand-800 bg-brand-950 p-2"
                >
                  <input
                    placeholder="Label"
                    value={d.label}
                    onChange={(e) => updateDriver(i, { label: e.target.value })}
                    className="input col-span-4 text-xs"
                  />
                  <input
                    type="number"
                    placeholder="Actuel"
                    value={d.current ?? ""}
                    onChange={(e) =>
                      updateDriver(i, {
                        current: e.target.value ? Number(e.target.value) : null
                      })
                    }
                    className="input col-span-3 text-xs"
                  />
                  <input
                    type="number"
                    placeholder="Cible"
                    value={d.target ?? ""}
                    onChange={(e) =>
                      updateDriver(i, {
                        target: e.target.value ? Number(e.target.value) : null
                      })
                    }
                    className="input col-span-3 text-xs"
                  />
                  <input
                    placeholder="Unité"
                    value={d.unit || ""}
                    onChange={(e) => updateDriver(i, { unit: e.target.value })}
                    className="input col-span-1 text-xs"
                  />
                  <button
                    type="button"
                    onClick={() => removeDriver(i)}
                    className="col-span-1 rounded border border-white/10 p-1 text-white/50 hover:border-rose-400/40 hover:text-rose-300"
                  >
                    <X className="h-3 w-3" />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>

        {err ? (
          <p className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
            {err}
          </p>
        ) : null}

        <div className="flex items-center justify-end gap-2 border-t border-brand-800 pt-3">
          <button type="button" onClick={onClose} className="btn-secondary text-sm">
            Annuler
          </button>
          <button
            type="submit"
            disabled={
              saving || !form.target_valuation || !form.target_date
            }
            className="btn-accent inline-flex items-center text-sm disabled:opacity-60"
          >
            {saving ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" /> Enregistrement…
              </>
            ) : (
              "Enregistrer"
            )}
          </button>
        </div>
      </form>
    </ModalShell>
  );
}

function MilestoneModal({
  planId,
  onClose,
  onSaved
}: {
  planId: number;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [form, setForm] = useState({
    label: "",
    target_date: "",
    target_value: "",
    metric: ""
  });
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setErr(null);
    try {
      const body: Record<string, unknown> = {
        plan_id: planId,
        label: form.label.trim(),
        target_date: form.target_date,
        status: "a_venir"
      };
      if (form.target_value) body.target_value = Number(form.target_value);
      if (form.metric.trim()) body.metric = form.metric.trim();
      const res = await authedFetch(
        "/api/v1/entreprises/value-milestones",
        { method: "POST", body: JSON.stringify(body) }
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      onSaved();
    } catch (e2) {
      setErr((e2 as Error).message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <ModalShell title="Nouveau jalon" onClose={onClose}>
      <form onSubmit={submit} className="grid gap-3">
        <div>
          <label className="label">Description</label>
          <input
            required
            value={form.label}
            onChange={(e) => setForm({ ...form, label: e.target.value })}
            className="input"
            placeholder="ex. Atteindre 1M$ ARR"
          />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="label">Date cible</label>
            <input
              type="date"
              required
              value={form.target_date}
              onChange={(e) =>
                setForm({ ...form, target_date: e.target.value })
              }
              className="input"
            />
          </div>
          <NumField
            label="Valeur cible"
            value={form.target_value}
            onChange={(v) => setForm({ ...form, target_value: v })}
          />
        </div>
        <div>
          <label className="label">Métrique (optionnel)</label>
          <input
            value={form.metric}
            onChange={(e) => setForm({ ...form, metric: e.target.value })}
            className="input"
            placeholder="ex. revenu, ebitda, ARR"
          />
        </div>

        {err ? (
          <p className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
            {err}
          </p>
        ) : null}

        <div className="flex items-center justify-end gap-2 border-t border-brand-800 pt-3">
          <button type="button" onClick={onClose} className="btn-secondary text-sm">
            Annuler
          </button>
          <button
            type="submit"
            disabled={saving || !form.label.trim() || !form.target_date}
            className="btn-accent inline-flex items-center text-sm disabled:opacity-60"
          >
            {saving ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              "Créer"
            )}
          </button>
        </div>
      </form>
    </ModalShell>
  );
}

// ─── shared ────────────────────────────────────────────────────────────

function Loading() {
  return (
    <p className="text-xs text-white/50">
      <Loader2 className="mr-1 inline h-3 w-3 animate-spin" /> Chargement…
    </p>
  );
}

function Empty({ msg }: { msg: string }) {
  return (
    <p className="rounded-lg border border-brand-800 bg-brand-900 px-4 py-3 text-sm text-white/60">
      {msg}
    </p>
  );
}

function Kpi({
  label,
  value,
  sub,
  icon: Icon,
  tone
}: {
  label: string;
  value: string;
  sub?: string;
  icon: React.ComponentType<{ className?: string }>;
  tone: "emerald" | "violet" | "sky" | "amber";
}) {
  const cls: Record<typeof tone, string> = {
    emerald: "bg-emerald-500/15 text-emerald-300",
    violet: "bg-violet-500/15 text-violet-300",
    sky: "bg-sky-500/15 text-sky-300",
    amber: "bg-amber-500/15 text-amber-300"
  };
  return (
    <div className="rounded-2xl border border-brand-800 bg-brand-900 p-4">
      <div className="flex items-center justify-between">
        <span className="text-[10px] font-semibold uppercase tracking-wider text-white/50">
          {label}
        </span>
        <span
          className={`flex h-8 w-8 items-center justify-center rounded-lg ${cls[tone]}`}
        >
          <Icon className="h-4 w-4" />
        </span>
      </div>
      <div className="mt-3 text-2xl font-bold text-white">{value}</div>
      {sub ? <div className="mt-1 text-xs text-white/50">{sub}</div> : null}
    </div>
  );
}

function ModalShell({
  title,
  onClose,
  children
}: {
  title: string;
  onClose: () => void;
  children: React.ReactNode;
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/70 p-4 backdrop-blur-sm">
      <div className="my-8 w-full max-w-2xl rounded-2xl border border-brand-800 bg-brand-950 shadow-2xl">
        <div className="flex items-center justify-between border-b border-brand-800 px-5 py-3">
          <h2 className="text-sm font-bold uppercase tracking-wider text-violet-300">
            {title}
          </h2>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md p-1.5 text-white/60 hover:bg-brand-900 hover:text-white"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="p-5">{children}</div>
      </div>
    </div>
  );
}
