"use client";

import { useCallback, useEffect, useState } from "react";
import { Loader2, Save, Settings2, X } from "lucide-react";

import { authedFetch } from "@/lib/auth";

/**
 * Modal de modification des valeurs par défaut globales pour les
 * inputs manuels et frais MDF du calculateur d'analyse financière.
 *
 * Phil veut pouvoir changer le taux d'intérêt refi par défaut (par
 * exemple 3.75 % → 4 %), le pourcentage de MDF prêteur B, OU le
 * montant des frais one-shot (Évaluateur, Notaire, Inspection, etc.)
 * sans devoir éditer le code. Quand un défaut est modifié, les
 * nouvelles analyses créées après le changement utilisent la nouvelle
 * valeur. Les analyses existantes ne sont PAS écrasées.
 *
 * Restreint à admin/owner (backend renvoie 403 sinon).
 *
 * Groupes :
 *   - inputs_manuels : taux refi, MDF %, taux prêteur B, TGA, durée
 *                      projet, réduction énergie, etc.
 *   - mdf_frais      : Évaluateur 1/2, Inspection, Notaire 1/2,
 *                      Avocat, Rapport efficacité, % courtiers.
 *
 * Convention pour l'unité affichée : si ``step < 1``, on suppose un
 * pourcentage (affiche « % » à droite) ; sinon on suppose un montant
 * en dollars (affiche « $ »). Les défauts entiers comme « durée
 * projet (années) » utilisent step = 1, donc affichés en « $ »
 * implicitement — c'est OK puisqu'il n'y a pas d'unité native, et le
 * label_fr clarifie déjà (« (années) »).
 */

export type AnalysisDefaultGroup = "inputs_manuels" | "mdf_frais";

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
  // Mai 2026 : statut "finançable par défaut". Pré-coche la case
  // "Finançable" sur les nouvelles fiches d'analyse pour les items
  // des groupes mdf_frais / mdf_pct. Null = non applicable.
  financable_par_defaut: boolean | null;
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

  // Mai 2026 : toggle du flag "finançable par défaut" sur un item MDF.
  // PATCH dédié (champ unique) — pas besoin de bouton Enregistrer, le
  // changement est immédiat.
  async function toggleFinancable(def: AnalysisDefault, next: boolean) {
    setError(null);
    // Optimistic update — on remettra en sync via la réponse serveur.
    setDefaults((prev) =>
      prev.map((d) =>
        d.key === def.key ? { ...d, financable_par_defaut: next } : d
      )
    );
    try {
      const r = await authedFetch(
        `/api/v1/prospection/analysis-defaults/${encodeURIComponent(def.key)}`,
        {
          method: "PATCH",
          body: JSON.stringify({ financable_par_defaut: next })
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
      onSaved?.();
    } catch (e) {
      // Rollback — on remet l'ancienne valeur.
      setDefaults((prev) =>
        prev.map((d) =>
          d.key === def.key ? { ...d, financable_par_defaut: !next } : d
        )
      );
      setError((e as Error).message);
    }
  }

  if (!open) return null;

  // Titre dynamique selon le groupe affiché.
  const modalTitle =
    group === "mdf_frais"
      ? "Modifier les défauts des frais MDF"
      : "Modifier les défauts des inputs manuels";

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
      <div className="flex max-h-[90vh] w-full max-w-xl flex-col rounded-2xl border border-brand-700 bg-brand-900 shadow-2xl">
        <div className="flex items-center justify-between border-b border-brand-700 px-5 py-3">
          <div className="flex items-center gap-2">
            <Settings2 className="h-4 w-4 text-accent-500" />
            <h2 className="text-sm font-semibold text-white">
              {modalTitle}
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

        <div className="overflow-y-auto px-5 py-4">
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
              // Unité affichée à droite de l'input :
              //   - step < 1     → pourcentage (%)
              //   - step >= 1 et clé commence par "frais_" / "pct_" → $
              //   - sinon (durée projet années, nb log, etc.) → pas
              //     d'unité (le label_fr clarifie déjà).
              const isPct = def.step < 1 && !def.key.startsWith("pct_");
              const isMoney =
                def.key.startsWith("frais_") ||
                (def.step >= 1 &&
                  !def.key.includes("annees") &&
                  !def.key.includes("nb_") &&
                  !def.key.includes("logements") &&
                  !def.key.includes("thermopompes") &&
                  !def.key.includes("pct"));
              const isPctCourtier = def.key.startsWith("pct_");
              const unit = isPct || isPctCourtier ? "%" : isMoney ? "$" : "";
              // Mai 2026 : le toggle "finançable par défaut" est
              // affiché uniquement pour le groupe `mdf_frais` (qui
              // contient les frais MDF et % courtiers — tout ce qui
              // peut être financé par le prêteur B). Pour les autres
              // groupes (`inputs_manuels`), la notion n'a pas de sens.
              const showFinancableToggle = def.group === "mdf_frais";
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
                    {unit ? (
                      <span className="text-[10px] text-white/40">{unit}</span>
                    ) : null}
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
                  {showFinancableToggle ? (
                    <label className="mt-2 flex cursor-pointer items-center gap-2 text-[10px] text-white/70">
                      <input
                        type="checkbox"
                        checked={!!def.financable_par_defaut}
                        onChange={(e) =>
                          void toggleFinancable(def, e.target.checked)
                        }
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


