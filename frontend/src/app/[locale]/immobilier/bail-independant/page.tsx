"use client";

/**
 * Ancienne adresse de la page « Bail indépendant » (2026-11-10) : la section
 * s'appelle maintenant « Admin locative ». Les liens et les onglets restés
 * ouverts sur l'ancienne adresse y sont conduits.
 */

import { useEffect } from "react";

import { useRouter } from "@/i18n/navigation";

export default function BailIndependantRedirection() {
  const router = useRouter();
  useEffect(() => {
    router.replace("/immobilier/admin-locative" as never);
  }, [router]);
  return <p className="p-6 text-sm text-white/60">Ouverture de l&apos;Admin locative…</p>;
}
