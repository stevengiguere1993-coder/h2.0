"use client";

import { useCallback, useEffect, useState } from "react";
import {
  Building2,
  Calculator,
  CheckCircle2,
  Landmark,
  Loader2,
  Plus,
  Save,
  SlidersHorizontal,
  Trash2,
  Wallet
} from "lucide-react";

import { authedFetch } from "@/lib/auth";

/**
 * Composants des sections de la page « Calculateur » (Paramètres
 * Prospection → analyse financière). Chaque section édite un groupe de
 * la table backend ``analysis_defaults`` via les endpoints
 * ``/api/v1/prospection/analysis-defaults`` (+ ``frais-custom`` pour la
 * liste dynamique de frais de démarrage).
 *
 * La logique d'édition d'un défaut scalaire (input numérique borné +
 * unité auto + bouton Enregistrer par ligne + toggle « finançable par
 * défaut ») est reprise de ``analysis-defaults-modal.tsx`` et adaptée
 * en pleine page.
 */

// ── Types (miroir du schéma backend AnalysisDefaultRead) ───────────

export type AnalysisDefault = {
  id: number;
  key: string;
  value_float: number | null;
  value_json: unknown;
  label_fr: string;
  description_fr: string | null;
  min_value: number | null;
  max_value: number | null;
  step: number;
  group: string | null;
  financable_par_defaut: boolean | null;
};

type FraisCustomItem = {
  id: string;
  label_fr: string;
  type_montant: "fixe" | "pct_prix_achat" | "pct_financement";
  valeur: number;
  financable_par_defaut: boolean;
};

const API = "/api/v1/prospection/analysis-defaults";

// Clé spéciale : la liste dynamique de frais personnalisés est stockée
// dans cette ligne (groupe mdf_frais) mais éditée via les routes
// frais-custom — on la masque du rendu scalaire pour ne pas afficher
// un input numérique cassé sur sa value_json (liste).
const FRAIS_CUSTOM_KEY = "frais_mdf_custom";

// ── Helpers d'unité / format ───────────────────────────────────────

/**
 * Déduit l'unité à afficher à droite de l'input d'un défaut scalaire.
 * Approche pilotée par le label_fr (fiable) avec repli sur la clé/step :
 *   - « (années) » dans le label → "ans"
 *   - label finit par « (%) » ou clé en *_pct → "%"
 *   - « ratio » / LTV / RCD dans le label → "" (décimal pur)
 *   - clé frais_* ou step >= 1 (montant) → "$"
 *   - sinon "" (pas d'unité native, le label clarifie déjà).
 */
function unitFor(def: AnalysisDefault): string {
  const label = def.label_fr.toLowerCase();
  if (label.includes("(années)") || label.includes("(annees)")) return "ans";
  if (def.label_fr.trim().endsWith("(%)") || def.key.endsWith("_pct")) {
    return "%";
  }
  if (
    label.includes("ratio") ||
    label.includes("ltv") ||
    label.includes("rcd")
  ) {
    return "";
  }
  if (def.key.startsWith("frais_") || def.key.startsWith("seuil_")) {
    return def.key.startsWith("seuil_") && label.includes("log") ? "log" : "$";
  }
  if (def.step >= 1) return "$";
  return "";
}

const TYPE_MONTANT_LABEL: Record<FraisCustomItem["type_montant"], string> = {
  fixe: "Montant fixe ($)",
  pct_prix_achat: "% du prix d'achat",
  pct_financement: "% du financement"
};

// ── Hook : charge les défauts d'un groupe ──────────────────────────

function useGroupDefaults(group: string) {
  const [defaults, setDefaults] = useState<AnalysisDefault[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const r = await authedFetch(
        `${API}?group=${encodeURIComponent(group)}`
      );
      if (r.status === 403) {
        throw new Error("Accès réservé aux administrateurs.");
      }
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const j = (await r.json()) as AnalysisDefault[];
      setDefaults(j);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, [group]);

  useEffect(() => {
    void load();
  }, [load]);

  return { defaults, setDefaults, loading, error } as const;
}

// ── Éditeur d'un défaut scalaire (1 ligne) ─────────────────────────

function ScalarDefaultRow({
  def,
  onUpdated,
  showFinancable
}: {
  def: AnalysisDefault;
  onUpdated: (next: AnalysisDefault) => void;
  showFinancable?: boolean;
}) {
  const [draft, setDraft] = useState(
    def.value_float != null ? String(def.value_float) : ""
  );
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Resync le brouillon si la valeur amont change (rechargement).
  useEffect(() => {
    setDraft(def.value_float != null ? String(def.value_float) : "");
  }, [def.value_float]);

  const draftNum = Number(draft);
  const dirty =
    Number.isFinite(draftNum) &&
    Math.abs(draftNum - (def.value_float ?? 0)) > 1e-9;
  const unit = unitFor(def);

  async function save() {
    if (!Number.isFinite(draftNum)) {
      setError("Valeur invalide.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const r = await authedFetch(`${API}/${encodeURIComponent(def.key)}`, {
        method: "PATCH",
        body: JSON.stringify({ value_float: draftNum })
      });
      if (!r.ok) {
        const t = await r.text().catch(() => "");
        throw new Error(t.slice(0, 200) || `HTTP ${r.status}`);
      }
      const updated = (await r.json()) as AnalysisDefault;
      onUpdated(updated);
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  }

  async function toggleFinancable(next: boolean) {
    // Optimistic — rollback sur erreur.
    onUpdated({ ...def, financable_par_defaut: next });
    try {
      const r = await authedFetch(`${API}/${encodeURIComponent(def.key)}`, {
        method: "PATCH",
        body: JSON.stringify({ financable_par_defaut: next })
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const updated = (await r.json()) as AnalysisDefault;
      onUpdated(updated);
    } catch (e) {
      onUpdated({ ...def, financable_par_defaut: !next });
      setError((e as Error).message);
    }
  }

  return (
    <div className="rounded-lg border border-brand-800 bg-brand-950/60 px-3 py-2.5">
      <label className="block text-xs font-semibold text-white/80">
        {def.label_fr}
      </label>
      {def.description_fr ? (
        <p className="mt-0.5 text-[10px] leading-snug text-white/50">
          {def.description_fr}
        </p>
      ) : null}
      <div className="mt-2 flex items-center gap-2">
        <input
          type="number"
          step={def.step}
          min={def.min_value ?? undefined}
          max={def.max_value ?? undefined}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          className="input flex-1 py-1.5 font-mono text-xs"
          disabled={saving}
        />
        {unit ? (
          <span className="w-7 shrink-0 text-[10px] text-white/40">{unit}</span>
        ) : (
          <span className="w-7 shrink-0" />
        )}
        <button
          type="button"
          onClick={() => void save()}
          disabled={!dirty || saving}
          className="inline-flex items-center gap-1 rounded-md border border-emerald-500/40 bg-emerald-500/15 px-2.5 py-1.5 text-[11px] font-semibold text-emerald-300 transition hover:bg-emerald-500/25 disabled:cursor-not-allowed disabled:opacity-40"
        >
          {saving ? (
            <Loader2 className="h-3 w-3 animate-spin" />
          ) : (
            <Save className="h-3 w-3" />
          )}
          Enregistrer
        </button>
      </div>
      {showFinancable ? (
        <label className="mt-2 flex cursor-pointer items-center gap-2 text-[10px] text-white/70">
          <input
            type="checkbox"
            checked={!!def.financable_par_defaut}
            onChange={(e) => void toggleFinancable(e.target.checked)}
            className="h-3.5 w-3.5 cursor-pointer accent-amber-400"
          />
          <span>
            Finançable par défaut
            <span className="ml-1 text-white/40">
              (case pré-cochée sur les nouvelles fiches)
            </span>
          </span>
        </label>
      ) : null}
      {saved ? (
        <p className="mt-1 flex items-center gap-1 text-[10px] text-emerald-400">
          <CheckCircle2 className="h-3 w-3" /> Enregistré.
        </p>
      ) : null}
      {error ? (
        <p className="mt-1 text-[10px] text-rose-400">{error}</p>
      ) : null}
    </div>
  );
}

// ── Coquille de section (tuile-icône + titre + sous-titre) ──────────

function SectionShell({
  icon: Icon,
  iconClass,
  title,
  subtitle,
  loading,
  error,
  highlight,
  children
}: {
  icon: React.ComponentType<{ className?: string }>;
  iconClass: string;
  title: string;
  subtitle: string;
  loading?: boolean;
  error?: string | null;
  highlight?: boolean;
  children?: React.ReactNode;
}) {
  return (
    <section
      className={`rounded-2xl border p-5 ${
        highlight
          ? "border-emerald-500/40 bg-emerald-500/[0.04]"
          : "border-brand-800 bg-brand-900"
      }`}
    >
      <header className="flex items-center gap-3">
        <span
          className={`flex h-10 w-10 items-center justify-center rounded-xl ${iconClass}`}
        >
          <Icon className="h-5 w-5" />
        </span>
        <div>
          <h2 className="text-base font-bold text-white">{title}</h2>
          <p className="mt-0.5 text-xs text-white/60">{subtitle}</p>
        </div>
      </header>

      {loading ? (
        <div className="mt-4 flex items-center gap-2 text-xs text-white/60">
          <Loader2 className="h-3.5 w-3.5 animate-spin" /> Chargement…
        </div>
      ) : null}
      {error ? (
        <p className="mt-3 rounded-md border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
          {error}
        </p>
      ) : null}
      {!loading && !error ? <div className="mt-4">{children}</div> : null}
    </section>
  );
}

// ── 1. Dépenses normalisées (SCHL) ─────────────────────────────────

export function DepensesNormaliseesSection() {
  const { defaults, setDefaults, loading, error } =
    useGroupDefaults("depenses_normalisees");

  function patch(next: AnalysisDefault) {
    setDefaults((prev) => prev.map((d) => (d.key === next.key ? next : d)));
  }

  return (
    <SectionShell
      icon={Calculator}
      iconClass="bg-emerald-500/15 text-emerald-400"
      title="Dépenses normalisées (SCHL)"
      subtitle="Barème SCHL : conciergerie, entretien, gestion, wifi/internet, thermopompe, seuil 12 log, taux d'inoccupation."
      loading={loading}
      error={error}
      highlight
    >
      <p className="mb-3 rounded-md border border-emerald-500/30 bg-emerald-500/[0.06] px-3 py-2 text-[11px] text-emerald-200/90">
        Ajuste ces valeurs quand la SCHL met à jour ses normes de dépenses
        normalisées — elles alimentent directement le calcul de la valeur
        économique des refinancements.
      </p>
      <div className="grid gap-2.5 sm:grid-cols-2">
        {defaults.map((def) => (
          <ScalarDefaultRow key={def.key} def={def} onUpdated={patch} />
        ))}
      </div>
    </SectionShell>
  );
}

// ── 2. Scénarios de financement (4 sous-cartes de 3 champs) ────────

const SCENARIOS: { prefix: string; label: string }[] = [
  { prefix: "scenario_achat_", label: "Achat (conventionnel)" },
  { prefix: "scenario_schl_std_", label: "SCHL standard" },
  { prefix: "scenario_aph50_", label: "APH 50 pts" },
  { prefix: "scenario_aph100_", label: "APH 100 pts" }
];

export function ScenariosFinancementSection() {
  const { defaults, setDefaults, loading, error } =
    useGroupDefaults("scenarios_financement");

  function patch(next: AnalysisDefault) {
    setDefaults((prev) => prev.map((d) => (d.key === next.key ? next : d)));
  }

  // Regroupe par préfixe de scénario ; tout reste (clé hors préfixes
  // connus) est rendu dans une sous-carte « Autres » pour ne rien
  // perdre si le backend ajoute un champ.
  const known = new Set<string>();
  const groups = SCENARIOS.map((sc) => {
    const items = defaults.filter((d) => d.key.startsWith(sc.prefix));
    items.forEach((d) => known.add(d.key));
    return { ...sc, items };
  });
  const others = defaults.filter((d) => !known.has(d.key));

  return (
    <SectionShell
      icon={Building2}
      iconClass="bg-sky-500/15 text-sky-400"
      title="Scénarios de financement"
      subtitle="LTV / amortissement / RCD des 4 scénarios (Achat, SCHL std, APH 50, APH 100)."
      loading={loading}
      error={error}
    >
      <div className="grid gap-3 sm:grid-cols-2">
        {groups.map((g) =>
          g.items.length > 0 ? (
            <div
              key={g.prefix}
              className="rounded-xl border border-brand-800 bg-brand-950/40 p-3"
            >
              <h3 className="mb-2 text-xs font-bold uppercase tracking-wide text-sky-300">
                {g.label}
              </h3>
              <div className="space-y-2">
                {g.items.map((def) => (
                  <ScalarDefaultRow key={def.key} def={def} onUpdated={patch} />
                ))}
              </div>
            </div>
          ) : null
        )}
        {others.length > 0 ? (
          <div className="rounded-xl border border-brand-800 bg-brand-950/40 p-3">
            <h3 className="mb-2 text-xs font-bold uppercase tracking-wide text-white/50">
              Autres
            </h3>
            <div className="space-y-2">
              {others.map((def) => (
                <ScalarDefaultRow key={def.key} def={def} onUpdated={patch} />
              ))}
            </div>
          </div>
        ) : null}
      </div>
    </SectionShell>
  );
}

// ── 3. Barèmes fiscaux (scalaire + paliers taxes de bienvenue) ─────

type TaxTier = { seuil: number | null; taux_pct: number };

function TaxesBienvenueEditor({
  def,
  onUpdated
}: {
  def: AnalysisDefault;
  onUpdated: (next: AnalysisDefault) => void;
}) {
  const initial: TaxTier[] = Array.isArray(def.value_json)
    ? (def.value_json as TaxTier[])
    : [];
  const [tiers, setTiers] = useState<TaxTier[]>(initial);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (Array.isArray(def.value_json)) {
      setTiers(def.value_json as TaxTier[]);
    }
  }, [def.value_json]);

  function setTier(i: number, patch: Partial<TaxTier>) {
    setTiers((prev) =>
      prev.map((t, idx) => (idx === i ? { ...t, ...patch } : t))
    );
  }

  async function save() {
    setSaving(true);
    setError(null);
    try {
      const r = await authedFetch(`${API}/${encodeURIComponent(def.key)}`, {
        method: "PATCH",
        body: JSON.stringify({ value_json: tiers })
      });
      if (!r.ok) {
        const t = await r.text().catch(() => "");
        throw new Error(t.slice(0, 200) || `HTTP ${r.status}`);
      }
      const updated = (await r.json()) as AnalysisDefault;
      onUpdated(updated);
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="rounded-lg border border-brand-800 bg-brand-950/60 px-3 py-2.5">
      <p className="text-xs font-semibold text-white/80">{def.label_fr}</p>
      {def.description_fr ? (
        <p className="mt-0.5 text-[10px] leading-snug text-white/50">
          {def.description_fr}
        </p>
      ) : null}
      <div className="mt-3 space-y-2">
        <div className="grid grid-cols-[1fr_1fr] gap-2 text-[10px] font-semibold uppercase tracking-wide text-white/40">
          <span>Seuil ($) — vide = palier ouvert</span>
          <span>Taux (%)</span>
        </div>
        {tiers.map((t, i) => (
          <div key={i} className="grid grid-cols-[1fr_1fr] gap-2">
            <input
              type="number"
              step={100}
              min={0}
              value={t.seuil ?? ""}
              placeholder="∞ (au-dessus)"
              onChange={(e) =>
                setTier(i, {
                  seuil: e.target.value === "" ? null : Number(e.target.value)
                })
              }
              className="input py-1.5 font-mono text-xs"
            />
            <input
              type="number"
              step={0.1}
              min={0}
              value={t.taux_pct}
              onChange={(e) =>
                setTier(i, { taux_pct: Number(e.target.value) })
              }
              className="input py-1.5 font-mono text-xs"
            />
          </div>
        ))}
      </div>
      <div className="mt-3 flex items-center gap-3">
        <button
          type="button"
          onClick={() => void save()}
          disabled={saving}
          className="inline-flex items-center gap-1 rounded-md border border-emerald-500/40 bg-emerald-500/15 px-2.5 py-1.5 text-[11px] font-semibold text-emerald-300 transition hover:bg-emerald-500/25 disabled:opacity-40"
        >
          {saving ? (
            <Loader2 className="h-3 w-3 animate-spin" />
          ) : (
            <Save className="h-3 w-3" />
          )}
          Enregistrer les paliers
        </button>
        {saved ? (
          <span className="flex items-center gap-1 text-[10px] text-emerald-400">
            <CheckCircle2 className="h-3 w-3" /> Enregistré.
          </span>
        ) : null}
      </div>
      {error ? (
        <p className="mt-1 text-[10px] text-rose-400">{error}</p>
      ) : null}
    </div>
  );
}

export function BaremesFiscauxSection() {
  const { defaults, setDefaults, loading, error } =
    useGroupDefaults("baremes_fiscaux");

  function patch(next: AnalysisDefault) {
    setDefaults((prev) => prev.map((d) => (d.key === next.key ? next : d)));
  }

  const scalars = defaults.filter((d) => d.value_float != null);
  const taxes = defaults.find((d) => d.key === "taxes_bienvenue_mtl");

  return (
    <SectionShell
      icon={Landmark}
      iconClass="bg-violet-500/15 text-violet-400"
      title="Barèmes fiscaux"
      subtitle="Ratio d'abordabilité APH + paliers progressifs des taxes de bienvenue (Montréal)."
      loading={loading}
      error={error}
    >
      <div className="space-y-3">
        {scalars.map((def) => (
          <ScalarDefaultRow key={def.key} def={def} onUpdated={patch} />
        ))}
        {taxes ? (
          <TaxesBienvenueEditor def={taxes} onUpdated={patch} />
        ) : null}
      </div>
    </SectionShell>
  );
}

// ── 4. Valeurs par défaut des analyses (inputs_manuels) ────────────

export function InputsManuelsSection() {
  const { defaults, setDefaults, loading, error } =
    useGroupDefaults("inputs_manuels");

  function patch(next: AnalysisDefault) {
    setDefaults((prev) => prev.map((d) => (d.key === next.key ? next : d)));
  }

  return (
    <SectionShell
      icon={SlidersHorizontal}
      iconClass="bg-amber-500/15 text-amber-400"
      title="Valeurs par défaut des analyses"
      subtitle="Taux refi, % MDF prêteur B, taux prêteur B, TGA, durée projet, taux d'inoccupation, etc."
      loading={loading}
      error={error}
    >
      <div className="grid gap-2.5 sm:grid-cols-2">
        {defaults.map((def) => (
          <ScalarDefaultRow key={def.key} def={def} onUpdated={patch} />
        ))}
      </div>
    </SectionShell>
  );
}

// ── 5. Frais de démarrage (MDF) + liste dynamique ──────────────────

function FraisCustomList() {
  const [items, setItems] = useState<FraisCustomItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [flash, setFlash] = useState<string | null>(null);

  // Brouillon du nouveau frais.
  const [form, setForm] = useState<{
    label_fr: string;
    type_montant: FraisCustomItem["type_montant"];
    valeur: string;
    financable_par_defaut: boolean;
  }>({
    label_fr: "",
    type_montant: "fixe",
    valeur: "",
    financable_par_defaut: false
  });

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const r = await authedFetch(`${API}/frais-custom`);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      setItems((await r.json()) as FraisCustomItem[]);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  function notify(msg: string) {
    setFlash(msg);
    setTimeout(() => setFlash(null), 2200);
  }

  async function add() {
    const valeurNum = Number(form.valeur);
    if (!form.label_fr.trim() || !Number.isFinite(valeurNum)) {
      setError("Nom et valeur requis.");
      return;
    }
    setAdding(true);
    setError(null);
    try {
      const r = await authedFetch(`${API}/frais-custom`, {
        method: "POST",
        body: JSON.stringify({
          label_fr: form.label_fr.trim(),
          type_montant: form.type_montant,
          valeur: valeurNum,
          financable_par_defaut: form.financable_par_defaut
        })
      });
      if (!r.ok) {
        const t = await r.text().catch(() => "");
        throw new Error(t.slice(0, 200) || `HTTP ${r.status}`);
      }
      const created = (await r.json()) as FraisCustomItem;
      setItems((prev) => [...prev, created]);
      setForm({
        label_fr: "",
        type_montant: "fixe",
        valeur: "",
        financable_par_defaut: false
      });
      notify("Frais ajouté.");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setAdding(false);
    }
  }

  async function toggleFin(item: FraisCustomItem, next: boolean) {
    setItems((prev) =>
      prev.map((it) =>
        it.id === item.id ? { ...it, financable_par_defaut: next } : it
      )
    );
    try {
      const r = await authedFetch(`${API}/frais-custom/${item.id}`, {
        method: "PATCH",
        body: JSON.stringify({ financable_par_defaut: next })
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
    } catch (e) {
      setItems((prev) =>
        prev.map((it) =>
          it.id === item.id ? { ...it, financable_par_defaut: !next } : it
        )
      );
      setError((e as Error).message);
    }
  }

  async function remove(item: FraisCustomItem) {
    setBusyId(item.id);
    setError(null);
    try {
      const r = await authedFetch(`${API}/frais-custom/${item.id}`, {
        method: "DELETE"
      });
      if (!r.ok && r.status !== 204) throw new Error(`HTTP ${r.status}`);
      setItems((prev) => prev.filter((it) => it.id !== item.id));
      notify("Frais retiré.");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div className="mt-4 rounded-xl border border-brand-800 bg-brand-950/40 p-3">
      <h3 className="text-xs font-bold uppercase tracking-wide text-amber-300">
        Frais de démarrage personnalisés
      </h3>
      <p className="mt-0.5 text-[10px] text-white/50">
        Postes additionnels ajoutables à la volée (montant fixe, % du prix
        d&apos;achat ou % du financement).
      </p>

      {loading ? (
        <div className="mt-3 flex items-center gap-2 text-xs text-white/60">
          <Loader2 className="h-3.5 w-3.5 animate-spin" /> Chargement…
        </div>
      ) : (
        <div className="mt-3 space-y-2">
          {items.length === 0 ? (
            <p className="text-[11px] text-white/40">
              Aucun frais personnalisé pour l&apos;instant.
            </p>
          ) : (
            items.map((item) => (
              <div
                key={item.id}
                className="flex items-center gap-2 rounded-lg border border-brand-800 bg-brand-950/60 px-3 py-2"
              >
                <div className="min-w-0 flex-1">
                  <p className="truncate text-xs font-semibold text-white/80">
                    {item.label_fr}
                  </p>
                  <p className="text-[10px] text-white/50">
                    {TYPE_MONTANT_LABEL[item.type_montant]} ·{" "}
                    <span className="font-mono text-white/70">
                      {item.valeur}
                      {item.type_montant === "fixe" ? " $" : " %"}
                    </span>
                  </p>
                </div>
                <label className="flex cursor-pointer items-center gap-1 text-[10px] text-white/60">
                  <input
                    type="checkbox"
                    checked={item.financable_par_defaut}
                    onChange={(e) => void toggleFin(item, e.target.checked)}
                    className="h-3.5 w-3.5 cursor-pointer accent-amber-400"
                  />
                  Finançable
                </label>
                <button
                  type="button"
                  onClick={() => void remove(item)}
                  disabled={busyId === item.id}
                  className="rounded-md border border-rose-500/30 p-1.5 text-rose-300 transition hover:bg-rose-500/10 disabled:opacity-40"
                  title="Retirer"
                >
                  {busyId === item.id ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <Trash2 className="h-3.5 w-3.5" />
                  )}
                </button>
              </div>
            ))
          )}
        </div>
      )}

      {/* Formulaire d'ajout. */}
      <div className="mt-3 rounded-lg border border-dashed border-brand-700 bg-brand-950/60 p-3">
        <div className="grid gap-2 sm:grid-cols-[1.4fr_1fr_0.8fr]">
          <input
            type="text"
            value={form.label_fr}
            onChange={(e) =>
              setForm((f) => ({ ...f, label_fr: e.target.value }))
            }
            placeholder="Nom du frais"
            className="input py-1.5 text-xs"
          />
          <select
            value={form.type_montant}
            onChange={(e) =>
              setForm((f) => ({
                ...f,
                type_montant: e.target
                  .value as FraisCustomItem["type_montant"]
              }))
            }
            className="input py-1.5 text-xs"
          >
            <option value="fixe">Montant fixe ($)</option>
            <option value="pct_prix_achat">% du prix d&apos;achat</option>
            <option value="pct_financement">% du financement</option>
          </select>
          <input
            type="number"
            step={0.01}
            min={0}
            value={form.valeur}
            onChange={(e) =>
              setForm((f) => ({ ...f, valeur: e.target.value }))
            }
            placeholder={form.type_montant === "fixe" ? "$" : "%"}
            className="input py-1.5 font-mono text-xs"
          />
        </div>
        <div className="mt-2 flex items-center justify-between">
          <label className="flex cursor-pointer items-center gap-2 text-[10px] text-white/70">
            <input
              type="checkbox"
              checked={form.financable_par_defaut}
              onChange={(e) =>
                setForm((f) => ({
                  ...f,
                  financable_par_defaut: e.target.checked
                }))
              }
              className="h-3.5 w-3.5 cursor-pointer accent-amber-400"
            />
            Finançable par défaut
          </label>
          <button
            type="button"
            onClick={() => void add()}
            disabled={adding}
            className="inline-flex items-center gap-1 rounded-md border border-amber-500/40 bg-amber-500/15 px-3 py-1.5 text-[11px] font-semibold text-amber-300 transition hover:bg-amber-500/25 disabled:opacity-40"
          >
            {adding ? (
              <Loader2 className="h-3 w-3 animate-spin" />
            ) : (
              <Plus className="h-3 w-3" />
            )}
            Ajouter un frais
          </button>
        </div>
      </div>

      {flash ? (
        <p className="mt-2 flex items-center gap-1 text-[10px] text-emerald-400">
          <CheckCircle2 className="h-3 w-3" /> {flash}
        </p>
      ) : null}
      {error ? (
        <p className="mt-2 text-[10px] text-rose-400">{error}</p>
      ) : null}
    </div>
  );
}

export function MdfFraisSection() {
  const { defaults, setDefaults, loading, error } =
    useGroupDefaults("mdf_frais");

  function patch(next: AnalysisDefault) {
    setDefaults((prev) => prev.map((d) => (d.key === next.key ? next : d)));
  }

  // Postes fixes éditables : on exclut la ligne porteuse de la liste
  // dynamique (frais_mdf_custom, dont la value_json est une liste).
  const fixed = defaults.filter((d) => d.key !== FRAIS_CUSTOM_KEY);

  return (
    <SectionShell
      icon={Wallet}
      iconClass="bg-rose-500/15 text-rose-400"
      title="Frais de démarrage (MDF prêteur B)"
      subtitle="Postes fixes (montant + finançable) et frais personnalisés ajoutables."
      loading={loading}
      error={error}
    >
      <div className="grid gap-2.5 sm:grid-cols-2">
        {fixed.map((def) => (
          <ScalarDefaultRow
            key={def.key}
            def={def}
            onUpdated={patch}
            showFinancable
          />
        ))}
      </div>
      <FraisCustomList />
    </SectionShell>
  );
}
