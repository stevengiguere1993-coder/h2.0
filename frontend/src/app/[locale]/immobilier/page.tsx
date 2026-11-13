"use client";

import { type ReactNode, useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  Building2,
  CalendarCheck,
  CalendarClock,
  CheckCircle2,
  DollarSign,
  Home,
  Loader2,
  Plus,
  RefreshCw,
  ShieldCheck,
  TrendingUp,
  Wrench
} from "lucide-react";

import { Link } from "@/i18n/navigation";
import { authedFetch, getToken } from "@/lib/auth";
import { PageDriveSection } from "@/components/drive/PageDriveSection";
import { useAujourdhuiImmobilier } from "@/hooks/use-aujourdhui-immobilier";
import { useCurrentUser } from "@/hooks/use-current-user";
import { useNavAccess } from "@/hooks/use-nav-access";
import { usePresentationImmobilier } from "@/hooks/use-presentation-immobilier";
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
  /** Chambres (retour partenaire 2026-09-28). */
  nb_logements_en_chambres?: number;
  nb_chambres?: number;
  nb_chambres_occupees?: number;
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

/** Immeubles du portefeuille (entreprise active) et chiffres clés —
 *  partagés par la vue d'ensemble actuelle et la page « Aujourd'hui ». */
function usePortefeuille(currentEntrepriseId: number | null) {
  const [list, setList] = useState<ImmeubleListItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);

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
        taux: 0,
        nbLogEnChambres: 0,
        nbChambres: 0,
        nbChambresOcc: 0,
        unites: 0
      };
    const nbI = list.length;
    const nbL = list.reduce((acc, x) => acc + x.nb_logements_actifs, 0);
    const nbO = list.reduce((acc, x) => acc + x.nb_logements_occupes, 0);
    const rev = list.reduce((acc, x) => acc + x.revenu_mensuel, 0);
    const tx = nbL > 0 ? nbO / nbL : 0;
    // Chambres : un logement loué en chambres vaut ses chambres, pas
    // une porte (retour partenaire 2026-09-28). Unités locatives =
    // logements entiers + chambres.
    const nbLC = list.reduce(
      (acc, x) => acc + (x.nb_logements_en_chambres || 0),
      0
    );
    const nbC = list.reduce((acc, x) => acc + (x.nb_chambres || 0), 0);
    const nbCO = list.reduce(
      (acc, x) => acc + (x.nb_chambres_occupees || 0),
      0
    );
    return {
      nbImmeubles: nbI,
      nbLogements: nbL,
      nbOccupes: nbO,
      revenu: rev,
      taux: tx,
      nbLogEnChambres: nbLC,
      nbChambres: nbC,
      nbChambresOcc: nbCO,
      unites: nbL - nbLC + nbC
    };
  }, [list]);

  return { list, error, kpis };
}

/** Accueil d'Immobilier : la page « Aujourd'hui » de la refonte, ou la
 *  vue d'ensemble actuelle si l'équipe est revenue à la présentation
 *  actuelle (Paramètres → Immobilier → Présentation d'Immobilier). */
export default function ImmobilierAccueil() {
  const { menu, pret } = usePresentationImmobilier();
  if (!pret) {
    return (
      <div className="flex items-center gap-2 p-6 text-xs text-white/70">
        <Loader2 className="h-3.5 w-3.5 animate-spin" /> Chargement…
      </div>
    );
  }
  return menu ? <Aujourdhui /> : <VueEnsembleActuelle />;
}

// ─── Présentation actuelle : vue d'ensemble (inchangée) ──────────────

function VueEnsembleActuelle() {
  const { currentEntrepriseId } = useImmobilierLayout();
  const { list, error, kpis } = usePortefeuille(currentEntrepriseId);
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

  return (
    <>
      <ImmobilierTopbar
        breadcrumbs={[{ label: "Immobilier" }]}
        rightSlot={
          <Link
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            href={"/immobilier/immeubles" as any}
            className="btn-outline-accent btn-sm"
          >
            <Plus className="h-3.5 w-3.5" />
            Nouvel immeuble
          </Link>
        }
      />
      <div className="p-4 lg:p-6">
        <header className="flex items-start gap-3">
          <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-accent-500/15 text-accent-500">
            <Building2 className="h-5 w-5" />
          </span>
          <div>
            <h1 className="text-2xl font-bold text-white">
              Immobilier
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
                href="/immobilier/paiements"
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
            sub={
              kpis.nbChambres > 0
                ? `Occupation ${fmtPct(kpis.taux)} · ${kpis.nbLogEnChambres} loué${
                    kpis.nbLogEnChambres > 1 ? "s" : ""
                  } en chambres : ${kpis.nbChambresOcc}/${kpis.nbChambres} chambres · ${kpis.unites} unités locatives`
                : `Occupation ${fmtPct(kpis.taux)}`
            }
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
            <h2 className="text-sm font-semibold uppercase tracking-wider text-accent-500">
              Portefeuille
            </h2>
            <Link
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
              href={"/immobilier/immeubles" as any}
              className="text-xs text-white/60 hover:text-accent-500"
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
              {list.map((imm) => (
                <ImmeubleRow key={imm.id} imm={imm} />
              ))}
            </ul>
          )}
        </section>
      </div>
    </>
  );
}

// ─── Nouvelle présentation : « Aujourd'hui » (refonte, lot 1) ────────
//
// Une seule liste de choses à faire (règle R5 : une alerte se lit à UN
// endroit). Chaque ligne vient de GET /immobilier/aujourdhui — le compte
// est celui de la page où elle mène — et un seul bouton par ligne (R2).

const BARRE_TON: Record<string, string> = {
  urgent: "bg-rose-500",
  attention: "bg-amber-500",
  info: "bg-slate-400"
};

function jourEnClair(iso: string): string {
  // Date construite en LOCAL (new Date(iso) décalerait d'un jour).
  const [y, m, d] = iso.split("-").map(Number);
  if (!y || !m || !d) return "";
  const txt = new Date(y, m - 1, d).toLocaleDateString("fr-CA", {
    weekday: "long",
    day: "numeric",
    month: "long"
  });
  return txt.charAt(0).toUpperCase() + txt.slice(1);
}

/** « 68 % » : pourcentage au format français (espace insécable). */
function pctFr(n: number): string {
  return `${Math.round(n * 100)}\u00a0%`;
}

function enListe(mots: string[]): string {
  if (mots.length <= 1) return mots.join("");
  return `${mots.slice(0, -1).join(", ")} et ${mots[mots.length - 1]}`;
}

function Aujourdhui() {
  const { currentEntrepriseId, setCurrentEntrepriseId, entreprises } =
    useImmobilierLayout();
  const { user } = useCurrentUser();
  const canSeeHref = useNavAccess(user);
  const { data, erreur, chargement, recharger } = useAujourdhuiImmobilier(
    currentEntrepriseId,
    { fraicheurMs: 15_000 }
  );
  const { list, error, kpis } = usePortefeuille(currentEntrepriseId);

  // Une ligne dont la page est refusée à ce compte n'est pas montrée.
  const lignes = (data?.lignes ?? []).filter((l) =>
    canSeeHref(l.href.split("?")[0])
  );
  const nb = lignes.length;

  return (
    <>
      <ImmobilierTopbar
        breadcrumbs={[{ label: "Immobilier" }]}
      />
      <div className="max-w-4xl p-4 pb-28 lg:p-6 lg:pb-28">
        <header className="flex items-start gap-3">
          <span className="flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-xl bg-accent-500/15 text-accent-500">
            <CalendarCheck className="h-5 w-5" />
          </span>
          <div className="min-w-0 flex-1">
            <h1 className="text-2xl font-bold text-white">Aujourd&apos;hui</h1>
            <p className="mt-1 text-sm text-white/70">
              {data ? (
                <>
                  {jourEnClair(data.jour)} ·{" "}
                  {nb === 0
                    ? "rien à faire"
                    : nb === 1
                      ? "1 chose à faire"
                      : `${nb} choses à faire`}
                </>
              ) : (
                "Ce qui demande une action dans Immobilier."
              )}
            </p>
          </div>
          <button
            type="button"
            onClick={recharger}
            disabled={chargement}
            className="btn-secondary btn-sm flex-shrink-0 gap-1.5 disabled:opacity-60"
          >
            <RefreshCw
              className={`h-3.5 w-3.5 ${chargement ? "animate-spin" : ""}`}
            />
            Actualiser
          </button>
        </header>

        {/* Une entreprise est choisie (page Immeubles) : la liste s'y
            limite, et on le dit — une liste de choses à faire ne doit
            jamais être filtrée en silence. */}
        {currentEntrepriseId != null ? (
          <p className="mt-4 rounded-xl border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-sm text-amber-300">
            Liste limitée à{" "}
            <span className="font-semibold">
              {entreprises.find((e) => e.id === currentEntrepriseId)?.name ??
                "une entreprise"}
            </span>
            .{" "}
            <button
              type="button"
              onClick={() => setCurrentEntrepriseId(null)}
              className="font-semibold underline underline-offset-2"
            >
              Voir toutes les entreprises
            </button>
          </p>
        ) : null}

        {erreur && !data ? (
          <div className="mt-5 rounded-2xl border border-rose-500/40 bg-rose-500/10 p-4 text-sm text-rose-300">
            La liste n&apos;a pas pu être lue ({erreur}).{" "}
            <button
              type="button"
              onClick={recharger}
              className="font-semibold underline underline-offset-2"
            >
              Réessayer
            </button>
          </div>
        ) : null}

        {!data && !erreur ? (
          <div className="mt-6 flex items-center gap-2 text-xs text-white/70">
            <Loader2 className="h-3.5 w-3.5 animate-spin" /> Chargement…
          </div>
        ) : null}

        {data ? (
          <section aria-label="À faire" className="mt-5">
            {nb === 0 ? (
              <div className="flex items-center gap-3 rounded-2xl border border-emerald-500/40 bg-emerald-500/10 p-4">
                <CheckCircle2 className="h-5 w-5 flex-shrink-0 text-emerald-300" />
                <p className="text-sm font-semibold text-white">
                  Rien à faire aujourd&apos;hui.
                </p>
              </div>
            ) : (
              <ul className="space-y-3">
                {lignes.map((l) => (
                  <li
                    key={l.cle}
                    className="relative overflow-hidden rounded-2xl border border-brand-800 bg-brand-900"
                  >
                    <span
                      aria-hidden
                      className={`absolute inset-y-0 left-0 w-1.5 ${
                        BARRE_TON[l.ton] ?? BARRE_TON.info
                      }`}
                    />
                    <div className="flex items-center gap-3 py-3.5 pl-5 pr-4">
                      <div className="min-w-0 flex-1">
                        <p className="text-base font-bold text-white">
                          {l.titre}
                        </p>
                        {l.detail ? (
                          <p className="mt-0.5 text-sm text-white/70">
                            {l.detail}
                          </p>
                        ) : null}
                      </div>
                      <Link
                        // eslint-disable-next-line @typescript-eslint/no-explicit-any
                        href={l.href as any}
                        aria-label={`${l.bouton} : ${l.titre}`}
                        className={`${
                          l.ton === "urgent" ? "btn-accent" : "btn-secondary"
                        } btn-sm min-h-[40px] flex-shrink-0 px-4`}
                      >
                        {l.bouton}
                      </Link>
                    </div>
                  </li>
                ))}
              </ul>
            )}

            {data.rien_a_signaler.length > 0 ? (
              <p className="mt-3 rounded-2xl border border-brand-800 bg-brand-900 px-4 py-3 text-sm text-white/70">
                Rien à signaler : {enListe(data.rien_a_signaler)}.
              </p>
            ) : null}

            {data.indisponibles.length > 0 ? (
              <p className="mt-3 rounded-2xl border border-amber-500/40 bg-amber-500/10 px-4 py-3 text-sm text-amber-300">
                Pas pu vérifier pour le moment : {enListe(data.indisponibles)}.{" "}
                <button
                  type="button"
                  onClick={recharger}
                  className="font-semibold underline underline-offset-2"
                >
                  Réessayer
                </button>
              </p>
            ) : null}
          </section>
        ) : null}

        <section className="mt-8">
          <div className="mb-3 flex items-center justify-between">
            <h2 className="text-xs font-semibold uppercase tracking-wider text-white/70">
              Portefeuille
            </h2>
            <Link
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
              href={"/immobilier/immeubles" as any}
              className="text-xs font-semibold text-accent-500 underline-offset-2 hover:underline"
            >
              Voir les immeubles
            </Link>
          </div>

          {error ? (
            <p className="mb-3 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
              {error}
            </p>
          ) : null}

          <div className="grid grid-cols-3 gap-3">
            <TuilePortefeuille
              label="Immeubles"
              value={list ? String(kpis.nbImmeubles) : "…"}
            />
            <TuilePortefeuille
              label="Loués"
              value={list ? `${kpis.nbOccupes} sur ${kpis.nbLogements}` : "…"}
              sub={
                list && kpis.nbLogements > 0
                  ? kpis.nbChambres > 0
                    ? `${pctFr(kpis.taux)} · ${kpis.nbChambresOcc} chambres sur ${kpis.nbChambres}`
                    : `${pctFr(kpis.taux)} d'occupation`
                  : undefined
              }
            />
            <TuilePortefeuille
              label="Par mois"
              value={list ? fmtCompact(kpis.revenu) : "…"}
              sub={list ? `${fmtCompact(kpis.revenu * 12)} par an` : undefined}
            />
          </div>

          {list === null ? null : list.length === 0 ? (
            <div className="mt-4">
              <EmptyState />
            </div>
          ) : (
            <ul className="mt-4 grid gap-3 lg:grid-cols-2">
              {list.map((imm) => (
                <ImmeubleRow key={imm.id} imm={imm} />
              ))}
            </ul>
          )}
        </section>

        <PageDriveSection
          pageKey="page:immobilier:vue-ensemble"
          pole="Gestion immobilière"
          label="Aujourd'hui"
          route="/immobilier"
          className="mt-8"
        />
      </div>
    </>
  );
}

function TuilePortefeuille({
  label,
  value,
  sub
}: {
  label: string;
  value: string;
  sub?: string;
}) {
  return (
    <div className="rounded-xl border border-brand-800 bg-brand-900 p-3 sm:p-4">
      <div className="text-[11px] font-semibold uppercase tracking-wider text-white/70">
        {label}
      </div>
      <div className="mt-1 text-lg font-bold text-white sm:text-2xl">{value}</div>
      {sub ? <div className="mt-0.5 text-xs text-white/70">{sub}</div> : null}
    </div>
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
    <div className="kpi-card">
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
        className="flex items-center gap-3 rounded-xl border border-brand-800 bg-brand-900 p-3 transition hover:border-accent-500"
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
            {(imm.nb_chambres || 0) > 0 ? (
              <span
                className="rounded bg-brand-950 px-1.5 py-0.5 font-mono text-white/60"
                title={`${imm.nb_logements_en_chambres} logement(s) loué(s) en chambres`}
              >
                {imm.nb_chambres_occupees}/{imm.nb_chambres} ch.
              </span>
            ) : null}
            <span
              className={`badge font-mono ${
                tauxOk ? "badge-emerald" : "badge-amber"
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
    <div className="empty-state">
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
        className="btn-outline-accent btn-sm mt-4"
      >
        <Plus className="h-3.5 w-3.5" />
        Ajouter un immeuble
      </Link>
    </div>
  );
}
