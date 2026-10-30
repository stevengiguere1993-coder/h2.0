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
import { SearchSelect } from "@/components/search-select";
import { Link } from "@/i18n/navigation";
import { useAppLayout } from "../../layout";
import { authedFetch } from "@/lib/auth";
import { splitFromTotal, TPS_RATE, TVQ_RATE } from "@/lib/tax";
import {
  projectLabel,
  fournisseursPourAchat,
  trierProjetsParAdresse
} from "@/lib/project";

type Project = {
  id: number;
  name: string;
  address?: string | null;
  billing_kind?: string;
};
type Fournisseur = {
  id: number;
  name: string;
  active?: boolean;
  in_directory?: boolean;
};
type BonMini = {
  id: number;
  reference: string;
  title: string;
  status: string;
  kind?: string | null;
  address?: string | null;
};
type ClientMini = { id: number; name: string };
type POMini = {
  id: number;
  reference: string;
  fournisseur_id: number | null;
  is_shop?: boolean;
  project_id: number | null;
  payment_method: string | null;
  description: string | null;
  amount_max: number | string | null;
  status: string;
};

// Une part d'un reçu DIVISÉ entre plusieurs projets (Steven 2026-10-30) :
// un projet ou un bon de travail, le montant TTC qui lui revient et le choix
// « à refacturer » (null = défaut du projet : contrat / bon → oui).
type PartRow = {
  key: number;
  cible: "projet" | "bon";
  id: string;
  total: string;
  billable: boolean | null;
};

function round2(n: number): number {
  return Math.round(n * 100) / 100;
}

function fmtMoney(n: number): string {
  return new Intl.NumberFormat("fr-CA", {
    style: "currency",
    currency: "CAD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2
  }).format(n);
}

/** Message d'erreur lisible : le `detail` JSON du serveur (messages en
 *  français) plutôt que le corps brut. */
function detailErreur(txt: string, status: number): string {
  try {
    const j = JSON.parse(txt) as { detail?: unknown };
    if (typeof j.detail === "string") return j.detail;
  } catch {
    /* texte brut */
  }
  return txt.slice(0, 240) || `http_${status}`;
}

const PAYMENT_OPTIONS = [
  { value: "bill_to_pay", label: "Facture à payer (compte fournisseur — un ou plusieurs paiements)" },
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
  // Rattachement du reçu : un PROJET, un BON DE TRAVAIL (son projet lié
  // est garanti à la sélection) ou un CLIENT direct (reçu hors projet).
  const [targetType, setTargetType] = useState<"projet" | "bon" | "client" | "shop">(
    "projet"
  );
  const [bonId, setBonId] = useState("");
  const [clientIdSel, setClientIdSel] = useState("");
  const [bons, setBons] = useState<BonMini[]>([]);
  const [clients, setClients] = useState<ClientMini[]>([]);
  // Reçu DIVISÉ entre plusieurs projets : une coche, puis une ligne par
  // projet / bon de travail avec le montant TTC qui lui revient. Un achat
  // par projet dans Kratos, UNE seule facture dans QuickBooks (une ligne
  // par projet). Possible pour la cible « Projet » seulement (client
  // direct et shop n'ont pas de sous-client projet par ligne).
  const [divise, setDivise] = useState(false);
  const [parts, setParts] = useState<PartRow[]>([
    { key: 1, cible: "projet", id: "", total: "", billable: null },
    { key: 2, cible: "projet", id: "", total: "", billable: null }
  ]);

  const [fournisseurId, setFournisseurId] = useState("");
  // Nature de l'achat : matériel, facture sous-traitant, outils ou
  // location d'outils.
  const [kind, setKind] = useState<
    "material" | "sub_invoice" | "tools" | "tool_rental"
  >("material");
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
    // Saisie du montant HT → on calcule TPS + TVQ + total automatiquement
    // (restent éditables ensuite). Champ vidé → on resynchronise le total.
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
  // Refacturation client. Majoration par défaut : 10 % quand l'achat est
  // refacturable (modifiable librement, 0 = coûtant).
  const [isBillable, setIsBillable] = useState(true);
  const [markupPercent, setMarkupPercent] = useState("10");
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
    // Refacturable par défaut UNIQUEMENT pour un projet à CONTRAT
    // (coûtant majoré). Estimé et forfaitaire → décoché (le prix
    // donné au client couvre les dépenses) ; cochable à la main.
    if (p?.billing_kind) setIsBillable(p.billing_kind === "contrat");
  }, [projectId, projects]);

  // Bon de travail = T&M refacturé au client → refacturable par défaut.
  useEffect(() => {
    if (targetType === "bon") setIsBillable(true);
  }, [targetType]);

  // ── Répartition entre projets (reçu divisé) ──
  const enDivision = divise && targetType === "projet";
  const totalNum = Number(total) || 0;
  const sommeParts = round2(
    parts.reduce((s, p) => s + (Number(p.total) || 0), 0)
  );
  const reste = round2(totalNum - sommeParts);
  function defautRefact(p: PartRow): boolean {
    // Bon de travail = T&M refacturé ; projet : contrat seulement.
    if (p.cible === "bon") return true;
    const pr = projects.find((x) => String(x.id) === p.id);
    return pr?.billing_kind === "contrat";
  }
  const partsCles = parts.map((p) => (p.id ? `${p.cible}:${p.id}` : ""));
  const partsDoublon = partsCles.some(
    (k, i) => k !== "" && partsCles.indexOf(k) !== i
  );
  const partsIncompletes = parts.some(
    (p) => !p.id || !(Number(p.total) > 0)
  );
  const repartiAuComplet = totalNum > 0 && Math.abs(reste) < 0.005;
  const divisionPrete =
    !enDivision ||
    (parts.length >= 2 &&
      !partsIncompletes &&
      !partsDoublon &&
      repartiAuComplet);
  const refactParts = parts.some((p) => p.billable ?? defautRefact(p));
  const refacturableEffectif = enDivision ? refactParts : isBillable;

  function majPart(key: number, patch: Partial<PartRow>) {
    setParts((prev) =>
      prev.map((p) => (p.key === key ? { ...p, ...patch } : p))
    );
  }
  function ajouterPart() {
    setParts((prev) => [
      ...prev,
      { key: Date.now(), cible: "projet", id: "", total: "", billable: null }
    ]);
  }
  function retirerPart(key: number) {
    setParts((prev) =>
      prev.length <= 2 ? prev : prev.filter((p) => p.key !== key)
    );
  }
  // Parts égales au cent près ; la dernière absorbe l'arrondi.
  function repartirEgalement() {
    if (!(totalNum > 0) || parts.length === 0) return;
    const n = parts.length;
    const base = Math.floor((totalNum / n) * 100) / 100;
    const dernier = round2(totalNum - base * (n - 1));
    setParts((prev) =>
      prev.map((p, i) => ({
        ...p,
        total: (i === n - 1 ? dernier : base).toFixed(2)
      }))
    );
  }
  function basculerDivise(on: boolean) {
    setDivise(on);
    // Le projet déjà choisi devient la première part.
    if (on && projectId) {
      setParts((prev) =>
        prev.map((p, i) =>
          i === 0 && !p.id ? { ...p, cible: "projet", id: projectId } : p
        )
      );
    }
  }

  // Majoration par défaut : 10 % dès que l'achat est refacturable (si le
  // champ est vide), vidée si non refacturable. La saisie manuelle est
  // préservée. Reçu divisé : refacturable dès qu'une part l'est.
  useEffect(() => {
    setMarkupPercent((prev) =>
      refacturableEffectif ? (prev.trim() === "" ? "10" : prev) : ""
    );
  }, [refacturableEffectif]);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const [pRes, frRes, poRes, stRes, bRes, cRes] = await Promise.all([
          authedFetch("/api/v1/projects?limit=500"),
          authedFetch("/api/v1/fournisseurs?limit=500"),
          authedFetch("/api/v1/purchase-orders?limit=500"),
          authedFetch("/api/v1/sous-traitants?limit=500"),
          authedFetch("/api/v1/bons-travail?limit=500"),
          authedFetch("/api/v1/clients?limit=500")
        ]);
        if (!cancelled) {
          if (pRes.ok) setProjects((await pRes.json()) as Project[]);
          if (bRes.ok) {
            const bs = (await bRes.json()) as BonMini[];
            // Bons actifs seulement (pas annulés / déjà facturés).
            setBons(
              bs.filter(
                (b) => b.status !== "cancelled" && b.status !== "facture"
              )
            );
          }
          if (cRes.ok) setClients((await cRes.json()) as ClientMini[]);
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
      if (enDivision) {
        // Reçu divisé : les projets sont dans `parts` (ci-dessous).
      } else if (targetType === "bon" && bonId) {
        // Le bon porte ses coûts via son PROJET lié (garanti ici) : le
        // reçu suit alors toute la machinerie projet (sous-client QB
        // « BT-xx », classe, refacturation).
        const bp = await authedFetch(
          `/api/v1/bons-travail/${Number(bonId)}/ensure-project`,
          { method: "POST" }
        );
        if (!bp.ok) throw new Error("Projet du bon introuvable.");
        const bpj = (await bp.json()) as { project_id: number };
        payload.project_id = bpj.project_id;
      } else if (targetType === "client" && clientIdSel) {
        // Reçu hors projet/BT → rattaché au CLIENT (CustomerRef QB).
        payload.client_id = Number(clientIdSel);
      } else if (targetType === "projet" && projectId) {
        payload.project_id = Number(projectId);
      } else if (targetType === "shop") {
        payload.is_shop = true;
      }
      if (fournisseurId) payload.fournisseur_id = Number(fournisseurId);
      payload.kind = kind;
      if (kind === "sub_invoice" && sousTraitantId) {
        payload.sous_traitant_id = Number(sousTraitantId);
      }
      if (hours.trim()) payload.hours = Number(hours);
      if (description.trim()) payload.description = description.trim();
      if (amount) payload.amount = Number(amount);
      if (amountTps) payload.amount_tps = Number(amountTps);
      if (amountTvq) payload.amount_tvq = Number(amountTvq);
      if (amountTps || amountTvq) {
        payload.amount_taxes =
          Math.round(
            ((Number(amountTps) || 0) + (Number(amountTvq) || 0)) * 100
          ) / 100;
      }
      // Reçu divisé : « à refacturer » se décide PAR PART (défaut du
      // projet côté serveur quand la ligne n'a pas été touchée).
      if (!enDivision) payload.is_billable = isBillable;
      if (markupPercent.trim()) {
        payload.markup_percent = Number(markupPercent);
      }
      if (paymentMethod) payload.payment_method = paymentMethod;
      if (supplierInvoiceNumber.trim()) {
        payload.supplier_invoice_number = supplierInvoiceNumber.trim();
      }
      if (invoiceDate) payload.invoice_date = invoiceDate;

      let createdId: number;
      if (enDivision) {
        // Une part par projet ; un bon de travail passe par son projet
        // porteur (garanti ici, comme pour un reçu simple).
        const partsPayload: {
          project_id: number;
          total: number;
          is_billable?: boolean;
        }[] = [];
        for (const p of parts) {
          let pid = Number(p.id);
          if (p.cible === "bon") {
            const bp = await authedFetch(
              `/api/v1/bons-travail/${pid}/ensure-project`,
              { method: "POST" }
            );
            if (!bp.ok)
              throw new Error("Projet du bon de travail introuvable.");
            pid = ((await bp.json()) as { project_id: number }).project_id;
          }
          const row: {
            project_id: number;
            total: number;
            is_billable?: boolean;
          } = { project_id: pid, total: round2(Number(p.total) || 0) };
          if (p.billable !== null) row.is_billable = p.billable;
          partsPayload.push(row);
        }
        payload.parts = partsPayload;
        const res = await authedFetch("/api/v1/achats/divise", {
          method: "POST",
          body: JSON.stringify(payload)
        });
        if (!res.ok) {
          throw new Error(detailErreur(await res.text(), res.status));
        }
        const body = (await res.json()) as {
          groupe_id: number;
          parts: { id: number }[];
        };
        createdId = body.parts[0]?.id ?? body.groupe_id;
      } else {
        const res = await authedFetch("/api/v1/achats", {
          method: "POST",
          body: JSON.stringify(payload)
        });
        if (!res.ok) {
          throw new Error(detailErreur(await res.text(), res.status));
        }
        createdId = ((await res.json()) as { id: number }).id;
      }

      if (receiptFile) {
        // Reçu divisé : téléversé sur la première part, recopié sur les
        // autres par le serveur.
        const fd = new FormData();
        fd.append("file", receiptFile, receiptFile.name);
        const up = await authedFetch(
          `/api/v1/achats/${createdId}/receipt`,
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

      router.replace(`/app/achats/${createdId}`);
    } catch (err) {
      setError((err as Error).message);
      setSubmitting(false);
    }
  }

  const projetOptions = trierProjetsParAdresse(projects).map((p) => ({
    value: String(p.id),
    label: projectLabel(p)
  }));
  // Numéro + adresse du chantier + description.
  const bonOptions = bons.map((b) => ({
    value: String(b.id),
    label: `${b.reference} — ${
      (b.address || "").trim() ? `${(b.address || "").trim()} · ` : ""
    }${b.title}`
  }));

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
                    if (po.project_id) {
                      setProjectId(String(po.project_id));
                      setTargetType("projet");
                    } else if (po.is_shop) {
                      setTargetType("shop");
                    }
                    if (po.payment_method)
                      setPaymentMethod(po.payment_method);
                    if (po.description && !description)
                      setDescription(po.description);
                    if (po.amount_max != null && !amount) {
                      setAmount(String(po.amount_max));
                      syncTotal(String(po.amount_max), amountTps, amountTvq);
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
              <span className="label">Rattacher à</span>
              <div className="mb-2 inline-flex rounded-md border border-brand-800 bg-brand-950 p-0.5 text-[11px]">
                {(
                  [
                    ["projet", "Projet"],
                    ["bon", "Bon de travail"],
                    ["client", "Client"],
                    ["shop", "Shop"]
                  ] as const
                ).map(([val, lab]) => (
                  <button
                    key={val}
                    type="button"
                    onClick={() => setTargetType(val)}
                    className={`rounded px-2.5 py-1 font-semibold transition ${
                      targetType === val
                        ? "bg-accent-500 text-brand-950"
                        : "text-white/70 hover:bg-white/5"
                    }`}
                  >
                    {lab}
                  </button>
                ))}
              </div>
              {targetType === "projet" ? (
                <>
                  {divise ? (
                    <p className="rounded-md border border-sky-500/30 bg-sky-500/15 px-3 py-2 text-xs text-white/80">
                      Les projets et le montant de chacun se choisissent dans
                      « Répartition entre projets », sous le total.
                    </p>
                  ) : (
                    <SearchSelect
                      id="project"
                      value={projectId}
                      onChange={setProjectId}
                      options={projetOptions}
                      placeholder="Choisis ou tape pour chercher un projet…"
                      emptyLabel="— Aucun (frais généraux) —"
                    />
                  )}
                  <label className="mt-2 flex items-start gap-2 text-xs text-white/80">
                    <input
                      type="checkbox"
                      className="mt-0.5"
                      checked={divise}
                      onChange={(e) => basculerDivise(e.target.checked)}
                    />
                    <span>
                      Cette facture touche plusieurs projets (diviser le
                      montant par projet)
                    </span>
                  </label>
                </>
              ) : targetType === "bon" ? (
                <SearchSelect
                  id="bon"
                  value={bonId}
                  onChange={setBonId}
                  options={bonOptions}
                  placeholder="Choisis ou tape pour chercher un bon de travail…"
                  emptyLabel="— Aucun —"
                />
              ) : targetType === "shop" ? (
                <p className="rounded-md border border-brand-800 bg-brand-950 px-3 py-2 text-xs text-white/70">
                  Achat pour le shop (atelier, camion, outillage), non relié à un projet.
                  Dans QuickBooks : classe <strong>Construction</strong>, aucun client.
                </p>
              ) : (
                <SearchSelect
                  id="client-direct"
                  value={clientIdSel}
                  onChange={setClientIdSel}
                  options={clients.map((c) => ({
                    value: String(c.id),
                    label: c.name
                  }))}
                  placeholder="Choisis ou tape pour chercher un client…"
                  emptyLabel="— Aucun —"
                />
              )}
            </div>
            <div>
              <label htmlFor="fournisseur" className="label">
                Fournisseur
              </label>
              <SearchSelect
                id="fournisseur"
                value={fournisseurId}
                onChange={(v) => {
                  if (v === "__new__") {
                    setShowFournisseurModal(true);
                    return;
                  }
                  setFournisseurId(v);
                }}
                emptyLabel="— Aucun —"
                placeholder="Choisis ou tape le nom du fournisseur…"
                options={[
                  ...fournisseursPourAchat(
                    fournisseurs,
                    clients.map((c) => c.name),
                    fournisseurId
                  ).map((fr) => ({
                    value: String(fr.id),
                    label: fr.name
                  })),
                  {
                    value: "__new__",
                    label: "+ Nouveau fournisseur…",
                    pinned: true
                  }
                ]}
              />
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

          {enDivision ? (
            <div className="rounded-xl border border-sky-500/30 bg-brand-900/40 p-4">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="text-xs font-semibold uppercase tracking-wider text-white/60">
                  Répartition entre projets
                </p>
                <span
                  className={`text-xs font-semibold ${
                    repartiAuComplet ? "text-emerald-300" : "text-rose-400"
                  }`}
                >
                  {totalNum > 0
                    ? repartiAuComplet
                      ? "Réparti au complet"
                      : `Reste à répartir : ${fmtMoney(reste)}`
                    : "Entre d'abord le total de la facture"}
                </span>
              </div>
              <div className="mt-3 space-y-2">
                {parts.map((p, i) => (
                  <div
                    key={p.key}
                    className="grid grid-cols-1 gap-2 rounded-lg border border-brand-800 p-2 sm:grid-cols-[7.5rem_minmax(0,1fr)_8rem_auto_auto] sm:items-center sm:border-0 sm:p-0"
                  >
                    <select
                      value={p.cible}
                      onChange={(e) =>
                        majPart(p.key, {
                          cible: e.target.value as "projet" | "bon",
                          id: ""
                        })
                      }
                      className="input text-xs"
                      aria-label={`Type de la part ${i + 1}`}
                    >
                      <option value="projet">Projet</option>
                      <option value="bon">Bon de travail</option>
                    </select>
                    <SearchSelect
                      id={`part-${p.key}`}
                      value={p.id}
                      onChange={(v) => majPart(p.key, { id: v })}
                      options={p.cible === "projet" ? projetOptions : bonOptions}
                      placeholder={
                        p.cible === "projet"
                          ? "Choisis ou tape pour chercher un projet…"
                          : "Choisis ou tape pour chercher un bon de travail…"
                      }
                    />
                    <input
                      type="number"
                      inputMode="decimal"
                      step="0.01"
                      min="0"
                      value={p.total}
                      onChange={(e) => majPart(p.key, { total: e.target.value })}
                      placeholder="Montant TTC"
                      className="input"
                      aria-label={`Montant TTC de la part ${i + 1}`}
                    />
                    <label
                      className="flex min-h-9 items-center gap-1.5 text-xs text-white/80"
                      title="À refacturer au client ? Par défaut : contrat ou bon de travail → oui ; forfait ou estimé → non."
                    >
                      <input
                        type="checkbox"
                        checked={p.billable ?? defautRefact(p)}
                        onChange={(e) =>
                          majPart(p.key, { billable: e.target.checked })
                        }
                      />
                      Refact.
                    </label>
                    <button
                      type="button"
                      onClick={() => retirerPart(p.key)}
                      disabled={parts.length <= 2}
                      className="btn-secondary min-h-9 text-xs disabled:opacity-40"
                      aria-label={`Retirer la part ${i + 1}`}
                    >
                      Retirer
                    </button>
                  </div>
                ))}
              </div>
              <div className="mt-3 flex flex-col gap-2 sm:flex-row">
                <button
                  type="button"
                  onClick={ajouterPart}
                  className="btn-secondary min-h-9 text-xs"
                >
                  + Ajouter un projet
                </button>
                <button
                  type="button"
                  onClick={repartirEgalement}
                  disabled={!(totalNum > 0)}
                  className="btn-secondary min-h-9 text-xs disabled:opacity-40"
                >
                  Répartir également
                </button>
              </div>
              <p className="mt-2 text-[11px] text-white/50">
                Un achat par projet dans Kratos (coûts et refacturation par
                projet) et UNE seule facture dans QuickBooks, une ligne par
                projet. Refacturation décidée projet par projet : contrat ou
                bon de travail → refacturable ; forfait ou estimé → non.
                Coche ou décoche par ligne au besoin.
              </p>
              {partsDoublon ? (
                <p className="mt-1 text-xs text-rose-400">
                  Chaque projet ne peut apparaître qu&apos;une fois.
                </p>
              ) : partsIncompletes ? (
                <p className="mt-1 text-xs text-rose-400">
                  Choisis un projet et entre un montant pour chaque ligne.
                </p>
              ) : null}
            </div>
          ) : null}

          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
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
              <label htmlFor="amounttps" className="label">
                TPS (5 %)
              </label>
              <input
                id="amounttps"
                type="number"
                step="0.01"
                min="0"
                value={amountTps}
                onChange={(e) => onTpsChange(e.target.value)}
                placeholder="0.00"
                className="input"
              />
            </div>
            <div>
              <label htmlFor="amounttvq" className="label">
                TVQ (9,975 %)
              </label>
              <input
                id="amounttvq"
                type="number"
                step="0.01"
                min="0"
                value={amountTvq}
                onChange={(e) => onTvqChange(e.target.value)}
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
            <label
              htmlFor="akind"
              className="mb-3 block text-xs font-semibold uppercase tracking-wider text-white/60"
            >
              Nature de l&apos;achat
            </label>
            <select
              id="akind"
              value={kind}
              onChange={(e) =>
                setKind(
                  e.target.value as
                    | "material"
                    | "sub_invoice"
                    | "tools"
                    | "tool_rental"
                )
              }
              className="input"
            >
              <option value="material">Matériel / Marchandise</option>
              <option value="sub_invoice">Facture sous-traitant</option>
              <option value="tools">Outils</option>
              <option value="tool_rental">Location d&apos;outils</option>
            </select>
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
                  {enDivision
                    ? " Reçu divisé : les heures sont réparties entre les projets au prorata des montants."
                    : ""}
                </p>
              </div>
            ) : null}
          </div>

          {/* Refacturation au client final */}
          <div className="rounded-xl border border-brand-800 bg-brand-900/40 p-4">
            <p className="mb-3 text-xs font-semibold uppercase tracking-wider text-white/60">
              Refacturation au client
            </p>
            {enDivision ? (
              <p className="mb-3 text-sm text-white/80">
                Décidée projet par projet dans « Répartition entre projets »
                (case « Refact. » de chaque ligne).
              </p>
            ) : (
              <label className="mb-3 flex items-center gap-2 text-sm text-white/80">
                <input
                  type="checkbox"
                  checked={isBillable}
                  onChange={(e) => setIsBillable(e.target.checked)}
                />
                Refacturable au client (apparaît dans « À refacturer »)
              </label>
            )}
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
              disabled={!refacturableEffectif}
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
              disabled={submitting || !divisionPrete}
              className="btn-accent text-sm disabled:opacity-50"
              title={
                divisionPrete
                  ? undefined
                  : "Complète la répartition entre projets (reste à répartir = 0)"
              }
            >
              {submitting ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" /> Création…
                </>
              ) : enDivision ? (
                `Créer le reçu divisé (${parts.length} projets)`
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
