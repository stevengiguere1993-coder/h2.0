"use client";

// Onglet « Communications » réutilisable pour les fiches CRM.
// Affiche en lecture seule la chronologie fusionnée des appels +
// SMS pour une entité (lead, client, locataire, contact request).
// Tous les détails techniques (transcription tour-par-tour, lecture
// du voicemail, etc.) restent dans /telephonie : on offre seulement
// un lien rapide vers le drawer correspondant.

import { useEffect, useMemo, useState } from "react";
import {
  Bot,
  Loader2,
  MessageSquare,
  Mic,
  PhoneIncoming,
  PhoneOutgoing,
  Search,
  Send,
  Voicemail
} from "lucide-react";

import { authedFetch } from "@/lib/auth";
import { Link } from "@/i18n/navigation";

export type CommunicationsEntityType =
  | "client"
  | "locataire"
  | "prospection_lead"
  | "contact_request";

type Event = {
  kind: "call" | "sms";
  id: number;
  at: string;
  direction: "inbound" | "outbound" | string;
  status: string;
  from_e164: string;
  to_e164: string;
  duration_sec: number | null;
  intent: string | null;
  was_voicemail: boolean;
  voicemail_summary: string | null;
  followup_suggestion: string | null;
  body: string | null;
  num_media: number;
};

type Filter = "all" | "call" | "sms" | "voicemail";

function fmtDuration(sec: number | null | undefined): string {
  if (!sec || sec <= 0) return "—";
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  if (m === 0) return `${s}s`;
  return `${m}m ${s.toString().padStart(2, "0")}s`;
}

function fmtDateTime(iso: string): string {
  try {
    return new Date(iso).toLocaleString("fr-CA", {
      day: "numeric",
      month: "short",
      hour: "2-digit",
      minute: "2-digit"
    });
  } catch {
    return iso;
  }
}

export function CommunicationsTimeline({
  entityType,
  entityId,
  title = "Communications",
  emptyHint,
  replyToE164
}: {
  entityType: CommunicationsEntityType;
  entityId: number;
  title?: string;
  emptyHint?: string;
  // Si fourni, affiche un quick-reply SMS sous le timeline qui
  // envoie au numéro indiqué (généralement le téléphone CRM du
  // contact en cours).
  replyToE164?: string | null;
}) {
  const [events, setEvents] = useState<Event[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<Filter>("all");
  const [search, setSearch] = useState("");
  const [replyBody, setReplyBody] = useState("");
  const [replyBusy, setReplyBusy] = useState(false);
  const [replyNotice, setReplyNotice] = useState<string | null>(null);

  async function sendQuickReply() {
    if (!replyToE164 || !replyBody.trim()) return;
    setReplyBusy(true);
    setReplyNotice(null);
    try {
      const r = await authedFetch("/api/v1/voice/sms", {
        method: "POST",
        body: JSON.stringify({
          to_e164: replyToE164,
          body: replyBody.trim()
        })
      });
      if (!r.ok) {
        const t = await r.text().catch(() => "");
        throw new Error(t.slice(0, 200));
      }
      setReplyBody("");
      setReplyNotice("SMS envoyé.");
      // Reload timeline to show the sent SMS
      const lr = await authedFetch(
        `/api/v1/voice/communications/${entityType}/${entityId}?limit=200`
      );
      if (lr.ok) setEvents((await lr.json()) as Event[]);
    } catch (e) {
      setReplyNotice(`Échec d'envoi : ${(e as Error).message}`);
    } finally {
      setReplyBusy(false);
    }
  }

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    (async () => {
      try {
        const r = await authedFetch(
          `/api/v1/voice/communications/${entityType}/${entityId}?limit=200`
        );
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const data = (await r.json()) as Event[];
        if (!cancelled) setEvents(Array.isArray(data) ? data : []);
      } catch (e) {
        if (!cancelled) setError((e as Error).message);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [entityType, entityId]);

  const filtered = useMemo(() => {
    let xs = events;
    if (filter === "call") xs = xs.filter((e) => e.kind === "call" && !e.was_voicemail);
    else if (filter === "sms") xs = xs.filter((e) => e.kind === "sms");
    else if (filter === "voicemail")
      xs = xs.filter((e) => e.kind === "call" && e.was_voicemail);

    const q = search.trim().toLowerCase();
    if (q) {
      xs = xs.filter((e) => {
        const hay = [
          e.body || "",
          e.voicemail_summary || "",
          e.intent || "",
          e.from_e164,
          e.to_e164
        ]
          .join(" ")
          .toLowerCase();
        return hay.includes(q);
      });
    }
    return xs;
  }, [events, filter, search]);

  const counts = useMemo(() => {
    const c = { all: events.length, call: 0, sms: 0, voicemail: 0 };
    for (const e of events) {
      if (e.kind === "sms") c.sms += 1;
      else if (e.was_voicemail) c.voicemail += 1;
      else c.call += 1;
    }
    return c;
  }, [events]);

  return (
    <section className="rounded-xl border border-brand-800 bg-brand-900 p-4 sm:p-5">
      <header className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm font-semibold uppercase tracking-wider text-accent-500">
          {title}
        </h3>
        <Link
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          href={"/telephonie" as any}
          className="text-[11px] text-white/50 underline decoration-dotted hover:text-accent-500"
        >
          Ouvrir la téléphonie →
        </Link>
      </header>

      <div className="mt-3 flex flex-wrap items-center gap-2">
        {(
          [
            { key: "all", label: `Tout · ${counts.all}` },
            { key: "call", label: `Appels · ${counts.call}` },
            { key: "sms", label: `SMS · ${counts.sms}` },
            { key: "voicemail", label: `Voicemail · ${counts.voicemail}` }
          ] as { key: Filter; label: string }[]
        ).map((f) => (
          <button
            key={f.key}
            type="button"
            onClick={() => setFilter(f.key)}
            className={`rounded-full px-3 py-1 text-[11px] font-semibold ${
              filter === f.key
                ? "bg-accent-500 text-brand-950"
                : "bg-white/5 text-white/60 hover:bg-white/10"
            }`}
          >
            {f.label}
          </button>
        ))}
        <div className="ml-auto flex items-center gap-1.5 rounded-md border border-brand-800 bg-brand-950 px-2 py-1">
          <Search className="h-3.5 w-3.5 text-white/40" />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Chercher dans le contenu…"
            className="w-40 bg-transparent text-xs text-white placeholder:text-white/30 focus:outline-none"
          />
        </div>
      </div>

      <div className="mt-4">
        {loading ? (
          <div className="flex items-center justify-center py-8">
            <Loader2 className="h-5 w-5 animate-spin text-accent-500" />
          </div>
        ) : error ? (
          <p className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
            {error}
          </p>
        ) : filtered.length === 0 ? (
          <p className="rounded-lg border border-brand-800 bg-brand-950 px-3 py-6 text-center text-xs text-white/40">
            {emptyHint ||
              "Aucun appel ni SMS lié à cette fiche pour le moment."}
          </p>
        ) : (
          <ol className="space-y-2">
            {filtered.map((e) => (
              <EventRow key={`${e.kind}-${e.id}`} ev={e} />
            ))}
          </ol>
        )}
      </div>

      {replyToE164 ? (
        <div className="mt-4 border-t border-brand-800 pt-3">
          <label className="text-[11px] font-semibold uppercase tracking-wider text-white/50">
            Réponse rapide SMS
            <span className="ml-2 font-mono text-white/40">
              → {replyToE164}
            </span>
          </label>
          <div className="mt-2 flex flex-col gap-2 sm:flex-row">
            <textarea
              value={replyBody}
              onChange={(e) => setReplyBody(e.target.value)}
              rows={2}
              maxLength={1600}
              placeholder="Tapez votre message…"
              className="flex-1 rounded-md border border-brand-800 bg-brand-950 px-3 py-2 text-sm text-white placeholder:text-white/30 focus:border-accent-500 focus:outline-none"
              disabled={replyBusy}
            />
            <button
              type="button"
              onClick={sendQuickReply}
              disabled={replyBusy || !replyBody.trim()}
              className="inline-flex items-center justify-center gap-2 rounded-md bg-accent-500 px-4 py-2 text-sm font-semibold text-brand-950 transition hover:bg-accent-400 disabled:opacity-50 sm:self-start"
            >
              {replyBusy ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Send className="h-4 w-4" />
              )}
              Envoyer
            </button>
          </div>
          {replyNotice ? (
            <p
              className={`mt-2 text-[11px] ${
                replyNotice.startsWith("SMS envoyé")
                  ? "text-emerald-300"
                  : "text-rose-300"
              }`}
            >
              {replyNotice}
            </p>
          ) : null}
          <p className="mt-1 text-[10px] text-white/30">
            Le SMS sera envoyé depuis le numéro Horizon (438 800 2979)
            et apparaîtra dans la fiche.
          </p>
        </div>
      ) : null}
    </section>
  );
}

function EventRow({ ev }: { ev: Event }) {
  const isInbound = ev.direction === "inbound";
  const isSms = ev.kind === "sms";
  const isVoicemail = ev.kind === "call" && ev.was_voicemail;

  const Icon = isSms
    ? MessageSquare
    : isVoicemail
    ? Voicemail
    : isInbound
    ? PhoneIncoming
    : PhoneOutgoing;

  const toneClass = isVoicemail
    ? "text-violet-300 border-violet-500/30 bg-violet-500/5"
    : isSms
    ? "text-blue-300 border-blue-500/30 bg-blue-500/5"
    : isInbound
    ? "text-teal-300 border-teal-500/30 bg-teal-500/5"
    : "text-amber-300 border-amber-500/30 bg-amber-500/5";

  const drawerHref = isSms
    ? `/telephonie?sms=${ev.id}`
    : `/telephonie?call=${ev.id}`;

  return (
    <li className={`rounded-lg border px-3 py-2 ${toneClass}`}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="flex min-w-0 items-start gap-2">
          <Icon className="mt-0.5 h-4 w-4 flex-shrink-0" />
          <div className="min-w-0">
            <div className="text-xs font-semibold">
              {isVoicemail
                ? "Voicemail"
                : isSms
                ? isInbound
                  ? "SMS reçu"
                  : "SMS envoyé"
                : isInbound
                ? "Appel reçu"
                : "Appel sortant"}{" "}
              <span className="ml-1 font-normal text-white/40">
                · {fmtDateTime(ev.at)}
              </span>
            </div>
            <div className="mt-0.5 font-mono text-[11px] text-white/50">
              {isInbound ? ev.from_e164 : ev.to_e164}
              {!isSms && ev.duration_sec ? (
                <span className="ml-2">{fmtDuration(ev.duration_sec)}</span>
              ) : null}
              <span className="ml-2 text-white/30">· {ev.status}</span>
            </div>
            {isSms && ev.body ? (
              <p className="mt-1 line-clamp-3 text-xs text-white/80">
                {ev.body}
              </p>
            ) : null}
            {isVoicemail && ev.voicemail_summary ? (
              <p className="mt-1 line-clamp-3 text-xs text-white/80">
                <Mic className="mr-1 inline h-3 w-3" />
                {ev.voicemail_summary}
              </p>
            ) : null}
            {!isSms && !isVoicemail && ev.intent ? (
              <p className="mt-1 text-[11px] text-white/50">
                <Bot className="mr-1 inline h-3 w-3" />
                Intention détectée : <span className="text-white/80">{ev.intent}</span>
              </p>
            ) : null}
            {ev.followup_suggestion ? (
              <p className="mt-1 line-clamp-2 text-[11px] italic text-white/50">
                💡 {ev.followup_suggestion}
              </p>
            ) : null}
          </div>
        </div>
        <Link
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          href={drawerHref as any}
          className="text-[11px] text-white/50 underline decoration-dotted hover:text-white"
        >
          Détails →
        </Link>
      </div>
    </li>
  );
}
