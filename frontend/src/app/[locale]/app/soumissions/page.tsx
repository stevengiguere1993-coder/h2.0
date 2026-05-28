"use client";

import { useEffect, useMemo, useState } from "react";
import { FileText, Loader2, Plus, Trash2 } from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { useAppLayout } from "../layout";
import { authedFetch } from "@/lib/auth";
import { useConfirm } from "@/components/confirm-dialog";
import { Link } from "@/i18n/navigation";

type Soumission = {
  id: number;
  reference: string;
  contact_request_id: number | null;
  client_id: number | null;
  title: string;
  description: string | null;
  subtotal: number | null;
  tps: number | null;
  tvq: number | null;
  total: number | null;
  status: string;
  sent_at: string | null;
  accepted_at: string | null;
  valid_until: string | null;
  pdf_url: string | null;
  notes: string | null;
  property_address: string | null;
  kind?: "quote" | "contract";
  contract_data?: string | null;
  created_at: string;
};

/** Prix estimé interne d'un contrat (contract_data JSON) — affiché
 *  dans la liste à la place du total, le contrat n'ayant pas d'items. */
function contractEstimate(s: Soumission): number | null {
  if (s.kind !== "contract" || !s.contract_data) return null;
  try {
    const cd = JSON.parse(s.contract_data) as { prix_estime?: unknown };
    const v = Number(cd.prix_estime);
    return Number.isFinite(v) && v > 0 ? v : null;
  } catch {
    return null;
  }
}

type Column = { id: string; label: string; dot: string };

const COLUMNS: Column[] = [
  { id: "draft", label: "Brouillons", dot: "bg-white/40" },
  { id: "sent", label: "Envoyées", dot: "bg-blue-400" },
  { id: "accepted", label: "Acceptées", dot: "bg-emerald-400" },
  { id: "rejected", label: "Refusées", dot: "bg-rose-500" },
  { id: "expired", label: "Expirées", dot: "bg-amber-400" }
];

function fmtMoney(n: number | null): string {
  if (n == null) return "—";
  return new Intl.NumberFormat("fr-CA", {
    style: "currency",
    currency: "CAD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2
  }).format(n);
}

export default function SoumissionsPage() {
  const confirm = useConfirm();
  const { onOpenSidebar } = useAppLayout();
  const [items, setItems] = useState<Soumission[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [dragging, setDragging] = useState<number | null>(null);
  const [hoverCol, setHoverCol] = useState<string | null>(null);

  // Fallback : somme des items par soumission. Utilisé quand le total
  // persisté en DB est null/0 (cas legacy ou items ajoutés sans
  // recalcul du total). Peuplé en 1 batch après le chargement de la
  // liste.
  const [itemsTotals, setItemsTotals] = useState<Record<number, number>>({});
  // Maps de résolution pour les cartes : nom du client (client_id →
  // name), prospect lié (contact_request_id → {name, address}), et
  // adresse du projet créé depuis la soumission (soumission_id →
  // address). Servent à afficher adresse + nom sur chaque carte,
  // qu'elle vise un client ou un prospect.
  const [clientNames, setClientNames] = useState<Map<number, string>>(
    new Map()
  );
  const [prospectById, setProspectById] = useState<
    Map<number, { name: string; address: string | null }>
  >(new Map());
  const [projectAddrBySoumission, setProjectAddrBySoumission] = useState<
    Map<number, string>
  >(new Map());

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const [res, clientsRes, projectsRes, prospectsRes] =
          await Promise.all([
            authedFetch("/api/v1/soumissions?limit=200"),
            authedFetch("/api/v1/clients?limit=500"),
            authedFetch("/api/v1/projects?limit=500"),
            authedFetch("/api/v1/contact?limit=500")
          ]);
        if (!res.ok) throw new Error(`http_${res.status}`);
        const data = (await res.json()) as Soumission[];
        if (cancelled) return;
        setItems(data);

        if (clientsRes.ok) {
          const cs = (await clientsRes.json()) as Array<{
            id: number;
            name: string;
          }>;
          if (!cancelled) {
            setClientNames(new Map(cs.map((c) => [c.id, c.name])));
          }
        }
        if (prospectsRes.ok) {
          const ps = (await prospectsRes.json()) as Array<{
            id: number;
            name: string;
            address: string | null;
          }>;
          if (!cancelled) {
            setProspectById(
              new Map(
                ps.map((p) => [
                  p.id,
                  { name: p.name, address: p.address }
                ])
              )
            );
          }
        }
        if (projectsRes.ok) {
          const ps = (await projectsRes.json()) as Array<{
            id: number;
            address: string | null;
            soumission_id: number | null;
          }>;
          if (!cancelled) {
            const m = new Map<number, string>();
            for (const p of ps) {
              if (p.soumission_id && p.address) m.set(p.soumission_id, p.address);
            }
            setProjectAddrBySoumission(m);
          }
        }

        const ids = data
          .filter(
            (s) =>
              s.kind !== "contract" &&
              !(Number(s.total) > 0) &&
              !(Number(s.subtotal) > 0)
          )
          .map((s) => s.id);
        if (ids.length > 0) {
          const r = await authedFetch(
            "/api/v1/soumissions/items-totals",
            {
              method: "POST",
              body: JSON.stringify({ soumission_ids: ids })
            }
          );
          if (!cancelled && r.ok) {
            const j = (await r.json()) as {
              totals: Record<string, number>;
            };
            const map: Record<number, number> = {};
            for (const [k, v] of Object.entries(j.totals || {})) {
              const num = Number(v);
              if (Number.isFinite(num) && num > 0)
                map[Number(k)] = num;
            }
            setItemsTotals(map);
          }
        }
      } catch {
        if (!cancelled) setError("Impossible de charger les soumissions.");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, []);

  // Helper : montant à afficher pour une soumission. Pour un contrat,
  // c'est le prix estimé interne (pas d'items) ; pour un devis, total >
  // subtotal > somme des items.
  const amountFor = useMemo(() => {
    return (s: Soumission): number | null => {
      if (s.kind === "contract") return contractEstimate(s);
      if (Number(s.total) > 0) return Number(s.total);
      if (Number(s.subtotal) > 0) return Number(s.subtotal);
      const fallback = itemsTotals[s.id];
      if (Number.isFinite(fallback) && fallback > 0) return fallback;
      return null;
    };
  }, [itemsTotals]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return items;
    return items.filter(
      (s) =>
        s.title.toLowerCase().includes(q) ||
        s.reference.toLowerCase().includes(q) ||
        (s.description || "").toLowerCase().includes(q)
    );
  }, [items, search]);

  const byColumn = useMemo(() => {
    const map: Record<string, Soumission[]> = Object.fromEntries(
      COLUMNS.map((c) => [c.id, [] as Soumission[]])
    );
    for (const s of filtered) {
      const target = COLUMNS.find((c) => c.id === s.status) ? s.status : "draft";
      map[target].push(s);
    }
    return map;
  }, [filtered]);

  async function moveSoumission(id: number, newStatus: string) {
    const prev = items;
    setItems((xs) => xs.map((x) => (x.id === id ? { ...x, status: newStatus } : x)));
    try {
      // Use the dedicated status endpoint so the CRM prospect card
      // moves in sync (quoted / won / lost) — even on reversals or
      // mistakes.
      const res = await authedFetch(
        `/api/v1/soumissions/${id}/status`,
        {
          method: "PATCH",
          body: JSON.stringify({ status: newStatus })
        }
      );
      if (!res.ok) throw new Error();
    } catch {
      setItems(prev);
      setError("Mise à jour échouée.");
    }
  }

  async function deleteSoumission(id: number, ref: string) {
    if (!(await confirm(`Supprimer la soumission ${ref} ?`))) return;
    const prev = items;
    setItems((xs) => xs.filter((x) => x.id !== id));
    try {
      const res = await authedFetch(`/api/v1/soumissions/${id}`, {
        method: "DELETE"
      });
      if (!res.ok) throw new Error();
    } catch {
      setItems(prev);
      setError("Suppression échouée.");
    }
  }

  return (
    <>
      <AppTopbar
        breadcrumbs={[{ label: "Construction", href: "/app" }, { label: "Soumissions" }]}
        onOpenSidebar={onOpenSidebar}
        onSearch={setSearch}
        searchPlaceholder="Rechercher une soumission…"
        rightSlot={
          <Link
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            href={"/app/soumissions/new" as any}
            className="btn-accent text-sm"
          >
            <Plus className="mr-1.5 h-4 w-4" />
            Nouvelle soumission
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
                    const item = items.find((s) => s.id === dragging);
                    if (item && item.status !== col.id)
                      moveSoumission(dragging, col.id);
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
                      <span className="rounded-md bg-brand-950 px-2 py-0.5 text-xs font-semibold text-white/70">
                        {cards.length}
                      </span>
                    </div>
                    <span className="text-xs font-semibold text-emerald-300">
                      {fmtMoney(
                        cards.reduce(
                          (sum, s) => sum + (amountFor(s) || 0),
                          0
                        )
                      )}
                    </span>
                  </div>

                  <div className="flex-1 space-y-3 p-3">
                    {cards.length === 0 ? (
                      <p className="py-8 text-center text-xs text-white/40">
                        Aucune soumission
                      </p>
                    ) : (
                      cards.map((s) => {
                        const prospect = s.contact_request_id
                          ? prospectById.get(s.contact_request_id)
                          : undefined;
                        return (
                        <SoumissionCard
                          key={s.id}
                          soumission={s}
                          amount={amountFor(s)}
                          clientName={
                            (s.client_id
                              ? clientNames.get(s.client_id)
                              : undefined) ??
                            prospect?.name ??
                            null
                          }
                          projectAddress={
                            projectAddrBySoumission.get(s.id) ??
                            prospect?.address ??
                            null
                          }
                          dragging={dragging === s.id}
                          onDragStart={() => setDragging(s.id)}
                          onDragEnd={() => {
                            setDragging(null);
                            setHoverCol(null);
                          }}
                          onDelete={() => deleteSoumission(s.id, s.reference)}
                        />
                        );
                      })
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

function SoumissionCard({
  soumission: s,
  amount,
  clientName,
  projectAddress,
  dragging,
  onDragStart,
  onDragEnd,
  onDelete
}: {
  soumission: Soumission;
  amount: number | null;
  clientName: string | null;
  projectAddress: string | null;
  dragging: boolean;
  onDragStart: () => void;
  onDragEnd: () => void;
  onDelete: () => void;
}) {
  return (
    <div
      draggable
      onDragStart={onDragStart}
      onDragEnd={onDragEnd}
      className={`group relative cursor-grab rounded-lg border border-brand-800 bg-brand-950 p-3 transition hover:border-accent-500 active:cursor-grabbing ${
        dragging ? "opacity-40" : ""
      }`}
    >
      <button
        type="button"
        onClick={(e) => {
          e.preventDefault();
          e.stopPropagation();
          onDelete();
        }}
        aria-label="Supprimer"
        className="absolute right-2 top-2 rounded-md p-1 text-white/40 opacity-0 transition hover:bg-rose-500/15 hover:text-rose-400 group-hover:opacity-100"
      >
        <Trash2 className="h-3.5 w-3.5" />
      </button>

      <Link
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        href={`/app/soumissions/${s.id}` as any}
        className="block pr-6"
      >
        {/* Adresse du chantier (top) — toujours affichée, même pour
            un contrat ; fallback à l'adresse du projet puis au titre. */}
        <p className="line-clamp-2 text-sm font-semibold text-white">
          {s.property_address || projectAddress || s.title}
        </p>
        {/* Nom du client (sous-titre) — taille bumpée pour
            lecture plus rapide. */}
        {clientName ? (
          <p className="mt-1 truncate text-xs font-medium text-white/75">
            {clientName}
          </p>
        ) : null}
        {/* Montant : total du devis, ou prix estimé interne pour un
            contrat. */}
        <p className="mt-2 text-sm font-bold text-white">
          {fmtMoney(amount)}
          {s.kind === "contract" ? (
            <span className="ml-1.5 text-[10px] font-semibold uppercase tracking-wider text-white/40">
              estimé
            </span>
          ) : null}
        </p>
        {/* Numéro de la soumission, en bas — bumpé en text-xs pour
            la lisibilité. */}
        <div className="mt-1.5 flex items-center justify-between">
          <span className="text-xs font-semibold uppercase tracking-wider text-accent-500">
            {s.reference}
            {s.kind === "contract" ? (
              <span className="ml-1.5 rounded bg-indigo-500/15 px-1 py-0.5 text-[9px] text-indigo-300">
                Contrat
              </span>
            ) : null}
          </span>
          <span className="text-[10px] text-white/40">
            {new Date(s.created_at).toLocaleDateString("fr-CA", {
              month: "short",
              day: "2-digit"
            })}
          </span>
        </div>
      </Link>
    </div>
  );
}

function EmptyState() {
  return (
    <div className="mx-auto mt-16 max-w-md rounded-2xl border border-dashed border-brand-800 bg-brand-900/40 p-10 text-center">
      <FileText className="mx-auto h-10 w-10 text-accent-500" />
      <h2 className="mt-4 text-lg font-semibold text-white">
        Aucune soumission
      </h2>
      <p className="mt-2 text-sm text-white/60">
        Créez votre première soumission pour un prospect ou un client existant.
      </p>
      <Link
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        href={"/app/soumissions/new" as any}
        className="btn-accent mt-6 inline-flex text-sm"
      >
        <Plus className="mr-1.5 h-4 w-4" />
        Nouvelle soumission
      </Link>
    </div>
  );
}
