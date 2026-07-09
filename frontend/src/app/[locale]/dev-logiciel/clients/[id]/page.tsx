"use client";

/**
 * Fiche client — Developpement logiciel.
 *
 * Vague "fiche client mature" (mai 2026) : la page est differente de la
 * fiche prospect (qui reste un funnel commercial). Ici on materialise
 * un *compte client* :
 *
 *   - Header : nom + badge "Client depuis ..." + bouton "Nouvelle
 *     soumission" / "Nouveau projet".
 *   - 5 KPI cards (projets actifs, MRR recurrent TTC/mois, facture a
 *     vie, encaisse a vie, en cours).
 *   - Cards "Projets en cours" (gros visuels par projet).
 *   - Tableau "Factures recentes" (10 dernieres, badge statut).
 *   - Tableau "Contrats" (signes/envoyes/brouillons).
 *   - Section repliable "Soumissions (historique commercial)".
 *   - Section repliable "Notes & contacts" (editable).
 *   - Section repliable "Historique prospect" (qualification d'origine
 *     si source_lead non null).
 *
 * L'endpoint backend GET /devlog/clients/{id}/full-history renvoie un
 * payload unifie qui contient toutes ces donnees + un bloc ``kpis``
 * calcule cote serveur (MRR via compute_devis, totaux TTC via
 * compute_invoice_totals).
 */

import { useEffect, useMemo, useState } from "react";
import { useParams, useRouter as useNextRouter } from "next/navigation";
import {
  ArrowLeft,
  BadgeDollarSign,
  Briefcase,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  ExternalLink,
  FilePlus2,
  FileText,
  Hourglass,
  Loader2,
  Receipt,
  Repeat,
  Save,
  Trash2
} from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { AddressInput } from "@/components/address-input";
import { EntityDriveSection } from "@/components/drive/EntityDriveSection";
import { Link } from "@/i18n/navigation";
import { useDevlogLayout } from "../../layout";
import { authedFetch } from "@/lib/auth";
import { useConfirm } from "@/components/confirm-dialog";

// ---------------------------------------------------------------------------
// Types miroirs des schemas backend (DevlogClientRead, _ClientFullHistory,
// _ClientKpis, DevlogProjectRead, DevlogInvoiceRead, DevlogContractRead,
// DevlogSoumissionRead, DevlogLeadRead).
// ---------------------------------------------------------------------------

type Client = {
  id: number;
  name: string;
  company: string | null;
  email: string | null;
  phone: string | null;
  address: string | null;
  website: string | null;
  status: string;
  notes: string | null;
  converted_from_lead_id: number | null;
  converted_at: string | null;
  created_at: string;
  updated_at: string;
};

type Kpis = {
  active_projects_count: number;
  total_invoiced_lifetime_cents: number;
  total_paid_lifetime_cents: number;
  outstanding_cents: number;
  mrr_recurring_cents: number;
};

type Project = {
  id: number;
  name: string;
  client_id: number | null;
  soumission_id: number | null;
  description: string | null;
  status: string;
  start_date: string | null;
  due_date: string | null;
  started_at: string | null;
  created_at: string;
  updated_at: string;
};

type Invoice = {
  id: number;
  number: string | null;
  client_id: number | null;
  project_id: number | null;
  amount: number | null;
  status: string;
  issued_date: string | null;
  due_date: string | null;
  notes: string | null;
  signature_token: string | null;
  sent_at: string | null;
  paid_at: string | null;
  payment_method: string | null;
  created_at: string;
  updated_at: string;
};

type Contract = {
  id: number;
  soumission_id: number | null;
  client_id: number | null;
  project_id: number | null;
  title: string;
  status: string;
  signed_at: string | null;
  signed_name: string | null;
  sent_at: string | null;
  created_at: string;
};

type Soumission = {
  id: number;
  title: string;
  lead_id: number | null;
  client_id: number | null;
  amount: number | null;
  status: string;
  is_devis_dev: boolean;
  signed_at: string | null;
  sent_at: string | null;
  created_at: string;
  updated_at: string;
};

type SourceLead = {
  id: number;
  name: string;
  email: string | null;
  project_type: string;
  source: string | null;
  status: string;
  project_summary: string | null;
  budget_range: string | null;
  notes: string | null;
  meeting_notes: string | null;
  created_at: string;
};

type FullHistory = {
  client: Client;
  source_lead: SourceLead | null;
  kpis: Kpis;
  soumissions: Soumission[];
  projects: Project[];
  contracts: Contract[];
  invoices: Invoice[];
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function fmtMoneyCents(cents: number, opts?: { withCents?: boolean }): string {
  const v = (cents || 0) / 100;
  return new Intl.NumberFormat("fr-CA", {
    style: "currency",
    currency: "CAD",
    minimumFractionDigits: opts?.withCents ? 2 : 0,
    maximumFractionDigits: opts?.withCents ? 2 : 0
  }).format(v);
}

function fmtMoney(amount: number | null | undefined): string {
  const v = Number(amount || 0);
  return new Intl.NumberFormat("fr-CA", {
    style: "currency",
    currency: "CAD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2
  }).format(v);
}

function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleDateString("fr-CA", {
      day: "numeric",
      month: "long",
      year: "numeric"
    });
  } catch {
    return "—";
  }
}

function fmtDateShort(iso: string | null | undefined): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleDateString("fr-CA");
  } catch {
    return "—";
  }
}

const PROJECT_STATUS_LABELS: Record<string, string> = {
  planifie: "Planifié",
  en_attente: "En attente",
  en_cours: "En cours",
  suspendu: "Suspendu",
  livre: "Livré"
};

const PROJECT_STATUS_TONE: Record<string, string> = {
  planifie: "bg-white/10 text-white/70",
  en_attente: "bg-amber-500/15 text-amber-300",
  en_cours: "bg-blue-500/15 text-blue-300",
  suspendu: "bg-rose-500/15 text-rose-300",
  livre: "bg-emerald-500/15 text-emerald-300"
};

const INVOICE_STATUS_LABELS: Record<string, string> = {
  brouillon: "Brouillon",
  envoyee: "Envoyée",
  payee: "Payée",
  annulee: "Annulée"
};

const INVOICE_STATUS_TONE: Record<string, string> = {
  brouillon: "bg-white/10 text-white/70",
  envoyee: "bg-amber-500/15 text-amber-300",
  payee: "bg-emerald-500/15 text-emerald-300",
  annulee: "bg-rose-500/15 text-rose-300"
};

const CONTRACT_STATUS_LABELS: Record<string, string> = {
  brouillon: "Brouillon",
  envoye: "Envoyé",
  signe: "Signé",
  annule: "Annulé"
};

const CONTRACT_STATUS_TONE: Record<string, string> = {
  brouillon: "bg-white/10 text-white/70",
  envoye: "bg-amber-500/15 text-amber-300",
  signe: "bg-emerald-500/15 text-emerald-300",
  annule: "bg-rose-500/15 text-rose-300"
};

const SOUMISSION_STATUS_LABELS: Record<string, string> = {
  brouillon: "Brouillon",
  envoyee: "Envoyée",
  acceptee: "Acceptée",
  refusee: "Refusée",
  expiree: "Expirée"
};

const SOUMISSION_STATUS_TONE: Record<string, string> = {
  brouillon: "bg-white/10 text-white/70",
  envoyee: "bg-amber-500/15 text-amber-300",
  acceptee: "bg-emerald-500/15 text-emerald-300",
  refusee: "bg-rose-500/15 text-rose-300",
  expiree: "bg-white/5 text-white/40"
};

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function ClientDetailPage() {
  const confirm = useConfirm();
  const { onOpenSidebar } = useDevlogLayout();
  const params = useParams<{ id: string }>();
  const id = Number(params.id);
  const router = useNextRouter();

  const [data, setData] = useState<FullHistory | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const res = await authedFetch(
          `/api/v1/devlog/clients/${id}/full-history`
        );
        if (!res.ok) throw new Error(`http_${res.status}`);
        const payload = (await res.json()) as FullHistory;
        if (!cancelled) setData(payload);
      } catch {
        if (!cancelled) setError("Client introuvable.");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    if (id) void load();
    return () => {
      cancelled = true;
    };
  }, [id]);

  async function onDelete() {
    if (!data) return;
    if (
      !(await confirm(
        `Supprimer définitivement « ${data.client.name} » et toutes les entités liées (soumissions / projets / factures) ?`
      ))
    )
      return;
    setDeleting(true);
    try {
      const res = await authedFetch(`/api/v1/devlog/clients/${id}`, {
        method: "DELETE"
      });
      if (!res.ok) throw new Error();
      router.replace("/dev-logiciel/clients");
    } catch {
      setDeleting(false);
      setError("Suppression échouée.");
    }
  }

  function patchClient(updated: Client) {
    setData((prev) => (prev ? { ...prev, client: updated } : prev));
  }

  return (
    <>
      <AppTopbar
        breadcrumbs={[
          { label: "Développement logiciel", href: "/dev-logiciel" as any },
          { label: "Clients" }
        ]}
        onOpenSidebar={onOpenSidebar}
      />

      <div className="p-4 lg:p-6">
        <Link
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          href={"/dev-logiciel/clients" as any}
          className="inline-flex items-center text-sm text-white/70 hover:text-accent-500"
        >
          <ArrowLeft className="mr-1 h-4 w-4" /> Retour aux clients
        </Link>

        {loading ? (
          <div className="flex min-h-[40vh] items-center justify-center">
            <Loader2 className="h-6 w-6 animate-spin text-accent-500" />
          </div>
        ) : error && !data ? (
          <p className="mt-6 rounded-lg border border-rose-500/40 bg-rose-500/10 px-4 py-2 text-sm text-rose-300">
            {error}
          </p>
        ) : data ? (
          <ClientAccount
            data={data}
            onPatchClient={patchClient}
            onDelete={onDelete}
            deleting={deleting}
          />
        ) : null}
      </div>
    </>
  );
}

// ---------------------------------------------------------------------------
// ClientAccount — vue compte client complete (header + KPIs + sections)
// ---------------------------------------------------------------------------

function ClientAccount({
  data,
  onPatchClient,
  onDelete,
  deleting
}: {
  data: FullHistory;
  onPatchClient: (c: Client) => void;
  onDelete: () => void;
  deleting: boolean;
}) {
  const { client, kpis, source_lead, projects, invoices, contracts, soumissions } = data;

  const clientSince = useMemo(() => {
    // Si converti, on prend la date de conversion (qui est ce qui
    // compte commercialement). Sinon, created_at.
    if (client.converted_at) return client.converted_at;
    return client.created_at;
  }, [client]);

  const activeProjects = useMemo(
    () => projects.filter((p) => p.status === "en_cours" || p.status === "livre"),
    [projects]
  );
  const otherProjects = useMemo(
    () => projects.filter((p) => p.status !== "en_cours" && p.status !== "livre"),
    [projects]
  );
  const recentInvoices = invoices.slice(0, 10);
  const allInvoicesCount = invoices.length;

  return (
    <>
      {/* ------------------------- Header ------------------------- */}
      <header className="mt-6 flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-3">
            <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-accent-500/15 text-lg font-semibold text-accent-500">
              {(client.name || "?").slice(0, 2).toUpperCase()}
            </div>
            <div className="min-w-0">
              <h1 className="truncate text-2xl font-bold text-white">
                {client.name}
              </h1>
              <p className="mt-0.5 text-xs text-white/60">
                <span className="inline-flex items-center gap-1 rounded-full bg-emerald-500/15 px-2 py-0.5 font-medium text-emerald-300">
                  <CheckCircle2 className="h-3 w-3" /> Client depuis le {fmtDate(clientSince)}
                </span>
                {client.status === "archived" ? (
                  <span className="ml-2 rounded-full bg-white/10 px-2 py-0.5 text-white/60">
                    Archivé
                  </span>
                ) : null}
              </p>
            </div>
          </div>

          <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-white/70">
            {client.company ? <span>{client.company}</span> : null}
            {client.email ? (
              <a
                href={`mailto:${client.email}`}
                className="text-white/70 hover:text-accent-500"
              >
                {client.email}
              </a>
            ) : null}
            {client.phone ? (
              <a
                href={`tel:${client.phone}`}
                className="text-white/70 hover:text-accent-500"
              >
                {client.phone}
              </a>
            ) : null}
            {client.address ? (
              <span className="text-white/60">{client.address}</span>
            ) : null}
            {client.website ? (
              <a
                href={client.website}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-1 text-white/70 hover:text-accent-500"
              >
                {client.website} <ExternalLink className="h-3 w-3" />
              </a>
            ) : null}
          </div>
        </div>

        <div className="flex flex-wrap items-start gap-2">
          <Link
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            href={`/dev-logiciel/soumissions/new?client_id=${client.id}` as any}
            className="btn-accent btn-sm self-start"
          >
            <FilePlus2 className="h-4 w-4" />
            Nouvelle soumission
          </Link>
          <Link
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            href={`/dev-logiciel/projets/new?client_id=${client.id}` as any}
            className="btn-outline-accent btn-sm self-start"
          >
            <Briefcase className="h-4 w-4" />
            Nouveau projet
          </Link>
          <button
            type="button"
            onClick={onDelete}
            disabled={deleting}
            className="btn-outline-rose btn-sm self-start"
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

      {/* ------------------------- Documents Drive (en haut, sous le header) ------------------------- */}
      {client?.id ? (
        <EntityDriveSection
          entityType="DevlogClient"
          entityId={client.id}
          pole="Développement logiciel"
          label="Client"
          route="/dev-logiciel/clients/[id]"
        />
      ) : null}

      {/* ------------------------- KPI cards ------------------------- */}
      <section className="mt-6 grid grid-cols-2 gap-3 lg:grid-cols-5">
        <KpiCard
          icon={<Briefcase className="h-4 w-4" />}
          label="Projets actifs"
          value={String(kpis.active_projects_count)}
          tone="neutral"
        />
        <KpiCard
          icon={<Repeat className="h-4 w-4" />}
          label="MRR récurrent"
          value={fmtMoneyCents(kpis.mrr_recurring_cents)}
          sub="TTC / mois"
          tone="emerald"
        />
        <KpiCard
          icon={<Receipt className="h-4 w-4" />}
          label="Facturé à vie"
          value={fmtMoneyCents(kpis.total_invoiced_lifetime_cents)}
          sub="TTC cumulé"
          tone="neutral"
        />
        <KpiCard
          icon={<BadgeDollarSign className="h-4 w-4" />}
          label="Encaissé à vie"
          value={fmtMoneyCents(kpis.total_paid_lifetime_cents)}
          tone="emerald"
        />
        <KpiCard
          icon={<Hourglass className="h-4 w-4" />}
          label="En cours"
          value={fmtMoneyCents(kpis.outstanding_cents)}
          sub="Reste à payer"
          tone={kpis.outstanding_cents > 0 ? "amber" : "neutral"}
        />
      </section>

      {/* ------------------------- Projets en cours ------------------------- */}
      <section className="mt-8">
        <SectionHeader
          title="Projets en cours"
          count={activeProjects.length}
          hint="Projets « en cours » ou « livré »"
        />
        {activeProjects.length === 0 ? (
          <EmptyHint>
            Aucun projet actif. Demarre un nouveau projet ou attends qu&apos;un
            contrat soit signe pour qu&apos;un projet soit auto-provisionne.
          </EmptyHint>
        ) : (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {activeProjects.map((p) => (
              <ProjectCard key={p.id} project={p} />
            ))}
          </div>
        )}
      </section>

      {/* ------------------------- Factures recentes ------------------------- */}
      <section className="mt-8">
        <SectionHeader
          title="Factures récentes"
          count={recentInvoices.length}
          hint={
            allInvoicesCount > 10
              ? `Affichage des 10 dernières sur ${allInvoicesCount}`
              : undefined
          }
        />
        {recentInvoices.length === 0 ? (
          <EmptyHint>Aucune facture pour ce client.</EmptyHint>
        ) : (
          <InvoicesTable invoices={recentInvoices} />
        )}
        {allInvoicesCount > 10 ? (
          <div className="mt-2">
            <Link
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
              href={
                `/dev-logiciel/facturation?client_id=${client.id}` as any
              }
              className="text-xs text-accent-500 underline decoration-dotted hover:text-accent-400"
            >
              Voir toutes les factures
            </Link>
          </div>
        ) : null}
      </section>

      {/* ------------------------- Contrats ------------------------- */}
      <section className="mt-8">
        <SectionHeader title="Contrats" count={contracts.length} />
        {contracts.length === 0 ? (
          <EmptyHint>Aucun contrat pour ce client.</EmptyHint>
        ) : (
          <ContractsTable contracts={contracts} />
        )}
      </section>

      {/* ------------------------- Soumissions (collapsable) ------------------------- */}
      <section className="mt-8">
        <CollapsibleSection
          title="Soumissions (historique commercial)"
          count={soumissions.length}
          defaultOpen={false}
        >
          {soumissions.length === 0 ? (
            <EmptyHint>Aucune soumission.</EmptyHint>
          ) : (
            <SoumissionsTable soumissions={soumissions} />
          )}
        </CollapsibleSection>
      </section>

      {/* ------------------------- Notes & contacts ------------------------- */}
      <section className="mt-4">
        <CollapsibleSection
          title="Notes & contacts (éditable)"
          defaultOpen={false}
        >
          <NotesContactsEditor client={client} onSaved={onPatchClient} />
        </CollapsibleSection>
      </section>

      {/* ------------------------- Historique prospect ------------------------- */}
      {source_lead ? (
        <section className="mt-4">
          <CollapsibleSection
            title="Historique prospect"
            defaultOpen={false}
            hint={`Prospect d'origine — converti le ${fmtDate(client.converted_at)}`}
          >
            <SourceLeadPanel lead={source_lead} clientLeadId={client.converted_from_lead_id} />
          </CollapsibleSection>
        </section>
      ) : null}
    </>
  );
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function KpiCard({
  icon,
  label,
  value,
  sub,
  tone
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  sub?: string;
  tone: "neutral" | "emerald" | "amber";
}) {
  const toneClasses =
    tone === "emerald"
      ? "border-emerald-500/30 bg-emerald-500/5"
      : tone === "amber"
      ? "border-amber-500/30 bg-amber-500/5"
      : "border-brand-800 bg-brand-900";
  const valueTone =
    tone === "emerald"
      ? "text-emerald-300"
      : tone === "amber"
      ? "text-amber-300"
      : "text-white";
  const iconTone =
    tone === "emerald"
      ? "text-emerald-300"
      : tone === "amber"
      ? "text-amber-300"
      : "text-accent-500";
  return (
    <div className={`rounded-xl border ${toneClasses} p-4`}>
      <div className={`flex items-center gap-2 text-xs uppercase tracking-wider ${iconTone}`}>
        {icon}
        <span>{label}</span>
      </div>
      <p className={`mt-2 text-2xl font-bold leading-tight ${valueTone}`}>{value}</p>
      {sub ? <p className="mt-0.5 text-[11px] text-white/50">{sub}</p> : null}
    </div>
  );
}

function SectionHeader({
  title,
  count,
  hint
}: {
  title: string;
  count?: number;
  hint?: string;
}) {
  return (
    <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
      <h2 className="text-sm font-semibold uppercase tracking-wider text-accent-500">
        {title}
        {typeof count === "number" ? (
          <span className="ml-2 rounded-full bg-white/10 px-2 py-0.5 text-[10px] text-white/70">
            {count}
          </span>
        ) : null}
      </h2>
      {hint ? <p className="text-[11px] text-white/40">{hint}</p> : null}
    </div>
  );
}

function EmptyHint({ children }: { children: React.ReactNode }) {
  return (
    <p className="rounded-lg border border-dashed border-white/10 bg-white/[0.02] px-4 py-3 text-xs text-white/50">
      {children}
    </p>
  );
}

function ProjectCard({ project }: { project: Project }) {
  const tone = PROJECT_STATUS_TONE[project.status] || "bg-white/10 text-white/70";
  const label = PROJECT_STATUS_LABELS[project.status] || project.status;
  return (
    <Link
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      href={`/dev-logiciel/projets/${project.id}` as any}
      className="group block rounded-xl border border-brand-800 bg-brand-900 p-4 transition hover:border-accent-500 hover:bg-brand-800/60"
    >
      <div className="flex items-start justify-between gap-2">
        <p className="line-clamp-2 text-sm font-semibold text-white group-hover:text-accent-500">
          {project.name}
        </p>
        <span className={`shrink-0 rounded px-2 py-0.5 text-[10px] uppercase ${tone}`}>
          {label}
        </span>
      </div>
      <div className="mt-3 space-y-1 text-[11px] text-white/50">
        {project.started_at ? (
          <p>Démarré le {fmtDateShort(project.started_at)}</p>
        ) : project.start_date ? (
          <p>Début prévu : {fmtDateShort(project.start_date)}</p>
        ) : null}
        {project.due_date ? (
          <p>Échéance : {fmtDateShort(project.due_date)}</p>
        ) : null}
        {project.soumission_id ? (
          <p>Soumission #{project.soumission_id}</p>
        ) : null}
      </div>
    </Link>
  );
}

function InvoicesTable({ invoices }: { invoices: Invoice[] }) {
  return (
    <div className="overflow-hidden rounded-xl border border-brand-800 bg-brand-900">
      <table className="min-w-full divide-y divide-brand-800 text-sm">
        <thead>
          <tr className="bg-brand-950/60 text-[11px] uppercase tracking-wider text-white/50">
            <th className="px-3 py-2 text-left">N°</th>
            <th className="px-3 py-2 text-left">Émise</th>
            <th className="px-3 py-2 text-right">Montant</th>
            <th className="px-3 py-2 text-left">Statut</th>
            <th className="px-3 py-2 text-right">Actions</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-brand-800">
          {invoices.map((inv) => {
            const label = INVOICE_STATUS_LABELS[inv.status] || inv.status;
            const tone =
              INVOICE_STATUS_TONE[inv.status] || "bg-white/10 text-white/70";
            return (
              <tr key={inv.id} className="hover:bg-brand-950/40">
                <td className="px-3 py-2 font-medium text-white">
                  {inv.number || `#${inv.id}`}
                </td>
                <td className="px-3 py-2 text-white/70">
                  {fmtDateShort(inv.issued_date)}
                </td>
                <td className="px-3 py-2 text-right font-semibold text-white">
                  {fmtMoney(inv.amount)}
                </td>
                <td className="px-3 py-2">
                  <span className={`rounded px-2 py-0.5 text-[10px] uppercase ${tone}`}>
                    {label}
                  </span>
                  {inv.paid_at ? (
                    <span className="ml-2 text-[10px] text-white/40">
                      le {fmtDateShort(inv.paid_at)}
                    </span>
                  ) : null}
                </td>
                <td className="px-3 py-2 text-right">
                  <Link
                    // eslint-disable-next-line @typescript-eslint/no-explicit-any
                    href={`/dev-logiciel/facturation/${inv.id}` as any}
                    className="text-xs text-accent-500 hover:text-accent-400"
                  >
                    Voir
                  </Link>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function ContractsTable({ contracts }: { contracts: Contract[] }) {
  return (
    <div className="overflow-hidden rounded-xl border border-brand-800 bg-brand-900">
      <table className="min-w-full divide-y divide-brand-800 text-sm">
        <thead>
          <tr className="bg-brand-950/60 text-[11px] uppercase tracking-wider text-white/50">
            <th className="px-3 py-2 text-left">Titre</th>
            <th className="px-3 py-2 text-left">Statut</th>
            <th className="px-3 py-2 text-left">Signé le</th>
            <th className="px-3 py-2 text-right">Projet</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-brand-800">
          {contracts.map((c) => {
            const label = CONTRACT_STATUS_LABELS[c.status] || c.status;
            const tone =
              CONTRACT_STATUS_TONE[c.status] || "bg-white/10 text-white/70";
            return (
              <tr key={c.id} className="hover:bg-brand-950/40">
                <td className="px-3 py-2">
                  <Link
                    // eslint-disable-next-line @typescript-eslint/no-explicit-any
                    href={`/dev-logiciel/contrats/${c.id}` as any}
                    className="font-medium text-white hover:text-accent-500"
                  >
                    {c.title}
                  </Link>
                </td>
                <td className="px-3 py-2">
                  <span className={`rounded px-2 py-0.5 text-[10px] uppercase ${tone}`}>
                    {label}
                  </span>
                </td>
                <td className="px-3 py-2 text-white/70">
                  {c.signed_at ? (
                    <span>
                      {fmtDateShort(c.signed_at)}
                      {c.signed_name ? (
                        <span className="text-white/40"> · par {c.signed_name}</span>
                      ) : null}
                    </span>
                  ) : (
                    "—"
                  )}
                </td>
                <td className="px-3 py-2 text-right text-xs">
                  {c.project_id ? (
                    <Link
                      // eslint-disable-next-line @typescript-eslint/no-explicit-any
                      href={`/dev-logiciel/projets/${c.project_id}` as any}
                      className="text-accent-500 hover:text-accent-400"
                    >
                      Projet #{c.project_id}
                    </Link>
                  ) : (
                    <span className="text-white/30">—</span>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function SoumissionsTable({ soumissions }: { soumissions: Soumission[] }) {
  return (
    <div className="overflow-hidden rounded-xl border border-brand-800 bg-brand-900">
      <table className="min-w-full divide-y divide-brand-800 text-sm">
        <thead>
          <tr className="bg-brand-950/60 text-[11px] uppercase tracking-wider text-white/50">
            <th className="px-3 py-2 text-left">Titre</th>
            <th className="px-3 py-2 text-left">Statut</th>
            <th className="px-3 py-2 text-right">Montant</th>
            <th className="px-3 py-2 text-left">Créée le</th>
            <th className="px-3 py-2 text-right" />
          </tr>
        </thead>
        <tbody className="divide-y divide-brand-800">
          {soumissions.map((s) => {
            const label = SOUMISSION_STATUS_LABELS[s.status] || s.status;
            const tone =
              SOUMISSION_STATUS_TONE[s.status] || "bg-white/10 text-white/70";
            return (
              <tr key={s.id} className="hover:bg-brand-950/40">
                <td className="px-3 py-2 font-medium text-white">{s.title}</td>
                <td className="px-3 py-2">
                  <span className={`rounded px-2 py-0.5 text-[10px] uppercase ${tone}`}>
                    {label}
                  </span>
                </td>
                <td className="px-3 py-2 text-right text-white/80">
                  {s.amount != null ? fmtMoney(s.amount) : "—"}
                </td>
                <td className="px-3 py-2 text-white/60">
                  {fmtDateShort(s.created_at)}
                </td>
                <td className="px-3 py-2 text-right">
                  <Link
                    // eslint-disable-next-line @typescript-eslint/no-explicit-any
                    href={`/dev-logiciel/soumissions/${s.id}` as any}
                    className="text-xs text-accent-500 hover:text-accent-400"
                  >
                    Voir
                  </Link>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function CollapsibleSection({
  title,
  count,
  hint,
  defaultOpen = false,
  children
}: {
  title: string;
  count?: number;
  hint?: string;
  defaultOpen?: boolean;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="overflow-hidden rounded-xl border border-brand-800 bg-brand-900">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-2 px-4 py-3 text-left text-sm font-semibold transition hover:bg-brand-950/40"
      >
        {open ? (
          <ChevronDown className="h-4 w-4 text-accent-500" />
        ) : (
          <ChevronRight className="h-4 w-4 text-white/40" />
        )}
        <span className="uppercase tracking-wider text-accent-500">{title}</span>
        {typeof count === "number" ? (
          <span className="rounded-full bg-white/10 px-2 py-0.5 text-[10px] text-white/70">
            {count}
          </span>
        ) : null}
        {hint ? (
          <span className="ml-auto text-[11px] font-normal normal-case text-white/40">
            {hint}
          </span>
        ) : null}
      </button>
      {open ? <div className="border-t border-brand-800 p-4">{children}</div> : null}
    </div>
  );
}

function NotesContactsEditor({
  client,
  onSaved
}: {
  client: Client;
  onSaved: (c: Client) => void;
}) {
  const [name, setName] = useState(client.name);
  const [company, setCompany] = useState(client.company || "");
  const [email, setEmail] = useState(client.email || "");
  const [phone, setPhone] = useState(client.phone || "");
  const [address, setAddress] = useState(client.address || "");
  const [website, setWebsite] = useState(client.website || "");
  const [notes, setNotes] = useState(client.notes || "");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const dirty = useMemo(() => {
    return (
      name !== client.name ||
      company !== (client.company || "") ||
      email !== (client.email || "") ||
      phone !== (client.phone || "") ||
      address !== (client.address || "") ||
      website !== (client.website || "") ||
      notes !== (client.notes || "")
    );
  }, [client, name, company, email, phone, address, website, notes]);

  async function onSave() {
    setSaving(true);
    setError(null);
    try {
      const payload = {
        name: name.trim(),
        company: company.trim() || null,
        email: email.trim() || null,
        phone: phone.trim() || null,
        address: address.trim() || null,
        website: website.trim() || null,
        notes: notes.trim() || null
      };
      const res = await authedFetch(`/api/v1/devlog/clients/${client.id}`, {
        method: "PATCH",
        body: JSON.stringify(payload)
      });
      if (!res.ok) throw new Error();
      const updated = (await res.json()) as Client;
      onSaved(updated);
    } catch {
      setError("Sauvegarde échouée.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Nom du contact">
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="input"
          />
        </Field>
        <Field label="Entreprise">
          <input
            type="text"
            value={company}
            onChange={(e) => setCompany(e.target.value)}
            className="input"
          />
        </Field>
        <Field label="Courriel">
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="input"
          />
        </Field>
        <Field label="Téléphone">
          <input
            type="tel"
            value={phone}
            onChange={(e) => setPhone(e.target.value)}
            className="input"
          />
        </Field>
        <div className="sm:col-span-2">
          <Field label="Adresse">
            <AddressInput value={address} onChange={setAddress} />
          </Field>
        </div>
        <div className="sm:col-span-2">
          <Field label="Site web">
            <input
              type="url"
              value={website}
              onChange={(e) => setWebsite(e.target.value)}
              className="input"
              placeholder="https://"
            />
          </Field>
        </div>
        <div className="sm:col-span-2">
          <Field label="Notes internes">
            <textarea
              rows={4}
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="Préférences, historique, personnes contact…"
              className="input"
            />
          </Field>
        </div>
      </div>

      {error ? (
        <p className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
          {error}
        </p>
      ) : null}

      <button
        type="button"
        onClick={onSave}
        disabled={saving || !dirty}
        className="btn-accent justify-center disabled:opacity-50"
      >
        {saving ? (
          <>
            <Loader2 className="mr-2 h-4 w-4 animate-spin" /> Sauvegarde…
          </>
        ) : (
          <>
            <Save className="mr-2 h-4 w-4" />
            {dirty ? "Sauvegarder" : "Aucun changement"}
          </>
        )}
      </button>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <label className="label">{label}</label>
      {children}
    </div>
  );
}

function SourceLeadPanel({
  lead,
  clientLeadId
}: {
  lead: SourceLead;
  clientLeadId: number | null;
}) {
  return (
    <div className="space-y-3 text-sm">
      <div className="flex flex-wrap items-center gap-2 text-xs text-white/50">
        <span>Prospect créé le {fmtDate(lead.created_at)}</span>
        {lead.source ? <span>· Source : {lead.source}</span> : null}
        {lead.budget_range ? <span>· Budget : {lead.budget_range}</span> : null}
      </div>
      {lead.project_summary ? (
        <div>
          <p className="text-[11px] uppercase tracking-wider text-white/40">
            Plan / besoins
          </p>
          <p className="mt-1 whitespace-pre-wrap text-white/80">
            {lead.project_summary}
          </p>
        </div>
      ) : null}
      {lead.notes ? (
        <div>
          <p className="text-[11px] uppercase tracking-wider text-white/40">
            Notes de qualification
          </p>
          <p className="mt-1 whitespace-pre-wrap text-white/80">{lead.notes}</p>
        </div>
      ) : null}
      {lead.meeting_notes ? (
        <div>
          <p className="text-[11px] uppercase tracking-wider text-white/40">
            Notes de rencontre
          </p>
          <p className="mt-1 whitespace-pre-wrap text-white/80">
            {lead.meeting_notes}
          </p>
        </div>
      ) : null}
      <p className="pt-1 text-[11px] text-white/40">
        <FileText className="-mt-0.5 mr-1 inline h-3 w-3" />
        Lecture seule — la fiche prospect reste accessible{" "}
        {clientLeadId ? (
          <Link
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            href={`/dev-logiciel/leads/${clientLeadId}` as any}
            className="text-accent-500 underline decoration-dotted hover:text-accent-400"
          >
            ici
          </Link>
        ) : (
          <span>via le module Prospects</span>
        )}
        .
      </p>
    </div>
  );
}
