"use client";

/**
 * Bandeau « Bail manquant au dossier » — même portée et même rendu que
 * `BandeauAvisRenouvellement` (page Paiements, page Baux, fiche
 * immeuble).
 *
 * Pourquoi il existe (audit 2026-08-19) : les baux sont signés HORS de
 * Kratos, le seul exemplaire au dossier est celui qu'on IMPORTE à
 * l'entrée du locataire. Un garde-fou bloque déjà le passage d'un
 * dossier de relocation à « Reloué » tant que le bail n'est pas
 * importé — mais il ne couvre que ce chemin : un bail créé directement
 * « déjà en vigueur » y échappe. En prod, 8 baux actifs se trouvaient
 * dans ce cas, tous récents.
 *
 * Le garde-fou bloque ce qu'il peut ; ce bandeau rend visible ce qui
 * est déjà passé à travers.
 */

import { useEffect, useState } from "react";

import { Link } from "@/i18n/navigation";
import { authedFetch } from "@/lib/auth";

type Row = {
  bail_id: number;
  immeuble: string;
  immeuble_id: number;
  logement: string;
  locataire: string;
  date_debut: string;
  jours: number;
};

type Data = { rows: Row[]; nb: number };

function fmtDateShort(iso: string): string {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(y, (m || 1) - 1, d || 1).toLocaleDateString("fr-CA", {
    day: "numeric",
    month: "short",
    year: "numeric"
  });
}

export function BandeauBailManquant({
  immeubleId,
  entrepriseId
}: {
  immeubleId?: number | null;
  entrepriseId?: number | null;
}) {
  const [data, setData] = useState<Data | null>(null);

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
        `/api/v1/immobilier/baux/sans-document?${params.toString()}`
      );
      if (r.ok) setData((await r.json()) as Data);
    })();
  }, [entrepriseId, immeubleId]);

  if (!data || data.rows.length === 0) return null;

  return (
    <div className="mt-5 rounded-xl border border-rose-500/30 bg-rose-500/5 p-4">
      <div className="mb-2 flex items-center gap-2 text-sm font-semibold text-rose-200">
        <span>📄 Bail manquant au dossier</span>
        <span className="text-xs font-normal text-white/50">
          {data.nb} {data.nb > 1 ? "baux actifs" : "bail actif"} sans
          document
        </span>
      </div>
      <p className="mb-3 text-xs text-white/50">
        Ces locataires sont entrés sans que leur bail signé soit importé
        dans Kratos. Ouvre la fiche du logement et utilise « Importer le
        bail » — sans lui, aucune preuve du loyer ni des conditions
        convenues.
      </p>
      <div className="space-y-1.5">
        {data.rows.map((r) => (
          <div
            key={r.bail_id}
            className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-rose-500/40 bg-rose-500/5 px-3 py-2 text-sm"
          >
            <div className="min-w-0">
              <span className="font-medium">{r.locataire}</span>
              <span className="ml-2 text-xs text-white/50">
                {r.immeuble} · {r.logement}
              </span>
            </div>
            <div className="flex items-center gap-3 text-xs text-white/60">
              <span>Entré le {fmtDateShort(r.date_debut)}</span>
              <span className="badge badge-rose">
                {r.jours} jour{r.jours > 1 ? "s" : ""}
              </span>
              <Link
                href={`/immobilier/immeubles/${r.immeuble_id}` as never}
                className="btn-ghost btn-xs"
              >
                Ouvrir
              </Link>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
