"use client";

/**
 * Page publique de signature d'une offre d'achat.
 *
 * URL : /sign-offer/[token]
 * Pas d'authentification — le token (32 octets URL-safe) authentifie
 * le destinataire et sert d'audit trail.
 *
 * UX inspirée DuProprio :
 *   - Résumé clair de l'offre (prix, adresse, conditions)
 *   - Bouton « Télécharger le PDF »
 *   - Nom complet + 2 boutons : « J'accepte » (vert) / « Je refuse » (rouge)
 *   - Si déjà signée / expirée : message neutre sans formulaire
 */

import { useCallback, useEffect, useState } from "react";
import { useParams } from "next/navigation";
import {
  CheckCircle2,
  Download,
  FileText,
  Loader2,
  XCircle
} from "lucide-react";

type PublicOffer = {
  id: number;
  status: string;
  property_address: string | null;
  prix_offert: number | null;
  date_possession: string | null;
  date_limite_reponse: string | null;
  acompte: number | null;
  inclusions: string | null;
  condition_inspection: boolean;
  condition_inspection_delai_jours: number;
  condition_financement: boolean;
  condition_financement_delai_jours: number;
  condition_vente: boolean;
  vendeur_nom: string | null;
  signed_name: string | null;
  signed_at: string | null;
};

function fmtMoney(n: number | null): string {
  if (n === null) return "—";
  return n.toLocaleString("fr-CA", {
    style: "currency",
    currency: "CAD",
    maximumFractionDigits: 0
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

export default function SignOfferPage() {
  const params = useParams<{ token: string }>();
  const token = params.token;

  const [data, setData] = useState<PublicOffer | null>(null);
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
      const res = await fetch(`/api/v1/public/offers/${token}`, {
        cache: "no-store"
      });
      if (!res.ok) throw new Error(`http_${res.status}`);
      setData((await res.json()) as PublicOffer);
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
      const res = await fetch(`/api/v1/public/offers/${token}/sign`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          signed_name: signedName.trim(),
          accept
        })
      });
      if (!res.ok) {
        const t = await res.text();
        throw new Error(t.slice(0, 200) || `HTTP ${res.status}`);
      }
      const updated = (await res.json()) as PublicOffer;
      setData(updated);
      setDoneMessage(
        accept
          ? "Merci, l'acheteur a été notifié de votre acceptation."
          : "L'acheteur a été notifié de votre refus."
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
        <Loader2 className="h-6 w-6 animate-spin text-emerald-600" />
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

  const expired = data.status === "expire";
  const alreadyDone =
    data.status === "signe" || data.status === "refuse" || Boolean(doneMessage);

  return (
    <div className="min-h-screen bg-slate-50 px-4 py-8">
      <div className="mx-auto max-w-2xl">
        <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm sm:p-8">
          {/* Header */}
          <div className="border-b border-slate-200 pb-4">
            <p className="text-xs font-semibold uppercase tracking-wider text-emerald-700">
              Horizon Services Immobiliers
            </p>
            <h1 className="mt-1 text-2xl font-bold text-slate-900">
              Offre d&apos;achat #{data.id}
            </h1>
            <p className="mt-1 text-sm text-slate-600">
              {data.property_address || "Propriété à confirmer"}
            </p>
          </div>

          {/* Résumé */}
          <dl className="mt-5 grid grid-cols-1 gap-y-3 sm:grid-cols-2">
            <div>
              <dt className="text-xs uppercase tracking-wider text-slate-500">
                Prix offert
              </dt>
              <dd className="mt-0.5 text-xl font-bold text-emerald-700">
                {fmtMoney(data.prix_offert)}
              </dd>
            </div>
            <div>
              <dt className="text-xs uppercase tracking-wider text-slate-500">
                Acompte
              </dt>
              <dd className="mt-0.5 text-sm text-slate-800">
                {fmtMoney(data.acompte)}
              </dd>
            </div>
            <div>
              <dt className="text-xs uppercase tracking-wider text-slate-500">
                Prise de possession
              </dt>
              <dd className="mt-0.5 text-sm text-slate-800">
                {fmtDate(data.date_possession)}
              </dd>
            </div>
            <div>
              <dt className="text-xs uppercase tracking-wider text-slate-500">
                Réponse attendue avant le
              </dt>
              <dd className="mt-0.5 text-sm text-slate-800">
                {fmtDate(data.date_limite_reponse)}
              </dd>
            </div>
          </dl>

          {/* Conditions */}
          <div className="mt-5 rounded-lg border border-slate-200 bg-slate-50 p-4">
            <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-600">
              Conditions
            </h3>
            <ul className="mt-2 space-y-1 text-sm text-slate-800">
              <li>
                {data.condition_inspection ? "[X]" : "[ ]"} Conditionnelle à une
                inspection préachat satisfaisante
                {data.condition_inspection
                  ? ` (délai : ${data.condition_inspection_delai_jours} jours)`
                  : ""}
              </li>
              <li>
                {data.condition_financement ? "[X]" : "[ ]"} Conditionnelle à
                l&apos;obtention d&apos;un financement hypothécaire
                {data.condition_financement
                  ? ` (délai : ${data.condition_financement_delai_jours} jours)`
                  : ""}
              </li>
              <li>
                {data.condition_vente ? "[X]" : "[ ]"} Conditionnelle à la vente
                d&apos;une autre propriété par l&apos;acheteur
              </li>
            </ul>
          </div>

          {data.inclusions ? (
            <details className="mt-3 rounded-lg border border-slate-200 bg-slate-50 p-4 text-sm text-slate-700">
              <summary className="cursor-pointer text-xs font-semibold uppercase tracking-wider text-slate-600">
                Inclusions standards
              </summary>
              <p className="mt-2">{data.inclusions}</p>
            </details>
          ) : null}

          {/* Lien PDF */}
          <div className="mt-5">
            <a
              href={`/api/v1/public/offers/${token}/pdf`}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-2 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50"
            >
              <Download className="h-4 w-4" />
              Télécharger l&apos;offre en PDF
            </a>
          </div>

          {/* Zone signature / statut */}
          <div className="mt-6 border-t border-slate-200 pt-6">
            {expired ? (
              <div className="rounded-lg border border-slate-300 bg-slate-100 p-4 text-sm text-slate-700">
                <FileText className="mb-2 h-5 w-5 text-slate-500" />
                Cette offre a expiré le{" "}
                <strong>{fmtDate(data.date_limite_reponse)}</strong>. Aucune
                réponse n&apos;est plus possible. Contactez l&apos;acheteur si
                vous souhaitez relancer la discussion.
              </div>
            ) : alreadyDone ? (
              <div
                className={`rounded-lg border p-4 text-sm ${
                  data.status === "signe" || doneMessage?.includes("acceptation")
                    ? "border-emerald-300 bg-emerald-50 text-emerald-900"
                    : "border-rose-300 bg-rose-50 text-rose-900"
                }`}
              >
                {data.status === "signe" ||
                doneMessage?.includes("acceptation") ? (
                  <CheckCircle2 className="mb-2 h-5 w-5 text-emerald-600" />
                ) : (
                  <XCircle className="mb-2 h-5 w-5 text-rose-600" />
                )}
                {doneMessage ||
                  (data.status === "signe"
                    ? `Offre signée le ${fmtDate(
                        data.signed_at
                      )} par ${data.signed_name}.`
                    : `Offre refusée le ${fmtDate(
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
                  électroniquement cette offre d&apos;achat ; elle constituera
                  alors un contrat liant juridiquement les parties (sous réserve
                  des conditions ci-dessus).
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
                    className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-900 placeholder:text-slate-400 focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
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
                    J&apos;accepte cette offre
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

          <p className="mt-6 border-t border-slate-200 pt-4 text-center text-xs text-slate-500">
            Horizon Services Immobiliers &middot; immohorizon.com
          </p>
        </div>
      </div>
    </div>
  );
}
