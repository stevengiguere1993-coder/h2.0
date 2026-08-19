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
 * ⚠️ RÈGLE POSÉE PAR PHIL (2026-08-19) : une alerte ne PORTE pas
 * l'action, elle y MÈNE. Chaque ligne est donc un lien vers la fiche du
 * logement — là où le bail vit, où on l'importe, et où on peut déclarer
 * qu'il n'y en aura pas. Aucun bouton d'action ici : une alerte sur
 * laquelle on agit devient un deuxième endroit où faire les choses, et
 * les deux finissent par diverger.
 */

import { useCallback, useEffect, useState } from "react";

import { Link } from "@/i18n/navigation";
import { authedFetch } from "@/lib/auth";

type Row = {
  bail_id: number;
  immeuble: string;
  immeuble_id: number;
  logement_id?: number | null;
  logement: string;
  locataire: string;
  date_debut: string;
  jours: number;
  motif?: string | null;
  motif_par?: string | null;
};

type Data = {
  rows: Row[];
  nb: number;
  nb_exceptions: number;
  exceptions: Row[];
};

function fmtDateShort(iso: string): string {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(y, (m || 1) - 1, d || 1).toLocaleDateString("fr-CA", {
    day: "numeric",
    month: "short",
    year: "numeric"
  });
}

/** Où se règle le cas : la fiche du logement porte le bail et son
 *  import. À défaut (donnée ancienne), la fiche de l'immeuble. */
function cible(r: Row): string {
  return r.logement_id != null
    ? `/immobilier/logements/${r.logement_id}`
    : `/immobilier/immeubles/${r.immeuble_id}`;
}

export function BandeauBailManquant({
  immeubleId,
  entrepriseId
}: {
  immeubleId?: number | null;
  entrepriseId?: number | null;
}) {
  const [data, setData] = useState<Data | null>(null);
  const [ouvrirExceptions, setOuvrirExceptions] = useState(false);

  const charger = useCallback(async () => {
    const params = new URLSearchParams();
    if (entrepriseId != null) params.set("entreprise_id", String(entrepriseId));
    if (immeubleId != null) params.set("immeuble_id", String(immeubleId));
    const r = await authedFetch(
      `/api/v1/immobilier/baux/sans-document?${params.toString()}`
    );
    if (r.ok) setData((await r.json()) as Data);
  }, [entrepriseId, immeubleId]);

  useEffect(() => {
    void charger();
  }, [charger]);

  if (!data) return null;
  if (data.rows.length === 0 && data.nb_exceptions === 0) return null;

  return (
    <div className="mt-5 rounded-xl border border-rose-500/30 bg-rose-500/5 p-4">
      {data.rows.length > 0 ? (
        <>
          <div className="mb-2 flex items-center gap-2 text-sm font-semibold text-rose-200">
            <span>📄 Bail manquant au dossier</span>
            <span className="text-xs font-normal text-white/50">
              {data.nb} {data.nb > 1 ? "baux actifs" : "bail actif"} sans
              document
            </span>
          </div>
          <p className="mb-3 text-xs text-white/50">
            Ces locataires sont entrés sans que leur bail signé soit importé
            dans Kratos. Sans lui, aucune preuve du loyer ni des conditions
            convenues. Clique une ligne pour ouvrir son logement et régler
            le cas.
          </p>
          <div className="space-y-1.5">
            {data.rows.map((r) => (
              <Link
                key={r.bail_id}
                href={cible(r) as never}
                className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-rose-500/40 bg-rose-500/5 px-3 py-2 text-sm transition hover:border-rose-400/70 hover:bg-rose-500/10"
              >
                <span className="min-w-0">
                  <span className="font-medium">{r.locataire}</span>
                  <span className="ml-2 text-xs text-white/50">
                    {r.immeuble} · {r.logement}
                  </span>
                </span>
                <span className="flex items-center gap-3 text-xs text-white/60">
                  <span>Entré le {fmtDateShort(r.date_debut)}</span>
                  <span className="badge badge-rose">
                    {r.jours} jour{r.jours > 1 ? "s" : ""}
                  </span>
                </span>
              </Link>
            ))}
          </div>
        </>
      ) : null}

      {data.nb_exceptions > 0 ? (
        <div className={data.rows.length > 0 ? "mt-3" : ""}>
          <button
            type="button"
            onClick={() => setOuvrirExceptions((v) => !v)}
            className="text-[11px] text-white/45 underline decoration-dotted underline-offset-2 hover:text-white/70"
          >
            {data.nb_exceptions} exception
            {data.nb_exceptions > 1 ? "s" : ""} déclarée
            {data.nb_exceptions > 1 ? "s" : ""} — aucun bail à joindre
            {ouvrirExceptions ? " (masquer)" : " (voir)"}
          </button>
          {ouvrirExceptions ? (
            <div className="mt-1.5 space-y-1">
              {data.exceptions.map((r) => (
                <Link
                  key={r.bail_id}
                  href={cible(r) as never}
                  className="block rounded-lg border border-brand-800 bg-brand-950/50 px-3 py-1.5 text-xs transition hover:border-white/20"
                >
                  <span className="text-white/80">{r.locataire}</span>
                  <span className="ml-2 text-white/40">
                    {r.immeuble} · {r.logement}
                  </span>
                  <span className="block text-[11px] text-white/50">
                    « {r.motif} »
                    {r.motif_par ? (
                      <span className="text-white/35"> — {r.motif_par}</span>
                    ) : null}
                  </span>
                </Link>
              ))}
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
