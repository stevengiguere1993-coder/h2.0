"use client";

import { useEffect, useMemo, useState } from "react";
import { useParams } from "next/navigation";
import { CheckCircle2, FileText, Loader2, XCircle } from "lucide-react";

import { SignaturePad } from "@/components/signature-pad";

type Item = {
  position: number;
  description: string;
  unit: string | null;
  quantity: number;
  unit_price: number;
  total: number;
};

type PublicBon = {
  reference: string;
  title: string;
  description: string | null;
  scope_md: string | null;
  status: string;
  amount: number | null;
  signed_by_name: string | null;
  signed_at: string | null;
  items: Item[];
  total: number;
  company_name: string;
  company_rbq: string;
  company_email: string;
};

function money(n: number): string {
  return new Intl.NumberFormat("fr-CA", {
    style: "currency",
    currency: "CAD",
    maximumFractionDigits: 2
  }).format(n);
}

export default function PublicBonPage() {
  const params = useParams<{ token: string }>();
  const token = params.token;

  const [data, setData] = useState<PublicBon | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [signName, setSignName] = useState("");
  const [signatureDataUrl, setSignatureDataUrl] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const res = await fetch(`/api/v1/public/bons/${token}`, {
          cache: "no-store"
        });
        if (!res.ok) throw new Error(`http_${res.status}`);
        if (!cancelled) setData((await res.json()) as PublicBon);
      } catch {
        if (!cancelled) setError("Lien invalide ou expiré.");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    if (token) load();
    return () => {
      cancelled = true;
    };
  }, [token]);

  const pdfUrl = useMemo(
    () => (token ? `/api/v1/public/bons/${token}/pdf` : ""),
    [token]
  );

  async function accept() {
    if (!signName.trim()) {
      setError("Ton nom complet est requis.");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const res = await fetch(`/api/v1/public/bons/${token}/accept`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          name: signName.trim(),
          signature_image_data_url: signatureDataUrl
        })
      });
      if (!res.ok) throw new Error(`http_${res.status}`);
      setData((await res.json()) as PublicBon);
    } catch {
      setError("Signature échouée — réessaie dans un instant.");
    } finally {
      setSubmitting(false);
    }
  }

  if (loading) {
    return (
      <main className="flex min-h-screen items-center justify-center bg-brand-950 text-white">
        <Loader2 className="h-6 w-6 animate-spin text-accent-500" />
      </main>
    );
  }
  if (error && !data) {
    return (
      <main className="flex min-h-screen items-center justify-center bg-brand-950 p-6 text-white">
        <div className="max-w-md rounded-2xl border border-rose-500/40 bg-rose-500/10 p-6 text-center">
          <XCircle className="mx-auto h-10 w-10 text-rose-300" />
          <h1 className="mt-4 text-lg font-bold">Lien invalide</h1>
          <p className="mt-2 text-sm text-rose-200">{error}</p>
        </div>
      </main>
    );
  }
  if (!data) return null;

  const isSigned = data.status === "signed";

  return (
    <main className="min-h-screen bg-brand-950 py-8 text-white">
      <div className="mx-auto max-w-3xl px-4">
        <header className="text-center">
          <p className="text-xs uppercase tracking-widest text-accent-500">
            {data.company_name}
          </p>
          <h1 className="mt-3 text-3xl font-bold">
            Bon de travail {data.reference}
          </h1>
          <p className="mt-1 text-white/70">{data.title}</p>
        </header>

        {isSigned ? (
          <div className="mt-6 rounded-xl border border-emerald-500/40 bg-emerald-500/10 p-5">
            <div className="flex items-center gap-3">
              <CheckCircle2 className="h-6 w-6 text-emerald-300" />
              <div>
                <p className="font-semibold text-white">Bon signé</p>
                <p className="text-sm text-emerald-200">
                  Signé par {data.signed_by_name}
                  {data.signed_at
                    ? ` le ${new Date(data.signed_at).toLocaleString(
                        "fr-CA"
                      )}`
                    : ""}
                  . Merci !
                </p>
              </div>
            </div>
          </div>
        ) : null}

        <section className="mt-6 overflow-hidden rounded-xl border border-brand-800 bg-brand-900">
          <div className="flex items-center justify-between border-b border-brand-800 px-5 py-4">
            <h2 className="text-sm font-semibold uppercase tracking-wider text-accent-500">
              Détails
            </h2>
            <a
              href={pdfUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-2 text-xs text-white/70 hover:text-accent-500"
            >
              <FileText className="h-4 w-4" /> PDF
            </a>
          </div>
          {data.description ? (
            <p className="border-b border-brand-800 px-5 py-4 text-sm text-white/80">
              {data.description}
            </p>
          ) : null}
          {data.scope_md ? (
            <div className="border-b border-brand-800 px-5 py-4 text-sm text-white/80">
              <p className="mb-2 text-xs uppercase tracking-wider text-accent-500">
                Portée des travaux
              </p>
              <pre className="whitespace-pre-wrap font-sans">{data.scope_md}</pre>
            </div>
          ) : null}
          {data.items.length > 0 ? (
            <table className="w-full text-sm">
              <thead className="border-b border-brand-800 text-left text-xs uppercase tracking-wider text-white/50">
                <tr>
                  <th className="px-5 py-2">Description</th>
                  <th className="px-5 py-2 text-right">Qté</th>
                  <th className="px-5 py-2 text-right">Prix</th>
                  <th className="px-5 py-2 text-right">Total</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-brand-800">
                {data.items.map((it, i) => (
                  <tr key={i}>
                    <td className="px-5 py-2">{it.description}</td>
                    <td className="px-5 py-2 text-right">
                      {it.quantity} {it.unit || ""}
                    </td>
                    <td className="px-5 py-2 text-right">
                      {money(it.unit_price)}
                    </td>
                    <td className="px-5 py-2 text-right font-semibold">
                      {money(it.total || it.quantity * it.unit_price)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : null}
          <div className="border-t border-brand-800 px-5 py-4 text-right">
            <span className="text-sm text-white/70">Montant : </span>
            <span className="text-base font-bold text-white">
              {money(data.total || data.amount || 0)}
            </span>
          </div>
        </section>

        {!isSigned ? (
          <section className="mt-6 rounded-xl border border-accent-500/40 bg-accent-500/10 p-6">
            <h2 className="text-base font-semibold text-white">
              Signer ce bon de travail
            </h2>
            <p className="mt-1 text-sm text-white/70">
              En signant, vous autorisez l&apos;exécution des travaux
              décrits pour le montant indiqué.
            </p>
            <div className="mt-4">
              <label htmlFor="sign_name" className="text-xs text-white/70">
                Nom complet (signature)
              </label>
              <input
                id="sign_name"
                type="text"
                value={signName}
                onChange={(e) => setSignName(e.target.value)}
                placeholder="Ex. Jean Tremblay"
                className="mt-1 w-full rounded-lg border border-brand-800 bg-brand-950 px-3 py-2 text-sm text-white placeholder:text-white/40 focus:border-accent-500 focus:outline-none"
              />
            </div>
            <div className="mt-4">
              <label className="text-xs text-white/70">
                Signature tracée (optionnel)
              </label>
              <div className="mt-1">
                <SignaturePad onChange={setSignatureDataUrl} />
              </div>
            </div>
            {error ? (
              <p className="mt-3 text-sm text-rose-300">{error}</p>
            ) : null}
            <button
              type="button"
              onClick={accept}
              disabled={submitting || !signName.trim()}
              className="mt-5 inline-flex items-center gap-2 rounded-lg bg-accent-500 px-5 py-3 text-sm font-bold text-brand-950 hover:bg-accent-400 disabled:opacity-60"
            >
              {submitting ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <CheckCircle2 className="h-4 w-4" />
              )}
              Signer ce bon
            </button>
          </section>
        ) : null}

        <footer className="mt-10 text-center text-xs text-white/40">
          {data.company_name} &middot; {data.company_rbq} &middot;{" "}
          <a
            className="hover:text-accent-500"
            href={`mailto:${data.company_email}`}
          >
            {data.company_email}
          </a>
        </footer>
      </div>
    </main>
  );
}
