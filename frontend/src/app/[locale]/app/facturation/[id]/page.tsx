"use client";

import { useEffect, useMemo, useState } from "react";
import { useParams, useRouter as useNextRouter } from "next/navigation";
import {
  ArrowLeft,
  FileText,
  Loader2,
  Mail,
  Plus,
  RefreshCw,
  Save,
  Send,
  Trash2
} from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { PaymentsPanel } from "@/components/payments-panel";
import { Link } from "@/i18n/navigation";
import { useAppLayout } from "../../layout";
import { authedFetch } from "@/lib/auth";
import { useConfirm } from "@/components/confirm-dialog";

type Facture = {
  id: number;
  reference: string;
  client_id: number | null;
  project_id: number | null;
  subtotal: number | string | null;
  tps: number | string | null;
  tvq: number | string | null;
  total: number | string | null;
  balance: number | string | null;
  status: string;
  issued_at: string | null;
  due_at: string | null;
  paid_at: string | null;
  qbo_invoice_id: string | null;
  qbo_doc_number: string | null;
  internal_notes: string | null;
  client_note: string | null;
  created_at: string;
};

type Item = {
  id: number;
  facture_id: number;
  position: number;
  description: string;
  unit: string | null;
  quantity: number;
  unit_price: number;
  total: number;
};

type Client = { id: number; name: string; email: string | null };

const STATUS_LABELS: Record<string, string> = {
  draft: "Brouillon",
  sent: "Envoyée",
  paid: "Payée",
  overdue: "En retard",
  void: "Annulée"
};

const STATUS_CLASS: Record<string, string> = {
  draft: "bg-white/10 text-white",
  sent: "bg-blue-500/20 text-blue-300",
  paid: "bg-emerald-500/20 text-emerald-300",
  overdue: "bg-rose-500/20 text-rose-300",
  void: "bg-white/5 text-white/50"
};

const TPS_RATE = 0.05;
const TVQ_RATE = 0.09975;

function fmtMoney(n: number | string | null): string {
  if (n == null || n === "") return "—";
  const num = typeof n === "string" ? Number(n) : n;
  return new Intl.NumberFormat("fr-CA", {
    style: "currency",
    currency: "CAD",
    maximumFractionDigits: 2
  }).format(num);
}

function isoToDateInput(iso: string | null): string {
  if (!iso) return "";
  return iso.slice(0, 10);
}

async function explainError(res: Response): Promise<string> {
  try {
    const data = await res.json();
    if (Array.isArray(data?.detail)) {
      return data.detail
        .map(
          (d: { loc?: (string | number)[]; msg?: string }) =>
            `${(d.loc || []).slice(1).join(".")} — ${d.msg}`
        )
        .join(" · ")
        .slice(0, 400);
    }
    if (typeof data?.detail === "string") return data.detail.slice(0, 400);
    return `http_${res.status}`;
  } catch {
    return `http_${res.status}`;
  }
}

export default function FactureDetailPage() {
  const confirm = useConfirm();
  const { onOpenSidebar } = useAppLayout();
  const params = useParams<{ id: string }>();
  const id = Number(params.id);
  const router = useNextRouter();

  const [f, setF] = useState<Facture | null>(null);
  const [items, setItems] = useState<Item[]>([]);
  const [client, setClient] = useState<Client | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [itemBusy, setItemBusy] = useState<number | "new" | null>(null);

  const [qboBusy, setQboBusy] = useState(false);
  const [qboNotice, setQboNotice] = useState<string | null>(null);

  const [sendOpen, setSendOpen] = useState(false);
  const [sendBusy, setSendBusy] = useState(false);
  const [sendNotice, setSendNotice] = useState<string | null>(null);
  const [sendTo, setSendTo] = useState("");
  const [sendCc, setSendCc] = useState("");
  const [sendSubject, setSendSubject] = useState("");
  const [sendMessage, setSendMessage] = useState("");

  const [dueAt, setDueAt] = useState("");
  const [internalNotes, setInternalNotes] = useState("");
  const [clientNote, setClientNote] = useState("");
  const [notesSaving, setNotesSaving] = useState(false);

  const [importOpen, setImportOpen] = useState(false);
  const [importBusy, setImportBusy] = useState(false);
  const [importIncludeSoumission, setImportIncludeSoumission] = useState(true);
  const [importSoumissionPct, setImportSoumissionPct] = useState("100");
  const [importIncludeHours, setImportIncludeHours] = useState(false);
  const [importOnlyApproved, setImportOnlyApproved] = useState(true);
  const [importIncludeAchats, setImportIncludeAchats] = useState(false);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const [fRes, iRes] = await Promise.all([
          authedFetch(`/api/v1/factures/${id}`),
          authedFetch(`/api/v1/factures/${id}/items`)
        ]);
        if (!fRes.ok) throw new Error(`http_${fRes.status}`);
        const fd = (await fRes.json()) as Facture;
        const iData = iRes.ok ? ((await iRes.json()) as Item[]) : [];
        if (cancelled) return;
        setF(fd);
        setItems(iData);
        setDueAt(isoToDateInput(fd.due_at));
        setInternalNotes(fd.internal_notes || "");
        setClientNote(fd.client_note || "");
        setSendSubject(`Facture ${fd.reference}`);
        if (fd.client_id) {
          const cr = await authedFetch(`/api/v1/clients/${fd.client_id}`);
          if (cr.ok && !cancelled) {
            const cd = (await cr.json()) as Client;
            setClient(cd);
            if (cd.email) setSendTo(cd.email);
          }
        }
      } catch {
        if (!cancelled) setError("Facture introuvable.");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    if (id) load();
    return () => {
      cancelled = true;
    };
  }, [id]);

  const subtotal = useMemo(
    () => +items.reduce((sum, it) => sum + Number(it.total || 0), 0).toFixed(2),
    [items]
  );
  const tps = +(subtotal * TPS_RATE).toFixed(2);
  const tvq = +(subtotal * TVQ_RATE).toFixed(2);
  const total = +(subtotal + tps + tvq).toFixed(2);

  async function updateStatus(newStatus: string) {
    if (!f) return;
    const prev = f;
    setF({ ...f, status: newStatus });
    try {
      const res = await authedFetch(`/api/v1/factures/${id}`, {
        method: "PATCH",
        body: JSON.stringify({
          status: newStatus,
          paid_at:
            newStatus === "paid" && !f.paid_at ? new Date().toISOString() : undefined
        })
      });
      if (!res.ok) throw new Error();
      const u = (await res.json()) as Facture;
      setF(u);
    } catch {
      setF(prev);
      setError("Changement de statut échoué.");
    }
  }

  async function saveDueAt() {
    if (!f) return;
    setSaving(true);
    try {
      const res = await authedFetch(`/api/v1/factures/${id}`, {
        method: "PATCH",
        body: JSON.stringify({
          due_at: dueAt ? new Date(dueAt).toISOString() : null
        })
      });
      if (!res.ok) throw new Error();
      const u = (await res.json()) as Facture;
      setF(u);
    } catch {
      setError("Sauvegarde échéance échouée.");
    } finally {
      setSaving(false);
    }
  }

  async function saveNotes() {
    if (!f) return;
    setNotesSaving(true);
    try {
      const res = await authedFetch(`/api/v1/factures/${id}`, {
        method: "PATCH",
        body: JSON.stringify({
          internal_notes: internalNotes.trim() || null,
          client_note: clientNote.trim() || null
        })
      });
      if (!res.ok) throw new Error();
      const u = (await res.json()) as Facture;
      setF(u);
    } catch {
      setError("Sauvegarde des notes échouée.");
    } finally {
      setNotesSaving(false);
    }
  }

  async function runImport() {
    if (
      !importIncludeSoumission &&
      !importIncludeHours &&
      !importIncludeAchats
    ) {
      setError("Choisis au moins une source à importer.");
      return;
    }
    setImportBusy(true);
    setError(null);
    try {
      const res = await authedFetch(
        `/api/v1/factures/${id}/import-sources`,
        {
          method: "POST",
          body: JSON.stringify({
            include_soumission: importIncludeSoumission,
            soumission_percentage: Math.max(
              1,
              Math.min(100, Number(importSoumissionPct) || 100)
            ),
            include_hours: importIncludeHours,
            only_approved: importOnlyApproved,
            include_achats: importIncludeAchats
          })
        }
      );
      if (!res.ok) {
        throw new Error(await explainError(res));
      }
      // Reload items from backend
      const iRes = await authedFetch(`/api/v1/factures/${id}/items`);
      if (iRes.ok) {
        setItems((await iRes.json()) as Item[]);
      }
      setImportOpen(false);
    } catch (err) {
      setError(`Import échoué : ${(err as Error).message}`);
    } finally {
      setImportBusy(false);
    }
  }

  async function addItem() {
    setItemBusy("new");
    try {
      const res = await authedFetch(`/api/v1/factures/${id}/items`, {
        method: "POST",
        body: JSON.stringify({
          position: items.length,
          description: "Nouvel item",
          unit: "unité",
          quantity: 1,
          unit_price: 0
        })
      });
      if (!res.ok) throw new Error();
      const created = (await res.json()) as Item;
      setItems((xs) => [...xs, created]);
    } catch {
      setError("Ajout d'item échoué.");
    } finally {
      setItemBusy(null);
    }
  }

  async function patchItem(item_id: number, patch: Partial<Item>) {
    setItemBusy(item_id);
    try {
      const res = await authedFetch(
        `/api/v1/factures/${id}/items/${item_id}`,
        {
          method: "PATCH",
          body: JSON.stringify(patch)
        }
      );
      if (!res.ok) throw new Error();
      const updated = (await res.json()) as Item;
      setItems((xs) => xs.map((x) => (x.id === item_id ? updated : x)));
    } catch {
      setError("Mise à jour échouée.");
    } finally {
      setItemBusy(null);
    }
  }

  async function deleteItem(item_id: number) {
    if (!(await confirm("Supprimer cet item ?"))) return;
    setItemBusy(item_id);
    try {
      const res = await authedFetch(
        `/api/v1/factures/${id}/items/${item_id}`,
        { method: "DELETE" }
      );
      if (!res.ok && res.status !== 204) throw new Error();
      setItems((xs) => xs.filter((x) => x.id !== item_id));
    } catch {
      setError("Suppression échouée.");
    } finally {
      setItemBusy(null);
    }
  }

  async function deleteFacture() {
    if (!f) return;
    if (!(await confirm(`Supprimer la facture ${f.reference} ?`))) return;
    setDeleting(true);
    try {
      const res = await authedFetch(`/api/v1/factures/${id}`, {
        method: "DELETE"
      });
      if (!res.ok && res.status !== 204) throw new Error();
      router.replace("/app/facturation");
    } catch {
      setDeleting(false);
      setError("Suppression échouée.");
    }
  }

  async function syncToQbo() {
    setQboBusy(true);
    setQboNotice(null);
    try {
      const res = await authedFetch(`/api/v1/factures/${id}/qbo/sync`, {
        method: "POST"
      });
      if (!res.ok) {
        throw new Error(await explainError(res));
      }
      const r = (await res.json()) as {
        qbo_invoice_id: string;
        qbo_doc_number: string;
      };
      setF((cur) =>
        cur
          ? {
              ...cur,
              qbo_invoice_id: r.qbo_invoice_id || null,
              qbo_doc_number: r.qbo_doc_number || null
            }
          : cur
      );
      setQboNotice(`Synchronisée avec QuickBooks (Invoice ${r.qbo_invoice_id}).`);
    } catch (err) {
      setQboNotice(`Erreur QuickBooks : ${(err as Error).message}`);
    } finally {
      setQboBusy(false);
    }
  }

  async function previewPdf() {
    try {
      const res = await authedFetch(`/api/v1/factures/${id}/pdf`);
      if (!res.ok) throw new Error(`http_${res.status}`);
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      window.open(url, "_blank", "noopener,noreferrer");
      setTimeout(() => URL.revokeObjectURL(url), 60_000);
    } catch (err) {
      setSendNotice(
        `Prévisualisation PDF échouée : ${(err as Error).message.slice(0, 240)}`
      );
    }
  }

  async function sendToClient() {
    if (!f) return;
    const to = sendTo
      .split(",")
      .map((x) => x.trim())
      .filter(Boolean);
    if (to.length === 0) {
      setSendNotice("Adresse courriel du destinataire requise.");
      return;
    }
    const cc = sendCc
      .split(",")
      .map((x) => x.trim())
      .filter(Boolean);
    setSendBusy(true);
    setSendNotice(null);
    try {
      const res = await authedFetch(`/api/v1/factures/${id}/send`, {
        method: "POST",
        body: JSON.stringify({
          to,
          cc: cc.length > 0 ? cc : null,
          subject: sendSubject || null,
          message: sendMessage || null
        })
      });
      if (!res.ok) {
        throw new Error(await explainError(res));
      }
      const updated = (await res.json()) as Facture;
      setF(updated);
      setSendOpen(false);
      setSendNotice(`Facture envoyée à ${to.join(", ")}.`);
    } catch (err) {
      setSendNotice(`Erreur d'envoi : ${(err as Error).message}`);
    } finally {
      setSendBusy(false);
    }
  }

  const isQboSynced = !!f?.qbo_invoice_id;

  return (
    <>
      <AppTopbar
        breadcrumbs={[{ label: "Construction", href: "/app" }, { label: "Facturation" }]}
        onOpenSidebar={onOpenSidebar}
      />

      <div className="p-4 lg:p-6">
        <Link
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          href={"/app/facturation" as any}
          className="inline-flex items-center text-sm text-white/70 hover:text-accent-500"
        >
          <ArrowLeft className="mr-1 h-4 w-4" /> Retour aux factures
        </Link>

        {loading ? (
          <div className="flex min-h-[40vh] items-center justify-center">
            <Loader2 className="h-6 w-6 animate-spin text-accent-500" />
          </div>
        ) : error && !f ? (
          <p className="mt-6 rounded-lg border border-rose-500/40 bg-rose-500/10 px-4 py-2 text-sm text-rose-300">
            {error}
          </p>
        ) : f ? (
          <>
            <header className="mt-6 flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
              <div>
                <h1 className="text-2xl font-bold text-white">{f.reference}</h1>
                <p className="mt-1 text-xs text-white/50">
                  {client ? `Client : ${client.name} · ` : ""}Émise le{" "}
                  {new Date(f.issued_at || f.created_at).toLocaleDateString(
                    "fr-CA",
                    { day: "numeric", month: "long", year: "numeric" }
                  )}
                </p>
              </div>
              <div className="flex flex-wrap items-center gap-3">
                <span
                  className={`rounded-md px-3 py-1.5 text-xs font-semibold ${
                    STATUS_CLASS[f.status] || "bg-white/10 text-white"
                  }`}
                >
                  {STATUS_LABELS[f.status] || f.status}
                </span>
                <select
                  value={f.status}
                  onChange={(e) => updateStatus(e.target.value)}
                  className="input w-40"
                >
                  {Object.entries(STATUS_LABELS).map(([k, v]) => (
                    <option key={k} value={k}>
                      {v}
                    </option>
                  ))}
                </select>
                <button
                  type="button"
                  onClick={deleteFacture}
                  disabled={deleting}
                  className="inline-flex items-center gap-2 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2.5 text-sm font-medium text-rose-300 hover:bg-rose-500/20"
                >
                  {deleting ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <Trash2 className="h-4 w-4" />
                  )}
                  Supprimer
                </button>
              </div>
            </header>

            {error ? (
              <p className="mt-4 rounded-lg border border-rose-500/40 bg-rose-500/10 px-4 py-2 text-sm text-rose-300">
                {error}
              </p>
            ) : null}
            {qboNotice ? (
              <p
                className={`mt-4 rounded-lg border px-4 py-2 text-sm ${
                  qboNotice.startsWith("Synchronisée")
                    ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-200"
                    : "border-amber-500/40 bg-amber-500/10 text-amber-200"
                }`}
              >
                {qboNotice}
              </p>
            ) : null}
            {sendNotice ? (
              <p
                className={`mt-4 rounded-lg border px-4 py-2 text-sm ${
                  sendNotice.startsWith("Facture envoyée")
                    ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-200"
                    : "border-amber-500/40 bg-amber-500/10 text-amber-200"
                }`}
              >
                {sendNotice}
              </p>
            ) : null}

            <div className="mt-6 grid gap-3 sm:grid-cols-3">
              <button
                type="button"
                onClick={previewPdf}
                className="flex items-start gap-3 rounded-xl border border-brand-800 bg-brand-900 p-4 text-left transition hover:border-accent-500"
              >
                <FileText className="mt-0.5 h-5 w-5 flex-shrink-0 text-accent-500" />
                <div>
                  <p className="text-sm font-semibold text-white">
                    Prévisualiser le PDF
                  </p>
                  <p className="mt-0.5 text-xs text-white/60">
                    Ouvre dans un nouvel onglet.
                  </p>
                </div>
              </button>
              <button
                type="button"
                onClick={() => setSendOpen(true)}
                className="flex items-start gap-3 rounded-xl border border-brand-800 bg-brand-900 p-4 text-left transition hover:border-accent-500"
              >
                <Mail className="mt-0.5 h-5 w-5 flex-shrink-0 text-accent-500" />
                <div>
                  <p className="text-sm font-semibold text-white">
                    {f.status !== "draft" ? "Renvoyer au client" : "Envoyer au client"}
                  </p>
                  <p className="mt-0.5 text-xs text-white/60">
                    PDF + courriel via Microsoft Graph.
                  </p>
                </div>
              </button>
              <button
                type="button"
                onClick={syncToQbo}
                disabled={qboBusy}
                className={`flex items-start gap-3 rounded-xl border p-4 text-left transition ${
                  isQboSynced
                    ? "border-emerald-500/40 bg-emerald-500/5 hover:bg-emerald-500/10"
                    : "border-brand-800 bg-brand-900 hover:border-accent-500"
                } disabled:opacity-60`}
              >
                {qboBusy ? (
                  <Loader2 className="mt-0.5 h-5 w-5 flex-shrink-0 animate-spin text-accent-500" />
                ) : (
                  <RefreshCw
                    className={`mt-0.5 h-5 w-5 flex-shrink-0 ${
                      isQboSynced ? "text-emerald-400" : "text-accent-500"
                    }`}
                  />
                )}
                <div>
                  <p className="text-sm font-semibold text-white">
                    {isQboSynced ? "Resync QuickBooks" : "Envoyer vers QuickBooks"}
                  </p>
                  <p className="mt-0.5 text-xs text-white/60">
                    {isQboSynced
                      ? `Invoice #${f.qbo_doc_number || f.qbo_invoice_id}`
                      : "Créer l'Invoice dans QBO"}
                  </p>
                </div>
              </button>
            </div>

            <section className="mt-6 rounded-xl border border-brand-800 bg-brand-900 p-5">
              <div className="flex flex-wrap items-center gap-3">
                <label className="label mb-0">Échéance</label>
                <select
                  value={(() => {
                    if (!dueAt) return "custom";
                    const issued = f?.issued_at
                      ? new Date(f.issued_at)
                      : new Date();
                    const due = new Date(dueAt);
                    const diffDays = Math.round(
                      (due.getTime() -
                        new Date(
                          issued.getFullYear(),
                          issued.getMonth(),
                          issued.getDate()
                        ).getTime()) /
                        86400000
                    );
                    if (diffDays === 0) return "0";
                    if ([10, 15, 30, 45, 60].includes(diffDays))
                      return String(diffDays);
                    return "custom";
                  })()}
                  onChange={(e) => {
                    const v = e.target.value;
                    if (v === "custom") return; // user éditera la date à droite
                    const issued = f?.issued_at
                      ? new Date(f.issued_at)
                      : new Date();
                    const base = new Date(
                      issued.getFullYear(),
                      issued.getMonth(),
                      issued.getDate()
                    );
                    base.setDate(base.getDate() + Number(v));
                    const yyyy = base.getFullYear();
                    const mm = String(base.getMonth() + 1).padStart(2, "0");
                    const dd = String(base.getDate()).padStart(2, "0");
                    setDueAt(`${yyyy}-${mm}-${dd}`);
                  }}
                  className="input w-48"
                >
                  <option value="0">Payable sur réception</option>
                  <option value="10">Net 10 jours</option>
                  <option value="15">Net 15 jours</option>
                  <option value="30">Net 30 jours</option>
                  <option value="45">Net 45 jours</option>
                  <option value="60">Net 60 jours</option>
                  <option value="custom">Date personnalisée</option>
                </select>
                <input
                  type="date"
                  value={dueAt}
                  onChange={(e) => setDueAt(e.target.value)}
                  className="input w-44"
                  title="Date d'échéance — modifie pour personnaliser"
                />
                <button
                  type="button"
                  onClick={saveDueAt}
                  disabled={saving}
                  className="btn-secondary text-xs"
                >
                  {saving ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <Save className="h-3.5 w-3.5" />
                  )}
                </button>
              </div>
              <p className="mt-2 text-[11px] text-white/50">
                Une facture d&apos;acompte se règle généralement{" "}
                <strong>sur réception</strong>. Les soldes finaux suivent
                tes conditions habituelles (souvent net 30).
              </p>
            </section>

            <section className="mt-6 rounded-xl border border-brand-800 bg-brand-900 p-5">
              <h2 className="text-sm font-semibold uppercase tracking-wider text-accent-500">
                Notes
              </h2>
              <div className="mt-4 space-y-4">
                <div>
                  <label htmlFor="client_note" className="label">
                    Note sur la facture{" "}
                    <span className="text-[10px] font-normal text-accent-500">
                      (visible par le client)
                    </span>
                  </label>
                  <textarea
                    id="client_note"
                    rows={3}
                    value={clientNote}
                    onChange={(e) => setClientNote(e.target.value)}
                    placeholder="Ex. Merci pour votre confiance. Paiement net 30j. Intérêts 2 % / mois après échéance."
                    className="input"
                  />
                  <p className="mt-1 text-xs text-white/50">
                    Apparaît sur le PDF envoyé au client.
                  </p>
                </div>
                <div>
                  <label htmlFor="internal_notes" className="label">
                    Notes internes{" "}
                    <span className="text-[10px] font-normal text-rose-300">
                      (non visibles par le client)
                    </span>
                  </label>
                  <textarea
                    id="internal_notes"
                    rows={3}
                    value={internalNotes}
                    onChange={(e) => setInternalNotes(e.target.value)}
                    placeholder="Ex. Client a demandé reporter l'échéance. Paiement promis le 15 mai par Interac."
                    className="input"
                  />
                </div>
                <div>
                  <button
                    type="button"
                    onClick={saveNotes}
                    disabled={
                      notesSaving ||
                      ((f.internal_notes || "") === internalNotes &&
                        (f.client_note || "") === clientNote)
                    }
                    className="btn-accent text-sm disabled:opacity-50"
                  >
                    {notesSaving ? (
                      <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    ) : (
                      <Save className="mr-2 h-4 w-4" />
                    )}
                    Sauvegarder les notes
                  </button>
                </div>
              </div>
            </section>

            <section className="mt-6 rounded-xl border border-brand-800 bg-brand-900">
              <div className="flex flex-wrap items-center justify-between gap-2 border-b border-brand-800 px-5 py-4">
                <h2 className="text-sm font-semibold uppercase tracking-wider text-accent-500">
                  Items de la facture
                </h2>
                <div className="flex gap-2">
                  {f.project_id ? (
                    <button
                      type="button"
                      onClick={() => setImportOpen(true)}
                      className="btn-secondary text-xs"
                    >
                      Importer du projet
                    </button>
                  ) : null}
                  <button
                    type="button"
                    onClick={addItem}
                    disabled={itemBusy === "new"}
                    className="btn-accent text-xs"
                  >
                    {itemBusy === "new" ? (
                      <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                    ) : (
                      <Plus className="mr-1.5 h-3.5 w-3.5" />
                    )}
                    Ajouter un item
                  </button>
                </div>
              </div>

              {items.length === 0 ? (
                <p className="px-5 py-10 text-center text-sm text-white/50">
                  Aucun item.
                </p>
              ) : (
                <div className="divide-y divide-brand-800">
                  {items.map((it) => (
                    <ItemRow
                      key={it.id}
                      item={it}
                      busy={itemBusy === it.id}
                      onPatch={(patch) => patchItem(it.id, patch)}
                      onDelete={() => deleteItem(it.id)}
                    />
                  ))}
                </div>
              )}

              <div className="border-t border-brand-800 px-5 py-4">
                <div className="ml-auto w-full max-w-xs space-y-1 text-right text-sm text-white/70">
                  <div className="flex justify-between">
                    <span>Sous-total</span>
                    <span>{fmtMoney(subtotal)}</span>
                  </div>
                  <div className="flex justify-between">
                    <span>TPS (5 %)</span>
                    <span>{fmtMoney(tps)}</span>
                  </div>
                  <div className="flex justify-between">
                    <span>TVQ (9,975 %)</span>
                    <span>{fmtMoney(tvq)}</span>
                  </div>
                  <div className="flex justify-between border-t border-brand-800 pt-1 text-base font-bold text-white">
                    <span>TOTAL CAD</span>
                    <span>{fmtMoney(total)}</span>
                  </div>
                </div>
              </div>
            </section>

            <div className="mt-6">
              <PaymentsPanel
                factureId={Number(f.id)}
                factureTotal={total}
                onStatusMayHaveChanged={async () => {
                  try {
                    const res = await authedFetch(`/api/v1/factures/${f.id}`);
                    if (res.ok) setF((await res.json()) as typeof f);
                  } catch {
                    /* ignore */
                  }
                }}
              />
            </div>
          </>
        ) : null}
      </div>

      {importOpen && f ? (
        <div
          className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/70 p-4"
          onClick={() => (!importBusy ? setImportOpen(false) : null)}
        >
          <div
            className="mt-10 w-full max-w-lg rounded-2xl border border-brand-800 bg-brand-950 p-6 shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          >
            <h3 className="text-lg font-bold text-white">
              Importer des items
            </h3>
            <p className="mt-1 text-xs text-white/60">
              Les lignes sélectionnées sont ajoutées à la facture
              existante sans remplacer ce qui s&apos;y trouve déjà. Tu
              peux ensuite modifier ou supprimer chaque ligne à la main.
            </p>

            <div className="mt-5 space-y-3">
              <label className="flex items-start gap-3 rounded-lg border border-brand-800 bg-brand-900 p-3 text-sm text-white/80">
                <input
                  type="checkbox"
                  checked={importIncludeSoumission}
                  onChange={(e) =>
                    setImportIncludeSoumission(e.target.checked)
                  }
                  className="mt-0.5"
                />
                <div className="flex-1">
                  <div className="font-semibold text-white">
                    Items du devis{" "}
                    <span className="text-xs font-normal text-white/50">
                      (soumission du projet)
                    </span>
                  </div>
                  {importIncludeSoumission ? (
                    <div className="mt-3 flex flex-wrap items-center gap-2">
                      <label className="text-xs text-white/70">
                        % à facturer
                      </label>
                      <input
                        type="number"
                        min="1"
                        max="100"
                        value={importSoumissionPct}
                        onChange={(e) =>
                          setImportSoumissionPct(e.target.value)
                        }
                        className="input w-20 text-sm"
                      />
                      <div className="flex gap-1">
                        {[25, 30, 50, 75, 100].map((v) => (
                          <button
                            key={v}
                            type="button"
                            onClick={() =>
                              setImportSoumissionPct(String(v))
                            }
                            className={`rounded-md px-2 py-0.5 text-[10px] font-semibold ${
                              String(v) === importSoumissionPct
                                ? "bg-accent-500 text-brand-950"
                                : "bg-white/5 text-white/70 hover:bg-white/10"
                            }`}
                          >
                            {v}%
                          </button>
                        ))}
                      </div>
                    </div>
                  ) : null}
                </div>
              </label>

              <label className="flex items-start gap-3 rounded-lg border border-brand-800 bg-brand-900 p-3 text-sm text-white/80">
                <input
                  type="checkbox"
                  checked={importIncludeHours}
                  onChange={(e) => setImportIncludeHours(e.target.checked)}
                  className="mt-0.5"
                />
                <div className="flex-1">
                  <div className="font-semibold text-white">
                    Heures punchées{" "}
                    <span className="text-xs font-normal text-white/50">
                      (T&amp;M)
                    </span>
                  </div>
                  {importIncludeHours ? (
                    <label className="mt-2 flex items-center gap-2 text-xs text-white/70">
                      <input
                        type="checkbox"
                        checked={importOnlyApproved}
                        onChange={(e) =>
                          setImportOnlyApproved(e.target.checked)
                        }
                      />
                      Seulement les punches approuvés
                    </label>
                  ) : null}
                </div>
              </label>

              <label className="flex items-start gap-3 rounded-lg border border-brand-800 bg-brand-900 p-3 text-sm text-white/80">
                <input
                  type="checkbox"
                  checked={importIncludeAchats}
                  onChange={(e) =>
                    setImportIncludeAchats(e.target.checked)
                  }
                  className="mt-0.5"
                />
                <div>
                  <div className="font-semibold text-white">
                    Achats du projet{" "}
                    <span className="text-xs font-normal text-white/50">
                      (matériel)
                    </span>
                  </div>
                </div>
              </label>
            </div>

            <div className="mt-6 flex items-center justify-end gap-3">
              <button
                type="button"
                onClick={() => setImportOpen(false)}
                disabled={importBusy}
                className="btn-secondary text-sm"
              >
                Annuler
              </button>
              <button
                type="button"
                onClick={runImport}
                disabled={
                  importBusy ||
                  (!importIncludeSoumission &&
                    !importIncludeHours &&
                    !importIncludeAchats)
                }
                className="btn-accent text-sm disabled:opacity-60"
              >
                {importBusy ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    Import…
                  </>
                ) : (
                  "Importer"
                )}
              </button>
            </div>
          </div>
        </div>
      ) : null}

      {sendOpen && f ? (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4"
          onClick={() => (!sendBusy ? setSendOpen(false) : null)}
        >
          <div
            className="w-full max-w-xl rounded-2xl border border-brand-800 bg-brand-950 p-6 shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          >
            <h3 className="text-lg font-bold text-white">Envoyer la facture</h3>
            <p className="mt-1 text-xs text-white/60">
              Référence {f.reference}. Le PDF est attaché automatiquement.
            </p>

            <div className="mt-5 space-y-4">
              <div>
                <label htmlFor="s_to" className="label">
                  Destinataire(s) <span className="text-rose-400">*</span>
                </label>
                <input
                  id="s_to"
                  value={sendTo}
                  onChange={(e) => setSendTo(e.target.value)}
                  className="input"
                  placeholder="client@exemple.com"
                />
              </div>
              <div>
                <label htmlFor="s_cc" className="label">CC</label>
                <input
                  id="s_cc"
                  value={sendCc}
                  onChange={(e) => setSendCc(e.target.value)}
                  className="input"
                />
              </div>
              <div>
                <label htmlFor="s_subj" className="label">Objet</label>
                <input
                  id="s_subj"
                  value={sendSubject}
                  onChange={(e) => setSendSubject(e.target.value)}
                  className="input"
                />
              </div>
              <div>
                <label htmlFor="s_msg" className="label">Message</label>
                <textarea
                  id="s_msg"
                  rows={4}
                  value={sendMessage}
                  onChange={(e) => setSendMessage(e.target.value)}
                  className="input"
                />
              </div>
            </div>

            <div className="mt-6 flex items-center justify-end gap-3">
              <button
                type="button"
                onClick={() => setSendOpen(false)}
                disabled={sendBusy}
                className="btn-secondary text-sm"
              >
                Annuler
              </button>
              <button
                type="button"
                onClick={sendToClient}
                disabled={sendBusy || !sendTo.trim()}
                className="btn-accent text-sm disabled:opacity-60"
              >
                {sendBusy ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" /> Envoi…
                  </>
                ) : (
                  <>
                    <Send className="mr-2 h-4 w-4" /> Envoyer
                  </>
                )}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </>
  );
}

function ItemRow({
  item,
  busy,
  onPatch,
  onDelete
}: {
  item: Item;
  busy: boolean;
  onPatch: (patch: Partial<Item>) => void;
  onDelete: () => void;
}) {
  const [description, setDescription] = useState(item.description);
  const [unit, setUnit] = useState(item.unit || "");
  const [quantity, setQuantity] = useState(String(item.quantity));
  const [unitPrice, setUnitPrice] = useState(String(item.unit_price));

  useEffect(() => {
    setDescription(item.description);
    setUnit(item.unit || "");
    setQuantity(String(item.quantity));
    setUnitPrice(String(item.unit_price));
  }, [item.id, item.description, item.unit, item.quantity, item.unit_price]);

  const computedTotal = useMemo(
    () => +(Number(quantity || 0) * Number(unitPrice || 0)).toFixed(2),
    [quantity, unitPrice]
  );

  function persist(field: keyof Item, value: unknown) {
    onPatch({ [field]: value } as Partial<Item>);
  }

  // Étiquettes mobile pour distinguer Description / Unité / Quantité /
  // Prix unitaire / Total quand le grid se déstacke verticalement
  // (mêmes étiquettes que sur la page bons de travail).
  return (
    <div className="grid gap-2 px-5 py-3 text-sm sm:grid-cols-[1fr_80px_80px_120px_120px_32px] sm:items-center">
      <div>
        <label className="mb-1 block text-[10px] font-semibold uppercase tracking-wider text-white/40 sm:hidden">
          Description
        </label>
        <input
          type="text"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          onBlur={() => {
            if (description !== item.description) persist("description", description);
          }}
          disabled={busy}
          className="input text-sm w-full"
        />
      </div>
      <div>
        <label className="mb-1 block text-[10px] font-semibold uppercase tracking-wider text-white/40 sm:hidden">
          Unité
        </label>
        <input
          type="text"
          value={unit}
          onChange={(e) => setUnit(e.target.value)}
          onBlur={() => {
            if (unit !== (item.unit || ""))
              persist("unit", unit || null);
          }}
          disabled={busy}
          placeholder="unité"
          className="input text-sm w-full"
        />
      </div>
      <div>
        <label className="mb-1 block text-[10px] font-semibold uppercase tracking-wider text-white/40 sm:hidden">
          Quantité
        </label>
        <input
          type="number"
          step="0.01"
          min="0"
          value={quantity}
          onChange={(e) => setQuantity(e.target.value)}
          onBlur={() => {
            if (Number(quantity) !== item.quantity)
              persist("quantity", Number(quantity));
          }}
          disabled={busy}
          className="input text-sm w-full"
        />
      </div>
      <div>
        <label className="mb-1 block text-[10px] font-semibold uppercase tracking-wider text-white/40 sm:hidden">
          Prix unitaire ($)
        </label>
        <input
          type="number"
          step="0.01"
          min="0"
          value={unitPrice}
          onChange={(e) => setUnitPrice(e.target.value)}
          onBlur={() => {
            if (Number(unitPrice) !== item.unit_price)
              persist("unit_price", Number(unitPrice));
          }}
          disabled={busy}
          className="input text-sm w-full"
        />
      </div>
      <div className="flex items-center justify-between sm:block sm:text-right">
        <span className="text-[10px] font-semibold uppercase tracking-wider text-white/40 sm:hidden">
          Total
        </span>
        <span className="font-semibold text-white">
          {fmtMoney(computedTotal)}
        </span>
      </div>
      <button
        type="button"
        onClick={onDelete}
        disabled={busy}
        className="flex items-center gap-1 text-rose-400 hover:text-rose-300 disabled:opacity-40 sm:justify-center"
        aria-label="Supprimer l'item"
      >
        {busy ? (
          <Loader2 className="h-4 w-4 animate-spin" />
        ) : (
          <Trash2 className="h-4 w-4" />
        )}
        <span className="text-xs sm:hidden">Supprimer</span>
      </button>
    </div>
  );
}
