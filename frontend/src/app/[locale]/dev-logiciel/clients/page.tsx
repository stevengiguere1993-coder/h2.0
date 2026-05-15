"use client";

import { useEffect, useMemo, useState } from "react";
import { Globe, Loader2, Mail, Phone, Plus, Trash2, X } from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { useConfirm } from "@/components/confirm-dialog";
import { authedFetch } from "@/lib/auth";
import { useDevlogLayout } from "../layout";

type Client = {
  id: number;
  name: string;
  company: string | null;
  email: string | null;
  phone: string | null;
  address: string | null;
  website: string | null;
  status: string;
  notes: string | null;
  created_at: string;
};

type DraftClient = {
  name: string;
  company: string;
  email: string;
  phone: string;
  address: string;
  website: string;
  status: string;
  notes: string;
};

const EMPTY_DRAFT: DraftClient = {
  name: "",
  company: "",
  email: "",
  phone: "",
  address: "",
  website: "",
  status: "active",
  notes: ""
};

export default function DevlogClientsPage() {
  const { onOpenSidebar } = useDevlogLayout();
  const confirm = useConfirm();
  const [clients, setClients] = useState<Client[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");

  const [editing, setEditing] = useState<number | "new" | null>(null);
  const [draft, setDraft] = useState<DraftClient>(EMPTY_DRAFT);
  const [saving, setSaving] = useState(false);

  async function loadClients() {
    try {
      const r = await authedFetch("/api/v1/devlog/clients");
      if (!r.ok) throw new Error("Chargement impossible");
      setClients(await r.json());
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erreur");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadClients();
  }, []);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return clients;
    return clients.filter((c) =>
      [c.name, c.company, c.email]
        .filter(Boolean)
        .some((v) => (v as string).toLowerCase().includes(q))
    );
  }, [clients, search]);

  function openNew() {
    setDraft(EMPTY_DRAFT);
    setEditing("new");
  }

  function openEdit(c: Client) {
    setDraft({
      name: c.name,
      company: c.company ?? "",
      email: c.email ?? "",
      phone: c.phone ?? "",
      address: c.address ?? "",
      website: c.website ?? "",
      status: c.status,
      notes: c.notes ?? ""
    });
    setEditing(c.id);
  }

  async function saveDraft() {
    if (!draft.name.trim()) return;
    setSaving(true);
    try {
      const payload = {
        name: draft.name.trim(),
        company: draft.company.trim() || null,
        email: draft.email.trim() || null,
        phone: draft.phone.trim() || null,
        address: draft.address.trim() || null,
        website: draft.website.trim() || null,
        status: draft.status,
        notes: draft.notes.trim() || null
      };
      const r =
        editing === "new"
          ? await authedFetch("/api/v1/devlog/clients", {
              method: "POST",
              body: JSON.stringify(payload)
            })
          : await authedFetch(`/api/v1/devlog/clients/${editing}`, {
              method: "PATCH",
              body: JSON.stringify(payload)
            });
      if (!r.ok) throw new Error();
      setEditing(null);
      await loadClients();
    } catch {
      setError("Enregistrement impossible");
    } finally {
      setSaving(false);
    }
  }

  async function deleteClient(clientId: number) {
    const ok = await confirm({
      title: "Supprimer ce client ?",
      description: "Cette action est irréversible.",
      confirmLabel: "Supprimer",
      destructive: true
    });
    if (!ok) return;
    try {
      const r = await authedFetch(`/api/v1/devlog/clients/${clientId}`, {
        method: "DELETE"
      });
      if (!r.ok) throw new Error();
      setEditing(null);
      setClients((xs) => xs.filter((c) => c.id !== clientId));
    } catch {
      setError("Suppression impossible");
    }
  }

  return (
    <div className="min-h-screen bg-brand-950">
      <AppTopbar
        breadcrumbs={[
          { label: "Développement logiciel", href: "/dev-logiciel" as any },
          { label: "Clients" }
        ]}
        onOpenSidebar={onOpenSidebar}
        rightSlot={
          <button
            type="button"
            onClick={openNew}
            className="inline-flex items-center gap-1.5 rounded-lg bg-blue-500 px-3 py-1.5 text-sm font-semibold text-white hover:bg-blue-400"
          >
            <Plus className="h-4 w-4" />
            Nouveau client
          </button>
        }
      />

      <div className="mx-auto max-w-4xl px-4 py-4 lg:px-6">
        {error ? (
          <div className="mb-3 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-300">
            {error}
          </div>
        ) : null}

        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Rechercher un client…"
          className="input mb-4 text-sm"
        />

        {loading ? (
          <div className="mt-10 flex justify-center">
            <Loader2 className="h-6 w-6 animate-spin text-blue-500" />
          </div>
        ) : filtered.length === 0 ? (
          <p className="mt-10 text-center text-sm text-white/40">
            Aucun client. Clique sur « Nouveau client » ou convertis un lead
            gagné depuis le pipeline.
          </p>
        ) : (
          <ul className="space-y-2">
            {filtered.map((c) => (
              <li key={c.id}>
                <button
                  type="button"
                  onClick={() => openEdit(c)}
                  className="flex w-full items-center gap-3 rounded-xl border border-brand-800 bg-brand-900 p-3 text-left transition hover:border-blue-500/60"
                >
                  <span className="flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-lg bg-blue-500/15 text-sm font-bold text-blue-300">
                    {c.name.slice(0, 2).toUpperCase()}
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-semibold text-white">
                      {c.name}
                      {c.company ? (
                        <span className="text-white/50"> · {c.company}</span>
                      ) : null}
                    </p>
                    <div className="mt-0.5 flex flex-wrap gap-x-3 gap-y-0.5 text-xs text-white/50">
                      {c.email ? (
                        <span className="inline-flex items-center gap-1">
                          <Mail className="h-3 w-3" />
                          {c.email}
                        </span>
                      ) : null}
                      {c.phone ? (
                        <span className="inline-flex items-center gap-1">
                          <Phone className="h-3 w-3" />
                          {c.phone}
                        </span>
                      ) : null}
                      {c.website ? (
                        <span className="inline-flex items-center gap-1">
                          <Globe className="h-3 w-3" />
                          {c.website}
                        </span>
                      ) : null}
                    </div>
                  </div>
                  {c.status !== "active" ? (
                    <span className="rounded bg-white/5 px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-white/40">
                      Archivé
                    </span>
                  ) : null}
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      {editing != null ? (
        <ClientDrawer
          isNew={editing === "new"}
          draft={draft}
          setDraft={setDraft}
          saving={saving}
          onClose={() => setEditing(null)}
          onSave={saveDraft}
          onDelete={
            typeof editing === "number"
              ? () => deleteClient(editing)
              : undefined
          }
        />
      ) : null}
    </div>
  );
}

function ClientDrawer({
  isNew,
  draft,
  setDraft,
  saving,
  onClose,
  onSave,
  onDelete
}: {
  isNew: boolean;
  draft: DraftClient;
  setDraft: (d: DraftClient) => void;
  saving: boolean;
  onClose: () => void;
  onSave: () => void;
  onDelete?: () => void;
}) {
  const set = (k: keyof DraftClient, v: string) =>
    setDraft({ ...draft, [k]: v });
  const inputCls = "input text-sm";

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <button
        type="button"
        aria-label="Fermer"
        onClick={onClose}
        className="absolute inset-0 bg-black/70 backdrop-blur-sm"
      />
      <div className="relative flex h-full w-full max-w-md flex-col border-l border-brand-800 bg-brand-950">
        <div className="flex items-center justify-between border-b border-brand-800 px-4 py-3">
          <h2 className="text-sm font-bold text-white">
            {isNew ? "Nouveau client" : "Modifier le client"}
          </h2>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md p-1 text-white/50 hover:bg-brand-900 hover:text-white"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="flex-1 space-y-3 overflow-y-auto px-4 py-4">
          <Field label="Nom *">
            <input
              value={draft.name}
              onChange={(e) => set("name", e.target.value)}
              className={inputCls}
              placeholder="Nom du contact"
            />
          </Field>
          <Field label="Entreprise">
            <input
              value={draft.company}
              onChange={(e) => set("company", e.target.value)}
              className={inputCls}
            />
          </Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Courriel">
              <input
                value={draft.email}
                onChange={(e) => set("email", e.target.value)}
                className={inputCls}
              />
            </Field>
            <Field label="Téléphone">
              <input
                value={draft.phone}
                onChange={(e) => set("phone", e.target.value)}
                className={inputCls}
              />
            </Field>
          </div>
          <Field label="Adresse">
            <input
              value={draft.address}
              onChange={(e) => set("address", e.target.value)}
              className={inputCls}
            />
          </Field>
          <Field label="Site web">
            <input
              value={draft.website}
              onChange={(e) => set("website", e.target.value)}
              className={inputCls}
            />
          </Field>
          <Field label="Statut">
            <select
              value={draft.status}
              onChange={(e) => set("status", e.target.value)}
              className={inputCls}
            >
              <option value="active">Actif</option>
              <option value="archived">Archivé</option>
            </select>
          </Field>
          <Field label="Notes">
            <textarea
              value={draft.notes}
              onChange={(e) => set("notes", e.target.value)}
              rows={4}
              className={inputCls}
            />
          </Field>
        </div>

        <div className="flex items-center gap-2 border-t border-brand-800 px-4 py-3">
          <button
            type="button"
            onClick={onSave}
            disabled={saving || !draft.name.trim()}
            className="inline-flex flex-1 items-center justify-center gap-1.5 rounded-lg bg-blue-500 px-3 py-2 text-sm font-semibold text-white hover:bg-blue-400 disabled:opacity-50"
          >
            {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
            Enregistrer
          </button>
          {onDelete ? (
            <button
              type="button"
              onClick={onDelete}
              title="Supprimer"
              className="rounded-lg border border-rose-500/40 bg-rose-500/10 p-2 text-rose-300 hover:bg-rose-500/20"
            >
              <Trash2 className="h-4 w-4" />
            </button>
          ) : null}
        </div>
      </div>
    </div>
  );
}

function Field({
  label,
  children
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-medium text-white/60">
        {label}
      </span>
      {children}
    </label>
  );
}
