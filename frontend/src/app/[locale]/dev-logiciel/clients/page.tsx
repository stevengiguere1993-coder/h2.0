"use client";

import { useEffect, useMemo, useState } from "react";
import {
  LayoutGrid,
  List as ListIcon,
  Loader2,
  Mail,
  MapPin,
  Phone,
  Plus,
  Trash2,
  UserCheck,
  Users,
  X
} from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { useConfirm } from "@/components/confirm-dialog";
import { authedFetch } from "@/lib/auth";
import { useDevlogLayout } from "../layout";

type Client = {
  id: number;
  name: string;
  company: string | null;
  email: string | null;
  phone: string | null;
  address: string | null;
  website: string | null;
  status: string;
  notes: string | null;
  created_at: string;
};

type Lead = {
  id: number;
  name: string;
  company: string | null;
  email: string | null;
  phone: string | null;
  status: string;
  client_id: number | null;
  created_at: string;
};

// Vue unifiée — un contact peut être client OU lead.
type Contact = {
  id: string; // "c:42" ou "l:13"
  kind: "client" | "lead";
  raw_id: number;
  name: string;
  company: string | null;
  email: string | null;
  phone: string | null;
  address: string | null;
  status: string;
  source: string; // "Converti" si lead.client_id != null, sinon "Manuel"
};

type Tab = "clients" | "prospects" | "perdu" | "all";

type View = "list" | "kanban";

const TABS: { key: Tab; label: string }[] = [
  { key: "clients", label: "Clients" },
  { key: "prospects", label: "Prospects" },
  { key: "perdu", label: "Perdu" },
  { key: "all", label: "Tous" }
];

const LEAD_KANBAN_LABEL: Record<string, string> = {
  nouveau: "Nouveaux",
  contacte: "Contactés",
  rdv: "Rendez-vous",
  presentation: "Présentation",
  soumission: "Soumission",
  gagne: "Gagnés",
  perdu: "Perdus"
};

type DraftClient = {
  name: string;
  company: string;
  email: string;
  phone: string;
  address: string;
  website: string;
  status: string;
  notes: string;
};

const EMPTY_DRAFT: DraftClient = {
  name: "",
  company: "",
  email: "",
  phone: "",
  address: "",
  website: "",
  status: "active",
  notes: ""
};

export default function DevlogClientsPage() {
  const { onOpenSidebar } = useDevlogLayout();
  const confirm = useConfirm();
  const [clients, setClients] = useState<Client[]>([]);
  const [leads, setLeads] = useState<Lead[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [tab, setTab] = useState<Tab>("clients");
  const [view, setView] = useState<View>("list");
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState<Record<string, boolean>>({});

  const [editing, setEditing] = useState<number | "new" | null>(null);
  const [draft, setDraft] = useState<DraftClient>(EMPTY_DRAFT);
  const [saving, setSaving] = useState(false);

  // Mémorise la préférence de vue (liste/kanban) entre sessions.
  useEffect(() => {
    if (typeof window === "undefined") return;
    const v = window.localStorage.getItem("devlog-clients-view");
    if (v === "kanban" || v === "list") setView(v);
  }, []);
  useEffect(() => {
    if (typeof window === "undefined") return;
    window.localStorage.setItem("devlog-clients-view", view);
  }, [view]);

  async function loadAll() {
    try {
      const [cr, lr] = await Promise.all([
        authedFetch("/api/v1/devlog/clients"),
        authedFetch("/api/v1/devlog/leads")
      ]);
      if (!cr.ok || !lr.ok) throw new Error("Chargement impossible");
      setClients(await cr.json());
      setLeads(await lr.json());
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

  // Unifie clients + leads en une liste de Contacts.
  const allContacts: Contact[] = useMemo(() => {
    const out: Contact[] = [];
    for (const c of clients) {
      out.push({
        id: `c:${c.id}`,
        kind: "client",
        raw_id: c.id,
        name: c.name,
        company: c.company,
        email: c.email,
        phone: c.phone,
        address: c.address,
        status: c.status,
        source: "Manuel"
      });
    }
    for (const l of leads) {
      out.push({
        id: `l:${l.id}`,
        kind: "lead",
        raw_id: l.id,
        name: l.name,
        company: l.company,
        email: l.email,
        phone: l.phone,
        address: null,
        status: l.status,
        source: l.client_id ? "Converti" : "Manuel"
      });
    }
    return out;
  }, [clients, leads]);

  // Filtre selon l'onglet actif.
  const tabbed = useMemo(() => {
    if (tab === "clients") {
      return allContacts.filter(
        (x) => x.kind === "client" && x.status === "active"
      );
    }
    if (tab === "prospects") {
      return allContacts.filter(
        (x) =>
          x.kind === "lead" &&
          x.status !== "gagne" &&
          x.status !== "perdu"
      );
    }
    if (tab === "perdu") {
      return allContacts.filter(
        (x) => x.kind === "lead" && x.status === "perdu"
      );
    }
    return allContacts;
  }, [allContacts, tab]);

  const counts = useMemo(
    () => ({
      clients: allContacts.filter(
        (x) => x.kind === "client" && x.status === "active"
      ).length,
      prospects: allContacts.filter(
        (x) =>
          x.kind === "lead" &&
          x.status !== "gagne" &&
          x.status !== "perdu"
      ).length,
      perdu: allContacts.filter(
        (x) => x.kind === "lead" && x.status === "perdu"
      ).length,
      all: allContacts.length
    }),
    [allContacts]
  );

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return tabbed;
    return tabbed.filter((x) =>
      [x.name, x.company, x.email, x.phone, x.address]
        .filter(Boolean)
        .some((v) => (v as string).toLowerCase().includes(q))
    );
  }, [tabbed, search]);

  // Colonnes kanban selon l'onglet (mirror du pattern Construction).
  const kanbanColumns: { key: string; label: string }[] = useMemo(() => {
    if (tab === "clients")
      return [{ key: "active", label: "Clients actifs" }];
    if (tab === "prospects")
      return [
        { key: "nouveau", label: "Nouveaux" },
        { key: "contacte", label: "Contactés" },
        { key: "rdv", label: "Rendez-vous" },
        { key: "presentation", label: "Présentation" },
        { key: "soumission", label: "Soumission" }
      ];
    if (tab === "perdu") return [{ key: "perdu", label: "Perdu" }];
    return [
      { key: "prospects", label: "Prospects" },
      { key: "clients", label: "Clients" }
    ];
  }, [tab]);

  function kanbanKeyOf(c: Contact): string {
    if (tab === "all") return c.kind === "client" ? "clients" : "prospects";
    if (tab === "clients") return "active";
    return c.status;
  }

  const byColumn = useMemo(() => {
    const map: Record<string, Contact[]> = {};
    for (const col of kanbanColumns) map[col.key] = [];
    for (const c of filtered) {
      const k = kanbanKeyOf(c);
      (map[k] ?? (map[k] = [])).push(c);
    }
    return map;
  }, [filtered, kanbanColumns]);

  // ---- Sélection multiple ----
  const selectedIds = Object.keys(selected).filter((k) => selected[k]);
  const allSelected =
    filtered.length > 0 && filtered.every((c) => selected[c.id]);
  function toggleAll() {
    if (allSelected) {
      setSelected({});
    } else {
      const next: Record<string, boolean> = {};
      for (const c of filtered) next[c.id] = true;
      setSelected(next);
    }
  }

  async function bulkDelete() {
    const ok = await confirm({
      title: `Supprimer ${selectedIds.length} contact(s) ?`,
      description: "Cette action est irréversible.",
      confirmLabel: "Supprimer",
      destructive: true
    });
    if (!ok) return;
    const toDelete = filtered.filter((c) => selected[c.id]);
    try {
      await Promise.all(
        toDelete.map((c) =>
          authedFetch(
            c.kind === "client"
              ? `/api/v1/devlog/clients/${c.raw_id}`
              : `/api/v1/devlog/leads/${c.raw_id}`,
            { method: "DELETE" }
          )
        )
      );
      setSelected({});
      await loadAll();
    } catch {
      setError("Suppression partielle ou impossible");
    }
  }

  // ---- Client create/edit drawer ----
  function openNewClient() {
    setDraft(EMPTY_DRAFT);
    setEditing("new");
  }

  function openEditClient(c: Client) {
    setDraft({
      name: c.name,
      company: c.company ?? "",
      email: c.email ?? "",
      phone: c.phone ?? "",
      address: c.address ?? "",
      website: c.website ?? "",
      status: c.status,
      notes: c.notes ?? ""
    });
    setEditing(c.id);
  }

  function openContact(c: Contact) {
    if (c.kind === "client") {
      const cl = clients.find((x) => x.id === c.raw_id);
      if (cl) openEditClient(cl);
    }
    // Les leads s'éditent depuis le CRM — on ne fait que cliquer ici.
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
        address: draft.address.trim() || null,
        website: draft.website.trim() || null,
        status: draft.status,
        notes: draft.notes.trim() || null
      };
      const r =
        editing === "new"
          ? await authedFetch("/api/v1/devlog/clients", {
              method: "POST",
              body: JSON.stringify(payload)
            })
          : await authedFetch(`/api/v1/devlog/clients/${editing}`, {
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

  async function deleteClient(id: number) {
    const ok = await confirm({
      title: "Supprimer ce client ?",
      description: "Cette action est irréversible.",
      confirmLabel: "Supprimer",
      destructive: true
    });
    if (!ok) return;
    try {
      const r = await authedFetch(`/api/v1/devlog/clients/${id}`, {
        method: "DELETE"
      });
      if (!r.ok) throw new Error();
      setEditing(null);
      await loadAll();
    } catch {
      setError("Suppression impossible");
    }
  }

  return (
    <div className="min-h-screen bg-brand-950">
      <AppTopbar
        breadcrumbs={[
          { label: "Développement logiciel", href: "/dev-logiciel" as any },
          { label: "Clients" }
        ]}
        onOpenSidebar={onOpenSidebar}
        searchPlaceholder="Chercher un contact…"
        onSearch={setSearch}
        rightSlot={
          <div className="flex items-center gap-2">
            {selectedIds.length > 0 ? (
              <button
                type="button"
                onClick={bulkDelete}
                className="inline-flex items-center gap-1.5 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-1.5 text-sm font-semibold text-rose-300 hover:bg-rose-500/20"
              >
                <Trash2 className="h-4 w-4" />
                Supprimer ({selectedIds.length})
              </button>
            ) : null}
            <button
              type="button"
              onClick={openNewClient}
              className="inline-flex items-center gap-1.5 rounded-lg bg-blue-500 px-3 py-1.5 text-sm font-semibold text-white hover:bg-blue-400"
            >
              <Plus className="h-4 w-4" />
              Nouveau client
            </button>
          </div>
        }
      />

      <div className="mx-auto max-w-6xl px-4 py-4 lg:px-6">
        {error ? (
          <div className="mb-3 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-300">
            {error}
          </div>
        ) : null}

        {/* Onglets + toggle vue */}
        <div className="mb-4 flex items-center justify-between gap-2">
          <div className="flex flex-wrap gap-1">
            {TABS.map((t) => (
              <button
                key={t.key}
                type="button"
                onClick={() => {
                  setTab(t.key);
                  setSelected({});
                }}
                className={`rounded-lg px-3 py-1.5 text-sm font-semibold transition ${
                  tab === t.key
                    ? "bg-blue-500 text-white"
                    : "bg-brand-900 text-white/70 hover:bg-brand-800 hover:text-white"
                }`}
              >
                {t.label}
                <span className="ml-1.5 rounded-full bg-black/20 px-1.5 text-[11px]">
                  {counts[t.key]}
                </span>
              </button>
            ))}
          </div>
          <div className="flex gap-1 rounded-lg border border-brand-800 bg-brand-900 p-1">
            <button
              type="button"
              onClick={() => setView("list")}
              title="Vue liste"
              className={`rounded-md p-1.5 ${
                view === "list"
                  ? "bg-blue-500 text-white"
                  : "text-white/60 hover:text-white"
              }`}
            >
              <ListIcon className="h-4 w-4" />
            </button>
            <button
              type="button"
              onClick={() => setView("kanban")}
              title="Vue kanban"
              className={`rounded-md p-1.5 ${
                view === "kanban"
                  ? "bg-blue-500 text-white"
                  : "text-white/60 hover:text-white"
              }`}
            >
              <LayoutGrid className="h-4 w-4" />
            </button>
          </div>
        </div>

        {loading ? (
          <div className="mt-10 flex justify-center">
            <Loader2 className="h-6 w-6 animate-spin text-blue-500" />
          </div>
        ) : filtered.length === 0 ? (
          <p className="mt-10 text-center text-sm text-white/40">
            Aucun contact ne correspond.
          </p>
        ) : view === "list" ? (
          <div className="overflow-hidden rounded-2xl border border-brand-800">
            <table className="w-full text-sm">
              <thead className="border-b border-brand-800 bg-brand-900 text-left text-xs uppercase tracking-wider text-white/50">
                <tr>
                  <th className="px-3 py-2">
                    <input
                      type="checkbox"
                      checked={allSelected}
                      onChange={toggleAll}
                    />
                  </th>
                  <th className="px-2 py-2">Type</th>
                  <th className="px-3 py-2">Nom</th>
                  <th className="px-3 py-2">Courriel</th>
                  <th className="px-3 py-2">Téléphone</th>
                  <th className="px-3 py-2">Source / statut</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-brand-800">
                {filtered.map((c) => (
                  <tr
                    key={c.id}
                    className="hover:bg-brand-900/50"
                  >
                    <td className="px-3 py-2">
                      <input
                        type="checkbox"
                        checked={!!selected[c.id]}
                        onChange={(e) =>
                          setSelected({ ...selected, [c.id]: e.target.checked })
                        }
                      />
                    </td>
                    <td className="px-2 py-2">
                      {c.kind === "client" ? (
                        <UserCheck className="h-4 w-4 text-emerald-400" />
                      ) : (
                        <Users className="h-4 w-4 text-sky-400" />
                      )}
                    </td>
                    <td className="px-3 py-2 font-semibold text-white">
                      <button
                        type="button"
                        onClick={() => openContact(c)}
                        className="text-left hover:underline"
                      >
                        {c.name}
                        {c.company ? (
                          <span className="ml-1 text-white/40">
                            · {c.company}
                          </span>
                        ) : null}
                      </button>
                    </td>
                    <td className="px-3 py-2 text-white/70">
                      {c.email || "—"}
                    </td>
                    <td className="px-3 py-2 text-white/70">
                      {c.phone || "—"}
                    </td>
                    <td className="px-3 py-2 text-xs text-white/50">
                      {c.kind === "client" ? c.source : c.status}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="flex gap-3 overflow-x-auto pb-4">
            {kanbanColumns.map((col) => {
              const list = byColumn[col.key] ?? [];
              return (
                <div
                  key={col.key}
                  className="flex w-72 flex-shrink-0 flex-col rounded-xl border border-brand-800 bg-brand-900/60"
                >
                  <div className="flex items-center gap-2 border-b border-brand-800 px-3 py-2">
                    <span className="text-sm font-semibold text-white">
                      {col.label}
                    </span>
                    <span className="rounded-full bg-white/5 px-2 text-xs font-bold text-white/60">
                      {list.length}
                    </span>
                  </div>
                  <div className="flex flex-1 flex-col gap-2 p-2">
                    {list.map((c) => (
                      <button
                        key={c.id}
                        type="button"
                        onClick={() => openContact(c)}
                        className="rounded-lg border border-brand-800 bg-brand-950 p-2.5 text-left transition hover:border-blue-500/60"
                      >
                        <div className="flex items-start justify-between gap-2">
                          <p className="line-clamp-2 text-sm font-semibold text-white">
                            {c.name}
                          </p>
                          {c.kind === "client" ? (
                            <UserCheck className="h-3.5 w-3.5 flex-shrink-0 text-emerald-400" />
                          ) : (
                            <Users className="h-3.5 w-3.5 flex-shrink-0 text-sky-400" />
                          )}
                        </div>
                        {c.company ? (
                          <p className="mt-0.5 truncate text-xs text-white/50">
                            {c.company}
                          </p>
                        ) : null}
                        <div className="mt-2 space-y-0.5 text-[11px] text-white/40">
                          {c.email ? (
                            <p className="inline-flex items-center gap-1">
                              <Mail className="h-3 w-3" />
                              {c.email}
                            </p>
                          ) : null}
                          {c.phone ? (
                            <p className="inline-flex items-center gap-1">
                              <Phone className="h-3 w-3" />
                              {c.phone}
                            </p>
                          ) : null}
                          {c.address ? (
                            <p className="inline-flex items-center gap-1">
                              <MapPin className="h-3 w-3" />
                              {c.address}
                            </p>
                          ) : null}
                        </div>
                      </button>
                    ))}
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
        <ClientDrawer
          isNew={editing === "new"}
          draft={draft}
          setDraft={setDraft}
          saving={saving}
          onClose={() => setEditing(null)}
          onSave={saveDraft}
          onDelete={
            typeof editing === "number"
              ? () => deleteClient(editing)
              : undefined
          }
        />
      ) : null}
    </div>
  );
}

function ClientDrawer({
  isNew,
  draft,
  setDraft,
  saving,
  onClose,
  onSave,
  onDelete
}: {
  isNew: boolean;
  draft: DraftClient;
  setDraft: (d: DraftClient) => void;
  saving: boolean;
  onClose: () => void;
  onSave: () => void;
  onDelete?: () => void;
}) {
  const set = (k: keyof DraftClient, v: string) =>
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
            {isNew ? "Nouveau client" : "Modifier le client"}
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
          <Field label="Adresse">
            <input
              value={draft.address}
              onChange={(e) => set("address", e.target.value)}
              className={inputCls}
            />
          </Field>
          <Field label="Site web">
            <input
              value={draft.website}
              onChange={(e) => set("website", e.target.value)}
              className={inputCls}
            />
          </Field>
          <Field label="Statut">
            <select
              value={draft.status}
              onChange={(e) => set("status", e.target.value)}
              className={inputCls}
            >
              <option value="active">Actif</option>
              <option value="archived">Archivé</option>
            </select>
          </Field>
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
