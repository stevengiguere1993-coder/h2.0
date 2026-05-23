"use client";

// Modal de détail d'un appel — affiché en surimpression au-dessus
// de la page courante quand on clique un appel dans le dropdown
// d'historique. Évite de quitter la fiche client/prospect/etc. pour
// aller dans /telephonie juste pour voir un transcript.

import { useEffect, useState } from "react";
import {
  Loader2,
  Mic,
  Phone,
  PhoneIncoming,
  PhoneOutgoing,
  X
} from "lucide-react";

import { authedFetch } from "@/lib/auth";

type Call = {
  id: number;
  direction: string;
  status: string;
  from_e164: string;
  to_e164: string;
  forwarded_to_e164: string | null;
  lead_name: string | null;
  intent: string | null;
  started_at: string;
  ended_at: string | null;
  duration_sec: number | null;
  recording_url: string | null;
  verbatim_transcript: string | null;
  voicemail_transcription: string | null;
  voicemail_summary: string | null;
};

type Turn = {
  id: number;
  turn_index: number;
  role: string;
  text: string;
};

type Detail = {
  call: Call;
  turns: Turn[];
};

type Props = {
  callId: number | null;
  onClose: () => void;
};

export function CallDetailModal({ callId, onClose }: Props) {
  const [detail, setDetail] = useState<Detail | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Fermer au clavier Escape — confort.
  useEffect(() => {
    if (callId === null) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [callId, onClose]);

  useEffect(() => {
    if (callId === null) {
      setDetail(null);
      setError(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    setDetail(null);
    void authedFetch(`/api/v1/voice/calls/${callId}/detail`)
      .then(async (r) => {
        if (cancelled) return;
        if (r.ok) {
          setDetail((await r.json()) as Detail);
        } else {
          setError(`HTTP ${r.status}`);
        }
      })
      .catch((e: unknown) => {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : String(e));
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [callId]);

  if (callId === null) return null;

  return (
    <div className="fixed inset-0 z-[200] flex items-start justify-center bg-black/60 p-4 pt-16">
      <div
        className="w-full max-w-2xl overflow-hidden rounded-2xl border border-brand-800 bg-brand-950 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-brand-800 px-5 py-3">
          <div className="flex items-center gap-2 text-sm font-semibold text-white">
            <Phone className="h-4 w-4 text-accent-500" />
            Détail de l&apos;appel
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md p-1 text-white/40 hover:bg-brand-900 hover:text-white"
            aria-label="Fermer"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="max-h-[70vh] overflow-y-auto p-5">
          {loading ? (
            <div className="flex items-center justify-center py-10">
              <Loader2 className="h-6 w-6 animate-spin text-accent-500" />
            </div>
          ) : error ? (
            <p className="rounded-md border border-rose-500/40 bg-rose-500/10 px-4 py-3 text-sm text-rose-300">
              Impossible de charger l&apos;appel : {error}
            </p>
          ) : detail ? (
            <div className="space-y-5">
              <header>
                <div className="flex items-center gap-2 text-xs uppercase tracking-wider text-white/40">
                  {detail.call.direction === "inbound" ? (
                    <>
                      <PhoneIncoming className="h-3 w-3" /> Entrant
                    </>
                  ) : (
                    <>
                      <PhoneOutgoing className="h-3 w-3" /> Sortant
                    </>
                  )}
                  <span>·</span>
                  <span>
                    {new Date(detail.call.started_at).toLocaleString(
                      "fr-CA",
                      {
                        day: "numeric",
                        month: "long",
                        year: "numeric",
                        hour: "2-digit",
                        minute: "2-digit"
                      }
                    )}
                  </span>
                  {detail.call.duration_sec != null ? (
                    <>
                      <span>·</span>
                      <span>
                        {Math.round(detail.call.duration_sec / 60)} min
                      </span>
                    </>
                  ) : null}
                </div>
                <h2 className="mt-1 text-lg font-semibold text-white">
                  {detail.call.lead_name || detail.call.from_e164}
                </h2>
                <p className="mt-0.5 font-mono text-xs text-white/60">
                  {detail.call.from_e164} → {detail.call.to_e164}
                  {detail.call.forwarded_to_e164
                    ? ` → ${detail.call.forwarded_to_e164}`
                    : ""}
                </p>
                {detail.call.intent ? (
                  <p className="mt-1 inline-block rounded-md bg-accent-500/15 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-accent-300">
                    {detail.call.intent}
                  </p>
                ) : null}
              </header>

              {detail.call.recording_url ? (
                <section>
                  <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-white/50">
                    Enregistrement
                  </h3>
                  <a
                    href={detail.call.recording_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex items-center gap-2 rounded-md border border-brand-800 bg-brand-900 px-3 py-1.5 text-xs text-white hover:border-accent-500"
                  >
                    <Mic className="h-3 w-3" />
                    Ouvrir l&apos;enregistrement Twilio
                  </a>
                </section>
              ) : null}

              {detail.call.verbatim_transcript ? (
                <section>
                  <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-white/50">
                    Verbatim (côté navigateur)
                  </h3>
                  <pre className="whitespace-pre-wrap rounded-md border border-brand-800 bg-brand-900 p-3 text-xs leading-relaxed text-white/90">
                    {detail.call.verbatim_transcript}
                  </pre>
                </section>
              ) : null}

              {detail.call.voicemail_transcription ? (
                <section>
                  <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-white/50">
                    Boîte vocale
                  </h3>
                  <pre className="whitespace-pre-wrap rounded-md border border-brand-800 bg-brand-900 p-3 text-xs leading-relaxed text-white/90">
                    {detail.call.voicemail_transcription}
                  </pre>
                </section>
              ) : null}

              {detail.turns.length > 0 ? (
                <section>
                  <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-white/50">
                    Conversation avec Léa
                  </h3>
                  <ul className="space-y-2">
                    {detail.turns.map((t) => (
                      <li
                        key={t.id}
                        className={`rounded-md border p-2 text-xs ${
                          t.role === "assistant"
                            ? "border-accent-500/30 bg-accent-500/5 text-white"
                            : "border-brand-800 bg-brand-900 text-white/85"
                        }`}
                      >
                        <span className="mr-2 text-[10px] font-semibold uppercase tracking-wider text-white/40">
                          {t.role === "assistant" ? "Léa" : "Appelant"}
                        </span>
                        {t.text}
                      </li>
                    ))}
                  </ul>
                </section>
              ) : null}

              {!detail.call.verbatim_transcript &&
              !detail.call.voicemail_transcription &&
              detail.turns.length === 0 ? (
                <p className="rounded-md border border-amber-500/30 bg-amber-500/5 px-3 py-3 text-xs text-amber-200">
                  Aucun verbatim, boîte vocale ou transcription IA pour
                  cet appel.
                </p>
              ) : null}
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}
