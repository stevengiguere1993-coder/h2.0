"use client";

import { useEffect } from "react";
import { ArrowLeft, Construction, MapPin, Smartphone } from "lucide-react";

import { Link, useRouter } from "@/i18n/navigation";
import { getToken } from "@/lib/auth";

export default function ProspectionLandingPage() {
  const router = useRouter();

  useEffect(() => {
    // Si déjà loggé : rediriger vers la PWA mobile (drive-by)
    const token = getToken();
    if (token) {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      router.replace("/m/prospection" as any);
    }
  }, [router]);

  return (
    <main className="flex min-h-screen flex-col bg-brand-950 text-white">
      <div className="mx-auto flex w-full max-w-2xl flex-1 flex-col px-4 py-12">
        <Link
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          href={"/connexion" as any}
          className="inline-flex items-center text-sm text-white/60 hover:text-accent-500"
        >
          <ArrowLeft className="mr-1 h-4 w-4" /> Retour
        </Link>

        <div className="mt-12 rounded-3xl border border-brand-800 bg-brand-900 p-8">
          <div className="flex items-start gap-4">
            <span className="flex h-14 w-14 shrink-0 items-center justify-center rounded-2xl bg-emerald-500/15 text-emerald-400">
              <MapPin className="h-7 w-7" />
            </span>
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2">
                <h1 className="text-2xl font-bold text-white">
                  Prospection
                </h1>
                <span className="inline-flex items-center rounded-full border border-amber-500/40 bg-amber-500/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-amber-300">
                  En développement
                </span>
              </div>
              <p className="mt-2 text-sm text-white/70">
                Module de prospection terrain inspiré de DealMachine,
                personnalisé pour le marché québécois et tes besoins
                Horizon.
              </p>
            </div>
          </div>

          <div className="mt-8 space-y-3">
            <h2 className="text-sm font-semibold uppercase tracking-wider text-accent-500">
              À venir
            </h2>
            <ul className="space-y-2 text-sm text-white/80">
              <li className="flex items-start gap-2">
                <span className="mt-1 inline-block h-1.5 w-1.5 shrink-0 rounded-full bg-emerald-400" />
                Mode drive-by — détecte tes arrêts en voiture et te
                propose d&apos;ajouter le chantier vu
              </li>
              <li className="flex items-start gap-2">
                <span className="mt-1 inline-block h-1.5 w-1.5 shrink-0 rounded-full bg-emerald-400" />
                Carte avec pins des prospects à visiter / contactés /
                relancés
              </li>
              <li className="flex items-start gap-2">
                <span className="mt-1 inline-block h-1.5 w-1.5 shrink-0 rounded-full bg-emerald-400" />
                Photos rapides + notes vocales sur chaque prospect
              </li>
              <li className="flex items-start gap-2">
                <span className="mt-1 inline-block h-1.5 w-1.5 shrink-0 rounded-full bg-emerald-400" />
                Lookup propriétaire via le rôle d&apos;évaluation
                municipal (sources publiques QC)
              </li>
              <li className="flex items-start gap-2">
                <span className="mt-1 inline-block h-1.5 w-1.5 shrink-0 rounded-full bg-emerald-400" />
                Campagnes de contact — courriel, courrier postal,
                relances automatiques
              </li>
              <li className="flex items-start gap-2">
                <span className="mt-1 inline-block h-1.5 w-1.5 shrink-0 rounded-full bg-emerald-400" />
                Pipeline : à visiter → contacté → soumissionné →
                converti / perdu
              </li>
            </ul>
          </div>

          <div className="mt-8 rounded-xl border border-dashed border-brand-700 bg-brand-950/40 p-4">
            <Construction className="mb-2 h-5 w-5 text-amber-400" />
            <p className="text-xs text-white/60">
              Cette page est un placeholder. La construction du module
              démarre — les premières fonctionnalités (drive-by + carte
              + photo) arriveront en priorité.
            </p>
          </div>
        </div>
      </div>
    </main>
  );
}
