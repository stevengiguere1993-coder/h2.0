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
 * Pas de bouton "Payer maintenant" pour l'instant : Stripe arrivera dans
 * une PR ultérieure. Le client paie hors-ligne (virement / chèque) et
 * Phil marque la facture comme payée depuis le portail interne.
 */

import { useCallback, useEffect, useState } from "react";
import { useParams } from "next/navigation";
import {
  CheckCircle2,
  Download,
  FileText,
  Loader2,
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

export default function PayInvoicePage() {
  const params = useParams<{ token: string }>();
  const token = params.token;

  const [data, setData] = useState<PublicInvoice | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

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

  return (
    <div className="min-h-screen bg-slate-50 px-4 py-8">
      <div className="mx-auto max-w-2xl">
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

          {/* Comment payer */}
          {!paid ? (
            <section className="mt-6 rounded-xl border border-blue-200 bg-blue-50 px-4 py-4">
              <h3 className="text-sm font-bold text-blue-900">
                Comment payer ?
              </h3>
              <p className="mt-2 text-sm leading-relaxed text-blue-900">
                {data.payment_instructions}
              </p>
              <p className="mt-3 text-xs text-blue-800">
                Pour toute question, écrivez-nous à{" "}
                <a
                  href="mailto:comptabilite@immohorizon.com"
                  className="font-semibold underline"
                >
                  comptabilite@immohorizon.com
                </a>
                .
              </p>
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
