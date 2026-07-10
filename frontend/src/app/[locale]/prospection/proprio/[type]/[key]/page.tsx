"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import {
  ArrowLeft,
  Building2,
  Loader2,
  Mail,
  MapPin,
  MessageSquare,
  Phone,
  Sparkles
} from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { Link } from "@/i18n/navigation";
import { authedFetch } from "@/lib/auth";
import { useProspectionLayout } from "../../../layout";

type LeadMini = {
  id: number;
  name: string;
  address: string | null;
  city: string | null;
  status: string;
  score: number;
  nb_logements: number | null;
  valeur_fonciere: number | null;
};

type FollowUpItem = {
  id: number;
  lead_id: number;
  lead_name: string;
  kind: string;
  direction: string;
  outcome: string;
  notes: string | null;
  performed_at: string;
  next_action_at: string | null;
  next_action_label: string | null;
};

type OwnerView = {
  key: string;
  key_type: string;
  owner_name: string | null;
  owner_kind: string;
  owner_phone: string | null;
  owner_email: string | null;
  owner_address: string | null;
  owner_neq: string | null;
  leads_count: number;
  leads: LeadMini[];
  total_logements: number | null;
  total_valeur_fonciere: number | null;
  timeline: FollowUpItem[];
  next_action_at: string | null;
};

const STATUS_LABEL: Record<string, string> = {
  a_visiter: "À visiter",
  visite: "Visité",
  a_contacter: "À contacter",
  contacte: "Contacté",
  hot_lead: "🔥 Hot Lead",
  cold_lead: "🧊 Cold Lead",
  a_recontacter: "📅 À recontacter",
  soumissionne: "Soumissionné",
  converti: "Converti",
  perdu: "Perdu"
};

const STATUS_COLOR: Record<string, string> = {
  a_visiter: "badge-emerald",
  visite: "badge-blue",
  a_contacter: "badge-amber",
  contacte: "badge-violet",
  soumissionne: "bg-pink-500/20 text-pink-300",
  converti: "bg-green-500/30 text-green-200",
  perdu: "badge-rose"
};

const KIND_EMOJI: Record<string, string> = {
  call: "📞",
  email: "📨",
  sms: "💬",
  visite: "🚗",
  note: "📝",
  auto: "⏰"
};

const OUTCOME_LABEL: Record<string, string> = {
  reached: "Joint",
  voicemail: "Boîte vocale",
  no_answer: "Pas de réponse",
  interested: "Intéressé",
  not_interested: "Pas intéressé",
  won: "Gagné",
  lost: "Perdu",
  pending: "En attente",
  scheduled: "Programmé"
};

function fmtMoney(n: number | null): string {
  if (n == null) return "—";
  return new Intl.NumberFormat("fr-CA", {
    style: "currency",
    currency: "CAD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2
  }).format(n);
}

function fmtDate(iso: string): string {
  return new Date(iso).toLocaleDateString("fr-CA", {
    day: "2-digit",
    month: "short",
    year: "numeric"
  });
}

function fmtDateTime(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleDateString("fr-CA", {
    day: "2-digit",
    month: "short"
  }) + ` ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

export default function OwnerViewPage() {
  const { onOpenSidebar } = useProspectionLayout();
  const params = useParams<{ type: string; key: string }>();
  const type = params.type;
  const key = decodeURIComponent(params.key);

  const [view, setView] = useState<OwnerView | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const url =
          type === "neq"
            ? `/api/v1/prospection/owners/by-neq/${encodeURIComponent(
                key
              )}`
            : `/api/v1/prospection/owners/by-name/${encodeURIComponent(
                key
              )}`;
        const res = await authedFetch(url);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        if (!cancelled)
          setView((await res.json()) as OwnerView);
      } catch (e) {
        if (!cancelled) setError((e as Error).message);
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    if (type && key) void load();
    return () => {
      cancelled = true;
    };
  }, [type, key]);

  return (
    <>
      <AppTopbar
        breadcrumbs={[
          { label: "Prospection", href: "/prospection" },
          { label: "Propriétaire" }
        ]}
        onOpenSidebar={onOpenSidebar}
        rightSlot={
          <Link
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            href={"/prospection/leads" as any}
            className="btn-secondary btn-sm"
          >
            <ArrowLeft className="h-3.5 w-3.5" />
            Retour aux leads
          </Link>
        }
      />

      <div className="p-4 lg:p-6">
        {loading ? (
          <div className="flex min-h-[40vh] items-center justify-center">
            <Loader2 className="h-6 w-6 animate-spin text-accent-500" />
          </div>
        ) : error ? (
          <p className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-300">
            {error}
          </p>
        ) : !view || view.leads_count === 0 ? (
          <div className="empty-state mt-8">
            <Building2 className="mx-auto h-8 w-8 text-white/20" />
            <p className="mt-3 text-sm text-white/50">
              Aucun lead trouvé pour ce propriétaire.
            </p>
          </div>
        ) : (
          <>
            {/* Header */}
            <header className="rounded-2xl border border-brand-800 bg-brand-900 p-5">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <p className="text-[11px] uppercase tracking-wider text-accent-500">
                    {view.owner_kind === "corporation"
                      ? "Corporation"
                      : view.owner_kind === "particulier"
                        ? "Particulier"
                        : "Propriétaire"}
                  </p>
                  <h1 className="mt-0.5 text-2xl font-bold text-white">
                    {view.owner_name || "Propriétaire inconnu"}
                  </h1>
                  {view.owner_neq ? (
                    <p className="mt-1 font-mono text-[11px] text-white/50">
                      NEQ : {view.owner_neq}
                    </p>
                  ) : null}
                  {view.owner_address ? (
                    <p className="mt-1 flex items-center gap-1 text-xs text-white/60">
                      <MapPin className="h-3 w-3" />
                      {view.owner_address}
                    </p>
                  ) : null}
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  {view.owner_phone ? (
                    <a
                      href={`tel:${view.owner_phone}`}
                      className="btn-outline-accent btn-sm"
                    >
                      <Phone className="h-3.5 w-3.5" />
                      {view.owner_phone}
                    </a>
                  ) : null}
                  {view.owner_email ? (
                    <a
                      href={`mailto:${view.owner_email}`}
                      className="btn-secondary btn-sm"
                    >
                      <Mail className="h-3.5 w-3.5" />
                      Courriel
                    </a>
                  ) : null}
                </div>
              </div>

              {/* KPIs */}
              <div className="mt-4 grid gap-3 sm:grid-cols-4">
                <Kpi
                  icon={<Building2 className="h-4 w-4" />}
                  label="Immeubles"
                  value={String(view.leads_count)}
                />
                <Kpi
                  icon={<Sparkles className="h-4 w-4" />}
                  label="Logements (total)"
                  value={
                    view.total_logements != null
                      ? String(view.total_logements)
                      : "—"
                  }
                />
                <Kpi
                  icon={<Sparkles className="h-4 w-4" />}
                  label="Valeur foncière (total)"
                  value={fmtMoney(view.total_valeur_fonciere)}
                />
                <Kpi
                  icon={<Sparkles className="h-4 w-4" />}
                  label="Prochaine action"
                  value={
                    view.next_action_at
                      ? fmtDateTime(view.next_action_at)
                      : "—"
                  }
                />
              </div>
            </header>

            {/* Liste des immeubles */}
            <section className="mt-6 rounded-2xl border border-brand-800 bg-brand-900 p-5">
              <h2 className="mb-3 text-sm font-semibold uppercase tracking-wider text-accent-500">
                Ses immeubles ({view.leads.length})
              </h2>
              <ul className="space-y-2">
                {view.leads.map((l) => (
                  <li key={l.id}>
                    <Link
                      // eslint-disable-next-line @typescript-eslint/no-explicit-any
                      href={`/prospection/${l.id}` as any}
                      className="flex items-center gap-3 rounded-lg border border-brand-800 bg-brand-950/40 p-3 transition hover:border-accent-500/40"
                    >
                      <span
                        className={`inline-flex h-8 w-10 shrink-0 items-center justify-center rounded-md text-xs font-bold tabular-nums ${
                          l.score >= 70
                            ? "bg-emerald-500/30 text-emerald-200"
                            : l.score >= 50
                              ? "bg-amber-500/25 text-amber-200"
                              : l.score >= 30
                                ? "bg-blue-500/25 text-blue-200"
                                : "bg-brand-800 text-white/50"
                        }`}
                      >
                        {l.score}
                      </span>
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-sm font-medium text-white">
                          {l.name}
                        </p>
                        <p className="truncate text-[11px] text-white/50">
                          {l.address || "—"}
                          {l.city ? ` · ${l.city}` : ""}
                        </p>
                      </div>
                      <div className="hidden text-right text-[11px] text-white/60 sm:block">
                        <p className="tabular-nums">
                          {l.nb_logements ?? "—"} log.
                        </p>
                        <p className="tabular-nums">
                          {fmtMoney(l.valeur_fonciere)}
                        </p>
                      </div>
                      <span
                        className={`badge shrink-0 ${
                          STATUS_COLOR[l.status] || "badge-neutral"
                        }`}
                      >
                        {STATUS_LABEL[l.status] || l.status}
                      </span>
                    </Link>
                  </li>
                ))}
              </ul>
            </section>

            {/* Timeline cross-property */}
            <section className="mt-6 rounded-2xl border border-brand-800 bg-brand-900 p-5">
              <h2 className="mb-3 text-sm font-semibold uppercase tracking-wider text-accent-500">
                Timeline unifiée ({view.timeline.length})
              </h2>
              {view.timeline.length === 0 ? (
                <p className="text-xs text-white/40">
                  Aucune interaction journalisée sur les immeubles de
                  ce propriétaire.
                </p>
              ) : (
                <ol className="space-y-2">
                  {view.timeline.map((f) => (
                    <li
                      key={f.id}
                      className="flex items-start gap-3 rounded-md border border-brand-800 bg-brand-950/40 p-3 text-sm"
                    >
                      <span className="mt-0.5 text-base">
                        {KIND_EMOJI[f.kind] || "·"}
                      </span>
                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-baseline gap-2">
                          <span className="font-medium text-white">
                            {OUTCOME_LABEL[f.outcome] || f.outcome}
                          </span>
                          <span className="text-[11px] text-white/40">
                            · {f.direction === "inbound" ? "entrant" : "sortant"}
                          </span>
                          <span className="ml-auto text-[11px] text-white/40">
                            {fmtDateTime(f.performed_at)}
                          </span>
                        </div>
                        <Link
                          // eslint-disable-next-line @typescript-eslint/no-explicit-any
                          href={`/prospection/${f.lead_id}` as any}
                          className="text-[11px] text-accent-500 hover:text-accent-400"
                        >
                          → {f.lead_name}
                        </Link>
                        {f.notes ? (
                          <p className="mt-1 flex items-start gap-1 text-[12px] text-white/70">
                            <MessageSquare className="mt-0.5 h-3 w-3 shrink-0" />
                            <span className="italic">{f.notes}</span>
                          </p>
                        ) : null}
                        {f.next_action_at ? (
                          <p className="mt-1 text-[11px] text-amber-300">
                            ⏰ Prochaine : {f.next_action_label || "Suivi"}{" "}
                            le {fmtDate(f.next_action_at)}
                          </p>
                        ) : null}
                      </div>
                    </li>
                  ))}
                </ol>
              )}
            </section>
          </>
        )}
      </div>
    </>
  );
}

function Kpi({
  icon,
  label,
  value
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
}) {
  return (
    <div className="kpi-card">
      <div className="flex items-center gap-1.5 text-[10px] uppercase tracking-wider text-white/50">
        {icon}
        {label}
      </div>
      <p className="mt-1 text-lg font-bold tabular-nums text-white">
        {value}
      </p>
    </div>
  );
}
