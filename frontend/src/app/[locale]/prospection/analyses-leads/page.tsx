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
  type_batiment: string | null;
  converted_to_lead_id: number | null;
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
  if (Math.abs(n) >= 1_000_000) return `${(n / 1_000_000).toFixed(2)} M$`;
  if (Math.abs(n) >= 1_000) return `${(n / 1_000).toFixed(0)} k$`;
  return `${Math.round(n)} $`;
}

function fmtDate(iso: string): string {
  return new Date(iso).toLocaleDateString("fr-CA", {
    month: "short",
    day: "2-digit"
  });
}

export default function AnalysesLeadsPage() {
  const router = useRouter();
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
      title: `Convertir « ${label} » en lead du Pipeline ?`,
      description:
        "Un nouveau lead sera créé dans Suivi de leads (statut « À contacter »). Le lien sera conservé sur la fiche d'analyse.",
      confirmLabel: "Convertir"
    });
    if (!ok) return;
    try {
      const r = await authedFetch(
        `/api/v1/lead-analyses/${id}/convert-to-lead`,
        { method: "POST" }
      );
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const j = (await r.json()) as { lead_id: number };
      void reload();
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      router.push(`/prospection/${j.lead_id}` as any);
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
  );
}

// ─── Card kanban ────────────────────────────────────────────────

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
          <span className="inline-flex items-center gap-0.5 text-emerald-300">
            <Flame className="h-2.5 w-2.5" /> refi{" "}
            {fmtMoney(lead.best_refi_amount)}
          </span>
        ) : null}
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
          disabled={!!lead.converted_to_lead_id}
          className="inline-flex items-center gap-1 rounded-md border border-emerald-500/30 bg-emerald-500/10 px-1.5 py-0.5 text-[10px] text-emerald-300 hover:bg-emerald-500/20 disabled:opacity-50"
          title={
            lead.converted_to_lead_id
              ? "Déjà converti"
              : "Convertir en lead Pipeline"
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
                    disabled={!!l.converted_to_lead_id}
                    className="rounded-md border border-emerald-500/30 p-1 text-emerald-300 hover:bg-emerald-500/10 disabled:opacity-50"
                    title="Convertir en lead Pipeline"
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
  attachments: Array<{
    id: number;
    filename: string;
    content_type: string;
    size_bytes: number;
  }>;
};

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
                  />
                  <FieldText
                    label="Ville"
                    value={data.city}
                    onSave={(v) => patchField("city", v)}
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
                    value={data.asking_price}
                    onSave={(v) => patchField("asking_price", v)}
                  />
                  <FieldNumber
                    label="Année construction"
                    value={data.annee_construction}
                    onSave={(v) => patchField("annee_construction", v)}
                  />
                  <FieldNumber
                    label="Nb logements"
                    value={data.nb_logements}
                    onSave={(v) => patchField("nb_logements", v)}
                  />
                  <FieldNumber
                    label="Nb stationnements"
                    value={data.nb_stationnements}
                    onSave={(v) => patchField("nb_stationnements", v)}
                  />
                  <FieldNumber
                    label="Revenus bruts ($/an)"
                    value={data.revenus_bruts}
                    onSave={(v) => patchField("revenus_bruts", v)}
                  />
                  <FieldNumber
                    label="Évaluation municipale ($)"
                    value={data.evaluation_municipale}
                    onSave={(v) => patchField("evaluation_municipale", v)}
                  />
                  <FieldNumber
                    label="Taxes municipales ($/an)"
                    value={data.taxes_municipales}
                    onSave={(v) => patchField("taxes_municipales", v)}
                  />
                  <FieldNumber
                    label="Taxes scolaires ($/an)"
                    value={data.taxes_scolaires}
                    onSave={(v) => patchField("taxes_scolaires", v)}
                  />
                  <FieldNumber
                    label="Assurances ($/an)"
                    value={data.assurances}
                    onSave={(v) => patchField("assurances", v)}
                  />
                  <FieldNumber
                    label="Énergie ($/an)"
                    value={data.energie}
                    onSave={(v) => patchField("energie", v)}
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

                {typology ? (
                  <div className="mt-3">
                    <p className="text-[11px] font-semibold uppercase tracking-wider text-white/50">
                      Typologie des logements
                    </p>
                    <div className="mt-1 flex flex-wrap gap-2">
                      {Object.entries(typology).map(([k, v]) =>
                        v ? (
                          <span
                            key={k}
                            className="rounded-full bg-brand-800 px-2 py-0.5 text-[11px] text-white/70"
                          >
                            <span className="font-mono">{k}</span> ×{" "}
                            <strong>{v}</strong>
                          </span>
                        ) : null
                      )}
                    </div>
                  </div>
                ) : null}

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
                        <a
                          key={a.id}
                          href={`/api/v1/lead-analyses/${id}/attachments/${a.id}`}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="block overflow-hidden rounded-md border border-brand-800 bg-brand-950 hover:border-accent-500"
                          title={a.filename}
                        >
                          {a.content_type.startsWith("image/") ? (
                            // eslint-disable-next-line @next/next/no-img-element
                            <img
                              src={`/api/v1/lead-analyses/${id}/attachments/${a.id}`}
                              alt={a.filename}
                              className="h-24 w-full object-cover"
                            />
                          ) : (
                            <div className="flex h-24 items-center justify-center text-3xl text-white/30">
                              📄
                            </div>
                          )}
                          <p className="truncate px-2 py-1 text-[10px] text-white/60">
                            {a.filename}
                          </p>
                        </a>
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

              {/* Section Analyse financière — Phase 3 placeholder */}
              <section className="rounded-xl border border-dashed border-amber-400/30 bg-amber-500/5 p-4">
                <div className="flex items-center gap-2">
                  <Pause className="h-4 w-4 text-amber-300" />
                  <h3 className="text-xs font-semibold uppercase tracking-wider text-amber-300">
                    Analyse financière — à venir
                  </h3>
                </div>
                <p className="mt-1 text-xs text-white/60">
                  Phase 3 du projet : moteur de calcul qui réplique tes
                  Excels (avec / sans abordabilité), bouton « Lancer
                  l&apos;analyse », résultats cashflow + TGA + scénarios
                  de refi.
                </p>
              </section>

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

function FieldText({
  label,
  value,
  onSave
}: {
  label: string;
  value: string | null;
  onSave: (v: string | null) => void;
}) {
  const [v, setV] = useState(value || "");
  useEffect(() => setV(value || ""), [value]);
  const isEmpty = !value;
  return (
    <div>
      <label
        className={`text-[10px] uppercase tracking-wider ${
          isEmpty ? "text-amber-300/80" : "text-white/50"
        }`}
      >
        {label}
        {isEmpty ? " ⚠" : ""}
      </label>
      <input
        type="text"
        value={v}
        onChange={(e) => setV(e.target.value)}
        onBlur={() => {
          if ((value || "") !== v) onSave(v.trim() || null);
        }}
        className="input mt-1 text-xs"
      />
    </div>
  );
}

function FieldNumber({
  label,
  value,
  onSave
}: {
  label: string;
  value: number | null;
  onSave: (v: number | null) => void;
}) {
  const [v, setV] = useState(value != null ? String(value) : "");
  useEffect(() => setV(value != null ? String(value) : ""), [value]);
  const isEmpty = value == null;
  return (
    <div>
      <label
        className={`text-[10px] uppercase tracking-wider ${
          isEmpty ? "text-amber-300/80" : "text-white/50"
        }`}
      >
        {label}
        {isEmpty ? " ⚠" : ""}
      </label>
      <input
        type="number"
        step="any"
        value={v}
        onChange={(e) => setV(e.target.value)}
        onBlur={() => {
          const num = v.trim() === "" ? null : Number(v);
          if (num !== value) onSave(Number.isFinite(num as number) ? num : null);
        }}
        className="input mt-1 font-mono text-xs"
      />
    </div>
  );
}
