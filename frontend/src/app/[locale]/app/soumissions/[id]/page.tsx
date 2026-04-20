"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter as useNextRouter } from "next/navigation";
import {
  ArrowLeft,
  FileText,
  Loader2,
  Mail,
  PenTool,
  Save,
  Send,
  Trash2
} from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { Link } from "@/i18n/navigation";
import { useAppLayout } from "../../layout";
import { authedFetch } from "@/lib/auth";

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
  created_at: string;
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

function isoToDateInput(iso: string | null): string {
  if (!iso) return "";
  return iso.slice(0, 10);
}

export default function SoumissionDetailPage() {
  const { onOpenSidebar } = useAppLayout();
  const params = useParams<{ id: string }>();
  const id = Number(params.id);
  const router = useNextRouter();

  const [s, setS] = useState<Soumission | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);

  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [subtotal, setSubtotal] = useState<string>("");
  const [validUntil, setValidUntil] = useState<string>("");
  const [notes, setNotes] = useState("");

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const res = await authedFetch(`/api/v1/soumissions/${id}`);
        if (!res.ok) throw new Error(`http_${res.status}`);
        const data = (await res.json()) as Soumission;
        if (!cancelled) {
          setS(data);
          setTitle(data.title);
          setDescription(data.description || "");
          setSubtotal(data.subtotal != null ? String(data.subtotal) : "");
          setValidUntil(isoToDateInput(data.valid_until));
          setNotes(data.notes || "");
        }
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

  const subtotalNum = Number(subtotal) || 0;
  const tps = +(subtotalNum * TPS_RATE).toFixed(2);
  const tvq = +(subtotalNum * TVQ_RATE).toFixed(2);
  const total = +(subtotalNum + tps + tvq).toFixed(2);

  const dirty =
    s !== null &&
    (title !== s.title ||
      description !== (s.description || "") ||
      String(s.subtotal || "") !== subtotal ||
      isoToDateInput(s.valid_until) !== validUntil ||
      (s.notes || "") !== notes);

  async function saveChanges() {
    if (!s) return;
    setSaving(true);
    setError(null);
    try {
      const payload = {
        title: title.trim(),
        description: description.trim() || null,
        subtotal: subtotalNum,
        tps,
        tvq,
        total,
        valid_until: validUntil ? new Date(validUntil).toISOString() : null,
        notes: notes.trim() || null
      };
      const res = await authedFetch(`/api/v1/soumissions/${id}`, {
        method: "PATCH",
        body: JSON.stringify(payload)
      });
      if (!res.ok) throw new Error();
      const updated = (await res.json()) as Soumission;
      setS(updated);
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
      const res = await authedFetch(`/api/v1/soumissions/${id}`, {
        method: "PATCH",
        body: JSON.stringify({
          status: newStatus,
          sent_at:
            newStatus === "sent" && !s.sent_at
              ? new Date().toISOString()
              : undefined,
          accepted_at:
            newStatus === "accepted" && !s.accepted_at
              ? new Date().toISOString()
              : undefined
        })
      });
      if (!res.ok) throw new Error();
      const updated = (await res.json()) as Soumission;
      setS(updated);
    } catch {
      setS(prev);
      setError("Changement de statut échoué.");
    }
  }

  async function deleteSoumission() {
    if (!s) return;
    if (!confirm(`Supprimer la soumission ${s.reference} ?`)) return;
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

  return (
    <>
      <AppTopbar
        breadcrumbs={[
          { label: "Construction" },
          { label: "Soumissions" },
          { label: s?.reference || "…" }
        ]}
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
            {/* Header */}
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
                    ? ` · Envoyée le ${new Date(s.sent_at).toLocaleDateString(
                        "fr-CA"
                      )}`
                    : ""}
                  {s.accepted_at
                    ? ` · Acceptée le ${new Date(
                        s.accepted_at
                      ).toLocaleDateString("fr-CA")}`
                    : ""}
                </p>
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
                    <option key={k} value={k}>
                      {v}
                    </option>
                  ))}
                </select>
                <button
                  type="button"
                  onClick={deleteSoumission}
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

            {/* Quick actions row (Phase 2 followup features placeholders) */}
            <div className="mt-6 grid gap-3 sm:grid-cols-3">
              <ActionCard
                icon={FileText}
                label="Générer PDF"
                hint="Version imprimable et téléchargeable."
              />
              <ActionCard
                icon={Mail}
                label="Envoyer au client"
                hint="Par courriel via Microsoft Graph."
              />
              <ActionCard
                icon={PenTool}
                label="Signature électronique"
                hint="Lien unique pour signature à distance."
              />
            </div>

            {/* Editable fields */}
            <div className="mt-8 grid gap-6 lg:grid-cols-3">
              <div className="lg:col-span-2 space-y-5 rounded-xl border border-brand-800 bg-brand-900 p-5">
                <h2 className="text-sm font-semibold uppercase tracking-wider text-accent-500">
                  Contenu
                </h2>

                <div>
                  <label htmlFor="title" className="label">
                    Titre
                  </label>
                  <input
                    id="title"
                    type="text"
                    value={title}
                    onChange={(e) => setTitle(e.target.value)}
                    className="input"
                  />
                </div>

                <div>
                  <label htmlFor="description" className="label">
                    Description détaillée
                  </label>
                  <textarea
                    id="description"
                    rows={8}
                    value={description}
                    onChange={(e) => setDescription(e.target.value)}
                    className="input"
                  />
                </div>

                <div className="grid gap-4 sm:grid-cols-2">
                  <div>
                    <label htmlFor="subtotal" className="label">
                      Sous-total (CAD)
                    </label>
                    <input
                      id="subtotal"
                      type="number"
                      step="0.01"
                      min="0"
                      value={subtotal}
                      onChange={(e) => setSubtotal(e.target.value)}
                      className="input"
                    />
                  </div>
                  <div>
                    <label htmlFor="valid_until" className="label">
                      Valide jusqu&apos;au
                    </label>
                    <input
                      id="valid_until"
                      type="date"
                      value={validUntil}
                      onChange={(e) => setValidUntil(e.target.value)}
                      className="input"
                    />
                  </div>
                </div>

                <div>
                  <label htmlFor="notes" className="label">
                    Notes internes
                  </label>
                  <textarea
                    id="notes"
                    rows={4}
                    value={notes}
                    onChange={(e) => setNotes(e.target.value)}
                    placeholder="Notes non visibles par le client."
                    className="input"
                  />
                </div>

                <div>
                  <button
                    type="button"
                    onClick={saveChanges}
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
              </div>

              {/* Sidebar: totals + meta */}
              <aside className="space-y-5">
                <div className="rounded-xl border border-brand-800 bg-brand-900 p-5">
                  <h2 className="text-sm font-semibold uppercase tracking-wider text-accent-500">
                    Montants
                  </h2>
                  <dl className="mt-4 space-y-2 text-sm">
                    <div className="flex items-center justify-between">
                      <dt className="text-white/60">Sous-total</dt>
                      <dd className="text-white">{fmtMoney(subtotalNum)}</dd>
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
                      <dd className="text-lg font-bold text-accent-500">
                        {fmtMoney(total)}
                      </dd>
                    </div>
                  </dl>
                </div>

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
                  </dl>
                </div>

                <div className="rounded-xl border border-dashed border-brand-800 bg-brand-900/40 p-5 text-xs text-white/50">
                  <p className="flex items-center gap-2 text-white/70">
                    <Send className="h-4 w-4 text-accent-500" />
                    <span className="font-semibold">
                      Actions à venir (phase 2b)
                    </span>
                  </p>
                  <ul className="mt-2 list-disc pl-5">
                    <li>Lignes d&apos;items détaillées</li>
                    <li>Génération PDF + envoi courriel</li>
                    <li>Signature électronique</li>
                    <li>Synchronisation QuickBooks</li>
                  </ul>
                </div>
              </aside>
            </div>
          </>
        ) : null}
      </div>
    </>
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
