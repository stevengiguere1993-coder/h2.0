"use client";

import { useEffect, useState } from "react";
import {
  ArrowRight,
  Check,
  Mail,
  MessageSquare,
  Phone
} from "lucide-react";

import { authedFetch } from "@/lib/auth";

type Channel = "call" | "email" | "sms";

type PlanStep = {
  position: number;
  channel: Channel;
  label: string;
  delay_days: number;
  state: "done" | "current" | "upcoming";
};

type Plan = {
  status: "none" | "active" | "done" | "stopped";
  next_at: string | null;
  current_index: number | null;
  steps: PlanStep[];
};

const CHAN: Record<Channel, { label: string; icon: typeof Phone }> = {
  call: { label: "Appel", icon: Phone },
  email: { label: "Courriel", icon: Mail },
  sms: { label: "SMS", icon: MessageSquare }
};

function fmt(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("fr-CA", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit"
  });
}

/** Affiche la séquence de relance prévue pour un lead : étapes faites,
 *  en cours, et à venir. Masqué s'il n'y a aucune cadence. */
export function RelancePlanCard({
  contactRequestId
}: {
  contactRequestId: number;
}) {
  const [plan, setPlan] = useState<Plan | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await authedFetch(
          `/api/v1/relances/plan/${contactRequestId}`
        );
        if (res.ok && !cancelled) setPlan((await res.json()) as Plan);
      } catch {
        /* ignore */
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [contactRequestId]);

  if (loading || !plan || plan.steps.length === 0) return null;

  const statusLabel =
    plan.status === "active"
      ? "En cours"
      : plan.status === "done"
      ? "Terminée"
      : plan.status === "stopped"
      ? "Arrêtée (réponse reçue / engagé)"
      : "Pas encore démarrée";

  return (
    <section className="rounded-xl border border-brand-800 bg-brand-900 p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm font-semibold uppercase tracking-wider text-accent-500">
          Relances prévues
        </h3>
        <span className="text-[11px] text-white/60">
          {statusLabel}
          {plan.status === "active" && plan.next_at
            ? ` · prochaine ${fmt(plan.next_at)}`
            : ""}
        </span>
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        {plan.steps.map((s, i) => {
          const meta = CHAN[s.channel];
          const Icon = meta.icon;
          const tone =
            s.state === "done"
              ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-200"
              : s.state === "current"
              ? "border-accent-500 bg-accent-500/10 text-accent-300"
              : "border-brand-800 bg-brand-950 text-white/50";
          return (
            <div key={i} className="flex items-center gap-2">
              <div
                className={`flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-xs ${tone}`}
              >
                {s.state === "done" ? (
                  <Check className="h-3.5 w-3.5" />
                ) : (
                  <Icon className="h-3.5 w-3.5" />
                )}
                <span className="font-semibold">{meta.label}</span>
                <span className="opacity-70">· {s.label}</span>
              </div>
              {i < plan.steps.length - 1 ? (
                <ArrowRight className="h-3.5 w-3.5 text-white/30" />
              ) : null}
            </div>
          );
        })}
      </div>
    </section>
  );
}
