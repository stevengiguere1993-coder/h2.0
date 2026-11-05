"use client";

/**
 * Gestion d'entreprise → Performance du fonds (2026-11-05, v1).
 *
 * Phil : « commençons par ça ! au début pas de registre d'investisseurs, mais
 * surtout les rendements par projet et ceux du fonds ».
 *
 * PRÉVU = la fiche de l'immeuble dans un scénario Revenus et dépenses ;
 * RÉEL = Kratos (prix et date d'achat, loyers de toutes les unités, dépenses
 * réelles, rapport / taux de cap, dette du jour, hypothèques). Tout est
 * calculé côté serveur (`GET /entreprises/revenus-depenses/performance`).
 * Lecture seule, admins seulement.
 */

import { useCallback, useEffect, useState } from "react";
import { AlertTriangle, Building2, ChevronDown, ChevronRight, Landmark, PiggyBank, TrendingUp, Wallet } from "lucide-react";

import { authedFetch } from "@/lib/auth";
import { QGTopbar } from "../layout";

const RD = "/entreprises/revenus-depenses";
const CARD = "rounded-2xl border border-[var(--qg-border)] bg-[var(--qg-card-bg)]";
const MUTED = "text-[var(--qg-text-muted)]";
const FAINT = "text-[var(--qg-text-faint)]";

type Prevu = { cout_projet: number; valeur: number; revenus_nets: number | null; dette: number; equite: number; mise_de_fonds: number | null };
type Reel = {
  prix_achat: number; date_achat: string | null; annees: number | null; travaux_et_frais: number; cout_projet: number; hypotheque_initiale: number;
  mise_de_fonds: number | null; valeur: number; methode_valeur: string; revenus_nets: number | null; service_dette: number; cash_flow: number | null;
  dette: number; equite: number; gain: number | null; rendement_total_pct: number | null; cash_on_cash_pct: number | null; annualise_pct: number | null;
  capital_recupere: boolean;
};
type Ecart = { valeur: number; revenus_nets: number | null; dette: number; equite: number };
type Projet = { id: string; nom: string; kratos_immeuble_id: number | null; dans_le_fonds: boolean; phase: string; prevu: Prevu; reel: Reel | null; ecart: Ecart | null; notes: string[] };
type Fonds = {
  nb_immeubles: number; nb_reels: number; nb_prevus: number; capital_investi: number; valeur: number; dettes: number; cash: number; van: number; gain: number;
  rendement_total_pct: number | null; annees_moyennes: number | null; annualise_pct: number | null; cash_flow_annuel: number; cash_on_cash_pct: number | null;
  part_des_gains: { gain: number; tranche_investisseurs: number; tranche_nous: number; reste: number; part_nous: number; part_investisseurs: number };
  regles: { seuil_investisseurs_pct: number; tranche_nous_pct: number; part_nous_pct: number };
};
type Performance = { projets: Projet[]; fonds: Fonds; aujourd_hui: string; annee_scenario: number; scenario: { id: number; nom: string } };
type ScenarioResume = { id: number; nom: string; is_default: boolean };

function money(n: number | null | undefined, decimals = 0): string {
  return n == null ? "—" : new Intl.NumberFormat("fr-CA", { style: "currency", currency: "CAD", maximumFractionDigits: decimals }).format(n);
}
function pct(n: number | null | undefined, d = 1): string {
  return n == null ? "—" : `${new Intl.NumberFormat("fr-CA", { maximumFractionDigits: d }).format(n)} %`;
}
function nb(n: number | null | undefined, d = 1): string {
  return n == null ? "—" : new Intl.NumberFormat("fr-CA", { maximumFractionDigits: d }).format(n);
}
function dateFr(iso: string | null | undefined): string {
  if (!iso) return "—";
  const [y, m, d] = iso.split("-").map(Number);
  if (!y || !m || !d) return iso;
  return new Date(y, m - 1, d).toLocaleDateString("fr-CA", { day: "numeric", month: "short", year: "numeric" });
}
function teinte(hex: string, alpha = "22"): string {
  return `${hex}${alpha}`;
}
function signe(n: number | null | undefined): string {
  if (n == null) return "";
  return n > 0 ? "text-emerald-400" : n < 0 ? "text-rose-400" : "";
}

const C = { fonds: "#8b5cf6", projet: "#0ea5e9", gain: "#10b981", cash: "#f59e0b", dette: "#f43f5e" };

function KPI({ label, valeur, sous, hex, icon: Icon }: { label: string; valeur: string; sous?: string; hex: string; icon: React.ComponentType<{ className?: string }> }) {
  return (
    <div className={`${CARD} flex items-center gap-3 p-4`} style={{ borderLeft: `4px solid ${hex}` }}>
      <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl" style={{ background: teinte(hex, "26"), color: hex }}>
        <Icon className="h-5 w-5" />
      </span>
      <div className="min-w-0">
        <p className={`text-[10px] font-semibold uppercase tracking-wider ${FAINT}`}>{label}</p>
        <p className="text-lg font-bold tabular-nums leading-tight">{valeur}</p>
        {sous ? <p className={`text-[11px] ${MUTED}`}>{sous}</p> : null}
      </div>
    </div>
  );
}

function Ligne({ label, prevu, reel, ecart, fmt = money }: { label: string; prevu: number | null | undefined; reel: number | null | undefined; ecart?: number | null; fmt?: (n: number | null | undefined) => string }) {
  return (
    <tr className="border-t border-[var(--qg-border)]">
      <td className={`py-1 pr-3 ${MUTED}`}>{label}</td>
      <td className="py-1 pr-3 text-right tabular-nums">{fmt(prevu)}</td>
      <td className="py-1 pr-3 text-right font-semibold tabular-nums">{fmt(reel)}</td>
      <td className={`py-1 text-right tabular-nums ${signe(ecart)}`}>{ecart == null ? "" : `${ecart > 0 ? "+" : ""}${fmt(ecart)}`}</td>
    </tr>
  );
}

function CarteProjet({ p }: { p: Projet }) {
  const [ouvert, setOuvert] = useState(false);
  const r = p.reel;
  const hex = p.dans_le_fonds ? C.fonds : "#94a3b8";
  return (
    <div className={`${CARD} overflow-hidden`} style={{ borderLeft: `4px solid ${hex}` }}>
      <button type="button" onClick={() => setOuvert((o) => !o)} className="flex w-full flex-wrap items-center gap-x-4 gap-y-1 px-4 py-3 text-left" style={{ background: teinte(hex, "10") }}>
        {ouvert ? <ChevronDown className="h-4 w-4 shrink-0" /> : <ChevronRight className="h-4 w-4 shrink-0" />}
        <span className="min-w-[200px] flex-1 font-semibold">{p.nom}</span>
        <span className={`rounded-full border px-2 py-0.5 text-[10px] uppercase tracking-wider ${p.dans_le_fonds ? "" : FAINT}`} style={p.dans_le_fonds ? { borderColor: hex, color: hex } : { borderColor: "var(--qg-border)" }}>{p.dans_le_fonds ? "dans le fonds" : "hors fonds"}</span>
        {r ? (
          <>
            <span className={`text-xs ${MUTED}`}>acquis {dateFr(r.date_achat)}{r.annees ? ` · ${nb(r.annees, 1)} an${r.annees >= 2 ? "s" : ""}` : ""}</span>
            <span className="text-xs">mise <b className="tabular-nums">{money(r.mise_de_fonds)}</b>{r.capital_recupere ? <span className={FAINT}> (récupérée)</span> : null}</span>
            <span className="text-xs">équité <b className={`tabular-nums ${signe(r.equite)}`}>{money(r.equite)}</b></span>
            <span className="text-xs">cash-flow <b className={`tabular-nums ${signe(r.cash_flow)}`}>{money(r.cash_flow)}</b></span>
            {r.capital_recupere ? <span className={`text-xs ${FAINT}`}>capital récupéré · gain = équité</span> : <span className="text-xs">rendement <b className={`tabular-nums ${signe(r.rendement_total_pct)}`}>{pct(r.rendement_total_pct)}</b>{r.annualise_pct != null ? <span className={FAINT}> · {pct(r.annualise_pct)} / an</span> : null}</span>}
          </>
        ) : (
          <span className={`text-xs ${FAINT}`}>prévu seulement · valeur {money(p.prevu.valeur)} · équité {money(p.prevu.equite)}</span>
        )}
        {p.notes.length ? <span className="inline-flex items-center gap-1 text-xs text-amber-300"><AlertTriangle className="h-3 w-3" /> {p.notes.length}</span> : null}
      </button>
      {ouvert ? (
        <div className="grid gap-4 p-4 lg:grid-cols-[1fr_minmax(260px,0.8fr)]">
          <table className="w-full text-xs">
            <thead className={`text-left ${FAINT}`}>
              <tr>
                <th className="py-1 pr-3 font-semibold uppercase tracking-wider">Projet</th>
                <th className="py-1 pr-3 text-right font-semibold uppercase tracking-wider">Prévu (scénario)</th>
                <th className="py-1 pr-3 text-right font-semibold uppercase tracking-wider">Réel (Kratos)</th>
                <th className="py-1 text-right font-semibold uppercase tracking-wider">Écart</th>
              </tr>
            </thead>
            <tbody>
              <Ligne label="Coût du projet (prix + travaux + frais)" prevu={p.prevu.cout_projet || null} reel={r?.cout_projet || null} />
              <Ligne label="Hypothèque initiale" prevu={null} reel={r?.hypotheque_initiale} />
              <Ligne label="Mise de fonds" prevu={p.prevu.mise_de_fonds} reel={r?.mise_de_fonds} />
              <Ligne label="Valeur" prevu={p.prevu.valeur} reel={r?.valeur} ecart={p.ecart?.valeur} />
              <Ligne label="Revenus nets SCHL / an" prevu={p.prevu.revenus_nets} reel={r?.revenus_nets} ecart={p.ecart?.revenus_nets} />
              <Ligne label="Service de dette / an" prevu={null} reel={r?.service_dette} />
              <Ligne label="Cash-flow / an" prevu={null} reel={r?.cash_flow} />
              <Ligne label="Dette (du jour)" prevu={p.prevu.dette} reel={r?.dette} ecart={p.ecart?.dette} />
              <Ligne label="Équité (valeur − dette)" prevu={p.prevu.equite} reel={r?.equite} ecart={p.ecart?.equite} />
              <Ligne label="Gain d'équité (équité − mise)" prevu={null} reel={r?.gain} />
              <Ligne label="Rendement total (gain ÷ mise)" prevu={null} reel={r?.rendement_total_pct} fmt={(n) => pct(n)} />
              <Ligne label="Cash-on-cash (cash-flow ÷ mise)" prevu={null} reel={r?.cash_on_cash_pct} fmt={(n) => pct(n)} />
              <Ligne label="Annualisé depuis l'achat" prevu={null} reel={r?.annualise_pct} fmt={(n) => pct(n)} />
            </tbody>
          </table>
          <div className="space-y-2 text-xs">
            {r ? <p className={MUTED}>Valeur réelle : {r.methode_valeur}.</p> : null}
            {p.notes.length ? (
              <div className="rounded-xl border border-amber-500/40 bg-amber-500/10 p-2.5 text-[11px] text-amber-200">
                <p className="mb-1 flex items-center gap-1 font-semibold"><AlertTriangle className="h-3.5 w-3.5" /> À vérifier</p>
                <ul className="space-y-0.5">{p.notes.map((n, i) => <li key={i}>{n}</li>)}</ul>
              </div>
            ) : null}
            <p className={FAINT}>Prévu = fiche du scénario ; réel = Kratos (prix et date d&apos;achat, loyers de toutes les unités, dépenses réelles, rapport et taux de cap, dette du jour, hypothèques). Les travaux et frais connexes réels viennent de la fiche du scénario.</p>
          </div>
        </div>
      ) : null}
    </div>
  );
}

export default function PerformanceFondsPage() {
  const [scenarios, setScenarios] = useState<ScenarioResume[]>([]);
  const [courant, setCourant] = useState<number | null>(null);
  const [perf, setPerf] = useState<Performance | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [charge, setCharge] = useState(true);

  const charger = useCallback(async (id: number | null) => {
    setCharge(true);
    try {
      const r = await authedFetch(`${RD}/performance${id != null ? `?scenario_id=${id}` : ""}`);
      if (r.status === 403) throw new Error("Réservé aux administrateurs.");
      if (!r.ok) throw new Error(`Erreur ${r.status}`);
      const d = (await r.json()) as Performance;
      setPerf(d);
      setCourant(d.scenario.id);
      setErr(null);
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setCharge(false);
    }
  }, []);

  useEffect(() => {
    void (async () => {
      try {
        const r = await authedFetch(`${RD}/scenarios`);
        if (r.ok) setScenarios(((await r.json()) as { items: ScenarioResume[] }).items);
      } catch {
        /* liste facultative */
      }
      await charger(null);
    })();
  }, [charger]);

  const f = perf?.fonds;
  const sousTitre = perf ? `Scénario « ${perf.scenario.nom} » (${perf.annee_scenario}) · réel au ${dateFr(perf.aujourd_hui)}` : "Rendements réels des projets et du fonds";

  return (
    <div className="space-y-5">
      <QGTopbar
        greeting="Performance du fonds"
        subtitle={sousTitre}
        rightSlot={
          scenarios.length > 1 ? (
            <select value={courant ?? ""} onChange={(e) => void charger(Number(e.target.value))} className="rounded-lg border border-[var(--qg-border)] bg-[var(--qg-bg)] px-2.5 py-1.5 text-sm outline-none">
              {scenarios.map((s) => <option key={s.id} value={s.id}>{s.nom}</option>)}
            </select>
          ) : undefined
        }
      />
      {err ? <p className="rounded-xl border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">{err}</p> : null}
      {charge && !perf ? <p className={`text-sm ${MUTED}`}>Chargement…</p> : null}
      {perf && f ? (
        <>
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-6">
            <KPI label="Capital investi" valeur={money(f.capital_investi)} sous={`${f.nb_immeubles} immeuble${f.nb_immeubles > 1 ? "s" : ""} dans le fonds (${f.nb_reels} réel${f.nb_reels > 1 ? "s" : ""}, ${f.nb_prevus} prévu${f.nb_prevus > 1 ? "s" : ""})`} hex={C.projet} icon={Building2} />
            <KPI label="VAN du fonds" valeur={money(f.van)} sous={`${money(f.valeur)} − ${money(f.dettes)} + cash ${money(f.cash)}`} hex={C.fonds} icon={Landmark} />
            <KPI label="Gain" valeur={money(f.gain)} sous="VAN − capital investi" hex={C.gain} icon={TrendingUp} />
            <KPI label="Rendement total" valeur={pct(f.rendement_total_pct)} sous="gain ÷ capital" hex={C.gain} icon={TrendingUp} />
            <KPI label="Annualisé" valeur={pct(f.annualise_pct)} sous={f.annees_moyennes ? `sur ${nb(f.annees_moyennes, 1)} an${f.annees_moyennes >= 2 ? "s" : ""} en moyenne` : "date d'achat requise"} hex={C.fonds} icon={TrendingUp} />
            <KPI label="Cash-flow annuel" valeur={money(f.cash_flow_annuel)} sous={`cash-on-cash ${pct(f.cash_on_cash_pct)}`} hex={C.cash} icon={Wallet} />
          </div>

          <section className={`${CARD} overflow-hidden`} style={{ borderTop: `3px solid ${C.projet}` }}>
            <div className="flex flex-wrap items-center gap-3 px-4 py-3" style={{ background: teinte(C.projet, "14") }}>
              <span className="flex h-9 w-9 items-center justify-center rounded-xl" style={{ background: teinte(C.projet, "33"), color: C.projet }}><Building2 className="h-5 w-5" /></span>
              <div className="min-w-0 flex-1">
                <h3 className="text-sm font-semibold">Rendements par projet</h3>
                <p className={`text-[11px] leading-snug ${MUTED}`}>Mise de fonds = coût du projet − hypothèque initiale · cash-flow = revenus nets SCHL − service de dette · gain = équité − mise · annualisé = (équité ÷ mise) ^ (1 ÷ années) − 1. Clique sur un immeuble pour le détail prévu / réel / écart.</p>
              </div>
            </div>
            <div className="space-y-3 p-4">
              {perf.projets.map((p) => <CarteProjet key={p.id} p={p} />)}
              {!perf.projets.length ? <p className={`text-sm ${FAINT}`}>Aucun immeuble dans ce scénario.</p> : null}
              {perf.projets.length && !f.nb_immeubles ? <p className={`rounded-xl border border-dashed border-[var(--qg-border)] px-4 py-3 text-xs ${MUTED}`}>Aucun immeuble n&apos;est « dans le fonds » dans ce scénario : le bloc Fonds reste à zéro. Coche « Dans le fonds » dans Revenus et dépenses pour les immeubles que le fonds détient.</p> : null}
            </div>
          </section>

          <section className={`${CARD} overflow-hidden`} style={{ borderTop: `3px solid ${C.fonds}` }}>
            <div className="flex flex-wrap items-center gap-3 px-4 py-3" style={{ background: teinte(C.fonds, "14") }}>
              <span className="flex h-9 w-9 items-center justify-center rounded-xl" style={{ background: teinte(C.fonds, "33"), color: C.fonds }}><PiggyBank className="h-5 w-5" /></span>
              <div className="min-w-0 flex-1">
                <h3 className="text-sm font-semibold">Rendement du fonds et part des gains</h3>
                <p className={`text-[11px] leading-snug ${MUTED}`}>Immeubles « dans le fonds » seulement, réel quand Kratos le permet, sinon prévu. Part des gains sur le gain réel, règles du document : les premiers {pct(f.regles.seuil_investisseurs_pct, 1)} du capital aux investisseurs, les {pct(f.regles.tranche_nous_pct, 1)} suivants à nous, le reste {pct(100 - f.regles.part_nous_pct, 0)} / {pct(f.regles.part_nous_pct, 0)}.</p>
              </div>
            </div>
            <div className="grid gap-4 p-4 text-xs lg:grid-cols-2">
              <ul className="space-y-1">
                <li className="flex justify-between gap-2"><span>Capital investi (mises de fonds)</span><b className="tabular-nums">{money(f.capital_investi)}</b></li>
                <li className="flex justify-between gap-2"><span>Valeur des immeubles</span><span className="tabular-nums">{money(f.valeur)}</span></li>
                <li className="flex justify-between gap-2"><span>Dettes du jour</span><span className="tabular-nums">− {money(f.dettes)}</span></li>
                <li className="flex justify-between gap-2"><span>Cash du fonds</span><span className="tabular-nums">{money(f.cash)}</span></li>
                <li className="flex justify-between gap-2 border-t border-[var(--qg-border)] pt-1 font-semibold"><span>VAN</span><span className="tabular-nums" style={{ color: C.fonds }}>{money(f.van)}</span></li>
                <li className="flex justify-between gap-2"><span>Gain (VAN − capital)</span><b className={`tabular-nums ${signe(f.gain)}`}>{money(f.gain)}</b></li>
                <li className="flex justify-between gap-2"><span>Rendement total · annualisé</span><span className="tabular-nums">{pct(f.rendement_total_pct)} · {pct(f.annualise_pct)}</span></li>
                <li className="flex justify-between gap-2"><span>Cash-flow annuel · cash-on-cash</span><span className="tabular-nums">{money(f.cash_flow_annuel)} · {pct(f.cash_on_cash_pct)}</span></li>
              </ul>
              <ul className="space-y-1 rounded-xl p-3" style={{ background: teinte(C.fonds, "12"), border: `1px solid ${teinte(C.fonds, "44")}` }}>
                <li className="flex justify-between gap-2"><span>Gain à partager</span><b className="tabular-nums">{money(f.part_des_gains.gain)}</b></li>
                <li className="flex justify-between gap-2"><span>Aux investisseurs (premiers {pct(f.regles.seuil_investisseurs_pct, 1)})</span><span className="tabular-nums">{money(f.part_des_gains.tranche_investisseurs)}</span></li>
                <li className="flex justify-between gap-2"><span>À nous ({pct(f.regles.tranche_nous_pct, 1)} suivants)</span><span className="tabular-nums">{money(f.part_des_gains.tranche_nous)}</span></li>
                <li className="flex justify-between gap-2"><span>Reste partagé {pct(100 - f.regles.part_nous_pct, 0)} / {pct(f.regles.part_nous_pct, 0)}</span><span className="tabular-nums">{money(f.part_des_gains.reste)}</span></li>
                <li className="flex justify-between gap-2 border-t border-[var(--qg-border)] pt-1 font-semibold"><span>Part des investisseurs</span><span className="tabular-nums">{money(f.part_des_gains.part_investisseurs)}</span></li>
                <li className="flex justify-between gap-2 font-semibold"><span>Notre part (en parts du fonds)</span><span className="tabular-nums" style={{ color: C.gain }}>{money(f.part_des_gains.part_nous)}</span></li>
              </ul>
            </div>
          </section>
        </>
      ) : null}
    </div>
  );
}
