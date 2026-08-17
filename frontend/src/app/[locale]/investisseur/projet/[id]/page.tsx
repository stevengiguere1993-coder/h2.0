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
  fmtDate,
  fmtMoney,
  fmtPct,
  HypothequesCard,
  investApiBase,
  NormalisesPanel,
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
        `${investApiBase(apercu)}/projets/${entrepriseId}`
      );
      if (!res.ok) throw new Error(`http_${res.status}`);
      setData((await res.json()) as ProjetDetail);
    } catch {
      setError("Projet introuvable ou chargement impossible.");
    } finally {
      setLoading(false);
    }
  }, [apercu, entrepriseId]);

  useEffect(() => {
    if (ready) void load();
  }, [ready, load]);

  async function openDocument(id: number, title: string) {
    const base = apercu
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
              : "/investisseur"
          },
          { label: data.entreprise_name }
        ]}
      />

      <div className="mx-auto w-full max-w-6xl p-4 lg:p-6">
        {apercu ? (
          <div className="mb-4 flex items-center gap-2 rounded-lg border border-sky-500/40 bg-sky-500/10 px-4 py-2.5 text-sm text-sky-400">
            <Eye className="h-4 w-4 shrink-0" />
            Aperçu administrateur — vue exacte de l&apos;investisseur.
          </div>
        ) : null}

        {/* En-tête */}
        <div className="mb-1 flex flex-wrap items-center gap-3">
          <h1 className="text-2xl font-bold text-white">
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
            <p className="mt-1.5 text-2xl font-bold tabular-nums text-white">
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
            <p className="mt-1.5 text-2xl font-bold tabular-nums text-white">
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
            <p className="mt-1.5 text-2xl font-bold tabular-nums text-emerald-400">
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
            <p className="mt-1.5 text-2xl font-bold tabular-nums text-white">
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
                apercu
                  ? `/api/v1/invest/admin/projets/${entrepriseId}/qbo-reels`
                  : `/api/v1/invest/me/projets/${entrepriseId}/qbo-reels`
              }
            />
          ) : null}
        </div>

        {/* Ma participation + histoire, puis hypothèques + actionnaires */}
        <div className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-2">
          {/* Colonne gauche */}
          <div className="min-w-0 space-y-4">
            <ParticipationHero data={data} />
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

function ParticipationHero({ data }: { data: ProjetDetail }) {
  const enAttente =
    data.flux.length === 0 && data.capital_investi_total === 0;

  return (
    <div className="rounded-2xl border border-accent-500/40 bg-brand-900 p-5">
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
          <p className="mt-1 text-2xl font-bold tabular-nums text-white">
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
          <p className="mt-1 text-2xl font-bold tabular-nums text-white">
            {enAttente ? "—" : fmtMoney(data.capital_actuel)}
          </p>
          <p className="mt-0.5 text-[10px] text-white/35">
            apports − remboursements
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
            automatiquement chaque nuit — le capital investi, le TVPI et
            le TRI apparaîtront dès la première synchronisation.
          </p>
        </div>
      ) : (
        <dl className="mt-4 space-y-2.5 border-t border-brand-800 pt-3 text-sm tabular-nums">
          <div className="flex justify-between gap-3">
            <dt className="text-white/60">
              Capital investi (total)
              <span className="block text-[10px] font-normal text-white/35">
                somme de vos apports — avances d&apos;actionnaires
                (QuickBooks)
              </span>
            </dt>
            <dd className="font-bold text-white">
              {fmtMoney(data.capital_investi_total)}
            </dd>
          </div>
          <div className="flex justify-between gap-3">
            <dt className="text-white/60">
              Capital remboursé
              <span className="block text-[10px] font-normal text-white/35">
                avances remboursées par la compagnie (ex. après
                refinancement)
              </span>
            </dt>
            <dd className="font-bold text-white">
              {fmtMoney(data.capital_rembourse)}
            </dd>
          </div>
          {data.distributions_recues > 0 ? (
            <div className="flex justify-between gap-3">
              <dt className="text-white/60">Distributions reçues</dt>
              <dd className="font-bold text-white">
                {fmtMoney(data.distributions_recues)}
              </dd>
            </div>
          ) : null}
          <div className="flex justify-between gap-3 border-t border-brand-800 pt-2.5">
            <dt className="text-white/60">
              TVPI
              <span className="block text-[10px] font-normal text-white/35">
                (remboursé + distributions + valeur des parts) ÷ investi
              </span>
            </dt>
            <dd className="font-bold text-white">
              {data.tvpi !== null
                ? `${data.tvpi.toLocaleString("fr-CA", {
                    maximumFractionDigits: 2
                  })}×`
                : "—"}
            </dd>
          </div>
          <div className="flex justify-between gap-3">
            <dt className="text-white/60">
              TRI réalisé
              <span className="block text-[10px] font-normal text-white/35">
                rendement annualisé de vos flux datés (méthode XIRR)
              </span>
            </dt>
            <dd
              className={`font-bold ${
                (data.tri_pct ?? 0) >= 0
                  ? "text-emerald-400"
                  : "text-rose-400"
              }`}
            >
              {fmtPct(data.tri_pct)}
            </dd>
          </div>
        </dl>
      )}

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
