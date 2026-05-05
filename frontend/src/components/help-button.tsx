"use client";

import { useEffect, useRef, useState } from "react";
import { usePathname } from "next/navigation";
import {
  AlertCircle,
  HelpCircle,
  Loader2,
  MessageCircleQuestion,
  Send,
  X
} from "lucide-react";

import { authedFetch } from "@/lib/auth";

type Tab = "question" | "bug";

export function HelpButton({
  triggerClassName,
  triggerStyle
}: {
  /** Override pour la position du bouton flottant. Par défaut, en bas-droite
   *  sur le desktop (`bottom-5 right-5`). La PWA mobile a une nav fixe en bas
   *  donc on monte le bouton au-dessus. */
  triggerClassName?: string;
  triggerStyle?: React.CSSProperties;
} = {}) {
  const [open, setOpen] = useState(false);
  const [tab, setTab] = useState<Tab>("question");

  // Question state
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState<string | null>(null);
  const [askLoading, setAskLoading] = useState(false);
  const [askError, setAskError] = useState<string | null>(null);

  // Bug state
  const [bugMsg, setBugMsg] = useState("");
  const [bugLoading, setBugLoading] = useState(false);
  const [bugSent, setBugSent] = useState(false);
  const [bugError, setBugError] = useState<string | null>(null);

  const pathname = usePathname() || "";
  // Référence sur le bloc « Réponse » pour scroller dessus dès qu'elle
  // arrive (sur mobile la réponse pourrait apparaître hors écran).
  const answerRef = useRef<HTMLDivElement | null>(null);

  // ESC pour fermer
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  // Scroll automatique sur la réponse quand elle est prête.
  useEffect(() => {
    if (answer && answerRef.current) {
      answerRef.current.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }, [answer]);

  // Reset des messages quand on change d'onglet
  function switchTab(next: Tab) {
    setTab(next);
    setAskError(null);
    setBugError(null);
    setBugSent(false);
  }

  async function onAsk() {
    if (question.trim().length < 2) return;
    setAskLoading(true);
    setAskError(null);
    setAnswer(null);
    try {
      const res = await authedFetch("/api/v1/help/ask", {
        method: "POST",
        body: JSON.stringify({
          question: question.trim(),
          context_url: pathname
        })
      });
      if (!res.ok) {
        const txt = await res.text().catch(() => "");
        let msg = `HTTP ${res.status}`;
        try {
          const j = JSON.parse(txt);
          if (j?.detail) msg = j.detail;
        } catch {
          if (txt) msg = txt.slice(0, 200);
        }
        throw new Error(msg);
      }
      const j = (await res.json()) as { answer: string };
      setAnswer(j.answer);
    } catch (err) {
      setAskError((err as Error).message || "Erreur");
    } finally {
      setAskLoading(false);
    }
  }

  async function onSendBug() {
    if (bugMsg.trim().length < 2) return;
    setBugLoading(true);
    setBugError(null);
    setBugSent(false);
    try {
      const ua =
        typeof navigator !== "undefined"
          ? navigator.userAgent.slice(0, 500)
          : null;
      const res = await authedFetch("/api/v1/help/reports", {
        method: "POST",
        body: JSON.stringify({
          message: bugMsg.trim(),
          context_url: pathname.slice(0, 500),
          user_agent: ua
        })
      });
      if (!res.ok) {
        // Surface du détail réel : on essaie d'extraire le `detail`
        // du payload JSON FastAPI, sinon on tombe sur le texte brut.
        let txt = "";
        try {
          const j = await res.json();
          txt =
            (j?.detail && (typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail))) ||
            JSON.stringify(j);
        } catch {
          txt = await res.text().catch(() => "");
        }
        throw new Error(`HTTP ${res.status} — ${txt.slice(0, 200)}`);
      }
      setBugMsg("");
      setBugSent(true);
    } catch (err) {
      setBugError((err as Error).message || "Erreur");
    } finally {
      setBugLoading(false);
    }
  }

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        title="Aide"
        className={
          triggerClassName ??
          "fixed bottom-5 right-5 z-40 inline-flex items-center gap-2 rounded-full bg-accent-500 px-4 py-3 text-sm font-semibold text-brand-950 shadow-lg ring-1 ring-accent-500/40 hover:bg-accent-400"
        }
        style={triggerStyle}
      >
        <HelpCircle className="h-5 w-5" />
        Aide
      </button>

      {open ? (
        <>
          {/* Backdrop : transparent à la souris pour ne pas bloquer la
              page derrière, mais visible (semi-opaque). On capture les
              clics dessus pour fermer. */}
          <div
            className="fixed inset-0 z-40 bg-black/40 backdrop-blur-sm"
            onClick={() => setOpen(false)}
          />

          {/* Panneau latéral droit */}
          <aside
            className="fixed right-0 top-0 z-50 flex h-full w-full max-w-md flex-col border-l border-brand-800 bg-brand-950 shadow-2xl"
            role="dialog"
            aria-modal="true"
          >
            <header
              className="flex items-center justify-between border-b border-brand-800 px-4 py-3"
              style={{
                paddingTop:
                  "max(env(safe-area-inset-top), 0.75rem)"
              }}
            >
              <div>
                <h2 className="text-base font-bold text-white">
                  Centre d&apos;aide
                </h2>
                <p className="mt-0.5 text-[11px] text-white/50">
                  Pose une question ou signale un bug.
                </p>
              </div>
              <button
                type="button"
                onClick={() => setOpen(false)}
                className="rounded-md p-1.5 text-white/60 hover:bg-brand-900 hover:text-white"
              >
                <X className="h-5 w-5" />
              </button>
            </header>

            {/* Tabs */}
            <div className="grid grid-cols-2 border-b border-brand-800">
              <button
                type="button"
                onClick={() => switchTab("question")}
                className={`flex items-center justify-center gap-2 py-3 text-sm font-medium transition ${
                  tab === "question"
                    ? "border-b-2 border-accent-500 text-white"
                    : "text-white/60 hover:text-white"
                }`}
              >
                <MessageCircleQuestion className="h-4 w-4" />
                Question
              </button>
              <button
                type="button"
                onClick={() => switchTab("bug")}
                className={`flex items-center justify-center gap-2 py-3 text-sm font-medium transition ${
                  tab === "bug"
                    ? "border-b-2 border-accent-500 text-white"
                    : "text-white/60 hover:text-white"
                }`}
              >
                <AlertCircle className="h-4 w-4" />
                Signaler un bug
              </button>
            </div>

            <div className="flex-1 overflow-y-auto p-4">
              {tab === "question" ? (
                <div className="space-y-3">
                  <p className="text-xs text-white/60">
                    L&apos;assistant répond en quelques secondes. Réponse
                    indicative — pour un vrai bug, utilise l&apos;onglet
                    « Signaler un bug ».
                  </p>
                  <textarea
                    value={question}
                    onChange={(e) => setQuestion(e.target.value)}
                    rows={4}
                    placeholder="Ex. Comment créer un PO pour une phase précise ?"
                    className="w-full rounded-md border border-brand-800 bg-brand-900 px-3 py-2 text-sm text-white placeholder:text-white/40 focus:border-accent-500 focus:outline-none"
                  />
                  <button
                    type="button"
                    onClick={onAsk}
                    disabled={askLoading || question.trim().length < 2}
                    className="inline-flex items-center gap-2 rounded-md bg-accent-500 px-3 py-2 text-sm font-semibold text-brand-950 disabled:opacity-50"
                  >
                    {askLoading ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : (
                      <Send className="h-4 w-4" />
                    )}
                    Envoyer
                  </button>
                  {askLoading ? (
                    <p className="rounded-md border border-brand-800 bg-brand-900 px-3 py-2 text-xs text-white/60">
                      L&apos;assistant réfléchit… (quelques secondes)
                    </p>
                  ) : null}
                  {askError ? (
                    <p className="rounded-md border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
                      {askError}
                    </p>
                  ) : null}
                  {answer ? (
                    <div
                      ref={answerRef}
                      className="rounded-md border border-brand-800 bg-brand-900 px-3 py-3 text-sm text-white/85 whitespace-pre-wrap"
                    >
                      {answer}
                    </div>
                  ) : null}
                </div>
              ) : (
                <div className="space-y-3">
                  <p className="text-xs text-white/60">
                    Décris ce qui ne marche pas ou ce qui devrait être
                    amélioré. Steven verra la demande dans Paramètres et
                    décidera quoi faire.
                  </p>
                  <textarea
                    value={bugMsg}
                    onChange={(e) => setBugMsg(e.target.value)}
                    rows={6}
                    placeholder="Ex. Quand je clique sur convertir un PO en achat, ça ne fait rien."
                    className="w-full rounded-md border border-brand-800 bg-brand-900 px-3 py-2 text-sm text-white placeholder:text-white/40 focus:border-accent-500 focus:outline-none"
                  />
                  <p className="text-[10px] text-white/40">
                    Page courante : <span className="font-mono">{pathname}</span>
                  </p>
                  <button
                    type="button"
                    onClick={onSendBug}
                    disabled={bugLoading || bugMsg.trim().length < 2}
                    className="inline-flex items-center gap-2 rounded-md bg-accent-500 px-3 py-2 text-sm font-semibold text-brand-950 disabled:opacity-50"
                  >
                    {bugLoading ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : (
                      <Send className="h-4 w-4" />
                    )}
                    Envoyer le signalement
                  </button>
                  {bugError ? (
                    <p className="rounded-md border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
                      {bugError}
                    </p>
                  ) : null}
                  {bugSent ? (
                    <p className="rounded-md border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-xs text-emerald-300">
                      Merci ! Le signalement est en attente de triage.
                    </p>
                  ) : null}
                </div>
              )}
            </div>
          </aside>
        </>
      ) : null}
    </>
  );
}
