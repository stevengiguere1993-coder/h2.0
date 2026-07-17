"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  Eye,
  FileSignature,
  Info,
  Loader2,
  RotateCcw,
  Upload
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
  custom_filename?: string | null;
  custom_uploaded_at?: string | null;
};

export default function ModelesDocumentsPage() {
  const [forms, setForms] = useState<TalForm[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [flash, setFlash] = useState<string | null>(null);
  const [previewing, setPreviewing] = useState<string | null>(null);
  const [uploading, setUploading] = useState<string | null>(null);
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
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </>
  );
}
