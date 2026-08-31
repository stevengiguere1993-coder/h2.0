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
  LayoutTemplate,
  Loader2,
  Mail,
  Plus,
  Search,
  ShieldCheck,
  Trash2,
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
  annule: "Annulé",
  expire: "Expiré"
};

const STATUS_CLS: Record<string, string> = {
  brouillon: "badge-neutral",
  envoye: "badge-sky",
  complete: "badge-emerald",
  refuse: "badge-rose",
  annule: "badge-neutral",
  expire: "badge-amber"
};

type TemplateRole = { name: string; require_sms_auth: boolean };

type TemplateItem = {
  id: number;
  title: string;
  entreprise_id: number | null;
  entreprise_name: string | null;
  filename: string;
  page_count: number;
  use_signing_order: boolean;
  roles: TemplateRole[];
  field_count: number;
  created_at: string;
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
  const [templatesOpen, setTemplatesOpen] = useState(false);
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
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => setTemplatesOpen(true)}
              className="btn-secondary inline-flex items-center gap-1.5 text-xs"
            >
              <LayoutTemplate className="h-3.5 w-3.5" />
              Modèles
            </button>
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
          </div>
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

      {templatesOpen ? (
        <TemplatesModal
          entreprises={entreprises}
          onClose={() => setTemplatesOpen(false)}
          onCreated={(id) =>
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            router.push(`/entreprises/signature/${id}` as any)
          }
        />
      ) : null}

      {/* Modal téléversement */}
      {uploadOpen ? (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
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

/* ---------- Modal modèles réutilisables ---------- */

type RoleSignerForm = {
  first_name: string;
  last_name: string;
  email: string;
  phone: string;
  require_sms_auth: boolean;
};

function TemplatesModal({
  entreprises,
  onClose,
  onCreated
}: {
  entreprises: { id: number; name: string }[];
  onClose: () => void;
  onCreated: (docId: number) => void;
}) {
  const [templates, setTemplates] = useState<TemplateItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  // Étape « utiliser un modèle »
  const [chosen, setChosen] = useState<TemplateItem | null>(null);
  const [title, setTitle] = useState("");
  const [ent, setEnt] = useState<string>("");
  const [roleSigners, setRoleSigners] = useState<RoleSignerForm[]>([]);
  const [busy, setBusy] = useState(false);

  const loadTemplates = useCallback(async () => {
    setLoading(true);
    setErr(null);
    try {
      const res = await authedFetch("/api/v1/esign/templates");
      if (!res.ok) throw new Error(`http_${res.status}`);
      setTemplates((await res.json()) as TemplateItem[]);
    } catch {
      setErr("Chargement des modèles impossible.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadTemplates();
  }, [loadTemplates]);

  function pick(t: TemplateItem) {
    setChosen(t);
    setTitle(t.title.replace(/^Modèle — /, ""));
    setEnt(t.entreprise_id ? String(t.entreprise_id) : "");
    setRoleSigners(
      t.roles.map((r) => ({
        first_name: "",
        last_name: "",
        email: "",
        phone: "",
        require_sms_auth: r.require_sms_auth
      }))
    );
    setErr(null);
  }

  async function removeTemplate(t: TemplateItem) {
    if (!window.confirm(`Supprimer le modèle « ${t.title} » ?`)) return;
    const res = await authedFetch(`/api/v1/esign/templates/${t.id}`, {
      method: "DELETE"
    });
    if (res.ok) await loadTemplates();
  }

  async function createFromTemplate(e: React.FormEvent) {
    e.preventDefault();
    if (!chosen) return;
    for (const rs of roleSigners) {
      if (rs.require_sms_auth && !rs.phone.trim()) {
        setErr(
          "Numéro de téléphone requis pour les signataires avec " +
            "authentification SMS."
        );
        return;
      }
    }
    setBusy(true);
    setErr(null);
    try {
      const res = await authedFetch(
        "/api/v1/esign/documents/from-template",
        {
          method: "POST",
          body: JSON.stringify({
            template_id: chosen.id,
            title: title.trim() || null,
            entreprise_id: ent ? Number(ent) : null,
            signers: roleSigners.map((rs, i) => ({
              first_name: rs.first_name.trim(),
              last_name: rs.last_name.trim(),
              email: rs.email.trim(),
              phone: rs.phone.trim() || null,
              require_sms_auth: rs.require_sms_auth,
              order_index: i
            }))
          })
        }
      );
      const body = await res.json().catch(() => null);
      if (!res.ok) {
        setErr(
          typeof body?.detail === "string"
            ? body.detail
            : `Erreur HTTP ${res.status}`
        );
        return;
      }
      onCreated((body as { id: number }).id);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="max-h-[85vh] w-full max-w-lg overflow-y-auto rounded-2xl border border-brand-800 bg-brand-900 p-5"
      >
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-white">
            {chosen
              ? `Nouveau document — ${chosen.title}`
              : "Modèles réutilisables"}
          </h2>
          <button type="button" onClick={onClose} className="btn-ghost btn-xs">
            ✕
          </button>
        </div>

        {err ? <p className="mb-3 text-xs text-rose-400">{err}</p> : null}

        {!chosen ? (
          loading ? (
            <div className="flex justify-center py-8">
              <Loader2 className="h-5 w-5 animate-spin text-accent-500" />
            </div>
          ) : templates.length === 0 ? (
            <p className="py-8 text-center text-xs text-white/60">
              Aucun modèle. Préparez un document (signataires + zones) puis
              cliquez « Enregistrer comme modèle » dans l&apos;éditeur.
            </p>
          ) : (
            <ul className="space-y-2">
              {templates.map((t) => (
                <li
                  key={t.id}
                  className="flex items-center justify-between gap-2 rounded-lg border border-brand-800 px-3 py-2.5"
                >
                  <div className="min-w-0">
                    <p className="truncate text-xs font-medium text-white">
                      {t.title}
                    </p>
                    <p className="truncate text-[11px] text-white/50">
                      {t.roles.length} signataire
                      {t.roles.length > 1 ? "s" : ""} · {t.field_count} zone
                      {t.field_count > 1 ? "s" : ""} · {t.page_count} page
                      {t.page_count > 1 ? "s" : ""}
                      {t.entreprise_name ? ` · ${t.entreprise_name}` : ""}
                    </p>
                  </div>
                  <div className="flex shrink-0 items-center gap-1.5">
                    <button
                      type="button"
                      onClick={() => pick(t)}
                      className="btn-accent btn-xs"
                    >
                      Utiliser
                    </button>
                    <button
                      type="button"
                      onClick={() => void removeTemplate(t)}
                      className="rounded p-1.5 text-white/40 hover:text-rose-400"
                      aria-label="Supprimer le modèle"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          )
        ) : (
          <form onSubmit={createFromTemplate} className="space-y-3">
            <div>
              <label className="label">Titre du document</label>
              <input
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                className="input w-full text-xs"
              />
            </div>
            <div>
              <label className="label">Entreprise concernée</label>
              <select
                value={ent}
                onChange={(e) => setEnt(e.target.value)}
                className="input w-full text-xs"
              >
                <option value="">— Aucune —</option>
                {entreprises.map((en) => (
                  <option key={en.id} value={String(en.id)}>
                    {en.name}
                  </option>
                ))}
              </select>
            </div>

            {chosen.roles.map((role, i) => (
              <fieldset
                key={i}
                className="space-y-2 rounded-lg border border-brand-800 p-3"
              >
                <legend className="px-1 text-[11px] font-semibold uppercase tracking-wider text-white/60">
                  {role.name}
                  {roleSigners[i]?.require_sms_auth ? (
                    <span className="ml-1.5 inline-flex items-center gap-0.5 normal-case text-emerald-400">
                      <ShieldCheck className="h-3 w-3" /> SMS
                    </span>
                  ) : null}
                </legend>
                <div className="grid grid-cols-2 gap-2">
                  <input
                    value={roleSigners[i]?.first_name || ""}
                    onChange={(e) =>
                      setRoleSigners((prev) =>
                        prev.map((x, j) =>
                          j === i ? { ...x, first_name: e.target.value } : x
                        )
                      )
                    }
                    placeholder="Prénom"
                    required
                    className="input w-full text-xs"
                  />
                  <input
                    value={roleSigners[i]?.last_name || ""}
                    onChange={(e) =>
                      setRoleSigners((prev) =>
                        prev.map((x, j) =>
                          j === i ? { ...x, last_name: e.target.value } : x
                        )
                      )
                    }
                    placeholder="Nom"
                    required
                    className="input w-full text-xs"
                  />
                </div>
                <input
                  type="email"
                  value={roleSigners[i]?.email || ""}
                  onChange={(e) =>
                    setRoleSigners((prev) =>
                      prev.map((x, j) =>
                        j === i ? { ...x, email: e.target.value } : x
                      )
                    )
                  }
                  placeholder="Courriel"
                  required
                  className="input w-full text-xs"
                />
                <div className="flex items-center gap-2">
                  <input
                    type="tel"
                    value={roleSigners[i]?.phone || ""}
                    onChange={(e) =>
                      setRoleSigners((prev) =>
                        prev.map((x, j) =>
                          j === i ? { ...x, phone: e.target.value } : x
                        )
                      )
                    }
                    placeholder="Téléphone"
                    className="input w-full text-xs"
                  />
                  <label className="flex shrink-0 items-center gap-1.5 text-[11px] text-white/70">
                    <input
                      type="checkbox"
                      checked={roleSigners[i]?.require_sms_auth || false}
                      onChange={(e) =>
                        setRoleSigners((prev) =>
                          prev.map((x, j) =>
                            j === i
                              ? { ...x, require_sms_auth: e.target.checked }
                              : x
                          )
                        )
                      }
                    />
                    Auth. SMS
                  </label>
                </div>
              </fieldset>
            ))}

            <div className="flex justify-end gap-2 pt-1">
              <button
                type="button"
                onClick={() => setChosen(null)}
                className="btn-secondary btn-sm"
                disabled={busy}
              >
                Retour
              </button>
              <button
                type="submit"
                disabled={busy}
                className="btn-accent btn-sm inline-flex items-center gap-1.5"
              >
                {busy ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : null}
                Créer le brouillon
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}
