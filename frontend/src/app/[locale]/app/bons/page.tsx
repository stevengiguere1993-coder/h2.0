"use client";

import { useEffect, useMemo, useState } from "react";
import { ClipboardCheck, Loader2, Plus } from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { useAppLayout } from "../layout";
import { authedFetch } from "@/lib/auth";
import { Link } from "@/i18n/navigation";

type Bon = {
  id: number;
  reference: string;
  title: string;
  description: string | null;
  project_id: number | null;
  client_id: number | null;
  amount: number | string | null;
  status: string;
  sent_at: string | null;
  signed_at: string | null;
  signed_by_name: string | null;
  created_at: string;
};

type Column = { id: string; label: string; dot: string };
const COLUMNS: Column[] = [
  { id: "draft", label: "Brouillons", dot: "bg-white/40" },
  { id: "sent", label: "Envoyés", dot: "bg-blue-400" },
  { id: "signed", label: "Signés", dot: "bg-emerald-400" },
  { id: "cancelled", label: "Annulés", dot: "bg-white/20" }
];

function money(n: number | string | null): string {
  if (n == null || n === "") return "—";
  const num = typeof n === "string" ? Number(n) : n;
  return new Intl.NumberFormat("fr-CA", {
    style: "currency",
    currency: "CAD",
    maximumFractionDigits: 0
  }).format(num);
}

export default function BonsPage() {
  const { onOpenSidebar } = useAppLayout();
  const [items, setItems] = useState<Bon[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const res = await authedFetch("/api/v1/bons-travail?limit=500");
        if (!res.ok) throw new Error(`http_${res.status}`);
        const data = (await res.json()) as Bon[];
        if (!cancelled) setItems(data);
      } catch {
        if (!cancelled) setError("Impossible de charger les bons de travail.");
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
      (b) =>
        b.reference.toLowerCase().includes(q) ||
        b.title.toLowerCase().includes(q) ||
        (b.description || "").toLowerCase().includes(q)
    );
  }, [items, search]);

  const byColumn = useMemo(() => {
    const map: Record<string, Bon[]> = Object.fromEntries(
      COLUMNS.map((c) => [c.id, [] as Bon[]])
    );
    for (const b of filtered) {
      const target = COLUMNS.find((c) => c.id === b.status) ? b.status : "draft";
      map[target].push(b);
    }
    return map;
  }, [filtered]);

  return (
    <>
      <AppTopbar
        breadcrumbs={[
          { label: "Construction", href: "/app" },
          { label: "Bons de travail" }
        ]}
        onOpenSidebar={onOpenSidebar}
        onSearch={setSearch}
        searchPlaceholder="Référence, titre…"
        rightSlot={
          <Link
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            href={"/app/bons/new" as any}
            className="btn-accent text-sm"
          >
            <Plus className="mr-1.5 h-4 w-4" /> Nouveau bon
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
          <div className="flex min-h-[40vh] items-center justify-center">
            <Loader2 className="h-6 w-6 animate-spin text-accent-500" />
          </div>
        ) : items.length === 0 ? (
          <Empty />
        ) : (
          <div className="flex gap-4 overflow-x-auto pb-4">
            {COLUMNS.map((col) => {
              const cards = byColumn[col.id] || [];
              return (
                <div
                  key={col.id}
                  className="flex w-80 min-w-[320px] flex-shrink-0 flex-col rounded-xl border border-brand-800 bg-brand-900/60"
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
                        Aucun bon
                      </p>
                    ) : (
                      cards.map((b) => (
                        <Link
                          key={b.id}
                          // eslint-disable-next-line @typescript-eslint/no-explicit-any
                          href={`/app/bons/${b.id}` as any}
                          className="block rounded-lg border border-brand-800 bg-brand-950 p-3 transition hover:border-accent-500"
                        >
                          <h3 className="truncate text-sm font-semibold text-white">
                            {b.reference}
                          </h3>
                          <p className="mt-0.5 truncate text-xs text-white/60">
                            {b.title}
                          </p>
                          <div className="mt-2 flex items-center justify-between text-xs">
                            <span className="text-white/50">
                              {b.signed_by_name
                                ? `Signé ${b.signed_by_name}`
                                : "—"}
                            </span>
                            <span className="font-semibold text-white">
                              {money(b.amount)}
                            </span>
                          </div>
                        </Link>
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

function Empty() {
  return (
    <div className="mx-auto mt-16 max-w-md rounded-2xl border border-dashed border-brand-800 bg-brand-900/40 p-10 text-center">
      <ClipboardCheck className="mx-auto h-10 w-10 text-accent-500" />
      <h2 className="mt-4 text-lg font-semibold text-white">Aucun bon de travail</h2>
      <p className="mt-2 text-sm text-white/60">
        Les bons de travail servent à faire signer les extras et changements
        hors soumission initiale.
      </p>
      <Link
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        href={"/app/bons/new" as any}
        className="btn-accent mt-6 inline-flex text-sm"
      >
        <Plus className="mr-1.5 h-4 w-4" /> Nouveau bon
      </Link>
    </div>
  );
}
