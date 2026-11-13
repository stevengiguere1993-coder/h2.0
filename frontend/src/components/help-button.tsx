"use client";

import { useEffect, useRef, useState } from "react";
import { usePathname } from "next/navigation";
import {
  AlertCircle,
  History,
  HelpCircle,
  Loader2,
  MessageCircleQuestion,
  Send,
  X
} from "lucide-react";

import { authedFetch } from "@/lib/auth";

type Tab = "question" | "bug" | "mes";

/** Signalement retrouvé par la base de connaissances du Centre d'aide. */
type SignalementLie = {
  id: number;
  status: string;
  statut_libelle: string;
  section: string | null;
  message: string;
  resolution_notes: string | null;
  created_at: string;
  traite_le: string | null;
};

type Livraison = { date: string; sujet: string };

type MonSignalement = {
  id: number;
  status: string;
  statut_libelle: string;
  message: string;
  section: string | null;
  context_url: string | null;
  resolution_notes: string | null;
  created_at: string;
  traite_le: string | null;
};

/** Pastille de statut : fond pastel, encre foncée en thème clair
 *  (classes déjà remappées dans globals.css). */
const STATUT_PASTILLE: Record<string, string> = {
  pending: "border-amber-500/30 bg-amber-500/15 text-amber-300",
  accepted: "border-emerald-500/30 bg-emerald-500/15 text-emerald-300",
  rejected: "border-rose-500/30 bg-rose-500/15 text-rose-300",
  resolved: "border-emerald-500/30 bg-emerald-500/15 text-emerald-300"
};

function dateCourte(iso: string | null): string {
  if (!iso) return "";
  return new Date(iso).toLocaleDateString("fr-CA", {
    day: "numeric",
    month: "long",
    year: "numeric"
  });
}

function Pastille({ status, libelle }: { status: string; libelle: string }) {
  return (
    <span
      className={`rounded-full border px-2 py-0.5 text-[11px] font-semibold ${
        STATUT_PASTILLE[status] || "border-white/20 bg-white/10 text-white/70"
      }`}
    >
      {libelle}
    </span>
  );
}

/** Liste « déjà signalé / déjà livré » affichée sous une réponse ou
 *  pendant la rédaction d'un signalement. */
function Connaissances({
  titre,
  signalements,
  livraisons
}: {
  titre: string;
  signalements: SignalementLie[];
  livraisons: Livraison[];
}) {
  if (signalements.length === 0 && livraisons.length === 0) return null;
  return (
    <div className="space-y-2 rounded-md border border-brand-800 bg-brand-900 px-3 py-3">
      <p className="text-xs font-semibold text-white">{titre}</p>
      {signalements.map((s) => (
        <div key={s.id} className="rounded-md border border-brand-800 bg-brand-950/40 p-2">
          <div className="flex flex-wrap items-center gap-2">
            <Pastille status={s.status} libelle={s.statut_libelle} />
            <span className="text-[11px] text-white/70">
              #{s.id}
              {s.section ? ` · ${s.section}` : ""}
              {s.traite_le ? ` · le ${dateCourte(s.traite_le)}` : ` · signalé le ${dateCourte(s.created_at)}`}
            </span>
          </div>
          <p className="mt-1 line-clamp-3 text-xs text-white/85">{s.message}</p>
          {s.resolution_notes ? (
            <p className="mt-1 text-xs text-white">
              <span className="font-semibold">Note : </span>
              {s.resolution_notes}
            </p>
          ) : null}
        </div>
      ))}
      {livraisons.length > 0 ? (
        <div>
          <p className="mt-1 text-[11px] font-semibold uppercase tracking-wider text-white/70">
            Corrections et nouveautés déjà livrées
          </p>
          <ul className="mt-1 space-y-1">
            {livraisons.map((l, i) => (
              <li key={`${l.date}-${i}`} className="text-xs text-white/85">
                <span className="font-mono text-white/70">{l.date}</span> · {l.sujet}
              </li>
            ))}
          </ul>
          <p className="mt-1 text-[11px] text-white/70">
            Tu vois encore l&apos;ancien comportement ? Recharge la page avant
            de signaler.
          </p>
        </div>
      ) : null}
    </div>
  );
}

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
  const [answerSig, setAnswerSig] = useState<SignalementLie[]>([]);
  const [answerLiv, setAnswerLiv] = useState<Livraison[]>([]);
  const [askLoading, setAskLoading] = useState(false);
  const [askError, setAskError] = useState<string | null>(null);

  // Bug state
  const [bugMsg, setBugMsg] = useState("");
  const [bugLoading, setBugLoading] = useState(false);
  const [bugSent, setBugSent] = useState(false);
  const [bugError, setBugError] = useState<string | null>(null);
  const [bugPhoto, setBugPhoto] = useState<File | null>(null);
  const [bugPhotoPreview, setBugPhotoPreview] = useState<string | null>(null);
  // « Déjà signalé ou déjà réglé ? » pendant la rédaction.
  const [simSig, setSimSig] = useState<SignalementLie[]>([]);
  const [simLiv, setSimLiv] = useState<Livraison[]>([]);

  // Mes signalements (historique du déclarant)
  const [mes, setMes] = useState<MonSignalement[] | null>(null);
  const [mesLoading, setMesLoading] = useState(false);
  const [mesError, setMesError] = useState<string | null>(null);

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

  // Lien d'une notification « Ton signalement a été réglé / refusé » : ?aide=mes-signalements ouvre le panneau sur l'historique.
  useEffect(() => {
    if (typeof window === "undefined") return;
    const url = new URL(window.location.href);
    if (url.searchParams.get("aide") === "mes-signalements") {
      setOpen(true);
      setTab("mes");
      url.searchParams.delete("aide");
      window.history.replaceState(null, "", url.pathname + url.search + url.hash);
    }
  }, []);

  // Historique chargé à l'ouverture de l'onglet.
  useEffect(() => {
    if (!open || tab !== "mes") return;
    let annule = false;
    (async () => {
      setMesLoading(true);
      setMesError(null);
      try {
        const res = await authedFetch("/api/v1/help/mes-signalements");
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const j = (await res.json()) as MonSignalement[];
        if (!annule) setMes(j);
      } catch (err) {
        if (!annule) setMesError((err as Error).message || "Erreur");
      } finally {
        if (!annule) setMesLoading(false);
      }
    })();
    return () => {
      annule = true;
    };
  }, [open, tab]);

  // Recherche « déjà signalé / déjà réglé ? » pendant la rédaction.
  useEffect(() => {
    const texte = bugMsg.trim();
    if (tab !== "bug" || texte.length < 12) {
      setSimSig([]);
      setSimLiv([]);
      return;
    }
    let annule = false;
    const t = setTimeout(async () => {
      try {
        const res = await authedFetch(
          `/api/v1/help/similaires?q=${encodeURIComponent(texte.slice(0, 1000))}`
        );
        if (!res.ok) return;
        const j = (await res.json()) as {
          signalements: SignalementLie[];
          livraisons: Livraison[];
        };
        if (!annule) {
          setSimSig(j.signalements || []);
          setSimLiv(j.livraisons || []);
        }
      } catch {
        /* silencieux : simple aide */
      }
    }, 700);
    return () => {
      annule = true;
      clearTimeout(t);
    };
  }, [bugMsg, tab]);

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
    setAnswerSig([]);
    setAnswerLiv([]);
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
      const j = (await res.json()) as {
        answer: string;
        signalements?: SignalementLie[];
        livraisons?: Livraison[];
      };
      setAnswer(j.answer);
      setAnswerSig(j.signalements || []);
      setAnswerLiv(j.livraisons || []);
    } catch (err) {
      setAskError((err as Error).message || "Erreur");
    } finally {
      setAskLoading(false);
    }
  }

  function onPickPhoto(file: File | null) {
    setBugPhoto(file);
    if (bugPhotoPreview) {
      URL.revokeObjectURL(bugPhotoPreview);
    }
    setBugPhotoPreview(file ? URL.createObjectURL(file) : null);
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
      // multipart pour permettre l'attachement d'une photo
      // optionnelle. Le backend accepte les 2 formats.
      const form = new FormData();
      form.append("message", bugMsg.trim());
      form.append("context_url", pathname.slice(0, 500));
      if (ua) form.append("user_agent", ua);
      if (bugPhoto) form.append("screenshot", bugPhoto);
      const res = await authedFetch("/api/v1/help/reports", {
        method: "POST",
        body: form
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
      onPickPhoto(null);
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
            <div className="grid grid-cols-3 border-b border-brand-800">
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
                Signaler
              </button>
              <button
                type="button"
                onClick={() => switchTab("mes")}
                className={`flex items-center justify-center gap-2 py-3 text-sm font-medium transition ${
                  tab === "mes"
                    ? "border-b-2 border-accent-500 text-white"
                    : "text-white/60 hover:text-white"
                }`}
              >
                <History className="h-4 w-4" />
                Mes signalements
              </button>
            </div>

            <div className="flex-1 overflow-y-auto p-4">
              {tab === "question" ? (
                <div className="space-y-3">
                  <p className="text-xs text-white/70">
                    Demande comment fonctionne quelque chose, ou si un
                    problème est déjà connu ou réglé. L&apos;assistant
                    cherche dans les signalements déjà traités et les
                    corrections livrées avant de répondre.
                  </p>
                  <textarea
                    value={question}
                    onChange={(e) => setQuestion(e.target.value)}
                    rows={4}
                    placeholder="Ex. Est-ce que le tri des numéros de chambre a été réglé ? Comment inscrire un paiement partiel ?"
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
                  {answer ? (
                    <Connaissances
                      titre="Ce que j'ai trouvé"
                      signalements={answerSig}
                      livraisons={answerLiv}
                    />
                  ) : null}
                </div>
              ) : tab === "mes" ? (
                <div className="space-y-3">
                  <p className="text-xs text-white/70">
                    Tes signalements et leur suivi : en attente, réglé ou
                    refusé, avec la note et la date de traitement.
                  </p>
                  {mesLoading && !mes ? (
                    <div className="flex justify-center py-6">
                      <Loader2 className="h-5 w-5 animate-spin text-accent-500" />
                    </div>
                  ) : null}
                  {mesError ? (
                    <p className="rounded-md border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
                      {mesError}
                    </p>
                  ) : null}
                  {mes && mes.length === 0 ? (
                    <p className="rounded-md border border-dashed border-brand-800 px-3 py-6 text-center text-xs text-white/70">
                      Aucun signalement pour l&apos;instant.
                    </p>
                  ) : null}
                  {(mes || []).map((m) => (
                    <div
                      key={m.id}
                      className="rounded-md border border-brand-800 bg-brand-900 p-3"
                    >
                      <div className="flex flex-wrap items-center gap-2">
                        <Pastille status={m.status} libelle={m.statut_libelle} />
                        <span className="text-[11px] text-white/70">
                          #{m.id}
                          {m.section ? ` · ${m.section}` : ""}
                        </span>
                      </div>
                      <p className="mt-1.5 whitespace-pre-wrap text-sm text-white/85">
                        {m.message}
                      </p>
                      {m.resolution_notes ? (
                        <p className="mt-1.5 text-xs text-white">
                          <span className="font-semibold">Note : </span>
                          {m.resolution_notes}
                        </p>
                      ) : null}
                      <p className="mt-1.5 text-[11px] text-white/70">
                        Signalé le {dateCourte(m.created_at)}
                        {m.traite_le
                          ? ` · ${m.statut_libelle} le ${dateCourte(m.traite_le)}`
                          : ""}
                      </p>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="space-y-3">
                  <p className="text-xs text-white/60">
                    Décris ce qui ne marche pas ou ce qui devrait être
                    amélioré. Steven verra la demande et tu seras avisé
                    quand elle sera réglée ou refusée (onglet
                    « Mes signalements »).
                  </p>
                  <textarea
                    value={bugMsg}
                    onChange={(e) => setBugMsg(e.target.value)}
                    rows={6}
                    placeholder="Ex. Quand je clique sur convertir un PO en achat, ça ne fait rien."
                    className="w-full rounded-md border border-brand-800 bg-brand-900 px-3 py-2 text-sm text-white placeholder:text-white/40 focus:border-accent-500 focus:outline-none"
                  />

                  <Connaissances
                    titre="Déjà signalé ou déjà réglé ?"
                    signalements={simSig}
                    livraisons={simLiv}
                  />

                  {/* Capture d'écran optionnelle. Format accepté :
                      JPEG / PNG / WebP / HEIC / GIF, max 4 MB. */}
                  <div>
                    <label className="mb-1 block text-[10px] font-semibold uppercase tracking-wider text-white/50">
                      Capture d&apos;écran (optionnel)
                    </label>
                    {bugPhotoPreview ? (
                      <div className="relative inline-block">
                        {/* eslint-disable-next-line @next/next/no-img-element */}
                        <img
                          src={bugPhotoPreview}
                          alt="aperçu"
                          className="max-h-40 rounded-md border border-brand-800 object-contain"
                        />
                        <button
                          type="button"
                          onClick={() => onPickPhoto(null)}
                          className="absolute -right-2 -top-2 rounded-full bg-rose-500 p-1 text-white shadow"
                          title="Retirer la photo"
                          aria-label="Retirer la photo"
                        >
                          <X className="h-3 w-3" />
                        </button>
                      </div>
                    ) : (
                      <label className="inline-flex cursor-pointer items-center gap-2 rounded-md border border-dashed border-brand-700 bg-brand-900 px-3 py-2 text-xs text-white/60 hover:border-accent-500 hover:text-white">
                        <input
                          type="file"
                          accept="image/*"
                          className="hidden"
                          onChange={(e) =>
                            onPickPhoto(e.target.files?.[0] ?? null)
                          }
                        />
                        + Ajouter une photo
                      </label>
                    )}
                  </div>

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
