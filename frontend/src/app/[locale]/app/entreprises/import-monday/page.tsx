"use client";

import { useState } from "react";
import {
  AlertTriangle,
  ArrowLeft,
  CheckCircle2,
  ExternalLink,
  Loader2,
  Sparkles,
  Upload
} from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { Link } from "@/i18n/navigation";
import { authedFetch } from "@/lib/auth";
import { useAppLayout } from "../../layout";

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

export default function ImportMondayPage() {
  const { onOpenSidebar } = useAppLayout();
  const [workspaces, setWorkspaces] = useState<Workspace[] | null>(null);
  const [boards, setBoards] = useState<Board[]>([]);
  const [discovering, setDiscovering] = useState(false);
  const [discoverError, setDiscoverError] = useState<string | null>(null);

  const [workspaceId, setWorkspaceId] = useState("");
  const [boardFilter, setBoardFilter] = useState("");
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
      if (workspaceId) body.workspace_id = Number(workspaceId);
      if (boardFilter.trim()) body.board_name_filter = boardFilter.trim();
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
    } catch (err) {
      setImportError((err as Error).message);
    } finally {
      setImporting(false);
    }
  }

  // Boards filtrés par workspace pour l'aperçu
  const filteredBoards = workspaceId
    ? boards.filter((b) => String(b.workspace?.id) === workspaceId)
    : boards;
  const previewBoards = boardFilter.trim()
    ? filteredBoards.filter((b) =>
        b.name.toLowerCase().includes(boardFilter.trim().toLowerCase())
      )
    : filteredBoards;

  return (
    <>
      <AppTopbar
        breadcrumbs={[
          { label: "Gestion d'entreprises", href: "/app/entreprises" },
          { label: "Import Monday" }
        ]}
        onOpenSidebar={onOpenSidebar}
      />
      <div className="p-4 lg:p-6">
        <Link
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          href={"/app/entreprises" as any}
          className="inline-flex items-center text-xs text-white/60 hover:text-violet-300"
        >
          <ArrowLeft className="mr-1 h-3.5 w-3.5" />
          Retour aux entreprises
        </Link>

        <header className="mt-4 flex items-start gap-3">
          <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-violet-500/15 text-violet-300">
            <ExternalLink className="h-5 w-5" />
          </span>
          <div>
            <h1 className="text-2xl font-bold text-white">
              Import depuis Monday
            </h1>
            <p className="mt-1 max-w-2xl text-sm text-white/60">
              Synchronisation idempotente des tableaux Monday en
              entreprises + tâches. Ré-exécutable autant de fois que
              voulu — Monday reste la source pendant la migration, h2.0
              accumule les données pour reprendre la main quand tout
              sera importé.
            </p>
          </div>
        </header>

        <div className="mt-3 inline-flex items-center gap-2 rounded-full border border-amber-500/40 bg-amber-500/10 px-3 py-1 text-[11px] font-semibold text-amber-200">
          <Sparkles className="h-3 w-3" />
          MONDAY_API_TOKEN doit être configuré côté Render
        </div>

        {/* Étape 1 : découverte */}
        <section className="mt-8 rounded-2xl border border-brand-800 bg-brand-900 p-5">
          <h2 className="text-sm font-semibold uppercase tracking-wider text-violet-300">
            1. Découvrir les workspaces et boards
          </h2>
          <p className="mt-2 text-xs text-white/60">
            Liste les workspaces et boards visibles avec ton token
            serveur. Sert à identifier l&apos;ID du workspace
            « Horizon services immobiliers ».
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
              <details className="rounded-lg border border-brand-800 bg-brand-950 p-3 text-xs">
                <summary className="cursor-pointer font-semibold text-white/80 hover:text-white">
                  {boards.length} board{boards.length > 1 ? "s" : ""} accessible
                  {boards.length > 1 ? "s" : ""}
                </summary>
                <ul className="mt-2 space-y-1">
                  {boards.map((b) => (
                    <li
                      key={b.id}
                      className="flex items-center justify-between gap-2 rounded px-2 py-1 hover:bg-brand-900"
                    >
                      <span className="truncate text-white/80">{b.name}</span>
                      <span className="flex-shrink-0 text-[10px] text-white/40">
                        {b.workspace?.name || "—"}
                      </span>
                    </li>
                  ))}
                </ul>
              </details>
            </div>
          ) : null}
        </section>

        {/* Étape 2 : import */}
        <section className="mt-6 rounded-2xl border border-brand-800 bg-brand-900 p-5">
          <h2 className="text-sm font-semibold uppercase tracking-wider text-violet-300">
            2. Lancer l&apos;import
          </h2>
          <p className="mt-2 text-xs text-white/60">
            Idempotent : ré-exécutable sans créer de doublons (clé
            unique sur Monday board id + item id).
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
                Clique l&apos;ID dans la section ci-dessus pour le
                pré-remplir.
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
                Insensible à la casse. Vide = tous les boards du
                workspace ciblé.
              </p>
            </div>
          </div>

          {workspaces && previewBoards.length > 0 ? (
            <div className="mt-4 rounded-lg border border-violet-500/30 bg-violet-500/5 p-3">
              <p className="text-[11px] font-semibold text-violet-200">
                Aperçu : {previewBoards.length} board
                {previewBoards.length > 1 ? "s" : ""} sera{previewBoards.length > 1 ? "ient" : ""}
                {" "}importé{previewBoards.length > 1 ? "s" : ""} :
              </p>
              <ul className="mt-1 space-y-0.5 pl-2 text-[11px] text-white/70">
                {previewBoards.slice(0, 8).map((b) => (
                  <li key={b.id}>· {b.name}</li>
                ))}
                {previewBoards.length > 8 ? (
                  <li className="text-white/40">
                    + {previewBoards.length - 8} autres…
                  </li>
                ) : null}
              </ul>
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
                Lancer l&apos;import
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
                href={"/app/entreprises" as any}
                className="mt-3 inline-flex items-center text-xs font-semibold text-emerald-300 hover:text-emerald-200"
              >
                Voir les entreprises importées →
              </Link>
            </div>
          ) : null}
        </section>
      </div>
    </>
  );
}
