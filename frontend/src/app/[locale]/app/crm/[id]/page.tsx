"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter as useNextRouter } from "next/navigation";
import {
  ArrowLeft,
  Calendar,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  FileText,
  Image as ImageIcon,
  Loader2,
  Mail,
  MapPin,
  Phone,
  Ruler,
  Trash2,
  User,
  Users
} from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { FollowUpTimeline } from "@/components/follow-up-timeline";
import { MeasurementsPanel } from "@/components/measurements-panel";
import { SalesTasksPanel } from "@/components/sales-tasks-panel";
import { Link } from "@/i18n/navigation";
import { useAppLayout } from "../../layout";
import { authedFetch } from "@/lib/auth";
import { useConfirm } from "@/components/confirm-dialog";
import { formatPhone } from "@/lib/utils";

type Prospect = {
  id: number;
  name: string;
  email: string;
  phone: string | null;
  address: string | null;
  project_type: string;
  budget_range: string | null;
  message: string;
  locale: string;
  source: string | null;
  status: string;
  internal_notes: string | null;
  gdpr_consent: boolean;
  marketing_consent: boolean;
  created_at: string;
  updated_at: string;
};

const STATUS_LABELS: Record<string, string> = {
  new: "Nouveau",
  contacted: "À rappeler",
  qualified: "Qualifié",
  quoted: "Soumission envoyée",
  won: "Soumission acceptée",
  lost: "Soumission refusée",
  spam: "Spam"
};

const PROJECT_LABEL: Record<string, string> = {
  salle_bain: "Salle de bain",
  cuisine: "Cuisine",
  multilogement: "Multilogement",
  renovation_complete: "Rénovation complète",
  autre: "Autre"
};

const BUDGET_LABEL: Record<string, string> = {
  under_10k: "Moins de 10 000 $",
  "10_25": "10 000 $ – 25 000 $",
  "25_50": "25 000 $ – 50 000 $",
  "50_100": "50 000 $ – 100 000 $",
  over_100: "Plus de 100 000 $",
  unsure: "Indéterminé"
};

const TABS = [
  { id: "apercu", label: "Aperçu", icon: FileText },
  { id: "client", label: "Client", icon: User },
  { id: "rendez-vous", label: "Rendez-vous", icon: Calendar },
  { id: "mesures", label: "Mesures", icon: Ruler },
  { id: "documents", label: "Documents", icon: FileText },
  { id: "employes", label: "Employés", icon: Users },
  { id: "taches", label: "Tâches", icon: CheckCircle2 }
] as const;

type TabId = (typeof TABS)[number]["id"];

export default function ProspectDetailPage() {
  const confirm = useConfirm();
  const { onOpenSidebar } = useAppLayout();
  const params = useParams<{ id: string }>();
  const id = Number(params.id);
  const router = useNextRouter();

  const [p, setP] = useState<Prospect | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<TabId>("apercu");
  const [notes, setNotes] = useState("");
  const [savingNotes, setSavingNotes] = useState(false);
  const [deleting, setDeleting] = useState(false);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const res = await authedFetch(`/api/v1/contact/${id}`);
        if (!res.ok) throw new Error(`http_${res.status}`);
        const data = (await res.json()) as Prospect;
        if (!cancelled) {
          setP(data);
          setNotes(data.internal_notes || "");
        }
      } catch {
        if (!cancelled) setError("Prospect introuvable.");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    if (id) load();
    return () => {
      cancelled = true;
    };
  }, [id]);

  async function updateStatus(newStatus: string) {
    if (!p) return;
    const prev = p;
    setP({ ...p, status: newStatus });
    try {
      const res = await authedFetch(`/api/v1/contact/${id}`, {
        method: "PATCH",
        body: JSON.stringify({ status: newStatus })
      });
      if (!res.ok) throw new Error();
    } catch {
      setP(prev);
      setError("Mise à jour du statut échouée.");
    }
  }

  async function saveNotes() {
    if (!p) return;
    setSavingNotes(true);
    try {
      const res = await authedFetch(`/api/v1/contact/${id}`, {
        method: "PATCH",
        body: JSON.stringify({ internal_notes: notes })
      });
      if (!res.ok) throw new Error();
      const updated = (await res.json()) as Prospect;
      setP(updated);
    } catch {
      setError("Sauvegarde des notes échouée.");
    } finally {
      setSavingNotes(false);
    }
  }

  async function deleteProspect() {
    if (!p) return;
    if (!(await confirm(`Supprimer définitivement le prospect « ${p.name} » ?`))) return;
    setDeleting(true);
    try {
      const res = await authedFetch(`/api/v1/contact/${id}`, { method: "DELETE" });
      if (!res.ok) throw new Error();
      router.back();
    } catch {
      setDeleting(false);
      setError("Suppression échouée.");
    }
  }

  return (
    <>
      <AppTopbar
        breadcrumbs={[{ label: "Construction", href: "/app" }, { label: "CRM / Prospects" }]}
        onOpenSidebar={onOpenSidebar}
      />

      <div className="p-4 lg:p-6">
        <Link
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          href={"/app/crm" as any}
          className="inline-flex items-center text-sm text-white/70 hover:text-accent-500"
        >
          <ArrowLeft className="mr-1 h-4 w-4" /> Retour au pipeline
        </Link>

        {loading ? (
          <div className="flex min-h-[40vh] items-center justify-center">
            <Loader2 className="h-6 w-6 animate-spin text-accent-500" />
          </div>
        ) : error ? (
          <p className="mt-6 rounded-lg border border-rose-500/40 bg-rose-500/10 px-4 py-2 text-sm text-rose-300">
            {error}
          </p>
        ) : p ? (
          <>
            {/* Header */}
            <header className="mt-6 flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
              <div>
                <h1 className="text-2xl font-bold text-white">{p.name}</h1>
                <p className="mt-1 text-sm text-accent-500">
                  {STATUS_LABELS[p.status] || p.status}
                </p>
                <p className="mt-1 text-xs text-white/50">
                  Créé le{" "}
                  {new Date(p.created_at).toLocaleDateString("fr-CA", {
                    day: "numeric",
                    month: "long",
                    year: "numeric",
                    hour: "2-digit",
                    minute: "2-digit"
                  })}
                </p>
              </div>
              <div className="flex flex-wrap items-end gap-3">
                <div>
                  <label className="label">Statut</label>
                  <select
                    value={p.status}
                    onChange={(e) => updateStatus(e.target.value)}
                    className="input w-56"
                  >
                    {Object.entries(STATUS_LABELS).map(([k, v]) => (
                      <option key={k} value={k}>
                        {v}
                      </option>
                    ))}
                  </select>
                </div>
                <Link
                  // Prefilled with the prospect ID so the form auto-
                  // links the new soumission. eslint disable for the
                  // i18n-typed Link.
                  // eslint-disable-next-line @typescript-eslint/no-explicit-any
                  href={
                    `/app/soumissions/new?contact_request_id=${p.id}` as any
                  }
                  className="btn-accent text-sm"
                >
                  <FileText className="mr-1.5 h-4 w-4" />
                  Créer soumission
                </Link>
                <button
                  type="button"
                  onClick={deleteProspect}
                  disabled={deleting}
                  className="inline-flex items-center gap-2 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2.5 text-sm font-medium text-rose-300 transition hover:bg-rose-500/20 hover:text-rose-200 disabled:opacity-50"
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

            {/* Tabs */}
            <div className="mt-8 flex flex-wrap gap-1 border-b border-brand-800">
              {TABS.map((t) => (
                <button
                  key={t.id}
                  type="button"
                  onClick={() => setTab(t.id)}
                  className={`flex items-center gap-2 border-b-2 px-4 py-2.5 text-sm font-medium transition ${
                    tab === t.id
                      ? "border-accent-500 text-white"
                      : "border-transparent text-white/60 hover:text-white"
                  }`}
                >
                  <t.icon className="h-4 w-4" />
                  {t.label}
                </button>
              ))}
            </div>

            {/* Tab panels */}
            <div className="mt-6">
              {tab === "apercu" ? (
                <div className="grid gap-6 lg:grid-cols-3">
                  <InfoCard
                    title="Type de projet"
                    value={PROJECT_LABEL[p.project_type] || p.project_type}
                  />
                  <InfoCard
                    title="Budget approximatif"
                    value={p.budget_range ? BUDGET_LABEL[p.budget_range] || p.budget_range : "—"}
                  />
                  <InfoCard title="Source" value={p.source || "—"} />
                  <div className="lg:col-span-3 rounded-xl border border-brand-800 bg-brand-900 p-5">
                    <h3 className="text-sm font-semibold uppercase tracking-wider text-accent-500">
                      Message du client
                    </h3>
                    <p className="mt-3 whitespace-pre-wrap text-sm text-white/90">
                      {p.message || "(aucun)"}
                    </p>
                  </div>
                  <div className="lg:col-span-3 rounded-xl border border-brand-800 bg-brand-900 p-5">
                    <h3 className="text-sm font-semibold uppercase tracking-wider text-accent-500">
                      Notes internes
                    </h3>
                    <textarea
                      value={notes}
                      onChange={(e) => setNotes(e.target.value)}
                      rows={5}
                      placeholder="Notes privées sur ce prospect (non visibles par le client)…"
                      className="input mt-3"
                    />
                    <button
                      type="button"
                      onClick={saveNotes}
                      disabled={savingNotes || notes === (p.internal_notes || "")}
                      className="btn-accent mt-3 text-sm"
                    >
                      {savingNotes ? (
                        <>
                          <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                          Sauvegarde…
                        </>
                      ) : (
                        "Sauvegarder les notes"
                      )}
                    </button>
                  </div>
                </div>
              ) : null}

              {tab === "client" ? (
                <div className="grid gap-4 sm:grid-cols-2">
                  <InfoRow icon={User} label="Nom complet" value={p.name} />
                  <InfoRow icon={Mail} label="Courriel" value={p.email} />
                  <InfoRow icon={Phone} label="Téléphone" value={p.phone ? formatPhone(p.phone) : "—"} />
                  <InfoRow
                    icon={MapPin}
                    label="Adresse du projet"
                    value={p.address || "—"}
                  />
                  <InfoRow
                    icon={CheckCircle2}
                    label="Consentement marketing"
                    value={p.marketing_consent ? "Oui" : "Non"}
                  />
                  <InfoRow
                    icon={CheckCircle2}
                    label="Langue"
                    value={p.locale === "fr" ? "Français" : "Anglais"}
                  />
                  <div className="lg:col-span-3">
                    <FollowUpTimeline
                      subjectType="prospect"
                      subjectId={p.id}
                    />
                  </div>
                </div>
              ) : null}

              {tab === "rendez-vous" ? (
                <AppointmentScheduler
                  contactRequestId={p.id}
                  prospectName={p.name}
                  prospectAddress={p.address || null}
                />
              ) : null}
              {tab === "mesures" ? (
                <MeasurementsPanel
                  contactRequestId={p.id}
                  defaultAddress={p.address || null}
                />
              ) : null}
              {tab === "documents" ? (
                <ProspectDocuments contactRequestId={p.id} />
              ) : null}
              {tab === "employes" ? (
                <Placeholder label="Employés assignés — module à venir avec la phase Projets/Agenda." />
              ) : null}
              {tab === "taches" ? (
                <SalesTasksPanel contactRequestId={p.id} />
              ) : null}
            </div>
          </>
        ) : null}
      </div>
    </>
  );
}

function InfoCard({ title, value }: { title: string; value: string }) {
  return (
    <div className="rounded-xl border border-brand-800 bg-brand-900 p-5">
      <p className="text-xs font-semibold uppercase tracking-wider text-accent-500">
        {title}
      </p>
      <p className="mt-2 text-lg font-semibold text-white">{value}</p>
    </div>
  );
}

function InfoRow({
  icon: Icon,
  label,
  value
}: {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  value: string;
}) {
  return (
    <div className="rounded-lg border border-brand-800 bg-brand-900 p-4">
      <p className="flex items-center gap-2 text-xs font-medium uppercase tracking-wider text-white/50">
        <Icon className="h-3.5 w-3.5 text-accent-500" /> {label}
      </p>
      <p className="mt-1.5 break-words text-sm text-white">{value}</p>
    </div>
  );
}

function Placeholder({ label }: { label: string }) {
  return (
    <div className="rounded-xl border border-dashed border-brand-800 bg-brand-900/40 p-10 text-center">
      <p className="text-sm text-white/50">{label}</p>
    </div>
  );
}

// ---------- Prospect documents (photos uploaded with the contact form) ----

type ProspectPhoto = {
  id: number;
  content_type: string;
  filename: string | null;
  created_at: string;
};

type ProspectSoumission = {
  id: number;
  reference: string;
  title: string;
  status: string;
  total: number | string | null;
  accepted_at: string | null;
  signed_name: string | null;
  contact_request_id: number | null;
};

function DocSection({
  title,
  count,
  icon,
  defaultOpen = false,
  children
}: {
  title: string;
  count: number;
  icon: React.ReactNode;
  defaultOpen?: boolean;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="overflow-hidden rounded-xl border border-brand-800 bg-brand-900">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-2 px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-white/70 transition hover:bg-brand-950/40"
      >
        {open ? (
          <ChevronDown className="h-3.5 w-3.5 text-accent-500" />
        ) : (
          <ChevronRight className="h-3.5 w-3.5 text-white/40" />
        )}
        <span className="text-accent-500">{icon}</span>
        <span className="text-white">{title}</span>
        <span className="ml-auto rounded-full bg-white/10 px-2 py-0.5 text-[10px] text-white/70">
          {count}
        </span>
      </button>
      {open ? <div className="border-t border-brand-800 p-4">{children}</div> : null}
    </div>
  );
}

function ProspectDocuments({
  contactRequestId
}: {
  contactRequestId: number;
}) {
  const confirm = useConfirm();
  const [files, setFiles] = useState<ProspectPhoto[]>([]);
  const [soumissions, setSoumissions] = useState<ProspectSoumission[]>([]);
  const [urls, setUrls] = useState<Record<number, string>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      try {
        const [fRes, sRes] = await Promise.all([
          authedFetch(`/api/v1/contact/${contactRequestId}/photos`),
          authedFetch("/api/v1/soumissions?limit=500")
        ]);
        if (cancelled) return;
        if (fRes.ok) setFiles((await fRes.json()) as ProspectPhoto[]);
        if (sRes.ok) {
          const all = (await sRes.json()) as ProspectSoumission[];
          setSoumissions(
            all.filter((s) => s.contact_request_id === contactRequestId)
          );
        }
      } catch {
        if (!cancelled) setError("Chargement échoué.");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [contactRequestId]);

  // Split images vs. other documents based on MIME type.
  const photos = files.filter((f) => f.content_type.startsWith("image/"));
  const otherDocs = files.filter(
    (f) => !f.content_type.startsWith("image/")
  );
  const signedSoumissions = soumissions.filter(
    (s) => s.status === "accepted" || s.accepted_at
  );

  // Lazy-load blob URLs for both photos (thumbnail preview) and
  // other documents (PDF download link). The endpoint requires a
  // Bearer token, so a plain <a href> would 401 — we fetch via
  // authedFetch and create an object URL the browser can render.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      for (const f of files) {
        if (urls[f.id]) continue;
        const res = await authedFetch(
          `/api/v1/contact/${contactRequestId}/photos/${f.id}/image`
        );
        if (!res.ok) continue;
        const blob = await res.blob();
        const url = URL.createObjectURL(blob);
        if (cancelled) {
          URL.revokeObjectURL(url);
          return;
        }
        setUrls((prev) => ({ ...prev, [f.id]: url }));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [files, contactRequestId, urls]);

  useEffect(() => {
    return () => {
      for (const url of Object.values(urls)) URL.revokeObjectURL(url);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function remove(pid: number) {
    if (!(await confirm("Supprimer ce document ?"))) return;
    const res = await authedFetch(
      `/api/v1/contact/${contactRequestId}/photos/${pid}`,
      { method: "DELETE" }
    );
    if (res.ok || res.status === 204) {
      setFiles((xs) => xs.filter((x) => x.id !== pid));
    }
  }

  async function onUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const picked = Array.from(e.target.files || []);
    e.target.value = "";
    if (picked.length === 0) return;
    setUploading(true);
    setError(null);
    try {
      for (const f of picked) {
        const form = new FormData();
        form.append("file", f);
        const res = await authedFetch(
          `/api/v1/contact/${contactRequestId}/photos`,
          { method: "POST", body: form }
        );
        if (!res.ok) {
          const txt = await res.text();
          throw new Error(txt.slice(0, 240) || `http_${res.status}`);
        }
        const created = (await res.json()) as ProspectPhoto;
        setFiles((xs) => [...xs, created]);
      }
    } catch (e) {
      setError(`Envoi échoué : ${(e as Error).message}`);
    } finally {
      setUploading(false);
    }
  }

  function fmtMoney(n: number | string | null): string {
    return new Intl.NumberFormat("fr-CA", {
      style: "currency",
      currency: "CAD",
      maximumFractionDigits: 2
    }).format(Number(n || 0));
  }

  return (
    <section className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold uppercase tracking-wider text-accent-500">
            Documents du prospect
          </h3>
          <p className="mt-1 text-xs text-white/60">
            Tout ce qu&apos;on reçoit ou produit pour ce prospect, classé
            par type.
          </p>
        </div>
        <label className="inline-flex cursor-pointer items-center gap-1.5 rounded-lg border border-brand-800 bg-brand-900 px-3 py-1.5 text-xs text-white hover:border-accent-500">
          {uploading ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <ImageIcon className="h-3.5 w-3.5" />
          )}
          Ajouter un fichier
          <input
            type="file"
            accept="image/*,application/pdf"
            multiple
            hidden
            onChange={onUpload}
            disabled={uploading}
          />
        </label>
      </div>

      {error ? (
        <p className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
          {error}
        </p>
      ) : null}

      {loading ? (
        <div className="flex items-center justify-center py-8">
          <Loader2 className="h-5 w-5 animate-spin text-white/40" />
        </div>
      ) : (
        <div className="space-y-2">
          {/* ---- Photos ---- */}
          <DocSection
            title="Photos"
            count={photos.length}
            icon={<ImageIcon className="h-3.5 w-3.5" />}
            defaultOpen={false}
          >
            {photos.length === 0 ? (
              <p className="rounded-lg border border-dashed border-brand-800 bg-brand-900/40 px-4 py-6 text-center text-xs text-white/40">
                Aucune photo jointe.
              </p>
            ) : (
              <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                {photos.map((p) => (
                  <li
                    key={p.id}
                    className="group overflow-hidden rounded-xl border border-brand-800 bg-brand-900"
                  >
                    <a
                      href={urls[p.id] || "#"}
                      target="_blank"
                      rel="noreferrer"
                      className="block aspect-video w-full overflow-hidden bg-black"
                    >
                      {urls[p.id] ? (
                        // eslint-disable-next-line @next/next/no-img-element
                        <img
                          alt={p.filename || "Photo"}
                          src={urls[p.id]}
                          className="h-full w-full object-cover"
                        />
                      ) : (
                        <div className="flex h-full items-center justify-center">
                          <Loader2 className="h-4 w-4 animate-spin text-white/40" />
                        </div>
                      )}
                    </a>
                    <div className="flex items-center justify-between gap-2 p-2">
                      <div className="min-w-0 text-xs">
                        <p className="truncate text-white">
                          {p.filename || `photo-${p.id}`}
                        </p>
                        <p className="text-white/40">
                          {new Date(p.created_at).toLocaleDateString("fr-CA")}
                        </p>
                      </div>
                      <button
                        type="button"
                        onClick={() => remove(p.id)}
                        className="rounded p-1 text-white/40 hover:text-rose-300"
                        aria-label="Supprimer"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </DocSection>

          {/* ---- Soumissions signées ---- */}
          <DocSection
            title="Soumissions signées"
            count={signedSoumissions.length}
            icon={<FileText className="h-3.5 w-3.5" />}
            defaultOpen={false}
          >
            {signedSoumissions.length === 0 ? (
              <p className="rounded-lg border border-dashed border-brand-800 bg-brand-900/40 px-4 py-6 text-center text-xs text-white/40">
                Aucune soumission signée par ce prospect.
              </p>
            ) : (
              <ul className="space-y-2">
                {signedSoumissions.map((s) => (
                  <li key={s.id}>
                    <Link
                      // eslint-disable-next-line @typescript-eslint/no-explicit-any
                      href={`/app/soumissions/${s.id}` as any}
                      className="flex items-start justify-between gap-3 rounded-lg border border-emerald-500/20 bg-emerald-500/5 px-3 py-2 text-sm hover:border-emerald-500/50"
                    >
                      <div className="min-w-0">
                        <p className="truncate font-semibold text-white">
                          {s.reference} — {s.title}
                        </p>
                        <p className="text-[11px] text-white/50">
                          Signée
                          {s.signed_name ? ` par ${s.signed_name}` : ""}
                          {s.accepted_at
                            ? ` le ${new Date(s.accepted_at).toLocaleDateString("fr-CA")}`
                            : ""}
                        </p>
                      </div>
                      <span className="shrink-0 text-sm font-semibold text-emerald-300">
                        {fmtMoney(s.total)}
                      </span>
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </DocSection>

          {/* ---- Autres documents (PDF, plans, devis concurrents…) ---- */}
          <DocSection
            title="Autres documents"
            count={otherDocs.length}
            icon={<FileText className="h-3.5 w-3.5" />}
            defaultOpen={false}
          >
            {otherDocs.length === 0 ? (
              <p className="rounded-lg border border-dashed border-brand-800 bg-brand-900/40 px-4 py-6 text-center text-xs text-white/40">
                Aucun PDF ou autre document. Utilise « Ajouter un
                fichier » plus haut pour déposer un plan, un devis
                concurrent, un rapport d&apos;inspection, etc.
              </p>
            ) : (
              <ul className="space-y-1.5">
                {otherDocs.map((d) => (
                  <li
                    key={d.id}
                    className="flex items-center justify-between gap-3 rounded-lg border border-brand-800 bg-brand-950 px-3 py-2 text-sm"
                  >
                    <a
                      href={urls[d.id] || "#"}
                      target="_blank"
                      rel="noreferrer"
                      download={d.filename || `document-${d.id}`}
                      className="flex min-w-0 items-center gap-2 text-white hover:text-accent-500"
                    >
                      <FileText className="h-4 w-4 shrink-0 text-accent-500" />
                      <div className="min-w-0">
                        <p className="truncate">
                          {d.filename || `document-${d.id}`}
                        </p>
                        <p className="text-[10px] text-white/40">
                          {d.content_type} ·{" "}
                          {new Date(d.created_at).toLocaleDateString("fr-CA")}
                        </p>
                      </div>
                    </a>
                    <button
                      type="button"
                      onClick={() => remove(d.id)}
                      className="rounded p-1 text-white/40 hover:text-rose-300"
                      aria-label="Supprimer"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </DocSection>
        </div>
      )}
    </section>
  );
}

// ---------- Appointment scheduler (Phase C) ----------

type Appointment = {
  id: number;
  title: string;
  start_at: string;
  end_at: string | null;
  contact_request_id: number | null;
  assignee_id: number | null;
  event_type: string;
  confirmation_sent_at?: string | null;
};

function todayIso(): string {
  const d = new Date();
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

type Employe = { id: number; full_name: string };

function AppointmentScheduler({
  contactRequestId,
  prospectName,
  prospectAddress
}: {
  contactRequestId: number;
  prospectName: string;
  prospectAddress: string | null;
}) {
  const [past, setPast] = useState<Appointment[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [employes, setEmployes] = useState<Employe[]>([]);

  // Form state
  const [title, setTitle] = useState(`Visite — ${prospectName}`);
  const [date, setDate] = useState(todayIso());
  const [startHm, setStartHm] = useState("10:00");
  const [endHm, setEndHm] = useState("11:00");
  const [location, setLocation] = useState(prospectAddress || "");
  const [eventType, setEventType] = useState("visite");
  const [assigneeId, setAssigneeId] = useState<string>("");
  const [submitting, setSubmitting] = useState(false);
  const [success, setSuccess] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      try {
        const [agendaRes, empRes] = await Promise.all([
          authedFetch("/api/v1/agenda?limit=500"),
          authedFetch("/api/v1/employes?limit=200")
        ]);
        if (!agendaRes.ok) throw new Error();
        const all = (await agendaRes.json()) as Appointment[];
        const emps = empRes.ok ? ((await empRes.json()) as Employe[]) : [];
        if (!cancelled) {
          setPast(
            all
              .filter((a) => a.contact_request_id === contactRequestId)
              .sort(
                (a, b) =>
                  new Date(b.start_at).getTime() -
                  new Date(a.start_at).getTime()
              )
          );
          setEmployes(emps);
        }
      } catch {
        if (!cancelled) setError("Chargement des RDV échoué.");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, [contactRequestId]);

  async function submit() {
    if (!title.trim() || !date || !startHm || !endHm) {
      setError("Tous les champs sont requis.");
      return;
    }
    setSubmitting(true);
    setError(null);
    setSuccess(null);
    try {
      const startIso = new Date(`${date}T${startHm}:00`).toISOString();
      const endIso = new Date(`${date}T${endHm}:00`).toISOString();
      const res = await authedFetch("/api/v1/appointments", {
        method: "POST",
        body: JSON.stringify({
          contact_request_id: contactRequestId,
          title: title.trim(),
          start_at: startIso,
          end_at: endIso,
          location: location.trim() || null,
          event_type: eventType,
          assignee_id: assigneeId ? Number(assigneeId) : null
        })
      });
      if (!res.ok) {
        const txt = await res.text();
        throw new Error(txt.slice(0, 240));
      }
      const created = (await res.json()) as Appointment;
      setPast((xs) => [created, ...xs]);
      setSuccess(
        "RDV créé. Un courriel de confirmation a été envoyé au prospect."
      );
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="space-y-4">
      <section className="rounded-2xl border border-accent-500/30 bg-accent-500/5 p-5">
        <h3 className="text-sm font-semibold uppercase tracking-wider text-accent-500">
          Planifier un rendez-vous
        </h3>
        <p className="mt-1 text-xs text-white/60">
          Le prospect reçoit un courriel de confirmation immédiat + un
          rappel 24 h avant.
        </p>

        <div className="mt-4 grid gap-3 sm:grid-cols-2">
          <div className="sm:col-span-2">
            <label className="label">Titre</label>
            <input
              type="text"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              className="input"
            />
          </div>
          <div>
            <label className="label">Type</label>
            <select
              value={eventType}
              onChange={(e) => setEventType(e.target.value)}
              className="input"
            >
              <option value="visite">Visite / soumission</option>
              <option value="reunion">Réunion</option>
              <option value="livraison">Livraison</option>
              <option value="chantier">Chantier</option>
            </select>
          </div>
          <div>
            <label className="label">Date</label>
            <input
              type="date"
              value={date}
              onChange={(e) => setDate(e.target.value)}
              className="input"
            />
          </div>
          <div>
            <label className="label">Début</label>
            <input
              type="time"
              value={startHm}
              onChange={(e) => setStartHm(e.target.value)}
              className="input"
            />
          </div>
          <div>
            <label className="label">Fin</label>
            <input
              type="time"
              value={endHm}
              onChange={(e) => setEndHm(e.target.value)}
              className="input"
            />
          </div>
          <div className="sm:col-span-2">
            <label className="label">Adresse / lieu</label>
            <input
              type="text"
              value={location}
              onChange={(e) => setLocation(e.target.value)}
              placeholder="Adresse de la visite"
              className="input"
            />
          </div>
          <div className="sm:col-span-2">
            <label className="label">Assigné à</label>
            <select
              value={assigneeId}
              onChange={(e) => setAssigneeId(e.target.value)}
              className="input"
            >
              <option value="">— Personne assignée —</option>
              {employes.map((e) => (
                <option key={e.id} value={String(e.id)}>
                  {e.full_name}
                </option>
              ))}
            </select>
            <p className="mt-1 text-[11px] text-white/40">
              La personne assignée reçoit le RDV dans son calendrier
              (lien .ics personnel dans son profil) + un courriel.
            </p>
          </div>
        </div>

        {error ? (
          <p className="mt-3 text-sm text-rose-300">{error}</p>
        ) : null}
        {success ? (
          <p className="mt-3 rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-sm text-emerald-200">
            {success}
          </p>
        ) : null}

        <div className="mt-4">
          <button
            type="button"
            onClick={submit}
            disabled={submitting}
            className="btn-accent text-sm disabled:opacity-60"
          >
            {submitting ? (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            ) : null}
            Planifier + envoyer la confirmation
          </button>
        </div>
      </section>

      <section>
        <h3 className="text-xs font-semibold uppercase tracking-wider text-accent-500">
          Historique
        </h3>
        {loading ? (
          <div className="flex items-center justify-center py-6">
            <Loader2 className="h-5 w-5 animate-spin text-white/40" />
          </div>
        ) : past.length === 0 ? (
          <p className="mt-2 text-xs text-white/50">
            Aucun rendez-vous planifié.
          </p>
        ) : (
          <ul className="mt-3 space-y-2">
            {past.map((a) => (
              <li
                key={a.id}
                className="rounded-xl border border-brand-800 bg-brand-900 p-3"
              >
                <p className="text-sm font-semibold text-white">
                  {a.title}
                </p>
                <p className="mt-0.5 text-xs text-white/60">
                  {new Date(a.start_at).toLocaleString("fr-CA", {
                    weekday: "short",
                    day: "numeric",
                    month: "short",
                    year: "numeric",
                    hour: "2-digit",
                    minute: "2-digit"
                  })}
                  {a.end_at
                    ? ` → ${new Date(a.end_at).toLocaleTimeString(
                        "fr-CA",
                        { hour: "2-digit", minute: "2-digit" }
                      )}`
                    : ""}
                </p>
                <span className="mt-1 inline-flex rounded bg-white/5 px-1.5 py-0.5 text-[10px] uppercase text-white/50">
                  {a.event_type}
                </span>
                {a.assignee_id ? (
                  <span className="ml-1 inline-flex rounded bg-sky-500/15 px-1.5 py-0.5 text-[10px] text-sky-200">
                    👤{" "}
                    {employes.find((e) => e.id === a.assignee_id)
                      ?.full_name || `#${a.assignee_id}`}
                  </span>
                ) : null}
                {a.confirmation_sent_at ? (
                  <span className="ml-1 inline-flex rounded bg-emerald-500/15 px-1.5 py-0.5 text-[10px] uppercase text-emerald-300">
                    courriel envoyé
                  </span>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
