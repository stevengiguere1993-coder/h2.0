"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useParams, useRouter as useNextRouter } from "next/navigation";
import {
  ArrowLeft,
  Briefcase,
  Check,
  Eye,
  EyeOff,
  FileText,
  Users,
  Loader2,
  Mail,
  PenTool,
  Plus,
  RefreshCw,
  Save,
  Send,
  Trash2
} from "lucide-react";

import { AddressInput } from "@/components/address-input";
import { AppTopbar } from "@/components/app-topbar";
import {
  ContractForm,
  defaultContractData,
  normalizeContractData,
  type ContractData,
  type UserOption
} from "@/components/contract-form";
import { FollowUpTimeline } from "@/components/follow-up-timeline";
import { Link } from "@/i18n/navigation";
import { useAppLayout } from "../../layout";
import { authedFetch } from "@/lib/auth";
import { useConfirm } from "@/components/confirm-dialog";

type Soumission = {
  id: number;
  reference: string;
  contact_request_id: number | null;
  client_id: number | null;
  title: string;
  description: string | null;
  subtotal: number | null;
  tps: number | null;
  tvq: number | null;
  total: number | null;
  status: string;
  sent_at: string | null;
  accepted_at: string | null;
  valid_until: string | null;
  pdf_url: string | null;
  notes: string | null;
  client_note: string | null;
  property_address: string | null;
  pricing_kind?: "forfaitaire" | "estime";
  kind?: "quote" | "contract";
  contract_data?: string | null;
  contractor_signed_name?: string | null;
  contractor_signed_at?: string | null;
  contractor_signature_token?: string | null;
  signed_name?: string | null;
  client_opened_at?: string | null;
  client_last_opened_at?: string | null;
  client_open_count?: number;
  contractor_opened_at?: string | null;
  contractor_last_opened_at?: string | null;
  contractor_open_count?: number;
  created_at: string;
  qbo_estimate_id?: string | null;
  qbo_doc_number?: string | null;
  qbo_sync_token?: string | null;
};

type Item = {
  id: number;
  soumission_id: number;
  position: number;
  description: string;
  unit: string | null;
  quantity: number;
  unit_price: number;
  cost_per_unit: number;
  total: number;
  tps_applicable: boolean;
  tvq_applicable: boolean;
  kind: "service" | "frais" | "rabais";
};

const STATUS_LABELS: Record<string, string> = {
  draft: "Brouillon",
  sent: "Envoyée",
  accepted: "Acceptée",
  rejected: "Refusée",
  expired: "Expirée"
};

const STATUS_CLASS: Record<string, string> = {
  draft: "bg-white/10 text-white",
  sent: "bg-blue-500/20 text-blue-300",
  accepted: "bg-emerald-500/20 text-emerald-300",
  rejected: "bg-rose-500/20 text-rose-300",
  expired: "bg-amber-500/20 text-amber-300"
};

const TPS_RATE = 0.05;
const TVQ_RATE = 0.09975;

function fmtMoney(n: number | null): string {
  if (n == null) return "—";
  return new Intl.NumberFormat("fr-CA", {
    style: "currency",
    currency: "CAD",
    maximumFractionDigits: 2
  }).format(n);
}

function fmtDateTime(iso: string): string {
  // Affiche « 16 mai 2026 à 14:43 » dans la locale du navigateur.
  const d = new Date(iso);
  const date = d.toLocaleDateString("fr-CA", {
    day: "numeric",
    month: "short",
    year: "numeric"
  });
  const time = d.toLocaleTimeString("fr-CA", {
    hour: "2-digit",
    minute: "2-digit"
  });
  return `${date} à ${time}`;
}
function isoToDateInput(iso: string | null): string {
  if (!iso) return "";
  return iso.slice(0, 10);
}

export default function SoumissionDetailPage() {
  const confirm = useConfirm();
  const { onOpenSidebar } = useAppLayout();
  const params = useParams<{ id: string }>();
  const id = Number(params.id);
  const router = useNextRouter();

  const [s, setS] = useState<Soumission | null>(null);
  const [items, setItems] = useState<Item[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [itemBusy, setItemBusy] = useState<number | "new" | null>(null);
  const [templatePickerOpen, setTemplatePickerOpen] = useState(false);
  const [qboBusy, setQboBusy] = useState(false);
  const [qboNotice, setQboNotice] = useState<string | null>(null);

  const [sendOpen, setSendOpen] = useState(false);
  const [sendBusy, setSendBusy] = useState(false);
  const [sendNotice, setSendNotice] = useState<string | null>(null);
  const [sendTo, setSendTo] = useState("");
  const [sendCc, setSendCc] = useState("");
  const [sendSubject, setSendSubject] = useState("");
  const [sendMessage, setSendMessage] = useState("");

  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [validUntil, setValidUntil] = useState<string>("");
  const [notes, setNotes] = useState("");
  const [clientNote, setClientNote] = useState("");
  const [propertyAddress, setPropertyAddress] = useState("");
  const [pricingKind, setPricingKind] = useState<"forfaitaire" | "estime">(
    "forfaitaire"
  );

  // Type de document : devis classique (items) ou contrat d'entreprise
  // (formulaire structuré dans contractData). Le contrat masque le
  // tableau d'items.
  const [kind, setKind] = useState<"quote" | "contract">("quote");
  const [contractData, setContractData] = useState<ContractData | null>(
    null
  );
  const [contractDirty, setContractDirty] = useState(false);
  const [users, setUsers] = useState<UserOption[]>([]);
  const [clientName, setClientName] = useState("");
  const [clientEmail, setClientEmail] = useState("");
  const [clientAddress, setClientAddress] = useState("");

  // Signature de l'entrepreneur (Horizon) — on envoie au chargé de
  // projet un courriel avec un lien public pour signer le contrat
  // AVANT l'envoi au client.
  const [sendingForSignature, setSendingForSignature] = useState(false);
  const [contractorSigNotice, setContractorSigNotice] = useState<
    string | null
  >(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const [sRes, iRes, uRes] = await Promise.all([
          authedFetch(`/api/v1/soumissions/${id}`),
          authedFetch(`/api/v1/soumissions/${id}/items`),
          authedFetch(`/api/v1/users`)
        ]);
        if (!sRes.ok) throw new Error(`http_${sRes.status}`);
        const sData = (await sRes.json()) as Soumission;
        const iData = iRes.ok ? ((await iRes.json()) as Item[]) : [];
        if (cancelled) return;
        setS(sData);
        setItems(iData);
        setTitle(sData.title);
        setDescription(sData.description || "");
        setValidUntil(isoToDateInput(sData.valid_until));
        setNotes(sData.notes || "");
        setClientNote(sData.client_note || "");
        setPropertyAddress(sData.property_address || "");
        setPricingKind(
          sData.pricing_kind === "estime" ? "estime" : "forfaitaire"
        );
        const docKind = sData.kind === "contract" ? "contract" : "quote";
        setKind(docKind);
        setSendSubject(
          `${docKind === "contract" ? "Contrat" : "Soumission"} ` +
            `${sData.reference} — ${sData.title}`
        );
        // Liste des utilisateurs → menu « responsable du projet ».
        if (uRes.ok) {
          const uData = (await uRes.json()) as Array<{
            id: number;
            display_name?: string | null;
            first_name?: string | null;
            last_name?: string | null;
            email: string;
            is_active?: boolean;
          }>;
          if (!cancelled)
            setUsers(
              uData
                .filter((u) => u.is_active !== false)
                .map((u) => ({
                  id: u.id,
                  // Nom réel en priorité (prénom + nom) ; on ne
                  // retombe sur display_name / courriel que si le
                  // profil n'a pas de nom complet renseigné.
                  label:
                    [u.first_name, u.last_name]
                      .filter(Boolean)
                      .join(" ") ||
                    u.display_name ||
                    u.email
                }))
            );
        }
        // Client / prospect lié — nom, courriel, adresse, et message
        // d'origine (pour pré-remplir la description d'un contrat).
        let cName = "";
        let cEmail = "";
        let cAddress = "";
        let cMessage = "";
        let contactIdForMessage: number | null =
          sData.contact_request_id;
        if (sData.client_id) {
          try {
            const cl = await authedFetch(
              `/api/v1/clients/${sData.client_id}`
            );
            if (cl.ok) {
              const c = (await cl.json()) as {
                name?: string;
                email?: string;
                address?: string;
                contact_request_id?: number | null;
              };
              cName = c.name || "";
              cEmail = c.email || "";
              cAddress = c.address || "";
              if (!contactIdForMessage && c.contact_request_id)
                contactIdForMessage = c.contact_request_id;
            }
          } catch {
            /* ignore */
          }
        }
        if (contactIdForMessage) {
          const cr = await authedFetch(
            `/api/v1/contact/${contactIdForMessage}`
          );
          if (cr.ok) {
            const crData = (await cr.json()) as {
              name?: string;
              email?: string;
              address?: string;
              message?: string;
            };
            if (!cName) cName = crData.name || cName;
            if (!cEmail) cEmail = crData.email || cEmail;
            if (!cAddress) cAddress = crData.address || cAddress;
            cMessage = crData.message || "";
          }
        }
        if (cancelled) return;
        setClientName(cName);
        setClientEmail(cEmail);
        setClientAddress(cAddress);
        if (cEmail) setSendTo(cEmail);
        // Données du contrat : parse contract_data si présent, sinon
        // défaut pré-rempli — chantier = adresse du client, et
        // description = message d'origine du prospect/client.
        const prefillAddr = sData.property_address || cAddress;
        let cd: ContractData;
        if (sData.contract_data) {
          try {
            cd = normalizeContractData(
              JSON.parse(sData.contract_data),
              { address: prefillAddr }
            );
          } catch {
            cd = defaultContractData({ address: prefillAddr });
          }
        } else {
          cd = defaultContractData({ address: prefillAddr });
          if (cMessage.trim()) cd.description = cMessage.trim();
        }
        setContractData(cd);
        setContractDirty(false);
      } catch {
        if (!cancelled) setError("Soumission introuvable.");
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
  // Per-item tax calculation: sum TPS only on items whose tps_applicable
  // is true, same for TVQ. Lets us mix taxable services with non-taxable
  // frais or rabais line items.
  const tps = useMemo(
    () =>
      +items
        .filter((it) => it.tps_applicable)
        .reduce((sum, it) => sum + Number(it.total || 0) * TPS_RATE, 0)
        .toFixed(2),
    [items]
  );
  const tvq = useMemo(
    () =>
      +items
        .filter((it) => it.tvq_applicable)
        .reduce((sum, it) => sum + Number(it.total || 0) * TVQ_RATE, 0)
        .toFixed(2),
    [items]
  );
  const total = +(subtotal + tps + tvq).toFixed(2);

  // Internal (non-client-facing) metrics: projected cost from each
  // line's cost_per_unit × quantity, and the resulting margin vs the
  // client-facing subtotal. These are rendered in the staff UI only —
  // the public soumission JSON + PDF never include cost_per_unit.
  const projectedCost = useMemo(
    () =>
      +items
        .reduce(
          (s, it) => s + Number(it.cost_per_unit || 0) * Number(it.quantity || 0),
          0
        )
        .toFixed(2),
    [items]
  );
  const projectedProfit = +(subtotal - projectedCost).toFixed(2);
  const projectedMarginPct =
    subtotal > 0 ? +((projectedProfit / subtotal) * 100).toFixed(1) : 0;

  const metaDirty =
    s !== null &&
    (title !== s.title ||
      description !== (s.description || "") ||
      isoToDateInput(s.valid_until) !== validUntil ||
      (s.notes || "") !== notes ||
      (s.client_note || "") !== clientNote ||
      kind !== (s.kind || "quote") ||
      contractDirty);

  async function syncToQbo(options?: { silent?: boolean }) {
    setQboBusy(true);
    if (!options?.silent) setQboNotice(null);
    try {
      const res = await authedFetch(`/api/v1/soumissions/${id}/qbo/sync`, {
        method: "POST"
      });
      if (!res.ok) {
        const err = await res.text();
        throw new Error(err || `http_${res.status}`);
      }
      const r = (await res.json()) as {
        qbo_estimate_id: string;
        qbo_doc_number: string;
      };
      setS((cur) =>
        cur
          ? {
              ...cur,
              qbo_estimate_id: r.qbo_estimate_id || null,
              qbo_doc_number: r.qbo_doc_number || null
            }
          : cur
      );
      if (!options?.silent)
        setQboNotice(`Synchronisé avec QuickBooks (Estimate ${r.qbo_estimate_id}).`);
    } catch (err) {
      setQboNotice(
        `Erreur de synchronisation QuickBooks : ${(err as Error).message.slice(0, 240)}`
      );
    } finally {
      setQboBusy(false);
    }
  }

  async function changeKind(newKind: "quote" | "contract") {
    if (!s || newKind === kind) return;
    setKind(newKind);
    // Persiste tout de suite le type : la prévisualisation PDF lit la
    // base, donc sans ça elle générerait le mauvais document (devis
    // vs contrat). Le reste du formulaire se sauvegarde normalement.
    try {
      const res = await authedFetch(`/api/v1/soumissions/${id}`, {
        method: "PATCH",
        body: JSON.stringify({ kind: newKind })
      });
      if (res.ok) {
        const updated = (await res.json()) as Soumission;
        setS(updated);
      }
    } catch {
      /* sera persisté au prochain « Sauvegarder » */
    }
  }

  function openSendModal() {
    if (!s) return;
    // Un contrat doit être signé par l'entrepreneur (chargé de
    // projet) AVANT l'envoi au client.
    if (kind === "contract" && !s.contractor_signed_name) {
      setSendNotice(
        "Le chargé de projet doit signer le contrat pour Horizon " +
          "avant de l'envoyer au client (section « Signature de " +
          "l'entrepreneur » ci-dessous)."
      );
      return;
    }
    if (!sendSubject)
      setSendSubject(
        `${kind === "contract" ? "Contrat" : "Soumission"} ` +
          `${s.reference} — ${s.title}`
      );
    setSendNotice(null);
    setSendOpen(true);
  }

  async function sendForContractorSignature() {
    if (!s) return;
    setSendingForSignature(true);
    setContractorSigNotice(null);
    try {
      const res = await authedFetch(
        `/api/v1/soumissions/${id}/send-for-contractor-signature`,
        { method: "POST" }
      );
      if (!res.ok) {
        let detail = `http_${res.status}`;
        try {
          const body = (await res.json()) as { detail?: string };
          if (body.detail) detail = body.detail;
        } catch {
          /* not json */
        }
        throw new Error(detail);
      }
      const updated = (await res.json()) as Soumission;
      setS(updated);
      setContractorSigNotice(
        "Courriel envoyé au chargé de projet — il peut signer le " +
          "contrat via le lien reçu."
      );
    } catch (err) {
      setContractorSigNotice(
        `Envoi échoué : ${(err as Error).message}`
      );
    } finally {
      setSendingForSignature(false);
    }
  }

  async function previewPdf() {
    try {
      // Fetch the PDF with the auth header then hand it off to the
      // browser as a blob URL. window.open() alone can't attach the
      // Bearer token, which is why a direct link returned 401.
      const res = await authedFetch(`/api/v1/soumissions/${id}/pdf`);
      if (!res.ok) throw new Error(`http_${res.status}`);
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      window.open(url, "_blank", "noopener,noreferrer");
      // Revoke later so the new tab has time to load it.
      setTimeout(() => URL.revokeObjectURL(url), 60_000);
    } catch (err) {
      setSendNotice(
        `Prévisualisation PDF échouée : ${(err as Error).message.slice(0, 240)}`
      );
    }
  }

  // convertToClient was removed — the conversion is now automatic
  // when the soumission status flips to "accepted" (either via the
  // staff /status endpoint or the public /accept endpoint). See
  // backend/app/api/v1/endpoints/soumission_status.py.

  async function convertToProject() {
    if (!s) return;
    try {
      const res = await authedFetch(
        `/api/v1/soumissions/${id}/convert-to-project`,
        { method: "POST" }
      );
      if (!res.ok) {
        const text = await res.text();
        throw new Error(text.slice(0, 240) || `http_${res.status}`);
      }
      const project = (await res.json()) as { id: number };
      router.replace(`/app/projets/${project.id}`);
    } catch (err) {
      setSendNotice(
        `Conversion en projet échouée : ${(err as Error).message}`
      );
    }
  }

  async function sendToClient() {
    if (!s) return;
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
      const res = await authedFetch(`/api/v1/soumissions/${id}/send`, {
        method: "POST",
        body: JSON.stringify({
          to,
          cc: cc.length > 0 ? cc : null,
          subject: sendSubject || null,
          message: sendMessage || null
        })
      });
      if (!res.ok) {
        const err = await res.text();
        throw new Error(err || `http_${res.status}`);
      }
      const updated = (await res.json()) as Soumission;
      setS(updated);
      setSendOpen(false);
      setSendNotice(`Soumission envoyée à ${to.join(", ")}.`);
    } catch (err) {
      setSendNotice(
        `Erreur d'envoi : ${(err as Error).message.slice(0, 240)}`
      );
    } finally {
      setSendBusy(false);
    }
  }

  async function saveMeta() {
    if (!s) return;
    setSaving(true);
    setError(null);
    try {
      const payload = {
        title: title.trim(),
        description: description.trim() || null,
        subtotal,
        tps,
        tvq,
        total,
        valid_until: validUntil ? new Date(validUntil).toISOString() : null,
        notes: notes.trim() || null,
        client_note: clientNote.trim() || null,
        property_address: propertyAddress.trim() || null,
        pricing_kind: pricingKind,
        kind,
        contract_data: contractData ? JSON.stringify(contractData) : null
      };
      const res = await authedFetch(`/api/v1/soumissions/${id}`, {
        method: "PATCH",
        body: JSON.stringify(payload)
      });
      if (!res.ok) throw new Error();
      const updated = (await res.json()) as Soumission;
      setS(updated);
      setContractDirty(false);
    } catch {
      setError("Sauvegarde échouée.");
    } finally {
      setSaving(false);
    }
  }

  async function updateStatus(newStatus: string) {
    if (!s) return;
    const prev = s;
    setS({ ...s, status: newStatus });
    try {
      // Hit the dedicated status endpoint so the backend also
      // propagates the change to the linked prospect CRM card
      // (draft -> sent -> prospect "quoted", accepted -> "won", etc.)
      const res = await authedFetch(
        `/api/v1/soumissions/${id}/status`,
        {
          method: "PATCH",
          body: JSON.stringify({ status: newStatus })
        }
      );
      if (!res.ok) throw new Error();
      const updated = (await res.json()) as Soumission;
      setS(updated);

      // Auto-sync to QBO when transitioning to "sent"
      if (newStatus === "sent" && prev.status !== "sent") {
        void syncToQbo({ silent: true });
      }
    } catch {
      setS(prev);
      setError("Changement de statut échoué.");
    }
  }

  async function deleteSoumission() {
    if (!s) return;
    if (!(await confirm(`Supprimer la soumission ${s.reference} ?`))) return;
    setDeleting(true);
    try {
      const res = await authedFetch(`/api/v1/soumissions/${id}`, {
        method: "DELETE"
      });
      if (!res.ok) throw new Error();
      router.replace("/app/soumissions");
    } catch {
      setDeleting(false);
      setError("Suppression échouée.");
    }
  }

  async function addItem(kind: "service" | "frais" | "rabais" = "service") {
    setItemBusy("new");
    try {
      const defaults: Record<string, Record<string, unknown>> = {
        service: {
          description: "Nouveau service",
          unit: "unité",
          quantity: 1,
          unit_price: 0,
          tps_applicable: true,
          tvq_applicable: true,
          kind: "service"
        },
        frais: {
          description: "Frais",
          unit: null,
          quantity: 1,
          unit_price: 0,
          tps_applicable: false,
          tvq_applicable: false,
          kind: "frais"
        },
        rabais: {
          description: "Rabais",
          unit: null,
          quantity: 1,
          unit_price: -0,
          tps_applicable: true,
          tvq_applicable: true,
          kind: "rabais"
        }
      };
      const res = await authedFetch(`/api/v1/soumissions/${id}/items`, {
        method: "POST",
        body: JSON.stringify({
          position: items.length,
          ...defaults[kind]
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
        `/api/v1/soumissions/${id}/items/${item_id}`,
        {
          method: "PATCH",
          body: JSON.stringify(patch)
        }
      );
      if (!res.ok) throw new Error();
      const updated = (await res.json()) as Item;
      setItems((xs) => xs.map((x) => (x.id === item_id ? updated : x)));
    } catch {
      setError("Mise à jour de l'item échouée.");
    } finally {
      setItemBusy(null);
    }
  }

  async function deleteItem(item_id: number) {
    const prev = items;
    setItems((xs) => xs.filter((x) => x.id !== item_id));
    try {
      const res = await authedFetch(
        `/api/v1/soumissions/${id}/items/${item_id}`,
        { method: "DELETE" }
      );
      if (!res.ok) throw new Error();
    } catch {
      setItems(prev);
      setError("Suppression de l'item échouée.");
    }
  }

  const isQboSynced = Boolean(s?.qbo_estimate_id);

  return (
    <>
      <AppTopbar
        breadcrumbs={[{ label: "Construction", href: "/app" }, { label: "Soumissions" }]}
        onOpenSidebar={onOpenSidebar}
      />

      <div className="p-4 lg:p-6">
        <Link
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          href={"/app/soumissions" as any}
          className="inline-flex items-center text-sm text-white/70 hover:text-accent-500"
        >
          <ArrowLeft className="mr-1 h-4 w-4" /> Retour aux soumissions
        </Link>

        {loading ? (
          <div className="flex min-h-[40vh] items-center justify-center">
            <Loader2 className="h-6 w-6 animate-spin text-accent-500" />
          </div>
        ) : error && !s ? (
          <p className="mt-6 rounded-lg border border-rose-500/40 bg-rose-500/10 px-4 py-2 text-sm text-rose-300">
            {error}
          </p>
        ) : s ? (
          <>
            <header className="mt-6 flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
              <div>
                <p className="text-xs font-semibold uppercase tracking-wider text-accent-500">
                  {s.reference}
                </p>
                <h1 className="mt-1 text-2xl font-bold text-white">{s.title}</h1>
                <p className="mt-1 text-xs text-white/50">
                  Créée le{" "}
                  {new Date(s.created_at).toLocaleDateString("fr-CA", {
                    day: "numeric",
                    month: "long",
                    year: "numeric"
                  })}
                  {s.sent_at
                    ? ` · Envoyée le ${new Date(s.sent_at).toLocaleDateString("fr-CA")}`
                    : ""}
                  {s.accepted_at
                    ? ` · Acceptée le ${new Date(s.accepted_at).toLocaleDateString("fr-CA")}`
                    : ""}
                </p>
                {isQboSynced ? (
                  <p className="mt-2 inline-flex items-center gap-1.5 rounded-md bg-emerald-500/15 px-2 py-0.5 text-[11px] font-semibold text-emerald-300">
                    <Check className="h-3 w-3" /> QuickBooks Estimate #
                    {s.qbo_doc_number || s.qbo_estimate_id}
                  </p>
                ) : null}
              </div>
              <div className="flex flex-wrap items-end gap-3">
                <span
                  className={`rounded-md px-3 py-1.5 text-xs font-semibold ${
                    STATUS_CLASS[s.status] || "bg-white/10 text-white"
                  }`}
                >
                  {STATUS_LABELS[s.status] || s.status}
                </span>
                <select
                  value={s.status}
                  onChange={(e) => updateStatus(e.target.value)}
                  className="input w-48"
                >
                  {Object.entries(STATUS_LABELS).map(([k, v]) => (
                    <option key={k} value={k}>{v}</option>
                  ))}
                </select>
                <button
                  type="button"
                  onClick={deleteSoumission}
                  disabled={deleting}
                  className="inline-flex items-center gap-2 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2.5 text-sm font-medium text-rose-300 hover:bg-rose-500/20"
                >
                  {deleting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Trash2 className="h-4 w-4" />}
                  Supprimer
                </button>
              </div>
            </header>

            {/* Suivi côté client : ouverture du lien + signature.
                S'affiche dès que la soumission a été envoyée. */}
            {s.sent_at ? (
              <div className="mt-4 flex flex-wrap items-center gap-2 text-xs">
                {s.client_opened_at ? (
                  <span
                    className="inline-flex items-center gap-1.5 rounded-md border border-blue-500/40 bg-blue-500/10 px-2.5 py-1 font-semibold text-blue-200"
                    title={
                      s.client_last_opened_at &&
                      s.client_last_opened_at !== s.client_opened_at
                        ? `Dernière visite : ${fmtDateTime(s.client_last_opened_at)}`
                        : undefined
                    }
                  >
                    <Eye className="h-3 w-3" />
                    Ouverte le {fmtDateTime(s.client_opened_at)}
                    {s.client_open_count && s.client_open_count > 1
                      ? ` · ${s.client_open_count} visites`
                      : ""}
                  </span>
                ) : (
                  <span className="inline-flex items-center gap-1.5 rounded-md border border-white/15 bg-white/5 px-2.5 py-1 font-semibold text-white/60">
                    <EyeOff className="h-3 w-3" />
                    Pas encore ouverte par le client
                  </span>
                )}
                {s.signed_name && s.accepted_at ? (
                  <span className="inline-flex items-center gap-1.5 rounded-md border border-emerald-500/40 bg-emerald-500/10 px-2.5 py-1 font-semibold text-emerald-200">
                    <Check className="h-3 w-3" />
                    Signée par {s.signed_name} le{" "}
                    {fmtDateTime(s.accepted_at)}
                  </span>
                ) : (
                  <span className="inline-flex items-center gap-1.5 rounded-md border border-white/15 bg-white/5 px-2.5 py-1 font-semibold text-white/60">
                    Non signée par le client
                  </span>
                )}
              </div>
            ) : null}

            {error ? (
              <p className="mt-4 rounded-lg border border-rose-500/40 bg-rose-500/10 px-4 py-2 text-sm text-rose-300">
                {error}
              </p>
            ) : null}
            {qboNotice ? (
              <p
                className={`mt-4 rounded-lg border px-4 py-2 text-sm ${
                  qboNotice.startsWith("Synchronisé")
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
                  sendNotice.startsWith("Soumission envoyée")
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
                onClick={openSendModal}
                className="flex items-start gap-3 rounded-xl border border-brand-800 bg-brand-900 p-4 text-left transition hover:border-accent-500"
              >
                <Mail className="mt-0.5 h-5 w-5 flex-shrink-0 text-accent-500" />
                <div>
                  <p className="text-sm font-semibold text-white">
                    {s.sent_at ? "Renvoyer au client" : "Envoyer au client"}
                  </p>
                  <p className="mt-0.5 text-xs text-white/60">
                    {s.sent_at
                      ? `Envoyée le ${new Date(s.sent_at).toLocaleDateString("fr-CA")}`
                      : "PDF + courriel via Microsoft Graph."}
                  </p>
                </div>
              </button>
              <button
                type="button"
                onClick={() => syncToQbo()}
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
                    {isQboSynced ? "Resynchroniser QuickBooks" : "Envoyer vers QuickBooks"}
                  </p>
                  <p className="mt-0.5 text-xs text-white/60">
                    {isQboSynced
                      ? `Estimate #${s.qbo_doc_number || s.qbo_estimate_id} — mise à jour`
                      : "Créer l'Estimate dans QBO"}
                  </p>
                </div>
              </button>
            </div>

            {s.status === "accepted" ? (
              <div className="mt-3 flex flex-wrap gap-2">
                {/* Le client est créé automatiquement quand la
                    soumission passe en "accepted" — pas besoin d'un
                    bouton manuel. Voir backend/soumission_status.py. */}
                <button
                  type="button"
                  onClick={convertToProject}
                  className="inline-flex items-center gap-2 rounded-lg border border-accent-500/40 bg-accent-500/10 px-4 py-2.5 text-sm font-medium text-accent-200 hover:bg-accent-500/20"
                >
                  <Briefcase className="h-4 w-4" />
                  Convertir en projet
                </button>
                <p className="w-full text-xs text-white/50">
                  Crée le projet et génère automatiquement une facture
                  d&apos;acompte de 25 % (TPS + TVQ incluses) en
                  <span className="text-accent-300"> brouillon</span> dans la
                  facturation.
                </p>
              </div>
            ) : null}

            {/* Type de soumission — devis (tableau d'items) ou
                contrat d'entreprise (formulaire structuré). */}
            <div className="mt-8 rounded-xl border border-brand-800 bg-brand-900 px-5 py-4">
              <p className="text-sm font-semibold uppercase tracking-wider text-accent-500">
                Type de soumission
              </p>
              <div className="mt-2 inline-flex rounded-lg border border-brand-700 bg-brand-950/40 p-0.5">
                <button
                  type="button"
                  onClick={() => void changeKind("quote")}
                  className={`rounded-md px-4 py-1.5 text-xs font-semibold transition ${
                    kind === "quote"
                      ? "bg-accent-500 text-brand-950 shadow"
                      : "text-white/70 hover:text-white"
                  }`}
                >
                  Devis
                </button>
                <button
                  type="button"
                  onClick={() => void changeKind("contract")}
                  className={`rounded-md px-4 py-1.5 text-xs font-semibold transition ${
                    kind === "contract"
                      ? "bg-accent-500 text-brand-950 shadow"
                      : "text-white/70 hover:text-white"
                  }`}
                >
                  Contrat
                </button>
              </div>
              <p className="mt-2 text-xs text-white/50">
                {kind === "quote"
                  ? "Devis classique : tableau d'items, prix et taxes."
                  : "Contrat d'entreprise à prix coûtant majoré — formulaire structuré (le tableau d'items est masqué)."}
              </p>
            </div>

            {kind === "quote" ? (
            <section className="mt-6 rounded-xl border border-brand-800 bg-brand-900">
              <div className="flex flex-wrap items-center justify-between gap-2 border-b border-brand-800 px-5 py-4">
                <h2 className="text-sm font-semibold uppercase tracking-wider text-accent-500">
                  Items de la soumission
                </h2>
                <div className="flex flex-wrap items-center gap-2">
                  <button
                    type="button"
                    onClick={() => setTemplatePickerOpen(true)}
                    className="inline-flex items-center rounded-lg border border-blue-500/40 bg-blue-500/10 px-3 py-1.5 text-xs font-semibold text-blue-200 hover:bg-blue-500/20"
                  >
                    <Briefcase className="mr-1.5 h-3.5 w-3.5" />
                    Insérer un service du catalogue
                  </button>
                  <button
                    type="button"
                    onClick={() => addItem("service")}
                    disabled={itemBusy === "new"}
                    className="btn-accent text-xs"
                  >
                    {itemBusy === "new" ? (
                      <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                    ) : (
                      <Plus className="mr-1.5 h-3.5 w-3.5" />
                    )}
                    Ajouter item
                  </button>
                  <button
                    type="button"
                    onClick={() => addItem("frais")}
                    disabled={itemBusy === "new"}
                    className="btn-secondary text-xs"
                  >
                    <Plus className="mr-1.5 h-3.5 w-3.5" /> Frais
                  </button>
                  <button
                    type="button"
                    onClick={() => addItem("rabais")}
                    disabled={itemBusy === "new"}
                    className="inline-flex items-center rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-1.5 text-xs font-semibold text-rose-200 hover:bg-rose-500/20 disabled:opacity-60"
                  >
                    <Plus className="mr-1.5 h-3.5 w-3.5" /> Rabais
                  </button>
                </div>
              </div>

              {items.length === 0 ? (
                <p className="px-5 py-10 text-center text-sm text-white/50">
                  Aucun item. Cliquez « Ajouter un item » pour commencer.
                </p>
              ) : (
                <div className="overflow-x-auto">
                  {/* Suggestions d'unités — le champ reste éditable pour
                      garder les valeurs custom existantes (ex. "seau 20L"). */}
                  <datalist id="soumission-units">
                    <option value="unité" />
                    <option value="pièce" />
                    <option value="forfait" />
                    <option value="ft²" />
                    <option value="pi²" />
                    <option value="m²" />
                    <option value="ft" />
                    <option value="pi" />
                    <option value="m" />
                    <option value="verge²" />
                    <option value="verge³" />
                    <option value="heure" />
                    <option value="jour" />
                    <option value="semaine" />
                    <option value="lot" />
                    <option value="kg" />
                    <option value="lb" />
                    <option value="L" />
                    <option value="gal" />
                  </datalist>
                  <table className="w-full text-sm">
                    <thead className="border-b border-brand-800 text-xs uppercase tracking-wider text-white/50">
                      <tr>
                        <th className="px-5 py-3 text-left font-semibold">Description</th>
                        <th className="px-3 py-3 text-right font-semibold">Qté</th>
                        <th className="px-3 py-3 text-left font-semibold">Unité</th>
                        <th
                          className="px-3 py-3 text-right font-bold text-amber-500"
                          title="Coût interne — invisible par le client"
                        >
                          Coût $/u 🔒
                        </th>
                        <th className="px-3 py-3 text-right font-semibold">Prix unit.</th>
                        <th className="px-3 py-3 text-center font-semibold" title="TPS applicable">TPS</th>
                        <th className="px-3 py-3 text-center font-semibold" title="TVQ applicable">TVQ</th>
                        <th className="px-3 py-3 text-right font-semibold">Total</th>
                        <th className="px-3 py-3"></th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-brand-800">
                      {items.map((it) => (
                        <ItemRow
                          key={it.id}
                          item={it}
                          busy={itemBusy === it.id}
                          onPatch={(patch) => patchItem(it.id, patch)}
                          onDelete={() => deleteItem(it.id)}
                        />
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </section>
            ) : contractData ? (
              <>
                <ContractForm
                  value={contractData}
                  onChange={(v) => {
                    setContractData(v);
                    setContractDirty(true);
                  }}
                  users={users}
                  clientName={clientName}
                  clientEmail={clientEmail}
                  clientAddress={clientAddress}
                />
                <div className="mt-4">
                  <button
                    type="button"
                    onClick={saveMeta}
                    disabled={saving || !metaDirty}
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
                        {metaDirty
                          ? "Sauvegarder le contrat"
                          : "Contrat à jour"}
                      </>
                    )}
                  </button>
                </div>

                {/* Signature de l'entrepreneur — on envoie au chargé
                    de projet un courriel avec un lien public pour
                    signer le contrat AVANT l'envoi au client. */}
                <section className="mt-6 rounded-xl border border-brand-800 bg-brand-900 p-5">
                  <h2 className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wider text-accent-500">
                    <PenTool className="h-4 w-4" />
                    Signature de l&apos;entrepreneur (Horizon)
                  </h2>
                  {s.contractor_signed_name ? (
                    <div className="mt-3 rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-4 py-3 text-sm text-emerald-200">
                      <Check className="mr-1.5 inline h-4 w-4" />
                      Signé par{" "}
                      <strong>{s.contractor_signed_name}</strong> pour
                      Horizon
                      {s.contractor_signed_at
                        ? ` le ${new Date(
                            s.contractor_signed_at
                          ).toLocaleDateString("fr-CA")}`
                        : ""}
                      . Le contrat a été envoyé automatiquement au
                      client pour signature.
                    </div>
                  ) : (
                    <div className="mt-3 space-y-3">
                      <p className="text-xs text-white/60">
                        Le chargé de projet signe le contrat pour la
                        compagnie. Cliquez ci-dessous pour lui envoyer
                        par courriel un lien de signature. Une fois
                        signé, le contrat est envoyé automatiquement
                        au client.
                      </p>
                      {s.contractor_signature_token &&
                      s.contractor_opened_at ? (
                        <p
                          className="inline-flex items-center gap-1.5 rounded-md border border-blue-500/40 bg-blue-500/10 px-2.5 py-1 text-[11px] font-semibold text-blue-200"
                          title={
                            s.contractor_last_opened_at &&
                            s.contractor_last_opened_at !==
                              s.contractor_opened_at
                              ? `Dernière visite : ${fmtDateTime(s.contractor_last_opened_at)}`
                              : undefined
                          }
                        >
                          <Eye className="h-3 w-3" />
                          Lien ouvert le{" "}
                          {fmtDateTime(s.contractor_opened_at)}
                          {s.contractor_open_count &&
                          s.contractor_open_count > 1
                            ? ` · ${s.contractor_open_count} visites`
                            : ""}
                        </p>
                      ) : null}
                      <button
                        type="button"
                        onClick={sendForContractorSignature}
                        disabled={sendingForSignature}
                        className="btn-accent text-sm disabled:opacity-50"
                      >
                        {sendingForSignature ? (
                          <>
                            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                            Envoi…
                          </>
                        ) : (
                          <>
                            <Mail className="mr-2 h-4 w-4" />
                            {s.contractor_signature_token
                              ? "Renvoyer le lien au chargé de projet"
                              : "Envoyer au chargé de projet pour signature"}
                          </>
                        )}
                      </button>
                      {s.contractor_signature_token ? (
                        <p className="text-[11px] text-white/40">
                          Un lien de signature a déjà été généré et
                          envoyé. En attente de la signature du chargé
                          de projet.
                        </p>
                      ) : null}
                    </div>
                  )}
                  {contractorSigNotice ? (
                    <p
                      className={`mt-3 rounded-lg border px-3 py-2 text-xs ${
                        contractorSigNotice.startsWith("Courriel envoyé")
                          ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-200"
                          : "border-amber-500/40 bg-amber-500/10 text-amber-200"
                      }`}
                    >
                      {contractorSigNotice}
                    </p>
                  ) : null}
                </section>
              </>
            ) : null}

            <div className="mt-8">
              <FollowUpTimeline subjectType="soumission" subjectId={s.id} />
            </div>

            <div className="mt-8 grid gap-6 lg:grid-cols-3">
              <div className="lg:col-span-2 space-y-5 rounded-xl border border-brand-800 bg-brand-900 p-5">
                <h2 className="text-sm font-semibold uppercase tracking-wider text-accent-500">
                  Informations
                </h2>

                <div>
                  <label htmlFor="title" className="label">Titre</label>
                  <input
                    id="title"
                    type="text"
                    value={title}
                    onChange={(e) => setTitle(e.target.value)}
                    className="input"
                  />
                </div>

                {/* Description : masquée pour un contrat — il a sa
                    propre « Description des travaux » (section 3.2). */}
                {kind === "quote" ? (
                  <div>
                    <label htmlFor="description" className="label">
                      Description
                    </label>
                    <textarea
                      id="description"
                      rows={6}
                      value={description}
                      onChange={(e) => setDescription(e.target.value)}
                      className="input"
                    />
                  </div>
                ) : null}

                <div>
                  <label htmlFor="property_address" className="label">
                    Adresse du chantier
                  </label>
                  <AddressInput
                    id="property_address"
                    value={propertyAddress}
                    onChange={setPropertyAddress}
                    placeholder="Commence à taper — on propose les adresses canadiennes"
                  />
                  <p className="mt-1 text-xs text-white/50">
                    Affichée sur le PDF et la page publique. Satellite +
                    Street View ci-dessous.
                  </p>
                  {propertyAddress.trim() ? (
                    <StreetViewEmbed address={propertyAddress.trim()} />
                  ) : null}
                </div>

                <div>
                  <label htmlFor="valid_until" className="label">Valide jusqu&apos;au</label>
                  <input
                    id="valid_until"
                    type="date"
                    value={validUntil}
                    onChange={(e) => setValidUntil(e.target.value)}
                    className="input sm:w-60"
                  />
                </div>

                {/* Type de soumission : forfaitaire (prix fixe) vs
                    estimé (estimation à confirmer). En mode estimé,
                    le PDF ET la page publique affichent une clause
                    qui explique au client que les coûts peuvent
                    varier. Sans objet pour un contrat (prix coûtant
                    majoré). */}
                {kind === "quote" ? (
                  <div>
                    <label className="label">Mode de prix</label>
                    <div className="inline-flex rounded-lg border border-brand-700 bg-brand-950/40 p-0.5">
                      <button
                        type="button"
                        onClick={() => setPricingKind("forfaitaire")}
                        className={`rounded-md px-3 py-1.5 text-xs font-semibold transition ${
                          pricingKind === "forfaitaire"
                            ? "bg-accent-500 text-brand-950 shadow"
                            : "text-white/70 hover:text-white"
                        }`}
                      >
                        Forfaitaire
                      </button>
                      <button
                        type="button"
                        onClick={() => setPricingKind("estime")}
                        className={`rounded-md px-3 py-1.5 text-xs font-semibold transition ${
                          pricingKind === "estime"
                            ? "bg-amber-500 text-brand-950 shadow"
                            : "text-white/70 hover:text-white"
                        }`}
                      >
                        Estimé
                      </button>
                    </div>
                    <p className="mt-1 text-xs text-white/50">
                      {pricingKind === "forfaitaire"
                        ? "Prix fixe garanti — le client paye le total même si nos coûts dépassent."
                        : "Estimé — clause client-facing ajoutée au PDF et à la page publique : « les coûts peuvent varier en cours de projet, on tient le client au courant »."}
                    </p>
                  </div>
                ) : null}

                {/* Note sur la soumission : masquée pour un contrat —
                    les modalités sont déjà dans le contrat lui-même. */}
                {kind === "quote" ? (
                  <div>
                    <label htmlFor="client_note" className="label">
                      Note sur la soumission{" "}
                      <span className="text-[10px] font-normal text-accent-500">
                        (visible par le client)
                      </span>
                    </label>
                    <textarea
                      id="client_note"
                      rows={3}
                      value={clientNote}
                      onChange={(e) => setClientNote(e.target.value)}
                      placeholder="Ex. Paiement 50 % à la signature, solde à la fin des travaux. Matériaux inclus."
                      className="input"
                    />
                    <p className="mt-1 text-xs text-white/50">
                      Apparaît sur le PDF + la page publique de signature.
                    </p>
                  </div>
                ) : null}

                <div>
                  <label htmlFor="notes" className="label">
                    Notes internes{" "}
                    <span className="text-[10px] font-normal text-rose-300">
                      (non visibles par le client)
                    </span>
                  </label>
                  <textarea
                    id="notes"
                    rows={4}
                    value={notes}
                    onChange={(e) => setNotes(e.target.value)}
                    placeholder="Notes privées — motifs de refus, marge visée, particularités du chantier…"
                    className="input"
                  />
                </div>

                <div>
                  <button
                    type="button"
                    onClick={saveMeta}
                    disabled={saving || !metaDirty}
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
                        {metaDirty ? "Sauvegarder" : "Aucun changement"}
                      </>
                    )}
                  </button>
                  {!metaDirty ? (
                    <p className="mt-2 text-xs text-white/40">
                      Les montants se sauvegardent avec les items ci-dessus.
                    </p>
                  ) : null}
                </div>
              </div>

              <aside className="space-y-5">
                {/* Montants + coût interne : dérivés du tableau
                    d'items → masqués pour un contrat (prix coûtant
                    majoré, pas de lignes de prix). */}
                {kind === "quote" ? (
                <>
                <div className="rounded-xl border border-brand-800 bg-brand-900 p-5">
                  <h2 className="text-sm font-semibold uppercase tracking-wider text-accent-500">
                    Montants
                  </h2>
                  <dl className="mt-4 space-y-2 text-sm">
                    <div className="flex items-center justify-between">
                      <dt className="text-white/60">Sous-total</dt>
                      <dd className="text-white">{fmtMoney(subtotal)}</dd>
                    </div>
                    <div className="flex items-center justify-between">
                      <dt className="text-white/60">TPS (5 %)</dt>
                      <dd className="text-white">{fmtMoney(tps)}</dd>
                    </div>
                    <div className="flex items-center justify-between">
                      <dt className="text-white/60">TVQ (9,975 %)</dt>
                      <dd className="text-white">{fmtMoney(tvq)}</dd>
                    </div>
                    <div className="flex items-center justify-between border-t border-brand-800 pt-3">
                      <dt className="font-semibold text-white">Total</dt>
                      <dd className="text-lg font-bold text-accent-500">{fmtMoney(total)}</dd>
                    </div>
                  </dl>
                  <p className="mt-3 text-xs text-white/40">
                    Les taxes sont calculées à partir de la somme des items.
                  </p>
                </div>

                {/* Internal margin panel — never sent to the client. */}
                <div className="rounded-xl border-2 border-amber-500/50 bg-amber-500/10 p-5">
                  <h2 className="flex items-center gap-2 text-sm font-bold uppercase tracking-wider text-amber-500">
                    🔒 Coût interne (non visible client)
                  </h2>
                  <dl className="mt-4 space-y-2 text-sm">
                    <div className="flex items-center justify-between">
                      <dt className="text-white/60">Coût projeté</dt>
                      <dd className="text-amber-200">
                        {fmtMoney(projectedCost)}
                      </dd>
                    </div>
                    <div className="flex items-center justify-between">
                      <dt className="text-white/60">Profit projeté</dt>
                      <dd
                        className={
                          projectedProfit >= 0
                            ? "text-emerald-300"
                            : "text-rose-300"
                        }
                      >
                        {fmtMoney(projectedProfit)}
                      </dd>
                    </div>
                    <div className="flex items-center justify-between border-t border-brand-800 pt-2">
                      <dt className="text-white/60">Marge brute</dt>
                      <dd
                        className={`text-lg font-bold ${
                          projectedMarginPct >= 30
                            ? "text-emerald-300"
                            : projectedMarginPct >= 0
                            ? "text-amber-300"
                            : "text-rose-300"
                        }`}
                      >
                        {projectedMarginPct.toFixed(1)} %
                      </dd>
                    </div>
                  </dl>
                  <p className="mt-3 text-[11px] text-white/50">
                    Ces chiffres ne figurent jamais sur le PDF ni sur la
                    page publique du client.
                  </p>
                </div>
                </>
                ) : null}

                <div className="rounded-xl border border-brand-800 bg-brand-900 p-5">
                  <h2 className="text-sm font-semibold uppercase tracking-wider text-accent-500">
                    Liens
                  </h2>
                  <dl className="mt-3 space-y-2 text-sm">
                    <div>
                      <dt className="text-white/50">Prospect lié</dt>
                      <dd className="mt-0.5 text-white">
                        {s.contact_request_id ? (
                          <Link
                            // eslint-disable-next-line @typescript-eslint/no-explicit-any
                            href={`/app/crm/${s.contact_request_id}` as any}
                            className="text-accent-500 hover:text-accent-600"
                          >
                            Fiche prospect #{s.contact_request_id}
                          </Link>
                        ) : (
                          <span className="text-white/50">—</span>
                        )}
                      </dd>
                    </div>
                    <div>
                      <dt className="text-white/50">Client lié</dt>
                      <dd className="mt-0.5 text-white">
                        {s.client_id ? `Client #${s.client_id}` : "—"}
                      </dd>
                    </div>
                    <div>
                      <dt className="text-white/50">QuickBooks</dt>
                      <dd className="mt-0.5 text-white">
                        {isQboSynced ? (
                          <span className="text-emerald-300">
                            Estimate #{s.qbo_doc_number || s.qbo_estimate_id}
                          </span>
                        ) : (
                          <span className="text-white/50">Non synchronisé</span>
                        )}
                      </dd>
                    </div>
                  </dl>
                </div>

                <div className="rounded-xl border border-dashed border-brand-800 bg-brand-900/40 p-5 text-xs text-white/50">
                  <p className="flex items-center gap-2 text-white/70">
                    <Send className="h-4 w-4 text-accent-500" />
                    <span className="font-semibold">À venir</span>
                  </p>
                  <ul className="mt-2 list-disc pl-5">
                    <li>Génération PDF + envoi courriel</li>
                    <li>Signature électronique (lien client)</li>
                  </ul>
                </div>
              </aside>
            </div>
          </>
        ) : null}
      </div>


      {templatePickerOpen ? (
        <ServiceTemplatePicker
          soumissionId={id}
          onClose={() => setTemplatePickerOpen(false)}
          onInserted={async () => {
            setTemplatePickerOpen(false);
            // Refresh the items list so the new lines show up.
            try {
              const res = await authedFetch(
                `/api/v1/soumissions/${id}/items`
              );
              if (res.ok) setItems((await res.json()) as Item[]);
            } catch {
              /* ignore */
            }
          }}
        />
      ) : null}

      {sendOpen && s ? (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4"
          onClick={() => (!sendBusy ? setSendOpen(false) : null)}
        >
          <div
            className="w-full max-w-xl rounded-2xl border border-brand-800 bg-brand-950 p-6 shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          >
            <h3 className="text-lg font-bold text-white">
              Envoyer la soumission
            </h3>
            <p className="mt-1 text-xs text-white/60">
              Référence {s.reference}. Un PDF sera attaché automatiquement et la
              soumission passera en statut « Envoyée ».
            </p>

            <div className="mt-5 space-y-4">
              <div>
                <label htmlFor="send_to" className="label">
                  Destinataire(s) <span className="text-rose-400">*</span>
                </label>
                <input
                  id="send_to"
                  type="text"
                  value={sendTo}
                  onChange={(e) => setSendTo(e.target.value)}
                  placeholder="client@exemple.com"
                  className="input"
                />
                <p className="mt-1 text-xs text-white/50">
                  Séparés par des virgules pour plusieurs adresses.
                </p>
              </div>
              <div>
                <label htmlFor="send_cc" className="label">CC (optionnel)</label>
                <input
                  id="send_cc"
                  type="text"
                  value={sendCc}
                  onChange={(e) => setSendCc(e.target.value)}
                  placeholder="info@immohorizon.com"
                  className="input"
                />
              </div>
              <div>
                <label htmlFor="send_subject" className="label">Objet</label>
                <input
                  id="send_subject"
                  type="text"
                  value={sendSubject}
                  onChange={(e) => setSendSubject(e.target.value)}
                  className="input"
                />
              </div>
              <div>
                <label htmlFor="send_message" className="label">
                  Message (optionnel)
                </label>
                <textarea
                  id="send_message"
                  rows={4}
                  value={sendMessage}
                  onChange={(e) => setSendMessage(e.target.value)}
                  placeholder="Bonjour, veuillez trouver ci-joint la soumission demandée…"
                  className="input"
                />
              </div>
            </div>

            {sendNotice ? (
              <p className="mt-3 rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs text-amber-200">
                {sendNotice}
              </p>
            ) : null}

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
  const [costPerUnit, setCostPerUnit] = useState(
    String(item.cost_per_unit ?? 0)
  );

  useEffect(() => {
    setDescription(item.description);
    setUnit(item.unit || "");
    setQuantity(String(item.quantity));
    setUnitPrice(String(item.unit_price));
    setCostPerUnit(String(item.cost_per_unit ?? 0));
  }, [
    item.id,
    item.description,
    item.unit,
    item.quantity,
    item.unit_price,
    item.cost_per_unit
  ]);

  const computedTotal = useMemo(
    () => +(Number(quantity || 0) * Number(unitPrice || 0)).toFixed(2),
    [quantity, unitPrice]
  );
  const computedMargin = useMemo(() => {
    const price = Number(unitPrice || 0);
    const cost = Number(costPerUnit || 0);
    if (price <= 0) return null;
    return +(((price - cost) / price) * 100).toFixed(0);
  }, [unitPrice, costPerUnit]);

  function commit(field: keyof Item) {
    if (field === "description" && description !== item.description) {
      onPatch({ description: description.trim() || item.description });
    } else if (field === "unit" && unit !== (item.unit || "")) {
      onPatch({ unit: unit.trim() || null });
    } else if (field === "quantity" && Number(quantity) !== Number(item.quantity)) {
      onPatch({ quantity: Number(quantity) || 0 });
    } else if (field === "unit_price" && Number(unitPrice) !== Number(item.unit_price)) {
      onPatch({ unit_price: Number(unitPrice) || 0 });
    } else if (
      field === "cost_per_unit" &&
      Number(costPerUnit) !== Number(item.cost_per_unit || 0)
    ) {
      onPatch({ cost_per_unit: Number(costPerUnit) || 0 });
    }
  }

  return (
    <tr className="align-top">
      <td className="px-5 py-3">
        <textarea
          rows={1}
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          onBlur={() => commit("description")}
          className="w-full resize-none rounded-md border border-transparent bg-transparent px-2 py-1.5 text-sm text-white focus:border-brand-700 focus:outline-none"
        />
      </td>
      <td className="px-3 py-3 w-28">
        <input
          type="number"
          step="0.001"
          min="0"
          value={quantity}
          onChange={(e) => setQuantity(e.target.value)}
          onBlur={() => commit("quantity")}
          className="w-full rounded-md border border-transparent bg-transparent px-2 py-1.5 text-right text-sm text-white focus:border-brand-700 focus:outline-none"
        />
      </td>
      <td className="px-3 py-3 w-28">
        <input
          type="text"
          list="soumission-units"
          value={unit}
          onChange={(e) => setUnit(e.target.value)}
          onBlur={() => commit("unit")}
          placeholder="—"
          className="w-full rounded-md border border-transparent bg-transparent px-2 py-1.5 text-sm text-white placeholder:text-white/30 focus:border-brand-700 focus:outline-none"
        />
      </td>
      <td className="px-3 py-3 w-28">
        {/* Cost per unit — internal only, never sent to client. */}
        <input
          type="number"
          step="0.01"
          value={costPerUnit}
          onChange={(e) => setCostPerUnit(e.target.value)}
          onBlur={() => commit("cost_per_unit")}
          className="w-full rounded-md border-2 border-amber-500/60 bg-amber-500/15 px-2 py-1.5 text-right text-sm font-semibold text-amber-500 placeholder:text-amber-500/40 focus:border-amber-500 focus:outline-none focus:ring-2 focus:ring-amber-500/30"
          aria-label="Coût par unité (interne)"
        />
      </td>
      <td className="px-3 py-3 w-32">
        <input
          type="number"
          step="0.01"
          value={unitPrice}
          onChange={(e) => setUnitPrice(e.target.value)}
          onBlur={() => commit("unit_price")}
          className="w-full rounded-md border border-transparent bg-transparent px-2 py-1.5 text-right text-sm text-white focus:border-brand-700 focus:outline-none"
        />
        {computedMargin !== null && Number(costPerUnit) > 0 ? (
          <p
            className={`mt-0.5 text-right text-[10px] ${
              computedMargin >= 0 ? "text-emerald-300" : "text-rose-300"
            }`}
          >
            marge {computedMargin}%
          </p>
        ) : null}
      </td>
      <td className="px-3 py-3 w-12 text-center">
        <input
          type="checkbox"
          checked={item.tps_applicable}
          onChange={(e) => onPatch({ tps_applicable: e.target.checked })}
          className="h-4 w-4 accent-accent-500"
          aria-label="TPS applicable"
        />
      </td>
      <td className="px-3 py-3 w-12 text-center">
        <input
          type="checkbox"
          checked={item.tvq_applicable}
          onChange={(e) => onPatch({ tvq_applicable: e.target.checked })}
          className="h-4 w-4 accent-accent-500"
          aria-label="TVQ applicable"
        />
      </td>
      <td className="px-3 py-3 w-32 whitespace-nowrap text-right text-sm font-semibold text-white">
        <span
          className={
            item.kind === "rabais" || computedTotal < 0
              ? "text-rose-300"
              : undefined
          }
        >
          {fmtMoney(computedTotal)}
        </span>
        {item.kind !== "service" ? (
          <span className="ml-1 rounded bg-white/10 px-1 py-0.5 text-[9px] uppercase text-white/60">
            {item.kind}
          </span>
        ) : null}
      </td>
      <td className="px-3 py-3 w-10 text-right">
        {busy ? (
          <Loader2 className="ml-auto h-4 w-4 animate-spin text-accent-500" />
        ) : (
          <button
            type="button"
            onClick={onDelete}
            aria-label="Supprimer l'item"
            className="rounded-md p-1.5 text-white/40 transition hover:bg-rose-500/15 hover:text-rose-400"
          >
            <Trash2 className="h-4 w-4" />
          </button>
        )}
      </td>
    </tr>
  );
}

function ActionCard({
  icon: Icon,
  label,
  hint
}: {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  hint: string;
}) {
  return (
    <button
      type="button"
      disabled
      title="À venir"
      className="flex items-start gap-3 rounded-xl border border-dashed border-brand-800 bg-brand-900/40 p-4 text-left opacity-60"
    >
      <Icon className="mt-0.5 h-5 w-5 flex-shrink-0 text-accent-500" />
      <div>
        <p className="text-sm font-semibold text-white">{label}</p>
        <p className="mt-0.5 text-xs text-white/50">{hint}</p>
      </div>
    </button>
  );
}

/**
 * Free satellite preview (Esri World Imagery tiles via Leaflet) + a
 * "Ouvrir dans Google Maps" button for the staff to hop into Street
 * View on demand (no API cost — it's just a link).
 *
 * Replaces the former Google StreetView iframe which required a paid
 * API key to stay watermark-free.
 */
function StreetViewEmbed({ address }: { address: string }) {
  const mapRef = useRef<HTMLDivElement | null>(null);
  const [coords, setCoords] = useState<[number, number] | null>(null);

  useEffect(() => {
    let cancelled = false;
    let map: unknown = null; // eslint-disable-line @typescript-eslint/no-explicit-any
    (async () => {
      if (!mapRef.current) return;
      const L = (await import("leaflet")).default;
      if (!document.getElementById("leaflet-css")) {
        const link = document.createElement("link");
        link.id = "leaflet-css";
        link.rel = "stylesheet";
        link.href = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.css";
        document.head.appendChild(link);
      }
      // Geocode via Photon (free, OSM-backed, no key).
      let center: [number, number] = [45.5017, -73.5673];
      try {
        const r = await fetch(
          `https://photon.komoot.io/api/?q=${encodeURIComponent(
            address
          )}&limit=1`
        );
        if (r.ok) {
          const data = await r.json();
          const coord = data.features?.[0]?.geometry?.coordinates;
          if (coord && coord.length === 2) center = [coord[1], coord[0]];
        }
      } catch {
        /* ignore */
      }
      if (cancelled) return;
      setCoords(center);
      const m = L.map(mapRef.current, {
        center,
        zoom: 19,
        zoomControl: true,
        scrollWheelZoom: false
      });
      map = m;
      L.tileLayer(
        "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        {
          attribution: "Imagery © Esri",
          maxZoom: 22,
          maxNativeZoom: 19
        }
      ).addTo(m);
      L.marker(center).addTo(m);
    })();
    return () => {
      cancelled = true;
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      (map as any)?.remove?.();
    };
  }, [address]);

  const gmapsUrl = `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(
    address
  )}`;
  const gstreetUrl = `https://www.google.com/maps/@?api=1&map_action=pano&viewpoint=${encodeURIComponent(
    address
  )}`;
  // Embedded Street View — Google's lightweight iframe endpoint that
  // works without an API key. Uses coordinates if we geocoded them,
  // otherwise falls back to the address string.
  const svEmbedSrc = coords
    ? `https://maps.google.com/maps?q=&layer=c&cbll=${coords[0]},${coords[1]}&cbp=11,0,0,0,0&output=svembed`
    : `https://maps.google.com/maps?q=${encodeURIComponent(
        address
      )}&layer=c&output=svembed`;

  return (
    <div className="mt-3 space-y-2">
      <div className="grid gap-2 sm:grid-cols-2">
        <div
          ref={mapRef}
          className="h-64 w-full overflow-hidden rounded-lg border border-brand-800 bg-brand-950"
        />
        <iframe
          key={svEmbedSrc}
          src={svEmbedSrc}
          className="h-64 w-full overflow-hidden rounded-lg border border-brand-800 bg-brand-950"
          loading="lazy"
          referrerPolicy="no-referrer-when-downgrade"
          title="Street View"
        />
      </div>
      <div className="flex flex-wrap gap-2 text-xs">
        <a
          href={gmapsUrl}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-1 rounded-md border border-brand-800 bg-brand-900 px-2 py-1 text-white/70 hover:border-accent-500 hover:text-white"
        >
          🗺️ Ouvrir dans Google Maps
        </a>
        <a
          href={gstreetUrl}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-1 rounded-md border border-brand-800 bg-brand-900 px-2 py-1 text-white/70 hover:border-accent-500 hover:text-white"
        >
          👁️ Ouvrir Street View en grand
        </a>
      </div>
    </div>
  );
}

type ServiceTemplate = {
  id: number;
  name: string;
  description: string | null;
  default_unit: string | null;
  default_unit_price: number | null;
  is_active: boolean;
};

function ServiceTemplatePicker({
  soumissionId,
  onClose,
  onInserted
}: {
  soumissionId: number;
  onClose: () => void;
  onInserted: () => void;
}) {
  const [templates, setTemplates] = useState<ServiceTemplate[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<number | null>(null);
  const [q, setQ] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await authedFetch("/api/v1/service-templates");
        if (!res.ok) throw new Error();
        if (!cancelled)
          setTemplates((await res.json()) as ServiceTemplate[]);
      } catch {
        if (!cancelled) setError("Chargement échoué.");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const filtered = q.trim()
    ? templates.filter((t) =>
        t.name.toLowerCase().includes(q.trim().toLowerCase())
      )
    : templates;

  async function apply(t: ServiceTemplate) {
    setBusy(t.id);
    setError(null);
    try {
      const res = await authedFetch(
        `/api/v1/service-templates/${t.id}/apply`,
        {
          method: "POST",
          body: JSON.stringify({ soumission_id: soumissionId })
        }
      );
      if (!res.ok) throw new Error();
      onInserted();
    } catch {
      setError("Insertion échouée.");
    } finally {
      setBusy(null);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4"
      onClick={onClose}
    >
      <div
        className="w-full max-w-xl overflow-hidden rounded-2xl border border-brand-800 bg-brand-950"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="flex items-center justify-between border-b border-brand-800 px-4 py-3">
          <h3 className="text-sm font-bold text-white">
            Insérer un service du catalogue
          </h3>
          <Link
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            href={"/app/services-catalogue" as any}
            className="text-xs text-accent-500 hover:underline"
          >
            Gérer le catalogue →
          </Link>
        </header>

        <div className="border-b border-brand-800 p-4">
          <input
            type="search"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Rechercher un service…"
            className="input"
            autoFocus
          />
        </div>

        <div className="max-h-96 overflow-y-auto">
          {loading ? (
            <div className="flex items-center justify-center py-6">
              <Loader2 className="h-5 w-5 animate-spin text-white/40" />
            </div>
          ) : filtered.length === 0 ? (
            <p className="px-4 py-10 text-center text-sm text-white/50">
              {templates.length === 0
                ? "Catalogue vide. Crée ton premier service dans « Gérer le catalogue »."
                : "Aucun service ne correspond à la recherche."}
            </p>
          ) : (
            <ul className="divide-y divide-brand-800">
              {filtered.map((t) => (
                <li
                  key={t.id}
                  className="flex items-center justify-between gap-3 px-4 py-3"
                >
                  <div className="min-w-0">
                    <p className="truncate text-sm font-semibold text-white">
                      {t.name}
                    </p>
                    {t.description ? (
                      <p className="mt-0.5 truncate text-xs text-white/50">
                        {t.description}
                      </p>
                    ) : null}
                    {t.default_unit_price != null ? (
                      <p className="mt-1 text-xs text-accent-400">
                        {t.default_unit_price} $
                        {t.default_unit ? ` / ${t.default_unit}` : ""}
                      </p>
                    ) : null}
                  </div>
                  <button
                    type="button"
                    onClick={() => apply(t)}
                    disabled={busy === t.id}
                    className="rounded-lg bg-accent-500 px-3 py-2 text-xs font-bold text-brand-950 disabled:opacity-60"
                  >
                    {busy === t.id ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    ) : (
                      "Insérer"
                    )}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>

        {error ? (
          <p className="border-t border-brand-800 px-4 py-3 text-xs text-rose-300">
            {error}
          </p>
        ) : null}
      </div>
    </div>
  );
}
