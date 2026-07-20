"use client";

/**
 * Menu « Générer ▾ » des lettres/avis TAL d'un bail — composant PARTAGÉ
 * (fiche immeuble, page Baux & paiements, hub locataire, page logement).
 * Les avis marqués `avecParams` ouvrent une modale qui collecte leurs
 * champs propres ; les mentions légales et délais sont bakés dans le PDF
 * (backend services/tal_forms.py).
 */

import { useCallback, useEffect, useState } from "react";
import {
  CheckCircle2,
  Eye,
  FileDown,
  FileSignature,
  Loader2,
  Mail,
  Pencil,
  Trash2,
  X
} from "lucide-react";

import { Link } from "@/i18n/navigation";
import { authedFetch } from "@/lib/auth";

export type BailDocument = {
  id: number;
  bail_id: number | null;
  locataire_id: number | null;
  type: string;
  titre: string;
  params: Record<string, unknown>;
  created_at: string | null;
  envoye_le: string | null;
  envoye_a: string | null;
  ouvert_le: string | null;
  signed_at: string | null;
  signed_by_name: string | null;
};

// Les composants d'une même ligne (Générer ▾ / Envoyer pour signature)
// se resynchronisent via cet événement quand un document est créé.
const DOCS_EVENT = "kratos:documents-changed";

function notifyDocumentsChanged(bailId: number): void {
  window.dispatchEvent(
    new CustomEvent(DOCS_EVENT, { detail: { bailId } })
  );
}

// Catalogue 2026-07-17 : les 5 premiers = formulaires OFFICIELS du TAL
// (PDF gouvernemental rempli tel quel) ; les 2 derniers = lettres maison
// envoyées par courriel SANS signature (avis de retard, avis d'accès).
const TAL_FORMS: {
  code: string;
  label: string;
  avecParams?: boolean;
  officiel?: boolean;
  sansSignature?: boolean;
}[] = [
  {
    code: "avis_modification",
    label: "Avis d'augmentation / modification (TAL-806)",
    avecParams: true,
    officiel: true
  },
  {
    code: "avis_non_reconduction",
    label: "Avis de non-reconduction — locataire (TAL-807)",
    avecParams: true,
    officiel: true
  },
  {
    code: "avis_reprise",
    label: "Avis de reprise de logement (TAL-809)",
    avecParams: true,
    officiel: true
  },
  {
    code: "avis_travaux_majeurs",
    label: "Avis de travaux majeurs (TAL-808)",
    avecParams: true,
    officiel: true
  },
  {
    code: "reponse_cession",
    label: "Réponse à une cession de bail (TAL-828)",
    avecParams: true,
    officiel: true
  },
  {
    code: "rappel_paiement",
    label: "Avis de retard de paiement",
    avecParams: true,
    sansSignature: true
  },
  {
    code: "avis_acces",
    label: "Avis d'accès au logement",
    avecParams: true,
    sansSignature: true
  }
];

// Types envoyés par simple courriel (PDF joint) — aucun flux de
// signature en ligne.
export const SANS_SIGNATURE = new Set([
  ...TAL_FORMS.filter((t) => t.sansSignature).map((t) => t.code),
  // Document personnalisé dont le modèle décoche « signature requise ».
  "personnalise_info"
]);

const MOI_MEME = new Set(["moi-même", "moi-meme", "moi même", "moi meme"]);

async function downloadTalPdf(
  bailId: number,
  code: string,
  body: Record<string, unknown>
): Promise<void> {
  const res = await authedFetch(
    `/api/v1/immobilier/baux/${bailId}/tal/${code}.pdf`,
    { method: "POST", body: JSON.stringify(body) }
  );
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `${code.replace(/_/g, "-")}-bail-${bailId}.pdf`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
  // Le backend a aussi CONSERVÉ le document — préviens le bouton
  // « Envoyer pour signature » de la même ligne.
  notifyDocumentsChanged(bailId);
}

// Modèles PERSONNALISÉS (règlement d'immeuble, contrat de chambreur…)
// créés dans Paramètres → Modèles de documents. Cache module (60 s) —
// le menu apparaît sur chaque ligne de bail, inutile de re-fetcher.
type PersoModele = {
  id: number;
  nom: string;
  titre: string | null;
  signature_requise: boolean;
  has_pdf: boolean;
};
let persoCache: { at: number; list: PersoModele[] } | null = null;
async function fetchPersoModeles(): Promise<PersoModele[]> {
  if (persoCache && Date.now() - persoCache.at < 60_000)
    return persoCache.list;
  try {
    const r = await authedFetch("/api/v1/immobilier/docs-perso/modeles");
    if (r.ok) {
      persoCache = {
        at: Date.now(),
        list: (await r.json()) as PersoModele[]
      };
    }
  } catch {
    /* silencieux — le menu TAL reste utilisable */
  }
  return persoCache?.list ?? [];
}

export function TalFormDropdown({ bailId }: { bailId: number }) {
  const [open, setOpen] = useState(false);
  const [downloading, setDownloading] = useState<string | null>(null);
  const [paramsCode, setParamsCode] = useState<string | null>(null);
  const [perso, setPerso] = useState<PersoModele[] | null>(null);

  useEffect(() => {
    if (!open || perso !== null) return;
    void fetchPersoModeles().then(setPerso);
  }, [open, perso]);

  async function download(code: string) {
    setDownloading(code);
    try {
      await downloadTalPdf(bailId, code, {});
      setOpen(false);
    } catch (e) {
      alert((e as Error).message);
    } finally {
      setDownloading(null);
    }
  }

  async function genererPerso(m: PersoModele) {
    setDownloading(`perso-${m.id}`);
    try {
      const r = await authedFetch(
        `/api/v1/immobilier/baux/${bailId}/docs-perso/${m.id}`,
        { method: "POST" }
      );
      if (!r.ok)
        throw new Error((await r.text()).slice(0, 200) || `HTTP ${r.status}`);
      notifyDocumentsChanged(bailId);
      setOpen(false);
    } catch (e) {
      alert((e as Error).message);
    } finally {
      setDownloading(null);
    }
  }

  return (
    <div className="relative inline-block">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="btn-secondary btn-xs"
        title="Générer une lettre ou un avis TAL pour ce bail"
      >
        Générer ▾
      </button>
      {open ? (
        <div className="absolute right-0 z-30 mt-1 w-60 rounded-lg border border-brand-700 bg-brand-950 py-1 shadow-2xl">
          {TAL_FORMS.map((f) => (
            <button
              key={f.code}
              type="button"
              onClick={() => {
                if (f.avecParams) {
                  setParamsCode(f.code);
                  setOpen(false);
                } else {
                  void download(f.code);
                }
              }}
              disabled={downloading === f.code}
              className="block w-full px-3 py-1.5 text-left text-xs text-white/80 hover:bg-brand-900 hover:text-white disabled:opacity-50"
            >
              {downloading === f.code ? "Génération…" : f.label}
            </button>
          ))}
          {perso && perso.length > 0 ? (
            <>
              <div className="mx-3 my-1 border-t border-brand-800" />
              <div className="px-3 py-1 text-[10px] font-semibold uppercase tracking-wider text-white/40">
                Mes documents
              </div>
              {perso.map((m) => (
                <button
                  key={m.id}
                  type="button"
                  onClick={() => void genererPerso(m)}
                  disabled={downloading === `perso-${m.id}`}
                  title={
                    m.signature_requise
                      ? "Généré puis envoyable pour signature en ligne"
                      : "Généré puis envoyable par courriel (suivi d'ouverture)"
                  }
                  className="block w-full px-3 py-1.5 text-left text-xs text-white/80 hover:bg-brand-900 hover:text-white disabled:opacity-50"
                >
                  {downloading === `perso-${m.id}`
                    ? "Génération…"
                    : m.titre || m.nom}
                </button>
              ))}
            </>
          ) : null}
        </div>
      ) : null}
      {paramsCode ? (
        <TalAvisModal
          bailId={bailId}
          code={paramsCode}
          onClose={() => setParamsCode(null)}
        />
      ) : null}
    </div>
  );
}

/** Modale de paramètres pour les avis qui exigent des champs propres
 * (reprise, travaux majeurs, accès, réponse cession). */
function TalAvisModal({
  bailId,
  code,
  initialParams,
  onClose,
  onGenerated
}: {
  bailId: number;
  code: string;
  // Paramètres d'un document existant (« Modifier ») — régénère une
  // NOUVELLE version avec les champs préremplis.
  initialParams?: Record<string, unknown>;
  onClose: () => void;
  onGenerated?: () => void;
}) {
  const [f, setF] = useState<Record<string, string>>(() => {
    const base: Record<string, string> = {
      modif_mode: "nouveau_loyer",
      cession_decision: "accepte",
      travaux_evacuation: "non",
      travaux_duree_unite: "jours",
      reprise_pour: "moi"
    };
    for (const [k, v] of Object.entries(initialParams || {})) {
      if (v == null) continue;
      if (typeof v === "boolean") {
        base[k] = v ? "oui" : "non";
      } else {
        base[k] = String(v);
      }
    }
    // Normalisation des anciens documents (« Modifier » sur un doc créé
    // avant le passage aux formulaires officiels).
    if (base.mois_concerne && base.mois_concerne.length >= 7) {
      base.mois_concerne = base.mois_concerne.slice(0, 7);
    }
    if (!initialParams?.cession_decision && base.cession_accepte === "non") {
      base.cession_decision = "refus_serieux";
    }
    if (
      base.reprise_beneficiaire &&
      !MOI_MEME.has(base.reprise_beneficiaire.trim().toLowerCase())
    ) {
      base.reprise_pour = "proche";
    }
    return base;
  });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const set = (k: string) => (v: string) =>
    setF((prev) => ({ ...prev, [k]: v }));

  const titre =
    TAL_FORMS.find((t) => t.code === code)?.label || "Paramètres de l'avis";

  const valid = (() => {
    switch (code) {
      case "avis_modification": {
        const mode = f.modif_mode || "nouveau_loyer";
        if (mode === "nouveau_loyer") return !!f.nouveau_loyer;
        if (mode === "hausse_montant") return !!f.hausse_montant;
        return !!f.hausse_pct;
      }
      case "avis_non_reconduction":
        return true;
      case "rappel_paiement":
        return !!(f.montant_du && f.mois_concerne);
      case "avis_reprise":
        return (
          f.reprise_pour !== "proche" || !!f.reprise_beneficiaire?.trim()
        );
      case "avis_travaux_majeurs":
        return !!(f.travaux_description?.trim() && f.travaux_date_debut);
      case "avis_acces":
        return !!(f.acces_date && f.acces_motif?.trim());
      case "reponse_cession": {
        const d = f.cession_decision || "accepte";
        if (d === "accepte") return !!f.cession_date;
        if (d === "refus_autre")
          return !!(f.cession_date && f.cession_motif_refus?.trim());
        return !!f.cession_motif_refus?.trim();
      }
      default:
        return true;
    }
  })();

  async function generer() {
    if (!valid) return;
    setBusy(true);
    setErr(null);
    const num = (s?: string) =>
      s?.trim() ? Number(s.replace(/\s/g, "").replace(",", ".")) : null;
    const body: Record<string, unknown> = {};
    if (code === "avis_modification") {
      const mode = f.modif_mode || "nouveau_loyer";
      body.modif_mode = mode;
      if (mode === "nouveau_loyer") body.nouveau_loyer = num(f.nouveau_loyer);
      else if (mode === "hausse_montant")
        body.hausse_montant = num(f.hausse_montant);
      else body.hausse_pct = num(f.hausse_pct);
      body.nouvelle_date_debut = f.nouvelle_date_debut || null;
      body.nouvelle_date_fin = f.nouvelle_date_fin || null;
      body.motif = f.motif?.trim() || null;
    } else if (code === "avis_non_reconduction") {
      body.depart_date = f.depart_date || null;
    } else if (code === "rappel_paiement") {
      body.montant_du = num(f.montant_du);
      body.mois_concerne = f.mois_concerne
        ? `${f.mois_concerne.slice(0, 7)}-01`
        : null;
    } else if (code === "avis_reprise") {
      if (f.reprise_pour === "proche") {
        body.reprise_beneficiaire = f.reprise_beneficiaire?.trim();
        body.reprise_lien = f.reprise_lien?.trim() || null;
      } else {
        body.reprise_lien = "moi-même";
      }
      body.reprise_date = f.reprise_date || null;
    } else if (code === "avis_travaux_majeurs") {
      body.travaux_description = f.travaux_description?.trim();
      body.travaux_date_debut = f.travaux_date_debut;
      body.travaux_duree_valeur = f.travaux_duree_valeur?.trim() || null;
      body.travaux_duree_unite = f.travaux_duree_unite || "jours";
      body.travaux_evacuation = f.travaux_evacuation === "oui";
      if (f.travaux_evacuation === "oui") {
        body.travaux_evacuation_du = f.travaux_evacuation_du || null;
        body.travaux_evacuation_au = f.travaux_evacuation_au || null;
        body.travaux_indemnite = num(f.travaux_indemnite);
      }
      body.travaux_conditions = f.travaux_conditions?.trim() || null;
    } else if (code === "avis_acces") {
      body.acces_date = f.acces_date;
      body.acces_plage = f.acces_plage?.trim() || null;
      body.acces_motif = f.acces_motif?.trim();
    } else if (code === "reponse_cession") {
      const d = f.cession_decision || "accepte";
      body.cession_decision = d;
      body.cession_date = f.cession_date || null;
      body.cession_motif_refus =
        d === "accepte" ? null : f.cession_motif_refus?.trim();
    }
    try {
      await downloadTalPdf(bailId, code, body);
      onGenerated?.();
      onClose();
    } catch (e) {
      setErr(`Génération échouée : ${(e as Error).message}`);
    } finally {
      setBusy(false);
    }
  }

  const inputCls =
    "mt-0.5 block w-full rounded-md border border-brand-800 bg-brand-950 px-2 py-1.5 text-xs text-white outline-none focus:border-accent-500";
  const labelCls = "block text-[11px] font-semibold text-white/60";

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/70 p-4 backdrop-blur-sm">
      <div className="my-8 w-full max-w-md rounded-2xl border border-brand-800 bg-brand-950 shadow-2xl">
        <div className="flex items-center justify-between border-b border-brand-800 px-5 py-3">
          <h2 className="text-sm font-bold uppercase tracking-wider text-accent-500">
            {titre}
          </h2>
          <button type="button" onClick={onClose} className="btn-ghost btn-xs">
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="grid gap-3 p-5">
          {code === "avis_modification" ? (
            <>
              <p className="text-xs text-white/50">
                Formulaire officiel TAL-806, prérempli avec le bail. À
                transmettre de 3 à 6 mois avant la fin du bail (12 mois
                et plus) ; le locataire a 1 mois pour répondre.
              </p>
              <label className={labelCls}>
                Forme de la hausse
                <select
                  value={f.modif_mode || "nouveau_loyer"}
                  onChange={(e) => set("modif_mode")(e.target.value)}
                  className={inputCls}
                >
                  <option value="nouveau_loyer" className="bg-brand-950 text-white">
                    Nouveau loyer ($ / mois)
                  </option>
                  <option value="hausse_montant" className="bg-brand-950 text-white">
                    Hausse en dollars (+ $ / mois)
                  </option>
                  <option value="hausse_pct" className="bg-brand-950 text-white">
                    Hausse en pourcentage (%)
                  </option>
                </select>
              </label>
              {(f.modif_mode || "nouveau_loyer") === "nouveau_loyer" ? (
                <label className={labelCls}>
                  Nouveau loyer mensuel ($) *
                  <input
                    inputMode="decimal"
                    value={f.nouveau_loyer || ""}
                    onChange={(e) => set("nouveau_loyer")(e.target.value)}
                    placeholder="ex. 1300"
                    className={inputCls}
                  />
                </label>
              ) : f.modif_mode === "hausse_montant" ? (
                <label className={labelCls}>
                  Montant de la hausse ($ / mois) *
                  <input
                    inputMode="decimal"
                    value={f.hausse_montant || ""}
                    onChange={(e) => set("hausse_montant")(e.target.value)}
                    placeholder="ex. 50"
                    className={inputCls}
                  />
                </label>
              ) : (
                <label className={labelCls}>
                  Pourcentage de la hausse (%) *
                  <input
                    inputMode="decimal"
                    value={f.hausse_pct || ""}
                    onChange={(e) => set("hausse_pct")(e.target.value)}
                    placeholder="ex. 4"
                    className={inputCls}
                  />
                </label>
              )}
              <div className="grid grid-cols-2 gap-3">
                <label className={labelCls}>
                  Bail renouvelé du
                  <input
                    type="date"
                    value={f.nouvelle_date_debut || ""}
                    onChange={(e) =>
                      set("nouvelle_date_debut")(e.target.value)
                    }
                    className={inputCls}
                  />
                </label>
                <label className={labelCls}>
                  au
                  <input
                    type="date"
                    value={f.nouvelle_date_fin || ""}
                    onChange={(e) =>
                      set("nouvelle_date_fin")(e.target.value)
                    }
                    className={inputCls}
                  />
                </label>
              </div>
              <p className="text-[10px] text-white/40">
                Laisse les dates vides pour reprendre automatiquement la
                durée du bail actuel.
              </p>
              <label className={labelCls}>
                Autre(s) modification(s) (garage, chauffage…)
                <textarea
                  value={f.motif || ""}
                  onChange={(e) => set("motif")(e.target.value)}
                  rows={2}
                  placeholder="Laisser vide si seule la hausse s'applique"
                  className={inputCls}
                />
              </label>
            </>
          ) : null}

          {code === "avis_non_reconduction" ? (
            <>
              <p className="text-xs text-white/50">
                Formulaire officiel TAL-807 — avis donné <b>par le
                locataire</b> qui quitte à la fin de son bail
                (art. 1946 C.c.Q.). Envoie-le-lui pour signature en
                ligne : c&apos;est lui qui le signe.
              </p>
              <label className={labelCls}>
                Date de départ (vide = fin du bail)
                <input
                  type="date"
                  value={f.depart_date || ""}
                  onChange={(e) => set("depart_date")(e.target.value)}
                  className={inputCls}
                />
              </label>
            </>
          ) : null}

          {code === "rappel_paiement" ? (
            <>
              <p className="text-xs text-white/50">
                Paiement exigé <b>immédiatement</b>. S&apos;envoie par
                courriel (PDF joint) — aucune signature requise.
              </p>
              <div className="grid grid-cols-2 gap-3">
                <label className={labelCls}>
                  Montant dû ($) *
                  <input
                    inputMode="decimal"
                    value={f.montant_du || ""}
                    onChange={(e) => set("montant_du")(e.target.value)}
                    placeholder="ex. 1250"
                    className={inputCls}
                  />
                </label>
                <label className={labelCls}>
                  Mois concerné *
                  <input
                    type="month"
                    value={f.mois_concerne || ""}
                    onChange={(e) => set("mois_concerne")(e.target.value)}
                    className={inputCls}
                  />
                </label>
              </div>
            </>
          ) : null}

          {code === "avis_reprise" ? (
            <>
              <p className="text-xs text-white/50">
                Formulaire officiel TAL-809. À transmettre au moins 6 mois
                avant la fin du bail ; le locataire a 1 mois pour répondre
                (silence = refus).
              </p>
              <label className={labelCls}>
                Le logement sera habité par
                <select
                  value={f.reprise_pour || "moi"}
                  onChange={(e) => set("reprise_pour")(e.target.value)}
                  className={inputCls}
                >
                  <option value="moi" className="bg-brand-950 text-white">
                    Moi-même (le locateur-propriétaire)
                  </option>
                  <option value="proche" className="bg-brand-950 text-white">
                    Un proche (parent, enfant…)
                  </option>
                </select>
              </label>
              {f.reprise_pour === "proche" ? (
                <div className="grid grid-cols-2 gap-3">
                  <label className={labelCls}>
                    Nom du bénéficiaire *
                    <input
                      value={f.reprise_beneficiaire || ""}
                      onChange={(e) =>
                        set("reprise_beneficiaire")(e.target.value)
                      }
                      placeholder="ex. Océane Meuser"
                      className={inputCls}
                    />
                  </label>
                  <label className={labelCls}>
                    Lien de parenté
                    <input
                      value={f.reprise_lien || ""}
                      onChange={(e) => set("reprise_lien")(e.target.value)}
                      placeholder="ex. ma conjointe, mon père…"
                      className={inputCls}
                    />
                  </label>
                </div>
              ) : null}
              <label className={labelCls}>
                Date de reprise (bail à durée indéterminée seulement)
                <input
                  type="date"
                  value={f.reprise_date || ""}
                  onChange={(e) => set("reprise_date")(e.target.value)}
                  className={inputCls}
                />
              </label>
              <p className="text-[10px] text-white/40">
                Bail à durée fixe : la date de fin du bail est reprise
                automatiquement sur le formulaire.
              </p>
            </>
          ) : null}

          {code === "avis_travaux_majeurs" ? (
            <>
              <p className="text-xs text-white/50">
                Formulaire officiel TAL-808. Préavis de 10 jours (3 mois
                si évacuation de plus de 7 jours).
              </p>
              <label className={labelCls}>
                Nature des travaux *
                <textarea
                  value={f.travaux_description || ""}
                  onChange={(e) =>
                    set("travaux_description")(e.target.value)
                  }
                  rows={3}
                  placeholder="ex. Réfection complète de la salle de bain"
                  className={inputCls}
                />
              </label>
              <div className="grid grid-cols-3 gap-3">
                <label className={labelCls}>
                  Date de début *
                  <input
                    type="date"
                    value={f.travaux_date_debut || ""}
                    onChange={(e) =>
                      set("travaux_date_debut")(e.target.value)
                    }
                    className={inputCls}
                  />
                </label>
                <label className={labelCls}>
                  Durée estimée
                  <input
                    inputMode="numeric"
                    value={f.travaux_duree_valeur || ""}
                    onChange={(e) =>
                      set("travaux_duree_valeur")(e.target.value)
                    }
                    placeholder="ex. 2"
                    className={inputCls}
                  />
                </label>
                <label className={labelCls}>
                  Unité
                  <select
                    value={f.travaux_duree_unite || "jours"}
                    onChange={(e) =>
                      set("travaux_duree_unite")(e.target.value)
                    }
                    className={inputCls}
                  >
                    <option value="jours" className="bg-brand-950 text-white">
                      jours
                    </option>
                    <option value="semaines" className="bg-brand-950 text-white">
                      semaines
                    </option>
                    <option value="mois" className="bg-brand-950 text-white">
                      mois
                    </option>
                  </select>
                </label>
              </div>
              <label className="flex cursor-pointer items-center gap-2 text-xs text-white/80">
                <input
                  type="checkbox"
                  checked={f.travaux_evacuation === "oui"}
                  onChange={(e) =>
                    set("travaux_evacuation")(
                      e.target.checked ? "oui" : "non"
                    )
                  }
                  className="h-3.5 w-3.5 accent-accent-500"
                />
                Évacuation temporaire requise
              </label>
              {f.travaux_evacuation === "oui" ? (
                <div className="grid grid-cols-3 gap-3">
                  <label className={labelCls}>
                    Évacuation du
                    <input
                      type="date"
                      value={f.travaux_evacuation_du || ""}
                      onChange={(e) =>
                        set("travaux_evacuation_du")(e.target.value)
                      }
                      className={inputCls}
                    />
                  </label>
                  <label className={labelCls}>
                    au
                    <input
                      type="date"
                      value={f.travaux_evacuation_au || ""}
                      onChange={(e) =>
                        set("travaux_evacuation_au")(e.target.value)
                      }
                      className={inputCls}
                    />
                  </label>
                  <label className={labelCls}>
                    Indemnité offerte ($)
                    <input
                      inputMode="decimal"
                      value={f.travaux_indemnite || ""}
                      onChange={(e) =>
                        set("travaux_indemnite")(e.target.value)
                      }
                      placeholder="0.00"
                      className={inputCls}
                    />
                  </label>
                </div>
              ) : null}
              <label className={labelCls}>
                Autres conditions (facultatif)
                <textarea
                  value={f.travaux_conditions || ""}
                  onChange={(e) =>
                    set("travaux_conditions")(e.target.value)
                  }
                  rows={2}
                  placeholder="ex. accès à l'eau coupé de 9 h à 12 h le premier jour"
                  className={inputCls}
                />
              </label>
            </>
          ) : null}

          {code === "avis_acces" ? (
            <>
              <p className="text-xs text-white/50">
                Préavis de 24 h — visite entre 9 h et 21 h (travaux :
                7 h à 19 h).
              </p>
              <div className="grid grid-cols-2 gap-3">
                <label className={labelCls}>
                  Date *
                  <input
                    type="date"
                    value={f.acces_date || ""}
                    onChange={(e) => set("acces_date")(e.target.value)}
                    className={inputCls}
                  />
                </label>
                <label className={labelCls}>
                  Plage horaire
                  <input
                    value={f.acces_plage || ""}
                    onChange={(e) => set("acces_plage")(e.target.value)}
                    placeholder="ex. entre 9 h et 12 h"
                    className={inputCls}
                  />
                </label>
              </div>
              <label className={labelCls}>
                Motif *
                <input
                  value={f.acces_motif || ""}
                  onChange={(e) => set("acces_motif")(e.target.value)}
                  placeholder="ex. vérification de l'état du logement, travaux mineurs…"
                  className={inputCls}
                />
              </label>
            </>
          ) : null}

          {code === "reponse_cession" ? (
            <>
              <p className="text-xs text-white/50">
                Formulaire officiel TAL-828 (avis reçus depuis le
                21 février 2024). Réponse à transmettre dans les
                15 jours — sans réponse, tu es réputé avoir consenti.
              </p>
              <label className={labelCls}>
                Décision
                <select
                  value={f.cession_decision || "accepte"}
                  onChange={(e) => set("cession_decision")(e.target.value)}
                  className={inputCls}
                >
                  <option value="accepte" className="bg-brand-950 text-white">
                    J&apos;accepte la cession de bail
                  </option>
                  <option
                    value="refus_serieux"
                    className="bg-brand-950 text-white"
                  >
                    Je refuse — motif sérieux (le bail continue)
                  </option>
                  <option
                    value="refus_autre"
                    className="bg-brand-950 text-white"
                  >
                    Je refuse — autre motif (le bail est résilié)
                  </option>
                </select>
              </label>
              {(f.cession_decision || "accepte") !== "refus_serieux" ? (
                <label className={labelCls}>
                  Date de cession (inscrite dans l&apos;avis du locataire) *
                  <input
                    type="date"
                    value={f.cession_date || ""}
                    onChange={(e) => set("cession_date")(e.target.value)}
                    className={inputCls}
                  />
                </label>
              ) : null}
              {(f.cession_decision || "accepte") !== "accepte" ? (
                <label className={labelCls}>
                  Motif du refus *
                  <textarea
                    value={f.cession_motif_refus || ""}
                    onChange={(e) =>
                      set("cession_motif_refus")(e.target.value)
                    }
                    rows={3}
                    placeholder="ex. capacité de payer insuffisante du candidat…"
                    className={inputCls}
                  />
                </label>
              ) : null}
            </>
          ) : null}

          {err ? (
            <p className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">
              {err}
            </p>
          ) : null}

          <div className="flex items-center justify-end gap-2 border-t border-brand-800 pt-3">
            <button
              type="button"
              onClick={onClose}
              disabled={busy}
              className="btn-secondary btn-sm"
            >
              Annuler
            </button>
            <button
              type="button"
              onClick={() => void generer()}
              disabled={busy || !valid}
              className="btn-accent btn-sm disabled:opacity-50"
            >
              {busy ? (
                <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />
              ) : (
                <FileDown className="mr-1 h-3.5 w-3.5" />
              )}
              Générer le PDF
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

/** Bouton « Envoyer pour signature » PILOTÉ PAR DOCUMENT (retour Phil
 * 2026-07-17) : grisé tant qu'aucun document n'a été généré pour le
 * bail ; sinon ouvre la bibliothèque des documents (voir / modifier /
 * envoyer / supprimer, avec états envoyé·ouvert·signé). */
export function BailSignature({ bailId }: { bailId: number }) {
  const [docs, setDocs] = useState<BailDocument[] | null>(null);
  const [open, setOpen] = useState(false);

  const load = useCallback(async () => {
    try {
      const r = await authedFetch(
        `/api/v1/immobilier/baux/${bailId}/documents`
      );
      if (r.ok) setDocs((await r.json()) as BailDocument[]);
    } catch {
      /* silencieux */
    }
  }, [bailId]);

  useEffect(() => {
    void load();
    const handler = (e: Event) => {
      const detail = (e as CustomEvent).detail as { bailId?: number };
      if (detail?.bailId === bailId) void load();
    };
    window.addEventListener(DOCS_EVENT, handler);
    return () => window.removeEventListener(DOCS_EVENT, handler);
  }, [bailId, load]);

  const n = docs?.length ?? 0;
  const signe = (docs || []).some((d) => d.signed_at);
  const envoye = !signe && (docs || []).some((d) => d.envoye_le);
  // Tous les documents du bail sont « sans signature » (avis de retard,
  // accès) → le bouton parle d'envoi par courriel, pas de signature.
  const tousCourriel =
    n > 0 && (docs || []).every((d) => SANS_SIGNATURE.has(d.type));

  return (
    <>
      <button
        type="button"
        disabled={n === 0}
        onClick={() => setOpen(true)}
        title={
          n === 0
            ? "Génère d'abord un document (Générer ▾) — le bouton s'activera"
            : `${n} document${n > 1 ? "s" : ""} — ouvrir la bibliothèque`
        }
        className={`inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1 text-xs font-semibold transition disabled:cursor-not-allowed disabled:opacity-40 ${
          signe
            ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-300"
            : envoye
              ? "border-sky-400/40 bg-sky-500/10 text-sky-300 hover:bg-sky-500/20"
              : "border-accent-500/40 bg-accent-500/10 text-accent-500 hover:bg-accent-500/20"
        }`}
      >
        {signe ? (
          <>
            <CheckCircle2 className="h-3.5 w-3.5" /> Signé
          </>
        ) : envoye ? (
          <>
            <Mail className="h-3.5 w-3.5" /> Envoyé — suivre
          </>
        ) : tousCourriel ? (
          <>
            <Mail className="h-3.5 w-3.5" /> Envoyer par courriel
          </>
        ) : (
          <>
            <FileSignature className="h-3.5 w-3.5" /> Envoyer pour signature
          </>
        )}
      </button>
      {open ? (
        <DocumentsModal
          docs={docs || []}
          onClose={() => setOpen(false)}
          onChanged={() => void load()}
        />
      ) : null}
    </>
  );
}

const TYPES_AVEC_PARAMS = new Set(
  TAL_FORMS.filter((t) => t.avecParams).map((t) => t.code)
);

function fmtDateTime(iso: string | null): string {
  if (!iso) return "";
  try {
    return new Date(iso).toLocaleString("fr-CA", {
      dateStyle: "short",
      timeStyle: "short"
    });
  } catch {
    return iso;
  }
}

/** Liste de documents RÉUTILISABLE (modale du bail + sections Documents
 * des fiches locataire/logement) : voir, modifier (nouvelle version),
 * envoyer (signature en ligne ou courriel PDF joint), supprimer. */
export function DocsList({
  docs,
  onChanged,
  emptyText
}: {
  docs: BailDocument[];
  onChanged: () => void;
  emptyText?: string;
}) {
  const [busyId, setBusyId] = useState<number | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [editDoc, setEditDoc] = useState<BailDocument | null>(null);
  const [flash, setFlash] = useState<string | null>(null);

  async function voir(d: BailDocument) {
    setBusyId(d.id);
    setErr(null);
    try {
      const r = await authedFetch(
        `/api/v1/immobilier/documents/${d.id}/pdf`
      );
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const blob = await r.blob();
      const url = URL.createObjectURL(blob);
      window.open(url, "_blank");
      window.setTimeout(() => URL.revokeObjectURL(url), 60000);
    } catch (e) {
      setErr(`Ouverture échouée : ${(e as Error).message}`);
    } finally {
      setBusyId(null);
    }
  }

  async function envoyer(d: BailDocument) {
    const sansSig = SANS_SIGNATURE.has(d.type);
    if (
      !window.confirm(
        sansSig
          ? `Envoyer « ${d.titre} » au locataire par courriel (PDF joint) ?`
          : `Envoyer « ${d.titre} » au locataire pour signature en ligne ?`
      )
    )
      return;
    setBusyId(d.id);
    setErr(null);
    try {
      const r = await authedFetch(
        `/api/v1/immobilier/documents/${d.id}/${
          sansSig ? "envoyer-courriel" : "envoyer-signature"
        }`,
        { method: "POST", body: JSON.stringify({}) }
      );
      if (!r.ok)
        throw new Error(
          (await r.text()).slice(0, 200) || `HTTP ${r.status}`
        );
      const res = (await r.json()) as { envoye_a: string };
      setFlash(
        sansSig
          ? `Envoyé à ${res.envoye_a} (PDF joint).`
          : `Envoyé à ${res.envoye_a} — suivi d'ouverture actif.`
      );
      onChanged();
    } catch (e) {
      setErr(`Envoi échoué : ${(e as Error).message}`);
    } finally {
      setBusyId(null);
    }
  }

  async function supprimer(d: BailDocument) {
    if (!window.confirm(`Supprimer « ${d.titre} » ?`)) return;
    setBusyId(d.id);
    setErr(null);
    try {
      const r = await authedFetch(
        `/api/v1/immobilier/documents/${d.id}`,
        { method: "DELETE" }
      );
      if (!r.ok && r.status !== 204)
        throw new Error(
          (await r.text()).slice(0, 200) || `HTTP ${r.status}`
        );
      onChanged();
    } catch (e) {
      setErr(`Suppression échouée : ${(e as Error).message}`);
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div className="space-y-3">
      {flash ? (
            <p className="rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-xs text-emerald-300">
              {flash}
            </p>
          ) : null}
          {err ? (
            <p className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">
              {err}
            </p>
          ) : null}

          {docs.length === 0 ? (
            <p className="rounded-xl border border-dashed border-brand-700 px-4 py-3 text-xs text-white/40">
              {emptyText ||
                "Aucun document — utilise « Générer ▾ » pour en créer un."}
            </p>
          ) : (
            <ul className="divide-y divide-brand-800 rounded-xl border border-brand-800">
              {docs.map((d) => (
                <li
                  key={d.id}
                  className="flex flex-wrap items-center justify-between gap-2 px-3 py-2.5"
                >
                  <span className="min-w-0">
                    <span className="text-sm font-medium text-white">
                      {d.titre}
                    </span>
                    {SANS_SIGNATURE.has(d.type) ? (
                      <span className="ml-2 rounded bg-white/10 px-1.5 py-0.5 text-[9px] uppercase tracking-wide text-white/50">
                        courriel
                      </span>
                    ) : null}
                    <span className="ml-2 text-[10px] text-white/40">
                      {fmtDateTime(d.created_at)}
                    </span>
                    <span className="mt-0.5 block text-[11px]">
                      {d.signed_at ? (
                        <span className="text-emerald-300">
                          Signé par {d.signed_by_name}{" "}
                          {fmtDateTime(d.signed_at)}
                        </span>
                      ) : d.ouvert_le ? (
                        <span className="text-sky-300">
                          Ouvert {fmtDateTime(d.ouvert_le)} — pas encore
                          signé
                        </span>
                      ) : d.envoye_le ? (
                        <span className="text-white/50">
                          Envoyé à {d.envoye_a} {fmtDateTime(d.envoye_le)}
                        </span>
                      ) : (
                        <span className="text-white/40">
                          Brouillon — pas encore envoyé
                        </span>
                      )}
                    </span>
                  </span>
                  <span className="flex flex-shrink-0 items-center gap-1.5">
                    <button
                      type="button"
                      onClick={() => void voir(d)}
                      disabled={busyId === d.id}
                      className="btn-secondary btn-xs"
                      title="Voir le PDF"
                    >
                      <Eye className="h-3 w-3" />
                    </button>
                    {TYPES_AVEC_PARAMS.has(d.type) && !d.signed_at ? (
                      <button
                        type="button"
                        onClick={() => setEditDoc(d)}
                        disabled={busyId === d.id}
                        className="btn-secondary btn-xs"
                        title="Modifier (rouvre le formulaire prérempli — nouvelle version)"
                      >
                        <Pencil className="h-3 w-3" />
                      </button>
                    ) : null}
                    {!d.signed_at ? (
                      <button
                        type="button"
                        onClick={() => void envoyer(d)}
                        disabled={busyId === d.id}
                        className="btn-accent btn-xs"
                        title={
                          d.envoye_le
                            ? "Renvoyer pour signature"
                            : "Envoyer pour signature"
                        }
                      >
                        {busyId === d.id ? (
                          <Loader2 className="h-3 w-3 animate-spin" />
                        ) : (
                          <Mail className="h-3 w-3" />
                        )}
                        {d.envoye_le ? "Renvoyer" : "Envoyer"}
                      </button>
                    ) : null}
                    {!d.signed_at ? (
                      <button
                        type="button"
                        onClick={() => void supprimer(d)}
                        disabled={busyId === d.id}
                        className="btn-outline-rose btn-xs"
                        title="Supprimer"
                      >
                        <Trash2 className="h-3 w-3" />
                      </button>
                    ) : null}
                  </span>
                </li>
              ))}
            </ul>
          )}

      {editDoc && editDoc.bail_id != null ? (
        <TalAvisModal
          bailId={editDoc.bail_id}
          code={editDoc.type}
          initialParams={editDoc.params}
          onClose={() => setEditDoc(null)}
          onGenerated={onChanged}
        />
      ) : null}
    </div>
  );
}

/** Bibliothèque des documents d'un bail (modale ouverte par le bouton
 * « Envoyer pour signature »). */
function DocumentsModal({
  docs,
  onClose,
  onChanged
}: {
  docs: BailDocument[];
  onClose: () => void;
  onChanged: () => void;
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/70 p-4 backdrop-blur-sm">
      <div className="my-8 w-full max-w-2xl rounded-2xl border border-brand-800 bg-brand-950 shadow-2xl">
        <div className="flex items-center justify-between border-b border-brand-800 px-5 py-3">
          <h2 className="text-sm font-bold uppercase tracking-wider text-accent-500">
            Documents du bail
          </h2>
          <button type="button" onClick={onClose} className="btn-ghost btn-xs">
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="space-y-3 p-5">
          <p className="text-xs text-white/50">
            Chaque génération est conservée ici. « Modifier » rouvre le
            formulaire prérempli et crée une nouvelle version ; « Envoyer »
            transmet le document au locataire — signature en ligne avec
            preuve d&apos;ouverture, ou simple courriel avec PDF joint pour
            les avis sans signature (retard, accès).
          </p>
          <DocsList docs={docs} onChanged={onChanged} />
          <div className="flex items-center justify-end border-t border-brand-800 pt-3">
            <button
              type="button"
              onClick={onClose}
              className="btn-secondary btn-sm"
            >
              Fermer
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

/** Section « Documents » des fiches LOCATAIRE et LOGEMENT (retour Phil
 * 2026-07-20) : TOUT ce qui a été généré/envoyé (avis TAL, DPA, lettres…)
 * au même endroit, avec la génération par bail HORS tableau (le menu
 * « Générer ▾ » n'est plus coupé par un conteneur défilant). */
export function DocumentsSection({
  locataireId,
  logementId,
  bails
}: {
  locataireId?: number;
  logementId?: number;
  /** Baux depuis lesquels générer un document (libellé affiché si >1). */
  bails: { id: number; label: string }[];
}) {
  const [docs, setDocs] = useState<BailDocument[] | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const load = useCallback(async () => {
    const url =
      locataireId != null
        ? `/api/v1/immobilier/locataires/${locataireId}/documents`
        : `/api/v1/immobilier/logements/${logementId}/documents`;
    try {
      const r = await authedFetch(url);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      setDocs((await r.json()) as BailDocument[]);
    } catch (e) {
      setErr(`Documents : ${(e as Error).message}`);
    }
  }, [locataireId, logementId]);

  useEffect(() => {
    void load();
    // Toute génération (même page ou ailleurs) rafraîchit la section.
    const handler = () => void load();
    window.addEventListener(DOCS_EVENT, handler);
    return () => window.removeEventListener(DOCS_EVENT, handler);
  }, [load]);

  return (
    <section className="rounded-2xl border border-brand-800 bg-brand-900 p-5">
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-accent-500">
          Documents
        </h2>
        <span className="text-[11px] text-white/40">
          {docs ? `${docs.length} document${docs.length > 1 ? "s" : ""}` : ""}
        </span>
        <span className="ml-auto flex flex-wrap items-center gap-2">
          {bails.map((b) => (
            <span key={b.id} className="inline-flex items-center gap-1.5">
              {bails.length > 1 ? (
                <span className="text-[11px] text-white/50">{b.label}</span>
              ) : null}
              <TalFormDropdown bailId={b.id} />
            </span>
          ))}
        </span>
      </div>
      {bails.length === 0 ? (
        <div className="mb-3 rounded-xl border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-xs text-amber-200">
          {locataireId != null ? (
            <>
              <b className="text-white">
                Ce locataire n&apos;a aucun bail
              </b>{" "}
              — les avis TAL se préremplissent depuis un bail, donc rien à
              générer ici pour l&apos;instant. Crée son bail depuis la
              fiche de l&apos;immeuble (onglet Baux &amp; locataires) et
              le menu « Générer ▾ » apparaîtra. Si ce locataire est un
              doublon (son bail vit sur une autre fiche), la page{" "}
              <Link
                // eslint-disable-next-line @typescript-eslint/no-explicit-any
                href={"/immobilier/locataires" as any}
                className="underline hover:text-white"
              >
                Locataires
              </Link>{" "}
              montre qui habite où — supprime le doublon avec la
              poubelle. Le DPA, lui, se génère depuis la section Dépôt
              préautorisé ci-dessus.
            </>
          ) : (
            <>
              <b className="text-white">Aucun bail actif</b> — logement
              libre : les avis se génèrent depuis un bail. L&apos;historique
              des documents des anciens baux reste visible ci-dessous.
            </>
          )}
        </div>
      ) : null}
      {err ? (
        <p className="mb-3 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
          {err}
        </p>
      ) : null}
      {docs === null ? (
        <p className="flex items-center gap-2 text-xs text-white/50">
          <Loader2 className="h-3.5 w-3.5 animate-spin" /> Chargement…
        </p>
      ) : (
        <DocsList
          docs={docs}
          onChanged={() => void load()}
          emptyText="Aucun document généré — utilise « Générer ▾ » ci-dessus (avis TAL, lettres) ou la section DPA."
        />
      )}
    </section>
  );
}
