"use client";

import { useCallback, useEffect, useState } from "react";
import {
  AlertCircle,
  Clock,
  Loader2,
  MapPin,
  Mail,
  MessageSquare,
  Phone,
  RefreshCw,
  Sun
} from "lucide-react";

import { Link } from "@/i18n/navigation";
import { authedFetch } from "@/lib/auth";
import { formatPhone } from "@/lib/utils";

type FollowUp = {
  id: number;
  outcome: string;
  notes: string | null;
  performed_at: string;
  next_action_at: string | null;
  next_action_label: string | null;
};

type QueueItem = {
  contact_request_id: number;
  contact_name: string;
  contact_phone: string | null;
  contact_email: string | null;
  contact_address: string | null;
  contact_status: string;
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

const OUTCOMES: {
  value: string;
  label: string;
  emoji: string;
  cls: string;
}[] = [
  {
    value: "no_answer",
    label: "Pas de rép.",
    emoji: "📵",
    cls: "border-brand-700 bg-brand-900 text-white/80"
  },
  {
    value: "voicemail",
    label: "BV",
    emoji: "📨",
    cls: "border-brand-700 bg-brand-900 text-white/80"
  },
  {
    value: "interested",
    label: "Intéressé",
    emoji: "🔥",
    cls: "border-emerald-500/50 bg-emerald-500/15 text-emerald-200"
  },
  {
    value: "not_interested",
    label: "Pas intér.",
    emoji: "❌",
    cls: "border-rose-500/50 bg-rose-500/15 text-rose-200"
  }
];

function fmtRel(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  const now = new Date();
  const diff = (d.getTime() - now.getTime()) / (1000 * 60 * 60 * 24);
  if (diff < -1) {
    const days = Math.floor(-diff);
    return `${days}j de retard`;
  }
  if (diff < 0) return "en retard";
  if (diff < 1) {
    const h = String(d.getHours()).padStart(2, "0");
    const m = String(d.getMinutes()).padStart(2, "0");
    return `${h}:${m}`;
  }
  if (diff < 2) return "demain";
  return d.toLocaleDateString("fr-CA", {
    day: "2-digit",
    month: "short"
  });
}

export default function MobileCrmPage() {
  const [queue, setQueue] = useState<QueueOut | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await authedFetch(
        "/api/v1/follow-ups/queue?mine=true"
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setQueue((await res.json()) as QueueOut);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <div className="min-h-screen bg-brand-950 pb-24">
      <header className="sticky top-0 z-10 border-b border-brand-800 bg-brand-950/95 px-4 py-3 backdrop-blur">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="flex items-center gap-1.5 text-lg font-bold text-white">
              <Sun className="h-5 w-5 text-amber-400" />
              Mes leads
            </h1>
            <p className="text-[11px] text-white/50">
              {queue?.total != null
                ? `${queue.total} relance${queue.total > 1 ? "s" : ""} prévue${queue.total > 1 ? "s" : ""}`
                : "—"}
            </p>
          </div>
          <button
            type="button"
            onClick={load}
            className="rounded-full bg-brand-900 p-2 text-white/60"
            aria-label="Rafraîchir"
          >
            <RefreshCw className="h-4 w-4" />
          </button>
        </div>
      </header>

      <main className="space-y-5 px-3 pt-4">
        {error ? (
          <p className="rounded-md border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
            {error}
          </p>
        ) : null}

        {loading ? (
          <div className="flex justify-center py-10">
            <Loader2 className="h-5 w-5 animate-spin text-accent-500" />
          </div>
        ) : !queue || queue.total === 0 ? (
          <div className="rounded-xl border border-dashed border-brand-800 p-8 text-center">
            <p className="text-2xl">🎉</p>
            <p className="mt-2 text-sm font-bold text-white">
              Tu es à jour
            </p>
            <p className="text-[11px] text-white/50">
              Aucune relance prévue.
            </p>
          </div>
        ) : (
          <>
            <Section
              title="En retard"
              accent="rose"
              items={queue.overdue}
              icon={<AlertCircle className="h-4 w-4" />}
              onChange={load}
            />
            <Section
              title="Aujourd'hui"
              accent="amber"
              items={queue.today}
              icon={<Sun className="h-4 w-4" />}
              onChange={load}
            />
            <Section
              title="Demain"
              accent="blue"
              items={queue.tomorrow}
              icon={<Clock className="h-4 w-4" />}
              onChange={load}
            />
            <Section
              title="Plus tard"
              accent="white"
              items={queue.later}
              icon={<Clock className="h-4 w-4" />}
              onChange={load}
            />
          </>
        )}
      </main>
    </div>
  );
}

const ACCENT: Record<string, string> = {
  rose: "text-rose-300",
  amber: "text-amber-300",
  blue: "text-blue-300",
  white: "text-white/60"
};

function Section({
  title,
  accent,
  items,
  icon,
  onChange
}: {
  title: string;
  accent: string;
  items: QueueItem[];
  icon: React.ReactNode;
  onChange: () => void;
}) {
  if (items.length === 0) return null;
  const a = ACCENT[accent];
  return (
    <section>
      <h2
        className={`flex items-center gap-1.5 px-1 text-[11px] font-semibold uppercase tracking-wider ${a}`}
      >
        {icon}
        {title}
        <span className="ml-auto text-white/40">{items.length}</span>
      </h2>
      <ul className="mt-2 space-y-3">
        {items.map((it) => (
          <Card key={it.contact_request_id} item={it} onChange={onChange} />
        ))}
      </ul>
    </section>
  );
}

function Card({
  item,
  onChange
}: {
  item: QueueItem;
  onChange: () => void;
}) {
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  async function logOutcome(outcome: string) {
    if (busy) return;
    setBusy(outcome);
    setErr(null);
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
      setErr((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  return (
    <li className="rounded-2xl border border-brand-800 bg-brand-900 p-3 shadow-sm">
      <Link
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        href={`/app/crm/${item.contact_request_id}` as any}
        className="block"
      >
        <div className="flex items-start justify-between gap-2">
          <h3 className="line-clamp-1 text-base font-bold text-white">
            {item.contact_name}
          </h3>
          <span className="shrink-0 rounded bg-brand-800 px-1.5 py-0.5 text-[9px] uppercase tabular-nums text-white/60">
            {fmtRel(item.next_action_at)}
          </span>
        </div>
        {item.next_action_label ? (
          <p className="mt-0.5 text-[11px] uppercase tracking-wider text-accent-500">
            {item.next_action_label}
          </p>
        ) : null}
        {item.contact_address ? (
          <p className="mt-1 flex items-center gap-1 text-[11px] text-white/50">
            <MapPin className="h-3 w-3" />
            {item.contact_address}
          </p>
        ) : null}
        {item.last_follow_up?.notes ? (
          <p className="mt-1 line-clamp-2 text-[11px] italic text-white/50">
            <MessageSquare className="mr-1 inline h-3 w-3" />
            {item.last_follow_up.notes}
          </p>
        ) : null}
      </Link>

      {/* Big tap targets : action contact + outcomes */}
      <div className="mt-2 flex gap-2">
        {item.contact_phone ? (
          <a
            href={`tel:${item.contact_phone}`}
            className="flex h-11 flex-1 items-center justify-center gap-1.5 rounded-xl bg-emerald-500 text-sm font-bold text-white"
          >
            <Phone className="h-4 w-4" />
            {formatPhone(item.contact_phone)}
          </a>
        ) : null}
        {item.contact_email ? (
          <a
            href={`mailto:${item.contact_email}`}
            className="flex h-11 w-11 items-center justify-center rounded-xl border border-brand-700 bg-brand-950 text-white/70"
            aria-label="Courriel"
          >
            <Mail className="h-4 w-4" />
          </a>
        ) : null}
      </div>

      <div className="mt-2 grid grid-cols-2 gap-2">
        {OUTCOMES.map((o) => (
          <button
            key={o.value}
            type="button"
            onClick={() => logOutcome(o.value)}
            disabled={busy !== null}
            className={`flex h-11 items-center justify-center gap-1.5 rounded-xl border text-xs font-bold transition disabled:opacity-40 ${o.cls}`}
          >
            {busy === o.value ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <>
                <span>{o.emoji}</span>
                <span>{o.label}</span>
              </>
            )}
          </button>
        ))}
      </div>

      {err ? (
        <p className="mt-2 rounded-md border border-rose-500/40 bg-rose-500/10 px-2 py-1 text-[10px] text-rose-300">
          {err}
        </p>
      ) : null}
    </li>
  );
}
