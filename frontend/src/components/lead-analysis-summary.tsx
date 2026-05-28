"use client";

import { useEffect, useState } from "react";
import { Loader2, FileText, ExternalLink } from "lucide-react";
import { Link } from "@/i18n/navigation";
import { authedFetch } from "@/lib/auth";

type Analysis = {
  id: number;
  address: string | null;
  city: string | null;
  postal_code: string | null;
  asking_price: number | null;
  nb_logements: number | null;
  revenus_bruts: number | null;
  evaluation_municipale: number | null;
};

function fmt(n: number | null | undefined, suffix: string = "") {
  if (n == null) return "—";
  return n.toLocaleString("fr-CA", { maximumFractionDigits: 0 }) + suffix;
}

/**
 * Affichage en lecture seule d'un résumé de fiche d'analyse de lead,
 * embarquable dans une autre page (ex : page detail d'un Deal Pipeline).
 * Le bouton « Ouvrir la fiche complète » navigue vers la page Analyses
 * des leads avec `?openId={id}` (ouverture auto du modal). Si
 * `fromDealId` est fourni, on ajoute `&fromDeal={dealId}` pour que la
 * page d'analyses affiche un bouton « Retour au deal » dans le modal
 * et préserve le contexte du Deal d'origine.
 */
export function LeadAnalysisSummary({
  id,
  fromDealId
}: {
  id: number;
  fromDealId?: number;
}) {
  const [data, setData] = useState<Analysis | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancel = false;
    setLoading(true);
    authedFetch(`/api/v1/lead-analyses/${id}`)
      .then(async (r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((j: Analysis) => {
        if (!cancel) setData(j);
      })
      .catch(() => {
        // Silent fail — la fiche peut avoir été supprimée
      })
      .finally(() => {
        if (!cancel) setLoading(false);
      });
    return () => {
      cancel = true;
    };
  }, [id]);

  if (loading) {
    return (
      <section className="mt-4 rounded-lg border border-brand-800 bg-brand-900/40 px-3 py-2">
        <div className="flex items-center gap-2 text-xs text-white/40">
          <Loader2 className="h-3 w-3 animate-spin" />
          Chargement de la fiche d&apos;analyse…
        </div>
      </section>
    );
  }

  if (!data) return null;

  return (
    <section className="mt-4 rounded-lg border border-brand-800 bg-brand-900/40 px-4 py-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <FileText className="h-4 w-4 text-accent-500" />
          <h2 className="text-sm font-semibold uppercase tracking-wider text-accent-500">
            Fiche d&apos;analyse
          </h2>
        </div>
        {/* eslint-disable-next-line @typescript-eslint/no-explicit-any */}
        <Link
          href={
            (fromDealId != null
              ? `/prospection/analyses-leads?openId=${data.id}&fromDeal=${fromDealId}`
              : `/prospection/analyses-leads?openId=${data.id}`) as any
          }
          className="inline-flex items-center gap-1 rounded-md border border-emerald-500/30 bg-emerald-500/10 px-2 py-0.5 text-[11px] text-emerald-300 hover:bg-emerald-500/20"
        >
          Ouvrir la fiche complète
          <ExternalLink className="h-3 w-3" />
        </Link>
      </div>
      <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1 text-xs sm:grid-cols-4">
        <div>
          <dt className="text-white/40">Prix demandé</dt>
          <dd className="text-white/90">{fmt(data.asking_price, " $")}</dd>
        </div>
        <div>
          <dt className="text-white/40">Logements</dt>
          <dd className="text-white/90">{data.nb_logements ?? "—"}</dd>
        </div>
        <div>
          <dt className="text-white/40">Revenus bruts</dt>
          <dd className="text-white/90">{fmt(data.revenus_bruts, " $")}</dd>
        </div>
        <div>
          <dt className="text-white/40">Éval. municipale</dt>
          <dd className="text-white/90">{fmt(data.evaluation_municipale, " $")}</dd>
        </div>
      </dl>
    </section>
  );
}
