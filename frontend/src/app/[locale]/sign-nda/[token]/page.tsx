"use client";

/**
 * Page publique de signature d'une entente de confidentialité (NDA).
 *
 * URL : /sign-nda/[token]
 * Pas d'authentification — le token (32 octets URL-safe) authentifie
 * le destinataire et sert d'audit trail.
 *
 * UX :
 *   - Résumé clair de l'entente (propriété visée, émetteur,
 *     destinataire, durée 2 ans, juridiction Québec, 5 engagements)
 *   - Bouton « Télécharger l'entente en PDF »
 *   - Champ « Nom complet » (pré-rempli avec investor_name, éditable)
 *   - Un seul bouton vert : « Je m'engage à respecter cette entente »
 *   - Pas de bouton « refuser » — ne rien faire suffit.
 *   - Si déjà signée : message neutre sans formulaire.
 */

import { useCallback, useEffect, useState } from "react";
import { useParams } from "next/navigation";
import {
  CheckCircle2,
  Download,
  Loader2,
  ShieldCheck,
  XCircle
} from "lucide-react";

type PublicNDA = {
  id: number;
  status: string;
  property_address: string | null;
  investor_name: string;
  issuer_name: string;
  duration_years: number;
  jurisdiction: string;
  engagement_items: string[];
  signed_name: string | null;
  signed_at: string | null;
  sent_at: string | null;
};

function fmtDate(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("fr-CA", {
    day: "numeric",
    month: "long",
    year: "numeric"
  });
}

export default function SignNDAPage() {
  const params = useParams<{ token: string }>();
  const token = params.token;

  const [data, setData] = useState<PublicNDA | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [signedName, setSignedName] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [doneMessage, setDoneMessage] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`/api/v1/public/ndas/${token}`, {
        cache: "no-store"
      });
      if (!res.ok) throw new Error(`http_${res.status}`);
      const json = (await res.json()) as PublicNDA;
      setData(json);
      // Pré-remplir le nom avec investor_name mais l'investisseur
      // peut le modifier s'il veut signer sous une variante (ex.
      // « Jean-Marc Tremblay » au lieu de « JM Tremblay »).
      if (!signedName) setSignedName(json.investor_name || "");
    } catch {
      setError("Lien invalide ou expiré.");
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  useEffect(() => {
    if (token) void load();
  }, [token, load]);

  async function submit() {
    if (submitting) return;
    if (!signedName.trim() || signedName.trim().length < 2) {
      setError("Veuillez entrer votre nom complet (au moins 2 caractères).");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const res = await fetch(`/api/v1/public/ndas/${token}/sign`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ signed_name: signedName.trim() })
      });
      if (!res.ok) {
        const t = await res.text();
        throw new Error(t.slice(0, 200) || `HTTP ${res.status}`);
      }
      const updated = (await res.json()) as PublicNDA;
      setData(updated);
      setDoneMessage(
        "Merci. Vous recevrez les informations confidentielles sous peu."
      );
    } catch (e) {
      setError((e as Error).message || "Soumission échouée.");
    } finally {
      setSubmitting(false);
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

  const alreadyDone = data.status === "signe" || Boolean(doneMessage);

  return (
    <div className="min-h-screen bg-slate-50 px-4 py-8">
      <div className="mx-auto max-w-2xl">
        <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm sm:p-8">
          {/* Header */}
          <div className="border-b border-slate-200 pb-4">
            <p className="text-xs font-semibold uppercase tracking-wider text-blue-700">
              {data.issuer_name}
            </p>
            <h1 className="mt-1 flex items-center gap-2 text-2xl font-bold text-slate-900">
              <ShieldCheck className="h-6 w-6 text-blue-600" />
              Entente de confidentialité
            </h1>
            <p className="mt-1 text-sm text-slate-600">
              Concernant la propriété :{" "}
              <span className="font-semibold">
                {data.property_address || "à confirmer"}
              </span>
            </p>
          </div>

          {/* Résumé */}
          <dl className="mt-5 grid grid-cols-1 gap-y-3 sm:grid-cols-2">
            <div>
              <dt className="text-xs uppercase tracking-wider text-slate-500">
                Émetteur
              </dt>
              <dd className="mt-0.5 text-sm font-semibold text-slate-800">
                {data.issuer_name}
              </dd>
            </div>
            <div>
              <dt className="text-xs uppercase tracking-wider text-slate-500">
                Destinataire
              </dt>
              <dd className="mt-0.5 text-sm font-semibold text-slate-800">
                {data.investor_name}
              </dd>
            </div>
            <div>
              <dt className="text-xs uppercase tracking-wider text-slate-500">
                Durée de l&apos;engagement
              </dt>
              <dd className="mt-0.5 text-sm text-slate-800">
                {data.duration_years} ans à compter de la signature
              </dd>
            </div>
            <div>
              <dt className="text-xs uppercase tracking-wider text-slate-500">
                Juridiction
              </dt>
              <dd className="mt-0.5 text-sm text-slate-800">
                {data.jurisdiction}
              </dd>
            </div>
            <div>
              <dt className="text-xs uppercase tracking-wider text-slate-500">
                Date d&apos;émission
              </dt>
              <dd className="mt-0.5 text-sm text-slate-800">
                {fmtDate(data.sent_at)}
              </dd>
            </div>
          </dl>

          {/* Engagements */}
          <div className="mt-5 rounded-lg border border-slate-200 bg-slate-50 p-4">
            <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-600">
              En signant, le destinataire s&apos;engage à :
            </h3>
            <ol className="mt-2 list-decimal space-y-1.5 pl-5 text-sm text-slate-800">
              {data.engagement_items.map((item, i) => (
                <li key={i}>{item}</li>
              ))}
            </ol>
          </div>

          {/* Lien PDF */}
          <div className="mt-5">
            <a
              href={`/api/v1/public/ndas/${token}/pdf`}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-2 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50"
            >
              <Download className="h-4 w-4" />
              Télécharger l&apos;entente en PDF
            </a>
          </div>

          {/* Zone signature / statut */}
          <div className="mt-6 border-t border-slate-200 pt-6">
            {alreadyDone ? (
              <div className="rounded-lg border border-emerald-300 bg-emerald-50 p-4 text-sm text-emerald-900">
                <CheckCircle2 className="mb-2 h-5 w-5 text-emerald-600" />
                {doneMessage ||
                  `Entente signée le ${fmtDate(data.signed_at)} par ${
                    data.signed_name
                  }.`}
              </div>
            ) : (
              <>
                <h3 className="text-sm font-bold text-slate-900">
                  Signature électronique
                </h3>
                <p className="mt-1 text-xs text-slate-600">
                  En cliquant sur « Je m&apos;engage à respecter cette
                  entente », vous signez électroniquement le présent NDA ; il
                  vous lie pour une durée de {data.duration_years} ans en vertu
                  du droit du {data.jurisdiction}.
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

                <div className="mt-4">
                  <button
                    type="button"
                    onClick={() => void submit()}
                    disabled={submitting}
                    className="inline-flex w-full items-center justify-center gap-2 rounded-lg bg-emerald-600 px-4 py-3 text-sm font-bold text-white hover:bg-emerald-700 disabled:opacity-60"
                  >
                    {submitting ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : (
                      <ShieldCheck className="h-4 w-4" />
                    )}
                    Je m&apos;engage à respecter cette entente
                  </button>
                </div>
              </>
            )}
          </div>

          <p className="mt-6 border-t border-slate-200 pt-4 text-center text-xs text-slate-500">
            {data.issuer_name} &middot; immohorizon.com
          </p>
        </div>
      </div>
    </div>
  );
}
