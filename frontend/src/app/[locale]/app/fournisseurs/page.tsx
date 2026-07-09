"use client";

import { useEffect, useMemo, useState } from "react";
import { Globe, Loader2, Mail, Phone, Plus, Truck } from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { useAppLayout } from "../layout";
import { authedFetch } from "@/lib/auth";
import { Link } from "@/i18n/navigation";
import { formatPhone } from "@/lib/utils";

type Fournisseur = {
  id: number;
  name: string;
  contact_name: string | null;
  email: string | null;
  phone: string | null;
  category: string | null;
  website: string | null;
  active: boolean;
  notes: string | null;
  created_at: string;
};

export default function FournisseursPage() {
  const { onOpenSidebar } = useAppLayout();
  const [items, setItems] = useState<Fournisseur[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const res = await authedFetch("/api/v1/fournisseurs?limit=500");
        if (!res.ok) throw new Error(`http_${res.status}`);
        const data = (await res.json()) as Fournisseur[];
        if (!cancelled) setItems(data);
      } catch {
        if (!cancelled) setError("Impossible de charger les fournisseurs.");
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
      (f) =>
        f.name.toLowerCase().includes(q) ||
        (f.contact_name || "").toLowerCase().includes(q) ||
        (f.email || "").toLowerCase().includes(q) ||
        (f.phone || "").includes(q) ||
        (f.category || "").toLowerCase().includes(q)
    );
  }, [items, search]);

  return (
    <>
      <AppTopbar
        breadcrumbs={[{ label: "Ressources", href: "/app" }, { label: "Fournisseurs" }]}
        onOpenSidebar={onOpenSidebar}
        onSearch={setSearch}
        searchPlaceholder="Nom, catégorie, contact…"
        rightSlot={
          <Link
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            href={"/app/fournisseurs/new" as any}
            className="btn-accent text-sm"
          >
            <Plus className="mr-1.5 h-4 w-4" /> Nouveau fournisseur
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
          <Empty />
        ) : (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {filtered.map((f) => (
              <Card key={f.id} f={f} />
            ))}
          </div>
        )}
      </div>
    </>
  );
}

function Card({ f }: { f: Fournisseur }) {
  return (
    <Link
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      href={`/app/fournisseurs/${f.id}` as any}
      className="group flex flex-col gap-2 rounded-xl border border-brand-800 bg-brand-900 p-5 transition hover:border-accent-500"
    >
      <div className="flex items-start justify-between">
        <div className="min-w-0">
          <h3 className="truncate text-base font-semibold text-white group-hover:text-accent-500">
            {f.name}
          </h3>
          {f.contact_name ? (
            <p className="truncate text-xs text-white/60">{f.contact_name}</p>
          ) : null}
        </div>
        {!f.active ? (
          <span className="badge badge-neutral">
            Inactif
          </span>
        ) : null}
      </div>

      {f.category ? (
        <span className="self-start rounded-md bg-accent-500/15 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-accent-500">
          {f.category}
        </span>
      ) : null}

      <div className="mt-1 space-y-1 text-xs text-white/70">
        {f.phone ? (
          <p className="flex items-center gap-1.5">
            <Phone className="h-3 w-3" /> {formatPhone(f.phone)}
          </p>
        ) : null}
        {f.email ? (
          <p className="flex items-center gap-1.5">
            <Mail className="h-3 w-3" /> <span className="truncate">{f.email}</span>
          </p>
        ) : null}
        {f.website ? (
          <p className="flex items-center gap-1.5">
            <Globe className="h-3 w-3" /> <span className="truncate">{f.website}</span>
          </p>
        ) : null}
      </div>
    </Link>
  );
}

function Empty() {
  return (
    <div className="empty-state mx-auto mt-16 max-w-md">
      <Truck className="mx-auto h-10 w-10 text-accent-500" />
      <h2 className="mt-4 text-lg font-semibold text-white">Aucun fournisseur</h2>
      <p className="mt-2 text-sm text-white/60">
        Tes fournisseurs de matériaux (plomberie, bois, céramique…) et leurs
        coordonnées.
      </p>
      <Link
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        href={"/app/fournisseurs/new" as any}
        className="btn-accent mt-6 inline-flex text-sm"
      >
        <Plus className="mr-1.5 h-4 w-4" /> Nouveau fournisseur
      </Link>
    </div>
  );
}
