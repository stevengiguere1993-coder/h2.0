"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Building2,
  Calculator,
  Database,
  Info,
  Loader2,
  MapPin,
  Search,
  TrendingUp,
  X
} from "lucide-react";

import { authedFetch } from "@/lib/auth";
import { AppTopbar } from "@/components/app-topbar";
import { useProspectionLayout } from "../layout";

type Area = { kind: string; value: string; count: number };

type Stats = {
  count: number;
  median: number | null;
  p25: number | null;
  p75: number | null;
  min: number | null;
  max: number | null;
};

type BedBreakdown = {
  bedrooms: number;
  pieces_label: string;
  standard: Stats;
  renovated: Stats;
  with_heating: Stats;
  with_electricity: Stats;
};

type Market = {
  quartier: string | null;
  fsa: string | null;
  sample_size: number;
  fresh_count: number;
  oldest_at: string | null;
  overall: Stats;
  by_bedrooms: BedBreakdown[];
  common_inclusions: { tag: string; count: number; pct: number }[];
};

type SchlBracket = {
  qc_label: string;
  schl_label: string;
  bedrooms: number;
  avg_rent: number | null;
  is_estimate: boolean;
};
type Schl = {
  matched: boolean;
  cma: string | null;
  zone: string | null;
  year: number | null;
  brackets: SchlBracket[];
};

function norm(s: string): string {
  return s
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9 ]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function money(n: number | null | undefined): string {
  if (n == null) return "—";
  return n.toLocaleString("fr-CA", {
    style: "currency",
    currency: "CAD",
    maximumFractionDigits: 0
  });
}

const GRM_TIERS = [
  { max: 7, label: "Excellent", cls: "text-emerald-300" },
  { max: 10, label: "Bon", cls: "text-sky-300" },
  { max: 13, label: "Moyen", cls: "text-amber-300" },
  { max: Infinity, label: "Cher", cls: "text-rose-300" }
];

type Filter = {
  quartier?: string;
  postal_code?: string;
  city?: string;
  nom_rue?: string;
};

function areaToFilter(a: Area): Filter {
  if (a.kind === "fsa") return { postal_code: a.value };
  if (a.kind === "city") return { city: a.value };
  return { quartier: a.value };
}
function areaLabel(a: Area): string {
  if (a.kind === "fsa") return `Code postal ${a.value}`;
  return a.value;
}

export default function MoyenneLocativePage() {
  const { onOpenSidebar } = useProspectionLayout();

  const [areas, setAreas] = useState<Area[]>([]);
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [market, setMarket] = useState<Market | null>(null);
  const [schl, setSchl] = useState<Schl | null>(null);
  const [label, setLabel] = useState("");
  const boxRef = useRef<HTMLDivElement | null>(null);

  const [mix, setMix] = useState<Record<number, string>>({});
  const [prix, setPrix] = useState("");
  const [monLoyer, setMonLoyer] = useState("");
  const [monBed, setMonBed] = useState<number>(1);

  useEffect(() => {
    void (async () => {
      const r = await authedFetch(
        "/api/v1/prospection/rental-comparables/areas"
      );
      if (r.ok) setAreas((await r.json()) as Area[]);
    })();
  }, []);

  useEffect(() => {
    function onClick(e: MouseEvent) {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, []);

  const matches = useMemo(() => {
    const q = norm(query);
    const base = q
      ? areas.filter((a) => norm(a.value).includes(q))
      : areas;
    return base.slice(0, 12);
  }, [query, areas]);

  const load = useCallback(
    async (f: Filter, displayLabel: string) => {
      setOpen(false);
      setLoading(true);
      setMarket(null);
      setSchl(null);
      setLabel(displayLabel);
      const mp = new URLSearchParams();
      if (f.quartier) mp.set("quartier", f.quartier);
      else if (f.postal_code) mp.set("postal_code", f.postal_code);
      else if (f.city) mp.set("city", f.city);
      else if (f.nom_rue) mp.set("nom_rue", f.nom_rue);
      const schlQ = f.quartier || f.city || f.nom_rue || displayLabel;
      const [mr, sr] = await Promise.all([
        authedFetch(
          `/api/v1/prospection/rental-comparables/summary?${mp.toString()}`
        ),
        authedFetch(
          `/api/v1/prospection/moyenne-locative?q=${encodeURIComponent(schlQ)}`
        )
      ]);
      if (mr.ok) setMarket((await mr.json()) as Market);
      if (sr.ok) setSchl((await sr.json()) as Schl);
      setLoading(false);
    },
    []
  );

  // Vue par défaut : tout le marché récent (peu importe la catégorisation
  // quartier/code postal des annonces), pour toujours afficher des chiffres.
  const loadOverall = useCallback(async () => {
    setOpen(false);
    setLabel("Tout le marché récent (Grand Montréal)");
    setLoading(true);
    setMarket(null);
    setSchl(null);
    const [mr, sr] = await Promise.all([
      authedFetch(
        "/api/v1/prospection/rental-comparables/summary?tout=true&max_age_days=45"
      ),
      authedFetch("/api/v1/prospection/moyenne-locative?q=Montr%C3%A9al")
    ]);
    if (mr.ok) setMarket((await mr.json()) as Market);
    if (sr.ok) setSchl((await sr.json()) as Schl);
    setLoading(false);
  }, []);

  useEffect(() => {
    void loadOverall();
  }, [loadOverall]);

  function resolveFree(): { f: Filter; label: string } | null {
    const q = query.trim();
    if (!q) return null;
    const pc = q.match(/[A-Za-z]\d[A-Za-z]/);
    if (pc) return { f: { postal_code: pc[0].toUpperCase() }, label: q };
    const nq = norm(q);
    const exact = areas.find(
      (a) => a.kind === "quartier" && norm(a.value) === nq
    );
    if (exact) return { f: { quartier: exact.value }, label: exact.value };
    const partial = areas.find(
      (a) =>
        a.kind === "quartier" &&
        (norm(a.value).includes(nq) || nq.includes(norm(a.value)))
    );
    if (partial) return { f: { quartier: partial.value }, label: partial.value };
    const cityA =
      areas.find((a) => a.kind === "city" && norm(a.value) === nq) ||
      areas.find(
        (a) =>
          a.kind === "city" &&
          (norm(a.value).includes(nq) || nq.includes(norm(a.value)))
      );
    if (cityA) return { f: { city: cityA.value }, label: cityA.value };
    const street = q.replace(/^\s*\d+\s*/, "").trim();
    if (street) return { f: { nom_rue: street }, label: q };
    return null;
  }

  function search() {
    const r = resolveFree();
    if (r) void load(r.f, r.label);
  }

  // SCHL average par nb de chambres (0..3), pour la colonne référence.
  const schlByBed = useMemo(() => {
    const m: Record<number, number | null> = {};
    schl?.brackets.forEach((b) => {
      if (!(b.bedrooms in m)) m[b.bedrooms] = b.avg_rent;
    });
    return m;
  }, [schl]);

  const rows = market?.by_bedrooms ?? [];

  const calc = useMemo(() => {
    let monthly = 0;
    let units = 0;
    for (const b of rows) {
      const n = parseInt(mix[b.bedrooms] || "0", 10);
      const ref = b.standard.median;
      if (n > 0 && ref) {
        monthly += n * ref;
        units += n;
      }
    }
    return { monthly, annual: monthly * 12, units };
  }, [rows, mix]);

  const grm = useMemo(() => {
    const p = parseFloat(prix.replace(/[^0-9.]/g, ""));
    if (!p || !calc.annual) return null;
    return p / calc.annual;
  }, [prix, calc.annual]);

  const compare = useMemo(() => {
    const loyer = parseFloat(monLoyer.replace(/[^0-9.]/g, ""));
    const target = rows.find((b) => b.bedrooms === monBed);
    const market_med = target?.standard.median ?? null;
    if (!loyer || market_med == null) return null;
    return { loyer, market: market_med, diff: (loyer - market_med) / market_med };
  }, [rows, monLoyer, monBed]);

  const hasMarket = !!market && market.sample_size > 0;
  const trulyEmpty =
    !loading && !!market && market.sample_size === 0 && areas.length === 0;

  return (
    <>
      <AppTopbar
        breadcrumbs={[
          { label: "Prospection", href: "/prospection" },
          { label: "Moyenne locative" }
        ]}
        onOpenSidebar={onOpenSidebar}
      />

      <div className="p-4 lg:p-6">
        <header className="flex flex-wrap items-center gap-3">
          <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-emerald-500/15 text-emerald-400">
            <Building2 className="h-5 w-5" />
          </span>
          <div className="min-w-0 flex-1">
            <h1 className="text-2xl font-bold text-white">Moyenne locative</h1>
            <p className="text-sm text-white/60">
              Loyers du marché à partir des annonces réelles (Kijiji, LesPAC) —
              médiane, fourchette inférieure/supérieure par type. Référence SCHL
              en complément.
            </p>
          </div>
        </header>

        {/* Recherche */}
        <section className="mt-6">
          <div ref={boxRef} className="relative max-w-2xl">
            <div className="flex gap-2">
              <div className="relative flex-1">
                <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-white/40" />
                <input
                  value={query}
                  onChange={(e) => {
                    setQuery(e.target.value);
                    setOpen(true);
                  }}
                  onFocus={() => setOpen(true)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      if (matches.length > 0) {
                        const a = matches[0];
                        void load(areaToFilter(a), areaLabel(a));
                      } else search();
                    }
                  }}
                  placeholder="Adresse, secteur ou code postal (ex. 1234 rue Beaubien, Verdun, H2W…)"
                  className="w-full rounded-xl border border-brand-800 bg-brand-900 py-3 pl-9 pr-3 text-sm text-white outline-none focus:border-emerald-500/60"
                />
                {query ? (
                  <button
                    type="button"
                    onClick={() => {
                      setQuery("");
                      setMarket(null);
                      setSchl(null);
                      setOpen(false);
                    }}
                    className="absolute right-2 top-1/2 -translate-y-1/2 rounded p-1 text-white/40 hover:text-white"
                  >
                    <X className="h-4 w-4" />
                  </button>
                ) : null}
              </div>
              <button
                type="button"
                onClick={search}
                className="shrink-0 rounded-xl bg-emerald-500 px-4 py-3 text-sm font-semibold text-white hover:bg-emerald-400"
              >
                Rechercher
              </button>
            </div>

            {open && matches.length > 0 ? (
              <div className="absolute z-20 mt-1 max-h-72 w-full overflow-y-auto rounded-xl border border-brand-800 bg-brand-900 py-1 shadow-2xl">
                {matches.map((a) => (
                  <button
                    key={`${a.kind}:${a.value}`}
                    type="button"
                    onClick={() => void load(areaToFilter(a), areaLabel(a))}
                    className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm text-white/80 hover:bg-brand-800/60"
                  >
                    <MapPin className="h-3.5 w-3.5 text-emerald-400" />
                    <span className="flex-1 truncate">{areaLabel(a)}</span>
                    <span className="text-[11px] text-white/30">
                      {a.count} annonce{a.count > 1 ? "s" : ""}
                    </span>
                  </button>
                ))}
              </div>
            ) : null}
          </div>

          <div className="mt-2 flex items-center gap-2">
            <button
              type="button"
              onClick={() => {
                setQuery("");
                void loadOverall();
              }}
              className="rounded-full border border-brand-800 bg-brand-900 px-3 py-1 text-xs text-white/60 hover:border-emerald-500/40 hover:text-emerald-300"
            >
              ↺ Tout le marché récent
            </button>
          </div>

          {trulyEmpty ? (
            <p className="mt-2 max-w-2xl rounded-lg border border-amber-500/30 bg-amber-500/5 px-3 py-2 text-xs text-amber-200">
              <Database className="mr-1 inline h-3.5 w-3.5" />
              Le collecteur d&apos;annonces n&apos;a pas encore de données. Lance
              le cron Render <strong>rental-scrape-daily</strong> (ou attends son
              prochain passage), puis reviens. La référence SCHL reste
              disponible.
            </p>
          ) : null}
        </section>

        {/* Résultats */}
        {loading ? (
          <div className="mt-10 flex items-center justify-center text-white/50">
            <Loader2 className="mr-2 h-5 w-5 animate-spin" /> Recherche…
          </div>
        ) : market || schl ? (
          <div className="mt-8 grid gap-5 lg:grid-cols-3">
            <div className="space-y-5 lg:col-span-2">
              {/* Loyers du marché */}
              <div className="rounded-2xl border border-brand-800 bg-brand-900 p-5">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <MapPin className="h-4 w-4 text-emerald-400" />
                    <h2 className="text-lg font-bold text-white">{label}</h2>
                  </div>
                  {hasMarket ? (
                    <span className="rounded-full border border-emerald-500/40 bg-emerald-500/10 px-3 py-1 text-xs font-semibold text-emerald-300">
                      {market!.sample_size} annonce
                      {market!.sample_size > 1 ? "s" : ""} ·{" "}
                      {market!.fresh_count} récente
                      {market!.fresh_count > 1 ? "s" : ""}
                    </span>
                  ) : null}
                </div>

                {hasMarket ? (
                  <div className="mt-4 overflow-x-auto">
                    <table className="w-full min-w-[620px] text-sm">
                      <thead>
                        <tr className="border-b border-brand-800 text-left text-[11px] uppercase tracking-wider text-white/45">
                          <th className="py-2 pr-3 font-semibold">Type</th>
                          <th className="py-2 pr-3 text-right font-semibold">
                            Médiane
                          </th>
                          <th className="py-2 pr-3 text-right font-semibold">
                            Inférieur
                          </th>
                          <th className="py-2 pr-3 text-right font-semibold">
                            Supérieur
                          </th>
                          <th className="py-2 pr-3 text-right font-semibold">
                            Fourchette
                          </th>
                          <th className="py-2 pr-3 text-right font-semibold">
                            n
                          </th>
                          <th className="py-2 text-right font-semibold">
                            Réf. SCHL
                          </th>
                        </tr>
                      </thead>
                      <tbody>
                        {rows.map((b) => (
                          <tr
                            key={b.bedrooms}
                            className="border-b border-brand-800/50"
                          >
                            <td className="py-2.5 pr-3 font-semibold text-white">
                              {b.pieces_label}
                            </td>
                            <td className="py-2.5 pr-3 text-right text-base font-bold tabular-nums text-emerald-300">
                              {money(b.standard.median)}
                            </td>
                            <td className="py-2.5 pr-3 text-right tabular-nums text-white/60">
                              {money(b.standard.p25)}
                            </td>
                            <td className="py-2.5 pr-3 text-right tabular-nums text-white/60">
                              {money(b.standard.p75)}
                            </td>
                            <td className="py-2.5 pr-3 text-right text-xs tabular-nums text-white/40">
                              {money(b.standard.min)}–{money(b.standard.max)}
                            </td>
                            <td className="py-2.5 pr-3 text-right text-xs text-white/40">
                              {b.standard.count}
                            </td>
                            <td className="py-2.5 text-right tabular-nums text-sky-300/80">
                              {money(schlByBed[Math.min(b.bedrooms, 3)] ?? null)}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <div className="mt-4 rounded-lg border border-amber-500/30 bg-amber-500/5 px-3 py-3 text-sm text-amber-200">
                    Pas encore d&apos;annonces pour ce secteur. Voici la
                    référence SCHL ci-dessous en attendant que le collecteur
                    passe.
                  </div>
                )}

                {/* Référence SCHL */}
                {schl?.matched ? (
                  <div className="mt-4 rounded-xl border border-sky-500/20 bg-sky-500/[0.04] p-3">
                    <div className="flex items-center justify-between">
                      <span className="text-xs font-semibold text-sky-300">
                        Référence SCHL (officielle)
                        {schl.zone ? ` — ${schl.zone}` : ""}
                      </span>
                      {schl.year ? (
                        <span className="text-[11px] text-white/40">
                          {schl.year}
                        </span>
                      ) : null}
                    </div>
                    <div className="mt-2 flex flex-wrap gap-x-5 gap-y-1 text-xs text-white/60">
                      {schl.brackets
                        .filter((x) => x.avg_rent != null && !x.is_estimate)
                        .map((x) => (
                          <span key={x.qc_label}>
                            {x.schl_label} :{" "}
                            <span className="font-semibold text-white">
                              {money(x.avg_rent)}
                            </span>
                          </span>
                        ))}
                    </div>
                  </div>
                ) : null}

                <p className="mt-3 text-[11px] text-white/35">
                  Source : annonces de location collectées par Kratos (Kijiji,
                  LesPAC), valeurs aberrantes et doublons écartés — même méthode
                  que Zipplex. « Réf. SCHL » = moyenne officielle du parc
                  existant. Les chiffres exacts de Zipplex demandent leur
                  abonnement (données propriétaires).
                </p>
              </div>

              {/* Compare un loyer */}
              {hasMarket ? (
                <div className="rounded-2xl border border-brand-800 bg-brand-900 p-5">
                  <h3 className="flex items-center gap-2 text-sm font-semibold text-white">
                    <TrendingUp className="h-4 w-4 text-emerald-400" />
                    Compare un loyer au marché
                  </h3>
                  <div className="mt-3 flex flex-wrap items-end gap-3">
                    <div>
                      <label className="mb-1 block text-[11px] text-white/50">
                        Loyer ($/mois)
                      </label>
                      <input
                        value={monLoyer}
                        onChange={(e) => setMonLoyer(e.target.value)}
                        inputMode="numeric"
                        placeholder="1 250"
                        className="w-32 rounded-lg border border-brand-800 bg-brand-950 px-3 py-2 text-sm text-white outline-none focus:border-emerald-500/60"
                      />
                    </div>
                    <div>
                      <label className="mb-1 block text-[11px] text-white/50">
                        Type
                      </label>
                      <select
                        value={monBed}
                        onChange={(e) => setMonBed(parseInt(e.target.value, 10))}
                        className="rounded-lg border border-brand-800 bg-brand-950 px-3 py-2 text-sm text-white outline-none focus:border-emerald-500/60"
                      >
                        {rows.map((b) => (
                          <option key={b.bedrooms} value={b.bedrooms}>
                            {b.pieces_label}
                          </option>
                        ))}
                      </select>
                    </div>
                    {compare ? (
                      <div
                        className={`rounded-lg border px-3 py-2 text-sm font-semibold ${
                          compare.diff > 0.02
                            ? "border-rose-500/40 bg-rose-500/10 text-rose-200"
                            : compare.diff < -0.02
                              ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-200"
                              : "border-white/15 bg-white/5 text-white/70"
                        }`}
                      >
                        {compare.diff > 0 ? "+" : ""}
                        {(compare.diff * 100).toFixed(0)} % vs médiane (
                        {money(compare.market)})
                      </div>
                    ) : null}
                  </div>
                </div>
              ) : null}
            </div>

            {/* Calculateur */}
            <div className="space-y-5">
              {hasMarket ? (
                <div className="rounded-2xl border border-brand-800 bg-brand-900 p-5">
                  <h3 className="flex items-center gap-2 text-sm font-semibold text-white">
                    <Calculator className="h-4 w-4 text-emerald-400" />
                    Revenu potentiel d&apos;un immeuble
                  </h3>
                  <p className="mt-1 text-[11px] text-white/45">
                    Nombre de logements par type → revenu au marché (médiane).
                  </p>
                  <div className="mt-3 space-y-2">
                    {rows
                      .filter((b) => b.standard.median != null)
                      .map((b) => (
                        <div
                          key={b.bedrooms}
                          className="flex items-center justify-between gap-2"
                        >
                          <span className="text-sm text-white/70">
                            {b.pieces_label}
                            <span className="ml-1 text-[11px] text-white/35">
                              {money(b.standard.median)}
                            </span>
                          </span>
                          <input
                            value={mix[b.bedrooms] || ""}
                            onChange={(e) =>
                              setMix((m) => ({
                                ...m,
                                [b.bedrooms]: e.target.value.replace(
                                  /[^0-9]/g,
                                  ""
                                )
                              }))
                            }
                            inputMode="numeric"
                            placeholder="0"
                            className="w-16 rounded-lg border border-brand-800 bg-brand-950 px-2 py-1.5 text-right text-sm text-white outline-none focus:border-emerald-500/60"
                          />
                        </div>
                      ))}
                  </div>
                  <div className="mt-3 space-y-1 border-t border-brand-800 pt-3 text-sm">
                    <div className="flex justify-between text-white/60">
                      <span>Logements</span>
                      <span className="font-semibold text-white">
                        {calc.units}
                      </span>
                    </div>
                    <div className="flex justify-between text-white/60">
                      <span>Revenu / mois</span>
                      <span className="font-semibold text-emerald-300">
                        {money(calc.monthly)}
                      </span>
                    </div>
                    <div className="flex justify-between text-white/60">
                      <span>Revenu / an</span>
                      <span className="font-bold text-emerald-300">
                        {money(calc.annual)}
                      </span>
                    </div>
                  </div>
                  <div className="mt-3 border-t border-brand-800 pt-3">
                    <label className="mb-1 block text-[11px] text-white/50">
                      Prix demandé / payé ($) — pour le GRM
                    </label>
                    <input
                      value={prix}
                      onChange={(e) => setPrix(e.target.value)}
                      inputMode="numeric"
                      placeholder="1 200 000"
                      className="w-full rounded-lg border border-brand-800 bg-brand-950 px-3 py-2 text-sm text-white outline-none focus:border-emerald-500/60"
                    />
                    {grm ? (
                      <div className="mt-2 flex items-center justify-between rounded-lg bg-brand-950 px-3 py-2 text-sm">
                        <span className="text-white/60">GRM</span>
                        <span className="font-bold text-white">
                          {grm.toFixed(1)}{" "}
                          <span
                            className={
                              GRM_TIERS.find((t) => grm < t.max)?.cls ??
                              "text-white/60"
                            }
                          >
                            · {GRM_TIERS.find((t) => grm < t.max)?.label ?? ""}
                          </span>
                        </span>
                      </div>
                    ) : null}
                  </div>
                </div>
              ) : null}

              <div className="rounded-2xl border border-brand-800 bg-brand-900 p-4 text-[11px] text-white/45">
                <Info className="mb-1 inline h-3.5 w-3.5 text-white/40" /> La
                <strong> médiane</strong> est plus représentative que la moyenne
                (moins sensible aux extrêmes). « Inférieur/Supérieur » = 25ᵉ et
                75ᵉ centiles : la moitié des loyers tombe entre les deux.
              </div>
            </div>
          </div>
        ) : (
          <div className="mt-10 max-w-2xl rounded-2xl border border-dashed border-brand-800 p-8 text-center text-white/50">
            <Building2 className="mx-auto h-8 w-8 opacity-40" />
            <p className="mt-3 text-sm">
              Tape une adresse, un secteur ou un code postal pour voir les loyers
              du marché.
            </p>
          </div>
        )}
      </div>
    </>
  );
}
