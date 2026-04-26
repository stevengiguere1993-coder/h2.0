"use client";

import { useEffect, useMemo, useState } from "react";
import { useParams, useRouter as useNextRouter } from "next/navigation";
import {
  ArrowLeft,
  ArrowRightCircle,
  CheckCircle2,
  ExternalLink,
  Loader2,
  Save,
  Trash2,
  X
} from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { FournisseurModal } from "@/components/fournisseur-modal";
import { Link } from "@/i18n/navigation";
import { useAppLayout } from "../../layout";
import { authedFetch } from "@/lib/auth";
import { useConfirm } from "@/components/confirm-dialog";

type PurchaseOrder = {
  id: number;
  reference: string;
  fournisseur_id: number | null;
  project_id: number | null;
  assigned_employe_id: number | null;
  description: string | null;
  amount_max: number | string | null;
  payment_method: string | null;
  status: string;
  sent_at: string | null;
  notes: string | null;
  created_at: string;
};

type Project = { id: number; name: string };
type Fournisseur = { id: number; name: string };
type Employe = {
  id: number;
  full_name: string;
  email: string | null;
  active?: boolean;
};

const PAYMENT_OPTIONS = [
  { value: "bill_to_pay", label: "Sur compte fournisseur (à payer plus tard)" },
  { value: "cheque_horizon", label: "Compte chèque Horizon" },
  { value: "cc_steven", label: "CC Horizon Steven Giguère" },
  { value: "cc_michael", label: "CC Horizon Michael Villiard" },
  { value: "cc_olivier", label: "CC Horizon Olivier Therrien" },
  { value: "cc_christian", label: "CC Horizon Christian Villiard" }
];

const STATUS_LABELS: Record<string, string> = {
  draft: "Planifié",
  sent: "PO envoyé",
  fulfilled: "Achat créé",
  cancelled: "Annulé"
};

const STATUS_BG: Record<string, string> = {
  draft: "bg-white/10 text-white/70 border-white/20",
  sent: "bg-blue-500/15 text-blue-300 border-blue-500/30",
  fulfilled: "bg-emerald-500/15 text-emerald-300 border-emerald-500/30",
  cancelled: "bg-rose-500/15 text-rose-300 border-rose-500/30"
};

export default function PurchaseOrderDetailPage() {
  const confirm = useConfirm();
  const { onOpenSidebar } = useAppLayout();
  const params = useParams<{ id: string }>();
  const id = Number(params.id);
  const router = useNextRouter();

  const [po, setPo] = useState<PurchaseOrder | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  const [fournisseurs, setFournisseurs] = useState<Fournisseur[]>([]);
  const [employes, setEmployes] = useState<Employe[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [sendingPo, setSendingPo] = useState(false);
  const [poNotice, setPoNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [projectId, setProjectId] = useState("");
  const [fournisseurId, setFournisseurId] = useState("");
  const [assignedEmpId, setAssignedEmpId] = useState("");
  const [paymentMethod, setPaymentMethod] = useState("");
  const [description, setDescription] = useState("");
  const [amountMax, setAmountMax] = useState("");
  const [notes, setNotes] = useState("");
  const [statusStr, setStatusStr] = useState("draft");
  const [showFournisseurModal, setShowFournisseurModal] = useState(false);
  const [showConvertModal, setShowConvertModal] = useState(false);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const [poRes, pRes, frRes, eRes] = await Promise.all([
          authedFetch(`/api/v1/purchase-orders/${id}`),
          authedFetch("/api/v1/projects?limit=500"),
          authedFetch("/api/v1/fournisseurs?limit=500"),
          authedFetch("/api/v1/employes?limit=500")
        ]);
        if (!poRes.ok) throw new Error();
        const data = (await poRes.json()) as PurchaseOrder;
        if (cancelled) return;
        setPo(data);
        setProjectId(data.project_id ? String(data.project_id) : "");
        setFournisseurId(
          data.fournisseur_id ? String(data.fournisseur_id) : ""
        );
        setAssignedEmpId(
          data.assigned_employe_id ? String(data.assigned_employe_id) : ""
        );
        setPaymentMethod(data.payment_method || "");
        setDescription(data.description || "");
        setAmountMax(data.amount_max != null ? String(data.amount_max) : "");
        setNotes(data.notes || "");
        setStatusStr(data.status);
        if (pRes.ok) setProjects((await pRes.json()) as Project[]);
        if (frRes.ok)
          setFournisseurs((await frRes.json()) as Fournisseur[]);
        if (eRes.ok) setEmployes((await eRes.json()) as Employe[]);
      } catch {
        if (!cancelled) setError("PO introuvable.");
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
    if (!po) return false;
    return (
      projectId !== (po.project_id ? String(po.project_id) : "") ||
      fournisseurId !==
        (po.fournisseur_id ? String(po.fournisseur_id) : "") ||
      assignedEmpId !==
        (po.assigned_employe_id ? String(po.assigned_employe_id) : "") ||
      paymentMethod !== (po.payment_method || "") ||
      description !== (po.description || "") ||
      amountMax !== (po.amount_max != null ? String(po.amount_max) : "") ||
      notes !== (po.notes || "") ||
      statusStr !== po.status
    );
  }, [
    po,
    projectId,
    fournisseurId,
    assignedEmpId,
    paymentMethod,
    description,
    amountMax,
    notes,
    statusStr
  ]);

  async function saveAll() {
    if (!po) return;
    setSaving(true);
    setError(null);
    try {
      const payload: Record<string, unknown> = {
        project_id: projectId ? Number(projectId) : null,
        fournisseur_id: fournisseurId ? Number(fournisseurId) : null,
        assigned_employe_id: assignedEmpId ? Number(assignedEmpId) : null,
        payment_method: paymentMethod || null,
        description: description.trim() || null,
        amount_max: amountMax ? Number(amountMax) : null,
        notes: notes.trim() || null,
        status: statusStr
      };
      const res = await authedFetch(`/api/v1/purchase-orders/${id}`, {
        method: "PATCH",
        body: JSON.stringify(payload)
      });
      if (!res.ok) throw new Error();
      setPo((await res.json()) as PurchaseOrder);
    } catch {
      setError("Sauvegarde échouée.");
    } finally {
      setSaving(false);
    }
  }

  async function sendPo() {
    if (!po) return;
    setSendingPo(true);
    setPoNotice(null);
    try {
      const res = await authedFetch(
        `/api/v1/purchase-orders/${id}/send-po`,
        { method: "POST", body: JSON.stringify({}) }
      );
      if (!res.ok) {
        const t = await res.text();
        throw new Error(t.slice(0, 200));
      }
      const u = (await res.json()) as PurchaseOrder;
      setPo(u);
      setStatusStr(u.status);
      setPoNotice("PO envoyé par courriel à l'employé assigné.");
      setTimeout(() => setPoNotice(null), 4000);
    } catch (e) {
      setPoNotice(`Échec : ${(e as Error).message}`);
    } finally {
      setSendingPo(false);
    }
  }

  async function onDelete() {
    if (!po) return;
    if (!(await confirm(`Supprimer le PO ${po.reference} ?`))) return;
    setDeleting(true);
    try {
      const res = await authedFetch(`/api/v1/purchase-orders/${id}`, {
        method: "DELETE"
      });
      if (res.status !== 204 && !res.ok) throw new Error();
      router.replace("/app/po");
    } catch {
      setError("Suppression échouée.");
      setDeleting(false);
    }
  }

  return (
    <>
      <AppTopbar
        breadcrumbs={[
          { label: "Construction", href: "/app" },
          { label: "Bons de commande", href: "/app/po" },
          { label: po?.reference || "Détail" }
        ]}
        onOpenSidebar={onOpenSidebar}
      />

      <div className="p-4 lg:p-6">
        <Link
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          href={"/app/po" as any}
          className="inline-flex items-center text-sm text-white/70 hover:text-accent-500"
        >
          <ArrowLeft className="mr-1 h-4 w-4" /> Retour aux PO
        </Link>

        {loading ? (
          <div className="flex min-h-[40vh] items-center justify-center">
            <Loader2 className="h-6 w-6 animate-spin text-accent-500" />
          </div>
        ) : error && !po ? (
          <p className="mt-6 rounded-lg border border-rose-500/40 bg-rose-500/10 px-4 py-2 text-sm text-rose-300">
            {error}
          </p>
        ) : po ? (
          <>
            <header className="mt-6 flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
              <div>
                <div className="flex items-center gap-3">
                  <h1 className="text-2xl font-bold text-white">
                    {po.reference}
                  </h1>
                  <span
                    className={`rounded-full border px-2 py-0.5 text-[10px] font-semibold ${
                      STATUS_BG[po.status] ||
                      "border-white/20 bg-white/10 text-white/70"
                    }`}
                  >
                    {STATUS_LABELS[po.status] || po.status}
                  </span>
                </div>
                {po.sent_at ? (
                  <p className="mt-1 text-xs text-white/50">
                    Envoyé le{" "}
                    {new Date(po.sent_at).toLocaleString("fr-CA", {
                      day: "numeric",
                      month: "long",
                      hour: "2-digit",
                      minute: "2-digit"
                    })}
                  </p>
                ) : null}
              </div>
              <div className="flex flex-wrap items-start gap-2">
                {po.assigned_employe_id ? (
                  <button
                    type="button"
                    onClick={sendPo}
                    disabled={
                      sendingPo || !fournisseurId || dirty
                    }
                    title={
                      dirty
                        ? "Sauvegarde d'abord les modifications"
                        : !fournisseurId
                          ? "Fournisseur requis avant l'envoi"
                          : "Envoyer le PO par courriel à l'employé"
                    }
                    className="inline-flex items-center gap-2 rounded-lg border border-blue-500/40 bg-blue-500/10 px-3 py-2.5 text-sm font-medium text-blue-200 hover:bg-blue-500/20 disabled:opacity-50"
                  >
                    {sendingPo ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : (
                      <ExternalLink className="h-4 w-4" />
                    )}
                    Envoyer le PO
                  </button>
                ) : null}
                {po.status !== "fulfilled" &&
                po.status !== "cancelled" ? (
                  <button
                    type="button"
                    onClick={() => setShowConvertModal(true)}
                    disabled={dirty || !fournisseurId}
                    title={
                      dirty
                        ? "Sauvegarde d'abord les modifications"
                        : !fournisseurId
                          ? "Fournisseur requis"
                          : "Convertir ce PO en achat (transaction comptable)"
                    }
                    className="inline-flex items-center gap-2 rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-3 py-2.5 text-sm font-medium text-emerald-200 hover:bg-emerald-500/20 disabled:opacity-50"
                  >
                    <ArrowRightCircle className="h-4 w-4" />
                    Convertir en achat
                  </button>
                ) : null}
                <button
                  type="button"
                  onClick={onDelete}
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

            {poNotice ? (
              <p
                className={`mt-3 rounded-lg border px-3 py-2 text-xs ${
                  poNotice.startsWith("Échec")
                    ? "border-rose-500/40 bg-rose-500/10 text-rose-300"
                    : "border-emerald-500/40 bg-emerald-500/10 text-emerald-300"
                }`}
              >
                {poNotice}
              </p>
            ) : null}

            {error ? (
              <p className="mt-4 rounded-lg border border-rose-500/40 bg-rose-500/10 px-4 py-2 text-sm text-rose-300">
                {error}
              </p>
            ) : null}

            <section className="mt-6 max-w-3xl space-y-5 rounded-xl border border-brand-800 bg-brand-900 p-5">
              <div className="grid gap-4 sm:grid-cols-2">
                <div>
                  <label htmlFor="ap" className="label">Projet</label>
                  <select
                    id="ap"
                    value={projectId}
                    onChange={(e) => setProjectId(e.target.value)}
                    className="input"
                  >
                    <option value="">— Aucun (frais généraux) —</option>
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
              <div className="grid gap-4 sm:grid-cols-2">
                <div>
                  <label htmlFor="ae" className="label">
                    Employé assigné
                  </label>
                  <select
                    id="ae"
                    value={assignedEmpId}
                    onChange={(e) => setAssignedEmpId(e.target.value)}
                    className="input"
                  >
                    <option value="">— Aucun —</option>
                    {employes
                      .filter((e) => e.active !== false)
                      .map((e) => (
                        <option key={e.id} value={String(e.id)}>
                          {e.full_name}
                        </option>
                      ))}
                  </select>
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
                    <option value="">— À définir —</option>
                    {PAYMENT_OPTIONS.map((opt) => (
                      <option key={opt.value} value={opt.value}>
                        {opt.label}
                      </option>
                    ))}
                  </select>
                </div>
              </div>
              <div>
                <label htmlFor="ad" className="label">Description / matériel</label>
                <input
                  id="ad"
                  type="text"
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  className="input"
                />
              </div>
              <div>
                <label htmlFor="amax" className="label">
                  Montant max autorisé (CAD)
                </label>
                <input
                  id="amax"
                  type="number"
                  step="0.01"
                  min="0"
                  value={amountMax}
                  onChange={(e) => setAmountMax(e.target.value)}
                  className="input sm:w-48"
                />
              </div>
              <div>
                <label htmlFor="anotes" className="label">Notes internes</label>
                <textarea
                  id="anotes"
                  rows={3}
                  value={notes}
                  onChange={(e) => setNotes(e.target.value)}
                  className="input"
                />
              </div>
              <div>
                <label htmlFor="ast" className="label">Statut</label>
                <select
                  id="ast"
                  value={statusStr}
                  onChange={(e) => setStatusStr(e.target.value)}
                  className="input sm:w-60"
                >
                  {Object.entries(STATUS_LABELS).map(([k, v]) => (
                    <option key={k} value={k}>
                      {v}
                    </option>
                  ))}
                </select>
              </div>
              <div>
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
            </section>
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

      {showConvertModal && po ? (
        <ConvertToAchatModal
          po={po}
          onClose={() => setShowConvertModal(false)}
          onConverted={(achatId) => {
            setShowConvertModal(false);
            router.push(`/app/achats/${achatId}`);
          }}
        />
      ) : null}
    </>
  );
}

// ---------------------------------------------------------------------------
// Convert PO → Achat modal
// ---------------------------------------------------------------------------

function ConvertToAchatModal({
  po,
  onClose,
  onConverted
}: {
  po: PurchaseOrder;
  onClose: () => void;
  onConverted: (achatId: number) => void;
}) {
  const [amount, setAmount] = useState(
    po.amount_max != null ? String(po.amount_max) : ""
  );
  const [supplierInvoiceNumber, setSupplierInvoiceNumber] = useState("");
  const [invoiceDate, setInvoiceDate] = useState(() => {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(
      2,
      "0"
    )}-${String(d.getDate()).padStart(2, "0")}`;
  });
  const [paymentMethod, setPaymentMethod] = useState(
    po.payment_method || ""
  );
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      const res = await authedFetch(
        `/api/v1/purchase-orders/${po.id}/convert-to-achat`,
        {
          method: "POST",
          body: JSON.stringify({
            amount: amount ? Number(amount) : null,
            supplier_invoice_number: supplierInvoiceNumber.trim() || null,
            invoice_date: invoiceDate || null,
            payment_method: paymentMethod || null,
            notes: notes.trim() || null
          })
        }
      );
      if (!res.ok) {
        const t = await res.text();
        throw new Error(t.slice(0, 200) || `http_${res.status}`);
      }
      const created = (await res.json()) as { id: number };
      onConverted(created.id);
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm">
      <form
        onSubmit={submit}
        className="relative w-full max-w-lg rounded-2xl border border-brand-800 bg-brand-950 p-5 shadow-2xl"
      >
        <button
          type="button"
          onClick={onClose}
          className="absolute right-3 top-3 rounded-md p-1 text-white/50 hover:bg-brand-800 hover:text-white"
          aria-label="Fermer"
        >
          <X className="h-4 w-4" />
        </button>
        <h2 className="text-base font-bold text-white">
          <CheckCircle2 className="mr-2 inline h-4 w-4 text-emerald-400" />
          Convertir {po.reference} en achat
        </h2>
        <p className="mt-1 text-xs text-white/60">
          L&apos;Achat est créé en statut « reçu », lié à ce PO. Le push
          QuickBooks démarre automatiquement en arrière-plan.
        </p>

        {err ? (
          <p className="mt-3 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
            {err}
          </p>
        ) : null}

        <div className="mt-4 space-y-3">
          <div>
            <label htmlFor="ca" className="label">
              Montant réel (CAD)
            </label>
            <input
              id="ca"
              type="number"
              step="0.01"
              min="0"
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
              className="input"
              autoFocus
            />
            <p className="mt-1 text-[11px] text-white/50">
              Pré-rempli avec le max autorisé du PO. Ajuste au montant
              réel de la facture fournisseur.
            </p>
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <label htmlFor="csi" className="label">
                # facture fournisseur
              </label>
              <input
                id="csi"
                type="text"
                value={supplierInvoiceNumber}
                onChange={(e) => setSupplierInvoiceNumber(e.target.value)}
                placeholder="Ex. RNS-204582"
                className="input"
              />
            </div>
            <div>
              <label htmlFor="cid" className="label">
                Date de facture
              </label>
              <input
                id="cid"
                type="date"
                value={invoiceDate}
                onChange={(e) => setInvoiceDate(e.target.value)}
                className="input"
              />
            </div>
          </div>
          <div>
            <label htmlFor="cpm" className="label">Mode de paiement</label>
            <select
              id="cpm"
              value={paymentMethod}
              onChange={(e) => setPaymentMethod(e.target.value)}
              className="input"
            >
              <option value="">— Conserver celui du PO —</option>
              {PAYMENT_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label htmlFor="cnotes" className="label">Notes</label>
            <textarea
              id="cnotes"
              rows={2}
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              className="input"
            />
          </div>
        </div>

        <div className="mt-5 flex items-center justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            disabled={busy}
            className="btn-secondary text-xs"
          >
            Annuler
          </button>
          <button
            type="submit"
            disabled={busy}
            className="btn-accent text-sm"
          >
            {busy ? (
              <Loader2 className="mr-1 h-4 w-4 animate-spin" />
            ) : null}
            Créer l&apos;achat
          </button>
        </div>
      </form>
    </div>
  );
}
