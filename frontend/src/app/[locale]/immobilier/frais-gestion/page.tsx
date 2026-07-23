"use client";

import { useCallback, useEffect, useState } from "react";
import {
  Check,
  ChevronLeft,
  ChevronRight,
  FileText,
  Loader2,
  Trash2
} from "lucide-react";

import { authedFetch } from "@/lib/auth";
import { ImmobilierTopbar } from "../layout";

/**
 * Frais de gestion mensuels (retour Phil 2026-07-22) : pour chaque
 * immeuble sous CONTRAT de gestion (case cochée, % modifiable), on
 * facture chaque mois X % des revenus locatifs du mois précédent au
 * propriétaire (client QuickBooks associé). Checklist par mois :
 * facturé / à faire.
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

  return (
    <>
      <ImmobilierTopbar
        breadcrumbs={[
          { label: "Gestion immobilière", href: "/immobilier" },
          { label: "Frais de gestion" }
        ]}
      />

      <div className="space-y-5 p-4 lg:p-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="text-2xl font-bold text-white">Frais de gestion</h1>
            <p className="mt-1 max-w-2xl text-sm text-white/60">
              Coche les immeubles sous contrat de gestion, ajuste le %,
              puis facture chaque mois les frais (% des revenus locatifs
              du mois affiché) dans QuickBooks. La liste sert de
              checklist : facturé ✓ / à faire.
            </p>
          </div>

          {/* Navigation mois */}
          <div className="flex items-center gap-2">
            <button
              className="btn-secondary btn-sm"
              onClick={() => mois && void load(addMonths(mois, -1))}
              aria-label="Mois précédent"
            >
              <ChevronLeft className="h-4 w-4" />
            </button>
            <div className="min-w-[170px] rounded-lg border border-brand-800 bg-brand-900 px-4 py-2 text-center text-sm font-medium text-white">
              {data?.mois_label || "…"}
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

        {data && (
          <div className="flex flex-wrap gap-3 text-sm">
            <span className="badge badge-emerald">
              {data.nb_factures} facturé{data.nb_factures > 1 ? "s" : ""}
            </span>
            <span
              className={`badge ${data.nb_a_facturer > 0 ? "badge-amber" : "badge-neutral"}`}
            >
              {data.nb_a_facturer} à facturer
            </span>
          </div>
        )}

        {loading ? (
          <div className="flex items-center justify-center py-16 text-white/50">
            <Loader2 className="mr-2 h-5 w-5 animate-spin" /> Chargement…
          </div>
        ) : data ? (
          <div className="overflow-x-auto rounded-2xl border border-brand-800 bg-brand-900">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-brand-800 text-left text-xs uppercase tracking-wide text-white/50">
                  <th className="px-4 py-3">Immeuble</th>
                  <th className="px-3 py-3 text-center">Contrat</th>
                  <th className="px-3 py-3 text-right">%</th>
                  <th className="px-3 py-3">Client QBO (propriétaire)</th>
                  <th className="px-3 py-3 text-right">
                    Revenus {data.mois_label}
                  </th>
                  <th className="px-3 py-3 text-right">Frais</th>
                  <th className="px-3 py-3 text-right">Statut</th>
                </tr>
              </thead>
              <tbody>
                {data.rows.map((row) => (
                  <tr
                    key={row.immeuble_id}
                    className={`border-b border-brand-800/60 ${
                      row.frais_gestion_actif ? "" : "opacity-50"
                    }`}
                  >
                    <td className="px-4 py-3">
                      <div className="font-medium text-white">{row.name}</div>
                      {row.address && (
                        <div className="text-xs text-white/40">
                          {row.address}
                        </div>
                      )}
                    </td>
                    <td className="px-3 py-3 text-center">
                      <input
                        type="checkbox"
                        checked={row.frais_gestion_actif}
                        onChange={(e) =>
                          void patchImmeuble(row.immeuble_id, {
                            frais_gestion_actif: e.target.checked
                          })
                        }
                        title="Contrat de gestion actif — on facture des frais mensuels sur cet immeuble"
                        className="h-4 w-4 accent-accent-500"
                      />
                    </td>
                    <td className="px-3 py-3 text-right">
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
                    <td className="px-3 py-3">
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
                          className="max-w-[220px] rounded border border-brand-800 bg-brand-950 px-2 py-1 text-white outline-none focus:border-accent-500 disabled:opacity-40"
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
                    <td className="px-3 py-3 text-right tabular-nums text-white/80">
                      {money(row.revenus)}
                    </td>
                    <td className="px-3 py-3 text-right font-medium tabular-nums text-white">
                      {row.facture
                        ? money(row.facture.montant)
                        : money(row.montant_estime)}
                    </td>
                    <td className="px-3 py-3 text-right">
                      {!row.frais_gestion_actif ? (
                        <span className="text-xs text-white/40">
                          sans contrat
                        </span>
                      ) : row.facture ? (
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
                {data.rows.length === 0 && (
                  <tr>
                    <td
                      colSpan={7}
                      className="px-4 py-10 text-center text-white/40"
                    >
                      Aucun immeuble actif.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        ) : null}
      </div>
    </>
  );
}
