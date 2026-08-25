"use client";

/* Console admin — fiche d'un projet (compagnie).

   Lecture seule sur les données financières : noms et % de parts
   viennent de la fiche entreprise (Parts & actionnaires), les apports/
   remboursements des avances d'actionnaires QuickBooks (bouton
   « Synchroniser QuickBooks »). La console gère : activation des
   comptes, visibilité par projet, publication (description, phase,
   transparence), jalons manuels et documents partagés (upload PDF ou
   fichiers COCHÉS depuis le Drive de la compagnie — copie au partage,
   jamais le Drive complet). */

import {
  Fragment,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState
} from "react";
import { useParams } from "next/navigation";
import { useRouter } from "@/i18n/navigation";
import {
  Eye,
  FileText,
  FolderOpen,
  Loader2,
  Paperclip,
  RefreshCw,
  Trash2,
  X
} from "lucide-react";

import { authedFetch } from "@/lib/auth";
import { useConfirm } from "@/components/confirm-dialog";
import { InvestisseurTopbar } from "../../../layout";
import {
  DepenseCategorie,
  fmtDate,
  fmtMoney,
  HypothequesCard,
  ImmeubleRow,
  NormalisesPanel,
  PhaseBadge,
  QboReelsPanel,
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
  parts_source: "fiche" | "manuel";
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

type QboSyncState = {
  at: string | null;
  statut?: string;
  projet_nom?: string;
  avances_total?: number;
  apparies?: {
    compte: string;
    solde: number;
    investisseur: string;
    nb_flux: number;
    participation_id: number;
  }[];
  sans_compte?: { compte: string; solde: number; partenaire: string }[];
  non_apparies?: string[];
} | null;

type AdminProjet = {
  entreprise_id: number;
  name: string;
  drive_folder_id: string | null;
  phase: string;
  qbo_sync: QboSyncState;
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

  const [driveOpen, setDriveOpen] = useState(false);
  const [uploadBusy, setUploadBusy] = useState(false);
  const [busyActiver, setBusyActiver] = useState<number | null>(null);
  const [busySync, setBusySync] = useState(false);
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

  async function syncQbo() {
    setBusySync(true);
    setBanner(null);
    try {
      const res = await authedFetch(
        `/api/v1/invest/admin/projets/${entrepriseId}/sync-qbo`,
        { method: "POST" }
      );
      const body = await res.json().catch(() => null);
      if (!res.ok || !body) {
        setBanner("Synchronisation QuickBooks échouée.");
        return;
      }
      if (body.statut === "aucun_projet") {
        setBanner(
          "Non applicable — cette compagnie n'a pas de projet dans la " +
            "section optimisation (gestion d'entreprise)."
        );
      } else if (body.statut === "sans_qbo") {
        setBanner(
          `Le projet « ${body.projet_nom} » n'a pas de connexion ` +
            "QuickBooks dans ses réglages."
        );
      } else if (body.statut === "erreur") {
        setBanner(`Lecture QuickBooks impossible : ${body.erreur || "?"}`);
      } else {
        const ap = (body.apparies || [])
          .map(
            (a: { investisseur: string; nb_flux: number }) =>
              `${a.investisseur} (${a.nb_flux} flux)`
          )
          .join(", ");
        const sansCompte = (body.sans_compte || [])
          .map(
            (s: {
              compte: string;
              solde: number;
              partenaire: string;
            }) =>
              `${Math.round(s.solde).toLocaleString("fr-CA")} $ dans « ${
                s.compte
              } » appartiennent à ${s.partenaire}, qui n'a pas encore ` +
              "de compte investisseur — ajoutez son courriel dans la " +
              "fiche entreprise, « Créer le compte & activer », puis " +
              "resynchronisez"
          )
          .join(" · ");
        const rest =
          (body.non_apparies || []).length > 0
            ? ` Comptes non appariés : ${body.non_apparies.join(", ")} — ` +
              "renommez le compte QBO ou l'actionnaire pour que les " +
              "noms se ressemblent."
            : "";
        setBanner(
          `Synchronisé depuis « ${body.projet_nom} » : avances totales ` +
            `${Math.round(body.avances_total).toLocaleString("fr-CA")} $` +
            (ap ? ` · flux mis à jour : ${ap}.` : ".") +
            (sansCompte ? ` ⚠ ${sansCompte}.` : "") +
            rest
        );
      }
      await load();
    } finally {
      setBusySync(false);
    }
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
          <NormalisesPanel
            serie={data.serie_mensuelle}
            revenusMode={data.revenus_mode}
            cashflowMoyen={data.cashflow_moyen}
            depensesParCategorie={data.depenses_par_categorie}
            showDepenses
            showCashflow
          />
          <QboReelsPanel
            fetchPath={`/api/v1/invest/admin/projets/${entrepriseId}/qbo-reels`}
          />
        </div>

        <h2 className="mb-3 mt-8 text-base font-semibold text-white">
          Gestion des investisseurs et de la publication
        </h2>
        <div className="grid grid-cols-1 gap-4 xl:grid-cols-[1.2fr_0.8fr]">
          {/* ── Colonne gauche : participations ── */}
          <div className="min-w-0 space-y-4">
            <div className="rounded-2xl border border-brand-800 bg-brand-900 p-4">
              <div className="mb-1 flex items-center justify-between gap-2">
                <h2 className="text-sm font-semibold text-white">
                  Actionnaires &amp; participations
                </h2>
                <button
                  type="button"
                  onClick={() => void syncQbo()}
                  disabled={busySync}
                  className="btn-outline-accent btn-xs inline-flex items-center gap-1"
                  title="Lit les comptes d'avances d'actionnaires du QuickBooks lié (section optimisation) : met à jour les avances totales (équité) et les apports/remboursements de chaque investisseur"
                >
                  {busySync ? (
                    <Loader2 className="h-3 w-3 animate-spin" />
                  ) : (
                    <RefreshCw className="h-3 w-3" />
                  )}
                  Synchroniser QuickBooks
                </button>
              </div>
              <p className="mb-2 text-[11px] text-white/35">
                Noms et % de parts : fiche entreprise (Parts &amp;
                actionnaires). Apports et remboursements : avances
                d&apos;actionnaires du QuickBooks lié. Rien ne se saisit
                ici — la console gère seulement la visibilité et les
                comptes.
              </p>

              {/* État persistant de la dernière sync QBO */}
              {data.qbo_sync ? (
                <div className="mb-3 rounded-xl border border-brand-800 bg-brand-950/40 px-3 py-2.5">
                  <p className="text-[10px] font-semibold uppercase tracking-wider text-white/40">
                    Synchronisation QuickBooks —{" "}
                    {data.qbo_sync.at
                      ? new Date(data.qbo_sync.at).toLocaleString(
                          "fr-CA",
                          {
                            day: "numeric",
                            month: "short",
                            hour: "2-digit",
                            minute: "2-digit"
                          }
                        )
                      : "—"}{" "}
                    · avances totales{" "}
                    {fmtMoney(data.qbo_sync.avances_total ?? 0)}
                  </p>
                  <ul className="mt-1.5 space-y-1 text-[11px]">
                    {(data.qbo_sync.apparies || []).map((a) => (
                      <li key={a.compte} className="text-white/60">
                        <span className="text-emerald-400">✓</span>{" "}
                        {a.compte} → <b>{a.investisseur}</b>{" "}
                        <span className="tabular-nums">
                          ({fmtMoney(a.solde)}
                          {a.nb_flux > 0
                            ? ` · ${a.nb_flux} mouvement${
                                a.nb_flux > 1 ? "s" : ""
                              } importés`
                            : " · aucun mouvement"}
                          )
                        </span>
                      </li>
                    ))}
                    {(data.qbo_sync.sans_compte || []).map((s) => (
                      <li key={s.compte} className="text-amber-400">
                        ⚠ {fmtMoney(s.solde)} dans « {s.compte} » —{" "}
                        {s.partenaire} n&apos;a pas encore de compte
                        investisseur : courriel dans la fiche entreprise
                        → « Créer le compte &amp; activer » →
                        resynchronisez.
                      </li>
                    ))}
                    {(data.qbo_sync.non_apparies || []).map((n) => (
                      <li key={n} className="text-rose-400">
                        ✕ « {n} » — aucun actionnaire au nom
                        correspondant (rapprochez les noms côté QBO ou
                        fiche entreprise).
                      </li>
                    ))}
                  </ul>
                </div>
              ) : (
                <p className="mb-3 rounded-xl border border-dashed border-brand-700 bg-brand-950/40 px-3 py-2 text-[11px] text-white/40">
                  Jamais synchronisé — cliquez « Synchroniser
                  QuickBooks » (la sync roule aussi automatiquement
                  chaque nuit).
                </p>
              )}

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
                    activation : « Synchroniser QuickBooks » pour ses
                    apports, puis « Visible dans son portail ».
                  </p>
                </div>
              ) : null}

              {data.participations.length === 0 ? (
                <p className="py-4 text-center text-sm text-white/50">
                  {data.partenaires.length > 0
                    ? "Aucune participation active — activez un actionnaire ci-dessus."
                    : "Aucun actionnaire dans la fiche entreprise (Parts & actionnaires) — ajoutez-les là (gestion d'entreprise), ils apparaîtront ici."}
                </p>
              ) : (
                <div className="space-y-3">
                  {data.participations.map((p) => (
                    <ParticipationCard
                      key={p.id}
                      p={p}
                      syncDone={!!data.qbo_sync}
                      syncApparie={
                        data.qbo_sync?.apparies?.find(
                          (a) => a.participation_id === p.id
                        ) || null
                      }
                      onChanged={load}
                      onRemove={() => void removeParticipation(p)}
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
              <h2 className="text-sm font-semibold text-white">
                Publication — ce que voit l&apos;investisseur
              </h2>
              <p className="mb-3 mt-1 text-[11px] text-white/35">
                Toute la fiche est calculée automatiquement (pôle
                locatif, gestion d&apos;entreprise, QuickBooks). Cette
                carte contrôle seulement l&apos;habillage et le niveau
                de transparence de ce que l&apos;investisseur voit.
              </p>

              <p className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-white/40">
                Mot de présentation
              </p>
              <textarea
                defaultValue={data.profil.description || ""}
                onBlur={(e) => {
                  const v = e.target.value.trim();
                  if (v !== (data.profil.description || "")) {
                    void patchProfil({ description: v });
                  }
                }}
                rows={3}
                placeholder="Affiché en tête de sa fiche projet — ex. : « Immeuble de 12 logements acquis en 2021, optimisé puis refinancé en 2023. »"
                className="input w-full text-xs"
              />

              <div className="mt-3">
                <p className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-white/40">
                  Phase affichée
                </p>
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
                <p className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-white/40">
                  Avances aux actionnaires ($)
                </p>
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
                  Équité = valeur − hypothèques − avances. Rempli
                  automatiquement par « Synchroniser QuickBooks » ;
                  modifiable à la main tant que la compagnie n&apos;a
                  pas de connexion QBO.
                </p>
              </div>

              <p className="mb-1 mt-4 text-[10px] font-semibold uppercase tracking-wider text-white/40">
                Transparence
              </p>
              <div className="space-y-2">
                {(
                  [
                    [
                      "show_depenses",
                      "Dépenses détaillées",
                      "graphique des dépenses, palmarès par catégorie et détail par compte QBO"
                    ],
                    [
                      "show_hypotheque",
                      "Détails d'hypothèque",
                      "section Hypothèques (créancier, soldes, taux, terme)"
                    ],
                    [
                      "show_actionnaires",
                      "Liste des actionnaires",
                      "co-actionnaires de SA compagnie seulement, jamais les autres projets"
                    ],
                    [
                      "show_cashflow",
                      "Cash-flow",
                      "cash-flow moyen + tableau des réels QuickBooks"
                    ]
                  ] as const
                ).map(([key, label, hint]) => (
                  <label
                    key={key}
                    className="flex items-start justify-between gap-2 text-xs text-white/70"
                  >
                    <span>
                      {label}
                      <span className="block text-[10px] text-white/35">
                        {hint}
                      </span>
                    </span>
                    <input
                      type="checkbox"
                      className="mt-0.5"
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
                            "ouvrez sa fiche dans gestion d'entreprise " +
                            "et liez son dossier dans la section " +
                            "« Documents Drive » (le même dossier sera " +
                            "utilisé ici), puis revenez cocher les " +
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

      {driveOpen && data.drive_folder_id ? (
        <DrivePickerModal
          entrepriseId={entrepriseId}
          folderId={data.drive_folder_id}
          sharedTitles={data.documents.map((d) => d.title)}
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

/* ─────────────────── Carte participation + flux ─────────────────── */

function ParticipationCard({
  p,
  syncDone,
  syncApparie,
  onChanged,
  onRemove,
  onVoirComme
}: {
  p: ParticipationRow;
  syncDone: boolean;
  syncApparie: {
    compte: string;
    solde: number;
    nb_flux: number;
  } | null;
  onChanged: () => Promise<void>;
  onRemove: () => void;
  onVoirComme: () => void;
}) {
  async function patch(body: Record<string, unknown>) {
    const res = await authedFetch(
      `/api/v1/invest/admin/participations/${p.id}`,
      { method: "PATCH", body: JSON.stringify(body) }
    );
    if (res.ok) await onChanged();
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
            Parts{" "}
            {p.parts_pct.toLocaleString("fr-CA", {
              maximumFractionDigits: 1
            })}{" "}
            %{" "}
            <span className="text-white/35">
              ({p.parts_source === "fiche"
                ? "fiche entreprise"
                : "saisi ici — ajoutez-le dans Parts & actionnaires"}
              )
            </span>{" "}
            · capital actuel {fmtMoney(p.capital_actuel)} · valeur des
            parts {fmtMoney(p.valeur_parts)}
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

      {/* Flux (lecture seule — alimentés par la synchronisation QBO) */}
      <div className="mt-3 border-t border-brand-800 pt-2">
        {p.flux.length > 0 ? (
          <ul className="space-y-1">
            {p.flux.map((f) => (
              <li
                key={f.id}
                className="flex items-center justify-between gap-2 text-xs"
              >
                <span className="text-white/70">
                  {fmtDate(f.date_flux)} —{" "}
                  {FLUX_LABELS[f.type] || f.type}
                  {f.source === "qbo" ? (
                    <span className="ml-1 rounded border border-sky-500/40 bg-sky-500/10 px-1 text-[9px] font-bold uppercase text-sky-400">
                      QBO
                    </span>
                  ) : null}
                  {f.note ? (
                    <span className="text-white/40"> · {f.note}</span>
                  ) : null}
                </span>
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
              </li>
            ))}
          </ul>
        ) : syncApparie ? (
          <p className="text-xs text-white/40">
            Compte d&apos;avances apparié : « {syncApparie.compte} » —
            solde {fmtMoney(syncApparie.solde)}, aucun mouvement à
            importer. Ses apports apparaîtront dès que des avances
            seront enregistrées dans QuickBooks.
          </p>
        ) : syncDone ? (
          <p className="text-xs text-amber-400">
            Aucun compte d&apos;avances QuickBooks ne correspond à son
            nom lors de la dernière synchronisation — vérifiez le nom
            du compte dans QBO (section optimisation → Avances des
            actionnaires).
          </p>
        ) : (
          <p className="text-xs text-white/40">
            Aucun apport trouvé — cliquez « Synchroniser QuickBooks »
            ci-dessus (la sync roule aussi chaque nuit).
          </p>
        )}
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

/* ──────────────── Modal sélection Drive ──────────────── */

function DrivePickerModal({
  entrepriseId,
  folderId,
  sharedTitles,
  onClose,
  onShared
}: {
  entrepriseId: number;
  folderId: string;
  sharedTitles: string[];
  onClose: () => void;
  onShared: () => Promise<void>;
}) {
  const [files, setFiles] = useState<DriveFileT[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [checked, setChecked] = useState<Record<string, boolean>>({});
  const [recherche, setRecherche] = useState("");
  const [busy, setBusy] = useState(false);
  const [stack, setStack] = useState<{ id: string; name: string }[]>([
    { id: folderId, name: "Dossier du projet" }
  ]);
  // id → nom de TOUS les fichiers vus (la sélection survit à la
  // navigation entre dossiers).
  const nomsRef = useRef<Record<string, string>>({});

  const current = stack[stack.length - 1];
  const dejaPartage = useMemo(() => {
    const set = new Set<string>();
    for (const t of sharedTitles) {
      set.add(t.toLowerCase().replace(/\.pdf$/i, "").trim());
    }
    return set;
  }, [sharedTitles]);

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
      for (const f of data.files || []) {
        nomsRef.current[f.id] = f.name;
      }
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

  const visibles = useMemo(() => {
    const q = recherche.trim().toLowerCase();
    if (!q) return files;
    return files.filter((f) => f.name.toLowerCase().includes(q));
  }, [files, recherche]);

  async function share() {
    const ids = Object.keys(checked).filter((k) => checked[k]);
    if (ids.length === 0) return;
    setBusy(true);
    setErr(null);
    try {
      for (const fid of ids) {
        const nom = nomsRef.current[fid];
        const res = await authedFetch(
          `/api/v1/invest/admin/projets/${entrepriseId}/documents/from-drive`,
          {
            method: "POST",
            body: JSON.stringify({ file_id: fid, title: nom || null })
          }
        );
        if (!res.ok) {
          const body = await res.json().catch(() => null);
          setErr(
            `${nom || fid} : ` +
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

        {/* Fil d'Ariane + recherche */}
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
        <input
          value={recherche}
          onChange={(e) => setRecherche(e.target.value)}
          placeholder="Rechercher dans ce dossier…"
          className="input mb-2 w-full text-xs"
        />

        <div className="min-h-0 flex-1 overflow-y-auto rounded-lg border border-brand-800">
          {loading ? (
            <div className="flex justify-center py-8">
              <Loader2 className="h-5 w-5 animate-spin text-accent-500" />
            </div>
          ) : err ? (
            <p className="p-4 text-xs text-rose-400">{err}</p>
          ) : visibles.length === 0 ? (
            <p className="p-4 text-center text-xs text-white/40">
              {recherche
                ? "Aucun fichier ne correspond à la recherche."
                : "Dossier vide."}
            </p>
          ) : (
            <ul>
              {visibles.map((f) => {
                const isFolder =
                  mime(f) === "application/vnd.google-apps.folder";
                const partage = dejaPartage.has(
                  f.name.toLowerCase().replace(/\.pdf$/i, "").trim()
                );
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
                      <label
                        className={`flex cursor-pointer items-center gap-2 px-3 py-2 text-sm hover:bg-white/5 ${
                          partage ? "text-white/40" : "text-white"
                        }`}
                      >
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
                        {partage ? (
                          <span className="ml-auto shrink-0 rounded-full border border-emerald-500/40 bg-emerald-500/10 px-1.5 py-0.5 text-[9px] font-bold text-emerald-400">
                            ✓ déjà partagé
                          </span>
                        ) : null}
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
