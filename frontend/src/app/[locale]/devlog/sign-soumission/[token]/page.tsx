"use client";

/**
 * Page publique de signature d'une soumission devis_dev.
 *
 * URL : /devlog/sign-soumission/[token]
 * Pas d'authentification — le token (32 octets URL-safe) authentifie
 * le destinataire et sert d'audit trail (IP capturée serveur).
 *
 * Thème clair (slate-50) — inspiré de /sign-offer/[token] (PR #445).
 *
 * ⚠️ Vue client uniquement — aucun coût interne, aucune marge, aucun
 * taux horaire, aucune heure. Le payload servi par
 * /api/v1/public/devlog/soumissions/{token} est déjà filtré côté
 * backend (PublicDevisPreview), on ne fait que l'afficher.
 */

import { useCallback, useEffect, useState } from "react";
import { useParams } from "next/navigation";
import {
  CheckCircle2,
  Download,
  FileText,
  Loader2,
  Repeat,
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

type DevisPreview = {
  recurring: {
    total_client_amount: number;
    items: RecurringItem[];
    description: string | null;
  };
  initial: {
    features: FeatureClient[];
    frais_fixes: FraisFixeClient[];
    total_final: number;
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

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(
        `/api/v1/public/devlog/soumissions/${token}`,
        { cache: "no-store" }
      );
      if (!res.ok) throw new Error(`http_${res.status}`);
      setData((await res.json()) as PublicSoumission);
    } catch {
      setError("Lien invalide ou expiré.");
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => {
    if (token) void load();
  }, [token, load]);

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
            accept
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

  const monthly = data.devis.recurring.total_client_amount || 0;
  const hasRecurring =
    monthly > 0 || (data.devis.recurring.items || []).length > 0;
  const features = data.devis.initial.features || [];
  const fraisFixes = data.devis.initial.frais_fixes || [];
  const totalInitial = data.devis.initial.total_final || 0;

  return (
    <div className="min-h-screen bg-slate-50 px-4 py-8">
      <div className="mx-auto max-w-2xl">
        <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm sm:p-8">
          {/* Header */}
          <div className="border-b border-slate-200 pb-4">
            <p className="text-xs font-semibold uppercase tracking-wider text-blue-700">
              Horizon Services Immobiliers &middot; Pôle Développement logiciel
            </p>
            <h1 className="mt-1 text-2xl font-bold text-slate-900">
              Soumission #{data.id}
            </h1>
            <p className="mt-1 text-sm text-slate-600">{data.title}</p>
            {data.client_name ? (
              <p className="mt-2 text-sm text-slate-700">
                <span className="font-semibold">Client :</span>{" "}
                {data.client_name}
                {data.client_address ? ` — ${data.client_address}` : ""}
              </p>
            ) : null}
            {data.sent_at ? (
              <p className="mt-1 text-xs text-slate-500">
                Envoyée le {fmtDate(data.sent_at)}
              </p>
            ) : null}
          </div>

          {/* Section 1 — Frais mensuels récurrents */}
          {hasRecurring ? (
            <section className="mt-5">
              <h2 className="text-xs font-semibold uppercase tracking-wider text-blue-700">
                Frais mensuels récurrents
              </h2>
              <div className="mt-2 rounded-xl border-2 border-blue-200 bg-blue-50 p-5 text-center">
                <Repeat className="mx-auto h-5 w-5 text-blue-600" />
                <p className="mt-1 text-2xl font-bold text-blue-700">
                  {fmtMoney(monthly)}{" "}
                  <span className="text-base font-normal text-blue-600">
                    / mois
                  </span>
                </p>
              </div>
              {data.devis.recurring.description ? (
                <p className="mt-3 text-sm text-slate-700">
                  {data.devis.recurring.description}
                </p>
              ) : data.devis.recurring.items.length > 0 ? (
                <ul className="mt-3 space-y-1 text-sm text-slate-700">
                  {data.devis.recurring.items.map((it, idx) => (
                    <li key={idx} className="flex items-start gap-2">
                      <span className="mt-1.5 inline-block h-1.5 w-1.5 flex-shrink-0 rounded-full bg-blue-500" />
                      <span>{it.description}</span>
                    </li>
                  ))}
                </ul>
              ) : null}
            </section>
          ) : null}

          {/* Section 2 — Investissement initial */}
          {features.length > 0 || fraisFixes.length > 0 || totalInitial > 0 ? (
            <section className="mt-6">
              <h2 className="text-xs font-semibold uppercase tracking-wider text-blue-700">
                Investissement initial
              </h2>
              <div className="mt-2 overflow-hidden rounded-xl border border-slate-200">
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
                  </tbody>
                  <tfoot className="bg-blue-50">
                    <tr>
                      <td className="px-4 py-3 text-sm font-bold text-blue-900">
                        Total
                      </td>
                      <td className="px-4 py-3 text-right text-base font-bold text-blue-900">
                        {fmtMoney(totalInitial)}
                      </td>
                    </tr>
                  </tfoot>
                </table>
              </div>
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
                    className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-900 placeholder:text-slate-400 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
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
