"use client";

import { useEffect, useMemo, useState } from "react";
import { useParams } from "next/navigation";
import { CheckCircle2, FileText, Loader2, XCircle } from "lucide-react";

import { SignaturePad } from "@/components/signature-pad";

type PublicPA = {
  reference: string;
  status: string;
  role: string;
  property_address: string | null;
  price: number | null;
  down_payment: number | null;
  mortgage_amount: number | null;
  deposit_amount: number | null;
  inspection_enabled: boolean;
  inspection_days: number;
  visit_units_enabled: boolean;
  water_septic_enabled: boolean;
  buyer_property_sale_enabled: boolean;
  conditional_other_offer_enabled: boolean;
  act_of_sale_date: string | null;
  occupation_date: string | null;
  acceptance_deadline_date: string | null;
  acceptance_deadline_time: string | null;
  seller_1_name: string | null;
  buyer_1_name: string | null;
  buyer_signed_at: string | null;
  buyer_signed_name: string | null;
};

function money(n: number | null): string {
  if (n === null) return "—";
  return new Intl.NumberFormat("fr-CA", {
    style: "currency",
    currency: "CAD",
    maximumFractionDigits: 2,
  }).format(n);
}

export default function BuyerSigningPage() {
  const params = useParams<{ token: string }>();
  const token = params.token;

  const [data, setData] = useState<PublicPA | null>(null);
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
        const res = await fetch(
          `/api/v1/public/purchase-agreements/buyer/${token}`,
          { cache: "no-store" }
        );
        if (!res.ok) throw new Error(`http_${res.status}`);
        if (!cancelled) setData((await res.json()) as PublicPA);
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
    () =>
      token ? `/api/v1/public/purchase-agreements/buyer/${token}/pdf` : "",
    [token]
  );

  async function sign() {
    if (!signName.trim()) {
      setError("Votre nom complet est requis pour signer.");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const res = await fetch(
        `/api/v1/public/purchase-agreements/buyer/${token}/sign`,
        {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({
            name: signName.trim(),
            signature_image_data_url: signatureDataUrl,
          }),
        }
      );
      if (!res.ok) {
        const t = await res.text();
        throw new Error(t.slice(0, 240) || `HTTP ${res.status}`);
      }
      setData((await res.json()) as PublicPA);
    } catch (e) {
      setError((e as Error).message || "Signature échouée.");
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

  const isSigned = !!data.buyer_signed_at;

  return (
    <main className="min-h-screen bg-brand-950 py-8 text-white">
      <div className="mx-auto max-w-3xl px-4">
        <header className="text-center">
          <p className="text-xs uppercase tracking-widest text-accent-500">
            Horizon Services Immobiliers
          </p>
          <h1 className="mt-3 text-3xl font-bold">
            Promesse d&apos;achat {data.reference}
          </h1>
          <p className="mt-1 text-white/70">Signature de l&apos;acheteur</p>
        </header>

        {isSigned ? (
          <div className="mt-6 rounded-xl border border-emerald-500/40 bg-emerald-500/10 p-5 text-emerald-100">
            <div className="flex items-center gap-3">
              <CheckCircle2 className="h-6 w-6 text-emerald-300" />
              <div>
                <p className="font-semibold text-white">PA signée</p>
                <p className="text-sm text-emerald-200">
                  Signée par {data.buyer_signed_name}. Vous pouvez maintenant
                  la transmettre au vendeur depuis le portail.
                </p>
              </div>
            </div>
          </div>
        ) : null}

        <section className="mt-6 overflow-hidden rounded-xl border border-brand-800 bg-brand-900">
          <div className="flex items-center justify-between border-b border-brand-800 px-5 py-4">
            <h2 className="text-sm font-semibold uppercase tracking-wider text-accent-500">
              Récapitulatif
            </h2>
            <a
              href={pdfUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-2 text-xs text-white/70 hover:text-accent-500"
            >
              <FileText className="h-4 w-4" /> Voir le PDF complet
            </a>
          </div>
          <dl className="divide-y divide-brand-800 text-sm">
            <Row k="Propriété" v={data.property_address || "—"} />
            <Row k="Vendeur" v={data.seller_1_name || "—"} />
            <Row k="Prix offert" v={money(data.price)} bold />
            <Row k="Mise de fonds" v={money(data.down_payment)} />
            <Row k="Hypothèque" v={money(data.mortgage_amount)} />
            <Row k="Acompte" v={money(data.deposit_amount)} />
            <Row
              k="Inspection"
              v={
                data.inspection_enabled
                  ? `Oui (${data.inspection_days} jours)`
                  : "Non"
              }
            />
            <Row
              k="Acte de vente avant le"
              v={data.act_of_sale_date || "—"}
            />
            <Row k="Occupation" v={data.occupation_date || "—"} />
            <Row
              k="Délai d'acceptation"
              v={
                data.acceptance_deadline_date
                  ? `${data.acceptance_deadline_date}${
                      data.acceptance_deadline_time
                        ? " à " + data.acceptance_deadline_time
                        : ""
                    }`
                  : "—"
              }
            />
          </dl>
        </section>

        {!isSigned ? (
          <section className="mt-6 rounded-xl border border-accent-500/40 bg-accent-500/10 p-6">
            <h2 className="text-base font-semibold text-white">
              Confirmer et signer
            </h2>
            <p className="mt-1 text-sm text-white/70">
              En signant, vous confirmez votre engagement à acheter aux
              conditions ci-dessus. La PA sera ensuite transmise au vendeur.
            </p>

            <div className="mt-4">
              <label className="text-xs text-white/70">
                Nom complet (signature)
              </label>
              <input
                type="text"
                value={signName}
                onChange={(e) => setSignName(e.target.value)}
                placeholder="Ex. Steven Giguère"
                className="mt-1 w-full rounded-lg border border-brand-800 bg-brand-950 px-3 py-2 text-sm text-white placeholder:text-white/40 focus:border-accent-500 focus:outline-none"
              />
            </div>

            <div className="mt-4">
              <label className="text-xs text-white/70">Signature tracée</label>
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
                Je signe la promesse d&apos;achat
              </button>
            </div>
          </section>
        ) : null}

        <footer className="mt-10 text-center text-xs text-white/40">
          Horizon Services Immobiliers · RBQ 5868-5991-01 ·{" "}
          <a className="hover:text-accent-500" href="mailto:info@immohorizon.com">
            info@immohorizon.com
          </a>
        </footer>
      </div>
    </main>
  );
}

function Row({ k, v, bold }: { k: string; v: string; bold?: boolean }) {
  return (
    <div className="flex items-center justify-between gap-4 px-5 py-2">
      <dt className="text-xs uppercase tracking-wider text-white/50">{k}</dt>
      <dd className={bold ? "text-base font-bold text-white" : "text-white/90"}>
        {v}
      </dd>
    </div>
  );
}
