"use client";

import { useEffect, useMemo, useState } from "react";
import {
  ArrowDown,
  ArrowUp,
  ArrowUpDown,
  Download,
  Loader2,
  MapPin,
  Plus,
  Search,
  Star
} from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
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
  score: number;
  tags: string[];
  photos_count: number;
  created_at: string;
};

const STATUS_LABEL: Record<string, string> = {
  a_visiter: "À visiter",
  visite: "Visité",
  a_contacter: "À contacter",
  contacte: "Contacté",
  soumissionne: "Soumissionné",
  converti: "Converti",
  perdu: "Perdu"
};

const STATUS_COLOR: Record<string, string> = {
  a_visiter: "bg-emerald-500/20 text-emerald-300",
  visite: "bg-blue-500/20 text-blue-300",
  a_contacter: "bg-amber-500/20 text-amber-300",
  contacte: "bg-violet-500/20 text-violet-300",
  soumissionne: "bg-pink-500/20 text-pink-300",
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
    maximumFractionDigits: 0
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

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const res = await authedFetch(
          "/api/v1/prospection?limit=1000&archived=false"
        );
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = (await res.json()) as Lead[];
        if (!cancelled) setLeads(data);
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
          <div className="flex items-center gap-2">
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
              Nouveau (mobile)
            </Link>
          </div>
        }
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
                    <th
                      onClick={() => toggleSort("name")}
                      className="cursor-pointer px-3 py-2.5 hover:text-white"
                    >
                      Nom
                      <SortIcon k="name" />
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
                      <td className="px-3 py-2.5">
                        <Link
                          // eslint-disable-next-line @typescript-eslint/no-explicit-any
                          href={`/prospection/${l.id}` as any}
                          className="font-medium text-white hover:text-emerald-300"
                        >
                          {l.name}
                        </Link>
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
                      <td className="px-3 py-2.5 text-white/60">
                        {KIND_LABEL[l.kind] || l.kind}
                      </td>
                      <td className="px-3 py-2.5 text-white/70">
                        {l.address ? (
                          <>
                            <div>{l.address}</div>
                            {l.city ? (
                              <div className="text-[11px] text-white/40">
                                {l.city}
                              </div>
                            ) : null}
                          </>
                        ) : (
                          <span className="text-white/30">—</span>
                        )}
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
                        {l.owner_kind === "corporation" ? (
                          <span className="ml-1 rounded bg-violet-500/15 px-1 py-0.5 text-[10px] text-violet-300">
                            corp
                          </span>
                        ) : null}
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
