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

type Column = {
  key: string;
  label: string;
  dot: string; // tailwind bg color class
  total: string; // tailwind text color for total
};

// Kanban du même style que les soumissions du portail Construction :
// 5 colonnes avec dot couleur, count en badge, et total $ par colonne.
const COLUMNS: Column[] = [
  { key: "brouillon", label: "Brouillons", dot: "bg-white/40", total: "text-white/60" },
  { key: "envoyee", label: "Envoyées", dot: "bg-blue-400", total: "text-blue-300" },
  { key: "acceptee", label: "Acceptées", dot: "bg-emerald-400", total: "text-emerald-300" },
  { key: "refusee", label: "Refusées", dot: "bg-rose-400", total: "text-rose-300" },
  { key: "expiree", label: "Expirées", dot: "bg-amber-400", total: "text-amber-300" }
];

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

function fmtDateShort(s: string): string {
  const d = new Date(s);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleDateString("fr-CA", { day: "numeric", month: "short" });
}

export default function DevlogSoumissionsPage() {
  const { onOpenSidebar } = useDevlogLayout();
  const confirm = useConfirm();
  const [items, setItems] = useState<Soumission[]>([]);
  const [leads, setLeads] = useState<RefItem[]>([]);
  const [clients, setClients] = useState<RefItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");

  // Drag & drop entre colonnes.
  const [draggedId, setDraggedId] = useState<number | null>(null);

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

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return items;
    return items.filter((s) =>
      [s.title, s.summary, s.notes]
        .filter(Boolean)
        .some((v) => (v as string).toLowerCase().includes(q))
    );
  }, [items, search]);

  const byColumn = useMemo(() => {
    const map: Record<string, Soumission[]> = {};
    for (const c of COLUMNS) map[c.key] = [];
    for (const it of filtered) (map[it.status] ?? (map[it.status] = [])).push(it);
    return map;
  }, [filtered]);

  async function moveStatus(id: number, status: string) {
    const it = items.find((x) => x.id === id);
    if (!it || it.status === status) return;
    const prev = items;
    setItems((xs) => xs.map((x) => (x.id === id ? { ...x, status } : x)));
    try {
      const r = await authedFetch(`/api/v1/devlog/soumissions/${id}`, {
        method: "PATCH",
        body: JSON.stringify({ status })
      });
      if (!r.ok) throw new Error();
    } catch {
      setItems(prev);
    }
  }

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
        searchPlaceholder="Chercher une soumission…"
        onSearch={setSearch}
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

      <div className="px-4 py-4 lg:px-6">
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
          <div className="flex gap-3 overflow-x-auto pb-4">
            {COLUMNS.map((col) => {
              const list = byColumn[col.key] ?? [];
              const total = list.reduce(
                (sum, s) => sum + (s.amount || 0),
                0
              );
              return (
                <div
                  key={col.key}
                  onDragOver={(e) => {
                    if (draggedId != null) e.preventDefault();
                  }}
                  onDrop={(e) => {
                    e.preventDefault();
                    if (draggedId != null) void moveStatus(draggedId, col.key);
                    setDraggedId(null);
                  }}
                  className="flex w-72 flex-shrink-0 flex-col rounded-xl border border-brand-800 bg-brand-900/60"
                >
                  <div className="flex items-center justify-between border-b border-brand-800 px-3 py-2">
                    <div className="flex items-center gap-2">
                      <span className={`h-2 w-2 rounded-full ${col.dot}`} />
                      <span className="text-sm font-semibold text-white">
                        {col.label}
                      </span>
                      <span className="rounded-full bg-white/5 px-2 text-xs font-bold text-white/60">
                        {list.length}
                      </span>
                    </div>
                    {total > 0 ? (
                      <span className={`text-xs font-semibold ${col.total}`}>
                        {fmtAmount(total)}
                      </span>
                    ) : null}
                  </div>
                  <div className="flex flex-1 flex-col gap-2 p-2">
                    {list.map((s) => {
                      const target =
                        (s.client_id && clientName.get(s.client_id)) ||
                        (s.lead_id && leadName.get(s.lead_id)) ||
                        "Sans destinataire";
                      return (
                        <button
                          key={s.id}
                          type="button"
                          draggable
                          onDragStart={() => setDraggedId(s.id)}
                          onDragEnd={() => setDraggedId(null)}
                          onClick={() => openEdit(s)}
                          className={`group relative rounded-lg border border-brand-800 bg-brand-950 p-2.5 text-left transition hover:border-blue-500/60 ${
                            draggedId === s.id ? "opacity-50" : ""
                          }`}
                        >
                          <p className="line-clamp-2 text-sm font-semibold text-white">
                            {s.title}
                          </p>
                          <p className="mt-0.5 truncate text-xs text-white/50">
                            {target}
                          </p>
                          <div className="mt-2 flex items-center justify-between">
                            <span className="text-[11px] uppercase tracking-wider text-blue-400">
                              #{s.id} · {fmtDateShort(s.created_at)}
                            </span>
                            <span className="text-sm font-semibold text-white">
                              {fmtAmount(s.amount)}
                            </span>
                          </div>
                          <button
                            type="button"
                            onClick={(e) => {
                              e.stopPropagation();
                              void deleteItem(s.id);
                            }}
                            title="Supprimer"
                            className="absolute right-1.5 top-1.5 hidden rounded-md p-1 text-white/40 hover:bg-rose-500/20 hover:text-rose-300 group-hover:block"
                          >
                            <Trash2 className="h-3.5 w-3.5" />
                          </button>
                        </button>
                      );
                    })}
                    {list.length === 0 ? (
                      <p className="px-1 py-2 text-[11px] text-white/30">
                        Aucune.
                      </p>
                    ) : null}
                  </div>
                </div>
              );
            })}
          </div>
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
                <option value="brouillon">Brouillon</option>
                <option value="envoyee">Envoyée</option>
                <option value="acceptee">Acceptée</option>
                <option value="refusee">Refusée</option>
                <option value="expiree">Expirée</option>
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
