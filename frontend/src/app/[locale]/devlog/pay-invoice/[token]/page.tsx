"use client";

/**
 * Page publique de consultation d'une facture devlog.
 *
 * URL : /devlog/pay-invoice/[token]
 * Pas d'authentification — le token (32 octets URL-safe) authentifie
 * le destinataire et permet d'afficher la facture + télécharger le PDF.
 *
 * Thème clair (slate-50) — pattern inspiré de /devlog/sign-soumission/[token]
 * (PR #473).
 *
 * Méthodes de paiement (mai 2026) :
 *  - Virement Interac (mis en avant en gros bloc principal) : email
 *    destinataire copiable + numéro de facture en référence copiable.
 *  - Chèque (bloc secondaire, en dessous).
 *  - Stripe (carte de crédit) : ne s'affiche QUE si le backend retourne
 *    `stripe_enabled: true`. Désactivé par défaut depuis mai 2026, le
 *    code Stripe reste en place pour réactivation future via env var.
 */

import { useCallback, useEffect, useState } from "react";
import { useParams } from "next/navigation";
import {
  AlertTriangle,
  Check,
  CheckCircle2,
  Copy,
  CreditCard,
  Download,
  FileText,
  Loader2,
  Mail,
  Receipt,
  XCircle
} from "lucide-react";

type InvoiceItem = {
  description: string;
  unit: string | null;
  quantity: number;
  unit_price: number;
  total: number;
};

type PublicInvoice = {
  id: number;
  number: string | null;
  status: string;
  issued_date: string | null;
  due_date: string | null;
  sent_at: string | null;
  paid_at: string | null;
  client_name: string | null;
  client_email: string | null;
  client_address: string | null;
  notes: string | null;
  items: InvoiceItem[];
  sous_total: number;
  tps: number;
  tvq: number;
  total: number;
  payment_instructions: string;
  stripe_enabled: boolean;
  interac_email: string;
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

/**
 * Bouton de copie inline — copie `value` dans le presse-papier et affiche
 * un check pendant 2s. Réutilisé pour l'email Interac et le numéro de
 * facture (référence du virement).
 */
function CopyButton({
  value,
  onCopied,
  label
}: {
  value: string;
  onCopied: (msg: string) => void;
  label: string;
}) {
  const [copied, setCopied] = useState(false);
  const handleCopy = useCallback(async () => {
    try {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        await navigator.clipboard.writeText(value);
      } else {
        // Fallback browsers anciens / contextes non sécurisés.
        const ta = document.createElement("textarea");
        ta.value = value;
        ta.setAttribute("readonly", "");
        ta.style.position = "absolute";
        ta.style.left = "-9999px";
        document.body.appendChild(ta);
        ta.select();
        document.execCommand("copy");
        document.body.removeChild(ta);
      }
      setCopied(true);
      onCopied(`${label} copié`);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      onCopied("Impossible de copier — copiez manuellement.");
    }
  }, [value, label, onCopied]);

  return (
    <button
      type="button"
      onClick={() => void handleCopy()}
      className="inline-flex items-center gap-1.5 rounded-md border border-emerald-300 bg-white px-2.5 py-1.5 text-xs font-semibold text-emerald-800 shadow-sm hover:bg-emerald-50"
      aria-label={`Copier ${label.toLowerCase()}`}
    >
      {copied ? (
        <>
          <Check className="h-3.5 w-3.5" />
          Copié
        </>
      ) : (
        <>
          <Copy className="h-3.5 w-3.5" />
          Copier
        </>
      )}
    </button>
  );
}

export default function PayInvoicePage() {
  const params = useParams<{ token: string }>();
  const token = params.token;

  const [data, setData] = useState<PublicInvoice | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [payLoading, setPayLoading] = useState(false);
  const [payError, setPayError] = useState<string | null>(null);
  const [toast, setToast] = useState<
    | { kind: "success" | "info"; message: string }
    | null
  >(null);

  const showToast = useCallback(
    (message: string, kind: "success" | "info" = "success") => {
      setToast({ kind, message });
      window.setTimeout(() => setToast(null), 2500);
    },
    []
  );

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(
        `/api/v1/public/devlog/invoices/${token}`,
        { cache: "no-store" }
      );
      if (!res.ok) throw new Error(`http_${res.status}`);
      setData((await res.json()) as PublicInvoice);
    } catch {
      setError("Lien invalide.");
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => {
    if (token) void load();
  }, [token, load]);

  // Retour Stripe : ?paid=1 → toast + poll jusqu'à confirmation
  // webhook (statut passe à `payee`). ?cancelled=1 → message neutre.
  // Conservé même si Stripe est OFF, pour réactivation future sans
  // re-toucher au frontend.
  useEffect(() => {
    if (typeof window === "undefined" || !token) return;
    const url = new URL(window.location.href);
    if (url.searchParams.get("paid") === "1") {
      setToast({
        kind: "success",
        message: "Paiement reçu, merci !"
      });
      let attempts = 0;
      const interval = window.setInterval(() => {
        attempts += 1;
        void (async () => {
          try {
            const r = await fetch(
              `/api/v1/public/devlog/invoices/${token}`,
              { cache: "no-store" }
            );
            if (r.ok) {
              const fresh = (await r.json()) as PublicInvoice;
              setData(fresh);
              if (fresh.status === "payee") {
                window.clearInterval(interval);
              }
            }
          } catch {
            /* silencieux — on retentera au prochain tick */
          }
          if (attempts >= 5) window.clearInterval(interval);
        })();
      }, 2000);
      url.searchParams.delete("paid");
      window.history.replaceState({}, "", url.toString());
      return () => window.clearInterval(interval);
    }
    if (url.searchParams.get("cancelled") === "1") {
      setToast({
        kind: "info",
        message: "Paiement annulé, vous pouvez réessayer."
      });
      url.searchParams.delete("cancelled");
      window.history.replaceState({}, "", url.toString());
    }
  }, [token]);

  const startCheckout = useCallback(async () => {
    setPayLoading(true);
    setPayError(null);
    try {
      const res = await fetch(
        `/api/v1/public/devlog/invoices/${token}/checkout-session`,
        { method: "POST", cache: "no-store" }
      );
      if (!res.ok) {
        const detail = await res
          .json()
          .then((b) => (b && b.detail) || null)
          .catch(() => null);
        throw new Error(
          detail || "Impossible de démarrer le paiement en ligne."
        );
      }
      const body = (await res.json()) as { url: string };
      if (!body.url) throw new Error("URL Stripe manquante.");
      window.location.href = body.url;
    } catch (exc) {
      const msg =
        exc instanceof Error
          ? exc.message
          : "Impossible de démarrer le paiement en ligne.";
      setPayError(msg);
      setPayLoading(false);
    }
  }, [token]);

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

  const paid = data.status === "payee";
  const invoiceLabel = data.number ?? `Facture #${data.id}`;
  // Référence à mettre dans la note du virement Interac. On préfère le
  // numéro de facture (lisible humain) ; fallback sur l'ID interne si
  // le numéro est null (cas théorique — une facture envoyée a toujours
  // un numéro).
  const interacReference = data.number ?? `FACTURE-${data.id}`;

  return (
    <div className="min-h-screen bg-slate-50 px-4 py-8">
      <div className="mx-auto max-w-2xl">
        {toast ? (
          <div
            className={
              "mb-4 flex items-start gap-2 rounded-lg border px-4 py-3 text-sm " +
              (toast.kind === "success"
                ? "border-emerald-300 bg-emerald-50 text-emerald-900"
                : "border-slate-300 bg-white text-slate-700")
            }
            role="status"
          >
            {toast.kind === "success" ? (
              <CheckCircle2 className="h-5 w-5 flex-none text-emerald-600" />
            ) : (
              <AlertTriangle className="h-5 w-5 flex-none text-slate-500" />
            )}
            <p className="leading-snug">{toast.message}</p>
          </div>
        ) : null}
        <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm sm:p-8">
          {/* Header */}
          <div className="flex items-start justify-between border-b border-slate-200 pb-4">
            <div>
              <p className="text-xs font-semibold uppercase tracking-wider text-blue-700">
                Horizon Services Immobiliers &middot; Pôle Développement
                logiciel
              </p>
              <h1 className="mt-1 text-2xl font-bold text-slate-900">
                {invoiceLabel}
              </h1>
              {data.client_name ? (
                <p className="mt-2 text-sm text-slate-700">
                  <span className="font-semibold">Facturé à :</span>{" "}
                  {data.client_name}
                </p>
              ) : null}
              {data.client_address ? (
                <p className="text-xs text-slate-500">
                  {data.client_address}
                </p>
              ) : null}
            </div>
            <Receipt className="h-8 w-8 text-blue-700" />
          </div>

          {/* Badge statut payée */}
          {paid ? (
            <div className="mt-4 flex items-center gap-2 rounded-lg border border-emerald-300 bg-emerald-50 px-4 py-3 text-sm text-emerald-900">
              <CheckCircle2 className="h-5 w-5 text-emerald-600" />
              <div>
                <p className="font-bold">Payée le {fmtDate(data.paid_at)}</p>
                <p className="text-xs text-emerald-700">
                  Merci pour votre paiement. Cette facture est acquittée.
                </p>
              </div>
            </div>
          ) : null}

          {/* Dates */}
          <div className="mt-5 grid grid-cols-2 gap-3 text-sm">
            <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
              <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">
                Émise le
              </p>
              <p className="mt-0.5 font-semibold text-slate-800">
                {fmtDate(data.issued_date)}
              </p>
            </div>
            <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
              <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">
                Échéance
              </p>
              <p className="mt-0.5 font-semibold text-slate-800">
                {fmtDate(data.due_date)}
              </p>
            </div>
          </div>

          {/* Items */}
          {data.items.length > 0 ? (
            <section className="mt-6">
              <h2 className="text-xs font-semibold uppercase tracking-wider text-blue-700">
                Détail de la facture
              </h2>
              <div className="mt-2 overflow-hidden rounded-xl border border-slate-200">
                <table className="w-full text-sm">
                  <thead className="bg-slate-100">
                    <tr>
                      <th className="px-3 py-2 text-left font-semibold text-slate-700">
                        Description
                      </th>
                      <th className="px-3 py-2 text-right font-semibold text-slate-700">
                        Qté
                      </th>
                      <th className="px-3 py-2 text-right font-semibold text-slate-700">
                        Prix unit.
                      </th>
                      <th className="px-3 py-2 text-right font-semibold text-slate-700">
                        Total
                      </th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-200">
                    {data.items.map((it, idx) => (
                      <tr key={idx}>
                        <td className="px-3 py-2 text-slate-800">
                          {it.description || "—"}
                          {it.unit ? (
                            <span className="ml-1 text-xs text-slate-500">
                              ({it.unit})
                            </span>
                          ) : null}
                        </td>
                        <td className="px-3 py-2 text-right text-slate-800">
                          {it.quantity}
                        </td>
                        <td className="px-3 py-2 text-right text-slate-800">
                          {fmtMoney(it.unit_price)}
                        </td>
                        <td className="px-3 py-2 text-right text-slate-800">
                          {fmtMoney(it.total)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                  <tfoot>
                    <tr>
                      <td
                        colSpan={3}
                        className="px-3 py-1.5 text-right text-xs text-slate-600"
                      >
                        Sous-total
                      </td>
                      <td className="px-3 py-1.5 text-right text-sm text-slate-800">
                        {fmtMoney(data.sous_total)}
                      </td>
                    </tr>
                    <tr>
                      <td
                        colSpan={3}
                        className="px-3 py-1 text-right text-xs text-slate-600"
                      >
                        TPS (5%)
                      </td>
                      <td className="px-3 py-1 text-right text-sm text-slate-800">
                        {fmtMoney(data.tps)}
                      </td>
                    </tr>
                    <tr>
                      <td
                        colSpan={3}
                        className="px-3 py-1 text-right text-xs text-slate-600"
                      >
                        TVQ (9.975%)
                      </td>
                      <td className="px-3 py-1 text-right text-sm text-slate-800">
                        {fmtMoney(data.tvq)}
                      </td>
                    </tr>
                    <tr className="bg-blue-50">
                      <td
                        colSpan={3}
                        className="px-3 py-3 text-right text-sm font-bold text-blue-900"
                      >
                        Total à payer
                      </td>
                      <td className="px-3 py-3 text-right text-lg font-bold text-blue-900">
                        {fmtMoney(data.total)}
                      </td>
                    </tr>
                  </tfoot>
                </table>
              </div>
            </section>
          ) : null}

          {/* Notes */}
          {data.notes ? (
            <section className="mt-5 rounded-lg border border-slate-200 bg-slate-50 px-4 py-3">
              <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">
                Notes
              </p>
              <p className="mt-1 whitespace-pre-line text-sm text-slate-700">
                {data.notes}
              </p>
            </section>
          ) : null}

          {/* Téléchargement PDF */}
          <div className="mt-6">
            <a
              href={`/api/v1/public/devlog/invoices/${token}/pdf`}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-2 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50"
            >
              <Download className="h-4 w-4" />
              Télécharger la facture en PDF
            </a>
          </div>

          {/* ============================================================ */}
          {/* BLOC PRINCIPAL : Virement Interac (mis en avant)              */}
          {/* ============================================================ */}
          {!paid ? (
            <section className="mt-6 rounded-2xl border-2 border-emerald-400 bg-gradient-to-br from-emerald-50 to-white px-5 py-5 shadow-sm sm:px-6 sm:py-6">
              <div className="flex items-center gap-2">
                <Mail className="h-6 w-6 text-emerald-700" />
                <h2 className="text-xl font-bold text-emerald-900 sm:text-2xl">
                  Payer par virement Interac
                </h2>
              </div>
              <p className="mt-1 text-sm text-emerald-900/80">
                Méthode recommandée — sans frais, instantané.
              </p>

              {/* Montant */}
              <div className="mt-5 rounded-xl border border-emerald-200 bg-white px-4 py-3">
                <p className="text-[10px] font-semibold uppercase tracking-wider text-emerald-700">
                  Montant à envoyer
                </p>
                <p className="mt-1 text-3xl font-bold text-emerald-900 sm:text-4xl">
                  {fmtMoney(data.total)}
                </p>
              </div>

              {/* Email destinataire */}
              <div className="mt-3 rounded-xl border border-emerald-200 bg-white px-4 py-3">
                <p className="text-[10px] font-semibold uppercase tracking-wider text-emerald-700">
                  Envoyer à cette adresse courriel
                </p>
                <div className="mt-1 flex flex-wrap items-center justify-between gap-3">
                  <p className="break-all font-mono text-lg font-bold text-emerald-900 sm:text-xl">
                    {data.interac_email}
                  </p>
                  <CopyButton
                    value={data.interac_email}
                    onCopied={(m) => showToast(m, "success")}
                    label="Courriel"
                  />
                </div>
              </div>

              {/* Référence */}
              <div className="mt-3 rounded-xl border border-emerald-200 bg-white px-4 py-3">
                <p className="text-[10px] font-semibold uppercase tracking-wider text-emerald-700">
                  Référence à inscrire dans la note du virement
                </p>
                <div className="mt-1 flex flex-wrap items-center justify-between gap-3">
                  <p className="break-all font-mono text-lg font-bold text-emerald-900 sm:text-xl">
                    {interacReference}
                  </p>
                  <CopyButton
                    value={interacReference}
                    onCopied={(m) => showToast(m, "success")}
                    label="Référence"
                  />
                </div>
              </div>

              <p className="mt-4 rounded-lg bg-emerald-100/60 px-3 py-2 text-xs text-emerald-900">
                <span className="font-semibold">Bon à savoir :</span> le
                virement est automatiquement accepté (pas de question de
                sécurité à configurer).
              </p>
            </section>
          ) : null}

          {/* ============================================================ */}
          {/* BLOC SECONDAIRE : Autres méthodes (chèque)                    */}
          {/* ============================================================ */}
          {!paid ? (
            <section className="mt-4 rounded-lg border border-slate-200 bg-slate-50 px-4 py-3">
              <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-600">
                Autres méthodes : chèque
              </h3>
              <p className="mt-1.5 text-xs leading-relaxed text-slate-700">
                {data.payment_instructions}
              </p>
              <p className="mt-2 text-xs text-slate-600">
                Pour toute question, écrivez-nous à{" "}
                <a
                  href="mailto:comptabilite@immohorizon.com"
                  className="font-semibold text-slate-800 underline"
                >
                  comptabilite@immohorizon.com
                </a>
                .
              </p>
            </section>
          ) : null}

          {/* ============================================================ */}
          {/* BLOC OPTIONNEL : Stripe — masqué tant que stripe_enabled=false */}
          {/* ============================================================ */}
          {!paid && data.stripe_enabled ? (
            <section className="mt-4">
              <button
                type="button"
                onClick={() => void startCheckout()}
                disabled={payLoading}
                className="flex w-full items-center justify-center gap-2 rounded-xl border border-slate-300 bg-white px-4 py-2.5 text-sm font-semibold text-slate-700 shadow-sm transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {payLoading ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <CreditCard className="h-4 w-4" />
                )}
                {payLoading
                  ? "Redirection vers Stripe…"
                  : "Payer en ligne par carte de crédit"}
              </button>
              {payError ? (
                <p className="mt-2 flex items-start gap-1 text-xs text-rose-700">
                  <AlertTriangle className="h-3.5 w-3.5 flex-none" />
                  <span>{payError}</span>
                </p>
              ) : (
                <p className="mt-2 text-center text-[11px] text-slate-500">
                  Paiement sécurisé par Stripe. Visa, Mastercard, Amex.
                </p>
              )}
            </section>
          ) : null}

          <p className="mt-6 flex items-center justify-center gap-1 border-t border-slate-200 pt-4 text-center text-xs text-slate-500">
            <FileText className="h-3 w-3" />
            Horizon Services Immobiliers &middot; immohorizon.com
          </p>
        </div>
      </div>
    </div>
  );
}
