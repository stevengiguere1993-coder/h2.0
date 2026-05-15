"use client";

import { useEffect, useMemo, useState } from "react";
import { useParams } from "next/navigation";
import {
  ArrowLeft,
  FileText,
  Loader2,
  Plus,
  Trash2,
  UserPlus
} from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { useConfirm } from "@/components/confirm-dialog";
import { Link } from "@/i18n/navigation";
import { authedFetch } from "@/lib/auth";
import { useDevlogLayout } from "../../layout";

type Lead = {
  id: number;
  name: string;
  company: string | null;
  email: string | null;
  phone: string | null;
  source: string;
  status: string;
  position: number;
  project_summary: string | null;
  budget_range: string | null;
  notes: string | null;
  client_id: number | null;
  created_at: string;
  updated_at: string;
};

type Soumission = {
  id: number;
  title: string;
  amount: number | null;
  status: string;
  created_at: string;
};

const STATUS_OPTIONS = [
  { key: "nouveau", label: "Nouveau" },
  { key: "contacte", label: "Contacté" },
  { key: "rdv", label: "Rendez-vous" },
  { key: "presentation", label: "Présentation" },
  { key: "soumission", label: "Soumission" },
  { key: "gagne", label: "Gagné" },
  { key: "perdu", label: "Perdu" }
];

const STATUS_CLS: Record<string, string> = {
  nouveau: "bg-white/5 text-white/60",
  contacte: "bg-blue-500/15 text-blue-300",
  rdv: "bg-violet-500/15 text-violet-300",
  presentation: "bg-amber-500/15 text-amber-300",
  soumission: "bg-orange-500/15 text-orange-300",
  gagne: "bg-emerald-500/15 text-emerald-300",
  perdu: "bg-rose-500/15 text-rose-300"
};

const SOUM_CLS: Record<string, string> = {
  brouillon: "bg-white/5 text-white/60",
  envoyee: "bg-blue-500/15 text-blue-300",
  acceptee: "bg-emerald-500/15 text-emerald-300",
  refusee: "bg-rose-500/15 text-rose-300",
  expiree: "bg-amber-500/15 text-amber-300"
};

function fmtAmount(n: number | null): string {
  if (n == null) return "—";
  return n.toLocaleString("fr-CA", {
    style: "currency",
    currency: "CAD",
    maximumFractionDigits: 0
  });
}

export default function DevlogLeadDetailPage() {
  const { onOpenSidebar } = useDevlogLayout();
  const params = useParams<{ id: string }>();
  const leadId = Number(params?.id);
  const confirm = useConfirm();

  const [lead, setLead] = useState<Lead | null>(null);
  const [soumissions, setSoumissions] = useState<Soumission[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Form draft (inline edit).
  const [name, setName] = useState("");
  const [company, setCompany] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [source, setSource] = useState("interne");
  const [statusStr, setStatusStr] = useState("nouveau");
  const [projectSummary, setProjectSummary] = useState("");
  const [budgetRange, setBudgetRange] = useState("");
  const [notes, setNotes] = useState("");

  async function loadAll() {
    try {
      const [lr, sr] = await Promise.all([
        authedFetch(`/api/v1/devlog/leads/${leadId}`),
        authedFetch(`/api/v1/devlog/leads/${leadId}/soumissions`)
      ]);
      if (!lr.ok) throw new Error("Lead introuvable");
      const data = (await lr.json()) as Lead;
      setLead(data);
      setName(data.name);
      setCompany(data.company ?? "");
      setEmail(data.email ?? "");
      setPhone(data.phone ?? "");
      setSource(data.source);
      setStatusStr(data.status);
      setProjectSummary(data.project_summary ?? "");
      setBudgetRange(data.budget_range ?? "");
      setNotes(data.notes ?? "");
      if (sr.ok) setSoumissions((await sr.json()) as Soumission[]);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erreur");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (Number.isFinite(leadId)) void loadAll();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [leadId]);

  const isDirty = useMemo(() => {
    if (!lead) return false;
    return (
      name !== lead.name ||
      company !== (lead.company ?? "") ||
      email !== (lead.email ?? "") ||
      phone !== (lead.phone ?? "") ||
      source !== lead.source ||
      statusStr !== lead.status ||
      projectSummary !== (lead.project_summary ?? "") ||
      budgetRange !== (lead.budget_range ?? "") ||
      notes !== (lead.notes ?? "")
    );
  }, [lead, name, company, email, phone, source, statusStr, projectSummary, budgetRange, notes]);

  async function save() {
    if (!isDirty) return;
    setSaving(true);
    try {
      const r = await authedFetch(`/api/v1/devlog/leads/${leadId}`, {
        method: "PATCH",
        body: JSON.stringify({
          name: name.trim(),
          company: company.trim() || null,
          email: email.trim() || null,
          phone: phone.trim() || null,
          source,
          status: statusStr,
          project_summary: projectSummary.trim() || null,
          budget_range: budgetRange.trim() || null,
          notes: notes.trim() || null
        })
      });
      if (!r.ok) throw new Error();
      setLead(await r.json());
    } catch {
      setError("Enregistrement impossible");
    } finally {
      setSaving(false);
    }
  }

  async function convertToClient() {
    const ok = await confirm({
      title: "Convertir en client ?",
      description:
        "Crée un client à partir de ce lead. Le lead passera en « Gagné ».",
      confirmLabel: "Convertir"
    });
    if (!ok) return;
    try {
      const r = await authedFetch(
        `/api/v1/devlog/leads/${leadId}/convert`,
        { method: "POST" }
      );
      if (!r.ok) throw new Error();
      await loadAll();
    } catch {
      setError("Conversion impossible");
    }
  }

  async function createSoumission() {
    const title = window.prompt("Titre de la soumission ?");
    if (!title || !title.trim()) return;
    try {
      const r = await authedFetch("/api/v1/devlog/soumissions", {
        method: "POST",
        body: JSON.stringify({
          title: title.trim(),
          lead_id: leadId,
          client_id: lead?.client_id ?? null,
          status: "brouillon"
        })
      });
      if (!r.ok) throw new Error();
      const created = (await r.json()) as { id: number };
      window.location.href = `/dev-logiciel/soumissions/${created.id}`;
    } catch {
      setError("Création soumission impossible");
    }
  }

  async function deleteLead() {
    const ok = await confirm({
      title: "Supprimer ce lead ?",
      description: "Cette action est irréversible.",
      confirmLabel: "Supprimer",
      destructive: true
    });
    if (!ok) return;
    try {
      const r = await authedFetch(`/api/v1/devlog/leads/${leadId}`, {
        method: "DELETE"
      });
      if (!r.ok) throw new Error();
      window.location.href = "/dev-logiciel/leads";
    } catch {
      setError("Suppression impossible");
    }
  }

  const inputCls = "input text-sm";

  return (
    <div className="min-h-screen bg-brand-950">
      <AppTopbar
        breadcrumbs={[
          { label: "Développement logiciel", href: "/dev-logiciel" as any },
          { label: "CRM", href: "/dev-logiciel/leads" as any },
          { label: lead?.name ?? `Lead #${leadId}` }
        ]}
        onOpenSidebar={onOpenSidebar}
      />

      <div className="mx-auto max-w-5xl px-4 py-5 lg:px-6">
        <div className="mb-4">
          <Link
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            href={"/dev-logiciel/leads" as any}
            className="inline-flex items-center gap-1.5 text-xs text-white/50 hover:text-white"
          >
            <ArrowLeft className="h-3 w-3" /> Retour au pipeline
          </Link>
        </div>

        {error ? (
          <div className="mb-3 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-300">
            {error}
          </div>
        ) : null}

        {loading ? (
          <div className="mt-10 flex justify-center">
            <Loader2 className="h-6 w-6 animate-spin text-blue-500" />
          </div>
        ) : !lead ? (
          <p className="text-center text-sm text-white/40">Lead introuvable.</p>
        ) : (
          <>
            {/* Header */}
            <header className="mb-5 flex flex-wrap items-start justify-between gap-3">
              <div>
                <h1 className="text-2xl font-bold text-white">{lead.name}</h1>
                <p className="mt-1 flex flex-wrap items-center gap-2 text-xs text-white/50">
                  {lead.company ? <span>{lead.company}</span> : null}
                  <span
                    className={`rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${
                      STATUS_CLS[lead.status] ?? "bg-white/5 text-white/50"
                    }`}
                  >
                    {STATUS_OPTIONS.find((s) => s.key === lead.status)
                      ?.label ?? lead.status}
                  </span>
                  <span className="rounded bg-white/5 px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-white/40">
                    {lead.source}
                  </span>
                  {lead.client_id ? (
                    <Link
                      // eslint-disable-next-line @typescript-eslint/no-explicit-any
                      href={`/dev-logiciel/clients/${lead.client_id}` as any}
                      className="rounded bg-emerald-500/15 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-emerald-300 hover:bg-emerald-500/25"
                    >
                      ✓ Client #{lead.client_id}
                    </Link>
                  ) : null}
                </p>
              </div>
              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  onClick={createSoumission}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-blue-500/40 bg-blue-500/10 px-3 py-1.5 text-xs font-semibold text-blue-300 hover:bg-blue-500/20"
                >
                  <FileText className="h-3.5 w-3.5" />
                  Nouvelle soumission
                </button>
                {!lead.client_id ? (
                  <button
                    type="button"
                    onClick={convertToClient}
                    className="inline-flex items-center gap-1.5 rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-3 py-1.5 text-xs font-semibold text-emerald-300 hover:bg-emerald-500/20"
                  >
                    <UserPlus className="h-3.5 w-3.5" />
                    Convertir en client
                  </button>
                ) : null}
                <button
                  type="button"
                  onClick={deleteLead}
                  title="Supprimer le lead"
                  className="rounded-lg border border-rose-500/40 bg-rose-500/10 p-1.5 text-rose-300 hover:bg-rose-500/20"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </div>
            </header>

            <div className="grid gap-4 lg:grid-cols-3">
              {/* Colonne principale : édition */}
              <section className="lg:col-span-2 space-y-4">
                <div className="rounded-2xl border border-brand-800 bg-brand-900 p-5">
                  <h2 className="mb-3 text-sm font-bold text-white">
                    Informations
                  </h2>
                  <div className="space-y-3">
                    <Field label="Nom *">
                      <input
                        value={name}
                        onChange={(e) => setName(e.target.value)}
                        className={inputCls}
                      />
                    </Field>
                    <Field label="Entreprise">
                      <input
                        value={company}
                        onChange={(e) => setCompany(e.target.value)}
                        className={inputCls}
                      />
                    </Field>
                    <div className="grid grid-cols-2 gap-3">
                      <Field label="Courriel">
                        <input
                          value={email}
                          onChange={(e) => setEmail(e.target.value)}
                          className={inputCls}
                        />
                      </Field>
                      <Field label="Téléphone">
                        <input
                          value={phone}
                          onChange={(e) => setPhone(e.target.value)}
                          className={inputCls}
                        />
                      </Field>
                    </div>
                    <div className="grid grid-cols-2 gap-3">
                      <Field label="Étape">
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
                      <Field label="Source">
                        <select
                          value={source}
                          onChange={(e) => setSource(e.target.value)}
                          className={inputCls}
                        >
                          <option value="interne">Interne</option>
                          <option value="web">Web</option>
                        </select>
                      </Field>
                    </div>
                    <Field label="Budget estimé">
                      <input
                        value={budgetRange}
                        onChange={(e) => setBudgetRange(e.target.value)}
                        className={inputCls}
                        placeholder="ex. 10 000 $ - 25 000 $"
                      />
                    </Field>
                    <Field label="Projet souhaité">
                      <textarea
                        value={projectSummary}
                        onChange={(e) => setProjectSummary(e.target.value)}
                        rows={3}
                        className={inputCls}
                      />
                    </Field>
                    <Field label="Notes internes">
                      <textarea
                        value={notes}
                        onChange={(e) => setNotes(e.target.value)}
                        rows={4}
                        className={inputCls}
                      />
                    </Field>
                  </div>
                  {isDirty ? (
                    <div className="mt-4 flex items-center justify-end gap-2">
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
                </div>
              </section>

              {/* Colonne secondaire : soumissions liées */}
              <section className="space-y-4">
                <div className="rounded-2xl border border-brand-800 bg-brand-900 p-5">
                  <div className="mb-3 flex items-center justify-between">
                    <h2 className="text-sm font-bold text-white">
                      Soumissions
                    </h2>
                    <button
                      type="button"
                      onClick={createSoumission}
                      title="Nouvelle soumission"
                      className="rounded-md p-1 text-white/40 hover:bg-brand-800 hover:text-white"
                    >
                      <Plus className="h-3.5 w-3.5" />
                    </button>
                  </div>
                  {soumissions.length === 0 ? (
                    <p className="text-xs text-white/40">
                      Aucune soumission pour ce lead.
                    </p>
                  ) : (
                    <ul className="space-y-1.5">
                      {soumissions.map((s) => (
                        <li key={s.id}>
                          <Link
                            // eslint-disable-next-line @typescript-eslint/no-explicit-any
                            href={`/dev-logiciel/soumissions/${s.id}` as any}
                            className="flex items-center justify-between gap-2 rounded-lg border border-brand-800 bg-brand-950 px-3 py-2 hover:border-blue-500/40"
                          >
                            <div className="min-w-0">
                              <p className="truncate text-xs font-semibold text-white">
                                {s.title}
                              </p>
                              <p className="text-[10px] text-white/40">
                                {fmtAmount(s.amount)}
                              </p>
                            </div>
                            <span
                              className={`flex-shrink-0 rounded px-1.5 py-0.5 text-[9px] uppercase tracking-wide ${
                                SOUM_CLS[s.status] ?? "bg-white/5 text-white/50"
                              }`}
                            >
                              {s.status}
                            </span>
                          </Link>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>

                <div className="rounded-2xl border border-brand-800 bg-brand-900 p-5">
                  <h2 className="mb-2 text-sm font-bold text-white">Métadonnées</h2>
                  <dl className="space-y-1 text-xs text-white/50">
                    <div className="flex justify-between gap-2">
                      <dt>Créé</dt>
                      <dd className="text-right text-white/70">
                        {new Date(lead.created_at).toLocaleString("fr-CA")}
                      </dd>
                    </div>
                    <div className="flex justify-between gap-2">
                      <dt>Modifié</dt>
                      <dd className="text-right text-white/70">
                        {new Date(lead.updated_at).toLocaleString("fr-CA")}
                      </dd>
                    </div>
                  </dl>
                </div>
              </section>
            </div>
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
