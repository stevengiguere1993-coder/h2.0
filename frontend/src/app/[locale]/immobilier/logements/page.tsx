"use client";

import { useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  Building2,
  DoorOpen,
  Loader2,
  Search
} from "lucide-react";

import { Link, useRouter } from "@/i18n/navigation";
import { authedFetch } from "@/lib/auth";
import { ImmobilierTopbar, useImmobilierLayout } from "../layout";
import {
  fmtPieces,
  type LogementFicheData
} from "@/components/immobilier/logement-fiche";

/**
 * Logements — vue agrégée de TOUS les logements du portefeuille
 * (entreprise active via le contexte du layout). Filtres client-side :
 * recherche texte, immeuble, statut. Clic sur une ligne → PAGE fiche
 * logement (/immobilier/logements/{id}) ; la colonne immeuble reste
 * un lien vers la fiche immeuble.
 */

type ImmeubleLite = {
  id: number;
  name: string;
  address: string;
  city?: string | null;
  gestion_externe?: boolean;
};

type Logement = LogementFicheData;

type Row = Logement & {
  immeuble_name: string;
  immeuble_gestion_externe: boolean;
};

const STATUTS = [
  { value: "all", label: "Tous" },
  { value: "occupe", label: "Occupés" },
  { value: "vacant", label: "Vacants" },
  { value: "reserve", label: "Réservés" },
  { value: "hors_location", label: "Hors loc." }
];

function fmtMoney(n: number | null | undefined): string {
  if (n == null) return "—";
  return new Intl.NumberFormat("fr-CA", {
    style: "currency",
    currency: "CAD",
    maximumFractionDigits: 0
  }).format(n);
}

function StatutBadge({ status }: { status: string }) {
  const map: Record<string, { cls: string; label: string }> = {
    occupe: { cls: "badge-emerald", label: "Occupé" },
    vacant: { cls: "badge-amber", label: "Vacant" },
    reserve: { cls: "badge-sky", label: "Réservé" },
    hors_location: { cls: "badge-neutral", label: "Hors loc." }
  };
  const t = map[status] || { cls: "badge-neutral", label: status };
  return <span className={`badge ${t.cls}`}>{t.label}</span>;
}

export default function LogementsPage() {
  const { currentEntrepriseId } = useImmobilierLayout();
  const router = useRouter();
  const [rows, setRows] = useState<Row[] | null>(null);
  const [immeubles, setImmeubles] = useState<ImmeubleLite[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [immeubleFilter, setImmeubleFilter] = useState<number | "all">("all");
  const [statutFilter, setStatutFilter] = useState<string>("all");

  // Clic sur une ligne → page fiche logement (vraie page 360).
  function openFiche(row: Row) {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    router.push(`/immobilier/logements/${row.id}` as any);
  }

  useEffect(() => {
    let cancelled = false;
    setRows(null);
    setError(null);
    setImmeubleFilter("all");
    void (async () => {
      try {
        const url =
          currentEntrepriseId != null
            ? `/api/v1/immobilier/immeubles?entreprise_id=${currentEntrepriseId}`
            : "/api/v1/immobilier/immeubles";
        const res = await authedFetch(url);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const imms = (await res.json()) as ImmeubleLite[];
        if (cancelled) return;
        setImmeubles(imms);

        const lists = await Promise.all(
          imms.map(async (imm) => {
            const r = await authedFetch(
              `/api/v1/immobilier/immeubles/${imm.id}/logements`
            );
            if (!r.ok) return [] as Row[];
            const logs = (await r.json()) as Logement[];
            return logs.map((l) => ({
              ...l,
              immeuble_name: imm.name,
              immeuble_gestion_externe: !!imm.gestion_externe
            }));
          })
        );
        if (cancelled) return;
        setRows(lists.flat());
      } catch (err) {
        if (!cancelled) setError((err as Error).message);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [currentEntrepriseId]);

  const filtered = useMemo(() => {
    if (rows === null) return null;
    const q = search.trim().toLowerCase();
    return rows.filter((r) => {
      if (immeubleFilter !== "all" && r.immeuble_id !== immeubleFilter)
        return false;
      if (statutFilter !== "all" && r.status !== statutFilter) return false;
      if (q) {
        const hay = `${r.numero} ${r.immeuble_name} ${r.type}`.toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });
  }, [rows, search, immeubleFilter, statutFilter]);

  return (
    <>
      <ImmobilierTopbar
        breadcrumbs={[
          { label: "Gestion immobilière", href: "/immobilier" },
          { label: "Logements" }
        ]}
      />

      <div className="p-4 lg:p-6">
        <header className="flex items-start gap-3">
          <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-accent-500/15 text-accent-500">
            <DoorOpen className="h-5 w-5" />
          </span>
          <div>
            <h1 className="text-2xl font-bold text-white">Logements</h1>
            <p className="mt-1 max-w-2xl text-sm text-white/60">
              Tous les logements du portefeuille, tous immeubles confondus —
              statut, pièces et loyer demandé en un coup d&apos;œil.
            </p>
          </div>
        </header>

        {/* Filtres */}
        <div className="mt-5 flex flex-wrap items-center gap-2">
          <div className="relative max-w-md flex-1">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-white/40" />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Recherche n° de logement / immeuble…"
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
          {STATUTS.map((s) => (
            <FilterPill
              key={s.value}
              label={s.label}
              active={statutFilter === s.value}
              onClick={() => setStatutFilter(s.value)}
            />
          ))}
          {filtered ? (
            <span className="text-xs text-white/50">
              {filtered.length} / {rows?.length || 0}
            </span>
          ) : null}
        </div>

        {error ? (
          <p className="mt-4 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
            <AlertTriangle className="mr-1.5 inline h-3.5 w-3.5" />
            {error}
          </p>
        ) : null}

        {filtered === null ? (
          <p className="mt-4 text-xs text-white/50">
            <Loader2 className="mr-1 inline h-3 w-3 animate-spin" />{" "}
            Chargement…
          </p>
        ) : filtered.length === 0 ? (
          <p className="mt-4 rounded-lg border border-brand-800 bg-brand-900 px-4 py-3 text-sm text-white/60">
            Aucun logement{" "}
            {rows && rows.length > 0
              ? "correspondant aux filtres"
              : "dans le portefeuille"}
            .
          </p>
        ) : (
          <div className="mt-4 overflow-hidden rounded-2xl border border-brand-800 bg-brand-900">
            <div className="overflow-x-auto">
              <table className="w-full min-w-[720px] text-left text-sm">
                <thead className="border-b border-brand-800 bg-brand-950 text-[10px] uppercase tracking-wider text-white/50">
                  <tr>
                    <th className="px-4 py-2.5">Logement</th>
                    <th className="px-4 py-2.5">Immeuble</th>
                    <th className="px-4 py-2.5">Type</th>
                    <th className="px-4 py-2.5">Pièces</th>
                    <th className="px-4 py-2.5 text-right">Loyer demandé</th>
                    <th className="px-4 py-2.5 text-right">Statut</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-brand-800">
                  {filtered.map((l) => (
                    <tr
                      key={l.id}
                      onClick={() => openFiche(l)}
                      className="group cursor-pointer hover:bg-brand-950/50"
                    >
                      <td className="px-4 py-3">
                        <span className="flex items-center gap-3">
                          <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-accent-500/15 text-accent-500">
                            <DoorOpen className="h-4 w-4" />
                          </span>
                          <span className="font-bold text-white group-hover:text-accent-500">
                            {l.numero}
                          </span>
                        </span>
                      </td>
                      <td className="px-4 py-3 text-xs text-white/70">
                        <Link
                          // eslint-disable-next-line @typescript-eslint/no-explicit-any
                          href={`/immobilier/immeubles/${l.immeuble_id}` as any}
                          onClick={(e) => e.stopPropagation()}
                          className="inline-flex items-center gap-1.5 hover:text-accent-500"
                        >
                          <Building2 className="h-3.5 w-3.5 text-white/40" />
                          {l.immeuble_name}
                        </Link>
                        {l.immeuble_gestion_externe ? (
                          <span className="ml-1.5 badge badge-sky">
                            Gestion externe
                          </span>
                        ) : null}
                      </td>
                      <td className="px-4 py-3 text-xs text-white/60">
                        {l.type}
                      </td>
                      <td className="px-4 py-3 font-mono text-xs text-white/70">
                        {l.location_en_chambres
                          ? "Chambre"
                          : fmtPieces(l.nb_pieces_decimal)}
                      </td>
                      <td className="px-4 py-3 text-right font-mono text-xs text-white/80">
                        {fmtMoney(l.loyer_demande)}
                      </td>
                      <td className="px-4 py-3 text-right">
                        <StatutBadge status={l.status} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
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
