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

const TAL_FORMS: { code: string; label: string; avecParams?: boolean }[] = [
  { code: "trousse_bail", label: "Trousse bail (données pour le TAL)" },
  { code: "sommaire_bail", label: "Sommaire du bail" },
  { code: "avis_modification", label: "Avis de modification" },
  { code: "avis_fin_bail", label: "Avis de non-renouvellement" },
  { code: "rappel_paiement", label: "Rappel de paiement" },
  { code: "mise_en_demeure", label: "Mise en demeure" },
  { code: "avis_reprise", label: "Avis de reprise du logement", avecParams: true },
  { code: "avis_travaux_majeurs", label: "Avis de travaux majeurs", avecParams: true },
  { code: "avis_acces", label: "Avis d'accès au logement", avecParams: true },
  { code: "reponse_cession", label: "Réponse cession / sous-location", avecParams: true }
];

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

export function TalFormDropdown({ bailId }: { bailId: number }) {
  const [open, setOpen] = useState(false);
  const [downloading, setDownloading] = useState<string | null>(null);
  const [paramsCode, setParamsCode] = useState<string | null>(null);

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
      cession_type: "cession",
      cession_accepte: "oui",
      travaux_evacuation: "non"
    };
    for (const [k, v] of Object.entries(initialParams || {})) {
      if (v == null) continue;
      if (typeof v === "boolean") {
        base[k] = v ? "oui" : "non";
      } else {
        base[k] = String(v);
      }
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
      case "avis_reprise":
        return !!(f.reprise_date && f.reprise_beneficiaire?.trim());
      case "avis_travaux_majeurs":
        return !!(f.travaux_description?.trim() && f.travaux_date_debut);
      case "avis_acces":
        return !!(f.acces_date && f.acces_motif?.trim());
      case "reponse_cession":
        return (
          !!f.cession_candidat?.trim() &&
          (f.cession_accepte === "oui" || !!f.cession_motif_refus?.trim())
        );
      default:
        return true;
    }
  })();

  async function generer() {
    if (!valid) return;
    setBusy(true);
    setErr(null);
    const body: Record<string, unknown> = {};
    if (code === "avis_reprise") {
      body.reprise_date = f.reprise_date;
      body.reprise_beneficiaire = f.reprise_beneficiaire?.trim();
      body.reprise_lien = f.reprise_lien?.trim() || null;
    } else if (code === "avis_travaux_majeurs") {
      body.travaux_description = f.travaux_description?.trim();
      body.travaux_date_debut = f.travaux_date_debut;
      body.travaux_duree = f.travaux_duree?.trim() || null;
      body.travaux_evacuation = f.travaux_evacuation === "oui";
      if (f.travaux_evacuation === "oui") {
        body.travaux_evacuation_duree =
          f.travaux_evacuation_duree?.trim() || null;
        body.travaux_indemnite = f.travaux_indemnite
          ? Number(f.travaux_indemnite)
          : null;
      }
    } else if (code === "avis_acces") {
      body.acces_date = f.acces_date;
      body.acces_plage = f.acces_plage?.trim() || null;
      body.acces_motif = f.acces_motif?.trim();
    } else if (code === "reponse_cession") {
      body.cession_type = f.cession_type;
      body.cession_candidat = f.cession_candidat?.trim();
      body.cession_accepte = f.cession_accepte === "oui";
      body.cession_motif_refus =
        f.cession_accepte === "oui"
          ? null
          : f.cession_motif_refus?.trim();
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
          {code === "avis_reprise" ? (
            <>
              <p className="text-xs text-white/50">
                À transmettre au moins 6 mois avant la fin du bail. Le
                locataire a 1 mois pour répondre (silence = refus).
              </p>
              <label className={labelCls}>
                Date prévue de la reprise *
                <input
                  type="date"
                  value={f.reprise_date || ""}
                  onChange={(e) => set("reprise_date")(e.target.value)}
                  className={inputCls}
                />
              </label>
              <label className={labelCls}>
                Bénéficiaire de la reprise *
                <input
                  value={f.reprise_beneficiaire || ""}
                  onChange={(e) =>
                    set("reprise_beneficiaire")(e.target.value)
                  }
                  placeholder="ex. Philippe Meuser"
                  className={inputCls}
                />
              </label>
              <label className={labelCls}>
                Lien avec le locateur
                <input
                  value={f.reprise_lien || ""}
                  onChange={(e) => set("reprise_lien")(e.target.value)}
                  placeholder="ex. moi-même, mon père, ma fille…"
                  className={inputCls}
                />
              </label>
            </>
          ) : null}

          {code === "avis_travaux_majeurs" ? (
            <>
              <p className="text-xs text-white/50">
                Préavis de 10 jours (3 mois si évacuation de plus d&apos;une
                semaine).
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
              <div className="grid grid-cols-2 gap-3">
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
                    value={f.travaux_duree || ""}
                    onChange={(e) => set("travaux_duree")(e.target.value)}
                    placeholder="ex. environ 2 semaines"
                    className={inputCls}
                  />
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
                <div className="grid grid-cols-2 gap-3">
                  <label className={labelCls}>
                    Durée de l&apos;évacuation
                    <input
                      value={f.travaux_evacuation_duree || ""}
                      onChange={(e) =>
                        set("travaux_evacuation_duree")(e.target.value)
                      }
                      placeholder="ex. 5 jours"
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
                Réponse à transmettre dans les 15 jours de l&apos;avis du
                locataire. Un refus doit reposer sur un motif sérieux.
              </p>
              <div className="grid grid-cols-2 gap-3">
                <label className={labelCls}>
                  Type de demande
                  <select
                    value={f.cession_type}
                    onChange={(e) => set("cession_type")(e.target.value)}
                    className={inputCls}
                  >
                    <option value="cession" className="bg-brand-950 text-white">
                      Cession de bail
                    </option>
                    <option
                      value="sous_location"
                      className="bg-brand-950 text-white"
                    >
                      Sous-location
                    </option>
                  </select>
                </label>
                <label className={labelCls}>
                  Décision
                  <select
                    value={f.cession_accepte}
                    onChange={(e) => set("cession_accepte")(e.target.value)}
                    className={inputCls}
                  >
                    <option value="oui" className="bg-brand-950 text-white">
                      Consentement
                    </option>
                    <option value="non" className="bg-brand-950 text-white">
                      Refus motivé
                    </option>
                  </select>
                </label>
              </div>
              <label className={labelCls}>
                Candidat proposé *
                <input
                  value={f.cession_candidat || ""}
                  onChange={(e) => set("cession_candidat")(e.target.value)}
                  placeholder="Nom de la personne proposée par le locataire"
                  className={inputCls}
                />
              </label>
              {f.cession_accepte === "non" ? (
                <label className={labelCls}>
                  Motif sérieux du refus *
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
        ) : (
          <>
            <FileSignature className="h-3.5 w-3.5" /> Envoyer pour signature
          </>
        )}
      </button>
      {open ? (
        <DocumentsModal
          bailId={bailId}
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

/** Bibliothèque des documents d'un bail : voir, modifier (régénérer),
 * envoyer pour signature, supprimer — avec les états de suivi. */
function DocumentsModal({
  bailId,
  docs,
  onClose,
  onChanged
}: {
  bailId: number;
  docs: BailDocument[];
  onClose: () => void;
  onChanged: () => void;
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
    if (
      !window.confirm(
        `Envoyer « ${d.titre} » au locataire pour signature en ligne ?`
      )
    )
      return;
    setBusyId(d.id);
    setErr(null);
    try {
      const r = await authedFetch(
        `/api/v1/immobilier/documents/${d.id}/envoyer-signature`,
        { method: "POST", body: JSON.stringify({}) }
      );
      if (!r.ok)
        throw new Error(
          (await r.text()).slice(0, 200) || `HTTP ${r.status}`
        );
      const res = (await r.json()) as { envoye_a: string };
      setFlash(`Envoyé à ${res.envoye_a} — suivi d'ouverture actif.`);
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
            transmet le document au locataire pour signature en ligne avec
            preuve d&apos;ouverture.
          </p>

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
              Aucun document — utilise « Générer ▾ » pour en créer un.
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
      {editDoc ? (
        <TalAvisModal
          bailId={bailId}
          code={editDoc.type}
          initialParams={editDoc.params}
          onClose={() => setEditDoc(null)}
          onGenerated={onChanged}
        />
      ) : null}
    </div>
  );
}
