"use client";

import { useEffect, useState } from "react";
import { Loader2, X, FileDown } from "lucide-react";

import { authedFetch } from "@/lib/auth";

/**
 * Wizard de génération d'une offre d'investissement .pptx pour une
 * `LeadAnalysis`. v3 (2026-05-28) — corrections slide-par-slide après
 * tests de Phil sur 1660 + 5271 :
 *
 *   1. **Champs auto-remplis** (read-only) — Phil vérifie les chiffres
 *      qui seront injectés dans le template.
 *   2. **Cover + branding** : qualificatif projet + tagline.
 *   2bis. **Présentation projet** (slide 3) : nb_etages (manuel).
 *      Superficie, année, frais énergétiques, stationnements → auto
 *      depuis la fiche.
 *   3. **Opportunité unique** (slide 4) : 4 bullets + levier principal
 *      + gain $ + lien Centris comparable (v3). Charts auto-substitués.
 *   4. **Plan création de valeur** (slide 5) : annotation valeur
 *      marchande. Source : `analysis.best_refi.valeur_economique`.
 *   5. **Échéancier** (slide 6) : phase 2 label + 5 dates jalons
 *      override (M1.1, M1.2, M2.1, M2.4, M3.1). Auto-suggérées selon
 *      stratégies value-add cochées.
 *   6. **Stratégie value-add** (slides 9 + 10) : rénos + flags + SCHL.
 *      Totaux rénos = `analysis.travaux_estimes`. Frais détaillés =
 *      `analysis.frais_developpement` + `frais_negociations` + autres.
 *   6bis. **ROI estimation long terme** (slide 11) : callout libre.
 *   7. **Tendances** (slide 12) : titre dynamique + Zipplex auto-lookup
 *      (override callout + moyenne possible). Chart auto-substitué.
 *   8. **Photos** : 4 slots (cover, extérieur, carte, tendances).
 *
 * Au submit, POST `/api/v1/lead-analyses/{id}/offre-investissement` et
 * download du `.pptx` retourné (audit log avec `service_version: "v3"`).
 */

type AutoFilledRow = { label: string; value: string };

const QUALIFICATIFS_SUGGESTED = [
  "solide",
  "durable",
  "rentable",
  "stratégique",
  "prometteur",
  "structurant",
];

const PROGRAMME_SCHL_OPTIONS = [
  { value: "aph_50", label: "APH 50 pts (efficacité énergétique)" },
  { value: "aph_100", label: "APH 100 pts (abordabilité + efficacité)" },
  { value: "aucun", label: "Aucun (SCHL standard)" },
];

const CONVERSION_CHAUFFAGE_OPTIONS = [
  { value: "aucun", label: "Aucun" },
  { value: "gaz_to_elec", label: "Gaz → Électrique" },
  { value: "elec_to_thermo", label: "Électrique → Thermopompe" },
];

// Catalogue par défaut — surchargé au mount par GET
// /lead-analyses/offre-investissement/catalogue-renovations. La copie
// statique sert de fallback si le fetch échoue (offline, tests).
const RENOVATIONS_DEFAULT_CATALOGUE = [
  "Fondation",
  "Brique",
  "Portes/fenêtres",
  "Balcons/escaliers",
  "Sous-sol",
  "Toit/sous-toit",
  "Drain entrée extérieur",
  "Chauffe-eau",
  "Panneau électrique à vérifier et corriger",
  "Finir appartement",
  "Rénovations intérieures générales",
  "Entretien extérieur général",
  "Détecteur de fumée et monoxydes",
  "Vermines",
  "Rajout d'un mur",
  "Conversion chauffage",
  "Insonorisation",
  "Plomberie majeure",
  "Électricité majeure",
  "Cuisine complète",
  "Salle de bain complète"
];

export type OffreInvestissementWizardData = {
  /** Champs auto extraits du LeadAnalysis (pour affichage seul). */
  autoFilled: AutoFilledRow[];
  /** Suggestions pré-remplies pour les bullets (basées sur les chiffres). */
  bulletSuggestions: { b1: string; b2: string; b3: string; b4: string };
  /** Quartier estimé (city) pour le tagline. */
  quartier: string;
  /** Gain potentiel auto-calculé (delta valeur marchande). */
  gainPotentielAuto?: number | null;
  /** Liste des attachments existants (photo seulement) à proposer. */
  existingPhotos: Array<{
    id: number;
    filename: string;
    content_type: string;
  }>;
};

export function OffreInvestissementWizard({
  open,
  onClose,
  analysisId,
  data,
}: {
  open: boolean;
  onClose: () => void;
  analysisId: number;
  data: OffreInvestissementWizardData;
}) {
  const [tagline, setTagline] = useState("");
  const [qualificatifProjet, setQualificatifProjet] = useState("solide");
  const [b1, setB1] = useState("");
  const [b2, setB2] = useState("");
  const [b3, setB3] = useState(""); // legacy = levierPrincipal
  const [b4, setB4] = useState("");
  const [levierPrincipalPhrase, setLevierPrincipalPhrase] = useState("");
  const [gainPotentielCallout, setGainPotentielCallout] = useState("");
  const [gainPotentielAuto, setGainPotentielAuto] = useState(true);
  const [lienCentrisComparable, setLienCentrisComparable] = useState("");
  const [valeurComparableCentris, setValeurComparableCentris] = useState<number>(0);
  const [valeurMarchandeAnnotation, setValeurMarchandeAnnotation] = useState("");
  const [phase2Label, setPhase2Label] = useState("");

  // Slide 3 — Présentation du projet (v3)
  const [nbEtages, setNbEtages] = useState<number>(3);

  // Slide 6 — Échéancier : 5 dates override (ISO yyyy-mm-dd)
  const [dateM11, setDateM11] = useState("");
  const [dateM12, setDateM12] = useState("");
  const [dateM21, setDateM21] = useState("");
  const [dateM24, setDateM24] = useState("");
  const [dateM31, setDateM31] = useState("");

  // Slide 11 — ROI : callout estimation long terme
  const [estimationLongTermeCallout, setEstimationLongTermeCallout] = useState("");

  // Slide 12 — Tendances : override callout (sinon Zipplex auto)
  const [tendancesCalloutManuel, setTendancesCalloutManuel] = useState("");
  const [tendancesMoyenneActuelle, setTendancesMoyenneActuelle] = useState<number>(0);

  // value-add flags
  const [conversionChambres, setConversionChambres] = useState(false);
  const [nbChambresTotal, setNbChambresTotal] = useState<number>(0);
  const [loyerParChambre, setLoyerParChambre] = useState<number>(0);
  const [conversionChauffage, setConversionChauffage] = useState<
    "aucun" | "gaz_to_elec" | "elec_to_thermo"
  >("aucun");
  const [ajoutLogementType, setAjoutLogementType] = useState("");
  const [ajoutLogementLoyer, setAjoutLogementLoyer] = useState<number>(0);
  const [optimisationLoyersStd, setOptimisationLoyersStd] = useState(true);
  const [programmeSchl, setProgrammeSchl] = useState<
    "aph_50" | "aph_100" | "aucun"
  >("aph_50");
  const [ajoutThermopompes, setAjoutThermopompes] = useState<number>(0);
  const [ajoutWifi, setAjoutWifi] = useState(false);

  // Catalogue rénovations (v2) — chargé via API au mount
  const [renovationsCatalogue, setRenovationsCatalogue] = useState<string[]>(
    RENOVATIONS_DEFAULT_CATALOGUE
  );
  const [renovationsSelectionnees, setRenovationsSelectionnees] = useState<
    Set<string>
  >(new Set());
  const [autresRenovations, setAutresRenovations] = useState("");

  // Tendances slide 12 (v2)
  const [tendancesCallout, setTendancesCallout] = useState("");

  // Photos (4 slots en v2 : cover, exterieur, carte, tendances)
  const [photoCoverBase64, setPhotoCoverBase64] = useState<string | null>(null);
  const [photoExterieurBase64, setPhotoExterieurBase64] = useState<
    string | null
  >(null);
  const [photoCarteBase64, setPhotoCarteBase64] = useState<string | null>(null);
  const [photoTendancesBase64, setPhotoTendancesBase64] = useState<
    string | null
  >(null);
  const [photoCoverAttachId, setPhotoCoverAttachId] = useState<number | null>(
    null
  );
  const [photoExtAttachId, setPhotoExtAttachId] = useState<number | null>(null);
  const [photoCarteAttachId, setPhotoCarteAttachId] = useState<number | null>(
    null
  );
  const [photoTendancesAttachId, setPhotoTendancesAttachId] = useState<
    number | null
  >(null);

  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState<{ text: string; kind: "ok" | "err" } | null>(
    null
  );

  // Reset state when wizard opens
  useEffect(() => {
    if (!open) return;
    setQualificatifProjet("solide");
    setTagline(
      `De l'achat au refinancement : un projet immobilier solide à ${
        data.quartier || "Montréal"
      }`
    );
    setB1(data.bulletSuggestions.b1);
    setB2(data.bulletSuggestions.b2);
    setLevierPrincipalPhrase(data.bulletSuggestions.b3);
    setB3(data.bulletSuggestions.b3);
    setB4(data.bulletSuggestions.b4);
    setGainPotentielCallout("");
    setGainPotentielAuto(true);
    setLienCentrisComparable("");
    setValeurMarchandeAnnotation("");
    setPhase2Label("");
    setNbEtages(3);
    setDateM11("");
    setDateM12("");
    setDateM21("");
    setDateM24("");
    setDateM31("");
    setEstimationLongTermeCallout("");
    setTendancesCalloutManuel("");
    setTendancesMoyenneActuelle(0);
    setRenovationsSelectionnees(new Set());
    setAutresRenovations("");
    setTendancesCallout("");
    setToast(null);
  }, [open, data]);

  // Re-génère la tagline quand qualificatif change (si non personnalisée)
  useEffect(() => {
    if (!open) return;
    const expected = `De l'achat au refinancement : un projet immobilier {q} à ${
      data.quartier || "Montréal"
    }`;
    // Si la tagline est encore au format auto-généré, on l'update
    const re = new RegExp(
      "^De l'achat au refinancement : un projet immobilier \\w+ à "
    );
    if (re.test(tagline)) {
      setTagline(expected.replace("{q}", qualificatifProjet));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [qualificatifProjet]);

  // Auto-suggère phase2Label selon les flags value-add
  useEffect(() => {
    if (!open) return;
    if (phase2Label) return; // override manuel — ne pas écraser
    if (conversionChambres) setPhase2Label("Création chambres");
    else if (conversionChauffage && conversionChauffage !== "aucun")
      setPhase2Label("Conversion chauffage");
    else setPhase2Label("Rencontres");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [conversionChambres, conversionChauffage, open]);

  // Charge le catalogue de rénovations depuis l'API
  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    void (async () => {
      try {
        const r = await authedFetch(
          "/api/v1/lead-analyses/offre-investissement/catalogue-renovations"
        );
        if (!r.ok) return;
        const j: { items?: string[] } = await r.json();
        if (cancelled) return;
        if (Array.isArray(j.items) && j.items.length > 0) {
          setRenovationsCatalogue(j.items);
        }
      } catch {
        // Silencieux : fallback sur le catalogue par défaut.
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [open]);

  function toggleRenovation(item: string) {
    setRenovationsSelectionnees((prev) => {
      const next = new Set(prev);
      if (next.has(item)) next.delete(item);
      else next.add(item);
      return next;
    });
  }

  useEffect(() => {
    if (!toast || toast.kind === "err") return;
    const t = setTimeout(() => setToast(null), 4000);
    return () => clearTimeout(t);
  }, [toast]);

  async function fileToBase64(file: File): Promise<string> {
    return new Promise((resolve, reject) => {
      const r = new FileReader();
      r.onload = () => {
        const result = r.result as string;
        // Strip data:image/...;base64, prefix
        const comma = result.indexOf(",");
        resolve(comma >= 0 ? result.slice(comma + 1) : result);
      };
      r.onerror = () => reject(r.error);
      r.readAsDataURL(file);
    });
  }

  function handlePhotoChange(
    slot: "cover" | "exterieur" | "carte" | "tendances",
    file: File | null
  ) {
    if (!file) return;
    void fileToBase64(file).then((b64) => {
      if (slot === "cover") {
        setPhotoCoverBase64(b64);
        setPhotoCoverAttachId(null);
      } else if (slot === "exterieur") {
        setPhotoExterieurBase64(b64);
        setPhotoExtAttachId(null);
      } else if (slot === "carte") {
        setPhotoCarteBase64(b64);
        setPhotoCarteAttachId(null);
      } else {
        setPhotoTendancesBase64(b64);
        setPhotoTendancesAttachId(null);
      }
    });
  }

  function buildPhotosPayload(): Array<{
    base64_data?: string;
    attachment_id?: number;
  }> {
    const photos: Array<{ base64_data?: string; attachment_id?: number }> = [];
    if (photoCoverBase64) photos.push({ base64_data: photoCoverBase64 });
    else if (photoCoverAttachId !== null)
      photos.push({ attachment_id: photoCoverAttachId });
    else photos.push({});

    if (photoExterieurBase64) photos.push({ base64_data: photoExterieurBase64 });
    else if (photoExtAttachId !== null)
      photos.push({ attachment_id: photoExtAttachId });
    else photos.push({});

    if (photoCarteBase64) photos.push({ base64_data: photoCarteBase64 });
    else if (photoCarteAttachId !== null)
      photos.push({ attachment_id: photoCarteAttachId });
    else photos.push({});

    if (photoTendancesBase64)
      photos.push({ base64_data: photoTendancesBase64 });
    else if (photoTendancesAttachId !== null)
      photos.push({ attachment_id: photoTendancesAttachId });
    else photos.push({});

    return photos.filter(
      (p) => p.base64_data !== undefined || p.attachment_id !== undefined
    );
  }

  async function handleGenerate() {
    if (busy) return;
    setBusy(true);
    setToast(null);
    try {
      const body = {
        value_add_strategy: {
          tagline_cover: tagline,
          qualificatif_projet: qualificatifProjet,
          bullet_opp_1: b1,
          bullet_opp_2: b2,
          levier_principal_phrase: levierPrincipalPhrase || b3,
          bullet_opp_3: levierPrincipalPhrase || b3, // alias backward-compat
          bullet_opp_4: b4,
          gain_potentiel_callout: gainPotentielCallout,
          gain_potentiel_auto: gainPotentielAuto,
          lien_centris_comparable: lienCentrisComparable,
          valeur_comparable_centris: valeurComparableCentris,
          valeur_marchande_annotation: valeurMarchandeAnnotation,
          phase2_label: phase2Label,
          nb_etages: nbEtages,
          date_m1_1: dateM11,
          date_m1_2: dateM12,
          date_m2_1: dateM21,
          date_m2_4: dateM24,
          date_m3_1: dateM31,
          conversion_chambres: conversionChambres,
          nb_chambres_total: nbChambresTotal,
          loyer_par_chambre: loyerParChambre,
          conversion_chauffage: conversionChauffage,
          ajout_logement_type: ajoutLogementType,
          ajout_logement_loyer: ajoutLogementLoyer,
          optimisation_loyers_std: optimisationLoyersStd,
          programme_schl: programmeSchl,
          ajout_thermopompes: ajoutThermopompes,
          ajout_wifi: ajoutWifi,
          renovations_selectionnees: Array.from(renovationsSelectionnees),
          autres_renovations: autresRenovations,
          estimation_long_terme_callout: estimationLongTermeCallout,
          tendances_callout: tendancesCallout,
          tendances_callout_manuel: tendancesCalloutManuel,
          tendances_moyenne_actuelle: tendancesMoyenneActuelle,
        },
        photos: buildPhotosPayload(),
      };
      const r = await authedFetch(
        `/api/v1/lead-analyses/${analysisId}/offre-investissement`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        }
      );
      if (!r.ok) {
        const detail = await r
          .json()
          .then((j: { detail?: string }) => j.detail || `HTTP ${r.status}`)
          .catch(() => `HTTP ${r.status}`);
        setToast({
          text: `Génération offre échouée : ${detail}`,
          kind: "err",
        });
        return;
      }
      const blob = await r.blob();
      const url = URL.createObjectURL(blob);
      // Trigger download
      const a = document.createElement("a");
      a.href = url;
      // Try to read filename from Content-Disposition
      const cd = r.headers.get("Content-Disposition") || "";
      const m = cd.match(/filename="?([^";]+)"?/);
      a.download = m ? m[1] : "Offre_Investissement.pptx";
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
      setToast({ text: "Offre .pptx générée.", kind: "ok" });
    } catch (e) {
      setToast({
        text: `Génération offre échouée : ${(e as Error).message}`,
        kind: "err",
      });
    } finally {
      setBusy(false);
    }
  }

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-[60] flex items-end justify-center bg-black/70 px-2 py-4 sm:items-center"
      onClick={onClose}
    >
      <div
        className="flex max-h-[calc(100vh-2rem)] w-full max-w-4xl flex-col overflow-hidden rounded-2xl border border-brand-800 bg-brand-950"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="flex flex-shrink-0 items-start justify-between gap-3 border-b border-brand-800 px-5 py-4">
          <div className="min-w-0 flex-1">
            <p className="text-[10px] uppercase tracking-wider text-emerald-400">
              Génération d&apos;offre d&apos;investissement
            </p>
            <h2 className="mt-0.5 text-base font-bold text-white">
              Template Horizon v2 — 16 slides (service v3 : charts dynamiques + auto-calculs)
            </h2>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md p-1 text-white/60 hover:bg-brand-900 hover:text-white"
            aria-label="Fermer"
          >
            <X className="h-4 w-4" />
          </button>
        </header>

        {toast ? (
          <div
            className={`flex items-start gap-2 border-b border-brand-800 px-5 py-2 text-[11px] ${
              toast.kind === "ok"
                ? "bg-emerald-500/10 text-emerald-300"
                : "bg-rose-500/10 text-rose-300"
            }`}
          >
            <span className="flex-1 whitespace-pre-line">{toast.text}</span>
          </div>
        ) : null}

        <div className="flex-1 overflow-y-auto px-5 py-4">
          {/* Section 1 — Auto-filled */}
          <section className="mb-6">
            <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-emerald-300">
              1. Champs auto-remplis depuis la fiche
            </h3>
            <p className="mb-3 text-[11px] text-white/60">
              Ces valeurs seront injectées dans le template. Si l&apos;une
              d&apos;elles est incorrecte, corrige-la d&apos;abord dans la
              fiche.
            </p>
            <div className="overflow-x-auto rounded-lg border border-brand-800">
              <table className="min-w-full text-[11px]">
                <tbody>
                  {data.autoFilled.map((row) => (
                    <tr
                      key={row.label}
                      className="border-b border-brand-800/50 last:border-b-0"
                    >
                      <td className="bg-brand-900/30 px-3 py-1.5 text-white/70">
                        {row.label}
                      </td>
                      <td className="px-3 py-1.5 text-right font-mono tabular-nums text-white">
                        {row.value}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          {/* Section 2 — Cover + branding */}
          <section className="mb-6">
            <h3 className="mb-3 text-xs font-semibold uppercase tracking-wider text-emerald-300">
              2. Cover &amp; branding
            </h3>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <label className="block">
                <span className="mb-1 block text-[11px] font-medium text-white/80">
                  Qualificatif du projet (adjectif)
                </span>
                <input
                  type="text"
                  list="qualificatif-suggestions"
                  value={qualificatifProjet}
                  onChange={(e) => setQualificatifProjet(e.target.value)}
                  maxLength={30}
                  placeholder="solide, durable, rentable, ..."
                  className="w-full rounded-md border border-brand-800 bg-brand-900/50 px-3 py-2 text-xs text-white placeholder-white/30 focus:border-emerald-500/50 focus:outline-none"
                />
                <datalist id="qualificatif-suggestions">
                  {QUALIFICATIFS_SUGGESTED.map((q) => (
                    <option key={q} value={q} />
                  ))}
                </datalist>
              </label>
              <label className="block sm:col-span-2">
                <span className="mb-1 block text-[11px] font-medium text-white/80">
                  Tagline cover (auto-généré, modifiable)
                </span>
                <textarea
                  value={tagline}
                  onChange={(e) => setTagline(e.target.value)}
                  rows={2}
                  maxLength={200}
                  className="w-full rounded-md border border-brand-800 bg-brand-900/50 px-3 py-2 text-xs text-white placeholder-white/30 focus:border-emerald-500/50 focus:outline-none"
                />
              </label>
            </div>
          </section>

          {/* Section 2bis — Présentation du projet (v3) */}
          <section className="mb-6">
            <h3 className="mb-3 text-xs font-semibold uppercase tracking-wider text-emerald-300">
              2bis. Présentation du projet (slide 3)
            </h3>
            <p className="mb-2 text-[11px] text-white/60">
              Superficie habitable, année de construction, frais
              énergétiques et stationnements sont auto-remplis depuis la
              fiche. Seul le nombre d&apos;étages doit être saisi (varie
              entre 2 et 5 selon le deal).
            </p>
            <label className="block max-w-[200px]">
              <span className="mb-1 block text-[11px] font-medium text-white/80">
                Nombre d&apos;étages
              </span>
              <input
                type="number"
                min={1}
                max={10}
                value={nbEtages}
                onChange={(e) => setNbEtages(Number(e.target.value) || 0)}
                className="w-full rounded-md border border-brand-800 bg-brand-900/50 px-3 py-2 text-xs text-white focus:border-emerald-500/50 focus:outline-none"
              />
            </label>
          </section>

          {/* Section 3 — Opportunité unique */}
          <section className="mb-6">
            <h3 className="mb-3 text-xs font-semibold uppercase tracking-wider text-emerald-300">
              3. Opportunité unique (slide 4)
            </h3>
            <div className="mb-3 grid grid-cols-1 gap-2 sm:grid-cols-2">
              {[
                { v: b1, set: setB1, label: "Bullet opportunité 1" },
                { v: b2, set: setB2, label: "Bullet opportunité 2" },
                {
                  v: levierPrincipalPhrase,
                  set: setLevierPrincipalPhrase,
                  label: "Levier principal (phrase 1 ligne)"
                },
                { v: b4, set: setB4, label: "Bullet opportunité 4" }
              ].map((b) => (
                <label key={b.label} className="block">
                  <span className="mb-1 block text-[11px] font-medium text-white/80">
                    {b.label}
                  </span>
                  <textarea
                    value={b.v}
                    onChange={(e) => b.set(e.target.value)}
                    rows={2}
                    maxLength={150}
                    className="w-full rounded-md border border-brand-800 bg-brand-900/50 px-3 py-2 text-[11px] text-white placeholder-white/30 focus:border-emerald-500/50 focus:outline-none"
                  />
                </label>
              ))}
            </div>
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
              <label className="block sm:col-span-2">
                <span className="mb-1 block text-[11px] font-medium text-white/80">
                  Gain potentiel callout (slide 4 — gros chiffre)
                </span>
                <input
                  type="text"
                  value={gainPotentielCallout}
                  onChange={(e) => setGainPotentielCallout(e.target.value)}
                  disabled={gainPotentielAuto}
                  placeholder={
                    gainPotentielAuto
                      ? "Auto-calculé depuis l'analyse financière"
                      : "ex: + 497 100$"
                  }
                  className="w-full rounded-md border border-brand-800 bg-brand-900/50 px-3 py-2 text-xs text-white placeholder-white/30 focus:border-emerald-500/50 focus:outline-none disabled:opacity-50"
                />
              </label>
              <label className="flex items-end gap-2 text-[11px] text-white/80 pb-2">
                <input
                  type="checkbox"
                  checked={gainPotentielAuto}
                  onChange={(e) => setGainPotentielAuto(e.target.checked)}
                  className="h-3 w-3"
                />
                <span>Auto-calculer</span>
              </label>
            </div>
            <div className="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-2">
              <label className="block">
                <span className="mb-1 block text-[11px] font-medium text-white/80">
                  Lien Centris d&apos;un comparable (URL)
                </span>
                <input
                  type="url"
                  value={lienCentrisComparable}
                  onChange={(e) => setLienCentrisComparable(e.target.value)}
                  maxLength={500}
                  placeholder="https://www.centris.ca/fr/..."
                  className="w-full rounded-md border border-brand-800 bg-brand-900/50 px-3 py-2 text-xs text-white placeholder-white/30 focus:border-emerald-500/50 focus:outline-none"
                />
                <span className="mt-1 block text-[10px] text-white/40">
                  Inséré dans la phrase « Similaire en vente à X M$ ... ».
                </span>
              </label>
              <label className="block">
                <span className="mb-1 block text-[11px] font-medium text-white/80">
                  Valeur du comparable Centris ($)
                </span>
                <input
                  type="number"
                  value={valeurComparableCentris || ""}
                  onChange={(e) =>
                    setValeurComparableCentris(Number(e.target.value) || 0)
                  }
                  min={0}
                  step={10000}
                  placeholder="ex: 2000000"
                  className="w-full rounded-md border border-brand-800 bg-brand-900/50 px-3 py-2 text-xs text-white placeholder-white/30 focus:border-emerald-500/50 focus:outline-none"
                />
                <span className="mt-1 block text-[10px] text-white/40">
                  Alimente le graphique « Profit à l&apos;achat » (barre rouge = écart vs prix payé). Si vide, fallback évaluation municipale.
                </span>
              </label>
            </div>
          </section>

          {/* Section 4 — Plan création de valeur */}
          <section className="mb-6">
            <h3 className="mb-3 text-xs font-semibold uppercase tracking-wider text-emerald-300">
              4. Plan création de valeur (slide 5)
            </h3>
            <label className="block">
              <span className="mb-1 block text-[11px] font-medium text-white/80">
                Annotation valeur marchande (optionnel)
              </span>
              <input
                type="text"
                value={valeurMarchandeAnnotation}
                onChange={(e) =>
                  setValeurMarchandeAnnotation(e.target.value)
                }
                maxLength={80}
                placeholder="ex: (payé 1.2M), Payé 1 100 000$"
                className="w-full rounded-md border border-brand-800 bg-brand-900/50 px-3 py-2 text-xs text-white placeholder-white/30 focus:border-emerald-500/50 focus:outline-none"
              />
            </label>
          </section>

          {/* Section 5 — Échéancier */}
          <section className="mb-6">
            <h3 className="mb-3 text-xs font-semibold uppercase tracking-wider text-emerald-300">
              5. Échéancier — Gantt (slide 6)
            </h3>
            <label className="mb-3 block">
              <span className="mb-1 block text-[11px] font-medium text-white/80">
                Libellé phase 2 (auto-suggéré selon les leviers cochés)
              </span>
              <input
                type="text"
                value={phase2Label}
                onChange={(e) => setPhase2Label(e.target.value)}
                maxLength={40}
                placeholder="ex: Création chambres, Travaux et rénovations, Conversion chauffage"
                className="w-full rounded-md border border-brand-800 bg-brand-900/50 px-3 py-2 text-xs text-white placeholder-white/30 focus:border-emerald-500/50 focus:outline-none"
              />
            </label>
            <div className="rounded-lg border border-brand-800 p-3">
              <p className="mb-2 text-[11px] text-white/70">
                Dates des jalons — auto-suggérées d&apos;après les
                stratégies cochées ci-dessous. Override possible.
                Laisser vide = auto.
              </p>
              <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
                {[
                  { v: dateM11, set: setDateM11, label: "M1.1 — Lettre de financement" },
                  { v: dateM12, set: setDateM12, label: "M1.2 — Passage au notaire" },
                  { v: dateM21, set: setDateM21, label: "M2.1 — Fin création chambres" },
                  { v: dateM24, set: setDateM24, label: "M2.4 — Fin travaux / stabilisation" },
                  { v: dateM31, set: setDateM31, label: "M3.1 — Remboursement partenaires" }
                ].map((d) => (
                  <label key={d.label} className="block">
                    <span className="mb-1 block text-[10px] font-medium text-white/70">
                      {d.label}
                    </span>
                    <input
                      type="date"
                      value={d.v}
                      onChange={(e) => d.set(e.target.value)}
                      className="w-full rounded-md border border-brand-800 bg-brand-900/50 px-2 py-1.5 text-[11px] text-white focus:border-emerald-500/50 focus:outline-none"
                    />
                  </label>
                ))}
              </div>
            </div>
          </section>

          {/* Section 6 — Stratégie value-add */}
          <section className="mb-6">
            <h3 className="mb-3 text-xs font-semibold uppercase tracking-wider text-emerald-300">
              6. Stratégie value-add (slides 9 + 10)
            </h3>

            <div className="mb-3 rounded-lg border border-brand-800 p-3">
              <h4 className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-white/70">
                Catalogue rénovations (slide 9)
              </h4>
              <div className="grid grid-cols-1 gap-x-3 gap-y-1 sm:grid-cols-2">
                {renovationsCatalogue.map((item) => (
                  <label
                    key={item}
                    className="flex items-center gap-2 text-[11px] text-white/80"
                  >
                    <input
                      type="checkbox"
                      checked={renovationsSelectionnees.has(item)}
                      onChange={() => toggleRenovation(item)}
                      className="h-3 w-3"
                    />
                    <span>{item}</span>
                  </label>
                ))}
              </div>
              <label className="mt-2 block">
                <span className="mb-1 block text-[11px] font-medium text-white/80">
                  Autres rénovations (1 par ligne)
                </span>
                <textarea
                  value={autresRenovations}
                  onChange={(e) => setAutresRenovations(e.target.value)}
                  rows={2}
                  placeholder={"ex: Finir appartement 5½\nIsolation toiture"}
                  className="w-full rounded-md border border-brand-800 bg-brand-900/50 px-3 py-2 text-[11px] text-white placeholder-white/30 focus:border-emerald-500/50 focus:outline-none"
                />
              </label>
            </div>

            <div className="mb-3 rounded-lg border border-brand-800 p-3">
              <h4 className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-white/70">
                Leviers value-add (slide 10)
              </h4>

              <label className="mb-2 flex items-center gap-2 text-[11px] text-white/80">
                <input
                  type="checkbox"
                  checked={conversionChambres}
                  onChange={(e) => setConversionChambres(e.target.checked)}
                  className="h-3 w-3"
                />
                <span>Conversion en chambres</span>
              </label>
              {conversionChambres ? (
                <div className="mb-3 ml-5 grid grid-cols-1 gap-2 sm:grid-cols-2">
                  <label className="block text-[11px] text-white/70">
                    <span>Nb chambres totales projetées</span>
                    <input
                      type="number"
                      value={nbChambresTotal}
                      onChange={(e) =>
                        setNbChambresTotal(Number(e.target.value))
                      }
                      className="mt-1 w-full rounded-md border border-brand-800 bg-brand-900/50 px-2 py-1 text-xs text-white"
                    />
                  </label>
                  <label className="block text-[11px] text-white/70">
                    <span>Loyer / chambre ($/mois)</span>
                    <input
                      type="number"
                      value={loyerParChambre}
                      onChange={(e) =>
                        setLoyerParChambre(Number(e.target.value))
                      }
                      className="mt-1 w-full rounded-md border border-brand-800 bg-brand-900/50 px-2 py-1 text-xs text-white"
                    />
                  </label>
                </div>
              ) : null}

              <label className="mb-2 flex items-center gap-2 text-[11px] text-white/80">
                <span className="w-44">Conversion chauffage</span>
                <select
                  value={conversionChauffage}
                  onChange={(e) =>
                    setConversionChauffage(
                      e.target.value as
                        | "aucun"
                        | "gaz_to_elec"
                        | "elec_to_thermo"
                    )
                  }
                  className="flex-1 rounded-md border border-brand-800 bg-brand-900/50 px-2 py-1 text-xs text-white"
                >
                  {CONVERSION_CHAUFFAGE_OPTIONS.map((opt) => (
                    <option key={opt.value} value={opt.value}>
                      {opt.label}
                    </option>
                  ))}
                </select>
              </label>

              <div className="mb-2 grid grid-cols-1 gap-2 sm:grid-cols-2">
                <label className="block text-[11px] text-white/70">
                  <span>Ajout d&apos;un logement — type</span>
                  <input
                    type="text"
                    value={ajoutLogementType}
                    onChange={(e) => setAjoutLogementType(e.target.value)}
                    placeholder="ex: 3.5 / aucun"
                    className="mt-1 w-full rounded-md border border-brand-800 bg-brand-900/50 px-2 py-1 text-xs text-white placeholder-white/30"
                  />
                </label>
                <label className="block text-[11px] text-white/70">
                  <span>Loyer projeté du logement ajouté</span>
                  <input
                    type="number"
                    value={ajoutLogementLoyer}
                    onChange={(e) =>
                      setAjoutLogementLoyer(Number(e.target.value))
                    }
                    className="mt-1 w-full rounded-md border border-brand-800 bg-brand-900/50 px-2 py-1 text-xs text-white"
                  />
                </label>
              </div>

              <label className="mb-2 flex items-center gap-2 text-[11px] text-white/80">
                <input
                  type="checkbox"
                  checked={optimisationLoyersStd}
                  onChange={(e) =>
                    setOptimisationLoyersStd(e.target.checked)
                  }
                  className="h-3 w-3"
                />
                <span>Optimisation loyers standard</span>
              </label>

              <label className="mb-2 flex items-center gap-2 text-[11px] text-white/80">
                <span className="w-44">Programme SCHL</span>
                <select
                  value={programmeSchl}
                  onChange={(e) =>
                    setProgrammeSchl(
                      e.target.value as "aph_50" | "aph_100" | "aucun"
                    )
                  }
                  className="flex-1 rounded-md border border-brand-800 bg-brand-900/50 px-2 py-1 text-xs text-white"
                >
                  {PROGRAMME_SCHL_OPTIONS.map((opt) => (
                    <option key={opt.value} value={opt.value}>
                      {opt.label}
                    </option>
                  ))}
                </select>
              </label>

              <div className="mb-2 grid grid-cols-1 gap-2 sm:grid-cols-2">
                <label className="block text-[11px] text-white/70">
                  <span>Nb thermopompes ajoutées</span>
                  <input
                    type="number"
                    value={ajoutThermopompes}
                    onChange={(e) =>
                      setAjoutThermopompes(Number(e.target.value))
                    }
                    className="mt-1 w-full rounded-md border border-brand-800 bg-brand-900/50 px-2 py-1 text-xs text-white"
                  />
                </label>
                <label className="flex items-center gap-2 text-[11px] text-white/80">
                  <input
                    type="checkbox"
                    checked={ajoutWifi}
                    onChange={(e) => setAjoutWifi(e.target.checked)}
                    className="h-3 w-3"
                  />
                  <span>Ajout WiFi</span>
                </label>
              </div>
            </div>
          </section>

          {/* Section 6bis — ROI : estimation long terme (slide 11) */}
          <section className="mb-6">
            <h3 className="mb-3 text-xs font-semibold uppercase tracking-wider text-emerald-300">
              6bis. ROI — estimation long terme (slide 11)
            </h3>
            <label className="block">
              <span className="mb-1 block text-[11px] font-medium text-white/80">
                Callout estimation long terme (bulle de la slide 11)
              </span>
              <input
                type="text"
                value={estimationLongTermeCallout}
                onChange={(e) => setEstimationLongTermeCallout(e.target.value)}
                maxLength={60}
                placeholder="ex: Estimations à plus de 2,5 M$!"
                className="w-full rounded-md border border-brand-800 bg-brand-900/50 px-3 py-2 text-xs text-white placeholder-white/30 focus:border-emerald-500/50 focus:outline-none"
              />
              <span className="mt-1 block text-[10px] text-white/40">
                Laissé vide = défaut « Estimations à plus de 3 M$! ».
              </span>
            </label>
          </section>

          {/* Section 7 — Tendances (slide 12) */}
          <section className="mb-6">
            <h3 className="mb-3 text-xs font-semibold uppercase tracking-wider text-emerald-300">
              7. Tendances Zipplex (slide 12)
            </h3>
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
              <label className="block">
                <span className="mb-1 block text-[11px] font-medium text-white/80">
                  Secteur (auto depuis la fiche)
                </span>
                <input
                  type="text"
                  value={data.quartier || "—"}
                  disabled
                  className="w-full rounded-md border border-brand-800 bg-brand-900/30 px-3 py-2 text-xs text-white/60"
                />
              </label>
              <label className="block">
                <span className="mb-1 block text-[11px] font-medium text-white/80">
                  Callout override (ex: +900$, +450$)
                </span>
                <input
                  type="text"
                  value={tendancesCalloutManuel}
                  onChange={(e) => setTendancesCalloutManuel(e.target.value)}
                  maxLength={20}
                  placeholder="auto Zipplex si vide"
                  className="w-full rounded-md border border-brand-800 bg-brand-900/50 px-3 py-2 text-xs text-white placeholder-white/30 focus:border-emerald-500/50 focus:outline-none"
                />
              </label>
              <label className="block">
                <span className="mb-1 block text-[11px] font-medium text-white/80">
                  Moyenne locative actuelle quartier (override $)
                </span>
                <input
                  type="number"
                  value={tendancesMoyenneActuelle}
                  onChange={(e) =>
                    setTendancesMoyenneActuelle(Number(e.target.value) || 0)
                  }
                  placeholder="auto Zipplex si 0"
                  className="w-full rounded-md border border-brand-800 bg-brand-900/50 px-3 py-2 text-xs text-white placeholder-white/30 focus:border-emerald-500/50 focus:outline-none"
                />
              </label>
              <label className="block">
                <span className="mb-1 block text-[11px] font-medium text-white/80">
                  Callout (legacy — laissé vide de préférence)
                </span>
                <input
                  type="text"
                  value={tendancesCallout}
                  onChange={(e) => setTendancesCallout(e.target.value)}
                  maxLength={20}
                  placeholder="(legacy v2)"
                  className="w-full rounded-md border border-brand-800 bg-brand-900/50 px-3 py-2 text-xs text-white placeholder-white/30 focus:border-emerald-500/50 focus:outline-none"
                />
              </label>
            </div>
          </section>

          {/* Section 8 — Photos */}
          <section className="mb-3">
            <h3 className="mb-3 text-xs font-semibold uppercase tracking-wider text-emerald-300">
              8. Photos (4 slots : cover, extérieur, carte, graphique
              Tendances)
            </h3>
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-4">
              {[
                {
                  label: "Cover",
                  set: (f: File | null) => handlePhotoChange("cover", f),
                  setAttach: setPhotoCoverAttachId,
                  attachId: photoCoverAttachId,
                  hasBase64: !!photoCoverBase64
                },
                {
                  label: "Extérieur",
                  set: (f: File | null) =>
                    handlePhotoChange("exterieur", f),
                  setAttach: setPhotoExtAttachId,
                  attachId: photoExtAttachId,
                  hasBase64: !!photoExterieurBase64
                },
                {
                  label: "Carte / quartier",
                  set: (f: File | null) => handlePhotoChange("carte", f),
                  setAttach: setPhotoCarteAttachId,
                  attachId: photoCarteAttachId,
                  hasBase64: !!photoCarteBase64
                },
                {
                  label: "Graphique Tendances (slide 12)",
                  set: (f: File | null) =>
                    handlePhotoChange("tendances", f),
                  setAttach: setPhotoTendancesAttachId,
                  attachId: photoTendancesAttachId,
                  hasBase64: !!photoTendancesBase64
                }
              ].map((slot) => (
                <div key={slot.label}>
                  <label className="mb-1 block text-[11px] text-white/70">
                    {slot.label}
                  </label>
                  <input
                    type="file"
                    accept="image/*"
                    onChange={(e) =>
                      slot.set(e.target.files?.[0] ?? null)
                    }
                    className="block w-full text-[10px] text-white/70 file:mr-2 file:rounded-md file:border-0 file:bg-emerald-500/20 file:px-2 file:py-1 file:text-[10px] file:text-emerald-300 hover:file:bg-emerald-500/30"
                  />
                  {data.existingPhotos.length > 0 ? (
                    <select
                      value={
                        slot.attachId !== null ? String(slot.attachId) : ""
                      }
                      onChange={(e) =>
                        slot.setAttach(
                          e.target.value ? Number(e.target.value) : null
                        )
                      }
                      className="mt-1 w-full rounded-md border border-brand-800 bg-brand-900/50 px-2 py-1 text-[10px] text-white/80"
                      disabled={slot.hasBase64}
                    >
                      <option value="">
                        ou attachment existant…
                      </option>
                      {data.existingPhotos.map((p) => (
                        <option key={p.id} value={String(p.id)}>
                          {p.filename}
                        </option>
                      ))}
                    </select>
                  ) : null}
                  <p className="mt-1 text-[10px] text-white/40">
                    {slot.hasBase64
                      ? "Photo chargée ✓"
                      : slot.attachId !== null
                        ? "Attachment ✓"
                        : "—"}
                  </p>
                </div>
              ))}
            </div>
          </section>
        </div>

        <footer className="flex flex-shrink-0 items-center justify-end gap-2 border-t border-brand-800 px-5 py-3">
          <button
            type="button"
            onClick={onClose}
            disabled={busy}
            className="rounded-md border border-brand-800 px-3 py-1.5 text-[11px] text-white/70 hover:bg-brand-900 disabled:opacity-50"
          >
            Annuler
          </button>
          <button
            type="button"
            onClick={() => void handleGenerate()}
            disabled={busy}
            className="inline-flex items-center gap-1.5 rounded-md border border-emerald-500/40 bg-emerald-500/20 px-3 py-1.5 text-[11px] font-medium text-emerald-300 hover:bg-emerald-500/30 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {busy ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <FileDown className="h-3.5 w-3.5" />
            )}
            {busy ? "Génération…" : "Générer .pptx"}
          </button>
        </footer>
      </div>
    </div>
  );
}
