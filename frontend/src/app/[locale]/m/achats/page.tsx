"use client";

import { useEffect, useState } from "react";
import {
  Camera,
  Loader2,
  Receipt,
  ShoppingCart
} from "lucide-react";

import { Link } from "@/i18n/navigation";
import { authedFetch } from "@/lib/auth";

type Achat = {
  id: number;
  reference?: string | null;
  description?: string | null;
  amount?: number | null;
  status?: string | null;
  invoice_date?: string | null;
  created_at?: string | null;
  fournisseur_id?: number | null;
};

const STATUS_LABEL: Record<string, string> = {
  draft: "Brouillon",
  ordered: "Commandée",
  received: "Reçue",
  paid: "Payée",
  cancelled: "Annulée"
};

function money(n: number | null | undefined): string {
  if (n == null) return "—";
  return `${Number(n).toLocaleString("fr-CA", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2
  })} $`;
}

function fmtDate(s: string | null | undefined): string {
  if (!s) return "";
  try {
    const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(s);
    const d = m
      ? new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]))
      : new Date(s);
    return d.toLocaleDateString("fr-CA", {
      day: "2-digit",
      month: "short"
    });
  } catch {
    return s as string;
  }
}

export default function MobileAchats() {
  const [items, setItems] = useState<Achat[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const res = await authedFetch("/api/v1/achats?limit=50");
        if (!res.ok) {
          throw new Error(`HTTP ${res.status}`);
        }
        const body = (await res.json()) as unknown;
        if (!cancelled) {
          setItems(Array.isArray(body) ? (body as Achat[]) : []);
        }
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

  return (
    <>
      <header
        className="sticky top-0 z-30 border-b border-brand-800 bg-brand-950/95 px-4 py-3 backdrop-blur"
        style={{ paddingTop: "max(env(safe-area-inset-top), 0.75rem)" }}
      >
        <h1 className="text-base font-bold text-white">Achats</h1>
      </header>

      <div className="space-y-3 p-4">
        <Link
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          href={"/app/achats/new" as any}
          className="flex w-full items-center gap-3 rounded-xl bg-accent-500 px-4 py-3.5 text-brand-950"
        >
          <Camera className="h-5 w-5" />
          <span className="flex-1 text-left text-sm font-bold">
            Scanner un reçu
          </span>
        </Link>

        {loading ? (
          <div className="flex min-h-[30vh] items-center justify-center">
            <Loader2 className="h-5 w-5 animate-spin text-accent-500" />
          </div>
        ) : error ? (
          <p className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-300">
            {error}
          </p>
        ) : items.length === 0 ? (
          <p className="rounded-xl border border-brand-800 bg-brand-900 px-4 py-6 text-center text-sm text-white/50">
            Aucun achat enregistré.
          </p>
        ) : (
          <ul className="space-y-2">
            {items.map((a) => (
              <li key={a.id}>
                <Link
                  // eslint-disable-next-line @typescript-eslint/no-explicit-any
                  href={`/app/achats/${a.id}` as any}
                  className="flex w-full items-start gap-3 rounded-xl border border-brand-800 bg-brand-900 px-4 py-3 text-white"
                >
                  <ShoppingCart className="mt-0.5 h-5 w-5 flex-shrink-0 text-accent-500" />
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center justify-between gap-2">
                      <p className="truncate text-sm font-semibold">
                        {a.reference || a.description || `Achat #${a.id}`}
                      </p>
                      <p className="flex-shrink-0 text-sm font-bold text-emerald-300">
                        {money(a.amount ?? null)}
                      </p>
                    </div>
                    <div className="mt-0.5 flex items-center gap-2 text-[11px] text-white/60">
                      {a.status ? (
                        <span>
                          {STATUS_LABEL[a.status] || a.status}
                        </span>
                      ) : null}
                      {a.invoice_date ? (
                        <span>· {fmtDate(a.invoice_date)}</span>
                      ) : a.created_at ? (
                        <span>· {fmtDate(a.created_at)}</span>
                      ) : null}
                    </div>
                  </div>
                </Link>
              </li>
            ))}
          </ul>
        )}

        <div className="flex items-center gap-2 pt-3 text-[11px] text-white/40">
          <Receipt className="h-3 w-3" />
          <span>Géré côté bureau dans le portail Construction.</span>
        </div>
      </div>
    </>
  );
}
