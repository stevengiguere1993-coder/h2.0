"use client";

import { use, useEffect, useState } from "react";
import {
  ArrowLeft,
  Building2,
  DoorOpen,
  FileText,
  Loader2,
  Pencil,
  TrendingUp,
  User,
  Wrench
} from "lucide-react";

import { Link, useRouter } from "@/i18n/navigation";
import { authedFetch } from "@/lib/auth";
import { ImmobilierTopbar } from "../../layout";
import {
  fmtPieces,
  LogementFiche,
  type LogementFicheBail,
  type LogementFicheData
} from "@/components/immobilier/logement-fiche";

/**
 * Fiche logement — VRAIE page 360 d'un logement : infos, locataire
 * actuel, historique des locataires (tous les baux), fluctuation du
 * loyer de bail en bail, rénos/maintenance (bons de travail) et
 * documents (baux). L'édition réutilise la modale partagée
 * LogementFiche.
 */

type DossierLocataire = { id: number; full_name: string };

type DossierBail = {
  id: number;
  locataire: DossierLocataire | null;
  loyer_mensuel: number;
  date_debut: string;
  date_fin: string;
  status: string;
  document_url: string | null;
  signed_at: string | null;
};

type DossierBon = {
  id: number;
  reference: string;
  title: string;
  status: string;
  montant: number | null;
  created_at: string | null;
};

type LoyerPoint = { date_debut: string; loyer_mensuel: number };

type Dossier = {
  logement: LogementFicheData;
  immeuble: { id: number; name: string; address: string | null };
  baux: DossierBail[];
  bons_travail: DossierBon[];
  historique_loyer: LoyerPoint[];
};

const BAIL_STATUS_LABEL: Record<string, string> = {
  actif: "Actif",
  termine: "Terminé",
  resilie: "Résilié",
  propose: "Proposé"
};

const BAIL_STATUS_BADGE: Record<string, string> = {
  actif: "badge-emerald",
  termine: "badge-neutral",
  resilie: "badge-rose",
  propose: "badge-sky"
};

const BON_STATUS_LABEL: Record<string, string> = {
  draft: "Brouillon",
  sent: "Envoyé",
  signed: "Signé",
  accepte_a_planifier: "Accepté à planifier",
  planifie: "Planifié",
  complete_a_refacturer: "Complété · à refacturer",
  facture: "Facturé",
  cancelled: "Annulé"
};

const BON_STATUS_BADGE: Record<string, string> = {
  draft: "badge-neutral",
  sent: "badge-sky",
  signed: "badge-sky",
  accepte_a_planifier: "badge-amber",
  planifie: "badge-blue",
  complete_a_refacturer: "badge-violet",
  facture: "badge-emerald",
  cancelled: "badge-neutral"
};

function money(n: number | null | undefined): string {
  if (n == null) return "—";
  return new Intl.NumberFormat("fr-CA", {
    style: "currency",
    currency: "CAD",
    maximumFractionDigits: 0
  }).format(n);
}

function fmtDate(d: string | null | undefined): string {
  if (!d) return "—";
  return d.slice(0, 10);
}

function StatutBadge({ status }: { status: string }) {
  const map: Record<string, { cls: string; label: string }> = {
    occupe: { cls: "badge-emerald", label: "Occupé" },
    vacant: { cls: "badge-amber", label: "Vacant" },
    reserve: { cls: "badge-sky", label: "Réservé" },
    hors_location: { cls: "badge-neutral", label: "Hors loc." }
  };
  const t = map[status] || { cls: "badge-neutral", label: status };
  return <span className={`badge ${t.cls}`}>{t.label}</span>;
}

export default function LogementDetailPage({
  params
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const logementId = Number(id);
  const router = useRouter();
  const [dossier, setDossier] = useState<Dossier | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showEdit, setShowEdit] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const r = await authedFetch(
          `/api/v1/immobilier/logements/${logementId}/dossier`
        );
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        if (!cancelled) setDossier((await r.json()) as Dossier);
      } catch (e) {
        if (!cancelled) setError((e as Error).message);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [logementId]);

  const lg = dossier?.logement ?? null;
  const bailActif = dossier
    ? dossier.baux.find((b) => b.status === "actif") ||
      dossier.baux.find((b) => b.status === "propose") ||
      null
    : null;
  const bauxHistorique = dossier
    ? dossier.baux.filter((b) => b.id !== bailActif?.id)
    : [];
  const documents = dossier
    ? dossier.baux.filter((b) => !!b.document_url)
    : [];
  const maxLoyer = dossier
    ? Math.max(...dossier.historique_loyer.map((p) => p.loyer_mensuel), 1)
    : 1;

  // Baux au format attendu par la modale partagée (section Occupation).
  const ficheBails: LogementFicheBail[] =
    dossier?.baux.map((b) => ({
      id: b.id,
      logement_id: logementId,
      locataire_id: b.locataire?.id ?? 0,
      date_debut: b.date_debut,
      date_fin: b.date_fin,
      loyer_mensuel: b.loyer_mensuel,
      status: b.status
    })) ?? [];

  return (
    <>
      <ImmobilierTopbar
        breadcrumbs={[
          { label: "Gestion immobilière", href: "/immobilier" },
          { label: "Logements", href: "/immobilier/logements" },
          { label: lg ? `Logement ${lg.numero}` : "Logement" }
        ]}
      />
      <div className="p-4 lg:p-6 pb-28">
        {dossier ? (
          <Link
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            href={`/immobilier/immeubles/${dossier.immeuble.id}` as any}
            className="inline-flex items-center text-xs text-white/50 hover:text-accent-500"
          >
            <ArrowLeft className="mr-1 h-3.5 w-3.5" />
            {dossier.immeuble.name}
          </Link>
        ) : (
          <Link
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            href={"/immobilier/logements" as any}
            className="inline-flex items-center text-xs text-white/50 hover:text-accent-500"
          >
            <ArrowLeft className="mr-1 h-3.5 w-3.5" /> Logements
          </Link>
        )}

        {error ? (
          <p className="mt-4 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-200">
            {error}
          </p>
        ) : !dossier || !lg ? (
          <div className="mt-6 flex items-center gap-2 text-xs text-white/50">
            <Loader2 className="h-3.5 w-3.5 animate-spin" /> Chargement…
          </div>
        ) : (
          <div className="mt-4 space-y-6">
            {/* Header */}
            <header className="flex items-start gap-4">
              <span className="flex h-14 w-14 items-center justify-center rounded-xl bg-accent-500/15 text-accent-500">
                <DoorOpen className="h-6 w-6" />
              </span>
              <div className="min-w-0">
                <h1 className="flex flex-wrap items-center gap-3 text-2xl font-bold text-white">
                  Logement {lg.numero} — {dossier.immeuble.name}
                  <StatutBadge status={lg.status} />
                </h1>
                <p className="mt-1 flex items-center gap-1.5 text-sm text-white/60">
                  <Building2 className="h-3.5 w-3.5 text-white/40" />
                  {dossier.immeuble.address || dossier.immeuble.name}
                </p>
              </div>
              <div className="ml-auto flex shrink-0 items-center gap-2">
                <button
                  type="button"
                  onClick={() => setShowEdit(true)}
                  className="btn-secondary btn-sm"
                  title="Modifier les informations du logement"
                >
                  <Pencil className="h-4 w-4" />
                  Modifier
                </button>
              </div>
            </header>

            {/* (a) Infos + (b) Locataire actuel & bail actif */}
            <section className="grid gap-4 lg:grid-cols-2">
              <div className="rounded-2xl border border-brand-800 bg-brand-900 p-5">
                <h2 className="mb-3 text-sm font-semibold uppercase tracking-wider text-accent-500">
                  Infos
                </h2>
                <dl className="space-y-1.5 text-sm">
                  <Row label="Type" value={lg.type} />
                  <Row label="Pièces" value={fmtPieces(lg.nb_pieces_decimal)} />
                  <Row
                    label="Chambres"
                    value={lg.nb_chambres != null ? String(lg.nb_chambres) : "—"}
                  />
                  <Row
                    label="Salles de bain"
                    value={lg.nb_sdb != null ? String(lg.nb_sdb) : "—"}
                  />
                  <Row
                    label="Superficie"
                    value={
                      lg.superficie_pi2 != null
                        ? `${lg.superficie_pi2} pi²`
                        : "—"
                    }
                  />
                  <Row
                    label="Étage"
                    value={lg.etage != null ? String(lg.etage) : "—"}
                  />
                  <Row label="Loyer demandé" value={money(lg.loyer_demande)} />
                </dl>
                {lg.notes ? (
                  <p className="mt-3 whitespace-pre-wrap border-t border-brand-800 pt-3 text-xs text-white/70">
                    {lg.notes}
                  </p>
                ) : null}
              </div>

              <div className="rounded-2xl border border-brand-800 bg-brand-900 p-5">
                <h2 className="mb-3 text-sm font-semibold uppercase tracking-wider text-accent-500">
                  Locataire actuel &amp; bail actif
                </h2>
                {bailActif ? (
                  <div className="space-y-2 text-sm">
                    {bailActif.locataire ? (
                      <Link
                        // eslint-disable-next-line @typescript-eslint/no-explicit-any
                        href={
                          `/immobilier/locataires/${bailActif.locataire.id}` as any
                        }
                        className="inline-flex items-center gap-1.5 font-medium text-accent-500 hover:underline"
                      >
                        <User className="h-4 w-4" />
                        {bailActif.locataire.full_name}
                      </Link>
                    ) : (
                      <p className="text-white/50">Locataire inconnu</p>
                    )}
                    <dl className="space-y-1.5">
                      <Row
                        label="Loyer"
                        value={`${money(bailActif.loyer_mensuel)}/mois`}
                      />
                      <Row
                        label="Période"
                        value={`${fmtDate(bailActif.date_debut)} → ${fmtDate(bailActif.date_fin)}`}
                      />
                    </dl>
                    <div className="flex flex-wrap items-center gap-2 pt-1">
                      <span
                        className={`badge ${BAIL_STATUS_BADGE[bailActif.status] || "badge-neutral"}`}
                      >
                        {BAIL_STATUS_LABEL[bailActif.status] ??
                          bailActif.status}
                      </span>
                      {bailActif.document_url ? (
                        <a
                          href={bailActif.document_url}
                          target="_blank"
                          rel="noreferrer"
                          className="inline-flex items-center gap-1 text-xs text-accent-500 hover:underline"
                        >
                          <FileText className="h-3.5 w-3.5" /> Voir le bail
                        </a>
                      ) : null}
                    </div>
                  </div>
                ) : (
                  <p className="text-sm text-white/50">
                    Aucun bail actif — logement libre.
                  </p>
                )}
              </div>
            </section>

            {/* (c) Historique des locataires */}
            <section className="rounded-2xl border border-brand-800 bg-brand-900 p-5">
              <h2 className="mb-3 text-sm font-semibold uppercase tracking-wider text-accent-500">
                Historique des locataires
              </h2>
              {bauxHistorique.length === 0 ? (
                <p className="text-sm text-white/50">
                  Aucun bail passé pour ce logement.
                </p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full min-w-[560px] text-left text-sm">
                    <thead className="text-[10px] uppercase tracking-wider text-white/45">
                      <tr>
                        <th className="py-2 pr-3">Locataire</th>
                        <th className="py-2 pr-3">Période</th>
                        <th className="py-2 pr-3 text-right">Loyer</th>
                        <th className="py-2 pr-3 text-right">Statut</th>
                        <th className="py-2 text-right">Document</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-brand-800/70">
                      {bauxHistorique.map((b) => (
                        <tr key={b.id}>
                          <td className="py-2.5 pr-3">
                            {b.locataire ? (
                              <Link
                                // eslint-disable-next-line @typescript-eslint/no-explicit-any
                                href={
                                  `/immobilier/locataires/${b.locataire.id}` as any
                                }
                                className="font-medium text-white hover:text-accent-500"
                              >
                                {b.locataire.full_name}
                              </Link>
                            ) : (
                              <span className="text-white/40">—</span>
                            )}
                          </td>
                          <td className="py-2.5 pr-3 text-xs text-white/60">
                            {fmtDate(b.date_debut)} → {fmtDate(b.date_fin)}
                          </td>
                          <td className="py-2.5 pr-3 text-right text-white/80">
                            {money(b.loyer_mensuel)}
                          </td>
                          <td className="py-2.5 pr-3 text-right">
                            <span
                              className={`badge ${BAIL_STATUS_BADGE[b.status] || "badge-neutral"}`}
                            >
                              {BAIL_STATUS_LABEL[b.status] ?? b.status}
                            </span>
                          </td>
                          <td className="py-2.5 text-right">
                            {b.document_url ? (
                              <a
                                href={b.document_url}
                                target="_blank"
                                rel="noreferrer"
                                className="inline-flex items-center gap-1 text-xs text-accent-500 hover:underline"
                              >
                                <FileText className="h-3.5 w-3.5" /> Bail
                              </a>
                            ) : (
                              <span className="text-xs text-white/30">—</span>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </section>

            {/* (d) Fluctuation du loyer */}
            <section className="rounded-2xl border border-brand-800 bg-brand-900 p-5">
              <h2 className="mb-3 flex items-center gap-2 text-sm font-semibold uppercase tracking-wider text-accent-500">
                <TrendingUp className="h-4 w-4" />
                Fluctuation du loyer
              </h2>
              {dossier.historique_loyer.length === 0 ? (
                <p className="text-sm text-white/50">
                  Aucun bail — pas encore d&apos;historique de loyer.
                </p>
              ) : (
                <ul className="space-y-2">
                  {dossier.historique_loyer.map((p, i) => {
                    const prev =
                      i > 0 ? dossier.historique_loyer[i - 1] : null;
                    const delta =
                      prev && prev.loyer_mensuel > 0
                        ? ((p.loyer_mensuel - prev.loyer_mensuel) /
                            prev.loyer_mensuel) *
                          100
                        : null;
                    return (
                      <li
                        key={`${p.date_debut}-${i}`}
                        className="flex items-center gap-3 text-sm"
                      >
                        <span className="w-24 shrink-0 font-mono text-xs text-white/50">
                          {fmtDate(p.date_debut)}
                        </span>
                        <span className="h-2 flex-1 overflow-hidden rounded-full bg-brand-950">
                          <span
                            className="block h-full rounded-full bg-accent-500/70"
                            style={{
                              width: `${Math.max(
                                (p.loyer_mensuel / maxLoyer) * 100,
                                2
                              )}%`
                            }}
                          />
                        </span>
                        <span className="w-20 shrink-0 text-right font-mono text-white/80">
                          {money(p.loyer_mensuel)}
                        </span>
                        <span className="w-16 shrink-0 text-right font-mono text-xs">
                          {delta == null ? (
                            <span className="text-white/30">—</span>
                          ) : delta > 0 ? (
                            <span className="text-emerald-300">
                              +{delta.toFixed(1)} %
                            </span>
                          ) : delta < 0 ? (
                            <span className="text-rose-300">
                              {delta.toFixed(1)} %
                            </span>
                          ) : (
                            <span className="text-white/40">0 %</span>
                          )}
                        </span>
                      </li>
                    );
                  })}
                </ul>
              )}
            </section>

            {/* (e) Rénos & maintenance */}
            <section className="rounded-2xl border border-brand-800 bg-brand-900 p-5">
              <h2 className="mb-3 flex items-center gap-2 text-sm font-semibold uppercase tracking-wider text-accent-500">
                <Wrench className="h-4 w-4" />
                Rénos &amp; maintenance
              </h2>
              {dossier.bons_travail.length === 0 ? (
                <p className="text-sm text-white/50">
                  Aucun bon de travail rattaché à ce logement.
                </p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full min-w-[560px] text-left text-sm">
                    <thead className="text-[10px] uppercase tracking-wider text-white/45">
                      <tr>
                        <th className="py-2 pr-3">Référence</th>
                        <th className="py-2 pr-3">Titre</th>
                        <th className="py-2 pr-3 text-right">Statut</th>
                        <th className="py-2 pr-3 text-right">Coût</th>
                        <th className="py-2 text-right">Date</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-brand-800/70">
                      {dossier.bons_travail.map((b) => (
                        <tr key={b.id}>
                          <td className="py-2.5 pr-3 font-mono text-xs text-white/70">
                            {b.reference}
                          </td>
                          <td className="py-2.5 pr-3 font-medium text-white">
                            {b.title}
                          </td>
                          <td className="py-2.5 pr-3 text-right">
                            <span
                              className={`badge ${BON_STATUS_BADGE[b.status] || "badge-neutral"}`}
                            >
                              {BON_STATUS_LABEL[b.status] ?? b.status}
                            </span>
                          </td>
                          <td className="py-2.5 pr-3 text-right text-white/80">
                            {money(b.montant)}
                          </td>
                          <td className="py-2.5 text-right text-xs text-white/60">
                            {fmtDate(b.created_at)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </section>

            {/* (f) Documents */}
            <section className="rounded-2xl border border-brand-800 bg-brand-900 p-5">
              <h2 className="mb-3 flex items-center gap-2 text-sm font-semibold uppercase tracking-wider text-accent-500">
                <FileText className="h-4 w-4" />
                Documents
              </h2>
              {documents.length === 0 ? (
                <p className="text-sm text-white/50">
                  Aucun document — les baux avec un PDF apparaîtront ici.
                </p>
              ) : (
                <ul className="space-y-2">
                  {documents.map((b) => (
                    <li
                      key={b.id}
                      className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm"
                    >
                      <a
                        href={b.document_url as string}
                        target="_blank"
                        rel="noreferrer"
                        className="inline-flex items-center gap-1.5 font-medium text-accent-500 hover:underline"
                      >
                        <FileText className="h-4 w-4" />
                        Bail {fmtDate(b.date_debut)} →{" "}
                        {fmtDate(b.date_fin)}
                      </a>
                      {b.locataire ? (
                        <span className="text-xs text-white/60">
                          {b.locataire.full_name}
                        </span>
                      ) : null}
                      {b.signed_at ? (
                        <span className="badge badge-emerald">
                          Signé le {fmtDate(b.signed_at)}
                        </span>
                      ) : null}
                    </li>
                  ))}
                </ul>
              )}
            </section>
          </div>
        )}
      </div>

      {showEdit && lg ? (
        <LogementFiche
          logement={lg}
          bails={ficheBails}
          onClose={() => setShowEdit(false)}
          onSaved={(updated) => {
            setDossier((d) =>
              d ? { ...d, logement: { ...d.logement, ...updated } } : d
            );
            setShowEdit(false);
          }}
          onDeleted={() => {
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            router.push("/immobilier/logements" as any);
          }}
        />
      ) : null}
    </>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-4">
      <dt className="text-white/50">{label}</dt>
      <dd className="text-right font-medium text-white">{value}</dd>
    </div>
  );
}
