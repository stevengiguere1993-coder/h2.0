"use client";

import { useEffect, useMemo, useState } from "react";
import { useParams } from "next/navigation";
import { CheckCircle2, FileText, Loader2, XCircle } from "lucide-react";

import { SignaturePad } from "@/components/signature-pad";

type PublicFacture = {
  reference: string;
  status: string;
  is_final: boolean;
  issued_at: string | null;
  due_at: string | null;
  total: number | null;
  signed_name: string | null;
  signed_at: string | null;
  company_name: string;
  company_rbq: string;
  company_email: string;
};

function money(n: number): string {
  return new Intl.NumberFormat("fr-CA", {
    style: "currency",
    currency: "CAD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2
  }).format(n);
}

export default function PublicFacturePage() {
  const params = useParams<{ token: string }>();
  const token = params.token;

  const [data, setData] = useState<PublicFacture | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [signName, setSignName] = useState("");
  const [signatureDataUrl, setSignatureDataUrl] = useState<string | null>(
    null
  );
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const res = await fetch(`/api/v1/public/factures/${token}`, {
          cache: "no-store"
        });
        if (!res.ok) throw new Error(`http_${res.status}`);
        if (!cancelled) setData((await res.json()) as PublicFacture);
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
    () => (token ? `/api/v1/public/factures/${token}/pdf` : ""),
    [token]
  );

  async function extractError(res: Response): Promise<string> {
    try {
      const body = (await res.json()) as {
        detail?: string | { msg?: string }[] | { msg?: string };
      };
      if (typeof body.detail === "string") return body.detail;
      if (Array.isArray(body.detail))
        return body.detail.map((d) => d.msg || "").filter(Boolean).join(", ");
      if (body.detail && typeof body.detail === "object" && body.detail.msg)
        return body.detail.msg;
    } catch {
      /* pas du JSON */
    }
    return `Erreur serveur (HTTP ${res.status}).`;
  }

  async function sign() {
    if (!signName.trim()) {
      setError("Votre nom complet est requis pour signer.");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const res = await fetch(`/api/v1/public/factures/${token}/sign`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          name: signName.trim(),
          signature_image_data_url: signatureDataUrl
        })
      });
      if (!res.ok) throw new Error(await extractError(res));
      setData((await res.json()) as PublicFacture);
    } catch (e) {
      const msg = e instanceof Error ? e.message : "";
      setError(msg || "Signature échouée — réessayez dans un instant.");
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

  const signed = !!data.signed_at;

  return (
    <main className="min-h-screen bg-brand-950 py-8 text-white">
      <div className="mx-auto max-w-3xl px-4">
        <header className="text-center">
          <p className="text-xs uppercase tracking-widest text-accent-500">
            {data.company_name}
          </p>
          <h1 className="mt-3 text-3xl font-bold">
            Facture {data.reference}
          </h1>
          {data.total != null ? (
            <p className="mt-1 text-white/70">
              Total : {money(data.total)}
            </p>
          ) : null}
        </header>

        {signed ? (
          <div className="mt-6 rounded-xl border border-emerald-500/40 bg-emerald-500/10 p-5 text-emerald-100">
            <div className="flex items-center gap-3">
              <CheckCircle2 className="h-6 w-6 text-emerald-300" />
              <div>
                <p className="font-semibold text-white">Facture signée</p>
                <p className="text-sm text-emerald-200">
                  Signée par {data.signed_name || "vous"}. Merci !
                </p>
              </div>
            </div>
          </div>
        ) : null}

        <section className="mt-6 overflow-hidden rounded-xl border border-brand-800 bg-brand-900">
          <div className="flex items-center justify-between border-b border-brand-800 px-5 py-4">
            <h2 className="text-sm font-semibold uppercase tracking-wider text-accent-500">
              Votre facture
            </h2>
            <a
              href={pdfUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-2 text-xs text-white/70 hover:text-accent-500"
            >
              <FileText className="h-4 w-4" /> Ouvrir le PDF
            </a>
          </div>
          <iframe
            src={pdfUrl}
            title={`Facture ${data.reference}`}
            className="h-[70vh] w-full bg-white"
          />
        </section>

        {!signed ? (
          <section className="mt-6 rounded-xl border border-accent-500/40 bg-accent-500/10 p-6">
            <h2 className="text-base font-semibold text-white">
              Signer la facture finale
            </h2>

            {/* Texte de reconnaissance — identique à celui du PDF —
                affiché juste avant la signature pour que le client
                comprenne bien ce qu'il signe. */}
            <div className="mt-4 rounded-lg border border-accent-500/40 bg-brand-950/60 p-4">
              <p className="text-xs font-bold uppercase tracking-wider text-accent-400">
                Facture finale
              </p>
              <p className="mt-2 text-sm leading-relaxed text-white/90">
                En signant cette facture finale, le client reconnaît
                que la totalité des travaux prévus à la soumission de
                base a été complétée à sa satisfaction. Tout travail
                supplémentaire est facturé séparément, par entente
                mutuelle entre le client et {data.company_name}.
              </p>
            </div>

            <p className="mt-3 text-xs text-white/50">
              Votre nom, votre adresse IP et l&apos;heure sont
              enregistrés comme trace.
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

            <div className="mt-5">
              <button
                type="button"
                onClick={sign}
                disabled={submitting || !signName.trim()}
                className="inline-flex items-center gap-2 rounded-lg bg-accent-500 px-5 py-3 text-sm font-bold text-brand-950 hover:bg-accent-400 disabled:opacity-60"
              >
                {submitting ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <CheckCircle2 className="h-4 w-4" />
                )}
                Je signe cette facture
              </button>
            </div>
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
