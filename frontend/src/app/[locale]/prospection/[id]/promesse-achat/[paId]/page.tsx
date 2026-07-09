"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams } from "next/navigation";
import {
  ArrowLeft,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  FileSignature,
  FileText,
  Loader2,
  Mail,
  Send,
  XCircle,
} from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { Link } from "@/i18n/navigation";
import { authedFetch } from "@/lib/auth";
import { useProspectionLayout } from "../../../layout";

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

export default function PAEditorPage() {
  const params = useParams<{ id: string; paId: string }>();
  const leadId = Number(params.id);
  const paId = Number(params.paId);
  const { onOpenSidebar } = useProspectionLayout();

  const [pa, setPa] = useState<PA | null>(null);
  const [form, setForm] = useState<Partial<PA>>({});
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [sendModal, setSendModal] = useState<"buyer" | "seller" | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      const res = await authedFetch(`/api/v1/purchase-agreements/${paId}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = (await res.json()) as PA;
      setPa(data);
      setForm({});
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, [paId]);

  useEffect(() => {
    void reload();
  }, [reload]);

  if (loading || !pa) {
    return (
      <main className="flex min-h-screen items-center justify-center bg-brand-950 text-white">
        <Loader2 className="h-6 w-6 animate-spin text-accent-500" />
      </main>
    );
  }

  const merged: PA = { ...pa, ...form };
  const dirty = Object.keys(form).length > 0;
  const locked =
    pa.status === "accepted" ||
    pa.status === "rejected" ||
    pa.status === "pending_seller_signature";

  function set<K extends keyof PA>(key: K, value: PA[K]) {
    setForm((f) => ({ ...f, [key]: value }));
  }

  async function save() {
    setSaving(true);
    setErr(null);
    try {
      const res = await authedFetch(`/api/v1/purchase-agreements/${paId}`, {
        method: "PATCH",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(form),
      });
      if (!res.ok) {
        const t = await res.text();
        throw new Error(t.slice(0, 240) || `HTTP ${res.status}`);
      }
      await reload();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <>
      <AppTopbar
        breadcrumbs={[
          { label: "Prospection", href: "/prospection" },
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          { label: `Lead #${leadId}`, href: `/prospection/${leadId}` as any },
          { label: `PA ${pa.reference}` },
        ]}
        onOpenSidebar={onOpenSidebar}
      />
      <div className="p-4 lg:p-6">
        <div className="mb-4 flex items-center gap-3">
          <Link
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            href={`/prospection/${leadId}` as any}
            className="inline-flex items-center gap-1.5 text-sm text-white/60 hover:text-white"
          >
            <ArrowLeft className="h-4 w-4" /> Retour à la fiche
          </Link>
        </div>

        <div className="flex flex-wrap items-baseline justify-between gap-3">
          <h1 className="flex items-center gap-2 text-2xl font-bold text-white">
            <FileSignature className="h-6 w-6 text-amber-400" />
            Promesse d&apos;achat — {pa.reference}
          </h1>
          <span
            className={`rounded-full px-3 py-1 text-xs font-semibold ${
              STATUS_COLOR[pa.status] || "bg-white/10 text-white/60"
            }`}
          >
            {STATUS_LABEL[pa.status] || pa.status}
          </span>
        </div>

        {/* Bandeau status final */}
        {pa.status === "accepted" ? (
          <div className="mt-4 flex items-center gap-2 rounded-lg border border-emerald-500/30 bg-emerald-500/10 p-3 text-sm text-emerald-200">
            <CheckCircle2 className="h-5 w-5" />
            Acceptée par {pa.seller_signed_name} le{" "}
            {pa.seller_signed_at
              ? new Date(pa.seller_signed_at).toLocaleString("fr-CA")
              : "—"}
          </div>
        ) : null}
        {pa.status === "rejected" ? (
          <div className="mt-4 rounded-lg border border-rose-500/30 bg-rose-500/10 p-3 text-sm text-rose-200">
            <div className="flex items-center gap-2">
              <XCircle className="h-5 w-5" /> Refusée par {pa.seller_signed_name}
              {" "}
              le{" "}
              {pa.seller_signed_at
                ? new Date(pa.seller_signed_at).toLocaleString("fr-CA")
                : "—"}
            </div>
            {pa.seller_rejection_reason ? (
              <div className="mt-1 italic">{pa.seller_rejection_reason}</div>
            ) : null}
          </div>
        ) : null}

        {/* Actions */}
        <div className="mt-4 flex flex-wrap items-center gap-2">
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
              className="inline-flex items-center gap-1.5 rounded-lg bg-amber-500 px-3 py-1.5 text-xs font-bold text-brand-950 hover:bg-amber-400"
            >
              <Send className="h-3.5 w-3.5" /> Envoyer à l&apos;acheteur
            </button>
          )}
          {pa.status === "pending_seller_signature" && (
            <button
              type="button"
              onClick={() => setSendModal("seller")}
              className="inline-flex items-center gap-1.5 rounded-lg bg-accent-500 px-3 py-1.5 text-xs font-bold text-brand-950 hover:bg-accent-400"
            >
              <Mail className="h-3.5 w-3.5" /> Envoyer au vendeur
            </button>
          )}
          {!locked && dirty ? (
            <button
              type="button"
              onClick={save}
              disabled={saving}
              className="ml-auto inline-flex items-center gap-1.5 rounded-lg bg-accent-500 px-3 py-1.5 text-xs font-bold text-brand-950 hover:bg-accent-400 disabled:opacity-60"
            >
              {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
              Enregistrer
            </button>
          ) : null}
        </div>

        {err ? (
          <p className="mt-3 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-300">
            {err}
          </p>
        ) : null}

        {/* Formulaire deux colonnes */}
        <div className="mt-6 grid gap-4 lg:grid-cols-2">
          <FormSection title="1. Identification des parties">
            <Field label="Acheteur principal — Nom">
              <input
                className="input"
                disabled={locked}
                value={merged.buyer_1_name || ""}
                onChange={(e) => set("buyer_1_name", e.target.value || null)}
              />
            </Field>
            <Field label="Acheteur — Courriel">
              <input
                type="email"
                className="input"
                disabled={locked}
                value={merged.buyer_1_email || ""}
                onChange={(e) => set("buyer_1_email", e.target.value || null)}
              />
            </Field>
            <Field label="Vendeur principal — Nom">
              <input
                className="input"
                disabled={locked}
                value={merged.seller_1_name || ""}
                onChange={(e) => set("seller_1_name", e.target.value || null)}
              />
            </Field>
            <Field label="Vendeur — Courriel">
              <input
                type="email"
                className="input"
                disabled={locked}
                value={merged.seller_1_email || ""}
                onChange={(e) => set("seller_1_email", e.target.value || null)}
              />
            </Field>
            <Field label="Vendeur — Téléphone (jour)">
              <input
                className="input"
                disabled={locked}
                value={merged.seller_1_phone_day || ""}
                onChange={(e) =>
                  set("seller_1_phone_day", e.target.value || null)
                }
              />
            </Field>
          </FormSection>

          <FormSection title="2. Objet du contrat">
            <Field label="Adresse civique">
              <input
                className="input"
                disabled={locked}
                value={merged.property_address || ""}
                onChange={(e) =>
                  set("property_address", e.target.value || null)
                }
              />
            </Field>
            <Field label="Désignation cadastrale (numéro de lot)">
              <input
                className="input"
                disabled={locked}
                value={merged.lot_designation || ""}
                onChange={(e) =>
                  set("lot_designation", e.target.value || null)
                }
              />
            </Field>
            <div className="grid grid-cols-3 gap-2">
              <Field label="Largeur">
                <input
                  type="number"
                  className="input"
                  disabled={locked}
                  value={merged.lot_width ?? ""}
                  onChange={(e) =>
                    set(
                      "lot_width",
                      e.target.value ? Number(e.target.value) : null
                    )
                  }
                />
              </Field>
              <Field label="Profondeur">
                <input
                  type="number"
                  className="input"
                  disabled={locked}
                  value={merged.lot_depth ?? ""}
                  onChange={(e) =>
                    set(
                      "lot_depth",
                      e.target.value ? Number(e.target.value) : null
                    )
                  }
                />
              </Field>
              <Field label="Unité">
                <select
                  className="input"
                  disabled={locked}
                  value={merged.lot_dimension_unit || "m"}
                  onChange={(e) => set("lot_dimension_unit", e.target.value)}
                >
                  <option value="m">m</option>
                  <option value="pi">pi</option>
                </select>
              </Field>
            </div>
          </FormSection>

          <FormSection title="3. Prix et modalités">
            <div className="grid grid-cols-2 gap-2">
              <Field label="Prix offert ($)">
                <input
                  type="number"
                  className="input"
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
                  className="input"
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
              <Field label="Hypothèque ($)">
                <input
                  type="number"
                  className="input"
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
                  className="input"
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
            <Field label="Notaire (fidéicommis)">
              <input
                className="input"
                disabled={locked}
                value={merged.deposit_notary || ""}
                onChange={(e) =>
                  set("deposit_notary", e.target.value || null)
                }
              />
            </Field>
          </FormSection>

          <FormSection title="6. Conditions">
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                disabled={locked}
                checked={!!merged.inspection_enabled}
                onChange={(e) => set("inspection_enabled", e.target.checked)}
              />
              6.2.1 Inspection
            </label>
            <Field label="Délai d'inspection (jours)">
              <input
                type="number"
                className="input"
                disabled={locked}
                value={merged.inspection_days ?? 10}
                onChange={(e) =>
                  set("inspection_days", Number(e.target.value) || 10)
                }
              />
            </Field>
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                disabled={locked}
                checked={!!merged.visit_units_enabled}
                onChange={(e) => set("visit_units_enabled", e.target.checked)}
              />
              6.2.2 Visite des logements et baux
            </label>
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                disabled={locked}
                checked={!!merged.water_septic_enabled}
                onChange={(e) => set("water_septic_enabled", e.target.checked)}
              />
              6.2.3 Tests eau / installations septiques
            </label>
          </FormSection>

          <FormSection title="7. Transfert et occupation">
            <div className="grid grid-cols-2 gap-2">
              <Field label="Acte de vente (avant le)">
                <input
                  type="date"
                  className="input"
                  disabled={locked}
                  value={merged.act_of_sale_date || ""}
                  onChange={(e) =>
                    set("act_of_sale_date", e.target.value || null)
                  }
                />
              </Field>
              <Field label="Occupation (date)">
                <input
                  type="date"
                  className="input"
                  disabled={locked}
                  value={merged.occupation_date || ""}
                  onChange={(e) =>
                    set("occupation_date", e.target.value || null)
                  }
                />
              </Field>
            </div>
            <Field label="Inclusions">
              <textarea
                rows={3}
                className="input"
                disabled={locked}
                value={merged.inclusions_text || ""}
                onChange={(e) => set("inclusions_text", e.target.value || null)}
              />
            </Field>
            <Field label="Exclusions">
              <textarea
                rows={3}
                className="input"
                disabled={locked}
                value={merged.exclusions_text || ""}
                onChange={(e) => set("exclusions_text", e.target.value || null)}
              />
            </Field>
          </FormSection>

          <FormSection title="8 + 9. Autres conditions et délai">
            <Field label="Autres conditions">
              <textarea
                rows={3}
                className="input"
                disabled={locked}
                value={merged.other_conditions_text || ""}
                onChange={(e) =>
                  set("other_conditions_text", e.target.value || null)
                }
              />
            </Field>
            <div className="grid grid-cols-2 gap-2">
              <Field label="Délai d'acceptation — Date">
                <input
                  type="date"
                  className="input"
                  disabled={locked}
                  value={merged.acceptance_deadline_date || ""}
                  onChange={(e) =>
                    set("acceptance_deadline_date", e.target.value || null)
                  }
                />
              </Field>
              <Field label="Délai — Heure">
                <input
                  type="time"
                  className="input"
                  disabled={locked}
                  value={merged.acceptance_deadline_time || ""}
                  onChange={(e) =>
                    set("acceptance_deadline_time", e.target.value || null)
                  }
                />
              </Field>
            </div>
          </FormSection>
        </div>

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
              await reload();
            }}
            onError={setErr}
          />
        ) : null}

        <style jsx>{`
          :global(.input) {
            width: 100%;
            background: rgb(11 16 28);
            border: 1px solid rgb(33 41 60);
            border-radius: 6px;
            padding: 6px 10px;
            color: white;
            font-size: 14px;
          }
          :global(.input:disabled) {
            opacity: 0.6;
          }
        `}</style>
      </div>
    </>
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
    <section className="rounded-xl border border-brand-800 bg-brand-900">
      <button
        type="button"
        className="flex w-full items-center justify-between px-4 py-3 text-left text-sm font-semibold uppercase tracking-wider text-accent-500"
        onClick={() => setOpen((o) => !o)}
      >
        {title}
        {open ? (
          <ChevronUp className="h-4 w-4" />
        ) : (
          <ChevronDown className="h-4 w-4" />
        )}
      </button>
      {open ? <div className="space-y-3 px-4 pb-4">{children}</div> : null}
    </section>
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
      <span className="mb-1 block text-xs uppercase tracking-wider text-white/50">
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
  onError,
}: {
  paId: number;
  role: "buyer" | "seller";
  defaultEmail: string;
  onClose: () => void;
  onSent: () => Promise<void>;
  onError: (s: string | null) => void;
}) {
  const [to, setTo] = useState(defaultEmail);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit() {
    setBusy(true);
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
            ? "L'acheteur recevra un lien pour réviser et signer la PA."
            : "Le vendeur recevra le PDF signé par l'acheteur, avec un lien pour accepter ou refuser."}
        </p>
        <div className="mt-4 space-y-3">
          <Field label="Courriel destinataire">
            <input
              type="email"
              className="input"
              value={to}
              onChange={(e) => setTo(e.target.value)}
              placeholder="exemple@domaine.com"
            />
          </Field>
          <Field label="Message (optionnel)">
            <textarea
              className="input"
              rows={3}
              value={message}
              onChange={(e) => setMessage(e.target.value)}
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
            className="inline-flex items-center gap-1.5 rounded-lg bg-accent-500 px-3 py-1.5 text-sm font-bold text-brand-950 hover:bg-accent-400 disabled:opacity-60"
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
