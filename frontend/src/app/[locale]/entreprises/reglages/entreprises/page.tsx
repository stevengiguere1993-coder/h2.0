"use client";

import { useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  Building2,
  CheckCircle2,
  ChevronDown,
  Loader2,
  Pencil,
  Plus,
  Save,
  Trash2,
  X
} from "lucide-react";

import { Link } from "@/i18n/navigation";
import { authedFetch } from "@/lib/auth";

type Entreprise = {
  id: number;
  name: string;
  neq?: string | null;
  type: string;
  color_accent: string;
  description?: string | null;
  is_active: boolean;
  monday_board_id?: string | null;
  monday_board_name?: string | null;
  created_at: string;
  updated_at: string;
};

type FormState = {
  name: string;
  neq: string;
  type: string;
  color_accent: string;
  description: string;
  is_active: boolean;
};

const TYPES = [
  { value: "gestion", label: "Société de gestion" },
  { value: "immobiliere", label: "Société immobilière" },
  { value: "construction", label: "Construction" },
  { value: "investissement", label: "Investissement" },
  { value: "autre", label: "Autre" }
];

function toForm(e: Entreprise): FormState {
  return {
    name: e.name,
    neq: e.neq || "",
    type: e.type,
    color_accent: e.color_accent,
    description: e.description || "",
    is_active: e.is_active
  };
}

export default function ReglagesEntreprisesPage() {
  const [list, setList] = useState<Entreprise[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<number | "new" | null>(null);
  const [form, setForm] = useState<FormState | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [savedToast, setSavedToast] = useState(false);

  async function load() {
    setLoadError(null);
    try {
      const res = await authedFetch("/api/v1/entreprises");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setList((await res.json()) as Entreprise[]);
    } catch (err) {
      setLoadError((err as Error).message);
    }
  }

  useEffect(() => {
    void load();
  }, []);

  function startEdit(e: Entreprise) {
    setEditingId(e.id);
    setForm(toForm(e));
    setSaveError(null);
  }

  function startCreate() {
    setEditingId("new");
    setForm({
      name: "",
      neq: "",
      type: "gestion",
      color_accent: "#7c3aed",
      description: "",
      is_active: true
    });
    setSaveError(null);
  }

  function cancel() {
    setEditingId(null);
    setForm(null);
    setSaveError(null);
  }

  async function save() {
    if (!form) return;
    setSaving(true);
    setSaveError(null);
    try {
      const isNew = editingId === "new";
      const url = isNew
        ? "/api/v1/entreprises"
        : `/api/v1/entreprises/${editingId}`;
      const body = {
        name: form.name.trim(),
        neq: form.neq.trim() || null,
        type: form.type,
        color_accent: form.color_accent,
        description: form.description.trim() || null,
        is_active: form.is_active
      };
      const res = await authedFetch(url, {
        method: isNew ? "POST" : "PATCH",
        body: JSON.stringify(body)
      });
      if (!res.ok) {
        const t = await res.text();
        throw new Error(t.slice(0, 240) || `HTTP ${res.status}`);
      }
      await load();
      setSavedToast(true);
      setTimeout(() => setSavedToast(false), 1800);
      setEditingId(null);
      setForm(null);
    } catch (err) {
      setSaveError((err as Error).message);
    } finally {
      setSaving(false);
    }
  }

  async function remove(e: Entreprise) {
    if (
      !confirm(
        `Supprimer définitivement « ${e.name} » et toutes ses tâches ?`
      )
    )
      return;
    try {
      const res = await authedFetch(`/api/v1/entreprises/${e.id}`, {
        method: "DELETE"
      });
      if (!res.ok && res.status !== 204) {
        const t = await res.text();
        alert(t.slice(0, 240) || `HTTP ${res.status}`);
        return;
      }
      await load();
    } catch (err) {
      alert((err as Error).message);
    }
  }

  const sorted = useMemo(
    () =>
      list ? [...list].sort((a, b) => a.name.localeCompare(b.name)) : null,
    [list]
  );

  return (
    <div className="p-4 lg:p-6">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-start gap-3">
          <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-violet-500/15 text-violet-300">
            <Building2 className="h-5 w-5" />
          </span>
          <div>
            <h1 className="text-2xl font-bold text-white">
              Entreprises du portefeuille
            </h1>
            <p className="mt-1 max-w-2xl text-sm text-white/60">
              Édition rapide des entreprises gérées : nom, NEQ, couleur
              accent, description, statut actif.
            </p>
          </div>
        </div>
        <button
          type="button"
          onClick={startCreate}
          className="btn-accent inline-flex items-center text-sm"
        >
          <Plus className="mr-2 h-4 w-4" />
          Nouvelle entreprise
        </button>
      </header>

      {loadError ? (
        <p className="mt-4 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
          <AlertTriangle className="mr-1.5 inline h-3.5 w-3.5" />
          {loadError}
        </p>
      ) : null}

      {savedToast ? (
        <div className="fixed bottom-6 left-1/2 z-50 -translate-x-1/2 rounded-full border border-emerald-500/40 bg-emerald-500/15 px-4 py-2 text-xs font-semibold text-emerald-200 shadow-lg">
          <CheckCircle2 className="mr-1.5 inline h-3.5 w-3.5" />
          Enregistré
        </div>
      ) : null}

      {/* Création nouvelle entreprise */}
      {editingId === "new" && form ? (
        <section className="mt-6 rounded-2xl border border-violet-500/40 bg-violet-500/5 p-5">
          <h2 className="mb-4 text-sm font-semibold uppercase tracking-wider text-violet-200">
            Nouvelle entreprise
          </h2>
          <EntrepriseForm
            form={form}
            setForm={setForm}
            saving={saving}
            saveError={saveError}
            onSave={save}
            onCancel={cancel}
          />
        </section>
      ) : null}

      {/* Liste */}
      <section className="mt-6">
        {sorted === null ? (
          <div className="flex items-center gap-2 text-xs text-white/50">
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
            Chargement…
          </div>
        ) : sorted.length === 0 ? (
          <p className="rounded-lg border border-brand-800 bg-brand-900 px-4 py-3 text-sm text-white/60">
            Aucune entreprise. Crées-en une ou{" "}
            <Link
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
              href={"/entreprises/reglages/integration" as any}
              className="font-semibold text-violet-300 hover:text-violet-200"
            >
              importes-les depuis Monday →
            </Link>
          </p>
        ) : (
          <ul className="space-y-2">
            {sorted.map((e) => (
              <li
                key={e.id}
                className="overflow-hidden rounded-xl border border-brand-800 bg-brand-900"
              >
                <div className="flex flex-wrap items-center gap-3 px-4 py-3">
                  <span
                    className="h-9 w-9 flex-shrink-0 rounded-lg"
                    style={{ backgroundColor: e.color_accent }}
                    aria-hidden
                  />
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <Link
                        // eslint-disable-next-line @typescript-eslint/no-explicit-any
                        href={`/entreprises/${e.id}` as any}
                        className="truncate text-sm font-bold text-white hover:text-violet-300"
                      >
                        {e.name}
                      </Link>
                      {!e.is_active ? (
                        <span className="rounded-full border border-white/20 px-2 py-0.5 text-[10px] uppercase tracking-wider text-white/50">
                          Inactif
                        </span>
                      ) : null}
                    </div>
                    <div className="mt-0.5 flex flex-wrap items-center gap-2 text-[11px] text-white/50">
                      <span className="rounded bg-brand-950 px-1.5 py-0.5 font-mono">
                        {e.type}
                      </span>
                      {e.neq ? (
                        <span className="font-mono">NEQ {e.neq}</span>
                      ) : null}
                      {e.monday_board_name ? (
                        <span className="truncate">
                          · Monday : {e.monday_board_name}
                        </span>
                      ) : null}
                    </div>
                  </div>
                  <button
                    type="button"
                    onClick={() =>
                      editingId === e.id ? cancel() : startEdit(e)
                    }
                    className="inline-flex items-center gap-1.5 rounded-lg border border-white/15 bg-brand-950 px-3 py-1.5 text-xs font-semibold text-white/80 transition hover:border-violet-300 hover:text-violet-200"
                  >
                    {editingId === e.id ? (
                      <>
                        <X className="h-3.5 w-3.5" />
                        Fermer
                      </>
                    ) : (
                      <>
                        <Pencil className="h-3.5 w-3.5" />
                        Modifier
                      </>
                    )}
                  </button>
                  <button
                    type="button"
                    onClick={() => remove(e)}
                    className="rounded-lg border border-white/15 bg-brand-950 p-2 text-white/50 transition hover:border-rose-400/50 hover:text-rose-300"
                    title="Supprimer"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                  <ChevronDown
                    className={`h-4 w-4 text-white/30 transition-transform ${
                      editingId === e.id ? "rotate-180" : ""
                    }`}
                  />
                </div>
                {editingId === e.id && form ? (
                  <div
                    className="border-t px-4 py-4"
                    style={{ borderColor: "var(--qg-border)", backgroundColor: "#0f0f12" }}
                  >
                    <EntrepriseForm
                      form={form}
                      setForm={setForm}
                      saving={saving}
                      saveError={saveError}
                      onSave={save}
                      onCancel={cancel}
                    />
                  </div>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

function EntrepriseForm({
  form,
  setForm,
  saving,
  saveError,
  onSave,
  onCancel
}: {
  form: FormState;
  setForm: (f: FormState) => void;
  saving: boolean;
  saveError: string | null;
  onSave: () => void;
  onCancel: () => void;
}) {
  function set<K extends keyof FormState>(k: K, v: FormState[K]) {
    setForm({ ...form, [k]: v });
  }

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        if (!saving) onSave();
      }}
      className="grid gap-4 sm:grid-cols-2"
    >
      <div className="sm:col-span-2">
        <label htmlFor="name" className="label">
          Nom
        </label>
        <input
          id="name"
          required
          value={form.name}
          onChange={(e) => set("name", e.target.value)}
          className="input"
          placeholder="ex. Atelier Boréal"
        />
      </div>
      <div>
        <label htmlFor="neq" className="label">
          NEQ (Numéro d&apos;entreprise du Québec)
        </label>
        <input
          id="neq"
          value={form.neq}
          onChange={(e) => set("neq", e.target.value)}
          className="input font-mono"
          placeholder="1234567890"
          maxLength={32}
        />
      </div>
      <div>
        <label htmlFor="type" className="label">
          Type
        </label>
        <select
          id="type"
          value={form.type}
          onChange={(e) => set("type", e.target.value)}
          className="input"
        >
          {TYPES.map((t) => (
            <option key={t.value} value={t.value}>
              {t.label}
            </option>
          ))}
        </select>
      </div>
      <div>
        <label htmlFor="color" className="label">
          Couleur accent
        </label>
        <div className="flex items-center gap-2">
          <input
            id="color"
            type="color"
            value={form.color_accent}
            onChange={(e) => set("color_accent", e.target.value)}
            className="h-9 w-12 cursor-pointer rounded-lg border border-white/15 bg-transparent"
          />
          <input
            type="text"
            value={form.color_accent}
            onChange={(e) => set("color_accent", e.target.value)}
            pattern="^#[0-9a-fA-F]{6}$"
            className="input flex-1 font-mono text-sm"
            placeholder="#7c3aed"
          />
        </div>
      </div>
      <div>
        <label className="label">Statut</label>
        <label className="mt-1 flex cursor-pointer items-center gap-2 rounded-lg border border-white/15 bg-brand-950 px-3 py-2 text-sm">
          <input
            type="checkbox"
            checked={form.is_active}
            onChange={(e) => set("is_active", e.target.checked)}
            className="h-4 w-4 accent-violet-500"
          />
          <span>{form.is_active ? "Actif" : "Inactif"}</span>
        </label>
      </div>
      <div className="sm:col-span-2">
        <label htmlFor="description" className="label">
          Description (optionnel)
        </label>
        <textarea
          id="description"
          value={form.description}
          onChange={(e) => set("description", e.target.value)}
          rows={3}
          className="input"
          placeholder="Mission, mandat, contexte stratégique…"
        />
      </div>

      {saveError ? (
        <p className="sm:col-span-2 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
          <AlertTriangle className="mr-1.5 inline h-3.5 w-3.5" />
          {saveError}
        </p>
      ) : null}

      <div className="flex items-center gap-2 sm:col-span-2">
        <button
          type="submit"
          disabled={saving || !form.name.trim()}
          className="btn-accent inline-flex items-center text-sm disabled:opacity-60"
        >
          {saving ? (
            <>
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              Enregistrement…
            </>
          ) : (
            <>
              <Save className="mr-2 h-4 w-4" />
              Enregistrer
            </>
          )}
        </button>
        <button
          type="button"
          onClick={onCancel}
          className="btn-secondary inline-flex items-center text-sm"
        >
          Annuler
        </button>
      </div>
    </form>
  );
}
