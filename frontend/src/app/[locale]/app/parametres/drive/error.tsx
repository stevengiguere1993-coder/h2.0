"use client";

/**
 * Error boundary local pour la page « Gestion documentaire Drive ».
 *
 * Affiche un fallback lisible si une exception client survient dans la
 * page (ex. Phase 4 Conventions). Sans ça, Next.js affiche un message
 * générique « Application error: a client-side exception has occurred ».
 *
 * Voir docs/DRIVE_INTEGRATION.md.
 */
import { useEffect } from "react";

export default function DriveSettingsError({
  error,
  reset
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    // eslint-disable-next-line no-console
    console.error("[drive settings] client exception", error);
  }, [error]);

  return (
    <div className="p-6">
      <section className="rounded-2xl border border-rose-500/40 bg-rose-500/5 p-5 text-sm text-rose-200">
        <h2 className="text-base font-bold text-rose-100">
          Erreur côté client sur la page Drive
        </h2>
        <p className="mt-2 text-xs text-rose-200/80">
          Une exception JavaScript a interrompu le rendu de cette page. Les
          autres pages Kratos restent fonctionnelles. Recharge la page ; si
          l&apos;erreur persiste, signale-le au support avec le message
          ci-dessous.
        </p>
        {error?.message ? (
          <pre className="mt-3 max-h-48 overflow-auto rounded bg-rose-950/40 p-3 font-mono text-[11px] text-rose-100">
            {error.message}
            {error.digest ? `\n\ndigest: ${error.digest}` : ""}
          </pre>
        ) : null}
        <div className="mt-4 flex gap-2">
          <button
            type="button"
            onClick={reset}
            className="rounded-lg bg-rose-500 px-3 py-1.5 text-xs font-semibold text-white hover:bg-rose-600"
          >
            Réessayer
          </button>
          <a
            href="/app/parametres"
            className="rounded-lg border border-white/15 px-3 py-1.5 text-xs text-white/70 hover:bg-white/5"
          >
            Retour aux paramètres
          </a>
        </div>
      </section>
    </div>
  );
}