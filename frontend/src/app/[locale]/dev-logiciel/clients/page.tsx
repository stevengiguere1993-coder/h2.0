"use client";

import { useEffect, useMemo, useState } from "react";
import {
  Briefcase,
  LayoutGrid,
  List,
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
import { useDevlogLayout } from "../layout";
import { authedFetch } from "@/lib/auth";
import { Link } from "@/i18n/navigation";
import { formatPhone } from "@/lib/utils";

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

type TabKey = "clients" | "prospects" | "lost" | "all";
type ViewMode = "list" | "kanban";

const VIEW_PREF_KEY = "devlog_clients_view_v1";

// Kanban column configuration per tab. `group` is the Row property we
// bucket against (`kind` for Tous, `extra` for Clients/Prospects).
type ColumnDef = {
  id: string;
  label: string;
  dot: string;
  match: (r: Row) => boolean;
};

function columnsForTab(tab: TabKey): ColumnDef[] {
  if (tab === "clients") {
    return [
      {
        id: "all_clients",
        label: "Clients actifs",
        dot: "bg-emerald-400",
        match: (r) => r.kind === "client"
      }
    ];
  }
  if (tab === "prospects") {
    return [
      {
        id: "new",
        label: "Nouveaux",
        dot: "bg-emerald-400",
        match: (r) => r.kind === "prospect" && r.extra === "new"
      },
      {
        id: "contacted",
        label: "Suivi à faire",
        dot: "bg-amber-400",
        match: (r) => r.kind === "prospect" && r.extra === "contacted"
      },
      {
        id: "qualified",
        label: "Soumission en préparation",
        dot: "bg-fuchsia-400",
        match: (r) => r.kind === "prospect" && r.extra === "qualified"
      },
      {
        id: "quoted",
        label: "Soumission envoyée",
        dot: "bg-blue-400",
        match: (r) => r.kind === "prospect" && r.extra === "quoted"
      }
    ];
  }
  if (tab === "lost") {
    return [
      {
        id: "lost",
        label: "Perdu (refusé, sans projet)",
        dot: "bg-rose-500",
        match: (r) => r.kind === "prospect" && r.extra === "lost"
      }
    ];
  }
  // "all" — simpler: just prospects vs clients side by side.
  return [
    {
      id: "prospect",
      label: "Prospects",
      dot: "bg-sky-400",
      match: (r) => r.kind === "prospect"
    },
    {
      id: "client",
      label: "Clients",
      dot: "bg-emerald-400",
      match: (r) => r.kind === "client"
    }
  ];
}

export default function ClientsPage() {
  const { onOpenSidebar } = useDevlogLayout();
  const [clients, setClients] = useState<Client[]>([]);
  const [prospects, setProspects] = useState<Prospect[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [tab, setTab] = useState<TabKey>("clients");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [view, setView] = useState<ViewMode>("list");

  // Restore the view preference so the chosen mode survives reloads.
  useEffect(() => {
    if (typeof window === "undefined") return;
    const saved = window.localStorage.getItem(VIEW_PREF_KEY);
    if (saved === "list" || saved === "kanban") setView(saved);
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") return;
    try {
      window.localStorage.setItem(VIEW_PREF_KEY, view);
    } catch {
      /* ignore */
    }
  }, [view]);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const [cRes, pRes] = await Promise.all([
          authedFetch("/api/v1/devlog/clients?limit=500"),
          authedFetch("/api/v1/devlog/leads?limit=500")
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
    const allProspectRows: Row[] = prospects
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
    // Onglet Prospects = leads actifs (exclut les perdus)
    const activeProspectRows = allProspectRows.filter(
      (r) => r.extra !== "lost"
    );
    const lostProspectRows = allProspectRows.filter(
      (r) => r.extra === "lost"
    );
    if (tab === "clients") return clientRows;
    if (tab === "prospects") return activeProspectRows;
    if (tab === "lost") return lostProspectRows;
    return [...clientRows, ...allProspectRows];
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
          ? `/api/v1/devlog/clients/${id}`
          : `/api/v1/devlog/leads/${id}`;
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
          { label: "Développement logiciel", href: "/dev-logiciel" as any },
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
              href={"/dev-logiciel/clients/new" as any}
              className="inline-flex items-center justify-center rounded-xl bg-accent-500 px-5 py-3 font-semibold text-white transition hover:bg-accent-400 text-sm"
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

        <div className="mb-4 flex flex-wrap items-center gap-3">
          <div className="flex flex-1 rounded-lg border border-brand-800 bg-brand-900 p-1 text-sm">
            {(
              [
                {
                  id: "clients" as TabKey,
                  label: `Clients (${clients.length})`
                },
                {
                  id: "prospects" as TabKey,
                  label: `Prospects (${
                    prospects.filter(
                      (p) => p.status !== "won" && p.status !== "lost"
                    ).length
                  })`
                },
                {
                  id: "lost" as TabKey,
                  label: `Perdu (${
                    prospects.filter((p) => p.status === "lost").length
                  })`
                },
                {
                  id: "all" as TabKey,
                  label: `Tous (${
                    clients.length +
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

          {/* Liste ↔ Kanban toggle. Preference persisted in localStorage
              so the chosen view sticks across reloads. */}
          <div
            className="flex rounded-lg border border-brand-800 bg-brand-900 p-1"
            role="group"
            aria-label="Mode d'affichage"
          >
            <button
              type="button"
              onClick={() => setView("list")}
              aria-pressed={view === "list"}
              title="Vue liste"
              className={`rounded-md p-1.5 transition ${
                view === "list"
                  ? "bg-accent-500 text-brand-950"
                  : "text-white/70 hover:text-white"
              }`}
            >
              <List className="h-4 w-4" />
            </button>
            <button
              type="button"
              onClick={() => setView("kanban")}
              aria-pressed={view === "kanban"}
              title="Vue kanban"
              className={`rounded-md p-1.5 transition ${
                view === "kanban"
                  ? "bg-accent-500 text-brand-950"
                  : "text-white/70 hover:text-white"
              }`}
            >
              <LayoutGrid className="h-4 w-4" />
            </button>
          </div>
        </div>

        {loading ? (
          <div className="flex min-h-[40vh] items-center justify-center">
            <Loader2 className="h-6 w-6 animate-spin text-accent-500" />
          </div>
        ) : filtered.length === 0 ? (
          <EmptyState />
        ) : view === "kanban" ? (
          <KanbanBoard
            columns={columnsForTab(tab)}
            rows={filtered}
          />
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
                      className="h-4 w-4 accent-blue-500"
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
                      ? `/dev-logiciel/clients/${r.id}`
                      : `/dev-logiciel/leads/${r.id}`;
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
                          className="h-4 w-4 accent-blue-500"
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
                        {r.phone ? formatPhone(r.phone) : "—"}
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

function KanbanBoard({
  columns,
  rows
}: {
  columns: ColumnDef[];
  rows: Row[];
}) {
  // Bucket rows into columns; anything that doesn't match any column
  // lands in a fallback "Autres" column so nothing disappears.
  const buckets = columns.map((c) => ({
    col: c,
    cards: rows.filter((r) => c.match(r))
  }));
  const assigned = new Set(
    buckets.flatMap((b) => b.cards.map((r) => `${r.kind}:${r.id}`))
  );
  const orphans = rows.filter(
    (r) => !assigned.has(`${r.kind}:${r.id}`)
  );

  return (
    <div className="flex gap-4 overflow-x-auto pb-4">
      {buckets.map(({ col, cards }) => (
        <KanbanColumn
          key={col.id}
          label={col.label}
          dot={col.dot}
          count={cards.length}
        >
          {cards.map((r) => (
            <KanbanCard key={`${r.kind}:${r.id}`} row={r} />
          ))}
        </KanbanColumn>
      ))}
      {orphans.length > 0 ? (
        <KanbanColumn
          label="Autres"
          dot="bg-white/20"
          count={orphans.length}
        >
          {orphans.map((r) => (
            <KanbanCard key={`${r.kind}:${r.id}`} row={r} />
          ))}
        </KanbanColumn>
      ) : null}
    </div>
  );
}

function KanbanColumn({
  label,
  dot,
  count,
  children
}: {
  label: string;
  dot: string;
  count: number;
  children: React.ReactNode;
}) {
  const isEmpty =
    !children ||
    (Array.isArray(children) && children.filter(Boolean).length === 0);
  return (
    <div className="flex w-80 min-w-[320px] flex-shrink-0 flex-col rounded-xl border border-brand-800 bg-brand-900/60">
      <div className="flex items-center justify-between border-b border-brand-800 px-4 py-3">
        <div className="flex items-center gap-2">
          <span className={`h-2 w-2 rounded-full ${dot}`} />
          <h2 className="text-sm font-semibold text-white">{label}</h2>
        </div>
        <span className="rounded-md bg-brand-950 px-2 py-0.5 text-xs font-semibold text-white/70">
          {count}
        </span>
      </div>
      <div className="flex-1 space-y-3 p-3">
        {isEmpty ? (
          <p className="py-8 text-center text-xs text-white/40">
            Aucun élément
          </p>
        ) : (
          children
        )}
      </div>
    </div>
  );
}

function KanbanCard({ row: r }: { row: Row }) {
  const href =
    r.kind === "client" ? `/dev-logiciel/clients/${r.id}` : `/dev-logiciel/leads/${r.id}`;
  const Icon = r.kind === "client" ? UserCheck : Users;
  const iconClass =
    r.kind === "client"
      ? "bg-emerald-500/15 text-emerald-400"
      : "bg-sky-500/15 text-sky-400";
  return (
    <Link
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      href={href as any}
      className="block rounded-lg border border-brand-800 bg-brand-950 p-3 transition hover:border-accent-500"
    >
      <div className="flex items-start justify-between gap-2">
        <h3 className="truncate text-sm font-semibold text-white">
          {r.name}
        </h3>
        <span
          title={r.kind === "client" ? "Client" : "Prospect"}
          className={`flex-shrink-0 rounded-md p-1 ${iconClass}`}
        >
          <Icon className="h-3.5 w-3.5" />
        </span>
      </div>
      {r.phone ? (
        <p className="mt-1 flex items-center gap-1.5 text-xs text-white/60">
          <Phone className="h-3 w-3" />
          <span className="truncate">{formatPhone(r.phone)}</span>
        </p>
      ) : null}
      {r.email ? (
        <p className="mt-1 flex items-center gap-1.5 text-xs text-white/60">
          <Mail className="h-3 w-3" />
          <span className="truncate">{r.email}</span>
        </p>
      ) : null}
      {r.address ? (
        <p className="mt-1 flex items-center gap-1.5 text-xs text-white/50">
          <MapPin className="h-3 w-3" />
          <span className="truncate">{r.address}</span>
        </p>
      ) : null}
    </Link>
  );
}

function EmptyState() {
  return (
    <div className="empty-state mx-auto mt-16 max-w-md">
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
        href={"/dev-logiciel/clients/new" as any}
        className="inline-flex items-center justify-center rounded-xl bg-accent-500 px-5 py-3 font-semibold text-white transition hover:bg-accent-400 mt-6 inline-flex text-sm"
      >
        <Plus className="mr-1.5 h-4 w-4" /> Nouveau client
      </Link>
    </div>
  );
}
