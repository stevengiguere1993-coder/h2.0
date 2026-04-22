"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter as useNextRouter } from "next/navigation";
import {
  ArrowLeft,
  Calendar,
  CheckCircle2,
  FileText,
  Loader2,
  Mail,
  MapPin,
  Phone,
  Trash2,
  User,
  Users
} from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { SalesTasksPanel } from "@/components/sales-tasks-panel";
import { Link } from "@/i18n/navigation";
import { useAppLayout } from "../../layout";
import { authedFetch } from "@/lib/auth";

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
  { id: "documents", label: "Documents", icon: FileText },
  { id: "employes", label: "Employés", icon: Users },
  { id: "taches", label: "Tâches", icon: CheckCircle2 }
] as const;

type TabId = (typeof TABS)[number]["id"];

export default function ProspectDetailPage() {
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
    if (!confirm(`Supprimer définitivement le prospect « ${p.name} » ?`)) return;
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
              <div className="flex items-end gap-3">
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
                  <InfoRow icon={Phone} label="Téléphone" value={p.phone || "—"} />
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
                </div>
              ) : null}

              {tab === "rendez-vous" ? (
                <AppointmentScheduler
                  contactRequestId={p.id}
                  prospectName={p.name}
                  prospectAddress={p.address || null}
                />
              ) : null}
              {tab === "documents" ? (
                <Placeholder label="Documents (soumissions, bons de travail, photos) — module à venir avec la phase Soumissions." />
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

  // Form state
  const [title, setTitle] = useState(`Visite — ${prospectName}`);
  const [date, setDate] = useState(todayIso());
  const [startHm, setStartHm] = useState("10:00");
  const [endHm, setEndHm] = useState("11:00");
  const [location, setLocation] = useState(prospectAddress || "");
  const [eventType, setEventType] = useState("visite");
  const [submitting, setSubmitting] = useState(false);
  const [success, setSuccess] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      try {
        // Reuse the agenda list and filter by contact_request_id.
        const res = await authedFetch("/api/v1/agenda?limit=500");
        if (!res.ok) throw new Error();
        const all = (await res.json()) as Appointment[];
        if (!cancelled)
          setPast(
            all
              .filter((a) => a.contact_request_id === contactRequestId)
              .sort(
                (a, b) =>
                  new Date(b.start_at).getTime() -
                  new Date(a.start_at).getTime()
              )
          );
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
          event_type: eventType
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
