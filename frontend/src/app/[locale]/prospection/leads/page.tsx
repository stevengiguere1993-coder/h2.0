"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowDown,
  ArrowUp,
  ArrowUpDown,
  Download,
  Layers,
  Loader2,
  MapPin,
  Phone,
  Plus,
  Save,
  Search,
  Star,
  Trash2,
  X
} from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { useConfirm } from "@/components/confirm-dialog";
import { Link } from "@/i18n/navigation";
import { authedFetch } from "@/lib/auth";
import { useProspectionLayout } from "../layout";

type Lead = {
  id: number;
  name: string;
  kind: string;
  status: string;
  address: string | null;
  city: string | null;
  postal_code: string | null;
  lat: number | null;
  lng: number | null;
  priority: number;
  nb_logements: number | null;
  valeur_fonciere: number | null;
  annee_construction: number | null;
  owner_kind: string;
  owner_name: string | null;
  owner_neq?: string | null;
  owner_phone?: string | null;
  multi_properties_count?: number;
  estimated_equity_pct?: number | null;
  score: number;
  tags: string[];
  photos_count: number;
  created_at: string;
  recontact_at?: string | null;
};

// Doit matcher _normalize_owner_name() côté backend pour que le lien
// vers la vue propriétaire fonctionne.
function normalizeOwnerName(name: string): string {
  if (!name) return "";
  return name
    .normalize("NFKD")
    .replace(/[̀-ͯ]/g, "") // strip accents
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9 ]+/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .replace(/ /g, "-");
}

function ownerViewHref(lead: {
  owner_neq?: string | null;
  owner_name: string | null;
}): string | null {
  if (lead.owner_neq) {
    return `/prospection/proprio/neq/${encodeURIComponent(lead.owner_neq)}`;
  }
  if (lead.owner_name) {
    const norm = normalizeOwnerName(lead.owner_name);
    if (norm) return `/prospection/proprio/nom/${encodeURIComponent(norm)}`;
  }
  return null;
}

const LEAD_KIND_LABEL: Record<string, string> = {
  multilogement: "Multilogement",
  terrain: "Terrain",
  semi_commercial: "Semi-commercial",
  autre: "Autre"
};

const STATUS_LABEL: Record<string, string> = {
  a_visiter: "Repéré",
  visite: "Visité (drive-by)",
  a_contacter: "À contacter",
  contacte: "Contacté",
  hot_lead: "🔥 Hot Lead",
  cold_lead: "🧊 Cold Lead",
  a_recontacter: "📅 À recontacter",
  soumissionne: "Offre soumise",
  offre_acceptee: "Offre acceptée",
  en_inspection: "Inspection",
  en_nego: "Négociation",
  chez_notaire: "Chez le notaire",
  en_cession: "Cession en cours",
  converti: "Acheté / Cédé ✓",
  perdu: "Perdu / refus"
};

const STATUS_COLOR: Record<string, string> = {
  a_visiter: "bg-emerald-500/20 text-emerald-300",
  visite: "bg-blue-500/20 text-blue-300",
  a_contacter: "bg-amber-500/20 text-amber-300",
  contacte: "bg-violet-500/20 text-violet-300",
  hot_lead: "bg-orange-500/25 text-orange-300",
  cold_lead: "bg-sky-500/25 text-sky-200",
  a_recontacter: "bg-slate-500/25 text-slate-200",
  soumissionne: "bg-pink-500/20 text-pink-300",
  offre_acceptee: "bg-fuchsia-500/25 text-fuchsia-200",
  en_inspection: "bg-cyan-500/20 text-cyan-300",
  en_nego: "bg-yellow-500/20 text-yellow-300",
  chez_notaire: "bg-indigo-500/25 text-indigo-200",
  en_cession: "bg-teal-500/25 text-teal-200",
  converti: "bg-green-500/30 text-green-200",
  perdu: "bg-rose-500/20 text-rose-300"
};

const KIND_LABEL: Record<string, string> = {
  multilogement: "Multi-logement",
  terrain: "Terrain",
  semi_commercial: "Semi-commercial",
  autre: "Autre"
};

type SizeBucket = "" | "small" | "medium" | "large";
const SIZE_LABEL: Record<Exclude<SizeBucket, "">, string> = {
  small: "4-10 portes",
  medium: "11-20 portes",
  large: "20+ portes"
};

type SortKey =
  | "name"
  | "city"
  | "nb_logements"
  | "valeur_fonciere"
  | "owner"
  | "status"
  | "priority"
  | "score"
  | "created_at";

const TAG_LABEL: Record<string, string> = {
  "sweet-spot": "Sweet spot 6-12",
  "petit-multi": "Petit multi",
  "moyen-multi": "Moyen multi",
  "gros-multi": "Gros multi",
  "tres-vieux": "60 ans+",
  vieux: "40 ans+",
  mature: "25 ans+",
  neuf: "Récent",
  corp: "Corporation",
  "neq-connu": "NEQ connu",
  "contact-direct": "Contact direct",
  "proprio-inconnu": "Proprio ?",
  "priorite-haute": "Prio haute"
};

function scoreBadgeClass(s: number): string {
  if (s >= 70) return "bg-emerald-500/30 text-emerald-200";
  if (s >= 50) return "bg-amber-500/25 text-amber-200";
  if (s >= 30) return "bg-blue-500/25 text-blue-200";
  return "bg-brand-800 text-white/50";
}

function bucketFor(n: number | null): SizeBucket {
  if (n == null) return "";
  if (n >= 21) return "large";
  if (n >= 11) return "medium";
  if (n >= 4) return "small";
  return "";
}

function fmtMoney(n: number | null): string {
  if (n == null) return "—";
  return new Intl.NumberFormat("fr-CA", {
    style: "currency",
    currency: "CAD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2
  }).format(n);
}

function fmtDate(iso: string): string {
  return new Date(iso).toLocaleDateString("fr-CA", {
    day: "2-digit",
    month: "short"
  });
}

function csvEscape(v: unknown): string {
  if (v == null) return "";
  const s = String(v);
  // RFC 4180 — quote if comma/quote/newline.
  if (/[",\n\r]/.test(s)) {
    return `"${s.replace(/"/g, '""')}"`;
  }
  return s;
}

function downloadCsv(rows: Lead[]) {
  const headers = [
    "id",
    "name",
    "kind",
    "status",
    "score",
    "tags",
    "address",
    "city",
    "postal_code",
    "nb_logements",
    "annee_construction",
    "valeur_fonciere",
    "owner_kind",
    "owner_name",
    "priority",
    "created_at"
  ];
  const lines: string[] = [headers.join(",")];
  for (const l of rows) {
    lines.push(
      [
        l.id,
        l.name,
        l.kind,
        l.status,
        l.score,
        (l.tags || []).join("|"),
        l.address,
        l.city,
        l.postal_code,
        l.nb_logements,
        l.annee_construction,
        l.valeur_fonciere,
        l.owner_kind,
        l.owner_name,
        l.priority,
        l.created_at
      ]
        .map(csvEscape)
        .join(",")
    );
  }
  // BOM pour qu'Excel ouvre proprement les accents.
  const blob = new Blob(["﻿" + lines.join("\r\n")], {
    type: "text/csv;charset=utf-8"
  });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  const stamp = new Date().toISOString().slice(0, 10);
  a.href = url;
  a.download = `prospection-leads-${stamp}.csv`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

function compare(a: unknown, b: unknown): number {
  const aNull = a == null || a === "";
  const bNull = b == null || b === "";
  if (aNull && bNull) return 0;
  if (aNull) return 1;
  if (bNull) return -1;
  if (typeof a === "number" && typeof b === "number") return a - b;
  return String(a).localeCompare(String(b), "fr");
}

export default function ProspectionLeadsPage() {
  const { onOpenSidebar } = useProspectionLayout();
  const [leads, setLeads] = useState<Lead[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [kindFilter, setKindFilter] = useState("");
  const [cityFilter, setCityFilter] = useState("");
  const [sizeFilter, setSizeFilter] = useState<SizeBucket>("");

  const [sortKey, setSortKey] = useState<SortKey>("score");
  const [sortAsc, setSortAsc] = useState(false);

  const [saveOpen, setSaveOpen] = useState(false);
  // Vue : tableau (par défaut) ou kanban. Persisté en localStorage.
  const [view, setView] = useState<"table" | "kanban">("table");
  useEffect(() => {
    try {
      const stored = window.localStorage.getItem(
        "horizon.prospection.leadsView"
      );
      if (stored === "kanban" || stored === "table") setView(stored);
    } catch {
      /* ignore */
    }
  }, []);
  useEffect(() => {
    try {
      window.localStorage.setItem(
        "horizon.prospection.leadsView",
        view
      );
    } catch {
      /* ignore */
    }
  }, [view]);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError(null);
      // Garde-fou : si l'API met plus de 30 s à répondre (cold start
      // Render, problème réseau, schema désynchronisé), on coupe et on
      // affiche un message clair plutôt qu'un spinner infini.
      const controller = new AbortController();
      const killer = window.setTimeout(() => controller.abort(), 30_000);
      try {
        const res = await authedFetch(
          "/api/v1/prospection?limit=1000&archived=false",
          { signal: controller.signal }
        );
        if (!res.ok) {
          throw new Error(
            `HTTP ${res.status}${
              res.status === 401
                ? " — session expirée, reconnecte-toi"
                : res.status >= 500
                  ? " — erreur serveur"
                  : ""
            }`
          );
        }
        const data = (await res.json()) as Lead[];
        if (!cancelled) setLeads(data);
      } catch (e) {
        if (cancelled) return;
        const err = e as Error;
        if (err.name === "AbortError") {
          setError(
            "Le serveur n'a pas répondu en 30 s. Réessaie ou recharge la page."
          );
        } else {
          setError(err.message);
        }
      } finally {
        window.clearTimeout(killer);
        if (!cancelled) setLoading(false);
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, []);

  const cities = useMemo(() => {
    const set = new Set<string>();
    for (const l of leads) {
      if (l.city) set.add(l.city);
    }
    return Array.from(set).sort((a, b) => a.localeCompare(b, "fr"));
  }, [leads]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return leads.filter((l) => {
      if (statusFilter && l.status !== statusFilter) return false;
      if (kindFilter && l.kind !== kindFilter) return false;
      if (cityFilter && l.city !== cityFilter) return false;
      if (sizeFilter && bucketFor(l.nb_logements) !== sizeFilter)
        return false;
      if (q) {
        const hay = [
          l.name,
          l.address,
          l.city,
          l.owner_name,
          l.postal_code
        ]
          .map((x) => (x || "").toLowerCase())
          .join(" ");
        if (!hay.includes(q)) return false;
      }
      return true;
    });
  }, [leads, search, statusFilter, kindFilter, cityFilter, sizeFilter]);

  const sorted = useMemo(() => {
    const arr = [...filtered];
    arr.sort((a, b) => {
      let va: unknown;
      let vb: unknown;
      switch (sortKey) {
        case "name":
          va = a.name;
          vb = b.name;
          break;
        case "city":
          va = a.city;
          vb = b.city;
          break;
        case "nb_logements":
          va = a.nb_logements;
          vb = b.nb_logements;
          break;
        case "valeur_fonciere":
          va = a.valeur_fonciere;
          vb = b.valeur_fonciere;
          break;
        case "owner":
          va = a.owner_name;
          vb = b.owner_name;
          break;
        case "status":
          va = STATUS_LABEL[a.status] || a.status;
          vb = STATUS_LABEL[b.status] || b.status;
          break;
        case "priority":
          va = a.priority;
          vb = b.priority;
          break;
        case "score":
          va = a.score;
          vb = b.score;
          break;
        case "created_at":
        default:
          va = a.created_at;
          vb = b.created_at;
      }
      const c = compare(va, vb);
      return sortAsc ? c : -c;
    });
    return arr;
  }, [filtered, sortKey, sortAsc]);

  const stats = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const l of leads) {
      counts[l.status] = (counts[l.status] || 0) + 1;
    }
    return [
      { key: "a_visiter", label: "À visiter", color: "text-emerald-300" },
      { key: "a_contacter", label: "À contacter", color: "text-amber-300" },
      {
        key: "soumissionne",
        label: "En soumission",
        color: "text-pink-300"
      },
      { key: "converti", label: "Convertis", color: "text-green-300" }
    ].map((s) => ({ ...s, count: counts[s.key] || 0 }));
  }, [leads]);

  function toggleSort(k: SortKey) {
    if (sortKey === k) {
      setSortAsc((v) => !v);
    } else {
      setSortKey(k);
      setSortAsc(k === "name" || k === "city" || k === "owner");
    }
  }

  function SortIcon({ k }: { k: SortKey }) {
    if (sortKey !== k)
      return <ArrowUpDown className="ml-1 inline h-3 w-3 opacity-40" />;
    return sortAsc ? (
      <ArrowUp className="ml-1 inline h-3 w-3 text-emerald-400" />
    ) : (
      <ArrowDown className="ml-1 inline h-3 w-3 text-emerald-400" />
    );
  }

  return (
    <>
      <AppTopbar
        breadcrumbs={[
          { label: "Prospection", href: "/prospection" },
          { label: "Liste des leads" }
        ]}
        onOpenSidebar={onOpenSidebar}
        rightSlot={
          <div className="flex flex-wrap items-center gap-2">
            {/* Toggle vue Tableau / Kanban */}
            <div className="inline-flex overflow-hidden rounded-md border border-brand-700 text-xs">
              <button
                type="button"
                onClick={() => setView("table")}
                className={`px-2.5 py-1.5 ${
                  view === "table"
                    ? "bg-emerald-500/15 text-emerald-300"
                    : "bg-brand-900 text-white/60 hover:text-white"
                }`}
              >
                ≡ Tableau
              </button>
              <button
                type="button"
                onClick={() => setView("kanban")}
                className={`px-2.5 py-1.5 ${
                  view === "kanban"
                    ? "bg-emerald-500/15 text-emerald-300"
                    : "bg-brand-900 text-white/60 hover:text-white"
                }`}
              >
                ▥ Kanban
              </button>
            </div>
            <Link
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
              href={"/prospection/lists" as any}
              className="inline-flex items-center gap-1.5 rounded-md border border-brand-700 bg-brand-900 px-3 py-1.5 text-xs font-medium text-white/70 hover:text-white"
              title="Listes (segments) sauvegardés"
            >
              <Layers className="h-3.5 w-3.5" />
              Listes
            </Link>
            <button
              type="button"
              onClick={() => setSaveOpen(true)}
              disabled={sorted.length === 0}
              className="inline-flex items-center gap-1.5 rounded-md border border-emerald-500/40 bg-emerald-500/10 px-3 py-1.5 text-xs font-medium text-emerald-300 hover:bg-emerald-500/20 disabled:opacity-40"
              title="Sauvegarde la vue filtrée actuelle comme liste"
            >
              <Save className="h-3.5 w-3.5" />
              Sauvegarder vue
            </button>
            <button
              type="button"
              onClick={() => downloadCsv(sorted)}
              disabled={sorted.length === 0}
              className="inline-flex items-center gap-1.5 rounded-md border border-emerald-500/40 bg-emerald-500/10 px-3 py-1.5 text-xs font-medium text-emerald-300 hover:bg-emerald-500/20 disabled:opacity-40"
              title="Exporter la liste filtrée en CSV"
            >
              <Download className="h-3.5 w-3.5" />
              CSV
            </button>
            <Link
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
              href={"/m/prospection" as any}
              className="btn-accent text-sm"
            >
              <Plus className="mr-1.5 h-4 w-4" />
              Ajouter
            </Link>
          </div>
        }
      />

      <SaveAsListModal
        open={saveOpen}
        onClose={() => setSaveOpen(false)}
        leadIds={sorted.map((l) => l.id)}
        criteria={{
          status: statusFilter || undefined,
          kind: kindFilter || undefined,
          city: cityFilter || undefined,
          // Pas de min/max envoyé — sizeFilter est appliqué côté
          // client. Si l'utilisateur veut une liste re-buildable, il
          // saisit lui-même les critères dans le builder.
        }}
      />

      <div className="p-4 lg:p-6">
        {/* Stats */}
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          {stats.map((s) => (
            <div
              key={s.key}
              className="rounded-xl border border-brand-800 bg-brand-900 p-3"
            >
              <p className="text-[11px] uppercase tracking-wider text-white/50">
                {s.label}
              </p>
              <p className={`mt-1 text-2xl font-bold ${s.color}`}>
                {s.count}
              </p>
            </div>
          ))}
        </div>

        {/* Filtres */}
        <div className="mt-4 rounded-xl border border-brand-800 bg-brand-900 p-3">
          <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-5">
            <div className="relative lg:col-span-2">
              <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-white/40" />
              <input
                type="search"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Rechercher (nom, adresse, ville, propriétaire)…"
                className="input pl-8 text-sm"
              />
            </div>
            <select
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
              className="input text-sm"
            >
              <option value="">Tous statuts</option>
              {Object.entries(STATUS_LABEL).map(([k, v]) => (
                <option key={k} value={k}>
                  {v}
                </option>
              ))}
            </select>
            <select
              value={kindFilter}
              onChange={(e) => setKindFilter(e.target.value)}
              className="input text-sm"
            >
              <option value="">Tous types</option>
              {Object.entries(KIND_LABEL).map(([k, v]) => (
                <option key={k} value={k}>
                  {v}
                </option>
              ))}
            </select>
            <select
              value={sizeFilter}
              onChange={(e) =>
                setSizeFilter(e.target.value as SizeBucket)
              }
              className="input text-sm"
            >
              <option value="">Toutes tailles</option>
              {(Object.keys(SIZE_LABEL) as Array<keyof typeof SIZE_LABEL>).map(
                (k) => (
                  <option key={k} value={k}>
                    {SIZE_LABEL[k]}
                  </option>
                )
              )}
            </select>
          </div>
          {cities.length > 0 ? (
            <div className="mt-2 flex flex-wrap items-center gap-1.5">
              <span className="text-[11px] uppercase tracking-wider text-white/40">
                Ville :
              </span>
              <button
                type="button"
                onClick={() => setCityFilter("")}
                className={`rounded-full px-2 py-0.5 text-[11px] transition ${
                  cityFilter === ""
                    ? "bg-emerald-500/20 text-emerald-300"
                    : "bg-brand-800 text-white/60 hover:text-white"
                }`}
              >
                Toutes
              </button>
              {cities.map((c) => (
                <button
                  key={c}
                  type="button"
                  onClick={() => setCityFilter(c)}
                  className={`rounded-full px-2 py-0.5 text-[11px] transition ${
                    cityFilter === c
                      ? "bg-emerald-500/20 text-emerald-300"
                      : "bg-brand-800 text-white/60 hover:text-white"
                  }`}
                >
                  {c}
                </button>
              ))}
            </div>
          ) : null}
          <p className="mt-2 text-[11px] text-white/40">
            {sorted.length}{" "}
            lead{sorted.length > 1 ? "s" : ""} affiché
            {sorted.length > 1 ? "s" : ""}
            {sorted.length !== leads.length
              ? ` sur ${leads.length}`
              : ""}
          </p>
        </div>

        {/* Tableau */}
        <div className="mt-4 overflow-hidden rounded-xl border border-brand-800 bg-brand-900">
          {loading ? (
            <div className="flex items-center justify-center py-12">
              <Loader2 className="h-6 w-6 animate-spin text-emerald-500" />
            </div>
          ) : error ? (
            <p className="p-6 text-sm text-rose-300">{error}</p>
          ) : sorted.length === 0 ? (
            <div className="p-12 text-center">
              <MapPin className="mx-auto h-8 w-8 text-white/20" />
              <p className="mt-3 text-sm text-white/50">
                Aucun lead ne correspond aux filtres.
              </p>
            </div>
          ) : view === "kanban" ? (
            <KanbanBoard
              leads={sorted}
              onChangeStatus={async (leadId, newStatus) => {
                // Optimistic update + persist
                setLeads((prev) =>
                  prev.map((l) =>
                    l.id === leadId ? { ...l, status: newStatus } : l
                  )
                );
                try {
                  await authedFetch(
                    `/api/v1/prospection/${leadId}`,
                    {
                      method: "PATCH",
                      body: JSON.stringify({ status: newStatus })
                    }
                  );
                } catch {
                  /* revert au prochain reload */
                }
              }}
            />
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="bg-brand-950/60 text-left text-[11px] uppercase tracking-wider text-white/50">
                  <tr>
                    <th
                      onClick={() => toggleSort("score")}
                      className="cursor-pointer px-3 py-2.5 text-center hover:text-white"
                    >
                      Score
                      <SortIcon k="score" />
                    </th>
                    <th className="px-3 py-2.5">Type</th>
                    <th
                      onClick={() => toggleSort("city")}
                      className="cursor-pointer px-3 py-2.5 hover:text-white"
                    >
                      Adresse / Ville
                      <SortIcon k="city" />
                    </th>
                    <th
                      onClick={() => toggleSort("nb_logements")}
                      className="cursor-pointer px-3 py-2.5 text-right hover:text-white"
                    >
                      # log.
                      <SortIcon k="nb_logements" />
                    </th>
                    <th
                      onClick={() => toggleSort("valeur_fonciere")}
                      className="cursor-pointer px-3 py-2.5 text-right hover:text-white"
                    >
                      Valeur
                      <SortIcon k="valeur_fonciere" />
                    </th>
                    <th
                      onClick={() => toggleSort("owner")}
                      className="cursor-pointer px-3 py-2.5 hover:text-white"
                    >
                      Propriétaire
                      <SortIcon k="owner" />
                    </th>
                    <th className="px-3 py-2.5">Téléphone</th>
                    <th
                      onClick={() => toggleSort("status")}
                      className="cursor-pointer px-3 py-2.5 hover:text-white"
                    >
                      Statut
                      <SortIcon k="status" />
                    </th>
                    <th
                      onClick={() => toggleSort("priority")}
                      className="cursor-pointer px-3 py-2.5 text-center hover:text-white"
                    >
                      Prio.
                      <SortIcon k="priority" />
                    </th>
                    <th
                      onClick={() => toggleSort("created_at")}
                      className="cursor-pointer px-3 py-2.5 text-right hover:text-white"
                    >
                      Ajouté
                      <SortIcon k="created_at" />
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-brand-800">
                  {sorted.map((l) => (
                    <tr
                      key={l.id}
                      className="cursor-pointer transition hover:bg-brand-800/40"
                    >
                      <td className="px-3 py-2.5 text-center">
                        <span
                          className={`inline-flex h-7 w-9 items-center justify-center rounded-md text-xs font-bold tabular-nums ${scoreBadgeClass(
                            l.score
                          )}`}
                          title={
                            l.tags.length
                              ? l.tags
                                  .map((t) => TAG_LABEL[t] || t)
                                  .join(" · ")
                              : undefined
                          }
                        >
                          {l.score}
                        </span>
                      </td>
                      <td className="px-3 py-2.5 text-white/60">
                        {KIND_LABEL[l.kind] || l.kind}
                      </td>
                      <td className="px-3 py-2.5">
                        <Link
                          // eslint-disable-next-line @typescript-eslint/no-explicit-any
                          href={`/prospection/${l.id}` as any}
                          className="font-medium text-white hover:text-emerald-300"
                        >
                          {l.address || (
                            <span className="text-white/30">—</span>
                          )}
                        </Link>
                        {l.city ? (
                          <div className="text-[11px] text-white/40">
                            {l.city}
                          </div>
                        ) : null}
                        {l.tags.length > 0 ? (
                          <div className="mt-1 flex flex-wrap gap-1">
                            {l.tags.slice(0, 3).map((t) => (
                              <span
                                key={t}
                                className="rounded bg-brand-800 px-1.5 py-0.5 text-[10px] text-white/60"
                              >
                                {TAG_LABEL[t] || t}
                              </span>
                            ))}
                          </div>
                        ) : null}
                      </td>
                      <td className="px-3 py-2.5 text-right tabular-nums text-white/80">
                        {l.nb_logements ?? (
                          <span className="text-white/30">—</span>
                        )}
                      </td>
                      <td className="px-3 py-2.5 text-right tabular-nums text-white/80">
                        {fmtMoney(l.valeur_fonciere)}
                      </td>
                      <td className="px-3 py-2.5 text-white/70">
                        {l.owner_name || (
                          <span className="text-white/30">—</span>
                        )}
                        <div className="mt-0.5 flex flex-wrap gap-1">
                          {l.owner_kind === "corporation" ? (
                            <span className="rounded bg-violet-500/15 px-1 py-0.5 text-[10px] text-violet-300">
                              Corp
                            </span>
                          ) : l.owner_kind === "particulier" ? (
                            <span className="rounded bg-blue-500/15 px-1 py-0.5 text-[10px] text-blue-300">
                              Particulier
                            </span>
                          ) : (
                            <span className="rounded bg-brand-800 px-1 py-0.5 text-[10px] text-white/40">
                              ?
                            </span>
                          )}
                          {(l.multi_properties_count ?? 0) > 0 ? (
                            (() => {
                              const href = ownerViewHref(l);
                              const inner = (
                                <span
                                  className="rounded bg-amber-500/15 px-1 py-0.5 text-[10px] text-amber-300 hover:bg-amber-500/25"
                                  title="Voir la fiche propriétaire (tous ses immeubles)"
                                >
                                  +{l.multi_properties_count} autres
                                </span>
                              );
                              return href ? (
                                <Link
                                  // eslint-disable-next-line @typescript-eslint/no-explicit-any
                                  href={href as any}
                                  onClick={(e) => e.stopPropagation()}
                                >
                                  {inner}
                                </Link>
                              ) : (
                                inner
                              );
                            })()
                          ) : null}
                        </div>
                      </td>
                      <td className="px-3 py-2.5">
                        {l.owner_phone ? (
                          <a
                            href={`tel:${l.owner_phone}`}
                            className="inline-flex items-center gap-1 text-xs text-emerald-300 hover:text-emerald-200"
                          >
                            <Phone className="h-3 w-3" />
                            {l.owner_phone}
                          </a>
                        ) : (
                          <span className="text-[11px] text-white/30">—</span>
                        )}
                      </td>
                      <td className="px-3 py-2.5">
                        <span
                          className={`rounded-full px-2 py-0.5 text-[11px] font-medium ${
                            STATUS_COLOR[l.status] ||
                            "bg-brand-800 text-white/60"
                          }`}
                        >
                          {STATUS_LABEL[l.status] || l.status}
                        </span>
                      </td>
                      <td className="px-3 py-2.5 text-center">
                        <span className="inline-flex items-center gap-0.5">
                          {Array.from({ length: l.priority }).map(
                            (_, i) => (
                              <Star
                                key={i}
                                className="h-3 w-3 fill-amber-400 text-amber-400"
                              />
                            )
                          )}
                        </span>
                      </td>
                      <td className="px-3 py-2.5 text-right text-[11px] text-white/40">
                        {fmtDate(l.created_at)}
                      </td>
                      <td className="px-3 py-2.5 text-right">
                        <DeleteLeadButton
                          leadId={l.id}
                          leadName={l.name}
                          onDeleted={() => {
                            setLeads((prev) =>
                              prev.filter((x) => x.id !== l.id)
                            );
                          }}
                        />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </>
  );
}

/**
 * Modal de création de liste à partir des leads filtrés actuels.
 *
 * Deux modes :
 * - « Liste manuelle » : on crée la liste vide, puis on ajoute les
 *   lead_ids actuellement affichés. Pas de critères stockés.
 * - « Liste re-construisible » : on envoie les critères au backend
 *   via /lists/from-query — la liste pourra être rebuilt plus tard
 *   pour récupérer les nouveaux leads matchant.
 */
function SaveAsListModal({
  open,
  onClose,
  leadIds,
  criteria
}: {
  open: boolean;
  onClose: () => void;
  leadIds: number[];
  criteria: {
    status?: string;
    kind?: string;
    city?: string;
  };
}) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [mode, setMode] = useState<"manual" | "rebuildable">(
    "rebuildable"
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (open) {
      setName("");
      setDescription("");
      setError(null);
    }
  }, [open]);

  async function save() {
    if (!name.trim() || busy) return;
    setBusy(true);
    setError(null);
    try {
      if (mode === "rebuildable") {
        const res = await authedFetch(
          "/api/v1/prospection/lists/from-query",
          {
            method: "POST",
            body: JSON.stringify({
              name: name.trim(),
              description: description.trim() || null,
              criteria
            })
          }
        );
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = (await res.json()) as { id: number };
        window.location.href = `/prospection/lists/${data.id}`;
      } else {
        // Mode manuel : crée vide puis add members
        const r1 = await authedFetch("/api/v1/prospection/lists", {
          method: "POST",
          body: JSON.stringify({
            name: name.trim(),
            description: description.trim() || null
          })
        });
        if (!r1.ok) throw new Error(`HTTP ${r1.status}`);
        const created = (await r1.json()) as { id: number };
        if (leadIds.length > 0) {
          await authedFetch(
            `/api/v1/prospection/lists/${created.id}/members`,
            {
              method: "POST",
              body: JSON.stringify({ lead_ids: leadIds })
            }
          );
        }
        window.location.href = `/prospection/lists/${created.id}`;
      }
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  if (!open) return null;
  return (
    <div className="fixed inset-0 z-[1000] flex items-center justify-center bg-black/70 p-4">
      <div className="w-full max-w-md rounded-2xl border border-brand-800 bg-brand-950 p-5 shadow-2xl">
        <header className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Save className="h-4 w-4 text-emerald-400" />
            <h2 className="text-sm font-semibold text-white">
              Sauvegarder la vue comme liste
            </h2>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md p-1 text-white/40 hover:bg-brand-900 hover:text-white"
          >
            <X className="h-4 w-4" />
          </button>
        </header>

        <div className="mt-4 space-y-3">
          <div>
            <label className="label">Nom de la liste</label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Ex: Plateau 6-12 portes"
              className="input"
              autoFocus
            />
          </div>
          <div>
            <label className="label">Description (optionnelle)</label>
            <input
              type="text"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              className="input"
            />
          </div>

          <fieldset className="space-y-1">
            <legend className="label">Type de liste</legend>
            <label className="flex cursor-pointer items-start gap-2 rounded-md border border-brand-700 bg-brand-900 p-2 text-xs">
              <input
                type="radio"
                checked={mode === "rebuildable"}
                onChange={() => setMode("rebuildable")}
                className="mt-0.5"
              />
              <span>
                <span className="font-medium text-white">
                  Re-constructible (recommandé)
                </span>
                <span className="block text-white/50">
                  Mémorise les filtres. Les nouveaux leads correspondants
                  pourront être ajoutés via « Recalculer ».
                </span>
              </span>
            </label>
            <label className="flex cursor-pointer items-start gap-2 rounded-md border border-brand-700 bg-brand-900 p-2 text-xs">
              <input
                type="radio"
                checked={mode === "manual"}
                onChange={() => setMode("manual")}
                className="mt-0.5"
              />
              <span>
                <span className="font-medium text-white">Manuelle</span>
                <span className="block text-white/50">
                  Capture les {leadIds.length} leads actuels. Pas de
                  rebuild — tu ajoutes/retires à la main par la suite.
                </span>
              </span>
            </label>
          </fieldset>

          {error ? (
            <p className="rounded-md border border-rose-500/40 bg-rose-500/10 px-2 py-1.5 text-xs text-rose-300">
              {error}
            </p>
          ) : null}
        </div>

        <footer className="mt-4 flex items-center justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            className="rounded-md px-3 py-1.5 text-xs text-white/60 hover:bg-brand-900 hover:text-white"
          >
            Annuler
          </button>
          <button
            type="button"
            onClick={save}
            disabled={!name.trim() || busy}
            className="btn-accent text-sm"
          >
            {busy ? (
              <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />
            ) : (
              <Save className="mr-1.5 h-4 w-4" />
            )}
            Créer la liste
          </button>
        </footer>
      </div>
    </div>
  );
}

/**
 * Kanban view des leads : 12 colonnes (une par statut buy-flow),
 * cards drag-and-droppables. HTML5 drag API native — aucune
 * dépendance externe. Le drop déclenche un PATCH du status.
 */
function KanbanBoard({
  leads,
  onChangeStatus
}: {
  leads: Lead[];
  onChangeStatus: (leadId: number, newStatus: string) => void;
}) {
  const [dragId, setDragId] = useState<number | null>(null);
  const [hoverCol, setHoverCol] = useState<string | null>(null);

  // Barre de défilement horizontale dupliquée EN HAUT du kanban, synchronisée
  // avec le défilement réel. Le kanban est large (15 colonnes) et, avec
  // beaucoup de cartes, les colonnes deviennent très hautes → la scrollbar
  // native se retrouve loin en bas. Celle du haut permet de se déplacer entre
  // les colonnes sans devoir descendre tout en bas.
  const topScrollRef = useRef<HTMLDivElement>(null);
  const bodyScrollRef = useRef<HTMLDivElement>(null);
  const [kanbanWidth, setKanbanWidth] = useState(0);

  useEffect(() => {
    const measure = () => {
      if (bodyScrollRef.current) {
        setKanbanWidth(bodyScrollRef.current.scrollWidth);
      }
    };
    measure();
    window.addEventListener("resize", measure);
    return () => window.removeEventListener("resize", measure);
  }, [leads]);

  // Synchronise le défilement entre les deux barres. Le garde > 1px évite
  // toute oscillation due aux arrondis sub-pixels.
  function syncScroll(
    from: HTMLDivElement | null,
    to: HTMLDivElement | null
  ) {
    if (from && to && Math.abs(to.scrollLeft - from.scrollLeft) > 1) {
      to.scrollLeft = from.scrollLeft;
    }
  }

  const COLUMNS: { key: string; label: string }[] = [
    { key: "a_visiter", label: "Repéré" },
    { key: "visite", label: "Visité" },
    { key: "a_contacter", label: "À contacter" },
    { key: "contacte", label: "Contacté" },
    { key: "hot_lead", label: "🔥 Hot Lead" },
    { key: "cold_lead", label: "🧊 Cold Lead" },
    { key: "a_recontacter", label: "📅 À recontacter" },
    { key: "soumissionne", label: "Offre soumise" },
    { key: "offre_acceptee", label: "Offre acceptée" },
    { key: "en_inspection", label: "Inspection" },
    { key: "en_nego", label: "Négociation" },
    { key: "chez_notaire", label: "Notaire" },
    { key: "en_cession", label: "Cession" },
    { key: "converti", label: "Acheté/Cédé" },
    { key: "perdu", label: "Perdu" }
  ];

  const byStatus: Record<string, Lead[]> = {};
  for (const c of COLUMNS) byStatus[c.key] = [];
  for (const l of leads) {
    const k = byStatus[l.status] ? l.status : "a_visiter";
    byStatus[k].push(l);
  }

  function fmtMoneyShort(n: number | null): string {
    if (n == null) return "—";
    if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M$`;
    if (n >= 1_000) return `${(n / 1_000).toFixed(0)}k$`;
    return `${Math.round(n)}$`;
  }

  return (
    <div>
      {/* Barre de défilement dupliquée EN HAUT, synchronisée avec le kanban. */}
      <div
        ref={topScrollRef}
        onScroll={() =>
          syncScroll(topScrollRef.current, bodyScrollRef.current)
        }
        className="overflow-x-auto"
        aria-hidden="true"
      >
        <div style={{ width: kanbanWidth, height: 1 }} />
      </div>
      <div
        ref={bodyScrollRef}
        onScroll={() =>
          syncScroll(bodyScrollRef.current, topScrollRef.current)
        }
        className="overflow-x-auto p-3"
      >
      <div className="flex gap-3" style={{ minWidth: "max-content" }}>
        {COLUMNS.map((col) => {
          const items = byStatus[col.key] || [];
          const isHover = hoverCol === col.key;
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
                  onChangeStatus(dragId, col.key);
                  setDragId(null);
                }
              }}
              className={`flex w-72 shrink-0 flex-col rounded-xl border bg-brand-900 transition ${
                isHover
                  ? "border-emerald-500/60 bg-emerald-500/5"
                  : col.key === "hot_lead"
                    ? "hot-lead-column border-orange-400/60"
                    : col.key === "cold_lead"
                      ? "cold-lead-column border-sky-400/60"
                      : col.key === "a_recontacter"
                        ? "recontact-column border-slate-400/40"
                        : "border-brand-800"
              }`}
            >
              <header className="sticky top-0 z-10 flex items-center justify-between rounded-t-xl border-b border-brand-800 bg-brand-900 px-3 py-2 text-xs font-semibold uppercase tracking-wider">
                <span className="text-white/80">
                  {col.key === "hot_lead" ? (
                    <>
                      <span className="hot-lead-flame mr-1">🔥</span>
                      <span className="text-orange-300">Hot Lead</span>
                    </>
                  ) : col.key === "cold_lead" ? (
                    <>
                      <span className="cold-lead-frost mr-1">🧊</span>
                      <span className="text-sky-300">Cold Lead</span>
                    </>
                  ) : col.key === "a_recontacter" ? (
                    <>
                      <span className="mr-1">📅</span>
                      À recontacter
                    </>
                  ) : (
                    col.label
                  )}
                </span>
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
                    <div
                      key={l.id}
                      draggable
                      onDragStart={() => setDragId(l.id)}
                      onDragEnd={() => setDragId(null)}
                      className={`cursor-grab rounded-md border border-brand-800 bg-brand-950 p-2 text-xs transition active:cursor-grabbing ${
                        dragId === l.id ? "opacity-50" : ""
                      }`}
                    >
                      {/* Top : adresse, ville (titre principal). On
                          tombe sur `name` si pas d'adresse encore
                          renseignée. */}
                      <div className="flex items-start justify-between gap-1">
                        <Link
                          // eslint-disable-next-line @typescript-eslint/no-explicit-any
                          href={`/prospection/${l.id}` as any}
                          className="min-w-0 flex-1 truncate font-medium text-white hover:text-emerald-300"
                        >
                          {l.address || l.name}
                          {l.city ? (
                            <span className="text-white/50">
                              , {l.city}
                            </span>
                          ) : null}
                        </Link>
                        <span
                          className={`shrink-0 rounded text-[10px] font-bold tabular-nums ${scoreBadgeClass(
                            l.score
                          )} px-1`}
                        >
                          {l.score}
                        </span>
                      </div>

                      {/* Sous-section : propriétaire. */}
                      {l.owner_name ? (
                        <p className="mt-1 truncate text-[10px] text-white/60">
                          <span className="text-white/40">Propr. </span>
                          {l.owner_name}
                        </p>
                      ) : null}

                      {/* Type d'immeuble + nombre d'unités. */}
                      <p className="mt-0.5 truncate text-[10px] text-white/60">
                        <span className="capitalize">
                          {LEAD_KIND_LABEL[l.kind] || l.kind || "—"}
                        </span>
                        {l.nb_logements != null ? (
                          <span> · {l.nb_logements} unité{l.nb_logements > 1 ? "s" : ""}</span>
                        ) : null}
                      </p>

                      {/* Date de recontact (colonne « À recontacter »). */}
                      {l.recontact_at && col.key === "a_recontacter" ? (
                        <p className="mt-1 truncate text-[10px] text-slate-300">
                          📅 Relance le{" "}
                          {new Date(l.recontact_at).toLocaleDateString(
                            "fr-CA",
                            { day: "numeric", month: "short", year: "numeric" }
                          )}
                        </p>
                      ) : null}

                      {/* Valeur foncière à droite (légère, en bas). */}
                      <div className="mt-1 flex items-center justify-end text-[10px] text-white/40 tabular-nums">
                        {fmtMoneyShort(l.valeur_fonciere)}
                      </div>

                      {l.owner_phone ? (
                        <a
                          href={`tel:${l.owner_phone}`}
                          onClick={(e) => e.stopPropagation()}
                          className="mt-1 block truncate text-[10px] text-emerald-400 hover:text-emerald-300"
                        >
                          📞 {l.owner_phone}
                        </a>
                      ) : null}
                    </div>
                  ))
                )}
              </div>
            </div>
          );
        })}
      </div>
      </div>
    </div>
  );
}

function DeleteLeadButton({
  leadId,
  leadName,
  onDeleted
}: {
  leadId: number;
  leadName: string;
  onDeleted: () => void;
}) {
  const confirm = useConfirm();
  const [busy, setBusy] = useState(false);

  async function handleClick(e: React.MouseEvent) {
    e.stopPropagation();
    const ok = await confirm({
      title: `Supprimer « ${leadName} » ?`,
      description:
        "Le lead sera supprimé définitivement. Cette action est " +
        "irréversible.",
      confirmLabel: "Supprimer",
      destructive: true
    });
    if (!ok) return;
    setBusy(true);
    try {
      const res = await authedFetch(
        `/api/v1/prospection/${leadId}`,
        { method: "DELETE" }
      );
      if (res.ok) onDeleted();
    } finally {
      setBusy(false);
    }
  }

  return (
    <button
      type="button"
      onClick={handleClick}
      disabled={busy}
      className="rounded-md p-1 text-white/30 hover:bg-rose-500/15 hover:text-rose-300 disabled:opacity-30"
      aria-label="Supprimer"
      title="Supprimer ce lead"
    >
      {busy ? (
        <Loader2 className="h-4 w-4 animate-spin" />
      ) : (
        <Trash2 className="h-4 w-4" />
      )}
    </button>
  );
}
