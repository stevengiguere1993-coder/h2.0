"use client";

import { useEffect, useMemo, useState } from "react";
import { ClipboardCheck, CreditCard, Loader2, Store } from "lucide-react";

import { Link } from "@/i18n/navigation";
import { authedFetch } from "@/lib/auth";

type MobilePO = {
  id: number;
  reference: string;
  status: string;
  amount_max: number | null;
  payment_method: string | null;
  description: string | null;
  fournisseur_name: string | null;
  project_name: string | null;
  assigned_name: string | null;
  is_mine: boolean;
  created_at: string;
};

const STATUS_LABELS: Record<string, string> = {
  draft: "Planifié",
  sent: "PO envoyé",
  fulfilled: "Achat créé",
  cancelled: "Annulé"
};

const STATUS_BG: Record<string, string> = {
  draft: "bg-white/10 text-white/70",
  sent: "bg-blue-500/15 text-blue-300",
  fulfilled: "bg-emerald-500/15 text-emerald-300",
  cancelled: "bg-rose-500/15 text-rose-300"
};

const PAYMENT_LABELS: Record<string, string> = {
  bill_to_pay: "Compte fournisseur",
  cheque_horizon: "Chèque Horizon",
  cc_steven: "CC Steven",
  cc_michael: "CC Michael",
  cc_olivier: "CC Olivier",
  cc_christian: "CC Christian"
};

function money(n: number | null): string {
  if (n == null) return "—";
  if (!Number.isFinite(n)) return "—";
  return `${n.toLocaleString("fr-CA", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2
  })} $`;
}

export default function MobilePurchaseOrders() {
  const [items, setItems] = useState<MobilePO[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [scope, setScope] = useState<"mine" | "all">("all");

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const res = await authedFetch("/api/v1/purchase-orders/mobile/list");
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        if (cancelled) return;
        const body = (await res.json()) as MobilePO[];
        const list = Array.isArray(body) ? body : [];
        setItems(list);
        // S'il y a des PO assignés à l'utilisateur, on ouvre sur « Mes PO ».
        if (list.some((p) => p.is_mine)) setScope("mine");
      } catch (err) {
        if (!cancelled) setError((err as Error).message);
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, []);

  const hasMine = items.some((p) => p.is_mine);

  const visible = useMemo(() => {
    const list = items.filter((po) => po.status !== "cancelled");
    const scoped =
      scope === "mine" && hasMine ? list.filter((po) => po.is_mine) : list;
    const rank = (s: string) => (s === "sent" ? 0 : s === "draft" ? 1 : 2);
    return [...scoped].sort((a, b) => {
      const r = rank(a.status) - rank(b.status);
      if (r !== 0) return r;
      return (b.created_at || "").localeCompare(a.created_at || "");
    });
  }, [items, scope, hasMine]);

  return (
    <>
      <header
        className="sticky top-0 z-30 border-b border-brand-800 bg-brand-950/95 px-4 py-3 backdrop-blur"
        style={{ paddingTop: "max(env(safe-area-inset-top), 0.75rem)" }}
      >
        <h1 className="text-base font-bold text-white">Bons de commande</h1>
        <p className="mt-0.5 text-[11px] text-white/50">
          Autorisation d&apos;achat — quoi acheter, où et le montant max.
        </p>
      </header>

      <div className="space-y-3 p-4">
        {hasMine ? (
          <div className="flex gap-1 rounded-xl border border-brand-800 bg-brand-900 p-1">
            {(
              [
                { id: "mine" as const, label: "Mes PO" },
                { id: "all" as const, label: "Tous" }
              ]
            ).map((t) => {
              const active = scope === t.id;
              return (
                <button
                  key={t.id}
                  type="button"
                  onClick={() => setScope(t.id)}
                  className={`flex-1 rounded-lg py-2 text-sm font-semibold transition ${
                    active ? "bg-accent-500 text-brand-950" : "text-white/60"
                  }`}
                >
                  {t.label}
                </button>
              );
            })}
          </div>
        ) : null}

        {loading ? (
          <div className="flex min-h-[30vh] items-center justify-center">
            <Loader2 className="h-5 w-5 animate-spin text-accent-500" />
          </div>
        ) : error ? (
          <p className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-300">
            {error}
          </p>
        ) : visible.length === 0 ? (
          <p className="rounded-xl border border-brand-800 bg-brand-900 px-4 py-6 text-center text-sm text-white/50">
            {scope === "mine"
              ? "Aucun bon de commande ne t'est assigné."
              : "Aucun bon de commande."}
          </p>
        ) : (
          <ul className="space-y-2">
            {visible.map((po) => (
              <li key={po.id}>
                <Link
                  // eslint-disable-next-line @typescript-eslint/no-explicit-any
                  href={`/m/po/${po.id}` as any}
                  className="flex w-full items-start gap-3 rounded-xl border border-brand-800 bg-brand-900 px-4 py-3 text-white"
                >
                  <ClipboardCheck className="mt-0.5 h-5 w-5 flex-shrink-0 text-accent-500" />
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center justify-between gap-2">
                      <p className="truncate font-mono text-sm font-bold text-accent-300">
                        {po.reference}
                      </p>
                      <span
                        className={`flex-shrink-0 rounded-full px-2 py-0.5 text-[10px] font-semibold ${
                          STATUS_BG[po.status] || "bg-white/10 text-white/70"
                        }`}
                      >
                        {STATUS_LABELS[po.status] || po.status}
                      </span>
                    </div>
                    <p className="mt-1 flex items-center gap-1.5 truncate text-sm font-semibold text-white">
                      <Store className="h-3.5 w-3.5 flex-shrink-0 text-white/40" />
                      {po.fournisseur_name || "Fournisseur —"}
                    </p>
                    <p className="mt-0.5 truncate text-[11px] text-white/50">
                      {po.project_name || "(frais généraux)"}
                    </p>
                    <div className="mt-1.5 flex items-center justify-between gap-2">
                      {po.payment_method ? (
                        <span className="inline-flex items-center gap-1 text-[11px] text-white/60">
                          <CreditCard className="h-3 w-3" />
                          {PAYMENT_LABELS[po.payment_method] ||
                            po.payment_method}
                        </span>
                      ) : (
                        <span />
                      )}
                      <span className="text-sm font-bold text-emerald-300">
                        max {money(po.amount_max)}
                      </span>
                    </div>
                  </div>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </div>
    </>
  );
}
