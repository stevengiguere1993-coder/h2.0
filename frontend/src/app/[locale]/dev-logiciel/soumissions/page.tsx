"use client";

import { useEffect, useMemo, useState } from "react";
import { Loader2, Plus, Trash2, X } from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { useConfirm } from "@/components/confirm-dialog";
import { authedFetch } from "@/lib/auth";
import { useDevlogLayout } from "../layout";

type Soumission = {
  id: number;
  title: string;
  lead_id: number | null;
  client_id: number | null;
  amount: number | null;
  status: string;
  summary: string | null;
  notes: string | null;
  created_at: string;
};

type RefItem = { id: number; name: string };

const STATUSES: { key: string; label: string }[] = [
  { key: "brouillon", label: "Brouillon" },
  { key: "envoyee", label: "Envoyée" },
  { key: "acceptee", label: "Acceptée" },
  { key: "refusee", label: "Refusée" }
];

const STATUS_CLS: Record<string, string> = {
  brouillon: "bg-white/5 text-white/50",
  envoyee: "bg-blue-500/15 text-blue-300",
  acceptee: "bg-emerald-500/15 text-emerald-300",
  refusee: "bg-rose-500/15 text-rose-300"
};

type Draft = {
  title: string;
  lead_id: string;
  client_id: string;
  amount: string;
  status: string;
  summary: string;
  notes: string;
};

const EMPTY_DRAFT: Draft = {
  title: "",
  lead_id: "",
  client_id: "",
  amount: "",
  status: "brouillon",
  summary: "",
  notes: ""
};

function fmtAmount(n: number | null): string {
  if (n == null) return "—";
  return n.toLocaleString("fr-CA", {
    style: "currency",
    currency: "CAD",
    maximumFractionDigits: 0
  });
}

export default function DevlogSoumissionsPage() {
  const { onOpenSidebar } = useDevlogLayout();
  const confirm = useConfirm();
  const [items, setItems] = useState<Soumission[]>([]);
  const [leads, setLeads] = useState<RefItem[]>([]);
  const [clients, setClients] = useState<RefItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [editing, setEditing] = useState<number | "new" | null>(null);
  const [draft, setDraft] = useState<Draft>(EMPTY_DRAFT);
  const [saving, setSaving] = useState(false);

  async function loadAll() {
    try {
      const [sr, lr, cr] = await Promise.all([
        authedFetch("/api/v1/devlog/soumissions"),
        authedFetch("/api/v1/devlog/leads"),
        authedFetch("/api/v1/devlog/clients")
      ]);
      if (!sr.ok) throw new Error("Chargement impossible");
      setItems(await sr.json());
      if (lr.ok) setLeads(await lr.json());
      if (cr.ok) setClients(await cr.json());
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erreur");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadAll();
  }, []);

  const leadName = useMemo(
    () => new Map(leads.map((l) => [l.id, l.name])),
    [leads]
  );
  const clientName = useMemo(
    () => new Map(clients.map((c) => [c.id, c.name])),
    [clients]
  );

  function openNew() {
    setDraft(EMPTY_DRAFT);
    setEditing("new");
  }

  function openEdit(s: Soumission) {
    setDraft({
      title: s.title,
      lead_id: s.lead_id ? String(s.lead_id) : "",
      client_id: s.client_id ? String(s.client_id) : "",
      amount: s.amount != null ? String(s.amount) : "",
      status: s.status,
      summary: s.summary ?? "",
      notes: s.notes ?? ""
    });
    setEditing(s.id);
  }

  async function saveDraft() {
    if (!draft.title.trim()) return;
    setSaving(true);
    try {
      const payload = {
        title: draft.title.trim(),
        lead_id: draft.lead_id ? Number(draft.lead_id) : null,
        client_id: draft.client_id ? Number(draft.client_id) : null,
        amount: draft.amount.trim() ? Number(draft.amount) : null,
        status: draft.status,
        summary: draft.summary.trim() || null,
        notes: draft.notes.trim() || null
      };
      const r =
        editing === "new"
          ? await authedFetch("/api/v1/devlog/soumissions", {
              method: "POST",
              body: JSON.stringify(payload)
            })
          : await authedFetch(`/api/v1/devlog/soumissions/${editing}`, {
              method: "PATCH",
              body: JSON.stringify(payload)
            });
      if (!r.ok) throw new Error();
      setEditing(null);
      await loadAll();
    } catch {
      setError("Enregistrement impossible");
    } finally {
      setSaving(false);
    }
  }

  async function deleteItem(id: number) {
    const ok = await confirm({
      title: "Supprimer cette soumission ?",
      description: "Cette action est irréversible.",
      confirmLabel: "Supprimer",
      destructive: true
    });
    if (!ok) return;
    try {
      const r = await authedFetch(`/api/v1/devlog/soumissions/${id}`, {
        method: "DELETE"
      });
      if (!r.ok) throw new Error();
      setEditing(null);
      setItems((xs) => xs.filter((s) => s.id !== id));
    } catch {
      setError("Suppression impossible");
    }
  }

  return (
    <div className="min-h-screen bg-brand-950">
      <AppTopbar
        breadcrumbs={[
          { label: "Développement logiciel", href: "/dev-logiciel" as any },
          { label: "Soumissions" }
        ]}
        onOpenSidebar={onOpenSidebar}
        rightSlot={
          <button
            type="button"
            onClick={openNew}
            className="inline-flex items-center gap-1.5 rounded-lg bg-blue-500 px-3 py-1.5 text-sm font-semibold text-white hover:bg-blue-400"
          >
            <Plus className="h-4 w-4" />
            Nouvelle soumission
          </button>
        }
      />

      <div className="mx-auto max-w-4xl px-4 py-4 lg:px-6">
        {error ? (
          <div className="mb-3 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-300">
            {error}
          </div>
        ) : null}

        {loading ? (
          <div className="mt-10 flex justify-center">
            <Loader2 className="h-6 w-6 animate-spin text-blue-500" />
          </div>
        ) : items.length === 0 ? (
          <p className="mt-10 text-center text-sm text-white/40">
            Aucune soumission. Clique sur « Nouvelle soumission ».
          </p>
        ) : (
          <ul className="space-y-2">
            {items.map((s) => {
              const target =
                (s.client_id && clientName.get(s.client_id)) ||
                (s.lead_id && leadName.get(s.lead_id)) ||
                null;
              return (
                <li key={s.id}>
                  <button
                    type="button"
                    onClick={() => openEdit(s)}
                    className="flex w-full items-center gap-3 rounded-xl border border-brand-800 bg-brand-900 p-3 text-left transition hover:border-blue-500/60"
                  >
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm font-semibold text-white">
                        {s.title}
                      </p>
                      <p className="mt-0.5 text-xs text-white/50">
                        {target ? target : "Sans destinataire"}
                      </p>
                    </div>
                    <span className="text-sm font-semibold text-white">
                      {fmtAmount(s.amount)}
                    </span>
                    <span
                      className={`rounded px-1.5 py-0.5 text-[10px] uppercase tracking-wide ${
                        STATUS_CLS[s.status] ?? "bg-white/5 text-white/50"
                      }`}
                    >
                      {STATUSES.find((x) => x.key === s.status)?.label ??
                        s.status}
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </div>

      {editing != null ? (
        <SoumissionDrawer
          isNew={editing === "new"}
          draft={draft}
          setDraft={setDraft}
          saving={saving}
          leads={leads}
          clients={clients}
          onClose={() => setEditing(null)}
          onSave={saveDraft}
          onDelete={
            typeof editing === "number" ? () => deleteItem(editing) : undefined
          }
        />
      ) : null}
    </div>
  );
}

function SoumissionDrawer({
  isNew,
  draft,
  setDraft,
  saving,
  leads,
  clients,
  onClose,
  onSave,
  onDelete
}: {
  isNew: boolean;
  draft: Draft;
  setDraft: (d: Draft) => void;
  saving: boolean;
  leads: RefItem[];
  clients: RefItem[];
  onClose: () => void;
  onSave: () => void;
  onDelete?: () => void;
}) {
  const set = (k: keyof Draft, v: string) => setDraft({ ...draft, [k]: v });
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
            {isNew ? "Nouvelle soumission" : "Modifier la soumission"}
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
          <Field label="Titre *">
            <input
              value={draft.title}
              onChange={(e) => set("title", e.target.value)}
              className={inputCls}
              placeholder="ex. Plateforme de réservation v1"
            />
          </Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Lead">
              <select
                value={draft.lead_id}
                onChange={(e) => set("lead_id", e.target.value)}
                className={inputCls}
              >
                <option value="">—</option>
                {leads.map((l) => (
                  <option key={l.id} value={l.id}>
                    {l.name}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Client">
              <select
                value={draft.client_id}
                onChange={(e) => set("client_id", e.target.value)}
                className={inputCls}
              >
                <option value="">—</option>
                {clients.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </select>
            </Field>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Montant ($)">
              <input
                value={draft.amount}
                onChange={(e) => set("amount", e.target.value)}
                className={inputCls}
                inputMode="decimal"
                placeholder="0"
              />
            </Field>
            <Field label="Statut">
              <select
                value={draft.status}
                onChange={(e) => set("status", e.target.value)}
                className={inputCls}
              >
                {STATUSES.map((s) => (
                  <option key={s.key} value={s.key}>
                    {s.label}
                  </option>
                ))}
              </select>
            </Field>
          </div>
          <Field label="Description">
            <textarea
              value={draft.summary}
              onChange={(e) => set("summary", e.target.value)}
              rows={3}
              className={inputCls}
              placeholder="Ce qui est inclus dans le devis…"
            />
          </Field>
          <Field label="Notes">
            <textarea
              value={draft.notes}
              onChange={(e) => set("notes", e.target.value)}
              rows={3}
              className={inputCls}
            />
          </Field>
        </div>

        <div className="flex items-center gap-2 border-t border-brand-800 px-4 py-3">
          <button
            type="button"
            onClick={onSave}
            disabled={saving || !draft.title.trim()}
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
