"use client";

import { useEffect, useMemo, useState } from "react";
import {
  ArrowRight,
  Loader2,
  Mail,
  MessageSquare,
  Phone,
  Plus,
  Trash2
} from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { useAppLayout } from "../layout";
import { authedFetch } from "@/lib/auth";
import { useConfirm } from "@/components/confirm-dialog";

type Channel = "call" | "email" | "sms";

type Step = {
  id: number;
  position: number;
  channel: Channel;
  delay_days: number;
  label: string;
  email_template_id: number | null;
  active: boolean;
  created_at: string;
};

type Template = { id: number; name: string; category: string };

const CHANNEL_META: Record<
  Channel,
  { label: string; icon: typeof Phone; dot: string }
> = {
  call: { label: "Appel", icon: Phone, dot: "bg-amber-400" },
  email: { label: "Courriel", icon: Mail, dot: "bg-indigo-400" },
  sms: { label: "SMS", icon: MessageSquare, dot: "bg-blue-400" }
};

export default function RelancesPage() {
  const { onOpenSidebar } = useAppLayout();
  const confirm = useConfirm();
  const [steps, setSteps] = useState<Step[]>([]);
  const [templates, setTemplates] = useState<Template[]>([]);
  const [enabled, setEnabled] = useState(true);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const [sRes, tRes, setRes] = await Promise.all([
        authedFetch("/api/v1/relances/cadence"),
        authedFetch("/api/v1/email-templates"),
        authedFetch("/api/v1/relances/settings")
      ]);
      if (!sRes.ok) throw new Error(`http_${sRes.status}`);
      const s = (await sRes.json()) as Step[];
      const t = tRes.ok ? ((await tRes.json()) as Template[]) : [];
      setSteps(s);
      setTemplates(t);
      if (setRes.ok) {
        const cfg = (await setRes.json()) as { enabled: boolean };
        setEnabled(cfg.enabled);
      }
    } catch {
      setError("Impossible de charger la séquence de relance.");
    } finally {
      setLoading(false);
    }
  }

  async function toggleEnabled() {
    const next = !enabled;
    setEnabled(next);
    try {
      const res = await authedFetch("/api/v1/relances/settings", {
        method: "PUT",
        body: JSON.stringify({ enabled: next })
      });
      if (!res.ok) throw new Error();
    } catch {
      setEnabled(!next);
      setError("Changement d'activation échoué.");
    }
  }

  useEffect(() => {
    load();
  }, []);

  // Jour cumulé de chaque étape (somme des délais jusqu'à elle).
  const cumulativeDays = useMemo(() => {
    let acc = 0;
    return steps.map((s) => {
      acc += s.delay_days;
      return acc;
    });
  }, [steps]);

  async function patchStep(id: number, patch: Partial<Step>) {
    setSteps((xs) => xs.map((x) => (x.id === id ? { ...x, ...patch } : x)));
    try {
      const res = await authedFetch(`/api/v1/relances/cadence/${id}`, {
        method: "PATCH",
        body: JSON.stringify(patch)
      });
      if (!res.ok) throw new Error();
    } catch {
      setError("Enregistrement échoué.");
      load();
    }
  }

  async function addStep() {
    try {
      const res = await authedFetch("/api/v1/relances/cadence", {
        method: "POST",
        body: JSON.stringify({
          channel: "call",
          delay_days: 1,
          label: "Nouvelle étape"
        })
      });
      if (!res.ok) throw new Error();
      const created = (await res.json()) as Step;
      setSteps((xs) => [...xs, created]);
    } catch {
      setError("Ajout d'étape échoué.");
    }
  }

  async function removeStep(id: number) {
    const ok = await confirm({
      title: "Supprimer cette étape ?",
      description: "Elle sera retirée de la séquence de relance.",
      confirmLabel: "Supprimer",
      destructive: true
    });
    if (!ok) return;
    const prev = steps;
    setSteps((xs) => xs.filter((x) => x.id !== id));
    try {
      const res = await authedFetch(`/api/v1/relances/cadence/${id}`, {
        method: "DELETE"
      });
      if (!res.ok && res.status !== 204) throw new Error();
    } catch {
      setSteps(prev);
      setError("Suppression échouée.");
    }
  }

  return (
    <>
      <AppTopbar
        breadcrumbs={[
          { label: "Construction", href: "/app" },
          { label: "Relances" }
        ]}
        onOpenSidebar={onOpenSidebar}
        rightSlot={
          <button
            type="button"
            onClick={() => void addStep()}
            className="btn-accent text-sm"
          >
            <Plus className="mr-1.5 h-4 w-4" /> Étape
          </button>
        }
      />

      <div className="p-4 lg:p-6">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h1 className="text-2xl font-bold text-white">
              Séquence de relance
            </h1>
            <p className="mt-1 max-w-2xl text-sm text-white/60">
              Une seule séquence, appliquée à tous les leads. Quand un contact
              ne répond pas, les étapes s&apos;enchaînent automatiquement selon
              les délais ci-dessous. Les étapes « courriel » partent
              automatiquement à l&apos;échéance ; les appels apparaissent comme
              à faire.
            </p>
          </div>
          <button
            type="button"
            onClick={() => void toggleEnabled()}
            className={`flex items-center gap-2 rounded-lg border px-3 py-2 text-sm font-semibold transition ${
              enabled
                ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-300"
                : "border-brand-800 bg-brand-900 text-white/60"
            }`}
            title="Activer / couper le moteur de relances"
          >
            <span
              className={`h-2.5 w-2.5 rounded-full ${
                enabled ? "bg-emerald-400" : "bg-white/30"
              }`}
            />
            {enabled ? "Moteur activé" : "Moteur désactivé"}
          </button>
        </div>

        {error ? (
          <p className="mt-4 rounded-lg border border-rose-500/40 bg-rose-500/10 px-4 py-2 text-sm text-rose-300">
            {error}
          </p>
        ) : null}

        {loading ? (
          <div className="flex min-h-[30vh] items-center justify-center">
            <Loader2 className="h-6 w-6 animate-spin text-accent-500" />
          </div>
        ) : (
          <>
            {/* Aperçu visuel de la séquence */}
            <div className="mt-6 flex flex-wrap items-center gap-2 rounded-xl border border-brand-800 bg-brand-900/60 p-4">
              {steps.length === 0 ? (
                <p className="text-sm text-white/50">
                  Aucune étape. Ajoute la première avec « + Étape ».
                </p>
              ) : (
                steps.map((s, i) => {
                  const meta = CHANNEL_META[s.channel];
                  const Icon = meta.icon;
                  return (
                    <div key={s.id} className="flex items-center gap-2">
                      <div
                        className={`flex items-center gap-2 rounded-lg border px-3 py-2 ${
                          s.active
                            ? "border-brand-800 bg-brand-950"
                            : "border-brand-800 bg-brand-950 opacity-40"
                        }`}
                      >
                        <span className={`h-2 w-2 rounded-full ${meta.dot}`} />
                        <Icon className="h-4 w-4 text-white/70" />
                        <span className="text-xs font-semibold text-white">
                          {meta.label}
                        </span>
                        <span className="badge badge-neutral">
                          J+{cumulativeDays[i]}
                        </span>
                      </div>
                      {i < steps.length - 1 ? (
                        <ArrowRight className="h-4 w-4 text-white/30" />
                      ) : null}
                    </div>
                  );
                })
              )}
            </div>

            {/* Éditeur des étapes */}
            <div className="mt-6 space-y-3">
              {steps.map((s, i) => {
                const meta = CHANNEL_META[s.channel];
                const Icon = meta.icon;
                return (
                  <div
                    key={s.id}
                    className="rounded-xl border border-brand-800 bg-brand-900/60 p-4"
                  >
                    <div className="flex flex-wrap items-end gap-4">
                      <div className="flex items-center gap-2 self-center">
                        <span className="flex h-7 w-7 items-center justify-center rounded-full bg-brand-950 text-xs font-bold text-white/70">
                          {i + 1}
                        </span>
                        <Icon className="h-4 w-4 text-white/60" />
                      </div>

                      <div>
                        <label className="label">Canal</label>
                        <select
                          value={s.channel}
                          onChange={(e) =>
                            patchStep(s.id, {
                              channel: e.target.value as Channel
                            })
                          }
                          className="input sm:w-40"
                        >
                          <option value="call">Appel</option>
                          <option value="email">Courriel</option>
                          <option value="sms">SMS</option>
                        </select>
                      </div>

                      <div>
                        <label className="label">
                          Délai (jours)
                          <span className="ml-1 text-white/40">
                            après l&apos;étape précédente
                          </span>
                        </label>
                        <input
                          type="number"
                          min={0}
                          value={s.delay_days}
                          onChange={(e) =>
                            patchStep(s.id, {
                              delay_days: Math.max(0, Number(e.target.value) || 0)
                            })
                          }
                          className="input sm:w-28"
                        />
                      </div>

                      <div className="min-w-[200px] flex-1">
                        <label className="label">Libellé</label>
                        <input
                          type="text"
                          value={s.label}
                          onChange={(e) =>
                            patchStep(s.id, { label: e.target.value })
                          }
                          className="input"
                        />
                      </div>

                      <label className="flex items-center gap-2 self-center pb-2 text-xs text-white/70">
                        <input
                          type="checkbox"
                          checked={s.active}
                          onChange={(e) =>
                            patchStep(s.id, { active: e.target.checked })
                          }
                          className="h-4 w-4"
                        />
                        Active
                      </label>

                      <button
                        type="button"
                        onClick={() => removeStep(s.id)}
                        aria-label="Supprimer l'étape"
                        className="btn-outline-rose btn-xs self-center"
                      >
                        <Trash2 className="h-4 w-4" />
                      </button>
                    </div>

                    {s.channel === "email" ? (
                      <div className="mt-3 max-w-md">
                        <label className="label">Gabarit de courriel</label>
                        <select
                          value={s.email_template_id ?? ""}
                          onChange={(e) =>
                            patchStep(s.id, {
                              email_template_id: e.target.value
                                ? Number(e.target.value)
                                : null
                            })
                          }
                          className="input"
                        >
                          <option value="">— Choisir un gabarit —</option>
                          {templates.map((t) => (
                            <option key={t.id} value={String(t.id)}>
                              {t.name}
                            </option>
                          ))}
                        </select>
                        {templates.length === 0 ? (
                          <p className="mt-1 text-[11px] text-white/50">
                            Aucun gabarit. Crée-en un dans Paramètres →
                            Gabarits courriels.
                          </p>
                        ) : !s.email_template_id ? (
                          <p className="mt-1 text-[11px] text-amber-300/80">
                            Sans gabarit, cette étape courriel ne pourra pas
                            partir automatiquement.
                          </p>
                        ) : null}
                      </div>
                    ) : null}
                  </div>
                );
              })}
            </div>
          </>
        )}
      </div>
    </>
  );
}
