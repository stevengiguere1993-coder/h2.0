"use client";

import { useEffect, useRef, useState } from "react";
import { Brain, Check, Loader2, Mic, Send, X } from "lucide-react";

import { authedFetch } from "@/lib/auth";

/**
 * Bouton flottant Kratos — bulle en bas à droite. Cliquable depuis
 * n'importe quel volet (Construction, Entreprises, Mobile…). Ouvre
 * une mini-fenêtre avec textarea + dictée vocale (Web Speech API)
 * + envoi au routeur `/api/v1/kratos/route`. Le résultat (succès /
 * needs_review) est affiché brièvement puis la modale se ferme.
 */

type KratosResponse = {
  id: number;
  intent_kind: string;
  summary: string | null;
  target_type: string | null;
  target_id: number | null;
  status: string;
};

const KIND_LABELS: Record<string, string> = {
  entreprise_task: "Tâche d'entreprise",
  lead_note: "Note sur lead",
  prospection_lead_note: "Note pipeline",
  note: "Note libre",
  unknown: "Non classé"
};

export function KratosFloating() {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [listening, setListening] = useState(false);
  const recogRef = useRef<unknown>(null);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);

  // Raccourci clavier Cmd/Ctrl + J pour ouvrir.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "j") {
        e.preventDefault();
        setOpen((v) => !v);
      } else if (e.key === "Escape" && open) {
        setOpen(false);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  useEffect(() => {
    if (open) {
      setTimeout(() => textareaRef.current?.focus(), 50);
    } else {
      setText("");
      setError(null);
      setSuccess(null);
    }
  }, [open]);

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
      const m = (await r.json()) as KratosResponse;
      const kindLabel = KIND_LABELS[m.intent_kind] || m.intent_kind;
      if (m.status === "routed") {
        setSuccess(`Classé · ${kindLabel}`);
      } else {
        setSuccess(`Enregistré · à confirmer (${kindLabel})`);
      }
      setText("");
      setTimeout(() => {
        setOpen(false);
      }, 1800);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSubmitting(false);
    }
  }

  function toggleMic() {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const w: any =
      typeof window !== "undefined" ? (window as unknown) : null;
    const SR = w?.SpeechRecognition || w?.webkitSpeechRecognition;
    if (!SR) {
      setError(
        "Dictée vocale non supportée — utilise Chrome ou Safari."
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
      {/* Bulle flottante */}
      {!open ? (
        <button
          type="button"
          onClick={() => setOpen(true)}
          title="Kratos · Cmd/Ctrl + J"
          aria-label="Ouvrir Kratos"
          // Calé au-dessus du bouton « Aide » (lui aussi en bas-droite)
          // pour ne pas le chevaucher / être caché derrière.
          className="fixed bottom-[4.75rem] right-5 z-40 inline-flex h-12 w-12 items-center justify-center rounded-full shadow-lg transition hover:scale-105"
          style={{
            backgroundColor: "var(--qg-accent, #d4ff3a)",
            color: "var(--qg-accent-ink, #0a0a0b)"
          }}
        >
          <Brain className="h-5 w-5" />
        </button>
      ) : null}

      {/* Mini-fenêtre */}
      {open ? (
        <div
          className="fixed inset-0 z-50 flex items-end justify-end p-3 sm:p-5"
          onClick={() => (!submitting ? setOpen(false) : null)}
        >
          <div
            onClick={(e) => e.stopPropagation()}
            className="w-full max-w-md rounded-2xl border bg-brand-900 p-4 shadow-xl"
            style={{
              borderColor: "var(--qg-border, rgba(255,255,255,0.1))",
              backgroundColor: "var(--qg-card-bg, #0f172a)"
            }}
          >
            <div className="flex items-center justify-between">
              <h3
                className="inline-flex items-center gap-2 text-sm font-bold"
                style={{ color: "var(--qg-text, #fff)" }}
              >
                <Brain
                  className="h-4 w-4"
                  style={{ color: "var(--qg-accent, #84cc16)" }}
                />
                Demander à Kratos
              </h3>
              <button
                type="button"
                onClick={() => setOpen(false)}
                className="rounded p-1 hover:bg-white/10"
                style={{ color: "var(--qg-text-muted)" }}
                aria-label="Fermer"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            <textarea
              ref={textareaRef}
              value={text}
              onChange={(e) => setText(e.target.value)}
              rows={5}
              placeholder="Tape ou dicte une note, un suivi, un courriel collé…"
              onKeyDown={(e) => {
                if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
                  e.preventDefault();
                  void submit();
                }
              }}
              className="mt-3 w-full resize-y rounded-lg border bg-transparent p-2.5 text-sm focus:outline-none"
              style={{
                borderColor: "var(--qg-border)",
                color: "var(--qg-text)"
              }}
            />

            <div className="mt-2 flex items-center justify-between gap-2">
              <button
                type="button"
                onClick={toggleMic}
                title="Dicter (Web Speech API)"
                aria-label="Dicter"
                className={`inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-xs font-semibold transition ${
                  listening
                    ? "border-rose-500/40 bg-rose-500/15 text-rose-300"
                    : "border-accent-500/40 bg-accent-500/10 text-accent-300 hover:bg-accent-500/20"
                }`}
              >
                <Mic
                  className={`h-3.5 w-3.5 ${listening ? "animate-pulse" : ""}`}
                />
                {listening ? "Écoute…" : "Dicter"}
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
                Envoyer
              </button>
            </div>

            {success ? (
              <p className="mt-2 inline-flex items-center gap-1 rounded-md border border-emerald-500/40 bg-emerald-500/10 px-2 py-1 text-xs text-emerald-300">
                <Check className="h-3.5 w-3.5" />
                {success}
              </p>
            ) : null}
            {error ? (
              <p className="mt-2 rounded-md border border-rose-500/40 bg-rose-500/10 px-2 py-1 text-xs text-rose-300">
                {error}
              </p>
            ) : null}

            <p
              className="mt-2 text-[10px]"
              style={{ color: "var(--qg-text-muted)" }}
            >
              ⌘/Ctrl + J pour rouvrir · ⌘/Ctrl + Enter pour envoyer
            </p>
          </div>
        </div>
      ) : null}
    </>
  );
}
