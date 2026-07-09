"use client";

import { useCallback, useEffect, useState } from "react";
import {
  ChevronRight,
  FileText,
  Loader2,
  Mail,
  Plus,
  Save,
  Trash2,
  X
} from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { authedFetch, hasMinRole } from "@/lib/auth";
import { useCurrentUser } from "@/hooks/use-current-user";
import { useConfirm } from "@/components/confirm-dialog";
import { useAppLayout } from "../layout";

type Template = {
  id: number;
  name: string;
  description: string | null;
  subject: string;
  body_html: string;
  category: string;
  created_by_user_id: number | null;
  created_at: string;
  updated_at: string;
};

const CATEGORY_OPTIONS = [
  { value: "relance", label: "Relance" },
  { value: "bienvenue", label: "Bienvenue" },
  { value: "signature", label: "Demande de signature" },
  { value: "rappel", label: "Rappel paiement" },
  { value: "custom", label: "Personnalisé" }
];

const VARIABLES = [
  { name: "{{nom}}", desc: "Nom du destinataire" },
  { name: "{{prenom}}", desc: "Prénom (1er mot du nom)" },
  { name: "{{adresse}}", desc: "Adresse de l'immeuble/chantier" },
  { name: "{{soumission_id}}", desc: "Numéro de soumission" },
  { name: "{{prospecteur}}", desc: "Nom du commercial" },
  { name: "{{horizon_phone}}", desc: "Téléphone Horizon" },
  { name: "{{horizon_url}}", desc: "URL du site" }
];

export default function EmailTemplatesPage() {
  const { onOpenSidebar } = useAppLayout();
  const { user } = useCurrentUser();
  const isManager = hasMinRole(user, "manager");
  const confirm = useConfirm();

  const [templates, setTemplates] = useState<Template[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<Template | null>(null);
  const [creating, setCreating] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await authedFetch("/api/v1/email-templates");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setTemplates((await res.json()) as Template[]);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function deleteTemplate(t: Template) {
    if (
      !(await confirm({
        title: `Supprimer le template « ${t.name} » ?`,
        description: "Action irréversible."
      }))
    )
      return;
    const res = await authedFetch(
      `/api/v1/email-templates/${t.id}`,
      { method: "DELETE" }
    );
    if (res.ok || res.status === 204) {
      setTemplates((prev) => prev.filter((x) => x.id !== t.id));
    }
  }

  return (
    <>
      <AppTopbar
        breadcrumbs={[
          { label: "Construction", href: "/app" },
          { label: "Templates courriels" }
        ]}
        onOpenSidebar={onOpenSidebar}
        rightSlot={
          isManager ? (
            <button
              type="button"
              onClick={() => setCreating(true)}
              className="btn-accent text-sm"
            >
              <Plus className="mr-1.5 h-4 w-4" />
              Nouveau template
            </button>
          ) : null
        }
      />

      <div className="mx-auto max-w-4xl p-4 lg:p-6">
        <header className="flex items-center gap-3">
          <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-accent-500/15 text-accent-500">
            <Mail className="h-5 w-5" />
          </span>
          <div>
            <h1 className="text-2xl font-bold text-white">
              Templates courriels
            </h1>
            <p className="text-sm text-white/60">
              Messages-types réutilisables avec variables interpolées.
              Envoi via Microsoft Graph (gratuit, infra existante).
            </p>
          </div>
        </header>

        {error ? (
          <p className="mt-4 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-300">
            {error}
          </p>
        ) : null}

        {loading ? (
          <div className="flex min-h-[20vh] items-center justify-center">
            <Loader2 className="h-6 w-6 animate-spin text-accent-500" />
          </div>
        ) : templates.length === 0 ? (
          <div className="mt-6 rounded-xl border border-dashed border-brand-800 bg-brand-900/40 p-8 text-center">
            <FileText className="mx-auto h-8 w-8 text-white/20" />
            <p className="mt-3 text-sm text-white/60">
              Aucun template pour l&apos;instant.
            </p>
            {isManager ? (
              <button
                type="button"
                onClick={() => setCreating(true)}
                className="mt-3 btn-accent text-sm"
              >
                <Plus className="mr-1.5 h-4 w-4" />
                Créer le premier
              </button>
            ) : null}
          </div>
        ) : (
          <ul className="mt-6 space-y-2">
            {templates.map((t) => (
              <li
                key={t.id}
                className="group flex items-center gap-3 rounded-xl border border-brand-800 bg-brand-900 p-3 transition hover:border-accent-500/40"
              >
                <button
                  type="button"
                  onClick={() => setEditing(t)}
                  className="min-w-0 flex-1 text-left"
                >
                  <div className="flex items-center gap-2">
                    <h3 className="truncate font-medium text-white">
                      {t.name}
                    </h3>
                    <span className="rounded-full bg-brand-800 px-2 py-0.5 text-[10px] uppercase text-white/60">
                      {t.category}
                    </span>
                  </div>
                  <p className="mt-0.5 truncate text-[11px] text-white/50">
                    {t.subject}
                  </p>
                </button>
                {isManager ? (
                  <button
                    type="button"
                    onClick={() => deleteTemplate(t)}
                    className="btn-outline-rose btn-xs opacity-0 group-hover:opacity-100"
                    aria-label="Supprimer"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                ) : null}
                <ChevronRight className="h-4 w-4 shrink-0 text-white/30" />
              </li>
            ))}
          </ul>
        )}

        {/* Variables disponibles */}
        <section className="mt-8 rounded-2xl border border-brand-800 bg-brand-900 p-4">
          <h2 className="text-xs font-semibold uppercase tracking-wider text-white/50">
            Variables disponibles
          </h2>
          <ul className="mt-2 grid gap-1 sm:grid-cols-2">
            {VARIABLES.map((v) => (
              <li
                key={v.name}
                className="flex items-baseline gap-2 text-[11px]"
              >
                <code className="rounded bg-brand-950 px-1.5 py-0.5 font-mono text-emerald-300">
                  {v.name}
                </code>
                <span className="text-white/50">{v.desc}</span>
              </li>
            ))}
          </ul>
        </section>
      </div>

      {(creating || editing) && isManager ? (
        <TemplateEditorModal
          initial={editing}
          onClose={() => {
            setCreating(false);
            setEditing(null);
          }}
          onSaved={async () => {
            setCreating(false);
            setEditing(null);
            await load();
          }}
        />
      ) : null}
    </>
  );
}

function TemplateEditorModal({
  initial,
  onClose,
  onSaved
}: {
  initial: Template | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [name, setName] = useState(initial?.name || "");
  const [description, setDescription] = useState(
    initial?.description || ""
  );
  const [subject, setSubject] = useState(initial?.subject || "");
  const [body, setBody] = useState(
    initial?.body_html ||
      "<p>Bonjour {{prenom}},</p>\n\n<p>… votre message ici …</p>\n\n<p>Cordialement,<br/>{{prospecteur}}</p>"
  );
  const [category, setCategory] = useState(initial?.category || "custom");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function save() {
    if (!name.trim() || !subject.trim() || saving) return;
    setSaving(true);
    setError(null);
    try {
      const payload = {
        name: name.trim(),
        description: description.trim() || null,
        subject: subject.trim(),
        body_html: body,
        category
      };
      const url = initial
        ? `/api/v1/email-templates/${initial.id}`
        : "/api/v1/email-templates";
      const res = await authedFetch(url, {
        method: initial ? "PATCH" : "POST",
        body: JSON.stringify(payload)
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      onSaved();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-[1000] flex items-center justify-center bg-black/70 p-4"
      role="dialog"
      aria-modal="true"
    >
      <div className="flex max-h-[92vh] w-full max-w-2xl flex-col overflow-hidden rounded-2xl border border-brand-800 bg-brand-950">
        <header className="flex items-center justify-between border-b border-brand-800 px-4 py-3">
          <h2 className="text-sm font-semibold text-white">
            {initial ? "Modifier le template" : "Nouveau template"}
          </h2>
          <button
            type="button"
            onClick={onClose}
            className="btn-ghost btn-xs"
          >
            <X className="h-4 w-4" />
          </button>
        </header>

        <div className="flex-1 overflow-y-auto p-4">
          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <label className="label">Nom *</label>
              <input
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                className="input"
                placeholder="Ex: Relance soumission J+7"
              />
            </div>
            <div>
              <label className="label">Catégorie</label>
              <select
                value={category}
                onChange={(e) => setCategory(e.target.value)}
                className="input"
              >
                {CATEGORY_OPTIONS.map((c) => (
                  <option key={c.value} value={c.value}>
                    {c.label}
                  </option>
                ))}
              </select>
            </div>
            <div className="sm:col-span-2">
              <label className="label">Description (interne)</label>
              <input
                type="text"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                className="input"
              />
            </div>
            <div className="sm:col-span-2">
              <label className="label">Sujet * (avec variables)</label>
              <input
                type="text"
                value={subject}
                onChange={(e) => setSubject(e.target.value)}
                className="input"
                placeholder="Suivi de votre soumission #{{soumission_id}}"
              />
            </div>
            <div className="sm:col-span-2">
              <label className="label">
                Corps HTML * (avec variables)
              </label>
              <textarea
                rows={12}
                value={body}
                onChange={(e) => setBody(e.target.value)}
                className="input font-mono text-xs"
              />
              <p className="mt-1 text-[10px] text-white/40">
                HTML accepté. Variables : {`{{nom}}, {{prenom}}, {{adresse}}, {{soumission_id}}, {{prospecteur}}`}
              </p>
            </div>
          </div>
          {error ? (
            <p className="mt-3 rounded-md border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
              {error}
            </p>
          ) : null}
        </div>

        <footer className="flex items-center justify-end gap-2 border-t border-brand-800 px-4 py-3">
          <button
            type="button"
            onClick={onClose}
            className="btn-ghost btn-sm"
          >
            Annuler
          </button>
          <button
            type="button"
            onClick={save}
            disabled={!name.trim() || !subject.trim() || saving}
            className="btn-accent text-sm"
          >
            {saving ? (
              <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />
            ) : (
              <Save className="mr-1.5 h-4 w-4" />
            )}
            Enregistrer
          </button>
        </footer>
      </div>
    </div>
  );
}
