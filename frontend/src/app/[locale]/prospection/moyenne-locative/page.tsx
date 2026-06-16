"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Building2,
  Calculator,
  Info,
  Loader2,
  MapPin,
  Minus,
  Search,
  TrendingDown,
  TrendingUp,
  X
} from "lucide-react";

import { authedFetch } from "@/lib/auth";
import { AppTopbar } from "@/components/app-topbar";
import { useProspectionLayout } from "../layout";

type Zone = {
  cma: string;
  zone: string | null;
  year: number | null;
  label: string;
};

type Bracket = {
  qc_label: string;
  schl_label: string;
  bedrooms: number;
  avg_rent: number | null;
  sample_size: number | null;
  is_estimate: boolean;
};

type Result = {
  matched: boolean;
  cma: string | null;
  zone: string | null;
  year: number | null;
  vacancy_rate: number | null;
  brackets: Bracket[];
  cma_brackets: Bracket[];
  suggestions: Zone[];
  notes: string[];
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

export default function MoyenneLocativePage() {
  const { onOpenSidebar } = useProspectionLayout();

  const [zones, setZones] = useState<Zone[]>([]);
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<Result | null>(null);
  const boxRef = useRef<HTMLDivElement | null>(null);

  // Calculateur de revenus : nb de logements par type.
  const [mix, setMix] = useState<Record<string, string>>({});
  const [prix, setPrix] = useState("");

  // Compare ton loyer.
  const [monLoyer, setMonLoyer] = useState("");
  const [monType, setMonType] = useState("4½");

  useEffect(() => {
    void (async () => {
      const r = await authedFetch("/api/v1/prospection/moyenne-locative/zones");
      if (r.ok) setZones((await r.json()) as Zone[]);
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
    if (!q) return zones.slice(0, 12);
    const toks = q.split(" ").filter(Boolean);
    return zones
      .map((z) => {
        const nl = norm(z.label);
        const score = toks.reduce((a, t) => a + (nl.includes(t) ? 1 : 0), 0);
        return { z, score, starts: nl.startsWith(q) };
      })
      .filter((m) => m.score > 0)
      .sort((a, b) => Number(b.starts) - Number(a.starts) || b.score - a.score)
      .slice(0, 12)
      .map((m) => m.z);
  }, [query, zones]);

  const loadByZone = useCallback(async (z: Zone) => {
    setOpen(false);
    setQuery(z.label);
    setLoading(true);
    setResult(null);
    const params = new URLSearchParams({ cma: z.cma });
    if (z.zone) params.set("zone", z.zone);
    const r = await authedFetch(
      `/api/v1/prospection/moyenne-locative?${params.toString()}`
    );
    if (r.ok) setResult((await r.json()) as Result);
    setLoading(false);
  }, []);

  const loadByQuery = useCallback(async () => {
    if (!query.trim()) return;
    setOpen(false);
    setLoading(true);
    setResult(null);
    const r = await authedFetch(
      `/api/v1/prospection/moyenne-locative?q=${encodeURIComponent(query.trim())}`
    );
    if (r.ok) setResult((await r.json()) as Result);
    setLoading(false);
  }, [query]);

  // Map bracket par qc_label pour le calculateur / comparaison.
  const cmaByBed = useMemo(() => {
    const m: Record<number, number | null> = {};
    result?.cma_brackets.forEach((b) => (m[b.bedrooms] = b.avg_rent));
    return m;
  }, [result]);

  const calc = useMemo(() => {
    if (!result) return { monthly: 0, annual: 0, units: 0 };
    let monthly = 0;
    let units = 0;
    for (const b of result.brackets) {
      const n = parseInt(mix[b.qc_label] || "0", 10);
      if (n > 0 && b.avg_rent != null) {
        monthly += n * b.avg_rent;
        units += n;
      }
    }
    return { monthly, annual: monthly * 12, units };
  }, [result, mix]);

  const grm = useMemo(() => {
    const p = parseFloat(prix.replace(/[^0-9.]/g, ""));
    if (!p || !calc.annual) return null;
    return p / calc.annual;
  }, [prix, calc.annual]);

  const compare = useMemo(() => {
    if (!result) return null;
    const loyer = parseFloat(monLoyer.replace(/[^0-9.]/g, ""));
    const target = result.brackets.find((b) => b.qc_label === monType);
    if (!loyer || !target || target.avg_rent == null) return null;
    const diff = (loyer - target.avg_rent) / target.avg_rent;
    return { loyer, market: target.avg_rent, diff };
  }, [result, monLoyer, monType]);

  const secteurLabel = result?.zone || (result?.cma ? `${result.cma} (RMR)` : "");

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
              Loyers moyens du marché par secteur (données SCHL). Tape une
              adresse ou un secteur — ça sort tout, par type de logement.
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
                      if (matches.length > 0) void loadByZone(matches[0]);
                      else void loadByQuery();
                    }
                  }}
                  placeholder="Adresse ou secteur (ex. Plateau-Mont-Royal, LaSalle, Longueuil…)"
                  className="w-full rounded-xl border border-brand-800 bg-brand-900 py-3 pl-9 pr-3 text-sm text-white outline-none focus:border-emerald-500/60"
                />
                {query ? (
                  <button
                    type="button"
                    onClick={() => {
                      setQuery("");
                      setResult(null);
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
                onClick={() => void loadByQuery()}
                className="shrink-0 rounded-xl bg-emerald-500 px-4 py-3 text-sm font-semibold text-white hover:bg-emerald-400"
              >
                Rechercher
              </button>
            </div>

            {open && matches.length > 0 ? (
              <div className="absolute z-20 mt-1 max-h-72 w-full overflow-y-auto rounded-xl border border-brand-800 bg-brand-900 py-1 shadow-2xl">
                {matches.map((z) => (
                  <button
                    key={`${z.cma}::${z.zone ?? ""}`}
                    type="button"
                    onClick={() => void loadByZone(z)}
                    className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm text-white/80 hover:bg-brand-800/60"
                  >
                    <MapPin className="h-3.5 w-3.5 text-emerald-400" />
                    <span className="flex-1 truncate">{z.label}</span>
                    <span className="text-[11px] text-white/30">{z.cma}</span>
                  </button>
                ))}
              </div>
            ) : null}
          </div>
          {zones.length === 0 ? (
            <p className="mt-2 max-w-2xl rounded-lg border border-amber-500/30 bg-amber-500/5 px-3 py-2 text-xs text-amber-200">
              <Info className="mr-1 inline h-3.5 w-3.5" />
              Aucune donnée SCHL chargée. Importe le fichier dans{" "}
              <strong>Paramètres → Sources</strong>, puis reviens ici.
            </p>
          ) : null}
        </section>

        {/* Résultats */}
        {loading ? (
          <div className="mt-10 flex items-center justify-center text-white/50">
            <Loader2 className="mr-2 h-5 w-5 animate-spin" /> Recherche…
          </div>
        ) : result && !result.matched ? (
          <div className="mt-8 max-w-2xl rounded-2xl border border-brand-800 bg-brand-900 p-5">
            <p className="text-sm text-white/70">
              {result.notes[0] || "Aucun résultat."}
            </p>
            {result.suggestions.length > 0 ? (
              <div className="mt-3 flex flex-wrap gap-2">
                {result.suggestions.map((z) => (
                  <button
                    key={`${z.cma}::${z.zone ?? ""}`}
                    type="button"
                    onClick={() => void loadByZone(z)}
                    className="rounded-full border border-brand-800 bg-brand-950 px-3 py-1 text-xs text-emerald-300 hover:border-emerald-500/50"
                  >
                    {z.label}
                  </button>
                ))}
              </div>
            ) : null}
          </div>
        ) : result && result.matched ? (
          <div className="mt-8 grid gap-5 lg:grid-cols-3">
            {/* Colonne gauche : données du secteur */}
            <div className="space-y-5 lg:col-span-2">
              <div className="rounded-2xl border border-brand-800 bg-brand-900 p-5">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div>
                    <div className="flex items-center gap-2">
                      <MapPin className="h-4 w-4 text-emerald-400" />
                      <h2 className="text-lg font-bold text-white">
                        {secteurLabel}
                      </h2>
                    </div>
                    <p className="mt-0.5 text-xs text-white/50">
                      RMR : {result.cma}
                      {result.vacancy_rate != null
                        ? ` · Taux d'inoccupation ${(
                            result.vacancy_rate * 100
                          ).toFixed(1)} %`
                        : ""}
                    </p>
                  </div>
                  {result.year ? (
                    <span className="rounded-full border border-emerald-500/40 bg-emerald-500/10 px-3 py-1 text-xs font-semibold text-emerald-300">
                      Données SCHL {result.year}
                    </span>
                  ) : null}
                </div>

                <div className="mt-4 overflow-x-auto">
                  <table className="w-full min-w-[480px] text-sm">
                    <thead>
                      <tr className="border-b border-brand-800 text-left text-[11px] uppercase tracking-wider text-white/45">
                        <th className="py-2 pr-3 font-semibold">Type</th>
                        <th className="py-2 pr-3 font-semibold">Équivalent</th>
                        <th className="py-2 pr-3 text-right font-semibold">
                          Loyer moyen
                        </th>
                        <th className="py-2 text-right font-semibold">vs RMR</th>
                      </tr>
                    </thead>
                    <tbody>
                      {result.brackets.map((b) => {
                        const cmaRent = cmaByBed[b.bedrooms];
                        const diff =
                          b.avg_rent != null && cmaRent
                            ? (b.avg_rent - cmaRent) / cmaRent
                            : null;
                        return (
                          <tr
                            key={b.qc_label}
                            className="border-b border-brand-800/50"
                          >
                            <td className="py-2.5 pr-3">
                              <span className="font-bold text-white">
                                {b.qc_label}
                              </span>
                              {b.is_estimate ? (
                                <span
                                  className="ml-1 text-[10px] text-amber-300"
                                  title="La SCHL regroupe 5½/6½ dans « 3 chambres et + »"
                                >
                                  ~est.
                                </span>
                              ) : null}
                            </td>
                            <td className="py-2.5 pr-3 text-xs text-white/50">
                              {b.schl_label}
                            </td>
                            <td className="py-2.5 pr-3 text-right font-semibold tabular-nums text-white">
                              {b.avg_rent != null ? money(b.avg_rent) : "n/d"}
                            </td>
                            <td className="py-2.5 text-right">
                              {diff != null ? (
                                <span
                                  className={`inline-flex items-center gap-1 text-xs font-semibold ${
                                    Math.abs(diff) < 0.005
                                      ? "text-white/40"
                                      : diff > 0
                                        ? "text-rose-300"
                                        : "text-emerald-300"
                                  }`}
                                >
                                  {Math.abs(diff) < 0.005 ? (
                                    <Minus className="h-3 w-3" />
                                  ) : diff > 0 ? (
                                    <TrendingUp className="h-3 w-3" />
                                  ) : (
                                    <TrendingDown className="h-3 w-3" />
                                  )}
                                  {diff > 0 ? "+" : ""}
                                  {(diff * 100).toFixed(0)} %
                                </span>
                              ) : (
                                <span className="text-white/30">—</span>
                              )}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>

                {result.notes.length > 0 ? (
                  <p className="mt-3 text-[11px] text-white/40">
                    {result.notes.join(" ")}
                  </p>
                ) : null}
                <p className="mt-1 text-[11px] text-white/30">
                  « vs RMR » = écart du secteur par rapport à la moyenne de toute
                  la région métropolitaine. ~est. : 5½/6½ estimés via le bracket
                  « 3 chambres et + ».
                </p>
              </div>

              {/* Compare ton loyer */}
              <div className="rounded-2xl border border-brand-800 bg-brand-900 p-5">
                <h3 className="flex items-center gap-2 text-sm font-semibold text-white">
                  <TrendingUp className="h-4 w-4 text-emerald-400" />
                  Compare un loyer au marché
                </h3>
                <div className="mt-3 flex flex-wrap items-end gap-3">
                  <div>
                    <label className="mb-1 block text-[11px] text-white/50">
                      Loyer actuel ($/mois)
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
                      value={monType}
                      onChange={(e) => setMonType(e.target.value)}
                      className="rounded-lg border border-brand-800 bg-brand-950 px-3 py-2 text-sm text-white outline-none focus:border-emerald-500/60"
                    >
                      {result.brackets.map((b) => (
                        <option key={b.qc_label} value={b.qc_label}>
                          {b.qc_label} ({b.schl_label})
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
                      {(compare.diff * 100).toFixed(0)} % vs marché (
                      {money(compare.market)})
                    </div>
                  ) : null}
                </div>
              </div>
            </div>

            {/* Colonne droite : calculateur de revenus */}
            <div className="space-y-5">
              <div className="rounded-2xl border border-brand-800 bg-brand-900 p-5">
                <h3 className="flex items-center gap-2 text-sm font-semibold text-white">
                  <Calculator className="h-4 w-4 text-emerald-400" />
                  Revenu potentiel d&apos;un immeuble
                </h3>
                <p className="mt-1 text-[11px] text-white/45">
                  Entre le nombre de logements par type pour estimer le revenu
                  locatif au prix du marché.
                </p>
                <div className="mt-3 space-y-2">
                  {result.brackets
                    .filter((b) => b.avg_rent != null)
                    .map((b) => (
                      <div
                        key={b.qc_label}
                        className="flex items-center justify-between gap-2"
                      >
                        <span className="text-sm text-white/70">
                          {b.qc_label}
                          <span className="ml-1 text-[11px] text-white/35">
                            {money(b.avg_rent)}
                          </span>
                        </span>
                        <input
                          value={mix[b.qc_label] || ""}
                          onChange={(e) =>
                            setMix((m) => ({
                              ...m,
                              [b.qc_label]: e.target.value.replace(/[^0-9]/g, "")
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
                    Prix demandé / payé ($) — pour le multiplicateur (GRM)
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
                      <span className="text-white/60">GRM (prix / revenu)</span>
                      <span className="font-bold text-white">
                        {grm.toFixed(1)}{" "}
                        <span
                          className={
                            GRM_TIERS.find((t) => grm < t.max)?.cls ??
                            "text-white/60"
                          }
                        >
                          ·{" "}
                          {GRM_TIERS.find((t) => grm < t.max)?.label ?? ""}
                        </span>
                      </span>
                    </div>
                  ) : null}
                </div>
              </div>

              <div className="rounded-2xl border border-brand-800 bg-brand-900 p-4 text-[11px] text-white/45">
                <Info className="mb-1 inline h-3.5 w-3.5 text-white/40" /> Les
                loyers sont des <strong>moyennes SCHL</strong> du parc existant —
                un logement rénové ou neuf se loue souvent au-dessus. Sers-t&apos;en
                comme plancher de référence, pas comme plafond.
              </div>
            </div>
          </div>
        ) : (
          <div className="mt-10 max-w-2xl rounded-2xl border border-dashed border-brand-800 p-8 text-center text-white/50">
            <Building2 className="mx-auto h-8 w-8 opacity-40" />
            <p className="mt-3 text-sm">
              Tape une adresse ou un secteur ci-dessus pour voir les loyers
              moyens du marché.
            </p>
          </div>
        )}
      </div>
    </>
  );
}
