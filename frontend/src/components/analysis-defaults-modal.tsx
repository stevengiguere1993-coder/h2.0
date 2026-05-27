"use client";

import { useCallback, useEffect, useState } from "react";
import { Loader2, Save, Settings2, X } from "lucide-react";

import { authedFetch } from "@/lib/auth";

/**
 * Modal de modification des valeurs par défaut globales pour les
 * inputs manuels du calculateur d'analyse financière.
 *
 * Phil veut pouvoir changer le taux d'intérêt refi par défaut (par
 * exemple 3.75 % → 4 %) ou le pourcentage de MDF prêteur B sans
 * devoir éditer le code. Quand un défaut est modifié, les nouvelles
 * analyses créées après le changement utilisent la nouvelle valeur.
 * Les analyses existantes ne sont PAS écrasées.
 *
 * Restreint à admin/owner (backend renvoie 403 sinon).
 */

export type AnalysisDefaultGroup = "refi" | "mdf";

type AnalysisDefault = {
  id: number;
  key: string;
  value_float: number | null;
  label_fr: string;
  description_fr: string | null;
  min_value: number | null;
  max_value: number | null;
  step: number;
  group: string | null;
};

export function AnalysisDefaultsModal({
  open,
  onClose,
  group,
  onSaved
}: {
  open: boolean;
  onClose: () => void;
  /** Filtre les défauts affichés. Le bouton de la section "Inputs
   *  manuels" passe "refi", celui de "Composition MDF" passe "mdf". */
  group: AnalysisDefaultGroup;
  /** Callback appelé après un save réussi (pour rafraîchir l'UI
   *  côté parent si nécessaire). */
  onSaved?: () => void;
}) {
  const [defaults, setDefaults] = useState<AnalysisDefault[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [savingKey, setSavingKey] = useState<string | null>(null);
  // Brouillon des valeurs en cours d'édition (string pour permettre
  // les états transitoires comme "3." ou vide pendant la saisie).
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [savedKey, setSavedKey] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const r = await authedFetch(
        `/api/v1/prospection/analysis-defaults?group=${encodeURIComponent(group)}`
      );
      if (r.status === 403) {
        throw new Error("Accès réservé aux administrateurs.");
      }
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const j = (await r.json()) as AnalysisDefault[];
      setDefaults(j);
      // Initialise le brouillon avec les valeurs actuelles (en %).
      const d: Record<string, string> = {};
      for (const def of j) {
        d[def.key] = def.value_float != null ? String(def.value_float) : "";
      }
      setDrafts(d);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, [group]);

  useEffect(() => {
    if (!open) return;
    void load();
  }, [open, load]);

  async function save(def: AnalysisDefault) {
    setSavingKey(def.key);
    setError(null);
    try {
      const raw = drafts[def.key];
      const num = Number(raw);
      if (!Number.isFinite(num)) {
        throw new Error("Valeur invalide.");
      }
      const r = await authedFetch(
        `/api/v1/prospection/analysis-defaults/${encodeURIComponent(def.key)}`,
        {
          method: "PATCH",
          body: JSON.stringify({ value_float: num })
        }
      );
      if (!r.ok) {
        const t = await r.text().catch(() => "");
        throw new Error(t.slice(0, 200) || `HTTP ${r.status}`);
      }
      const updated = (await r.json()) as AnalysisDefault;
      setDefaults((prev) =>
        prev.map((d) => (d.key === updated.key ? updated : d))
      );
      setDrafts((prev) => ({
        ...prev,
        [updated.key]:
          updated.value_float != null ? String(updated.value_float) : ""
      }));
      setSavedKey(def.key);
      onSaved?.();
      // Efface le badge "enregistré" après 2s.
      setTimeout(() => setSavedKey(null), 2000);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSavingKey(null);
    }
  }

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
      <div className="w-full max-w-lg rounded-2xl border border-brand-700 bg-brand-900 shadow-2xl">
        <div className="flex items-center justify-between border-b border-brand-700 px-5 py-3">
          <div className="flex items-center gap-2">
            <Settings2 className="h-4 w-4 text-accent-500" />
            <h2 className="text-sm font-semibold text-white">
              Modifier les défauts globaux
            </h2>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md p-1 text-white/60 hover:bg-brand-800 hover:text-white"
            title="Fermer"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="px-5 py-4">
          <p className="text-[11px] text-white/60">
            Modifier un défaut change la valeur pré-remplie pour les
            <strong className="text-white"> nouvelles analyses</strong>{" "}
            uniquement. Les analyses existantes ne sont pas écrasées.
            L&apos;override par fiche reste toujours possible.
          </p>

          {loading ? (
            <div className="mt-4 flex items-center gap-2 text-xs text-white/60">
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
              Chargement…
            </div>
          ) : null}

          {error ? (
            <div className="mt-3 rounded-md border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-[11px] text-rose-300">
              {error}
            </div>
          ) : null}

          {!loading && defaults.length === 0 && !error ? (
            <p className="mt-3 text-xs text-white/40">
              Aucun défaut configurable pour cette section.
            </p>
          ) : null}

          <div className="mt-3 space-y-3">
            {defaults.map((def) => {
              const saving = savingKey === def.key;
              const saved = savedKey === def.key;
              const draft = drafts[def.key] ?? "";
              const draftNum = Number(draft);
              const dirty =
                Number.isFinite(draftNum) &&
                Math.abs(draftNum - (def.value_float ?? 0)) > 1e-9;
              return (
                <div
                  key={def.key}
                  className="rounded-lg border border-brand-700 bg-brand-950/60 px-3 py-2"
                >
                  <label className="block text-[11px] font-semibold text-white/80">
                    {def.label_fr}
                  </label>
                  {def.description_fr ? (
                    <p className="mt-0.5 text-[10px] text-white/50">
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
                      onChange={(e) =>
                        setDrafts((p) => ({ ...p, [def.key]: e.target.value }))
                      }
                      className="input flex-1 font-mono text-xs"
                      disabled={saving}
                    />
                    <span className="text-[10px] text-white/40">%</span>
                    <button
                      type="button"
                      onClick={() => void save(def)}
                      disabled={!dirty || saving}
                      className="inline-flex items-center gap-1 rounded-md border border-emerald-500/40 bg-emerald-500/15 px-2 py-1 text-[11px] font-semibold text-emerald-300 hover:bg-emerald-500/25 disabled:cursor-not-allowed disabled:opacity-40"
                    >
                      {saving ? (
                        <Loader2 className="h-3 w-3 animate-spin" />
                      ) : (
                        <Save className="h-3 w-3" />
                      )}
                      Enregistrer
                    </button>
                  </div>
                  {saved ? (
                    <p className="mt-1 text-[10px] text-emerald-400">
                      ✓ Défaut mis à jour.
                    </p>
                  ) : null}
                </div>
              );
            })}
          </div>
        </div>

        <div className="flex justify-end gap-2 border-t border-brand-700 px-5 py-3">
          <button
            type="button"
            onClick={onClose}
            className="rounded-md border border-brand-700 px-3 py-1 text-xs text-white/70 hover:bg-brand-800"
          >
            Fermer
          </button>
        </div>
      </div>
    </div>
  );
}
