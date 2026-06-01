"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Eye,
  FileText,
  Image as ImageIcon,
  Link2,
  Loader2,
  Plus,
  Search,
  Sparkles,
  Trash2,
  Upload,
  Wand2,
  X
} from "lucide-react";

import { useSearchParams } from "next/navigation";

import { authedFetch } from "@/lib/auth";
import { useConfirm } from "@/components/confirm-dialog";
import { AppTopbar } from "@/components/app-topbar";
import {
  LeadAnalysisCard,
  type LeadAnalysisCardBadge
} from "@/components/lead-analysis-card";
import { LeadAnalysisDetailModal } from "@/components/leads/LeadAnalysisDetailModal";
import { useProspectionLayout } from "../layout";
import { useRouter } from "@/i18n/navigation";

/**
 * Page « Analyses des leads » (Prospection > Analyses des leads).
 *
 * Workflow :
 *   1. L'utilisateur colle/upload des sources (URLs Centris/DuProprio,
 *      texte SMS, photos MLS, PDF, captures d'écran).
 *   2. Clic « Extraire et créer la fiche » → Claude analyse tout et
 *      crée une (ou plusieurs) fiche(s) `LeadAnalysis` avec statut
 *      « À analyser ».
 *   3. Le kanban en bas montre les leads par colonne (À analyser,
 *      Décision en attente, Intéressant, Abandonné).
 *   4. Drag & drop entre colonnes pour reclasser.
 *   5. Boutons par carte : ouvrir fiche, supprimer (confirm),
 *      convertir en lead du Pipeline (confirm).
 *
 * Note : le modal de détail (LeadAnalysisDetailModal) a été extrait
 * dans `@/components/leads/LeadAnalysisDetailModal` pour pouvoir être
 * réutilisé depuis la page d'un Deal Pipeline.
 */

type Lead = {
  id: number;
  status: "a_analyser" | "decision_en_attente" | "interessant" | "abandonne";
  position: number;
  address: string | null;
  city: string | null;
  asking_price: number | null;
  nb_logements: number | null;
  annee_construction: number | null;
  best_refi_amount: number | null;
  best_refi_program: string | null;
  mdf_preteur_b: number | null;
  type_batiment: string | null;
  converted_to_lead_id: number | null;
  converted_to_deal_id: number | null;
  model_used: string | null;
  validation_severity: "error" | "warning" | "info" | null;
  validation_count: number;
  created_at: string;
  attachments_count: number;
};

/**
 * Mapping du champ ``model_used`` (cascade tri-couche d'extraction) vers
 * un badge visuel { label, color } cohérent avec ``LeadAnalysisCardBadge``.
 */
function extractionBadge(
  modelUsed: string | null | undefined
): LeadAnalysisCardBadge {
  const m = (modelUsed || "").toLowerCase();
  if (m.startsWith("claude")) return { label: "Claude", color: "amber" };
  if (m.includes("llama") || m.includes("groq"))
    return { label: "Groq", color: "emerald" };
  if (m.startsWith("local + gemini") || m === "local + gemini")
    return { label: "Local + Gemini", color: "blue" };
  if (m.startsWith("gemini")) return { label: "Gemini", color: "violet" };
  if (m === "local") return { label: "Parser local", color: "slate" };
  return { label: "Aucune extraction", color: "rose" };
}

type ExtractResult = {
  created: Lead[];
  warnings: string[];
  model_used: string | null;
};

const COLUMNS: Array<{
  key: Lead["status"];
  label: string;
  dot: string;
  desc: string;
}> = [
  {
    key: "a_analyser",
    label: "À analyser",
    dot: "bg-violet-400",
    desc: "Fraîchement capturés"
  },
  {
    key: "decision_en_attente",
    label: "Décision en attente",
    dot: "bg-amber-400",
    desc: "Analyse complétée, à classer"
  },
  {
    key: "interessant",
    label: "Intéressant",
    dot: "bg-emerald-400",
    desc: "À pousser plus loin"
  },
  {
    key: "abandonne",
    label: "Abandonné / Rejeté",
    dot: "bg-rose-400",
    desc: "Hors critères"
  }
];

function fmtMoney(n: number | null): string {
  if (n == null) return "—";
  const rounded = Math.round(n);
  const sign = rounded < 0 ? "-" : "";
  const abs = Math.abs(rounded).toString();
  const withSep = abs.replace(/\B(?=(\d{3})+(?!\d))/g, " ");
  return `${sign}${withSep} $`;
}

function fmtDate(iso: string): string {
  return new Date(iso).toLocaleDateString("fr-CA", {
    month: "short",
    day: "2-digit"
  });
}

export default function AnalysesLeadsPage() {
  const router = useRouter();
  const { onOpenSidebar } = useProspectionLayout();
  const confirm = useConfirm();

  // ── Capture ───────────────────────────────────────────────────
  const [urlsText, setUrlsText] = useState("");
  const [rawText, setRawText] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [extracting, setExtracting] = useState(false);
  const [extractResult, setExtractResult] = useState<{ count: number; warnings: string[] } | null>(null);
  const [extractErr, setExtractErr] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  // ── Kanban ────────────────────────────────────────────────────
  const [leads, setLeads] = useState<Lead[]>([]);
  const [loading, setLoading] = useState(false);
  const [view, setView] = useState<"kanban" | "table">("kanban");
  const [search, setSearch] = useState("");
  const [dragId, setDragId] = useState<number | null>(null);
  const [hoverCol, setHoverCol] = useState<Lead["status"] | null>(null);

  // ── Détail modal ──────────────────────────────────────────────
  const [detailId, setDetailId] = useState<number | null>(null);
  // Si le modal a été ouvert depuis la page d'un Deal (param
  // ?fromDeal={dealId}), on garde le dealId pour afficher un bouton
  // « Retour au deal » dans le header du modal — Phil reste dans le
  // contexte du Deal d'origine.
  const [backToDealId, setBackToDealId] = useState<number | null>(null);

  // Ouverture automatique du modal via ?openId={id} (lien depuis la
  // page detail d'un deal — composant LeadAnalysisSummary).
  const searchParams = useSearchParams();
  useEffect(() => {
    const raw = searchParams.get("openId");
    if (!raw) return;
    const id = Number(raw);
    if (!Number.isFinite(id) || id <= 0) return;
    setDetailId(id);
    const fromRaw = searchParams.get("fromDeal");
    if (fromRaw) {
      const fromId = Number(fromRaw);
      if (Number.isFinite(fromId) && fromId > 0) setBackToDealId(fromId);
    }
    // Nettoyage de l'URL pour eviter une re-ouverture en boucle au
    // reload / back-forward.
    if (typeof window !== "undefined") {
      const url = new URL(window.location.href);
      url.searchParams.delete("openId");
      url.searchParams.delete("fromDeal");
      window.history.replaceState(null, "", url.toString());
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Navigation « Retour au deal » : ferme le modal et pousse vers la
  // page Deal d'origine.
  const goBackToDeal = useCallback(() => {
    if (backToDealId == null) return;
    setDetailId(null);
    setBackToDealId(null);
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    router.push(`/prospection/pipeline/${backToDealId}` as any);
  }, [backToDealId, router]);

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      const r = await authedFetch("/api/v1/lead-analyses");
      if (r.ok) {
        setLeads((await r.json()) as Lead[]);
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  // Paste handler : permet de coller une image dans la zone capture.
  useEffect(() => {
    function onPaste(e: ClipboardEvent) {
      const items = e.clipboardData?.items;
      if (!items) return;
      const incoming: File[] = [];
      for (let i = 0; i < items.length; i++) {
        const it = items[i];
        if (it.kind === "file" && it.type.startsWith("image/")) {
          const f = it.getAsFile();
          if (f) incoming.push(f);
        }
      }
      if (incoming.length > 0) {
        setFiles((prev) => [...prev, ...incoming]);
      }
    }
    window.addEventListener("paste", onPaste);
    return () => window.removeEventListener("paste", onPaste);
  }, []);

  function onFilesPicked(picked: FileList | null) {
    if (!picked) return;
    const arr: File[] = [];
    for (let i = 0; i < picked.length; i++) arr.push(picked[i]);
    setFiles((prev) => [...prev, ...arr]);
  }

  function onDrop(e: React.DragEvent) {
    e.preventDefault();
    if (e.dataTransfer?.files) onFilesPicked(e.dataTransfer.files);
  }

  function removeFile(idx: number) {
    setFiles((prev) => prev.filter((_, i) => i !== idx));
  }

  async function onExtract() {
    setExtractErr(null);
    setExtractResult(null);
    const hasSource =
      urlsText.trim() || rawText.trim() || files.length > 0;
    if (!hasSource) {
      setExtractErr(
        "Colle un lien, du texte ou ajoute au moins un fichier."
      );
      return;
    }
    setExtracting(true);
    try {
      const fd = new FormData();
      if (urlsText.trim()) fd.append("urls", urlsText.trim());
      if (rawText.trim()) fd.append("text", rawText.trim());
      for (const f of files) fd.append("files", f);
      const r = await authedFetch("/api/v1/lead-analyses/extract", {
        method: "POST",
        body: fd
      });
      if (!r.ok) {
        const t = await r.text().catch(() => "");
        throw new Error(t.slice(0, 300) || `HTTP ${r.status}`);
      }
      const data = (await r.json()) as ExtractResult;
      setUrlsText("");
      setRawText("");
      setFiles([]);
      setExtractResult({ count: data.created.length, warnings: data.warnings || [] });
      await reload();
    } catch (e) {
      setExtractErr((e as Error).message);
    } finally {
      setExtracting(false);
    }
  }

  async function moveLead(id: number, newStatus: Lead["status"]) {
    const prev = leads;
    setLeads((xs) =>
      xs.map((x) => (x.id === id ? { ...x, status: newStatus } : x))
    );
    try {
      const r = await authedFetch(`/api/v1/lead-analyses/${id}`, {
        method: "PATCH",
        body: JSON.stringify({ status: newStatus })
      });
      if (!r.ok) throw new Error();
    } catch {
      setLeads(prev);
    }
  }

  async function deleteLead(id: number, label: string) {
    const ok = await confirm({
      title: `Supprimer ${label} ?`,
      description:
        "L'analyse, ses notes et les fichiers joints seront effacés.",
      confirmLabel: "Supprimer",
      destructive: true
    });
    if (!ok) return;
    setLeads((xs) => xs.filter((x) => x.id !== id));
    try {
      await authedFetch(`/api/v1/lead-analyses/${id}`, {
        method: "DELETE"
      });
    } catch {
      void reload();
    }
  }

  async function convertToLead(id: number, label: string) {
    const ok = await confirm({
      title: `Ajouter « ${label} » au Pipeline ?`,
      description:
        "Un nouveau deal sera créé dans le Pipeline. La fiche d'analyse restera accessible depuis la page du deal.",
      confirmLabel: "Ajouter au Pipeline"
    });
    if (!ok) return;
    try {
      const r = await authedFetch(
        `/api/v1/lead-analyses/${id}/convert-to-deal`,
        { method: "POST" }
      );
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const j = (await r.json()) as { deal_id: number };
      void reload();
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      router.push(`/prospection/pipeline/${j.deal_id}` as any);
    } catch (e) {
      setExtractErr((e as Error).message);
    }
  }

  // Filtrage : on masque les fiches deja converties en deal (elles
  // vivent uniquement dans le Pipeline) puis on applique la recherche.
  const filtered = useMemo(() => {
    const visible = leads.filter((l) => l.converted_to_deal_id == null);
    const q = search.trim().toLowerCase();
    if (!q) return visible;
    return visible.filter((l) => {
      return (
        (l.address || "").toLowerCase().includes(q) ||
        (l.city || "").toLowerCase().includes(q) ||
        (l.type_batiment || "").toLowerCase().includes(q)
      );
    });
  }, [leads, search]);

  const byStatus = useMemo(() => {
    const m: Record<Lead["status"], Lead[]> = {
      a_analyser: [],
      decision_en_attente: [],
      interessant: [],
      abandonne: []
    };
    for (const l of filtered) m[l.status]?.push(l);
    return m;
  }, [filtered]);

  return (
    <>
      <AppTopbar
        breadcrumbs={[
          { label: "Prospection", href: "/prospection" },
          { label: "Analyses des leads" }
        ]}
        onOpenSidebar={onOpenSidebar}
      />
    <div className="px-5 py-6 lg:px-8">
      <header className="mb-5">
        <h1
          className="text-2xl font-bold text-white"
          style={{ fontFamily: "var(--font-fraunces, Georgia, serif)" }}
        >
          Analyses des{" "}
          <span className="italic text-accent-500">leads</span>
        </h1>
        <p className="mt-1 text-sm text-white/60">
          Colle un lien Centris/DuProprio, des photos, un PDF, un SMS — l&apos;IA
          extrait les infos et crée une fiche d&apos;analyse à compléter.
        </p>
      </header>

      {/* ── Zone de capture ───────────────────────────────────── */}
      <section
        onDragOver={(e) => e.preventDefault()}
        onDrop={onDrop}
        className="rounded-2xl border border-brand-800 bg-brand-900/40 p-5"
      >
        <div className="flex items-center gap-2">
          <Wand2 className="h-4 w-4 text-accent-500" />
          <h2 className="text-sm font-semibold uppercase tracking-wider text-accent-500">
            Capture de lead
          </h2>
        </div>

        <div className="mt-3 grid gap-3 lg:grid-cols-2">
          <div>
            <label className="label flex items-center gap-1.5">
              <Link2 className="h-3.5 w-3.5" />
              Lien(s) — Centris / DuProprio / Realtor (un par ligne)
            </label>
            <textarea
              value={urlsText}
              onChange={(e) => setUrlsText(e.target.value)}
              rows={3}
              placeholder="https://www.centris.ca/...&#10;https://duproprio.com/..."
              className="input font-mono text-xs"
            />
          </div>
          <div>
            <label className="label flex items-center gap-1.5">
              <FileText className="h-3.5 w-3.5" />
              Texte (SMS, email, description courtier…)
            </label>
            <textarea
              value={rawText}
              onChange={(e) => setRawText(e.target.value)}
              rows={3}
              placeholder="Colle ici un texte que tu as reçu sur l'immeuble…"
              className="input text-xs"
            />
          </div>
        </div>

        <div className="mt-3">
          <label className="label flex items-center gap-1.5">
            <ImageIcon className="h-3.5 w-3.5" />
            Photos, PDF, captures d&apos;écran (glisse, ou Ctrl+V pour
            coller une image)
          </label>
          <input
            ref={fileInputRef}
            type="file"
            multiple
            accept="image/*,application/pdf"
            className="hidden"
            onChange={(e) => onFilesPicked(e.target.files)}
          />
          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            className="inline-flex items-center gap-1.5 rounded-lg border border-dashed border-brand-700 bg-brand-900 px-3 py-2 text-xs text-white/70 hover:border-accent-500 hover:text-white"
          >
            <Upload className="h-3.5 w-3.5" />
            Ajouter des fichiers
          </button>
          {files.length > 0 ? (
            <ul className="mt-2 flex flex-wrap gap-2">
              {files.map((f, i) => (
                <li
                  key={i}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-brand-700 bg-brand-950 px-2 py-1 text-[11px] text-white/70"
                >
                  <span className="truncate max-w-[180px]">{f.name}</span>
                  <span className="text-white/40">
                    ({Math.round(f.size / 1024)} ko)
                  </span>
                  <button
                    type="button"
                    onClick={() => removeFile(i)}
                    className="text-white/40 hover:text-rose-300"
                    aria-label="Retirer"
                  >
                    <X className="h-3 w-3" />
                  </button>
                </li>
              ))}
            </ul>
          ) : null}
        </div>

        {extractErr ? (
          <p className="mt-3 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
            {extractErr}
          </p>
        ) : null}
        {extractResult ? (
          <div className="mt-3 space-y-2">
            <p className="rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-xs text-emerald-300">
              ✓ {extractResult.count} fiche{extractResult.count > 1 ? "s" : ""} créée{extractResult.count > 1 ? "s" : ""}
              {extractResult.count === 0 && extractResult.warnings.length === 0
                ? " (rien à extraire)"
                : ""}
            </p>
            {extractResult.warnings.length > 0 ? (
              <div className="rounded-lg border border-amber-500/50 bg-amber-500/15 px-3 py-2">
                <p className="text-[11px] font-semibold uppercase tracking-wider text-amber-700 dark:text-amber-300">
                  ⚠ {extractResult.warnings.length} avertissement{extractResult.warnings.length > 1 ? "s" : ""}
                </p>
                <ul className="mt-1.5 space-y-1.5 text-[11px] text-amber-900 dark:text-amber-100">
                  {extractResult.warnings.map((w, i) => (
                    <li key={i} className="whitespace-pre-wrap break-words">• {w}</li>
                  ))}
                </ul>
              </div>
            ) : null}
          </div>
        ) : null}

        <div className="mt-4 flex justify-end">
          <button
            type="button"
            onClick={onExtract}
            disabled={extracting}
            className="btn-accent inline-flex items-center text-sm disabled:opacity-60"
          >
            {extracting ? (
              <>
                <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />
                Extraction en cours…
              </>
            ) : (
              <>
                <Sparkles className="mr-1.5 h-4 w-4" />
                Extraire et créer la fiche
              </>
            )}
          </button>
        </div>
      </section>

      {/* ── Toolbar kanban ────────────────────────────────────── */}
      <div className="mt-6 flex flex-wrap items-center gap-3 rounded-lg border border-brand-800 bg-brand-900/40 px-3 py-2">
        <label className="relative inline-flex items-center">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-white/40" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Rechercher (adresse, ville, type…)"
            className="w-72 rounded-md border border-brand-800 bg-brand-900 py-1 pl-8 pr-2 text-xs text-white placeholder:text-white/30 focus:border-accent-500 focus:outline-none"
          />
        </label>
        <span className="text-[11px] text-white/40">
          {filtered.length} fiche{filtered.length > 1 ? "s" : ""}
        </span>
        <div className="ml-auto inline-flex rounded-lg border border-brand-800 bg-brand-900 p-0.5">
          <button
            type="button"
            onClick={() => setView("kanban")}
            className={`rounded-md px-3 py-1 text-xs font-semibold transition ${
              view === "kanban"
                ? "bg-accent-500 text-brand-950"
                : "text-white/60 hover:text-white"
            }`}
          >
            Kanban
          </button>
          <button
            type="button"
            onClick={() => setView("table")}
            className={`ml-0.5 rounded-md px-3 py-1 text-xs font-semibold transition ${
              view === "table"
                ? "bg-accent-500 text-brand-950"
                : "text-white/60 hover:text-white"
            }`}
          >
            Tableau
          </button>
        </div>
      </div>

      {/* ── Kanban / Tableau ──────────────────────────────────── */}
      {loading ? (
        <p className="mt-6 text-center text-sm text-white/50">
          <Loader2 className="mr-2 inline h-4 w-4 animate-spin" />
          Chargement…
        </p>
      ) : view === "kanban" ? (
        <div className="mt-4 grid gap-3 lg:grid-cols-4">
          {COLUMNS.map((col) => {
            const items = byStatus[col.key] || [];
            const hover = hoverCol === col.key;
            return (
              <div
                key={col.key}
                onDragOver={(e) => {
                  e.preventDefault();
                  setHoverCol(col.key);
                }}
                onDragLeave={() => setHoverCol(null)}
                onDrop={(e) => {
                  e.preventDefault();
                  setHoverCol(null);
                  if (dragId != null) {
                    void moveLead(dragId, col.key);
                    setDragId(null);
                  }
                }}
                className={`flex flex-col rounded-xl border bg-brand-900 transition ${
                  hover
                    ? "border-accent-500/60 bg-accent-500/5"
                    : "border-brand-800"
                }`}
              >
                <header className="flex items-center justify-between rounded-t-xl border-b border-brand-800 px-3 py-2">
                  <div className="flex items-center gap-1.5">
                    <span className={`h-2 w-2 rounded-full ${col.dot}`} />
                    <span className="text-xs font-semibold uppercase tracking-wider text-white/80">
                      {col.label}
                    </span>
                  </div>
                  <span className="rounded-full bg-brand-800 px-1.5 py-0.5 text-[10px] tabular-nums text-white/60">
                    {items.length}
                  </span>
                </header>
                <div className="flex-1 space-y-2 p-2">
                  {items.length === 0 ? (
                    <p className="px-2 py-4 text-center text-[10px] text-white/30">
                      —
                    </p>
                  ) : (
                    items.map((l) => (
                      <LeadCard
                        key={l.id}
                        lead={l}
                        dragging={dragId === l.id}
                        onDragStart={() => setDragId(l.id)}
                        onDragEnd={() => setDragId(null)}
                        onView={() => setDetailId(l.id)}
                        onChangeStatus={(s) => void moveLead(l.id, s)}
                        onDelete={() =>
                          deleteLead(l.id, l.address || `Lead #${l.id}`)
                        }
                        onConvert={() =>
                          convertToLead(l.id, l.address || `Lead #${l.id}`)
                        }
                      />
                    ))
                  )}
                </div>
              </div>
            );
          })}
        </div>
      ) : (
        <LeadTable
          leads={filtered}
          onView={(id) => setDetailId(id)}
          onDelete={(id, label) => deleteLead(id, label)}
          onConvert={(id, label) => convertToLead(id, label)}
        />
      )}

      {detailId !== null ? (
        <LeadAnalysisDetailModal
          analysisId={detailId}
          open
          onClose={() => {
            setDetailId(null);
            setBackToDealId(null);
          }}
          onAfterUpdate={() => {
            void reload();
          }}
          onBackToDeal={backToDealId != null ? goBackToDeal : undefined}
        />
      ) : null}
    </div>
    </>
  );
}

// ─── Card kanban ────────────────────────────────────────────────

/** Mapping statut d'analyse -> badge visuel (label + couleur). */
const STATUS_BADGE: Record<Lead["status"], LeadAnalysisCardBadge> = {
  a_analyser: { label: "À analyser", color: "violet" },
  decision_en_attente: { label: "Décision en attente", color: "amber" },
  interessant: { label: "Intéressant", color: "emerald" },
  abandonne: { label: "Abandonné", color: "rose" }
};

function LeadCard({
  lead,
  dragging,
  onDragStart,
  onDragEnd,
  onView,
  onDelete,
  onConvert
}: {
  lead: Lead;
  dragging: boolean;
  onDragStart: () => void;
  onDragEnd: () => void;
  onView: () => void;
  onChangeStatus: (s: Lead["status"]) => void;
  onDelete: () => void;
  onConvert: () => void;
}) {
  return (
    <div
      draggable
      onDragStart={onDragStart}
      onDragEnd={onDragEnd}
      className={`cursor-grab transition active:cursor-grabbing ${dragging ? "opacity-50" : ""}`}
    >
      <LeadAnalysisCard
        data={{
          id: lead.id,
          address: lead.address,
          city: lead.city,
          nb_logements: lead.nb_logements,
          asking_price: lead.asking_price,
          best_refi_amount: lead.best_refi_amount,
          best_refi_program: lead.best_refi_program,
          mdf_preteur_b: lead.mdf_preteur_b
        }}
        badge={STATUS_BADGE[lead.status]}
        extraBadge={extractionBadge(lead.model_used)}
        validationSeverity={lead.validation_severity}
        validationCount={lead.validation_count}
        onClick={onView}
        actions={
          <>
            <button
              type="button"
              onClick={onView}
              className="inline-flex items-center gap-1 rounded-md border border-white/15 bg-brand-950 px-1.5 py-0.5 text-[10px] text-white/70 hover:text-white"
              title="Ouvrir la fiche complète"
            >
              <Eye className="h-3 w-3" />
              Fiche
            </button>
            <button
              type="button"
              onClick={onConvert}
              disabled={!!lead.converted_to_deal_id}
              className="inline-flex items-center gap-1 rounded-md border border-emerald-500/30 bg-emerald-500/10 px-1.5 py-0.5 text-[10px] text-emerald-300 hover:bg-emerald-500/20 disabled:opacity-50"
              title={
                lead.converted_to_deal_id
                  ? "Déjà converti"
                  : "Ajouter au Pipeline"
              }
            >
              <Plus className="h-3 w-3" />
              Pipeline
            </button>
            <button
              type="button"
              onClick={onDelete}
              className="inline-flex items-center rounded-md border border-white/15 bg-brand-950 p-0.5 text-white/40 hover:border-rose-400/50 hover:text-rose-300"
              title="Supprimer"
              aria-label="Supprimer"
            >
              <Trash2 className="h-3 w-3" />
            </button>
          </>
        }
      />
    </div>
  );
}

// ─── Vue tableau ────────────────────────────────────────────────

function LeadTable({
  leads,
  onView,
  onDelete,
  onConvert
}: {
  leads: Lead[];
  onView: (id: number) => void;
  onDelete: (id: number, label: string) => void;
  onConvert: (id: number, label: string) => void;
}) {
  return (
    <div className="mt-4 overflow-x-auto rounded-xl border border-brand-800 bg-brand-900/40">
      <table className="w-full min-w-[800px] text-[13px]">
        <thead>
          <tr
            className="text-[10px] font-semibold uppercase tracking-wider text-white/40"
            style={{ borderBottom: "1px solid rgba(100,116,139,0.35)" }}
          >
            <th className="px-3 py-3 text-left">Adresse</th>
            <th className="px-3 py-3 text-left">Ville</th>
            <th className="w-[100px] px-3 py-3 text-center">Prix</th>
            <th className="w-[80px] px-3 py-3 text-center">Logements</th>
            <th className="w-[100px] px-3 py-3 text-center">Refi</th>
            <th className="w-[140px] px-3 py-3 text-center">Statut</th>
            <th className="w-[90px] px-3 py-3 text-center">Ajouté</th>
            <th className="w-[150px] px-3 py-3 text-right">Actions</th>
          </tr>
        </thead>
        <tbody>
          {leads.map((l) => (
            <tr
              key={l.id}
              className="border-t border-brand-800 hover:bg-brand-950/40"
            >
              <td className="px-3 py-2">
                <button
                  type="button"
                  onClick={() => onView(l.id)}
                  className="text-left text-sm font-medium text-white hover:text-accent-500"
                >
                  {l.address || `Lead #${l.id}`}
                </button>
              </td>
              <td className="px-3 py-2 text-xs text-white/60">
                {l.city || "—"}
              </td>
              <td className="px-3 py-2 text-center text-xs font-mono tabular-nums text-white/80">
                {fmtMoney(l.asking_price)}
              </td>
              <td className="px-3 py-2 text-center text-xs tabular-nums text-white/70">
                {l.nb_logements ?? "—"}
              </td>
              <td className="px-3 py-2 text-center text-xs tabular-nums text-emerald-300">
                {fmtMoney(l.best_refi_amount)}
              </td>
              <td className="px-3 py-2 text-center">
                <span className="rounded-full bg-brand-800 px-2 py-0.5 text-[10px] text-white/70">
                  {COLUMNS.find((c) => c.key === l.status)?.label || l.status}
                </span>
              </td>
              <td className="px-3 py-2 text-center text-[10px] text-white/40">
                {fmtDate(l.created_at)}
              </td>
              <td className="px-3 py-2 text-right">
                <div className="inline-flex items-center gap-1">
                  <button
                    type="button"
                    onClick={() => onView(l.id)}
                    className="rounded-md border border-white/15 p-1 text-white/60 hover:text-white"
                    title="Fiche"
                  >
                    <Eye className="h-3 w-3" />
                  </button>
                  <button
                    type="button"
                    onClick={() =>
                      onConvert(l.id, l.address || `Lead #${l.id}`)
                    }
                    disabled={!!l.converted_to_deal_id}
                    className="rounded-md border border-emerald-500/30 p-1 text-emerald-300 hover:bg-emerald-500/10 disabled:opacity-50"
                    title="Ajouter au Pipeline"
                  >
                    <Plus className="h-3 w-3" />
                  </button>
                  <button
                    type="button"
                    onClick={() =>
                      onDelete(l.id, l.address || `Lead #${l.id}`)
                    }
                    className="rounded-md border border-white/15 p-1 text-white/40 hover:border-rose-400/50 hover:text-rose-300"
                    title="Supprimer"
                  >
                    <Trash2 className="h-3 w-3" />
                  </button>
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
