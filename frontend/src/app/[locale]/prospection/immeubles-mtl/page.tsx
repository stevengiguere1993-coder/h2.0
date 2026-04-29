"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Building2,
  CheckCircle2,
  ExternalLink,
  Eye,
  Loader2,
  MapPin,
  Plus,
  RefreshCw,
  Search,
  Users,
  X
} from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { authedFetch } from "@/lib/auth";
import { useProspectionLayout } from "../layout";

type Property = {
  matricule: string;
  civique_debut: string | null;
  nom_rue: string | null;
  suite_debut: string | null;
  municipalite: string | null;
  nombre_logement: number | null;
  annee_construction: number | null;
  code_utilisation: string | null;
  libelle_utilisation: string | null;
  superficie_terrain: number | null;
  superficie_batiment: number | null;
  full_address: string | null;
  already_lead: boolean;
  has_owner_data: boolean;
  owner_names: string[] | null;
};

type UtilisationType = {
  code: string;
  libelle: string | null;
  count: number;
};

type OwnerCandidate = {
  neq: string;
  nom: string | null;
  statut: string | null;
  forme_juridique: string | null;
  adresse: string | null;
  ville: string | null;
  code_postal: string | null;
  telephone: string | null;
};

type ListResponse = {
  total: number;
  properties: Property[];
};

const SIZE_PRESETS = [
  { label: "Tous", min: undefined as number | undefined, max: undefined as number | undefined },
  { label: "4-10", min: 4, max: 10 },
  { label: "11-20", min: 11, max: 20 },
  { label: "20+", min: 20, max: undefined },
  { label: "50+", min: 50, max: undefined },
  { label: "100+", min: 100, max: undefined }
];

export default function ImmeublesMtlPage() {
  const { onOpenSidebar } = useProspectionLayout();
  const [properties, setProperties] = useState<Property[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Filtres
  const [presetIdx, setPresetIdx] = useState(3); // 20+ par défaut
  const [minLogements, setMinLogements] = useState<string>("20");
  const [maxLogements, setMaxLogements] = useState<string>("");
  const [minAnnee, setMinAnnee] = useState<string>("");
  const [maxAnnee, setMaxAnnee] = useState<string>("");
  const [rueSearch, setRueSearch] = useState<string>("");
  const [sortBy, setSortBy] = useState("nombre_logement_desc");
  const [offset, setOffset] = useState(0);
  const limit = 100;

  // Filtre utilisation : liste des codes disponibles (chargée 1×) +
  // ensemble des codes cochés pour la requête.
  const [utilTypes, setUtilTypes] = useState<UtilisationType[]>([]);
  const [selectedCodes, setSelectedCodes] = useState<Set<string>>(
    new Set()
  );
  const [showUtilFilter, setShowUtilFilter] = useState(false);

  // Owner candidates modal
  const [ownerModalFor, setOwnerModalFor] = useState<Property | null>(
    null
  );
  const [streetViewFor, setStreetViewFor] = useState<Property | null>(
    null
  );

  function applyPreset(i: number) {
    setPresetIdx(i);
    const p = SIZE_PRESETS[i];
    setMinLogements(p.min != null ? String(p.min) : "");
    setMaxLogements(p.max != null ? String(p.max) : "");
    setOffset(0);
  }

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams();
      if (minLogements) params.set("min_logements", minLogements);
      if (maxLogements) params.set("max_logements", maxLogements);
      if (minAnnee) params.set("min_annee", minAnnee);
      if (maxAnnee) params.set("max_annee", maxAnnee);
      if (rueSearch.trim())
        params.set("nom_rue_contains", rueSearch.trim());
      // codes_utilisation : multi-valeur, FastAPI accepte
      // ?codes_utilisation=A&codes_utilisation=B
      for (const code of selectedCodes) {
        params.append("codes_utilisation", code);
      }
      params.set("sort_by", sortBy);
      params.set("limit", String(limit));
      params.set("offset", String(offset));

      const res = await authedFetch(
        `/api/v1/prospection/mtl-properties?${params}`
      );
      if (!res.ok) {
        const t = await res.text();
        throw new Error(t.slice(0, 200) || `HTTP ${res.status}`);
      }
      const data = (await res.json()) as ListResponse;
      setProperties(data.properties);
      setTotal(data.total);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, [
    minLogements,
    maxLogements,
    minAnnee,
    maxAnnee,
    rueSearch,
    selectedCodes,
    sortBy,
    offset
  ]);

  // Charge la liste des types d'utilisation au montage. Utilise
  // min_logements pour ne montrer que les types pertinents au
  // périmètre actuel.
  useEffect(() => {
    void (async () => {
      try {
        const params = new URLSearchParams();
        if (minLogements) params.set("min_logements", minLogements);
        const r = await authedFetch(
          `/api/v1/prospection/mtl-properties/utilisation-types?${params}`
        );
        if (!r.ok) return;
        setUtilTypes((await r.json()) as UtilisationType[]);
      } catch {
        /* ignore */
      }
    })();
  }, [minLogements]);

  useEffect(() => {
    void load();
  }, [load]);

  const filteredCount = properties.length;
  const totalPages = Math.ceil(total / limit);
  const currentPage = Math.floor(offset / limit) + 1;

  function fmtArea(n: number | null): string {
    if (n == null) return "—";
    return `${Math.round(n).toLocaleString("fr-CA")} m²`;
  }

  return (
    <>
      <AppTopbar
        breadcrumbs={[
          { label: "Prospection", href: "/prospection" },
          { label: "Immeubles MTL" }
        ]}
        onOpenSidebar={onOpenSidebar}
      />

      <div className="p-4 lg:p-6">
        <header className="flex items-center gap-3">
          <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-emerald-500/15 text-emerald-400">
            <Building2 className="h-5 w-5" />
          </span>
          <div>
            <h1 className="text-2xl font-bold text-white">
              Immeubles — Rôle d&apos;évaluation Montréal
            </h1>
            <p className="text-sm text-white/60">
              Filtre les ~500 000 unités d&apos;évaluation pour
              identifier des cibles d&apos;acquisition. Pour chaque
              immeuble, identifie le proprio (REQ) et convertis en
              lead en 1 clic.
            </p>
          </div>
        </header>

        {/* Filtres */}
        <section className="mt-6 rounded-2xl border border-brand-800 bg-brand-900 p-4">
          {/* Presets nb logements */}
          <div className="mb-3 flex flex-wrap items-center gap-2">
            <span className="text-[11px] uppercase tracking-wider text-white/50">
              Préréglage taille :
            </span>
            {SIZE_PRESETS.map((p, i) => (
              <button
                key={p.label}
                type="button"
                onClick={() => applyPreset(i)}
                className={`rounded-full px-3 py-1 text-xs ${
                  presetIdx === i
                    ? "bg-emerald-500/20 text-emerald-300"
                    : "bg-brand-800 text-white/60 hover:text-white"
                }`}
              >
                {p.label}
              </button>
            ))}
          </div>

          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <div>
              <label className="label">Min logements</label>
              <input
                type="number"
                min="0"
                value={minLogements}
                onChange={(e) => {
                  setMinLogements(e.target.value);
                  setOffset(0);
                }}
                className="input text-sm"
              />
            </div>
            <div>
              <label className="label">Max logements</label>
              <input
                type="number"
                min="0"
                value={maxLogements}
                onChange={(e) => {
                  setMaxLogements(e.target.value);
                  setOffset(0);
                }}
                className="input text-sm"
              />
            </div>
            <div>
              <label className="label">Année min</label>
              <input
                type="number"
                min="1700"
                max="2100"
                value={minAnnee}
                onChange={(e) => {
                  setMinAnnee(e.target.value);
                  setOffset(0);
                }}
                className="input text-sm"
              />
            </div>
            <div>
              <label className="label">Année max</label>
              <input
                type="number"
                min="1700"
                max="2100"
                value={maxAnnee}
                onChange={(e) => {
                  setMaxAnnee(e.target.value);
                  setOffset(0);
                }}
                className="input text-sm"
              />
            </div>
            <div className="lg:col-span-3">
              <label className="label">Nom de rue contient</label>
              <div className="relative">
                <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-white/40" />
                <input
                  type="search"
                  value={rueSearch}
                  onChange={(e) => {
                    setRueSearch(e.target.value);
                    setOffset(0);
                  }}
                  placeholder="Ex: Saint-Laurent, Sherbrooke, …"
                  className="input pl-8 text-sm"
                />
              </div>
            </div>
            <div>
              <label className="label">Trier par</label>
              <select
                value={sortBy}
                onChange={(e) => setSortBy(e.target.value)}
                className="input text-sm"
              >
                <option value="nombre_logement_desc">
                  # logements ↓
                </option>
                <option value="nombre_logement_asc">
                  # logements ↑
                </option>
                <option value="annee_construction_asc">
                  Année construction ↑ (plus ancien d&apos;abord)
                </option>
                <option value="annee_construction_desc">
                  Année construction ↓
                </option>
                <option value="superficie_terrain_desc">
                  Superficie terrain ↓
                </option>
                <option value="matricule_asc">Matricule</option>
              </select>
            </div>
          </div>

          {/* Filtre Type d'utilisation (collapse + checkboxes) */}
          <div className="mt-3 border-t border-brand-800 pt-3">
            <button
              type="button"
              onClick={() => setShowUtilFilter((v) => !v)}
              className="flex w-full items-center justify-between text-sm text-white/80 hover:text-emerald-300"
            >
              <span className="font-medium">
                Type d&apos;utilisation
                {selectedCodes.size > 0 ? (
                  <span className="ml-2 rounded-full bg-emerald-500/15 px-2 py-0.5 text-[10px] text-emerald-300">
                    {selectedCodes.size} cochés
                  </span>
                ) : (
                  <span className="ml-2 text-xs text-white/40">
                    (tous)
                  </span>
                )}
              </span>
              <span className="text-xs text-white/50">
                {showUtilFilter ? "Replier ▲" : "Déplier ▼"}
              </span>
            </button>

            {showUtilFilter ? (
              <div className="mt-3 space-y-2">
                {selectedCodes.size > 0 ? (
                  <button
                    type="button"
                    onClick={() => {
                      setSelectedCodes(new Set());
                      setOffset(0);
                    }}
                    className="text-[11px] text-rose-300 hover:text-rose-200"
                  >
                    × Effacer la sélection ({selectedCodes.size})
                  </button>
                ) : null}
                <div className="grid max-h-72 grid-cols-1 gap-1.5 overflow-y-auto rounded-md border border-brand-800 bg-brand-950 p-2 sm:grid-cols-2 lg:grid-cols-3">
                  {utilTypes.length === 0 ? (
                    <p className="col-span-full text-xs text-white/40">
                      Aucun type chargé. Vérifie que les données MTL
                      sont importées.
                    </p>
                  ) : (
                    utilTypes.map((t) => {
                      const checked = selectedCodes.has(t.code);
                      return (
                        <label
                          key={t.code}
                          className={`flex cursor-pointer items-center gap-2 rounded px-2 py-1 text-[11px] transition ${
                            checked
                              ? "bg-emerald-500/15 text-emerald-200"
                              : "text-white/70 hover:bg-brand-900"
                          }`}
                        >
                          <input
                            type="checkbox"
                            checked={checked}
                            onChange={(e) => {
                              const next = new Set(selectedCodes);
                              if (e.target.checked) next.add(t.code);
                              else next.delete(t.code);
                              setSelectedCodes(next);
                              setOffset(0);
                            }}
                            className="h-3.5 w-3.5 rounded border-brand-700 bg-brand-900 text-emerald-500 focus:ring-emerald-500"
                          />
                          <span className="flex-1 truncate">
                            <span className="font-mono text-[10px] text-white/40">
                              {t.code}
                            </span>{" "}
                            {t.libelle || "(sans libellé)"}
                          </span>
                          <span className="shrink-0 text-[10px] text-white/40">
                            {t.count.toLocaleString("fr-CA")}
                          </span>
                        </label>
                      );
                    })
                  )}
                </div>
              </div>
            ) : null}
          </div>
        </section>

        {/* Stats + pagination */}
        <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
          <p className="text-xs text-white/60">
            {loading ? (
              <Loader2 className="inline h-3 w-3 animate-spin" />
            ) : (
              <>
                <span className="font-bold text-emerald-300">
                  {total.toLocaleString("fr-CA")}
                </span>{" "}
                propriété{total > 1 ? "s" : ""} matchent les filtres ·
                affichage {offset + 1}-{offset + filteredCount}
              </>
            )}
          </p>
          {totalPages > 1 ? (
            <div className="flex items-center gap-2 text-xs">
              <button
                type="button"
                disabled={offset === 0}
                onClick={() => setOffset(Math.max(0, offset - limit))}
                className="rounded border border-brand-700 bg-brand-900 px-2 py-1 text-white/70 disabled:opacity-30"
              >
                ← Précédent
              </button>
              <span className="text-white/50">
                Page {currentPage} / {totalPages}
              </span>
              <button
                type="button"
                disabled={offset + limit >= total}
                onClick={() => setOffset(offset + limit)}
                className="rounded border border-brand-700 bg-brand-900 px-2 py-1 text-white/70 disabled:opacity-30"
              >
                Suivant →
              </button>
            </div>
          ) : null}
        </div>

        {error ? (
          <p className="mt-3 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-300">
            {error}
            {error.includes("500") || error.includes("serveur") ? (
              <span className="mt-1 block text-xs text-rose-200">
                Le rôle Montréal n&apos;est peut-être pas encore importé
                en DB. Lance{" "}
                <code className="rounded bg-rose-500/20 px-1">
                  python -m scripts.import_montreal_roles
                </code>{" "}
                depuis le Render Shell.
              </span>
            ) : null}
          </p>
        ) : null}

        {/* Tableau */}
        <div className="mt-4 overflow-hidden rounded-xl border border-brand-800 bg-brand-900">
          {loading && properties.length === 0 ? (
            <div className="flex items-center justify-center py-12">
              <Loader2 className="h-6 w-6 animate-spin text-emerald-500" />
            </div>
          ) : properties.length === 0 ? (
            <div className="p-12 text-center">
              <Building2 className="mx-auto h-8 w-8 text-white/20" />
              <p className="mt-3 text-sm text-white/50">
                Aucune propriété ne correspond aux filtres.
              </p>
              <p className="mt-1 text-[11px] text-white/40">
                Si la table est vide, il faut d&apos;abord importer le
                rôle Montréal (voir Sources de données).
              </p>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="bg-brand-950/60 text-left text-[11px] uppercase tracking-wider text-white/50">
                  <tr>
                    <th className="px-3 py-2.5">Adresse</th>
                    <th className="px-3 py-2.5 text-right">
                      # logements
                    </th>
                    <th className="px-3 py-2.5 text-right">Année</th>
                    <th className="px-3 py-2.5 text-right">Terrain</th>
                    <th className="px-3 py-2.5">Utilisation</th>
                    <th className="px-3 py-2.5">Propriétaire</th>
                    <th className="px-3 py-2.5">Matricule</th>
                    <th className="px-3 py-2.5">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-brand-800">
                  {properties.map((p) => (
                    <tr
                      key={p.matricule}
                      className="transition hover:bg-brand-800/40"
                    >
                      <td className="px-3 py-2.5 text-white/80">
                        <button
                          type="button"
                          onClick={() => setStreetViewFor(p)}
                          className="text-left hover:text-emerald-300 hover:underline"
                          title="Ouvrir Street View"
                        >
                          {p.full_address || "—"}
                        </button>
                        {p.municipalite ? (
                          <div className="text-[10px] text-white/40">
                            {p.municipalite}
                          </div>
                        ) : null}
                      </td>
                      <td className="px-3 py-2.5 text-right tabular-nums font-bold text-emerald-300">
                        {p.nombre_logement ?? "—"}
                      </td>
                      <td className="px-3 py-2.5 text-right tabular-nums text-white/70">
                        {p.annee_construction ?? "—"}
                      </td>
                      <td className="px-3 py-2.5 text-right tabular-nums text-white/70">
                        {fmtArea(p.superficie_terrain)}
                      </td>
                      <td className="px-3 py-2.5 text-[11px] text-white/60">
                        {p.libelle_utilisation || "—"}
                      </td>
                      <td className="px-3 py-2.5 max-w-[180px]">
                        {p.owner_names && p.owner_names.length > 0 ? (
                          <button
                            type="button"
                            onClick={() => setOwnerModalFor(p)}
                            className="text-left text-[11px] text-emerald-300 hover:text-emerald-200 hover:underline"
                            title="Voir les détails du propriétaire"
                          >
                            {p.owner_names.length === 1 ? (
                              <span className="line-clamp-2">
                                {p.owner_names[0]}
                              </span>
                            ) : (
                              <span>
                                <span className="line-clamp-1">
                                  {p.owner_names[0]}
                                </span>
                                <span className="text-[10px] text-white/40">
                                  +{p.owner_names.length - 1} autre
                                  {p.owner_names.length > 2 ? "s" : ""}
                                </span>
                              </span>
                            )}
                          </button>
                        ) : (
                          <span className="text-[11px] text-white/30">—</span>
                        )}
                      </td>
                      <td className="px-3 py-2.5 font-mono text-[10px] text-white/40">
                        {p.matricule}
                      </td>
                      <td className="px-3 py-2.5">
                        <div className="flex flex-wrap gap-1">
                          <button
                            type="button"
                            onClick={() => setStreetViewFor(p)}
                            className="inline-flex items-center gap-1 rounded-md border border-amber-500/40 bg-amber-500/10 px-2 py-1 text-[10px] text-amber-300 hover:bg-amber-500/20"
                            title="Street View"
                          >
                            <Eye className="h-3 w-3" />
                            Voir
                          </button>
                          <button
                            type="button"
                            onClick={() => setOwnerModalFor(p)}
                            className={`inline-flex items-center gap-1 rounded-md border px-2 py-1 text-[10px] ${
                              p.has_owner_data
                                ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-300 hover:bg-emerald-500/20"
                                : "border-blue-500/40 bg-blue-500/10 text-blue-300 hover:bg-blue-500/20"
                            }`}
                            title={
                              p.has_owner_data
                                ? "Propriétaires déjà documentés — clic pour voir"
                                : "Documenter les propriétaires"
                            }
                          >
                            {p.has_owner_data ? (
                              <CheckCircle2 className="h-3 w-3" />
                            ) : (
                              <Users className="h-3 w-3" />
                            )}
                            Proprio
                          </button>
                          {p.already_lead ? (
                            <span className="inline-flex items-center gap-1 rounded-md border border-emerald-500/40 bg-emerald-500/10 px-2 py-1 text-[10px] text-emerald-300">
                              <CheckCircle2 className="h-3 w-3" />
                              Lead
                            </span>
                          ) : (
                            <ConvertButton property={p} />
                          )}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>

      {ownerModalFor ? (
        <OwnerCandidatesModal
          property={ownerModalFor}
          onClose={() => setOwnerModalFor(null)}
          onConverted={() => {
            setOwnerModalFor(null);
            void load();
          }}
        />
      ) : null}

      {streetViewFor ? (
        <StreetViewModal
          property={streetViewFor}
          onClose={() => setStreetViewFor(null)}
        />
      ) : null}
    </>
  );
}

function StreetViewModal({
  property,
  onClose
}: {
  property: Property;
  onClose: () => void;
}) {
  const fullAddr = property.full_address || "";
  // svembed = iframe Google Maps lite, pas besoin de clé API.
  // L'address suffit comme paramètre de recherche.
  const svSrc = `https://maps.google.com/maps?q=${encodeURIComponent(
    fullAddr + ", Montréal, QC"
  )}&layer=c&output=svembed`;
  const satSrc = `https://maps.google.com/maps?q=${encodeURIComponent(
    fullAddr + ", Montréal, QC"
  )}&t=k&z=19&output=embed`;
  const gmapsUrl = `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(
    fullAddr + ", Montréal, QC"
  )}`;

  return (
    <div
      onClick={onClose}
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 p-4 backdrop-blur-sm"
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="w-full max-w-4xl overflow-hidden rounded-2xl border border-brand-800 bg-brand-950"
      >
        <div className="flex items-start justify-between gap-3 border-b border-brand-800 bg-brand-900/50 px-5 py-3">
          <div>
            <h2 className="flex items-center gap-2 text-base font-bold text-white">
              <Eye className="h-5 w-5 text-amber-400" />
              {fullAddr}
            </h2>
            <p className="mt-0.5 text-[11px] text-white/50">
              Matricule {property.matricule} ·{" "}
              {property.nombre_logement ?? "?"} logements
              {property.annee_construction
                ? ` · ${property.annee_construction}`
                : ""}
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md p-1 text-white/40 hover:bg-brand-800 hover:text-white"
            aria-label="Fermer"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="grid gap-2 p-3 sm:grid-cols-2">
          <div className="overflow-hidden rounded-lg border border-brand-800 bg-black">
            <p className="border-b border-brand-800 bg-brand-900/40 px-3 py-1.5 text-[11px] uppercase tracking-wider text-amber-300">
              Street View
            </p>
            <iframe
              src={svSrc}
              className="h-72 w-full"
              loading="lazy"
              referrerPolicy="no-referrer-when-downgrade"
              title="Street View"
            />
          </div>
          <div className="overflow-hidden rounded-lg border border-brand-800 bg-black">
            <p className="border-b border-brand-800 bg-brand-900/40 px-3 py-1.5 text-[11px] uppercase tracking-wider text-emerald-300">
              Vue satellite
            </p>
            <iframe
              src={satSrc}
              className="h-72 w-full"
              loading="lazy"
              referrerPolicy="no-referrer-when-downgrade"
              title="Satellite"
            />
          </div>
        </div>

        <div className="flex flex-wrap items-center justify-end gap-2 border-t border-brand-800 bg-brand-900/30 px-5 py-3">
          <a
            href={gmapsUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1.5 rounded-lg border border-brand-700 px-3 py-1.5 text-xs text-white/80 hover:bg-brand-800"
          >
            <ExternalLink className="h-3 w-3" />
            Ouvrir dans Google Maps
          </a>
        </div>
      </div>
    </div>
  );
}

function ConvertButton({ property }: { property: Property }) {
  const [busy, setBusy] = useState(false);
  async function convert() {
    if (busy) return;
    setBusy(true);
    try {
      const res = await authedFetch(
        `/api/v1/prospection/mtl-properties/${encodeURIComponent(
          property.matricule
        )}/convert-to-lead`,
        { method: "POST" }
      );
      if (!res.ok) {
        const t = await res.text();
        alert(t.slice(0, 200) || `HTTP ${res.status}`);
        return;
      }
      const data = (await res.json()) as { lead_id: number };
      window.location.href = `/prospection/${data.lead_id}`;
    } finally {
      setBusy(false);
    }
  }
  return (
    <button
      type="button"
      onClick={convert}
      disabled={busy}
      className="inline-flex items-center gap-1 rounded-md border border-emerald-500/40 bg-emerald-500/10 px-2 py-1 text-[10px] text-emerald-300 hover:bg-emerald-500/20 disabled:opacity-50"
    >
      {busy ? (
        <Loader2 className="h-3 w-3 animate-spin" />
      ) : (
        <Plus className="h-3 w-3" />
      )}
      Ajouter
    </button>
  );
}

type EvalWebOwner = {
  name: string;
  statut: string | null;
  postal_address: string | null;
  inscription_date: string | null;
  conditions: string | null;
  // Champs ajoutés par l'enrichissement auto (REQ + Canada411)
  phone: string | null;
  phone_source: string | null;
  req_neq: string | null;
  req_status: string | null;
  req_forme_juridique: string | null;
  req_address: string | null;
  req_ville: string | null;
  req_code_postal: string | null;
  c411_address: string | null;
};

type EvalWebResponse = {
  matricule: string;
  owners: EvalWebOwner[];
  fetched_at: string | null;
  cached: boolean;
};

function OwnerCandidatesModal({
  property,
  onClose,
  onConverted
}: {
  property: Property;
  onClose: () => void;
  onConverted: () => void;
}) {
  const [candidates, setCandidates] = useState<OwnerCandidate[]>([]);
  const [loading, setLoading] = useState(true);
  const [converting, setConverting] = useState<string | null>(null);

  // EvalWeb (rôle) — fetch on demand
  const [evalLoading, setEvalLoading] = useState(false);
  const [evalData, setEvalData] = useState<EvalWebResponse | null>(null);
  const [evalError, setEvalError] = useState<string | null>(null);
  // Fallback collage manuel
  const [showPaste, setShowPaste] = useState(false);
  const [pasteText, setPasteText] = useState("");
  const [pasteSubmitting, setPasteSubmitting] = useState(false);

  async function submitPaste() {
    if (!pasteText.trim()) return;
    setPasteSubmitting(true);
    setEvalError(null);
    try {
      const r = await authedFetch(
        `/api/v1/prospection/mtl-properties/${encodeURIComponent(
          property.matricule
        )}/owner-evalweb-manual`,
        {
          method: "POST",
          body: JSON.stringify({ text: pasteText })
        }
      );
      if (!r.ok) {
        const err = await r.json().catch(() => ({}));
        throw new Error(err.detail || `HTTP ${r.status}`);
      }
      setEvalData((await r.json()) as EvalWebResponse);
      setShowPaste(false);
      setPasteText("");
    } catch (e) {
      setEvalError(e instanceof Error ? e.message : "Erreur");
    } finally {
      setPasteSubmitting(false);
    }
  }

  async function fetchEvalWeb(refresh = false) {
    setEvalLoading(true);
    setEvalError(null);
    try {
      const url =
        `/api/v1/prospection/mtl-properties/${encodeURIComponent(
          property.matricule
        )}/owner-evalweb` + (refresh ? "?refresh=true" : "");
      const r = await authedFetch(url);
      if (!r.ok) {
        const err = await r.json().catch(() => ({}));
        throw new Error(err.detail || `HTTP ${r.status}`);
      }
      setEvalData((await r.json()) as EvalWebResponse);
    } catch (e) {
      setEvalError(e instanceof Error ? e.message : "Erreur");
    } finally {
      setEvalLoading(false);
    }
  }

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const r = await authedFetch(
          `/api/v1/prospection/mtl-properties/${encodeURIComponent(
            property.matricule
          )}/owner-candidates`
        );
        if (!r.ok) throw new Error();
        const data = (await r.json()) as OwnerCandidate[];
        if (!cancelled) setCandidates(data);
      } catch {
        if (!cancelled) setCandidates([]);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();

    // Si on a déjà des données EvalWeb cachées pour cette propriété,
    // on les charge automatiquement (cache_only=true → pas de scrape).
    if (property.has_owner_data) {
      void (async () => {
        try {
          const r = await authedFetch(
            `/api/v1/prospection/mtl-properties/${encodeURIComponent(
              property.matricule
            )}/owner-evalweb?cache_only=true`
          );
          if (!r.ok) return;
          const data = (await r.json()) as EvalWebResponse;
          if (!cancelled && data.owners.length > 0) {
            setEvalData(data);
          }
        } catch {
          /* ignore */
        }
      })();
    }

    return () => {
      cancelled = true;
    };
  }, [property.matricule, property.has_owner_data]);

  // Polling de l'extension navigateur : si l'utilisateur a l'extension
  // Horizon installée et qu'il navigue sur la fiche montreal.ca de ce
  // matricule dans un autre onglet, les données arriveront en DB
  // (owners_json) via POST /api/v1/extension/evalweb-owners. On polle
  // toutes les 3s tant qu'on n'a pas de données affichées.
  useEffect(() => {
    if (evalData && evalData.owners.length > 0) return;
    let cancelled = false;
    const intervalId = setInterval(async () => {
      try {
        const r = await authedFetch(
          `/api/v1/prospection/mtl-properties/${encodeURIComponent(
            property.matricule
          )}/owner-evalweb?cache_only=true`
        );
        if (!r.ok) return;
        const data = (await r.json()) as EvalWebResponse;
        if (!cancelled && data.owners.length > 0) {
          setEvalData(data);
        }
      } catch {
        /* ignore */
      }
    }, 3000);
    return () => {
      cancelled = true;
      clearInterval(intervalId);
    };
  }, [property.matricule, evalData]);

  async function convertWithOwner(neq: string | null) {
    setConverting(neq || "no-neq");
    try {
      const params = new URLSearchParams();
      if (neq) params.set("owner_neq", neq);
      const res = await authedFetch(
        `/api/v1/prospection/mtl-properties/${encodeURIComponent(
          property.matricule
        )}/convert-to-lead?${params}`,
        { method: "POST" }
      );
      if (!res.ok) {
        const t = await res.text();
        alert(t.slice(0, 200));
        return;
      }
      const data = (await res.json()) as { lead_id: number };
      onConverted();
      window.location.href = `/prospection/${data.lead_id}`;
    } finally {
      setConverting(null);
    }
  }

  return (
    <div
      className="fixed inset-0 z-[1000] flex items-center justify-center bg-black/70 p-4"
      role="dialog"
      aria-modal="true"
    >
      <div className="flex max-h-[90vh] w-full max-w-2xl flex-col overflow-hidden rounded-2xl border border-brand-800 bg-brand-950">
        <header className="flex items-start justify-between gap-3 border-b border-brand-800 p-4">
          <div className="min-w-0">
            <h2 className="flex items-center gap-2 text-sm font-semibold text-white">
              <Users className="h-4 w-4 text-emerald-400" />
              Propriétaires candidats
            </h2>
            <p className="mt-1 text-xs text-white/60">
              <MapPin className="mr-1 inline h-3 w-3" />
              {property.full_address}
              {property.municipalite ? ` · ${property.municipalite}` : ""}
            </p>
            <p className="mt-0.5 font-mono text-[10px] text-white/40">
              Matricule {property.matricule}
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md p-1 text-white/40 hover:bg-brand-900 hover:text-white"
          >
            <X className="h-4 w-4" />
          </button>
        </header>

        <div className="flex-1 overflow-y-auto p-4">
          {/* EvalWeb (rôle d'évaluation MTL) — source primaire. */}
          <section className="mb-4 rounded-lg border border-emerald-500/30 bg-emerald-500/5 p-3">
            <div className="mb-2 flex items-center justify-between gap-2">
              <h3 className="text-[11px] font-semibold uppercase tracking-wider text-emerald-300">
                Propriétaires au rôle (EvalWeb)
              </h3>
              <div className="flex items-center gap-1.5">
                <button
                  type="button"
                  onClick={() => {
                    // Demande à l'extension d'ouvrir montreal.ca dans
                    // un onglet en arrière-plan (focus reste ici), de
                    // piloter le flow 4 étapes, scraper, puis fermer
                    // l'onglet. Si l'extension n'est pas installée, on
                    // fallback sur window.open visible.
                    const matricule = property.matricule;
                    const hasExtension = (window as unknown as { __h2_extension?: string }).__h2_extension;
                    if (hasExtension) {
                      window.postMessage(
                        { type: "h2_open_evalweb", matricule },
                        "*"
                      );
                    } else {
                      const url = `https://montreal.ca/role-evaluation-fonciere?h2matricule=${encodeURIComponent(matricule)}`;
                      window.open(url, "_blank", "noopener");
                    }
                  }}
                  className="inline-flex items-center gap-1 rounded-md border border-emerald-400 bg-emerald-500/20 px-2 py-1 text-[10px] font-semibold text-emerald-200 hover:bg-emerald-500/30"
                  title="L'extension Horizon ouvre montreal.ca en arrière-plan, scrape, et envoie les données ici"
                >
                  <Search className="h-3 w-3" />
                  Récupérer (auto)
                </button>
                <button
                  type="button"
                  onClick={() => fetchEvalWeb(!!evalData)}
                  disabled={evalLoading}
                  className="inline-flex items-center gap-1 rounded-md border border-emerald-500/40 bg-emerald-500/10 px-2 py-1 text-[10px] text-emerald-300 hover:bg-emerald-500/20 disabled:opacity-50"
                  title="Tente le scraper VPS (peut être bloqué par reCAPTCHA)"
                >
                  {evalLoading ? (
                    <Loader2 className="h-3 w-3 animate-spin" />
                  ) : evalData ? (
                    <RefreshCw className="h-3 w-3" />
                  ) : (
                    <Search className="h-3 w-3" />
                  )}
                  {evalLoading
                    ? "…"
                    : evalData
                      ? "Rafraîchir"
                      : "VPS"}
                </button>
              </div>
            </div>

            {!evalData && !evalLoading && !evalError ? (
              <div className="space-y-2">
                <p className="text-[11px] text-white/50">
                  Clique <strong>« Récupérer (auto) »</strong> :
                  l&apos;extension Horizon ouvre montreal.ca dans un nouvel
                  onglet, navigue automatiquement jusqu&apos;à la fiche du
                  matricule, scrape les propriétaires et les renvoie ici
                  (~10-15 secondes). Cette modale se met à jour
                  automatiquement.
                </p>
                <p className="text-[10px] text-white/40">
                  Pas l&apos;extension ? Va dans{" "}
                  <a
                    href="/prospection/parametres/outils"
                    className="underline hover:text-white/60"
                  >
                    Paramètres → Outils
                  </a>{" "}
                  pour la télécharger (1 fois, ~2 min).
                </p>
              </div>
            ) : null}

            {evalError ? (
              <div className="rounded border border-rose-500/40 bg-rose-500/10 p-2 text-[11px] text-rose-300">
                <p>{evalError}</p>
                <button
                  type="button"
                  onClick={() => {
                    setShowPaste(true);
                    setEvalError(null);
                  }}
                  className="mt-2 inline-flex items-center gap-1 rounded border border-emerald-500/40 bg-emerald-500/10 px-2 py-1 text-[10px] text-emerald-300 hover:bg-emerald-500/20"
                >
                  Saisir manuellement →
                </button>
              </div>
            ) : null}

            {/* Fallback : collage manuel depuis EvalWeb */}
            {!evalData && (showPaste || evalError) ? (
              <div className="mt-2 rounded border border-emerald-700/40 bg-brand-900 p-2.5">
                <p className="text-[11px] font-semibold text-emerald-200">
                  Collage manuel depuis EvalWeb
                </p>
                <ol className="mt-1.5 list-decimal space-y-0.5 pl-4 text-[10px] text-white/60">
                  <li>
                    Ouvre EvalWeb pour cette propriété :{" "}
                    <a
                      href="https://montreal.ca/role-evaluation-fonciere"
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-emerald-300 underline hover:text-emerald-200"
                    >
                      ouvrir le site
                    </a>{" "}
                    et cherche le matricule{" "}
                    <code className="text-white/80">
                      {property.matricule}
                    </code>
                  </li>
                  <li>
                    Sélectionne tout le bloc « Propriétaire » (du label
                    « Nom » jusqu&apos;avant « Caractéristiques ») et
                    fais Ctrl+C
                  </li>
                  <li>Colle ci-dessous puis valide</li>
                </ol>
                <textarea
                  value={pasteText}
                  onChange={(e) => setPasteText(e.target.value)}
                  rows={6}
                  placeholder={
                    "Nom\nGEREMIA, ROBERTO (Emphytéote)\nStatut aux fins d'imposition scolaire\nPersonne physique\nAdresse postale\n450 CH DU GOLF, VERDUN QUEBEC, H3E 1A8\n…"
                  }
                  className="mt-2 w-full rounded border border-brand-800 bg-brand-950 p-2 font-mono text-[10px] text-white"
                />
                <div className="mt-2 flex items-center gap-2">
                  <button
                    type="button"
                    onClick={submitPaste}
                    disabled={
                      pasteSubmitting || !pasteText.trim()
                    }
                    className="inline-flex items-center gap-1 rounded-md bg-emerald-500 px-3 py-1.5 text-[11px] font-semibold text-brand-950 hover:bg-emerald-400 disabled:opacity-50"
                  >
                    {pasteSubmitting ? (
                      <Loader2 className="h-3 w-3 animate-spin" />
                    ) : null}
                    Parser et sauvegarder
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      setShowPaste(false);
                      setPasteText("");
                    }}
                    className="text-[11px] text-white/50 hover:text-white"
                  >
                    Annuler
                  </button>
                </div>
              </div>
            ) : null}

            {evalData ? (
              evalData.owners.length === 0 ? (
                <p className="text-[11px] text-white/50">
                  Aucun propriétaire trouvé pour ce matricule.
                </p>
              ) : (
                <ul className="space-y-2">
                  {evalData.owners.map((o, i) => (
                    <li
                      key={i}
                      className="rounded-md border border-brand-800 bg-brand-900 p-2.5"
                    >
                      <p className="text-sm font-semibold text-white">
                        {o.name}
                      </p>
                      <div className="mt-0.5 flex flex-wrap items-center gap-2 text-[10px] text-white/50">
                        {o.statut ? <span>{o.statut}</span> : null}
                        {o.req_neq ? (
                          <span className="rounded-full bg-blue-500/15 px-1.5 py-0.5 text-blue-300">
                            REQ : {o.req_neq}
                          </span>
                        ) : null}
                        {o.conditions ? (
                          <span className="rounded-full bg-amber-500/15 px-1.5 py-0.5 text-amber-300">
                            {o.conditions}
                          </span>
                        ) : null}
                      </div>
                      {o.postal_address ? (
                        <p className="mt-1 text-[11px] text-white/70">
                          <MapPin className="mr-1 inline h-3 w-3" />
                          {o.postal_address}
                        </p>
                      ) : null}
                      {/* Téléphone trouvé (REQ ou Canada411) */}
                      {o.phone ? (
                        <p className="mt-1 text-[11px] text-emerald-300">
                          📞{" "}
                          <a
                            href={`tel:${o.phone}`}
                            className="hover:text-emerald-200"
                          >
                            {o.phone}
                          </a>
                          <span className="ml-1 text-[10px] text-white/40">
                            ({o.phone_source === "req"
                              ? "REQ"
                              : o.phone_source === "canada411"
                                ? "Canada411"
                                : ""}
                            )
                          </span>
                        </p>
                      ) : null}
                      {/* Adresse REQ (siège social corp) */}
                      {o.req_address ? (
                        <p className="mt-0.5 text-[10px] text-blue-300/70">
                          Siège REQ : {o.req_address}
                          {o.req_ville ? `, ${o.req_ville}` : ""}
                          {o.req_code_postal
                            ? ` ${o.req_code_postal}`
                            : ""}
                        </p>
                      ) : null}
                      {o.inscription_date ? (
                        <p className="mt-0.5 text-[10px] text-white/40">
                          Inscrit au rôle : {o.inscription_date}
                        </p>
                      ) : null}
                    </li>
                  ))}
                </ul>
              )
            ) : null}

            {evalData?.fetched_at ? (
              <p className="mt-2 text-[10px] text-white/30">
                Récupéré le{" "}
                {new Date(evalData.fetched_at).toLocaleDateString(
                  "fr-CA"
                )}
                {evalData.cached ? " (cache)" : ""}
              </p>
            ) : null}
          </section>

          <h3 className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-blue-300">
            Corporations REQ candidates
          </h3>

          {loading ? (
            <div className="flex justify-center py-8">
              <Loader2 className="h-5 w-5 animate-spin text-emerald-500" />
            </div>
          ) : candidates.length === 0 ? (
            <div className="rounded-md border border-amber-500/30 bg-amber-500/5 p-3 text-xs text-amber-200">
              Aucune corporation REQ avec adresse postale matchant cette
              propriété.
              <br />
              <span className="text-amber-200/60">
                Soit le proprio est un particulier (pas dans le REQ —
                voir la section EvalWeb ci-dessus), soit la corporation
                a une adresse différente.
              </span>
            </div>
          ) : (
            <ul className="space-y-2">
              {candidates.map((c) => (
                <li
                  key={c.neq}
                  className="rounded-md border border-brand-800 bg-brand-900 p-3"
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0 flex-1">
                      <p className="font-medium text-white">
                        {c.nom || "(sans nom)"}
                      </p>
                      <p className="mt-0.5 font-mono text-[10px] text-white/40">
                        NEQ {c.neq}
                      </p>
                      <p className="mt-1 text-[11px] text-white/60">
                        {c.adresse}
                        {c.ville ? `, ${c.ville}` : ""}
                        {c.code_postal ? ` ${c.code_postal}` : ""}
                      </p>
                      {c.telephone ? (
                        <p className="mt-0.5 text-[11px] text-emerald-300">
                          📞 {c.telephone}
                        </p>
                      ) : null}
                      {c.statut ? (
                        <span className="mt-1 inline-block rounded-full bg-brand-800 px-1.5 py-0.5 text-[10px] text-white/60">
                          {c.statut}
                        </span>
                      ) : null}
                    </div>
                    <button
                      type="button"
                      onClick={() => convertWithOwner(c.neq)}
                      disabled={converting !== null}
                      className="inline-flex shrink-0 items-center gap-1 rounded-md border border-emerald-500/40 bg-emerald-500/10 px-2.5 py-1.5 text-[11px] text-emerald-300 hover:bg-emerald-500/20 disabled:opacity-50"
                    >
                      {converting === c.neq ? (
                        <Loader2 className="h-3 w-3 animate-spin" />
                      ) : (
                        <Plus className="h-3 w-3" />
                      )}
                      Lead avec ce proprio
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>

        <footer className="flex items-center justify-between gap-2 border-t border-brand-800 p-3">
          <p className="text-[10px] text-white/40">
            Le matching se fait par adresse postale du siège REQ.
            Précision ~70-80 %.
          </p>
          <button
            type="button"
            onClick={() => convertWithOwner(null)}
            disabled={converting !== null || property.already_lead}
            className="inline-flex items-center gap-1 rounded-md border border-brand-700 bg-brand-900 px-2.5 py-1.5 text-[11px] text-white/70 hover:text-white disabled:opacity-50"
          >
            {converting === "no-neq" ? (
              <Loader2 className="h-3 w-3 animate-spin" />
            ) : (
              <Plus className="h-3 w-3" />
            )}
            {evalData && evalData.owners.length > 0
              ? "Créer lead avec proprio EvalWeb"
              : "Créer lead sans proprio"}
          </button>
        </footer>
      </div>
    </div>
  );
}
