"use client";

import { useEffect, useMemo, useState } from "react";
import { Briefcase, Loader2, MapPin, Plus, Trash2 } from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { useDevlogLayout } from "../layout";
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
  created_at: string;
  updated_at: string;
};

type Column = { id: string; label: string; dot: string };

// IDs alignés sur les valeurs backend DevlogProject.status (français).
const COLUMNS: Column[] = [
  { id: "planifie", label: "À planifier", dot: "bg-white/40" },
  { id: "en_attente", label: "En attente de début", dot: "bg-violet-400" },
  { id: "en_cours", label: "En cours", dot: "bg-blue-400" },
  { id: "suspendu", label: "Suspendu", dot: "bg-amber-400" },
  { id: "livre", label: "Livré", dot: "bg-emerald-400" }
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
  const { onOpenSidebar } = useDevlogLayout();
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
          authedFetch("/api/v1/devlog/projects?limit=200"),
          authedFetch("/api/v1/devlog/clients?limit=500")
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
      const target = COLUMNS.find((c) => c.id === p.status) ? p.status : "planifie";
      map[target].push(p);
    }
    return map;
  }, [filtered]);

  async function moveProject(id: number, newStatus: string) {
    const prev = items;
    setItems((xs) => xs.map((x) => (x.id === id ? { ...x, status: newStatus } : x)));
    try {
      const res = await authedFetch(`/api/v1/devlog/projects/${id}`, {
        method: "PUT",
        body: JSON.stringify({ status: newStatus })
      });
      if (!res.ok) throw new Error();
    } catch {
      setItems(prev);
      setError("Mise à jour du statut échouée.");
    }
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
      const res = await authedFetch(`/api/v1/devlog/projects/${id}`, {
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
        breadcrumbs={[{ label: "Développement logiciel", href: "/dev-logiciel" as any }, { label: "Projets" }]}
        onOpenSidebar={onOpenSidebar}
        onSearch={setSearch}
        searchPlaceholder="Rechercher un projet…"
        rightSlot={
          <Link
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            href={"/dev-logiciel/projets/new" as any}
            className="inline-flex items-center justify-center rounded-xl bg-blue-500 px-5 py-3 font-semibold text-white transition hover:bg-blue-400 text-sm"
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
            <Loader2 className="h-6 w-6 animate-spin text-blue-400" />
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
                      ? "border-blue-500 bg-brand-900"
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
  onDelete
}: {
  project: Project;
  clientName: string | null;
  dragging: boolean;
  onDragStart: () => void;
  onDragEnd: () => void;
  onDelete: () => void;
}) {
  return (
    <Link
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      href={`/dev-logiciel/projets/${p.id}` as any}
      draggable
      onDragStart={onDragStart}
      onDragEnd={onDragEnd}
      className={`group relative block rounded-lg border bg-brand-950 p-3 transition ${
        dragging
          ? "border-blue-500 opacity-60"
          : "border-brand-800 hover:border-blue-500"
      }`}
    >
      <button
        type="button"
        onClick={(e) => {
          e.preventDefault();
          e.stopPropagation();
          onDelete();
        }}
        aria-label="Supprimer"
        title="Supprimer"
        className="absolute right-2 top-2 rounded-md p-1 text-white/40 opacity-0 transition hover:bg-rose-500/15 hover:text-rose-400 group-hover:opacity-100"
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
    </Link>
  );
}

function EmptyState() {
  return (
    <div className="mx-auto mt-16 max-w-md rounded-2xl border border-dashed border-brand-800 bg-brand-900/40 p-10 text-center">
      <Briefcase className="mx-auto h-10 w-10 text-blue-400" />
      <h2 className="mt-4 text-lg font-semibold text-white">Aucun projet</h2>
      <p className="mt-2 text-sm text-white/60">
        Crée un projet à partir d&apos;une soumission acceptée ou directement
        avec le bouton ci-dessous.
      </p>
      <Link
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        href={"/dev-logiciel/projets/new" as any}
        className="inline-flex mt-6 rounded-xl bg-blue-500 px-5 py-3 font-semibold text-white transition hover:bg-blue-400 text-sm"
      >
        <Plus className="mr-1.5 h-4 w-4" />
        Nouveau projet
      </Link>
    </div>
  );
}
