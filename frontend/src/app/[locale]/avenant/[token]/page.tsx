"use client";

// Page PUBLIQUE de signature d'un avenant de devis (lien tokenisé envoyé
// au client) — même mécanique que /soumission/[token] : signature tracée
// obligatoire, nom, IP et heure comme trace (retour Phil 2026-09-30).

import { useEffect, useMemo, useState } from "react";
import { useParams } from "next/navigation";
import { CheckCircle2, FileText, Loader2, XCircle } from "lucide-react";

import { SignaturePad } from "@/components/signature-pad";

type Snap = {
  description?: string;
  unit?: string | null;
  quantity?: number;
  unit_price?: number;
  total?: number;
};

type Change = {
  op: string;
  label: string;
  description: string;
  avant: Snap | null;
  apres: Snap | null;
};

type PublicAvenant = {
  reference: string;
  soumission_reference: string;
  title: string;
  note: string | null;
  status: string;
  signed_name: string | null;
  signed_at: string | null;
  changes: Change[];
  contrat_avant: number;
  impact: number;
  contrat_apres: number;
  tps: number;
  tvq: number;
  total_apres: number;
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

function line(s: Snap | null | undefined): string {
  if (!s) return "—";
  const q = Number(s.quantity || 0);
  const up = Number(s.unit_price || 0);
  const t = Number(s.total || 0);
  return `${q}${s.unit ? ` ${s.unit}` : ""} × ${money(up)} = ${money(t)}`;
}

export default function PublicAvenantPage() {
  const params = useParams<{ token: string }>();
  const token = params.token;

  const [data, setData] = useState<PublicAvenant | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [signName, setSignName] = useState("");
  const [signatureDataUrl, setSignatureDataUrl] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState<"sign" | "decline" | null>(null);
  const [declineOpen, setDeclineOpen] = useState(false);
  const [declineReason, setDeclineReason] = useState("");

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const res = await fetch(`/api/v1/public/avenants/${token}`, { cache: "no-store" });
        if (!res.ok) throw new Error(`http_${res.status}`);
        if (!cancelled) setData((await res.json()) as PublicAvenant);
      } catch {
        if (!cancelled) setError("Lien invalide ou expiré.");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    if (token) void load();
    return () => {
      cancelled = true;
    };
  }, [token]);

  const pdfUrl = useMemo(() => (token ? `/api/v1/public/avenants/${token}/pdf` : ""), [token]);

  async function extractError(res: Response): Promise<string> {
    try {
      const body = (await res.json()) as { detail?: string | { msg?: string }[] };
      if (typeof body.detail === "string") return body.detail;
      if (Array.isArray(body.detail)) return body.detail.map((d) => d.msg || "").filter(Boolean).join(", ");
    } catch {
      /* not JSON */
    }
    return `Erreur serveur (HTTP ${res.status}).`;
  }

  async function sign() {
    if (!signName.trim()) {
      setError("Ton nom complet est requis pour signer.");
      return;
    }
    if (!signatureDataUrl) {
      setError("La signature tracée est obligatoire.");
      return;
    }
    setSubmitting("sign");
    setError(null);
    try {
      const res = await fetch(`/api/v1/public/avenants/${token}/sign`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ name: signName.trim(), signature_image_data_url: signatureDataUrl })
      });
      if (!res.ok) throw new Error(await extractError(res));
      setData((await res.json()) as PublicAvenant);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSubmitting(null);
    }
  }

  async function decline() {
    setSubmitting("decline");
    setError(null);
    try {
      const res = await fetch(`/api/v1/public/avenants/${token}/decline`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ reason: declineReason.trim() || null })
      });
      if (!res.ok) throw new Error(await extractError(res));
      setData((await res.json()) as PublicAvenant);
      setDeclineOpen(false);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSubmitting(null);
    }
  }

  if (loading) {
    return (
      <main className="flex min-h-screen items-center justify-center bg-brand-950 text-white">
        <Loader2 className="h-6 w-6 animate-spin text-white/60" />
      </main>
    );
  }
  if (error && !data) {
    return (
      <main className="flex min-h-screen items-center justify-center bg-brand-950 px-4 text-white">
        <div className="rounded-xl border border-rose-500/40 bg-rose-500/10 p-6 text-center">
          <XCircle className="mx-auto h-8 w-8 text-rose-300" />
          <p className="mt-3 text-white">{error}</p>
        </div>
      </main>
    );
  }
  if (!data) return null;

  const isSigned = data.status === "signe";
  const isDeclined = data.status === "refuse";
  const isFinal = isSigned || isDeclined;

  return (
    <main className="min-h-screen bg-brand-950 py-8 text-white">
      <div className="mx-auto max-w-3xl px-4">
        <header className="text-center">
          <p className="text-xs uppercase tracking-widest text-accent-500">{data.company_name}</p>
          <h1 className="mt-3 text-3xl font-bold">Avenant {data.reference}</h1>
          <p className="mt-1 text-white/70">
            à la soumission {data.soumission_reference} — {data.title}
          </p>
        </header>

        {isSigned ? (
          <div className="mt-6 rounded-xl border border-emerald-500/40 bg-emerald-500/10 p-5 text-emerald-100">
            <div className="flex items-center gap-3">
              <CheckCircle2 className="h-6 w-6 text-emerald-300" />
              <div>
                <p className="font-semibold text-white">Avenant signé</p>
                <p className="text-sm text-emerald-200">
                  Signé par {data.signed_name || "vous"}. Merci ! Une copie signée vous a été envoyée par courriel.
                </p>
              </div>
            </div>
          </div>
        ) : null}
        {isDeclined ? (
          <div className="mt-6 rounded-xl border border-rose-500/40 bg-rose-500/10 p-5 text-rose-100">
            <p className="font-semibold text-white">Avenant refusé</p>
            <p className="text-sm text-rose-200">
              Merci — si vous changez d&apos;idée, contactez-nous à {data.company_email}.
            </p>
          </div>
        ) : null}

        <section className="mt-6 overflow-hidden rounded-xl border border-brand-800 bg-brand-900">
          <div className="flex items-center justify-between border-b border-brand-800 px-5 py-4">
            <h2 className="text-sm font-semibold uppercase tracking-wider text-accent-500">
              Changements au contrat
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
          {data.note ? (
            <p className="border-b border-brand-800 px-5 py-4 text-sm text-white/80">{data.note}</p>
          ) : null}
          <table className="w-full text-sm">
            <thead className="border-b border-brand-800 text-left text-xs uppercase tracking-wider text-white/50">
              <tr>
                <th className="px-5 py-2">Changement</th>
                <th className="px-5 py-2">Description</th>
                <th className="px-5 py-2">Avant</th>
                <th className="px-5 py-2">Après</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-brand-800">
              {data.changes.map((c, i) => (
                <tr key={i}>
                  <td className="px-5 py-3 font-semibold text-white">{c.label}</td>
                  <td className="px-5 py-3 text-white/85">{c.description}</td>
                  <td className="px-5 py-3 text-white/70">{c.op === "ajout" ? "—" : line(c.avant)}</td>
                  <td className="px-5 py-3 text-white/85">
                    {c.op === "retrait" ? <span className="text-rose-300">Retiré</span> : line(c.apres)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="border-t border-brand-800 px-5 py-4">
            <dl className="ml-auto max-w-sm space-y-1 text-sm">
              <div className="flex justify-between text-white/70">
                <dt>Contrat avant cet avenant (HT)</dt>
                <dd>{money(data.contrat_avant)}</dd>
              </div>
              <div className="flex justify-between font-semibold text-white">
                <dt>Impact de l&apos;avenant (HT)</dt>
                <dd className={data.impact >= 0 ? "text-emerald-300" : "text-rose-300"}>
                  {data.impact >= 0 ? "+" : "−"}
                  {money(Math.abs(data.impact))}
                </dd>
              </div>
              <div className="flex justify-between text-white/70">
                <dt>Contrat après (HT)</dt>
                <dd>{money(data.contrat_apres)}</dd>
              </div>
              <div className="flex justify-between text-white/70">
                <dt>TPS (5 %)</dt>
                <dd>{money(data.tps)}</dd>
              </div>
              <div className="flex justify-between text-white/70">
                <dt>TVQ (9,975 %)</dt>
                <dd>{money(data.tvq)}</dd>
              </div>
              <div className="flex justify-between border-t border-brand-800 pt-2 text-base font-bold text-white">
                <dt>Total du contrat</dt>
                <dd>{money(data.total_apres)}</dd>
              </div>
            </dl>
          </div>
        </section>

        {!isFinal ? (
          <section className="mt-6 rounded-xl border border-accent-500/40 bg-accent-500/10 p-6">
            <h2 className="text-base font-semibold text-white">Signer cet avenant</h2>
            <p className="mt-1 text-sm text-white/70">
              Entrez votre nom complet et signez. Votre IP et l&apos;heure seront enregistrées comme trace.
              Toutes les autres conditions de la soumission restent inchangées.
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
              <label className="text-xs text-white/70">Signature tracée (obligatoire)</label>
              <div className="mt-1">
                <SignaturePad onChange={setSignatureDataUrl} />
              </div>
            </div>
            {error ? <p className="mt-3 text-sm text-rose-300">{error}</p> : null}
            <div className="mt-5 flex flex-wrap items-center gap-3">
              <button
                type="button"
                onClick={sign}
                disabled={submitting !== null || !signName.trim() || !signatureDataUrl}
                className="inline-flex items-center gap-2 rounded-lg bg-accent-500 px-5 py-3 text-sm font-bold text-brand-950 hover:bg-accent-400 disabled:opacity-60"
              >
                {submitting === "sign" ? <Loader2 className="h-4 w-4 animate-spin" /> : <CheckCircle2 className="h-4 w-4" />}
                Je signe cet avenant
              </button>
              <button
                type="button"
                onClick={() => setDeclineOpen(true)}
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
          <a className="hover:text-accent-500" href={`mailto:${data.company_email}`}>
            {data.company_email}
          </a>
        </footer>
      </div>

      {declineOpen ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4" onClick={() => setDeclineOpen(false)}>
          <div className="w-full max-w-md rounded-2xl border border-brand-800 bg-brand-900 p-6" onClick={(e) => e.stopPropagation()}>
            <h3 className="text-lg font-bold text-white">Refuser l&apos;avenant</h3>
            <p className="mt-1 text-sm text-white/70">Dites-nous pourquoi (facultatif) : ça nous aide à ajuster.</p>
            <textarea
              rows={3}
              value={declineReason}
              onChange={(e) => setDeclineReason(e.target.value)}
              className="mt-3 w-full rounded-lg border border-brand-800 bg-brand-950 px-3 py-2 text-sm text-white focus:border-accent-500 focus:outline-none"
            />
            <div className="mt-4 flex justify-end gap-3">
              <button type="button" onClick={() => setDeclineOpen(false)} className="text-sm text-white/70 hover:text-white">
                Annuler
              </button>
              <button
                type="button"
                onClick={decline}
                disabled={submitting !== null}
                className="inline-flex items-center gap-2 rounded-lg bg-rose-500 px-4 py-2 text-sm font-semibold text-white hover:bg-rose-600 disabled:opacity-60"
              >
                {submitting === "decline" ? <Loader2 className="h-4 w-4 animate-spin" /> : <XCircle className="h-4 w-4" />}
                Confirmer le refus
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </main>
  );
}
