"use client";

import { useEffect, useMemo, useState } from "react";
import { useParams, useRouter as useNextRouter } from "next/navigation";
import {
  ArrowLeft,
  CheckCircle2,
  ExternalLink,
  Loader2,
  Save,
  Trash2
} from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { FournisseurModal } from "@/components/fournisseur-modal";
import { ReceiptScanner } from "@/components/receipt-scanner";
import { Link } from "@/i18n/navigation";
import { useAppLayout } from "../../layout";
import { authedFetch } from "@/lib/auth";
import { useConfirm } from "@/components/confirm-dialog";

const PAYMENT_OPTIONS = [
  { value: "bill_to_pay", label: "Sur compte fournisseur (à payer plus tard)" },
  { value: "cheque_horizon", label: "Compte chèque Horizon" },
  { value: "cc_steven", label: "CC Horizon Steven Giguère" },
  { value: "cc_michael", label: "CC Horizon Michael Villiard" },
  { value: "cc_olivier", label: "CC Horizon Olivier Therrien" },
  { value: "cc_christian", label: "CC Horizon Christian Villiard" }
];

type Employe = {
  id: number;
  full_name: string;
  email: string | null;
  active?: boolean;
};

type Achat = {
  id: number;
  reference: string | null;
  purchase_order_id: number | null;
  fournisseur_id: number | null;
  project_id: number | null;
  description: string | null;
  amount: number | string | null;
  status: string;
  received_at: string | null;
  paid_at: string | null;
  invoice_date: string | null;
  supplier_invoice_number: string | null;
  receipt_url: string | null;
  has_receipt_image: boolean;
  receipt_image_content_type: string | null;
  notes: string | null;
  created_at: string;
  qbo_bill_id: string | null;
  qbo_doc_number: string | null;
  payment_method: string | null;
  is_billable: boolean;
  markup_percent: number | null;
  invoiced_at: string | null;
  facture_item_id: number | null;
};

type Project = { id: number; name: string };
type Fournisseur = { id: number; name: string };

const STATUS_LABELS: Record<string, string> = {
  received: "Reçu",
  paid: "Payé",
  cancelled: "Annulé"
};

function isoToDateInput(iso: string | null): string {
  if (!iso) return "";
  return iso.slice(0, 10);
}

export default function AchatDetailPage() {
  const confirm = useConfirm();
  const { onOpenSidebar } = useAppLayout();
  const params = useParams<{ id: string }>();
  const id = Number(params.id);
  const router = useNextRouter();

  const [a, setA] = useState<Achat | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  const [fournisseurs, setFournisseurs] = useState<Fournisseur[]>([]);
  const [employes, setEmployes] = useState<Employe[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [projectId, setProjectId] = useState("");
  const [fournisseurId, setFournisseurId] = useState("");
  const [description, setDescription] = useState("");
  const [amount, setAmount] = useState("");
  const [isBillable, setIsBillable] = useState(true);
  const [markupPercent, setMarkupPercent] = useState("");
  const [statusStr, setStatusStr] = useState("received");
  const [invoiceDate, setInvoiceDate] = useState("");
  const [supplierInvoiceNumber, setSupplierInvoiceNumber] = useState("");
  const [receivedAt, setReceivedAt] = useState("");
  const [receiptUrl, setReceiptUrl] = useState("");
  const [notes, setNotes] = useState("");
  const [paymentMethod, setPaymentMethod] = useState("");
  const [showFournisseurModal, setShowFournisseurModal] = useState(false);
  const [uploadBusy, setUploadBusy] = useState(false);
  const [pendingReceipt, setPendingReceipt] = useState<File | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const [aRes, pRes, frRes, eRes] = await Promise.all([
          authedFetch(`/api/v1/achats/${id}`),
          authedFetch("/api/v1/projects?limit=500"),
          authedFetch("/api/v1/fournisseurs?limit=500"),
          authedFetch("/api/v1/employes?limit=500&volet=construction")
        ]);
        if (!aRes.ok) throw new Error(`http_${aRes.status}`);
        const data = (await aRes.json()) as Achat;
        if (cancelled) return;
        setA(data);
        setProjectId(data.project_id ? String(data.project_id) : "");
        setFournisseurId(
          data.fournisseur_id ? String(data.fournisseur_id) : ""
        );
        setDescription(data.description || "");
        setAmount(data.amount != null ? String(data.amount) : "");
        setIsBillable(data.is_billable !== false);
        setMarkupPercent(
          data.markup_percent != null ? String(data.markup_percent) : ""
        );
        setStatusStr(data.status);
        setInvoiceDate(
          data.invoice_date ? data.invoice_date.slice(0, 10) : ""
        );
        setSupplierInvoiceNumber(data.supplier_invoice_number || "");
        setReceivedAt(isoToDateInput(data.received_at));
        setReceiptUrl(data.receipt_url || "");
        setNotes(data.notes || "");
        setPaymentMethod(data.payment_method || "");
        if (pRes.ok) setProjects((await pRes.json()) as Project[]);
        if (frRes.ok) setFournisseurs((await frRes.json()) as Fournisseur[]);
        if (eRes.ok) setEmployes((await eRes.json()) as Employe[]);
      } catch {
        if (!cancelled) setError("Achat introuvable.");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    if (id) load();
    return () => {
      cancelled = true;
    };
  }, [id]);

  const dirty = useMemo(() => {
    if (!a) return false;
    return (
      projectId !== (a.project_id ? String(a.project_id) : "") ||
      fournisseurId !== (a.fournisseur_id ? String(a.fournisseur_id) : "") ||
      description !== (a.description || "") ||
      amount !== (a.amount != null ? String(a.amount) : "") ||
      statusStr !== a.status ||
      invoiceDate !==
        (a.invoice_date ? a.invoice_date.slice(0, 10) : "") ||
      supplierInvoiceNumber !== (a.supplier_invoice_number || "") ||
      receivedAt !== isoToDateInput(a.received_at) ||
      receiptUrl !== (a.receipt_url || "") ||
      notes !== (a.notes || "") ||
      paymentMethod !== (a.payment_method || "")
    );
  }, [
    a, projectId, fournisseurId, description, amount, statusStr,
    invoiceDate, supplierInvoiceNumber, receivedAt, receiptUrl,
    notes, paymentMethod
  ]);

  async function saveAll() {
    if (!a) return;
    setSaving(true);
    setError(null);
    try {
      const payload: Record<string, unknown> = {
        description: description.trim() || null,
        amount: amount ? Number(amount) : null,
        status: statusStr,
        invoice_date: invoiceDate || null,
        supplier_invoice_number: supplierInvoiceNumber.trim() || null,
        received_at: receivedAt ? new Date(receivedAt).toISOString() : null,
        receipt_url: receiptUrl.trim() || null,
        notes: notes.trim() || null,
        fournisseur_id: fournisseurId ? Number(fournisseurId) : null,
        project_id: projectId ? Number(projectId) : null,
        is_billable: isBillable,
        markup_percent: markupPercent.trim() ? Number(markupPercent) : null,
        payment_method: paymentMethod || null
      };
      const res = await authedFetch(`/api/v1/achats/${id}`, {
        method: "PATCH",
        body: JSON.stringify(payload)
      });
      if (!res.ok) throw new Error();
      setA((await res.json()) as Achat);
    } catch {
      setError("Sauvegarde échouée.");
    } finally {
      setSaving(false);
    }
  }

  async function uploadReceipt(file: File) {
    if (!a) return;
    setUploadBusy(true);
    setError(null);
    try {
      const fd = new FormData();
      fd.append("file", file, file.name);
      const res = await authedFetch(`/api/v1/achats/${id}/receipt`, {
        method: "POST",
        body: fd
      });
      if (!res.ok && res.status !== 204) {
        const txt = await res.text();
        throw new Error(txt.slice(0, 240) || `http_${res.status}`);
      }
      // Reload the achat row to refresh has_receipt_image + content_type.
      const re = await authedFetch(`/api/v1/achats/${id}`);
      if (re.ok) setA((await re.json()) as Achat);
    } catch (err) {
      setError(`Upload reçu échoué : ${(err as Error).message}`);
    } finally {
      setUploadBusy(false);
    }
  }

  async function deleteReceipt() {
    if (!a) return;
    if (!(await confirm("Supprimer la photo / le PDF du reçu ?"))) return;
    setUploadBusy(true);
    try {
      const res = await authedFetch(`/api/v1/achats/${id}/receipt`, {
        method: "DELETE"
      });
      if (!res.ok && res.status !== 204) throw new Error();
      const re = await authedFetch(`/api/v1/achats/${id}`);
      if (re.ok) setA((await re.json()) as Achat);
    } catch {
      setError("Suppression du reçu échouée.");
    } finally {
      setUploadBusy(false);
    }
  }

  async function openReceipt() {
    try {
      const res = await authedFetch(`/api/v1/achats/${id}/receipt`);
      if (!res.ok) throw new Error(`http_${res.status}`);
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      window.open(url, "_blank", "noopener,noreferrer");
      setTimeout(() => URL.revokeObjectURL(url), 60_000);
    } catch (err) {
      setError(`Ouverture reçu échouée : ${(err as Error).message}`);
    }
  }

  async function onDelete() {
    if (!a) return;
    if (!(await confirm(`Supprimer l'achat ${a.reference} ?`))) return;
    setDeleting(true);
    try {
      const res = await authedFetch(`/api/v1/achats/${id}`, {
        method: "DELETE"
      });
      if (!res.ok && res.status !== 204) throw new Error();
      router.replace("/app/achats");
    } catch {
      setDeleting(false);
      setError("Suppression échouée.");
    }
  }

  return (
    <>
      <AppTopbar
        breadcrumbs={[{ label: "Construction", href: "/app" }, { label: "Achats / PO" }]}
        onOpenSidebar={onOpenSidebar}
      />

      <div className="p-4 lg:p-6">
        <Link
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          href={"/app/achats" as any}
          className="inline-flex items-center text-sm text-white/70 hover:text-accent-500"
        >
          <ArrowLeft className="mr-1 h-4 w-4" /> Retour aux achats
        </Link>

        {loading ? (
          <div className="flex min-h-[40vh] items-center justify-center">
            <Loader2 className="h-6 w-6 animate-spin text-accent-500" />
          </div>
        ) : error && !a ? (
          <p className="mt-6 rounded-lg border border-rose-500/40 bg-rose-500/10 px-4 py-2 text-sm text-rose-300">
            {error}
          </p>
        ) : a ? (
          <>
            <header className="mt-6 flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
              <h1 className="text-2xl font-bold text-white">{a.reference}</h1>
              <div className="flex flex-wrap items-start gap-2">
                <AchatQboPushButton
                  achat={a}
                  onSynced={(billId, docNumber) =>
                    setA((prev) =>
                      prev
                        ? {
                            ...prev,
                            qbo_bill_id: billId,
                            qbo_doc_number: docNumber
                          }
                        : prev
                    )
                  }
                />
                <button
                  type="button"
                  onClick={onDelete}
                  disabled={deleting}
                  className="inline-flex items-center gap-2 self-start rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2.5 text-sm font-medium text-rose-300 hover:bg-rose-500/20"
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

            <div className="mt-6 max-w-3xl space-y-6">
              <section className="rounded-xl border border-brand-800 bg-brand-900 p-5">
                <h2 className="text-sm font-semibold uppercase tracking-wider text-accent-500">
                  Lien
                </h2>
                <div className="mt-4 grid gap-4 sm:grid-cols-2">
                  <div>
                    <label htmlFor="ap" className="label">Projet</label>
                    <select
                      id="ap"
                      value={projectId}
                      onChange={(e) => setProjectId(e.target.value)}
                      className="input"
                    >
                      <option value="">— Aucun —</option>
                      {projects.map((p) => (
                        <option key={p.id} value={String(p.id)}>
                          {p.name}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div>
                    <label htmlFor="af" className="label">Fournisseur</label>
                    <select
                      id="af"
                      value={fournisseurId}
                      onChange={(e) => {
                        const v = e.target.value;
                        if (v === "__new__") {
                          setShowFournisseurModal(true);
                          return;
                        }
                        setFournisseurId(v);
                      }}
                      className="input"
                    >
                      <option value="">— Aucun —</option>
                      {fournisseurs.map((fr) => (
                        <option key={fr.id} value={String(fr.id)}>
                          {fr.name}
                        </option>
                      ))}
                      <option value="__new__">+ Nouveau fournisseur…</option>
                    </select>
                  </div>
                </div>
                <div className="mt-4 grid gap-4 sm:grid-cols-2">
                  <div>
                    <label htmlFor="sin" className="label">
                      # facture fournisseur
                    </label>
                    <input
                      id="sin"
                      type="text"
                      value={supplierInvoiceNumber}
                      onChange={(e) =>
                        setSupplierInvoiceNumber(e.target.value)
                      }
                      placeholder="Ex. RNS-204582"
                      className="input"
                    />
                  </div>
                  <div>
                    <label htmlFor="apm" className="label">
                      Mode de paiement
                    </label>
                    <select
                      id="apm"
                      value={paymentMethod}
                      onChange={(e) => setPaymentMethod(e.target.value)}
                      className="input"
                    >
                      <option value="">— Non défini —</option>
                      {PAYMENT_OPTIONS.map((opt) => (
                        <option key={opt.value} value={opt.value}>
                          {opt.label}
                        </option>
                      ))}
                    </select>
                    <p className="mt-1 text-[11px] text-white/50">
                      Détermine le routage QuickBooks (Bill vs Purchase).
                    </p>
                  </div>
                </div>
              </section>

              <section className="rounded-xl border border-brand-800 bg-brand-900 p-5">
                <h2 className="text-sm font-semibold uppercase tracking-wider text-accent-500">
                  Détails
                </h2>
                <div className="mt-4 space-y-4">
                  <div>
                    <label htmlFor="ad" className="label">Description</label>
                    <input
                      id="ad"
                      type="text"
                      value={description}
                      onChange={(e) => setDescription(e.target.value)}
                      className="input"
                    />
                  </div>
                  <div className="grid gap-4 sm:grid-cols-3">
                    <div>
                      <label htmlFor="aamount" className="label">
                        Montant (CAD)
                      </label>
                      <input
                        id="aamount"
                        type="number"
                        step="0.01"
                        min="0"
                        value={amount}
                        onChange={(e) => setAmount(e.target.value)}
                        className="input"
                      />
                    </div>
                    <div>
                      <label htmlFor="astatus" className="label">Statut</label>
                      <select
                        id="astatus"
                        value={statusStr}
                        onChange={(e) => setStatusStr(e.target.value)}
                        className="input"
                      >
                        {Object.entries(STATUS_LABELS).map(([k, v]) => (
                          <option key={k} value={k}>{v}</option>
                        ))}
                      </select>
                    </div>
                  </div>

                  {/* Refacturation client */}
                  <div className="rounded-xl border border-brand-800 bg-brand-900/40 p-4">
                    <div className="mb-3 flex items-center justify-between">
                      <p className="text-xs font-semibold uppercase tracking-wider text-white/60">
                        Refacturation au client
                      </p>
                      {a?.invoiced_at ? (
                        <span className="inline-flex items-center gap-1.5 rounded-full border border-emerald-500/40 bg-emerald-500/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-emerald-300">
                          ✓ Refacturé
                          {a.facture_item_id ? ` · ligne #${a.facture_item_id}` : ""}
                        </span>
                      ) : isBillable ? (
                        <span className="inline-flex items-center gap-1.5 rounded-full border border-amber-500/40 bg-amber-500/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-amber-300">
                          À refacturer
                        </span>
                      ) : (
                        <span className="inline-flex items-center gap-1.5 rounded-full border border-white/20 bg-white/5 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-white/40">
                          Non refacturable
                        </span>
                      )}
                    </div>
                    <label className="mb-3 flex items-center gap-2 text-sm text-white/80">
                      <input
                        type="checkbox"
                        checked={isBillable}
                        onChange={(e) => setIsBillable(e.target.checked)}
                        disabled={!!a?.invoiced_at}
                      />
                      Refacturable au client
                    </label>
                    <label htmlFor="amarkup" className="label">
                      Majoration (%) — appliquée à l&apos;import facture
                    </label>
                    <input
                      id="amarkup"
                      type="number"
                      step="0.5"
                      min="0"
                      max="500"
                      value={markupPercent}
                      onChange={(e) => setMarkupPercent(e.target.value)}
                      placeholder="0"
                      disabled={!isBillable || !!a?.invoiced_at}
                      className="input"
                    />
                    {a?.invoiced_at ? (
                      <p className="mt-1 text-xs text-white/40">
                        Cet achat est déjà refacturé. Les champs sont verrouillés.
                      </p>
                    ) : null}
                  </div>

                  <div className="grid gap-4 sm:grid-cols-2">
                    <div>
                      <label htmlFor="aidate" className="label">
                        Date de facture
                      </label>
                      <input
                        id="aidate"
                        type="date"
                        value={invoiceDate}
                        onChange={(e) => setInvoiceDate(e.target.value)}
                        className="input"
                      />
                    </div>
                    <div>
                      <label htmlFor="arec" className="label">Reçu le</label>
                      <input
                        id="arec"
                        type="date"
                        value={receivedAt}
                        onChange={(e) => setReceivedAt(e.target.value)}
                        className="input"
                      />
                    </div>
                  </div>
                </div>
              </section>

              <section className="rounded-xl border border-brand-800 bg-brand-900 p-5">
                <h2 className="text-sm font-semibold uppercase tracking-wider text-accent-500">
                  Facture / reçu
                </h2>
                <p className="mt-1 text-xs text-white/50">
                  Scan avec la caméra de ton cell, ou importe un fichier
                  (JPG, PNG, WEBP, HEIC ou PDF, 15 Mo max).
                </p>

                {a.has_receipt_image ? (
                  <div className="mt-4 flex flex-wrap items-center gap-3">
                    <span className="rounded-md bg-emerald-500/15 px-2 py-1 text-xs font-semibold text-emerald-300">
                      {a.receipt_image_content_type === "application/pdf"
                        ? "PDF attaché"
                        : "Photo attachée"}
                    </span>
                    <button
                      type="button"
                      onClick={openReceipt}
                      className="btn-secondary text-xs"
                    >
                      Ouvrir
                    </button>
                    <button
                      type="button"
                      onClick={deleteReceipt}
                      disabled={uploadBusy}
                      className="inline-flex items-center gap-1 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-1.5 text-xs font-medium text-rose-300 hover:bg-rose-500/20 disabled:opacity-60"
                    >
                      Supprimer
                    </button>
                  </div>
                ) : null}
                <div className="mt-4">
                  <p className="text-xs text-white/50">
                    {a.has_receipt_image
                      ? "Remplacer la pièce jointe :"
                      : "Ajoute une pièce jointe :"}
                  </p>
                  <div className="mt-2">
                    <ReceiptScanner
                      value={pendingReceipt}
                      onChange={setPendingReceipt}
                    />
                  </div>
                  {pendingReceipt ? (
                    <button
                      type="button"
                      disabled={uploadBusy}
                      onClick={async () => {
                        await uploadReceipt(pendingReceipt);
                        setPendingReceipt(null);
                      }}
                      className="btn-accent mt-3 text-sm"
                    >
                      {uploadBusy ? (
                        <>
                          <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                          Envoi…
                        </>
                      ) : (
                        "Envoyer au dossier"
                      )}
                    </button>
                  ) : null}
                </div>
              </section>

              <section className="rounded-xl border border-brand-800 bg-brand-900 p-5">
                <h2 className="text-sm font-semibold uppercase tracking-wider text-accent-500">
                  Notes
                </h2>
                <textarea
                  rows={3}
                  value={notes}
                  onChange={(e) => setNotes(e.target.value)}
                  className="input mt-3"
                />
              </section>

              <button
                type="button"
                onClick={saveAll}
                disabled={saving || !dirty}
                className="btn-accent text-sm"
              >
                {saving ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    Sauvegarde…
                  </>
                ) : (
                  <>
                    <Save className="mr-2 h-4 w-4" />
                    {dirty ? "Sauvegarder" : "Aucun changement"}
                  </>
                )}
              </button>
            </div>
          </>
        ) : null}
      </div>
      <FournisseurModal
        open={showFournisseurModal}
        onClose={() => setShowFournisseurModal(false)}
        onCreated={(f) => {
          setFournisseurs((prev) => [...prev, f]);
          setFournisseurId(String(f.id));
          setShowFournisseurModal(false);
        }}
      />
    </>
  );
}

// ---------------------------------------------------------------------------
// QuickBooks push — pousse l'achat vers QBO comme un Bill (facture
// fournisseur). Affiche un bouton ou un badge selon l'état actuel.
// ---------------------------------------------------------------------------

function AchatQboPushButton({
  achat,
  onSynced
}: {
  achat: Achat;
  onSynced: (billId: string, docNumber: string) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [justSynced, setJustSynced] = useState(false);

  async function push() {
    setBusy(true);
    setErr(null);
    try {
      const res = await authedFetch(
        `/api/v1/achats/${achat.id}/qbo/sync`,
        { method: "POST" }
      );
      if (!res.ok) {
        const text = await res.text();
        throw new Error(text.slice(0, 240) || `http_${res.status}`);
      }
      const data = (await res.json()) as {
        qbo_bill_id: string;
        qbo_doc_number: string;
      };
      onSynced(data.qbo_bill_id, data.qbo_doc_number);
      setJustSynced(true);
      setTimeout(() => setJustSynced(false), 4000);
    } catch (e) {
      setErr(`Push QBO échoué : ${(e as Error).message}`);
    } finally {
      setBusy(false);
    }
  }

  if (achat.qbo_bill_id) {
    return (
      <div className="flex flex-col items-start gap-1">
        <div className="inline-flex items-center gap-2 self-start rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-3 py-2.5 text-sm font-medium text-emerald-300">
          <CheckCircle2 className="h-4 w-4" />
          QB Bill ✓ #{achat.qbo_bill_id}
        </div>
        <button
          type="button"
          onClick={push}
          disabled={busy}
          className="text-[11px] text-white/50 underline decoration-dotted hover:text-accent-400 disabled:opacity-40"
        >
          {busy ? "Mise à jour…" : "Re-synchroniser"}
        </button>
        {err ? <p className="text-[11px] text-rose-300">{err}</p> : null}
      </div>
    );
  }

  return (
    <div className="flex flex-col items-start gap-1">
      <button
        type="button"
        onClick={push}
        disabled={busy}
        className="inline-flex items-center gap-2 self-start rounded-lg border border-accent-500/40 bg-accent-500/10 px-3 py-2.5 text-sm font-medium text-accent-200 hover:bg-accent-500/20 disabled:opacity-50"
      >
        {busy ? (
          <Loader2 className="h-4 w-4 animate-spin" />
        ) : (
          <ExternalLink className="h-4 w-4" />
        )}
        Envoyer vers QuickBooks
      </button>
      {justSynced ? (
        <p className="text-[11px] text-emerald-300">
          Bill créée dans QuickBooks.
        </p>
      ) : null}
      {err ? <p className="text-[11px] text-rose-300">{err}</p> : null}
    </div>
  );
}
