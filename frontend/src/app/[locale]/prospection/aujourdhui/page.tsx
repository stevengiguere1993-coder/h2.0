"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertCircle,
  CheckCircle2,
  Clock,
  Loader2,
  Mail,
  MapPin,
  Phone,
  RefreshCw,
  Sun
} from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { Link } from "@/i18n/navigation";
import { authedFetch } from "@/lib/auth";
import { useProspectionLayout } from "../layout";
import { PAMilestonesWidget } from "./_pa-milestones-widget";

type Lead = {
  id: number;
  name: string;
  status: string;
  address: string | null;
  city: string | null;
  owner_name: string | null;
  owner_phone: string | null;
  owner_email: string | null;
  nb_logements: number | null;
  valeur_fonciere: number | null;
  score: number;
  priority: number;
  last_contacted_at: string | null;
  created_at: string;
};

const STATUS_LABEL: Record<string, string> = {
  a_visiter: "Repéré",
  visite: "Visité",
  a_contacter: "À contacter",
  contacte: "Contacté",
  hot_lead: "🔥 Hot Lead",
  soumissionne: "Offre soumise",
  offre_acceptee: "Offre acceptée",
  en_inspection: "Inspection",
  en_nego: "Négociation",
  chez_notaire: "Chez le notaire",
  en_cession: "Cession en cours",
  converti: "Acheté / Cédé ✓",
  perdu: "Perdu / refus"
};

function fmtMoney(n: number | null): string {
  if (n == null) return "—";
  return new Intl.NumberFormat("fr-CA", {
    style: "currency",
    currency: "CAD",
    maximumFractionDigits: 0
  }).format(n);
}

function fmtRelative(iso: string | null): string {
  if (!iso) return "jamais contacté";
  const d = new Date(iso);
  const now = new Date();
  const days = Math.floor(
    (now.getTime() - d.getTime()) / (1000 * 60 * 60 * 24)
  );
  if (days < 1) return "aujourd'hui";
  if (days === 1) return "hier";
  if (days < 30) return `il y a ${days} j`;
  const months = Math.floor(days / 30);
  return `il y a ${months} mois`;
}

/**
 * Page « Aujourd'hui » du portail Prospection — queue d'action par
 * priorité.
 *
 * Buckets :
 * - À contacter : status=a_contacter (proprio identifié, pas joint)
 * - Repérés non visités : status=a_visiter (drive-by jamais fait)
 * - Pipeline actif : leads dans une étape post-offre (inspection,
 *   nego, notaire, cession) — actions critiques avec délais
 * - Relances dues : leads contactés il y a ≥ 7 jours sans
 *   changement de statut
 */
export default function ProspectionAujourdhuiPage() {
  const { onOpenSidebar } = useProspectionLayout();
  const [leads, setLeads] = useState<Lead[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await authedFetch(
        "/api/v1/prospection?limit=1000&archived=false"
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setLeads((await res.json()) as Lead[]);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const buckets = useMemo(() => {
    const now = Date.now();
    const sevenDays = 7 * 24 * 60 * 60 * 1000;

    const active_pipeline: Lead[] = [];
    const a_contacter: Lead[] = [];
    const a_visiter: Lead[] = [];
    const relances: Lead[] = [];

    const ACTIVE_PIPELINE = new Set([
      "soumissionne",
      "offre_acceptee",
      "en_inspection",
      "en_nego",
      "chez_notaire",
      "en_cession"
    ]);

    for (const l of leads) {
      if (l.status === "perdu" || l.status === "converti") continue;

      if (ACTIVE_PIPELINE.has(l.status)) {
        active_pipeline.push(l);
        continue;
      }
      if (l.status === "a_contacter") {
        a_contacter.push(l);
        continue;
      }
      if (l.status === "a_visiter") {
        a_visiter.push(l);
        continue;
      }
      if (l.status === "contacte" || l.status === "visite") {
        // Relance due si aucun contact dans les 7 derniers jours
        const lastTouch = l.last_contacted_at
          ? new Date(l.last_contacted_at).getTime()
          : new Date(l.created_at).getTime();
        if (now - lastTouch >= sevenDays) {
          relances.push(l);
        }
      }
    }

    // Tri principal : score desc, secondaire : priority desc
    const sortByScore = (a: Lead, b: Lead) =>
      b.score - a.score || b.priority - a.priority;
    active_pipeline.sort(sortByScore);
    a_contacter.sort(sortByScore);
    a_visiter.sort(sortByScore);
    relances.sort(sortByScore);

    return {
      active_pipeline,
      a_contacter,
      a_visiter,
      relances,
      total:
        active_pipeline.length +
        a_contacter.length +
        a_visiter.length +
        relances.length
    };
  }, [leads]);

  return (
    <>
      <AppTopbar
        breadcrumbs={[
          { label: "Prospection", href: "/prospection" },
          { label: "Aujourd'hui" }
        ]}
        onOpenSidebar={onOpenSidebar}
        rightSlot={
          <button
            type="button"
            onClick={load}
            className="rounded-md p-1.5 text-white/40 hover:bg-brand-900 hover:text-white"
            title="Rafraîchir"
          >
            <RefreshCw className="h-4 w-4" />
          </button>
        }
      />

      <div className="p-4 lg:p-6">
        <h1 className="flex items-center gap-2 text-2xl font-bold text-white">
          <Sun className="h-6 w-6 text-amber-400" />
          Aujourd&apos;hui
        </h1>
        <p className="mt-1 text-sm text-white/60">
          Ta queue de prospection — immeubles à contacter, à visiter,
          relances et pipeline actif.
        </p>

        {error ? (
          <p className="mt-4 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-300">
            {error}
          </p>
        ) : null}

        {loading ? (
          <div className="flex min-h-[40vh] items-center justify-center">
            <Loader2 className="h-6 w-6 animate-spin text-emerald-500" />
          </div>
        ) : buckets.total === 0 ? (
          <div className="mt-8 rounded-2xl border border-dashed border-brand-800 bg-brand-900/50 p-12 text-center">
            <CheckCircle2 className="mx-auto h-10 w-10 text-emerald-400" />
            <p className="mt-3 text-base font-bold text-white">
              Aucune action immédiate
            </p>
            <p className="mt-1 text-sm text-white/60">
              Va sur la carte ou en mode mobile pour ajouter de
              nouveaux immeubles à prospecter.
            </p>
          </div>
        ) : (
          <div className="mt-6 space-y-6">
            <PAMilestonesWidget days={7} />

            <Bucket
              title="Pipeline actif (post-offre)"
              hint="Inspection, négo, notaire, cession en cours"
              accent="rose"
              icon={<AlertCircle className="h-4 w-4" />}
              leads={buckets.active_pipeline}
            />
            <Bucket
              title="À contacter"
              hint="Propriétaires identifiés, premier appel à faire"
              accent="amber"
              icon={<Phone className="h-4 w-4" />}
              leads={buckets.a_contacter}
            />
            <Bucket
              title="Relances dues (7+ jours sans contact)"
              hint="Contactés/visités mais sans suite récente"
              accent="blue"
              icon={<Clock className="h-4 w-4" />}
              leads={buckets.relances}
            />
            <Bucket
              title="Repérés à visiter"
              hint="Drive-by capturé, pas encore de visite approfondie"
              accent="white"
              icon={<MapPin className="h-4 w-4" />}
              leads={buckets.a_visiter}
            />
          </div>
        )}
      </div>
    </>
  );
}

const ACCENT: Record<
  string,
  { border: string; bg: string; text: string }
> = {
  rose: {
    border: "border-rose-500/30",
    bg: "bg-rose-500/10",
    text: "text-rose-300"
  },
  amber: {
    border: "border-amber-500/30",
    bg: "bg-amber-500/10",
    text: "text-amber-300"
  },
  blue: {
    border: "border-blue-500/30",
    bg: "bg-blue-500/10",
    text: "text-blue-300"
  },
  white: {
    border: "border-brand-700",
    bg: "bg-brand-900",
    text: "text-white/60"
  }
};

function Bucket({
  title,
  hint,
  accent,
  icon,
  leads
}: {
  title: string;
  hint: string;
  accent: string;
  icon: React.ReactNode;
  leads: Lead[];
}) {
  if (leads.length === 0) return null;
  const a = ACCENT[accent];
  return (
    <section>
      <header
        className={`mb-2 flex items-center gap-2 rounded-md ${a.bg} ${a.border} border px-3 py-1.5`}
      >
        <span className={a.text}>{icon}</span>
        <h2
          className={`text-xs font-semibold uppercase tracking-wider ${a.text}`}
        >
          {title}
        </h2>
        <span className="ml-auto text-xs text-white/50">
          {leads.length}
        </span>
      </header>
      <p className="mb-2 px-3 text-[11px] text-white/40">{hint}</p>
      <ul className="space-y-2">
        {leads.map((l) => (
          <li
            key={l.id}
            className="rounded-xl border border-brand-800 bg-brand-900 p-3"
          >
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="min-w-0 flex-1">
                <Link
                  // eslint-disable-next-line @typescript-eslint/no-explicit-any
                  href={`/prospection/${l.id}` as any}
                  className="block truncate font-bold text-white hover:text-emerald-300"
                >
                  {l.name}
                </Link>
                <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-white/60">
                  {l.address ? (
                    <span className="inline-flex items-center gap-1">
                      <MapPin className="h-3 w-3" />
                      {l.address}
                      {l.city ? ` · ${l.city}` : ""}
                    </span>
                  ) : null}
                  {l.owner_phone ? (
                    <a
                      href={`tel:${l.owner_phone}`}
                      className="inline-flex items-center gap-1 hover:text-emerald-300"
                    >
                      <Phone className="h-3 w-3" />
                      {l.owner_phone}
                    </a>
                  ) : null}
                  {l.owner_email ? (
                    <a
                      href={`mailto:${l.owner_email}`}
                      className="inline-flex items-center gap-1 hover:text-emerald-300"
                    >
                      <Mail className="h-3 w-3" />
                      {l.owner_email}
                    </a>
                  ) : null}
                  {l.owner_name ? (
                    <span className="text-white/50">
                      {l.owner_name}
                    </span>
                  ) : null}
                </div>
              </div>
              <div className="text-right">
                <div className="flex items-center justify-end gap-2">
                  <span
                    className={`inline-flex h-6 w-9 items-center justify-center rounded text-[11px] font-bold tabular-nums ${
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
                  <span className="text-[10px] uppercase tracking-wider text-white/50">
                    {STATUS_LABEL[l.status] || l.status}
                  </span>
                </div>
                <div className="mt-1 text-[10px] text-white/40">
                  {l.nb_logements != null ? `${l.nb_logements} log. · ` : ""}
                  {fmtMoney(l.valeur_fonciere)}
                </div>
                <div className="mt-0.5 text-[10px] text-white/40">
                  {fmtRelative(l.last_contacted_at)}
                </div>
              </div>
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}
