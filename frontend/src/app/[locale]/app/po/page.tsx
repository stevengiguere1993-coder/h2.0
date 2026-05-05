"use client";

import { useEffect, useMemo, useState } from "react";
import { ClipboardCheck, Loader2, Plus, Search } from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { Link, useRouter } from "@/i18n/navigation";
import { useAppLayout } from "../layout";
import { authedFetch } from "@/lib/auth";

type PurchaseOrder = {
  id: number;
  reference: string;
  fournisseur_id: number | null;
  project_id: number | null;
  assigned_employe_id: number | null;
  description: string | null;
  amount_max: number | string | null;
  payment_method: string | null;
  status: string;
  sent_at: string | null;
  created_at: string;
};

type Project = { id: number; name: string };
type Fournisseur = { id: number; name: string };
type Employe = { id: number; full_name: string };

const STATUS_LABELS: Record<string, string> = {
  draft: "Planifié",
  sent: "PO envoyé",
  fulfilled: "Achat créé",
  cancelled: "Annulé"
};

const STATUS_BG: Record<string, string> = {
  draft: "bg-white/10 text-white/70 border-white/20",
  sent: "bg-blue-500/15 text-blue-300 border-blue-500/30",
  fulfilled: "bg-emerald-500/15 text-emerald-300 border-emerald-500/30",
  cancelled: "bg-rose-500/15 text-rose-300 border-rose-500/30"
};

function fmtMoney(n: number | string | null): string {
  if (n == null || n === "") return "—";
  const v = typeof n === "string" ? Number(n) : n;
  return new Intl.NumberFormat("fr-CA", {
    style: "currency",
    currency: "CAD",
    maximumFractionDigits: 0
  }).format(v);
}

export default function PurchaseOrdersListPage() {
  const { onOpenSidebar } = useAppLayout();
  const router = useRouter();
  const [items, setItems] = useState<PurchaseOrder[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [fournisseurs, setFournisseurs] = useState<Fournisseur[]>([]);
  const [employes, setEmployes] = useState<Employe[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [tab, setTab] = useState<
    "all" | "draft" | "sent" | "fulfilled"
  >("all");

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      try {
        const [poRes, prRes, frRes, eRes] = await Promise.all([
          authedFetch("/api/v1/purchase-orders?limit=500"),
          authedFetch("/api/v1/projects?limit=500"),
          authedFetch("/api/v1/fournisseurs?limit=500"),
          authedFetch("/api/v1/employes?limit=500&volet=construction")
        ]);
        if (!poRes.ok) throw new Error();
        if (cancelled) return;
        setItems((await poRes.json()) as PurchaseOrder[]);
        if (prRes.ok) setProjects((await prRes.json()) as Project[]);
        if (frRes.ok)
          setFournisseurs((await frRes.json()) as Fournisseur[]);
        if (eRes.ok) setEmployes((await eRes.json()) as Employe[]);
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

  const projById = useMemo(() => {
    const m = new Map<number, Project>();
    projects.forEach((p) => m.set(p.id, p));
    return m;
  }, [projects]);
  const frById = useMemo(() => {
    const m = new Map<number, Fournisseur>();
    fournisseurs.forEach((f) => m.set(f.id, f));
    return m;
  }, [fournisseurs]);
  const empById = useMemo(() => {
    const m = new Map<number, Employe>();
    employes.forEach((e) => m.set(e.id, e));
    return m;
  }, [employes]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return items.filter((po) => {
      if (tab !== "all" && po.status !== tab) return false;
      if (
        q &&
        !po.reference.toLowerCase().includes(q) &&
        !(po.description || "").toLowerCase().includes(q)
      ) {
        return false;
      }
      return true;
    });
  }, [items, search, tab]);

  return (
    <>
      <AppTopbar
        breadcrumbs={[
          { label: "Construction", href: "/app" },
          { label: "Bons de commande (PO)" }
        ]}
        onOpenSidebar={onOpenSidebar}
        rightSlot={
          <Link
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            href={"/app/po/new" as any}
            className="btn-accent text-sm"
          >
            <Plus className="mr-1.5 h-4 w-4" />
            Nouveau PO
          </Link>
        }
      />

      <div className="p-4 lg:p-6">
        <h1 className="text-2xl font-bold text-white">
          Bons de commande
        </h1>
        <p className="mt-1 text-sm text-white/60">
          Documents d&apos;autorisation interne — pas d&apos;impact
          comptable. Convertis un PO en achat quand l&apos;employé
          revient avec sa facture fournisseur.
        </p>

        {error ? (
          <p className="mt-4 rounded-lg border border-rose-500/40 bg-rose-500/10 px-4 py-2 text-sm text-rose-300">
            {error}
          </p>
        ) : null}

        <div className="mt-5 flex flex-wrap gap-1 border-b border-brand-800">
          {(
            [
              { value: "all" as const, label: "Tous" },
              { value: "draft" as const, label: "Planifiés" },
              { value: "sent" as const, label: "PO envoyés" },
              { value: "fulfilled" as const, label: "Convertis en achat" }
            ]
          ).map((t) => {
            const count =
              t.value === "all"
                ? items.length
                : items.filter((po) => po.status === t.value).length;
            const active = tab === t.value;
            return (
              <button
                key={t.value}
                type="button"
                onClick={() => setTab(t.value)}
                className={`relative whitespace-nowrap px-4 py-2.5 text-sm transition ${
                  active
                    ? "font-semibold text-accent-500"
                    : "text-white/60 hover:text-white"
                }`}
              >
                {t.label}
                <span
                  className={`ml-1.5 inline-flex h-4 min-w-[16px] items-center justify-center rounded-full px-1 text-[10px] font-semibold ${
                    active
                      ? "bg-accent-500/20 text-accent-300"
                      : "bg-white/5 text-white/50"
                  }`}
                >
                  {count}
                </span>
                {active ? (
                  <span className="absolute inset-x-3 -bottom-px h-0.5 rounded-t bg-accent-500" />
                ) : null}
              </button>
            );
          })}
        </div>

        <div className="mt-4">
          <div className="relative max-w-md">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-white/40" />
            <input
              type="search"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Rechercher (PO-0027, description…)"
              className="input pl-8"
            />
          </div>
        </div>

        {loading ? (
          <div className="mt-8 flex items-center justify-center">
            <Loader2 className="h-6 w-6 animate-spin text-accent-500" />
          </div>
        ) : filtered.length === 0 ? (
          <div className="mt-8 rounded-2xl border border-dashed border-brand-800 bg-brand-900/40 px-6 py-14 text-center">
            <ClipboardCheck className="mx-auto h-8 w-8 text-white/30" />
            <p className="mt-3 text-sm text-white/60">
              Aucun bon de commande.
            </p>
            <Link
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
              href={"/app/po/new" as any}
              className="mt-3 inline-block text-accent-400 underline decoration-dotted hover:text-accent-300"
            >
              Créer le premier PO →
            </Link>
          </div>
        ) : (
          <div className="mt-4 overflow-hidden rounded-xl border border-brand-800 bg-brand-900">
            <table className="w-full text-sm">
              <thead className="border-b border-brand-800 bg-brand-950/50 text-left text-[11px] uppercase tracking-wider text-white/50">
                <tr>
                  <th className="px-3 py-2">PO</th>
                  <th className="px-3 py-2">Fournisseur</th>
                  <th className="px-3 py-2">Projet</th>
                  <th className="px-3 py-2">Assigné à</th>
                  <th className="px-3 py-2 text-right">Max autorisé</th>
                  <th className="px-3 py-2 text-center">Statut</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-brand-800">
                {filtered.map((po) => {
                  const proj = po.project_id
                    ? projById.get(po.project_id)
                    : null;
                  const fr = po.fournisseur_id
                    ? frById.get(po.fournisseur_id)
                    : null;
                  const emp = po.assigned_employe_id
                    ? empById.get(po.assigned_employe_id)
                    : null;
                  return (
                    <tr
                      key={po.id}
                      onClick={() =>
                        router.push(
                          // eslint-disable-next-line @typescript-eslint/no-explicit-any
                          `/app/po/${po.id}` as any
                        )
                      }
                      className="cursor-pointer hover:bg-brand-800/30"
                    >
                      <td className="px-3 py-2">
                        <Link
                          // eslint-disable-next-line @typescript-eslint/no-explicit-any
                          href={`/app/po/${po.id}` as any}
                          onClick={(e) => e.stopPropagation()}
                          className="font-mono text-accent-400 hover:underline"
                        >
                          {po.reference}
                        </Link>
                      </td>
                      <td className="px-3 py-2 text-white/80">
                        {fr?.name || "—"}
                      </td>
                      <td className="px-3 py-2 text-white/80">
                        {proj?.name || (
                          <span className="text-white/40">
                            (frais généraux)
                          </span>
                        )}
                      </td>
                      <td className="px-3 py-2 text-white/70">
                        {emp?.full_name || "—"}
                      </td>
                      <td className="px-3 py-2 text-right font-semibold text-white">
                        {fmtMoney(po.amount_max)}
                      </td>
                      <td className="px-3 py-2 text-center">
                        <span
                          className={`rounded-full border px-2 py-0.5 text-[10px] font-semibold ${
                            STATUS_BG[po.status] ||
                            "border-white/20 bg-white/10 text-white/70"
                          }`}
                        >
                          {STATUS_LABELS[po.status] || po.status}
                        </span>
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
