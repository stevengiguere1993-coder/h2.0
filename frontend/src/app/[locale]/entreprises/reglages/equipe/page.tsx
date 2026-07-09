"use client";

import { Users, Sparkles } from "lucide-react";

export default function ReglagesEquipePage() {
  return (
    <div className="p-4 lg:p-6">
      <header className="flex items-start gap-3">
        <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-accent-500/15 text-accent-500">
          <Users className="h-5 w-5" />
        </span>
        <div>
          <h1 className="text-2xl font-bold text-white">Équipe</h1>
          <p className="mt-1 max-w-2xl text-sm text-white/60">
            Membres ayant accès au volet Gestion d&apos;entreprises.
          </p>
        </div>
      </header>
      <div className="mt-6 inline-flex items-center gap-2 rounded-full border border-amber-500/40 bg-amber-500/10 px-3 py-1 text-xs font-semibold text-amber-200">
        <Sparkles className="h-3.5 w-3.5" />
        Section en développement
      </div>
    </div>
  );
}
