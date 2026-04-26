"use client";

import { useEffect } from "react";
import { AlertTriangle, RotateCcw } from "lucide-react";

export default function MobileError({
  error,
  reset
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    // eslint-disable-next-line no-console
    console.error("[mobile] runtime error:", error);
  }, [error]);

  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-4 bg-brand-950 px-6 text-center text-white">
      <AlertTriangle className="h-10 w-10 text-amber-400" />
      <h1 className="text-base font-bold">Une erreur est survenue</h1>
      <p className="max-w-xs text-xs text-white/60">
        L&apos;application a rencontré un problème en chargeant cette
        page. Tu peux réessayer ou revenir à l&apos;accueil.
      </p>
      {error.message ? (
        <p className="max-w-xs break-words rounded-md bg-brand-900 px-3 py-2 font-mono text-[10px] text-white/40">
          {error.message}
        </p>
      ) : null}
      <div className="flex gap-2">
        <button
          type="button"
          onClick={() => reset()}
          className="inline-flex items-center gap-1.5 rounded-md bg-accent-500 px-3 py-2 text-xs font-semibold text-brand-950"
        >
          <RotateCcw className="h-3.5 w-3.5" />
          Réessayer
        </button>
        <a
          href="/m"
          className="inline-flex items-center rounded-md border border-brand-800 bg-brand-900 px-3 py-2 text-xs text-white/80"
        >
          Accueil
        </a>
      </div>
    </main>
  );
}
