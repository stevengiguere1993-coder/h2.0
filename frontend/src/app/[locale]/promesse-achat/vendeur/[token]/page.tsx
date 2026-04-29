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
  seller_signed_at: string | null;
  seller_signed_name: string | null;
  seller_response: string | null;
};

function money(n: number | null): string {
  if (n === null) return "—";
  return new Intl.NumberFormat("fr-CA", {
    style: "currency",
    currency: "CAD",
    maximumFractionDigits: 2,
  }).format(n);
}

export default function SellerSigningPage() {
  const params = useParams<{ token: string }>();
  const token = params.token;

  const [data, setData] = useState<PublicPA | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [signName, setSignName] = useState("");
  const [signatureDataUrl, setSignatureDataUrl] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState<"accept" | "reject" | null>(
    null
  );
  const [rejectOpen, setRejectOpen] = useState(false);
  const [rejectReason, setRejectReason] = useState("");

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const res = await fetch(
          `/api/v1/public/purchase-agreements/seller/${token}`,
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
      token ? `/api/v1/public/purchase-agreements/seller/${token}/pdf` : "",
    [token]
  );

  async function accept() {
    if (!signName.trim()) {
      setError("Votre nom complet est requis pour signer.");
      return;
    }
    setSubmitting("accept");
    setError(null);
    try {
      const res = await fetch(
        `/api/v1/public/purchase-agreements/seller/${token}/accept`,
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
      setError((e as Error).message || "Acceptation échouée.");
    } finally {
      setSubmitting(null);
    }
  }

  async function reject() {
    if (!signName.trim()) {
      setError("Votre nom complet est requis.");
      return;
    }
    setSubmitting("reject");
    setError(null);
    try {
      const res = await fetch(
        `/api/v1/public/purchase-agreements/seller/${token}/reject`,
        {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({
            name: signName.trim(),
            signature_image_data_url: signatureDataUrl,
            reason: rejectReason.trim() || null,
          }),
        }
      );
      if (!res.ok) {
        const t = await res.text();
        throw new Error(t.slice(0, 240) || `HTTP ${res.status}`);
      }
      setData((await res.json()) as PublicPA);
      setRejectOpen(false);
    } catch (e) {
      setError((e as Error).message || "Refus échoué.");
    } finally {
      setSubmitting(null);
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

  const isAccepted = data.status === "accepted";
  const isRejected = data.status === "rejected";
  const isFinal = isAccepted || isRejected;

  return (
    <main className="min-h-screen bg-brand-950 py-8 text-white">
      <div className="mx-auto max-w-3xl px-4">
        <header className="text-center">
          <p className="text-xs uppercase tracking-widest text-accent-500">
            Horizon Services Immobiliers
          </p>
          <h1 className="mt-3 text-3xl font-bold">
            Offre d&apos;achat {data.reference}
          </h1>
          <p className="mt-1 text-white/70">Réponse du vendeur</p>
        </header>

        {isAccepted ? (
          <div className="mt-6 rounded-xl border border-emerald-500/40 bg-emerald-500/10 p-5 text-emerald-100">
            <div className="flex items-center gap-3">
              <CheckCircle2 className="h-6 w-6 text-emerald-300" />
              <div>
                <p className="font-semibold text-white">Offre acceptée</p>
                <p className="text-sm text-emerald-200">
                  Acceptée par {data.seller_signed_name}. Merci ! L&apos;équipe
                  Horizon vous contactera pour la suite.
                </p>
              </div>
            </div>
          </div>
        ) : null}
        {isRejected ? (
          <div className="mt-6 rounded-xl border border-rose-500/40 bg-rose-500/10 p-5 text-rose-100">
            <p className="font-semibold text-white">Offre refusée</p>
            <p className="text-sm text-rose-200">
              Merci d&apos;avoir pris le temps d&apos;examiner cette offre.
            </p>
          </div>
        ) : null}

        <section className="mt-6 overflow-hidden rounded-xl border border-brand-800 bg-brand-900">
          <div className="flex items-center justify-between border-b border-brand-800 px-5 py-4">
            <h2 className="text-sm font-semibold uppercase tracking-wider text-accent-500">
              Détails de l&apos;offre
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
            <Row k="Acheteur" v={data.buyer_1_name || "—"} />
            <Row k="Prix offert" v={money(data.price)} bold />
            <Row k="Mise de fonds" v={money(data.down_payment)} />
            <Row k="Hypothèque" v={money(data.mortgage_amount)} />
            <Row k="Acompte (fidéicommis)" v={money(data.deposit_amount)} />
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
              k="Délai pour répondre"
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

        {!isFinal ? (
          <section className="mt-6 rounded-xl border border-accent-500/40 bg-accent-500/10 p-6">
            <h2 className="text-base font-semibold text-white">
              Votre réponse
            </h2>
            <p className="mt-1 text-sm text-white/70">
              Acceptez ou refusez l&apos;offre. Votre IP et l&apos;heure
              seront enregistrées comme trace.
            </p>

            <div className="mt-4">
              <label className="text-xs text-white/70">
                Nom complet (signature)
              </label>
              <input
                type="text"
                value={signName}
                onChange={(e) => setSignName(e.target.value)}
                placeholder="Ex. Jean Tremblay"
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

            <div className="mt-5 flex flex-wrap gap-3">
              <button
                type="button"
                onClick={accept}
                disabled={submitting !== null || !signName.trim()}
                className="inline-flex items-center gap-2 rounded-lg bg-emerald-500 px-5 py-3 text-sm font-bold text-brand-950 hover:bg-emerald-400 disabled:opacity-60"
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
                onClick={() => setRejectOpen(true)}
                disabled={submitting !== null}
                className="inline-flex items-center gap-2 rounded-lg border border-rose-500/40 bg-rose-500/10 px-5 py-3 text-sm font-medium text-rose-200 hover:bg-rose-500/20 disabled:opacity-60"
              >
                Je refuse cette offre
              </button>
            </div>
          </section>
        ) : null}

        <footer className="mt-10 text-center text-xs text-white/40">
          Horizon Services Immobiliers · RBQ 5868-5991-01 ·{" "}
          <a
            className="hover:text-accent-500"
            href="mailto:info@immohorizon.com"
          >
            info@immohorizon.com
          </a>
        </footer>
      </div>

      {rejectOpen ? (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4"
          onClick={submitting !== null ? undefined : () => setRejectOpen(false)}
        >
          <div
            className="w-full max-w-md rounded-2xl border border-brand-800 bg-brand-950 p-6"
            onClick={(e) => e.stopPropagation()}
          >
            <h3 className="text-lg font-bold text-white">Refuser l&apos;offre</h3>
            <p className="mt-1 text-xs text-white/60">
              Facultatif : indiquez la raison pour qu&apos;on puisse en tenir
              compte si une nouvelle offre est faite.
            </p>
            <textarea
              rows={3}
              value={rejectReason}
              onChange={(e) => setRejectReason(e.target.value)}
              placeholder="Prix trop bas, conditions, autres considérations…"
              className="mt-4 w-full rounded-lg border border-brand-800 bg-brand-900 px-3 py-2 text-sm text-white placeholder:text-white/40 focus:border-accent-500 focus:outline-none"
            />
            <div className="mt-5 flex items-center justify-end gap-3">
              <button
                type="button"
                onClick={() => setRejectOpen(false)}
                disabled={submitting !== null}
                className="text-sm text-white/70 hover:text-white"
              >
                Annuler
              </button>
              <button
                type="button"
                onClick={reject}
                disabled={submitting !== null}
                className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-4 py-2 text-sm font-medium text-rose-200 hover:bg-rose-500/20 disabled:opacity-60"
              >
                {submitting === "reject" ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  "Confirmer le refus"
                )}
              </button>
            </div>
          </div>
        </div>
      ) : null}
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
