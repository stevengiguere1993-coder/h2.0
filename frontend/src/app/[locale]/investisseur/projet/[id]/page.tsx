"use client";

/* Portail Investisseur v2 — fiche projet (une compagnie).

   L'histoire complète : immeubles (valeur, hypothèque, équité),
   revenus/dépenses 12 mois, timeline, ma participation (TRI, flux),
   actionnaires de la compagnie, documents partagés. Respecte les
   interrupteurs de publication réglés côté admin. */

import { useCallback, useEffect, useState } from "react";
import { useParams } from "next/navigation";
import {
  Building2,
  Eye,
  FileText,
  Loader2,
  Users
} from "lucide-react";

import { authedFetch } from "@/lib/auth";
import { InvestisseurTopbar } from "../../layout";
import {
  BudgetOptimisationPanel,
  fmtDate,
  fmtMoney,
  HypothequesCard,
  investApiBase,
  NormalisesPanel,
  useApercuPartenaire,
  PhaseBadge,
  ProjetDetail,
  QboReelsPanel,
  Timeline,
  useApercu
} from "../../invest-ui";

const FLUX_LABELS: Record<string, string> = {
  apport: "Apport de capital",
  remboursement: "Remboursement de capital",
  dividende: "Distribution",
  sortie: "Sortie"
};

export default function ProjetPage() {
  const params = useParams<{ id: string }>();
  const entrepriseId = Number(params.id);
  const apercu = useApercu();
  const apercuP = useApercuPartenaire();
  //: Une des deux formes d'aperçu admin (compte existant ou « compte à
  //: créer ») — les sous-requêtes passent alors par les routes admin.
  const enApercu = apercu !== null || apercuP !== null;
  const [data, setData] = useState<ProjetDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    const t = setTimeout(() => setReady(true), 0);
    return () => clearTimeout(t);
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await authedFetch(
        apercuP
          ? `/api/v1/invest/admin/apercu-partenaire/${apercuP}/projets/${entrepriseId}`
          : `${investApiBase(apercu)}/projets/${entrepriseId}`
      );
      if (!res.ok) throw new Error(`http_${res.status}`);
      setData((await res.json()) as ProjetDetail);
    } catch {
      setError("Projet introuvable ou chargement impossible.");
    } finally {
      setLoading(false);
    }
  }, [apercu, apercuP, entrepriseId]);

  useEffect(() => {
    if (ready) void load();
  }, [ready, load]);

  async function openDocument(id: number, title: string) {
    const base = enApercu
      ? `/api/v1/invest/admin/documents/${id}/pdf`
      : `/api/v1/invest/me/documents/${id}/pdf`;
    const res = await authedFetch(base);
    if (!res.ok) return;
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    window.open(url, "_blank", "noopener");
    setTimeout(() => URL.revokeObjectURL(url), 60_000);
    void title;
  }

  if (loading || !ready) {
    return (
      <>
        <InvestisseurTopbar
          breadcrumbs={[
            { label: "Mon portefeuille", href: "/investisseur" },
            { label: "…" }
          ]}
        />
        <div className="flex items-center justify-center py-24">
          <Loader2 className="h-6 w-6 animate-spin text-accent-500" />
        </div>
      </>
    );
  }

  if (error || !data) {
    return (
      <>
        <InvestisseurTopbar
          breadcrumbs={[
            { label: "Mon portefeuille", href: "/investisseur" },
            { label: "Erreur" }
          ]}
        />
        <div className="p-6">
          <div className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-4 py-3 text-sm text-rose-400">
            {error || "Projet introuvable."}
          </div>
        </div>
      </>
    );
  }

  return (
    <>
      <InvestisseurTopbar
        breadcrumbs={[
          {
            label: "Mon portefeuille",
            href: apercu
              ? `/investisseur?apercu=${apercu}`
              : apercuP
              ? `/investisseur?apercu_p=${apercuP}`
              : "/investisseur"
          },
          { label: data.entreprise_name }
        ]}
      />

      <div className="mx-auto w-full max-w-6xl p-4 lg:p-6">
        {enApercu ? (
          <div className="mb-4 flex items-center gap-2 rounded-lg border border-sky-500/40 bg-sky-500/10 px-4 py-2.5 text-sm text-sky-400">
            <Eye className="h-4 w-4 shrink-0" />
            {apercuP
              ? "Aperçu administrateur — vue qu'aura cet actionnaire une fois son compte créé et activé."
              : "Aperçu administrateur — vue exacte de l'investisseur."}
          </div>
        ) : null}

        {/* En-tête */}
        <div className="mb-1 flex flex-wrap items-center gap-3">
          <h1 className="font-display text-3xl font-bold tracking-tight text-white">
            {data.entreprise_name}
          </h1>
          <PhaseBadge phase={data.phase} />
        </div>
        <p className="mb-5 text-xs text-white/40">
          Tableau de bord consolidé de votre investissement — tous les
          immeubles de la compagnie s&apos;additionnent ici.
        </p>
        {data.description ? (
          <p className="mb-5 max-w-3xl whitespace-pre-line text-sm text-white/70">
            {data.description}
          </p>
        ) : null}

        {/* KPIs projet */}
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <div className="rounded-2xl border border-brand-800 bg-brand-900 p-4">
            <p className="text-[11px] font-semibold uppercase tracking-wider text-white/40">
              Valeur des immeubles
            </p>
            <p className="mt-1.5 font-display text-2xl font-bold tabular-nums text-white">
              {fmtMoney(data.valeur_totale)}
            </p>
            <p className="mt-1 text-xs text-white/50">
              évaluation de référence
            </p>
          </div>
          <div className="rounded-2xl border border-brand-800 bg-brand-900 p-4">
            <p className="text-[11px] font-semibold uppercase tracking-wider text-white/40">
              Dette hypothécaire
            </p>
            <p className="mt-1.5 font-display text-2xl font-bold tabular-nums text-white">
              {fmtMoney(data.hypotheque_totale)}
            </p>
            <p className="mt-1 text-xs text-white/50">
              balance à ce jour
            </p>
          </div>
          <div className="rounded-2xl border border-brand-800 bg-brand-900 p-4">
            <p className="text-[11px] font-semibold uppercase tracking-wider text-white/40">
              Équité de la compagnie
            </p>
            <p className="mt-1.5 font-display text-2xl font-bold tabular-nums text-emerald-400">
              {fmtMoney(data.equite)}
            </p>
            <p className="mt-1 text-xs text-white/50">
              {(data.avances_actionnaires ?? 0) > 0
                ? `valeur − hypothèques − avances aux actionnaires (${fmtMoney(
                    data.avances_actionnaires
                  )})`
                : "valeur − hypothèques"}
            </p>
          </div>
          <div className="rounded-2xl border border-brand-800 bg-brand-900 p-4">
            <p className="text-[11px] font-semibold uppercase tracking-wider text-white/40">
              Occupation
            </p>
            <p className="mt-1.5 font-display text-2xl font-bold tabular-nums text-white">
              {data.nb_baux_actifs} / {data.nb_logements || "—"}
            </p>
            <p className="mt-1 text-xs text-white/50">
              loyers {fmtMoney(data.loyers_mensuels)}/mois
            </p>
          </div>
        </div>

        {/* Immeubles */}
        <div className="mt-5 overflow-hidden rounded-2xl border border-brand-800 bg-brand-900">
          <div className="flex items-center justify-between border-b border-brand-800 px-4 py-2.5">
            <h2 className="text-sm font-semibold text-white">
              Immeubles de la compagnie
            </h2>
            <span className="text-xs text-white/40">
              {data.immeubles.length} immeuble
              {data.immeubles.length > 1 ? "s" : ""}
            </span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm tabular-nums">
              <thead>
                <tr className="text-left text-[10px] uppercase tracking-wider text-white/40">
                  <th className="px-4 py-2.5 font-medium">Immeuble</th>
                  <th className="px-4 py-2.5 text-right font-medium">
                    Logements
                  </th>
                  <th className="px-4 py-2.5 text-right font-medium">
                    Loyers / mois
                  </th>
                  <th className="px-4 py-2.5 text-right font-medium">
                    Valeur
                  </th>
                  <th className="px-4 py-2.5 text-right font-medium">
                    Hypothèque
                  </th>
                  <th className="px-4 py-2.5 text-right font-medium">
                    Équité
                  </th>
                </tr>
              </thead>
              <tbody>
                {data.immeubles.map((im) => (
                  <tr
                    key={im.immeuble_id}
                    className="border-t border-brand-800/60"
                  >
                    <td className="px-4 py-3">
                      <p className="font-medium text-white">
                        {im.address || im.name}
                      </p>
                      <p className="text-xs text-white/40">
                        {im.nb_baux_actifs} / {im.nb_logements} loué
                        {im.nb_baux_actifs > 1 ? "s" : ""}
                        {im.ownership_pct !== 100
                          ? ` · détenu à ${im.ownership_pct} %`
                          : ""}
                      </p>
                    </td>
                    <td className="px-4 py-3 text-right text-white/80">
                      {im.nb_logements || "—"}
                    </td>
                    <td className="px-4 py-3 text-right text-white/80">
                      {fmtMoney(im.loyers_mensuels)}
                      {(im.loyers_potentiels ?? 0) >
                      im.loyers_mensuels + 1 ? (
                        <span className="block text-[11px] text-white/40">
                          pot. {fmtMoney(im.loyers_potentiels)}
                        </span>
                      ) : null}
                    </td>
                    <td className="px-4 py-3 text-right text-white/80">
                      {fmtMoney(im.valeur)}
                    </td>
                    <td className="px-4 py-3 text-right text-white/80">
                      {fmtMoney(im.hypotheque_balance)}
                    </td>
                    <td className="px-4 py-3 text-right font-semibold text-emerald-400">
                      {fmtMoney(im.equite)}
                    </td>
                  </tr>
                ))}
                {data.immeubles.length > 1 ? (
                  <tr className="border-t-2 border-brand-700 bg-brand-950/50 font-semibold">
                    <td className="px-4 py-3 text-white">TOTAL</td>
                    <td className="px-4 py-3 text-right text-white">
                      {data.immeubles.reduce(
                        (s, im) => s + im.nb_logements,
                        0
                      )}
                    </td>
                    <td className="px-4 py-3 text-right text-white">
                      {fmtMoney(
                        data.immeubles.reduce(
                          (s, im) => s + im.loyers_mensuels,
                          0
                        )
                      )}
                    </td>
                    <td className="px-4 py-3 text-right text-white">
                      {fmtMoney(
                        data.immeubles.reduce(
                          (s, im) => s + (im.valeur || 0),
                          0
                        )
                      )}
                    </td>
                    <td className="px-4 py-3 text-right text-white">
                      {fmtMoney(
                        data.immeubles.reduce(
                          (s, im) => s + im.hypotheque_balance,
                          0
                        )
                      )}
                    </td>
                    <td className="px-4 py-3 text-right text-emerald-400">
                      {fmtMoney(
                        data.immeubles.reduce((s, im) => s + im.equite, 0)
                      )}
                    </td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          </div>
        </div>

        {/* Revenus / dépenses : normalisés (pôle locatif) et réels (QBO) */}
        <div className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-2">
          <NormalisesPanel
            serie={data.serie_mensuelle}
            revenusMode={data.revenus_mode}
            cashflowMoyen={data.cashflow_moyen}
            depensesParCategorie={data.depenses_par_categorie}
            showDepenses={data.show_depenses}
            showCashflow={data.show_cashflow}
          />
          {data.show_cashflow ? (
            <QboReelsPanel
              fetchPath={
                enApercu
                  ? `/api/v1/invest/admin/projets/${entrepriseId}/qbo-reels`
                  : `/api/v1/invest/me/projets/${entrepriseId}/qbo-reels`
              }
            />
          ) : null}
        </div>

        {/* Budget du projet d'optimisation — « où va l'argent » */}
        {data.show_budget !== false ? (
          <div className="mt-4">
            <BudgetOptimisationPanel
              fetchPath={
                enApercu
                  ? `/api/v1/invest/admin/projets/${entrepriseId}/budget`
                  : `/api/v1/invest/me/projets/${entrepriseId}/budget`
              }
            />
          </div>
        ) : null}

        {/* Ma participation + histoire, puis hypothèques + actionnaires */}
        <div className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-2">
          {/* Colonne gauche */}
          <div className="min-w-0 space-y-4">
            <ParticipationHero
              data={data}
              avancesPath={
                enApercu
                  ? `/api/v1/invest/admin/projets/${entrepriseId}/avances`
                  : `/api/v1/invest/me/projets/${entrepriseId}/avances`
              }
            />
            {data.show_hypotheque ? (
              <HypothequesCard immeubles={data.immeubles} />
            ) : null}
          </div>

          {/* Colonne droite */}
          <div className="min-w-0 space-y-4">
            {/* L'histoire du projet */}
            <div className="rounded-2xl border border-brand-800 bg-brand-900 p-5">
              <h2 className="mb-4 text-sm font-semibold text-white">
                L&apos;histoire du projet
              </h2>
              <Timeline events={data.timeline} />
            </div>

            {/* Actionnaires */}
            {data.show_actionnaires && data.actionnaires.length > 0 ? (
              <div className="rounded-2xl border border-brand-800 bg-brand-900 p-4">
                <h2 className="mb-3 flex items-center gap-2 text-sm font-semibold text-white">
                  <Users className="h-4 w-4 text-accent-500" />
                  Actionnaires
                </h2>
                <ul className="space-y-1.5">
                  {data.actionnaires.map((a, i) => (
                    <li
                      key={i}
                      className="flex items-center justify-between text-sm"
                    >
                      <span className="text-white/80">
                        {a.name}
                        {a.is_me ? (
                          <span className="text-white/40"> (vous)</span>
                        ) : null}
                      </span>
                      <span className="font-bold tabular-nums text-white">
                        {a.parts_pct !== null
                          ? `${a.parts_pct.toLocaleString("fr-CA", {
                              maximumFractionDigits: 1
                            })} %`
                          : "—"}
                      </span>
                    </li>
                  ))}
                </ul>
                <p className="mt-2 text-[11px] text-white/35">
                  Visible entre co-actionnaires de cette compagnie
                  seulement.
                </p>
              </div>
            ) : null}

            {/* Documents */}
            {data.documents.length > 0 ? (
              <div className="rounded-2xl border border-brand-800 bg-brand-900 p-4">
                <h2 className="mb-3 text-sm font-semibold text-white">
                  Documents
                </h2>
                <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                  {data.documents.map((d) => (
                    <button
                      key={d.id}
                      type="button"
                      onClick={() => void openDocument(d.id, d.title)}
                      className="group flex items-center gap-2.5 rounded-xl border border-brand-800 bg-brand-950/50 p-3 text-left transition hover:border-accent-500/60"
                    >
                      <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-accent-500/15 text-accent-500">
                        <FileText className="h-4 w-4" />
                      </span>
                      <span className="min-w-0">
                        <span className="block truncate text-sm font-medium text-white group-hover:text-accent-500">
                          {d.title}
                        </span>
                        <span className="text-[11px] text-white/40">
                          PDF · {(d.size_bytes / 1024 / 1024).toFixed(1)} Mo
                        </span>
                      </span>
                    </button>
                  ))}
                </div>
              </div>
            ) : null}
          </div>
        </div>

        <p className="mt-8 flex items-center justify-center gap-1.5 pb-4 text-center text-[11px] text-white/30">
          <Building2 className="h-3.5 w-3.5" />
          Données assemblées en direct depuis la gestion de vos immeubles
          · Horizon Services Immobiliers
        </p>
      </div>
    </>
  );
}

/* ─────────────────── Ma participation (carte héro) ─────────────────── */

type AvancesActionnaires = {
  statut: string;
  erreur?: string;
  actionnaires?: {
    name: string;
    solde: number | null;
    comptes: { nom: string; solde: number }[];
  }[];
  autres_comptes?: { nom: string; solde: number }[];
  total?: number;
};

function ParticipationHero({
  data,
  avancesPath
}: {
  data: ProjetDetail;
  avancesPath: string;
}) {
  //: Soldes LIVE des comptes d'avances d'actionnaires (QuickBooks) —
  //: la même lecture que l'encadré de la page Optimisation.
  const [avances, setAvances] = useState<AvancesActionnaires | null>(
    null
  );
  const estMoi = new Set(
    data.actionnaires.filter((a) => a.is_me).map((a) => a.name)
  );

  useEffect(() => {
    let cancelled = false;
    authedFetch(avancesPath)
      .then(async (res) => {
        if (cancelled || !res.ok) return;
        setAvances((await res.json()) as AvancesActionnaires);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [avancesPath]);
  //: MA ligne dans les avances QuickBooks — LA source du capital
  //: encore investi, la même que la liste par actionnaire plus bas :
  //: la tuile et la liste racontent toujours la même histoire
  //: (retour Phil 2026-08-25 : « ça dit qu'on leur doit 0, mais
  //: direct en bas on voit le vrai montant »).
  const maLigneAvances =
    avances?.statut === "connecte"
      ? (avances.actionnaires || []).find(
          (a) =>
            estMoi.has(a.name) &&
            a.solde !== null &&
            a.solde !== undefined
        )
      : undefined;
  //: Tant que la sync QuickBooks (avances d'actionnaires) n'a jamais
  //: tourné ET qu'aucun solde live n'est lisible, un capital à 0 veut
  //: dire « pas encore de données » ; après, « remboursé ».
  const synchronise = data.apports_synchronises === true;
  const enAttente =
    data.flux.length === 0 &&
    data.capital_investi_total === 0 &&
    !synchronise &&
    !maLigneAvances;
  const capitalAffiche = maLigneAvances
    ? (maLigneAvances.solde as number)
    : enAttente
    ? null
    : data.capital_actuel;
  const rembourse = !enAttente && capitalAffiche === 0;

  return (
    <div className="rounded-2xl border border-accent-500/40 bg-brand-900 p-5 shadow-card">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-sm font-semibold text-white">
          Ma participation
        </h2>
        <span className="inline-flex items-center rounded-full border border-accent-500/50 bg-accent-500/10 px-2.5 py-0.5 text-[11px] font-bold tabular-nums text-accent-500">
          {data.parts_pct.toLocaleString("fr-CA", {
            maximumFractionDigits: 1
          })}{" "}
          % de la compagnie
        </span>
      </div>

      {/* Les deux chiffres qui comptent */}
      <div className="grid grid-cols-2 gap-3">
        <div className="rounded-xl border border-brand-800 bg-brand-950/50 p-3">
          <p className="text-[10px] font-semibold uppercase tracking-wider text-white/40">
            Valeur de mes parts
          </p>
          <p className="mt-1 font-display text-2xl font-bold tabular-nums text-white">
            {fmtMoney(data.valeur_parts)}
          </p>
          <p className="mt-0.5 text-[10px] text-white/35">
            équité de la compagnie ×{" "}
            {data.parts_pct.toLocaleString("fr-CA", {
              maximumFractionDigits: 1
            })}{" "}
            %
          </p>
        </div>
        <div className="rounded-xl border border-brand-800 bg-brand-950/50 p-3">
          <p className="text-[10px] font-semibold uppercase tracking-wider text-white/40">
            Capital encore investi
          </p>
          {rembourse ? (
            <p className="mt-1.5 text-lg font-bold leading-6 text-emerald-400">
              Remboursé complètement&nbsp;!
            </p>
          ) : (
            <p className="mt-1 font-display text-2xl font-bold tabular-nums text-white">
              {capitalAffiche === null ? "—" : fmtMoney(capitalAffiche)}
            </p>
          )}
          <p className="mt-0.5 text-[10px] text-white/35">
            {rembourse
              ? "tous les apports ont été remboursés"
              : maLigneAvances
              ? "solde de vos avances d'actionnaire (QuickBooks)"
              : "apports − remboursements"}
          </p>
        </div>
      </div>

      {enAttente ? (
        <div className="mt-3 rounded-xl border border-dashed border-amber-500/40 bg-amber-500/5 px-3.5 py-3">
          <p className="text-xs font-semibold text-amber-400">
            Apports en attente de synchronisation
          </p>
          <p className="mt-0.5 text-[11px] text-white/45">
            Vos apports proviennent des avances d&apos;actionnaires du
            QuickBooks de la compagnie et se mettent à jour
            automatiquement chaque nuit — le capital investi apparaîtra
            dès la première synchronisation.
          </p>
        </div>
      ) : null}

      {/* Capital restant par actionnaire = soldes RÉELS des comptes
          d'avances QuickBooks (même lecture que l'encadré de la page
          Optimisation) — mêmes règles de transparence que la liste des
          actionnaires (le serveur renvoie « masque » sinon). */}
      {avances?.statut === "connecte" &&
      (avances.actionnaires || []).length > 0 ? (
        <div className="mt-4 border-t border-brand-800 pt-3">
          <p className="mb-2 text-[10px] font-semibold uppercase tracking-wider text-white/40">
            Capital encore investi par actionnaire
          </p>
          <ul className="space-y-1.5">
            {(avances.actionnaires || []).map((a, i) => (
              <li key={i} className="text-xs">
                <div className="flex items-center justify-between gap-2">
                  <span
                    className="min-w-0 truncate text-white/70"
                    title={
                      a.comptes.length === 1
                        ? `Compte QuickBooks : ${a.comptes[0].nom}`
                        : undefined
                    }
                  >
                    {a.name}
                    {estMoi.has(a.name) ? (
                      <span className="text-white/40"> (vous)</span>
                    ) : null}
                  </span>
                  {a.solde === null || a.solde === undefined ? (
                    <span
                      className="shrink-0 text-white/35"
                      title="Aucun compte d'avances trouvé à son nom dans QuickBooks"
                    >
                      —
                    </span>
                  ) : a.solde === 0 ? (
                    <b className="shrink-0 text-emerald-400">
                      Remboursé
                    </b>
                  ) : (
                    <b className="shrink-0 tabular-nums text-white/80">
                      {fmtMoney(a.solde)}
                    </b>
                  )}
                </div>
                {a.comptes.length > 1 ? (
                  <ul className="mb-0.5 mt-0.5 space-y-0.5 border-l border-brand-800 pl-2.5">
                    {a.comptes.map((cpt, j) => (
                      <li
                        key={j}
                        className="flex items-center justify-between gap-2 text-[10px]"
                      >
                        <span className="min-w-0 truncate text-white/40">
                          {cpt.nom}
                        </span>
                        <span className="shrink-0 tabular-nums text-white/50">
                          {fmtMoney(cpt.solde)}
                        </span>
                      </li>
                    ))}
                  </ul>
                ) : null}
              </li>
            ))}
            {(avances.autres_comptes || []).map((c, i) => (
              <li
                key={`autre-${i}`}
                className="flex items-center justify-between gap-2 text-xs"
                title="Compte d'avances QuickBooks sans actionnaire reconnu dans la fiche"
              >
                <span className="min-w-0 truncate italic text-white/45">
                  {c.nom}
                </span>
                <b className="shrink-0 tabular-nums text-white/60">
                  {fmtMoney(c.solde)}
                </b>
              </li>
            ))}
          </ul>
          <p className="mt-2 text-[11px] text-white/35">
            Soldes des comptes d&apos;avances d&apos;actionnaires — lus
            en direct dans QuickBooks.
          </p>
        </div>
      ) : null}

      {/* Mouvements */}
      {data.flux.length > 0 ? (
        <div className="mt-4 border-t border-brand-800 pt-3">
          <p className="mb-2 text-[10px] font-semibold uppercase tracking-wider text-white/40">
            Mouvements
          </p>
          <ul className="max-h-64 space-y-1.5 overflow-y-auto pr-1">
            {data.flux.map((f) => (
              <li
                key={f.id}
                className="flex items-center justify-between gap-2 text-xs"
              >
                <span className="min-w-0 truncate text-white/70">
                  {fmtDate(f.date_flux)} —{" "}
                  {f.label || FLUX_LABELS[f.type] || f.type}
                  {f.note ? (
                    <span className="text-white/35"> · {f.note}</span>
                  ) : null}
                </span>
                <b
                  className={`shrink-0 tabular-nums ${
                    f.type === "apport"
                      ? "text-white/80"
                      : "text-emerald-400"
                  }`}
                >
                  {f.type === "apport" ? "−" : "+"}
                  {fmtMoney(f.montant)}
                </b>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}
