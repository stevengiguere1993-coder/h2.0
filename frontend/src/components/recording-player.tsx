"use client";

import { useEffect, useRef, useState } from "react";
import { Loader2, Play } from "lucide-react";

import { authedFetch } from "@/lib/auth";

/**
 * Lecteur d'enregistrement intégré : récupère le média audio (voicemail /
 * appel) via le proxy backend `/api/v1/voice/calls/{id}/recording` — qui
 * streame depuis Twilio avec l'auth du compte — puis le joue DANS Kratos.
 *
 * On passe par un blob authentifié (et non un <audio src> direct) parce que
 * l'endpoint exige le JWT, qu'une balise <audio> ne peut pas envoyer en
 * en-tête.
 */
export function RecordingPlayer({
  callId,
  label = "Écouter",
  className
}: {
  callId: number;
  label?: string;
  className?: string;
}) {
  const [src, setSrc] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const urlRef = useRef<string | null>(null);

  // Libère l'object URL quand le composant disparaît.
  useEffect(() => {
    return () => {
      if (urlRef.current) URL.revokeObjectURL(urlRef.current);
    };
  }, []);

  async function load() {
    if (src || loading) return;
    setLoading(true);
    setError(null);
    try {
      const r = await authedFetch(`/api/v1/voice/calls/${callId}/recording`);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const blob = await r.blob();
      const objectUrl = URL.createObjectURL(blob);
      urlRef.current = objectUrl;
      setSrc(objectUrl);
    } catch {
      setError("Lecture impossible pour le moment.");
    } finally {
      setLoading(false);
    }
  }

  if (src) {
    return (
      <audio
        controls
        autoPlay
        src={src}
        className="mt-2 h-9 w-full max-w-xs"
      />
    );
  }

  return (
    <span className="inline-flex flex-col gap-1">
      <button
        type="button"
        onClick={load}
        disabled={loading}
        className={
          className ??
          "inline-flex items-center gap-1.5 rounded-md border border-amber-500/40 px-2 py-1 text-[11px] text-amber-200 hover:bg-amber-500/10 disabled:opacity-60"
        }
      >
        {loading ? (
          <Loader2 className="h-3.5 w-3.5 animate-spin" />
        ) : (
          <Play className="h-3.5 w-3.5" />
        )}
        {label}
      </button>
      {error ? (
        <span className="text-[10px] text-rose-300">{error}</span>
      ) : null}
    </span>
  );
}
