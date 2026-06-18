"use client";

import { useEffect, useState } from "react";

import { authedFetch } from "@/lib/auth";

/** Interrupteur de la synchro QuickBooks automatique (OFF par défaut).
 *  À n'activer qu'après la migration de masse validée. */
export function QboAutoSyncToggle() {
  // Défaut « désactivé » (fail-closed, comme le backend). On corrige avec
  // la vraie valeur dès que l'API répond. IMPORTANT : on NE retourne JAMAIS
  // null — sinon la carte est invisible si l'API est lente ou échoue.
  const [enabled, setEnabled] = useState(false);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const r = await authedFetch("/api/v1/qbo/auto-sync");
        if (r.ok && !cancelled) {
          const d = (await r.json()) as { enabled: boolean };
          setEnabled(!!d.enabled);
        }
      } catch {
        /* ignore — reste désactivé (fail-closed) */
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  async function toggle() {
    if (loading) return;
    const next = !enabled;
    setEnabled(next);
    setErr(null);
    try {
      const r = await authedFetch("/api/v1/qbo/auto-sync", {
        method: "PUT",
        body: JSON.stringify({ enabled: next })
      });
      if (!r.ok) {
        const body = await r.text().catch(() => "");
        throw new Error(`HTTP ${r.status} — ${body.slice(0, 400)}`);
      }
    } catch (e) {
      setEnabled(!next);
      setErr((e as Error).message || "Échec de l'enregistrement.");
    }
  }

  return (
    <div className="mt-3 flex flex-wrap items-center gap-3 rounded-2xl border border-brand-800 bg-brand-900 p-5">
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
        {err ? (
          <p className="mt-2 break-words rounded-lg border border-rose-500/40 bg-rose-500/10 px-2 py-1 text-[11px] text-rose-300">
            {err}
          </p>
        ) : null}
      </div>
      <button
        type="button"
        onClick={() => void toggle()}
        disabled={loading}
        className={`flex flex-shrink-0 items-center gap-2 rounded-lg border px-3 py-2 text-sm font-semibold transition disabled:opacity-60 ${
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
        {loading ? "…" : enabled ? "Activée" : "Désactivée"}
      </button>
    </div>
  );
}
