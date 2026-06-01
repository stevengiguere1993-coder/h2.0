"use client";

import { useCallback, useEffect, useState } from "react";
import {
  AlarmClock,
  Calendar,
  CheckCircle2,
  ChevronRight,
  Clock,
  DollarSign,
  Loader2,
  MapPin,
  Palmtree,
  Play,
  Square,
  X,
  XCircle
} from "lucide-react";

import { Link, useRouter } from "@/i18n/navigation";
import { authedFetch } from "@/lib/auth";

type EmployeMini = {
  id: number;
  full_name: string;
  email: string | null;
  role: string | null;
  hourly_rate: number | null;
};

type OpenPunch = {
  id: number;
  started_at: string;
  project_id: number | null;
  task: string | null;
};

type EventMini = {
  id: number;
  title: string;
  description: string | null;
  location: string | null;
  start_at: string;
  end_at: string | null;
  all_day: boolean;
  project_id: number | null;
  event_type: string;
};

type WeekStats = {
  hours_worked: number;
  hours_target: number;
  revenue: number;
  revenue_target: number;
  shifts_approved: number;
  shifts_pending: number;
};

type MobileMe = {
  user_email: string;
  employe: EmployeMini | null;
  open_punch: OpenPunch | null;
  current_event: EventMini | null;
  next_event: EventMini | null;
  week: WeekStats;
};

function money(n: number): string {
  return new Intl.NumberFormat("fr-CA", {
    style: "currency",
    currency: "CAD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2
  }).format(n);
}

function formatDayLong(d: Date): string {
  return d.toLocaleDateString("fr-CA", {
    weekday: "long",
    day: "numeric",
    month: "long",
    year: "numeric"
  });
}

function formatEventWhen(start: string, end: string | null): string {
  const s = new Date(start);
  const sameDay =
    end && new Date(end).toDateString() === s.toDateString();
  const dateFmt = s.toLocaleDateString("fr-CA", {
    weekday: "short",
    day: "numeric",
    month: "short"
  });
  const startHm = s.toLocaleTimeString("fr-CA", {
    hour: "2-digit",
    minute: "2-digit"
  });
  if (!end) return `${dateFmt} · ${startHm}`;
  const endHm = new Date(end).toLocaleTimeString("fr-CA", {
    hour: "2-digit",
    minute: "2-digit"
  });
  return sameDay
    ? `${dateFmt} · ${startHm} → ${endHm}`
    : `${dateFmt} · ${startHm} …`;
}

// Heures décimales → « h/min » (ex. 7.89 → « 7 h 53 »), plus lisible
// qu'un décimal pour un relevé de temps.
function fmtHm(h: number | null | undefined): string {
  if (h == null) return "—";
  const totalMin = Math.round(h * 60);
  const hh = Math.floor(totalMin / 60);
  const mm = totalMin % 60;
  return `${hh} h ${String(mm).padStart(2, "0")}`;
}

export default function MobileHome() {
  const router = useRouter();
  const [data, setData] = useState<MobileMe | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [punchBusy, setPunchBusy] = useState(false);
  // Most recent leave decision (pending/approved/rejected), shown as a
  // banner on the home so employees see the outcome without having to
  // dig through menus.
  const [recentLeave, setRecentLeave] = useState<{
    id: number;
    status: "pending" | "approved" | "rejected" | "cancelled";
    start_at: string;
    end_at: string;
    review_note: string | null;
  } | null>(null);
  const [dismissedLeaveIds, setDismissedLeaveIds] = useState<Set<number>>(
    () => {
      if (typeof window === "undefined") return new Set();
      try {
        const raw = window.localStorage.getItem("hsi-dismissed-leaves");
        return new Set(raw ? (JSON.parse(raw) as number[]) : []);
      } catch {
        return new Set();
      }
    }
  );

  function dismissLeave(id: number) {
    setDismissedLeaveIds((prev) => {
      const next = new Set(prev);
      next.add(id);
      try {
        window.localStorage.setItem(
          "hsi-dismissed-leaves",
          JSON.stringify(Array.from(next))
        );
      } catch {
        // ignore storage errors
      }
      return next;
    });
  }

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [meRes, leavesRes] = await Promise.all([
        authedFetch("/api/v1/mobile/me"),
        authedFetch("/api/v1/leaves/mine?limit=1")
      ]);
      if (!meRes.ok) throw new Error(`http_${meRes.status}`);
      setData((await meRes.json()) as MobileMe);
      if (leavesRes.ok) {
        const rows = (await leavesRes.json()) as Array<{
          id: number;
          status: "pending" | "approved" | "rejected" | "cancelled";
          start_at: string;
          end_at: string;
          review_note: string | null;
        }>;
        setRecentLeave(rows[0] || null);
      }
    } catch {
      setError("Chargement échoué.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  // punchStart was removed from the home — users now go to /m/punch
  // where they pick a context (project / prospect / admin) before
  // starting. See the <Link /> on the "Poinçonner" button below.

  async function punchStop() {
    setPunchBusy(true);
    try {
      // Best-effort geo capture pour ajouter le lieu d'arrêt à
      // l'historique. Pas bloquant si l'utilisateur refuse / pas dispo.
      let geo: string | null = null;
      if (typeof navigator !== "undefined" && navigator.geolocation) {
        geo = await new Promise<string | null>((resolve) => {
          const timeoutId = setTimeout(() => resolve(null), 6000);
          navigator.geolocation.getCurrentPosition(
            (pos) => {
              clearTimeout(timeoutId);
              const { latitude, longitude } = pos.coords;
              resolve(
                `${latitude.toFixed(6)},${longitude.toFixed(6)}`
              );
            },
            () => {
              clearTimeout(timeoutId);
              resolve(null);
            },
            {
              enableHighAccuracy: true,
              timeout: 5000,
              maximumAge: 30000
            }
          );
        });
      }
      const res = await authedFetch("/api/v1/mobile/punch/stop", {
        method: "POST",
        body: JSON.stringify(geo ? { geolocation: geo } : {})
      });
      if (!res.ok) throw new Error();
      await load();
    } catch {
      setError("Arrêt du punch échoué.");
    } finally {
      setPunchBusy(false);
    }
  }

  const today = new Date();
  const inService = !!data?.open_punch;

  return (
    <>
      <Topbar
        title="Profil"
        right={
          <span
            className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${
              inService
                ? "bg-emerald-500/20 text-emerald-300"
                : "bg-rose-500/15 text-rose-300"
            }`}
          >
            {inService ? "En service" : "Pas en service"}
          </span>
        }
      />

      <div className="space-y-4 p-4">
        {error ? (
          <p className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
            {error}
          </p>
        ) : null}

        {recentLeave && !dismissedLeaveIds.has(recentLeave.id) ? (
          <LeaveBanner
            leave={recentLeave}
            onDismiss={() => dismissLeave(recentLeave.id)}
          />
        ) : null}

        {/* Profile card */}
        <section className="rounded-2xl border border-brand-800 bg-brand-900 p-4">
          <div className="flex items-center gap-3">
            <Avatar name={data?.employe?.full_name || data?.user_email || "?"} />
            <div>
              <p className="text-sm text-accent-500">
                Bienvenue, {firstName(data?.employe?.full_name) || ""}
              </p>
              <p className="mt-0.5 text-xs text-white/50">
                {formatDayLong(today)}
              </p>
            </div>
          </div>
        </section>

        {loading ? (
          <div className="flex items-center justify-center py-10">
            <Loader2 className="h-5 w-5 animate-spin text-white/40" />
          </div>
        ) : (
          <>
            {/* Current event */}
            <section className="rounded-2xl border border-brand-800 bg-brand-900 p-4">
              <p className="flex items-center gap-2 text-xs uppercase tracking-wider text-white/50">
                <MapPin className="h-3.5 w-3.5 text-accent-500" /> Événement
                actuel
              </p>
              {data?.current_event ? (
                <EventLine event={data.current_event} />
              ) : (
                <p className="mt-2 text-sm text-white/60">
                  Aucun événement en cours
                </p>
              )}
            </section>

            {/* Next event */}
            <section className="rounded-2xl border border-brand-800 bg-brand-900 p-4">
              <p className="flex items-center gap-2 text-xs uppercase tracking-wider text-white/50">
                <Calendar className="h-3.5 w-3.5 text-accent-500" /> Prochain
                événement
              </p>
              {data?.next_event ? (
                <EventLine event={data.next_event} />
              ) : (
                <p className="mt-2 text-sm text-white/60">
                  Plus d&apos;événements aujourd&apos;hui
                </p>
              )}
            </section>

            {/* Week stats */}
            <section className="rounded-2xl border border-brand-800 bg-brand-900 p-4">
              <p className="flex items-center gap-2 text-xs uppercase tracking-wider text-white/50">
                <Clock className="h-3.5 w-3.5 text-accent-500" /> Cette
                semaine
              </p>
              <div className="mt-3 space-y-3">
                <StatBar
                  icon={Clock}
                  label="Heures travaillées"
                  value={fmtHm(data?.week.hours_worked)}
                  sub={`de ${data?.week.hours_target.toFixed(0)}h`}
                  pct={percent(
                    data?.week.hours_worked || 0,
                    data?.week.hours_target || 1
                  )}
                />
                <StatBar
                  icon={DollarSign}
                  label="Revenus"
                  value={money(data?.week.revenue || 0)}
                  sub={`de ${money(data?.week.revenue_target || 0)}`}
                  pct={percent(
                    data?.week.revenue || 0,
                    data?.week.revenue_target || 1
                  )}
                />
                <div className="grid grid-cols-2 gap-3 pt-1">
                  <InfoTile
                    icon={CheckCircle2}
                    tone="emerald"
                    label="Shifts approuvés"
                    value={String(data?.week.shifts_approved || 0)}
                  />
                  <InfoTile
                    icon={AlarmClock}
                    tone="amber"
                    label="Shifts en attente"
                    value={String(data?.week.shifts_pending || 0)}
                  />
                </div>
              </div>
            </section>

            {/* Quick actions */}
            <section className="space-y-3">
              <p className="flex items-center gap-2 text-xs uppercase tracking-wider text-white/50">
                ⚡ Actions rapides
              </p>
              {inService ? (
                <button
                  type="button"
                  onClick={punchStop}
                  disabled={punchBusy}
                  className="flex w-full items-center justify-center gap-2 rounded-xl bg-rose-500 px-5 py-4 text-base font-bold text-white disabled:opacity-60"
                >
                  {punchBusy ? (
                    <Loader2 className="h-5 w-5 animate-spin" />
                  ) : (
                    <Square className="h-5 w-5" />
                  )}
                  Arrêter le punch
                </button>
              ) : (
                <Link
                  // eslint-disable-next-line @typescript-eslint/no-explicit-any
                  href={"/m/punch" as any}
                  className="flex w-full items-center justify-center gap-2 rounded-xl bg-blue-500 px-5 py-4 text-base font-bold text-white"
                >
                  <Play className="h-5 w-5" />
                  Poinçonner
                </Link>
              )}
              <Link
                // eslint-disable-next-line @typescript-eslint/no-explicit-any
                href={"/m/agenda" as any}
                className="flex w-full items-center justify-center gap-2 rounded-xl bg-violet-500 px-5 py-4 text-base font-bold text-white"
              >
                <Calendar className="h-5 w-5" /> Voir l&apos;agenda
              </Link>
              <Link
                // eslint-disable-next-line @typescript-eslint/no-explicit-any
                href={"/m/conge" as any}
                className="flex w-full items-center justify-center gap-2 rounded-xl bg-accent-500 px-5 py-4 text-base font-bold text-brand-950"
              >
                <Palmtree className="h-5 w-5" /> Demander un congé
              </Link>
            </section>
          </>
        )}
      </div>
    </>
  );
}

function Topbar({
  title,
  right
}: {
  title: string;
  right?: React.ReactNode;
}) {
  return (
    <header
      className="sticky top-0 z-30 flex items-center justify-between gap-3 border-b border-brand-800 bg-brand-950/95 px-4 py-3 backdrop-blur"
      style={{ paddingTop: "max(env(safe-area-inset-top), 0.75rem)" }}
    >
      <h1 className="text-base font-bold text-white">{title}</h1>
      {right}
    </header>
  );
}

function Avatar({ name }: { name: string }) {
  const initials = name
    .split(/[\s.@]+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((s) => s[0]?.toUpperCase() || "")
    .join("");
  return (
    <span className="flex h-12 w-12 items-center justify-center rounded-full bg-accent-500/20 text-sm font-bold text-accent-500">
      {initials || "?"}
    </span>
  );
}

function firstName(full: string | undefined | null): string {
  if (!full) return "";
  return full.split(" ")[0] || full;
}

function percent(value: number, target: number): number {
  if (target <= 0) return 0;
  return Math.min(100, Math.max(0, (value / target) * 100));
}

function StatBar({
  icon: Icon,
  label,
  value,
  sub,
  pct
}: {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  value: string;
  sub: string;
  pct: number;
}) {
  return (
    <div>
      <div className="flex items-center justify-between">
        <span className="flex items-center gap-1.5 text-xs text-white/60">
          <Icon className="h-3.5 w-3.5" /> {label}
        </span>
        <span className="text-xs text-white/50">{sub}</span>
      </div>
      <p className="mt-1 text-lg font-bold text-white">{value}</p>
      <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-brand-950">
        <div
          className="h-full bg-emerald-500 transition-all"
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

function InfoTile({
  icon: Icon,
  tone,
  label,
  value
}: {
  icon: React.ComponentType<{ className?: string }>;
  tone: "emerald" | "amber";
  label: string;
  value: string;
}) {
  const toneMap: Record<string, string> = {
    emerald: "text-emerald-300 bg-emerald-500/10",
    amber: "text-amber-300 bg-amber-500/10"
  };
  return (
    <div
      className={`flex items-center gap-2 rounded-lg px-3 py-2 ${toneMap[tone]}`}
    >
      <Icon className="h-4 w-4" />
      <div>
        <p className="text-[10px] uppercase tracking-wider text-white/60">
          {label}
        </p>
        <p className="text-sm font-bold">{value}</p>
      </div>
    </div>
  );
}

function EventLine({ event: e }: { event: EventMini }) {
  const href = e.project_id
    ? `/m/intervention/${e.id}`
    : `/m/intervention/${e.id}`;
  return (
    <Link
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      href={href as any}
      className="mt-2 flex items-center justify-between gap-2"
    >
      <div className="min-w-0">
        <p className="truncate text-sm font-semibold text-white">
          {e.title}
        </p>
        <p className="mt-0.5 text-xs text-white/50">
          {formatEventWhen(e.start_at, e.end_at)}
        </p>
        {e.location ? (
          <p className="mt-0.5 truncate text-xs text-white/50">
            📍 {e.location}
          </p>
        ) : null}
      </div>
      <ChevronRight className="h-4 w-4 flex-shrink-0 text-white/30" />
    </Link>
  );
}

function LeaveBanner({
  leave,
  onDismiss
}: {
  leave: {
    id: number;
    status: "pending" | "approved" | "rejected" | "cancelled";
    start_at: string;
    end_at: string;
    review_note: string | null;
  };
  onDismiss: () => void;
}) {
  if (leave.status === "cancelled") return null;
  const when =
    new Date(leave.start_at).toDateString() ===
    new Date(leave.end_at).toDateString()
      ? new Date(leave.start_at).toLocaleDateString("fr-CA", {
          day: "numeric",
          month: "long"
        })
      : `${new Date(leave.start_at).toLocaleDateString("fr-CA", {
          day: "numeric",
          month: "short"
        })} → ${new Date(leave.end_at).toLocaleDateString("fr-CA", {
          day: "numeric",
          month: "short"
        })}`;

  const config =
    leave.status === "pending"
      ? {
          tone: "border-amber-500/40 bg-amber-500/10 text-amber-200",
          Icon: Palmtree,
          title: "Demande de congé en attente",
          sub: `${when} · en attente d'approbation`
        }
      : leave.status === "approved"
        ? {
            tone:
              "border-emerald-500/40 bg-emerald-500/10 text-emerald-200",
            Icon: CheckCircle2,
            title: "Congé approuvé ✅",
            sub: `${when}${leave.review_note ? ` · ${leave.review_note}` : ""}`
          }
        : {
            tone: "border-rose-500/40 bg-rose-500/10 text-rose-200",
            Icon: XCircle,
            title: "Demande de congé refusée",
            sub: `${when}${leave.review_note ? ` · ${leave.review_note}` : ""}`
          };

  const { Icon } = config;
  return (
    <div
      className={`relative flex items-center gap-3 rounded-xl border p-3 ${config.tone}`}
    >
      <Icon className="h-5 w-5 flex-shrink-0" />
      <Link
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        href={"/m/conges" as any}
        className="flex min-w-0 flex-1 items-center gap-2"
      >
        <div className="flex-1 min-w-0 pr-6">
          <p className="text-sm font-semibold">{config.title}</p>
          <p className="mt-0.5 text-xs opacity-80">{config.sub}</p>
        </div>
        <ChevronRight className="h-4 w-4 flex-shrink-0 opacity-60" />
      </Link>
      <button
        type="button"
        onClick={onDismiss}
        aria-label="Fermer"
        className="absolute right-2 top-2 flex h-6 w-6 items-center justify-center rounded-full text-current opacity-70 transition hover:bg-white/10 hover:opacity-100"
      >
        <X className="h-4 w-4" />
      </button>
    </div>
  );
}
