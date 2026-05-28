"use client";

import { useEffect, useMemo, useState } from "react";
import { Loader2, X, FileDown } from "lucide-react";

import { authedFetch } from "@/lib/auth";

/**
 * Wizard de génération d'une offre d'investissement .pptx pour une
 * `LeadAnalysis`. MVP — 2 sections :
 *
 *   1. **Champs auto-remplis** (read-only) — Phil vérifie les chiffres
 *      qui seront injectés dans le template.
 *   2. **Stratégie value-add** — tagline + 4 bullets + checkboxes
 *      flags + textarea libre rénovations + photos (3 max).
 *
 * Au submit, POST `/api/v1/lead-analyses/{id}/offre-investissement` et
 * download du `.pptx` retourné.
 */

type AutoFilledRow = { label: string; value: string };

export type OffreInvestissementWizardData = {
  /** Champs auto extraits du LeadAnalysis (pour affichage seul). */
  autoFilled: AutoFilledRow[];
  /** Suggestions pré-remplies pour les bullets (basées sur les chiffres). */
  bulletSuggestions: { b1: string; b2: string; b3: string; b4: string };
  /** Quartier estimé (city) pour le tagline. */
  quartier: string;
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
  const [b1, setB1] = useState("");
  const [b2, setB2] = useState("");
  const [b3, setB3] = useState("");
  const [b4, setB4] = useState("");

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

  const [listeRenovations, setListeRenovations] = useState("");

  // Photos
  const [photoCoverBase64, setPhotoCoverBase64] = useState<string | null>(null);
  const [photoExterieurBase64, setPhotoExterieurBase64] = useState<
    string | null
  >(null);
  const [photoCarteBase64, setPhotoCarteBase64] = useState<string | null>(null);
  const [photoCoverAttachId, setPhotoCoverAttachId] = useState<number | null>(
    null
  );
  const [photoExtAttachId, setPhotoExtAttachId] = useState<number | null>(null);
  const [photoCarteAttachId, setPhotoCarteAttachId] = useState<number | null>(
    null
  );

  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState<{ text: string; kind: "ok" | "err" } | null>(
    null
  );

  // Reset state when wizard opens
  useEffect(() => {
    if (!open) return;
    setTagline(
      `De l'achat au refinancement : un projet immobilier solide à ${
        data.quartier || "Montréal"
      }`
    );
    setB1(data.bulletSuggestions.b1);
    setB2(data.bulletSuggestions.b2);
    setB3(data.bulletSuggestions.b3);
    setB4(data.bulletSuggestions.b4);
    setToast(null);
  }, [open, data]);

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
    slot: "cover" | "exterieur" | "carte",
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
      } else {
        setPhotoCarteBase64(b64);
        setPhotoCarteAttachId(null);
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
          bullet_opp_1: b1,
          bullet_opp_2: b2,
          bullet_opp_3: b3,
          bullet_opp_4: b4,
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
          liste_renovations: listeRenovations,
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
              Template Horizon v1 — 16 slides
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

          {/* Section 2 — Value-add */}
          <section>
            <h3 className="mb-3 text-xs font-semibold uppercase tracking-wider text-emerald-300">
              2. Stratégie value-add
            </h3>

            <label className="mb-3 block">
              <span className="mb-1 block text-[11px] font-medium text-white/80">
                Angle stratégique / tagline (slide cover)
              </span>
              <textarea
                value={tagline}
                onChange={(e) => setTagline(e.target.value)}
                rows={2}
                maxLength={200}
                className="w-full rounded-md border border-brand-800 bg-brand-900/50 px-3 py-2 text-xs text-white placeholder-white/30 focus:border-emerald-500/50 focus:outline-none"
              />
            </label>

            <div className="mb-3 grid grid-cols-1 gap-2 sm:grid-cols-2">
              {[
                { v: b1, set: setB1, label: "Bullet opportunité 1" },
                { v: b2, set: setB2, label: "Bullet opportunité 2" },
                { v: b3, set: setB3, label: "Bullet opportunité 3" },
                { v: b4, set: setB4, label: "Bullet opportunité 4" },
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

            <div className="mb-3 rounded-lg border border-brand-800 p-3">
              <h4 className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-white/70">
                Leviers value-add
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
                  <option value="aucun">Aucun</option>
                  <option value="gaz_to_elec">Gaz → Électrique</option>
                  <option value="elec_to_thermo">
                    Électrique → Thermopompe
                  </option>
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
                  <option value="aph_50">APH 50 pts</option>
                  <option value="aph_100">APH 100 pts</option>
                  <option value="aucun">Aucun (SCHL standard)</option>
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

            <label className="mb-3 block">
              <span className="mb-1 block text-[11px] font-medium text-white/80">
                Liste des rénovations (texte libre)
              </span>
              <textarea
                value={listeRenovations}
                onChange={(e) => setListeRenovations(e.target.value)}
                rows={4}
                placeholder="ex: Fondation\nBriques\nPortes/fenêtres\n..."
                className="w-full rounded-md border border-brand-800 bg-brand-900/50 px-3 py-2 text-xs text-white placeholder-white/30 focus:border-emerald-500/50 focus:outline-none"
              />
            </label>

            <div className="mb-3 rounded-lg border border-brand-800 p-3">
              <h4 className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-white/70">
                Photos (3 max — cover, extérieur, carte/quartier)
              </h4>
              <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
                {[
                  {
                    label: "Cover",
                    set: (f: File | null) => handlePhotoChange("cover", f),
                    setAttach: setPhotoCoverAttachId,
                    attachId: photoCoverAttachId,
                    hasBase64: !!photoCoverBase64,
                  },
                  {
                    label: "Extérieur",
                    set: (f: File | null) =>
                      handlePhotoChange("exterieur", f),
                    setAttach: setPhotoExtAttachId,
                    attachId: photoExtAttachId,
                    hasBase64: !!photoExterieurBase64,
                  },
                  {
                    label: "Carte / quartier",
                    set: (f: File | null) => handlePhotoChange("carte", f),
                    setAttach: setPhotoCarteAttachId,
                    attachId: photoCarteAttachId,
                    hasBase64: !!photoCarteBase64,
                  },
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
                          ou utiliser un attachment existant…
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
                          ? "Attachment sélectionné ✓"
                          : "Aucune (placeholder du template conservé)"}
                    </p>
                  </div>
                ))}
              </div>
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
