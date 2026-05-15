"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { CheckCircle2, FileSignature, Loader2, XCircle } from "lucide-react";

// Page publique (sans authentification) — le client signe son contrat
// de développement logiciel via le lien tokenisé reçu par courriel.

type PublicContract = {
  title: string;
  body: string | null;
  status: string;
  signed_at: string | null;
  signed_name: string | null;
};

export default function PublicSignDevlogPage() {
  const params = useParams<{ token: string }>();
  const token = params.token;

  const [data, setData] = useState<PublicContract | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [signName, setSignName] = useState("");
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const r = await fetch(
          `/api/v1/public/devlog/contracts/${token}`,
          { cache: "no-store" }
        );
        if (!r.ok) throw new Error(`http_${r.status}`);
        if (!cancelled) setData((await r.json()) as PublicContract);
      } catch {
        if (!cancelled) setError("Lien invalide ou expiré.");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [token]);

  async function sign() {
    if (!signName.trim() || submitting) return;
    setSubmitting(true);
    setError(null);
    try {
      const r = await fetch(
        `/api/v1/public/devlog/contracts/${token}/sign`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ name: signName.trim() })
        }
      );
      if (!r.ok) throw new Error();
      setData((await r.json()) as PublicContract);
    } catch {
      setError("Signature impossible. Réessaie ou contacte-nous.");
    } finally {
      setSubmitting(false);
    }
  }

  const isSigned = data?.status === "signe" || !!data?.signed_at;
  const isCancelled = data?.status === "annule";

  return (
    <div className="min-h-screen bg-brand-950 px-4 py-10 text-white">
      <div className="mx-auto max-w-3xl">
        <header className="mb-6 flex items-center gap-3">
          <span className="flex h-12 w-12 items-center justify-center rounded-xl bg-blue-500/15 text-blue-300">
            <FileSignature className="h-6 w-6" />
          </span>
          <div>
            <h1 className="text-2xl font-bold">Signature de contrat</h1>
            <p className="text-sm text-white/60">
              Développement logiciel — Horizon
            </p>
          </div>
        </header>

        {loading ? (
          <div className="flex justify-center py-12">
            <Loader2 className="h-6 w-6 animate-spin text-blue-500" />
          </div>
        ) : error || !data ? (
          <div className="rounded-2xl border border-rose-500/40 bg-rose-500/10 p-6 text-center">
            <XCircle className="mx-auto h-8 w-8 text-rose-300" />
            <p className="mt-2 text-sm text-rose-200">
              {error ?? "Lien invalide."}
            </p>
          </div>
        ) : (
          <>
            <article className="rounded-2xl border border-brand-800 bg-brand-900 p-6">
              <h2 className="mb-3 text-xl font-bold">{data.title}</h2>
              {data.body ? (
                <pre className="whitespace-pre-wrap break-words font-sans text-sm leading-relaxed text-white/85">
                  {data.body}
                </pre>
              ) : (
                <p className="text-sm text-white/40">(Contenu vide)</p>
              )}
            </article>

            {isCancelled ? (
              <div className="mt-4 rounded-xl border border-rose-500/40 bg-rose-500/10 p-4 text-center text-sm text-rose-300">
                Ce contrat a été annulé.
              </div>
            ) : isSigned ? (
              <div className="mt-4 rounded-xl border border-emerald-500/40 bg-emerald-500/10 p-4">
                <div className="flex items-center gap-2 text-emerald-300">
                  <CheckCircle2 className="h-5 w-5" />
                  <span className="font-semibold">Contrat signé</span>
                </div>
                <p className="mt-1 text-sm text-emerald-200/80">
                  Par <strong>{data.signed_name}</strong> le{" "}
                  {data.signed_at
                    ? new Date(data.signed_at).toLocaleString("fr-CA")
                    : ""}
                </p>
              </div>
            ) : (
              <section className="mt-4 rounded-2xl border border-brand-800 bg-brand-900 p-6">
                <h3 className="mb-3 text-sm font-bold">Signer ce contrat</h3>
                <p className="mb-3 text-xs text-white/60">
                  En tapant ton nom complet et en cliquant « Signer », tu
                  acceptes les termes du contrat ci-dessus. Une trace
                  horodatée sera enregistrée.
                </p>
                <input
                  value={signName}
                  onChange={(e) => setSignName(e.target.value)}
                  placeholder="Ton nom complet"
                  className="w-full rounded-lg border border-brand-700 bg-brand-950 px-3 py-2 text-sm text-white"
                />
                <button
                  type="button"
                  onClick={() => void sign()}
                  disabled={!signName.trim() || submitting}
                  className="mt-3 inline-flex items-center gap-2 rounded-lg bg-blue-500 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-400 disabled:opacity-50"
                >
                  {submitting ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <CheckCircle2 className="h-4 w-4" />
                  )}
                  Signer
                </button>
              </section>
            )}
          </>
        )}
      </div>
    </div>
  );
}
