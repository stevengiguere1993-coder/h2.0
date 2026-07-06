"use client";

import { useEffect, useState } from "react";
import {
  useRouter as useNextRouter,
  useSearchParams
} from "next/navigation";
import { ArrowLeft, Loader2 } from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { FournisseurModal } from "@/components/fournisseur-modal";
import { Link } from "@/i18n/navigation";
import { useAppLayout } from "../../layout";
import { authedFetch } from "@/lib/auth";
import { projectLabel } from "@/lib/project";

type Project = { id: number; name: string; address?: string | null };
type Fournisseur = { id: number; name: string };
type Employe = {
  id: number;
  full_name: string;
  email: string | null;
  active?: boolean;
};

const PAYMENT_OPTIONS = [
  { value: "bill_to_pay", label: "Facture à payer (compte fournisseur — un ou plusieurs paiements)" },
  { value: "cheque_horizon", label: "Compte chèque Horizon" },
  { value: "cc_steven", label: "CC Horizon Steven Giguère" },
  { value: "cc_michael", label: "CC Horizon Michael Villiard" },
  { value: "cc_olivier", label: "CC Horizon Olivier Therrien" },
  { value: "cc_christian", label: "CC Horizon Christian Villiard" }
];

export default function NewPurchaseOrderPage() {
  const { onOpenSidebar } = useAppLayout();
  const router = useNextRouter();
  const searchParams = useSearchParams();
  const prefilledProjectId = searchParams.get("project_id");
  const phaseHint = searchParams.get("phase_hint");

  const [projectId, setProjectId] = useState(prefilledProjectId || "");
  const [fournisseurId, setFournisseurId] = useState("");
  const [description, setDescription] = useState(
    phaseHint ? `Phase ${phaseHint} — ` : ""
  );
  const [amountMax, setAmountMax] = useState("");
  const [assignedEmpId, setAssignedEmpId] = useState("");
  const [paymentMethod, setPaymentMethod] = useState("");

  const [projects, setProjects] = useState<Project[]>([]);
  const [fournisseurs, setFournisseurs] = useState<Fournisseur[]>([]);
  const [employes, setEmployes] = useState<Employe[]>([]);
  const [showFournisseurModal, setShowFournisseurModal] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const [pRes, frRes, eRes] = await Promise.all([
          authedFetch("/api/v1/projects?limit=500"),
          authedFetch("/api/v1/fournisseurs?limit=500"),
          authedFetch("/api/v1/employes?limit=500&volet=construction")
        ]);
        if (!cancelled) {
          if (pRes.ok) setProjects((await pRes.json()) as Project[]);
          if (frRes.ok)
            setFournisseurs((await frRes.json()) as Fournisseur[]);
          if (eRes.ok) setEmployes((await eRes.json()) as Employe[]);
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
      const payload: Record<string, unknown> = {};
      if (projectId) payload.project_id = Number(projectId);
      if (fournisseurId) payload.fournisseur_id = Number(fournisseurId);
      if (description.trim()) payload.description = description.trim();
      if (amountMax) payload.amount_max = Number(amountMax);
      if (assignedEmpId) payload.assigned_employe_id = Number(assignedEmpId);
      if (paymentMethod) payload.payment_method = paymentMethod;

      const res = await authedFetch("/api/v1/purchase-orders", {
        method: "POST",
        body: JSON.stringify(payload)
      });
      if (!res.ok) {
        const txt = await res.text();
        throw new Error(txt.slice(0, 240) || `http_${res.status}`);
      }
      const created = (await res.json()) as { id: number };
      router.replace(`/app/po/${created.id}`);
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
          { label: "Bons de commande", href: "/app/po" },
          { label: "Nouveau" }
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

        <h1 className="mt-6 text-2xl font-bold text-white">
          Nouveau bon de commande
        </h1>
        <p className="mt-1 text-sm text-white/60">
          Le numéro PO sera attribué automatiquement (suite alignée
          sur ta numérotation QuickBooks). Aucun impact comptable
          tant qu&apos;un Achat n&apos;est pas créé à partir de ce PO.
        </p>

        <form onSubmit={onSubmit} className="mt-6 max-w-2xl space-y-5">
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
                    {projectLabel(p)}
                  </option>
                ))}
              </select>
              <p className="mt-1 text-[11px] text-white/50">
                Vide = matériaux généraux (caulking, vis, outils
                partagés).
              </p>
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
              <p className="mt-1 text-[11px] text-white/50">
                Recevra le PO par courriel quand tu cliques sur
                « Envoyer le PO ».
              </p>
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
              <p className="mt-1 text-[11px] text-white/50">
                Pré-rempli sur l&apos;Achat dérivé. Détermine le
                routage QB (Bill ou Purchase).
              </p>
            </div>
          </div>

          <div>
            <label htmlFor="description" className="label">
              Description / matériel
            </label>
            <input
              id="description"
              type="text"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Ex. 70 tubes caulking, vis 2 1/2 (2 boîtes)…"
              className="input"
            />
          </div>

          <div>
            <label htmlFor="amount_max" className="label">
              Montant max autorisé (CAD)
            </label>
            <input
              id="amount_max"
              type="number"
              step="0.01"
              min="0"
              value={amountMax}
              onChange={(e) => setAmountMax(e.target.value)}
              placeholder="0.00"
              className="input sm:w-48"
            />
            <p className="mt-1 text-[11px] text-white/50">
              Plafond budgétaire indicatif pour l&apos;employé. Le
              montant réel sera saisi sur l&apos;Achat à la
              conversion.
            </p>
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
                "Créer le PO"
              )}
            </button>
            <Link
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
              href={"/app/po" as any}
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
