"use client";

import { KeyRound } from "lucide-react";

import { ImmobilierTopbar, useImmobilierLayout } from "../layout";
import { LocationsBoard } from "@/components/immobilier/locations-board";
import {
  useNomPageImmobilier,
  usePresentationImmobilier
} from "@/hooks/use-presentation-immobilier";

/**
 * Page « Locations » — pipeline de relocation des logements (vacances) :
 * départ confirmé → annonces → visites → candidat retenu → reloué.
 */

export default function LocationsPage() {
  const { currentEntrepriseId } = useImmobilierLayout();
  // Refonte : la page s'appelle « À louer » avec le nouveau menu.
  const titrePage = useNomPageImmobilier("Locations & nouveaux baux", "À louer");
  // Lot « baux » de la refonte : en-tête plus court, le tableau remonte.
  const presentation = usePresentationImmobilier();
  const nouvelle = presentation.pret && presentation.baux;
  return (
    <>
      <ImmobilierTopbar
        breadcrumbs={[
          { label: "Immobilier", href: "/immobilier" },
          { label: titrePage }
        ]}
      />
      <div className="p-4 pb-28 lg:p-6 lg:pb-28">
        <header className="flex items-start gap-3">
          <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-amber-500/15 text-amber-300">
            <KeyRound className="h-5 w-5" />
          </span>
          <div>
            <h1 className="text-2xl font-bold text-white">{titrePage}</h1>
            {nouvelle ? (
              <p className="mt-1 max-w-2xl text-sm text-white/70">
                Un dossier par logement qui se libère, du départ
                jusqu&apos;au nouveau bail.
              </p>
            ) : (
              <p className="mt-1 max-w-2xl text-sm text-white/60">
                Chaque logement qui se libère devient un dossier : départ
                confirmé, annonces publiées, visites de candidats,
                jusqu&apos;au nouveau bail. Rien ne part tout seul —
                l&apos;équipe consigne tout ici.
              </p>
            )}
          </div>
        </header>
        <div className={nouvelle ? "mt-4" : "mt-6"}>
          <LocationsBoard entrepriseId={currentEntrepriseId} />
        </div>
      </div>
    </>
  );
}
