"use client";

import { useState } from "react";
import { ExternalLink, FolderOpen, Pencil, X } from "lucide-react";

/**
 * Bouton Google Drive partagé entreprise / lead / deal.
 *
 * - Si une URL est configurée : affiche un bouton coloré qui ouvre
 *   le dossier dans un nouvel onglet, + une icône crayon pour
 *   modifier.
 * - Sinon : bouton « + Drive » grisé qui ouvre une mini-modale pour
 *   coller l'URL.
 *
 * `onSave(url)` — appelé avec l'URL nettoyée (ou chaîne vide pour
 * supprimer). Le parent fait le PATCH backend.
 */
export function DriveButton({
  url,
  onSave
}: {
  url: string | null | undefined;
  onSave: (newUrl: string) => Promise<void> | void;
}) {
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  // Valeur transmise *directement* par la modale au moment du submit
  // — on n'utilise pas un state intermédiaire `draft` qui serait
  // stale au moment où submit est appelé.
  async function performSave(rawValue: string) {
    const v = rawValue.trim();
    if (v && !/^https?:\/\//i.test(v)) {
      setErr("L'URL doit commencer par http:// ou https://");
      return;
    }
    setSaving(true);
    setErr(null);
    try {
      await onSave(v);
      setEditing(false);
    } catch (e2) {
      setErr((e2 as Error).message || "Erreur");
    } finally {
      setSaving(false);
    }
  }

  function openEditor() {
    setErr(null);
    setEditing(true);
  }

  if (!url) {
    return (
      <>
        <button
          type="button"
          onClick={openEditor}
          className="inline-flex items-center gap-1.5 rounded-lg border border-dashed border-white/20 bg-transparent px-2.5 py-1.5 text-xs text-white/50 hover:border-emerald-400/50 hover:text-emerald-300"
          title="Configurer le dossier Google Drive"
        >
          <FolderOpen className="h-3.5 w-3.5" />
          + Drive
        </button>
        {editing ? (
          <DriveUrlModal
            initial=""
            onSubmit={performSave}
            onCancel={() => setEditing(false)}
            saving={saving}
            error={err}
          />
        ) : null}
      </>
    );
  }

  return (
    <>
      <span className="inline-flex items-center overflow-hidden rounded-lg border border-emerald-400/30 bg-emerald-500/10">
        <a
          href={url}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-1.5 px-2.5 py-1.5 text-xs font-semibold text-emerald-200 hover:bg-emerald-500/20"
          title={url}
        >
          <FolderOpen className="h-3.5 w-3.5" />
          Drive
          <ExternalLink className="h-3 w-3 opacity-70" />
        </a>
        <button
          type="button"
          onClick={openEditor}
          className="border-l border-emerald-400/30 px-1.5 py-1.5 text-emerald-200/60 hover:bg-emerald-500/20 hover:text-emerald-200"
          title="Modifier l'URL"
          aria-label="Modifier"
        >
          <Pencil className="h-3 w-3" />
        </button>
      </span>
      {editing ? (
        <DriveUrlModal
          initial={url}
          onSubmit={performSave}
          onCancel={() => setEditing(false)}
          saving={saving}
          error={err}
        />
      ) : null}
    </>
  );
}

function DriveUrlModal({
  initial,
  onSubmit,
  onCancel,
  saving,
  error
}: {
  initial: string;
  onSubmit: (url: string) => void | Promise<void>;
  onCancel: () => void;
  saving: boolean;
  error: string | null;
}) {
  const [val, setVal] = useState(initial);

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/60 px-2 py-4 sm:items-center">
      <div
        className="w-full max-w-md rounded-2xl border border-brand-800 bg-brand-900 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-brand-800 p-4">
          <h2 className="text-sm font-bold text-white">
            Dossier Google Drive
          </h2>
          <button
            type="button"
            onClick={onCancel}
            aria-label="Fermer"
            className="rounded-md p-1 text-white/60 hover:bg-white/5 hover:text-white"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void onSubmit(val);
          }}
          className="grid gap-3 p-4"
        >
          <p className="text-xs text-white/60">
            Colle l&apos;URL du dossier Drive partagé. Le bouton
            « Drive » du header ouvrira ce lien dans un nouvel onglet.
          </p>
          <input
            type="url"
            value={val}
            onChange={(e) => setVal(e.target.value)}
            placeholder="https://drive.google.com/drive/folders/..."
            className="input"
            autoFocus
          />
          {error ? (
            <p className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
              {error}
            </p>
          ) : null}
          <div className="flex flex-wrap items-center justify-end gap-2 pt-1">
            {initial ? (
              <button
                type="button"
                onClick={() => void onSubmit("")}
                className="rounded-lg border border-white/15 px-3 py-1.5 text-xs text-rose-300 hover:bg-rose-500/10"
              >
                Effacer
              </button>
            ) : null}
            <button
              type="button"
              onClick={onCancel}
              className="btn-secondary text-xs"
            >
              Annuler
            </button>
            <button
              type="submit"
              disabled={saving}
              className="btn-accent text-xs disabled:opacity-60"
            >
              {saving ? "Enregistrement…" : "Enregistrer"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
