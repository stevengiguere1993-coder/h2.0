"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Banknote,
  CreditCard,
  FileSignature,
  Landmark,
  Loader2,
  Plus,
  Sparkles,
  Trash2,
  Wallet
} from "lucide-react";

import { authedFetch } from "@/lib/auth";
import { useConfirm } from "@/components/confirm-dialog";

type Payment = {
  id: number;
  facture_id: number;
  amount: number;
  method: PaymentMethod;
  paid_at: string;
  reference: string | null;
  notes: string | null;
  qbo_payment_id: string | null;
  created_at: string;
};

type PaymentMethod =
  | "cash"
  | "credit_card"
  | "debit_card"
  | "check"
  | "bank_transfer"
  | "other";

const METHOD_LABELS: Record<PaymentMethod, string> = {
  cash: "Argent comptant",
  credit_card: "Carte de crédit",
  debit_card: "Carte de débit",
  check: "Chèque",
  bank_transfer: "Virement bancaire",
  other: "Paiement direct"
};

const METHOD_ICONS: Record<
  PaymentMethod,
  React.ComponentType<{ className?: string }>
> = {
  cash: Banknote,
  credit_card: CreditCard,
  debit_card: Wallet,
  check: FileSignature,
  bank_transfer: Landmark,
  other: Sparkles
};

function money(n: number): string {
  return new Intl.NumberFormat("fr-CA", {
    style: "currency",
    currency: "CAD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2
  }).format(n);
}

function today(): string {
  const d = new Date();
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

export function PaymentsPanel({
  factureId,
  factureTotal,
  onStatusMayHaveChanged
}: {
  factureId: number;
  factureTotal: number;
  onStatusMayHaveChanged?: () => void;
}) {
  const confirm = useConfirm();
  const [payments, setPayments] = useState<Payment[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [modalOpen, setModalOpen] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await authedFetch(
        `/api/v1/factures/${factureId}/payments`
      );
      if (!res.ok) throw new Error(`http_${res.status}`);
      setPayments((await res.json()) as Payment[]);
    } catch {
      setError("Chargement des paiements échoué.");
    } finally {
      setLoading(false);
    }
  }, [factureId]);

  useEffect(() => {
    void load();
  }, [load]);

  const paidSum = useMemo(
    () => payments.reduce((s, p) => s + Number(p.amount || 0), 0),
    [payments]
  );
  const balance = Math.max(0, factureTotal - paidSum);
  const progress =
    factureTotal > 0 ? Math.min(100, (paidSum / factureTotal) * 100) : 0;

  async function remove(pid: number) {
    if (!(await confirm("Supprimer ce paiement ?"))) return;
    try {
      const res = await authedFetch(
        `/api/v1/factures/${factureId}/payments/${pid}`,
        { method: "DELETE" }
      );
      if (!res.ok && res.status !== 204) throw new Error();
      setPayments((xs) => xs.filter((x) => x.id !== pid));
      onStatusMayHaveChanged?.();
    } catch {
      setError("Suppression échouée.");
    }
  }

  return (
    <section className="rounded-xl border border-brand-800 bg-brand-900 p-5">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-accent-500">
          Paiements
        </h2>
        <button
          type="button"
          onClick={() => setModalOpen(true)}
          className="btn-accent text-xs"
        >
          <Plus className="mr-1.5 h-3.5 w-3.5" /> Enregistrer un paiement
        </button>
      </div>

      {/* Progress */}
      <div className="mt-4">
        <div className="flex items-end justify-between text-xs text-white/70">
          <span>
            Reçu :{" "}
            <strong className="text-emerald-300">{money(paidSum)}</strong>
          </span>
          <span>
            Solde :{" "}
            <strong className={balance > 0 ? "text-rose-300" : "text-emerald-300"}>
              {money(balance)}
            </strong>
          </span>
        </div>
        <div className="mt-2 h-2 overflow-hidden rounded-full bg-brand-950">
          <div
            className="h-full bg-gradient-to-r from-emerald-500 to-accent-500 transition-all"
            style={{ width: `${progress}%` }}
          />
        </div>
        <p className="mt-1 text-[10px] text-white/40">
          Total facture : {money(factureTotal)} · {progress.toFixed(0)} % réglé
        </p>
      </div>

      {error ? (
        <p className="mt-3 text-sm text-rose-300">{error}</p>
      ) : null}

      {/* List */}
      <div className="mt-5">
        {loading ? (
          <div className="flex items-center justify-center py-6">
            <Loader2 className="h-5 w-5 animate-spin text-white/40" />
          </div>
        ) : payments.length === 0 ? (
          <p className="rounded-lg border border-dashed border-brand-800 bg-brand-950/40 px-4 py-6 text-center text-xs text-white/50">
            Aucun paiement enregistré.
          </p>
        ) : (
          <ul className="divide-y divide-brand-800">
            {payments.map((p) => {
              const Icon = METHOD_ICONS[p.method];
              return (
                <li
                  key={p.id}
                  className="flex items-center justify-between gap-3 py-3 text-sm"
                >
                  <div className="flex items-center gap-3">
                    <Icon className="h-4 w-4 text-white/60" />
                    <div>
                      <p className="font-semibold text-white">
                        {money(Number(p.amount))}
                      </p>
                      <p className="text-xs text-white/50">
                        {METHOD_LABELS[p.method]} · {p.paid_at}
                        {p.reference ? ` · Réf. ${p.reference}` : ""}
                      </p>
                    </div>
                  </div>
                  <button
                    type="button"
                    onClick={() => remove(p.id)}
                    className="rounded-md p-1.5 text-rose-400 hover:bg-rose-500/10 hover:text-rose-300"
                    aria-label="Supprimer"
                  >
                    <Trash2 className="h-4 w-4" />
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </div>

      {modalOpen ? (
        <PaymentModal
          factureId={factureId}
          defaultAmount={balance}
          onClose={() => setModalOpen(false)}
          onCreated={(p) => {
            setPayments((xs) => [...xs, p]);
            setModalOpen(false);
            onStatusMayHaveChanged?.();
          }}
        />
      ) : null}
    </section>
  );
}

function PaymentModal({
  factureId,
  defaultAmount,
  onClose,
  onCreated
}: {
  factureId: number;
  defaultAmount: number;
  onClose: () => void;
  onCreated: (p: Payment) => void;
}) {
  const [method, setMethod] = useState<PaymentMethod>("bank_transfer");
  const [amount, setAmount] = useState(
    defaultAmount > 0 ? defaultAmount.toFixed(2) : ""
  );
  const [paidAt, setPaidAt] = useState(today());
  const [reference, setReference] = useState("");
  const [notes, setNotes] = useState("");
  const [sendStatement, setSendStatement] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit() {
    if (!amount || Number(amount) <= 0) {
      setError("Montant requis.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const res = await authedFetch(
        `/api/v1/factures/${factureId}/payments`,
        {
          method: "POST",
          body: JSON.stringify({
            amount: Number(amount),
            method,
            paid_at: paidAt,
            reference: reference.trim() || null,
            notes: notes.trim() || null,
            send_statement: sendStatement
          })
        }
      );
      if (!res.ok) {
        const txt = await res.text();
        throw new Error(txt.slice(0, 240) || `http_${res.status}`);
      }
      const created = (await res.json()) as Payment;
      onCreated(created);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const methods: { id: PaymentMethod; label: string }[] = [
    { id: "cash", label: "Argent comptant" },
    { id: "credit_card", label: "Carte de crédit" },
    { id: "debit_card", label: "Carte de débit" },
    { id: "check", label: "Chèque" },
    { id: "bank_transfer", label: "Virement bancaire" },
    { id: "other", label: "Paiement direct" }
  ];

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto overscroll-contain bg-black/70 p-4 sm:items-center"
      onClick={() => (!busy ? onClose() : null)}
    >
      <div
        className="my-auto max-h-[calc(100dvh-2rem)] w-full max-w-xl overflow-y-auto overscroll-contain rounded-2xl border border-brand-800 bg-brand-950 p-6"
        onClick={(e) => e.stopPropagation()}
      >
        <h3 className="text-lg font-bold text-white">
          Enregistrer un paiement
        </h3>
        <div className="mt-5 space-y-4">
          <div>
            <label className="label">Méthode de paiement</label>
            <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-3">
              {methods.map((m) => {
                const Icon = METHOD_ICONS[m.id];
                const active = method === m.id;
                return (
                  <button
                    key={m.id}
                    type="button"
                    onClick={() => setMethod(m.id)}
                    className={`flex flex-col items-center gap-2 rounded-lg border px-3 py-3 text-xs font-medium transition ${
                      active
                        ? "border-accent-500 bg-accent-500/10 text-white"
                        : "border-brand-800 bg-brand-900 text-white/70 hover:border-brand-700"
                    }`}
                  >
                    <Icon className="h-5 w-5" />
                    <span>{m.label}</span>
                  </button>
                );
              })}
            </div>
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <label htmlFor="pm_amount" className="label">
                Montant (CAD)
              </label>
              <input
                id="pm_amount"
                type="number"
                step="0.01"
                min="0"
                value={amount}
                onChange={(e) => setAmount(e.target.value)}
                className="input"
                autoFocus
              />
            </div>
            <div>
              <label htmlFor="pm_date" className="label">
                Date du paiement
              </label>
              <input
                id="pm_date"
                type="date"
                value={paidAt}
                onChange={(e) => setPaidAt(e.target.value)}
                className="input"
              />
            </div>
          </div>

          <div>
            <label htmlFor="pm_ref" className="label">
              Numéro de référence
            </label>
            <input
              id="pm_ref"
              type="text"
              value={reference}
              onChange={(e) => setReference(e.target.value)}
              placeholder="Ex. No. de chèque, transaction #…"
              className="input"
            />
          </div>

          <div>
            <label htmlFor="pm_notes" className="label">
              Notes
            </label>
            <textarea
              id="pm_notes"
              rows={2}
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              className="input"
            />
          </div>

          <label className="flex cursor-pointer items-start gap-2 rounded-lg border border-brand-800 bg-brand-900/40 p-3 hover:border-accent-500/40">
            <input
              type="checkbox"
              checked={sendStatement}
              onChange={(e) => setSendStatement(e.target.checked)}
              className="mt-0.5"
            />
            <span className="text-sm">
              <span className="block font-medium text-white">
                Envoyer l&apos;état de compte au client
              </span>
              <span className="mt-0.5 block text-[11px] text-white/60">
                Le relevé à jour (factures, paiements, solde) est
                expédié par courriel au client après l&apos;enregistrement
                du paiement.
              </span>
            </span>
          </label>

          {error ? (
            <p className="text-sm text-rose-300">{error}</p>
          ) : null}
        </div>

        <div className="mt-6 flex items-center justify-end gap-3">
          <button
            type="button"
            onClick={onClose}
            disabled={busy}
            className="btn-secondary text-sm"
          >
            Annuler
          </button>
          <button
            type="button"
            onClick={submit}
            disabled={busy}
            className="btn-accent text-sm disabled:opacity-60"
          >
            {busy ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" /> Création…
              </>
            ) : (
              "Créer le paiement"
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
