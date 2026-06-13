"use client";

import { useCallback, useEffect, useState } from "react";

import { AppTopbar } from "@/components/app-topbar";
import { useAppLayout } from "../layout";
import { authedFetch } from "@/lib/auth";
import { Link } from "@/i18n/navigation";

// ----------------------------------------------------------------------
// Ordres de travail (bons de travail assignables)
//
// Un ordre de travail est un PROJET léger (kind="bon_travail") : il
// réutilise toute la plomberie projet — achats, heures (punch), équipe /
// responsable, et facturation. On le crée ici, on l'assigne à un
// employé, puis on l'ouvre dans la fiche projet pour le détail.
// ----------------------------------------------------------------------

type WorkOrder = {
  id: number;
  name: string;
  status: string;
  address: string | null;
  responsible_user_id: number | null;
  responsible_name?: string | null;
};

type UserMini = { id: number; email: string; full_name?: string | null };
type ClientMini = { id: number; name: string };

export default function OrdresTravailPage() {
  const { onOpenSidebar } = useAppLayout();
  const [items, setItems] = useState<WorkOrder[]>([]);
  const [users, setUsers] = useState<UserMini[]>([]);
  const [clients, setClients] = useState<ClientMini[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [clientId, setClientId] = useState("");
  const [address, setAddress] = useState("");
  const [assigneeId, setAssigneeId] = useState("");
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [oRes, uRes, cRes] = await Promise.all([
        authedFetch("/api/v1/projects?kind=bon_travail&limit=300"),
        authedFetch("/api/v1/users"),
        authedFetch("/api/v1/clients?limit=500")
      ]);
      if (oRes.ok) setItems((await oRes.json()) as WorkOrder[]);
      if (uRes.ok) setUsers((await uRes.json()) as UserMini[]);
      if (cRes.ok) setClients((await cRes.json()) as ClientMini[]);
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function create() {
    if (!name.trim()) {
      setError("Le titre de l'ordre de travail est requis.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const body: Record<string, unknown> = {
        name: name.trim(),
        kind: "bon_travail"
      };
      if (clientId) body.client_id = Number(clientId);
      if (address.trim()) body.address = address.trim();
      if (assigneeId) body.responsible_user_id = Number(assigneeId);
      const res = await authedFetch("/api/v1/projects", {
        method: "POST",
        body: JSON.stringify(body)
      });
      if (!res.ok) throw new Error(`Erreur ${res.status}`);
      setName("");
      setClientId("");
      setAddress("");
      setAssigneeId("");
      setCreating(false);
      await load();
    } catch (e) {
      setError(`Création échouée : ${(e as Error).message}`);
    } finally {
      setSaving(false);
    }
  }

  function userName(id: number | null): string {
    if (!id) return "Non assigné";
    const u = users.find((x) => x.id === id);
    return u ? u.full_name || u.email : `#${id}`;
  }

  return (
    <div className="min-h-screen bg-brand-950">
      <AppTopbar
        breadcrumbs={[{ label: "Ordres de travail" }]}
        onOpenSidebar={onOpenSidebar}
      />
      <div className="p-4 lg:p-6">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="text-xl font-bold text-white">Ordres de travail</h1>
            <p className="mt-1 text-sm text-white/70">
              Travaux assignables à un employé. Chaque ordre suit ses
              achats et ses heures, et peut être facturé (comme un projet).
            </p>
          </div>
          <button
            type="button"
            onClick={() => setCreating((v) => !v)}
            className="btn-accent text-sm"
          >
            {creating ? "Fermer" : "+ Nouvel ordre"}
          </button>
        </div>

        {error ? (
          <p className="mb-3 rounded-md border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">
            {error}
          </p>
        ) : null}

        {creating ? (
          <div className="mb-5 rounded-xl border border-brand-800 bg-brand-900 p-4">
            <div className="grid gap-3 sm:grid-cols-2">
              <div className="sm:col-span-2">
                <label className="label text-xs">Titre *</label>
                <input
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="Ex. Réparation toiture — 4455 Bourret"
                  className="input"
                />
              </div>
              <div>
                <label className="label text-xs">Client (optionnel)</label>
                <select
                  value={clientId}
                  onChange={(e) => setClientId(e.target.value)}
                  className="input"
                >
                  <option value="">—</option>
                  {clients.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.name}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className="label text-xs">Assigné à</label>
                <select
                  value={assigneeId}
                  onChange={(e) => setAssigneeId(e.target.value)}
                  className="input"
                >
                  <option value="">— Non assigné —</option>
                  {users.map((u) => (
                    <option key={u.id} value={u.id}>
                      {u.full_name || u.email}
                    </option>
                  ))}
                </select>
              </div>
              <div className="sm:col-span-2">
                <label className="label text-xs">Adresse / lieu (optionnel)</label>
                <input
                  value={address}
                  onChange={(e) => setAddress(e.target.value)}
                  placeholder="Adresse des travaux"
                  className="input"
                />
              </div>
            </div>
            <div className="mt-3">
              <button
                type="button"
                onClick={() => void create()}
                disabled={saving}
                className="btn-accent text-sm disabled:opacity-50"
              >
                {saving ? "Création…" : "Créer l'ordre de travail"}
              </button>
            </div>
          </div>
        ) : null}

        {loading ? (
          <p className="text-sm text-white/50">Chargement…</p>
        ) : items.length === 0 ? (
          <p className="rounded-xl border border-brand-800 bg-brand-900 p-6 text-sm text-white/60">
            Aucun ordre de travail. Crée le premier avec « + Nouvel ordre ».
          </p>
        ) : (
          <ul className="space-y-2">
            {items.map((o) => (
              <li key={o.id}>
                <Link
                  // eslint-disable-next-line @typescript-eslint/no-explicit-any
                  href={`/app/projets/${o.id}` as any}
                  className="block rounded-xl border border-brand-800 bg-brand-900 p-3 transition hover:border-accent-500/50"
                >
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="font-semibold text-white">{o.name}</span>
                    <span className="rounded bg-sky-500/15 px-2 py-0.5 text-[11px] text-sky-200">
                      👤 {o.responsible_name || userName(o.responsible_user_id)}
                    </span>
                  </div>
                  {o.address ? (
                    <p className="mt-1 text-xs text-white/60">{o.address}</p>
                  ) : null}
                  <p className="mt-1 text-[11px] text-white/45">
                    Ouvrir pour gérer achats, heures et facturation.
                  </p>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
