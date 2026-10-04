"use client";

import { useEffect, useState } from "react";
import { Eye } from "lucide-react";

import {
  getApercu,
  localePrefix,
  stopApercu,
  type ApercuInfo,
  type UserRole
} from "@/lib/auth";

/**
 * Bandeau « Aperçu : tu vois Kratos comme … · lecture seule ».
 *
 * Affiché quand un admin/owner regarde Kratos avec le jeton d'aperçu d'un
 * autre utilisateur (cf. startApercu / getApercu dans lib/auth.ts). Il
 * rappelle QUI est regardé et que tout est en lecture seule (le backend
 * refuse chaque écriture avec ce jeton), et offre la sortie « Quitter
 * l'aperçu » : on restaure le jeton admin puis on recharge complètement la
 * page pour que tous les layouts relisent /auth/me avec le bon compte.
 *
 * Monté dans <PublicChrome /> (layout racine), PAS dans un volet : le
 * bandeau doit suivre l'admin partout — sélecteur de portail /connexion,
 * zone employé /m, volets /app, /immobilier, /prospection… — alors que
 * chaque volet rend son propre chrome. En flux normal (pas `fixed`) pour
 * ne masquer aucune topbar.
 *
 * `localStorage` n'est lu QUE dans un useEffect (jamais au rendu initial)
 * pour éviter toute différence serveur/client à l'hydratation : au premier
 * rendu le bandeau est absent, il apparaît dès le montage.
 */

const ROLE_LABEL: Record<UserRole, string> = {
  owner: "Propriétaire",
  admin: "Administrateur",
  manager: "Gestionnaire",
  employee: "Employé"
};

export function ApercuBanner() {
  const [info, setInfo] = useState<ApercuInfo | null>(null);

  useEffect(() => {
    setInfo(getApercu());
  }, []);

  if (!info) return null;

  const nom = info.display_name || info.email;
  const role = ROLE_LABEL[info.role] || info.role;

  function quitter() {
    stopApercu();
    // Rechargement complet (pas de router.push) : chaque layout relit
    // /auth/me avec le jeton admin restauré.
    window.location.assign(`${localePrefix()}/app/utilisateurs`);
  }

  return (
    <div
      data-testid="apercu-banner"
      role="status"
      className="flex flex-wrap items-center justify-between gap-2 border-b-2 border-accent-500 bg-brand-900 px-4 py-2 text-sm text-white"
    >
      <p className="flex min-w-0 items-center gap-2">
        <Eye className="h-4 w-4 shrink-0 text-accent-500" />
        <span className="min-w-0">
          Aperçu : tu vois Kratos comme <strong>{nom}</strong> ({role}) ·
          lecture seule
        </span>
      </p>
      <button
        type="button"
        onClick={quitter}
        className="btn-accent !px-3 !py-1.5 text-xs"
      >
        Quitter l&apos;aperçu
      </button>
    </div>
  );
}
