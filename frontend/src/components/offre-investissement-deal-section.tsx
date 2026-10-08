"use client";

/**
 * Section « Pitch deck — offre d'investissement (PowerPoint) » de la page
 * d'un deal du Pipeline, entre l'offre d'achat et le NDA.
 *
 * Au clic « Préparer le deck » : l'assistant (`OffreInvestissementWizard`)
 * charge lui-même ses intrants pré-remplis depuis la fiche d'analyse liée
 * (`GET /lead-analyses/{id}/offre-investissement/defaults`), laisse
 * ajuster textes, dates et photos, puis télécharge le .pptx.
 *
 * Pattern visuel calqué sur `<OfferSection>` / `<NDASection>`.
 */

import { useState } from "react";
import { Presentation } from "lucide-react";

import { OffreInvestissementWizard } from "@/components/leads/OffreInvestissementWizard";

export function OffreInvestissementDealSection({ analysisId }: { analysisId: number }) {
  const [wizardOpen, setWizardOpen] = useState(false);

  return (
    <section className="mt-4 rounded-xl border border-brand-800 bg-brand-900 p-5">
      <div className="flex items-center justify-between gap-2">
        <h2 className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wider text-accent-500">
          <Presentation className="h-4 w-4" />
          Pitch deck — offre d&apos;investissement (PowerPoint)
        </h2>
        <button
          type="button"
          onClick={() => setWizardOpen(true)}
          className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-500 px-3 py-1.5 text-xs font-bold text-white hover:bg-emerald-400"
        >
          <Presentation className="h-3.5 w-3.5" />
          Préparer le deck
        </button>
      </div>

      <p className="mt-1 text-xs text-white/40">
        Gabarit Horizon v3 (16 diapos) rempli depuis la fiche d&apos;analyse liée, ses scénarios
        et le TRI investisseur : chiffres, tableaux, graphiques et échéancier sont calculés ;
        tu ajustes seulement les textes, les dates et les photos avant le téléchargement.
      </p>

      <OffreInvestissementWizard open={wizardOpen} onClose={() => setWizardOpen(false)} analysisId={analysisId} />
    </section>
  );
}
