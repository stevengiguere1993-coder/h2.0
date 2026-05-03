"use client";

import { useEffect, useState } from "react";
import { ClipboardList, Loader2, Sparkles } from "lucide-react";

import { Link } from "@/i18n/navigation";
import { authedFetch } from "@/lib/auth";
import { ImmobilierTopbar } from "../layout";

type ImmeubleListItem = {
  id: number;
  name: string;
  nb_logements_actifs: number;
  nb_logements_occupes: number;
};

export default function BauxPage() {
  const [list, setList] = useState<ImmeubleListItem[] | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const res = await authedFetch("/api/v1/immobilier/immeubles");
        if (!res.ok) return;
        const data = (await res.json()) as ImmeubleListItem[];
        if (!cancelled) setList(data);
      } catch {
        /* ignore */
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <>
      <ImmobilierTopbar
        breadcrumbs={[
          { label: "Gestion immobilière", href: "/immobilier" },
          { label: "Baux & paiements" }
        ]}
      />
      <div className="p-4 lg:p-6">
        <header className="flex items-start gap-3">
          <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-sky-500/15 text-sky-300">
            <ClipboardList className="h-5 w-5" />
          </span>
          <div>
            <h1 className="text-2xl font-bold text-white">Baux & paiements</h1>
            <p className="mt-1 max-w-2xl text-sm text-white/60">
              Gestion des baux par immeuble. Ouvre une fiche immeuble pour
              créer / éditer ses baux, suivre les paiements et déclencher
              les renouvellements.
            </p>
          </div>
        </header>

        <div className="mt-6 inline-flex items-center gap-2 rounded-full border border-amber-500/40 bg-amber-500/10 px-3 py-1 text-xs font-semibold text-amber-200">
          <Sparkles className="h-3.5 w-3.5" />
          Vue transversale en développement — accède via une fiche immeuble.
        </div>

        <section className="mt-6">
          <h2 className="mb-3 text-sm font-semibold uppercase tracking-wider text-sky-300">
            Immeubles du portefeuille
          </h2>
          {list === null ? (
            <p className="text-xs text-white/50">
              <Loader2 className="mr-1 inline h-3 w-3 animate-spin" /> Chargement…
            </p>
          ) : list.length === 0 ? (
            <p className="rounded-lg border border-brand-800 bg-brand-900 px-4 py-3 text-sm text-white/60">
              Aucun immeuble. Crées-en un pour commencer.
            </p>
          ) : (
            <ul className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
              {list.map((imm) => (
                <li key={imm.id}>
                  <Link
                    // eslint-disable-next-line @typescript-eslint/no-explicit-any
                    href={`/immobilier/immeubles/${imm.id}` as any}
                    className="block rounded-xl border border-brand-800 bg-brand-900 p-3 transition hover:border-sky-400/40"
                  >
                    <p className="truncate text-sm font-bold text-white">
                      {imm.name}
                    </p>
                    <p className="mt-1 text-[11px] text-white/50">
                      {imm.nb_logements_occupes}/{imm.nb_logements_actifs}{" "}
                      logements occupés
                    </p>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </>
  );
}
