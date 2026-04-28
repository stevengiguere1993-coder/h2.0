"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useSearchParams } from "next/navigation";
import {
  ArrowLeft,
  ArrowRight,
  Check,
  Loader2,
  Sparkles,
  Upload
} from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { authedFetch } from "@/lib/auth";
import {
  calculerAnalyse,
  INPUTS_DEFAULTS,
  type AnalyseInputs
} from "@/lib/financial-calculator";
import { useProspectionLayout } from "../../layout";

type ExtractResponse = {
  extracted: {
    adresse?: string | null;
    prix_achat?: number | null;
    nombre_logements?: number | null;
    revenus_annuels?: number | null;
    nouveau_loyer_moyen?: number | null;
    taxes_municipales?: number | null;
    taxes_scolaires?: number | null;
    assurances?: number | null;
    energie?: number | null;
    tga?: number | null;
    annee_construction?: number | null;
    notes?: string | null;
  };
  confidence: "low" | "medium" | "high";
};

const STEPS = [
  { id: 1, title: "Identification", desc: "Adresse, prix, logements" },
  { id: 2, title: "Revenus / dépenses", desc: "Loyers actuels, taxes, énergie" },
  { id: 3, title: "Hypothèses refi", desc: "Loyers stabilisés, ajouts" },
  { id: 4, title: "Frais & paramètres", desc: "Démarrage, taux, TGA" },
  { id: 5, title: "Résultats", desc: "Calcul des 3 scénarios" }
] as const;

export default function NouvelleAnalysePage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { onOpenSidebar } = useProspectionLayout();
  const leadIdParam = searchParams.get("lead_id");
  const leadId = leadIdParam ? Number(leadIdParam) : null;

  const [step, setStep] = useState(1);
  const [inputs, setInputs] = useState<AnalyseInputs>({ ...INPUTS_DEFAULTS });
  const [extracting, setExtracting] = useState(false);
  const [extractError, setExtractError] = useState<string | null>(null);
  const [extractNotes, setExtractNotes] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Pré-remplit depuis le lead si lead_id passé
  useEffect(() => {
    if (!leadId) return;
    void (async () => {
      try {
        const res = await authedFetch(`/api/v1/prospection/${leadId}`);
        if (!res.ok) return;
        const lead = await res.json();
        setInputs((prev) => ({
          ...prev,
          adresse: lead.address
            ? `${lead.address}${lead.city ? ", " + lead.city : ""}`
            : prev.adresse,
          prixAchat: lead.purchase_price ?? prev.prixAchat,
          nombreLogements: lead.nb_logements ?? prev.nombreLogements
        }));
      } catch {
        /* ignore */
      }
    })();
  }, [leadId]);

  const results = useMemo(() => {
    if (step !== 5) return null;
    try {
      return calculerAnalyse(inputs);
    } catch (e) {
      return null;
    }
  }, [inputs, step]);

  function setField<K extends keyof AnalyseInputs>(
    key: K,
    value: AnalyseInputs[K]
  ) {
    setInputs((prev) => ({ ...prev, [key]: value }));
  }

  async function handleUpload(file: File) {
    setExtracting(true);
    setExtractError(null);
    setExtractNotes(null);
    try {
      const fd = new FormData();
      fd.append("file", file);
      const res = await authedFetch(
        "/api/v1/prospection/analyses/extract",
        { method: "POST", body: fd }
      );
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || `HTTP ${res.status}`);
      }
      const data = (await res.json()) as ExtractResponse;
      const ex = data.extracted;
      setInputs((prev) => ({
        ...prev,
        adresse: ex.adresse ?? prev.adresse,
        prixAchat: ex.prix_achat ?? prev.prixAchat,
        nombreLogements: ex.nombre_logements ?? prev.nombreLogements,
        revenusAnnuels: ex.revenus_annuels ?? prev.revenusAnnuels,
        nouveauLoyerMoyen:
          ex.nouveau_loyer_moyen ?? prev.nouveauLoyerMoyen,
        taxesMunicipales: ex.taxes_municipales ?? prev.taxesMunicipales,
        taxesScolaires: ex.taxes_scolaires ?? prev.taxesScolaires,
        assurances: ex.assurances ?? prev.assurances,
        energie: ex.energie ?? prev.energie,
        tga: ex.tga ?? prev.tga
      }));
      if (ex.notes) setExtractNotes(ex.notes);
    } catch (e) {
      setExtractError(
        e instanceof Error ? e.message : "Erreur d'extraction"
      );
    } finally {
      setExtracting(false);
    }
  }

  async function handleSave() {
    if (!results) return;
    setSaving(true);
    setSaveError(null);
    try {
      const name =
        inputs.adresse?.trim() ||
        `Analyse du ${new Date().toLocaleDateString("fr-CA")}`;
      const res = await authedFetch("/api/v1/prospection/analyses", {
        method: "POST",
        body: JSON.stringify({
          name,
          lead_id: leadId,
          inputs,
          results
        })
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || `HTTP ${res.status}`);
      }
      const created = await res.json();
      router.push(`/prospection/analyse/${created.id}`);
    } catch (e) {
      setSaveError(e instanceof Error ? e.message : "Erreur de sauvegarde");
    } finally {
      setSaving(false);
    }
  }

  return (
    <>
      <AppTopbar
        breadcrumbs={[
          { label: "Prospection", href: "/prospection" },
          { label: "Analyses", href: "/prospection/analyse" },
          { label: "Nouvelle" }
        ]}
        onOpenSidebar={onOpenSidebar}
      />

      <div className="px-4 py-6 lg:px-6">
        <Stepper step={step} onStepClick={(s) => setStep(s)} />

        <div className="mt-6 max-w-3xl">
          {step === 1 && (
            <Step1
              inputs={inputs}
              setField={setField}
              onUpload={handleUpload}
              extracting={extracting}
              extractError={extractError}
              extractNotes={extractNotes}
              fileInputRef={fileInputRef}
            />
          )}
          {step === 2 && <Step2 inputs={inputs} setField={setField} />}
          {step === 3 && <Step3 inputs={inputs} setField={setField} />}
          {step === 4 && <Step4 inputs={inputs} setField={setField} />}
          {step === 5 && (
            <Step5
              inputs={inputs}
              results={results}
              saving={saving}
              saveError={saveError}
              onSave={handleSave}
            />
          )}
        </div>

        <div className="mt-8 flex max-w-3xl items-center justify-between border-t border-brand-800 pt-4">
          <button
            type="button"
            onClick={() => setStep((s) => Math.max(1, s - 1))}
            disabled={step === 1}
            className="inline-flex items-center gap-1.5 rounded-lg border border-brand-800 px-3 py-2 text-sm text-white/80 hover:bg-brand-900 disabled:opacity-30"
          >
            <ArrowLeft className="h-4 w-4" /> Retour
          </button>
          {step < 5 ? (
            <button
              type="button"
              onClick={() => setStep((s) => Math.min(5, s + 1))}
              className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-500 px-3 py-2 text-sm font-semibold text-brand-950 hover:bg-emerald-400"
            >
              Suivant <ArrowRight className="h-4 w-4" />
            </button>
          ) : null}
        </div>
      </div>
    </>
  );
}

function Stepper({
  step,
  onStepClick
}: {
  step: number;
  onStepClick: (s: number) => void;
}) {
  return (
    <ol className="flex flex-wrap gap-2">
      {STEPS.map((s) => {
        const active = s.id === step;
        const done = s.id < step;
        return (
          <li key={s.id}>
            <button
              type="button"
              onClick={() => onStepClick(s.id)}
              className={`flex items-center gap-2 rounded-lg border px-3 py-2 text-xs transition hover:border-emerald-500 hover:text-emerald-200 ${
                active
                  ? "border-emerald-500 bg-emerald-500/10 text-emerald-200"
                  : done
                    ? "border-emerald-700/50 bg-brand-900 text-emerald-300/80"
                    : "border-brand-800 bg-brand-900/40 text-white/40"
              }`}
            >
              <span
                className={`flex h-6 w-6 items-center justify-center rounded-full text-[11px] font-bold ${
                  active
                    ? "bg-emerald-500 text-brand-950"
                    : done
                      ? "bg-emerald-700/40 text-emerald-200"
                      : "bg-brand-800 text-white/50"
                }`}
              >
                {done ? <Check className="h-3.5 w-3.5" /> : s.id}
              </span>
              <span className="hidden font-medium md:inline">
                {s.title}
              </span>
            </button>
          </li>
        );
      })}
    </ol>
  );
}

// -------------------- Steps --------------------

function NumberField({
  label,
  value,
  onChange,
  suffix,
  step = 1,
  hint
}: {
  label: string;
  value: number;
  onChange: (v: number) => void;
  suffix?: string;
  step?: number;
  hint?: string;
}) {
  // Affiche "" quand la valeur est 0 pour ne pas que le « 0 » colle
  // devant ce que l'utilisateur tape. À la perte de focus, on remet
  // 0 (ou la valeur saisie). Bonus : select-all au focus pour
  // remplacer rapidement la valeur existante.
  const display = value === 0 ? "" : String(value);
  return (
    <label className="block">
      <span className="block text-xs font-semibold uppercase tracking-wider text-white/50">
        {label}
      </span>
      <div className="mt-1 flex items-center gap-2">
        <input
          type="number"
          value={display}
          step={step}
          placeholder="0"
          onFocus={(e) => e.currentTarget.select()}
          onChange={(e) => {
            const raw = e.target.value;
            if (raw === "") {
              onChange(0);
            } else {
              const n = Number(raw);
              onChange(Number.isFinite(n) ? n : 0);
            }
          }}
          className="w-full rounded-lg border border-brand-800 bg-brand-900 px-3 py-2 text-sm text-white focus:border-emerald-500 focus:outline-none"
        />
        {suffix ? (
          <span className="text-xs text-white/50">{suffix}</span>
        ) : null}
      </div>
      {hint ? <p className="mt-1 text-[11px] text-white/40">{hint}</p> : null}
    </label>
  );
}

function TextField({
  label,
  value,
  onChange,
  placeholder
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
}) {
  return (
    <label className="block">
      <span className="block text-xs font-semibold uppercase tracking-wider text-white/50">
        {label}
      </span>
      <input
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="mt-1 w-full rounded-lg border border-brand-800 bg-brand-900 px-3 py-2 text-sm text-white placeholder:text-white/30 focus:border-emerald-500 focus:outline-none"
      />
    </label>
  );
}

function Step1({
  inputs,
  setField,
  onUpload,
  extracting,
  extractError,
  extractNotes,
  fileInputRef
}: {
  inputs: AnalyseInputs;
  setField: <K extends keyof AnalyseInputs>(key: K, v: AnalyseInputs[K]) => void;
  onUpload: (f: File) => void;
  extracting: boolean;
  extractError: string | null;
  extractNotes: string | null;
  fileInputRef: React.RefObject<HTMLInputElement | null>;
}) {
  return (
    <section className="space-y-4">
      <h2 className="text-lg font-semibold text-white">Identification</h2>

      <div className="rounded-xl border border-emerald-700/40 bg-emerald-500/5 p-4">
        <div className="flex items-start gap-3">
          <Sparkles className="mt-0.5 h-5 w-5 text-emerald-400" />
          <div className="flex-1">
            <h3 className="text-sm font-semibold text-emerald-200">
              Pré-remplir depuis un document
            </h3>
            <p className="mt-1 text-xs text-white/60">
              Upload une fiche de listing, un rent-roll, un compte de
              taxes ou un état des résultats. Claude extrait
              automatiquement le prix, les loyers, les taxes…
            </p>
            <input
              ref={fileInputRef}
              type="file"
              accept=".pdf,.jpg,.jpeg,.png,.webp,application/pdf,image/*"
              className="hidden"
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) onUpload(f);
                e.target.value = "";
              }}
            />
            <button
              type="button"
              onClick={() => fileInputRef.current?.click()}
              disabled={extracting}
              className="mt-3 inline-flex items-center gap-1.5 rounded-lg bg-emerald-500 px-3 py-2 text-sm font-semibold text-brand-950 hover:bg-emerald-400 disabled:opacity-50"
            >
              {extracting ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Upload className="h-4 w-4" />
              )}
              {extracting ? "Extraction…" : "Choisir un fichier"}
            </button>
            {extractError ? (
              <p className="mt-2 text-xs text-red-300">{extractError}</p>
            ) : null}
            {extractNotes ? (
              <p className="mt-2 text-xs text-emerald-300/80">
                <strong>Notes Claude :</strong> {extractNotes}
              </p>
            ) : null}
          </div>
        </div>
      </div>

      <TextField
        label="Adresse"
        value={inputs.adresse}
        onChange={(v) => setField("adresse", v)}
        placeholder="123 rue Example, Montréal"
      />
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <NumberField
          label="Prix d'achat"
          value={inputs.prixAchat}
          onChange={(v) => setField("prixAchat", v)}
          suffix="$"
        />
        <NumberField
          label="Nombre de logements"
          value={inputs.nombreLogements}
          onChange={(v) => setField("nombreLogements", v)}
        />
      </div>
    </section>
  );
}

function Step2({
  inputs,
  setField
}: {
  inputs: AnalyseInputs;
  setField: <K extends keyof AnalyseInputs>(key: K, v: AnalyseInputs[K]) => void;
}) {
  return (
    <section className="space-y-4">
      <h2 className="text-lg font-semibold text-white">
        Revenus &amp; dépenses actuels
      </h2>
      <NumberField
        label="Revenus locatifs annuels actuels"
        value={inputs.revenusAnnuels}
        onChange={(v) => setField("revenusAnnuels", v)}
        suffix="$/an"
      />
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <NumberField
          label="Taxes municipales"
          value={inputs.taxesMunicipales}
          onChange={(v) => setField("taxesMunicipales", v)}
          suffix="$/an"
        />
        <NumberField
          label="Taxes scolaires"
          value={inputs.taxesScolaires}
          onChange={(v) => setField("taxesScolaires", v)}
          suffix="$/an"
        />
        <NumberField
          label="Assurances"
          value={inputs.assurances}
          onChange={(v) => setField("assurances", v)}
          suffix="$/an"
        />
        <NumberField
          label="Énergie commune"
          value={inputs.energie}
          onChange={(v) => setField("energie", v)}
          suffix="$/an"
          hint="Chauffage, électricité aires communes"
        />
        <NumberField
          label="Autres dépenses"
          value={inputs.autresDepenses}
          onChange={(v) => setField("autresDepenses", v)}
          suffix="$/an"
        />
      </div>
    </section>
  );
}

function Step3({
  inputs,
  setField
}: {
  inputs: AnalyseInputs;
  setField: <K extends keyof AnalyseInputs>(key: K, v: AnalyseInputs[K]) => void;
}) {
  return (
    <section className="space-y-4">
      <h2 className="text-lg font-semibold text-white">
        Hypothèses de refinancement
      </h2>
      <p className="text-xs text-white/50">
        Loyers stabilisés et améliorations qui supportent les scénarios
        SCHL et APH 50.
      </p>
      <NumberField
        label="Nouveau loyer mensuel moyen (post-stabilisation)"
        value={inputs.nouveauLoyerMoyen}
        onChange={(v) => setField("nouveauLoyerMoyen", v)}
        suffix="$/mois"
      />
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <NumberField
          label="Logements ajoutés"
          value={inputs.logementsAjoutes}
          onChange={(v) => setField("logementsAjoutes", v)}
        />
        <NumberField
          label="Thermopompes ajoutées"
          value={inputs.thermopompesAjoutees}
          onChange={(v) => setField("thermopompesAjoutees", v)}
        />
        <NumberField
          label="Réduction coût énergie"
          value={inputs.reductionCoutEnergie}
          onChange={(v) => setField("reductionCoutEnergie", v)}
          step={0.01}
          suffix="0-1"
          hint="Ex: 0.3 = 30% de moins après améliorations"
        />
        <NumberField
          label="Années de portage"
          value={inputs.nombreAnneesPortage}
          onChange={(v) => setField("nombreAnneesPortage", v)}
          suffix="ans"
          hint="Acquisition → refinancement"
        />
      </div>
      <label className="flex items-center gap-2 text-sm text-white/80">
        <input
          type="checkbox"
          checked={inputs.wifi}
          onChange={(e) => setField("wifi", e.target.checked)}
          className="h-4 w-4 rounded border-brand-700 bg-brand-900 text-emerald-500 focus:ring-emerald-500"
        />
        WIFI inclus (5 $/log/mois + 120 $/mois internet)
      </label>
    </section>
  );
}

function Step4({
  inputs,
  setField
}: {
  inputs: AnalyseInputs;
  setField: <K extends keyof AnalyseInputs>(key: K, v: AnalyseInputs[K]) => void;
}) {
  function setFrais<K extends keyof AnalyseInputs["fraisDemarrage"]>(
    key: K,
    v: AnalyseInputs["fraisDemarrage"][K]
  ) {
    setField("fraisDemarrage", { ...inputs.fraisDemarrage, [key]: v });
  }
  return (
    <section className="space-y-4">
      <h2 className="text-lg font-semibold text-white">
        Frais de démarrage &amp; paramètres financiers
      </h2>
      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        <NumberField
          label="TGA (taux global d'actualisation)"
          value={inputs.tga}
          onChange={(v) => setField("tga", v)}
          step={0.001}
          suffix="ex 0.04"
        />
        <NumberField
          label="Taux intérêt achat"
          value={inputs.tauxInteretAchat}
          onChange={(v) => setField("tauxInteretAchat", v)}
          step={0.0025}
          suffix="ex 0.04"
        />
        <NumberField
          label="Taux intérêt refi"
          value={inputs.tauxInteretRefi}
          onChange={(v) => setField("tauxInteretRefi", v)}
          step={0.0025}
          suffix="ex 0.0375"
        />
      </div>

      <h3 className="mt-4 text-sm font-semibold uppercase tracking-wider text-white/60">
        Frais de démarrage
      </h3>
      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        <NumberField
          label="Taxes de bienvenue"
          value={inputs.fraisDemarrage.taxesBienvenue}
          onChange={(v) => setFrais("taxesBienvenue", v)}
          suffix="$"
        />
        <NumberField
          label="Évaluateur 1"
          value={inputs.fraisDemarrage.evaluateur1}
          onChange={(v) => setFrais("evaluateur1", v)}
          suffix="$"
        />
        <NumberField
          label="Évaluateur 2"
          value={inputs.fraisDemarrage.evaluateur2}
          onChange={(v) => setFrais("evaluateur2", v)}
          suffix="$"
        />
        <NumberField
          label="Inspection"
          value={inputs.fraisDemarrage.inspection}
          onChange={(v) => setFrais("inspection", v)}
          suffix="$"
        />
        <NumberField
          label="Avocat"
          value={inputs.fraisDemarrage.avocat}
          onChange={(v) => setFrais("avocat", v)}
          suffix="$"
        />
        <NumberField
          label="Notaire 1"
          value={inputs.fraisDemarrage.notaire1}
          onChange={(v) => setFrais("notaire1", v)}
          suffix="$"
        />
        <NumberField
          label="Notaire 2"
          value={inputs.fraisDemarrage.notaire2}
          onChange={(v) => setFrais("notaire2", v)}
          suffix="$"
        />
        <NumberField
          label="Rapport efficacité"
          value={inputs.fraisDemarrage.rapportEfficacite}
          onChange={(v) => setFrais("rapportEfficacite", v)}
          suffix="$"
        />
        <NumberField
          label="Frais développement"
          value={inputs.fraisDemarrage.fraisDeveloppement}
          onChange={(v) => setFrais("fraisDeveloppement", v)}
          suffix="$"
        />
        <NumberField
          label="Frais négociation"
          value={inputs.fraisDemarrage.fraisNegociation}
          onChange={(v) => setFrais("fraisNegociation", v)}
          suffix="$"
        />
        <NumberField
          label="Frais travaux"
          value={inputs.fraisDemarrage.fraisTravaux}
          onChange={(v) => setFrais("fraisTravaux", v)}
          suffix="$"
        />
      </div>
    </section>
  );
}

function Step5({
  inputs,
  results,
  saving,
  saveError,
  onSave
}: {
  inputs: AnalyseInputs;
  results: ReturnType<typeof calculerAnalyse> | null;
  saving: boolean;
  saveError: string | null;
  onSave: () => void;
}) {
  if (!results) {
    return (
      <p className="text-sm text-red-300">
        Erreur de calcul. Vérifie tes inputs.
      </p>
    );
  }
  const { achat, schl, aph50 } = results;
  return (
    <section className="space-y-4">
      <h2 className="text-lg font-semibold text-white">
        Résultats — 3 scénarios
      </h2>
      <p className="text-xs text-white/50">
        Aperçu rapide. La fiche complète apparaît après sauvegarde.
      </p>
      <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
        <ResultCard
          label="Achat conventionnel"
          tone="neutral"
          rows={[
            ["Prêt accordé", fmt$(achat.pretAccorde)],
            ["Prix d'acquisition", fmt$(achat.prixAcquisition)],
            ["Mise de fonds", fmt$(achat.miseDeFonds || 0), true]
          ]}
        />
        <ResultCard
          label="Refinancement SCHL"
          tone={
            (schl.gainActionnaires ?? 0) >= 0 ? "positive" : "negative"
          }
          rows={[
            ["Prêt accordé", fmt$(schl.pretAccorde)],
            ["Prix d'acquisition", fmt$(schl.prixAcquisition)],
            ["Gain actionnaires", fmt$(schl.gainActionnaires || 0), true]
          ]}
        />
        <ResultCard
          label="Refinancement APH 50"
          tone={
            (aph50.gainActionnaires ?? 0) >= 0 ? "positive" : "negative"
          }
          rows={[
            ["Prêt accordé", fmt$(aph50.pretAccorde)],
            ["Prix d'acquisition", fmt$(aph50.prixAcquisition)],
            ["Gain actionnaires", fmt$(aph50.gainActionnaires || 0), true]
          ]}
        />
      </div>

      {saveError ? (
        <p className="text-sm text-red-300">{saveError}</p>
      ) : null}

      <button
        type="button"
        onClick={onSave}
        disabled={saving}
        className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-500 px-4 py-2.5 text-sm font-semibold text-brand-950 hover:bg-emerald-400 disabled:opacity-50"
      >
        {saving ? (
          <Loader2 className="h-4 w-4 animate-spin" />
        ) : (
          <Check className="h-4 w-4" />
        )}
        {saving ? "Sauvegarde…" : "Sauvegarder l'analyse"}
      </button>
    </section>
  );
}

function ResultCard({
  label,
  tone,
  rows
}: {
  label: string;
  tone: "neutral" | "positive" | "negative";
  rows: Array<[string, string, boolean?]>;
}) {
  const ring =
    tone === "positive"
      ? "border-emerald-700/40 bg-emerald-500/5"
      : tone === "negative"
      ? "border-red-700/40 bg-red-500/5"
      : "border-brand-800 bg-brand-900/40";
  return (
    <div className={`rounded-xl border p-4 ${ring}`}>
      <h3 className="text-sm font-semibold text-white">{label}</h3>
      <dl className="mt-3 space-y-1.5 text-xs">
        {rows.map(([k, v, highlight]) => (
          <div key={k} className="flex items-center justify-between">
            <dt className="text-white/60">{k}</dt>
            <dd
              className={`tabular-nums ${
                highlight ? "text-base font-bold text-white" : "text-white/80"
              }`}
            >
              {v}
            </dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

function fmt$(n: number): string {
  return n.toLocaleString("fr-CA", {
    style: "currency",
    currency: "CAD",
    maximumFractionDigits: 0
  });
}
