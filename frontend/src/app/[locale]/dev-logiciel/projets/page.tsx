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

type Column = {
  key: string;
  label: string;
  dot: string;
};

// Kanban des projets — alignement direct sur le pôle Construction :
// 5 colonnes avec dot couleur et count badge.
const COLUMNS: Column[] = [
  { key: "planifie", label: "À planifier", dot: "bg-white/40" },
  { key: "en_attente", label: "En attente de début", dot: "bg-violet-400" },
  { key: "en_cours", label: "En cours", dot: "bg-blue-400" },
  { key: "suspendu", label: "Suspendu", dot: "bg-amber-400" },
  { key: "livre", label: "Livré", dot: "bg-emerald-400" }
];

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
  status: "planifie",
  start_date: "",
  due_date: ""
};

function fmtDateShort(s: string | null): string {
  if (!s) return "";
  const d = new Date(s);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleDateString("fr-CA", { day: "numeric", month: "short" });
}

export default function DevlogProjectsPage() {
  const { onOpenSidebar } = useDevlogLayout();
  const confirm = useConfirm();
  const [items, setItems] = useState<Project[]>([]);
  const [clients, setClients] = useState<RefItem[]>([]);
  const [soumissions, setSoumissions] = useState<SoumissionRef[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [draggedId, setDraggedId] = useState<number | null>(null);

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

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return items;
    return items.filter((p) =>
      [p.name, p.description]
        .filter(Boolean)
        .some((v) => (v as string).toLowerCase().includes(q))
    );
  }, [items, search]);

  const byColumn = useMemo(() => {
    const map: Record<string, Project[]> = {};
    for (const c of COLUMNS) map[c.key] = [];
    for (const p of filtered) (map[p.status] ?? (map[p.status] = [])).push(p);
    return map;
  }, [filtered]);

  async function moveStatus(id: number, status: string) {
    const p = items.find((x) => x.id === id);
    if (!p || p.status === status) return;
    const prev = items;
    setItems((xs) => xs.map((x) => (x.id === id ? { ...x, status } : x)));
    try {
      const r = await authedFetch(`/api/v1/devlog/projects/${id}`, {
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
        searchPlaceholder="Chercher un projet…"
        onSearch={setSearch}
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
            Aucun projet. Clique sur « Nouveau projet ».
          </p>
        ) : (
          <div className="flex gap-3 overflow-x-auto pb-4">
            {COLUMNS.map((col) => {
              const list = byColumn[col.key] ?? [];
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
                  <div className="flex items-center gap-2 border-b border-brand-800 px-3 py-2">
                    <span className={`h-2 w-2 rounded-full ${col.dot}`} />
                    <span className="text-sm font-semibold text-white">
                      {col.label}
                    </span>
                    <span className="rounded-full bg-white/5 px-2 text-xs font-bold text-white/60">
                      {list.length}
                    </span>
                  </div>
                  <div className="flex flex-1 flex-col gap-2 p-2">
                    {list.map((p) => {
                      const cn = p.client_id ? clientName.get(p.client_id) : null;
                      const start = fmtDateShort(p.start_date);
                      const end = fmtDateShort(p.due_date);
                      return (
                        <button
                          key={p.id}
                          type="button"
                          draggable
                          onDragStart={() => setDraggedId(p.id)}
                          onDragEnd={() => setDraggedId(null)}
                          onClick={() => openEdit(p)}
                          className={`group relative rounded-lg border border-brand-800 bg-brand-950 p-2.5 text-left transition hover:border-blue-500/60 ${
                            draggedId === p.id ? "opacity-50" : ""
                          }`}
                        >
                          <p className="line-clamp-2 text-sm font-semibold text-white">
                            {p.name}
                          </p>
                          {cn ? (
                            <p className="mt-0.5 truncate text-xs text-white/50">
                              {cn}
                            </p>
                          ) : null}
                          {start || end ? (
                            <p className="mt-2 inline-flex items-center gap-1 text-[11px] text-white/40">
                              <CalendarClock className="h-3 w-3" />
                              {start || "?"} → {end || "?"}
                            </p>
                          ) : null}
                          <button
                            type="button"
                            onClick={(e) => {
                              e.stopPropagation();
                              void deleteItem(p.id);
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
                        Aucun.
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
                <option value="planifie">À planifier</option>
                <option value="en_attente">En attente de début</option>
                <option value="en_cours">En cours</option>
                <option value="suspendu">Suspendu</option>
                <option value="livre">Livré</option>
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
