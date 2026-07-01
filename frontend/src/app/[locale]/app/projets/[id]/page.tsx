"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useParams, useRouter as useNextRouter } from "next/navigation";
import {
  ArrowLeft,
  Calendar,
  CheckCircle2,
  ChevronRight,
  Circle,
  DollarSign,
  FileText,
  Hammer,
  Loader2,
  Mail,
  MapPin,
  Plus,
  ArrowDownUp,
  Save,
  Trash2
} from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { AddressInput } from "@/components/address-input";
import { EntityDriveSection } from "@/components/drive/EntityDriveSection";
import { Link } from "@/i18n/navigation";
import { useAppLayout } from "../../layout";
import { authedFetch } from "@/lib/auth";
import { TAX_FACTOR } from "@/lib/tax";
import { useConfirm } from "@/components/confirm-dialog";
import { MultiSelectDropdown } from "@/components/multi-select-dropdown";
import {
  AchatMarkPaidModal,
  type MarkPaidAchat
} from "@/components/achat-mark-paid-modal";

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
  estimated_hours_override: number | string | null;
  correction_status?: string;
  awaiting_signature?: boolean;
  has_signed_bon?: boolean;
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

type TabId =
  | "summary"
  | "planification"
  | "agenda"
  | "achats"
  | "photos"
  | "tasks"
  | "corrections"
  | "finances";

const TABS: { id: TabId; label: string }[] = [
  { id: "summary", label: "Résumé" },
  { id: "planification", label: "Planification" },
  { id: "agenda", label: "Agenda chantier" },
  { id: "achats", label: "Achats / PO" },
  { id: "finances", label: "Récap & finances" },
  { id: "photos", label: "Photos" },
  { id: "tasks", label: "Tâches" },
  { id: "corrections", label: "Corrections / améliorations" }
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
  const [soumissionMode, setSoumissionMode] = useState<"pct" | "amount">("pct");
  const [soumissionPct, setSoumissionPct] = useState("100");
  const [soumissionAmount, setSoumissionAmount] = useState("");
  const [includeHours, setIncludeHours] = useState(false);
  const [includeAchats, setIncludeAchats] = useState(false);
  const [onlyApproved, setOnlyApproved] = useState(true);
  const [dueInDays, setDueInDays] = useState("0");
  const [tab, setTab] = useState<TabId>("summary");
  // #25 — Phase ciblée par un clic depuis le Gantt / la liste agenda :
  // on ouvre l'onglet Planification ET on défile/surligne cette phase
  // précise (au lieu de juste afficher toutes les planifs).
  const [focusPhaseId, setFocusPhaseId] = useState<number | null>(null);

  // Si l'URL contient un fragment (#planification, #agenda…) on bascule
  // sur ce tab au mount. Permet le deep-link depuis l'agenda chantier
  // (click sur une phase virtuelle ouvre /app/projets/{id}#planification).
  useEffect(() => {
    if (typeof window === "undefined") return;
    const hash = window.location.hash.replace(/^#/, "") as TabId;
    const valid: TabId[] = [
      "summary",
      "planification",
      "agenda",
      "achats",
      "photos",
      "tasks",
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
  const [correctionsCount, setCorrectionsCount] = useState(0);

  async function loadCorrectionsCount() {
    try {
      const r = await authedFetch(`/api/v1/projects/${id}/corrections`);
      if (r.ok) {
        const arr = (await r.json()) as unknown[];
        setCorrectionsCount(Array.isArray(arr) ? arr.length : 0);
      }
    } catch {
      /* ignore */
    }
  }

  useEffect(() => {
    if (id) void loadCorrectionsCount();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

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
        setEstimatedHoursOverride(
          data.estimated_hours_override != null
            ? String(data.estimated_hours_override)
            : ""
        );
        setDescription(data.description || "");
        setNotes(data.notes || "");
        // Load the client list in parallel so the selector has options.
        const cs = await authedFetch("/api/v1/clients?limit=500");
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

  // Rafraîchit le projet (ex. après changement du statut de correction ou
  // signature d'un bon de correction) sans recharger toute la page.
  async function reloadProject() {
    try {
      const res = await authedFetch(`/api/v1/projects/${id}`);
      if (res.ok) setP((await res.json()) as Project);
    } catch {
      /* ignore */
    }
  }

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
      const res = await authedFetch(`/api/v1/projects/${id}`, {
        method: "PUT",
        body: JSON.stringify({ status: newStatus })
      });
      if (!res.ok) {
        const t = await res.text().catch(() => "");
        throw new Error(`HTTP ${res.status} ${t.slice(0, 200)}`);
      }
      // On RELIT le projet depuis le serveur (source de vérité unique) au
      // lieu de se fier au corps de la réponse : garantit que la fiche
      // affiche le statut réellement persisté — donc cohérent avec le
      // tableau kanban (qui lit le même champ).
      const reload = await authedFetch(`/api/v1/projects/${id}`);
      if (reload.ok) {
        setP((await reload.json()) as Project);
      } else {
        setP((await res.json()) as Project);
      }
    } catch (e) {
      setP(prev);
      setError(`Changement de statut échoué : ${(e as Error).message}`);
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
    setSoumissionMode("pct");
    setSoumissionPct("100");
    setSoumissionAmount("");
    setIncludeHours(!p.soumission_id);
    setIncludeAchats(false);
    setOnlyApproved(true);
    setDueInDays("0");
    setFactureModalOpen(true);
  }

  async function createFacture() {
    if (!p) return;
    // Aucune source cochée = facture VIERGE : on crée une facture vide
    // (brouillon) et l'utilisateur saisit lui-même toutes les lignes sur
    // la fiche. Le backend gère l'import à zéro sans souci.
    setConvertingToFacture(true);
    setError(null);
    try {
      const amountVal = Number(soumissionAmount) || 0;
      const useAmount =
        soumissionMode === "amount" && amountVal > 0 && includeSoumission;
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
            // Si l'admin a coché « Montant $ », on envoie le montant
            // exact. Le backend dérive le ratio depuis le subtotal.
            ...(useAmount ? { soumission_amount: amountVal } : {}),
            include_hours: includeHours,
            only_approved: onlyApproved,
            include_achats: includeAchats,
            due_in_days: Number(dueInDays) || 0
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
    if (!(await confirm(`Supprimer définitivement le projet « ${p.name} » ?`))) return;
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
        breadcrumbs={[{ label: "Construction", href: "/app" }, { label: "Projets" }]}
        onOpenSidebar={onOpenSidebar}
      />

      <div className="p-4 lg:p-6">
        <button
          type="button"
          onClick={() => {
            // Retour intelligent : si on est arrivé ici depuis une autre
            // page de l'app (ex. l'agenda), on revient dessus via
            // l'historique. Sinon (accès direct / nouvel onglet), repli
            // sur la liste des projets.
            if (
              typeof window !== "undefined" &&
              window.history.length > 1
            ) {
              router.back();
            } else {
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
              router.push("/app/projets" as any);
            }
          }}
          className="inline-flex items-center text-sm text-white/70 hover:text-accent-500"
        >
          <ArrowLeft className="mr-1 h-4 w-4" /> Retour
        </button>

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

            {/* Documents Drive (en haut, sous le header, avant les onglets) */}
            <EntityDriveSection
              entityType="ConstructionProject"
              entityId={id}
              pole="Construction"
              label="Projet"
              route="/app/projets/[id]"
            />

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
                  onClick={() => {
                    setTab(t.id);
                    if (typeof window !== "undefined") {
                      window.history.replaceState(null, "", `#${t.id}`);
                    }
                  }}
                  className={`whitespace-nowrap px-4 py-2.5 text-sm font-medium transition ${
                    tab === t.id
                      ? "border-b-2 border-accent-500 text-white"
                      : t.id === "corrections" &&
                          correctionsCount > 0 &&
                          (p?.correction_status || "a_planifier") !== "termine"
                        ? "text-rose-300 hover:text-rose-200"
                        : "text-white/60 hover:text-white"
                  }`}
                >
                  {t.label}
                  {t.id === "corrections" &&
                  correctionsCount > 0 &&
                  (p?.correction_status || "a_planifier") !== "termine" ? (
                    <span className="ml-1.5 inline-block h-2 w-2 rounded-full bg-rose-400 align-middle" />
                  ) : null}
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
              ) : tab === "planification" ? (
                <PlanificationTab
                  projectId={id}
                  focusPhaseId={focusPhaseId}
                  onFocusConsumed={() => setFocusPhaseId(null)}
                />
              ) : tab === "agenda" ? (
                <ChantierAgendaTab
                  projectId={id}
                  projectName={p?.name || ""}
                  projectEndDate={p?.end_date || null}
                  onOpenPhase={(phaseId) => {
                    setFocusPhaseId(phaseId ?? null);
                    setTab("planification");
                    if (typeof window !== "undefined") {
                      window.history.replaceState(null, "", "#planification");
                    }
                  }}
                />
              ) : tab === "achats" ? (
                <ProjectAchatsTab projectId={id} />
              ) : tab === "finances" ? (
                <FinancesTab projectId={id} project={p} />
              ) : tab === "photos" ? (
                <PhotosTab projectId={id} />
              ) : tab === "corrections" ? (
                <ProjectCorrections
                  projectId={id}
                  correctionStatus={p?.correction_status || "a_planifier"}
                  awaitingSignature={!!p?.awaiting_signature}
                  hasSignedBon={!!p?.has_signed_bon}
                  onChanged={() => {
                    void reloadProject();
                    void loadCorrectionsCount();
                  }}
                />
              ) : (
                <TasksTab projectId={id} />
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
              Sélectionne les sources d&apos;items à inclure — ou laisse tout
              décoché pour créer une <strong>facture vierge</strong> et saisir
              toi-même chaque ligne. Tu pourras de toute façon ajuster
              manuellement sur la fiche.
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
                    <div className="mt-3 space-y-2">
                      {/* Toggle mode : % vs montant $ */}
                      <div className="inline-flex rounded-md border border-brand-800 bg-brand-950 p-0.5 text-[11px]">
                        <button
                          type="button"
                          onClick={() => setSoumissionMode("pct")}
                          className={`rounded px-2.5 py-1 font-semibold transition ${
                            soumissionMode === "pct"
                              ? "bg-accent-500 text-brand-950"
                              : "text-white/70 hover:bg-white/5"
                          }`}
                        >
                          Pourcentage
                        </button>
                        <button
                          type="button"
                          onClick={() => setSoumissionMode("amount")}
                          className={`rounded px-2.5 py-1 font-semibold transition ${
                            soumissionMode === "amount"
                              ? "bg-accent-500 text-brand-950"
                              : "text-white/70 hover:bg-white/5"
                          }`}
                        >
                          Montant $
                        </button>
                      </div>

                      {soumissionMode === "pct" ? (
                        <div className="flex flex-wrap items-center gap-2">
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
                      ) : (
                        <div className="flex flex-wrap items-center gap-2">
                          <label
                            htmlFor="s_amount"
                            className="text-xs text-white/70"
                          >
                            Montant à facturer (avant taxes)
                          </label>
                          <div className="relative">
                            <input
                              id="s_amount"
                              type="number"
                              min="0"
                              step="0.01"
                              placeholder="5000"
                              value={soumissionAmount}
                              onChange={(e) =>
                                setSoumissionAmount(e.target.value)
                              }
                              className="input w-32 pr-8 text-sm"
                            />
                            <span className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-xs text-white/50">
                              $
                            </span>
                          </div>
                          {p.budget ? (
                            <span className="text-[10px] text-white/40">
                              Budget total :{" "}
                              {Number(p.budget).toLocaleString("fr-CA", {
                                minimumFractionDigits: 2,
                                maximumFractionDigits: 2
                              })}{" "}
                              $
                            </span>
                          ) : null}
                        </div>
                      )}
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
                  Échéance (jours à partir d&apos;aujourd&apos;hui) — 0 =
                  payable sur réception
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
                disabled={convertingToFacture}
                className="btn-accent text-sm disabled:opacity-60"
              >
                {convertingToFacture ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" /> Création…
                  </>
                ) : !includeSoumission && !includeHours && !includeAchats ? (
                  "Créer une facture vierge"
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
          <div>
            <div className="flex items-center justify-between gap-2">
              <label className="label" htmlFor="p_address">
                Adresse du chantier
              </label>
              {(() => {
                const selectedClient = props.clients.find(
                  (c) => String(c.id) === props.clientId
                );
                const clientAddress = selectedClient?.address?.trim() || "";
                if (!clientAddress) return null;
                if (props.address.trim() === clientAddress) {
                  return (
                    <span className="text-[10px] uppercase tracking-wider text-emerald-400">
                      ✓ Adresse du client
                    </span>
                  );
                }
                return (
                  <button
                    type="button"
                    onClick={() => props.onAddress(clientAddress)}
                    className="text-[10px] uppercase tracking-wider text-accent-400 underline decoration-dotted hover:text-accent-300"
                    title={`Importer : ${clientAddress}`}
                  >
                    ↩ Utiliser l&apos;adresse du client
                  </button>
                );
              })()}
            </div>
            <AddressInput
              id="p_address"
              value={props.address}
              onChange={props.onAddress}
            />
            <p className="mt-1 text-[11px] text-white/50">
              Adresse du chantier (peut différer de l&apos;adresse du
              client). Tape pour autocomplete ou clique sur «&nbsp;Utiliser
              l&apos;adresse du client&nbsp;» pour importer celle-ci.
            </p>
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
          <div>
            <label className="label" htmlFor="p_hours_override">
              Heures main-d&apos;œuvre (override)
            </label>
            <input
              id="p_hours_override"
              type="number"
              step="0.5"
              min="0"
              value={props.estimatedHoursOverride}
              onChange={(e) =>
                props.onEstimatedHoursOverride(e.target.value)
              }
              placeholder="Auto si vide"
              className="input"
            />
            <p className="mt-1 text-[11px] text-white/40">
              Laisse vide pour le calcul automatique (somme des phases ×
              personnes assignées). Saisis un total pour forcer.
            </p>
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

type Photo = {
  id: number;
  project_id: number;
  content_type: string;
  caption: string | null;
  uploaded_by_email: string | null;
  created_at: string;
};

function PhotosTab({ projectId }: { projectId: number }) {
  const confirm = useConfirm();
  const [photos, setPhotos] = useState<Photo[]>([]);
  // Object URLs résolus via authedFetch pour chaque photo. Une balise
  // <img src=...> directe ne peut pas envoyer le Bearer token, donc
  // les images affichaient un placeholder cassé. On fetch chaque blob
  // côté JS, on crée une object URL et on la met dans src.
  const [photoUrls, setPhotoUrls] = useState<Record<number, string>>({});
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState<{ done: number; total: number } | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [caption, setCaption] = useState("");

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      try {
        const res = await authedFetch(
          `/api/v1/projects/${projectId}/photos`
        );
        if (!res.ok) throw new Error();
        if (!cancelled) setPhotos((await res.json()) as Photo[]);
      } catch {
        if (!cancelled) setErr("Chargement échoué.");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  // Charge les blobs (images ou PDF) via authedFetch et les expose
  // comme object URLs. Les PDF sont skippés (on affiche une icône).
  useEffect(() => {
    let cancelled = false;
    const created: string[] = [];
    (async () => {
      for (const p of photos) {
        if (photoUrls[p.id]) continue;
        if (p.content_type === "application/pdf") continue;
        try {
          const r = await authedFetch(
            `/api/v1/projects/${projectId}/photos/${p.id}/image`
          );
          if (!r.ok) continue;
          const blob = await r.blob();
          const url = URL.createObjectURL(blob);
          created.push(url);
          if (cancelled) {
            URL.revokeObjectURL(url);
            continue;
          }
          setPhotoUrls((prev) => ({ ...prev, [p.id]: url }));
        } catch {
          /* ignore — l'utilisateur verra le placeholder */
        }
      }
    })();
    return () => {
      cancelled = true;
      // Les URLs sont revoke quand la photo disparaît du state via
      // remove() — pas ici pour éviter de casser un re-render qui
      // garde les mêmes blobs.
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [photos, projectId]);

  // Cleanup global au démontage de la tab.
  useEffect(() => {
    return () => {
      Object.values(photoUrls).forEach((url) => URL.revokeObjectURL(url));
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function uploadOne(file: File): Promise<Photo> {
    const fd = new FormData();
    fd.append("file", file, file.name);
    if (caption.trim()) fd.append("caption", caption.trim());
    const res = await authedFetch(
      `/api/v1/projects/${projectId}/photos`,
      { method: "POST", body: fd }
    );
    if (!res.ok) {
      const txt = await res.text();
      throw new Error(txt.slice(0, 240) || `http_${res.status}`);
    }
    return (await res.json()) as Photo;
  }

  async function upload(files: File[]) {
    if (files.length === 0) return;
    setBusy(true);
    setErr(null);
    setProgress({ done: 0, total: files.length });
    const created: Photo[] = [];
    const failures: string[] = [];
    let done = 0;
    await Promise.all(
      files.map(async (f) => {
        try {
          const photo = await uploadOne(f);
          created.push(photo);
        } catch (e) {
          failures.push(`${f.name}: ${(e as Error).message}`);
        } finally {
          done += 1;
          setProgress({ done, total: files.length });
        }
      })
    );
    if (created.length > 0) {
      created.sort((a, b) => b.id - a.id);
      setPhotos((xs) => [...created, ...xs]);
      setCaption("");
    }
    if (failures.length > 0) {
      setErr(
        `${failures.length} échec(s) : ${failures.slice(0, 3).join(" ; ")}` +
          (failures.length > 3 ? "…" : "")
      );
    }
    setProgress(null);
    setBusy(false);
  }

  async function remove(id: number) {
    if (!(await confirm("Supprimer cette photo ?"))) return;
    try {
      const res = await authedFetch(
        `/api/v1/projects/${projectId}/photos/${id}`,
        { method: "DELETE" }
      );
      if (!res.ok && res.status !== 204) throw new Error();
      setPhotos((xs) => xs.filter((p) => p.id !== id));
      setPhotoUrls((prev) => {
        const url = prev[id];
        if (url) URL.revokeObjectURL(url);
        const next = { ...prev };
        delete next[id];
        return next;
      });
    } catch {
      setErr("Suppression échouée.");
    }
  }

  async function openImage(p: Photo) {
    try {
      const res = await authedFetch(
        `/api/v1/projects/${projectId}/photos/${p.id}/image`
      );
      if (!res.ok) throw new Error();
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      window.open(url, "_blank", "noopener,noreferrer");
      setTimeout(() => URL.revokeObjectURL(url), 60_000);
    } catch {
      setErr("Ouverture échouée.");
    }
  }

  return (
    <div className="space-y-5">
      <section className="rounded-xl border border-brand-800 bg-brand-900 p-5">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-accent-500">
          Ajouter une photo
        </h2>
        <p className="mt-1 text-xs text-white/60">
          Scan avec la caméra (mobile) ou import de plusieurs fichiers à la
          fois. JPG / PNG / WEBP / HEIC / PDF, 15 Mo max par fichier.
        </p>
        <div className="mt-4 space-y-3">
          <input
            type="text"
            value={caption}
            onChange={(e) => setCaption(e.target.value)}
            placeholder="Légende commune (optionnel, appliquée à tous les fichiers)"
            className="input"
          />
          <div className="grid gap-3 sm:grid-cols-2">
            <label className="block">
              <span className="mb-1 block text-xs uppercase tracking-wider text-white/50">
                Importer (multi-sélection)
              </span>
              <input
                type="file"
                multiple
                accept="image/jpeg,image/png,image/webp,image/heic,image/heif,application/pdf"
                disabled={busy}
                onChange={(e) => {
                  const files = Array.from(e.target.files ?? []);
                  e.target.value = "";
                  if (files.length) upload(files);
                }}
                className="block w-full text-sm text-white/70 file:mr-3 file:rounded-md file:border-0 file:bg-accent-500 file:px-3 file:py-2 file:text-sm file:font-semibold file:text-brand-950 hover:file:bg-accent-400"
              />
            </label>
            <label className="block">
              <span className="mb-1 block text-xs uppercase tracking-wider text-white/50">
                Caméra (mobile)
              </span>
              <input
                type="file"
                accept="image/*"
                capture="environment"
                disabled={busy}
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  e.target.value = "";
                  if (f) upload([f]);
                }}
                className="block w-full text-sm text-white/70 file:mr-3 file:rounded-md file:border-0 file:bg-accent-500 file:px-3 file:py-2 file:text-sm file:font-semibold file:text-brand-950 hover:file:bg-accent-400"
              />
            </label>
          </div>
        </div>
        {progress ? (
          <p className="mt-3 text-sm text-white/70">
            Upload en cours… {progress.done}/{progress.total}
          </p>
        ) : null}
        {err ? (
          <p className="mt-3 text-sm text-rose-300">{err}</p>
        ) : null}
      </section>

      <section>
        {loading ? (
          <div className="flex min-h-[30vh] items-center justify-center">
            <Loader2 className="h-6 w-6 animate-spin text-accent-500" />
          </div>
        ) : photos.length === 0 ? (
          <p className="rounded-xl border border-dashed border-brand-800 bg-brand-900/40 px-6 py-10 text-center text-sm text-white/60">
            Aucune photo pour ce projet.
          </p>
        ) : (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {photos.map((p) => (
              <div
                key={p.id}
                className="rounded-xl border border-brand-800 bg-brand-900 p-3"
              >
                <button
                  type="button"
                  onClick={() => openImage(p)}
                  className="block aspect-video w-full overflow-hidden rounded-lg bg-brand-950"
                >
                  {p.content_type === "application/pdf" ? (
                    <div className="flex h-full items-center justify-center text-sm text-white/60">
                      📄 PDF
                    </div>
                  ) : photoUrls[p.id] ? (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img
                      src={photoUrls[p.id]}
                      alt={p.caption || ""}
                      className="h-full w-full object-cover"
                      loading="lazy"
                    />
                  ) : (
                    <div className="flex h-full items-center justify-center text-xs text-white/30">
                      Chargement…
                    </div>
                  )}
                </button>
                <p className="mt-2 line-clamp-2 text-xs text-white/80">
                  {p.caption || <span className="text-white/40">Sans légende</span>}
                </p>
                <div className="mt-1 flex items-center justify-between text-[10px] text-white/40">
                  <span>
                    {new Date(p.created_at).toLocaleDateString("fr-CA")}
                  </span>
                  <button
                    type="button"
                    onClick={() => remove(p.id)}
                    className="text-rose-400 hover:text-rose-300"
                    aria-label="Supprimer"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}

type Task = {
  id: number;
  project_id: number;
  title: string;
  description: string | null;
  assignee_id: number | null;
  due_date: string | null;
  done: boolean;
  done_at: string | null;
  position: number;
  created_at: string;
};

function TasksTab({ projectId }: { projectId: number }) {
  const confirm = useConfirm();
  const [tasks, setTasks] = useState<Task[]>([]);
  const [employes, setEmployes] = useState<Array<{ id: number; full_name: string }>>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  const [newTitle, setNewTitle] = useState("");
  const [newAssignee, setNewAssignee] = useState("");
  const [newDue, setNewDue] = useState("");
  const [creating, setCreating] = useState(false);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      try {
        const [tRes, eRes] = await Promise.all([
          authedFetch(`/api/v1/projects/${projectId}/tasks`),
          authedFetch("/api/v1/employes?limit=500&volet=construction")
        ]);
        if (!tRes.ok) throw new Error();
        const ts = (await tRes.json()) as Task[];
        const es = eRes.ok
          ? ((await eRes.json()) as Array<{ id: number; full_name: string }>)
          : [];
        if (cancelled) return;
        setTasks(ts);
        setEmployes(es);
      } catch {
        if (!cancelled) setErr("Chargement échoué.");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  async function addTask() {
    if (!newTitle.trim()) return;
    setCreating(true);
    try {
      const payload: Record<string, unknown> = {
        title: newTitle.trim(),
        position: tasks.length
      };
      if (newAssignee) payload.assignee_id = Number(newAssignee);
      if (newDue) payload.due_date = newDue;
      const res = await authedFetch(
        `/api/v1/projects/${projectId}/tasks`,
        { method: "POST", body: JSON.stringify(payload) }
      );
      if (!res.ok) throw new Error();
      const created = (await res.json()) as Task;
      setTasks((xs) => [...xs, created]);
      setNewTitle("");
      setNewAssignee("");
      setNewDue("");
    } catch {
      setErr("Ajout échoué.");
    } finally {
      setCreating(false);
    }
  }

  async function toggleDone(t: Task) {
    try {
      const res = await authedFetch(
        `/api/v1/projects/${projectId}/tasks/${t.id}`,
        { method: "PATCH", body: JSON.stringify({ done: !t.done }) }
      );
      if (!res.ok) throw new Error();
      const updated = (await res.json()) as Task;
      setTasks((xs) => xs.map((x) => (x.id === t.id ? updated : x)));
    } catch {
      setErr("Mise à jour échouée.");
    }
  }

  async function remove(id: number) {
    if (!(await confirm("Supprimer cette tâche ?"))) return;
    try {
      const res = await authedFetch(
        `/api/v1/projects/${projectId}/tasks/${id}`,
        { method: "DELETE" }
      );
      if (!res.ok && res.status !== 204) throw new Error();
      setTasks((xs) => xs.filter((x) => x.id !== id));
    } catch {
      setErr("Suppression échouée.");
    }
  }

  const empName = (id: number | null) =>
    id ? employes.find((e) => e.id === id)?.full_name || `#${id}` : "—";

  return (
    <div className="space-y-5">
      <section className="rounded-xl border border-brand-800 bg-brand-900 p-5">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-accent-500">
          Nouvelle tâche
        </h2>
        <div className="mt-4 grid gap-3 sm:grid-cols-[1fr_220px_180px_auto]">
          <input
            type="text"
            value={newTitle}
            onChange={(e) => setNewTitle(e.target.value)}
            placeholder="Ex. Plomberie brute 2e étage"
            className="input"
          />
          <select
            value={newAssignee}
            onChange={(e) => setNewAssignee(e.target.value)}
            className="input"
          >
            <option value="">— Assigner à —</option>
            {employes.map((e) => (
              <option key={e.id} value={String(e.id)}>
                {e.full_name}
              </option>
            ))}
          </select>
          <input
            type="date"
            value={newDue}
            onChange={(e) => setNewDue(e.target.value)}
            className="input"
          />
          <button
            type="button"
            onClick={addTask}
            disabled={creating || !newTitle.trim()}
            className="btn-accent text-sm"
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

      <section className="rounded-xl border border-brand-800 bg-brand-900">
        {loading ? (
          <div className="flex min-h-[30vh] items-center justify-center">
            <Loader2 className="h-6 w-6 animate-spin text-accent-500" />
          </div>
        ) : tasks.length === 0 ? (
          <p className="px-5 py-8 text-center text-sm text-white/60">
            Aucune tâche pour ce projet.
          </p>
        ) : (
          <ul className="divide-y divide-brand-800">
            {tasks.map((t) => (
              <li
                key={t.id}
                className="flex items-start gap-3 px-4 py-3 text-sm"
              >
                <input
                  type="checkbox"
                  checked={t.done}
                  onChange={() => toggleDone(t)}
                  className="mt-1 h-4 w-4"
                />
                <div className="min-w-0 flex-1">
                  <p
                    className={`truncate font-medium ${
                      t.done ? "text-white/40 line-through" : "text-white"
                    }`}
                  >
                    {t.title}
                  </p>
                  <div className="mt-1 flex flex-wrap items-center gap-2 text-[11px] text-white/50">
                    <span>Assigné : {empName(t.assignee_id)}</span>
                    {t.due_date ? (
                      <span>Échéance : {t.due_date}</span>
                    ) : null}
                    {t.done && t.done_at ? (
                      <span className="text-emerald-300">
                        Fait {new Date(t.done_at).toLocaleDateString("fr-CA")}
                      </span>
                    ) : null}
                  </div>
                </div>
                <button
                  type="button"
                  onClick={() => remove(t.id)}
                  className="text-rose-400 hover:text-rose-300"
                  aria-label="Supprimer"
                >
                  <Trash2 className="h-4 w-4" />
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

type InvoiceLine = {
  id: number;
  reference: string;
  status: string;
  total: number;
  issued_at: string | null;
  due_at: string | null;
  paid_at: string | null;
  paid_amount: number;
};

type Finances = {
  projected_revenue: number;
  projected_revenue_ex_tax: number;
  projected_service_cost: number;
  projected_labour_cost: number;
  projected_labour_hours: number;
  projected_total_cost: number;
  projected_profit: number;
  projected_margin_pct: number;
  actual_material_cost: number;
  actual_material_cost_ht?: number;
  actual_labour_cost: number;
  actual_labour_hours: number;
  actual_total_cost: number;
  actual_total_cost_ht: number;
  actual_profit: number;
  actual_margin_pct: number;
  billing_kind: string;
  service_lines: { label: string; quantity: number; unit_cost: number; total: number }[];
  material_lines: { label: string; quantity: number; unit_cost: number; total: number }[];
  invoiced_amount: number;
  invoiced_amount_ex_tax: number;
  extras_billed_amount: number;
  rabais_billed_amount?: number;
  rabais_billed_amount_ttc?: number;
  paid_amount: number;
  balance_due: number;
  tps_collected: number;
  tvq_collected: number;
  taxes_collected: number;
  facture_ht_base?: number;
  tps_percue?: number;
  tvq_percue?: number;
  tps_paid_on_purchases?: number;
  tvq_paid_on_purchases?: number;
  net_tps_to_remit?: number;
  net_tvq_to_remit?: number;
  net_taxes_to_remit?: number;
  invoices?: InvoiceLine[];
};

// ─── Cartes de synthèse (délai + avancement contrat) réutilisées
//     dans l'onglet « Récap & finances » ────────────────────────

function RecapDelayCard({
  plannedDays,
  actualDays,
  overrunDays,
  endDate,
  isDelivered
}: {
  plannedDays: number | null;
  actualDays: number | null;
  overrunDays: number | null;
  endDate: Date | null;
  isDelivered: boolean;
}) {
  let pillCls = "bg-emerald-500/15 text-emerald-300 border-emerald-500/30";
  let label = "Dans les temps";
  let detail = "";
  if (overrunDays != null) {
    if (overrunDays > 0) {
      pillCls = "bg-rose-500/15 text-rose-300 border-rose-500/30";
      label = `${overrunDays} jour${overrunDays > 1 ? "s" : ""} de retard`;
      detail = isDelivered
        ? "Livré au-delà de la date prévue."
        : "La date de fin prévue est dépassée.";
    } else if (overrunDays < 0) {
      label = `${-overrunDays} jour${
        -overrunDays > 1 ? "s" : ""
      } d'avance`;
      detail = isDelivered
        ? "Livré avant la date prévue. Bravo."
        : "Date de fin prévue pas encore atteinte.";
    } else {
      label = "Pile à la date prévue";
    }
  }

  return (
    <div className="rounded-xl border border-brand-800 bg-brand-900 p-4">
      <h3 className="text-[10px] uppercase tracking-wider text-white/50">
        Délai
      </h3>
      <span
        className={`mt-2 inline-flex rounded-full border px-2 py-0.5 text-[11px] font-semibold ${pillCls}`}
      >
        {label}
      </span>
      <div className="mt-3 grid grid-cols-2 gap-2 text-sm">
        <div>
          <p className="text-[10px] text-white/40">Jours prévus</p>
          <p className="text-base font-semibold text-white">
            {plannedDays != null ? `${plannedDays} j` : "—"}
          </p>
        </div>
        <div>
          <p className="text-[10px] text-white/40">
            Jours {isDelivered ? "réels" : "écoulés"}
          </p>
          <p className="text-base font-semibold text-white">
            {actualDays != null ? `${actualDays} j` : "—"}
          </p>
        </div>
      </div>
      {endDate ? (
        <p className="mt-2 text-[10px] text-white/40">
          Fin prévue :{" "}
          {endDate.toLocaleDateString("fr-CA", {
            day: "2-digit",
            month: "short",
            year: "numeric"
          })}
        </p>
      ) : null}
      {detail ? (
        <p className="mt-1 text-[10px] text-white/50">{detail}</p>
      ) : null}
    </div>
  );
}

function RecapContractProgressCard({
  actualCost,
  contractRevenueExTax,
  invoicedExTax,
  paidAmount,
  invoicedAmount,
  rabaisBilled = 0
}: {
  actualCost: number;
  contractRevenueExTax: number;
  invoicedExTax: number;
  paidAmount: number;
  invoicedAmount: number;
  rabaisBilled?: number;
}) {
  // Montant utilisé sur la soumission = part du total soumissionné (HT)
  // déjà consommée par les coûts réels. L'idée : voir d'un coup d'œil si on
  // a déjà brûlé 90 % du montant soumissionné → signal d'alerte. (Ce n'est
  // PAS un avancement d'exécution du contrat, juste coût réel / soumission.)
  const pctSpent =
    contractRevenueExTax > 0
      ? Math.min(200, (actualCost / contractRevenueExTax) * 100)
      : 0;
  const remainingBudget = Math.max(0, contractRevenueExTax - actualCost);
  // Base facturée vs extras facturés (au-delà du contrat initial).
  const baseInvoiced = Math.min(invoicedExTax, contractRevenueExTax);
  const extrasInvoiced = Math.max(0, invoicedExTax - contractRevenueExTax);
  // Un rabais réduit le montant à facturer : il ne reste rien à facturer
  // pour la part « offerte ». On le déduit donc du reste à facturer.
  const baseRemaining = Math.max(
    0,
    contractRevenueExTax - baseInvoiced - rabaisBilled
  );
  const balanceDue = Math.max(0, invoicedAmount - paidAmount);
  const overRun = actualCost > contractRevenueExTax;

  if (contractRevenueExTax <= 0) return null;

  return (
    <div className="rounded-xl border border-brand-800 bg-brand-900 p-4">
      <div className="flex items-center justify-between">
        <h3 className="text-[10px] uppercase tracking-wider text-white/50">
          Montant utilisé sur la soumission
        </h3>
        <span
          className={`rounded-full border px-2 py-0.5 text-[11px] font-semibold ${
            overRun
              ? "border-rose-500/40 bg-rose-500/15 text-rose-300"
              : pctSpent > 80
                ? "border-amber-500/40 bg-amber-500/15 text-amber-300"
                : "border-emerald-500/40 bg-emerald-500/15 text-emerald-300"
          }`}
        >
          {pctSpent.toFixed(0)} % consommé
        </span>
      </div>
      <div className="mt-3 h-2 overflow-hidden rounded-full bg-brand-950">
        <div
          className={`h-full ${
            overRun
              ? "bg-rose-500"
              : pctSpent > 80
                ? "bg-amber-500"
                : "bg-emerald-500"
          }`}
          style={{ width: `${Math.min(100, pctSpent)}%` }}
        />
      </div>
      <div className="mt-3 grid grid-cols-2 gap-3 text-xs">
        <div>
          <p className="text-white/50">Soumission acceptée (HT)</p>
          <p className="font-mono text-base font-semibold text-white">
            {fmtMoney(contractRevenueExTax)}
          </p>
        </div>
        <div>
          <p className="text-white/50">Coût réel à ce jour</p>
          <p
            className={`font-mono text-base font-semibold ${
              overRun ? "text-rose-300" : "text-white"
            }`}
          >
            {fmtMoney(actualCost)}
          </p>
        </div>
        <div>
          <p className="text-white/50">
            {overRun ? "Dépassement" : "Reste avant dépassement"}
          </p>
          <p
            className={`font-mono text-sm font-semibold ${
              overRun ? "text-rose-300" : "text-emerald-300"
            }`}
          >
            {overRun
              ? `−${fmtMoney(actualCost - contractRevenueExTax)}`
              : fmtMoney(remainingBudget)}
          </p>
        </div>
        <div>
          <p className="text-white/50">Reste à facturer (base)</p>
          <p className="font-mono text-sm font-semibold text-white/90">
            {fmtMoney(baseRemaining)}
          </p>
        </div>
      </div>
      <div className="mt-3 space-y-1 border-t border-brand-800 pt-3 text-xs">
        <div className="flex justify-between">
          <span className="text-white/60">Facturé sur la base</span>
          <span className="font-mono text-white">
            {fmtMoney(baseInvoiced)}
          </span>
        </div>
        {rabaisBilled > 0 ? (
          <div className="flex justify-between">
            <span className="text-white/60">Rabais appliqué</span>
            <span className="font-mono text-rose-300">
              −{fmtMoney(rabaisBilled)}
            </span>
          </div>
        ) : null}
        {extrasInvoiced > 0 ? (
          <div className="flex justify-between">
            <span className="text-white/60">Facturé en extras</span>
            <span className="font-mono text-amber-300">
              +{fmtMoney(extrasInvoiced)}
            </span>
          </div>
        ) : null}
        <div className="flex justify-between border-t border-brand-800 pt-1 font-semibold">
          <span className="text-white">Client nous doit</span>
          <span
            className={`font-mono ${
              balanceDue > 0 ? "text-amber-300" : "text-emerald-300"
            }`}
          >
            {fmtMoney(balanceDue)}
          </span>
        </div>
      </div>
    </div>
  );
}

function FinancesTab({
  projectId,
  project
}: {
  projectId: number;
  project: Project | null;
}) {
  const [data, setData] = useState<Finances | null>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  // Heures estimées manuelles (override). Chargées depuis le projet
  // (champ estimated_hours_override) — quand non null, prend le pas
  // sur le calcul auto somme-des-phases.
  const [overrideHours, setOverrideHours] = useState<string>("");
  const [overrideOriginal, setOverrideOriginal] = useState<string>("");
  const [editingHours, setEditingHours] = useState(false);
  const [savingHours, setSavingHours] = useState(false);
  const [sendingStatement, setSendingStatement] = useState(false);
  const [statementMsg, setStatementMsg] = useState<string | null>(null);
  // Section « Coûts réels (achats) » repliée par défaut — souvent une
  // longue liste ; on l'ouvre au clic sur l'en-tête.
  const [achatsOpen, setAchatsOpen] = useState(false);

  async function loadAll() {
    setLoading(true);
    try {
      const [finRes, projRes] = await Promise.all([
        authedFetch(`/api/v1/projects/${projectId}/finances`),
        authedFetch(`/api/v1/projects/${projectId}`)
      ]);
      if (!finRes.ok) {
        const txt = await finRes.text().catch(() => "");
        throw new Error(
          `HTTP ${finRes.status}${txt ? ` — ${txt.slice(0, 240)}` : ""}`
        );
      }
      setData((await finRes.json()) as Finances);
      if (projRes.ok) {
        const p = (await projRes.json()) as {
          estimated_hours_override?: number | string | null;
        };
        const v =
          p.estimated_hours_override != null
            ? String(p.estimated_hours_override)
            : "";
        setOverrideHours(v);
        setOverrideOriginal(v);
      }
    } catch (e) {
      setErr(`Chargement des finances échoué : ${(e as Error).message}`);
    } finally {
      setLoading(false);
    }
  }

  async function openStatement() {
    try {
      const res = await authedFetch(
        `/api/v1/projects/${projectId}/statement.pdf`
      );
      if (!res.ok) throw new Error(`http_${res.status}`);
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      window.open(url, "_blank", "noopener,noreferrer");
      setTimeout(() => URL.revokeObjectURL(url), 60_000);
    } catch (e) {
      setErr(
        `Ouverture de l'état de compte échouée : ${(e as Error).message}`
      );
    }
  }

  async function sendStatement() {
    if (sendingStatement) return;
    setSendingStatement(true);
    setStatementMsg(null);
    setErr(null);
    try {
      const res = await authedFetch(
        `/api/v1/projects/${projectId}/statement/send`,
        { method: "POST" }
      );
      if (!res.ok) {
        let detail = `http_${res.status}`;
        try {
          const j = (await res.json()) as { detail?: string };
          if (j.detail) detail = j.detail;
        } catch {
          /* ignore */
        }
        throw new Error(detail);
      }
      const j = (await res.json()) as { to?: string };
      setStatementMsg(
        j.to
          ? `État de compte envoyé à ${j.to}.`
          : "État de compte envoyé au client."
      );
    } catch (e) {
      setErr(`Envoi de l'état de compte échoué : ${(e as Error).message}`);
    } finally {
      setSendingStatement(false);
    }
  }

  async function saveOverrideHours() {
    setSavingHours(true);
    try {
      const value =
        overrideHours.trim() === "" ? null : Number(overrideHours);
      const res = await authedFetch(`/api/v1/projects/${projectId}`, {
        method: "PATCH",
        body: JSON.stringify({ estimated_hours_override: value })
      });
      if (!res.ok) throw new Error();
      setOverrideOriginal(overrideHours);
      setEditingHours(false);
      // Recharge les finances pour voir l'impact (nouvelles heures
      // prévues + nouveau coût main-d'œuvre prévu).
      await loadAll();
    } catch {
      setErr("Sauvegarde des heures estimées échouée.");
    } finally {
      setSavingHours(false);
    }
  }

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      try {
        const [finRes, projRes] = await Promise.all([
          authedFetch(`/api/v1/projects/${projectId}/finances`),
          authedFetch(`/api/v1/projects/${projectId}`)
        ]);
        if (!finRes.ok) {
          const txt = await finRes.text().catch(() => "");
          throw new Error(
            `HTTP ${finRes.status}${txt ? ` — ${txt.slice(0, 240)}` : ""}`
          );
        }
        if (!cancelled) setData((await finRes.json()) as Finances);
        if (projRes.ok && !cancelled) {
          const p = (await projRes.json()) as {
            estimated_hours_override?: number | string | null;
          };
          const v =
            p.estimated_hours_override != null
              ? String(p.estimated_hours_override)
              : "";
          setOverrideHours(v);
          setOverrideOriginal(v);
        }
      } catch (e) {
        if (!cancelled)
          setErr(
            `Chargement des finances échoué : ${(e as Error).message}`
          );
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

  // Délai (anciennement dans l'onglet Récap) : prévu vs réel.
  const parseDate = (s: string | null): Date | null => {
    if (!s) return null;
    const [y, m, d] = s.split("-").map(Number);
    if (!y || !m || !d) return null;
    return new Date(y, m - 1, d);
  };
  const startDate = parseDate(project?.start_date ?? null);
  const endDate = parseDate(project?.end_date ?? null);
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const isDelivered = project?.status === "delivered";
  const actualEnd = isDelivered ? new Date(project!.updated_at) : today;
  actualEnd.setHours(0, 0, 0, 0);
  const plannedDays =
    startDate && endDate
      ? Math.round((endDate.getTime() - startDate.getTime()) / 86_400_000) + 1
      : null;
  const actualDays = startDate
    ? Math.round((actualEnd.getTime() - startDate.getTime()) / 86_400_000) + 1
    : null;
  const overrunDays = endDate
    ? Math.round((actualEnd.getTime() - endDate.getTime()) / 86_400_000)
    : null;
  // Gain (ou perte) de profit par rapport au prévu.
  const profitDiff = data.actual_profit - data.projected_profit;

  return (
    <div className="space-y-5">
      {/* Délai prévu vs réel (synthèse importée du Récap). */}
      {project ? (
        <RecapDelayCard
          plannedDays={plannedDays}
          actualDays={actualDays}
          overrunDays={overrunDays}
          endDate={endDate}
          isDelivered={!!isDelivered}
        />
      ) : null}

      {/* KPIs : projection vs réel — coût et profit côte à côte
          pour comparer ce qui était prévu et ce qui se matérialise. */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <FinanceKpi
          label="Coût projeté (TTC)"
          value={fmtMoney(data.projected_total_cost)}
          sub={`Services ${fmtMoney(
            data.projected_service_cost
          )} · Main-d'œuvre ${fmtMoney(data.projected_labour_cost)}`}
          tone="white"
        />
        <FinanceKpi
          label="Profit projeté"
          value={fmtMoney(data.projected_profit)}
          sub={`${data.projected_margin_pct.toFixed(1)} % marge · Revenu HT ${fmtMoney(data.projected_revenue_ex_tax)}`}
          tone={data.projected_profit >= 0 ? "emerald" : "rose"}
        />
        <FinanceKpi
          label="Coût actuel (TTC)"
          value={fmtMoney(data.actual_total_cost)}
          sub={`Matériaux ${fmtMoney(
            data.actual_material_cost
          )} · Main-d'œuvre ${fmtMoney(data.actual_labour_cost)}`}
          tone="white"
        />
        <FinanceKpi
          label="Profit réel"
          value={fmtMoney(data.actual_profit)}
          sub={`${data.actual_margin_pct.toFixed(1)} % marge · ${
            profitDiff >= 0 ? "+" : ""
          }${fmtMoney(profitDiff)} vs prévu · hors taxes${
            data.billing_kind === "forfaitaire"
              ? ""
              : " · basé sur le facturé"
          }`}
          tone={data.actual_profit >= 0 ? "emerald" : "rose"}
        />
      </div>

      {/* Décomposition du profit réel — TOUT en HT, taxes retirées.
          Séparé du bloc taxes pour éviter toute confusion. */}
      <div className="rounded-xl border border-brand-800 bg-brand-900 p-5">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold uppercase tracking-wider text-accent-500">
            Profit réel
          </h3>
          <span
            className={`text-base font-bold ${
              data.actual_profit >= 0 ? "text-emerald-300" : "text-rose-300"
            }`}
          >
            {fmtMoney(data.actual_profit)}{" "}
            <span className="text-xs font-normal text-white/50">
              ({data.actual_margin_pct.toFixed(1)} %)
            </span>
          </span>
        </div>
        <dl className="mt-3 space-y-1 text-sm">
          <div className="flex justify-between">
            <dt className="text-white/60">Revenu (HT)</dt>
            <dd className="font-mono text-white/90">
              {fmtMoney(
                data.billing_kind === "forfaitaire"
                  ? data.projected_revenue_ex_tax +
                      (data.extras_billed_amount || 0) -
                      (data.rabais_billed_amount || 0)
                  : data.invoiced_amount_ex_tax
              )}
            </dd>
          </div>
          <div className="flex justify-between">
            <dt className="text-white/60">
              − Matériaux{" "}
              <span className="text-[10px] text-white/40">
                (HT, taxes retirées)
              </span>
            </dt>
            <dd className="font-mono text-white/90">
              {fmtMoney(
                data.actual_material_cost_ht ?? data.actual_material_cost
              )}
            </dd>
          </div>
          <div className="flex justify-between">
            <dt className="text-white/60">
              − Main-d&apos;œuvre{" "}
              <span className="text-[10px] text-white/40">
                ({data.actual_labour_hours.toFixed(1)} h)
              </span>
            </dt>
            <dd className="font-mono text-white/90">
              {fmtMoney(data.actual_labour_cost)}
            </dd>
          </div>
          <div className="flex justify-between border-t border-brand-800 pt-1">
            <dt className="font-semibold text-white">= Profit réel</dt>
            <dd
              className={`font-mono font-bold ${
                data.actual_profit >= 0 ? "text-emerald-300" : "text-rose-300"
              }`}
            >
              {fmtMoney(data.actual_profit)}
            </dd>
          </div>
        </dl>
        <p className="mt-2 text-[10px] text-white/40">
          Calcul 100 % hors taxes. Les taxes payées sur les matériaux sont
          récupérées (CTI/RTI) → exclues du coût. Indépendant du montant
          facturé.
        </p>
      </div>

      {/* Montant utilisé sur la soumission — coût réel vs soumission
          acceptée (synthèse importée du Récap). */}
      <RecapContractProgressCard
        actualCost={data.actual_total_cost_ht}
        contractRevenueExTax={data.projected_revenue_ex_tax}
        invoicedExTax={data.invoiced_amount_ex_tax}
        paidAmount={data.paid_amount}
        invoicedAmount={data.invoiced_amount}
        rabaisBilled={data.rabais_billed_amount ?? 0}
      />

      {/* Labour budget vs actual */}
      <section className="rounded-xl border border-brand-800 bg-brand-900 p-5">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h3 className="text-sm font-semibold uppercase tracking-wider text-accent-500">
            Main-d&apos;œuvre
          </h3>
          {!editingHours ? (
            <button
              type="button"
              onClick={() => setEditingHours(true)}
              className="text-[11px] text-accent-300 underline decoration-dotted hover:text-accent-200"
            >
              ✏️ Modifier l&apos;estimation d&apos;heures
            </button>
          ) : null}
        </div>
        <p className="mt-1 text-[11px] text-white/50">
          {overrideOriginal !== "" ? (
            <>
              Heures fixées manuellement : <strong>{overrideOriginal} h</strong>.
              Le calcul automatique (somme des phases) est ignoré.
            </>
          ) : (
            <>
              Calcul automatique : somme des phases (durée × 8 h ×
              personnes assignées), jours ouvrables seulement.
              Tu peux fixer un total manuel pour overrider.
            </>
          )}
          {" "}Coût horaire = taux base × (1 + prime CNESST + prime CCQ).
        </p>

        {editingHours ? (
          <div className="mt-3 rounded-lg border border-accent-500/30 bg-accent-500/5 p-3">
            <label
              htmlFor="hours_estimate"
              className="text-[11px] uppercase tracking-wider text-accent-300"
            >
              Heures estimées du projet
            </label>
            <div className="mt-1 flex flex-wrap items-center gap-2">
              <input
                id="hours_estimate"
                type="number"
                step="0.5"
                min="0"
                value={overrideHours}
                onChange={(e) => setOverrideHours(e.target.value)}
                placeholder="Laisse vide = calcul auto"
                className="input w-44"
              />
              <span className="text-xs text-white/50">heures</span>
              <button
                type="button"
                onClick={saveOverrideHours}
                disabled={savingHours}
                className="btn-accent text-xs"
              >
                {savingHours ? "Enregistrement…" : "Enregistrer"}
              </button>
              <button
                type="button"
                onClick={() => {
                  setEditingHours(false);
                  setOverrideHours(overrideOriginal);
                }}
                disabled={savingHours}
                className="btn-secondary text-xs"
              >
                Annuler
              </button>
            </div>
            <p className="mt-2 text-[11px] text-white/60">
              Saisis le nombre d&apos;heures total estimé pour le
              chantier (ex. 120 h pour une réno de salle de bain
              standard). Laisse vide pour revenir au calcul automatique
              à partir des phases planifiées.
            </p>
          </div>
        ) : null}

        <div className="mt-4 grid gap-4 sm:grid-cols-2">
          <div>
            <p className="text-xs text-white/50">
              Prévue
              {overrideOriginal !== "" ? (
                <span className="ml-1 text-[10px] text-accent-400">
                  (manuel)
                </span>
              ) : (
                <span className="ml-1 text-[10px] text-white/40">
                  (auto)
                </span>
              )}
            </p>
            <p className="mt-1 text-lg font-bold text-white">
              {data.projected_labour_hours.toFixed(0)} h
            </p>
            <p className="text-xs text-white/60">
              {fmtMoney(data.projected_labour_cost)}
            </p>
          </div>
          <div>
            <p className="text-xs text-white/50">Réelle (punches)</p>
            <p className="mt-1 text-lg font-bold text-white">
              {data.actual_labour_hours.toFixed(1)} h
            </p>
            <p className="text-xs text-white/60">
              {fmtMoney(data.actual_labour_cost)}
            </p>
          </div>
        </div>
        {data.projected_labour_hours > 0 ? (
          <>
            <div className="mt-4 h-2 overflow-hidden rounded-full bg-brand-950">
              <div
                className={`h-full ${
                  data.actual_labour_hours > data.projected_labour_hours
                    ? "bg-rose-500"
                    : "bg-emerald-500"
                }`}
                style={{
                  width: `${Math.min(
                    100,
                    (data.actual_labour_hours / data.projected_labour_hours) *
                      100
                  )}%`
                }}
              />
            </div>
            <p className="mt-1 text-[11px] text-white/50">
              {Math.round(
                (data.actual_labour_hours / data.projected_labour_hours) * 100
              )}{" "}
              % des heures prévues consommées
            </p>
          </>
        ) : null}
      </section>

      {/* Total facturé — affiché AU-DESSUS des coûts. Basé UNIQUEMENT sur
          les factures ENVOYÉES au client (les brouillons ne comptent pas). */}
      <section className="rounded-xl border border-emerald-500/40 bg-emerald-500/5 p-5">
        <div className="flex items-center justify-between gap-3">
          <h3 className="text-sm font-semibold uppercase tracking-wider text-accent-500">
            Total facturé
          </h3>
          <span className="text-2xl font-bold text-emerald-300">
            {fmtMoney(data.invoiced_amount)}
          </span>
        </div>
        <p className="mt-1 text-xs text-white/50">
          Factures envoyées au client — les brouillons ne sont pas comptés.
        </p>
      </section>

      {/* Service lines */}
      <section className="rounded-xl border border-brand-800 bg-brand-900 p-5">
        <h3 className="text-sm font-semibold uppercase tracking-wider text-accent-500">
          Coût des services (soumission)
        </h3>
        {data.service_lines.length === 0 ? (
          <p className="mt-3 text-xs text-white/50">
            Aucun service lié à ce projet.
          </p>
        ) : (
          <table className="mt-3 w-full text-sm">
            <thead className="border-b border-brand-800 text-xs uppercase tracking-wider text-white/50">
              <tr>
                <th className="py-2 text-left">Nom</th>
                <th className="py-2 text-right">Qté</th>
                <th className="py-2 text-right">Coût/unité</th>
                <th className="py-2 text-right">Total</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-brand-800">
              {data.service_lines.map((l, i) => (
                <tr key={i}>
                  <td className="py-2 text-white">{l.label}</td>
                  <td className="py-2 text-right text-white/70">
                    {l.quantity}
                  </td>
                  <td className="py-2 text-right text-white/70">
                    {fmtMoney(l.unit_cost)}
                  </td>
                  <td className="py-2 text-right font-semibold text-white">
                    {fmtMoney(l.total)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      {/* Material (achats) — repliée par défaut, on déplie au clic. */}
      <section className="rounded-xl border border-brand-800 bg-brand-900 p-5">
        <button
          type="button"
          onClick={() => setAchatsOpen((v) => !v)}
          aria-expanded={achatsOpen}
          className="flex w-full items-center justify-between gap-2 text-left"
        >
          <span className="flex items-center gap-2">
            <ChevronRight
              className={`h-4 w-4 text-white/50 transition-transform ${
                achatsOpen ? "rotate-90" : ""
              }`}
            />
            <span className="text-sm font-semibold uppercase tracking-wider text-accent-500">
              Coûts réels (achats)
            </span>
          </span>
          <span className="flex items-center gap-2 text-xs text-white/50">
            <span>
              {data.material_lines.length}{" "}
              {data.material_lines.length > 1 ? "achats" : "achat"}
            </span>
            <span className="font-mono text-sm font-bold text-white">
              {fmtMoney(data.actual_material_cost)}
            </span>
          </span>
        </button>
        {!achatsOpen ? null : data.material_lines.length === 0 ? (
          <p className="mt-3 text-xs text-white/50">
            Aucun achat enregistré sur ce projet.
          </p>
        ) : (
          <table className="mt-3 w-full text-sm">
            <thead className="border-b border-brand-800 text-xs uppercase tracking-wider text-white/50">
              <tr>
                <th className="py-2 text-left">Description</th>
                <th className="py-2 text-right">Total</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-brand-800">
              {data.material_lines.map((l, i) => (
                <tr key={i}>
                  <td className="py-2 text-white">{l.label}</td>
                  <td className="py-2 text-right font-semibold text-white">
                    {fmtMoney(l.total)}
                  </td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr className="border-t border-brand-800">
                <td className="py-2 text-right text-xs text-white/60">
                  Total achats
                </td>
                <td className="py-2 text-right text-sm font-bold text-white">
                  {fmtMoney(data.actual_material_cost)}
                </td>
              </tr>
            </tfoot>
          </table>
        )}
      </section>

      {/* Invoicing */}
      <section className="rounded-xl border border-brand-800 bg-brand-900 p-5">
        <h3 className="text-sm font-semibold uppercase tracking-wider text-accent-500">
          Facturation
        </h3>
        <dl className="mt-3 space-y-1 text-sm">
          {data.projected_revenue > 0 ? (
            <div className="flex justify-between">
              <dt className="text-white/60">Total du contrat</dt>
              <dd className="font-semibold text-white/80">
                {fmtMoney(data.projected_revenue)}
              </dd>
            </div>
          ) : null}
          <div className="flex justify-between">
            <dt className="text-white/60">Facturé</dt>
            <dd className="font-semibold text-white">
              {fmtMoney(data.invoiced_amount)}
              {data.projected_revenue > 0 ? (
                <span className="ml-1.5 text-[11px] font-normal text-white/40">
                  ({Math.round(
                    (data.invoiced_amount / data.projected_revenue) * 100
                  )}{" "}
                  %)
                </span>
              ) : null}
            </dd>
          </div>
          {data.extras_billed_amount > 0 ? (
            <div className="flex justify-between text-[12px]">
              <dt className="text-white/50">
                dont extras (hors soumission)
              </dt>
              <dd className="text-amber-300">
                {fmtMoney(data.extras_billed_amount)}
              </dd>
            </div>
          ) : null}
          {data.projected_revenue > 0 ? (() => {
            // Le « reste à facturer » porte uniquement sur le contrat
            // (soumission). On retire la part extras du facturé pour
            // ne pas fausser le calcul. Un rabais (réduction volontaire
            // du prix) déduit aussi le reste : on l'ajoute donc au
            // facturé contrat (TTC) pour ne pas créer de faux reste.
            const contractInvoiced = Math.max(
              0,
              data.invoiced_amount -
                (data.extras_billed_amount || 0) +
                (data.rabais_billed_amount_ttc || 0)
            );
            const remaining = Math.max(
              0,
              data.projected_revenue - contractInvoiced
            );
            return (
              <div className="flex justify-between">
                <dt className="text-white/60">Reste à facturer</dt>
                <dd
                  className={`font-bold ${
                    remaining > 0 ? "text-amber-300" : "text-emerald-300"
                  }`}
                >
                  {fmtMoney(remaining)}
                </dd>
              </div>
            );
          })() : null}
          <div className="flex justify-between">
            <dt className="text-white/60">Reçu</dt>
            <dd className="font-semibold text-emerald-300">
              {fmtMoney(data.paid_amount)}
            </dd>
          </div>
          <div className="flex justify-between border-t border-brand-800 pt-1">
            <dt className="text-white/60">Solde dû</dt>
            <dd
              className={`font-bold ${
                data.balance_due > 0 ? "text-rose-300" : "text-emerald-300"
              }`}
            >
              {fmtMoney(data.balance_due)}
            </dd>
          </div>
        </dl>

        {/* Taxes à remettre — base = montant FACTURÉ (pas le contrat).
            Perçue sur ventes − récupérée sur achats (CTI/RTI). N'entre
            JAMAIS dans le calcul du profit. Se recalcule à chaque
            facture / avenant / rabais. */}
        {data.taxes_collected > 0 || (data.tps_percue ?? 0) > 0 ? (
          <div className="mt-5 rounded-lg border border-blue-500/30 bg-blue-500/5 p-3">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <h4 className="text-[11px] font-semibold uppercase tracking-wider text-blue-300">
                🏛️ Taxes à remettre au gouvernement
              </h4>
              <span className="text-[10px] text-white/50">
                Basé sur le FACTURÉ ({fmtMoney(data.facture_ht_base ?? data.invoiced_amount_ex_tax)} HT)
              </span>
            </div>
            <dl className="mt-2 space-y-1.5 text-sm">
              <div className="flex flex-wrap items-baseline justify-between gap-1">
                <dt className="text-white/60">
                  TPS (5 %){" "}
                  <span className="text-[10px] text-white/40">
                    perçue {fmtMoney(data.tps_percue ?? data.tps_collected)} − CTI{" "}
                    {fmtMoney(data.tps_paid_on_purchases ?? 0)}
                  </span>
                </dt>
                <dd className="font-mono text-white/90">
                  {fmtMoney(data.net_tps_to_remit ?? data.tps_collected)}
                </dd>
              </div>
              <div className="flex flex-wrap items-baseline justify-between gap-1">
                <dt className="text-white/60">
                  TVQ (9,975 %){" "}
                  <span className="text-[10px] text-white/40">
                    perçue {fmtMoney(data.tvq_percue ?? data.tvq_collected)} − RTI{" "}
                    {fmtMoney(data.tvq_paid_on_purchases ?? 0)}
                  </span>
                </dt>
                <dd className="font-mono text-white/90">
                  {fmtMoney(data.net_tvq_to_remit ?? data.tvq_collected)}
                </dd>
              </div>
              <div className="flex justify-between border-t border-blue-500/20 pt-1">
                <dt className="font-semibold text-blue-300">
                  Net à remettre
                </dt>
                <dd className="font-mono font-bold text-blue-300">
                  {fmtMoney(data.net_taxes_to_remit ?? data.taxes_collected)}
                </dd>
              </div>
            </dl>
            <p className="mt-2 text-[10px] text-white/40">
              ↳ Se recalcule à chaque facture / avenant / rabais. Ces
              montants ne sont PAS du revenu et n&apos;entrent pas dans le
              calcul du profit (taxes payées récupérées en CTI/RTI).
            </p>
          </div>
        ) : null}

        {/* Liste des factures réellement émises — statut visuel
            (brouillon / envoyée / en retard / payée / annulée), date
            d'envoi, montant payé, solde, lien vers la fiche. */}
        {data.invoices && data.invoices.length > 0 ? (
          <div className="mt-5">
            <h4 className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-white/50">
              Factures émises ({data.invoices.length})
            </h4>
            <ul className="space-y-1.5">
              {data.invoices.map((inv) => (
                <InvoiceRow key={inv.id} inv={inv} />
              ))}
            </ul>
          </div>
        ) : (
          <p className="mt-5 text-[11px] text-white/40">
            Aucune facture émise pour ce projet.
          </p>
        )}

        {data.invoices && data.invoices.length > 0 ? (
          <div className="mt-5 flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={openStatement}
              className="inline-flex items-center gap-2 rounded-lg border border-brand-800 bg-brand-950/40 px-3 py-2 text-xs font-medium text-white/80 transition hover:border-accent-500 hover:text-white"
            >
              <FileText className="h-4 w-4 text-accent-500" />
              Consulter l&apos;état de compte (PDF)
            </button>
            <button
              type="button"
              onClick={sendStatement}
              disabled={sendingStatement}
              className="inline-flex items-center gap-2 rounded-lg border border-brand-800 bg-brand-950/40 px-3 py-2 text-xs font-medium text-white/80 transition hover:border-accent-500 hover:text-white disabled:cursor-not-allowed disabled:opacity-60"
            >
              {sendingStatement ? (
                <Loader2 className="h-4 w-4 animate-spin text-accent-500" />
              ) : (
                <Mail className="h-4 w-4 text-accent-500" />
              )}
              {sendingStatement
                ? "Envoi…"
                : "Envoyer l'état de compte au client"}
            </button>
          </div>
        ) : null}
        {statementMsg ? (
          <p className="mt-2 text-[11px] text-emerald-400">{statementMsg}</p>
        ) : null}
      </section>
    </div>
  );
}

function FinanceKpi({
  label,
  value,
  sub,
  tone
}: {
  label: string;
  value: string;
  sub: string;
  tone: "accent" | "emerald" | "rose" | "white";
}) {
  const toneMap: Record<string, string> = {
    accent: "text-accent-500",
    emerald: "text-emerald-400",
    rose: "text-rose-400",
    white: "text-white"
  };
  return (
    <div className="rounded-xl border border-brand-800 bg-brand-900 p-5">
      <p className="text-xs font-medium uppercase tracking-wider text-white/50">
        {label}
      </p>
      <p className={`mt-2 text-2xl font-bold ${toneMap[tone]}`}>{value}</p>
      <p className="mt-1 text-xs text-white/50">{sub}</p>
    </div>
  );
}


// ---------- Planification (phases + tâches) ----------

type Phase = {
  id: number;
  project_id: number;
  name: string;
  position: number;
  start_date: string | null;
  // "HH:MM:SS" si la phase démarre à une heure précise (créneau dans
  // la journée). NULL = phase « journée complète ».
  start_time: string | null;
  duration_days: number | null;
  notes: string | null;
  assignee_employe_id: number | null;
  assignee_sous_traitant_id: number | null;
  assignee_employe_ids: number[];
  assignee_sous_traitant_ids: number[];
  sous_traitant_settings?: Array<{
    sous_traitant_id: number;
    hourly_billed: boolean;
    worker_count: number;
  }>;
  created_at: string;
  updated_at: string;
};

type PhaseTask = {
  id: number;
  project_id: number;
  phase_id: number | null;
  title: string;
  description: string | null;
  assignee_id: number | null;
  due_date: string | null;
  done: boolean;
  done_at: string | null;
  position: number;
};

function addDays(iso: string, days: number): string {
  const d = new Date(iso + "T12:00:00");
  d.setDate(d.getDate() + days);
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

type LinkedEvent = {
  id: number;
  title: string;
  start_at: string;
  all_day: boolean;
  phase_id: number | null;
  project_id: number | null;
  assignee_id: number | null;
  event_type: string;
};

function PlanificationTab({
  projectId,
  focusPhaseId = null,
  onFocusConsumed
}: {
  projectId: number;
  focusPhaseId?: number | null;
  onFocusConsumed?: () => void;
}) {
  const confirm = useConfirm();
  const [phases, setPhases] = useState<Phase[]>([]);
  // #25 — Phase à surligner brièvement après un clic depuis l'agenda.
  const [highlightPhaseId, setHighlightPhaseId] = useState<number | null>(
    null
  );
  const [tasks, setTasks] = useState<PhaseTask[]>([]);
  // Events ponctuels liés au projet ET rattachés à une phase précise.
  // Affichés inline sous leur phase (« Livraison conteneur 8h » sous
  // « Démolition »).
  const [phaseEvents, setPhaseEvents] = useState<LinkedEvent[]>([]);
  const [employes, setEmployes] = useState<
    Array<{ id: number; full_name: string }>
  >([]);
  const [sousTraitants, setSousTraitants] = useState<
    Array<{
      id: number;
      full_name: string;
      trade?: string | null;
      hourly_rate?: number | null;
    }>
  >([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [busyPhase, setBusyPhase] = useState<number | "new" | null>(null);
  const [busyTask, setBusyTask] = useState<number | "new" | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [phRes, tRes, eRes, sRes, agRes] = await Promise.all([
        authedFetch(`/api/v1/projects/${projectId}/phases`),
        authedFetch(`/api/v1/projects/${projectId}/tasks`),
        authedFetch(`/api/v1/employes?limit=200&volet=construction`),
        authedFetch(`/api/v1/sous-traitants?limit=200`),
        authedFetch(`/api/v1/agenda?limit=500`)
      ]);
      if (!phRes.ok) throw new Error();
      setPhases((await phRes.json()) as Phase[]);
      if (tRes.ok) setTasks((await tRes.json()) as PhaseTask[]);
      if (agRes.ok) {
        const all = (await agRes.json()) as LinkedEvent[];
        // Garde seulement les events liés au projet ET rattachés à
        // une phase. Les events sans phase apparaissent dans l'onglet
        // Agenda chantier mais pas ici.
        setPhaseEvents(
          all.filter(
            (e) => e.project_id === projectId && e.phase_id != null
          )
        );
      }
      if (eRes.ok)
        setEmployes(
          (await eRes.json()) as Array<{ id: number; full_name: string }>
        );
      if (sRes.ok)
        setSousTraitants(
          (await sRes.json()) as Array<{
            id: number;
            full_name: string;
            trade?: string | null;
            hourly_rate?: number | null;
          }>
        );
    } catch {
      setErr("Chargement échoué.");
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    void load();
  }, [load]);

  // #25 — Quand on arrive ici via un clic sur une phase précise (Gantt /
  // liste agenda), on défile jusqu'à sa carte et on la surligne ~2,5 s
  // une fois les phases chargées.
  useEffect(() => {
    if (focusPhaseId == null) return;
    if (!phases.some((p) => p.id === focusPhaseId)) return;
    const el =
      typeof document !== "undefined"
        ? document.getElementById(`phase-card-${focusPhaseId}`)
        : null;
    if (el) {
      el.scrollIntoView({ behavior: "smooth", block: "center" });
      setHighlightPhaseId(focusPhaseId);
      const t = setTimeout(() => setHighlightPhaseId(null), 2500);
      onFocusConsumed?.();
      return () => clearTimeout(t);
    }
    onFocusConsumed?.();
  }, [focusPhaseId, phases, onFocusConsumed]);

  // Auto-seed des 3 phases de base (Démolition / Plomberie /
  // Électricité) la première fois qu'on ouvre le tab Planification
  // pour ce projet et qu'il n'a aucune phase. On stocke un flag local
  // pour ne pas re-seeder si l'utilisateur les supprime toutes
  // volontairement.
  useEffect(() => {
    if (loading) return;
    if (phases.length > 0) return;
    const flagKey = `phases-seeded-${projectId}`;
    if (typeof window === "undefined") return;
    try {
      if (window.localStorage.getItem(flagKey) === "1") return;
      window.localStorage.setItem(flagKey, "1");
    } catch {
      return;
    }
    void seedDefaultPhases();
    // seedDefaultPhases est défini plus bas — la fonction lit l'état
    // courant donc on ne dépend pas de la référence.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loading, projectId]);

  // #22/#25 — Une nouvelle phase démarre à 1 jour (et non 5) : sinon une
  // planification entrée « pour une journée » s'affichait comme une longue
  // barre couvrant 5 jours. L'utilisateur ajuste la durée dans l'éditeur.
  async function addPhase(name?: string, durationDays = 1) {
    setBusyPhase("new");
    setErr(null);
    try {
      const res = await authedFetch(
        `/api/v1/projects/${projectId}/phases`,
        {
          method: "POST",
          body: JSON.stringify({
            name: name || `Phase ${phases.length + 1}`,
            position: phases.length,
            duration_days: durationDays
          })
        }
      );
      if (!res.ok) {
        const txt = await res.text();
        throw new Error(`${res.status} — ${txt.slice(0, 200)}`);
      }
      const created = (await res.json()) as Phase;
      setPhases((xs) => [...xs, created]);
      return created;
    } catch (e) {
      setErr(`Ajout phase échoué : ${(e as Error).message}`);
      return null;
    } finally {
      setBusyPhase(null);
    }
  }

  async function seedDefaultPhases() {
    // Insère les 3 phases standard d'un chantier construction/rénovation.
    // On les crée séquentiellement pour garder l'ordre position=0,1,2
    // stable côté backend (chaque POST calcule la position suivante).
    const defaults = [
      { name: "Démolition", days: 3 },
      { name: "Plomberie", days: 5 },
      { name: "Électricité", days: 5 }
    ];
    setBusyPhase("new");
    setErr(null);
    try {
      for (const d of defaults) {
        const res = await authedFetch(
          `/api/v1/projects/${projectId}/phases`,
          {
            method: "POST",
            body: JSON.stringify({
              name: d.name,
              position: 0, // let backend append
              duration_days: d.days
            })
          }
        );
        if (!res.ok) {
          const txt = await res.text();
          throw new Error(`${res.status} — ${txt.slice(0, 200)}`);
        }
        const created = (await res.json()) as Phase;
        setPhases((xs) => [...xs, created]);
      }
    } catch (e) {
      setErr(`Insertion phases de base échouée : ${(e as Error).message}`);
    } finally {
      setBusyPhase(null);
    }
  }

  async function patchPhase(id: number, patch: Partial<Phase>) {
    // Avertit si on assigne un employé déjà occupé sur une autre
    // phase qui chevauche la période de celle-ci. Évite le double-
    // booking silencieux.
    const newAssignees = patch.assignee_employe_ids;
    const currentPhase = phases.find((p) => p.id === id);
    if (
      Array.isArray(newAssignees) &&
      currentPhase &&
      currentPhase.start_date &&
      currentPhase.duration_days
    ) {
      const previous = new Set(currentPhase.assignee_employe_ids || []);
      const added = newAssignees.filter((eid) => !previous.has(eid));
      if (added.length > 0) {
        const start = new Date(currentPhase.start_date);
        const end = new Date(start);
        end.setDate(end.getDate() + (currentPhase.duration_days || 1));
        const empNameById = new Map(
          employes.map((e) => [e.id, e.full_name])
        );
        // Récupère TOUTES les phases visibles (tous projets confondus)
        // pour détecter les conflits cross-projets — la state locale
        // ne contient que les phases de ce projet.
        let allPhases: Phase[] = phases;
        try {
          const r = await authedFetch("/api/v1/phases");
          if (r.ok) allPhases = (await r.json()) as Phase[];
        } catch {
          /* fallback sur les phases locales */
        }
        const conflicts: string[] = [];
        for (const eid of added) {
          // Cherche une phase d'un AUTRE projet qui chevauche +
          // assigne le même employé
          const conflictPhases = allPhases.filter((p) => {
            if (p.id === id) return false;
            if (!p.start_date || !p.duration_days) return false;
            if (!(p.assignee_employe_ids || []).includes(eid)) return false;
            const ps = new Date(p.start_date);
            const pe = new Date(ps);
            pe.setDate(pe.getDate() + (p.duration_days || 1));
            // Overlap si ps < end && pe > start
            return ps.getTime() < end.getTime() && pe.getTime() > start.getTime();
          });
          for (const p of conflictPhases) {
            const empName = empNameById.get(eid) || `Employé #${eid}`;
            conflicts.push(
              `${empName} : déjà sur phase « ${p.name} » (projet #${p.project_id}) du ${p.start_date} pour ${p.duration_days} jour(s)`
            );
          }
        }
        if (conflicts.length > 0) {
          const ok = await confirm({
            title: "Conflit d'assignation détecté",
            description:
              "Un ou plusieurs employés sont déjà assignés à des phases qui chevauchent cette période :\n\n" +
              conflicts.map((c) => `• ${c}`).join("\n") +
              "\n\nAssigner quand même ?",
            confirmLabel: "Assigner quand même",
            destructive: true
          });
          if (!ok) {
            return;
          }
        }
      }
    }

    setBusyPhase(id);
    try {
      const res = await authedFetch(
        `/api/v1/projects/${projectId}/phases/${id}`,
        { method: "PATCH", body: JSON.stringify(patch) }
      );
      if (!res.ok) throw new Error();
      const updated = (await res.json()) as Phase;
      setPhases((xs) => xs.map((x) => (x.id === id ? updated : x)));
    } catch {
      setErr("Mise à jour échouée.");
    } finally {
      setBusyPhase(null);
    }
  }

  async function patchPhaseSousTraitant(
    phaseId: number,
    stId: number,
    patch: { hourly_billed?: boolean; worker_count?: number }
  ) {
    setBusyPhase(phaseId);
    try {
      const res = await authedFetch(
        `/api/v1/projects/${projectId}/phases/${phaseId}/sous-traitants/${stId}`,
        { method: "PATCH", body: JSON.stringify(patch) }
      );
      if (!res.ok) throw new Error();
      const updated = (await res.json()) as Phase;
      setPhases((xs) => xs.map((x) => (x.id === phaseId ? updated : x)));
    } catch {
      setErr("Mise à jour échouée.");
    } finally {
      setBusyPhase(null);
    }
  }

  async function removePhase(id: number) {
    if (!(await confirm("Supprimer cette phase ? Les tâches qui y sont seront détachées."))) return;
    setBusyPhase(id);
    try {
      const res = await authedFetch(
        `/api/v1/projects/${projectId}/phases/${id}`,
        { method: "DELETE" }
      );
      if (!res.ok && res.status !== 204) throw new Error();
      setPhases((xs) => xs.filter((x) => x.id !== id));
      setTasks((xs) =>
        xs.map((t) => (t.phase_id === id ? { ...t, phase_id: null } : t))
      );
    } catch {
      setErr("Suppression échouée.");
    } finally {
      setBusyPhase(null);
    }
  }

  async function movePhase(id: number, delta: number) {
    const idx = phases.findIndex((p) => p.id === id);
    if (idx < 0) return;
    const next = [...phases];
    const [moved] = next.splice(idx, 1);
    next.splice(Math.max(0, Math.min(next.length, idx + delta)), 0, moved);
    setPhases(next);
    try {
      await authedFetch(
        `/api/v1/projects/${projectId}/phases/reorder`,
        {
          method: "PUT",
          body: JSON.stringify({ phase_ids: next.map((p) => p.id) })
        }
      );
    } catch {
      setErr("Réordonnancement échoué.");
    }
  }

  // #14 — Remet les phases en ordre chronologique (date de début
  // croissante). Les phases sans date passent à la fin. Persiste le
  // nouvel ordre via l'endpoint de réordonnancement.
  async function sortPhasesByDate() {
    const next = [...phases].sort((a, b) => {
      const da = a.start_date ? new Date(a.start_date).getTime() : Infinity;
      const dbb = b.start_date ? new Date(b.start_date).getTime() : Infinity;
      if (da !== dbb) return da - dbb;
      return a.id - b.id;
    });
    // Aucun changement → ne rien faire.
    if (next.every((p, i) => p.id === phases[i].id)) return;
    setPhases(next);
    try {
      await authedFetch(`/api/v1/projects/${projectId}/phases/reorder`, {
        method: "PUT",
        body: JSON.stringify({ phase_ids: next.map((p) => p.id) })
      });
    } catch {
      setErr("Réordonnancement échoué.");
    }
  }

  async function addTask(phaseId: number | null) {
    setBusyTask("new");
    setErr(null);
    try {
      const res = await authedFetch(
        `/api/v1/projects/${projectId}/tasks`,
        {
          method: "POST",
          body: JSON.stringify({
            title: "Nouvelle tâche",
            phase_id: phaseId,
            position: tasks.filter((t) => t.phase_id === phaseId).length
          })
        }
      );
      if (!res.ok) {
        const txt = await res.text();
        throw new Error(`${res.status} — ${txt.slice(0, 200)}`);
      }
      const created = (await res.json()) as PhaseTask;
      setTasks((xs) => [...xs, created]);
    } catch (e) {
      setErr(`Ajout tâche échoué : ${(e as Error).message}`);
    } finally {
      setBusyTask(null);
    }
  }

  async function patchTask(id: number, patch: Partial<PhaseTask>) {
    setBusyTask(id);
    try {
      const res = await authedFetch(
        `/api/v1/projects/${projectId}/tasks/${id}`,
        { method: "PATCH", body: JSON.stringify(patch) }
      );
      if (!res.ok) throw new Error();
      const updated = (await res.json()) as PhaseTask;
      setTasks((xs) => xs.map((x) => (x.id === id ? updated : x)));
    } catch {
      setErr("Mise à jour échouée.");
    } finally {
      setBusyTask(null);
    }
  }

  async function removeTask(id: number) {
    if (!(await confirm("Supprimer cette tâche ?"))) return;
    setBusyTask(id);
    try {
      const res = await authedFetch(
        `/api/v1/projects/${projectId}/tasks/${id}`,
        { method: "DELETE" }
      );
      if (!res.ok && res.status !== 204) throw new Error();
      setTasks((xs) => xs.filter((x) => x.id !== id));
    } catch {
      setErr("Suppression échouée.");
    } finally {
      setBusyTask(null);
    }
  }

  if (loading) {
    return (
      <div className="flex min-h-[30vh] items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-accent-500" />
      </div>
    );
  }

  const unplaced = tasks.filter((t) => t.phase_id === null);

  return (
    <div className="space-y-4">
      {err ? (
        <p className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
          {err}
        </p>
      ) : null}

      <ProjectTeamSection projectId={projectId} phases={phases} />

      <div className="flex items-center justify-between">
        <p className="text-xs text-white/60">
          Découpe le projet en phases (ex. Démolition, Fondation,
          Plomberie, Finition). Chaque phase a une date de début et une
          durée en jours — la fin est calculée automatiquement.
        </p>
        <div className="flex items-center gap-2">
          {phases.length > 1 ? (
            <button
              type="button"
              onClick={() => sortPhasesByDate()}
              className="inline-flex items-center rounded-lg border border-brand-700 px-2.5 py-1.5 text-xs text-white/70 hover:border-accent-500 hover:text-accent-500"
              title="Réordonner les phases par date de début"
            >
              <ArrowDownUp className="mr-1.5 h-3.5 w-3.5" />
              Trier par date
            </button>
          ) : null}
          <button
            type="button"
            onClick={() => addPhase()}
            disabled={busyPhase === "new"}
            className="btn-accent text-xs disabled:opacity-60"
          >
            {busyPhase === "new" ? (
              <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
            ) : (
              <Plus className="mr-1.5 h-3.5 w-3.5" />
            )}
            Nouvelle phase
          </button>
        </div>
      </div>

      {phases.length === 0 ? (
        <p className="rounded-2xl border border-dashed border-brand-800 bg-brand-900/40 px-6 py-10 text-center text-sm text-white/60">
          Aucune phase. Clique « Nouvelle phase » pour en créer une.
          (Démolition, Plomberie et Électricité sont créées
          automatiquement à la première ouverture du projet.)
        </p>
      ) : (
        <ol className="space-y-3">
          {phases.map((ph, idx) => (
            <PhaseCard
              key={ph.id}
              phase={ph}
              index={idx}
              highlighted={highlightPhaseId === ph.id}
              count={phases.length}
              projectId={projectId}
              tasks={tasks.filter((t) => t.phase_id === ph.id)}
              linkedEvents={phaseEvents.filter(
                (e) => e.phase_id === ph.id
              )}
              employes={employes}
              sousTraitants={sousTraitants}
              busyPhase={busyPhase === ph.id}
              busyTask={busyTask}
              onPatch={(patch) => patchPhase(ph.id, patch)}
              onPatchSousTraitant={(stId, patch) =>
                patchPhaseSousTraitant(ph.id, stId, patch)
              }
              onRemove={() => removePhase(ph.id)}
              onMoveUp={() => movePhase(ph.id, -1)}
              onMoveDown={() => movePhase(ph.id, 1)}
              onAddTask={() => addTask(ph.id)}
              onPatchTask={patchTask}
              onRemoveTask={removeTask}
            />
          ))}
        </ol>
      )}

      {phases.length > 0 ? (
        <div className="flex justify-center">
          <button
            type="button"
            onClick={() => addPhase()}
            disabled={busyPhase === "new"}
            className="inline-flex items-center gap-2 rounded-xl border border-dashed border-brand-700 bg-brand-900/40 px-4 py-3 text-sm font-medium text-white/70 transition hover:border-accent-500 hover:bg-accent-500/10 hover:text-white disabled:opacity-60"
          >
            {busyPhase === "new" ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Plus className="h-4 w-4" />
            )}
            Ajouter une phase
          </button>
        </div>
      ) : null}

      {/* Floating bucket for tasks not tied to a phase. */}
      <section className="rounded-xl border border-brand-800 bg-brand-900/40 p-4">
        <div className="flex items-center justify-between">
          <h3 className="text-xs font-semibold uppercase tracking-wider text-white/60">
            Tâches sans phase ({unplaced.length})
          </h3>
          <button
            type="button"
            onClick={() => addTask(null)}
            disabled={busyTask === "new"}
            className="btn-secondary text-xs disabled:opacity-60"
          >
            <Plus className="mr-1.5 h-3.5 w-3.5" /> Ajouter
          </button>
        </div>
        {unplaced.length > 0 ? (
          <ul className="mt-3 space-y-2">
            {unplaced.map((t) => (
              <PhaseTaskRow
                key={t.id}
                task={t}
                busy={busyTask === t.id}
                phases={phases}
                onPatch={(patch) => patchTask(t.id, patch)}
                onRemove={() => removeTask(t.id)}
              />
            ))}
          </ul>
        ) : null}
      </section>
    </div>
  );
}

function PhaseCard({
  phase,
  index,
  count,
  projectId,
  tasks,
  linkedEvents,
  employes,
  sousTraitants,
  busyPhase,
  busyTask,
  onPatch,
  onPatchSousTraitant,
  onRemove,
  onMoveUp,
  onMoveDown,
  onAddTask,
  onPatchTask,
  onRemoveTask,
  highlighted = false
}: {
  phase: Phase;
  index: number;
  highlighted?: boolean;
  projectId: number;
  employes: Array<{ id: number; full_name: string }>;
  sousTraitants: Array<{
    id: number;
    full_name: string;
    trade?: string | null;
    hourly_rate?: number | null;
  }>;
  count: number;
  tasks: PhaseTask[];
  linkedEvents: LinkedEvent[];
  busyPhase: boolean;
  busyTask: number | "new" | null;
  onPatch: (patch: Partial<Phase>) => void;
  onPatchSousTraitant: (
    stId: number,
    patch: { hourly_billed?: boolean; worker_count?: number }
  ) => void;
  onRemove: () => void;
  onMoveUp: () => void;
  onMoveDown: () => void;
  onAddTask: () => void;
  onPatchTask: (id: number, patch: Partial<PhaseTask>) => void;
  onRemoveTask: (id: number) => void;
}) {
  const [name, setName] = useState(phase.name);
  const [startDate, setStartDate] = useState(phase.start_date || "");
  // Mode « journée complète » (durée en jours entiers, pas d'heure
  // précise) vs créneau horaire (start + end dans la même journée).
  // L'état initial est dérivé du modèle : si start_time est défini,
  // on est en mode créneau ; sinon journée complète.
  const initFullDay = phase.start_time == null;
  const [fullDay, setFullDay] = useState(initFullDay);
  // Mode journée complète : nombre de jours.
  const [daysPart, setDaysPart] = useState(
    initFullDay && phase.duration_days != null
      ? String(Math.max(1, Math.ceil(phase.duration_days)))
      : "1"
  );
  // Mode créneau : heure début + heure fin (HH:MM).
  const trimSec = (t: string | null) => (t ? t.slice(0, 5) : "");
  const computeEndFromDuration = (
    startHHMM: string,
    durationDays: number | null
  ) => {
    if (!startHHMM || durationDays == null) return "";
    const [h, m] = startHHMM.split(":").map(Number);
    const totalMin = h * 60 + m + durationDays * 8 * 60;
    const eh = Math.floor(totalMin / 60) % 24;
    const em = Math.floor(totalMin % 60);
    return `${String(eh).padStart(2, "0")}:${String(em).padStart(2, "0")}`;
  };
  const [startTime, setStartTime] = useState(
    !initFullDay ? trimSec(phase.start_time) : "08:00"
  );
  const [endTime, setEndTime] = useState(
    !initFullDay
      ? computeEndFromDuration(trimSec(phase.start_time), phase.duration_days)
      : "12:00"
  );

  useEffect(() => {
    setName(phase.name);
    setStartDate(phase.start_date || "");
    const fd = phase.start_time == null;
    setFullDay(fd);
    setDaysPart(
      fd && phase.duration_days != null
        ? String(Math.max(1, Math.ceil(phase.duration_days)))
        : "1"
    );
    setStartTime(!fd ? trimSec(phase.start_time) : "08:00");
    setEndTime(
      !fd
        ? computeEndFromDuration(
            trimSec(phase.start_time),
            phase.duration_days
          )
        : "12:00"
    );
  }, [
    phase.id,
    phase.name,
    phase.start_date,
    phase.start_time,
    phase.duration_days
  ]);

  // Dérive la durée actuelle (en jours décimaux) selon le mode.
  // « Journée complète » = 1 jour fixe (pas de N jours configurable).
  // Pour planifier sur plusieurs jours, l'utilisateur crée plusieurs
  // phases — chaque phase = une journée (ou un créneau) précis.
  const currentDuration: number | null = (() => {
    if (fullDay) return 1;
    if (!startTime || !endTime) return null;
    const [sh, sm] = startTime.split(":").map(Number);
    const [eh, em] = endTime.split(":").map(Number);
    const diffMin = eh * 60 + em - (sh * 60 + sm);
    if (diffMin <= 0) return null;
    return diffMin / 60 / 8; // 8 h = 1 jour
  })();

  const endDate =
    startDate && fullDay
      ? startDate // 1 journée = même jour
      : startDate && !fullDay
        ? startDate
        : null;

  // Persiste les changements (mode + jours/heures) en un seul patch
  // pour éviter les races (ex. on bascule full→partial : on doit
  // envoyer start_time + duration_days nouveau d'un coup).
  const persist = () => {
    if (fullDay) {
      const patch: Partial<Phase> = {
        start_time: null,
        duration_days: currentDuration
      };
      if (
        phase.start_time !== null ||
        currentDuration !== phase.duration_days
      ) {
        onPatch(patch);
      }
    } else {
      const patch: Partial<Phase> = {
        start_time: startTime ? `${startTime}:00` : null,
        duration_days: currentDuration
      };
      if (
        trimSec(phase.start_time) !== startTime ||
        currentDuration !== phase.duration_days
      ) {
        onPatch(patch);
      }
    }
  };

  return (
    <li
      id={`phase-card-${phase.id}`}
      className={`rounded-2xl border bg-brand-900 p-4 transition ${
        highlighted
          ? "border-accent-500 ring-2 ring-accent-500/60"
          : "border-brand-800"
      }`}
    >
      <div className="flex items-start gap-3">
        <span className="mt-1 flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-full bg-accent-500 text-xs font-bold text-brand-950">
          {index + 1}
        </span>
        <div className="flex-1 min-w-0">
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            onBlur={() =>
              name.trim() && name !== phase.name && onPatch({ name: name.trim() })
            }
            placeholder="Titre de la phase"
            className="w-full rounded-md border border-brand-800 bg-brand-950 px-2 py-1.5 text-lg font-bold text-white focus:border-accent-500 focus:outline-none"
          />
          <div className="mt-2 grid gap-3 sm:grid-cols-3">
            <label className="text-xs text-white/60">
              Début
              <input
                type="date"
                value={startDate}
                onChange={(e) => setStartDate(e.target.value)}
                onBlur={() =>
                  startDate !== (phase.start_date || "") &&
                  onPatch({ start_date: startDate || null })
                }
                className="mt-1 w-full rounded-md border border-brand-800 bg-brand-950 px-2 py-1 text-sm text-white"
              />
            </label>
            <div className="text-xs text-white/60 sm:col-span-2">
              <label className="flex items-center gap-2 text-white/70">
                <input
                  type="checkbox"
                  checked={fullDay}
                  onChange={(e) => {
                    const next = e.target.checked;
                    setFullDay(next);
                    // Persiste tout de suite le mode pour que la
                    // ligne s'aligne sur le serveur. Journée complète
                    // = 1 j sec, créneau = duration calculée.
                    if (next) {
                      onPatch({ start_time: null, duration_days: 1 });
                    } else {
                      const [sh, sm] = startTime.split(":").map(Number);
                      const [eh, em] = endTime.split(":").map(Number);
                      const diffMin = eh * 60 + em - (sh * 60 + sm);
                      const dur = diffMin > 0 ? diffMin / 60 / 8 : 0.5;
                      onPatch({
                        start_time: `${startTime}:00`,
                        duration_days: dur
                      });
                    }
                  }}
                  className="h-4 w-4 rounded border-brand-800 bg-brand-950 accent-accent-500"
                />
                Journée complète
              </label>
              {fullDay ? null : (
                <div className="mt-2 grid grid-cols-2 gap-2">
                  <label className="text-[11px] uppercase tracking-wider text-white/40">
                    Heure début
                    <input
                      type="time"
                      value={startTime}
                      onChange={(e) => setStartTime(e.target.value)}
                      onBlur={persist}
                      className="mt-1 w-full rounded-md border border-brand-800 bg-brand-950 px-2 py-1 text-sm text-white"
                    />
                  </label>
                  <label className="text-[11px] uppercase tracking-wider text-white/40">
                    Heure fin
                    <input
                      type="time"
                      value={endTime}
                      onChange={(e) => setEndTime(e.target.value)}
                      onBlur={persist}
                      className="mt-1 w-full rounded-md border border-brand-800 bg-brand-950 px-2 py-1 text-sm text-white"
                    />
                  </label>
                </div>
              )}
            </div>
            <div className="text-xs text-white/60 sm:col-span-3">
              Fin (calculée)
              <p className="mt-1 rounded-md border border-brand-800 bg-brand-950 px-2 py-1.5 text-sm font-semibold text-accent-500">
                {fullDay
                  ? endDate || "—"
                  : startDate
                    ? `${startDate} · ${startTime} → ${endTime}`
                    : "—"}
              </p>
            </div>
          </div>

          <div className="mt-3">
            <p className="text-xs text-white/60">
              Assignés à
              {phase.assignee_employe_ids.length +
                phase.assignee_sous_traitant_ids.length >
              0 ? (
                <span className="ml-1 text-white/40">
                  ({phase.assignee_employe_ids.length +
                    phase.assignee_sous_traitant_ids.length}{" "}
                  personne
                  {phase.assignee_employe_ids.length +
                    phase.assignee_sous_traitant_ids.length >
                  1
                    ? "s"
                    : ""}
                  )
                </span>
              ) : null}
            </p>
            <div className="mt-2 grid gap-2 sm:grid-cols-2">
              <div>
                <p className="mb-1 text-[10px] uppercase tracking-wider text-white/40">
                  Employés
                </p>
                <MultiSelectDropdown
                  options={employes.map((e) => ({
                    id: e.id,
                    label: e.full_name,
                  }))}
                  selectedIds={phase.assignee_employe_ids}
                  onChange={(ids) =>
                    onPatch({ assignee_employe_ids: ids })
                  }
                  placeholder="— Aucun employé —"
                  emptyLabel="Aucun employé disponible"
                />
              </div>
              <div>
                <p className="mb-1 text-[10px] uppercase tracking-wider text-white/40">
                  Sous-traitants
                </p>
                <MultiSelectDropdown
                  options={sousTraitants.map((s) => ({
                    id: s.id,
                    label: s.full_name,
                    sublabel: s.trade || undefined,
                  }))}
                  selectedIds={phase.assignee_sous_traitant_ids}
                  onChange={(ids) =>
                    onPatch({ assignee_sous_traitant_ids: ids })
                  }
                  placeholder="— Aucun sous-traitant —"
                  emptyLabel="Aucun sous-traitant disponible"
                />
              </div>
            </div>
            {phase.assignee_sous_traitant_ids.length > 0 ? (
              <div className="mt-2 space-y-1.5 rounded-lg border border-brand-800 bg-brand-950/40 p-2">
                <p className="text-[10px] uppercase tracking-wider text-white/40">
                  Sous-traitants payés à l&apos;heure (comptés dans le coût
                  projeté)
                </p>
                {phase.assignee_sous_traitant_ids.map((stId) => {
                  const st = sousTraitants.find((s) => s.id === stId);
                  const setting = (phase.sous_traitant_settings || []).find(
                    (x) => x.sous_traitant_id === stId
                  );
                  const hourly = setting?.hourly_billed ?? false;
                  const workers = setting?.worker_count ?? 1;
                  return (
                    <div
                      key={stId}
                      className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs"
                    >
                      <span className="min-w-[120px] flex-1 truncate text-white/80">
                        {st?.full_name || `#${stId}`}
                        {st?.hourly_rate != null ? (
                          <span className="ml-1 text-white/40">
                            ({fmtMoney(st.hourly_rate)}/h)
                          </span>
                        ) : null}
                      </span>
                      <label className="flex cursor-pointer items-center gap-1.5 text-white/70">
                        <input
                          type="checkbox"
                          checked={hourly}
                          disabled={busyPhase}
                          onChange={(e) =>
                            onPatchSousTraitant(stId, {
                              hourly_billed: e.target.checked,
                            })
                          }
                          className="h-3.5 w-3.5"
                        />
                        Payé à l&apos;heure
                      </label>
                      {hourly ? (
                        <label className="flex items-center gap-1.5 text-white/70">
                          Nb travailleurs
                          <input
                            key={`wc-${workers}`}
                            type="number"
                            min={1}
                            max={999}
                            defaultValue={workers}
                            disabled={busyPhase}
                            onBlur={(e) => {
                              const v = Math.max(
                                1,
                                Math.round(Number(e.target.value) || 1)
                              );
                              if (v !== workers) {
                                onPatchSousTraitant(stId, {
                                  worker_count: v,
                                });
                              }
                            }}
                            className="input w-16 px-2 py-1 text-xs"
                          />
                        </label>
                      ) : null}
                    </div>
                  );
                })}
              </div>
            ) : null}
          </div>
        </div>
        <div className="flex flex-shrink-0 flex-col items-end gap-1">
          <button
            type="button"
            onClick={onMoveUp}
            disabled={index === 0 || busyPhase}
            className="rounded p-1 text-white/40 hover:text-white disabled:opacity-20"
            title="Monter"
          >
            ▲
          </button>
          <button
            type="button"
            onClick={onMoveDown}
            disabled={index === count - 1 || busyPhase}
            className="rounded p-1 text-white/40 hover:text-white disabled:opacity-20"
            title="Descendre"
          >
            ▼
          </button>
          <button
            type="button"
            onClick={onRemove}
            disabled={busyPhase}
            className="rounded p-1 text-rose-300 hover:text-rose-200 disabled:opacity-30"
            title="Supprimer la phase"
          >
            <Trash2 className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>

      <div className="mt-4 border-t border-brand-800 pt-3">
        <div className="flex items-center justify-between">
          <p className="text-xs font-semibold uppercase tracking-wider text-white/60">
            Tâches ({tasks.length})
          </p>
          <div className="flex items-center gap-2">
            <Link
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
              href={
                `/app/po/new?project_id=${projectId}&phase_hint=${encodeURIComponent(
                  phase.name
                )}` as any
              }
              className="inline-flex items-center rounded-md border border-brand-800 bg-brand-900 px-2.5 py-1.5 text-xs text-white/80 hover:border-accent-500/40 hover:text-white"
              title={`Créer un PO pour la phase « ${phase.name} »`}
            >
              <Plus className="mr-1.5 h-3.5 w-3.5" />
              PO
            </Link>
            <button
              type="button"
              onClick={onAddTask}
              disabled={busyTask === "new"}
              className="btn-secondary text-xs disabled:opacity-60"
            >
              {busyTask === "new" ? (
                <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
              ) : (
                <Plus className="mr-1.5 h-3.5 w-3.5" />
              )}
              Tâche
            </button>
          </div>
        </div>
        {tasks.length > 0 ? (
          <ul className="mt-3 space-y-2">
            {tasks.map((t) => (
              <PhaseTaskRow
                key={t.id}
                task={t}
                busy={busyTask === t.id}
                phases={[]}
                onPatch={(patch) => onPatchTask(t.id, patch)}
                onRemove={() => onRemoveTask(t.id)}
              />
            ))}
          </ul>
        ) : (
          <p className="mt-3 text-xs text-white/40">
            Aucune tâche dans cette phase.
          </p>
        )}

        {/* Événements ponctuels rattachés à cette phase (Livraison
            8h, Inspection 14h…). Lien vers l'agenda chantier pour
            modifier. */}
        {linkedEvents.length > 0 ? (
          <div className="mt-4 border-t border-brand-800 pt-3">
            <p className="text-[10px] font-semibold uppercase tracking-wider text-accent-300/70">
              📅 Événements rattachés ({linkedEvents.length})
            </p>
            <ul className="mt-1.5 space-y-1">
              {linkedEvents
                .slice()
                .sort(
                  (a, b) =>
                    new Date(a.start_at).getTime() -
                    new Date(b.start_at).getTime()
                )
                .map((e) => {
                  const d = new Date(e.start_at);
                  const dayFmt = d.toLocaleDateString("fr-CA", {
                    weekday: "short",
                    day: "numeric",
                    month: "short"
                  });
                  const timeFmt = e.all_day
                    ? "Journée"
                    : d.toLocaleTimeString("fr-CA", {
                        hour: "2-digit",
                        minute: "2-digit"
                      });
                  return (
                    <li
                      key={e.id}
                      className="flex items-center gap-2 rounded-md border border-brand-800 bg-brand-950/50 px-2 py-1.5 text-xs"
                    >
                      <span className="text-white/40 tabular-nums">
                        {dayFmt} · {timeFmt}
                      </span>
                      <span className="flex-1 truncate text-white/90">
                        {e.title}
                      </span>
                    </li>
                  );
                })}
            </ul>
          </div>
        ) : null}
      </div>
    </li>
  );
}

function PhaseTaskRow({
  task,
  busy,
  phases,
  onPatch,
  onRemove
}: {
  task: PhaseTask;
  busy: boolean;
  phases: Phase[];
  onPatch: (patch: Partial<PhaseTask>) => void;
  onRemove: () => void;
}) {
  const [title, setTitle] = useState(task.title);
  useEffect(() => setTitle(task.title), [task.id, task.title]);
  return (
    <li className="flex items-center gap-2 rounded-lg border border-brand-800 bg-brand-950 px-3 py-2 text-sm">
      <input
        type="checkbox"
        checked={task.done}
        onChange={(e) => onPatch({ done: e.target.checked })}
        disabled={busy}
        className="h-4 w-4 accent-emerald-500"
      />
      <input
        type="text"
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        onBlur={() =>
          title.trim() && title !== task.title && onPatch({ title: title.trim() })
        }
        className={`flex-1 bg-transparent focus:outline-none ${
          task.done ? "text-white/40 line-through" : "text-white"
        }`}
      />
      {phases.length > 0 ? (
        <select
          value={task.phase_id ?? ""}
          onChange={(e) =>
            onPatch({
              phase_id: e.target.value ? Number(e.target.value) : null
            })
          }
          className="rounded border border-brand-800 bg-brand-900 px-1.5 py-0.5 text-xs text-white/70"
          title="Déplacer dans une phase"
        >
          <option value="">— Sans phase —</option>
          {phases.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}
            </option>
          ))}
        </select>
      ) : null}
      <button
        type="button"
        onClick={onRemove}
        disabled={busy}
        className="rounded p-1 text-white/40 hover:text-rose-300 disabled:opacity-30"
        aria-label="Supprimer"
      >
        {busy ? (
          <Loader2 className="h-3.5 w-3.5 animate-spin" />
        ) : (
          <Trash2 className="h-3.5 w-3.5" />
        )}
      </button>
    </li>
  );
}

// ---------- Agenda chantier ----------

type ChantierEvent = {
  id: number;
  title: string;
  description: string | null;
  location: string | null;
  start_at: string;
  end_at: string | null;
  all_day: boolean;
  project_id: number | null;
  assignee_id: number | null;
  event_type: string;
};

function ChantierAgendaTab({
  projectId,
  projectName,
  projectEndDate,
  onOpenPhase
}: {
  projectId: number;
  projectName: string;
  projectEndDate?: string | null;
  onOpenPhase: (phaseId?: number) => void;
}) {
  const confirm = useConfirm();
  const [events, setEvents] = useState<ChantierEvent[]>([]);
  const [employes, setEmployes] = useState<Array<{ id: number; full_name: string }>>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [view, setView] = useState<"list" | "gantt">("list");

  // Inline form state for adding an event (replaces broken window.prompt
  // flow which is blocked in PWA standalone mode on iOS and Android).
  const [formOpen, setFormOpen] = useState(false);
  // État du modal d'édition d'un event existant (clic sur la carte
  // dans la liste « À venir » / « Passés »).
  const [editingEvent, setEditingEvent] = useState<ChantierEvent | null>(
    null
  );
  const [fTitle, setFTitle] = useState("");
  const [fDate, setFDate] = useState(() => {
    const d = new Date();
    const p = (n: number) => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
  });
  const [fTime, setFTime] = useState("08:00");
  const [fAllDay, setFAllDay] = useState(false);
  const [fDurationDays, setFDurationDays] = useState("1");
  const [fPhaseId, setFPhaseId] = useState<string>(""); // event linké à phase
  const [fAssigneeIds, setFAssigneeIds] = useState<number[]>([]);
  const [fDescription, setFDescription] = useState("");
  // Phases du projet pour le sélecteur (chargées avec les events).
  const [projectPhases, setProjectPhases] = useState<
    Array<{ id: number; name: string }>
  >([]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [evRes, empRes, phRes] = await Promise.all([
        authedFetch(`/api/v1/agenda?limit=500`),
        authedFetch(`/api/v1/employes?limit=200&volet=construction`),
        authedFetch(`/api/v1/projects/${projectId}/phases`)
      ]);
      if (!evRes.ok) throw new Error();
      const all = (await evRes.json()) as ChantierEvent[];
      const realEvents = all.filter((e) => e.project_id === projectId);

      // Transforme les phases du projet en événements virtuels
      // (event_type="phase", id négatif pour ne pas collisionner) afin
      // qu'elles s'affichent dans la liste / le Gantt de l'onglet
      // Agenda chantier — sinon la planification n'apparaissait nulle
      // part en dehors de l'onglet Planification.
      let phaseEvents: ChantierEvent[] = [];
      if (phRes.ok) {
        type Phase = {
          id: number;
          name: string;
          start_date: string | null;
          start_time: string | null;
          duration_days: number | null;
        };
        const phs = (await phRes.json()) as Phase[];
        // Mémorise la liste {id, name} pour le sélecteur de phase
        // dans le formulaire de création d'event.
        setProjectPhases(
          phs.map((p) => ({ id: p.id, name: p.name }))
        );
        phaseEvents = phs
          .filter((p) => p.start_date)
          .map((p) => {
            // Aligne sur les bornes de jour quand la phase est en
            // « journée complète ». Si start_time est défini, la
            // phase est un créneau horaire — on utilise alors
            // start_time + duration × 8 h.
            const dur = Math.max(0.125, Number(p.duration_days) || 1);
            const t = (p.start_time || "00:00:00").slice(0, 8);
            const startMs = new Date(`${p.start_date}T${t}`).getTime();
            const endMs =
              p.start_time != null
                ? startMs + dur * 8 * 3_600_000
                : startMs + dur * 86_400_000;
            return {
              id: -p.id, // négatif pour éviter collision avec events réels
              title: `📐 ${p.name}`,
              description: null,
              location: null,
              start_at: new Date(startMs).toISOString(),
              end_at: new Date(endMs).toISOString(),
              all_day: p.start_time == null,
              project_id: projectId,
              assignee_id: null,
              event_type: "phase"
            };
          });
      }

      setEvents([...realEvents, ...phaseEvents]);
      if (empRes.ok) {
        setEmployes(
          (await empRes.json()) as Array<{ id: number; full_name: string }>
        );
      }
    } catch {
      setError("Chargement échoué.");
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    void load();
  }, [load]);

  function resetForm() {
    setFTitle("");
    setFTime("08:00");
    setFAllDay(false);
    setFDurationDays("1");
    setFPhaseId("");
    setFAssigneeIds([]);
    setFDescription("");
  }

  async function submitForm(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!fTitle.trim()) {
      setError("Le titre est requis.");
      return;
    }
    if (!fDate) {
      setError("La date est requise.");
      return;
    }
    setCreating(true);
    setError(null);
    try {
      // ROUTING UNIFIÉ : pour éviter le doublon entre planification
      // et agenda chantier, on crée la BONNE entité selon le contexte :
      //
      // - all_day coché (multi-jour ou journée entière) → PHASE de
      //   projet, visible dans l'onglet Planification ET (comme event
      //   virtuel) dans tous les calendriers agenda.
      //
      // - all_day décoché (heure spécifique, ex. « Livraison 8h ») →
      //   AgendaEvent ponctuel comme avant.
      //
      // Une seule création, visible partout — plus besoin de doubler.
      if (fAllDay) {
        const dur = Math.max(1, Number(fDurationDays) || 1);
        const res = await authedFetch(
          `/api/v1/projects/${projectId}/phases`,
          {
            method: "POST",
            body: JSON.stringify({
              name: fTitle.trim(),
              start_date: fDate,
              duration_days: dur,
              assignee_employe_ids:
                fAssigneeIds.length > 0 ? fAssigneeIds : null
            })
          }
        );
        if (!res.ok) {
          const txt = await res.text();
          throw new Error(txt.slice(0, 200));
        }
      } else {
        const startIso = new Date(
          `${fDate}T${fTime || "08:00"}:00`
        ).toISOString();
        // Multi-assignees : crée 1 event par personne sélectionnée
        // (le backend ne supporte qu'un assignee_id par event). Si
        // aucun assignee → un seul event sans assignee.
        const targets =
          fAssigneeIds.length > 0 ? fAssigneeIds : [null];
        const phaseLink = fPhaseId ? Number(fPhaseId) : null;
        for (const assigneeId of targets) {
          const res = await authedFetch(`/api/v1/agenda`, {
            method: "POST",
            body: JSON.stringify({
              title: fTitle.trim(),
              description: fDescription.trim() || null,
              start_at: startIso,
              all_day: false,
              project_id: projectId,
              phase_id: phaseLink,
              assignee_id: assigneeId,
              event_type: "chantier"
            })
          });
          if (!res.ok) {
            const txt = await res.text();
            throw new Error(txt.slice(0, 200));
          }
        }
      }
      resetForm();
      setFormOpen(false);
      await load();
    } catch (e) {
      setError(`Ajout échoué : ${(e as Error).message}`);
    } finally {
      setCreating(false);
    }
  }

  async function removeEvent(id: number) {
    // id négatif = phase virtuelle (cf. load) → renvoie l'utilisateur
    // vers l'onglet Planification au lieu de tenter une DELETE qui
    // échouera côté API.
    if (id < 0) {
      setError(
        "Cette ligne vient de la Planification du projet. Modifie-la depuis l'onglet « Planification »."
      );
      return;
    }
    if (!(await confirm("Supprimer cet événement ?"))) return;
    try {
      const res = await authedFetch(`/api/v1/agenda/${id}`, {
        method: "DELETE"
      });
      if (!res.ok && res.status !== 204) throw new Error();
      setEvents((xs) => xs.filter((e) => e.id !== id));
    } catch {
      setError("Suppression échouée.");
    }
  }

  const upcoming = events
    .filter((e) => new Date(e.start_at) >= new Date(Date.now() - 86_400_000))
    .sort(
      (a, b) =>
        new Date(a.start_at).getTime() - new Date(b.start_at).getTime()
    );
  const past = events
    .filter((e) => new Date(e.start_at) < new Date(Date.now() - 86_400_000))
    .sort(
      (a, b) =>
        new Date(b.start_at).getTime() - new Date(a.start_at).getTime()
    );

  if (loading) {
    return (
      <div className="flex min-h-[30vh] items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-accent-500" />
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {error ? (
        <p className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
          {error}
        </p>
      ) : null}

      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="flex-1 min-w-[240px] text-xs text-white/60">
          Tous les événements agenda liés à ce projet — visites, livraisons,
          inspections, etc. Chaque employé voit ces événements dans son
          agenda personnel quand il lui est assigné.
        </p>
        <div className="inline-flex rounded-lg border border-brand-800 bg-brand-900 p-0.5">
          <button
            type="button"
            onClick={() => setView("list")}
            className={`rounded-md px-3 py-1.5 text-xs font-semibold transition ${
              view === "list"
                ? "bg-accent-500 text-brand-950"
                : "text-white/60 hover:text-white"
            }`}
          >
            Liste
          </button>
          <button
            type="button"
            onClick={() => setView("gantt")}
            className={`rounded-md px-3 py-1.5 text-xs font-semibold transition ${
              view === "gantt"
                ? "bg-accent-500 text-brand-950"
                : "text-white/60 hover:text-white"
            }`}
          >
            Gantt
          </button>
        </div>
        <button
          type="button"
          onClick={() => setFormOpen((v) => !v)}
          className="btn-accent shrink-0 text-xs"
        >
          <Plus className="mr-1.5 h-3.5 w-3.5" />
          {formOpen ? "Fermer" : "Ajouter un événement"}
        </button>
      </div>

      {formOpen ? (
        <form
          onSubmit={submitForm}
          className="space-y-3 rounded-xl border border-accent-500/30 bg-accent-500/5 p-4"
        >
          <div>
            <label className="label">Titre *</label>
            <input
              type="text"
              value={fTitle}
              onChange={(e) => setFTitle(e.target.value)}
              placeholder="Ex. Livraison matériaux, inspection finale…"
              className="input"
              autoFocus
              required
            />
          </div>
          <div className="grid gap-3 sm:grid-cols-3">
            <div>
              <label className="label">Date *</label>
              <input
                type="date"
                value={fDate}
                onChange={(e) => setFDate(e.target.value)}
                className="input"
                required
              />
            </div>
            {fAllDay ? (
              <div>
                <label className="label">Durée (jours)</label>
                <input
                  type="number"
                  min="1"
                  step="1"
                  value={fDurationDays}
                  onChange={(e) => setFDurationDays(e.target.value)}
                  className="input"
                />
              </div>
            ) : (
              <div>
                <label className="label">Heure</label>
                <input
                  type="time"
                  value={fTime}
                  onChange={(e) => setFTime(e.target.value)}
                  className="input"
                />
              </div>
            )}
            <div className="flex items-end">
              <label className="flex cursor-pointer items-center gap-2 rounded-lg border border-brand-800 bg-brand-900 px-3 py-2.5 text-sm text-white">
                <input
                  type="checkbox"
                  checked={fAllDay}
                  onChange={(e) => setFAllDay(e.target.checked)}
                  className="h-4 w-4 accent-accent-500"
                />
                <span>Phase de chantier (journée complète)</span>
              </label>
            </div>
          </div>
          <p className="text-[11px] text-white/50">
            <strong>Phase</strong> (case cochée) = bloc de travail
            multi-jour visible dans la Planification ET dans tous les
            calendriers agenda.{" "}
            <strong>Événement</strong> ponctuel (case décochée) =
            moment précis (livraison, inspection…). Tu peux le rattacher
            à une phase existante via le sélecteur ci-dessous.
          </p>
          {!fAllDay && projectPhases.length > 0 ? (
            <div>
              <label className="label">
                Rattacher à une phase (optionnel)
              </label>
              <select
                value={fPhaseId}
                onChange={(e) => setFPhaseId(e.target.value)}
                className="input"
              >
                <option value="">— Aucune phase —</option>
                {projectPhases.map((p) => (
                  <option key={p.id} value={String(p.id)}>
                    {p.name}
                  </option>
                ))}
              </select>
              <p className="mt-1 text-[10px] text-white/40">
                L&apos;événement apparaîtra sous cette phase dans
                l&apos;onglet Planification, en plus de la liste agenda.
              </p>
            </div>
          ) : null}
          <div>
            <label className="label">Assigné(s)</label>
            <MultiSelectDropdown
              options={employes.map((e) => ({
                id: e.id,
                label: e.full_name,
              }))}
              selectedIds={fAssigneeIds}
              onChange={setFAssigneeIds}
              placeholder="— Personne(s) assignée(s) —"
              emptyLabel="Aucun employé disponible"
            />
            <p className="mt-1 text-[11px] text-white/40">
              Si plusieurs personnes sont sélectionnées, un événement sera
              créé pour chacune (chacune le verra dans son agenda).
            </p>
          </div>
          <div>
            <label className="label">Notes</label>
            <textarea
              rows={2}
              value={fDescription}
              onChange={(e) => setFDescription(e.target.value)}
              className="input"
              placeholder="Détails, adresse, contact…"
            />
          </div>
          <div className="flex items-center justify-end gap-2">
            <button
              type="button"
              onClick={() => {
                resetForm();
                setFormOpen(false);
              }}
              className="btn-secondary text-xs"
              disabled={creating}
            >
              Annuler
            </button>
            <button
              type="submit"
              disabled={creating}
              className="btn-accent text-xs disabled:opacity-60"
            >
              {creating ? (
                <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
              ) : null}
              Créer l&apos;événement
            </button>
          </div>
        </form>
      ) : null}

      {view === "gantt" ? (
        <ChantierGantt
          events={events}
          employes={employes}
          onRemoveEvent={removeEvent}
          onOpenPhase={onOpenPhase}
        />
      ) : (
        <>
          <section>
            <h3 className="text-xs font-semibold uppercase tracking-wider text-accent-500">
              À venir ({upcoming.length})
            </h3>
            {upcoming.length === 0 ? (
              <p className="mt-2 text-xs text-white/50">
                Aucun événement à venir.
              </p>
            ) : (
              <ul className="mt-3 space-y-2">
                {upcoming.map((e) => (
                  <EventRow
                    key={e.id}
                    event={e}
                    projectName={projectName}
                    projectEndDate={projectEndDate}
                    onRemove={() => removeEvent(e.id)}
                    onClickPhase={onOpenPhase}
                    onClickEvent={(ev) => setEditingEvent(ev)}
                  />
                ))}
              </ul>
            )}
          </section>

          {past.length > 0 ? (
            <section>
              <h3 className="text-xs font-semibold uppercase tracking-wider text-white/50">
                Passés ({past.length})
              </h3>
              <ul className="mt-3 space-y-2 opacity-70">
                {past.slice(0, 10).map((e) => (
                  <EventRow
                    key={e.id}
                    event={e}
                    projectName={projectName}
                    projectEndDate={projectEndDate}
                    onRemove={() => removeEvent(e.id)}
                    onClickPhase={onOpenPhase}
                    onClickEvent={(ev) => setEditingEvent(ev)}
                  />
                ))}
              </ul>
            </section>
          ) : null}
        </>
      )}

      {editingEvent ? (
        <EventEditModal
          event={editingEvent}
          employes={employes}
          onClose={() => setEditingEvent(null)}
          onSaved={(updated) => {
            setEvents((xs) =>
              xs.map((x) => (x.id === updated.id ? updated : x))
            );
            setEditingEvent(null);
          }}
          onDeleted={(id) => {
            setEvents((xs) => xs.filter((x) => x.id !== id));
            setEditingEvent(null);
          }}
        />
      ) : null}
    </div>
  );
}

function EventEditModal({
  event,
  employes,
  onClose,
  onSaved,
  onDeleted
}: {
  event: ChantierEvent;
  employes: Array<{ id: number; full_name: string }>;
  onClose: () => void;
  onSaved: (e: ChantierEvent) => void;
  onDeleted: (id: number) => void;
}) {
  const confirm = useConfirm();
  const initial = new Date(event.start_at);
  const p2 = (n: number) => String(n).padStart(2, "0");
  const [title, setTitle] = useState(event.title);
  const [date, setDate] = useState(
    `${initial.getFullYear()}-${p2(initial.getMonth() + 1)}-${p2(initial.getDate())}`
  );
  const [time, setTime] = useState(
    event.all_day
      ? "08:00"
      : `${p2(initial.getHours())}:${p2(initial.getMinutes())}`
  );
  const [allDay, setAllDay] = useState(event.all_day);
  const [location, setLocation] = useState(event.location || "");
  const [description, setDescription] = useState(event.description || "");
  const [assigneeId, setAssigneeId] = useState(
    event.assignee_id != null ? String(event.assignee_id) : ""
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function save(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!title.trim()) {
      setError("Le titre est requis.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const startIso = allDay
        ? new Date(`${date}T00:00:00`).toISOString()
        : new Date(`${date}T${time || "08:00"}:00`).toISOString();
      const payload = {
        title: title.trim(),
        description: description.trim() || null,
        location: location.trim() || null,
        start_at: startIso,
        all_day: allDay,
        assignee_id: assigneeId ? Number(assigneeId) : null
      };
      const res = await authedFetch(`/api/v1/agenda/${event.id}`, {
        method: "PATCH",
        body: JSON.stringify(payload)
      });
      if (!res.ok) {
        const txt = await res.text();
        throw new Error(txt.slice(0, 240) || `HTTP ${res.status}`);
      }
      onSaved((await res.json()) as ChantierEvent);
    } catch (err) {
      setError((err as Error).message);
      setBusy(false);
    }
  }

  async function remove() {
    if (
      !(await confirm({
        title: `Supprimer « ${event.title} » ?`,
        description: "L'événement sera effacé définitivement.",
        confirmLabel: "Supprimer",
        destructive: true
      }))
    )
      return;
    setBusy(true);
    try {
      const res = await authedFetch(`/api/v1/agenda/${event.id}`, {
        method: "DELETE"
      });
      if (!res.ok && res.status !== 204) throw new Error();
      onDeleted(event.id);
    } catch {
      setError("Suppression échouée.");
      setBusy(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
      onClick={() => (!busy ? onClose() : null)}
    >
      <form
        onSubmit={save}
        onClick={(e) => e.stopPropagation()}
        className="w-full max-w-md space-y-3 rounded-2xl border border-brand-800 bg-brand-900 p-5"
      >
        <h3 className="text-base font-bold text-white">
          Modifier l&apos;événement
        </h3>
        {error ? (
          <p className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
            {error}
          </p>
        ) : null}
        <div>
          <label className="label text-[10px] uppercase">Titre</label>
          <input
            className="input"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="Titre de l'événement"
            autoFocus
          />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="label text-[10px] uppercase">Date</label>
            <input
              type="date"
              className="input"
              value={date}
              onChange={(e) => setDate(e.target.value)}
            />
          </div>
          <div>
            <label className="label text-[10px] uppercase">Heure</label>
            <input
              type="time"
              className="input"
              value={time}
              onChange={(e) => setTime(e.target.value)}
              disabled={allDay}
            />
          </div>
        </div>
        <label className="flex items-center gap-2 text-xs text-white/70">
          <input
            type="checkbox"
            checked={allDay}
            onChange={(e) => setAllDay(e.target.checked)}
          />
          Journée complète
        </label>
        <div>
          <label className="label text-[10px] uppercase">Assigné à</label>
          <select
            className="input"
            value={assigneeId}
            onChange={(e) => setAssigneeId(e.target.value)}
          >
            <option value="">—</option>
            {employes.map((e) => (
              <option key={e.id} value={String(e.id)}>
                {e.full_name}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="label text-[10px] uppercase">Lieu</label>
          <input
            className="input"
            value={location}
            onChange={(e) => setLocation(e.target.value)}
            placeholder="Adresse du chantier, bureau…"
          />
        </div>
        <div>
          <label className="label text-[10px] uppercase">Description</label>
          <textarea
            className="input min-h-[80px]"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
          />
        </div>
        <div className="flex items-center justify-between pt-2">
          <button
            type="button"
            onClick={remove}
            disabled={busy}
            className="rounded-md border border-rose-500/40 px-3 py-1.5 text-xs text-rose-300 hover:bg-rose-500/10 disabled:opacity-40"
          >
            <Trash2 className="mr-1 inline-block h-3.5 w-3.5" />
            Supprimer
          </button>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={onClose}
              disabled={busy}
              className="rounded-md px-3 py-1.5 text-xs text-white/70 hover:bg-white/5"
            >
              Annuler
            </button>
            <button
              type="submit"
              disabled={busy}
              className="btn-accent text-xs disabled:opacity-60"
            >
              {busy ? (
                <Loader2 className="mr-1.5 inline-block h-3.5 w-3.5 animate-spin" />
              ) : null}
              Enregistrer
            </button>
          </div>
        </div>
      </form>
    </div>
  );
}

function EventRow({
  event,
  projectName,
  projectEndDate,
  onRemove,
  onClickPhase,
  onClickEvent
}: {
  event: ChantierEvent;
  projectName: string;
  projectEndDate?: string | null;
  onRemove: () => void;
  onClickPhase?: (phaseId: number) => void;
  onClickEvent?: (e: ChantierEvent) => void;
}) {
  const s = new Date(event.start_at);
  const dayFmt = s.toLocaleDateString("fr-CA", {
    weekday: "short",
    day: "numeric",
    month: "short",
    year: "numeric"
  });
  const timeFmt = event.all_day
    ? "Journée complète"
    : s.toLocaleTimeString("fr-CA", {
        hour: "2-digit",
        minute: "2-digit"
      });
  const isPhase = event.event_type === "phase";
  const clickable = isPhase
    ? !!onClickPhase
    : !!onClickEvent;
  // Détecte un event hors-délai (après date fin projet) → mise en
  // évidence jaune ambré, cohérent avec l'agenda.
  let outOfRange = false;
  if (projectEndDate) {
    const [y, m, d] = projectEndDate.split("-").map(Number);
    if (y && m && d) {
      const projectEnd = new Date(y, m - 1, d, 23, 59, 59, 999);
      outOfRange = s > projectEnd;
    }
  }
  return (
    <li
      className={`flex items-start justify-between gap-3 rounded-xl border p-3 ${
        outOfRange
          ? "border-amber-400/60 bg-amber-500/10"
          : "border-brand-800 bg-brand-900"
      } ${clickable ? "cursor-pointer hover:border-accent-500" : ""}`}
      onClick={
        isPhase && onClickPhase
          ? () => onClickPhase(Math.abs(event.id))
          : onClickEvent
          ? () => onClickEvent(event)
          : undefined
      }
    >
      <div className="min-w-0">
        <p className="text-sm font-semibold text-white">{event.title}</p>
        <p className="mt-0.5 text-xs text-white/60">
          {dayFmt} · {timeFmt}
          {outOfRange ? (
            <span className="ml-2 rounded bg-amber-500/20 px-1.5 py-0.5 text-[10px] font-semibold text-amber-200">
              Hors délai
            </span>
          ) : null}
        </p>
        {event.location ? (
          <p className="mt-0.5 text-xs text-white/50">📍 {event.location}</p>
        ) : null}
        <span className="mt-1 inline-flex rounded bg-white/5 px-1.5 py-0.5 text-[10px] uppercase text-white/50">
          {event.event_type} · {projectName}
        </span>
      </div>
      {isPhase ? null : (
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            onRemove();
          }}
          className="rounded p-1 text-white/40 hover:text-rose-300"
          aria-label="Supprimer"
        >
          <Trash2 className="h-3.5 w-3.5" />
        </button>
      )}
    </li>
  );
}

// ---------- Vue Gantt de l'agenda chantier ----------
// Une rangée par événement, ordonné par date. La timeline horizontale
// couvre min(start) → max(end_or_start), avec une marge de 1 jour.
// Bar = durée de l'événement (1 jour si all_day sans end_at). Click
// sur la barre = ouvre le détail (pour l'instant : delete via icône
// sous le titre, comme dans EventRow).

function ChantierGantt({
  events,
  employes,
  onRemoveEvent,
  onOpenPhase
}: {
  events: ChantierEvent[];
  employes: Array<{ id: number; full_name: string }>;
  onRemoveEvent: (id: number) => void;
  onOpenPhase: (phaseId: number) => void;
}) {
  const empById = useMemo(() => {
    const m = new Map<number, string>();
    employes.forEach((e) => m.set(e.id, e.full_name));
    return m;
  }, [employes]);

  const sorted = useMemo(
    () =>
      [...events].sort(
        (a, b) =>
          new Date(a.start_at).getTime() - new Date(b.start_at).getTime()
      ),
    [events]
  );

  if (sorted.length === 0) {
    return (
      <p className="rounded-xl border border-dashed border-brand-800 bg-brand-900/40 px-4 py-8 text-center text-xs text-white/50">
        Aucun événement pour ce projet — passe en vue Liste pour en ajouter
        un.
      </p>
    );
  }

  // Timeline range : min(start) → max(end || start). On NE prolonge
  // PAS la fin à 23h59 — sinon une phase de 1 j qui termine à minuit
  // pile (start + 24 h) ajoute une colonne vide pour le lendemain.
  const ts = sorted.map((e) => new Date(e.start_at).getTime());
  const tsEnd = sorted.map((e) =>
    new Date(e.end_at || e.start_at).getTime()
  );
  const rangeStart = new Date(Math.min(...ts));
  rangeStart.setHours(0, 0, 0, 0);
  // Pour la fin, on prend max(end_at) mais on retire 1 ms si c'est
  // pile sur un minuit (cas standard d'une phase all-day = start + N×24h).
  // Comme ça la dernière colonne représente bien le dernier jour
  // d'activité, sans phantom day.
  let rangeEndMs = Math.max(...tsEnd);
  const lastDate = new Date(rangeEndMs);
  if (
    lastDate.getHours() === 0 &&
    lastDate.getMinutes() === 0 &&
    lastDate.getSeconds() === 0 &&
    lastDate.getMilliseconds() === 0
  ) {
    rangeEndMs -= 1;
  }
  const rangeEndRaw = new Date(rangeEndMs);
  // Ajoute au moins 7 jours d'amplitude pour les projets très courts
  const minAmplitudeMs = 7 * 86400000;
  const rangeEnd =
    rangeEndRaw.getTime() - rangeStart.getTime() < minAmplitudeMs
      ? new Date(rangeStart.getTime() + minAmplitudeMs)
      : rangeEndRaw;
  const totalMs = rangeEnd.getTime() - rangeStart.getTime();

  // Découpe la frise horizontale en jours pour les graduations.
  const days: Date[] = [];
  for (
    let d = new Date(rangeStart);
    d.getTime() <= rangeEnd.getTime();
    d.setDate(d.getDate() + 1)
  ) {
    days.push(new Date(d));
  }
  const dayWidthPct = 100 / days.length;

  // Couleur par event_type (cohérent avec /app/agenda).
  function colorFor(type: string): string {
    switch (type) {
      case "phase":
        return "#d4ff3a"; // accent (planification du projet)
      case "chantier":
        return "#3b82f6"; // blue
      case "livraison":
        return "#a855f7"; // purple
      case "inspection":
        return "#ef4444"; // red
      case "visite":
        return "#10b981"; // emerald
      case "conge":
        return "#f59e0b"; // amber
      default:
        return "#64748b"; // slate
    }
  }

  function dayLabel(d: Date): string {
    return d.toLocaleDateString("fr-CA", {
      day: "2-digit",
      month: "short"
    });
  }

  return (
    <div className="overflow-x-auto rounded-xl border border-brand-800 bg-brand-900">
      <div className="min-w-[860px] p-4">
        {/* Header timeline */}
        <div className="mb-3 grid grid-cols-[180px_1fr] gap-3">
          <div className="text-[10px] font-semibold uppercase tracking-wider text-white/50">
            Événement
          </div>
          <div className="relative h-5">
            {days.map((d, i) => (
              <div
                key={i}
                className="absolute top-0 text-center text-[9px] text-white/40 tabular-nums"
                style={{
                  left: `${i * dayWidthPct}%`,
                  width: `${dayWidthPct}%`
                }}
              >
                {/* Affiche 1 label sur N selon la densité */}
                {days.length <= 14 || i % Math.ceil(days.length / 14) === 0
                  ? dayLabel(d)
                  : ""}
              </div>
            ))}
          </div>
        </div>

        {/* Bars */}
        <ul className="space-y-1.5">
          {sorted.map((e) => {
            const start = new Date(e.start_at).getTime();
            const end = new Date(e.end_at || e.start_at).getTime();
            const leftPct = Math.max(
              0,
              ((start - rangeStart.getTime()) / totalMs) * 100
            );
            // Largeur minimale visible = 1 jour
            const dayPct = (86400000 / totalMs) * 100;
            const widthPct = Math.max(
              dayPct,
              ((end - start) / totalMs) * 100
            );
            const color = colorFor(e.event_type);
            const assignee =
              e.assignee_id != null ? empById.get(e.assignee_id) : null;
            const dateLabel = new Date(e.start_at).toLocaleDateString(
              "fr-CA",
              { day: "2-digit", month: "short" }
            );
            return (
              <li
                key={e.id}
                className={`grid grid-cols-[180px_1fr] items-center gap-3 ${
                  e.event_type === "phase"
                    ? "cursor-pointer rounded hover:bg-accent-500/5"
                    : ""
                }`}
                onClick={
                  e.event_type === "phase"
                    ? () => onOpenPhase(Math.abs(e.id))
                    : undefined
                }
              >
                <div className="flex min-w-0 items-start gap-1.5">
                  {e.event_type === "phase" ? null : (
                    <button
                      type="button"
                      onClick={() => onRemoveEvent(e.id)}
                      className="mt-0.5 flex-shrink-0 rounded p-0.5 text-white/30 hover:text-rose-300"
                      aria-label="Supprimer"
                      title="Supprimer"
                    >
                      <Trash2 className="h-3 w-3" />
                    </button>
                  )}
                  <div className="min-w-0">
                    <p className="truncate text-xs font-semibold text-white">
                      {e.title}
                    </p>
                    <p className="truncate text-[10px] text-white/50">
                      {dateLabel}
                      {assignee ? ` · ${assignee.split(" ")[0]}` : ""}
                    </p>
                  </div>
                </div>
                <div className="relative h-6 rounded bg-brand-950/40">
                  {/* Lignes de jours */}
                  {days.map((_, i) => (
                    <div
                      key={i}
                      className="absolute top-0 h-full border-l border-white/[0.04]"
                      style={{ left: `${i * dayWidthPct}%` }}
                    />
                  ))}
                  <div
                    className="absolute top-0 h-full rounded transition hover:opacity-90"
                    style={{
                      left: `${leftPct}%`,
                      width: `${widthPct}%`,
                      backgroundColor: `${color}30`,
                      borderLeft: `3px solid ${color}`
                    }}
                    title={`${e.title} · ${dateLabel}${
                      assignee ? ` · ${assignee}` : ""
                    }`}
                  >
                    <span
                      className="block truncate px-2 py-1 text-[10px] font-medium text-white"
                      style={{ color }}
                    >
                      {e.title}
                    </span>
                  </div>
                </div>
              </li>
            );
          })}
        </ul>

        {/* Légende */}
        <div className="mt-4 flex flex-wrap items-center gap-3 border-t border-brand-800 pt-3 text-[10px] text-white/50">
          <span className="font-semibold uppercase tracking-wider">
            Légende
          </span>
          {(
            [
              ["phase", "Phase planifiée"],
              ["chantier", "Chantier"],
              ["livraison", "Livraison"],
              ["inspection", "Inspection"],
              ["visite", "Visite"],
              ["conge", "Congé"]
            ] as const
          ).map(([type, label]) => (
            <span key={type} className="inline-flex items-center gap-1.5">
              <span
                className="h-2 w-2 rounded-sm"
                style={{ backgroundColor: colorFor(type) }}
              />
              {label}
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}

// ---------- Team assignment on a project ----------

type TeamMember = {
  id: number;
  email: string;
  role: string;
  full_name?: string | null;
};

function ProjectTeamSection({
  projectId,
  phases
}: {
  projectId: number;
  phases: Phase[];
}) {
  const [members, setMembers] = useState<TeamMember[]>([]);
  const [allUsers, setAllUsers] = useState<TeamMember[]>([]);
  const [responsibleId, setResponsibleId] = useState<number | null>(null);
  const [savingResp, setSavingResp] = useState(false);
  const [loading, setLoading] = useState(true);
  const [picking, setPicking] = useState(false);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [mRes, uRes, pRes] = await Promise.all([
        authedFetch(`/api/v1/projects/${projectId}/members`),
        authedFetch("/api/v1/users"),
        authedFetch(`/api/v1/projects/${projectId}`)
      ]);
      if (mRes.ok) setMembers((await mRes.json()) as TeamMember[]);
      if (uRes.ok) setAllUsers((await uRes.json()) as TeamMember[]);
      if (pRes.ok) {
        const proj = (await pRes.json()) as {
          responsible_user_id: number | null;
        };
        setResponsibleId(proj.responsible_user_id ?? null);
      }
    } catch {
      setErr("Chargement de l'équipe échoué.");
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  async function setResponsible(userId: number | null) {
    setSavingResp(true);
    setErr(null);
    const prev = responsibleId;
    setResponsibleId(userId);
    try {
      const res = await authedFetch(`/api/v1/projects/${projectId}`, {
        method: "PUT",
        body: JSON.stringify({ responsible_user_id: userId })
      });
      if (!res.ok) {
        const txt = await res.text();
        throw new Error(`${res.status} — ${txt.slice(0, 200)}`);
      }
    } catch (e) {
      setResponsibleId(prev);
      setErr(`Responsable non enregistré : ${(e as Error).message}`);
    } finally {
      setSavingResp(false);
    }
  }

  useEffect(() => {
    void load();
  }, [load]);

  async function addMember(userId: number) {
    setSaving(true);
    setErr(null);
    try {
      const nextIds = [...new Set([...members.map((m) => m.id), userId])];
      const res = await authedFetch(`/api/v1/projects/${projectId}/members`, {
        method: "PUT",
        body: JSON.stringify({ user_ids: nextIds })
      });
      if (!res.ok) {
        const txt = await res.text();
        throw new Error(`${res.status} — ${txt.slice(0, 200)}`);
      }
      setMembers((await res.json()) as TeamMember[]);
      setPicking(false);
    } catch (e) {
      setErr(`Ajout membre échoué : ${(e as Error).message}`);
    } finally {
      setSaving(false);
    }
  }

  async function removeMember(userId: number) {
    setSaving(true);
    setErr(null);
    try {
      const res = await authedFetch(
        `/api/v1/projects/${projectId}/members/${userId}`,
        { method: "DELETE" }
      );
      if (!res.ok && res.status !== 204) throw new Error();
      setMembers((xs) => xs.filter((m) => m.id !== userId));
    } catch {
      setErr("Retrait membre échoué.");
    } finally {
      setSaving(false);
    }
  }

  const notAssigned = allUsers.filter(
    (u) => !members.some((m) => m.id === u.id)
  );

  // Une personne assignée à au moins une phase compte comme "sur le
  // projet" pour éviter le warning rouge alors qu'une ressource est
  // déjà prévue. On déduplique sur (employe_id, sous_traitant_id).
  const phaseAssigneeKeys = new Set<string>();
  for (const ph of phases) {
    if (ph.assignee_employe_id) {
      phaseAssigneeKeys.add(`emp-${ph.assignee_employe_id}`);
    }
    if (ph.assignee_sous_traitant_id) {
      phaseAssigneeKeys.add(`st-${ph.assignee_sous_traitant_id}`);
    }
  }
  const phaseAssigneeCount = phaseAssigneeKeys.size;
  const hasAnyTeam = members.length > 0 || phaseAssigneeCount > 0;

  return (
    <section
      className={`rounded-2xl border p-4 ${
        hasAnyTeam
          ? "border-emerald-500/30 bg-emerald-500/5"
          : "border-rose-500/40 bg-rose-500/5"
      }`}
    >
      <div className="flex flex-wrap items-center gap-2">
        <p className="text-sm font-semibold text-white">
          {hasAnyTeam ? "🛠️" : "⚠️"} Équipe sur ce projet
        </p>
        <span className="text-xs text-white/60">
          ({members.length} {members.length === 1 ? "personne" : "personnes"}
          {phaseAssigneeCount > 0
            ? ` + ${phaseAssigneeCount} via phases`
            : ""}
          )
        </span>
        <button
          type="button"
          onClick={() => setPicking((v) => !v)}
          disabled={saving || notAssigned.length === 0}
          className="ml-auto btn-accent text-xs disabled:opacity-50"
          title={
            notAssigned.length === 0
              ? "Tous les utilisateurs sont déjà assignés"
              : "Ajouter un membre"
          }
        >
          {picking ? "Fermer" : "+ Ajouter"}
        </button>
      </div>

      {err ? (
        <p className="mt-2 text-xs text-rose-300">{err}</p>
      ) : null}

      {/* Responsable du projet : vers qui la téléphonie (Léa) route un
          appel de suivi d'un client existant. */}
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <label
          htmlFor="project-responsible"
          className="text-xs font-semibold text-white/80"
        >
          📞 Responsable (suivi d&apos;appel) :
        </label>
        <select
          id="project-responsible"
          value={responsibleId ?? ""}
          disabled={savingResp || loading}
          onChange={(e) =>
            setResponsible(e.target.value ? Number(e.target.value) : null)
          }
          className="rounded-md border border-brand-700 bg-brand-900 px-2.5 py-1 text-xs text-white focus:border-accent-500 focus:outline-none disabled:opacity-50"
        >
          <option value="">— Aucun (réception / back-office) —</option>
          {allUsers.map((u) => (
            <option key={u.id} value={u.id}>
              {u.full_name || u.email}
            </option>
          ))}
        </select>
        {savingResp ? (
          <Loader2 className="h-3.5 w-3.5 animate-spin text-white/50" />
        ) : null}
      </div>

      {loading ? (
        <div className="mt-3 flex items-center gap-2 text-xs text-white/50">
          <Loader2 className="h-3.5 w-3.5 animate-spin" />
          Chargement…
        </div>
      ) : members.length === 0 && phaseAssigneeCount === 0 ? (
        <p className="mt-2 text-xs text-rose-200/90">
          Aucune personne assignée. L&apos;agenda affiche ce projet en rouge
          ⚠️ tant qu&apos;au moins une personne n&apos;est pas ajoutée (soit
          ici, soit sur une phase plus bas).
        </p>
      ) : members.length === 0 ? (
        <p className="mt-2 text-xs text-emerald-200/90">
          {phaseAssigneeCount} personne{phaseAssigneeCount > 1 ? "s" : ""}{" "}
          assignée{phaseAssigneeCount > 1 ? "s" : ""} via des phases — ajoute
          un membre ici pour un accès global au projet.
        </p>
      ) : (
        <ul className="mt-3 flex flex-wrap gap-2">
          {members.map((m) => {
            const displayName = m.full_name || m.email;
            return (
              <li
                key={m.id}
                className="group flex items-center gap-2 rounded-full border border-emerald-500/30 bg-emerald-500/10 px-3 py-1 text-xs text-white"
                title={m.full_name ? m.email : undefined}
              >
                <span className="font-semibold">{displayName}</span>
                <span className="rounded bg-white/10 px-1.5 py-0.5 text-[9px] uppercase text-white/60">
                  {m.role}
                </span>
                <button
                  type="button"
                  onClick={() => removeMember(m.id)}
                  disabled={saving}
                  className="text-white/40 hover:text-rose-300"
                  aria-label="Retirer du projet"
                >
                  <Trash2 className="h-3 w-3" />
                </button>
              </li>
            );
          })}
        </ul>
      )}

      {picking ? (
        <div className="mt-3 rounded-lg border border-brand-800 bg-brand-950 p-3">
          <p className="text-xs text-white/60">
            Choisis une personne à ajouter au projet :
          </p>
          <ul className="mt-2 max-h-48 overflow-y-auto space-y-1">
            {notAssigned.map((u) => (
              <li key={u.id}>
                <button
                  type="button"
                  onClick={() => addMember(u.id)}
                  disabled={saving}
                  className="flex w-full items-center justify-between gap-2 rounded-md px-2 py-1.5 text-left text-xs text-white hover:bg-accent-500/10"
                >
                  <span className="min-w-0 truncate">
                    <span className="font-medium">
                      {u.full_name || u.email}
                    </span>
                    {u.full_name ? (
                      <span className="ml-2 text-white/40">{u.email}</span>
                    ) : null}
                  </span>
                  <span className="rounded bg-white/5 px-1.5 py-0.5 text-[9px] uppercase text-white/50">
                    {u.role}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </section>
  );
}

// ---------------------------------------------------------------------------
// Onglet Achats / PO dans la fiche projet — montre 2 sections :
// les Bons de commande (planification) et les Achats (transactions
// comptables qui chargent réellement le projet). Bouton + Nouveau PO
// + Nouveau achat directement depuis ici, avec project_id pré-rempli.
// ---------------------------------------------------------------------------

type ProjectPo = {
  id: number;
  reference: string;
  fournisseur_id: number | null;
  project_id: number | null;
  assigned_employe_id: number | null;
  description: string | null;
  amount_max: number | string | null;
  status: string;
  payment_method: string | null;
};

type ProjectAchat = {
  id: number;
  reference: string | null;
  purchase_order_id: number | null;
  fournisseur_id: number | null;
  project_id: number | null;
  description: string | null;
  amount: number | string | null;
  amount_taxes: number | string | null;
  supplier_invoice_number: string | null;
  invoice_date: string | null;
  status: string;
  payment_method: string | null;
  qbo_bill_id: string | null;
};

type ProjectFournisseur = { id: number; name: string };

const PO_STATUS_LABEL: Record<string, string> = {
  draft: "Planifié",
  sent: "PO envoyé",
  fulfilled: "Achat créé",
  cancelled: "Annulé"
};

const PO_STATUS_BG: Record<string, string> = {
  draft: "bg-white/10 text-white/70 border-white/20",
  sent: "bg-blue-500/15 text-blue-300 border-blue-500/30",
  fulfilled: "bg-emerald-500/15 text-emerald-300 border-emerald-500/30",
  cancelled: "bg-rose-500/15 text-rose-300 border-rose-500/30"
};

const ACHAT_STATUS_LABEL: Record<string, string> = {
  received: "À payer",
  paid: "Payé",
  cancelled: "Annulé"
};

const ACHAT_STATUS_BG: Record<string, string> = {
  received: "bg-amber-500/15 text-amber-300 border-amber-500/30",
  paid: "bg-emerald-500/15 text-emerald-300 border-emerald-500/30",
  cancelled: "bg-rose-500/15 text-rose-300 border-rose-500/30"
};

const ACHAT_PAYMENT_LABEL: Record<string, string> = {
  bill_to_pay: "Sur compte",
  cheque_horizon: "Chèque",
  cc_steven: "CC Steven",
  cc_michael: "CC Michael",
  cc_olivier: "CC Olivier",
  cc_christian: "CC Christian"
};

function ProjectAchatsTab({ projectId }: { projectId: number }) {
  // URL de retour passée aux pages de détail PO / achat : un clic sur
  // « Retour » y ramène l'utilisateur sur cet onglet plutôt que sur la
  // liste globale Achats / dépenses du menu latéral.
  const backToTab = encodeURIComponent(`/app/projets/${projectId}#achats`);
  const [pos, setPos] = useState<ProjectPo[]>([]);
  const [achats, setAchats] = useState<ProjectAchat[]>([]);
  const [fournisseurs, setFournisseurs] = useState<ProjectFournisseur[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  // Achat ciblé par le modal « marquer payé » (clic sur le badge « À payer »).
  const [payTarget, setPayTarget] = useState<MarkPaidAchat | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      try {
        const [poRes, aRes, frRes] = await Promise.all([
          authedFetch("/api/v1/purchase-orders?limit=500"),
          authedFetch("/api/v1/achats?limit=500"),
          authedFetch("/api/v1/fournisseurs?limit=500")
        ]);
        if (!aRes.ok || !poRes.ok) throw new Error();
        const allPos = (await poRes.json()) as ProjectPo[];
        const allAchats = (await aRes.json()) as ProjectAchat[];
        if (!cancelled) {
          setPos(allPos.filter((p) => p.project_id === projectId));
          setAchats(allAchats.filter((a) => a.project_id === projectId));
          setFournisseurs(
            frRes.ok
              ? ((await frRes.json()) as ProjectFournisseur[])
              : []
          );
        }
      } catch {
        if (!cancelled) setError("Chargement échoué.");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  const fournisseurById = useMemo(() => {
    const m = new Map<number, ProjectFournisseur>();
    fournisseurs.forEach((f) => m.set(f.id, f));
    return m;
  }, [fournisseurs]);

  function fmt(n: number): string {
    return new Intl.NumberFormat("fr-CA", {
      style: "currency",
      currency: "CAD",
      minimumFractionDigits: 2,
      maximumFractionDigits: 2
    }).format(n);
  }

  // Affichage TTC (taxes incluses). Les PO n'ont pas de taxes stockées →
  // on applique le facteur QC standard ; les achats ont leurs taxes
  // réelles (amount + amount_taxes).
  const poTotal = pos.reduce(
    (s, p) =>
      s + (p.amount_max != null ? Number(p.amount_max) * TAX_FACTOR : 0),
    0
  );
  const achatTotal = achats.reduce(
    (s, a) =>
      s +
      (a.amount != null ? Number(a.amount) : 0) +
      (a.amount_taxes != null ? Number(a.amount_taxes) : 0),
    0
  );
  // Détail HT / taxes pour l'en-tête (« sans taxes + taxes = total »).
  const achatHT = achats.reduce(
    (s, a) => s + (a.amount != null ? Number(a.amount) : 0),
    0
  );
  const achatTaxes = achats.reduce(
    (s, a) => s + (a.amount_taxes != null ? Number(a.amount_taxes) : 0),
    0
  );

  // POs actifs (pas annulés ni convertis) → les pertinents pour le suivi.
  const activePos = pos.filter(
    (p) => p.status !== "cancelled" && p.status !== "fulfilled"
  );

  return (
    <section className="space-y-6">
      <header>
        <h2 className="text-base font-bold text-white">
          Bons de commande &amp; achats
        </h2>
        <p className="mt-0.5 text-xs text-white/60">
          Les <strong>POs</strong> sont des autorisations internes (pas
          d&apos;impact comptable). Les <strong>Achats</strong> sont les
          transactions réelles qui chargent la section{" "}
          <span className="text-accent-400">Coût matériel réel</span> de
          l&apos;onglet Finances.
        </p>
      </header>

      {error ? (
        <p className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
          {error}
        </p>
      ) : null}

      {loading ? (
        <div className="flex min-h-[20vh] items-center justify-center">
          <Loader2 className="h-5 w-5 animate-spin text-accent-500" />
        </div>
      ) : (
        <>
          {/* Section : Bons de commande */}
          <section>
            <header className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
              <h3 className="text-sm font-semibold uppercase tracking-wider text-accent-500">
                📋 Bons de commande ({activePos.length} actifs · {fmt(poTotal)} max)
              </h3>
              <Link
                // eslint-disable-next-line @typescript-eslint/no-explicit-any
                href={`/app/po/new?project_id=${projectId}` as any}
                className="btn-secondary text-xs"
              >
                + Nouveau PO
              </Link>
            </header>
            {pos.length === 0 ? (
              <div className="rounded-xl border border-dashed border-brand-800 bg-brand-900/40 px-4 py-6 text-center text-xs text-white/50">
                Aucun PO pour ce projet.
              </div>
            ) : (
              <div className="overflow-x-auto rounded-xl border border-brand-800 bg-brand-900">
                <table className="w-full min-w-[720px] text-sm">
                  <thead className="border-b border-brand-800 bg-brand-950/50 text-left text-[11px] uppercase tracking-wider text-white/50">
                    <tr>
                      <th className="px-3 py-2">PO</th>
                      <th className="px-3 py-2">Fournisseur</th>
                      <th className="px-3 py-2">Description</th>
                      <th className="px-3 py-2">Paiement</th>
                      <th className="px-3 py-2 text-right">Max autorisé</th>
                      <th className="px-3 py-2 text-center">Statut</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-brand-800">
                    {pos.map((p) => {
                      const fr = p.fournisseur_id
                        ? fournisseurById.get(p.fournisseur_id)
                        : null;
                      const amt =
                        p.amount_max != null
                          ? Number(p.amount_max) * TAX_FACTOR
                          : 0;
                      return (
                        <tr key={p.id} className="hover:bg-brand-800/30">
                          <td className="px-3 py-2">
                            <Link
                              // eslint-disable-next-line @typescript-eslint/no-explicit-any
                              href={`/app/po/${p.id}?from=${backToTab}` as any}
                              className="font-mono text-accent-400 hover:underline"
                            >
                              {p.reference}
                            </Link>
                          </td>
                          <td className="px-3 py-2 text-white/80">
                            {fr?.name || "—"}
                          </td>
                          <td className="px-3 py-2 text-white/70">
                            <span className="line-clamp-1">
                              {p.description || "—"}
                            </span>
                          </td>
                          <td className="px-3 py-2 text-[11px] text-white/60">
                            {ACHAT_PAYMENT_LABEL[p.payment_method || ""] ||
                              (p.payment_method
                                ? p.payment_method
                                : "—")}
                          </td>
                          <td className="px-3 py-2 text-right font-semibold text-white">
                            {fmt(amt)}
                          </td>
                          <td className="px-3 py-2 text-center">
                            <span
                              className={`rounded-full border px-2 py-0.5 text-[10px] font-semibold ${
                                PO_STATUS_BG[p.status] ||
                                "border-white/20 bg-white/10 text-white/70"
                              }`}
                            >
                              {PO_STATUS_LABEL[p.status] || p.status}
                            </span>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          {/* Section : Achats / dépenses */}
          <section>
            <header className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
              <h3 className="text-sm font-semibold uppercase tracking-wider text-emerald-400">
                💸 Achats / dépenses ({achats.length} · {fmt(achatHT)} +{" "}
                {fmt(achatTaxes)} taxes = {fmt(achatTotal)})
              </h3>
              <Link
                // eslint-disable-next-line @typescript-eslint/no-explicit-any
                href={`/app/achats/new?project_id=${projectId}` as any}
                className="btn-secondary text-xs"
              >
                + Nouvel achat
              </Link>
            </header>
            {achats.length === 0 ? (
              <div className="rounded-xl border border-dashed border-brand-800 bg-brand-900/40 px-4 py-6 text-center text-xs text-white/50">
                Aucun achat enregistré pour ce projet.
              </div>
            ) : (
              <div className="overflow-x-auto rounded-xl border border-brand-800 bg-brand-900">
                <table className="w-full min-w-[860px] text-sm">
                  <thead className="border-b border-brand-800 bg-brand-950/50 text-left text-[11px] uppercase tracking-wider text-white/50">
                    <tr>
                      <th className="px-3 py-2">Réf.</th>
                      <th className="px-3 py-2">PO</th>
                      <th className="px-3 py-2">Fournisseur</th>
                      <th className="px-3 py-2">Description</th>
                      <th className="px-3 py-2">Paiement</th>
                      <th className="px-3 py-2 text-right">Montant</th>
                      <th className="px-3 py-2 text-center">Statut</th>
                      <th className="px-3 py-2 text-center">QB</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-brand-800">
                    {achats.map((a) => {
                      const fr = a.fournisseur_id
                        ? fournisseurById.get(a.fournisseur_id)
                        : null;
                      const amt =
                        (a.amount != null ? Number(a.amount) : 0) +
                        (a.amount_taxes != null ? Number(a.amount_taxes) : 0);
                      const linkedPo = a.purchase_order_id
                        ? pos.find((p) => p.id === a.purchase_order_id)
                        : null;
                      return (
                        <tr key={a.id} className="hover:bg-brand-800/30">
                          <td className="px-3 py-2">
                            <Link
                              // eslint-disable-next-line @typescript-eslint/no-explicit-any
                              href={`/app/achats/${a.id}?from=${backToTab}` as any}
                              className="font-mono text-accent-400 hover:underline"
                            >
                              {a.supplier_invoice_number ||
                                a.reference ||
                                `A-${a.id}`}
                            </Link>
                          </td>
                          <td className="px-3 py-2 text-[11px]">
                            {linkedPo ? (
                              <Link
                                // eslint-disable-next-line @typescript-eslint/no-explicit-any
                                href={`/app/po/${linkedPo.id}?from=${backToTab}` as any}
                                className="text-accent-400 hover:underline"
                              >
                                {linkedPo.reference}
                              </Link>
                            ) : (
                              <span className="text-white/30">—</span>
                            )}
                          </td>
                          <td className="px-3 py-2 text-white/80">
                            {fr?.name || "—"}
                          </td>
                          <td className="px-3 py-2 text-white/70">
                            <span className="line-clamp-1">
                              {a.description || "—"}
                            </span>
                          </td>
                          <td className="px-3 py-2 text-[11px] text-white/60">
                            {ACHAT_PAYMENT_LABEL[a.payment_method || ""] ||
                              (a.payment_method ? a.payment_method : "—")}
                          </td>
                          <td className="px-3 py-2 text-right font-semibold text-white">
                            {fmt(amt)}
                          </td>
                          <td className="px-3 py-2 text-center">
                            {a.status === "received" ? (
                              <button
                                type="button"
                                onClick={() =>
                                  setPayTarget({
                                    id: a.id,
                                    reference:
                                      a.supplier_invoice_number ||
                                      a.reference ||
                                      `A-${a.id}`,
                                    description: a.description,
                                    payment_method: a.payment_method
                                  })
                                }
                                title="Cliquer pour marquer payé"
                                className={`rounded-full border px-2 py-0.5 text-[10px] font-semibold transition hover:ring-2 hover:ring-emerald-400/60 ${
                                  ACHAT_STATUS_BG[a.status] ||
                                  "border-white/20 bg-white/10 text-white/70"
                                }`}
                              >
                                {ACHAT_STATUS_LABEL[a.status] || a.status}
                              </button>
                            ) : (
                              <span
                                className={`rounded-full border px-2 py-0.5 text-[10px] font-semibold ${
                                  ACHAT_STATUS_BG[a.status] ||
                                  "border-white/20 bg-white/10 text-white/70"
                                }`}
                              >
                                {ACHAT_STATUS_LABEL[a.status] || a.status}
                              </span>
                            )}
                          </td>
                          <td className="px-3 py-2 text-center">
                            {a.qbo_bill_id ? (
                              <span className="text-xs text-emerald-400">
                                ✓
                              </span>
                            ) : (
                              <span className="text-xs text-white/30">
                                —
                              </span>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </>
      )}
      {payTarget ? (
        <AchatMarkPaidModal
          achat={payTarget}
          onClose={() => setPayTarget(null)}
          onSaved={(u) => {
            setAchats((prev) =>
              prev.map((x) =>
                x.id === u.id
                  ? {
                      ...x,
                      status: u.status ?? "paid",
                      payment_method: u.payment_method ?? x.payment_method
                    }
                  : x
              )
            );
            setPayTarget(null);
          }}
        />
      ) : null}
    </section>
  );
}

// ─── Ligne de facture émise dans la section Facturation ─────────────────

const INVOICE_STATUS_LABEL: Record<string, string> = {
  draft: "Brouillon",
  sent: "Envoyée",
  paid: "Payée",
  overdue: "En retard",
  void: "Annulée"
};

const INVOICE_STATUS_TONE: Record<string, string> = {
  draft: "bg-white/10 text-white/70 border-white/20",
  sent: "bg-blue-500/15 text-blue-300 border-blue-500/30",
  paid: "bg-emerald-500/15 text-emerald-300 border-emerald-500/30",
  overdue: "bg-rose-500/15 text-rose-300 border-rose-500/30",
  void: "bg-white/5 text-white/40 border-white/10"
};

function InvoiceRow({ inv }: { inv: InvoiceLine }) {
  const tone = INVOICE_STATUS_TONE[inv.status] || INVOICE_STATUS_TONE.draft;
  const label = INVOICE_STATUS_LABEL[inv.status] || inv.status;
  const balance = Math.max(0, inv.total - inv.paid_amount);
  const issued = inv.issued_at
    ? new Date(inv.issued_at).toLocaleDateString("fr-CA", {
        day: "2-digit",
        month: "short",
        year: "numeric"
      })
    : null;
  return (
    <li>
      <Link
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        href={`/app/facturation/${inv.id}` as any}
        className="flex items-center justify-between gap-2 rounded-lg border border-brand-800 bg-brand-950/50 px-3 py-2 text-xs hover:border-accent-500/40 hover:bg-brand-950"
      >
        <span className="flex min-w-0 items-center gap-2">
          <span
            className={`inline-flex flex-shrink-0 items-center rounded-md border px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider ${tone}`}
          >
            {label}
          </span>
          <span className="truncate font-mono text-white/90">
            {inv.reference}
          </span>
          {issued ? (
            <span className="hidden flex-shrink-0 text-[10px] text-white/40 sm:inline">
              · {issued}
            </span>
          ) : null}
        </span>
        <span className="flex flex-shrink-0 items-center gap-3">
          <span className="text-right">
            <span className="block font-semibold text-white">
              {fmtMoney(inv.total)}
            </span>
            {balance > 0 ? (
              <span className="block text-[10px] text-rose-300">
                Solde {fmtMoney(balance)}
              </span>
            ) : (
              <span className="block text-[10px] text-emerald-300">
                Reçu intégral
              </span>
            )}
          </span>
        </span>
      </Link>
    </li>
  );
}

type CorrectionItem = {
  id: number;
  title: string;
  details: string | null;
  status: string;
};

const CORRECTION_STATUS: { id: string; label: string }[] = [
  { id: "a_planifier", label: "À planifier" },
  { id: "planifie", label: "Planifié" },
  { id: "termine", label: "Terminé" }
];

function ProjectCorrections({
  projectId,
  correctionStatus,
  awaitingSignature,
  hasSignedBon,
  onChanged
}: {
  projectId: number;
  correctionStatus: string;
  awaitingSignature: boolean;
  hasSignedBon: boolean;
  onChanged: () => void;
}) {
  const [items, setItems] = useState<CorrectionItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [newTitle, setNewTitle] = useState("");
  const [newDetails, setNewDetails] = useState("");
  const [adding, setAdding] = useState(false);
  const [statusVal, setStatusVal] = useState(correctionStatus);
  const [err, setErr] = useState<string | null>(null);

  async function saveStatus(next: string) {
    setStatusVal(next);
    try {
      await authedFetch(`/api/v1/projects/${projectId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ correction_status: next })
      });
      onChanged();
    } catch {
      setErr("Changement de statut échoué.");
    }
  }

  async function load() {
    try {
      const r = await authedFetch(
        `/api/v1/projects/${projectId}/corrections`
      );
      if (r.ok) setItems((await r.json()) as CorrectionItem[]);
    } catch {
      /* ignore */
    } finally {
      setLoading(false);
    }
  }
  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId]);

  async function add() {
    if (!newTitle.trim()) return;
    setAdding(true);
    setErr(null);
    try {
      const r = await authedFetch(
        `/api/v1/projects/${projectId}/corrections`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            title: newTitle.trim(),
            details: newDetails.trim() || null
          })
        }
      );
      if (!r.ok) throw new Error();
      const c = (await r.json()) as CorrectionItem;
      setItems((x) => [...x, c]);
      setNewTitle("");
      setNewDetails("");
      onChanged();
    } catch {
      setErr("Ajout de la correction échoué.");
    } finally {
      setAdding(false);
    }
  }

  async function toggle(c: CorrectionItem) {
    const next = c.status === "complete" ? "a_faire" : "complete";
    setItems((x) =>
      x.map((i) => (i.id === c.id ? { ...i, status: next } : i))
    );
    try {
      await authedFetch(
        `/api/v1/projects/${projectId}/corrections/${c.id}`,
        {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ status: next })
        }
      );
      onChanged();
    } catch {
      void load();
    }
  }

  async function remove(itemId: number) {
    setItems((x) => x.filter((i) => i.id !== itemId));
    try {
      await authedFetch(
        `/api/v1/projects/${projectId}/corrections/${itemId}`,
        { method: "DELETE" }
      );
      onChanged();
    } catch {
      void load();
    }
  }

  const todo = items.filter((i) => i.status !== "complete").length;

  return (
    <section className="mt-6 space-y-4 rounded-2xl border border-rose-500/20 bg-rose-500/[0.03] p-5">
      {/* En-tête + statut segmenté */}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="flex flex-wrap items-center gap-2 text-base font-bold text-white">
            <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-rose-500/15 text-rose-300">
              <Hammer className="h-4 w-4" />
            </span>
            Corrections / améliorations
            {hasSignedBon ? (
              <span className="inline-flex items-center gap-1 rounded-full bg-emerald-500/15 px-2 py-0.5 text-[10px] font-semibold text-emerald-300">
                <CheckCircle2 className="h-3 w-3" /> Signé
              </span>
            ) : awaitingSignature ? (
              <span className="inline-flex items-center gap-1 rounded-full bg-rose-500/20 px-2 py-0.5 text-[10px] font-semibold text-rose-300">
                <Circle className="h-3 w-3" /> À signer
              </span>
            ) : null}
          </h2>
          <p className="mt-1 max-w-lg text-xs text-white/50">
            {todo} point{todo > 1 ? "s" : ""} à reprendre. Les coûts du retour
            s&apos;accumulent sur ce projet.
          </p>
        </div>
        <div className="flex flex-col items-start gap-1 sm:items-end">
          <span className="text-[10px] font-semibold uppercase tracking-wider text-white/40">
            Statut
          </span>
          <div className="inline-flex gap-1 rounded-lg bg-brand-950 p-1">
            {CORRECTION_STATUS.map((s) => {
              const active = statusVal === s.id;
              return (
                <button
                  key={s.id}
                  type="button"
                  onClick={() => void saveStatus(s.id)}
                  className={`rounded-md px-3 py-1 text-xs font-semibold transition ${
                    active
                      ? s.id === "termine"
                        ? "bg-emerald-500 text-white"
                        : s.id === "planifie"
                          ? "bg-sky-500 text-white"
                          : "bg-amber-500 text-brand-950"
                      : "text-white/50 hover:text-white"
                  }`}
                >
                  {s.label}
                </button>
              );
            })}
          </div>
        </div>
      </div>

      {/* Carte 1 — points à reprendre (checklist) */}
      <div className="rounded-xl border border-brand-800 bg-brand-950/60 p-4">
        <h3 className="mb-3 text-[11px] font-semibold uppercase tracking-wider text-white/40">
          Points à reprendre
        </h3>
        <div className="space-y-2">
          {loading ? (
            <Loader2 className="h-5 w-5 animate-spin text-rose-300" />
          ) : items.length === 0 ? (
            <p className="rounded-lg border border-dashed border-brand-800 py-6 text-center text-sm text-white/40">
              Aucun point pour l&apos;instant. Ajoute-les ci-dessous.
            </p>
          ) : (
            items.map((c) => (
              <div
                key={c.id}
                className="flex items-start gap-3 rounded-lg border border-brand-800 bg-brand-900 p-3"
              >
                <button
                  type="button"
                  onClick={() => void toggle(c)}
                  className="mt-0.5 flex-shrink-0"
                  aria-label="Basculer le statut"
                >
                  {c.status === "complete" ? (
                    <CheckCircle2 className="h-5 w-5 text-emerald-400" />
                  ) : (
                    <Circle className="h-5 w-5 text-white/40" />
                  )}
                </button>
                <div className="min-w-0 flex-1">
                  <p
                    className={`text-sm font-medium ${
                      c.status === "complete"
                        ? "text-white/40 line-through"
                        : "text-white"
                    }`}
                  >
                    {c.title}
                  </p>
                  {c.details ? (
                    <p className="mt-0.5 whitespace-pre-wrap text-xs text-white/50">
                      {c.details}
                    </p>
                  ) : null}
                </div>
                <span
                  className={`flex-shrink-0 rounded-md px-1.5 py-0.5 text-[10px] font-semibold ${
                    c.status === "complete"
                      ? "bg-emerald-500/15 text-emerald-300"
                      : "bg-amber-500/15 text-amber-300"
                  }`}
                >
                  {c.status === "complete" ? "Complété" : "À faire"}
                </span>
                <button
                  type="button"
                  onClick={() => void remove(c.id)}
                  className="flex-shrink-0 text-rose-400 hover:text-rose-300"
                  aria-label="Supprimer"
                >
                  <Trash2 className="h-4 w-4" />
                </button>
              </div>
            ))
          )}
        </div>

        <div className="mt-3 space-y-2 rounded-lg border border-brand-800 bg-brand-900/60 p-3">
          <input
            value={newTitle}
            onChange={(e) => setNewTitle(e.target.value)}
            placeholder="Titre de la correction à faire…"
            className="input w-full text-sm"
          />
          <textarea
            value={newDetails}
            onChange={(e) => setNewDetails(e.target.value)}
            rows={2}
            placeholder="Détails (optionnel)…"
            className="input w-full text-sm"
          />
          <button
            type="button"
            onClick={() => void add()}
            disabled={adding || !newTitle.trim()}
            className="btn-accent text-xs"
          >
            {adding ? (
              <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
            ) : (
              <Plus className="mr-1.5 h-3.5 w-3.5" />
            )}
            Ajouter
          </button>
        </div>
        {err ? <p className="mt-2 text-xs text-rose-400">{err}</p> : null}
      </div>

      {/* Carte 2 — bon de correction signable (plus de redirection). */}
      <CorrectionBonPanel
        projectId={projectId}
        corrections={items}
        onChanged={onChanged}
      />

      {/* Carte 3 — photos du projet (avant/après correction). */}
      <div className="rounded-xl border border-brand-800 bg-brand-950/60 p-4">
        <h3 className="mb-3 text-[11px] font-semibold uppercase tracking-wider text-white/40">
          Photos
        </h3>
        <PhotosTab projectId={projectId} />
      </div>
    </section>
  );
}

// #4 — Panneau du bon de correction embarqué dans l'onglet Corrections :
// création/reprise du bon, lignes, aperçu PDF, envoi pour signature et
// récap du montant chargé au client. Remplace la redirection vers la
// fiche générique /app/bons/[id].
type BonLite = {
  id: number;
  reference: string;
  status: string;
  amount: number | string | null;
  sent_at: string | null;
  signed_at: string | null;
  signed_by_name: string | null;
};
type BonItemLite = {
  id: number;
  position: number;
  description: string;
  unit: string | null;
  quantity: number | string;
  unit_price: number | string;
  total: number | string;
};
type BonRecapLite = {
  total: number;
  labor_total: number;
  achats_total: number;
  fixed_amount: number | null;
};

function corMoney(n: number | string | null | undefined): string {
  if (n == null || n === "") return "0,00 $";
  const v = typeof n === "string" ? Number(n) : n;
  if (!Number.isFinite(v)) return "0,00 $";
  return `${v.toLocaleString("fr-CA", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2
  })} $`;
}

function CorrectionBonPanel({
  projectId,
  corrections,
  onChanged
}: {
  projectId: number;
  corrections: CorrectionItem[];
  onChanged: () => void;
}) {
  const [bonId, setBonId] = useState<number | null>(null);
  const [bon, setBon] = useState<BonLite | null>(null);
  const [bonItems, setBonItems] = useState<BonItemLite[]>([]);
  const [recap, setRecap] = useState<BonRecapLite | null>(null);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [itemBusy, setItemBusy] = useState<number | "new" | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [sendOpen, setSendOpen] = useState(false);
  const [sendTo, setSendTo] = useState("");
  const [sendBusy, setSendBusy] = useState(false);
  const [sendNotice, setSendNotice] = useState<string | null>(null);

  async function loadBon(id: number) {
    try {
      const [bRes, iRes, rRes] = await Promise.all([
        authedFetch(`/api/v1/bons-travail/${id}`),
        authedFetch(`/api/v1/bons-travail/${id}/items`),
        authedFetch(`/api/v1/bons-travail/${id}/recap`)
      ]);
      if (bRes.ok) setBon((await bRes.json()) as BonLite);
      if (iRes.ok) setBonItems((await iRes.json()) as BonItemLite[]);
      if (rRes.ok) setRecap((await rRes.json()) as BonRecapLite);
    } catch {
      /* ignore */
    }
  }

  useEffect(() => {
    let cancelled = false;
    async function init() {
      setLoading(true);
      try {
        const r = await authedFetch(
          `/api/v1/projects/${projectId}/correction-bon`
        );
        if (r.ok) {
          const d = (await r.json()) as { bon_id: number | null };
          if (!cancelled && d.bon_id) {
            setBonId(d.bon_id);
            await loadBon(d.bon_id);
          }
        }
        // Pré-remplit le courriel d'envoi depuis le client du projet.
        const pr = await authedFetch(`/api/v1/projects/${projectId}`);
        if (pr.ok) {
          const proj = (await pr.json()) as { client_id?: number | null };
          if (proj.client_id) {
            const cr = await authedFetch(`/api/v1/clients/${proj.client_id}`);
            if (cr.ok) {
              const c = (await cr.json()) as { email?: string | null };
              if (c.email && !cancelled) setSendTo(c.email);
            }
          }
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    void init();
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  async function refreshRecap(id: number) {
    try {
      const r = await authedFetch(`/api/v1/bons-travail/${id}/recap`);
      if (r.ok) setRecap((await r.json()) as BonRecapLite);
    } catch {
      /* ignore */
    }
  }

  async function createBon() {
    setCreating(true);
    setErr(null);
    try {
      const r = await authedFetch(
        `/api/v1/projects/${projectId}/correction-bon`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: "{}"
        }
      );
      if (!r.ok) throw new Error();
      const { bon_id } = (await r.json()) as { bon_id: number };
      setBonId(bon_id);
      await loadBon(bon_id);
      onChanged();
    } catch {
      setErr("Création du bon de correction échouée.");
    } finally {
      setCreating(false);
    }
  }

  async function addItem() {
    if (!bonId) return;
    setItemBusy("new");
    try {
      const r = await authedFetch(`/api/v1/bons-travail/${bonId}/items`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          position: bonItems.length,
          description: "Nouvel item",
          unit: "unité",
          quantity: 1,
          unit_price: 0
        })
      });
      if (!r.ok) throw new Error();
      const created = (await r.json()) as BonItemLite;
      setBonItems((xs) => [...xs, created]);
      void refreshRecap(bonId);
    } catch {
      setErr("Ajout d'item échoué.");
    } finally {
      setItemBusy(null);
    }
  }

  // Ajoute une ligne par point de correction pas encore présent dans le
  // bon (comparaison sur le titre). Sert quand des points ont été ajoutés
  // après la création du bon (à la création, le back-end les sème déjà).
  async function importCorrections() {
    if (!bonId) return;
    const existing = new Set(
      bonItems.map((it) => it.description.split(" — ")[0].trim())
    );
    const missing = corrections.filter((c) => !existing.has(c.title.trim()));
    if (missing.length === 0) {
      setErr("Tous les points sont déjà dans le bon.");
      return;
    }
    setItemBusy("new");
    try {
      const created: BonItemLite[] = [];
      let pos = bonItems.length;
      for (const c of missing) {
        const desc = c.details ? `${c.title} — ${c.details}` : c.title;
        const r = await authedFetch(`/api/v1/bons-travail/${bonId}/items`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            position: pos++,
            description: desc.slice(0, 500),
            unit: "unité",
            quantity: 1,
            unit_price: 0
          })
        });
        if (r.ok) created.push((await r.json()) as BonItemLite);
      }
      setBonItems((xs) => [...xs, ...created]);
      void refreshRecap(bonId);
    } catch {
      setErr("Import des points échoué.");
    } finally {
      setItemBusy(null);
    }
  }

  async function patchItem(itemId: number, patch: Partial<BonItemLite>) {
    if (!bonId) return;
    setItemBusy(itemId);
    try {
      const r = await authedFetch(
        `/api/v1/bons-travail/${bonId}/items/${itemId}`,
        {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(patch)
        }
      );
      if (!r.ok) throw new Error();
      const u = (await r.json()) as BonItemLite;
      setBonItems((xs) => xs.map((x) => (x.id === itemId ? u : x)));
      void refreshRecap(bonId);
    } catch {
      setErr("Mise à jour échouée.");
    } finally {
      setItemBusy(null);
    }
  }

  async function deleteItem(itemId: number) {
    if (!bonId) return;
    setItemBusy(itemId);
    try {
      const r = await authedFetch(
        `/api/v1/bons-travail/${bonId}/items/${itemId}`,
        { method: "DELETE" }
      );
      if (!r.ok && r.status !== 204) throw new Error();
      setBonItems((xs) => xs.filter((x) => x.id !== itemId));
      void refreshRecap(bonId);
    } catch {
      setErr("Suppression échouée.");
    } finally {
      setItemBusy(null);
    }
  }

  async function previewPdf() {
    if (!bonId) return;
    try {
      const r = await authedFetch(`/api/v1/bons-travail/${bonId}/pdf`);
      if (!r.ok) throw new Error();
      const blob = await r.blob();
      const url = URL.createObjectURL(blob);
      window.open(url, "_blank", "noopener,noreferrer");
      setTimeout(() => URL.revokeObjectURL(url), 60_000);
    } catch {
      setErr("Aperçu PDF échoué.");
    }
  }

  async function send() {
    if (!bonId) return;
    const to = sendTo
      .split(",")
      .map((x) => x.trim())
      .filter(Boolean);
    if (to.length === 0) {
      setSendNotice("Adresse courriel requise.");
      return;
    }
    setSendBusy(true);
    setSendNotice(null);
    try {
      const r = await authedFetch(`/api/v1/bons-travail/${bonId}/send`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ to, subject: null, message: null })
      });
      if (!r.ok) throw new Error((await r.text()).slice(0, 200));
      setBon((await r.json()) as BonLite);
      setSendOpen(false);
      setSendNotice(`Envoyé à ${to.join(", ")}.`);
      onChanged();
    } catch (e) {
      setSendNotice(`Erreur : ${(e as Error).message}`);
    } finally {
      setSendBusy(false);
    }
  }

  if (loading) {
    return (
      <div className="mt-5 flex items-center gap-2 border-t border-rose-500/20 pt-4 text-xs text-white/40">
        <Loader2 className="h-4 w-4 animate-spin" /> Chargement du bon de
        correction…
      </div>
    );
  }

  if (!bonId || !bon) {
    return (
      <div className="rounded-xl border border-brand-800 bg-brand-950/60 p-4">
        <h3 className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-white/40">
          Bon de correction à signer
        </h3>
        <p className="mb-3 text-xs text-white/50">
          Génère le bon signable pour le client. Tes points de correction
          seront repris automatiquement comme lignes (montants à ajuster).
        </p>
        <button
          type="button"
          onClick={() => void createBon()}
          disabled={creating}
          className="inline-flex items-center gap-1.5 rounded-lg bg-rose-500 px-3 py-2 text-sm font-semibold text-white hover:bg-rose-400 disabled:opacity-50"
        >
          {creating ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Hammer className="h-4 w-4" />
          )}
          Préparer le bon de correction
        </button>
        {err ? <p className="mt-2 text-xs text-rose-400">{err}</p> : null}
      </div>
    );
  }

  const signed = !!bon.signed_at;
  const sent = !signed && !!bon.sent_at;

  return (
    <div className="rounded-xl border border-brand-800 bg-brand-950/60 p-4">
      <h3 className="mb-3 text-[11px] font-semibold uppercase tracking-wider text-white/40">
        Bon de correction à signer
      </h3>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="flex flex-wrap items-center gap-2 text-sm font-semibold text-white">
            <Hammer className="h-4 w-4 text-rose-300" /> Bon
            <span className="font-mono text-xs text-white/50">
              {bon.reference}
            </span>
            {signed ? (
              <span className="inline-flex items-center gap-1 rounded-full bg-emerald-500/15 px-2 py-0.5 text-[10px] font-semibold text-emerald-300">
                <CheckCircle2 className="h-3 w-3" /> Signé
                {bon.signed_by_name ? ` — ${bon.signed_by_name}` : ""}
              </span>
            ) : sent ? (
              <span className="inline-flex items-center gap-1 rounded-full bg-rose-500/20 px-2 py-0.5 text-[10px] font-semibold text-rose-300">
                <Circle className="h-3 w-3" /> À signer
              </span>
            ) : (
              <span className="inline-flex items-center gap-1 rounded-full bg-white/10 px-2 py-0.5 text-[10px] font-semibold text-white/60">
                Brouillon
              </span>
            )}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={() => void previewPdf()}
            className="inline-flex items-center gap-1.5 rounded-lg border border-brand-700 bg-brand-900 px-3 py-2 text-xs font-semibold text-white/80 hover:border-accent-500"
          >
            <FileText className="h-4 w-4" /> Prévisualiser le PDF
          </button>
          {!signed ? (
            <button
              type="button"
              onClick={() => {
                setSendNotice(null);
                setSendOpen(true);
              }}
              className="inline-flex items-center gap-1.5 rounded-lg bg-rose-500 px-3 py-2 text-xs font-semibold text-white hover:bg-rose-400"
            >
              <Mail className="h-4 w-4" /> Envoyer pour signature
            </button>
          ) : null}
        </div>
      </div>

      {sendOpen ? (
        <div className="mt-3 rounded-lg border border-brand-800 bg-brand-900 p-3">
          <label className="text-[11px] font-semibold uppercase tracking-wider text-white/40">
            Courriel du client
          </label>
          <input
            value={sendTo}
            onChange={(e) => setSendTo(e.target.value)}
            placeholder="client@exemple.com"
            className="input mt-1 w-full text-sm"
          />
          <div className="mt-2 flex items-center gap-2">
            <button
              type="button"
              onClick={() => void send()}
              disabled={sendBusy}
              className="inline-flex items-center gap-1.5 rounded-lg bg-rose-500 px-3 py-1.5 text-xs font-semibold text-white hover:bg-rose-400 disabled:opacity-50"
            >
              {sendBusy ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Mail className="h-3.5 w-3.5" />
              )}
              Envoyer (PDF + lien signature)
            </button>
            <button
              type="button"
              onClick={() => setSendOpen(false)}
              className="text-xs text-white/50 hover:text-white"
            >
              Annuler
            </button>
          </div>
        </div>
      ) : null}
      {sendNotice ? (
        <p className="mt-2 text-xs text-white/60">{sendNotice}</p>
      ) : null}

      {/* Lignes du bon */}
      <div className="mt-4 space-y-2">
        {bonItems.length === 0 ? (
          <p className="text-xs text-white/40">
            Aucune ligne — ajoute ce qui est chargé au client pour la
            correction.
          </p>
        ) : (
          bonItems.map((it) => (
            <div
              key={it.id}
              className="flex flex-wrap items-center gap-2 rounded-lg border border-brand-800 bg-brand-900 p-2"
            >
              <input
                defaultValue={it.description}
                onBlur={(e) => {
                  if (e.target.value !== it.description)
                    void patchItem(it.id, { description: e.target.value });
                }}
                className="input min-w-[8rem] flex-1 text-sm"
              />
              <input
                type="number"
                step="0.01"
                defaultValue={String(it.quantity)}
                onBlur={(e) => {
                  const v = Number(e.target.value);
                  if (Number.isFinite(v) && v !== Number(it.quantity))
                    void patchItem(it.id, { quantity: v });
                }}
                className="input w-16 text-sm"
                title="Quantité"
              />
              <span className="text-white/30">×</span>
              <input
                type="number"
                step="0.01"
                defaultValue={String(it.unit_price)}
                onBlur={(e) => {
                  const v = Number(e.target.value);
                  if (Number.isFinite(v) && v !== Number(it.unit_price))
                    void patchItem(it.id, { unit_price: v });
                }}
                className="input w-24 text-sm"
                title="Prix unitaire"
              />
              <span className="w-24 text-right text-sm font-semibold text-white">
                {corMoney(it.total)}
              </span>
              <button
                type="button"
                onClick={() => void deleteItem(it.id)}
                disabled={itemBusy === it.id}
                className="text-rose-400 hover:text-rose-300 disabled:opacity-40"
                aria-label="Supprimer la ligne"
              >
                <Trash2 className="h-4 w-4" />
              </button>
            </div>
          ))
        )}
      </div>

      <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={() => void addItem()}
            disabled={itemBusy === "new"}
            className="inline-flex items-center gap-1.5 rounded-lg border border-brand-700 bg-brand-900 px-3 py-1.5 text-xs font-semibold text-white/80 hover:border-accent-500 disabled:opacity-50"
          >
            {itemBusy === "new" ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Plus className="h-3.5 w-3.5" />
            )}
            Ajouter un item
          </button>
          {corrections.length > 0 ? (
            <button
              type="button"
              onClick={() => void importCorrections()}
              disabled={itemBusy === "new"}
              className="inline-flex items-center gap-1.5 rounded-lg border border-brand-700 bg-brand-900 px-3 py-1.5 text-xs font-semibold text-white/80 hover:border-accent-500 disabled:opacity-50"
            >
              <Hammer className="h-3.5 w-3.5" /> Reprendre les points
            </button>
          ) : null}
        </div>
        <p className="text-sm">
          <span className="text-white/50">Total chargé au client : </span>
          <span className="font-bold text-emerald-300">
            {corMoney(recap ? recap.total : bon.amount)}
          </span>
        </p>
      </div>

      {err ? <p className="mt-2 text-xs text-rose-400">{err}</p> : null}
    </div>
  );
}
