"use client";

// Photos MMS d'un SMS — chargées via le proxy authentifié
// /voice/sms/{id}/media/{i} (les URLs Twilio exigent l'auth du compte,
// un <img> direct ne charge jamais). Fetch + blob comme l'avatar :
// l'endpoint exige le Bearer token.

import { useEffect, useState } from "react";
import { ImageOff, Loader2, X } from "lucide-react";

import { authedFetch } from "@/lib/auth";

export function MmsImages({
  smsId,
  count
}: {
  smsId: number;
  count: number;
}) {
  const [urls, setUrls] = useState<(string | null)[] | null>(null);
  const [zoom, setZoom] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const created: string[] = [];
    (async () => {
      const out: (string | null)[] = [];
      for (let i = 0; i < count; i++) {
        try {
          const r = await authedFetch(
            `/api/v1/voice/sms/${smsId}/media/${i}`
          );
          if (!r.ok) throw new Error(`HTTP ${r.status}`);
          const blob = await r.blob();
          const u = URL.createObjectURL(blob);
          created.push(u);
          out.push(u);
        } catch {
          out.push(null);
        }
      }
      if (!cancelled) setUrls(out);
    })();
    return () => {
      cancelled = true;
      created.forEach((u) => URL.revokeObjectURL(u));
    };
  }, [smsId, count]);

  if (count <= 0) return null;

  if (urls === null) {
    return (
      <div className="mt-1.5 inline-flex items-center gap-1.5 rounded-md bg-white/5 px-2 py-1 text-[10px] text-white/40">
        <Loader2 className="h-3 w-3 animate-spin" />
        Photo{count > 1 ? "s" : ""}…
      </div>
    );
  }

  return (
    <>
      <div className="mt-1.5 flex flex-wrap gap-1.5">
        {urls.map((u, i) =>
          u ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              key={i}
              src={u}
              alt={`Photo ${i + 1}`}
              onClick={() => setZoom(u)}
              className="h-28 max-w-[12rem] cursor-zoom-in rounded-lg border border-white/10 object-cover"
            />
          ) : (
            <span
              key={i}
              className="inline-flex items-center gap-1.5 rounded-md border border-white/10 bg-white/5 px-2 py-1 text-[10px] text-white/40"
            >
              <ImageOff className="h-3 w-3" />
              Image indisponible
            </span>
          )
        )}
      </div>

      {zoom ? (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/85 p-4"
          onClick={() => setZoom(null)}
        >
          <button
            type="button"
            onClick={() => setZoom(null)}
            aria-label="Fermer"
            className="absolute right-4 top-4 rounded-full bg-white/10 p-2 text-white hover:bg-white/20"
          >
            <X className="h-5 w-5" />
          </button>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={zoom}
            alt="Photo"
            onClick={(e) => e.stopPropagation()}
            className="max-h-[90vh] max-w-full rounded-xl object-contain"
          />
        </div>
      ) : null}
    </>
  );
}
