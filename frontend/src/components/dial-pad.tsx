"use client";

// Dial pad téléphonique — composer un numéro et lancer un appel
// click-to-call qui passe par le 438 d'Horizon (le destinataire voit
// toujours Horizon, jamais le téléphone perso de l'utilisateur).
//
// Flow :
//   1. User tape un numéro
//   2. POST /api/v1/voice/calls/outbound (admin)
//   3. Twilio ring le cell de l'user (TWILIO_FORWARD_TO)
//   4. Quand l'user décroche, Twilio bridge vers la cible
//
// Aucun audio WebRTC ici — c'est du POTS classique côté user, ce qui
// garantit que ça marche partout (4G, WiFi, vieux téléphone).

import { useState } from "react";
import { Loader2, Phone, X } from "lucide-react";

import { authedFetch } from "@/lib/auth";

const KEYS = [
  ["1", ""],
  ["2", "ABC"],
  ["3", "DEF"],
  ["4", "GHI"],
  ["5", "JKL"],
  ["6", "MNO"],
  ["7", "PQRS"],
  ["8", "TUV"],
  ["9", "WXYZ"],
  ["*", ""],
  ["0", "+"],
  ["#", ""]
] as const;

function formatE164(input: string): string | null {
  const digits = input.replace(/[^\d+]/g, "");
  if (!digits) return null;
  // Cas standard nord-américain : 10 chiffres → +1XXXXXXXXXX.
  if (/^\d{10}$/.test(digits)) return `+1${digits}`;
  if (/^1\d{10}$/.test(digits)) return `+${digits}`;
  if (digits.startsWith("+")) return digits;
  return null;
}

function prettyDisplay(input: string): string {
  // Format visuel : (514) 555-1234 si 10 chiffres NA.
  const digits = input.replace(/[^\d]/g, "");
  if (input.startsWith("+")) {
    return input;
  }
  if (digits.length === 10) {
    return `(${digits.slice(0, 3)}) ${digits.slice(3, 6)}-${digits.slice(6)}`;
  }
  if (digits.length === 11 && digits.startsWith("1")) {
    return `+1 (${digits.slice(1, 4)}) ${digits.slice(4, 7)}-${digits.slice(7)}`;
  }
  return input;
}

export function DialPad({ onClose }: { onClose?: () => void }) {
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  function press(key: string) {
    if (key === "+" && value.length === 0) {
      setValue("+");
      return;
    }
    setValue((v) => (v + key).slice(0, 20));
  }

  function backspace() {
    setValue((v) => v.slice(0, -1));
  }

  async function dial() {
    setError(null);
    setNotice(null);
    const e164 = formatE164(value);
    if (!e164) {
      setError(
        "Format de numéro invalide. Tapez 10 chiffres ou +<indicatif><numéro>."
      );
      return;
    }
    setBusy(true);
    try {
      const r = await authedFetch("/api/v1/voice/calls/outbound", {
        method: "POST",
        body: JSON.stringify({ target_e164: e164 })
      });
      if (!r.ok) {
        const t = await r.text().catch(() => "");
        throw new Error(t.slice(0, 200) || `HTTP ${r.status}`);
      }
      setNotice(
        `Appel lancé vers ${e164}. Votre téléphone sonnera dans quelques secondes — décrochez pour parler à la cible.`
      );
    } catch (e) {
      setError(`Échec : ${(e as Error).message}`);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="w-full max-w-xs space-y-3">
      <div className="rounded-xl border border-brand-800 bg-brand-950 px-3 py-3">
        <div className="text-[10px] uppercase tracking-wider text-white/40">
          Numéro à composer
        </div>
        <div className="mt-1 flex items-center justify-between gap-2">
          <input
            type="tel"
            value={value}
            onChange={(e) => setValue(e.target.value)}
            placeholder="(514) 555-1234"
            className="flex-1 bg-transparent font-mono text-xl text-white placeholder:text-white/30 focus:outline-none"
          />
          {value ? (
            <button
              type="button"
              onClick={backspace}
              className="rounded-full p-1 text-white/40 hover:bg-white/10 hover:text-white"
              aria-label="Effacer"
            >
              <X className="h-4 w-4" />
            </button>
          ) : null}
        </div>
        {value ? (
          <div className="mt-1 text-[10px] text-white/40">
            → {prettyDisplay(value)}
          </div>
        ) : null}
      </div>

      <div className="grid grid-cols-3 gap-1.5">
        {KEYS.map(([digit, letters]) => (
          <button
            key={digit}
            type="button"
            onClick={() => press(digit)}
            className="flex flex-col items-center justify-center rounded-xl border border-brand-800 bg-brand-900 py-3 transition hover:border-accent-500/40 hover:bg-brand-800 active:scale-95"
          >
            <span className="text-xl font-semibold text-white">{digit}</span>
            {letters ? (
              <span className="text-[9px] tracking-widest text-white/40">
                {letters}
              </span>
            ) : null}
          </button>
        ))}
      </div>

      <button
        type="button"
        onClick={dial}
        disabled={busy || value.length === 0}
        className="flex w-full items-center justify-center gap-2 rounded-xl bg-emerald-500 px-4 py-3 text-sm font-semibold text-emerald-950 transition hover:bg-emerald-400 disabled:opacity-50"
      >
        {busy ? (
          <Loader2 className="h-5 w-5 animate-spin" />
        ) : (
          <Phone className="h-5 w-5" />
        )}
        Appeler
      </button>

      {error ? (
        <p className="rounded-md border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
          {error}
        </p>
      ) : null}
      {notice ? (
        <p className="rounded-md border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-xs text-emerald-300">
          {notice}
        </p>
      ) : null}

      <p className="text-[10px] text-white/40">
        L&apos;appel passe par le 438 d&apos;Horizon. La cible verra
        notre numéro, jamais le vôtre.
      </p>

      {onClose ? (
        <button
          type="button"
          onClick={onClose}
          className="w-full rounded-md border border-brand-800 px-3 py-1.5 text-[11px] text-white/60 hover:text-white"
        >
          Fermer
        </button>
      ) : null}
    </div>
  );
}
