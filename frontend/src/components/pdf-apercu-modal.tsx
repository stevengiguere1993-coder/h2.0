"use client";

import { useEffect } from "react";
import { ExternalLink, X } from "lucide-react";

/**
 * Aperçu d'un PDF (ou d'une image) en fenêtre modale — Phil 2026-10-04 :
 * « un pop-up avec un X plutôt que d'ouvrir une nouvelle page ».
 * `url` est un object URL (blob chargé avec le jeton) ; le parent le
 * révoque à la fermeture. Échap ou clic hors du cadre ferment aussi.
 */
export function PdfApercuModal({
  url,
  titre,
  onClose
}: {
  url: string;
  titre?: string;
  onClose: () => void;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div
      className="fixed inset-0 z-[100] flex items-center justify-center bg-black/80 p-3 sm:p-6"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-label={titre || "Aperçu du document"}
    >
      <div
        className="flex h-[94vh] w-full max-w-5xl flex-col overflow-hidden rounded-xl border border-brand-700 bg-brand-950 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between gap-3 border-b border-brand-800 px-4 py-2">
          <p className="truncate text-sm font-semibold text-white">
            {titre || "Aperçu"}
          </p>
          <span className="flex flex-shrink-0 items-center gap-1">
            <a
              href={url}
              target="_blank"
              rel="noopener noreferrer"
              className="btn-ghost btn-xs"
              title="Ouvrir dans un nouvel onglet"
            >
              <ExternalLink className="h-4 w-4" />
            </a>
            <button
              type="button"
              onClick={onClose}
              className="btn-ghost btn-xs"
              title="Fermer"
              aria-label="Fermer"
            >
              <X className="h-4 w-4" />
            </button>
          </span>
        </div>
        <iframe
          src={url}
          title={titre || "Aperçu"}
          className="h-full w-full flex-1 bg-white"
        />
      </div>
    </div>
  );
}
