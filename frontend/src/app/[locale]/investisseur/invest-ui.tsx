"use client";

/* Portail Investisseur v2 — briques UI partagées (portefeuille, fiche
   projet, aperçu admin). Graphiques SVG faits main (pas de lib), encre
   sur `currentColor` pour rester lisibles dans les deux thèmes. */

import { useEffect, useState } from "react";

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

export type ImmeubleRow = {
  immeuble_id: number;
  name: string;
  address: string | null;
  nb_logements: number;
  nb_baux_actifs: number;
  loyers_mensuels: number;
  valeur: number | null;
  valeur_source: string | null;
  valeur_date: string | null;
  hypotheque_balance: number;
  hypotheque_preteur: string | null;
  hypotheque_taux_pct: number | null;
  hypotheque_fin_terme: string | null;
  equite: number;
  ownership_pct: number;
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

export type ProjetDetail = {
  entreprise_id: number;
  entreprise_name: string;
  description: string | null;
  phase: string;
  statut_participation: string;
  immeubles: ImmeubleRow[];
  valeur_totale: number;
  hypotheque_totale: number;
  equite: number;
  loyers_mensuels: number;
  nb_logements: number;
  nb_baux_actifs: number;
  taux_occupation: number | null;
  serie_mensuelle: SerieMois[];
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
  actionnaires: { name: string; parts_pct: number; is_me: boolean }[];
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
