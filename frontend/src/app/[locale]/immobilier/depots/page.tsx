"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  Check,
  Loader2,
  Pencil,
  RotateCcw,
  Search,
  ShieldCheck,
  X
} from "lucide-react";

import { Link } from "@/i18n/navigation";
import { authedFetch } from "@/lib/auth";
import { ImmobilierTopbar, useImmobilierLayout } from "../layout";

/**
 * Dépôts de garantie — OPÉRATIONNEL (retour Phil 2026-07-10) : on peut
 * saisir/modifier le montant du dépôt de chaque bail directement ici
 * (PATCH bail), marquer un dépôt comme rendu au locataire, et les baux
 * actifs SANS dépôt apparaissent comme lignes « à saisir ».
 */

type DepotRow = {
  bail_id: number;
  immeuble_id: number;
  immeuble_name: string;
  logement_id?: number | null;
  logement_numero: string | null;
  locataire_id: number | null;
  locataire_name: string | null;
  montant: number;
  statut: string; // "detenu" | "a_rendre" | "rendu" | "aucun" | "transfere" | "saisi"
  depot_recu_le: string | null;
  depot_detenteur: string | null;
  depot_rendu_le: string | null;
  //: Dépôt gardé (2026-10-08) : date, montant gardé, motif, reste à rendre.
  depot_saisi_le?: string | null;
  depot_saisi_montant?: number | null;
  depot_saisi_motif?: string | null;
  reste_a_rendre?: number;
  //: Transfert d'unité : le dépôt est parti vers / venu d'un autre logement.
  transfere_vers_logement?: string | null;
  transfere_depuis_logement?: string | null;
  date_debut: string;
  date_fin: string;
};

type Overview = {
  rows: DepotRow[];
  total_detenu: number;
  total_a_rendre: number;
  nb_a_rendre: number;
  total_rendu: number;
  nb_sans_depot: number;
  total_saisi?: number;
  nb_saisi?: number;
};

function money(n: number | null | undefined): string {
  if (n == null) return "—";
  return n.toLocaleString("fr-CA", {
    style: "currency",
    currency: "CAD",
    maximumFractionDigits: 0
  });
}

/** Date de réception + détenteur du dépôt, MODIFIABLES sur place
 *  (retour Phil 2026-09-09 : « date inconnue » partout parce qu'aucun
 *  formulaire ne les écrivait). */
function DepotInfosCell({
  row,
  onSave
}: {
  row: { depot_recu_le?: string | null; depot_detenteur?: string | null; date_debut?: string | null };
  onSave: (patch: { depot_recu_le?: string | null; depot_detenteur?: string | null }) => Promise<boolean>;
}) {
  const [date, setDate] = useState(row.depot_recu_le ?? "");
  const [det, setDet] = useState(row.depot_detenteur ?? "");
  useEffect(() => {
    setDate(row.depot_recu_le ?? "");
    setDet(row.depot_detenteur ?? "");
  }, [row.depot_recu_le, row.depot_detenteur]);
  return (
    <div className="space-y-1">
      <input
        type="date"
        value={date}
        onChange={(e) => setDate(e.target.value)}
        onBlur={() => {
          if ((date || null) !== (row.depot_recu_le ?? null))
            void onSave({ depot_recu_le: date || null });
        }}
        className="input w-36 py-0.5 text-xs"
        title={
          row.depot_recu_le
            ? "Date de réception du dépôt"
            : `Date à compléter${row.date_debut ? ` (bail débuté le ${row.date_debut})` : ""}`
        }
      />
      <input
        value={det}
        onChange={(e) => setDet(e.target.value)}
        onBlur={() => {
          if ((det.trim() || null) !== (row.depot_detenteur ?? null))
            void onSave({ depot_detenteur: det.trim() || null });
        }}
        placeholder="détenteur à préciser"
        className="input w-36 py-0.5 text-[11px]"
        title="Qui détient l'argent du dépôt"
      />
    </div>
  );
}

export default function DepotsPage() {
  const { currentEntrepriseId } = useImmobilierLayout();
  const [data, setData] = useState<Overview | null>(null);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [statutFilter, setStatutFilter] = useState<
    "all" | "detenu" | "a_rendre" | "aucun" | "rendu" | "transfere" | "saisi"
  >("all");
  const [garderPour, setGarderPour] = useState<DepotRow | null>(null);
  const [immeubleFilter, setImmeubleFilter] = useState<number | "all">("all");
  const [actionErr, setActionErr] = useState<string | null>(null);

  async function patchBail(
    bailId: number,
    body: Record<string, unknown>
  ): Promise<boolean> {
    setActionErr(null);
    const r = await authedFetch(`/api/v1/immobilier/baux/${bailId}`, {
      method: "PATCH",
      body: JSON.stringify(body)
    });
    if (!r.ok) {
      const t = await r.text();
      setActionErr(t.slice(0, 200) || `HTTP ${r.status}`);
      return false;
    }
    return true;
  }

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

  //: Les tuiles du haut suivent les FILTRES (retour Phil 2026-07-30) :
  //: filtrer un immeuble ou un locataire recalcule à rendre / détenu.
  const stats = useMemo(() => {
    let aRendre = 0;
    let nbARendre = 0;
    let detenu = 0;
    let saisi = 0;
    for (const r of filteredRows) {
      const garde = r.depot_saisi_le ? (r.depot_saisi_montant ?? r.montant) : 0;
      if (r.statut === "a_rendre") {
        aRendre += r.reste_a_rendre ?? r.montant - garde;
        nbARendre += 1;
        saisi += garde;
      } else if (r.statut === "detenu") {
        detenu += r.reste_a_rendre ?? r.montant - garde;
        saisi += garde;
      } else if (r.statut === "saisi") {
        saisi += garde;
      }
    }
    return { aRendre, nbARendre, detenu, saisi };
  }, [filteredRows]);
  const filtreActif =
    search.trim() !== "" || statutFilter !== "all" || immeubleFilter !== "all";

  return (
    <>
      <ImmobilierTopbar
        breadcrumbs={[
          { label: "Immobilier", href: "/immobilier" },
          { label: "Dépôts de garantie" }
        ]}
      />
      <GarderDepotModal
        row={garderPour}
        onClose={() => setGarderPour(null)}
        onConfirm={async (montant, motif) => {
          if (!garderPour) return;
          const ok = await patchBail(garderPour.bail_id, {
            depot_saisi_le: new Date().toISOString().slice(0, 10),
            depot_saisi_montant: montant,
            depot_saisi_motif: motif || null,
            depot_rendu_le: null
          });
          if (ok) {
            setGarderPour(null);
            void load();
          }
        }}
      />
      <div className="p-4 pb-28 lg:p-6 lg:pb-28">
        <header className="flex items-start gap-3">
          <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-violet-500/15 text-violet-300">
            <ShieldCheck className="h-5 w-5" />
          </span>
          <div>
            <h1 className="text-2xl font-bold text-white">
              Dépôts de garantie
            </h1>
            <p className="mt-1 max-w-2xl text-sm text-white/60">
              Ce que tu détiens, ce qu&apos;il faut rendre et ce qui a été
              gardé. Un dépôt passe « à rendre » quand le départ est acté
              ou que le logement a été remis en location à quelqu&apos;un
              d&apos;autre — pas juste parce que le bail est fini. « Garder »
              consigne la retenue (en tout ou en partie) et son motif.
            </p>
          </div>
        </header>

        <div className="mt-6 grid grid-cols-1 gap-3 sm:grid-cols-4">
          <div className="rounded-2xl border border-rose-500/40 bg-rose-500/10 p-4 text-rose-200">
            <div className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wider opacity-80">
              <AlertTriangle className="h-3.5 w-3.5" /> À rendre
              {filtreActif ? " (filtré)" : ""}
            </div>
            <div className="mt-1 text-3xl font-bold">
              {money(stats.aRendre)}
            </div>
            <div className="text-[11px] opacity-70">
              {stats.nbARendre} logement
              {stats.nbARendre > 1 ? "s" : ""} reloué
              {stats.nbARendre > 1 ? "s" : ""} — ancien locataire à
              rembourser
            </div>
          </div>
          <div className="rounded-2xl border border-violet-500/30 bg-violet-500/5 p-4 text-violet-200">
            <div className="text-[11px] font-semibold uppercase tracking-wider opacity-80">
              Détenus{filtreActif ? " (filtré)" : ""}
            </div>
            <div className="mt-1 text-3xl font-bold">
              {money(stats.detenu)}
            </div>
          </div>
          <div className="rounded-2xl border border-amber-500/30 bg-amber-500/5 p-4 text-amber-200">
            <div className="text-[11px] font-semibold uppercase tracking-wider opacity-80">
              Gardés{filtreActif ? " (filtré)" : ""}
            </div>
            <div className="mt-1 text-3xl font-bold">
              {money(stats.saisi)}
            </div>
            <div className="text-[11px] opacity-70">
              dépôts conservés (préavis, dommages, impayés)
            </div>
          </div>
          <div className="rounded-2xl border border-white/15 bg-white/5 p-4 text-white/70">
            <div className="text-[11px] font-semibold uppercase tracking-wider opacity-80">
              Total{filtreActif ? " (filtré)" : " au portefeuille"}
            </div>
            <div className="mt-1 text-3xl font-bold">
              {money(stats.detenu + stats.aRendre)}
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
          <FilterPill
            label={`Sans dépôt${
              data?.nb_sans_depot ? ` (${data.nb_sans_depot})` : ""
            }`}
            active={statutFilter === "aucun"}
            onClick={() => setStatutFilter("aucun")}
          />
          <FilterPill
            label={`Gardés${data?.nb_saisi ? ` (${data.nb_saisi})` : ""}`}
            active={statutFilter === "saisi"}
            onClick={() => setStatutFilter("saisi")}
          />
          <FilterPill
            label="Transférés"
            active={statutFilter === "transfere"}
            onClick={() => setStatutFilter("transfere")}
          />
          <FilterPill
            label="Rendus"
            active={statutFilter === "rendu"}
            onClick={() => setStatutFilter("rendu")}
          />
        </div>

        {actionErr ? (
          <p className="mt-3 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">
            {actionErr}
          </p>
        ) : null}

        <div className="mt-4 overflow-x-auto rounded-2xl border border-brand-800">
          <table className="w-full min-w-[800px] text-sm">
            <thead>
              <tr className="border-b border-brand-800 bg-brand-900 text-left text-[11px] uppercase tracking-wider text-white/45">
                <th className="px-3 py-2.5 font-semibold">Locataire</th>
                <th className="px-3 py-2.5 font-semibold">Immeuble · logt</th>
                <th className="px-3 py-2.5 font-semibold">Période</th>
                <th className="px-3 py-2.5 text-right font-semibold">Dépôt</th>
                <th className="px-3 py-2.5 font-semibold">Reçu · détenu par</th>
                <th className="px-3 py-2.5 text-right font-semibold">Statut</th>
                <th className="px-3 py-2.5 text-right font-semibold">Rendu</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr>
                  <td colSpan={7} className="px-3 py-10 text-center text-white/50">
                    <Loader2 className="mr-1 inline h-4 w-4 animate-spin" />{" "}
                    Chargement…
                  </td>
                </tr>
              ) : !data || filteredRows.length === 0 ? (
                <tr>
                  <td colSpan={7} className="px-3 py-12 text-center text-white/50">
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
                      r.statut === "a_rendre"
                        ? "bg-rose-500/[0.04]"
                        : r.statut === "rendu"
                          ? "bg-emerald-500/[0.05]"
                          : ""
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
                        r.logement_id != null ? (
                          <Link
                            // eslint-disable-next-line @typescript-eslint/no-explicit-any
                            href={
                              `/immobilier/logements/${r.logement_id}` as any
                            }
                            className="text-accent-500/80 hover:text-accent-500 hover:underline"
                            title="Ouvrir la fiche du logement"
                          >
                            {" "}
                            · {r.logement_numero}
                          </Link>
                        ) : (
                          <span className="text-white/40">
                            {" "}
                            · {r.logement_numero}
                          </span>
                        )
                      ) : null}
                    </td>
                    <td className="px-3 py-2.5 text-xs text-white/60">
                      {r.date_debut} → {r.date_fin}
                    </td>
                    <td className="px-3 py-2.5 text-right">
                      <MontantCell
                        row={r}
                        onSave={async (montant) => {
                          const ok = await patchBail(r.bail_id, {
                            depot_garantie: montant
                          });
                          if (ok) void load();
                          return ok;
                        }}
                      />
                    </td>
                    {/* Un dépôt est l'argent du locataire : savoir quand
                        il est entré et chez qui il dort n'est pas un
                        détail au moment de le rendre. */}
                    <td className="px-3 py-2.5 text-xs text-white/60">
                      {r.montant > 0 ? (
                        <DepotInfosCell
                          row={r}
                          onSave={async (patch) => {
                            const ok = await patchBail(r.bail_id, patch);
                            if (ok) void load();
                            return ok;
                          }}
                        />
                      ) : (
                        <span className="text-white/25">—</span>
                      )}
                    </td>
                    <td className="px-3 py-2.5 text-right">
                      {r.statut === "a_rendre" ? (
                        <span className="badge badge-rose">
                          À rendre
                          {r.depot_saisi_le
                            ? ` ${money(r.reste_a_rendre ?? 0)} (gardé ${money(
                                r.depot_saisi_montant ?? 0
                              )})`
                            : ""}
                        </span>
                      ) : r.statut === "saisi" ? (
                        <span
                          className="badge badge-amber"
                          title={r.depot_saisi_motif || "Dépôt gardé"}
                        >
                          Gardé{r.depot_saisi_le ? ` le ${r.depot_saisi_le}` : ""}
                          {r.depot_saisi_motif ? ` — ${r.depot_saisi_motif}` : ""}
                        </span>
                      ) : r.statut === "rendu" ? (
                        <span className="badge badge-emerald">
                          Rendu{r.depot_rendu_le ? ` le ${r.depot_rendu_le}` : ""}
                        </span>
                      ) : r.statut === "aucun" ? (
                        <span
                          className="badge border border-white/10 text-white/50"
                          title="Bail actif sans montant de dépôt entré — saisis-le dans la colonne Montant"
                        >
                          Sans dépôt
                        </span>
                      ) : r.statut === "transfere" ? (
                        <span
                          className="badge badge-sky"
                          title="Transfert d'unité : le dépôt a suivi le locataire sur son nouveau bail — rien à rendre"
                        >
                          Transféré
                          {r.transfere_vers_logement
                            ? ` → Log. ${r.transfere_vers_logement}`
                            : ""}
                        </span>
                      ) : (
                        <span className="badge badge-violet">
                          Détenu
                          {r.transfere_depuis_logement ? (
                            <span
                              className="ml-1 font-normal opacity-70"
                              title="Reçu par transfert d'unité"
                            >
                              (du log. {r.transfere_depuis_logement})
                            </span>
                          ) : null}
                        </span>
                      )}
                    </td>
                    <td className="px-3 py-2.5 text-right">
                      {r.statut === "detenu" || r.statut === "a_rendre" ? (
                        <button
                          type="button"
                          title="Garder le dépôt (en tout ou en partie) — préavis insuffisant, dommages, loyers impayés"
                          onClick={() => setGarderPour(r)}
                          className="mr-1 rounded-md border border-amber-400/30 bg-amber-500/10 px-2 py-1 text-[11px] font-semibold text-amber-200 hover:bg-amber-500/20"
                        >
                          Garder
                        </button>
                      ) : null}
                      {r.statut === "saisi" ? (
                        <button
                          type="button"
                          title="Annuler — le dépôt n'a pas été gardé"
                          onClick={async () => {
                            if (!window.confirm("Annuler ? Le dépôt redeviendra détenu.")) return;
                            const ok = await patchBail(r.bail_id, {
                              depot_saisi_le: null,
                              depot_saisi_montant: null,
                              depot_saisi_motif: null
                            });
                            if (ok) void load();
                          }}
                          className="rounded-md border border-white/10 px-1.5 py-1 text-white/50 hover:text-white"
                        >
                          <RotateCcw className="h-3 w-3" />
                        </button>
                      ) : null}
                      {r.statut === "detenu" || r.statut === "a_rendre" ? (
                        <button
                          type="button"
                          title="Marquer le dépôt comme remboursé au locataire"
                          onClick={async () => {
                            if (
                              !window.confirm(
                                `Marquer le dépôt de ${
                                  r.locataire_name || "ce locataire"
                                } (${money(r.montant)}) comme RENDU ?\n\nLa ligne passera en vert avec la date d'aujourd'hui.`
                              )
                            )
                              return;
                            const today = new Date()
                              .toISOString()
                              .slice(0, 10);
                            const ok = await patchBail(r.bail_id, {
                              depot_rendu_le: today
                            });
                            if (ok) void load();
                          }}
                          className="rounded-md border border-emerald-400/30 bg-emerald-500/10 px-2 py-1 text-[11px] font-semibold text-emerald-200 hover:bg-emerald-500/20"
                        >
                          <Check className="mr-1 inline h-3 w-3" />
                          Rendu
                        </button>
                      ) : r.statut === "rendu" ? (
                        <button
                          type="button"
                          title="Annuler — le dépôt n'a pas été rendu"
                          onClick={async () => {
                            if (
                              !window.confirm(
                                "Annuler ? Le dépôt redeviendra détenu."
                              )
                            )
                              return;
                            const ok = await patchBail(r.bail_id, {
                              depot_rendu_le: null
                            });
                            if (ok) void load();
                          }}
                          className="rounded-md border border-white/10 px-1.5 py-1 text-white/50 hover:text-white"
                        >
                          <RotateCcw className="h-3 w-3" />
                        </button>
                      ) : (
                        <span className="text-white/25">—</span>
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

function MontantCell({
  row,
  onSave
}: {
  row: DepotRow;
  onSave: (montant: number) => Promise<boolean>;
}) {
  const [editing, setEditing] = useState(false);
  const [val, setVal] = useState("");
  const [saving, setSaving] = useState(false);

  if (!editing) {
    return (
      <span className="inline-flex items-center gap-1.5">
        <span
          className={`font-semibold tabular-nums ${
            row.montant > 0 ? "text-white" : "text-white/35"
          }`}
        >
          {row.montant > 0 ? money(row.montant) : "—"}
        </span>
        <button
          type="button"
          title={row.montant > 0 ? "Modifier le dépôt" : "Saisir le dépôt"}
          onClick={() => {
            setVal(row.montant > 0 ? String(row.montant) : "");
            setEditing(true);
          }}
          className="rounded p-1 text-white/35 hover:bg-brand-900 hover:text-white"
        >
          <Pencil className="h-3 w-3" />
        </button>
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1">
      <input
        autoFocus
        type="number"
        min={0}
        step={0.01}
        value={val}
        onChange={(e) => setVal(e.target.value)}
        onKeyDown={async (e) => {
          if (e.key === "Escape") setEditing(false);
          if (e.key === "Enter" && val.trim() !== "") {
            setSaving(true);
            if (await onSave(Number(val))) setEditing(false);
            setSaving(false);
          }
        }}
        className="w-24 rounded-md border border-brand-800 bg-brand-950 px-2 py-1 text-right text-xs text-white outline-none focus:border-accent-500"
        placeholder="0,00"
      />
      <button
        type="button"
        disabled={saving || val.trim() === "" || Number.isNaN(Number(val))}
        onClick={async () => {
          setSaving(true);
          if (await onSave(Number(val))) setEditing(false);
          setSaving(false);
        }}
        className="rounded-md border border-emerald-400/30 bg-emerald-500/10 p-1 text-emerald-200 hover:bg-emerald-500/20 disabled:opacity-40"
      >
        {saving ? (
          <Loader2 className="h-3 w-3 animate-spin" />
        ) : (
          <Check className="h-3 w-3" />
        )}
      </button>
      <button
        type="button"
        onClick={() => setEditing(false)}
        className="rounded-md border border-white/10 p-1 text-white/50 hover:text-white"
      >
        <X className="h-3 w-3" />
      </button>
    </span>
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


/** Garder un dépôt (Phil 2026-10-08) : montant conservé + motif. */
function GarderDepotModal({
  row,
  onClose,
  onConfirm
}: {
  row: DepotRow | null;
  onClose: () => void;
  onConfirm: (montant: number, motif: string) => Promise<void> | void;
}) {
  const [montant, setMontant] = useState("");
  const [motif, setMotif] = useState("");
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    if (row) {
      setMontant(String(row.montant));
      setMotif("");
      setErr(null);
    }
  }, [row]);
  if (!row) return null;
  const MOTIFS = [
    "Parti sans préavis suffisant",
    "Dommages au logement",
    "Loyers impayés",
    "Nettoyage / remise en état"
  ];
  return (
    <div
      className="fixed inset-0 z-[70] flex items-center justify-center bg-black/70 p-4 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="w-full max-w-sm rounded-2xl border border-brand-800 bg-brand-950 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="border-b border-brand-800 px-5 py-3">
          <h2 className="text-sm font-bold uppercase tracking-wider text-amber-300">
            Garder le dépôt
          </h2>
          <p className="mt-0.5 text-xs text-white/60">
            {row.locataire_name || "Locataire"} · {row.immeuble_name}
            {row.logement_numero ? ` · Log. ${row.logement_numero}` : ""} ·
            dépôt {money(row.montant)}
          </p>
        </div>
        <div className="grid gap-3 p-5">
          <label className="text-[11px] font-semibold text-white/60">
            Montant gardé ($) — le reste sera « à rendre »
            <input
              inputMode="decimal"
              value={montant}
              onChange={(e) => setMontant(e.target.value)}
              className="input mt-0.5 block w-full"
            />
          </label>
          <div>
            <span className="text-[11px] font-semibold text-white/60">Motif</span>
            <div className="mt-1 flex flex-wrap gap-1.5">
              {MOTIFS.map((m) => (
                <button
                  key={m}
                  type="button"
                  onClick={() => setMotif(m)}
                  className={`rounded-full border px-2.5 py-1 text-[11px] ${
                    motif === m
                      ? "border-amber-500/60 bg-amber-500/20 text-amber-200"
                      : "border-brand-800 text-white/60 hover:text-white"
                  }`}
                >
                  {m}
                </button>
              ))}
            </div>
            <input
              value={motif}
              onChange={(e) => setMotif(e.target.value)}
              placeholder="ou précise…"
              className="input mt-1.5 block w-full"
            />
          </div>
          {err ? (
            <p className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">
              {err}
            </p>
          ) : null}
          <div className="flex justify-end gap-2 border-t border-brand-800 pt-3">
            <button type="button" onClick={onClose} className="btn-secondary btn-sm">
              Annuler
            </button>
            <button
              type="button"
              onClick={() => {
                const v = Number(montant.replace(/\s/g, "").replace(",", "."));
                if (!Number.isFinite(v) || v <= 0 || v > row.montant + 0.005) {
                  setErr(`Montant entre 0 et ${money(row.montant)}.`);
                  return;
                }
                void onConfirm(Math.round(v * 100) / 100, motif.trim());
              }}
              className="btn-accent btn-sm"
            >
              Garder
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
