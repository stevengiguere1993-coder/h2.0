"use client";

/**
 * Revenus et dépenses → onglet « Performance du fonds » (v2 2026-11-06 : projection ;
 * v3 2026-11-09 : refinancements, cash remis aux investisseurs, fourchette).
 *
 * Phil : « il faut que tout ça soit annualisé… en ayant seulement l'année
 * actuelle, on ne peut pas voir la performance du fonds » ; « un fonds c'est
 * toujours sur le capital du fonds… il faut que ça reflète [le document] » ;
 * « de l'argent qui dort… le voir comme si on l'avait remboursé » ; « on ne
 * peut pas savoir d'avance le taux d'intérêt et le taux de cap… un plus ou moins ».
 *
 * Année par année, selon le document du fonds : VAN = valeur + cash − dettes
 * (p. 11), gain de l'année = VAN fin − VAN début + cash remis, avec ses trois
 * sources (p. 14), rendement du fonds = gain ÷ VAN de départ, partage en parts
 * 7 % / 3 % / 70-30 (p. 7-8), frais du fonds en cash (p. 20), refi sur la
 * valeur stabilisée (p. 12). Calculé côté serveur
 * (`GET /entreprises/revenus-depenses/performance`), lecture seule ici.
 */

import { useEffect, useState } from "react";
import { AlertTriangle, Building2, ChevronDown, ChevronRight, History, Landmark, PiggyBank, RefreshCw, TrendingUp, Wallet } from "lucide-react";

import { authedFetch } from "@/lib/auth";

const RD = "/api/v1/entreprises/revenus-depenses";
const CARD = "rounded-2xl border border-[var(--qg-border)] bg-[var(--qg-card-bg)]";
const MUTED = "text-[var(--qg-text-muted)]";
const FAINT = "text-[var(--qg-text-faint)]";

type Evenement = { annee: number; type: "renouvellement" | "conversion" | "refinancement"; ancien_solde: number; nouveau_pret: number; cash_sorti: number; frais: number; taux_pct: number; valeur: number; ltv_pct?: number };
type AnneeProjet = {
  annee: number; n: number; en_renovation: boolean; prorata: number; revenus_bruts: number; depenses: number; revenus_nets: number;
  service_dette: number; interets: number; capital_rembourse: number; cash_flow: number; cash_flow_cumule: number; solde: number; valeur: number; methode: string; equite: number;
  cash_refi: number; frais_refi: number; evenements: Evenement[];
};
type SommaireProjet = {
  equite_depart: number; equite_horizon: number; cash_flow_cumule: number; cash_refi_cumule: number; frais_refi_cumules: number; nb_refinancements: number;
  capital_rembourse: number; plus_value: number; gain_total: number; multiple: number | null; rendement_total_pct: number | null; annualise_pct: number | null; tri_pct: number | null;
};
type Projet = {
  id: string; nom: string; kratos_immeuble_id: number | null; dans_le_fonds: boolean; phase: string; acquise_cette_annee: boolean; date_acquisition: string | null;
  annee_stabilisation: number | null;
  depart: { valeur: number; cout_projet: number; dette: number; equite: number; revenus_nets: number; taux_cap_pct: number; nb_prets: number; prets_kratos: boolean; valeur_entree: number };
  annees: AnneeProjet[]; sommaire: SommaireProjet; notes: string[];
};
type AnneeFonds = {
  annee: number; n: number; revenus_bruts: number; depenses: number; revenus_nets: number; service_dette: number; capital_rembourse: number; frais_fonds: number;
  cash_flow: number; cash_net: number; cash_refi: number; frais_refi: number; distributions: number; cash: number; valeur: number; dettes: number; van_debut: number;
  capital_entre: number; van: number; gain: number; rendement_pct: number | null;
  sources: { plus_value: number; capital_rembourse: number; cash: number };
  partage: { tranche_investisseurs: number; tranche_nous: number; reste: number; part_nous: number; part_investisseurs: number };
  prix_part: number; distribution_par_part: number; rendement_part_pct: number; parts_total: number; parts_entrees: number; nouvelles_parts_nous: number; parts_nous: number; pct_nous: number;
};
type SommaireFonds = {
  van_depart: number; van_horizon: number; capital_entre: number; gain_total: number; plus_value: number; capital_rembourse: number; cash_flow_cumule: number;
  frais_fonds_cumules: number; cash_horizon: number; cash_refi_total: number; frais_refi_total: number; nb_refinancements: number; distributions_total: number; cash_remis: boolean;
  part_nous_total: number; part_investisseurs_total: number; tri_pct: number | null; rendement_moyen_pct: number | null;
  prix_part_depart: number; prix_part_horizon: number; distributions_par_part: number; valeur_totale_par_part: number; rendement_part_annualise_pct: number | null; parts_depart: number; parts_horizon: number;
  parts_nous_horizon: number; pct_nous_horizon: number; nb_immeubles: number; nb_hors_fonds: number; nb_acquisitions_an1: number;
};
type Borne = { van_horizon: number; tri_pct: number | null; rendement_moyen_pct: number | null; prix_part_horizon: number; rendement_part_annualise_pct: number | null; pct_nous_horizon: number; distributions_total: number; gain_total: number };
type Fourchette = { points: number; prudent: Borne; favorable: Borne } | null;
type Historique = {
  id: string; nom: string; kratos_immeuble_id: number; prix_achat: number; date_achat: string | null; nb_prets: number; refinance: boolean;
  premier_pret: { montant: number; date: string | null; status: string } | null; manques: string[]; complet: boolean;
};
type Hypotheses = {
  croissance_loyers_pct: number; croissance_depenses_pct: number; horizon_annees: number; incertitude_points: number;
  refinancement: { actif: boolean; ltv_pct: number; frais_pct: number; cadence_ans: number; cash_remis: boolean };
  prix_part_depart: number; part_nos_holdings_depart_pct: number;
};
type Performance = {
  annee_depart: number; horizon: number; hypotheses: Hypotheses; regles: { seuil_investisseurs_pct: number; tranche_nous_pct: number; part_nous_pct: number }; aujourd_hui: string;
  reference_prets: { taux_pct: number; amortissement_mois: number; nb_prets: number; source: string };
  fonds: { annees: AnneeFonds[]; sommaire: SommaireFonds; cash_depart: number; taux_frais_pct: number; fourchette: Fourchette };
  projets: Projet[]; historique: Historique[]; scenario: { id: number; nom: string };
};

function money(n: number | null | undefined, decimals = 0): string {
  return n == null ? "—" : new Intl.NumberFormat("fr-CA", { style: "currency", currency: "CAD", maximumFractionDigits: decimals }).format(n);
}
function compact(n: number): string {
  const abs = Math.abs(n);
  if (abs >= 1_000_000) return `${new Intl.NumberFormat("fr-CA", { maximumFractionDigits: 2 }).format(n / 1_000_000)} M$`;
  if (abs >= 1_000) return `${new Intl.NumberFormat("fr-CA", { maximumFractionDigits: 0 }).format(n / 1_000)} k$`;
  return money(n);
}
function pct(n: number | null | undefined, d = 1): string {
  return n == null ? "—" : `${new Intl.NumberFormat("fr-CA", { maximumFractionDigits: d }).format(n)} %`;
}
function nb(n: number | null | undefined, d = 0): string {
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
function fourchetteTxt(f: Fourchette, k: keyof Borne, fmt: (n: number | null | undefined) => string): string | undefined {
  if (!f) return undefined;
  const a = f.prudent[k] as number | null;
  const b = f.favorable[k] as number | null;
  if (a == null || b == null) return undefined;
  return `de ${fmt(Math.min(a, b))} à ${fmt(Math.max(a, b))} (± ${nb(f.points, 2)} pt)`;
}

const C = { fonds: "#8b5cf6", projet: "#0ea5e9", gain: "#10b981", cash: "#f59e0b", refi: "#f97316", histo: "#64748b" };

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

function Entete({ hex, icon: Icon, titre, note }: { hex: string; icon: React.ComponentType<{ className?: string }>; titre: string; note: string }) {
  return (
    <div className="flex flex-wrap items-center gap-3 px-4 py-3" style={{ background: teinte(hex, "14") }}>
      <span className="flex h-9 w-9 items-center justify-center rounded-xl" style={{ background: teinte(hex, "33"), color: hex }}><Icon className="h-5 w-5" /></span>
      <div className="min-w-0 flex-1">
        <h3 className="text-sm font-semibold">{titre}</h3>
        <p className={`text-[11px] leading-snug ${MUTED}`}>{note}</p>
      </div>
    </div>
  );
}

type Ligne<T> = { label: string; val: (a: T) => number | null | undefined; fmt?: (n: number | null | undefined) => string; fort?: boolean; sous?: boolean; hex?: string; couleur?: boolean; masquer?: boolean };

/** Tableau années en colonnes, indicateurs en lignes ; première colonne collée. */
function TableAnnees<T extends { annee: number }>({ annees, lignes, sousTitres }: { annees: T[]; lignes: Ligne<T>[]; sousTitres?: (a: T) => string | null }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[640px] text-xs">
        <thead className={FAINT}>
          <tr>
            <th className="sticky left-0 z-10 bg-[var(--qg-card-bg)] py-1.5 pr-3 text-left font-semibold uppercase tracking-wider">Année</th>
            {annees.map((a) => (
              <th key={a.annee} className="py-1.5 pl-3 text-right font-semibold tabular-nums">
                {a.annee}
                {sousTitres && sousTitres(a) ? <span className={`block text-[9px] font-normal normal-case ${FAINT}`}>{sousTitres(a)}</span> : null}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {lignes.filter((l) => !l.masquer).map((l) => (
            <tr key={l.label} className={`border-t border-[var(--qg-border)] ${l.fort ? "font-semibold" : ""}`} style={l.hex ? { background: teinte(l.hex, "10") } : undefined}>
              <td className={`sticky left-0 z-10 whitespace-nowrap bg-[var(--qg-card-bg)] py-1 pr-3 ${l.sous ? `pl-3 ${MUTED}` : ""}`} style={l.hex ? { color: l.hex } : undefined}>{l.label}</td>
              {annees.map((a) => {
                const v = l.val(a);
                return <td key={a.annee} className={`whitespace-nowrap py-1 pl-3 text-right tabular-nums ${l.couleur ? signe(v) : ""}`}>{(l.fmt || money)(v)}</td>;
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Barres de VAN par année (notre part en superposition) et cash remis aux investisseurs. */
function GraphiqueVAN({ annees, vanDepart }: { annees: AnneeFonds[]; vanDepart: number }) {
  const points = [{ annee: annees.length ? annees[0].annee - 1 : 0, van: vanDepart, pct: null as number | null, dist: 0 }, ...annees.map((a) => ({ annee: a.annee, van: a.van, pct: a.pct_nous, dist: a.distributions }))];
  const max = Math.max(...points.map((p) => p.van + p.dist), 1);
  const W = 720, H = 190, padL = 8, padB = 28, padT = 22;
  const bw = (W - padL * 2) / points.length;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="h-48 w-full" role="img" aria-label="VAN du fonds par année">
      {points.map((p, i) => {
        const h = Math.max(((H - padB - padT) * p.van) / max, 1);
        const hd = ((H - padB - padT) * p.dist) / max;
        const x = padL + i * bw + bw * 0.15;
        const y = H - padB - h;
        const notre = p.pct != null ? (h * p.pct) / 100 : 0;
        return (
          <g key={p.annee}>
            <rect x={x} y={y} width={bw * 0.7} height={h} rx={4} fill={C.fonds} opacity={i === 0 ? 0.45 : 0.8} />
            {notre > 0 ? <rect x={x} y={H - padB - notre} width={bw * 0.7} height={notre} rx={3} fill={C.gain} opacity={0.95} /> : null}
            {hd > 0.5 ? <rect x={x} y={y - hd} width={bw * 0.7} height={hd} rx={3} fill={C.cash} opacity={0.7} /> : null}
            <text x={x + bw * 0.35} y={y - hd - 6} textAnchor="middle" fontSize={10} fill="currentColor" className="tabular-nums">{compact(p.van)}{p.dist > 0 ? ` +${compact(p.dist)}` : ""}</text>
            <text x={x + bw * 0.35} y={H - padB + 13} textAnchor="middle" fontSize={10} fill="currentColor" opacity={0.6}>{i === 0 ? "départ" : p.annee}</text>
            {p.pct != null && p.pct > 0 ? <text x={x + bw * 0.35} y={H - padB + 25} textAnchor="middle" fontSize={9} fill={C.gain}>{pct(p.pct, 1)} à nous</text> : null}
          </g>
        );
      })}
    </svg>
  );
}

function typeEvenement(e: Evenement): string {
  if (e.type === "refinancement") return `refinancé : nouveau prêt ${money(e.nouveau_pret)} (${pct(e.ltv_pct ?? 0, 0)} de ${money(e.valeur)}) à ${pct(e.taux_pct, 2)}, frais ${money(e.frais)}, cash sorti ${money(e.cash_sorti)}`;
  if (e.type === "conversion") return `prêt intérêts seulement devenu hypothèque amortie à ${pct(e.taux_pct, 2)}`;
  return `terme renouvelé à ${pct(e.taux_pct, 2)}`;
}

function CarteProjet({ p }: { p: Projet }) {
  const [ouvert, setOuvert] = useState(false);
  const hex = p.dans_le_fonds ? C.projet : "#94a3b8";
  const s = p.sommaire;
  const evenements = p.annees.flatMap((a) => a.evenements);
  return (
    <div className={`${CARD} overflow-hidden`} style={{ borderLeft: `4px solid ${hex}` }}>
      <button type="button" onClick={() => setOuvert((o) => !o)} className="flex w-full flex-wrap items-center gap-x-4 gap-y-1 px-4 py-3 text-left" style={{ background: teinte(hex, "10") }}>
        {ouvert ? <ChevronDown className="h-4 w-4 shrink-0" /> : <ChevronRight className="h-4 w-4 shrink-0" />}
        <span className="min-w-[200px] flex-1 font-semibold">{p.nom}</span>
        <span className={`rounded-full border px-2 py-0.5 text-[10px] uppercase tracking-wider ${p.dans_le_fonds ? "" : FAINT}`} style={p.dans_le_fonds ? { borderColor: hex, color: hex } : { borderColor: "var(--qg-border)" }}>{p.dans_le_fonds ? "dans le fonds" : "hors fonds"}</span>
        {p.acquise_cette_annee ? <span className="rounded-full border border-amber-400/60 px-2 py-0.5 text-[10px] uppercase tracking-wider text-amber-300">acquis {p.date_acquisition ? `le ${dateFr(p.date_acquisition)}` : "cette année"}</span> : null}
        {p.annee_stabilisation ? <span className={`text-xs ${MUTED}`}>stabilisé en {p.annee_stabilisation}</span> : null}
        {s.nb_refinancements ? <span className="inline-flex items-center gap-1 text-xs" style={{ color: C.refi }}><RefreshCw className="h-3 w-3" /> {s.nb_refinancements} refi · {money(s.cash_refi_cumule)} sortis</span> : null}
        <span className="text-xs">capital <b className="tabular-nums">{money(s.equite_depart)}</b> → <b className={`tabular-nums ${signe(s.equite_horizon - s.equite_depart)}`}>{money(s.equite_horizon)}</b></span>
        <span className="text-xs">cash-flow cumulé <b className={`tabular-nums ${signe(s.cash_flow_cumule)}`}>{money(s.cash_flow_cumule)}</b></span>
        <span className="text-xs">TRI <b className={`tabular-nums ${signe(s.tri_pct)}`}>{pct(s.tri_pct)}</b>{s.multiple != null ? <span className={FAINT}> · ×{nb(s.multiple, 2)}</span> : null}</span>
        {p.notes.length ? <span className="inline-flex items-center gap-1 text-xs text-amber-300"><AlertTriangle className="h-3 w-3" /> {p.notes.length}</span> : null}
      </button>
      {ouvert ? (
        <div className="space-y-3 p-4">
          <TableAnnees
            annees={p.annees}
            sousTitres={(a) => (a.en_renovation ? "en rénovation" : a.evenements.some((e) => e.type === "refinancement") ? "refi" : a.prorata < 100 ? `${pct(a.prorata, 0)} de l'année` : null)}
            lignes={[
              { label: "Revenus bruts", val: (a) => a.revenus_bruts },
              { label: "Dépenses (barème SCHL)", val: (a) => a.depenses, sous: true },
              { label: "Revenus nets", val: (a) => a.revenus_nets, fort: true },
              { label: "Service de dette", val: (a) => a.service_dette },
              { label: "dont capital remboursé", val: (a) => a.capital_rembourse, sous: true },
              { label: "Cash-flow", val: (a) => a.cash_flow, fort: true, couleur: true, hex: C.cash },
              { label: "Cash sorti au refinancement", val: (a) => a.cash_refi || null, hex: C.refi, masquer: !s.nb_refinancements },
              { label: "Cash-flow cumulé", val: (a) => a.cash_flow_cumule, sous: true, couleur: true },
              { label: "Solde de la dette", val: (a) => a.solde },
              { label: "Valeur", val: (a) => a.valeur },
              { label: "Équité (valeur − dette)", val: (a) => a.equite, fort: true, hex: C.projet }
            ]}
          />
          <div className="grid gap-3 text-xs lg:grid-cols-[1fr_minmax(260px,0.8fr)]">
            <ul className={`space-y-0.5 ${MUTED}`}>
              <li>Départ : valeur {money(p.depart.valeur)} · dette {money(p.depart.dette)} ({p.depart.prets_kratos ? `${p.depart.nb_prets} prêt${p.depart.nb_prets > 1 ? "s" : ""} Kratos` : "dette de la fiche"}) · capital {money(p.depart.equite)}{p.depart.taux_cap_pct ? ` · taux de cap ${pct(p.depart.taux_cap_pct, 2)}` : ""}.</li>
              <li>À l&apos;horizon : plus-value {money(s.plus_value)}, capital remboursé {money(s.capital_rembourse)}, cash-flow cumulé {money(s.cash_flow_cumule)}{s.cash_refi_cumule ? `, cash sorti aux refis ${money(s.cash_refi_cumule)}` : ""} → gain {money(s.gain_total)} ({pct(s.rendement_total_pct)} du capital, {pct(s.annualise_pct)} par an, TRI {pct(s.tri_pct)}).</li>
              <li>Valeur : {Array.from(new Set(p.annees.map((a) => a.methode))).join(" → ")}.</li>
              {evenements.length ? <li>Prêts : {evenements.map((e) => `${e.annee} — ${typeEvenement(e)}`).join(" ; ")}.</li> : null}
            </ul>
            {p.notes.length ? (
              <div className="rounded-xl border border-amber-500/40 bg-amber-500/10 p-2.5 text-[11px] text-amber-200">
                <p className="mb-1 flex items-center gap-1 font-semibold"><AlertTriangle className="h-3.5 w-3.5" /> Hypothèses prises</p>
                <ul className="space-y-0.5">{p.notes.map((n, i) => <li key={i}>{n}</li>)}</ul>
              </div>
            ) : null}
          </div>
        </div>
      ) : null}
    </div>
  );
}

export function PerformanceTab({ scenarioId, version }: { scenarioId: number | null; version: string | null }) {
  const [perf, setPerf] = useState<Performance | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [charge, setCharge] = useState(true);

  useEffect(() => {
    let actif = true;
    void (async () => {
      setCharge(true);
      try {
        const r = await authedFetch(`${RD}/performance${scenarioId != null ? `?scenario_id=${scenarioId}` : ""}`);
        if (r.status === 403) throw new Error("Réservé aux administrateurs.");
        if (!r.ok) throw new Error(`Erreur ${r.status}`);
        const d = (await r.json()) as Performance;
        if (!actif) return;
        setPerf(d);
        setErr(null);
      } catch (e) {
        if (actif) setErr((e as Error).message);
      } finally {
        if (actif) setCharge(false);
      }
    })();
    return () => {
      actif = false;
    };
  }, [scenarioId, version]);

  const s = perf?.fonds.sommaire;
  const annees = perf?.fonds.annees || [];
  const h = perf?.hypotheses;
  const fo = perf?.fonds.fourchette ?? null;
  const remis = !!s?.cash_remis;
  return (
    <div className="space-y-4">
      {err ? <p className="rounded-xl border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">{err}</p> : null}
      {charge && !perf ? <p className={`text-sm ${MUTED}`}>Chargement…</p> : null}
      {perf && s && h ? (
        <>
          <p className={`text-xs ${MUTED}`}>
            Projection de {perf.annee_depart} à {perf.annee_depart + perf.horizon - 1} ({perf.horizon} ans) · scénario « {perf.scenario.nom} » · loyers +{pct(h.croissance_loyers_pct)} et dépenses +{pct(h.croissance_depenses_pct)} par an · frais du fonds {pct(perf.fonds.taux_frais_pct)} de la VAN · {h.refinancement.actif ? `refinancement à ${pct(h.refinancement.ltv_pct, 0)} de la valeur à l'échéance des termes et à la stabilisation` : "détention simple, sans refinancement"} · {remis ? "cash remis aux investisseurs" : "cash gardé dans le fonds"} · prêts inconnus : {perf.reference_prets.source}.{charge ? " Mise à jour…" : ""}
          </p>
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
            <KPI label="VAN du fonds" valeur={`${compact(s.van_depart)} → ${compact(s.van_horizon)}`} sous={fourchetteTxt(fo, "van_horizon", (n) => compact(n ?? 0)) ?? `${s.nb_immeubles} immeuble${s.nb_immeubles > 1 ? "s" : ""} dans le fonds`} hex={C.fonds} icon={Landmark} />
            <KPI label="Rendement du fonds" valeur={pct(s.rendement_moyen_pct)} sous={`moyenne par an · TRI ${pct(s.tri_pct)}${fourchetteTxt(fo, "tri_pct", (n) => pct(n)) ? ` · ${fourchetteTxt(fo, "tri_pct", (n) => pct(n))}` : ""}`} hex={C.gain} icon={TrendingUp} />
            <KPI label="Pour un investisseur" valeur={`${pct(s.rendement_part_annualise_pct)} par an`} sous={`part ${money(s.prix_part_depart, 2)} → ${money(s.prix_part_horizon, 2)}${remis && s.distributions_par_part ? ` + ${money(s.distributions_par_part, 2)} de cash remis = ${money(s.valeur_totale_par_part, 2)} par part` : ""}${fourchetteTxt(fo, "rendement_part_annualise_pct", (n) => pct(n)) ? ` · ${fourchetteTxt(fo, "rendement_part_annualise_pct", (n) => pct(n))}` : ""}`} hex={C.projet} icon={PiggyBank} />
            <KPI label="Gain total" valeur={money(s.gain_total)} sous={`plus-value ${compact(s.plus_value)} · capital remboursé ${compact(s.capital_rembourse)} · cash ${compact(s.cash_flow_cumule - s.frais_fonds_cumules)}${s.cash_refi_total ? ` · refis ${compact(s.cash_refi_total)}` : ""}`} hex={C.gain} icon={TrendingUp} />
            <KPI label="Nos 3 holdings" valeur={`${pct(s.pct_nous_horizon)} du fonds`} sous={`${money(s.part_nous_total)} en parts de gains à l'horizon${fourchetteTxt(fo, "pct_nous_horizon", (n) => pct(n)) ? ` · ${fourchetteTxt(fo, "pct_nous_horizon", (n) => pct(n))}` : ""}`} hex={C.cash} icon={Wallet} />
            {remis ? (
              <KPI label="Remis aux investisseurs" valeur={money(s.distributions_total)} sous={`${s.nb_refinancements} refinancement${s.nb_refinancements > 1 ? "s" : ""} · ${compact(s.cash_refi_total)} sortis des refis · réserve ${money(s.cash_horizon)}`} hex={C.refi} icon={RefreshCw} />
            ) : (
              <KPI label="Cash du fonds" valeur={money(s.cash_horizon)} sous={`cash-flow cumulé ${compact(s.cash_flow_cumule)} − frais ${compact(s.frais_fonds_cumules)}${s.cash_refi_total ? ` + refis ${compact(s.cash_refi_total)}` : ""}`} hex={C.cash} icon={Wallet} />
            )}
          </div>

          <section className={`${CARD} overflow-hidden`} style={{ borderTop: `3px solid ${C.fonds}` }}>
            <Entete hex={C.fonds} icon={Landmark} titre="Le fonds, année par année" note={`Document p. 11 et 14 : VAN = valeur des immeubles + cash − dettes ; le gain de l'année = VAN de fin − VAN de début${remis ? " + cash remis aux investisseurs" : ""}, fait de la plus-value (loyers en hausse), du capital remboursé et du cash. Rendement du fonds = gain ÷ VAN de départ (plus le capital entré dans l'année).`} />
            <div className="space-y-4 p-4">
              <GraphiqueVAN annees={annees} vanDepart={s.van_depart} />
              <TableAnnees
                annees={annees}
                lignes={[
                  { label: "Revenus bruts", val: (a) => a.revenus_bruts },
                  { label: "Dépenses (barème SCHL)", val: (a) => a.depenses, sous: true },
                  { label: "Revenus nets", val: (a) => a.revenus_nets, fort: true },
                  { label: "Service de dette", val: (a) => a.service_dette },
                  { label: "dont capital remboursé", val: (a) => a.capital_rembourse, sous: true },
                  { label: "Frais de gestion du fonds", val: (a) => a.frais_fonds },
                  { label: "Cash de l'année", val: (a) => a.cash_net, fort: true, couleur: true, hex: C.cash },
                  { label: "Cash sorti aux refinancements", val: (a) => a.cash_refi || null, hex: C.refi, masquer: !s.nb_refinancements },
                  { label: "Remis aux investisseurs", val: (a) => a.distributions || null, fort: true, hex: C.refi, masquer: !remis },
                  { label: remis ? "Réserve de cash" : "Cash accumulé", val: (a) => a.cash, sous: true },
                  { label: "Valeur des immeubles", val: (a) => a.valeur },
                  { label: "Dettes", val: (a) => a.dettes },
                  { label: "Capital entré (acquisitions)", val: (a) => a.capital_entre || null },
                  { label: "VAN en fin d'année", val: (a) => a.van, fort: true, hex: C.fonds },
                  { label: "Gain de l'année", val: (a) => a.gain, fort: true, couleur: true },
                  { label: "plus-value", val: (a) => a.sources.plus_value, sous: true, couleur: true },
                  { label: "capital remboursé", val: (a) => a.sources.capital_rembourse, sous: true },
                  { label: remis ? "cash (remis + réserve)" : "cash gardé", val: (a) => a.sources.cash, sous: true, couleur: true },
                  { label: "Rendement du fonds", val: (a) => a.rendement_pct, fmt: (n) => pct(n, 2), fort: true, couleur: true, hex: C.gain }
                ]}
              />
            </div>
          </section>

          <section className={`${CARD} overflow-hidden`} style={{ borderTop: `3px solid ${C.gain}` }}>
            <Entete hex={C.gain} icon={PiggyBank} titre="Le partage en parts" note={`Document p. 7-8 : les premiers ${pct(perf.regles.seuil_investisseurs_pct)} du capital aux investisseurs, les ${pct(perf.regles.tranche_nous_pct)} suivants à nous, le reste ${pct(100 - perf.regles.part_nous_pct, 0)} / ${pct(perf.regles.part_nous_pct, 0)}. Les investisseurs gardent le même nombre de parts et le prix monte ; nous recevons de nouvelles parts au nouveau prix (${pct(perf.regles.part_nous_pct / 3, 0)} à chaque holding). L'argent de nos holdings est traité comme celui d'un investisseur (p. 9).${remis ? " Le cash remis revient par part et compte dans le rendement de la part." : ""}`} />
            <div className="p-4">
              <TableAnnees
                annees={annees}
                lignes={[
                  { label: "Gain à partager", val: (a) => a.gain, couleur: true },
                  { label: `1. Aux investisseurs (premiers ${pct(perf.regles.seuil_investisseurs_pct)})`, val: (a) => a.partage.tranche_investisseurs, sous: true },
                  { label: `2. À nous (${pct(perf.regles.tranche_nous_pct)} suivants)`, val: (a) => a.partage.tranche_nous, sous: true },
                  { label: "3. Le reste, partagé", val: (a) => a.partage.reste, sous: true },
                  { label: "Part des investisseurs", val: (a) => a.partage.part_investisseurs, fort: true },
                  { label: "Notre part (nouvelles parts)", val: (a) => a.partage.part_nous, fort: true, hex: C.gain },
                  { label: "Prix de la part", val: (a) => a.prix_part, fmt: (n) => money(n, 2), fort: true, hex: C.projet },
                  { label: "Cash remis par part", val: (a) => a.distribution_par_part || null, fmt: (n) => money(n, 2), sous: true, masquer: !remis },
                  { label: "Rendement de la part", val: (a) => a.rendement_part_pct, fmt: (n) => pct(n, 2), couleur: true },
                  { label: "Parts du fonds", val: (a) => a.parts_total, fmt: (n) => nb(n) },
                  { label: "dont entrées (capital)", val: (a) => a.parts_entrees || null, fmt: (n) => nb(n), sous: true },
                  { label: "Nouvelles parts à nous", val: (a) => a.nouvelles_parts_nous, fmt: (n) => nb(n), sous: true },
                  { label: "Nos parts, cumul", val: (a) => a.parts_nous, fmt: (n) => nb(n) },
                  { label: "Notre part du fonds", val: (a) => a.pct_nous, fmt: (n) => pct(n, 1), fort: true, hex: C.cash }
                ]}
              />
              <p className={`mt-2 text-[11px] ${FAINT}`}>Au départ : {nb(s.parts_depart)} parts à {money(s.prix_part_depart, 2)} ({money(s.van_depart)}), dont {pct(h.part_nos_holdings_depart_pct, 0)} à nos holdings. À l&apos;horizon : {nb(s.parts_horizon)} parts à {money(s.prix_part_horizon, 2)}, dont {nb(s.parts_nous_horizon)} à nous{remis ? ` ; ${money(s.distributions_par_part, 2)} de cash remis par part en chemin` : ""}.</p>
            </div>
          </section>

          <section className={`${CARD} overflow-hidden`} style={{ borderTop: `3px solid ${C.projet}` }}>
            <Entete hex={C.projet} icon={Building2} titre="Par projet" note="Chaque immeuble, année par année : loyers et dépenses indexés (barème SCHL), service de dette et capital remboursé prêt par prêt (hypothèques Kratos, ou la dette de la fiche), refinancements, valeur = revenus nets ÷ taux de cap, ou coût + plus-value linéaire en rénovation. Capital de départ = équité d'aujourd'hui, ou la mise pour une acquisition de l'année." />
            <div className="space-y-3 p-4">
              {perf.projets.map((p) => <CarteProjet key={p.id} p={p} />)}
              {!perf.projets.length ? <p className={`text-sm ${FAINT}`}>Aucun immeuble dans ce scénario.</p> : null}
              {perf.projets.length && !s.nb_immeubles ? <p className={`rounded-xl border border-dashed border-[var(--qg-border)] px-4 py-3 text-xs ${MUTED}`}>Aucun immeuble n&apos;est « dans le fonds » : le fonds reste à zéro. Coche « Dans le fonds » dans l&apos;onglet Revenus.</p> : null}
            </div>
          </section>

          <section className={`${CARD} overflow-hidden`} style={{ borderTop: `3px solid ${C.histo}` }}>
            <Entete hex={C.histo} icon={History} titre="Historique réel (à venir)" note="Pour montrer le passé comme le futur, il faut par immeuble : la date d'achat, le prêt initial quand il y a eu un refinancement, les travaux et frais payés par date, le cash sorti à chaque refi. Voici ce que Kratos a déjà et ce qui manque." />
            <div className="overflow-x-auto p-4">
              {perf.historique.length ? (
                <table className="w-full min-w-[640px] text-xs">
                  <thead className={`text-left ${FAINT}`}>
                    <tr>
                      <th className="py-1 pr-3 font-semibold uppercase tracking-wider">Immeuble</th>
                      <th className="py-1 pr-3 text-right font-semibold uppercase tracking-wider">Prix d&apos;achat</th>
                      <th className="py-1 pr-3 font-semibold uppercase tracking-wider">Date d&apos;achat</th>
                      <th className="py-1 pr-3 font-semibold uppercase tracking-wider">Prêts</th>
                      <th className="py-1 font-semibold uppercase tracking-wider">Il manque</th>
                    </tr>
                  </thead>
                  <tbody>
                    {perf.historique.map((x) => (
                      <tr key={x.id} className="border-t border-[var(--qg-border)] align-top">
                        <td className="py-1.5 pr-3 font-semibold">{x.nom}</td>
                        <td className={`py-1.5 pr-3 text-right tabular-nums ${x.prix_achat ? "" : "text-rose-400"}`}>{x.prix_achat ? money(x.prix_achat) : "manquant"}</td>
                        <td className={`py-1.5 pr-3 ${x.date_achat ? "" : "text-rose-400"}`}>{x.date_achat ? dateFr(x.date_achat) : "manquante"}</td>
                        <td className={`py-1.5 pr-3 ${MUTED}`}>{x.nb_prets} dans Kratos{x.premier_pret ? ` · premier : ${money(x.premier_pret.montant)} (${dateFr(x.premier_pret.date)})` : ""}{x.refinance ? " · refinancé" : ""}</td>
                        <td className="py-1.5 text-amber-300">{x.manques.length ? x.manques.join(" · ") : "rien, complet"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : (
                <p className={`text-sm ${FAINT}`}>Aucun immeuble lié à Kratos dans ce scénario.</p>
              )}
            </div>
          </section>
        </>
      ) : null}
    </div>
  );
}
