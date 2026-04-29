"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Loader2, RefreshCw, Trello } from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { Link } from "@/i18n/navigation";
import { authedFetch } from "@/lib/auth";
import { useProspectionLayout } from "../layout";

type Lead = {
  id: number;
  name: string;
  kind: string;
  status: string;
  score: number;
  address: string | null;
  city: string | null;
  nb_logements: number | null;
  owner_name: string | null;
  archived: boolean;
  created_at: string;
};

const COLUMNS: { key: string; label: string; color: string }[] = [
  { key: "a_visiter", label: "Repéré", color: "border-emerald-500/40 bg-emerald-500/5" },
  { key: "visite", label: "Visité", color: "border-blue-500/40 bg-blue-500/5" },
  { key: "a_contacter", label: "À contacter", color: "border-amber-500/40 bg-amber-500/5" },
  { key: "contacte", label: "Contacté", color: "border-violet-500/40 bg-violet-500/5" },
  { key: "soumissionne", label: "Offre soumise", color: "border-pink-500/40 bg-pink-500/5" },
  { key: "offre_acceptee", label: "Offre acceptée", color: "border-fuchsia-500/40 bg-fuchsia-500/5" },
  { key: "en_inspection", label: "Inspection", color: "border-cyan-500/40 bg-cyan-500/5" },
  { key: "en_nego", label: "Négociation", color: "border-yellow-500/40 bg-yellow-500/5" },
  { key: "chez_notaire", label: "Chez le notaire", color: "border-indigo-500/40 bg-indigo-500/5" },
  { key: "en_cession", label: "Cession", color: "border-teal-500/40 bg-teal-500/5" },
  { key: "converti", label: "Acheté ✓", color: "border-green-500/40 bg-green-500/10" },
  { key: "perdu", label: "Perdu", color: "border-rose-500/40 bg-rose-500/5" }
];

const KIND_LABEL: Record<string, string> = {
  multilogement: "Multi-logement",
  terrain: "Terrain",
  semi_commercial: "Semi-commercial",
  autre: "Autre"
};

function scoreClass(score: number): string {
  if (score >= 70) return "bg-emerald-500/20 text-emerald-300";
  if (score >= 40) return "bg-amber-500/20 text-amber-300";
  return "bg-white/10 text-white/50";
}

export default function ProspectionKanbanPage() {
  const { onOpenSidebar } = useProspectionLayout();
  const [leads, setLeads] = useState<Lead[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [draggedId, setDraggedId] = useState<number | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const r = await authedFetch(
        "/api/v1/prospection?limit=1000&archived=false"
      );
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const data = (await r.json()) as Lead[];
      setLeads(data);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const grouped = useMemo(() => {
    const map: Record<string, Lead[]> = {};
    for (const col of COLUMNS) map[col.key] = [];
    for (const lead of leads) {
      if (map[lead.status]) {
        map[lead.status].push(lead);
      } else {
        // Status inconnu : on le met dans Repéré comme fallback
        map.a_visiter.push(lead);
      }
    }
    // Trie par score décroissant dans chaque colonne
    for (const col of COLUMNS) {
      map[col.key].sort((a, b) => b.score - a.score);
    }
    return map;
  }, [leads]);

  async function changeStatus(leadId: number, newStatus: string) {
    try {
      const r = await authedFetch(`/api/v1/prospection/${leadId}`, {
        method: "PATCH",
        body: JSON.stringify({ status: newStatus })
      });
      if (!r.ok) {
        const t = await r.text();
        throw new Error(t.slice(0, 200) || `HTTP ${r.status}`);
      }
      // Update optimiste : déplace le lead localement avant le reload
      setLeads((prev) =>
        prev.map((l) => (l.id === leadId ? { ...l, status: newStatus } : l))
      );
    } catch (e) {
      alert(`Erreur : ${(e as Error).message}`);
      void load();
    }
  }

  return (
    <>
      <AppTopbar
        breadcrumbs={[
          { label: "Prospection", href: "/prospection" },
          { label: "Suivi de leads" }
        ]}
        onOpenSidebar={onOpenSidebar}
      />

      <div className="flex flex-col gap-3 p-4">
        <header className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Trello className="h-5 w-5 text-emerald-400" />
            <h1 className="text-xl font-bold text-white">
              Suivi de leads
            </h1>
            {!loading ? (
              <span className="text-sm text-white/50">
                ({leads.length} actifs)
              </span>
            ) : null}
          </div>
          <button
            type="button"
            onClick={() => void load()}
            disabled={loading}
            className="inline-flex items-center gap-1.5 rounded-md border border-emerald-500/40 bg-emerald-500/10 px-3 py-1.5 text-sm text-emerald-300 hover:bg-emerald-500/20 disabled:opacity-50"
          >
            {loading ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <RefreshCw className="h-3.5 w-3.5" />
            )}
            Rafraîchir
          </button>
        </header>

        {error ? (
          <p className="rounded-md border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
            {error}
          </p>
        ) : null}

        <p className="text-xs text-white/50">
          Glisse-dépose une carte vers une autre colonne pour changer son
          statut. Les leads sont triés par score décroissant dans chaque
          colonne.
        </p>

        <div className="flex gap-3 overflow-x-auto pb-4">
          {COLUMNS.map((col) => {
            const colLeads = grouped[col.key] || [];
            return (
              <div
                key={col.key}
                onDragOver={(e) => e.preventDefault()}
                onDrop={() => {
                  if (draggedId !== null) {
                    void changeStatus(draggedId, col.key);
                    setDraggedId(null);
                  }
                }}
                className={`flex w-72 shrink-0 flex-col rounded-lg border ${col.color}`}
              >
                <div className="border-b border-white/10 px-3 py-2">
                  <div className="flex items-center justify-between">
                    <h2 className="text-sm font-semibold text-white">
                      {col.label}
                    </h2>
                    <span className="rounded-full bg-white/10 px-2 py-0.5 text-[11px] text-white/70">
                      {colLeads.length}
                    </span>
                  </div>
                </div>
                <ul className="flex-1 space-y-2 overflow-y-auto p-2 min-h-[200px]">
                  {colLeads.length === 0 ? (
                    <li className="rounded-md border border-dashed border-white/10 bg-black/20 px-2 py-4 text-center text-[11px] text-white/30">
                      Aucun lead
                    </li>
                  ) : null}
                  {colLeads.map((l) => (
                    <li
                      key={l.id}
                      draggable
                      onDragStart={() => setDraggedId(l.id)}
                      onDragEnd={() => setDraggedId(null)}
                      className="cursor-move"
                    >
                      <Link
                        // eslint-disable-next-line @typescript-eslint/no-explicit-any
                        href={`/prospection/${l.id}` as any}
                        className="block rounded-md border border-brand-800 bg-brand-950/80 p-2.5 text-left transition hover:border-emerald-500/40 hover:bg-brand-950"
                      >
                        <div className="flex items-start justify-between gap-2">
                          <p className="line-clamp-2 text-sm font-medium text-white">
                            {l.name}
                          </p>
                          {l.score > 0 ? (
                            <span
                              className={`shrink-0 rounded px-1.5 py-0.5 text-[10px] font-bold tabular-nums ${scoreClass(l.score)}`}
                              title={`Score : ${l.score}/100`}
                            >
                              {l.score}
                            </span>
                          ) : null}
                        </div>
                        <p className="mt-1 text-[11px] text-white/50">
                          {KIND_LABEL[l.kind] || l.kind}
                          {l.nb_logements
                            ? ` · ${l.nb_logements} logs`
                            : ""}
                        </p>
                        {l.address ? (
                          <p className="mt-0.5 truncate text-[11px] text-white/40">
                            {l.address}
                            {l.city ? ` · ${l.city}` : ""}
                          </p>
                        ) : null}
                        {l.owner_name ? (
                          <p className="mt-1 truncate text-[11px] text-emerald-300/80">
                            👤 {l.owner_name}
                          </p>
                        ) : null}
                      </Link>
                    </li>
                  ))}
                </ul>
              </div>
            );
          })}
        </div>
      </div>
    </>
  );
}
