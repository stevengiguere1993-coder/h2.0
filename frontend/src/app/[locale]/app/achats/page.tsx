"use client";

import { useEffect, useMemo, useState } from "react";
import { Loader2, Plus, ShoppingCart } from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { useAppLayout } from "../layout";
import { authedFetch } from "@/lib/auth";
import { Link } from "@/i18n/navigation";

type Achat = {
  id: number;
  reference: string;
  fournisseur_id: number | null;
  project_id: number | null;
  description: string | null;
  amount: number | string | null;
  status: string;
  ordered_at: string | null;
  received_at: string | null;
  receipt_url: string | null;
  notes: string | null;
  created_at: string;
};

type Project = { id: number; name: string };
type Fournisseur = { id: number; name: string };

const STATUS_LABELS: Record<string, string> = {
  draft: "Brouillon",
  ordered: "Commandé",
  received: "Reçu",
  cancelled: "Annulé"
};

const STATUS_CLASS: Record<string, string> = {
  draft: "bg-white/10 text-white",
  ordered: "bg-blue-500/20 text-blue-300",
  received: "bg-emerald-500/20 text-emerald-300",
  cancelled: "bg-white/5 text-white/50"
};

function fmtMoney(n: number | string | null): string {
  if (n == null || n === "") return "—";
  const num = typeof n === "string" ? Number(n) : n;
  return new Intl.NumberFormat("fr-CA", {
    style: "currency",
    currency: "CAD",
    maximumFractionDigits: 2
  }).format(num);
}

function fmtDate(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("fr-CA", {
    day: "2-digit",
    month: "short"
  });
}

export default function AchatsPage() {
  const { onOpenSidebar } = useAppLayout();
  const [items, setItems] = useState<Achat[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [fournisseurs, setFournisseurs] = useState<Fournisseur[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [fStatus, setFStatus] = useState("");
  const [fProject, setFProject] = useState("");
  const [fFournisseur, setFFournisseur] = useState("");

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const [aRes, pRes, frRes] = await Promise.all([
          authedFetch("/api/v1/achats?limit=500"),
          authedFetch("/api/v1/projects?limit=500"),
          authedFetch("/api/v1/fournisseurs?limit=500")
        ]);
        if (!aRes.ok) throw new Error(`http_${aRes.status}`);
        const as = (await aRes.json()) as Achat[];
        const ps = pRes.ok ? ((await pRes.json()) as Project[]) : [];
        const frs = frRes.ok ? ((await frRes.json()) as Fournisseur[]) : [];
        if (cancelled) return;
        setItems(as);
        setProjects(ps);
        setFournisseurs(frs);
      } catch {
        if (!cancelled) setError("Impossible de charger les achats.");
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

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return items.filter((a) => {
      if (fStatus && a.status !== fStatus) return false;
      if (fProject && String(a.project_id || "") !== fProject) return false;
      if (fFournisseur && String(a.fournisseur_id || "") !== fFournisseur)
        return false;
      if (
        q &&
        !a.reference.toLowerCase().includes(q) &&
        !(a.description || "").toLowerCase().includes(q)
      )
        return false;
      return true;
    });
  }, [items, search, fStatus, fProject, fFournisseur]);

  const total = useMemo(
    () =>
      filtered.reduce(
        (sum, a) => sum + (a.amount != null ? Number(a.amount) : 0),
        0
      ),
    [filtered]
  );

  return (
    <>
      <AppTopbar
        breadcrumbs={[{ label: "Construction", href: "/app" }, { label: "Achats / PO" }]}
        onOpenSidebar={onOpenSidebar}
        onSearch={setSearch}
        searchPlaceholder="Référence, description…"
        rightSlot={
          <Link
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            href={"/app/achats/new" as any}
            className="btn-accent text-sm"
          >
            <Plus className="mr-1.5 h-4 w-4" /> Nouvel achat
          </Link>
        }
      />

      <div className="p-4 lg:p-6">
        {error ? (
          <p className="mb-4 rounded-lg border border-rose-500/40 bg-rose-500/10 px-4 py-2 text-sm text-rose-300">
            {error}
          </p>
        ) : null}

        <div className="mb-4 flex flex-wrap items-center gap-2">
          <select
            value={fStatus}
            onChange={(e) => setFStatus(e.target.value)}
            className="input w-40"
          >
            <option value="">Tous les statuts</option>
            {Object.entries(STATUS_LABELS).map(([k, v]) => (
              <option key={k} value={k}>
                {v}
              </option>
            ))}
          </select>
          <select
            value={fProject}
            onChange={(e) => setFProject(e.target.value)}
            className="input w-48"
          >
            <option value="">Tous les projets</option>
            {projects.map((p) => (
              <option key={p.id} value={String(p.id)}>
                {p.name}
              </option>
            ))}
          </select>
          <select
            value={fFournisseur}
            onChange={(e) => setFFournisseur(e.target.value)}
            className="input w-48"
          >
            <option value="">Tous les fournisseurs</option>
            {fournisseurs.map((fr) => (
              <option key={fr.id} value={String(fr.id)}>
                {fr.name}
              </option>
            ))}
          </select>

          <div className="ml-auto rounded-md bg-brand-900 px-3 py-2 text-sm">
            <span className="text-white/50">Total filtré </span>
            <span className="font-bold text-white">{fmtMoney(total)}</span>
          </div>
        </div>

        {loading ? (
          <div className="flex min-h-[40vh] items-center justify-center">
            <Loader2 className="h-6 w-6 animate-spin text-accent-500" />
          </div>
        ) : filtered.length === 0 ? (
          <Empty />
        ) : (
          <div className="overflow-x-auto rounded-xl border border-brand-800 bg-brand-900">
            <table className="w-full text-sm">
              <thead className="border-b border-brand-800 text-left text-xs uppercase tracking-wider text-white/50">
                <tr>
                  <th className="px-4 py-3">Référence</th>
                  <th className="px-4 py-3">Fournisseur</th>
                  <th className="px-4 py-3">Projet</th>
                  <th className="px-4 py-3">Description</th>
                  <th className="px-4 py-3 text-right">Montant</th>
                  <th className="px-4 py-3">Commandé</th>
                  <th className="px-4 py-3 text-center">Statut</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-brand-800">
                {filtered.map((a) => {
                  const fr = a.fournisseur_id ? frById.get(a.fournisseur_id) : null;
                  const pr = a.project_id ? projById.get(a.project_id) : null;
                  return (
                    <tr
                      key={a.id}
                      onClick={() => (window.location.href = `/app/achats/${a.id}`)}
                      className="cursor-pointer hover:bg-brand-800/50"
                    >
                      <td className="px-4 py-3 font-semibold text-white">
                        {a.reference}
                      </td>
                      <td className="px-4 py-3 text-white/70">
                        {fr?.name || "—"}
                      </td>
                      <td className="px-4 py-3 text-white/70">
                        {pr?.name || "—"}
                      </td>
                      <td className="px-4 py-3 text-xs text-white/60">
                        <span className="line-clamp-1">{a.description || "—"}</span>
                      </td>
                      <td className="px-4 py-3 text-right font-semibold text-white">
                        {fmtMoney(a.amount)}
                      </td>
                      <td className="px-4 py-3 text-white/70">
                        {fmtDate(a.ordered_at)}
                      </td>
                      <td className="px-4 py-3 text-center">
                        <span
                          className={`rounded-md px-2 py-0.5 text-[10px] font-semibold ${
                            STATUS_CLASS[a.status] || "bg-white/10 text-white"
                          }`}
                        >
                          {STATUS_LABELS[a.status] || a.status}
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

function Empty() {
  return (
    <div className="mx-auto mt-16 max-w-md rounded-2xl border border-dashed border-brand-800 bg-brand-900/40 p-10 text-center">
      <ShoppingCart className="mx-auto h-10 w-10 text-accent-500" />
      <h2 className="mt-4 text-lg font-semibold text-white">Aucun achat</h2>
      <p className="mt-2 text-sm text-white/60">
        Enregistre tes achats de matériaux par projet; ils se reporteront
        dans la facture du client.
      </p>
      <Link
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        href={"/app/achats/new" as any}
        className="btn-accent mt-6 inline-flex text-sm"
      >
        <Plus className="mr-1.5 h-4 w-4" /> Nouvel achat
      </Link>
    </div>
  );
}
