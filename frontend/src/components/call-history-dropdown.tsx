"use client";

// Historique d'appels — composant repliable réutilisable.
//
// Affiche, dans n'importe quelle vue (construction, prospection,
// téléphonie), un panneau replié par défaut. Ouvert au clic : champ
// de recherche + liste des appels matchant. Source unique de vérité
// = `voice_calls` (volet téléphonie). Le composant n'enregistre rien
// par lui-même ; il LIT le journal centralisé.
//
// Cliquer un appel ouvre le détail dans /telephonie?call={id}. Le
// parent peut surcharger ce comportement via `onSelect` (par
// exemple pour ouvrir un modal sans quitter la page).

import { useEffect, useState } from "react";
import {
  ChevronDown,
  ChevronRight,
  Loader2,
  Phone,
  Search
} from "lucide-react";

import { authedFetch } from "@/lib/auth";

type Call = {
  id: number;
  from_e164: string;
  to_e164: string;
  forwarded_to_e164: string | null;
  lead_name: string | null;
  intent: string | null;
  started_at: string;
  ended_at: string | null;
  recording_url: string | null;
  verbatim_transcript: string | null;
};

type Props = {
  /** Pré-remplit le champ de recherche (ex. numéro ou nom d'un
   *  contact ouvert dans la vue parente). */
  initialQuery?: string;
  /** Titre affiché dans l'en-tête (ex. « Historique d'appels —
   *  Steven Giguère »). Par défaut « Historique d'appels ». */
  title?: string;
  /** Quand un appel est cliqué — appelé avec son id. Par défaut,
   *  on navigue vers /fr/telephonie?call={id}. */
  onSelect?: (callId: number) => void;
};

export function CallHistoryDropdown({
  initialQuery = "",
  title = "Historique d'appels",
  onSelect
}: Props) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState(initialQuery);
  const [items, setItems] = useState<Call[]>([]);
  const [loading, setLoading] = useState(false);

  // Si le parent change `initialQuery` (ex. l'utilisateur clique un
  // autre contact), on resynchronise le champ.
  useEffect(() => {
    setQuery(initialQuery);
  }, [initialQuery]);

  // Fetch quand on ouvre OU quand la query change pendant l'ouverture.
  // Debounce léger côté input (300 ms) pour pas spammer l'API.
  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setLoading(true);
    const timer = setTimeout(async () => {
      try {
        const qs = query.trim()
          ? `?q=${encodeURIComponent(query.trim())}`
          : "";
        const r = await authedFetch(`/api/v1/voice/calls/search${qs}`);
        if (cancelled) return;
        if (r.ok) {
          setItems((await r.json()) as Call[]);
        } else {
          setItems([]);
        }
      } catch {
        if (!cancelled) setItems([]);
      } finally {
        if (!cancelled) setLoading(false);
      }
    }, 300);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [open, query]);

  return (
    <div className="rounded-2xl border border-brand-800 bg-brand-900">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center justify-between gap-2 px-4 py-3 text-left"
      >
        <span className="flex items-center gap-2 text-sm font-semibold text-white">
          <Phone className="h-4 w-4 text-accent-500" />
          {title}
          {open && items.length > 0 ? (
            <span className="rounded-full bg-accent-500/20 px-2 py-0.5 text-[10px] font-medium text-accent-300">
              {items.length}
            </span>
          ) : null}
        </span>
        {open ? (
          <ChevronDown className="h-4 w-4 text-white/40" />
        ) : (
          <ChevronRight className="h-4 w-4 text-white/40" />
        )}
      </button>

      {open ? (
        <div className="space-y-2 border-t border-brand-800 p-3">
          <div className="flex items-center gap-2 rounded-md border border-brand-800 bg-brand-950 px-2 py-1.5">
            <Search className="h-3.5 w-3.5 text-white/40" />
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Nom (client / prospect / employé), ou numéro…"
              className="flex-1 bg-transparent text-xs text-white outline-none placeholder:text-white/30"
            />
          </div>

          {loading ? (
            <div className="flex items-center justify-center py-4">
              <Loader2 className="h-4 w-4 animate-spin text-white/40" />
            </div>
          ) : items.length === 0 ? (
            <p className="px-2 py-4 text-center text-xs text-white/40">
              {query.trim()
                ? "Aucun appel trouvé pour cette recherche."
                : "Aucun appel récent."}
            </p>
          ) : (
            <ul className="max-h-80 space-y-1 overflow-y-auto">
              {items.map((c) => (
                <li key={c.id}>
                  <button
                    type="button"
                    onClick={() => {
                      if (onSelect) {
                        onSelect(c.id);
                      } else if (typeof window !== "undefined") {
                        const path = window.location.pathname;
                        const locale =
                          path.startsWith("/en/") || path === "/en"
                            ? "/en"
                            : "/fr";
                        window.location.href = `${locale}/telephonie?call=${c.id}`;
                      }
                    }}
                    className="w-full rounded-md px-2 py-1.5 text-left text-xs transition hover:bg-brand-800"
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="truncate font-medium text-white">
                        {c.lead_name || c.from_e164}
                      </span>
                      <span className="shrink-0 text-[10px] text-white/40">
                        {new Date(c.started_at).toLocaleDateString(
                          "fr-CA",
                          {
                            day: "numeric",
                            month: "short",
                            hour: "2-digit",
                            minute: "2-digit"
                          }
                        )}
                      </span>
                    </div>
                    <div className="mt-0.5 flex items-center gap-2 text-[10px] text-white/50">
                      <span className="font-mono">{c.from_e164}</span>
                      {c.intent ? (
                        <>
                          <span>·</span>
                          <span>{c.intent}</span>
                        </>
                      ) : null}
                      {c.verbatim_transcript ? (
                        <>
                          <span>·</span>
                          <span className="text-accent-400">verbatim</span>
                        </>
                      ) : null}
                    </div>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      ) : null}
    </div>
  );
}
