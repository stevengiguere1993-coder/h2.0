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

type PublicSoumission = {
  reference: string;
  title: string;
  description: string | null;
  client_note: string | null;
  status: string;
  valid_until: string | null;
  signed_name: string | null;
  items: Item[];
  subtotal: number;
  tps: number;
  tvq: number;
  total: number;
  company_name: string;
  company_rbq: string;
  company_email: string;
  pricing_kind?: "forfaitaire" | "estime";
};

function money(n: number): string {
  return new Intl.NumberFormat("fr-CA", {
    style: "currency",
    currency: "CAD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2
  }).format(n);
}

export default function PublicSoumissionPage() {
  const params = useParams<{ token: string }>();
  const token = params.token;

  const [data, setData] = useState<PublicSoumission | null>(null);
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
        const res = await fetch(`/api/v1/public/soumissions/${token}`, {
          cache: "no-store"
        });
        if (!res.ok) throw new Error(`http_${res.status}`);
        if (!cancelled) setData((await res.json()) as PublicSoumission);
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
    () => (token ? `/api/v1/public/soumissions/${token}/pdf` : ""),
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
      /* not JSON */
    }
    return `Erreur serveur (HTTP ${res.status}).`;
  }

  async function accept() {
    if (!signName.trim()) {
      setError("Ton nom complet est requis pour signer.");
      return;
    }
    if (!signatureDataUrl) {
      setError("La signature tracée est obligatoire — signe dans le cadre.");
      return;
    }
    setSubmitting("accept");
    setError(null);
    try {
      const res = await fetch(`/api/v1/public/soumissions/${token}/accept`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          name: signName.trim(),
          signature_image_data_url: signatureDataUrl
        })
      });
      if (!res.ok) {
        const detail = await extractError(res);
        throw new Error(detail);
      }
      setData((await res.json()) as PublicSoumission);
    } catch (e) {
      const msg = e instanceof Error ? e.message : "";
      setError(msg || "Acceptation échouée — réessaie dans un instant.");
    } finally {
      setSubmitting(null);
    }
  }

  async function reject() {
    setSubmitting("reject");
    setError(null);
    try {
      const res = await fetch(`/api/v1/public/soumissions/${token}/reject`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ reason: rejectReason.trim() || null })
      });
      if (!res.ok) {
        const detail = await extractError(res);
        throw new Error(detail);
      }
      setData((await res.json()) as PublicSoumission);
      setRejectOpen(false);
    } catch (e) {
      const msg = e instanceof Error ? e.message : "";
      setError(msg || "Refus échoué — réessaie dans un instant.");
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
            {data.company_name}
          </p>
          <h1 className="mt-3 text-3xl font-bold">Soumission {data.reference}</h1>
          <p className="mt-1 text-white/70">{data.title}</p>
        </header>

        {isAccepted ? (
          <div className="mt-6 rounded-xl border border-emerald-500/40 bg-emerald-500/10 p-5 text-emerald-100">
            <div className="flex items-center gap-3">
              <CheckCircle2 className="h-6 w-6 text-emerald-300" />
              <div>
                <p className="font-semibold text-white">
                  Soumission acceptée
                </p>
                <p className="text-sm text-emerald-200">
                  Signée par {data.signed_name || "vous"}. Merci ! Nous te
                  contactons sous peu pour confirmer la suite.
                </p>
              </div>
            </div>
          </div>
        ) : null}
        {isRejected ? (
          <div className="mt-6 rounded-xl border border-rose-500/40 bg-rose-500/10 p-5 text-rose-100">
            <p className="font-semibold text-white">Soumission refusée</p>
            <p className="text-sm text-rose-200">
              Merci — si tu changes d&apos;idée, contacte-nous à{" "}
              {data.company_email}.
            </p>
          </div>
        ) : null}

        <section className="mt-6 overflow-hidden rounded-xl border border-brand-800 bg-brand-900">
          <div className="flex items-center justify-between border-b border-brand-800 px-5 py-4">
            <h2 className="text-sm font-semibold uppercase tracking-wider text-accent-500">
              Détail des travaux
            </h2>
            <a
              href={pdfUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-2 text-xs text-white/70 hover:text-accent-500"
            >
              <FileText className="h-4 w-4" /> Télécharger le PDF
            </a>
          </div>

          {data.description ? (
            <p className="border-b border-brand-800 px-5 py-4 text-sm text-white/80">
              {data.description}
            </p>
          ) : null}

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
              {data.items.length === 0 ? (
                <tr>
                  <td colSpan={4} className="px-5 py-6 text-center text-white/50">
                    Aucun item détaillé.
                  </td>
                </tr>
              ) : (
                data.items.map((it, i) => (
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
                ))
              )}
            </tbody>
          </table>

          <div className="border-t border-brand-800 px-5 py-4">
            <div className="ml-auto max-w-xs space-y-1 text-right text-sm">
              <div className="flex justify-between text-white/70">
                <span>Sous-total</span>
                <span>{money(data.subtotal)}</span>
              </div>
              <div className="flex justify-between text-white/70">
                <span>TPS (5 %)</span>
                <span>{money(data.tps)}</span>
              </div>
              <div className="flex justify-between text-white/70">
                <span>TVQ (9,975 %)</span>
                <span>{money(data.tvq)}</span>
              </div>
              <div className="flex justify-between border-t border-brand-800 pt-1 text-base font-bold">
                <span>TOTAL</span>
                <span>{money(data.total)}</span>
              </div>
            </div>
          </div>
        </section>

        {data.client_note ? (
          <section className="mt-4 rounded-xl border border-accent-500/30 bg-accent-500/5 p-4 text-sm text-brand-100 whitespace-pre-line">
            {data.client_note}
          </section>
        ) : null}

        {/* Clause client-facing pour les soumissions ESTIMÉES — clarifie
            que les montants peuvent évoluer en cours de projet et que
            l'équipe s'engage à tenir le client au courant. */}
        {data.pricing_kind === "estime" ? (
          <section className="mt-4 rounded-xl border border-amber-400/40 bg-amber-500/10 p-4 text-sm text-brand-100">
            <p className="mb-2 text-xs font-bold uppercase tracking-wider text-amber-300">
              Estimé — important
            </p>
            <p>
              Cette soumission est un <strong>estimé</strong> et non un
              prix forfaitaire fixe. Les montants présentés sont basés
              sur notre meilleure évaluation des matériaux, de la
              main-d&apos;œuvre et des conditions actuellement connues.
            </p>
            <p className="mt-2">
              Les coûts réels peuvent <strong>varier en cours de projet</strong>{" "}
              (découvertes en cours de travaux, ajustements de matériaux,
              modifications demandées par le client, fluctuations des
              prix fournisseurs, etc.).
            </p>
            <p className="mt-2">
              Nous nous engageons à <strong>vous tenir informé en
              continu</strong> de l&apos;avancement, des coûts engagés et
              de tout écart significatif par rapport à cet estimé, afin
              que les décisions soient prises ensemble.
            </p>
          </section>
        ) : null}

        {data.valid_until ? (
          <p className="mt-3 text-center text-xs text-white/50">
            Valide jusqu&apos;au{" "}
            {new Date(data.valid_until).toLocaleDateString("fr-CA", {
              day: "numeric",
              month: "long",
              year: "numeric"
            })}
          </p>
        ) : null}

        {!isFinal ? (
          <section className="mt-6 rounded-xl border border-accent-500/40 bg-accent-500/10 p-6">
            <h2 className="text-base font-semibold text-white">
              Accepter cette soumission
            </h2>
            <p className="mt-1 text-sm text-white/70">
              Entrez votre nom complet et cliquez « J&apos;accepte ». Votre IP
              et l&apos;heure seront enregistrées comme trace.
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
                Signature tracée (obligatoire)
              </label>
              <div className="mt-1">
                <SignaturePad onChange={setSignatureDataUrl} />
              </div>
            </div>

            {error ? (
              <p className="mt-3 text-sm text-rose-300">{error}</p>
            ) : null}

            <div className="mt-5 flex flex-wrap items-center gap-3">
              <button
                type="button"
                onClick={accept}
                disabled={submitting !== null || !signName.trim() || !signatureDataUrl}
                className="inline-flex items-center gap-2 rounded-lg bg-accent-500 px-5 py-3 text-sm font-bold text-brand-950 hover:bg-accent-400 disabled:opacity-60"
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
                onClick={() => setRejectOpen(true)}
                disabled={submitting !== null}
                className="text-sm text-white/60 hover:text-rose-300"
              >
                Refuser
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

      {rejectOpen ? (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4"
          onClick={() => (submitting ? null : setRejectOpen(false))}
        >
          <div
            className="w-full max-w-md rounded-2xl border border-brand-800 bg-brand-950 p-6"
            onClick={(e) => e.stopPropagation()}
          >
            <h3 className="text-lg font-bold text-white">
              Refuser la soumission
            </h3>
            <p className="mt-1 text-xs text-white/60">
              Facultatif : indique la raison pour qu&apos;on puisse
              t&apos;offrir une alternative.
            </p>
            <textarea
              rows={3}
              value={rejectReason}
              onChange={(e) => setRejectReason(e.target.value)}
              placeholder="Trop cher, délai, autre entrepreneur…"
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
