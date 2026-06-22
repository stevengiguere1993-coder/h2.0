"use client";

import { useState } from "react";
import { CheckCircle2, Loader2 } from "lucide-react";

import { authedFetch } from "@/lib/auth";

// Modes de paiement RÉELS (un achat « à payer »/sur compte devient payé via
// l'un d'eux). Aligné sur le backend (PaymentMethod).
const REAL_PAYMENT_METHODS: { value: string; label: string }[] = [
  { value: "cheque_horizon", label: "Chèque Horizon" },
  { value: "cc_steven", label: "CC Steven Giguère" },
  { value: "cc_michael", label: "CC Michael Villiard" },
  { value: "cc_olivier", label: "CC Olivier Therrien" },
  { value: "cc_christian", label: "CC Christian Villiard" }
];

export type MarkPaidAchat = {
  id: number;
  reference?: string | null;
  description?: string | null;
  payment_method?: string | null;
};

/** Modal réutilisable « Marquer l'achat comme payé » (liste Achats + onglet
 *  Achats d'un projet). POST /api/v1/achats/{id}/mark-paid. */
export function AchatMarkPaidModal({
  achat,
  onClose,
  onSaved
}: {
  achat: MarkPaidAchat;
  onClose: () => void;
  onSaved: (a: { id: number; status?: string; payment_method?: string }) => void;
}) {
  const todayIso = new Date().toISOString().slice(0, 10);
  const initialMethod =
    achat.payment_method && achat.payment_method !== "bill_to_pay"
      ? achat.payment_method
      : "";
  const [method, setMethod] = useState(initialMethod);
  const [paidDate, setPaidDate] = useState(todayIso);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit() {
    if (!method) {
      setError("Choisis un mode de paiement.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const paidIso = new Date(`${paidDate}T12:00:00`).toISOString();
      const res = await authedFetch(`/api/v1/achats/${achat.id}/mark-paid`, {
        method: "POST",
        body: JSON.stringify({ payment_method: method, paid_at: paidIso })
      });
      if (!res.ok) {
        const txt = await res.text();
        let detail = txt;
        try {
          const j = JSON.parse(txt) as { detail?: string };
          if (j.detail) detail = j.detail;
        } catch {
          /* ignore */
        }
        throw new Error(detail.slice(0, 240));
      }
      const updated = (await res.json()) as {
        id: number;
        status?: string;
        payment_method?: string;
      };
      onSaved(updated);
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
      onClick={onClose}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="w-full max-w-md rounded-2xl border border-brand-800 bg-brand-950 p-6 shadow-2xl"
      >
        <h2 className="text-lg font-bold text-white">
          Marquer l&apos;achat comme payé
        </h2>
        <p className="mt-1 text-xs text-white/60">
          {achat.reference || `Achat #${achat.id}`}
          {achat.description ? ` — ${achat.description}` : ""}
        </p>

        <div className="mt-5 space-y-4">
          <div>
            <label className="label">Mode de paiement</label>
            <select
              value={method}
              onChange={(e) => setMethod(e.target.value)}
              className="input"
              autoFocus
            >
              <option value="">— Choisir —</option>
              {REAL_PAYMENT_METHODS.map((m) => (
                <option key={m.value} value={m.value}>
                  {m.label}
                </option>
              ))}
            </select>
            {achat.payment_method === "bill_to_pay" ? (
              <p className="mt-1 text-[11px] text-white/40">
                L&apos;achat était saisi en « à payer / sur compte ». Choisis
                ici la méthode réellement utilisée pour le payer.
              </p>
            ) : null}
          </div>
          <div>
            <label className="label">Date de paiement</label>
            <input
              type="date"
              value={paidDate}
              onChange={(e) => setPaidDate(e.target.value)}
              className="input"
            />
          </div>

          {error ? (
            <p className="rounded-md border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
              {error}
            </p>
          ) : null}
        </div>

        <div className="mt-6 flex justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            disabled={busy}
            className="rounded-lg border border-white/20 px-4 py-2 text-sm text-white/70 hover:bg-white/5"
          >
            Annuler
          </button>
          <button
            type="button"
            onClick={submit}
            disabled={busy || !method}
            className="inline-flex items-center gap-2 rounded-lg bg-emerald-500 px-4 py-2 text-sm font-semibold text-brand-950 hover:bg-emerald-400 disabled:opacity-60"
          >
            {busy ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <CheckCircle2 className="h-4 w-4" />
            )}
            Marquer payé
          </button>
        </div>
      </div>
    </div>
  );
}
