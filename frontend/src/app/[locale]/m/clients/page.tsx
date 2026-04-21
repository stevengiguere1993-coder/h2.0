"use client";

import { useEffect, useMemo, useState } from "react";
import { Loader2, Mail, Phone, Search, Users } from "lucide-react";

import { authedFetch } from "@/lib/auth";

type Client = {
  id: number;
  name: string;
  email: string | null;
  phone: string | null;
  address: string | null;
};

export default function MobileClients() {
  const [items, setItems] = useState<Client[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [q, setQ] = useState("");

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      try {
        const res = await authedFetch("/api/v1/clients?limit=500");
        if (!res.ok) throw new Error();
        if (!cancelled) setItems((await res.json()) as Client[]);
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
      (c) =>
        c.name.toLowerCase().includes(s) ||
        (c.email || "").toLowerCase().includes(s) ||
        (c.phone || "").includes(s) ||
        (c.address || "").toLowerCase().includes(s)
    );
  }, [items, q]);

  return (
    <>
      <header
        className="sticky top-0 z-30 border-b border-brand-800 bg-brand-950/95 px-4 py-3 backdrop-blur"
        style={{ paddingTop: "max(env(safe-area-inset-top), 0.75rem)" }}
      >
        <h1 className="text-base font-bold text-white">Clients</h1>
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
            <Users className="mx-auto h-8 w-8 text-white/30" />
            <p className="mt-3 text-sm text-white/60">Aucun client trouvé.</p>
          </div>
        ) : (
          <ul className="space-y-2">
            {filtered.map((c) => (
              <li
                key={c.id}
                className="rounded-xl border border-brand-800 bg-brand-900 px-4 py-3"
              >
                <p className="text-sm font-semibold text-white">{c.name}</p>
                <div className="mt-1 space-y-0.5 text-xs text-white/60">
                  {c.phone ? (
                    <a
                      href={`tel:${c.phone}`}
                      className="flex items-center gap-1.5 hover:text-accent-500"
                    >
                      <Phone className="h-3 w-3" />
                      {c.phone}
                    </a>
                  ) : null}
                  {c.email ? (
                    <a
                      href={`mailto:${c.email}`}
                      className="flex items-center gap-1.5 truncate hover:text-accent-500"
                    >
                      <Mail className="h-3 w-3" />
                      <span className="truncate">{c.email}</span>
                    </a>
                  ) : null}
                  {c.address ? (
                    <p className="text-white/50">{c.address}</p>
                  ) : null}
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </>
  );
}
