"use client";

import { useEffect, useMemo, useState } from "react";
import {
  useParams,
  useRouter as useNextRouter,
  useSearchParams
} from "next/navigation";
import {
  ArrowLeft,
  CheckCircle2,
  ExternalLink,
  Loader2,
  Save,
  Trash2
} from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { EntityDriveSection } from "@/components/drive/EntityDriveSection";
import { FournisseurModal } from "@/components/fournisseur-modal";
import { ReceiptScanner } from "@/components/receipt-scanner";
import { Link } from "@/i18n/navigation";
import { useAppLayout } from "../../layout";
import { authedFetch } from "@/lib/auth";
import { splitFromTotal, TPS_RATE, TVQ_RATE } from "@/lib/tax";
import { projectLabel } from "@/lib/project";
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
  amount_taxes: number | string | null;
  amount_tps: number | string | null;
  amount_tvq: number | string | null;
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

type Project = { id: number; name: string; address?: string | null };
type Fournisseur = { id: number; name: string };

const STATUS_LABELS: Record<string, string> = {
  received: "À payer",
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

  // « Retour » : si on arrive depuis un autre écran (ex. l'onglet
  // Achats / PO d'un projet), on y retourne via le paramètre `from`.
  // Sinon, on retombe sur la liste globale Achats / dépenses.
  const searchParams = useSearchParams();
  const fromParam = searchParams.get("from");
  const backHref =
    fromParam && fromParam.startsWith("/app/") ? fromParam : "/app/achats";
  const backLabel = fromParam?.startsWith("/app/projets/")
    ? "Retour au projet"
    : "Retour aux achats";

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
  // Total (TTC) éditable : décompose le HT + taxes automatiquement,
  // tout en laissant l'employé ajuster le HT/taxes au besoin.
  const [total, setTotal] = useState("");
  const [amount, setAmount] = useState("");
  const [amountTps, setAmountTps] = useState("");
  const [amountTvq, setAmountTvq] = useState("");

  function onTotalChange(v: string) {
    setTotal(v);
    const n = Number(v);
    if (v.trim() !== "" && !Number.isNaN(n) && n > 0) {
      const { ht, tps, tvq } = splitFromTotal(n);
      setAmount(ht.toFixed(2));
      setAmountTps(tps.toFixed(2));
      setAmountTvq(tvq.toFixed(2));
    }
  }
  function syncTotal(htStr: string, tpsStr: string, tvqStr: string) {
    const sum =
      (Number(htStr) || 0) + (Number(tpsStr) || 0) + (Number(tvqStr) || 0);
    setTotal(sum ? sum.toFixed(2) : "");
  }
  function onAmountChange(v: string) {
    setAmount(v);
    // HT saisi → TPS + TVQ + total calculés (éditables ensuite).
    const n = Number(v);
    if (v.trim() !== "" && !Number.isNaN(n) && n > 0) {
      const tps = Math.round(n * TPS_RATE * 100) / 100;
      const tvq = Math.round(n * TVQ_RATE * 100) / 100;
      setAmountTps(tps.toFixed(2));
      setAmountTvq(tvq.toFixed(2));
      setTotal((n + tps + tvq).toFixed(2));
    } else {
      syncTotal(v, amountTps, amountTvq);
    }
  }
  function onTpsChange(v: string) {
    setAmountTps(v);
    syncTotal(amount, v, amountTvq);
  }
  function onTvqChange(v: string) {
    setAmountTvq(v);
    syncTotal(amount, amountTps, v);
  }
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
        {
          const amt = Number(data.amount) || 0;
          const tax = Number(data.amount_taxes) || 0;
          const sum = amt + tax;
          if (sum > 0 && tax === 0) {
            // Reçu legacy (ou saisi avant la décomposition TTC) : le
            // montant stocké est le total de la facture. On applique la
            // décomposition QC standard pour que le HT et les taxes ne
            // restent pas à zéro. Ajustable ensuite si taxes non standard.
            const { ht, tps, tvq } = splitFromTotal(sum);
            setAmount(ht.toFixed(2));
            setAmountTps(tps.toFixed(2));
            setAmountTvq(tvq.toFixed(2));
            setTotal(sum.toFixed(2));
          } else {
            setAmount(data.amount != null ? String(data.amount) : "");
            // TPS/TVQ : valeurs stockées si présentes, sinon on répartit
            // le montant de taxes stocké selon les taux QC standard
            // (rétro-compat — préserve exactement la somme).
            const tpsFb = Math.round((tax * 5) / 14.975 * 100) / 100;
            const tvqFb = Math.round((tax - tpsFb) * 100) / 100;
            setAmountTps(
              data.amount_tps != null
                ? String(data.amount_tps)
                : tax > 0
                  ? tpsFb.toFixed(2)
                  : ""
            );
            setAmountTvq(
              data.amount_tvq != null
                ? String(data.amount_tvq)
                : tax > 0
                  ? tvqFb.toFixed(2)
                  : ""
            );
            setTotal(sum ? sum.toFixed(2) : "");
          }
        }
        setIsBillable(data.is_billable !== false);
        // Achat refacturable sans majoration enregistrée → on affiche
        // 10 % par défaut (modifiable ; 0 = coûtant). Couvre les achats
        // existants créés avant le défaut backend.
        setMarkupPercent(
          data.markup_percent != null
            ? String(data.markup_percent)
            : data.is_billable !== false
            ? "10"
            : ""
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
      amountTps !== (a.amount_tps != null ? String(a.amount_tps) : "") ||
      amountTvq !== (a.amount_tvq != null ? String(a.amount_tvq) : "") ||
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
    a, projectId, fournisseurId, description, amount, amountTps, amountTvq,
    statusStr, invoiceDate, supplierInvoiceNumber, receivedAt,
    receiptUrl, notes, paymentMethod
  ]);

  async function saveAll() {
    if (!a) return;
    setSaving(true);
    setError(null);
    try {
      const payload: Record<string, unknown> = {
        description: description.trim() || null,
        amount: amount ? Number(amount) : null,
        amount_tps: amountTps ? Number(amountTps) : null,
        amount_tvq: amountTvq ? Number(amountTvq) : null,
        amount_taxes:
          amountTps || amountTvq
            ? Math.round(
                ((Number(amountTps) || 0) + (Number(amountTvq) || 0)) * 100
              ) / 100
            : null,
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

  const [rotating, setRotating] = useState(false);
  async function rotateReceipt(direction: "left" | "right") {
    setRotating(true);
    setError(null);
    try {
      const res = await authedFetch(
        `/api/v1/achats/${id}/receipt/rotate?direction=${direction}`,
        { method: "POST" }
      );
      if (!res.ok) throw new Error(`http_${res.status}`);
      // Réouvre le reçu pivoté dans un nouvel onglet.
      await openReceipt();
    } catch (err) {
      setError(`Rotation échouée : ${(err as Error).message}`);
    } finally {
      setRotating(false);
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
          href={backHref as any}
          className="inline-flex items-center text-sm text-white/70 hover:text-accent-500"
        >
          <ArrowLeft className="mr-1 h-4 w-4" /> {backLabel}
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

            <EntityDriveSection
              entityType="Achat"
              entityId={a.id}
              pole="Construction"
              label="Achat / dépense"
              route="/app/achats/[id]"
            />

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
                          {projectLabel(p)}
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
                  <div>
                    <label htmlFor="atotal" className="label">
                      Montant total (TTC) — total de la facture
                    </label>
                    <input
                      id="atotal"
                      type="number"
                      step="0.01"
                      min="0"
                      value={total}
                      onChange={(e) => onTotalChange(e.target.value)}
                      className="input"
                      placeholder="0.00"
                    />
                    <p className="mt-1 text-xs text-white/40">
                      Le HT et les taxes (TPS 5 % + TVQ 9,975 %) sont calculés
                      automatiquement. Ajustables si la facture a des taxes
                      non standard.
                    </p>
                  </div>
                  <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
                    <div>
                      <label htmlFor="aamount" className="label">
                        Montant HT (avant taxes)
                      </label>
                      <input
                        id="aamount"
                        type="number"
                        step="0.01"
                        min="0"
                        value={amount}
                        onChange={(e) => onAmountChange(e.target.value)}
                        className="input"
                      />
                    </div>
                    <div>
                      <label htmlFor="aamounttps" className="label">
                        TPS (5 %)
                      </label>
                      <input
                        id="aamounttps"
                        type="number"
                        step="0.01"
                        min="0"
                        value={amountTps}
                        onChange={(e) => onTpsChange(e.target.value)}
                        className="input"
                        placeholder="0.00"
                      />
                    </div>
                    <div>
                      <label htmlFor="aamounttvq" className="label">
                        TVQ (9,975 %)
                      </label>
                      <input
                        id="aamounttvq"
                        type="number"
                        step="0.01"
                        min="0"
                        value={amountTvq}
                        onChange={(e) => onTvqChange(e.target.value)}
                        className="input"
                        placeholder="0.00"
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
                  {(amount || amountTps || amountTvq) ? (
                    <p className="-mt-1 text-[11px] text-white/50">
                      Le markup pour refacturation est appliqué sur le
                      HT seulement (les taxes payées au fournisseur ne sont
                      pas majorées).
                    </p>
                  ) : null}

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
                        onChange={(e) => {
                          const on = e.target.checked;
                          setIsBillable(on);
                          // Cocher « refacturable » sans majoration saisie
                          // → 10 % par défaut (modifiable).
                          if (on && markupPercent.trim() === "") {
                            setMarkupPercent("10");
                          }
                        }}
                        disabled={!!a?.invoiced_at}
                      />
                      Refacturable au client
                    </label>
                    <label htmlFor="amarkup" className="label">
                      Majoration (%) — appliquée sur le HT à l&apos;import facture
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
                      onClick={() => rotateReceipt("left")}
                      disabled={rotating}
                      title="Pivoter de 90° vers la gauche"
                      className="inline-flex items-center gap-1 rounded-lg border border-brand-700 bg-brand-900 px-3 py-1.5 text-xs text-white/80 hover:border-accent-500 hover:text-white disabled:opacity-60"
                    >
                      ↺ Pivoter gauche
                    </button>
                    <button
                      type="button"
                      onClick={() => rotateReceipt("right")}
                      disabled={rotating}
                      title="Pivoter de 90° vers la droite"
                      className="inline-flex items-center gap-1 rounded-lg border border-brand-700 bg-brand-900 px-3 py-1.5 text-xs text-white/80 hover:border-accent-500 hover:text-white disabled:opacity-60"
                    >
                      ↻ Pivoter droite
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

              <VersementsCard
                achatId={a.id}
                ttc={(Number(a.amount) || 0) + (Number(a.amount_taxes) || 0)}
                onAchatRefreshed={(fresh) => setA(fresh)}
              />

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
  // Type QB réel : un achat payé (chèque/CC) est une DÉPENSE (Purchase) ;
  // « sur compte / à payer » (bill_to_pay) est une FACTURE FOURNISSEUR (Bill).
  // Le champ qbo_bill_id stocke l'Id dans les deux cas → on déduit le libellé
  // du mode de paiement pour ne pas afficher « Bill » sur une dépense payée.
  const _pm = (achat.payment_method || "").trim();
  const qbLabel =
    _pm && _pm !== "bill_to_pay" ? "QB Dépense" : "QB Facture fourn.";

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
          {qbLabel} ✓ #{achat.qbo_bill_id}
        </div>
        <button
          type="button"
          onClick={push}
          disabled={busy}
          className="text-[11px] text-white/50 underline decoration-dotted hover:text-accent-400 disabled:opacity-40"
        >
          {busy ? "Mise à jour…" : "Re-synchroniser"}
        </button>
        {justSynced ? (
          <p className="text-[11px] text-emerald-300">
            Mis à jour dans QuickBooks ✓
          </p>
        ) : null}
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
          {qbLabel === "QB Dépense" ? "Dépense créée" : "Facture fournisseur créée"}{" "}
          dans QuickBooks.
        </p>
      ) : null}
      {err ? <p className="text-[11px] text-rose-300">{err}</p> : null}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Versements (paiements partiels) — une dépense fournisseur payée en
// plusieurs virements. Chaque versement part vers QB comme un paiement
// distinct (montant + date + compte réels) lié à la facture fournisseur,
// pour que CHAQUE ligne du flux bancaire s'apparie à SON paiement.
// ---------------------------------------------------------------------------

type Versement = {
  id: number;
  achat_id: number;
  amount: number | string;
  paid_at: string | null;
  payment_method: string;
  qbo_bill_payment_id: string | null;
};

const VERSEMENT_METHODS = PAYMENT_OPTIONS.filter(
  (o) => o.value !== "bill_to_pay"
);

function methodLabel(value: string): string {
  return (
    PAYMENT_OPTIONS.find((o) => o.value === value)?.label || value
  );
}

function VersementsCard({
  achatId,
  ttc,
  onAchatRefreshed
}: {
  achatId: number;
  ttc: number;
  onAchatRefreshed: (a: Achat) => void;
}) {
  const confirm = useConfirm();
  const [items, setItems] = useState<Versement[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [amount, setAmount] = useState("");
  const [paidAt, setPaidAt] = useState("");
  const [method, setMethod] = useState("cheque_horizon");

  async function load() {
    try {
      const res = await authedFetch(`/api/v1/achats/${achatId}/versements`);
      if (res.ok) setItems((await res.json()) as Versement[]);
    } catch {
      /* silencieux */
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [achatId]);

  async function refreshAchat() {
    try {
      const res = await authedFetch(`/api/v1/achats/${achatId}`);
      if (res.ok) onAchatRefreshed((await res.json()) as Achat);
    } catch {
      /* silencieux */
    }
  }

  async function add() {
    const n = Number(amount);
    if (!n || n <= 0) {
      setErr("Entre un montant de versement valide.");
      return;
    }
    setBusy(true);
    setErr(null);
    try {
      const res = await authedFetch(`/api/v1/achats/${achatId}/versements`, {
        method: "POST",
        body: JSON.stringify({
          amount: n,
          paid_at: paidAt || null,
          payment_method: method
        })
      });
      if (!res.ok) {
        const d = (await res.json().catch(() => null)) as {
          detail?: string;
        } | null;
        throw new Error(d?.detail || `HTTP ${res.status}`);
      }
      setAmount("");
      setPaidAt("");
      await load();
      await refreshAchat();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Ajout du versement échoué.");
    } finally {
      setBusy(false);
    }
  }

  async function remove(id: number) {
    const ok = await confirm({
      title: "Supprimer ce versement ?",
      description:
        "Son paiement QuickBooks (s'il a été poussé) sera aussi supprimé.",
      confirmLabel: "Supprimer"
    });
    if (!ok) return;
    setErr(null);
    try {
      const res = await authedFetch(`/api/v1/achats/versements/${id}`, {
        method: "DELETE"
      });
      if (!res.ok && res.status !== 204)
        throw new Error(`HTTP ${res.status}`);
      await load();
      await refreshAchat();
    } catch (e) {
      setErr(
        e instanceof Error ? e.message : "Suppression du versement échouée."
      );
    }
  }

  const paye = items.reduce((s, v) => s + (Number(v.amount) || 0), 0);
  const restant = Math.max(0, Math.round((ttc - paye) * 100) / 100);
  const fmt = (n: number) =>
    n.toLocaleString("fr-CA", { style: "currency", currency: "CAD" });

  return (
    <section className="rounded-xl border border-brand-800 bg-brand-900 p-5">
      <h2 className="text-sm font-semibold uppercase tracking-wider text-accent-500">
        Versements (paiement en plusieurs fois)
      </h2>
      <p className="mt-1 text-xs text-white/50">
        Dépense payée en plusieurs virements ? Ajoute chaque versement
        (montant + date + compte réels) : QuickBooks reçoit la facture
        fournisseur et UN paiement par versement — chaque ligne bancaire
        peut alors s&apos;apparier à son paiement.
      </p>

      {items.length > 0 ? (
        <ul className="mt-4 space-y-2">
          {items.map((v) => (
            <li
              key={v.id}
              className="flex flex-wrap items-center gap-2 rounded-lg border border-brand-800 bg-brand-950 px-3 py-2 text-sm"
            >
              <span className="font-semibold text-white">
                {fmt(Number(v.amount) || 0)}
              </span>
              <span className="text-white/60">
                {v.paid_at || "date non précisée"}
              </span>
              <span className="text-white/60">
                · {methodLabel(v.payment_method)}
              </span>
              <span
                className={`rounded px-1.5 py-0.5 text-[10px] font-semibold ${
                  v.qbo_bill_payment_id
                    ? "bg-emerald-500/15 text-emerald-300"
                    : "bg-amber-500/15 text-amber-300"
                }`}
              >
                {v.qbo_bill_payment_id ? "QB ✓" : "QB en attente"}
              </span>
              <button
                type="button"
                onClick={() => void remove(v.id)}
                aria-label="Supprimer ce versement"
                className="ml-auto rounded-md border border-brand-800 p-1 text-white/50 hover:border-rose-500 hover:text-rose-300"
              >
                <Trash2 className="h-3.5 w-3.5" />
              </button>
            </li>
          ))}
        </ul>
      ) : (
        <p className="mt-4 text-xs text-white/40">
          Aucun versement. (Inutile pour une dépense payée en une seule
          fois.)
        </p>
      )}

      {items.length > 0 ? (
        <p className="mt-3 text-xs text-white/60">
          Payé <span className="font-semibold text-white">{fmt(paye)}</span>{" "}
          sur <span className="font-semibold text-white">{fmt(ttc)}</span>
          {restant > 0 ? (
            <>
              {" "}
              — restant{" "}
              <span className="font-semibold text-amber-300">
                {fmt(restant)}
              </span>
            </>
          ) : (
            <span className="ml-1 font-semibold text-emerald-300">
              — payé au complet
            </span>
          )}
        </p>
      ) : null}

      <div className="mt-4 grid gap-2 sm:grid-cols-[1fr_1fr_1.5fr_auto]">
        <input
          type="number"
          step="0.01"
          min="0"
          placeholder={restant > 0 ? `Montant (${restant})` : "Montant"}
          value={amount}
          onChange={(e) => setAmount(e.target.value)}
          className="input"
        />
        <input
          type="date"
          value={paidAt}
          onChange={(e) => setPaidAt(e.target.value)}
          className="input"
        />
        <select
          value={method}
          onChange={(e) => setMethod(e.target.value)}
          className="input"
        >
          {VERSEMENT_METHODS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
        <button
          type="button"
          onClick={() => void add()}
          disabled={busy}
          className="btn-accent text-sm"
        >
          {busy ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            "+ Versement"
          )}
        </button>
      </div>
      {err ? <p className="mt-2 text-[11px] text-rose-300">{err}</p> : null}
    </section>
  );
}
