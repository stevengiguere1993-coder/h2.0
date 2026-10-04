"use client";

/**
 * Zone employés (/m) — contexte de variante.
 *
 * La zone employés sert deux publics : les employés Construction (punch,
 * projets, achats — inchangé) et les employés « autres » (ex. vidéo /
 * marketing : seul pôle Entreprises, sans fiche Employé Construction) qui
 * y retrouvent leur agenda, leurs tâches et leur feuille de temps.
 *
 * La variante est calculée UNE fois dans le layout à partir du `me` déjà
 * chargé par getMe ; les pages la lisent ici sans refaire /auth/me.
 */

import { createContext, useContext, useMemo, type ReactNode } from "react";

import type { CurrentUser } from "@/lib/auth";

export type ZoneVariant = "construction" | "autre";

type ZoneEmployeCtx = {
  me: CurrentUser | null;
  variant: ZoneVariant;
};

// Hors provider, on garde le comportement historique : Construction.
const ZoneEmployeContext = createContext<ZoneEmployeCtx>({
  me: null,
  variant: "construction"
});

export function ZoneEmployeProvider({
  me,
  variant,
  children
}: ZoneEmployeCtx & { children: ReactNode }) {
  const value = useMemo(() => ({ me, variant }), [me, variant]);
  return (
    <ZoneEmployeContext.Provider value={value}>
      {children}
    </ZoneEmployeContext.Provider>
  );
}

export function useZoneEmploye(): ZoneEmployeCtx {
  return useContext(ZoneEmployeContext);
}
