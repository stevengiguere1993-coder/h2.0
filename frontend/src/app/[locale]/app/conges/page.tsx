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
import { PageDriveSection } from "@/components/drive/PageDriveSection";
import { useAppLayout } from "../layout";
import { authedFetch } from "@/lib/auth";

type Leave = {
  id: number;
  employe_id: number;
  employe_name: string | null;
  kind: "vacation" | "sick" | "personal";
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

const KIND_LABEL: Record<string, string> = {
  vacation: "🌴 Vacances",
  sick: "🤒 Maladie",
  personal: "📋 Personnel"
};
const KIND_COLOR: Record<string, string> = {
  vacation: "bg-emerald-500/15 text-emerald-300 border-emerald-500/40",
  sick: "bg-rose-500/15 text-rose-300 border-rose-500/40",
  personal: "bg-sky-500/15 text-sky-300 border-sky-500/40"
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
  const [logOpen, setLogOpen] = useState(false);

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
          { label: "Administration", href: "/app" },
          { label: "Vacances & congés" }
        ]}
        onOpenSidebar={onOpenSidebar}
      />

      <div className="p-4 lg:p-6">
        <PageDriveSection
          pageKey="page:app:conges"
          pole="Construction"
          label="Congés"
          route="/app/conges"
          className="mb-4"
        />

        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <h1 className="text-xl font-bold text-white">Vacances & congés</h1>
          <button
            type="button"
            onClick={() => setLogOpen(true)}
            className="btn-accent text-xs"
          >
            + Logger une absence employé
          </button>
        </div>
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
                        className={`rounded border px-1.5 py-0.5 text-[10px] font-semibold ${
                          KIND_COLOR[l.kind || "vacation"]
                        }`}
                      >
                        {KIND_LABEL[l.kind || "vacation"]}
                      </span>
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
                        className="btn-outline-rose btn-sm disabled:opacity-60"
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

      {logOpen ? (
        <AdminLogLeaveModal
          onClose={() => setLogOpen(false)}
          onCreated={() => {
            setLogOpen(false);
            void load();
          }}
        />
      ) : null}
    </>
  );
}

function AdminLogLeaveModal({
  onClose,
  onCreated
}: {
  onClose: () => void;
  onCreated: () => void;
}) {
  const [employes, setEmployes] = useState<
    Array<{ id: number; full_name: string }>
  >([]);
  const [employeId, setEmployeId] = useState("");
  const [kind, setKind] = useState<"sick" | "vacation" | "personal">("sick");
  const [startDate, setStartDate] = useState(() => {
    const d = new Date();
    const p = (n: number) => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
  });
  const [endDate, setEndDate] = useState(() => {
    const d = new Date();
    const p = (n: number) => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
  });
  const [reason, setReason] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const res = await authedFetch("/api/v1/employes?limit=500&volet=construction");
      if (!res.ok) return;
      if (!cancelled)
        setEmployes(
          (await res.json()) as Array<{ id: number; full_name: string }>
        );
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  async function submit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!employeId) {
      setError("Choisis un employé.");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const res = await authedFetch("/api/v1/leaves/admin", {
        method: "POST",
        body: JSON.stringify({
          employe_id: Number(employeId),
          kind,
          // 8h-17h Montréal pour avoir un bloc visible
          start_at: new Date(`${startDate}T08:00:00`).toISOString(),
          end_at: new Date(`${endDate}T17:00:00`).toISOString(),
          reason: reason.trim() || null
        })
      });
      if (!res.ok) {
        const t = await res.text();
        throw new Error(t.slice(0, 200) || `http_${res.status}`);
      }
      onCreated();
    } catch (e) {
      setError(`Échec : ${(e as Error).message}`);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4"
      onClick={() => (!submitting ? onClose() : null)}
    >
      <form
        onSubmit={submit}
        onClick={(e) => e.stopPropagation()}
        className="w-full max-w-md space-y-4 rounded-2xl border border-brand-800 bg-brand-950 p-5 text-white"
      >
        <h3 className="text-base font-bold">Logger une absence employé</h3>
        <p className="text-xs text-white/60">
          Auto-approuvé. Crée un bloc agenda pour cet employé pendant la
          période — utile quand un employé appelle malade le matin.
        </p>
        <div>
          <label className="label">Employé</label>
          <select
            value={employeId}
            onChange={(e) => setEmployeId(e.target.value)}
            className="input"
            required
          >
            <option value="">— Choisir —</option>
            {employes.map((e) => (
              <option key={e.id} value={String(e.id)}>
                {e.full_name}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="label">Type</label>
          <div className="grid grid-cols-3 gap-2">
            {(
              [
                { id: "sick" as const, label: "🤒 Maladie" },
                { id: "vacation" as const, label: "🌴 Vacances" },
                { id: "personal" as const, label: "📋 Personnel" }
              ]
            ).map((k) => (
              <button
                key={k.id}
                type="button"
                onClick={() => setKind(k.id)}
                className={`rounded-lg border px-3 py-2 text-xs ${
                  kind === k.id
                    ? "border-accent-500 bg-accent-500/10"
                    : "border-brand-800 bg-brand-900 hover:border-accent-500/50"
                }`}
              >
                {k.label}
              </button>
            ))}
          </div>
        </div>
        <div className="grid gap-3 sm:grid-cols-2">
          <div>
            <label className="label">Du</label>
            <input
              type="date"
              value={startDate}
              onChange={(e) => setStartDate(e.target.value)}
              className="input"
              required
            />
          </div>
          <div>
            <label className="label">Au</label>
            <input
              type="date"
              value={endDate}
              onChange={(e) => setEndDate(e.target.value)}
              className="input"
              required
            />
          </div>
        </div>
        <div>
          <label className="label">Raison / note (optionnel)</label>
          <textarea
            rows={2}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            className="input"
            placeholder="Ex. Grippe — appel ce matin"
          />
        </div>
        {error ? <p className="text-xs text-rose-300">{error}</p> : null}
        <div className="flex items-center justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            disabled={submitting}
            className="btn-secondary text-sm"
          >
            Annuler
          </button>
          <button
            type="submit"
            disabled={submitting}
            className="btn-accent text-sm disabled:opacity-60"
          >
            {submitting ? "Enregistrement…" : "Enregistrer (auto-approuvé)"}
          </button>
        </div>
      </form>
    </div>
  );
}
