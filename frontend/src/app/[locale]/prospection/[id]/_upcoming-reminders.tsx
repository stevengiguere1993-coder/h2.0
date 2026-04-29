"use client";

import { useCallback, useEffect, useState } from "react";
import {
  AlarmClock,
  Check,
  Loader2,
  Mail,
  MessageCircle,
  PhoneCall,
  StickyNote,
  Users,
} from "lucide-react";

import { authedFetch } from "@/lib/auth";

type FollowUp = {
  id: number;
  subject_type: string;
  subject_id: number;
  kind: string;
  outcome: string;
  notes: string | null;
  performed_at: string;
  next_action_at: string | null;
  next_action_label: string | null;
};

const LABEL_ICON: Record<
  string,
  React.ComponentType<{ className?: string }>
> = {
  Rappeler: PhoneCall,
  Appel: PhoneCall,
  Texto: MessageCircle,
  SMS: MessageCircle,
  Courriel: Mail,
  Visite: Users,
  "Note interne": StickyNote,
};

function pickIcon(label: string | null) {
  if (!label) return AlarmClock;
  return LABEL_ICON[label] || AlarmClock;
}

function formatWhen(iso: string): { text: string; tone: string } {
  const d = new Date(iso);
  const now = new Date();
  const diffMs = d.getTime() - now.getTime();
  const diffMin = Math.round(diffMs / 60000);
  const diffH = Math.round(diffMin / 60);
  const diffD = Math.round(diffH / 24);

  let text: string;
  if (diffMs < 0) {
    if (diffMin > -60) text = `en retard de ${Math.abs(diffMin)} min`;
    else if (diffH > -24) text = `en retard de ${Math.abs(diffH)} h`;
    else text = `en retard de ${Math.abs(diffD)} j`;
  } else if (diffMin < 60) {
    text = `dans ${diffMin} min`;
  } else if (diffH < 24) {
    text = `dans ${diffH} h`;
  } else if (diffD <= 7) {
    text = `dans ${diffD} j`;
  } else {
    text = d.toLocaleDateString("fr-CA", {
      day: "2-digit",
      month: "short",
    });
  }

  const tone =
    diffMs < 0
      ? "border-rose-500/40 bg-rose-500/10 text-rose-200"
      : diffH < 24
        ? "border-amber-500/40 bg-amber-500/10 text-amber-200"
        : "border-blue-500/30 bg-blue-500/5 text-blue-200";

  return { text, tone };
}

export function UpcomingReminders({ leadId }: { leadId: number }) {
  const [items, setItems] = useState<FollowUp[]>([]);
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState<number | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await authedFetch(
        `/api/v1/follow-ups?subject_type=prospect&subject_id=${leadId}&limit=100`
      );
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const all = (await r.json()) as FollowUp[];
      const upcoming = all
        .filter(
          (f) =>
            f.next_action_at &&
            !["won", "lost", "not_interested"].includes(f.outcome)
        )
        .sort((a, b) =>
          (a.next_action_at || "").localeCompare(b.next_action_at || "")
        );
      setItems(upcoming);
    } catch {
      setItems([]);
    } finally {
      setLoading(false);
    }
  }, [leadId]);

  useEffect(() => {
    void load();
  }, [load]);

  async function markDone(id: number) {
    setBusyId(id);
    try {
      const r = await authedFetch(`/api/v1/follow-ups/${id}`, {
        method: "PATCH",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ next_action_at: null, next_action_label: null }),
      });
      if (!r.ok) throw new Error();
      setItems((xs) => xs.filter((x) => x.id !== id));
    } catch {
      // silent — reload pour resynchroniser
      await load();
    } finally {
      setBusyId(null);
    }
  }

  if (loading) {
    return (
      <section className="rounded-xl border border-brand-800 bg-brand-900 p-4">
        <div className="flex items-center gap-2 text-xs text-white/50">
          <Loader2 className="h-3.5 w-3.5 animate-spin" /> Chargement…
        </div>
      </section>
    );
  }

  if (items.length === 0) return null;

  return (
    <section className="rounded-xl border border-amber-500/30 bg-amber-500/5 p-4">
      <div className="flex items-center justify-between gap-2">
        <h2 className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wider text-amber-300">
          <AlarmClock className="h-4 w-4" />
          Rappels à venir
        </h2>
        <span className="text-xs text-white/50">
          {items.length} rappel{items.length > 1 ? "s" : ""}
        </span>
      </div>

      <ul className="mt-3 space-y-1.5">
        {items.map((it) => {
          const Icon = pickIcon(it.next_action_label);
          const { text: whenText, tone } = formatWhen(it.next_action_at!);
          return (
            <li key={it.id} className="flex items-stretch gap-1">
              <div
                className={`flex flex-1 items-center gap-3 rounded-lg border px-3 py-2 ${tone}`}
              >
                <Icon className="h-4 w-4" />
                <div className="min-w-0 flex-1">
                  <div className="flex items-baseline gap-2">
                    <span className="text-sm font-semibold text-white">
                      {it.next_action_label || "Suivi"}
                    </span>
                    <span className="text-[11px] uppercase tracking-wider opacity-80">
                      {whenText}
                    </span>
                  </div>
                  <div className="text-[11px] text-white/50">
                    {new Date(it.next_action_at!).toLocaleString("fr-CA", {
                      weekday: "short",
                      day: "2-digit",
                      month: "short",
                      hour: "2-digit",
                      minute: "2-digit",
                    })}
                    {it.notes ? (
                      <span className="ml-2 text-white/40 italic">
                        — {it.notes.slice(0, 60)}
                        {it.notes.length > 60 ? "…" : ""}
                      </span>
                    ) : null}
                  </div>
                </div>
              </div>
              <button
                type="button"
                onClick={() => markDone(it.id)}
                disabled={busyId === it.id}
                className="inline-flex items-center gap-1 rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-2 text-xs font-semibold text-emerald-300 hover:bg-emerald-500/20 disabled:opacity-60"
                title="Marquer comme fait"
              >
                {busyId === it.id ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Check className="h-3.5 w-3.5" />
                )}
                Fait
              </button>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
