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
  X,
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
  section?: string | null;
  rejected_at?: string | null;
  traite_le?: string | null;
  traite_par?: string | null;
};

type Onglet = "pending" | "historique" | "all";

/** Sections proposées au traitement (saisie libre aussi possible). */
const SECTIONS = [
  "Construction",
  "Construction · Punch",
  "Construction · Projets",
  "Construction · Soumissions",
  "Construction · Facturation",
  "Construction · Achats",
  "Immobilier",
  "Immobilier · Gestion locative",
  "Entreprises",
  "Entreprises · Comptabilité",
  "Entreprises · Rencontres",
  "Entreprises · Employés",
  "Prospection",
  "Communication",
  "Développement logiciel",
  "Zone employés (mobile)",
  "Espace investisseur",
  "Paramètres"
];

function dateHeure(iso: string | null | undefined): string {
  return iso ? new Date(iso).toLocaleString("fr-CA") : "";
}

const STATUS_LABEL: Record<string, string> = {
  pending: "En attente",
  // Ancien statut : accepté = réglé (Steven, 2026-11-13).
  accepted: "Réglé",
  rejected: "Refusé",
  resolved: "Réglé"
};

const STATUS_BG: Record<string, string> = {
  pending: "bg-amber-500/15 text-amber-300 border-amber-500/30",
  accepted: "bg-emerald-500/15 text-emerald-300 border-emerald-500/30",
  rejected: "bg-rose-500/15 text-rose-300 border-rose-500/30",
  resolved: "bg-emerald-500/15 text-emerald-300 border-emerald-500/30"
};

export function HelpRequestsSection() {
  const [items, setItems] = useState<HelpReport[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<Onglet>("pending");
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

  // Historique : signalements traités (réglés ou refusés), la décision la
  // plus récente en premier.
  const filtered =
    tab === "all"
      ? items
      : tab === "historique"
        ? items
            .filter((r) => r.status !== "pending")
            .sort((a, b) =>
              (b.traite_le || b.resolved_at || b.created_at).localeCompare(
                a.traite_le || a.resolved_at || a.created_at
              )
            )
        : items.filter((r) => r.status === tab);

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

  function onUpdated(rep: HelpReport) {
    setItems((prev) => prev.map((r) => (r.id === rep.id ? rep : r)));
  }

  /** Décision sur un signalement, avec la note et la section saisies sur
   *  la carte : le déclarant reçoit la notification avec cette note. */
  async function singleAct(
    id: number,
    action: "accept" | "reject" | "resolve" | "pending",
    notes: string,
    section: string
  ) {
    setBusy(true);
    try {
      const map: Record<string, string> = {
        accept: "accepted",
        reject: "rejected",
        resolve: "resolved",
        pending: "pending"
      };
      const res = await authedFetch(`/api/v1/help/reports/${id}`, {
        method: "PATCH",
        body: JSON.stringify({
          status: map[action],
          resolution_notes: notes,
          section
        })
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      onUpdated((await res.json()) as HelpReport);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const counts = {
    pending: items.filter((r) => r.status === "pending").length,
    accepted: items.filter((r) => r.status === "accepted").length,
    historique: items.filter((r) => r.status !== "pending").length,
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
            {counts.historique} traités)
          </h2>
          <p className="mt-0.5 text-xs text-white/60">
            Bugs signalés via le bouton « Aide ». Chaque décision (réglé ou
            refusé) avise le déclarant avec ta note. Les bugs réglés
            nourrissent l&apos;onglet « Question » : l&apos;assistant les cite
            quand quelqu&apos;un repose la même question.
          </p>
        </div>
        <CopyAllButton reports={filtered} />
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
        {(["pending", "historique", "all"] as const).map((t) => (
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
              : t === "historique"
                  ? `Historique (${counts.historique})`
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
            onClick={() => bulkAct("reject")}
            className="inline-flex items-center gap-1 rounded-md bg-rose-500/15 px-2.5 py-1 text-rose-300 hover:bg-rose-500/25 disabled:opacity-50"
          >
            <XCircle className="h-3.5 w-3.5" />
            Refuser
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={() => bulkAct("resolve")}
            className="inline-flex items-center gap-1 rounded-md bg-emerald-500/15 px-2.5 py-1 text-emerald-300 hover:bg-emerald-500/25 disabled:opacity-50"
          >
            <CheckCircle2 className="h-3.5 w-3.5" />
            Marquer réglés
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
          {filtered.map((r) => (
            <ReportCard
              key={r.id}
              report={r}
              checked={selected.has(r.id)}
              onToggle={() => toggle(r.id)}
              busy={busy}
              onAct={(action, notes, section) =>
                singleAct(r.id, action, notes, section)
              }
              onUpdated={onUpdated}
            />
          ))}
        </div>
      )}
    </section>
  );
}

/** Carte d'un signalement : note et section saisies AVANT la décision
 *  (le déclarant reçoit la note dans sa notification), dates
 *  d'historique, actions. */
function ReportCard({
  report: r,
  checked,
  onToggle,
  busy,
  onAct,
  onUpdated
}: {
  report: HelpReport;
  checked: boolean;
  onToggle: () => void;
  busy: boolean;
  onAct: (
    action: "accept" | "reject" | "resolve" | "pending",
    notes: string,
    section: string
  ) => void;
  onUpdated: (rep: HelpReport) => void;
}) {
  const [notes, setNotes] = useState(r.resolution_notes || "");
  const [section, setSection] = useState(r.section || "");
  const [saving, setSaving] = useState(false);
  const [savedFlash, setSavedFlash] = useState(false);

  // Rechargement de la liste : on reprend les valeurs du serveur.
  useEffect(() => {
    setNotes(r.resolution_notes || "");
    setSection(r.section || "");
  }, [r.resolution_notes, r.section]);

  const dirty =
    (notes.trim() || null) !== (r.resolution_notes?.trim() || null) ||
    (section.trim() || null) !== (r.section?.trim() || null);

  async function enregistrer() {
    setSaving(true);
    try {
      const res = await authedFetch(`/api/v1/help/reports/${r.id}`, {
        method: "PATCH",
        body: JSON.stringify({ resolution_notes: notes, section })
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      onUpdated((await res.json()) as HelpReport);
      setSavedFlash(true);
      setTimeout(() => setSavedFlash(false), 1500);
    } catch {
      /* silencieux : le bouton reste affiché */
    } finally {
      setSaving(false);
    }
  }

  const decision =
    r.status === "resolved"
      ? `Réglé le ${dateHeure(r.traite_le || r.resolved_at)}`
      : r.status === "rejected"
        ? `Refusé le ${dateHeure(r.traite_le || r.rejected_at)}`
        : r.status === "accepted"
          ? `Réglé le ${dateHeure(r.traite_le || r.accepted_at)}`
          : null;

  const listeId = `sections-bug-${r.id}`;

  return (
    <div
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
          onChange={onToggle}
          className="mt-1 rounded border-brand-700 bg-brand-900"
        />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span
              className={`rounded-full border px-2 py-0.5 text-[11px] font-semibold ${
                STATUS_BG[r.status] ||
                "border-white/20 bg-white/10 text-white/70"
              }`}
            >
              {STATUS_LABEL[r.status] || r.status}
            </span>
            <span className="text-[11px] text-white/70">
              #{r.id} · {r.user_email || "(anonyme)"} · {dateHeure(r.created_at)}
            </span>
          </div>
          <p className="mt-1.5 whitespace-pre-wrap text-sm text-white/85">
            {r.message}
          </p>
          {r.context_url ? (
            <p className="mt-1 text-[11px] text-white/70">
              URL : <span className="font-mono">{r.context_url}</span>
            </p>
          ) : null}
          {decision ? (
            <p className="mt-1 text-[11px] font-semibold text-white">
              {decision}
              {r.traite_par ? ` par ${r.traite_par}` : ""}
            </p>
          ) : null}
          {r.has_screenshot ? <ScreenshotThumb reportId={r.id} /> : null}

          <div className="mt-2 grid gap-2 rounded-md border border-brand-800 bg-brand-950/40 p-2">
            <label className="block">
              <span className="text-[11px] font-semibold uppercase tracking-wider text-white/70">
                Section
              </span>
              <input
                list={listeId}
                value={section}
                onChange={(e) => setSection(e.target.value)}
                maxLength={64}
                placeholder="Ex. Immobilier · Gestion locative"
                className="mt-1 w-full rounded-md border border-brand-800 bg-brand-900 px-2 py-1.5 text-xs text-white placeholder:text-white/40 focus:border-accent-500 focus:outline-none"
              />
              <datalist id={listeId}>
                {SECTIONS.map((s) => (
                  <option key={s} value={s} />
                ))}
              </datalist>
            </label>
            <label className="block">
              <span className="text-[11px] font-semibold uppercase tracking-wider text-white/70">
                Note pour le déclarant et l&apos;historique
              </span>
              <textarea
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                rows={2}
                placeholder="Ce qui causait le bug, ce qui a été corrigé, ou pourquoi c'est refusé…"
                className="mt-1 w-full rounded-md border border-brand-800 bg-brand-900 px-2 py-1.5 text-xs text-white placeholder:text-white/40 focus:border-accent-500 focus:outline-none"
              />
            </label>
            {dirty || savedFlash ? (
              <div className="flex items-center gap-2">
                {dirty ? (
                  <button
                    type="button"
                    onClick={enregistrer}
                    disabled={saving}
                    className="rounded border border-accent-500/40 bg-accent-500/10 px-2 py-0.5 text-[11px] font-semibold text-accent-500 hover:bg-accent-500/20 disabled:opacity-50"
                  >
                    {saving ? "Enregistrement…" : "Enregistrer sans changer le statut"}
                  </button>
                ) : null}
                {savedFlash ? (
                  <span className="text-[11px] text-emerald-300">Enregistré ✓</span>
                ) : null}
              </div>
            ) : null}
          </div>

          <div className="mt-2 flex flex-wrap gap-2">
            <CopyReportButton report={r} />
            {r.status === "pending" ? (
              <>
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => onAct("reject", notes, section)}
                  className="inline-flex items-center gap-1 rounded-md border border-rose-500/40 bg-rose-500/10 px-2.5 py-1 text-[11px] text-rose-300 hover:bg-rose-500/20 disabled:opacity-50"
                >
                  <XCircle className="h-3 w-3" />
                  Refuser
                </button>
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => onAct("resolve", notes, section)}
                  className="inline-flex items-center gap-1 rounded-md border border-emerald-500/40 bg-emerald-500/10 px-2.5 py-1 text-[11px] text-emerald-300 hover:bg-emerald-500/20 disabled:opacity-50"
                >
                  <CheckCircle2 className="h-3 w-3" />
                  Marquer réglé
                </button>
              </>
            ) : null}
            {r.status !== "pending" ? (
              <button
                type="button"
                disabled={busy}
                onClick={() => onAct("pending", notes, section)}
                className="inline-flex items-center gap-1 rounded-md border border-white/20 bg-brand-950 px-2.5 py-1 text-[11px] text-white/85 hover:border-accent-500/50 disabled:opacity-50"
              >
                Remettre en attente
              </button>
            ) : null}
          </div>
        </div>
      </div>
    </div>
  );
}

/** Charge la capture jointe via authedFetch (l'endpoint exige le Bearer
 * token, donc un <img src=URL> direct renverrait 401 / image cassée) et
 * l'affiche via un object URL. Clic = aperçu plein écran en modale. */
function ScreenshotThumb({ reportId }: { reportId: number }) {
  const [url, setUrl] = useState<string | null>(null);
  const [err, setErr] = useState(false);
  const [open, setOpen] = useState(false);

  // Échap ferme l'aperçu.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  useEffect(() => {
    let cancelled = false;
    let objUrl: string | null = null;
    (async () => {
      try {
        const res = await authedFetch(
          `/api/v1/help/reports/${reportId}/screenshot`
        );
        if (!res.ok) throw new Error();
        const blob = await res.blob();
        objUrl = URL.createObjectURL(blob);
        if (cancelled) {
          URL.revokeObjectURL(objUrl);
          return;
        }
        setUrl(objUrl);
      } catch {
        if (!cancelled) setErr(true);
      }
    })();
    return () => {
      cancelled = true;
      if (objUrl) URL.revokeObjectURL(objUrl);
    };
  }, [reportId]);

  if (err) {
    return (
      <p className="mt-2 text-[11px] text-rose-300">
        Impossible de charger la capture.
      </p>
    );
  }
  if (!url) {
    return (
      <p className="mt-2 text-[11px] text-white/40">
        Chargement de la capture…
      </p>
    );
  }
  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="mt-2 inline-block rounded-md focus:outline-none focus-visible:ring-2 focus-visible:ring-accent-500"
        title="Agrandir la capture"
        aria-label="Agrandir la capture"
      >
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={url}
          alt="Capture jointe"
          className="max-h-48 cursor-zoom-in rounded-md border border-brand-800 object-contain"
        />
      </button>
      {open ? (
        // Aperçu en fenêtre modale (Phil 2026-10-03) : pas de nouvelle
        // page, un X (ou Échap / clic à côté) pour fermer.
        <div
          className="fixed inset-0 z-[100] flex items-center justify-center bg-black/85 p-4"
          onClick={() => setOpen(false)}
          role="dialog"
          aria-modal="true"
          aria-label="Capture d'écran"
        >
          <button
            type="button"
            onClick={() => setOpen(false)}
            className="absolute right-4 top-4 rounded-full bg-white/90 p-2 text-slate-900 hover:bg-white"
            aria-label="Fermer"
            title="Fermer"
          >
            <X className="h-5 w-5" />
          </button>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={url}
            alt="Capture jointe"
            onClick={(e) => e.stopPropagation()}
            className="max-h-[92vh] max-w-[96vw] rounded-lg object-contain shadow-2xl"
          />
        </div>
      ) : null}
    </>
  );
}

/** Formate un signalement en texte prêt à coller à Claude. */
function formatReport(report: HelpReport): string {
  const date = new Date(report.created_at).toLocaleString("fr-CA");
  const lines: string[] = [
    `Bug signalé par ${report.user_email || "(anonyme)"} le ${date}`
  ];
  if (report.context_url) lines.push(`URL : ${report.context_url}`);
  if (report.has_screenshot) lines.push("(capture d'écran jointe)");
  lines.push("", report.message.trim());
  return lines.join("\n");
}

/** Copie du texte dans le presse-papier (avec fallback execCommand). */
async function copyToClipboard(text: string): Promise<void> {
  if (typeof navigator !== "undefined" && navigator.clipboard) {
    await navigator.clipboard.writeText(text);
    return;
  }
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

/** Bouton « Tout copier » : copie d'un coup TOUS les signalements
 * affichés, formatés et séparés, pour les coller en bloc à Claude. */
function CopyAllButton({ reports }: { reports: HelpReport[] }) {
  const [copied, setCopied] = useState(false);

  async function handleCopy() {
    if (reports.length === 0) return;
    const header =
      `${reports.length} bug${reports.length > 1 ? "s" : ""} à corriger ` +
      `(copiés le ${new Date().toLocaleString("fr-CA")}) :`;
    const blocks = reports.map(
      (r, i) => `### Bug ${i + 1}/${reports.length}\n${formatReport(r)}`
    );
    const text = [header, "", blocks.join("\n\n---\n\n")].join("\n");
    try {
      await copyToClipboard(text);
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
      disabled={reports.length === 0}
      className={`inline-flex items-center gap-1.5 rounded-md border px-3 py-2 text-xs font-semibold transition disabled:opacity-40 ${
        copied
          ? "border-emerald-500/50 bg-emerald-500/15 text-emerald-300"
          : "border-accent-500/40 bg-accent-500/10 text-accent-500 hover:bg-accent-500/20"
      }`}
      title="Copier tous les bugs affichés pour les coller à Claude"
    >
      {copied ? (
        <>
          <Check className="h-3.5 w-3.5" />
          Copié
        </>
      ) : (
        <>
          <Copy className="h-3.5 w-3.5" />
          Tout copier ({reports.length})
        </>
      )}
    </button>
  );
}

/** Bouton qui copie une demande formatée pour la coller à Claude. */
function CopyReportButton({ report }: { report: HelpReport }) {
  const [copied, setCopied] = useState(false);

  function buildText(): string {
    return formatReport(report);
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
