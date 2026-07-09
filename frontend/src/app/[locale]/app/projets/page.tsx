"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  Briefcase,
  CheckCircle2,
  Clock,
  GripVertical,
  Loader2,
  MapPin,
  Plus,
  Trash2
} from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { useAppLayout } from "../layout";
import { authedFetch } from "@/lib/auth";
import { Link } from "@/i18n/navigation";
import { useConfirm } from "@/components/confirm-dialog";

type Project = {
  id: number;
  name: string;
  client_id: number | null;
  contact_request_id: number | null;
  soumission_id: number | null;
  status: string;
  address: string | null;
  description: string | null;
  notes: string | null;
  start_date: string | null;
  end_date: string | null;
  budget: number | string | null;
  // Fallback côté affichage quand budget est null mais qu'on a une
  // soumission liée (ex. projet créé via auto-acceptation sans budget
  // saisi).
  soumission_total: number | string | null;
  // Flux A — état de signature des bons liés (corrections).
  awaiting_signature?: boolean;
  has_signed_bon?: boolean;
  // Bon de correction créé mais pas encore envoyé au client.
  correction_bon_draft?: boolean;
  // Statut de la correction : "a_planifier" | "planifie" | "termine".
  correction_status?: string;
  created_at: string;
  updated_at: string;
};

type Column = { id: string; label: string; dot: string };

const COLUMNS: Column[] = [
  { id: "planned", label: "À planifier", dot: "bg-white/40" },
  { id: "ready_to_start", label: "En attente de début", dot: "bg-violet-400" },
  { id: "in_progress", label: "En cours", dot: "bg-blue-400" },
  { id: "suspended", label: "Suspendu", dot: "bg-amber-400" },
  {
    id: "correction",
    label: "Correction / Amélioration",
    dot: "bg-rose-400"
  },
  { id: "delivered", label: "Livré", dot: "bg-emerald-400" }
];

function fmtMoney(
  n: number | string | null,
  fallback: number | string | null = null
): string {
  let v = n;
  if (v == null || v === "" || Number(v) === 0) v = fallback;
  if (v == null || v === "") return "—";
  const num = typeof v === "string" ? Number(v) : v;
  if (!Number.isFinite(num)) return "—";
  return new Intl.NumberFormat("fr-CA", {
    style: "currency",
    currency: "CAD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2
  }).format(num);
}

function fmtDate(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("fr-CA", {
    day: "2-digit",
    month: "short"
  });
}

export default function ProjectsPage() {
  const { onOpenSidebar } = useAppLayout();
  const confirm = useConfirm();
  const [items, setItems] = useState<Project[]>([]);
  const [clientNames, setClientNames] = useState<Map<number, string>>(
    new Map()
  );
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [dragging, setDragging] = useState<number | null>(null);
  const [hoverCol, setHoverCol] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const [projRes, clientsRes] = await Promise.all([
          authedFetch("/api/v1/projects?limit=200"),
          authedFetch("/api/v1/clients?limit=500")
        ]);
        if (!projRes.ok) throw new Error(`http_${projRes.status}`);
        const data = (await projRes.json()) as Project[];
        if (!cancelled) setItems(data);
        if (clientsRes.ok) {
          const cs = (await clientsRes.json()) as Array<{
            id: number;
            name: string;
          }>;
          if (!cancelled) {
            setClientNames(new Map(cs.map((c) => [c.id, c.name])));
          }
        }
      } catch {
        if (!cancelled) setError("Impossible de charger les projets.");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, []);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return items;
    return items.filter(
      (p) =>
        p.name.toLowerCase().includes(q) ||
        (p.address || "").toLowerCase().includes(q) ||
        (p.description || "").toLowerCase().includes(q)
    );
  }, [items, search]);

  const byColumn = useMemo(() => {
    const map: Record<string, Project[]> = Object.fromEntries(
      COLUMNS.map((c) => [c.id, [] as Project[]])
    );
    for (const p of filtered) {
      const target = COLUMNS.find((c) => c.id === p.status) ? p.status : "planned";
      map[target].push(p);
    }
    return map;
  }, [filtered]);

  async function moveProject(id: number, newStatus: string) {
    const prev = items;
    setItems((xs) =>
      xs.map((x) =>
        x.id === id
          ? {
              ...x,
              status: newStatus,
              // Le backend prépare automatiquement le bon de correction au
              // passage en colonne Correction : on reflète tout de suite
              // « Bon à envoyer » sans attendre un rechargement.
              correction_bon_draft:
                newStatus === "correction" &&
                !x.has_signed_bon &&
                !x.awaiting_signature
                  ? true
                  : x.correction_bon_draft
            }
          : x
      )
    );
    try {
      const res = await authedFetch(`/api/v1/projects/${id}`, {
        method: "PUT",
        body: JSON.stringify({ status: newStatus })
      });
      if (!res.ok) {
        const t = await res.text().catch(() => "");
        throw new Error(`HTTP ${res.status} ${t.slice(0, 160)}`);
      }
    } catch (e) {
      setItems(prev);
      setError(`Mise à jour du statut échouée : ${(e as Error).message}`);
    }
  }

  // ── Glisser-déposer tactile (mobile) ──
  // Le drag HTML5 ne marche pas au doigt : on gère le tactile via une
  // poignée + Pointer Events. La colonne sous le doigt est retrouvée par
  // `data-col-id` + elementFromPoint.
  function columnIdAtPoint(x: number, y: number): string | null {
    if (typeof document === "undefined") return null;
    const el = document.elementFromPoint(x, y);
    return el?.closest("[data-col-id]")?.getAttribute("data-col-id") ?? null;
  }
  function onTouchDragMove(x: number, y: number) {
    setHoverCol(columnIdAtPoint(x, y));
  }
  function onTouchDragEnd(id: number, x: number, y: number) {
    const cid = columnIdAtPoint(x, y);
    const col = COLUMNS.find((c) => c.id === cid);
    const item = items.find((p) => p.id === id);
    if (col && item && item.status !== col.id) moveProject(id, col.id);
    setDragging(null);
    setHoverCol(null);
  }

  async function deleteProject(id: number, name: string) {
    if (
      !(await confirm({
        title: `Supprimer « ${name} » ?`,
        description:
          "Le projet et toutes ses données liées (phases, tâches, photos) seront définitivement supprimés.",
      }))
    )
      return;
    const prev = items;
    setItems((xs) => xs.filter((x) => x.id !== id));
    try {
      const res = await authedFetch(`/api/v1/projects/${id}`, {
        method: "DELETE",
      });
      if (!res.ok && res.status !== 204) throw new Error();
    } catch {
      setItems(prev);
      setError("Suppression du projet échouée.");
    }
  }

  return (
    <>
      <AppTopbar
        breadcrumbs={[{ label: "Construction", href: "/app" }, { label: "Projets" }]}
        onOpenSidebar={onOpenSidebar}
        onSearch={setSearch}
        searchPlaceholder="Rechercher un projet…"
        rightSlot={
          <Link
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            href={"/app/projets/new" as any}
            className="btn-accent text-sm"
          >
            <Plus className="mr-1.5 h-4 w-4" />
            Nouveau projet
          </Link>
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
        ) : items.length === 0 ? (
          <EmptyState />
        ) : (
          <div className="flex gap-4 overflow-x-auto pb-4">
            {COLUMNS.map((col) => {
              const cards = byColumn[col.id] || [];
              const isHover = hoverCol === col.id;
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
                  onDrop={() => {
                    if (dragging == null) return;
                    const p = items.find((x) => x.id === dragging);
                    if (p && p.status !== col.id) moveProject(dragging, col.id);
                    setDragging(null);
                    setHoverCol(null);
                  }}
                  className={`flex w-80 min-w-[320px] flex-shrink-0 flex-col rounded-xl border bg-brand-900/60 ${
                    isHover
                      ? "border-accent-500 bg-brand-900"
                      : "border-brand-800"
                  }`}
                >
                  <div className="flex items-center justify-between border-b border-brand-800 px-4 py-3">
                    <div className="flex items-center gap-2">
                      <span className={`h-2 w-2 rounded-full ${col.dot}`} />
                      <h2 className="text-sm font-semibold text-white">
                        {col.label}
                      </h2>
                    </div>
                    <span className="rounded-md bg-brand-950 px-2 py-0.5 text-xs font-semibold text-white/70">
                      {cards.length}
                    </span>
                  </div>

                  <div className="flex-1 space-y-3 p-3">
                    {cards.length === 0 ? (
                      <p className="py-8 text-center text-xs text-white/40">
                        Aucun projet
                      </p>
                    ) : (
                      cards.map((p) => (
                        <ProjectCard
                          key={p.id}
                          project={p}
                          clientName={
                            p.client_id
                              ? clientNames.get(p.client_id) ?? null
                              : null
                          }
                          dragging={dragging === p.id}
                          onDragStart={() => setDragging(p.id)}
                          onDragEnd={() => {
                            setDragging(null);
                            setHoverCol(null);
                          }}
                          onDelete={() => deleteProject(p.id, p.name)}
                          onTouchDragStart={() => setDragging(p.id)}
                          onTouchDragMove={onTouchDragMove}
                          onTouchDragEnd={(x, y) => onTouchDragEnd(p.id, x, y)}
                        />
                      ))
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </>
  );
}

function ProjectCard({
  project: p,
  clientName,
  dragging,
  onDragStart,
  onDragEnd,
  onDelete,
  onTouchDragStart,
  onTouchDragMove,
  onTouchDragEnd
}: {
  project: Project;
  clientName: string | null;
  dragging: boolean;
  onDragStart: () => void;
  onDragEnd: () => void;
  onDelete: () => void;
  onTouchDragStart: () => void;
  onTouchDragMove: (x: number, y: number) => void;
  onTouchDragEnd: (x: number, y: number) => void;
}) {
  const touch = useRef<{ x: number; y: number; moved: boolean } | null>(null);
  return (
    <Link
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      href={`/app/projets/${p.id}` as any}
      draggable
      onDragStart={onDragStart}
      onDragEnd={onDragEnd}
      className={`group relative block rounded-lg border bg-brand-950 py-3 pl-7 pr-3 transition ${
        dragging
          ? "border-accent-500 opacity-60"
          : "border-brand-800 hover:border-accent-500"
      }`}
    >
      {/* Poignée de glissement — fonctionne au doigt (Pointer Events).
          touch-action:none pour que le glisser ne fasse pas défiler la
          page. Le reste de la carte se tape pour ouvrir le projet. */}
      <div
        className="absolute left-0 top-0 flex h-full w-6 cursor-grab touch-none items-start justify-center pt-3 text-white/30 active:cursor-grabbing"
        style={{ touchAction: "none" }}
        aria-label="Glisser pour déplacer"
        title="Glisser pour déplacer"
        onPointerDown={(e) => {
          if (e.pointerType === "mouse") return;
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
        onClick={(e) => {
          e.preventDefault();
          e.stopPropagation();
        }}
      >
        <GripVertical className="h-4 w-4" />
      </div>
      <button
        type="button"
        onClick={(e) => {
          e.preventDefault();
          e.stopPropagation();
          onDelete();
        }}
        aria-label="Supprimer"
        title="Supprimer"
        className="btn-outline-rose btn-xs absolute right-2 top-2 opacity-0 group-hover:opacity-100"
      >
        <Trash2 className="h-3.5 w-3.5" />
      </button>
      {/* Top : adresse du projet (titre principal) ; fallback au
          nom interne si aucune adresse n'a encore été saisie. */}
      <h3 className="flex items-start gap-1 pr-6 text-sm font-semibold text-white">
        {p.address ? (
          <>
            <MapPin className="mt-0.5 h-3.5 w-3.5 flex-shrink-0 text-white/60" />
            <span className="truncate">{p.address}</span>
          </>
        ) : (
          <span className="truncate">{p.name}</span>
        )}
      </h3>
      {/* Nom du client (sous-titre). */}
      {clientName ? (
        <p className="mt-1 truncate text-xs text-white/60">{clientName}</p>
      ) : null}
      <div className="mt-2 flex items-center justify-between text-xs">
        <span className="text-white/50">
          {fmtDate(p.start_date)}
          {p.end_date ? ` → ${fmtDate(p.end_date)}` : ""}
        </span>
        {/* Montant de la soumission acceptée (fallback budget). */}
        <span className="font-semibold text-white">
          {fmtMoney(p.budget, p.soumission_total)}
        </span>
      </div>

      {/* Flux A — badges signature + statut de correction + action, tous
          au même gabarit (rounded-md, px-2 py-1, text-[11px], icône h-3). */}
      {(p.has_signed_bon ||
        p.awaiting_signature ||
        p.status === "correction") && (
        <div className="mt-3 flex flex-wrap items-center gap-1.5">
          {p.has_signed_bon ? (
            <span className="badge badge-emerald">
              <CheckCircle2 className="h-3 w-3" /> Signé
            </span>
          ) : p.awaiting_signature ? (
            <span className="badge badge-rose">
              <Clock className="h-3 w-3" /> À signer
            </span>
          ) : p.correction_bon_draft ? (
            <span className="badge badge-neutral">
              <Clock className="h-3 w-3" /> Bon à envoyer
            </span>
          ) : null}
          {p.status === "correction" && p.correction_status === "termine" ? (
            <span className="badge badge-emerald">
              <CheckCircle2 className="h-3 w-3" /> Correction terminée
            </span>
          ) : p.status === "correction" &&
            p.correction_status === "planifie" ? (
            <span className="badge badge-sky">
              <CheckCircle2 className="h-3 w-3" /> Correction planifiée
            </span>
          ) : p.status === "correction" ? (
            <span className="badge badge-amber">
              <Clock className="h-3 w-3" /> Correction à planifier
            </span>
          ) : null}
        </div>
      )}
    </Link>
  );
}

function EmptyState() {
  return (
    <div className="empty-state mx-auto mt-16 max-w-md">
      <Briefcase className="mx-auto h-10 w-10 text-accent-500" />
      <h2 className="mt-4 text-lg font-semibold text-white">Aucun projet</h2>
      <p className="mt-2 text-sm text-white/60">
        Crée un projet à partir d&apos;une soumission acceptée ou directement
        avec le bouton ci-dessous.
      </p>
      <Link
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        href={"/app/projets/new" as any}
        className="btn-accent mt-6 inline-flex text-sm"
      >
        <Plus className="mr-1.5 h-4 w-4" />
        Nouveau projet
      </Link>
    </div>
  );
}
