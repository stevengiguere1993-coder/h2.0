"use client";

import { useEffect, useMemo, useState } from "react";
import { Briefcase, Calendar, Loader2, MapPin, Search } from "lucide-react";

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

const STATUS_LABEL: Record<string, string> = {
  planned: "Planifié",
  in_progress: "En cours",
  on_hold: "En pause",
  done: "Terminé",
  cancelled: "Annulé"
};

const STATUS_CLASS: Record<string, string> = {
  planned: "bg-sky-500/15 text-sky-300 border-sky-500/30",
  in_progress: "bg-emerald-500/15 text-emerald-300 border-emerald-500/30",
  on_hold: "bg-amber-500/15 text-amber-300 border-amber-500/30",
  done: "bg-slate-500/15 text-slate-300 border-slate-500/30",
  cancelled: "bg-rose-500/15 text-rose-300 border-rose-500/30"
};

function fmtDate(s: string | null): string {
  if (!s) return "";
  try {
    return new Date(s).toLocaleDateString("fr-CA", {
      day: "2-digit",
      month: "short"
    });
  } catch {
    return s;
  }
}

export default function MobileProjets() {
  const [items, setItems] = useState<Project[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [q, setQ] = useState("");

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      try {
        const res = await authedFetch("/api/v1/mobile/projects");
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

  const filtered = useMemo(() => {
    const s = q.trim().toLowerCase();
    if (!s) return items;
    return items.filter(
      (p) =>
        p.name.toLowerCase().includes(s) ||
        (p.address || "").toLowerCase().includes(s)
    );
  }, [items, q]);

  return (
    <>
      <header
        className="sticky top-0 z-30 border-b border-brand-800 bg-brand-950/95 px-4 py-3 backdrop-blur"
        style={{ paddingTop: "max(env(safe-area-inset-top), 0.75rem)" }}
      >
        <h1 className="text-base font-bold text-white">Mes projets</h1>
        <p className="mt-0.5 text-[11px] text-white/50">
          Projets où tu es assigné.
        </p>
        <div className="relative mt-3">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-white/40" />
          <input
            type="search"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Rechercher…"
            className="w-full rounded-lg border border-brand-800 bg-brand-900 py-2 pl-9 pr-3 text-sm text-white placeholder:text-white/40"
          />
        </div>
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
        ) : filtered.length === 0 ? (
          <div className="rounded-2xl border border-dashed border-brand-800 bg-brand-900/40 px-6 py-10 text-center">
            <Briefcase className="mx-auto h-8 w-8 text-white/30" />
            <p className="mt-3 text-sm text-white/60">
              Aucun projet assigné pour l’instant.
            </p>
          </div>
        ) : (
          <ul className="space-y-2">
            {filtered.map((p) => {
              const statusLabel = STATUS_LABEL[p.status] || p.status;
              const statusCls =
                STATUS_CLASS[p.status] ||
                "bg-white/10 text-white/60 border-white/20";
              return (
                <li key={p.id}>
                  <Link
                    // eslint-disable-next-line @typescript-eslint/no-explicit-any
                    href={`/m/intervention/${p.id}` as any}
                    className="block rounded-xl border border-brand-800 bg-brand-900 px-4 py-3 transition hover:border-accent-500/60"
                  >
                    <div className="flex items-start justify-between gap-2">
                      <p className="text-sm font-semibold text-white">
                        {p.name}
                      </p>
                      <span
                        className={`shrink-0 rounded-full border px-2 py-0.5 text-[10px] font-medium ${statusCls}`}
                      >
                        {statusLabel}
                      </span>
                    </div>
                    <div className="mt-1.5 space-y-0.5 text-xs text-white/60">
                      {p.address ? (
                        <p className="flex items-center gap-1.5">
                          <MapPin className="h-3 w-3 shrink-0" />
                          <span className="truncate">{p.address}</span>
                        </p>
                      ) : null}
                      {p.start_date || p.end_date ? (
                        <p className="flex items-center gap-1.5">
                          <Calendar className="h-3 w-3 shrink-0" />
                          <span>
                            {fmtDate(p.start_date)}
                            {p.start_date && p.end_date ? " → " : ""}
                            {fmtDate(p.end_date)}
                          </span>
                        </p>
                      ) : null}
                    </div>
                  </Link>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </>
  );
}
