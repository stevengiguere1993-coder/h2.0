"use client";

import { AppTopbar } from "@/components/app-topbar";
import { ConnexionsSection } from "@/components/connexions-section";
import { useProspectionLayout } from "../../layout";
import { ParametresTabs } from "../_tabs";

export default function ProspectionConnexionsPage() {
  const { onOpenSidebar } = useProspectionLayout();
  return (
    <>
      <AppTopbar
        breadcrumbs={[
          { label: "Prospection", href: "/prospection" },
          { label: "Paramètres", href: "/prospection/parametres" },
          { label: "Connexions" }
        ]}
        onOpenSidebar={onOpenSidebar}
      />
      <ParametresTabs />

      <div className="mx-auto max-w-3xl p-4 lg:p-6">
        <h1 className="text-2xl font-bold text-white">Connexions</h1>
        <p className="mt-1 text-sm text-white/60">
          Calendrier externe (Google/Outlook/Apple) et autres
          intégrations spécifiques au volet Prospection.
        </p>

        <ConnexionsSection scope="prospection" />
      </div>
    </>
  );
}
