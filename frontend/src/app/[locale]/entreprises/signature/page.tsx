"use client";

/* Signature électronique (eSign) — liste des documents.
   Deux vues : « En cours » (brouillons + envoyés + refus) et
   « Signés » (complétés), + « Tous ». Upload d'un PDF → brouillon →
   éditeur de préparation (/entreprises/signature/[id]). */

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "@/i18n/navigation";
import {
  CheckCircle2,
  Clock,
  Eye,
  FileSignature,
  FileText,
  Loader2,
  Mail,
  Plus,
  Search,
  XCircle
} from "lucide-react";

import { authedFetch } from "@/lib/auth";
import { QGTopbar, useEntreprisesLayout } from "../layout";

type SignerLite = {
  id: number;
  first_name: string;
  last_name: string;
  email: string;
  require_sms_auth: boolean;
  sent_at: string | null;
  opened_at: string | null;
  open_count: number;
  signed_at: string | null;
  declined_at: string | null;
};

type DocumentItem = {
  id: number;
  title: string;
  status: string;
  entreprise_id: number | null;
  entreprise_name: string | null;
  filename: string;
  page_count: number;
  use_signing_order: boolean;
  sent_at: string | null;
  completed_at: string | null;
  created_at: string;
  updated_at: string | null;
  signers: SignerLite[];
};

const STATUS_LABEL: Record<string, string> = {
  brouillon: "Brouillon",
  envoye: "En attente",
  complete: "Signé",
  refuse: "Refusé",
  annule: "Annulé"
};

const STATUS_CLS: Record<string, string> = {
  brouillon: "badge-neutral",
  envoye: "badge-sky",
  complete: "badge-emerald",
  refuse: "badge-rose",
  annule: "badge-neutral"
};

type Tab = "en_cours" | "signes" | "tous";

function fmtDate(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleDateString("fr-CA", {
    day: "numeric",
    month: "short",
    year: "numeric"
  });
}

function SignerChip({ s }: { s: SignerLite }) {
  const name = `${s.first_name} ${s.last_name}`.trim();
  if (s.declined_at) {
    return (
      <span className="badge badge-rose" title={`${name} — a refusé`}>
        <XCircle className="h-3 w-3" />
        {s.first_name}
      </span>
    );
  }
  if (s.signed_at) {
    return (
      <span
        className="badge badge-emerald"
        title={`${name} — signé le ${fmtDate(s.signed_at)}`}
      >
        <CheckCircle2 className="h-3 w-3" />
        {s.first_name}
      </span>
    );
  }
  if (s.opened_at) {
    return (
      <span
        className="badge badge-amber"
        title={`${name} — ouvert ${s.open_count}× (pas encore signé)`}
      >
        <Eye className="h-3 w-3" />
        {s.first_name}
      </span>
    );
  }
  if (s.sent_at) {
    return (
      <span className="badge badge-sky" title={`${name} — invitation envoyée`}>
        <Mail className="h-3 w-3" />
        {s.first_name}
      </span>
    );
  }
  return (
    <span className="badge badge-neutral" title={`${name} — en préparation`}>
      <Clock className="h-3 w-3" />
      {s.first_name}
    </span>
  );
}

export default function SignaturePage() {
  const router = useRouter();
  const { entreprises } = useEntreprisesLayout();

  const [tab, setTab] = useState<Tab>("en_cours");
  const [docs, setDocs] = useState<DocumentItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [q, setQ] = useState("");
  const [entFilter, setEntFilter] = useState<string>("");

  const [uploadOpen, setUploadOpen] = useState(false);
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [uploadTitle, setUploadTitle] = useState("");
  const [uploadEnt, setUploadEnt] = useState<string>("");
  const [uploadBusy, setUploadBusy] = useState(false);
  const [uploadErr, setUploadErr] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams();
      if (tab !== "tous") params.set("group", tab);
      if (entFilter) params.set("entreprise_id", entFilter);
      const res = await authedFetch(
        `/api/v1/esign/documents?${params.toString()}`
      );
      if (!res.ok) throw new Error(`http_${res.status}`);
      setDocs((await res.json()) as DocumentItem[]);
    } catch {
      setError("Chargement impossible. Réessayez.");
    } finally {
      setLoading(false);
    }
  }, [tab, entFilter]);

  useEffect(() => {
    void load();
  }, [load]);

  const filtered = useMemo(() => {
    const needle = q.trim().toLowerCase();
    if (!needle) return docs;
    return docs.filter(
      (d) =>
        d.title.toLowerCase().includes(needle) ||
        d.filename.toLowerCase().includes(needle) ||
        (d.entreprise_name || "").toLowerCase().includes(needle) ||
        d.signers.some((s) =>
          `${s.first_name} ${s.last_name} ${s.email}`
            .toLowerCase()
            .includes(needle)
        )
    );
  }, [docs, q]);

  async function submitUpload(e: React.FormEvent) {
    e.preventDefault();
    if (!uploadFile) return;
    setUploadBusy(true);
    setUploadErr(null);
    try {
      const fd = new FormData();
      fd.append("file", uploadFile);
      if (uploadTitle.trim()) fd.append("title", uploadTitle.trim());
      if (uploadEnt) fd.append("entreprise_id", uploadEnt);
      const res = await authedFetch("/api/v1/esign/documents", {
        method: "POST",
        body: fd
      });
      if (!res.ok) {
        const detail = await res
          .json()
          .then((j) => j?.detail)
          .catch(() => null);
        throw new Error(
          typeof detail === "string" ? detail : `Erreur HTTP ${res.status}`
        );
      }
      const doc = (await res.json()) as DocumentItem;
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      router.push(`/entreprises/signature/${doc.id}` as any);
    } catch (err) {
      setUploadErr(
        err instanceof Error ? err.message : "Téléversement échoué."
      );
      setUploadBusy(false);
    }
  }

  const TABS: { key: Tab; label: string }[] = [
    { key: "en_cours", label: "Documents en cours" },
    { key: "signes", label: "Documents signés" },
    { key: "tous", label: "Tous" }
  ];

  return (
    <>
      <QGTopbar
        greeting="Signature"
        subtitle="Signature électronique de documents"
        rightSlot={
          <button
            type="button"
            onClick={() => {
              setUploadFile(null);
              setUploadTitle("");
              setUploadEnt("");
              setUploadErr(null);
              setUploadOpen(true);
            }}
            className="btn-accent inline-flex items-center gap-1.5 text-xs"
          >
            <Plus className="h-3.5 w-3.5" />
            Nouveau document
          </button>
        }
      />

      <div className="p-4 lg:p-6">
        {error ? (
          <div className="mb-4 rounded-lg border border-rose-500/40 bg-rose-500/10 px-4 py-3 text-sm text-rose-600">
            {error}
          </div>
        ) : null}

        {/* Onglets + filtres */}
        <div
          className="mb-4 flex flex-wrap items-center gap-2 rounded-2xl border p-3"
          style={{
            borderColor: "var(--qg-border)",
            backgroundColor: "var(--qg-card-bg)"
          }}
        >
          <div className="flex items-center gap-1">
            {TABS.map((t) => (
              <button
                key={t.key}
                type="button"
                onClick={() => setTab(t.key)}
                className={`rounded-lg px-3 py-1.5 text-xs font-medium transition ${
                  tab === t.key
                    ? "bg-[var(--qg-accent)] text-[var(--qg-accent-ink)]"
                    : "text-[var(--qg-text-muted)] hover:bg-[var(--qg-bg-alt)] hover:text-[var(--qg-text)]"
                }`}
              >
                {t.label}
              </button>
            ))}
          </div>
          <div className="ml-auto flex flex-wrap items-center gap-2">
            <select
              value={entFilter}
              onChange={(e) => setEntFilter(e.target.value)}
              className="input text-xs"
            >
              <option value="">Toutes les entreprises</option>
              {entreprises.map((ent) => (
                <option key={ent.id} value={String(ent.id)}>
                  {ent.name}
                </option>
              ))}
            </select>
            <div className="relative">
              <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-[var(--qg-text-soft)]" />
              <input
                value={q}
                onChange={(e) => setQ(e.target.value)}
                placeholder="Rechercher…"
                className="input pl-8 text-xs"
              />
            </div>
          </div>
        </div>

        {loading ? (
          <div className="flex items-center justify-center py-16">
            <Loader2 className="h-5 w-5 animate-spin text-accent-500" />
          </div>
        ) : filtered.length === 0 ? (
          <div
            className="rounded-2xl border p-10 text-center"
            style={{
              borderColor: "var(--qg-border)",
              backgroundColor: "var(--qg-card-bg)"
            }}
          >
            <FileSignature className="mx-auto h-8 w-8 text-[var(--qg-text-soft)]" />
            <p className="mt-3 text-sm text-[var(--qg-text-muted)]">
              {tab === "signes"
                ? "Aucun document signé pour l'instant."
                : "Aucun document. Téléversez un PDF pour démarrer une signature."}
            </p>
          </div>
        ) : (
          <div
            className="overflow-hidden rounded-2xl border"
            style={{
              borderColor: "var(--qg-border)",
              backgroundColor: "var(--qg-card-bg)"
            }}
          >
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr
                    className="text-left text-[10px] uppercase tracking-wider"
                    style={{ color: "var(--qg-text-soft)" }}
                  >
                    <th className="px-4 py-3 font-medium">Document</th>
                    <th className="px-4 py-3 font-medium">Entreprise</th>
                    <th className="px-4 py-3 font-medium">Signataires</th>
                    <th className="px-4 py-3 font-medium">Statut</th>
                    <th className="px-4 py-3 font-medium">Activité</th>
                  </tr>
                </thead>
                <tbody>
                  {filtered.map((d) => {
                    const done = d.signers.filter((s) => s.signed_at).length;
                    return (
                      <tr
                        key={d.id}
                        onClick={() =>
                          router.push(
                            // eslint-disable-next-line @typescript-eslint/no-explicit-any
                            `/entreprises/signature/${d.id}` as any
                          )
                        }
                        className="cursor-pointer border-b transition hover:bg-white/[0.03]"
                        style={{ borderColor: "var(--qg-border-soft)" }}
                      >
                        <td className="px-4 py-3">
                          <div className="flex items-center gap-2.5">
                            <FileText className="h-4 w-4 shrink-0 text-[var(--qg-accent)]" />
                            <div className="min-w-0">
                              <p className="truncate font-medium text-[var(--qg-text)]">
                                {d.title}
                              </p>
                              <p className="truncate text-xs text-[var(--qg-text-soft)]">
                                {d.filename} · {d.page_count} page
                                {d.page_count > 1 ? "s" : ""}
                              </p>
                            </div>
                          </div>
                        </td>
                        <td className="px-4 py-3 text-[var(--qg-text-muted)]">
                          {d.entreprise_name || "—"}
                        </td>
                        <td className="px-4 py-3">
                          {d.signers.length === 0 ? (
                            <span className="text-xs text-[var(--qg-text-soft)]">
                              À définir
                            </span>
                          ) : (
                            <div className="flex flex-wrap items-center gap-1">
                              {d.signers.map((s) => (
                                <SignerChip key={s.id} s={s} />
                              ))}
                              {d.status === "envoye" ? (
                                <span className="ml-1 text-xs text-[var(--qg-text-soft)]">
                                  {done}/{d.signers.length}
                                </span>
                              ) : null}
                            </div>
                          )}
                        </td>
                        <td className="px-4 py-3">
                          <span
                            className={`badge ${
                              STATUS_CLS[d.status] || "badge-neutral"
                            }`}
                          >
                            {STATUS_LABEL[d.status] || d.status}
                          </span>
                        </td>
                        <td className="px-4 py-3 text-xs text-[var(--qg-text-muted)]">
                          {d.status === "complete"
                            ? `Complété le ${fmtDate(d.completed_at)}`
                            : d.sent_at
                            ? `Envoyé le ${fmtDate(d.sent_at)}`
                            : `Créé le ${fmtDate(d.created_at)}`}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>

      {/* Modal téléversement */}
      {uploadOpen ? (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
          onClick={() => !uploadBusy && setUploadOpen(false)}
        >
          <form
            onSubmit={submitUpload}
            onClick={(e) => e.stopPropagation()}
            className="w-full max-w-md space-y-3 rounded-2xl border border-brand-800 bg-brand-900 p-5"
          >
            <div className="flex items-center justify-between">
              <h2 className="text-sm font-semibold text-white">
                Nouveau document à signer
              </h2>
              <button
                type="button"
                onClick={() => setUploadOpen(false)}
                className="btn-ghost btn-xs"
                disabled={uploadBusy}
              >
                ✕
              </button>
            </div>

            <label className="flex cursor-pointer flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-brand-700 bg-brand-950/60 px-4 py-8 text-center hover:border-accent-500/60">
              {uploadFile ? (
                <>
                  <FileText className="h-6 w-6 text-accent-500" />
                  <span className="text-xs font-medium text-white">
                    {uploadFile.name}
                  </span>
                  <span className="text-[11px] text-white/50">
                    {(uploadFile.size / 1024 / 1024).toFixed(1)} Mo — cliquez
                    pour remplacer
                  </span>
                </>
              ) : (
                <>
                  <Plus className="h-6 w-6 text-white/40" />
                  <span className="text-xs text-white/70">
                    Cliquez pour choisir un PDF (max 25 Mo)
                  </span>
                </>
              )}
              <input
                type="file"
                accept="application/pdf"
                className="hidden"
                disabled={uploadBusy}
                onChange={(e) => {
                  const f = e.target.files?.[0] || null;
                  setUploadFile(f);
                  if (f && !uploadTitle.trim()) {
                    setUploadTitle(f.name.replace(/\.pdf$/i, ""));
                  }
                  e.target.value = "";
                }}
              />
            </label>

            <div>
              <label className="label">Titre du document</label>
              <input
                value={uploadTitle}
                onChange={(e) => setUploadTitle(e.target.value)}
                placeholder="Ex. : Contrat de service 2026"
                className="input w-full text-xs"
              />
            </div>

            <div>
              <label className="label">Entreprise concernée</label>
              <select
                value={uploadEnt}
                onChange={(e) => setUploadEnt(e.target.value)}
                className="input w-full text-xs"
              >
                <option value="">— Aucune —</option>
                {entreprises.map((ent) => (
                  <option key={ent.id} value={String(ent.id)}>
                    {ent.name}
                  </option>
                ))}
              </select>
            </div>

            {uploadErr ? (
              <p className="text-xs text-rose-400">{uploadErr}</p>
            ) : null}

            <div className="flex justify-end gap-2 pt-1">
              <button
                type="button"
                onClick={() => setUploadOpen(false)}
                className="btn-secondary btn-sm"
                disabled={uploadBusy}
              >
                Annuler
              </button>
              <button
                type="submit"
                disabled={!uploadFile || uploadBusy}
                className="btn-accent btn-sm inline-flex items-center gap-1.5"
              >
                {uploadBusy ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : null}
                Continuer
              </button>
            </div>
          </form>
        </div>
      ) : null}
    </>
  );
}
