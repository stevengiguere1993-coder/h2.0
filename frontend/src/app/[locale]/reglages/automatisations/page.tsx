"use client";

import { useCallback, useEffect, useState } from "react";

import { Link } from "@/i18n/navigation";
import { authedFetch, getMe, getToken } from "@/lib/auth";

// ----------------------------------------------------------------------
// Réglages → Automatisations
//
// Hub central (réservé owner/admin) pour SUIVRE et activer/couper toutes
// les automatisations du portail (relances, rapports, synchros…). Volet
// invisible pour les autres rôles : pas dans le menu construction.
// ----------------------------------------------------------------------

type Param = {
  key: string;
  label: string;
  type: "int";
  default: number;
  help: string;
  value: number;
};

type Automation = {
  key: string;
  label: string;
  category: "relance" | "rapport" | "synchro" | "courriel" | "telephonie";
  trigger: "cron" | "evenement";
  schedule: string | null;
  description: string;
  controllable: boolean;
  enabled: boolean;
  last_run_at: string | null;
  params: Param[];
};

type Me = { email?: string | null; role?: string | null };

const CATEGORY_LABELS: Record<Automation["category"], string> = {
  relance: "Relances & rappels",
  rapport: "Rapports & alertes",
  synchro: "Synchronisations",
  courriel: "Courriels (événementiels)",
  telephonie: "Téléphonie (Léa)"
};

const CATEGORY_ORDER: Automation["category"][] = [
  "relance",
  "rapport",
  "synchro",
  "courriel",
  "telephonie"
];

function formatLastRun(iso: string | null): string {
  if (!iso) return "Jamais (ou non suivi)";
  const d = new Date(iso);
  return d.toLocaleString("fr-CA", {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit"
  });
}

export default function AutomationsPage() {
  const [checking, setChecking] = useState(true);
  const [allowed, setAllowed] = useState(false);
  const [items, setItems] = useState<Automation[]>([]);
  const [loading, setLoading] = useState(true);
  const [busyKey, setBusyKey] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      const res = await authedFetch("/api/v1/automations");
      if (!res.ok) throw new Error(`Erreur ${res.status}`);
      setItems((await res.json()) as Automation[]);
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
          if (ok) void reload();
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
  }, [reload]);

  async function toggle(a: Automation) {
    if (!a.controllable) return;
    setBusyKey(a.key);
    const prev = a.enabled;
    setItems((xs) =>
      xs.map((x) => (x.key === a.key ? { ...x, enabled: !prev } : x))
    );
    try {
      const res = await authedFetch(`/api/v1/automations/${a.key}`, {
        method: "PATCH",
        body: JSON.stringify({ enabled: !prev })
      });
      if (!res.ok) throw new Error(`Erreur ${res.status}`);
    } catch (e) {
      setItems((xs) =>
        xs.map((x) => (x.key === a.key ? { ...x, enabled: prev } : x))
      );
      setError(`Changement non enregistré : ${(e as Error).message}`);
    } finally {
      setBusyKey(null);
    }
  }

  function updateParam(key: string, paramKey: string, val: number) {
    setItems((xs) =>
      xs.map((x) =>
        x.key === key
          ? {
              ...x,
              params: x.params.map((p) =>
                p.key === paramKey ? { ...p, value: val } : p
              )
            }
          : x
      )
    );
  }

  async function saveConfig(a: Automation) {
    setBusyKey(a.key);
    try {
      const config = Object.fromEntries(a.params.map((p) => [p.key, p.value]));
      const res = await authedFetch(`/api/v1/automations/${a.key}/config`, {
        method: "PATCH",
        body: JSON.stringify({ config })
      });
      if (!res.ok) throw new Error(`Erreur ${res.status}`);
      setError(null);
    } catch (e) {
      setError(`Réglage non enregistré : ${(e as Error).message}`);
    } finally {
      setBusyKey(null);
    }
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
            Cette section est réservée aux propriétaires et administrateurs.
          </p>
          <Link
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            href={"/connexion" as any}
            className="mt-4 inline-flex items-center gap-1.5 text-xs text-rose-200 hover:underline"
          >
            Retour
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-brand-950">
      <div className="mx-auto max-w-5xl px-4 py-8 lg:px-6">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h1 className="text-2xl font-bold text-white">Automatisations</h1>
            <p className="mt-1 text-sm text-white/70">
              Suivez et activez/coupez toutes les automatisations du portail
              au même endroit. Réservé aux propriétaires et administrateurs.
            </p>
          </div>
          <button
            type="button"
            onClick={() => void reload()}
            className="rounded-md border border-brand-700 px-3 py-1.5 text-xs font-medium text-white/80 hover:bg-brand-800"
          >
            Rafraîchir
          </button>
        </div>

        {error ? (
          <p className="mt-4 rounded-md border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">
            {error}
          </p>
        ) : null}

        {loading ? (
          <p className="mt-8 text-sm text-white/50">Chargement…</p>
        ) : (
          <div className="mt-6 space-y-8">
            {CATEGORY_ORDER.map((cat) => {
              const group = items.filter((i) => i.category === cat);
              if (group.length === 0) return null;
              return (
                <section key={cat}>
                  <h2 className="mb-3 text-xs font-bold uppercase tracking-wider text-accent-500">
                    {CATEGORY_LABELS[cat]}
                  </h2>
                  <ul className="space-y-2">
                    {group.map((a) => (
                      <li
                        key={a.key}
                        className="rounded-xl border border-brand-800 bg-brand-900 p-3"
                      >
                        <div className="flex items-start justify-between gap-3">
                          <div className="min-w-0">
                            <div className="flex flex-wrap items-center gap-2">
                              <span className="text-sm font-semibold text-white">
                                {a.label}
                              </span>
                              {a.enabled ? (
                                <span className="rounded bg-emerald-500/20 px-1.5 py-0.5 text-[10px] font-semibold uppercase text-emerald-300">
                                  Actif
                                </span>
                              ) : (
                                <span className="rounded bg-rose-500/20 px-1.5 py-0.5 text-[10px] font-semibold uppercase text-rose-300">
                                  Coupé
                                </span>
                              )}
                              <span className="rounded bg-white/10 px-1.5 py-0.5 text-[10px] uppercase text-white/60">
                                {a.trigger === "cron" ? "Planifié" : "Événement"}
                              </span>
                            </div>
                            <p className="mt-1 text-xs text-white/70">
                              {a.description}
                            </p>
                            <p className="mt-1 text-[11px] text-white/50">
                              {a.schedule ? `Horaire : ${a.schedule} · ` : ""}
                              Dernière exécution : {formatLastRun(a.last_run_at)}
                            </p>
                          </div>
                          <div className="shrink-0">
                            {a.controllable ? (
                              <button
                                type="button"
                                disabled={busyKey === a.key}
                                onClick={() => void toggle(a)}
                                className={`rounded-md px-3 py-1.5 text-xs font-semibold transition disabled:opacity-50 ${
                                  a.enabled
                                    ? "bg-rose-500/20 text-rose-200 hover:bg-rose-500/30"
                                    : "bg-emerald-500/20 text-emerald-200 hover:bg-emerald-500/30"
                                }`}
                              >
                                {a.enabled ? "Couper" : "Activer"}
                              </button>
                            ) : (
                              <span className="text-[10px] text-white/40">
                                réglé ailleurs
                              </span>
                            )}
                          </div>
                        </div>

                        {a.params.length > 0 ? (
                          <div className="mt-3 flex flex-wrap items-end gap-3 border-t border-brand-800 pt-3">
                            {a.params.map((p) => (
                              <div key={p.key}>
                                <label className="block text-[10px] font-medium uppercase tracking-wide text-white/60">
                                  {p.label}
                                </label>
                                <input
                                  type="number"
                                  min={1}
                                  value={p.value}
                                  onChange={(e) =>
                                    updateParam(
                                      a.key,
                                      p.key,
                                      Number(e.target.value)
                                    )
                                  }
                                  className="mt-1 w-24 rounded-md border border-brand-700 bg-brand-950 px-2 py-1 text-sm text-white focus:border-accent-500 focus:outline-none"
                                />
                                {p.help ? (
                                  <p className="mt-0.5 max-w-[16rem] text-[10px] text-white/45">
                                    {p.help}
                                  </p>
                                ) : null}
                              </div>
                            ))}
                            <button
                              type="button"
                              disabled={busyKey === a.key}
                              onClick={() => void saveConfig(a)}
                              className="rounded-md bg-accent-500 px-3 py-1.5 text-xs font-semibold text-brand-950 transition hover:bg-accent-400 disabled:opacity-50"
                            >
                              Enregistrer
                            </button>
                          </div>
                        ) : null}
                      </li>
                    ))}
                  </ul>
                </section>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
