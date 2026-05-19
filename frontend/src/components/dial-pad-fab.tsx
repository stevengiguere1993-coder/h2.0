"use client";

// Bouton flottant (FAB) en bas à droite qui ouvre le DialPad.
// Utilisé dans /telephonie ET dans /app — partout dans le portail
// construction, l'utilisateur peut composer un numéro en deux clics.

import { useState } from "react";
import { Phone } from "lucide-react";

import { DialPad } from "@/components/dial-pad";

export function DialPadFab() {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="fixed bottom-6 right-6 z-40 flex h-14 w-14 items-center justify-center rounded-full bg-emerald-500 text-emerald-950 shadow-2xl transition hover:bg-emerald-400 active:scale-95"
        aria-label="Ouvrir le dial pad"
        title="Composer un numéro"
      >
        <Phone className="h-6 w-6" />
      </button>
      {open ? (
        <div
          className="fixed inset-0 z-50 flex items-end justify-end bg-black/50 p-6"
          onClick={() => setOpen(false)}
        >
          <div
            className="rounded-2xl border border-brand-800 bg-brand-900 p-5 shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          >
            <DialPad onClose={() => setOpen(false)} />
          </div>
        </div>
      ) : null}
    </>
  );
}
