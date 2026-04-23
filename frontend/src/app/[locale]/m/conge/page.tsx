"use client";

import { useState } from "react";
import { Loader2, Palmtree, X } from "lucide-react";

import { useRouter } from "@/i18n/navigation";
import { authedFetch } from "@/lib/auth";

function today(): string {
  const d = new Date();
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

type Kind = "vacation" | "sick" | "personal";

export default function MobileConge() {
  const router = useRouter();
  const [kind, setKind] = useState<Kind>("vacation");
  const [startDate, setStartDate] = useState(today());
  const [endDate, setEndDate] = useState(today());
  const [startHour, setStartHour] = useState("08");
  const [startMin, setStartMin] = useState("00");
  const [endHour, setEndHour] = useState("17");
  const [endMin, setEndMin] = useState("00");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);

  // Pour les vacances, on prend la période complète (start 08:00 → end
  // 17:00). Pour une journée maladie / personnelle courte, on peut
  // choisir des heures précises le même jour.
  const multiDay = kind === "vacation";

  async function submit() {
    setBusy(true);
    setError(null);
    try {
      const effectiveEnd = multiDay ? endDate : startDate;
      const startIso = new Date(
        `${startDate}T${startHour}:${startMin}:00`
      ).toISOString();
      const endIso = new Date(
        `${effectiveEnd}T${endHour}:${endMin}:00`
      ).toISOString();
      const res = await authedFetch("/api/v1/mobile/leave", {
        method: "POST",
        body: JSON.stringify({
          kind,
          start_at: startIso,
          end_at: endIso,
          reason: reason.trim() || null
        })
      });
      if (!res.ok) {
        const txt = await res.text();
        throw new Error(txt.slice(0, 240));
      }
      setSuccess(true);
      setTimeout(() => {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        router.push("/m/conges" as any);
      }, 1200);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const kindLabel: Record<Kind, { title: string; emoji: string }> = {
    vacation: { title: "Demander des vacances", emoji: "🌴" },
    sick: { title: "Déclarer une journée maladie", emoji: "🤒" },
    personal: { title: "Déclarer une absence personnelle", emoji: "📋" }
  };

  return (
    <>
      <header
        className="sticky top-0 z-30 flex items-center justify-between border-b border-brand-800 bg-brand-950/95 px-4 py-3 backdrop-blur"
        style={{ paddingTop: "max(env(safe-area-inset-top), 0.75rem)" }}
      >
        <div className="flex items-center gap-2">
          <Palmtree className="h-4 w-4 text-accent-500" />
          <h1 className="text-base font-bold text-white">
            {kindLabel[kind].title}
          </h1>
        </div>
        <button
          type="button"
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          onClick={() => router.push("/m" as any)}
          className="rounded-md p-1 text-white/60 hover:bg-white/5"
          aria-label="Fermer"
        >
          <X className="h-4 w-4" />
        </button>
      </header>

      <div className="space-y-4 p-4">
        {success ? (
          <div className="rounded-xl border border-emerald-500/40 bg-emerald-500/10 px-4 py-3 text-sm text-emerald-200">
            Demande envoyée. Retour à la liste…
          </div>
        ) : null}

        <div>
          <label className="text-xs font-medium uppercase tracking-wider text-white/60">
            Type de demande
          </label>
          <div className="mt-1 grid grid-cols-3 gap-2">
            {(["vacation", "sick", "personal"] as Kind[]).map((k) => (
              <button
                key={k}
                type="button"
                onClick={() => setKind(k)}
                className={`rounded-lg border px-2 py-2 text-xs ${
                  kind === k
                    ? "border-accent-500 bg-accent-500/15 text-white"
                    : "border-brand-800 bg-brand-900 text-white/60"
                }`}
              >
                {kindLabel[k].emoji}{" "}
                {k === "vacation"
                  ? "Vacances"
                  : k === "sick"
                  ? "Maladie"
                  : "Personnel"}
              </button>
            ))}
          </div>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="text-xs font-medium uppercase tracking-wider text-white/60">
              {multiDay ? "Du" : "Date"}
            </label>
            <input
              type="date"
              value={startDate}
              onChange={(e) => {
                setStartDate(e.target.value);
                // Garde la date de fin ≥ date de début
                if (multiDay && e.target.value > endDate) {
                  setEndDate(e.target.value);
                }
              }}
              className="mt-1 w-full rounded-lg border border-brand-800 bg-brand-900 px-3 py-2.5 text-white"
            />
          </div>
          {multiDay ? (
            <div>
              <label className="text-xs font-medium uppercase tracking-wider text-white/60">
                Au
              </label>
              <input
                type="date"
                value={endDate}
                min={startDate}
                onChange={(e) => setEndDate(e.target.value)}
                className="mt-1 w-full rounded-lg border border-brand-800 bg-brand-900 px-3 py-2.5 text-white"
              />
            </div>
          ) : null}
        </div>

        {!multiDay ? (
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs font-medium uppercase tracking-wider text-white/60">
                Heure de début
              </label>
              <div className="mt-1 flex items-center gap-1">
                <Stepper value={startHour} setValue={setStartHour} max={23} />
                <span className="text-white/50">:</span>
                <Stepper
                  value={startMin}
                  setValue={setStartMin}
                  max={59}
                  step={5}
                />
              </div>
            </div>
            <div>
              <label className="text-xs font-medium uppercase tracking-wider text-white/60">
                Heure de fin
              </label>
              <div className="mt-1 flex items-center gap-1">
                <Stepper value={endHour} setValue={setEndHour} max={23} />
                <span className="text-white/50">:</span>
                <Stepper
                  value={endMin}
                  setValue={setEndMin}
                  max={59}
                  step={5}
                />
              </div>
            </div>
          </div>
        ) : null}

        <div>
          <label className="text-xs font-medium uppercase tracking-wider text-white/60">
            Raison (optionnel)
          </label>
          <textarea
            rows={3}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder={
              kind === "vacation"
                ? "Ex. Voyage en famille, vacances d'été…"
                : kind === "sick"
                ? "Ex. Grippe, rendez-vous médical…"
                : "Note ou raison"
            }
            className="mt-1 w-full rounded-lg border border-brand-800 bg-brand-900 px-3 py-2.5 text-sm text-white"
          />
        </div>

        {error ? <p className="text-sm text-rose-300">{error}</p> : null}

        <div className="flex gap-3 pt-2">
          <button
            type="button"
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            onClick={() => router.push("/m" as any)}
            disabled={busy}
            className="flex-1 rounded-xl border border-brand-800 px-4 py-3 text-sm font-semibold text-white/80"
          >
            Annuler
          </button>
          <button
            type="button"
            onClick={submit}
            disabled={busy}
            className="flex flex-[2] items-center justify-center gap-2 rounded-xl bg-accent-500 px-4 py-3 text-sm font-bold text-brand-950 disabled:opacity-60"
          >
            {busy ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Palmtree className="h-4 w-4" />
            )}
            Envoyer la demande
          </button>
        </div>
      </div>
    </>
  );
}

function Stepper({
  value,
  setValue,
  max,
  step = 1
}: {
  value: string;
  setValue: (v: string) => void;
  max: number;
  step?: number;
}) {
  return (
    <select
      value={value}
      onChange={(e) => setValue(e.target.value)}
      className="flex-1 rounded-lg border border-brand-800 bg-brand-900 px-2 py-2 text-white"
    >
      {Array.from({ length: Math.floor(max / step) + 1 }, (_, i) => i * step)
        .filter((v) => v <= max)
        .map((v) => {
          const s = String(v).padStart(2, "0");
          return (
            <option key={s} value={s}>
              {s}
            </option>
          );
        })}
    </select>
  );
}
