"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { AlertTriangle, Loader2, Search, ShieldCheck } from "lucide-react";

import { Link } from "@/i18n/navigation";
import { authedFetch } from "@/lib/auth";
import { ImmobilierTopbar, useImmobilierLayout } from "../layout";

/**
 * Dépôts de garantie — suivi des dépôts détenus (baux actifs) et à rendre
 * (baux terminés/résiliés). Évite d'oublier de rembourser un locataire.
 */

type DepotRow = {
  bail_id: number;
  immeuble_id: number;
  immeuble_name: string;
  logement_numero: string | null;
  locataire_id: number | null;
  locataire_name: string | null;
  montant: number;
  statut: string; // "detenu" | "a_rendre"
  date_debut: string;
  date_fin: string;
};

type Overview = {
  rows: DepotRow[];
  total_detenu: number;
  total_a_rendre: number;
  nb_a_rendre: number;
};

function money(n: number | null | undefined): string {
  if (n == null) return "—";
  return n.toLocaleString("fr-CA", {
    style: "currency",
    currency: "CAD",
    maximumFractionDigits: 0
  });
}

export default function DepotsPage() {
  const { currentEntrepriseId } = useImmobilierLayout();
  const [data, setData] = useState<Overview | null>(null);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [statutFilter, setStatutFilter] = useState<
    "all" | "detenu" | "a_rendre"
  >("all");
  const [immeubleFilter, setImmeubleFilter] = useState<number | "all">("all");

  const load = useCallback(async () => {
    setLoading(true);
    const params = new URLSearchParams();
    if (currentEntrepriseId != null) {
      params.set("entreprise_id", String(currentEntrepriseId));
    }
    const r = await authedFetch(
      `/api/v1/immobilier/depots/overview?${params.toString()}`
    );
    if (r.ok) setData((await r.json()) as Overview);
    setLoading(false);
  }, [currentEntrepriseId]);

  useEffect(() => {
    void load();
  }, [load]);

  // Immeubles distincts présents dans les rows chargées (pour le select).
  const immeubles = useMemo(() => {
    const m = new Map<number, string>();
    for (const r of data?.rows || []) m.set(r.immeuble_id, r.immeuble_name);
    return [...m.entries()]
      .map(([id, name]) => ({ id, name }))
      .sort((a, b) => a.name.localeCompare(b.name, "fr"));
  }, [data]);

  // Filtres client-side sur les rows chargées.
  const filteredRows = useMemo(() => {
    if (!data) return [];
    const q = search.trim().toLowerCase();
    return data.rows.filter((r) => {
      if (statutFilter !== "all" && r.statut !== statutFilter) return false;
      if (immeubleFilter !== "all" && r.immeuble_id !== immeubleFilter)
        return false;
      if (q) {
        const hay = `${r.locataire_name || ""} ${r.immeuble_name} ${
          r.logement_numero || ""
        }`.toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });
  }, [data, search, statutFilter, immeubleFilter]);

  return (
    <>
      <ImmobilierTopbar
        breadcrumbs={[
          { label: "Gestion immobilière", href: "/immobilier" },
          { label: "Dépôts de garantie" }
        ]}
      />
      <div className="p-4 lg:p-6">
        <header className="flex items-start gap-3">
          <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-violet-500/15 text-violet-300">
            <ShieldCheck className="h-5 w-5" />
          </span>
          <div>
            <h1 className="text-2xl font-bold text-white">
              Dépôts de garantie
            </h1>
            <p className="mt-1 max-w-2xl text-sm text-white/60">
              Ce que tu détiens (baux actifs) et ce qu&apos;il faut rendre
              (baux terminés). Pour ne jamais oublier un remboursement.
            </p>
          </div>
        </header>

        <div className="mt-6 grid grid-cols-1 gap-3 sm:grid-cols-3">
          <div className="rounded-2xl border border-rose-500/40 bg-rose-500/10 p-4 text-rose-200">
            <div className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wider opacity-80">
              <AlertTriangle className="h-3.5 w-3.5" /> À rendre
            </div>
            <div className="mt-1 text-3xl font-bold">
              {money(data?.total_a_rendre ?? 0)}
            </div>
            <div className="text-[11px] opacity-70">
              {data?.nb_a_rendre ?? 0} bail
              {(data?.nb_a_rendre ?? 0) > 1 ? "s" : ""} terminé
              {(data?.nb_a_rendre ?? 0) > 1 ? "s" : ""}
            </div>
          </div>
          <div className="rounded-2xl border border-violet-500/30 bg-violet-500/5 p-4 text-violet-200">
            <div className="text-[11px] font-semibold uppercase tracking-wider opacity-80">
              Détenus (baux actifs)
            </div>
            <div className="mt-1 text-3xl font-bold">
              {money(data?.total_detenu ?? 0)}
            </div>
          </div>
          <div className="rounded-2xl border border-white/15 bg-white/5 p-4 text-white/70">
            <div className="text-[11px] font-semibold uppercase tracking-wider opacity-80">
              Total au portefeuille
            </div>
            <div className="mt-1 text-3xl font-bold">
              {money((data?.total_detenu ?? 0) + (data?.total_a_rendre ?? 0))}
            </div>
          </div>
        </div>

        {/* Filtres */}
        <div className="mt-6 flex flex-wrap items-center gap-2">
          <div className="relative max-w-md flex-1">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-white/40" />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Recherche locataire / immeuble / logement…"
              className="input w-full pl-9"
            />
          </div>
          <select
            value={immeubleFilter === "all" ? "all" : String(immeubleFilter)}
            onChange={(e) =>
              setImmeubleFilter(
                e.target.value === "all" ? "all" : Number(e.target.value)
              )
            }
            className="input w-auto max-w-[220px] text-sm"
          >
            <option value="all">Tous les immeubles</option>
            {immeubles.map((imm) => (
              <option key={imm.id} value={imm.id}>
                {imm.name}
              </option>
            ))}
          </select>
          <FilterPill
            label="Tous"
            active={statutFilter === "all"}
            onClick={() => setStatutFilter("all")}
          />
          <FilterPill
            label="Détenus"
            active={statutFilter === "detenu"}
            onClick={() => setStatutFilter("detenu")}
          />
          <FilterPill
            label="À rendre"
            active={statutFilter === "a_rendre"}
            onClick={() => setStatutFilter("a_rendre")}
          />
          {data ? (
            <span className="text-xs text-white/50">
              {filteredRows.length} / {data.rows.length}
            </span>
          ) : null}
        </div>

        <div className="mt-4 overflow-x-auto rounded-2xl border border-brand-800">
          <table className="w-full min-w-[720px] text-sm">
            <thead>
              <tr className="border-b border-brand-800 bg-brand-900 text-left text-[11px] uppercase tracking-wider text-white/45">
                <th className="px-3 py-2.5 font-semibold">Locataire</th>
                <th className="px-3 py-2.5 font-semibold">Immeuble · logt</th>
                <th className="px-3 py-2.5 font-semibold">Période</th>
                <th className="px-3 py-2.5 text-right font-semibold">Dépôt</th>
                <th className="px-3 py-2.5 text-right font-semibold">Statut</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr>
                  <td colSpan={5} className="px-3 py-10 text-center text-white/50">
                    <Loader2 className="mr-1 inline h-4 w-4 animate-spin" />{" "}
                    Chargement…
                  </td>
                </tr>
              ) : !data || filteredRows.length === 0 ? (
                <tr>
                  <td colSpan={5} className="px-3 py-12 text-center text-white/50">
                    {data && data.rows.length > 0
                      ? "Aucun dépôt correspondant aux filtres."
                      : "Aucun dépôt de garantie enregistré."}
                  </td>
                </tr>
              ) : (
                filteredRows.map((r) => (
                  <tr
                    key={r.bail_id}
                    className={`border-b border-brand-800/60 hover:bg-brand-900/40 ${
                      r.statut === "a_rendre" ? "bg-rose-500/[0.04]" : ""
                    }`}
                  >
                    <td className="px-3 py-2.5">
                      {r.locataire_id ? (
                        <Link
                          // eslint-disable-next-line @typescript-eslint/no-explicit-any
                          href={`/immobilier/locataires/${r.locataire_id}` as any}
                          className="font-medium text-white hover:text-accent-500"
                        >
                          {r.locataire_name || "—"}
                        </Link>
                      ) : (
                        <span className="text-white/70">
                          {r.locataire_name || "—"}
                        </span>
                      )}
                    </td>
                    <td className="px-3 py-2.5 text-white/70">
                      <Link
                        // eslint-disable-next-line @typescript-eslint/no-explicit-any
                        href={`/immobilier/immeubles/${r.immeuble_id}` as any}
                        className="hover:text-accent-500"
                      >
                        {r.immeuble_name}
                      </Link>
                      {r.logement_numero ? (
                        <span className="text-white/40"> · {r.logement_numero}</span>
                      ) : null}
                    </td>
                    <td className="px-3 py-2.5 text-xs text-white/60">
                      {r.date_debut} → {r.date_fin}
                    </td>
                    <td className="px-3 py-2.5 text-right font-semibold tabular-nums text-white">
                      {money(r.montant)}
                    </td>
                    <td className="px-3 py-2.5 text-right">
                      {r.statut === "a_rendre" ? (
                        <span className="badge badge-rose">
                          À rendre
                        </span>
                      ) : (
                        <span className="badge badge-violet">
                          Détenu
                        </span>
                      )}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </>
  );
}

function FilterPill({
  label,
  active,
  onClick
}: {
  label: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`rounded-full px-3 py-1 text-xs font-semibold transition ${
        active
          ? "bg-brand-900 text-white"
          : "border border-white/10 bg-brand-950 text-white/60 hover:text-white"
      }`}
    >
      {label}
    </button>
  );
}
