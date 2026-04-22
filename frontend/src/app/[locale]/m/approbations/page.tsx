"use client";

import { useCallback, useEffect, useState } from "react";
import {
  Check,
  Clock,
  Loader2,
  ShieldCheck,
  Timer,
  X
} from "lucide-react";

import { Link } from "@/i18n/navigation";
import { authedFetch } from "@/lib/auth";
import { useCurrentUser } from "@/hooks/use-current-user";

type PendingPunch = {
  id: number;
  employe_id: number;
  employe_name: string | null;
  project_id: number | null;
  contact_request_id: number | null;
  started_at: string;
  ended_at: string | null;
  hours: number | null;
  task: string | null;
  notes: string | null;
};

function fmtShift(started: string, ended: string | null): string {
  const s = new Date(started);
  const e = ended ? new Date(ended) : null;
  const dayFmt = s.toLocaleDateString("fr-CA", {
    weekday: "short",
    day: "numeric",
    month: "short"
  });
  const timeOpts: Intl.DateTimeFormatOptions = {
    hour: "2-digit",
    minute: "2-digit"
  };
  const startHm = s.toLocaleTimeString("fr-CA", timeOpts);
  const endHm = e ? e.toLocaleTimeString("fr-CA", timeOpts) : "—";
  return `${dayFmt} · ${startHm} → ${endHm}`;
}

export default function MobileApprobationsPage() {
  const { user } = useCurrentUser();
  const role = user?.role || "employee";
  const isManagerPlus = ["owner", "admin", "manager"].includes(role);

  const [items, setItems] = useState<PendingPunch[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<number | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await authedFetch("/api/v1/punch/pending");
      if (!res.ok) {
        if (res.status === 403) {
          setError("Permissions insuffisantes.");
          setItems([]);
          return;
        }
        throw new Error();
      }
      setItems((await res.json()) as PendingPunch[]);
    } catch {
      setError("Chargement échoué.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (isManagerPlus) void load();
    else setLoading(false);
  }, [isManagerPlus, load]);

  async function decide(id: number, action: "approve" | "reject") {
    if (
      action === "reject" &&
      !confirm("Refuser et supprimer ce punch ?")
    )
      return;
    setBusy(id);
    try {
      const res = await authedFetch(`/api/v1/punch/${id}/${action}`, {
        method: "POST"
      });
      if (!res.ok && res.status !== 204) throw new Error();
      setItems((xs) => xs.filter((x) => x.id !== id));
    } catch {
      setError("Action échouée.");
    } finally {
      setBusy(null);
    }
  }

  if (!isManagerPlus && !loading) {
    return (
      <>
        <Header />
        <div className="p-4">
          <div className="rounded-2xl border border-brand-800 bg-brand-900 p-6 text-center">
            <ShieldCheck className="mx-auto h-8 w-8 text-white/30" />
            <p className="mt-3 text-sm text-white/60">
              Cette section est réservée aux gestionnaires et
              administrateurs.
            </p>
            <Link
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
              href={"/m" as any}
              className="mt-4 inline-block text-xs text-accent-500 hover:underline"
            >
              ← Retour à l&apos;accueil
            </Link>
          </div>
        </div>
      </>
    );
  }

  return (
    <>
      <Header />
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
            <Check className="mx-auto h-8 w-8 text-emerald-400" />
            <p className="mt-3 text-sm text-white/60">
              Tous les punches sont approuvés.
            </p>
          </div>
        ) : (
          <ul className="space-y-2">
            {items.map((p) => (
              <li
                key={p.id}
                className="rounded-xl border border-amber-500/30 bg-amber-500/5 p-3"
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-semibold text-white">
                      {p.employe_name || `Employé #${p.employe_id}`}
                    </p>
                    <p className="mt-0.5 flex items-center gap-1.5 text-xs text-white/70">
                      <Clock className="h-3 w-3" />
                      {fmtShift(p.started_at, p.ended_at)}
                    </p>
                    <p className="mt-1 flex items-center gap-1.5 text-xs text-emerald-300">
                      <Timer className="h-3 w-3" />
                      {p.hours?.toFixed(2) ?? "—"} h
                    </p>
                    {p.task ? (
                      <p className="mt-1 text-xs text-white/50">
                        {p.task}
                      </p>
                    ) : null}
                    {p.notes ? (
                      <p className="mt-1 rounded border border-brand-800 bg-brand-950 p-2 text-xs text-white/60">
                        {p.notes}
                      </p>
                    ) : null}
                  </div>
                </div>
                <div className="mt-3 flex gap-2">
                  <button
                    type="button"
                    disabled={busy === p.id}
                    onClick={() => decide(p.id, "reject")}
                    className="flex flex-1 items-center justify-center gap-1 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs font-bold text-rose-200 hover:bg-rose-500/20 disabled:opacity-60"
                  >
                    {busy === p.id ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    ) : (
                      <X className="h-3.5 w-3.5" />
                    )}
                    Refuser
                  </button>
                  <button
                    type="button"
                    disabled={busy === p.id}
                    onClick={() => decide(p.id, "approve")}
                    className="flex flex-1 items-center justify-center gap-1 rounded-lg bg-emerald-500 px-3 py-2 text-xs font-bold text-brand-950 disabled:opacity-60"
                  >
                    {busy === p.id ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    ) : (
                      <Check className="h-3.5 w-3.5" />
                    )}
                    Approuver
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </>
  );
}

function Header() {
  return (
    <header
      className="sticky top-0 z-30 border-b border-brand-800 bg-brand-950/95 px-4 py-3 backdrop-blur"
      style={{ paddingTop: "max(env(safe-area-inset-top), 0.75rem)" }}
    >
      <div className="flex items-center gap-2">
        <ShieldCheck className="h-4 w-4 text-accent-500" />
        <h1 className="text-base font-bold text-white">
          Approbations de punch
        </h1>
      </div>
      <p className="mt-0.5 text-xs text-white/50">
        Valide ou refuse les heures soumises par l&apos;équipe.
      </p>
    </header>
  );
}
