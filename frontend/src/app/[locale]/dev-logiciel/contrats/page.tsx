"use client";

import { useEffect, useMemo, useState } from "react";
import {
  CheckCircle2,
  Copy,
  FileSignature,
  Link2,
  Loader2,
  Plus,
  Send,
  Trash2,
  X
} from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { useConfirm } from "@/components/confirm-dialog";
import { authedFetch } from "@/lib/auth";
import { useDevlogLayout } from "../layout";

type Contract = {
  id: number;
  title: string;
  body: string | null;
  status: string;
  soumission_id: number | null;
  client_id: number | null;
  project_id: number | null;
  signature_token: string | null;
  sent_at: string | null;
  signed_at: string | null;
  signed_name: string | null;
  created_at: string;
};

type RefItem = { id: number; name: string };
type SoumRef = { id: number; title: string };
type ProjectRef = { id: number; name: string };

const STATUS_OPTIONS = [
  { key: "brouillon", label: "Brouillon" },
  { key: "envoye", label: "Envoyé" },
  { key: "signe", label: "Signé" },
  { key: "annule", label: "Annulé" }
];

const STATUS_CLS: Record<string, string> = {
  brouillon: "bg-white/5 text-white/60",
  envoye: "bg-blue-500/15 text-blue-300",
  signe: "bg-emerald-500/15 text-emerald-300",
  annule: "bg-rose-500/15 text-rose-300"
};

type Draft = {
  title: string;
  body: string;
  status: string;
  soumission_id: string;
  client_id: string;
  project_id: string;
};

const EMPTY_DRAFT: Draft = {
  title: "",
  body: "",
  status: "brouillon",
  soumission_id: "",
  client_id: "",
  project_id: ""
};

const DEFAULT_TEMPLATE = `# Contrat de développement logiciel

**Entre** : Horizon Dév. logiciel
**Et** : [Nom du client]

## 1. Objet
Le présent contrat porte sur la livraison du projet décrit dans la soumission acceptée.

## 2. Livrables
[Détailler les livrables]

## 3. Échéancier
- Démarrage : [date]
- Livraison : [date]

## 4. Tarification
[Détails de la soumission acceptée]

## 5. Conditions de paiement
- Dépôt : 30 % à la signature
- Solde : à la livraison

## 6. Propriété intellectuelle
[Clauses standard]

## 7. Confidentialité
Les parties s'engagent à respecter la confidentialité des informations échangées.

Signé par les parties.`;

export default function DevlogContractsPage() {
  const { onOpenSidebar } = useDevlogLayout();
  const confirm = useConfirm();
  const [items, setItems] = useState<Contract[]>([]);
  const [clients, setClients] = useState<RefItem[]>([]);
  const [projects, setProjects] = useState<ProjectRef[]>([]);
  const [soumissions, setSoumissions] = useState<SoumRef[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");

  const [editing, setEditing] = useState<number | "new" | null>(null);
  const [draft, setDraft] = useState<Draft>(EMPTY_DRAFT);
  const [saving, setSaving] = useState(false);
  const [linkCopied, setLinkCopied] = useState<number | null>(null);

  async function loadAll() {
    try {
      const [cr, clr, pr, sr] = await Promise.all([
        authedFetch("/api/v1/devlog/contracts"),
        authedFetch("/api/v1/devlog/clients"),
        authedFetch("/api/v1/devlog/projects"),
        authedFetch("/api/v1/devlog/soumissions")
      ]);
      if (!cr.ok) throw new Error("Chargement impossible");
      setItems(await cr.json());
      if (clr.ok) setClients(await clr.json());
      if (pr.ok) setProjects(await pr.json());
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
    return items.filter((c) =>
      q
        ? `${c.title} ${c.signed_name || ""}`
            .toLowerCase()
            .includes(q)
        : true
    );
  }, [items, search]);

  function openNew() {
    setDraft({ ...EMPTY_DRAFT, body: DEFAULT_TEMPLATE });
    setEditing("new");
  }

  function openEdit(c: Contract) {
    setDraft({
      title: c.title,
      body: c.body ?? "",
      status: c.status,
      soumission_id: c.soumission_id ? String(c.soumission_id) : "",
      client_id: c.client_id ? String(c.client_id) : "",
      project_id: c.project_id ? String(c.project_id) : ""
    });
    setEditing(c.id);
  }

  async function saveDraft() {
    if (!draft.title.trim()) return;
    setSaving(true);
    try {
      const payload = {
        title: draft.title.trim(),
        body: draft.body.trim() || null,
        status: draft.status,
        soumission_id: draft.soumission_id ? Number(draft.soumission_id) : null,
        client_id: draft.client_id ? Number(draft.client_id) : null,
        project_id: draft.project_id ? Number(draft.project_id) : null
      };
      const r =
        editing === "new"
          ? await authedFetch("/api/v1/devlog/contracts", {
              method: "POST",
              body: JSON.stringify(payload)
            })
          : await authedFetch(`/api/v1/devlog/contracts/${editing}`, {
              method: "PATCH",
              body: JSON.stringify(payload)
            });
      if (!r.ok) throw new Error();
      setEditing(null);
      await loadAll();
    } catch {
      setError("Enregistrement impossible (le contrat est peut-être signé).");
    } finally {
      setSaving(false);
    }
  }

  async function sendContract(id: number) {
    const ok = await confirm({
      title: "Générer le lien de signature ?",
      description:
        "Un lien public sera créé. Tu pourras le copier et l'envoyer au client par courriel. Le contrat passera en « Envoyé ».",
      confirmLabel: "Générer"
    });
    if (!ok) return;
    try {
      const r = await authedFetch(`/api/v1/devlog/contracts/${id}/send`, {
        method: "POST"
      });
      if (!r.ok) throw new Error();
      await loadAll();
    } catch {
      setError("Génération du lien impossible");
    }
  }

  async function copyLink(c: Contract) {
    if (!c.signature_token) return;
    const url = `${window.location.origin}/sign-devlog/${c.signature_token}`;
    try {
      await navigator.clipboard.writeText(url);
      setLinkCopied(c.id);
      setTimeout(() => setLinkCopied(null), 2000);
    } catch {
      window.prompt("Copie ce lien :", url);
    }
  }

  async function deleteItem(id: number) {
    const ok = await confirm({
      title: "Supprimer ce contrat ?",
      description: "Cette action est irréversible.",
      confirmLabel: "Supprimer",
      destructive: true
    });
    if (!ok) return;
    try {
      const r = await authedFetch(`/api/v1/devlog/contracts/${id}`, {
        method: "DELETE"
      });
      if (!r.ok) throw new Error();
      setEditing(null);
      setItems((xs) => xs.filter((c) => c.id !== id));
    } catch {
      setError("Suppression impossible");
    }
  }

  return (
    <div className="min-h-screen bg-brand-950">
      <AppTopbar
        breadcrumbs={[
          { label: "Développement logiciel", href: "/dev-logiciel" as any },
          { label: "Contrats" }
        ]}
        onOpenSidebar={onOpenSidebar}
        searchPlaceholder="Chercher un contrat…"
        onSearch={setSearch}
        rightSlot={
          <button
            type="button"
            onClick={openNew}
            className="inline-flex items-center gap-1.5 rounded-lg bg-blue-500 px-3 py-1.5 text-sm font-semibold text-white hover:bg-blue-400"
          >
            <Plus className="h-4 w-4" />
            Nouveau contrat
          </button>
        }
      />

      <div className="mx-auto max-w-4xl px-4 py-4 lg:px-6">
        {error ? (
          <div className="mb-3 flex items-start justify-between gap-2 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-300">
            <span>{error}</span>
            <button type="button" onClick={() => setError(null)}>
              <X className="h-4 w-4" />
            </button>
          </div>
        ) : null}

        {loading ? (
          <div className="mt-10 flex justify-center">
            <Loader2 className="h-6 w-6 animate-spin text-blue-500" />
          </div>
        ) : filtered.length === 0 ? (
          <p className="mt-10 text-center text-sm text-white/40">
            Aucun contrat. Clique sur « Nouveau contrat ».
          </p>
        ) : (
          <ul className="space-y-2">
            {filtered.map((c) => (
              <li
                key={c.id}
                className="rounded-xl border border-brand-800 bg-brand-900 p-3"
              >
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <button
                    type="button"
                    onClick={() => openEdit(c)}
                    className="flex min-w-0 flex-1 items-center gap-3 text-left"
                  >
                    <span className="flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-lg bg-blue-500/15 text-blue-300">
                      <FileSignature className="h-4 w-4" />
                    </span>
                    <div className="min-w-0">
                      <p className="truncate text-sm font-semibold text-white">
                        {c.title}
                      </p>
                      <p className="mt-0.5 truncate text-xs text-white/50">
                        {c.client_id
                          ? clientName.get(c.client_id) ?? "Client supprimé"
                          : "Sans client"}
                        {c.signed_name ? ` · Signé par ${c.signed_name}` : ""}
                      </p>
                    </div>
                  </button>
                  <div className="flex flex-shrink-0 items-center gap-2">
                    <span
                      className={`rounded px-1.5 py-0.5 text-[10px] uppercase tracking-wide ${
                        STATUS_CLS[c.status] ?? "bg-white/5 text-white/50"
                      }`}
                    >
                      {STATUS_OPTIONS.find((s) => s.key === c.status)?.label ?? c.status}
                    </span>
                    {c.status === "brouillon" ? (
                      <button
                        type="button"
                        onClick={() => void sendContract(c.id)}
                        title="Générer le lien de signature"
                        className="rounded-md border border-blue-500/40 bg-blue-500/10 px-2 py-1 text-[10px] font-semibold text-blue-300 hover:bg-blue-500/20"
                      >
                        <Send className="h-3 w-3" />
                      </button>
                    ) : null}
                    {c.signature_token ? (
                      <button
                        type="button"
                        onClick={() => void copyLink(c)}
                        title="Copier le lien de signature"
                        className="rounded-md border border-white/15 bg-white/5 px-2 py-1 text-[10px] font-semibold text-white/70 hover:bg-white/10"
                      >
                        {linkCopied === c.id ? (
                          <CheckCircle2 className="h-3 w-3 text-emerald-300" />
                        ) : (
                          <Copy className="h-3 w-3" />
                        )}
                      </button>
                    ) : null}
                  </div>
                </div>
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
          clients={clients}
          projects={projects}
          soumissions={soumissions}
          locked={
            typeof editing === "number" &&
            items.find((c) => c.id === editing)?.status === "signe"
          }
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
  clients,
  projects,
  soumissions,
  locked,
  onClose,
  onSave,
  onDelete
}: {
  isNew: boolean;
  draft: Draft;
  setDraft: (d: Draft) => void;
  saving: boolean;
  clients: RefItem[];
  projects: ProjectRef[];
  soumissions: SoumRef[];
  locked?: boolean;
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
      <div className="relative flex h-full w-full max-w-2xl flex-col border-l border-brand-800 bg-brand-950">
        <div className="flex items-center justify-between border-b border-brand-800 px-4 py-3">
          <h2 className="text-sm font-bold text-white">
            {isNew ? "Nouveau contrat" : locked ? "Contrat signé (lecture seule)" : "Modifier le contrat"}
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
              disabled={locked}
              className={inputCls}
            />
          </Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Client">
              <select
                value={draft.client_id}
                onChange={(e) => set("client_id", e.target.value)}
                disabled={locked}
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
                disabled={locked}
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
          <Field label="Soumission liée">
            <select
              value={draft.soumission_id}
              onChange={(e) => set("soumission_id", e.target.value)}
              disabled={locked}
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
          <Field label="Contenu du contrat (Markdown)">
            <textarea
              value={draft.body}
              onChange={(e) => set("body", e.target.value)}
              disabled={locked}
              rows={18}
              className={inputCls}
              placeholder="# Contrat..."
            />
          </Field>
        </div>

        <div className="flex items-center gap-2 border-t border-brand-800 px-4 py-3">
          <button
            type="button"
            onClick={onSave}
            disabled={saving || !draft.title.trim() || locked}
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
