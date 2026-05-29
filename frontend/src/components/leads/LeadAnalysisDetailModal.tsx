"use client";

import { useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  ArrowLeft,
  Ban,
  CheckCircle2,
  Download,
  FileDown,
  Flame,
  Info,
  Loader2,
  Sparkles,
  X
} from "lucide-react";

import { authedFetch, hasMinRole } from "@/lib/auth";
import {
  OffreInvestissementWizard,
  type OffreInvestissementWizardData
} from "@/components/leads/OffreInvestissementWizard";
import { useCurrentUser } from "@/hooks/use-current-user";
import { useConfirm } from "@/components/confirm-dialog";
import { AnalysisDefaultsModal } from "@/components/analysis-defaults-modal";
import { PillPicker } from "@/components/task-pills";

/**
 * Modal de fiche d'analyse détaillée d'un lead. Extrait de la page
 * `prospection/analyses-leads/page.tsx` (où il était défini in-place
 * sur ~550 lignes + ~2300 lignes de helpers) pour devenir réutilisable
 * depuis la page d'un Deal Pipeline.
 *
 * Le composant est entièrement autonome :
 *   - charge la fiche via `GET /lead-analyses/{id}` au mount,
 *   - cleanup propre via flag `cancelled` à l'unmount,
 *   - notifie le parent à chaque sauvegarde via `onAfterUpdate`.
 *
 * Props :
 *   - `analysisId`      : id de la fiche d'analyse à charger,
 *   - `open`            : controlled — ne render que si true,
 *   - `onClose`         : fermeture (click overlay, X, Escape implicite),
 *   - `onAfterUpdate?`  : appelé après chaque patch réussi (refresh
 *                        kanban / résumé Deal),
 *   - `onBackToDeal?`   : si fourni, affiche un bouton « Retour au
 *                        deal » dans le header (cas `?fromDeal` sur la
 *                        page kanban Analyses).
 */

// ─── Types ───────────────────────────────────────────────────────

type LeadStatus = "a_analyser" | "decision_en_attente" | "interessant" | "abandonne";

/** Phase A3 — entrée individuelle d'anomalie post-extraction. */
export type ValidationWarning = {
  field: string;
  severity: "error" | "warning" | "info";
  message: string;
  source_local?: number | string | null;
  source_gemini?: number | string | null;
  source_claude?: number | string | null;
};

type LeadDetail = {
  id: number;
  status: LeadStatus;
  position: number;
  address: string | null;
  city: string | null;
  postal_code: string | null;
  province: string | null;
  asking_price: number | null;
  nb_logements: number | null;
  annee_construction: number | null;
  best_refi_amount: number | null;
  best_refi_program: string | null;
  mdf_preteur_b: number | null;
  type_batiment: string | null;
  converted_to_lead_id: number | null;
  converted_to_deal_id: number | null;
  model_used: string | null;
  validation_severity: "error" | "warning" | "info" | null;
  validation_count: number;
  created_at: string;
  attachments_count: number;
  typology_json: string | null;
  revenus_bruts: number | null;
  taxes_municipales: number | null;
  taxes_scolaires: number | null;
  assurances: number | null;
  energie: number | null;
  depenses_autres: number | null;
  superficie_terrain: number | null;
  superficie_batiment: number | null;
  evaluation_municipale: number | null;
  description: string | null;
  courtier_nom: string | null;
  courtier_contact: string | null;
  nb_stationnements: number | null;
  source_urls: string | null;
  source_text: string | null;
  notes: string | null;
  // Inputs manuels analyse financière
  loyers_projetes_json: string | null;
  loyers_max_abordabilite_json: string | null;
  travaux_estimes: number | null;
  nb_logements_ajoutes: number | null;
  nb_thermopompes_ajoutees: number | null;
  ajout_wifi: boolean | null;
  reduction_energie_pct: number | null;
  taux_interet_refi_pct: number | null;
  tga_pct: number | null;
  taux_interet_achat_pct: number | null;
  duree_projet_annees: number | null;
  frais_developpement: number | null;
  frais_negociations: number | null;
  mdf_preteur_b_pct: number | null;
  taux_interet_preteur_b_projet_pct: number | null;
  frais_demarrage_overrides_json: string | null;
  frais_demarrage_financables_json: string | null;
  analysis_results_json: string | null;
  validation_warnings: ValidationWarning[] | null;
  attachments: Array<{
    id: number;
    filename: string;
    content_type: string;
    size_bytes: number;
  }>;
};

const COLUMNS: Array<{
  key: LeadStatus;
  label: string;
  dot: string;
  desc: string;
}> = [
  {
    key: "a_analyser",
    label: "À analyser",
    dot: "bg-violet-400",
    desc: "Fraîchement capturés"
  },
  {
    key: "decision_en_attente",
    label: "Décision en attente",
    dot: "bg-amber-400",
    desc: "Analyse complétée, à classer"
  },
  {
    key: "interessant",
    label: "Intéressant",
    dot: "bg-emerald-400",
    desc: "À pousser plus loin"
  },
  {
    key: "abandonne",
    label: "Abandonné / Rejeté",
    dot: "bg-rose-400",
    desc: "Hors critères"
  }
];

const TYPOLOGY_KEYS = ["1.5", "2.5", "3.5", "4.5", "5.5", "6.5", "7.5", "8.5"];

function fmtMoney(n: number | null): string {
  if (n == null) return "—";
  const rounded = Math.round(n);
  const sign = rounded < 0 ? "-" : "";
  const abs = Math.abs(rounded).toString();
  const withSep = abs.replace(/\B(?=(\d{3})+(?!\d))/g, " ");
  return `${sign}${withSep} $`;
}

// ─── Composant principal ──────────────────────────────────────────

export function LeadAnalysisDetailModal({
  analysisId,
  open,
  onClose,
  onAfterUpdate,
  onBackToDeal
}: {
  analysisId: number;
  open: boolean;
  onClose: () => void;
  onAfterUpdate?: () => void;
  /** Si défini, affiche un bouton « Retour au deal » dans le header
   *  du modal — utilisé par la page kanban Analyses quand le modal est
   *  ouvert via ?openId={id}&fromDeal={dealId}. */
  onBackToDeal?: () => void;
}) {
  const [data, setData] = useState<LeadDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    const ctrl = new AbortController();
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const r = await authedFetch(`/api/v1/lead-analyses/${analysisId}`, {
          signal: ctrl.signal
        });
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const j = (await r.json()) as LeadDetail;
        if (!cancelled) setData(j);
      } catch (e) {
        if (!cancelled && (e as Error).name !== "AbortError") {
          setError((e as Error).message);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    void load();
    return () => {
      cancelled = true;
      ctrl.abort();
    };
  }, [analysisId, open]);

  async function patchField(field: string, value: unknown) {
    if (!data) return;
    setData({ ...data, [field]: value } as LeadDetail);
    try {
      await authedFetch(`/api/v1/lead-analyses/${analysisId}`, {
        method: "PATCH",
        body: JSON.stringify({ [field]: value })
      });
      onAfterUpdate?.();
    } catch {
      /* silent — local state retained */
    }
  }

  // ── Estimation IA des dépenses manquantes ─────────────────────
  const [estimatingExpenses, setEstimatingExpenses] = useState(false);
  const [estimateMsg, setEstimateMsg] = useState<{
    text: string;
    kind: "ok" | "warn" | "err";
  } | null>(null);
  async function estimateExpenses() {
    if (!data) return;
    setEstimatingExpenses(true);
    setEstimateMsg(null);
    try {
      const r = await authedFetch(
        `/api/v1/lead-analyses/${analysisId}/estimate-expenses`,
        { method: "POST" }
      );
      if (!r.ok) {
        setEstimateMsg({
          text: `Estimation échouée (HTTP ${r.status})`,
          kind: "err"
        });
        return;
      }
      const out = (await r.json()) as {
        taxes_municipales: number | null;
        taxes_scolaires: number | null;
        assurances: number | null;
        source?: string;
        note?: string;
      };
      const patch: Record<string, number> = {};
      if (data.taxes_municipales == null && out.taxes_municipales != null) {
        patch.taxes_municipales = out.taxes_municipales;
      }
      if (data.taxes_scolaires == null && out.taxes_scolaires != null) {
        patch.taxes_scolaires = out.taxes_scolaires;
      }
      if (data.assurances == null && out.assurances != null) {
        patch.assurances = out.assurances;
      }
      if (Object.keys(patch).length > 0) {
        setData({ ...data, ...patch } as LeadDetail);
        await authedFetch(`/api/v1/lead-analyses/${analysisId}`, {
          method: "PATCH",
          body: JSON.stringify(patch)
        });
        onAfterUpdate?.();
        const labels = Object.keys(patch)
          .map((k) =>
            k === "taxes_municipales"
              ? "taxes muni"
              : k === "taxes_scolaires"
              ? "taxes scol"
              : "assurances"
          )
          .join(", ");
        setEstimateMsg({
          text: `${labels} estimé${
            Object.keys(patch).length > 1 ? "s" : ""
          } via ${out.source || "IA"}.`,
          kind: "ok"
        });
      } else {
        const reason =
          out.note ||
          "L'IA n'a pas pu estimer — vérifie que le prix demandé et le nombre de logements sont renseignés.";
        setEstimateMsg({ text: reason, kind: "warn" });
      }
    } catch (e) {
      setEstimateMsg({
        text: `Estimation échouée : ${(e as Error).message}`,
        kind: "err"
      });
    } finally {
      setEstimatingExpenses(false);
    }
  }

  const typology = useMemo(() => {
    if (!data?.typology_json) return null;
    try {
      return JSON.parse(data.typology_json) as Record<string, number>;
    } catch {
      return null;
    }
  }, [data?.typology_json]);

  // ── Export PDF de la fiche d'analyse ──────────────────────────
  // Pattern `openAuthedPdf` repris de `nda-section.tsx` (PR #526) :
  // le browser ne joint pas le header `Authorization` sur une nav
  // top-level, donc on fetch en blob puis on ouvre une URL blob.
  const [pdfBusy, setPdfBusy] = useState(false);
  const [pdfToast, setPdfToast] = useState<{
    text: string;
    kind: "ok" | "err";
  } | null>(null);

  // ── Offre d'investissement .pptx (MVP) ────────────────────────────
  const [offreWizardOpen, setOffreWizardOpen] = useState(false);
  const offreWizardData = useMemo<OffreInvestissementWizardData>(() => {
    const fmt = (n: number | null | undefined) =>
      n == null ? "—" : fmtMoney(n);
    const fmtPct = (n: number | null | undefined) =>
      n == null ? "—" : `${n}%`;
    const autoFilled: Array<{ label: string; value: string }> = [
      { label: "Adresse", value: data?.address || "—" },
      { label: "Ville", value: data?.city || "—" },
      { label: "Prix demandé", value: fmt(data?.asking_price ?? null) },
      { label: "Revenus bruts", value: fmt(data?.revenus_bruts ?? null) },
      {
        label: "Nb logements",
        value: data?.nb_logements ? String(data.nb_logements) : "—"
      },
      {
        label: "Année construction",
        value: data?.annee_construction
          ? String(data.annee_construction)
          : "—"
      },
      {
        label: "Évaluation municipale",
        value: fmt(data?.evaluation_municipale ?? null)
      },
      {
        label: "Taxes municipales",
        value: fmt(data?.taxes_municipales ?? null)
      },
      { label: "Énergie", value: fmt(data?.energie ?? null) },
      { label: "Assurances", value: fmt(data?.assurances ?? null) },
      {
        label: "Best refi (montant)",
        value: fmt(data?.best_refi_amount ?? null)
      },
      {
        label: "Best refi (programme)",
        value: data?.best_refi_program || "—"
      },
      { label: "MDF prêteur B", value: fmt(data?.mdf_preteur_b ?? null) },
      {
        label: "Taux refi",
        value: fmtPct(data?.taux_interet_refi_pct ?? null)
      }
    ];
    const askingPrice = data?.asking_price ?? 0;
    const evalMuni = data?.evaluation_municipale ?? 0;
    let bulletSub = "Acquisition à fort potentiel d'optimisation";
    if (askingPrice && evalMuni && askingPrice < evalMuni) {
      const pct = Math.round((1 - askingPrice / evalMuni) * 100);
      bulletSub = `Offre d'achat acceptée ${pct}% sous la valeur municipale`;
    }
    return {
      autoFilled,
      bulletSuggestions: {
        b1: bulletSub,
        b2: "Loyers moyens actuels sous le marché",
        b3: "Potentiel d'augmentation via optimisation",
        b4: `Demande forte | Secteur ${data?.city || "Montréal"}`
      },
      quartier: data?.city || "Montréal",
      existingPhotos: (data?.attachments || []).filter((a) =>
        a.content_type.startsWith("image/")
      )
    };
  }, [data]);

  useEffect(() => {
    if (!pdfToast || pdfToast.kind === "err") return;
    const t = setTimeout(() => setPdfToast(null), 4000);
    return () => clearTimeout(t);
  }, [pdfToast]);

  async function downloadPdf() {
    if (pdfBusy) return;
    setPdfBusy(true);
    setPdfToast(null);
    try {
      const r = await authedFetch(
        `/api/v1/lead-analyses/${analysisId}/pdf`
      );
      if (!r.ok) {
        const detail = await r
          .json()
          .then((j: { detail?: string }) => j.detail || `HTTP ${r.status}`)
          .catch(() => `HTTP ${r.status}`);
        setPdfToast({
          text: `Génération PDF échouée : ${detail}`,
          kind: "err"
        });
        return;
      }
      const blob = await r.blob();
      const url = URL.createObjectURL(blob);
      window.open(url, "_blank");
      window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
      setPdfToast({ text: "PDF généré.", kind: "ok" });
    } catch (e) {
      setPdfToast({
        text: `Génération PDF échouée : ${(e as Error).message}`,
        kind: "err"
      });
    } finally {
      setPdfBusy(false);
    }
  }

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-end justify-center bg-black/70 px-2 py-4 sm:items-center"
      onClick={onClose}
    >
      <div
        className="flex max-h-[calc(100vh-2rem)] w-full max-w-3xl flex-col overflow-hidden rounded-2xl border border-brand-800 bg-brand-950"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="flex flex-shrink-0 items-start justify-between gap-3 border-b border-brand-800 px-5 py-4">
          <div className="min-w-0 flex-1">
            <p className="text-[10px] uppercase tracking-wider text-accent-500">
              Fiche d&apos;analyse
            </p>
            <h2 className="mt-0.5 truncate text-base font-bold text-white">
              {data?.address || `Lead #${analysisId}`}
            </h2>
            {data ? <ExtractionBadgeInline modelUsed={data.model_used} /> : null}
          </div>
          <div className="flex flex-shrink-0 items-center gap-1">
            {onBackToDeal ? (
              <button
                type="button"
                onClick={onBackToDeal}
                className="inline-flex items-center gap-1 rounded-md border border-emerald-500/30 bg-emerald-500/10 px-2 py-1 text-[11px] text-emerald-300 hover:bg-emerald-500/20"
                title="Revenir à la page du deal"
              >
                <ArrowLeft className="h-3 w-3" />
                Retour au deal
              </button>
            ) : null}
            <button
              type="button"
              onClick={() => setOffreWizardOpen(true)}
              disabled={!data}
              title="Générer un .pptx d'offre d'investissement"
              className="inline-flex items-center gap-1 rounded-md border border-emerald-500/40 bg-emerald-500/15 px-2 py-1 text-[11px] font-medium text-emerald-300 transition hover:bg-emerald-500/25 disabled:cursor-not-allowed disabled:opacity-50"
            >
              <FileDown className="h-3 w-3" />
              Offre .pptx
            </button>
            <button
              type="button"
              onClick={() => void downloadPdf()}
              disabled={pdfBusy || !data}
              title="Télécharger la fiche complète en PDF"
              className="inline-flex items-center gap-1 rounded-md border border-blue-500/30 bg-blue-500/10 px-2 py-1 text-[11px] font-medium text-blue-300 transition hover:bg-blue-500/20 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {pdfBusy ? (
                <Loader2 className="h-3 w-3 animate-spin" />
              ) : (
                <Download className="h-3 w-3" />
              )}
              {pdfBusy ? "Génération…" : "PDF"}
            </button>
            <button
              type="button"
              onClick={onClose}
              className="rounded-md p-1 text-white/60 hover:bg-brand-900 hover:text-white"
              aria-label="Fermer"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        </header>
        {pdfToast ? (
          <div
            className={`flex items-start gap-2 border-b border-brand-800 px-5 py-2 text-[11px] ${
              pdfToast.kind === "ok"
                ? "bg-emerald-500/10 text-emerald-300"
                : "bg-rose-500/10 text-rose-300"
            }`}
          >
            {pdfToast.kind === "ok" ? (
              <CheckCircle2 className="h-3 w-3 flex-shrink-0" />
            ) : (
              <AlertTriangle className="h-3 w-3 flex-shrink-0" />
            )}
            <p className="flex-1">{pdfToast.text}</p>
            {pdfToast.kind === "err" ? (
              <button
                type="button"
                onClick={() => setPdfToast(null)}
                className="ml-1 shrink-0 text-rose-300 hover:text-rose-100"
                aria-label="Fermer le message"
              >
                ✕
              </button>
            ) : null}
          </div>
        ) : null}

        <div className="flex-1 overflow-y-auto px-5 py-4">
          {loading ? (
            <p className="py-12 text-center text-sm text-white/40">
              <Loader2 className="mr-2 inline h-4 w-4 animate-spin" />
              Chargement…
            </p>
          ) : error ? (
            <p className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
              {error}
            </p>
          ) : !data ? null : (
            <div className="space-y-5">
              <section className="rounded-xl border border-brand-800 bg-brand-900 p-4">
                <h3 className="text-[10px] font-semibold uppercase tracking-wider text-accent-500">
                  Statut du lead
                </h3>
                <p className="mt-1 text-[10px] text-white/50">
                  Change la colonne du kanban depuis ici aussi.
                </p>
                <div className="mt-2">
                  <PillPicker
                    options={COLUMNS.map((c) => ({
                      value: c.key,
                      label: c.label,
                      dot: c.dot,
                      cls: c.dot
                    }))}
                    value={data.status}
                    onChange={(v) => patchField("status", v)}
                    ariaLabel="Statut du lead"
                  />
                </div>
              </section>

              <section>
                <h3 className="text-[10px] font-semibold uppercase tracking-wider text-accent-500">
                  Infos extraites
                </h3>
                <p className="mt-0.5 text-[11px] text-white/40">
                  Champs pré-remplis par l&apos;IA — clique pour corriger.
                  Les champs vides sont à compléter manuellement.
                </p>
                <div className="mt-3 grid gap-3 sm:grid-cols-2">
                  <FieldText
                    label="Adresse"
                    value={data.address}
                    onSave={(v) => patchField("address", v)}
                    required
                  />
                  <FieldText
                    label="Ville"
                    value={data.city}
                    onSave={(v) => patchField("city", v)}
                    required
                  />
                  <FieldText
                    label="Code postal"
                    value={data.postal_code}
                    onSave={(v) => patchField("postal_code", v)}
                  />
                  <FieldText
                    label="Type bâtiment"
                    value={data.type_batiment}
                    onSave={(v) => patchField("type_batiment", v)}
                  />
                  <FieldNumber
                    label="Prix demandé ($)"
                    name="asking_price"
                    value={data.asking_price}
                    onSave={(v) => patchField("asking_price", v)}
                    required
                    format="money"
                  />
                  <FieldNumber
                    label="Année construction"
                    value={data.annee_construction}
                    onSave={(v) => patchField("annee_construction", v)}
                  />
                  <FieldNumber
                    label="Nb logements"
                    name="nb_logements"
                    value={data.nb_logements}
                    onSave={(v) => patchField("nb_logements", v)}
                    required
                  />
                  <FieldNumber
                    label="Nb stationnements"
                    value={data.nb_stationnements}
                    onSave={(v) => patchField("nb_stationnements", v)}
                  />
                  <FieldNumber
                    label="Revenus bruts ($/an)"
                    name="revenus_bruts"
                    value={data.revenus_bruts}
                    onSave={(v) => patchField("revenus_bruts", v)}
                    required
                    format="money"
                  />
                  <FieldNumber
                    label="Évaluation municipale ($)"
                    value={data.evaluation_municipale}
                    onSave={(v) => patchField("evaluation_municipale", v)}
                    format="money"
                  />
                  <FieldNumber
                    label="Taxes municipales ($/an)"
                    name="taxes_municipales"
                    value={data.taxes_municipales}
                    onSave={(v) => patchField("taxes_municipales", v)}
                    required
                    onEstimate={() => void estimateExpenses()}
                    estimating={estimatingExpenses}
                    format="money"
                  />
                  <FieldNumber
                    label="Taxes scolaires ($/an)"
                    name="taxes_scolaires"
                    value={data.taxes_scolaires}
                    onSave={(v) => patchField("taxes_scolaires", v)}
                    required
                    onEstimate={() => void estimateExpenses()}
                    estimating={estimatingExpenses}
                    format="money"
                  />
                  <FieldNumber
                    label="Assurances ($/an)"
                    name="assurances"
                    value={data.assurances}
                    onSave={(v) => patchField("assurances", v)}
                    required
                    onEstimate={() => void estimateExpenses()}
                    estimating={estimatingExpenses}
                    format="money"
                  />
                  <FieldNumber
                    label="Énergie ($/an)"
                    name="energie"
                    value={data.energie}
                    onSave={(v) => patchField("energie", v)}
                    format="money"
                  />
                  <FieldNumber
                    label="Superficie terrain"
                    value={data.superficie_terrain}
                    onSave={(v) => patchField("superficie_terrain", v)}
                  />
                  <FieldNumber
                    label="Superficie bâtiment"
                    value={data.superficie_batiment}
                    onSave={(v) => patchField("superficie_batiment", v)}
                  />
                  <FieldText
                    label="Courtier (nom)"
                    value={data.courtier_nom}
                    onSave={(v) => patchField("courtier_nom", v)}
                  />
                  <FieldText
                    label="Courtier (contact)"
                    value={data.courtier_contact}
                    onSave={(v) => patchField("courtier_contact", v)}
                  />
                </div>

                {estimateMsg ? (
                  <p
                    className={`mt-2 rounded-lg border px-3 py-2 text-[11px] ${
                      estimateMsg.kind === "ok"
                        ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-300"
                        : estimateMsg.kind === "warn"
                        ? "border-amber-500/50 bg-amber-500/10 text-amber-200"
                        : "border-rose-500/40 bg-rose-500/10 text-rose-300"
                    }`}
                  >
                    {estimateMsg.text}
                  </p>
                ) : null}

                <div className="mt-3">
                  <p className="text-[11px] font-semibold uppercase tracking-wider text-white/50">
                    Typologie des logements
                  </p>
                  <p className="mt-0.5 text-[10px] text-white/40">
                    Quantité par typologie — modifiable si Claude n&apos;a
                    pas trouvé ou si tu veux corriger.
                  </p>
                  <TypologyEditor
                    value={typology || {}}
                    onSave={(j) =>
                      patchField("typology_json", JSON.stringify(j))
                    }
                  />
                </div>

                <div className="mt-3">
                  <p className="text-[11px] font-semibold uppercase tracking-wider text-white/50">
                    Description
                  </p>
                  <textarea
                    rows={3}
                    value={data.description || ""}
                    onChange={(e) =>
                      setData({ ...data, description: e.target.value })
                    }
                    onBlur={(e) => patchField("description", e.target.value)}
                    placeholder="Description / notes du courtier"
                    className="input mt-1 text-xs"
                  />
                </div>
              </section>

              {/* Sources originales */}
              {data.source_urls || data.source_text || data.attachments?.length ? (
                <section>
                  <div className="flex items-center justify-between gap-2">
                    <h3 className="text-[10px] font-semibold uppercase tracking-wider text-accent-500">
                      Sources originales
                    </h3>
                    <ReExtractButtons
                      id={analysisId}
                      hasSources={
                        !!(
                          data.source_urls ||
                          data.source_text ||
                          (data.attachments && data.attachments.length > 0)
                        )
                      }
                      onSuccess={async () => {
                        const r = await authedFetch(
                          `/api/v1/lead-analyses/${analysisId}`
                        );
                        if (r.ok) setData((await r.json()) as LeadDetail);
                        onAfterUpdate?.();
                      }}
                    />
                  </div>
                  {data.source_urls ? (
                    <div className="mt-2 space-y-1">
                      {data.source_urls
                        .split("\n")
                        .filter((u) => u.trim())
                        .map((u, i) => (
                          <a
                            key={i}
                            href={u}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="block truncate text-xs text-violet-300 hover:underline"
                          >
                            🔗 {u}
                          </a>
                        ))}
                    </div>
                  ) : null}
                  {data.attachments?.length ? (
                    <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-4">
                      {data.attachments.map((a) => (
                        <AttachmentThumb
                          key={a.id}
                          leadId={analysisId}
                          attachment={a}
                        />
                      ))}
                    </div>
                  ) : null}
                  {data.source_text ? (
                    <details className="mt-2">
                      <summary className="cursor-pointer text-[11px] text-white/50">
                        Texte original collé
                      </summary>
                      <pre className="mt-1 whitespace-pre-wrap rounded-md border border-brand-800 bg-brand-950 p-2 text-[11px] text-white/70">
                        {data.source_text}
                      </pre>
                    </details>
                  ) : null}
                </section>
              ) : null}

              {/* Phase A3 — Panneau "Validation de l'extraction" */}
              <ValidationPanel warnings={data.validation_warnings} />

              {/* Section Analyse financière — inputs manuels + bouton */}
              <ManualAnalysisSection
                data={data}
                onPatch={patchField}
                onRefresh={async () => {
                  const r = await authedFetch(
                    `/api/v1/lead-analyses/${analysisId}`
                  );
                  if (r.ok) setData((await r.json()) as LeadDetail);
                  onAfterUpdate?.();
                }}
              />

              {/* Résultats si analyse exécutée */}
              {data.analysis_results_json ? (
                <AnalysisResultsTable
                  resultsJson={data.analysis_results_json}
                  overridesJson={data.frais_demarrage_overrides_json}
                  financablesJson={data.frais_demarrage_financables_json}
                  mdfPct={data.mdf_preteur_b_pct ?? 25}
                  prixAchat={data.asking_price ?? 0}
                  fraisDemarrageTotalDb={null}
                  mdfPreteurBDb={data.mdf_preteur_b ?? null}
                  onPatchOverrides={(j) =>
                    patchField("frais_demarrage_overrides_json", j)
                  }
                  onPatchFinancables={(j) =>
                    patchField("frais_demarrage_financables_json", j)
                  }
                />
              ) : null}

              {/* Détail granulaire des calculs (style Excel) */}
              {data.analysis_results_json ? (
                <CalculationDetailsSection
                  resultsJson={data.analysis_results_json}
                  overridesJson={data.frais_demarrage_overrides_json}
                  lead={data}
                />
              ) : null}

              {/* Notes internes */}
              <section>
                <h3 className="text-[10px] font-semibold uppercase tracking-wider text-accent-500">
                  Notes internes
                </h3>
                <textarea
                  rows={3}
                  value={data.notes || ""}
                  onChange={(e) =>
                    setData({ ...data, notes: e.target.value })
                  }
                  onBlur={(e) => patchField("notes", e.target.value)}
                  placeholder="Tes notes privées sur ce lead"
                  className="input mt-2 text-xs"
                />
              </section>

            </div>
          )}
        </div>
      </div>
      <OffreInvestissementWizard
        open={offreWizardOpen}
        onClose={() => setOffreWizardOpen(false)}
        analysisId={analysisId}
        data={offreWizardData}
      />
    </div>
  );
}

// ─── Bouton ⚙️ défauts — visible admin/owner uniquement ──────────

function DefaultsGearButton({
  group,
  title
}: {
  group: "inputs_manuels" | "mdf_frais";
  title: string;
}) {
  const { user } = useCurrentUser();
  const [open, setOpen] = useState(false);
  if (!hasMinRole(user, "admin")) return null;
  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        title={title}
        aria-label="Modifier les défauts"
        className="inline-flex items-center gap-1 rounded-md border border-white/10 bg-white/[0.03] px-2 py-1 text-[10px] text-white/60 hover:bg-white/10 hover:text-white"
      >
        <span className="inline-block h-3 w-3">⚙</span>
        Défauts
      </button>
      <AnalysisDefaultsModal
        open={open}
        onClose={() => setOpen(false)}
        group={group}
      />
    </>
  );
}

// ─── Vignette d'attachment : fetch via authedFetch puis blob URL ───

function AttachmentThumb({
  leadId,
  attachment
}: {
  leadId: number;
  attachment: {
    id: number;
    filename: string;
    content_type: string;
    size_bytes: number;
  };
}) {
  const [blobUrl, setBlobUrl] = useState<string | null>(null);
  const [err, setErr] = useState(false);
  const isImage = (attachment.content_type || "").startsWith("image/");
  const isPdf = (attachment.content_type || "").includes("pdf");

  useEffect(() => {
    let cancelled = false;
    let cleanupUrl: string | null = null;
    (async () => {
      try {
        const r = await authedFetch(
          `/api/v1/lead-analyses/${leadId}/attachments/${attachment.id}`
        );
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const blob = await r.blob();
        if (cancelled) return;
        const url = URL.createObjectURL(blob);
        cleanupUrl = url;
        setBlobUrl(url);
      } catch {
        if (!cancelled) setErr(true);
      }
    })();
    return () => {
      cancelled = true;
      if (cleanupUrl) URL.revokeObjectURL(cleanupUrl);
    };
  }, [leadId, attachment.id]);

  return (
    <a
      href={blobUrl || "#"}
      target="_blank"
      rel="noopener noreferrer"
      onClick={(e) => {
        if (!blobUrl) e.preventDefault();
      }}
      className="block overflow-hidden rounded-md border border-brand-800 bg-brand-950 hover:border-accent-500"
      title={attachment.filename}
    >
      {isImage && blobUrl ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={blobUrl}
          alt={attachment.filename}
          className="h-24 w-full object-cover"
        />
      ) : isImage && !blobUrl && !err ? (
        <div className="flex h-24 items-center justify-center text-white/30">
          <Loader2 className="h-4 w-4 animate-spin" />
        </div>
      ) : err ? (
        <div className="flex h-24 items-center justify-center text-2xl text-rose-300/60">
          ✗
        </div>
      ) : isPdf ? (
        <div className="flex h-24 items-center justify-center text-3xl text-white/30">
          📕
        </div>
      ) : (
        <div className="flex h-24 items-center justify-center text-3xl text-white/30">
          📄
        </div>
      )}
      <p className="truncate px-2 py-1 text-[10px] text-white/60">
        {attachment.filename}
      </p>
    </a>
  );
}

// ─── Champs éditables ────────────────────────────────────────────

const CHAMPS_NECESSAIRES_CALC: ReadonlySet<string> = new Set([
  "asking_price",
  "nb_logements",
  "revenus_bruts",
  "taxes_municipales",
  "taxes_scolaires",
  "assurances",
  "energie",
  "typology_json"
]);

function FieldText({
  label,
  value,
  onSave,
  required,
  name
}: {
  label: string;
  value: string | null;
  onSave: (v: string | null) => void;
  required?: boolean;
  name?: string;
}) {
  const [v, setV] = useState(value || "");
  useEffect(() => setV(value || ""), [value]);
  const isEmpty = !value;
  const missingRequired = isEmpty && required;
  const necessaryForCalc =
    isEmpty && !missingRequired && !!name && CHAMPS_NECESSAIRES_CALC.has(name);
  return (
    <div>
      <label
        className={`text-[10px] uppercase tracking-wider ${
          missingRequired
            ? "text-rose-400 font-semibold"
            : necessaryForCalc
            ? "text-amber-600 dark:text-amber-300/80"
            : "text-white/50"
        }`}
      >
        {label}
        {missingRequired ? " · OBLIGATOIRE" : ""}
      </label>
      <input
        type="text"
        value={v}
        onChange={(e) => setV(e.target.value)}
        onBlur={() => {
          if ((value || "") !== v) onSave(v.trim() || null);
        }}
        className={`input mt-1 text-xs ${
          missingRequired
            ? "border-rose-400/70 focus:border-rose-400 ring-1 ring-rose-400/30"
            : ""
        }`}
      />
    </div>
  );
}

function _formatMoneyExcel(n: number): string {
  const sign = n < 0 ? "-" : "";
  const rounded = Math.round(Math.abs(n));
  const withSep = rounded
    .toString()
    .replace(/\B(?=(\d{3})+(?!\d))/g, " ");
  return `${sign}${withSep} $`;
}

function _formatPercentExcel(n: number): string {
  return `${n.toFixed(2)} %`;
}

function _parseNumberLiberal(s: string): number | null {
  if (s == null) return null;
  const cleaned = s
    .replace(/[\s ]/g, "")
    .replace(/\$/g, "")
    .replace(/%/g, "")
    .replace(/,/g, ".");
  if (cleaned === "" || cleaned === "-" || cleaned === ".") return null;
  const n = Number(cleaned);
  return Number.isFinite(n) ? n : null;
}

function FieldNumber({
  label,
  value,
  onSave,
  required,
  onEstimate,
  estimating,
  format = "plain",
  name
}: {
  label: string;
  value: number | null;
  onSave: (v: number | null) => void;
  required?: boolean;
  onEstimate?: () => void;
  estimating?: boolean;
  format?: "money" | "percent" | "plain";
  name?: string;
}) {
  const [focused, setFocused] = useState(false);
  const [v, setV] = useState(value != null ? String(value) : "");
  useEffect(() => {
    if (!focused) setV(value != null ? String(value) : "");
  }, [value, focused]);
  const isEmpty = value == null;
  const missingRequired = isEmpty && required;
  const necessaryForCalc =
    isEmpty && !missingRequired && !!name && CHAMPS_NECESSAIRES_CALC.has(name);

  const displayed = (() => {
    if (focused) return v;
    if (value == null) return "";
    if (format === "money") return _formatMoneyExcel(value);
    if (format === "percent") return _formatPercentExcel(value);
    return String(value);
  })();

  return (
    <div>
      <div className="flex items-baseline justify-between gap-2">
        <label
          className={`text-[10px] uppercase tracking-wider ${
            missingRequired
              ? "text-rose-400 font-semibold"
              : necessaryForCalc
              ? "text-amber-600 dark:text-amber-300/80"
              : "text-white/50"
          }`}
        >
          {label}
          {missingRequired ? " · OBLIGATOIRE" : ""}
        </label>
        {isEmpty && onEstimate ? (
          <button
            type="button"
            onClick={onEstimate}
            disabled={!!estimating}
            className="inline-flex items-center gap-1 rounded border border-amber-400/50 bg-amber-500/15 px-1.5 py-0 text-[9px] font-semibold text-amber-200 hover:bg-amber-500/25 disabled:opacity-50"
            title="Estimer cette valeur avec l'IA"
          >
            {estimating ? (
              <Loader2 className="h-2.5 w-2.5 animate-spin" />
            ) : (
              <Sparkles className="h-2.5 w-2.5" />
            )}
            IA
          </button>
        ) : null}
      </div>
      <input
        type="text"
        inputMode="decimal"
        value={displayed}
        onFocus={(e) => {
          setFocused(true);
          setV(value != null ? String(value) : "");
          requestAnimationFrame(() => {
            try {
              e.target.select();
            } catch {
              /* ignore */
            }
          });
        }}
        onChange={(e) => setV(e.target.value)}
        onBlur={() => {
          setFocused(false);
          const num = _parseNumberLiberal(v);
          if (num !== value) onSave(num);
        }}
        className={`input mt-1 font-mono text-xs ${
          missingRequired
            ? "border-rose-400/70 focus:border-rose-400 ring-1 ring-rose-400/30"
            : ""
        }`}
      />
    </div>
  );
}

// ─── Typology editor ───────────────────────────────────────────

function TypologyEditor({
  value,
  onSave
}: {
  value: Record<string, number>;
  onSave: (newValue: Record<string, number>) => void;
}) {
  const [local, setLocal] = useState<Record<string, string>>(() => {
    const m: Record<string, string> = {};
    for (const k of TYPOLOGY_KEYS) {
      const n = Number(value[k] || 0);
      m[k] = n > 0 ? String(n) : "";
    }
    return m;
  });

  function commit(k: string, raw: string) {
    setLocal((prev) => ({ ...prev, [k]: raw }));
    const next: Record<string, number> = {};
    for (const kk of TYPOLOGY_KEYS) {
      const r = kk === k ? raw : local[kk];
      const n = Number(r);
      if (Number.isFinite(n) && n > 0) next[kk] = Math.floor(n);
    }
    onSave(next);
  }

  const total = TYPOLOGY_KEYS.reduce(
    (acc, k) => acc + (Number(local[k]) || 0),
    0
  );

  return (
    <div className="mt-1">
      <div className="grid grid-cols-4 gap-2 sm:grid-cols-8">
        {TYPOLOGY_KEYS.map((k) => (
          <div key={k} className="flex flex-col items-center">
            <label className="text-[10px] font-mono text-white/50">
              {k}
            </label>
            <input
              type="number"
              min="0"
              step="1"
              value={local[k]}
              onChange={(e) =>
                setLocal((prev) => ({ ...prev, [k]: e.target.value }))
              }
              onBlur={(e) => commit(k, e.target.value)}
              placeholder="0"
              className="w-full rounded border border-brand-800 bg-brand-950 px-1 py-0.5 text-center text-xs text-white focus:border-accent-500 focus:outline-none"
            />
          </div>
        ))}
      </div>
      <p className="mt-1 text-[10px] text-white/40">
        Total typologie : <strong className="text-white/70">{total}</strong>{" "}
        unité{total > 1 ? "s" : ""}
      </p>
    </div>
  );
}

// ─── Section inputs analyse financière + bouton Lancer ──────────

function ManualAnalysisSection({
  data,
  onPatch,
  onRefresh
}: {
  data: LeadDetail;
  onPatch: (field: string, value: unknown) => void;
  onRefresh: () => Promise<void>;
}) {
  const typology = useMemo<Record<string, number>>(() => {
    if (!data.typology_json) return {};
    try {
      const j = JSON.parse(data.typology_json);
      if (j && typeof j === "object") return j;
    } catch {
      /* ignore */
    }
    return {};
  }, [data.typology_json]);

  const [prixLoyers, setPrixLoyers] = useState<Record<string, string>>(
    () => {
      try {
        const j = JSON.parse(data.loyers_projetes_json || "{}");
        const m: Record<string, string> = {};
        for (const k of Object.keys(j)) m[k] = String(j[k]);
        return m;
      } catch {
        return {};
      }
    }
  );

  const [loyerAbord, setLoyerAbord] = useState<string>(() => {
    try {
      const j = JSON.parse(data.loyers_max_abordabilite_json || "{}");
      return String(j.abordable ?? "");
    } catch {
      return "";
    }
  });

  const [running, setRunning] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const missingRequired = useMemo(() => {
    const missing: string[] = [];
    if (!data.address) missing.push("Adresse");
    if (!data.city) missing.push("Ville");
    if (!data.nb_logements) missing.push("Nb logements");
    if (!data.asking_price) missing.push("Prix demandé");
    if (!data.revenus_bruts) missing.push("Revenus annuels");
    if (data.taxes_municipales == null) missing.push("Taxes municipales");
    if (data.taxes_scolaires == null) missing.push("Taxes scolaires");
    if (data.assurances == null) missing.push("Assurances");
    return missing;
  }, [data]);

  const missingRecommended = useMemo(() => {
    const missing: string[] = [];
    if (data.energie == null) missing.push("Énergie");
    if (data.depenses_autres == null) missing.push("Autres dépenses");
    if (!data.annee_construction) missing.push("Année construction");
    if (!data.evaluation_municipale) missing.push("Évaluation municipale");
    return missing;
  }, [data]);

  const missingEstimable = useMemo(() => {
    const m: string[] = [];
    if (data.taxes_municipales == null) m.push("Taxes municipales");
    if (data.taxes_scolaires == null) m.push("Taxes scolaires");
    if (data.assurances == null) m.push("Assurances");
    return m;
  }, [data]);

  const [estimating, setEstimating] = useState(false);

  async function estimateExpenses() {
    setEstimating(true);
    setErr(null);
    try {
      const r = await authedFetch(
        `/api/v1/lead-analyses/${data.id}/estimate-expenses`,
        { method: "POST" }
      );
      if (!r.ok) {
        const txt = await r.text();
        throw new Error(txt.slice(0, 200) || `HTTP ${r.status}`);
      }
      const out = (await r.json()) as {
        taxes_municipales: number | null;
        taxes_scolaires: number | null;
        assurances: number | null;
        source: string;
        note?: string;
      };
      if (data.taxes_municipales == null && out.taxes_municipales != null) {
        onPatch("taxes_municipales", out.taxes_municipales);
      }
      if (data.taxes_scolaires == null && out.taxes_scolaires != null) {
        onPatch("taxes_scolaires", out.taxes_scolaires);
      }
      if (data.assurances == null && out.assurances != null) {
        onPatch("assurances", out.assurances);
      }
      await onRefresh();
    } catch (e) {
      setErr(`Estimation IA échouée : ${(e as Error).message}`);
    } finally {
      setEstimating(false);
    }
  }

  function setPrixLoyer(typo: string, v: string) {
    const next = { ...prixLoyers, [typo]: v };
    setPrixLoyers(next);
    const asJson: Record<string, number> = {};
    for (const [k, val] of Object.entries(next)) {
      const num = Number(val);
      if (Number.isFinite(num) && num > 0) asJson[k] = num;
    }
    onPatch("loyers_projetes_json", JSON.stringify(asJson));
  }

  function setLoyerAbordable(v: string) {
    setLoyerAbord(v);
    const num = Number(v);
    onPatch(
      "loyers_max_abordabilite_json",
      JSON.stringify(Number.isFinite(num) && num > 0 ? { abordable: num } : {})
    );
  }

  async function launchAnalysis() {
    setErr(null);
    if (missingRequired.length > 0) {
      setErr(
        `Champs obligatoires manquants : ${missingRequired.join(", ")}.`
      );
      return;
    }
    setRunning(true);
    try {
      const r = await authedFetch(
        `/api/v1/lead-analyses/${data.id}/run-financial-analysis`,
        { method: "POST" }
      );
      if (!r.ok) {
        const t = await r.text().catch(() => "");
        throw new Error(t.slice(0, 240) || `HTTP ${r.status}`);
      }
      await onRefresh();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setRunning(false);
    }
  }

  return (
    <section className="rounded-xl border border-accent-500/30 bg-accent-500/5 p-4">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <Sparkles className="h-4 w-4 text-accent-500" />
          <h3 className="text-xs font-semibold uppercase tracking-wider text-accent-500">
            Analyse financière — inputs manuels
          </h3>
        </div>
        <DefaultsGearButton group="inputs_manuels" title="Modifier les défauts des inputs manuels (taux refi, MDF %, taux prêteur B, TGA, durée projet, etc.)" />
      </div>

      {missingRequired.length > 0 ? (
        <div className="mt-2 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-[11px]">
          <p className="text-rose-300">
            ⚠ Obligatoires manquants :{" "}
            <strong>{missingRequired.join(", ")}</strong>. Complète-les
            dans la section ci-dessus avant de lancer l&apos;analyse.
          </p>
          {missingEstimable.length > 0 ? (
            <div className="mt-1.5 flex items-center gap-2">
              <button
                type="button"
                onClick={() => void estimateExpenses()}
                disabled={estimating}
                className="inline-flex items-center gap-1.5 rounded-md border border-amber-400/50 bg-amber-500/15 px-2 py-1 text-[11px] font-semibold text-amber-200 hover:bg-amber-500/25 disabled:opacity-50"
                title="Estimer avec l'IA (taxes muni, taxes scol, assurances)"
              >
                {estimating ? (
                  <Loader2 className="h-3 w-3 animate-spin" />
                ) : (
                  <Sparkles className="h-3 w-3" />
                )}
                Estimer avec l&apos;IA : {missingEstimable.join(", ")}
              </button>
            </div>
          ) : null}
        </div>
      ) : null}

      {missingRequired.length === 0 && missingRecommended.length > 0 ? (
        <p className="mt-2 rounded-lg border border-white/10 bg-white/[0.03] px-3 py-2 text-[11px] text-white/60">
          ℹ Informations recommandées non saisies (l&apos;analyse peut
          quand même se lancer) :{" "}
          <strong className="text-white/80">
            {missingRecommended.join(", ")}
          </strong>
          .
        </p>
      ) : null}

      {/* Inputs avec défaut */}
      <div className="mt-3 grid gap-3 sm:grid-cols-4">
        <FieldNumber
          label="TGA (%)"
          value={data.tga_pct ?? 4}
          onSave={(v) => onPatch("tga_pct", v ?? 4)}
          format="percent"
        />
        <FieldNumber
          label="Taux intérêt achat (%)"
          value={data.taux_interet_achat_pct ?? 4}
          onSave={(v) => onPatch("taux_interet_achat_pct", v ?? 4)}
          format="percent"
        />
        <FieldNumber
          label="MDF prêteur B (%)"
          value={data.mdf_preteur_b_pct ?? 25}
          onSave={(v) => onPatch("mdf_preteur_b_pct", v ?? 25)}
          format="percent"
        />
        <FieldYesNo
          label="Wifi inclus refi"
          value={data.ajout_wifi ?? true}
          onSave={(v) => onPatch("ajout_wifi", v)}
        />
      </div>

      <div className="mt-3 grid gap-3 sm:grid-cols-3">
        <FieldNumber
          label="Logements ajoutés refi"
          value={data.nb_logements_ajoutes}
          onSave={(v) => onPatch("nb_logements_ajoutes", v)}
        />
        <FieldNumber
          label="Thermopompes ajoutées"
          value={data.nb_thermopompes_ajoutees}
          onSave={(v) => onPatch("nb_thermopompes_ajoutees", v)}
        />
        <FieldNumber
          label="% réduction énergie"
          value={data.reduction_energie_pct}
          onSave={(v) => onPatch("reduction_energie_pct", v)}
          format="percent"
        />
        <FieldNumber
          label="Taux d'intérêt refi (%)"
          value={data.taux_interet_refi_pct}
          onSave={(v) => onPatch("taux_interet_refi_pct", v)}
          format="percent"
        />
        <FieldNumber
          label="Taux d'intérêt prêteur B (%)"
          value={data.taux_interet_preteur_b_projet_pct ?? 8}
          onSave={(v) =>
            onPatch("taux_interet_preteur_b_projet_pct", v ?? 8)
          }
          format="percent"
        />
        <FieldNumber
          label="Durée projet (années)"
          value={data.duree_projet_annees}
          onSave={(v) => onPatch("duree_projet_annees", v)}
        />
        <FieldNumber
          label="Frais développement ($)"
          value={data.frais_developpement}
          onSave={(v) => onPatch("frais_developpement", v)}
          format="money"
        />
        <FieldNumber
          label="Frais négociations ($)"
          value={data.frais_negociations}
          onSave={(v) => onPatch("frais_negociations", v)}
          format="money"
        />
        <FieldNumber
          label="Frais travaux ($)"
          value={data.travaux_estimes}
          onSave={(v) => onPatch("travaux_estimes", v)}
          format="money"
        />
        <FieldNumber
          label="Loyer abordable (APH SELECT)"
          value={loyerAbord ? Number(loyerAbord) : null}
          onSave={(v) => setLoyerAbordable(v == null ? "" : String(v))}
        />
      </div>

      <div className="mt-3">
        <p className="text-[11px] font-semibold uppercase tracking-wider text-white/50">
          Loyers projetés par typologie (uniquement où la quantité &gt; 0)
        </p>
        <div className="mt-1 grid gap-2 sm:grid-cols-3">
          {TYPOLOGY_KEYS.filter((k) => (typology[k] || 0) > 0).map((k) => (
            <div key={k}>
              <label className="text-[10px] uppercase tracking-wider text-white/50">
                {k} ({typology[k]} log.) — $/mois
              </label>
              <input
                type="number"
                step="any"
                value={prixLoyers[k] ?? ""}
                onChange={(e) => setPrixLoyer(k, e.target.value)}
                className="input font-mono text-xs"
                placeholder="ex. 1400"
              />
            </div>
          ))}
          {TYPOLOGY_KEYS.filter((k) => (typology[k] || 0) > 0).length === 0 ? (
            <p className="col-span-3 text-[11px] text-white/40">
              Renseigne d&apos;abord la typologie dans les infos extraites
              ci-dessus.
            </p>
          ) : null}
        </div>
      </div>

      {err ? (
        <p className="mt-3 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-[11px] text-rose-300">
          {err}
        </p>
      ) : null}

      <div className="mt-4 flex justify-end">
        <button
          type="button"
          onClick={() => void launchAnalysis()}
          disabled={running || missingRequired.length > 0}
          className="btn-accent inline-flex items-center text-sm disabled:opacity-60"
        >
          {running ? (
            <>
              <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />
              Calcul en cours…
            </>
          ) : (
            <>
              <Flame className="mr-1.5 h-4 w-4" />
              Lancer l&apos;analyse
            </>
          )}
        </button>
      </div>
    </section>
  );
}

function FieldYesNo({
  label,
  value,
  onSave
}: {
  label: string;
  value: boolean;
  onSave: (v: boolean) => void;
}) {
  return (
    <div>
      <label className="text-[10px] uppercase tracking-wider text-white/50">
        {label}
      </label>
      <div className="mt-1 inline-flex rounded-md border border-brand-700 bg-brand-950 p-0.5">
        <button
          type="button"
          onClick={() => onSave(true)}
          className={`rounded px-3 py-1 text-[11px] font-semibold ${
            value ? "bg-emerald-500 text-brand-950" : "text-white/60"
          }`}
        >
          Oui
        </button>
        <button
          type="button"
          onClick={() => onSave(false)}
          className={`rounded px-3 py-1 text-[11px] font-semibold ${
            !value ? "bg-rose-500 text-white" : "text-white/60"
          }`}
        >
          Non
        </button>
      </div>
    </div>
  );
}

// ─── Types résultats ─────────────────────────────────────────────

type DepensesBreakdown = {
  inoccupation: number;
  taxes_municipales: number;
  taxes_scolaires: number;
  assurances: number;
  energie: number;
  concierge: number;
  entretien: number;
  gestion: number;
  wifi: number;
  thermopompes: number;
  autres: number;
};

type ScenarioResult = {
  name: string;
  label: string;
  ltv: number;
  amort_annees: number;
  rcd: number;
  nb_log: number;
  loyer_mois: number;
  revenus_totaux: number;
  depenses_total: number;
  depenses?: DepensesBreakdown;
  revenus_net: number;
  valeur_eco_tga: number;
  valeur_eco_rcd: number;
  valeur_marchande: number | null;
  valeur_retenue: number;
  financement: number;
  paiement_mensuel_actuel?: number;
  cashflow_annuel?: number;
  mdf_necessaire: number | null;
  equite_a_la_fin: number | null;
};

type FraisDemarrageBreakdown = {
  courtier_hypothecaire_1: number;
  courtier_hypothecaire_2: number;
  taxes_bienvenue: number;
  evaluateur: number;
  evaluateur_2: number;
  inspection: number;
  avocat: number;
  notaire: number;
  notaire_2: number;
  rapport_efficacite: number;
  frais_developpement: number;
  frais_negociations: number;
  frais_travaux: number;
  // Mai 2026 : frais de dossier du prêteur B (2 % × prêt initial par
  // défaut, modifiable via le défaut global `frais_dossier_preteur_pct`).
  // Inséré APRÈS « Travaux estimés » dans l'UI.
  frais_dossier_preteur: number;
  interets: number;
  revenus_nets_pendant_projet: number;
};

type AnalysisResults = {
  frais_demarrage?: FraisDemarrageBreakdown;
  frais_demarrage_total: number;
  prix_acquisition: number;
  mdf_preteur_b?: number;
  mdf_preteur_b_pct?: number;
  mdf_pct_prix_achat?: number;
  mdf_25pct_prix_achat?: number;
  prix_achat?: number;
  frais_demarrage_financables?: string[];
  taux_interet_preteur_b_projet?: number;
  taux_inoccupation_pct?: number;
  typology: {
    h13_loyer_pondere: number;
    nb_abordables: number;
    nb_pdm: number;
    nouveau_loyer_moyen_pdm: number;
  };
  scenarios: {
    achat: ScenarioResult;
    refi_schl: ScenarioResult;
    refi_aph_50: ScenarioResult;
    refi_aph_100: ScenarioResult | null;
  };
  best_refi: {
    amount: number;
    program: string;
  };
};

function AnalysisResultsTable({
  resultsJson,
  overridesJson,
  financablesJson,
  mdfPct,
  prixAchat,
  fraisDemarrageTotalDb,
  mdfPreteurBDb,
  onPatchOverrides,
  onPatchFinancables
}: {
  resultsJson: string;
  overridesJson?: string | null;
  financablesJson?: string | null;
  mdfPct?: number;
  prixAchat?: number;
  fraisDemarrageTotalDb?: number | null;
  mdfPreteurBDb?: number | null;
  onPatchOverrides?: (json: string) => void;
  onPatchFinancables?: (json: string) => void;
}) {
  void fraisDemarrageTotalDb;
  const data = useMemo<AnalysisResults | null>(() => {
    try {
      return JSON.parse(resultsJson) as AnalysisResults;
    } catch {
      return null;
    }
  }, [resultsJson]);

  if (!data) return null;

  const cols: Array<[string, ScenarioResult | null]> = [
    ["Achat", data.scenarios.achat],
    ["SCHL standard", data.scenarios.refi_schl],
    ["SCHL Efficacité (50 pts)", data.scenarios.refi_aph_50],
    ["SCHL Abord+Eff (100 pts)", data.scenarios.refi_aph_100]
  ];

  const jsonPct = data.mdf_preteur_b_pct;
  const jsonPctPercent = jsonPct != null && jsonPct < 1 ? jsonPct * 100 : jsonPct;
  const livePct = mdfPct ?? 25;
  const inputsChanged =
    jsonPctPercent != null && Math.abs(jsonPctPercent - livePct) > 0.01;

  return (
    <section className="rounded-xl border border-emerald-500/30 bg-emerald-500/5 p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-xs font-semibold uppercase tracking-wider text-emerald-300">
          ✓ Résultats de l&apos;analyse financière
        </h3>
        <div className="text-[11px] text-white/70">
          <strong className="text-emerald-300">Best refi</strong> :{" "}
          {fmtMoney(data.best_refi.amount)} —{" "}
          <span className="text-white/60">{data.best_refi.program}</span>
        </div>
      </div>

      <p className="mt-1 text-[10px] text-white/40">
        Frais démarrage : {fmtMoney(data.frais_demarrage_total)} · Prix
        acquisition : {fmtMoney(data.prix_acquisition)} · Loyer pondéré H13 :{" "}
        {fmtMoney(data.typology.h13_loyer_pondere)} /mois
        {data.typology.nb_abordables > 0
          ? ` · ${data.typology.nb_abordables} abord / ${data.typology.nb_pdm} PDM`
          : ""}
      </p>

      {inputsChanged ? (
        <div className="mt-2 rounded-lg border border-amber-400/60 bg-amber-500/15 px-3 py-2 text-[11px] text-amber-200">
          ⚠ Les inputs ont changé depuis la dernière analyse
          (ex. MDF prêteur B : {jsonPctPercent}% → {livePct}%).{" "}
          <strong>Relance l&apos;analyse</strong> pour mettre à jour
          les résultats ci-dessous.
        </div>
      ) : null}

      {data.mdf_preteur_b != null ? (
        <div className="mt-2 rounded-lg border border-amber-400/40 bg-amber-500/10 px-3 py-2">
          <p className="text-[10px] uppercase tracking-wider text-amber-300">
            MDF avec prêteur B
          </p>
          <p className="mt-0.5 text-sm font-bold text-amber-200">
            {fmtMoney(data.mdf_preteur_b)}
          </p>
          <p className="text-[10px] text-white/50">
            {(() => {
              const liveOrJson = mdfPct ?? data.mdf_preteur_b_pct ?? 25;
              const pctDisplay =
                liveOrJson < 1
                  ? (liveOrJson * 100).toFixed(0)
                  : liveOrJson.toFixed(0);
              return `${pctDisplay} % × prix d'achat + frais démarrage`;
            })()}
          </p>
        </div>
      ) : null}

      <div className="mt-3 overflow-x-auto">
        <table className="w-full min-w-[640px] text-[11px]">
          <thead>
            <tr className="text-white/40">
              <th className="px-2 py-1 text-left">Métrique</th>
              {cols.map(([label, s]) => (
                <th key={label} className="px-2 py-1 text-right">
                  {label}
                  {s ? (
                    <span className="ml-1 text-white/30">
                      ({(s.ltv * 100).toFixed(0)}% · {s.amort_annees}ans · RCD{" "}
                      {s.rcd.toFixed(2)})
                    </span>
                  ) : null}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            <ResultRow label="Loyer moyen ($/mois)" cols={cols} pick={(s) => s.loyer_mois} />
            <ResultRow label="Revenus totaux ($/an)" cols={cols} pick={(s) => s.revenus_totaux} />
            <ResultRow label="Dépenses totales" cols={cols} pick={(s) => s.depenses_total} />
            <ResultRow label="Revenus net" cols={cols} pick={(s) => s.revenus_net} />
            <ResultRow label="Valeur éco RDC" cols={cols} pick={(s) => s.valeur_eco_rcd} />
            <ResultRow label="Valeur éco TGA" cols={cols} pick={(s) => s.valeur_eco_tga} />
            <ResultRow label="Valeur marchande" cols={cols} pick={(s) => s.valeur_marchande} fallback="—" />
            <ResultRow label="Valeur retenue" cols={cols} pick={(s) => s.valeur_retenue} bold />
            <ResultRow label="Prêt accordé" cols={cols} pick={(s) => s.financement} bold />
            <ResultRow label="MDF nécessaire" cols={cols} pick={(s) => s.mdf_necessaire} fallback="N/A" />
            <ResultRow label="Cashflow annuel" cols={cols} pick={(s) => s.cashflow_annuel} fallback="N/A" colorEquite />
            <ResultRow label="Équité à la fin" cols={cols} pick={(s) => s.equite_a_la_fin} fallback="N/A" colorEquite />
          </tbody>
        </table>
      </div>

      <FraisDemarrageBreakdownPanel
        data={data}
        overridesJson={overridesJson}
        financablesJson={financablesJson}
        mdfPct={mdfPct}
        prixAchat={prixAchat}
        mdfPreteurBDb={mdfPreteurBDb}
        onPatchOverrides={onPatchOverrides}
        onPatchFinancables={onPatchFinancables}
      />
    </section>
  );
}

// ─── Frais de démarrage ──────────────────────────────────────────

const FRAIS_KEYS: Array<keyof FraisDemarrageBreakdown> = [
  "courtier_hypothecaire_1",
  "courtier_hypothecaire_2",
  "taxes_bienvenue",
  "evaluateur",
  "evaluateur_2",
  "inspection",
  "avocat",
  "notaire",
  "notaire_2",
  "rapport_efficacite",
  "frais_developpement",
  "frais_negociations",
  "frais_travaux",
  // Mai 2026 : nouveau poste, juste après "Travaux estimés" comme
  // demandé par Phil (ordre figé pour respecter sa lecture habituelle).
  "frais_dossier_preteur",
  "interets",
  "revenus_nets_pendant_projet"
];

function _fmtPctShort(frac: number): string {
  const asPct = Math.abs(frac) <= 1 ? frac * 100 : frac;
  const isInt = Math.abs(asPct - Math.round(asPct)) < 0.01;
  return isInt
    ? `${Math.round(asPct)} %`
    : `${asPct.toFixed(1).replace(".", ",")} %`;
}

function buildFraisLabels(
  mdfPctNumeric: number,
  tauxInteretPreteurB: number | null | undefined
): Array<[keyof FraisDemarrageBreakdown, string]> {
  const inverseMdf = 1 - mdfPctNumeric;
  const tauxLbl =
    tauxInteretPreteurB != null && !Number.isNaN(tauxInteretPreteurB)
      ? _fmtPctShort(tauxInteretPreteurB)
      : "taux prêteur B";
  const interetsLabel = `Intérêts pendant projet (${_fmtPctShort(inverseMdf)} × prix × ${tauxLbl} × durée)`;
  const labels: Record<keyof FraisDemarrageBreakdown, string> = {
    courtier_hypothecaire_1: "Courtier hypothécaire (1 % × prix d'achat)",
    courtier_hypothecaire_2: "Courtier hypothécaire 2 (1 % × financement APH)",
    taxes_bienvenue: "Taxes de bienvenue (Montréal, tiers progressifs)",
    evaluateur: "Évaluateur agréé",
    evaluateur_2: "Évaluateur agréé 2",
    inspection: "Inspection",
    avocat: "Avocat",
    notaire: "Notaire",
    notaire_2: "Notaire 2",
    rapport_efficacite: "Rapport d'efficacité énergétique",
    frais_developpement: "Frais de développement",
    frais_negociations: "Frais de négociations",
    frais_travaux: "Travaux estimés",
    frais_dossier_preteur: "Frais de dossier du prêteur",
    interets: interetsLabel,
    revenus_nets_pendant_projet: "Revenus nets pendant projet (négatif)"
  };
  return FRAIS_KEYS.map((k) => [k, labels[k]] as [keyof FraisDemarrageBreakdown, string]);
}

const DEFAULT_FINANCABLES = [
  "rapport_efficacite",
  "frais_developpement",
  "frais_travaux"
];

function FraisDemarrageBreakdownPanel({
  data,
  overridesJson,
  financablesJson,
  mdfPct,
  prixAchat,
  mdfPreteurBDb,
  onPatchOverrides,
  onPatchFinancables
}: {
  data: AnalysisResults;
  overridesJson?: string | null;
  financablesJson?: string | null;
  mdfPct?: number;
  prixAchat?: number;
  mdfPreteurBDb?: number | null;
  onPatchOverrides?: (json: string) => void;
  onPatchFinancables?: (json: string) => void;
}) {
  const frais = data.frais_demarrage;
  const mdfPctFinal = mdfPct ?? data.mdf_preteur_b_pct ?? 25;
  const mdfPctNumeric =
    mdfPctFinal > 1 ? mdfPctFinal / 100 : mdfPctFinal;
  const prixFinal = prixAchat ?? data.prix_achat ?? 0;
  const mdfPctValue =
    data.mdf_pct_prix_achat ?? data.mdf_25pct_prix_achat ?? mdfPctNumeric * prixFinal;
  const mdfTotalStored = mdfPreteurBDb ?? data.mdf_preteur_b ?? null;

  const overrides = useMemo<Record<string, number>>(() => {
    if (!overridesJson) return {};
    try {
      const j = JSON.parse(overridesJson);
      if (j && typeof j === "object") return j as Record<string, number>;
    } catch {
      /* ignore */
    }
    return {};
  }, [overridesJson]);

  const financables = useMemo<Set<string>>(() => {
    if (financablesJson) {
      try {
        const j = JSON.parse(financablesJson);
        if (Array.isArray(j)) return new Set(j.map((x) => String(x)));
      } catch {
        /* ignore */
      }
    }
    return new Set(DEFAULT_FINANCABLES);
  }, [financablesJson]);

  function toggleFinancable(key: string) {
    const next = new Set(financables);
    if (next.has(key)) next.delete(key);
    else next.add(key);
    onPatchFinancables?.(JSON.stringify(Array.from(next)));
  }

  function setOverride(key: string, val: number | null) {
    const next = { ...overrides };
    if (val == null || !Number.isFinite(val)) {
      delete next[key];
    } else {
      next[key] = val;
    }
    onPatchOverrides?.(JSON.stringify(next));
  }

  const fraisLabels = buildFraisLabels(
    mdfPctNumeric,
    data.taux_interet_preteur_b_projet
  );

  let subTotalCash = 0;
  let subTotalFinanced = 0;
  if (frais) {
    for (const k of FRAIS_KEYS) {
      const v =
        overrides[k] != null ? Number(overrides[k]) : Number(frais[k] || 0);
      if (!Number.isFinite(v)) continue;
      if (financables.has(k)) {
        subTotalCash += v * mdfPctNumeric;
        subTotalFinanced += v * (1 - mdfPctNumeric);
      } else {
        subTotalCash += v;
      }
    }
  }
  const totalMdfLocal = mdfPctValue + subTotalCash;

  if (!frais) return null;

  return (
    <section className="mt-4 rounded-lg border border-amber-400/30 bg-amber-500/5 p-4">
      <div className="flex items-center justify-between gap-2">
        <h4 className="text-xs font-semibold uppercase tracking-wider text-amber-300">
          Composition de la MDF avec prêteur B
        </h4>
        <DefaultsGearButton group="mdf_frais" title="Modifier les défauts des frais MDF (Évaluateur, Inspection, Notaire, Avocat, Rapport efficacité, % courtiers)" />
      </div>
      <p className="mt-0.5 text-[10px] text-white/50">
        Total à sortir en cash = {_fmtPctShort(mdfPctNumeric)} du prix
        d&apos;achat + frais non finançables + {_fmtPctShort(mdfPctNumeric)}
        {" "}des frais finançables. Coche un poste pour le rendre
        finançable par le prêteur B (par défaut : rapport efficacité,
        frais développement, travaux).
      </p>

      <table className="mt-3 w-full text-[11px]">
        <thead>
          <tr className="text-[9px] uppercase tracking-wider text-white/40">
            <th className="px-2 py-1 text-left">Poste</th>
            <th className="px-2 py-1 text-right">Valeur</th>
            <th className="w-16 px-2 py-1 text-center" title="Coché = ce poste est financé par le prêteur B, tu ne paies que le pct en cash">
              Finançable
            </th>
            <th className="px-2 py-1 text-right">Cash à sortir</th>
          </tr>
        </thead>
        <tbody>
          <tr className="border-t border-amber-400/20">
            <td className="px-2 py-1 font-semibold text-amber-200" colSpan={3}>
              {_fmtPctShort(mdfPctNumeric)} du prix d&apos;achat
              {prixFinal > 0 ? (
                <span className="ml-1 text-white/50">
                  ({_fmtPctShort(mdfPctNumeric)} × {fmtMoney(prixFinal)})
                </span>
              ) : null}
            </td>
            <td className="px-2 py-1 text-right font-mono tabular-nums font-semibold text-amber-200">
              {fmtMoney(mdfPctValue)}
            </td>
          </tr>
          <tr className="border-t border-amber-400/20">
            <td className="px-2 py-1 text-white/50" colSpan={4}>
              <span className="text-[10px] uppercase tracking-wider">
                Frais de démarrage
              </span>
            </td>
          </tr>
          {fraisLabels.map(([key, label]) => {
            const computed = Number(frais[key] || 0);
            const overridden = overrides[key] != null;
            const displayVal = overridden
              ? Number(overrides[key])
              : computed;
            if (!overridden && !computed) return null;
            const isFinancable = financables.has(key);
            const cashForRow = isFinancable
              ? displayVal * mdfPctNumeric
              : displayVal;
            return (
              <tr key={key} className="border-t border-brand-800/60">
                <td className="px-2 py-1 pl-4 text-white/60">
                  {label}
                  {overridden ? (
                    <button
                      type="button"
                      onClick={() => setOverride(key, null)}
                      className="ml-1 rounded bg-amber-500/20 px-1 py-0 text-[9px] text-amber-200 hover:bg-amber-500/30"
                      title="Réinitialiser à la valeur calculée"
                    >
                      override · réinit
                    </button>
                  ) : null}
                </td>
                <td className="px-2 py-1 text-right">
                  <EditableMoney
                    value={displayVal}
                    computed={computed}
                    overridden={overridden}
                    onSave={(v) =>
                      setOverride(key, v === computed ? null : v)
                    }
                  />
                </td>
                <td className="px-2 py-1 text-center">
                  <input
                    type="checkbox"
                    checked={isFinancable}
                    onChange={() => toggleFinancable(key)}
                    className="h-3.5 w-3.5 cursor-pointer accent-amber-400"
                    title={
                      isFinancable
                        ? `Finançable — payé seulement à ${_fmtPctShort(mdfPctNumeric)} en cash`
                        : "Non finançable — payé 100 % en cash"
                    }
                  />
                </td>
                <td
                  className={`px-2 py-1 text-right font-mono tabular-nums ${
                    isFinancable ? "text-emerald-300" : "text-white/80"
                  }`}
                >
                  {fmtMoney(cashForRow)}
                </td>
              </tr>
            );
          })}
          <tr className="border-t border-amber-400/40 bg-amber-500/5">
            <td className="px-2 py-1 pl-4 text-amber-200" colSpan={3}>
              Sous-total frais de démarrage (cash)
            </td>
            <td className="px-2 py-1 text-right font-mono tabular-nums font-semibold text-amber-200">
              {fmtMoney(subTotalCash)}
            </td>
          </tr>
          {subTotalFinanced > 0.5 ? (
            <tr className="bg-emerald-500/5">
              <td className="px-2 py-1 pl-4 text-[10px] text-emerald-300" colSpan={3}>
                dont financé par prêteur B
              </td>
              <td className="px-2 py-1 text-right font-mono tabular-nums text-[10px] text-emerald-300">
                +{fmtMoney(subTotalFinanced)}
              </td>
            </tr>
          ) : null}
          <tr className="border-t-2 border-amber-400/60 bg-amber-500/10">
            <td className="px-2 py-1.5 font-bold text-amber-200" colSpan={3}>
              Total — MDF avec prêteur B
              {mdfTotalStored != null &&
              Math.abs((mdfTotalStored || 0) - totalMdfLocal) > 1 ? (
                <span className="ml-2 rounded bg-amber-500/30 px-1 py-0 text-[9px] font-normal text-amber-100">
                  recalcul requis
                </span>
              ) : null}
            </td>
            <td className="px-2 py-1.5 text-right font-mono tabular-nums font-bold text-amber-200">
              {fmtMoney(totalMdfLocal)}
            </td>
          </tr>
        </tbody>
      </table>
    </section>
  );
}

function EditableMoney({
  value,
  computed,
  overridden,
  onSave
}: {
  value: number;
  computed: number;
  overridden: boolean;
  onSave: (v: number) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(String(Math.round(value)));
  useEffect(() => {
    if (!editing) setDraft(String(Math.round(value)));
  }, [value, editing]);

  if (editing) {
    return (
      <input
        autoFocus
        type="number"
        value={draft}
        step="1"
        onChange={(e) => setDraft(e.target.value)}
        onBlur={() => {
          setEditing(false);
          const n = Number(draft);
          if (Number.isFinite(n)) onSave(n);
        }}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            const n = Number(draft);
            if (Number.isFinite(n)) onSave(n);
            setEditing(false);
          } else if (e.key === "Escape") {
            setEditing(false);
            setDraft(String(Math.round(computed)));
          }
        }}
        className="w-28 rounded border border-amber-400/40 bg-brand-950 px-1 py-0.5 text-right font-mono text-[11px] text-white focus:border-accent-500 focus:outline-none"
      />
    );
  }
  return (
    <button
      type="button"
      onClick={() => setEditing(true)}
      title={
        overridden
          ? `Manuel (calcul auto : ${fmtMoney(computed)}). Clique pour modifier.`
          : "Clique pour overrider"
      }
      className={`font-mono tabular-nums hover:underline ${
        overridden ? "text-amber-200 font-semibold" : "text-white/80"
      }`}
    >
      {fmtMoney(value)}
    </button>
  );
}

function ResultRow({
  label,
  cols,
  pick,
  bold,
  fallback,
  colorEquite
}: {
  label: string;
  cols: Array<[string, ScenarioResult | null]>;
  pick: (s: ScenarioResult) => number | null | undefined;
  bold?: boolean;
  fallback?: string;
  colorEquite?: boolean;
}) {
  return (
    <tr className="border-t border-brand-800/60">
      <td className="px-2 py-1 text-white/60">{label}</td>
      {cols.map(([k, s]) => {
        if (!s) return (
          <td key={k} className="px-2 py-1 text-right text-white/30">—</td>
        );
        const val = pick(s);
        if (val == null) return (
          <td key={k} className="px-2 py-1 text-right text-white/30">
            {fallback || "—"}
          </td>
        );
        const txt = fmtMoney(val);
        const tone = colorEquite
          ? val >= 0
            ? "text-emerald-300"
            : "text-rose-300"
          : bold
            ? "text-white"
            : "text-white/80";
        return (
          <td
            key={k}
            className={`px-2 py-1 text-right font-mono tabular-nums ${tone} ${bold ? "font-bold" : ""}`}
          >
            {txt}
          </td>
        );
      })}
    </tr>
  );
}

// ─── Détail granulaire des calculs (style Excel) ───────────────

function CalculationDetailsSection({
  resultsJson,
  overridesJson,
  lead
}: {
  resultsJson: string;
  overridesJson?: string | null;
  lead: LeadDetail;
}) {
  const [open, setOpen] = useState(false);

  const data = useMemo<AnalysisResults | null>(() => {
    try {
      return JSON.parse(resultsJson) as AnalysisResults;
    } catch {
      return null;
    }
  }, [resultsJson]);

  const overrides = useMemo<Record<string, number>>(() => {
    if (!overridesJson) return {};
    try {
      const j = JSON.parse(overridesJson);
      if (j && typeof j === "object") return j as Record<string, number>;
    } catch {
      /* ignore */
    }
    return {};
  }, [overridesJson]);

  if (!data) return null;

  return (
    <section className="mt-3">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="text-xs text-emerald-300 underline-offset-2 hover:underline"
      >
        {open ? "▾" : "▸"} Voir détails des calculs
      </button>

      {open ? (
        <div className="mt-2 max-h-[600px] overflow-y-auto rounded-xl border border-brand-800 bg-brand-950/40 p-4 text-[11px] text-white/80">
          <p className="text-[10px] text-white/40">
            Reproduit la granularité du fichier Excel d&apos;origine. Toutes
            les valeurs sont issues du dernier calcul d&apos;analyse persisté.
          </p>

          <HypothesesSubsection lead={lead} data={data} />
          <TypologieSubsection data={data} />
          <FraisDemarrageDetailSubsection
            data={data}
            overrides={overrides}
            mdfPctFinal={lead.mdf_preteur_b_pct ?? data.mdf_preteur_b_pct ?? 25}
            prixAchat={lead.asking_price ?? data.prix_achat ?? 0}
          />
          <ScenariosDetailSubsection data={data} />
          <BestRefiSubsection data={data} />
        </div>
      ) : null}
    </section>
  );
}

function _fmtMoneyDetail(n: number | null | undefined): string {
  if (n == null || Number.isNaN(n)) return "—";
  const rounded = Math.round(n);
  const sign = rounded < 0 ? "-" : "";
  const abs = Math.abs(rounded).toString();
  const withSep = abs.replace(/\B(?=(\d{3})+(?!\d))/g, " ");
  return `${sign}${withSep} $`;
}

function _fmtPctDetail(n: number | null | undefined): string {
  if (n == null || Number.isNaN(n)) return "—";
  const asPct = Math.abs(n) <= 1 ? n * 100 : n;
  return `${asPct.toFixed(2).replace(".", ",")} %`;
}

function _fmtIntDetail(n: number | null | undefined): string {
  if (n == null || Number.isNaN(n)) return "—";
  const abs = Math.round(n).toString();
  return abs.replace(/\B(?=(\d{3})+(?!\d))/g, " ");
}

function _fmtBoolDetail(b: boolean | null | undefined): string {
  if (b == null) return "—";
  return b ? "Oui" : "Non";
}

function HypothesesSubsection({
  lead,
  data
}: {
  lead: LeadDetail;
  data: AnalysisResults;
}) {
  const prixAchat = lead.asking_price ?? data.prix_achat ?? null;
  const nbLog = lead.nb_logements;
  const coutParLogement =
    prixAchat != null && nbLog != null && nbLog > 0
      ? prixAchat / nbLog
      : null;

  const rows: Array<[string, string]> = [
    ["Prix d'achat", _fmtMoneyDetail(prixAchat)],
    ["Nombre de logements", _fmtIntDetail(nbLog)],
    ["Coût par logement", _fmtMoneyDetail(coutParLogement)],
    ["Durée du projet (années)", _fmtIntDetail(lead.duree_projet_annees)],
    ["TGA (taux global d'actualisation)", _fmtPctDetail(lead.tga_pct)],
    ["Taux d'intérêt achat", _fmtPctDetail(lead.taux_interet_achat_pct)],
    ["Taux d'intérêt refi", _fmtPctDetail(lead.taux_interet_refi_pct)],
    ["MDF prêteur B (%)", _fmtPctDetail(lead.mdf_preteur_b_pct ?? data.mdf_preteur_b_pct)],
    [
      "Taux d'intérêt prêteur B (chantier)",
      _fmtPctDetail(data.taux_interet_preteur_b_projet)
    ],
    ["Taux d'inoccupation", _fmtPctDetail(data.taux_inoccupation_pct)],
    ["Réduction énergie (refi)", _fmtPctDetail(lead.reduction_energie_pct)],
    ["WiFi ajouté (refi)", _fmtBoolDetail(lead.ajout_wifi)],
    ["Nb thermopompes ajoutées (APH)", _fmtIntDetail(lead.nb_thermopompes_ajoutees)],
    ["Nb logements ajoutés", _fmtIntDetail(lead.nb_logements_ajoutes)]
  ];
  return (
    <div className="mt-4">
      <h4 className="text-[10px] font-semibold uppercase tracking-wider text-accent-500">
        A · Hypothèses paramétrables
      </h4>
      <table className="mt-2 w-full">
        <tbody>
          {rows.map(([label, val]) => (
            <tr key={label} className="border-t border-brand-800/60">
              <td className="px-2 py-1 text-white/60">{label}</td>
              <td className="px-2 py-1 text-right font-mono tabular-nums text-white/90">
                {val}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function TypologieSubsection({ data }: { data: AnalysisResults }) {
  const t = data.typology;
  const rows: Array<[string, string]> = [
    ["H13 — loyer pondéré ($/mois)", _fmtMoneyDetail(t.h13_loyer_pondere)],
    ["Nb logements abordables", _fmtIntDetail(t.nb_abordables)],
    ["Nb logements PDM (programme de modulation)", _fmtIntDetail(t.nb_pdm)],
    ["Nouveau loyer moyen PDM ($/mois)", _fmtMoneyDetail(t.nouveau_loyer_moyen_pdm)]
  ];
  return (
    <div className="mt-4">
      <h4 className="text-[10px] font-semibold uppercase tracking-wider text-accent-500">
        B · Typologie agrégée
      </h4>
      <table className="mt-2 w-full">
        <tbody>
          {rows.map(([label, val]) => (
            <tr key={label} className="border-t border-brand-800/60">
              <td className="px-2 py-1 text-white/60">{label}</td>
              <td className="px-2 py-1 text-right font-mono tabular-nums text-white/90">
                {val}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function FraisDemarrageDetailSubsection({
  data,
  overrides,
  mdfPctFinal,
  prixAchat
}: {
  data: AnalysisResults;
  overrides: Record<string, number>;
  mdfPctFinal: number;
  prixAchat: number;
}) {
  const frais = data.frais_demarrage;
  const financables = new Set(data.frais_demarrage_financables ?? []);
  const mdfPctNumeric = mdfPctFinal > 1 ? mdfPctFinal / 100 : mdfPctFinal;
  const mdfFromPrice = mdfPctNumeric * prixAchat;
  const mdfTotal = data.mdf_preteur_b ?? null;

  if (!frais) {
    return (
      <div className="mt-4">
        <h4 className="text-[10px] font-semibold uppercase tracking-wider text-accent-500">
          C · Frais de démarrage
        </h4>
        <p className="mt-2 text-white/40">
          Détail indisponible dans cette version d&apos;analyse.
        </p>
      </div>
    );
  }

  const fraisLabels = buildFraisLabels(
    mdfPctNumeric,
    data.taux_interet_preteur_b_projet
  );

  return (
    <div className="mt-4">
      <h4 className="text-[10px] font-semibold uppercase tracking-wider text-accent-500">
        C · Frais de démarrage (détail par poste)
      </h4>
      <table className="mt-2 w-full">
        <thead>
          <tr className="text-white/40">
            <th className="px-2 py-1 text-left font-normal">Poste</th>
            <th className="px-2 py-1 text-right font-normal">Valeur</th>
            <th className="px-2 py-1 text-center font-normal">Override</th>
            <th className="px-2 py-1 text-center font-normal">Finançable</th>
          </tr>
        </thead>
        <tbody>
          {fraisLabels.map(([key, label]) => {
            const v = frais[key];
            const isOverridden = Object.prototype.hasOwnProperty.call(
              overrides,
              key
            );
            const isFinancable = financables.has(key);
            return (
              <tr key={key} className="border-t border-brand-800/60">
                <td className="px-2 py-1 text-white/60">{label}</td>
                <td className="px-2 py-1 text-right font-mono tabular-nums text-white/90">
                  {_fmtMoneyDetail(v)}
                </td>
                <td className="px-2 py-1 text-center text-white/40">
                  {isOverridden ? "manuel" : "calculé"}
                </td>
                <td className="px-2 py-1 text-center text-white/40">
                  {isFinancable ? "oui" : "—"}
                </td>
              </tr>
            );
          })}
          <tr className="border-t-2 border-brand-700">
            <td className="px-2 py-1 font-semibold text-white">
              Total frais de démarrage
            </td>
            <td className="px-2 py-1 text-right font-mono font-bold tabular-nums text-white">
              {_fmtMoneyDetail(data.frais_demarrage_total)}
            </td>
            <td colSpan={2} />
          </tr>
        </tbody>
      </table>

      <div className="mt-3 rounded-lg border border-amber-400/30 bg-amber-500/5 p-3">
        <p className="text-[10px] uppercase tracking-wider text-amber-300">
          MDF prêteur B — composition
        </p>
        <table className="mt-1 w-full">
          <tbody>
            <tr className="border-t border-brand-800/60">
              <td className="px-2 py-1 text-white/60">
                {_fmtPctDetail(mdfPctNumeric)} × prix d&apos;achat
                ({_fmtMoneyDetail(prixAchat)})
              </td>
              <td className="px-2 py-1 text-right font-mono tabular-nums text-white/90">
                {_fmtMoneyDetail(mdfFromPrice)}
              </td>
            </tr>
            <tr className="border-t border-brand-800/60">
              <td className="px-2 py-1 text-white/60">
                + Frais de démarrage total (cash après finançables)
              </td>
              <td className="px-2 py-1 text-right font-mono tabular-nums text-white/90">
                {_fmtMoneyDetail(data.frais_demarrage_total)}
              </td>
            </tr>
            <tr className="border-t-2 border-brand-700">
              <td className="px-2 py-1 font-semibold text-amber-200">
                = MDF prêteur B total (cash)
              </td>
              <td className="px-2 py-1 text-right font-mono font-bold tabular-nums text-amber-200">
                {_fmtMoneyDetail(mdfTotal)}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  );
}

const DEPENSES_LABELS: Array<[keyof DepensesBreakdown, string]> = [
  ["inoccupation", "Inoccupation (% × revenus)"],
  ["taxes_municipales", "Taxes municipales"],
  ["taxes_scolaires", "Taxes scolaires"],
  ["assurances", "Assurances"],
  ["energie", "Énergie"],
  ["concierge", "Concierge"],
  ["entretien", "Entretien"],
  ["gestion", "Gestion"],
  ["wifi", "WiFi"],
  ["thermopompes", "Thermopompes (APH)"],
  ["autres", "Autres dépenses"]
];

function ScenariosDetailSubsection({ data }: { data: AnalysisResults }) {
  const scenarios: Array<[string, ScenarioResult | null]> = [
    ["Achat", data.scenarios.achat],
    ["SCHL standard", data.scenarios.refi_schl],
    ["APH 50 pts (Efficacité)", data.scenarios.refi_aph_50],
    ["APH 100 pts (Abord + Eff.)", data.scenarios.refi_aph_100]
  ];

  return (
    <div className="mt-4">
      <h4 className="text-[10px] font-semibold uppercase tracking-wider text-accent-500">
        D · Détail par scénario
      </h4>
      <div className="mt-2 space-y-4">
        {scenarios.map(([label, s]) => (
          <ScenarioDetailCard key={label} label={label} scenario={s} />
        ))}
      </div>
    </div>
  );
}

function ScenarioDetailCard({
  label,
  scenario
}: {
  label: string;
  scenario: ScenarioResult | null;
}) {
  if (!scenario) {
    return (
      <div className="rounded-lg border border-brand-800 bg-brand-950 p-3">
        <p className="text-[11px] font-semibold text-white/80">{label}</p>
        <p className="mt-1 text-[10px] text-white/40">
          Scénario non applicable (ex. pas d&apos;abordabilité).
        </p>
      </div>
    );
  }
  const dep = scenario.depenses;
  return (
    <div className="rounded-lg border border-brand-800 bg-brand-950 p-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <p className="text-[11px] font-semibold text-white">{label}</p>
        <p className="text-[10px] text-white/40">
          LTV {(scenario.ltv * 100).toFixed(0)} % · amort.{" "}
          {scenario.amort_annees} ans · RCD {scenario.rcd.toFixed(2)}
        </p>
      </div>

      <table className="mt-2 w-full">
        <tbody>
          <tr className="border-t border-brand-800/60">
            <td className="px-2 py-1 text-white/60">Nombre de logements</td>
            <td className="px-2 py-1 text-right font-mono tabular-nums text-white/90">
              {_fmtIntDetail(scenario.nb_log)}
            </td>
          </tr>
          <tr className="border-t border-brand-800/60">
            <td className="px-2 py-1 text-white/60">Loyer moyen ($/mois)</td>
            <td className="px-2 py-1 text-right font-mono tabular-nums text-white/90">
              {_fmtMoneyDetail(scenario.loyer_mois)}
            </td>
          </tr>
          <tr className="border-t border-brand-800/60">
            <td className="px-2 py-1 text-white/60">Revenus totaux ($/an)</td>
            <td className="px-2 py-1 text-right font-mono tabular-nums text-white/90">
              {_fmtMoneyDetail(scenario.revenus_totaux)}
            </td>
          </tr>
        </tbody>
      </table>

      <p className="mt-3 text-[10px] uppercase tracking-wider text-white/40">
        Dépenses
      </p>
      <table className="mt-1 w-full">
        <tbody>
          {DEPENSES_LABELS.map(([key, lbl]) => (
            <tr key={key} className="border-t border-brand-800/60">
              <td className="px-2 py-1 text-white/60">{lbl}</td>
              <td className="px-2 py-1 text-right font-mono tabular-nums text-white/80">
                {dep ? _fmtMoneyDetail(dep[key]) : "—"}
              </td>
            </tr>
          ))}
          <tr className="border-t-2 border-brand-700">
            <td className="px-2 py-1 font-semibold text-white">
              Total dépenses
            </td>
            <td className="px-2 py-1 text-right font-mono font-bold tabular-nums text-white">
              {_fmtMoneyDetail(scenario.depenses_total)}
            </td>
          </tr>
        </tbody>
      </table>

      <p className="mt-3 text-[10px] uppercase tracking-wider text-white/40">
        Valeurs et financement
      </p>
      <table className="mt-1 w-full">
        <tbody>
          <tr className="border-t border-brand-800/60">
            <td className="px-2 py-1 text-white/60">
              Revenus nets (revenus − dépenses)
            </td>
            <td className="px-2 py-1 text-right font-mono tabular-nums text-white/90">
              {_fmtMoneyDetail(scenario.revenus_net)}
            </td>
          </tr>
          <tr className="border-t border-brand-800/60">
            <td className="px-2 py-1 text-white/60">Valeur éco RCD</td>
            <td className="px-2 py-1 text-right font-mono tabular-nums text-white/80">
              {_fmtMoneyDetail(scenario.valeur_eco_rcd)}
            </td>
          </tr>
          <tr className="border-t border-brand-800/60">
            <td className="px-2 py-1 text-white/60">Valeur éco TGA</td>
            <td className="px-2 py-1 text-right font-mono tabular-nums text-white/80">
              {_fmtMoneyDetail(scenario.valeur_eco_tga)}
            </td>
          </tr>
          <tr className="border-t border-brand-800/60">
            <td className="px-2 py-1 text-white/60">Valeur marchande</td>
            <td className="px-2 py-1 text-right font-mono tabular-nums text-white/80">
              {_fmtMoneyDetail(scenario.valeur_marchande)}
            </td>
          </tr>
          <tr className="border-t border-brand-800/60">
            <td className="px-2 py-1 font-semibold text-white">
              Valeur retenue
            </td>
            <td className="px-2 py-1 text-right font-mono font-bold tabular-nums text-white">
              {_fmtMoneyDetail(scenario.valeur_retenue)}
            </td>
          </tr>
          <tr className="border-t border-brand-800/60">
            <td className="px-2 py-1 font-semibold text-white">
              Financement (prêt accordé)
            </td>
            <td className="px-2 py-1 text-right font-mono font-bold tabular-nums text-white">
              {_fmtMoneyDetail(scenario.financement)}
            </td>
          </tr>
          {scenario.mdf_necessaire != null ? (
            <tr className="border-t border-brand-800/60">
              <td className="px-2 py-1 text-white/60">MDF nécessaire</td>
              <td className="px-2 py-1 text-right font-mono tabular-nums text-amber-200">
                {_fmtMoneyDetail(scenario.mdf_necessaire)}
              </td>
            </tr>
          ) : null}
          {scenario.equite_a_la_fin != null ? (
            <tr className="border-t border-brand-800/60">
              <td className="px-2 py-1 text-white/60">Équité à la fin</td>
              <td
                className={`px-2 py-1 text-right font-mono tabular-nums ${scenario.equite_a_la_fin >= 0 ? "text-emerald-300" : "text-rose-300"}`}
              >
                {_fmtMoneyDetail(scenario.equite_a_la_fin)}
              </td>
            </tr>
          ) : null}
          {scenario.cashflow_annuel != null ? (
            <tr className="border-t border-brand-800/60">
              <td className="px-2 py-1 text-white/60">Cashflow annuel</td>
              <td
                className={`px-2 py-1 text-right font-mono tabular-nums ${scenario.cashflow_annuel >= 0 ? "text-emerald-300" : "text-rose-300"}`}
              >
                {_fmtMoneyDetail(scenario.cashflow_annuel)}
              </td>
            </tr>
          ) : null}
        </tbody>
      </table>
    </div>
  );
}

function BestRefiSubsection({ data }: { data: AnalysisResults }) {
  return (
    <div className="mt-4">
      <h4 className="text-[10px] font-semibold uppercase tracking-wider text-accent-500">
        E · Best refi (scénario retenu)
      </h4>
      <table className="mt-2 w-full">
        <tbody>
          <tr className="border-t border-brand-800/60">
            <td className="px-2 py-1 text-white/60">Programme retenu</td>
            <td className="px-2 py-1 text-right font-mono tabular-nums text-emerald-300">
              {data.best_refi.program}
            </td>
          </tr>
          <tr className="border-t border-brand-800/60">
            <td className="px-2 py-1 font-semibold text-white">
              Montant (équité finale)
            </td>
            <td className="px-2 py-1 text-right font-mono font-bold tabular-nums text-emerald-300">
              {_fmtMoneyDetail(data.best_refi.amount)}
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  );
}

// ─── Phase A3 : Panneau "Validation de l'extraction" ──────────────

const FIELD_LABELS: Record<string, string> = {
  asking_price: "Prix demandé",
  nb_logements: "Nombre de logements",
  revenus_bruts: "Revenus bruts",
  taxes_municipales: "Taxes municipales",
  taxes_scolaires: "Taxes scolaires",
  assurances: "Assurances",
  energie: "Énergie",
  evaluation_municipale: "Évaluation municipale",
  superficie_terrain: "Superficie terrain",
  superficie_batiment: "Superficie bâtiment",
  annee_construction: "Année construction"
};

function _fmtSourceValue(v: number | string | null | undefined): string {
  if (v == null || v === "") return "—";
  if (typeof v === "number") {
    const rounded = Math.round(v);
    const sign = rounded < 0 ? "-" : "";
    const abs = Math.abs(rounded).toString();
    const withSep = abs.replace(/\B(?=(\d{3})+(?!\d))/g, " ");
    return `${sign}${withSep}`;
  }
  return String(v);
}

function ValidationPanel({
  warnings
}: {
  warnings: ValidationWarning[] | null;
}) {
  const list = warnings || [];

  if (list.length === 0) {
    return (
      <section>
        <h3 className="text-[10px] font-semibold uppercase tracking-wider text-accent-500">
          Validation de l&apos;extraction
        </h3>
        <div className="mt-2 flex items-center gap-2 rounded-md border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-xs text-emerald-300">
          <CheckCircle2 className="h-4 w-4 flex-shrink-0" />
          <span>Aucune anomalie détectée sur les champs extraits.</span>
        </div>
      </section>
    );
  }

  return (
    <section>
      <h3 className="text-[10px] font-semibold uppercase tracking-wider text-accent-500">
        Validation de l&apos;extraction ({list.length})
      </h3>
      <ul className="mt-2 space-y-2">
        {list.map((w, i) => {
          const sevCls =
            w.severity === "error"
              ? "border-rose-500/40 bg-rose-500/10 text-rose-300"
              : w.severity === "warning"
              ? "border-amber-500/40 bg-amber-500/10 text-amber-300"
              : "border-blue-500/40 bg-blue-500/10 text-blue-300";
          const Icon =
            w.severity === "error"
              ? Ban
              : w.severity === "warning"
              ? AlertTriangle
              : Info;
          const fieldLabel = FIELD_LABELS[w.field] || w.field;
          const hasSources =
            w.source_local != null ||
            w.source_gemini != null ||
            w.source_claude != null;
          return (
            <li
              key={i}
              className={`rounded-md border px-3 py-2 text-xs ${sevCls}`}
            >
              <div className="flex items-start gap-2">
                <Icon className="mt-0.5 h-4 w-4 flex-shrink-0" />
                <div className="min-w-0 flex-1">
                  <p className="font-semibold">{fieldLabel}</p>
                  <p className="mt-0.5 text-white/80">{w.message}</p>
                  {hasSources ? (
                    <div className="mt-1.5 flex flex-wrap gap-3 text-[10px] text-white/60">
                      {w.source_local != null ? (
                        <span>
                          <span className="font-semibold text-white/70">
                            Local :
                          </span>{" "}
                          <span className="font-mono tabular-nums">
                            {_fmtSourceValue(w.source_local)}
                          </span>
                        </span>
                      ) : null}
                      {w.source_gemini != null ? (
                        <span>
                          <span className="font-semibold text-white/70">
                            Gemini :
                          </span>{" "}
                          <span className="font-mono tabular-nums">
                            {_fmtSourceValue(w.source_gemini)}
                          </span>
                        </span>
                      ) : null}
                      {w.source_claude != null ? (
                        <span>
                          <span className="font-semibold text-white/70">
                            Claude :
                          </span>{" "}
                          <span className="font-mono tabular-nums">
                            {_fmtSourceValue(w.source_claude)}
                          </span>
                        </span>
                      ) : null}
                    </div>
                  ) : null}
                </div>
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

// ─── Badge "Extrait par" + ReExtract buttons ─────────────────────

const EXTRACTION_BADGE_CLS: Record<string, string> = {
  local: "border-slate-500/30 bg-slate-500/10 text-slate-300",
  "local + gemini": "border-blue-500/30 bg-blue-500/10 text-blue-300",
  gemini: "border-violet-500/30 bg-violet-500/10 text-violet-300",
  claude: "border-amber-500/30 bg-amber-500/10 text-amber-300",
  groq: "border-emerald-500/30 bg-emerald-500/10 text-emerald-300",
  none: "border-rose-500/30 bg-rose-500/10 text-rose-300"
};

function extractionBadgeMeta(
  modelUsed: string | null | undefined
): { label: string; cls: string } {
  const m = (modelUsed || "").toLowerCase();
  if (m.startsWith("claude"))
    return { label: "Claude", cls: EXTRACTION_BADGE_CLS.claude };
  if (m.includes("llama") || m.includes("groq"))
    return { label: "Groq", cls: EXTRACTION_BADGE_CLS.groq };
  if (m.startsWith("local + gemini") || m === "local + gemini")
    return {
      label: "Local + Gemini",
      cls: EXTRACTION_BADGE_CLS["local + gemini"]
    };
  if (m.startsWith("gemini"))
    return { label: "Gemini", cls: EXTRACTION_BADGE_CLS.gemini };
  if (m === "local")
    return { label: "Parser local", cls: EXTRACTION_BADGE_CLS.local };
  return { label: "Aucune extraction", cls: EXTRACTION_BADGE_CLS.none };
}

function ExtractionBadgeInline({
  modelUsed
}: {
  modelUsed: string | null | undefined;
}) {
  const meta = extractionBadgeMeta(modelUsed);
  return (
    <span
      title={`Extrait par : ${modelUsed || "aucun modele"}`}
      className={`mt-1 inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 text-[10px] font-medium ${meta.cls}`}
    >
      <Sparkles className="h-3 w-3" />
      Extrait par : {meta.label}
    </span>
  );
}

function ReExtractButtons({
  id,
  hasSources,
  onSuccess
}: {
  id: number;
  hasSources: boolean;
  onSuccess: () => Promise<void>;
}) {
  const confirm = useConfirm();
  const [busyKind, setBusyKind] = useState<"groq" | "claude" | null>(null);
  const [toast, setToast] = useState<{
    text: string;
    kind: "ok" | "err";
  } | null>(null);
  const [claudeEnabled, setClaudeEnabled] = useState<boolean | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const r = await authedFetch(
          "/api/v1/lead-analyses/check-claude-health"
        );
        if (!r.ok) {
          if (!cancelled) setClaudeEnabled(false);
          return;
        }
        const out = (await r.json()) as { enabled?: boolean };
        if (!cancelled) setClaudeEnabled(out.enabled === true);
      } catch {
        if (!cancelled) setClaudeEnabled(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!toast || toast.kind === "err") return;
    const t = setTimeout(() => setToast(null), 6000);
    return () => clearTimeout(t);
  }, [toast]);

  async function runGroq() {
    if (!hasSources || busyKind) return;
    const ok = await confirm({
      title: "Ré-extraire avec Groq ?",
      description:
        "Cette opération est gratuite (Groq Llama 3.3 70B). Groq " +
        "relit les sources originales de la fiche (URLs, texte, PDF/" +
        "images OCR-isés) et remplit les champs vides. Les champs " +
        "déjà saisis ne sont pas écrasés (sauf adresse/ville). " +
        "Continuer ?",
      confirmLabel: "Lancer Groq"
    });
    if (!ok) return;
    setBusyKind("groq");
    setToast(null);
    try {
      const r = await authedFetch(
        `/api/v1/lead-analyses/${id}/re-extract-with-groq`,
        { method: "POST" }
      );
      if (!r.ok) {
        const detail = await r
          .json()
          .then((j: { detail?: string }) => j.detail || `HTTP ${r.status}`)
          .catch(() => `HTTP ${r.status}`);
        const text =
          r.status === 503
            ? `Extraction Groq indisponible : ${detail}`
            : `Ré-extraction Groq échouée (HTTP ${r.status}) : ${detail}`;
        setToast({ text, kind: "err" });
        return;
      }
      const out = (await r.json()) as {
        fields_patched: string[];
        model_used: string;
      };
      await onSuccess();
      const n = out.fields_patched?.length || 0;
      setToast({
        text:
          n > 0
            ? `Champs ré-extraits par Groq (${n}). Vérifie les modifications.`
            : "Groq n'a pas trouvé de nouveaux champs à remplir.",
        kind: "ok"
      });
    } catch (e) {
      setToast({
        text: `Ré-extraction Groq échouée : ${(e as Error).message}`,
        kind: "err"
      });
    } finally {
      setBusyKind(null);
    }
  }

  async function runClaude() {
    if (!hasSources || busyKind) return;
    const ok = await confirm({
      title: "Ré-extraire avec Claude ?",
      description:
        "Cette opération coûte environ 3 cents (Claude Sonnet 4.6, " +
        "multimodal). Claude relit les sources originales et remplit " +
        "les champs vides. Les champs déjà saisis ne sont pas écrasés " +
        "(sauf adresse/ville). Continuer ?",
      confirmLabel: "Lancer Claude (~3¢)"
    });
    if (!ok) return;
    setBusyKind("claude");
    setToast(null);
    try {
      const r = await authedFetch(
        `/api/v1/lead-analyses/${id}/re-extract-with-claude`,
        { method: "POST" }
      );
      if (!r.ok) {
        const detail = await r
          .json()
          .then((j: { detail?: string }) => j.detail || `HTTP ${r.status}`)
          .catch(() => `HTTP ${r.status}`);
        const text =
          r.status === 503
            ? `Extraction Claude indisponible : ${detail}`
            : `Ré-extraction Claude échouée (HTTP ${r.status}) : ${detail}`;
        setToast({ text, kind: "err" });
        return;
      }
      const out = (await r.json()) as {
        fields_patched: string[];
        model_used: string;
      };
      await onSuccess();
      const n = out.fields_patched?.length || 0;
      setToast({
        text:
          n > 0
            ? `Champs ré-extraits par Claude (${n}). Vérifie les modifications.`
            : "Claude n'a pas trouvé de nouveaux champs à remplir.",
        kind: "ok"
      });
    } catch (e) {
      setToast({
        text: `Ré-extraction Claude échouée : ${(e as Error).message}`,
        kind: "err"
      });
    } finally {
      setBusyKind(null);
    }
  }

  const isBusy = busyKind !== null;

  return (
    <div className="flex flex-col items-end gap-1">
      <div className="flex items-center gap-1">
        <button
          type="button"
          onClick={() => void runGroq()}
          disabled={!hasSources || isBusy}
          title={
            hasSources
              ? "Relance Groq Llama 3.3 70B sur les sources originales (gratuit)"
              : "Aucune source à ré-extraire — colle une URL/texte ou ajoute un fichier"
          }
          className="inline-flex items-center gap-1 rounded-md border border-emerald-500/30 bg-emerald-500/10 px-2 py-1 text-[10px] font-medium text-emerald-300 transition hover:bg-emerald-500/20 disabled:cursor-not-allowed disabled:opacity-40"
        >
          {busyKind === "groq" ? (
            <Loader2 className="h-3 w-3 animate-spin" />
          ) : (
            <Sparkles className="h-3 w-3" />
          )}
          Ré-extraire avec Groq
        </button>
        {claudeEnabled === true ? (
          <button
            type="button"
            onClick={() => void runClaude()}
            disabled={!hasSources || isBusy}
            title={
              hasSources
                ? "Relance Claude Sonnet 4.6 (~3¢) — uniquement si tu veux comparer"
                : "Aucune source à ré-extraire"
            }
            className="inline-flex items-center gap-1 rounded-md border border-amber-500/30 bg-amber-500/10 px-2 py-1 text-[10px] font-medium text-amber-300 transition hover:bg-amber-500/20 disabled:cursor-not-allowed disabled:opacity-40"
          >
            {busyKind === "claude" ? (
              <Loader2 className="h-3 w-3 animate-spin" />
            ) : (
              <Sparkles className="h-3 w-3" />
            )}
            Claude (~3¢)
          </button>
        ) : null}
      </div>
      {toast ? (
        <div
          className={`mt-1 flex max-w-[320px] items-start gap-1 rounded-md border px-2 py-1 text-right text-[10px] ${
            toast.kind === "ok"
              ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-300"
              : "border-rose-500/40 bg-rose-500/10 text-rose-300"
          }`}
        >
          <p className="flex-1 whitespace-pre-line text-left">{toast.text}</p>
          {toast.kind === "err" ? (
            <button
              type="button"
              onClick={() => setToast(null)}
              aria-label="Fermer le message"
              className="ml-1 shrink-0 text-rose-300 hover:text-rose-100"
            >
              ✕
            </button>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

