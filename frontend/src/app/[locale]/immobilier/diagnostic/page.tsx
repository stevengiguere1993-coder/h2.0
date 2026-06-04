"use client";

import { useEffect, useState } from "react";
import { AlertTriangle, Loader2 } from "lucide-react";

import { authedFetch } from "@/lib/auth";
import { ImmobilierTopbar } from "../layout";

type Row = {
  id: number;
  name: string;
  address: string | null;
  city: string | null;
  scope: "entreprise" | "deal" | "global";
  nb_logements: number;
  nb_baux: number;
  is_duplicate_name: boolean;
  is_active: boolean;
  created_at: string | null;
};

const SCOPE_LABEL: Record<Row["scope"], string> = {
  entreprise: "Entreprise",
  deal: "Deal",
  global: "Global"
};

export default function ImmeublesDiagnosticPage() {
  const [rows, setRows] = useState<Row[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const r = await authedFetch("/api/v1/immobilier/immeubles/diagnostic");
        if (r.status === 403) throw new Error("Réservé aux administrateurs.");
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        if (!cancelled) setRows((await r.json()) as Row[]);
      } catch (e) {
        if (!cancelled) setError((e as Error).message);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const dupCount = (rows || []).filter((r) => r.is_duplicate_name).length;

  return (
    <>
      <ImmobilierTopbar
        breadcrumbs={[
          { label: "Gestion immobilière", href: "/immobilier" },
          { label: "Diagnostic immeubles" }
        ]}
      />
      <div className="p-4 lg:p-6">
        <h1 className="text-xl font-bold text-white">
          Diagnostic des immeubles (doublons)
        </h1>
        <p className="mt-1 max-w-2xl text-sm text-white/60">
          Tous les immeubles, avec leur scope et ce qui y est rattaché. Un
          immeuble en double <strong>sans logement ni bail</strong> (souvent
          créé sans adresse via un picker de tâche) est généralement celui à
          supprimer ; celui qui porte les logements/baux est le « vrai ».
        </p>

        {error ? (
          <p className="mt-4 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-200">
            {error}
          </p>
        ) : !rows ? (
          <div className="mt-6 flex items-center gap-2 text-xs text-white/50">
            <Loader2 className="h-3.5 w-3.5 animate-spin" /> Chargement…
          </div>
        ) : (
          <>
            <p className="mt-4 text-xs text-white/60">
              {rows.length} immeuble(s) ·{" "}
              <span className="text-amber-300">
                {dupCount} en doublon de nom
              </span>
            </p>
            <div className="mt-3 overflow-x-auto rounded-2xl border border-brand-800 bg-brand-900">
              <table className="w-full text-left text-sm">
                <thead className="border-b border-brand-800 bg-brand-950 text-[10px] uppercase tracking-wider text-white/50">
                  <tr>
                    <th className="px-3 py-2.5">#</th>
                    <th className="px-3 py-2.5">Nom</th>
                    <th className="px-3 py-2.5">Adresse</th>
                    <th className="px-3 py-2.5">Scope</th>
                    <th className="px-3 py-2.5 text-right">Logements</th>
                    <th className="px-3 py-2.5 text-right">Baux</th>
                    <th className="px-3 py-2.5">Créé le</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-brand-800">
                  {rows.map((r) => {
                    const empty = r.nb_logements === 0 && r.nb_baux === 0;
                    const suspect = r.is_duplicate_name && empty;
                    return (
                      <tr
                        key={r.id}
                        className={suspect ? "bg-amber-500/10" : undefined}
                      >
                        <td className="px-3 py-2 font-mono text-xs text-white/60">
                          {r.id}
                        </td>
                        <td className="px-3 py-2 font-medium text-white">
                          <span className="inline-flex items-center gap-1.5">
                            {r.is_duplicate_name ? (
                              <AlertTriangle className="h-3.5 w-3.5 text-amber-400" />
                            ) : null}
                            {r.name}
                          </span>
                        </td>
                        <td className="px-3 py-2 text-xs text-white/70">
                          {r.address || "—"}
                          {r.city ? `, ${r.city}` : ""}
                        </td>
                        <td className="px-3 py-2 text-xs text-white/70">
                          {SCOPE_LABEL[r.scope]}
                        </td>
                        <td className="px-3 py-2 text-right font-mono text-xs text-white/80">
                          {r.nb_logements}
                        </td>
                        <td className="px-3 py-2 text-right font-mono text-xs text-white/80">
                          {r.nb_baux}
                        </td>
                        <td className="px-3 py-2 text-[11px] text-white/50">
                          {r.created_at
                            ? new Date(r.created_at).toLocaleDateString("fr-CA")
                            : "—"}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <p className="mt-3 text-[11px] text-white/40">
              Lignes surlignées = doublon de nom <em>sans</em> logement ni bail
              (candidats à la suppression). Dis-moi les # à supprimer et
              j'ajoute la fusion/suppression sécurisée.
            </p>
          </>
        )}
      </div>
    </>
  );
}
