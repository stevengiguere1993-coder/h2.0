"use client";

import { useCallback, useEffect, useState } from "react";
import {
  Building2,
  Calculator,
  Check,
  CheckCircle2,
  Eye,
  EyeOff,
  GripVertical,
  Landmark,
  Loader2,
  Pencil,
  Percent,
  Plus,
  Save,
  SlidersHorizontal,
  Trash2,
  Wallet,
  X
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
          className="inline-flex items-center gap-1 rounded-md border border-accent-500/40 bg-accent-500/15 px-2.5 py-1.5 text-[11px] font-semibold text-accent-500 transition hover:bg-accent-500/25 disabled:cursor-not-allowed disabled:opacity-40"
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
          ? "border-accent-500/40 bg-accent-500/[0.04]"
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
      iconClass="bg-accent-500/15 text-accent-500"
      title="Dépenses normalisées (SCHL)"
      subtitle="Barème SCHL : conciergerie, entretien, gestion, wifi/internet, thermopompe, seuil 12 log, taux d'inoccupation."
      loading={loading}
      error={error}
      highlight
    >
      <p className="mb-3 rounded-md border border-accent-500/30 bg-accent-500/[0.06] px-3 py-2 text-[11px] text-accent-200/90">
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
          className="inline-flex items-center gap-1 rounded-md border border-accent-500/40 bg-accent-500/15 px-2.5 py-1.5 text-[11px] font-semibold text-accent-500 transition hover:bg-accent-500/25 disabled:opacity-40"
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

// ── 5. Frais de démarrage (MDF) — REGISTRE UNIFIÉ ──────────────────
//
// UNE seule liste pour TOUS les postes (fixes, %, formules, inputs de
// fiche et perso), chargée via GET ``/analysis-defaults/mdf-registry``
// (ordonnée + enrichie). Pour chaque poste on peut :
//   • réordonner par drag-drop (poignée GripVertical → PUT .../order) ;
//   • renommer le libellé (PATCH .../mdf-registry/{key} {label_fr}) ;
//   • éditer le montant $ / % (montant_fixe, pct, perso) via les
//     endpoints defaults existants (poste fixe → PATCH
//     /analysis-defaults/{cléBD} ; perso → PATCH /frais-custom/{id}) ;
//   • basculer « finançable par défaut » (même endpoints) ;
//   • masquer/afficher (PATCH .../mdf-registry/{key} {visible}) pour les
//     non-supprimables, ou supprimer (DELETE /frais-custom/{id}) pour
//     les perso.
// Le drag-drop réutilise le DnD HTML5 natif du repo (poignée
// GripVertical + draggable/onDragStart/onDragOver/onDrop), aucune lib
// externe (le projet n'embarque pas @dnd-kit).

type RegistryNature =
  | "montant_fixe"
  | "pct"
  | "formule"
  | "input_fiche"
  | "perso";

type RegistryPoste = {
  key: string;
  label_fr: string;
  nature: RegistryNature;
  visible: boolean;
  supprimable: boolean;
  financable_par_defaut: boolean | null;
  montant_defaut: number | null;
  pct_defaut: number | null;
};

// Mapping clé interne d'un poste FIXE → clé BD du défaut $ (montant).
// Miroir de ``_FIXED_KEY_TO_DB_AMOUNT`` côté backend.
const FIXED_KEY_TO_DB_AMOUNT: Record<string, string> = {
  evaluateur: "frais_evaluateur",
  evaluateur_2: "frais_evaluateur_2",
  inspection: "frais_inspection",
  avocat: "frais_avocat",
  notaire: "frais_notaire",
  notaire_2: "frais_notaire_2",
  rapport_efficacite: "frais_rapport_efficacite"
};

// Mapping clé interne d'un poste FIXE → clé BD du défaut % (pourcentage,
// 1.0 = 1 %). Miroir de ``_FIXED_KEY_TO_DB_PCT`` côté backend.
const FIXED_KEY_TO_DB_PCT: Record<string, string> = {
  courtier_hypothecaire_1: "pct_courtier_hypothecaire_1",
  courtier_hypothecaire_2: "pct_courtier_hypothecaire_2",
  frais_dossier_preteur: "frais_dossier_preteur_pct"
};

// Libellé court de la nature (badge à droite du libellé).
const NATURE_BADGE: Record<RegistryNature, string> = {
  montant_fixe: "Montant",
  pct: "Pourcentage",
  formule: "Calculé",
  input_fiche: "Saisi par fiche",
  perso: "Personnalisé"
};

// Un poste est éditable (montant/%) seulement pour ces natures.
function isEditableValue(nature: RegistryNature): boolean {
  return nature === "montant_fixe" || nature === "pct" || nature === "perso";
}

// L'unité affichée pour la valeur éditable d'un poste.
function unitForPoste(p: RegistryPoste): "$" | "%" | "" {
  if (p.nature === "montant_fixe") return "$";
  if (p.nature === "pct") return "%";
  if (p.nature === "perso") return p.montant_defaut != null ? "$" : "%";
  return "";
}

// ── Hook DnD HTML5 natif (clés string) ─────────────────────────────
// Repris du mécanisme du repo (soumission devlog / pipeline) : poignée
// draggable, liseré de drop, calcul du nouvel ordre des clés au drop.
function useKeyDnd(
  keys: string[],
  onReorder: (orderedKeys: string[]) => void
) {
  const [dragKey, setDragKey] = useState<string | null>(null);
  const [overIndex, setOverIndex] = useState<number | null>(null);

  function reset() {
    setDragKey(null);
    setOverIndex(null);
  }

  function commit(targetIndex: number) {
    if (dragKey == null) return;
    const from = keys.indexOf(dragKey);
    if (from < 0) return;
    const next = keys.filter((x) => x !== dragKey);
    let insertAt = targetIndex;
    if (from < targetIndex) insertAt -= 1;
    insertAt = Math.max(0, Math.min(insertAt, next.length));
    next.splice(insertAt, 0, dragKey);
    reset();
    const changed = next.some((x, i) => x !== keys[i]);
    if (changed) onReorder(next);
  }

  function handleProps(key: string) {
    return {
      draggable: true,
      onDragStart: (ev: React.DragEvent) => {
        setDragKey(key);
        try {
          ev.dataTransfer.effectAllowed = "move";
          ev.dataTransfer.setData("text/plain", key);
        } catch {
          /* ignore (jsdom) */
        }
      },
      onDragEnd: reset
    };
  }

  function rowProps(index: number) {
    return {
      onDragOver: (ev: React.DragEvent) => {
        if (dragKey == null) return;
        ev.preventDefault();
        ev.stopPropagation();
        ev.dataTransfer.dropEffect = "move";
        const rect = (
          ev.currentTarget as HTMLElement
        ).getBoundingClientRect();
        const after = ev.clientY - rect.top > rect.height / 2;
        const next = after ? index + 1 : index;
        if (overIndex !== next) setOverIndex(next);
      },
      onDrop: (ev: React.DragEvent) => {
        if (dragKey == null) return;
        ev.preventDefault();
        ev.stopPropagation();
        commit(overIndex ?? index);
      }
    };
  }

  return {
    dragKey,
    overIndex,
    isDragging: dragKey != null,
    handleProps,
    rowProps,
    reset
  };
}

// Liseré bleu de drop (même rendu que la soumission devlog).
function dropRowClass(
  index: number,
  count: number,
  overIndex: number | null,
  isDragging: boolean
): string {
  if (!isDragging || overIndex == null) return "";
  if (overIndex === index) {
    return "shadow-[inset_0_2px_0_0_rgb(96,165,250)]";
  }
  if (overIndex === count && index === count - 1) {
    return "shadow-[inset_0_-2px_0_0_rgb(96,165,250)]";
  }
  return "";
}

// ── Une ligne du registre unifié ───────────────────────────────────

function RegistryRow({
  poste,
  index,
  count,
  dnd,
  onReload,
  onError
}: {
  poste: RegistryPoste;
  index: number;
  count: number;
  dnd: ReturnType<typeof useKeyDnd>;
  onReload: (next: RegistryPoste[]) => void;
  onError: (msg: string | null) => void;
}) {
  // Brouillons d'édition.
  const [labelDraft, setLabelDraft] = useState(poste.label_fr);
  const [editingLabel, setEditingLabel] = useState(false);
  const [valueDraft, setValueDraft] = useState(
    poste.montant_defaut != null
      ? String(poste.montant_defaut)
      : poste.pct_defaut != null
        ? String(poste.pct_defaut)
        : ""
  );
  const [savingLabel, setSavingLabel] = useState(false);
  const [savingValue, setSavingValue] = useState(false);
  const [valueSaved, setValueSaved] = useState(false);
  const [busy, setBusy] = useState(false);

  // Resync les brouillons quand la donnée amont change (rechargement).
  useEffect(() => {
    if (!editingLabel) setLabelDraft(poste.label_fr);
  }, [poste.label_fr, editingLabel]);
  useEffect(() => {
    setValueDraft(
      poste.montant_defaut != null
        ? String(poste.montant_defaut)
        : poste.pct_defaut != null
          ? String(poste.pct_defaut)
          : ""
    );
  }, [poste.montant_defaut, poste.pct_defaut]);

  const editable = isEditableValue(poste.nature);
  const unit = unitForPoste(poste);
  const currentValue =
    poste.montant_defaut != null
      ? poste.montant_defaut
      : poste.pct_defaut != null
        ? poste.pct_defaut
        : null;
  const valueNum = Number(valueDraft);
  const valueDirty =
    Number.isFinite(valueNum) &&
    Math.abs(valueNum - (currentValue ?? 0)) > 1e-9;

  // Endpoint + body pour éditer le montant/% d'un poste fixe (clé BD)
  // ou perso (frais-custom). Retourne null si non éditable.
  function valueRequest(value: number): { url: string; body: string } | null {
    if (poste.nature === "perso") {
      return {
        url: `${API}/frais-custom/${poste.key}`,
        body: JSON.stringify({ valeur: value })
      };
    }
    if (poste.nature === "montant_fixe") {
      const dbKey = FIXED_KEY_TO_DB_AMOUNT[poste.key];
      if (!dbKey) return null;
      return {
        url: `${API}/${encodeURIComponent(dbKey)}`,
        body: JSON.stringify({ value_float: value })
      };
    }
    if (poste.nature === "pct") {
      const dbKey = FIXED_KEY_TO_DB_PCT[poste.key];
      if (!dbKey) return null;
      return {
        url: `${API}/${encodeURIComponent(dbKey)}`,
        body: JSON.stringify({ value_float: value })
      };
    }
    return null;
  }

  // Endpoint + body pour basculer « finançable par défaut ». Pour les
  // postes fixes, le flag vit sur la ligne BD du montant/%.
  function financableRequest(
    next: boolean
  ): { url: string; body: string } | null {
    if (poste.nature === "perso") {
      return {
        url: `${API}/frais-custom/${poste.key}`,
        body: JSON.stringify({ financable_par_defaut: next })
      };
    }
    const dbKey =
      FIXED_KEY_TO_DB_AMOUNT[poste.key] ?? FIXED_KEY_TO_DB_PCT[poste.key];
    if (!dbKey) return null;
    return {
      url: `${API}/${encodeURIComponent(dbKey)}`,
      body: JSON.stringify({ financable_par_defaut: next })
    };
  }

  // Recharge la liste enrichie depuis le registre après une action qui
  // n'en renvoie pas (endpoints defaults / frais-custom).
  async function reloadRegistry() {
    const r = await authedFetch(`${API}/mdf-registry`);
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    onReload((await r.json()) as RegistryPoste[]);
  }

  async function saveLabel() {
    const next = labelDraft.trim();
    if (!next || next === poste.label_fr) {
      setEditingLabel(false);
      setLabelDraft(poste.label_fr);
      return;
    }
    setSavingLabel(true);
    onError(null);
    try {
      const r = await authedFetch(
        `${API}/mdf-registry/${encodeURIComponent(poste.key)}`,
        { method: "PATCH", body: JSON.stringify({ label_fr: next }) }
      );
      if (!r.ok) {
        const t = await r.text().catch(() => "");
        throw new Error(t.slice(0, 200) || `HTTP ${r.status}`);
      }
      onReload((await r.json()) as RegistryPoste[]);
      setEditingLabel(false);
    } catch (e) {
      onError((e as Error).message);
    } finally {
      setSavingLabel(false);
    }
  }

  async function saveValue() {
    if (!Number.isFinite(valueNum)) {
      onError("Valeur invalide.");
      return;
    }
    const req = valueRequest(valueNum);
    if (!req) return;
    setSavingValue(true);
    onError(null);
    try {
      const r = await authedFetch(req.url, {
        method: "PATCH",
        body: req.body
      });
      if (!r.ok) {
        const t = await r.text().catch(() => "");
        throw new Error(t.slice(0, 200) || `HTTP ${r.status}`);
      }
      await reloadRegistry();
      setValueSaved(true);
      setTimeout(() => setValueSaved(false), 2000);
    } catch (e) {
      onError((e as Error).message);
    } finally {
      setSavingValue(false);
    }
  }

  async function toggleFinancable(next: boolean) {
    const req = financableRequest(next);
    if (!req) return;
    setBusy(true);
    onError(null);
    try {
      const r = await authedFetch(req.url, {
        method: "PATCH",
        body: req.body
      });
      if (!r.ok) {
        const t = await r.text().catch(() => "");
        throw new Error(t.slice(0, 200) || `HTTP ${r.status}`);
      }
      await reloadRegistry();
    } catch (e) {
      onError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  // Masquer / afficher (non-supprimables) via le registre.
  async function setVisible(next: boolean) {
    setBusy(true);
    onError(null);
    try {
      const r = await authedFetch(
        `${API}/mdf-registry/${encodeURIComponent(poste.key)}`,
        { method: "PATCH", body: JSON.stringify({ visible: next }) }
      );
      if (!r.ok) {
        const t = await r.text().catch(() => "");
        throw new Error(t.slice(0, 200) || `HTTP ${r.status}`);
      }
      onReload((await r.json()) as RegistryPoste[]);
    } catch (e) {
      onError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  // Supprimer un poste perso (DELETE) — puis recharge le registre.
  async function removePerso() {
    setBusy(true);
    onError(null);
    try {
      const r = await authedFetch(`${API}/frais-custom/${poste.key}`, {
        method: "DELETE"
      });
      if (!r.ok && r.status !== 204) {
        const t = await r.text().catch(() => "");
        throw new Error(t.slice(0, 200) || `HTTP ${r.status}`);
      }
      await reloadRegistry();
    } catch (e) {
      onError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const dropClass = dropRowClass(index, count, dnd.overIndex, dnd.isDragging);
  const dimmed = !poste.visible;

  return (
    <div
      {...dnd.rowProps(index)}
      className={`rounded-lg border px-3 py-2.5 transition ${
        dimmed
          ? "border-brand-800 bg-brand-950/30 opacity-60"
          : "border-brand-800 bg-brand-950/60"
      } ${dropClass}`}
    >
      <div className="flex items-start gap-2">
        {/* Poignée de drag-drop. */}
        <span
          {...dnd.handleProps(poste.key)}
          role="button"
          aria-label="Glisser pour réordonner"
          title="Glisser pour réordonner"
          className="mt-0.5 inline-flex cursor-grab touch-none text-white/50 hover:text-white/80 active:cursor-grabbing"
        >
          <GripVertical className="h-4 w-4" />
        </span>

        <div className="min-w-0 flex-1">
          {/* Ligne libellé (éditable inline). */}
          <div className="flex items-center gap-2">
            {editingLabel ? (
              <>
                <input
                  type="text"
                  value={labelDraft}
                  onChange={(e) => setLabelDraft(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") void saveLabel();
                    if (e.key === "Escape") {
                      setEditingLabel(false);
                      setLabelDraft(poste.label_fr);
                    }
                  }}
                  autoFocus
                  className="input flex-1 py-1 text-xs"
                  disabled={savingLabel}
                />
                <button
                  type="button"
                  onClick={() => void saveLabel()}
                  disabled={savingLabel}
                  className="rounded-md border border-accent-500/40 bg-accent-500/15 p-1 text-accent-500 transition hover:bg-accent-500/25 disabled:opacity-40"
                  title="Enregistrer le nom"
                >
                  {savingLabel ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <Check className="h-3.5 w-3.5" />
                  )}
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setEditingLabel(false);
                    setLabelDraft(poste.label_fr);
                  }}
                  className="rounded-md border border-brand-700 p-1 text-white/60 transition hover:bg-brand-800 hover:text-white/80"
                  title="Annuler"
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              </>
            ) : (
              <>
                <span
                  className={`truncate text-xs font-semibold ${
                    dimmed ? "text-white/50" : "text-white/85"
                  }`}
                >
                  {poste.label_fr}
                </span>
                <button
                  type="button"
                  onClick={() => {
                    setLabelDraft(poste.label_fr);
                    setEditingLabel(true);
                  }}
                  className="rounded-md p-1 text-white/40 transition hover:bg-brand-800 hover:text-white/70"
                  title="Renommer"
                >
                  <Pencil className="h-3 w-3" />
                </button>
                <span className="shrink-0 rounded-full border border-brand-700 bg-brand-900 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-white/50">
                  {NATURE_BADGE[poste.nature]}
                </span>
                {dimmed ? (
                  <span className="shrink-0 rounded-full border border-amber-500/40 bg-amber-500/10 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-amber-200">
                    Masqué
                  </span>
                ) : null}
              </>
            )}
          </div>

          {/* Ligne valeur + finançable + actions. */}
          <div className="mt-2 flex flex-wrap items-center gap-2">
            {editable ? (
              <div className="flex items-center gap-1.5">
                <input
                  type="number"
                  step={poste.nature === "montant_fixe" ? 1 : 0.01}
                  min={0}
                  value={valueDraft}
                  onChange={(e) => setValueDraft(e.target.value)}
                  className="input w-28 py-1 font-mono text-xs"
                  disabled={savingValue || dimmed}
                />
                <span className="w-4 shrink-0 text-[10px] text-white/40">
                  {unit}
                </span>
                <button
                  type="button"
                  onClick={() => void saveValue()}
                  disabled={!valueDirty || savingValue || dimmed}
                  className="inline-flex items-center gap-1 rounded-md border border-accent-500/40 bg-accent-500/15 px-2 py-1 text-[10px] font-semibold text-accent-500 transition hover:bg-accent-500/25 disabled:cursor-not-allowed disabled:opacity-40"
                >
                  {savingValue ? (
                    <Loader2 className="h-3 w-3 animate-spin" />
                  ) : (
                    <Save className="h-3 w-3" />
                  )}
                  Enregistrer
                </button>
                {valueSaved ? (
                  <CheckCircle2 className="h-3.5 w-3.5 text-emerald-400" />
                ) : null}
              </div>
            ) : (
              <span className="rounded-md border border-brand-700 bg-brand-900/60 px-2 py-1 text-[10px] italic text-white/50">
                {poste.nature === "formule"
                  ? "Calculé automatiquement"
                  : "Saisi sur chaque fiche"}
              </span>
            )}

            {/* Toggle finançable (si applicable). */}
            {poste.financable_par_defaut != null ? (
              <label className="flex cursor-pointer items-center gap-1.5 text-[10px] text-white/70">
                <input
                  type="checkbox"
                  checked={!!poste.financable_par_defaut}
                  onChange={(e) => void toggleFinancable(e.target.checked)}
                  disabled={busy}
                  className="h-3.5 w-3.5 cursor-pointer accent-amber-400"
                />
                Finançable par défaut
              </label>
            ) : null}

            {/* Actions à droite : masquer/afficher ou supprimer. */}
            <div className="ml-auto flex items-center gap-1">
              {poste.supprimable ? (
                <button
                  type="button"
                  onClick={() => void removePerso()}
                  disabled={busy}
                  className="rounded-md border border-rose-500/30 p-1.5 text-rose-300 transition hover:bg-rose-500/10 disabled:opacity-40"
                  title="Supprimer ce poste"
                >
                  {busy ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <Trash2 className="h-3.5 w-3.5" />
                  )}
                </button>
              ) : dimmed ? (
                <button
                  type="button"
                  onClick={() => void setVisible(true)}
                  disabled={busy}
                  className="inline-flex items-center gap-1 rounded-md border border-accent-500/40 bg-accent-500/15 px-2 py-1 text-[10px] font-semibold text-accent-500 transition hover:bg-accent-500/25 disabled:opacity-40"
                  title="Réafficher ce poste"
                >
                  {busy ? (
                    <Loader2 className="h-3 w-3 animate-spin" />
                  ) : (
                    <Eye className="h-3 w-3" />
                  )}
                  Afficher
                </button>
              ) : (
                <button
                  type="button"
                  onClick={() => void setVisible(false)}
                  disabled={busy}
                  className="rounded-md border border-brand-700 p-1.5 text-white/50 transition hover:bg-brand-800 hover:text-white/80 disabled:opacity-40"
                  title="Masquer ce poste (exclu du calcul)"
                >
                  {busy ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <EyeOff className="h-3.5 w-3.5" />
                  )}
                </button>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

// ── Liste unifiée + formulaire d'ajout ─────────────────────────────

function UnifiedFraisRegistry() {
  const [postes, setPostes] = useState<RegistryPoste[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [flash, setFlash] = useState<string | null>(null);

  // Brouillon du nouveau poste (créé comme perso).
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
      const r = await authedFetch(`${API}/mdf-registry`);
      if (r.status === 403) {
        throw new Error("Accès réservé aux administrateurs.");
      }
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      setPostes((await r.json()) as RegistryPoste[]);
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

  const keys = postes.map((p) => p.key);

  // Réordonnancement (optimistic) — PUT .../order avec le nouvel ordre.
  const dnd = useKeyDnd(keys, (orderedKeys) => {
    const byKey = new Map(postes.map((p) => [p.key, p]));
    const optimistic = orderedKeys
      .map((k) => byKey.get(k))
      .filter((p): p is RegistryPoste => p != null);
    setPostes(optimistic);
    void persistOrder(orderedKeys);
  });

  async function persistOrder(orderedKeys: string[]) {
    setError(null);
    try {
      const r = await authedFetch(`${API}/mdf-registry/order`, {
        method: "PUT",
        body: JSON.stringify({ order: orderedKeys })
      });
      if (!r.ok) {
        const t = await r.text().catch(() => "");
        throw new Error(t.slice(0, 200) || `HTTP ${r.status}`);
      }
      setPostes((await r.json()) as RegistryPoste[]);
    } catch (e) {
      setError((e as Error).message);
      // Rollback : on recharge l'ordre serveur authentique.
      void load();
    }
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
      // Le POST renvoie le poste perso ; on recharge le registre pour
      // récupérer l'ordre + l'enrichissement à jour (le poste est
      // auto-appendu au registre par le backend).
      await load();
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

  return (
    <div>
      <p className="mb-3 rounded-md border border-rose-500/30 bg-rose-500/[0.06] px-3 py-2 text-[11px] text-rose-200/90">
        Liste unique de TOUS les postes de frais de démarrage. Glisse la
        poignée pour réordonner, clique le crayon pour renommer, ajuste le
        montant ou le pourcentage et coche « finançable par défaut ».
        L&apos;ordre et les libellés se reflètent dans la fiche d&apos;analyse
        et le PDF. Un poste{" "}
        <strong className="text-white">masqué est exclu du calcul</strong> mais
        reste dans la liste (bouton « Afficher » pour le réactiver). Les postes
        « Calculé » et « Saisi par fiche » n&apos;ont pas de montant éditable
        ici.
      </p>

      {loading ? (
        <div className="flex items-center gap-2 text-xs text-white/60">
          <Loader2 className="h-3.5 w-3.5 animate-spin" /> Chargement…
        </div>
      ) : (
        <div className="space-y-2">
          {postes.length === 0 ? (
            <p className="text-[11px] text-white/40">
              Aucun poste de frais pour l&apos;instant.
            </p>
          ) : (
            postes.map((p, i) => (
              <RegistryRow
                key={p.key}
                poste={p}
                index={i}
                count={postes.length}
                dnd={dnd}
                onReload={setPostes}
                onError={setError}
              />
            ))
          )}
        </div>
      )}

      {/* Formulaire d'ajout d'un poste (créé comme perso). */}
      <div className="mt-3 rounded-lg border border-dashed border-brand-700 bg-brand-950/60 p-3">
        <p className="mb-2 text-[10px] font-semibold uppercase tracking-wide text-amber-300">
          Ajouter un frais
        </p>
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
        <p className="mt-2 rounded-md border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-[11px] text-rose-300">
          {error}
        </p>
      ) : null}
    </div>
  );
}

export function MdfFraisSection() {
  return (
    <SectionShell
      icon={Wallet}
      iconClass="bg-rose-500/15 text-rose-400"
      title="Frais de démarrage (MDF prêteur B)"
      subtitle="Liste unifiée : réordonne, renomme, édite montant/%, finançable, masque ou supprime chaque poste."
    >
      <UnifiedFraisRegistry />
    </SectionShell>
  );
}

// ── 6. Défauts TRI (tri_defaults) ──────────────────────────────────

export function TriDefautsSection() {
  const { defaults, setDefaults, loading, error } =
    useGroupDefaults("tri_defaults");

  function patch(next: AnalysisDefault) {
    setDefaults((prev) => prev.map((d) => (d.key === next.key ? next : d)));
  }

  return (
    <SectionShell
      icon={Percent}
      iconClass="bg-accent-500/15 text-accent-500"
      title="Défauts TRI (taux de rendement interne)"
      subtitle="Valeurs pré-remplies de l'onglet TRI : % des parts de l'investisseur, croissance des loyers et des dépenses."
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
