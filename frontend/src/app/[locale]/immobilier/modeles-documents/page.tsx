"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  Eye,
  FileSignature,
  Info,
  Loader2,
  Pencil,
  RotateCcw,
  Upload,
  X
} from "lucide-react";

import { authedFetch } from "@/lib/auth";
import { ImmobilierTopbar } from "../layout";

/**
 * Paramètres → Modèles de documents (locatif). Répertoire de TOUS les
 * modèles générables avec aperçu PDF sur données d'exemple. Les 5 avis
 * encadrés par le TAL utilisent les FORMULAIRES OFFICIELS (exigence
 * Phil 2026-07-17) — remplaçables ici quand le TAL publie une nouvelle
 * version. La vraie génération se fait depuis un BAIL (« Générer ▾ »).
 */

type TalForm = {
  code: string;
  label: string;
  description: string;
  officiel?: boolean;
  signature_requise?: boolean;
  // Lettre maison dont le texte est éditable (gabarit).
  texte_modifiable?: boolean;
  custom_filename?: string | null;
  custom_uploaded_at?: string | null;
};

export default function ModelesDocumentsPage() {
  const [forms, setForms] = useState<TalForm[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [flash, setFlash] = useState<string | null>(null);
  const [previewing, setPreviewing] = useState<string | null>(null);
  const [uploading, setUploading] = useState<string | null>(null);
  const [editerCode, setEditerCode] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement | null>(null);
  const uploadCode = useRef<string | null>(null);

  const load = useCallback(async () => {
    try {
      const r = await authedFetch("/api/v1/immobilier/tal/forms");
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      setForms((await r.json()) as TalForm[]);
    } catch (e) {
      setError(`Chargement échoué : ${(e as Error).message}`);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function apercu(code: string) {
    setPreviewing(code);
    setError(null);
    try {
      const r = await authedFetch(
        `/api/v1/immobilier/tal/apercu/${code}.pdf`
      );
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const blob = await r.blob();
      const url = URL.createObjectURL(blob);
      window.open(url, "_blank");
      window.setTimeout(() => URL.revokeObjectURL(url), 60000);
    } catch (e) {
      setError(`Aperçu échoué : ${(e as Error).message}`);
    } finally {
      setPreviewing(null);
    }
  }

  function demanderRemplacement(code: string) {
    uploadCode.current = code;
    fileRef.current?.click();
  }

  async function remplacer(file: File) {
    const code = uploadCode.current;
    if (!code) return;
    setUploading(code);
    setError(null);
    setFlash(null);
    try {
      const fd = new FormData();
      fd.append("file", file);
      const r = await authedFetch(
        `/api/v1/immobilier/tal/modeles/${code}/pdf`,
        { method: "POST", body: fd }
      );
      if (!r.ok)
        throw new Error(
          (await r.text()).slice(0, 300) || `HTTP ${r.status}`
        );
      setFlash(
        "PDF modèle remplacé — toutes les prochaines générations utiliseront cette version."
      );
      await load();
    } catch (e) {
      setError(`Remplacement refusé : ${(e as Error).message}`);
    } finally {
      setUploading(null);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  async function revenir(code: string) {
    if (
      !window.confirm(
        "Revenir au PDF officiel d'origine (supprime la version téléversée) ?"
      )
    )
      return;
    setUploading(code);
    setError(null);
    try {
      const r = await authedFetch(
        `/api/v1/immobilier/tal/modeles/${code}/pdf`,
        { method: "DELETE" }
      );
      if (!r.ok && r.status !== 204) throw new Error(`HTTP ${r.status}`);
      setFlash("PDF d'origine restauré.");
      await load();
    } catch (e) {
      setError(`Restauration échouée : ${(e as Error).message}`);
    } finally {
      setUploading(null);
    }
  }

  const tous: TalForm[] = [
    ...(forms || []),
    {
      code: "dpa",
      label: "Accord de débit préautorisé (DPA)",
      description:
        "Formulaire d'adhésion au prélèvement automatique du loyer "
        + "(Règle H1 Paiements Canada) — s'envoie depuis la fiche du "
        + "locataire, section DPA.",
      signature_requise: true
    }
  ];

  return (
    <>
      <ImmobilierTopbar
        breadcrumbs={[
          { label: "Gestion immobilière", href: "/immobilier" },
          { label: "Modèles de documents" }
        ]}
      />
      <input
        ref={fileRef}
        type="file"
        accept="application/pdf"
        className="hidden"
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (file) void remplacer(file);
        }}
      />
      <div className="p-4 pb-28 lg:p-6 lg:pb-28">
        <div className="mb-4 flex items-start gap-2 rounded-2xl border border-sky-400/30 bg-sky-500/10 p-4 text-sm text-sky-200">
          <Info className="mt-0.5 h-4 w-4 flex-shrink-0" />
          <div>
            <p className="font-semibold text-white">
              Où générer ces documents ?
            </p>
            <p className="mt-1 text-xs text-sky-200/80">
              Sur chaque <strong>bail</strong> : menu « Générer ▾ » (fiche
              immeuble → Baux &amp; locataires, hub locataire, page
              logement, Baux &amp; paiements). Le document se préremplit
              avec les données du bail, puis se retrouve dans la
              bibliothèque du bail : signature en ligne pour les
              formulaires TAL, simple courriel avec PDF joint pour les
              avis de retard et d&apos;accès. Les 5 avis marqués
              « Officiel TAL » utilisent les vrais formulaires du
              Tribunal, remplis tels quels — si le TAL publie une
              nouvelle version, remplace le PDF ici. Les aperçus
              utilisent des données d&apos;exemple.
            </p>
          </div>
        </div>

        {flash ? (
          <p className="mb-4 rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-xs text-emerald-300">
            {flash}
          </p>
        ) : null}
        {error ? (
          <p className="mb-4 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
            {error}
          </p>
        ) : null}

        {forms === null ? (
          <div className="flex items-center gap-2 text-xs text-white/50">
            <Loader2 className="h-3.5 w-3.5 animate-spin" /> Chargement…
          </div>
        ) : (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {tous.map((f) => (
              <div
                key={f.code}
                className="flex flex-col rounded-2xl border border-brand-800 bg-brand-900 p-4"
              >
                <div className="flex items-center gap-2">
                  <span className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-lg bg-accent-500/15 text-accent-500">
                    <FileSignature className="h-4 w-4" />
                  </span>
                  <h2 className="text-sm font-semibold text-white">
                    {f.label}
                  </h2>
                </div>
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {f.officiel ? (
                    <span className="rounded-full border border-emerald-500/40 bg-emerald-500/10 px-2 py-0.5 text-[10px] font-semibold text-emerald-300">
                      Officiel TAL
                    </span>
                  ) : null}
                  {f.signature_requise === false ? (
                    <span className="rounded-full border border-sky-400/40 bg-sky-500/10 px-2 py-0.5 text-[10px] font-semibold text-sky-300">
                      Courriel — sans signature
                    </span>
                  ) : null}
                  {f.custom_filename ? (
                    <span
                      className="rounded-full border border-amber-400/40 bg-amber-500/10 px-2 py-0.5 text-[10px] font-semibold text-amber-300"
                      title={`Version téléversée : ${f.custom_filename}`}
                    >
                      PDF remplacé
                    </span>
                  ) : null}
                </div>
                <p className="mt-2 flex-1 text-xs text-white/60">
                  {f.description}
                </p>
                <div className="mt-3 flex flex-wrap items-center gap-1.5">
                  <button
                    type="button"
                    onClick={() => void apercu(f.code)}
                    disabled={previewing === f.code}
                    className="btn-secondary btn-sm"
                  >
                    {previewing === f.code ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    ) : (
                      <Eye className="h-3.5 w-3.5" />
                    )}
                    Aperçu (exemple)
                  </button>
                  {f.officiel ? (
                    <button
                      type="button"
                      onClick={() => demanderRemplacement(f.code)}
                      disabled={uploading === f.code}
                      className="btn-ghost btn-sm"
                      title="Téléverser une nouvelle version du formulaire publiée par le TAL"
                    >
                      {uploading === f.code ? (
                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      ) : (
                        <Upload className="h-3.5 w-3.5" />
                      )}
                      Remplacer le PDF
                    </button>
                  ) : null}
                  {f.officiel && f.custom_filename ? (
                    <button
                      type="button"
                      onClick={() => void revenir(f.code)}
                      disabled={uploading === f.code}
                      className="btn-ghost btn-sm"
                      title="Revenir au PDF officiel embarqué d'origine"
                    >
                      <RotateCcw className="h-3.5 w-3.5" />
                      Original
                    </button>
                  ) : null}
                  {f.texte_modifiable ? (
                    <button
                      type="button"
                      onClick={() => setEditerCode(f.code)}
                      className="btn-ghost btn-sm"
                      title="Modifier le texte de cette lettre (gabarit)"
                    >
                      <Pencil className="h-3.5 w-3.5" />
                      Modifier le texte
                    </button>
                  ) : null}
                </div>
              </div>
            ))}
          </div>
        )}

        <PersoSection />
      </div>
      {editerCode ? (
        <GabaritModal
          code={editerCode}
          titre={
            (forms || []).find((f) => f.code === editerCode)?.label ||
            editerCode
          }
          onClose={() => setEditerCode(null)}
          onSaved={(message) => {
            setEditerCode(null);
            setFlash(message);
          }}
        />
      ) : null}
    </>
  );
}

// ── Documents PERSONNALISÉS (retour Steven 2026-07-20, point 5) ──────
// Règlement d'immeuble, contrat de chambreur… Modèle TEXTE ({variables}
// remplies depuis le bail, **gras** supporté) OU PDF téléversé tel quel.
// Ils apparaissent dans « Générer ▾ » sur chaque bail, section « Mes
// documents », puis s'envoient pour signature (ou simple courriel).

type PersoModele = {
  id: number;
  nom: string;
  titre: string | null;
  corps: string | null;
  signature_requise: boolean;
  pdf_filename: string | null;
  has_pdf: boolean;
  variables: string[];
};

function PersoSection() {
  const [modeles, setModeles] = useState<PersoModele[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [flash, setFlash] = useState<string | null>(null);
  const [editing, setEditing] = useState<PersoModele | "new" | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);
  const pdfRef = useRef<HTMLInputElement | null>(null);
  const pdfForId = useRef<number | null>(null);

  const load = useCallback(async () => {
    try {
      const r = await authedFetch("/api/v1/immobilier/docs-perso/modeles");
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      setModeles((await r.json()) as PersoModele[]);
    } catch (e) {
      setErr(`Documents personnalisés : ${(e as Error).message}`);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function apercu(m: PersoModele) {
    setBusyId(m.id);
    setErr(null);
    try {
      const r = await authedFetch(
        `/api/v1/immobilier/docs-perso/modeles/${m.id}/apercu.pdf`
      );
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const blob = await r.blob();
      const url = URL.createObjectURL(blob);
      window.open(url, "_blank");
      window.setTimeout(() => URL.revokeObjectURL(url), 60000);
    } catch (e) {
      setErr(`Aperçu échoué : ${(e as Error).message}`);
    } finally {
      setBusyId(null);
    }
  }

  async function supprimer(m: PersoModele) {
    if (
      !window.confirm(
        `Supprimer le modèle « ${m.nom} » ? Les documents déjà générés restent conservés.`
      )
    )
      return;
    setBusyId(m.id);
    try {
      const r = await authedFetch(
        `/api/v1/immobilier/docs-perso/modeles/${m.id}`,
        { method: "DELETE" }
      );
      if (!r.ok && r.status !== 204) throw new Error(`HTTP ${r.status}`);
      setFlash(`Modèle « ${m.nom} » supprimé.`);
      await load();
    } catch (e) {
      setErr(`Suppression échouée : ${(e as Error).message}`);
    } finally {
      setBusyId(null);
    }
  }

  async function uploadPdf(file: File) {
    const id = pdfForId.current;
    if (id == null) return;
    setBusyId(id);
    setErr(null);
    try {
      const fd = new FormData();
      fd.append("file", file);
      const r = await authedFetch(
        `/api/v1/immobilier/docs-perso/modeles/${id}/pdf`,
        { method: "POST", body: fd }
      );
      if (!r.ok)
        throw new Error((await r.text()).slice(0, 300) || `HTTP ${r.status}`);
      setFlash(
        "PDF téléversé — il sera utilisé tel quel à la génération (le texte du modèle est ignoré)."
      );
      await load();
    } catch (e) {
      setErr(`Téléversement refusé : ${(e as Error).message}`);
    } finally {
      setBusyId(null);
      if (pdfRef.current) pdfRef.current.value = "";
    }
  }

  async function retirerPdf(m: PersoModele) {
    if (
      !window.confirm(
        "Retirer le PDF téléversé ? Le modèle redeviendra un modèle texte."
      )
    )
      return;
    setBusyId(m.id);
    try {
      const r = await authedFetch(
        `/api/v1/immobilier/docs-perso/modeles/${m.id}/pdf`,
        { method: "DELETE" }
      );
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      await load();
    } catch (e) {
      setErr(`Retrait échoué : ${(e as Error).message}`);
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div className="mt-8">
      <input
        ref={pdfRef}
        type="file"
        accept="application/pdf"
        className="hidden"
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (file) void uploadPdf(file);
        }}
      />
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-accent-500">
          Documents personnalisés
        </h2>
        <span className="text-[11px] text-white/40">
          règlement d&apos;immeuble, contrat de chambreur…
        </span>
        <button
          type="button"
          onClick={() => setEditing("new")}
          className="btn-accent btn-sm ml-auto"
        >
          + Nouveau modèle
        </button>
      </div>
      <p className="mb-3 text-xs text-white/50">
        Tes propres modèles, générés depuis n&apos;importe quel bail via
        « Générer ▾ » (section « Mes documents ») — préremplis avec les
        données du bail, puis envoyables pour <b>signature en ligne</b> (ou
        par simple courriel avec suivi d&apos;ouverture si tu décoches la
        signature). Tu peux aussi téléverser un PDF déjà mis en page.
      </p>
      {flash ? (
        <p className="mb-3 rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-xs text-emerald-300">
          {flash}
        </p>
      ) : null}
      {err ? (
        <p className="mb-3 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
          {err}
        </p>
      ) : null}
      {modeles === null ? (
        <div className="flex items-center gap-2 text-xs text-white/50">
          <Loader2 className="h-3.5 w-3.5 animate-spin" /> Chargement…
        </div>
      ) : modeles.length === 0 ? (
        <div className="rounded-2xl border border-dashed border-brand-800 bg-brand-900/40 p-6 text-center text-xs text-white/50">
          Aucun modèle personnalisé — clique « + Nouveau modèle » pour créer
          ton premier (ex. règlement d&apos;immeuble).
        </div>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {modeles.map((m) => (
            <div
              key={m.id}
              className="flex flex-col rounded-2xl border border-brand-800 bg-brand-900 p-4"
            >
              <div className="flex items-center gap-2">
                <span className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-lg bg-accent-500/15 text-accent-500">
                  <FileSignature className="h-4 w-4" />
                </span>
                <h3 className="text-sm font-semibold text-white">{m.nom}</h3>
              </div>
              <div className="mt-2 flex flex-wrap gap-1.5">
                {m.signature_requise ? (
                  <span className="rounded-full border border-emerald-500/40 bg-emerald-500/10 px-2 py-0.5 text-[10px] font-semibold text-emerald-300">
                    Signature en ligne
                  </span>
                ) : (
                  <span className="rounded-full border border-sky-400/40 bg-sky-500/10 px-2 py-0.5 text-[10px] font-semibold text-sky-300">
                    Courriel — sans signature
                  </span>
                )}
                {m.has_pdf ? (
                  <span
                    className="rounded-full border border-amber-400/40 bg-amber-500/10 px-2 py-0.5 text-[10px] font-semibold text-amber-300"
                    title={m.pdf_filename || undefined}
                  >
                    PDF téléversé
                  </span>
                ) : null}
              </div>
              {m.titre ? (
                <p className="mt-2 flex-1 text-xs text-white/60">{m.titre}</p>
              ) : (
                <span className="flex-1" />
              )}
              <div className="mt-3 flex flex-wrap items-center gap-1.5">
                <button
                  type="button"
                  onClick={() => void apercu(m)}
                  disabled={busyId === m.id}
                  className="btn-secondary btn-sm"
                >
                  {busyId === m.id ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <Eye className="h-3.5 w-3.5" />
                  )}
                  Aperçu
                </button>
                <button
                  type="button"
                  onClick={() => setEditing(m)}
                  className="btn-ghost btn-sm"
                >
                  <Pencil className="h-3.5 w-3.5" />
                  Modifier
                </button>
                <button
                  type="button"
                  onClick={() => {
                    pdfForId.current = m.id;
                    pdfRef.current?.click();
                  }}
                  disabled={busyId === m.id}
                  className="btn-ghost btn-sm"
                  title="Téléverser un PDF déjà mis en page (utilisé tel quel)"
                >
                  <Upload className="h-3.5 w-3.5" />
                  PDF
                </button>
                {m.has_pdf ? (
                  <button
                    type="button"
                    onClick={() => void retirerPdf(m)}
                    disabled={busyId === m.id}
                    className="btn-ghost btn-sm"
                    title="Retirer le PDF téléversé (revenir au modèle texte)"
                  >
                    <RotateCcw className="h-3.5 w-3.5" />
                  </button>
                ) : null}
                <button
                  type="button"
                  onClick={() => void supprimer(m)}
                  disabled={busyId === m.id}
                  className="btn-ghost btn-sm text-rose-300 hover:text-rose-200"
                  title="Supprimer ce modèle"
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
      {editing ? (
        <PersoModal
          modele={editing === "new" ? null : editing}
          onClose={() => setEditing(null)}
          onSaved={(msg) => {
            setEditing(null);
            setFlash(msg);
            void load();
          }}
        />
      ) : null}
    </div>
  );
}

function PersoModal({
  modele,
  onClose,
  onSaved
}: {
  modele: PersoModele | null;
  onClose: () => void;
  onSaved: (message: string) => void;
}) {
  const [nom, setNom] = useState(modele?.nom ?? "");
  const [titreDoc, setTitreDoc] = useState(modele?.titre ?? "");
  const [corps, setCorps] = useState(modele?.corps ?? "");
  const [signature, setSignature] = useState(
    modele ? modele.signature_requise : true
  );
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const variables = modele?.variables ?? [
    "locataire",
    "locateur",
    "adresse",
    "ville",
    "logement",
    "loyer",
    "bail_debut",
    "bail_fin",
    "date"
  ];

  async function save() {
    if (!nom.trim()) return;
    setBusy(true);
    setErr(null);
    try {
      const body = JSON.stringify({
        nom: nom.trim(),
        titre: titreDoc.trim() || null,
        corps,
        signature_requise: signature
      });
      const r = await authedFetch(
        modele
          ? `/api/v1/immobilier/docs-perso/modeles/${modele.id}`
          : "/api/v1/immobilier/docs-perso/modeles",
        { method: modele ? "PUT" : "POST", body }
      );
      if (!r.ok)
        throw new Error((await r.text()).slice(0, 300) || `HTTP ${r.status}`);
      onSaved(
        modele
          ? `Modèle « ${nom.trim()} » mis à jour.`
          : `Modèle « ${nom.trim()} » créé — il apparaît maintenant dans « Générer ▾ » sur chaque bail.`
      );
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/70 p-4 backdrop-blur-sm">
      <div className="my-8 w-full max-w-2xl rounded-2xl border border-brand-800 bg-brand-950 shadow-2xl">
        <div className="flex items-center justify-between border-b border-brand-800 px-5 py-3">
          <h2 className="flex items-center gap-2 text-sm font-bold uppercase tracking-wider text-accent-500">
            <Pencil className="h-4 w-4" />
            {modele ? "Modifier le modèle" : "Nouveau modèle personnalisé"}
          </h2>
          <button type="button" onClick={onClose} className="btn-ghost btn-xs">
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="space-y-3 p-5">
          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <label className="mb-1 block text-[11px] font-semibold uppercase tracking-wider text-white/50">
                Nom du modèle *
              </label>
              <input
                value={nom}
                onChange={(e) => setNom(e.target.value)}
                placeholder="Ex. Contrat de chambreur"
                className="input w-full"
              />
            </div>
            <div>
              <label className="mb-1 block text-[11px] font-semibold uppercase tracking-wider text-white/50">
                Titre affiché sur le document
              </label>
              <input
                value={titreDoc}
                onChange={(e) => setTitreDoc(e.target.value)}
                placeholder="Ex. CONTRAT DE LOCATION D'UNE CHAMBRE"
                className="input w-full"
              />
            </div>
          </div>
          <div>
            <label className="mb-1 block text-[11px] font-semibold uppercase tracking-wider text-white/50">
              Texte du document
            </label>
            <textarea
              value={corps}
              onChange={(e) => setCorps(e.target.value)}
              rows={12}
              placeholder={"Un paragraphe par bloc, séparés d'une ligne vide.\n\nEx. Le locataire {locataire} loue une chambre au {adresse} pour {loyer} par mois, du {bail_debut} au {bail_fin}."}
              className="input w-full font-mono text-xs leading-relaxed"
            />
            <p className="mt-1 text-[11px] text-white/40">
              Variables remplies depuis le bail :{" "}
              {variables.map((v) => (
                <code
                  key={v}
                  className="mr-1 rounded bg-brand-800 px-1 py-0.5 text-[10px] text-accent-500"
                >
                  {"{"}
                  {v}
                  {"}"}
                </code>
              ))}{" "}
              · **gras** supporté. Si un PDF est téléversé sur ce modèle, il
              est utilisé tel quel et ce texte est ignoré.
            </p>
          </div>
          <label className="flex cursor-pointer items-center gap-2 text-sm text-white/80">
            <input
              type="checkbox"
              checked={signature}
              onChange={(e) => setSignature(e.target.checked)}
              className="h-4 w-4 accent-accent-500"
            />
            Signature en ligne requise (sinon : simple courriel avec PDF
            joint + suivi d&apos;ouverture)
          </label>
          {err ? (
            <p className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
              {err}
            </p>
          ) : null}
        </div>
        <div className="flex items-center justify-end gap-2 border-t border-brand-800 px-5 py-3">
          <button type="button" onClick={onClose} className="btn-secondary btn-sm">
            Annuler
          </button>
          <button
            type="button"
            onClick={() => void save()}
            disabled={busy || !nom.trim()}
            className="btn-accent btn-sm"
          >
            {busy ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : null}
            Enregistrer
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Éditeur de gabarit des lettres maison (retard, accès) ────────────
// Le texte (titre + paragraphes, un paragraphe par bloc séparé d'une
// ligne vide) est enregistré dans automation_settings et utilisé pour
// toutes les prochaines générations. Variables {x} remplacées par les
// données du bail ; **gras** supporté.

type Gabarit = {
  code: string;
  titre: string;
  paragraphes: string[];
  variables: string[];
  personnalise: boolean;
};

function GabaritModal({
  code,
  titre,
  onClose,
  onSaved
}: {
  code: string;
  titre: string;
  onClose: () => void;
  onSaved: (message: string) => void;
}) {
  const [gabarit, setGabarit] = useState<Gabarit | null>(null);
  const [titreDraft, setTitreDraft] = useState("");
  const [texte, setTexte] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const r = await authedFetch(
          `/api/v1/immobilier/tal/gabarits/${code}`
        );
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const g = (await r.json()) as Gabarit;
        if (cancelled) return;
        setGabarit(g);
        setTitreDraft(g.titre);
        setTexte(g.paragraphes.join("\n\n"));
      } catch (e) {
        if (!cancelled) setErr((e as Error).message);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [code]);

  async function save(reset: boolean) {
    setBusy(true);
    setErr(null);
    try {
      const paragraphes = reset
        ? []
        : texte
            .split(/\n\s*\n/)
            .map((p) => p.trim())
            .filter(Boolean);
      const r = await authedFetch(
        `/api/v1/immobilier/tal/gabarits/${code}`,
        {
          method: "PUT",
          body: JSON.stringify({
            titre: reset ? null : titreDraft.trim() || null,
            paragraphes
          })
        }
      );
      if (!r.ok)
        throw new Error(
          (await r.text()).slice(0, 200) || `HTTP ${r.status}`
        );
      onSaved(
        reset
          ? "Texte d'origine restauré."
          : "Gabarit enregistré — utilisé pour toutes les prochaines générations."
      );
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/70 p-4 backdrop-blur-sm">
      <div className="my-8 w-full max-w-2xl rounded-2xl border border-brand-800 bg-brand-950 shadow-2xl">
        <div className="flex items-center justify-between border-b border-brand-800 px-5 py-3">
          <h2 className="text-sm font-bold uppercase tracking-wider text-accent-500">
            Modifier le texte — {titre}
          </h2>
          <button type="button" onClick={onClose} className="btn-ghost btn-xs">
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="space-y-3 p-5">
          {gabarit === null && !err ? (
            <p className="flex items-center gap-2 text-xs text-white/50">
              <Loader2 className="h-3.5 w-3.5 animate-spin" /> Chargement…
            </p>
          ) : null}
          {gabarit ? (
            <>
              <label className="block text-[11px] font-semibold uppercase tracking-wider text-white/50">
                Titre de la lettre
                <input
                  value={titreDraft}
                  onChange={(e) => setTitreDraft(e.target.value)}
                  className="input mt-1 w-full"
                />
              </label>
              <label className="block text-[11px] font-semibold uppercase tracking-wider text-white/50">
                Texte (un paragraphe par bloc, ligne vide entre les blocs)
                <textarea
                  value={texte}
                  onChange={(e) => setTexte(e.target.value)}
                  rows={14}
                  className="input mt-1 w-full font-mono text-xs leading-5"
                />
              </label>
              <p className="text-[11px] text-white/50">
                Variables remplacées automatiquement :{" "}
                {gabarit.variables.map((v) => (
                  <code
                    key={v}
                    className="mr-1 rounded bg-white/10 px-1.5 py-0.5 text-[10px] text-accent-500"
                  >
                    {"{" + v + "}"}
                  </code>
                ))}
                — <b>**gras**</b> pour mettre en gras. Utilise « Aperçu
                (exemple) » sur la carte pour vérifier le rendu après
                l&apos;enregistrement.
              </p>
              {gabarit.personnalise ? (
                <p className="text-[11px] text-amber-300">
                  Un texte personnalisé est actif (différent de
                  l&apos;original).
                </p>
              ) : null}
            </>
          ) : null}
          {err ? (
            <p className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
              {err}
            </p>
          ) : null}
          <div className="flex items-center justify-between border-t border-brand-800 pt-3">
            <button
              type="button"
              onClick={() => void save(true)}
              disabled={busy || !gabarit}
              className="btn-ghost btn-sm text-white/60"
              title="Revenir au texte d'origine"
            >
              <RotateCcw className="h-3.5 w-3.5" />
              Texte d&apos;origine
            </button>
            <span className="flex items-center gap-2">
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
                onClick={() => void save(false)}
                disabled={busy || !gabarit || !texte.trim()}
                className="btn-accent btn-sm disabled:opacity-50"
              >
                {busy ? (
                  <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />
                ) : null}
                Enregistrer
              </button>
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}
