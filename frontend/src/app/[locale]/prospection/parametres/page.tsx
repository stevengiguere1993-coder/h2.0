"use client";

import { useEffect, useState } from "react";
import {
  AlertCircle,
  CheckCircle2,
  Database,
  Info,
  Loader2,
  Map,
  RefreshCw,
  RotateCcw,
  Save,
  Sparkles
} from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { ConnexionsSection } from "@/components/connexions-section";
import { Link } from "@/i18n/navigation";
import { authedFetch, hasMinRole } from "@/lib/auth";
import { useCurrentUser } from "@/hooks/use-current-user";
import {
  DEFAULT_PREFS,
  loadPrefs,
  resetPrefs,
  savePrefs,
  ZONE_PRESETS,
  type ProspectionPrefs
} from "@/lib/prospection-prefs";
import { useProspectionLayout } from "../layout";

const KIND_OPTIONS = [
  { value: "multilogement", label: "Multi-logement" },
  { value: "terrain", label: "Terrain" },
  { value: "semi_commercial", label: "Semi-commercial" },
  { value: "autre", label: "Autre" }
];

const SCORE_RULES: { label: string; pts: string; explain: string }[] = [
  {
    label: "Sweet spot 6-12 logements",
    pts: "+30",
    explain: "Le créneau idéal Horizon — assez gros pour un contrat juteux, gérable côté logistique."
  },
  {
    label: "Multi 13-20 portes",
    pts: "+24",
    explain: "Encore très intéressant, légèrement plus gros mais reste dans la cible."
  },
  {
    label: "Petit multi 4-5 portes",
    pts: "+22",
    explain: "Acceptable, surtout si valeur foncière élevée ou bâtiment ancien."
  },
  {
    label: "60 ans+ (très vieux)",
    pts: "+18",
    explain: "Forte probabilité de besoin en rénovation majeure (toit, plomberie, électricité)."
  },
  {
    label: "Corporation avec NEQ connu",
    pts: "+22",
    explain: "Décision d'investissement, budget alloué, prise de décision plus rapide."
  },
  {
    label: "Priorité haute (4-5 étoiles)",
    pts: "+4",
    explain: "Drapeau manuel posé par l'utilisateur quand il sent un coup à jouer."
  },
  {
    label: "Complétude des données",
    pts: "jusqu'à +8",
    explain: "Plus le lead est renseigné (adresse, notes, matricule, valeur), plus il est actionnable."
  }
];

export default function ProspectionSettingsPage() {
  const { onOpenSidebar } = useProspectionLayout();
  const { user } = useCurrentUser();
  const isOwner = hasMinRole(user, "owner");
  const isAdmin = hasMinRole(user, "admin");

  const [prefs, setPrefs] = useState<ProspectionPrefs>(DEFAULT_PREFS);
  const [savedAt, setSavedAt] = useState<number | null>(null);

  useEffect(() => {
    setPrefs(loadPrefs());
  }, []);

  function update<K extends keyof ProspectionPrefs>(
    k: K,
    v: ProspectionPrefs[K]
  ) {
    setPrefs((prev) => ({ ...prev, [k]: v }));
  }

  function applyZone(z: (typeof ZONE_PRESETS)[number]) {
    setPrefs((prev) => ({
      ...prev,
      mapCenterLat: z.lat,
      mapCenterLng: z.lng,
      mapZoom: z.zoom
    }));
  }

  function save() {
    savePrefs(prefs);
    setSavedAt(Date.now());
    window.setTimeout(() => setSavedAt(null), 2500);
  }

  function reset() {
    resetPrefs();
    setPrefs(DEFAULT_PREFS);
    setSavedAt(Date.now());
    window.setTimeout(() => setSavedAt(null), 2500);
  }

  return (
    <>
      <AppTopbar
        breadcrumbs={[
          { label: "Prospection", href: "/prospection" },
          { label: "Paramètres" }
        ]}
        onOpenSidebar={onOpenSidebar}
      />

      <div className="mx-auto max-w-3xl p-4 lg:p-6">
        <h1 className="text-2xl font-bold text-white">
          Paramètres Prospection
        </h1>
        <p className="mt-1 text-sm text-white/60">
          Personnalise la zone de prospection par défaut, comprends
          comment le score est calculé, et accède aux outils admin.
        </p>

        {savedAt ? (
          <p className="mt-4 flex items-center gap-1.5 rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-sm text-emerald-300">
            <CheckCircle2 className="h-4 w-4" />
            Préférences enregistrées.
          </p>
        ) : null}

        {/* === Préférences carte === */}
        <section className="mt-6 rounded-2xl border border-brand-800 bg-brand-900 p-5">
          <header className="flex items-center gap-3">
            <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-emerald-500/15 text-emerald-400">
              <Map className="h-5 w-5" />
            </span>
            <div>
              <h2 className="text-base font-bold text-white">
                Préférences de carte
              </h2>
              <p className="mt-0.5 text-xs text-white/60">
                Centre et zoom appliqués à l&apos;ouverture de la carte
                Prospection. Sauvegardés sur ce poste seulement.
              </p>
            </div>
          </header>

          <div className="mt-4 space-y-4">
            <div>
              <label className="label">Zone rapide</label>
              <div className="mt-1 flex flex-wrap gap-1.5">
                {ZONE_PRESETS.map((z) => (
                  <button
                    key={z.label}
                    type="button"
                    onClick={() => applyZone(z)}
                    className="rounded-full border border-brand-700 bg-brand-950 px-2.5 py-1 text-[11px] text-white/70 hover:border-emerald-500/50 hover:text-emerald-300"
                  >
                    {z.label}
                  </button>
                ))}
              </div>
            </div>

            <div className="grid gap-3 sm:grid-cols-3">
              <div>
                <label className="label">Latitude</label>
                <input
                  type="number"
                  step="0.0001"
                  value={prefs.mapCenterLat}
                  onChange={(e) =>
                    update("mapCenterLat", Number(e.target.value))
                  }
                  className="input"
                />
              </div>
              <div>
                <label className="label">Longitude</label>
                <input
                  type="number"
                  step="0.0001"
                  value={prefs.mapCenterLng}
                  onChange={(e) =>
                    update("mapCenterLng", Number(e.target.value))
                  }
                  className="input"
                />
              </div>
              <div>
                <label className="label">Zoom (1-19)</label>
                <input
                  type="number"
                  min="1"
                  max="19"
                  value={prefs.mapZoom}
                  onChange={(e) =>
                    update("mapZoom", Number(e.target.value))
                  }
                  className="input"
                />
              </div>
            </div>
          </div>
        </section>

        {/* === Défauts nouveaux leads === */}
        <section className="mt-6 rounded-2xl border border-brand-800 bg-brand-900 p-5">
          <header className="flex items-center gap-3">
            <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-emerald-500/15 text-emerald-400">
              <Sparkles className="h-5 w-5" />
            </span>
            <div>
              <h2 className="text-base font-bold text-white">
                Défauts pour les nouveaux leads
              </h2>
              <p className="mt-0.5 text-xs text-white/60">
                Pré-remplit le formulaire de capture drive-by pour
                gagner des secondes sur le terrain.
              </p>
            </div>
          </header>

          <div className="mt-4 grid gap-3 sm:grid-cols-2">
            <div>
              <label className="label">Type par défaut</label>
              <select
                value={prefs.defaultKind}
                onChange={(e) => update("defaultKind", e.target.value)}
                className="input"
              >
                {KIND_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="label">
                Priorité par défaut ({prefs.defaultPriority}/5)
              </label>
              <input
                type="range"
                min="1"
                max="5"
                step="1"
                value={prefs.defaultPriority}
                onChange={(e) =>
                  update("defaultPriority", Number(e.target.value))
                }
                className="w-full"
              />
            </div>
          </div>
        </section>

        <div className="mt-4 flex flex-wrap items-center justify-end gap-2">
          <button
            type="button"
            onClick={reset}
            className="inline-flex items-center gap-1.5 rounded-md border border-brand-700 bg-brand-900 px-3 py-2 text-xs text-white/70 hover:bg-brand-800 hover:text-white"
          >
            <RotateCcw className="h-3.5 w-3.5" />
            Réinitialiser
          </button>
          <button
            type="button"
            onClick={save}
            className="btn-accent text-sm"
          >
            <Save className="mr-1.5 h-4 w-4" />
            Enregistrer
          </button>
        </div>

        {/* === Méthodologie scoring === */}
        <section className="mt-6 rounded-2xl border border-brand-800 bg-brand-900 p-5">
          <header className="flex items-center gap-3">
            <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-emerald-500/15 text-emerald-400">
              <Info className="h-5 w-5" />
            </span>
            <div>
              <h2 className="text-base font-bold text-white">
                Comment le score est calculé
              </h2>
              <p className="mt-0.5 text-xs text-white/60">
                Score 0-100 plafonné. Les bonus s&apos;additionnent.
                Maximum 6 tags par lead.
              </p>
            </div>
          </header>

          <ul className="mt-4 divide-y divide-brand-800 text-sm">
            {SCORE_RULES.map((r) => (
              <li key={r.label} className="flex items-start gap-3 py-2.5">
                <span className="w-20 shrink-0 rounded-md bg-emerald-500/15 px-2 py-1 text-center text-xs font-bold text-emerald-300">
                  {r.pts}
                </span>
                <div className="min-w-0">
                  <p className="font-medium text-white">{r.label}</p>
                  <p className="text-xs text-white/50">{r.explain}</p>
                </div>
              </li>
            ))}
          </ul>
        </section>

        {/* === Connexions Prospection === */}
        <ConnexionsSection scope="prospection" />

        {/* === Outils admin === */}
        {isAdmin ? <AdminToolsSection /> : null}

        {/* === Lien vers Sources de données === */}
        {isOwner ? (
          <Link
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            href={"/prospection/sources" as any}
            className="mt-6 flex items-center gap-3 rounded-2xl border border-brand-800 bg-brand-900 p-5 transition hover:border-emerald-500/50"
          >
            <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-emerald-500/15 text-emerald-400">
              <Database className="h-5 w-5" />
            </span>
            <div className="min-w-0 flex-1">
              <h2 className="text-base font-bold text-white">
                Sources de données →
              </h2>
              <p className="mt-0.5 text-xs text-white/60">
                Imports manuels du rôle d&apos;évaluation Montréal et
                du Registraire des entreprises (REQ).
              </p>
            </div>
          </Link>
        ) : null}
      </div>
    </>
  );
}

function AdminToolsSection() {
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function recompute() {
    if (busy) return;
    setBusy(true);
    setResult(null);
    setError(null);
    try {
      const res = await authedFetch(
        "/api/v1/prospection/recompute-scores",
        { method: "POST" }
      );
      if (!res.ok) {
        const t = await res.text();
        throw new Error(t.slice(0, 240) || `HTTP ${res.status}`);
      }
      const data = (await res.json()) as { recomputed: number };
      setResult(
        `${data.recomputed.toLocaleString("fr-CA")} leads recalculés.`
      );
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="mt-6 rounded-2xl border border-brand-800 bg-brand-900 p-5">
      <header className="flex items-center gap-3">
        <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-amber-500/15 text-amber-400">
          <RefreshCw className="h-5 w-5" />
        </span>
        <div>
          <h2 className="text-base font-bold text-white">
            Outils administratifs
          </h2>
          <p className="mt-0.5 text-xs text-white/60">
            Actions rares à utiliser après une mise à jour de la
            logique de scoring ou pour backfiller d&apos;anciens leads.
          </p>
        </div>
      </header>

      <div className="mt-4">
        <button
          type="button"
          onClick={recompute}
          disabled={busy}
          className="inline-flex items-center gap-2 rounded-lg border border-amber-500/40 bg-amber-500/10 px-4 py-2 text-sm font-medium text-amber-300 hover:bg-amber-500/20 disabled:opacity-50"
        >
          {busy ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <RefreshCw className="h-4 w-4" />
          )}
          Recalculer tous les scores
        </button>

        {result ? (
          <p className="mt-3 flex items-center gap-1.5 rounded-md border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-xs text-emerald-300">
            <CheckCircle2 className="h-3.5 w-3.5" />
            {result}
          </p>
        ) : null}
        {error ? (
          <p className="mt-3 flex items-center gap-1.5 rounded-md border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
            <AlertCircle className="h-3.5 w-3.5" />
            {error}
          </p>
        ) : null}
      </div>
    </section>
  );
}
