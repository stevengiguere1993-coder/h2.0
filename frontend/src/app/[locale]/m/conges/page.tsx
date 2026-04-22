"use client";

import { useCallback, useEffect, useState } from "react";
import { Loader2, Palmtree, Plus } from "lucide-react";

import { Link } from "@/i18n/navigation";
import { authedFetch } from "@/lib/auth";

type MyLeave = {
  id: number;
  start_at: string;
  end_at: string;
  reason: string | null;
  status: "pending" | "approved" | "rejected" | "cancelled";
  review_note: string | null;
  created_at: string;
};

const STATUS_LABEL: Record<string, string> = {
  pending: "En attente",
  approved: "Approuvé",
  rejected: "Refusé",
  cancelled: "Annulé"
};

const STATUS_CLASS: Record<string, string> = {
  pending: "bg-amber-500/15 text-amber-300 border-amber-500/40",
  approved: "bg-emerald-500/15 text-emerald-300 border-emerald-500/40",
  rejected: "bg-rose-500/15 text-rose-300 border-rose-500/40",
  cancelled: "bg-white/5 text-white/50 border-brand-800"
};

function fmtRange(s: string, e: string): string {
  const a = new Date(s);
  const b = new Date(e);
  const sameDay = a.toDateString() === b.toDateString();
  const dateOpts: Intl.DateTimeFormatOptions = {
    weekday: "short",
    day: "numeric",
    month: "short"
  };
  const timeOpts: Intl.DateTimeFormatOptions = {
    hour: "2-digit",
    minute: "2-digit"
  };
  if (sameDay) {
    return `${a.toLocaleDateString("fr-CA", dateOpts)} · ${a.toLocaleTimeString(
      "fr-CA",
      timeOpts
    )} → ${b.toLocaleTimeString("fr-CA", timeOpts)}`;
  }
  return `${a.toLocaleDateString("fr-CA", dateOpts)} → ${b.toLocaleDateString(
    "fr-CA",
    dateOpts
  )}`;
}

export default function MobileMesConges() {
  const [items, setItems] = useState<MyLeave[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<number | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await authedFetch("/api/v1/leaves/mine");
      if (!res.ok) throw new Error();
      setItems((await res.json()) as MyLeave[]);
    } catch {
      setError("Chargement échoué.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function cancel(id: number) {
    if (!confirm("Annuler cette demande ?")) return;
    setBusy(id);
    try {
      const res = await authedFetch(`/api/v1/leaves/${id}/cancel`, {
        method: "POST"
      });
      if (!res.ok) throw new Error();
      await load();
    } catch {
      setError("Annulation échouée.");
    } finally {
      setBusy(null);
    }
  }

  return (
    <>
      <header
        className="sticky top-0 z-30 flex items-center justify-between border-b border-brand-800 bg-brand-950/95 px-4 py-3 backdrop-blur"
        style={{ paddingTop: "max(env(safe-area-inset-top), 0.75rem)" }}
      >
        <div className="flex items-center gap-2">
          <Palmtree className="h-4 w-4 text-accent-500" />
          <h1 className="text-base font-bold text-white">Mes congés</h1>
        </div>
        <Link
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          href={"/m/conge" as any}
          className="inline-flex items-center gap-1 rounded-lg bg-accent-500 px-3 py-1.5 text-xs font-bold text-brand-950"
        >
          <Plus className="h-3.5 w-3.5" /> Demander
        </Link>
      </header>

      <div className="p-4">
        {error ? (
          <p className="mb-3 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
            {error}
          </p>
        ) : null}

        {loading ? (
          <div className="flex items-center justify-center py-10">
            <Loader2 className="h-5 w-5 animate-spin text-white/40" />
          </div>
        ) : items.length === 0 ? (
          <div className="rounded-2xl border border-dashed border-brand-800 bg-brand-900/40 px-6 py-10 text-center">
            <Palmtree className="mx-auto h-8 w-8 text-white/30" />
            <p className="mt-3 text-sm text-white/60">
              Aucune demande de congé.
            </p>
            <Link
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
              href={"/m/conge" as any}
              className="mt-4 inline-flex items-center gap-1 rounded-lg bg-accent-500 px-4 py-2 text-sm font-bold text-brand-950"
            >
              <Plus className="h-4 w-4" /> Nouvelle demande
            </Link>
          </div>
        ) : (
          <ul className="space-y-2">
            {items.map((l) => (
              <li
                key={l.id}
                className={`rounded-xl border p-3 ${
                  STATUS_CLASS[l.status]
                }`}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="text-xs font-semibold uppercase tracking-wider">
                    {STATUS_LABEL[l.status]}
                  </span>
                  {l.status === "pending" || l.status === "approved" ? (
                    <button
                      type="button"
                      disabled={busy === l.id}
                      onClick={() => cancel(l.id)}
                      className="text-[10px] uppercase text-white/50 hover:text-rose-300"
                    >
                      {busy === l.id ? "…" : "Annuler"}
                    </button>
                  ) : null}
                </div>
                <p className="mt-1 text-sm font-semibold text-white">
                  {fmtRange(l.start_at, l.end_at)}
                </p>
                {l.reason ? (
                  <p className="mt-1 text-xs text-white/60">
                    <span className="text-white/40">Raison : </span>
                    {l.reason}
                  </p>
                ) : null}
                {l.review_note ? (
                  <p className="mt-1 text-xs text-white/60">
                    <span className="text-white/40">Note : </span>
                    {l.review_note}
                  </p>
                ) : null}
                <p className="mt-1 text-[10px] text-white/40">
                  Soumise le{" "}
                  {new Date(l.created_at).toLocaleDateString("fr-CA", {
                    day: "numeric",
                    month: "short"
                  })}
                </p>
              </li>
            ))}
          </ul>
        )}
      </div>
    </>
  );
}
