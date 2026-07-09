"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  Bell,
  ChevronDown,
  ChevronRight,
  FileText,
  GripVertical,
  Loader2,
  Mail,
  Pencil,
  Phone,
  Plus,
  Trash2,
  X
} from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { AddressInput } from "@/components/address-input";
import { useAppLayout } from "../layout";
import { authedFetch } from "@/lib/auth";
import { useConfirm } from "@/components/confirm-dialog";
import { Link, useRouter } from "@/i18n/navigation";
import { formatPhone } from "@/lib/utils";

type Prospect = {
  id: number;
  name: string;
  email: string;
  phone: string | null;
  address: string | null;
  project_type: string;
  budget_range: string | null;
  message: string;
  locale: string;
  source: string | null;
  status: string;
  kanban_column: string | null;
  rappel_at: string | null;
  created_at: string;
};

/** ISO (UTC) → valeur d'un <input type="datetime-local"> en heure
 *  locale, ou "" si vide. */
function toLocalInput(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  const p = (n: number) => String(n).padStart(2, "0");
  return (
    `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}` +
    `T${p(d.getHours())}:${p(d.getMinutes())}`
  );
}

function fmtRappel(iso: string): string {
  return new Date(iso).toLocaleString("fr-CA", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit"
  });
}

type Column = { id: string; label: string; dot: string; custom?: boolean };

// Default columns mirror the built-in status enum. Users can add / rename
// extra columns — those are stored in localStorage + on the prospect's
// `kanban_column` field so they persist across sessions.
const DEFAULT_COLUMNS: Column[] = [
  { id: "new", label: "Nouveaux", dot: "bg-emerald-400" },
  { id: "contacted", label: "Suivi à faire", dot: "bg-amber-400" },
  { id: "rdv_prevu", label: "Rendez-vous prévu", dot: "bg-cyan-400" },
  { id: "qualified", label: "Soumission en préparation", dot: "bg-fuchsia-400" },
  { id: "quoted", label: "Soumission envoyée", dot: "bg-blue-400" },
  { id: "won", label: "Acceptée", dot: "bg-green-500" },
  { id: "lost", label: "Refusée", dot: "bg-rose-500" }
];

const DOTS = [
  "bg-emerald-400",
  "bg-amber-400",
  "bg-blue-400",
  "bg-fuchsia-400",
  "bg-sky-400",
  "bg-rose-400",
  "bg-teal-400"
];

/** Convertit un texte d'erreur Pydantic / FastAPI en message court
 *  français pour l'UI. Si on ne reconnaît pas le contenu, on tombe
 *  sur un message générique avec le code HTTP. */
function translateBackendError(raw: string, status: number): string {
  const lower = raw.toLowerCase();
  if (lower.includes("not a valid email") || lower.includes("email_address")) {
    return "Le courriel n'est pas valide.";
  }
  if (lower.includes("at least 10 characters")) {
    return "Le message doit faire au moins 10 caractères.";
  }
  if (lower.includes("at least") && lower.includes("character")) {
    return "Un champ obligatoire est trop court.";
  }
  if (lower.includes("field required") || lower.includes("missing")) {
    return "Un champ obligatoire est manquant.";
  }
  if (status === 401 || status === 403) {
    return "Action non autorisée. Vérifie ta connexion.";
  }
  return `Création échouée (HTTP ${status}).`;
}

const PROJECT_LABEL: Record<string, string> = {
  salle_bain: "Salle de bain",
  cuisine: "Cuisine",
  multilogement: "Multilogement",
  renovation_complete: "Rénovation complète",
  autre: "Autre"
};

const CUSTOM_COLS_KEY = "hsi_crm_custom_columns_v1";

function loadCustomColumns(): Column[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(CUSTOM_COLS_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as Column[];
    return parsed.map((c, i) => ({
      ...c,
      custom: true,
      dot: c.dot || DOTS[i % DOTS.length]
    }));
  } catch {
    return [];
  }
}

const COLLAPSED_COLS_KEY = "hsi_crm_collapsed_columns_v1";
// Colonnes repliées par défaut au premier chargement : Acceptée et
// Refusée prennent de la place pour des leads "terminés" qu'on
// consulte rarement.
const DEFAULT_COLLAPSED = ["won", "lost"];

function loadCollapsedColumns(): Set<string> {
  if (typeof window === "undefined") return new Set(DEFAULT_COLLAPSED);
  try {
    const raw = window.localStorage.getItem(COLLAPSED_COLS_KEY);
    if (raw === null) return new Set(DEFAULT_COLLAPSED);
    const parsed = JSON.parse(raw) as string[];
    return new Set(Array.isArray(parsed) ? parsed : []);
  } catch {
    return new Set(DEFAULT_COLLAPSED);
  }
}

function saveCollapsedColumns(ids: Set<string>) {
  try {
    window.localStorage.setItem(
      COLLAPSED_COLS_KEY,
      JSON.stringify(Array.from(ids))
    );
  } catch {
    /* ignore */
  }
}

export default function CrmKanbanPage() {
  const confirm = useConfirm();
  const { onOpenSidebar } = useAppLayout();
  const router = useRouter();
  const [items, setItems] = useState<Prospect[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [dragging, setDragging] = useState<number | null>(null);
  const [hoverCol, setHoverCol] = useState<string | null>(null);
  const [customColumns, setCustomColumns] = useState<Column[]>([]);
  const [collapsedCols, setCollapsedCols] = useState<Set<string>>(
    () => new Set(DEFAULT_COLLAPSED)
  );
  const [createOpen, setCreateOpen] = useState(false);
  // Horloge rafraîchie chaque minute : permet au badge « à rappeler »
  // d'apparaître au moment du rappel sans recharger la page.
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 60_000);
    return () => clearInterval(t);
  }, []);

  useEffect(() => {
    setCollapsedCols(loadCollapsedColumns());
    let cancelled = false;
    (async () => {
      try {
        const res = await authedFetch("/api/v1/crm/columns");
        let server: Column[] = res.ok
          ? (
              (await res.json()) as Array<{
                key: string;
                label: string;
                dot: string | null;
              }>
            ).map((c) => ({
              id: c.key,
              label: c.label,
              dot: c.dot || "bg-sky-400",
              custom: true
            }))
          : [];
        // Migration : pousse vers le serveur les colonnes encore
        // seulement présentes dans le localStorage (ancien stockage),
        // pour les rendre disponibles sur tous les appareils.
        const local = loadCustomColumns();
        const missing = local.filter(
          (l) => !server.some((s) => s.id === l.id)
        );
        for (let i = 0; i < missing.length; i++) {
          const m = missing[i];
          try {
            await authedFetch("/api/v1/crm/columns", {
              method: "POST",
              body: JSON.stringify({
                key: m.id,
                label: m.label,
                dot: m.dot,
                position: server.length + i
              })
            });
          } catch {
            /* ignore */
          }
        }
        if (missing.length) server = [...server, ...missing];
        if (!cancelled) setCustomColumns(server);
      } catch {
        if (!cancelled) setCustomColumns(loadCustomColumns());
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  function toggleColumnCollapsed(colId: string) {
    setCollapsedCols((prev) => {
      const next = new Set(prev);
      if (next.has(colId)) next.delete(colId);
      else next.add(colId);
      saveCollapsedColumns(next);
      return next;
    });
  }

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const res = await authedFetch("/api/v1/contact?limit=500");
        if (!res.ok) throw new Error(`http_${res.status}`);
        const data = (await res.json()) as Prospect[];
        if (!cancelled) setItems(data);
      } catch {
        if (!cancelled) setError("Impossible de charger les prospects.");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, []);

  const columns = useMemo(
    () => [...DEFAULT_COLUMNS, ...customColumns],
    [customColumns]
  );

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return items;
    return items.filter(
      (p) =>
        p.name.toLowerCase().includes(q) ||
        p.email.toLowerCase().includes(q) ||
        (p.phone || "").includes(q)
    );
  }, [items, search]);

  const byColumn = useMemo(() => {
    const map: Record<string, Prospect[]> = Object.fromEntries(
      columns.map((c) => [c.id, [] as Prospect[]])
    );
    for (const p of filtered) {
      // Prefer the custom kanban_column when it matches one of the
      // user-defined columns. Otherwise bucket by `status`.
      const col =
        p.kanban_column &&
        columns.find((c) => c.id === p.kanban_column)
          ? p.kanban_column
          : columns.find((c) => c.id === p.status)
          ? p.status
          : "new";
      map[col].push(p);
    }
    return map;
  }, [filtered, columns]);

  async function moveProspect(id: number, target: Column) {
    const prev = items;
    setItems((xs) =>
      xs.map((x) =>
        x.id === id
          ? {
              ...x,
              status: target.custom ? x.status : target.id,
              kanban_column: target.custom ? target.id : null
            }
          : x
      )
    );
    try {
      const body: Record<string, string | null> = target.custom
        ? { kanban_column: target.id }
        : { status: target.id, kanban_column: null };
      const res = await authedFetch(`/api/v1/contact/${id}`, {
        method: "PATCH",
        body: JSON.stringify(body)
      });
      if (!res.ok) throw new Error();
    } catch {
      setItems(prev);
      setError("Mise à jour échouée.");
    }
  }

  async function setRappel(id: number, value: string | null) {
    setItems((xs) =>
      xs.map((x) => (x.id === id ? { ...x, rappel_at: value } : x))
    );
    try {
      const res = await authedFetch(`/api/v1/contact/${id}`, {
        method: "PATCH",
        body: JSON.stringify({ rappel_at: value })
      });
      if (!res.ok) throw new Error();
    } catch {
      setError("Mise à jour du rappel échouée.");
    }
  }

  async function deleteProspect(id: number, name: string) {
    if (!(await confirm(`Supprimer définitivement le prospect « ${name} » ?`))) return;
    const prev = items;
    setItems((xs) => xs.filter((x) => x.id !== id));
    try {
      const res = await authedFetch(`/api/v1/contact/${id}`, {
        method: "DELETE"
      });
      if (!res.ok) throw new Error();
    } catch {
      setItems(prev);
      setError("Suppression échouée.");
    }
  }

  async function addCustomColumn() {
    const label = prompt("Nom de la nouvelle colonne :");
    if (!label || !label.trim()) return;
    const id = `custom_${Date.now()}`;
    const dot = DOTS[customColumns.length % DOTS.length];
    const position = customColumns.length;
    setCustomColumns((cur) => [
      ...cur,
      { id, label: label.trim(), dot, custom: true }
    ]);
    try {
      const res = await authedFetch("/api/v1/crm/columns", {
        method: "POST",
        body: JSON.stringify({ key: id, label: label.trim(), dot, position })
      });
      if (!res.ok) throw new Error();
    } catch {
      setError("Création de la colonne échouée.");
    }
  }

  async function renameCustomColumn(colId: string) {
    const col = customColumns.find((c) => c.id === colId);
    if (!col) return;
    const label = prompt("Nouveau nom :", col.label);
    if (!label || !label.trim() || label === col.label) return;
    setCustomColumns((cur) =>
      cur.map((c) => (c.id === colId ? { ...c, label: label.trim() } : c))
    );
    try {
      const res = await authedFetch(`/api/v1/crm/columns/${colId}`, {
        method: "PATCH",
        body: JSON.stringify({ label: label.trim() })
      });
      if (!res.ok) throw new Error();
    } catch {
      setError("Renommage de la colonne échoué.");
    }
  }

  async function removeCustomColumn(colId: string) {
    const col = customColumns.find((c) => c.id === colId);
    if (!col) return;
    const affected = items.filter((p) => p.kanban_column === colId);
    if (
      !confirm(
        `Supprimer la colonne « ${col.label} » ? Les ${affected.length} prospect${
          affected.length > 1 ? "s" : ""
        } qu'elle contient retournent dans la colonne par statut.`
      )
    )
      return;
    setCustomColumns((cur) => cur.filter((c) => c.id !== colId));
    try {
      await authedFetch(`/api/v1/crm/columns/${colId}`, { method: "DELETE" });
    } catch {
      /* ignore */
    }
    // Clear kanban_column on affected prospects in the background.
    for (const p of affected) {
      try {
        await authedFetch(`/api/v1/contact/${p.id}`, {
          method: "PATCH",
          body: JSON.stringify({ kanban_column: null })
        });
      } catch {
        /* ignore */
      }
    }
    setItems((xs) =>
      xs.map((x) =>
        x.kanban_column === colId ? { ...x, kanban_column: null } : x
      )
    );
  }

  async function startSoumission(p: Prospect) {
    router.push(
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      (`/app/soumissions/new?contact_request_id=${p.id}` as any)
    );
  }

  function onDragStart(id: number) {
    setDragging(id);
  }
  function onDragEnd() {
    setDragging(null);
    setHoverCol(null);
  }
  function onDropToColumn(col: Column) {
    if (dragging == null) return;
    const item = items.find((p) => p.id === dragging);
    if (item) {
      const currentCol = item.kanban_column || item.status;
      if (currentCol !== col.id) moveProspect(dragging, col);
    }
    setDragging(null);
    setHoverCol(null);
  }

  // ── Drag tactile (mobile) ───────────────────────────────────────────
  // Le HTML5 drag-and-drop ne fonctionne pas au doigt : on ajoute un
  // glisser basé sur les Pointer Events, déclenché depuis la poignée
  // (grip) de la carte. On retrouve la colonne sous le doigt via
  // elementFromPoint(data-col-id).
  function columnIdAtPoint(x: number, y: number): string | null {
    if (typeof document === "undefined") return null;
    const el = document.elementFromPoint(x, y);
    const colEl = el?.closest("[data-col-id]");
    return colEl?.getAttribute("data-col-id") || null;
  }
  function onTouchDragStart(id: number) {
    setDragging(id);
  }
  function onTouchDragMove(x: number, y: number) {
    setHoverCol(columnIdAtPoint(x, y));
  }
  function onTouchDragEnd(id: number, x: number, y: number) {
    const cid = columnIdAtPoint(x, y);
    const col = columns.find((c) => c.id === cid);
    if (col) {
      const item = items.find((p) => p.id === id);
      const currentCol = item ? item.kanban_column || item.status : null;
      if (item && currentCol !== col.id) moveProspect(id, col);
    }
    setDragging(null);
    setHoverCol(null);
  }

  return (
    <>
      <AppTopbar
        breadcrumbs={[
          { label: "Construction", href: "/app" },
          { label: "CRM / Prospects" }
        ]}
        onOpenSidebar={onOpenSidebar}
        onSearch={setSearch}
        searchPlaceholder="Rechercher un prospect…"
        rightSlot={
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => void addCustomColumn()}
              className="btn-secondary text-sm"
              title="Ajouter une colonne personnalisée (ex. « À rappeler »)"
            >
              <Plus className="mr-1.5 h-4 w-4" /> Colonne
            </button>
            <button
              type="button"
              onClick={() => setCreateOpen(true)}
              className="btn-accent text-sm"
            >
              <Plus className="mr-1.5 h-4 w-4" /> Créer un prospect
            </button>
          </div>
        }
      />

      <div className="p-4 lg:p-6">
        {error ? (
          <p className="mb-4 rounded-lg border border-rose-500/40 bg-rose-500/10 px-4 py-2 text-sm text-rose-300">
            {error}
          </p>
        ) : null}

        {loading ? (
          <div className="flex min-h-[50vh] items-center justify-center">
            <Loader2 className="h-6 w-6 animate-spin text-accent-500" />
          </div>
        ) : (
          <div className="flex gap-4 overflow-x-auto pb-4">
            {columns.map((col) => {
              const cards = byColumn[col.id] || [];
              const isHover = hoverCol === col.id;
              const collapsed = collapsedCols.has(col.id);
              return (
                <div
                  key={col.id}
                  data-col-id={col.id}
                  onDragOver={(e) => {
                    e.preventDefault();
                    setHoverCol(col.id);
                  }}
                  onDragLeave={() =>
                    setHoverCol((h) => (h === col.id ? null : h))
                  }
                  onDrop={() => onDropToColumn(col)}
                  className={`flex w-80 min-w-[320px] flex-shrink-0 flex-col rounded-xl border bg-brand-900/60 ${
                    isHover
                      ? "border-accent-500 bg-brand-900"
                      : "border-brand-800"
                  }`}
                >
                  <div className="flex items-center justify-between border-b border-brand-800 px-4 py-3">
                    <button
                      type="button"
                      onClick={() => toggleColumnCollapsed(col.id)}
                      className="flex flex-1 items-center gap-2 text-left"
                      title={
                        collapsed
                          ? "Cliquer pour déplier"
                          : "Cliquer pour replier"
                      }
                    >
                      {collapsed ? (
                        <ChevronRight className="h-3.5 w-3.5 text-white/50" />
                      ) : (
                        <ChevronDown className="h-3.5 w-3.5 text-white/50" />
                      )}
                      <span
                        className={`h-2 w-2 rounded-full ${col.dot}`}
                      />
                      <h2 className="text-sm font-semibold text-white">
                        {col.label}
                      </h2>
                    </button>
                    <div className="flex items-center gap-2">
                      <span className="badge badge-neutral">
                        {cards.length}
                      </span>
                      {col.custom ? (
                        <>
                          <button
                            type="button"
                            onClick={() => renameCustomColumn(col.id)}
                            className="btn-ghost btn-xs"
                            aria-label="Renommer la colonne"
                            title="Renommer la colonne"
                          >
                            <Pencil className="h-3.5 w-3.5" />
                          </button>
                          <button
                            type="button"
                            onClick={() => removeCustomColumn(col.id)}
                            className="btn-ghost btn-xs"
                            aria-label="Supprimer la colonne"
                            title="Supprimer la colonne"
                          >
                            <X className="h-3.5 w-3.5" />
                          </button>
                        </>
                      ) : null}
                    </div>
                  </div>

                  {collapsed ? null : (
                    <div className="flex-1 space-y-3 p-3">
                      {cards.length === 0 ? (
                        <p className="py-8 text-center text-xs text-white/40">
                          Aucun prospect
                        </p>
                      ) : (
                        cards.map((p) => (
                          <ProspectCard
                            key={p.id}
                            prospect={p}
                            now={now}
                            dragging={dragging === p.id}
                            onDragStart={() => onDragStart(p.id)}
                            onDragEnd={onDragEnd}
                            onTouchDragStart={() => onTouchDragStart(p.id)}
                            onTouchDragMove={onTouchDragMove}
                            onTouchDragEnd={(x, y) => onTouchDragEnd(p.id, x, y)}
                            onDelete={() => deleteProspect(p.id, p.name)}
                            onCreateSoumission={() => startSoumission(p)}
                            onSetRappel={(v) => setRappel(p.id, v)}
                          />
                        ))
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>

      {createOpen ? (
        <CreateProspectModal
          onClose={() => setCreateOpen(false)}
          onCreated={(p) => {
            setItems((xs) => [p, ...xs]);
            setCreateOpen(false);
          }}
        />
      ) : null}
    </>
  );
}

function ProspectCard({
  prospect: p,
  now,
  dragging,
  onDragStart,
  onDragEnd,
  onTouchDragStart,
  onTouchDragMove,
  onTouchDragEnd,
  onDelete,
  onCreateSoumission,
  onSetRappel
}: {
  prospect: Prospect;
  now: number;
  dragging: boolean;
  onDragStart: () => void;
  onDragEnd: () => void;
  onTouchDragStart: () => void;
  onTouchDragMove: (x: number, y: number) => void;
  onTouchDragEnd: (x: number, y: number) => void;
  onDelete: () => void;
  onCreateSoumission: () => void;
  onSetRappel: (value: string | null) => void;
}) {
  // Suivi du geste tactile sur la poignée (distingue tap vs glisser).
  const touch = useRef<{ x: number; y: number; moved: boolean } | null>(null);
  const [editRappel, setEditRappel] = useState(false);
  // Rappel « dû » = échéance atteinte/dépassée (comparée à `now`, qui
  // est rafraîchi chaque minute par le parent).
  const rappelDue =
    !!p.rappel_at && new Date(p.rappel_at).getTime() <= now;

  return (
    <div
      draggable
      onDragStart={onDragStart}
      onDragEnd={onDragEnd}
      className={`group relative cursor-grab rounded-lg border border-brand-800 bg-brand-950 p-3 transition hover:border-accent-500 active:cursor-grabbing ${
        dragging ? "opacity-40" : ""
      }`}
    >
      {/* Poignée de glissement — fonctionne au doigt (Pointer Events).
          touch-action:none pour que le glisser ne déclenche pas le scroll. */}
      <div
        className="absolute left-0 top-0 flex h-full w-7 cursor-grab touch-none items-start justify-center pt-3 text-white/30 active:cursor-grabbing"
        style={{ touchAction: "none" }}
        aria-label="Glisser pour déplacer"
        title="Glisser pour déplacer"
        onPointerDown={(e) => {
          if (e.pointerType === "mouse") return; // souris → DnD HTML5
          touch.current = { x: e.clientX, y: e.clientY, moved: false };
          (e.currentTarget as HTMLElement).setPointerCapture?.(e.pointerId);
        }}
        onPointerMove={(e) => {
          const t = touch.current;
          if (!t || e.pointerType === "mouse") return;
          const dist = Math.hypot(e.clientX - t.x, e.clientY - t.y);
          if (!t.moved && dist > 8) {
            t.moved = true;
            onTouchDragStart();
          }
          if (t.moved) {
            e.preventDefault();
            onTouchDragMove(e.clientX, e.clientY);
          }
        }}
        onPointerUp={(e) => {
          const t = touch.current;
          touch.current = null;
          if (!t || e.pointerType === "mouse") return;
          if (t.moved) onTouchDragEnd(e.clientX, e.clientY);
        }}
        onPointerCancel={() => {
          touch.current = null;
        }}
      >
        <GripVertical className="h-4 w-4" />
      </div>

      <div className="absolute right-2 top-2 flex items-center gap-1">
        <button
          type="button"
          onClick={(e) => {
            e.preventDefault();
            e.stopPropagation();
            setEditRappel((v) => !v);
          }}
          aria-label="Planifier un rappel"
          title="Planifier un rappel"
          className={`rounded-md p-1 transition ${
            p.rappel_at
              ? rappelDue
                ? "text-rose-400 hover:bg-rose-500/15"
                : "text-amber-400 hover:bg-amber-500/15"
              : "text-white/40 opacity-0 hover:bg-accent-500/15 group-hover:opacity-100"
          }`}
        >
          <Bell className="h-3.5 w-3.5" />
        </button>
        <button
          type="button"
          onClick={(e) => {
            e.preventDefault();
            e.stopPropagation();
            onCreateSoumission();
          }}
          aria-label="Créer une soumission"
          title="Créer une soumission"
          className="rounded-md p-1 text-accent-400 opacity-0 transition hover:bg-accent-500/15 group-hover:opacity-100"
        >
          <FileText className="h-3.5 w-3.5" />
        </button>
        <button
          type="button"
          onClick={(e) => {
            e.preventDefault();
            e.stopPropagation();
            onDelete();
          }}
          aria-label="Supprimer"
          className="rounded-md p-1 text-white/40 opacity-0 transition hover:bg-rose-500/15 hover:text-rose-400 group-hover:opacity-100"
        >
          <Trash2 className="h-3.5 w-3.5" />
        </button>
      </div>

      <Link
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        href={`/app/crm/${p.id}` as any}
        className="block pl-5 pr-12"
      >
        <p className="flex items-center gap-1.5 text-sm font-semibold text-white">
          {rappelDue ? (
            <span
              title="Rappel dû — action requise"
              className="inline-block h-2 w-2 flex-shrink-0 animate-pulse rounded-full bg-rose-500"
            />
          ) : null}
          <span className="truncate">{p.name}</span>
        </p>
        {p.phone ? (
          <p className="mt-1 flex items-center gap-1.5 text-xs text-white/60">
            <Phone className="h-3 w-3" />
            <span className="truncate">{formatPhone(p.phone)}</span>
          </p>
        ) : null}
        <p className="mt-1 flex items-center gap-1.5 text-xs text-white/60">
          <Mail className="h-3 w-3" />
          <span className="truncate">{p.email}</span>
        </p>
        <div className="mt-2 flex items-center justify-between">
          <span className="inline-flex rounded-md bg-accent-500/15 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-accent-500">
            {PROJECT_LABEL[p.project_type] || p.project_type}
          </span>
          <span className="text-[10px] text-white/40">
            {new Date(p.created_at).toLocaleDateString("fr-CA", {
              month: "short",
              day: "2-digit"
            })}
          </span>
        </div>
      </Link>

      {/* Rappel : éditeur (date/heure) ou indicateur. Hors du Link pour
          que le clic ne déclenche pas la navigation. */}
      {editRappel ? (
        <div className="mt-2 pl-5 pr-2" onClick={(e) => e.stopPropagation()}>
          <div className="flex items-center gap-2">
            <input
              type="datetime-local"
              defaultValue={toLocalInput(p.rappel_at)}
              onChange={(e) => {
                const v = e.target.value;
                onSetRappel(v ? new Date(v).toISOString() : null);
              }}
              className="w-full rounded-md border border-brand-800 bg-brand-950 px-2 py-1 text-xs text-white"
            />
            {p.rappel_at ? (
              <button
                type="button"
                onClick={() => {
                  onSetRappel(null);
                  setEditRappel(false);
                }}
                className="whitespace-nowrap text-[11px] text-white/50 hover:text-rose-300"
              >
                Effacer
              </button>
            ) : null}
          </div>
        </div>
      ) : p.rappel_at ? (
        <p
          className={`mt-2 flex items-center gap-1 pl-5 text-[11px] ${
            rappelDue ? "font-semibold text-rose-300" : "text-white/50"
          }`}
        >
          <Bell className="h-3 w-3" />
          {rappelDue ? "À rappeler" : "Rappel"} · {fmtRappel(p.rappel_at)}
        </p>
      ) : null}
    </div>
  );
}

function CreateProspectModal({
  onClose,
  onCreated
}: {
  onClose: () => void;
  onCreated: (p: Prospect) => void;
}) {
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [address, setAddress] = useState("");
  const [projectType, setProjectType] = useState<string>("autre");
  const [budgetRange, setBudgetRange] = useState<string>("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit() {
    // Validation côté client en français — on accepte courriel
    // OU téléphone (au moins l'un des deux).
    if (!name.trim()) {
      setError("Le nom complet est obligatoire.");
      return;
    }
    const cleanEmail = email.trim();
    const cleanPhone = phone.trim();
    if (!cleanEmail && !cleanPhone) {
      setError("Au moins un courriel ou un téléphone est requis.");
      return;
    }
    if (cleanEmail && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(cleanEmail)) {
      setError("Le courriel n'est pas valide (ex. nom@exemple.com).");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      // Le endpoint /api/v1/contact accepte du multipart/form-data
      // (il sert aussi le formulaire public avec photos). On envoie
      // un FormData plutôt qu'un JSON sinon FastAPI ne trouve pas
      // les champs requis (name / email / message / gdpr_consent).
      const fd = new FormData();
      fd.append("name", name.trim());
      // Email vide : on envoie un placeholder calme côté backend
      // si seul le téléphone est fourni (le schéma actuel exige
      // un email côté pydantic). On utilise un domaine sentinel
      // qu'on pourra filtrer plus tard.
      fd.append(
        "email",
        cleanEmail || `no-email+${Date.now()}@horizon.placeholder`
      );
      fd.append(
        "message",
        message.trim() || "(création manuelle depuis le CRM)"
      );
      fd.append("gdpr_consent", "true");
      fd.append("marketing_consent", "false");
      fd.append("locale", "fr");
      fd.append("source", "manual");
      fd.append("project_type", projectType || "autre");
      if (cleanPhone) fd.append("phone", cleanPhone);
      if (address.trim()) fd.append("address", address.trim());
      if (budgetRange) fd.append("budget_range", budgetRange);
      const res = await authedFetch("/api/v1/contact", {
        method: "POST",
        body: fd
      });
      if (!res.ok) {
        // Traduit les erreurs Pydantic anglaises en messages
        // français courts compréhensibles côté UI.
        const txt = await res.text().catch(() => "");
        throw new Error(translateBackendError(txt, res.status));
      }
      // Public ack endpoint returns { ok, reference }; refetch the full row.
      const listRes = await authedFetch(
        `/api/v1/contact?limit=1&status=new`
      );
      if (listRes.ok) {
        const rows = (await listRes.json()) as Prospect[];
        if (rows.length > 0) {
          onCreated(rows[0]);
          return;
        }
      }
      onClose();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4"
      onClick={() => (!busy ? onClose() : null)}
    >
      <div
        className="w-full max-w-lg rounded-2xl border border-brand-800 bg-brand-950 p-6"
        onClick={(e) => e.stopPropagation()}
      >
        <h3 className="text-lg font-bold text-white">Nouveau prospect</h3>
        <div className="mt-5 space-y-3">
          <div>
            <label className="label">Nom complet *</label>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="input"
              autoFocus
            />
          </div>
          <p className="text-[11px] text-white/50">
            Courriel <strong>ou</strong> téléphone — au moins l&apos;un
            des deux est requis.
          </p>
          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <label className="label">Courriel</label>
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="input"
                placeholder="nom@exemple.com"
              />
            </div>
            <div>
              <label className="label">Téléphone</label>
              <input
                value={phone}
                onChange={(e) => setPhone(e.target.value)}
                className="input"
                placeholder="(514) 555-1234"
              />
            </div>
          </div>
          <div>
            <label className="label">Lieu du projet</label>
            <AddressInput
              value={address}
              onChange={setAddress}
              placeholder="Ex. 158 Rue Maurice, Saint-Sauveur, QC"
            />
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <label className="label">Type de projet</label>
              <select
                value={projectType}
                onChange={(e) => setProjectType(e.target.value)}
                className="input"
              >
                {Object.entries(PROJECT_LABEL).map(([k, v]) => (
                  <option key={k} value={k}>
                    {v}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="label">Budget</label>
              <select
                value={budgetRange}
                onChange={(e) => setBudgetRange(e.target.value)}
                className="input"
              >
                <option value="">— Non précisé —</option>
                <option value="under_10k">Moins de 10 000 $</option>
                <option value="10_25">10 000 $ – 25 000 $</option>
                <option value="25_50">25 000 $ – 50 000 $</option>
                <option value="50_100">50 000 $ – 100 000 $</option>
                <option value="over_100">Plus de 100 000 $</option>
                <option value="unsure">Indéterminé</option>
              </select>
            </div>
          </div>
          <div>
            <label className="label">Message / notes initiales</label>
            <textarea
              rows={3}
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              className="input"
            />
          </div>
          {error ? <p className="text-sm text-rose-300">{error}</p> : null}
        </div>
        <div className="mt-6 flex items-center justify-end gap-3">
          <button
            type="button"
            onClick={onClose}
            disabled={busy}
            className="btn-secondary text-sm"
          >
            Annuler
          </button>
          <button
            type="button"
            onClick={submit}
            disabled={busy}
            className="btn-accent text-sm disabled:opacity-60"
          >
            {busy ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" /> Création…
              </>
            ) : (
              "Créer"
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
