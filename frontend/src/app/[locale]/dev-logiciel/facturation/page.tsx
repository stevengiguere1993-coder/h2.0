"use client";

import { useEffect, useMemo, useState } from "react";
import { Loader2, Plus, Trash2, X } from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { useConfirm } from "@/components/confirm-dialog";
import { authedFetch } from "@/lib/auth";
import { useDevlogLayout } from "../layout";

type Invoice = {
  id: number;
  number: string | null;
  client_id: number | null;
  project_id: number | null;
  amount: number | null;
  status: string;
  issued_date: string | null;
  due_date: string | null;
  notes: string | null;
  created_at: string;
};

type RefItem = { id: number; name: string };

const STATUSES: { key: string; label: string }[] = [
  { key: "brouillon", label: "Brouillon" },
  { key: "envoyee", label: "Envoyée" },
  { key: "payee", label: "Payée" },
  { key: "annulee", label: "Annulée" }
];

const STATUS_CLS: Record<string, string> = {
  brouillon: "badge-neutral",
  envoyee: "badge-blue",
  payee: "badge-emerald",
  annulee: "badge-rose"
};

type Draft = {
  number: string;
  client_id: string;
  project_id: string;
  amount: string;
  status: string;
  issued_date: string;
  due_date: string;
  notes: string;
};

const EMPTY_DRAFT: Draft = {
  number: "",
  client_id: "",
  project_id: "",
  amount: "",
  status: "brouillon",
  issued_date: "",
  due_date: "",
  notes: ""
};

function fmtAmount(n: number | null): string {
  if (n == null) return "—";
  return n.toLocaleString("fr-CA", {
    style: "currency",
    currency: "CAD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2
  });
}

export default function DevlogInvoicesPage() {
  const { onOpenSidebar } = useDevlogLayout();
  const confirm = useConfirm();
  const [items, setItems] = useState<Invoice[]>([]);
  const [clients, setClients] = useState<RefItem[]>([]);
  const [projects, setProjects] = useState<RefItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [editing, setEditing] = useState<number | "new" | null>(null);
  const [draft, setDraft] = useState<Draft>(EMPTY_DRAFT);
  const [saving, setSaving] = useState(false);

  async function loadAll() {
    try {
      const [ir, cr, pr] = await Promise.all([
        authedFetch("/api/v1/devlog/invoices"),
        authedFetch("/api/v1/devlog/clients"),
        authedFetch("/api/v1/devlog/projects")
      ]);
      if (!ir.ok) throw new Error("Chargement impossible");
      setItems(await ir.json());
      if (cr.ok) setClients(await cr.json());
      if (pr.ok) setProjects(await pr.json());
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

  const clientName = useMemo(
    () => new Map(clients.map((c) => [c.id, c.name])),
    [clients]
  );

  const totalPaid = useMemo(
    () =>
      items
        .filter((i) => i.status === "payee")
        .reduce((s, i) => s + (i.amount || 0), 0),
    [items]
  );
  const totalOutstanding = useMemo(
    () =>
      items
        .filter((i) => i.status === "envoyee")
        .reduce((s, i) => s + (i.amount || 0), 0),
    [items]
  );

  function openNew() {
    setDraft(EMPTY_DRAFT);
    setEditing("new");
  }

  function openEdit(i: Invoice) {
    setDraft({
      number: i.number ?? "",
      client_id: i.client_id ? String(i.client_id) : "",
      project_id: i.project_id ? String(i.project_id) : "",
      amount: i.amount != null ? String(i.amount) : "",
      status: i.status,
      issued_date: i.issued_date ?? "",
      due_date: i.due_date ?? "",
      notes: i.notes ?? ""
    });
    setEditing(i.id);
  }

  async function saveDraft() {
    setSaving(true);
    try {
      const payload = {
        number: draft.number.trim() || null,
        client_id: draft.client_id ? Number(draft.client_id) : null,
        project_id: draft.project_id ? Number(draft.project_id) : null,
        amount: draft.amount.trim() ? Number(draft.amount) : null,
        status: draft.status,
        issued_date: draft.issued_date || null,
        due_date: draft.due_date || null,
        notes: draft.notes.trim() || null
      };
      const r =
        editing === "new"
          ? await authedFetch("/api/v1/devlog/invoices", {
              method: "POST",
              body: JSON.stringify(payload)
            })
          : await authedFetch(`/api/v1/devlog/invoices/${editing}`, {
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
      title: "Supprimer cette facture ?",
      description: "Cette action est irréversible.",
      confirmLabel: "Supprimer",
      destructive: true
    });
    if (!ok) return;
    try {
      const r = await authedFetch(`/api/v1/devlog/invoices/${id}`, {
        method: "DELETE"
      });
      if (!r.ok) throw new Error();
      setEditing(null);
      setItems((xs) => xs.filter((i) => i.id !== id));
    } catch {
      setError("Suppression impossible");
    }
  }

  return (
    <div className="min-h-screen bg-brand-950">
      <AppTopbar
        breadcrumbs={[
          { label: "Développement logiciel", href: "/dev-logiciel" as any },
          { label: "Facturation" }
        ]}
        onOpenSidebar={onOpenSidebar}
        rightSlot={
          <button
            type="button"
            onClick={openNew}
            className="inline-flex items-center gap-1.5 rounded-lg bg-accent-500 px-3 py-1.5 text-sm font-semibold text-white hover:bg-accent-400"
          >
            <Plus className="h-4 w-4" />
            Nouvelle facture
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
            <Loader2 className="h-6 w-6 animate-spin text-accent-500" />
          </div>
        ) : (
          <>
            <div className="mb-4 grid gap-3 sm:grid-cols-2">
              <div className="rounded-2xl border border-brand-800 bg-brand-900 p-4">
                <p className="text-xs uppercase tracking-wide text-white/50">
                  Encaissé (payées)
                </p>
                <p className="mt-1 text-2xl font-bold text-emerald-300">
                  {fmtAmount(totalPaid)}
                </p>
              </div>
              <div className="rounded-2xl border border-brand-800 bg-brand-900 p-4">
                <p className="text-xs uppercase tracking-wide text-white/50">
                  En attente (envoyées)
                </p>
                <p className="mt-1 text-2xl font-bold text-blue-300">
                  {fmtAmount(totalOutstanding)}
                </p>
              </div>
            </div>

            {items.length === 0 ? (
              <p className="mt-10 text-center text-sm text-white/40">
                Aucune facture. Clique sur « Nouvelle facture ».
              </p>
            ) : (
              <ul className="space-y-2">
                {items.map((i) => (
                  <li key={i.id}>
                    <button
                      type="button"
                      onClick={() => openEdit(i)}
                      className="flex w-full items-center gap-3 rounded-xl border border-brand-800 bg-brand-900 p-3 text-left transition hover:border-accent-500"
                    >
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-sm font-semibold text-white">
                          {i.number ? `Facture ${i.number}` : "Facture"}
                        </p>
                        <p className="mt-0.5 truncate text-xs text-white/50">
                          {i.client_id
                            ? clientName.get(i.client_id) ?? "Client supprimé"
                            : "Sans client"}
                          {i.issued_date ? ` · ${i.issued_date}` : ""}
                        </p>
                      </div>
                      <span className="text-sm font-semibold text-white">
                        {fmtAmount(i.amount)}
                      </span>
                      <span
                        className={`badge uppercase tracking-wide ${
                          STATUS_CLS[i.status] ?? "badge-neutral"
                        }`}
                      >
                        {STATUSES.find((x) => x.key === i.status)?.label ??
                          i.status}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </>
        )}
      </div>

      {editing != null ? (
        <InvoiceDrawer
          isNew={editing === "new"}
          draft={draft}
          setDraft={setDraft}
          saving={saving}
          clients={clients}
          projects={projects}
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

function InvoiceDrawer({
  isNew,
  draft,
  setDraft,
  saving,
  clients,
  projects,
  onClose,
  onSave,
  onDelete
}: {
  isNew: boolean;
  draft: Draft;
  setDraft: (d: Draft) => void;
  saving: boolean;
  clients: RefItem[];
  projects: RefItem[];
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
            {isNew ? "Nouvelle facture" : "Modifier la facture"}
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
          <div className="grid grid-cols-2 gap-3">
            <Field label="Numéro">
              <input
                value={draft.number}
                onChange={(e) => set("number", e.target.value)}
                className={inputCls}
                placeholder="ex. 2026-001"
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
          <div className="grid grid-cols-2 gap-3">
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
            <Field label="Projet">
              <select
                value={draft.project_id}
                onChange={(e) => set("project_id", e.target.value)}
                className={inputCls}
              >
                <option value="">—</option>
                {projects.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </select>
            </Field>
          </div>
          <Field label="Montant ($)">
            <input
              value={draft.amount}
              onChange={(e) => set("amount", e.target.value)}
              className={inputCls}
              inputMode="decimal"
              placeholder="0"
            />
          </Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Date d'émission">
              <input
                type="date"
                value={draft.issued_date}
                onChange={(e) => set("issued_date", e.target.value)}
                className={inputCls}
              />
            </Field>
            <Field label="Échéance">
              <input
                type="date"
                value={draft.due_date}
                onChange={(e) => set("due_date", e.target.value)}
                className={inputCls}
              />
            </Field>
          </div>
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
            disabled={saving}
            className="inline-flex flex-1 items-center justify-center gap-1.5 rounded-lg bg-accent-500 px-3 py-2 text-sm font-semibold text-white hover:bg-accent-400 disabled:opacity-50"
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
