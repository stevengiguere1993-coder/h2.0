"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { ClipboardCheck, HardHat, Loader2, Plus, Wrench } from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { useAppLayout } from "../layout";
import { authedFetch } from "@/lib/auth";
import { Link, useRouter } from "@/i18n/navigation";

type Bon = {
  id: number;
  reference: string;
  title: string;
  description: string | null;
  project_id: number | null;
  client_id: number | null;
  amount: number | string | null;
  address: string | null;
  bon_type: string;
  status: string;
  kind: string | null;
  owner_entreprise_id: number | null;
  immeuble_id: number | null;
  logement_id: number | null;
  executant_type: string | null;
  sous_traitant_id: number | null;
  marge_pct: number | string | null;
  sent_at: string | null;
  signed_at: string | null;
  signed_by_name: string | null;
  created_at: string;
};

type Column = { id: string; label: string; dot: string };
// Cycle du bon de travail INTERNE (entretien de nos immeubles).
const COLUMNS: Column[] = [
  { id: "draft", label: "Brouillon", dot: "bg-white/40" },
  { id: "accepte_a_planifier", label: "Accepté à planifier", dot: "bg-amber-400" },
  { id: "planifie", label: "Planifié", dot: "bg-blue-400" },
  {
    id: "complete_a_refacturer",
    label: "Complété · à refacturer",
    dot: "bg-violet-400"
  },
  { id: "facture", label: "Facturé", dot: "bg-emerald-400" },
  { id: "cancelled", label: "Annulé", dot: "bg-white/20" }
];

function money(n: number | string | null): string {
  if (n == null || n === "") return "—";
  const num = typeof n === "string" ? Number(n) : n;
  return new Intl.NumberFormat("fr-CA", {
    style: "currency",
    currency: "CAD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2
  }).format(num);
}

export default function BonsPage() {
  const { onOpenSidebar } = useAppLayout();
  const router = useRouter();
  const [items, setItems] = useState<Bon[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [dragOverCol, setDragOverCol] = useState<string | null>(null);
  const dragIdRef = useRef<number | null>(null);

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

  // Le board ne montre que les bons INTERNES (entretien de nos immeubles).
  // Les bons « construction » signés client restent en legacy ailleurs.
  const internal = useMemo(
    () => items.filter((b) => (b.kind ?? "construction") === "interne"),
    [items]
  );

  // Anciens bons construction (signature client) — affichés à part pour ne
  // jamais les perdre de vue. Filtrés par la recherche aussi.
  const legacy = useMemo(() => {
    const all = items.filter(
      (b) => (b.kind ?? "construction") !== "interne"
    );
    const q = search.trim().toLowerCase();
    if (!q) return all;
    return all.filter(
      (b) =>
        b.reference.toLowerCase().includes(q) ||
        b.title.toLowerCase().includes(q) ||
        (b.address || "").toLowerCase().includes(q)
    );
  }, [items, search]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return internal;
    return internal.filter(
      (b) =>
        b.reference.toLowerCase().includes(q) ||
        b.title.toLowerCase().includes(q) ||
        (b.address || "").toLowerCase().includes(q) ||
        (b.description || "").toLowerCase().includes(q)
    );
  }, [internal, search]);

  const byColumn = useMemo(() => {
    const map: Record<string, Bon[]> = Object.fromEntries(
      COLUMNS.map((c) => [c.id, [] as Bon[]])
    );
    for (const b of filtered) {
      const target = COLUMNS.find((c) => c.id === b.status) ? b.status : "draft";
      map[target].push(b);
    }
    const cmp = (a: Bon, b: Bon) => {
      const byAddr = (a.address || "~").localeCompare(b.address || "~", "fr", {
        sensitivity: "base"
      });
      if (byAddr !== 0) return byAddr;
      return a.reference.localeCompare(b.reference, "fr");
    };
    for (const id of Object.keys(map)) map[id].sort(cmp);
    return map;
  }, [filtered]);

  async function moveTo(bonId: number, status: string) {
    const current = items.find((b) => b.id === bonId);
    if (!current || current.status === status) return;
    const prevStatus = current.status;
    // Optimiste.
    setItems((prev) =>
      prev.map((b) => (b.id === bonId ? { ...b, status } : b))
    );
    try {
      const res = await authedFetch(`/api/v1/bons-travail/${bonId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status })
      });
      if (!res.ok) throw new Error(`http_${res.status}`);
    } catch {
      // Annule le déplacement optimiste.
      setItems((prev) =>
        prev.map((b) => (b.id === bonId ? { ...b, status: prevStatus } : b))
      );
      setError("Échec du déplacement du bon. Réessaie.");
    }
  }

  return (
    <>
      <AppTopbar
        breadcrumbs={[
          { label: "Construction", href: "/app" },
          { label: "Bons de travail" }
        ]}
        onOpenSidebar={onOpenSidebar}
        onSearch={setSearch}
        searchPlaceholder="Référence, titre, adresse…"
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
        <p className="mb-4 rounded-lg border border-brand-800 bg-brand-900/60 px-4 py-3 text-xs text-white/60">
          <strong className="text-white/80">À quoi ça sert ?</strong>{" "}
          Un bon de travail gère un travail d&apos;entretien sur{" "}
          <strong className="text-white/80">un de nos immeubles</strong>{" "}
          (compagnie → immeuble → appartement). On assigne nos hommes à
          tout faire ou un sous-traitant, on suit l&apos;avancement, puis on
          refacture les heures et le matériel à la compagnie propriétaire.
          Glisse une carte d&apos;une colonne à l&apos;autre pour changer son
          statut.
        </p>

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
          <>
            {internal.length === 0 ? (
              <p className="mb-6 rounded-lg border border-dashed border-brand-800 bg-brand-900/40 px-4 py-6 text-center text-sm text-white/50">
                Aucun bon d&apos;entretien interne pour l&apos;instant. Crée-en
                un avec « Nouveau bon », ou retrouve tes anciens bons plus bas.
              </p>
            ) : (
              <div className="flex gap-4 overflow-x-auto pb-4">
                {COLUMNS.map((col) => {
              const cards = byColumn[col.id] || [];
              const isOver = dragOverCol === col.id;
              return (
                <div
                  key={col.id}
                  className={`flex w-80 min-w-[320px] flex-shrink-0 flex-col rounded-xl border bg-brand-900/60 transition ${
                    isOver
                      ? "border-accent-500 ring-1 ring-accent-500/40"
                      : "border-brand-800"
                  }`}
                  onDragOver={(e) => {
                    e.preventDefault();
                    if (dragOverCol !== col.id) setDragOverCol(col.id);
                  }}
                  onDragLeave={() => {
                    if (dragOverCol === col.id) setDragOverCol(null);
                  }}
                  onDrop={(e) => {
                    e.preventDefault();
                    setDragOverCol(null);
                    const id = dragIdRef.current;
                    dragIdRef.current = null;
                    if (id != null) moveTo(id, col.id);
                  }}
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
                      cards.map((b) => {
                        const sousTraitant =
                          (b.executant_type ?? "") === "sous_traitant";
                        return (
                          <div
                            key={b.id}
                            role="button"
                            tabIndex={0}
                            draggable
                            onDragStart={(e) => {
                              dragIdRef.current = b.id;
                              e.dataTransfer.effectAllowed = "move";
                            }}
                            onDragEnd={() => {
                              dragIdRef.current = null;
                              setDragOverCol(null);
                            }}
                            onClick={() =>
                              router.push(
                                // eslint-disable-next-line @typescript-eslint/no-explicit-any
                                `/app/bons/${b.id}` as any
                              )
                            }
                            onKeyDown={(e) => {
                              if (e.key === "Enter")
                                router.push(
                                  // eslint-disable-next-line @typescript-eslint/no-explicit-any
                                  `/app/bons/${b.id}` as any
                                );
                            }}
                            className="block cursor-pointer rounded-lg border border-brand-800 bg-brand-950 p-3 transition hover:border-accent-500"
                          >
                            <h3 className="truncate text-sm font-semibold text-white">
                              {b.address || "Adresse non renseignée"}
                            </h3>
                            <p className="mt-0.5 truncate text-xs text-white/70">
                              {b.title}
                            </p>
                            <p className="mt-0.5 truncate text-[11px] text-white/40">
                              {b.reference}
                            </p>
                            <div className="mt-2 flex items-center justify-between text-xs">
                              <span
                                className={`inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[11px] font-medium ${
                                  sousTraitant
                                    ? "bg-orange-500/15 text-orange-300"
                                    : "bg-sky-500/15 text-sky-300"
                                }`}
                              >
                                {sousTraitant ? (
                                  <HardHat className="h-3 w-3" />
                                ) : (
                                  <Wrench className="h-3 w-3" />
                                )}
                                {sousTraitant ? "Sous-traitant" : "Nos hommes"}
                              </span>
                              <span className="font-semibold text-white">
                                {money(b.amount)}
                              </span>
                            </div>
                          </div>
                        );
                      })
                    )}
                  </div>
                </div>
              );
                })}
              </div>
            )}
            {legacy.length > 0 ? (
              <LegacyBons
                bons={legacy}
                onOpen={(id) =>
                  // eslint-disable-next-line @typescript-eslint/no-explicit-any
                  router.push(`/app/bons/${id}` as any)
                }
              />
            ) : null}
          </>
        )}
      </div>
    </>
  );
}

const LEGACY_STATUS: Record<string, { label: string; cls: string }> = {
  draft: { label: "Brouillon", cls: "bg-white/10 text-white/70" },
  sent: { label: "Envoyé", cls: "bg-blue-500/20 text-blue-300" },
  signed: { label: "Signé", cls: "bg-emerald-500/20 text-emerald-300" },
  cancelled: { label: "Annulé", cls: "bg-white/5 text-white/50" }
};

function LegacyBons({
  bons,
  onOpen
}: {
  bons: Bon[];
  onOpen: (id: number) => void;
}) {
  return (
    <section className="mt-8">
      <h2 className="text-lg font-bold text-white">
        Anciens bons de travail (construction)
      </h2>
      <p className="mt-1 text-xs text-white/50">
        Bons signés / envoyés au client avant la refonte. Toujours
        accessibles — clique pour ouvrir la fiche.
      </p>
      <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {bons.map((b) => {
          const st = LEGACY_STATUS[b.status] || {
            label: b.status,
            cls: "bg-white/10 text-white/70"
          };
          return (
            <button
              key={b.id}
              type="button"
              onClick={() => onOpen(b.id)}
              className="block rounded-lg border border-brand-800 bg-brand-950 p-3 text-left transition hover:border-accent-500"
            >
              <div className="flex items-start justify-between gap-2">
                <h3 className="min-w-0 truncate text-sm font-semibold text-white">
                  {b.address || b.title}
                </h3>
                <span
                  className={`flex-shrink-0 rounded-md px-1.5 py-0.5 text-[10px] font-semibold ${st.cls}`}
                >
                  {st.label}
                </span>
              </div>
              <p className="mt-0.5 truncate text-xs text-white/60">{b.title}</p>
              <p className="mt-0.5 truncate text-[11px] text-white/40">
                {b.reference} · {money(b.amount)}
              </p>
            </button>
          );
        })}
      </div>
    </section>
  );
}

function Empty() {
  return (
    <div className="mx-auto mt-16 max-w-md rounded-2xl border border-dashed border-brand-800 bg-brand-900/40 p-10 text-center">
      <ClipboardCheck className="mx-auto h-10 w-10 text-accent-500" />
      <h2 className="mt-4 text-lg font-semibold text-white">
        Aucun bon de travail
      </h2>
      <p className="mt-2 text-sm text-white/60">
        Les bons de travail servent à gérer l&apos;entretien de nos immeubles :
        on rattache une compagnie, un immeuble et un appartement, on assigne
        l&apos;exécutant, puis on refacture.
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
