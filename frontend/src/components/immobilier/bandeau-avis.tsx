"use client";

/**
 * Bandeau « Avis de renouvellement » — composant PARTAGÉ entre la page
 * Baux & paiements (/immobilier/baux), la page Baux
 * (/immobilier/suivi-baux) et l'onglet Baux & locataires de la fiche
 * immeuble. Même rendu partout (miroir exact) ; seule la PORTÉE change :
 *   - `entrepriseId` limite au portefeuille de l'entreprise sélectionnée ;
 *   - `immeubleId` limite aux alertes de CET immeuble.
 *
 * Retour client 2026-08-14 : le bandeau ne liste QUE l'actionnable
 * (à envoyer / en retard). Les « à venir » (ligne verte « rien à
 * faire ») sortent de la liste — seul le compteur de l'en-tête les
 * mentionne. Aucune action → pas de bandeau du tout.
 */

import { useEffect, useState } from "react";

import { authedFetch } from "@/lib/auth";

type Echeance = {
  bail_id: number;
  immeuble: string;
  logement: string;
  locataire: string;
  date_fin: string;
  fenetre_debut: string;
  fenetre_fin: string;
  statut: string; // a_envoyer | en_retard | a_venir
  jours: number;
  loyer_mensuel: number;
};

type EcheanceData = {
  rows: Echeance[];
  nb_a_envoyer: number;
  nb_en_retard: number;
  nb_a_venir: number;
};

function fmtDateShort(iso: string): string {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(y, (m || 1) - 1, d || 1).toLocaleDateString("fr-CA", {
    day: "numeric",
    month: "short",
    year: "numeric"
  });
}

export function BandeauAvisRenouvellement({
  immeubleId,
  entrepriseId
}: {
  /** Alertes de CET immeuble seulement (fiche immeuble, ?immeuble_id=). */
  immeubleId?: number | null;
  /** Portefeuille de l'entreprise sélectionnée (page Baux & paiements). */
  entrepriseId?: number | null;
}) {
  const [data, setData] = useState<EcheanceData | null>(null);

  useEffect(() => {
    void (async () => {
      const params = new URLSearchParams();
      if (entrepriseId != null) {
        params.set("entreprise_id", String(entrepriseId));
      }
      if (immeubleId != null) {
        params.set("immeuble_id", String(immeubleId));
      }
      const r = await authedFetch(
        `/api/v1/immobilier/baux/echeances?${params.toString()}`
      );
      if (r.ok) setData((await r.json()) as EcheanceData);
    })();
  }, [entrepriseId, immeubleId]);

  if (!data || data.rows.length === 0) return null;
  const actionnables = data.rows.filter((r) => r.statut !== "a_venir");
  if (actionnables.length === 0) return null;
  const TONE: Record<string, { box: string; chip: string; txt: string }> = {
    en_retard: {
      box: "border-rose-500/40 bg-rose-500/5",
      chip: "badge-rose",
      txt: "En retard"
    },
    a_envoyer: {
      box: "border-amber-500/40 bg-amber-500/5",
      chip: "badge-amber",
      txt: "À envoyer"
    }
  };
  return (
    <div className="mt-5 rounded-xl border border-amber-500/30 bg-amber-500/5 p-4">
      <div className="mb-2 flex items-center gap-2 text-sm font-semibold text-amber-200">
        <span>📅 Avis de renouvellement</span>
        <span className="text-xs font-normal text-white/50">
          {data.nb_en_retard > 0 ? `${data.nb_en_retard} en retard · ` : ""}
          {data.nb_a_envoyer} à envoyer
          {data.nb_a_venir > 0 ? ` · ${data.nb_a_venir} à venir` : ""}
        </span>
      </div>
      <p className="mb-3 text-xs text-white/50">
        L&apos;avis officiel se transmet via le formulaire du TAL ou de la
        CORPIQ, entre 6 et 3 mois avant la fin du bail.
      </p>
      <div className="space-y-1.5">
        {actionnables.map((r) => {
          const t = TONE[r.statut] || TONE.a_envoyer;
          return (
            <div
              key={r.bail_id}
              className={`flex flex-wrap items-center justify-between gap-2 rounded-lg border px-3 py-2 text-sm ${t.box}`}
            >
              <div className="min-w-0">
                <span className="font-medium">{r.locataire}</span>
                <span className="ml-2 text-xs text-white/50">
                  {r.immeuble} · {r.logement}
                </span>
              </div>
              <div className="flex items-center gap-3 text-xs text-white/60">
                <span>Fin du bail : {fmtDateShort(r.date_fin)}</span>
                <span className="hidden sm:inline">
                  Fenêtre : {fmtDateShort(r.fenetre_debut)} →{" "}
                  {fmtDateShort(r.fenetre_fin)}
                </span>
                <span className={`badge ${t.chip}`}>{t.txt}</span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
