"use client";

import { useEffect, useMemo, useState } from "react";
import { Loader2, Plus, Trash2, UserPlus, X } from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { useConfirm } from "@/components/confirm-dialog";
import { authedFetch } from "@/lib/auth";
import { useDevlogLayout } from "../layout";

type Lead = {
  id: number;
  name: string;
  company: string | null;
  email: string | null;
  phone: string | null;
  source: string;
  status: string;
  position: number;
  project_summary: string | null;
  budget_range: string | null;
  notes: string | null;
  client_id: number | null;
  created_at: string;
};

const COLUMNS: { key: string; label: string }[] = [
  { key: "nouveau", label: "Nouveau" },
  { key: "contacte", label: "Contacté" },
  { key: "rdv", label: "Rendez-vous" },
  { key: "presentation", label: "Présentation" },
  { key: "soumission", label: "Soumission" },
  { key: "gagne", label: "Gagné" },
  { key: "perdu", label: "Perdu" }
];

type DraftLead = {
  name: string;
  company: string;
  email: string;
  phone: string;
  source: string;
  status: string;
  project_summary: string;
  budget_range: string;
  notes: string;
};

const EMPTY_DRAFT: DraftLead = {
  name: "",
  company: "",
  email: "",
  phone: "",
  source: "interne",
  status: "nouveau",
  project_summary: "",
  budget_range: "",
  notes: ""
};

export default function DevlogLeadsPage() {
  const { onOpenSidebar } = useDevlogLayout();
  const confirm = useConfirm();
  const [leads, setLeads] = useState<Lead[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [draggedId, setDraggedId] = useState<number | null>(null);

  // Panneau latéral : "new" pour création, un id pour édition, null fermé.
  const [editing, setEditing] = useState<number | "new" | null>(null);
  const [draft, setDraft] = useState<DraftLead>(EMPTY_DRAFT);
  const [saving, setSaving] = useState(false);

  async function loadLeads() {
    try {
      const r = await authedFetch("/api/v1/devlog/leads");
      if (!r.ok) throw new Error("Chargement impossible");
      setLeads(await r.json());
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erreur");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadLeads();
  }, []);

  const byColumn = useMemo(() => {
    const map: Record<string, Lead[]> = {};
    for (const c of COLUMNS) map[c.key] = [];
    for (const l of leads) (map[l.status] ?? (map[l.status] = [])).push(l);
    for (const k of Object.keys(map))
      map[k].sort((a, b) => a.position - b.position || b.id - a.id);
    return map;
  }, [leads]);

  async function moveLead(leadId: number, status: string) {
    const lead = leads.find((l) => l.id === leadId);
    if (!lead || lead.status === status) return;
    const prev = leads;
    setLeads((xs) =>
      xs.map((l) => (l.id === leadId ? { ...l, status } : l))
    );
    try {
      const r = await authedFetch(
        `/api/v1/devlog/leads/${leadId}/status`,
        { method: "PATCH", body: JSON.stringify({ status }) }
      );
      if (!r.ok) throw new Error();
    } catch {
      setLeads(prev);
    }
  }

  function openNew() {
    setDraft(EMPTY_DRAFT);
    setEditing("new");
  }

  function openEdit(lead: Lead) {
    setDraft({
      name: lead.name,
      company: lead.company ?? "",
      email: lead.email ?? "",
      phone: lead.phone ?? "",
      source: lead.source,
      status: lead.status,
      project_summary: lead.project_summary ?? "",
      budget_range: lead.budget_range ?? "",
      notes: lead.notes ?? ""
    });
    setEditing(lead.id);
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
        source: draft.source,
        status: draft.status,
        project_summary: draft.project_summary.trim() || null,
        budget_range: draft.budget_range.trim() || null,
        notes: draft.notes.trim() || null
      };
      const r =
        editing === "new"
          ? await authedFetch("/api/v1/devlog/leads", {
              method: "POST",
              body: JSON.stringify(payload)
            })
          : await authedFetch(`/api/v1/devlog/leads/${editing}`, {
              method: "PATCH",
              body: JSON.stringify(payload)
            });
      if (!r.ok) throw new Error();
      setEditing(null);
      await loadLeads();
    } catch {
      setError("Enregistrement impossible");
    } finally {
      setSaving(false);
    }
  }

  async function deleteLead(leadId: number) {
    const ok = await confirm({
      title: "Supprimer ce lead ?",
      description: "Cette action est irréversible.",
      confirmLabel: "Supprimer",
      destructive: true
    });
    if (!ok) return;
    try {
      const r = await authedFetch(`/api/v1/devlog/leads/${leadId}`, {
        method: "DELETE"
      });
      if (!r.ok) throw new Error();
      setEditing(null);
      setLeads((xs) => xs.filter((l) => l.id !== leadId));
    } catch {
      setError("Suppression impossible");
    }
  }

  async function convertLead(leadId: number) {
    const ok = await confirm({
      title: "Convertir en client ?",
      description:
        "Un client du pôle sera créé à partir de ce lead, et le lead passera en « Gagné ».",
      confirmLabel: "Convertir"
    });
    if (!ok) return;
    try {
      const r = await authedFetch(
        `/api/v1/devlog/leads/${leadId}/convert`,
        { method: "POST" }
      );
      if (!r.ok) throw new Error();
      setEditing(null);
      await loadLeads();
    } catch {
      setError("Conversion impossible");
    }
  }

  const editingLead =
    typeof editing === "number"
      ? leads.find((l) => l.id === editing) ?? null
      : null;

  return (
    <div className="min-h-screen bg-brand-950">
      <AppTopbar
        breadcrumbs={[
          { label: "Développement logiciel", href: "/dev-logiciel" as any },
          { label: "Pipeline" }
        ]}
        onOpenSidebar={onOpenSidebar}
        rightSlot={
          <button
            type="button"
            onClick={openNew}
            className="inline-flex items-center gap-1.5 rounded-lg bg-blue-500 px-3 py-1.5 text-sm font-semibold text-white hover:bg-blue-400"
          >
            <Plus className="h-4 w-4" />
            Nouveau lead
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
        ) : (
          <div className="flex gap-3 overflow-x-auto pb-4">
            {COLUMNS.map((col) => (
              <div
                key={col.key}
                onDragOver={(ev) => {
                  if (draggedId != null) ev.preventDefault();
                }}
                onDrop={(ev) => {
                  ev.preventDefault();
                  if (draggedId != null) void moveLead(draggedId, col.key);
                  setDraggedId(null);
                }}
                className="flex w-64 flex-shrink-0 flex-col rounded-xl border border-brand-800 bg-brand-900/60"
              >
                <div className="flex items-center justify-between border-b border-brand-800 px-3 py-2">
                  <span className="text-sm font-semibold text-white">
                    {col.label}
                  </span>
                  <span className="rounded-full bg-white/5 px-2 text-xs font-bold text-white/60">
                    {byColumn[col.key]?.length ?? 0}
                  </span>
                </div>
                <div className="flex flex-1 flex-col gap-2 p-2">
                  {(byColumn[col.key] ?? []).map((lead) => (
                    <button
                      key={lead.id}
                      type="button"
                      draggable
                      onDragStart={() => setDraggedId(lead.id)}
                      onDragEnd={() => setDraggedId(null)}
                      onClick={() => openEdit(lead)}
                      className={`rounded-lg border border-brand-800 bg-brand-950 p-2.5 text-left transition hover:border-blue-500/60 ${
                        draggedId === lead.id ? "opacity-50" : ""
                      }`}
                    >
                      <p className="text-sm font-semibold text-white">
                        {lead.name}
                      </p>
                      {lead.company ? (
                        <p className="text-xs text-white/60">
                          {lead.company}
                        </p>
                      ) : null}
                      {lead.budget_range ? (
                        <p className="mt-1 text-[11px] text-blue-300">
                          {lead.budget_range}
                        </p>
                      ) : null}
                      <div className="mt-1.5 flex items-center gap-1.5">
                        <span className="rounded bg-white/5 px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-white/50">
                          {lead.source}
                        </span>
                        {lead.client_id ? (
                          <span className="rounded bg-emerald-500/15 px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-emerald-300">
                            Client
                          </span>
                        ) : null}
                      </div>
                    </button>
                  ))}
                  {(byColumn[col.key]?.length ?? 0) === 0 ? (
                    <p className="px-1 py-2 text-[11px] text-white/30">
                      Aucun lead.
                    </p>
                  ) : null}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {editing != null ? (
        <LeadDrawer
          isNew={editing === "new"}
          draft={draft}
          setDraft={setDraft}
          saving={saving}
          lead={editingLead}
          onClose={() => setEditing(null)}
          onSave={saveDraft}
          onDelete={
            typeof editing === "number"
              ? () => deleteLead(editing)
              : undefined
          }
          onConvert={
            typeof editing === "number" && !editingLead?.client_id
              ? () => convertLead(editing)
              : undefined
          }
        />
      ) : null}
    </div>
  );
}

function LeadDrawer({
  isNew,
  draft,
  setDraft,
  saving,
  lead,
  onClose,
  onSave,
  onDelete,
  onConvert
}: {
  isNew: boolean;
  draft: DraftLead;
  setDraft: (d: DraftLead) => void;
  saving: boolean;
  lead: Lead | null;
  onClose: () => void;
  onSave: () => void;
  onDelete?: () => void;
  onConvert?: () => void;
}) {
  const set = (k: keyof DraftLead, v: string) =>
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
            {isNew ? "Nouveau lead" : "Modifier le lead"}
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
          <div className="grid grid-cols-2 gap-3">
            <Field label="Étape">
              <select
                value={draft.status}
                onChange={(e) => set("status", e.target.value)}
                className={inputCls}
              >
                {COLUMNS.map((c) => (
                  <option key={c.key} value={c.key}>
                    {c.label}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Source">
              <select
                value={draft.source}
                onChange={(e) => set("source", e.target.value)}
                className={inputCls}
              >
                <option value="interne">Interne</option>
                <option value="web">Web</option>
              </select>
            </Field>
          </div>
          <Field label="Budget estimé">
            <input
              value={draft.budget_range}
              onChange={(e) => set("budget_range", e.target.value)}
              className={inputCls}
              placeholder="ex. 10 000 $ - 25 000 $"
            />
          </Field>
          <Field label="Projet souhaité">
            <textarea
              value={draft.project_summary}
              onChange={(e) => set("project_summary", e.target.value)}
              rows={3}
              className={inputCls}
              placeholder="Ce que le client veut faire développer…"
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

          {lead?.client_id ? (
            <p className="rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-xs text-emerald-300">
              Ce lead a été converti en client (#{lead.client_id}).
            </p>
          ) : null}
        </div>

        <div className="flex items-center gap-2 border-t border-brand-800 px-4 py-3">
          <button
            type="button"
            onClick={onSave}
            disabled={saving || !draft.name.trim()}
            className="inline-flex flex-1 items-center justify-center gap-1.5 rounded-lg bg-blue-500 px-3 py-2 text-sm font-semibold text-white hover:bg-blue-400 disabled:opacity-50"
          >
            {saving ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : null}
            Enregistrer
          </button>
          {onConvert ? (
            <button
              type="button"
              onClick={onConvert}
              title="Convertir en client"
              className="inline-flex items-center gap-1.5 rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-sm font-semibold text-emerald-300 hover:bg-emerald-500/20"
            >
              <UserPlus className="h-4 w-4" />
              Client
            </button>
          ) : null}
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
