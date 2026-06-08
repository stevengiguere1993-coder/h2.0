"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  AlertTriangle,
  Info,
  Loader2,
  MapPin,
  Newspaper,
  Plus,
  Search,
  TrendingUp,
  Trash2,
  X
} from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { authedFetch } from "@/lib/auth";
import { useProspectionLayout } from "../layout";

// ─────────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────────

type Comparable = {
  id: number;
  address_full: string | null;
  civique: string | null;
  nom_rue: string | null;
  municipalite: string | null;
  price: number | null;
  date_sold: string | null;
  nb_logement: number | null;
  annee_construction: number | null;
  superficie_terrain: number | null;
  libelle_utilisation: string | null;
  source: string | null;
  source_url: string | null;
};

type ComparablesResponse = {
  total: number;
  comparables: Comparable[];
};

type AddressSuggestion = {
  matricule: string;
  civique: string | null;
  nom_rue: string | null;
  municipalite: string | null;
  label: string;
};

type HealthResponse = {
  journal_source_configured?: boolean;
  // Champs additionnels tolérés sans casser le typage.
  [key: string]: unknown;
};

// ─────────────────────────────────────────────────────────────────────────
// Helpers de formatage
// ─────────────────────────────────────────────────────────────────────────

function fmtPrice(n: number | null): string {
  if (n == null) return "—";
  // Ex. 1 250 000 $ — format CA, sans décimales.
  return `${Math.round(n).toLocaleString("fr-CA")} $`;
}

function fmtDate(d: string | null): string {
  if (!d) return "—";
  // Tolère "YYYY-MM-DD" ou ISO complet. On évite un parse Date() qui
  // décale d'un jour avec les fuseaux horaires sur les dates seules.
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(d);
  if (m) {
    const dt = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
    return dt.toLocaleDateString("fr-CA", {
      year: "numeric",
      month: "short",
      day: "numeric"
    });
  }
  const dt = new Date(d);
  return Number.isNaN(dt.getTime())
    ? d
    : dt.toLocaleDateString("fr-CA", {
        year: "numeric",
        month: "short",
        day: "numeric"
      });
}

function fmtArea(n: number | null): string {
  if (n == null) return "—";
  return `${Math.round(n).toLocaleString("fr-CA")} m²`;
}

function comparableAddress(c: Comparable): string {
  if (c.address_full) return c.address_full;
  const parts = [c.civique, c.nom_rue].filter(Boolean).join(" ").trim();
  return parts || "—";
}

// ─────────────────────────────────────────────────────────────────────────
// Page
// ─────────────────────────────────────────────────────────────────────────

export default function ComparablesPage() {
  const { onOpenSidebar } = useProspectionLayout();

  const [comparables, setComparables] = useState<Comparable[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [searched, setSearched] = useState(false);

  // Adresse + autocomplete
  const [address, setAddress] = useState("");
  const [matricule, setMatricule] = useState<string | null>(null);
  const [suggestions, setSuggestions] = useState<AddressSuggestion[]>([]);
  const [suggestOpen, setSuggestOpen] = useState(false);
  const [suggestLoading, setSuggestLoading] = useState(false);
  const addrWrapRef = useRef<HTMLDivElement | null>(null);

  // Filtres
  const [minPrice, setMinPrice] = useState("");
  const [maxPrice, setMaxPrice] = useState("");
  const [minLogements, setMinLogements] = useState("");
  const [maxLogements, setMaxLogements] = useState("");
  const [minAnnee, setMinAnnee] = useState("");
  const [maxAnnee, setMaxAnnee] = useState("");
  const [soldSince, setSoldSince] = useState("");

  // Modal ajout manuel
  const [showAddModal, setShowAddModal] = useState(false);

  // Santé : la source automatique (Journal) est-elle branchée ?
  const [journalConfigured, setJournalConfigured] = useState<boolean | null>(
    null
  );

  // ── Santé : un seul appel au montage. Si l'endpoint n'existe pas
  //    encore (404 / réseau), on reste en `null` → on n'affiche aucun
  //    bandeau trompeur.
  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const r = await authedFetch(
          "/api/v1/prospection/comparables/health"
        );
        if (!r.ok) return;
        const data = (await r.json()) as HealthResponse;
        if (!cancelled && typeof data.journal_source_configured === "boolean") {
          setJournalConfigured(data.journal_source_configured);
        }
      } catch {
        /* endpoint pas encore déployé : on ignore */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  // ── Autocomplete adresse : debounce 350 ms, réutilise l'endpoint
  //    existant address-search (rôle d'évaluation MTL).
  useEffect(() => {
    const q = address.trim();
    if (q.length < 2) {
      setSuggestions([]);
      setSuggestLoading(false);
      return;
    }
    setSuggestLoading(true);
    const handle = setTimeout(async () => {
      try {
        const res = await authedFetch(
          `/api/v1/prospection/mtl-properties/address-search?q=${encodeURIComponent(
            q
          )}&limit=12`
        );
        if (!res.ok) throw new Error();
        const data = (await res.json()) as AddressSuggestion[];
        setSuggestions(data);
        setSuggestOpen(true);
      } catch {
        setSuggestions([]);
      } finally {
        setSuggestLoading(false);
      }
    }, 350);
    return () => clearTimeout(handle);
  }, [address]);

  // Click hors du champ adresse → ferme le dropdown.
  useEffect(() => {
    function onDoc(e: MouseEvent) {
      if (!addrWrapRef.current) return;
      if (!addrWrapRef.current.contains(e.target as Node))
        setSuggestOpen(false);
    }
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, []);

  function pickSuggestion(s: AddressSuggestion) {
    setAddress(s.label);
    setMatricule(s.matricule);
    setSuggestOpen(false);
  }

  const search = useCallback(async () => {
    setLoading(true);
    setError(null);
    setSearched(true);
    try {
      const params = new URLSearchParams();
      // Privilégie le matricule choisi dans l'autocomplete ; sinon le
      // texte d'adresse libre.
      if (matricule) params.set("matricule", matricule);
      else if (address.trim()) params.set("address", address.trim());
      if (minPrice) params.set("min_price", minPrice);
      if (maxPrice) params.set("max_price", maxPrice);
      if (minLogements) params.set("min_logements", minLogements);
      if (maxLogements) params.set("max_logements", maxLogements);
      if (minAnnee) params.set("min_annee", minAnnee);
      if (maxAnnee) params.set("max_annee", maxAnnee);
      if (soldSince) params.set("sold_since", soldSince);
      params.set("refresh", "true");

      const res = await authedFetch(
        `/api/v1/prospection/comparables?${params}`
      );
      if (!res.ok) {
        const t = await res.text();
        throw new Error(t.slice(0, 200) || `HTTP ${res.status}`);
      }
      const data = (await res.json()) as ComparablesResponse;
      setComparables(data.comparables || []);
      setTotal(data.total || 0);
    } catch (e) {
      setError((e as Error).message);
      setComparables([]);
      setTotal(0);
    } finally {
      setLoading(false);
    }
  }, [
    matricule,
    address,
    minPrice,
    maxPrice,
    minLogements,
    maxLogements,
    minAnnee,
    maxAnnee,
    soldSince
  ]);

  // Recharge sans refaire les filtres (après ajout/suppression).
  const reload = useCallback(async () => {
    if (!searched) return;
    await search();
  }, [searched, search]);

  async function deleteComparable(c: Comparable) {
    if (
      !window.confirm(
        `Supprimer ce comparable ?\n${comparableAddress(c)} — ${fmtPrice(
          c.price
        )}`
      )
    )
      return;
    try {
      const res = await authedFetch(
        `/api/v1/prospection/comparables/${c.id}`,
        { method: "DELETE" }
      );
      if (!res.ok) {
        const t = await res.text();
        alert(t.slice(0, 200) || `HTTP ${res.status}`);
        return;
      }
      await reload();
    } catch (e) {
      alert((e as Error).message);
    }
  }

  return (
    <>
      <AppTopbar
        breadcrumbs={[
          { label: "Prospection", href: "/prospection" },
          { label: "Comparables" }
        ]}
        onOpenSidebar={onOpenSidebar}
      />

      <div className="p-4 lg:p-6">
        <header className="flex flex-wrap items-center gap-3">
          <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-emerald-500/15 text-emerald-400">
            <TrendingUp className="h-5 w-5" />
          </span>
          <div className="min-w-0 flex-1">
            <h1 className="text-2xl font-bold text-white">
              Comparables vendus
            </h1>
            <p className="text-sm text-white/60">
              Recherche les immeubles multilogements vendus récemment pour
              appuyer tes évaluations. Croise une adresse avec les rôles
              fonciers et conserve tes comparables dans ta base.
            </p>
          </div>
          <button
            type="button"
            onClick={() => setShowAddModal(true)}
            className="inline-flex items-center gap-1.5 rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-sm font-medium text-emerald-300 hover:bg-emerald-500/20"
          >
            <Plus className="h-4 w-4" />
            Ajouter un comparable manuel
          </button>
        </header>

        {/* Encart pédagogique : source automatique non branchée. */}
        {journalConfigured === false ? (
          <div className="mt-4 flex items-start gap-3 rounded-xl border border-amber-500/30 bg-amber-500/5 px-4 py-3">
            <Info className="mt-0.5 h-4 w-4 flex-shrink-0 text-amber-300" />
            <p className="text-[13px] text-amber-200">
              La source automatique (Journal) n&apos;est pas encore activée.
              En attendant, ajoute tes comparables connus manuellement — ils
              sont croisés automatiquement avec les rôles fonciers et
              conservés dans ta base.
            </p>
          </div>
        ) : null}

        {/* Recherche + filtres */}
        <section className="mt-6 rounded-2xl border border-brand-800 bg-brand-900 p-4">
          <div ref={addrWrapRef} className="relative">
            <label className="label">Adresse</label>
            <div className="relative">
              <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-white/40" />
              <input
                type="text"
                value={address}
                onChange={(e) => {
                  setAddress(e.target.value);
                  // L'utilisateur retape : on oublie le matricule choisi.
                  setMatricule(null);
                  setSuggestOpen(true);
                }}
                onFocus={() => {
                  if (suggestions.length > 0) setSuggestOpen(true);
                }}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    setSuggestOpen(false);
                    void search();
                  }
                }}
                autoComplete="off"
                placeholder="Tape un numéro civique + rue (ex. 261 Mont-Royal)"
                className="input pl-8 text-sm"
              />
              {suggestLoading ? (
                <Loader2 className="absolute right-2.5 top-1/2 h-4 w-4 -translate-y-1/2 animate-spin text-white/40" />
              ) : null}
            </div>

            {suggestOpen && suggestions.length > 0 ? (
              <ul className="absolute left-0 right-0 top-full z-30 mt-1 max-h-72 overflow-auto rounded-lg border border-brand-800 bg-brand-950 shadow-xl">
                {suggestions.map((s) => (
                  <li key={s.matricule}>
                    <button
                      type="button"
                      onClick={() => pickSuggestion(s)}
                      className="flex w-full items-start gap-2 px-3 py-2 text-left text-sm hover:bg-brand-900"
                    >
                      <MapPin className="mt-0.5 h-3.5 w-3.5 flex-shrink-0 text-emerald-400" />
                      <div className="min-w-0 flex-1">
                        <div className="truncate text-white/80">
                          {s.label}
                        </div>
                        <div className="text-[10px] text-white/40">
                          Matricule {s.matricule}
                        </div>
                      </div>
                    </button>
                  </li>
                ))}
              </ul>
            ) : null}
            {matricule ? (
              <p className="mt-1 text-[11px] text-emerald-300">
                Adresse rattachée au matricule {matricule}.
              </p>
            ) : null}
          </div>

          <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <div>
              <label className="label">Prix min</label>
              <input
                type="number"
                min="0"
                value={minPrice}
                onChange={(e) => setMinPrice(e.target.value)}
                placeholder="$"
                className="input text-sm"
              />
            </div>
            <div>
              <label className="label">Prix max</label>
              <input
                type="number"
                min="0"
                value={maxPrice}
                onChange={(e) => setMaxPrice(e.target.value)}
                placeholder="$"
                className="input text-sm"
              />
            </div>
            <div>
              <label className="label">Min logements</label>
              <input
                type="number"
                min="0"
                value={minLogements}
                onChange={(e) => setMinLogements(e.target.value)}
                className="input text-sm"
              />
            </div>
            <div>
              <label className="label">Max logements</label>
              <input
                type="number"
                min="0"
                value={maxLogements}
                onChange={(e) => setMaxLogements(e.target.value)}
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
                onChange={(e) => setMinAnnee(e.target.value)}
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
                onChange={(e) => setMaxAnnee(e.target.value)}
                className="input text-sm"
              />
            </div>
            <div>
              <label className="label">Vendu depuis</label>
              <input
                type="date"
                value={soldSince}
                onChange={(e) => setSoldSince(e.target.value)}
                className="input text-sm"
              />
            </div>
            <div className="flex items-end">
              <button
                type="button"
                onClick={() => {
                  setSuggestOpen(false);
                  void search();
                }}
                disabled={loading}
                className="inline-flex w-full items-center justify-center gap-1.5 rounded-lg bg-emerald-500 px-4 py-2 text-sm font-semibold text-brand-950 hover:bg-emerald-400 disabled:opacity-50"
              >
                {loading ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Search className="h-4 w-4" />
                )}
                Rechercher
              </button>
            </div>
          </div>
        </section>

        {/* Compteur de résultats */}
        {searched ? (
          <div className="mt-3">
            <p className="text-xs text-white/60">
              {loading ? (
                <Loader2 className="inline h-3 w-3 animate-spin" />
              ) : (
                <>
                  <span className="font-bold text-emerald-300">
                    {total.toLocaleString("fr-CA")}
                  </span>{" "}
                  comparable{total > 1 ? "s" : ""} trouvé
                  {total > 1 ? "s" : ""}
                </>
              )}
            </p>
          </div>
        ) : null}

        {error ? (
          <p className="mt-3 flex items-start gap-2 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-300">
            <AlertTriangle className="mt-0.5 h-4 w-4 flex-shrink-0" />
            <span>{error}</span>
          </p>
        ) : null}

        {/* Tableau de résultats */}
        <div className="mt-4 overflow-hidden rounded-xl border border-brand-800 bg-brand-900">
          {loading && comparables.length === 0 ? (
            <div className="flex items-center justify-center py-12">
              <Loader2 className="h-6 w-6 animate-spin text-emerald-500" />
            </div>
          ) : !searched ? (
            <div className="p-12 text-center">
              <TrendingUp className="mx-auto h-8 w-8 text-white/20" />
              <p className="mt-3 text-sm text-white/60">
                Cherche une adresse ou applique des filtres, puis clique
                « Rechercher » pour afficher les comparables vendus.
              </p>
            </div>
          ) : comparables.length === 0 ? (
            <div className="p-12 text-center">
              <TrendingUp className="mx-auto h-8 w-8 text-white/20" />
              <p className="mt-3 text-sm text-white/60">
                Aucun comparable ne correspond à ta recherche.
              </p>
              <p className="mt-1 text-[11px] text-white/40">
                Ajoute un comparable connu manuellement pour enrichir ta
                base.
              </p>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="bg-brand-950/60 text-left text-[11px] uppercase tracking-wider text-white/50">
                  <tr>
                    <th className="px-3 py-2.5">Adresse</th>
                    <th className="px-3 py-2.5 text-right">Prix</th>
                    <th className="px-3 py-2.5 text-right">Date vente</th>
                    <th className="px-3 py-2.5 text-right">Nb log</th>
                    <th className="px-3 py-2.5 text-right">Année</th>
                    <th className="px-3 py-2.5 text-right">Superficie</th>
                    <th className="px-3 py-2.5">Source</th>
                    <th className="px-3 py-2.5"></th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-brand-800">
                  {comparables.map((c) => {
                    const isManual = c.source === "manual";
                    return (
                      <tr
                        key={c.id}
                        className="transition hover:bg-brand-800/40"
                      >
                        <td className="px-3 py-2.5 text-white/80">
                          {c.source_url ? (
                            <a
                              href={c.source_url}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="hover:text-emerald-300 hover:underline"
                            >
                              {comparableAddress(c)}
                            </a>
                          ) : (
                            comparableAddress(c)
                          )}
                          {c.municipalite ? (
                            <div className="text-[10px] text-white/40">
                              {c.municipalite}
                            </div>
                          ) : null}
                          {c.libelle_utilisation ? (
                            <div className="text-[10px] text-white/40">
                              {c.libelle_utilisation}
                            </div>
                          ) : null}
                        </td>
                        <td className="px-3 py-2.5 text-right font-bold tabular-nums text-emerald-300">
                          {fmtPrice(c.price)}
                        </td>
                        <td className="px-3 py-2.5 text-right tabular-nums text-white/70">
                          {fmtDate(c.date_sold)}
                        </td>
                        <td className="px-3 py-2.5 text-right tabular-nums text-white/70">
                          {c.nb_logement ?? "—"}
                        </td>
                        <td className="px-3 py-2.5 text-right tabular-nums text-white/70">
                          {c.annee_construction ?? "—"}
                        </td>
                        <td className="px-3 py-2.5 text-right tabular-nums text-white/70">
                          {fmtArea(c.superficie_terrain)}
                        </td>
                        <td className="px-3 py-2.5">
                          {isManual ? (
                            <span className="inline-flex items-center gap-1 rounded-full bg-amber-500/15 px-2 py-0.5 text-[10px] text-amber-200">
                              <Plus className="h-2.5 w-2.5" />
                              Manuel
                            </span>
                          ) : (
                            <span className="inline-flex items-center gap-1 rounded-full bg-emerald-500/15 px-2 py-0.5 text-[10px] text-emerald-300">
                              <Newspaper className="h-2.5 w-2.5" />
                              Journal
                            </span>
                          )}
                        </td>
                        <td className="px-3 py-2.5 text-right">
                          {isManual ? (
                            <button
                              type="button"
                              onClick={() => deleteComparable(c)}
                              className="inline-flex items-center justify-center rounded-md border border-rose-500/40 bg-rose-500/10 p-1.5 text-rose-300 hover:bg-rose-500/20"
                              title="Supprimer ce comparable manuel"
                              aria-label="Supprimer"
                            >
                              <Trash2 className="h-3.5 w-3.5" />
                            </button>
                          ) : null}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>

      {showAddModal ? (
        <AddComparableModal
          onClose={() => setShowAddModal(false)}
          onAdded={() => {
            setShowAddModal(false);
            void reload();
          }}
        />
      ) : null}
    </>
  );
}

// ─────────────────────────────────────────────────────────────────────────
// Modal : ajout d'un comparable manuel
// ─────────────────────────────────────────────────────────────────────────

function AddComparableModal({
  onClose,
  onAdded
}: {
  onClose: () => void;
  onAdded: () => void;
}) {
  const [addressFull, setAddressFull] = useState("");
  const [civique, setCivique] = useState("");
  const [nomRue, setNomRue] = useState("");
  const [municipalite, setMunicipalite] = useState("");
  const [region, setRegion] = useState("");
  const [price, setPrice] = useState("");
  const [dateSold, setDateSold] = useState("");
  const [nbLogement, setNbLogement] = useState("");
  const [annee, setAnnee] = useState("");
  const [superficie, setSuperficie] = useState("");

  // Autocomplete adresse (aide facultative). Quand une suggestion est
  // choisie, on pré-remplit civique/rue/municipalité et on mémorise le
  // matricule pour croiser exactement avec le rôle d'évaluation côté API.
  const [addrQuery, setAddrQuery] = useState("");
  const [matricule, setMatricule] = useState<string | null>(null);
  const [suggestions, setSuggestions] = useState<AddressSuggestion[]>([]);
  const [suggestOpen, setSuggestOpen] = useState(false);
  const [suggestLoading, setSuggestLoading] = useState(false);
  const addrWrapRef = useRef<HTMLDivElement | null>(null);

  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Debounce 350 ms → réutilise le même endpoint address-search que la
  // recherche principale (rôle d'évaluation MTL).
  useEffect(() => {
    const q = addrQuery.trim();
    if (q.length < 2) {
      setSuggestions([]);
      setSuggestLoading(false);
      return;
    }
    setSuggestLoading(true);
    const handle = setTimeout(async () => {
      try {
        const res = await authedFetch(
          `/api/v1/prospection/mtl-properties/address-search?q=${encodeURIComponent(
            q
          )}&limit=12`
        );
        if (!res.ok) throw new Error();
        const data = (await res.json()) as AddressSuggestion[];
        setSuggestions(data);
        setSuggestOpen(true);
      } catch {
        setSuggestions([]);
      } finally {
        setSuggestLoading(false);
      }
    }, 350);
    return () => clearTimeout(handle);
  }, [addrQuery]);

  // Click hors du champ adresse → ferme le dropdown.
  useEffect(() => {
    function onDoc(e: MouseEvent) {
      if (!addrWrapRef.current) return;
      if (!addrWrapRef.current.contains(e.target as Node))
        setSuggestOpen(false);
    }
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, []);

  // Sélection d'une suggestion : pré-remplit les champs et garde le
  // matricule. L'utilisateur peut toujours ajuster les champs ensuite.
  function pickSuggestion(s: AddressSuggestion) {
    setAddrQuery(s.label);
    setMatricule(s.matricule);
    if (s.civique) setCivique(s.civique);
    if (s.nom_rue) setNomRue(s.nom_rue);
    if (s.municipalite) setMunicipalite(s.municipalite);
    setSuggestOpen(false);
  }

  async function submit() {
    setError(null);
    // Validation simple : prix + date requis, et au moins une forme
    // d'adresse (texte libre OU civique+rue).
    if (!price.trim()) {
      setError("Le prix est requis.");
      return;
    }
    if (!dateSold.trim()) {
      setError("La date de vente est requise.");
      return;
    }
    if (!addressFull.trim() && !(civique.trim() && nomRue.trim())) {
      setError(
        "Indique une adresse complète, ou un numéro civique + une rue."
      );
      return;
    }

    setSubmitting(true);
    try {
      const payload: Record<string, unknown> = {
        price: Number(price),
        date_sold: dateSold
      };
      if (addressFull.trim()) payload.address_full = addressFull.trim();
      if (civique.trim()) payload.civique = civique.trim();
      if (nomRue.trim()) payload.nom_rue = nomRue.trim();
      if (municipalite.trim()) payload.municipalite = municipalite.trim();
      if (region.trim()) payload.region = region.trim();
      if (nbLogement.trim()) payload.nb_logement = Number(nbLogement);
      if (annee.trim()) payload.annee_construction = Number(annee);
      if (superficie.trim()) payload.superficie_terrain = Number(superficie);
      // Matricule du rôle d'évaluation (si l'adresse vient de
      // l'autocomplete) : le backend croise exactement et enrichit les
      // données. Optionnel — fallback texte si absent.
      if (matricule) payload.matricule = matricule;

      const res = await authedFetch(
        "/api/v1/prospection/comparables/manual",
        {
          method: "POST",
          body: JSON.stringify(payload)
        }
      );
      if (!res.ok) {
        const t = await res.text();
        throw new Error(t.slice(0, 200) || `HTTP ${res.status}`);
      }
      onAdded();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-[1000] flex items-center justify-center bg-black/70 p-4"
      role="dialog"
      aria-modal="true"
    >
      <div className="flex max-h-[90vh] w-full max-w-xl flex-col overflow-hidden rounded-2xl border border-brand-800 bg-brand-950">
        <header className="flex items-start justify-between gap-3 border-b border-brand-800 p-4">
          <div className="min-w-0">
            <h2 className="flex items-center gap-2 text-sm font-semibold text-white">
              <Plus className="h-4 w-4 text-emerald-400" />
              Ajouter un comparable manuel
            </h2>
            <p className="mt-1 text-xs text-white/60">
              Saisis une vente connue. Elle est croisée automatiquement
              avec les rôles fonciers et conservée dans ta base.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md p-1 text-white/40 hover:bg-brand-900 hover:text-white"
            aria-label="Fermer"
          >
            <X className="h-4 w-4" />
          </button>
        </header>

        <div className="flex-1 space-y-3 overflow-y-auto p-4">
          {/* Autocomplete : aide facultative. Pré-remplit civique/rue/
              municipalité et rattache le matricule du rôle d'évaluation. */}
          <div ref={addrWrapRef} className="relative">
            <label className="label">Rechercher une adresse (rôle MTL)</label>
            <div className="relative">
              <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-white/40" />
              <input
                type="text"
                value={addrQuery}
                onChange={(e) => {
                  setAddrQuery(e.target.value);
                  // L'utilisateur retape : on oublie le matricule choisi.
                  setMatricule(null);
                  setSuggestOpen(true);
                }}
                onFocus={() => {
                  if (suggestions.length > 0) setSuggestOpen(true);
                }}
                autoComplete="off"
                placeholder="Tape un numéro civique + rue (ex. 261 Mont-Royal)"
                className="input pl-8 text-sm"
              />
              {suggestLoading ? (
                <Loader2 className="absolute right-2.5 top-1/2 h-4 w-4 -translate-y-1/2 animate-spin text-white/40" />
              ) : null}
            </div>

            {suggestOpen && suggestions.length > 0 ? (
              <ul className="absolute left-0 right-0 top-full z-30 mt-1 max-h-72 overflow-auto rounded-lg border border-brand-800 bg-brand-950 shadow-xl">
                {suggestions.map((s) => (
                  <li key={s.matricule}>
                    <button
                      type="button"
                      onClick={() => pickSuggestion(s)}
                      className="flex w-full items-start gap-2 px-3 py-2 text-left text-sm hover:bg-brand-900"
                    >
                      <MapPin className="mt-0.5 h-3.5 w-3.5 flex-shrink-0 text-emerald-400" />
                      <div className="min-w-0 flex-1">
                        <div className="truncate text-white/80">
                          {s.label}
                        </div>
                        <div className="text-[10px] text-white/40">
                          Matricule {s.matricule}
                        </div>
                      </div>
                    </button>
                  </li>
                ))}
              </ul>
            ) : null}
            {matricule ? (
              <p className="mt-1 text-[11px] text-emerald-300">
                Adresse rattachée au matricule {matricule} — nb logements,
                année et superficie seront enrichis automatiquement.
              </p>
            ) : (
              <p className="mt-1 text-[10px] text-white/40">
                Facultatif : choisis une suggestion pour pré-remplir les
                champs, ou saisis l&apos;adresse à la main ci-dessous.
              </p>
            )}
          </div>

          <div>
            <label className="label">Adresse complète</label>
            <input
              type="text"
              value={addressFull}
              onChange={(e) => setAddressFull(e.target.value)}
              placeholder="Ex. 261 av. du Mont-Royal Est"
              className="input text-sm"
            />
            <p className="mt-1 text-[10px] text-white/40">
              Ou renseigne le numéro civique et la rue séparément
              ci-dessous.
            </p>
          </div>

          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <label className="label">Numéro civique</label>
              <input
                type="text"
                value={civique}
                onChange={(e) => {
                  setCivique(e.target.value);
                  // Édition manuelle : le matricule choisi ne correspond
                  // plus forcément à l'adresse saisie, on l'oublie.
                  setMatricule(null);
                }}
                className="input text-sm"
              />
            </div>
            <div>
              <label className="label">Rue</label>
              <input
                type="text"
                value={nomRue}
                onChange={(e) => {
                  setNomRue(e.target.value);
                  setMatricule(null);
                }}
                className="input text-sm"
              />
            </div>
            <div>
              <label className="label">Municipalité</label>
              <input
                type="text"
                value={municipalite}
                onChange={(e) => setMunicipalite(e.target.value)}
                placeholder="Ex. Montréal"
                className="input text-sm"
              />
            </div>
            <div>
              <label className="label">Région</label>
              <input
                type="text"
                value={region}
                onChange={(e) => setRegion(e.target.value)}
                placeholder="Ex. Montréal (06)"
                className="input text-sm"
              />
            </div>
          </div>

          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <label className="label">
                Prix de vente <span className="text-rose-300">*</span>
              </label>
              <input
                type="number"
                min="0"
                value={price}
                onChange={(e) => setPrice(e.target.value)}
                placeholder="$"
                className="input text-sm"
              />
            </div>
            <div>
              <label className="label">
                Date de vente <span className="text-rose-300">*</span>
              </label>
              <input
                type="date"
                value={dateSold}
                onChange={(e) => setDateSold(e.target.value)}
                className="input text-sm"
              />
            </div>
          </div>

          <div className="grid gap-3 sm:grid-cols-3">
            <div>
              <label className="label">Nb logements</label>
              <input
                type="number"
                min="0"
                value={nbLogement}
                onChange={(e) => setNbLogement(e.target.value)}
                className="input text-sm"
              />
            </div>
            <div>
              <label className="label">Année</label>
              <input
                type="number"
                min="1700"
                max="2100"
                value={annee}
                onChange={(e) => setAnnee(e.target.value)}
                className="input text-sm"
              />
            </div>
            <div>
              <label className="label">Superficie (m²)</label>
              <input
                type="number"
                min="0"
                value={superficie}
                onChange={(e) => setSuperficie(e.target.value)}
                className="input text-sm"
              />
            </div>
          </div>

          {error ? (
            <p className="flex items-start gap-2 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
              <AlertTriangle className="mt-0.5 h-3.5 w-3.5 flex-shrink-0" />
              <span>{error}</span>
            </p>
          ) : null}
        </div>

        <footer className="flex items-center justify-end gap-2 border-t border-brand-800 p-3">
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-brand-700 bg-brand-900 px-3 py-1.5 text-sm text-white/70 hover:text-white"
          >
            Annuler
          </button>
          <button
            type="button"
            onClick={submit}
            disabled={submitting}
            className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-500 px-4 py-1.5 text-sm font-semibold text-brand-950 hover:bg-emerald-400 disabled:opacity-50"
          >
            {submitting ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Plus className="h-4 w-4" />
            )}
            Ajouter
          </button>
        </footer>
      </div>
    </div>
  );
}
