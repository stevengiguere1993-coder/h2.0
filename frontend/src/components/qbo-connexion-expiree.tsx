"use client";

import { useState } from "react";
import { AlertCircle, Loader2, RefreshCw } from "lucide-react";

import { authedFetch } from "@/lib/auth";

/**
 * Connexion QuickBooks rompue (incident 2026-10-09) : Intuit refuse le
 * jeton enregistré (`invalid_grant`). Rien ne repart tant qu'un
 * administrateur n'a pas refait l'autorisation Intuit — ce bloc remplace
 * le message technique par une explication et le bouton qui lance
 * directement cette autorisation.
 */

/** Vrai si un message d'échec QuickBooks signale une connexion rompue. */
export function estConnexionQboExpiree(message?: string | null): boolean {
  return (
    !!message && /invalid_grant|connexion quickbooks expirée/i.test(message)
  );
}

export function QboConnexionExpiree({
  scope = "construction",
  className = ""
}: {
  /** Connexion à refaire : « construction » = QuickBooks d'Horizon. */
  scope?: string;
  className?: string;
}) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function reconnecter() {
    setBusy(true);
    setErr(null);
    try {
      const res = await authedFetch(
        `/api/v1/qbo/connect?scope=${encodeURIComponent(scope)}`
      );
      if (res.status === 403) {
        throw new Error(
          "Seul un administrateur peut reconnecter QuickBooks."
        );
      }
      if (!res.ok) {
        throw new Error(
          `Impossible de lancer la reconnexion (http_${res.status}).`
        );
      }
      const data = (await res.json()) as { auth_url: string };
      window.location.href = data.auth_url;
    } catch (e) {
      setErr((e as Error).message);
      setBusy(false);
    }
  }

  return (
    <div
      className={`rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 ${className}`}
    >
      <p className="flex items-start gap-2 text-sm text-rose-300">
        <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
        <span>
          La connexion QuickBooks a expiré : QuickBooks refuse le jeton
          enregistré. Reconnecte-la avec ton compte QuickBooks, puis
          relance l&apos;envoi.
        </span>
      </p>
      <button
        type="button"
        onClick={reconnecter}
        disabled={busy}
        className="btn-accent btn-sm mt-2 gap-1.5"
      >
        {busy ? (
          <Loader2 className="h-4 w-4 animate-spin" />
        ) : (
          <RefreshCw className="h-4 w-4" />
        )}
        Reconnecter QuickBooks
      </button>
      {err ? <p className="mt-1 text-xs text-rose-300">{err}</p> : null}
    </div>
  );
}
