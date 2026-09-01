"use client";

/* Portail Investisseur v2 — briques UI partagées (portefeuille, fiche
   projet, aperçu admin). Graphiques SVG faits main (pas de lib), encre
   sur `currentColor` pour rester lisibles dans les deux thèmes. */

import { Fragment, useEffect, useMemo, useState } from "react";
import {
  ChevronDown,
  ChevronRight,
  Loader2,
  Paperclip
} from "lucide-react";

import { authedFetch } from "@/lib/auth";

/* ----------------------------- Types ----------------------------- */

export type ProjetCard = {
  entreprise_id: number;
  entreprise_name: string;
  color_accent: string | null;
  phase: string;
  adresse: string | null;
  nb_immeubles: number;
  nb_logements: number;
  cover_photo_url: string | null;
  parts_pct: number;
  valeur_parts: number;
  cashflow_moyen_part: number | null;
  statut: string;
  /** Vue globale admin seulement : nombre d'investisseurs au capital. */
  nb_investisseurs?: number;
  capital_investi_total: number;
  capital_rembourse: number;
  distributions_recues: number;
  capital_actuel: number;
  tri_pct: number | null;
  tvpi: number | null;
};

export type Portefeuille = {
  capital_actuel: number;
  capital_investi_total: number;
  capital_rembourse: number;
  distributions_recues: number;
  valeur_parts: number;
  tri_pct: number | null;
  tvpi: number | null;
  serie_valeur: { date: string; label: string; valeur: number }[];
  projets: ProjetCard[];
};

export type HypothequeRow = {
  id: number;
  rang: number | null;
  preteur: string | null;
  montant_initial: number | null;
  balance: number;
  taux_pct: number | null;
  type_taux: string | null;
  paiement_mensuel: number | null;
  amortissement_mois: number | null;
  date_debut: string | null;
  date_fin_terme: string | null;
};

export type ImmeubleRow = {
  immeuble_id: number;
  name: string;
  address: string | null;
  nb_logements: number;
  nb_baux_actifs: number;
  loyers_mensuels: number;
  loyers_potentiels?: number;
  valeur: number | null;
  valeur_source: string | null;
  valeur_date: string | null;
  hypotheque_balance: number;
  hypotheque_preteur: string | null;
  hypotheque_taux_pct: number | null;
  hypotheque_fin_terme: string | null;
  equite: number;
  ownership_pct: number;
  hypotheques?: HypothequeRow[];
};

export type SerieMois = {
  mois: string;
  label: string;
  revenus: number;
  depenses: number | null;
};

export type TimelineEvent = {
  date: string;
  kind: string;
  titre: string;
  description: string | null;
};

export type FluxRow = {
  id: number;
  type: string;
  label?: string;
  montant: number;
  date_flux: string;
  note: string | null;
  source?: string;
};

export type DepenseCategorie = { categorie: string; total: number };

export const CATEGORIE_LABELS: Record<string, string> = {
  taxes_municipales: "Taxes municipales",
  taxes_scolaires: "Taxes scolaires",
  assurances: "Assurances",
  energie: "Énergie",
  entretien: "Entretien & réparations",
  deneigement: "Déneigement",
  conciergerie: "Conciergerie",
  gestion: "Frais de gestion",
  autre: "Autres"
};

export type ProjetDetail = {
  entreprise_id: number;
  entreprise_name: string;
  description: string | null;
  phase: string;
  statut_participation: string;
  immeubles: ImmeubleRow[];
  valeur_totale: number;
  hypotheque_totale: number;
  avances_actionnaires?: number;
  depenses_par_categorie?: DepenseCategorie[];
  equite: number;
  loyers_mensuels: number;
  nb_logements: number;
  nb_baux_actifs: number;
  taux_occupation: number | null;
  serie_mensuelle: SerieMois[];
  /** "recus" = paiements enregistrés ; "potentiel" = loyers effectifs
   *  des unités louées (aucun paiement détaillé suivi). */
  revenus_mode?: "recus" | "potentiel";
  hypotheque_mensuelle: number | null;
  cashflow_moyen: number | null;
  timeline: TimelineEvent[];
  parts_pct: number;
  valeur_parts: number;
  capital_investi_total: number;
  capital_rembourse: number;
  distributions_recues: number;
  capital_actuel: number;
  tri_pct: number | null;
  tvpi: number | null;
  flux: FluxRow[];
  actionnaires: {
    name: string;
    parts_pct: number | null;
    is_me: boolean;
  }[];
  apports_synchronises?: boolean;
  show_depenses: boolean;
  show_hypotheque: boolean;
  show_actionnaires: boolean;
  show_cashflow: boolean;
  show_budget?: boolean;
  /** Dossier Google Drive partagé — affiché dans Documents. */
  drive_folder_url?: string | null;
  documents: { id: number; title: string; size_bytes: number }[];
};

/* --------------------------- Formats --------------------------- */

export function fmtMoney(v: number | null | undefined): string {
  if (v === null || v === undefined) return "—";
  return `${Math.round(v).toLocaleString("fr-CA")} $`;
}

export function fmtPct(v: number | null | undefined): string {
  if (v === null || v === undefined) return "—";
  return `${v.toLocaleString("fr-CA", { maximumFractionDigits: 1 })} %`;
}

export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(`${iso.slice(0, 10)}T12:00:00`).toLocaleDateString(
    "fr-CA",
    { day: "numeric", month: "short", year: "numeric" }
  );
}

/** Mode « voir comme » : /investisseur?apercu=<userId> (admin). Lu via
 *  window.location pour éviter le Suspense de useSearchParams. */
export function useApercu(): number | null {
  const [uid, setUid] = useState<number | null>(null);
  useEffect(() => {
    const p = new URLSearchParams(window.location.search).get("apercu");
    setUid(p ? Number(p) || null : null);
  }, []);
  return uid;
}

/* Aperçu « avant création du compte » : ?apercu_p=<partner_id>
   (ligne Parts & actionnaires) — le portail se rend tel que cet
   actionnaire le verra une fois son compte créé. */
export function useApercuPartenaire(): number | null {
  const [pid, setPid] = useState<number | null>(null);
  useEffect(() => {
    const p = new URLSearchParams(window.location.search).get(
      "apercu_p"
    );
    setPid(p ? Number(p) || null : null);
  }, []);
  return pid;
}

export function investApiBase(apercuUserId: number | null): string {
  return apercuUserId
    ? `/api/v1/invest/admin/apercu/${apercuUserId}`
    : "/api/v1/invest/me";
}

/* --------------------------- Badges --------------------------- */

export function PhaseBadge({ phase }: { phase: string }) {
  if (phase === "optimisation") {
    return (
      <span className="inline-flex items-center rounded-full border border-sky-500/50 bg-sky-500/15 px-2.5 py-0.5 text-[10.5px] font-bold uppercase tracking-wider text-sky-400">
        Optimisation
      </span>
    );
  }
  return (
    <span className="inline-flex items-center rounded-full border border-accent-500/50 bg-accent-500/10 px-2.5 py-0.5 text-[10.5px] font-bold uppercase tracking-wider text-accent-500">
      Détention long terme
    </span>
  );
}

/* ------------------------ Graphique valeur ------------------------ */

export function ValueChart({
  serie
}: {
  serie: { label: string; valeur: number }[];
}) {
  if (serie.length < 2) return null;
  const W = 900;
  const H = 230;
  const padL = 66;
  const padR = 20;
  const padT = 26;
  const padB = 30;
  const vals = serie.map((p) => p.valeur);
  const maxV = Math.max(...vals, 1);
  const minV = Math.min(...vals, 0);
  const span = Math.max(maxV - minV, 1);
  const x = (i: number) =>
    padL + (i / (serie.length - 1)) * (W - padL - padR);
  const y = (v: number) =>
    padT + (1 - (v - minV) / span) * (H - padT - padB);
  const pts = serie.map((p, i) => `${x(i)},${y(p.valeur)}`).join(" ");
  const area = `M${pts.split(" ").join(" L")} L${x(serie.length - 1)},${
    H - padB
  } L${x(0)},${H - padB} Z`;
  const gridYs = [0.25, 0.5, 0.75].map(
    (f) => padT + f * (H - padT - padB)
  );
  const last = serie[serie.length - 1];
  const xLabels = [
    0,
    Math.floor((serie.length - 1) / 2),
    serie.length - 1
  ];

  return (
    <div className="overflow-x-auto">
      <svg
        viewBox={`0 0 ${W} ${H}`}
        width="100%"
        style={{ minWidth: 560 }}
        role="img"
        aria-label={`Évolution de la valeur totale, dernier point ${fmtMoney(
          last.valeur
        )}`}
      >
        <defs>
          <linearGradient id="invArea" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#c98500" stopOpacity="0.28" />
            <stop offset="100%" stopColor="#c98500" stopOpacity="0" />
          </linearGradient>
        </defs>
        <g stroke="rgba(128,138,160,0.25)" strokeWidth="1">
          {gridYs.map((gy) => (
            <line key={gy} x1={padL} y1={gy} x2={W - padR} y2={gy} />
          ))}
          <line
            x1={padL}
            y1={H - padB}
            x2={W - padR}
            y2={H - padB}
          />
        </g>
        <path d={area} fill="url(#invArea)" stroke="none" />
        <polyline
          points={pts}
          fill="none"
          stroke="#c98500"
          strokeWidth="2.5"
          strokeLinejoin="round"
        />
        <circle
          cx={x(serie.length - 1)}
          cy={y(last.valeur)}
          r="5"
          fill="#c98500"
          stroke="rgba(0,0,0,0.4)"
          strokeWidth="2"
        />
        <text
          x={x(serie.length - 1) - 6}
          y={y(last.valeur) - 12}
          textAnchor="end"
          fontSize="13"
          fontWeight="700"
          fill="currentColor"
        >
          {fmtMoney(last.valeur)}
        </text>
        <g fontSize="11" fill="currentColor" opacity="0.55">
          {xLabels.map((i) => (
            <text
              key={i}
              x={x(i)}
              y={H - 8}
              textAnchor={
                i === 0
                  ? "start"
                  : i === serie.length - 1
                  ? "end"
                  : "middle"
              }
            >
              {serie[i].label}
            </text>
          ))}
          <text x={padL - 8} y={padT + 4} textAnchor="end">
            {fmtMoney(maxV)}
          </text>
          <text x={padL - 8} y={H - padB + 4} textAnchor="end">
            {fmtMoney(minV)}
          </text>
        </g>
      </svg>
    </div>
  );
}

/* -------------------- Graphique revenus/dépenses -------------------- */

export function RevDepChart({
  serie,
  showDepenses
}: {
  serie: SerieMois[];
  showDepenses: boolean;
}) {
  if (serie.length === 0) return null;
  const W = 900;
  const H = 220;
  const padL = 56;
  const padR = 14;
  const padT = 16;
  const padB = 28;
  const maxV = Math.max(
    ...serie.map((r) => Math.max(r.revenus, r.depenses ?? 0)),
    1
  );
  const innerW = W - padL - padR;
  const step = innerW / serie.length;
  const barW = showDepenses
    ? Math.min(24, (step - 10) / 2)
    : Math.min(34, step - 12);
  const y = (v: number) => padT + (1 - v / maxV) * (H - padT - padB);

  return (
    <div className="overflow-x-auto">
      <svg
        viewBox={`0 0 ${W} ${H}`}
        width="100%"
        style={{ minWidth: 560 }}
        role="img"
        aria-label="Revenus perçus et dépenses des 12 derniers mois"
      >
        <g stroke="rgba(128,138,160,0.25)" strokeWidth="1">
          {[0.25, 0.5, 0.75].map((f) => {
            const gy = padT + f * (H - padT - padB);
            return (
              <line key={f} x1={padL} y1={gy} x2={W - padR} y2={gy} />
            );
          })}
          <line x1={padL} y1={H - padB} x2={W - padR} y2={H - padB} />
        </g>
        {serie.map((r, i) => {
          const cx = padL + i * step + step / 2;
          const revX = showDepenses ? cx - barW - 1 : cx - barW / 2;
          return (
            <g key={r.mois}>
              <rect
                x={revX}
                y={y(r.revenus)}
                width={barW}
                height={Math.max(0, H - padB - y(r.revenus))}
                rx="3"
                fill="#199e70"
              >
                <title>{`${r.label} — revenus perçus ${fmtMoney(
                  r.revenus
                )}`}</title>
              </rect>
              {showDepenses && r.depenses !== null ? (
                <rect
                  x={cx + 1}
                  y={y(r.depenses)}
                  width={barW}
                  height={Math.max(0, H - padB - y(r.depenses))}
                  rx="3"
                  fill="#e66767"
                >
                  <title>{`${r.label} — dépenses ${fmtMoney(
                    r.depenses
                  )}`}</title>
                </rect>
              ) : null}
              <text
                x={cx}
                y={H - 8}
                textAnchor="middle"
                fontSize="10"
                fill="currentColor"
                opacity="0.55"
              >
                {r.label.slice(0, 1).toUpperCase()}
              </text>
            </g>
          );
        })}
        <g fontSize="11" fill="currentColor" opacity="0.55">
          <text x={padL - 8} y={padT + 4} textAnchor="end">
            {fmtMoney(maxV)}
          </text>
          <text x={padL - 8} y={H - padB + 4} textAnchor="end">
            0
          </text>
        </g>
      </svg>
    </div>
  );
}

/* --------------------------- Timeline --------------------------- */

const KIND_DOT: Record<string, string> = {
  acquisition: "border-accent-500",
  optimisation: "border-sky-500",
  refinancement: "border-accent-500",
  phase: "border-emerald-500",
  autre: "border-white/40"
};

export function Timeline({ events }: { events: TimelineEvent[] }) {
  return (
    <ul className="ml-1 space-y-0">
      {events.map((e, i) => (
        <li key={`${e.date}-${i}`} className="relative pb-6 pl-7 last:pb-0">
          {i < events.length - 1 ? (
            <span className="absolute bottom-0 left-[5px] top-2 w-0.5 bg-brand-800" />
          ) : null}
          <span
            className={`absolute left-0 top-1.5 h-3 w-3 rounded-full border-[3px] bg-brand-950 ${
              KIND_DOT[e.kind] || KIND_DOT.autre
            }`}
          />
          <p className="text-[11px] font-bold uppercase tracking-wider text-white/40">
            {fmtDate(e.date)}
          </p>
          <p className="text-sm font-semibold text-white">{e.titre}</p>
          {e.description ? (
            <p className="text-xs text-white/60">{e.description}</p>
          ) : null}
        </li>
      ))}
    </ul>
  );
}

/* ----------------- Dépenses par catégorie (12 mois) ----------------- */

// Ordre LOGIQUE des catégories (retour investisseur 2026-09-02 : les
// deux taxes en premier — municipales puis scolaires — et « Autres »
// à la fin), plutôt qu'un tri par montant.
const CATEGORIE_ORDRE: Record<string, number> = {
  taxes_municipales: 0,
  taxes_scolaires: 1,
  assurances: 2,
  energie: 3,
  entretien: 4,
  deneigement: 5,
  conciergerie: 6,
  gestion: 7,
  autre: 99
};

export function DepensesParCategorie({
  items
}: {
  items: DepenseCategorie[];
}) {
  if (!items || items.length === 0) return null;
  const total = items.reduce((s, x) => s + x.total, 0);
  if (total <= 0) return null;
  const ordonnes = [...items].sort(
    (a, b) =>
      (CATEGORIE_ORDRE[a.categorie] ?? 50) -
        (CATEGORIE_ORDRE[b.categorie] ?? 50) || b.total - a.total
  );
  return (
    <div className="mt-3 border-t border-brand-800 pt-3">
      <p className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-white/40">
        Dépenses par catégorie · 12 mois
      </p>
      <ul className="space-y-1.5">
        {ordonnes.map((d) => {
          const pct = Math.max(2, Math.round((d.total / total) * 100));
          return (
            <li key={d.categorie} className="text-xs">
              <div className="mb-0.5 flex items-baseline justify-between gap-2">
                <span className="text-white/70">
                  {CATEGORIE_LABELS[d.categorie] || d.categorie}
                </span>
                <span className="font-semibold tabular-nums text-white">
                  {fmtMoney(d.total)}
                </span>
              </div>
              <div className="h-1.5 overflow-hidden rounded-full bg-brand-800/60">
                <div
                  className="h-full rounded-full bg-[#e66767]"
                  style={{ width: `${pct}%` }}
                />
              </div>
            </li>
          );
        })}
      </ul>
      <p className="mt-1.5 text-right text-[11px] text-white/40 tabular-nums">
        Total : {fmtMoney(total)} / an
      </p>
    </div>
  );
}

/* --------------------- Section Hypothèques --------------------- */

export function HypothequesCard({
  immeubles
}: {
  immeubles: ImmeubleRow[];
}) {
  const rows = immeubles.flatMap((im) =>
    (im.hypotheques || []).map((h) => ({ im, h }))
  );
  return (
    <div className="rounded-2xl border border-brand-800 bg-brand-900 p-4">
      <h2 className="mb-3 text-sm font-semibold text-white">Hypothèques</h2>
      {rows.length === 0 ? (
        <p className="text-xs text-white/40">
          Aucune hypothèque active sur les immeubles de la compagnie.
        </p>
      ) : (
        <div className="space-y-3">
          {rows.map(({ im, h }) => (
            <div
              key={h.id}
              className="rounded-xl border border-brand-800 bg-brand-950/50 p-3"
            >
              <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
                <p className="text-sm font-semibold text-white">
                  {h.preteur || "Créancier —"}
                  {h.rang && h.rang > 1 ? (
                    <span className="ml-1.5 text-xs font-normal text-white/40">
                      {h.rang}ᵉ rang
                    </span>
                  ) : null}
                </p>
                <p className="text-xs text-white/40">
                  {im.address || im.name}
                </p>
              </div>
              <dl className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-xs tabular-nums sm:grid-cols-3">
                <div>
                  <dt className="text-white/40">Solde actuel</dt>
                  <dd className="font-bold text-white">
                    {fmtMoney(h.balance)}
                  </dd>
                </div>
                <div>
                  <dt className="text-white/40">Solde de départ</dt>
                  <dd className="font-semibold text-white/80">
                    {fmtMoney(h.montant_initial)}
                  </dd>
                </div>
                <div>
                  <dt className="text-white/40">Taux</dt>
                  <dd className="font-semibold text-white/80">
                    {h.taux_pct !== null
                      ? `${h.taux_pct.toLocaleString("fr-CA", {
                          maximumFractionDigits: 2
                        })} %${
                          h.type_taux ? ` (${h.type_taux})` : ""
                        }`
                      : "—"}
                  </dd>
                </div>
                <div>
                  <dt className="text-white/40">Paiement</dt>
                  <dd className="font-semibold text-white/80">
                    {h.paiement_mensuel !== null
                      ? `${fmtMoney(h.paiement_mensuel)}/mois`
                      : "—"}
                  </dd>
                </div>
                <div>
                  <dt className="text-white/40">Fin du terme</dt>
                  <dd className="font-semibold text-white/80">
                    {fmtDate(h.date_fin_terme)}
                  </dd>
                </div>
                <div>
                  <dt className="text-white/40">Amortissement</dt>
                  <dd className="font-semibold text-white/80">
                    {h.amortissement_mois
                      ? `${Math.round(h.amortissement_mois / 12)} ans`
                      : "—"}
                  </dd>
                </div>
              </dl>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/* ------------- Filtre de période partagé (par année) ------------- */

function anneesDe(labels: string[]): string[] {
  return Array.from(
    new Set(labels.map((l) => /(\d{4})/.exec(l)?.[1] || ""))
  )
    .filter(Boolean)
    .sort()
    .reverse();
}

function PeriodeSelect({
  annees,
  value,
  onChange
}: {
  annees: string[];
  value: string;
  onChange: (v: string) => void;
}) {
  if (annees.length < 2) return null;
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className="input w-auto text-xs"
      title="Filtrer par période"
    >
      <option value="12m">12 derniers mois</option>
      {annees.map((a) => (
        <option key={a} value={a}>
          {a}
        </option>
      ))}
      <option value="">Depuis le début</option>
    </select>
  );
}

/* ------- Revenus & dépenses NORMALISÉS (pôle locatif) ------- */

export function NormalisesPanel({
  serie,
  revenusMode,
  cashflowMoyen,
  depensesParCategorie,
  showDepenses,
  showCashflow
}: {
  serie: SerieMois[];
  revenusMode?: "recus" | "potentiel";
  cashflowMoyen: number | null;
  depensesParCategorie?: DepenseCategorie[];
  showDepenses: boolean;
  showCashflow: boolean;
}) {
  const [periode, setPeriode] = useState("12m");
  const annees = useMemo(
    () => anneesDe(serie.map((r) => r.mois)),
    [serie]
  );
  const vue = useMemo(() => {
    if (periode === "12m") return serie.slice(-12);
    if (!periode) return serie;
    return serie.filter((r) => r.mois.startsWith(periode));
  }, [serie, periode]);
  const totaux = useMemo(
    () => ({
      revenus: vue.reduce((s, r) => s + r.revenus, 0),
      depenses: vue.reduce((s, r) => s + (r.depenses ?? 0), 0)
    }),
    [vue]
  );

  return (
    <div className="rounded-2xl border border-brand-800 bg-brand-900 p-4 text-white">
      <div className="mb-1 flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-sm font-semibold">
          Revenus et dépenses normalisés
        </h2>
        <PeriodeSelect
          annees={annees}
          value={periode}
          onChange={setPeriode}
        />
      </div>
      <p className="mb-2 text-[11px] text-white/35">
        Pôle gestion locative — loyers et dépenses récurrentes.
        {showCashflow && cashflowMoyen !== null ? (
          <>
            {" "}
            Cash-flow moyen :{" "}
            <b
              className={
                cashflowMoyen >= 0 ? "text-emerald-400" : "text-rose-400"
              }
            >
              {cashflowMoyen >= 0 ? "+" : ""}
              {fmtMoney(cashflowMoyen)}/mois
            </b>
          </>
        ) : null}
      </p>
      <RevDepChart serie={vue} showDepenses={showDepenses} />
      <div className="mt-1 flex flex-wrap gap-4 text-xs text-white/50">
        <span className="inline-flex items-center gap-1.5">
          <i className="inline-block h-2.5 w-2.5 rounded-sm bg-[#199e70]" />
          {revenusMode === "potentiel"
            ? "Loyers (unités louées — paiements détaillés non suivis)"
            : "Revenus perçus"}
        </span>
        {showDepenses ? (
          <span className="inline-flex items-center gap-1.5">
            <i className="inline-block h-2.5 w-2.5 rounded-sm bg-[#e66767]" />
            Dépenses
          </span>
        ) : null}
        <span className="ml-auto tabular-nums text-white/40">
          Période : {fmtMoney(totaux.revenus)}
          {showDepenses ? ` − ${fmtMoney(totaux.depenses)}` : ""}
        </span>
      </div>
      {showDepenses && depensesParCategorie ? (
        <DepensesParCategorie items={depensesParCategorie} />
      ) : null}
    </div>
  );
}

/* ------- Revenus & dépenses RÉELS (QuickBooks — optimisation) ------- */

export type QboReelsRow = {
  mois: string;
  debut?: string | null;
  fin?: string | null;
  revenus: number;
  depenses: number;
  hypotheque?: number;
  ecart: number;
  details?: {
    nom: string;
    compte_id?: string | null;
    type: string;
    montant: number;
  }[];
};

export type QboReels = {
  statut:
    | "aucun_projet"
    | "sans_qbo"
    | "erreur"
    | "connecte"
    | "masque";
  projet_nom?: string;
  erreur?: string;
  rows?: QboReelsRow[];
  total?: {
    revenus: number;
    depenses: number;
    hypotheque?: number;
    ecart: number;
  } | null;
};

type QboTxnPiece = {
  att_id: string;
  file_name: string | null;
  content_type: string | null;
};

type QboTxnRow = {
  txn_type: string;
  txn_id: string;
  date: string | null;
  fournisseur: string | null;
  doc_number: string | null;
  montant_impute: number;
  montant_total: number;
  description: string | null;
  pieces: QboTxnPiece[];
};

/* Transactions QuickBooks d'un compte de dépense pour un mois cliqué
   dans « Revenus et dépenses réels », avec les factures jointes servies
   en direct — même principe que la page Optimisation. */
function TransactionsReellesModal({
  titre,
  fetchUrl,
  pieceBase,
  onClose
}: {
  titre: string;
  fetchUrl: string;
  pieceBase: string;
  onClose: () => void;
}) {
  const [rows, setRows] = useState<QboTxnRow[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [pieceBusy, setPieceBusy] = useState<string | null>(null);

  useEffect(() => {
    void (async () => {
      try {
        const r = await authedFetch(fetchUrl);
        if (!r.ok) {
          const j = (await r.json().catch(() => null)) as {
            detail?: string;
          } | null;
          throw new Error(j?.detail || `HTTP ${r.status}`);
        }
        setRows((await r.json()) as QboTxnRow[]);
      } catch (e) {
        setErr((e as Error).message);
      }
    })();
  }, [fetchUrl]);

  async function ouvrirPiece(pc: QboTxnPiece) {
    setPieceBusy(pc.att_id);
    try {
      const params = new URLSearchParams();
      if (pc.content_type) params.set("ct", pc.content_type);
      if (pc.file_name) params.set("nom", pc.file_name);
      const r = await authedFetch(
        `${pieceBase}/${pc.att_id}?${params.toString()}`
      );
      if (!r.ok) {
        const j = (await r.json().catch(() => null)) as {
          detail?: string;
        } | null;
        throw new Error(j?.detail || `HTTP ${r.status}`);
      }
      const url = URL.createObjectURL(await r.blob());
      window.open(url, "_blank");
      window.setTimeout(() => URL.revokeObjectURL(url), 60000);
    } catch (e) {
      setErr(`Pièce : ${(e as Error).message}`);
    } finally {
      setPieceBusy(null);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4"
      onClick={onClose}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="max-h-[80vh] w-full max-w-3xl overflow-y-auto rounded-2xl border border-brand-800 bg-brand-900 p-4 text-white"
      >
        <div className="mb-3 flex items-center justify-between gap-2">
          <h3 className="text-sm font-semibold">
            Transactions QuickBooks — {titre}
          </h3>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-brand-700 px-2.5 py-1 text-xs text-white/70 transition hover:text-white"
          >
            Fermer
          </button>
        </div>
        {err ? (
          <p className="mb-2 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-400">
            {err}
          </p>
        ) : null}
        {rows === null && !err ? (
          <p className="py-6 text-center text-xs text-white/40">
            Chargement depuis QuickBooks…
          </p>
        ) : rows !== null && rows.length === 0 ? (
          <p className="py-6 text-center text-xs text-white/40">
            Aucune transaction sur ce compte pour cette période.
          </p>
        ) : rows !== null ? (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[620px] text-left text-[13px]">
              <thead className="text-[10px] uppercase tracking-wider text-white/40">
                <tr>
                  <th className="pb-2 pr-2">Date</th>
                  <th className="pb-2 pr-2">Fournisseur</th>
                  <th className="pb-2 pr-2">Description</th>
                  <th className="pb-2 pr-2 text-right">Montant</th>
                  <th className="pb-2 text-right">Facture</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((t) => (
                  <tr
                    key={`${t.txn_type}-${t.txn_id}`}
                    className="border-t border-brand-800/60"
                  >
                    <td className="py-1.5 pr-2 whitespace-nowrap text-white/80">
                      {t.date || "—"}
                    </td>
                    <td className="py-1.5 pr-2 text-white/80">
                      {t.fournisseur || "—"}
                      {t.doc_number ? (
                        <span className="ml-1 text-[11px] text-white/40">
                          #{t.doc_number}
                        </span>
                      ) : null}
                    </td>
                    <td
                      className="max-w-[220px] truncate py-1.5 pr-2 text-[12px] text-white/50"
                      title={t.description || undefined}
                    >
                      {t.description || "—"}
                    </td>
                    <td
                      className="py-1.5 pr-2 text-right tabular-nums text-white"
                      title={
                        t.montant_impute !== t.montant_total
                          ? `Part de ce compte : ${fmtMoney(t.montant_impute)} — transaction totale : ${fmtMoney(t.montant_total)}`
                          : undefined
                      }
                    >
                      {fmtMoney(t.montant_impute)}
                    </td>
                    <td className="py-1.5 text-right">
                      {t.pieces.length === 0 ? (
                        <span
                          className="text-[11px] text-white/35"
                          title="Aucune pièce jointe sur ce document dans QuickBooks"
                        >
                          —
                        </span>
                      ) : (
                        t.pieces.map((pc) => (
                          <button
                            key={pc.att_id}
                            type="button"
                            disabled={pieceBusy === pc.att_id}
                            onClick={() => void ouvrirPiece(pc)}
                            className="ml-1 inline-flex items-center gap-1 rounded-md border border-brand-700 px-1.5 py-0.5 text-[11px] text-white/80 transition hover:text-white disabled:opacity-40"
                            title={pc.file_name || "Ouvrir la pièce jointe"}
                          >
                            <Paperclip className="h-3 w-3" />
                            {pieceBusy === pc.att_id ? "…" : "Ouvrir"}
                          </button>
                        ))
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="mt-2 text-[10px] text-white/35">
              Les factures ponctuelles (travaux, réparations…) sont
              jointes à leurs transactions. Les factures récurrentes
              (électricité, assurances, télécommunications…) ne sont
              pas déposées systématiquement — elles demeurent
              disponibles sur demande.
            </p>
          </div>
        ) : null}
      </div>
    </div>
  );
}


export function QboReelsPanel({ fetchPath }: { fetchPath: string }) {
  const [reels, setReels] = useState<QboReels | null>(null);
  const [failed, setFailed] = useState(false);
  const [periode, setPeriode] = useState("12m");
  const [ouverts, setOuverts] = useState<Set<string>>(new Set());
  //: Compte de dépense cliqué → transactions + factures du mois.
  const [txnCompte, setTxnCompte] = useState<{
    titre: string;
    url: string;
  } | null>(null);
  //: Les routes transactions/pièces vivent à côté de qbo-reels (même
  //: base me/… ou admin/…).
  const baseProjet = fetchPath.replace(/\/qbo-reels$/, "");

  useEffect(() => {
    let cancelled = false;
    authedFetch(fetchPath)
      .then(async (res) => {
        if (cancelled) return;
        if (!res.ok) {
          setFailed(true);
          return;
        }
        setReels((await res.json()) as QboReels);
      })
      .catch(() => {
        if (!cancelled) setFailed(true);
      });
    return () => {
      cancelled = true;
    };
  }, [fetchPath]);

  const rows = useMemo(() => reels?.rows || [], [reels]);
  const annees = useMemo(
    () => anneesDe(rows.map((r) => r.mois)),
    [rows]
  );
  const vue = useMemo(() => {
    if (periode === "12m") return rows.slice(-12);
    if (!periode) return rows;
    return rows.filter(
      (r) => (/(\d{4})/.exec(r.mois)?.[1] || "") === periode
    );
  }, [rows, periode]);
  // Total RECALCULÉ sur les mois affichés (celui du backend couvre
  // toute la période).
  const total = useMemo(() => {
    const somme = (f: (r: QboReelsRow) => number) =>
      Math.round(vue.reduce((s, r) => s + f(r), 0) * 100) / 100;
    return {
      revenus: somme((r) => r.revenus),
      depenses: somme((r) => r.depenses),
      hypotheque: somme((r) => r.hypotheque || 0),
      ecart: somme((r) => r.ecart)
    };
  }, [vue]);
  const showHyp = vue.some((r) => Math.abs(r.hypotheque || 0) >= 0.01);
  const hasDetails = vue.some((r) => (r.details || []).length > 0);

  function basculer(cle: string) {
    setOuverts((prev) => {
      const next = new Set(prev);
      if (next.has(cle)) next.delete(cle);
      else next.add(cle);
      return next;
    });
  }

  const naBox = (titre: string, texte: string) => (
    <div className="rounded-xl border border-dashed border-brand-700 bg-brand-950/40 px-4 py-6 text-center">
      <p className="text-sm font-semibold text-white/70">{titre}</p>
      <p className="mx-auto mt-1 max-w-sm text-xs text-white/40">
        {texte}
      </p>
    </div>
  );

  function DetailsRow({
    details,
    colSpan,
    debut,
    fin
  }: {
    details: {
      nom: string;
      compte_id?: string | null;
      type: string;
      montant: number;
    }[];
    colSpan: number;
    debut?: string | null;
    fin?: string | null;
  }) {
    if (!details.length) return null;
    return (
      <tr>
        <td colSpan={colSpan} className="pb-2">
          <div className="ml-3 space-y-0.5 border-l border-brand-800 pl-3">
            {details.map((d, i) => (
              <div
                key={i}
                className="flex items-center justify-between gap-2 text-[11px]"
              >
                {d.type === "depense" && d.compte_id && debut && fin ? (
                  <button
                    type="button"
                    onClick={() =>
                      setTxnCompte({
                        titre: d.nom,
                        url: `${baseProjet}/qbo-comptes/${d.compte_id}/transactions?debut=${debut}&fin=${fin}`
                      })
                    }
                    className="text-left text-white/50 underline decoration-dotted underline-offset-2 transition hover:text-white/80"
                    title="Voir les transactions de ce compte pour ce mois (et leurs factures)"
                  >
                    {d.nom}
                  </button>
                ) : (
                  <span className="text-white/50">{d.nom}</span>
                )}
                <span
                  className={`tabular-nums ${
                    d.type === "revenu"
                      ? "text-emerald-400"
                      : "text-rose-400"
                  }`}
                >
                  {d.type === "revenu" ? "+" : "−"}
                  {fmtMoney(Math.abs(d.montant))}
                </span>
              </div>
            ))}
          </div>
        </td>
      </tr>
    );
  }

  if (reels?.statut === "masque") return null;

  const nbCols = 3 + (showHyp ? 1 : 0) + 1;

  return (
    <div className="rounded-2xl border border-brand-800 bg-brand-900 p-4 text-white">
      <div className="mb-1 flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-sm font-semibold">
          Revenus et dépenses réels
        </h2>
        {reels?.statut === "connecte" ? (
          <PeriodeSelect
            annees={annees}
            value={periode}
            onChange={setPeriode}
          />
        ) : null}
      </div>
      <p className="mb-3 text-[11px] text-white/35">
        Importations QuickBooks du projet lié dans la section
        optimisation (gestion d&apos;entreprise)
        {reels?.statut === "connecte" && reels.projet_nom
          ? ` — ${reels.projet_nom}`
          : ""}
        {hasDetails
          ? " — cliquez un mois pour le détail par compte, puis un compte de dépense pour ses transactions et factures"
          : ""}
        .
      </p>

      {failed ? (
        naBox(
          "Chargement impossible",
          "Les données réelles n'ont pas pu être chargées — réessayez plus tard."
        )
      ) : reels === null ? (
        <div className="flex justify-center py-10">
          <Loader2 className="h-5 w-5 animate-spin text-accent-500" />
        </div>
      ) : reels.statut === "aucun_projet" ? (
        naBox(
          "Non applicable — pas encore rentré",
          "Cette compagnie n'a aucun projet dans la section optimisation " +
            "de gestion d'entreprise. Créez-y le projet et connectez " +
            "QuickBooks pour voir les chiffres réels ici."
        )
      ) : reels.statut === "sans_qbo" ? (
        naBox(
          "QuickBooks non connecté",
          `Le projet « ${reels.projet_nom} » existe dans la section ` +
            "optimisation, mais aucune connexion QuickBooks n'est " +
            "choisie dans ses réglages."
        )
      ) : reels.statut === "erreur" ? (
        naBox(
          "Lecture QuickBooks impossible",
          reels.erreur ||
            "Erreur de lecture — vérifiez la connexion QuickBooks dans la section optimisation."
        )
      ) : vue.length === 0 ? (
        naBox(
          "Aucune donnée sur la période",
          "QuickBooks est connecté mais le rapport est vide pour cette période."
        )
      ) : (
        <div className="max-h-[420px] overflow-y-auto overflow-x-auto">
          <table className="w-full min-w-[420px] text-xs tabular-nums">
            <thead className="sticky top-0 bg-brand-900">
              <tr className="text-left text-[10px] uppercase tracking-wider text-white/40">
                <th className="py-1.5 pr-2 font-medium">Mois</th>
                <th className="py-1.5 pl-2 text-right font-medium">
                  Revenus
                </th>
                <th className="py-1.5 pl-2 text-right font-medium">
                  Dépenses
                </th>
                {showHyp ? (
                  <th className="py-1.5 pl-2 text-right font-medium">
                    Hypothèque
                  </th>
                ) : null}
                <th className="py-1.5 pl-2 text-right font-medium">
                  Écart
                </th>
              </tr>
            </thead>
            <tbody>
              {vue.map((r) => (
                <Fragment key={r.mois}>
                  <tr
                    className={`border-t border-brand-800/60 ${
                      (r.details || []).length
                        ? "cursor-pointer hover:bg-white/[0.03]"
                        : ""
                    }`}
                    onClick={() =>
                      (r.details || []).length && basculer(r.mois)
                    }
                    title={
                      (r.details || []).length
                        ? "Cliquer pour voir le détail par compte"
                        : undefined
                    }
                  >
                    <td className="py-1.5 pr-2 text-white/70">
                      <span className="inline-flex items-center gap-1">
                        {(r.details || []).length ? (
                          ouverts.has(r.mois) ? (
                            <ChevronDown className="h-3 w-3 opacity-50" />
                          ) : (
                            <ChevronRight className="h-3 w-3 opacity-50" />
                          )
                        ) : null}
                        {r.mois}
                      </span>
                    </td>
                    <td className="py-1.5 pl-2 text-right text-white/80">
                      {fmtMoney(r.revenus)}
                    </td>
                    <td className="py-1.5 pl-2 text-right text-white/80">
                      {fmtMoney(r.depenses)}
                    </td>
                    {showHyp ? (
                      <td className="py-1.5 pl-2 text-right text-white/80">
                        {fmtMoney(r.hypotheque || 0)}
                      </td>
                    ) : null}
                    <td
                      className={`py-1.5 pl-2 text-right font-semibold ${
                        r.ecart >= 0
                          ? "text-emerald-400"
                          : "text-rose-400"
                      }`}
                    >
                      {r.ecart >= 0 ? "+" : ""}
                      {fmtMoney(r.ecart)}
                    </td>
                  </tr>
                  {ouverts.has(r.mois) ? (
                    <DetailsRow
                      details={r.details || []}
                      colSpan={nbCols}
                      debut={r.debut}
                      fin={r.fin}
                    />
                  ) : null}
                </Fragment>
              ))}
              <tr className="border-t-2 border-brand-700 font-semibold">
                <td className="py-2 pr-2 text-white">TOTAL</td>
                <td className="py-2 pl-2 text-right text-white">
                  {fmtMoney(total.revenus)}
                </td>
                <td className="py-2 pl-2 text-right text-white">
                  {fmtMoney(total.depenses)}
                </td>
                {showHyp ? (
                  <td className="py-2 pl-2 text-right text-white">
                    {fmtMoney(total.hypotheque)}
                  </td>
                ) : null}
                <td
                  className={`py-2 pl-2 text-right ${
                    total.ecart >= 0
                      ? "text-emerald-400"
                      : "text-rose-400"
                  }`}
                >
                  {total.ecart >= 0 ? "+" : ""}
                  {fmtMoney(total.ecart)}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      )}
      {txnCompte ? (
        <TransactionsReellesModal
          titre={txnCompte.titre}
          fetchUrl={txnCompte.url}
          pieceBase={`${baseProjet}/qbo-pieces`}
          onClose={() => setTxnCompte(null)}
        />
      ) : null}
    </div>
  );
}


export type BudgetInvest = {
  statut: string;
  projet_nom?: string;
  erreur?: string;
  date_debut?: string | null;
  lignes?: {
    ligne_id: number;
    nom: string;
    mode?: string | null;
    budget: number;
    depense: number | null;
    reste: number | null;
  }[];
  total?: { budget: number; depense: number; reste: number };
};

/* Budget du projet d'optimisation, vu du portail : chaque enveloppe
   avec son budget, le dépensé réel QuickBooks et le reste — « où
   est-ce que leur argent a été dépensé » (Phil, 2026-08-25). Le
   montant dépensé s'ouvre sur les transactions + factures. */
export function BudgetOptimisationPanel({
  fetchPath
}: {
  fetchPath: string;
}) {
  const [data, setData] = useState<BudgetInvest | null>(null);
  const [failed, setFailed] = useState(false);
  const [txnLigne, setTxnLigne] = useState<{
    titre: string;
    url: string;
  } | null>(null);
  //: Les routes transactions/pièces vivent à côté de /budget.
  const baseProjet = fetchPath.replace(/\/budget$/, "");

  useEffect(() => {
    let cancelled = false;
    authedFetch(fetchPath)
      .then(async (res) => {
        if (cancelled) return;
        if (!res.ok) {
          setFailed(true);
          return;
        }
        setData((await res.json()) as BudgetInvest);
      })
      .catch(() => {
        if (!cancelled) setFailed(true);
      });
    return () => {
      cancelled = true;
    };
  }, [fetchPath]);

  if (data?.statut === "masque") return null;

  const naBox = (titre: string, texte: string) => (
    <div className="rounded-xl border border-dashed border-brand-700 bg-brand-950/40 px-4 py-6 text-center">
      <p className="text-sm font-semibold text-white/70">{titre}</p>
      <p className="mx-auto mt-1 max-w-sm text-xs text-white/40">
        {texte}
      </p>
    </div>
  );

  const lignes = data?.lignes || [];

  return (
    <div className="rounded-2xl border border-brand-800 bg-brand-900 p-4 text-white">
      <div className="mb-1 flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-sm font-semibold">
          Budget d&apos;optimisation (amélioration)
        </h2>
        {data?.statut === "connecte" && data.date_debut ? (
          <span className="text-xs text-white/40">
            depuis le {fmtDate(data.date_debut)}
          </span>
        ) : null}
      </div>
      <p className="mb-3 text-[11px] text-white/35">
        Où va l&apos;argent : les enveloppes de dépenses du projet
        d&apos;optimisation
        {data?.statut === "connecte" && data.projet_nom
          ? ` — ${data.projet_nom}`
          : ""}
        , avec le dépensé réel QuickBooks. Cliquez un montant dépensé
        pour voir les transactions et leurs factures.
      </p>

      {failed ? (
        naBox(
          "Chargement impossible",
          "Le budget n'a pas pu être chargé — réessayez plus tard."
        )
      ) : data === null ? (
        <div className="flex justify-center py-10">
          <Loader2 className="h-5 w-5 animate-spin text-accent-500" />
        </div>
      ) : data.statut === "aucun_projet" ? (
        naBox(
          "Non applicable — pas encore rentré",
          "Cette compagnie n'a aucun projet dans la section " +
            "optimisation de gestion d'entreprise."
        )
      ) : data.statut === "sans_qbo" ? (
        naBox(
          "QuickBooks non connecté",
          `Le projet « ${data.projet_nom} » existe dans la section ` +
            "optimisation, mais aucune connexion QuickBooks n'est " +
            "choisie dans ses réglages."
        )
      ) : data.statut === "erreur" ? (
        naBox(
          "Lecture QuickBooks impossible",
          data.erreur ||
            "Erreur de lecture — vérifiez la connexion QuickBooks."
        )
      ) : lignes.length === 0 ? (
        naBox(
          "Aucune enveloppe",
          "Le projet d'optimisation n'a pas encore de lignes de budget."
        )
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[420px] text-xs tabular-nums">
            <thead>
              <tr className="text-left text-[10px] uppercase tracking-wider text-white/40">
                <th className="py-1.5 pr-2 font-medium">Enveloppe</th>
                <th className="py-1.5 pl-2 text-right font-medium">
                  Budget
                </th>
                <th className="py-1.5 pl-2 text-right font-medium">
                  Dépensé
                </th>
                <th className="py-1.5 pl-2 text-right font-medium">
                  Reste
                </th>
              </tr>
            </thead>
            <tbody>
              {lignes.map((l) => {
                const pct =
                  l.budget > 0 && l.depense !== null
                    ? Math.min(
                        100,
                        Math.max(0, (l.depense / l.budget) * 100)
                      )
                    : 0;
                const depasse = l.reste !== null && l.reste < 0;
                return (
                  <tr
                    key={l.ligne_id}
                    className="border-t border-brand-800/60"
                  >
                    <td className="py-2 pr-2">
                      <p className="text-white/80">{l.nom}</p>
                      {l.budget > 0 ? (
                        <span className="mt-1 block h-1 w-full max-w-[140px] overflow-hidden rounded-full bg-white/10">
                          <span
                            className={`block h-full ${
                              depasse ? "bg-rose-400" : "bg-accent-500"
                            }`}
                            style={{ width: `${pct}%` }}
                          />
                        </span>
                      ) : null}
                    </td>
                    <td className="py-2 pl-2 text-right text-white/80">
                      {fmtMoney(l.budget)}
                    </td>
                    <td className="py-2 pl-2 text-right">
                      {l.depense === null ? (
                        <span className="text-white/35">—</span>
                      ) : l.mode === "deficit_operation" ? (
                        <span
                          className="text-white/80"
                          title="Déficit d'opération couvert par cette enveloppe (calculé du cashflow — pas de factures individuelles)"
                        >
                          {fmtMoney(l.depense)}
                        </span>
                      ) : (
                        <button
                          type="button"
                          onClick={() =>
                            setTxnLigne({
                              titre: l.nom,
                              url: `${baseProjet}/qbo-lignes/${l.ligne_id}/transactions`
                            })
                          }
                          className="text-white/80 underline decoration-dotted underline-offset-2 transition hover:text-white"
                          title="Voir les transactions derrière ce montant (et leurs factures)"
                        >
                          {fmtMoney(l.depense)}
                        </button>
                      )}
                    </td>
                    <td
                      className={`py-2 pl-2 text-right font-semibold ${
                        depasse ? "text-rose-400" : "text-emerald-400"
                      }`}
                    >
                      {l.reste === null ? "—" : fmtMoney(l.reste)}
                    </td>
                  </tr>
                );
              })}
              {data.total ? (
                <tr className="border-t-2 border-brand-700 font-semibold">
                  <td className="py-2 pr-2 text-white">TOTAL</td>
                  <td className="py-2 pl-2 text-right text-white">
                    {fmtMoney(data.total.budget)}
                  </td>
                  <td className="py-2 pl-2 text-right text-white">
                    {fmtMoney(data.total.depense)}
                  </td>
                  <td
                    className={`py-2 pl-2 text-right ${
                      data.total.reste < 0
                        ? "text-rose-400"
                        : "text-emerald-400"
                    }`}
                  >
                    {fmtMoney(data.total.reste)}
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      )}
      {txnLigne ? (
        <TransactionsReellesModal
          titre={txnLigne.titre}
          fetchUrl={txnLigne.url}
          pieceBase={`${baseProjet}/qbo-pieces`}
          onClose={() => setTxnLigne(null)}
        />
      ) : null}
    </div>
  );
}
