"use client";

import { useEffect, useState } from "react";
import {
  Building2,
  DollarSign,
  Loader2,
  Percent,
  Sparkles,
  TrendingUp,
  Wallet
} from "lucide-react";

import { Link } from "@/i18n/navigation";
import { authedFetch } from "@/lib/auth";
import { PageDriveSection } from "@/components/drive/PageDriveSection";
import { InvestisseurTopbar } from "./layout";

type Investissement = {
  id: number;
  immeuble_id: number;
  immeuble_name: string;
  immeuble_address: string;
  immeuble_cover_photo_url?: string | null;
  montant_investi: number;
  parts_pct: number;
  date_investissement: string;
  status: string;
  total_distributions: number;
  nb_distributions: number;
  valeur_part_courante?: number | null;
  dpi?: number | null;
  tvpi?: number | null;
  rendement_annuel_estime?: number | null;
};

type Portefeuille = {
  user_id: number;
  nb_investissements: number;
  total_capital_investi: number;
  total_distributions: number;
  valeur_portefeuille_courante: number;
  dpi_global?: number | null;
  tvpi_global?: number | null;
  investissements: Investissement[];
};

function fmtCurrency(n: number | null | undefined): string {
  if (n == null) return "—";
  return new Intl.NumberFormat("fr-CA", {
    style: "currency",
    currency: "CAD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2
  }).format(n);
}

function fmtMultiple(n: number | null | undefined): string {
  if (n == null) return "—";
  return `${n.toFixed(2)}×`;
}

function fmtPct(n: number | null | undefined): string {
  if (n == null) return "—";
  return `${n.toFixed(1)}%`;
}

export default function InvestisseurPortefeuille() {
  const [data, setData] = useState<Portefeuille | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const res = await authedFetch(
          "/api/v1/investissements/me/portefeuille"
        );
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const d = (await res.json()) as Portefeuille;
        if (!cancelled) setData(d);
      } catch (err) {
        if (!cancelled) setError((err as Error).message);
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <>
      <InvestisseurTopbar
        breadcrumbs={[{ label: "Mon portefeuille" }]}
      />
      <div className="p-4 lg:p-6">
        <header className="flex items-start gap-3">
          <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-accent-500/15 text-accent-500">
            <Wallet className="h-5 w-5" />
          </span>
          <div>
            <h1 className="text-2xl font-bold text-white">Mon portefeuille</h1>
            <p className="mt-1 max-w-2xl text-sm text-white/60">
              Vue consolidée de tes participations dans le portefeuille
              Horizon : capital investi, distributions reçues, valeur
              estimée des parts.
            </p>
          </div>
        </header>

        <PageDriveSection
          pageKey="page:investisseur:portail"
          pole="Investisseurs"
          label="Portail investisseurs"
          route="/investisseur"
          className="mt-6"
        />

        {error ? (
          <p className="mt-4 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
            {error}
          </p>
        ) : null}

        {data === null && !error ? (
          <div className="mt-6 flex items-center gap-2 text-xs text-white/50">
            <Loader2 className="h-3.5 w-3.5 animate-spin" /> Chargement…
          </div>
        ) : null}

        {data ? (
          <>
            <section className="mt-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <Kpi
                label="Capital investi"
                value={fmtCurrency(data.total_capital_investi)}
                sub={`${data.nb_investissements} investissement${
                  data.nb_investissements > 1 ? "s" : ""
                }`}
                icon={DollarSign}
                tone="emerald"
              />
              <Kpi
                label="Distributions reçues"
                value={fmtCurrency(data.total_distributions)}
                sub={`DPI ${fmtMultiple(data.dpi_global)}`}
                icon={Wallet}
                tone="violet"
              />
              <Kpi
                label="Valeur des parts"
                value={fmtCurrency(data.valeur_portefeuille_courante)}
                sub="estimation courante"
                icon={Building2}
                tone="sky"
              />
              <Kpi
                label="TVPI global"
                value={fmtMultiple(data.tvpi_global)}
                sub="(distrib. + valeur) / capital"
                icon={TrendingUp}
                tone={
                  (data.tvpi_global || 0) >= 1.2
                    ? "emerald"
                    : (data.tvpi_global || 0) >= 1
                    ? "amber"
                    : "rose"
                }
              />
            </section>

            <section className="mt-8">
              <h2 className="mb-3 text-sm font-semibold uppercase tracking-wider text-accent-500">
                Investissements
              </h2>
              {data.investissements.length === 0 ? (
                <EmptyState />
              ) : (
                <ul className="grid gap-3 lg:grid-cols-2">
                  {data.investissements.map((inv) => (
                    <InvestissementCard key={inv.id} inv={inv} />
                  ))}
                </ul>
              )}
            </section>
          </>
        ) : null}
      </div>
    </>
  );
}

function Kpi({
  label,
  value,
  sub,
  icon: Icon,
  tone
}: {
  label: string;
  value: string;
  sub?: string;
  icon: React.ComponentType<{ className?: string }>;
  tone: "emerald" | "violet" | "sky" | "amber" | "rose";
}) {
  const cls: Record<typeof tone, string> = {
    emerald: "bg-emerald-500/15 text-emerald-300",
    violet: "bg-violet-500/15 text-violet-300",
    sky: "bg-sky-500/15 text-sky-300",
    amber: "bg-amber-500/15 text-amber-300",
    rose: "bg-rose-500/15 text-rose-300"
  };
  return (
    <div className="rounded-2xl border border-brand-800 bg-brand-900 p-4">
      <div className="flex items-center justify-between">
        <span className="text-[10px] font-semibold uppercase tracking-wider text-white/50">
          {label}
        </span>
        <span
          className={`flex h-8 w-8 items-center justify-center rounded-lg ${cls[tone]}`}
        >
          <Icon className="h-4 w-4" />
        </span>
      </div>
      <div className="mt-3 text-2xl font-bold text-white">{value}</div>
      {sub ? <div className="mt-1 text-xs text-white/50">{sub}</div> : null}
    </div>
  );
}

function InvestissementCard({ inv }: { inv: Investissement }) {
  const tvpiOk = (inv.tvpi || 0) >= 1.2;
  return (
    <li className="rounded-2xl border border-brand-800 bg-brand-900 p-4">
      <div className="flex items-start gap-3">
        <div className="h-14 w-14 flex-shrink-0 overflow-hidden rounded-lg bg-brand-950">
          {inv.immeuble_cover_photo_url ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={inv.immeuble_cover_photo_url}
              alt={inv.immeuble_name}
              className="h-full w-full object-cover"
            />
          ) : (
            <div className="flex h-full w-full items-center justify-center text-white/30">
              <Building2 className="h-6 w-6" />
            </div>
          )}
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <h3 className="truncate text-base font-bold text-white">
              {inv.immeuble_name}
            </h3>
            {inv.status !== "actif" ? (
              <span className="rounded-full border border-white/15 px-1.5 py-0.5 text-[10px] uppercase text-white/50">
                {inv.status}
              </span>
            ) : null}
          </div>
          <p className="truncate text-[11px] text-white/50">
            {inv.immeuble_address}
          </p>
          <p className="mt-1 text-[11px] text-white/40">
            Investi le {inv.date_investissement} ·{" "}
            {inv.parts_pct.toFixed(2)}% des parts
          </p>
        </div>
      </div>

      <dl className="mt-4 grid grid-cols-2 gap-y-2 border-t border-brand-800 pt-3 text-sm">
        <dt className="text-white/50">Capital investi</dt>
        <dd className="text-right font-mono text-white">
          {fmtCurrency(inv.montant_investi)}
        </dd>
        <dt className="text-white/50">
          Distributions ({inv.nb_distributions})
        </dt>
        <dd className="text-right font-mono text-emerald-300">
          {fmtCurrency(inv.total_distributions)}
        </dd>
        <dt className="text-white/50">Valeur de la part</dt>
        <dd className="text-right font-mono text-white">
          {fmtCurrency(inv.valeur_part_courante)}
        </dd>
        <dt className="text-white/50">DPI</dt>
        <dd className="text-right font-mono text-white">
          {fmtMultiple(inv.dpi)}
        </dd>
        <dt className="text-white/50">TVPI</dt>
        <dd
          className={`text-right font-mono font-bold ${
            tvpiOk ? "text-emerald-300" : "text-amber-300"
          }`}
        >
          {fmtMultiple(inv.tvpi)}
        </dd>
        <dt className="text-white/50">
          <Percent className="mr-1 inline h-3 w-3" />
          Rendement annualisé
        </dt>
        <dd
          className={`text-right font-mono ${
            (inv.rendement_annuel_estime || 0) >= 0
              ? "text-emerald-300"
              : "text-rose-300"
          }`}
        >
          {fmtPct(inv.rendement_annuel_estime)}
        </dd>
      </dl>
    </li>
  );
}

function EmptyState() {
  return (
    <div className="rounded-2xl border border-dashed border-brand-800 bg-brand-900/40 p-8 text-center">
      <Wallet className="mx-auto h-10 w-10 text-white/30" />
      <h3 className="mt-3 text-sm font-bold text-white">
        Aucun investissement enregistré
      </h3>
      <p className="mt-1 text-xs text-white/60">
        Les administrateurs créent les investissements au closing — ils
        apparaîtront automatiquement ici.
      </p>
      <p className="mt-4 inline-flex items-center gap-2 rounded-full border border-emerald-400/30 bg-emerald-500/10 px-3 py-1 text-[11px] font-semibold text-emerald-200">
        <Sparkles className="h-3 w-3" />
        Volet en lancement progressif
      </p>
      <Link
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        href={"/connexion" as any}
        className="mt-4 block text-[11px] text-white/40 hover:text-white/60"
      >
        Retour à l&apos;accueil portail
      </Link>
    </div>
  );
}
