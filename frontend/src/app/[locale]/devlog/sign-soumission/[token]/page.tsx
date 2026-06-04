"use client";

/**
 * Page publique de signature d'une soumission devis_dev.
 *
 * URL : /devlog/sign-soumission/[token]
 * Pas d'authentification — le token (32 octets URL-safe) authentifie
 * le destinataire et sert d'audit trail (IP capturée serveur).
 *
 * Refonte mai 2026 (#496) : UX inspirée de la vue client interne
 * (`dev-logiciel/soumissions/[id]`). Pour CHAQUE bloc (récurrent +
 * investissement initial) on affiche un grand cartouche avec le prix
 * TTC en gros, puis le détail sous-total / TPS / TVQ / total TTC.
 *
 * ⚠️ Vue client uniquement — aucun coût interne, aucune marge, aucun
 * taux horaire, aucune heure. Le payload servi par
 * /api/v1/public/devlog/soumissions/{token} est déjà filtré côté
 * backend (PublicDevisPreview).
 */

import { useCallback, useEffect, useState } from "react";
import { useParams } from "next/navigation";
import {
  CheckCircle2,
  Download,
  FileText,
  Gift,
  Loader2,
  Repeat,
  Sparkles,
  XCircle
} from "lucide-react";

type RecurringItem = {
  description: string;
};

type FeatureClient = {
  description: string;
  prix_client: number;
};

type FraisFixeClient = {
  description: string;
  prix_client: number;
};

type ModuleFeature = {
  description: string;
  prix_client: number;
};

type SoumissionModule = {
  id: number;
  name: string;
  selected: boolean;
  optional: boolean;
  offert: boolean;
  free_when_module_id: number | null;
  prix_client: number;
  features: ModuleFeature[];
};

type DevisPreview = {
  recurring: {
    total_client_amount: number; // HT (sous-total mensuel)
    items: RecurringItem[];
    description: string | null;
    tps_amount: number;
    tvq_amount: number;
    tps_pct: number;
    tvq_pct: number;
    total_client_amount_taxe: number; // TTC mensuel
  };
  initial: {
    features: FeatureClient[];
    frais_fixes: FraisFixeClient[];
    total_final: number; // HT (sous-total initial)
    tps_amount: number;
    tvq_amount: number;
    tps_pct: number;
    tvq_pct: number;
    total_final_taxe: number; // TTC initial
    modules?: SoumissionModule[];
    has_modules?: boolean;
  };
};

type PublicSoumission = {
  id: number;
  status: string;
  title: string;
  client_name: string | null;
  client_address: string | null;
  sent_at: string | null;
  signed_at: string | null;
  signed_name: string | null;
  devis: DevisPreview;
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

function fmtDate(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("fr-CA", {
    day: "numeric",
    month: "long",
    year: "numeric"
  });
}

export default function SignSoumissionPage() {
  const params = useParams<{ token: string }>();
  const token = params.token;

  const [data, setData] = useState<PublicSoumission | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [signedName, setSignedName] = useState("");
  const [submitting, setSubmitting] = useState<"accept" | "reject" | null>(
    null
  );
  const [doneMessage, setDoneMessage] = useState<string | null>(null);
  // Sélection interactive des modules (Phase 4). null tant que la
  // soumission n'est pas chargée ; ensuite Set des ids cochés.
  const [selectedIds, setSelectedIds] = useState<Set<number> | null>(null);
  const [recalculating, setRecalculating] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(
        `/api/v1/public/devlog/soumissions/${token}`,
        { cache: "no-store" }
      );
      if (!res.ok) throw new Error(`http_${res.status}`);
      const json = (await res.json()) as PublicSoumission;
      setData(json);
      // État initial des cases à cocher = état persisté côté serveur.
      const mods = json.devis?.initial?.modules || [];
      if (mods.length > 0) {
        setSelectedIds(
          new Set(mods.filter((m) => m.selected).map((m) => m.id))
        );
      } else {
        setSelectedIds(null);
      }
    } catch {
      setError("Lien invalide ou expiré.");
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => {
    if (token) void load();
  }, [token, load]);

  // Recalcul en direct : à chaque changement de sélection, on demande
  // au backend les totaux recalculés (sans persister). Le serveur fait
  // foi pour le calcul (gratuité « module → module », taxes, etc.).
  const recalc = useCallback(
    async (ids: Set<number>) => {
      setRecalculating(true);
      try {
        const res = await fetch(
          `/api/v1/public/devlog/soumissions/${token}/preview`,
          {
            method: "POST",
            headers: { "content-type": "application/json" },
            body: JSON.stringify({ selected_module_ids: Array.from(ids) })
          }
        );
        if (res.ok) {
          setData((await res.json()) as PublicSoumission);
        }
      } catch {
        // silencieux : on garde l'affichage courant
      } finally {
        setRecalculating(false);
      }
    },
    [token]
  );

  function toggleModule(id: number) {
    setSelectedIds((prev) => {
      const base = prev ? new Set(prev) : new Set<number>();
      if (base.has(id)) base.delete(id);
      else base.add(id);
      void recalc(base);
      return base;
    });
  }

  async function submit(accept: boolean) {
    if (submitting) return;
    if (!signedName.trim() || signedName.trim().length < 2) {
      setError("Veuillez entrer votre nom complet (au moins 2 caractères).");
      return;
    }
    setSubmitting(accept ? "accept" : "reject");
    setError(null);
    try {
      const res = await fetch(
        `/api/v1/public/devlog/soumissions/${token}/sign`,
        {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({
            signed_name: signedName.trim(),
            accept,
            // Sélection finale du client (null => soumission sans
            // modules : le backend ignore ce champ, rétrocompat).
            selected_module_ids: selectedIds
              ? Array.from(selectedIds)
              : null
          })
        }
      );
      if (!res.ok) {
        const t = await res.text();
        throw new Error(t.slice(0, 200) || `HTTP ${res.status}`);
      }
      const updated = (await res.json()) as PublicSoumission;
      setData(updated);
      setDoneMessage(
        accept
          ? "Merci, Horizon a été notifié de votre acceptation."
          : "Horizon a été notifié de votre refus."
      );
    } catch (e) {
      setError((e as Error).message || "Soumission échouée.");
    } finally {
      setSubmitting(null);
    }
  }

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-slate-50">
        <Loader2 className="h-6 w-6 animate-spin text-blue-600" />
      </div>
    );
  }

  if (error && !data) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-slate-50 p-6">
        <div className="max-w-md rounded-2xl border border-rose-200 bg-white p-6 text-center shadow">
          <XCircle className="mx-auto h-10 w-10 text-rose-500" />
          <h1 className="mt-3 text-lg font-bold text-slate-900">
            Lien invalide
          </h1>
          <p className="mt-2 text-sm text-slate-600">{error}</p>
        </div>
      </div>
    );
  }

  if (!data) return null;

  const alreadyDone =
    data.status === "acceptee" ||
    data.status === "refusee" ||
    Boolean(doneMessage);
  const accepted =
    data.status === "acceptee" || doneMessage?.includes("acceptation");

  const rec = data.devis.recurring;
  const init = data.devis.initial;
  const monthlyTTC = rec.total_client_amount_taxe || 0;
  const monthlyHT = rec.total_client_amount || 0;
  const hasRecurring = monthlyHT > 0 || (rec.items || []).length > 0;
  const features = init.features || [];
  const fraisFixes = init.frais_fixes || [];
  const initialHT = init.total_final || 0;
  const initialTTC = init.total_final_taxe || 0;
  // Mode modules (Phase 4) : sélection interactive. Sinon, vue legacy
  // (liste plate features / frais fixes — rétrocompat stricte).
  const modules = init.modules || [];
  const hasModules = Boolean(init.has_modules) && modules.length > 0;
  // Modules « offerts » (gratuité « module → module » déclenchée).
  const offeredModules = modules.filter((m) => m.offert);
  // Modules à proposer en sélection (on retire les offerts, montrés à
  // part dans « Inclus gratuitement »).
  const selectableModules = modules.filter((m) => !m.offert);
  // Nom du module déclencheur d'une gratuité (free_when_module_id), pour
  // afficher la condition « Si le module "<nom>" est sélectionné » dans
  // la section « Inclus gratuitement ».
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
    <div className="min-h-screen bg-slate-50 px-4 py-8">
      <div className="mx-auto max-w-3xl">
        <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm sm:p-8">
          {/* Header */}
          <div className="border-b border-slate-200 pb-5">
            <div className="flex items-center gap-2">
              <Sparkles className="h-5 w-5 text-blue-600" />
              <p className="text-xs font-semibold uppercase tracking-wider text-blue-700">
                Horizon Services Immobiliers &middot; Pôle Développement
                logiciel
              </p>
            </div>
            <h1 className="mt-2 text-3xl font-bold text-slate-900">
              Soumission #{data.id}
            </h1>
            <p className="mt-1 text-base text-slate-700">{data.title}</p>
            <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-slate-600">
              {data.client_name ? (
                <span>
                  <span className="font-semibold text-slate-700">
                    Client :
                  </span>{" "}
                  {data.client_name}
                  {data.client_address ? ` — ${data.client_address}` : ""}
                </span>
              ) : null}
              {data.sent_at ? (
                <span className="text-xs text-slate-500">
                  Envoyée le {fmtDate(data.sent_at)}
                </span>
              ) : null}
            </div>
          </div>

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
                <p className="mt-4 text-sm text-slate-700">
                  {rec.description}
                </p>
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

              {/* Mode MODULES (Phase 4) : sélection interactive */}
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
                              disabled={!m.optional || alreadyDone}
                              onChange={() => toggleModule(m.id)}
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

          {/* Lien PDF */}
          <div className="mt-6">
            <a
              href={`/api/v1/public/devlog/soumissions/${token}/pdf`}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-2 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50"
            >
              <Download className="h-4 w-4" />
              Télécharger la soumission en PDF
            </a>
          </div>

          {/* Zone signature / statut */}
          <div className="mt-6 border-t border-slate-200 pt-6">
            {alreadyDone ? (
              <div
                className={`rounded-lg border p-4 text-sm ${
                  accepted
                    ? "border-emerald-300 bg-emerald-50 text-emerald-900"
                    : "border-rose-300 bg-rose-50 text-rose-900"
                }`}
              >
                {accepted ? (
                  <CheckCircle2 className="mb-2 h-5 w-5 text-emerald-600" />
                ) : (
                  <XCircle className="mb-2 h-5 w-5 text-rose-600" />
                )}
                {doneMessage ||
                  (data.status === "acceptee"
                    ? `Soumission acceptée le ${fmtDate(
                        data.signed_at
                      )} par ${data.signed_name}.`
                    : `Soumission refusée le ${fmtDate(
                        data.signed_at
                      )} par ${data.signed_name}.`)}
              </div>
            ) : (
              <>
                <h3 className="text-sm font-bold text-slate-900">
                  Votre réponse
                </h3>
                <p className="mt-1 text-xs text-slate-600">
                  En cliquant sur « J&apos;accepte », vous signez
                  électroniquement cette soumission. Un contrat détaillé
                  vous sera transmis pour finaliser les modalités
                  d&apos;exécution.
                </p>

                <label className="mt-4 block">
                  <span className="text-xs font-semibold uppercase tracking-wider text-slate-600">
                    Nom complet *
                  </span>
                  <input
                    type="text"
                    placeholder="Prénom Nom"
                    value={signedName}
                    onChange={(e) => setSignedName(e.target.value)}
                    className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 placeholder:text-slate-400 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                  />
                </label>

                {error ? (
                  <p className="mt-3 rounded-md border border-rose-300 bg-rose-50 px-3 py-2 text-sm text-rose-700">
                    {error}
                  </p>
                ) : null}

                <div className="mt-4 flex flex-col gap-2 sm:flex-row">
                  <button
                    type="button"
                    onClick={() => void submit(true)}
                    disabled={submitting !== null}
                    className="inline-flex flex-1 items-center justify-center gap-2 rounded-lg bg-emerald-600 px-4 py-3 text-sm font-bold text-white hover:bg-emerald-700 disabled:opacity-60"
                  >
                    {submitting === "accept" ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : (
                      <CheckCircle2 className="h-4 w-4" />
                    )}
                    J&apos;accepte cette soumission
                  </button>
                  <button
                    type="button"
                    onClick={() => void submit(false)}
                    disabled={submitting !== null}
                    className="inline-flex flex-1 items-center justify-center gap-2 rounded-lg border border-rose-300 bg-white px-4 py-3 text-sm font-bold text-rose-700 hover:bg-rose-50 disabled:opacity-60"
                  >
                    {submitting === "reject" ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : (
                      <XCircle className="h-4 w-4" />
                    )}
                    Je refuse
                  </button>
                </div>
              </>
            )}
          </div>

          <p className="mt-6 flex items-center justify-center gap-1 border-t border-slate-200 pt-4 text-center text-xs text-slate-500">
            <FileText className="h-3 w-3" />
            Horizon Services Immobiliers &middot; immohorizon.com
          </p>
        </div>
      </div>
    </div>
  );
}
