"use client";

import { useEffect, useMemo, useState } from "react";
import { useParams } from "next/navigation";
import {
  ArrowLeft,
  CalendarClock,
  Clock,
  FileText,
  Loader2,
  Receipt,
  Trash2,
  X
} from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { useConfirm } from "@/components/confirm-dialog";
import { Link } from "@/i18n/navigation";
import { authedFetch } from "@/lib/auth";
import { useDevlogLayout } from "../../layout";

type Project = {
  id: number;
  name: string;
  client_id: number | null;
  soumission_id: number | null;
  description: string | null;
  status: string;
  start_date: string | null;
  due_date: string | null;
  created_at: string;
  updated_at: string;
};

type RefItem = { id: number; name: string };
type SoumRef = { id: number; title: string; amount: number | null };
type Invoice = {
  id: number;
  number: string | null;
  amount: number | null;
  status: string;
  issued_date: string | null;
};
type TimeEntry = {
  id: number;
  user_id: number | null;
  work_date: string;
  hours: number;
  description: string | null;
};

type Tab = "apercu" | "heures" | "facturation" | "agenda";

const STATUS_OPTIONS = [
  { key: "planifie", label: "À planifier" },
  { key: "en_attente", label: "En attente de début" },
  { key: "en_cours", label: "En cours" },
  { key: "suspendu", label: "Suspendu" },
  { key: "livre", label: "Livré" }
];

const STATUS_CLS: Record<string, string> = {
  planifie: "bg-white/5 text-white/60",
  en_attente: "bg-violet-500/15 text-violet-300",
  en_cours: "bg-blue-500/15 text-blue-300",
  suspendu: "bg-amber-500/15 text-amber-300",
  livre: "bg-emerald-500/15 text-emerald-300"
};

const INV_CLS: Record<string, string> = {
  brouillon: "bg-white/5 text-white/60",
  envoyee: "bg-blue-500/15 text-blue-300",
  payee: "bg-emerald-500/15 text-emerald-300",
  annulee: "bg-rose-500/15 text-rose-300"
};

function fmtAmount(n: number | null): string {
  if (n == null) return "—";
  return n.toLocaleString("fr-CA", {
    style: "currency",
    currency: "CAD",
    maximumFractionDigits: 0
  });
}

export default function DevlogProjetDetailPage() {
  const { onOpenSidebar } = useDevlogLayout();
  const params = useParams<{ id: string }>();
  const projectId = Number(params?.id);
  const confirm = useConfirm();

  const [project, setProject] = useState<Project | null>(null);
  const [clients, setClients] = useState<RefItem[]>([]);
  const [soumissions, setSoumissions] = useState<SoumRef[]>([]);
  const [invoices, setInvoices] = useState<Invoice[]>([]);
  const [entries, setEntries] = useState<TimeEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("apercu");

  const [name, setName] = useState("");
  const [clientId, setClientId] = useState("");
  const [soumissionId, setSoumissionId] = useState("");
  const [description, setDescription] = useState("");
  const [statusStr, setStatusStr] = useState("planifie");
  const [startDate, setStartDate] = useState("");
  const [dueDate, setDueDate] = useState("");

  async function loadAll() {
    try {
      const [pr, cr, sr, ir, er] = await Promise.all([
        authedFetch(`/api/v1/devlog/projects/${projectId}`),
        authedFetch("/api/v1/devlog/clients"),
        authedFetch("/api/v1/devlog/soumissions"),
        authedFetch(`/api/v1/devlog/projects/${projectId}/invoices`),
        authedFetch(`/api/v1/devlog/projects/${projectId}/time-entries`)
      ]);
      if (!pr.ok) throw new Error("Projet introuvable");
      const data = (await pr.json()) as Project;
      setProject(data);
      setName(data.name);
      setClientId(data.client_id ? String(data.client_id) : "");
      setSoumissionId(data.soumission_id ? String(data.soumission_id) : "");
      setDescription(data.description ?? "");
      setStatusStr(data.status);
      setStartDate(data.start_date ?? "");
      setDueDate(data.due_date ?? "");
      if (cr.ok) setClients((await cr.json()) as RefItem[]);
      if (sr.ok) setSoumissions((await sr.json()) as SoumRef[]);
      if (ir.ok) setInvoices((await ir.json()) as Invoice[]);
      if (er.ok) setEntries((await er.json()) as TimeEntry[]);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erreur");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (Number.isFinite(projectId)) void loadAll();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId]);

  const isDirty = useMemo(() => {
    if (!project) return false;
    return (
      name !== project.name ||
      clientId !== (project.client_id ? String(project.client_id) : "") ||
      soumissionId !==
        (project.soumission_id ? String(project.soumission_id) : "") ||
      description !== (project.description ?? "") ||
      statusStr !== project.status ||
      startDate !== (project.start_date ?? "") ||
      dueDate !== (project.due_date ?? "")
    );
  }, [
    project,
    name,
    clientId,
    soumissionId,
    description,
    statusStr,
    startDate,
    dueDate
  ]);

  const totalHours = useMemo(
    () => entries.reduce((s, e) => s + (e.hours || 0), 0),
    [entries]
  );
  const totalBilled = useMemo(
    () =>
      invoices
        .filter((i) => i.status === "payee")
        .reduce((s, i) => s + (i.amount || 0), 0),
    [invoices]
  );
  const totalPending = useMemo(
    () =>
      invoices
        .filter((i) => i.status === "envoyee")
        .reduce((s, i) => s + (i.amount || 0), 0),
    [invoices]
  );

  async function save() {
    setSaving(true);
    try {
      const r = await authedFetch(`/api/v1/devlog/projects/${projectId}`, {
        method: "PATCH",
        body: JSON.stringify({
          name: name.trim(),
          client_id: clientId ? Number(clientId) : null,
          soumission_id: soumissionId ? Number(soumissionId) : null,
          description: description.trim() || null,
          status: statusStr,
          start_date: startDate || null,
          due_date: dueDate || null
        })
      });
      if (!r.ok) throw new Error();
      setProject(await r.json());
    } catch {
      setError("Enregistrement impossible");
    } finally {
      setSaving(false);
    }
  }

  async function logTime() {
    const hoursStr = window.prompt("Heures à saisir (ex: 2.5) ?");
    if (!hoursStr) return;
    const hours = Number(hoursStr);
    if (!Number.isFinite(hours) || hours <= 0) return;
    const desc = window.prompt("Description (optionnel) ?") || "";
    try {
      const r = await authedFetch("/api/v1/devlog/time-entries", {
        method: "POST",
        body: JSON.stringify({
          project_id: projectId,
          work_date: new Date().toISOString().slice(0, 10),
          hours,
          description: desc.trim() || null
        })
      });
      if (!r.ok) throw new Error();
      await loadAll();
    } catch {
      setError("Saisie d'heures impossible");
    }
  }

  async function newInvoice() {
    try {
      const r = await authedFetch("/api/v1/devlog/invoices", {
        method: "POST",
        body: JSON.stringify({
          project_id: projectId,
          client_id: project?.client_id ?? null,
          status: "brouillon"
        })
      });
      if (!r.ok) throw new Error();
      await loadAll();
    } catch {
      setError("Création facture impossible");
    }
  }

  async function deleteProject() {
    const ok = await confirm({
      title: "Supprimer ce projet ?",
      description:
        "Les heures et factures liées ne seront pas supprimées (juste désaffiliées).",
      confirmLabel: "Supprimer",
      destructive: true
    });
    if (!ok) return;
    try {
      const r = await authedFetch(`/api/v1/devlog/projects/${projectId}`, {
        method: "DELETE"
      });
      if (!r.ok) throw new Error();
      window.location.href = "/dev-logiciel/projets";
    } catch {
      setError("Suppression impossible");
    }
  }

  const clientName =
    project?.client_id != null
      ? clients.find((c) => c.id === project.client_id)?.name ?? null
      : null;

  const inputCls = "input text-sm";

  return (
    <div className="min-h-screen bg-brand-950">
      <AppTopbar
        breadcrumbs={[
          { label: "Développement logiciel", href: "/dev-logiciel" as any },
          { label: "Projets", href: "/dev-logiciel/projets" as any },
          { label: project?.name ?? `Projet #${projectId}` }
        ]}
        onOpenSidebar={onOpenSidebar}
      />

      <div className="mx-auto max-w-5xl px-4 py-5 lg:px-6">
        <div className="mb-4">
          <Link
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            href={"/dev-logiciel/projets" as any}
            className="inline-flex items-center gap-1.5 text-xs text-white/50 hover:text-white"
          >
            <ArrowLeft className="h-3 w-3" /> Retour aux projets
          </Link>
        </div>

        {error ? (
          <div className="mb-3 flex items-start justify-between gap-2 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-300">
            <span>{error}</span>
            <button type="button" onClick={() => setError(null)}>
              <X className="h-4 w-4" />
            </button>
          </div>
        ) : null}

        {loading ? (
          <div className="mt-10 flex justify-center">
            <Loader2 className="h-6 w-6 animate-spin text-blue-500" />
          </div>
        ) : !project ? (
          <p className="text-center text-sm text-white/40">Projet introuvable.</p>
        ) : (
          <>
            <header className="mb-4 flex flex-wrap items-start justify-between gap-3">
              <div>
                <h1 className="text-2xl font-bold text-white">{project.name}</h1>
                <p className="mt-1 flex flex-wrap items-center gap-2 text-xs text-white/50">
                  {clientName ? (
                    <Link
                      // eslint-disable-next-line @typescript-eslint/no-explicit-any
                      href={`/dev-logiciel/clients/${project.client_id}` as any}
                      className="text-blue-300 hover:underline"
                    >
                      {clientName}
                    </Link>
                  ) : null}
                  <span
                    className={`rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${
                      STATUS_CLS[project.status] ?? "bg-white/5 text-white/50"
                    }`}
                  >
                    {STATUS_OPTIONS.find((s) => s.key === project.status)
                      ?.label ?? project.status}
                  </span>
                  {project.start_date || project.due_date ? (
                    <span className="inline-flex items-center gap-1">
                      <CalendarClock className="h-3 w-3" />
                      {project.start_date ?? "—"} → {project.due_date ?? "—"}
                    </span>
                  ) : null}
                </p>
              </div>
              <button
                type="button"
                onClick={deleteProject}
                className="rounded-lg border border-rose-500/40 bg-rose-500/10 p-1.5 text-rose-300 hover:bg-rose-500/20"
              >
                <Trash2 className="h-3.5 w-3.5" />
              </button>
            </header>

            {/* Tabs */}
            <div className="mb-4 inline-flex rounded-lg border border-brand-800 bg-brand-900 p-0.5">
              {(
                [
                  { key: "apercu", label: "Aperçu" },
                  { key: "heures", label: "Heures" },
                  { key: "facturation", label: "Facturation" },
                  { key: "agenda", label: "Agenda" }
                ] as { key: Tab; label: string }[]
              ).map((t) => (
                <button
                  key={t.key}
                  type="button"
                  onClick={() => setTab(t.key)}
                  className={`rounded-md px-3 py-1.5 text-xs font-semibold ${
                    tab === t.key
                      ? "bg-blue-500 text-white"
                      : "text-white/60 hover:text-white"
                  }`}
                >
                  {t.label}
                </button>
              ))}
            </div>

            {/* Aperçu — édition */}
            {tab === "apercu" ? (
              <section className="rounded-2xl border border-brand-800 bg-brand-900 p-5">
                <div className="grid gap-3 sm:grid-cols-2">
                  <Field label="Nom du projet *">
                    <input
                      value={name}
                      onChange={(e) => setName(e.target.value)}
                      className={inputCls}
                    />
                  </Field>
                  <Field label="Statut">
                    <select
                      value={statusStr}
                      onChange={(e) => setStatusStr(e.target.value)}
                      className={inputCls}
                    >
                      {STATUS_OPTIONS.map((s) => (
                        <option key={s.key} value={s.key}>
                          {s.label}
                        </option>
                      ))}
                    </select>
                  </Field>
                  <Field label="Client">
                    <select
                      value={clientId}
                      onChange={(e) => setClientId(e.target.value)}
                      className={inputCls}
                    >
                      <option value="">—</option>
                      {clients.map((c) => (
                        <option key={c.id} value={c.id}>
                          {c.name}
                        </option>
                      ))}
                    </select>
                  </Field>
                  <Field label="Soumission liée">
                    <select
                      value={soumissionId}
                      onChange={(e) => setSoumissionId(e.target.value)}
                      className={inputCls}
                    >
                      <option value="">—</option>
                      {soumissions.map((s) => (
                        <option key={s.id} value={s.id}>
                          {s.title}
                        </option>
                      ))}
                    </select>
                  </Field>
                  <Field label="Début">
                    <input
                      type="date"
                      value={startDate}
                      onChange={(e) => setStartDate(e.target.value)}
                      className={inputCls}
                    />
                  </Field>
                  <Field label="Échéance">
                    <input
                      type="date"
                      value={dueDate}
                      onChange={(e) => setDueDate(e.target.value)}
                      className={inputCls}
                    />
                  </Field>
                </div>
                <div className="mt-3">
                  <Field label="Description / portée">
                    <textarea
                      value={description}
                      onChange={(e) => setDescription(e.target.value)}
                      rows={5}
                      className={inputCls}
                    />
                  </Field>
                </div>
                {isDirty ? (
                  <div className="mt-3 flex items-center justify-end gap-2">
                    <button
                      type="button"
                      onClick={() => void loadAll()}
                      className="rounded-md border border-white/15 px-3 py-1.5 text-xs text-white/60 hover:bg-brand-800"
                    >
                      Annuler
                    </button>
                    <button
                      type="button"
                      onClick={() => void save()}
                      disabled={saving}
                      className="inline-flex items-center gap-1.5 rounded-md bg-blue-500 px-3 py-1.5 text-xs font-semibold text-white hover:bg-blue-400 disabled:opacity-50"
                    >
                      {saving ? (
                        <Loader2 className="h-3 w-3 animate-spin" />
                      ) : null}
                      Enregistrer
                    </button>
                  </div>
                ) : null}

                {/* Mini-stats */}
                <div className="mt-5 grid gap-3 sm:grid-cols-3">
                  <Stat label="Heures totales" value={`${totalHours.toLocaleString("fr-CA")} h`} icon={<Clock className="h-4 w-4 text-blue-300" />} />
                  <Stat label="Facturé encaissé" value={fmtAmount(totalBilled)} icon={<Receipt className="h-4 w-4 text-emerald-300" />} />
                  <Stat label="Facturé en attente" value={fmtAmount(totalPending)} icon={<Receipt className="h-4 w-4 text-blue-300" />} />
                </div>
              </section>
            ) : null}

            {/* Heures */}
            {tab === "heures" ? (
              <section className="rounded-2xl border border-brand-800 bg-brand-900 p-5">
                <div className="mb-3 flex items-center justify-between">
                  <h2 className="text-sm font-bold text-white">
                    Heures saisies — total {totalHours} h
                  </h2>
                  <button
                    type="button"
                    onClick={logTime}
                    className="inline-flex items-center gap-1.5 rounded-md bg-blue-500 px-3 py-1.5 text-xs font-semibold text-white hover:bg-blue-400"
                  >
                    <Clock className="h-3 w-3" />
                    Saisir des heures
                  </button>
                </div>
                {entries.length === 0 ? (
                  <p className="py-4 text-center text-xs text-white/40">
                    Aucune saisie d'heures.
                  </p>
                ) : (
                  <ul className="divide-y divide-brand-800">
                    {entries.map((e) => (
                      <li key={e.id} className="flex items-center gap-3 py-2">
                        <span className="flex h-9 w-12 flex-shrink-0 flex-col items-center justify-center rounded-lg bg-blue-500/15 text-blue-300">
                          <span className="text-xs font-bold">{e.hours}</span>
                          <span className="text-[8px] uppercase">h</span>
                        </span>
                        <div className="min-w-0 flex-1">
                          <p className="text-xs text-white/80">
                            {e.work_date}
                          </p>
                          {e.description ? (
                            <p className="truncate text-[11px] text-white/40">
                              {e.description}
                            </p>
                          ) : null}
                        </div>
                      </li>
                    ))}
                  </ul>
                )}
              </section>
            ) : null}

            {/* Facturation */}
            {tab === "facturation" ? (
              <section className="rounded-2xl border border-brand-800 bg-brand-900 p-5">
                <div className="mb-3 flex items-center justify-between">
                  <h2 className="text-sm font-bold text-white">Factures du projet</h2>
                  <button
                    type="button"
                    onClick={newInvoice}
                    className="inline-flex items-center gap-1.5 rounded-md bg-blue-500 px-3 py-1.5 text-xs font-semibold text-white hover:bg-blue-400"
                  >
                    <Receipt className="h-3 w-3" />
                    Nouvelle facture
                  </button>
                </div>
                {invoices.length === 0 ? (
                  <p className="py-4 text-center text-xs text-white/40">
                    Aucune facture pour ce projet.
                  </p>
                ) : (
                  <ul className="space-y-1.5">
                    {invoices.map((i) => (
                      <li key={i.id}>
                        <div className="flex items-center justify-between gap-2 rounded-lg border border-brand-800 bg-brand-950 px-3 py-2">
                          <div className="min-w-0">
                            <p className="truncate text-xs font-semibold text-white">
                              {i.number ?? `Facture #${i.id}`}
                            </p>
                            <p className="text-[10px] text-white/40">
                              {i.issued_date ?? "—"}
                            </p>
                          </div>
                          <span className="text-xs font-semibold text-white">
                            {fmtAmount(i.amount)}
                          </span>
                          <span
                            className={`rounded px-1.5 py-0.5 text-[9px] uppercase tracking-wide ${
                              INV_CLS[i.status] ?? "bg-white/5 text-white/50"
                            }`}
                          >
                            {i.status}
                          </span>
                        </div>
                      </li>
                    ))}
                  </ul>
                )}
              </section>
            ) : null}

            {/* Agenda */}
            {tab === "agenda" ? (
              <section className="rounded-2xl border border-brand-800 bg-brand-900 p-5">
                <h2 className="mb-2 text-sm font-bold text-white">
                  Agenda du projet
                </h2>
                <p className="text-xs text-white/40">
                  À venir : vue calendrier avec jalons, rendez-vous client,
                  mises en production. Brancher avec /dev-logiciel/agenda
                  (Phase 2).
                </p>
                <div className="mt-3 rounded-lg border border-dashed border-brand-800 bg-brand-950 p-6 text-center">
                  <FileText className="mx-auto h-6 w-6 text-white/20" />
                  <p className="mt-2 text-xs text-white/40">
                    En attendant, utilise les champs Début / Échéance dans l'onglet Aperçu.
                  </p>
                </div>
              </section>
            ) : null}
          </>
        )}
      </div>
    </div>
  );
}

function Field({
  label,
  children
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-medium text-white/60">
        {label}
      </span>
      {children}
    </label>
  );
}

function Stat({
  label,
  value,
  icon
}: {
  label: string;
  value: string;
  icon: React.ReactNode;
}) {
  return (
    <div className="rounded-xl border border-brand-800 bg-brand-950 p-3">
      <div className="flex items-center justify-between">
        <p className="text-[10px] uppercase tracking-wide text-white/40">
          {label}
        </p>
        {icon}
      </div>
      <p className="mt-1 text-lg font-bold text-white">{value}</p>
    </div>
  );
}
