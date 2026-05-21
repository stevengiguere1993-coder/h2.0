"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Building,
  Eye,
  FileText,
  Flame,
  Image as ImageIcon,
  Link2,
  Loader2,
  Pause,
  Plus,
  Search,
  Sparkles,
  Trash2,
  Upload,
  Wand2,
  X
} from "lucide-react";

import { authedFetch } from "@/lib/auth";
import { useConfirm } from "@/components/confirm-dialog";
import { AppTopbar } from "@/components/app-topbar";
import { PillPicker } from "@/components/task-pills";
import { useProspectionLayout } from "../layout";
import { Link, useRouter } from "@/i18n/navigation";

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
  created_at: string;
  attachments_count: number;
};

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
  const [extractMsg, setExtractMsg] = useState<string | null>(null);
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
    setExtractMsg(null);
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
      // Reset les inputs.
      setUrlsText("");
      setRawText("");
      setFiles([]);
      const n = data.created.length;
      const warnTxt = data.warnings.length
        ? ` · ${data.warnings.length} avertissement(s)`
        : "";
      setExtractMsg(
        `${n} fiche${n > 1 ? "s" : ""} créée${n > 1 ? "s" : ""}${warnTxt}`
      );
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

  // Filtrage recherche.
  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return leads;
    return leads.filter((l) => {
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
        {extractMsg ? (
          <p className="mt-3 rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-xs text-emerald-300">
            ✓ {extractMsg}
          </p>
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
        <LeadDetailModal
          id={detailId}
          onClose={() => setDetailId(null)}
          onSaved={() => {
            void reload();
          }}
        />
      ) : null}
    </div>
    </>
  );
}

// ─── Card kanban ────────────────────────────────────────────────

function LeadCard({
  lead,
  dragging,
  onDragStart,
  onDragEnd,
  onView,
  onChangeStatus,
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
      className={`group cursor-grab rounded-md border border-brand-800 bg-brand-950 p-2.5 transition active:cursor-grabbing ${
        dragging ? "opacity-50" : ""
      }`}
    >
      <button
        type="button"
        onClick={onView}
        className="block w-full text-left"
      >
        <p className="line-clamp-2 text-xs font-semibold text-white hover:text-accent-500">
          {lead.address || `Lead #${lead.id}`}
        </p>
        {lead.city ? (
          <p className="mt-0.5 text-[10px] text-white/50">{lead.city}</p>
        ) : null}
      </button>
      <div className="mt-1.5 flex flex-wrap items-center gap-2 text-[10px] text-white/60">
        {lead.nb_logements != null ? (
          <span className="inline-flex items-center gap-0.5">
            <Building className="h-2.5 w-2.5" /> {lead.nb_logements} log.
          </span>
        ) : null}
        {lead.asking_price != null ? (
          <span className="font-mono tabular-nums">
            {fmtMoney(lead.asking_price)}
          </span>
        ) : null}
        {lead.best_refi_amount != null ? (
          <span
            className={`inline-flex items-center gap-0.5 ${
              lead.best_refi_amount >= 0 ? "text-emerald-300" : "text-rose-300"
            }`}
            title={lead.best_refi_program || ""}
          >
            <Flame className="h-2.5 w-2.5" />
            {lead.best_refi_amount >= 0 ? "refi" : "perte"}{" "}
            {fmtMoney(lead.best_refi_amount)}
          </span>
        ) : null}
      </div>
      {lead.best_refi_program ? (
        <p className="mt-0.5 truncate text-[9px] text-white/40" title={lead.best_refi_program}>
          {lead.best_refi_program}
        </p>
      ) : null}
      {lead.mdf_preteur_b != null ? (
        <p
          className="mt-0.5 text-[10px] text-amber-300/80"
          title="Mise de fonds avec prêteur B = 25 % × prix d'achat + frais démarrage"
        >
          MDF prêteur B : <span className="font-mono">{fmtMoney(lead.mdf_preteur_b)}</span>
        </p>
      ) : null}
      {/* Sélecteur de statut — même style que les pills tâches
          d'entreprise (point coloré + label, picker discret). */}
      <div
        className="mt-1.5"
        onClick={(e) => e.stopPropagation()}
      >
        <PillPicker
          options={COLUMNS.map((c) => ({
            value: c.key,
            label: c.label,
            dot: c.dot,
            cls: c.dot
          }))}
          value={lead.status}
          onChange={(v) => onChangeStatus(v as Lead["status"])}
          ariaLabel="Statut du lead"
        />
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-1">
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
          className="ml-auto inline-flex items-center rounded-md border border-white/15 bg-brand-950 p-0.5 text-white/40 hover:border-rose-400/50 hover:text-rose-300"
          title="Supprimer"
          aria-label="Supprimer"
        >
          <Trash2 className="h-3 w-3" />
        </button>
      </div>
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

// ─── Modale fiche détail (Phase 1 — read-only des extraits) ────

type LeadDetail = Lead & {
  postal_code: string | null;
  province: string | null;
  typology_json: string | null;
  revenus_bruts: number | null;
  taxes_municipales: number | null;
  taxes_scolaires: number | null;
  assurances: number | null;
  energie: number | null;
  depenses_autres: number | null;
  superficie_terrain: number | null;
  superficie_batiment: number | null;
  evaluation_municipale: number | null;
  description: string | null;
  courtier_nom: string | null;
  courtier_contact: string | null;
  nb_stationnements: number | null;
  source_urls: string | null;
  source_text: string | null;
  notes: string | null;
  // Inputs manuels analyse financière
  loyers_projetes_json: string | null;
  loyers_max_abordabilite_json: string | null;
  travaux_estimes: number | null;
  nb_logements_ajoutes: number | null;
  nb_thermopompes_ajoutees: number | null;
  ajout_wifi: boolean | null;
  reduction_energie_pct: number | null;
  taux_interet_refi_pct: number | null;
  tga_pct: number | null;
  taux_interet_achat_pct: number | null;
  duree_projet_annees: number | null;
  frais_developpement: number | null;
  frais_negociations: number | null;
  // MDF prêteur B configurable + overrides frais démarrage
  mdf_preteur_b_pct: number | null;
  frais_demarrage_overrides_json: string | null;
  frais_demarrage_financables_json: string | null;
  // Résultats analyse
  analysis_results_json: string | null;
  attachments: Array<{
    id: number;
    filename: string;
    content_type: string;
    size_bytes: number;
  }>;
};

const TYPOLOGY_KEYS = ["1.5", "2.5", "3.5", "4.5", "5.5", "6.5", "7.5", "8.5"];

function LeadDetailModal({
  id,
  onClose,
  onSaved
}: {
  id: number;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [data, setData] = useState<LeadDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const r = await authedFetch(`/api/v1/lead-analyses/${id}`);
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const j = (await r.json()) as LeadDetail;
        if (!cancelled) setData(j);
      } catch (e) {
        if (!cancelled) setError((e as Error).message);
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [id]);

  async function patchField(field: string, value: unknown) {
    if (!data) return;
    setData({ ...data, [field]: value } as LeadDetail);
    try {
      await authedFetch(`/api/v1/lead-analyses/${id}`, {
        method: "PATCH",
        body: JSON.stringify({ [field]: value })
      });
      onSaved();
    } catch {
      /* silent — local state retained */
    }
  }

  // ── Estimation IA des dépenses manquantes ─────────────────────
  // Appelle /estimate-expenses (Claude + fallback heuristique). On
  // ne remplace que les champs vides. Si l'IA ne peut rien estimer
  // (ex. fiche sans prix d'achat), on affiche un message clair.
  const [estimatingExpenses, setEstimatingExpenses] = useState(false);
  const [estimateMsg, setEstimateMsg] = useState<{
    text: string;
    kind: "ok" | "warn" | "err";
  } | null>(null);
  async function estimateExpenses() {
    if (!data) return;
    setEstimatingExpenses(true);
    setEstimateMsg(null);
    try {
      const r = await authedFetch(
        `/api/v1/lead-analyses/${id}/estimate-expenses`,
        { method: "POST" }
      );
      if (!r.ok) {
        setEstimateMsg({
          text: `Estimation échouée (HTTP ${r.status})`,
          kind: "err"
        });
        return;
      }
      const out = (await r.json()) as {
        taxes_municipales: number | null;
        taxes_scolaires: number | null;
        assurances: number | null;
        source?: string;
        note?: string;
      };
      const patch: Record<string, number> = {};
      if (data.taxes_municipales == null && out.taxes_municipales != null) {
        patch.taxes_municipales = out.taxes_municipales;
      }
      if (data.taxes_scolaires == null && out.taxes_scolaires != null) {
        patch.taxes_scolaires = out.taxes_scolaires;
      }
      if (data.assurances == null && out.assurances != null) {
        patch.assurances = out.assurances;
      }
      if (Object.keys(patch).length > 0) {
        setData({ ...data, ...patch } as LeadDetail);
        await authedFetch(`/api/v1/lead-analyses/${id}`, {
          method: "PATCH",
          body: JSON.stringify(patch)
        });
        onSaved();
        const labels = Object.keys(patch)
          .map((k) =>
            k === "taxes_municipales"
              ? "taxes muni"
              : k === "taxes_scolaires"
              ? "taxes scol"
              : "assurances"
          )
          .join(", ");
        setEstimateMsg({
          text: `${labels} estimé${
            Object.keys(patch).length > 1 ? "s" : ""
          } via ${out.source || "IA"}.`,
          kind: "ok"
        });
      } else {
        // Aucun champ patché — soit tout est déjà rempli, soit l'IA
        // n'a rien pu estimer faute d'infos (ex. prix manquant).
        const reason =
          out.note ||
          "L'IA n'a pas pu estimer — vérifie que le prix demandé et le nombre de logements sont renseignés.";
        setEstimateMsg({ text: reason, kind: "warn" });
      }
    } catch (e) {
      setEstimateMsg({
        text: `Estimation échouée : ${(e as Error).message}`,
        kind: "err"
      });
    } finally {
      setEstimatingExpenses(false);
    }
  }

  const typology = useMemo(() => {
    if (!data?.typology_json) return null;
    try {
      return JSON.parse(data.typology_json) as Record<string, number>;
    } catch {
      return null;
    }
  }, [data?.typology_json]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-end justify-center bg-black/70 px-2 py-4 sm:items-center"
      onClick={onClose}
    >
      <div
        className="flex max-h-[calc(100vh-2rem)] w-full max-w-3xl flex-col overflow-hidden rounded-2xl border border-brand-800 bg-brand-950"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="flex flex-shrink-0 items-start justify-between gap-3 border-b border-brand-800 px-5 py-4">
          <div className="min-w-0 flex-1">
            <p className="text-[10px] uppercase tracking-wider text-accent-500">
              Fiche d&apos;analyse
            </p>
            <h2 className="mt-0.5 truncate text-base font-bold text-white">
              {data?.address || `Lead #${id}`}
            </h2>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md p-1 text-white/60 hover:bg-brand-900 hover:text-white"
            aria-label="Fermer"
          >
            <X className="h-4 w-4" />
          </button>
        </header>

        <div className="flex-1 overflow-y-auto px-5 py-4">
          {loading ? (
            <p className="py-12 text-center text-sm text-white/40">
              <Loader2 className="mr-2 inline h-4 w-4 animate-spin" />
              Chargement…
            </p>
          ) : error ? (
            <p className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
              {error}
            </p>
          ) : !data ? null : (
            <div className="space-y-5">
              {/* Sélecteur de statut — première section (déplacée
                  ici depuis la fin de la fiche pour mise en avant). */}
              <section className="rounded-xl border border-brand-800 bg-brand-900 p-4">
                <h3 className="text-[10px] font-semibold uppercase tracking-wider text-accent-500">
                  Statut du lead
                </h3>
                <p className="mt-1 text-[10px] text-white/50">
                  Change la colonne du kanban depuis ici aussi.
                </p>
                <div className="mt-2">
                  <PillPicker
                    options={COLUMNS.map((c) => ({
                      value: c.key,
                      label: c.label,
                      dot: c.dot,
                      cls: c.dot
                    }))}
                    value={data.status}
                    onChange={(v) => patchField("status", v)}
                    ariaLabel="Statut du lead"
                  />
                </div>
              </section>

              <section>
                <h3 className="text-[10px] font-semibold uppercase tracking-wider text-accent-500">
                  Infos extraites
                </h3>
                <p className="mt-0.5 text-[11px] text-white/40">
                  Champs pré-remplis par l&apos;IA — clique pour corriger.
                  Les champs vides sont à compléter manuellement.
                </p>
                <div className="mt-3 grid gap-3 sm:grid-cols-2">
                  <FieldText
                    label="Adresse"
                    value={data.address}
                    onSave={(v) => patchField("address", v)}
                    required
                  />
                  <FieldText
                    label="Ville"
                    value={data.city}
                    onSave={(v) => patchField("city", v)}
                    required
                  />
                  <FieldText
                    label="Code postal"
                    value={data.postal_code}
                    onSave={(v) => patchField("postal_code", v)}
                  />
                  <FieldText
                    label="Type bâtiment"
                    value={data.type_batiment}
                    onSave={(v) => patchField("type_batiment", v)}
                  />
                  <FieldNumber
                    label="Prix demandé ($)"
                    name="asking_price"
                    value={data.asking_price}
                    onSave={(v) => patchField("asking_price", v)}
                    required
                    format="money"
                  />
                  <FieldNumber
                    label="Année construction"
                    value={data.annee_construction}
                    onSave={(v) => patchField("annee_construction", v)}
                  />
                  <FieldNumber
                    label="Nb logements"
                    name="nb_logements"
                    value={data.nb_logements}
                    onSave={(v) => patchField("nb_logements", v)}
                    required
                  />
                  <FieldNumber
                    label="Nb stationnements"
                    value={data.nb_stationnements}
                    onSave={(v) => patchField("nb_stationnements", v)}
                  />
                  <FieldNumber
                    label="Revenus bruts ($/an)"
                    name="revenus_bruts"
                    value={data.revenus_bruts}
                    onSave={(v) => patchField("revenus_bruts", v)}
                    required
                    format="money"
                  />
                  <FieldNumber
                    label="Évaluation municipale ($)"
                    value={data.evaluation_municipale}
                    onSave={(v) => patchField("evaluation_municipale", v)}
                    format="money"
                  />
                  <FieldNumber
                    label="Taxes municipales ($/an)"
                    name="taxes_municipales"
                    value={data.taxes_municipales}
                    onSave={(v) => patchField("taxes_municipales", v)}
                    required
                    onEstimate={() => void estimateExpenses()}
                    estimating={estimatingExpenses}
                    format="money"
                  />
                  <FieldNumber
                    label="Taxes scolaires ($/an)"
                    name="taxes_scolaires"
                    value={data.taxes_scolaires}
                    onSave={(v) => patchField("taxes_scolaires", v)}
                    required
                    onEstimate={() => void estimateExpenses()}
                    estimating={estimatingExpenses}
                    format="money"
                  />
                  <FieldNumber
                    label="Assurances ($/an)"
                    name="assurances"
                    value={data.assurances}
                    onSave={(v) => patchField("assurances", v)}
                    required
                    onEstimate={() => void estimateExpenses()}
                    estimating={estimatingExpenses}
                    format="money"
                  />
                  <FieldNumber
                    label="Énergie ($/an)"
                    name="energie"
                    value={data.energie}
                    onSave={(v) => patchField("energie", v)}
                    format="money"
                  />
                  <FieldNumber
                    label="Superficie terrain"
                    value={data.superficie_terrain}
                    onSave={(v) => patchField("superficie_terrain", v)}
                  />
                  <FieldNumber
                    label="Superficie bâtiment"
                    value={data.superficie_batiment}
                    onSave={(v) => patchField("superficie_batiment", v)}
                  />
                  <FieldText
                    label="Courtier (nom)"
                    value={data.courtier_nom}
                    onSave={(v) => patchField("courtier_nom", v)}
                  />
                  <FieldText
                    label="Courtier (contact)"
                    value={data.courtier_contact}
                    onSave={(v) => patchField("courtier_contact", v)}
                  />
                </div>

                {estimateMsg ? (
                  <p
                    className={`mt-2 rounded-lg border px-3 py-2 text-[11px] ${
                      estimateMsg.kind === "ok"
                        ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-300"
                        : estimateMsg.kind === "warn"
                        ? "border-amber-500/50 bg-amber-500/10 text-amber-200"
                        : "border-rose-500/40 bg-rose-500/10 text-rose-300"
                    }`}
                  >
                    {estimateMsg.text}
                  </p>
                ) : null}

                <div className="mt-3">
                  <p className="text-[11px] font-semibold uppercase tracking-wider text-white/50">
                    Typologie des logements
                  </p>
                  <p className="mt-0.5 text-[10px] text-white/40">
                    Quantité par typologie — modifiable si Claude n&apos;a
                    pas trouvé ou si tu veux corriger.
                  </p>
                  <TypologyEditor
                    value={typology || {}}
                    onSave={(j) =>
                      patchField("typology_json", JSON.stringify(j))
                    }
                  />
                </div>

                <div className="mt-3">
                  <p className="text-[11px] font-semibold uppercase tracking-wider text-white/50">
                    Description
                  </p>
                  <textarea
                    rows={3}
                    value={data.description || ""}
                    onChange={(e) =>
                      setData({ ...data, description: e.target.value })
                    }
                    onBlur={(e) => patchField("description", e.target.value)}
                    placeholder="Description / notes du courtier"
                    className="input mt-1 text-xs"
                  />
                </div>
              </section>

              {/* Sources originales */}
              {data.source_urls || data.source_text || data.attachments?.length ? (
                <section>
                  <h3 className="text-[10px] font-semibold uppercase tracking-wider text-accent-500">
                    Sources originales
                  </h3>
                  {data.source_urls ? (
                    <div className="mt-2 space-y-1">
                      {data.source_urls
                        .split("\n")
                        .filter((u) => u.trim())
                        .map((u, i) => (
                          <a
                            key={i}
                            href={u}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="block truncate text-xs text-violet-300 hover:underline"
                          >
                            🔗 {u}
                          </a>
                        ))}
                    </div>
                  ) : null}
                  {data.attachments?.length ? (
                    <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-4">
                      {data.attachments.map((a) => (
                        <AttachmentThumb
                          key={a.id}
                          leadId={id}
                          attachment={a}
                        />
                      ))}
                    </div>
                  ) : null}
                  {data.source_text ? (
                    <details className="mt-2">
                      <summary className="cursor-pointer text-[11px] text-white/50">
                        Texte original collé
                      </summary>
                      <pre className="mt-1 whitespace-pre-wrap rounded-md border border-brand-800 bg-brand-950 p-2 text-[11px] text-white/70">
                        {data.source_text}
                      </pre>
                    </details>
                  ) : null}
                </section>
              ) : null}

              {/* Section Analyse financière — inputs manuels + bouton */}
              <ManualAnalysisSection
                data={data}
                onPatch={patchField}
                onRefresh={async () => {
                  // Recharge la fiche pour récupérer les résultats
                  const r = await authedFetch(`/api/v1/lead-analyses/${id}`);
                  if (r.ok) setData((await r.json()) as LeadDetail);
                  onSaved();
                }}
              />

              {/* Résultats si analyse exécutée */}
              {data.analysis_results_json ? (
                <AnalysisResultsTable
                  resultsJson={data.analysis_results_json}
                  overridesJson={data.frais_demarrage_overrides_json}
                  financablesJson={data.frais_demarrage_financables_json}
                  mdfPct={data.mdf_preteur_b_pct ?? 25}
                  prixAchat={data.asking_price ?? 0}
                  fraisDemarrageTotalDb={null}
                  mdfPreteurBDb={data.mdf_preteur_b ?? null}
                  onPatchOverrides={(j) =>
                    patchField("frais_demarrage_overrides_json", j)
                  }
                  onPatchFinancables={(j) =>
                    patchField("frais_demarrage_financables_json", j)
                  }
                />
              ) : null}

              {/* Notes internes */}
              <section>
                <h3 className="text-[10px] font-semibold uppercase tracking-wider text-accent-500">
                  Notes internes
                </h3>
                <textarea
                  rows={3}
                  value={data.notes || ""}
                  onChange={(e) =>
                    setData({ ...data, notes: e.target.value })
                  }
                  onBlur={(e) => patchField("notes", e.target.value)}
                  placeholder="Tes notes privées sur ce lead"
                  className="input mt-2 text-xs"
                />
              </section>

            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ─── Champ éditable ────────────────────────────────────────────

// ─── Vignette d'attachment : fetch via authedFetch puis blob URL ───
//
// Les endpoints backend qui servent un fichier (image, PDF) exigent
// un Bearer token. Un <img src> ou <a href> direct envoie une simple
// GET sans token → 401. On télécharge le blob côté JS et on génère
// un objectURL pour l'aperçu + le lien d'ouverture en nouvel onglet.

function AttachmentThumb({
  leadId,
  attachment
}: {
  leadId: number;
  attachment: {
    id: number;
    filename: string;
    content_type: string;
    size_bytes: number;
  };
}) {
  const [blobUrl, setBlobUrl] = useState<string | null>(null);
  const [err, setErr] = useState(false);
  const isImage = (attachment.content_type || "").startsWith("image/");
  const isPdf = (attachment.content_type || "").includes("pdf");

  useEffect(() => {
    let cancelled = false;
    let cleanupUrl: string | null = null;
    (async () => {
      try {
        const r = await authedFetch(
          `/api/v1/lead-analyses/${leadId}/attachments/${attachment.id}`
        );
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const blob = await r.blob();
        if (cancelled) return;
        const url = URL.createObjectURL(blob);
        cleanupUrl = url;
        setBlobUrl(url);
      } catch {
        if (!cancelled) setErr(true);
      }
    })();
    return () => {
      cancelled = true;
      if (cleanupUrl) URL.revokeObjectURL(cleanupUrl);
    };
  }, [leadId, attachment.id]);

  return (
    <a
      href={blobUrl || "#"}
      target="_blank"
      rel="noopener noreferrer"
      onClick={(e) => {
        if (!blobUrl) e.preventDefault();
      }}
      className="block overflow-hidden rounded-md border border-brand-800 bg-brand-950 hover:border-accent-500"
      title={attachment.filename}
    >
      {isImage && blobUrl ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={blobUrl}
          alt={attachment.filename}
          className="h-24 w-full object-cover"
        />
      ) : isImage && !blobUrl && !err ? (
        <div className="flex h-24 items-center justify-center text-white/30">
          <Loader2 className="h-4 w-4 animate-spin" />
        </div>
      ) : err ? (
        <div className="flex h-24 items-center justify-center text-2xl text-rose-300/60">
          ✗
        </div>
      ) : isPdf ? (
        <div className="flex h-24 items-center justify-center text-3xl text-white/30">
          📕
        </div>
      ) : (
        <div className="flex h-24 items-center justify-center text-3xl text-white/30">
          📄
        </div>
      )}
      <p className="truncate px-2 py-1 text-[10px] text-white/60">
        {attachment.filename}
      </p>
    </a>
  );
}

// Champs effectivement consommés par les fonctions compute_* de
// l'analyse financière (backend/app/services/lead_analysis_finance.py).
// Quand l'un de ces champs est vide, on surligne son label en ambre
// pour signaler que le calcul sera incomplet, sans bruit visuel sur
// les autres champs facultatifs.
//
// Les noms ci-dessous sont les noms tels qu'utilisés côté formulaire
// (prop `name` passée à FieldText / FieldNumber), pas les noms du
// modèle backend (certains diffèrent : asking_price ↔ prix_achat,
// nb_logements ↔ nombre_logements, revenus_bruts ↔ revenus_annuels).
const CHAMPS_NECESSAIRES_CALC: ReadonlySet<string> = new Set([
  "asking_price",
  "nb_logements",
  "revenus_bruts",
  "taxes_municipales",
  "taxes_scolaires",
  "assurances",
  "energie",
  "typology_json"
]);

function FieldText({
  label,
  value,
  onSave,
  required,
  name
}: {
  label: string;
  value: string | null;
  onSave: (v: string | null) => void;
  required?: boolean;
  /** Nom du champ côté formulaire — utilisé pour décider si le
   *  surlignage ambre « champ nécessaire aux calculs » doit
   *  s'appliquer quand la valeur est vide. */
  name?: string;
}) {
  const [v, setV] = useState(value || "");
  useEffect(() => setV(value || ""), [value]);
  const isEmpty = !value;
  const missingRequired = isEmpty && required;
  const necessaryForCalc =
    isEmpty && !missingRequired && !!name && CHAMPS_NECESSAIRES_CALC.has(name);
  return (
    <div>
      <label
        className={`text-[10px] uppercase tracking-wider ${
          missingRequired
            ? "text-rose-400 font-semibold"
            : necessaryForCalc
            ? "text-amber-600 dark:text-amber-300/80"
            : "text-white/50"
        }`}
      >
        {label}
        {missingRequired ? " · OBLIGATOIRE" : ""}
      </label>
      <input
        type="text"
        value={v}
        onChange={(e) => setV(e.target.value)}
        onBlur={() => {
          if ((value || "") !== v) onSave(v.trim() || null);
        }}
        className={`input mt-1 text-xs ${
          missingRequired
            ? "border-rose-400/70 focus:border-rose-400 ring-1 ring-rose-400/30"
            : ""
        }`}
      />
    </div>
  );
}

function _formatMoneyExcel(n: number): string {
  // 100000 → "100 000 $"
  const sign = n < 0 ? "-" : "";
  const rounded = Math.round(Math.abs(n));
  const withSep = rounded
    .toString()
    .replace(/\B(?=(\d{3})+(?!\d))/g, " ");
  return `${sign}${withSep} $`;
}

function _formatPercentExcel(n: number): string {
  // 4 → "4.00 %"
  return `${n.toFixed(2)} %`;
}

function _parseNumberLiberal(s: string): number | null {
  // Accepte "100 000 $", "100,000.00", "100000", "4.00%", "4%"
  if (s == null) return null;
  const cleaned = s
    .replace(/[\s ]/g, "")
    .replace(/\$/g, "")
    .replace(/%/g, "")
    .replace(/,/g, ".");
  if (cleaned === "" || cleaned === "-" || cleaned === ".") return null;
  const n = Number(cleaned);
  return Number.isFinite(n) ? n : null;
}

function FieldNumber({
  label,
  value,
  onSave,
  required,
  onEstimate,
  estimating,
  format = "plain",
  name
}: {
  label: string;
  value: number | null;
  onSave: (v: number | null) => void;
  required?: boolean;
  /** Quand le champ est vide ET cette prop est fournie, on affiche
   *  un bouton « Estimer IA » à droite du label qui appelle ce
   *  handler. Utilisé pour taxes muni / scolaires / assurances. */
  onEstimate?: () => void;
  estimating?: boolean;
  /** Format d'affichage hors-focus :
   *  - "money"   : « 100 000 $ » (Excel style)
   *  - "percent" : « 4.00 % »
   *  - "plain"   : valeur brute (défaut) */
  format?: "money" | "percent" | "plain";
  /** Nom du champ côté formulaire — utilisé pour décider si le
   *  surlignage ambre « champ nécessaire aux calculs » doit
   *  s'appliquer quand la valeur est vide. */
  name?: string;
}) {
  const [focused, setFocused] = useState(false);
  const [v, setV] = useState(value != null ? String(value) : "");
  useEffect(() => {
    if (!focused) setV(value != null ? String(value) : "");
  }, [value, focused]);
  const isEmpty = value == null;
  const missingRequired = isEmpty && required;
  const necessaryForCalc =
    isEmpty && !missingRequired && !!name && CHAMPS_NECESSAIRES_CALC.has(name);

  // Texte affiché quand le champ n'est pas focus.
  const displayed = (() => {
    if (focused) return v;
    if (value == null) return "";
    if (format === "money") return _formatMoneyExcel(value);
    if (format === "percent") return _formatPercentExcel(value);
    return String(value);
  })();

  return (
    <div>
      <div className="flex items-baseline justify-between gap-2">
        <label
          className={`text-[10px] uppercase tracking-wider ${
            missingRequired
              ? "text-rose-400 font-semibold"
              : necessaryForCalc
              ? "text-amber-600 dark:text-amber-300/80"
              : "text-white/50"
          }`}
        >
          {label}
          {missingRequired ? " · OBLIGATOIRE" : ""}
        </label>
        {isEmpty && onEstimate ? (
          <button
            type="button"
            onClick={onEstimate}
            disabled={!!estimating}
            className="inline-flex items-center gap-1 rounded border border-amber-400/50 bg-amber-500/15 px-1.5 py-0 text-[9px] font-semibold text-amber-200 hover:bg-amber-500/25 disabled:opacity-50"
            title="Estimer cette valeur avec l'IA"
          >
            {estimating ? (
              <Loader2 className="h-2.5 w-2.5 animate-spin" />
            ) : (
              <Sparkles className="h-2.5 w-2.5" />
            )}
            IA
          </button>
        ) : null}
      </div>
      <input
        type="text"
        inputMode="decimal"
        value={displayed}
        onFocus={(e) => {
          setFocused(true);
          // À l'entrée en focus, on charge la valeur brute pour
          // permettre l'édition naturelle (pas de « 100 000 $ »
          // qui empêcherait de taper).
          setV(value != null ? String(value) : "");
          // Sélectionne le contenu pour faciliter l'écrasement.
          requestAnimationFrame(() => {
            try {
              e.target.select();
            } catch {
              /* ignore */
            }
          });
        }}
        onChange={(e) => setV(e.target.value)}
        onBlur={() => {
          setFocused(false);
          const num = _parseNumberLiberal(v);
          if (num !== value) onSave(num);
        }}
        className={`input mt-1 font-mono text-xs ${
          missingRequired
            ? "border-rose-400/70 focus:border-rose-400 ring-1 ring-rose-400/30"
            : ""
        }`}
      />
    </div>
  );
}

// ─── Typology editor : grille éditable des unités par type ─────

function TypologyEditor({
  value,
  onSave
}: {
  value: Record<string, number>;
  onSave: (newValue: Record<string, number>) => void;
}) {
  const [local, setLocal] = useState<Record<string, string>>(() => {
    const m: Record<string, string> = {};
    for (const k of TYPOLOGY_KEYS) {
      const n = Number(value[k] || 0);
      m[k] = n > 0 ? String(n) : "";
    }
    return m;
  });

  function commit(k: string, raw: string) {
    setLocal((prev) => ({ ...prev, [k]: raw }));
    const next: Record<string, number> = {};
    for (const kk of TYPOLOGY_KEYS) {
      const r = kk === k ? raw : local[kk];
      const n = Number(r);
      if (Number.isFinite(n) && n > 0) next[kk] = Math.floor(n);
    }
    onSave(next);
  }

  const total = TYPOLOGY_KEYS.reduce(
    (acc, k) => acc + (Number(local[k]) || 0),
    0
  );

  return (
    <div className="mt-1">
      <div className="grid grid-cols-4 gap-2 sm:grid-cols-8">
        {TYPOLOGY_KEYS.map((k) => (
          <div key={k} className="flex flex-col items-center">
            <label className="text-[10px] font-mono text-white/50">
              {k}
            </label>
            <input
              type="number"
              min="0"
              step="1"
              value={local[k]}
              onChange={(e) =>
                setLocal((prev) => ({ ...prev, [k]: e.target.value }))
              }
              onBlur={(e) => commit(k, e.target.value)}
              placeholder="0"
              className="w-full rounded border border-brand-800 bg-brand-950 px-1 py-0.5 text-center text-xs text-white focus:border-accent-500 focus:outline-none"
            />
          </div>
        ))}
      </div>
      <p className="mt-1 text-[10px] text-white/40">
        Total typologie : <strong className="text-white/70">{total}</strong>{" "}
        unité{total > 1 ? "s" : ""}
      </p>
    </div>
  );
}

// ─── Section infos manuelles d'analyse + bouton Lancer ─────────

function ManualAnalysisSection({
  data,
  onPatch,
  onRefresh
}: {
  data: LeadDetail;
  onPatch: (field: string, value: unknown) => void;
  onRefresh: () => Promise<void>;
}) {
  // Typologie parsée pour savoir quels prix H demander.
  const typology = useMemo<Record<string, number>>(() => {
    if (!data.typology_json) return {};
    try {
      const j = JSON.parse(data.typology_json);
      if (j && typeof j === "object") return j;
    } catch {
      /* ignore */
    }
    return {};
  }, [data.typology_json]);

  // Loyers projetés (H6..H12) — seulement où G > 0.
  const [prixLoyers, setPrixLoyers] = useState<Record<string, string>>(
    () => {
      try {
        const j = JSON.parse(data.loyers_projetes_json || "{}");
        const m: Record<string, string> = {};
        for (const k of Object.keys(j)) m[k] = String(j[k]);
        return m;
      } catch {
        return {};
      }
    }
  );

  // Loyer abordable (D8 APH SELECT).
  const [loyerAbord, setLoyerAbord] = useState<string>(() => {
    try {
      const j = JSON.parse(data.loyers_max_abordabilite_json || "{}");
      return String(j.abordable ?? "");
    } catch {
      return "";
    }
  });

  const [running, setRunning] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  // Champs OBLIGATOIRES pour lancer l'analyse. Sans eux, le bouton
  // est désactivé. Adresse, ville, nb logements, prix, revenus,
  // taxes muni/scolaires/assurances sont indispensables à la
  // mécanique de calcul (Steven : tout le reste est recommandé).
  const missingRequired = useMemo(() => {
    const missing: string[] = [];
    if (!data.address) missing.push("Adresse");
    if (!data.city) missing.push("Ville");
    if (!data.nb_logements) missing.push("Nb logements");
    if (!data.asking_price) missing.push("Prix demandé");
    if (!data.revenus_bruts) missing.push("Revenus annuels");
    if (data.taxes_municipales == null) missing.push("Taxes municipales");
    if (data.taxes_scolaires == null) missing.push("Taxes scolaires");
    if (data.assurances == null) missing.push("Assurances");
    return missing;
  }, [data]);

  // Champs recommandés (non bloquants) — affichage informatif si
  // manquants, mais l'analyse peut quand même se lancer.
  const missingRecommended = useMemo(() => {
    const missing: string[] = [];
    if (data.energie == null) missing.push("Énergie");
    if (data.depenses_autres == null) missing.push("Autres dépenses");
    if (!data.annee_construction) missing.push("Année construction");
    if (!data.evaluation_municipale) missing.push("Évaluation municipale");
    return missing;
  }, [data]);

  // Sous-ensemble que l'IA peut estimer (taxes muni/scol/assurances).
  const missingEstimable = useMemo(() => {
    const m: string[] = [];
    if (data.taxes_municipales == null) m.push("Taxes municipales");
    if (data.taxes_scolaires == null) m.push("Taxes scolaires");
    if (data.assurances == null) m.push("Assurances");
    return m;
  }, [data]);

  const [estimating, setEstimating] = useState(false);

  async function estimateExpenses() {
    setEstimating(true);
    setErr(null);
    try {
      const r = await authedFetch(
        `/api/v1/lead-analyses/${data.id}/estimate-expenses`,
        { method: "POST" }
      );
      if (!r.ok) {
        const txt = await r.text();
        throw new Error(txt.slice(0, 200) || `HTTP ${r.status}`);
      }
      const out = (await r.json()) as {
        taxes_municipales: number | null;
        taxes_scolaires: number | null;
        assurances: number | null;
        source: string;
        note?: string;
      };
      // Patche uniquement les champs encore vides — on ne remplace
      // pas une valeur déjà saisie manuellement.
      if (data.taxes_municipales == null && out.taxes_municipales != null) {
        onPatch("taxes_municipales", out.taxes_municipales);
      }
      if (data.taxes_scolaires == null && out.taxes_scolaires != null) {
        onPatch("taxes_scolaires", out.taxes_scolaires);
      }
      if (data.assurances == null && out.assurances != null) {
        onPatch("assurances", out.assurances);
      }
      await onRefresh();
    } catch (e) {
      setErr(`Estimation IA échouée : ${(e as Error).message}`);
    } finally {
      setEstimating(false);
    }
  }

  function setPrixLoyer(typo: string, v: string) {
    const next = { ...prixLoyers, [typo]: v };
    setPrixLoyers(next);
    const asJson: Record<string, number> = {};
    for (const [k, val] of Object.entries(next)) {
      const num = Number(val);
      if (Number.isFinite(num) && num > 0) asJson[k] = num;
    }
    onPatch("loyers_projetes_json", JSON.stringify(asJson));
  }

  function setLoyerAbordable(v: string) {
    setLoyerAbord(v);
    const num = Number(v);
    onPatch(
      "loyers_max_abordabilite_json",
      JSON.stringify(Number.isFinite(num) && num > 0 ? { abordable: num } : {})
    );
  }

  async function launchAnalysis() {
    setErr(null);
    if (missingRequired.length > 0) {
      setErr(
        `Champs obligatoires manquants : ${missingRequired.join(", ")}.`
      );
      return;
    }
    setRunning(true);
    try {
      const r = await authedFetch(
        `/api/v1/lead-analyses/${data.id}/run-financial-analysis`,
        { method: "POST" }
      );
      if (!r.ok) {
        const t = await r.text().catch(() => "");
        throw new Error(t.slice(0, 240) || `HTTP ${r.status}`);
      }
      await onRefresh();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setRunning(false);
    }
  }

  return (
    <section className="rounded-xl border border-accent-500/30 bg-accent-500/5 p-4">
      <div className="flex items-center gap-2">
        <Sparkles className="h-4 w-4 text-accent-500" />
        <h3 className="text-xs font-semibold uppercase tracking-wider text-accent-500">
          Analyse financière — inputs manuels
        </h3>
      </div>

      {missingRequired.length > 0 ? (
        <div className="mt-2 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-[11px]">
          <p className="text-rose-300">
            ⚠ Obligatoires manquants :{" "}
            <strong>{missingRequired.join(", ")}</strong>. Complète-les
            dans la section ci-dessus avant de lancer l&apos;analyse.
          </p>
          {missingEstimable.length > 0 ? (
            <div className="mt-1.5 flex items-center gap-2">
              <button
                type="button"
                onClick={() => void estimateExpenses()}
                disabled={estimating}
                className="inline-flex items-center gap-1.5 rounded-md border border-amber-400/50 bg-amber-500/15 px-2 py-1 text-[11px] font-semibold text-amber-200 hover:bg-amber-500/25 disabled:opacity-50"
                title="Estimer avec l'IA (taxes muni, taxes scol, assurances)"
              >
                {estimating ? (
                  <Loader2 className="h-3 w-3 animate-spin" />
                ) : (
                  <Sparkles className="h-3 w-3" />
                )}
                Estimer avec l&apos;IA : {missingEstimable.join(", ")}
              </button>
            </div>
          ) : null}
        </div>
      ) : null}

      {missingRequired.length === 0 && missingRecommended.length > 0 ? (
        <p className="mt-2 rounded-lg border border-white/10 bg-white/[0.03] px-3 py-2 text-[11px] text-white/60">
          ℹ Informations recommandées non saisies (l&apos;analyse peut
          quand même se lancer) :{" "}
          <strong className="text-white/80">
            {missingRecommended.join(", ")}
          </strong>
          .
        </p>
      ) : null}

      {/* Inputs avec défaut */}
      <div className="mt-3 grid gap-3 sm:grid-cols-4">
        <FieldNumber
          label="TGA (%)"
          value={data.tga_pct ?? 4}
          onSave={(v) => onPatch("tga_pct", v ?? 4)}
          format="percent"
        />
        <FieldNumber
          label="Taux intérêt achat (%)"
          value={data.taux_interet_achat_pct ?? 4}
          onSave={(v) => onPatch("taux_interet_achat_pct", v ?? 4)}
          format="percent"
        />
        <FieldNumber
          label="MDF prêteur B (%)"
          value={data.mdf_preteur_b_pct ?? 25}
          onSave={(v) => onPatch("mdf_preteur_b_pct", v ?? 25)}
          format="percent"
        />
        <FieldYesNo
          label="Wifi inclus refi"
          value={data.ajout_wifi ?? true}
          onSave={(v) => onPatch("ajout_wifi", v)}
        />
      </div>

      {/* Inputs purement manuels */}
      <div className="mt-3 grid gap-3 sm:grid-cols-3">
        <FieldNumber
          label="Logements ajoutés refi"
          value={data.nb_logements_ajoutes}
          onSave={(v) => onPatch("nb_logements_ajoutes", v)}
        />
        <FieldNumber
          label="Thermopompes ajoutées"
          value={data.nb_thermopompes_ajoutees}
          onSave={(v) => onPatch("nb_thermopompes_ajoutees", v)}
        />
        <FieldNumber
          label="% réduction énergie"
          value={data.reduction_energie_pct}
          onSave={(v) => onPatch("reduction_energie_pct", v)}
          format="percent"
        />
        <FieldNumber
          label="Taux d'intérêt refi (%)"
          value={data.taux_interet_refi_pct}
          onSave={(v) => onPatch("taux_interet_refi_pct", v)}
          format="percent"
        />
        <FieldNumber
          label="Durée projet (années)"
          value={data.duree_projet_annees}
          onSave={(v) => onPatch("duree_projet_annees", v)}
        />
        <FieldNumber
          label="Frais développement ($)"
          value={data.frais_developpement}
          onSave={(v) => onPatch("frais_developpement", v)}
          format="money"
        />
        <FieldNumber
          label="Frais négociations ($)"
          value={data.frais_negociations}
          onSave={(v) => onPatch("frais_negociations", v)}
          format="money"
        />
        <FieldNumber
          label="Frais travaux ($)"
          value={data.travaux_estimes}
          onSave={(v) => onPatch("travaux_estimes", v)}
          format="money"
        />
        <FieldNumber
          label="Loyer abordable (APH SELECT)"
          value={loyerAbord ? Number(loyerAbord) : null}
          onSave={(v) => setLoyerAbordable(v == null ? "" : String(v))}
        />
      </div>

      {/* Prix loyers projetés par typologie (H6..H12, où G > 0) */}
      <div className="mt-3">
        <p className="text-[11px] font-semibold uppercase tracking-wider text-white/50">
          Loyers projetés par typologie (uniquement où la quantité &gt; 0)
        </p>
        <div className="mt-1 grid gap-2 sm:grid-cols-3">
          {TYPOLOGY_KEYS.filter((k) => (typology[k] || 0) > 0).map((k) => (
            <div key={k}>
              <label className="text-[10px] uppercase tracking-wider text-white/50">
                {k} ({typology[k]} log.) — $/mois
              </label>
              <input
                type="number"
                step="any"
                value={prixLoyers[k] ?? ""}
                onChange={(e) => setPrixLoyer(k, e.target.value)}
                className="input font-mono text-xs"
                placeholder="ex. 1400"
              />
            </div>
          ))}
          {TYPOLOGY_KEYS.filter((k) => (typology[k] || 0) > 0).length === 0 ? (
            <p className="col-span-3 text-[11px] text-white/40">
              Renseigne d&apos;abord la typologie dans les infos extraites
              ci-dessus.
            </p>
          ) : null}
        </div>
      </div>

      {err ? (
        <p className="mt-3 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-[11px] text-rose-300">
          {err}
        </p>
      ) : null}

      {/* Bouton Lancer */}
      <div className="mt-4 flex justify-end">
        <button
          type="button"
          onClick={() => void launchAnalysis()}
          disabled={running || missingRequired.length > 0}
          className="btn-accent inline-flex items-center text-sm disabled:opacity-60"
        >
          {running ? (
            <>
              <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />
              Calcul en cours…
            </>
          ) : (
            <>
              <Flame className="mr-1.5 h-4 w-4" />
              Lancer l&apos;analyse
            </>
          )}
        </button>
      </div>
    </section>
  );
}

function FieldYesNo({
  label,
  value,
  onSave
}: {
  label: string;
  value: boolean;
  onSave: (v: boolean) => void;
}) {
  return (
    <div>
      <label className="text-[10px] uppercase tracking-wider text-white/50">
        {label}
      </label>
      <div className="mt-1 inline-flex rounded-md border border-brand-700 bg-brand-950 p-0.5">
        <button
          type="button"
          onClick={() => onSave(true)}
          className={`rounded px-3 py-1 text-[11px] font-semibold ${
            value ? "bg-emerald-500 text-brand-950" : "text-white/60"
          }`}
        >
          Oui
        </button>
        <button
          type="button"
          onClick={() => onSave(false)}
          className={`rounded px-3 py-1 text-[11px] font-semibold ${
            !value ? "bg-rose-500 text-white" : "text-white/60"
          }`}
        >
          Non
        </button>
      </div>
    </div>
  );
}

// ─── Tableau de résultats post-analyse ─────────────────────────

type ScenarioResult = {
  name: string;
  label: string;
  ltv: number;
  amort_annees: number;
  rcd: number;
  nb_log: number;
  loyer_mois: number;
  revenus_totaux: number;
  depenses_total: number;
  revenus_net: number;
  valeur_eco_tga: number;
  valeur_eco_rcd: number;
  valeur_marchande: number | null;
  valeur_retenue: number;
  financement: number;
  paiement_mensuel_actuel?: number;
  cashflow_annuel?: number;
  mdf_necessaire: number | null;
  equite_a_la_fin: number | null;
};

type FraisDemarrageBreakdown = {
  courtier_hypothecaire_1: number;
  courtier_hypothecaire_2: number;
  taxes_bienvenue: number;
  evaluateur: number;
  evaluateur_2: number;
  inspection: number;
  avocat: number;
  notaire: number;
  notaire_2: number;
  rapport_efficacite: number;
  frais_developpement: number;
  frais_negociations: number;
  frais_travaux: number;
  interets: number;
  revenus_nets_pendant_projet: number;
};

type AnalysisResults = {
  frais_demarrage?: FraisDemarrageBreakdown;
  frais_demarrage_total: number;
  prix_acquisition: number;
  mdf_preteur_b?: number;
  mdf_preteur_b_pct?: number;
  mdf_pct_prix_achat?: number;
  mdf_25pct_prix_achat?: number;
  prix_achat?: number;
  typology: {
    h13_loyer_pondere: number;
    nb_abordables: number;
    nb_pdm: number;
    nouveau_loyer_moyen_pdm: number;
  };
  scenarios: {
    achat: ScenarioResult;
    refi_schl: ScenarioResult;
    refi_aph_50: ScenarioResult;
    refi_aph_100: ScenarioResult | null;
  };
  best_refi: {
    amount: number;
    program: string;
  };
};

function AnalysisResultsTable({
  resultsJson,
  overridesJson,
  financablesJson,
  mdfPct,
  prixAchat,
  fraisDemarrageTotalDb,
  mdfPreteurBDb,
  onPatchOverrides,
  onPatchFinancables
}: {
  resultsJson: string;
  overridesJson?: string | null;
  financablesJson?: string | null;
  mdfPct?: number;
  prixAchat?: number;
  fraisDemarrageTotalDb?: number | null;
  mdfPreteurBDb?: number | null;
  onPatchOverrides?: (json: string) => void;
  onPatchFinancables?: (json: string) => void;
}) {
  const data = useMemo<AnalysisResults | null>(() => {
    try {
      return JSON.parse(resultsJson) as AnalysisResults;
    } catch {
      return null;
    }
  }, [resultsJson]);

  if (!data) return null;

  const cols: Array<[string, ScenarioResult | null]> = [
    ["Achat", data.scenarios.achat],
    ["SCHL standard", data.scenarios.refi_schl],
    ["SCHL Efficacité (50 pts)", data.scenarios.refi_aph_50],
    ["SCHL Abord+Eff (100 pts)", data.scenarios.refi_aph_100]
  ];

  // Détecte si les inputs LIVE divergent du snapshot JSON
  // (mdfPct ou pourcentage de la MDF prêteur B). Si oui, on affiche
  // un bandeau « Re-lancer l'analyse » pour avertir l'utilisateur.
  const jsonPct = data.mdf_preteur_b_pct;
  const jsonPctPercent = jsonPct != null && jsonPct < 1 ? jsonPct * 100 : jsonPct;
  const livePct = mdfPct ?? 25;
  const inputsChanged =
    jsonPctPercent != null && Math.abs(jsonPctPercent - livePct) > 0.01;

  return (
    <section className="rounded-xl border border-emerald-500/30 bg-emerald-500/5 p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-xs font-semibold uppercase tracking-wider text-emerald-300">
          ✓ Résultats de l&apos;analyse financière
        </h3>
        <div className="text-[11px] text-white/70">
          <strong className="text-emerald-300">Best refi</strong> :{" "}
          {fmtMoney(data.best_refi.amount)} —{" "}
          <span className="text-white/60">{data.best_refi.program}</span>
        </div>
      </div>

      <p className="mt-1 text-[10px] text-white/40">
        Frais démarrage : {fmtMoney(data.frais_demarrage_total)} · Prix
        acquisition : {fmtMoney(data.prix_acquisition)} · Loyer pondéré H13 :{" "}
        {fmtMoney(data.typology.h13_loyer_pondere)} /mois
        {data.typology.nb_abordables > 0
          ? ` · ${data.typology.nb_abordables} abord / ${data.typology.nb_pdm} PDM`
          : ""}
      </p>

      {inputsChanged ? (
        <div className="mt-2 rounded-lg border border-amber-400/60 bg-amber-500/15 px-3 py-2 text-[11px] text-amber-200">
          ⚠ Les inputs ont changé depuis la dernière analyse
          (ex. MDF prêteur B : {jsonPctPercent}% → {livePct}%).{" "}
          <strong>Relance l&apos;analyse</strong> pour mettre à jour
          les résultats ci-dessous.
        </div>
      ) : null}

      {/* MDF avec prêteur B — X % du prix d'achat + frais
          démarrage. X paramétrable (défaut 25 %, parfois 35 %). */}
      {data.mdf_preteur_b != null ? (
        <div className="mt-2 rounded-lg border border-amber-400/40 bg-amber-500/10 px-3 py-2">
          <p className="text-[10px] uppercase tracking-wider text-amber-300">
            MDF avec prêteur B
          </p>
          <p className="mt-0.5 text-sm font-bold text-amber-200">
            {fmtMoney(data.mdf_preteur_b)}
          </p>
          <p className="text-[10px] text-white/50">
            {(() => {
              // Priorité au prop `mdfPct` (live depuis la DB).
              // Sinon valeur figée dans le JSON d'analyse.
              const liveOrJson = mdfPct ?? data.mdf_preteur_b_pct ?? 25;
              const pctDisplay =
                liveOrJson < 1
                  ? (liveOrJson * 100).toFixed(0)
                  : liveOrJson.toFixed(0);
              return `${pctDisplay} % × prix d'achat + frais démarrage`;
            })()}
          </p>
        </div>
      ) : null}

      <div className="mt-3 overflow-x-auto">
        <table className="w-full min-w-[640px] text-[11px]">
          <thead>
            <tr className="text-white/40">
              <th className="px-2 py-1 text-left">Métrique</th>
              {cols.map(([label, s]) => (
                <th key={label} className="px-2 py-1 text-right">
                  {label}
                  {s ? (
                    <span className="ml-1 text-white/30">
                      ({(s.ltv * 100).toFixed(0)}% · {s.amort_annees}ans · RCD{" "}
                      {s.rcd.toFixed(2)})
                    </span>
                  ) : null}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            <ResultRow
              label="Loyer moyen ($/mois)"
              cols={cols}
              pick={(s) => s.loyer_mois}
            />
            <ResultRow
              label="Revenus totaux ($/an)"
              cols={cols}
              pick={(s) => s.revenus_totaux}
            />
            <ResultRow
              label="Dépenses totales"
              cols={cols}
              pick={(s) => s.depenses_total}
            />
            <ResultRow
              label="Revenus net"
              cols={cols}
              pick={(s) => s.revenus_net}
            />
            <ResultRow
              label="Valeur éco RDC"
              cols={cols}
              pick={(s) => s.valeur_eco_rcd}
            />
            <ResultRow
              label="Valeur éco TGA"
              cols={cols}
              pick={(s) => s.valeur_eco_tga}
            />
            <ResultRow
              label="Valeur marchande"
              cols={cols}
              pick={(s) => s.valeur_marchande}
              fallback="—"
            />
            <ResultRow
              label="Valeur retenue"
              cols={cols}
              pick={(s) => s.valeur_retenue}
              bold
            />
            <ResultRow
              label="Prêt accordé"
              cols={cols}
              pick={(s) => s.financement}
              bold
            />
            <ResultRow
              label="MDF nécessaire"
              cols={cols}
              pick={(s) => s.mdf_necessaire}
              fallback="N/A"
            />
            <ResultRow
              label="Cashflow annuel"
              cols={cols}
              pick={(s) => s.cashflow_annuel}
              fallback="N/A"
              colorEquite
            />
            <ResultRow
              label="Équité à la fin"
              cols={cols}
              pick={(s) => s.equite_a_la_fin}
              fallback="N/A"
              colorEquite
            />
          </tbody>
        </table>
      </div>

      <FraisDemarrageBreakdownPanel
        data={data}
        overridesJson={overridesJson}
        financablesJson={financablesJson}
        mdfPct={mdfPct}
        prixAchat={prixAchat}
        mdfPreteurBDb={mdfPreteurBDb}
        onPatchOverrides={onPatchOverrides}
        onPatchFinancables={onPatchFinancables}
      />
    </section>
  );
}

// ─── Détail des frais de démarrage + composition de la MDF ─────

const FRAIS_LABELS: Array<[keyof FraisDemarrageBreakdown, string]> = [
  ["courtier_hypothecaire_1", "Courtier hypothécaire (1 % × prix d'achat)"],
  ["courtier_hypothecaire_2", "Courtier hypothécaire 2 (1 % × financement APH)"],
  ["taxes_bienvenue", "Taxes de bienvenue (Montréal, tiers progressifs)"],
  ["evaluateur", "Évaluateur agréé"],
  ["evaluateur_2", "Évaluateur agréé 2"],
  ["inspection", "Inspection"],
  ["avocat", "Avocat"],
  ["notaire", "Notaire"],
  ["notaire_2", "Notaire 2"],
  ["rapport_efficacite", "Rapport d'efficacité énergétique"],
  ["frais_developpement", "Frais de développement"],
  ["frais_negociations", "Frais de négociations"],
  ["frais_travaux", "Travaux estimés"],
  ["interets", "Intérêts pendant projet (75 % × prix × 8 % × durée)"],
  ["revenus_nets_pendant_projet", "Revenus nets pendant projet (négatif)"]
];

const DEFAULT_FINANCABLES = [
  "rapport_efficacite",
  "frais_developpement",
  "frais_travaux"
];

function FraisDemarrageBreakdownPanel({
  data,
  overridesJson,
  financablesJson,
  mdfPct,
  prixAchat,
  mdfPreteurBDb,
  onPatchOverrides,
  onPatchFinancables
}: {
  data: AnalysisResults;
  overridesJson?: string | null;
  financablesJson?: string | null;
  mdfPct?: number;
  prixAchat?: number;
  mdfPreteurBDb?: number | null;
  onPatchOverrides?: (json: string) => void;
  onPatchFinancables?: (json: string) => void;
}) {
  const frais = data.frais_demarrage;
  const mdfPctFinal = mdfPct ?? data.mdf_preteur_b_pct ?? 25;
  const mdfPctNumeric =
    mdfPctFinal > 1 ? mdfPctFinal / 100 : mdfPctFinal; // tolère fraction ou %
  const prixFinal = prixAchat ?? data.prix_achat ?? 0;
  const mdfPctValue =
    data.mdf_pct_prix_achat ?? data.mdf_25pct_prix_achat ?? mdfPctNumeric * prixFinal;
  const mdfTotalStored = mdfPreteurBDb ?? data.mdf_preteur_b ?? null;

  const overrides = useMemo<Record<string, number>>(() => {
    if (!overridesJson) return {};
    try {
      const j = JSON.parse(overridesJson);
      if (j && typeof j === "object") return j as Record<string, number>;
    } catch {
      /* ignore */
    }
    return {};
  }, [overridesJson]);

  // Set des clés finançables (= payées seulement à mdfPct % en cash).
  // Si le JSON est invalide ou absent → défauts (rapport eff, dev,
  // travaux).
  const financables = useMemo<Set<string>>(() => {
    if (financablesJson) {
      try {
        const j = JSON.parse(financablesJson);
        if (Array.isArray(j)) return new Set(j.map((x) => String(x)));
      } catch {
        /* ignore */
      }
    }
    return new Set(DEFAULT_FINANCABLES);
  }, [financablesJson]);

  function toggleFinancable(key: string) {
    const next = new Set(financables);
    if (next.has(key)) next.delete(key);
    else next.add(key);
    onPatchFinancables?.(JSON.stringify(Array.from(next)));
  }

  function setOverride(key: string, val: number | null) {
    const next = { ...overrides };
    if (val == null || !Number.isFinite(val)) {
      delete next[key];
    } else {
      next[key] = val;
    }
    onPatchOverrides?.(JSON.stringify(next));
  }

  // Calcule le sous-total local (en appliquant les overrides ET la
  // logique finançable : un poste coché ne compte que mdfPct % en
  // cash). Affiche le bon total même si le moteur n'a pas re-roulé.
  let subTotalCash = 0;
  let subTotalFinanced = 0;
  if (frais) {
    for (const [k] of FRAIS_LABELS) {
      const v =
        overrides[k] != null ? Number(overrides[k]) : Number(frais[k] || 0);
      if (!Number.isFinite(v)) continue;
      if (financables.has(k)) {
        subTotalCash += v * mdfPctNumeric;
        subTotalFinanced += v * (1 - mdfPctNumeric);
      } else {
        subTotalCash += v;
      }
    }
  }
  const totalMdfLocal = mdfPctValue + subTotalCash;

  if (!frais) return null;

  return (
    <section className="mt-4 rounded-lg border border-amber-400/30 bg-amber-500/5 p-4">
      <h4 className="text-xs font-semibold uppercase tracking-wider text-amber-300">
        Composition de la MDF avec prêteur B
      </h4>
      <p className="mt-0.5 text-[10px] text-white/50">
        Total à sortir en cash = {mdfPctFinal} % du prix d&apos;achat +
        frais non finançables + {mdfPctFinal} % des frais finançables.
        Coche un poste pour le rendre finançable par le prêteur B
        (par défaut : rapport efficacité, frais développement, travaux).
      </p>

      <table className="mt-3 w-full text-[11px]">
        <thead>
          <tr className="text-[9px] uppercase tracking-wider text-white/40">
            <th className="px-2 py-1 text-left">Poste</th>
            <th className="px-2 py-1 text-right">Valeur</th>
            <th className="w-16 px-2 py-1 text-center" title="Coché = ce poste est financé par le prêteur B, tu ne paies que le pct en cash">
              Finançable
            </th>
            <th className="px-2 py-1 text-right">Cash à sortir</th>
          </tr>
        </thead>
        <tbody>
          <tr className="border-t border-amber-400/20">
            <td className="px-2 py-1 font-semibold text-amber-200" colSpan={3}>
              {mdfPctFinal} % du prix d&apos;achat
              {prixFinal > 0 ? (
                <span className="ml-1 text-white/50">
                  ({mdfPctFinal} % × {fmtMoney(prixFinal)})
                </span>
              ) : null}
            </td>
            <td className="px-2 py-1 text-right font-mono tabular-nums font-semibold text-amber-200">
              {fmtMoney(mdfPctValue)}
            </td>
          </tr>
          <tr className="border-t border-amber-400/20">
            <td className="px-2 py-1 text-white/50" colSpan={4}>
              <span className="text-[10px] uppercase tracking-wider">
                Frais de démarrage
              </span>
            </td>
          </tr>
          {FRAIS_LABELS.map(([key, label]) => {
            const computed = Number(frais[key] || 0);
            const overridden = overrides[key] != null;
            const displayVal = overridden
              ? Number(overrides[key])
              : computed;
            if (!overridden && !computed) return null;
            const isFinancable = financables.has(key);
            const cashForRow = isFinancable
              ? displayVal * mdfPctNumeric
              : displayVal;
            return (
              <tr key={key} className="border-t border-brand-800/60">
                <td className="px-2 py-1 pl-4 text-white/60">
                  {label}
                  {overridden ? (
                    <button
                      type="button"
                      onClick={() => setOverride(key, null)}
                      className="ml-1 rounded bg-amber-500/20 px-1 py-0 text-[9px] text-amber-200 hover:bg-amber-500/30"
                      title="Réinitialiser à la valeur calculée"
                    >
                      override · réinit
                    </button>
                  ) : null}
                </td>
                <td className="px-2 py-1 text-right">
                  <EditableMoney
                    value={displayVal}
                    computed={computed}
                    overridden={overridden}
                    onSave={(v) =>
                      setOverride(key, v === computed ? null : v)
                    }
                  />
                </td>
                <td className="px-2 py-1 text-center">
                  <input
                    type="checkbox"
                    checked={isFinancable}
                    onChange={() => toggleFinancable(key)}
                    className="h-3.5 w-3.5 cursor-pointer accent-amber-400"
                    title={
                      isFinancable
                        ? `Finançable — payé seulement à ${mdfPctFinal} % en cash`
                        : "Non finançable — payé 100 % en cash"
                    }
                  />
                </td>
                <td
                  className={`px-2 py-1 text-right font-mono tabular-nums ${
                    isFinancable ? "text-emerald-300" : "text-white/80"
                  }`}
                >
                  {fmtMoney(cashForRow)}
                </td>
              </tr>
            );
          })}
          <tr className="border-t border-amber-400/40 bg-amber-500/5">
            <td
              className="px-2 py-1 pl-4 text-amber-200"
              colSpan={3}
            >
              Sous-total frais de démarrage (cash)
            </td>
            <td className="px-2 py-1 text-right font-mono tabular-nums font-semibold text-amber-200">
              {fmtMoney(subTotalCash)}
            </td>
          </tr>
          {subTotalFinanced > 0.5 ? (
            <tr className="bg-emerald-500/5">
              <td
                className="px-2 py-1 pl-4 text-[10px] text-emerald-300"
                colSpan={3}
              >
                dont financé par prêteur B
              </td>
              <td className="px-2 py-1 text-right font-mono tabular-nums text-[10px] text-emerald-300">
                +{fmtMoney(subTotalFinanced)}
              </td>
            </tr>
          ) : null}
          <tr className="border-t-2 border-amber-400/60 bg-amber-500/10">
            <td
              className="px-2 py-1.5 font-bold text-amber-200"
              colSpan={3}
            >
              Total — MDF avec prêteur B
              {mdfTotalStored != null &&
              Math.abs((mdfTotalStored || 0) - totalMdfLocal) > 1 ? (
                <span className="ml-2 rounded bg-amber-500/30 px-1 py-0 text-[9px] font-normal text-amber-100">
                  recalcul requis
                </span>
              ) : null}
            </td>
            <td className="px-2 py-1.5 text-right font-mono tabular-nums font-bold text-amber-200">
              {fmtMoney(totalMdfLocal)}
            </td>
          </tr>
        </tbody>
      </table>
    </section>
  );
}

function EditableMoney({
  value,
  computed,
  overridden,
  onSave
}: {
  value: number;
  computed: number;
  overridden: boolean;
  onSave: (v: number) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(String(Math.round(value)));
  useEffect(() => {
    if (!editing) setDraft(String(Math.round(value)));
  }, [value, editing]);

  if (editing) {
    return (
      <input
        autoFocus
        type="number"
        value={draft}
        step="1"
        onChange={(e) => setDraft(e.target.value)}
        onBlur={() => {
          setEditing(false);
          const n = Number(draft);
          if (Number.isFinite(n)) onSave(n);
        }}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            const n = Number(draft);
            if (Number.isFinite(n)) onSave(n);
            setEditing(false);
          } else if (e.key === "Escape") {
            setEditing(false);
            setDraft(String(Math.round(computed)));
          }
        }}
        className="w-28 rounded border border-amber-400/40 bg-brand-950 px-1 py-0.5 text-right font-mono text-[11px] text-white focus:border-accent-500 focus:outline-none"
      />
    );
  }
  return (
    <button
      type="button"
      onClick={() => setEditing(true)}
      title={
        overridden
          ? `Manuel (calcul auto : ${fmtMoney(computed)}). Clique pour modifier.`
          : "Clique pour overrider"
      }
      className={`font-mono tabular-nums hover:underline ${
        overridden ? "text-amber-200 font-semibold" : "text-white/80"
      }`}
    >
      {fmtMoney(value)}
    </button>
  );
}

function ResultRow({
  label,
  cols,
  pick,
  bold,
  fallback,
  colorEquite
}: {
  label: string;
  cols: Array<[string, ScenarioResult | null]>;
  pick: (s: ScenarioResult) => number | null | undefined;
  bold?: boolean;
  fallback?: string;
  colorEquite?: boolean;
}) {
  return (
    <tr className="border-t border-brand-800/60">
      <td className="px-2 py-1 text-white/60">{label}</td>
      {cols.map(([k, s]) => {
        if (!s) return (
          <td key={k} className="px-2 py-1 text-right text-white/30">—</td>
        );
        const val = pick(s);
        if (val == null) return (
          <td key={k} className="px-2 py-1 text-right text-white/30">
            {fallback || "—"}
          </td>
        );
        const txt = fmtMoney(val);
        const tone = colorEquite
          ? val >= 0
            ? "text-emerald-300"
            : "text-rose-300"
          : bold
            ? "text-white"
            : "text-white/80";
        return (
          <td
            key={k}
            className={`px-2 py-1 text-right font-mono tabular-nums ${tone} ${bold ? "font-bold" : ""}`}
          >
            {txt}
          </td>
        );
      })}
    </tr>
  );
}
