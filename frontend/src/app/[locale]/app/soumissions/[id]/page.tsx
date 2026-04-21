"use client";

import { useEffect, useMemo, useState } from "react";
import { useParams, useRouter as useNextRouter } from "next/navigation";
import {
  ArrowLeft,
  Check,
  FileText,
  Loader2,
  Mail,
  PenTool,
  Plus,
  RefreshCw,
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
  total: number;
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
  const [items, setItems] = useState<Item[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [itemBusy, setItemBusy] = useState<number | "new" | null>(null);
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

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const [sRes, iRes] = await Promise.all([
          authedFetch(`/api/v1/soumissions/${id}`),
          authedFetch(`/api/v1/soumissions/${id}/items`)
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
        setSendSubject(`Soumission ${sData.reference} — ${sData.title}`);
        if (sData.contact_request_id) {
          const cr = await authedFetch(
            `/api/v1/contact/${sData.contact_request_id}`
          );
          if (cr.ok && !cancelled) {
            const crData = (await cr.json()) as { email?: string };
            if (crData.email) setSendTo(crData.email);
          }
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

  const subtotal = useMemo(
    () => +items.reduce((sum, it) => sum + Number(it.total || 0), 0).toFixed(2),
    [items]
  );
  const tps = +(subtotal * TPS_RATE).toFixed(2);
  const tvq = +(subtotal * TVQ_RATE).toFixed(2);
  const total = +(subtotal + tps + tvq).toFixed(2);

  const metaDirty =
    s !== null &&
    (title !== s.title ||
      description !== (s.description || "") ||
      isoToDateInput(s.valid_until) !== validUntil ||
      (s.notes || "") !== notes);

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

  function openSendModal() {
    if (!s) return;
    if (!sendSubject)
      setSendSubject(`Soumission ${s.reference} — ${s.title}`);
    setSendNotice(null);
    setSendOpen(true);
  }

  function previewPdf() {
    const href = `${process.env.NEXT_PUBLIC_API_BASE_URL || ""}/api/v1/soumissions/${id}/pdf`;
    window.open(href, "_blank", "noopener,noreferrer");
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
            newStatus === "sent" && !s.sent_at ? new Date().toISOString() : undefined,
          accepted_at:
            newStatus === "accepted" && !s.accepted_at
              ? new Date().toISOString()
              : undefined
        })
      });
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

  async function addItem() {
    setItemBusy("new");
    try {
      const res = await authedFetch(`/api/v1/soumissions/${id}/items`, {
        method: "POST",
        body: JSON.stringify({
          position: items.length,
          description: "Nouvel item",
          unit: "unité",
          quantity: 1,
          unit_price: 0
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

            <section className="mt-8 rounded-xl border border-brand-800 bg-brand-900">
              <div className="flex items-center justify-between border-b border-brand-800 px-5 py-4">
                <h2 className="text-sm font-semibold uppercase tracking-wider text-accent-500">
                  Items de la soumission
                </h2>
                <button
                  type="button"
                  onClick={addItem}
                  disabled={itemBusy === "new"}
                  className="btn-accent text-xs"
                >
                  {itemBusy === "new" ? (
                    <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <Plus className="mr-1.5 h-3.5 w-3.5" />
                  )}
                  Ajouter un item
                </button>
              </div>

              {items.length === 0 ? (
                <p className="px-5 py-10 text-center text-sm text-white/50">
                  Aucun item. Cliquez « Ajouter un item » pour commencer.
                </p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead className="border-b border-brand-800 text-xs uppercase tracking-wider text-white/50">
                      <tr>
                        <th className="px-5 py-3 text-left font-semibold">Description</th>
                        <th className="px-3 py-3 text-right font-semibold">Qté</th>
                        <th className="px-3 py-3 text-left font-semibold">Unité</th>
                        <th className="px-3 py-3 text-right font-semibold">Prix unit.</th>
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

                <div>
                  <label htmlFor="description" className="label">Description</label>
                  <textarea
                    id="description"
                    rows={6}
                    value={description}
                    onChange={(e) => setDescription(e.target.value)}
                    className="input"
                  />
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

                <div>
                  <label htmlFor="notes" className="label">Notes internes</label>
                  <textarea
                    id="notes"
                    rows={4}
                    value={notes}
                    onChange={(e) => setNotes(e.target.value)}
                    placeholder="Notes privées non visibles par le client."
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

  useEffect(() => {
    setDescription(item.description);
    setUnit(item.unit || "");
    setQuantity(String(item.quantity));
    setUnitPrice(String(item.unit_price));
  }, [item.id, item.description, item.unit, item.quantity, item.unit_price]);

  const computedTotal = useMemo(
    () => +(Number(quantity || 0) * Number(unitPrice || 0)).toFixed(2),
    [quantity, unitPrice]
  );

  function commit(field: keyof Item) {
    if (field === "description" && description !== item.description) {
      onPatch({ description: description.trim() || item.description });
    } else if (field === "unit" && unit !== (item.unit || "")) {
      onPatch({ unit: unit.trim() || null });
    } else if (field === "quantity" && Number(quantity) !== Number(item.quantity)) {
      onPatch({ quantity: Number(quantity) || 0 });
    } else if (field === "unit_price" && Number(unitPrice) !== Number(item.unit_price)) {
      onPatch({ unit_price: Number(unitPrice) || 0 });
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
      <td className="px-3 py-3 w-24">
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
      <td className="px-3 py-3 w-24">
        <input
          type="text"
          value={unit}
          onChange={(e) => setUnit(e.target.value)}
          onBlur={() => commit("unit")}
          placeholder="—"
          className="w-full rounded-md border border-transparent bg-transparent px-2 py-1.5 text-sm text-white placeholder:text-white/30 focus:border-brand-700 focus:outline-none"
        />
      </td>
      <td className="px-3 py-3 w-32">
        <input
          type="number"
          step="0.01"
          min="0"
          value={unitPrice}
          onChange={(e) => setUnitPrice(e.target.value)}
          onBlur={() => commit("unit_price")}
          className="w-full rounded-md border border-transparent bg-transparent px-2 py-1.5 text-right text-sm text-white focus:border-brand-700 focus:outline-none"
        />
      </td>
      <td className="px-3 py-3 w-32 whitespace-nowrap text-right text-sm font-semibold text-white">
        {fmtMoney(computedTotal)}
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
