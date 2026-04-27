"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { Calculator, Loader2 } from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { Link } from "@/i18n/navigation";
import { authedFetch } from "@/lib/auth";
import type {
  AnalyseInputs,
  AnalyseResultats,
  ScenarioResultat
} from "@/lib/financial-calculator";
import { useProspectionLayout } from "../../layout";

type AnalyseRead = {
  id: number;
  lead_id: number | null;
  name: string;
  inputs: AnalyseInputs;
  results: AnalyseResultats;
  created_at: string;
  updated_at: string;
};

function fmt$(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  return n.toLocaleString("fr-CA", {
    style: "currency",
    currency: "CAD",
    maximumFractionDigits: 0
  });
}

function fmtPct(n: number): string {
  return `${(n * 100).toFixed(2)} %`;
}

export default function AnalyseDetailPage() {
  const params = useParams<{ id: string }>();
  const id = params?.id;
  const { onOpenSidebar } = useProspectionLayout();
  const [analyse, setAnalyse] = useState<AnalyseRead | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!id) return;
    void (async () => {
      setLoading(true);
      setError(null);
      try {
        const res = await authedFetch(
          `/api/v1/prospection/analyses/${id}`
        );
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        setAnalyse((await res.json()) as AnalyseRead);
      } catch (e) {
        setError(e instanceof Error ? e.message : "Erreur");
      } finally {
        setLoading(false);
      }
    })();
  }, [id]);

  return (
    <>
      <AppTopbar
        breadcrumbs={[
          { label: "Prospection", href: "/prospection" },
          { label: "Analyses", href: "/prospection/analyse" },
          { label: analyse?.name || "Analyse" }
        ]}
        onOpenSidebar={onOpenSidebar}
      />
      <div className="px-4 py-6 lg:px-6">
        {loading ? (
          <div className="flex items-center gap-2 text-sm text-white/50">
            <Loader2 className="h-4 w-4 animate-spin" /> Chargement…
          </div>
        ) : error ? (
          <p className="rounded-lg border border-red-500/40 bg-red-500/10 p-4 text-sm text-red-300">
            {error}
          </p>
        ) : !analyse ? null : (
          <Detail analyse={analyse} />
        )}
      </div>
    </>
  );
}

function Detail({ analyse }: { analyse: AnalyseRead }) {
  const { inputs, results } = analyse;
  return (
    <>
      <header className="mb-6 flex flex-wrap items-center gap-3">
        <Calculator className="h-6 w-6 text-emerald-400" />
        <h1 className="text-xl font-bold text-white">{analyse.name}</h1>
        <span className="rounded-full bg-emerald-500/10 px-2 py-0.5 text-xs text-emerald-300">
          {inputs.nombreLogements} logements
        </span>
        {analyse.lead_id ? (
          <Link
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            href={`/prospection/${analyse.lead_id}` as any}
            className="ml-auto text-xs text-emerald-300 hover:text-emerald-200"
          >
            ← Retour à la fiche lead
          </Link>
        ) : null}
      </header>

      <div className="mb-6 grid grid-cols-2 gap-3 md:grid-cols-4">
        <Kpi label="Prix d'achat" value={fmt$(inputs.prixAchat)} />
        <Kpi
          label="Revenus actuels"
          value={fmt$(inputs.revenusAnnuels)}
        />
        <Kpi label="TGA" value={fmtPct(inputs.tga)} />
        <Kpi
          label="Frais démarrage (×3)"
          value={fmt$(results.achat.fraisDemarrageTotal)}
        />
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <ScenarioCard scenario={results.achat} />
        <ScenarioCard scenario={results.schl} />
        <ScenarioCard scenario={results.aph50} />
      </div>

      <DepensesTable results={results} inputs={inputs} />
    </>
  );
}

function Kpi({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-brand-800 bg-brand-900/40 p-3">
      <p className="text-[11px] uppercase tracking-wider text-white/50">
        {label}
      </p>
      <p className="mt-1 text-base font-bold tabular-nums text-white">
        {value}
      </p>
    </div>
  );
}

function ScenarioCard({ scenario }: { scenario: ScenarioResultat }) {
  const isRefi = scenario.id !== "achat";
  const keyValue = isRefi
    ? scenario.gainActionnaires ?? 0
    : scenario.miseDeFonds ?? 0;
  const tone = !isRefi
    ? "neutral"
    : keyValue >= 0
    ? "positive"
    : "negative";
  const ring =
    tone === "positive"
      ? "border-emerald-700/40 bg-emerald-500/5"
      : tone === "negative"
      ? "border-red-700/40 bg-red-500/5"
      : "border-brand-800 bg-brand-900/40";

  return (
    <div className={`rounded-xl border p-4 ${ring}`}>
      <h3 className="text-sm font-semibold text-white">{scenario.label}</h3>

      <div className="mt-3 border-y border-white/5 py-3">
        <p className="text-[10px] uppercase tracking-wider text-white/50">
          {isRefi ? "Gain actionnaires" : "Mise de fonds"}
        </p>
        <p
          className={`text-2xl font-bold tabular-nums ${
            tone === "positive"
              ? "text-emerald-300"
              : tone === "negative"
              ? "text-red-300"
              : "text-white"
          }`}
        >
          {fmt$(keyValue)}
        </p>
      </div>

      <dl className="mt-3 space-y-1 text-xs">
        <Row k="Prêt accordé" v={fmt$(scenario.pretAccorde)} />
        <Row k="Prix acquisition" v={fmt$(scenario.prixAcquisition)} />
        <Row k="Valeur retenue" v={fmt$(scenario.valeurRetenue)} />
        <Row
          k="Valeur économique TGA"
          v={fmt$(scenario.valeurEconomiqueTGA)}
        />
        <Row
          k="Valeur économique RCD"
          v={fmt$(scenario.valeurEconomiqueRCD)}
        />
        <Row k="Hypothèque max RCD" v={fmt$(scenario.hypothequeMaxRCD)} />
        <Row k="Revenus nets" v={fmt$(scenario.revenusNets)} />
        <Row k="RCD" v={scenario.ratioCouvertureDette.toString()} />
        <Row
          k="Ratio prêt / valeur"
          v={`${(scenario.ratioPretValeur * 100).toFixed(0)} %`}
        />
        <Row k="Amortissement" v={`${scenario.amortissementAnnees} ans`} />
        <Row k="Taux d'intérêt" v={fmtPct(scenario.tauxInteret)} />
      </dl>
    </div>
  );
}

function Row({ k, v }: { k: string; v: string }) {
  return (
    <div className="flex items-center justify-between">
      <dt className="text-white/60">{k}</dt>
      <dd className="tabular-nums text-white/85">{v}</dd>
    </div>
  );
}

function DepensesTable({
  results,
  inputs
}: {
  results: AnalyseResultats;
  inputs: AnalyseInputs;
}) {
  const rows: Array<[keyof AnalyseResultats["achat"]["depensesNormalisees"], string]> = [
    ["inoccupation", "Inoccupation (3 %)"],
    ["taxesMunicipales", "Taxes municipales"],
    ["taxesScolaires", "Taxes scolaires"],
    ["assurances", "Assurances"],
    ["energie", "Énergie"],
    ["concierge", "Concierge"],
    ["entretien", "Entretien"],
    ["gestion", "Gestion"],
    ["wifi", "WIFI"],
    ["thermopompes", "Thermopompes"],
    ["autres", "Autres"],
    ["total", "Total"]
  ];
  return (
    <section className="mt-6 overflow-hidden rounded-xl border border-brand-800">
      <h3 className="border-b border-brand-800 bg-brand-900/60 px-4 py-2 text-xs font-semibold uppercase tracking-wider text-white/60">
        Détail des dépenses normalisées
      </h3>
      <table className="min-w-full divide-y divide-brand-800/60 text-sm">
        <thead className="bg-brand-900/30 text-left text-xs uppercase tracking-wider text-white/50">
          <tr>
            <th className="px-4 py-2">Poste</th>
            <th className="px-4 py-2 text-right">Achat</th>
            <th className="px-4 py-2 text-right">SCHL</th>
            <th className="px-4 py-2 text-right">APH 50</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-brand-800/40">
          {rows.map(([k, label]) => {
            const isTotal = k === "total";
            return (
              <tr
                key={k as string}
                className={
                  isTotal ? "bg-brand-900/40 font-bold" : "hover:bg-brand-900/30"
                }
              >
                <td className="px-4 py-2 text-white/70">{label}</td>
                <td className="px-4 py-2 text-right tabular-nums text-white/85">
                  {fmt$(results.achat.depensesNormalisees[k])}
                </td>
                <td className="px-4 py-2 text-right tabular-nums text-white/85">
                  {fmt$(results.schl.depensesNormalisees[k])}
                </td>
                <td className="px-4 py-2 text-right tabular-nums text-white/85">
                  {fmt$(results.aph50.depensesNormalisees[k])}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </section>
  );
}
