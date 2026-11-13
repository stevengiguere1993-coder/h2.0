"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  ArrowLeft,
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
  X
} from "lucide-react";

import { authedFetch, getMe, getToken } from "@/lib/auth";
import { Link, useRouter } from "@/i18n/navigation";
import { AppTopbar } from "@/components/app-topbar";
import { CallButton } from "@/components/call-button";
import { DialPad } from "@/components/dial-pad";
import { DialPadFab } from "@/components/dial-pad-fab";
import { MmsImages } from "@/components/mms-images";
import { PushNotificationsToggle } from "@/components/push-notifications-toggle";
import { RecordingPlayer } from "@/components/recording-player";
import { PageDriveSection } from "@/components/drive/PageDriveSection";
import { useTelephonieLayout } from "./_client-shell";
import {
  closeTelephonie,
  navigateTelephonie,
  useTelephonieUrl
} from "./_url-state";
import { AcquisitionPanel } from "@/components/communications/acquisition-panel";
import { AutomationsPanel } from "@/components/communications/automations-panel";
import { RoutingPanel } from "@/components/telephonie/routing-panel";

// Volet « Téléphonie / Secrétaire d'appels » — interface premium.
//
// Sections (tabs) :
//   1. Tableau de bord — KPIs du jour + activité live + plan
//   2. Appels — journal complet avec drawer de détail + transcription
//   3. Numéros — toggles secrétaire / rappel auto / forward / état
//   4. Filtres — blocklist + VIP whitelist
//   5. Heures — plages d'ouverture hebdomadaires
//   6. Acheminement (admins) — qui sonne selon le sujet de l'appel,
//      règles par chantier, heures d'appel personnelles de l'équipe
//
// Accès géré par capacité (Paramètres → Permissions) : rôle owner/admin
// ou capacité `telephonie.access` — plus de liste d'emails en dur (P-05d).

type Me = {
  email?: string | null;
  role?: string | null;
  access?: Record<string, boolean>;
};

import type { TelephonieSection as Section } from "./_client-shell";

type SmsThread = {
  peer_e164: string;
  name: string | null;
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
  peer_e164?: string | null;
  contact_name?: string | null;
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
  // Détail d'appel et conversation ouverte vivent dans l'URL
  // (?call= / ?fil=) : « retour » sur le téléphone les referme.
  const urlParams = useTelephonieUrl();
  const drawerCallId = Number(urlParams.get("call")) || null;
  const smsParam = urlParams.get("sms");
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
    (callId: number) => {
      navigateTelephonie({ section, call: String(callId) });
    },
    [section]
  );

  // Transcription de l'appel ouvert (à l'ouverture comme à l'arrivée
  // par un lien de notification /telephonie?call={id}).
  useEffect(() => {
    if (!drawerCallId || turnsByCallId[drawerCallId]) return;
    let cancelled = false;
    void (async () => {
      try {
        const res = await authedFetch(
          `/api/v1/voice/calls/${drawerCallId}/turns`
        );
        if (!res.ok) return;
        const data = (await res.json()) as CallTurnRow[];
        if (!cancelled) {
          setTurnsByCallId((prev) => ({ ...prev, [drawerCallId]: data }));
        }
      } catch {
        /* ignore */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [drawerCallId, turnsByCallId]);

  // Lien de notification d'un texto (/telephonie?sms={id}) : on ouvre
  // la conversation de cet expéditeur.
  useEffect(() => {
    if (!smsParam) return;
    const smsId = Number(smsParam);
    const known = smsThreads.find((t) => t.last_message.id === smsId);
    if (known) {
      navigateTelephonie(
        { section: "messages", fil: known.peer_e164, sms: null },
        { replace: true }
      );
      return;
    }
    let cancelled = false;
    void (async () => {
      try {
        const res = await authedFetch(
          `/api/v1/voice/sms?sms_id=${encodeURIComponent(smsParam)}&limit=1`
        );
        const rows = res.ok ? ((await res.json()) as SmsRow[]) : [];
        const m = rows[0];
        if (cancelled) return;
        const peer = m
          ? m.direction === "outbound"
            ? m.to_e164
            : m.from_e164
          : null;
        navigateTelephonie(
          { section: "messages", fil: peer, sms: null },
          { replace: true }
        );
      } catch {
        /* ignore */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [smsParam, smsThreads]);

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
        const role = (me?.role || "").toLowerCase().trim();
        // Accès = rôle owner/admin, ou capacité telephonie.access (P-05d).
        const ok =
          role === "owner" ||
          role === "admin" ||
          me?.access?.["telephonie.access"] === true;
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
            Le volet Communications n&apos;est pas activé pour ton compte.
            Demande à un administrateur de t&apos;y donner accès.
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
        breadcrumbs={[{ label: "Communications" }]}
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
            onlyMissed={urlParams.get("filtre") === "manques"}
            onToggleMissed={(on) =>
              navigateTelephonie(
                { filtre: on ? "manques" : null },
                { replace: true }
              )
            }
            onOpenCall={openDrawer}
          />
        ) : null}

        {section === "messages" ? (
          <MessagesSection
            threads={smsThreads}
            selected={urlParams.get("fil")}
            composing={urlParams.get("nouveau") === "1"}
            onReload={() => void reload()}
          />
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

        {section === "acheminement" ? <RoutingPanel /> : null}

        {section === "acquisition" ? <AcquisitionPanel /> : null}
        {section === "automatisations" ? <AutomationsPanel /> : null}

      </div>

      {drawerCall ? (
        <CallDrawer
          key={drawerCall.id}
          call={drawerCall}
          turns={turnsByCallId[drawerCall.id]}
          onClose={() => closeTelephonie({ call: null })}
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
    { key: "heures", label: "Heures", icon: <Clock className="h-3.5 w-3.5" /> }
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
  const answeredToday = todayCalls.filter(
    (c) => c.status === "completed" || c.status === "in-progress"
  ).length;
  const answerRate =
    totalToday === 0 ? 0 : Math.round((answeredToday / totalToday) * 100);

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
          onClick={() =>
            navigateTelephonie(
              { section: "appels", filtre: "manques" },
              { reset: true }
            )
          }
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
          icon={<TrendingUp className="h-4 w-4" />}
          label="Taux de réponse"
          value={totalToday ? `${answerRate}%` : "—"}
          subtitle={`${answeredToday} / ${totalToday} répondus`}
          tone="teal"
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
                        <span className="truncate text-sm text-white">
                          {c.contact_name || c.peer_e164 || c.from_e164}
                        </span>
                        {c.caller_kind && c.caller_kind !== "unknown" ? (
                          <CallerKindBadge kind={c.caller_kind} />
                        ) : null}
                      </div>
                      <div className="truncate text-[11px] text-white/50">
                        {c.contact_name
                          ? `${c.peer_e164 || c.from_e164} · `
                          : ""}
                        {formatDateTime(c.started_at)}
                        {c.duration_sec != null ? ` · ${c.duration_sec}s` : ""}
                      </div>
                    </div>
                    <StatusBadge status={c.status} />
                  </button>
                  {/* Bouton « Rappeler » direct si l'appel a généré
                      une demande de callback (intent=callback ou
                      manqué). Sinon, juste le badge intent. */}
                  {needsCallback(c) ? (
                    <CallbackInlineButton
                      targetE164={callbackTarget(c)}
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
  onlyMissed,
  onToggleMissed,
  onOpenCall
}: {
  calls: CallRow[];
  search: string;
  onlyMissed: boolean;
  onToggleMissed: (on: boolean) => void;
  onOpenCall: (id: number) => void;
}) {
  const q = search.trim().toLowerCase();
  const missedCount = calls.filter(isMissed).length;
  const filtered = calls.filter((c) => {
    if (onlyMissed && !isMissed(c)) return false;
    if (!q) return true;
    return (
      c.from_e164.toLowerCase().includes(q) ||
      (c.peer_e164 || "").toLowerCase().includes(q) ||
      (c.contact_name || "").toLowerCase().includes(q) ||
      (c.intent || "").toLowerCase().includes(q) ||
      (c.lead_name || "").toLowerCase().includes(q) ||
      (c.caller_kind || "").toLowerCase().includes(q) ||
      (c.status || "").toLowerCase().includes(q)
    );
  });

  return (
    <section className="mt-5 rounded-2xl border border-brand-800 bg-brand-900 p-3 sm:p-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="flex items-center gap-2 text-sm font-bold text-white">
          <PhoneCall className="h-4 w-4 text-teal-300" />
          Journal d&apos;appels
          <span className="ml-2 rounded-full bg-brand-800 px-2 py-0.5 text-[10px] text-white/60">
            {filtered.length}
          </span>
        </h2>
        {/* Filtre rapide : les appels manqués à rappeler. */}
        <div className="inline-flex rounded-lg border border-brand-800 bg-brand-950 p-0.5 text-[12px]">
          <button
            type="button"
            onClick={() => onToggleMissed(false)}
            className={`rounded-md px-3 py-1.5 font-semibold transition ${
              !onlyMissed
                ? "bg-brand-800 text-white"
                : "text-white/60 hover:text-white"
            }`}
          >
            Tous
          </button>
          <button
            type="button"
            onClick={() => onToggleMissed(true)}
            className={`inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 font-semibold transition ${
              onlyMissed
                ? "bg-rose-500/15 text-rose-300"
                : "text-white/60 hover:text-white"
            }`}
          >
            <PhoneOff className="h-3.5 w-3.5" />
            Manqués
            {missedCount > 0 ? (
              <span className="rounded-full bg-rose-500/15 px-1.5 text-[10px] text-rose-300">
                {missedCount}
              </span>
            ) : null}
          </button>
        </div>
      </div>

      {filtered.length === 0 ? (
        <EmptyHint>
          {onlyMissed
            ? "Aucun appel manqué parmi les derniers appels."
            : "Aucun appel ne correspond à ta recherche."}
        </EmptyHint>
      ) : (
        <>
          {/* Téléphone : une carte par appel, bouton « Rappeler » à
              portée de pouce sur chaque appel manqué. */}
          <ul className="mt-3 divide-y divide-brand-800 md:hidden">
            {filtered.map((c) => (
              <li key={c.id} className="flex items-center gap-2 py-2.5">
                <button
                  type="button"
                  onClick={() => onOpenCall(c.id)}
                  className="flex min-w-0 flex-1 items-center gap-3 text-left"
                >
                  <DirectionIcon dir={c.direction} status={c.status} />
                  <div className="min-w-0 flex-1">
                    <div
                      className={`truncate text-sm font-semibold ${
                        isMissed(c) ? "text-rose-300" : "text-white"
                      }`}
                    >
                      {c.contact_name || c.peer_e164 || c.from_e164}
                    </div>
                    <div className="truncate text-[12px] text-white/60">
                      {c.contact_name
                        ? `${c.peer_e164 || c.from_e164} · `
                        : ""}
                      {formatDateTime(c.started_at)}
                      {c.was_voicemail ? " · message vocal" : ""}
                      {c.duration_sec != null && !isMissed(c)
                        ? ` · ${c.duration_sec}s`
                        : ""}
                    </div>
                  </div>
                </button>
                <CallActions call={c} />
              </li>
            ))}
          </ul>

          <div className="mt-3 hidden overflow-x-auto md:block">
            <table className="w-full text-xs">
              <thead className="text-left text-white/40">
                <tr>
                  <th className="py-1.5 font-normal">Date</th>
                  <th className="py-1.5 font-normal">De</th>
                  <th className="py-1.5 font-normal">Identifié</th>
                  <th className="py-1.5 font-normal">Intent</th>
                  <th className="py-1.5 font-normal">Statut</th>
                  <th className="py-1.5 text-right font-normal">Durée</th>
                  <th className="py-1.5 text-right font-normal">Actions</th>
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
                          {c.peer_e164 || c.from_e164}
                        </span>
                        {c.was_blocked ? <Tag tone="rose">blocked</Tag> : null}
                        {c.was_vip ? <Tag tone="emerald">vip</Tag> : null}
                        {c.was_voicemail ? <Tag tone="amber">vm</Tag> : null}
                      </div>
                    </td>
                    <td className="py-2">
                      {c.contact_name ? (
                        <div className="flex items-center gap-1.5">
                          <span className="text-white/90">{c.contact_name}</span>
                          {c.caller_kind && c.caller_kind !== "unknown" ? (
                            <CallerKindBadge kind={c.caller_kind} />
                          ) : null}
                        </div>
                      ) : c.caller_kind && c.caller_kind !== "unknown" ? (
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
                    <td className="py-2 text-right">
                      <CallActions call={c} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </section>
  );
}

/** Appel manqué = appel ENTRANT sans réponse (non répondu, occupé,
 *  échec, raccroché) ou laissé en message vocal. */
function isMissed(c: CallRow): boolean {
  if (c.direction === "outbound") return false;
  return (
    c.was_voicemail ||
    c.status === "no-answer" ||
    c.status === "busy" ||
    c.status === "failed" ||
    c.status === "canceled"
  );
}

/** Appel à rappeler : manqué, ou l'appelant a demandé un rappel. */
function needsCallback(c: CallRow): boolean {
  return isMissed(c) || c.intent === "callback";
}

/** Numéro à rappeler : celui laissé à Léa s'il y en a un, sinon le
 *  numéro de l'appelant (ou du destinataire pour un appel sortant). */
function callbackTarget(c: CallRow): string {
  return (
    c.lead_callback_phone ||
    c.peer_e164 ||
    (c.direction === "outbound" ? c.to_e164 : c.from_e164)
  );
}

/** Ouvre la conversation texto avec ce numéro (section Messages). */
function openSmsWith(peer: string) {
  navigateTelephonie({ section: "messages", fil: peer }, { reset: true });
}

/** Actions d'une ligne d'appel : rappel en un clic (mis en avant si
 *  l'appel est manqué) et texto. Les clics ne déclenchent pas
 *  l'ouverture du détail de la ligne. */
function CallActions({ call }: { call: CallRow }) {
  const target = callbackTarget(call);
  const peer = call.peer_e164 || target;
  return (
    <span
      className="inline-flex shrink-0 items-start justify-end gap-1.5"
      onClick={(e) => e.stopPropagation()}
    >
      {needsCallback(call) ? (
        <CallbackInlineButton
          targetE164={target}
          entityType={call.entity_type || undefined}
          entityId={call.entity_id || undefined}
        />
      ) : (
        <CallButton
          targetE164={target}
          entityType={call.entity_type || undefined}
          entityId={call.entity_id || undefined}
          label="Appeler"
          variant="icon"
        />
      )}
      {peer && peer.startsWith("+") ? (
        <button
          type="button"
          onClick={() => openSmsWith(peer)}
          title={`Texter ${peer}`}
          aria-label={`Texter ${peer}`}
          className="inline-flex h-7 w-7 items-center justify-center rounded-full border border-brand-700 bg-brand-950 text-white/70 transition hover:text-white"
        >
          <MessageSquare className="h-3.5 w-3.5" />
        </button>
      ) : null}
    </span>
  );
}

// ----------------------------------------------------------------------
// Messages (SMS) section — inbox threadée + composeur
// ----------------------------------------------------------------------

function MessagesSection({
  threads,
  selected,
  composing,
  onReload
}: {
  threads: SmsThread[];
  /** Conversation ouverte (?fil= dans l'URL). */
  selected: string | null;
  /** Composition d'un nouveau texto (?nouveau=1). */
  composing: boolean;
  onReload: () => void;
}) {
  // Grand écran : liste + conversation côte à côte, la première
  // conversation s'affiche d'office. Téléphone : la liste, puis la
  // conversation en plein écran (comme une app de messagerie) — le
  // bouton « retour » ramène à la liste.
  const isDesktop = useMediaQuery("(min-width: 1024px)");
  const shown =
    selected ||
    (isDesktop && !composing ? threads[0]?.peer_e164 || null : null);
  const chatOpen = !!shown || composing;

  const [messages, setMessages] = useState<SmsRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [threadError, setThreadError] = useState(false);
  const [reply, setReply] = useState("");
  const [sending, setSending] = useState(false);
  const [sendError, setSendError] = useState<string | null>(null);
  const [composerTo, setComposerTo] = useState("");
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const loadedPeer = useRef<string | null>(null);

  const loadThread = useCallback(
    async (peer: string, opts: { silent?: boolean } = {}) => {
      if (!opts.silent) {
        setLoading(true);
        setMessages([]);
        setThreadError(false);
      }
      try {
        const res = await authedFetch(
          `/api/v1/voice/sms?peer_e164=${encodeURIComponent(peer)}&limit=100`
        );
        if (res.ok) {
          const data = (await res.json()) as SmsRow[];
          if (loadedPeer.current !== peer) return;
          // Chrono ascendant pour l'affichage type chat.
          setMessages([...data].reverse());
          setThreadError(false);
          // Marque les entrants non lus comme lus (best-effort).
          for (const m of data) {
            if (m.direction === "inbound" && m.read_at === null) {
              void authedFetch(`/api/v1/voice/sms/${m.id}/read`, {
                method: "POST"
              });
            }
          }
        } else if (!opts.silent) {
          // Échec de chargement (ex. 500). Un 401 déclenche déjà la
          // redirection vers la connexion via authedFetch.
          setThreadError(true);
        }
      } catch {
        if (!opts.silent) setThreadError(true);
      } finally {
        if (!opts.silent) setLoading(false);
      }
    },
    []
  );

  useEffect(() => {
    loadedPeer.current = shown;
    setReply("");
    setSendError(null);
    if (!shown) return;
    void loadThread(shown);
    // Conversation ouverte : les nouveaux textos arrivent sans recharger.
    const t = setInterval(() => void loadThread(shown, { silent: true }), 15_000);
    return () => clearInterval(t);
  }, [shown, loadThread]);

  // Toujours afficher le dernier message (bas de la conversation).
  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages, shown]);

  // Téléphone : la conversation couvre l'écran — on bloque le défilement
  // de la page derrière.
  useEffect(() => {
    if (isDesktop || !chatOpen) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = prev;
    };
  }, [isDesktop, chatOpen]);

  const sendReply = useCallback(
    async (to: string, body: string): Promise<SmsRow | null> => {
      if (!to || !body.trim()) return null;
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
        const sent = (await res.json()) as SmsRow;
        setReply("");
        if (loadedPeer.current === sent.to_e164) {
          setMessages((prev) => [...prev, sent]);
        }
        onReload();
        return sent;
      } catch (err) {
        setSendError(err instanceof Error ? err.message : String(err));
        return null;
      } finally {
        setSending(false);
      }
    },
    [onReload]
  );

  const closeChat = () => closeTelephonie({ fil: null, nouveau: null });
  const thread = shown ? threads.find((t) => t.peer_e164 === shown) : null;

  return (
    <section className="mt-5 grid gap-4 pb-24 lg:grid-cols-[320px_minmax(0,1fr)] lg:pb-0">
      {/* Liste des conversations */}
      <div className="min-w-0 rounded-2xl border border-brand-800 bg-brand-900 p-2 sm:p-3">
        <div className="flex items-center justify-between gap-2 px-1 pb-2">
          <h2 className="flex items-center gap-2 text-sm font-bold text-white">
            <MessageSquare className="h-4 w-4 text-teal-300" />
            Textos
          </h2>
          <button
            type="button"
            onClick={() => {
              setComposerTo("");
              setReply("");
              navigateTelephonie({ section: "messages", nouveau: "1", fil: null });
            }}
            className="rounded-md border border-teal-500/40 bg-teal-500/10 px-3 py-1.5 text-[12px] font-semibold text-teal-200 hover:bg-teal-500/20"
          >
            + Nouveau
          </button>
        </div>
        {threads.length === 0 ? (
          <EmptyHint compact>
            Aucun texto reçu pour l&apos;instant. Texte le numéro principal
            depuis ton mobile pour tester.
          </EmptyHint>
        ) : (
          <ul className="space-y-0.5">
            {threads.map((t) => {
              const isActive = shown === t.peer_e164;
              const unread = t.unread > 0;
              const label = t.name || formatPhone(t.peer_e164);
              return (
                <li key={t.peer_e164}>
                  <button
                    type="button"
                    onClick={() =>
                      navigateTelephonie({
                        section: "messages",
                        fil: t.peer_e164,
                        nouveau: null
                      })
                    }
                    className={`flex w-full items-center gap-3 rounded-xl px-2 py-2.5 text-left transition ${
                      isActive ? "bg-teal-500/10" : "hover:bg-brand-800/40"
                    }`}
                  >
                    <Avatar label={label} />
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <span
                          className={`min-w-0 flex-1 truncate text-sm ${
                            unread ? "font-bold text-white" : "font-semibold text-white/90"
                          }`}
                        >
                          {label}
                        </span>
                        <span className="shrink-0 text-[11px] text-white/50">
                          {formatShort(t.last_message.received_at)}
                        </span>
                      </div>
                      <div className="mt-0.5 flex items-center gap-2">
                        <span
                          className={`line-clamp-2 min-w-0 flex-1 break-words text-[12px] ${
                            unread ? "text-white/90" : "text-white/60"
                          }`}
                        >
                          {t.last_message.direction === "outbound" ? "Vous : " : ""}
                          {t.last_message.body ||
                            (t.last_message.num_media > 0 ? "📷 Photo" : "(MMS)")}
                        </span>
                        {unread ? (
                          <span className="inline-flex h-5 min-w-[20px] shrink-0 items-center justify-center rounded-full bg-teal-500 px-1.5 text-[10px] font-bold text-brand-950">
                            {t.unread}
                          </span>
                        ) : null}
                      </div>
                    </div>
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </div>

      {/* Conversation — plein écran sur téléphone, colonne sur ordinateur. */}
      <div
        className={`${
          chatOpen ? "fixed inset-0 z-[55] flex" : "hidden"
        } min-w-0 flex-col bg-brand-950 lg:static lg:z-auto lg:flex lg:h-[78vh] lg:overflow-hidden lg:rounded-2xl lg:border lg:border-brand-800 lg:bg-brand-900`}
      >
        {composing && !selected ? (
          <>
            <ChatHeader
              title="Nouveau texto"
              onBack={closeChat}
            />
            <div className="flex-1 space-y-3 overflow-y-auto p-4">
              <label className="block text-[12px] font-semibold text-white/70">
                À
                <input
                  type="tel"
                  inputMode="tel"
                  autoFocus
                  placeholder="514 555-1234"
                  value={composerTo}
                  onChange={(e) => setComposerTo(e.target.value)}
                  className="mt-1 w-full rounded-lg border border-brand-800 bg-brand-900 px-3 py-2.5 text-base text-white placeholder-white/30 lg:bg-brand-950 lg:text-sm"
                />
              </label>
              {composerTo && !toE164(composerTo) ? (
                <p className="text-[12px] text-amber-300">
                  Numéro incomplet : 10 chiffres (ex. 514 555-1234).
                </p>
              ) : null}
            </div>
            <ChatComposer
              value={reply}
              onChange={setReply}
              sending={sending}
              error={sendError}
              disabled={!toE164(composerTo)}
              onSend={async () => {
                const to = toE164(composerTo);
                if (!to) return;
                const sent = await sendReply(to, reply);
                if (sent) {
                  navigateTelephonie(
                    { section: "messages", fil: sent.to_e164, nouveau: null },
                    { replace: true }
                  );
                }
              }}
            />
          </>
        ) : shown ? (
          <>
            <ChatHeader
              title={thread?.name || formatPhone(shown)}
              subtitle={thread?.name ? formatPhone(shown) : undefined}
              badge={
                thread?.caller_kind && thread.caller_kind !== "unknown" ? (
                  <CallerKindBadge kind={thread.caller_kind} />
                ) : null
              }
              onBack={closeChat}
              action={
                <CallButton
                  targetE164={shown}
                  entityType={thread?.entity_type || undefined}
                  entityId={thread?.entity_id || undefined}
                  label="Appeler"
                  variant="icon"
                  className="h-9 w-9"
                />
              }
            />
            <div
              ref={scrollRef}
              className="flex-1 overflow-y-auto overscroll-contain px-3 py-4 sm:px-4"
            >
              {loading ? (
                <p className="text-center text-[12px] text-white/50">Chargement…</p>
              ) : threadError ? (
                <p className="text-center text-[12px] text-rose-300">
                  Échec du chargement des messages. Rafraîchis, ou
                  reconnecte-toi si ta session a expiré.
                </p>
              ) : messages.length === 0 ? (
                <p className="text-center text-[12px] text-white/50">
                  Aucun message. Écris le premier ci-dessous.
                </p>
              ) : (
                <ChatBubbles messages={messages} />
              )}
            </div>
            <ChatComposer
              value={reply}
              onChange={setReply}
              sending={sending}
              error={sendError}
              onSend={() => void sendReply(shown, reply)}
            />
          </>
        ) : (
          <div className="flex flex-1 items-center justify-center p-6">
            <EmptyHint>Sélectionne une conversation à gauche.</EmptyHint>
          </div>
        )}
      </div>
    </section>
  );
}

function ChatHeader({
  title,
  subtitle,
  badge,
  action,
  onBack
}: {
  title: string;
  subtitle?: string;
  badge?: React.ReactNode;
  action?: React.ReactNode;
  onBack: () => void;
}) {
  return (
    <div className="flex items-center gap-2 border-b border-brand-800 bg-brand-900 px-2 py-2 pt-[max(0.5rem,env(safe-area-inset-top))] lg:px-4 lg:pt-2">
      <button
        type="button"
        onClick={onBack}
        className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-full text-white/80 hover:bg-brand-800 hover:text-white lg:hidden"
        aria-label="Retour aux conversations"
      >
        <ArrowLeft className="h-5 w-5" />
      </button>
      <Avatar label={title} />
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="truncate text-sm font-bold text-white">{title}</span>
          {badge}
        </div>
        {subtitle ? (
          <div className="truncate text-[12px] text-white/60">{subtitle}</div>
        ) : null}
      </div>
      {action}
    </div>
  );
}

/** Bulles de conversation : les nôtres à droite, les siennes à gauche,
 *  séparateur par jour, heure sous chaque bulle. */
function ChatBubbles({ messages }: { messages: SmsRow[] }) {
  let lastDay = "";
  return (
    <div className="space-y-1.5">
      {messages.map((m, i) => {
        const at = m.received_at || m.sent_at || "";
        const day = dayLabel(at);
        const showDay = day !== lastDay;
        lastDay = day;
        const mine = m.direction === "outbound";
        const next = messages[i + 1];
        const lastOfGroup =
          !next ||
          next.direction !== m.direction ||
          dayLabel(next.received_at || next.sent_at || "") !== day;
        const failed = m.status === "failed" || m.status === "undelivered";
        return (
          <div key={m.id}>
            {showDay ? (
              <div className="my-3 text-center text-[11px] font-semibold text-white/50">
                {day}
              </div>
            ) : null}
            <div className={`flex ${mine ? "justify-end" : "justify-start"}`}>
              <div
                className={`max-w-[82%] whitespace-pre-wrap break-words rounded-2xl px-3.5 py-2 text-[15px] leading-snug sm:max-w-[70%] ${
                  mine
                    ? `bg-teal-500/20 text-white ring-1 ring-teal-500/30 ${
                        lastOfGroup ? "rounded-br-md" : ""
                      }`
                    : `bg-brand-800 text-white ${lastOfGroup ? "rounded-bl-md" : ""}`
                }`}
              >
                {m.body}
                {m.num_media > 0 ? (
                  <MmsImages smsId={m.id} count={m.num_media} />
                ) : null}
              </div>
            </div>
            {lastOfGroup || failed ? (
              <div
                className={`mt-0.5 px-1 text-[11px] ${
                  mine ? "text-right" : "text-left"
                } ${failed ? "text-rose-300" : "text-white/50"}`}
              >
                {failed ? "Non distribué · " : ""}
                {formatTime(at)}
              </div>
            ) : null}
          </div>
        );
      })}
    </div>
  );
}

/** Zone de saisie collée en bas de la conversation. Entrée envoie sur
 *  ordinateur (Maj+Entrée = nouvelle ligne) ; sur téléphone Entrée
 *  fait une nouvelle ligne et on envoie avec le bouton. */
function ChatComposer({
  value,
  onChange,
  onSend,
  sending,
  error,
  disabled = false
}: {
  value: string;
  onChange: (v: string) => void;
  onSend: () => void;
  sending: boolean;
  error: string | null;
  disabled?: boolean;
}) {
  const ref = useRef<HTMLTextAreaElement | null>(null);
  const canSend = !sending && !disabled && !!value.trim();
  // Hauteur qui suit le texte (jusqu'à ~6 lignes).
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
  }, [value]);
  return (
    <div className="border-t border-brand-800 bg-brand-900 px-2 pt-2 pb-[max(0.5rem,env(safe-area-inset-bottom))] lg:px-3 lg:pb-3">
      {error ? (
        <p className="mb-1.5 px-1 text-[12px] text-rose-300">Erreur : {error}</p>
      ) : null}
      <div className="flex items-end gap-2">
        <textarea
          ref={ref}
          rows={1}
          placeholder="Texto…"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={(e) => {
            if (
              e.key === "Enter" &&
              !e.shiftKey &&
              !e.nativeEvent.isComposing &&
              window.matchMedia("(pointer: fine)").matches
            ) {
              e.preventDefault();
              if (canSend) onSend();
            }
          }}
          className="min-h-[42px] min-w-0 flex-1 resize-none rounded-2xl border border-brand-800 bg-brand-950 px-4 py-2.5 text-base text-white placeholder-white/40 lg:text-sm"
        />
        <button
          type="button"
          disabled={!canSend}
          onClick={onSend}
          aria-label="Envoyer"
          className="inline-flex h-[42px] w-[42px] shrink-0 items-center justify-center rounded-full border border-teal-500/40 bg-teal-500/15 text-teal-300 transition hover:bg-teal-500/25 disabled:opacity-40"
        >
          {sending ? (
            <RefreshCw className="h-4 w-4 animate-spin" />
          ) : (
            <Send className="h-4 w-4" />
          )}
        </button>
      </div>
    </div>
  );
}

function Avatar({ label }: { label: string }) {
  const letters = /[a-zA-ZÀ-ÿ]/.test(label)
    ? label
        .split(/\s+/)
        .filter(Boolean)
        .slice(0, 2)
        .map((w) => w[0]?.toUpperCase() || "")
        .join("")
    : "#";
  return (
    <span className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-teal-500/15 text-[13px] font-bold text-teal-300">
      {letters}
    </span>
  );
}

function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(false);
  useEffect(() => {
    const mq = window.matchMedia(query);
    const sync = () => setMatches(mq.matches);
    sync();
    mq.addEventListener("change", sync);
    return () => mq.removeEventListener("change", sync);
  }, [query]);
  return matches;
}

/** +15145551234 → (514) 555-1234 ; autre format laissé tel quel. */
function formatPhone(e164: string): string {
  const m = /^\+1(\d{3})(\d{3})(\d{4})$/.exec(e164);
  return m ? `(${m[1]}) ${m[2]}-${m[3]}` : e164;
}

/** Saisie libre → E.164 (+1 ajouté pour 10 chiffres), sinon null. */
function toE164(raw: string): string | null {
  const t = raw.trim();
  if (t.startsWith("+")) {
    const d = t.replace(/[^\d]/g, "");
    return d.length >= 8 ? `+${d}` : null;
  }
  const d = t.replace(/\D/g, "");
  if (d.length === 10) return `+1${d}`;
  if (d.length === 11 && d.startsWith("1")) return `+${d}`;
  return null;
}

function dayLabel(iso: string): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const today = new Date();
  const yesterday = new Date();
  yesterday.setDate(today.getDate() - 1);
  if (d.toDateString() === today.toDateString()) return "Aujourd’hui";
  if (d.toDateString() === yesterday.toDateString()) return "Hier";
  return d.toLocaleDateString("fr-CA", {
    weekday: "long",
    day: "numeric",
    month: "long",
    ...(d.getFullYear() !== today.getFullYear() ? { year: "numeric" } : {})
  });
}

function formatTime(iso: string): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleTimeString("fr-CA", { hour: "2-digit", minute: "2-digit" });
}

/** Heure si aujourd'hui, sinon date courte (liste des conversations). */
function formatShort(iso: string): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  if (d.toDateString() === new Date().toDateString()) return formatTime(iso);
  return d.toLocaleDateString("fr-CA", { day: "numeric", month: "short" });
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
            <p className="mb-1 text-[11px] text-white/50">
              Astuce : plusieurs numéros séparés par virgule = on les sonne
              tous en parallèle, le premier qui décroche gagne.
            </p>
            <ForwardField
              label="Fallback générique"
              hint="utilisé quand Léa transfère sans contexte particulier. Plusieurs numéros séparés par virgule autorisés."
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
              hint="nouveau client en transfert direct : on sonne tous ces numéros en parallèle. Plusieurs numéros séparés par virgule."
              value={n.closer_forward_e164}
              onSave={(v) =>
                patchNumber(n, { closer_forward_e164: v ?? "" })
              }
              tone="amber"
            />
            <ForwardField
              label="🏗️ Suivi projet (back-office)"
              hint="utilisé si aucun responsable de projet assigné n'est dispo. Plusieurs numéros séparés par virgule."
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
              placeholder="+15145551234, +15145559999"
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
      className="fixed inset-0 z-[55] bg-black/40 backdrop-blur-sm"
      onClick={onClose}
    >
      <aside
        onClick={(e) => e.stopPropagation()}
        className="absolute right-0 top-0 flex h-full w-full max-w-xl flex-col overflow-y-auto border-l border-brand-800 bg-brand-900 shadow-2xl"
      >
        <header className="sticky top-0 z-10 border-b border-brand-800 bg-brand-900 p-4 pt-[max(1rem,env(safe-area-inset-top))]">
          <div className="flex items-center justify-between gap-3">
          <div className="flex min-w-0 items-center gap-3">
            <button
              type="button"
              onClick={onClose}
              className="-ml-1 inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-white/70 hover:bg-brand-800 hover:text-white sm:hidden"
              aria-label="Retour"
            >
              <ArrowLeft className="h-5 w-5" />
            </button>
            <DirectionIcon dir={call.direction} status={call.status} />
            <div>
              <div className="text-base font-bold text-white">
                {call.contact_name || call.peer_e164 || call.from_e164}
              </div>
              <div className="text-[11px] text-white/50">
                {call.contact_name
                  ? `${call.peer_e164 || call.from_e164} · `
                  : ""}
                {formatDateTime(call.started_at)}
                {call.duration_sec != null ? ` · ${call.duration_sec}s` : ""}
              </div>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="hidden rounded-md p-2 text-white/60 hover:bg-brand-800 hover:text-white sm:inline-flex"
            aria-label="Fermer"
          >
            <X className="h-4 w-4" />
          </button>
          </div>
          {/* Rappel en un clic + texto, sans recomposer le numéro. */}
          <div className="mt-3 flex flex-wrap items-start gap-2">
            <CallButton
              targetE164={callbackTarget(call)}
              entityType={call.entity_type || undefined}
              entityId={call.entity_id || undefined}
              label={needsCallback(call) ? "Rappeler" : "Appeler"}
              tone={needsCallback(call) ? "amber" : "teal"}
              className="px-3 py-1.5 text-[12px]"
            />
            {(call.peer_e164 || callbackTarget(call)).startsWith("+") ? (
              <button
                type="button"
                onClick={() =>
                  openSmsWith(call.peer_e164 || callbackTarget(call))
                }
                className="inline-flex items-center gap-1.5 rounded-md border border-brand-700 bg-brand-950 px-3 py-1.5 text-[12px] font-semibold text-white/80 transition hover:text-white"
              >
                <MessageSquare className="h-3.5 w-3.5" />
                Texto
              </button>
            ) : null}
          </div>
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
      tone="amber"
      className="px-3 py-1.5 text-[12px]"
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
