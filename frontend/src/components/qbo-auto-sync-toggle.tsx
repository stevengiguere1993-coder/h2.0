"use client";

import { useEffect, useState } from "react";

import { authedFetch } from "@/lib/auth";

/** Interrupteur de la synchro QuickBooks automatique (OFF par défaut).
 *  À n'activer qu'après la migration de masse validée. */
export function QboAutoSyncToggle() {
  const [enabled, setEnabled] = useState<boolean | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const r = await authedFetch("/api/v1/qbo/auto-sync");
        if (r.ok && !cancelled) {
          const d = (await r.json()) as { enabled: boolean };
          setEnabled(d.enabled);
        }
      } catch {
        /* ignore */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  async function toggle() {
    if (enabled === null) return;
    const next = !enabled;
    setEnabled(next);
    try {
      const r = await authedFetch("/api/v1/qbo/auto-sync", {
        method: "PUT",
        body: JSON.stringify({ enabled: next })
      });
      if (!r.ok) throw new Error();
    } catch {
      setEnabled(!next);
    }
  }

  if (enabled === null) return null;

  return (
    <div className="mt-3 flex items-center gap-3 rounded-2xl border border-brand-800 bg-brand-900 p-5">
      <div className="min-w-0 flex-1">
        <h2 className="text-base font-bold text-white">
          Synchro QuickBooks automatique
        </h2>
        <p className="mt-0.5 text-xs text-white/60">
          Activée : factures et soumissions partent vers QB à la création, les
          nouveaux clients aussi, et les factures QB reliées à un projet
          reviennent dans Kratos (cron). À n&apos;activer qu&apos;APRÈS la
          migration de masse validée.
        </p>
      </div>
      <button
        type="button"
        onClick={() => void toggle()}
        className={`flex flex-shrink-0 items-center gap-2 rounded-lg border px-3 py-2 text-sm font-semibold transition ${
          enabled
            ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-300"
            : "border-brand-800 bg-brand-950 text-white/60"
        }`}
      >
        <span
          className={`h-2.5 w-2.5 rounded-full ${
            enabled ? "bg-emerald-400" : "bg-white/30"
          }`}
        />
        {enabled ? "Activée" : "Désactivée"}
      </button>
    </div>
  );
}
