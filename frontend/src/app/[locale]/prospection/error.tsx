"use client";

import { useEffect } from "react";

/**
 * Error boundary du segment Prospection. Évite l'écran noir Next.js
 * quand un composant client throw — affiche un message + bouton de
 * récupération qui re-monte le sous-arbre sans recharger la page.
 */
export default function ProspectionError({
  error,
  reset
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    // Log dans la console pour avoir accès aux détails depuis F12.
    // eslint-disable-next-line no-console
    console.error("[prospection] client-side exception:", error);
  }, [error]);

  return (
    <div className="flex min-h-[60vh] flex-col items-center justify-center px-6 text-center">
      <h2 className="text-base font-semibold text-white">
        Quelque chose s&apos;est mal passé.
      </h2>
      <p className="mt-2 text-sm text-white/60">
        Une erreur a interrompu l&apos;affichage. Essaie de revenir en
        arrière ou de cliquer sur « Réessayer ». Tu n&apos;as rien
        perdu — l&apos;action précédente est déjà sauvegardée si tu
        l&apos;avais terminée.
      </p>
      {error?.message ? (
        <pre className="mt-3 max-w-xl overflow-auto rounded-md border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-left text-[11px] text-rose-200">
          {error.message}
        </pre>
      ) : null}
      <button
        type="button"
        onClick={reset}
        className="mt-4 inline-flex items-center gap-1.5 rounded-lg bg-violet-400 px-4 py-1.5 text-sm font-semibold text-brand-950 shadow hover:bg-violet-300"
      >
        Réessayer
      </button>
    </div>
  );
}
