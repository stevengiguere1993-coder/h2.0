"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  AlertTriangle,
  Brain,
  Check,
  Lightbulb,
  Loader2,
  Mic,
  RefreshCw,
  Send,
  Sparkles,
  Trash2,
  X
} from "lucide-react";

import { QGTopbar } from "../layout";
import { authedFetch } from "@/lib/auth";
import { Link } from "@/i18n/navigation";

/**
 * Kratos — page « cerveau / secrétaire virtuel ».
 *
 * L'utilisateur tape (ou dicte) du texte libre. Claude le route vers
 * le bon endroit (tâche d'entreprise, note de lead, etc.). Inbox
 * persistante listant tout l'historique.
 */

type KratosMessage = {
  id: number;
  user_id: number | null;
  original_text: string;
  intent_kind: string;
  summary: string | null;
  target_type: string | null;
  target_id: number | null;
  status: string;
  intent_json: string | null;
  created_at: string;
  processed_at: string | null;
};

type KratosProblem = {
  id: number;
  entreprise_id: number;
  title: string;
  description: string | null;
  severity: string;
  suggested_action_kind: string | null;
  suggested_action_label: string | null;
  suggested_action_params: string | null;
  status: string;
  applied_target_type: string | null;
  applied_target_id: number | null;
  created_at: string;
  resolved_at: string | null;
};

type EntrepriseMini = { id: number; name: string };

const KIND_LABELS: Record<string, { label: string; cls: string }> = {
  entreprise_task: {
    label: "Tâche d'entreprise",
    cls: "bg-violet-500/15 text-violet-300 border-violet-500/30"
  },
  lead_note: {
    label: "Note sur lead",
    cls: "bg-emerald-500/15 text-emerald-300 border-emerald-500/30"
  },
  prospection_lead_note: {
    label: "Note pipeline",
    cls: "bg-sky-500/15 text-sky-300 border-sky-500/30"
  },
  note: {
    label: "Note libre",
    cls: "bg-white/10 text-white/70 border-white/20"
  },
  unknown: {
    label: "Non classé",
    cls: "bg-amber-500/15 text-amber-300 border-amber-500/30"
  }
};

function fmtDateTime(iso: string): string {
  try {
    return new Date(iso).toLocaleString("fr-CA", {
      month: "short",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit"
    });
  } catch {
    return iso;
  }
}

function targetHref(t: string | null, id: number | null): string | null {
  if (!t || !id) return null;
  switch (t) {
    case "entreprise_tache":
      return `/entreprises/taches`;
    case "lead_analysis":
      return `/prospection/analyses-leads?lead=${id}`;
    case "prospection_lead":
      return `/prospection/${id}` as string;
    default:
      return null;
  }
}

export default function KratosPage() {
  const [text, setText] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [messages, setMessages] = useState<KratosMessage[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [listening, setListening] = useState(false);
  const recogRef = useRef<unknown>(null);

  // ── Problèmes proactifs (Phase 4) ────────────────────────────
  const [problems, setProblems] = useState<KratosProblem[]>([]);
  const [entreprises, setEntreprises] = useState<EntrepriseMini[]>([]);
  const [scanningId, setScanningId] = useState<number | null>(null);
  const entById = (id: number) =>
    entreprises.find((e) => e.id === id)?.name || `Entreprise #${id}`;

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [r1, r2, r3] = await Promise.all([
        authedFetch("/api/v1/kratos/inbox?limit=50"),
        authedFetch("/api/v1/kratos/problems?status=open&limit=100"),
        authedFetch("/api/v1/entreprises?limit=200")
      ]);
      if (r1.ok) setMessages((await r1.json()) as KratosMessage[]);
      if (r2.ok) setProblems((await r2.json()) as KratosProblem[]);
      if (r3.ok) {
        const list = (await r3.json()) as Array<{ id: number; name: string }>;
        setEntreprises(list.map((e) => ({ id: e.id, name: e.name })));
      }
    } catch {
      /* silencieux */
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function scan(entrepriseId: number) {
    setScanningId(entrepriseId);
    try {
      const r = await authedFetch(
        `/api/v1/kratos/scan/${entrepriseId}?force=true`,
        { method: "POST" }
      );
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const created = (await r.json()) as KratosProblem[];
      setProblems((prev) => {
        const fresh = prev.filter((p) => p.entreprise_id !== entrepriseId);
        return [...created, ...fresh];
      });
    } catch (e) {
      setError(`Scan échoué : ${(e as Error).message}`);
    } finally {
      setScanningId(null);
    }
  }

  async function applyProblem(id: number) {
    try {
      const r = await authedFetch(
        `/api/v1/kratos/problems/${id}/apply`,
        { method: "POST" }
      );
      if (!r.ok) throw new Error();
      const updated = (await r.json()) as KratosProblem;
      setProblems((prev) =>
        prev.map((p) => (p.id === id ? updated : p))
      );
    } catch {
      setError("Application de la solution échouée.");
    }
  }

  async function dismissProblem(id: number) {
    try {
      const r = await authedFetch(
        `/api/v1/kratos/problems/${id}/dismiss`,
        { method: "POST" }
      );
      if (!r.ok && r.status !== 204) throw new Error();
      setProblems((prev) => prev.filter((p) => p.id !== id));
    } catch {
      setError("Rejet du problème échoué.");
    }
  }

  async function submit() {
    const t = text.trim();
    if (!t) return;
    setSubmitting(true);
    setError(null);
    setSuccess(null);
    try {
      const r = await authedFetch("/api/v1/kratos/route", {
        method: "POST",
        body: JSON.stringify({ text: t })
      });
      if (!r.ok) {
        const body = await r.text();
        throw new Error(body.slice(0, 200) || `HTTP ${r.status}`);
      }
      const m = (await r.json()) as KratosMessage;
      setMessages((prev) => [m, ...prev]);
      setText("");
      const kind = KIND_LABELS[m.intent_kind]?.label || m.intent_kind;
      if (m.status === "routed") {
        setSuccess(`Classé · ${kind}`);
      } else {
        setSuccess("Enregistré · à confirmer dans l'inbox");
      }
      setTimeout(() => setSuccess(null), 4000);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSubmitting(false);
    }
  }

  async function discard(id: number) {
    try {
      const r = await authedFetch(`/api/v1/kratos/${id}/discard`, {
        method: "POST"
      });
      if (!r.ok && r.status !== 204) throw new Error();
      setMessages((prev) =>
        prev.map((m) => (m.id === id ? { ...m, status: "discarded" } : m))
      );
    } catch {
      setError("Suppression échouée.");
    }
  }

  // ── Mode dictée (Web Speech API) ───────────────────────────────
  function toggleMic() {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const w: any =
      typeof window !== "undefined" ? (window as unknown) : null;
    const SR = w?.SpeechRecognition || w?.webkitSpeechRecognition;
    if (!SR) {
      setError(
        "La dictée vocale n'est pas supportée par ton navigateur — utilise Chrome ou Safari."
      );
      return;
    }
    if (listening) {
      try {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        (recogRef.current as any)?.stop();
      } catch {
        /* ignore */
      }
      setListening(false);
      return;
    }
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const rec: any = new SR();
    rec.lang = "fr-CA";
    rec.continuous = true;
    rec.interimResults = true;
    let accumulated = text ? text + " " : "";
    rec.onresult = (e: { results: ArrayLike<{ 0: { transcript: string }; isFinal: boolean }>; resultIndex: number }) => {
      let interim = "";
      let final = "";
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const r = e.results[i];
        if (r.isFinal) final += r[0].transcript;
        else interim += r[0].transcript;
      }
      if (final) {
        accumulated += final;
        setText(accumulated.trim());
      } else if (interim) {
        setText((accumulated + interim).trim());
      }
    };
    rec.onend = () => setListening(false);
    rec.onerror = () => setListening(false);
    rec.start();
    recogRef.current = rec;
    setListening(true);
  }

  return (
    <>
      <QGTopbar
        greeting={
          <span className="inline-flex items-center gap-2">
            <Brain className="h-4 w-4 text-accent-500" />
            Kratos · Cerveau
          </span>
        }
        subtitle="Ton secrétaire virtuel cross-volet"
      />

      <div className="p-4 lg:p-6">
        <header className="flex items-center gap-3">
          <span
            className="flex h-10 w-10 items-center justify-center rounded-xl bg-accent-500/15 text-accent-500"
            style={{ backgroundColor: "var(--qg-accent)", color: "var(--qg-accent-ink)" }}
          >
            <Brain className="h-5 w-5" />
          </span>
          <div>
            <h1 className="text-2xl font-bold" style={{ color: "var(--qg-text)" }}>
              Kratos · ton cerveau secrétaire
            </h1>
            <p className="text-xs" style={{ color: "var(--qg-text-muted)" }}>
              Dis ce que tu as en tête. Kratos classe automatiquement en
              tâche, suivi de lead, ou note. Dictée vocale supportée
              (Chrome / Safari).
            </p>
          </div>
        </header>

        {/* Capture box */}
        <section
          className="mt-5 rounded-2xl border p-4"
          style={{
            borderColor: "var(--qg-border)",
            backgroundColor: "var(--qg-card-bg)"
          }}
        >
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            rows={5}
            placeholder="Exemples :
— Suivi locataire 1-5 Elgin : payé son loyer en retard, prochaine relance lundi prochain.
— Note sur l'immeuble 3737 Ethel : courtier rappelle que les revenus annuels sont à 92 400 $.
— Vérifier auprès de QuickBooks si la facture #1012 a été payée cette semaine."
            className="w-full resize-y rounded-lg border bg-transparent p-3 text-sm focus:outline-none"
            style={{
              borderColor: "var(--qg-border)",
              color: "var(--qg-text)"
            }}
          />
          <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
            <button
              type="button"
              onClick={toggleMic}
              className={`inline-flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-xs font-semibold transition ${
                listening
                  ? "border-rose-500/40 bg-rose-500/15 text-rose-300"
                  : "border-accent-500/40 bg-accent-500/10 text-accent-300 hover:bg-accent-500/20"
              }`}
              title="Démarrer / arrêter la dictée vocale"
            >
              <Mic className={`h-3.5 w-3.5 ${listening ? "animate-pulse" : ""}`} />
              {listening ? "Écoute… (clique pour arrêter)" : "Dicter"}
            </button>
            <div className="flex items-center gap-2">
              {success ? (
                <span className="inline-flex items-center gap-1 text-xs text-emerald-300">
                  <Check className="h-3.5 w-3.5" />
                  {success}
                </span>
              ) : null}
              <button
                type="button"
                onClick={() => setText("")}
                disabled={!text}
                className="rounded-md px-3 py-1.5 text-xs transition hover:bg-white/5 disabled:opacity-40"
                style={{ color: "var(--qg-text-muted)" }}
              >
                Effacer
              </button>
              <button
                type="button"
                onClick={() => void submit()}
                disabled={submitting || !text.trim()}
                className="btn-accent inline-flex items-center gap-1.5 text-xs disabled:opacity-50"
              >
                {submitting ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Send className="h-3.5 w-3.5" />
                )}
                Envoyer à Kratos
              </button>
            </div>
          </div>
          {error ? (
            <p className="mt-2 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
              {error}
            </p>
          ) : null}
        </section>

        {/* Phase 4 — Problèmes proactifs */}
        <ProblemsSection
          problems={problems}
          entreprises={entreprises}
          scanningId={scanningId}
          onScan={scan}
          onApply={applyProblem}
          onDismiss={dismissProblem}
          entById={entById}
        />

        {/* Inbox */}
        <section className="mt-6">
          <h2
            className="text-xs font-semibold uppercase tracking-wider"
            style={{ color: "var(--qg-text-muted)" }}
          >
            <Sparkles className="mr-1 inline-block h-3.5 w-3.5" />
            Inbox · 50 dernières entrées
          </h2>
          {loading ? (
            <div className="mt-4 flex items-center justify-center py-8">
              <Loader2 className="h-5 w-5 animate-spin text-accent-500" />
            </div>
          ) : messages.length === 0 ? (
            <p
              className="mt-4 rounded-2xl border border-dashed px-6 py-12 text-center text-sm"
              style={{
                borderColor: "var(--qg-border-soft)",
                color: "var(--qg-text-muted)"
              }}
            >
              Aucune entrée pour l&apos;instant. Tape quelque chose et
              Kratos s&apos;occupe du reste.
            </p>
          ) : (
            <ul className="mt-3 space-y-2">
              {messages.map((m) => {
                const k = KIND_LABELS[m.intent_kind] || KIND_LABELS.note;
                const href = targetHref(m.target_type, m.target_id);
                const isDiscarded = m.status === "discarded";
                const needsReview = m.status === "needs_review";
                return (
                  <li
                    key={m.id}
                    className={`rounded-xl border p-3 ${
                      isDiscarded ? "opacity-50" : ""
                    }`}
                    style={{
                      borderColor: needsReview
                        ? "rgb(245 158 11 / 0.5)"
                        : "var(--qg-border)",
                      backgroundColor: "var(--qg-card-bg)"
                    }}
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center gap-2">
                          <span
                            className={`rounded-full border px-2 py-0.5 text-[10px] font-semibold ${k.cls}`}
                          >
                            {k.label}
                          </span>
                          {needsReview ? (
                            <span className="rounded-full border border-amber-500/40 bg-amber-500/15 px-2 py-0.5 text-[10px] font-semibold text-amber-300">
                              à confirmer
                            </span>
                          ) : null}
                          {isDiscarded ? (
                            <span className="rounded-full border border-rose-500/30 bg-rose-500/10 px-2 py-0.5 text-[10px] font-semibold text-rose-300">
                              rejeté
                            </span>
                          ) : null}
                          <span
                            className="text-[10px]"
                            style={{ color: "var(--qg-text-muted)" }}
                          >
                            {fmtDateTime(m.created_at)}
                          </span>
                        </div>
                        {m.summary ? (
                          <p
                            className="mt-1.5 text-sm font-semibold"
                            style={{ color: "var(--qg-text)" }}
                          >
                            {m.summary}
                          </p>
                        ) : null}
                        <p
                          className="mt-1 text-xs whitespace-pre-wrap"
                          style={{ color: "var(--qg-text-muted)" }}
                        >
                          {m.original_text.slice(0, 400)}
                          {m.original_text.length > 400 ? "…" : ""}
                        </p>
                        {href ? (
                          <Link
                            // eslint-disable-next-line @typescript-eslint/no-explicit-any
                            href={href as any}
                            className="mt-2 inline-block text-xs text-accent-400 hover:underline"
                          >
                            Ouvrir l&apos;objet créé →
                          </Link>
                        ) : null}
                      </div>
                      {!isDiscarded ? (
                        <button
                          type="button"
                          onClick={() => void discard(m.id)}
                          className="rounded p-1 text-white/40 hover:bg-rose-500/15 hover:text-rose-300"
                          title="Rejeter"
                          aria-label="Rejeter"
                        >
                          <X className="h-3.5 w-3.5" />
                        </button>
                      ) : null}
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
        </section>
      </div>
    </>
  );
}

// ─── Section problèmes proactifs (Phase 4) ─────────────────────

const SEVERITY_CLS: Record<string, string> = {
  high: "bg-rose-500/15 text-rose-300 border-rose-500/40",
  medium: "bg-amber-500/15 text-amber-300 border-amber-500/40",
  low: "bg-sky-500/15 text-sky-300 border-sky-500/30"
};

function ProblemsSection({
  problems,
  entreprises,
  scanningId,
  onScan,
  onApply,
  onDismiss,
  entById
}: {
  problems: KratosProblem[];
  entreprises: EntrepriseMini[];
  scanningId: number | null;
  onScan: (entrepriseId: number) => Promise<void>;
  onApply: (problemId: number) => Promise<void>;
  onDismiss: (problemId: number) => Promise<void>;
  entById: (id: number) => string;
}) {
  // Group by entreprise
  const byEnt = new Map<number, KratosProblem[]>();
  for (const p of problems) {
    const arr = byEnt.get(p.entreprise_id) || [];
    arr.push(p);
    byEnt.set(p.entreprise_id, arr);
  }
  // Liste : entreprises ayant déjà des problèmes en premier, puis
  // toutes les autres (pour pouvoir lancer un scan ad hoc).
  const orderedEnts: EntrepriseMini[] = [
    ...Array.from(byEnt.keys()).map((id) => ({
      id,
      name: entById(id)
    })),
    ...entreprises.filter((e) => !byEnt.has(e.id))
  ];

  return (
    <section className="mt-6">
      <h2
        className="text-xs font-semibold uppercase tracking-wider"
        style={{ color: "var(--qg-text-muted)" }}
      >
        <Lightbulb className="mr-1 inline-block h-3.5 w-3.5" />
        Problèmes détectés & solutions
      </h2>
      <p
        className="mt-0.5 text-[10px]"
        style={{ color: "var(--qg-text-muted)" }}
      >
        Kratos analyse chaque entreprise (1×/jour) et propose 3 à 5
        actions concrètes. Tu peux relancer un scan à la demande.
      </p>

      <div className="mt-3 space-y-3">
        {orderedEnts.length === 0 ? (
          <p
            className="rounded-2xl border border-dashed px-6 py-8 text-center text-xs"
            style={{
              borderColor: "var(--qg-border-soft)",
              color: "var(--qg-text-muted)"
            }}
          >
            Aucune entreprise active.
          </p>
        ) : null}
        {orderedEnts.map((ent) => {
          const list = byEnt.get(ent.id) || [];
          return (
            <div
              key={ent.id}
              className="rounded-xl border p-3"
              style={{
                borderColor: "var(--qg-border)",
                backgroundColor: "var(--qg-card-bg)"
              }}
            >
              <div className="flex items-center justify-between gap-2">
                <h3
                  className="text-sm font-semibold"
                  style={{ color: "var(--qg-text)" }}
                >
                  {ent.name}
                  <span
                    className="ml-2 text-[10px] font-normal"
                    style={{ color: "var(--qg-text-muted)" }}
                  >
                    {list.length} problème{list.length > 1 ? "s" : ""}{" "}
                    ouvert{list.length > 1 ? "s" : ""}
                  </span>
                </h3>
                <button
                  type="button"
                  onClick={() => void onScan(ent.id)}
                  disabled={scanningId === ent.id}
                  className="inline-flex items-center gap-1 rounded-md border border-accent-500/40 bg-accent-500/10 px-2 py-1 text-[11px] font-semibold text-accent-300 hover:bg-accent-500/20 disabled:opacity-40"
                  title="Lancer un scan IA maintenant"
                >
                  {scanningId === ent.id ? (
                    <Loader2 className="h-3 w-3 animate-spin" />
                  ) : (
                    <RefreshCw className="h-3 w-3" />
                  )}
                  Scanner
                </button>
              </div>
              {list.length === 0 ? (
                <p
                  className="mt-2 text-[11px]"
                  style={{ color: "var(--qg-text-muted)" }}
                >
                  Aucun problème détecté — clique « Scanner » pour
                  demander une analyse à Kratos.
                </p>
              ) : (
                <ul className="mt-2 space-y-2">
                  {list.map((p) => (
                    <li
                      key={p.id}
                      className="rounded-lg border p-2.5"
                      style={{
                        borderColor: "var(--qg-border-soft)",
                        backgroundColor: "var(--qg-bg-alt, transparent)"
                      }}
                    >
                      <div className="flex items-start justify-between gap-2">
                        <div className="min-w-0 flex-1">
                          <div className="flex flex-wrap items-center gap-1.5">
                            <AlertTriangle className="h-3 w-3 text-amber-400" />
                            <span
                              className={`rounded-full border px-1.5 py-0 text-[9px] font-bold uppercase ${
                                SEVERITY_CLS[p.severity] || SEVERITY_CLS.medium
                              }`}
                            >
                              {p.severity}
                            </span>
                            <span
                              className="text-sm font-semibold"
                              style={{ color: "var(--qg-text)" }}
                            >
                              {p.title}
                            </span>
                          </div>
                          {p.description ? (
                            <p
                              className="mt-1 text-xs"
                              style={{ color: "var(--qg-text-muted)" }}
                            >
                              {p.description}
                            </p>
                          ) : null}
                          <div className="mt-2 flex flex-wrap items-center gap-2">
                            {p.suggested_action_kind === "create_task" ? (
                              <button
                                type="button"
                                onClick={() => void onApply(p.id)}
                                className="btn-accent inline-flex items-center gap-1 text-[11px]"
                              >
                                <Check className="h-3 w-3" />
                                {p.suggested_action_label || "Créer la tâche"}
                              </button>
                            ) : p.suggested_action_label ? (
                              <span
                                className="rounded-md border px-2 py-0.5 text-[11px]"
                                style={{
                                  borderColor: "var(--qg-border)",
                                  color: "var(--qg-text-muted)"
                                }}
                              >
                                {p.suggested_action_label}
                              </span>
                            ) : null}
                            <button
                              type="button"
                              onClick={() => void onDismiss(p.id)}
                              className="text-[11px] hover:underline"
                              style={{ color: "var(--qg-text-muted)" }}
                            >
                              Rejeter
                            </button>
                          </div>
                        </div>
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          );
        })}
      </div>
    </section>
  );
}
