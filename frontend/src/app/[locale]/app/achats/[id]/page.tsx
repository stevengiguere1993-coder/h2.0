"use client";

import { useEffect, useMemo, useState } from "react";
import { useParams, useRouter as useNextRouter } from "next/navigation";
import { ArrowLeft, Loader2, Save, Trash2 } from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { ReceiptScanner } from "@/components/receipt-scanner";
import { Link } from "@/i18n/navigation";
import { useAppLayout } from "../../layout";
import { authedFetch } from "@/lib/auth";

type Achat = {
  id: number;
  reference: string;
  fournisseur_id: number | null;
  project_id: number | null;
  description: string | null;
  amount: number | string | null;
  status: string;
  ordered_at: string | null;
  received_at: string | null;
  receipt_url: string | null;
  has_receipt_image: boolean;
  receipt_image_content_type: string | null;
  notes: string | null;
  created_at: string;
};

type Project = { id: number; name: string };
type Fournisseur = { id: number; name: string };

const STATUS_LABELS: Record<string, string> = {
  draft: "Brouillon",
  ordered: "Commandé",
  received: "Reçu",
  cancelled: "Annulé"
};

function isoToDateInput(iso: string | null): string {
  if (!iso) return "";
  return iso.slice(0, 10);
}

export default function AchatDetailPage() {
  const { onOpenSidebar } = useAppLayout();
  const params = useParams<{ id: string }>();
  const id = Number(params.id);
  const router = useNextRouter();

  const [a, setA] = useState<Achat | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  const [fournisseurs, setFournisseurs] = useState<Fournisseur[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [projectId, setProjectId] = useState("");
  const [fournisseurId, setFournisseurId] = useState("");
  const [description, setDescription] = useState("");
  const [amount, setAmount] = useState("");
  const [statusStr, setStatusStr] = useState("draft");
  const [orderedAt, setOrderedAt] = useState("");
  const [receivedAt, setReceivedAt] = useState("");
  const [receiptUrl, setReceiptUrl] = useState("");
  const [notes, setNotes] = useState("");
  const [uploadBusy, setUploadBusy] = useState(false);
  const [pendingReceipt, setPendingReceipt] = useState<File | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const [aRes, pRes, frRes] = await Promise.all([
          authedFetch(`/api/v1/achats/${id}`),
          authedFetch("/api/v1/projects?limit=500"),
          authedFetch("/api/v1/fournisseurs?limit=500")
        ]);
        if (!aRes.ok) throw new Error(`http_${aRes.status}`);
        const data = (await aRes.json()) as Achat;
        if (cancelled) return;
        setA(data);
        setProjectId(data.project_id ? String(data.project_id) : "");
        setFournisseurId(
          data.fournisseur_id ? String(data.fournisseur_id) : ""
        );
        setDescription(data.description || "");
        setAmount(data.amount != null ? String(data.amount) : "");
        setStatusStr(data.status);
        setOrderedAt(isoToDateInput(data.ordered_at));
        setReceivedAt(isoToDateInput(data.received_at));
        setReceiptUrl(data.receipt_url || "");
        setNotes(data.notes || "");
        if (pRes.ok) setProjects((await pRes.json()) as Project[]);
        if (frRes.ok) setFournisseurs((await frRes.json()) as Fournisseur[]);
      } catch {
        if (!cancelled) setError("Achat introuvable.");
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
    if (!a) return false;
    return (
      projectId !== (a.project_id ? String(a.project_id) : "") ||
      fournisseurId !== (a.fournisseur_id ? String(a.fournisseur_id) : "") ||
      description !== (a.description || "") ||
      amount !== (a.amount != null ? String(a.amount) : "") ||
      statusStr !== a.status ||
      orderedAt !== isoToDateInput(a.ordered_at) ||
      receivedAt !== isoToDateInput(a.received_at) ||
      receiptUrl !== (a.receipt_url || "") ||
      notes !== (a.notes || "")
    );
  }, [
    a, projectId, fournisseurId, description, amount, statusStr,
    orderedAt, receivedAt, receiptUrl, notes
  ]);

  async function saveAll() {
    if (!a) return;
    setSaving(true);
    setError(null);
    try {
      const payload: Record<string, unknown> = {
        description: description.trim() || null,
        amount: amount ? Number(amount) : null,
        status: statusStr,
        ordered_at: orderedAt ? new Date(orderedAt).toISOString() : null,
        received_at: receivedAt ? new Date(receivedAt).toISOString() : null,
        receipt_url: receiptUrl.trim() || null,
        notes: notes.trim() || null
      };
      const res = await authedFetch(`/api/v1/achats/${id}`, {
        method: "PATCH",
        body: JSON.stringify(payload)
      });
      if (!res.ok) throw new Error();
      setA((await res.json()) as Achat);
    } catch {
      setError("Sauvegarde échouée.");
    } finally {
      setSaving(false);
    }
  }

  async function uploadReceipt(file: File) {
    if (!a) return;
    setUploadBusy(true);
    setError(null);
    try {
      const fd = new FormData();
      fd.append("file", file, file.name);
      const res = await authedFetch(`/api/v1/achats/${id}/receipt`, {
        method: "POST",
        body: fd
      });
      if (!res.ok && res.status !== 204) {
        const txt = await res.text();
        throw new Error(txt.slice(0, 240) || `http_${res.status}`);
      }
      // Reload the achat row to refresh has_receipt_image + content_type.
      const re = await authedFetch(`/api/v1/achats/${id}`);
      if (re.ok) setA((await re.json()) as Achat);
    } catch (err) {
      setError(`Upload reçu échoué : ${(err as Error).message}`);
    } finally {
      setUploadBusy(false);
    }
  }

  async function deleteReceipt() {
    if (!a) return;
    if (!confirm("Supprimer la photo / le PDF du reçu ?")) return;
    setUploadBusy(true);
    try {
      const res = await authedFetch(`/api/v1/achats/${id}/receipt`, {
        method: "DELETE"
      });
      if (!res.ok && res.status !== 204) throw new Error();
      const re = await authedFetch(`/api/v1/achats/${id}`);
      if (re.ok) setA((await re.json()) as Achat);
    } catch {
      setError("Suppression du reçu échouée.");
    } finally {
      setUploadBusy(false);
    }
  }

  async function openReceipt() {
    try {
      const res = await authedFetch(`/api/v1/achats/${id}/receipt`);
      if (!res.ok) throw new Error(`http_${res.status}`);
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      window.open(url, "_blank", "noopener,noreferrer");
      setTimeout(() => URL.revokeObjectURL(url), 60_000);
    } catch (err) {
      setError(`Ouverture reçu échouée : ${(err as Error).message}`);
    }
  }

  async function onDelete() {
    if (!a) return;
    if (!confirm(`Supprimer l'achat ${a.reference} ?`)) return;
    setDeleting(true);
    try {
      const res = await authedFetch(`/api/v1/achats/${id}`, {
        method: "DELETE"
      });
      if (!res.ok && res.status !== 204) throw new Error();
      router.replace("/app/achats");
    } catch {
      setDeleting(false);
      setError("Suppression échouée.");
    }
  }

  return (
    <>
      <AppTopbar
        breadcrumbs={[{ label: "Construction", href: "/app" }, { label: "Achats / PO" }]}
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

        {loading ? (
          <div className="flex min-h-[40vh] items-center justify-center">
            <Loader2 className="h-6 w-6 animate-spin text-accent-500" />
          </div>
        ) : error && !a ? (
          <p className="mt-6 rounded-lg border border-rose-500/40 bg-rose-500/10 px-4 py-2 text-sm text-rose-300">
            {error}
          </p>
        ) : a ? (
          <>
            <header className="mt-6 flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
              <h1 className="text-2xl font-bold text-white">{a.reference}</h1>
              <button
                type="button"
                onClick={onDelete}
                disabled={deleting}
                className="inline-flex items-center gap-2 self-start rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2.5 text-sm font-medium text-rose-300 hover:bg-rose-500/20"
              >
                {deleting ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Trash2 className="h-4 w-4" />
                )}
                Supprimer
              </button>
            </header>

            {error ? (
              <p className="mt-4 rounded-lg border border-rose-500/40 bg-rose-500/10 px-4 py-2 text-sm text-rose-300">
                {error}
              </p>
            ) : null}

            <div className="mt-6 max-w-3xl space-y-6">
              <section className="rounded-xl border border-brand-800 bg-brand-900 p-5">
                <h2 className="text-sm font-semibold uppercase tracking-wider text-accent-500">
                  Lien
                </h2>
                <div className="mt-4 grid gap-4 sm:grid-cols-2">
                  <div>
                    <label htmlFor="ap" className="label">Projet</label>
                    <select
                      id="ap"
                      value={projectId}
                      onChange={(e) => setProjectId(e.target.value)}
                      className="input"
                    >
                      <option value="">— Aucun —</option>
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
                      onChange={(e) => setFournisseurId(e.target.value)}
                      className="input"
                    >
                      <option value="">— Aucun —</option>
                      {fournisseurs.map((fr) => (
                        <option key={fr.id} value={String(fr.id)}>
                          {fr.name}
                        </option>
                      ))}
                    </select>
                  </div>
                </div>
              </section>

              <section className="rounded-xl border border-brand-800 bg-brand-900 p-5">
                <h2 className="text-sm font-semibold uppercase tracking-wider text-accent-500">
                  Détails
                </h2>
                <div className="mt-4 space-y-4">
                  <div>
                    <label htmlFor="ad" className="label">Description</label>
                    <input
                      id="ad"
                      type="text"
                      value={description}
                      onChange={(e) => setDescription(e.target.value)}
                      className="input"
                    />
                  </div>
                  <div className="grid gap-4 sm:grid-cols-3">
                    <div>
                      <label htmlFor="aamount" className="label">
                        Montant (CAD)
                      </label>
                      <input
                        id="aamount"
                        type="number"
                        step="0.01"
                        min="0"
                        value={amount}
                        onChange={(e) => setAmount(e.target.value)}
                        className="input"
                      />
                    </div>
                    <div>
                      <label htmlFor="astatus" className="label">Statut</label>
                      <select
                        id="astatus"
                        value={statusStr}
                        onChange={(e) => setStatusStr(e.target.value)}
                        className="input"
                      >
                        {Object.entries(STATUS_LABELS).map(([k, v]) => (
                          <option key={k} value={k}>{v}</option>
                        ))}
                      </select>
                    </div>
                  </div>
                  <div className="grid gap-4 sm:grid-cols-2">
                    <div>
                      <label htmlFor="aord" className="label">Commandé le</label>
                      <input
                        id="aord"
                        type="date"
                        value={orderedAt}
                        onChange={(e) => setOrderedAt(e.target.value)}
                        className="input"
                      />
                    </div>
                    <div>
                      <label htmlFor="arec" className="label">Reçu le</label>
                      <input
                        id="arec"
                        type="date"
                        value={receivedAt}
                        onChange={(e) => setReceivedAt(e.target.value)}
                        className="input"
                      />
                    </div>
                  </div>
                </div>
              </section>

              <section className="rounded-xl border border-brand-800 bg-brand-900 p-5">
                <h2 className="text-sm font-semibold uppercase tracking-wider text-accent-500">
                  Facture / reçu
                </h2>
                <p className="mt-1 text-xs text-white/50">
                  Scan avec la caméra de ton cell, ou importe un fichier
                  (JPG, PNG, WEBP, HEIC ou PDF, 15 Mo max).
                </p>

                {a.has_receipt_image ? (
                  <div className="mt-4 flex flex-wrap items-center gap-3">
                    <span className="rounded-md bg-emerald-500/15 px-2 py-1 text-xs font-semibold text-emerald-300">
                      {a.receipt_image_content_type === "application/pdf"
                        ? "PDF attaché"
                        : "Photo attachée"}
                    </span>
                    <button
                      type="button"
                      onClick={openReceipt}
                      className="btn-secondary text-xs"
                    >
                      Ouvrir
                    </button>
                    <button
                      type="button"
                      onClick={deleteReceipt}
                      disabled={uploadBusy}
                      className="inline-flex items-center gap-1 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-1.5 text-xs font-medium text-rose-300 hover:bg-rose-500/20 disabled:opacity-60"
                    >
                      Supprimer
                    </button>
                  </div>
                ) : null}
                <div className="mt-4">
                  <p className="text-xs text-white/50">
                    {a.has_receipt_image
                      ? "Remplacer la pièce jointe :"
                      : "Ajoute une pièce jointe :"}
                  </p>
                  <div className="mt-2">
                    <ReceiptScanner
                      value={pendingReceipt}
                      onChange={setPendingReceipt}
                    />
                  </div>
                  {pendingReceipt ? (
                    <button
                      type="button"
                      disabled={uploadBusy}
                      onClick={async () => {
                        await uploadReceipt(pendingReceipt);
                        setPendingReceipt(null);
                      }}
                      className="btn-accent mt-3 text-sm"
                    >
                      {uploadBusy ? (
                        <>
                          <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                          Envoi…
                        </>
                      ) : (
                        "Envoyer au dossier"
                      )}
                    </button>
                  ) : null}
                </div>

                <div className="mt-4 border-t border-brand-800 pt-4">
                  <label htmlFor="aurl" className="label">
                    Ou URL externe vers le reçu
                  </label>
                  <input
                    id="aurl"
                    type="url"
                    value={receiptUrl}
                    onChange={(e) => setReceiptUrl(e.target.value)}
                    placeholder="https://…"
                    className="input"
                  />
                </div>
              </section>

              <section className="rounded-xl border border-brand-800 bg-brand-900 p-5">
                <h2 className="text-sm font-semibold uppercase tracking-wider text-accent-500">
                  Notes
                </h2>
                <textarea
                  rows={3}
                  value={notes}
                  onChange={(e) => setNotes(e.target.value)}
                  className="input mt-3"
                />
              </section>

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
          </>
        ) : null}
      </div>
    </>
  );
}
