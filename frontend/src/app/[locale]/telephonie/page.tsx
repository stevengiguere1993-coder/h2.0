"use client";

import { useCallback, useEffect, useState } from "react";
import {
  AlertTriangle,
  ArrowLeft,
  CheckCircle2,
  Filter,
  PhoneCall,
  PhoneForwarded,
  PhoneIncoming,
  RefreshCw,
  Sparkles,
  Workflow
} from "lucide-react";

import { authedFetch, getMe, getToken } from "@/lib/auth";
import { Link, useRouter } from "@/i18n/navigation";
import { CallButton } from "@/components/call-button";

// Volet « Téléphonie / Secrétaire d'appels ».
//
// Phase 1 : page de pilotage minimal — numéros connus + journal
// d'appels live + plan restant. Gated par email (sgiguere) en attendant
// que les rôles d'accès au volet soient câblés côté back.

const TELEPHONIE_ALLOWED_EMAILS = ["sgiguere@immohorizon.com"];

type Me = {
  email?: string | null;
};

type PhoneNumberRow = {
  id: number;
  e164: string;
  provider: string;
  label: string | null;
  forward_to_e164: string | null;
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

type CallTurnRow = {
  id: number;
  turn_index: number;
  role: string;
  text: string;
  confidence: number | null;
  created_at: string;
};


export default function TelephonieHome() {
  const router = useRouter();
  const [checking, setChecking] = useState(true);
  const [allowed, setAllowed] = useState(false);

  const [numbers, setNumbers] = useState<PhoneNumberRow[]>([]);
  const [calls, setCalls] = useState<CallRow[]>([]);
  const [filters, setFilters] = useState<FilterRow[]>([]);
  const [hours, setHours] = useState<BusinessHoursRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [expandedCallId, setExpandedCallId] = useState<number | null>(null);
  const [turnsByCallId, setTurnsByCallId] = useState<Record<number, CallTurnRow[]>>({});

  const patchNumber = useCallback(
    async (n: PhoneNumberRow, patch: Partial<PhoneNumberRow>) => {
      // Optimistic update
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
        // Rollback
        setNumbers((prev) =>
          prev.map((row) => (row.id === n.id ? n : row))
        );
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
      // Confirmation explicite à l'activation — c'est CE flag qui
      // déclenche les appels vers de vrais clients.
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

  const expandCall = useCallback(async (callId: number) => {
    if (expandedCallId === callId) {
      setExpandedCallId(null);
      return;
    }
    setExpandedCallId(callId);
    if (turnsByCallId[callId]) return;
    try {
      const res = await authedFetch(`/api/v1/voice/calls/${callId}/turns`);
      if (!res.ok) throw new Error(`turns http_${res.status}`);
      const data = (await res.json()) as CallTurnRow[];
      setTurnsByCallId((prev) => ({ ...prev, [callId]: data }));
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : String(err));
    }
  }, [expandedCallId, turnsByCallId]);

  const reload = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const [nRes, cRes, fRes] = await Promise.all([
        authedFetch("/api/v1/voice/phone-numbers"),
        authedFetch("/api/v1/voice/calls?limit=30"),
        authedFetch("/api/v1/voice/filters")
      ]);
      if (!nRes.ok) throw new Error(`numbers http_${nRes.status}`);
      if (!cRes.ok) throw new Error(`calls http_${cRes.status}`);
      if (!fRes.ok) throw new Error(`filters http_${fRes.status}`);
      const nums = (await nRes.json()) as PhoneNumberRow[];
      setNumbers(nums);
      setCalls((await cRes.json()) as CallRow[]);
      setFilters((await fRes.json()) as FilterRow[]);
      // Heures : on charge celles du 1er numéro (Phase 3 = 1 numéro).
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

  const addFilter = useCallback(
    async (phoneNumberId: number, kind: "block" | "vip", pattern: string, label: string) => {
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
    async (phoneNumberId: number, rows: { day_of_week: number; open_time: string; close_time: string }[]) => {
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
        const ok = TELEPHONIE_ALLOWED_EMAILS.includes(email);
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
            <ArrowLeft className="h-3 w-3" />
            Retour au sélecteur de portail
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-brand-950 text-white">
      <div className="mx-auto max-w-4xl px-5 py-8">
        <Link
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          href={"/connexion" as any}
          className="inline-flex items-center text-xs text-white/60 hover:text-teal-300"
        >
          <ArrowLeft className="mr-1 h-3.5 w-3.5" />
          Retour au sélecteur de portail
        </Link>

        <header className="mt-4 flex items-start justify-between gap-3">
          <div>
            <div className="flex items-center gap-2 text-xs uppercase tracking-wider text-teal-300">
              <PhoneCall className="h-4 w-4" />
              Téléphonie
            </div>
            <h1 className="mt-1 text-3xl font-bold">
              Secrétaire IA d&apos;appels
            </h1>
            <p className="mt-1 text-sm text-white/60">
              Numéro 438 unique, secrétaire IA bilingue qui décroche,
              qualifie et transfère — désactivable par numéro (fallback
              transfert direct).
            </p>
          </div>
          <span className="shrink-0 rounded-full border border-emerald-500/40 bg-emerald-500/10 px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wider text-emerald-300">
            Toutes phases livrées
          </span>
        </header>

        {/* Live data */}
        <section className="mt-6 rounded-2xl border border-white/10 bg-white/[0.02] p-5">
          <div className="flex items-center justify-between gap-3">
            <h2 className="flex items-center gap-2 text-sm font-bold text-white">
              <PhoneIncoming className="h-4 w-4 text-teal-300" />
              Numéros configurés
            </h2>
            <button
              type="button"
              onClick={() => void reload()}
              disabled={loading}
              className="inline-flex items-center gap-1.5 rounded-md border border-white/10 bg-white/5 px-2.5 py-1 text-[11px] text-white/70 hover:bg-white/10 disabled:opacity-50"
            >
              <RefreshCw className={`h-3 w-3 ${loading ? "animate-spin" : ""}`} />
              Rafraîchir
            </button>
          </div>

          {loadError ? (
            <p className="mt-3 rounded-md border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-[11px] text-rose-200">
              Erreur de chargement : {loadError}
            </p>
          ) : null}

          {numbers.length === 0 && !loading && !loadError ? (
            <p className="mt-3 rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-[11px] text-amber-200">
              Aucun numéro enregistré. Le bootstrap se déclenche au prochain
              démarrage du backend si TWILIO_PHONE_NUMBER est configuré côté
              Render.
            </p>
          ) : null}

          {numbers.length > 0 ? (
            <table className="mt-3 w-full text-xs">
              <thead className="text-left text-white/40">
                <tr>
                  <th className="py-1.5 font-normal">Numéro</th>
                  <th className="py-1.5 font-normal">Libellé</th>
                  <th className="py-1.5 font-normal">Forward vers</th>
                  <th className="py-1.5 font-normal">Secrétaire IA</th>
                  <th className="py-1.5 font-normal">Rappel auto leads</th>
                  <th className="py-1.5 text-right font-normal">État</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/10">
                {numbers.map((n) => (
                  <tr key={n.id}>
                    <td className="py-2 font-mono text-white">{n.e164}</td>
                    <td className="py-2 text-white/70">{n.label || "—"}</td>
                    <td className="py-2 font-mono text-white/80">
                      {n.forward_to_e164 || (
                        <span className="text-white/30">non configuré</span>
                      )}
                    </td>
                    <td className="py-2">
                      <button
                        type="button"
                        onClick={() => void toggleSecretary(n)}
                        className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wider transition ${
                          n.secretary_mode_active
                            ? "bg-amber-500/20 text-amber-200 hover:bg-amber-500/30"
                            : "bg-white/5 text-white/50 hover:bg-white/10"
                        }`}
                        title={
                          n.secretary_mode_active
                            ? "Cliquer pour désactiver — retour au transfert direct"
                            : "Cliquer pour activer — l'IA décroche et qualifie"
                        }
                      >
                        <Sparkles className="h-3 w-3" />
                        {n.secretary_mode_active ? "activée" : "désactivée"}
                      </button>
                    </td>
                    <td className="py-2">
                      <button
                        type="button"
                        onClick={() => void toggleAutoCallback(n)}
                        className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wider transition ${
                          n.lead_auto_callback_enabled
                            ? "bg-emerald-500/20 text-emerald-200 hover:bg-emerald-500/30"
                            : "bg-white/5 text-white/50 hover:bg-white/10"
                        }`}
                        title={
                          n.lead_auto_callback_enabled
                            ? "Cliquer pour désactiver — les nouveaux leads ne seront plus rappelés automatiquement"
                            : "Cliquer pour activer — Léa rappellera automatiquement chaque nouveau lead 60 sec après création"
                        }
                      >
                        <PhoneForwarded className="h-3 w-3" />
                        {n.lead_auto_callback_enabled ? "actif" : "désactivé"}
                      </button>
                    </td>
                    <td className="py-2 text-right">
                      {n.active ? (
                        <span className="text-emerald-300">actif</span>
                      ) : (
                        <span className="text-white/40">inactif</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : null}
        </section>

        {/* Test click-to-call (Phase 4) */}
        {numbers.length > 0 ? (
          <section className="mt-4 rounded-2xl border border-white/10 bg-white/[0.02] p-5">
            <h2 className="flex items-center gap-2 text-sm font-bold text-white">
              <PhoneForwarded className="h-4 w-4 text-emerald-300" />
              Test sortant (click-to-call)
            </h2>
            <p className="mt-1 text-[11px] text-white/40">
              Twilio appellera d&apos;abord ton mobile interne, puis
              bridgera vers la cible.
            </p>
            <OutboundTester />
          </section>
        ) : null}

        {/* Filtres + Heures (Phase 3) */}
        {numbers.length > 0 ? (
          <>
            <FiltersSection
              phoneNumberId={numbers[0].id}
              filters={filters.filter((f) => f.phone_number_id === numbers[0].id)}
              onAdd={addFilter}
              onDelete={deleteFilter}
            />
            <BusinessHoursSection
              phoneNumberId={numbers[0].id}
              hours={hours}
              onSave={saveHours}
            />
          </>
        ) : null}

        {/* Call log */}
        <section className="mt-4 rounded-2xl border border-white/10 bg-white/[0.02] p-5">
          <h2 className="flex items-center gap-2 text-sm font-bold text-white">
            <PhoneCall className="h-4 w-4 text-teal-300" />
            Journal d&apos;appels (30 derniers)
          </h2>
          {calls.length === 0 ? (
            <p className="mt-3 text-[11px] text-white/40">
              Aucun appel reçu pour l&apos;instant. Appelle le numéro
              ci-dessus depuis un mobile vérifié sur Twilio pour tester.
            </p>
          ) : (
            <table className="mt-3 w-full text-xs">
              <thead className="text-left text-white/40">
                <tr>
                  <th className="py-1.5 font-normal">Date</th>
                  <th className="py-1.5 font-normal">De</th>
                  <th className="py-1.5 font-normal">Intent</th>
                  <th className="py-1.5 font-normal">Statut</th>
                  <th className="py-1.5 text-right font-normal">Durée</th>
                  <th className="py-1.5 text-right font-normal" />
                </tr>
              </thead>
              <tbody className="divide-y divide-white/10">
                {calls.map((c) => (
                  <CallRowItem
                    key={c.id}
                    call={c}
                    expanded={expandedCallId === c.id}
                    turns={turnsByCallId[c.id]}
                    onToggle={() => void expandCall(c.id)}
                  />
                ))}
              </tbody>
            </table>
          )}
        </section>

        {/* Plan en 4 phases */}
        <h2 className="mt-8 text-sm font-bold uppercase tracking-wider text-white/70">
          Plan de livraison
        </h2>
        <div className="mt-3 space-y-3">
          <PhaseCard
            num={1}
            title="Fondations"
            icon={<PhoneIncoming className="h-4 w-4 text-teal-300" />}
            scope="1-2 PR"
            status="done"
          >
            <ul className="space-y-1">
              <li>
                Module backend <code>app/integrations/voice/</code>, abstraction
                provider (Twilio par défaut). ✓
              </li>
              <li>
                Modèles SQL : <code>PhoneNumber</code>, <code>Call</code>,{" "}
                <code>CallRoute</code>, <code>CallTranscript</code>. ✓
              </li>
              <li>Endpoint webhook Twilio (signature HMAC vérifiée). ✓</li>
              <li>
                Bootstrap automatique au démarrage du backend : numéro 438
                enregistré + voice_url poussée chez Twilio. ✓
              </li>
              <li>
                Dispatch simple : appel entrant →{" "}
                <code>&lt;Dial&gt;</code> vers <code>TWILIO_FORWARD_TO</code>. ✓
              </li>
              <li>
                Page <code>/telephonie</code> : journal d&apos;appels live. ✓
              </li>
            </ul>
          </PhaseCard>

          <PhaseCard
            num={2}
            title="Secrétaire IA (qualification + dispatch)"
            icon={<Sparkles className="h-4 w-4 text-amber-300" />}
            scope="2-3 PR"
            status="in_progress"
          >
            <ul className="space-y-1">
              <li>
                Décroche + salutation française/anglaise naturelle
                (Polly Neural). ✓
              </li>
              <li>
                Capture nom + raison de l&apos;appel + numéro de rappel,
                tour-par-tour via Claude (cascade Gemini → Anthropic →
                Groq). ✓
              </li>
              <li>
                Création automatique d&apos;un ContactRequest CRM quand
                l&apos;appelant demande à être rappelé. ✓
              </li>
              <li>
                Transfert direct vers <code>forward_to_e164</code> quand
                l&apos;intent est clair (rénovation / logiciel / gestion
                immo / urgence). ✓
              </li>
              <li>
                Toggle activable par numéro depuis cette page. ✓
              </li>
              <li>
                Reste à faire : prise de RDV intégrée à l&apos;agenda
                + résumé structuré post-appel.
              </li>
            </ul>
          </PhaseCard>

          <PhaseCard
            num={3}
            title="Filtres & règles intelligentes"
            icon={<Filter className="h-4 w-4 text-violet-300" />}
            scope="1-2 PR"
            status="done"
          >
            <ul className="space-y-1">
              <li>
                Heures d&apos;ouverture par jour de semaine (timezone
                Montréal) — hors heures → voicemail IA. ✓
              </li>
              <li>
                Blocklist : pattern E.164 exact ou préfixe (<code>+1438*</code>),
                rejet immédiat (tonalité d&apos;occupation). ✓
              </li>
              <li>
                Whitelist VIP : sonne direct sans passer par la secrétaire
                IA, même si elle est activée. ✓
              </li>
              <li>
                Voicemail IA : <code>&lt;Record&gt;</code> + transcription
                Twilio + résumé Claude + notification cloche +
                ContactRequest CRM. ✓
              </li>
              <li>
                Reste à faire : file d&apos;attente si tous les users sont
                occupés (Phase 3.5 si besoin).
              </li>
            </ul>
          </PhaseCard>

          <PhaseCard
            num={4}
            title="Sortant + intégration CRM"
            icon={<PhoneForwarded className="h-4 w-4 text-emerald-300" />}
            scope="1-2 PR"
            status="done"
          >
            <ul className="space-y-1">
              <li>
                Composant <code>&lt;CallButton&gt;</code> réutilisable :
                click-to-call qui sonne ton mobile puis bridge vers la
                cible. Wired sur la fiche Prospection (à côté du
                téléphone propriétaire). ✓
              </li>
              <li>
                Journalisation : chaque appel sortant est créé dans{" "}
                <code>voice_calls</code> avec <code>entity_type</code> +
                <code>entity_id</code> → filtrable par fiche via
                <code>GET /voice/calls?entity_type=&amp;entity_id=</code>. ✓
              </li>
              <li>
                Bouton « Suggérer un suivi » par appel : Claude analyse
                le contexte (intent, voicemail, tours secrétaire) et
                propose une action en 2 phrases. ✓
              </li>
              <li>
                Reste à faire : créer un Follow-up agenda d&apos;un clic
                depuis la suggestion (Phase 4.5 si besoin).
              </li>
            </ul>
          </PhaseCard>
        </div>

        {/* Coûts récap */}
        <section className="mt-8 rounded-2xl border border-white/10 bg-white/[0.02] p-5">
          <h2 className="flex items-center gap-2 text-sm font-bold text-white">
            <Workflow className="h-4 w-4 text-white/60" />
            Coûts attendus
          </h2>
          <table className="mt-3 w-full text-xs">
            <tbody className="divide-y divide-white/10">
              <tr>
                <td className="py-2 text-white/70">Trial Twilio</td>
                <td className="py-2 text-right text-emerald-300">
                  0 $ (~15 USD de crédit, plusieurs mois)
                </td>
              </tr>
              <tr>
                <td className="py-2 text-white/70">Numéro 438 (prod)</td>
                <td className="py-2 text-right text-white/90">~1,15 $/mois</td>
              </tr>
              <tr>
                <td className="py-2 text-white/70">Appels entrants</td>
                <td className="py-2 text-right text-white/90">~0,01 $/min</td>
              </tr>
              <tr>
                <td className="py-2 text-white/70">
                  IA (cascade Gemini → Anthropic → Groq)
                </td>
                <td className="py-2 text-right text-emerald-300">
                  0 $ (tier gratuit Gemini suffit)
                </td>
              </tr>
              <tr>
                <td className="py-2 font-semibold text-white">
                  Total croisière prod
                </td>
                <td className="py-2 text-right font-semibold text-teal-300">
                  ~5-20 $/mois
                </td>
              </tr>
            </tbody>
          </table>
          <p className="mt-3 text-[11px] text-white/40">
            Alternative cheap (VoIP.ms) restera possible plus tard — le
            module est déjà codé avec une abstraction provider pour qu&apos;on
            puisse swap sans réécrire le frontend.
          </p>
        </section>

        {/* CTA */}
        <div className="mt-8 rounded-2xl border border-amber-500/40 bg-amber-500/10 p-4 text-center">
          <Sparkles className="mx-auto mb-1.5 h-5 w-5 text-amber-300" />
          <p className="text-sm font-semibold text-white">
            Active la secrétaire IA pour tester
          </p>
          <p className="mt-1 text-xs text-white/70">
            Bouton « Secrétaire IA » dans le tableau des numéros ci-dessus.
            Une fois activée, appelle le numéro : l&apos;IA décroche,
            comprend ta demande et soit te transfère, soit prend un
            message. Clique sur un appel dans le journal pour voir la
            transcription tour-par-tour.
          </p>
        </div>
      </div>
    </div>
  );
}

function CallRowItem({
  call,
  expanded,
  turns,
  onToggle
}: {
  call: CallRow;
  expanded: boolean;
  turns: CallTurnRow[] | undefined;
  onToggle: () => void;
}) {
  return (
    <>
      <tr className="cursor-pointer hover:bg-white/[0.03]" onClick={onToggle}>
        <td className="py-2 text-white/60">{formatDateTime(call.started_at)}</td>
        <td className="py-2 font-mono text-white">
          {call.from_e164}
          {call.was_blocked ? (
            <span className="ml-1.5 rounded bg-rose-500/20 px-1 text-[9px] uppercase tracking-wide text-rose-300">
              blocked
            </span>
          ) : null}
          {call.was_vip ? (
            <span className="ml-1.5 rounded bg-emerald-500/20 px-1 text-[9px] uppercase tracking-wide text-emerald-300">
              vip
            </span>
          ) : null}
          {call.was_voicemail ? (
            <span className="ml-1.5 rounded bg-amber-500/20 px-1 text-[9px] uppercase tracking-wide text-amber-300">
              voicemail
            </span>
          ) : null}
        </td>
        <td className="py-2 text-white/80">
          <span className="mr-1 text-[9px] uppercase tracking-wide text-white/40">
            {call.direction === "outbound" ? "↗" : "↘"}
          </span>
          {call.intent ? (
            <IntentBadge intent={call.intent} />
          ) : (
            <span className="text-white/30">—</span>
          )}
          {call.entity_type ? (
            <span className="ml-1.5 rounded bg-violet-500/15 px-1 text-[9px] uppercase tracking-wide text-violet-300">
              {call.entity_type}#{call.entity_id}
            </span>
          ) : null}
        </td>
        <td className="py-2">
          <StatusBadge status={call.status} />
        </td>
        <td className="py-2 text-right text-white/80">
          {call.duration_sec != null ? `${call.duration_sec}s` : "—"}
        </td>
        <td className="py-2 text-right text-white/40">
          {expanded ? "▾" : "▸"}
        </td>
      </tr>
      {expanded ? (
        <tr>
          <td colSpan={6} className="bg-white/[0.02] p-3">
            {call.was_voicemail ? (
              <div className="mb-3 rounded-md border border-amber-500/30 bg-amber-500/5 p-3 text-[11px] text-white/80">
                <div className="mb-1 font-semibold text-amber-200">
                  Voicemail
                </div>
                {call.voicemail_summary ? (
                  <div className="mb-2 italic text-amber-100">
                    Résumé IA : {call.voicemail_summary}
                  </div>
                ) : null}
                {call.voicemail_transcription ? (
                  <div className="whitespace-pre-wrap">
                    {call.voicemail_transcription}
                  </div>
                ) : (
                  <div className="text-white/40">
                    Transcription en cours… (Twilio prend 5-15 sec après
                    l&apos;enregistrement)
                  </div>
                )}
                {call.recording_url ? (
                  <a
                    href={call.recording_url}
                    target="_blank"
                    rel="noreferrer"
                    className="mt-2 inline-block rounded-md border border-amber-500/40 px-2 py-1 text-[10px] text-amber-200 hover:bg-amber-500/10"
                  >
                    ▶ Écouter
                  </a>
                ) : null}
              </div>
            ) : null}
            {call.lead_name || call.lead_callback_phone || call.lead_reason ? (
              <div className="mb-3 rounded-md border border-teal-500/30 bg-teal-500/5 p-3 text-[11px] text-white/80">
                <div className="mb-1 font-semibold text-teal-200">
                  Lead capturé
                </div>
                {call.lead_name ? <div>Nom : {call.lead_name}</div> : null}
                {call.lead_callback_phone ? (
                  <div>Rappel : {call.lead_callback_phone}</div>
                ) : null}
                {call.lead_reason ? <div>Raison : {call.lead_reason}</div> : null}
                {call.contact_request_id ? (
                  <div className="mt-1 text-teal-300">
                    Fiche CRM #{call.contact_request_id} créée
                  </div>
                ) : null}
              </div>
            ) : null}
            {turns === undefined ? (
              <p className="text-[11px] text-white/40">Chargement…</p>
            ) : turns.length === 0 ? (
              <p className="text-[11px] text-white/40">
                Pas de transcription (transfert direct, pas de secrétaire IA
                sur cet appel).
              </p>
            ) : (
              <ul className="space-y-2">
                {turns.map((t) => (
                  <li
                    key={t.id}
                    className={`rounded-md p-2 text-[11px] ${
                      t.role === "assistant"
                        ? "bg-teal-500/10 text-teal-100"
                        : "bg-white/5 text-white/80"
                    }`}
                  >
                    <span className="mr-2 font-semibold uppercase tracking-wide text-[9px] opacity-60">
                      {t.role === "assistant" ? "Secrétaire" : "Appelant"}
                    </span>
                    {t.text}
                  </li>
                ))}
              </ul>
            )}
            <SuggestFollowupBlock call={call} />
          </td>
        </tr>
      ) : null}
    </>
  );
}

function SuggestFollowupBlock({ call }: { call: CallRow }) {
  const [suggestion, setSuggestion] = useState<string | null>(
    call.followup_suggestion
  );
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function ask() {
    setBusy(true);
    setErr(null);
    try {
      const res = await authedFetch(
        `/api/v1/voice/calls/${call.id}/suggest-followup`,
        { method: "POST" }
      );
      if (!res.ok) throw new Error(`http_${res.status}`);
      const data = (await res.json()) as { suggestion: string };
      setSuggestion(data.suggestion);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mt-3 rounded-md border border-violet-500/20 bg-violet-500/5 p-3 text-[11px] text-white/80">
      <div className="mb-1 flex items-center justify-between gap-2">
        <span className="font-semibold text-violet-200">Suivi suggéré (IA)</span>
        <button
          type="button"
          onClick={ask}
          disabled={busy}
          className="rounded-md border border-violet-500/40 px-2 py-0.5 text-[10px] text-violet-200 hover:bg-violet-500/10 disabled:opacity-50"
        >
          {busy ? "…" : suggestion ? "Régénérer" : "Générer"}
        </button>
      </div>
      {suggestion ? (
        <p className="whitespace-pre-wrap">{suggestion}</p>
      ) : (
        <p className="text-white/40">
          Pas encore de suggestion. Clique sur Générer pour demander à
          l&apos;IA quoi faire après cet appel.
        </p>
      )}
      {err ? <p className="mt-1 text-rose-300">{err}</p> : null}
    </div>
  );
}

function IntentBadge({ intent }: { intent: string }) {
  const map: Record<string, { label: string; cls: string }> = {
    renovation: { label: "rénovation", cls: "bg-teal-500/15 text-teal-300" },
    dev_logiciel: { label: "logiciel", cls: "bg-violet-500/15 text-violet-300" },
    gestion_immo: { label: "gestion immo", cls: "bg-blue-500/15 text-blue-300" },
    urgence: { label: "urgence", cls: "bg-rose-500/15 text-rose-300" },
    callback: { label: "rappel", cls: "bg-amber-500/15 text-amber-300" },
    spam: { label: "spam", cls: "bg-white/10 text-white/40" },
    unclear: { label: "indéfini", cls: "bg-white/10 text-white/40" }
  };
  const meta = map[intent] || { label: intent, cls: "bg-white/10 text-white/60" };
  return (
    <span
      className={`inline-block rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${meta.cls}`}
    >
      {meta.label}
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
  const meta = known[status] || { label: status, cls: "bg-white/10 text-white/60" };
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

const DAY_LABELS = ["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"];

function OutboundTester() {
  const [target, setTarget] = useState("");
  return (
    <div className="mt-3 flex flex-wrap items-center gap-2">
      <input
        type="tel"
        placeholder="+15146191111"
        value={target}
        onChange={(e) => setTarget(e.target.value)}
        className="flex-1 min-w-[200px] rounded-md border border-white/10 bg-white/5 px-2 py-1 text-xs text-white placeholder-white/30"
      />
      <CallButton targetE164={target} />
    </div>
  );
}

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
    <section className="mt-4 rounded-2xl border border-white/10 bg-white/[0.02] p-5">
      <h2 className="flex items-center gap-2 text-sm font-bold text-white">
        <Filter className="h-4 w-4 text-violet-300" />
        Filtres (blocklist + VIP)
      </h2>
      <p className="mt-1 text-[11px] text-white/40">
        Pattern : numéro exact (<code>+14385551234</code>), préfixe avec
        astérisque (<code>+1438*</code>) ou vide = match-tout.
      </p>

      <div className="mt-4 grid gap-3 md:grid-cols-2">
        <div>
          <h3 className="text-[11px] font-semibold uppercase tracking-wider text-rose-300">
            Blocklist ({blocks.length})
          </h3>
          {blocks.length === 0 ? (
            <p className="mt-2 text-[11px] text-white/40">Aucun blocage.</p>
          ) : (
            <ul className="mt-2 space-y-1">
              {blocks.map((f) => (
                <FilterItem key={f.id} f={f} onDelete={() => onDelete(f.id)} />
              ))}
            </ul>
          )}
        </div>
        <div>
          <h3 className="text-[11px] font-semibold uppercase tracking-wider text-emerald-300">
            VIP — ring direct ({vips.length})
          </h3>
          {vips.length === 0 ? (
            <p className="mt-2 text-[11px] text-white/40">Aucun VIP.</p>
          ) : (
            <ul className="mt-2 space-y-1">
              {vips.map((f) => (
                <FilterItem key={f.id} f={f} onDelete={() => onDelete(f.id)} />
              ))}
            </ul>
          )}
        </div>
      </div>

      <div className="mt-4 flex flex-wrap items-end gap-2 border-t border-white/5 pt-4">
        <select
          value={kind}
          onChange={(e) => setKind(e.target.value as "block" | "vip")}
          className="rounded-md border border-white/10 bg-white/5 px-2 py-1 text-xs text-white"
        >
          <option value="block">Bloquer</option>
          <option value="vip">VIP</option>
        </select>
        <input
          type="text"
          placeholder="Pattern (ex: +14385551234)"
          value={pattern}
          onChange={(e) => setPattern(e.target.value)}
          className="min-w-[180px] flex-1 rounded-md border border-white/10 bg-white/5 px-2 py-1 text-xs text-white placeholder-white/30"
        />
        <input
          type="text"
          placeholder="Libellé (optionnel)"
          value={label}
          onChange={(e) => setLabel(e.target.value)}
          className="min-w-[140px] flex-1 rounded-md border border-white/10 bg-white/5 px-2 py-1 text-xs text-white placeholder-white/30"
        />
        <button
          type="button"
          onClick={() => {
            if (!pattern.trim() && !confirm("Sans pattern, ce filtre s'applique à TOUS les appels. Continuer ?")) return;
            onAdd(phoneNumberId, kind, pattern, label);
            setPattern("");
            setLabel("");
          }}
          className="rounded-md border border-teal-500/40 bg-teal-500/10 px-3 py-1 text-xs font-semibold text-teal-200 hover:bg-teal-500/20"
        >
          Ajouter
        </button>
      </div>
    </section>
  );
}

function FilterItem({ f, onDelete }: { f: FilterRow; onDelete: () => void }) {
  return (
    <li className="flex items-center justify-between gap-2 rounded-md bg-white/5 px-2 py-1 text-[11px]">
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
        ✕
      </button>
    </li>
  );
}

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
  // État local par jour : enabled + open + close.
  type DayState = { enabled: boolean; open: string; close: string };
  const init = (): DayState[] =>
    DAY_LABELS.map((_, dow) => {
      const existing = hours.find((h) => h.day_of_week === dow);
      return existing
        ? { enabled: true, open: existing.open_time, close: existing.close_time }
        : { enabled: false, open: "09:00", close: "17:00" };
    });

  const [days, setDays] = useState<DayState[]>(init);

  // Re-sync si les heures fetched changent (après reload).
  useEffect(() => {
    setDays(init());
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hours]);

  const update = (i: number, patch: Partial<DayState>) =>
    setDays((prev) => prev.map((d, idx) => (idx === i ? { ...d, ...patch } : d)));

  const save = () => {
    const rows = days
      .map((d, dow) => ({ enabled: d.enabled, day_of_week: dow, open_time: d.open, close_time: d.close }))
      .filter((r) => r.enabled)
      .map(({ enabled: _ignore, ...rest }) => rest);
    onSave(phoneNumberId, rows);
  };

  return (
    <section className="mt-4 rounded-2xl border border-white/10 bg-white/[0.02] p-5">
      <h2 className="flex items-center gap-2 text-sm font-bold text-white">
        <Workflow className="h-4 w-4 text-blue-300" />
        Heures d&apos;ouverture (timezone Montréal)
      </h2>
      <p className="mt-1 text-[11px] text-white/40">
        Hors heures → voicemail IA (enregistrement + transcription + résumé).
        Aucun jour activé = ouvert 24/7.
      </p>
      <div className="mt-3 space-y-1.5">
        {days.map((d, i) => (
          <div key={i} className="flex items-center gap-3 text-xs">
            <label className="flex w-20 items-center gap-2 text-white/80">
              <input
                type="checkbox"
                checked={d.enabled}
                onChange={(e) => update(i, { enabled: e.target.checked })}
                className="h-3 w-3"
              />
              {DAY_LABELS[i]}
            </label>
            <input
              type="time"
              value={d.open}
              onChange={(e) => update(i, { open: e.target.value })}
              disabled={!d.enabled}
              className="rounded-md border border-white/10 bg-white/5 px-2 py-1 text-white disabled:opacity-40"
            />
            <span className="text-white/40">→</span>
            <input
              type="time"
              value={d.close}
              onChange={(e) => update(i, { close: e.target.value })}
              disabled={!d.enabled}
              className="rounded-md border border-white/10 bg-white/5 px-2 py-1 text-white disabled:opacity-40"
            />
          </div>
        ))}
      </div>
      <button
        type="button"
        onClick={save}
        className="mt-3 rounded-md border border-teal-500/40 bg-teal-500/10 px-3 py-1 text-xs font-semibold text-teal-200 hover:bg-teal-500/20"
      >
        Enregistrer les heures
      </button>
    </section>
  );
}

function PhaseCard({
  num,
  title,
  icon,
  scope,
  status,
  children
}: {
  num: number;
  title: string;
  icon: React.ReactNode;
  scope: string;
  status: "todo" | "in_progress" | "done";
  children: React.ReactNode;
}) {
  return (
    <div className="rounded-2xl border border-white/10 bg-white/[0.02] p-5">
      <header className="flex items-start justify-between gap-3 border-b border-white/10 pb-3">
        <div className="flex items-center gap-3">
          <span className="flex h-8 w-8 items-center justify-center rounded-full bg-white/10 text-xs font-bold text-white">
            {num}
          </span>
          <div>
            <h3 className="flex items-center gap-1.5 text-base font-bold text-white">
              {icon}
              {title}
            </h3>
            <p className="text-[11px] text-white/40">{scope}</p>
          </div>
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
            ? "Terminé"
            : status === "in_progress"
              ? "En cours"
              : "À faire"}
        </span>
      </header>
      <div className="mt-3 text-xs text-white/70">{children}</div>
    </div>
  );
}
