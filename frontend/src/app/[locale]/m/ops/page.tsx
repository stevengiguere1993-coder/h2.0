"use client";

import { useEffect, useState } from "react";
import { Briefcase, ChevronRight, Loader2 } from "lucide-react";

import { Link } from "@/i18n/navigation";
import { authedFetch } from "@/lib/auth";

type Project = {
  id: number;
  name: string;
  address: string | null;
  status: string;
  start_date: string | null;
  end_date: string | null;
};

const STATUS_LABELS: Record<string, string> = {
  planned: "Prévu",
  in_progress: "En cours",
  suspended: "Suspendu",
  delivered: "Livré"
};

export default function MobileOps() {
  const [items, setItems] = useState<Project[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      try {
        const res = await authedFetch("/api/v1/projects?limit=200");
        if (!res.ok) throw new Error();
        if (!cancelled) setItems((await res.json()) as Project[]);
      } catch {
        if (!cancelled) setError("Chargement échoué.");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, []);

  const active = items.filter((p) =>
    ["planned", "in_progress", "suspended"].includes(p.status)
  );

  return (
    <>
      <header
        className="sticky top-0 z-30 border-b border-brand-800 bg-brand-950/95 px-4 py-3 backdrop-blur"
        style={{ paddingTop: "max(env(safe-area-inset-top), 0.75rem)" }}
      >
        <h1 className="text-base font-bold text-white">Opérations</h1>
        <p className="mt-0.5 text-xs text-white/50">Chantiers actifs</p>
      </header>

      <div className="p-4">
        {error ? (
          <p className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
            {error}
          </p>
        ) : null}

        {loading ? (
          <div className="flex items-center justify-center py-10">
            <Loader2 className="h-5 w-5 animate-spin text-white/40" />
          </div>
        ) : active.length === 0 ? (
          <div className="rounded-2xl border border-dashed border-brand-800 bg-brand-900/40 px-6 py-10 text-center">
            <Briefcase className="mx-auto h-8 w-8 text-white/30" />
            <p className="mt-3 text-sm text-white/60">
              Aucun chantier en cours.
            </p>
          </div>
        ) : (
          <ul className="space-y-2">
            {active.map((p) => (
              <li
                key={p.id}
                className="rounded-xl border border-brand-800 bg-brand-900"
              >
                <Link
                  // eslint-disable-next-line @typescript-eslint/no-explicit-any
                  href={`/m/intervention/${p.id}` as any}
                  className="flex items-center justify-between gap-2 px-4 py-3"
                >
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-semibold text-white">
                      {p.name}
                    </p>
                    {p.address ? (
                      <p className="mt-0.5 truncate text-xs text-white/50">
                        {p.address}
                      </p>
                    ) : null}
                    <p className="mt-1 text-[10px] uppercase tracking-wider text-accent-500">
                      {STATUS_LABELS[p.status] || p.status}
                    </p>
                  </div>
                  <ChevronRight className="h-4 w-4 text-white/30" />
                </Link>
              </li>
            ))}
          </ul>
        )}
      </div>
    </>
  );
}
