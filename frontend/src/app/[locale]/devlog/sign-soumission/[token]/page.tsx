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
  Loader2,
  Sparkles,
  XCircle
} from "lucide-react";
import {
  SoumissionClientView,
  type SoumissionClientViewData
} from "@/components/devlog/SoumissionClientView";

// La structure du devis client (modules + totaux) est partagée avec
// l'éditeur admin via le composant <SoumissionClientView>. On réutilise
// directement son type pour garantir l'égalité parfaite des deux rendus.
type DevisPreview = SoumissionClientViewData;

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

          {/* Affichage client PARTAGÉ avec la « Vue client » de
              l'éditeur admin. Le composant <SoumissionClientView> rend
              les sections « Frais mensuels récurrents » + « Investissement
              initial » (modules, « Inclus gratuitement », totaux). Ici en
              mode INTERACTIF : la sélection des modules + le recalcul live
              sont pilotés par cette page (selectedIds / toggleModule). */}
          <SoumissionClientView
            devis={data.devis}
            selectedIds={selectedIds}
            onToggleModule={toggleModule}
            disableToggles={alreadyDone}
            recalculating={recalculating}
          />

          {/* Lien PDF */}
          <div className="mt-6">
            <a
              href={`/api/v1/public/devlog/soumissions/${token}/pdf${
                selectedIds
                  ? `?selected=${Array.from(selectedIds).join(",")}`
                  : ""
              }`}
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
