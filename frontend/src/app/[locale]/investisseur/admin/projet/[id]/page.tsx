"use client";

/* Console admin — fiche d'un projet (compagnie).

   - Participations : ajouter un investisseur (compte créé + invitation
     courriel au besoin), % de parts, visibilité, flux (apports,
     remboursements, distributions) → nourrit le TRI.
   - Publication : description, phase, interrupteurs de transparence.
   - Jalons manuels de la timeline.
   - Documents partagés : upload PDF ou fichiers COCHÉS depuis le Drive
     de la compagnie (copie au partage — jamais le Drive complet). */

import { useCallback, useEffect, useState } from "react";
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
  fmtDate,
  fmtMoney,
  fmtPct,
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
  };
  immeubles: {
    immeuble_id: number;
    name: string;
    address: string | null;
    nb_logements: number;
    nb_baux_actifs: number;
    loyers_mensuels: number;
    valeur: number | null;
    valeur_source: string | null;
    valeur_date: string | null;
    hypotheque_balance: number;
    hypotheque_preteur: string | null;
    hypotheque_taux_pct: number | null;
    hypotheque_fin_terme: string | null;
    equite: number;
    ownership_pct: number;
  }[];
  valeur_totale: number;
  hypotheque_totale: number;
  equite: number;
  loyers_mensuels: number;
  nb_logements: number;
  nb_baux_actifs: number;
  taux_occupation: number | null;
  serie_mensuelle: SerieMois[];
  hypotheque_mensuelle: number;
  cashflow_moyen: number;
  timeline: TimelineEvent[];
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

        <div className="mb-5 flex flex-wrap items-center gap-3">
          <h1 className="text-xl font-bold text-white">{data.name}</h1>
          <PhaseBadge phase={data.phase} />
        </div>

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
              valeur − hypothèques
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
              loyers {fmtMoney(data.loyers_mensuels)}/mois · cash-flow{" "}
              <span
                className={
                  data.cashflow_moyen >= 0
                    ? "text-emerald-400"
                    : "text-rose-400"
                }
              >
                {data.cashflow_moyen >= 0 ? "+" : ""}
                {fmtMoney(data.cashflow_moyen)}/mois
              </span>
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
                  <tr
                    key={im.immeuble_id}
                    className="border-t border-brand-800/60"
                  >
                    <td className="px-4 py-3">
                      <p className="font-medium text-white">
                        {im.address || im.name}
                      </p>
                      <p className="text-xs text-white/40">
                        {im.hypotheque_preteur
                          ? `${im.hypotheque_preteur}${
                              im.hypotheque_taux_pct !== null
                                ? ` · ${im.hypotheque_taux_pct.toLocaleString(
                                    "fr-CA",
                                    { maximumFractionDigits: 2 }
                                  )} %`
                                : ""
                            }`
                          : "aucune hypothèque active"}
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
              </tbody>
            </table>
          </div>
        </div>

        {/* Revenus / dépenses + timeline */}
        <div className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-[1.2fr_0.8fr]">
          <div className="rounded-2xl border border-brand-800 bg-brand-900 p-4 text-white">
            <div className="mb-1 flex flex-wrap items-baseline justify-between gap-2">
              <h2 className="text-sm font-semibold">
                Revenus et dépenses · 12 derniers mois
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
            <RevDepChart serie={data.serie_mensuelle} showDepenses />
            <div className="mt-1 flex gap-4 text-xs text-white/50">
              <span className="inline-flex items-center gap-1.5">
                <i className="inline-block h-2.5 w-2.5 rounded-sm bg-[#199e70]" />
                Revenus perçus
              </span>
              <span className="inline-flex items-center gap-1.5">
                <i className="inline-block h-2.5 w-2.5 rounded-sm bg-[#e66767]" />
                Dépenses
              </span>
            </div>
          </div>
          <div className="rounded-2xl border border-brand-800 bg-brand-900 p-5">
            <h2 className="mb-4 text-sm font-semibold text-white">
              Timeline du projet
            </h2>
            <Timeline events={data.timeline} />
          </div>
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
                  Participations
                </h2>
                <button
                  type="button"
                  onClick={() => setAddOpen(true)}
                  className="btn-accent btn-xs inline-flex items-center gap-1"
                >
                  <Plus className="h-3 w-3" />
                  Ajouter un investisseur
                </button>
              </div>

              {data.participations.length === 0 ? (
                <p className="py-4 text-center text-sm text-white/50">
                  Aucun investisseur sur ce projet. Ajoutez une
                  participation — le compte et l&apos;invitation courriel
                  se créent tout seuls au besoin.
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
                  {data.drive_folder_id ? (
                    <button
                      type="button"
                      onClick={() => setDriveOpen(true)}
                      className="btn-secondary btn-xs inline-flex items-center gap-1"
                    >
                      <FolderOpen className="h-3 w-3" />
                      Depuis le Drive
                    </button>
                  ) : null}
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
