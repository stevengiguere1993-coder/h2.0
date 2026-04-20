"use client";

import { useEffect, useMemo, useState } from "react";
import { Loader2, Mail, Phone, Plus } from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { useAppLayout } from "../layout";
import { authedFetch } from "@/lib/auth";
import { Link } from "@/i18n/navigation";

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
  created_at: string;
};

type Column = {
  id: string;
  label: string;
  dot: string;
};

const COLUMNS: Column[] = [
  { id: "new", label: "Nouveaux", dot: "bg-emerald-400" },
  { id: "contacted", label: "À rappeler", dot: "bg-amber-400" },
  { id: "quoted", label: "Soumission envoyée", dot: "bg-blue-400" },
  { id: "won", label: "Soumission acceptée", dot: "bg-green-500" },
  { id: "lost", label: "Soumission refusée", dot: "bg-rose-500" }
];

const PROJECT_LABEL: Record<string, string> = {
  salle_bain: "Salle de bain",
  cuisine: "Cuisine",
  multilogement: "Multilogement",
  renovation_complete: "Rénovation complète",
  autre: "Autre"
};

export default function CrmKanbanPage() {
  const { onOpenSidebar } = useAppLayout();
  const [items, setItems] = useState<Prospect[]>([]);
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
      COLUMNS.map((c) => [c.id, [] as Prospect[]])
    );
    for (const p of filtered) {
      const target = COLUMNS.find((c) => c.id === p.status) ? p.status : "new";
      map[target].push(p);
    }
    return map;
  }, [filtered]);

  async function moveProspect(id: number, newStatus: string) {
    const prev = items;
    setItems((xs) =>
      xs.map((x) => (x.id === id ? { ...x, status: newStatus } : x))
    );
    try {
      const res = await authedFetch(`/api/v1/contact/${id}`, {
        method: "PATCH",
        body: JSON.stringify({ status: newStatus })
      });
      if (!res.ok) throw new Error();
    } catch {
      setItems(prev);
      setError("Mise à jour échouée.");
    }
  }

  function onDragStart(id: number) {
    setDragging(id);
  }
  function onDragEnd() {
    setDragging(null);
    setHoverCol(null);
  }
  function onDropToColumn(colId: string) {
    if (dragging == null) return;
    const item = items.find((p) => p.id === dragging);
    if (item && item.status !== colId) moveProspect(dragging, colId);
    setDragging(null);
    setHoverCol(null);
  }

  return (
    <>
      <AppTopbar
        breadcrumbs={[{ label: "Construction" }, { label: "CRM / Prospects" }]}
        onOpenSidebar={onOpenSidebar}
        onSearch={setSearch}
        searchPlaceholder="Rechercher un prospect…"
        rightSlot={
          <button
            type="button"
            className="btn-accent text-sm"
            disabled
            title="À venir — création manuelle"
          >
            <Plus className="mr-1.5 h-4 w-4" /> Créer un prospect
          </button>
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
                  onDrop={() => onDropToColumn(col.id)}
                  className={`flex w-80 min-w-[320px] flex-shrink-0 flex-col rounded-xl border bg-brand-900/60 ${
                    isHover ? "border-accent-500 bg-brand-900" : "border-brand-800"
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
                        Aucun prospect
                      </p>
                    ) : (
                      cards.map((p) => (
                        <ProspectCard
                          key={p.id}
                          prospect={p}
                          dragging={dragging === p.id}
                          onDragStart={() => onDragStart(p.id)}
                          onDragEnd={onDragEnd}
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

function ProspectCard({
  prospect: p,
  dragging,
  onDragStart,
  onDragEnd
}: {
  prospect: Prospect;
  dragging: boolean;
  onDragStart: () => void;
  onDragEnd: () => void;
}) {
  return (
    <Link
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      href={`/app/crm/${p.id}` as any}
      draggable
      onDragStart={onDragStart}
      onDragEnd={onDragEnd}
      className={`block cursor-grab rounded-lg border border-brand-800 bg-brand-950 p-3 transition hover:border-accent-500 active:cursor-grabbing ${
        dragging ? "opacity-40" : ""
      }`}
    >
      <p className="truncate text-sm font-semibold text-white">{p.name}</p>
      {p.phone ? (
        <p className="mt-1 flex items-center gap-1.5 text-xs text-white/60">
          <Phone className="h-3 w-3" />
          <span className="truncate">{p.phone}</span>
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
  );
}
