"use client";

import { useEffect, useMemo, useState } from "react";
import {
  HardHat,
  Loader2,
  Mail,
  Phone,
  Plus,
  Star,
  Trash2,
  X
} from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { useConfirm } from "@/components/confirm-dialog";
import { authedFetch } from "@/lib/auth";
import { useDevlogLayout } from "../layout";

type SousTraitant = {
  id: number;
  name: string;
  company: string | null;
  email: string | null;
  phone: string | null;
  specialty: string | null;
  hourly_rate: number | null;
  active: boolean;
  rating: number | null;
  notes: string | null;
};

type Draft = {
  name: string;
  company: string;
  email: string;
  phone: string;
  specialty: string;
  hourly_rate: string;
  active: boolean;
  rating: string;
  notes: string;
};

const EMPTY_DRAFT: Draft = {
  name: "",
  company: "",
  email: "",
  phone: "",
  specialty: "",
  hourly_rate: "",
  active: true,
  rating: "",
  notes: ""
};

function fmtRate(n: number | null): string {
  if (n == null) return "—";
  return `${n.toLocaleString("fr-CA", { maximumFractionDigits: 2 })} $/h`;
}

export default function DevlogSousTraitantsPage() {
  const { onOpenSidebar } = useDevlogLayout();
  const confirm = useConfirm();
  const [items, setItems] = useState<SousTraitant[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [showInactive, setShowInactive] = useState(false);

  const [editing, setEditing] = useState<number | "new" | null>(null);
  const [draft, setDraft] = useState<Draft>(EMPTY_DRAFT);
  const [saving, setSaving] = useState(false);

  async function loadAll() {
    try {
      const r = await authedFetch("/api/v1/devlog/sous-traitants");
      if (!r.ok) throw new Error("Chargement impossible");
      setItems(await r.json());
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

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return items
      .filter((s) => (showInactive ? true : s.active))
      .filter((s) =>
        q
          ? [s.name, s.company, s.email, s.specialty]
              .filter(Boolean)
              .some((v) => (v as string).toLowerCase().includes(q))
          : true
      );
  }, [items, search, showInactive]);

  function openNew() {
    setDraft(EMPTY_DRAFT);
    setEditing("new");
  }

  function openEdit(s: SousTraitant) {
    setDraft({
      name: s.name,
      company: s.company ?? "",
      email: s.email ?? "",
      phone: s.phone ?? "",
      specialty: s.specialty ?? "",
      hourly_rate: s.hourly_rate != null ? String(s.hourly_rate) : "",
      active: s.active,
      rating: s.rating != null ? String(s.rating) : "",
      notes: s.notes ?? ""
    });
    setEditing(s.id);
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
        specialty: draft.specialty.trim() || null,
        hourly_rate: draft.hourly_rate.trim() ? Number(draft.hourly_rate) : null,
        active: draft.active,
        rating: draft.rating.trim() ? Number(draft.rating) : null,
        notes: draft.notes.trim() || null
      };
      const r =
        editing === "new"
          ? await authedFetch("/api/v1/devlog/sous-traitants", {
              method: "POST",
              body: JSON.stringify(payload)
            })
          : await authedFetch(`/api/v1/devlog/sous-traitants/${editing}`, {
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
      title: "Supprimer ce sous-traitant ?",
      description: "Cette action est irréversible.",
      confirmLabel: "Supprimer",
      destructive: true
    });
    if (!ok) return;
    try {
      const r = await authedFetch(`/api/v1/devlog/sous-traitants/${id}`, {
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
          { label: "Sous-traitants" }
        ]}
        onOpenSidebar={onOpenSidebar}
        searchPlaceholder="Chercher un sous-traitant…"
        onSearch={setSearch}
        rightSlot={
          <button
            type="button"
            onClick={openNew}
            className="btn-accent btn-sm"
          >
            <Plus className="h-4 w-4" />
            Nouveau sous-traitant
          </button>
        }
      />

      <div className="mx-auto max-w-4xl px-4 py-4 lg:px-6">
        {error ? (
          <div className="mb-3 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-300">
            {error}
          </div>
        ) : null}

        <div className="mb-3 flex items-center justify-between gap-2">
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Rechercher…"
            className="input flex-1 text-sm"
          />
          <label className="inline-flex items-center gap-2 text-xs text-white/60">
            <input
              type="checkbox"
              checked={showInactive}
              onChange={(e) => setShowInactive(e.target.checked)}
            />
            Inclure inactifs
          </label>
        </div>

        {loading ? (
          <div className="mt-10 flex justify-center">
            <Loader2 className="h-6 w-6 animate-spin text-accent-500" />
          </div>
        ) : filtered.length === 0 ? (
          <p className="mt-10 text-center text-sm text-white/40">
            Aucun sous-traitant.
          </p>
        ) : (
          <ul className="space-y-2">
            {filtered.map((s) => (
              <li key={s.id}>
                <button
                  type="button"
                  onClick={() => openEdit(s)}
                  className={`flex w-full items-center gap-3 rounded-xl border bg-brand-900 p-3 text-left transition hover:border-accent-500/60 ${
                    s.active ? "border-brand-800" : "border-brand-800 opacity-60"
                  }`}
                >
                  <span className="flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-lg bg-accent-500/15 text-accent-500">
                    <HardHat className="h-4 w-4" />
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-semibold text-white">
                      {s.name}
                      {s.company ? (
                        <span className="text-white/50"> · {s.company}</span>
                      ) : null}
                    </p>
                    <div className="mt-0.5 flex flex-wrap gap-x-3 text-xs text-white/50">
                      {s.specialty ? <span>{s.specialty}</span> : null}
                      {s.email ? (
                        <span className="inline-flex items-center gap-1">
                          <Mail className="h-3 w-3" />
                          {s.email}
                        </span>
                      ) : null}
                      {s.phone ? (
                        <span className="inline-flex items-center gap-1">
                          <Phone className="h-3 w-3" />
                          {s.phone}
                        </span>
                      ) : null}
                    </div>
                  </div>
                  <div className="flex flex-col items-end gap-1">
                    <span className="text-xs font-semibold text-white">
                      {fmtRate(s.hourly_rate)}
                    </span>
                    {s.rating ? (
                      <span className="badge badge-amber">
                        <Star className="h-3 w-3 fill-amber-300" />
                        {s.rating}/5
                      </span>
                    ) : null}
                    {!s.active ? (
                      <span className="badge badge-neutral uppercase tracking-wide">
                        Inactif
                      </span>
                    ) : null}
                  </div>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      {editing != null ? (
        <Drawer
          isNew={editing === "new"}
          draft={draft}
          setDraft={setDraft}
          saving={saving}
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

function Drawer({
  isNew,
  draft,
  setDraft,
  saving,
  onClose,
  onSave,
  onDelete
}: {
  isNew: boolean;
  draft: Draft;
  setDraft: (d: Draft) => void;
  saving: boolean;
  onClose: () => void;
  onSave: () => void;
  onDelete?: () => void;
}) {
  const set = <K extends keyof Draft>(k: K, v: Draft[K]) =>
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
            {isNew ? "Nouveau sous-traitant" : "Modifier le sous-traitant"}
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
          <Field label="Nom *">
            <input
              value={draft.name}
              onChange={(e) => set("name", e.target.value)}
              className={inputCls}
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
          <Field label="Spécialité">
            <input
              value={draft.specialty}
              onChange={(e) => set("specialty", e.target.value)}
              className={inputCls}
              placeholder="ex. Frontend React, Backend Python, UI/UX, QA…"
            />
          </Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Taux horaire ($/h)">
              <input
                type="number"
                step="0.5"
                value={draft.hourly_rate}
                onChange={(e) => set("hourly_rate", e.target.value)}
                className={inputCls}
              />
            </Field>
            <Field label="Évaluation (1-5)">
              <input
                type="number"
                min="1"
                max="5"
                value={draft.rating}
                onChange={(e) => set("rating", e.target.value)}
                className={inputCls}
              />
            </Field>
          </div>
          <label className="flex items-center gap-2 text-sm text-white/80">
            <input
              type="checkbox"
              checked={draft.active}
              onChange={(e) => set("active", e.target.checked)}
            />
            Actif
          </label>
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
