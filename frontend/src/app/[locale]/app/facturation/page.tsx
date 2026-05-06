"use client";

import { useEffect, useMemo, useState } from "react";
import { DollarSign, Loader2, Plus } from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { useAppLayout } from "../layout";
import { authedFetch } from "@/lib/auth";
import { Link } from "@/i18n/navigation";

type Facture = {
  id: number;
  reference: string;
  client_id: number | null;
  project_id: number | null;
  subtotal: number | string | null;
  tps: number | string | null;
  tvq: number | string | null;
  total: number | string | null;
  balance: number | string | null;
  status: string;
  issued_at: string | null;
  due_at: string | null;
  paid_at: string | null;
  qbo_invoice_id: string | null;
  qbo_doc_number: string | null;
  created_at: string;
};

type Column = { id: string; label: string; dot: string };

const COLUMNS: Column[] = [
  { id: "draft", label: "Brouillons", dot: "bg-white/40" },
  { id: "sent", label: "Envoyées", dot: "bg-blue-400" },
  { id: "paid", label: "Payées", dot: "bg-emerald-400" },
  { id: "overdue", label: "En retard", dot: "bg-rose-500" },
  { id: "void", label: "Annulées", dot: "bg-white/20" }
];

function fmtMoney(n: number | string | null): string {
  if (n == null || n === "") return "—";
  const num = typeof n === "string" ? Number(n) : n;
  return new Intl.NumberFormat("fr-CA", {
    style: "currency",
    currency: "CAD",
    maximumFractionDigits: 0
  }).format(num);
}

function fmtDate(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("fr-CA", {
    day: "2-digit",
    month: "short"
  });
}

export default function FacturationPage() {
  const { onOpenSidebar } = useAppLayout();
  const [items, setItems] = useState<Facture[]>([]);
  const [clientNames, setClientNames] = useState<Map<number, string>>(
    new Map()
  );
  const [projectNames, setProjectNames] = useState<Map<number, string>>(
    new Map()
  );
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [dragging, setDragging] = useState<number | null>(null);
  const [hoverCol, setHoverCol] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const [fRes, cRes, pRes] = await Promise.all([
          authedFetch("/api/v1/factures?limit=500"),
          authedFetch("/api/v1/clients?limit=500"),
          authedFetch("/api/v1/projects?limit=500")
        ]);
        if (!fRes.ok) throw new Error(`http_${fRes.status}`);
        const data = (await fRes.json()) as Facture[];
        const cs = cRes.ok
          ? ((await cRes.json()) as Array<{ id: number; name: string }>)
          : [];
        const ps = pRes.ok
          ? ((await pRes.json()) as Array<{ id: number; name: string }>)
          : [];
        if (!cancelled) {
          setItems(data);
          setClientNames(new Map(cs.map((c) => [c.id, c.name])));
          setProjectNames(new Map(ps.map((p) => [p.id, p.name])));
        }
      } catch {
        if (!cancelled) setError("Impossible de charger les factures.");
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
    return items.filter((f) => {
      const cn = f.client_id ? (clientNames.get(f.client_id) || "") : "";
      const pn = f.project_id ? (projectNames.get(f.project_id) || "") : "";
      return (
        f.reference.toLowerCase().includes(q) ||
        String(f.total || "").includes(q) ||
        cn.toLowerCase().includes(q) ||
        pn.toLowerCase().includes(q)
      );
    });
  }, [items, search, clientNames, projectNames]);

  const byColumn = useMemo(() => {
    const map: Record<string, Facture[]> = Object.fromEntries(
      COLUMNS.map((c) => [c.id, [] as Facture[]])
    );
    for (const f of filtered) {
      const target = COLUMNS.find((c) => c.id === f.status) ? f.status : "draft";
      map[target].push(f);
    }
    return map;
  }, [filtered]);

  async function move(id: number, newStatus: string) {
    const prev = items;
    setItems((xs) => xs.map((x) => (x.id === id ? { ...x, status: newStatus } : x)));
    try {
      const res = await authedFetch(`/api/v1/factures/${id}`, {
        method: "PATCH",
        body: JSON.stringify({ status: newStatus })
      });
      if (!res.ok) throw new Error();
    } catch {
      setItems(prev);
      setError("Mise à jour du statut échouée.");
    }
  }

  return (
    <>
      <AppTopbar
        breadcrumbs={[{ label: "Construction", href: "/app" }, { label: "Facturation" }]}
        onOpenSidebar={onOpenSidebar}
        onSearch={setSearch}
        searchPlaceholder="Référence, montant…"
        rightSlot={
          <Link
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            href={"/app/facturation/new" as any}
            className="btn-accent text-sm"
          >
            <Plus className="mr-1.5 h-4 w-4" /> Nouvelle facture
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
          <div className="flex min-h-[50vh] items-center justify-center">
            <Loader2 className="h-6 w-6 animate-spin text-accent-500" />
          </div>
        ) : items.length === 0 ? (
          <EmptyState />
        ) : (
          <div className="flex gap-4 overflow-x-auto pb-4">
            {COLUMNS.map((col) => {
              const cards = byColumn[col.id] || [];
              const isHover = hoverCol === col.id;
              return (
                <div
                  key={col.id}
                  onDragOver={(e) => {
                    e.preventDefault();
                    setHoverCol(col.id);
                  }}
                  onDragLeave={() =>
                    setHoverCol((h) => (h === col.id ? null : h))
                  }
                  onDrop={() => {
                    if (dragging == null) return;
                    const f = items.find((x) => x.id === dragging);
                    if (f && f.status !== col.id) move(dragging, col.id);
                    setDragging(null);
                    setHoverCol(null);
                  }}
                  className={`flex w-80 min-w-[320px] flex-shrink-0 flex-col rounded-xl border bg-brand-900/60 ${
                    isHover
                      ? "border-accent-500 bg-brand-900"
                      : "border-brand-800"
                  }`}
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
                        Aucune facture
                      </p>
                    ) : (
                      cards.map((f) => (
                        <Card
                          key={f.id}
                          fa={f}
                          clientName={
                            f.client_id ? clientNames.get(f.client_id) ?? null : null
                          }
                          projectName={
                            f.project_id ? projectNames.get(f.project_id) ?? null : null
                          }
                          dragging={dragging === f.id}
                          onDragStart={() => setDragging(f.id)}
                          onDragEnd={() => {
                            setDragging(null);
                            setHoverCol(null);
                          }}
                        />
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

function Card({
  fa,
  clientName,
  projectName,
  dragging,
  onDragStart,
  onDragEnd
}: {
  fa: Facture;
  clientName: string | null;
  projectName: string | null;
  dragging: boolean;
  onDragStart: () => void;
  onDragEnd: () => void;
}) {
  return (
    <Link
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      href={`/app/facturation/${fa.id}` as any}
      draggable
      onDragStart={onDragStart}
      onDragEnd={onDragEnd}
      className={`block rounded-lg border bg-brand-950 p-3 transition ${
        dragging
          ? "border-accent-500 opacity-60"
          : "border-brand-800 hover:border-accent-500"
      }`}
    >
      <h3 className="truncate text-sm font-semibold text-white">
        {fa.reference}
      </h3>
      {clientName || projectName ? (
        <p className="mt-0.5 truncate text-[11px] text-white/60">
          {clientName ? clientName : ""}
          {clientName && projectName ? " · " : ""}
          {projectName ? projectName : ""}
        </p>
      ) : null}
      <div className="mt-1 flex items-center justify-between text-xs">
        <span className="text-white/50">
          {fa.due_at ? `Échéance ${fmtDate(fa.due_at)}` : fmtDate(fa.created_at)}
        </span>
        <span className="font-semibold text-white">{fmtMoney(fa.total)}</span>
      </div>
      {fa.qbo_invoice_id ? (
        <p className="mt-2 text-[10px] text-emerald-400">
          QBO Invoice #{fa.qbo_doc_number || fa.qbo_invoice_id}
        </p>
      ) : null}
    </Link>
  );
}

function EmptyState() {
  return (
    <div className="mx-auto mt-16 max-w-md rounded-2xl border border-dashed border-brand-800 bg-brand-900/40 p-10 text-center">
      <DollarSign className="mx-auto h-10 w-10 text-accent-500" />
      <h2 className="mt-4 text-lg font-semibold text-white">Aucune facture</h2>
      <p className="mt-2 text-sm text-white/60">
        Crée une facture directement, ou depuis un projet actif avec le
        bouton « Créer une facture » sur sa fiche.
      </p>
      <Link
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        href={"/app/facturation/new" as any}
        className="btn-accent mt-6 inline-flex text-sm"
      >
        <Plus className="mr-1.5 h-4 w-4" /> Nouvelle facture
      </Link>
    </div>
  );
}
