"use client";

import { useEffect, useMemo, useState } from "react";
import {
  FileText,
  GripVertical,
  Loader2,
  Mail,
  Phone,
  Plus,
  Trash2,
  X
} from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { AddressInput } from "@/components/address-input";
import { useDevlogLayout } from "../layout";
import { authedFetch } from "@/lib/auth";
import { useConfirm } from "@/components/confirm-dialog";
import { Link, useRouter } from "@/i18n/navigation";
import { formatPhone } from "@/lib/utils";

// CLONE 1:1 de la page Construction `/app/crm/page.tsx`, branchée sur
// les endpoints `/api/v1/devlog/leads`. Mêmes colonnes, mêmes patterns
// de carte, même modal de création. Seules différences : le type de
// projet (catalogue dev IA au lieu de rénovation) et la cible des
// liens (`/dev-logiciel/...`).

type Lead = {
  id: number;
  name: string;
  email: string | null;
  phone: string | null;
  address: string | null;
  project_type: string;
  budget_range: string | null;
  // Côté DB le champ s'appelle encore `project_summary` ; on l'utilise
  // tel quel (équivalent fonctionnel de `message` côté ContactRequest).
  project_summary: string | null;
  locale: string;
  source: string | null;
  status: string;
  kanban_column: string | null;
  created_at: string;
};

type Column = { id: string; label: string; dot: string; custom?: boolean };

// Colonnes par défaut — alignement direct sur la page CRM Construction.
const DEFAULT_COLUMNS: Column[] = [
  { id: "new", label: "Nouveaux", dot: "bg-emerald-400" },
  { id: "contacted", label: "Suivi à faire", dot: "bg-amber-400" },
  { id: "qualified", label: "Soumission en préparation", dot: "bg-fuchsia-400" },
  { id: "quoted", label: "Soumission envoyée", dot: "bg-blue-400" },
  { id: "won", label: "Acceptée", dot: "bg-green-500" },
  { id: "lost", label: "Refusée", dot: "bg-rose-500" }
];

const DOTS = [
  "bg-emerald-400",
  "bg-amber-400",
  "bg-blue-400",
  "bg-fuchsia-400",
  "bg-sky-400",
  "bg-rose-400",
  "bg-teal-400"
];

function translateBackendError(raw: string, status: number): string {
  const lower = raw.toLowerCase();
  if (lower.includes("not a valid email") || lower.includes("email_address")) {
    return "Le courriel n'est pas valide.";
  }
  if (lower.includes("at least") && lower.includes("character")) {
    return "Un champ obligatoire est trop court.";
  }
  if (lower.includes("field required") || lower.includes("missing")) {
    return "Un champ obligatoire est manquant.";
  }
  if (status === 401 || status === 403) {
    return "Action non autorisée. Vérifie ta connexion.";
  }
  return `Création échouée (HTTP ${status}).`;
}

// Catalogue de projets dev IA — équivalent du PROJECT_LABEL Construction.
const PROJECT_LABEL: Record<string, string> = {
  web_app: "Application web",
  mobile_app: "Application mobile",
  automation: "Automatisation",
  integration: "Intégration",
  consulting: "Consultation",
  autre: "Autre"
};

const CUSTOM_COLS_KEY = "devlog_crm_custom_columns_v1";

function loadCustomColumns(): Column[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(CUSTOM_COLS_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as Column[];
    return parsed.map((c, i) => ({
      ...c,
      custom: true,
      dot: c.dot || DOTS[i % DOTS.length]
    }));
  } catch {
    return [];
  }
}

function saveCustomColumns(cols: Column[]) {
  try {
    window.localStorage.setItem(CUSTOM_COLS_KEY, JSON.stringify(cols));
  } catch {
    /* ignore */
  }
}

export default function DevlogCrmPage() {
  const confirm = useConfirm();
  const { onOpenSidebar } = useDevlogLayout();
  const router = useRouter();
  const [items, setItems] = useState<Lead[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [dragging, setDragging] = useState<number | null>(null);
  const [hoverCol, setHoverCol] = useState<string | null>(null);
  const [customColumns, setCustomColumns] = useState<Column[]>([]);
  const [createOpen, setCreateOpen] = useState(false);

  useEffect(() => {
    setCustomColumns(loadCustomColumns());
  }, []);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const res = await authedFetch("/api/v1/devlog/leads?limit=500");
        if (!res.ok) throw new Error(`http_${res.status}`);
        const data = (await res.json()) as Lead[];
        if (!cancelled) setItems(data);
      } catch {
        if (!cancelled) setError("Impossible de charger les prospects.");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, []);

  const columns = useMemo(
    () => [...DEFAULT_COLUMNS, ...customColumns],
    [customColumns]
  );

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return items;
    return items.filter(
      (p) =>
        p.name.toLowerCase().includes(q) ||
        (p.email || "").toLowerCase().includes(q) ||
        (p.phone || "").includes(q)
    );
  }, [items, search]);

  const byColumn = useMemo(() => {
    const map: Record<string, Lead[]> = Object.fromEntries(
      columns.map((c) => [c.id, [] as Lead[]])
    );
    for (const p of filtered) {
      const col =
        p.kanban_column && columns.find((c) => c.id === p.kanban_column)
          ? p.kanban_column
          : columns.find((c) => c.id === p.status)
          ? p.status
          : "new";
      map[col].push(p);
    }
    return map;
  }, [filtered, columns]);

  async function moveLead(id: number, target: Column) {
    const prev = items;
    setItems((xs) =>
      xs.map((x) =>
        x.id === id
          ? {
              ...x,
              status: target.custom ? x.status : target.id,
              kanban_column: target.custom ? target.id : null
            }
          : x
      )
    );
    try {
      const body: Record<string, string | null> = target.custom
        ? { kanban_column: target.id }
        : { status: target.id, kanban_column: null };
      const res = await authedFetch(`/api/v1/devlog/leads/${id}`, {
        method: "PATCH",
        body: JSON.stringify(body)
      });
      if (!res.ok) throw new Error();
    } catch {
      setItems(prev);
      setError("Mise à jour échouée.");
    }
  }

  async function deleteLead(id: number, name: string) {
    if (!(await confirm(`Supprimer définitivement le prospect « ${name} » ?`))) return;
    const prev = items;
    setItems((xs) => xs.filter((x) => x.id !== id));
    try {
      const res = await authedFetch(`/api/v1/devlog/leads/${id}`, {
        method: "DELETE"
      });
      if (!res.ok) throw new Error();
    } catch {
      setItems(prev);
      setError("Suppression échouée.");
    }
  }

  function addCustomColumn() {
    const label = prompt("Nom de la nouvelle colonne :");
    if (!label || !label.trim()) return;
    const id = `custom_${Date.now()}`;
    const next = [
      ...customColumns,
      {
        id,
        label: label.trim(),
        dot: DOTS[customColumns.length % DOTS.length],
        custom: true
      }
    ];
    setCustomColumns(next);
    saveCustomColumns(next);
  }

  function renameCustomColumn(colId: string) {
    const col = customColumns.find((c) => c.id === colId);
    if (!col) return;
    const label = prompt("Nouveau nom :", col.label);
    if (!label || !label.trim() || label === col.label) return;
    const next = customColumns.map((c) =>
      c.id === colId ? { ...c, label: label.trim() } : c
    );
    setCustomColumns(next);
    saveCustomColumns(next);
  }

  async function removeCustomColumn(colId: string) {
    const col = customColumns.find((c) => c.id === colId);
    if (!col) return;
    const affected = items.filter((p) => p.kanban_column === colId);
    if (
      !confirm(
        `Supprimer la colonne « ${col.label} » ? Les ${affected.length} prospect${
          affected.length > 1 ? "s" : ""
        } qu'elle contient retournent dans la colonne par statut.`
      )
    )
      return;
    const next = customColumns.filter((c) => c.id !== colId);
    setCustomColumns(next);
    saveCustomColumns(next);
    for (const p of affected) {
      try {
        await authedFetch(`/api/v1/devlog/leads/${p.id}`, {
          method: "PATCH",
          body: JSON.stringify({ kanban_column: null })
        });
      } catch {
        /* ignore */
      }
    }
    setItems((xs) =>
      xs.map((x) =>
        x.kanban_column === colId ? { ...x, kanban_column: null } : x
      )
    );
  }

  async function startSoumission(p: Lead) {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    router.push(`/dev-logiciel/soumissions?lead_id=${p.id}` as any);
  }

  function onDragStart(id: number) {
    setDragging(id);
  }
  function onDragEnd() {
    setDragging(null);
    setHoverCol(null);
  }
  function onDropToColumn(col: Column) {
    if (dragging == null) return;
    const item = items.find((p) => p.id === dragging);
    if (item) {
      const currentCol = item.kanban_column || item.status;
      if (currentCol !== col.id) moveLead(dragging, col);
    }
    setDragging(null);
    setHoverCol(null);
  }

  return (
    <>
      <AppTopbar
        breadcrumbs={[
          { label: "Développement logiciel", href: "/dev-logiciel" as any },
          { label: "CRM / Prospects" }
        ]}
        onOpenSidebar={onOpenSidebar}
        onSearch={setSearch}
        searchPlaceholder="Rechercher un prospect…"
        rightSlot={
          <button
            type="button"
            onClick={() => setCreateOpen(true)}
            className="inline-flex items-center justify-center rounded-xl bg-blue-500 px-5 py-3 font-semibold text-white transition hover:bg-blue-400 text-sm"
          >
            <Plus className="mr-1.5 h-4 w-4" /> Créer un prospect
          </button>
        }
      />

      <div className="p-4 lg:p-6">
        {error ? (
          <p className="mb-4 rounded-lg border border-rose-500/40 bg-rose-500/10 px-4 py-2 text-sm text-rose-300">
            {error}
          </p>
        ) : null}

        {loading ? (
          <div className="flex min-h-[50vh] items-center justify-center">
            <Loader2 className="h-6 w-6 animate-spin text-blue-400" />
          </div>
        ) : (
          <div className="flex gap-4 overflow-x-auto pb-4">
            {columns.map((col) => {
              const cards = byColumn[col.id] || [];
              const isHover = hoverCol === col.id;
              return (
                <div
                  key={col.id}
                  onDragOver={(e) => {
                    e.preventDefault();
                    setHoverCol(col.id);
                  }}
                  onDragLeave={() =>
                    setHoverCol((h) => (h === col.id ? null : h))
                  }
                  onDrop={() => onDropToColumn(col)}
                  className={`flex w-80 min-w-[320px] flex-shrink-0 flex-col rounded-xl border bg-brand-900/60 ${
                    isHover
                      ? "border-blue-500 bg-brand-900"
                      : "border-brand-800"
                  }`}
                >
                  <div className="flex items-center justify-between border-b border-brand-800 px-4 py-3">
                    <button
                      type="button"
                      onClick={() =>
                        col.custom ? renameCustomColumn(col.id) : null
                      }
                      className="flex items-center gap-2 text-left"
                      title={col.custom ? "Cliquer pour renommer" : ""}
                    >
                      <span
                        className={`h-2 w-2 rounded-full ${col.dot}`}
                      />
                      <h2 className="text-sm font-semibold text-white">
                        {col.label}
                      </h2>
                    </button>
                    <div className="flex items-center gap-2">
                      <span className="rounded-md bg-brand-950 px-2 py-0.5 text-xs font-semibold text-white/70">
                        {cards.length}
                      </span>
                      {col.custom ? (
                        <button
                          type="button"
                          onClick={() => removeCustomColumn(col.id)}
                          className="rounded p-1 text-white/40 hover:bg-rose-500/10 hover:text-rose-300"
                          aria-label="Supprimer la colonne"
                          title="Supprimer la colonne"
                        >
                          <X className="h-3.5 w-3.5" />
                        </button>
                      ) : null}
                    </div>
                  </div>

                  <div className="flex-1 space-y-3 p-3">
                    {cards.length === 0 ? (
                      <p className="py-8 text-center text-xs text-white/40">
                        Aucun prospect
                      </p>
                    ) : (
                      cards.map((p) => (
                        <LeadCard
                          key={p.id}
                          lead={p}
                          dragging={dragging === p.id}
                          onDragStart={() => onDragStart(p.id)}
                          onDragEnd={onDragEnd}
                          onDelete={() => deleteLead(p.id, p.name)}
                          onCreateSoumission={() => startSoumission(p)}
                        />
                      ))
                    )}
                  </div>
                </div>
              );
            })}
            <button
              type="button"
              onClick={addCustomColumn}
              className="flex h-12 w-80 min-w-[320px] flex-shrink-0 items-center justify-center gap-2 rounded-xl border border-dashed border-brand-800 text-sm text-white/40 hover:border-blue-500 hover:text-white"
            >
              <Plus className="h-4 w-4" />
              Ajouter une colonne
            </button>
          </div>
        )}
      </div>

      {createOpen ? (
        <CreateLeadModal
          onClose={() => setCreateOpen(false)}
          onCreated={(p) => {
            setItems((xs) => [p, ...xs]);
            setCreateOpen(false);
          }}
        />
      ) : null}
    </>
  );
}

function LeadCard({
  lead: p,
  dragging,
  onDragStart,
  onDragEnd,
  onDelete,
  onCreateSoumission
}: {
  lead: Lead;
  dragging: boolean;
  onDragStart: () => void;
  onDragEnd: () => void;
  onDelete: () => void;
  onCreateSoumission: () => void;
}) {
  return (
    <div
      draggable
      onDragStart={onDragStart}
      onDragEnd={onDragEnd}
      className={`group relative cursor-grab rounded-lg border border-brand-800 bg-brand-950 p-3 transition hover:border-blue-500 active:cursor-grabbing ${
        dragging ? "opacity-40" : ""
      }`}
    >
      <GripVertical className="absolute left-1 top-3 h-3 w-3 text-white/20" />

      <div className="absolute right-2 top-2 flex items-center gap-1 opacity-0 transition group-hover:opacity-100">
        <button
          type="button"
          onClick={(e) => {
            e.preventDefault();
            e.stopPropagation();
            onCreateSoumission();
          }}
          aria-label="Créer une soumission"
          title="Créer une soumission"
          className="rounded-md p-1 text-blue-300 hover:bg-blue-500/15"
        >
          <FileText className="h-3.5 w-3.5" />
        </button>
        <button
          type="button"
          onClick={(e) => {
            e.preventDefault();
            e.stopPropagation();
            onDelete();
          }}
          aria-label="Supprimer"
          className="rounded-md p-1 text-white/40 hover:bg-rose-500/15 hover:text-rose-400"
        >
          <Trash2 className="h-3.5 w-3.5" />
        </button>
      </div>

      <Link
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        href={`/dev-logiciel/leads/${p.id}` as any}
        className="block pl-3 pr-12"
      >
        <p className="truncate text-sm font-semibold text-white">{p.name}</p>
        {p.phone ? (
          <p className="mt-1 flex items-center gap-1.5 text-xs text-white/60">
            <Phone className="h-3 w-3" />
            <span className="truncate">{formatPhone(p.phone)}</span>
          </p>
        ) : null}
        {p.email ? (
          <p className="mt-1 flex items-center gap-1.5 text-xs text-white/60">
            <Mail className="h-3 w-3" />
            <span className="truncate">{p.email}</span>
          </p>
        ) : null}
        <div className="mt-2 flex items-center justify-between">
          <span className="inline-flex rounded-md bg-blue-500/15 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-blue-400">
            {PROJECT_LABEL[p.project_type] || p.project_type}
          </span>
          <span className="text-[10px] text-white/40">
            {new Date(p.created_at).toLocaleDateString("fr-CA", {
              month: "short",
              day: "2-digit"
            })}
          </span>
        </div>
      </Link>
    </div>
  );
}

function CreateLeadModal({
  onClose,
  onCreated
}: {
  onClose: () => void;
  onCreated: (p: Lead) => void;
}) {
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [address, setAddress] = useState("");
  const [projectType, setProjectType] = useState<string>("autre");
  const [budgetRange, setBudgetRange] = useState<string>("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit() {
    if (!name.trim()) {
      setError("Le nom complet est obligatoire.");
      return;
    }
    const cleanEmail = email.trim();
    const cleanPhone = phone.trim();
    if (!cleanEmail && !cleanPhone) {
      setError("Au moins un courriel ou un téléphone est requis.");
      return;
    }
    if (cleanEmail && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(cleanEmail)) {
      setError("Le courriel n'est pas valide (ex. nom@exemple.com).");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const payload: Record<string, string | null> = {
        name: name.trim(),
        email: cleanEmail || null,
        phone: cleanPhone || null,
        address: address.trim() || null,
        project_type: projectType || "autre",
        budget_range: budgetRange || null,
        project_summary:
          message.trim() || "(création manuelle depuis le CRM)",
        locale: "fr",
        source: "manual",
        status: "new"
      };
      const res = await authedFetch("/api/v1/devlog/leads", {
        method: "POST",
        body: JSON.stringify(payload)
      });
      if (!res.ok) {
        const txt = await res.text().catch(() => "");
        throw new Error(translateBackendError(txt, res.status));
      }
      const created = (await res.json()) as Lead;
      onCreated(created);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4"
      onClick={() => (!busy ? onClose() : null)}
    >
      <div
        className="w-full max-w-lg rounded-2xl border border-brand-800 bg-brand-950 p-6"
        onClick={(e) => e.stopPropagation()}
      >
        <h3 className="text-lg font-bold text-white">Nouveau prospect</h3>
        <div className="mt-5 space-y-3">
          <div>
            <label className="label">Nom complet *</label>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="input"
              autoFocus
            />
          </div>
          <p className="text-[11px] text-white/50">
            Courriel <strong>ou</strong> téléphone — au moins l&apos;un
            des deux est requis.
          </p>
          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <label className="label">Courriel</label>
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="input"
                placeholder="nom@exemple.com"
              />
            </div>
            <div>
              <label className="label">Téléphone</label>
              <input
                value={phone}
                onChange={(e) => setPhone(e.target.value)}
                className="input"
                placeholder="(514) 555-1234"
              />
            </div>
          </div>
          <div>
            <label className="label">Lieu du projet</label>
            <AddressInput
              value={address}
              onChange={setAddress}
              placeholder="Ex. 158 Rue Maurice, Saint-Sauveur, QC"
            />
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <label className="label">Type de projet</label>
              <select
                value={projectType}
                onChange={(e) => setProjectType(e.target.value)}
                className="input"
              >
                {Object.entries(PROJECT_LABEL).map(([k, v]) => (
                  <option key={k} value={k}>
                    {v}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="label">Budget</label>
              <select
                value={budgetRange}
                onChange={(e) => setBudgetRange(e.target.value)}
                className="input"
              >
                <option value="">— Non précisé —</option>
                <option value="under_10k">Moins de 10 000 $</option>
                <option value="10_25">10 000 $ – 25 000 $</option>
                <option value="25_50">25 000 $ – 50 000 $</option>
                <option value="50_100">50 000 $ – 100 000 $</option>
                <option value="over_100">Plus de 100 000 $</option>
                <option value="unsure">Indéterminé</option>
              </select>
            </div>
          </div>
          <div>
            <label className="label">Message / notes initiales</label>
            <textarea
              rows={3}
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              className="input"
            />
          </div>
          {error ? <p className="text-sm text-rose-300">{error}</p> : null}
        </div>
        <div className="mt-6 flex items-center justify-end gap-3">
          <button
            type="button"
            onClick={onClose}
            disabled={busy}
            className="btn-secondary text-sm"
          >
            Annuler
          </button>
          <button
            type="button"
            onClick={submit}
            disabled={busy}
            className="inline-flex items-center justify-center rounded-xl bg-blue-500 px-5 py-3 font-semibold text-white transition hover:bg-blue-400 text-sm disabled:opacity-60"
          >
            {busy ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" /> Création…
              </>
            ) : (
              "Créer"
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
