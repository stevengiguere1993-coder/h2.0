"use client";

import { useEffect, useState } from "react";
import { Loader2, TrendingUp } from "lucide-react";

import { authedFetch } from "@/lib/auth";

type StatsRow = {
  count: number;
  median: number | null;
  p25: number | null;
  p75: number | null;
  min: number | null;
  max: number | null;
};

type BedroomBreakdown = {
  bedrooms: number;
  pieces_label: string;
  standard: StatsRow;
  renovated: StatsRow;
  with_heating: StatsRow;
  with_electricity: StatsRow;
};

type ComparablesSummary = {
  quartier: string | null;
  fsa: string | null;
  sample_size: number;
  fresh_count: number;
  oldest_at: string | null;
  overall: StatsRow;
  by_bedrooms: BedroomBreakdown[];
  common_inclusions: Array<{ tag: string; count: number; pct: number }>;
};

const TAG_LABELS: Record<string, string> = {
  chauffage: "Chauffage",
  electricite: "Électricité",
  eau_chaude: "Eau chaude",
  internet: "Internet",
  cable: "Câble TV",
  stationnement: "Stationnement",
  electromenagers: "Électroménagers",
  climatiseur: "Climatiseur",
  laveuse_secheuse: "Laveuse/Sécheuse",
  ascenseur: "Ascenseur",
  meuble: "Meublé"
};

function fmt$(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  return n.toLocaleString("fr-CA", {
    style: "currency",
    currency: "CAD",
    maximumFractionDigits: 0
  });
}

export function ComparablesSection({
  postalCode,
  address
}: {
  postalCode: string | null;
  address: string | null;
}) {
  const [data, setData] = useState<ComparablesSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancel = false;
    void (async () => {
      setLoading(true);
      try {
        const params = new URLSearchParams();
        if (postalCode) {
          params.set("postal_code", postalCode);
        } else if (address) {
          const m = address.match(/^\d+\s+(.+?)(?:,|$)/);
          if (m) params.set("nom_rue", m[1].trim());
        }
        if (!params.toString()) {
          setData(null);
          setLoading(false);
          return;
        }
        const res = await authedFetch(
          `/api/v1/prospection/rental-comparables/summary?${params}`
        );
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        if (!cancel) setData((await res.json()) as ComparablesSummary);
      } catch (e) {
        if (!cancel)
          setError(e instanceof Error ? e.message : "Erreur");
      } finally {
        if (!cancel) setLoading(false);
      }
    })();
    return () => {
      cancel = true;
    };
  }, [postalCode, address]);

  if (loading) {
    return (
      <section className="rounded-xl border border-brand-800 bg-brand-900 p-5">
        <h2 className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wider text-accent-500">
          <TrendingUp className="h-4 w-4" /> Comparables loyers
        </h2>
        <p className="mt-2 flex items-center gap-2 text-xs text-white/50">
          <Loader2 className="h-3 w-3 animate-spin" /> Chargement…
        </p>
      </section>
    );
  }

  if (error || !data || data.sample_size === 0) {
    return (
      <section className="rounded-xl border border-brand-800 bg-brand-900 p-5">
        <h2 className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wider text-accent-500">
          <TrendingUp className="h-4 w-4" /> Comparables loyers
        </h2>
        <p className="mt-2 text-xs text-white/50">
          {error
            ? `Erreur : ${error}`
            : "Aucune annonce comparable récente pour ce secteur. Lance un scrape via Paramètres → Sources de données → « Mise à jour comparables »."}
        </p>
      </section>
    );
  }

  return (
    <section className="rounded-xl border border-brand-800 bg-brand-900 p-5">
      <header className="flex items-center justify-between gap-2">
        <h2 className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wider text-accent-500">
          <TrendingUp className="h-4 w-4" /> Comparables loyers
        </h2>
        <span className="text-[10px] text-white/40">
          {data.sample_size} annonce{data.sample_size > 1 ? "s" : ""} ·{" "}
          {data.fresh_count} fraîche{data.fresh_count > 1 ? "s" : ""}{" "}
          (&lt; 14j)
        </span>
      </header>

      <p className="mt-1 text-[11px] text-white/50">
        {data.quartier
          ? `Quartier : ${data.quartier}`
          : data.fsa
            ? `Zone postale ${data.fsa}`
            : "Zone proche"}
        {" — "}médiane globale {fmt$(data.overall.median)}
      </p>

      {/* Boxplot SVG par chambres */}
      {data.by_bedrooms.length > 0 ? (
        <Boxplot rows={data.by_bedrooms} />
      ) : null}

      {/* Détails par taille avec impacts inclusions/réno */}
      <div className="mt-4 space-y-2">
        {data.by_bedrooms.map((b) => (
          <div
            key={b.bedrooms}
            className="rounded-md border border-brand-800 bg-brand-950 p-2.5"
          >
            <p className="text-xs font-semibold text-white">
              {b.pieces_label}
            </p>
            <div className="mt-1 grid grid-cols-2 gap-1 text-[10px] sm:grid-cols-4">
              <Stat
                label="Standard"
                stats={b.standard}
                color="text-white/80"
              />
              <Stat
                label="Rénové"
                stats={b.renovated}
                color="text-emerald-300"
              />
              <Stat
                label="+ chauffage"
                stats={b.with_heating}
                color="text-amber-300"
              />
              <Stat
                label="+ électricité"
                stats={b.with_electricity}
                color="text-blue-300"
              />
            </div>
          </div>
        ))}
      </div>

      {/* Inclusions communes */}
      {data.common_inclusions.length > 0 ? (
        <div className="mt-3">
          <p className="text-[10px] font-semibold uppercase tracking-wider text-white/50">
            Inclusions courantes du secteur
          </p>
          <div className="mt-1 flex flex-wrap gap-1.5">
            {data.common_inclusions.map((inc) => (
              <span
                key={inc.tag}
                className="inline-flex items-center gap-1 rounded-full bg-brand-800 px-2 py-0.5 text-[10px] text-white/70"
              >
                {TAG_LABELS[inc.tag] || inc.tag}
                <span className="text-white/40">
                  {inc.pct.toFixed(0)} %
                </span>
              </span>
            ))}
          </div>
        </div>
      ) : null}
    </section>
  );
}

function Stat({
  label,
  stats,
  color
}: {
  label: string;
  stats: StatsRow;
  color: string;
}) {
  if (stats.count === 0) {
    return (
      <div>
        <p className="text-white/40">{label}</p>
        <p className="text-white/30">—</p>
      </div>
    );
  }
  return (
    <div>
      <p className="text-white/50">
        {label} (n={stats.count})
      </p>
      <p className={`tabular-nums ${color}`}>{fmt$(stats.median)}</p>
    </div>
  );
}

/** Mini-boxplot SVG horizontal par bracket de chambres. Affiche
 * P25 → P75 comme rectangle, médiane comme ligne, min/max comme
 * trait extérieur. Tout en pur SVG, pas de dépendance graphique. */
function Boxplot({ rows }: { rows: BedroomBreakdown[] }) {
  const valid = rows.filter((r) => r.standard.count > 0);
  if (valid.length === 0) return null;

  // Échelle X commune à tous les boxplots
  const allMins = valid
    .map((r) => r.standard.min)
    .filter((x): x is number => x !== null);
  const allMaxs = valid
    .map((r) => r.standard.max)
    .filter((x): x is number => x !== null);
  const min = Math.floor((Math.min(...allMins) || 800) / 100) * 100;
  const max = Math.ceil((Math.max(...allMaxs) || 3000) / 100) * 100;
  const W = 360;
  const H = 28;
  const PADDING = 60;

  function x(v: number): number {
    return PADDING + ((v - min) / (max - min)) * (W - PADDING - 8);
  }

  return (
    <div className="mt-3 overflow-x-auto">
      <svg
        viewBox={`0 0 ${W} ${valid.length * (H + 6) + 22}`}
        className="w-full"
      >
        {valid.map((r, i) => {
          const y = i * (H + 6);
          const s = r.standard;
          if (
            s.min === null ||
            s.max === null ||
            s.median === null ||
            s.p25 === null ||
            s.p75 === null
          )
            return null;
          return (
            <g key={r.bedrooms} transform={`translate(0, ${y + 4})`}>
              <text
                x={0}
                y={H / 2 + 4}
                fill="#9ca3af"
                fontSize="10"
              >
                {r.bedrooms === 0 ? "Studio" : `${r.bedrooms + 2}½`}
              </text>
              {/* whisker */}
              <line
                x1={x(s.min)}
                x2={x(s.max)}
                y1={H / 2}
                y2={H / 2}
                stroke="#10b98180"
                strokeWidth={1}
              />
              {/* box P25 → P75 */}
              <rect
                x={x(s.p25)}
                y={H / 2 - 8}
                width={Math.max(2, x(s.p75) - x(s.p25))}
                height={16}
                fill="#10b98140"
                stroke="#10b981"
              />
              {/* median */}
              <line
                x1={x(s.median)}
                x2={x(s.median)}
                y1={H / 2 - 10}
                y2={H / 2 + 10}
                stroke="#34d399"
                strokeWidth={2}
              />
              {/* labels min/max */}
              <text
                x={x(s.min) - 2}
                y={H / 2 + 4}
                textAnchor="end"
                fill="#6b7280"
                fontSize="9"
              >
                {Math.round(s.min)}$
              </text>
              <text
                x={x(s.max) + 2}
                y={H / 2 + 4}
                fill="#6b7280"
                fontSize="9"
              >
                {Math.round(s.max)}$
              </text>
            </g>
          );
        })}
        {/* axe X */}
        <text
          x={PADDING}
          y={valid.length * (H + 6) + 14}
          fill="#6b7280"
          fontSize="9"
        >
          {min}$
        </text>
        <text
          x={W - 4}
          y={valid.length * (H + 6) + 14}
          textAnchor="end"
          fill="#6b7280"
          fontSize="9"
        >
          {max}$
        </text>
      </svg>
    </div>
  );
}
