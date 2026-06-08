"use client";

/**
 * Section "Offre d'investissement (PowerPoint)" affichée sur la page d'un
 * deal du Pipeline, entre l'offre d'achat et le NDA.
 *
 * Auparavant, la génération du .pptx d'offre investisseur se déclenchait
 * depuis un bouton du header de la fiche d'analyse de lead
 * (`LeadAnalysisDetailModal`). On l'a déplacée ici : le wizard lui-même
 * (`OffreInvestissementWizard`) est inchangé, seul son point d'entrée
 * bouge vers le flow Pipeline.
 *
 * Au clic « Générer le PowerPoint » : on charge la fiche d'analyse liée
 * (`GET /api/v1/lead-analyses/{analysisId}`), on dérive les données du
 * wizard via `buildOffreWizardData`, puis on ouvre le wizard. Un fetch
 * raté affiche une erreur propre sans crasher la page.
 *
 * Pattern visuel strictement calqué sur `<OfferSection>` / `<NDASection>`.
 */

import { useState } from "react";
import { AlertTriangle, Loader2, Presentation } from "lucide-react";

import { authedFetch } from "@/lib/auth";
import {
  OffreInvestissementWizard,
  buildOffreWizardData,
  type OffreInvestissementWizardData,
  type OffreWizardSourceAnalysis
} from "@/components/leads/OffreInvestissementWizard";

export function OffreInvestissementDealSection({
  analysisId
}: {
  analysisId: number;
}) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [wizardOpen, setWizardOpen] = useState(false);
  const [wizardData, setWizardData] =
    useState<OffreInvestissementWizardData | null>(null);

  async function openWizard() {
    if (loading) return;
    setLoading(true);
    setError(null);
    try {
      const res = await authedFetch(`/api/v1/lead-analyses/${analysisId}`);
      if (!res.ok) {
        throw new Error(`HTTP ${res.status}`);
      }
      const analysis = (await res.json()) as OffreWizardSourceAnalysis;
      setWizardData(buildOffreWizardData(analysis));
      setWizardOpen(true);
    } catch (e) {
      setError(
        (e as Error).message ||
          "Impossible de charger la fiche d'analyse liée au deal."
      );
    } finally {
      setLoading(false);
    }
  }

  return (
    <section className="mt-4 rounded-xl border border-brand-800 bg-brand-900 p-5">
      <div className="flex items-center justify-between gap-2">
        <h2 className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wider text-accent-500">
          <Presentation className="h-4 w-4" />
          Offre d&apos;investissement (PowerPoint)
        </h2>
        <button
          type="button"
          onClick={() => void openWizard()}
          disabled={loading}
          className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-500 px-3 py-1.5 text-xs font-bold text-white hover:bg-emerald-400 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {loading ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <Presentation className="h-3.5 w-3.5" />
          )}
          {loading ? "Chargement…" : "Générer le PowerPoint"}
        </button>
      </div>

      <p className="mt-1 text-xs text-white/40">
        Génère le .pptx d&apos;offre investisseur (template Horizon, 16
        slides) à partir des chiffres de la fiche d&apos;analyse liée à ce
        deal. Le wizard pré-remplit les champs et te laisse ajuster
        bullets, leviers value-add et photos avant le téléchargement.
      </p>

      {error ? (
        <p className="mt-3 flex items-start gap-2 rounded-md border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-300">
          <AlertTriangle className="mt-0.5 h-4 w-4 flex-shrink-0" />
          <span>{error}</span>
        </p>
      ) : null}

      {wizardData ? (
        <OffreInvestissementWizard
          open={wizardOpen}
          onClose={() => setWizardOpen(false)}
          analysisId={analysisId}
          data={wizardData}
        />
      ) : null}
    </section>
  );
}
