"use client";

import { useEffect, useMemo, useState } from "react";
import { useParams, useRouter as useNextRouter } from "next/navigation";
import {
  ArrowLeft,
  CheckCircle2,
  FileText,
  Loader2,
  Mail,
  Plus,
  Save,
  Send,
  Trash2
} from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { Link } from "@/i18n/navigation";
import { useAppLayout } from "../../layout";
import { authedFetch } from "@/lib/auth";
import { useConfirm } from "@/components/confirm-dialog";

type Bon = {
  id: number;
  reference: string;
  title: string;
  description: string | null;
  project_id: number | null;
  client_id: number | null;
  amount: number | string | null;
  status: string;
  sent_to_email: string | null;
  sent_at: string | null;
  signed_at: string | null;
  signed_by_name: string | null;
  created_at: string;
};

type Item = {
  id: number;
  bon_id: number;
  position: number;
  description: string;
  unit: string | null;
  quantity: number;
  unit_price: number;
  total: number;
};

type Client = { id: number; name: string; email: string | null };

const STATUS_LABELS: Record<string, string> = {
  draft: "Brouillon",
  sent: "Envoyé",
  signed: "Signé",
  cancelled: "Annulé"
};

const STATUS_CLASS: Record<string, string> = {
  draft: "bg-white/10 text-white",
  sent: "bg-blue-500/20 text-blue-300",
  signed: "bg-emerald-500/20 text-emerald-300",
  cancelled: "bg-white/5 text-white/50"
};

function money(n: number | string | null): string {
  if (n == null || n === "") return "—";
  const num = typeof n === "string" ? Number(n) : n;
  return new Intl.NumberFormat("fr-CA", {
    style: "currency",
    currency: "CAD",
    maximumFractionDigits: 2
  }).format(num);
}

export default function BonDetailPage() {
  const confirm = useConfirm();
  const { onOpenSidebar } = useAppLayout();
  const params = useParams<{ id: string }>();
  const id = Number(params.id);
  const router = useNextRouter();

  const [b, setB] = useState<Bon | null>(null);
  const [items, setItems] = useState<Item[]>([]);
  const [client, setClient] = useState<Client | null>(null);
  const [loading, setLoading] = useState(true);
  const [itemBusy, setItemBusy] = useState<number | "new" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);

  const [sendOpen, setSendOpen] = useState(false);
  const [sendBusy, setSendBusy] = useState(false);
  const [sendNotice, setSendNotice] = useState<string | null>(null);
  const [sendTo, setSendTo] = useState("");
  const [sendSubject, setSendSubject] = useState("");
  const [sendMessage, setSendMessage] = useState("");

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      try {
        const [bRes, iRes] = await Promise.all([
          authedFetch(`/api/v1/bons-travail/${id}`),
          authedFetch(`/api/v1/bons-travail/${id}/items`)
        ]);
        if (!bRes.ok) throw new Error(`http_${bRes.status}`);
        const bd = (await bRes.json()) as Bon;
        const iData = iRes.ok ? ((await iRes.json()) as Item[]) : [];
        if (cancelled) return;
        setB(bd);
        setItems(iData);
        setSendSubject(`Bon de travail ${bd.reference} — ${bd.title}`);
        if (bd.client_id) {
          const cr = await authedFetch(`/api/v1/clients/${bd.client_id}`);
          if (cr.ok && !cancelled) {
            const cd = (await cr.json()) as Client;
            setClient(cd);
            if (cd.email) setSendTo(cd.email);
          }
        }
      } catch {
        if (!cancelled) setError("Bon introuvable.");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    if (id) load();
    return () => {
      cancelled = true;
    };
  }, [id]);

  const itemsTotal = useMemo(
    () => +items.reduce((sum, it) => sum + Number(it.total || 0), 0).toFixed(2),
    [items]
  );

  async function updateStatus(newStatus: string) {
    if (!b) return;
    const prev = b;
    setB({ ...b, status: newStatus });
    try {
      const res = await authedFetch(`/api/v1/bons-travail/${id}`, {
        method: "PATCH",
        body: JSON.stringify({ status: newStatus })
      });
      if (!res.ok) throw new Error();
      setB((await res.json()) as Bon);
    } catch {
      setB(prev);
      setError("Changement de statut échoué.");
    }
  }

  async function addItem() {
    setItemBusy("new");
    try {
      const res = await authedFetch(`/api/v1/bons-travail/${id}/items`, {
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
        `/api/v1/bons-travail/${id}/items/${item_id}`,
        { method: "PATCH", body: JSON.stringify(patch) }
      );
      if (!res.ok) throw new Error();
      const updated = (await res.json()) as Item;
      setItems((xs) => xs.map((x) => (x.id === item_id ? updated : x)));
    } catch {
      setError("Mise à jour échouée.");
    } finally {
      setItemBusy(null);
    }
  }

  async function deleteItem(item_id: number) {
    if (!(await confirm("Supprimer cet item ?"))) return;
    setItemBusy(item_id);
    try {
      const res = await authedFetch(
        `/api/v1/bons-travail/${id}/items/${item_id}`,
        { method: "DELETE" }
      );
      if (!res.ok && res.status !== 204) throw new Error();
      setItems((xs) => xs.filter((x) => x.id !== item_id));
    } catch {
      setError("Suppression échouée.");
    } finally {
      setItemBusy(null);
    }
  }

  async function previewPdf() {
    try {
      const res = await authedFetch(`/api/v1/bons-travail/${id}/pdf`);
      if (!res.ok) throw new Error(`http_${res.status}`);
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      window.open(url, "_blank", "noopener,noreferrer");
      setTimeout(() => URL.revokeObjectURL(url), 60_000);
    } catch (err) {
      setSendNotice(`PDF échoué : ${(err as Error).message}`);
    }
  }

  async function sendToClient() {
    if (!b) return;
    const to = sendTo.split(",").map((x) => x.trim()).filter(Boolean);
    if (to.length === 0) {
      setSendNotice("Adresse courriel requise.");
      return;
    }
    setSendBusy(true);
    setSendNotice(null);
    try {
      const res = await authedFetch(`/api/v1/bons-travail/${id}/send`, {
        method: "POST",
        body: JSON.stringify({
          to,
          subject: sendSubject || null,
          message: sendMessage || null
        })
      });
      if (!res.ok) {
        const txt = await res.text();
        throw new Error(txt.slice(0, 240) || `http_${res.status}`);
      }
      setB((await res.json()) as Bon);
      setSendOpen(false);
      setSendNotice(`Bon envoyé à ${to.join(", ")}.`);
    } catch (err) {
      setSendNotice(`Erreur : ${(err as Error).message}`);
    } finally {
      setSendBusy(false);
    }
  }

  async function onDelete() {
    if (!b) return;
    if (!(await confirm(`Supprimer ${b.reference} ?`))) return;
    setDeleting(true);
    try {
      const res = await authedFetch(`/api/v1/bons-travail/${id}`, {
        method: "DELETE"
      });
      if (!res.ok && res.status !== 204) throw new Error();
      router.replace("/app/bons");
    } catch {
      setDeleting(false);
      setError("Suppression échouée.");
    }
  }

  return (
    <>
      <AppTopbar
        breadcrumbs={[
          { label: "Construction", href: "/app" },
          { label: "Bons de travail", href: "/app/bons" },
          { label: b?.reference || "…" }
        ]}
        onOpenSidebar={onOpenSidebar}
      />

      <div className="p-4 lg:p-6">
        <Link
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          href={"/app/bons" as any}
          className="inline-flex items-center text-sm text-white/70 hover:text-accent-500"
        >
          <ArrowLeft className="mr-1 h-4 w-4" /> Retour aux bons
        </Link>

        {loading ? (
          <div className="flex min-h-[40vh] items-center justify-center">
            <Loader2 className="h-6 w-6 animate-spin text-accent-500" />
          </div>
        ) : error && !b ? (
          <p className="mt-6 rounded-lg border border-rose-500/40 bg-rose-500/10 px-4 py-2 text-sm text-rose-300">
            {error}
          </p>
        ) : b ? (
          <>
            <header className="mt-6 flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
              <div>
                <h1 className="text-2xl font-bold text-white">{b.reference}</h1>
                <p className="mt-1 text-sm text-white/70">{b.title}</p>
                {client ? (
                  <p className="mt-1 text-xs text-white/50">
                    Client : {client.name}
                  </p>
                ) : null}
              </div>
              <div className="flex flex-wrap items-center gap-3">
                <span
                  className={`rounded-md px-3 py-1.5 text-xs font-semibold ${
                    STATUS_CLASS[b.status] || "bg-white/10 text-white"
                  }`}
                >
                  {STATUS_LABELS[b.status] || b.status}
                </span>
                <select
                  value={b.status}
                  onChange={(e) => updateStatus(e.target.value)}
                  className="input w-40"
                >
                  {Object.entries(STATUS_LABELS).map(([k, v]) => (
                    <option key={k} value={k}>
                      {v}
                    </option>
                  ))}
                </select>
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

            {b.signed_at && b.signed_by_name ? (
              <div className="mt-4 rounded-lg border border-emerald-500/40 bg-emerald-500/10 p-3 text-sm text-emerald-200">
                <CheckCircle2 className="mr-2 inline h-4 w-4" />
                Signé électroniquement par <strong>{b.signed_by_name}</strong>{" "}
                le {new Date(b.signed_at).toLocaleString("fr-CA")}
              </div>
            ) : null}

            {sendNotice ? (
              <p className={`mt-4 rounded-lg border px-4 py-2 text-sm ${
                sendNotice.startsWith("Bon envoyé")
                  ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-200"
                  : "border-amber-500/40 bg-amber-500/10 text-amber-200"
              }`}>
                {sendNotice}
              </p>
            ) : null}

            <div className="mt-6 grid gap-3 sm:grid-cols-2">
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
                onClick={() => setSendOpen(true)}
                className="flex items-start gap-3 rounded-xl border border-brand-800 bg-brand-900 p-4 text-left transition hover:border-accent-500"
              >
                <Mail className="mt-0.5 h-5 w-5 flex-shrink-0 text-accent-500" />
                <div>
                  <p className="text-sm font-semibold text-white">
                    {b.sent_at ? "Renvoyer au client" : "Envoyer au client"}
                  </p>
                  <p className="mt-0.5 text-xs text-white/60">
                    PDF + lien signature électronique.
                  </p>
                </div>
              </button>
            </div>

            <section className="mt-6 rounded-xl border border-brand-800 bg-brand-900">
              <div className="flex items-center justify-between border-b border-brand-800 px-5 py-4">
                <h2 className="text-sm font-semibold uppercase tracking-wider text-accent-500">
                  Items — montant chargé au client
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
                <p className="px-5 py-8 text-center text-sm text-white/50">
                  Aucun item — sinon laisse simplement le montant global sur
                  la fiche (c&apos;est ce que le client paiera).
                </p>
              ) : (
                <div className="divide-y divide-brand-800">
                  {items.map((it) => (
                    <ItemRow
                      key={it.id}
                      item={it}
                      busy={itemBusy === it.id}
                      onPatch={(patch) => patchItem(it.id, patch)}
                      onDelete={() => deleteItem(it.id)}
                    />
                  ))}
                </div>
              )}
              <div className="border-t border-brand-800 px-5 py-3 text-right text-sm">
                <span className="text-white/60">Total items : </span>
                <span className="font-bold text-white">{money(itemsTotal)}</span>
              </div>
            </section>
          </>
        ) : null}
      </div>

      {sendOpen && b ? (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4"
          onClick={() => (!sendBusy ? setSendOpen(false) : null)}
        >
          <div
            className="w-full max-w-xl rounded-2xl border border-brand-800 bg-brand-950 p-6"
            onClick={(e) => e.stopPropagation()}
          >
            <h3 className="text-lg font-bold text-white">Envoyer le bon</h3>
            <p className="mt-1 text-xs text-white/60">
              Le client recevra un lien pour signer en ligne.
            </p>
            <div className="mt-5 space-y-4">
              <div>
                <label htmlFor="b_to" className="label">
                  Destinataire <span className="text-rose-400">*</span>
                </label>
                <input
                  id="b_to"
                  value={sendTo}
                  onChange={(e) => setSendTo(e.target.value)}
                  className="input"
                  placeholder="client@exemple.com"
                />
              </div>
              <div>
                <label htmlFor="b_subj" className="label">Objet</label>
                <input
                  id="b_subj"
                  value={sendSubject}
                  onChange={(e) => setSendSubject(e.target.value)}
                  className="input"
                />
              </div>
              <div>
                <label htmlFor="b_msg" className="label">Message</label>
                <textarea
                  id="b_msg"
                  rows={4}
                  value={sendMessage}
                  onChange={(e) => setSendMessage(e.target.value)}
                  className="input"
                />
              </div>
            </div>
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

  function persist(field: keyof Item, value: unknown) {
    onPatch({ [field]: value } as Partial<Item>);
  }

  return (
    <div className="grid gap-2 px-5 py-3 text-sm sm:grid-cols-[1fr_80px_80px_120px_120px_32px] sm:items-center">
      <input
        type="text"
        value={description}
        onChange={(e) => setDescription(e.target.value)}
        onBlur={() => description !== item.description && persist("description", description)}
        disabled={busy}
        className="input text-sm"
      />
      <input
        type="text"
        value={unit}
        onChange={(e) => setUnit(e.target.value)}
        onBlur={() => unit !== (item.unit || "") && persist("unit", unit || null)}
        disabled={busy}
        placeholder="unité"
        className="input text-sm"
      />
      <input
        type="number"
        step="0.01"
        min="0"
        value={quantity}
        onChange={(e) => setQuantity(e.target.value)}
        onBlur={() => Number(quantity) !== item.quantity && persist("quantity", Number(quantity))}
        disabled={busy}
        className="input text-sm"
      />
      <input
        type="number"
        step="0.01"
        min="0"
        value={unitPrice}
        onChange={(e) => setUnitPrice(e.target.value)}
        onBlur={() => Number(unitPrice) !== item.unit_price && persist("unit_price", Number(unitPrice))}
        disabled={busy}
        className="input text-sm"
      />
      <span className="text-right font-semibold text-white">
        {money(computedTotal)}
      </span>
      <button
        type="button"
        onClick={onDelete}
        disabled={busy}
        className="text-rose-400 hover:text-rose-300 disabled:opacity-40"
        aria-label="Supprimer"
      >
        {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Trash2 className="h-4 w-4" />}
      </button>
    </div>
  );
}
