"use client";

import { useEffect, useMemo, useState } from "react";
import { Loader2, Mail, Phone, Plus, Users } from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { useAppLayout } from "../layout";
import { authedFetch } from "@/lib/auth";
import { Link } from "@/i18n/navigation";
import { formatPhone } from "@/lib/utils";

type Employe = {
  id: number;
  full_name: string;
  email: string | null;
  phone: string | null;
  role: string | null;
  hourly_rate: number | string | null;
  is_partner: boolean;
  active: boolean;
  notes: string | null;
  created_at: string;
};

function fmtRate(n: number | string | null): string {
  if (n == null || n === "") return "—";
  const num = typeof n === "string" ? Number(n) : n;
  return (
    new Intl.NumberFormat("fr-CA", {
      style: "currency",
      currency: "CAD",
      minimumFractionDigits: 2,
      maximumFractionDigits: 2
    }).format(num) + "/h"
  );
}

export default function EmployesPage() {
  const { onOpenSidebar } = useAppLayout();
  const [items, setItems] = useState<Employe[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const res = await authedFetch("/api/v1/employes?limit=500");
        if (!res.ok) throw new Error(`http_${res.status}`);
        const data = (await res.json()) as Employe[];
        if (!cancelled) setItems(data);
      } catch {
        if (!cancelled) setError("Impossible de charger les employés.");
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
      (x) =>
        x.full_name.toLowerCase().includes(q) ||
        (x.email || "").toLowerCase().includes(q) ||
        (x.phone || "").includes(q) ||
        (x.role || "").toLowerCase().includes(q)
    );
  }, [items, search]);

  return (
    <>
      <AppTopbar
        breadcrumbs={[{ label: "Ressources", href: "/app" }, { label: "Employés" }]}
        onOpenSidebar={onOpenSidebar}
        onSearch={setSearch}
        searchPlaceholder="Nom, courriel, rôle, téléphone…"
        rightSlot={
          <Link
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            href={"/app/employes/new" as any}
            className="btn-accent text-sm"
          >
            <Plus className="mr-1.5 h-4 w-4" /> Nouvel employé
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
            {filtered.map((e) => (
              <Card key={e.id} emp={e} />
            ))}
          </div>
        )}
      </div>
    </>
  );
}

function Card({ emp }: { emp: Employe }) {
  return (
    <Link
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      href={`/app/employes/${emp.id}` as any}
      className="group flex flex-col gap-2 rounded-xl border border-brand-800 bg-brand-900 p-5 transition hover:border-accent-500"
    >
      <div className="flex items-start justify-between">
        <div className="min-w-0">
          <h3 className="truncate text-base font-semibold text-white group-hover:text-accent-500">
            {emp.full_name}
          </h3>
          {emp.role ? (
            <p className="truncate text-xs text-white/60">{emp.role}</p>
          ) : null}
        </div>
        <div className="flex flex-col items-end gap-1">
          {!emp.active ? (
            <span className="badge badge-neutral">
              Inactif
            </span>
          ) : null}
          {emp.is_partner ? (
            <span className="rounded-md bg-accent-500/15 px-1.5 py-0.5 text-[10px] font-semibold text-accent-500">
              Partenaire
            </span>
          ) : null}
        </div>
      </div>

      <div className="mt-1 space-y-1 text-xs text-white/70">
        {emp.phone ? (
          <p className="flex items-center gap-1.5">
            <Phone className="h-3 w-3" /> <span>{formatPhone(emp.phone)}</span>
          </p>
        ) : null}
        {emp.email ? (
          <p className="flex items-center gap-1.5">
            <Mail className="h-3 w-3" /> <span className="truncate">{emp.email}</span>
          </p>
        ) : null}
      </div>

      <div className="mt-auto flex items-center justify-between pt-2 text-xs">
        <span className="text-white/50">Taux horaire</span>
        <span className="font-semibold text-white">{fmtRate(emp.hourly_rate)}</span>
      </div>
    </Link>
  );
}

function EmptyState() {
  return (
    <div className="empty-state mx-auto mt-16 max-w-md">
      <Users className="mx-auto h-10 w-10 text-accent-500" />
      <h2 className="mt-4 text-lg font-semibold text-white">Aucun employé</h2>
      <p className="mt-2 text-sm text-white/60">
        Ajoute ton équipe. Pour activer le punch mobile d&apos;un membre,
        utilise le même courriel que son compte de connexion.
      </p>
      <Link
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        href={"/app/employes/new" as any}
        className="btn-accent mt-6 inline-flex text-sm"
      >
        <Plus className="mr-1.5 h-4 w-4" /> Nouvel employé
      </Link>
    </div>
  );
}
