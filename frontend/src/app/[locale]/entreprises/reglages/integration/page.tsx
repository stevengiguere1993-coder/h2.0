"use client";

import { useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  ExternalLink,
  Loader2,
  Sparkles,
  Upload
} from "lucide-react";

import { Link } from "@/i18n/navigation";
import { authedFetch } from "@/lib/auth";

type Workspace = { id: string; name: string; kind?: string };
type Board = {
  id: string;
  name: string;
  workspace?: { id: string; name: string };
};

type ImportResult = {
  boards_processed: number;
  entreprises_created: number;
  entreprises_updated: number;
  taches_created: number;
  taches_updated: number;
  errors: string[];
};

export default function ReglagesIntegrationPage() {
  const [workspaces, setWorkspaces] = useState<Workspace[] | null>(null);
  const [boards, setBoards] = useState<Board[]>([]);
  const [discovering, setDiscovering] = useState(false);
  const [discoverError, setDiscoverError] = useState<string | null>(null);

  const [workspaceId, setWorkspaceId] = useState("");
  const [boardFilter, setBoardFilter] = useState("");
  const [selectedBoardIds, setSelectedBoardIds] = useState<Set<string>>(
    new Set()
  );
  const [importing, setImporting] = useState(false);
  const [importError, setImportError] = useState<string | null>(null);
  const [result, setResult] = useState<ImportResult | null>(null);

  async function discover() {
    setDiscovering(true);
    setDiscoverError(null);
    try {
      const res = await authedFetch(
        "/api/v1/entreprises/monday-workspaces"
      );
      if (!res.ok) {
        const t = await res.text();
        throw new Error(t.slice(0, 240) || `HTTP ${res.status}`);
      }
      const data = (await res.json()) as {
        workspaces: Workspace[];
        boards: Board[];
      };
      setWorkspaces(data.workspaces || []);
      setBoards(data.boards || []);
    } catch (err) {
      setDiscoverError((err as Error).message);
    } finally {
      setDiscovering(false);
    }
  }

  async function runImport() {
    setImporting(true);
    setImportError(null);
    setResult(null);
    try {
      const body: Record<string, unknown> = {};
      if (selectedBoardIds.size > 0) {
        body.board_ids = [...selectedBoardIds];
      } else {
        if (workspaceId) body.workspace_id = Number(workspaceId);
        if (boardFilter.trim())
          body.board_name_filter = boardFilter.trim();
      }
      const res = await authedFetch(
        "/api/v1/entreprises/import-monday-tasks",
        {
          method: "POST",
          body: JSON.stringify(body)
        }
      );
      if (!res.ok) {
        const t = await res.text();
        throw new Error(t.slice(0, 240) || `HTTP ${res.status}`);
      }
      setResult((await res.json()) as ImportResult);
      setSelectedBoardIds(new Set());
    } catch (err) {
      setImportError((err as Error).message);
    } finally {
      setImporting(false);
    }
  }

  const filteredBoards = workspaceId
    ? boards.filter((b) => String(b.workspace?.id) === workspaceId)
    : boards;
  const previewBoards = boardFilter.trim()
    ? filteredBoards.filter((b) =>
        b.name.toLowerCase().includes(boardFilter.trim().toLowerCase())
      )
    : filteredBoards;

  function toggleBoard(id: string) {
    const next = new Set(selectedBoardIds);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setSelectedBoardIds(next);
  }
  function selectAllVisible() {
    setSelectedBoardIds(new Set(previewBoards.map((b) => b.id)));
  }
  function clearSelection() {
    setSelectedBoardIds(new Set());
  }

  return (
    <div className="p-4 lg:p-6">
      <header className="flex items-start gap-3">
        <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-violet-500/15 text-violet-300">
          <ExternalLink className="h-5 w-5" />
        </span>
        <div>
          <h1 className="text-2xl font-bold text-white">
            Intégration Monday.com
          </h1>
          <p className="mt-1 max-w-2xl text-sm text-white/60">
            Synchronisation idempotente des tableaux Monday en
            entreprises + tâches. Ré-exécutable autant de fois que voulu —
            Monday reste la source pendant la migration.
          </p>
        </div>
      </header>

      <div className="mt-3 inline-flex items-center gap-2 rounded-full border border-amber-500/40 bg-amber-500/10 px-3 py-1 text-[11px] font-semibold text-amber-200">
        <Sparkles className="h-3 w-3" />
        MONDAY_API_TOKEN doit être configuré côté Render
      </div>

      <section className="mt-8 rounded-2xl border border-brand-800 bg-brand-900 p-5">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-violet-300">
          1. Découvrir les workspaces et boards
        </h2>
        <p className="mt-2 text-xs text-white/60">
          Liste les workspaces et boards visibles avec ton token serveur.
        </p>
        <button
          type="button"
          onClick={discover}
          disabled={discovering}
          className="btn-secondary mt-4 inline-flex items-center text-sm disabled:opacity-60"
        >
          {discovering ? (
            <>
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              Interrogation Monday…
            </>
          ) : (
            "Lister les workspaces & boards"
          )}
        </button>
        {discoverError ? (
          <p className="mt-3 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
            <AlertTriangle className="mr-1.5 inline h-3.5 w-3.5" />
            {discoverError}
          </p>
        ) : null}

        {workspaces ? (
          <div className="mt-4 space-y-3">
            {workspaces.length === 0 ? (
              <p className="text-xs text-white/50">
                Aucun workspace visible (token possiblement limité).
              </p>
            ) : (
              <details
                open
                className="rounded-lg border border-brand-800 bg-brand-950 p-3 text-xs"
              >
                <summary className="cursor-pointer font-semibold text-white/80 hover:text-white">
                  {workspaces.length} workspace
                  {workspaces.length > 1 ? "s" : ""} visible
                  {workspaces.length > 1 ? "s" : ""}
                </summary>
                <ul className="mt-2 space-y-1">
                  {workspaces.map((w) => (
                    <li
                      key={w.id}
                      className="flex items-center justify-between gap-2 rounded px-2 py-1 hover:bg-brand-900"
                    >
                      <span className="text-white/80">{w.name}</span>
                      <button
                        type="button"
                        onClick={() => setWorkspaceId(w.id)}
                        className="font-mono text-[10px] text-violet-300 hover:text-violet-200"
                        title="Utiliser cet ID"
                      >
                        {w.id} ↑
                      </button>
                    </li>
                  ))}
                </ul>
              </details>
            )}
            <div
              className="rounded-lg border p-3 text-xs"
              style={{
                borderColor: "var(--qg-border)",
                backgroundColor: "var(--qg-bg)"
              }}
            >
              <div className="mb-2 flex items-center justify-between">
                <p
                  className="font-semibold"
                  style={{ color: "var(--qg-text)" }}
                >
                  {previewBoards.length} board
                  {previewBoards.length > 1 ? "s" : ""} — clique pour sélectionner
                </p>
                <div className="flex items-center gap-2 text-[10px]">
                  <button
                    type="button"
                    onClick={selectAllVisible}
                    className="text-violet-500 hover:text-violet-400"
                  >
                    Tout sélectionner
                  </button>
                  {selectedBoardIds.size > 0 ? (
                    <button
                      type="button"
                      onClick={clearSelection}
                      style={{ color: "var(--qg-text-muted)" }}
                    >
                      Vider ({selectedBoardIds.size})
                    </button>
                  ) : null}
                </div>
              </div>
              <ul className="max-h-72 space-y-1 overflow-y-auto pr-1">
                {previewBoards.map((b) => {
                  const checked = selectedBoardIds.has(b.id);
                  return (
                    <li
                      key={b.id}
                      onClick={() => toggleBoard(b.id)}
                      className="flex cursor-pointer items-center justify-between gap-2 rounded border px-2 py-1.5 transition"
                      style={{
                        borderColor: checked
                          ? "rgba(167,139,250,0.4)"
                          : "transparent",
                        backgroundColor: checked
                          ? "rgba(139,92,246,0.1)"
                          : "transparent"
                      }}
                    >
                      <label className="flex flex-1 cursor-pointer items-center gap-2 truncate">
                        <input
                          type="checkbox"
                          checked={checked}
                          onChange={() => toggleBoard(b.id)}
                          className="h-3.5 w-3.5 accent-violet-500"
                          onClick={(e) => e.stopPropagation()}
                        />
                        <span
                          className="truncate"
                          style={{ color: "var(--qg-text)" }}
                        >
                          {b.name}
                        </span>
                      </label>
                      <span
                        className="flex-shrink-0 text-[10px]"
                        style={{ color: "var(--qg-text-soft)" }}
                      >
                        {b.workspace?.name || "—"}
                      </span>
                    </li>
                  );
                })}
              </ul>
            </div>
          </div>
        ) : null}
      </section>

      <section className="mt-6 rounded-2xl border border-brand-800 bg-brand-900 p-5">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-violet-300">
          2. Lancer l&apos;import
        </h2>
        <p className="mt-2 text-xs text-white/60">
          Idempotent : ré-exécutable sans créer de doublons.
        </p>

        <div className="mt-4 grid gap-4 sm:grid-cols-2">
          <div>
            <label htmlFor="ws_id" className="label">
              ID du workspace
            </label>
            <input
              id="ws_id"
              value={workspaceId}
              onChange={(e) => setWorkspaceId(e.target.value)}
              placeholder="(vide = tous les workspaces)"
              className="input font-mono text-sm"
              inputMode="numeric"
            />
            <p className="mt-1 text-[10px] text-white/40">
              Visible dans l&apos;URL Monday : /workspace/123456789.
            </p>
          </div>
          <div>
            <label htmlFor="board_filter" className="label">
              Filtre sur le nom des boards
            </label>
            <input
              id="board_filter"
              value={boardFilter}
              onChange={(e) => setBoardFilter(e.target.value)}
              placeholder="ex. tâche"
              className="input"
            />
            <p className="mt-1 text-[10px] text-white/40">
              Insensible à la casse. Vide = tous les boards.
            </p>
          </div>
        </div>

        {workspaces ? (
          <div className="mt-4 rounded-lg border border-violet-500/30 bg-violet-500/5 p-3">
            {selectedBoardIds.size > 0 ? (
              <p className="text-[11px] font-semibold text-violet-200">
                <strong>{selectedBoardIds.size}</strong> board
                {selectedBoardIds.size > 1 ? "s" : ""} sélectionné
                {selectedBoardIds.size > 1 ? "s" : ""} sera
                {selectedBoardIds.size > 1 ? "ont" : ""} importé
                {selectedBoardIds.size > 1 ? "s" : ""}.
              </p>
            ) : previewBoards.length > 0 ? (
              <p className="text-[11px] text-violet-200/80">
                Aucune sélection : tous les {previewBoards.length} boards
                visibles seront importés (filtre workspace + nom appliqués).
              </p>
            ) : (
              <p className="text-[11px] text-white/50">
                Lance la découverte ci-dessus pour voir les boards disponibles.
              </p>
            )}
          </div>
        ) : null}

        <button
          type="button"
          onClick={runImport}
          disabled={importing}
          className="btn-accent mt-4 inline-flex items-center text-sm disabled:opacity-60"
        >
          {importing ? (
            <>
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              Import en cours…
            </>
          ) : (
            <>
              <Upload className="mr-2 h-4 w-4" />
              Importer
              {selectedBoardIds.size > 0
                ? ` (${selectedBoardIds.size})`
                : ""}
            </>
          )}
        </button>

        {importError ? (
          <p className="mt-3 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
            <AlertTriangle className="mr-1.5 inline h-3.5 w-3.5" />
            {importError}
          </p>
        ) : null}

        {result ? (
          <div className="mt-4 rounded-lg border border-emerald-500/40 bg-emerald-500/10 p-4 text-sm">
            <p className="flex items-center gap-2 font-bold text-emerald-300">
              <CheckCircle2 className="h-4 w-4" />
              Import terminé
            </p>
            <ul className="mt-2 space-y-0.5 text-[11px] text-emerald-100/90">
              <li>
                · {result.boards_processed} board
                {result.boards_processed > 1 ? "s" : ""} traité
                {result.boards_processed > 1 ? "s" : ""}
              </li>
              <li>
                · {result.entreprises_created} entreprise
                {result.entreprises_created > 1 ? "s" : ""} créée
                {result.entreprises_created > 1 ? "s" : ""}
                {result.entreprises_updated > 0 ? (
                  <>
                    , {result.entreprises_updated} mise
                    {result.entreprises_updated > 1 ? "s" : ""} à jour
                  </>
                ) : null}
              </li>
              <li>
                · {result.taches_created} tâche
                {result.taches_created > 1 ? "s" : ""} créée
                {result.taches_created > 1 ? "s" : ""}
                {result.taches_updated > 0 ? (
                  <>
                    , {result.taches_updated} mise
                    {result.taches_updated > 1 ? "s" : ""} à jour
                  </>
                ) : null}
              </li>
            </ul>
            {result.errors && result.errors.length > 0 ? (
              <details className="mt-2 text-[11px] text-amber-200">
                <summary className="cursor-pointer font-semibold">
                  {result.errors.length} avertissement
                  {result.errors.length > 1 ? "s" : ""}
                </summary>
                <ul className="mt-1 space-y-0.5 pl-3">
                  {result.errors.map((e, i) => (
                    <li key={i}>· {e}</li>
                  ))}
                </ul>
              </details>
            ) : null}
            <Link
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
              href={"/entreprises/reglages/entreprises" as any}
              className="mt-3 inline-flex items-center text-xs font-semibold text-emerald-300 hover:text-emerald-200"
            >
              Voir les entreprises importées →
            </Link>
          </div>
        ) : null}
      </section>
    </div>
  );
}
