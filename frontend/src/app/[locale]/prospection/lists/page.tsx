"use client";

import { useCallback, useEffect, useState } from "react";
import {
  ArrowLeft,
  ChevronRight,
  Layers,
  Loader2,
  Plus,
  RefreshCw,
  Trash2
} from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { Link } from "@/i18n/navigation";
import { authedFetch } from "@/lib/auth";
import { useConfirm } from "@/components/confirm-dialog";
import { useProspectionLayout } from "../layout";

type ProspectionList = {
  id: number;
  name: string;
  description: string | null;
  criteria_json: string | null;
  created_by_user_id: number | null;
  created_at: string;
  updated_at: string;
  member_count: number;
};

export default function ProspectionListsIndexPage() {
  const { onOpenSidebar } = useProspectionLayout();
  const confirm = useConfirm();
  const [lists, setLists] = useState<ProspectionList[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await authedFetch("/api/v1/prospection/lists");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setLists((await res.json()) as ProspectionList[]);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function createEmpty() {
    if (!newName.trim() || creating) return;
    setCreating(true);
    try {
      const res = await authedFetch("/api/v1/prospection/lists", {
        method: "POST",
        body: JSON.stringify({ name: newName.trim() })
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setNewName("");
      await load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setCreating(false);
    }
  }

  async function deleteList(id: number, name: string) {
    if (
      !(await confirm({
        title: `Supprimer la liste « ${name} » ?`,
        description: "Les leads ne sont pas supprimés, juste retirés de la liste."
      }))
    )
      return;
    const res = await authedFetch(`/api/v1/prospection/lists/${id}`, {
      method: "DELETE"
    });
    if (res.ok || res.status === 204) {
      setLists((prev) => prev.filter((l) => l.id !== id));
    }
  }

  return (
    <>
      <AppTopbar
        breadcrumbs={[
          { label: "Prospection", href: "/prospection" },
          { label: "Listes" }
        ]}
        onOpenSidebar={onOpenSidebar}
        rightSlot={
          <Link
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            href={"/prospection/leads" as any}
            className="btn-outline-accent btn-sm"
          >
            <ArrowLeft className="h-3.5 w-3.5" />
            Tous les leads
          </Link>
        }
      />

      <div className="mx-auto max-w-4xl p-4 lg:p-6">
        <header className="flex items-center gap-3">
          <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-accent-500/15 text-accent-500">
            <Layers className="h-5 w-5" />
          </span>
          <div className="flex-1">
            <h1 className="text-2xl font-bold text-white">
              Mes listes
            </h1>
            <p className="text-sm text-white/60">
              Segments sauvegardés. Construis une liste depuis les
              filtres de la page « Tous les leads » (bouton « Sauvegarder
              cette vue »), ou crée une liste vide ici.
            </p>
          </div>
          <button
            type="button"
            onClick={load}
            className="btn-ghost btn-xs"
            title="Rafraîchir"
          >
            <RefreshCw className="h-4 w-4" />
          </button>
        </header>

        {/* Création rapide d'une liste vide */}
        <div className="mt-4 flex flex-wrap items-end gap-2 rounded-xl border border-brand-800 bg-brand-900 p-3">
          <div className="flex-1">
            <label className="label">
              Nouvelle liste vide
            </label>
            <input
              type="text"
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") void createEmpty();
              }}
              placeholder="Ex: « Plateau 6-12 portes »"
              className="input"
            />
          </div>
          <button
            type="button"
            onClick={createEmpty}
            disabled={!newName.trim() || creating}
            className="btn-accent text-sm"
          >
            {creating ? (
              <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />
            ) : (
              <Plus className="mr-1.5 h-4 w-4" />
            )}
            Créer
          </button>
        </div>

        {error ? (
          <p className="mt-4 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-300">
            {error}
          </p>
        ) : null}

        {loading ? (
          <div className="flex min-h-[20vh] items-center justify-center">
            <Loader2 className="h-6 w-6 animate-spin text-accent-500" />
          </div>
        ) : lists.length === 0 ? (
          <div className="mt-6 rounded-xl border border-dashed border-brand-800 bg-brand-900/40 p-8 text-center">
            <Layers className="mx-auto h-8 w-8 text-white/20" />
            <p className="mt-3 text-sm text-white/60">
              Aucune liste pour l&apos;instant.
            </p>
            <p className="mt-1 text-xs text-white/40">
              Crée-en une vide ci-dessus ou utilise le List Builder
              depuis « Tous les leads ».
            </p>
          </div>
        ) : (
          <ul className="mt-6 space-y-2">
            {lists.map((l) => (
              <li
                key={l.id}
                className="group flex items-center gap-3 rounded-xl border border-brand-800 bg-brand-900 p-3 transition hover:border-accent-500/40"
              >
                <Link
                  // eslint-disable-next-line @typescript-eslint/no-explicit-any
                  href={`/prospection/lists/${l.id}` as any}
                  className="min-w-0 flex-1"
                >
                  <div className="flex items-center gap-2">
                    <h3 className="truncate font-medium text-white">
                      {l.name}
                    </h3>
                    <span className="rounded-full border border-accent-500/30 bg-accent-500/10 px-2 py-0.5 text-[11px] tabular-nums text-accent-500">
                      {l.member_count}
                    </span>
                    {l.criteria_json ? (
                      <span className="badge badge-blue">
                        builder
                      </span>
                    ) : null}
                  </div>
                  {l.description ? (
                    <p className="mt-0.5 truncate text-[11px] text-white/50">
                      {l.description}
                    </p>
                  ) : null}
                </Link>
                <button
                  type="button"
                  onClick={() => deleteList(l.id, l.name)}
                  className="btn-outline-rose btn-xs opacity-0 transition group-hover:opacity-100"
                  aria-label="Supprimer"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
                <ChevronRight className="h-4 w-4 shrink-0 text-white/30" />
              </li>
            ))}
          </ul>
        )}
      </div>
    </>
  );
}
