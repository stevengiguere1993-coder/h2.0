"use client";

import { useEffect, useMemo, useState } from "react";
import { useParams, useRouter as useNextRouter } from "next/navigation";
import {
  ArrowLeft,
  Calendar,
  DollarSign,
  FileText,
  Loader2,
  MapPin,
  Save,
  Trash2
} from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { AddressInput } from "@/components/address-input";
import { Link } from "@/i18n/navigation";
import { useAppLayout } from "../../layout";
import { authedFetch } from "@/lib/auth";

type Project = {
  id: number;
  name: string;
  client_id: number | null;
  contact_request_id: number | null;
  soumission_id: number | null;
  status: string;
  address: string | null;
  description: string | null;
  notes: string | null;
  start_date: string | null;
  end_date: string | null;
  budget: number | string | null;
  created_at: string;
  updated_at: string;
};

const STATUS_LABELS: Record<string, string> = {
  planned: "Prévu",
  in_progress: "En cours",
  suspended: "Suspendu",
  delivered: "Livré"
};

const STATUS_CLASS: Record<string, string> = {
  planned: "bg-white/10 text-white",
  in_progress: "bg-blue-500/20 text-blue-300",
  suspended: "bg-amber-500/20 text-amber-300",
  delivered: "bg-emerald-500/20 text-emerald-300"
};

type TabId = "summary" | "agenda" | "bons" | "factures";

const TABS: { id: TabId; label: string }[] = [
  { id: "summary", label: "Résumé" },
  { id: "agenda", label: "Agenda" },
  { id: "bons", label: "Bons de travail" },
  { id: "factures", label: "Facturation" }
];

function fmtMoney(n: number | string | null): string {
  if (n == null || n === "") return "—";
  const num = typeof n === "string" ? Number(n) : n;
  return new Intl.NumberFormat("fr-CA", {
    style: "currency",
    currency: "CAD",
    maximumFractionDigits: 2
  }).format(num);
}

function isoToDateInput(iso: string | null): string {
  if (!iso) return "";
  return iso.slice(0, 10);
}

export default function ProjectDetailPage() {
  const { onOpenSidebar } = useAppLayout();
  const params = useParams<{ id: string }>();
  const id = Number(params.id);
  const router = useNextRouter();

  const [p, setP] = useState<Project | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [convertingToFacture, setConvertingToFacture] = useState(false);
  const [factureModalOpen, setFactureModalOpen] = useState(false);
  const [includeSoumission, setIncludeSoumission] = useState(true);
  const [soumissionPct, setSoumissionPct] = useState("100");
  const [includeHours, setIncludeHours] = useState(false);
  const [includeAchats, setIncludeAchats] = useState(false);
  const [onlyApproved, setOnlyApproved] = useState(true);
  const [dueInDays, setDueInDays] = useState("30");
  const [tab, setTab] = useState<TabId>("summary");

  // form state
  const [name, setName] = useState("");
  const [clientId, setClientId] = useState("");
  const [clients, setClients] = useState<Array<{ id: number; name: string }>>([]);
  const [address, setAddress] = useState("");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [budget, setBudget] = useState("");
  const [description, setDescription] = useState("");
  const [notes, setNotes] = useState("");

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const res = await authedFetch(`/api/v1/projects/${id}`);
        if (!res.ok) throw new Error(`http_${res.status}`);
        const data = (await res.json()) as Project;
        if (cancelled) return;
        setP(data);
        setName(data.name);
        setClientId(data.client_id ? String(data.client_id) : "");
        setAddress(data.address || "");
        setStartDate(isoToDateInput(data.start_date));
        setEndDate(isoToDateInput(data.end_date));
        setBudget(data.budget != null ? String(data.budget) : "");
        setDescription(data.description || "");
        setNotes(data.notes || "");
        // Load the client list in parallel so the selector has options.
        const cs = await authedFetch("/api/v1/clients?limit=500");
        if (cs.ok && !cancelled) {
          setClients((await cs.json()) as Array<{ id: number; name: string }>);
        }
      } catch {
        if (!cancelled) setError("Projet introuvable.");
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
    if (!p) return false;
    return (
      name !== p.name ||
      clientId !== (p.client_id ? String(p.client_id) : "") ||
      address !== (p.address || "") ||
      startDate !== isoToDateInput(p.start_date) ||
      endDate !== isoToDateInput(p.end_date) ||
      budget !== (p.budget != null ? String(p.budget) : "") ||
      description !== (p.description || "") ||
      notes !== (p.notes || "")
    );
  }, [
    p, name, clientId, address, startDate, endDate, budget, description, notes,
  ]);

  async function updateStatus(newStatus: string) {
    if (!p) return;
    const prev = p;
    setP({ ...p, status: newStatus });
    try {
      const res = await authedFetch(`/api/v1/projects/${id}`, {
        method: "PUT",
        body: JSON.stringify({ status: newStatus })
      });
      if (!res.ok) throw new Error();
      const updated = (await res.json()) as Project;
      setP(updated);
    } catch {
      setP(prev);
      setError("Changement de statut échoué.");
    }
  }

  async function saveAll() {
    if (!p) return;
    setSaving(true);
    setError(null);
    try {
      const payload: Record<string, unknown> = {
        name: name.trim(),
        client_id: clientId ? Number(clientId) : null,
        address: address.trim() || null,
        start_date: startDate || null,
        end_date: endDate || null,
        budget: budget ? Number(budget) : null,
        description: description.trim() || null,
        notes: notes.trim() || null
      };
      const res = await authedFetch(`/api/v1/projects/${id}`, {
        method: "PUT",
        body: JSON.stringify(payload)
      });
      if (!res.ok) throw new Error();
      const updated = (await res.json()) as Project;
      setP(updated);
    } catch {
      setError("Sauvegarde échouée.");
    } finally {
      setSaving(false);
    }
  }

  function openFactureModal() {
    if (!p) return;
    // Default: if the project came from a soumission, prefer prix fixe.
    setIncludeSoumission(!!p.soumission_id);
    setSoumissionPct("100");
    setIncludeHours(!p.soumission_id);
    setIncludeAchats(false);
    setOnlyApproved(true);
    setDueInDays("30");
    setFactureModalOpen(true);
  }

  async function createFacture() {
    if (!p) return;
    if (!includeSoumission && !includeHours && !includeAchats) {
      setError("Choisis au moins une source d'items.");
      return;
    }
    setConvertingToFacture(true);
    setError(null);
    try {
      const res = await authedFetch(
        `/api/v1/projects/${id}/convert-to-facture`,
        {
          method: "POST",
          body: JSON.stringify({
            include_soumission: includeSoumission,
            soumission_percentage: Math.max(
              1,
              Math.min(100, Number(soumissionPct) || 100)
            ),
            include_hours: includeHours,
            only_approved: onlyApproved,
            include_achats: includeAchats,
            due_in_days: Number(dueInDays) || 30
          })
        }
      );
      if (!res.ok) {
        const txt = await res.text();
        throw new Error(txt.slice(0, 240) || `http_${res.status}`);
      }
      const created = (await res.json()) as { id: number };
      setFactureModalOpen(false);
      router.push(`/app/facturation/${created.id}`);
    } catch (err) {
      setError(`Création facture échouée : ${(err as Error).message}`);
    } finally {
      setConvertingToFacture(false);
    }
  }

  async function onDelete() {
    if (!p) return;
    if (!confirm(`Supprimer définitivement le projet « ${p.name} » ?`)) return;
    setDeleting(true);
    try {
      const res = await authedFetch(`/api/v1/projects/${id}`, {
        method: "DELETE"
      });
      if (!res.ok) throw new Error();
      router.replace("/app/projets");
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
          { label: "Projets" },
          { label: p?.name || "…" }
        ]}
        onOpenSidebar={onOpenSidebar}
      />

      <div className="p-4 lg:p-6">
        <Link
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          href={"/app/projets" as any}
          className="inline-flex items-center text-sm text-white/70 hover:text-accent-500"
        >
          <ArrowLeft className="mr-1 h-4 w-4" /> Retour aux projets
        </Link>

        {loading ? (
          <div className="flex min-h-[40vh] items-center justify-center">
            <Loader2 className="h-6 w-6 animate-spin text-accent-500" />
          </div>
        ) : error && !p ? (
          <p className="mt-6 rounded-lg border border-rose-500/40 bg-rose-500/10 px-4 py-2 text-sm text-rose-300">
            {error}
          </p>
        ) : p ? (
          <>
            <header className="mt-6 flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
              <div>
                <h1 className="text-2xl font-bold text-white">{p.name}</h1>
                <p className="mt-1 text-xs text-white/50">
                  Créé le{" "}
                  {new Date(p.created_at).toLocaleDateString("fr-CA", {
                    day: "numeric",
                    month: "long",
                    year: "numeric"
                  })}
                </p>
              </div>
              <div className="flex flex-wrap items-center gap-3">
                <span
                  className={`rounded-md px-3 py-1.5 text-xs font-semibold ${
                    STATUS_CLASS[p.status] || "bg-white/10 text-white"
                  }`}
                >
                  {STATUS_LABELS[p.status] || p.status}
                </span>
                <select
                  value={p.status}
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

            {error ? (
              <p className="mt-4 rounded-lg border border-rose-500/40 bg-rose-500/10 px-4 py-2 text-sm text-rose-300">
                {error}
              </p>
            ) : null}

            <div className="mt-4">
              <button
                type="button"
                onClick={openFactureModal}
                className="inline-flex items-center gap-2 rounded-lg border border-accent-500/40 bg-accent-500/10 px-4 py-2.5 text-sm font-medium text-accent-200 hover:bg-accent-500/20"
              >
                <DollarSign className="h-4 w-4" />
                Créer une facture
              </button>
              <p className="mt-1 text-xs text-white/50">
                Choix des sources d&apos;items au prochain écran: soumission
                acceptée (prix fixe), heures punchées (T&amp;M), achats du
                projet.
              </p>
            </div>

            {/* Header KPIs */}
            <section className="mt-6 grid gap-3 sm:grid-cols-3">
              <Kpi
                icon={MapPin}
                label="Adresse"
                value={p.address || "Non renseignée"}
              />
              <Kpi
                icon={Calendar}
                label="Calendrier"
                value={
                  p.start_date || p.end_date
                    ? `${p.start_date || "?"} → ${p.end_date || "?"}`
                    : "Non planifié"
                }
              />
              <Kpi
                icon={DollarSign}
                label="Budget"
                value={fmtMoney(p.budget)}
              />
            </section>

            {/* Tabs */}
            <nav className="mt-8 flex gap-1 overflow-x-auto border-b border-brand-800">
              {TABS.map((t) => (
                <button
                  key={t.id}
                  type="button"
                  onClick={() => setTab(t.id)}
                  className={`px-4 py-2.5 text-sm font-medium transition ${
                    tab === t.id
                      ? "border-b-2 border-accent-500 text-white"
                      : "text-white/60 hover:text-white"
                  }`}
                >
                  {t.label}
                </button>
              ))}
            </nav>

            <div className="mt-6">
              {tab === "summary" ? (
                <SummaryTab
                  name={name}
                  onName={setName}
                  clientId={clientId}
                  onClientId={setClientId}
                  clients={clients}
                  address={address}
                  onAddress={setAddress}
                  startDate={startDate}
                  onStartDate={setStartDate}
                  endDate={endDate}
                  onEndDate={setEndDate}
                  budget={budget}
                  onBudget={setBudget}
                  description={description}
                  onDescription={setDescription}
                  notes={notes}
                  onNotes={setNotes}
                  dirty={dirty}
                  saving={saving}
                  onSave={saveAll}
                />
              ) : (
                <PlaceholderTab
                  label={TABS.find((t) => t.id === tab)?.label || ""}
                />
              )}
            </div>
          </>
        ) : null}
      </div>

      {factureModalOpen && p ? (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4"
          onClick={() => (!convertingToFacture ? setFactureModalOpen(false) : null)}
        >
          <div
            className="w-full max-w-lg rounded-2xl border border-brand-800 bg-brand-950 p-6 shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          >
            <h3 className="text-lg font-bold text-white">Créer une facture</h3>
            <p className="mt-1 text-xs text-white/60">
              Sélectionne les sources d&apos;items à inclure. Tu pourras
              ensuite ajuster manuellement sur la fiche facture.
            </p>

            <div className="mt-5 space-y-3">
              <label className="flex items-start gap-3 rounded-lg border border-brand-800 bg-brand-900 p-3 text-sm text-white/80">
                <input
                  type="checkbox"
                  checked={includeSoumission}
                  disabled={!p.soumission_id}
                  onChange={(e) => setIncludeSoumission(e.target.checked)}
                  className="mt-0.5"
                />
                <div className="flex-1">
                  <div className="font-semibold text-white">
                    Items de la soumission acceptée{" "}
                    <span className="text-xs font-normal text-white/50">
                      (prix fixe)
                    </span>
                  </div>
                  <p className="mt-1 text-xs text-white/60">
                    {p.soumission_id
                      ? "Reprend les items du devis, avec un ratio pour facturation par étapes."
                      : "Aucune soumission liée à ce projet."}
                  </p>
                  {includeSoumission && p.soumission_id ? (
                    <div className="mt-3 flex flex-wrap items-center gap-2">
                      <label
                        htmlFor="s_pct"
                        className="text-xs text-white/70"
                      >
                        % à facturer
                      </label>
                      <input
                        id="s_pct"
                        type="number"
                        min="1"
                        max="100"
                        value={soumissionPct}
                        onChange={(e) => setSoumissionPct(e.target.value)}
                        className="input w-20 text-sm"
                      />
                      <div className="flex gap-1">
                        {[25, 30, 50, 75, 100].map((v) => (
                          <button
                            key={v}
                            type="button"
                            onClick={() => setSoumissionPct(String(v))}
                            className={`rounded-md px-2 py-0.5 text-[10px] font-semibold ${
                              String(v) === soumissionPct
                                ? "bg-accent-500 text-brand-950"
                                : "bg-white/5 text-white/70 hover:bg-white/10"
                            }`}
                          >
                            {v}%
                          </button>
                        ))}
                      </div>
                    </div>
                  ) : null}
                </div>
              </label>

              <label className="flex items-start gap-3 rounded-lg border border-brand-800 bg-brand-900 p-3 text-sm text-white/80">
                <input
                  type="checkbox"
                  checked={includeHours}
                  onChange={(e) => setIncludeHours(e.target.checked)}
                  className="mt-0.5"
                />
                <div className="flex-1">
                  <div className="font-semibold text-white">
                    Heures punchées{" "}
                    <span className="text-xs font-normal text-white/50">
                      (T&amp;M)
                    </span>
                  </div>
                  <p className="mt-1 text-xs text-white/60">
                    Regroupées par employé × taux horaire.
                  </p>
                  {includeHours ? (
                    <label className="mt-2 flex items-center gap-2 text-xs text-white/70">
                      <input
                        type="checkbox"
                        checked={onlyApproved}
                        onChange={(e) => setOnlyApproved(e.target.checked)}
                      />
                      Seulement les punches approuvés
                    </label>
                  ) : null}
                </div>
              </label>

              <label className="flex items-start gap-3 rounded-lg border border-brand-800 bg-brand-900 p-3 text-sm text-white/80">
                <input
                  type="checkbox"
                  checked={includeAchats}
                  onChange={(e) => setIncludeAchats(e.target.checked)}
                  className="mt-0.5"
                />
                <div>
                  <div className="font-semibold text-white">
                    Achats du projet{" "}
                    <span className="text-xs font-normal text-white/50">
                      (matériel)
                    </span>
                  </div>
                  <p className="mt-1 text-xs text-white/60">
                    Chaque bon d&apos;achat devient une ligne au montant
                    payé.
                  </p>
                </div>
              </label>

              <div className="pt-2">
                <label htmlFor="due_days" className="label">
                  Échéance (jours à partir d&apos;aujourd&apos;hui)
                </label>
                <input
                  id="due_days"
                  type="number"
                  min="0"
                  max="365"
                  value={dueInDays}
                  onChange={(e) => setDueInDays(e.target.value)}
                  className="input w-32"
                />
              </div>
            </div>

            {error ? (
              <p className="mt-3 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
                {error}
              </p>
            ) : null}

            <div className="mt-6 flex items-center justify-end gap-3">
              <button
                type="button"
                onClick={() => setFactureModalOpen(false)}
                disabled={convertingToFacture}
                className="btn-secondary text-sm"
              >
                Annuler
              </button>
              <button
                type="button"
                onClick={createFacture}
                disabled={
                  convertingToFacture ||
                  (!includeSoumission && !includeHours && !includeAchats)
                }
                className="btn-accent text-sm disabled:opacity-60"
              >
                {convertingToFacture ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" /> Création…
                  </>
                ) : (
                  "Créer la facture"
                )}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </>
  );
}

function Kpi({
  icon: Icon,
  label,
  value
}: {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  value: string;
}) {
  return (
    <div className="rounded-xl border border-brand-800 bg-brand-900 p-4">
      <div className="flex items-center gap-2">
        <Icon className="h-4 w-4 text-accent-500" />
        <p className="text-xs font-medium uppercase tracking-wider text-white/50">
          {label}
        </p>
      </div>
      <p className="mt-2 truncate text-sm font-semibold text-white">{value}</p>
    </div>
  );
}

function SummaryTab(props: {
  name: string;
  onName: (v: string) => void;
  clientId: string;
  onClientId: (v: string) => void;
  clients: Array<{ id: number; name: string }>;
  address: string;
  onAddress: (v: string) => void;
  startDate: string;
  onStartDate: (v: string) => void;
  endDate: string;
  onEndDate: (v: string) => void;
  budget: string;
  onBudget: (v: string) => void;
  description: string;
  onDescription: (v: string) => void;
  notes: string;
  onNotes: (v: string) => void;
  dirty: boolean;
  saving: boolean;
  onSave: () => void;
}) {
  return (
    <div className="max-w-3xl space-y-6">
      <section className="rounded-xl border border-brand-800 bg-brand-900 p-5">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-accent-500">
          Identification
        </h2>
        <div className="mt-4 space-y-4">
          <div>
            <label className="label" htmlFor="p_name">Nom du projet</label>
            <input
              id="p_name"
              type="text"
              value={props.name}
              onChange={(e) => props.onName(e.target.value)}
              className="input"
            />
          </div>
          <div>
            <label className="label" htmlFor="p_client">Client</label>
            <select
              id="p_client"
              value={props.clientId}
              onChange={(e) => props.onClientId(e.target.value)}
              className="input"
            >
              <option value="">— Aucun client —</option>
              {props.clients.map((c) => (
                <option key={c.id} value={String(c.id)}>
                  {c.name}
                </option>
              ))}
            </select>
            <p className="mt-1 text-xs text-white/50">
              Nécessaire pour facturer (le client reçoit la facture par
              courriel).
            </p>
          </div>
          <div>
            <label className="label" htmlFor="p_address">Adresse du chantier</label>
            <AddressInput
              id="p_address"
              value={props.address}
              onChange={props.onAddress}
            />
          </div>
        </div>
      </section>

      <section className="rounded-xl border border-brand-800 bg-brand-900 p-5">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-accent-500">
          Calendrier & budget
        </h2>
        <div className="mt-4 grid gap-4 sm:grid-cols-3">
          <div>
            <label className="label" htmlFor="p_start">Début</label>
            <input
              id="p_start"
              type="date"
              value={props.startDate}
              onChange={(e) => props.onStartDate(e.target.value)}
              className="input"
            />
          </div>
          <div>
            <label className="label" htmlFor="p_end">Fin</label>
            <input
              id="p_end"
              type="date"
              value={props.endDate}
              onChange={(e) => props.onEndDate(e.target.value)}
              className="input"
            />
          </div>
          <div>
            <label className="label" htmlFor="p_budget">Budget (CAD)</label>
            <input
              id="p_budget"
              type="number"
              step="0.01"
              min="0"
              value={props.budget}
              onChange={(e) => props.onBudget(e.target.value)}
              className="input"
            />
          </div>
        </div>
      </section>

      <section className="rounded-xl border border-brand-800 bg-brand-900 p-5">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-accent-500">
          Description des travaux
        </h2>
        <textarea
          rows={4}
          value={props.description}
          onChange={(e) => props.onDescription(e.target.value)}
          placeholder="Portée, contraintes, détails clés…"
          className="input mt-3"
        />
      </section>

      <section className="rounded-xl border border-brand-800 bg-brand-900 p-5">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-accent-500">
          Notes internes
        </h2>
        <textarea
          rows={3}
          value={props.notes}
          onChange={(e) => props.onNotes(e.target.value)}
          placeholder="Points à surveiller, historique, infos clients…"
          className="input mt-3"
        />
      </section>

      <button
        type="button"
        onClick={props.onSave}
        disabled={props.saving || !props.dirty}
        className="btn-accent text-sm"
      >
        {props.saving ? (
          <>
            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            Sauvegarde…
          </>
        ) : (
          <>
            <Save className="mr-2 h-4 w-4" />
            {props.dirty ? "Sauvegarder" : "Aucun changement"}
          </>
        )}
      </button>
    </div>
  );
}

function PlaceholderTab({ label }: { label: string }) {
  return (
    <div className="rounded-xl border border-dashed border-brand-800 bg-brand-900/40 p-10 text-center">
      <FileText className="mx-auto h-10 w-10 text-accent-500" />
      <h3 className="mt-4 text-base font-semibold text-white">{label}</h3>
      <p className="mt-2 text-sm text-white/60">
        Ce module sera branché dans la prochaine phase (agenda, bons de
        travail, factures liées au projet).
      </p>
    </div>
  );
}
