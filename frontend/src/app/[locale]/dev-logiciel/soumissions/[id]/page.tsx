"use client";

import { useEffect, useMemo, useState } from "react";
import { useParams } from "next/navigation";
import {
  ArrowLeft,
  Check,
  FolderPlus,
  Loader2,
  Plus,
  Receipt,
  Trash2,
  X
} from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { useConfirm } from "@/components/confirm-dialog";
import { Link } from "@/i18n/navigation";
import { authedFetch } from "@/lib/auth";
import { useDevlogLayout } from "../../layout";

type Soumission = {
  id: number;
  title: string;
  lead_id: number | null;
  client_id: number | null;
  amount: number | null;
  status: string;
  summary: string | null;
  notes: string | null;
  created_at: string;
  updated_at: string;
};

type Item = {
  id: number;
  soumission_id: number;
  position: number;
  description: string;
  unit: string | null;
  quantity: number;
  unit_price: number;
  total: number;
  notes: string | null;
};

type RefItem = { id: number; name: string };
type LeadRef = { id: number; name: string };

const STATUS_OPTIONS = [
  { key: "brouillon", label: "Brouillon" },
  { key: "envoyee", label: "Envoyée" },
  { key: "acceptee", label: "Acceptée" },
  { key: "refusee", label: "Refusée" },
  { key: "expiree", label: "Expirée" }
];

const STATUS_CLS: Record<string, string> = {
  brouillon: "bg-white/5 text-white/60",
  envoyee: "bg-blue-500/15 text-blue-300",
  acceptee: "bg-emerald-500/15 text-emerald-300",
  refusee: "bg-rose-500/15 text-rose-300",
  expiree: "bg-amber-500/15 text-amber-300"
};

function fmtAmount(n: number | null): string {
  if (n == null) return "—";
  return n.toLocaleString("fr-CA", {
    style: "currency",
    currency: "CAD",
    maximumFractionDigits: 2
  });
}

export default function DevlogSoumissionDetailPage() {
  const { onOpenSidebar } = useDevlogLayout();
  const params = useParams<{ id: string }>();
  const soumissionId = Number(params?.id);
  const confirm = useConfirm();

  const [soum, setSoum] = useState<Soumission | null>(null);
  const [items, setItems] = useState<Item[]>([]);
  const [leads, setLeads] = useState<LeadRef[]>([]);
  const [clients, setClients] = useState<RefItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [title, setTitle] = useState("");
  const [leadId, setLeadId] = useState("");
  const [clientId, setClientId] = useState("");
  const [statusStr, setStatusStr] = useState("brouillon");
  const [summary, setSummary] = useState("");
  const [notes, setNotes] = useState("");

  async function loadAll() {
    try {
      const [sr, ir, lr, cr] = await Promise.all([
        authedFetch(`/api/v1/devlog/soumissions/${soumissionId}`),
        authedFetch(`/api/v1/devlog/soumissions/${soumissionId}/items`),
        authedFetch("/api/v1/devlog/leads"),
        authedFetch("/api/v1/devlog/clients")
      ]);
      if (!sr.ok) throw new Error("Soumission introuvable");
      const data = (await sr.json()) as Soumission;
      setSoum(data);
      setTitle(data.title);
      setLeadId(data.lead_id ? String(data.lead_id) : "");
      setClientId(data.client_id ? String(data.client_id) : "");
      setStatusStr(data.status);
      setSummary(data.summary ?? "");
      setNotes(data.notes ?? "");
      if (ir.ok) setItems((await ir.json()) as Item[]);
      if (lr.ok) setLeads((await lr.json()) as LeadRef[]);
      if (cr.ok) setClients((await cr.json()) as RefItem[]);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erreur");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (Number.isFinite(soumissionId)) void loadAll();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [soumissionId]);

  const isDirty = useMemo(() => {
    if (!soum) return false;
    return (
      title !== soum.title ||
      leadId !== (soum.lead_id ? String(soum.lead_id) : "") ||
      clientId !== (soum.client_id ? String(soum.client_id) : "") ||
      statusStr !== soum.status ||
      summary !== (soum.summary ?? "") ||
      notes !== (soum.notes ?? "")
    );
  }, [soum, title, leadId, clientId, statusStr, summary, notes]);

  const total = useMemo(
    () => items.reduce((s, it) => s + (it.total || 0), 0),
    [items]
  );

  async function saveHeader() {
    setSaving(true);
    try {
      const r = await authedFetch(`/api/v1/devlog/soumissions/${soumissionId}`, {
        method: "PATCH",
        body: JSON.stringify({
          title: title.trim(),
          lead_id: leadId ? Number(leadId) : null,
          client_id: clientId ? Number(clientId) : null,
          status: statusStr,
          summary: summary.trim() || null,
          notes: notes.trim() || null
        })
      });
      if (!r.ok) throw new Error();
      setSoum(await r.json());
    } catch {
      setError("Enregistrement impossible");
    } finally {
      setSaving(false);
    }
  }

  async function addItem() {
    try {
      const r = await authedFetch("/api/v1/devlog/soumission-items", {
        method: "POST",
        body: JSON.stringify({
          soumission_id: soumissionId,
          position: items.length,
          description: "Nouvelle ligne",
          unit: "h",
          quantity: 1,
          unit_price: 0
        })
      });
      if (!r.ok) throw new Error();
      await loadAll();
    } catch {
      setError("Ajout de ligne impossible");
    }
  }

  async function patchItem(id: number, patch: Record<string, unknown>) {
    // Optimistic update.
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
      const r = await authedFetch(`/api/v1/devlog/soumission-items/${id}`, {
        method: "PATCH",
        body: JSON.stringify(patch)
      });
      if (!r.ok) throw new Error();
      // Refetch pour synchroniser le total de la soumission.
      const updated = (await r.json()) as Item;
      setItems((xs) => xs.map((it) => (it.id === id ? updated : it)));
      // Recharge soumission pour le total amount.
      const sr = await authedFetch(`/api/v1/devlog/soumissions/${soumissionId}`);
      if (sr.ok) setSoum((await sr.json()) as Soumission);
    } catch {
      setError("Mise à jour de ligne impossible");
    }
  }

  async function deleteItem(id: number) {
    setItems((xs) => xs.filter((it) => it.id !== id));
    try {
      await authedFetch(`/api/v1/devlog/soumission-items/${id}`, {
        method: "DELETE"
      });
      const sr = await authedFetch(`/api/v1/devlog/soumissions/${soumissionId}`);
      if (sr.ok) setSoum((await sr.json()) as Soumission);
    } catch {
      void loadAll();
    }
  }

  async function deleteSoumission() {
    const ok = await confirm({
      title: "Supprimer cette soumission ?",
      description: "Toutes ses lignes seront supprimées.",
      confirmLabel: "Supprimer",
      destructive: true
    });
    if (!ok) return;
    try {
      const r = await authedFetch(`/api/v1/devlog/soumissions/${soumissionId}`, {
        method: "DELETE"
      });
      if (!r.ok) throw new Error();
      window.location.href = "/dev-logiciel/soumissions";
    } catch {
      setError("Suppression impossible");
    }
  }

  async function setStatus(s: string) {
    setStatusStr(s);
    try {
      const r = await authedFetch(`/api/v1/devlog/soumissions/${soumissionId}`, {
        method: "PATCH",
        body: JSON.stringify({ status: s })
      });
      if (!r.ok) throw new Error();
      setSoum(await r.json());
    } catch {
      setError("Changement de statut impossible");
    }
  }

  async function createProjectFromSoum() {
    if (!soum?.client_id) {
      setError("Lier un client à la soumission avant de créer le projet.");
      return;
    }
    try {
      const r = await authedFetch("/api/v1/devlog/projects", {
        method: "POST",
        body: JSON.stringify({
          name: soum.title,
          client_id: soum.client_id,
          soumission_id: soum.id,
          status: "planifie"
        })
      });
      if (!r.ok) throw new Error();
      const c = (await r.json()) as { id: number };
      window.location.href = `/dev-logiciel/projets/${c.id}`;
    } catch {
      setError("Création projet impossible");
    }
  }

  async function createInvoiceFromSoum() {
    if (!soum?.client_id) {
      setError("Lier un client à la soumission avant de créer la facture.");
      return;
    }
    try {
      const r = await authedFetch("/api/v1/devlog/invoices", {
        method: "POST",
        body: JSON.stringify({
          client_id: soum.client_id,
          amount: total,
          status: "brouillon"
        })
      });
      if (!r.ok) throw new Error();
      window.location.href = `/dev-logiciel/facturation`;
    } catch {
      setError("Création facture impossible");
    }
  }

  const inputCls = "input text-sm";

  return (
    <div className="min-h-screen bg-brand-950">
      <AppTopbar
        breadcrumbs={[
          { label: "Développement logiciel", href: "/dev-logiciel" as any },
          { label: "Soumissions", href: "/dev-logiciel/soumissions" as any },
          { label: soum?.title ?? `Soumission #${soumissionId}` }
        ]}
        onOpenSidebar={onOpenSidebar}
      />

      <div className="mx-auto max-w-5xl px-4 py-5 lg:px-6">
        <div className="mb-4">
          <Link
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            href={"/dev-logiciel/soumissions" as any}
            className="inline-flex items-center gap-1.5 text-xs text-white/50 hover:text-white"
          >
            <ArrowLeft className="h-3 w-3" /> Retour
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
            <Loader2 className="h-6 w-6 animate-spin text-blue-500" />
          </div>
        ) : !soum ? (
          <p className="text-center text-sm text-white/40">Introuvable.</p>
        ) : (
          <>
            <header className="mb-4 flex flex-wrap items-start justify-between gap-3">
              <div>
                <h1 className="text-2xl font-bold text-white">{soum.title}</h1>
                <p className="mt-1 flex flex-wrap items-center gap-2 text-xs text-white/50">
                  <span
                    className={`rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${
                      STATUS_CLS[soum.status] ?? "bg-white/5 text-white/50"
                    }`}
                  >
                    {STATUS_OPTIONS.find((s) => s.key === soum.status)?.label ??
                      soum.status}
                  </span>
                  <span className="text-sm font-bold text-white">
                    {fmtAmount(total)}
                  </span>
                </p>
              </div>
              <div className="flex flex-wrap gap-2">
                {soum.status === "acceptee" ? (
                  <>
                    <button
                      type="button"
                      onClick={createProjectFromSoum}
                      className="inline-flex items-center gap-1.5 rounded-lg border border-blue-500/40 bg-blue-500/10 px-3 py-1.5 text-xs font-semibold text-blue-300 hover:bg-blue-500/20"
                    >
                      <FolderPlus className="h-3.5 w-3.5" />
                      Créer le projet
                    </button>
                    <button
                      type="button"
                      onClick={createInvoiceFromSoum}
                      className="inline-flex items-center gap-1.5 rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-3 py-1.5 text-xs font-semibold text-emerald-300 hover:bg-emerald-500/20"
                    >
                      <Receipt className="h-3.5 w-3.5" />
                      Créer la facture
                    </button>
                  </>
                ) : null}
                {soum.status === "brouillon" ? (
                  <button
                    type="button"
                    onClick={() => void setStatus("envoyee")}
                    className="inline-flex items-center gap-1.5 rounded-lg border border-blue-500/40 bg-blue-500/10 px-3 py-1.5 text-xs font-semibold text-blue-300 hover:bg-blue-500/20"
                  >
                    <Check className="h-3.5 w-3.5" />
                    Marquer envoyée
                  </button>
                ) : null}
                <button
                  type="button"
                  onClick={deleteSoumission}
                  className="rounded-lg border border-rose-500/40 bg-rose-500/10 p-1.5 text-rose-300 hover:bg-rose-500/20"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </div>
            </header>

            {/* En-tête éditable */}
            <section className="mb-4 rounded-2xl border border-brand-800 bg-brand-900 p-5">
              <h2 className="mb-3 text-sm font-bold text-white">
                En-tête de la soumission
              </h2>
              <div className="space-y-3">
                <Field label="Titre *">
                  <input
                    value={title}
                    onChange={(e) => setTitle(e.target.value)}
                    className={inputCls}
                  />
                </Field>
                <div className="grid grid-cols-2 gap-3">
                  <Field label="Lead">
                    <select
                      value={leadId}
                      onChange={(e) => setLeadId(e.target.value)}
                      className={inputCls}
                    >
                      <option value="">—</option>
                      {leads.map((l) => (
                        <option key={l.id} value={l.id}>
                          {l.name}
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
                </div>
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
                <Field label="Description / portée">
                  <textarea
                    value={summary}
                    onChange={(e) => setSummary(e.target.value)}
                    rows={3}
                    className={inputCls}
                  />
                </Field>
                <Field label="Notes internes">
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
                    className="rounded-md border border-white/15 px-3 py-1.5 text-xs text-white/60 hover:bg-brand-800"
                  >
                    Annuler
                  </button>
                  <button
                    type="button"
                    onClick={() => void saveHeader()}
                    disabled={saving}
                    className="inline-flex items-center gap-1.5 rounded-md bg-blue-500 px-3 py-1.5 text-xs font-semibold text-white hover:bg-blue-400 disabled:opacity-50"
                  >
                    {saving ? <Loader2 className="h-3 w-3 animate-spin" /> : null}
                    Enregistrer
                  </button>
                </div>
              ) : null}
            </section>

            {/* Lignes */}
            <section className="rounded-2xl border border-brand-800 bg-brand-900 p-5">
              <div className="mb-3 flex items-center justify-between">
                <h2 className="text-sm font-bold text-white">
                  Lignes ({items.length})
                </h2>
                <button
                  type="button"
                  onClick={addItem}
                  className="inline-flex items-center gap-1.5 rounded-md bg-blue-500 px-3 py-1.5 text-xs font-semibold text-white hover:bg-blue-400"
                >
                  <Plus className="h-3 w-3" />
                  Ajouter une ligne
                </button>
              </div>
              {items.length === 0 ? (
                <p className="py-4 text-center text-xs text-white/40">
                  Aucune ligne. Clique sur « Ajouter une ligne ».
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
                                      ? {
                                          ...x,
                                          quantity: Number(e.target.value)
                                        }
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
                              title="Supprimer la ligne"
                              className="rounded p-1 text-white/40 hover:bg-rose-500/15 hover:text-rose-300"
                            >
                              <Trash2 className="h-3 w-3" />
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                    <tfoot>
                      <tr className="border-t border-brand-800">
                        <td colSpan={4} className="px-2 py-3 text-right text-xs text-white/60">
                          Total
                        </td>
                        <td className="px-2 py-3 text-right text-base font-bold text-white">
                          {fmtAmount(total)}
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
