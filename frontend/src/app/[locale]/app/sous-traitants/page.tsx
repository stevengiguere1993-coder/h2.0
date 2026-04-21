"use client";

import { useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  HardHat,
  Loader2,
  Mail,
  Phone,
  Plus,
  Star
} from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { useAppLayout } from "../layout";
import { authedFetch } from "@/lib/auth";
import { Link } from "@/i18n/navigation";

type SousTraitant = {
  id: number;
  full_name: string;
  contact_name: string | null;
  email: string | null;
  phone: string | null;
  address: string | null;
  rbq_license: string | null;
  rbq_expires_at: string | null;
  insurance_provider: string | null;
  insurance_expires_at: string | null;
  trades: string | null;
  hourly_rate: number | null;
  rating: number | null;
  competence_rating: number | null;
  availability_rating: number | null;
  punctuality_rating: number | null;
  quality_rating: number | null;
  active: boolean;
  notes: string | null;
  created_at: string;
};

function overallScore(st: SousTraitant): number | null {
  const axes = [
    st.competence_rating,
    st.availability_rating,
    st.punctuality_rating,
    st.quality_rating
  ].filter((v): v is number => typeof v === "number" && v > 0);
  if (axes.length > 0) {
    return axes.reduce((a, b) => a + b, 0) / axes.length;
  }
  return st.rating && st.rating > 0 ? st.rating : null;
}

function fmtRate(n: number | null): string {
  if (n == null) return "—";
  return (
    new Intl.NumberFormat("fr-CA", {
      style: "currency",
      currency: "CAD",
      maximumFractionDigits: 2
    }).format(n) + "/h"
  );
}

function daysUntil(iso: string | null): number | null {
  if (!iso) return null;
  const d = new Date(iso);
  if (isNaN(d.getTime())) return null;
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  return Math.round((d.getTime() - today.getTime()) / (1000 * 60 * 60 * 24));
}

export default function SousTraitantsPage() {
  const { onOpenSidebar } = useAppLayout();
  const [items, setItems] = useState<SousTraitant[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const res = await authedFetch("/api/v1/sous-traitants?limit=500");
        if (!res.ok) throw new Error(`http_${res.status}`);
        const data = (await res.json()) as SousTraitant[];
        if (!cancelled) setItems(data);
      } catch {
        if (!cancelled) setError("Impossible de charger les sous-traitants.");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, []);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return items;
    return items.filter(
      (x) =>
        x.full_name.toLowerCase().includes(q) ||
        (x.contact_name || "").toLowerCase().includes(q) ||
        (x.email || "").toLowerCase().includes(q) ||
        (x.phone || "").includes(q) ||
        (x.trades || "").toLowerCase().includes(q) ||
        (x.rbq_license || "").toLowerCase().includes(q)
    );
  }, [items, search]);

  return (
    <>
      <AppTopbar
        breadcrumbs={[{ label: "Ressources", href: "/app" }, { label: "Sous-traitants" }]}
        onOpenSidebar={onOpenSidebar}
        onSearch={setSearch}
        searchPlaceholder="Nom, RBQ, métier, courriel…"
        rightSlot={
          <Link
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            href={"/app/sous-traitants/new" as any}
            className="btn-accent text-sm"
          >
            <Plus className="mr-1.5 h-4 w-4" /> Nouveau sous-traitant
          </Link>
        }
      />

      <div className="p-4 lg:p-6">
        {error ? (
          <p className="mb-4 rounded-lg border border-rose-500/40 bg-rose-500/10 px-4 py-2 text-sm text-rose-300">
            {error}
          </p>
        ) : null}

        {loading ? (
          <div className="flex min-h-[40vh] items-center justify-center">
            <Loader2 className="h-6 w-6 animate-spin text-accent-500" />
          </div>
        ) : filtered.length === 0 ? (
          <EmptyState />
        ) : (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {filtered.map((st) => (
              <Card key={st.id} st={st} />
            ))}
          </div>
        )}
      </div>
    </>
  );
}

function Card({ st }: { st: SousTraitant }) {
  const rbqDays = daysUntil(st.rbq_expires_at);
  const insDays = daysUntil(st.insurance_expires_at);
  const rbqExpired = rbqDays != null && rbqDays < 0;
  const insExpired = insDays != null && insDays < 0;
  const rbqExpiringSoon = rbqDays != null && rbqDays >= 0 && rbqDays <= 30;
  const insExpiringSoon = insDays != null && insDays >= 0 && insDays <= 30;

  const trades = (st.trades || "")
    .split(",")
    .map((t) => t.trim())
    .filter(Boolean);

  return (
    <Link
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      href={`/app/sous-traitants/${st.id}` as any}
      className="group flex flex-col gap-3 rounded-xl border border-brand-800 bg-brand-900 p-5 transition hover:border-accent-500"
    >
      <div className="flex items-start justify-between">
        <div className="min-w-0">
          <h3 className="truncate text-base font-semibold text-white group-hover:text-accent-500">
            {st.full_name}
          </h3>
          {st.contact_name ? (
            <p className="truncate text-xs text-white/60">{st.contact_name}</p>
          ) : null}
        </div>
        <OverallBadge score={overallScore(st)} />
      </div>

      {/* Trades */}
      {trades.length > 0 ? (
        <div className="flex flex-wrap gap-1">
          {trades.slice(0, 4).map((t) => (
            <span
              key={t}
              className="rounded-md bg-accent-500/15 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-accent-500"
            >
              {t}
            </span>
          ))}
          {trades.length > 4 ? (
            <span className="text-[10px] text-white/40">+{trades.length - 4}</span>
          ) : null}
        </div>
      ) : null}

      {/* Contact */}
      <div className="space-y-1 text-xs text-white/70">
        {st.phone ? (
          <p className="flex items-center gap-1.5">
            <Phone className="h-3 w-3" /> <span>{st.phone}</span>
          </p>
        ) : null}
        {st.email ? (
          <p className="flex items-center gap-1.5">
            <Mail className="h-3 w-3" /> <span className="truncate">{st.email}</span>
          </p>
        ) : null}
      </div>

      {/* RBQ & insurance status */}
      <div className="flex flex-wrap gap-2 text-[10px]">
        {st.rbq_license ? (
          <span
            className={`inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 font-semibold ${
              rbqExpired
                ? "bg-rose-500/15 text-rose-300"
                : rbqExpiringSoon
                ? "bg-amber-500/15 text-amber-300"
                : "bg-emerald-500/10 text-emerald-300"
            }`}
          >
            {rbqExpired || rbqExpiringSoon ? (
              <AlertTriangle className="h-3 w-3" />
            ) : null}
            RBQ {st.rbq_license}
          </span>
        ) : (
          <span className="rounded-md bg-rose-500/10 px-1.5 py-0.5 font-semibold text-rose-300">
            Pas de licence RBQ
          </span>
        )}
        {st.insurance_provider ? (
          <span
            className={`inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 font-semibold ${
              insExpired
                ? "bg-rose-500/15 text-rose-300"
                : insExpiringSoon
                ? "bg-amber-500/15 text-amber-300"
                : "bg-emerald-500/10 text-emerald-300"
            }`}
          >
            {insExpired || insExpiringSoon ? (
              <AlertTriangle className="h-3 w-3" />
            ) : null}
            Assurance OK
          </span>
        ) : (
          <span className="rounded-md bg-rose-500/10 px-1.5 py-0.5 font-semibold text-rose-300">
            Assurance manquante
          </span>
        )}
        {!st.active ? (
          <span className="rounded-md bg-white/5 px-1.5 py-0.5 font-semibold text-white/50">
            Inactif
          </span>
        ) : null}
      </div>

      {/* Rate */}
      <div className="flex items-center justify-between pt-1 text-xs">
        <span className="text-white/50">Taux horaire</span>
        <span className="font-semibold text-white">{fmtRate(st.hourly_rate)}</span>
      </div>
    </Link>
  );
}

function OverallBadge({ score }: { score: number | null }) {
  if (score == null) {
    return <span className="text-[10px] text-white/30">Non évalué</span>;
  }
  const rounded = Math.round(score);
  return (
    <div className="flex items-center gap-1.5">
      <div className="flex items-center gap-0.5">
        {Array.from({ length: 5 }).map((_, i) => (
          <Star
            key={i}
            className={`h-3 w-3 ${
              i < rounded
                ? "fill-accent-500 text-accent-500"
                : "text-white/20"
            }`}
          />
        ))}
      </div>
      <span className="text-[10px] font-semibold text-white/70">
        {score.toFixed(1)}
      </span>
    </div>
  );
}

function EmptyState() {
  return (
    <div className="mx-auto mt-16 max-w-md rounded-2xl border border-dashed border-brand-800 bg-brand-900/40 p-10 text-center">
      <HardHat className="mx-auto h-10 w-10 text-accent-500" />
      <h2 className="mt-4 text-lg font-semibold text-white">
        Aucun sous-traitant
      </h2>
      <p className="mt-2 text-sm text-white/60">
        Ajoutez vos partenaires de métiers (plomberie, électricité, céramique…)
        avec leur licence RBQ, assurance et taux horaire.
      </p>
      <Link
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        href={"/app/sous-traitants/new" as any}
        className="btn-accent mt-6 inline-flex text-sm"
      >
        <Plus className="mr-1.5 h-4 w-4" />
        Nouveau sous-traitant
      </Link>
    </div>
  );
}
