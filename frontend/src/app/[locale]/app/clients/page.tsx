"use client";

import { useEffect, useMemo, useState } from "react";
import {
  Briefcase,
  Loader2,
  Mail,
  MapPin,
  Phone,
  Plus,
  Trash2,
  UserCheck,
  Users
} from "lucide-react";

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

type Prospect = {
  id: number;
  name: string;
  email: string;
  phone: string | null;
  address: string | null;
  status: string;
};

type Row = {
  kind: "client" | "prospect";
  id: number;
  name: string;
  email: string | null;
  phone: string | null;
  address: string | null;
  extra?: string;
};

type TabKey = "all" | "clients" | "prospects";

export default function ClientsPage() {
  const { onOpenSidebar } = useAppLayout();
  const [clients, setClients] = useState<Client[]>([]);
  const [prospects, setProspects] = useState<Prospect[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [tab, setTab] = useState<TabKey>("all");
  const [selected, setSelected] = useState<Set<string>>(new Set());

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const [cRes, pRes] = await Promise.all([
          authedFetch("/api/v1/clients?limit=500"),
          authedFetch("/api/v1/contact?limit=500")
        ]);
        if (!cRes.ok) throw new Error(`http_${cRes.status}`);
        if (!cancelled) setClients((await cRes.json()) as Client[]);
        if (pRes.ok && !cancelled)
          setProspects((await pRes.json()) as Prospect[]);
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

  const rows: Row[] = useMemo(() => {
    const clientRows: Row[] = clients.map((c) => ({
      kind: "client",
      id: c.id,
      name: c.name,
      email: c.email,
      phone: c.phone,
      address: c.address,
      extra: c.contact_request_id ? "Converti" : "Manuel"
    }));
    const prospectRows: Row[] = prospects
      .filter((p) => p.status !== "won")
      .map((p) => ({
        kind: "prospect",
        id: p.id,
        name: p.name,
        email: p.email,
        phone: p.phone,
        address: p.address,
        extra: p.status
      }));
    if (tab === "clients") return clientRows;
    if (tab === "prospects") return prospectRows;
    return [...clientRows, ...prospectRows];
  }, [clients, prospects, tab]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return rows;
    return rows.filter(
      (r) =>
        r.name.toLowerCase().includes(q) ||
        (r.email || "").toLowerCase().includes(q) ||
        (r.phone || "").includes(q) ||
        (r.address || "").toLowerCase().includes(q)
    );
  }, [rows, search]);

  function rowKey(r: Row): string {
    return `${r.kind}:${r.id}`;
  }

  function toggle(r: Row) {
    const k = rowKey(r);
    setSelected((s) => {
      const next = new Set(s);
      if (next.has(k)) next.delete(k);
      else next.add(k);
      return next;
    });
  }

  function toggleAll() {
    if (selected.size === filtered.length && filtered.length > 0) {
      setSelected(new Set());
    } else {
      setSelected(new Set(filtered.map(rowKey)));
    }
  }

  async function bulkDelete() {
    if (selected.size === 0) return;
    if (
      !confirm(
        `Supprimer définitivement ${selected.size} fiche${
          selected.size > 1 ? "s" : ""
        } ? Cette action est irréversible.`
      )
    )
      return;
    const keys = Array.from(selected);
    let failed = 0;
    for (const k of keys) {
      const [kind, id] = k.split(":");
      const url =
        kind === "client"
          ? `/api/v1/clients/${id}`
          : `/api/v1/contact/${id}`;
      try {
        const res = await authedFetch(url, { method: "DELETE" });
        if (!res.ok && res.status !== 204) failed += 1;
      } catch {
        failed += 1;
      }
    }
    // Optimistically remove the successful ones.
    setClients((xs) =>
      xs.filter((c) => !selected.has(`client:${c.id}`))
    );
    setProspects((xs) =>
      xs.filter((p) => !selected.has(`prospect:${p.id}`))
    );
    setSelected(new Set());
    if (failed > 0) setError(`${failed} suppression(s) ont échoué.`);
  }

  const allChecked =
    filtered.length > 0 && selected.size === filtered.length;
  const someChecked = selected.size > 0 && !allChecked;

  return (
    <>
      <AppTopbar
        breadcrumbs={[
          { label: "Construction", href: "/app" },
          { label: "Clients" }
        ]}
        onOpenSidebar={onOpenSidebar}
        onSearch={setSearch}
        searchPlaceholder="Nom, courriel, téléphone, adresse…"
        rightSlot={
          <div className="flex items-center gap-2">
            {selected.size > 0 ? (
              <button
                type="button"
                onClick={bulkDelete}
                className="inline-flex items-center gap-1 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs font-medium text-rose-200 hover:bg-rose-500/20"
              >
                <Trash2 className="h-3.5 w-3.5" /> Supprimer ({selected.size})
              </button>
            ) : null}
            <Link
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
              href={"/app/clients/new" as any}
              className="btn-accent text-sm"
            >
              <Plus className="mr-1.5 h-4 w-4" /> Nouveau client
            </Link>
          </div>
        }
      />

      <div className="p-4 lg:p-6">
        {error ? (
          <p className="mb-4 rounded-lg border border-rose-500/40 bg-rose-500/10 px-4 py-2 text-sm text-rose-300">
            {error}
          </p>
        ) : null}

        <div className="mb-4 flex rounded-lg border border-brand-800 bg-brand-900 p-1 text-sm">
          {(
            [
              { id: "all" as TabKey, label: `Tous (${clients.length + prospects.filter((p) => p.status !== "won").length})` },
              { id: "clients" as TabKey, label: `Clients (${clients.length})` },
              {
                id: "prospects" as TabKey,
                label: `Prospects (${
                  prospects.filter((p) => p.status !== "won").length
                })`
              }
            ]
          ).map((t) => (
            <button
              key={t.id}
              type="button"
              onClick={() => {
                setTab(t.id);
                setSelected(new Set());
              }}
              className={`flex-1 rounded-md px-3 py-1.5 font-semibold transition ${
                tab === t.id
                  ? "bg-accent-500 text-brand-950"
                  : "text-white/70 hover:text-white"
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>

        {loading ? (
          <div className="flex min-h-[40vh] items-center justify-center">
            <Loader2 className="h-6 w-6 animate-spin text-accent-500" />
          </div>
        ) : filtered.length === 0 ? (
          <EmptyState />
        ) : (
          <div className="overflow-hidden rounded-xl border border-brand-800 bg-brand-900">
            <table className="w-full text-sm">
              <thead className="border-b border-brand-800 text-xs uppercase tracking-wider text-white/50">
                <tr>
                  <th className="px-4 py-3 w-10">
                    <input
                      type="checkbox"
                      checked={allChecked}
                      ref={(el) => {
                        if (el) el.indeterminate = someChecked;
                      }}
                      onChange={toggleAll}
                      className="h-4 w-4 accent-accent-500"
                      aria-label="Tout sélectionner"
                    />
                  </th>
                  <th className="px-3 py-3 text-left">Type</th>
                  <th className="px-3 py-3 text-left">Nom</th>
                  <th className="px-3 py-3 text-left">Courriel</th>
                  <th className="px-3 py-3 text-left">Téléphone</th>
                  <th className="px-3 py-3"></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-brand-800">
                {filtered.map((r) => {
                  const k = rowKey(r);
                  const href =
                    r.kind === "client"
                      ? `/app/clients/${r.id}`
                      : `/app/crm/${r.id}`;
                  return (
                    <tr
                      key={k}
                      className="group transition hover:bg-brand-950/50"
                    >
                      <td className="px-4 py-3">
                        <input
                          type="checkbox"
                          checked={selected.has(k)}
                          onChange={() => toggle(r)}
                          className="h-4 w-4 accent-accent-500"
                          aria-label="Sélectionner"
                        />
                      </td>
                      <td className="px-3 py-3">
                        {r.kind === "client" ? (
                          <span
                            title="Client"
                            className="inline-flex rounded-md bg-emerald-500/15 p-1.5 text-emerald-400"
                          >
                            <UserCheck className="h-3.5 w-3.5" />
                          </span>
                        ) : (
                          <span
                            title="Prospect"
                            className="inline-flex rounded-md bg-sky-500/15 p-1.5 text-sky-400"
                          >
                            <Users className="h-3.5 w-3.5" />
                          </span>
                        )}
                      </td>
                      <td className="px-3 py-3">
                        <Link
                          // eslint-disable-next-line @typescript-eslint/no-explicit-any
                          href={href as any}
                          className="font-semibold text-white hover:text-accent-500"
                        >
                          {r.name}
                        </Link>
                      </td>
                      <td className="px-3 py-3 text-white/70">
                        {r.email || "—"}
                      </td>
                      <td className="px-3 py-3 text-white/70">
                        {r.phone || "—"}
                      </td>
                      <td className="px-3 py-3 text-right text-xs text-white/40">
                        {r.extra}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </>
  );
}

function EmptyState() {
  return (
    <div className="mx-auto mt-16 max-w-md rounded-2xl border border-dashed border-brand-800 bg-brand-900/40 p-10 text-center">
      <Briefcase className="mx-auto h-10 w-10 text-accent-500" />
      <h2 className="mt-4 text-lg font-semibold text-white">
        Aucune fiche
      </h2>
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
    </div>
  );
}
