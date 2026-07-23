"use client";

import { useCallback, useEffect, useState } from "react";
import {
  Building2,
  Check,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  FileText,
  Loader2,
  Settings,
  Trash2
} from "lucide-react";

import { authedFetch } from "@/lib/auth";
import { ImmobilierTopbar } from "../layout";

/**
 * Frais de gestion mensuels (retours Phil 2026-07-22) :
 * 1. Sous-section RÉGLAGES (repliable) : choisir quels immeubles sont
 *    sous contrat de gestion (+ % et client QuickBooks du proprio),
 *    modifiable en tout temps.
 * 2. DASHBOARD : toutes les compagnies/immeubles qu'on facture.
 * 3. FACTURATION DU MOIS : début août, on voit ce qui reste à facturer
 *    pour la gestion de juillet — bouton « Créer la facture » (QBO),
 *    checklist facturé / à faire, navigable mois par mois.
 */

type FactureInfo = {
  id: number;
  revenus: number;
  pct: number;
  montant: number;
  qbo_doc_number?: string | null;
  created_at?: string | null;
};

type Row = {
  immeuble_id: number;
  name: string;
  address?: string | null;
  frais_gestion_actif: boolean;
  frais_gestion_pct: number;
  qbo_customer_id?: string | null;
  qbo_customer_name?: string | null;
  revenus: number;
  montant_estime: number;
  facture?: FactureInfo | null;
  derniere_facture_mois?: string | null;
  frais_gestion_depuis?: string | null;
  solde?: number;
  mois_manques?: { mois: string; label: string }[];
};

type Overview = {
  mois: string;
  mois_label: string;
  rows: Row[];
  nb_factures: number;
  nb_a_facturer: number;
};

type QboOptions = {
  connected: boolean;
  customers: { id: string; name: string }[];
};

function money(n: number | null | undefined): string {
  return new Intl.NumberFormat("fr-CA", {
    style: "currency",
    currency: "CAD"
  }).format(n || 0);
}

function moisPrecedentISO(): string {
  const d = new Date();
  const p = new Date(d.getFullYear(), d.getMonth() - 1, 1);
  return `${p.getFullYear()}-${String(p.getMonth() + 1).padStart(2, "0")}-01`;
}

function addMonths(iso: string, n: number): string {
  const [y, m] = iso.split("-").map((x) => parseInt(x, 10));
  const d = new Date(y, m - 1 + n, 1);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-01`;
}

export default function FraisGestionPage() {
  const [mois, setMois] = useState<string | null>(null);
  const [data, setData] = useState<Overview | null>(null);
  const [loading, setLoading] = useState(true);
  const [qboOpts, setQboOpts] = useState<QboOptions | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [showConfig, setShowConfig] = useState(false);

  const load = useCallback(
    async (m?: string | null) => {
      setLoading(true);
      try {
        const params = new URLSearchParams();
        const target = m ?? mois;
        if (target) params.set("mois", target);
        const r = await authedFetch(
          `/api/v1/immobilier/frais-gestion?${params.toString()}`
        );
        if (r.ok) {
          const d: Overview = await r.json();
          setData(d);
          setMois(d.mois);
        }
      } finally {
        setLoading(false);
      }
    },
    [mois]
  );

  useEffect(() => {
    void load(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    void (async () => {
      try {
        const r = await authedFetch("/api/v1/timesheets/qbo-options");
        if (r.ok) setQboOpts(await r.json());
      } catch {
        /* noop */
      }
    })();
  }, []);

  const patchImmeuble = async (
    id: number,
    patch: Record<string, unknown>
  ) => {
    await authedFetch(`/api/v1/immobilier/frais-gestion/immeubles/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch)
    });
    setData((prev) =>
      prev
        ? {
            ...prev,
            rows: prev.rows.map((row) =>
              row.immeuble_id === id ? { ...row, ...patch } : row
            )
          }
        : prev
    );
  };

  const doFacturer = async (row: Row) => {
    if (!data) return;
    if (
      !window.confirm(
        `Créer la facture QuickBooks des frais de gestion de « ${row.name} » ?\n\n${row.frais_gestion_pct} % des revenus de ${data.mois_label} (${money(row.revenus)}) = ${money(row.montant_estime)} + taxes.`
      )
    )
      return;
    setBusyId(row.immeuble_id);
    setMsg(null);
    try {
      const r = await authedFetch("/api/v1/immobilier/frais-gestion/facturer", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ immeuble_id: row.immeuble_id, mois: data.mois })
      });
      const d = await r.json().catch(() => null);
      if (!r.ok) {
        throw new Error((d && (d.detail || d.message)) || `Erreur ${r.status}`);
      }
      setMsg({
        ok: true,
        text: `Facture QuickBooks ${d.doc_number ? `#${d.doc_number}` : ""} créée pour ${row.name} : ${money(d.montant)} (${d.pct} % de ${money(d.revenus)}).`
      });
      await load();
    } catch (e: any) {
      setMsg({ ok: false, text: e?.message || "Facturation impossible" });
    } finally {
      setBusyId(null);
    }
  };

  const annulerFacture = async (row: Row) => {
    if (!row.facture) return;
    if (
      !window.confirm(
        `Décocher ${row.name} pour ce mois ? (À faire si la facture a été supprimée dans QuickBooks — la ligne redevient « à facturer ».)`
      )
    )
      return;
    await authedFetch(
      `/api/v1/immobilier/frais-gestion/factures/${row.facture.id}`,
      { method: "DELETE" }
    );
    await load();
  };

  const sousContrat = data?.rows.filter((r) => r.frais_gestion_actif) || [];
  const totalAFacturer = sousContrat
    .filter((r) => !r.facture)
    .reduce((a, r) => a + r.montant_estime, 0);
  const totalFacture = sousContrat
    .filter((r) => r.facture)
    .reduce((a, r) => a + (r.facture?.montant || 0), 0);

  return (
    <>
      <ImmobilierTopbar
        breadcrumbs={[
          { label: "Gestion immobilière", href: "/immobilier" },
          { label: "Frais de gestion" }
        ]}
      />

      <div className="space-y-5 p-4 lg:p-6">
        <div>
          <h1 className="text-2xl font-bold text-white">Frais de gestion</h1>
          <p className="mt-1 max-w-2xl text-sm text-white/60">
            Chaque début de mois, facture les frais de gestion du mois
            précédent (% des revenus locatifs) aux propriétaires sous
            contrat.
          </p>
        </div>

        {msg && (
          <div
            className={`rounded-xl border px-4 py-3 text-sm ${
              msg.ok
                ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-300"
                : "border-rose-500/30 bg-rose-500/10 text-rose-300"
            }`}
          >
            {msg.text}
          </div>
        )}

        {/* ── 1. RÉGLAGES (repliable) : qui est sous contrat ── */}
        <section className="rounded-2xl border border-brand-800 bg-brand-900 p-5">
          <button
            className="flex w-full items-center justify-between gap-2 text-left"
            onClick={() => setShowConfig((v) => !v)}
          >
            <span className="flex items-center gap-2 text-sm font-medium text-white">
              <Settings className="h-4 w-4" />
              Réglages — immeubles sous contrat de gestion
            </span>
            <span className="flex items-center gap-2">
              <span className="badge badge-neutral">
                {sousContrat.length} sous contrat
              </span>
              <ChevronDown
                className={`h-4 w-4 text-white/40 transition ${showConfig ? "rotate-180" : ""}`}
              />
            </span>
          </button>

          {showConfig && data && (
            <div className="mt-4 overflow-x-auto">
              <p className="mb-2 text-xs text-white/50">
                Coche les immeubles à facturer chaque mois, ajuste le %
                et choisis le client QuickBooks (le propriétaire).
                Enregistré dès que tu changes — modifiable en tout temps.
              </p>
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-brand-800 text-left text-xs uppercase tracking-wide text-white/50">
                    <th className="px-3 py-2">Immeuble</th>
                    <th className="px-3 py-2 text-center">Contrat</th>
                    <th className="px-3 py-2 text-right">%</th>
                    <th
                      className="px-3 py-2"
                      title="Les mois de revenus AVANT cette date ne comptent pas dans le solde à facturer"
                    >
                      Facturer depuis
                    </th>
                    <th className="px-3 py-2">Client QBO (propriétaire)</th>
                  </tr>
                </thead>
                <tbody>
                  {data.rows.map((row) => (
                    <tr
                      key={row.immeuble_id}
                      className={`border-b border-brand-800/60 ${
                        row.frais_gestion_actif ? "" : "opacity-60"
                      }`}
                    >
                      <td className="px-3 py-2.5">
                        <div className="font-medium text-white">
                          {row.name}
                        </div>
                        {row.address && (
                          <div className="text-xs text-white/40">
                            {row.address}
                          </div>
                        )}
                      </td>
                      <td className="px-3 py-2.5 text-center">
                        <input
                          type="checkbox"
                          checked={row.frais_gestion_actif}
                          onChange={(e) => {
                            const patch: Record<string, unknown> = {
                              frais_gestion_actif: e.target.checked
                            };
                            // Activer un contrat sans date → on part du
                            // mois précédent (pas de faux arriéré).
                            if (
                              e.target.checked &&
                              !row.frais_gestion_depuis
                            ) {
                              patch.frais_gestion_depuis =
                                moisPrecedentISO();
                            }
                            void patchImmeuble(row.immeuble_id, patch);
                          }}
                          title="Contrat de gestion actif — on facture des frais mensuels sur cet immeuble"
                          className="h-4 w-4 accent-accent-500"
                        />
                      </td>
                      <td className="px-3 py-2.5 text-right">
                        <input
                          inputMode="decimal"
                          defaultValue={String(row.frais_gestion_pct)}
                          onBlur={(e) => {
                            const v = parseFloat(
                              e.target.value.replace(",", ".")
                            );
                            if (!isNaN(v) && v >= 0 && v <= 100) {
                              void patchImmeuble(row.immeuble_id, {
                                frais_gestion_pct: v
                              });
                            }
                          }}
                          disabled={!row.frais_gestion_actif}
                          className="w-16 rounded border border-brand-800 bg-brand-950 px-2 py-1 text-right text-white outline-none focus:border-accent-500 disabled:opacity-40"
                        />
                      </td>
                      <td className="px-3 py-2.5">
                        <input
                          type="month"
                          value={(row.frais_gestion_depuis || "").slice(0, 7)}
                          disabled={!row.frais_gestion_actif}
                          onChange={(e) => {
                            if (e.target.value) {
                              void patchImmeuble(row.immeuble_id, {
                                frais_gestion_depuis:
                                  e.target.value + "-01"
                              });
                            }
                          }}
                          title="Recule cette date pour rattraper des mois passés dans le solde"
                          className="rounded border border-brand-800 bg-brand-950 px-2 py-1 text-white outline-none focus:border-accent-500 disabled:opacity-40"
                        />
                      </td>
                      <td className="px-3 py-2.5">
                        {qboOpts?.connected ? (
                          <select
                            value={row.qbo_customer_id || ""}
                            disabled={!row.frais_gestion_actif}
                            onChange={(e) => {
                              const id = e.target.value;
                              const name = id
                                ? qboOpts.customers.find((c) => c.id === id)
                                    ?.name || ""
                                : "";
                              void patchImmeuble(row.immeuble_id, {
                                qbo_customer_id: id,
                                qbo_customer_name: name
                              });
                            }}
                            className="max-w-[240px] rounded border border-brand-800 bg-brand-950 px-2 py-1 text-white outline-none focus:border-accent-500 disabled:opacity-40"
                          >
                            <option value="">— choisir —</option>
                            {qboOpts.customers.map((c) => (
                              <option key={c.id} value={c.id}>
                                {c.name}
                              </option>
                            ))}
                          </select>
                        ) : (
                          <span className="text-xs text-white/40">
                            QuickBooks non connecté
                          </span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>

        {loading && !data ? (
          <div className="flex items-center justify-center py-16 text-white/50">
            <Loader2 className="mr-2 h-5 w-5 animate-spin" /> Chargement…
          </div>
        ) : data ? (
          <>
            {/* ── 2. DASHBOARD : les compagnies qu'on facture ── */}
            {sousContrat.length === 0 ? (
              <div className="rounded-2xl border border-brand-800 bg-brand-900 p-8 text-center text-sm text-white/50">
                Aucun immeuble sous contrat — ouvre les Réglages ci-dessus
                et coche ceux qu&apos;on facture.
              </div>
            ) : (
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                {sousContrat.map((row) => (
                  <div
                    key={row.immeuble_id}
                    className="rounded-2xl border border-brand-800 bg-brand-900 p-4"
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0">
                        <div className="flex items-center gap-2">
                          <Building2 className="h-4 w-4 shrink-0 text-accent-500" />
                          <span className="truncate font-medium text-white">
                            {row.name}
                          </span>
                        </div>
                        {row.address && (
                          <div className="mt-0.5 truncate text-xs text-white/40">
                            {row.address}
                          </div>
                        )}
                      </div>
                      <span className="badge badge-neutral shrink-0">
                        {row.frais_gestion_pct} %
                      </span>
                    </div>
                    <dl className="mt-3 space-y-1 text-xs">
                      <div className="flex justify-between gap-2">
                        <dt className="text-white/40">Client QBO</dt>
                        <dd
                          className={`truncate ${row.qbo_customer_name ? "text-white/80" : "text-amber-300"}`}
                        >
                          {row.qbo_customer_name || "à choisir"}
                        </dd>
                      </div>
                      <div className="flex justify-between gap-2">
                        <dt className="text-white/40">Dernier mois facturé</dt>
                        <dd className="text-white/80">
                          {row.derniere_facture_mois || "jamais"}
                        </dd>
                      </div>
                      <div className="flex justify-between gap-2">
                        <dt className="text-white/40">Solde à facturer</dt>
                        <dd
                          className={
                            (row.solde || 0) > 0
                              ? "font-semibold text-amber-300"
                              : "text-white/80"
                          }
                        >
                          {money(row.solde || 0)}
                        </dd>
                      </div>
                    </dl>
                    {(row.mois_manques?.length || 0) > 0 && (
                      <div className="mt-2 flex flex-wrap gap-1">
                        {row.mois_manques!.map((mm) => (
                          <button
                            key={mm.mois}
                            className="rounded-full border border-amber-500/40 bg-amber-500/10 px-2 py-0.5 text-[11px] text-amber-300 transition hover:bg-amber-500/20"
                            title="Mois avec revenus jamais facturé — clique pour aller le facturer"
                            onClick={() => void load(mm.mois)}
                          >
                            {mm.label}
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}

            {/* ── 3. FACTURATION DU MOIS ── */}
            <section className="rounded-2xl border border-brand-800 bg-brand-900 p-5">
              <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
                <div>
                  <h2 className="text-base font-bold text-white">
                    Facturation — gestion de {data.mois_label}
                  </h2>
                  <p className="mt-0.5 text-xs text-white/50">
                    {data.nb_factures} facturé
                    {data.nb_factures > 1 ? "s" : ""} (
                    {money(totalFacture)}) · {data.nb_a_facturer} à
                    facturer ({money(totalAFacturer)})
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <button
                    className="btn-secondary btn-sm"
                    onClick={() => mois && void load(addMonths(mois, -1))}
                    aria-label="Mois précédent"
                  >
                    <ChevronLeft className="h-4 w-4" />
                  </button>
                  <div className="min-w-[160px] rounded-lg border border-brand-800 bg-brand-950 px-4 py-2 text-center text-sm font-medium text-white">
                    {data.mois_label}
                  </div>
                  <button
                    className="btn-secondary btn-sm"
                    onClick={() => mois && void load(addMonths(mois, 1))}
                    aria-label="Mois suivant"
                  >
                    <ChevronRight className="h-4 w-4" />
                  </button>
                </div>
              </div>

              {sousContrat.length === 0 ? (
                <p className="py-4 text-sm text-white/50">
                  Rien à facturer — aucun immeuble sous contrat.
                </p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-brand-800 text-left text-xs uppercase tracking-wide text-white/50">
                        <th className="px-3 py-2">Immeuble</th>
                        <th className="px-3 py-2 text-right">
                          Revenus {data.mois_label}
                        </th>
                        <th className="px-3 py-2 text-right">%</th>
                        <th className="px-3 py-2 text-right">Frais</th>
                        <th className="px-3 py-2 text-right">Statut</th>
                      </tr>
                    </thead>
                    <tbody>
                      {sousContrat.map((row) => (
                        <tr
                          key={row.immeuble_id}
                          className="border-b border-brand-800/60"
                        >
                          <td className="px-3 py-3">
                            <div className="font-medium text-white">
                              {row.name}
                            </div>
                            {!row.qbo_customer_id && !row.facture && (
                              <div className="text-xs text-amber-300">
                                Client QBO à choisir dans les Réglages
                              </div>
                            )}
                          </td>
                          <td className="px-3 py-3 text-right tabular-nums text-white/80">
                            {money(row.revenus)}
                          </td>
                          <td className="px-3 py-3 text-right tabular-nums text-white/60">
                            {row.facture
                              ? row.facture.pct
                              : row.frais_gestion_pct}{" "}
                            %
                          </td>
                          <td className="px-3 py-3 text-right font-medium tabular-nums text-white">
                            {row.facture
                              ? money(row.facture.montant)
                              : money(row.montant_estime)}
                          </td>
                          <td className="px-3 py-3 text-right">
                            {row.facture ? (
                              <span className="inline-flex items-center gap-1.5">
                                <span
                                  className="badge badge-emerald"
                                  title={
                                    row.facture.created_at
                                      ? `Facturé le ${new Date(row.facture.created_at).toLocaleDateString("fr-CA")}`
                                      : undefined
                                  }
                                >
                                  <Check className="mr-1 h-3 w-3" />
                                  Facturé
                                  {row.facture.qbo_doc_number
                                    ? ` #${row.facture.qbo_doc_number}`
                                    : ""}
                                </span>
                                <button
                                  className="btn-outline-rose btn-xs"
                                  title="Décocher ce mois (facture supprimée dans QuickBooks)"
                                  onClick={() => void annulerFacture(row)}
                                >
                                  <Trash2 className="h-3.5 w-3.5" />
                                </button>
                              </span>
                            ) : (
                              <button
                                className="btn-accent btn-xs whitespace-nowrap"
                                disabled={busyId === row.immeuble_id}
                                title={`Crée la facture QuickBooks : ${row.frais_gestion_pct} % des revenus de ${data.mois_label} + taxes`}
                                onClick={() => void doFacturer(row)}
                              >
                                {busyId === row.immeuble_id ? (
                                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                                ) : (
                                  <FileText className="h-3.5 w-3.5" />
                                )}
                                Créer la facture
                              </button>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </section>
          </>
        ) : null}
      </div>
    </>
  );
}
