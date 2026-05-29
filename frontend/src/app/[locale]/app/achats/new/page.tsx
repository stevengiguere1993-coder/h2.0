"use client";

import { useEffect, useState } from "react";
import {
  useRouter as useNextRouter,
  useSearchParams
} from "next/navigation";
import { ArrowLeft, Loader2 } from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { FournisseurModal } from "@/components/fournisseur-modal";
import { ReceiptScanner } from "@/components/receipt-scanner";
import { Link } from "@/i18n/navigation";
import { useAppLayout } from "../../layout";
import { authedFetch } from "@/lib/auth";
import { splitFromTotal } from "@/lib/tax";

type Project = { id: number; name: string; billing_kind?: string };
type Fournisseur = { id: number; name: string };
type POMini = {
  id: number;
  reference: string;
  fournisseur_id: number | null;
  project_id: number | null;
  payment_method: string | null;
  description: string | null;
  amount_max: number | string | null;
  status: string;
};

const PAYMENT_OPTIONS = [
  { value: "bill_to_pay", label: "Sur compte fournisseur (à payer plus tard)" },
  { value: "cheque_horizon", label: "Compte chèque Horizon" },
  { value: "cc_steven", label: "CC Horizon Steven Giguère" },
  { value: "cc_michael", label: "CC Horizon Michael Villiard" },
  { value: "cc_olivier", label: "CC Horizon Olivier Therrien" },
  { value: "cc_christian", label: "CC Horizon Christian Villiard" }
];

function todayIso(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(
    2,
    "0"
  )}-${String(d.getDate()).padStart(2, "0")}`;
}

export default function NewAchatPage() {
  const { onOpenSidebar } = useAppLayout();
  const router = useNextRouter();
  const searchParams = useSearchParams();
  const prefilledProjectId = searchParams.get("project_id");

  const [purchaseOrderId, setPurchaseOrderId] = useState("");
  const [projectId, setProjectId] = useState(prefilledProjectId || "");
  const [fournisseurId, setFournisseurId] = useState("");
  // Phase C — facture sous-traitant.
  const [kind, setKind] = useState<"material" | "sub_invoice">("material");
  const [sousTraitantId, setSousTraitantId] = useState("");
  const [hours, setHours] = useState("");
  const [sousTraitants, setSousTraitants] = useState<
    { id: number; full_name: string }[]
  >([]);
  const [description, setDescription] = useState("");
  // L'employé saisit le total (TTC) de la facture ; le HT et les taxes
  // sont décomposés automatiquement (TPS + TVQ) mais restent éditables.
  const [total, setTotal] = useState("");
  const [amount, setAmount] = useState("");
  const [amountTaxes, setAmountTaxes] = useState("");

  function onTotalChange(v: string) {
    setTotal(v);
    const n = Number(v);
    if (v.trim() !== "" && !Number.isNaN(n) && n > 0) {
      const { ht, taxes } = splitFromTotal(n);
      setAmount(ht.toFixed(2));
      setAmountTaxes(taxes.toFixed(2));
    }
  }

  function syncTotal(htStr: string, taxStr: string) {
    const sum = (Number(htStr) || 0) + (Number(taxStr) || 0);
    setTotal(sum ? sum.toFixed(2) : "");
  }
  function onAmountChange(v: string) {
    setAmount(v);
    syncTotal(v, amountTaxes);
  }
  function onTaxesChange(v: string) {
    setAmountTaxes(v);
    syncTotal(amount, v);
  }
  // Refacturation client.
  const [isBillable, setIsBillable] = useState(true);
  const [markupPercent, setMarkupPercent] = useState("");
  const [paymentMethod, setPaymentMethod] = useState("");
  const [supplierInvoiceNumber, setSupplierInvoiceNumber] = useState("");
  const [invoiceDate, setInvoiceDate] = useState(() => todayIso());

  const [projects, setProjects] = useState<Project[]>([]);
  const [fournisseurs, setFournisseurs] = useState<Fournisseur[]>([]);
  const [purchaseOrders, setPurchaseOrders] = useState<POMini[]>([]);
  const [showFournisseurModal, setShowFournisseurModal] = useState(false);
  const [receiptFile, setReceiptFile] = useState<File | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Défaut « refacturable » selon le type de la soumission du projet :
  // forfaitaire = décoché, estimé / à contrat = coché. Se réapplique
  // quand on change de projet ; un ajustement manuel reste possible
  // ensuite (l'effet ne dépend que du projet sélectionné).
  useEffect(() => {
    if (!projectId) return;
    const p = projects.find((x) => String(x.id) === String(projectId));
    if (p?.billing_kind) setIsBillable(p.billing_kind !== "forfaitaire");
  }, [projectId, projects]);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const [pRes, frRes, poRes, stRes] = await Promise.all([
          authedFetch("/api/v1/projects?limit=500"),
          authedFetch("/api/v1/fournisseurs?limit=500"),
          authedFetch("/api/v1/purchase-orders?limit=500"),
          authedFetch("/api/v1/sous-traitants?limit=500")
        ]);
        if (!cancelled) {
          if (pRes.ok) setProjects((await pRes.json()) as Project[]);
          if (frRes.ok)
            setFournisseurs((await frRes.json()) as Fournisseur[]);
          if (stRes.ok)
            setSousTraitants(
              (await stRes.json()) as { id: number; full_name: string }[]
            );
          if (poRes.ok) {
            const pos = (await poRes.json()) as POMini[];
            // Filtre : seulement les POs encore actifs (pas annulés
            // ni déjà convertis), pour ne pas polluer la liste.
            setPurchaseOrders(
              pos.filter(
                (po) =>
                  po.status !== "cancelled" && po.status !== "fulfilled"
              )
            );
          }
        }
      } catch {
        /* ignore */
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, []);

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const payload: Record<string, unknown> = {
        // Achat direct = received dès la création
        status: "received"
      };
      if (purchaseOrderId)
        payload.purchase_order_id = Number(purchaseOrderId);
      if (projectId) payload.project_id = Number(projectId);
      if (fournisseurId) payload.fournisseur_id = Number(fournisseurId);
      payload.kind = kind;
      if (kind === "sub_invoice" && sousTraitantId) {
        payload.sous_traitant_id = Number(sousTraitantId);
      }
      if (hours.trim()) payload.hours = Number(hours);
      if (description.trim()) payload.description = description.trim();
      if (amount) payload.amount = Number(amount);
      if (amountTaxes) payload.amount_taxes = Number(amountTaxes);
      payload.is_billable = isBillable;
      if (markupPercent.trim()) {
        payload.markup_percent = Number(markupPercent);
      }
      if (paymentMethod) payload.payment_method = paymentMethod;
      if (supplierInvoiceNumber.trim()) {
        payload.supplier_invoice_number = supplierInvoiceNumber.trim();
      }
      if (invoiceDate) payload.invoice_date = invoiceDate;

      const res = await authedFetch("/api/v1/achats", {
        method: "POST",
        body: JSON.stringify(payload)
      });
      if (!res.ok) {
        const txt = await res.text();
        throw new Error(txt.slice(0, 240) || `http_${res.status}`);
      }
      const created = (await res.json()) as { id: number };

      if (receiptFile) {
        const fd = new FormData();
        fd.append("file", receiptFile, receiptFile.name);
        const up = await authedFetch(
          `/api/v1/achats/${created.id}/receipt`,
          { method: "POST", body: fd }
        );
        if (!up.ok && up.status !== 204) {
          const txt = await up.text();
          setError(
            "Achat créé, mais l'upload du reçu a échoué : " +
              (txt.slice(0, 200) || `http_${up.status}`)
          );
        }
      }

      router.replace(`/app/achats/${created.id}`);
    } catch (err) {
      setError((err as Error).message);
      setSubmitting(false);
    }
  }

  return (
    <>
      <AppTopbar
        breadcrumbs={[
          { label: "Construction", href: "/app" },
          { label: "Achats / dépenses", href: "/app/achats" },
          { label: "Nouveau" }
        ]}
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

        <h1 className="mt-6 text-2xl font-bold text-white">
          Nouvel achat
        </h1>
        <p className="mt-1 text-sm text-white/60">
          Saisis l&apos;achat directement avec la facture du fournisseur.
          Lie-le à un PO existant si applicable, ou laisse vide pour un
          achat « on-the-fly ».
        </p>

        <form onSubmit={onSubmit} className="mt-6 max-w-2xl space-y-5">
          <div>
            <label htmlFor="po_source" className="label">
              PO source (optionnel)
            </label>
            <select
              id="po_source"
              value={purchaseOrderId}
              onChange={(e) => {
                const v = e.target.value;
                setPurchaseOrderId(v);
                if (v) {
                  // Pré-remplit depuis le PO sélectionné
                  const po = purchaseOrders.find(
                    (p) => String(p.id) === v
                  );
                  if (po) {
                    if (po.fournisseur_id)
                      setFournisseurId(String(po.fournisseur_id));
                    if (po.project_id)
                      setProjectId(String(po.project_id));
                    if (po.payment_method)
                      setPaymentMethod(po.payment_method);
                    if (po.description && !description)
                      setDescription(po.description);
                    if (po.amount_max != null && !amount) {
                      setAmount(String(po.amount_max));
                      syncTotal(String(po.amount_max), amountTaxes);
                    }
                  }
                }
              }}
              className="input"
            >
              <option value="">— Aucun (achat on-the-fly) —</option>
              {purchaseOrders.map((po) => (
                <option key={po.id} value={String(po.id)}>
                  {po.reference}
                  {po.description ? ` — ${po.description.slice(0, 40)}` : ""}
                </option>
              ))}
            </select>
            <p className="mt-1 text-[11px] text-white/50">
              Lie cet achat à un bon de commande existant pour pré-
              remplir fournisseur, projet et mode de paiement. Le PO
              passe en « Convertis en achat » à la création.
            </p>
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <label htmlFor="project" className="label">
                Projet
              </label>
              <select
                id="project"
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
              <label htmlFor="fournisseur" className="label">
                Fournisseur
              </label>
              <select
                id="fournisseur"
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
              <label htmlFor="sin" className="label">
                {purchaseOrderId
                  ? "Numéro de PO (lié)"
                  : "# facture fournisseur"}
              </label>
              {purchaseOrderId ? (
                <div className="input flex items-center gap-2 bg-brand-950/60 font-mono text-sm">
                  <span className="text-accent-300">
                    {purchaseOrders.find(
                      (po) => String(po.id) === purchaseOrderId
                    )?.reference || "—"}
                  </span>
                  <button
                    type="button"
                    onClick={() => setPurchaseOrderId("")}
                    className="ml-auto text-[11px] text-white/40 underline decoration-dotted hover:text-white"
                  >
                    Délier
                  </button>
                </div>
              ) : (
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
              )}
              <p className="mt-1 text-[11px] text-white/50">
                {purchaseOrderId
                  ? "Le numéro de PO sera utilisé comme DocNumber dans QuickBooks. Tu peux quand même ajouter le # facture fournisseur si tu l'as."
                  : "Apparaît comme DocNumber dans QuickBooks pour rapprochement."}
              </p>
              {purchaseOrderId ? (
                <input
                  type="text"
                  value={supplierInvoiceNumber}
                  onChange={(e) =>
                    setSupplierInvoiceNumber(e.target.value)
                  }
                  placeholder="# facture fournisseur (optionnel)"
                  className="input mt-2"
                />
              ) : null}
            </div>
            <div>
              <label htmlFor="idate" className="label">
                Date de facture
              </label>
              <input
                id="idate"
                type="date"
                value={invoiceDate}
                onChange={(e) => setInvoiceDate(e.target.value)}
                className="input"
              />
            </div>
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
              placeholder="0.00"
              className="input"
            />
            <p className="mt-1 text-xs text-white/40">
              Le HT et les taxes (TPS 5 % + TVQ 9,975 %) sont calculés
              automatiquement à partir du total. Ajustables si la facture a
              des taxes non standard.
            </p>
          </div>

          <div className="grid gap-4 sm:grid-cols-3">
            <div>
              <label htmlFor="amount" className="label">
                Montant HT (avant taxes)
              </label>
              <input
                id="amount"
                type="number"
                step="0.01"
                min="0"
                value={amount}
                onChange={(e) => onAmountChange(e.target.value)}
                placeholder="0.00"
                className="input"
              />
            </div>
            <div>
              <label htmlFor="amounttaxes" className="label">
                Taxes (CAD)
              </label>
              <input
                id="amounttaxes"
                type="number"
                step="0.01"
                min="0"
                value={amountTaxes}
                onChange={(e) => onTaxesChange(e.target.value)}
                placeholder="0.00"
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
                <option value="">— À définir —</option>
                {PAYMENT_OPTIONS.map((opt) => (
                  <option key={opt.value} value={opt.value}>
                    {opt.label}
                  </option>
                ))}
              </select>
            </div>
          </div>

          {/* Nature de l'achat — matériel ou facture sous-traitant */}
          <div className="rounded-xl border border-brand-800 bg-brand-900/40 p-4">
            <p className="mb-3 text-xs font-semibold uppercase tracking-wider text-white/60">
              Nature de l&apos;achat
            </p>
            <div className="grid gap-2 sm:grid-cols-2">
              <label
                className={`flex cursor-pointer items-center gap-2 rounded-lg border p-2 text-sm ${
                  kind === "material"
                    ? "border-accent-500 bg-accent-500/10 text-white"
                    : "border-brand-800 bg-brand-900 text-white/70"
                }`}
              >
                <input
                  type="radio"
                  name="kind"
                  value="material"
                  checked={kind === "material"}
                  onChange={() => setKind("material")}
                />
                Matériel / Marchandise
              </label>
              <label
                className={`flex cursor-pointer items-center gap-2 rounded-lg border p-2 text-sm ${
                  kind === "sub_invoice"
                    ? "border-accent-500 bg-accent-500/10 text-white"
                    : "border-brand-800 bg-brand-900 text-white/70"
                }`}
              >
                <input
                  type="radio"
                  name="kind"
                  value="sub_invoice"
                  checked={kind === "sub_invoice"}
                  onChange={() => setKind("sub_invoice")}
                />
                Facture sous-traitant
              </label>
            </div>
            {kind === "sub_invoice" ? (
              <div className="mt-3 grid gap-3 sm:grid-cols-2">
                <div>
                  <label htmlFor="ast" className="label">
                    Sous-traitant
                  </label>
                  <select
                    id="ast"
                    value={sousTraitantId}
                    onChange={(e) => setSousTraitantId(e.target.value)}
                    className="input"
                  >
                    <option value="">— Sélectionne —</option>
                    {sousTraitants.map((s) => (
                      <option key={s.id} value={s.id}>
                        {s.full_name}
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <label htmlFor="ahrs" className="label">
                    Heures (si facturation au taux horaire)
                  </label>
                  <input
                    id="ahrs"
                    type="number"
                    step="0.25"
                    min="0"
                    value={hours}
                    onChange={(e) => setHours(e.target.value)}
                    placeholder="0"
                    className="input"
                  />
                </div>
                <p className="text-xs text-white/40 sm:col-span-2">
                  Le montant facturé au client sera calculé selon le contrat
                  de projet (markup, taux horaire ou forfait). Configure le
                  contrat sur la page du projet.
                </p>
              </div>
            ) : null}
          </div>

          {/* Refacturation au client final */}
          <div className="rounded-xl border border-brand-800 bg-brand-900/40 p-4">
            <p className="mb-3 text-xs font-semibold uppercase tracking-wider text-white/60">
              Refacturation au client
            </p>
            <label className="mb-3 flex items-center gap-2 text-sm text-white/80">
              <input
                type="checkbox"
                checked={isBillable}
                onChange={(e) => setIsBillable(e.target.checked)}
              />
              Refacturable au client (apparaît dans « À refacturer »)
            </label>
            <label htmlFor="markup" className="label">
              Majoration (%) — appliquée au montant à l&apos;import facture
            </label>
            <input
              id="markup"
              type="number"
              step="0.5"
              min="0"
              max="500"
              value={markupPercent}
              onChange={(e) => setMarkupPercent(e.target.value)}
              placeholder="0"
              disabled={!isBillable}
              className="input"
            />
            <p className="mt-1 text-xs text-white/40">
              Laissé vide = aucun markup (le client paie le coûtant). Modifiable
              au moment de l&apos;import.
            </p>
          </div>

          <div>
            <label htmlFor="description" className="label">
              Description
            </label>
            <input
              id="description"
              type="text"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Ex. Bois traité 2x4, vis 2 1/2 (boîte)…"
              className="input"
            />
          </div>

          <div>
            <label className="label">Facture / reçu (optionnel)</label>
            <ReceiptScanner value={receiptFile} onChange={setReceiptFile} />
          </div>

          {error ? <p className="text-sm text-rose-400">{error}</p> : null}

          <div className="flex items-center gap-3">
            <button
              type="submit"
              disabled={submitting}
              className="btn-accent text-sm"
            >
              {submitting ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" /> Création…
                </>
              ) : (
                "Créer l'achat"
              )}
            </button>
            <Link
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
              href={"/app/achats" as any}
              className="btn-secondary text-sm"
            >
              Annuler
            </Link>
          </div>
        </form>
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
