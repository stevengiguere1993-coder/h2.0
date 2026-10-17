"use client";

import { useEffect, useState } from "react";
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
  echecEnregistre = false,
  className = ""
}: {
  /** Connexion à refaire : « construction » = QuickBooks d'Horizon. */
  scope?: string;
  /** Échec lu sur la fiche (envoi passé, d'âge inconnu) plutôt que
   *  résultat de l'envoi qu'on vient de lancer : la connexion a pu être
   *  rétablie depuis (reconnexion, ou jeton périmé d'avant le correctif
   *  du 2026-10-09). L'état réel est alors vérifié avant de demander une
   *  reconnexion. */
  echecEnregistre?: boolean;
  className?: string;
}) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  // null = vérification de l'état réel en cours.
  const [aReconnecter, setAReconnecter] = useState<boolean | null>(
    echecEnregistre ? null : true
  );

  useEffect(() => {
    if (!echecEnregistre) return;
    let annule = false;
    (async () => {
      try {
        const res = await authedFetch(
          `/api/v1/qbo/status?scope=${encodeURIComponent(scope)}`
        );
        if (!res.ok) throw new Error(`http_${res.status}`);
        const s = (await res.json()) as {
          connected: boolean;
          needs_reconnect?: boolean;
        };
        if (!annule) setAReconnecter(!s.connected || !!s.needs_reconnect);
      } catch {
        // État illisible : on garde l'avertissement complet.
        if (!annule) setAReconnecter(true);
      }
    })();
    return () => {
      annule = true;
    };
  }, [echecEnregistre, scope]);

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

  if (aReconnecter === null) return null;
  if (!aReconnecter) {
    // La connexion n'est plus signalée comme expirée : le dernier échec
    // date d'avant son rétablissement, un nouvel envoi suffit.
    return (
      <p className={`text-sm text-rose-300 ${className}`}>
        Dernier échec QuickBooks : la connexion était refusée à ce
        moment-là. Relance l&apos;envoi.
      </p>
    );
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
