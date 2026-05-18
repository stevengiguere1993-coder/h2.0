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
};

export default function TelephonieHome() {
  const router = useRouter();
  const [checking, setChecking] = useState(true);
  const [allowed, setAllowed] = useState(false);

  const [numbers, setNumbers] = useState<PhoneNumberRow[]>([]);
  const [calls, setCalls] = useState<CallRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const [nRes, cRes] = await Promise.all([
        authedFetch("/api/v1/voice/phone-numbers"),
        authedFetch("/api/v1/voice/calls?limit=30")
      ]);
      if (!nRes.ok) throw new Error(`numbers http_${nRes.status}`);
      if (!cRes.ok) throw new Error(`calls http_${cRes.status}`);
      setNumbers((await nRes.json()) as PhoneNumberRow[]);
      setCalls((await cRes.json()) as CallRow[]);
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

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
              Numéro 438 unique, appels entrants forwardés au mobile en
              Phase 1. Secrétaire IA et qualification automatique en
              Phase 2.
            </p>
          </div>
          <span className="shrink-0 rounded-full border border-emerald-500/40 bg-emerald-500/10 px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wider text-emerald-300">
            Phase 1 active
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
                  <th className="py-1.5 font-normal">Vers</th>
                  <th className="py-1.5 font-normal">Statut</th>
                  <th className="py-1.5 text-right font-normal">Durée</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/10">
                {calls.map((c) => (
                  <tr key={c.id}>
                    <td className="py-2 text-white/60">
                      {formatDateTime(c.started_at)}
                    </td>
                    <td className="py-2 font-mono text-white">{c.from_e164}</td>
                    <td className="py-2 font-mono text-white/80">{c.to_e164}</td>
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
            status="todo"
          >
            <ul className="space-y-1">
              <li>
                Décroche + salutation française naturelle (Twilio
                ConversationRelay ou Anthropic + ElevenLabs TTS).
              </li>
              <li>
                Capture nom + raison de l&apos;appel + numéro de rappel
                si nécessaire.
              </li>
              <li>
                Création automatique d&apos;un lead CRM selon l&apos;intent
                détecté (construction / dev IA / gestion immo / autre).
              </li>
              <li>
                Transfert vers le bon user selon l&apos;intent et la
                disponibilité.
              </li>
              <li>
                Prise de RDV intégrée à ton agenda existant (créneaux
                libres).
              </li>
              <li>
                Transcription complète + résumé structuré (décisions,
                actions) après chaque appel — réutilise la cascade IA
                déjà en place.
              </li>
            </ul>
          </PhaseCard>

          <PhaseCard
            num={3}
            title="Filtres & règles intelligentes"
            icon={<Filter className="h-4 w-4 text-violet-300" />}
            scope="1-2 PR"
            status="todo"
          >
            <ul className="space-y-1">
              <li>
                Heures d&apos;ouverture (hors heures → voicemail IA).
              </li>
              <li>
                Blocklist (spam / démarchage / robocalls) — raccroche
                poliment ou met en boîte vocale.
              </li>
              <li>
                Whitelist VIP (clients existants, partenaires) — sonne
                direct sans passer par l&apos;IA.
              </li>
              <li>File d&apos;attente si tous les users sont occupés.</li>
              <li>Voicemail IA qui transcrit + résume + notifie.</li>
            </ul>
          </PhaseCard>

          <PhaseCard
            num={4}
            title="Sortant + intégration CRM"
            icon={<PhoneForwarded className="h-4 w-4 text-emerald-300" />}
            scope="1-2 PR"
            status="todo"
          >
            <ul className="space-y-1">
              <li>
                Bouton « click-to-call » depuis n&apos;importe quelle
                fiche prospect / client / contact.
              </li>
              <li>
                Journalisation automatique de l&apos;appel sortant dans
                la fiche concernée (durée, transcription, résumé).
              </li>
              <li>
                Suggestion automatique d&apos;une action de suivi
                post-appel (créer un follow-up, planifier RDV…).
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
        <div className="mt-8 rounded-2xl border border-teal-500/40 bg-teal-500/10 p-4 text-center">
          <CheckCircle2 className="mx-auto mb-1.5 h-5 w-5 text-teal-300" />
          <p className="text-sm font-semibold text-white">
            Phase 1 prête. Appelle le numéro pour tester.
          </p>
          <p className="mt-1 text-xs text-white/70">
            Le journal ci-dessus se met à jour à chaque appel. Quand tu seras
            prêt pour la secrétaire IA, dis-le et j&apos;enchaîne sur la
            Phase 2.
          </p>
        </div>
      </div>
    </div>
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
