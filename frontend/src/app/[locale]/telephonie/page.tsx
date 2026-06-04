"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  Bot,
  Building2,
  CheckCircle2,
  Clock,
  Filter,
  Home,
  MessageSquare,
  Phone,
  PhoneCall,
  PhoneForwarded,
  PhoneIncoming,
  PhoneOff,
  RefreshCw,
  Send,
  ShieldCheck,
  Sparkles,
  TrendingUp,
  Users,
  Workflow,
  X
} from "lucide-react";

import { authedFetch, getMe, getToken } from "@/lib/auth";
import { Link, useRouter } from "@/i18n/navigation";
import { AppTopbar } from "@/components/app-topbar";
import { CallButton } from "@/components/call-button";
import { DialPad } from "@/components/dial-pad";
import { DialPadFab } from "@/components/dial-pad-fab";
import { PushNotificationsToggle } from "@/components/push-notifications-toggle";
import { RecordingPlayer } from "@/components/recording-player";
import { PageDriveSection } from "@/components/drive/PageDriveSection";
import { useTelephonieLayout } from "./_client-shell";

// Volet « Téléphonie / Secrétaire d'appels » — interface premium.
//
// Sections (tabs) :
//   1. Tableau de bord — KPIs du jour + activité live + plan
//   2. Appels — journal complet avec drawer de détail + transcription
//   3. Numéros — toggles secrétaire / rappel auto / forward / état
//   4. Filtres — blocklist + VIP whitelist
//   5. Heures — plages d'ouverture hebdomadaires
//
// L'accès reste gated par email pour l'instant (sgiguere) — sera
// remplacé par un rôle dédié quand le volet sortira en GA.

const TELEPHONIE_ALLOWED_EMAILS = ["sgiguere@immohorizon.com"];

type Me = { email?: string | null; role?: string | null };

import type { TelephonieSection as Section } from "./_client-shell";

type SmsThread = {
  peer_e164: string;
  last_message: {
    id: number;
    direction: string;
    body: string | null;
    received_at: string;
    num_media: number;
  };
  caller_kind: string | null;
  entity_type: string | null;
  entity_id: number | null;
  unread: number;
};

type SmsRow = {
  id: number;
  phone_number_id: number;
  provider_sid: string;
  direction: string;
  status: string;
  from_e164: string;
  to_e164: string;
  body: string | null;
  media_urls: string | null;
  num_media: number;
  received_at: string;
  sent_at: string | null;
  caller_kind: string | null;
  entity_type: string | null;
  entity_id: number | null;
  sent_by_user_id: number | null;
  read_at: string | null;
};

type PhoneNumberRow = {
  id: number;
  e164: string;
  provider: string;
  label: string | null;
  forward_to_e164: string | null;
  urgency_forward_e164: string | null;
  closer_forward_e164: string | null;
  followup_forward_e164: string | null;
  secretary_mode_active: boolean;
  lead_auto_callback_enabled: boolean;
  owner_user_id: number | null;
  active: boolean;
};

type CallRow = {
  id: number;
  phone_number_id: number;
  direction: string;
  status: string;
  from_e164: string;
  to_e164: string;
  forwarded_to_e164: string | null;
  started_at: string;
  answered_at: string | null;
  ended_at: string | null;
  duration_sec: number | null;
  lang: string;
  intent: string | null;
  lead_name: string | null;
  lead_callback_phone: string | null;
  lead_reason: string | null;
  contact_request_id: number | null;
  was_blocked: boolean;
  was_vip: boolean;
  was_voicemail: boolean;
  voicemail_transcription: string | null;
  voicemail_summary: string | null;
  recording_url: string | null;
  entity_type: string | null;
  entity_id: number | null;
  followup_suggestion: string | null;
  caller_kind: string | null;
};

type CallTurnRow = {
  id: number;
  turn_index: number;
  role: string;
  text: string;
  confidence: number | null;
  created_at: string;
};

type FilterRow = {
  id: number;
  phone_number_id: number;
  kind: "block" | "vip" | string;
  pattern: string | null;
  label: string | null;
  active: boolean;
};

type BusinessHoursRow = {
  id: number;
  phone_number_id: number;
  day_of_week: number;
  open_time: string;
  close_time: string;
  timezone: string;
};

type UsageDay = {
  usage_date: string;
  cents_spent: number;
  calls_count: number;
  spam_blocked: number;
};

export default function TelephonieHome() {
  const router = useRouter();
  const { onOpenSidebar } = useTelephonieLayout();
  const [checking, setChecking] = useState(true);
  const [allowed, setAllowed] = useState(false);
  // Section vit dans le contexte du layout pour que la sidebar la
  // contrôle aussi (cohérence avec les autres volets).
  const { section, setSection } = useTelephonieLayout();

  const [numbers, setNumbers] = useState<PhoneNumberRow[]>([]);
  const [calls, setCalls] = useState<CallRow[]>([]);
  const [filters, setFilters] = useState<FilterRow[]>([]);
  const [hours, setHours] = useState<BusinessHoursRow[]>([]);
  const [usage, setUsage] = useState<UsageDay | null>(null);
  const [smsThreads, setSmsThreads] = useState<SmsThread[]>([]);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [drawerCallId, setDrawerCallId] = useState<number | null>(null);
  const [turnsByCallId, setTurnsByCallId] = useState<
    Record<number, CallTurnRow[]>
  >({});
  const [search, setSearch] = useState("");

  const reload = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const [nRes, cRes, fRes, uRes, sRes] = await Promise.all([
        authedFetch("/api/v1/voice/phone-numbers"),
        authedFetch("/api/v1/voice/calls?limit=100"),
        authedFetch("/api/v1/voice/filters"),
        authedFetch("/api/v1/voice/usage/today"),
        authedFetch("/api/v1/voice/sms/threads?limit=80")
      ]);
      if (!nRes.ok) throw new Error(`numbers http_${nRes.status}`);
      if (!cRes.ok) throw new Error(`calls http_${cRes.status}`);
      if (!fRes.ok) throw new Error(`filters http_${fRes.status}`);
      const nums = (await nRes.json()) as PhoneNumberRow[];
      setNumbers(nums);
      setCalls((await cRes.json()) as CallRow[]);
      setFilters((await fRes.json()) as FilterRow[]);
      if (uRes.ok) setUsage((await uRes.json()) as UsageDay);
      if (sRes.ok) setSmsThreads((await sRes.json()) as SmsThread[]);
      if (nums.length > 0) {
        const hRes = await authedFetch(
          `/api/v1/voice/business-hours?phone_number_id=${nums[0].id}`
        );
        if (hRes.ok) setHours((await hRes.json()) as BusinessHoursRow[]);
      }
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  const patchNumber = useCallback(
    async (n: PhoneNumberRow, patch: Partial<PhoneNumberRow>) => {
      setNumbers((prev) =>
        prev.map((row) => (row.id === n.id ? { ...row, ...patch } : row))
      );
      try {
        const res = await authedFetch(`/api/v1/voice/phone-numbers/${n.id}`, {
          method: "PATCH",
          body: JSON.stringify(patch)
        });
        if (!res.ok) throw new Error(`http_${res.status}`);
      } catch (err) {
        setNumbers((prev) => prev.map((row) => (row.id === n.id ? n : row)));
        setLoadError(err instanceof Error ? err.message : String(err));
      }
    },
    []
  );

  const toggleSecretary = useCallback(
    (n: PhoneNumberRow) =>
      patchNumber(n, { secretary_mode_active: !n.secretary_mode_active }),
    [patchNumber]
  );

  const toggleAutoCallback = useCallback(
    async (n: PhoneNumberRow) => {
      const next = !n.lead_auto_callback_enabled;
      if (
        next &&
        !window.confirm(
          "Activer le rappel auto va faire que Léa appelle automatiquement " +
            "tout nouveau lead avec un téléphone, dans les 60 secondes après " +
            "la création de la fiche.\n\n" +
            "Es-tu sûr d'avoir testé la secrétaire IA et que tout fonctionne ?"
        )
      ) {
        return;
      }
      await patchNumber(n, { lead_auto_callback_enabled: next });
    },
    [patchNumber]
  );

  const addFilter = useCallback(
    async (
      phoneNumberId: number,
      kind: "block" | "vip",
      pattern: string,
      label: string
    ) => {
      const res = await authedFetch("/api/v1/voice/filters", {
        method: "POST",
        body: JSON.stringify({
          phone_number_id: phoneNumberId,
          kind,
          pattern: pattern.trim() || null,
          label: label.trim() || null
        })
      });
      if (!res.ok) {
        setLoadError(`add filter http_${res.status}`);
        return;
      }
      const f = (await res.json()) as FilterRow;
      setFilters((prev) => [...prev, f]);
    },
    []
  );

  const deleteFilter = useCallback(async (filterId: number) => {
    const res = await authedFetch(`/api/v1/voice/filters/${filterId}`, {
      method: "DELETE"
    });
    if (!res.ok && res.status !== 204) {
      setLoadError(`del filter http_${res.status}`);
      return;
    }
    setFilters((prev) => prev.filter((f) => f.id !== filterId));
  }, []);

  const saveHours = useCallback(
    async (
      phoneNumberId: number,
      rows: { day_of_week: number; open_time: string; close_time: string }[]
    ) => {
      const res = await authedFetch("/api/v1/voice/business-hours", {
        method: "PUT",
        body: JSON.stringify({
          phone_number_id: phoneNumberId,
          hours: rows.map((r) => ({ ...r, timezone: "America/Montreal" }))
        })
      });
      if (!res.ok) {
        setLoadError(`save hours http_${res.status}`);
        return;
      }
      setHours((await res.json()) as BusinessHoursRow[]);
    },
    []
  );

  const openDrawer = useCallback(
    async (callId: number) => {
      setDrawerCallId(callId);
      if (turnsByCallId[callId]) return;
      try {
        const res = await authedFetch(`/api/v1/voice/calls/${callId}/turns`);
        if (!res.ok) return;
        const data = (await res.json()) as CallTurnRow[];
        setTurnsByCallId((prev) => ({ ...prev, [callId]: data }));
      } catch {
        /* ignore */
      }
    },
    [turnsByCallId]
  );

  useEffect(() => {
    let cancelled = false;
    async function check() {
      const tok = getToken();
      if (!tok) {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        router.replace("/connexion" as any);
        return;
      }
      try {
        const me = (await getMe(tok)) as Me;
        const email = (me?.email || "").toLowerCase().trim();
        const role = (me?.role || "").toLowerCase().trim();
        // Owner & admin = accès total ; sinon whitelist email héritée.
        const ok =
          role === "owner" ||
          role === "admin" ||
          TELEPHONIE_ALLOWED_EMAILS.includes(email);
        if (!cancelled) {
          setAllowed(ok);
          setChecking(false);
          if (ok) void reload();
        }
      } catch {
        if (!cancelled) {
          setAllowed(false);
          setChecking(false);
        }
      }
    }
    void check();
    return () => {
      cancelled = true;
    };
  }, [router, reload]);

  if (checking) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-brand-950">
        <p className="text-sm text-white/50">Chargement…</p>
      </div>
    );
  }

  if (!allowed) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-brand-950 p-6">
        <div className="max-w-md rounded-2xl border border-rose-500/40 bg-rose-500/10 p-6 text-center">
          <AlertTriangle className="mx-auto mb-2 h-6 w-6 text-rose-300" />
          <h1 className="text-base font-bold text-white">Accès restreint</h1>
          <p className="mt-2 text-xs text-rose-200">
            Le volet Téléphonie est en cours de développement et n&apos;est
            pas encore disponible pour ton compte.
          </p>
          <Link
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            href={"/connexion" as any}
            className="mt-4 inline-flex items-center gap-1.5 text-xs text-rose-200 hover:underline"
          >
            Retour
          </Link>
        </div>
      </div>
    );
  }

  const primaryNumber = numbers[0];
  const drawerCall = calls.find((c) => c.id === drawerCallId) || null;

  return (
    <div className="min-h-screen bg-brand-950">
      <AppTopbar
        breadcrumbs={[{ label: "Téléphonie" }]}
        onOpenSidebar={onOpenSidebar}
        searchPlaceholder="Filtrer les appels (numéro, intent…)"
        onSearch={(q) => setSearch(q)}
      />

      <div className="mx-auto max-w-7xl px-4 pb-12 pt-5 lg:px-6">
        {/* Bouton refresh discret (la nav est dans la sidebar). */}
        <div className="mb-3 flex items-center justify-end">
          <button
            type="button"
            onClick={() => void reload()}
            disabled={loading}
            className="inline-flex items-center gap-1.5 rounded-md border border-brand-800 bg-brand-900 px-2.5 py-1 text-[11px] text-white/70 hover:text-white disabled:opacity-50"
          >
            {loading ? "Chargement…" : "↻ Rafraîchir"}
          </button>
        </div>

        {loadError ? (
          <div className="mt-3 rounded-md border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-[12px] text-rose-200">
            Erreur de chargement : {loadError}
          </div>
        ) : null}

        <PageDriveSection
          pageKey="page:telephonie:accueil"
          pole="Téléphonie"
          label="Téléphonie"
          route="/telephonie"
          className="mt-3"
        />

        {section === "dashboard" ? (
          <DashboardSection
            numbers={numbers}
            calls={calls}
            usage={usage}
            onOpenCall={openDrawer}
            onJumpTo={setSection}
            onToggleSecretary={toggleSecretary}
            onToggleAutoCallback={toggleAutoCallback}
          />
        ) : null}

        {section === "appels" ? (
          <CallsSection
            calls={calls}
            search={search}
            onOpenCall={openDrawer}
          />
        ) : null}

        {section === "messages" ? (
          <MessagesSection threads={smsThreads} onReload={() => void reload()} />
        ) : null}

        {section === "numeros" ? (
          <NumbersSection
            numbers={numbers}
            onToggleSecretary={toggleSecretary}
            onToggleAutoCallback={toggleAutoCallback}
            patchNumber={patchNumber}
          />
        ) : null}

        {section === "filtres" && primaryNumber ? (
          <FiltersSection
            phoneNumberId={primaryNumber.id}
            filters={filters.filter(
              (f) => f.phone_number_id === primaryNumber.id
            )}
            onAdd={addFilter}
            onDelete={deleteFilter}
          />
        ) : null}

        {section === "heures" && primaryNumber ? (
          <BusinessHoursSection
            phoneNumberId={primaryNumber.id}
            hours={hours}
            onSave={saveHours}
          />
        ) : null}

        {section === "plan" ? <PlanSection /> : null}
      </div>

      {drawerCall ? (
        <CallDrawer
          call={drawerCall}
          turns={turnsByCallId[drawerCall.id]}
          onClose={() => setDrawerCallId(null)}
        />
      ) : null}

      {/* Dial pad flottant (Phase 10) — bouton fixe en bas à droite. */}
      <DialPadFab />
    </div>
  );
}

// (DialPadFab a été extrait dans components/dial-pad-fab.tsx pour
// pouvoir être réutilisé dans /app/layout.tsx aussi.)

function DashboardDialButton() {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="inline-flex items-center gap-2 rounded-md bg-emerald-500 px-3 py-1.5 text-xs font-semibold text-emerald-950 transition hover:bg-emerald-400"
      >
        <Phone className="h-3.5 w-3.5" />
        Composer un numéro
      </button>
      {open ? (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
          onClick={() => setOpen(false)}
        >
          <div
            className="rounded-2xl border border-brand-800 bg-brand-900 p-5 shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          >
            <DialPad onClose={() => setOpen(false)} />
          </div>
        </div>
      ) : null}
    </>
  );
}

// ----------------------------------------------------------------------
// Section tabs
// ----------------------------------------------------------------------

function SectionTabs({
  active,
  onChange,
  onReload,
  loading
}: {
  active: Section;
  onChange: (s: Section) => void;
  onReload: () => void;
  loading: boolean;
}) {
  const items: { key: Section; label: string; icon: React.ReactNode }[] = [
    { key: "dashboard", label: "Tableau de bord", icon: <Home className="h-3.5 w-3.5" /> },
    { key: "appels", label: "Appels", icon: <PhoneCall className="h-3.5 w-3.5" /> },
    { key: "messages", label: "Messages", icon: <MessageSquare className="h-3.5 w-3.5" /> },
    { key: "numeros", label: "Numéros", icon: <Phone className="h-3.5 w-3.5" /> },
    { key: "filtres", label: "Filtres", icon: <Filter className="h-3.5 w-3.5" /> },
    { key: "heures", label: "Heures", icon: <Clock className="h-3.5 w-3.5" /> },
    { key: "plan", label: "Roadmap", icon: <Workflow className="h-3.5 w-3.5" /> }
  ];
  return (
    <div className="flex items-center gap-2 overflow-x-auto border-b border-brand-800 pb-2">
      {items.map((it) => (
        <button
          key={it.key}
          type="button"
          onClick={() => onChange(it.key)}
          className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs font-semibold transition ${
            active === it.key
              ? "border-teal-500/50 bg-teal-500/10 text-teal-200"
              : "border-brand-800 bg-brand-900 text-white/70 hover:border-brand-700 hover:text-white"
          }`}
        >
          {it.icon}
          {it.label}
        </button>
      ))}
      <button
        type="button"
        onClick={onReload}
        disabled={loading}
        className="ml-auto inline-flex items-center gap-1.5 rounded-full border border-brand-800 bg-brand-900 px-3 py-1.5 text-[11px] text-white/70 hover:border-brand-700 disabled:opacity-50"
      >
        <RefreshCw className={`h-3 w-3 ${loading ? "animate-spin" : ""}`} />
        Rafraîchir
      </button>
    </div>
  );
}

// ----------------------------------------------------------------------
// Dashboard section — KPIs + live activity
// ----------------------------------------------------------------------

function DashboardSection({
  numbers,
  calls,
  usage,
  onOpenCall,
  onJumpTo,
  onToggleSecretary,
  onToggleAutoCallback
}: {
  numbers: PhoneNumberRow[];
  calls: CallRow[];
  usage: UsageDay | null;
  onOpenCall: (id: number) => void;
  onJumpTo: (s: Section) => void;
  onToggleSecretary: (n: PhoneNumberRow) => void;
  onToggleAutoCallback: (n: PhoneNumberRow) => void;
}) {
  // Calculs KPI sur les calls (sans filtrage côté serveur, on a déjà le top 100).
  const todayStart = useMemo(() => {
    const d = new Date();
    d.setHours(0, 0, 0, 0);
    return d.getTime();
  }, []);
  const todayCalls = calls.filter(
    (c) => new Date(c.started_at).getTime() >= todayStart
  );
  const totalToday = todayCalls.length;
  const inboundToday = todayCalls.filter((c) => c.direction === "inbound").length;
  const outboundToday = todayCalls.filter((c) => c.direction === "outbound").length;
  const missedToday = todayCalls.filter(
    (c) => c.status === "no-answer" || c.status === "busy" || c.status === "failed"
  ).length;
  const aiHandledToday = todayCalls.filter(
    (c) => c.intent && c.intent !== "unclear"
  ).length;
  const voicemailToday = todayCalls.filter((c) => c.was_voicemail).length;
  const avgDuration =
    todayCalls.filter((c) => c.duration_sec).length === 0
      ? 0
      : Math.round(
          todayCalls
            .filter((c) => c.duration_sec)
            .reduce((s, c) => s + (c.duration_sec || 0), 0) /
            todayCalls.filter((c) => c.duration_sec).length
        );

  const primary = numbers[0];
  const secretaryOn = !!primary?.secretary_mode_active;
  const autoOn = !!primary?.lead_auto_callback_enabled;

  return (
    <div className="mt-5 space-y-5">
      {/* Hero — état du système + numéro */}
      <section className="rounded-2xl border border-brand-800 bg-brand-900 p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="flex items-center gap-2 text-xs uppercase tracking-wider text-teal-300">
              <PhoneCall className="h-4 w-4" />
              Ligne principale
            </div>
            <div className="mt-1 font-mono text-2xl font-bold text-white">
              {primary ? primary.e164 : "(aucun numéro configuré)"}
            </div>
            {primary?.label ? (
              <div className="text-xs text-white/50">{primary.label}</div>
            ) : null}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <StatusPill
              on={secretaryOn}
              icon={<Sparkles className="h-3 w-3" />}
              label={secretaryOn ? "Secrétaire IA active" : "Secrétaire IA off"}
              onClick={() => primary && onToggleSecretary(primary)}
              disabled={!primary}
              title={
                secretaryOn
                  ? "Cliquer pour désactiver — retour au transfert direct"
                  : "Cliquer pour activer — Léa décroche et qualifie"
              }
            />
            <StatusPill
              on={autoOn}
              icon={<Bot className="h-3 w-3" />}
              label={
                autoOn ? "Rappel auto leads actif" : "Rappel auto leads off"
              }
              onClick={() => primary && onToggleAutoCallback(primary)}
              disabled={!primary}
              title={
                autoOn
                  ? "Cliquer pour désactiver — les nouveaux leads ne seront plus rappelés"
                  : "Cliquer pour activer — Léa rappellera chaque nouveau lead 60 sec après création"
              }
            />
          </div>
        </div>
        <div className="mt-3 text-[11px] text-white/60">
          Astuce : clique sur les pastilles ci-dessus pour activer ou
          désactiver. Les changements sont appliqués immédiatement et
          partagés entre toi et toute l&apos;équipe.
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-3 border-t border-brand-800 pt-3">
          <DashboardDialButton />
          <PushNotificationsToggle />
        </div>
      </section>

      {/* KPI grid */}
      <section className="grid gap-3 md:grid-cols-2 lg:grid-cols-4">
        <KpiCard
          icon={<PhoneIncoming className="h-4 w-4" />}
          label="Appels aujourd'hui"
          value={String(totalToday)}
          subtitle={`${inboundToday} entrants · ${outboundToday} sortants`}
          tone="teal"
        />
        <KpiCard
          icon={<Bot className="h-4 w-4" />}
          label="Qualifiés par Léa"
          value={String(aiHandledToday)}
          subtitle={
            totalToday === 0
              ? "—"
              : `${Math.round((aiHandledToday / totalToday) * 100)}% du total`
          }
          tone="violet"
        />
        <KpiCard
          icon={<PhoneOff className="h-4 w-4" />}
          label="Manqués"
          value={String(missedToday + voicemailToday)}
          subtitle={`${missedToday} non-rep · ${voicemailToday} voicemail`}
          tone="amber"
        />
        <KpiCard
          icon={<ShieldCheck className="h-4 w-4" />}
          label="Spam bloqué (jour)"
          value={String(usage?.spam_blocked ?? 0)}
          subtitle={
            usage
              ? `${(usage.cents_spent / 100).toFixed(2)} $ dépensés`
              : "—"
          }
          tone="emerald"
        />
        <KpiCard
          icon={<Clock className="h-4 w-4" />}
          label="Durée moyenne"
          value={avgDuration ? `${avgDuration}s` : "—"}
          subtitle="appels du jour"
          tone="blue"
        />
        <KpiCard
          icon={<Users className="h-4 w-4" />}
          label="Filtres actifs"
          value={String(numbers.length ? "—" : 0)}
          subtitle="VIP + blocklist"
          tone="violet"
          onClick={() => onJumpTo("filtres")}
        />
        <KpiCard
          icon={<TrendingUp className="h-4 w-4" />}
          label="Coût mensuel estimé"
          value={
            usage
              ? `~${((usage.cents_spent / 100) * 30).toFixed(0)} $`
              : "—"
          }
          subtitle="projection 30 j"
          tone="teal"
        />
        <KpiCard
          icon={<Building2 className="h-4 w-4" />}
          label="Identifiés CRM"
          value={String(
            todayCalls.filter(
              (c) => c.caller_kind && c.caller_kind !== "unknown"
            ).length
          )}
          subtitle="reconnus avant décroché"
          tone="amber"
        />
      </section>

      {/* Activity feed */}
      <section className="grid gap-4 lg:grid-cols-3">
        <div className="lg:col-span-2 rounded-2xl border border-brand-800 bg-brand-900 p-5">
          <div className="flex items-center justify-between">
            <h2 className="flex items-center gap-2 text-sm font-bold text-white">
              <PhoneCall className="h-4 w-4 text-teal-300" />
              Activité récente
            </h2>
            <button
              type="button"
              onClick={() => onJumpTo("appels")}
              className="text-[11px] text-teal-300 hover:underline"
            >
              Tout voir →
            </button>
          </div>
          {calls.length === 0 ? (
            <EmptyHint>
              Appelle le numéro ci-dessus depuis un mobile vérifié pour
              déclencher ton premier appel test.
            </EmptyHint>
          ) : (
            <ul className="mt-3 divide-y divide-brand-800">
              {calls.slice(0, 6).map((c) => (
                <li
                  key={c.id}
                  className="flex items-center gap-2 py-2.5 hover:bg-brand-800/30"
                >
                  <button
                    type="button"
                    onClick={() => onOpenCall(c.id)}
                    className="flex flex-1 items-center gap-3 text-left"
                  >
                    <DirectionIcon dir={c.direction} status={c.status} />
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2 truncate">
                        <span className="truncate font-mono text-sm text-white">
                          {c.from_e164}
                        </span>
                        {c.caller_kind && c.caller_kind !== "unknown" ? (
                          <CallerKindBadge kind={c.caller_kind} />
                        ) : null}
                      </div>
                      <div className="truncate text-[11px] text-white/50">
                        {formatDateTime(c.started_at)}
                        {c.duration_sec != null ? ` · ${c.duration_sec}s` : ""}
                        {c.lead_name ? ` · ${c.lead_name}` : ""}
                      </div>
                    </div>
                    <StatusBadge status={c.status} />
                  </button>
                  {/* Bouton « Rappeler » direct si l'appel a généré
                      une demande de callback (intent=callback ou
                      manqué). Sinon, juste le badge intent. */}
                  {c.intent === "callback" ||
                  c.status === "no-answer" ||
                  c.status === "busy" ||
                  c.status === "failed" ? (
                    <CallbackInlineButton
                      targetE164={c.from_e164}
                      entityType={c.entity_type || undefined}
                      entityId={c.entity_id || undefined}
                    />
                  ) : c.intent ? (
                    <IntentBadge intent={c.intent} />
                  ) : null}
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="rounded-2xl border border-brand-800 bg-brand-900 p-5">
          <h2 className="flex items-center gap-2 text-sm font-bold text-white">
            <Sparkles className="h-4 w-4 text-amber-300" />
            Comment ça marche
          </h2>
          <ol className="mt-3 space-y-2 text-[12px] text-white/70">
            <li className="flex gap-2">
              <span className="font-bold text-teal-300">1.</span>
              <span>
                Léa décroche en français/anglais selon l&apos;appelant
                (Polly Neural).
              </span>
            </li>
            <li className="flex gap-2">
              <span className="font-bold text-teal-300">2.</span>
              <span>
                Identification CRM : client / locataire / lead reconnu
                → routage adapté.
              </span>
            </li>
            <li className="flex gap-2">
              <span className="font-bold text-teal-300">3.</span>
              <span>
                Filtrage anti-spam 6 couches (geo, STIR/SHAKEN, rate
                limit, honeypot, lookup, cost cap).
              </span>
            </li>
            <li className="flex gap-2">
              <span className="font-bold text-teal-300">4.</span>
              <span>
                Transfert WebRTC sur ton browser ouvert, fallback mobile
                après 15 sec.
              </span>
            </li>
            <li className="flex gap-2">
              <span className="font-bold text-teal-300">5.</span>
              <span>
                Hors heures → voicemail IA + transcription + résumé
                automatique dans le CRM.
              </span>
            </li>
          </ol>
        </div>
      </section>

      <DiagnosticPanel />
    </div>
  );
}

// ----------------------------------------------------------------------
// Diagnostic panel — fetch /voice/diag avec le JWT admin
// ----------------------------------------------------------------------

type DiagPayload = {
  env: Record<string, unknown>;
  ai?: { configured?: boolean; provider?: string; error?: string };
  tables: Record<string, string>;
  columns: Record<string, string>;
  phone_numbers?: unknown;
  usage_today?: unknown;
};

function DiagnosticPanel() {
  const [data, setData] = useState<DiagPayload | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [open, setOpen] = useState(false);

  const fetchDiag = useCallback(async () => {
    setBusy(true);
    setErr(null);
    try {
      const res = await authedFetch("/api/v1/voice/diag");
      if (!res.ok) throw new Error(`http_${res.status}`);
      setData((await res.json()) as DiagPayload);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }, []);

  // Auto-load au premier déploiement de la card.
  useEffect(() => {
    if (open && data === null && !busy) void fetchDiag();
  }, [open, data, busy, fetchDiag]);

  const env = (data?.env || {}) as Record<string, unknown>;
  const tables = data?.tables || {};
  const columns = data?.columns || {};

  // Compteurs pour vue d'ensemble rapide.
  const tablesMissing = Object.entries(tables).filter(
    ([, v]) => v !== "ok"
  );
  const columnsMissing = Object.entries(columns).filter(
    ([, v]) => v !== "ok"
  );
  const allGreen =
    data !== null &&
    tablesMissing.length === 0 &&
    columnsMissing.length === 0;

  return (
    <section className="mt-5 rounded-2xl border border-brand-800 bg-brand-900 p-5">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center justify-between gap-3"
      >
        <h2 className="flex items-center gap-2 text-sm font-bold text-white">
          🔧 Diagnostic infra téléphonie
          {data ? (
            <span
              className={`rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider ${
                allGreen
                  ? "bg-emerald-500/15 text-emerald-300"
                  : "bg-amber-500/15 text-amber-300"
              }`}
            >
              {allGreen
                ? "tout vert"
                : `${tablesMissing.length + columnsMissing.length} alertes`}
            </span>
          ) : null}
        </h2>
        <span className="text-white/40">{open ? "▾" : "▸"}</span>
      </button>

      {open ? (
        <div className="mt-4 space-y-4">
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={() => void fetchDiag()}
              disabled={busy}
              className="rounded-md border border-teal-500/40 bg-teal-500/10 px-2.5 py-1 text-[11px] font-semibold text-teal-200 hover:bg-teal-500/20 disabled:opacity-50"
            >
              {busy ? "Chargement…" : "Rafraîchir"}
            </button>
            <BootstrapButton onDone={() => void fetchDiag()} />
            <DedupeButton onDone={() => void fetchDiag()} />
            {err ? (
              <span className="text-[11px] text-rose-300">{err}</span>
            ) : null}
          </div>

          {data ? (
            <>
              {/* Variables d'environnement */}
              <DiagBlock title="Variables d'environnement Render">
                <ul className="grid gap-1 sm:grid-cols-2">
                  {Object.entries(env).map(([k, v]) => {
                    const ok =
                      v === true ||
                      (typeof v === "string" && v.length > 0 && v !== "null");
                    const display =
                      v === true ? "✓ configuré" : v == null ? "—" : String(v);
                    return (
                      <li
                        key={k}
                        className="flex items-center justify-between gap-2 rounded-md bg-brand-950 px-2 py-1.5 text-[11px]"
                      >
                        <code className="text-white/70">{k}</code>
                        <span
                          className={
                            ok ? "text-emerald-300" : "text-amber-300"
                          }
                        >
                          {display.length > 30
                            ? display.slice(0, 27) + "…"
                            : display}
                        </span>
                      </li>
                    );
                  })}
                </ul>
              </DiagBlock>

              {/* Tables */}
              <DiagBlock title="Tables téléphonie en DB">
                <ul className="grid gap-1 sm:grid-cols-2">
                  {Object.entries(tables).map(([k, v]) => {
                    const ok = v === "ok";
                    return (
                      <li
                        key={k}
                        className="flex items-center justify-between gap-2 rounded-md bg-brand-950 px-2 py-1.5 text-[11px]"
                      >
                        <code className="text-white/70">{k}</code>
                        <span
                          className={
                            ok ? "text-emerald-300" : "text-rose-300"
                          }
                        >
                          {v}
                        </span>
                      </li>
                    );
                  })}
                </ul>
              </DiagBlock>

              {/* Colonnes critiques */}
              <DiagBlock title="Colonnes critiques (ALTER ADD COLUMN)">
                <ul className="grid gap-1 sm:grid-cols-2">
                  {Object.entries(columns).map(([k, v]) => {
                    const ok = v === "ok";
                    return (
                      <li
                        key={k}
                        className="flex items-center justify-between gap-2 rounded-md bg-brand-950 px-2 py-1.5 text-[10px]"
                      >
                        <code className="text-white/70">{k}</code>
                        <span
                          className={
                            ok ? "text-emerald-300" : "text-rose-300"
                          }
                        >
                          {v}
                        </span>
                      </li>
                    );
                  })}
                </ul>
              </DiagBlock>

              {/* IA */}
              <DiagBlock title="Provider IA">
                <p className="text-[11px] text-white/70">
                  {data.ai?.configured
                    ? `Actif : ${data.ai.provider}`
                    : data.ai?.error
                      ? `Erreur : ${data.ai.error}`
                      : "Non configuré (Léa ne pourra pas répondre tour-par-tour, seul le greeting statique fonctionnera)"}
                </p>
              </DiagBlock>

              {/* JSON brut (pour copier-coller en debug) */}
              <details className="rounded-xl border border-brand-800 bg-brand-950 p-3">
                <summary className="cursor-pointer text-[11px] font-semibold text-white/60">
                  JSON brut (à coller en cas de bug)
                </summary>
                <pre className="mt-2 max-h-96 overflow-auto whitespace-pre-wrap text-[10px] text-white/70">
                  {JSON.stringify(data, null, 2)}
                </pre>
              </details>
            </>
          ) : busy ? null : (
            <p className="text-[11px] text-white/40">
              Clique sur Rafraîchir pour charger le diagnostic.
            </p>
          )}
        </div>
      ) : null}
    </section>
  );
}

function DiagBlock({
  title,
  children
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <h3 className="mb-2 text-[10px] font-bold uppercase tracking-wider text-white/40">
        {title}
      </h3>
      {children}
    </div>
  );
}

function DedupeButton({ onDone }: { onDone: () => void }) {
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<string | null>(null);
  return (
    <>
      <button
        type="button"
        onClick={async () => {
          setBusy(true);
          setResult(null);
          try {
            const res = await authedFetch("/api/v1/voice/diag/dedupe", {
              method: "POST"
            });
            const data = (await res.json()) as {
              ok: boolean;
              message?: string;
              error?: string;
              matched_rows?: { id: number; e164: string }[];
              deleted_count?: number;
            };
            if (data.ok) {
              const found = data.matched_rows?.length || 0;
              const deleted = data.deleted_count || 0;
              setResult(
                deleted > 0
                  ? `✓ ${data.message}`
                  : `ℹ️ ${found} ligne(s), aucun doublon`
              );
              onDone();
            } else {
              setResult(`✗ Échec : ${data.error || "inconnu"}`);
            }
          } catch (e) {
            setResult(`✗ ${e instanceof Error ? e.message : String(e)}`);
          } finally {
            setBusy(false);
          }
        }}
        disabled={busy}
        title="Fusionne les lignes PhoneNumber doublons (mêmes 10 derniers chiffres) en une seule"
        className="rounded-md border border-violet-500/40 bg-violet-500/10 px-2.5 py-1 text-[11px] font-semibold text-violet-200 hover:bg-violet-500/20 disabled:opacity-50"
      >
        {busy ? "Fusion…" : "Fusionner les doublons"}
      </button>
      {result ? (
        <span
          className={`text-[11px] ${
            result.startsWith("✓") || result.startsWith("ℹ️")
              ? "text-emerald-300"
              : "text-rose-300"
          }`}
        >
          {result}
        </span>
      ) : null}
    </>
  );
}

function BootstrapButton({ onDone }: { onDone: () => void }) {
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<string | null>(null);
  return (
    <>
      <button
        type="button"
        onClick={async () => {
          setBusy(true);
          setResult(null);
          try {
            const res = await authedFetch("/api/v1/voice/diag/bootstrap", {
              method: "POST"
            });
            const data = (await res.json()) as {
              ok: boolean;
              return_code?: number;
              error?: string;
            };
            if (data.ok) {
              setResult("✓ Bootstrap réussi");
              onDone();
            } else {
              setResult(
                `✗ Échec : ${data.error || `code ${data.return_code}`}`
              );
            }
          } catch (e) {
            setResult(`✗ ${e instanceof Error ? e.message : String(e)}`);
          } finally {
            setBusy(false);
          }
        }}
        disabled={busy}
        title="Relance le bootstrap Twilio : crée la ligne PhoneNumber + pousse l'URL webhook sur le numéro"
        className="rounded-md border border-amber-500/40 bg-amber-500/10 px-2.5 py-1 text-[11px] font-semibold text-amber-200 hover:bg-amber-500/20 disabled:opacity-50"
      >
        {busy ? "Bootstrap en cours…" : "Relancer le bootstrap"}
      </button>
      {result ? (
        <span
          className={`text-[11px] ${
            result.startsWith("✓") ? "text-emerald-300" : "text-rose-300"
          }`}
        >
          {result}
        </span>
      ) : null}
    </>
  );
}

// ----------------------------------------------------------------------
// Calls section — full table with search + drawer
// ----------------------------------------------------------------------

function CallsSection({
  calls,
  search,
  onOpenCall
}: {
  calls: CallRow[];
  search: string;
  onOpenCall: (id: number) => void;
}) {
  const q = search.trim().toLowerCase();
  const filtered = q
    ? calls.filter(
        (c) =>
          c.from_e164.toLowerCase().includes(q) ||
          (c.intent || "").toLowerCase().includes(q) ||
          (c.lead_name || "").toLowerCase().includes(q) ||
          (c.caller_kind || "").toLowerCase().includes(q) ||
          (c.status || "").toLowerCase().includes(q)
      )
    : calls;

  return (
    <section className="mt-5 rounded-2xl border border-brand-800 bg-brand-900 p-5">
      <div className="flex items-center justify-between">
        <h2 className="flex items-center gap-2 text-sm font-bold text-white">
          <PhoneCall className="h-4 w-4 text-teal-300" />
          Journal d&apos;appels
          <span className="ml-2 rounded-full bg-brand-800 px-2 py-0.5 text-[10px] text-white/60">
            {filtered.length}
          </span>
        </h2>
      </div>

      {filtered.length === 0 ? (
        <EmptyHint>Aucun appel ne correspond à ta recherche.</EmptyHint>
      ) : (
        <div className="mt-3 overflow-x-auto">
          <table className="w-full text-xs">
            <thead className="text-left text-white/40">
              <tr>
                <th className="py-1.5 font-normal">Date</th>
                <th className="py-1.5 font-normal">De</th>
                <th className="py-1.5 font-normal">Identifié</th>
                <th className="py-1.5 font-normal">Intent</th>
                <th className="py-1.5 font-normal">Statut</th>
                <th className="py-1.5 text-right font-normal">Durée</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-brand-800">
              {filtered.map((c) => (
                <tr
                  key={c.id}
                  className="cursor-pointer hover:bg-brand-800/30"
                  onClick={() => onOpenCall(c.id)}
                >
                  <td className="py-2 text-white/60">
                    {formatDateTime(c.started_at)}
                  </td>
                  <td className="py-2">
                    <div className="flex items-center gap-2">
                      <DirectionIcon dir={c.direction} status={c.status} />
                      <span className="font-mono text-white">
                        {c.from_e164}
                      </span>
                      {c.was_blocked ? <Tag tone="rose">blocked</Tag> : null}
                      {c.was_vip ? <Tag tone="emerald">vip</Tag> : null}
                      {c.was_voicemail ? <Tag tone="amber">vm</Tag> : null}
                    </div>
                  </td>
                  <td className="py-2">
                    {c.caller_kind && c.caller_kind !== "unknown" ? (
                      <CallerKindBadge kind={c.caller_kind} />
                    ) : (
                      <span className="text-white/30">—</span>
                    )}
                  </td>
                  <td className="py-2">
                    {c.intent ? (
                      <IntentBadge intent={c.intent} />
                    ) : (
                      <span className="text-white/30">—</span>
                    )}
                  </td>
                  <td className="py-2">
                    <StatusBadge status={c.status} />
                  </td>
                  <td className="py-2 text-right text-white/80">
                    {c.duration_sec != null ? `${c.duration_sec}s` : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

// ----------------------------------------------------------------------
// Messages (SMS) section — inbox threadée + composeur
// ----------------------------------------------------------------------

function MessagesSection({
  threads,
  onReload
}: {
  threads: SmsThread[];
  onReload: () => void;
}) {
  const [selected, setSelected] = useState<string | null>(
    threads[0]?.peer_e164 || null
  );
  const [messages, setMessages] = useState<SmsRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [reply, setReply] = useState("");
  const [sending, setSending] = useState(false);
  const [sendError, setSendError] = useState<string | null>(null);
  const [composerTo, setComposerTo] = useState("");
  const [showComposer, setShowComposer] = useState(threads.length === 0);

  const loadThread = useCallback(async (peer: string) => {
    setLoading(true);
    setMessages([]);
    try {
      const res = await authedFetch(
        `/api/v1/voice/sms?peer_e164=${encodeURIComponent(peer)}&limit=100`
      );
      if (res.ok) {
        const data = (await res.json()) as SmsRow[];
        // Chrono ascendant pour l'affichage type chat.
        setMessages([...data].reverse());
        // Mark all unread as read (best-effort).
        for (const m of data) {
          if (m.direction === "inbound" && m.read_at === null) {
            void authedFetch(`/api/v1/voice/sms/${m.id}/read`, {
              method: "POST"
            });
          }
        }
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (selected) void loadThread(selected);
  }, [selected, loadThread]);

  const sendReply = useCallback(
    async (to: string, body: string) => {
      if (!to || !body.trim()) return;
      setSending(true);
      setSendError(null);
      try {
        const res = await authedFetch("/api/v1/voice/sms", {
          method: "POST",
          body: JSON.stringify({ to_e164: to, body: body.trim() })
        });
        if (!res.ok) {
          const t = await res.text().catch(() => "");
          throw new Error(t || `http_${res.status}`);
        }
        setReply("");
        // Recharge la thread + la liste pour voir le nouvel envoi.
        await loadThread(to);
        onReload();
      } catch (err) {
        setSendError(err instanceof Error ? err.message : String(err));
      } finally {
        setSending(false);
      }
    },
    [loadThread, onReload]
  );

  return (
    <section className="mt-5 grid gap-4 lg:grid-cols-[320px_1fr]">
      {/* Inbox */}
      <div className="rounded-2xl border border-brand-800 bg-brand-900 p-3">
        <div className="flex items-center justify-between gap-2 px-1 pb-2">
          <h2 className="flex items-center gap-2 text-sm font-bold text-white">
            <MessageSquare className="h-4 w-4 text-teal-300" />
            Inbox
          </h2>
          <button
            type="button"
            onClick={() => {
              // Désélectionne la conversation en cours, sinon le composer
              // (rendu seulement si !selected) ne s'affiche pas.
              setSelected(null);
              setComposerTo("");
              setReply("");
              setShowComposer(true);
            }}
            className="rounded-md border border-teal-500/40 bg-teal-500/10 px-2 py-1 text-[10px] font-semibold text-teal-200 hover:bg-teal-500/20"
          >
            + Nouveau
          </button>
        </div>
        {threads.length === 0 ? (
          <EmptyHint compact>
            Aucun SMS reçu pour l&apos;instant. Texte le numéro principal
            depuis ton mobile pour tester l&apos;inbox.
          </EmptyHint>
        ) : (
          <ul className="space-y-1">
            {threads.map((t) => {
              const isActive = selected === t.peer_e164;
              return (
                <li key={t.peer_e164}>
                  <button
                    type="button"
                    onClick={() => setSelected(t.peer_e164)}
                    className={`flex w-full items-start gap-2 rounded-lg px-2 py-2 text-left transition ${
                      isActive
                        ? "bg-teal-500/10"
                        : "hover:bg-brand-800/40"
                    }`}
                  >
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <span className="truncate text-xs font-semibold text-white">
                          {t.peer_e164}
                        </span>
                        {t.caller_kind && t.caller_kind !== "unknown" ? (
                          <CallerKindBadge kind={t.caller_kind} />
                        ) : null}
                      </div>
                      <div className="truncate text-[11px] text-white/50">
                        {t.last_message.direction === "outbound" ? "→ " : ""}
                        {t.last_message.body || "(MMS)"}
                      </div>
                      <div className="text-[10px] text-white/30">
                        {formatDateTime(t.last_message.received_at)}
                      </div>
                    </div>
                    {t.unread > 0 ? (
                      <span className="inline-flex h-4 min-w-[16px] items-center justify-center rounded-full bg-teal-500 px-1 text-[9px] font-bold text-brand-950">
                        {t.unread}
                      </span>
                    ) : null}
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </div>

      {/* Conversation panel */}
      <div className="rounded-2xl border border-brand-800 bg-brand-900 p-4 flex flex-col min-h-[400px]">
        {showComposer && !selected ? (
          <div className="space-y-3">
            <h3 className="text-sm font-bold text-white">Nouveau SMS</h3>
            <input
              type="tel"
              placeholder="+15146191111"
              value={composerTo}
              onChange={(e) => setComposerTo(e.target.value)}
              className="w-full rounded-md border border-brand-800 bg-brand-950 px-3 py-2 text-sm text-white placeholder-white/30"
            />
            <textarea
              placeholder="Message…"
              value={reply}
              onChange={(e) => setReply(e.target.value)}
              rows={4}
              className="w-full rounded-md border border-brand-800 bg-brand-950 px-3 py-2 text-sm text-white placeholder-white/30"
            />
            <button
              type="button"
              disabled={sending || !composerTo || !reply.trim()}
              onClick={() => {
                void sendReply(composerTo.trim(), reply);
                setSelected(composerTo.trim());
                setShowComposer(false);
              }}
              className="inline-flex items-center gap-1.5 rounded-md border border-teal-500/40 bg-teal-500/10 px-3 py-2 text-xs font-semibold text-teal-200 hover:bg-teal-500/20 disabled:opacity-50"
            >
              <Send className="h-3.5 w-3.5" />
              {sending ? "Envoi…" : "Envoyer"}
            </button>
            {sendError ? (
              <p className="text-[11px] text-rose-300">Erreur : {sendError}</p>
            ) : null}
          </div>
        ) : selected ? (
          <>
            <div className="flex items-center justify-between border-b border-brand-800 pb-2">
              <div className="font-mono text-sm font-bold text-white">
                {selected}
              </div>
              <CallButton targetE164={selected} label="Appeler" />
            </div>
            <div className="flex-1 overflow-y-auto py-3 space-y-2">
              {loading ? (
                <p className="text-[11px] text-white/40">Chargement…</p>
              ) : messages.length === 0 ? (
                <p className="text-[11px] text-white/40">Aucun message.</p>
              ) : (
                messages.map((m) => (
                  <div
                    key={m.id}
                    className={`max-w-[80%] rounded-2xl px-3 py-2 text-sm ${
                      m.direction === "outbound"
                        ? "ml-auto bg-teal-500/15 text-white/90"
                        : "mr-auto bg-brand-800 text-white/90"
                    }`}
                  >
                    {m.body || (m.num_media > 0 ? "(MMS)" : "")}
                    <div className="mt-1 text-[9px] text-white/40">
                      {formatDateTime(m.received_at)}
                    </div>
                  </div>
                ))
              )}
            </div>
            <div className="flex items-end gap-2 border-t border-brand-800 pt-3">
              <textarea
                placeholder="Réponse…"
                value={reply}
                onChange={(e) => setReply(e.target.value)}
                rows={2}
                className="flex-1 rounded-md border border-brand-800 bg-brand-950 px-3 py-2 text-sm text-white placeholder-white/30"
              />
              <button
                type="button"
                disabled={sending || !reply.trim()}
                onClick={() => void sendReply(selected, reply)}
                className="inline-flex items-center gap-1.5 rounded-md border border-teal-500/40 bg-teal-500/10 px-3 py-2 text-xs font-semibold text-teal-200 hover:bg-teal-500/20 disabled:opacity-50"
              >
                <Send className="h-3.5 w-3.5" />
                {sending ? "…" : "Envoyer"}
              </button>
            </div>
            {sendError ? (
              <p className="mt-2 text-[11px] text-rose-300">{sendError}</p>
            ) : null}
          </>
        ) : (
          <EmptyHint>Sélectionne une conversation à gauche.</EmptyHint>
        )}
      </div>
    </section>
  );
}

// ----------------------------------------------------------------------
// Numbers section
// ----------------------------------------------------------------------

function NumbersSection({
  numbers,
  onToggleSecretary,
  onToggleAutoCallback,
  patchNumber
}: {
  numbers: PhoneNumberRow[];
  onToggleSecretary: (n: PhoneNumberRow) => void;
  onToggleAutoCallback: (n: PhoneNumberRow) => void;
  patchNumber: (
    n: PhoneNumberRow,
    patch: Partial<PhoneNumberRow>
  ) => Promise<void> | void;
}) {
  if (numbers.length === 0) {
    return (
      <EmptyHint>
        Aucun numéro enregistré. Le bootstrap se déclenche au prochain
        démarrage du backend si TWILIO_PHONE_NUMBER est configuré.
      </EmptyHint>
    );
  }
  return (
    <section className="mt-5 grid gap-3 md:grid-cols-2">
      {numbers.map((n) => (
        <article
          key={n.id}
          className="rounded-2xl border border-brand-800 bg-brand-900 p-5"
        >
          <div className="flex items-start justify-between gap-2">
            <div>
              <div className="font-mono text-lg font-bold text-white">
                {n.e164}
              </div>
              <div className="text-xs text-white/50">{n.label || "—"}</div>
            </div>
            <span
              className={`rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider ${
                n.active
                  ? "bg-emerald-500/15 text-emerald-300"
                  : "bg-white/10 text-white/50"
              }`}
            >
              {n.active ? "actif" : "inactif"}
            </span>
          </div>

          <dl className="mt-4 space-y-2 text-xs">
            <Row label="Secrétaire IA">
              <ToggleButton
                on={n.secretary_mode_active}
                onClick={() => onToggleSecretary(n)}
                icon={<Sparkles className="h-3 w-3" />}
                tone="amber"
              />
            </Row>
            <Row label="Rappel auto leads">
              <ToggleButton
                on={n.lead_auto_callback_enabled}
                onClick={() => onToggleAutoCallback(n)}
                icon={<PhoneForwarded className="h-3 w-3" />}
                tone="emerald"
              />
            </Row>
          </dl>

          {/* Cibles de transfert par scénario — configurables depuis
              l'app (au lieu d'env vars Render). */}
          <div className="mt-4 space-y-2 border-t border-brand-800 pt-3">
            <p className="text-xs font-semibold uppercase tracking-wider text-white/80">
              Cibles de transfert (E.164)
            </p>
            <ForwardField
              label="Fallback générique"
              hint="utilisé quand Léa transfère sans contexte particulier"
              value={n.forward_to_e164}
              onSave={(v) =>
                patchNumber(n, { forward_to_e164: v ?? "" })
              }
            />
            <ForwardField
              label="🚨 Urgence locataire"
              hint="hot-transfert + enregistrement (consentement annoncé). Plusieurs numéros séparés par virgule = ring tous en parallèle, premier qui décroche gagne."
              value={n.urgency_forward_e164}
              onSave={(v) =>
                patchNumber(n, { urgency_forward_e164: v ?? "" })
              }
              tone="rose"
            />
            <ForwardField
              label="🎯 Closer (lead qualifié)"
              hint="vendeur humain pour confirmer un RDV"
              value={n.closer_forward_e164}
              onSave={(v) =>
                patchNumber(n, { closer_forward_e164: v ?? "" })
              }
              tone="amber"
            />
            <ForwardField
              label="🏗️ Suivi projet (back-office)"
              hint="utilisé si aucun chargé de projet assigné n'est dispo"
              value={n.followup_forward_e164}
              onSave={(v) =>
                patchNumber(n, { followup_forward_e164: v ?? "" })
              }
              tone="teal"
            />
          </div>
        </article>
      ))}
    </section>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <dt className="text-white/50">{label}</dt>
      <dd>{children}</dd>
    </div>
  );
}

function ForwardField({
  label,
  hint,
  value,
  onSave,
  tone = "white"
}: {
  label: string;
  hint?: string;
  value: string | null;
  onSave: (next: string | null) => Promise<void> | void;
  tone?: "white" | "rose" | "amber" | "teal";
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value || "");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!editing) setDraft(value || "");
  }, [value, editing]);

  const labelTone: Record<typeof tone, string> = {
    white: "text-white/90",
    rose: "text-rose-400",
    amber: "text-amber-400",
    teal: "text-teal-400"
  };

  async function persist() {
    setSaving(true);
    try {
      const trimmed = draft.trim();
      await onSave(trimmed || null);
      setEditing(false);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="rounded-md border border-brand-800 bg-brand-950/40 p-2.5">
      <div className="flex items-center justify-between gap-2">
        <div className="min-w-0 flex-1">
          <div className={`text-xs font-semibold ${labelTone[tone]}`}>
            {label}
          </div>
          {hint ? (
            <div className="text-[11px] text-white/70">{hint}</div>
          ) : null}
        </div>
        {!editing ? (
          <button
            type="button"
            onClick={() => setEditing(true)}
            className="rounded-md border border-brand-800 px-2 py-0.5 text-[11px] font-medium text-white/80 hover:bg-brand-800 hover:text-white"
          >
            {value ? "Modifier" : "+ Ajouter"}
          </button>
        ) : null}
      </div>
      <div className="mt-1.5">
        {editing ? (
          <div className="flex items-center gap-1">
            <input
              type="tel"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              placeholder="+15145551234"
              className="flex-1 rounded border border-brand-700 bg-brand-950 px-2 py-1 font-mono text-xs text-white placeholder:text-white/50 focus:border-accent-500 focus:outline-none"
              disabled={saving}
            />
            <button
              type="button"
              onClick={persist}
              disabled={saving}
              className="rounded bg-accent-500 px-2 py-1 text-[10px] font-semibold text-brand-950 disabled:opacity-50"
            >
              {saving ? "…" : "OK"}
            </button>
            <button
              type="button"
              onClick={() => {
                setEditing(false);
                setDraft(value || "");
              }}
              disabled={saving}
              className="rounded border border-brand-700 px-2 py-1 text-[10px] text-white/70"
            >
              ✕
            </button>
          </div>
        ) : value ? (
          <span className="font-mono text-sm font-semibold text-white">
            {value}
          </span>
        ) : (
          <span className="text-[11px] italic text-white/60">
            non configuré (fallback env var)
          </span>
        )}
      </div>
    </div>
  );
}

function ToggleButton({
  on,
  onClick,
  icon,
  tone
}: {
  on: boolean;
  onClick: () => void;
  icon: React.ReactNode;
  tone: "amber" | "emerald";
}) {
  const onCls =
    tone === "amber"
      ? "bg-amber-500/20 text-amber-200 hover:bg-amber-500/30"
      : "bg-emerald-500/20 text-emerald-200 hover:bg-emerald-500/30";
  return (
    <button
      type="button"
      onClick={onClick}
      className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-[11px] font-semibold uppercase tracking-wide transition ${
        on ? onCls : "bg-white/10 text-white/50 hover:bg-white/15"
      }`}
    >
      {icon}
      {on ? "activée" : "désactivée"}
    </button>
  );
}

// ----------------------------------------------------------------------
// Filters section
// ----------------------------------------------------------------------

function FiltersSection({
  phoneNumberId,
  filters,
  onAdd,
  onDelete
}: {
  phoneNumberId: number;
  filters: FilterRow[];
  onAdd: (
    phoneNumberId: number,
    kind: "block" | "vip",
    pattern: string,
    label: string
  ) => void;
  onDelete: (filterId: number) => void;
}) {
  const [kind, setKind] = useState<"block" | "vip">("block");
  const [pattern, setPattern] = useState("");
  const [label, setLabel] = useState("");
  const blocks = filters.filter((f) => f.kind === "block");
  const vips = filters.filter((f) => f.kind === "vip");

  return (
    <section className="mt-5 grid gap-4 lg:grid-cols-3">
      <div className="lg:col-span-2 grid gap-3 md:grid-cols-2">
        <FilterCard
          title="Blocklist"
          subtitle={`${blocks.length} ${blocks.length > 1 ? "numéros" : "numéro"}`}
          tone="rose"
        >
          {blocks.length === 0 ? (
            <EmptyHint compact>Aucun blocage.</EmptyHint>
          ) : (
            <ul className="space-y-1">
              {blocks.map((f) => (
                <FilterItem key={f.id} f={f} onDelete={() => onDelete(f.id)} />
              ))}
            </ul>
          )}
        </FilterCard>
        <FilterCard
          title="VIP — ring direct"
          subtitle={`${vips.length} ${vips.length > 1 ? "numéros" : "numéro"}`}
          tone="emerald"
        >
          {vips.length === 0 ? (
            <EmptyHint compact>Aucun VIP.</EmptyHint>
          ) : (
            <ul className="space-y-1">
              {vips.map((f) => (
                <FilterItem key={f.id} f={f} onDelete={() => onDelete(f.id)} />
              ))}
            </ul>
          )}
        </FilterCard>
      </div>

      <div className="rounded-2xl border border-brand-800 bg-brand-900 p-5">
        <h2 className="flex items-center gap-2 text-sm font-bold text-white">
          <Filter className="h-4 w-4 text-violet-300" />
          Ajouter un filtre
        </h2>
        <p className="mt-1 text-[11px] text-white/50">
          Pattern : numéro exact (<code>+14385551234</code>), préfixe avec
          astérisque (<code>+1438*</code>), ou vide = match-tout.
        </p>
        <div className="mt-3 space-y-2 text-xs">
          <select
            value={kind}
            onChange={(e) => setKind(e.target.value as "block" | "vip")}
            className="w-full rounded-md border border-brand-800 bg-brand-950 px-2 py-1.5 text-white"
          >
            <option value="block">Bloquer ce numéro</option>
            <option value="vip">VIP (ring direct, skip secrétaire)</option>
          </select>
          <input
            type="text"
            placeholder="Pattern (ex: +14385551234 ou +1438*)"
            value={pattern}
            onChange={(e) => setPattern(e.target.value)}
            className="w-full rounded-md border border-brand-800 bg-brand-950 px-2 py-1.5 text-white placeholder-white/30"
          />
          <input
            type="text"
            placeholder="Libellé (ex: Marie Tremblay)"
            value={label}
            onChange={(e) => setLabel(e.target.value)}
            className="w-full rounded-md border border-brand-800 bg-brand-950 px-2 py-1.5 text-white placeholder-white/30"
          />
          <button
            type="button"
            onClick={() => {
              if (
                !pattern.trim() &&
                !confirm(
                  "Sans pattern, ce filtre s'applique à TOUS les appels. Continuer ?"
                )
              )
                return;
              onAdd(phoneNumberId, kind, pattern, label);
              setPattern("");
              setLabel("");
            }}
            className="w-full rounded-md border border-teal-500/40 bg-teal-500/10 px-3 py-2 text-xs font-semibold text-teal-200 hover:bg-teal-500/20"
          >
            Ajouter
          </button>
        </div>
      </div>
    </section>
  );
}

function FilterCard({
  title,
  subtitle,
  tone,
  children
}: {
  title: string;
  subtitle: string;
  tone: "rose" | "emerald";
  children: React.ReactNode;
}) {
  const toneCls =
    tone === "rose" ? "text-rose-300" : "text-emerald-300";
  return (
    <div className="rounded-2xl border border-brand-800 bg-brand-900 p-5">
      <h3 className={`text-xs font-bold uppercase tracking-wider ${toneCls}`}>
        {title}
      </h3>
      <div className="text-[10px] text-white/40">{subtitle}</div>
      <div className="mt-3">{children}</div>
    </div>
  );
}

function FilterItem({
  f,
  onDelete
}: {
  f: FilterRow;
  onDelete: () => void;
}) {
  return (
    <li className="flex items-center justify-between gap-2 rounded-md bg-brand-950 px-2 py-1.5 text-[11px]">
      <div className="min-w-0">
        <div className="font-mono text-white">{f.pattern || "(tous)"}</div>
        {f.label ? (
          <div className="truncate text-white/40">{f.label}</div>
        ) : null}
      </div>
      <button
        type="button"
        onClick={onDelete}
        className="text-white/40 hover:text-rose-300"
        title="Supprimer"
      >
        <X className="h-3 w-3" />
      </button>
    </li>
  );
}

// ----------------------------------------------------------------------
// Business hours section
// ----------------------------------------------------------------------

const DAY_LABELS = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"];

function BusinessHoursSection({
  phoneNumberId,
  hours,
  onSave
}: {
  phoneNumberId: number;
  hours: BusinessHoursRow[];
  onSave: (
    phoneNumberId: number,
    rows: { day_of_week: number; open_time: string; close_time: string }[]
  ) => void;
}) {
  type DayState = { enabled: boolean; open: string; close: string };
  const init = (): DayState[] =>
    DAY_LABELS.map((_, dow) => {
      const existing = hours.find((h) => h.day_of_week === dow);
      return existing
        ? { enabled: true, open: existing.open_time, close: existing.close_time }
        : { enabled: false, open: "09:00", close: "17:00" };
    });
  const [days, setDays] = useState<DayState[]>(init);

  useEffect(() => {
    setDays(init());
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hours]);

  const update = (i: number, patch: Partial<DayState>) =>
    setDays((prev) =>
      prev.map((d, idx) => (idx === i ? { ...d, ...patch } : d))
    );

  const save = () => {
    const rows = days
      .map((d, dow) => ({
        enabled: d.enabled,
        day_of_week: dow,
        open_time: d.open,
        close_time: d.close
      }))
      .filter((r) => r.enabled)
      .map(({ enabled: _e, ...rest }) => rest);
    onSave(phoneNumberId, rows);
  };

  return (
    <section className="mt-5 rounded-2xl border border-brand-800 bg-brand-900 p-5">
      <div className="flex items-center justify-between">
        <h2 className="flex items-center gap-2 text-sm font-bold text-white">
          <Clock className="h-4 w-4 text-blue-300" />
          Heures d&apos;ouverture
          <span className="ml-2 rounded-full bg-brand-800 px-2 py-0.5 text-[10px] text-white/60">
            Montréal
          </span>
        </h2>
        <button
          type="button"
          onClick={save}
          className="rounded-md border border-teal-500/40 bg-teal-500/10 px-3 py-1.5 text-xs font-semibold text-teal-200 hover:bg-teal-500/20"
        >
          <CheckCircle2 className="mr-1 inline h-3 w-3" />
          Enregistrer
        </button>
      </div>
      <p className="mt-1 text-[11px] text-white/50">
        Hors plages → voicemail IA (enregistrement + transcription + résumé).
        Aucun jour activé = ouvert 24 / 7.
      </p>

      <div className="mt-4 space-y-2">
        {days.map((d, i) => (
          <div
            key={i}
            className="flex items-center gap-3 rounded-lg border border-brand-800 bg-brand-950 px-3 py-2 text-sm"
          >
            <label className="flex w-28 items-center gap-2 text-white/80">
              <input
                type="checkbox"
                checked={d.enabled}
                onChange={(e) => update(i, { enabled: e.target.checked })}
                className="h-3.5 w-3.5"
              />
              {DAY_LABELS[i]}
            </label>
            <input
              type="time"
              value={d.open}
              onChange={(e) => update(i, { open: e.target.value })}
              disabled={!d.enabled}
              className="rounded-md border border-brand-800 bg-brand-900 px-2 py-1 text-white disabled:opacity-40"
            />
            <span className="text-white/40">→</span>
            <input
              type="time"
              value={d.close}
              onChange={(e) => update(i, { close: e.target.value })}
              disabled={!d.enabled}
              className="rounded-md border border-brand-800 bg-brand-900 px-2 py-1 text-white disabled:opacity-40"
            />
            {!d.enabled ? (
              <span className="ml-auto text-[11px] text-white/40">
                voicemail
              </span>
            ) : null}
          </div>
        ))}
      </div>
    </section>
  );
}

// ----------------------------------------------------------------------
// Plan section (les 4 phases)
// ----------------------------------------------------------------------

function PlanSection() {
  return (
    <section className="mt-5 space-y-3">
      <PhaseCard
        num={1}
        title="Fondations"
        status="done"
        items={[
          "Module backend voice + abstraction provider",
          "Modèles SQL + webhook Twilio signé HMAC",
          "Auto-bootstrap + dispatch <Dial> simple"
        ]}
      />
      <PhaseCard
        num={2}
        title="Secrétaire IA bilingue"
        status="done"
        items={[
          "Polly Neural FR/EN + Claude tour-par-tour",
          "Création ContactRequest sur callback",
          "Toggle activable par numéro"
        ]}
      />
      <PhaseCard
        num={3}
        title="Filtres + Heures + Voicemail IA"
        status="done"
        items={[
          "Blocklist + VIP whitelist par pattern",
          "Heures d'ouverture par jour de semaine",
          "Voicemail Record + transcription + résumé Claude"
        ]}
      />
      <PhaseCard
        num={4}
        title="Sortant + lien CRM"
        status="done"
        items={[
          "Click-to-call avec entity_type/id",
          "AI outbound auto sur nouveaux leads (toggle safety)",
          "Suggestion follow-up Claude post-appel"
        ]}
      />
      <PhaseCard
        num={5}
        title="Anti-spam 6 couches + Voice SDK hybride"
        status="done"
        items={[
          "Geo, STIR/SHAKEN, rate limit, honeypot, Lookup, cost cap",
          "Identification CRM avant décroché (bypass spam VIP)",
          "Voice SDK browser WebRTC + fallback mobile 15 sec"
        ]}
      />
      <PhaseCard
        num={6}
        title="SMS bidirectionnel + petit téléphone CRM"
        status="done"
        items={[
          "SMS entrants + sortants via le 438 (inbox threadée)",
          "Auto-identification CRM des SMS (client / locataire / lead)",
          "Petit téléphone à côté des numéros : prospect, client, lead",
          "Tous les appels CRM enregistrés dans /telephonie (entity_type/id)"
        ]}
      />

      {/* ============ Prochaines étapes ============ */}
      <h2 className="mt-8 text-sm font-bold uppercase tracking-wider text-amber-300">
        Prochaines étapes
      </h2>
      <p className="text-[12px] text-white/60">
        Notes pour quand on sera prêt à fusionner davantage la téléphonie
        avec les autres volets. Aucun de ces items n&apos;est en cours,
        ils attendent ton feu vert.
      </p>

      <PhaseCard
        num={7}
        title="Onglet « Communications » dans chaque fiche CRM"
        status="done"
        items={[
          "Onglet/section « Communications » ajouté dans /prospection/[id], /app/crm/[id] et /app/clients/[id]",
          "Endpoint GET /api/v1/voice/communications/{type}/{id} accessible à tout utilisateur authentifié (read-only, scopé par entité)",
          "Filtres Tout / Appels / SMS / Voicemail + recherche libre dans le contenu, lien vers le drawer détaillé /telephonie"
        ]}
      />

      <PhaseCard
        num={8}
        title="Routage intelligent inbound + intake construction IA"
        status="done"
        items={[
          "Urgence locataire : Léa détecte les mots-clés (dégât, fuite, panne chauffage…) et hot-transfère vers URGENCY_FORWARD_E164",
          "Suivi de projet : appelant identifié comme client/contact d'un projet actif → ring les membres online via Voice SDK + fallback mobile",
          "Intake construction conversationnel : Léa collecte type travaux, adresse, échéancier, budget, courriel, meilleur moment de rappel",
          "À la fin de l'intake : ContactRequest auto-créé + courriel récap envoyé via Microsoft Graph avec lien tokenisé /valider-demande/{token}",
          "Page publique de validation : client édite les infos, ajoute des photos, confirme — la fiche CRM est synchronisée automatiquement",
          "Toggle « Rappel auto leads » (appels SORTANTS vers nouveaux ContactRequests web) reste OFF par défaut — à flip seulement quand l'intake inbound aura été validé en prod"
        ]}
      />

      <PhaseCard
        num={9}
        title="Fusion CRM ↔ Téléphonie (vue 360 contact)"
        status="done"
        items={[
          "VoiceConsole actif dans tout le portail construction (/app) — les appels entrants ring via WebRTC quel que soit l'écran ouvert",
          "Quick-reply SMS depuis la fiche prospect/client/lead, envoyé directement via le 438 d'Horizon (timeline auto-refresh)",
          "Notifications cloche : voicemails (déjà en place), SMS entrants (déjà en place), URGENCES locataires (nouveau — broadcast à tous les owners avec lien direct vers l'appel)"
        ]}
      />

      <PhaseCard
        num={10}
        title="App mobile dédiée + dial pad + push"
        status="done"
        items={[
          "PWA installable (manifest scope global + service worker v4) — bouton « Installer l'app » dispo, ajoute Horizon à l'écran d'accueil iPhone et Android",
          "WebPush bout-en-bout : pywebpush + VAPID, pushManager frontend, sw.js gère push/notificationclick. Urgences locataires push tous les owners en plus de la cloche",
          "Dial pad flottant dans /telephonie — composer un numéro et lancer un appel click-to-call qui passe par le 438 (le cell de l'user sonne, puis bridge vers la cible)",
          "Résumé IA post-appel (followup_suggestion) déjà exposé dans le CallDrawer avec bouton « Re-générer »",
          "À venir si besoin : app Android native APK direct (sans App Store) ; recording avec consentement Québec ; extension push aux SMS reçus"
        ]}
      />
    </section>
  );
}

function PhaseCard({
  num,
  title,
  status,
  items
}: {
  num: number;
  title: string;
  status: "done" | "in_progress" | "todo";
  items: string[];
}) {
  return (
    <article className="rounded-2xl border border-brand-800 bg-brand-900 p-5">
      <header className="flex items-center justify-between gap-3 border-b border-brand-800 pb-3">
        <div className="flex items-center gap-3">
          <span className="flex h-8 w-8 items-center justify-center rounded-full bg-brand-800 text-xs font-bold text-white">
            {num}
          </span>
          <h3 className="text-base font-bold text-white">{title}</h3>
        </div>
        <span
          className={`rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${
            status === "done"
              ? "bg-emerald-500/15 text-emerald-300"
              : status === "in_progress"
                ? "bg-amber-500/15 text-amber-300"
                : "bg-white/5 text-white/50"
          }`}
        >
          {status === "done"
            ? "Livré"
            : status === "in_progress"
              ? "En cours"
              : "À faire"}
        </span>
      </header>
      <ul className="mt-3 space-y-1 text-xs text-white/70">
        {items.map((it, i) => (
          <li key={i}>• {it}</li>
        ))}
      </ul>
    </article>
  );
}

// ----------------------------------------------------------------------
// Call drawer
// ----------------------------------------------------------------------

function CallDrawer({
  call,
  turns,
  onClose
}: {
  call: CallRow;
  turns: CallTurnRow[] | undefined;
  onClose: () => void;
}) {
  const [suggestion, setSuggestion] = useState<string | null>(
    call.followup_suggestion
  );
  const [busy, setBusy] = useState(false);

  const askSuggest = async () => {
    setBusy(true);
    try {
      const res = await authedFetch(
        `/api/v1/voice/calls/${call.id}/suggest-followup`,
        { method: "POST" }
      );
      if (!res.ok) return;
      const data = (await res.json()) as { suggestion: string };
      setSuggestion(data.suggestion);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-40 bg-black/40 backdrop-blur-sm"
      onClick={onClose}
    >
      <aside
        onClick={(e) => e.stopPropagation()}
        className="absolute right-0 top-0 flex h-full w-full max-w-xl flex-col overflow-y-auto border-l border-brand-800 bg-brand-900 shadow-2xl"
      >
        <header className="sticky top-0 z-10 flex items-center justify-between gap-3 border-b border-brand-800 bg-brand-900 p-4">
          <div className="flex items-center gap-3">
            <DirectionIcon dir={call.direction} status={call.status} />
            <div>
              <div className="font-mono text-base font-bold text-white">
                {call.from_e164}
              </div>
              <div className="text-[11px] text-white/50">
                {formatDateTime(call.started_at)}
                {call.duration_sec != null ? ` · ${call.duration_sec}s` : ""}
              </div>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md p-2 text-white/60 hover:bg-brand-800 hover:text-white"
            aria-label="Fermer"
          >
            <X className="h-4 w-4" />
          </button>
        </header>

        <div className="space-y-4 p-4">
          {/* Status badges */}
          <div className="flex flex-wrap items-center gap-2">
            <StatusBadge status={call.status} />
            {call.intent ? <IntentBadge intent={call.intent} /> : null}
            {call.caller_kind && call.caller_kind !== "unknown" ? (
              <CallerKindBadge kind={call.caller_kind} />
            ) : null}
            {call.was_blocked ? <Tag tone="rose">blocked</Tag> : null}
            {call.was_vip ? <Tag tone="emerald">vip</Tag> : null}
            {call.was_voicemail ? <Tag tone="amber">voicemail</Tag> : null}
          </div>

          {/* Voicemail */}
          {call.was_voicemail ? (
            <DrawerCard title="Voicemail" tone="amber">
              {call.voicemail_summary ? (
                <p className="italic text-amber-100">{call.voicemail_summary}</p>
              ) : null}
              {call.voicemail_transcription ? (
                <p className="mt-2 whitespace-pre-wrap text-white/80">
                  {call.voicemail_transcription}
                </p>
              ) : (
                <p className="text-[11px] text-white/40">
                  Transcription en cours…
                </p>
              )}
              {call.recording_url ? (
                <RecordingPlayer callId={call.id} />
              ) : null}
            </DrawerCard>
          ) : null}

          {/* Lead capturé */}
          {(call.lead_name || call.lead_callback_phone || call.lead_reason) ? (
            <DrawerCard title="Lead capturé" tone="teal">
              {call.lead_name ? (
                <div>
                  <span className="text-white/50">Nom : </span>
                  {call.lead_name}
                </div>
              ) : null}
              {call.lead_callback_phone ? (
                <div>
                  <span className="text-white/50">Rappel : </span>
                  <span className="font-mono">
                    {call.lead_callback_phone}
                  </span>
                </div>
              ) : null}
              {call.lead_reason ? (
                <div>
                  <span className="text-white/50">Raison : </span>
                  {call.lead_reason}
                </div>
              ) : null}
              {call.contact_request_id ? (
                <div className="mt-1 text-teal-300">
                  Fiche CRM #{call.contact_request_id} créée
                </div>
              ) : null}
              {call.lead_callback_phone ? (
                <div className="mt-3">
                  <CallButton
                    targetE164={call.lead_callback_phone}
                    entityType={call.entity_type || undefined}
                    entityId={call.entity_id || undefined}
                    label="Rappeler maintenant"
                  />
                </div>
              ) : null}
            </DrawerCard>
          ) : null}

          {/* Transcript */}
          <DrawerCard title="Conversation" tone="neutral">
            {turns === undefined ? (
              <p className="text-[11px] text-white/40">Chargement…</p>
            ) : turns.length === 0 ? (
              <p className="text-[11px] text-white/40">
                Pas de transcription (transfert direct sans secrétaire IA).
              </p>
            ) : (
              <ul className="space-y-2">
                {turns.map((t) => (
                  <li
                    key={t.id}
                    className={`rounded-md p-2 text-[11px] ${
                      t.role === "assistant"
                        ? "bg-teal-500/10 text-teal-100"
                        : "bg-brand-800 text-white/80"
                    }`}
                  >
                    <div className="mb-0.5 text-[9px] font-semibold uppercase tracking-wide opacity-60">
                      {t.role === "assistant" ? "Léa" : "Appelant"}
                    </div>
                    {t.text}
                  </li>
                ))}
              </ul>
            )}
          </DrawerCard>

          {/* Followup suggestion */}
          <DrawerCard title="Suggestion de suivi (IA)" tone="violet">
            {suggestion ? (
              <p className="whitespace-pre-wrap text-white/80">{suggestion}</p>
            ) : (
              <p className="text-[11px] text-white/40">
                Clique sur Générer pour demander à Claude une action de
                suivi concrète post-appel.
              </p>
            )}
            <button
              type="button"
              onClick={askSuggest}
              disabled={busy}
              className="mt-3 rounded-md border border-violet-500/40 bg-violet-500/10 px-2.5 py-1 text-[11px] text-violet-200 hover:bg-violet-500/20 disabled:opacity-50"
            >
              {busy ? "…" : suggestion ? "Régénérer" : "Générer"}
            </button>
          </DrawerCard>
        </div>
      </aside>
    </div>
  );
}

function DrawerCard({
  title,
  tone,
  children
}: {
  title: string;
  tone: "amber" | "teal" | "violet" | "neutral";
  children: React.ReactNode;
}) {
  const map = {
    amber: "border-amber-500/30 bg-amber-500/5 text-amber-200",
    teal: "border-teal-500/30 bg-teal-500/5 text-teal-200",
    violet: "border-violet-500/30 bg-violet-500/5 text-violet-200",
    neutral: "border-brand-800 bg-brand-950 text-white/70"
  };
  const titleTone = map[tone].split(" ").slice(-1)[0];
  return (
    <div className={`rounded-xl border p-3 text-[12px] ${map[tone]}`}>
      <div className={`mb-2 text-[10px] font-bold uppercase tracking-wider ${titleTone}`}>
        {title}
      </div>
      <div className="text-white/80">{children}</div>
    </div>
  );
}

// ----------------------------------------------------------------------
// Small UI helpers
// ----------------------------------------------------------------------

function KpiCard({
  icon,
  label,
  value,
  subtitle,
  tone,
  onClick
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  subtitle: string;
  tone: "teal" | "amber" | "violet" | "emerald" | "blue";
  onClick?: () => void;
}) {
  const map = {
    teal: "text-teal-300",
    amber: "text-amber-300",
    violet: "text-violet-300",
    emerald: "text-emerald-300",
    blue: "text-blue-300"
  };
  const Component = onClick ? "button" : "div";
  return (
    <Component
      onClick={onClick}
      className={`rounded-2xl border border-brand-800 bg-brand-900 p-4 text-left transition ${
        onClick ? "hover:border-brand-700 hover:bg-brand-800" : ""
      }`}
    >
      <div
        className={`flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wider ${map[tone]}`}
      >
        {icon}
        {label}
      </div>
      <div className="mt-1 text-2xl font-bold text-white">{value}</div>
      <div className="text-[11px] text-white/50">{subtitle}</div>
    </Component>
  );
}

function StatusPill({
  on,
  icon,
  label,
  onClick,
  disabled,
  title
}: {
  on: boolean;
  icon: React.ReactNode;
  label: string;
  onClick: () => void;
  disabled?: boolean;
  title?: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      title={title}
      className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-[10px] font-semibold uppercase tracking-wider transition disabled:cursor-not-allowed disabled:opacity-50 ${
        on
          ? "bg-emerald-500/20 text-emerald-200 hover:bg-emerald-500/30"
          : "bg-white/10 text-white/50 hover:bg-white/15"
      }`}
    >
      <span className="flex h-1.5 w-1.5 rounded-full bg-current opacity-80" />
      {icon}
      {label}
    </button>
  );
}

function EmptyHint({
  children,
  compact = false
}: {
  children: React.ReactNode;
  compact?: boolean;
}) {
  return (
    <p
      className={`text-[11px] text-white/40 ${
        compact ? "" : "rounded-md border border-brand-800 bg-brand-950 px-3 py-3 mt-3"
      }`}
    >
      {children}
    </p>
  );
}

function Tag({
  children,
  tone
}: {
  children: React.ReactNode;
  tone: "rose" | "emerald" | "amber";
}) {
  const cls = {
    rose: "bg-rose-500/20 text-rose-300",
    emerald: "bg-emerald-500/20 text-emerald-300",
    amber: "bg-amber-500/20 text-amber-300"
  }[tone];
  return (
    <span
      className={`rounded px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide ${cls}`}
    >
      {children}
    </span>
  );
}

function DirectionIcon({
  dir,
  status
}: {
  dir: string;
  status: string;
}) {
  if (dir === "outbound") {
    return (
      <span className="flex h-7 w-7 items-center justify-center rounded-full bg-blue-500/15 text-blue-300">
        <PhoneForwarded className="h-3.5 w-3.5" />
      </span>
    );
  }
  if (status === "no-answer" || status === "busy" || status === "failed") {
    return (
      <span className="flex h-7 w-7 items-center justify-center rounded-full bg-rose-500/15 text-rose-300">
        <PhoneOff className="h-3.5 w-3.5" />
      </span>
    );
  }
  return (
    <span className="flex h-7 w-7 items-center justify-center rounded-full bg-teal-500/15 text-teal-300">
      <PhoneIncoming className="h-3.5 w-3.5" />
    </span>
  );
}

function StatusBadge({ status }: { status: string }) {
  const known: Record<string, { label: string; cls: string }> = {
    completed: { label: "terminé", cls: "bg-emerald-500/15 text-emerald-300" },
    "in-progress": { label: "en cours", cls: "bg-amber-500/15 text-amber-300" },
    ringing: { label: "sonne", cls: "bg-amber-500/15 text-amber-300" },
    queued: { label: "queue", cls: "bg-white/10 text-white/60" },
    "no-answer": { label: "non répondu", cls: "bg-rose-500/15 text-rose-300" },
    busy: { label: "occupé", cls: "bg-rose-500/15 text-rose-300" },
    failed: { label: "échec", cls: "bg-rose-500/15 text-rose-300" },
    canceled: { label: "annulé", cls: "bg-white/10 text-white/60" }
  };
  const meta =
    known[status] || { label: status, cls: "bg-white/10 text-white/60" };
  return (
    <span
      className={`inline-block rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${meta.cls}`}
    >
      {meta.label}
    </span>
  );
}

function CallbackInlineButton({
  targetE164,
  entityType,
  entityId
}: {
  targetE164: string;
  entityType?: string;
  entityId?: number;
}) {
  return (
    <CallButton
      targetE164={targetE164}
      entityType={entityType}
      entityId={entityId}
      label="Rappeler"
      className="inline-flex items-center gap-1 rounded-md bg-amber-500/15 px-2.5 py-1 text-[11px] font-semibold text-amber-300 hover:bg-amber-500/25"
      variant="full"
    />
  );
}


function IntentBadge({ intent }: { intent: string }) {
  const map: Record<string, { label: string; cls: string }> = {
    renovation: { label: "rénovation", cls: "bg-teal-500/15 text-teal-300" },
    dev_logiciel: { label: "logiciel", cls: "bg-violet-500/15 text-violet-300" },
    gestion_immo: { label: "gestion immo", cls: "bg-blue-500/15 text-blue-300" },
    urgence: { label: "urgence", cls: "bg-rose-500/15 text-rose-300" },
    callback: { label: "rappel", cls: "bg-amber-500/15 text-amber-300" },
    lead_qualification: { label: "qualification", cls: "bg-violet-500/15 text-violet-300" },
    spam: { label: "spam", cls: "bg-white/10 text-white/40" },
    unclear: { label: "indéfini", cls: "bg-white/10 text-white/40" }
  };
  const meta =
    map[intent] || { label: intent, cls: "bg-white/10 text-white/60" };
  return (
    <span
      className={`inline-block rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${meta.cls}`}
    >
      {meta.label}
    </span>
  );
}

function CallerKindBadge({ kind }: { kind: string }) {
  const map: Record<string, { label: string; cls: string }> = {
    client: { label: "client", cls: "bg-emerald-500/15 text-emerald-300" },
    locataire: { label: "locataire", cls: "bg-blue-500/15 text-blue-300" },
    lead_prospection: { label: "lead prospect", cls: "bg-violet-500/15 text-violet-300" },
    lead_web: { label: "lead web", cls: "bg-teal-500/15 text-teal-300" }
  };
  const meta = map[kind];
  if (!meta) return null;
  return (
    <span
      className={`inline-block rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${meta.cls}`}
    >
      {meta.label}
    </span>
  );
}

function formatDateTime(iso: string): string {
  try {
    const d = new Date(iso);
    return d.toLocaleString("fr-CA", {
      day: "2-digit",
      month: "2-digit",
      hour: "2-digit",
      minute: "2-digit"
    });
  } catch {
    return iso;
  }
}
