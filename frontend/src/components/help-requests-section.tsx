"use client";

import { useCallback, useEffect, useState } from "react";
import {
  Check,
  CheckCircle2,
  CheckSquare,
  Copy,
  HelpCircle,
  Loader2,
  RefreshCw,
  XCircle
} from "lucide-react";

import { authedFetch } from "@/lib/auth";

/**
 * Section « Demandes d'aide » — bugs signalés via le bouton Aide.
 * Visible uniquement par l'owner (à gérer côté caller via isOwner).
 */
type HelpReport = {
  id: number;
  user_email: string | null;
  kind: string;
  status: string;
  message: string;
  context_url: string | null;
  user_agent: string | null;
  created_at: string;
  accepted_at: string | null;
  resolved_at: string | null;
  has_screenshot?: boolean;
  resolution_notes?: string | null;
};

const STATUS_LABEL: Record<string, string> = {
  pending: "En attente",
  accepted: "Accepté",
  rejected: "Rejeté",
  resolved: "Résolu"
};

const STATUS_BG: Record<string, string> = {
  pending: "bg-amber-500/15 text-amber-300 border-amber-500/30",
  accepted: "bg-blue-500/15 text-blue-300 border-blue-500/30",
  rejected: "bg-rose-500/15 text-rose-300 border-rose-500/30",
  resolved: "bg-emerald-500/15 text-emerald-300 border-emerald-500/30"
};

export function HelpRequestsSection() {
  const [items, setItems] = useState<HelpReport[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<"pending" | "accepted" | "all">("pending");
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await authedFetch("/api/v1/help/reports");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setItems((await res.json()) as HelpReport[]);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const filtered =
    tab === "all" ? items : items.filter((r) => r.status === tab);

  function toggle(id: number) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function toggleAll() {
    if (selected.size === filtered.length) {
      setSelected(new Set());
    } else {
      setSelected(new Set(filtered.map((r) => r.id)));
    }
  }

  async function bulkAct(action: "accept" | "reject" | "resolve") {
    if (selected.size === 0) return;
    setBusy(true);
    try {
      const res = await authedFetch("/api/v1/help/reports/bulk", {
        method: "POST",
        body: JSON.stringify({ ids: Array.from(selected), action })
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setSelected(new Set());
      await load();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  function onNotesUpdated(reportId: number, notes: string) {
    // Mise à jour locale après save d'une note de résolution.
    setItems((prev) =>
      prev.map((r) =>
        r.id === reportId ? { ...r, resolution_notes: notes || null } : r
      )
    );
  }

  async function singleAct(
    id: number,
    action: "accept" | "reject" | "resolve"
  ) {
    setBusy(true);
    try {
      const map: Record<string, string> = {
        accept: "accepted",
        reject: "rejected",
        resolve: "resolved"
      };
      const res = await authedFetch(`/api/v1/help/reports/${id}`, {
        method: "PATCH",
        body: JSON.stringify({ status: map[action] })
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      await load();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const counts = {
    pending: items.filter((r) => r.status === "pending").length,
    accepted: items.filter((r) => r.status === "accepted").length,
    all: items.length
  };

  return (
    <section className="mt-6 rounded-2xl border border-brand-800 bg-brand-900 p-5">
      <header className="flex items-center gap-3">
        <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-accent-500/15 text-accent-500">
          <HelpCircle className="h-5 w-5" />
        </span>
        <div className="min-w-0 flex-1">
          <h2 className="text-base font-bold text-white">
            Demandes d&apos;aide ({counts.pending} en attente,{" "}
            {counts.accepted} acceptés)
          </h2>
          <p className="mt-0.5 text-xs text-white/60">
            Bugs signalés via le bouton « Aide ». Quand tu reviens parler
            à Claude, dis « regarde les bugs acceptés » et il les traite.
          </p>
        </div>
        <button
          type="button"
          onClick={load}
          className="rounded-md p-2 text-white/60 hover:bg-brand-800 hover:text-white"
          title="Rafraîchir"
        >
          <RefreshCw className="h-4 w-4" />
        </button>
      </header>

      {error ? (
        <p className="mt-3 rounded-md border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
          {error}
        </p>
      ) : null}

      <div className="mt-4 flex gap-2 border-b border-brand-800">
        {(["pending", "accepted", "all"] as const).map((t) => (
          <button
            key={t}
            type="button"
            onClick={() => {
              setTab(t);
              setSelected(new Set());
            }}
            className={`px-3 py-2 text-sm transition ${
              tab === t
                ? "border-b-2 border-accent-500 text-white"
                : "text-white/60 hover:text-white"
            }`}
          >
            {t === "pending"
              ? `En attente (${counts.pending})`
              : t === "accepted"
                ? `Acceptés (${counts.accepted})`
                : `Tous (${counts.all})`}
          </button>
        ))}
      </div>

      {selected.size > 0 ? (
        <div className="mt-3 flex flex-wrap items-center gap-2 rounded-md border border-accent-500/30 bg-accent-500/5 px-3 py-2 text-xs">
          <span className="text-white/70">
            {selected.size} sélectionné{selected.size > 1 ? "s" : ""}
          </span>
          <button
            type="button"
            disabled={busy}
            onClick={() => bulkAct("accept")}
            className="inline-flex items-center gap-1 rounded-md bg-blue-500/15 px-2.5 py-1 text-blue-300 hover:bg-blue-500/25 disabled:opacity-50"
          >
            <CheckSquare className="h-3.5 w-3.5" />
            Accepter
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={() => bulkAct("reject")}
            className="inline-flex items-center gap-1 rounded-md bg-rose-500/15 px-2.5 py-1 text-rose-300 hover:bg-rose-500/25 disabled:opacity-50"
          >
            <XCircle className="h-3.5 w-3.5" />
            Rejeter
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={() => bulkAct("resolve")}
            className="inline-flex items-center gap-1 rounded-md bg-emerald-500/15 px-2.5 py-1 text-emerald-300 hover:bg-emerald-500/25 disabled:opacity-50"
          >
            <CheckCircle2 className="h-3.5 w-3.5" />
            Marquer résolus
          </button>
        </div>
      ) : null}

      {loading ? (
        <div className="mt-4 flex items-center justify-center py-6">
          <Loader2 className="h-5 w-5 animate-spin text-accent-500" />
        </div>
      ) : filtered.length === 0 ? (
        <p className="mt-4 rounded-md border border-dashed border-brand-800 bg-brand-950/40 px-4 py-6 text-center text-xs text-white/50">
          Aucune demande dans cette catégorie.
        </p>
      ) : (
        <div className="mt-3 space-y-2">
          <label className="flex items-center gap-2 px-1 text-[11px] text-white/50">
            <input
              type="checkbox"
              checked={
                filtered.length > 0 && selected.size === filtered.length
              }
              onChange={toggleAll}
              className="rounded border-brand-700 bg-brand-900"
            />
            Tout sélectionner ({filtered.length})
          </label>
          {filtered.map((r) => {
            const checked = selected.has(r.id);
            return (
              <div
                key={r.id}
                className={`rounded-lg border p-3 ${
                  checked
                    ? "border-accent-500/50 bg-accent-500/5"
                    : "border-brand-800 bg-brand-950/30"
                }`}
              >
                <div className="flex items-start gap-3">
                  <input
                    type="checkbox"
                    checked={checked}
                    onChange={() => toggle(r.id)}
                    className="mt-1 rounded border-brand-700 bg-brand-900"
                  />
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span
                        className={`rounded-full border px-2 py-0.5 text-[10px] font-semibold ${
                          STATUS_BG[r.status] ||
                          "border-white/20 bg-white/10 text-white/70"
                        }`}
                      >
                        {STATUS_LABEL[r.status] || r.status}
                      </span>
                      <span className="text-[11px] text-white/50">
                        {r.user_email || "(anonyme)"} ·{" "}
                        {new Date(r.created_at).toLocaleString("fr-CA")}
                      </span>
                    </div>
                    <p className="mt-1.5 whitespace-pre-wrap text-sm text-white/85">
                      {r.message}
                    </p>
                    {r.context_url ? (
                      <p className="mt-1 text-[11px] text-white/40">
                        URL :{" "}
                        <span className="font-mono">{r.context_url}</span>
                      </p>
                    ) : null}
                    {r.has_screenshot ? (
                      <a
                        href={`/api/v1/help/reports/${r.id}/screenshot`}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="mt-2 inline-block"
                      >
                        {/* eslint-disable-next-line @next/next/no-img-element */}
                        <img
                          src={`/api/v1/help/reports/${r.id}/screenshot`}
                          alt="Capture jointe"
                          className="max-h-48 rounded-md border border-brand-800 object-contain"
                        />
                      </a>
                    ) : null}
                    <ResolutionNoteEditor
                      reportId={r.id}
                      initial={r.resolution_notes || ""}
                      onSaved={(notes) => onNotesUpdated(r.id, notes)}
                    />
                    <div className="mt-2 flex flex-wrap gap-2">
                      <CopyReportButton report={r} />
                      {r.status === "pending" ? (
                        <>
                          <button
                            type="button"
                            disabled={busy}
                            onClick={() => singleAct(r.id, "accept")}
                            className="inline-flex items-center gap-1 rounded-md border border-blue-500/40 bg-blue-500/10 px-2.5 py-1 text-[11px] text-blue-300 hover:bg-blue-500/20 disabled:opacity-50"
                          >
                            <CheckSquare className="h-3 w-3" />
                            Accepter
                          </button>
                          <button
                            type="button"
                            disabled={busy}
                            onClick={() => singleAct(r.id, "reject")}
                            className="inline-flex items-center gap-1 rounded-md border border-rose-500/40 bg-rose-500/10 px-2.5 py-1 text-[11px] text-rose-300 hover:bg-rose-500/20 disabled:opacity-50"
                          >
                            <XCircle className="h-3 w-3" />
                            Rejeter
                          </button>
                        </>
                      ) : null}
                      {r.status === "accepted" ? (
                        <button
                          type="button"
                          disabled={busy}
                          onClick={() => singleAct(r.id, "resolve")}
                          className="inline-flex items-center gap-1 rounded-md border border-emerald-500/40 bg-emerald-500/10 px-2.5 py-1 text-[11px] text-emerald-300 hover:bg-emerald-500/20 disabled:opacity-50"
                        >
                          <CheckCircle2 className="h-3 w-3" />
                          Marquer résolu
                        </button>
                      ) : null}
                    </div>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}

/** Bouton qui copie une demande formatée pour la coller à Claude. */
function CopyReportButton({ report }: { report: HelpReport }) {
  const [copied, setCopied] = useState(false);

  function buildText(): string {
    const date = new Date(report.created_at).toLocaleString("fr-CA");
    const lines: string[] = [
      `Bug signalé par ${report.user_email || "(anonyme)"} le ${date}`
    ];
    if (report.context_url) lines.push(`URL : ${report.context_url}`);
    lines.push("", report.message.trim());
    return lines.join("\n");
  }

  async function handleCopy() {
    const text = buildText();
    try {
      if (typeof navigator !== "undefined" && navigator.clipboard) {
        await navigator.clipboard.writeText(text);
      } else {
        // Fallback : textarea + execCommand pour navigateurs anciens.
        const ta = document.createElement("textarea");
        ta.value = text;
        ta.style.position = "fixed";
        ta.style.opacity = "0";
        document.body.appendChild(ta);
        ta.focus();
        ta.select();
        document.execCommand("copy");
        document.body.removeChild(ta);
      }
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* silent */
    }
  }

  return (
    <button
      type="button"
      onClick={handleCopy}
      className={`inline-flex items-center gap-1 rounded-md border px-2.5 py-1 text-[11px] transition ${
        copied
          ? "border-emerald-500/50 bg-emerald-500/15 text-emerald-300"
          : "border-white/15 bg-brand-950 text-white/80 hover:border-accent-500/50 hover:text-accent-500"
      }`}
      title="Copier la demande pour la coller à Claude"
    >
      {copied ? (
        <>
          <Check className="h-3 w-3" />
          Copié
        </>
      ) : (
        <>
          <Copy className="h-3 w-3" />
          Copier
        </>
      )}
    </button>
  );
}

// ─── Notes de résolution (admin) ──────────────────────────────────
//
// Permet à Steven (ou tout owner) d'écrire ce qui causait le bug
// et ce qu'on a fait pour régler. Devient une référence pour la
// base de connaissances et pour Claude à la prochaine occurrence.

function ResolutionNoteEditor({
  reportId,
  initial,
  onSaved
}: {
  reportId: number;
  initial: string;
  onSaved: (notes: string) => void;
}) {
  const [val, setVal] = useState(initial);
  const [saving, setSaving] = useState(false);
  const [savedFlash, setSavedFlash] = useState(false);

  const dirty = (val.trim() || null) !== (initial.trim() || null);

  async function save() {
    setSaving(true);
    try {
      const r = await authedFetch(`/api/v1/help/reports/${reportId}`, {
        method: "PATCH",
        body: JSON.stringify({ resolution_notes: val })
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      onSaved(val);
      setSavedFlash(true);
      setTimeout(() => setSavedFlash(false), 1500);
    } catch {
      /* silent — l'utilisateur reverra dirty=true */
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="mt-2 rounded-md border border-brand-800 bg-brand-950/40 p-2">
      <div className="flex items-center justify-between gap-2">
        <span className="text-[10px] font-semibold uppercase tracking-wider text-white/50">
          Notes de résolution
        </span>
        {savedFlash ? (
          <span className="text-[10px] text-emerald-400">Enregistré ✓</span>
        ) : null}
      </div>
      <textarea
        value={val}
        onChange={(e) => setVal(e.target.value)}
        rows={2}
        placeholder="Ce qui causait le bug, ce qu'on a fait pour régler…"
        className="mt-1 w-full rounded-md border border-brand-800 bg-brand-900 px-2 py-1.5 text-xs text-white placeholder:text-white/30 focus:border-accent-500 focus:outline-none"
      />
      {dirty ? (
        <button
          type="button"
          onClick={save}
          disabled={saving}
          className="mt-1 rounded border border-accent-500/40 bg-accent-500/10 px-2 py-0.5 text-[10px] font-semibold text-accent-300 hover:bg-accent-500/20 disabled:opacity-50"
        >
          {saving ? "Enregistrement…" : "Enregistrer"}
        </button>
      ) : null}
    </div>
  );
}
