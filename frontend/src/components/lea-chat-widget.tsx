"use client";

// Léa-Web — widget de chat texte alimenté par la même IA Léa que le
// téléphone. Floating button bas-droite, ouvre un panneau de chat.
// Session persistée en localStorage pour survivre aux refresh et
// changements de page.
//
// Affiché uniquement sur les pages publiques (pas /app, /telephonie,
// etc.) — voir mount dans public-chrome.tsx.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Calendar,
  CheckCircle2,
  Loader2,
  MessageCircle,
  Send,
  Sparkles,
  X
} from "lucide-react";

const STORAGE_KEY = "lea_chat_token_v1";

type ChatMessage = {
  id: number;
  role: "user" | "assistant" | "system";
  text: string;
  created_at: string;
  meta_json: string | null;
};

type ChatSession = {
  token: string;
  lang: string;
  visitor_name: string | null;
  visitor_email: string | null;
  visitor_phone: string | null;
  contact_request_id: number | null;
  booked_event_id: number | null;
  messages: ChatMessage[];
};

type ProposedSlot = {
  user_id: number;
  user_display: string;
  start_at: string;
  end_at: string;
  appointment_type_id: number;
};

function parseMeta(meta_json: string | null): {
  proposed_slots?: ProposedSlot[];
  booked_event_id?: number;
  intent?: string;
} {
  if (!meta_json) return {};
  try {
    return JSON.parse(meta_json);
  } catch {
    return {};
  }
}

function formatSlot(startAt: string): string {
  try {
    return new Date(startAt).toLocaleString("fr-CA", {
      weekday: "long",
      day: "numeric",
      month: "long",
      hour: "2-digit",
      minute: "2-digit"
    });
  } catch {
    return startAt;
  }
}

export function LeaChatWidget() {
  const [open, setOpen] = useState(false);
  const [session, setSession] = useState<ChatSession | null>(null);
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [booking, setBooking] = useState(false);
  const [unread, setUnread] = useState(0);
  const scrollRef = useRef<HTMLDivElement>(null);

  // Initialisation : récupère ou crée une session
  useEffect(() => {
    if (!open) return;
    if (session) return;
    let cancelled = false;

    async function load() {
      const stored =
        typeof window !== "undefined"
          ? window.localStorage.getItem(STORAGE_KEY)
          : null;
      if (stored) {
        try {
          const r = await fetch(`/api/v1/lea-web/${stored}`, {
            cache: "no-store"
          });
          if (r.ok) {
            const data = (await r.json()) as ChatSession;
            if (!cancelled) setSession(data);
            return;
          }
        } catch {
          /* fall through to new session */
        }
      }
      // Nouvelle session
      try {
        const r = await fetch("/api/v1/lea-web/start", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            lang: "fr-CA",
            landing_page:
              typeof window !== "undefined" ? window.location.pathname : null
          })
        });
        if (!r.ok) throw new Error(`http_${r.status}`);
        const data = (await r.json()) as ChatSession;
        if (!cancelled) {
          window.localStorage.setItem(STORAGE_KEY, data.token);
          setSession(data);
        }
      } catch (e) {
        console.warn("Léa chat init failed", e);
      }
    }

    void load();
    return () => {
      cancelled = true;
    };
  }, [open, session]);

  // Auto-scroll au bas quand nouveaux messages
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [session?.messages?.length]);

  // Compteur unread quand widget fermé
  useEffect(() => {
    if (open) setUnread(0);
  }, [open]);

  const send = useCallback(async () => {
    if (!session || !draft.trim() || sending) return;
    const text = draft.trim();
    setDraft("");
    setSending(true);
    // Affichage optimiste
    const optimistic: ChatMessage = {
      id: -Math.random(),
      role: "user",
      text,
      created_at: new Date().toISOString(),
      meta_json: null
    };
    setSession((prev) =>
      prev ? { ...prev, messages: [...prev.messages, optimistic] } : prev
    );
    try {
      const r = await fetch(`/api/v1/lea-web/${session.token}/say`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text })
      });
      if (!r.ok) throw new Error(`http_${r.status}`);
      const data = (await r.json()) as ChatSession;
      setSession(data);
    } catch (e) {
      console.warn("Léa send failed", e);
    } finally {
      setSending(false);
    }
  }, [draft, sending, session]);

  const book = useCallback(
    async (idx: number) => {
      if (!session || booking) return;
      setBooking(true);
      try {
        const r = await fetch(`/api/v1/lea-web/${session.token}/book`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ chosen_slot_index: idx })
        });
        if (!r.ok) {
          const t = await r.text().catch(() => "");
          throw new Error(t.slice(0, 200) || `http_${r.status}`);
        }
        const data = (await r.json()) as ChatSession;
        setSession(data);
      } catch (e) {
        console.warn("Booking failed", e);
      } finally {
        setBooking(false);
      }
    },
    [booking, session]
  );

  // Dernier message assistant avec proposed_slots (pour boutons)
  const latestSlots = useMemo<ProposedSlot[] | null>(() => {
    if (!session || session.booked_event_id) return null;
    for (let i = session.messages.length - 1; i >= 0; i--) {
      const m = session.messages[i];
      if (m.role !== "assistant") continue;
      const meta = parseMeta(m.meta_json);
      if (meta.proposed_slots && meta.proposed_slots.length > 0) {
        return meta.proposed_slots;
      }
    }
    return null;
  }, [session]);

  return (
    <>
      {/* Floating launcher */}
      {!open ? (
        <button
          type="button"
          onClick={() => setOpen(true)}
          aria-label="Parler avec Léa"
          className="fixed bottom-6 right-6 z-50 flex items-center gap-2 rounded-full bg-emerald-600 px-5 py-3 font-semibold text-white shadow-2xl ring-2 ring-emerald-400/30 transition hover:bg-emerald-500 hover:shadow-emerald-600/40 active:scale-95"
        >
          <MessageCircle className="h-5 w-5" />
          <span className="hidden sm:inline">Parler avec Léa</span>
          <span className="sm:hidden">Léa</span>
          {unread > 0 ? (
            <span className="rounded-full bg-rose-500 px-2 py-0.5 text-xs">
              {unread}
            </span>
          ) : null}
        </button>
      ) : null}

      {/* Chat panel */}
      {open ? (
        <div className="fixed inset-x-0 bottom-0 z-50 sm:inset-x-auto sm:bottom-6 sm:right-6 sm:w-[380px] sm:max-w-[calc(100vw-2rem)]">
          <div className="flex h-[80vh] flex-col overflow-hidden rounded-t-2xl border border-emerald-500/30 bg-white shadow-2xl sm:h-[600px] sm:rounded-2xl dark:bg-slate-900">
            {/* Header */}
            <header className="flex items-center justify-between gap-2 border-b border-slate-200 bg-gradient-to-r from-emerald-600 to-teal-600 px-4 py-3 text-white">
              <div className="flex items-center gap-2 min-w-0">
                <div className="flex h-9 w-9 items-center justify-center rounded-full bg-white/20">
                  <Sparkles className="h-5 w-5" />
                </div>
                <div className="min-w-0">
                  <div className="text-sm font-bold">Léa</div>
                  <div className="text-[11px] opacity-90">
                    Horizon Services Immobiliers
                  </div>
                </div>
              </div>
              <button
                type="button"
                onClick={() => setOpen(false)}
                aria-label="Fermer"
                className="rounded-full p-1.5 transition hover:bg-white/20"
              >
                <X className="h-4 w-4" />
              </button>
            </header>

            {/* Messages */}
            <div
              ref={scrollRef}
              className="flex-1 space-y-3 overflow-y-auto bg-slate-50 px-4 py-4 dark:bg-slate-950"
            >
              {!session ? (
                <div className="flex items-center justify-center py-8">
                  <Loader2 className="h-5 w-5 animate-spin text-emerald-600" />
                </div>
              ) : (
                <>
                  {session.messages.map((m) => (
                    <MessageBubble key={m.id} m={m} />
                  ))}
                  {latestSlots ? (
                    <div className="space-y-2 pl-2">
                      <p className="text-[11px] uppercase tracking-wider text-slate-500">
                        Choisissez un créneau :
                      </p>
                      {latestSlots.map((s, i) => (
                        <button
                          key={i}
                          type="button"
                          onClick={() => book(i)}
                          disabled={booking}
                          className="flex w-full items-center justify-between gap-2 rounded-lg border border-emerald-500/40 bg-white px-3 py-2.5 text-left text-sm font-medium text-slate-800 shadow-sm transition hover:border-emerald-500 hover:bg-emerald-50 disabled:opacity-50 dark:bg-slate-900 dark:text-slate-100"
                        >
                          <div className="flex items-center gap-2 min-w-0">
                            <Calendar className="h-4 w-4 flex-shrink-0 text-emerald-600" />
                            <span className="truncate">
                              {formatSlot(s.start_at)}
                            </span>
                          </div>
                          <span className="rounded-md bg-emerald-600 px-2 py-0.5 text-[11px] font-semibold text-white">
                            Choisir
                          </span>
                        </button>
                      ))}
                    </div>
                  ) : null}
                  {session.booked_event_id ? (
                    <div className="rounded-lg border border-emerald-500/40 bg-emerald-50 p-3 text-sm text-emerald-900">
                      <div className="flex items-center gap-2 font-semibold">
                        <CheckCircle2 className="h-4 w-4" />
                        Rendez-vous confirmé
                      </div>
                      <p className="mt-1 text-xs">
                        Un courriel de confirmation vous sera envoyé. À bientôt !
                      </p>
                    </div>
                  ) : null}
                  {sending ? (
                    <div className="flex items-center gap-2 px-2 text-xs text-slate-500">
                      <Loader2 className="h-3 w-3 animate-spin" />
                      Léa écrit…
                    </div>
                  ) : null}
                </>
              )}
            </div>

            {/* Input */}
            <form
              onSubmit={(e) => {
                e.preventDefault();
                void send();
              }}
              className="flex items-center gap-2 border-t border-slate-200 bg-white px-3 py-3 dark:bg-slate-900"
            >
              <input
                type="text"
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                placeholder={
                  session?.booked_event_id
                    ? "Votre RV est confirmé 🎉"
                    : "Écrivez votre message…"
                }
                disabled={sending || !session}
                className="flex-1 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 placeholder:text-slate-400 focus:border-emerald-500 focus:outline-none focus:ring-2 focus:ring-emerald-500/20 disabled:opacity-60 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
                maxLength={2000}
                autoComplete="off"
              />
              <button
                type="submit"
                disabled={sending || !draft.trim() || !session}
                className="flex h-10 w-10 items-center justify-center rounded-lg bg-emerald-600 text-white transition hover:bg-emerald-500 disabled:opacity-40"
                aria-label="Envoyer"
              >
                {sending ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Send className="h-4 w-4" />
                )}
              </button>
            </form>
          </div>
        </div>
      ) : null}
    </>
  );
}

function MessageBubble({ m }: { m: ChatMessage }) {
  const isUser = m.role === "user";
  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
      <div
        className={`max-w-[85%] whitespace-pre-line rounded-2xl px-3 py-2 text-sm shadow-sm ${
          isUser
            ? "bg-emerald-600 text-white"
            : "bg-white text-slate-800 dark:bg-slate-800 dark:text-slate-100"
        }`}
      >
        {m.text}
      </div>
    </div>
  );
}
