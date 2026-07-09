"use client";

import { useEffect, useMemo, useState } from "react";
import { Loader2, Plus, Trash2, X } from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { useConfirm } from "@/components/confirm-dialog";
import { authedFetch } from "@/lib/auth";
import { useCurrentUser } from "@/hooks/use-current-user";
import { PageDriveSection } from "@/components/drive/PageDriveSection";
import { useDevlogLayout } from "../layout";

type TimeEntry = {
  id: number;
  project_id: number | null;
  user_id: number | null;
  work_date: string;
  hours: number;
  description: string | null;
  created_at: string;
};

type ProjectRef = { id: number; name: string };

type Draft = {
  project_id: string;
  work_date: string;
  hours: string;
  description: string;
};

function todayISO(): string {
  return new Date().toISOString().slice(0, 10);
}

const emptyDraft = (): Draft => ({
  project_id: "",
  work_date: todayISO(),
  hours: "",
  description: ""
});

export default function DevlogHoursPage() {
  const { onOpenSidebar } = useDevlogLayout();
  const { user } = useCurrentUser();
  const confirm = useConfirm();
  const [items, setItems] = useState<TimeEntry[]>([]);
  const [projects, setProjects] = useState<ProjectRef[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [editing, setEditing] = useState<number | "new" | null>(null);
  const [draft, setDraft] = useState<Draft>(emptyDraft());
  const [saving, setSaving] = useState(false);

  async function loadAll() {
    try {
      const [tr, pr] = await Promise.all([
        authedFetch("/api/v1/devlog/time-entries"),
        authedFetch("/api/v1/devlog/projects")
      ]);
      if (!tr.ok) throw new Error("Chargement impossible");
      setItems(await tr.json());
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

  const projectName = useMemo(
    () => new Map(projects.map((p) => [p.id, p.name])),
    [projects]
  );

  const totalHours = useMemo(
    () => items.reduce((sum, e) => sum + (e.hours || 0), 0),
    [items]
  );

  function openNew() {
    setDraft(emptyDraft());
    setEditing("new");
  }

  function openEdit(e: TimeEntry) {
    setDraft({
      project_id: e.project_id ? String(e.project_id) : "",
      work_date: e.work_date,
      hours: String(e.hours),
      description: e.description ?? ""
    });
    setEditing(e.id);
  }

  async function saveDraft() {
    if (!draft.work_date || !draft.hours.trim()) return;
    setSaving(true);
    try {
      const payload = {
        project_id: draft.project_id ? Number(draft.project_id) : null,
        user_id: editing === "new" ? user?.id ?? null : undefined,
        work_date: draft.work_date,
        hours: Number(draft.hours),
        description: draft.description.trim() || null
      };
      const r =
        editing === "new"
          ? await authedFetch("/api/v1/devlog/time-entries", {
              method: "POST",
              body: JSON.stringify(payload)
            })
          : await authedFetch(`/api/v1/devlog/time-entries/${editing}`, {
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
      title: "Supprimer cette saisie ?",
      description: "Cette action est irréversible.",
      confirmLabel: "Supprimer",
      destructive: true
    });
    if (!ok) return;
    try {
      const r = await authedFetch(`/api/v1/devlog/time-entries/${id}`, {
        method: "DELETE"
      });
      if (!r.ok) throw new Error();
      setEditing(null);
      setItems((xs) => xs.filter((e) => e.id !== id));
    } catch {
      setError("Suppression impossible");
    }
  }

  return (
    <div className="min-h-screen bg-brand-950">
      <AppTopbar
        breadcrumbs={[
          { label: "Développement logiciel", href: "/dev-logiciel" as any },
          { label: "Heures" }
        ]}
        onOpenSidebar={onOpenSidebar}
        rightSlot={
          <button
            type="button"
            onClick={openNew}
            className="btn-accent btn-sm"
          >
            <Plus className="h-4 w-4" />
            Saisir des heures
          </button>
        }
      />

      <div className="mx-auto max-w-4xl px-4 py-4 lg:px-6">
        <PageDriveSection
          pageKey="page:dev-logiciel:heures"
          pole="Développement logiciel"
          label="Suivi des heures"
          route="/dev-logiciel/heures"
          className="mb-4"
        />

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
            <div className="mb-4 rounded-2xl border border-brand-800 bg-brand-900 p-4">
              <p className="text-xs uppercase tracking-wide text-white/50">
                Total des heures saisies
              </p>
              <p className="mt-1 text-3xl font-bold text-white">
                {totalHours.toLocaleString("fr-CA", {
                  maximumFractionDigits: 1
                })}{" "}
                h
              </p>
            </div>

            {items.length === 0 ? (
              <p className="mt-10 text-center text-sm text-white/40">
                Aucune saisie. Clique sur « Saisir des heures ».
              </p>
            ) : (
              <ul className="space-y-2">
                {items.map((e) => (
                  <li key={e.id}>
                    <button
                      type="button"
                      onClick={() => openEdit(e)}
                      className="flex w-full items-center gap-3 rounded-xl border border-brand-800 bg-brand-900 p-3 text-left transition hover:border-accent-500"
                    >
                      <span className="flex h-11 w-14 flex-shrink-0 flex-col items-center justify-center rounded-lg bg-accent-500/15 text-accent-500">
                        <span className="text-sm font-bold">{e.hours}</span>
                        <span className="text-[9px] uppercase">heures</span>
                      </span>
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-sm font-semibold text-white">
                          {e.project_id
                            ? projectName.get(e.project_id) ??
                              "Projet supprimé"
                            : "Sans projet"}
                        </p>
                        <p className="mt-0.5 truncate text-xs text-white/50">
                          {e.work_date}
                          {e.description ? ` · ${e.description}` : ""}
                        </p>
                      </div>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </>
        )}
      </div>

      {editing != null ? (
        <TimeEntryDrawer
          isNew={editing === "new"}
          draft={draft}
          setDraft={setDraft}
          saving={saving}
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

function TimeEntryDrawer({
  isNew,
  draft,
  setDraft,
  saving,
  projects,
  onClose,
  onSave,
  onDelete
}: {
  isNew: boolean;
  draft: Draft;
  setDraft: (d: Draft) => void;
  saving: boolean;
  projects: ProjectRef[];
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
            {isNew ? "Saisir des heures" : "Modifier la saisie"}
          </h2>
          <button
            type="button"
            onClick={onClose}
            className="btn-ghost btn-xs"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="flex-1 space-y-3 overflow-y-auto px-4 py-4">
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
          <div className="grid grid-cols-2 gap-3">
            <Field label="Date *">
              <input
                type="date"
                value={draft.work_date}
                onChange={(e) => set("work_date", e.target.value)}
                className={inputCls}
              />
            </Field>
            <Field label="Heures *">
              <input
                value={draft.hours}
                onChange={(e) => set("hours", e.target.value)}
                className={inputCls}
                inputMode="decimal"
                placeholder="0"
              />
            </Field>
          </div>
          <Field label="Description">
            <textarea
              value={draft.description}
              onChange={(e) => set("description", e.target.value)}
              rows={4}
              className={inputCls}
              placeholder="Ce qui a été fait…"
            />
          </Field>
        </div>

        <div className="flex items-center gap-2 border-t border-brand-800 px-4 py-3">
          <button
            type="button"
            onClick={onSave}
            disabled={saving || !draft.work_date || !draft.hours.trim()}
            className="btn-accent btn-sm flex-1 justify-center disabled:opacity-50"
          >
            {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
            Enregistrer
          </button>
          {onDelete ? (
            <button
              type="button"
              onClick={onDelete}
              title="Supprimer"
              className="btn-outline-rose btn-xs"
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
