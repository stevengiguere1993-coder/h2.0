"use client";

/* Portail Investisseur v2 — briques UI partagées (portefeuille, fiche
   projet, aperçu admin). Graphiques SVG faits main (pas de lib), encre
   sur `currentColor` pour rester lisibles dans les deux thèmes. */

import { Fragment, useEffect, useMemo, useState } from "react";
import { ChevronDown, ChevronRight, Loader2 } from "lucide-react";

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
  show_depenses: boolean;
  show_hypotheque: boolean;
  show_actionnaires: boolean;
  show_cashflow: boolean;
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

export function DepensesParCategorie({
  items
}: {
  items: DepenseCategorie[];
}) {
  if (!items || items.length === 0) return null;
  const total = items.reduce((s, x) => s + x.total, 0);
  if (total <= 0) return null;
  return (
    <div className="mt-3 border-t border-brand-800 pt-3">
      <p className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-white/40">
        Dépenses par catégorie · 12 mois
      </p>
      <ul className="space-y-1.5">
        {items.map((d) => {
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
  revenus: number;
  depenses: number;
  hypotheque?: number;
  ecart: number;
  details?: { nom: string; type: string; montant: number }[];
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

export function QboReelsPanel({ fetchPath }: { fetchPath: string }) {
  const [reels, setReels] = useState<QboReels | null>(null);
  const [failed, setFailed] = useState(false);
  const [periode, setPeriode] = useState("12m");
  const [ouverts, setOuverts] = useState<Set<string>>(new Set());

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
    colSpan
  }: {
    details: { nom: string; type: string; montant: number }[];
    colSpan: number;
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
                <span className="text-white/50">{d.nom}</span>
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
        {hasDetails ? " — cliquez un mois pour le détail par compte" : ""}
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
    </div>
  );
}
