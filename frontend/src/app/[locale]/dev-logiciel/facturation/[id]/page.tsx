"use client";

import { useEffect, useMemo, useState } from "react";
import { useParams } from "next/navigation";
import {
  ArrowLeft,
  CheckCircle2,
  Copy,
  Download,
  FileDown,
  Loader2,
  Mail,
  Plus,
  Send,
  Trash2,
  X
} from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { useConfirm } from "@/components/confirm-dialog";
import { Link } from "@/i18n/navigation";
import { authedFetch } from "@/lib/auth";
import { TPS_RATE, TVQ_RATE } from "@/lib/tax";
import { useDevlogLayout } from "../../layout";
import { EntityDriveSection } from "@/components/drive/EntityDriveSection";

type Invoice = {
  id: number;
  number: string | null;
  client_id: number | null;
  project_id: number | null;
  amount: number | null;
  status: string;
  issued_date: string | null;
  due_date: string | null;
  notes: string | null;
  signature_token: string | null;
  sent_at: string | null;
  paid_at: string | null;
  created_at: string;
  updated_at: string;
};

type Item = {
  id: number;
  invoice_id: number;
  position: number;
  description: string;
  unit: string | null;
  quantity: number;
  unit_price: number;
  total: number;
  source_kind: string | null;
  notes: string | null;
};

type RefItem = { id: number; name: string };
type SoumRef = { id: number; title: string };
type ProjectRef = { id: number; name: string };

const STATUS_OPTIONS = [
  { key: "brouillon", label: "Brouillon" },
  { key: "envoyee", label: "Envoyée" },
  { key: "payee", label: "Payée" },
  { key: "annulee", label: "Annulée" }
];

const STATUS_CLS: Record<string, string> = {
  brouillon: "badge-neutral",
  envoyee: "badge-blue",
  payee: "badge-emerald",
  annulee: "badge-rose"
};

function fmtAmount(n: number | null): string {
  if (n == null) return "—";
  return n.toLocaleString("fr-CA", {
    style: "currency",
    currency: "CAD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2
  });
}

export default function DevlogInvoiceDetailPage() {
  const { onOpenSidebar } = useDevlogLayout();
  const params = useParams<{ id: string }>();
  const invoiceId = Number(params?.id);
  const confirm = useConfirm();

  const [inv, setInv] = useState<Invoice | null>(null);
  const [items, setItems] = useState<Item[]>([]);
  const [clients, setClients] = useState<RefItem[]>([]);
  const [projects, setProjects] = useState<ProjectRef[]>([]);
  const [soumissions, setSoumissions] = useState<SoumRef[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Form draft.
  const [number, setNumber] = useState("");
  const [clientId, setClientId] = useState("");
  const [projectId, setProjectId] = useState("");
  const [statusStr, setStatusStr] = useState("brouillon");
  const [issuedDate, setIssuedDate] = useState("");
  const [dueDate, setDueDate] = useState("");
  const [notes, setNotes] = useState("");

  // Import dialog.
  const [importOpen, setImportOpen] = useState(false);
  const [importProject, setImportProject] = useState("");
  const [importHours, setImportHours] = useState(true);
  const [importRate, setImportRate] = useState("");
  const [importSoumission, setImportSoumission] = useState(false);
  const [importSoumissionId, setImportSoumissionId] = useState("");
  const [importBusy, setImportBusy] = useState(false);

  async function loadAll() {
    try {
      const [ir, itr, cr, pr, sr] = await Promise.all([
        authedFetch(`/api/v1/devlog/invoices/${invoiceId}`),
        authedFetch(`/api/v1/devlog/invoices/${invoiceId}/items`),
        authedFetch("/api/v1/devlog/clients"),
        authedFetch("/api/v1/devlog/projects"),
        authedFetch("/api/v1/devlog/soumissions")
      ]);
      if (!ir.ok) throw new Error("Facture introuvable");
      const data = (await ir.json()) as Invoice;
      setInv(data);
      setNumber(data.number ?? "");
      setClientId(data.client_id ? String(data.client_id) : "");
      setProjectId(data.project_id ? String(data.project_id) : "");
      setStatusStr(data.status);
      setIssuedDate(data.issued_date ?? "");
      setDueDate(data.due_date ?? "");
      setNotes(data.notes ?? "");
      if (itr.ok) setItems((await itr.json()) as Item[]);
      if (cr.ok) setClients((await cr.json()) as RefItem[]);
      if (pr.ok) setProjects((await pr.json()) as ProjectRef[]);
      if (sr.ok) setSoumissions((await sr.json()) as SoumRef[]);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erreur");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (Number.isFinite(invoiceId)) void loadAll();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [invoiceId]);

  const isDirty = useMemo(() => {
    if (!inv) return false;
    return (
      number !== (inv.number ?? "") ||
      clientId !== (inv.client_id ? String(inv.client_id) : "") ||
      projectId !== (inv.project_id ? String(inv.project_id) : "") ||
      statusStr !== inv.status ||
      issuedDate !== (inv.issued_date ?? "") ||
      dueDate !== (inv.due_date ?? "") ||
      notes !== (inv.notes ?? "")
    );
  }, [inv, number, clientId, projectId, statusStr, issuedDate, dueDate, notes]);

  const total = useMemo(
    () => items.reduce((s, it) => s + (it.total || 0), 0),
    [items]
  );

  async function saveHeader() {
    setSaving(true);
    try {
      const r = await authedFetch(`/api/v1/devlog/invoices/${invoiceId}`, {
        method: "PATCH",
        body: JSON.stringify({
          number: number.trim() || null,
          client_id: clientId ? Number(clientId) : null,
          project_id: projectId ? Number(projectId) : null,
          status: statusStr,
          issued_date: issuedDate || null,
          due_date: dueDate || null,
          notes: notes.trim() || null
        })
      });
      if (!r.ok) throw new Error();
      setInv(await r.json());
    } catch {
      setError("Enregistrement impossible");
    } finally {
      setSaving(false);
    }
  }

  async function addItem() {
    try {
      const r = await authedFetch("/api/v1/devlog/invoice-items", {
        method: "POST",
        body: JSON.stringify({
          invoice_id: invoiceId,
          position: items.length,
          description: "Nouvelle ligne",
          quantity: 1,
          unit_price: 0
        })
      });
      if (!r.ok) throw new Error();
      await loadAll();
    } catch {
      setError("Ajout ligne impossible");
    }
  }

  async function patchItem(id: number, patch: Record<string, unknown>) {
    setItems((xs) =>
      xs.map((it) =>
        it.id === id
          ? {
              ...it,
              ...patch,
              total:
                patch.quantity !== undefined || patch.unit_price !== undefined
                  ? Number(
                      (
                        Number(patch.quantity ?? it.quantity) *
                        Number(patch.unit_price ?? it.unit_price)
                      ).toFixed(2)
                    )
                  : it.total
            }
          : it
      )
    );
    try {
      const r = await authedFetch(`/api/v1/devlog/invoice-items/${id}`, {
        method: "PATCH",
        body: JSON.stringify(patch)
      });
      if (!r.ok) throw new Error();
      const updated = (await r.json()) as Item;
      setItems((xs) => xs.map((it) => (it.id === id ? updated : it)));
      const ir = await authedFetch(`/api/v1/devlog/invoices/${invoiceId}`);
      if (ir.ok) setInv((await ir.json()) as Invoice);
    } catch {
      setError("Mise à jour ligne impossible");
    }
  }

  async function deleteItem(id: number) {
    setItems((xs) => xs.filter((it) => it.id !== id));
    try {
      await authedFetch(`/api/v1/devlog/invoice-items/${id}`, {
        method: "DELETE"
      });
      const ir = await authedFetch(`/api/v1/devlog/invoices/${invoiceId}`);
      if (ir.ok) setInv((await ir.json()) as Invoice);
    } catch {
      void loadAll();
    }
  }

  async function deleteInvoice() {
    const ok = await confirm({
      title: "Supprimer cette facture ?",
      description: "Toutes ses lignes seront supprimées.",
      confirmLabel: "Supprimer",
      destructive: true
    });
    if (!ok) return;
    try {
      const r = await authedFetch(`/api/v1/devlog/invoices/${invoiceId}`, {
        method: "DELETE"
      });
      if (!r.ok) throw new Error();
      window.location.href = "/dev-logiciel/facturation";
    } catch {
      setError("Suppression impossible");
    }
  }

  async function runImport() {
    if (!importProject) {
      setError("Choisis un projet à importer.");
      return;
    }
    setImportBusy(true);
    try {
      const r = await authedFetch(
        `/api/v1/devlog/invoices/${invoiceId}/import-sources`,
        {
          method: "POST",
          body: JSON.stringify({
            project_id: Number(importProject),
            include_hours: importHours,
            hourly_rate: importRate ? Number(importRate) : null,
            include_soumission: importSoumission,
            soumission_id: importSoumissionId ? Number(importSoumissionId) : null
          })
        }
      );
      if (!r.ok) throw new Error();
      setImportOpen(false);
      await loadAll();
    } catch {
      setError("Import impossible");
    } finally {
      setImportBusy(false);
    }
  }

  const [sending, setSending] = useState(false);
  const [copyOk, setCopyOk] = useState(false);

  async function markPaid() {
    try {
      const r = await authedFetch(
        `/api/v1/devlog/invoices/${invoiceId}/mark-paid`,
        { method: "POST" }
      );
      if (!r.ok) throw new Error();
      await loadAll();
    } catch {
      setError("Mise à jour impossible");
    }
  }

  async function sendInvoice() {
    if (sending) return;
    const ok = await confirm({
      title: "Envoyer la facture au client ?",
      description:
        "Le PDF sera généré et envoyé par courriel. Un lien public " +
        "permettra au client de consulter la facture en ligne.",
      confirmLabel: "Envoyer"
    });
    if (!ok) return;
    setSending(true);
    try {
      const r = await authedFetch(
        `/api/v1/devlog/invoices/${invoiceId}/send`,
        { method: "POST" }
      );
      if (!r.ok) {
        const t = await r.text();
        throw new Error(t.slice(0, 200) || "Envoi impossible");
      }
      await loadAll();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Envoi impossible");
    } finally {
      setSending(false);
    }
  }

  function publicUrl(): string | null {
    if (!inv?.signature_token) return null;
    const origin =
      typeof window !== "undefined" ? window.location.origin : "";
    return `${origin}/devlog/pay-invoice/${inv.signature_token}`;
  }

  async function copyPublicLink() {
    const url = publicUrl();
    if (!url) return;
    try {
      await navigator.clipboard.writeText(url);
      setCopyOk(true);
      window.setTimeout(() => setCopyOk(false), 1800);
    } catch {
      setError("Copie impossible — copie le lien manuellement.");
    }
  }

  function fmtDate(iso: string | null): string {
    if (!iso) return "—";
    return new Date(iso).toLocaleDateString("fr-CA", {
      day: "numeric",
      month: "short",
      year: "numeric"
    });
  }

  const sousTotal = useMemo(
    () => Number(total.toFixed(2)),
    [total]
  );
  const tps = useMemo(
    () => Number((sousTotal * TPS_RATE).toFixed(2)),
    [sousTotal]
  );
  const tvq = useMemo(
    () => Number((sousTotal * TVQ_RATE).toFixed(2)),
    [sousTotal]
  );
  const grandTotal = useMemo(
    () => Number((sousTotal + tps + tvq).toFixed(2)),
    [sousTotal, tps, tvq]
  );

  const inputCls = "input text-sm";

  return (
    <div className="min-h-screen bg-brand-950">
      <AppTopbar
        breadcrumbs={[
          { label: "Développement logiciel", href: "/dev-logiciel" as any },
          { label: "Facturation", href: "/dev-logiciel/facturation" as any },
          { label: inv?.number ?? `Facture #${invoiceId}` }
        ]}
        onOpenSidebar={onOpenSidebar}
      />

      <div className="mx-auto max-w-5xl px-4 py-5 lg:px-6">
        <div className="mb-4">
          <Link
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            href={"/dev-logiciel/facturation" as any}
            className="inline-flex items-center gap-1.5 text-xs text-white/50 hover:text-white"
          >
            <ArrowLeft className="h-3 w-3" /> Retour à la facturation
          </Link>
        </div>

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
            <Loader2 className="h-6 w-6 animate-spin text-accent-500" />
          </div>
        ) : !inv ? (
          <p className="text-center text-sm text-white/40">Facture introuvable.</p>
        ) : (
          <>
            <EntityDriveSection
              entityType="DevlogInvoice"
              entityId={inv.id}
              pole="Développement logiciel"
              label="Facture"
              route="/dev-logiciel/facturation/[id]"
            />
            <header className="mb-4 flex flex-wrap items-start justify-between gap-3">
              <div>
                <h1 className="text-2xl font-bold text-white">
                  {inv.number ?? `Facture #${inv.id}`}
                </h1>
                <p className="mt-1 flex flex-wrap items-center gap-2 text-xs text-white/50">
                  <span
                    className={`badge uppercase tracking-wide ${
                      STATUS_CLS[inv.status] ?? "badge-neutral"
                    }`}
                  >
                    {STATUS_OPTIONS.find((s) => s.key === inv.status)?.label ??
                      inv.status}
                  </span>
                  <span className="text-sm font-bold text-white">
                    {fmtAmount(total)}
                  </span>
                </p>
              </div>
              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  onClick={() => setImportOpen(true)}
                  className="btn-outline-accent btn-sm"
                >
                  <Download className="h-3.5 w-3.5" />
                  Importer du projet
                </button>
                <a
                  href={`/api/v1/devlog/invoices/${invoiceId}/pdf`}
                  target="_blank"
                  rel="noreferrer"
                  className="btn-secondary btn-sm"
                >
                  <FileDown className="h-3.5 w-3.5" />
                  Télécharger PDF
                </a>
                {inv.status !== "payee" && inv.status !== "annulee" ? (
                  <button
                    type="button"
                    onClick={() => void sendInvoice()}
                    disabled={sending}
                    className="btn-accent btn-sm disabled:opacity-50"
                  >
                    {sending ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    ) : (
                      <Mail className="h-3.5 w-3.5" />
                    )}
                    {inv.sent_at ? "Renvoyer" : "Envoyer au client"}
                  </button>
                ) : null}
                {inv.signature_token ? (
                  <button
                    type="button"
                    onClick={() => void copyPublicLink()}
                    className="btn-secondary btn-sm"
                  >
                    {copyOk ? (
                      <CheckCircle2 className="h-3.5 w-3.5 text-emerald-300" />
                    ) : (
                      <Copy className="h-3.5 w-3.5" />
                    )}
                    {copyOk ? "Copié !" : "Copier le lien public"}
                  </button>
                ) : null}
                {inv.status !== "payee" && inv.status !== "annulee" ? (
                  <button
                    type="button"
                    onClick={() => void markPaid()}
                    className="inline-flex items-center gap-1.5 rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-3 py-1.5 text-xs font-semibold text-emerald-300 hover:bg-emerald-500/20"
                  >
                    <CheckCircle2 className="h-3.5 w-3.5" />
                    Marquer payée
                  </button>
                ) : null}
                <button
                  type="button"
                  onClick={deleteInvoice}
                  className="btn-outline-rose btn-xs"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </div>
            </header>

            {inv.status === "payee" && inv.paid_at ? (
              <div className="mb-3 inline-flex items-center gap-2 rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-xs font-semibold text-emerald-300">
                <CheckCircle2 className="h-4 w-4" />
                Payée le {fmtDate(inv.paid_at)}
              </div>
            ) : inv.sent_at ? (
              <div className="mb-3 inline-flex items-center gap-2 rounded-lg border border-blue-500/40 bg-blue-500/10 px-3 py-2 text-xs font-semibold text-blue-300">
                <Send className="h-4 w-4" />
                Envoyée le {fmtDate(inv.sent_at)}
              </div>
            ) : null}

            <section className="mb-4 rounded-2xl border border-brand-800 bg-brand-900 p-5">
              <h2 className="mb-3 text-sm font-bold text-white">En-tête</h2>
              <div className="grid grid-cols-2 gap-3">
                <Field label="Numéro">
                  <input
                    value={number}
                    onChange={(e) => setNumber(e.target.value)}
                    className={inputCls}
                    placeholder="ex. 2026-001"
                  />
                </Field>
                <Field label="Statut">
                  <select
                    value={statusStr}
                    onChange={(e) => setStatusStr(e.target.value)}
                    className={inputCls}
                  >
                    {STATUS_OPTIONS.map((s) => (
                      <option key={s.key} value={s.key}>
                        {s.label}
                      </option>
                    ))}
                  </select>
                </Field>
                <Field label="Client">
                  <select
                    value={clientId}
                    onChange={(e) => setClientId(e.target.value)}
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
                    value={projectId}
                    onChange={(e) => setProjectId(e.target.value)}
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
                <Field label="Date d'émission">
                  <input
                    type="date"
                    value={issuedDate}
                    onChange={(e) => setIssuedDate(e.target.value)}
                    className={inputCls}
                  />
                </Field>
                <Field label="Échéance">
                  <input
                    type="date"
                    value={dueDate}
                    onChange={(e) => setDueDate(e.target.value)}
                    className={inputCls}
                  />
                </Field>
              </div>
              <div className="mt-3">
                <Field label="Notes">
                  <textarea
                    value={notes}
                    onChange={(e) => setNotes(e.target.value)}
                    rows={3}
                    className={inputCls}
                  />
                </Field>
              </div>
              {isDirty ? (
                <div className="mt-3 flex items-center justify-end gap-2">
                  <button
                    type="button"
                    onClick={() => void loadAll()}
                    className="btn-secondary btn-sm"
                  >
                    Annuler
                  </button>
                  <button
                    type="button"
                    onClick={() => void saveHeader()}
                    disabled={saving}
                    className="btn-accent btn-sm disabled:opacity-50"
                  >
                    {saving ? <Loader2 className="h-3 w-3 animate-spin" /> : null}
                    Enregistrer
                  </button>
                </div>
              ) : null}
            </section>

            <section className="rounded-2xl border border-brand-800 bg-brand-900 p-5">
              <div className="mb-3 flex items-center justify-between">
                <h2 className="text-sm font-bold text-white">
                  Lignes ({items.length})
                </h2>
                <button
                  type="button"
                  onClick={addItem}
                  className="btn-accent btn-sm"
                >
                  <Plus className="h-3 w-3" />
                  Ajouter une ligne
                </button>
              </div>
              {items.length === 0 ? (
                <p className="py-4 text-center text-xs text-white/40">
                  Aucune ligne. Ajoute manuellement ou importe depuis un projet.
                </p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-xs">
                    <thead className="border-b border-brand-800 text-[10px] uppercase tracking-wider text-white/40">
                      <tr>
                        <th className="px-2 py-2 text-left">Description</th>
                        <th className="px-2 py-2 text-right">Unité</th>
                        <th className="px-2 py-2 text-right">Qté</th>
                        <th className="px-2 py-2 text-right">Prix unit.</th>
                        <th className="px-2 py-2 text-right">Total</th>
                        <th className="px-2 py-2"></th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-brand-800">
                      {items.map((it) => (
                        <tr key={it.id}>
                          <td className="px-2 py-1.5">
                            <input
                              value={it.description}
                              onChange={(e) =>
                                setItems((xs) =>
                                  xs.map((x) =>
                                    x.id === it.id
                                      ? { ...x, description: e.target.value }
                                      : x
                                  )
                                )
                              }
                              onBlur={(e) =>
                                void patchItem(it.id, {
                                  description: e.target.value
                                })
                              }
                              className="w-full rounded border border-brand-700 bg-brand-950 px-1.5 py-1 text-white"
                            />
                            {it.source_kind ? (
                              <span className="badge badge-neutral mt-0.5 uppercase">
                                {it.source_kind}
                              </span>
                            ) : null}
                          </td>
                          <td className="px-2 py-1.5">
                            <input
                              value={it.unit ?? ""}
                              onChange={(e) =>
                                setItems((xs) =>
                                  xs.map((x) =>
                                    x.id === it.id
                                      ? { ...x, unit: e.target.value }
                                      : x
                                  )
                                )
                              }
                              onBlur={(e) =>
                                void patchItem(it.id, {
                                  unit: e.target.value || null
                                })
                              }
                              className="w-16 rounded border border-brand-700 bg-brand-950 px-1.5 py-1 text-right text-white"
                            />
                          </td>
                          <td className="px-2 py-1.5">
                            <input
                              type="number"
                              step="0.5"
                              value={it.quantity}
                              onChange={(e) =>
                                setItems((xs) =>
                                  xs.map((x) =>
                                    x.id === it.id
                                      ? { ...x, quantity: Number(e.target.value) }
                                      : x
                                  )
                                )
                              }
                              onBlur={(e) =>
                                void patchItem(it.id, {
                                  quantity: Number(e.target.value)
                                })
                              }
                              className="w-20 rounded border border-brand-700 bg-brand-950 px-1.5 py-1 text-right text-white"
                            />
                          </td>
                          <td className="px-2 py-1.5">
                            <input
                              type="number"
                              step="0.01"
                              value={it.unit_price}
                              onChange={(e) =>
                                setItems((xs) =>
                                  xs.map((x) =>
                                    x.id === it.id
                                      ? {
                                          ...x,
                                          unit_price: Number(e.target.value)
                                        }
                                      : x
                                  )
                                )
                              }
                              onBlur={(e) =>
                                void patchItem(it.id, {
                                  unit_price: Number(e.target.value)
                                })
                              }
                              className="w-24 rounded border border-brand-700 bg-brand-950 px-1.5 py-1 text-right text-white"
                            />
                          </td>
                          <td className="px-2 py-1.5 text-right font-semibold text-white">
                            {fmtAmount(it.total)}
                          </td>
                          <td className="px-2 py-1.5 text-center">
                            <button
                              type="button"
                              onClick={() => void deleteItem(it.id)}
                              className="btn-ghost btn-xs"
                            >
                              <Trash2 className="h-3 w-3" />
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                    <tfoot>
                      <tr className="border-t border-brand-800">
                        <td colSpan={4} className="px-2 py-2 text-right text-xs text-white/60">
                          Sous-total
                        </td>
                        <td className="px-2 py-2 text-right text-xs text-white/80">
                          {fmtAmount(sousTotal)}
                        </td>
                        <td></td>
                      </tr>
                      <tr>
                        <td colSpan={4} className="px-2 py-1 text-right text-xs text-white/60">
                          TPS (5%)
                        </td>
                        <td className="px-2 py-1 text-right text-xs text-white/80">
                          {fmtAmount(tps)}
                        </td>
                        <td></td>
                      </tr>
                      <tr>
                        <td colSpan={4} className="px-2 py-1 text-right text-xs text-white/60">
                          TVQ (9.975%)
                        </td>
                        <td className="px-2 py-1 text-right text-xs text-white/80">
                          {fmtAmount(tvq)}
                        </td>
                        <td></td>
                      </tr>
                      <tr className="border-t border-brand-800">
                        <td colSpan={4} className="px-2 py-3 text-right text-xs font-semibold text-white">
                          Total
                        </td>
                        <td className="px-2 py-3 text-right text-base font-bold text-white">
                          {fmtAmount(grandTotal)}
                        </td>
                        <td></td>
                      </tr>
                    </tfoot>
                  </table>
                </div>
              )}
            </section>
          </>
        )}
      </div>

      {/* Modal import */}
      {importOpen ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center px-4">
          <button
            type="button"
            aria-label="Fermer"
            onClick={() => (!importBusy ? setImportOpen(false) : null)}
            className="absolute inset-0 bg-black/70 backdrop-blur-sm"
          />
          <div className="relative w-full max-w-md rounded-2xl border border-brand-800 bg-brand-950 p-5 shadow-xl">
            <h3 className="mb-3 text-sm font-bold text-white">
              Importer depuis un projet
            </h3>
            <div className="space-y-3">
              <Field label="Projet *">
                <select
                  value={importProject}
                  onChange={(e) => setImportProject(e.target.value)}
                  className="input text-sm"
                >
                  <option value="">— Choisir un projet —</option>
                  {projects.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name}
                    </option>
                  ))}
                </select>
              </Field>

              <label className="flex items-center gap-2 text-sm text-white/80">
                <input
                  type="checkbox"
                  checked={importHours}
                  onChange={(e) => setImportHours(e.target.checked)}
                />
                Importer les heures (total agrégé)
              </label>
              {importHours ? (
                <Field label="Taux facturable ($/h)">
                  <input
                    type="number"
                    step="0.5"
                    value={importRate}
                    onChange={(e) => setImportRate(e.target.value)}
                    className="input text-sm"
                    placeholder="ex. 95"
                  />
                </Field>
              ) : null}

              <label className="flex items-center gap-2 text-sm text-white/80">
                <input
                  type="checkbox"
                  checked={importSoumission}
                  onChange={(e) => setImportSoumission(e.target.checked)}
                />
                Importer les lignes d'une soumission
              </label>
              {importSoumission ? (
                <Field label="Soumission">
                  <select
                    value={importSoumissionId}
                    onChange={(e) => setImportSoumissionId(e.target.value)}
                    className="input text-sm"
                  >
                    <option value="">— Choisir —</option>
                    {soumissions.map((s) => (
                      <option key={s.id} value={s.id}>
                        {s.title}
                      </option>
                    ))}
                  </select>
                </Field>
              ) : null}
            </div>
            <div className="mt-4 flex items-center justify-end gap-2">
              <button
                type="button"
                onClick={() => setImportOpen(false)}
                disabled={importBusy}
                className="btn-secondary btn-sm"
              >
                Annuler
              </button>
              <button
                type="button"
                onClick={() => void runImport()}
                disabled={
                  importBusy ||
                  !importProject ||
                  (!importHours && !importSoumission)
                }
                className="btn-accent btn-sm disabled:opacity-50"
              >
                {importBusy ? (
                  <Loader2 className="h-3 w-3 animate-spin" />
                ) : null}
                Importer
              </button>
            </div>
          </div>
        </div>
      ) : null}
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
