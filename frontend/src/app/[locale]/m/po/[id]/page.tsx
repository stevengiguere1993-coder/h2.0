"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import {
  Camera,
  ChevronLeft,
  ClipboardCheck,
  CreditCard,
  Loader2,
  MapPin,
  Store,
  User
} from "lucide-react";

import { Link } from "@/i18n/navigation";
import { authedFetch } from "@/lib/auth";

type POLine = {
  id: number;
  position: number;
  description: string;
  unit: string | null;
  quantity: number;
  unit_price: number;
  total: number;
};

type MobilePODetail = {
  id: number;
  reference: string;
  status: string;
  amount_max: number | null;
  payment_method: string | null;
  description: string | null;
  fournisseur_name: string | null;
  project_name: string | null;
  project_address: string | null;
  assigned_name: string | null;
  is_mine: boolean;
  notes: string | null;
  sent_at: string | null;
  created_at: string;
  items: POLine[];
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
  bill_to_pay: "Facture à payer (compte fournisseur — un ou plusieurs paiements)",
  cheque_horizon: "Compte chèque Horizon",
  cc_steven: "CC Horizon Steven Giguère",
  cc_michael: "CC Horizon Michael Villiard",
  cc_olivier: "CC Horizon Olivier Therrien",
  cc_christian: "CC Horizon Christian Villiard"
};

function money(n: number | null): string {
  if (n == null || !Number.isFinite(n)) return "—";
  return `${n.toLocaleString("fr-CA", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2
  })} $`;
}

function qty(n: number): string {
  if (!Number.isFinite(n)) return String(n);
  return n.toLocaleString("fr-CA", { maximumFractionDigits: 2 });
}

export default function MobilePurchaseOrderDetail() {
  const params = useParams<{ id: string }>();
  const id = Number(params.id);

  const [po, setPo] = useState<MobilePODetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!Number.isFinite(id)) return;
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const res = await authedFetch(`/api/v1/purchase-orders/mobile/${id}`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        if (cancelled) return;
        setPo((await res.json()) as MobilePODetail);
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
  }, [id]);

  return (
    <>
      <header
        className="sticky top-0 z-30 border-b border-brand-800 bg-brand-950/95 px-4 py-3 backdrop-blur"
        style={{ paddingTop: "max(env(safe-area-inset-top), 0.75rem)" }}
      >
        <Link
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          href={"/m/po" as any}
          className="inline-flex items-center gap-1 text-sm text-white/60"
        >
          <ChevronLeft className="h-4 w-4" /> Bons de commande
        </Link>
      </header>

      {loading ? (
        <div className="flex min-h-[40vh] items-center justify-center">
          <Loader2 className="h-5 w-5 animate-spin text-accent-500" />
        </div>
      ) : error ? (
        <p className="m-4 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-300">
          {error}
        </p>
      ) : !po ? (
        <p className="m-4 text-sm text-white/50">Bon de commande introuvable.</p>
      ) : (
        <div className="space-y-3 p-4">
          <div className="rounded-2xl border border-brand-800 bg-brand-900 p-4">
            <div className="flex items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <ClipboardCheck className="h-5 w-5 text-accent-500" />
                <span className="font-mono text-lg font-bold text-accent-300">
                  {po.reference}
                </span>
              </div>
              <span
                className={`rounded-full px-2.5 py-1 text-[11px] font-semibold ${
                  STATUS_BG[po.status] || "bg-white/10 text-white/70"
                }`}
              >
                {STATUS_LABELS[po.status] || po.status}
              </span>
            </div>

            {po.is_mine ? (
              <p className="mt-2 inline-flex items-center gap-1 rounded-md bg-accent-500/15 px-2 py-0.5 text-[11px] font-semibold text-accent-300">
                Assigné à toi
              </p>
            ) : null}

            <div className="mt-4 rounded-xl bg-emerald-500/10 px-4 py-3 text-center">
              <p className="text-[11px] uppercase tracking-wider text-emerald-300/70">
                Montant maximum autorisé
              </p>
              <p className="mt-0.5 text-2xl font-bold text-emerald-300">
                {money(po.amount_max)}
              </p>
            </div>

            <dl className="mt-4 space-y-3 text-sm">
              <div className="flex items-start gap-3">
                <Store className="mt-0.5 h-4 w-4 flex-shrink-0 text-white/40" />
                <div>
                  <dt className="text-[11px] uppercase tracking-wider text-white/40">
                    Fournisseur
                  </dt>
                  <dd className="font-semibold text-white">
                    {po.fournisseur_name || "—"}
                  </dd>
                </div>
              </div>
              {po.payment_method ? (
                <div className="flex items-start gap-3">
                  <CreditCard className="mt-0.5 h-4 w-4 flex-shrink-0 text-white/40" />
                  <div>
                    <dt className="text-[11px] uppercase tracking-wider text-white/40">
                      Mode de paiement
                    </dt>
                    <dd className="font-semibold text-white">
                      {PAYMENT_LABELS[po.payment_method] || po.payment_method}
                    </dd>
                  </div>
                </div>
              ) : null}
              <div className="flex items-start gap-3">
                <MapPin className="mt-0.5 h-4 w-4 flex-shrink-0 text-white/40" />
                <div>
                  <dt className="text-[11px] uppercase tracking-wider text-white/40">
                    Projet
                  </dt>
                  <dd className="font-semibold text-white">
                    {po.project_name || "(frais généraux)"}
                  </dd>
                  {po.project_address ? (
                    <dd className="text-xs text-white/50">
                      {po.project_address}
                    </dd>
                  ) : null}
                </div>
              </div>
              {po.assigned_name ? (
                <div className="flex items-start gap-3">
                  <User className="mt-0.5 h-4 w-4 flex-shrink-0 text-white/40" />
                  <div>
                    <dt className="text-[11px] uppercase tracking-wider text-white/40">
                      Assigné à
                    </dt>
                    <dd className="font-semibold text-white">
                      {po.assigned_name}
                    </dd>
                  </div>
                </div>
              ) : null}
            </dl>

            {po.description ? (
              <div className="mt-4 border-t border-brand-800 pt-3">
                <p className="text-[11px] uppercase tracking-wider text-white/40">
                  Description
                </p>
                <p className="mt-1 whitespace-pre-wrap text-sm text-white/80">
                  {po.description}
                </p>
              </div>
            ) : null}
            {po.notes ? (
              <div className="mt-3 border-t border-brand-800 pt-3">
                <p className="text-[11px] uppercase tracking-wider text-white/40">
                  Notes
                </p>
                <p className="mt-1 whitespace-pre-wrap text-sm text-white/80">
                  {po.notes}
                </p>
              </div>
            ) : null}
          </div>

          {po.items.length > 0 ? (
            <div className="rounded-2xl border border-brand-800 bg-brand-900 p-4">
              <p className="text-sm font-semibold text-white">
                Articles à acheter
              </p>
              <ul className="mt-3 divide-y divide-brand-800">
                {po.items.map((it) => (
                  <li
                    key={it.id}
                    className="flex items-start justify-between gap-3 py-2.5"
                  >
                    <div className="min-w-0 flex-1">
                      <p className="text-sm text-white">{it.description}</p>
                      <p className="mt-0.5 text-[11px] text-white/50">
                        {qty(it.quantity)}
                        {it.unit ? ` ${it.unit}` : ""} × {money(it.unit_price)}
                      </p>
                    </div>
                    <span className="flex-shrink-0 text-sm font-semibold text-white">
                      {money(it.total)}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}

          {po.status !== "fulfilled" && po.status !== "cancelled" ? (
            <Link
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
              href={"/app/achats/new" as any}
              className="flex w-full items-center gap-3 rounded-xl bg-accent-500 px-4 py-3.5 text-brand-950"
            >
              <Camera className="h-5 w-5" />
              <span className="flex-1 text-left text-sm font-bold">
                Scanner la facture (créer l&apos;achat)
              </span>
            </Link>
          ) : null}

          <p className="pt-1 text-center text-[11px] text-white/40">
            La conversion en achat et l&apos;envoi du PO se font depuis le
            portail bureau.
          </p>
        </div>
      )}
    </>
  );
}
