"use client";

import { useCallback, useEffect, useState } from "react";
import { Loader2, Play, Square, Timer } from "lucide-react";

import { authedFetch } from "@/lib/auth";

type OpenPunch = {
  id: number;
  started_at: string;
  project_id: number | null;
  task: string | null;
};

type Me = {
  open_punch: OpenPunch | null;
};

function hhmmss(ms: number): string {
  const total = Math.floor(ms / 1000);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  const p = (n: number) => String(n).padStart(2, "0");
  return `${p(h)}:${p(m)}:${p(s)}`;
}

export default function MobilePunch() {
  const [data, setData] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [now, setNow] = useState(() => new Date());

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await authedFetch("/api/v1/mobile/me");
      if (!res.ok) throw new Error();
      setData((await res.json()) as Me);
    } catch {
      setError("Chargement échoué.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (!data?.open_punch) return;
    const t = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(t);
  }, [data?.open_punch]);

  async function start() {
    setBusy(true);
    setError(null);
    try {
      const res = await authedFetch("/api/v1/mobile/punch/start", {
        method: "POST",
        body: JSON.stringify({})
      });
      if (!res.ok) {
        const txt = await res.text();
        throw new Error(txt.slice(0, 240));
      }
      await load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function stop() {
    setBusy(true);
    setError(null);
    try {
      const res = await authedFetch("/api/v1/mobile/punch/stop", {
        method: "POST"
      });
      if (!res.ok) {
        const txt = await res.text();
        throw new Error(txt.slice(0, 240));
      }
      await load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const elapsed = data?.open_punch
    ? now.getTime() - new Date(data.open_punch.started_at).getTime()
    : 0;

  return (
    <>
      <header
        className="sticky top-0 z-30 border-b border-brand-800 bg-brand-950/95 px-4 py-3 backdrop-blur"
        style={{ paddingTop: "max(env(safe-area-inset-top), 0.75rem)" }}
      >
        <h1 className="text-base font-bold text-white">Punch</h1>
      </header>

      <div className="flex flex-col items-center gap-6 px-4 pt-8">
        {loading ? (
          <Loader2 className="h-5 w-5 animate-spin text-white/40" />
        ) : data?.open_punch ? (
          <>
            <div className="flex flex-col items-center">
              <Timer className="h-10 w-10 text-emerald-400" />
              <p className="mt-2 text-xs uppercase tracking-wider text-white/50">
                Punch en cours
              </p>
              <p className="mt-3 font-mono text-5xl font-bold text-white">
                {hhmmss(elapsed)}
              </p>
              <p className="mt-1 text-xs text-white/50">
                Démarré à{" "}
                {new Date(data.open_punch.started_at).toLocaleTimeString(
                  "fr-CA",
                  { hour: "2-digit", minute: "2-digit" }
                )}
              </p>
            </div>
            <button
              type="button"
              onClick={stop}
              disabled={busy}
              className="flex w-full max-w-xs items-center justify-center gap-2 rounded-xl bg-rose-500 px-5 py-5 text-lg font-bold text-white disabled:opacity-60"
            >
              {busy ? (
                <Loader2 className="h-5 w-5 animate-spin" />
              ) : (
                <Square className="h-5 w-5" />
              )}
              Arrêter
            </button>
          </>
        ) : (
          <>
            <div className="flex flex-col items-center">
              <Timer className="h-10 w-10 text-white/30" />
              <p className="mt-2 text-xs uppercase tracking-wider text-white/50">
                Aucun punch en cours
              </p>
            </div>
            <button
              type="button"
              onClick={start}
              disabled={busy}
              className="flex w-full max-w-xs items-center justify-center gap-2 rounded-xl bg-blue-500 px-5 py-5 text-lg font-bold text-white disabled:opacity-60"
            >
              {busy ? (
                <Loader2 className="h-5 w-5 animate-spin" />
              ) : (
                <Play className="h-5 w-5" />
              )}
              Poinçonner
            </button>
          </>
        )}

        {error ? (
          <p className="text-sm text-rose-300">{error}</p>
        ) : null}
      </div>
    </>
  );
}
