"use client";

/* Paramètres → Général → Assistant IA (« chacun son IA »).
   Déplacé du profil vers Paramètres (retour Phil 2026-09-02). */

import { ArrowLeft } from "lucide-react";

import { Link } from "@/i18n/navigation";
import { MonIaSection } from "@/components/mon-ia-section";

export default function AssistantIaPage() {
  return (
    <div className="mx-auto max-w-3xl space-y-5 p-4 lg:p-6">
      <header className="flex items-center gap-3">
        <Link
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          href={"/parametres" as any}
          className="inline-flex items-center gap-1.5 rounded-md px-2 py-1.5 text-sm text-white/70 hover:bg-brand-900 hover:text-white"
        >
          <ArrowLeft className="h-4 w-4" /> Paramètres
        </Link>
        <h1 className="text-xl font-bold text-white">Assistant IA</h1>
      </header>
      <MonIaSection />
    </div>
  );
}
