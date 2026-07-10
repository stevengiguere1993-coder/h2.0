"use client";

import { ChevronLeft } from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { ConnexionsSection } from "@/components/connexions-section";
import { Link } from "@/i18n/navigation";
import { useAppLayout } from "../../layout";
import { hasMinRole } from "@/lib/auth";
import { useCurrentUser } from "@/hooks/use-current-user";

/**
 * Page « Connexions » (manager+) — vue centralisée des sources externes
 * du pôle Construction (QBO, calendrier, rôles d'évaluation, REQ, SCHL…)
 * avec leur statut et un raccourci pour les configurer. Consolidée depuis
 * l'ancien hub Construction `/app/parametres`.
 */

export default function ConnexionsPage() {
  const { onOpenSidebar } = useAppLayout();
  const { user } = useCurrentUser();
  const isManager = hasMinRole(user, "manager");

  return (
    <>
      <AppTopbar
        breadcrumbs={[
          { label: "Construction", href: "/app" },
          { label: "Paramètres", href: "/parametres" },
          { label: "Connexions" }
        ]}
        onOpenSidebar={onOpenSidebar}
      />

      <div className="p-4 lg:p-6">
        <Link
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          href={"/parametres" as any}
          className="mb-2 inline-flex items-center text-xs text-white/60 hover:text-accent-500"
        >
          <ChevronLeft className="mr-1 h-3.5 w-3.5" /> Paramètres
        </Link>

        <h1 className="text-2xl font-bold text-white">Connexions</h1>
        <p className="mt-1 max-w-2xl text-sm text-white/60">
          Toutes les sources externes utilisées par Horizon côté
          Construction, avec leur statut et un raccourci pour les
          configurer.
        </p>

        {isManager ? (
          <ConnexionsSection />
        ) : (
          <p className="mt-6 rounded-2xl border border-brand-800 bg-brand-900 p-5 text-sm text-white/60">
            Cette section est réservée aux gestionnaires.
          </p>
        )}
      </div>
    </>
  );
}
