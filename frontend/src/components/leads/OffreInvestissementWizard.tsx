"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { AlertTriangle, FileDown, Loader2, RefreshCw, X } from "lucide-react";

import { authedFetch } from "@/lib/auth";

/**
 * Assistant de génération du pitch deck (offre d'investissement .pptx),
 * v3 — Phil 2026-10-08 : « quand je génère, je n'ai pas ou presque rien
 * à changer ensuite ».
 *
 * Tout est pré-rempli par `GET /lead-analyses/{id}/offre-investissement/defaults`
 * (fiche + résultats d'analyse + TRI investisseur). L'utilisateur ajuste
 * seulement ce qui ne se déduit pas des chiffres : accroche, puces,
 * leviers, dates des jalons, rénovations, photos. L'aperçu des chiffres
 * imprimés (dont le TRI) se recalcule quand le capital ou le % de parts
 * change. Au submit : `POST …/offre-investissement` → téléchargement.
 */

type Jalon = { date: string; label: string };

type DeckInputs = {
  tagline: string;
  presente_par: string;
  projet_sous_titre: string;
  investissement_requis: number | null;
  pct_parts: number | null;
  nb_etages: number | null;
  superficie_text: string;
  unites_note: string;
  frais_energetiques_text: string;
  stationnements_text: string;
  bullets: string[];
  comparable_phrase: string;
  comparable_url: string;
  valeur_comparable: number | null;
  leviers: string[];
  date_debut: string;
  jalons: Record<string, Jalon>;
  renovations: string[];
  tendances_secteur: string;
  tendances_source: string;
  contingence_pct: number;
  fonds_roulement_mois: number;
};

type ApercuTri = { annee: number; tri: number | null; cash: number; parts: number; patrimoine: number };

type Apercu = {
  adresse: string;
  prix: number;
  nb_logements: number;
  revenus: number;
  loyer_moyen: number;
  strategie: string;
  frais_demarrage: number;
  pret_max: number;
  mdf: number;
  fonds_necessaires: number;
  balance_vente: number;
  refi_programme: string;
  refi_valeur: number;
  refi_pret: number;
  refi_equite: number;
  nouveau_loyer: number;
  nouveaux_revenus: number;
  capital: number;
  pct_parts: number;
  tri: ApercuTri[];
};

type PhotoSlot = { key: string; slide: number; label: string };
type Attachment = { id: number; filename: string; content_type: string; size_bytes?: number };

type Defaults = {
  analysis_ready: boolean;
  raison?: string | null;
  inputs: DeckInputs | null;
  apercu: Apercu | null;
  photos: { slots: PhotoSlot[]; attachments: Attachment[] };
  renovations_catalogue: string[];
  template_version: string;
  service_version: string;
};

type PhotoChoix = { attachment_id?: number; base64_data?: string; filename?: string };

const JALON_LABELS: Record<string, string> = {
  m1_1: "M1.1",
  m1_2: "M1.2",
  m2_1: "M2.1",
  m2_2: "M2.2",
  m2_3: "M2.3",
  m2_4: "M2.4",
  m3_1: "M3.1"
};

function fmtMoney(n: number | null | undefined): string {
  if (n == null || Number.isNaN(n)) return "—";
  return `${Math.round(n).toLocaleString("fr-CA").replace(/ /g, " ")} $`;
}

function fmtPct(n: number | null | undefined, dec = 1): string {
  if (n == null || Number.isNaN(n)) return "n/d";
  return `${(n * 100).toFixed(dec).replace(".", ",")} %`;
}

const inputCls =
  "w-full rounded-md border border-brand-800 bg-brand-900/50 px-3 py-2 text-xs text-white placeholder-white/30 focus:border-emerald-500/50 focus:outline-none";
const labelCls = "mb-1 block text-[11px] font-medium text-white/80";

function Champ({
  label,
  children,
  hint,
  className
}: {
  label: string;
  children: React.ReactNode;
  hint?: string;
  className?: string;
}) {
  return (
    <label className={`block ${className || ""}`}>
      <span className={labelCls}>{label}</span>
      {children}
      {hint ? <span className="mt-0.5 block text-[10px] text-white/40">{hint}</span> : null}
    </label>
  );
}

function Section({ titre, sous, children }: { titre: string; sous?: string; children: React.ReactNode }) {
  return (
    <section className="mb-6">
      <h3 className="mb-1 text-xs font-semibold uppercase tracking-wider text-emerald-300">{titre}</h3>
      {sous ? <p className="mb-3 text-[11px] text-white/50">{sous}</p> : <div className="mb-3" />}
      {children}
    </section>
  );
}

export function OffreInvestissementWizard({
  open,
  onClose,
  analysisId
}: {
  open: boolean;
  onClose: () => void;
  analysisId: number;
}) {
  const [loading, setLoading] = useState(false);
  const [erreur, setErreur] = useState<string | null>(null);
  const [defaults, setDefaults] = useState<Defaults | null>(null);
  const [inputs, setInputs] = useState<DeckInputs | null>(null);
  const [apercu, setApercu] = useState<Apercu | null>(null);
  const [apercuBusy, setApercuBusy] = useState(false);
  const [photos, setPhotos] = useState<Record<string, PhotoChoix>>({});
  const [renoLibre, setRenoLibre] = useState("");
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState<{ text: string; kind: "ok" | "err" | "warn" } | null>(null);
  const apercuTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const charger = useCallback(async () => {
    setLoading(true);
    setErreur(null);
    try {
      const r = await authedFetch(`/api/v1/lead-analyses/${analysisId}/offre-investissement/defaults`);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const d = (await r.json()) as Defaults;
      setDefaults(d);
      setInputs(d.inputs);
      setApercu(d.apercu);
      setPhotos({});
    } catch (e) {
      setErreur((e as Error).message || "Impossible de préparer le deck.");
    } finally {
      setLoading(false);
    }
  }, [analysisId]);

  useEffect(() => {
    if (open) void charger();
  }, [open, charger]);

  // Aperçu du TRI recalculé quand le capital ou le % de parts change.
  const rafraichirApercu = useCallback(
    (capital: number | null, pct: number | null) => {
      if (apercuTimer.current) clearTimeout(apercuTimer.current);
      apercuTimer.current = setTimeout(async () => {
        setApercuBusy(true);
        try {
          const q = new URLSearchParams();
          if (capital && capital > 0) q.set("investissement_requis", String(capital));
          if (pct && pct > 0) q.set("pct_parts", String(pct));
          const r = await authedFetch(
            `/api/v1/lead-analyses/${analysisId}/offre-investissement/defaults?${q.toString()}`
          );
          if (r.ok) {
            const d = (await r.json()) as Defaults;
            if (d.apercu) setApercu(d.apercu);
          }
        } catch {
          /* aperçu seulement */
        } finally {
          setApercuBusy(false);
        }
      }, 500);
    },
    [analysisId]
  );

  function set<K extends keyof DeckInputs>(key: K, value: DeckInputs[K]) {
    setInputs((prev) => (prev ? { ...prev, [key]: value } : prev));
    if (key === "investissement_requis" || key === "pct_parts") {
      const next = { ...(inputs as DeckInputs), [key]: value } as DeckInputs;
      rafraichirApercu(next.investissement_requis, next.pct_parts);
    }
  }

  function setListe(key: "bullets" | "leviers", i: number, value: string) {
    setInputs((prev) => {
      if (!prev) return prev;
      const arr = [...prev[key]];
      while (arr.length <= i) arr.push("");
      arr[i] = value;
      return { ...prev, [key]: arr };
    });
  }

  function setJalon(key: string, champ: keyof Jalon, value: string) {
    setInputs((prev) =>
      prev
        ? { ...prev, jalons: { ...prev.jalons, [key]: { ...(prev.jalons[key] || { date: "", label: "" }), [champ]: value } } }
        : prev
    );
  }

  function toggleReno(nom: string) {
    setInputs((prev) => {
      if (!prev) return prev;
      const has = prev.renovations.includes(nom);
      return { ...prev, renovations: has ? prev.renovations.filter((x) => x !== nom) : [...prev.renovations, nom] };
    });
  }

  function ajouterRenoLibre() {
    const v = renoLibre.trim();
    if (!v) return;
    setInputs((prev) => (prev && !prev.renovations.includes(v) ? { ...prev, renovations: [...prev.renovations, v] } : prev));
    setRenoLibre("");
  }

  function choisirPhotoFichier(slot: string, file: File | null) {
    if (!file) {
      setPhotos((p) => {
        const n = { ...p };
        delete n[slot];
        return n;
      });
      return;
    }
    const reader = new FileReader();
    reader.onload = () => {
      const res = String(reader.result || "");
      const b64 = res.includes(",") ? res.split(",")[1] : res;
      setPhotos((p) => ({ ...p, [slot]: { base64_data: b64, filename: file.name } }));
    };
    reader.readAsDataURL(file);
  }

  function choisirPhotoAttachment(slot: string, id: number | null) {
    setPhotos((p) => {
      const n = { ...p };
      if (id == null) delete n[slot];
      else n[slot] = { attachment_id: id };
      return n;
    });
  }

  async function generer() {
    if (!inputs) return;
    setBusy(true);
    setToast(null);
    try {
      const photosPayload: Record<string, { attachment_id?: number; base64_data?: string }> = {};
      for (const [k, v] of Object.entries(photos)) {
        if (v.attachment_id != null) photosPayload[k] = { attachment_id: v.attachment_id };
        else if (v.base64_data) photosPayload[k] = { base64_data: v.base64_data };
      }
      const r = await authedFetch(`/api/v1/lead-analyses/${analysisId}/offre-investissement`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ inputs, photos: photosPayload })
      });
      if (!r.ok) {
        const body = (await r.json().catch(() => null)) as { detail?: string } | null;
        throw new Error(typeof body?.detail === "string" ? body.detail : `HTTP ${r.status}`);
      }
      const misses = Number(r.headers.get("X-Deck-Misses") || "0");
      const blob = await r.blob();
      const cd = r.headers.get("Content-Disposition") || "";
      const m = /filename="?([^"]+)"?/.exec(cd);
      const filename = m?.[1] || `Offre_Investissement_${analysisId}.pptx`;
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 2000);
      const manquantes = Object.keys(photosPayload).length;
      setToast(
        misses > 0
          ? { text: `Deck généré, mais ${misses} élément(s) du gabarit n'ont pas été trouvés — vérifie le fichier (détail dans le journal d'activité).`, kind: "warn" }
          : { text: `Deck généré (${filename})${manquantes < 9 ? ` — ${9 - manquantes} emplacement(s) de photo gardent leur pastille grise.` : "."}`, kind: "ok" }
      );
    } catch (e) {
      setToast({ text: `Génération échouée : ${(e as Error).message}`, kind: "err" });
    } finally {
      setBusy(false);
    }
  }

  if (!open) return null;

  const jalonKeys = inputs ? ["m1_1", "m1_2", "m2_1", "m2_2", "m2_3", "m2_4", "m3_1"].filter((k) => inputs.jalons[k]) : [];
  const catalogue = defaults?.renovations_catalogue || [];
  const renosHorsCatalogue = (inputs?.renovations || []).filter((r) => !catalogue.includes(r));

  return (
    <div className="fixed inset-0 z-[60] flex items-end justify-center bg-black/70 px-2 py-4 sm:items-center" onClick={onClose}>
      <div
        className="flex max-h-[calc(100vh-2rem)] w-full max-w-5xl flex-col overflow-hidden rounded-2xl border border-brand-800 bg-brand-950"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="flex flex-shrink-0 items-start justify-between gap-3 border-b border-brand-800 px-5 py-4">
          <div className="min-w-0 flex-1">
            <p className="text-[10px] uppercase tracking-wider text-emerald-400">Pitch deck — offre d&apos;investissement</p>
            <h2 className="mt-0.5 text-base font-bold text-white">
              {apercu?.adresse || "Fiche d'analyse"} · gabarit Horizon v3 (16 diapos)
            </h2>
            <p className="mt-0.5 text-[11px] text-white/50">
              Tout est pré-rempli depuis la fiche, son analyse et le TRI. Ajuste ce qui ne se déduit pas des chiffres, choisis les photos, puis génère.
            </p>
          </div>
          <button type="button" onClick={onClose} className="rounded-md p-1 text-white/60 hover:bg-brand-900 hover:text-white" aria-label="Fermer">
            <X className="h-4 w-4" />
          </button>
        </header>

        {toast ? (
          <div
            className={`flex items-start gap-2 border-b border-brand-800 px-5 py-2 text-[11px] ${
              toast.kind === "ok" ? "bg-emerald-500/10 text-emerald-300" : toast.kind === "warn" ? "bg-amber-500/10 text-amber-200" : "bg-rose-500/10 text-rose-300"
            }`}
          >
            <span className="flex-1 whitespace-pre-line">{toast.text}</span>
          </div>
        ) : null}

        <div className="flex-1 overflow-y-auto px-5 py-4">
          {loading ? (
            <div className="flex items-center justify-center gap-2 py-16 text-sm text-white/50">
              <Loader2 className="h-4 w-4 animate-spin" /> Préparation du deck…
            </div>
          ) : erreur ? (
            <p className="flex items-start gap-2 rounded-md border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-300">
              <AlertTriangle className="mt-0.5 h-4 w-4 flex-shrink-0" />
              <span>{erreur}</span>
            </p>
          ) : defaults && !defaults.analysis_ready ? (
            <p className="flex items-start gap-2 rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-sm text-amber-200">
              <AlertTriangle className="mt-0.5 h-4 w-4 flex-shrink-0" />
              <span>{defaults.raison || "Lance d'abord l'analyse financière de la fiche."}</span>
            </p>
          ) : inputs && apercu ? (
            <>
              {/* Aperçu des chiffres imprimés */}
              <Section titre="Chiffres qui seront imprimés" sous="Repris de la fiche et de son analyse. Si un chiffre est faux, corrige la fiche puis relance l'analyse.">
                <div className="grid grid-cols-2 gap-2 text-[11px] sm:grid-cols-4">
                  {[
                    ["Prix", fmtMoney(apercu.prix)],
                    ["Logements", String(apercu.nb_logements)],
                    ["Revenus actuels", `${fmtMoney(apercu.revenus)}/an`],
                    ["Loyer moyen", `${fmtMoney(apercu.loyer_moyen)}/mois`],
                    ["Stratégie", apercu.strategie],
                    ["Frais de démarrage", fmtMoney(apercu.frais_demarrage)],
                    ["Prêt maximal", fmtMoney(apercu.pret_max)],
                    ["Fonds nécessaires", fmtMoney(apercu.fonds_necessaires)],
                    ["Refi retenu", apercu.refi_programme],
                    ["Valeur au refi", fmtMoney(apercu.refi_valeur)],
                    ["Prêt au refi", fmtMoney(apercu.refi_pret)],
                    ["Équité dégagée", fmtMoney(apercu.refi_equite)],
                    ["Nouveau loyer moyen", `${fmtMoney(apercu.nouveau_loyer)}/mois`],
                    ["Nouveaux revenus", `${fmtMoney(apercu.nouveaux_revenus)}/an`],
                    ["Balance de vente", apercu.balance_vente > 0 ? fmtMoney(apercu.balance_vente) : "Aucune"]
                  ].map(([l, v]) => (
                    <div key={l} className="rounded-lg border border-brand-800 bg-brand-900/40 px-3 py-2">
                      <div className="text-[10px] uppercase tracking-wider text-white/40">{l}</div>
                      <div className="font-mono tabular-nums text-white">{v}</div>
                    </div>
                  ))}
                </div>
                <div className="mt-3 overflow-x-auto rounded-lg border border-brand-800">
                  <table className="min-w-full text-[11px]">
                    <thead>
                      <tr className="border-b border-brand-800 text-white/60">
                        <th className="px-3 py-1.5 text-left">
                          TRI investisseur {apercuBusy ? <RefreshCw className="ml-1 inline h-3 w-3 animate-spin" /> : null}
                        </th>
                        {apercu.tri.map((h) => (
                          <th key={h.annee} className="px-3 py-1.5 text-right">Année {h.annee}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {[
                        ["Cash retourné", (h: ApercuTri) => fmtMoney(h.cash)],
                        ["Valeur des parts", (h: ApercuTri) => fmtMoney(h.parts)],
                        ["Patrimoine", (h: ApercuTri) => fmtMoney(h.patrimoine)],
                        ["TRI", (h: ApercuTri) => fmtPct(h.tri)]
                      ].map(([l, f]) => (
                        <tr key={l as string} className="border-t border-brand-800/50">
                          <td className="px-3 py-1.5 text-white/70">{l as string}</td>
                          {apercu.tri.map((h) => (
                            <td key={h.annee} className="px-3 py-1.5 text-right font-mono tabular-nums text-white">
                              {(f as (h: ApercuTri) => string)(h)}
                            </td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </Section>

              <Section titre="1. Couverture et résumé (diapos 1–2)">
                <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                  <Champ label="Accroche de couverture" className="sm:col-span-2">
                    <input className={inputCls} value={inputs.tagline} onChange={(e) => set("tagline", e.target.value)} />
                  </Champ>
                  <Champ label="Présenté par">
                    <input className={inputCls} value={inputs.presente_par} onChange={(e) => set("presente_par", e.target.value)} />
                  </Champ>
                  <Champ label="Sous-titre du projet">
                    <input className={inputCls} value={inputs.projet_sous_titre} onChange={(e) => set("projet_sous_titre", e.target.value)} />
                  </Champ>
                  <Champ label="Investissement requis (capital de l'investisseur)" hint="Par défaut : capital injecté de l'onglet TRI, sinon les fonds nécessaires.">
                    <input
                      type="number"
                      className={inputCls}
                      value={inputs.investissement_requis ?? ""}
                      onChange={(e) => set("investissement_requis", e.target.value === "" ? null : Number(e.target.value))}
                    />
                  </Champ>
                  <Champ label="% des parts du projet offert">
                    <input
                      type="number"
                      min={1}
                      max={100}
                      className={inputCls}
                      value={inputs.pct_parts != null ? Math.round(inputs.pct_parts * 1000) / 10 : ""}
                      onChange={(e) => set("pct_parts", e.target.value === "" ? null : Number(e.target.value) / 100)}
                    />
                  </Champ>
                </div>
              </Section>

              <Section titre="2. Présentation du projet (diapo 3)">
                <div className="grid grid-cols-2 gap-2 sm:grid-cols-5">
                  <Champ label="Nombre d'étages">
                    <input type="number" min={1} max={30} className={inputCls} value={inputs.nb_etages ?? ""} onChange={(e) => set("nb_etages", e.target.value === "" ? null : Number(e.target.value))} />
                  </Champ>
                  <Champ label="Superficie habitable">
                    <input className={inputCls} value={inputs.superficie_text} onChange={(e) => set("superficie_text", e.target.value)} />
                  </Champ>
                  <Champ label="Note sous les unités" hint="ex. « 6 garages », « 2 vacants »">
                    <input className={inputCls} value={inputs.unites_note} onChange={(e) => set("unites_note", e.target.value)} />
                  </Champ>
                  <Champ label="Frais énergétiques">
                    <input className={inputCls} value={inputs.frais_energetiques_text} onChange={(e) => set("frais_energetiques_text", e.target.value)} />
                  </Champ>
                  <Champ label="Stationnements">
                    <input className={inputCls} value={inputs.stationnements_text} onChange={(e) => set("stationnements_text", e.target.value)} />
                  </Champ>
                </div>
              </Section>

              <Section titre="3. Opportunité unique (diapo 4)" sous="Quatre puces, puis le comparable Centris (phrase + lien) et sa valeur — elle alimente le graphique « Profit à l'achat » et la valeur marchande « avant ».">
                <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                  {[0, 1, 2, 3].map((i) => (
                    <Champ key={i} label={`Puce ${i + 1}`}>
                      <input className={inputCls} maxLength={140} value={inputs.bullets[i] || ""} onChange={(e) => setListe("bullets", i, e.target.value)} />
                    </Champ>
                  ))}
                  <Champ label="Comparable (phrase)">
                    <input className={inputCls} value={inputs.comparable_phrase} onChange={(e) => set("comparable_phrase", e.target.value)} />
                  </Champ>
                  <Champ label="Lien Centris du comparable">
                    <input className={inputCls} value={inputs.comparable_url} onChange={(e) => set("comparable_url", e.target.value)} placeholder="https://www.centris.ca/…" />
                  </Champ>
                  <Champ label="Valeur marchande comparable ($)" hint="Par défaut : valeur économique au TGA de l'achat, arrondie. Vide = pas de gain affiché.">
                    <input type="number" className={inputCls} value={inputs.valeur_comparable ?? ""} onChange={(e) => set("valeur_comparable", e.target.value === "" ? null : Number(e.target.value))} />
                  </Champ>
                </div>
              </Section>

              <Section titre="4. Leviers de création de valeur (diapo 5)">
                <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                  {[0, 1, 2, 3].map((i) => (
                    <input key={i} className={inputCls} value={inputs.leviers[i] || ""} onChange={(e) => setListe("leviers", i, e.target.value)} />
                  ))}
                </div>
              </Section>

              <Section titre="5. Échéancier (diapo 6)" sous="Le Gantt, les cases colorées et les repères sont placés d'après ces dates (1er du mois).">
                <div className="mb-2 grid grid-cols-1 gap-2 sm:grid-cols-3">
                  <Champ label="Début du projet">
                    <input type="date" className={inputCls} value={inputs.date_debut} onChange={(e) => set("date_debut", e.target.value)} />
                  </Champ>
                </div>
                <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                  {jalonKeys.map((k) => (
                    <div key={k} className="flex items-end gap-2 rounded-lg border border-brand-800 bg-brand-900/30 p-2">
                      <span className="pb-2 text-[11px] font-semibold text-emerald-300">{JALON_LABELS[k]}</span>
                      <Champ label="Date" className="w-36">
                        <input type="date" className={inputCls} value={inputs.jalons[k].date} onChange={(e) => setJalon(k, "date", e.target.value)} />
                      </Champ>
                      <Champ label="Livrable" className="flex-1">
                        <input className={inputCls} value={inputs.jalons[k].label} onChange={(e) => setJalon(k, "label", e.target.value)} />
                      </Champ>
                    </div>
                  ))}
                </div>
              </Section>

              <Section titre="6. Rénovations (diapo 9)" sous="Les postes cochés sont listés ; le total est celui des travaux de la fiche.">
                <div className="flex flex-wrap gap-1.5">
                  {catalogue.map((nom) => {
                    const on = inputs.renovations.includes(nom);
                    return (
                      <button
                        key={nom}
                        type="button"
                        onClick={() => toggleReno(nom)}
                        className={`rounded-full border px-2.5 py-1 text-[11px] ${on ? "border-emerald-500/60 bg-emerald-500/20 text-emerald-200" : "border-brand-800 bg-brand-900/40 text-white/60 hover:text-white"}`}
                      >
                        {nom}
                      </button>
                    );
                  })}
                  {renosHorsCatalogue.map((nom) => (
                    <button key={nom} type="button" onClick={() => toggleReno(nom)} className="rounded-full border border-emerald-500/60 bg-emerald-500/20 px-2.5 py-1 text-[11px] text-emerald-200">
                      {nom} ×
                    </button>
                  ))}
                </div>
                <div className="mt-2 flex gap-2">
                  <input className={inputCls} placeholder="Autre poste…" value={renoLibre} onChange={(e) => setRenoLibre(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); ajouterRenoLibre(); } }} />
                  <button type="button" onClick={ajouterRenoLibre} className="whitespace-nowrap rounded-md border border-brand-800 px-3 py-1.5 text-[11px] text-white/70 hover:bg-brand-900">
                    Ajouter
                  </button>
                </div>
              </Section>

              <Section titre="7. Tendances et risques (diapos 12 et 14)">
                <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                  <Champ label="Secteur (titre Tendances)">
                    <input className={inputCls} value={inputs.tendances_secteur} onChange={(e) => set("tendances_secteur", e.target.value)} />
                  </Champ>
                  <Champ label="Source des données">
                    <input className={inputCls} value={inputs.tendances_source} onChange={(e) => set("tendances_source", e.target.value)} />
                  </Champ>
                  <Champ label="Marge de contingence (%)">
                    <input type="number" className={inputCls} value={inputs.contingence_pct} onChange={(e) => set("contingence_pct", Number(e.target.value) || 0)} />
                  </Champ>
                  <Champ label="Fonds de roulement (mois)">
                    <input type="number" className={inputCls} value={inputs.fonds_roulement_mois} onChange={(e) => set("fonds_roulement_mois", Number(e.target.value) || 0)} />
                  </Champ>
                </div>
              </Section>

              <Section titre="8. Photos" sous="Choisis une pièce jointe de la fiche ou téléverse une image. Un emplacement vide garde sa pastille grise « photo à insérer » (visible, donc impossible à oublier). Recadrage automatique.">
                <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
                  {(defaults?.photos.slots || []).map((slot) => {
                    const choix = photos[slot.key];
                    return (
                      <div key={slot.key} className="rounded-lg border border-brand-800 bg-brand-900/30 p-2">
                        <div className="mb-1 text-[11px] font-medium text-white/80">{slot.label}</div>
                        {defaults && defaults.photos.attachments.length > 0 ? (
                          <select
                            className="mb-1 w-full rounded-md border border-brand-800 bg-brand-900/50 px-2 py-1 text-[10px] text-white/80"
                            value={choix?.attachment_id != null ? String(choix.attachment_id) : ""}
                            onChange={(e) => choisirPhotoAttachment(slot.key, e.target.value ? Number(e.target.value) : null)}
                          >
                            <option value="">Pièce jointe de la fiche…</option>
                            {defaults.photos.attachments.map((a) => (
                              <option key={a.id} value={String(a.id)}>{a.filename}</option>
                            ))}
                          </select>
                        ) : null}
                        <input
                          type="file"
                          accept="image/*"
                          onChange={(e) => choisirPhotoFichier(slot.key, e.target.files?.[0] ?? null)}
                          className="block w-full text-[10px] text-white/70 file:mr-2 file:rounded-md file:border-0 file:bg-emerald-500/20 file:px-2 file:py-1 file:text-[10px] file:text-emerald-300 hover:file:bg-emerald-500/30"
                        />
                        <p className="mt-1 text-[10px] text-white/40">
                          {choix?.base64_data ? `Image chargée ✓ ${choix.filename || ""}` : choix?.attachment_id != null ? "Pièce jointe ✓" : "Pastille grise"}
                        </p>
                      </div>
                    );
                  })}
                </div>
              </Section>
            </>
          ) : null}
        </div>

        <footer className="flex flex-shrink-0 items-center justify-between gap-2 border-t border-brand-800 px-5 py-3">
          <span className="text-[10px] text-white/40">
            {defaults ? `Gabarit ${defaults.template_version} · service ${defaults.service_version}` : ""}
          </span>
          <div className="flex items-center gap-2">
            <button type="button" onClick={onClose} disabled={busy} className="rounded-md border border-brand-800 px-3 py-1.5 text-[11px] text-white/70 hover:bg-brand-900 disabled:opacity-50">
              Fermer
            </button>
            <button
              type="button"
              onClick={() => void generer()}
              disabled={busy || !inputs || !defaults?.analysis_ready}
              className="inline-flex items-center gap-1.5 rounded-md border border-emerald-500/40 bg-emerald-500/20 px-3 py-1.5 text-[11px] font-medium text-emerald-300 hover:bg-emerald-500/30 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <FileDown className="h-3.5 w-3.5" />}
              {busy ? "Génération…" : "Générer le .pptx"}
            </button>
          </div>
        </footer>
      </div>
    </div>
  );
}
