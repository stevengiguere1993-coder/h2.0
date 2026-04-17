"use client";

import { useEffect, useState } from "react";
import { Loader2 } from "lucide-react";

import { Link } from "@/i18n/navigation";
import { useCurrentUser } from "@/hooks/use-current-user";
import { authedFetch } from "@/lib/auth";

type ContactRequest = {
  id: number;
  name: string;
  email: string;
  phone: string | null;
  address: string | null;
  project_type: string;
  budget_range: string | null;
  message: string;
  locale: string;
  source: string | null;
  status: string;
  created_at: string;
};

const STATUS_LABELS: Record<string, string> = {
  new: "Nouveau",
  contacted: "Contacté",
  qualified: "Qualifié",
  quoted: "Devis envoyé",
  won: "Gagné",
  lost: "Perdu",
  spam: "Spam"
};

const STATUS_CLASS: Record<string, string> = {
  new: "bg-blue-100 text-blue-800",
  contacted: "bg-amber-100 text-amber-800",
  qualified: "bg-violet-100 text-violet-800",
  quoted: "bg-indigo-100 text-indigo-800",
  won: "bg-green-100 text-green-800",
  lost: "bg-gray-100 text-gray-600",
  spam: "bg-red-100 text-red-700"
};

export default function CrmPage() {
  const { user, loading: authLoading } = useCurrentUser();
  const [items, setItems] = useState<ContactRequest[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<string>("");

  useEffect(() => {
    if (!user) return;
    const load = async () => {
      setLoading(true);
      setError(null);
      try {
        const qs = statusFilter ? `?status=${encodeURIComponent(statusFilter)}&limit=100` : "?limit=100";
        const res = await authedFetch(`/api/v1/contact${qs}`);
        if (!res.ok) throw new Error(`http_${res.status}`);
        const data = (await res.json()) as ContactRequest[];
        setItems(data);
      } catch (err) {
        setError("Impossible de charger les demandes.");
      } finally {
        setLoading(false);
      }
    };
    load();
  }, [user, statusFilter]);

  async function updateStatus(id: number, newStatus: string) {
    const prev = items;
    setItems((xs) => xs.map((x) => (x.id === id ? { ...x, status: newStatus } : x)));
    try {
      const res = await authedFetch(`/api/v1/contact/${id}`, {
        method: "PATCH",
        body: JSON.stringify({ status: newStatus })
      });
      if (!res.ok) throw new Error(`http_${res.status}`);
    } catch {
      setItems(prev);
      setError("Mise à jour échouée.");
    }
  }

  if (authLoading) return <CenterSpinner />;
  if (!user) return null;

  return (
    <section className="section">
      <div className="container">
        <header className="flex flex-col items-start justify-between gap-3 sm:flex-row sm:items-center">
          <div>
            <p className="text-sm text-brand-600"><Link href={"/app" as "/app"} className="hover:text-brand-900">&larr; Portail</Link></p>
            <h1 className="text-3xl font-bold text-brand-950">CRM — Demandes de contact</h1>
            <p className="mt-1 text-sm text-brand-700">
              Pipeline des prospects issus du site public.
            </p>
          </div>
          <div>
            <label className="sr-only" htmlFor="status-filter">Filtrer</label>
            <select
              id="status-filter"
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
              className="input w-56"
            >
              <option value="">Tous les statuts</option>
              {Object.entries(STATUS_LABELS).map(([k, v]) => (
                <option key={k} value={k}>{v}</option>
              ))}
            </select>
          </div>
        </header>

        {error ? <p className="mt-6 text-sm text-red-600">{error}</p> : null}

        <div className="mt-8 overflow-hidden rounded-2xl border border-brand-100 bg-white shadow-card">
          {loading ? (
            <div className="py-16"><CenterSpinner /></div>
          ) : items.length === 0 ? (
            <p className="px-6 py-12 text-center text-sm text-brand-600">
              Aucune demande pour ce filtre.
            </p>
          ) : (
            <table className="w-full divide-y divide-brand-100 text-sm">
              <thead className="bg-brand-50 text-left text-xs uppercase tracking-wider text-brand-700">
                <tr>
                  <th className="px-4 py-3">Date</th>
                  <th className="px-4 py-3">Contact</th>
                  <th className="px-4 py-3">Projet</th>
                  <th className="px-4 py-3">Source</th>
                  <th className="px-4 py-3">Statut</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-brand-100">
                {items.map((r) => (
                  <tr key={r.id} className="hover:bg-brand-50/50">
                    <td className="px-4 py-3 text-brand-700">
                      {new Date(r.created_at).toLocaleDateString("fr-CA", { month: "short", day: "2-digit" })}
                    </td>
                    <td className="px-4 py-3">
                      <div className="font-semibold text-brand-950">{r.name}</div>
                      <div className="text-xs text-brand-600">{r.email}</div>
                      {r.phone ? <div className="text-xs text-brand-600">{r.phone}</div> : null}
                    </td>
                    <td className="px-4 py-3">
                      <div className="text-brand-900">{r.project_type}</div>
                      {r.budget_range ? <div className="text-xs text-brand-600">{r.budget_range}</div> : null}
                      <div className="text-xs text-brand-700 line-clamp-2 max-w-xs">{r.message}</div>
                    </td>
                    <td className="px-4 py-3 text-xs text-brand-600">{r.source || “–”}</td>
                    <td className="px-4 py-3">
                      <select
                        value={r.status}
                        onChange={(e) => updateStatus(r.id, e.target.value)}
                        className={`rounded-md px-2 py-1 text-xs font-semibold ${STATUS_CLASS[r.status] || "bg-gray-100"}`}
                      >
                        {Object.entries(STATUS_LABELS).map(([k, v]) => (
                          <option key={k} value={k}>{v}</option>
                        ))}
                      </select>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </section>
  );
}

function CenterSpinner() {
  return (
    <div className="flex min-h-[40vh] items-center justify-center">
      <Loader2 className="h-6 w-6 animate-spin text-brand-700" />
    </div>
  );
}
