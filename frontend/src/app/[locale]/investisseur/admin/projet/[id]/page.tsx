"use client";

/* Console admin — fiche d'un projet (compagnie).

   - Participations : ajouter un investisseur (compte créé + invitation
     courriel au besoin), % de parts, visibilité, flux (apports,
     remboursements, distributions) → nourrit le TRI.
   - Publication : description, phase, interrupteurs de transparence.
   - Jalons manuels de la timeline.
   - Documents partagés : upload PDF ou fichiers COCHÉS depuis le Drive
     de la compagnie (copie au partage — jamais le Drive complet). */

import { Fragment, useCallback, useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { useRouter } from "@/i18n/navigation";
import {
  Eye,
  FileText,
  FolderOpen,
  Loader2,
  Paperclip,
  Plus,
  Trash2,
  X
} from "lucide-react";

import { authedFetch } from "@/lib/auth";
import { useConfirm } from "@/components/confirm-dialog";
import { InvestisseurTopbar } from "../../../layout";
import {
  DepenseCategorie,
  DepensesParCategorie,
  fmtDate,
  fmtMoney,
  fmtPct,
  HypothequesCard,
  ImmeubleRow,
  PhaseBadge,
  RevDepChart,
  SerieMois,
  Timeline,
  TimelineEvent
} from "../../../invest-ui";

type FluxRow = {
  id: number;
  type: string;
  montant: number;
  date_flux: string;
  note: string | null;
  source: string;
};

type ParticipationRow = {
  id: number;
  user_id: number;
  user_name: string;
  user_email: string | null;
  parts_pct: number;
  statut: string;
  is_visible: boolean;
  notes: string | null;
  valeur_parts: number;
  capital_investi_total: number;
  capital_rembourse: number;
  distributions_recues: number;
  capital_actuel: number;
  tri_pct: number | null;
  tvpi: number | null;
  flux: FluxRow[];
};

type AdminProjet = {
  entreprise_id: number;
  name: string;
  drive_folder_id: string | null;
  phase: string;
  profil: {
    description: string | null;
    phase_override: string | null;
    show_depenses: boolean;
    show_hypotheque: boolean;
    show_actionnaires: boolean;
    show_cashflow: boolean;
    avances_actionnaires: number | null;
  };
  immeubles: (ImmeubleRow & {
    logements: {
      logement_id: number;
      numero: string | null;
      loue: boolean;
      loyer: number | null;
    }[];
  })[];
  valeur_totale: number;
  hypotheque_totale: number;
  avances_actionnaires: number;
  depenses_par_categorie: DepenseCategorie[];
  equite: number;
  loyers_mensuels: number;
  nb_logements: number;
  nb_baux_actifs: number;
  taux_occupation: number | null;
  serie_mensuelle: SerieMois[];
  revenus_mode?: "recus" | "potentiel";
  hypotheque_mensuelle: number;
  cashflow_moyen: number;
  timeline: TimelineEvent[];
  partenaires: PartenaireT[];
  participations: ParticipationRow[];
  jalons: {
    id: number;
    date_jalon: string;
    titre: string;
    description: string | null;
    kind: string;
  }[];
  documents: {
    id: number;
    title: string;
    source: string;
    size_bytes: number;
  }[];
};

type DriveFileT = {
  id: string;
  name: string;
  mime_type?: string;
  mimeType?: string;
  size?: string | null;
};

type PartenaireT = {
  partner_id: number;
  name: string;
  email: string | null;
  missing_email: boolean;
  role: string | null;
  ownership_pct: number | null;
  user_id: number | null;
  has_account: boolean;
  deja_participant: boolean;
  participation_id: number | null;
  is_visible: boolean;
};

const FLUX_LABELS: Record<string, string> = {
  apport: "Apport",
  remboursement: "Remboursement",
  dividende: "Distribution",
  sortie: "Sortie"
};

export default function AdminProjetPage() {
  const params = useParams<{ id: string }>();
  const entrepriseId = Number(params.id);
  const router = useRouter();
  const confirm = useConfirm();

  const [data, setData] = useState<AdminProjet | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [banner, setBanner] = useState<string | null>(null);

  const [addOpen, setAddOpen] = useState(false);
  const [driveOpen, setDriveOpen] = useState(false);
  const [uploadBusy, setUploadBusy] = useState(false);
  const [busyActiver, setBusyActiver] = useState<number | null>(null);
  const [expandedImm, setExpandedImm] = useState<number | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const res = await authedFetch(
        `/api/v1/invest/admin/projets/${entrepriseId}`
      );
      if (!res.ok) throw new Error(`http_${res.status}`);
      setData((await res.json()) as AdminProjet);
    } catch {
      setError("Projet introuvable ou chargement impossible.");
    } finally {
      setLoading(false);
    }
  }, [entrepriseId]);

  useEffect(() => {
    void load();
  }, [load]);

  async function patchProfil(body: Record<string, unknown>) {
    const res = await authedFetch(
      `/api/v1/invest/admin/projets/${entrepriseId}/profil`,
      { method: "PATCH", body: JSON.stringify(body) }
    );
    if (res.ok) await load();
  }

  async function activerPartenaire(pa: PartenaireT) {
    setBusyActiver(pa.partner_id);
    setBanner(null);
    try {
      const res = await authedFetch(
        `/api/v1/invest/admin/projets/${entrepriseId}/partenaires/${pa.partner_id}/activer`,
        { method: "POST" }
      );
      const body = await res.json().catch(() => null);
      if (!res.ok) {
        setBanner(
          typeof body?.detail === "string"
            ? body.detail
            : "Activation échouée."
        );
        return;
      }
      if (body?.invitation_sent) {
        setBanner(
          `Compte créé et invitation envoyée à ${pa.email}. Le projet ` +
            "reste masqué pour lui — activez « Visible dans son " +
            "portail » quand vous êtes prêt."
        );
      } else if (body?.temp_password) {
        setBanner(
          `Compte créé mais courriel non configuré — transmettez ce ` +
            `mot de passe temporaire à ${pa.name} : ${body.temp_password}`
        );
      }
      await load();
    } finally {
      setBusyActiver(null);
    }
  }

  async function removeParticipation(p: ParticipationRow) {
    if (
      !(await confirm({
        title: `Retirer ${p.user_name} de ce projet ?`,
        description:
          "Sa participation et tous ses flux seront supprimés. Son " +
          "compte investisseur n'est pas touché.",
        confirmLabel: "Retirer",
        destructive: true
      }))
    ) {
      return;
    }
    const res = await authedFetch(
      `/api/v1/invest/admin/participations/${p.id}`,
      { method: "DELETE" }
    );
    if (res.ok) await load();
  }

  async function removeFlux(fluxId: number) {
    if (!(await confirm({ title: "Supprimer ce flux ?" }))) return;
    const res = await authedFetch(
      `/api/v1/invest/admin/flux/${fluxId}`,
      { method: "DELETE" }
    );
    if (res.ok) await load();
  }

  async function removeJalon(id: number) {
    if (!(await confirm({ title: "Supprimer ce jalon ?" }))) return;
    const res = await authedFetch(`/api/v1/invest/admin/jalons/${id}`, {
      method: "DELETE"
    });
    if (res.ok) await load();
  }

  async function removeDocument(id: number) {
    if (
      !(await confirm({
        title: "Retirer ce document partagé ?",
        description: "Les investisseurs ne le verront plus.",
        confirmLabel: "Retirer",
        destructive: true
      }))
    ) {
      return;
    }
    const res = await authedFetch(
      `/api/v1/invest/admin/documents/${id}`,
      { method: "DELETE" }
    );
    if (res.ok) await load();
  }

  async function uploadDocument(file: File) {
    setUploadBusy(true);
    try {
      const fd = new FormData();
      fd.append("file", file);
      const res = await authedFetch(
        `/api/v1/invest/admin/projets/${entrepriseId}/documents`,
        { method: "POST", body: fd }
      );
      if (!res.ok) {
        const body = await res.json().catch(() => null);
        setBanner(
          typeof body?.detail === "string"
            ? body.detail
            : "Téléversement échoué."
        );
        return;
      }
      await load();
    } finally {
      setUploadBusy(false);
    }
  }

  async function openDocument(id: number) {
    const res = await authedFetch(
      `/api/v1/invest/admin/documents/${id}/pdf`
    );
    if (!res.ok) return;
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    window.open(url, "_blank", "noopener");
    setTimeout(() => URL.revokeObjectURL(url), 60_000);
  }

  if (loading) {
    return (
      <>
        <InvestisseurTopbar
          breadcrumbs={[
            { label: "Console admin", href: "/investisseur/admin" },
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
            { label: "Console admin", href: "/investisseur/admin" },
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
          { label: "Console admin", href: "/investisseur/admin" },
          { label: data.name }
        ]}
      />

      <div className="mx-auto w-full max-w-6xl p-4 lg:p-6">
        {banner ? (
          <div className="mb-4 flex items-start justify-between gap-3 rounded-lg border border-amber-500/40 bg-amber-500/10 px-4 py-3 text-sm text-amber-400">
            <span>{banner}</span>
            <button
              type="button"
              onClick={() => setBanner(null)}
              className="shrink-0 hover:opacity-70"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        ) : null}

        <div className="mb-1 flex flex-wrap items-center gap-3">
          <h1 className="text-xl font-bold text-white">{data.name}</h1>
          <PhaseBadge phase={data.phase} />
        </div>
        <p className="mb-5 text-xs text-white/40">
          Tableau de bord consolidé — tous les immeubles et
          investissements de la compagnie s&apos;additionnent ici. C&apos;est
          ce que verront ses investisseurs.
        </p>

        {/* ── Dashboard du projet (visible même sans investisseur) ── */}
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
              {fmtMoney(data.hypotheque_mensuelle)}/mois
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
              {data.avances_actionnaires > 0
                ? `valeur − hypothèques − avances (${fmtMoney(
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
        <div className="mt-4 overflow-hidden rounded-2xl border border-brand-800 bg-brand-900">
          <div className="flex items-center justify-between border-b border-brand-800 px-4 py-2.5">
            <h2 className="text-sm font-semibold text-white">
              Immeubles de la compagnie
            </h2>
            <span className="text-xs text-white/40">
              {data.immeubles.length} immeuble
              {data.immeubles.length > 1 ? "s" : ""} — c&apos;est ce que
              verront les investisseurs
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
                  <Fragment key={im.immeuble_id}>
                    <tr
                      onClick={() =>
                        setExpandedImm(
                          expandedImm === im.immeuble_id
                            ? null
                            : im.immeuble_id
                        )
                      }
                      className="cursor-pointer border-t border-brand-800/60 transition hover:bg-white/[0.03]"
                      title="Cliquez pour voir les logements"
                    >
                      <td className="px-4 py-3">
                        <p className="font-medium text-white">
                          {expandedImm === im.immeuble_id ? "▾ " : "▸ "}
                          {im.address || im.name}
                        </p>
                        <p className="text-xs text-white/40">
                          {im.nb_baux_actifs} / {im.nb_logements || "—"}{" "}
                          loués
                          {im.ownership_pct !== 100
                            ? ` · détenu à ${im.ownership_pct} %`
                            : ""}
                          {im.valeur_source === "achat"
                            ? " · ⚠ valeur = prix d'achat (aucune évaluation saisie)"
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
                          <span
                            className="block text-[11px] text-amber-400"
                            title="Loyer si toutes les unités étaient louées"
                          >
                            pot. {fmtMoney(im.loyers_potentiels ?? 0)}
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
                    {expandedImm === im.immeuble_id ? (
                      <tr className="border-t border-brand-800/40 bg-brand-950/50">
                        <td colSpan={6} className="px-4 py-3">
                          {im.logements.length === 0 ? (
                            <p className="text-xs text-white/40">
                              Aucun logement saisi pour cet immeuble
                              dans le pôle locatif.
                            </p>
                          ) : (
                            <div className="grid grid-cols-2 gap-1.5 sm:grid-cols-3 lg:grid-cols-4">
                              {im.logements.map((lg) => (
                                <div
                                  key={lg.logement_id}
                                  className={`rounded-lg border px-2.5 py-1.5 text-xs ${
                                    lg.loue
                                      ? "border-brand-800"
                                      : "border-amber-500/40 bg-amber-500/5"
                                  }`}
                                >
                                  <span className="font-medium text-white">
                                    {lg.numero || "—"}
                                  </span>
                                  <span
                                    className={`ml-1.5 ${
                                      lg.loue
                                        ? "text-emerald-400"
                                        : "text-amber-400"
                                    }`}
                                  >
                                    {lg.loue ? "Loué" : "Vacant"}
                                  </span>
                                  <span className="float-right tabular-nums text-white/70">
                                    {lg.loyer !== null
                                      ? `${fmtMoney(lg.loyer)}${
                                          lg.loue ? "" : " (demandé)"
                                        }`
                                      : "—"}
                                  </span>
                                </div>
                              ))}
                            </div>
                          )}
                        </td>
                      </tr>
                    ) : null}
                  </Fragment>
                ))}
                {data.immeubles.length > 1 ? (
                  <tr className="border-t-2 border-brand-700 bg-brand-950/40 font-semibold">
                    <td className="px-4 py-3 text-white">TOTAL</td>
                    <td className="px-4 py-3 text-right text-white">
                      {data.immeubles.reduce(
                        (s, im) => s + im.nb_logements,
                        0
                      ) || "—"}
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
          {data.immeubles.length === 0 ? (
            <p className="px-4 py-4 text-sm text-amber-400">
              ⚠ Aucun immeuble lié à cette compagnie. Dans le pôle
              locatif, ouvrez la fiche de l&apos;immeuble et choisissez
              cette compagnie comme propriétaire — il apparaîtra ici
              automatiquement.
            </p>
          ) : null}
        </div>

        {/* Timeline + hypothèques */}
        <div className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-2">
          <div className="rounded-2xl border border-brand-800 bg-brand-900 p-5">
            <h2 className="mb-1 text-sm font-semibold text-white">
              Timeline du projet
            </h2>
            <p className="mb-4 text-[11px] text-white/35">
              Automatique : acquisitions (dates d&apos;achat des
              immeubles), financements (hypothèques du pôle locatif),
              flux des investisseurs, phase d&apos;optimisation — plus
              vos jalons manuels ci-dessous.
            </p>
            <Timeline events={data.timeline} />
          </div>
          <HypothequesCard immeubles={data.immeubles} />
        </div>

        {/* Revenus / dépenses : normalisés (pôle locatif) vs réels (QBO) */}
        <div className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-2">
          <div className="rounded-2xl border border-brand-800 bg-brand-900 p-4 text-white">
            <div className="mb-1 flex flex-wrap items-baseline justify-between gap-2">
              <h2 className="text-sm font-semibold">
                Revenus et dépenses normalisés
              </h2>
              <span className="text-xs text-white/50 tabular-nums">
                Cash-flow moyen :{" "}
                <b
                  className={
                    data.cashflow_moyen >= 0
                      ? "text-emerald-400"
                      : "text-rose-400"
                  }
                >
                  {data.cashflow_moyen >= 0 ? "+" : ""}
                  {fmtMoney(data.cashflow_moyen)}/mois
                </b>
              </span>
            </div>
            <p className="mb-2 text-[11px] text-white/35">
              Pôle gestion locative — loyers et dépenses récurrentes,
              12 derniers mois.
            </p>
            <RevDepChart serie={data.serie_mensuelle} showDepenses />
            <div className="mt-1 flex flex-wrap gap-4 text-xs text-white/50">
              <span className="inline-flex items-center gap-1.5">
                <i className="inline-block h-2.5 w-2.5 rounded-sm bg-[#199e70]" />
                {data.revenus_mode === "potentiel"
                  ? "Loyers (unités louées — paiements détaillés non suivis)"
                  : "Revenus perçus"}
              </span>
              <span className="inline-flex items-center gap-1.5">
                <i className="inline-block h-2.5 w-2.5 rounded-sm bg-[#e66767]" />
                Dépenses
              </span>
            </div>
            <DepensesParCategorie items={data.depenses_par_categorie} />
          </div>
          <QboReelsPanel entrepriseId={entrepriseId} />
        </div>

        <h2 className="mb-3 mt-8 text-base font-semibold text-white">
          Gestion des investisseurs et de la publication
        </h2>
        <div className="grid grid-cols-1 gap-4 xl:grid-cols-[1.2fr_0.8fr]">
          {/* ── Colonne gauche : participations ── */}
          <div className="min-w-0 space-y-4">
            <div className="rounded-2xl border border-brand-800 bg-brand-900 p-4">
              <div className="mb-3 flex items-center justify-between">
                <h2 className="text-sm font-semibold text-white">
                  Actionnaires &amp; participations
                </h2>
                <button
                  type="button"
                  onClick={() => setAddOpen(true)}
                  className="btn-secondary btn-xs inline-flex items-center gap-1"
                  title="Pour un investisseur qui n'est pas dans Parts & actionnaires"
                >
                  <Plus className="h-3 w-3" />
                  Autre investisseur
                </button>
              </div>

              {/* Actionnaires de la fiche entreprise — activation 1 clic */}
              {data.partenaires.length > 0 ? (
                <div className="mb-3 rounded-xl border border-brand-800 bg-brand-950/60 p-3">
                  <p className="mb-2 text-[10px] font-semibold uppercase tracking-wider text-white/40">
                    Parts &amp; actionnaires (fiche entreprise)
                  </p>
                  <ul className="space-y-1.5">
                    {data.partenaires.map((pa) => (
                      <li
                        key={pa.partner_id}
                        className="flex flex-wrap items-center justify-between gap-2 text-sm"
                      >
                        <div className="min-w-0">
                          <span className="font-medium text-white">
                            {pa.name}
                          </span>
                          {pa.ownership_pct !== null ? (
                            <span className="ml-1.5 text-xs text-white/50 tabular-nums">
                              {pa.ownership_pct.toLocaleString("fr-CA", {
                                maximumFractionDigits: 1
                              })}{" "}
                              %
                            </span>
                          ) : null}
                          <span className="ml-1.5 text-xs">
                            {pa.missing_email ? (
                              <span className="text-amber-400">
                                ⚠ courriel manquant (fiche entreprise)
                              </span>
                            ) : (
                              <span className="text-white/40">
                                {pa.email}
                              </span>
                            )}
                          </span>
                        </div>
                        <div className="shrink-0">
                          {pa.deja_participant ? (
                            <span
                              className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10.5px] font-bold ${
                                pa.is_visible
                                  ? "border-emerald-500/50 bg-emerald-500/10 text-emerald-400"
                                  : "border-amber-500/50 bg-amber-500/10 text-amber-400"
                              }`}
                            >
                              {pa.is_visible
                                ? "✓ Visible dans son portail"
                                : "Activé · masqué"}
                            </span>
                          ) : (
                            <button
                              type="button"
                              onClick={() => void activerPartenaire(pa)}
                              disabled={
                                (pa.missing_email && !pa.has_account) ||
                                busyActiver === pa.partner_id
                              }
                              title={
                                pa.missing_email && !pa.has_account
                                  ? "Ajoutez d'abord son courriel dans la fiche entreprise"
                                  : pa.has_account
                                  ? "Crée sa participation (masquée) sur ce projet"
                                  : "Crée son compte (invitation courriel) + sa participation masquée"
                              }
                              className="btn-outline-accent btn-xs disabled:opacity-40"
                            >
                              {busyActiver === pa.partner_id ? (
                                <Loader2 className="h-3 w-3 animate-spin" />
                              ) : pa.has_account ? (
                                "Activer sur ce projet"
                              ) : (
                                "Créer le compte & activer"
                              )}
                            </button>
                          )}
                        </div>
                      </li>
                    ))}
                  </ul>
                  <p className="mt-2 text-[10px] text-white/35">
                    Synchronisé depuis la fiche entreprise. Après
                    activation : ajoutez l&apos;apport dans sa carte
                    ci-dessous, puis cochez « Visible dans son portail ».
                  </p>
                </div>
              ) : null}

              {data.participations.length === 0 ? (
                <p className="py-4 text-center text-sm text-white/50">
                  {data.partenaires.length > 0
                    ? "Aucune participation active — activez un actionnaire ci-dessus."
                    : "Aucun actionnaire dans la fiche entreprise (Parts & actionnaires) — ajoutez-les là, ou utilisez « Autre investisseur »."}
                </p>
              ) : (
                <div className="space-y-3">
                  {data.participations.map((p) => (
                    <ParticipationCard
                      key={p.id}
                      p={p}
                      onChanged={load}
                      onRemove={() => void removeParticipation(p)}
                      onRemoveFlux={(fid) => void removeFlux(fid)}
                      onVoirComme={() =>
                        router.push(
                          // eslint-disable-next-line @typescript-eslint/no-explicit-any
                          `/investisseur?apercu=${p.user_id}` as any
                        )
                      }
                    />
                  ))}
                </div>
              )}
            </div>

            {/* Jalons */}
            <JalonsCard
              entrepriseId={entrepriseId}
              jalons={data.jalons}
              onChanged={load}
              onRemove={(id) => void removeJalon(id)}
            />
          </div>

          {/* ── Colonne droite : publication + documents ── */}
          <div className="min-w-0 space-y-4">
            <div className="rounded-2xl border border-brand-800 bg-brand-900 p-4">
              <h2 className="mb-3 text-sm font-semibold text-white">
                Publication
              </h2>
              <label className="label">Présentation du projet</label>
              <textarea
                defaultValue={data.profil.description || ""}
                onBlur={(e) => {
                  const v = e.target.value.trim();
                  if (v !== (data.profil.description || "")) {
                    void patchProfil({ description: v });
                  }
                }}
                rows={3}
                placeholder="Petit texte affiché en tête de la fiche projet…"
                className="input w-full text-xs"
              />
              <div className="mt-3">
                <label className="label">Phase affichée</label>
                <select
                  value={data.profil.phase_override || ""}
                  onChange={(e) =>
                    void patchProfil({ phase_override: e.target.value })
                  }
                  className="input w-full text-xs"
                >
                  <option value="">
                    Automatique (selon la section optimisation)
                  </option>
                  <option value="optimisation">Optimisation</option>
                  <option value="long_terme">Détention long terme</option>
                </select>
              </div>
              <div className="mt-3">
                <label className="label">
                  Avances aux actionnaires ($)
                </label>
                <input
                  type="number"
                  min="0"
                  step="1000"
                  defaultValue={data.profil.avances_actionnaires ?? ""}
                  onBlur={(e) => {
                    const v = e.target.value ? Number(e.target.value) : 0;
                    if (v !== (data.profil.avances_actionnaires ?? 0)) {
                      void patchProfil({ avances_actionnaires: v });
                    }
                  }}
                  placeholder="0"
                  className="input w-full text-xs tabular-nums"
                />
                <p className="mt-1 text-[10px] text-white/35">
                  Soustraites de l&apos;équité : équité = valeur −
                  hypothèques − avances.
                </p>
              </div>
              <div className="mt-3 space-y-2">
                {(
                  [
                    ["show_depenses", "Dépenses détaillées visibles"],
                    [
                      "show_hypotheque",
                      "Détails d'hypothèque visibles (prêteur, taux, terme)"
                    ],
                    ["show_actionnaires", "Liste des actionnaires visible"],
                    ["show_cashflow", "Cash-flow visible"]
                  ] as const
                ).map(([key, label]) => (
                  <label
                    key={key}
                    className="flex items-center justify-between gap-2 text-xs text-white/70"
                  >
                    <span>{label}</span>
                    <input
                      type="checkbox"
                      checked={data.profil[key]}
                      onChange={(e) =>
                        void patchProfil({ [key]: e.target.checked })
                      }
                    />
                  </label>
                ))}
              </div>
            </div>

            {/* Documents */}
            <div className="rounded-2xl border border-brand-800 bg-brand-900 p-4">
              <div className="mb-2 flex items-center justify-between">
                <h2 className="text-sm font-semibold text-white">
                  Documents partagés
                </h2>
                <div className="flex items-center gap-1.5">
                  <button
                    type="button"
                    onClick={() => {
                      if (data.drive_folder_id) {
                        setDriveOpen(true);
                      } else {
                        setBanner(
                          "Aucun dossier Drive lié à cette compagnie — " +
                            "collez le lien de son dossier Google Drive " +
                            "dans la fiche entreprise (gestion " +
                            "d'entreprise), puis revenez cocher les " +
                            "fichiers à partager."
                        );
                      }
                    }}
                    className="btn-secondary btn-xs inline-flex items-center gap-1"
                  >
                    <FolderOpen className="h-3 w-3" />
                    Depuis le Drive
                  </button>
                  <label className="btn-outline-accent btn-xs inline-flex cursor-pointer items-center gap-1">
                    {uploadBusy ? (
                      <Loader2 className="h-3 w-3 animate-spin" />
                    ) : (
                      <Paperclip className="h-3 w-3" />
                    )}
                    PDF
                    <input
                      type="file"
                      accept="application/pdf"
                      className="hidden"
                      disabled={uploadBusy}
                      onChange={(e) => {
                        const f = e.target.files?.[0];
                        if (f) void uploadDocument(f);
                        e.target.value = "";
                      }}
                    />
                  </label>
                </div>
              </div>
              <p className="mb-2 text-[11px] text-white/35">
                Les investisseurs ne voient QUE cette liste — jamais le
                Drive complet de l&apos;immeuble.
              </p>
              {data.documents.length === 0 ? (
                <p className="py-3 text-center text-xs text-white/40">
                  Aucun document partagé.
                </p>
              ) : (
                <ul>
                  {data.documents.map((d) => (
                    <li
                      key={d.id}
                      className="flex items-center justify-between gap-2 border-b border-brand-800/60 py-2 last:border-0"
                    >
                      <button
                        type="button"
                        onClick={() => void openDocument(d.id)}
                        className="flex min-w-0 items-center gap-2 text-left hover:opacity-80"
                      >
                        <FileText className="h-4 w-4 shrink-0 text-accent-500" />
                        <span className="min-w-0">
                          <span className="block truncate text-sm text-white">
                            {d.title}
                          </span>
                          <span className="text-[11px] text-white/40">
                            {d.source === "drive"
                              ? "copié du Drive"
                              : "téléversé"}{" "}
                            · {(d.size_bytes / 1024 / 1024).toFixed(1)} Mo
                          </span>
                        </span>
                      </button>
                      <button
                        type="button"
                        onClick={() => void removeDocument(d.id)}
                        className="shrink-0 rounded p-1 text-white/40 hover:text-rose-400"
                        aria-label="Retirer"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        </div>
      </div>

      {addOpen ? (
        <AddParticipationModal
          entrepriseId={entrepriseId}
          onClose={() => setAddOpen(false)}
          onAdded={async (msg) => {
            setAddOpen(false);
            if (msg) setBanner(msg);
            await load();
          }}
        />
      ) : null}
      {driveOpen && data.drive_folder_id ? (
        <DrivePickerModal
          entrepriseId={entrepriseId}
          folderId={data.drive_folder_id}
          onClose={() => setDriveOpen(false)}
          onShared={async () => {
            setDriveOpen(false);
            await load();
          }}
        />
      ) : null}
    </>
  );
}

/* ──────── Revenus / dépenses RÉELS (QuickBooks — optimisation) ──────── */

type QboReels = {
  statut: "aucun_projet" | "sans_qbo" | "erreur" | "connecte";
  projet_nom?: string;
  erreur?: string;
  rows?: {
    mois: string;
    revenus: number;
    depenses: number;
    hypotheque: number;
    ecart: number;
  }[];
  total?: {
    revenus: number;
    depenses: number;
    hypotheque: number;
    ecart: number;
  } | null;
};

function QboReelsPanel({ entrepriseId }: { entrepriseId: number }) {
  const [reels, setReels] = useState<QboReels | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    authedFetch(`/api/v1/invest/admin/projets/${entrepriseId}/qbo-reels`)
      .then(async (res) => {
        if (cancelled) return;
        if (!res.ok) {
          setFailed(true);
          return;
        }
        setReels((await res.json()) as QboReels);
      })
      .catch(() => {
        if (!cancelled) setFailed(true);
      });
    return () => {
      cancelled = true;
    };
  }, [entrepriseId]);

  const naBox = (titre: string, texte: string) => (
    <div className="rounded-xl border border-dashed border-brand-700 bg-brand-950/40 px-4 py-6 text-center">
      <p className="text-sm font-semibold text-white/70">{titre}</p>
      <p className="mx-auto mt-1 max-w-sm text-xs text-white/40">
        {texte}
      </p>
    </div>
  );

  const rows = reels?.rows || [];
  const showHyp =
    rows.some((r) => Math.abs(r.hypotheque) >= 0.01) ||
    Math.abs(reels?.total?.hypotheque || 0) >= 0.01;

  return (
    <div className="rounded-2xl border border-brand-800 bg-brand-900 p-4 text-white">
      <div className="mb-1 flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-sm font-semibold">
          Revenus et dépenses réels
        </h2>
        {reels?.statut === "connecte" && reels.projet_nom ? (
          <span className="text-xs text-white/40">
            QuickBooks · {reels.projet_nom}
          </span>
        ) : null}
      </div>
      <p className="mb-3 text-[11px] text-white/35">
        Importations QuickBooks du projet lié dans la section
        optimisation (gestion d&apos;entreprise) — 12 derniers mois.
      </p>

      {failed ? (
        naBox(
          "Chargement impossible",
          "Les données réelles n'ont pas pu être chargées — réessayez plus tard."
        )
      ) : reels === null ? (
        <div className="flex justify-center py-10">
          <Loader2 className="h-5 w-5 animate-spin text-accent-500" />
        </div>
      ) : reels.statut === "aucun_projet" ? (
        naBox(
          "Non applicable — pas encore rentré",
          "Cette compagnie n'a aucun projet dans la section optimisation " +
            "de gestion d'entreprise. Créez-y le projet et connectez " +
            "QuickBooks pour voir les chiffres réels ici."
        )
      ) : reels.statut === "sans_qbo" ? (
        naBox(
          "QuickBooks non connecté",
          `Le projet « ${reels.projet_nom} » existe dans la section ` +
            "optimisation, mais aucune connexion QuickBooks n'est " +
            "choisie dans ses réglages."
        )
      ) : reels.statut === "erreur" ? (
        naBox(
          "Lecture QuickBooks impossible",
          reels.erreur ||
            "Erreur de lecture — vérifiez la connexion QuickBooks dans la section optimisation."
        )
      ) : rows.length === 0 ? (
        naBox(
          "Aucune donnée sur la période",
          "QuickBooks est connecté mais le rapport des 12 derniers mois est vide."
        )
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-xs tabular-nums">
            <thead>
              <tr className="text-left text-[10px] uppercase tracking-wider text-white/40">
                <th className="py-1.5 pr-2 font-medium">Mois</th>
                <th className="py-1.5 pl-2 text-right font-medium">
                  Revenus
                </th>
                <th className="py-1.5 pl-2 text-right font-medium">
                  Dépenses
                </th>
                {showHyp ? (
                  <th className="py-1.5 pl-2 text-right font-medium">
                    Hypothèque
                  </th>
                ) : null}
                <th className="py-1.5 pl-2 text-right font-medium">
                  Écart
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr
                  key={r.mois}
                  className="border-t border-brand-800/60"
                >
                  <td className="py-1.5 pr-2 text-white/70">{r.mois}</td>
                  <td className="py-1.5 pl-2 text-right text-white/80">
                    {fmtMoney(r.revenus)}
                  </td>
                  <td className="py-1.5 pl-2 text-right text-white/80">
                    {fmtMoney(r.depenses)}
                  </td>
                  {showHyp ? (
                    <td className="py-1.5 pl-2 text-right text-white/80">
                      {fmtMoney(r.hypotheque)}
                    </td>
                  ) : null}
                  <td
                    className={`py-1.5 pl-2 text-right font-semibold ${
                      r.ecart >= 0 ? "text-emerald-400" : "text-rose-400"
                    }`}
                  >
                    {r.ecart >= 0 ? "+" : ""}
                    {fmtMoney(r.ecart)}
                  </td>
                </tr>
              ))}
              {reels.total ? (
                <tr className="border-t-2 border-brand-700 font-semibold">
                  <td className="py-2 pr-2 text-white">TOTAL</td>
                  <td className="py-2 pl-2 text-right text-white">
                    {fmtMoney(reels.total.revenus)}
                  </td>
                  <td className="py-2 pl-2 text-right text-white">
                    {fmtMoney(reels.total.depenses)}
                  </td>
                  {showHyp ? (
                    <td className="py-2 pl-2 text-right text-white">
                      {fmtMoney(reels.total.hypotheque)}
                    </td>
                  ) : null}
                  <td
                    className={`py-2 pl-2 text-right ${
                      reels.total.ecart >= 0
                        ? "text-emerald-400"
                        : "text-rose-400"
                    }`}
                  >
                    {reels.total.ecart >= 0 ? "+" : ""}
                    {fmtMoney(reels.total.ecart)}
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

/* ─────────────────── Carte participation + flux ─────────────────── */

function ParticipationCard({
  p,
  onChanged,
  onRemove,
  onRemoveFlux,
  onVoirComme
}: {
  p: ParticipationRow;
  onChanged: () => Promise<void>;
  onRemove: () => void;
  onRemoveFlux: (fluxId: number) => void;
  onVoirComme: () => void;
}) {
  const [fluxType, setFluxType] = useState("apport");
  const [fluxMontant, setFluxMontant] = useState("");
  const [fluxDate, setFluxDate] = useState(
    new Date().toISOString().slice(0, 10)
  );
  const [fluxNote, setFluxNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function patch(body: Record<string, unknown>) {
    const res = await authedFetch(
      `/api/v1/invest/admin/participations/${p.id}`,
      { method: "PATCH", body: JSON.stringify(body) }
    );
    if (res.ok) await onChanged();
  }

  async function addFlux(e: React.FormEvent) {
    e.preventDefault();
    const montant = Number(fluxMontant.replace(",", "."));
    if (!montant || montant <= 0) {
      setErr("Montant invalide.");
      return;
    }
    setBusy(true);
    setErr(null);
    try {
      const res = await authedFetch(
        `/api/v1/invest/admin/participations/${p.id}/flux`,
        {
          method: "POST",
          body: JSON.stringify({
            type: fluxType,
            montant,
            date_flux: fluxDate,
            note: fluxNote.trim() || null
          })
        }
      );
      if (!res.ok) {
        const body = await res.json().catch(() => null);
        setErr(
          typeof body?.detail === "string"
            ? body.detail
            : "Ajout du flux échoué."
        );
        return;
      }
      setFluxMontant("");
      setFluxNote("");
      await onChanged();
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="rounded-xl border border-brand-800 bg-brand-950/60 p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="min-w-0">
          <p className="text-sm font-semibold text-white">
            {p.user_name}
            <span className="ml-2 text-xs font-normal text-white/40">
              {p.user_email}
            </span>
          </p>
          <p className="text-xs text-white/50 tabular-nums">
            Capital actuel {fmtMoney(p.capital_actuel)} · valeur des
            parts {fmtMoney(p.valeur_parts)} · TRI {fmtPct(p.tri_pct)}
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-1.5">
          <button
            type="button"
            onClick={onVoirComme}
            className="btn-secondary btn-xs inline-flex items-center gap-1"
          >
            <Eye className="h-3 w-3" />
            Voir comme lui
          </button>
          <button
            type="button"
            onClick={onRemove}
            className="rounded p-1.5 text-white/40 hover:text-rose-400"
            aria-label="Retirer la participation"
          >
            <Trash2 className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>

      <div className="mt-2 flex flex-wrap items-center gap-3 text-xs">
        <label className="flex items-center gap-1.5 text-white/60">
          Parts
          <input
            type="number"
            step="0.1"
            min="0.1"
            max="100"
            defaultValue={p.parts_pct}
            onBlur={(e) => {
              const v = Number(e.target.value);
              if (v && v !== p.parts_pct) void patch({ parts_pct: v });
            }}
            className="input w-20 text-xs tabular-nums"
          />
          %
        </label>
        <label className="flex items-center gap-1.5 text-white/60">
          <input
            type="checkbox"
            checked={p.is_visible}
            onChange={(e) => void patch({ is_visible: e.target.checked })}
          />
          Visible dans son portail
        </label>
        <label className="flex items-center gap-1.5 text-white/60">
          Statut
          <select
            value={p.statut}
            onChange={(e) => void patch({ statut: e.target.value })}
            className="input text-xs"
          >
            <option value="actif">Actif</option>
            <option value="sorti">Sorti</option>
          </select>
        </label>
      </div>

      {/* Flux */}
      <div className="mt-3 border-t border-brand-800 pt-2">
        {p.flux.length > 0 ? (
          <ul className="mb-2 space-y-1">
            {p.flux.map((f) => (
              <li
                key={f.id}
                className="flex items-center justify-between gap-2 text-xs"
              >
                <span className="text-white/70">
                  {fmtDate(f.date_flux)} —{" "}
                  {FLUX_LABELS[f.type] || f.type}
                  {f.note ? (
                    <span className="text-white/40"> · {f.note}</span>
                  ) : null}
                </span>
                <span className="flex items-center gap-2">
                  <b
                    className={`tabular-nums ${
                      f.type === "apport"
                        ? "text-white/80"
                        : "text-emerald-400"
                    }`}
                  >
                    {f.type === "apport" ? "−" : "+"}
                    {fmtMoney(f.montant)}
                  </b>
                  <button
                    type="button"
                    onClick={() => onRemoveFlux(f.id)}
                    className="rounded p-0.5 text-white/30 hover:text-rose-400"
                    aria-label="Supprimer le flux"
                  >
                    <X className="h-3 w-3" />
                  </button>
                </span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="mb-2 text-xs text-white/40">
            Aucun flux — ajoutez l&apos;apport initial ci-dessous.
          </p>
        )}
        <form
          onSubmit={addFlux}
          className="flex flex-wrap items-center gap-1.5"
        >
          <select
            value={fluxType}
            onChange={(e) => setFluxType(e.target.value)}
            className="input text-xs"
          >
            <option value="apport">Apport</option>
            <option value="remboursement">Remboursement</option>
            <option value="dividende">Distribution</option>
            <option value="sortie">Sortie</option>
          </select>
          <input
            value={fluxMontant}
            onChange={(e) => setFluxMontant(e.target.value)}
            placeholder="Montant $"
            inputMode="decimal"
            className="input w-24 text-xs tabular-nums"
          />
          <input
            type="date"
            value={fluxDate}
            onChange={(e) => setFluxDate(e.target.value)}
            className="input text-xs"
          />
          <input
            value={fluxNote}
            onChange={(e) => setFluxNote(e.target.value)}
            placeholder="Note (optionnel)"
            className="input min-w-0 flex-1 text-xs"
          />
          <button
            type="submit"
            disabled={busy}
            className="btn-outline-accent btn-xs"
          >
            {busy ? (
              <Loader2 className="h-3 w-3 animate-spin" />
            ) : (
              "Ajouter"
            )}
          </button>
        </form>
        {err ? <p className="mt-1 text-xs text-rose-400">{err}</p> : null}
        <p className="mt-2 text-[10px] text-white/35">
          Un flux = un événement réel (apport, remboursement,
          distribution) — c&apos;est ce qui nourrit le capital investi,
          la valeur des parts et le TRI. À venir : proposition
          automatique de ces flux depuis QuickBooks (aucune double
          saisie).
        </p>
      </div>
    </div>
  );
}

/* ─────────────────────── Jalons ─────────────────────── */

function JalonsCard({
  entrepriseId,
  jalons,
  onChanged,
  onRemove
}: {
  entrepriseId: number;
  jalons: AdminProjet["jalons"];
  onChanged: () => Promise<void>;
  onRemove: (id: number) => void;
}) {
  const [dateJalon, setDateJalon] = useState(
    new Date().toISOString().slice(0, 10)
  );
  const [titre, setTitre] = useState("");
  const [kind, setKind] = useState("autre");
  const [descr, setDescr] = useState("");
  const [busy, setBusy] = useState(false);

  async function add(e: React.FormEvent) {
    e.preventDefault();
    if (!titre.trim()) return;
    setBusy(true);
    try {
      const res = await authedFetch(
        `/api/v1/invest/admin/projets/${entrepriseId}/jalons`,
        {
          method: "POST",
          body: JSON.stringify({
            date_jalon: dateJalon,
            titre: titre.trim(),
            description: descr.trim() || null,
            kind
          })
        }
      );
      if (res.ok) {
        setTitre("");
        setDescr("");
        await onChanged();
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="rounded-2xl border border-brand-800 bg-brand-900 p-4">
      <h2 className="mb-1 text-sm font-semibold text-white">
        Jalons de la timeline
      </h2>
      <p className="mb-3 text-[11px] text-white/35">
        Les acquisitions et les flux apparaissent automatiquement —
        ajoutez ici les moments marquants (fin des rénovations, hausse
        des loyers, refinancement en cours…).
      </p>
      {jalons.length > 0 ? (
        <ul className="mb-3 space-y-1.5">
          {jalons.map((j) => (
            <li
              key={j.id}
              className="flex items-start justify-between gap-2 text-sm"
            >
              <div>
                <p className="text-white">
                  <span className="text-xs text-white/40">
                    {fmtDate(j.date_jalon)} —{" "}
                  </span>
                  {j.titre}
                </p>
                {j.description ? (
                  <p className="text-xs text-white/50">{j.description}</p>
                ) : null}
              </div>
              <button
                type="button"
                onClick={() => onRemove(j.id)}
                className="shrink-0 rounded p-1 text-white/30 hover:text-rose-400"
                aria-label="Supprimer"
              >
                <X className="h-3 w-3" />
              </button>
            </li>
          ))}
        </ul>
      ) : null}
      <form onSubmit={add} className="space-y-1.5">
        <div className="flex flex-wrap gap-1.5">
          <input
            type="date"
            value={dateJalon}
            onChange={(e) => setDateJalon(e.target.value)}
            className="input text-xs"
          />
          <select
            value={kind}
            onChange={(e) => setKind(e.target.value)}
            className="input text-xs"
          >
            <option value="autre">Jalon</option>
            <option value="acquisition">Acquisition</option>
            <option value="optimisation">Optimisation</option>
            <option value="refinancement">Refinancement</option>
          </select>
          <input
            value={titre}
            onChange={(e) => setTitre(e.target.value)}
            placeholder="Titre (ex. : Loyers optimisés +43 %)"
            className="input min-w-0 flex-1 text-xs"
          />
        </div>
        <div className="flex gap-1.5">
          <input
            value={descr}
            onChange={(e) => setDescr(e.target.value)}
            placeholder="Détail (optionnel)"
            className="input min-w-0 flex-1 text-xs"
          />
          <button
            type="submit"
            disabled={busy || !titre.trim()}
            className="btn-outline-accent btn-xs shrink-0"
          >
            {busy ? (
              <Loader2 className="h-3 w-3 animate-spin" />
            ) : (
              "Ajouter"
            )}
          </button>
        </div>
      </form>
    </div>
  );
}

/* ──────────────── Modal ajout de participation ──────────────── */

function AddParticipationModal({
  entrepriseId,
  onClose,
  onAdded
}: {
  entrepriseId: number;
  onClose: () => void;
  onAdded: (banner: string | null) => Promise<void>;
}) {
  const [existing, setExisting] = useState<
    { user_id: number; name: string; email: string }[]
  >([]);
  const [mode, setMode] = useState<"nouveau" | "existant">("nouveau");
  const [existingId, setExistingId] = useState("");
  const [firstName, setFirstName] = useState("");
  const [lastName, setLastName] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [pct, setPct] = useState("");
  const [apport, setApport] = useState("");
  const [apportDate, setApportDate] = useState(
    new Date().toISOString().slice(0, 10)
  );
  const [visible, setVisible] = useState(true);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    authedFetch("/api/v1/invest/admin/investisseurs")
      .then(async (res) => {
        if (res.ok) {
          setExisting(
            (await res.json()) as {
              user_id: number;
              name: string;
              email: string;
            }[]
          );
        }
      })
      .catch(() => undefined);
  }, []);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setErr(null);
    const pctNum = Number(pct.replace(",", "."));
    if (!pctNum || pctNum <= 0 || pctNum > 100) {
      setErr("Pourcentage de parts invalide (0–100).");
      return;
    }
    const body: Record<string, unknown> = {
      entreprise_id: entrepriseId,
      parts_pct: pctNum,
      is_visible: visible
    };
    if (mode === "existant") {
      if (!existingId) {
        setErr("Choisissez un investisseur.");
        return;
      }
      body.user_id = Number(existingId);
    } else {
      if (!firstName.trim() || !lastName.trim() || !email.trim()) {
        setErr("Prénom, nom et courriel requis.");
        return;
      }
      body.new_investor = {
        first_name: firstName.trim(),
        last_name: lastName.trim(),
        email: email.trim(),
        phone: phone.trim() || null
      };
    }
    const apportNum = Number(apport.replace(",", "."));
    if (apportNum > 0) {
      body.apport_initial = apportNum;
      body.apport_date = apportDate;
    }
    setBusy(true);
    try {
      const res = await authedFetch(
        "/api/v1/invest/admin/participations",
        { method: "POST", body: JSON.stringify(body) }
      );
      const payload = await res.json().catch(() => null);
      if (!res.ok) {
        setErr(
          typeof payload?.detail === "string"
            ? payload.detail
            : `Erreur HTTP ${res.status}`
        );
        return;
      }
      let banner: string | null = null;
      if (payload?.invitation_sent) {
        banner = `Invitation envoyée à ${payload.user_email}.`;
      } else if (payload?.temp_password) {
        banner =
          `Compte créé mais courriel non configuré — transmettez ce ` +
          `mot de passe temporaire : ${payload.temp_password}`;
      }
      await onAdded(banner);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
      onClick={() => !busy && onClose()}
    >
      <form
        onSubmit={submit}
        onClick={(e) => e.stopPropagation()}
        className="max-h-[85vh] w-full max-w-md space-y-3 overflow-y-auto rounded-2xl border border-brand-800 bg-brand-900 p-5"
      >
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold text-white">
            Ajouter un investisseur
          </h2>
          <button
            type="button"
            onClick={onClose}
            className="btn-ghost btn-xs"
            disabled={busy}
          >
            ✕
          </button>
        </div>

        <div className="flex gap-1">
          {(
            [
              ["nouveau", "Nouveau compte"],
              ["existant", "Investisseur existant"]
            ] as const
          ).map(([key, label]) => (
            <button
              key={key}
              type="button"
              onClick={() => setMode(key)}
              className={`rounded-lg px-3 py-1.5 text-xs font-medium ${
                mode === key
                  ? "bg-accent-500 text-brand-950"
                  : "text-white/60 hover:bg-white/5 hover:text-white"
              }`}
            >
              {label}
            </button>
          ))}
        </div>

        {mode === "existant" ? (
          <div>
            <label className="label">Investisseur</label>
            <select
              value={existingId}
              onChange={(e) => setExistingId(e.target.value)}
              className="input w-full text-xs"
            >
              <option value="">— Choisir —</option>
              {existing.map((u) => (
                <option key={u.user_id} value={String(u.user_id)}>
                  {u.name} ({u.email})
                </option>
              ))}
            </select>
          </div>
        ) : (
          <>
            <div className="grid grid-cols-2 gap-2">
              <div>
                <label className="label">Prénom</label>
                <input
                  value={firstName}
                  onChange={(e) => setFirstName(e.target.value)}
                  className="input w-full text-xs"
                />
              </div>
              <div>
                <label className="label">Nom</label>
                <input
                  value={lastName}
                  onChange={(e) => setLastName(e.target.value)}
                  className="input w-full text-xs"
                />
              </div>
            </div>
            <div>
              <label className="label">Courriel</label>
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="input w-full text-xs"
              />
              <p className="mt-1 text-[10px] text-white/35">
                Le compte (accès portail seulement) est créé avec un mot
                de passe aléatoire envoyé par courriel.
              </p>
            </div>
            <div>
              <label className="label">Téléphone (optionnel)</label>
              <input
                type="tel"
                value={phone}
                onChange={(e) => setPhone(e.target.value)}
                className="input w-full text-xs"
              />
            </div>
          </>
        )}

        <div className="grid grid-cols-2 gap-2">
          <div>
            <label className="label">Parts (%)</label>
            <input
              value={pct}
              onChange={(e) => setPct(e.target.value)}
              placeholder="ex. 50"
              inputMode="decimal"
              className="input w-full text-xs tabular-nums"
            />
          </div>
          <div>
            <label className="label">Apport initial ($, optionnel)</label>
            <input
              value={apport}
              onChange={(e) => setApport(e.target.value)}
              placeholder="ex. 250000"
              inputMode="decimal"
              className="input w-full text-xs tabular-nums"
            />
          </div>
        </div>
        {apport ? (
          <div>
            <label className="label">Date de l&apos;apport</label>
            <input
              type="date"
              value={apportDate}
              onChange={(e) => setApportDate(e.target.value)}
              className="input w-full text-xs"
            />
          </div>
        ) : null}
        <label className="flex items-center gap-2 text-xs text-white/70">
          <input
            type="checkbox"
            checked={visible}
            onChange={(e) => setVisible(e.target.checked)}
          />
          Visible immédiatement dans son portail
        </label>

        {err ? <p className="text-xs text-rose-400">{err}</p> : null}

        <div className="flex justify-end gap-2 pt-1">
          <button
            type="button"
            onClick={onClose}
            className="btn-secondary btn-sm"
            disabled={busy}
          >
            Annuler
          </button>
          <button
            type="submit"
            disabled={busy}
            className="btn-accent btn-sm inline-flex items-center gap-1.5"
          >
            {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
            Ajouter
          </button>
        </div>
      </form>
    </div>
  );
}

/* ──────────────── Modal sélection Drive ──────────────── */

function DrivePickerModal({
  entrepriseId,
  folderId,
  onClose,
  onShared
}: {
  entrepriseId: number;
  folderId: string;
  onClose: () => void;
  onShared: () => Promise<void>;
}) {
  const [files, setFiles] = useState<DriveFileT[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [checked, setChecked] = useState<Record<string, boolean>>({});
  const [busy, setBusy] = useState(false);
  const [stack, setStack] = useState<{ id: string; name: string }[]>([
    { id: folderId, name: "Dossier du projet" }
  ]);

  const current = stack[stack.length - 1];

  const loadFolder = useCallback(async (fid: string) => {
    setLoading(true);
    setErr(null);
    try {
      const res = await authedFetch(
        `/api/v1/drive/folders/${fid}/files?page_size=200`
      );
      if (!res.ok) {
        const body = await res.json().catch(() => null);
        throw new Error(
          typeof body?.detail === "string" ? body.detail : "erreur Drive"
        );
      }
      const data = (await res.json()) as { files: DriveFileT[] };
      setFiles(data.files || []);
    } catch (e) {
      setErr(
        e instanceof Error
          ? `Drive inaccessible : ${e.message}`
          : "Drive inaccessible — connectez votre compte Google dans Paramètres → Drive."
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadFolder(current.id);
  }, [current.id, loadFolder]);

  function mime(f: DriveFileT): string {
    return f.mime_type || f.mimeType || "";
  }

  async function share() {
    const ids = Object.keys(checked).filter((k) => checked[k]);
    if (ids.length === 0) return;
    setBusy(true);
    setErr(null);
    try {
      for (const fid of ids) {
        const f = files.find((x) => x.id === fid);
        const res = await authedFetch(
          `/api/v1/invest/admin/projets/${entrepriseId}/documents/from-drive`,
          {
            method: "POST",
            body: JSON.stringify({ file_id: fid, title: f?.name || null })
          }
        );
        if (!res.ok) {
          const body = await res.json().catch(() => null);
          setErr(
            `${f?.name || fid} : ` +
              (typeof body?.detail === "string"
                ? body.detail
                : `erreur HTTP ${res.status}`)
          );
          setBusy(false);
          return;
        }
      }
      await onShared();
    } finally {
      setBusy(false);
    }
  }

  const nbChecked = Object.values(checked).filter(Boolean).length;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
      onClick={() => !busy && onClose()}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="flex max-h-[85vh] w-full max-w-lg flex-col rounded-2xl border border-brand-800 bg-brand-900 p-5"
      >
        <div className="mb-2 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-white">
            Partager depuis le Drive
          </h2>
          <button
            type="button"
            onClick={onClose}
            className="btn-ghost btn-xs"
            disabled={busy}
          >
            ✕
          </button>
        </div>
        <p className="mb-2 text-[11px] text-white/40">
          Cochez les fichiers à partager — une copie est prise au moment
          du partage, les investisseurs ne touchent jamais au Drive.
        </p>

        {/* Fil d'Ariane des dossiers */}
        <div className="mb-2 flex flex-wrap items-center gap-1 text-xs">
          {stack.map((s, i) => (
            <span key={s.id} className="flex items-center gap-1">
              {i > 0 ? <span className="text-white/30">/</span> : null}
              <button
                type="button"
                onClick={() => setStack(stack.slice(0, i + 1))}
                className={
                  i === stack.length - 1
                    ? "font-medium text-white"
                    : "text-accent-500 hover:underline"
                }
              >
                {s.name}
              </button>
            </span>
          ))}
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto rounded-lg border border-brand-800">
          {loading ? (
            <div className="flex justify-center py-8">
              <Loader2 className="h-5 w-5 animate-spin text-accent-500" />
            </div>
          ) : err ? (
            <p className="p-4 text-xs text-rose-400">{err}</p>
          ) : files.length === 0 ? (
            <p className="p-4 text-center text-xs text-white/40">
              Dossier vide.
            </p>
          ) : (
            <ul>
              {files.map((f) => {
                const isFolder =
                  mime(f) === "application/vnd.google-apps.folder";
                return (
                  <li
                    key={f.id}
                    className="border-b border-brand-800/60 last:border-0"
                  >
                    {isFolder ? (
                      <button
                        type="button"
                        onClick={() =>
                          setStack([...stack, { id: f.id, name: f.name }])
                        }
                        className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm text-white hover:bg-white/5"
                      >
                        <FolderOpen className="h-4 w-4 shrink-0 text-accent-500" />
                        {f.name}
                      </button>
                    ) : (
                      <label className="flex cursor-pointer items-center gap-2 px-3 py-2 text-sm text-white hover:bg-white/5">
                        <input
                          type="checkbox"
                          checked={!!checked[f.id]}
                          onChange={(e) =>
                            setChecked((prev) => ({
                              ...prev,
                              [f.id]: e.target.checked
                            }))
                          }
                        />
                        <FileText className="h-4 w-4 shrink-0 text-white/40" />
                        <span className="min-w-0 truncate">{f.name}</span>
                      </label>
                    )}
                  </li>
                );
              })}
            </ul>
          )}
        </div>

        <div className="mt-3 flex items-center justify-between">
          <span className="text-xs text-white/50">
            {nbChecked} fichier{nbChecked > 1 ? "s" : ""} sélectionné
            {nbChecked > 1 ? "s" : ""}
          </span>
          <button
            type="button"
            onClick={() => void share()}
            disabled={busy || nbChecked === 0}
            className="btn-accent btn-sm inline-flex items-center gap-1.5"
          >
            {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
            Partager la sélection
          </button>
        </div>
      </div>
    </div>
  );
}
