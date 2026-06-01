"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type DragEvent,
  type ReactNode
} from "react";
import {
  AlertCircle,
  ArrowDownAZ,
  ArrowUpAZ,
  ChevronRight,
  Download,
  Eye,
  File as FileIcon,
  FileImage,
  FileSpreadsheet,
  FileText,
  FileType2,
  Film,
  Folder,
  FolderOpen,
  FolderPlus,
  Grid3x3,
  Inbox,
  List as ListIcon,
  Loader2,
  Maximize2,
  Minimize2,
  MoreVertical,
  Move,
  Pencil,
  Plus,
  RefreshCw,
  Search,
  Share2,
  Trash2,
  Upload,
  UploadCloud,
  X
} from "lucide-react";

import { useConfirm } from "@/components/confirm-dialog";
import { authedFetch } from "@/lib/auth";

// ---------------------------------------------------------------------------
// Types (miroir des schémas backend Phase 2)
// ---------------------------------------------------------------------------

export type DriveOwner = {
  display_name?: string | null;
  email_address?: string | null;
};

export type DriveFile = {
  id: string;
  name: string;
  mime_type: string;
  size?: string | null;
  modified_time?: string | null;
  created_time?: string | null;
  owners?: DriveOwner[];
  parents?: string[];
  thumbnail_link?: string | null;
  web_view_link?: string | null;
  icon_link?: string | null;
  trashed?: boolean | null;
  is_folder?: boolean;
};

type DriveFolderContents = {
  files: DriveFile[];
  next_page_token?: string | null;
};

type DriveFolderPathSegment = { id: string; name: string };
type DriveFolderPath = { segments: DriveFolderPathSegment[] };
type DrivePreviewUrl = {
  preview_url: string;
  web_view_link?: string | null;
};

type DriveActions = {
  upload?: boolean;
  rename?: boolean;
  move?: boolean;
  delete?: boolean;
  createFolder?: boolean;
  share?: boolean;
};

const DEFAULT_ACTIONS: Required<DriveActions> = {
  upload: true,
  rename: true,
  move: true,
  delete: true,
  createFolder: true,
  share: true
};

const FOLDER_MIME = "application/vnd.google-apps.folder";
const PAGE_SIZE = 50;
const VIEW_STORAGE_KEY = "kratos.driveExplorer.view";

type ViewMode = "grid" | "list";
type SortField = "name" | "modified_time" | "size";
type SortDir = "asc" | "desc";

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

export type DriveFolderExplorerProps = {
  /** ID du dossier Drive racine à afficher. */
  folderId: string;
  /** Callback déclenché quand l'utilisateur clique sur un fichier (non dossier). */
  onFileSelected?: (file: DriveFile) => void;
  /** Actions autorisées. Défaut : tout activé. */
  allowedActions?: DriveActions;
  /** Classes additionnelles pour le wrapper. */
  className?: string;
};

// ---------------------------------------------------------------------------
// Toasts (système local au composant — pas de dépendance externe)
// ---------------------------------------------------------------------------

type ToastKind = "success" | "error" | "info";
type Toast = { id: number; kind: ToastKind; message: string };

function useToasts() {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const idRef = useRef(0);
  const push = useCallback((kind: ToastKind, message: string) => {
    idRef.current += 1;
    const id = idRef.current;
    setToasts((prev) => [...prev, { id, kind, message }]);
    window.setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id));
    }, 4000);
  }, []);
  const dismiss = useCallback((id: number) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);
  return { toasts, push, dismiss };
}

function ToastStack({
  toasts,
  onDismiss
}: {
  toasts: Toast[];
  onDismiss: (id: number) => void;
}) {
  if (toasts.length === 0) return null;
  return (
    <div className="pointer-events-none fixed inset-x-0 bottom-4 z-[1100] flex flex-col items-center gap-2 px-3">
      {toasts.map((t) => (
        <div
          key={t.id}
          className={`pointer-events-auto flex max-w-md items-start gap-2 rounded-xl border px-3 py-2 text-sm shadow-lg ${
            t.kind === "success"
              ? "border-emerald-500/40 bg-emerald-500/15 text-emerald-100"
              : t.kind === "error"
                ? "border-rose-500/40 bg-rose-500/15 text-rose-100"
                : "border-white/15 bg-brand-900 text-white/90"
          }`}
        >
          <span className="flex-1 break-words">{t.message}</span>
          <button
            type="button"
            onClick={() => onDismiss(t.id)}
            className="rounded p-0.5 text-white/60 hover:bg-white/10 hover:text-white"
            aria-label="Fermer la notification"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Helpers généraux
// ---------------------------------------------------------------------------

function isFolder(f: DriveFile): boolean {
  return f.is_folder === true || f.mime_type === FOLDER_MIME;
}

function formatBytes(raw: string | null | undefined): string {
  if (!raw) return "—";
  const n = Number(raw);
  if (!Number.isFinite(n) || n < 0) return "—";
  const units = ["o", "Ko", "Mo", "Go", "To"];
  let val = n;
  let u = 0;
  while (val >= 1024 && u < units.length - 1) {
    val /= 1024;
    u += 1;
  }
  return `${val.toFixed(val >= 10 || u === 0 ? 0 : 1)} ${units[u]}`;
}

function formatDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString("fr-CA", {
      dateStyle: "short",
      timeStyle: "short"
    });
  } catch {
    return iso;
  }
}

/**
 * Étiquette courte du type de fichier pour l'affichage dans la colonne « Type ».
 * On normalise les MIME Google + Office vers une étiquette compréhensible.
 */
function shortMimeLabel(mime: string): string {
  if (mime === FOLDER_MIME) return "Dossier";
  if (mime.startsWith("application/vnd.google-apps.document")) return "Google Doc";
  if (mime.startsWith("application/vnd.google-apps.spreadsheet"))
    return "Google Sheet";
  if (mime.startsWith("application/vnd.google-apps.presentation"))
    return "Google Slides";
  if (mime.startsWith("application/vnd.google-apps.form")) return "Google Form";
  if (mime === "application/pdf") return "PDF";
  if (mime.startsWith("image/")) return "Image";
  if (mime.startsWith("video/")) return "Vidéo";
  if (mime.startsWith("audio/")) return "Audio";
  if (
    mime ===
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
  )
    return "Word";
  if (
    mime ===
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
  )
    return "Excel";
  if (
    mime ===
    "application/vnd.openxmlformats-officedocument.presentationml.presentation"
  )
    return "PowerPoint";
  if (mime === "text/csv") return "CSV";
  if (mime === "text/plain") return "Texte";
  return mime.split("/").pop() || mime;
}

function FileTypeIcon({
  file,
  className = "h-6 w-6"
}: {
  file: DriveFile;
  className?: string;
}) {
  const mime = file.mime_type || "";
  if (isFolder(file))
    return <Folder className={`${className} text-amber-300`} />;
  if (mime.startsWith("image/"))
    return <FileImage className={`${className} text-fuchsia-300`} />;
  if (mime.startsWith("video/"))
    return <Film className={`${className} text-rose-300`} />;
  if (mime === "application/pdf")
    return <FileType2 className={`${className} text-rose-400`} />;
  if (
    mime.startsWith("application/vnd.google-apps.spreadsheet") ||
    mime ===
      "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" ||
    mime === "text/csv"
  )
    return <FileSpreadsheet className={`${className} text-emerald-300`} />;
  if (
    mime.startsWith("application/vnd.google-apps.document") ||
    mime ===
      "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
  )
    return <FileText className={`${className} text-sky-300`} />;
  return <FileIcon className={`${className} text-white/60`} />;
}

function canPreviewInline(mime: string): boolean {
  if (!mime) return false;
  if (mime === FOLDER_MIME) return false;
  if (mime.startsWith("image/")) return true;
  if (mime.startsWith("video/")) return true;
  if (mime === "application/pdf") return true;
  if (mime.startsWith("application/vnd.google-apps.")) return true;
  return false;
}

function isOfficeMime(mime: string): boolean {
  return (
    mime ===
      "application/vnd.openxmlformats-officedocument.wordprocessingml.document" ||
    mime ===
      "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" ||
    mime ===
      "application/vnd.openxmlformats-officedocument.presentationml.presentation"
  );
}

/**
 * Lit le `detail` d'une réponse FastAPI en erreur, avec fallback sur
 * `res.statusText` puis sur `http_<code>`. Pattern hérité de la PR #521.
 */
async function readErrorDetail(res: Response): Promise<string> {
  try {
    const txt = await res.text();
    if (!txt) return `Erreur ${res.status}`;
    try {
      const parsed = JSON.parse(txt) as { detail?: unknown };
      if (typeof parsed.detail === "string") return parsed.detail;
      if (parsed.detail && typeof parsed.detail === "object") {
        const d = parsed.detail as { message?: string };
        if (typeof d.message === "string") return d.message;
        return JSON.stringify(parsed.detail);
      }
      return txt;
    } catch {
      return txt;
    }
  } catch {
    return `Erreur ${res.status}`;
  }
}

// ---------------------------------------------------------------------------
// Composant principal
// ---------------------------------------------------------------------------

export function DriveFolderExplorer({
  folderId,
  onFileSelected,
  allowedActions,
  className = ""
}: DriveFolderExplorerProps) {
  const actions = { ...DEFAULT_ACTIONS, ...(allowedActions || {}) };
  const confirm = useConfirm();
  const { toasts, push: toast, dismiss } = useToasts();

  // Navigation : pile de breadcrumbs locale au composant. Le sommet de pile est
  // le dossier visible. On démarre toujours par le `folderId` racine fourni
  // en prop.
  const [currentFolderId, setCurrentFolderId] = useState<string>(folderId);
  useEffect(() => {
    setCurrentFolderId(folderId);
  }, [folderId]);

  const [breadcrumbs, setBreadcrumbs] = useState<DriveFolderPathSegment[]>([]);
  const [files, setFiles] = useState<DriveFile[]>([]);
  const [nextPageToken, setNextPageToken] = useState<string | null>(null);

  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<{
    kind: "auth" | "permission" | "notfound" | "network" | "other";
    message: string;
  } | null>(null);

  const [view, setView] = useState<ViewMode>("grid");
  const [sortField, setSortField] = useState<SortField>("name");
  const [sortDir, setSortDir] = useState<SortDir>("asc");

  // Charge la préférence de vue depuis localStorage (au mount).
  useEffect(() => {
    if (typeof window === "undefined") return;
    try {
      const stored = window.localStorage.getItem(VIEW_STORAGE_KEY);
      if (stored === "grid" || stored === "list") setView(stored);
    } catch {
      /* ignore */
    }
  }, []);

  function changeView(v: ViewMode) {
    setView(v);
    try {
      window.localStorage.setItem(VIEW_STORAGE_KEY, v);
    } catch {
      /* ignore */
    }
  }

  // -------------------------------------------------------------------------
  // Recherche (debounce 300ms)
  // -------------------------------------------------------------------------
  const [searchInput, setSearchInput] = useState("");
  const [searchQuery, setSearchQuery] = useState("");
  useEffect(() => {
    const t = window.setTimeout(() => {
      setSearchQuery(searchInput.trim());
    }, 300);
    return () => window.clearTimeout(t);
  }, [searchInput]);
  const isSearching = searchQuery.length > 0;

  // -------------------------------------------------------------------------
  // Fetch breadcrumbs path
  // -------------------------------------------------------------------------
  const loadPath = useCallback(async (id: string) => {
    try {
      const res = await authedFetch(
        `/api/v1/drive/folders/${encodeURIComponent(id)}/path`
      );
      if (!res.ok) {
        // On ne fait pas planter le composant pour ça — on tombe en arrière
        // sur un breadcrumb à 1 segment.
        setBreadcrumbs([{ id, name: "Dossier" }]);
        return;
      }
      const data = (await res.json()) as DriveFolderPath;
      setBreadcrumbs(data.segments || [{ id, name: "Dossier" }]);
    } catch {
      setBreadcrumbs([{ id, name: "Dossier" }]);
    }
  }, []);

  // -------------------------------------------------------------------------
  // Fetch liste fichiers (ou résultats de recherche)
  // -------------------------------------------------------------------------
  const loadListing = useCallback(
    async (folder: string, query: string, append = false) => {
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

        let url: string;
        if (query) {
          params.set("q", query);
          params.set("parent_folder_id", folder);
          url = `/api/v1/drive/search?${params.toString()}`;
        } else {
          url = `/api/v1/drive/folders/${encodeURIComponent(folder)}/files?${params.toString()}`;
        }

        const res = await authedFetch(url);
        if (!res.ok) {
          const msg = await readErrorDetail(res);
          if (res.status === 401)
            setError({ kind: "auth", message: msg });
          else if (res.status === 403)
            setError({ kind: "permission", message: msg });
          else if (res.status === 404)
            setError({ kind: "notfound", message: msg });
          else setError({ kind: "other", message: msg });
          if (!append) setFiles([]);
          return;
        }
        const data = (await res.json()) as DriveFolderContents;
        setFiles((prev) => (append ? [...prev, ...data.files] : data.files));
        setNextPageToken(data.next_page_token ?? null);
      } catch (e) {
        setError({
          kind: "network",
          message: (e as Error).message || "Erreur réseau"
        });
        if (!append) setFiles([]);
      } finally {
        setLoading(false);
        setLoadingMore(false);
      }
    },
    [nextPageToken]
  );

  // Reload quand on change de dossier ou de query.
  useEffect(() => {
    setNextPageToken(null);
    void loadListing(currentFolderId, searchQuery, false);
    if (!searchQuery) void loadPath(currentFolderId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentFolderId, searchQuery]);

  function refresh() {
    setNextPageToken(null);
    void loadListing(currentFolderId, searchQuery, false);
    void loadPath(currentFolderId);
  }

  function loadMore() {
    if (!nextPageToken) return;
    void loadListing(currentFolderId, searchQuery, true);
  }

  // -------------------------------------------------------------------------
  // Navigation
  // -------------------------------------------------------------------------
  function navigateInto(folder: DriveFile) {
    if (!isFolder(folder)) return;
    setSearchInput("");
    setSearchQuery("");
    setCurrentFolderId(folder.id);
  }

  function navigateToBreadcrumb(seg: DriveFolderPathSegment) {
    setSearchInput("");
    setSearchQuery("");
    setCurrentFolderId(seg.id);
  }

  // -------------------------------------------------------------------------
  // Tri (vue liste)
  // -------------------------------------------------------------------------
  const sortedFiles = useMemo(() => {
    const arr = [...files];
    arr.sort((a, b) => {
      // Dossiers d'abord, toujours.
      const af = isFolder(a) ? 0 : 1;
      const bf = isFolder(b) ? 0 : 1;
      if (af !== bf) return af - bf;

      let cmp = 0;
      if (sortField === "name") {
        cmp = a.name.localeCompare(b.name, "fr", { sensitivity: "base" });
      } else if (sortField === "modified_time") {
        const am = a.modified_time ? Date.parse(a.modified_time) : 0;
        const bm = b.modified_time ? Date.parse(b.modified_time) : 0;
        cmp = am - bm;
      } else if (sortField === "size") {
        const as = a.size ? Number(a.size) : 0;
        const bs = b.size ? Number(b.size) : 0;
        cmp = as - bs;
      }
      return sortDir === "asc" ? cmp : -cmp;
    });
    return arr;
  }, [files, sortField, sortDir]);

  function toggleSort(field: SortField) {
    if (sortField === field) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortField(field);
      setSortDir("asc");
    }
  }

  // -------------------------------------------------------------------------
  // Drag & drop upload
  // -------------------------------------------------------------------------
  const [dragOver, setDragOver] = useState(false);
  const dragCounter = useRef(0);
  const [uploads, setUploads] = useState<
    { id: number; name: string; progress: number; status: "running" | "done" | "error"; error?: string }[]
  >([]);
  const uploadIdRef = useRef(0);

  const onDragEnter = useCallback(
    (e: DragEvent) => {
      if (!actions.upload) return;
      if (!e.dataTransfer?.types?.includes("Files")) return;
      e.preventDefault();
      dragCounter.current += 1;
      setDragOver(true);
    },
    [actions.upload]
  );
  const onDragLeave = useCallback(
    (e: DragEvent) => {
      if (!actions.upload) return;
      e.preventDefault();
      dragCounter.current = Math.max(0, dragCounter.current - 1);
      if (dragCounter.current === 0) setDragOver(false);
    },
    [actions.upload]
  );
  const onDragOver = useCallback(
    (e: DragEvent) => {
      if (!actions.upload) return;
      if (!e.dataTransfer?.types?.includes("Files")) return;
      e.preventDefault();
    },
    [actions.upload]
  );
  const onDrop = useCallback(
    (e: DragEvent) => {
      if (!actions.upload) return;
      e.preventDefault();
      dragCounter.current = 0;
      setDragOver(false);
      const files = e.dataTransfer?.files;
      if (!files || files.length === 0) return;
      void uploadFiles(Array.from(files));
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [actions.upload, currentFolderId]
  );

  async function uploadOne(file: File): Promise<DriveFile | null> {
    uploadIdRef.current += 1;
    const id = uploadIdRef.current;
    setUploads((prev) => [
      ...prev,
      { id, name: file.name, progress: 0, status: "running" }
    ]);

    return new Promise((resolve) => {
      const xhr = new XMLHttpRequest();
      const token =
        typeof window !== "undefined"
          ? window.localStorage.getItem("hsi_access_token")
          : null;
      xhr.open(
        "POST",
        `/api/v1/drive/folders/${encodeURIComponent(currentFolderId)}/upload`
      );
      if (token) xhr.setRequestHeader("authorization", `Bearer ${token}`);
      xhr.upload.onprogress = (ev) => {
        if (!ev.lengthComputable) return;
        const pct = Math.round((ev.loaded / ev.total) * 100);
        setUploads((prev) =>
          prev.map((u) => (u.id === id ? { ...u, progress: pct } : u))
        );
      };
      xhr.onload = () => {
        if (xhr.status >= 200 && xhr.status < 300) {
          try {
            const created = JSON.parse(xhr.responseText) as DriveFile;
            setUploads((prev) =>
              prev.map((u) =>
                u.id === id ? { ...u, progress: 100, status: "done" } : u
              )
            );
            window.setTimeout(() => {
              setUploads((prev) => prev.filter((u) => u.id !== id));
            }, 2000);
            resolve(created);
          } catch {
            setUploads((prev) =>
              prev.map((u) =>
                u.id === id
                  ? {
                      ...u,
                      status: "error",
                      error: "Réponse serveur invalide"
                    }
                  : u
              )
            );
            resolve(null);
          }
        } else {
          let msg = `Erreur ${xhr.status}`;
          try {
            const parsed = JSON.parse(xhr.responseText) as {
              detail?: string;
            };
            if (typeof parsed.detail === "string") msg = parsed.detail;
          } catch {
            if (xhr.responseText) msg = xhr.responseText;
          }
          setUploads((prev) =>
            prev.map((u) =>
              u.id === id ? { ...u, status: "error", error: msg } : u
            )
          );
          resolve(null);
        }
      };
      xhr.onerror = () => {
        setUploads((prev) =>
          prev.map((u) =>
            u.id === id ? { ...u, status: "error", error: "Erreur réseau" } : u
          )
        );
        resolve(null);
      };
      const fd = new FormData();
      fd.append("file", file, file.name);
      xhr.send(fd);
    });
  }

  async function uploadFiles(list: File[]) {
    const results = await Promise.all(list.map((f) => uploadOne(f)));
    const ok = results.filter((r) => r !== null).length;
    const ko = results.length - ok;
    if (ok > 0)
      toast(
        "success",
        `${ok} fichier${ok > 1 ? "s" : ""} téléversé${ok > 1 ? "s" : ""}.`
      );
    if (ko > 0)
      toast(
        "error",
        `${ko} téléversement${ko > 1 ? "s" : ""} échoué${ko > 1 ? "s" : ""}.`
      );
    if (ok > 0) refresh();
  }

  // Bouton « Téléverser » dans le header.
  const fileInputRef = useRef<HTMLInputElement>(null);
  function triggerFilePicker() {
    fileInputRef.current?.click();
  }
  function onFileInputChange(e: React.ChangeEvent<HTMLInputElement>) {
    const selected = e.target.files;
    if (!selected || selected.length === 0) return;
    void uploadFiles(Array.from(selected));
    e.target.value = "";
  }

  // -------------------------------------------------------------------------
  // Modal de preview
  // -------------------------------------------------------------------------
  const [previewing, setPreviewing] = useState<DriveFile | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [previewFullscreen, setPreviewFullscreen] = useState(false);

  async function openPreview(file: DriveFile) {
    if (isFolder(file)) return;
    setPreviewing(file);
    setPreviewUrl(null);
    setPreviewFullscreen(false);

    if (!canPreviewInline(file.mime_type)) return;
    try {
      const res = await authedFetch(
        `/api/v1/drive/files/${encodeURIComponent(file.id)}/preview-url`
      );
      if (!res.ok) {
        const msg = await readErrorDetail(res);
        toast("error", `Aperçu indisponible : ${msg}`);
        return;
      }
      const data = (await res.json()) as DrivePreviewUrl;
      setPreviewUrl(data.preview_url);
    } catch (e) {
      toast("error", `Aperçu indisponible : ${(e as Error).message}`);
    }
  }

  function closePreview() {
    setPreviewing(null);
    setPreviewUrl(null);
    setPreviewFullscreen(false);
  }

  // -------------------------------------------------------------------------
  // Actions individuelles (rename, move, delete, share, download)
  // -------------------------------------------------------------------------
  type ActionModalState =
    | { kind: "rename"; file: DriveFile }
    | { kind: "move"; file: DriveFile }
    | { kind: "share"; file: DriveFile }
    | { kind: "createFolder" }
    | null;
  const [actionModal, setActionModal] = useState<ActionModalState>(null);

  async function doRename(file: DriveFile, newName: string) {
    const body = JSON.stringify({ name: newName });
    const res = await authedFetch(
      `/api/v1/drive/files/${encodeURIComponent(file.id)}`,
      { method: "PATCH", body }
    );
    if (!res.ok) {
      const msg = await readErrorDetail(res);
      toast("error", `Renommage échoué : ${msg}`);
      return;
    }
    toast("success", "Renommé.");
    refresh();
  }

  async function doMove(file: DriveFile, newParentId: string) {
    const body = JSON.stringify({
      parent_folder_id: newParentId,
      old_parent_folder_id: currentFolderId
    });
    const res = await authedFetch(
      `/api/v1/drive/files/${encodeURIComponent(file.id)}`,
      { method: "PATCH", body }
    );
    if (!res.ok) {
      const msg = await readErrorDetail(res);
      toast("error", `Déplacement échoué : ${msg}`);
      return;
    }
    toast("success", "Déplacé.");
    refresh();
  }

  async function doShare(
    file: DriveFile,
    payload: {
      email: string;
      role: string;
      send_notification: boolean;
      message: string;
    }
  ) {
    const res = await authedFetch(
      `/api/v1/drive/files/${encodeURIComponent(file.id)}/share`,
      { method: "POST", body: JSON.stringify(payload) }
    );
    if (!res.ok) {
      const msg = await readErrorDetail(res);
      toast("error", `Partage échoué : ${msg}`);
      return;
    }
    toast("success", `Partagé avec ${payload.email}.`);
  }

  async function doDelete(file: DriveFile, permanent: boolean) {
    const ok = await confirm({
      title: permanent
        ? `Supprimer définitivement « ${file.name} » ?`
        : `Envoyer « ${file.name} » à la corbeille ?`,
      description: permanent
        ? "Cette action est irréversible. Le fichier sera supprimé immédiatement de Drive."
        : "Tu pourras restaurer depuis la corbeille Drive si besoin.",
      confirmLabel: permanent ? "Supprimer définitivement" : "Mettre à la corbeille",
      destructive: true
    });
    if (!ok) return;
    const qs = permanent ? "?permanent=true" : "";
    const res = await authedFetch(
      `/api/v1/drive/files/${encodeURIComponent(file.id)}${qs}`,
      { method: "DELETE" }
    );
    if (!res.ok && res.status !== 204) {
      const msg = await readErrorDetail(res);
      toast("error", `Suppression échouée : ${msg}`);
      return;
    }
    toast("success", permanent ? "Supprimé définitivement." : "Mis à la corbeille.");
    refresh();
  }

  async function doDownload(file: DriveFile) {
    if (isFolder(file)) return;
    try {
      const res = await authedFetch(
        `/api/v1/drive/files/${encodeURIComponent(file.id)}/download`
      );
      if (!res.ok) {
        const msg = await readErrorDetail(res);
        toast("error", `Téléchargement échoué : ${msg}`);
        return;
      }
      const blob = await res.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = file.name;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      window.URL.revokeObjectURL(url);
    } catch (e) {
      toast("error", `Téléchargement échoué : ${(e as Error).message}`);
    }
  }

  async function doCreateFolder(name: string) {
    const res = await authedFetch(
      `/api/v1/drive/folders/${encodeURIComponent(currentFolderId)}/subfolders`,
      { method: "POST", body: JSON.stringify({ name }) }
    );
    if (!res.ok) {
      const msg = await readErrorDetail(res);
      toast("error", `Création échouée : ${msg}`);
      return;
    }
    toast("success", "Dossier créé.");
    refresh();
  }

  // -------------------------------------------------------------------------
  // Bouton « + Nouveau »
  // -------------------------------------------------------------------------
  const [newMenuOpen, setNewMenuOpen] = useState(false);

  // -------------------------------------------------------------------------
  // Rendu
  // -------------------------------------------------------------------------
  return (
    <div
      className={`relative rounded-2xl border border-brand-800 bg-brand-900 ${className}`}
      onDragEnter={onDragEnter}
      onDragLeave={onDragLeave}
      onDragOver={onDragOver}
      onDrop={onDrop}
    >
      <ToastStack toasts={toasts} onDismiss={dismiss} />

      {/* Header --------------------------------------------------------- */}
      <div className="flex flex-col gap-3 border-b border-brand-800 p-3 sm:flex-row sm:items-center sm:gap-2">
        <Breadcrumbs
          segments={breadcrumbs}
          isSearching={isSearching}
          onNavigate={navigateToBreadcrumb}
        />

        <div className="flex flex-wrap items-center gap-2 sm:ml-auto">
          <div className="relative">
            <Search className="pointer-events-none absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-white/40" />
            <input
              type="search"
              placeholder="Rechercher…"
              value={searchInput}
              onChange={(e) => setSearchInput(e.target.value)}
              className="w-48 rounded-lg border border-brand-800 bg-brand-950 py-1.5 pl-7 pr-2 text-xs text-white placeholder-white/30 focus:border-accent-500 focus:outline-none sm:w-56"
            />
          </div>

          <div className="inline-flex overflow-hidden rounded-lg border border-brand-800">
            <button
              type="button"
              onClick={() => changeView("grid")}
              className={`flex items-center gap-1 px-2 py-1.5 text-xs ${
                view === "grid"
                  ? "bg-accent-500/20 text-accent-300"
                  : "text-white/60 hover:bg-white/5"
              }`}
              title="Vue grille"
              aria-label="Vue grille"
            >
              <Grid3x3 className="h-3.5 w-3.5" />
            </button>
            <button
              type="button"
              onClick={() => changeView("list")}
              className={`flex items-center gap-1 border-l border-brand-800 px-2 py-1.5 text-xs ${
                view === "list"
                  ? "bg-accent-500/20 text-accent-300"
                  : "text-white/60 hover:bg-white/5"
              }`}
              title="Vue liste"
              aria-label="Vue liste"
            >
              <ListIcon className="h-3.5 w-3.5" />
            </button>
          </div>

          <button
            type="button"
            onClick={refresh}
            className="rounded-lg border border-brand-800 px-2 py-1.5 text-xs text-white/60 hover:bg-white/5 hover:text-white"
            title="Rafraîchir"
            aria-label="Rafraîchir"
          >
            <RefreshCw className="h-3.5 w-3.5" />
          </button>

          {(actions.upload || actions.createFolder) && !isSearching ? (
            <div className="relative">
              <button
                type="button"
                onClick={() => setNewMenuOpen((v) => !v)}
                className="inline-flex items-center gap-1 rounded-lg bg-accent-500 px-2.5 py-1.5 text-xs font-semibold text-white hover:bg-accent-600"
              >
                <Plus className="h-3.5 w-3.5" />
                Nouveau
              </button>
              {newMenuOpen ? (
                <>
                  <button
                    type="button"
                    aria-hidden="true"
                    tabIndex={-1}
                    onClick={() => setNewMenuOpen(false)}
                    className="fixed inset-0 z-30 cursor-default"
                  />
                  <div className="absolute right-0 z-40 mt-1 w-52 overflow-hidden rounded-lg border border-brand-800 bg-brand-950 text-xs shadow-xl">
                    {actions.createFolder ? (
                      <button
                        type="button"
                        onClick={() => {
                          setNewMenuOpen(false);
                          setActionModal({ kind: "createFolder" });
                        }}
                        className="flex w-full items-center gap-2 px-3 py-2 text-white/80 hover:bg-white/5"
                      >
                        <FolderPlus className="h-3.5 w-3.5" /> Nouveau dossier
                      </button>
                    ) : null}
                    {actions.upload ? (
                      <button
                        type="button"
                        onClick={() => {
                          setNewMenuOpen(false);
                          triggerFilePicker();
                        }}
                        className="flex w-full items-center gap-2 border-t border-brand-800 px-3 py-2 text-white/80 hover:bg-white/5"
                      >
                        <Upload className="h-3.5 w-3.5" /> Téléverser un fichier
                      </button>
                    ) : null}
                  </div>
                </>
              ) : null}
            </div>
          ) : null}

          <input
            ref={fileInputRef}
            type="file"
            multiple
            className="hidden"
            onChange={onFileInputChange}
          />
        </div>
      </div>

      {/* Corps ---------------------------------------------------------- */}
      <div className="relative min-h-[14rem]">
        {loading ? (
          <SkeletonGrid view={view} />
        ) : error ? (
          <ErrorState
            kind={error.kind}
            message={error.message}
            onRetry={refresh}
          />
        ) : files.length === 0 ? (
          <EmptyState
            isSearching={isSearching}
            canUpload={actions.upload}
            onUpload={triggerFilePicker}
          />
        ) : view === "grid" ? (
          <GridView
            files={sortedFiles}
            actions={actions}
            onOpenFolder={navigateInto}
            onPreviewFile={openPreview}
            onAction={(file, kind) => handleAction(file, kind)}
            onFileSelected={onFileSelected}
          />
        ) : (
          <ListView
            files={sortedFiles}
            actions={actions}
            sortField={sortField}
            sortDir={sortDir}
            onToggleSort={toggleSort}
            onOpenFolder={navigateInto}
            onPreviewFile={openPreview}
            onAction={(file, kind) => handleAction(file, kind)}
            onFileSelected={onFileSelected}
          />
        )}

        {/* Pagination */}
        {!loading && !error && nextPageToken ? (
          <div className="flex justify-center border-t border-brand-800 p-3">
            <button
              type="button"
              onClick={loadMore}
              disabled={loadingMore}
              className="inline-flex items-center gap-2 rounded-lg border border-brand-800 px-3 py-1.5 text-xs text-white/70 hover:bg-white/5 disabled:opacity-50"
            >
              {loadingMore ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : null}
              Charger plus
            </button>
          </div>
        ) : null}

        {/* Overlay drag-and-drop */}
        {dragOver && actions.upload ? (
          <div className="pointer-events-none absolute inset-0 z-20 flex items-center justify-center rounded-2xl border-2 border-dashed border-accent-500 bg-accent-500/10 backdrop-blur-sm">
            <div className="flex flex-col items-center gap-2 text-sm font-semibold text-accent-200">
              <UploadCloud className="h-8 w-8" />
              Déposez ici pour téléverser
            </div>
          </div>
        ) : null}
      </div>

      {/* Liste de progression des uploads */}
      {uploads.length > 0 ? (
        <div className="fixed bottom-4 right-4 z-[1050] w-80 max-w-[95vw] overflow-hidden rounded-xl border border-brand-800 bg-brand-950 shadow-2xl">
          <div className="flex items-center justify-between border-b border-brand-800 px-3 py-2 text-xs font-semibold text-white">
            Téléversements en cours
            <span className="text-white/40">{uploads.length}</span>
          </div>
          <div className="max-h-56 overflow-y-auto">
            {uploads.map((u) => (
              <div
                key={u.id}
                className="border-b border-brand-800 px-3 py-2 text-xs last:border-b-0"
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="truncate text-white/80">{u.name}</span>
                  <span
                    className={
                      u.status === "done"
                        ? "text-emerald-300"
                        : u.status === "error"
                          ? "text-rose-300"
                          : "text-white/60"
                    }
                  >
                    {u.status === "done"
                      ? "OK"
                      : u.status === "error"
                        ? "Erreur"
                        : `${u.progress}%`}
                  </span>
                </div>
                <div className="mt-1 h-1 overflow-hidden rounded bg-white/10">
                  <div
                    className={`h-full transition-all ${
                      u.status === "error"
                        ? "bg-rose-500"
                        : u.status === "done"
                          ? "bg-emerald-500"
                          : "bg-accent-500"
                    }`}
                    style={{ width: `${u.progress}%` }}
                  />
                </div>
                {u.error ? (
                  <p className="mt-1 text-[10px] text-rose-300">{u.error}</p>
                ) : null}
              </div>
            ))}
          </div>
        </div>
      ) : null}

      {/* Modal preview */}
      {previewing ? (
        <PreviewModal
          file={previewing}
          previewUrl={previewUrl}
          fullscreen={previewFullscreen}
          onToggleFullscreen={() => setPreviewFullscreen((v) => !v)}
          onDownload={() => doDownload(previewing)}
          onClose={closePreview}
        />
      ) : null}

      {/* Modals d'action */}
      {actionModal?.kind === "rename" ? (
        <RenameModal
          file={actionModal.file}
          onCancel={() => setActionModal(null)}
          onSubmit={async (name) => {
            setActionModal(null);
            await doRename(actionModal.file, name);
          }}
        />
      ) : null}
      {actionModal?.kind === "move" ? (
        <MoveModal
          file={actionModal.file}
          currentFolderId={currentFolderId}
          onCancel={() => setActionModal(null)}
          onSubmit={async (newParent) => {
            setActionModal(null);
            await doMove(actionModal.file, newParent);
          }}
        />
      ) : null}
      {actionModal?.kind === "share" ? (
        <ShareModal
          file={actionModal.file}
          onCancel={() => setActionModal(null)}
          onSubmit={async (payload) => {
            setActionModal(null);
            await doShare(actionModal.file, payload);
          }}
        />
      ) : null}
      {actionModal?.kind === "createFolder" ? (
        <CreateFolderModal
          onCancel={() => setActionModal(null)}
          onSubmit={async (name) => {
            setActionModal(null);
            await doCreateFolder(name);
          }}
        />
      ) : null}
    </div>
  );

  // -------------------------------------------------------------------------
  // Dispatcher des actions de menu (rename / move / delete / share / etc.)
  // -------------------------------------------------------------------------
  function handleAction(file: DriveFile, kind: ActionKind) {
    switch (kind) {
      case "open":
        if (isFolder(file)) navigateInto(file);
        else void openPreview(file);
        return;
      case "preview":
        if (!isFolder(file)) void openPreview(file);
        return;
      case "download":
        void doDownload(file);
        return;
      case "rename":
        setActionModal({ kind: "rename", file });
        return;
      case "move":
        setActionModal({ kind: "move", file });
        return;
      case "share":
        setActionModal({ kind: "share", file });
        return;
      case "delete":
        void doDelete(file, false);
        return;
      case "deletePermanent":
        void doDelete(file, true);
        return;
    }
  }
}

// ---------------------------------------------------------------------------
// Sous-composants : header
// ---------------------------------------------------------------------------

function Breadcrumbs({
  segments,
  isSearching,
  onNavigate
}: {
  segments: DriveFolderPathSegment[];
  isSearching: boolean;
  onNavigate: (seg: DriveFolderPathSegment) => void;
}) {
  return (
    <nav className="flex min-w-0 flex-1 items-center gap-1 overflow-x-auto whitespace-nowrap text-xs text-white/70">
      <FolderOpen className="h-3.5 w-3.5 shrink-0 text-accent-500" />
      {segments.length === 0 ? (
        <span className="text-white/40">Chargement…</span>
      ) : (
        segments.map((s, i) => (
          <span key={s.id} className="flex items-center gap-1">
            {i > 0 ? (
              <ChevronRight className="h-3 w-3 shrink-0 text-white/30" />
            ) : null}
            <button
              type="button"
              onClick={() => onNavigate(s)}
              className={`max-w-[14rem] truncate rounded px-1 py-0.5 hover:bg-white/5 ${
                i === segments.length - 1
                  ? "font-semibold text-white"
                  : "text-white/60"
              }`}
              title={s.name}
            >
              {s.name}
            </button>
          </span>
        ))
      )}
      {isSearching ? (
        <span className="ml-2 rounded-full border border-accent-500/40 bg-accent-500/10 px-2 py-0.5 text-[10px] uppercase text-accent-300">
          Recherche
        </span>
      ) : null}
    </nav>
  );
}

// ---------------------------------------------------------------------------
// Sous-composants : états (loading / empty / error)
// ---------------------------------------------------------------------------

function SkeletonGrid({ view }: { view: ViewMode }) {
  const items = Array.from({ length: view === "grid" ? 8 : 6 });
  if (view === "grid") {
    return (
      <div className="grid grid-cols-2 gap-3 p-3 sm:grid-cols-3 lg:grid-cols-4">
        {items.map((_, i) => (
          <div
            key={i}
            className="h-32 animate-pulse rounded-xl border border-brand-800 bg-brand-950/60"
          />
        ))}
      </div>
    );
  }
  return (
    <div className="space-y-2 p-3">
      {items.map((_, i) => (
        <div
          key={i}
          className="h-10 animate-pulse rounded-lg border border-brand-800 bg-brand-950/60"
        />
      ))}
    </div>
  );
}

function EmptyState({
  isSearching,
  canUpload,
  onUpload
}: {
  isSearching: boolean;
  canUpload: boolean;
  onUpload: () => void;
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 p-12 text-center text-white/60">
      <Inbox className="h-10 w-10 text-white/30" />
      <p className="text-sm">
        {isSearching
          ? "Aucun résultat pour cette recherche."
          : "Aucun fichier dans ce dossier."}
      </p>
      {!isSearching && canUpload ? (
        <button
          type="button"
          onClick={onUpload}
          className="inline-flex items-center gap-1.5 rounded-lg bg-accent-500 px-3 py-1.5 text-xs font-semibold text-white hover:bg-accent-600"
        >
          <Upload className="h-3.5 w-3.5" /> Téléverser le premier
        </button>
      ) : null}
    </div>
  );
}

function ErrorState({
  kind,
  message,
  onRetry
}: {
  kind: "auth" | "permission" | "notfound" | "network" | "other";
  message: string;
  onRetry: () => void;
}) {
  const title =
    kind === "auth"
      ? "Connexion Drive requise"
      : kind === "permission"
        ? "Accès refusé"
        : kind === "notfound"
          ? "Dossier introuvable"
          : kind === "network"
            ? "Erreur de connexion"
            : "Erreur Drive";
  const help =
    kind === "auth"
      ? "Tu dois te connecter à Google Drive dans Paramètres."
      : kind === "permission"
        ? "Tu n'as pas les permissions pour ce dossier sur Drive. Demande à son propriétaire de te le partager."
        : kind === "notfound"
          ? "Ce dossier n'existe plus ou a été supprimé."
          : kind === "network"
            ? "Impossible de joindre le serveur. Vérifie ta connexion."
            : message;
  return (
    <div className="flex flex-col items-center justify-center gap-3 p-10 text-center">
      <AlertCircle className="h-8 w-8 text-rose-300" />
      <div>
        <p className="text-sm font-semibold text-white">{title}</p>
        <p className="mt-1 max-w-md text-xs text-white/60">{help}</p>
        {kind !== "auth" && kind !== "permission" && kind !== "notfound" ? (
          <p className="mt-1 text-[10px] font-mono text-white/40">{message}</p>
        ) : null}
      </div>
      {kind === "auth" ? (
        <a
          href="/fr/app/parametres/drive"
          className="inline-flex items-center gap-1.5 rounded-lg bg-accent-500 px-3 py-1.5 text-xs font-semibold text-white hover:bg-accent-600"
        >
          Aller à Paramètres → Drive
        </a>
      ) : (
        <button
          type="button"
          onClick={onRetry}
          className="inline-flex items-center gap-1.5 rounded-lg border border-brand-800 px-3 py-1.5 text-xs text-white/70 hover:bg-white/5"
        >
          <RefreshCw className="h-3.5 w-3.5" /> Réessayer
        </button>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sous-composants : vues
// ---------------------------------------------------------------------------

type ActionKind =
  | "open"
  | "preview"
  | "download"
  | "rename"
  | "move"
  | "share"
  | "delete"
  | "deletePermanent";

function GridView({
  files,
  actions,
  onOpenFolder,
  onPreviewFile,
  onAction,
  onFileSelected
}: {
  files: DriveFile[];
  actions: Required<DriveActions>;
  onOpenFolder: (f: DriveFile) => void;
  onPreviewFile: (f: DriveFile) => void;
  onAction: (f: DriveFile, kind: ActionKind) => void;
  onFileSelected?: (f: DriveFile) => void;
}) {
  return (
    <div className="grid grid-cols-2 gap-3 p-3 sm:grid-cols-3 lg:grid-cols-4">
      {files.map((f) => (
        <GridCard
          key={f.id}
          file={f}
          actions={actions}
          onOpenFolder={onOpenFolder}
          onPreviewFile={onPreviewFile}
          onAction={onAction}
          onFileSelected={onFileSelected}
        />
      ))}
    </div>
  );
}

function GridCard({
  file,
  actions,
  onOpenFolder,
  onPreviewFile,
  onAction,
  onFileSelected
}: {
  file: DriveFile;
  actions: Required<DriveActions>;
  onOpenFolder: (f: DriveFile) => void;
  onPreviewFile: (f: DriveFile) => void;
  onAction: (f: DriveFile, kind: ActionKind) => void;
  onFileSelected?: (f: DriveFile) => void;
}) {
  const folder = isFolder(file);
  return (
    <div
      role="button"
      tabIndex={0}
      onClick={() => {
        if (folder) onOpenFolder(file);
        else {
          onFileSelected?.(file);
          onPreviewFile(file);
        }
      }}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          if (folder) onOpenFolder(file);
          else {
            onFileSelected?.(file);
            onPreviewFile(file);
          }
        }
      }}
      onContextMenu={(e) => {
        e.preventDefault();
        // Pas de vrai menu contextuel positionné — on ouvre le menu actions
        // standard de la card via le bouton « ... ».
      }}
      className="group relative flex h-32 cursor-pointer flex-col justify-between overflow-hidden rounded-xl border border-brand-800 bg-brand-950 p-2 text-left transition hover:border-accent-500/50 hover:shadow-lg focus:border-accent-500 focus:outline-none"
    >
      <div className="flex h-16 items-center justify-center overflow-hidden rounded-lg bg-brand-900">
        {file.thumbnail_link ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={file.thumbnail_link}
            alt=""
            className="h-full w-full object-cover"
            onError={(e) => {
              (e.currentTarget as HTMLImageElement).style.display = "none";
            }}
          />
        ) : (
          <FileTypeIcon file={file} className="h-8 w-8" />
        )}
      </div>
      <div className="mt-1 min-w-0">
        <p
          className="truncate text-xs font-semibold text-white"
          title={file.name}
        >
          {file.name}
        </p>
        <p className="truncate text-[10px] text-white/40">
          {formatDate(file.modified_time)}
        </p>
      </div>

      <ItemActionsMenu
        file={file}
        actions={actions}
        onAction={onAction}
        className="absolute right-1 top-1 opacity-0 transition group-hover:opacity-100"
      />
    </div>
  );
}

function ListView({
  files,
  actions,
  sortField,
  sortDir,
  onToggleSort,
  onOpenFolder,
  onPreviewFile,
  onAction,
  onFileSelected
}: {
  files: DriveFile[];
  actions: Required<DriveActions>;
  sortField: SortField;
  sortDir: SortDir;
  onToggleSort: (f: SortField) => void;
  onOpenFolder: (f: DriveFile) => void;
  onPreviewFile: (f: DriveFile) => void;
  onAction: (f: DriveFile, kind: ActionKind) => void;
  onFileSelected?: (f: DriveFile) => void;
}) {
  function SortArrow({ field }: { field: SortField }) {
    if (sortField !== field) return null;
    return sortDir === "asc" ? (
      <ArrowUpAZ className="h-3 w-3" />
    ) : (
      <ArrowDownAZ className="h-3 w-3" />
    );
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[36rem] text-left text-xs">
        <thead className="border-b border-brand-800 text-[10px] uppercase tracking-wider text-white/40">
          <tr>
            <th className="px-3 py-2 font-semibold">
              <button
                type="button"
                onClick={() => onToggleSort("name")}
                className="inline-flex items-center gap-1 hover:text-white"
              >
                Nom <SortArrow field="name" />
              </button>
            </th>
            <th className="hidden px-3 py-2 font-semibold sm:table-cell">
              Type
            </th>
            <th className="px-3 py-2 font-semibold">
              <button
                type="button"
                onClick={() => onToggleSort("modified_time")}
                className="inline-flex items-center gap-1 hover:text-white"
              >
                Modifié <SortArrow field="modified_time" />
              </button>
            </th>
            <th className="hidden px-3 py-2 font-semibold sm:table-cell">
              <button
                type="button"
                onClick={() => onToggleSort("size")}
                className="inline-flex items-center gap-1 hover:text-white"
              >
                Taille <SortArrow field="size" />
              </button>
            </th>
            <th className="px-3 py-2 text-right font-semibold">Actions</th>
          </tr>
        </thead>
        <tbody>
          {files.map((f) => {
            const folder = isFolder(f);
            return (
              <tr
                key={f.id}
                onClick={() => {
                  if (folder) onOpenFolder(f);
                  else {
                    onFileSelected?.(f);
                    onPreviewFile(f);
                  }
                }}
                className="cursor-pointer border-b border-brand-800/60 text-white/80 hover:bg-white/5"
              >
                <td className="max-w-[18rem] px-3 py-2">
                  <div className="flex items-center gap-2 truncate">
                    <FileTypeIcon file={f} className="h-4 w-4 shrink-0" />
                    <span className="truncate" title={f.name}>
                      {f.name}
                    </span>
                  </div>
                </td>
                <td className="hidden px-3 py-2 text-white/50 sm:table-cell">
                  {shortMimeLabel(f.mime_type)}
                </td>
                <td className="px-3 py-2 text-white/50">
                  {formatDate(f.modified_time)}
                </td>
                <td className="hidden px-3 py-2 text-white/50 sm:table-cell">
                  {folder ? "—" : formatBytes(f.size)}
                </td>
                <td
                  className="px-3 py-2 text-right"
                  onClick={(e) => e.stopPropagation()}
                >
                  <ItemActionsMenu
                    file={f}
                    actions={actions}
                    onAction={onAction}
                  />
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Menu d'actions par item (... / clic droit)
// ---------------------------------------------------------------------------

function ItemActionsMenu({
  file,
  actions,
  onAction,
  className = ""
}: {
  file: DriveFile;
  actions: Required<DriveActions>;
  onAction: (f: DriveFile, kind: ActionKind) => void;
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  const folder = isFolder(file);
  return (
    <div className={`relative inline-block ${className}`}>
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation();
          setOpen((v) => !v);
        }}
        className="rounded-md p-1 text-white/60 hover:bg-white/10 hover:text-white"
        aria-label="Actions"
      >
        <MoreVertical className="h-4 w-4" />
      </button>
      {open ? (
        <>
          <button
            type="button"
            aria-hidden="true"
            tabIndex={-1}
            onClick={(e) => {
              e.stopPropagation();
              setOpen(false);
            }}
            className="fixed inset-0 z-30 cursor-default"
          />
          <div className="absolute right-0 z-40 mt-1 w-52 overflow-hidden rounded-lg border border-brand-800 bg-brand-950 text-xs shadow-2xl">
            <MenuItem
              icon={folder ? FolderOpen : Eye}
              label={folder ? "Ouvrir" : "Aperçu"}
              onClick={() => {
                setOpen(false);
                onAction(file, "open");
              }}
            />
            {!folder ? (
              <MenuItem
                icon={Eye}
                label="Aperçu (modal)"
                onClick={() => {
                  setOpen(false);
                  onAction(file, "preview");
                }}
              />
            ) : null}
            {!folder ? (
              <MenuItem
                icon={Download}
                label="Télécharger"
                onClick={() => {
                  setOpen(false);
                  onAction(file, "download");
                }}
              />
            ) : null}
            {actions.rename ? (
              <MenuItem
                icon={Pencil}
                label="Renommer"
                onClick={() => {
                  setOpen(false);
                  onAction(file, "rename");
                }}
              />
            ) : null}
            {actions.move ? (
              <MenuItem
                icon={Move}
                label="Déplacer…"
                onClick={() => {
                  setOpen(false);
                  onAction(file, "move");
                }}
              />
            ) : null}
            {actions.share ? (
              <MenuItem
                icon={Share2}
                label="Partager…"
                onClick={() => {
                  setOpen(false);
                  onAction(file, "share");
                }}
              />
            ) : null}
            {actions.delete ? (
              <>
                <MenuItem
                  icon={Trash2}
                  label="Supprimer (corbeille)"
                  danger
                  onClick={() => {
                    setOpen(false);
                    onAction(file, "delete");
                  }}
                />
                <MenuItem
                  icon={Trash2}
                  label="Supprimer définitivement"
                  danger
                  small
                  onClick={() => {
                    setOpen(false);
                    onAction(file, "deletePermanent");
                  }}
                />
              </>
            ) : null}
          </div>
        </>
      ) : null}
    </div>
  );
}

function MenuItem({
  icon: Icon,
  label,
  onClick,
  danger,
  small
}: {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  onClick: () => void;
  danger?: boolean;
  small?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`flex w-full items-center gap-2 border-b border-brand-800 px-3 py-2 text-left last:border-b-0 hover:bg-white/5 ${
        danger ? "text-rose-300" : "text-white/80"
      } ${small ? "text-[11px] opacity-80" : ""}`}
    >
      <Icon className="h-3.5 w-3.5" />
      {label}
    </button>
  );
}

// ---------------------------------------------------------------------------
// Modals action
// ---------------------------------------------------------------------------

function ModalShell({
  title,
  onCancel,
  children,
  size = "md"
}: {
  title: string;
  onCancel: () => void;
  children: ReactNode;
  size?: "md" | "lg" | "xl";
}) {
  const widthClass =
    size === "xl" ? "max-w-4xl" : size === "lg" ? "max-w-2xl" : "max-w-md";
  return (
    <div
      className="fixed inset-0 z-[1000] flex items-end justify-center bg-black/60 px-2 py-4 sm:items-center"
      onClick={onCancel}
    >
      <div
        className={`w-full ${widthClass} rounded-2xl border border-brand-800 bg-brand-900 shadow-2xl`}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-brand-800 p-4">
          <h2 className="text-sm font-bold text-white">{title}</h2>
          <button
            type="button"
            onClick={onCancel}
            aria-label="Fermer"
            className="rounded-md p-1 text-white/60 hover:bg-white/5 hover:text-white"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}

function RenameModal({
  file,
  onCancel,
  onSubmit
}: {
  file: DriveFile;
  onCancel: () => void;
  onSubmit: (name: string) => Promise<void> | void;
}) {
  const [name, setName] = useState(file.name);
  const [saving, setSaving] = useState(false);
  return (
    <ModalShell title="Renommer" onCancel={onCancel}>
      <form
        onSubmit={async (e) => {
          e.preventDefault();
          if (!name.trim() || name.trim() === file.name) {
            onCancel();
            return;
          }
          setSaving(true);
          await onSubmit(name.trim());
        }}
        className="grid gap-3 p-4"
      >
        <input
          type="text"
          value={name}
          autoFocus
          onChange={(e) => setName(e.target.value)}
          className="w-full rounded-lg border border-brand-800 bg-brand-950 px-3 py-2 text-sm text-white focus:border-accent-500 focus:outline-none"
        />
        <div className="flex items-center justify-end gap-2 pt-1">
          <button
            type="button"
            onClick={onCancel}
            className="rounded-lg border border-white/15 px-3 py-1.5 text-xs text-white/70 hover:bg-white/5"
          >
            Annuler
          </button>
          <button
            type="submit"
            disabled={saving || !name.trim()}
            className="inline-flex items-center gap-1 rounded-lg bg-accent-500 px-3 py-1.5 text-xs font-semibold text-white hover:bg-accent-600 disabled:opacity-50"
          >
            {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
            Renommer
          </button>
        </div>
      </form>
    </ModalShell>
  );
}

function MoveModal({
  file,
  currentFolderId,
  onCancel,
  onSubmit
}: {
  file: DriveFile;
  currentFolderId: string;
  onCancel: () => void;
  onSubmit: (newParentId: string) => Promise<void> | void;
}) {
  const [target, setTarget] = useState("");
  const [saving, setSaving] = useState(false);
  return (
    <ModalShell title={`Déplacer « ${file.name} »`} onCancel={onCancel}>
      <form
        onSubmit={async (e) => {
          e.preventDefault();
          const t = target.trim();
          if (!t || t === currentFolderId) {
            onCancel();
            return;
          }
          setSaving(true);
          await onSubmit(t);
        }}
        className="grid gap-3 p-4"
      >
        <p className="text-xs text-white/60">
          Colle l&apos;ID du dossier Drive de destination. Le picker visuel
          arrive en Phase 4.
        </p>
        <input
          type="text"
          value={target}
          autoFocus
          onChange={(e) => setTarget(e.target.value)}
          placeholder="1abc...xyz"
          className="w-full rounded-lg border border-brand-800 bg-brand-950 px-3 py-2 font-mono text-xs text-white focus:border-accent-500 focus:outline-none"
        />
        <div className="flex items-center justify-end gap-2 pt-1">
          <button
            type="button"
            onClick={onCancel}
            className="rounded-lg border border-white/15 px-3 py-1.5 text-xs text-white/70 hover:bg-white/5"
          >
            Annuler
          </button>
          <button
            type="submit"
            disabled={saving || !target.trim()}
            className="inline-flex items-center gap-1 rounded-lg bg-accent-500 px-3 py-1.5 text-xs font-semibold text-white hover:bg-accent-600 disabled:opacity-50"
          >
            {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
            Déplacer
          </button>
        </div>
      </form>
    </ModalShell>
  );
}

function ShareModal({
  file,
  onCancel,
  onSubmit
}: {
  file: DriveFile;
  onCancel: () => void;
  onSubmit: (payload: {
    email: string;
    role: string;
    send_notification: boolean;
    message: string;
  }) => Promise<void> | void;
}) {
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<"reader" | "commenter" | "writer">("reader");
  const [notify, setNotify] = useState(true);
  const [message, setMessage] = useState("");
  const [saving, setSaving] = useState(false);
  return (
    <ModalShell title={`Partager « ${file.name} »`} onCancel={onCancel}>
      <form
        onSubmit={async (e) => {
          e.preventDefault();
          if (!email.trim()) return;
          setSaving(true);
          await onSubmit({
            email: email.trim(),
            role,
            send_notification: notify,
            message
          });
        }}
        className="grid gap-3 p-4 text-xs"
      >
        <label className="grid gap-1">
          <span className="text-white/60">Email du destinataire</span>
          <input
            type="email"
            required
            autoFocus
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="prenom.nom@exemple.com"
            className="w-full rounded-lg border border-brand-800 bg-brand-950 px-3 py-2 text-white focus:border-accent-500 focus:outline-none"
          />
        </label>
        <label className="grid gap-1">
          <span className="text-white/60">Rôle</span>
          <select
            value={role}
            onChange={(e) =>
              setRole(e.target.value as "reader" | "commenter" | "writer")
            }
            className="w-full rounded-lg border border-brand-800 bg-brand-950 px-3 py-2 text-white focus:border-accent-500 focus:outline-none"
          >
            <option value="reader">Lecteur</option>
            <option value="commenter">Commentateur</option>
            <option value="writer">Éditeur</option>
          </select>
        </label>
        <label className="flex items-center gap-2 text-white/70">
          <input
            type="checkbox"
            checked={notify}
            onChange={(e) => setNotify(e.target.checked)}
            className="rounded border-brand-800 bg-brand-950"
          />
          Envoyer une notification par courriel
        </label>
        {notify ? (
          <label className="grid gap-1">
            <span className="text-white/60">Message (optionnel)</span>
            <textarea
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              rows={3}
              className="w-full rounded-lg border border-brand-800 bg-brand-950 px-3 py-2 text-white focus:border-accent-500 focus:outline-none"
            />
          </label>
        ) : null}
        <div className="flex items-center justify-end gap-2 pt-1">
          <button
            type="button"
            onClick={onCancel}
            className="rounded-lg border border-white/15 px-3 py-1.5 text-white/70 hover:bg-white/5"
          >
            Annuler
          </button>
          <button
            type="submit"
            disabled={saving || !email.trim()}
            className="inline-flex items-center gap-1 rounded-lg bg-accent-500 px-3 py-1.5 font-semibold text-white hover:bg-accent-600 disabled:opacity-50"
          >
            {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
            Partager
          </button>
        </div>
      </form>
    </ModalShell>
  );
}

function CreateFolderModal({
  onCancel,
  onSubmit
}: {
  onCancel: () => void;
  onSubmit: (name: string) => Promise<void> | void;
}) {
  const [name, setName] = useState("");
  const [saving, setSaving] = useState(false);
  return (
    <ModalShell title="Nouveau dossier" onCancel={onCancel}>
      <form
        onSubmit={async (e) => {
          e.preventDefault();
          if (!name.trim()) return;
          setSaving(true);
          await onSubmit(name.trim());
        }}
        className="grid gap-3 p-4"
      >
        <input
          type="text"
          value={name}
          autoFocus
          onChange={(e) => setName(e.target.value)}
          placeholder="Nom du dossier"
          className="w-full rounded-lg border border-brand-800 bg-brand-950 px-3 py-2 text-sm text-white focus:border-accent-500 focus:outline-none"
        />
        <div className="flex items-center justify-end gap-2 pt-1">
          <button
            type="button"
            onClick={onCancel}
            className="rounded-lg border border-white/15 px-3 py-1.5 text-xs text-white/70 hover:bg-white/5"
          >
            Annuler
          </button>
          <button
            type="submit"
            disabled={saving || !name.trim()}
            className="inline-flex items-center gap-1 rounded-lg bg-accent-500 px-3 py-1.5 text-xs font-semibold text-white hover:bg-accent-600 disabled:opacity-50"
          >
            {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
            Créer
          </button>
        </div>
      </form>
    </ModalShell>
  );
}

// ---------------------------------------------------------------------------
// Modal preview
// ---------------------------------------------------------------------------

function PreviewModal({
  file,
  previewUrl,
  fullscreen,
  onToggleFullscreen,
  onDownload,
  onClose
}: {
  file: DriveFile;
  previewUrl: string | null;
  fullscreen: boolean;
  onToggleFullscreen: () => void;
  onDownload: () => void;
  onClose: () => void;
}) {
  const inline = canPreviewInline(file.mime_type);
  const office = isOfficeMime(file.mime_type);
  return (
    <div
      className="fixed inset-0 z-[1000] flex items-center justify-center bg-black/80 p-2"
      onClick={onClose}
    >
      <div
        className={`flex flex-col overflow-hidden rounded-2xl border border-brand-800 bg-brand-950 shadow-2xl ${
          fullscreen ? "h-full w-full" : "h-[90vh] w-full max-w-5xl"
        }`}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-brand-800 px-3 py-2">
          <div className="flex min-w-0 items-center gap-2">
            <FileTypeIcon file={file} className="h-4 w-4 shrink-0" />
            <span className="truncate text-sm font-semibold text-white">
              {file.name}
            </span>
          </div>
          <div className="flex shrink-0 items-center gap-1">
            <button
              type="button"
              onClick={onDownload}
              className="rounded-md p-1.5 text-white/60 hover:bg-white/5 hover:text-white"
              title="Télécharger"
              aria-label="Télécharger"
            >
              <Download className="h-4 w-4" />
            </button>
            <button
              type="button"
              onClick={onToggleFullscreen}
              className="rounded-md p-1.5 text-white/60 hover:bg-white/5 hover:text-white"
              title={fullscreen ? "Réduire" : "Plein écran"}
              aria-label={fullscreen ? "Réduire" : "Plein écran"}
            >
              {fullscreen ? (
                <Minimize2 className="h-4 w-4" />
              ) : (
                <Maximize2 className="h-4 w-4" />
              )}
            </button>
            <button
              type="button"
              onClick={onClose}
              className="rounded-md p-1.5 text-white/60 hover:bg-white/5 hover:text-white"
              title="Fermer"
              aria-label="Fermer"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        </div>
        <div className="flex flex-1 items-center justify-center overflow-hidden bg-black/40">
          {office ? (
            <div className="flex flex-col items-center gap-3 p-8 text-center text-sm text-white/70">
              <FileTypeIcon file={file} className="h-12 w-12" />
              <p className="max-w-md">
                Ce type de fichier ne peut pas être prévisualisé en ligne.
                Télécharge-le pour l&apos;ouvrir.
              </p>
              <button
                type="button"
                onClick={onDownload}
                className="inline-flex items-center gap-1.5 rounded-lg bg-accent-500 px-3 py-1.5 text-xs font-semibold text-white hover:bg-accent-600"
              >
                <Download className="h-3.5 w-3.5" /> Télécharger
              </button>
            </div>
          ) : !inline ? (
            <div className="flex flex-col items-center gap-3 p-8 text-center text-sm text-white/70">
              <FileTypeIcon file={file} className="h-12 w-12" />
              <p>Aperçu non disponible pour ce type de fichier.</p>
              <button
                type="button"
                onClick={onDownload}
                className="inline-flex items-center gap-1.5 rounded-lg bg-accent-500 px-3 py-1.5 text-xs font-semibold text-white hover:bg-accent-600"
              >
                <Download className="h-3.5 w-3.5" /> Télécharger
              </button>
            </div>
          ) : previewUrl ? (
            <iframe
              src={previewUrl}
              title={file.name}
              className="h-full w-full border-0"
              allow="autoplay"
            />
          ) : (
            <Loader2 className="h-6 w-6 animate-spin text-accent-500" />
          )}
        </div>
      </div>
    </div>
  );
}

export default DriveFolderExplorer;
