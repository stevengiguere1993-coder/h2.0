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

import { PageDriveSection } from "@/components/drive/PageDriveSection";
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
  entreprise_id: number | null;
  problem_text: string | null;
  title: string;
  description: string | null;
  severity: string;
  solution_plan: string | null;
  solution_steps_json: string | null;
  suggested_action_kind: string | null;
  suggested_action_label: string | null;
  suggested_action_params: string | null;
  status: string;
  applied_target_type: string | null;
  applied_target_id: number | null;
  created_at: string;
  resolved_at: string | null;
};

type SolutionStep = {
  title: string;
  description?: string;
  entreprise_id?: number | null;
  action_kind?: string;
  action_params?: Record<string, unknown>;
};

type EntrepriseMini = { id: number; name: string };

const KIND_LABELS: Record<string, { label: string; cls: string }> = {
  entreprise_task: {
    label: "Tâche d'entreprise",
    cls: "badge-violet"
  },
  lead_note: {
    label: "Note sur lead",
    cls: "badge-emerald"
  },
  prospection_lead_note: {
    label: "Note pipeline",
    cls: "badge-sky"
  },
  note: {
    label: "Note libre",
    cls: "badge-neutral"
  },
  unknown: {
    label: "Non classé",
    cls: "badge-amber"
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

  // ── Problèmes user-driven (Phase 4 réorientée) ──────────────
  const [problems, setProblems] = useState<KratosProblem[]>([]);
  const [entreprises, setEntreprises] = useState<EntrepriseMini[]>([]);
  const [problemText, setProblemText] = useState("");
  const [solving, setSolving] = useState(false);
  const [solveErr, setSolveErr] = useState<string | null>(null);
  const [problemListening, setProblemListening] = useState(false);
  const problemRecogRef = useRef<unknown>(null);
  const entById = (id: number | null | undefined) =>
    id == null
      ? "Transverse"
      : entreprises.find((e) => e.id === id)?.name || `Entreprise #${id}`;

  async function solveProblem() {
    const t = problemText.trim();
    if (!t) return;
    setSolving(true);
    setSolveErr(null);
    try {
      const r = await authedFetch("/api/v1/kratos/solve", {
        method: "POST",
        body: JSON.stringify({ text: t })
      });
      if (!r.ok) {
        const body = await r.text();
        throw new Error(body.slice(0, 200) || `HTTP ${r.status}`);
      }
      const p = (await r.json()) as KratosProblem;
      setProblems((prev) => [p, ...prev]);
      setProblemText("");
    } catch (e) {
      setSolveErr((e as Error).message);
    } finally {
      setSolving(false);
    }
  }

  function toggleProblemMic() {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const w: any =
      typeof window !== "undefined" ? (window as unknown) : null;
    const SR = w?.SpeechRecognition || w?.webkitSpeechRecognition;
    if (!SR) {
      setSolveErr(
        "Dictée vocale non supportée — utilise Chrome ou Safari."
      );
      return;
    }
    if (problemListening) {
      try {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        (problemRecogRef.current as any)?.stop();
      } catch {
        /* ignore */
      }
      setProblemListening(false);
      return;
    }
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const rec: any = new SR();
    rec.lang = "fr-CA";
    rec.continuous = true;
    rec.interimResults = true;
    let accumulated = problemText ? problemText + " " : "";
    rec.onresult = (e: {
      results: ArrayLike<{ 0: { transcript: string }; isFinal: boolean }>;
      resultIndex: number;
    }) => {
      let interim = "";
      let final = "";
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const r = e.results[i];
        if (r.isFinal) final += r[0].transcript;
        else interim += r[0].transcript;
      }
      if (final) {
        accumulated += final;
        setProblemText(accumulated.trim());
      } else if (interim) {
        setProblemText((accumulated + interim).trim());
      }
    };
    rec.onend = () => setProblemListening(false);
    rec.onerror = () => setProblemListening(false);
    rec.start();
    problemRecogRef.current = rec;
    setProblemListening(true);
  }

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
        <PageDriveSection
          pageKey="page:entreprises:kratos"
          pole="Gestion d'entreprises"
          label="Cerveau Kratos"
          route="/entreprises/kratos"
        />
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
              className={
                listening ? "btn-outline-rose btn-sm" : "btn-outline-accent btn-sm"
              }
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
                className="btn-ghost btn-sm disabled:opacity-40"
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

        {/* Phase 4 réorientée — Problèmes user-driven + solutions IA */}
        <UserDrivenProblemsSection
          problems={problems}
          problemText={problemText}
          setProblemText={setProblemText}
          solving={solving}
          solveErr={solveErr}
          onSolve={() => void solveProblem()}
          listening={problemListening}
          onToggleMic={toggleProblemMic}
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
                          <span className={`badge ${k.cls}`}>
                            {k.label}
                          </span>
                          {needsReview ? (
                            <span className="badge badge-amber">
                              à confirmer
                            </span>
                          ) : null}
                          {isDiscarded ? (
                            <span className="badge badge-rose">
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
                          className="btn-ghost btn-xs"
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


// ─── Section problèmes user-driven (Phase 4 réorientée) ────────

const SEVERITY_CLS: Record<string, string> = {
  high: "badge-rose",
  medium: "badge-amber",
  low: "badge-sky"
};

function UserDrivenProblemsSection({
  problems,
  problemText,
  setProblemText,
  solving,
  solveErr,
  onSolve,
  listening,
  onToggleMic,
  onApply,
  onDismiss,
  entById
}: {
  problems: KratosProblem[];
  problemText: string;
  setProblemText: (s: string) => void;
  solving: boolean;
  solveErr: string | null;
  onSolve: () => void;
  listening: boolean;
  onToggleMic: () => void;
  onApply: (id: number) => Promise<void>;
  onDismiss: (id: number) => Promise<void>;
  entById: (id: number | null | undefined) => string;
}) {
  return (
    <section className="mt-6">
      <h2
        className="text-xs font-semibold uppercase tracking-wider"
        style={{ color: "var(--qg-text-muted)" }}
      >
        <Lightbulb className="mr-1 inline-block h-3.5 w-3.5" />
        Problèmes & solutions
      </h2>
      <p
        className="mt-0.5 text-[10px]"
        style={{ color: "var(--qg-text-muted)" }}
      >
        Décris (ou dicte) un problème. Kratos propose un plan d&apos;action
        en tenant compte de tes entreprises, ressources et solutions
        externes.
      </p>

      {/* Capture box pour décrire un problème */}
      <div
        className="mt-3 rounded-2xl border p-4"
        style={{
          borderColor: "var(--qg-border)",
          backgroundColor: "var(--qg-card-bg)"
        }}
      >
        <textarea
          value={problemText}
          onChange={(e) => setProblemText(e.target.value)}
          rows={4}
          placeholder="Exemples :
— On a trop d'achats non-classés dans QuickBooks chaque mois — comment systématiser ?
— Pas de relève pour la gestion locative quand Marie part en congé.
— Comment automatiser les rappels de fin de bail pour les locataires ?"
          onKeyDown={(e) => {
            if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
              e.preventDefault();
              onSolve();
            }
          }}
          className="w-full resize-y rounded-lg border bg-transparent p-3 text-sm focus:outline-none"
          style={{
            borderColor: "var(--qg-border)",
            color: "var(--qg-text)"
          }}
        />
        <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
          <button
            type="button"
            onClick={onToggleMic}
            className={
              listening ? "btn-outline-rose btn-sm" : "btn-outline-accent btn-sm"
            }
          >
            <Mic
              className={`h-3.5 w-3.5 ${listening ? "animate-pulse" : ""}`}
            />
            {listening ? "Écoute…" : "Dicter"}
          </button>
          <button
            type="button"
            onClick={onSolve}
            disabled={solving || !problemText.trim()}
            className="btn-accent inline-flex items-center gap-1.5 text-xs disabled:opacity-50"
          >
            {solving ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Send className="h-3.5 w-3.5" />
            )}
            Demander un plan d&apos;action
          </button>
        </div>
        {solveErr ? (
          <p className="mt-2 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
            {solveErr}
          </p>
        ) : null}
      </div>

      {/* Liste des problèmes + solutions */}
      <div className="mt-3 space-y-3">
        {problems.length === 0 ? (
          <p
            className="rounded-2xl border border-dashed px-6 py-8 text-center text-xs"
            style={{
              borderColor: "var(--qg-border-soft)",
              color: "var(--qg-text-muted)"
            }}
          >
            Aucun problème pour l&apos;instant. Écris-en un et Kratos
            te propose un plan d&apos;action.
          </p>
        ) : null}
        {problems.map((p) => (
          <ProblemSolutionCard
            key={p.id}
            problem={p}
            entById={entById}
            onApply={() => void onApply(p.id)}
            onDismiss={() => void onDismiss(p.id)}
          />
        ))}
      </div>
    </section>
  );
}

function ProblemSolutionCard({
  problem,
  entById,
  onApply,
  onDismiss
}: {
  problem: KratosProblem;
  entById: (id: number | null | undefined) => string;
  onApply: () => void;
  onDismiss: () => void;
}) {
  let steps: SolutionStep[] = [];
  try {
    if (problem.solution_steps_json) {
      const parsed = JSON.parse(problem.solution_steps_json);
      if (Array.isArray(parsed)) steps = parsed as SolutionStep[];
    }
  } catch {
    /* ignore */
  }
  const isDismissed = problem.status === "dismissed";
  const isApplied = problem.status === "applied";

  return (
    <div
      className={`rounded-xl border p-4 ${isDismissed ? "opacity-50" : ""}`}
      style={{
        borderColor: "var(--qg-border)",
        backgroundColor: "var(--qg-card-bg)"
      }}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span
              className={`badge uppercase ${
                SEVERITY_CLS[problem.severity] || SEVERITY_CLS.medium
              }`}
            >
              {problem.severity}
            </span>
            <span
              className="rounded-full border px-2 py-0.5 text-[10px]"
              style={{
                borderColor: "var(--qg-border)",
                color: "var(--qg-text-muted)"
              }}
            >
              {entById(problem.entreprise_id)}
            </span>
            {isApplied ? (
              <span className="badge badge-emerald">
                appliqué
              </span>
            ) : null}
            {isDismissed ? (
              <span className="badge badge-rose">
                rejeté
              </span>
            ) : null}
          </div>
          <h3
            className="mt-2 text-sm font-bold"
            style={{ color: "var(--qg-text)" }}
          >
            {problem.title}
          </h3>
          {problem.problem_text ? (
            <p
              className="mt-1 whitespace-pre-wrap text-[11px] italic"
              style={{ color: "var(--qg-text-muted)" }}
            >
              « {problem.problem_text.slice(0, 400)}
              {problem.problem_text.length > 400 ? "…" : ""} »
            </p>
          ) : null}
        </div>
      </div>

      {problem.solution_plan ? (
        <div
          className="mt-3 rounded-lg border px-3 py-2 text-[12px] whitespace-pre-wrap"
          style={{
            borderColor: "var(--qg-border-soft)",
            backgroundColor: "var(--qg-bg-alt, transparent)",
            color: "var(--qg-text)"
          }}
        >
          {problem.solution_plan}
        </div>
      ) : null}

      {steps.length > 0 ? (
        <div className="mt-3">
          <h4
            className="text-[10px] font-semibold uppercase tracking-wider"
            style={{ color: "var(--qg-text-muted)" }}
          >
            Étapes proposées
          </h4>
          <ol className="mt-2 space-y-1.5">
            {steps.map((s, i) => (
              <li
                key={i}
                className="rounded-md border p-2 text-[11px]"
                style={{
                  borderColor: "var(--qg-border-soft)",
                  backgroundColor: "var(--qg-bg-alt, transparent)"
                }}
              >
                <p className="font-semibold" style={{ color: "var(--qg-text)" }}>
                  {i + 1}. {s.title}
                </p>
                {s.description ? (
                  <p className="mt-0.5" style={{ color: "var(--qg-text-muted)" }}>
                    {s.description}
                  </p>
                ) : null}
                {s.action_kind === "create_task" ? (
                  <p className="mt-0.5 text-[10px] text-accent-400">
                    → suggérée comme tâche d&apos;entreprise
                  </p>
                ) : null}
              </li>
            ))}
          </ol>
        </div>
      ) : null}

      {!isDismissed && !isApplied ? (
        <div className="mt-3 flex flex-wrap items-center gap-2">
          {problem.suggested_action_kind === "create_task" ? (
            <button
              type="button"
              onClick={onApply}
              className="btn-accent inline-flex items-center gap-1 text-[11px]"
            >
              <Check className="h-3 w-3" />
              Créer la 1ʳᵉ tâche
            </button>
          ) : null}
          <button
            type="button"
            onClick={onDismiss}
            className="text-[11px] hover:underline"
            style={{ color: "var(--qg-text-muted)" }}
          >
            Rejeter
          </button>
        </div>
      ) : null}
    </div>
  );
}
