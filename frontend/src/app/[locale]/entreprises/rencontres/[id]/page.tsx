"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useParams } from "next/navigation";
import {
  ChevronLeft,
  FileAudio,
  Loader2,
  Mic,
  Plus,
  Sparkles,
  Trash2,
  Upload,
  Wand2
} from "lucide-react";

import { authedFetch } from "@/lib/auth";
import { useConfirm } from "@/components/confirm-dialog";
import { Link, useRouter } from "@/i18n/navigation";
import { QGTopbar, useEntreprisesLayout } from "../../layout";
import { EntityDriveSection } from "@/components/drive/EntityDriveSection";

/**
 * Page détail d'une rencontre. Liste les sections (= topics), permet
 * d'ajouter, éditer, transcrire un audio, résumer via Claude, et
 * générer le résumé global.
 */

type Section = {
  id: number;
  rencontre_id: number;
  position: number;
  title: string;
  transcript: string | null;
  ai_summary_json: string | null;
  created_at: string;
  updated_at: string;
};

type Rencontre = {
  id: number;
  title: string;
  meeting_date: string | null;
  location: string | null;
  attendees: string | null;
  entreprise_ids_json: string | null;
  notes: string | null;
  global_summary: string | null;
  status: string;
  created_at: string;
  updated_at: string;
  sections: Section[];
};

type SectionSummary = {
  summary?: string;
  decisions?: string[];
  action_items?: Array<{
    title: string;
    owner?: string | null;
    entreprise_hint?: string | null;
    due?: string | null;
  }>;
  open_questions?: string[];
  risks?: string[];
};

function parseSummary(json: string | null): SectionSummary | null {
  if (!json) return null;
  try {
    return JSON.parse(json) as SectionSummary;
  } catch {
    return null;
  }
}

function parseIds(json: string | null): number[] {
  if (!json) return [];
  try {
    const v = JSON.parse(json);
    return Array.isArray(v) ? v.map(Number).filter(Number.isFinite) : [];
  } catch {
    return [];
  }
}

export default function RencontreDetailPage() {
  const params = useParams<{ id: string }>();
  const id = Number(params.id);
  const { entreprises } = useEntreprisesLayout();
  const confirm = useConfirm();
  const router = useRouter();

  const [data, setData] = useState<Rencontre | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [generatingGlobal, setGeneratingGlobal] = useState(false);
  const [newSectionTitle, setNewSectionTitle] = useState("");
  const [creatingSection, setCreatingSection] = useState(false);
  const [deletingRencontre, setDeletingRencontre] = useState(false);
  // ID de la section fraîchement créée par « Lancer un enregistrement ».
  // Sert à mettre en valeur son bouton « Dicter » (pulse) pendant
  // quelques secondes — l'utilisateur doit cliquer manuellement pour
  // démarrer la dictée. NE PAS auto-déclencher : Web Speech API
  // requiert un geste utilisateur direct, perdu après un await fetch.
  const [highlightSectionId, setHighlightSectionId] = useState<number | null>(
    null
  );

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await authedFetch(`/api/v1/rencontres/${id}`);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      setData((await r.json()) as Rencontre);
    } catch (e) {
      setError(`Chargement échoué : ${(e as Error).message}`);
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    if (Number.isFinite(id)) void load();
  }, [id, load]);

  async function patchRencontre(patch: Partial<Rencontre>) {
    if (!data) return;
    setData({ ...data, ...patch });
    try {
      await authedFetch(`/api/v1/rencontres/${id}`, {
        method: "PATCH",
        body: JSON.stringify(patch)
      });
    } catch {
      /* silent */
    }
  }

  async function addSection() {
    const t = newSectionTitle.trim();
    if (!t) return;
    setCreatingSection(true);
    try {
      const r = await authedFetch(`/api/v1/rencontres/${id}/sections`, {
        method: "POST",
        body: JSON.stringify({ title: t })
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const s = (await r.json()) as Section;
      setData((d) => (d ? { ...d, sections: [...d.sections, s] } : d));
      setNewSectionTitle("");
    } finally {
      setCreatingSection(false);
    }
  }

  // Crée une nouvelle section avec un titre par défaut, scroll vers
  // elle, et met en surbrillance son bouton « Dicter » pour 6 s.
  // L'utilisateur clique ensuite sur Dicter — c'est OBLIGATOIRE pour
  // que Web Speech API démarre (le navigateur exige un geste user
  // direct, perdu si on auto-déclenche après un await réseau,
  // particulièrement sur iOS Safari et PWA qui peuvent freezer).
  async function quickStartRecording() {
    setCreatingSection(true);
    try {
      const now = new Date();
      const defaultTitle = `Enregistrement — ${now.toLocaleDateString(
        "fr-CA"
      )} ${now.toLocaleTimeString("fr-CA", {
        hour: "2-digit",
        minute: "2-digit"
      })}`;
      const r = await authedFetch(`/api/v1/rencontres/${id}/sections`, {
        method: "POST",
        body: JSON.stringify({ title: defaultTitle })
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const s = (await r.json()) as Section;
      setData((d) => (d ? { ...d, sections: [...d.sections, s] } : d));
      setHighlightSectionId(s.id);
      // Scroll vers la section fraîchement créée (laisse React monter).
      setTimeout(() => {
        const el = document.getElementById(`section-${s.id}`);
        el?.scrollIntoView({ behavior: "smooth", block: "start" });
      }, 50);
      // Retire le highlight après 6 s.
      setTimeout(() => setHighlightSectionId(null), 6000);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setCreatingSection(false);
    }
  }

  async function deleteRencontre() {
    if (!data) return;
    const ok = await confirm({
      title: `Supprimer « ${data.title} » ?`,
      description:
        "Toutes les sections, transcripts et résumés associés seront perdus. Cette action est irréversible.",
      confirmLabel: "Supprimer définitivement",
      destructive: true
    });
    if (!ok) return;
    setDeletingRencontre(true);
    try {
      const r = await authedFetch(`/api/v1/rencontres/${id}`, {
        method: "DELETE"
      });
      if (!r.ok && r.status !== 204) throw new Error(`HTTP ${r.status}`);
      router.push({
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        pathname: "/entreprises/rencontres" as any
      });
    } catch (e) {
      setError(`Suppression échouée : ${(e as Error).message}`);
      setDeletingRencontre(false);
    }
  }

  async function deleteSection(sectionId: number) {
    try {
      const r = await authedFetch(
        `/api/v1/rencontres/${id}/sections/${sectionId}`,
        { method: "DELETE" }
      );
      if (!r.ok && r.status !== 204) throw new Error();
      setData((d) =>
        d ? { ...d, sections: d.sections.filter((s) => s.id !== sectionId) } : d
      );
    } catch {
      setError("Suppression échouée.");
    }
  }

  async function generateGlobal() {
    setGeneratingGlobal(true);
    try {
      const r = await authedFetch(
        `/api/v1/rencontres/${id}/summarize`,
        { method: "POST" }
      );
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      setData((await r.json()) as Rencontre);
    } catch (e) {
      setError(`Résumé global échoué : ${(e as Error).message}`);
    } finally {
      setGeneratingGlobal(false);
    }
  }

  const entNames = data
    ? parseIds(data.entreprise_ids_json)
        .map((id) => entreprises.find((e) => e.id === id)?.name)
        .filter(Boolean)
    : [];

  return (
    <>
      <QGTopbar
        greeting={
          <span className="inline-flex items-center gap-2">
            <Link
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
              href={"/entreprises/rencontres" as any}
              className="text-[var(--qg-text-soft)] hover:text-accent-500"
            >
              <ChevronLeft className="inline-block h-4 w-4" />
            </Link>
            {data?.title || "Rencontre"}
          </span>
        }
        subtitle={
          data?.meeting_date
            ? `${data.meeting_date}${data.location ? ` · ${data.location}` : ""}`
            : undefined
        }
        rightSlot={
          data ? (
            <button
              type="button"
              onClick={() => void deleteRencontre()}
              disabled={deletingRencontre}
              className="inline-flex items-center gap-1.5 rounded-md border border-rose-500/40 bg-rose-500/10 px-2.5 py-1.5 text-xs font-semibold text-rose-300 hover:bg-rose-500/20 disabled:opacity-50"
              title="Supprimer cette rencontre"
            >
              {deletingRencontre ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Trash2 className="h-3.5 w-3.5" />
              )}
              Supprimer
            </button>
          ) : undefined
        }
      />

      <div className="p-4 lg:p-6">
        {loading ? (
          <div className="flex items-center justify-center py-12">
            <Loader2 className="h-6 w-6 animate-spin text-accent-500" />
          </div>
        ) : error ? (
          <p className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-300">
            {error}
          </p>
        ) : !data ? null : (
          <div className="space-y-5">
            <EntityDriveSection
              entityType="Rencontre"
              entityId={data.id}
              pole="Gestion d'entreprises"
              label="Rencontre"
              route="/entreprises/rencontres/[id]"
            />
            {/* Métadonnées rencontre */}
            <section
              className="rounded-xl border p-4"
              style={{
                borderColor: "var(--qg-border)",
                backgroundColor: "var(--qg-card-bg)"
              }}
            >
              <div className="grid gap-3 sm:grid-cols-2">
                <div>
                  <label className="label text-[10px] uppercase">Titre</label>
                  <input
                    className="input"
                    defaultValue={data.title}
                    onBlur={(e) =>
                      patchRencontre({ title: e.target.value.trim() })
                    }
                  />
                </div>
                <div>
                  <label className="label text-[10px] uppercase">Date</label>
                  <input
                    type="date"
                    className="input"
                    defaultValue={data.meeting_date || ""}
                    onBlur={(e) =>
                      patchRencontre({ meeting_date: e.target.value || null })
                    }
                  />
                </div>
                <div>
                  <label className="label text-[10px] uppercase">Lieu</label>
                  <input
                    className="input"
                    defaultValue={data.location || ""}
                    onBlur={(e) =>
                      patchRencontre({ location: e.target.value.trim() || null })
                    }
                  />
                </div>
                <div>
                  <label className="label text-[10px] uppercase">
                    Participants
                  </label>
                  <input
                    className="input"
                    defaultValue={data.attendees || ""}
                    onBlur={(e) =>
                      patchRencontre({ attendees: e.target.value.trim() || null })
                    }
                  />
                </div>
              </div>
              {entNames.length > 0 ? (
                <p
                  className="mt-2 text-[11px]"
                  style={{ color: "var(--qg-text-muted)" }}
                >
                  Entreprises : {entNames.join(" · ")}
                </p>
              ) : null}
            </section>

            {/* Sections */}
            <section>
              <h2
                className="text-xs font-semibold uppercase tracking-wider"
                style={{ color: "var(--qg-text-muted)" }}
              >
                Sections ({data.sections.length})
              </h2>

              {/* Lance une nouvelle section + démarre la dictée en un
                  clic — pas besoin de taper un titre d'abord. */}
              <div
                className="mt-3 rounded-2xl border p-4"
                style={{
                  borderColor: "var(--qg-border)",
                  backgroundColor: "var(--qg-card-bg)"
                }}
              >
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div className="min-w-0">
                    <p className="text-sm font-semibold text-white">
                      🎙 Lancer un enregistrement
                    </p>
                    <p
                      className="mt-0.5 text-[11px]"
                      style={{ color: "var(--qg-text-soft)" }}
                    >
                      Crée une section avec titre par défaut (date + heure,
                      modifiable). Appuie ensuite sur <strong>🎙 Dicter</strong>
                      {" "}dans la section pour démarrer l&apos;enregistrement.
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={() => void quickStartRecording()}
                    disabled={creatingSection}
                    className="btn-accent inline-flex items-center gap-2 text-sm disabled:opacity-50"
                  >
                    {creatingSection ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : (
                      <Mic className="h-4 w-4" />
                    )}
                    Lancer l&apos;enregistrement
                  </button>
                </div>
                <p
                  className="mt-2 border-t pt-2 text-[11px]"
                  style={{
                    borderColor: "var(--qg-border-soft)",
                    color: "var(--qg-text-soft)"
                  }}
                >
                  💡 Tu peux ouvrir cette rencontre sur ton téléphone
                  <em> en même temps</em> et lancer un autre enregistrement
                  en parallèle — chacun sera une section distincte,
                  fusionnée par le résumé global.
                </p>
              </div>

              <div className="mt-3 space-y-3">
                {data.sections.map((s) => (
                  <SectionCard
                    key={s.id}
                    rencontreId={id}
                    section={s}
                    highlightDictation={highlightSectionId === s.id}
                    onChanged={(updated) =>
                      setData((d) =>
                        d
                          ? {
                              ...d,
                              sections: d.sections.map((x) =>
                                x.id === updated.id ? updated : x
                              )
                            }
                          : d
                      )
                    }
                    onDelete={() => void deleteSection(s.id)}
                  />
                ))}
              </div>

              {/* Ajouter une section */}
              <div className="mt-3 flex items-center gap-2">
                <input
                  className="input flex-1"
                  placeholder="Titre du topic (ex. Stratégie financière 2026)…"
                  value={newSectionTitle}
                  onChange={(e) => setNewSectionTitle(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") void addSection();
                  }}
                />
                <button
                  type="button"
                  onClick={() => void addSection()}
                  disabled={creatingSection || !newSectionTitle.trim()}
                  className="btn-accent inline-flex items-center gap-1 text-xs disabled:opacity-50"
                >
                  {creatingSection ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <Plus className="h-3.5 w-3.5" />
                  )}
                  Ajouter une section
                </button>
              </div>
            </section>

            {/* Résumé global */}
            <section
              className="rounded-xl border p-4"
              style={{
                borderColor: "var(--qg-border)",
                backgroundColor: "var(--qg-card-bg)"
              }}
            >
              <div className="flex items-center justify-between">
                <h2
                  className="text-xs font-semibold uppercase tracking-wider"
                  style={{ color: "var(--qg-text-muted)" }}
                >
                  Résumé global
                </h2>
                <button
                  type="button"
                  onClick={() => void generateGlobal()}
                  disabled={generatingGlobal || data.sections.length === 0}
                  className="btn-accent inline-flex items-center gap-1.5 text-xs disabled:opacity-50"
                >
                  {generatingGlobal ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <Sparkles className="h-3.5 w-3.5" />
                  )}
                  {data.global_summary ? "Régénérer" : "Générer le résumé global"}
                </button>
              </div>
              {data.global_summary ? (
                <div
                  className="mt-3 whitespace-pre-wrap rounded-lg border p-3 text-sm"
                  style={{
                    borderColor: "var(--qg-border-soft)",
                    backgroundColor: "var(--qg-bg-alt, transparent)",
                    color: "var(--qg-text)"
                  }}
                >
                  {data.global_summary}
                </div>
              ) : (
                <p
                  className="mt-3 text-xs"
                  style={{ color: "var(--qg-text-muted)" }}
                >
                  Aucun résumé global pour l&apos;instant. Génère-le quand toutes
                  les sections sont résumées.
                </p>
              )}
            </section>
          </div>
        )}
      </div>
    </>
  );
}

// ─── Carte d'une section ───────────────────────────────────────

function SectionCard({
  rencontreId,
  section,
  onChanged,
  onDelete,
  highlightDictation = false
}: {
  rencontreId: number;
  section: Section;
  onChanged: (s: Section) => void;
  onDelete: () => void;
  // Met en surbrillance (pulse) le bouton Dicter pendant quelques
  // secondes — utilisé après la création via « Lancer un
  // enregistrement » pour montrer la prochaine action à l'user.
  highlightDictation?: boolean;
}) {
  const [title, setTitle] = useState(section.title);
  const [transcript, setTranscript] = useState(section.transcript || "");
  const [summarizing, setSummarizing] = useState(false);
  const [cleaning, setCleaning] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [listening, setListening] = useState(false);
  const recogRef = useRef<unknown>(null);
  const fileRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    setTitle(section.title);
    setTranscript(section.transcript || "");
  }, [section]);

  async function patchSection(patch: Partial<Section>) {
    try {
      const r = await authedFetch(
        `/api/v1/rencontres/${rencontreId}/sections/${section.id}`,
        {
          method: "PATCH",
          body: JSON.stringify(patch)
        }
      );
      if (!r.ok) return;
      onChanged((await r.json()) as Section);
    } catch {
      /* silent */
    }
  }

  async function summarize() {
    setSummarizing(true);
    try {
      const r = await authedFetch(
        `/api/v1/rencontres/${rencontreId}/sections/${section.id}/summarize`,
        { method: "POST" }
      );
      if (!r.ok) return;
      onChanged((await r.json()) as Section);
    } finally {
      setSummarizing(false);
    }
  }

  // Nettoyage du transcript brut de la dictée par Claude : corrige les
  // homophones, accents, mots mal entendus, et la ponctuation. Le
  // transcript existant est remplacé par la version corrigée.
  async function cleanRawTranscript() {
    if (!confirm(
      "Réécrire le transcript de cette section en français québécois "
      + "propre (corrige les homophones, accents, mots mal entendus) ? "
      + "Le texte actuel sera remplacé."
    )) return;
    setCleaning(true);
    try {
      // Sauve d'abord la version courante au cas où la dictée live a
      // produit du nouveau texte non encore persisté.
      if (transcript !== (section.transcript || "")) {
        await patchSection({ transcript });
      }
      const r = await authedFetch(
        `/api/v1/rencontres/${rencontreId}/sections/${section.id}/clean-transcript`,
        { method: "POST" }
      );
      if (!r.ok) return;
      const updated = (await r.json()) as Section;
      // Reflète la version nettoyée localement (et coupe la dictée
      // en cours pour éviter d'écraser la correction).
      accumulatedRef.current = updated.transcript || "";
      setTranscript(updated.transcript || "");
      onChanged(updated);
    } finally {
      setCleaning(false);
    }
  }

  // Mode dictée stable + persistant. Web Speech a tendance à s'arrêter
  // tout seul après 30-60s ou quand il n'entend rien — on relance
  // automatiquement tant que l'utilisateur n'a pas cliqué stop. On
  // auto-save toutes les 5s pour ne jamais rien perdre. Et on traite
  // les commandes vocales de ponctuation (« virgule », « point »,
  // « nouveau paragraphe ») pour une saisie naturelle.
  const wantListenRef = useRef<boolean>(false);
  const accumulatedRef = useRef<string>("");
  const autoSaveRef = useRef<number | null>(null);

  function applyVoiceCommands(text: string): string {
    // Remplace les expressions parlées par leur ponctuation.
    return text
      .replace(/\b(virgule)\b/gi, ",")
      .replace(/\b(point d'interrogation)\b/gi, "?")
      .replace(/\b(point d'exclamation)\b/gi, "!")
      .replace(/\b(deux points)\b/gi, " : ")
      .replace(/\b(point virgule)\b/gi, ";")
      .replace(/\b(point)\b/gi, ".")
      .replace(/\b(nouvelle ligne|à la ligne)\b/gi, "\n")
      .replace(/\b(nouveau paragraphe)\b/gi, "\n\n")
      .replace(/\s+([,.!?;:])/g, "$1")
      .replace(/([,.!?;:])(?=\S)/g, "$1 ");
  }

  function startRecognition() {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const w: any = typeof window !== "undefined" ? (window as unknown) : null;
    const SR = w?.SpeechRecognition || w?.webkitSpeechRecognition;
    if (!SR) return;
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const rec: any = new SR();
    rec.lang = "fr-CA";
    rec.continuous = true;
    rec.interimResults = true;
    rec.maxAlternatives = 1;
    rec.onresult = (e: {
      results: ArrayLike<{ 0: { transcript: string }; isFinal: boolean }>;
      resultIndex: number;
    }) => {
      let interim = "";
      let final = "";
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const r = e.results[i];
        if (r.isFinal) final += r[0].transcript + " ";
        else interim += r[0].transcript;
      }
      if (final) {
        accumulatedRef.current += applyVoiceCommands(final);
        setTranscript(accumulatedRef.current.trim());
      } else if (interim) {
        setTranscript(
          (accumulatedRef.current + applyVoiceCommands(interim)).trim()
        );
      }
    };
    rec.onerror = (e: { error: string }) => {
      // « no-speech » et « aborted » sont normaux — on relance.
      // Les autres (network, not-allowed) sont fatals.
      if (e.error === "not-allowed" || e.error === "service-not-allowed") {
        wantListenRef.current = false;
        setListening(false);
        alert(
          "Microphone refusé par le navigateur. Active la permission micro."
        );
      }
    };
    rec.onend = () => {
      // Si l'utilisateur n'a pas cliqué stop, on relance — Web Speech
      // a tendance à s'arrêter automatiquement après 30-60s.
      if (wantListenRef.current) {
        try {
          setTimeout(() => {
            try {
              rec.start();
            } catch {
              // Si start échoue, recrée une nouvelle instance.
              if (wantListenRef.current) startRecognition();
            }
          }, 100);
        } catch {
          /* ignore */
        }
      } else {
        setListening(false);
        // Persiste le transcript à la fin de la dictée.
        void patchSection({ transcript: accumulatedRef.current.trim() });
      }
    };
    try {
      rec.start();
      recogRef.current = rec;
    } catch {
      /* déjà actif — ignore */
    }
  }

  function toggleMic() {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const w: any = typeof window !== "undefined" ? (window as unknown) : null;
    const SR = w?.SpeechRecognition || w?.webkitSpeechRecognition;
    if (!SR) {
      alert(
        "Dictée non supportée par ce navigateur — utilise Chrome ou Safari."
      );
      return;
    }
    if (listening) {
      // Stop volontaire.
      wantListenRef.current = false;
      try {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        (recogRef.current as any)?.stop();
      } catch {
        /* ignore */
      }
      if (autoSaveRef.current) {
        window.clearInterval(autoSaveRef.current);
        autoSaveRef.current = null;
      }
      setListening(false);
      return;
    }
    // Démarre — on (re)part du transcript actuel.
    accumulatedRef.current = transcript ? transcript + " " : "";
    wantListenRef.current = true;
    setListening(true);
    startRecognition();
    // Auto-save toutes les 5s pour ne JAMAIS rien perdre, même si
    // crash / fermeture onglet.
    if (autoSaveRef.current) window.clearInterval(autoSaveRef.current);
    autoSaveRef.current = window.setInterval(() => {
      const t = accumulatedRef.current.trim();
      if (t && t !== (section.transcript || "")) {
        void patchSection({ transcript: t });
      }
    }, 5000);
  }

  // Cleanup auto-save interval au démontage.
  useEffect(() => {
    return () => {
      if (autoSaveRef.current) window.clearInterval(autoSaveRef.current);
      wantListenRef.current = false;
    };
  }, []);

  async function uploadAudio(file: File) {
    // Transcription serveur via Gemini (gratuit) — l'audio est envoyé,
    // transcrit en français québécois avec interlocuteurs, puis ajouté
    // au transcript de la section. Limite ~18 MB (≈ 30-45 min
    // compressées) ; au-delà le backend renvoie un message clair.
    setUploading(true);
    try {
      const form = new FormData();
      form.append("file", file);
      const r = await authedFetch(
        `/api/v1/rencontres/${rencontreId}/sections/${section.id}/transcribe`,
        { method: "POST", body: form }
      );
      if (!r.ok) {
        const t = await r.text();
        alert(t.slice(0, 300) || `Transcription échouée (HTTP ${r.status}).`);
        return;
      }
      const updated = (await r.json()) as Section;
      setTranscript(updated.transcript || "");
      onChanged(updated);
    } catch (e) {
      alert((e as Error).message || "Erreur réseau pendant la transcription.");
    } finally {
      setUploading(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  const summary = parseSummary(section.ai_summary_json);

  return (
    <article
      id={`section-${section.id}`}
      className="rounded-xl border p-4 scroll-mt-4"
      style={{
        borderColor: "var(--qg-border)",
        backgroundColor: "var(--qg-card-bg)"
      }}
    >
      <div className="flex items-start justify-between gap-2">
        <input
          className="input flex-1 text-base font-semibold"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          onBlur={() => {
            if (title.trim() && title !== section.title) {
              void patchSection({ title: title.trim() });
            }
          }}
        />
        <button
          type="button"
          onClick={onDelete}
          className="rounded p-1.5 text-white/40 hover:bg-rose-500/15 hover:text-rose-300"
          title="Supprimer cette section"
        >
          <Trash2 className="h-3.5 w-3.5" />
        </button>
      </div>

      <textarea
        rows={8}
        value={transcript}
        onChange={(e) => setTranscript(e.target.value)}
        onBlur={() => {
          if (transcript !== (section.transcript || "")) {
            void patchSection({ transcript });
          }
        }}
        placeholder="Tape, dicte ou uploade un audio pour générer le transcript de cette section…"
        className="input mt-3 min-h-[160px] text-sm"
      />

      <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={toggleMic}
            className={`inline-flex items-center gap-1.5 rounded-md border px-2 py-1 text-[11px] font-semibold transition ${
              listening
                ? "border-rose-500/40 bg-rose-500/15 text-rose-300"
                : highlightDictation && !listening
                  ? "border-accent-500 bg-accent-500/30 text-accent-200 ring-2 ring-accent-500/60 animate-pulse"
                  : "border-accent-500/40 bg-accent-500/10 text-accent-300 hover:bg-accent-500/20"
            }`}
          >
            <Mic className={`h-3 w-3 ${listening ? "animate-pulse" : ""}`} />
            {listening
              ? "Écoute… (clique pour arrêter)"
              : highlightDictation
                ? "👉 Clique ici pour démarrer"
                : "Dicter (mode persistant + auto-save)"}
          </button>
          <button
            type="button"
            onClick={() => fileRef.current?.click()}
            disabled={uploading}
            title="Téléverse un enregistrement (mp3, m4a, wav… max ~18 MB ≈ 30-45 min) — transcrit automatiquement en français québécois avec interlocuteurs"
            className="inline-flex items-center gap-1.5 rounded-md border border-sky-500/40 bg-sky-500/10 px-2 py-1 text-[11px] font-semibold text-sky-300 transition hover:bg-sky-500/20 disabled:opacity-50"
          >
            {uploading ? (
              <Loader2 className="h-3 w-3 animate-spin" />
            ) : (
              <FileAudio className="h-3 w-3" />
            )}
            {uploading ? "Transcription en cours…" : "Téléverser un audio"}
          </button>
          <span
            className="text-[10px]"
            style={{ color: "var(--qg-text-muted)" }}
            title="La dictée gère « point », « virgule », « nouveau paragraphe » à la voix"
          >
            astuce : dis « virgule », « point », « nouveau paragraphe »
          </span>
          <input
            ref={fileRef}
            type="file"
            accept="audio/*,video/mp4,video/webm"
            className="hidden"
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) void uploadAudio(f);
              }}
            />
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => void cleanRawTranscript()}
            disabled={cleaning || !(section.transcript || transcript)}
            title="Réécrit le transcript brut en français québécois propre (homophones, accents, mots mal entendus)"
            className="inline-flex items-center gap-1.5 rounded-md border border-violet-500/40 bg-violet-500/10 px-2 py-1 text-[11px] font-semibold text-violet-300 transition hover:bg-violet-500/20 disabled:opacity-50"
          >
            {cleaning ? (
              <Loader2 className="h-3 w-3 animate-spin" />
            ) : (
              <Wand2 className="h-3 w-3" />
            )}
            Nettoyer la dictée
          </button>
          <button
            type="button"
            onClick={() => void summarize()}
            disabled={summarizing || !(section.transcript || transcript)}
            className="btn-accent inline-flex items-center gap-1.5 text-[11px] disabled:opacity-50"
          >
            {summarizing ? (
              <Loader2 className="h-3 w-3 animate-spin" />
            ) : (
              <Sparkles className="h-3 w-3" />
            )}
            {summary ? "Re-résumer" : "Résumer cette section"}
          </button>
        </div>
      </div>

      {summary ? (
        <div
          className="mt-3 rounded-lg border p-3"
          style={{
            borderColor: "var(--qg-border-soft)",
            backgroundColor: "var(--qg-bg-alt, transparent)"
          }}
        >
          {summary.summary ? (
            <p className="text-sm whitespace-pre-wrap" style={{ color: "var(--qg-text)" }}>
              {summary.summary}
            </p>
          ) : null}
          {summary.decisions && summary.decisions.length > 0 ? (
            <div className="mt-2">
              <h5 className="text-[10px] font-semibold uppercase tracking-wider text-emerald-300">
                Décisions
              </h5>
              <ul className="mt-1 list-disc space-y-0.5 pl-5 text-[12px]" style={{ color: "var(--qg-text)" }}>
                {summary.decisions.map((d, i) => <li key={i}>{d}</li>)}
              </ul>
            </div>
          ) : null}
          {summary.action_items && summary.action_items.length > 0 ? (
            <div className="mt-2">
              <h5 className="text-[10px] font-semibold uppercase tracking-wider text-accent-500">
                Actions à faire
              </h5>
              <ul className="mt-1 space-y-1 text-[12px]" style={{ color: "var(--qg-text)" }}>
                {summary.action_items.map((a, i) => (
                  <li key={i} className="rounded-md border border-brand-800/40 p-1.5">
                    <strong>{a.title}</strong>
                    {a.owner ? <span className="text-white/60"> · {a.owner}</span> : null}
                    {a.entreprise_hint ? (
                      <span className="text-white/40"> ({a.entreprise_hint})</span>
                    ) : null}
                    {a.due ? (
                      <span className="ml-2 text-amber-300/80">{a.due}</span>
                    ) : null}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
          {summary.open_questions && summary.open_questions.length > 0 ? (
            <div className="mt-2">
              <h5 className="text-[10px] font-semibold uppercase tracking-wider text-amber-300">
                Questions en suspens
              </h5>
              <ul className="mt-1 list-disc space-y-0.5 pl-5 text-[12px]" style={{ color: "var(--qg-text)" }}>
                {summary.open_questions.map((q, i) => <li key={i}>{q}</li>)}
              </ul>
            </div>
          ) : null}
          {summary.risks && summary.risks.length > 0 ? (
            <div className="mt-2">
              <h5 className="text-[10px] font-semibold uppercase tracking-wider text-rose-300">
                Risques
              </h5>
              <ul className="mt-1 list-disc space-y-0.5 pl-5 text-[12px]" style={{ color: "var(--qg-text)" }}>
                {summary.risks.map((r, i) => <li key={i}>{r}</li>)}
              </ul>
            </div>
          ) : null}
        </div>
      ) : null}
    </article>
  );
}
