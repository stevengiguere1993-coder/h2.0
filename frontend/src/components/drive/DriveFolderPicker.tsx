"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertCircle,
  Check,
  ChevronRight,
  Folder,
  FolderOpen,
  Home,
  Inbox,
  Loader2,
  RefreshCw,
  X
} from "lucide-react";

import { authedFetch } from "@/lib/auth";

/**
 * <DriveFolderPicker> — sélecteur visuel de dossier Drive.
 *
 * Modale plein écran qui affiche un explorateur de DOSSIERS Drive en mode
 * sélection (à la Google Drive). On navigue dans l'arborescence, et le
 * dossier « courant » (celui dans lequel on se trouve) est le candidat à la
 * sélection via le bouton « Choisir ce dossier ».
 *
 * Réutilise les mêmes endpoints que <DriveFolderExplorer> :
 *  - listing :   GET /api/v1/drive/folders/{folderId}/files
 *  - breadcrumbs: GET /api/v1/drive/folders/{folderId}/path
 *
 * On démarre à la racine du Drive (`root`, alias accepté par l'API Google).
 * Seuls les DOSSIERS sont cliquables ; les fichiers sont affichés grisés et
 * non sélectionnables (on ne lie QUE des dossiers).
 *
 * Le composant ne crash JAMAIS : toute erreur réseau / OAuth est capturée
 * et rendue dans un encart local. Guards `?.` partout.
 */

const FOLDER_MIME = "application/vnd.google-apps.folder";
const PAGE_SIZE = 100;
const ROOT_ID = "root";

type DriveFile = {
  id: string;
  name: string;
  mime_type: string;
  is_folder?: boolean;
  modified_time?: string | null;
};

type DriveFolderContents = {
  files: DriveFile[];
  next_page_token?: string | null;
};

type DriveFolderPathSegment = { id: string; name: string };
type DriveFolderPath = { segments: DriveFolderPathSegment[] };

export type DriveFolderPickerProps = {
  /** Modale visible ? */
  open: boolean;
  /** Appelé avec le dossier choisi (id résolu + nom lisible). */
  onSelect: (folderId: string, folderName: string) => void;
  /** Fermeture (Annuler / X). */
  onClose: () => void;
  /** Dossier de départ (défaut : racine `root`). */
  initialFolderId?: string;
};

function isFolder(f: DriveFile): boolean {
  return f?.is_folder === true || f?.mime_type === FOLDER_MIME;
}

export function DriveFolderPicker({
  open,
  onSelect,
  onClose,
  initialFolderId
}: DriveFolderPickerProps) {
  const startId = initialFolderId?.trim() || ROOT_ID;

  const [currentFolderId, setCurrentFolderId] = useState<string>(startId);
  const [breadcrumbs, setBreadcrumbs] = useState<DriveFolderPathSegment[]>([]);
  const [files, setFiles] = useState<DriveFile[]>([]);
  const [nextPageToken, setNextPageToken] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<{
    kind: "auth" | "permission" | "notfound" | "network" | "other";
    message: string;
  } | null>(null);

  // Réinitialise la navigation à chaque (ré)ouverture.
  useEffect(() => {
    if (open) {
      setCurrentFolderId(initialFolderId?.trim() || ROOT_ID);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  // -------------------------------------------------------------------------
  // Fetch breadcrumbs
  // -------------------------------------------------------------------------
  const loadPath = useCallback(async (id: string) => {
    try {
      const res = await authedFetch(
        `/api/v1/drive/folders/${encodeURIComponent(id)}/path`
      );
      if (!res.ok) {
        setBreadcrumbs([{ id, name: "Mon disque" }]);
        return;
      }
      const data = (await res.json()) as DriveFolderPath;
      const segs = Array.isArray(data?.segments) ? data.segments : [];
      setBreadcrumbs(segs.length > 0 ? segs : [{ id, name: "Mon disque" }]);
    } catch {
      setBreadcrumbs([{ id, name: "Mon disque" }]);
    }
  }, []);

  // -------------------------------------------------------------------------
  // Fetch listing
  // -------------------------------------------------------------------------
  const loadListing = useCallback(
    async (folder: string, append = false) => {
      if (!append) {
        setLoading(true);
        setError(null);
      } else {
        setLoadingMore(true);
      }
      try {
        const params = new URLSearchParams();
        params.set("page_size", String(PAGE_SIZE));
        if (append && nextPageToken) params.set("page_token", nextPageToken);

        const res = await authedFetch(
          `/api/v1/drive/folders/${encodeURIComponent(folder)}/files?${params.toString()}`
        );
        if (!res.ok) {
          let msg = `Erreur ${res.status}`;
          try {
            const txt = await res.text();
            if (txt) {
              try {
                const parsed = JSON.parse(txt) as { detail?: unknown };
                if (typeof parsed?.detail === "string") msg = parsed.detail;
                else msg = txt;
              } catch {
                msg = txt;
              }
            }
          } catch {
            /* ignore */
          }
          if (res.status === 401) setError({ kind: "auth", message: msg });
          else if (res.status === 403)
            setError({ kind: "permission", message: msg });
          else if (res.status === 404)
            setError({ kind: "notfound", message: msg });
          else setError({ kind: "other", message: msg });
          if (!append) setFiles([]);
          return;
        }
        const data = (await res.json()) as DriveFolderContents;
        const incoming = Array.isArray(data?.files) ? data.files : [];
        setFiles((prev) => (append ? [...prev, ...incoming] : incoming));
        setNextPageToken(data?.next_page_token ?? null);
      } catch (e) {
        setError({
          kind: "network",
          message: (e as Error)?.message || "Erreur réseau"
        });
        if (!append) setFiles([]);
      } finally {
        setLoading(false);
        setLoadingMore(false);
      }
    },
    [nextPageToken]
  );

  // Recharge quand on change de dossier (uniquement modale ouverte).
  useEffect(() => {
    if (!open) return;
    setNextPageToken(null);
    void loadListing(currentFolderId, false);
    void loadPath(currentFolderId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentFolderId, open]);

  function navigateInto(folder: DriveFile) {
    if (!isFolder(folder)) return;
    setCurrentFolderId(folder.id);
  }

  function navigateToBreadcrumb(seg: DriveFolderPathSegment) {
    setCurrentFolderId(seg.id);
  }

  function refresh() {
    setNextPageToken(null);
    void loadListing(currentFolderId, false);
    void loadPath(currentFolderId);
  }

  function loadMore() {
    if (!nextPageToken) return;
    void loadListing(currentFolderId, true);
  }

  // Dossier courant = dernier segment de breadcrumb (id réel + nom lisible).
  // On résout ainsi l'alias `root` vers son vrai id Drive + "Mon disque".
  const currentSegment = useMemo<DriveFolderPathSegment | null>(() => {
    if (breadcrumbs.length > 0) return breadcrumbs[breadcrumbs.length - 1];
    return null;
  }, [breadcrumbs]);

  // Dossiers d'abord, triés alpha ; fichiers grisés ensuite.
  const sorted = useMemo(() => {
    const arr = [...files];
    arr.sort((a, b) => {
      const af = isFolder(a) ? 0 : 1;
      const bf = isFolder(b) ? 0 : 1;
      if (af !== bf) return af - bf;
      return (a?.name || "").localeCompare(b?.name || "", "fr", {
        sensitivity: "base"
      });
    });
    return arr;
  }, [files]);

  if (!open) return null;

  function handleSelect() {
    // Id résolu : segment courant si dispo (gère l'alias `root`), sinon
    // l'id de navigation brut.
    const resolvedId = currentSegment?.id || currentFolderId;
    const resolvedName = currentSegment?.name || "Dossier";
    if (!resolvedId || resolvedId === ROOT_ID) {
      // À la racine sans breadcrumb résolu → on tente quand même avec `root`.
      onSelect(resolvedId || ROOT_ID, resolvedName);
      return;
    }
    onSelect(resolvedId, resolvedName);
  }

  const selectLabel = currentSegment?.name
    ? `Choisir « ${currentSegment.name} »`
    : "Choisir ce dossier";

  return (
    <div
      className="fixed inset-0 z-[1300] flex items-center justify-center bg-black/70 p-4"
      onClick={onClose}
    >
      <div
        className="flex h-[80vh] max-h-[640px] w-full max-w-3xl flex-col overflow-hidden rounded-2xl border border-brand-800 bg-brand-950 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* En-tête ------------------------------------------------------- */}
        <header className="flex items-center justify-between gap-3 border-b border-brand-800 px-5 py-3">
          <div className="flex items-center gap-2">
            <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-accent-500/15 text-accent-500">
              <FolderOpen className="h-4.5 w-4.5" />
            </span>
            <div>
              <h3 className="text-base font-bold text-white">
                Choisir un dossier Drive
              </h3>
              <p className="text-[11px] text-white/50">
                Navigue dans ton Drive et sélectionne le dossier à lier.
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg p-1.5 text-white/50 hover:bg-white/10 hover:text-white"
            aria-label="Fermer"
          >
            <X className="h-4 w-4" />
          </button>
        </header>

        {/* Breadcrumbs --------------------------------------------------- */}
        <div className="flex items-center gap-2 border-b border-brand-800 px-5 py-2">
          <nav className="flex min-w-0 flex-1 items-center gap-1 overflow-x-auto whitespace-nowrap text-xs">
            <button
              type="button"
              onClick={() => setCurrentFolderId(ROOT_ID)}
              className="flex shrink-0 items-center gap-1 rounded px-1 py-0.5 text-white/60 hover:bg-white/5 hover:text-white"
              title="Racine du Drive"
            >
              <Home className="h-3.5 w-3.5 text-accent-500" />
            </button>
            {breadcrumbs.length === 0 ? (
              <span className="text-white/45">Chargement…</span>
            ) : (
              breadcrumbs.map((s, i) => (
                <span key={s.id} className="flex items-center gap-1">
                  <ChevronRight className="h-3 w-3 shrink-0 text-white/30" />
                  <button
                    type="button"
                    onClick={() => navigateToBreadcrumb(s)}
                    className={`max-w-[14rem] truncate rounded px-1 py-0.5 hover:bg-white/5 ${
                      i === breadcrumbs.length - 1
                        ? "font-semibold text-white"
                        : "text-white/60 hover:text-white"
                    }`}
                    title={s.name}
                  >
                    {s.name}
                  </button>
                </span>
              ))
            )}
          </nav>
          <button
            type="button"
            onClick={refresh}
            className="shrink-0 rounded-lg border border-brand-800 p-1.5 text-white/50 hover:bg-white/5 hover:text-white"
            title="Rafraîchir"
            aria-label="Rafraîchir"
          >
            <RefreshCw className="h-3.5 w-3.5" />
          </button>
        </div>

        {/* Corps : liste des dossiers ------------------------------------ */}
        <div className="min-h-0 flex-1 overflow-y-auto p-3">
          {loading ? (
            <div className="space-y-2">
              {Array.from({ length: 7 }).map((_, i) => (
                <div
                  key={i}
                  className="h-11 animate-pulse rounded-lg border border-brand-800 bg-brand-900/60"
                />
              ))}
            </div>
          ) : error ? (
            <div className="flex flex-col items-center justify-center gap-3 p-10 text-center">
              <AlertCircle className="h-8 w-8 text-rose-300" />
              <div>
                <p className="text-sm font-semibold text-white">
                  {error.kind === "auth"
                    ? "Connexion Drive requise"
                    : error.kind === "permission"
                      ? "Accès refusé"
                      : error.kind === "notfound"
                        ? "Dossier introuvable"
                        : "Erreur Drive"}
                </p>
                <p className="mt-1 max-w-md text-xs text-white/60">
                  {error.kind === "auth"
                    ? "Connecte ton compte Google Drive dans Paramètres > Drive."
                    : error.message}
                </p>
              </div>
              {error.kind !== "auth" ? (
                <button
                  type="button"
                  onClick={refresh}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-brand-800 px-3 py-1.5 text-xs text-white/70 hover:bg-white/5"
                >
                  <RefreshCw className="h-3.5 w-3.5" /> Réessayer
                </button>
              ) : null}
            </div>
          ) : sorted.length === 0 ? (
            <div className="flex flex-col items-center justify-center gap-3 p-12 text-center text-white/60">
              <Inbox className="h-10 w-10 text-white/30" />
              <p className="text-sm">Ce dossier est vide.</p>
              <p className="text-xs text-white/40">
                Tu peux quand même le sélectionner ci-dessous.
              </p>
            </div>
          ) : (
            <ul className="space-y-1">
              {sorted.map((f) => {
                const folder = isFolder(f);
                return (
                  <li key={f.id}>
                    <button
                      type="button"
                      disabled={!folder}
                      onClick={() => folder && navigateInto(f)}
                      className={`flex w-full items-center gap-3 rounded-lg border px-3 py-2 text-left transition ${
                        folder
                          ? "cursor-pointer border-brand-800 bg-brand-900 text-white hover:border-accent-500/50 hover:bg-accent-500/10"
                          : "cursor-not-allowed border-transparent bg-transparent text-white/30"
                      }`}
                      title={
                        folder
                          ? `Ouvrir « ${f.name} »`
                          : "Seuls les dossiers peuvent être sélectionnés"
                      }
                    >
                      <Folder
                        className={`h-5 w-5 shrink-0 ${
                          folder ? "text-amber-300" : "text-white/20"
                        }`}
                      />
                      <span className="min-w-0 flex-1 truncate text-sm">
                        {f.name}
                      </span>
                      {folder ? (
                        <ChevronRight className="h-4 w-4 shrink-0 text-white/30" />
                      ) : (
                        <span className="shrink-0 text-[10px] uppercase text-white/25">
                          Fichier
                        </span>
                      )}
                    </button>
                  </li>
                );
              })}
              {nextPageToken ? (
                <li className="pt-1">
                  <button
                    type="button"
                    onClick={loadMore}
                    disabled={loadingMore}
                    className="inline-flex w-full items-center justify-center gap-2 rounded-lg border border-brand-800 px-3 py-1.5 text-xs text-white/70 hover:bg-white/5 disabled:opacity-50"
                  >
                    {loadingMore ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    ) : null}
                    Charger plus de dossiers
                  </button>
                </li>
              ) : null}
            </ul>
          )}
        </div>

        {/* Pied : sélection ---------------------------------------------- */}
        <footer className="flex flex-wrap items-center justify-between gap-3 border-t border-brand-800 px-5 py-3">
          <p className="min-w-0 flex-1 text-xs text-white/55">
            Dossier courant :{" "}
            <span className="font-semibold text-white/80">
              {currentSegment?.name || "Mon disque"}
            </span>
          </p>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={onClose}
              className="rounded-lg border border-brand-700 px-3 py-1.5 text-sm text-white/70 hover:bg-white/5"
            >
              Annuler
            </button>
            <button
              type="button"
              onClick={handleSelect}
              disabled={loading || !!error}
              className="inline-flex items-center gap-1.5 rounded-lg bg-accent-500 px-3 py-1.5 text-sm font-semibold text-white hover:bg-accent-400 disabled:opacity-50"
            >
              <Check className="h-4 w-4" />
              {selectLabel}
            </button>
          </div>
        </footer>
      </div>
    </div>
  );
}

export default DriveFolderPicker;
