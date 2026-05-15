"use client";

import { useEffect, useMemo, useState } from "react";
import { useParams } from "next/navigation";
import {
  ArrowLeft,
  FileText,
  FolderKanban,
  Loader2,
  Plus,
  Receipt,
  Trash2
} from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { useConfirm } from "@/components/confirm-dialog";
import { Link } from "@/i18n/navigation";
import { authedFetch } from "@/lib/auth";
import { useDevlogLayout } from "../../layout";

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
  updated_at: string;
};

type Soumission = {
  id: number;
  title: string;
  amount: number | null;
  status: string;
};
type Project = {
  id: number;
  name: string;
  status: string;
  start_date: string | null;
  due_date: string | null;
};
type Invoice = {
  id: number;
  number: string | null;
  amount: number | null;
  status: string;
  issued_date: string | null;
};

function fmtAmount(n: number | null): string {
  if (n == null) return "—";
  return n.toLocaleString("fr-CA", {
    style: "currency",
    currency: "CAD",
    maximumFractionDigits: 0
  });
}

const SOUM_CLS: Record<string, string> = {
  brouillon: "bg-white/5 text-white/60",
  envoyee: "bg-blue-500/15 text-blue-300",
  acceptee: "bg-emerald-500/15 text-emerald-300",
  refusee: "bg-rose-500/15 text-rose-300",
  expiree: "bg-amber-500/15 text-amber-300"
};

const PROJ_CLS: Record<string, string> = {
  planifie: "bg-white/5 text-white/60",
  en_attente: "bg-violet-500/15 text-violet-300",
  en_cours: "bg-blue-500/15 text-blue-300",
  suspendu: "bg-amber-500/15 text-amber-300",
  livre: "bg-emerald-500/15 text-emerald-300"
};

const INV_CLS: Record<string, string> = {
  brouillon: "bg-white/5 text-white/60",
  envoyee: "bg-blue-500/15 text-blue-300",
  payee: "bg-emerald-500/15 text-emerald-300",
  annulee: "bg-rose-500/15 text-rose-300"
};

export default function DevlogClientDetailPage() {
  const { onOpenSidebar } = useDevlogLayout();
  const params = useParams<{ id: string }>();
  const clientId = Number(params?.id);
  const confirm = useConfirm();

  const [client, setClient] = useState<Client | null>(null);
  const [soumissions, setSoumissions] = useState<Soumission[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [invoices, setInvoices] = useState<Invoice[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [name, setName] = useState("");
  const [company, setCompany] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [address, setAddress] = useState("");
  const [website, setWebsite] = useState("");
  const [statusStr, setStatusStr] = useState("active");
  const [notes, setNotes] = useState("");

  async function loadAll() {
    try {
      const [cr, sr, pr, ir] = await Promise.all([
        authedFetch(`/api/v1/devlog/clients/${clientId}`),
        authedFetch(`/api/v1/devlog/clients/${clientId}/soumissions`),
        authedFetch(`/api/v1/devlog/clients/${clientId}/projects`),
        authedFetch(`/api/v1/devlog/clients/${clientId}/invoices`)
      ]);
      if (!cr.ok) throw new Error("Client introuvable");
      const data = (await cr.json()) as Client;
      setClient(data);
      setName(data.name);
      setCompany(data.company ?? "");
      setEmail(data.email ?? "");
      setPhone(data.phone ?? "");
      setAddress(data.address ?? "");
      setWebsite(data.website ?? "");
      setStatusStr(data.status);
      setNotes(data.notes ?? "");
      if (sr.ok) setSoumissions((await sr.json()) as Soumission[]);
      if (pr.ok) setProjects((await pr.json()) as Project[]);
      if (ir.ok) setInvoices((await ir.json()) as Invoice[]);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erreur");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (Number.isFinite(clientId)) void loadAll();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [clientId]);

  const isDirty = useMemo(() => {
    if (!client) return false;
    return (
      name !== client.name ||
      company !== (client.company ?? "") ||
      email !== (client.email ?? "") ||
      phone !== (client.phone ?? "") ||
      address !== (client.address ?? "") ||
      website !== (client.website ?? "") ||
      statusStr !== client.status ||
      notes !== (client.notes ?? "")
    );
  }, [client, name, company, email, phone, address, website, statusStr, notes]);

  async function save() {
    if (!isDirty) return;
    setSaving(true);
    try {
      const r = await authedFetch(`/api/v1/devlog/clients/${clientId}`, {
        method: "PATCH",
        body: JSON.stringify({
          name: name.trim(),
          company: company.trim() || null,
          email: email.trim() || null,
          phone: phone.trim() || null,
          address: address.trim() || null,
          website: website.trim() || null,
          status: statusStr,
          notes: notes.trim() || null
        })
      });
      if (!r.ok) throw new Error();
      setClient(await r.json());
    } catch {
      setError("Enregistrement impossible");
    } finally {
      setSaving(false);
    }
  }

  async function newSoumission() {
    const title = window.prompt("Titre de la soumission ?");
    if (!title || !title.trim()) return;
    try {
      const r = await authedFetch("/api/v1/devlog/soumissions", {
        method: "POST",
        body: JSON.stringify({
          title: title.trim(),
          client_id: clientId,
          status: "brouillon"
        })
      });
      if (!r.ok) throw new Error();
      const c = (await r.json()) as { id: number };
      window.location.href = `/dev-logiciel/soumissions/${c.id}`;
    } catch {
      setError("Création soumission impossible");
    }
  }

  async function newProject() {
    const nm = window.prompt("Nom du projet ?");
    if (!nm || !nm.trim()) return;
    try {
      const r = await authedFetch("/api/v1/devlog/projects", {
        method: "POST",
        body: JSON.stringify({
          name: nm.trim(),
          client_id: clientId,
          status: "planifie"
        })
      });
      if (!r.ok) throw new Error();
      const p = (await r.json()) as { id: number };
      window.location.href = `/dev-logiciel/projets/${p.id}`;
    } catch {
      setError("Création projet impossible");
    }
  }

  async function newInvoice() {
    try {
      const r = await authedFetch("/api/v1/devlog/invoices", {
        method: "POST",
        body: JSON.stringify({
          client_id: clientId,
          status: "brouillon"
        })
      });
      if (!r.ok) throw new Error();
      await loadAll();
    } catch {
      setError("Création facture impossible");
    }
  }

  async function deleteClient() {
    const ok = await confirm({
      title: "Supprimer ce client ?",
      description:
        "Les soumissions / projets / factures liés ne seront PAS supprimés (juste désaffiliés).",
      confirmLabel: "Supprimer",
      destructive: true
    });
    if (!ok) return;
    try {
      const r = await authedFetch(`/api/v1/devlog/clients/${clientId}`, {
        method: "DELETE"
      });
      if (!r.ok) throw new Error();
      window.location.href = "/dev-logiciel/clients";
    } catch {
      setError("Suppression impossible");
    }
  }

  const inputCls = "input text-sm";

  return (
    <div className="min-h-screen bg-brand-950">
      <AppTopbar
        breadcrumbs={[
          { label: "Développement logiciel", href: "/dev-logiciel" as any },
          { label: "Clients", href: "/dev-logiciel/clients" as any },
          { label: client?.name ?? `Client #${clientId}` }
        ]}
        onOpenSidebar={onOpenSidebar}
      />

      <div className="mx-auto max-w-5xl px-4 py-5 lg:px-6">
        <div className="mb-4">
          <Link
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            href={"/dev-logiciel/clients" as any}
            className="inline-flex items-center gap-1.5 text-xs text-white/50 hover:text-white"
          >
            <ArrowLeft className="h-3 w-3" /> Retour aux clients
          </Link>
        </div>

        {error ? (
          <div className="mb-3 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-300">
            {error}
          </div>
        ) : null}

        {loading ? (
          <div className="mt-10 flex justify-center">
            <Loader2 className="h-6 w-6 animate-spin text-blue-500" />
          </div>
        ) : !client ? (
          <p className="text-center text-sm text-white/40">Client introuvable.</p>
        ) : (
          <>
            <header className="mb-5 flex flex-wrap items-start justify-between gap-3">
              <div className="flex items-center gap-3">
                <span className="flex h-12 w-12 items-center justify-center rounded-xl bg-blue-500/15 text-sm font-bold text-blue-300">
                  {client.name.slice(0, 2).toUpperCase()}
                </span>
                <div>
                  <h1 className="text-2xl font-bold text-white">{client.name}</h1>
                  <p className="mt-0.5 flex flex-wrap items-center gap-2 text-xs text-white/50">
                    {client.company ? <span>{client.company}</span> : null}
                    <span
                      className={`rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${
                        client.status === "active"
                          ? "bg-emerald-500/15 text-emerald-300"
                          : "bg-white/5 text-white/40"
                      }`}
                    >
                      {client.status === "active" ? "Actif" : "Archivé"}
                    </span>
                  </p>
                </div>
              </div>
              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  onClick={newSoumission}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-blue-500/40 bg-blue-500/10 px-3 py-1.5 text-xs font-semibold text-blue-300 hover:bg-blue-500/20"
                >
                  <FileText className="h-3.5 w-3.5" /> Soumission
                </button>
                <button
                  type="button"
                  onClick={newProject}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-blue-500/40 bg-blue-500/10 px-3 py-1.5 text-xs font-semibold text-blue-300 hover:bg-blue-500/20"
                >
                  <FolderKanban className="h-3.5 w-3.5" /> Projet
                </button>
                <button
                  type="button"
                  onClick={newInvoice}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-blue-500/40 bg-blue-500/10 px-3 py-1.5 text-xs font-semibold text-blue-300 hover:bg-blue-500/20"
                >
                  <Receipt className="h-3.5 w-3.5" /> Facture
                </button>
                <button
                  type="button"
                  onClick={deleteClient}
                  title="Supprimer le client"
                  className="rounded-lg border border-rose-500/40 bg-rose-500/10 p-1.5 text-rose-300 hover:bg-rose-500/20"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </div>
            </header>

            <div className="grid gap-4 lg:grid-cols-3">
              <section className="lg:col-span-2 space-y-4">
                <div className="rounded-2xl border border-brand-800 bg-brand-900 p-5">
                  <h2 className="mb-3 text-sm font-bold text-white">
                    Coordonnées
                  </h2>
                  <div className="space-y-3">
                    <Field label="Nom du contact *">
                      <input
                        value={name}
                        onChange={(e) => setName(e.target.value)}
                        className={inputCls}
                      />
                    </Field>
                    <Field label="Entreprise">
                      <input
                        value={company}
                        onChange={(e) => setCompany(e.target.value)}
                        className={inputCls}
                      />
                    </Field>
                    <div className="grid grid-cols-2 gap-3">
                      <Field label="Courriel">
                        <input
                          value={email}
                          onChange={(e) => setEmail(e.target.value)}
                          className={inputCls}
                        />
                      </Field>
                      <Field label="Téléphone">
                        <input
                          value={phone}
                          onChange={(e) => setPhone(e.target.value)}
                          className={inputCls}
                        />
                      </Field>
                    </div>
                    <Field label="Adresse">
                      <input
                        value={address}
                        onChange={(e) => setAddress(e.target.value)}
                        className={inputCls}
                      />
                    </Field>
                    <div className="grid grid-cols-2 gap-3">
                      <Field label="Site web">
                        <input
                          value={website}
                          onChange={(e) => setWebsite(e.target.value)}
                          className={inputCls}
                        />
                      </Field>
                      <Field label="Statut">
                        <select
                          value={statusStr}
                          onChange={(e) => setStatusStr(e.target.value)}
                          className={inputCls}
                        >
                          <option value="active">Actif</option>
                          <option value="archived">Archivé</option>
                        </select>
                      </Field>
                    </div>
                    <Field label="Notes internes">
                      <textarea
                        value={notes}
                        onChange={(e) => setNotes(e.target.value)}
                        rows={4}
                        className={inputCls}
                      />
                    </Field>
                  </div>
                  {isDirty ? (
                    <div className="mt-4 flex items-center justify-end gap-2">
                      <button
                        type="button"
                        onClick={() => void loadAll()}
                        className="rounded-md border border-white/15 px-3 py-1.5 text-xs text-white/60 hover:bg-brand-800"
                      >
                        Annuler
                      </button>
                      <button
                        type="button"
                        onClick={() => void save()}
                        disabled={saving}
                        className="inline-flex items-center gap-1.5 rounded-md bg-blue-500 px-3 py-1.5 text-xs font-semibold text-white hover:bg-blue-400 disabled:opacity-50"
                      >
                        {saving ? (
                          <Loader2 className="h-3 w-3 animate-spin" />
                        ) : null}
                        Enregistrer
                      </button>
                    </div>
                  ) : null}
                </div>
              </section>

              <section className="space-y-4">
                <RelatedList
                  title="Soumissions"
                  icon={<FileText className="h-3.5 w-3.5" />}
                  items={soumissions.map((s) => ({
                    id: s.id,
                    href: `/dev-logiciel/soumissions/${s.id}`,
                    title: s.title,
                    subtitle: fmtAmount(s.amount),
                    badge: s.status,
                    badgeCls: SOUM_CLS[s.status]
                  }))}
                  onAdd={newSoumission}
                />
                <RelatedList
                  title="Projets"
                  icon={<FolderKanban className="h-3.5 w-3.5" />}
                  items={projects.map((p) => ({
                    id: p.id,
                    href: `/dev-logiciel/projets/${p.id}`,
                    title: p.name,
                    subtitle: p.due_date
                      ? `Échéance ${p.due_date}`
                      : p.start_date
                      ? `Début ${p.start_date}`
                      : "—",
                    badge: p.status,
                    badgeCls: PROJ_CLS[p.status]
                  }))}
                  onAdd={newProject}
                />
                <RelatedList
                  title="Factures"
                  icon={<Receipt className="h-3.5 w-3.5" />}
                  items={invoices.map((i) => ({
                    id: i.id,
                    href: `/dev-logiciel/facturation`,
                    title: i.number ?? `Facture #${i.id}`,
                    subtitle: fmtAmount(i.amount),
                    badge: i.status,
                    badgeCls: INV_CLS[i.status]
                  }))}
                  onAdd={newInvoice}
                />
              </section>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

function RelatedList({
  title,
  icon,
  items,
  onAdd
}: {
  title: string;
  icon?: React.ReactNode;
  items: Array<{
    id: number;
    href: string;
    title: string;
    subtitle?: string;
    badge?: string;
    badgeCls?: string;
  }>;
  onAdd?: () => void;
}) {
  return (
    <div className="rounded-2xl border border-brand-800 bg-brand-900 p-5">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="inline-flex items-center gap-1.5 text-sm font-bold text-white">
          {icon} {title}
        </h2>
        <div className="flex items-center gap-2">
          <span className="rounded-full bg-white/5 px-2 text-[10px] font-bold text-white/50">
            {items.length}
          </span>
          {onAdd ? (
            <button
              type="button"
              onClick={onAdd}
              title="Ajouter"
              className="rounded-md p-1 text-white/40 hover:bg-brand-800 hover:text-white"
            >
              <Plus className="h-3.5 w-3.5" />
            </button>
          ) : null}
        </div>
      </div>
      {items.length === 0 ? (
        <p className="text-xs text-white/40">Rien à afficher.</p>
      ) : (
        <ul className="space-y-1.5">
          {items.map((it) => (
            <li key={it.id}>
              <Link
                // eslint-disable-next-line @typescript-eslint/no-explicit-any
                href={it.href as any}
                className="flex items-center justify-between gap-2 rounded-lg border border-brand-800 bg-brand-950 px-3 py-2 hover:border-blue-500/40"
              >
                <div className="min-w-0">
                  <p className="truncate text-xs font-semibold text-white">
                    {it.title}
                  </p>
                  {it.subtitle ? (
                    <p className="text-[10px] text-white/40">{it.subtitle}</p>
                  ) : null}
                </div>
                {it.badge ? (
                  <span
                    className={`flex-shrink-0 rounded px-1.5 py-0.5 text-[9px] uppercase tracking-wide ${
                      it.badgeCls ?? "bg-white/5 text-white/50"
                    }`}
                  >
                    {it.badge}
                  </span>
                ) : null}
              </Link>
            </li>
          ))}
        </ul>
      )}
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
