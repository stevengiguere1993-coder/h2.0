"use client";

import { useCallback, useEffect, useState } from "react";
import {
  Check,
  CheckCircle2,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  ChevronUp,
  CircleDollarSign,
  Loader2,
  Plus,
  Trash2,
  TrendingUp
} from "lucide-react";

import { authedFetch } from "@/lib/auth";
import { ImmobilierTopbar, useImmobilierLayout } from "../layout";

/**
 * Finances — P&L annuel par immeuble + saisie des dépenses.
 *
 * Pour chaque immeuble : loyers annualisés (baux actifs × 12), revenus
 * réellement reçus (paiements), dépenses (ponctuelles datées + courantes
 * annualisées), service de dette (hypothèques actives × 12) et les deux
 * cashflows (potentiel / réel). Clic sur un immeuble → ses dépenses,
 * ajout/suppression inline.
 */

type PnlRow = {
  immeuble_id: number;
  immeuble_name: string;
  loyers_annualises: number;
  revenus_recus: number;
  depenses: number;
  dette_annuelle: number;
  cashflow_potentiel: number;
  cashflow_reel: number;
  nb_baux_actifs: number;
};

type Pnl = { annee: number; rows: PnlRow[]; totaux: PnlRow };

type PrevMois = {
  mois: string;
  revenus: number;
  depenses_courantes: number;
  hypotheque: number;
  maintenance: number;
  cashflow_net: number;
  cashflow_cumule: number;
};
type Previsionnel = {
  rows: PrevMois[];
  revenus_mensuels: number;
  depenses_mensuelles: number;
  hypotheque_mensuelle: number;
  cashflow_mensuel_base: number;
  total_maintenance_planifiee: number;
  cashflow_horizon: number;
};

function moisLabel(ym: string): string {
  const [y, m] = ym.split("-").map(Number);
  const dt = new Date(y, (m || 1) - 1, 1);
  return dt.toLocaleDateString("fr-CA", { month: "short", year: "2-digit" });
}

type Depense = {
  id: number;
  immeuble_id: number;
  categorie: string;
  libelle: string;
  montant: number;
  frequence: string;
  date_depense: string | null;
  notes: string | null;
};

const CATEGORIES = [
  ["taxes_municipales", "Taxes municipales"],
  ["taxes_scolaires", "Taxes scolaires"],
  ["assurances", "Assurances"],
  ["energie", "Énergie"],
  ["entretien", "Entretien"],
  ["deneigement", "Déneigement"],
  ["conciergerie", "Conciergerie"],
  ["gestion", "Gestion"],
  ["autre", "Autre"]
] as const;

const CAT_LABEL: Record<string, string> = Object.fromEntries(CATEGORIES);

function fmtMoney(n: number): string {
  const v = Math.round(n);
  return `${v.toLocaleString("fr-CA")} $`;
}

export default function FinancesPage() {
  const { currentEntrepriseId } = useImmobilierLayout();
  const [annee, setAnnee] = useState(new Date().getFullYear());
  const [data, setData] = useState<Pnl | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [openId, setOpenId] = useState<number | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [prev, setPrev] = useState<Previsionnel | null>(null);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      const params = new URLSearchParams({ mois: "12" });
      if (currentEntrepriseId != null) {
        params.set("entreprise_id", String(currentEntrepriseId));
      }
      const r = await authedFetch(
        `/api/v1/immobilier/finances/previsionnel?${params.toString()}`
      );
      if (r.ok && !cancelled) setPrev((await r.json()) as Previsionnel);
    })();
    return () => {
      cancelled = true;
    };
  }, [currentEntrepriseId]);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams({ annee: String(annee) });
      if (currentEntrepriseId != null) {
        params.set("entreprise_id", String(currentEntrepriseId));
      }
      const r = await authedFetch(
        `/api/v1/immobilier/finances/pnl?${params.toString()}`
      );
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      setData((await r.json()) as Pnl);
    } catch (e) {
      setError(`Chargement échoué : ${(e as Error).message}`);
    } finally {
      setLoading(false);
    }
  }, [annee, currentEntrepriseId]);

  useEffect(() => {
    void load();
  }, [load]);

  function flash(msg: string) {
    setToast(msg);
    window.setTimeout(() => setToast(null), 2500);
  }

  return (
    <>
      <ImmobilierTopbar
        breadcrumbs={[
          { label: "Gestion immobilière", href: "/immobilier" },
          { label: "Finances" }
        ]}
      />
      <div className="p-4 lg:p-6">
        <header className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-start gap-3">
            <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-emerald-500/15 text-emerald-300">
              <CircleDollarSign className="h-5 w-5" />
            </span>
            <div>
              <h1 className="text-2xl font-bold text-white">Finances</h1>
              <p className="mt-1 max-w-2xl text-sm text-white/60">
                Profits &amp; pertes par immeuble : loyers, dépenses
                d&apos;exploitation, service de dette → cashflow réel.
              </p>
            </div>
          </div>
          <div className="inline-flex items-center gap-1 rounded-lg border border-brand-800 bg-brand-900 px-1 py-1">
            <button
              type="button"
              onClick={() => setAnnee((a) => a - 1)}
              className="btn-ghost btn-xs"
              aria-label="Année précédente"
            >
              <ChevronLeft className="h-4 w-4" />
            </button>
            <span className="min-w-[70px] text-center text-sm font-semibold text-white">
              {annee}
            </span>
            <button
              type="button"
              onClick={() => setAnnee((a) => a + 1)}
              className="btn-ghost btn-xs"
              aria-label="Année suivante"
            >
              <ChevronRight className="h-4 w-4" />
            </button>
          </div>
        </header>

        {error ? (
          <p className="mt-4 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-300">
            {error}
          </p>
        ) : null}

        {data ? (
          <div className="mt-5 grid grid-cols-2 gap-3 lg:grid-cols-4">
            <Tile
              label="Loyers annualisés"
              value={fmtMoney(data.totaux.loyers_annualises)}
              sub={`${data.totaux.nb_baux_actifs} baux actifs`}
            />
            <Tile
              label="Dépenses / an"
              value={fmtMoney(data.totaux.depenses)}
            />
            <Tile
              label="Dette / an"
              value={fmtMoney(data.totaux.dette_annuelle)}
            />
            <Tile
              label="Cashflow potentiel"
              value={fmtMoney(data.totaux.cashflow_potentiel)}
              tone={
                data.totaux.cashflow_potentiel >= 0 ? "emerald" : "rose"
              }
            />
          </div>
        ) : null}

        {prev && prev.rows.length > 0 ? (
          <section className="mt-6">
            <h2 className="mb-2 flex items-center gap-2 text-sm font-semibold text-white">
              <TrendingUp className="h-4 w-4 text-emerald-400" />
              Prévisionnel — 12 prochains mois
            </h2>
            <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
              <Tile
                label="Revenus / mois"
                value={fmtMoney(prev.revenus_mensuels)}
              />
              <Tile
                label="Charges / mois"
                value={fmtMoney(
                  prev.depenses_mensuelles + prev.hypotheque_mensuelle
                )}
                sub={`dont ${fmtMoney(prev.hypotheque_mensuelle)} hypothèque`}
              />
              <Tile
                label="Cashflow / mois (base)"
                value={fmtMoney(prev.cashflow_mensuel_base)}
                tone={prev.cashflow_mensuel_base >= 0 ? "emerald" : "rose"}
              />
              <Tile
                label="Cashflow projeté 12 mois"
                value={fmtMoney(prev.cashflow_horizon)}
                tone={prev.cashflow_horizon >= 0 ? "emerald" : "rose"}
                sub={
                  prev.total_maintenance_planifiee > 0
                    ? `dont ${fmtMoney(
                        prev.total_maintenance_planifiee
                      )} maintenance planifiée`
                    : undefined
                }
              />
            </div>
            <div className="mt-3 overflow-x-auto rounded-xl border border-brand-800 bg-brand-900">
              <table className="w-full text-sm">
                <thead className="bg-brand-950/60 text-left text-[11px] uppercase tracking-wider text-white/50">
                  <tr>
                    <th className="px-3 py-2.5">Mois</th>
                    <th className="px-3 py-2.5 text-right">Revenus</th>
                    <th className="px-3 py-2.5 text-right">Dépenses</th>
                    <th className="px-3 py-2.5 text-right">Hypothèque</th>
                    <th className="px-3 py-2.5 text-right">Maintenance</th>
                    <th className="px-3 py-2.5 text-right">Cashflow</th>
                    <th className="px-3 py-2.5 text-right">Cumulé</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-brand-800">
                  {prev.rows.map((m) => (
                    <tr key={m.mois} className="hover:bg-brand-950/40">
                      <td className="px-3 py-2 capitalize text-white/80">
                        {moisLabel(m.mois)}
                      </td>
                      <td className="px-3 py-2 text-right tabular-nums text-white/70">
                        {fmtMoney(m.revenus)}
                      </td>
                      <td className="px-3 py-2 text-right tabular-nums text-white/50">
                        {fmtMoney(m.depenses_courantes)}
                      </td>
                      <td className="px-3 py-2 text-right tabular-nums text-white/50">
                        {fmtMoney(m.hypotheque)}
                      </td>
                      <td className="px-3 py-2 text-right tabular-nums text-white/50">
                        {m.maintenance > 0 ? fmtMoney(m.maintenance) : "—"}
                      </td>
                      <td
                        className={`px-3 py-2 text-right font-semibold tabular-nums ${
                          m.cashflow_net >= 0
                            ? "text-emerald-300"
                            : "text-rose-300"
                        }`}
                      >
                        {fmtMoney(m.cashflow_net)}
                      </td>
                      <td
                        className={`px-3 py-2 text-right tabular-nums ${
                          m.cashflow_cumule >= 0
                            ? "text-emerald-300/80"
                            : "text-rose-300/80"
                        }`}
                      >
                        {fmtMoney(m.cashflow_cumule)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="mt-2 text-[11px] text-white/35">
              Projection à partir des baux actifs, dépenses récurrentes,
              hypothèques et maintenance planifiée. Suppose les loyers maintenus
              (renouvellement).
            </p>
          </section>
        ) : null}

        <h2 className="mt-6 mb-2 text-sm font-semibold text-white">
          Profits &amp; pertes {annee}
        </h2>
        <div className="mt-1 overflow-hidden rounded-xl border border-brand-800 bg-brand-900">
          {loading ? (
            <div className="flex items-center justify-center py-12">
              <Loader2 className="h-6 w-6 animate-spin text-emerald-400" />
            </div>
          ) : !data || data.rows.length === 0 ? (
            <div className="p-10 text-center text-sm text-white/50">
              Aucun immeuble actif
              {currentEntrepriseId != null ? " pour cette entreprise" : ""}.
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="bg-brand-950/60 text-left text-[11px] uppercase tracking-wider text-white/50">
                  <tr>
                    <th className="px-3 py-2.5">Immeuble</th>
                    <th className="px-3 py-2.5 text-right">Loyers/an</th>
                    <th className="px-3 py-2.5 text-right">Reçus {annee}</th>
                    <th className="px-3 py-2.5 text-right">Dépenses</th>
                    <th className="px-3 py-2.5 text-right">Dette</th>
                    <th className="px-3 py-2.5 text-right">
                      Cashflow potentiel
                    </th>
                    <th className="px-3 py-2.5"></th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-brand-800">
                  {data.rows.map((r) => (
                    <ImmeubleRow
                      key={r.immeuble_id}
                      row={r}
                      open={openId === r.immeuble_id}
                      onToggle={() =>
                        setOpenId((cur) =>
                          cur === r.immeuble_id ? null : r.immeuble_id
                        )
                      }
                      onChanged={() => {
                        void load();
                      }}
                      flash={flash}
                    />
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        <p className="mt-3 text-[11px] text-white/40">
          Dépenses « mensuelles » comptées × 12, « annuelles » × 1,
          « ponctuelles » dans leur année. Cashflow potentiel = loyers
          annualisés − dépenses − dette ; le réel utilise les paiements
          reçus de l&apos;année.
        </p>
      </div>

      {toast ? (
        <div className="pointer-events-none fixed inset-x-0 bottom-4 z-[1100] flex justify-center px-3">
          <div className="pointer-events-auto flex items-center gap-2 rounded-xl border border-emerald-500/40 bg-emerald-500/15 px-3 py-2 text-sm text-emerald-100 shadow-lg">
            <CheckCircle2 className="h-4 w-4" />
            {toast}
          </div>
        </div>
      ) : null}
    </>
  );
}

function Tile({
  label,
  value,
  sub,
  tone
}: {
  label: string;
  value: string;
  sub?: string;
  tone?: "emerald" | "rose";
}) {
  return (
    <div className="rounded-xl border border-brand-800 bg-brand-900 px-4 py-3">
      <p className="text-[11px] uppercase tracking-wider text-white/50">
        {label}
      </p>
      <p
        className={`mt-1 text-xl font-bold tabular-nums ${
          tone === "emerald"
            ? "text-emerald-300"
            : tone === "rose"
              ? "text-rose-300"
              : "text-white"
        }`}
      >
        {value}
      </p>
      {sub ? <p className="mt-0.5 text-[10px] text-white/40">{sub}</p> : null}
    </div>
  );
}

function ImmeubleRow({
  row,
  open,
  onToggle,
  onChanged,
  flash
}: {
  row: PnlRow;
  open: boolean;
  onToggle: () => void;
  onChanged: () => void;
  flash: (m: string) => void;
}) {
  return (
    <>
      <tr
        className="cursor-pointer transition hover:bg-brand-800/40"
        onClick={onToggle}
      >
        <td className="px-3 py-2.5 font-medium text-white">
          {row.immeuble_name}
          <span className="ml-2 text-[10px] text-white/40">
            {row.nb_baux_actifs} bail{row.nb_baux_actifs > 1 ? "s" : ""}
          </span>
        </td>
        <td className="px-3 py-2.5 text-right tabular-nums text-white/80">
          {fmtMoney(row.loyers_annualises)}
        </td>
        <td className="px-3 py-2.5 text-right tabular-nums text-white/60">
          {fmtMoney(row.revenus_recus)}
        </td>
        <td className="px-3 py-2.5 text-right tabular-nums text-amber-200/90">
          {fmtMoney(row.depenses)}
        </td>
        <td className="px-3 py-2.5 text-right tabular-nums text-white/60">
          {fmtMoney(row.dette_annuelle)}
        </td>
        <td
          className={`px-3 py-2.5 text-right font-semibold tabular-nums ${
            row.cashflow_potentiel >= 0
              ? "text-emerald-300"
              : "text-rose-300"
          }`}
        >
          {fmtMoney(row.cashflow_potentiel)}
        </td>
        <td className="px-3 py-2.5 text-right text-white/40">
          {open ? (
            <ChevronUp className="ml-auto h-4 w-4" />
          ) : (
            <ChevronDown className="ml-auto h-4 w-4" />
          )}
        </td>
      </tr>
      {open ? (
        <tr>
          <td colSpan={7} className="bg-brand-950/40 px-4 py-3">
            <DepensesPanel
              immeubleId={row.immeuble_id}
              onChanged={onChanged}
              flash={flash}
            />
          </td>
        </tr>
      ) : null}
    </>
  );
}

function DepensesPanel({
  immeubleId,
  onChanged,
  flash
}: {
  immeubleId: number;
  onChanged: () => void;
  flash: (m: string) => void;
}) {
  const [rows, setRows] = useState<Depense[] | null>(null);
  const [adding, setAdding] = useState(false);
  const [fCat, setFCat] = useState("taxes_municipales");
  const [fLib, setFLib] = useState("");
  const [fMontant, setFMontant] = useState("");
  const [fFreq, setFFreq] = useState("annuel");
  const [fDate, setFDate] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const r = await authedFetch(
        `/api/v1/immobilier/immeubles/${immeubleId}/depenses`
      );
      if (r.ok) setRows((await r.json()) as Depense[]);
    } catch {
      /* silencieux */
    }
  }, [immeubleId]);

  useEffect(() => {
    void load();
  }, [load]);

  async function add() {
    if (!fLib.trim() || !fMontant.trim()) return;
    setBusy(true);
    try {
      const r = await authedFetch(
        `/api/v1/immobilier/immeubles/${immeubleId}/depenses`,
        {
          method: "POST",
          body: JSON.stringify({
            categorie: fCat,
            libelle: fLib.trim(),
            montant: Number(fMontant),
            frequence: fFreq,
            date_depense: fFreq === "ponctuel" && fDate ? fDate : null
          })
        }
      );
      if (!r.ok) {
        const t = await r.text();
        throw new Error(t.slice(0, 150) || `HTTP ${r.status}`);
      }
      setFLib("");
      setFMontant("");
      setAdding(false);
      flash("Dépense ajoutée");
      await load();
      onChanged();
    } catch (e) {
      alert((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function remove(d: Depense) {
    if (!window.confirm(`Supprimer « ${d.libelle} » ?`)) return;
    const r = await authedFetch(`/api/v1/immobilier/depenses/${d.id}`, {
      method: "DELETE"
    });
    if (r.ok || r.status === 204) {
      await load();
      onChanged();
    }
  }

  return (
    <div>
      <div className="flex items-center justify-between">
        <p className="section-title">Dépenses d&apos;exploitation</p>
        <button
          type="button"
          onClick={() => setAdding((v) => !v)}
          className="inline-flex items-center gap-1 rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-2 py-1 text-[11px] font-semibold text-emerald-300 hover:bg-emerald-500/20"
        >
          <Plus className="h-3 w-3" /> Ajouter
        </button>
      </div>

      {adding ? (
        <div className="mt-2 flex flex-wrap items-end gap-2 rounded-lg border border-brand-800 bg-brand-900 p-2">
          <label className="text-[11px] text-white/60">
            Catégorie
            <select
              value={fCat}
              onChange={(e) => setFCat(e.target.value)}
              className="mt-0.5 block rounded-md border border-brand-800 bg-brand-950 px-2 py-1.5 text-xs text-white"
            >
              {CATEGORIES.map(([v, l]) => (
                <option key={v} value={v}>
                  {l}
                </option>
              ))}
            </select>
          </label>
          <label className="flex-1 text-[11px] text-white/60">
            Libellé
            <input
              value={fLib}
              onChange={(e) => setFLib(e.target.value)}
              placeholder="Taxes 2026, assurance bâtiment…"
              className="mt-0.5 block w-full rounded-md border border-brand-800 bg-brand-950 px-2 py-1.5 text-xs text-white"
            />
          </label>
          <label className="text-[11px] text-white/60">
            Montant
            <input
              value={fMontant}
              onChange={(e) => setFMontant(e.target.value)}
              inputMode="decimal"
              placeholder="0.00"
              className="mt-0.5 block w-28 rounded-md border border-brand-800 bg-brand-950 px-2 py-1.5 text-xs text-white"
            />
          </label>
          <label className="text-[11px] text-white/60">
            Fréquence
            <select
              value={fFreq}
              onChange={(e) => setFFreq(e.target.value)}
              className="mt-0.5 block rounded-md border border-brand-800 bg-brand-950 px-2 py-1.5 text-xs text-white"
            >
              <option value="annuel">Annuelle</option>
              <option value="mensuel">Mensuelle</option>
              <option value="ponctuel">Ponctuelle</option>
            </select>
          </label>
          {fFreq === "ponctuel" ? (
            <label className="text-[11px] text-white/60">
              Date
              <input
                type="date"
                value={fDate}
                onChange={(e) => setFDate(e.target.value)}
                className="mt-0.5 block rounded-md border border-brand-800 bg-brand-950 px-2 py-1.5 text-xs text-white"
              />
            </label>
          ) : null}
          <button
            type="button"
            onClick={() => void add()}
            disabled={busy || !fLib.trim() || !fMontant.trim()}
            className="inline-flex items-center gap-1 rounded-lg bg-emerald-500 px-3 py-1.5 text-xs font-semibold text-white hover:bg-emerald-600 disabled:opacity-50"
          >
            {busy ? (
              <Loader2 className="h-3 w-3 animate-spin" />
            ) : (
              <Check className="h-3 w-3" />
            )}
            Enregistrer
          </button>
        </div>
      ) : null}

      {rows === null ? (
        <p className="mt-2 text-xs text-white/40">
          <Loader2 className="mr-1 inline h-3 w-3 animate-spin" />
          Chargement…
        </p>
      ) : rows.length === 0 ? (
        <p className="mt-2 text-xs text-white/40">
          Aucune dépense saisie — ajoute taxes, assurances, entretien…
          pour un cashflow réaliste.
        </p>
      ) : (
        <ul className="mt-2 divide-y divide-brand-800 rounded-lg border border-brand-800">
          {rows.map((d) => (
            <li
              key={d.id}
              className="flex items-center justify-between gap-2 px-3 py-1.5 text-xs"
            >
              <span className="min-w-0">
                <span className="text-white/80">{d.libelle}</span>
                <span className="ml-2 rounded bg-white/10 px-1.5 py-0.5 text-[10px] text-white/50">
                  {CAT_LABEL[d.categorie] || d.categorie}
                </span>
                <span className="ml-1 text-[10px] text-white/40">
                  {d.frequence === "mensuel"
                    ? "mensuelle (×12)"
                    : d.frequence === "annuel"
                      ? "annuelle"
                      : d.date_depense || "ponctuelle"}
                </span>
              </span>
              <span className="flex flex-shrink-0 items-center gap-2">
                <span className="font-semibold tabular-nums text-white">
                  {fmtMoney(d.montant)}
                </span>
                <button
                  type="button"
                  onClick={() => void remove(d)}
                  className="btn-outline-rose btn-xs"
                  title="Supprimer"
                >
                  <Trash2 className="h-3 w-3" />
                </button>
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
