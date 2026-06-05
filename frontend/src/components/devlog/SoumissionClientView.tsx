"use client";

/**
 * Vue client PARTAGÉE d'une soumission devis_dev.
 *
 * Rendu de référence : la page publique de signature
 * (`/devlog/sign-soumission/[token]`). Ce composant factorise le bloc
 * d'AFFICHAGE côté client pour qu'il soit STRICTEMENT identique entre :
 *   1. la page publique (mode interactif — cases à cocher + recalcul) ;
 *   2. la « Vue client » de l'éditeur admin (mode aperçu, lecture seule).
 *
 * Le composant est PUREMENT présentationnel : il reçoit en props les
 * données DÉJÀ calculées (structure modules + totaux issus de
 * `compute_devis`), sans aucune logique réseau ni de signature. La
 * sélection interactive (cases à cocher + recalcul live) reste gérée par
 * le parent (page publique) via les props optionnelles `selectedIds` /
 * `onToggleModule`. En mode aperçu (éditeur), on n'envoie pas ces props :
 * les modules s'affichent en lecture seule, cases pré-cochées selon
 * l'état persisté (`selected`).
 *
 * ⚠️ Vue CLIENT uniquement — aucun coût interne, aucune marge, aucun
 * taux horaire, aucune heure. Les données fournies doivent déjà être
 * filtrées (cf. PublicDevisPreview côté backend).
 *
 * Rétrocompat : une soumission SANS modules retombe sur le rendu plat
 * (liste features / frais fixes), identique au mode legacy historique.
 */

import { Gift, Loader2, Repeat, Sparkles } from "lucide-react";

export type ClientRecurringItem = {
  description: string;
};

export type ClientFeature = {
  description: string;
  prix_client: number;
};

export type ClientFraisFixe = {
  description: string;
  prix_client: number;
};

export type ClientModuleFeature = {
  description: string;
  prix_client: number;
};

export type ClientModule = {
  id: number;
  name: string;
  selected: boolean;
  optional: boolean;
  offert: boolean;
  free_when_module_id: number | null;
  prix_client: number;
  features: ClientModuleFeature[];
};

export type ClientRecurringBlock = {
  total_client_amount: number; // HT (sous-total mensuel)
  items: ClientRecurringItem[];
  description: string | null;
  tps_amount: number;
  tvq_amount: number;
  tps_pct: number;
  tvq_pct: number;
  total_client_amount_taxe: number; // TTC mensuel
};

export type ClientInitialBlock = {
  features: ClientFeature[];
  frais_fixes: ClientFraisFixe[];
  total_final: number; // HT (sous-total initial)
  tps_amount: number;
  tvq_amount: number;
  tps_pct: number;
  tvq_pct: number;
  total_final_taxe: number; // TTC initial
  modules?: ClientModule[];
  has_modules?: boolean;
  /**
   * Fonctionnalités DIRECTES (hors module) — items `feature` sans
   * `module_id`. Elles font partie de l'investissement initial et ont un
   * prix, mais n'appartiennent à aucun module sélectionnable. En mode
   * modules, le bloc plat `features` n'est pas rendu : on affiche ces
   * fonctionnalités directes dans un bloc dédié « Autres fonctionnalités
   * (hors module) » pour qu'elles restent visibles côté client.
   */
  direct_features?: ClientFeature[];
};

export type SoumissionClientViewData = {
  recurring: ClientRecurringBlock;
  initial: ClientInitialBlock;
};

function fmtMoney(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  return n.toLocaleString("fr-CA", {
    style: "currency",
    currency: "CAD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2
  });
}

export function SoumissionClientView({
  devis,
  selectedIds,
  onToggleModule,
  disableToggles = false,
  recalculating = false
}: {
  /** Données client déjà calculées (structure modules + totaux). */
  devis: SoumissionClientViewData;
  /**
   * Sélection interactive des modules (page publique). Si fourni,
   * pilote l'état coché des cases ; sinon on retombe sur `m.selected`.
   */
  selectedIds?: Set<number> | null;
  /** Handler de bascule d'un module (page publique uniquement). */
  onToggleModule?: (id: number) => void;
  /**
   * Désactive toutes les cases (aperçu lecture seule de l'éditeur, ou
   * soumission déjà signée côté public).
   */
  disableToggles?: boolean;
  /** Affiche l'indicateur « Mise à jour du total… » pendant un recalcul. */
  recalculating?: boolean;
}) {
  const rec = devis.recurring;
  const init = devis.initial;

  const monthlyTTC = rec.total_client_amount_taxe || 0;
  const monthlyHT = rec.total_client_amount || 0;
  const hasRecurring = monthlyHT > 0 || (rec.items || []).length > 0;

  const features = init.features || [];
  const fraisFixes = init.frais_fixes || [];
  const initialHT = init.total_final || 0;
  const initialTTC = init.total_final_taxe || 0;
  // Fonctionnalités directes (hors module) — montrées en mode modules
  // dans un bloc dédié (en mode legacy elles sont déjà dans `features`).
  const directFeatures = init.direct_features || [];

  // Mode modules : sélection interactive. Sinon, vue plate (legacy).
  const modules = init.modules || [];
  const hasModules = Boolean(init.has_modules) && modules.length > 0;
  // Modules « offerts » (gratuité « module → module » déclenchée).
  const offeredModules = modules.filter((m) => m.offert);
  // Modules à proposer en sélection (on retire les offerts, montrés à
  // part dans « Inclus gratuitement »).
  const selectableModules = modules.filter((m) => !m.offert);
  // Nom du module déclencheur d'une gratuité (free_when_module_id), pour
  // afficher « Si le module "<nom>" est sélectionné ».
  const triggerModuleName = (id: number | null): string | null => {
    if (id === null || id === undefined) return null;
    const trigger = modules.find((mod) => mod.id === id);
    return trigger ? trigger.name : null;
  };
  const hasInitial =
    features.length > 0 ||
    fraisFixes.length > 0 ||
    initialHT > 0 ||
    hasModules;

  return (
    <>
      {/* Section 1 — Frais mensuels récurrents (vert / emerald) */}
      {hasRecurring ? (
        <section className="mt-6">
          <div className="flex items-center gap-2">
            <Repeat className="h-4 w-4 text-emerald-700" />
            <h2 className="text-xs font-semibold uppercase tracking-wider text-emerald-700">
              Frais mensuels récurrents
            </h2>
          </div>
          {/* Grand cartouche prix TTC */}
          <div className="mt-2 rounded-2xl border-2 border-emerald-300 bg-emerald-50 p-6 text-center shadow-sm">
            <p className="text-xs font-semibold uppercase tracking-wider text-emerald-700">
              Total mensuel taxes incluses
            </p>
            <p className="mt-1 text-4xl font-extrabold text-emerald-700 sm:text-5xl">
              {fmtMoney(monthlyTTC)}
            </p>
            <p className="mt-1 text-sm font-medium text-emerald-700">
              par mois
            </p>
          </div>
          {/* Inclusions */}
          {rec.description ? (
            <p className="mt-4 text-sm text-slate-700">{rec.description}</p>
          ) : rec.items.length > 0 ? (
            <div className="mt-4">
              <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">
                Inclut
              </p>
              <ul className="mt-1 space-y-1 text-sm text-slate-700">
                {rec.items.map((it, idx) => (
                  <li key={idx} className="flex items-start gap-2">
                    <span className="mt-1.5 inline-block h-1.5 w-1.5 flex-shrink-0 rounded-full bg-emerald-500" />
                    <span>{it.description}</span>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
          {/* Détail taxes */}
          {monthlyHT > 0 ? (
            <div className="mt-4 overflow-hidden rounded-xl border border-emerald-200 bg-white">
              <table className="w-full text-sm">
                <tbody className="divide-y divide-emerald-100">
                  <tr>
                    <td className="px-4 py-2 text-slate-700">
                      Sous-total mensuel
                    </td>
                    <td className="px-4 py-2 text-right text-slate-800">
                      {fmtMoney(monthlyHT)}
                    </td>
                  </tr>
                  <tr>
                    <td className="px-4 py-2 text-slate-700">
                      TPS ({rec.tps_pct}%)
                    </td>
                    <td className="px-4 py-2 text-right text-slate-800">
                      {fmtMoney(rec.tps_amount)}
                    </td>
                  </tr>
                  <tr>
                    <td className="px-4 py-2 text-slate-700">
                      TVQ ({rec.tvq_pct}%)
                    </td>
                    <td className="px-4 py-2 text-right text-slate-800">
                      {fmtMoney(rec.tvq_amount)}
                    </td>
                  </tr>
                </tbody>
                <tfoot className="bg-emerald-50">
                  <tr>
                    <td className="px-4 py-3 text-sm font-bold text-emerald-900">
                      Total mensuel TTC
                    </td>
                    <td className="px-4 py-3 text-right text-base font-bold text-emerald-900">
                      {fmtMoney(monthlyTTC)}
                    </td>
                  </tr>
                </tfoot>
              </table>
            </div>
          ) : null}
        </section>
      ) : null}

      {/* Section 2 — Investissement initial (bleu) */}
      {hasInitial ? (
        <section className="mt-8">
          <div className="flex items-center gap-2">
            <Sparkles className="h-4 w-4 text-blue-700" />
            <h2 className="text-xs font-semibold uppercase tracking-wider text-blue-700">
              Investissement initial
            </h2>
          </div>
          {/* Grand cartouche prix TTC */}
          <div className="mt-2 rounded-2xl border-2 border-blue-300 bg-blue-50 p-6 text-center shadow-sm">
            <p className="text-xs font-semibold uppercase tracking-wider text-blue-700">
              Total taxes incluses
            </p>
            <p className="mt-1 text-4xl font-extrabold text-blue-700 sm:text-5xl">
              {fmtMoney(initialTTC)}
            </p>
            <p className="mt-1 text-sm font-medium text-blue-700">
              paiement unique
            </p>
            {recalculating ? (
              <p className="mt-2 inline-flex items-center gap-1 text-xs font-medium text-blue-600">
                <Loader2 className="h-3 w-3 animate-spin" />
                Mise à jour du total…
              </p>
            ) : null}
          </div>

          {/* Mode MODULES : sélection (interactive côté public, lecture
              seule en aperçu éditeur) */}
          {hasModules ? (
            <>
              <p className="mt-4 text-sm text-slate-600">
                Personnalisez votre projet : cochez les modules
                souhaités. Le total se met à jour automatiquement.
              </p>
              <div className="mt-3 space-y-3">
                {selectableModules.map((m) => {
                  const checked = selectedIds
                    ? selectedIds.has(m.id)
                    : m.selected;
                  return (
                    <div
                      key={`mod-${m.id}`}
                      className={`overflow-hidden rounded-xl border transition ${
                        checked
                          ? "border-blue-300 bg-white"
                          : "border-slate-200 bg-slate-50"
                      }`}
                    >
                      <label className="flex cursor-pointer items-start gap-3 p-4">
                        <input
                          type="checkbox"
                          checked={checked}
                          disabled={!m.optional || disableToggles}
                          onChange={() => onToggleModule?.(m.id)}
                          className="mt-1 h-5 w-5 flex-shrink-0 rounded border-slate-300 text-blue-600 focus:ring-blue-500 disabled:opacity-50"
                        />
                        <div className="min-w-0 flex-1">
                          <div className="flex items-baseline justify-between gap-3">
                            <span className="text-sm font-bold text-slate-900">
                              {m.name}
                            </span>
                            <span className="flex-shrink-0 text-sm font-bold text-blue-700">
                              {fmtMoney(m.prix_client)}
                            </span>
                          </div>
                          {m.features.length > 0 ? (
                            <ul className="mt-2 space-y-1">
                              {m.features.map((feat, fi) => (
                                <li
                                  key={`mf-${m.id}-${fi}`}
                                  className="flex items-start gap-2 text-sm text-slate-600"
                                >
                                  <span className="mt-1.5 inline-block h-1.5 w-1.5 flex-shrink-0 rounded-full bg-blue-400" />
                                  <span>{feat.description || "—"}</span>
                                </li>
                              ))}
                            </ul>
                          ) : null}
                        </div>
                      </label>
                    </div>
                  );
                })}
              </div>

              {/* Section « Inclus gratuitement » */}
              {offeredModules.length > 0 ? (
                <div className="mt-4">
                  <div className="flex items-center gap-2">
                    <Gift className="h-4 w-4 text-emerald-700" />
                    <h3 className="text-xs font-semibold uppercase tracking-wider text-emerald-700">
                      Inclus gratuitement
                    </h3>
                  </div>
                  <div className="mt-2 space-y-3">
                    {offeredModules.map((m) => {
                      const triggerName = triggerModuleName(
                        m.free_when_module_id
                      );
                      return (
                        <div
                          key={`free-${m.id}`}
                          className="overflow-hidden rounded-xl border border-emerald-200 bg-emerald-50 p-4"
                        >
                          <div className="flex items-baseline justify-between gap-3">
                            <span className="text-sm font-bold text-emerald-900">
                              {m.name}
                            </span>
                            <span className="flex-shrink-0 rounded-full bg-emerald-600 px-2 py-0.5 text-xs font-bold text-white">
                              Offert
                            </span>
                          </div>
                          {triggerName ? (
                            <p className="mt-1 text-xs font-medium italic text-emerald-700">
                              (Si le module &laquo;&nbsp;{triggerName}&nbsp;&raquo; est
                              sélectionné)
                            </p>
                          ) : null}
                          {m.features.length > 0 ? (
                            <ul className="mt-2 space-y-1">
                              {m.features.map((feat, fi) => (
                                <li
                                  key={`free-f-${m.id}-${fi}`}
                                  className="flex items-start gap-2 text-sm text-emerald-800"
                                >
                                  <span className="mt-1.5 inline-block h-1.5 w-1.5 flex-shrink-0 rounded-full bg-emerald-500" />
                                  <span>{feat.description || "—"}</span>
                                </li>
                              ))}
                            </ul>
                          ) : null}
                          <p className="mt-2 text-right text-sm font-bold text-emerald-700">
                            {fmtMoney(0)}
                          </p>
                        </div>
                      );
                    })}
                  </div>
                </div>
              ) : null}

              {/* Autres fonctionnalités (hors module) — fonctionnalités
                  directes, toujours incluses dans l'investissement
                  initial (non décochables, pas rattachées à un module).
                  Côté client, on liste les NOMS sans prix individuel
                  (comme les modules) et on n'affiche qu'UN SEUL total pour
                  tout le bloc. */}
              {directFeatures.length > 0 ? (
                <div className="mt-4 overflow-hidden rounded-xl border border-slate-200 bg-white">
                  <div className="p-4">
                    <div className="flex items-baseline justify-between gap-3">
                      <span className="text-sm font-bold text-slate-900">
                        Autres fonctionnalités
                      </span>
                      <span className="flex-shrink-0 text-sm font-bold text-blue-700">
                        {fmtMoney(
                          directFeatures.reduce(
                            (acc, feat) => acc + (feat.prix_client || 0),
                            0
                          )
                        )}
                      </span>
                    </div>
                    <ul className="mt-2 space-y-1">
                      {directFeatures.map((feat, idx) => (
                        <li
                          key={`direct-${idx}`}
                          className="flex items-start gap-2 text-sm text-slate-600"
                        >
                          <span className="mt-1.5 inline-block h-1.5 w-1.5 flex-shrink-0 rounded-full bg-blue-400" />
                          <span>{feat.description || "—"}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                </div>
              ) : null}

              {/* Récap taxes (mode modules) */}
              <div className="mt-4 overflow-hidden rounded-xl border border-blue-200 bg-white">
                <table className="w-full text-sm">
                  <tbody className="divide-y divide-slate-200">
                    <tr>
                      <td className="px-4 py-2 font-semibold text-slate-800">
                        Sous-total
                      </td>
                      <td className="px-4 py-2 text-right font-semibold text-slate-800">
                        {fmtMoney(initialHT)}
                      </td>
                    </tr>
                    <tr>
                      <td className="px-4 py-2 text-slate-700">
                        TPS ({init.tps_pct}%)
                      </td>
                      <td className="px-4 py-2 text-right text-slate-800">
                        {fmtMoney(init.tps_amount)}
                      </td>
                    </tr>
                    <tr>
                      <td className="px-4 py-2 text-slate-700">
                        TVQ ({init.tvq_pct}%)
                      </td>
                      <td className="px-4 py-2 text-right text-slate-800">
                        {fmtMoney(init.tvq_amount)}
                      </td>
                    </tr>
                  </tbody>
                  <tfoot className="bg-blue-50">
                    <tr>
                      <td className="px-4 py-3 text-sm font-bold text-blue-900">
                        Total TTC
                      </td>
                      <td className="px-4 py-3 text-right text-base font-bold text-blue-900">
                        {fmtMoney(initialTTC)}
                      </td>
                    </tr>
                  </tfoot>
                </table>
              </div>
            </>
          ) : (
            /* Détail features + frais fixes + récap taxes (mode legacy) */
            <div className="mt-4 overflow-hidden rounded-xl border border-blue-200 bg-white">
              <table className="w-full text-sm">
                <thead className="bg-slate-100">
                  <tr>
                    <th className="px-4 py-2 text-left font-semibold text-slate-700">
                      Description
                    </th>
                    <th className="px-4 py-2 text-right font-semibold text-slate-700">
                      Montant
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-200">
                  {features.map((feat, idx) => (
                    <tr key={`feat-${idx}`}>
                      <td className="px-4 py-2 text-slate-800">
                        {feat.description || "—"}
                      </td>
                      <td className="px-4 py-2 text-right text-slate-800">
                        {fmtMoney(feat.prix_client)}
                      </td>
                    </tr>
                  ))}
                  {fraisFixes.length > 0 ? (
                    <tr className="bg-slate-50">
                      <td
                        colSpan={2}
                        className="px-4 py-2 text-xs font-semibold uppercase tracking-wider text-slate-600"
                      >
                        Frais fixes
                      </td>
                    </tr>
                  ) : null}
                  {fraisFixes.map((ff, idx) => (
                    <tr key={`ff-${idx}`}>
                      <td className="px-4 py-2 text-slate-800">
                        {ff.description || "—"}
                      </td>
                      <td className="px-4 py-2 text-right text-slate-800">
                        {fmtMoney(ff.prix_client)}
                      </td>
                    </tr>
                  ))}
                  {/* Sous-total + taxes */}
                  <tr className="border-t-2 border-blue-200">
                    <td className="px-4 py-2 font-semibold text-slate-800">
                      Sous-total
                    </td>
                    <td className="px-4 py-2 text-right font-semibold text-slate-800">
                      {fmtMoney(initialHT)}
                    </td>
                  </tr>
                  <tr>
                    <td className="px-4 py-2 text-slate-700">
                      TPS ({init.tps_pct}%)
                    </td>
                    <td className="px-4 py-2 text-right text-slate-800">
                      {fmtMoney(init.tps_amount)}
                    </td>
                  </tr>
                  <tr>
                    <td className="px-4 py-2 text-slate-700">
                      TVQ ({init.tvq_pct}%)
                    </td>
                    <td className="px-4 py-2 text-right text-slate-800">
                      {fmtMoney(init.tvq_amount)}
                    </td>
                  </tr>
                </tbody>
                <tfoot className="bg-blue-50">
                  <tr>
                    <td className="px-4 py-3 text-sm font-bold text-blue-900">
                      Total TTC
                    </td>
                    <td className="px-4 py-3 text-right text-base font-bold text-blue-900">
                      {fmtMoney(initialTTC)}
                    </td>
                  </tr>
                </tfoot>
              </table>
            </div>
          )}
        </section>
      ) : null}
    </>
  );
}

