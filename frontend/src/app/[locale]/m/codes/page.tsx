"use client";

/**
 * Mes codes d'accès (Steven 2026-11-13) : les codes qu'un gestionnaire
 * m'a partagés pour un BT, un projet ou quelques jours. Le code reste
 * caché jusqu'à « Afficher » (consultation notée au journal).
 */

import { ChevronLeft, KeyRound } from "lucide-react";

import { Link } from "@/i18n/navigation";
import { MesCodes } from "@/components/immobilier/codes-acces";

export default function MobileMesCodes() {
  return (
    <>
      <header
        className="sticky top-0 z-30 flex items-center gap-2 border-b border-brand-800 bg-brand-950/95 px-4 py-3 backdrop-blur"
        style={{ paddingTop: "max(env(safe-area-inset-top), 0.75rem)" }}
      >
        <Link
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          href={"/m" as any}
          className="btn-ghost btn-xs"
          aria-label="Retour"
        >
          <ChevronLeft className="h-5 w-5" />
        </Link>
        <KeyRound className="h-4 w-4 text-accent-500" />
        <h1 className="text-base font-bold text-white">Mes codes d&apos;accès</h1>
      </header>
      <div className="p-4">
        <MesCodes />
      </div>
    </>
  );
}
