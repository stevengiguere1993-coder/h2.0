"use client";

// VoiceConsole — Twilio Voice SDK hybride.
//
// Quand un user du portail h2.0 a son navigateur ouvert, ce composant
// s'enregistre comme Twilio Client via `@twilio/voice-sdk`. Quand Léa
// (secrétaire IA) décide de transférer, Twilio ring tous les Clients
// online en parallèle (`<Dial><Client>user_5</Client>...</Dial>`).
// Premier qui clique « Répondre » prend l'appel ; les autres voient la
// popup disparaître. Si personne ne répond en 15 sec, Twilio bascule
// automatiquement sur le mobile (fallback côté backend).
//
// Le composant gère :
//   - le fetch initial du token + register
//   - le ping de présence toutes les 30 sec
//   - le popup d'appel entrant (caller_kind, nom, intent si dispo)
//   - les boutons Répondre / Refuser / Mute / Raccrocher

import { useCallback, useEffect, useRef, useState } from "react";
import { Phone, PhoneOff, Mic, MicOff } from "lucide-react";

import { authedFetch } from "@/lib/auth";

type DeviceAny = {
  register(): Promise<void>;
  unregister(): Promise<void>;
  on(event: string, handler: (...args: unknown[]) => void): void;
  updateToken(token: string): void;
  destroy(): void;
};

type CallAny = {
  accept(): void;
  reject(): void;
  disconnect(): void;
  mute(shouldMute: boolean): void;
  parameters: Record<string, string>;
  on(event: string, handler: (...args: unknown[]) => void): void;
};

type IncomingMeta = {
  from: string;
  callerKindHint?: string;
};

// Seul cet utilisateur voit la bannière d'erreur Voice en bas de
// page. Pour les autres on échoue silencieusement — un token Twilio
// invalide n'a aucune action utile pour eux, le bruit visuel n'aide
// personne.
const OWNER_EMAIL = "sgiguere@immohorizon.com";

export function VoiceConsole() {
  const deviceRef = useRef<DeviceAny | null>(null);
  const [status, setStatus] = useState<"idle" | "ready" | "error">("idle");
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [incoming, setIncoming] = useState<{ call: CallAny; meta: IncomingMeta } | null>(null);
  const [active, setActive] = useState<CallAny | null>(null);
  const [muted, setMuted] = useState(false);
  const [userEmail, setUserEmail] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const res = await authedFetch("/api/v1/auth/me");
        if (!res.ok) return;
        const me = (await res.json()) as { email?: string };
        if (!cancelled) setUserEmail(me.email ?? null);
      } catch {
        /* silencieux */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  // Verbatim de l'appel — Web Speech API du navigateur (ne capte
  // QUE le micro local, pas la voix du distant via WebRTC). Le buffer
  // accumule les résultats finaux pendant l'appel, et on le POSTe à
  // la fin sur /sdk/transcript pour le lier à la Call correspondante.
  const recognitionRef = useRef<{ stop: () => void } | null>(null);
  const transcriptBufferRef = useRef<string>("");
  const lastCallSidsRef = useRef<{
    child: string | null;
    parent: string | null;
  }>({ child: null, parent: null });

  // 1) Boot : fetch token + register Device
  useEffect(() => {
    let mounted = true;
    let pingTimer: ReturnType<typeof setInterval> | null = null;

    async function boot() {
      try {
        const res = await authedFetch("/api/v1/voice/sdk/token");
        if (res.status === 503) {
          // SDK pas configuré côté backend — on disable silencieusement.
          setStatus("idle");
          return;
        }
        if (!res.ok) throw new Error(`token http_${res.status}`);
        const { token } = (await res.json()) as { token: string };

        // Charge le SDK dynamiquement (évite SSR + ne charge qu'au login).
        const { Device } = (await import("@twilio/voice-sdk")) as unknown as {
          Device: new (token: string, opts?: Record<string, unknown>) => DeviceAny;
        };
        const device = new Device(token, {
          codecPreferences: ["opus", "pcmu"],
          // Déclenche `tokenWillExpire` 30 s avant l'expiration du
          // token (au lieu des 10 s par défaut) pour avoir le temps
          // de re-fetch sans coupure.
          tokenRefreshMs: 30_000,
          // logLevel: "warn",
        });

        // Renouvellement du token. Le token Twilio expire (1h côté
        // backend), et Twilio peut aussi le rejeter plus tôt (ex.
        // horloge serveur décalée → 20101 « AccessTokenInvalid »
        // au bout de quelques minutes). Dans les deux cas on va
        // chercher un token frais et on le pousse au Device — le
        // softphone se répare tout seul, sans recharger la page.
        const refreshToken = async (): Promise<boolean> => {
          try {
            const r = await authedFetch("/api/v1/voice/sdk/token");
            if (!r.ok) return false;
            const { token: fresh } = (await r.json()) as { token: string };
            device.updateToken(fresh);
            return true;
          } catch {
            return false;
          }
        };

        // Garde-fou anti-boucle : si le token reste rejeté malgré le
        // refresh (vrai mauvais secret), on s'arrête après quelques
        // tentatives et on affiche la bannière. Le compteur est remis
        // à zéro dès qu'un enregistrement réussit.
        let tokenRetries = 0;
        const MAX_TOKEN_RETRIES = 3;

        device.on("registered", () => {
          tokenRetries = 0;
          if (mounted) setStatus("ready");
        });
        device.on("tokenWillExpire", () => {
          void refreshToken();
        });
        device.on("error", (err: unknown) => {
          const msg = err instanceof Error ? err.message : String(err);
          const code = (err as { code?: number } | null)?.code;
          const tokenInvalid =
            code === 20101 || /20101|AccessToken/i.test(msg);
          if (tokenInvalid && tokenRetries < MAX_TOKEN_RETRIES) {
            tokenRetries += 1;
            console.warn(
              `[Voice] token rejeté (20101) — refresh ${tokenRetries}/${MAX_TOKEN_RETRIES}`
            );
            void (async () => {
              if (await refreshToken()) {
                try {
                  await device.register();
                } catch {
                  /* l'event error suivant relancera la récup */
                }
              }
            })();
            return; // pas de bannière pendant la récupération
          }
          console.warn("[Voice] device error", err);
          if (mounted) {
            setStatus("error");
            setErrorMsg(msg || "device error");
          }
        });
        device.on("incoming", (call: CallAny) => {
          if (!mounted) {
            call.reject();
            return;
          }
          const from = call.parameters?.From || "Inconnu";
          setIncoming({ call, meta: { from } });
          call.on("disconnect", () => {
            if (!mounted) return;
            setIncoming((cur) => (cur?.call === call ? null : cur));
            setActive((cur) => (cur === call ? null : cur));
            setMuted(false);
          });
          call.on("cancel", () => {
            if (!mounted) return;
            setIncoming((cur) => (cur?.call === call ? null : cur));
          });
        });

        await device.register();
        deviceRef.current = device;

        // 2) Heartbeat de présence — backend invalide après 60s.
        const ping = async () => {
          try {
            await authedFetch("/api/v1/voice/sdk/presence/ping?accepting=true", {
              method: "POST"
            });
          } catch {
            // network blip : on réessaye au prochain tick.
          }
        };
        void ping();
        pingTimer = setInterval(() => void ping(), 30_000);
      } catch (err) {
        if (mounted) {
          setStatus("error");
          setErrorMsg(err instanceof Error ? err.message : String(err));
        }
      }
    }

    void boot();
    return () => {
      mounted = false;
      if (pingTimer) clearInterval(pingTimer);
      try {
        deviceRef.current?.unregister();
        deviceRef.current?.destroy();
      } catch {
        /* ignore */
      }
    };
  }, []);

  // Annonce départ : signale "not accepting" pour pas que d'autres
  // appels soient routés ici pendant le close de la page.
  useEffect(() => {
    function bye() {
      navigator.sendBeacon?.(
        "/api/v1/voice/sdk/presence/ping?accepting=false",
        new Blob([""], { type: "text/plain" })
      );
    }
    window.addEventListener("beforeunload", bye);
    return () => window.removeEventListener("beforeunload", bye);
  }, []);

  // Pendant un appel actif : démarre Web Speech API sur le micro
  // local. À la fin de l'appel (active devient null), on stoppe et
  // on POST le verbatim accumulé. Best-effort — si le navigateur
  // ne supporte pas SpeechRecognition (Firefox, vieux Safari), on
  // n'enregistre rien et on log juste un avertissement.
  useEffect(() => {
    if (!active) return;

    // Capture les CallSids du tour courant — utiles à la POST finale
    // car `active` sera null à ce moment-là.
    const params = (active.parameters || {}) as Record<string, string>;
    const customGet = (
      active as unknown as {
        customParameters?: { get: (k: string) => string | undefined };
      }
    ).customParameters?.get;
    lastCallSidsRef.current = {
      child: params.CallSid || null,
      parent:
        (customGet ? customGet("ParentCallSid") : undefined) ||
        params.ParentCallSid ||
        null,
    };
    transcriptBufferRef.current = "";

    const W = window as unknown as {
      SpeechRecognition?: new () => unknown;
      webkitSpeechRecognition?: new () => unknown;
    };
    const SR = W.SpeechRecognition || W.webkitSpeechRecognition;
    if (!SR) {
      console.warn(
        "[Voice] Web Speech API non supportée par ce navigateur — " +
          "le verbatim ne sera pas capturé pour cet appel."
      );
      return;
    }

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const rec: any = new SR();
    rec.lang = "fr-CA";
    rec.continuous = true;
    rec.interimResults = false; // seulement les résultats finaux

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    rec.onresult = (e: any) => {
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const r = e.results[i];
        if (r.isFinal) {
          transcriptBufferRef.current += r[0].transcript + " ";
        }
      }
    };
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    rec.onerror = (e: any) => {
      console.warn(
        "[Voice] SpeechRecognition error:",
        e?.error || e
      );
    };

    try {
      rec.start();
      recognitionRef.current = { stop: () => rec.stop() };
    } catch (err) {
      console.warn("[Voice] SR start failed:", err);
    }

    return () => {
      try {
        recognitionRef.current?.stop();
      } catch {
        /* ignore */
      }
      recognitionRef.current = null;
      const buf = transcriptBufferRef.current.trim();
      transcriptBufferRef.current = "";
      const sids = lastCallSidsRef.current;
      lastCallSidsRef.current = { child: null, parent: null };
      if (!buf) return;
      void authedFetch("/api/v1/voice/sdk/transcript", {
        method: "POST",
        body: JSON.stringify({
          call_sid: sids.child,
          parent_call_sid: sids.parent,
          transcript: buf
        })
      }).catch(() => {
        /* best-effort, on ne bloque pas l'utilisateur */
      });
    };
  }, [active]);

  const acceptCall = useCallback(() => {
    if (!incoming) return;
    incoming.call.accept();
    setActive(incoming.call);
    setIncoming(null);
  }, [incoming]);

  const rejectCall = useCallback(() => {
    if (!incoming) return;
    incoming.call.reject();
    setIncoming(null);
  }, [incoming]);

  const hangup = useCallback(() => {
    active?.disconnect();
    setActive(null);
    setMuted(false);
  }, [active]);

  const toggleMute = useCallback(() => {
    if (!active) return;
    const next = !muted;
    active.mute(next);
    setMuted(next);
  }, [active, muted]);

  // Rien à afficher si pas configuré ou en erreur silencieuse.
  if (status === "idle" || status === "error") {
    return null;
  }

  return (
    <>
      {/* Incoming popup */}
      {incoming ? (
        <div className="fixed inset-x-0 top-4 z-[100] flex justify-center px-4">
          <div className="w-full max-w-md rounded-xl border border-teal-500/50 bg-brand-900/95 p-4 shadow-2xl backdrop-blur">
            <div className="text-[10px] uppercase tracking-wider text-teal-300">
              Appel entrant — Léa transfère
            </div>
            <div className="mt-1 font-mono text-lg text-white">
              {incoming.meta.from}
            </div>
            <div className="mt-3 flex items-center justify-end gap-2">
              <button
                type="button"
                onClick={rejectCall}
                className="inline-flex items-center gap-1.5 rounded-md border border-rose-500/40 bg-rose-500/10 px-3 py-1.5 text-xs font-semibold text-rose-200 hover:bg-rose-500/20"
              >
                <PhoneOff className="h-3.5 w-3.5" />
                Refuser
              </button>
              <button
                type="button"
                onClick={acceptCall}
                className="inline-flex items-center gap-1.5 rounded-md border border-emerald-500/40 bg-emerald-500/15 px-3 py-1.5 text-xs font-semibold text-emerald-200 hover:bg-emerald-500/25"
              >
                <Phone className="h-3.5 w-3.5" />
                Répondre
              </button>
            </div>
          </div>
        </div>
      ) : null}

      {/* Active call dock */}
      {active ? (
        <div className="fixed bottom-4 right-4 z-[100] flex items-center gap-2 rounded-full border border-emerald-500/40 bg-brand-900/95 px-3 py-2 shadow-2xl backdrop-blur">
          <span className="flex h-2 w-2 animate-pulse rounded-full bg-emerald-400" />
          <span className="text-[11px] font-semibold text-white">
            En appel — {active.parameters?.From || "—"}
          </span>
          <button
            type="button"
            onClick={toggleMute}
            className={`ml-2 rounded-full border p-1.5 ${
              muted
                ? "border-amber-500/40 bg-amber-500/20 text-amber-200"
                : "border-white/10 bg-white/5 text-white/70 hover:bg-white/10"
            }`}
            title={muted ? "Démuter" : "Muter"}
          >
            {muted ? <MicOff className="h-3 w-3" /> : <Mic className="h-3 w-3" />}
          </button>
          <button
            type="button"
            onClick={hangup}
            className="rounded-full border border-rose-500/40 bg-rose-500/20 p-1.5 text-rose-200 hover:bg-rose-500/30"
            title="Raccrocher"
          >
            <PhoneOff className="h-3 w-3" />
          </button>
        </div>
      ) : null}

      {errorMsg && userEmail === OWNER_EMAIL ? (
        <div className="fixed bottom-4 left-4 z-[100] max-w-xs rounded-md border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-[10px] text-rose-200">
          Voice : {errorMsg}
        </div>
      ) : null}
    </>
  );
}
