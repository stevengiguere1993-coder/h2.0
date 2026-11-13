"use client";

/**
 * Périodes de prix de loyer d'un bail — le déclencheur discret sous le
 * loyer dans le tableau des baux (Steven 2026-11-13, point 10 : « il
 * n'est pas possible de changer le prix d'un loyer sans que cela affecte
 * le prix passé […] pouvoir mettre des périodes de prix de loyer »).
 *
 * La fenêtre elle-même (`LoyerPeriodesModal`) vit avec les autres
 * fenêtres des paiements : elle s'ouvre aussi depuis « Corriger » sur une
 * ligne de paiement (même geste partout).
 */

import { useState } from "react";

import { LoyerPeriodesModal } from "@/components/immobilier/paiement-modals";

function fmtDefaut(n: number): string {
  return new Intl.NumberFormat("fr-CA", {
    style: "currency",
    currency: "CAD",
    maximumFractionDigits: 2
  }).format(n);
}

export function LoyerPeriodesInline({
  bailId,
  locataireName,
  fmt = fmtDefaut,
  onChanged,
  onFlash
}: {
  bailId: number | null;
  locataireName?: string | null;
  fmt?: (n: number) => string;
  onChanged?: () => void | Promise<void>;
  onFlash?: (msg: string) => void;
}) {
  const [open, setOpen] = useState(false);
  if (bailId == null) return null;
  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        title="Changer le loyer à partir d'un mois (période de prix) — les mois passés gardent leur prix, le solde ne bouge pas"
        className="mt-0.5 block w-full cursor-pointer text-right font-sans text-[10px] font-normal text-white/60 transition hover:text-white"
      >
        changer le loyer
      </button>
      {open ? (
        <LoyerPeriodesModal
          bailId={bailId}
          locataireName={locataireName}
          fmt={fmt}
          onClose={() => setOpen(false)}
          onChanged={async (msg) => {
            onFlash?.(msg);
            await onChanged?.();
          }}
        />
      ) : null}
    </>
  );
}
