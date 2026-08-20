"use client";

/**
 * Bandeau « Dépôt de garantie à rembourser » — même portée et même
 * rendu que `BandeauAvisRenouvellement` (Paiements, Baux, fiche
 * immeuble).
 *
 * Demande de Phil (2026-08-19) : « mon employé vient les mettre lorsque
 * c'est loué, mais il oublie tout le temps de venir l'enlever à la
 * fin… à la minute où il est sorti, ça met une alerte comme dans
 * Paiements pour le renouvellement ».
 *
 * Deux principes appliqués :
 *
 * 1. **Pas de blocage.** Phil a explicitement refusé un verrou à la
 *    relocation (« ça peut être un petit peu gossant »). L'oubli se
 *    rattrape par une alerte visible, pas par une porte fermée.
 * 2. **Aucune action ici.** Une alerte MÈNE à l'action, elle ne la
 *    porte pas — sinon elle devient un deuxième endroit où faire les
 *    choses. Chaque ligne ouvre donc la page Dépôts, où « Marquer
 *    rendu » existe déjà.
 *
 * Tous les logements n'ont pas de dépôt : sans dépôt, aucune ligne.
 */

import { useCallback, useEffect, useState } from "react";

import { Link } from "@/i18n/navigation";
import { authedFetch } from "@/lib/auth";

type DepotRow = {
  bail_id: number;
  immeuble_id: number;
  immeuble_name: string;
  logement_numero?: string | null;
  locataire_id?: number | null;
  locataire_name?: string | null;
  montant: number;
  statut: string;
  date_fin?: string | null;
};

type DepotOverview = {
  rows: DepotRow[];
  total_a_rendre?: number;
};

function fmtMoney(n: number): string {
  return new Intl.NumberFormat("fr-CA", {
    style: "currency",
    currency: "CAD",
    maximumFractionDigits: 0
  }).format(n);
}

function fmtDateShort(iso?: string | null): string {
  if (!iso) return "";
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(y, (m || 1) - 1, d || 1).toLocaleDateString("fr-CA", {
    day: "numeric",
    month: "short",
    year: "numeric"
  });
}

export function BandeauDepotARembourser({
  immeubleId,
  entrepriseId
}: {
  immeubleId?: number | null;
  entrepriseId?: number | null;
}) {
  const [rows, setRows] = useState<DepotRow[] | null>(null);

  const charger = useCallback(async () => {
    const params = new URLSearchParams();
    if (entrepriseId != null) params.set("entreprise_id", String(entrepriseId));
    if (immeubleId != null) params.set("immeuble_id", String(immeubleId));
    const r = await authedFetch(
      `/api/v1/immobilier/depots/overview?${params.toString()}`
    );
    if (r.ok) {
      const d = (await r.json()) as DepotOverview;
      setRows((d.rows || []).filter((x) => x.statut === "a_rendre"));
    }
  }, [entrepriseId, immeubleId]);

  useEffect(() => {
    void charger();
  }, [charger]);

  if (!rows || rows.length === 0) return null;
  const total = rows.reduce((acc, r) => acc + (r.montant || 0), 0);

  return (
    <div className="mt-5 rounded-xl border border-amber-500/30 bg-amber-500/5 p-4">
      <div className="mb-2 flex items-center gap-2 text-sm font-semibold text-amber-200">
        <span>💰 Dépôt de garantie à rembourser</span>
        <span className="text-xs font-normal text-white/50">
          {rows.length} locataire{rows.length > 1 ? "s" : ""} parti
          {rows.length > 1 ? "s" : ""} · {fmtMoney(total)} à rendre
        </span>
      </div>
      <p className="mb-3 text-xs text-white/50">
        Ces locataires sont partis et leur dépôt est toujours détenu.
        Clique une ligne pour ouvrir la page Dépôts et le marquer rendu.
      </p>
      <div className="space-y-1.5">
        {rows.map((r) => (
          <Link
            key={r.bail_id}
            href={"/immobilier/depots" as never}
            className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-amber-500/40 bg-amber-500/5 px-3 py-2 text-sm transition hover:border-amber-400/70 hover:bg-amber-500/10"
          >
            <span className="min-w-0">
              <span className="font-medium">
                {r.locataire_name || "Locataire"}
              </span>
              <span className="ml-2 text-xs text-white/50">
                {r.immeuble_name}
                {r.logement_numero ? ` · ${r.logement_numero}` : ""}
              </span>
            </span>
            <span className="flex items-center gap-3 text-xs text-white/60">
              {r.date_fin ? (
                <span>Parti le {fmtDateShort(r.date_fin)}</span>
              ) : null}
              <span className="badge badge-amber">
                {fmtMoney(r.montant)}
              </span>
            </span>
          </Link>
        ))}
      </div>
    </div>
  );
}
