"use client";

import { KeyRound } from "lucide-react";

import { ImmobilierTopbar, useImmobilierLayout } from "../layout";
import { LocationsBoard } from "@/components/immobilier/locations-board";

/**
 * Page « Locations » — pipeline de relocation des logements (vacances) :
 * départ confirmé → annonces → visites → candidat retenu → reloué.
 */

export default function LocationsPage() {
  const { currentEntrepriseId } = useImmobilierLayout();
  return (
    <>
      <ImmobilierTopbar
        breadcrumbs={[
          { label: "Gestion immobilière", href: "/immobilier" },
          { label: "Locations" }
        ]}
      />
      <div className="p-4 pb-28 lg:p-6 lg:pb-28">
        <header className="flex items-start gap-3">
          <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-amber-500/15 text-amber-300">
            <KeyRound className="h-5 w-5" />
          </span>
          <div>
            <h1 className="text-2xl font-bold text-white">Locations</h1>
            <p className="mt-1 max-w-2xl text-sm text-white/60">
              Chaque logement qui se libère devient un dossier : départ
              confirmé, annonces publiées, visites de candidats, jusqu&apos;au
              nouveau bail. Rien ne part tout seul — l&apos;équipe consigne
              tout ici.
            </p>
          </div>
        </header>
        <div className="mt-6">
          <LocationsBoard entrepriseId={currentEntrepriseId} />
        </div>
      </div>
    </>
  );
}
