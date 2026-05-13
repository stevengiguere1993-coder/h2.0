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
  Upload
} from "lucide-react";

import { authedFetch } from "@/lib/auth";
import { Link } from "@/i18n/navigation";
import { QGTopbar, useEntreprisesLayout } from "../../layout";

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

  const [data, setData] = useState<Rencontre | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [generatingGlobal, setGeneratingGlobal] = useState(false);
  const [newSectionTitle, setNewSectionTitle] = useState("");
  const [creatingSection, setCreatingSection] = useState(false);

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

              <div className="mt-3 space-y-3">
                {data.sections.map((s) => (
                  <SectionCard
                    key={s.id}
                    rencontreId={id}
                    section={s}
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
  onDelete
}: {
  rencontreId: number;
  section: Section;
  onChanged: (s: Section) => void;
  onDelete: () => void;
}) {
  const [title, setTitle] = useState(section.title);
  const [transcript, setTranscript] = useState(section.transcript || "");
  const [summarizing, setSummarizing] = useState(false);
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

  function toggleMic() {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const w: any = typeof window !== "undefined" ? (window as unknown) : null;
    const SR = w?.SpeechRecognition || w?.webkitSpeechRecognition;
    if (!SR) {
      alert("Dictée non supportée (Chrome/Safari).");
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
    let accumulated = transcript ? transcript + "\n\n" : "";
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
        accumulated += final;
        setTranscript(accumulated.trim());
      } else if (interim) {
        setTranscript((accumulated + interim).trim());
      }
    };
    rec.onend = () => {
      setListening(false);
      // Persiste le transcript à la fin de la dictée.
      void patchSection({ transcript });
    };
    rec.onerror = () => setListening(false);
    rec.start();
    recogRef.current = rec;
    setListening(true);
  }

  async function uploadAudio(file: File) {
    setUploading(true);
    try {
      const fd = new FormData();
      fd.append("file", file);
      const r = await authedFetch(
        `/api/v1/rencontres/${rencontreId}/sections/${section.id}/transcribe`,
        { method: "POST", body: fd }
      );
      if (!r.ok) {
        const txt = await r.text();
        alert(`Transcription échouée : ${txt.slice(0, 200)}`);
        return;
      }
      const updated = (await r.json()) as Section;
      onChanged(updated);
      setTranscript(updated.transcript || "");
    } finally {
      setUploading(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  const summary = parseSummary(section.ai_summary_json);

  return (
    <article
      className="rounded-xl border p-4"
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
                : "border-accent-500/40 bg-accent-500/10 text-accent-300 hover:bg-accent-500/20"
            }`}
          >
            <Mic className={`h-3 w-3 ${listening ? "animate-pulse" : ""}`} />
            {listening ? "Écoute…" : "Dicter"}
          </button>
          <label
            className="inline-flex cursor-pointer items-center gap-1.5 rounded-md border border-violet-500/40 bg-violet-500/10 px-2 py-1 text-[11px] font-semibold text-violet-300 hover:bg-violet-500/20"
            title="Upload MP3/M4A/WAV → transcrit via Whisper (OpenAI)"
          >
            {uploading ? (
              <Loader2 className="h-3 w-3 animate-spin" />
            ) : (
              <Upload className="h-3 w-3" />
            )}
            Upload audio
            <input
              ref={fileRef}
              type="file"
              accept="audio/*"
              className="hidden"
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) void uploadAudio(f);
              }}
            />
          </label>
        </div>
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
