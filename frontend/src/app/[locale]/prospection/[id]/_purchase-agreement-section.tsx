"use client";

import { useCallback, useEffect, useState } from "react";
import {
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  FileSignature,
  FileText,
  Loader2,
  Mail,
  Plus,
  Send,
  Trash2,
  XCircle,
} from "lucide-react";

import { authedFetch } from "@/lib/auth";
import { useConfirm } from "@/components/confirm-dialog";

type PA = {
  id: number;
  reference: string;
  lead_id: number;
  status: string;
  created_at: string;
  updated_at: string | null;
  sent_to_seller_at: string | null;
  buyer_signed_at: string | null;
  buyer_signed_name: string | null;
  seller_signed_at: string | null;
  seller_signed_name: string | null;
  seller_response: string | null;
  seller_rejection_reason: string | null;

  buyer_1_name: string | null;
  buyer_1_email: string | null;
  buyer_1_phone_day: string | null;
  buyer_1_address: string | null;
  buyer_2_name: string | null;
  buyer_2_email: string | null;

  seller_1_name: string | null;
  seller_1_email: string | null;
  seller_1_phone_day: string | null;
  seller_1_address: string | null;
  seller_2_name: string | null;
  seller_2_email: string | null;

  property_address: string | null;
  lot_designation: string | null;
  lot_width: number | null;
  lot_depth: number | null;
  lot_dimension_unit: string | null;
  lot_area: number | null;
  lot_area_unit: string | null;

  price: number | null;
  down_payment: number | null;
  mortgage_amount: number | null;
  deposit_amount: number | null;
  deposit_notary: string | null;

  visit_date: string | null;
  rented_appliances_text: string | null;
  annual_rents: number | null;
  leases_expiry_text: string | null;

  financing_kind: string | null;
  financing_min_pct: number | null;
  financing_max_rate: number | null;
  financing_amortization_years: number | null;
  financing_min_term_years: number | null;
  inspection_enabled: boolean | null;
  inspection_days: number | null;
  visit_units_enabled: boolean | null;
  water_septic_enabled: boolean | null;
  buyer_property_sale_enabled: boolean | null;
  buyer_property_address: string | null;
  buyer_property_deadline: string | null;
  conditional_other_offer_enabled: boolean | null;
  other_offer_date: string | null;

  act_of_sale_date: string | null;
  occupation_date: string | null;
  occupation_time: string | null;
  occupation_compensation_per_month: number | null;
  baux_text: string | null;
  inclusions_text: string | null;
  exclusions_text: string | null;

  other_conditions_text: string | null;

  acceptance_deadline_date: string | null;
  acceptance_deadline_time: string | null;

  notes: string | null;
};

const STATUS_LABEL: Record<string, string> = {
  draft: "Brouillon",
  pending_buyer_signature: "Attente sig. acheteur",
  pending_seller_signature: "Attente sig. vendeur",
  accepted: "Acceptée",
  rejected: "Refusée",
  expired: "Expirée",
};

const STATUS_COLOR: Record<string, string> = {
  draft: "bg-white/10 text-white/70",
  pending_buyer_signature: "bg-amber-500/20 text-amber-200",
  pending_seller_signature: "bg-blue-500/20 text-blue-200",
  accepted: "bg-emerald-500/20 text-emerald-200",
  rejected: "bg-rose-500/20 text-rose-200",
  expired: "bg-white/10 text-white/40",
};

function fmt$(n: number | null): string {
  if (n === null || n === undefined) return "—";
  return n.toLocaleString("fr-CA", {
    style: "currency",
    currency: "CAD",
    maximumFractionDigits: 0,
  });
}

function fmtDate(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("fr-CA", {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}

export function PurchaseAgreementSection({ leadId }: { leadId: number }) {
  const confirm = useConfirm();
  const [pas, setPas] = useState<PA[]>([]);
  const [loading, setLoading] = useState(true);
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [creating, setCreating] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      const res = await authedFetch(
        `/api/v1/prospection/${leadId}/purchase-agreements`
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setPas((await res.json()) as PA[]);
    } catch {
      setPas([]);
    } finally {
      setLoading(false);
    }
  }, [leadId]);

  useEffect(() => {
    void reload();
  }, [reload]);

  async function createPA() {
    setCreating(true);
    setErr(null);
    try {
      const res = await authedFetch(
        `/api/v1/prospection/${leadId}/purchase-agreements`,
        {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({}),
        }
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const created = (await res.json()) as PA;
      setPas((xs) => [created, ...xs]);
      setExpandedId(created.id);
    } catch (e) {
      setErr((e as Error).message || "Création échouée.");
    } finally {
      setCreating(false);
    }
  }

  async function removePA(id: number) {
    if (!(await confirm("Supprimer cette promesse d'achat ?"))) return;
    try {
      const res = await authedFetch(`/api/v1/purchase-agreements/${id}`, {
        method: "DELETE",
      });
      if (!res.ok && res.status !== 204) throw new Error(`HTTP ${res.status}`);
      setPas((xs) => xs.filter((p) => p.id !== id));
      if (expandedId === id) setExpandedId(null);
    } catch (e) {
      setErr((e as Error).message || "Suppression échouée.");
    }
  }

  return (
    <section className="rounded-xl border border-brand-800 bg-brand-900 p-5">
      <div className="flex items-center justify-between gap-2">
        <h2 className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wider text-accent-500">
          <FileSignature className="h-4 w-4" />
          Promesse d&apos;achat
        </h2>
        <button
          type="button"
          onClick={createPA}
          disabled={creating}
          className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-500 px-2.5 py-1 text-xs font-semibold text-brand-950 hover:bg-emerald-400 disabled:opacity-60"
        >
          {creating ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <Plus className="h-3.5 w-3.5" />
          )}
          Nouvelle PA
        </button>
      </div>

      {err ? <p className="mt-3 text-sm text-rose-300">{err}</p> : null}

      {loading ? (
        <div className="mt-3 flex items-center gap-2 text-sm text-white/50">
          <Loader2 className="h-4 w-4 animate-spin" /> Chargement…
        </div>
      ) : pas.length === 0 ? (
        <p className="mt-3 text-sm text-white/50">
          Aucune promesse d&apos;achat. Cliquez « Nouvelle PA » pour préparer
          une offre — l&apos;adresse et le propriétaire sont auto-remplis depuis
          le lead.
        </p>
      ) : (
        <ul className="mt-3 space-y-2">
          {pas.map((pa) => (
            <li
              key={pa.id}
              className="rounded-lg border border-brand-800 bg-brand-950/40"
            >
              <div className="flex items-center justify-between gap-2 px-3 py-2">
                <button
                  type="button"
                  onClick={() =>
                    setExpandedId(expandedId === pa.id ? null : pa.id)
                  }
                  className="flex flex-1 items-center gap-3 text-left"
                >
                  {expandedId === pa.id ? (
                    <ChevronUp className="h-4 w-4 text-white/50" />
                  ) : (
                    <ChevronDown className="h-4 w-4 text-white/50" />
                  )}
                  <div className="flex-1">
                    <div className="flex items-center gap-2">
                      <span className="font-mono text-sm text-white">
                        {pa.reference}
                      </span>
                      <span
                        className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${
                          STATUS_COLOR[pa.status] || "bg-white/10 text-white/60"
                        }`}
                      >
                        {STATUS_LABEL[pa.status] || pa.status}
                      </span>
                    </div>
                    <div className="mt-0.5 text-xs text-white/50">
                      {fmt$(pa.price)} · {fmtDate(pa.created_at)}
                    </div>
                  </div>
                </button>
                <button
                  type="button"
                  onClick={() => removePA(pa.id)}
                  className="rounded p-1 text-white/40 hover:bg-rose-500/10 hover:text-rose-300"
                  aria-label="Supprimer"
                >
                  <Trash2 className="h-4 w-4" />
                </button>
              </div>
              {expandedId === pa.id ? (
                <PADetail pa={pa} onUpdated={reload} onSetErr={setErr} />
              ) : null}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

// --- Détail / formulaire ---------------------------------------------

function PADetail({
  pa,
  onUpdated,
  onSetErr,
}: {
  pa: PA;
  onUpdated: () => Promise<void>;
  onSetErr: (s: string | null) => void;
}) {
  const [form, setForm] = useState<Partial<PA>>({});
  const [saving, setSaving] = useState(false);
  const [sending, setSending] = useState<"buyer" | "seller" | null>(null);
  const [sendModal, setSendModal] = useState<"buyer" | "seller" | null>(null);

  const merged = { ...pa, ...form };
  const dirty = Object.keys(form).length > 0;
  const locked =
    pa.status === "accepted" || pa.status === "rejected" ||
    pa.status === "pending_seller_signature";

  function set<K extends keyof PA>(key: K, value: PA[K]) {
    setForm((f) => ({ ...f, [key]: value }));
  }

  async function save() {
    setSaving(true);
    onSetErr(null);
    try {
      const res = await authedFetch(`/api/v1/purchase-agreements/${pa.id}`, {
        method: "PATCH",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(form),
      });
      if (!res.ok) {
        const t = await res.text();
        throw new Error(t.slice(0, 240) || `HTTP ${res.status}`);
      }
      setForm({});
      await onUpdated();
    } catch (e) {
      onSetErr((e as Error).message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="border-t border-brand-800 px-3 py-3 text-sm">
      {/* Actions principales */}
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <a
          href={`${process.env.NEXT_PUBLIC_API_BASE_URL || ""}/api/v1/purchase-agreements/${pa.id}/pdf`}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-1.5 rounded-lg border border-brand-800 bg-brand-900 px-3 py-1.5 text-xs font-semibold text-white/80 hover:text-white"
        >
          <FileText className="h-3.5 w-3.5" /> Aperçu PDF
        </a>
        {(pa.status === "draft" ||
          pa.status === "pending_buyer_signature") && (
          <button
            type="button"
            onClick={() => setSendModal("buyer")}
            disabled={sending !== null}
            className="inline-flex items-center gap-1.5 rounded-lg bg-amber-500 px-3 py-1.5 text-xs font-bold text-brand-950 hover:bg-amber-400 disabled:opacity-60"
          >
            <Send className="h-3.5 w-3.5" /> Envoyer à l&apos;acheteur
          </button>
        )}
        {pa.status === "pending_seller_signature" && (
          <button
            type="button"
            onClick={() => setSendModal("seller")}
            disabled={sending !== null}
            className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-500 px-3 py-1.5 text-xs font-bold text-brand-950 hover:bg-emerald-400 disabled:opacity-60"
          >
            <Mail className="h-3.5 w-3.5" /> Envoyer au vendeur
          </button>
        )}
      </div>

      {pa.status === "accepted" ? (
        <div className="mb-3 flex items-center gap-2 rounded-lg border border-emerald-500/30 bg-emerald-500/10 p-2 text-xs text-emerald-200">
          <CheckCircle2 className="h-4 w-4" /> Acceptée par{" "}
          {pa.seller_signed_name} le {fmtDate(pa.seller_signed_at)}
        </div>
      ) : null}
      {pa.status === "rejected" ? (
        <div className="mb-3 rounded-lg border border-rose-500/30 bg-rose-500/10 p-2 text-xs text-rose-200">
          <div className="flex items-center gap-2">
            <XCircle className="h-4 w-4" /> Refusée par {pa.seller_signed_name}{" "}
            le {fmtDate(pa.seller_signed_at)}
          </div>
          {pa.seller_rejection_reason ? (
            <div className="mt-1 italic">{pa.seller_rejection_reason}</div>
          ) : null}
        </div>
      ) : null}

      {/* Formulaire — sections collapsibles simples */}
      <FormSection title="Objet du contrat">
        <Field label="Adresse de l'immeuble">
          <input
            className="input-pa"
            disabled={locked}
            value={merged.property_address || ""}
            onChange={(e) => set("property_address", e.target.value)}
          />
        </Field>
        <Field label="Désignation cadastrale (lot)">
          <input
            className="input-pa"
            disabled={locked}
            value={merged.lot_designation || ""}
            onChange={(e) => set("lot_designation", e.target.value)}
          />
        </Field>
      </FormSection>

      <FormSection title="Prix et modalités">
        <div className="grid grid-cols-2 gap-2">
          <Field label="Prix offert ($)">
            <input
              type="number"
              className="input-pa"
              disabled={locked}
              value={merged.price ?? ""}
              onChange={(e) =>
                set("price", e.target.value ? Number(e.target.value) : null)
              }
            />
          </Field>
          <Field label="Mise de fonds ($)">
            <input
              type="number"
              className="input-pa"
              disabled={locked}
              value={merged.down_payment ?? ""}
              onChange={(e) =>
                set(
                  "down_payment",
                  e.target.value ? Number(e.target.value) : null
                )
              }
            />
          </Field>
          <Field label="Emprunt hypothécaire ($)">
            <input
              type="number"
              className="input-pa"
              disabled={locked}
              value={merged.mortgage_amount ?? ""}
              onChange={(e) =>
                set(
                  "mortgage_amount",
                  e.target.value ? Number(e.target.value) : null
                )
              }
            />
          </Field>
          <Field label="Acompte ($)">
            <input
              type="number"
              className="input-pa"
              disabled={locked}
              value={merged.deposit_amount ?? ""}
              onChange={(e) =>
                set(
                  "deposit_amount",
                  e.target.value ? Number(e.target.value) : null
                )
              }
            />
          </Field>
        </div>
      </FormSection>

      <FormSection title="Conditions">
        <div className="space-y-2">
          <label className="flex items-center gap-2 text-xs">
            <input
              type="checkbox"
              disabled={locked}
              checked={!!merged.inspection_enabled}
              onChange={(e) => set("inspection_enabled", e.target.checked)}
            />
            6.2.1 Inspection (
            <input
              type="number"
              className="w-12 rounded border border-brand-800 bg-brand-950 px-1 py-0.5 text-xs"
              disabled={locked}
              value={merged.inspection_days ?? 10}
              onChange={(e) =>
                set("inspection_days", Number(e.target.value) || 10)
              }
            />{" "}
            jours)
          </label>
          <label className="flex items-center gap-2 text-xs">
            <input
              type="checkbox"
              disabled={locked}
              checked={!!merged.visit_units_enabled}
              onChange={(e) => set("visit_units_enabled", e.target.checked)}
            />
            6.2.2 Visite des logements et vérification des baux
          </label>
          <label className="flex items-center gap-2 text-xs">
            <input
              type="checkbox"
              disabled={locked}
              checked={!!merged.water_septic_enabled}
              onChange={(e) => set("water_septic_enabled", e.target.checked)}
            />
            6.2.3 Tests eau potable / installations septiques
          </label>
        </div>
      </FormSection>

      <FormSection title="Transfert et occupation">
        <div className="grid grid-cols-2 gap-2">
          <Field label="Acte de vente (avant le)">
            <input
              type="date"
              className="input-pa"
              disabled={locked}
              value={merged.act_of_sale_date || ""}
              onChange={(e) => set("act_of_sale_date", e.target.value || null)}
            />
          </Field>
          <Field label="Occupation (date)">
            <input
              type="date"
              className="input-pa"
              disabled={locked}
              value={merged.occupation_date || ""}
              onChange={(e) => set("occupation_date", e.target.value || null)}
            />
          </Field>
        </div>
        <Field label="Inclusions">
          <textarea
            className="input-pa"
            rows={2}
            disabled={locked}
            value={merged.inclusions_text || ""}
            onChange={(e) => set("inclusions_text", e.target.value)}
          />
        </Field>
        <Field label="Exclusions">
          <textarea
            className="input-pa"
            rows={2}
            disabled={locked}
            value={merged.exclusions_text || ""}
            onChange={(e) => set("exclusions_text", e.target.value)}
          />
        </Field>
      </FormSection>

      <FormSection title="Délai d'acceptation">
        <div className="grid grid-cols-2 gap-2">
          <Field label="Date">
            <input
              type="date"
              className="input-pa"
              disabled={locked}
              value={merged.acceptance_deadline_date || ""}
              onChange={(e) =>
                set("acceptance_deadline_date", e.target.value || null)
              }
            />
          </Field>
          <Field label="Heure">
            <input
              type="time"
              className="input-pa"
              disabled={locked}
              value={merged.acceptance_deadline_time || ""}
              onChange={(e) =>
                set("acceptance_deadline_time", e.target.value || null)
              }
            />
          </Field>
        </div>
      </FormSection>

      {!locked && dirty ? (
        <div className="mt-3 flex justify-end">
          <button
            type="button"
            onClick={save}
            disabled={saving}
            className="inline-flex items-center gap-1.5 rounded-lg bg-accent-500 px-3 py-1.5 text-xs font-bold text-brand-950 hover:bg-accent-400 disabled:opacity-60"
          >
            {saving ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : null}
            Enregistrer
          </button>
        </div>
      ) : null}

      {sendModal ? (
        <SendModal
          paId={pa.id}
          role={sendModal}
          defaultEmail={
            sendModal === "buyer"
              ? pa.buyer_1_email || ""
              : pa.seller_1_email || ""
          }
          onClose={() => setSendModal(null)}
          onSent={async () => {
            setSendModal(null);
            await onUpdated();
          }}
          setSending={setSending}
          onError={onSetErr}
        />
      ) : null}

      <style jsx>{`
        :global(.input-pa) {
          width: 100%;
          background: rgb(11 16 28);
          border: 1px solid rgb(33 41 60);
          border-radius: 6px;
          padding: 6px 8px;
          color: white;
          font-size: 12px;
        }
        :global(.input-pa:disabled) {
          opacity: 0.6;
        }
      `}</style>
    </div>
  );
}

function FormSection({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(true);
  return (
    <div className="mb-2 rounded-lg border border-brand-800 bg-brand-950/30">
      <button
        type="button"
        className="flex w-full items-center justify-between px-3 py-2 text-left text-xs font-semibold uppercase tracking-wider text-white/70"
        onClick={() => setOpen((o) => !o)}
      >
        {title}
        {open ? (
          <ChevronUp className="h-3.5 w-3.5" />
        ) : (
          <ChevronDown className="h-3.5 w-3.5" />
        )}
      </button>
      {open ? <div className="space-y-2 px-3 pb-3">{children}</div> : null}
    </div>
  );
}

function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <label className="block">
      <span className="mb-1 block text-[10px] uppercase tracking-wider text-white/50">
        {label}
      </span>
      {children}
    </label>
  );
}

function SendModal({
  paId,
  role,
  defaultEmail,
  onClose,
  onSent,
  setSending,
  onError,
}: {
  paId: number;
  role: "buyer" | "seller";
  defaultEmail: string;
  onClose: () => void;
  onSent: () => Promise<void>;
  setSending: (v: "buyer" | "seller" | null) => void;
  onError: (s: string | null) => void;
}) {
  const [to, setTo] = useState(defaultEmail);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit() {
    setBusy(true);
    setSending(role);
    onError(null);
    try {
      const path =
        role === "buyer"
          ? `/api/v1/purchase-agreements/${paId}/send-to-buyer`
          : `/api/v1/purchase-agreements/${paId}/send-to-seller`;
      const res = await authedFetch(path, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          to: [to.trim()],
          message: message.trim() || null,
        }),
      });
      if (!res.ok) {
        const t = await res.text();
        throw new Error(t.slice(0, 240) || `HTTP ${res.status}`);
      }
      await onSent();
    } catch (e) {
      onError((e as Error).message);
    } finally {
      setBusy(false);
      setSending(null);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4"
      onClick={busy ? undefined : onClose}
    >
      <div
        className="w-full max-w-md rounded-2xl border border-brand-800 bg-brand-950 p-6"
        onClick={(e) => e.stopPropagation()}
      >
        <h3 className="text-base font-bold text-white">
          {role === "buyer"
            ? "Envoyer à l'acheteur pour signature"
            : "Envoyer au vendeur"}
        </h3>
        <p className="mt-1 text-xs text-white/60">
          {role === "buyer"
            ? "L'acheteur recevra un lien pour réviser et signer la PA. Une fois signée, vous pourrez l'envoyer au vendeur."
            : "Le vendeur recevra le PDF signé par l'acheteur, avec un lien pour accepter ou refuser."}
        </p>
        <div className="mt-4 space-y-3">
          <Field label="Courriel destinataire">
            <input
              type="email"
              className="input-pa"
              value={to}
              onChange={(e) => setTo(e.target.value)}
              placeholder="exemple@domaine.com"
            />
          </Field>
          <Field label="Message (optionnel)">
            <textarea
              className="input-pa"
              rows={3}
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              placeholder="Petit mot personnel…"
            />
          </Field>
        </div>
        <div className="mt-5 flex justify-end gap-3">
          <button
            type="button"
            onClick={onClose}
            disabled={busy}
            className="text-sm text-white/70 hover:text-white"
          >
            Annuler
          </button>
          <button
            type="button"
            onClick={submit}
            disabled={busy || !to.trim()}
            className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-500 px-3 py-1.5 text-sm font-bold text-brand-950 hover:bg-emerald-400 disabled:opacity-60"
          >
            {busy ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Send className="h-3.5 w-3.5" />
            )}
            Envoyer
          </button>
        </div>
      </div>
    </div>
  );
}
