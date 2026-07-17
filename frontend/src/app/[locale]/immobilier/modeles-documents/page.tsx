"use client";

import { useEffect, useState } from "react";
import { Eye, FileSignature, Info, Loader2 } from "lucide-react";

import { authedFetch } from "@/lib/auth";
import { ImmobilierTopbar } from "../layout";

/**
 * Paramètres → Modèles de documents (locatif). Répertoire de TOUS les
 * modèles générables (trousse bail, avis TAL, DPA) avec aperçu PDF sur
 * données d'exemple. La vraie génération se fait depuis un BAIL (menu
 * « Générer ▾ ») : les modèles s'y préremplissent automatiquement —
 * retour Phil 2026-07-17 (« ils sont où les modèles ? »).
 */

type TalForm = { code: string; label: string; description: string };

export default function ModelesDocumentsPage() {
  const [forms, setForms] = useState<TalForm[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [previewing, setPreviewing] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const r = await authedFetch("/api/v1/immobilier/tal/forms");
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        if (!cancelled) setForms((await r.json()) as TalForm[]);
      } catch (e) {
        if (!cancelled)
          setError(`Chargement échoué : ${(e as Error).message}`);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

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

  const tous: TalForm[] = [
    ...(forms || []),
    {
      code: "dpa",
      label: "Accord de débit préautorisé (DPA)",
      description:
        "Formulaire d'adhésion au prélèvement automatique du loyer "
        + "(Règle H1 Paiements Canada) — s'envoie depuis la fiche du "
        + "locataire, section DPA."
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
              logement, Baux &amp; paiements). Le modèle se préremplit
              automatiquement avec les données du bail (locateur,
              locataire, adresse, loyer…), puis se retrouve dans la
              bibliothèque du bail (« Envoyer pour signature ») où tu peux
              le voir, le modifier et l&apos;envoyer pour signature en
              ligne. Le DPA s&apos;envoie depuis la fiche du locataire.
              Les aperçus ci-dessous utilisent des données d&apos;exemple.
            </p>
          </div>
        </div>

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
                <p className="mt-2 flex-1 text-xs text-white/60">
                  {f.description}
                </p>
                <button
                  type="button"
                  onClick={() => void apercu(f.code)}
                  disabled={previewing === f.code}
                  className="btn-secondary btn-sm mt-3 w-fit"
                >
                  {previewing === f.code ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <Eye className="h-3.5 w-3.5" />
                  )}
                  Aperçu (exemple)
                </button>
              </div>
            ))}
          </div>
        )}
      </div>
    </>
  );
}
