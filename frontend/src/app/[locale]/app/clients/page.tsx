"use client";

import { useEffect, useMemo, useState } from "react";
import { Briefcase, Loader2, Mail, MapPin, Phone, Plus, Users } from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { useAppLayout } from "../layout";
import { authedFetch } from "@/lib/auth";
import { Link } from "@/i18n/navigation";

type Client = {
  id: number;
  name: string;
  email: string | null;
  phone: string | null;
  address: string | null;
  notes: string | null;
  contact_request_id: number | null;
  created_at: string;
};

export default function ClientsPage() {
  const { onOpenSidebar } = useAppLayout();
  const [items, setItems] = useState<Client[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const res = await authedFetch("/api/v1/clients?limit=500");
        if (!res.ok) throw new Error(`http_${res.status}`);
        const data = (await res.json()) as Client[];
        if (!cancelled) setItems(data);
      } catch {
        if (!cancelled) setError("Impossible de charger les clients.");
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
      (c) =>
        c.name.toLowerCase().includes(q) ||
        (c.email || "").toLowerCase().includes(q) ||
        (c.phone || "").includes(q) ||
        (c.address || "").toLowerCase().includes(q)
    );
  }, [items, search]);

  return (
    <>
      <AppTopbar
        breadcrumbs={[{ label: "Construction", href: "/app" }, { label: "Clients" }]}
        onOpenSidebar={onOpenSidebar}
        onSearch={setSearch}
        searchPlaceholder="Nom, courriel, téléphone, adresse…"
        rightSlot={
          <Link
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            href={"/app/clients/new" as any}
            className="btn-accent text-sm"
          >
            <Plus className="mr-1.5 h-4 w-4" /> Nouveau client
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
        ) : filtered.length === 0 ? (
          <EmptyState />
        ) : (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {filtered.map((c) => (
              <Card key={c.id} client={c} />
            ))}
          </div>
        )}
      </div>
    </>
  );
}

function Card({ client: c }: { client: Client }) {
  return (
    <Link
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      href={`/app/clients/${c.id}` as any}
      className="group flex flex-col gap-2 rounded-xl border border-brand-800 bg-brand-900 p-5 transition hover:border-accent-500"
    >
      <div className="flex items-start justify-between">
        <h3 className="truncate text-base font-semibold text-white group-hover:text-accent-500">
          {c.name}
        </h3>
        {c.contact_request_id ? (
          <span className="rounded-md bg-emerald-500/15 px-1.5 py-0.5 text-[10px] font-semibold text-emerald-400">
            Converti
          </span>
        ) : null}
      </div>

      <div className="mt-1 space-y-1 text-xs text-white/70">
        {c.phone ? (
          <p className="flex items-center gap-1.5">
            <Phone className="h-3 w-3" /> <span>{c.phone}</span>
          </p>
        ) : null}
        {c.email ? (
          <p className="flex items-center gap-1.5">
            <Mail className="h-3 w-3" /> <span className="truncate">{c.email}</span>
          </p>
        ) : null}
        {c.address ? (
          <p className="flex items-center gap-1.5">
            <MapPin className="h-3 w-3" />{" "}
            <span className="truncate">{c.address}</span>
          </p>
        ) : null}
      </div>
    </Link>
  );
}

function EmptyState() {
  return (
    <div className="mx-auto mt-16 max-w-md rounded-2xl border border-dashed border-brand-800 bg-brand-900/40 p-10 text-center">
      <Briefcase className="mx-auto h-10 w-10 text-accent-500" />
      <h2 className="mt-4 text-lg font-semibold text-white">Aucun client</h2>
      <p className="mt-2 text-sm text-white/60">
        Les clients se créent automatiquement quand un prospect accepte
        une soumission, ou manuellement avec le bouton ci-dessous.
      </p>
      <Link
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        href={"/app/clients/new" as any}
        className="btn-accent mt-6 inline-flex text-sm"
      >
        <Plus className="mr-1.5 h-4 w-4" /> Nouveau client
      </Link>
      <p className="mt-2 text-[10px] uppercase tracking-wider text-white/40">
        <Users className="mr-1 inline h-3 w-3" /> Section réservée aux
        clients actifs
      </p>
    </div>
  );
}
