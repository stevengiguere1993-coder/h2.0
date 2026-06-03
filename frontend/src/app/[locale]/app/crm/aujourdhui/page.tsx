"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertCircle,
  CalendarClock,
  CheckCircle2,
  ChevronRight,
  Clock,
  Filter,
  Loader2,
  Mail,
  MapPin,
  MessageSquare,
  Phone,
  Plus,
  RefreshCw,
  Smartphone,
  Sun,
  X
} from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { PageDriveSection } from "@/components/drive/PageDriveSection";
import { Link } from "@/i18n/navigation";
import { authedFetch } from "@/lib/auth";
import { useAppLayout } from "../../layout";
import { useConfirm } from "@/components/confirm-dialog";
import { formatPhone } from "@/lib/utils";

type FollowUp = {
  id: number;
  subject_type: string;
  subject_id: number;
  kind: string;
  direction: string;
  outcome: string;
  notes: string | null;
  performed_by_user_id: number | null;
  performed_at: string;
  next_action_at: string | null;
  next_action_label: string | null;
  created_at: string;
};

type QueueItem = {
  contact_request_id: number;
  contact_name: string;
  contact_phone: string | null;
  contact_email: string | null;
  contact_address: string | null;
  contact_status: string;
  contact_assigned_to_user_id: number | null;
  last_follow_up: FollowUp | null;
  next_action_at: string | null;
  next_action_label: string | null;
  bucket: string;
};

type QueueOut = {
  overdue: QueueItem[];
  today: QueueItem[];
  tomorrow: QueueItem[];
  later: QueueItem[];
  total: number;
};

const OUTCOME_OPTIONS: { value: string; label: string; emoji: string }[] = [
  { value: "no_answer", label: "Pas de réponse", emoji: "📵" },
  { value: "voicemail", label: "Boîte vocale", emoji: "📨" },
  { value: "reached", label: "Joint", emoji: "🟢" },
  { value: "interested", label: "Intéressé", emoji: "🔥" },
  { value: "not_interested", label: "Pas intéressé", emoji: "❌" },
  { value: "won", label: "Gagné", emoji: "🏆" },
  { value: "lost", label: "Perdu", emoji: "🚫" }
];

function fmtRelative(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  const now = new Date();
  const diff = (d.getTime() - now.getTime()) / (1000 * 60 * 60 * 24);
  if (diff < -1) {
    const days = Math.floor(-diff);
    return `il y a ${days} jour${days > 1 ? "s" : ""}`;
  }
  if (diff < 0) return "en retard";
  if (diff < 1) {
    const h = (d.getHours().toString()).padStart(2, "0");
    const m = (d.getMinutes().toString()).padStart(2, "0");
    return `aujourd'hui ${h}:${m}`;
  }
  if (diff < 2) return "demain";
  return d.toLocaleDateString("fr-CA", {
    day: "2-digit",
    month: "short"
  });
}

export default function CrmAujourdhuiPage() {
  const { onOpenSidebar } = useAppLayout();
  const confirm = useConfirm();
  const [queue, setQueue] = useState<QueueOut | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [mineOnly, setMineOnly] = useState(true);
  const [routePlanning, setRoutePlanning] = useState(false);

  async function planRoute() {
    if (routePlanning) return;
    setRoutePlanning(true);
    try {
      // Capture la position GPS si possible
      let coords: { lat: number; lng: number } | null = null;
      if (
        typeof navigator !== "undefined" &&
        navigator.geolocation
      ) {
        coords = await new Promise((resolve) => {
          navigator.geolocation.getCurrentPosition(
            (pos) =>
              resolve({
                lat: pos.coords.latitude,
                lng: pos.coords.longitude
              }),
            () => resolve(null),
            { enableHighAccuracy: true, timeout: 5000 }
          );
        });
      }
      const res = await authedFetch(
        "/api/v1/follow-ups/daily-route",
        {
          method: "POST",
          body: JSON.stringify({
            bucket: "today",
            max_stops: 10,
            start_lat: coords?.lat,
            start_lng: coords?.lng
          })
        }
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = (await res.json()) as {
        google_maps_url: string | null;
        ordered_lead_ids: number[];
        skipped_no_address: number;
        notes: string[];
      };
      if (data.google_maps_url) {
        window.open(
          data.google_maps_url,
          "_blank",
          "noopener,noreferrer"
        );
      } else {
        alert(
          "Pas assez de leads géocodables aujourd'hui pour optimiser une route.\n\n" +
            (data.notes?.join("\n") || "")
        );
      }
    } catch (e) {
      alert(`Erreur : ${(e as Error).message}`);
    } finally {
      setRoutePlanning(false);
    }
  }

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams();
      if (mineOnly) params.set("mine", "true");
      const res = await authedFetch(
        `/api/v1/follow-ups/queue?${params}`
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setQueue((await res.json()) as QueueOut);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, [mineOnly]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <>
      <AppTopbar
        breadcrumbs={[
          { label: "CRM", href: "/app/crm" },
          { label: "Aujourd'hui" }
        ]}
        onOpenSidebar={onOpenSidebar}
        rightSlot={
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={planRoute}
              disabled={routePlanning}
              className="inline-flex items-center gap-1.5 rounded-md border border-emerald-500/40 bg-emerald-500/10 px-2.5 py-1.5 text-xs font-medium text-emerald-300 hover:bg-emerald-500/20 disabled:opacity-50"
              title="Optimise l'ordre de visite via OSRM"
            >
              {routePlanning ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <MapPin className="h-3.5 w-3.5" />
              )}
              Route du jour
            </button>
            <button
              type="button"
              onClick={() => setMineOnly((v) => !v)}
              className={`inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1.5 text-xs font-medium transition ${
                mineOnly
                  ? "border-emerald-500/50 bg-emerald-500/15 text-emerald-300"
                  : "border-brand-700 bg-brand-900 text-white/60 hover:text-white"
              }`}
            >
              <Filter className="h-3.5 w-3.5" />
              {mineOnly ? "Mes leads" : "Tous"}
            </button>
            <button
              type="button"
              onClick={load}
              className="rounded-md p-1.5 text-white/40 hover:bg-brand-900 hover:text-white"
              title="Rafraîchir"
            >
              <RefreshCw className="h-4 w-4" />
            </button>
            <Link
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
              href={"/m/crm" as any}
              className="hidden items-center gap-1 rounded-md border border-brand-700 bg-brand-900 px-2.5 py-1.5 text-xs text-white/70 hover:text-white sm:inline-flex"
            >
              <Smartphone className="h-3.5 w-3.5" />
              Vue mobile
            </Link>
          </div>
        }
      />

      <div className="p-4 lg:p-6">
        <h1 className="flex items-center gap-2 text-2xl font-bold text-white">
          <Sun className="h-6 w-6 text-amber-400" />
          Aujourd&apos;hui
        </h1>
        <p className="mt-1 text-sm text-white/60">
          Ta queue de prospection — appels et relances à faire aujourd&apos;hui,
          en retard d&apos;abord.
        </p>

        <PageDriveSection
          pageKey="page:app:crm-aujourdhui"
          pole="Construction"
          label="CRM — Aujourd'hui"
          route="/app/crm/aujourdhui"
          className="mt-6"
        />

        {error ? (
          <p className="mt-4 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-300">
            {error}
          </p>
        ) : null}

        {loading ? (
          <div className="flex min-h-[40vh] items-center justify-center">
            <Loader2 className="h-6 w-6 animate-spin text-accent-500" />
          </div>
        ) : !queue ? null : queue.total === 0 ? (
          <div className="mt-8 rounded-2xl border border-dashed border-brand-800 bg-brand-900/50 p-12 text-center">
            <CheckCircle2 className="mx-auto h-10 w-10 text-emerald-400" />
            <p className="mt-3 text-base font-bold text-white">
              Tu es à jour 🎉
            </p>
            <p className="mt-1 text-sm text-white/60">
              Aucune relance prévue dans les 14 prochains jours.
            </p>
            <Link
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
              href={"/app/crm" as any}
              className="mt-4 inline-flex items-center gap-1 text-xs text-emerald-400 hover:text-emerald-300"
            >
              Voir le pipeline complet <ChevronRight className="h-3 w-3" />
            </Link>
          </div>
        ) : (
          <div className="mt-6 space-y-6">
            <Bucket
              title="En retard"
              accent="rose"
              icon={<AlertCircle className="h-4 w-4" />}
              items={queue.overdue}
              onChange={load}
            />
            <Bucket
              title="Aujourd'hui"
              accent="amber"
              icon={<Sun className="h-4 w-4" />}
              items={queue.today}
              onChange={load}
            />
            <Bucket
              title="Demain"
              accent="blue"
              icon={<Clock className="h-4 w-4" />}
              items={queue.tomorrow}
              onChange={load}
            />
            <Bucket
              title="Cette semaine"
              accent="white"
              icon={<CalendarClock className="h-4 w-4" />}
              items={queue.later}
              onChange={load}
            />
          </div>
        )}
      </div>
    </>
  );
}

const ACCENT_CLASSES: Record<
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
  accent,
  icon,
  items,
  onChange
}: {
  title: string;
  accent: string;
  icon: React.ReactNode;
  items: QueueItem[];
  onChange: () => void;
}) {
  if (items.length === 0) return null;
  const a = ACCENT_CLASSES[accent];
  return (
    <section>
      <header
        className={`mb-2 flex items-center gap-2 rounded-md ${a.bg} ${a.border} border px-3 py-1.5`}
      >
        <span className={a.text}>{icon}</span>
        <h2 className={`text-xs font-semibold uppercase tracking-wider ${a.text}`}>
          {title}
        </h2>
        <span className="ml-auto text-xs text-white/50">
          {items.length}
        </span>
      </header>
      <ul className="space-y-2">
        {items.map((it) => (
          <QueueRow key={it.contact_request_id} item={it} onChange={onChange} />
        ))}
      </ul>
    </section>
  );
}

function QueueRow({
  item,
  onChange
}: {
  item: QueueItem;
  onChange: () => void;
}) {
  const [busyOutcome, setBusyOutcome] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [justCalled, setJustCalled] = useState(false);

  async function logOutcome(outcome: string) {
    if (busyOutcome) return;
    setBusyOutcome(outcome);
    setError(null);
    try {
      const res = await authedFetch("/api/v1/follow-ups", {
        method: "POST",
        body: JSON.stringify({
          subject_type: "prospect",
          subject_id: item.contact_request_id,
          kind: "call",
          direction: "outbound",
          outcome,
          completed_step: item.next_action_label || undefined
        })
      });
      if (!res.ok) {
        const t = await res.text();
        throw new Error(t.slice(0, 200) || `HTTP ${res.status}`);
      }
      onChange();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusyOutcome(null);
    }
  }

  return (
    <li className="rounded-xl border border-brand-800 bg-brand-900 p-3">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <Link
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            href={`/app/crm/${item.contact_request_id}` as any}
            className="block truncate font-bold text-white hover:text-accent-500"
          >
            {item.contact_name}
          </Link>
          <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-white/60">
            {item.contact_phone ? (
              <a
                href={`tel:${item.contact_phone}`}
                onClick={() => setJustCalled(true)}
                className="inline-flex items-center gap-1 hover:text-emerald-300"
              >
                <Phone className="h-3 w-3" />
                {formatPhone(item.contact_phone)}
              </a>
            ) : null}
            {item.contact_email ? (
              <a
                href={`mailto:${item.contact_email}`}
                className="inline-flex items-center gap-1 hover:text-emerald-300"
              >
                <Mail className="h-3 w-3" />
                {item.contact_email}
              </a>
            ) : null}
            {item.contact_address ? (
              <span className="truncate">{item.contact_address}</span>
            ) : null}
          </div>
          {item.last_follow_up?.notes ? (
            <p className="mt-1.5 line-clamp-2 text-[11px] italic text-white/40">
              <MessageSquare className="mr-1 inline h-3 w-3" />
              {item.last_follow_up.notes}
            </p>
          ) : null}
        </div>
        <div className="text-right text-[10px] text-white/50">
          <div className="font-medium uppercase tracking-wider">
            {item.next_action_label || "à rappeler"}
          </div>
          <div className="mt-0.5 tabular-nums">
            {fmtRelative(item.next_action_at)}
          </div>
        </div>
      </div>

      {/* Hint après un click-to-call */}
      {justCalled ? (
        <p className="mt-2 rounded-md border border-amber-500/40 bg-amber-500/10 px-2 py-1 text-[11px] text-amber-200">
          📞 Comment s&apos;est passé l&apos;appel ?
        </p>
      ) : null}

      {/* Quick outcome buttons */}
      <div className="mt-3 flex flex-wrap gap-1.5">
        {OUTCOME_OPTIONS.map((o) => (
          <button
            key={o.value}
            type="button"
            onClick={() => logOutcome(o.value)}
            disabled={busyOutcome !== null}
            className={`inline-flex items-center gap-1 rounded-md border px-2 py-1 text-[11px] font-medium transition disabled:opacity-40 ${
              o.value === "interested" || o.value === "won"
                ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-300 hover:bg-emerald-500/20"
                : o.value === "not_interested" || o.value === "lost"
                  ? "border-rose-500/40 bg-rose-500/10 text-rose-300 hover:bg-rose-500/20"
                  : "border-brand-700 bg-brand-950 text-white/70 hover:bg-brand-800 hover:text-white"
            }`}
          >
            {busyOutcome === o.value ? (
              <Loader2 className="h-3 w-3 animate-spin" />
            ) : (
              <span>{o.emoji}</span>
            )}
            {o.label}
          </button>
        ))}
      </div>

      {error ? (
        <p className="mt-2 rounded-md border border-rose-500/40 bg-rose-500/10 px-2 py-1 text-[11px] text-rose-300">
          {error}
        </p>
      ) : null}
    </li>
  );
}
