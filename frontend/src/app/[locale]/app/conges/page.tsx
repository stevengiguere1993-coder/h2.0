"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Check,
  ChevronRight,
  Loader2,
  Palmtree,
  X
} from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { useAppLayout } from "../layout";
import { authedFetch } from "@/lib/auth";

type Leave = {
  id: number;
  employe_id: number;
  employe_name: string | null;
  start_at: string;
  end_at: string;
  reason: string | null;
  status: "pending" | "approved" | "rejected" | "cancelled";
  reviewed_by_user_id: number | null;
  reviewed_at: string | null;
  review_note: string | null;
  agenda_event_id: number | null;
  created_at: string;
};

type Tab = "pending" | "approved" | "rejected" | "all";

function fmtRange(s: string, e: string): string {
  const a = new Date(s);
  const b = new Date(e);
  const sameDay = a.toDateString() === b.toDateString();
  const dateOpts: Intl.DateTimeFormatOptions = {
    weekday: "short",
    day: "numeric",
    month: "short",
    year: "numeric"
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

const STATUS_LABELS: Record<string, string> = {
  pending: "En attente",
  approved: "Approuvé",
  rejected: "Refusé",
  cancelled: "Annulé"
};

const STATUS_CLASS: Record<string, string> = {
  pending: "bg-amber-500/15 text-amber-300",
  approved: "bg-emerald-500/15 text-emerald-300",
  rejected: "bg-rose-500/15 text-rose-300",
  cancelled: "bg-white/10 text-white/60"
};

export default function CongesAdminPage() {
  const { onOpenSidebar } = useAppLayout();
  const [items, setItems] = useState<Leave[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("pending");
  const [busy, setBusy] = useState<number | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const q = tab === "all" ? "" : `?status=${tab}`;
      const res = await authedFetch(`/api/v1/leaves${q}`);
      if (!res.ok) throw new Error(`http_${res.status}`);
      setItems((await res.json()) as Leave[]);
    } catch {
      setError("Chargement échoué.");
    } finally {
      setLoading(false);
    }
  }, [tab]);

  useEffect(() => {
    void load();
  }, [load]);

  const counts = useMemo(() => {
    return {
      pending: items.filter((x) => x.status === "pending").length,
      approved: items.filter((x) => x.status === "approved").length,
      rejected: items.filter((x) => x.status === "rejected").length,
      total: items.length
    };
  }, [items]);

  async function decide(id: number, action: "approve" | "reject") {
    let note: string | null = null;
    if (action === "reject") {
      note = prompt("Raison du refus (optionnel) :") || null;
    } else {
      note = prompt("Note pour l'employé (optionnel) :") || null;
    }
    setBusy(id);
    try {
      const res = await authedFetch(`/api/v1/leaves/${id}/${action}`, {
        method: "POST",
        body: JSON.stringify({ note: note || null })
      });
      if (!res.ok) throw new Error();
      await load();
    } catch {
      setError("Action échouée.");
    } finally {
      setBusy(null);
    }
  }

  return (
    <>
      <AppTopbar
        breadcrumbs={[
          { label: "Construction", href: "/app" },
          { label: "Congés" }
        ]}
        onOpenSidebar={onOpenSidebar}
      />

      <div className="p-4 lg:p-6">
        <div className="mb-4 flex rounded-lg border border-brand-800 bg-brand-900 p-1 text-sm">
          {(
            [
              { id: "pending" as Tab, label: `En attente (${counts.pending})` },
              { id: "approved" as Tab, label: "Approuvés" },
              { id: "rejected" as Tab, label: "Refusés" },
              { id: "all" as Tab, label: "Tous" }
            ]
          ).map((t) => (
            <button
              key={t.id}
              type="button"
              onClick={() => setTab(t.id)}
              className={`flex-1 rounded-md px-3 py-1.5 font-semibold transition ${
                tab === t.id
                  ? "bg-accent-500 text-brand-950"
                  : "text-white/70 hover:text-white"
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>

        {error ? (
          <p className="mb-4 rounded-lg border border-rose-500/40 bg-rose-500/10 px-4 py-2 text-sm text-rose-300">
            {error}
          </p>
        ) : null}

        {loading ? (
          <div className="flex min-h-[30vh] items-center justify-center">
            <Loader2 className="h-6 w-6 animate-spin text-accent-500" />
          </div>
        ) : items.length === 0 ? (
          <div className="rounded-2xl border border-dashed border-brand-800 bg-brand-900/40 px-6 py-10 text-center">
            <Palmtree className="mx-auto h-8 w-8 text-white/30" />
            <p className="mt-3 text-sm text-white/60">
              Aucune demande{" "}
              {tab === "pending" ? "en attente" : `${STATUS_LABELS[tab] || ""}`.toLowerCase()}.
            </p>
          </div>
        ) : (
          <ul className="space-y-2">
            {items.map((l) => (
              <li
                key={l.id}
                className="rounded-xl border border-brand-800 bg-brand-900 p-4"
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <p className="text-sm font-semibold text-white">
                        {l.employe_name || `Employé #${l.employe_id}`}
                      </p>
                      <span
                        className={`rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase ${
                          STATUS_CLASS[l.status]
                        }`}
                      >
                        {STATUS_LABELS[l.status]}
                      </span>
                    </div>
                    <p className="mt-1 text-xs text-white/70">
                      {fmtRange(l.start_at, l.end_at)}
                    </p>
                    {l.reason ? (
                      <p className="mt-2 rounded border border-brand-800 bg-brand-950 p-2 text-xs text-white/60">
                        <span className="text-white/40">Raison : </span>
                        {l.reason}
                      </p>
                    ) : null}
                    {l.review_note ? (
                      <p className="mt-2 rounded border border-brand-800 bg-brand-950 p-2 text-xs text-white/60">
                        <span className="text-white/40">Note : </span>
                        {l.review_note}
                      </p>
                    ) : null}
                    <p className="mt-2 text-[10px] text-white/40">
                      Soumise le{" "}
                      {new Date(l.created_at).toLocaleDateString("fr-CA", {
                        day: "numeric",
                        month: "short",
                        year: "numeric",
                        hour: "2-digit",
                        minute: "2-digit"
                      })}
                    </p>
                  </div>

                  {l.status === "pending" ? (
                    <div className="flex flex-shrink-0 gap-2">
                      <button
                        type="button"
                        disabled={busy === l.id}
                        onClick={() => decide(l.id, "approve")}
                        className="inline-flex items-center gap-1 rounded-lg bg-emerald-500 px-3 py-2 text-xs font-bold text-brand-950 disabled:opacity-60"
                      >
                        {busy === l.id ? (
                          <Loader2 className="h-3.5 w-3.5 animate-spin" />
                        ) : (
                          <Check className="h-3.5 w-3.5" />
                        )}
                        Approuver
                      </button>
                      <button
                        type="button"
                        disabled={busy === l.id}
                        onClick={() => decide(l.id, "reject")}
                        className="inline-flex items-center gap-1 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs font-bold text-rose-200 hover:bg-rose-500/20 disabled:opacity-60"
                      >
                        <X className="h-3.5 w-3.5" />
                        Refuser
                      </button>
                    </div>
                  ) : null}
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </>
  );
}
