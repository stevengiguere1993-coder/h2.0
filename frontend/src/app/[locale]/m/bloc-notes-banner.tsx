"use client";

/**
 * Bloc-notes (zone employés, bug 13, 2026-10-18) — compteurs partagés.
 *
 * `useBlocNotesResume` interroge GET /bloc-notes/resume (toutes les 60 s)
 * pour le badge du menu Plus et la bannière d'accueil ; `BlocNotesBanner`
 * n'apparaît que s'il y a des notes jamais ouvertes (« Nouveau »).
 */

import { useEffect, useState } from "react";
import { ChevronRight, NotebookPen } from "lucide-react";

import { Link } from "@/i18n/navigation";
import { authedFetch } from "@/lib/auth";

export type BlocNotesResume = {
  non_lues: number;
  ouvertes: number;
  peut_envoyer: boolean;
};

export function useBlocNotesResume(): BlocNotesResume | null {
  const [resume, setResume] = useState<BlocNotesResume | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function poll() {
      try {
        const res = await authedFetch("/api/v1/bloc-notes/resume");
        if (!res.ok) return;
        const body = (await res.json()) as BlocNotesResume;
        if (!cancelled) setResume(body);
      } catch {
        /* silencieux : le badge n'est qu'un confort */
      }
    }
    void poll();
    const t = setInterval(poll, 60_000);
    return () => {
      cancelled = true;
      clearInterval(t);
    };
  }, []);

  return resume;
}

export function BlocNotesBanner() {
  const resume = useBlocNotesResume();
  const n = resume?.non_lues ?? 0;
  if (n === 0) return null;
  return (
    <Link
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      href={"/m/notes" as any}
      className="flex items-center gap-3 rounded-xl border border-accent-500/40 bg-accent-500/10 px-4 py-3 text-white"
    >
      <NotebookPen className="h-5 w-5 shrink-0 text-accent-500" />
      <span className="flex-1 text-sm">
        <span className="font-semibold">
          {n === 1 ? "1 nouvelle note" : `${n} nouvelles notes`}
        </span>{" "}
        <span className="text-white/70">dans ton bloc-notes</span>
      </span>
      <ChevronRight className="h-4 w-4 shrink-0 text-white/40" />
    </Link>
  );
}
