"use client";

import { useEffect, useState } from "react";
import {
  AlertTriangle,
  Loader2,
  Plus,
  Search,
  User,
  X
} from "lucide-react";

import { authedFetch } from "@/lib/auth";
import { ImmobilierTopbar } from "../layout";

type Locataire = {
  id: number;
  full_name: string;
  email?: string | null;
  phone?: string | null;
  paiement_score?: number | null;
  employeur?: string | null;
  revenu_annuel?: number | null;
};

export default function LocatairesPage() {
  const [list, setList] = useState<Locataire[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [showCreate, setShowCreate] = useState(false);

  async function reload() {
    setError(null);
    try {
      const url = search.trim()
        ? `/api/v1/immobilier/locataires?search=${encodeURIComponent(search.trim())}`
        : "/api/v1/immobilier/locataires";
      const res = await authedFetch(url);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setList((await res.json()) as Locataire[]);
    } catch (err) {
      setError((err as Error).message);
    }
  }

  useEffect(() => {
    const t = setTimeout(reload, 250);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search]);

  return (
    <>
      <ImmobilierTopbar
        breadcrumbs={[
          { label: "Gestion immobilière", href: "/immobilier" },
          { label: "Locataires" }
        ]}
        rightSlot={
          <button
            type="button"
            onClick={() => setShowCreate(true)}
            className="inline-flex items-center gap-1.5 rounded-lg border border-sky-400/30 bg-sky-500/10 px-3 py-1.5 text-xs font-semibold text-sky-200 hover:bg-sky-500/20"
          >
            <Plus className="h-3.5 w-3.5" />
            Nouveau locataire
          </button>
        }
      />

      <div className="p-4 lg:p-6">
        <div className="relative mb-4 max-w-md">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-white/40" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Recherche par nom…"
            className="input w-full pl-9"
          />
        </div>

        {error ? (
          <p className="mb-4 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
            <AlertTriangle className="mr-1.5 inline h-3.5 w-3.5" />
            {error}
          </p>
        ) : null}

        {list === null ? (
          <Loading />
        ) : list.length === 0 ? (
          <p className="rounded-lg border border-brand-800 bg-brand-900 px-4 py-3 text-sm text-white/60">
            Aucun locataire {search ? "correspondant" : "enregistré"}.
          </p>
        ) : (
          <div className="overflow-hidden rounded-2xl border border-brand-800 bg-brand-900">
            <table className="w-full text-left text-sm">
              <thead className="border-b border-brand-800 bg-brand-950 text-[10px] uppercase tracking-wider text-white/50">
                <tr>
                  <th className="px-4 py-2.5">Nom</th>
                  <th className="px-4 py-2.5">Contact</th>
                  <th className="px-4 py-2.5">Employeur</th>
                  <th className="px-4 py-2.5 text-right">Revenu/an</th>
                  <th className="px-4 py-2.5 text-right">Score paiement</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-brand-800">
                {list.map((l) => (
                  <tr key={l.id} className="hover:bg-brand-950/50">
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-3">
                        <div className="flex h-8 w-8 items-center justify-center rounded-full bg-sky-500/15 text-sky-300">
                          <User className="h-4 w-4" />
                        </div>
                        <span className="font-bold text-white">
                          {l.full_name}
                        </span>
                      </div>
                    </td>
                    <td className="px-4 py-3 text-xs text-white/60">
                      <div>{l.email || "—"}</div>
                      <div className="font-mono text-white/40">
                        {l.phone || "—"}
                      </div>
                    </td>
                    <td className="px-4 py-3 text-xs text-white/60">
                      {l.employeur || "—"}
                    </td>
                    <td className="px-4 py-3 text-right font-mono text-xs text-white/70">
                      {l.revenu_annuel
                        ? new Intl.NumberFormat("fr-CA", {
                            style: "currency",
                            currency: "CAD",
                            minimumFractionDigits: 2,
                            maximumFractionDigits: 2
                          }).format(l.revenu_annuel)
                        : "—"}
                    </td>
                    <td className="px-4 py-3 text-right font-mono text-xs">
                      {l.paiement_score != null ? (
                        <span
                          className={
                            l.paiement_score >= 90
                              ? "text-emerald-300"
                              : l.paiement_score >= 70
                              ? "text-amber-300"
                              : "text-rose-300"
                          }
                        >
                          {l.paiement_score}
                        </span>
                      ) : (
                        <span className="text-white/40">—</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {showCreate ? (
        <CreateLocataireModal
          onClose={() => setShowCreate(false)}
          onSaved={() => {
            setShowCreate(false);
            void reload();
          }}
        />
      ) : null}
    </>
  );
}

function CreateLocataireModal({
  onClose,
  onSaved
}: {
  onClose: () => void;
  onSaved: () => void;
}) {
  const [form, setForm] = useState({
    full_name: "",
    email: "",
    phone: "",
    employeur: "",
    revenu_annuel: ""
  });
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setErr(null);
    try {
      const body: Record<string, unknown> = {
        full_name: form.full_name.trim()
      };
      if (form.email.trim()) body.email = form.email.trim();
      if (form.phone.trim()) body.phone = form.phone.trim();
      if (form.employeur.trim()) body.employeur = form.employeur.trim();
      if (form.revenu_annuel)
        body.revenu_annuel = Number(form.revenu_annuel);
      const res = await authedFetch("/api/v1/immobilier/locataires", {
        method: "POST",
        body: JSON.stringify(body)
      });
      if (!res.ok) {
        const t = await res.text();
        throw new Error(t.slice(0, 240) || `HTTP ${res.status}`);
      }
      onSaved();
    } catch (e2) {
      setErr((e2 as Error).message);
    } finally {
      setSaving(false);
    }
  }

  function set<K extends keyof typeof form>(k: K, v: string) {
    setForm({ ...form, [k]: v });
  }

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/70 p-4 backdrop-blur-sm">
      <div className="my-8 w-full max-w-lg rounded-2xl border border-brand-800 bg-brand-950 shadow-2xl">
        <div className="flex items-center justify-between border-b border-brand-800 px-5 py-3">
          <h2 className="text-sm font-bold uppercase tracking-wider text-sky-300">
            Nouveau locataire
          </h2>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md p-1.5 text-white/60 hover:bg-brand-900 hover:text-white"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
        <form onSubmit={submit} className="grid gap-4 p-5">
          <div>
            <label className="label">Nom complet</label>
            <input
              required
              value={form.full_name}
              onChange={(e) => set("full_name", e.target.value)}
              className="input"
            />
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <label className="label">Email</label>
              <input
                type="email"
                value={form.email}
                onChange={(e) => set("email", e.target.value)}
                className="input"
              />
            </div>
            <div>
              <label className="label">Téléphone</label>
              <input
                value={form.phone}
                onChange={(e) => set("phone", e.target.value)}
                className="input font-mono"
              />
            </div>
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <label className="label">Employeur</label>
              <input
                value={form.employeur}
                onChange={(e) => set("employeur", e.target.value)}
                className="input"
              />
            </div>
            <div>
              <label className="label">Revenu annuel (CAD)</label>
              <input
                type="number"
                value={form.revenu_annuel}
                onChange={(e) => set("revenu_annuel", e.target.value)}
                className="input font-mono"
                min={0}
                step={1000}
              />
            </div>
          </div>

          {err ? (
            <p className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
              <AlertTriangle className="mr-1.5 inline h-3.5 w-3.5" />
              {err}
            </p>
          ) : null}

          <div className="flex items-center justify-end gap-2 border-t border-brand-800 pt-4">
            <button type="button" onClick={onClose} className="btn-secondary text-sm">
              Annuler
            </button>
            <button
              type="submit"
              disabled={saving || !form.full_name.trim()}
              className="btn-accent inline-flex items-center text-sm disabled:opacity-60"
            >
              {saving ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  Création…
                </>
              ) : (
                "Créer"
              )}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

function Loading() {
  return (
    <p className="text-xs text-white/50">
      <Loader2 className="mr-1 inline h-3 w-3 animate-spin" /> Chargement…
    </p>
  );
}
