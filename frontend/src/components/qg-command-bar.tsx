"use client";

/**
 * QG Command Bar — barre de commande conversationnelle ⌘K du volet
 * Entreprises. Pill flottante en bas de l'écran + overlay au clic /
 * raccourci. Recherche sémantique cross-entités via Gemini embeddings.
 */

import {
  useCallback,
  useEffect,
  useRef,
  useState
} from "react";
import { useRouter } from "next/navigation";
import {
  ArrowRight,
  Briefcase,
  FileText,
  Loader2,
  Search,
  Sparkles,
  X
} from "lucide-react";

import { authedFetch } from "@/lib/auth";

type Hit = {
  source_type: string;
  source_id: number;
  entreprise_id: number | null;
  entreprise_name: string | null;
  entreprise_color: string | null;
  title: string;
  snippet: string;
  similarity: number;
};

const ICONS: Record<
  string,
  React.ComponentType<{ className?: string }>
> = {
  tache: Sparkles,
  summary: FileText,
  insight: Sparkles
};

export function QGCommandBar() {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<Hit[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [activeIdx, setActiveIdx] = useState(0);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const debounceRef = useRef<number | null>(null);
  const router = useRouter();

  // Raccourci clavier ⌘K / Ctrl+K + Echap
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setOpen((v) => !v);
      } else if (e.key === "Escape" && open) {
        setOpen(false);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  // Focus l'input à l'ouverture
  useEffect(() => {
    if (open) {
      setTimeout(() => inputRef.current?.focus(), 50);
    } else {
      setQ("");
      setHits([]);
      setActiveIdx(0);
      setError(null);
    }
  }, [open]);

  // Recherche débouncée
  const runSearch = useCallback(async (query: string) => {
    if (!query.trim() || query.trim().length < 2) {
      setHits([]);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const res = await authedFetch("/api/v1/entreprises/search", {
        method: "POST",
        body: JSON.stringify({ query: query.trim(), limit: 10 })
      });
      if (!res.ok) {
        if (res.status === 503) {
          throw new Error(
            "IA indisponible (clé Gemini non configurée)."
          );
        }
        throw new Error(`HTTP ${res.status}`);
      }
      const data = (await res.json()) as Hit[];
      setHits(data);
      setActiveIdx(0);
    } catch (err) {
      setError((err as Error).message);
      setHits([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (debounceRef.current) {
      window.clearTimeout(debounceRef.current);
    }
    debounceRef.current = window.setTimeout(() => {
      void runSearch(q);
    }, 250);
    return () => {
      if (debounceRef.current) {
        window.clearTimeout(debounceRef.current);
      }
    };
  }, [q, runSearch]);

  function navigate(hit: Hit) {
    if (hit.source_type === "tache" && hit.entreprise_id) {
      router.push(`/entreprises/${hit.entreprise_id}`);
    } else if (hit.entreprise_id) {
      router.push(`/entreprises/${hit.entreprise_id}`);
    } else {
      router.push("/entreprises");
    }
    setOpen(false);
  }

  function onInputKey(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActiveIdx((i) => Math.min(i + 1, Math.max(0, hits.length - 1)));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActiveIdx((i) => Math.max(i - 1, 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      const h = hits[activeIdx];
      if (h) navigate(h);
    }
  }

  return (
    <>
      {/* Pill flottante toujours visible en bas-centre */}
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="fixed bottom-6 left-1/2 z-30 -translate-x-1/2 transform"
        aria-label="Ouvrir la barre de commande"
        title="Demander à Kratos (⌘K)"
      >
        <span
          className="flex items-center gap-2 rounded-full px-4 py-2 text-[12px] font-semibold backdrop-blur transition hover:scale-105"
          style={{
            backgroundColor: "rgba(15,15,18,0.85)",
            border: "1px solid rgba(212,255,58,0.25)",
            color: "#a0a0a8",
            boxShadow:
              "0 8px 32px -8px rgba(0,0,0,0.6), 0 0 24px -8px rgba(212,255,58,0.15)"
          }}
        >
          <Sparkles className="h-3.5 w-3.5" style={{ color: "#d4ff3a" }} />
          Demander à Kratos
          <kbd
            className="ml-2 rounded border px-1.5 py-0.5 text-[10px] font-mono"
            style={{
              borderColor: "#35353f",
              backgroundColor: "#0a0a0b",
              color: "#a0a0a8"
            }}
          >
            ⌘K
          </kbd>
        </span>
      </button>

      {open ? (
        <div
          className="fixed inset-0 z-50 flex items-start justify-center px-4 pt-[15vh]"
          style={{ backgroundColor: "rgba(0,0,0,0.7)" }}
          onClick={() => setOpen(false)}
        >
          <div
            className="w-full max-w-2xl overflow-hidden rounded-2xl"
            style={{
              backgroundColor: "#0f0f12",
              border: "1px solid #25252d",
              boxShadow: "0 32px 64px -16px rgba(0,0,0,0.8)"
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <div
              className="flex items-center gap-3 px-4 py-3"
              style={{ borderBottom: "1px solid #25252d" }}
            >
              <Search className="h-4 w-4 text-[#66666e]" />
              <input
                ref={inputRef}
                value={q}
                onChange={(e) => setQ(e.target.value)}
                onKeyDown={onInputKey}
                placeholder="Cherche une tâche, un briefing, un projet…"
                className="flex-1 bg-transparent text-[15px] text-[#f5f5f7] placeholder:text-[#66666e] focus:outline-none"
              />
              {loading ? (
                <Loader2 className="h-4 w-4 animate-spin text-[#d4ff3a]" />
              ) : null}
              <button
                type="button"
                onClick={() => setOpen(false)}
                className="rounded-md p-1 text-[#66666e] hover:bg-[#18181d] hover:text-[#f5f5f7]"
                aria-label="Fermer"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            <div className="max-h-[55vh] overflow-y-auto p-2">
              {error ? (
                <p className="m-2 rounded-md border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-[12px] text-rose-300">
                  {error}
                </p>
              ) : null}

              {!error && hits.length === 0 && q.trim().length >= 2 && !loading ? (
                <p className="px-4 py-12 text-center text-[12px] text-[#66666e]">
                  Aucun résultat. Reindex tes tâches via{" "}
                  <span
                    className="cursor-pointer underline hover:text-[#d4ff3a]"
                    onClick={() => {
                      router.push("/entreprises");
                      setOpen(false);
                    }}
                  >
                    Vue d&apos;ensemble
                  </span>{" "}
                  si tu viens de les importer.
                </p>
              ) : null}

              {!error && hits.length === 0 && q.trim().length < 2 ? (
                <div className="px-4 py-8">
                  <p className="text-[12px] uppercase tracking-wider text-[#66666e]">
                    Astuce
                  </p>
                  <p className="mt-2 text-[13px] text-[#a0a0a8]">
                    Tape une question ou des mots-clés. La recherche
                    sémantique trouve des éléments même si les mots
                    exacts ne sont pas dans la tâche.
                  </p>
                  <div className="mt-4 flex flex-wrap gap-2">
                    {[
                      "fournisseurs en retard",
                      "prochains paiements",
                      "embauche urgente",
                      "synergies entre entreprises"
                    ].map((s) => (
                      <button
                        key={s}
                        type="button"
                        onClick={() => setQ(s)}
                        className="rounded-md px-2.5 py-1 text-[11px] transition hover:text-[#d4ff3a]"
                        style={{
                          border: "1px solid #25252d",
                          backgroundColor: "#15151a",
                          color: "#a0a0a8"
                        }}
                      >
                        {s}
                      </button>
                    ))}
                  </div>
                </div>
              ) : null}

              {hits.map((h, i) => {
                const Icon = ICONS[h.source_type] || Briefcase;
                const active = i === activeIdx;
                return (
                  <button
                    key={`${h.source_type}-${h.source_id}`}
                    type="button"
                    onClick={() => navigate(h)}
                    onMouseEnter={() => setActiveIdx(i)}
                    className="flex w-full items-start gap-3 rounded-md px-3 py-2.5 text-left transition"
                    style={{
                      backgroundColor: active ? "#18181d" : "transparent"
                    }}
                  >
                    <span
                      className="mt-0.5 flex h-6 w-6 flex-shrink-0 items-center justify-center rounded"
                      style={{
                        backgroundColor:
                          (h.entreprise_color || "#d4ff3a") + "26",
                        color: h.entreprise_color || "#d4ff3a"
                      }}
                    >
                      <Icon className="h-3 w-3" />
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="flex items-center gap-2">
                        <span className="truncate text-[13px] font-semibold text-[#f5f5f7]">
                          {h.title}
                        </span>
                        {h.entreprise_name ? (
                          <span
                            className="rounded-full px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wider"
                            style={{
                              backgroundColor:
                                (h.entreprise_color || "#a0a0a8") + "1f",
                              color: h.entreprise_color || "#a0a0a8"
                            }}
                          >
                            {h.entreprise_name}
                          </span>
                        ) : null}
                      </span>
                      {h.snippet && h.snippet !== h.title ? (
                        <span className="mt-0.5 line-clamp-1 text-[11px] text-[#a0a0a8]">
                          {h.snippet}
                        </span>
                      ) : null}
                    </span>
                    <span
                      className="flex-shrink-0 self-center text-[10px] tabular-nums"
                      style={{
                        color:
                          h.similarity > 0.7
                            ? "#d4ff3a"
                            : h.similarity > 0.5
                            ? "#a0a0a8"
                            : "#66666e",
                        fontFamily: "var(--font-mono, monospace)"
                      }}
                    >
                      {(h.similarity * 100).toFixed(0)}%
                    </span>
                    {active ? (
                      <ArrowRight
                        className="h-3.5 w-3.5 self-center text-[#d4ff3a]"
                      />
                    ) : null}
                  </button>
                );
              })}
            </div>

            <div
              className="flex items-center justify-between px-4 py-2 text-[10px] text-[#66666e]"
              style={{
                borderTop: "1px solid #25252d",
                backgroundColor: "#0a0a0b"
              }}
            >
              <span className="flex items-center gap-3">
                <span>
                  <kbd className="rounded border border-[#35353f] px-1 py-0.5 font-mono">
                    ↑↓
                  </kbd>{" "}
                  Naviguer
                </span>
                <span>
                  <kbd className="rounded border border-[#35353f] px-1 py-0.5 font-mono">
                    ↵
                  </kbd>{" "}
                  Ouvrir
                </span>
                <span>
                  <kbd className="rounded border border-[#35353f] px-1 py-0.5 font-mono">
                    Esc
                  </kbd>{" "}
                  Fermer
                </span>
              </span>
              <span>Recherche sémantique · Gemini</span>
            </div>
          </div>
        </div>
      ) : null}
    </>
  );
}
