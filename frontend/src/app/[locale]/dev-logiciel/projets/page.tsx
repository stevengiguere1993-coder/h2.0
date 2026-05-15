"use client";

import { useEffect, useMemo, useState } from "react";
import { CalendarClock, Loader2, Plus, Trash2, X } from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { useConfirm } from "@/components/confirm-dialog";
import { authedFetch } from "@/lib/auth";
import { useDevlogLayout } from "../layout";

type Project = {
  id: number;
  name: string;
  client_id: number | null;
  soumission_id: number | null;
  description: string | null;
  status: string;
  start_date: string | null;
  due_date: string | null;
  created_at: string;
};

type RefItem = { id: number; name: string };
type SoumissionRef = { id: number; title: string };

const STATUSES: { key: string; label: string }[] = [
  { key: "a_demarrer", label: "À démarrer" },
  { key: "en_cours", label: "En cours" },
  { key: "en_pause", label: "En pause" },
  { key: "livre", label: "Livré" },
  { key: "archive", label: "Archivé" }
];

const STATUS_CLS: Record<string, string> = {
  a_demarrer: "bg-white/5 text-white/50",
  en_cours: "bg-blue-500/15 text-blue-300",
  en_pause: "bg-amber-500/15 text-amber-300",
  livre: "bg-emerald-500/15 text-emerald-300",
  archive: "bg-white/5 text-white/40"
};

type Draft = {
  name: string;
  client_id: string;
  soumission_id: string;
  description: string;
  status: string;
  start_date: string;
  due_date: string;
};

const EMPTY_DRAFT: Draft = {
  name: "",
  client_id: "",
  soumission_id: "",
  description: "",
  status: "a_demarrer",
  start_date: "",
  due_date: ""
};

export default function DevlogProjectsPage() {
  const { onOpenSidebar } = useDevlogLayout();
  const confirm = useConfirm();
  const [items, setItems] = useState<Project[]>([]);
  const [clients, setClients] = useState<RefItem[]>([]);
  const [soumissions, setSoumissions] = useState<SoumissionRef[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [editing, setEditing] = useState<number | "new" | null>(null);
  const [draft, setDraft] = useState<Draft>(EMPTY_DRAFT);
  const [saving, setSaving] = useState(false);

  async function loadAll() {
    try {
      const [pr, cr, sr] = await Promise.all([
        authedFetch("/api/v1/devlog/projects"),
        authedFetch("/api/v1/devlog/clients"),
        authedFetch("/api/v1/devlog/soumissions")
      ]);
      if (!pr.ok) throw new Error("Chargement impossible");
      setItems(await pr.json());
      if (cr.ok) setClients(await cr.json());
      if (sr.ok) setSoumissions(await sr.json());
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

  function openNew() {
    setDraft(EMPTY_DRAFT);
    setEditing("new");
  }

  function openEdit(p: Project) {
    setDraft({
      name: p.name,
      client_id: p.client_id ? String(p.client_id) : "",
      soumission_id: p.soumission_id ? String(p.soumission_id) : "",
      description: p.description ?? "",
      status: p.status,
      start_date: p.start_date ?? "",
      due_date: p.due_date ?? ""
    });
    setEditing(p.id);
  }

  async function saveDraft() {
    if (!draft.name.trim()) return;
    setSaving(true);
    try {
      const payload = {
        name: draft.name.trim(),
        client_id: draft.client_id ? Number(draft.client_id) : null,
        soumission_id: draft.soumission_id
          ? Number(draft.soumission_id)
          : null,
        description: draft.description.trim() || null,
        status: draft.status,
        start_date: draft.start_date || null,
        due_date: draft.due_date || null
      };
      const r =
        editing === "new"
          ? await authedFetch("/api/v1/devlog/projects", {
              method: "POST",
              body: JSON.stringify(payload)
            })
          : await authedFetch(`/api/v1/devlog/projects/${editing}`, {
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
      title: "Supprimer ce projet ?",
      description: "Cette action est irréversible.",
      confirmLabel: "Supprimer",
      destructive: true
    });
    if (!ok) return;
    try {
      const r = await authedFetch(`/api/v1/devlog/projects/${id}`, {
        method: "DELETE"
      });
      if (!r.ok) throw new Error();
      setEditing(null);
      setItems((xs) => xs.filter((p) => p.id !== id));
    } catch {
      setError("Suppression impossible");
    }
  }

  return (
    <div className="min-h-screen bg-brand-950">
      <AppTopbar
        breadcrumbs={[
          { label: "Développement logiciel", href: "/dev-logiciel" as any },
          { label: "Projets" }
        ]}
        onOpenSidebar={onOpenSidebar}
        rightSlot={
          <button
            type="button"
            onClick={openNew}
            className="inline-flex items-center gap-1.5 rounded-lg bg-blue-500 px-3 py-1.5 text-sm font-semibold text-white hover:bg-blue-400"
          >
            <Plus className="h-4 w-4" />
            Nouveau projet
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
            Aucun projet. Clique sur « Nouveau projet ».
          </p>
        ) : (
          <ul className="space-y-2">
            {items.map((p) => (
              <li key={p.id}>
                <button
                  type="button"
                  onClick={() => openEdit(p)}
                  className="flex w-full items-center gap-3 rounded-xl border border-brand-800 bg-brand-900 p-3 text-left transition hover:border-blue-500/60"
                >
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-semibold text-white">
                      {p.name}
                    </p>
                    <div className="mt-0.5 flex flex-wrap items-center gap-x-3 text-xs text-white/50">
                      <span>
                        {p.client_id
                          ? clientName.get(p.client_id) ?? "Client supprimé"
                          : "Sans client"}
                      </span>
                      {p.due_date ? (
                        <span className="inline-flex items-center gap-1">
                          <CalendarClock className="h-3 w-3" />
                          {p.due_date}
                        </span>
                      ) : null}
                    </div>
                  </div>
                  <span
                    className={`rounded px-1.5 py-0.5 text-[10px] uppercase tracking-wide ${
                      STATUS_CLS[p.status] ?? "bg-white/5 text-white/50"
                    }`}
                  >
                    {STATUSES.find((x) => x.key === p.status)?.label ??
                      p.status}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      {editing != null ? (
        <ProjectDrawer
          isNew={editing === "new"}
          draft={draft}
          setDraft={setDraft}
          saving={saving}
          clients={clients}
          soumissions={soumissions}
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

function ProjectDrawer({
  isNew,
  draft,
  setDraft,
  saving,
  clients,
  soumissions,
  onClose,
  onSave,
  onDelete
}: {
  isNew: boolean;
  draft: Draft;
  setDraft: (d: Draft) => void;
  saving: boolean;
  clients: RefItem[];
  soumissions: SoumissionRef[];
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
            {isNew ? "Nouveau projet" : "Modifier le projet"}
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
          <Field label="Nom du projet *">
            <input
              value={draft.name}
              onChange={(e) => set("name", e.target.value)}
              className={inputCls}
              placeholder="ex. Plateforme de réservation"
            />
          </Field>
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
          <Field label="Soumission liée">
            <select
              value={draft.soumission_id}
              onChange={(e) => set("soumission_id", e.target.value)}
              className={inputCls}
            >
              <option value="">—</option>
              {soumissions.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.title}
                </option>
              ))}
            </select>
          </Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Date de début">
              <input
                type="date"
                value={draft.start_date}
                onChange={(e) => set("start_date", e.target.value)}
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
          <Field label="Description">
            <textarea
              value={draft.description}
              onChange={(e) => set("description", e.target.value)}
              rows={4}
              className={inputCls}
              placeholder="Portée du projet, livrables…"
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
