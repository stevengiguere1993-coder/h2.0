"use client";

import { useEffect, useState } from "react";
import { Loader2, Plus } from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { authedFetch } from "@/lib/auth";
import { Link, useRouter } from "@/i18n/navigation";
import { useProspectionLayout } from "../layout";

/**
 * Liste des deals (Pipeline) — analogue de /entreprises/page.tsx.
 * Chaque deal a sa propre fiche détaillée avec ses tâches, comme
 * une entreprise. La sidebar affiche aussi cette liste pour un
 * accès rapide.
 */

type Deal = {
  id: number;
  address: string;
  priority: string;
  created_at: string;
  updated_at: string;
};

export default function PipelineDealsListPage() {
  const { onOpenSidebar } = useProspectionLayout();
  const router = useRouter();
  const [deals, setDeals] = useState<Deal[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [newAddress, setNewAddress] = useState("");

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const r = await authedFetch("/api/v1/prospection/deals");
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        if (!cancelled) setDeals((await r.json()) as Deal[]);
      } catch (e) {
        if (!cancelled) setError((e as Error).message);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  async function createDeal(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!newAddress.trim()) return;
    setCreating(true);
    try {
      const r = await authedFetch("/api/v1/prospection/deals", {
        method: "POST",
        body: JSON.stringify({
          address: newAddress.trim(),
          priority: "moyenne"
        })
      });
      if (!r.ok) throw new Error();
      const created = (await r.json()) as Deal;
      setNewAddress("");
      // Aller direct sur la fiche du nouveau deal — l'utilisateur
      // veut généralement enchainer avec ses tâches.
      router.push(`/prospection/pipeline/${created.id}` as never);
    } catch {
      setError("Création échouée.");
    } finally {
      setCreating(false);
    }
  }

  return (
    <>
      <AppTopbar
        breadcrumbs={[
          { label: "Prospection", href: "/prospection" },
          { label: "Pipeline" }
        ]}
        onOpenSidebar={onOpenSidebar}
      />

      <div className="p-4 lg:p-6">
        <header className="mb-4 flex items-center gap-3">
          <h1 className="text-2xl font-bold text-white">Pipeline</h1>
          <span className="rounded-md bg-brand-900 px-2 py-1 text-xs text-white/60">
            {deals.length} deal{deals.length > 1 ? "s" : ""}
          </span>
        </header>

        <form
          onSubmit={createDeal}
          className="mb-6 flex flex-wrap items-center gap-2 rounded-xl border border-brand-800 bg-brand-900 p-3"
        >
          <input
            type="text"
            value={newAddress}
            onChange={(e) => setNewAddress(e.target.value)}
            placeholder="Adresse du nouveau deal (ex. 5640 Salaberry)"
            className="input flex-1 min-w-[240px]"
          />
          <button
            type="submit"
            disabled={creating || !newAddress.trim()}
            className="btn-accent text-sm disabled:opacity-50"
          >
            {creating ? (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            ) : (
              <Plus className="mr-1.5 h-4 w-4" />
            )}
            Ajouter un deal
          </button>
        </form>

        {error ? (
          <p className="mb-4 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-300">
            {error}
          </p>
        ) : null}

        {loading ? (
          <div className="flex min-h-[40vh] items-center justify-center">
            <Loader2 className="h-6 w-6 animate-spin text-accent-500" />
          </div>
        ) : deals.length === 0 ? (
          <div className="mx-auto mt-12 max-w-md rounded-2xl border border-dashed border-brand-800 bg-brand-900/40 p-10 text-center">
            <h2 className="text-lg font-semibold text-white">
              Aucun deal pour l&apos;instant
            </h2>
            <p className="mt-2 text-sm text-white/60">
              Saisis une adresse et clique « Ajouter un deal » pour
              commencer ton pipeline.
            </p>
          </div>
        ) : (
          <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {deals.map((d) => (
              <li key={d.id}>
                <Link
                  // eslint-disable-next-line @typescript-eslint/no-explicit-any
                  href={`/prospection/pipeline/${d.id}` as any}
                  className="block rounded-xl border border-brand-800 bg-brand-900 p-4 text-left transition hover:border-emerald-500/50"
                >
                  <h3 className="text-base font-semibold text-white break-words">
                    {d.address}
                  </h3>
                  <p className="mt-2 text-[11px] text-white/40">
                    Ajouté le{" "}
                    {new Date(d.created_at).toLocaleDateString("fr-CA", {
                      day: "2-digit",
                      month: "short",
                      year: "numeric"
                    })}
                  </p>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </div>
    </>
  );
}
