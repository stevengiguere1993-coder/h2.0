"use client";

import { useEffect, useState } from "react";
import {
  AlertTriangle,
  ArrowLeft,
  CheckCircle2,
  Filter,
  PhoneCall,
  PhoneForwarded,
  PhoneIncoming,
  Sparkles,
  Workflow
} from "lucide-react";

import { getMe, getToken } from "@/lib/auth";
import { Link, useRouter } from "@/i18n/navigation";

// Volet « Téléphonie / Secrétaire d'appels ».
//
// Page d'accueil — état des lieux + plan que nous avons défini avec
// l'utilisateur, en attendant le démarrage de la Phase 1 (intégration
// Twilio). L'accès est gated par email côté front (login-form) et
// peut être étendu côté back quand on commencera à exposer des
// endpoints réels.

const TELEPHONIE_ALLOWED_EMAILS = ["sgiguere@immohorizon.com"];

type Me = {
  email?: string | null;
};

export default function TelephonieHome() {
  const router = useRouter();
  const [checking, setChecking] = useState(true);
  const [allowed, setAllowed] = useState(false);

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
  }, [router]);

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
              Numéro 514 unique, IA qui décroche en français, qualifie le
              lead, filtre les indésirables et transfère au bon user.
            </p>
          </div>
          <span className="shrink-0 rounded-full border border-amber-500/40 bg-amber-500/10 px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wider text-amber-300">
            En développement
          </span>
        </header>

        {/* Bannière setup */}
        <section className="mt-6 rounded-2xl border border-teal-500/40 bg-teal-500/5 p-5">
          <h2 className="flex items-center gap-2 text-sm font-bold text-teal-200">
            <Sparkles className="h-4 w-4" />
            Prochaine étape
          </h2>
          <p className="mt-2 text-xs text-white/70">
            Avant qu&apos;on puisse écrire la première ligne de code
            d&apos;intégration, j&apos;ai besoin de ton compte Twilio.
          </p>
          <ol className="mt-3 list-decimal space-y-1.5 pl-5 text-xs text-white/80">
            <li>
              Créer un compte sur{" "}
              <a
                href="https://www.twilio.com/try-twilio"
                target="_blank"
                rel="noreferrer"
                className="text-teal-300 underline hover:text-teal-200"
              >
                twilio.com/try-twilio
              </a>{" "}
              (~5 min, juste courriel + carte non-débitée pour
              anti-fraude).
            </li>
            <li>
              Console → Account → Récupérer{" "}
              <code className="rounded bg-white/10 px-1 text-[11px]">
                Account SID
              </code>{" "}
              +{" "}
              <code className="rounded bg-white/10 px-1 text-[11px]">
                Auth Token
              </code>
              .
            </li>
            <li>
              Me les donner pour qu&apos;on les mette dans les variables
              d&apos;env Render : <code>TWILIO_ACCOUNT_SID</code> +{" "}
              <code>TWILIO_AUTH_TOKEN</code>.
            </li>
            <li>
              Acheter 1 numéro 514 dans la console Twilio (~1 $ via le
              crédit trial gratuit) ou laisser le système le faire via
              l&apos;API en Phase 1.
            </li>
          </ol>
          <p className="mt-3 rounded-md border border-white/10 bg-white/5 px-3 py-2 text-[11px] text-white/60">
            💡 <strong>Pas de carte débitée tant qu&apos;on reste sur le
            crédit trial</strong> (~15 USD offerts). Le numéro coûte
            ~1,15 $/mois et les appels entrants ~0,01 $/min — on a des
            mois d&apos;usage en bas volume avant de dépasser le trial.
          </p>
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
            status="todo"
          >
            <ul className="space-y-1">
              <li>
                Module backend <code>app/integrations/voice/</code>, abstraction
                provider (Twilio par défaut, swap futur possible).
              </li>
              <li>
                Modèles SQL : <code>PhoneNumber</code>, <code>Call</code>,{" "}
                <code>CallRoute</code>, <code>CallTranscript</code>.
              </li>
              <li>
                Endpoint webhook Twilio (signature HMAC vérifiée).
              </li>
              <li>
                Achat / import des numéros 514 via l&apos;API Twilio +
                attribution à un user.
              </li>
              <li>
                Dispatch simple : appel entrant →{" "}
                <code>&lt;Dial&gt;</code> vers le mobile du user assigné.
              </li>
              <li>
                Page <code>/telephonie</code> : liste des numéros, qui
                répond à quoi, journal d&apos;appels minimal.
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
              <li>
                File d&apos;attente si tous les users sont occupés.
              </li>
              <li>
                Voicemail IA qui transcrit + résume + notifie.
              </li>
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
                <td className="py-2 text-white/70">Numéro 514 (prod)</td>
                <td className="py-2 text-right text-white/90">
                  ~1,15 $/mois
                </td>
              </tr>
              <tr>
                <td className="py-2 text-white/70">Appels entrants</td>
                <td className="py-2 text-right text-white/90">
                  ~0,01 $/min
                </td>
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
            module sera codé avec une abstraction provider pour qu&apos;on
            puisse swap sans réécrire le frontend.
          </p>
        </section>

        {/* CTA */}
        <div className="mt-8 rounded-2xl border border-teal-500/40 bg-teal-500/10 p-4 text-center">
          <CheckCircle2 className="mx-auto mb-1.5 h-5 w-5 text-teal-300" />
          <p className="text-sm font-semibold text-white">
            Prêt à démarrer la Phase 1
          </p>
          <p className="mt-1 text-xs text-white/70">
            Quand tu m&apos;auras donné tes credentials Twilio, je
            commence l&apos;intégration backend + un premier numéro 514
            qui sonne sur ton mobile.
          </p>
        </div>
      </div>
    </div>
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
