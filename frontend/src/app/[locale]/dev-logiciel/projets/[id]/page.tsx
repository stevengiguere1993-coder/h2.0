"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useParams, useRouter as useNextRouter } from "next/navigation";
import {
  ArrowLeft,
  DollarSign,
  Loader2,
  Plus,
  Save,
  Trash2
} from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { EntityDriveSection } from "@/components/drive/EntityDriveSection";
import { Link } from "@/i18n/navigation";
import { useDevlogLayout } from "../../layout";
import { authedFetch } from "@/lib/auth";
import { useConfirm } from "@/components/confirm-dialog";

type Project = {
  id: number;
  name: string;
  client_id: number | null;
  lead_id: number | null;
  soumission_id: number | null;
  status: string;
  address: string | null;
  description: string | null;
  notes: string | null;
  start_date: string | null;
  end_date: string | null;
  budget: number | string | null;
  estimated_hours_override: number | string | null;
  created_at: string;
  updated_at: string;
};

const STATUS_LABELS: Record<string, string> = {
  planifie: "Planifié",
  en_attente: "En attente",
  en_cours: "En cours",
  suspendu: "Suspendu",
  livre: "Livré",
  // Backward compat avec d'anciens statuts EN.
  planned: "Planifié",
  in_progress: "En cours",
  suspended: "Suspendu",
  delivered: "Livré"
};

const STATUS_CLASS: Record<string, string> = {
  planifie: "bg-white/10 text-white",
  en_attente: "bg-white/10 text-white",
  en_cours: "bg-blue-500/20 text-blue-300",
  suspendu: "bg-amber-500/20 text-amber-300",
  livre: "bg-emerald-500/20 text-emerald-300",
  planned: "bg-white/10 text-white",
  in_progress: "bg-blue-500/20 text-blue-300",
  suspended: "bg-amber-500/20 text-amber-300",
  delivered: "bg-emerald-500/20 text-emerald-300"
};

type TabId =
  | "summary"
  | "planification"
  | "members"
  | "recurring"
  | "achats"
  | "finances";

// Refonte Dev Logiciel 2026-05-25 — onglets dédiés au pôle, ré-alignés
// sur la dualité « investissement initial / services récurrents » du
// devis_dev. L'onglet « Agenda chantier » du pôle Construction est
// retiré (pas pertinent en dev). Nouvel onglet « Services récurrents »
// pour le MRR (DevlogProjectRecurringService).
const TABS: { id: TabId; label: string; available: boolean }[] = [
  { id: "summary", label: "Résumé", available: true },
  { id: "planification", label: "Modules & échéancier", available: true },
  { id: "members", label: "Équipe", available: true },
  { id: "recurring", label: "Frais récurrents", available: true },
  { id: "achats", label: "Frais imprévus", available: true },
  { id: "finances", label: "Finances", available: true }
];

function fmtMoney(n: number | string | null): string {
  if (n == null || n === "") return "—";
  const num = typeof n === "string" ? Number(n) : n;
  return new Intl.NumberFormat("fr-CA", {
    style: "currency",
    currency: "CAD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2
  }).format(num);
}

function isoToDateInput(iso: string | null): string {
  if (!iso) return "";
  return iso.slice(0, 10);
}

export default function ProjectDetailPage() {
  const confirm = useConfirm();
  const { onOpenSidebar } = useDevlogLayout();
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

  // Si l'URL contient un fragment (#planification, #agenda…) on bascule
  // sur ce tab au mount. Permet le deep-link depuis l'agenda chantier
  // (click sur une phase virtuelle ouvre /dev-logiciel/projets/{id}#planification).
  useEffect(() => {
    if (typeof window === "undefined") return;
    const hash = window.location.hash.replace(/^#/, "") as TabId;
    const valid: TabId[] = [
      "summary",
      "planification",
      "members",
      "recurring",
      "achats",
      "finances"
    ];
    if (valid.includes(hash)) setTab(hash);
  }, []);

  // form state
  const [name, setName] = useState("");
  const [clientId, setClientId] = useState("");
  const [clients, setClients] = useState<
    Array<{ id: number; name: string; address?: string | null }>
  >([]);
  const [address, setAddress] = useState("");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [budget, setBudget] = useState("");
  const [estimatedHoursOverride, setEstimatedHoursOverride] = useState("");
  const [description, setDescription] = useState("");
  const [notes, setNotes] = useState("");

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const res = await authedFetch(`/api/v1/devlog/projects/${id}`);
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
        setEstimatedHoursOverride(
          data.estimated_hours_override != null
            ? String(data.estimated_hours_override)
            : ""
        );
        setDescription(data.description || "");
        setNotes(data.notes || "");
        // Load the client list in parallel so the selector has options.
        const cs = await authedFetch("/api/v1/devlog/clients?limit=500");
        if (cs.ok && !cancelled) {
          setClients(
            (await cs.json()) as Array<{
              id: number;
              name: string;
              address?: string | null;
            }>
          );
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
      estimatedHoursOverride !==
        (p.estimated_hours_override != null
          ? String(p.estimated_hours_override)
          : "") ||
      description !== (p.description || "") ||
      notes !== (p.notes || "")
    );
  }, [
    p, name, clientId, address, startDate, endDate, budget,
    estimatedHoursOverride, description, notes,
  ]);

  // Auto-save : quand l'utilisateur modifie un champ (ex. sélectionne
  // une adresse dans l'autocomplete) et arrête d'éditer 1,2 s, on
  // persiste automatiquement. Évite la perte de données si l'usager
  // oublie de cliquer Sauvegarder. Doit être déclaré APRÈS `dirty` —
  // sinon TDZ ReferenceError au mount.
  useEffect(() => {
    if (!p) return;
    if (!dirty) return;
    if (saving) return;
    const t = setTimeout(() => {
      void saveAll();
    }, 1200);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    dirty,
    // `saving` fait partie des deps : sans lui, une modif faite PENDANT un
    // save en vol (le garde `if (saving) return` court-circuite l'effet)
    // n'était jamais re-planifiée. Avec `saving`, l'effet se ré-évalue au
    // passage saving true→false : si `dirty` est encore vrai (l'utilisateur
    // a retouché un champ), il re-planifie le save ; sinon il s'arrête sur
    // le garde `if (!dirty) return`. Pas de boucle (save uniquement si dirty).
    saving,
    name,
    clientId,
    address,
    startDate,
    endDate,
    budget,
    estimatedHoursOverride,
    description,
    notes
  ]);

  async function updateStatus(newStatus: string) {
    if (!p) return;
    const prev = p;
    setP({ ...p, status: newStatus });
    try {
      const res = await authedFetch(`/api/v1/devlog/projects/${id}`, {
        method: "PATCH",
        body: JSON.stringify({ status: newStatus })
      });
      if (!res.ok) throw new Error();
      const updated = (await res.json()) as Project;
      setP(updated);
      // Refonte mai 2026 — quand un projet passe en « livre », bascule
      // automatiquement les services récurrents pending → active
      // (le backend SQLAlchemy event listener pose delivered_at mais
      // ne peut pas appeler un service async ; on déclenche depuis le
      // frontend une fois le PATCH terminé). Idempotent côté API.
      if (newStatus === "livre") {
        try {
          await authedFetch(
            `/api/v1/devlog/projects/${id}/recurring-services/activate-pending`,
            { method: "POST" }
          );
        } catch {
          /* best-effort — Phil peut activer manuellement depuis l'onglet */
        }
      }
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
        estimated_hours_override: estimatedHoursOverride
          ? Number(estimatedHoursOverride)
          : null,
        description: description.trim() || null,
        notes: notes.trim() || null
      };
      const res = await authedFetch(`/api/v1/devlog/projects/${id}`, {
        method: "PATCH",
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
        `/api/v1/devlog/projects/${id}/convert-to-facture`,
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
      router.push(`/dev-logiciel/facturation/${created.id}`);
    } catch (err) {
      setError(`Création facture échouée : ${(err as Error).message}`);
    } finally {
      setConvertingToFacture(false);
    }
  }

  async function onDelete() {
    if (!p) return;
    if (!(await confirm(`Supprimer définitivement le projet « ${p.name} » ?`))) return;
    setDeleting(true);
    try {
      const res = await authedFetch(`/api/v1/devlog/projects/${id}`, {
        method: "DELETE"
      });
      if (!res.ok) throw new Error();
      router.replace("/dev-logiciel/projets");
    } catch {
      setDeleting(false);
      setError("Suppression échouée.");
    }
  }

  return (
    <>
      <AppTopbar
        breadcrumbs={[{ label: "Développement logiciel", href: "/dev-logiciel" as any }, { label: "Projets" }]}
        onOpenSidebar={onOpenSidebar}
      />

      <div className="p-4 lg:p-6">
        <Link
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          href={"/dev-logiciel/projets" as any}
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
                  {[
                    ["planifie", "Planifié"],
                    ["en_attente", "En attente"],
                    ["en_cours", "En cours"],
                    ["suspendu", "Suspendu"],
                    ["livre", "Livré"]
                  ].map(([k, v]) => (
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

            {/* Documents Drive (en haut, sous le header, avant les onglets) */}
            {p ? (
              <EntityDriveSection
                entityType="DevlogProject"
                entityId={id}
                pole="Développement logiciel"
                label="Projet"
                route="/dev-logiciel/projets/[id]"
              />
            ) : null}

            {error ? (
              <p className="mt-4 rounded-lg border border-rose-500/40 bg-rose-500/10 px-4 py-2 text-sm text-rose-300">
                {error}
              </p>
            ) : null}

            <div className="mt-4">
              <button
                type="button"
                onClick={openFactureModal}
                className="inline-flex items-center gap-2 rounded-lg border border-accent-500/40 bg-accent-500/10 px-4 py-2.5 text-sm font-medium text-accent-500 hover:bg-accent-500/20"
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

            {/* Header KPIs Dev Logiciel — 4 cards alignées sur le devis_dev :
                investissement initial + MRR + heures + marge. */}
            <DevlogHeaderKpis projectId={id} />
            <section className="mt-4 flex flex-wrap items-center gap-3 text-xs text-white/50">
              <span>
                Démarré :{" "}
                {p.start_date
                  ? new Date(p.start_date).toLocaleDateString("fr-CA")
                  : "—"}
              </span>
              <span>·</span>
              <span>
                Échéance :{" "}
                {p.end_date
                  ? new Date(p.end_date).toLocaleDateString("fr-CA")
                  : "—"}
              </span>
            </section>

            {/* Tabs */}
            <nav className="mt-8 flex gap-1 overflow-x-auto border-b border-brand-800">
              {TABS.map((t) => {
                const isActive = tab === t.id;
                const baseCls = "px-4 py-2.5 text-sm font-medium transition whitespace-nowrap";
                const activeCls = isActive
                  ? "border-b-2 border-accent-500 text-white"
                  : "text-white/60 hover:text-white";
                // Style atténué pour les onglets indisponibles : opacity
                // + italique + curseur not-allowed au hover. On laisse
                // quand même le clic faire setTab (le contenu affichera
                // le placeholder « bientôt »).
                const unavailableCls = t.available
                  ? ""
                  : "opacity-60 italic hover:cursor-not-allowed";
                return (
                  <button
                    key={t.id}
                    type="button"
                    onClick={() => {
                      setTab(t.id);
                      if (typeof window !== "undefined") {
                        window.history.replaceState(null, "", `#${t.id}`);
                      }
                    }}
                    className={`${baseCls} ${activeCls} ${unavailableCls}`}
                    aria-disabled={!t.available || undefined}
                    title={
                      t.available
                        ? undefined
                        : "Section bientôt disponible pour le pôle dev-logiciel"
                    }
                  >
                    {t.label}
                    {!t.available ? (
                      <span className="ml-1.5 text-[10px] font-normal not-italic text-white/40">
                        (bientôt)
                      </span>
                    ) : null}
                  </button>
                );
              })}
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
                  estimatedHoursOverride={estimatedHoursOverride}
                  onEstimatedHoursOverride={setEstimatedHoursOverride}
                  description={description}
                  onDescription={setDescription}
                  notes={notes}
                  onNotes={setNotes}
                  dirty={dirty}
                  saving={saving}
                  onSave={saveAll}
                />
              ) : tab === "finances" ? (
                <DevlogFinancesTab projectId={id} />
              ) : tab === "members" ? (
                <DevlogMembersTab projectId={id} />
              ) : tab === "planification" ? (
                <DevlogPlanificationTab projectId={id} />
              ) : tab === "achats" ? (
                <DevlogAchatsTab projectId={id} />
              ) : tab === "recurring" ? (
                <DevlogRecurringServicesTab projectId={id} />
              ) : null}
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
                className="inline-flex items-center justify-center rounded-xl bg-accent-500 px-5 py-3 font-semibold text-white transition hover:bg-accent-400 text-sm disabled:opacity-60"
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

function SummaryTab(props: {
  name: string;
  onName: (v: string) => void;
  clientId: string;
  onClientId: (v: string) => void;
  clients: Array<{ id: number; name: string; address?: string | null }>;
  address: string;
  onAddress: (v: string) => void;
  startDate: string;
  onStartDate: (v: string) => void;
  endDate: string;
  onEndDate: (v: string) => void;
  budget: string;
  onBudget: (v: string) => void;
  estimatedHoursOverride: string;
  onEstimatedHoursOverride: (v: string) => void;
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
        </div>
      </section>

      <section className="rounded-xl border border-brand-800 bg-brand-900 p-5">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-accent-500">
          Calendrier
        </h2>
        <p className="mt-1 text-[11px] text-white/40">
          Le budget et les heures prévues sont importés automatiquement de
          la soumission acceptée — détail par module dans l&apos;onglet
          «&nbsp;Modules &amp; échéancier&nbsp;».
        </p>
        <div className="mt-4 grid gap-4 sm:grid-cols-2">
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
        </div>
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
        className="inline-flex items-center justify-center rounded-xl bg-accent-500 px-5 py-3 font-semibold text-white transition hover:bg-accent-400 text-sm"
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

type TeamMember = {
  id: number;
  email: string;
  role: string;
  full_name?: string | null;
};

// ---------------------------------------------------------------------------
// Vague 2 (2026-05) — Onglets dev-logiciel dédiés.
// Composants simplifiés alignés sur les schémas Pydantic des endpoints
// /api/v1/devlog/projects/{id}/(tasks|finances|members). Volontairement
// plus légers que les clones Construction (pas de sous-traitants pour
// les phases, pas de service/material lines pour les finances, etc.).
// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// Onglet Finances dev-logiciel — vue lecture seule alignée sur
// DevlogProjectFinances (total_facture / total_paye / reste / soumission /
// heures / marge_estimee). Pas de KPI projected vs actual : le backend
// ne distingue pas (encore) les coûts internes par type.
// ---------------------------------------------------------------------------

type DevlogFinancesData = {
  project_id: number;
  soumission_id: number | null;
  total_facture: number;
  total_paye: number;
  total_reste_a_facturer: number;
  total_soumission: number;
  total_heures_facturables: number;
  marge_estimee: number;
  nb_sections_soumission: number;
  // Refonte mai 2026 — bloc récurrent
  mrr_active_cents?: number;
  nb_recurring_services_active?: number;
  nb_recurring_services_pending?: number;
  nb_recurring_services_paused?: number;
  nb_recurring_services_cancelled?: number;
};

function DevlogFinancesTab({ projectId }: { projectId: number }) {
  const [data, setData] = useState<DevlogFinancesData | null>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      try {
        const res = await authedFetch(
          `/api/v1/devlog/projects/${projectId}/finances`
        );
        if (!res.ok) {
          const txt = await res.text().catch(() => "");
          throw new Error(
            `HTTP ${res.status}${txt ? ` — ${txt.slice(0, 200)}` : ""}`
          );
        }
        if (!cancelled) setData((await res.json()) as DevlogFinancesData);
      } catch (e) {
        if (!cancelled)
          setErr(`Chargement des finances échoué : ${(e as Error).message}`);
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    if (projectId) load();
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  if (loading) {
    return (
      <div className="flex min-h-[30vh] items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-accent-500" />
      </div>
    );
  }
  if (err || !data) {
    return (
      <p className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-4 py-2 text-sm text-rose-300">
        {err || "Données indisponibles."}
      </p>
    );
  }

  const mrr = (data.mrr_active_cents ?? 0) / 100;

  return (
    <div className="space-y-6">
      {/* Bloc 1 : INVESTISSEMENT INITIAL */}
      <section className="rounded-xl border border-brand-800 bg-brand-900 p-5">
        <div className="mb-4 flex items-center justify-between gap-3">
          <h3 className="text-sm font-semibold uppercase tracking-wider text-accent-500">
            Investissement initial
          </h3>
          <span className="text-[11px] text-white/50">
            Mise en oeuvre — facturé à la livraison
          </span>
        </div>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <DevlogFinanceKpi
            label="Soumission"
            value={fmtMoney(data.total_soumission)}
            sub="Total initial accepté"
            tone="white"
          />
          <DevlogFinanceKpi
            label="Facturé"
            value={fmtMoney(data.total_facture)}
            sub="Factures envoyées + payées"
            tone="white"
          />
          <DevlogFinanceKpi
            label="Encaissé"
            value={fmtMoney(data.total_paye)}
            sub={`${
              data.total_facture > 0
                ? ((data.total_paye / data.total_facture) * 100).toFixed(1)
                : "0.0"
            } % du facturé`}
            tone="emerald"
          />
          <DevlogFinanceKpi
            label="Reste à facturer"
            value={fmtMoney(data.total_reste_a_facturer)}
            sub={`Sur ${fmtMoney(data.total_soumission)}`}
            tone={data.total_reste_a_facturer >= 0 ? "white" : "rose"}
          />
        </div>
      </section>

      {/* Bloc 2 : SERVICES RÉCURRENTS */}
      <section className="rounded-xl border border-brand-800 bg-brand-900 p-5">
        <div className="mb-4 flex items-center justify-between gap-3">
          <h3 className="text-sm font-semibold uppercase tracking-wider text-accent-500">
            Services récurrents
          </h3>
          <span className="text-[11px] text-white/50">
            MRR — facturé chaque mois après livraison
          </span>
        </div>
        <div className="grid gap-4 sm:grid-cols-3">
          <DevlogFinanceKpi
            label="MRR actif"
            value={`${fmtMoney(mrr)} / mois`}
            sub={`${data.nb_recurring_services_active ?? 0} service${
              (data.nb_recurring_services_active ?? 0) > 1 ? "s" : ""
            } actif${(data.nb_recurring_services_active ?? 0) > 1 ? "s" : ""}`}
            tone="emerald"
          />
          <DevlogFinanceKpi
            label="En attente"
            value={String(data.nb_recurring_services_pending ?? 0)}
            sub="Activé à la livraison"
            tone="white"
          />
          <DevlogFinanceKpi
            label="ARR projeté"
            value={`${fmtMoney(mrr * 12)} / an`}
            sub="MRR actif × 12"
            tone="emerald"
          />
        </div>
        <p className="mt-3 text-[11px] text-white/40">
          Détail dans l&apos;onglet « Services récurrents » — ajout / pause /
          génération de facture mensuelle.
        </p>
      </section>

      {/* Bloc 3 : Marge */}
      <section className="rounded-xl border border-brand-800 bg-brand-900 p-5">
        <div className="mb-4 flex items-center justify-between gap-3">
          <h3 className="text-sm font-semibold uppercase tracking-wider text-accent-500">
            Marge & efficacité
          </h3>
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <DevlogFinanceKpi
            label="Marge estimée (initial)"
            value={fmtMoney(data.marge_estimee)}
            sub={`${data.total_heures_facturables.toFixed(1)} h saisies × 75 $/h`}
            tone={data.marge_estimee >= 0 ? "emerald" : "rose"}
          />
          <DevlogFinanceKpi
            label="Heures saisies"
            value={`${data.total_heures_facturables.toFixed(1)} h`}
            sub="Total cumulé sur le projet"
            tone="white"
          />
        </div>
      </section>

      <section className="rounded-xl border border-brand-800 bg-brand-900 p-5">
        <h3 className="text-sm font-semibold uppercase tracking-wider text-accent-500">
          Soumission liée
        </h3>
        {data.soumission_id ? (
          <div className="mt-3 grid gap-3 sm:grid-cols-3 text-sm">
            <div>
              <p className="text-[11px] uppercase tracking-wider text-white/50">
                Initial (mise en oeuvre)
              </p>
              <p className="mt-1 font-semibold text-white">
                {fmtMoney(data.total_soumission)}
              </p>
            </div>
            <div>
              <p className="text-[11px] uppercase tracking-wider text-white/50">
                Sections
              </p>
              <p className="mt-1 font-semibold text-white">
                {data.nb_sections_soumission}
              </p>
            </div>
            <div>
              <p className="text-[11px] uppercase tracking-wider text-white/50">
                Soumission ID
              </p>
              <Link
                // eslint-disable-next-line @typescript-eslint/no-explicit-any
                href={`/dev-logiciel/soumissions/${data.soumission_id}` as any}
                className="mt-1 inline-block font-semibold text-accent-500 underline decoration-dotted hover:text-accent-400"
              >
                #{data.soumission_id} →
              </Link>
            </div>
          </div>
        ) : (
          <p className="mt-2 text-sm text-white/60">
            Aucune soumission liée à ce projet. Le reste à facturer et la marge
            estimée sont basés sur la soumission acceptée — relie-en une depuis
            l&apos;onglet Résumé pour activer ces calculs.
          </p>
        )}
      </section>

      <p className="text-[11px] text-white/40">
        Vue agrégée lecture seule. La marge estimée valorise les heures saisies
        à un taux par défaut de 75 $/h ; un calcul précis arrivera quand les
        taux par membre seront branchés.
      </p>
    </div>
  );
}

function DevlogFinanceKpi({
  label,
  value,
  sub,
  tone
}: {
  label: string;
  value: string;
  sub?: string;
  tone: "white" | "emerald" | "rose";
}) {
  const toneClass =
    tone === "emerald"
      ? "text-emerald-300"
      : tone === "rose"
        ? "text-rose-300"
        : "text-white";
  return (
    <div className="panel">
      <p className="text-[11px] font-medium uppercase tracking-wider text-white/50">
        {label}
      </p>
      <p className={`mt-2 text-xl font-bold ${toneClass}`}>{value}</p>
      {sub ? <p className="mt-1 text-[11px] text-white/40">{sub}</p> : null}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Onglet Membres dev-logiciel — assignation user / sous-traitant XOR
// avec rôle et taux horaire. DELETE utilise le member_id (PK), pas le
// user_id. Le composant Construction utilisait PUT user_ids[] (refonte
// incompatible avec le modèle XOR du backend devlog).
// ---------------------------------------------------------------------------

type DevlogMember = {
  id: number;
  project_id: number;
  user_id: number | null;
  sous_traitant_id: number | null;
  role: string | null;
  hourly_rate: number | null;
  added_by_user_id: number | null;
  added_at: string;
};

type DevlogSousTraitant = {
  id: number;
  name: string;
  company: string | null;
  specialty: string | null;
  hourly_rate: number | null;
  active: boolean;
};

function DevlogMembersTab({ projectId }: { projectId: number }) {
  const confirm = useConfirm();
  const [members, setMembers] = useState<DevlogMember[]>([]);
  const [users, setUsers] = useState<TeamMember[]>([]);
  const [sousTraitants, setSousTraitants] = useState<DevlogSousTraitant[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);

  const [pickKind, setPickKind] = useState<"user" | "sous_traitant">("user");
  const [pickId, setPickId] = useState("");
  const [pickRole, setPickRole] = useState("");
  const [pickRate, setPickRate] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [mRes, uRes, sRes] = await Promise.all([
        authedFetch(`/api/v1/devlog/projects/${projectId}/members`),
        authedFetch("/api/v1/users"),
        authedFetch("/api/v1/devlog/sous-traitants?limit=500")
      ]);
      if (!mRes.ok) throw new Error(`HTTP ${mRes.status}`);
      setMembers((await mRes.json()) as DevlogMember[]);
      if (uRes.ok) setUsers((await uRes.json()) as TeamMember[]);
      if (sRes.ok) {
        const all = (await sRes.json()) as DevlogSousTraitant[];
        setSousTraitants(all.filter((s) => s.active));
      }
    } catch (e) {
      setErr(`Chargement de l'équipe échoué : ${(e as Error).message}`);
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    void load();
  }, [load]);

  async function addMember() {
    if (!pickId) {
      setErr("Choisis une personne à ajouter.");
      return;
    }
    setAdding(true);
    setErr(null);
    try {
      const payload: Record<string, unknown> = {};
      if (pickKind === "user") payload.user_id = Number(pickId);
      else payload.sous_traitant_id = Number(pickId);
      if (pickRole.trim()) payload.role = pickRole.trim();
      if (pickRate.trim()) payload.hourly_rate = Number(pickRate);
      const res = await authedFetch(
        `/api/v1/devlog/projects/${projectId}/members`,
        { method: "POST", body: JSON.stringify(payload) }
      );
      if (!res.ok) {
        const txt = await res.text().catch(() => "");
        throw new Error(`HTTP ${res.status}${txt ? ` — ${txt.slice(0, 200)}` : ""}`);
      }
      const created = (await res.json()) as DevlogMember;
      setMembers((xs) => [...xs, created]);
      setPickId("");
      setPickRole("");
      setPickRate("");
    } catch (e) {
      setErr(`Ajout membre échoué : ${(e as Error).message}`);
    } finally {
      setAdding(false);
    }
  }

  async function removeMember(memberId: number) {
    if (!(await confirm("Retirer cette personne du projet ?"))) return;
    setErr(null);
    try {
      const res = await authedFetch(
        `/api/v1/devlog/projects/${projectId}/members/${memberId}`,
        { method: "DELETE" }
      );
      if (!res.ok && res.status !== 204) throw new Error(`HTTP ${res.status}`);
      setMembers((xs) => xs.filter((m) => m.id !== memberId));
    } catch (e) {
      setErr(`Retrait échoué : ${(e as Error).message}`);
    }
  }

  const userById = useMemo(() => {
    const m = new Map<number, TeamMember>();
    users.forEach((u) => m.set(u.id, u));
    return m;
  }, [users]);

  const sousTraitantById = useMemo(() => {
    const m = new Map<number, DevlogSousTraitant>();
    sousTraitants.forEach((s) => m.set(s.id, s));
    return m;
  }, [sousTraitants]);

  // Pour le picker : exclut ceux déjà membres (selon le type courant).
  const availableUsers = useMemo(() => {
    const taken = new Set(
      members.filter((m) => m.user_id != null).map((m) => m.user_id as number)
    );
    return users.filter((u) => !taken.has(u.id));
  }, [users, members]);

  const availableSousTraitants = useMemo(() => {
    const taken = new Set(
      members
        .filter((m) => m.sous_traitant_id != null)
        .map((m) => m.sous_traitant_id as number)
    );
    return sousTraitants.filter((s) => !taken.has(s.id));
  }, [sousTraitants, members]);

  function memberLabel(m: DevlogMember): {
    name: string;
    kind: "Interne" | "Sous-traitant";
    sub: string | null;
  } {
    if (m.user_id != null) {
      const u = userById.get(m.user_id);
      return {
        name: u ? u.full_name || u.email : `User #${m.user_id}`,
        kind: "Interne",
        sub: u?.full_name ? u.email : null
      };
    }
    if (m.sous_traitant_id != null) {
      const s = sousTraitantById.get(m.sous_traitant_id);
      return {
        name: s ? s.name : `Sous-traitant #${m.sous_traitant_id}`,
        kind: "Sous-traitant",
        sub: s?.company || s?.specialty || null
      };
    }
    return { name: "—", kind: "Interne", sub: null };
  }

  return (
    <div className="space-y-5">
      <section className="rounded-xl border border-brand-800 bg-brand-900 p-5">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-accent-500">
          Équipe du projet
        </h2>
        <p className="mt-1 text-xs text-white/60">
          Ajoute les membres internes ou sous-traitants assignés au projet,
          avec leur taux horaire pour le calcul des coûts.
        </p>
        <div className="mt-4 grid gap-3 sm:grid-cols-[140px_1fr_180px_140px_auto]">
          <select
            value={pickKind}
            onChange={(e) => {
              setPickKind(e.target.value as "user" | "sous_traitant");
              setPickId("");
            }}
            className="input"
          >
            <option value="user">Interne</option>
            <option value="sous_traitant">Sous-traitant</option>
          </select>
          <select
            value={pickId}
            onChange={(e) => setPickId(e.target.value)}
            className="input"
          >
            <option value="">
              — {pickKind === "user" ? "Personne" : "Sous-traitant"} —
            </option>
            {pickKind === "user"
              ? availableUsers.map((u) => (
                  <option key={u.id} value={String(u.id)}>
                    {u.full_name || u.email}
                  </option>
                ))
              : availableSousTraitants.map((s) => (
                  <option key={s.id} value={String(s.id)}>
                    {s.name}
                    {s.specialty ? ` — ${s.specialty}` : ""}
                  </option>
                ))}
          </select>
          <input
            type="text"
            value={pickRole}
            onChange={(e) => setPickRole(e.target.value)}
            placeholder="Rôle (ex. Dev backend)"
            className="input"
          />
          <input
            type="number"
            min="0"
            step="0.01"
            value={pickRate}
            onChange={(e) => setPickRate(e.target.value)}
            placeholder="Taux $/h"
            className="input"
          />
          <button
            type="button"
            onClick={addMember}
            disabled={adding || !pickId}
            className="inline-flex items-center justify-center rounded-xl bg-accent-500 px-5 py-3 font-semibold text-white transition hover:bg-accent-400 text-sm disabled:opacity-60"
          >
            {adding ? (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            ) : (
              <Plus className="mr-2 h-4 w-4" />
            )}
            Ajouter
          </button>
        </div>
        {err ? <p className="mt-3 text-sm text-rose-300">{err}</p> : null}
      </section>

      <section className="rounded-xl border border-brand-800 bg-brand-900">
        {loading ? (
          <div className="flex min-h-[30vh] items-center justify-center">
            <Loader2 className="h-6 w-6 animate-spin text-accent-500" />
          </div>
        ) : members.length === 0 ? (
          <p className="px-5 py-8 text-center text-sm text-white/60">
            Aucune personne n&apos;est assignée à ce projet pour le moment.
          </p>
        ) : (
          <ul className="divide-y divide-brand-800">
            {members.map((m) => {
              const meta = memberLabel(m);
              return (
                <li
                  key={m.id}
                  className="grid gap-3 px-4 py-3 text-sm sm:grid-cols-[1fr_120px_180px_140px_auto] sm:items-center"
                >
                  <div className="min-w-0">
                    <p className="truncate font-medium text-white">
                      {meta.name}
                    </p>
                    {meta.sub ? (
                      <p className="mt-0.5 truncate text-[11px] text-white/50">
                        {meta.sub}
                      </p>
                    ) : null}
                  </div>
                  <span
                    className={`rounded-full border px-2 py-0.5 text-center text-[11px] font-semibold ${
                      meta.kind === "Interne"
                        ? "border-blue-500/30 bg-blue-500/15 text-blue-300"
                        : "border-amber-500/30 bg-amber-500/15 text-amber-300"
                    }`}
                  >
                    {meta.kind}
                  </span>
                  <span className="text-white/80">{m.role || "—"}</span>
                  <span className="text-white/70">
                    {m.hourly_rate != null
                      ? `${fmtMoney(m.hourly_rate)} / h`
                      : "—"}
                  </span>
                  <button
                    type="button"
                    onClick={() => removeMember(m.id)}
                    className="text-rose-400 hover:text-rose-300"
                    aria-label="Retirer du projet"
                  >
                    <Trash2 className="h-4 w-4" />
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </section>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Vague 2.5 (2026-05-25) — Onglets Planification / Photos / Achats / Recap.
// Composants dedies au pole dev-logiciel, alignes sur les schemas Pydantic
// /api/v1/devlog/projects/{id}/(phases|photos|purchases|recap).
// ---------------------------------------------------------------------------

type DevlogPhase = {
  id: number;
  project_id: number;
  name: string;
  description: string | null;
  position: number;
  start_date: string | null;
  end_date: string | null;
  status: string;
  // Budget & heures importés de la soumission (refonte projet 2026-06).
  source_module_id: number | null;
  budget_cents: number;
  heures_dev_prevues: number;
  heures_manager_prevues: number;
  created_at: string;
  updated_at: string;
};

const DEVLOG_PHASE_STATUSES: { value: string; label: string; cls: string }[] = [
  { value: "planifie", label: "À venir", cls: "bg-white/10 text-white/80 border-white/20" },
  { value: "en_cours", label: "En cours", cls: "bg-blue-500/20 text-blue-300 border-blue-500/30" },
  { value: "termine", label: "Terminé", cls: "bg-emerald-500/20 text-emerald-300 border-emerald-500/30" }
];

function phaseStatusMeta(status: string) {
  return (
    DEVLOG_PHASE_STATUSES.find((s) => s.value === status) ||
    DEVLOG_PHASE_STATUSES[0]
  );
}

function durationLabel(start: string | null, end: string | null): string {
  if (!start || !end) return "—";
  const s = new Date(start);
  const e = new Date(end);
  const ms = e.getTime() - s.getTime();
  if (Number.isNaN(ms)) return "—";
  const days = Math.round(ms / 86_400_000) + 1;
  if (days <= 0) return "—";
  if (days === 1) return "1 jour";
  if (days < 14) return `${days} jours`;
  const weeks = Math.round(days / 7);
  return `${weeks} sem.`;
}

function DevlogPlanificationTab({ projectId }: { projectId: number }) {
  const confirm = useConfirm();
  const [phases, setPhases] = useState<DevlogPhase[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  // form etat
  const [newName, setNewName] = useState("");
  const [newStart, setNewStart] = useState("");
  const [newEnd, setNewEnd] = useState("");
  const [creating, setCreating] = useState(false);

  // drag-and-drop : id de la phase en cours de drag
  const [dragId, setDragId] = useState<number | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      try {
        const res = await authedFetch(
          `/api/v1/devlog/projects/${projectId}/phases`
        );
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = (await res.json()) as DevlogPhase[];
        if (!cancelled) setPhases(data);
      } catch (e) {
        if (!cancelled) setErr(`Chargement échoué : ${(e as Error).message}`);
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    if (projectId) load();
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  async function addPhase() {
    if (!newName.trim()) return;
    setCreating(true);
    setErr(null);
    try {
      const payload: Record<string, unknown> = {
        name: newName.trim(),
        position: 0,
        status: "planifie"
      };
      if (newStart) payload.start_date = newStart;
      if (newEnd) payload.end_date = newEnd;
      const res = await authedFetch(
        `/api/v1/devlog/projects/${projectId}/phases`,
        { method: "POST", body: JSON.stringify(payload) }
      );
      if (!res.ok) {
        const txt = await res.text().catch(() => "");
        throw new Error(
          `HTTP ${res.status}${txt ? ` — ${txt.slice(0, 200)}` : ""}`
        );
      }
      const created = (await res.json()) as DevlogPhase;
      setPhases((xs) => [...xs, created]);
      setNewName("");
      setNewStart("");
      setNewEnd("");
    } catch (e) {
      setErr(`Ajout échoué : ${(e as Error).message}`);
    } finally {
      setCreating(false);
    }
  }

  async function patchPhase(id: number, patch: Partial<DevlogPhase>) {
    setErr(null);
    try {
      const res = await authedFetch(
        `/api/v1/devlog/projects/${projectId}/phases/${id}`,
        { method: "PATCH", body: JSON.stringify(patch) }
      );
      if (!res.ok) {
        const txt = await res.text().catch(() => "");
        throw new Error(
          `HTTP ${res.status}${txt ? ` — ${txt.slice(0, 200)}` : ""}`
        );
      }
      const updated = (await res.json()) as DevlogPhase;
      setPhases((xs) => xs.map((x) => (x.id === id ? updated : x)));
    } catch (e) {
      setErr(`Mise à jour échouée : ${(e as Error).message}`);
    }
  }

  async function removePhase(id: number) {
    if (!(await confirm("Supprimer cette phase ?"))) return;
    setErr(null);
    try {
      const res = await authedFetch(
        `/api/v1/devlog/projects/${projectId}/phases/${id}`,
        { method: "DELETE" }
      );
      if (!res.ok && res.status !== 204) throw new Error(`HTTP ${res.status}`);
      setPhases((xs) => xs.filter((x) => x.id !== id));
    } catch (e) {
      setErr(`Suppression échouée : ${(e as Error).message}`);
    }
  }

  async function reorder(newOrder: number[]) {
    // Optimistic update local : on reattribue les positions immediatement.
    setPhases((xs) => {
      const byId = new Map(xs.map((p) => [p.id, p]));
      const reordered: DevlogPhase[] = [];
      newOrder.forEach((id, idx) => {
        const ph = byId.get(id);
        if (ph) {
          reordered.push({ ...ph, position: idx });
          byId.delete(id);
        }
      });
      // Append phases non mentionnees (ne devrait pas arriver normalement)
      Array.from(byId.values()).forEach((ph) =>
        reordered.push({ ...ph, position: reordered.length })
      );
      return reordered;
    });
    try {
      const res = await authedFetch(
        `/api/v1/devlog/projects/${projectId}/phases/reorder`,
        { method: "POST", body: JSON.stringify({ phase_ids: newOrder }) }
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const updated = (await res.json()) as DevlogPhase[];
      setPhases(updated);
    } catch (e) {
      setErr(`Réordonnancement échoué : ${(e as Error).message}`);
    }
  }

  function onDragStart(id: number) {
    setDragId(id);
  }
  function onDragOver(e: React.DragEvent<HTMLElement>) {
    e.preventDefault();
  }
  function onDrop(targetId: number) {
    if (dragId == null || dragId === targetId) return;
    const ids = phases.map((p) => p.id);
    const from = ids.indexOf(dragId);
    const to = ids.indexOf(targetId);
    if (from < 0 || to < 0) return;
    const next = [...ids];
    next.splice(from, 1);
    next.splice(to, 0, dragId);
    setDragId(null);
    void reorder(next);
  }

  const sorted = useMemo(
    () => [...phases].sort((a, b) => a.position - b.position || a.id - b.id),
    [phases]
  );

  return (
    <div className="space-y-5">
      <section className="rounded-xl border border-brand-800 bg-brand-900 p-5">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-accent-500">
          Phases du projet
        </h2>
        <p className="mt-1 text-xs text-white/60">
          Phases dérivées de la section « Investissement initial » de la
          soumission. Les services récurrents sont gérés dans l&apos;onglet
          dédié (ils ne sont pas des phases).
        </p>
        <div className="mt-4 grid gap-3 sm:grid-cols-[1fr_160px_160px_auto]">
          <input
            type="text"
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            placeholder="Ex. Design UI, Dev sprint 1, Recette client…"
            className="input"
          />
          <input
            type="date"
            value={newStart}
            onChange={(e) => setNewStart(e.target.value)}
            placeholder="Début"
            className="input"
          />
          <input
            type="date"
            value={newEnd}
            onChange={(e) => setNewEnd(e.target.value)}
            placeholder="Fin"
            className="input"
          />
          <button
            type="button"
            onClick={addPhase}
            disabled={creating || !newName.trim()}
            className="inline-flex items-center justify-center rounded-xl bg-accent-500 px-5 py-3 font-semibold text-white transition hover:bg-accent-400 text-sm disabled:opacity-60"
          >
            {creating ? (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            ) : (
              <Plus className="mr-2 h-4 w-4" />
            )}
            Ajouter
          </button>
        </div>
        {err ? <p className="mt-3 text-sm text-rose-300">{err}</p> : null}
      </section>

      <section>
        {loading ? (
          <div className="flex min-h-[30vh] items-center justify-center">
            <Loader2 className="h-6 w-6 animate-spin text-accent-500" />
          </div>
        ) : sorted.length === 0 ? (
          <p className="rounded-xl border border-dashed border-brand-800 bg-brand-900/40 px-6 py-10 text-center text-sm text-white/60">
            Aucune phase. Décompose ton projet en étapes pour suivre l&apos;avancement.
          </p>
        ) : (
          <ol className="space-y-3">
            {sorted.map((ph, idx) => {
              const meta = phaseStatusMeta(ph.status);
              return (
                <li
                  key={ph.id}
                  draggable
                  onDragStart={() => onDragStart(ph.id)}
                  onDragOver={onDragOver}
                  onDrop={() => onDrop(ph.id)}
                  className={`flex flex-col gap-3 rounded-xl border bg-brand-900 p-4 transition sm:flex-row sm:items-center ${
                    dragId === ph.id
                      ? "border-accent-500/60 bg-brand-900/60"
                      : "border-brand-800 hover:border-brand-700"
                  }`}
                >
                  <div className="flex shrink-0 items-center gap-3 sm:w-20">
                    <span
                      className="cursor-grab text-white/30 hover:text-white/60"
                      title="Glisser pour réordonner"
                      aria-hidden="true"
                    >
                      ⠿
                    </span>
                    <span className="rounded-full bg-brand-950 px-2 py-0.5 text-xs font-semibold text-white/70">
                      #{idx + 1}
                    </span>
                  </div>
                  <div className="min-w-0 flex-1">
                    <input
                      type="text"
                      value={ph.name}
                      onChange={(e) =>
                        setPhases((xs) =>
                          xs.map((x) =>
                            x.id === ph.id ? { ...x, name: e.target.value } : x
                          )
                        )
                      }
                      onBlur={(e) => {
                        const v = e.target.value.trim();
                        if (v && v !== ph.name) patchPhase(ph.id, { name: v });
                      }}
                      className="w-full bg-transparent text-base font-semibold text-white focus:outline-none"
                      placeholder="Nom de la phase"
                    />
                    <div className="mt-1 flex flex-wrap items-center gap-2 text-[11px] text-white/50">
                      {ph.budget_cents > 0 ? (
                        <span className="rounded bg-emerald-500/15 px-1.5 py-0.5 font-semibold text-emerald-300">
                          {fmtMoney(ph.budget_cents / 100)}
                        </span>
                      ) : null}
                      {ph.heures_dev_prevues > 0 ? (
                        <span className="rounded bg-blue-500/15 px-1.5 py-0.5 font-semibold text-blue-300">
                          {ph.heures_dev_prevues} h prévues
                        </span>
                      ) : null}
                      <span>
                        Durée :{" "}
                        <span className="text-white/70">
                          {durationLabel(ph.start_date, ph.end_date)}
                        </span>
                      </span>
                      {ph.source_module_id ? (
                        <span
                          className="rounded bg-white/5 px-1.5 py-0.5 text-white/40"
                          title="Importé d'un module de la soumission"
                        >
                          ↳ module
                        </span>
                      ) : null}
                    </div>
                  </div>
                  <div className="grid w-full grid-cols-2 gap-2 sm:w-auto sm:grid-cols-[140px_140px_140px_auto]">
                    <input
                      type="date"
                      value={ph.start_date || ""}
                      onChange={(e) =>
                        patchPhase(ph.id, {
                          start_date: e.target.value || null
                        } as Partial<DevlogPhase>)
                      }
                      className="input text-xs"
                    />
                    <input
                      type="date"
                      value={ph.end_date || ""}
                      onChange={(e) =>
                        patchPhase(ph.id, {
                          end_date: e.target.value || null
                        } as Partial<DevlogPhase>)
                      }
                      className="input text-xs"
                    />
                    <select
                      value={ph.status}
                      onChange={(e) =>
                        patchPhase(ph.id, { status: e.target.value })
                      }
                      className={`rounded-full border px-2 py-1 text-[11px] font-semibold ${meta.cls}`}
                    >
                      {DEVLOG_PHASE_STATUSES.map((s) => (
                        <option
                          key={s.value}
                          value={s.value}
                          className="bg-brand-950 text-white"
                        >
                          {s.label}
                        </option>
                      ))}
                    </select>
                    <button
                      type="button"
                      onClick={() => removePhase(ph.id)}
                      className="text-rose-400 hover:text-rose-300"
                      aria-label="Supprimer la phase"
                    >
                      <Trash2 className="h-4 w-4" />
                    </button>
                  </div>
                </li>
              );
            })}
          </ol>
        )}
      </section>
      <p className="text-[11px] text-white/40">
        Astuce : glisse une phase par sa poignée pour la réordonner. Les dates
        et le statut se sauvegardent automatiquement.
      </p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Achats
// ---------------------------------------------------------------------------

type DevlogPurchase = {
  id: number;
  project_id: number;
  description: string;
  amount_cents: number;
  supplier: string | null;
  purchased_at: string | null;
  notes: string | null;
  has_receipt: boolean;
  receipt_filename: string | null;
  receipt_content_type: string | null;
  created_by_user_id: number | null;
  created_at: string;
  updated_at: string;
};

function DevlogAchatsTab({ projectId }: { projectId: number }) {
  const confirm = useConfirm();
  const [items, setItems] = useState<DevlogPurchase[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [creating, setCreating] = useState(false);

  // form state
  const [fDesc, setFDesc] = useState("");
  const [fAmount, setFAmount] = useState("");
  const [fSupplier, setFSupplier] = useState("");
  const [fDate, setFDate] = useState("");
  const [fNotes, setFNotes] = useState("");

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      try {
        const res = await authedFetch(
          `/api/v1/devlog/projects/${projectId}/purchases`
        );
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        if (!cancelled) setItems((await res.json()) as DevlogPurchase[]);
      } catch (e) {
        if (!cancelled)
          setErr(`Chargement échoué : ${(e as Error).message}`);
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  function resetForm() {
    setFDesc("");
    setFAmount("");
    setFSupplier("");
    setFDate("");
    setFNotes("");
  }

  async function addPurchase() {
    const amount = Number(fAmount);
    if (!fDesc.trim() || !Number.isFinite(amount) || amount < 0) {
      setErr("Description et montant requis.");
      return;
    }
    setCreating(true);
    setErr(null);
    try {
      const payload: Record<string, unknown> = {
        description: fDesc.trim(),
        amount_cents: Math.round(amount * 100)
      };
      if (fSupplier.trim()) payload.supplier = fSupplier.trim();
      if (fDate) payload.purchased_at = fDate;
      if (fNotes.trim()) payload.notes = fNotes.trim();
      const res = await authedFetch(
        `/api/v1/devlog/projects/${projectId}/purchases`,
        { method: "POST", body: JSON.stringify(payload) }
      );
      if (!res.ok) {
        const txt = await res.text().catch(() => "");
        throw new Error(
          `HTTP ${res.status}${txt ? ` — ${txt.slice(0, 200)}` : ""}`
        );
      }
      const created = (await res.json()) as DevlogPurchase;
      setItems((xs) => [created, ...xs]);
      resetForm();
      setModalOpen(false);
    } catch (e) {
      setErr(`Ajout échoué : ${(e as Error).message}`);
    } finally {
      setCreating(false);
    }
  }

  async function removePurchase(id: number) {
    if (!(await confirm("Supprimer cet achat ?"))) return;
    setErr(null);
    try {
      const res = await authedFetch(
        `/api/v1/devlog/projects/${projectId}/purchases/${id}`,
        { method: "DELETE" }
      );
      if (!res.ok && res.status !== 204) throw new Error(`HTTP ${res.status}`);
      setItems((xs) => xs.filter((x) => x.id !== id));
    } catch (e) {
      setErr(`Suppression échouée : ${(e as Error).message}`);
    }
  }

  async function uploadReceipt(id: number, file: File) {
    setErr(null);
    const fd = new FormData();
    fd.append("file", file, file.name);
    try {
      const res = await authedFetch(
        `/api/v1/devlog/projects/${projectId}/purchases/${id}/receipt`,
        { method: "POST", body: fd }
      );
      if (!res.ok) {
        const txt = await res.text().catch(() => "");
        throw new Error(
          `HTTP ${res.status}${txt ? ` — ${txt.slice(0, 200)}` : ""}`
        );
      }
      const updated = (await res.json()) as DevlogPurchase;
      setItems((xs) => xs.map((x) => (x.id === id ? updated : x)));
    } catch (e) {
      setErr(`Upload reçu échoué : ${(e as Error).message}`);
    }
  }

  async function viewReceipt(id: number) {
    try {
      const res = await authedFetch(
        `/api/v1/devlog/projects/${projectId}/purchases/${id}/receipt`
      );
      if (!res.ok) throw new Error();
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      window.open(url, "_blank", "noopener,noreferrer");
      setTimeout(() => URL.revokeObjectURL(url), 60_000);
    } catch {
      setErr("Ouverture reçu échouée.");
    }
  }

  const total = items.reduce((acc, x) => acc + x.amount_cents, 0);

  return (
    <div className="space-y-5">
      <section className="flex items-center justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold uppercase tracking-wider text-accent-500">
            Outils & licences
          </h2>
          <p className="mt-1 text-xs text-white/60">
            Suivi des outils, licences et abonnements du projet (Figma,
            Stripe, AWS, dépendances payantes, sous-traitance ponctuelle…).
            Total cumulé en bas de la liste.
          </p>
        </div>
        <button
          type="button"
          onClick={() => setModalOpen(true)}
          className="inline-flex items-center justify-center rounded-xl bg-accent-500 px-4 py-2.5 font-semibold text-white transition hover:bg-accent-400 text-sm"
        >
          <Plus className="mr-2 h-4 w-4" />
          Ajouter une dépense
        </button>
      </section>

      <section className="overflow-hidden rounded-xl border border-brand-800 bg-brand-900">
        {loading ? (
          <div className="flex min-h-[30vh] items-center justify-center">
            <Loader2 className="h-6 w-6 animate-spin text-accent-500" />
          </div>
        ) : items.length === 0 ? (
          <p className="px-5 py-10 text-center text-sm text-white/60">
            Aucun achat pour ce projet.
          </p>
        ) : (
          <table className="w-full text-sm">
            <thead className="bg-brand-950/50 text-[11px] uppercase tracking-wider text-white/50">
              <tr>
                <th className="px-4 py-2 text-left">Date</th>
                <th className="px-4 py-2 text-left">Description</th>
                <th className="px-4 py-2 text-left">Fournisseur</th>
                <th className="px-4 py-2 text-right">Montant</th>
                <th className="px-4 py-2 text-center">Reçu</th>
                <th className="px-4 py-2"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-brand-800">
              {items.map((it) => (
                <tr key={it.id}>
                  <td className="px-4 py-2 text-white/70">
                    {it.purchased_at || "—"}
                  </td>
                  <td className="px-4 py-2 text-white">
                    <div className="font-medium">{it.description}</div>
                    {it.notes ? (
                      <div className="mt-0.5 text-[11px] text-white/40">
                        {it.notes}
                      </div>
                    ) : null}
                  </td>
                  <td className="px-4 py-2 text-white/70">
                    {it.supplier || "—"}
                  </td>
                  <td className="px-4 py-2 text-right font-semibold text-white">
                    {fmtMoney(it.amount_cents / 100)}
                  </td>
                  <td className="px-4 py-2 text-center">
                    {it.has_receipt ? (
                      <button
                        type="button"
                        onClick={() => viewReceipt(it.id)}
                        className="text-xs text-accent-500 underline decoration-dotted hover:text-accent-400"
                      >
                        Voir
                      </button>
                    ) : (
                      <label className="inline-flex cursor-pointer items-center gap-1 text-xs text-white/50 hover:text-white/80">
                        <input
                          type="file"
                          accept="image/*,application/pdf"
                          className="hidden"
                          onChange={(e) => {
                            const f = e.target.files?.[0];
                            e.target.value = "";
                            if (f) uploadReceipt(it.id, f);
                          }}
                        />
                        + Joindre
                      </label>
                    )}
                  </td>
                  <td className="px-4 py-2 text-right">
                    <button
                      type="button"
                      onClick={() => removePurchase(it.id)}
                      className="text-rose-400 hover:text-rose-300"
                      aria-label="Supprimer"
                    >
                      <Trash2 className="h-4 w-4" />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
            <tfoot className="bg-brand-950/40 text-sm font-semibold text-white">
              <tr>
                <td className="px-4 py-3" colSpan={3}>
                  Total ({items.length} achat{items.length > 1 ? "s" : ""})
                </td>
                <td className="px-4 py-3 text-right text-blue-300">
                  {fmtMoney(total / 100)}
                </td>
                <td colSpan={2}></td>
              </tr>
            </tfoot>
          </table>
        )}
      </section>
      {err ? <p className="text-sm text-rose-300">{err}</p> : null}

      {modalOpen ? (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4"
          onClick={() => (!creating ? setModalOpen(false) : null)}
        >
          <div
            className="w-full max-w-lg rounded-2xl border border-brand-800 bg-brand-950 p-6 shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          >
            <h3 className="text-lg font-bold text-white">Nouvel achat</h3>
            <div className="mt-4 space-y-3">
              <div>
                <label className="label" htmlFor="ach_desc">
                  Description *
                </label>
                <input
                  id="ach_desc"
                  type="text"
                  value={fDesc}
                  onChange={(e) => setFDesc(e.target.value)}
                  placeholder="Ex. Licences Figma 3 mois"
                  className="input"
                />
              </div>
              <div className="grid gap-3 sm:grid-cols-2">
                <div>
                  <label className="label" htmlFor="ach_amount">
                    Montant (CAD) *
                  </label>
                  <input
                    id="ach_amount"
                    type="number"
                    min="0"
                    step="0.01"
                    value={fAmount}
                    onChange={(e) => setFAmount(e.target.value)}
                    className="input"
                  />
                </div>
                <div>
                  <label className="label" htmlFor="ach_date">
                    Date
                  </label>
                  <input
                    id="ach_date"
                    type="date"
                    value={fDate}
                    onChange={(e) => setFDate(e.target.value)}
                    className="input"
                  />
                </div>
              </div>
              <div>
                <label className="label" htmlFor="ach_sup">
                  Fournisseur
                </label>
                <input
                  id="ach_sup"
                  type="text"
                  value={fSupplier}
                  onChange={(e) => setFSupplier(e.target.value)}
                  placeholder="Ex. Figma Inc."
                  className="input"
                />
              </div>
              <div>
                <label className="label" htmlFor="ach_notes">
                  Notes
                </label>
                <textarea
                  id="ach_notes"
                  value={fNotes}
                  onChange={(e) => setFNotes(e.target.value)}
                  rows={2}
                  className="input"
                />
              </div>
            </div>
            <div className="mt-6 flex items-center justify-end gap-3">
              <button
                type="button"
                onClick={() => setModalOpen(false)}
                disabled={creating}
                className="btn-secondary text-sm"
              >
                Annuler
              </button>
              <button
                type="button"
                onClick={addPurchase}
                disabled={creating || !fDesc.trim() || !fAmount}
                className="inline-flex items-center justify-center rounded-xl bg-accent-500 px-5 py-3 font-semibold text-white transition hover:bg-accent-400 text-sm disabled:opacity-60"
              >
                {creating ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    Création…
                  </>
                ) : (
                  "Créer l'achat"
                )}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Header KPIs Dev Logiciel — 4 cards : initial / MRR / heures / marge
// Charge /finances pour avoir tous les chiffres en un seul appel.
// ---------------------------------------------------------------------------

function DevlogHeaderKpis({ projectId }: { projectId: number }) {
  const [data, setData] = useState<DevlogFinancesData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await authedFetch(
          `/api/v1/devlog/projects/${projectId}/finances`
        );
        if (!res.ok) return;
        if (!cancelled) setData((await res.json()) as DevlogFinancesData);
      } catch {
        /* ignore */
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  if (loading) {
    return (
      <section className="mt-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {[0, 1, 2, 3].map((i) => (
          <div
            key={i}
            className="h-24 animate-pulse rounded-xl border border-brand-800 bg-brand-900"
          />
        ))}
      </section>
    );
  }

  const mrr = (data?.mrr_active_cents ?? 0) / 100;
  const factPct =
    data && data.total_soumission > 0
      ? Math.min(
          100,
          Math.round((data.total_facture / data.total_soumission) * 100)
        )
      : 0;

  return (
    <section className="mt-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
      {/* KPI 1 : Investissement initial */}
      <div className="panel">
        <p className="text-[11px] font-medium uppercase tracking-wider text-white/50">
          Budget initial
        </p>
        <p className="mt-2 text-xl font-bold text-white">
          {fmtMoney(data?.total_facture ?? 0)}
        </p>
        <p className="mt-1 text-[11px] text-white/40">
          sur {fmtMoney(data?.total_soumission ?? 0)} ({factPct}%)
        </p>
        <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-brand-950">
          <div
            className="h-full bg-blue-500 transition-all"
            style={{ width: `${factPct}%` }}
          />
        </div>
      </div>

      {/* KPI 2 : MRR */}
      <div className="panel">
        <p className="text-[11px] font-medium uppercase tracking-wider text-white/50">
          MRR actif
        </p>
        <p className="mt-2 text-xl font-bold text-emerald-300">
          {fmtMoney(mrr)} <span className="text-xs text-white/50">/ mois</span>
        </p>
        <p className="mt-1 text-[11px] text-white/40">
          {data?.nb_recurring_services_active ?? 0} service
          {(data?.nb_recurring_services_active ?? 0) > 1 ? "s" : ""} actif
          {(data?.nb_recurring_services_active ?? 0) > 1 ? "s" : ""}
          {(data?.nb_recurring_services_pending ?? 0) > 0
            ? ` · ${data?.nb_recurring_services_pending} en attente`
            : ""}
        </p>
      </div>

      {/* KPI 3 : Heures */}
      <div className="panel">
        <p className="text-[11px] font-medium uppercase tracking-wider text-white/50">
          Heures saisies
        </p>
        <p className="mt-2 text-xl font-bold text-white">
          {(data?.total_heures_facturables ?? 0).toFixed(1)} h
        </p>
        <p className="mt-1 text-[11px] text-white/40">Cumul du projet</p>
      </div>

      {/* KPI 4 : Marge estimée */}
      <div className="panel">
        <p className="text-[11px] font-medium uppercase tracking-wider text-white/50">
          Marge estimée
        </p>
        <p
          className={`mt-2 text-xl font-bold ${
            (data?.marge_estimee ?? 0) >= 0 ? "text-emerald-300" : "text-rose-300"
          }`}
        >
          {fmtMoney(data?.marge_estimee ?? 0)}
        </p>
        <p className="mt-1 text-[11px] text-white/40">
          Initial — heures × 75 $/h
        </p>
      </div>
    </section>
  );
}

// ---------------------------------------------------------------------------
// Services récurrents — liste + CRUD + toggle status + génération facture.
// Aligné sur les endpoints /api/v1/devlog/projects/{id}/recurring-services
// ajoutés en mai 2026 par la refonte « initial / récurrent ».
// ---------------------------------------------------------------------------

type DevlogRecurringService = {
  id: number;
  project_id: number;
  name: string;
  monthly_amount_cents: number;
  start_date: string | null;
  status: "pending" | "active" | "paused" | "cancelled";
  last_invoiced_at: string | null;
  source_soumission_item_id: number | null;
  created_at: string;
  updated_at: string;
};

const RECURRING_STATUS_META: Record<
  string,
  { label: string; cls: string }
> = {
  pending: {
    label: "En attente",
    cls: "bg-white/10 text-white/80 border-white/20"
  },
  active: {
    label: "Actif",
    cls: "bg-emerald-500/20 text-emerald-300 border-emerald-500/30"
  },
  paused: {
    label: "En pause",
    cls: "bg-amber-500/20 text-amber-300 border-amber-500/30"
  },
  cancelled: {
    label: "Annulé",
    cls: "bg-rose-500/20 text-rose-300 border-rose-500/30"
  }
};

function DevlogRecurringServicesTab({
  projectId
}: {
  projectId: number;
}) {
  const confirm = useConfirm();
  const [services, setServices] = useState<DevlogRecurringService[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // Form ajout
  const [fName, setFName] = useState("");
  const [fAmount, setFAmount] = useState("");
  const [fStart, setFStart] = useState("");
  const [creating, setCreating] = useState(false);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      try {
        const res = await authedFetch(
          `/api/v1/devlog/projects/${projectId}/recurring-services`
        );
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        if (!cancelled)
          setServices((await res.json()) as DevlogRecurringService[]);
      } catch (e) {
        if (!cancelled)
          setErr(`Chargement échoué : ${(e as Error).message}`);
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  async function addService() {
    const amount = Number(fAmount);
    if (!fName.trim() || !Number.isFinite(amount) || amount < 0) {
      setErr("Nom et montant requis.");
      return;
    }
    setCreating(true);
    setErr(null);
    try {
      const payload: Record<string, unknown> = {
        name: fName.trim(),
        monthly_amount_cents: Math.round(amount * 100),
        status: "pending"
      };
      if (fStart) payload.start_date = fStart;
      const res = await authedFetch(
        `/api/v1/devlog/projects/${projectId}/recurring-services`,
        { method: "POST", body: JSON.stringify(payload) }
      );
      if (!res.ok) {
        const txt = await res.text().catch(() => "");
        throw new Error(
          `HTTP ${res.status}${txt ? ` — ${txt.slice(0, 200)}` : ""}`
        );
      }
      const created = (await res.json()) as DevlogRecurringService;
      setServices((xs) => [...xs, created]);
      setFName("");
      setFAmount("");
      setFStart("");
    } catch (e) {
      setErr(`Ajout échoué : ${(e as Error).message}`);
    } finally {
      setCreating(false);
    }
  }

  async function patchService(
    id: number,
    patch: Partial<DevlogRecurringService>
  ) {
    setErr(null);
    try {
      const res = await authedFetch(
        `/api/v1/devlog/projects/${projectId}/recurring-services/${id}`,
        { method: "PATCH", body: JSON.stringify(patch) }
      );
      if (!res.ok) {
        const txt = await res.text().catch(() => "");
        throw new Error(
          `HTTP ${res.status}${txt ? ` — ${txt.slice(0, 200)}` : ""}`
        );
      }
      const updated = (await res.json()) as DevlogRecurringService;
      setServices((xs) => xs.map((x) => (x.id === id ? updated : x)));
    } catch (e) {
      setErr(`Mise à jour échouée : ${(e as Error).message}`);
    }
  }

  async function removeService(id: number) {
    if (!(await confirm("Supprimer ce service récurrent ?"))) return;
    setErr(null);
    try {
      const res = await authedFetch(
        `/api/v1/devlog/projects/${projectId}/recurring-services/${id}`,
        { method: "DELETE" }
      );
      if (!res.ok && res.status !== 204) throw new Error(`HTTP ${res.status}`);
      setServices((xs) => xs.filter((x) => x.id !== id));
    } catch (e) {
      setErr(`Suppression échouée : ${(e as Error).message}`);
    }
  }

  async function generateInvoice(id: number, name: string) {
    if (
      !(await confirm(
        `Générer la facture mensuelle brouillon pour « ${name} » ?`
      ))
    )
      return;
    setBusy(true);
    setErr(null);
    try {
      const res = await authedFetch(
        `/api/v1/devlog/projects/${projectId}/recurring-services/${id}/generate-invoice`,
        { method: "POST" }
      );
      if (!res.ok) {
        const txt = await res.text().catch(() => "");
        throw new Error(
          `HTTP ${res.status}${txt ? ` — ${txt.slice(0, 200)}` : ""}`
        );
      }
      const data = (await res.json()) as { invoice_id: number };
      // Refresh la liste pour récupérer last_invoiced_at.
      const lr = await authedFetch(
        `/api/v1/devlog/projects/${projectId}/recurring-services`
      );
      if (lr.ok) setServices((await lr.json()) as DevlogRecurringService[]);
      alert(`Facture brouillon #${data.invoice_id} créée.`);
    } catch (e) {
      setErr(`Génération facture échouée : ${(e as Error).message}`);
    } finally {
      setBusy(false);
    }
  }

  const totalMrrActive = services
    .filter((s) => s.status === "active")
    .reduce((acc, s) => acc + s.monthly_amount_cents, 0);

  return (
    <div className="space-y-5">
      <section className="rounded-xl border border-brand-800 bg-brand-900 p-5">
        <div className="flex items-start justify-between gap-3">
          <div>
            <h2 className="text-sm font-semibold uppercase tracking-wider text-accent-500">
              Services récurrents
            </h2>
            <p className="mt-1 text-xs text-white/60">
              Hébergement, support, maintenance, abonnements… facturés
              automatiquement chaque mois après livraison du projet. Le
              MRR (montant mensuel récurrent) cumule les services en statut
              « actif ».
            </p>
          </div>
          <div className="text-right">
            <p className="text-[11px] uppercase tracking-wider text-white/50">
              MRR total actif
            </p>
            <p className="mt-1 text-xl font-bold text-emerald-300">
              {fmtMoney(totalMrrActive / 100)}{" "}
              <span className="text-xs font-normal text-white/50">/ mois</span>
            </p>
          </div>
        </div>
      </section>

      <section className="rounded-xl border border-brand-800 bg-brand-900 p-5">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-accent-500">
          Ajouter un service récurrent
        </h2>
        <div className="mt-4 grid gap-3 sm:grid-cols-[1fr_180px_180px_auto]">
          <input
            type="text"
            value={fName}
            onChange={(e) => setFName(e.target.value)}
            placeholder="Ex. Hébergement et maintenance Pro"
            className="input"
          />
          <input
            type="number"
            min="0"
            step="0.01"
            value={fAmount}
            onChange={(e) => setFAmount(e.target.value)}
            placeholder="Montant mensuel HT"
            className="input"
          />
          <input
            type="date"
            value={fStart}
            onChange={(e) => setFStart(e.target.value)}
            placeholder="Démarrage"
            className="input"
          />
          <button
            type="button"
            onClick={addService}
            disabled={creating || !fName.trim() || !fAmount}
            className="inline-flex items-center justify-center rounded-xl bg-accent-500 px-5 py-3 font-semibold text-white transition hover:bg-accent-400 text-sm disabled:opacity-60"
          >
            {creating ? (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            ) : (
              <Plus className="mr-2 h-4 w-4" />
            )}
            Ajouter
          </button>
        </div>
        {err ? <p className="mt-3 text-sm text-rose-300">{err}</p> : null}
      </section>

      <section>
        {loading ? (
          <div className="flex min-h-[30vh] items-center justify-center">
            <Loader2 className="h-6 w-6 animate-spin text-accent-500" />
          </div>
        ) : services.length === 0 ? (
          <p className="rounded-xl border border-dashed border-brand-800 bg-brand-900/40 px-6 py-10 text-center text-sm text-white/60">
            Aucun service récurrent. Les services issus de la soumission
            seront ajoutés automatiquement au démarrage du projet ; tu peux
            aussi en ajouter manuellement ci-dessus.
          </p>
        ) : (
          <ul className="space-y-3">
            {services.map((s) => {
              const meta =
                RECURRING_STATUS_META[s.status] ||
                RECURRING_STATUS_META.pending;
              return (
                <li
                  key={s.id}
                  className="panel"
                >
                  <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                    <div className="min-w-0 flex-1">
                      <input
                        type="text"
                        value={s.name}
                        onChange={(e) =>
                          setServices((xs) =>
                            xs.map((x) =>
                              x.id === s.id
                                ? { ...x, name: e.target.value }
                                : x
                            )
                          )
                        }
                        onBlur={(e) => {
                          const v = e.target.value.trim();
                          if (v && v !== s.name)
                            patchService(s.id, { name: v });
                        }}
                        className="w-full bg-transparent text-base font-semibold text-white focus:outline-none"
                        placeholder="Nom du service"
                      />
                      <div className="mt-1 flex flex-wrap items-center gap-3 text-[11px] text-white/50">
                        <span>
                          Démarrage :{" "}
                          {s.start_date
                            ? new Date(s.start_date).toLocaleDateString("fr-CA")
                            : "—"}
                        </span>
                        <span>·</span>
                        <span>
                          Dernière facturation :{" "}
                          {s.last_invoiced_at
                            ? new Date(s.last_invoiced_at).toLocaleDateString(
                                "fr-CA"
                              )
                            : "jamais"}
                        </span>
                      </div>
                    </div>
                    <div className="grid grid-cols-[140px_120px_auto_auto] items-center gap-2 sm:grid-cols-[160px_140px_auto_auto]">
                      <input
                        type="number"
                        min="0"
                        step="0.01"
                        value={(s.monthly_amount_cents / 100).toString()}
                        onChange={(e) => {
                          const v = Math.max(
                            0,
                            Math.round(Number(e.target.value || 0) * 100)
                          );
                          setServices((xs) =>
                            xs.map((x) =>
                              x.id === s.id
                                ? { ...x, monthly_amount_cents: v }
                                : x
                            )
                          );
                        }}
                        onBlur={(e) => {
                          const v = Math.max(
                            0,
                            Math.round(Number(e.target.value || 0) * 100)
                          );
                          if (v !== s.monthly_amount_cents)
                            patchService(s.id, { monthly_amount_cents: v });
                        }}
                        className="input text-sm"
                        title="Montant mensuel HT (CAD)"
                      />
                      <select
                        value={s.status}
                        onChange={(e) =>
                          patchService(s.id, {
                            status: e.target.value as DevlogRecurringService["status"]
                          })
                        }
                        className={`rounded-full border px-2 py-1 text-[11px] font-semibold ${meta.cls}`}
                      >
                        {Object.entries(RECURRING_STATUS_META).map(
                          ([k, v]) => (
                            <option
                              key={k}
                              value={k}
                              className="bg-brand-950 text-white"
                            >
                              {v.label}
                            </option>
                          )
                        )}
                      </select>
                      <button
                        type="button"
                        onClick={() => generateInvoice(s.id, s.name)}
                        disabled={busy || s.status !== "active"}
                        className="inline-flex items-center gap-1 rounded-lg border border-accent-500/40 bg-accent-500/10 px-3 py-1.5 text-xs font-medium text-accent-500 hover:bg-accent-500/20 disabled:opacity-50"
                        title={
                          s.status === "active"
                            ? "Générer la facture du mois (brouillon)"
                            : "Service non actif"
                        }
                      >
                        <DollarSign className="h-3.5 w-3.5" />
                        Facture
                      </button>
                      <button
                        type="button"
                        onClick={() => removeService(s.id)}
                        className="text-rose-400 hover:text-rose-300"
                        aria-label="Supprimer"
                      >
                        <Trash2 className="h-4 w-4" />
                      </button>
                    </div>
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </section>

      <p className="text-[11px] text-white/40">
        Le bouton « Facture » crée une facture brouillon avec une ligne au
        montant mensuel TTC (TPS + TVQ ajoutées automatiquement). Tu peux
        ensuite l&apos;ouvrir et l&apos;envoyer depuis l&apos;onglet
        Facturation. L&apos;automatisation cron arrivera plus tard.
      </p>
    </div>
  );
}
