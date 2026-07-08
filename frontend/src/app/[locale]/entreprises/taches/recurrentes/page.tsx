"use client";

import { useEffect, useMemo, useState } from "react";
import {
  CheckCircle2,
  Loader2,
  Pause,
  Pencil,
  Play,
  Plus,
  Repeat,
  Search,
  Trash2,
  X
} from "lucide-react";

import { PageDriveSection } from "@/components/drive/PageDriveSection";
import { authedFetch } from "@/lib/auth";
import { useConfirm } from "@/components/confirm-dialog";
import { QGTopbar, useEntreprisesLayout } from "../../layout";
import { Link } from "@/i18n/navigation";
import {
  TASK_PRIORITY_OPTIONS,
  TASK_STATUS_OPTIONS,
  type TaskStatusValue
} from "@/lib/task-config";
import {
  ImmeublePicker,
  type ImmeubleMini
} from "@/components/immeuble-picker";

/**
 * Page globale `/entreprises/taches/recurrentes` — refonte complète.
 *
 * - Liste cross-entreprise avec filtres (recherche, statut par
 *   défaut, fréquence, actifs seulement, entreprise).
 * - Création complète façon « tâche normale » :
 *     · multi-select entreprise (≥1, obligatoire)
 *     · titre, statut par défaut, lead_days, récurrence
 *       (jour/semaine/mois/année/custom), 1ère échéance — TOUS
 *       obligatoires
 *     · ICE (impact/confidence/effort) — obligatoires
 *     · immeuble (multi), département, notes — optionnels
 */

type TacheTemplate = {
  id: number;
  entreprise_id: number;
  entreprise_name: string;
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
  default_status: string;
  immeuble_ids: number[];
  is_active: boolean;
  nb_materialized: number;
  last_materialized_at?: string | null;
};

const FREQ_PRESETS: Array<{
  key: string;
  label: string;
  every_n: number;
  unit: string;
}> = [
  { key: "daily", label: "Quotidienne", every_n: 1, unit: "jour" },
  { key: "weekly", label: "Hebdomadaire", every_n: 1, unit: "semaine" },
  { key: "biweekly", label: "Aux 2 semaines", every_n: 2, unit: "semaine" },
  { key: "monthly", label: "Mensuelle", every_n: 1, unit: "mois" },
  { key: "quarterly", label: "Trimestrielle", every_n: 3, unit: "mois" },
  { key: "yearly", label: "Annuelle", every_n: 1, unit: "annee" },
  { key: "custom", label: "Personnalisée", every_n: 1, unit: "mois" }
];

const FREQ_UNITS = [
  { value: "jour", label: "jour(s)" },
  { value: "semaine", label: "semaine(s)" },
  { value: "mois", label: "mois" },
  { value: "annee", label: "année(s)" }
];

function todayPlusDays(n: number): string {
  const d = new Date();
  d.setDate(d.getDate() + n);
  return d.toISOString().slice(0, 10);
}

function formatFreq(every_n: number, unit: string): string {
  // Match d'un preset si possible (sinon affichage brut « tous les N <unit> »).
  for (const p of FREQ_PRESETS) {
    if (p.key === "custom") continue;
    if (p.every_n === every_n && p.unit === unit) return p.label;
  }
  return `Tous les ${every_n} ${unit}`;
}

export default function TachesRecurrentesPage() {
  const [list, setList] = useState<TacheTemplate[] | null>(null);
  const [running, setRunning] = useState(false);
  const [runMsg, setRunMsg] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [editing, setEditing] = useState<TacheTemplate | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Filtres (style tableau de tâches normal).
  const [search, setSearch] = useState("");
  const [filterStatus, setFilterStatus] = useState<string>("");
  const [filterFreq, setFilterFreq] = useState<string>("");
  const [filterEntreprise, setFilterEntreprise] = useState<string>("");
  const [activeOnly, setActiveOnly] = useState(false);

  const confirm = useConfirm();

  async function reload() {
    try {
      const r = await authedFetch(
        "/api/v1/entreprises/tache-templates/all"
      );
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      setList((await r.json()) as TacheTemplate[]);
    } catch (e) {
      setError((e as Error).message);
    }
  }

  useEffect(() => {
    void reload();
  }, []);

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
        } à partir des modèles dus.`
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
    const ok = await confirm({
      title: `Supprimer le modèle « ${t.title} » ?`,
      description: `Modèle de « ${t.entreprise_name} ». Les tâches déjà créées ne sont pas supprimées.`,
      confirmLabel: "Supprimer",
      destructive: true
    });
    if (!ok) return;
    await authedFetch(`/api/v1/entreprises/tache-templates/${t.id}`, {
      method: "DELETE"
    });
    void reload();
  }

  // Filtrage côté client.
  const filtered = useMemo(() => {
    if (!list) return null;
    const q = search.trim().toLowerCase();
    return list.filter((t) => {
      if (activeOnly && !t.is_active) return false;
      if (filterStatus && t.default_status !== filterStatus) return false;
      if (filterEntreprise && String(t.entreprise_id) !== filterEntreprise)
        return false;
      if (filterFreq) {
        const preset = FREQ_PRESETS.find((p) => p.key === filterFreq);
        if (preset && preset.key !== "custom") {
          if (t.every_n !== preset.every_n || t.unit !== preset.unit)
            return false;
        }
      }
      if (!q) return true;
      return (
        t.title.toLowerCase().includes(q) ||
        t.entreprise_name.toLowerCase().includes(q) ||
        (t.description || "").toLowerCase().includes(q) ||
        (t.departement || "").toLowerCase().includes(q)
      );
    });
  }, [list, search, activeOnly, filterStatus, filterFreq, filterEntreprise]);

  return (
    <>
      <QGTopbar
        greeting={
          <>
            Tâches{" "}
            <span
              style={{
                color: "var(--qg-accent)",
                fontFamily: "var(--font-display, ui-sans-serif, system-ui, sans-serif)"
              }}
            >
              récurrentes
            </span>
          </>
        }
        subtitle="Modèles cross-entreprise · matérialisés automatiquement par le cron"
        rightSlot={
          <Link
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            href={"/entreprises/taches" as any}
            className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--qg-border)] bg-[var(--qg-bg-alt)] px-3 py-1.5 text-xs text-[var(--qg-text)] hover:bg-[var(--qg-bg)]"
          >
            ← Toutes les tâches
          </Link>
        }
      />

      <div className="px-5 py-6 lg:px-8">
        <PageDriveSection
          pageKey="page:entreprises:taches-recurrentes"
          pole="Gestion d'entreprises"
          label="Tâches récurrentes"
          route="/entreprises/taches/recurrentes"
        />
        {/* Toolbar : « Nouveau modèle » à gauche, « Matérialiser
            maintenant » poussé tout à droite. */}
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <button
            type="button"
            onClick={() => setShowCreate(true)}
            className="btn-accent inline-flex items-center text-xs"
          >
            <Plus className="mr-1.5 h-3.5 w-3.5" />
            Nouveau modèle
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
        </div>

        <FiltersBar
          search={search}
          setSearch={setSearch}
          filterStatus={filterStatus}
          setFilterStatus={setFilterStatus}
          filterFreq={filterFreq}
          setFilterFreq={setFilterFreq}
          filterEntreprise={filterEntreprise}
          setFilterEntreprise={setFilterEntreprise}
          activeOnly={activeOnly}
          setActiveOnly={setActiveOnly}
        />

        {error ? (
          <p className="mb-3 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
            {error}
          </p>
        ) : null}

        {runMsg ? (
          <p className="mb-4 rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-xs text-emerald-300">
            <CheckCircle2 className="mr-1.5 inline h-3.5 w-3.5" />
            {runMsg}
          </p>
        ) : null}

        {filtered === null ? (
          <p className="py-12 text-center text-sm text-white/40">Chargement…</p>
        ) : filtered.length === 0 ? (
          <div className="rounded-xl border border-brand-800 bg-brand-900/40 px-6 py-12 text-center">
            <Repeat className="mx-auto mb-3 h-8 w-8 text-white/30" />
            <p className="text-sm text-white/60">
              Aucun modèle pour ces filtres.
            </p>
          </div>
        ) : (
          <ul className="space-y-2">
            {filtered.map((t) => (
              <TemplateRow
                key={t.id}
                t={t}
                onToggle={() => toggleActive(t)}
                onDelete={() => remove(t)}
                onEdit={() => setEditing(t)}
              />
            ))}
          </ul>
        )}
      </div>

      {showCreate ? (
        <TemplateFormModal
          mode="create"
          onClose={() => setShowCreate(false)}
          onSaved={() => {
            setShowCreate(false);
            void reload();
          }}
        />
      ) : null}

      {editing ? (
        <TemplateFormModal
          mode="edit"
          existing={editing}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null);
            void reload();
          }}
        />
      ) : null}
    </>
  );
}

// ─── Filtres ───────────────────────────────────────────────────────
//
// Style harmonisé avec la barre de filtres du <TaskBoard> : même
// fond, même hauteur de pickers, même pattern « <Label> : <select> »
// avec « Tous » en première option. La barre de recherche reste la
// première — comportement identique aux task-boards depuis qu'on l'y
// a ajoutée.

function FiltersBar({
  search,
  setSearch,
  filterStatus,
  setFilterStatus,
  filterFreq,
  setFilterFreq,
  filterEntreprise,
  setFilterEntreprise,
  activeOnly,
  setActiveOnly
}: {
  search: string;
  setSearch: (v: string) => void;
  filterStatus: string;
  setFilterStatus: (v: string) => void;
  filterFreq: string;
  setFilterFreq: (v: string) => void;
  filterEntreprise: string;
  setFilterEntreprise: (v: string) => void;
  activeOnly: boolean;
  setActiveOnly: (v: boolean) => void;
}) {
  const { entreprises } = useEntreprisesLayout();
  return (
    <div className="mb-4 flex flex-wrap items-center gap-3 rounded-lg border border-brand-800 bg-brand-900/40 px-3 py-2">
      <SearchInput value={search} onChange={setSearch} />
      <FilterPicker
        label="Statut"
        value={filterStatus}
        onChange={setFilterStatus}
        options={TASK_STATUS_OPTIONS.map((s) => ({
          value: s.value,
          label: s.label
        }))}
      />
      <FilterPicker
        label="Fréquence"
        value={filterFreq}
        onChange={setFilterFreq}
        options={FREQ_PRESETS.filter((p) => p.key !== "custom").map((p) => ({
          value: p.key,
          label: p.label
        }))}
      />
      <FilterPicker
        label="Entreprise"
        value={filterEntreprise}
        onChange={setFilterEntreprise}
        options={entreprises.map((e) => ({
          value: String(e.id),
          label: e.name
        }))}
      />
      <label className="ml-auto flex cursor-pointer items-center gap-1.5 text-xs text-white/70">
        <input
          type="checkbox"
          checked={activeOnly}
          onChange={(e) => setActiveOnly(e.target.checked)}
          className="h-3.5 w-3.5 accent-accent-500"
        />
        Actifs seulement
      </label>
    </div>
  );
}

function SearchInput({
  value,
  onChange
}: {
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <label className="relative inline-flex items-center">
      <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-white/40" />
      <input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder="Rechercher…"
        className="w-56 rounded-md border border-brand-800 bg-brand-900 py-1 pl-8 pr-2 text-xs text-white placeholder:text-white/30 focus:border-accent-500 focus:outline-none"
      />
    </label>
  );
}

function FilterPicker({
  label,
  value,
  onChange,
  options
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  options: Array<{ value: string; label: string }>;
}) {
  return (
    <label className="inline-flex items-center gap-1.5 text-xs text-white/60">
      <span>{label}&nbsp;:</span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="rounded-md border border-brand-800 bg-brand-900 px-2 py-1 text-xs text-white focus:border-accent-500 focus:outline-none"
      >
        <option value="">Tous</option>
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </label>
  );
}

// ─── Liste ─────────────────────────────────────────────────────────

function TemplateRow({
  t,
  onToggle,
  onDelete,
  onEdit
}: {
  t: TacheTemplate;
  onToggle: () => void;
  onDelete: () => void;
  onEdit: () => void;
}) {
  const statusOpt = TASK_STATUS_OPTIONS.find(
    (s) => s.value === t.default_status
  );
  return (
    <li className="rounded-xl border border-brand-800 bg-brand-900 p-4">
      <div className="flex items-start gap-3">
        <span className="mt-0.5 flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-lg bg-violet-500/15 text-violet-300">
          <Repeat className="h-4 w-4" />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="truncate text-sm font-bold text-white">
              {t.title}
            </h3>
            <span className="rounded-full border border-white/10 bg-brand-950 px-1.5 py-0.5 text-[10px] text-white/70">
              {t.entreprise_name}
            </span>
            {statusOpt ? (
              <span
                className={`rounded-full px-1.5 py-0.5 text-[10px] font-semibold ${statusOpt.pill}`}
              >
                {statusOpt.label}
              </span>
            ) : null}
            {!t.is_active ? (
              <span className="rounded-full border border-white/15 px-1.5 py-0.5 text-[10px] uppercase text-white/50">
                Désactivé
              </span>
            ) : null}
          </div>
          <p className="mt-1 text-[11px] text-white/50">
            {formatFreq(t.every_n, t.unit)}
            {t.departement ? ` · ${t.departement}` : ""}
            {" · prochain "}
            <span className="text-white/70">{t.next_due}</span>
            {" · lead "}
            <span>{t.lead_days}j</span>
            {t.impact && t.confidence && t.effort
              ? ` · ICE ${t.impact}/${t.confidence}/${t.effort}`
              : ""}
          </p>
          {t.description ? (
            <p className="mt-1 line-clamp-2 text-xs text-white/60">
              {t.description}
            </p>
          ) : null}
          <p className="mt-1.5 text-[10px] text-white/40">
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
            onClick={onEdit}
            className="rounded-lg border border-white/15 bg-brand-950 p-1.5 text-white/60 hover:text-white"
            title="Modifier"
            aria-label="Modifier"
          >
            <Pencil className="h-3.5 w-3.5" />
          </button>
          <button
            type="button"
            onClick={onToggle}
            className="inline-flex items-center gap-1 rounded-lg border border-white/15 bg-brand-950 px-2 py-1 text-[10px] text-white/70 hover:text-white"
            title={t.is_active ? "Désactiver" : "Activer"}
          >
            {t.is_active ? (
              <>
                <Pause className="h-3 w-3" />
                Pause
              </>
            ) : (
              <>
                <Play className="h-3 w-3" />
                Activer
              </>
            )}
          </button>
          <button
            type="button"
            onClick={onDelete}
            className="rounded-lg border border-white/15 bg-brand-950 p-1.5 text-white/40 hover:border-rose-400/50 hover:text-rose-300"
            title="Supprimer"
          >
            <Trash2 className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>
    </li>
  );
}

// ─── Form Modal (create + edit) ────────────────────────────────────

type FormState = {
  // Création multi-entreprise. En édition, un seul id pré-rempli.
  entrepriseIds: number[];
  title: string;
  description: string;
  departement: string;
  default_status: TaskStatusValue;
  freqPreset: string;
  every_n: string;
  unit: string;
  lead_days: string;
  next_due: string;
  impact: string;
  confidence: string;
  effort: string;
  immeuble_ids: number[];
};

function TemplateFormModal({
  mode,
  existing,
  onClose,
  onSaved
}: {
  mode: "create" | "edit";
  existing?: TacheTemplate;
  onClose: () => void;
  onSaved: () => void;
}) {
  const { entreprises } = useEntreprisesLayout();
  const [form, setForm] = useState<FormState>(() => {
    if (existing) {
      // Match preset si possible.
      const preset =
        FREQ_PRESETS.find(
          (p) =>
            p.key !== "custom" &&
            p.every_n === existing.every_n &&
            p.unit === existing.unit
        )?.key || "custom";
      return {
        entrepriseIds: [existing.entreprise_id],
        title: existing.title,
        description: existing.description || "",
        departement: existing.departement || "",
        default_status: (existing.default_status || "todo") as TaskStatusValue,
        freqPreset: preset,
        every_n: String(existing.every_n),
        unit: existing.unit,
        lead_days: String(existing.lead_days),
        next_due: existing.next_due,
        impact: existing.impact ? String(existing.impact) : "",
        confidence: existing.confidence ? String(existing.confidence) : "",
        effort: existing.effort ? String(existing.effort) : "",
        immeuble_ids: existing.immeuble_ids || []
      };
    }
    return {
      entrepriseIds: [],
      title: "",
      description: "",
      departement: "",
      default_status: "todo" as TaskStatusValue,
      freqPreset: "monthly",
      every_n: "1",
      unit: "mois",
      lead_days: "7",
      next_due: todayPlusDays(7),
      impact: "",
      confidence: "",
      effort: "",
      immeuble_ids: []
    };
  });
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  // Catalogue d'immeubles : filtré par entreprise(s) sélectionnée(s).
  // En création, agrégé sur les N entreprises ; en édition, sur la seule.
  const [immeubles, setImmeubles] = useState<ImmeubleMini[]>([]);
  useEffect(() => {
    let cancelled = false;
    async function load() {
      const ids = form.entrepriseIds;
      if (ids.length === 0) {
        setImmeubles([]);
        return;
      }
      try {
        const results = await Promise.all(
          ids.map((eid) =>
            authedFetch(`/api/v1/imm/immeubles?entreprise_id=${eid}`).then(
              (r) => (r.ok ? r.json() : [])
            )
          )
        );
        if (cancelled) return;
        const merged = new Map<number, ImmeubleMini>();
        for (const list of results) {
          for (const i of list as ImmeubleMini[]) {
            if (!merged.has(i.id)) merged.set(i.id, i);
          }
        }
        setImmeubles(Array.from(merged.values()));
      } catch {
        /* silent */
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [form.entrepriseIds.join(",")]);

  function setPreset(presetKey: string) {
    const p = FREQ_PRESETS.find((x) => x.key === presetKey);
    if (!p) return;
    if (presetKey === "custom") {
      setForm((f) => ({ ...f, freqPreset: presetKey }));
    } else {
      setForm((f) => ({
        ...f,
        freqPreset: presetKey,
        every_n: String(p.every_n),
        unit: p.unit
      }));
    }
  }

  function toggleEntreprise(id: number) {
    setForm((f) => {
      const has = f.entrepriseIds.includes(id);
      return {
        ...f,
        entrepriseIds: has
          ? f.entrepriseIds.filter((x) => x !== id)
          : [...f.entrepriseIds, id]
      };
    });
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (form.entrepriseIds.length === 0) {
      setErr("Choisis au moins une entreprise.");
      return;
    }
    if (!form.title.trim()) {
      setErr("Le titre est obligatoire.");
      return;
    }
    // ICE optionnel : on accepte vide. Si l'utilisateur a saisi
    // une valeur partielle (ex. impact mais pas effort), on
    // refuse — soit les 3 sont remplis, soit aucun.
    const iceFilled = [form.impact, form.confidence, form.effort].filter(
      (v) => v.trim() !== ""
    );
    if (iceFilled.length > 0 && iceFilled.length < 3) {
      setErr(
        "Pour le score ICE, remplis les 3 champs (impact, confiance, effort) ou laisse-les tous vides."
      );
      return;
    }
    if (iceFilled.length === 3) {
      const ice = [
        Number(form.impact),
        Number(form.confidence),
        Number(form.effort)
      ];
      if (ice.some((v) => !Number.isFinite(v) || v < 1 || v > 10)) {
        setErr("Le score ICE doit être entre 1 et 10 pour chacun des 3 champs.");
        return;
      }
    }
    const every_n = Number(form.every_n);
    if (!Number.isFinite(every_n) || every_n < 1) {
      setErr("La fréquence doit être un nombre ≥ 1.");
      return;
    }
    const lead_days = Number(form.lead_days);
    if (!Number.isFinite(lead_days) || lead_days < 0) {
      setErr("Le délai (lead) doit être un nombre ≥ 0.");
      return;
    }
    if (!form.next_due) {
      setErr("La 1ère date d'échéance est obligatoire.");
      return;
    }

    const payloadBase = {
      title: form.title.trim(),
      description: form.description.trim() || null,
      departement: form.departement.trim() || null,
      default_status: form.default_status,
      every_n,
      unit: form.unit,
      lead_days,
      next_due: form.next_due,
      impact: iceFilled.length === 3 ? Number(form.impact) : null,
      confidence: iceFilled.length === 3 ? Number(form.confidence) : null,
      effort: iceFilled.length === 3 ? Number(form.effort) : null,
      immeuble_ids: form.immeuble_ids,
      is_active: true
    };

    setSaving(true);
    setErr(null);
    try {
      if (mode === "edit" && existing) {
        const res = await authedFetch(
          `/api/v1/entreprises/tache-templates/${existing.id}`,
          { method: "PATCH", body: JSON.stringify(payloadBase) }
        );
        if (!res.ok) {
          const t = await res.text();
          throw new Error(t.slice(0, 240) || `HTTP ${res.status}`);
        }
      } else {
        const res = await authedFetch(
          "/api/v1/entreprises/tache-templates/bulk",
          {
            method: "POST",
            body: JSON.stringify({
              entreprise_ids: form.entrepriseIds,
              ...payloadBase
            })
          }
        );
        if (!res.ok) {
          const t = await res.text();
          throw new Error(t.slice(0, 240) || `HTTP ${res.status}`);
        }
      }
      onSaved();
    } catch (e2) {
      setErr((e2 as Error).message);
    } finally {
      setSaving(false);
    }
  }

  const isCustom = form.freqPreset === "custom";

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/60 px-2 py-4 sm:items-center">
      <div
        className="flex max-h-[calc(100vh-2rem)] w-full max-w-2xl flex-col overflow-hidden rounded-2xl border border-brand-800 bg-brand-900 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex flex-shrink-0 items-center justify-between border-b border-brand-800 px-5 py-4">
          <h2 className="text-base font-bold text-white">
            {mode === "edit"
              ? "Modifier le modèle récurrent"
              : "Nouveau modèle récurrent"}
          </h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="Fermer"
            className="rounded-md p-1 text-white/60 hover:bg-white/5 hover:text-white"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <form
          id="template-form"
          onSubmit={submit}
          className="flex-1 overflow-y-auto px-5 py-4"
        >
          <div className="grid gap-4">
            {/* Multi-select entreprise (création) ou disabled (édition) */}
            <div>
              <label className="label">
                Entreprise{mode === "create" ? "(s)" : ""}{" "}
                <span className="text-rose-400">*</span>
              </label>
              {mode === "edit" ? (
                <p className="rounded-lg border border-white/10 bg-brand-950 px-3 py-2 text-xs text-white/70">
                  {existing?.entreprise_name || "—"}
                </p>
              ) : (
                <div className="max-h-40 overflow-y-auto rounded-lg border border-brand-800 bg-brand-950 p-2">
                  {entreprises.length === 0 ? (
                    <p className="text-xs text-white/40">
                      Aucune entreprise.
                    </p>
                  ) : (
                    <ul className="space-y-1">
                      {entreprises.map((e) => (
                        <li key={e.id}>
                          <label className="flex cursor-pointer items-center gap-2 rounded px-2 py-1 hover:bg-brand-900">
                            <input
                              type="checkbox"
                              checked={form.entrepriseIds.includes(e.id)}
                              onChange={() => toggleEntreprise(e.id)}
                              className="h-3.5 w-3.5 accent-accent-500"
                            />
                            <span className="text-xs text-white/80">
                              {e.name}
                              {!e.is_active ? (
                                <span className="ml-1 text-white/40">
                                  (inactive)
                                </span>
                              ) : null}
                            </span>
                          </label>
                        </li>
                      ))}
                    </ul>
                  )}
                  <p className="mt-1 text-[10px] text-white/40">
                    {form.entrepriseIds.length} sélectionnée
                    {form.entrepriseIds.length > 1 ? "s" : ""}
                  </p>
                </div>
              )}
            </div>

            {/* Titre */}
            <div>
              <label className="label">
                Titre <span className="text-rose-400">*</span>
              </label>
              <input
                required
                value={form.title}
                onChange={(e) => setForm({ ...form, title: e.target.value })}
                className="input"
                placeholder="ex. Faire la TPS/TVQ trimestrielle"
              />
            </div>

            {/* Statut + Lead days */}
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="label">
                  Statut au démarrage{" "}
                  <span className="text-rose-400">*</span>
                </label>
                <select
                  required
                  value={form.default_status}
                  onChange={(e) =>
                    setForm({
                      ...form,
                      default_status: e.target.value as TaskStatusValue
                    })
                  }
                  className="input"
                >
                  {TASK_STATUS_OPTIONS.map((s) => (
                    <option key={s.value} value={s.value}>
                      {s.label}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className="label">
                  Délai avant échéance (jours){" "}
                  <span className="text-rose-400">*</span>
                </label>
                <input
                  required
                  type="number"
                  min={0}
                  value={form.lead_days}
                  onChange={(e) =>
                    setForm({ ...form, lead_days: e.target.value })
                  }
                  className="input"
                />
                <p className="mt-1 text-[10px] text-white/40">
                  Ex. 7 = la tâche apparaît 7 jours avant l&apos;échéance.
                </p>
              </div>
            </div>

            {/* Récurrence */}
            <div>
              <label className="label">
                Récurrence <span className="text-rose-400">*</span>
              </label>
              <select
                required
                value={form.freqPreset}
                onChange={(e) => setPreset(e.target.value)}
                className="input"
              >
                {FREQ_PRESETS.map((p) => (
                  <option key={p.key} value={p.key}>
                    {p.label}
                  </option>
                ))}
              </select>
              {isCustom ? (
                <div className="mt-2 grid grid-cols-2 gap-2">
                  <div>
                    <label className="label text-[10px]">Tous les</label>
                    <input
                      type="number"
                      min={1}
                      value={form.every_n}
                      onChange={(e) =>
                        setForm({ ...form, every_n: e.target.value })
                      }
                      className="input"
                    />
                  </div>
                  <div>
                    <label className="label text-[10px]">Unité</label>
                    <select
                      value={form.unit}
                      onChange={(e) =>
                        setForm({ ...form, unit: e.target.value })
                      }
                      className="input"
                    >
                      {FREQ_UNITS.map((u) => (
                        <option key={u.value} value={u.value}>
                          {u.label}
                        </option>
                      ))}
                    </select>
                  </div>
                </div>
              ) : null}
            </div>

            {/* 1ère échéance */}
            <div>
              <label className="label">
                1ère date d&apos;échéance{" "}
                <span className="text-rose-400">*</span>
              </label>
              <input
                required
                type="date"
                value={form.next_due}
                onChange={(e) =>
                  setForm({ ...form, next_due: e.target.value })
                }
                className="input"
              />
              <p className="mt-1 text-[10px] text-white/40">
                Les récurrences suivantes se calculent à partir de cette date.
              </p>
            </div>

            {/* ICE */}
            <div>
              <label className="label">
                Score ICE
                <span className="ml-1 text-[10px] font-normal text-white/40">
                  (optionnel)
                </span>
              </label>
              <div className="grid grid-cols-3 gap-2">
                <ICEInput
                  label="Impact"
                  value={form.impact}
                  onChange={(v) => setForm({ ...form, impact: v })}
                />
                <ICEInput
                  label="Confiance"
                  value={form.confidence}
                  onChange={(v) => setForm({ ...form, confidence: v })}
                />
                <ICEInput
                  label="Effort"
                  value={form.effort}
                  onChange={(v) => setForm({ ...form, effort: v })}
                />
              </div>
              <p className="mt-1 text-[10px] text-white/40">
                Soit les 3 champs remplis (1-10) — la tâche aura un score
                automatique — soit les 3 vides : tâche sans score.
              </p>
            </div>

            <div className="my-2 border-t border-brand-800 pt-2">
              <p className="text-[10px] uppercase tracking-wider text-white/40">
                Optionnel
              </p>
            </div>

            {/* Immeubles */}
            <div>
              <label className="label">Immeubles (multi)</label>
              {form.entrepriseIds.length === 0 ? (
                <p className="rounded-lg border border-dashed border-brand-800 px-3 py-2 text-xs text-white/40">
                  Sélectionne au moins une entreprise pour voir ses immeubles.
                </p>
              ) : (
                <ImmeublePicker
                  immeubles={immeubles}
                  values={form.immeuble_ids}
                  onChange={(ids) =>
                    setForm({ ...form, immeuble_ids: ids })
                  }
                  variant="modal"
                />
              )}
            </div>

            {/* Département */}
            <div>
              <label className="label">Département</label>
              <input
                value={form.departement}
                onChange={(e) =>
                  setForm({ ...form, departement: e.target.value })
                }
                className="input"
                placeholder="ex. Compta, RH, Marketing"
              />
            </div>

            {/* Notes */}
            <div>
              <label className="label">Notes</label>
              <textarea
                value={form.description}
                onChange={(e) =>
                  setForm({ ...form, description: e.target.value })
                }
                rows={3}
                className="input"
                placeholder="Comment exécuter la tâche, liens utiles…"
              />
            </div>

            {err ? (
              <p className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
                {err}
              </p>
            ) : null}
          </div>
        </form>

        <div className="flex flex-shrink-0 items-center justify-end gap-2 border-t border-brand-800 px-5 py-3">
          <button type="button" onClick={onClose} className="btn-secondary text-xs">
            Annuler
          </button>
          <button
            type="submit"
            form="template-form"
            disabled={saving}
            className="btn-accent text-xs disabled:opacity-60"
          >
            {saving ? (
              <>
                <Loader2 className="mr-1.5 inline h-3.5 w-3.5 animate-spin" />
                Enregistrement…
              </>
            ) : mode === "edit" ? (
              "Enregistrer"
            ) : (
              `Créer (${form.entrepriseIds.length || 0} entreprise${
                form.entrepriseIds.length > 1 ? "s" : ""
              })`
            )}
          </button>
        </div>
      </div>
    </div>
  );
}

function ICEInput({
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
      <label className="block text-[10px] font-medium text-white/70">
        {label}
      </label>
      <input
        type="number"
        min={1}
        max={10}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder="1-10"
        className="input"
      />
    </div>
  );
}
