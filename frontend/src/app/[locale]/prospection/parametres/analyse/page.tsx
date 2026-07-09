"use client";

import { SlidersHorizontal } from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { hasMinRole } from "@/lib/auth";
import { useCurrentUser } from "@/hooks/use-current-user";
import { useProspectionLayout } from "../../layout";
import { ParametresTabs } from "../_tabs";
import {
  BaremesFiscauxSection,
  DepensesNormaliseesSection,
  InputsManuelsSection,
  MdfFraisSection,
  ScenariosFinancementSection,
  TriDefautsSection
} from "./_analyse-sections";

/**
 * Page « Calculateur » des Paramètres Prospection.
 *
 * Édite TOUTES les valeurs de configuration de l'analyse financière de
 * lead, externalisées côté backend (table analysis_defaults + frais
 * personnalisés). Remplace l'ancienne modale « Défauts » enfouie dans
 * la fiche de lead.
 *
 * Sections (une par groupe backend) :
 *   1. Dépenses normalisées (SCHL) — depenses_normalisees
 *   2. Scénarios de financement     — scenarios_financement
 *   3. Barèmes fiscaux              — baremes_fiscaux
 *   4. Valeurs par défaut analyses  — inputs_manuels
 *   5. Frais de démarrage (MDF)     — mdf_frais + frais-custom
 *   6. Défauts TRI                  — tri_defaults
 *
 * Accès réservé admin/owner (le backend renvoie 403 sinon).
 */
export default function ProspectionAnalysePage() {
  const { onOpenSidebar } = useProspectionLayout();
  const { user } = useCurrentUser();
  const isAdmin = hasMinRole(user, "admin");

  return (
    <>
      <AppTopbar
        breadcrumbs={[
          { label: "Prospection", href: "/prospection" },
          { label: "Paramètres", href: "/prospection/parametres" },
          { label: "Calculateur" }
        ]}
        onOpenSidebar={onOpenSidebar}
      />
      <ParametresTabs />

      <div className="mx-auto max-w-3xl p-4 lg:p-6">
        <h1 className="flex items-center gap-2 text-2xl font-bold text-white">
          <SlidersHorizontal className="h-6 w-6 text-accent-500" />
          Calculateur d&apos;analyse financière
        </h1>
        <p className="mt-1 text-sm text-white/60">
          Toutes les valeurs de configuration qui alimentent l&apos;analyse
          financière d&apos;un lead. Modifier un défaut change la valeur
          pré-remplie pour les{" "}
          <strong className="text-white">nouvelles analyses</strong>{" "}
          uniquement — les analyses existantes ne sont pas écrasées et
          l&apos;override par fiche reste toujours possible.
        </p>

        {!isAdmin ? (
          <p className="mt-6 rounded-lg border border-amber-500/40 bg-amber-500/10 p-3 text-sm text-amber-200">
            Cette section est réservée aux comptes admin / owner.
          </p>
        ) : (
          <div className="mt-6 space-y-6">
            <DepensesNormaliseesSection />
            <ScenariosFinancementSection />
            <BaremesFiscauxSection />
            <InputsManuelsSection />
            <MdfFraisSection />
            <TriDefautsSection />
          </div>
        )}
      </div>
    </>
  );
}
