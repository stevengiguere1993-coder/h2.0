"use client";

import { Fragment, useState } from "react";
import { ChevronDown, ChevronRight, Loader2, Search, Sparkles } from "lucide-react";

import { authedFetch } from "@/lib/auth";
import { Link } from "@/i18n/navigation";

/**
 * « Demander à Kratos » (2026-11-13) : une question en langage naturel
 * cherchée dans TOUTES les rencontres (résumés, décisions, actions,
 * transcripts). Kratos dit si le sujet a été discuté, où, et retrace
 * l'avancement du dossier jusqu'au dernier état connu, avec les
 * passages sources (liens vers chaque rencontre).
 */

type Extrait = {
  section: string | null;
  type: string;
  libelle: string;
  texte: string;
};

type Source = {
  rencontre_id: number;
  titre: string;
  date: string | null;
  extraits: Extrait[];
};

type Reponse = {
  question: string;
  reponse: string;
  ia: boolean;
  fournisseur: string | null;
  mots_cles: string[];
  rencontres_lues: number;
  sources: Source[];
};

const EXEMPLES = [
  "Où en est le dossier du camion ?",
  "A-t-on discuté du déneigement ?",
  "Qu'est-ce qui a été décidé pour Saint-Clément ?"
];

/** Rendu léger : **gras** et « Rencontre #12 » cliquable. */
function RichLine({ text }: { text: string }) {
  const parts = text.split(/(\*\*[^*]+\*\*|Rencontre #\d+)/g);
  return (
    <>
      {parts.map((p, i) => {
        if (p.startsWith("**") && p.endsWith("**") && p.length > 4) {
          return (
            <strong key={i} style={{ color: "var(--qg-text)" }}>
              {p.slice(2, -2)}
            </strong>
          );
        }
        const m = /^Rencontre #(\d+)$/.exec(p);
        if (m) {
          return (
            <Link
              key={i}
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
              href={`/entreprises/rencontres/${m[1]}` as any}
              className="font-semibold text-accent-500 underline-offset-2 hover:underline"
            >
              {p}
            </Link>
          );
        }
        return <Fragment key={i}>{p}</Fragment>;
      })}
    </>
  );
}

function RichText({ text }: { text: string }) {
  const lines = text.split("\n");
  return (
    <div className="space-y-1 text-sm leading-relaxed" style={{ color: "var(--qg-text)" }}>
      {lines.map((raw, i) => {
        const line = raw.replace(/^#{1,6}\s+/, "");
        if (!line.trim()) return <div key={i} className="h-1" />;
        const bullet = /^\s*([-*•]|\d+\.)\s+/.exec(line);
        if (bullet) {
          return (
            <div key={i} className="flex gap-2 pl-1">
              <span aria-hidden>•</span>
              <span>
                <RichLine text={line.slice(bullet[0].length)} />
              </span>
            </div>
          );
        }
        return (
          <p key={i} className={raw.startsWith("#") ? "font-semibold" : undefined}>
            <RichLine text={line} />
          </p>
        );
      })}
    </div>
  );
}

export function RencontresDemander({
  entrepriseId
}: {
  entrepriseId?: number | null;
}) {
  const [question, setQuestion] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [res, setRes] = useState<Reponse | null>(null);
  const [sourcesOpen, setSourcesOpen] = useState(false);

  async function ask(q: string) {
    const texte = q.trim();
    if (texte.length < 2) return;
    setQuestion(texte);
    setLoading(true);
    setError(null);
    setRes(null);
    setSourcesOpen(false);
    try {
      const r = await authedFetch("/api/v1/rencontres/demander", {
        method: "POST",
        body: JSON.stringify({
          question: texte,
          entreprise_id: entrepriseId ?? null
        })
      });
      if (!r.ok) {
        const t = await r.text();
        throw new Error(
          r.status === 403
            ? "Accès à la page Rencontres requis."
            : t.slice(0, 200) || `HTTP ${r.status}`
        );
      }
      setRes((await r.json()) as Reponse);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }

  const nbExtraits = res
    ? res.sources.reduce((n, s) => n + s.extraits.length, 0)
    : 0;

  return (
    <section
      className="mb-4 rounded-2xl border p-4"
      style={{
        borderColor: "var(--qg-border)",
        backgroundColor: "var(--qg-card-bg)"
      }}
    >
      <div className="flex items-center gap-2">
        <Sparkles className="h-4 w-4 text-accent-500" />
        <h2 className="text-base font-semibold" style={{ color: "var(--qg-text)" }}>
          Demander à Kratos
        </h2>
      </div>
      <p className="mt-1 text-sm" style={{ color: "var(--qg-text-muted)" }}>
        Pose une question : Kratos cherche dans toutes les rencontres
        {entrepriseId ? " de cette entreprise" : ""} et te dit si on en a
        discuté et où en est le dossier.
      </p>
      <form
        className="mt-3 flex flex-col gap-2 sm:flex-row"
        onSubmit={(e) => {
          e.preventDefault();
          void ask(question);
        }}
      >
        <input
          className="input flex-1 text-base"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder="ex. Où en est le dossier du camion ?"
          maxLength={2000}
          aria-label="Question sur les rencontres"
        />
        <button
          type="submit"
          disabled={loading || question.trim().length < 2}
          className="btn-accent inline-flex items-center justify-center gap-1.5 text-sm disabled:opacity-50"
        >
          {loading ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Search className="h-4 w-4" />
          )}
          {loading ? "Recherche…" : "Demander"}
        </button>
      </form>
      {!res && !loading && !error ? (
        <div className="mt-2 flex flex-wrap gap-2">
          {EXEMPLES.map((ex) => (
            <button
              key={ex}
              type="button"
              onClick={() => void ask(ex)}
              className="rounded-full border px-3 py-1 text-xs transition hover:border-accent-500"
              style={{
                borderColor: "var(--qg-border)",
                color: "var(--qg-text-muted)"
              }}
            >
              {ex}
            </button>
          ))}
        </div>
      ) : null}

      {error ? (
        <p className="mt-3 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-300">
          {error}
        </p>
      ) : null}

      {res ? (
        <div className="mt-4 space-y-3">
          <RichText text={res.reponse} />
          <p className="text-xs" style={{ color: "var(--qg-text-muted)" }}>
            {res.rencontres_lues} rencontre{res.rencontres_lues > 1 ? "s" : ""} lue
            {res.rencontres_lues > 1 ? "s" : ""}
            {res.mots_cles.length > 0 ? ` · mots cherchés : ${res.mots_cles.join(", ")}` : ""}
            {res.ia ? "" : " · réponse sans IA (recherche brute)"}
          </p>
          {res.sources.length > 0 ? (
            <div>
              <button
                type="button"
                onClick={() => setSourcesOpen((v) => !v)}
                className="inline-flex items-center gap-1 text-sm font-medium"
                style={{ color: "var(--qg-text)" }}
              >
                {sourcesOpen ? (
                  <ChevronDown className="h-4 w-4" />
                ) : (
                  <ChevronRight className="h-4 w-4" />
                )}
                Sources : {res.sources.length} rencontre
                {res.sources.length > 1 ? "s" : ""}, {nbExtraits} passage
                {nbExtraits > 1 ? "s" : ""}
              </button>
              {sourcesOpen ? (
                <ul className="mt-2 space-y-3">
                  {res.sources.map((s) => (
                    <li
                      key={s.rencontre_id}
                      className="rounded-xl border p-3"
                      style={{ borderColor: "var(--qg-border-soft)" }}
                    >
                      <Link
                        // eslint-disable-next-line @typescript-eslint/no-explicit-any
                        href={`/entreprises/rencontres/${s.rencontre_id}` as any}
                        className="text-sm font-semibold text-accent-500 hover:underline"
                      >
                        {s.titre}
                      </Link>
                      <span className="ml-2 text-xs" style={{ color: "var(--qg-text-muted)" }}>
                        {s.date || "sans date"}
                      </span>
                      <ul className="mt-2 space-y-2">
                        {s.extraits.map((ex, i) => (
                          <li key={i} className="text-sm" style={{ color: "var(--qg-text)" }}>
                            <span
                              className="mr-1 text-xs font-semibold uppercase"
                              style={{ color: "var(--qg-text-muted)" }}
                            >
                              {ex.libelle}
                              {ex.section && ex.section !== s.titre
                                ? ` · ${ex.section}`
                                : ""}
                            </span>
                            <span className="whitespace-pre-line">{ex.texte}</span>
                          </li>
                        ))}
                      </ul>
                    </li>
                  ))}
                </ul>
              ) : null}
            </div>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
