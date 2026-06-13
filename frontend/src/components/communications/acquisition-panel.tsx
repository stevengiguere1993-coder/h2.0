"use client";

import { useCallback, useEffect, useState } from "react";

import { Link } from "@/i18n/navigation";
import { authedFetch, getMe, getToken } from "@/lib/auth";

// ----------------------------------------------------------------------
// Réglages → Tableau Acquisition
//
// Vue « système d'acquisition » : l'entonnoir des leads (nouveaux →
// contactés → RDV → qualifiés → soumissionnés → gagnés) + taux de
// conversion, à partir des données réelles du CRM et de la téléphonie.
// Réservé owner/admin.
// ----------------------------------------------------------------------

type Stage = { key: string; label: string; count: number };
type Funnel = {
  days: number;
  total_leads: number;
  spam_filtered: number;
  lost: number;
  won: number;
  conversion_rate: number;
  stages: Stage[];
  voice: { calls_total: number; leads_captured: number };
};
type Me = { role?: string | null };

const PERIODS = [
  { days: 7, label: "7 jours" },
  { days: 30, label: "30 jours" },
  { days: 90, label: "90 jours" }
];

export function AcquisitionPanel() {
  const [checking, setChecking] = useState(true);
  const [allowed, setAllowed] = useState(false);
  const [data, setData] = useState<Funnel | null>(null);
  const [days, setDays] = useState(30);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async (d: number) => {
    setLoading(true);
    try {
      const res = await authedFetch(`/api/v1/acquisition/funnel?days=${d}`);
      if (!res.ok) throw new Error(`Erreur ${res.status}`);
      setData((await res.json()) as Funnel);
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    async function check() {
      const tok = getToken();
      if (!tok) {
        if (!cancelled) {
          setAllowed(false);
          setChecking(false);
        }
        return;
      }
      try {
        const me = (await getMe(tok)) as Me;
        const role = (me?.role || "").toLowerCase().trim();
        const ok = role === "owner" || role === "admin";
        if (!cancelled) {
          setAllowed(ok);
          setChecking(false);
          if (ok) void reload(days);
        }
      } catch {
        if (!cancelled) {
          setAllowed(false);
          setChecking(false);
        }
      }
    }
    void check();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reload]);

  function changePeriod(d: number) {
    setDays(d);
    void reload(d);
  }

  if (checking) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-brand-950 text-sm text-white/60">
        Vérification des accès…
      </div>
    );
  }
  if (!allowed) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-brand-950">
        <div className="rounded-xl border border-rose-500/40 bg-rose-500/10 p-6 text-center">
          <p className="text-sm font-semibold text-rose-200">Accès réservé</p>
          <p className="mt-1 text-xs text-white/70">
            Réservé aux propriétaires et administrateurs.
          </p>
          <Link
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            href={"/connexion" as any}
            className="mt-4 inline-flex text-xs text-rose-200 hover:underline"
          >
            Retour
          </Link>
        </div>
      </div>
    );
  }

  const maxCount = data
    ? Math.max(1, ...data.stages.map((s) => s.count))
    : 1;

  return (
    <div className="min-h-screen bg-brand-950">
      <div className="mx-auto max-w-4xl px-4 py-8 lg:px-6">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h1 className="text-2xl font-bold text-white">
              Tableau acquisition
            </h1>
            <p className="mt-1 text-sm text-white/70">
              L&apos;entonnoir de vos leads, du premier contact à la
              conversion.
            </p>
          </div>
          <div className="flex gap-1">
            {PERIODS.map((p) => (
              <button
                key={p.days}
                type="button"
                onClick={() => changePeriod(p.days)}
                className={`rounded-md px-3 py-1.5 text-xs font-semibold transition ${
                  days === p.days
                    ? "bg-accent-500 text-brand-950"
                    : "border border-brand-700 text-white/70 hover:bg-brand-800"
                }`}
              >
                {p.label}
              </button>
            ))}
          </div>
        </div>

        {error ? (
          <p className="mt-4 rounded-md border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">
            {error}
          </p>
        ) : null}

        {loading || !data ? (
          <p className="mt-8 text-sm text-white/50">Chargement…</p>
        ) : (
          <>
            {/* KPIs */}
            <div className="mt-6 grid grid-cols-2 gap-3 sm:grid-cols-4">
              <Kpi label="Leads" value={data.total_leads} tone="white" />
              <Kpi label="Gagnés" value={data.won} tone="emerald" />
              <Kpi
                label="Conversion"
                value={`${data.conversion_rate}%`}
                tone="violet"
              />
              <Kpi
                label="Spam filtré"
                value={data.spam_filtered}
                tone="muted"
              />
            </div>

            {/* Entonnoir */}
            <div className="mt-8">
              <h2 className="mb-3 text-xs font-bold uppercase tracking-wider text-accent-500">
                Entonnoir ({data.days} jours)
              </h2>
              <ul className="space-y-2">
                {data.stages.map((s) => {
                  const pct = Math.round((100 * s.count) / maxCount);
                  return (
                    <li key={s.key}>
                      <div className="mb-1 flex items-center justify-between text-xs">
                        <span className="font-medium text-white/85">
                          {s.label}
                        </span>
                        <span className="font-semibold text-white">
                          {s.count}
                        </span>
                      </div>
                      <div className="h-3 overflow-hidden rounded-full bg-brand-800">
                        <div
                          className="h-full rounded-full bg-accent-500"
                          style={{ width: `${Math.max(2, pct)}%` }}
                        />
                      </div>
                    </li>
                  );
                })}
              </ul>
              {data.lost > 0 ? (
                <p className="mt-3 text-[11px] text-white/50">
                  {data.lost} lead{data.lost > 1 ? "s" : ""} perdu
                  {data.lost > 1 ? "s" : ""} sur la période.
                </p>
              ) : null}
            </div>

            {/* Téléphonie */}
            <div className="mt-8">
              <h2 className="mb-3 text-xs font-bold uppercase tracking-wider text-teal-300">
                Téléphonie (Léa)
              </h2>
              <div className="grid grid-cols-2 gap-3">
                <Kpi
                  label="Appels reçus"
                  value={data.voice.calls_total}
                  tone="white"
                />
                <Kpi
                  label="Leads captés"
                  value={data.voice.leads_captured}
                  tone="teal"
                />
              </div>
            </div>

            <p className="mt-8 text-[11px] text-white/40">
              Source : pipeline CRM (demandes de contact) + journal d&apos;appels.
              Mise à jour en temps réel.
            </p>
          </>
        )}
      </div>
    </div>
  );
}

function Kpi({
  label,
  value,
  tone
}: {
  label: string;
  value: number | string;
  tone: "white" | "emerald" | "violet" | "teal" | "muted";
}) {
  const toneCls: Record<typeof tone, string> = {
    white: "text-white",
    emerald: "text-emerald-300",
    violet: "text-violet-300",
    teal: "text-teal-300",
    muted: "text-white/50"
  };
  return (
    <div className="rounded-xl border border-brand-800 bg-brand-900 p-3">
      <div className="text-[11px] uppercase tracking-wide text-white/50">
        {label}
      </div>
      <div className={`mt-1 text-xl font-bold ${toneCls[tone]}`}>{value}</div>
    </div>
  );
}
