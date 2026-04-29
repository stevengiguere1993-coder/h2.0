"use client";

import { useEffect, useMemo, useState } from "react";
import {
  CalendarClock,
  ClipboardCheck,
  Eye,
  FileSignature,
  Home,
  Loader2,
} from "lucide-react";

import { Link } from "@/i18n/navigation";
import { authedFetch } from "@/lib/auth";

type Milestone = {
  pa_id: number;
  pa_reference: string;
  lead_id: number;
  lead_name: string | null;
  property_address: string | null;
  kind: "visite" | "inspection" | "acceptance" | "occupation" | "acte";
  label: string;
  when: string; // ISO date
  status: string;
};

const KIND_ICON: Record<Milestone["kind"], React.ReactNode> = {
  visite: <Eye className="h-3.5 w-3.5" />,
  inspection: <ClipboardCheck className="h-3.5 w-3.5" />,
  acceptance: <FileSignature className="h-3.5 w-3.5" />,
  occupation: <Home className="h-3.5 w-3.5" />,
  acte: <CalendarClock className="h-3.5 w-3.5" />,
};

const KIND_COLOR: Record<Milestone["kind"], string> = {
  visite: "text-blue-300 bg-blue-500/10",
  inspection: "text-amber-300 bg-amber-500/10",
  acceptance: "text-rose-300 bg-rose-500/10",
  occupation: "text-emerald-300 bg-emerald-500/10",
  acte: "text-violet-300 bg-violet-500/10",
};

function fmtDay(iso: string): string {
  const d = new Date(iso + "T00:00:00");
  return d.toLocaleDateString("fr-CA", {
    weekday: "short",
    day: "numeric",
    month: "short",
  });
}

function daysUntil(iso: string): number {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const target = new Date(iso + "T00:00:00");
  return Math.round((target.getTime() - today.getTime()) / 86400000);
}

export function PAMilestonesWidget({ days = 7 }: { days?: number }) {
  const [items, setItems] = useState<Milestone[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancel = false;
    void (async () => {
      setLoading(true);
      try {
        const res = await authedFetch(
          `/api/v1/prospection/pa-milestones?days=${days}`
        );
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = (await res.json()) as Milestone[];
        if (!cancel) setItems(data);
      } catch {
        if (!cancel) setItems([]);
      } finally {
        if (!cancel) setLoading(false);
      }
    })();
    return () => {
      cancel = true;
    };
  }, [days]);

  // Bucketing par jour pour affichage chrono
  const grouped = useMemo(() => {
    const map = new Map<string, Milestone[]>();
    for (const m of items) {
      const list = map.get(m.when) || [];
      list.push(m);
      map.set(m.when, list);
    }
    return Array.from(map.entries()).sort(([a], [b]) => (a < b ? -1 : 1));
  }, [items]);

  if (loading) {
    return (
      <section className="rounded-xl border border-brand-800 bg-brand-900 p-4">
        <div className="flex items-center gap-2 text-xs text-white/50">
          <Loader2 className="h-3.5 w-3.5 animate-spin" /> Chargement des
          échéances PA…
        </div>
      </section>
    );
  }

  if (items.length === 0) return null;

  return (
    <section className="rounded-xl border border-amber-500/30 bg-amber-500/5 p-4">
      <div className="flex items-center justify-between gap-2">
        <h2 className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wider text-amber-300">
          <CalendarClock className="h-4 w-4" />
          Prochaines échéances PA ({days} jours)
        </h2>
        <span className="text-xs text-white/50">
          {items.length} échéance{items.length > 1 ? "s" : ""}
        </span>
      </div>

      <ul className="mt-3 space-y-3">
        {grouped.map(([day, list]) => {
          const delta = daysUntil(day);
          const deltaLabel =
            delta === 0
              ? "Aujourd'hui"
              : delta === 1
                ? "Demain"
                : `Dans ${delta} j`;
          return (
            <li key={day}>
              <div className="mb-1 flex items-baseline gap-2">
                <span className="text-xs font-bold uppercase tracking-wider text-white/80">
                  {fmtDay(day)}
                </span>
                <span className="text-[10px] text-white/40">{deltaLabel}</span>
              </div>
              <ul className="space-y-1.5">
                {list.map((m, i) => (
                  <li key={`${m.pa_id}-${m.kind}-${i}`}>
                    <Link
                      // eslint-disable-next-line @typescript-eslint/no-explicit-any
                      href={`/prospection/${m.lead_id}` as any}
                      className="flex items-center gap-2 rounded-lg border border-brand-800 bg-brand-950/40 px-3 py-2 text-xs hover:border-amber-500/30"
                    >
                      <span
                        className={`inline-flex h-6 w-6 items-center justify-center rounded ${
                          KIND_COLOR[m.kind]
                        }`}
                      >
                        {KIND_ICON[m.kind]}
                      </span>
                      <div className="flex-1">
                        <div className="font-medium text-white">{m.label}</div>
                        <div className="text-white/50">
                          {m.property_address || m.lead_name || "—"}
                          <span className="ml-2 font-mono text-[10px] text-white/40">
                            {m.pa_reference}
                          </span>
                        </div>
                      </div>
                    </Link>
                  </li>
                ))}
              </ul>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
