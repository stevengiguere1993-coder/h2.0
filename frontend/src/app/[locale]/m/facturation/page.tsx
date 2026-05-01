"use client";

import { useEffect, useMemo, useState } from "react";
import { FileText, Loader2 } from "lucide-react";

import { Link } from "@/i18n/navigation";
import { authedFetch } from "@/lib/auth";

type Facture = {
  id: number;
  reference: string;
  client_id: number | null;
  project_id: number | null;
  total: number | null;
  balance: number | null;
  status: string;
  issued_at: string | null;
  due_at: string | null;
};

const STATUS_LABEL: Record<string, string> = {
  draft: "Brouillon",
  sent: "Envoyée",
  paid: "Payée",
  overdue: "En retard",
  void: "Annulée"
};

const STATUS_CLASS: Record<string, string> = {
  draft: "bg-slate-500/15 text-slate-300 border-slate-500/30",
  sent: "bg-sky-500/15 text-sky-300 border-sky-500/30",
  paid: "bg-emerald-500/15 text-emerald-300 border-emerald-500/30",
  overdue: "bg-rose-500/15 text-rose-300 border-rose-500/30",
  void: "bg-brand-700/30 text-white/40 border-brand-700"
};

function money(n: number | null | undefined): string {
  if (n == null) return "—";
  return `${Number(n).toLocaleString("fr-CA", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2
  })} $`;
}

function fmtDate(s: string | null): string {
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
    return s;
  }
}

const FILTERS = [
  { key: "all", label: "Toutes" },
  { key: "draft", label: "Brouillon" },
  { key: "sent", label: "Envoyée" },
  { key: "overdue", label: "En retard" },
  { key: "paid", label: "Payée" }
] as const;

type FilterKey = (typeof FILTERS)[number]["key"];

export default function MobileFacturation() {
  const [items, setItems] = useState<Facture[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<FilterKey>("all");

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const res = await authedFetch("/api/v1/factures?limit=100");
        if (!res.ok) {
          throw new Error(`HTTP ${res.status}`);
        }
        const body = (await res.json()) as unknown;
        if (!cancelled) {
          setItems(Array.isArray(body) ? (body as Facture[]) : []);
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

  const filtered = useMemo(() => {
    if (filter === "all") return items;
    return items.filter((f) => f.status === filter);
  }, [items, filter]);

  return (
    <>
      <header
        className="sticky top-0 z-30 border-b border-brand-800 bg-brand-950/95 px-4 py-3 backdrop-blur"
        style={{ paddingTop: "max(env(safe-area-inset-top), 0.75rem)" }}
      >
        <h1 className="text-base font-bold text-white">Facturation</h1>
      </header>

      <div className="p-4">
        <div className="flex flex-wrap gap-2 pb-3">
          {FILTERS.map((f) => (
            <button
              key={f.key}
              type="button"
              onClick={() => setFilter(f.key)}
              className={`rounded-full border px-3 py-1.5 text-[11px] font-semibold transition ${
                filter === f.key
                  ? "border-accent-500 bg-accent-500/20 text-accent-300"
                  : "border-brand-800 bg-brand-900 text-white/70"
              }`}
            >
              {f.label}
            </button>
          ))}
        </div>

        {loading ? (
          <div className="flex min-h-[30vh] items-center justify-center">
            <Loader2 className="h-5 w-5 animate-spin text-accent-500" />
          </div>
        ) : error ? (
          <p className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-300">
            {error}
          </p>
        ) : filtered.length === 0 ? (
          <p className="rounded-xl border border-brand-800 bg-brand-900 px-4 py-6 text-center text-sm text-white/50">
            Aucune facture pour ce filtre.
          </p>
        ) : (
          <ul className="space-y-2">
            {filtered.map((f) => (
              <li key={f.id}>
                <Link
                  // eslint-disable-next-line @typescript-eslint/no-explicit-any
                  href={`/app/facturation/${f.id}` as any}
                  className="flex w-full items-start gap-3 rounded-xl border border-brand-800 bg-brand-900 px-4 py-3 text-white"
                >
                  <FileText className="mt-0.5 h-5 w-5 flex-shrink-0 text-accent-500" />
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center justify-between gap-2">
                      <p className="truncate text-sm font-semibold">
                        {f.reference}
                      </p>
                      <p className="flex-shrink-0 text-sm font-bold text-emerald-300">
                        {money(f.total)}
                      </p>
                    </div>
                    <div className="mt-1 flex flex-wrap items-center gap-2 text-[11px]">
                      <span
                        className={`rounded-full border px-2 py-0.5 ${
                          STATUS_CLASS[f.status] ||
                          "border-brand-700 bg-brand-800 text-white/60"
                        }`}
                      >
                        {STATUS_LABEL[f.status] || f.status}
                      </span>
                      {f.issued_at ? (
                        <span className="text-white/60">
                          Émise {fmtDate(f.issued_at)}
                        </span>
                      ) : null}
                      {f.due_at ? (
                        <span className="text-white/60">
                          · Échéance {fmtDate(f.due_at)}
                        </span>
                      ) : null}
                      {f.balance != null && Number(f.balance) > 0 ? (
                        <span className="text-amber-300">
                          · Solde {money(f.balance)}
                        </span>
                      ) : null}
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
