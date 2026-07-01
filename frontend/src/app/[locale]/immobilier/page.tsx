"use client";

import { type ReactNode, useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  Building2,
  CalendarClock,
  DollarSign,
  Home,
  Loader2,
  Plus,
  ShieldCheck,
  TrendingUp,
  Users,
  Wrench
} from "lucide-react";

import { Link } from "@/i18n/navigation";
import { authedFetch, getToken } from "@/lib/auth";
import { PageDriveSection } from "@/components/drive/PageDriveSection";
import { ImmobilierTopbar, useImmobilierLayout } from "./layout";

type ImmeubleListItem = {
  id: number;
  name: string;
  address: string;
  city?: string | null;
  type: string;
  nb_logements?: number | null;
  cover_photo_url?: string | null;
  has_cover_photo?: boolean;
  is_active: boolean;
  nb_logements_actifs: number;
  nb_logements_occupes: number;
  revenu_mensuel: number;
  taux_occupation: number;
};

function fmtCurrency(n: number): string {
  return new Intl.NumberFormat("fr-CA", {
    style: "currency",
    currency: "CAD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2
  }).format(n);
}

function fmtPct(n: number): string {
  return `${(n * 100).toFixed(0)}%`;
}

function fmtCompact(n: number): string {
  return n.toLocaleString("fr-CA", {
    style: "currency",
    currency: "CAD",
    maximumFractionDigits: 0
  });
}

function ATraiterTile({
  href,
  icon,
  label,
  count,
  sub,
  tone
}: {
  href: string;
  icon: ReactNode;
  label: string;
  count: number;
  sub: string;
  tone: "rose" | "amber" | "orange" | "violet";
}) {
  const active = count > 0;
  const toneCls = active
    ? {
        rose: "border-rose-500/40 bg-rose-500/10 text-rose-200",
        amber: "border-amber-500/40 bg-amber-500/10 text-amber-200",
        orange: "border-orange-500/40 bg-orange-500/10 text-orange-200",
        violet: "border-violet-500/40 bg-violet-500/10 text-violet-200"
      }[tone]
    : "border-brand-800 bg-brand-900 text-white/45";
  return (
    <Link
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      href={href as any}
      className={`block rounded-2xl border p-4 transition hover:brightness-125 ${toneCls}`}
    >
      <div className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wider opacity-80">
        {icon}
        {label}
      </div>
      <div className="mt-1 text-3xl font-bold">{count}</div>
      <div className="text-[11px] opacity-70">{sub}</div>
    </Link>
  );
}

type ATraiter = {
  loyers_retard_nb: number;
  loyers_retard_total: number;
  baux_a_renouveler_nb: number;
  maintenance_urgente_nb: number;
  depots_a_rendre_nb: number;
  depots_a_rendre_total: number;
};

export default function ImmobilierDashboard() {
  const { currentEntrepriseId } = useImmobilierLayout();
  const [list, setList] = useState<ImmeubleListItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [aTraiter, setATraiter] = useState<ATraiter | null>(null);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const r = await authedFetch("/api/v1/immobilier/a-traiter");
        if (r.ok && !cancelled) setATraiter((await r.json()) as ATraiter);
      } catch {
        /* silencieux : le cockpit est secondaire */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [currentEntrepriseId]);

  useEffect(() => {
    let cancelled = false;
    setList(null);
    async function load() {
      try {
        const url =
          currentEntrepriseId != null
            ? `/api/v1/immobilier/immeubles?entreprise_id=${currentEntrepriseId}`
            : "/api/v1/immobilier/immeubles";
        const res = await authedFetch(url);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = (await res.json()) as ImmeubleListItem[];
        if (!cancelled) setList(data);
      } catch (err) {
        if (!cancelled) setError((err as Error).message);
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [currentEntrepriseId]);

  const kpis = useMemo(() => {
    if (!list)
      return {
        nbImmeubles: 0,
        nbLogements: 0,
        nbOccupes: 0,
        revenu: 0,
        taux: 0
      };
    const nbI = list.length;
    const nbL = list.reduce((acc, x) => acc + x.nb_logements_actifs, 0);
    const nbO = list.reduce((acc, x) => acc + x.nb_logements_occupes, 0);
    const rev = list.reduce((acc, x) => acc + x.revenu_mensuel, 0);
    const tx = nbL > 0 ? nbO / nbL : 0;
    return {
      nbImmeubles: nbI,
      nbLogements: nbL,
      nbOccupes: nbO,
      revenu: rev,
      taux: tx
    };
  }, [list]);

  return (
    <>
      <ImmobilierTopbar
        breadcrumbs={[{ label: "Gestion immobilière" }]}
        rightSlot={
          <Link
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            href={"/immobilier/immeubles" as any}
            className="inline-flex items-center gap-1.5 rounded-lg border border-sky-400/30 bg-sky-500/10 px-3 py-1.5 text-xs font-semibold text-sky-200 hover:bg-sky-500/20"
          >
            <Plus className="h-3.5 w-3.5" />
            Nouvel immeuble
          </Link>
        }
      />
      <div className="p-4 lg:p-6">
        <header className="flex items-start gap-3">
          <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-sky-500/15 text-sky-300">
            <Building2 className="h-5 w-5" />
          </span>
          <div>
            <h1 className="text-2xl font-bold text-white">
              Gestion immobilière
            </h1>
            <p className="mt-1 max-w-2xl text-sm text-white/60">
              Vue d&apos;ensemble du portefeuille : occupation, revenus
              mensuels, immeubles à surveiller.
            </p>
          </div>
        </header>

        {aTraiter ? (
          <section className="mt-6">
            <h2 className="mb-2 text-xs font-semibold uppercase tracking-wider text-white/45">
              À traiter
            </h2>
            <div className="grid gap-3 grid-cols-2 lg:grid-cols-4">
              <ATraiterTile
                href="/immobilier/baux"
                icon={<AlertTriangle className="h-4 w-4" />}
                label="Loyers en retard"
                count={aTraiter.loyers_retard_nb}
                sub={
                  aTraiter.loyers_retard_nb > 0
                    ? fmtCompact(aTraiter.loyers_retard_total)
                    : "rien à relancer"
                }
                tone="rose"
              />
              <ATraiterTile
                href="/immobilier/renouvellements"
                icon={<CalendarClock className="h-4 w-4" />}
                label="Baux à renouveler"
                count={aTraiter.baux_a_renouveler_nb}
                sub={
                  aTraiter.baux_a_renouveler_nb > 0
                    ? "avis à envoyer"
                    : "à jour"
                }
                tone="amber"
              />
              <ATraiterTile
                href="/immobilier/bons-travail"
                icon={<Wrench className="h-4 w-4" />}
                label="Maintenance urgente"
                count={aTraiter.maintenance_urgente_nb}
                sub={
                  aTraiter.maintenance_urgente_nb > 0
                    ? "ordres ouverts"
                    : "rien d'urgent"
                }
                tone="orange"
              />
              <ATraiterTile
                href="/immobilier/depots"
                icon={<ShieldCheck className="h-4 w-4" />}
                label="Dépôts à rendre"
                count={aTraiter.depots_a_rendre_nb}
                sub={
                  aTraiter.depots_a_rendre_nb > 0
                    ? fmtCompact(aTraiter.depots_a_rendre_total)
                    : "rien à rembourser"
                }
                tone="violet"
              />
            </div>
          </section>
        ) : null}

        <PageDriveSection
          pageKey="page:immobilier:vue-ensemble"
          pole="Gestion immobilière"
          label="Vue d'ensemble"
          route="/immobilier"
          className="mt-6"
        />

        {error ? (
          <p className="mt-4 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
            {error}
          </p>
        ) : null}

        {/* KPI cards */}
        <section className="mt-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <KpiCard
            label="Immeubles actifs"
            value={String(kpis.nbImmeubles)}
            icon={Building2}
            tone="sky"
          />
          <KpiCard
            label="Logements"
            value={`${kpis.nbOccupes} / ${kpis.nbLogements}`}
            sub={`Occupation ${fmtPct(kpis.taux)}`}
            icon={Home}
            tone="emerald"
          />
          <KpiCard
            label="Revenu mensuel"
            value={fmtCurrency(kpis.revenu)}
            sub={`${fmtCurrency(kpis.revenu * 12)} / an`}
            icon={DollarSign}
            tone="violet"
          />
          <KpiCard
            label="Taux d'occupation"
            value={fmtPct(kpis.taux)}
            icon={TrendingUp}
            tone={kpis.taux >= 0.95 ? "emerald" : "amber"}
          />
        </section>

        {/* Liste immeubles */}
        <section className="mt-8">
          <div className="mb-3 flex items-center justify-between">
            <h2 className="text-sm font-semibold uppercase tracking-wider text-sky-300">
              Portefeuille
            </h2>
            <Link
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
              href={"/immobilier/immeubles" as any}
              className="text-xs text-white/60 hover:text-sky-300"
            >
              Voir tout →
            </Link>
          </div>

          {list === null ? (
            <div className="flex items-center gap-2 text-xs text-white/50">
              <Loader2 className="h-3.5 w-3.5 animate-spin" /> Chargement…
            </div>
          ) : list.length === 0 ? (
            <EmptyState />
          ) : (
            <ul className="grid gap-3 lg:grid-cols-2">
              {list.slice(0, 6).map((imm) => (
                <ImmeubleRow key={imm.id} imm={imm} />
              ))}
            </ul>
          )}
        </section>
      </div>
    </>
  );
}

function KpiCard({
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
  tone: "sky" | "emerald" | "violet" | "amber";
}) {
  const toneCls: Record<typeof tone, string> = {
    sky: "bg-sky-500/15 text-sky-300",
    emerald: "bg-emerald-500/15 text-emerald-300",
    violet: "bg-violet-500/15 text-violet-300",
    amber: "bg-amber-500/15 text-amber-300"
  };
  return (
    <div className="rounded-2xl border border-brand-800 bg-brand-900 p-4">
      <div className="flex items-center justify-between">
        <span className="text-[10px] font-semibold uppercase tracking-wider text-white/50">
          {label}
        </span>
        <span
          className={`flex h-8 w-8 items-center justify-center rounded-lg ${toneCls[tone]}`}
        >
          <Icon className="h-4 w-4" />
        </span>
      </div>
      <div className="mt-3 text-2xl font-bold text-white">{value}</div>
      {sub ? <div className="mt-1 text-xs text-white/50">{sub}</div> : null}
    </div>
  );
}

function ImmeubleRow({ imm }: { imm: ImmeubleListItem }) {
  const taux = fmtPct(imm.taux_occupation);
  const tauxOk = imm.taux_occupation >= 0.9;
  return (
    <li>
      <Link
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        href={`/immobilier/immeubles/${imm.id}` as any}
        className="flex items-center gap-3 rounded-xl border border-brand-800 bg-brand-900 p-3 transition hover:border-sky-400/40"
      >
        <div className="h-14 w-14 flex-shrink-0 overflow-hidden rounded-lg bg-brand-950">
          {imm.has_cover_photo || imm.cover_photo_url ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={
                imm.has_cover_photo
                  ? `/api/v1/immobilier/immeubles/${imm.id}/cover-photo?t=${getToken() || ""}`
                  : (imm.cover_photo_url as string)
              }
              alt={imm.name}
              className="h-full w-full object-cover"
            />
          ) : (
            <div className="flex h-full w-full items-center justify-center text-white/30">
              <Building2 className="h-6 w-6" />
            </div>
          )}
        </div>
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm font-bold text-white">
            {imm.name}
          </div>
          <div className="truncate text-[11px] text-white/50">
            {imm.address}
            {imm.city ? `, ${imm.city}` : ""}
          </div>
          <div className="mt-1 flex flex-wrap items-center gap-1.5 text-[10px]">
            <span className="rounded bg-brand-950 px-1.5 py-0.5 font-mono text-white/60">
              {imm.nb_logements_occupes}/{imm.nb_logements_actifs} occ.
            </span>
            <span
              className={`rounded px-1.5 py-0.5 font-mono ${
                tauxOk ? "bg-emerald-500/15 text-emerald-300" : "bg-amber-500/15 text-amber-300"
              }`}
            >
              {taux}
            </span>
            <span className="rounded bg-brand-950 px-1.5 py-0.5 font-mono text-white/60">
              {fmtCurrency(imm.revenu_mensuel)}/m
            </span>
          </div>
        </div>
      </Link>
    </li>
  );
}

function EmptyState() {
  return (
    <div className="rounded-2xl border border-dashed border-brand-800 bg-brand-900/40 p-8 text-center">
      <Building2 className="mx-auto h-10 w-10 text-white/30" />
      <h3 className="mt-3 text-sm font-bold text-white">
        Aucun immeuble dans le portefeuille
      </h3>
      <p className="mt-1 text-xs text-white/60">
        Ajoute ton premier immeuble manuellement ou importe-le depuis le
        rôle d&apos;évaluation MAMH (matricule).
      </p>
      <Link
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        href={"/immobilier/immeubles" as any}
        className="mt-4 inline-flex items-center gap-1.5 rounded-lg border border-sky-400/30 bg-sky-500/10 px-3 py-1.5 text-xs font-semibold text-sky-200 hover:bg-sky-500/20"
      >
        <Plus className="h-3.5 w-3.5" />
        Ajouter un immeuble
      </Link>
    </div>
  );
}
