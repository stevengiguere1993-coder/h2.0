"use client";

// Bouton « Appeler » réutilisable (Téléphonie Phase 4).
//
// Click-to-call : POST /api/v1/voice/calls/outbound → Twilio appelle
// d'abord le mobile interne (TWILIO_FORWARD_TO), puis bridge vers la
// cible une fois qu'on décroche. La ligne `voice_calls` est créée avec
// `entity_type` / `entity_id` pour pouvoir la retrouver dans la fiche.
//
// Usage :
//
//   <CallButton targetE164={lead.owner_phone}
//               entityType="prospection_lead"
//               entityId={lead.id} />

import { useState } from "react";
import { Phone } from "lucide-react";

import { authedFetch } from "@/lib/auth";

export type CallButtonProps = {
  targetE164: string | null | undefined;
  entityType?: string;
  entityId?: number;
  label?: string;
  className?: string;
  /** Petit format (icône seule) ou inline texte. */
  variant?: "icon" | "full";
};

export function CallButton({
  targetE164,
  entityType,
  entityId,
  label = "Appeler",
  className,
  variant = "full"
}: CallButtonProps) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [okMsg, setOkMsg] = useState<string | null>(null);

  const normalized = normalizeE164(targetE164 || "");
  const disabled = busy || !normalized;

  async function call() {
    if (!normalized) return;
    setBusy(true);
    setError(null);
    setOkMsg(null);
    try {
      const res = await authedFetch("/api/v1/voice/calls/outbound", {
        method: "POST",
        body: JSON.stringify({
          target_e164: normalized,
          entity_type: entityType,
          entity_id: entityId
        })
      });
      if (!res.ok) {
        const text = await res.text().catch(() => "");
        throw new Error(text || `http_${res.status}`);
      }
      setOkMsg("Ton mobile va sonner — décroche pour parler.");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  const base =
    "inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-[11px] font-semibold transition disabled:opacity-40 disabled:cursor-not-allowed";
  const cls = normalized
    ? "border-teal-500/40 bg-teal-500/10 text-teal-200 hover:bg-teal-500/20"
    : "border-white/10 bg-white/5 text-white/40";

  return (
    <span className="inline-flex flex-col items-start gap-1">
      <button
        type="button"
        onClick={call}
        disabled={disabled}
        title={
          normalized
            ? `Appeler ${normalized}`
            : "Aucun numéro disponible pour cet enregistrement"
        }
        className={`${base} ${cls} ${className || ""}`}
      >
        <Phone className="h-3 w-3" />
        {variant === "full" ? (busy ? "Composition…" : label) : null}
      </button>
      {error ? (
        <span className="text-[10px] text-rose-300">{error}</span>
      ) : null}
      {okMsg ? (
        <span className="text-[10px] text-emerald-300">{okMsg}</span>
      ) : null}
    </span>
  );
}

function normalizeE164(s: string): string | null {
  const trimmed = s.trim();
  if (!trimmed) return null;
  // Si commence par +, on garde. Sinon, si 10 chiffres NANP → préfixe +1.
  if (trimmed.startsWith("+")) {
    const digits = trimmed.replace(/[^\d+]/g, "");
    return digits.length >= 8 ? digits : null;
  }
  const digits = trimmed.replace(/\D/g, "");
  if (digits.length === 10) return `+1${digits}`;
  if (digits.length === 11 && digits.startsWith("1")) return `+${digits}`;
  return null;
}
