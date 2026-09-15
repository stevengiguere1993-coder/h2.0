"use client";

import { useEffect, useState } from "react";
import {
  AlertTriangle,
  Loader2,
  Plus,
  Search,
  User
} from "lucide-react";

import { Link, useRouter } from "@/i18n/navigation";
import { authedFetch } from "@/lib/auth";
import { BoutonExport } from "@/components/immobilier/bouton-export";
import { CreateLocataireModal } from "@/components/immobilier/create-locataire-modal";
import { ImmobilierTopbar, useImmobilierLayout } from "../layout";

type Locataire = {
  id: number;
  full_name: string;
  email?: string | null;
  phone?: string | null;
  paiement_score?: number | null;
  employeur?: string | null;
  revenu_annuel?: number | null;
  // Bail actif → colonnes Immeuble / Appart cliquables (retour Phil).
  immeuble_id?: number | null;
  immeuble_name?: string | null;
  logement_id?: number | null;
  logement_numero?: string | null;
  /** Pourquoi la fiche remonte quand ce n'est PAS son nom qui matche
   *  (« garant : Jacques Roy », « courriel : … ») — retour Phil
   *  2026-09-09, point 8 : chercher Jacques doit montrer Sébastien. */
  match_via?: string | null;
};

type ImmeubleLite = {
  id: number;
  name: string;
};

/** Fiche existante qui porte le même courriel ou le même téléphone —
 *  matière de l'alerte anti-doublon (retour Phil 2026-08-13 : 6 paires
 *  de fiches avaient dû être fusionnées à la main). */

type BailLite = {
  id: number;
  locataire_id: number;
  status: string;
};

type ScoreFilter = "all" | "lt70" | "70_89" | "gte90";

const SCORE_FILTERS: { value: ScoreFilter; label: string }[] = [
  { value: "all", label: "Tous" },
  { value: "lt70", label: "Score < 70" },
  { value: "70_89", label: "70–89" },
  { value: "gte90", label: "≥ 90" }
];

export default function LocatairesPage() {
  const router = useRouter();
  const { currentEntrepriseId } = useImmobilierLayout();
  const [list, setList] = useState<Locataire[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [scoreFilter, setScoreFilter] = useState<ScoreFilter>("all");
  const [showCreate, setShowCreate] = useState(false);
  const [immeubles, setImmeubles] = useState<ImmeubleLite[]>([]);
  const [immeubleFilter, setImmeubleFilter] = useState<number | "all">("all");
  // Locataires ayant un bail ACTIF dans l'immeuble choisi (null = pas chargé).
  const [immeubleLocataireIds, setImmeubleLocataireIds] =
    useState<Set<number> | null>(null);
  const [loadingImmeuble, setLoadingImmeuble] = useState(false);

  async function reload() {
    setError(null);
    try {
      const url = search.trim()
        ? `/api/v1/immobilier/locataires?search=${encodeURIComponent(search.trim())}`
        : "/api/v1/immobilier/locataires";
      const res = await authedFetch(url);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setList((await res.json()) as Locataire[]);
    } catch (err) {
      setError((err as Error).message);
    }
  }

  useEffect(() => {
    const t = setTimeout(reload, 250);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search]);

  // Liste des immeubles pour le filtre (entreprise active du layout).
  useEffect(() => {
    let cancelled = false;
    setImmeubleFilter("all");
    void (async () => {
      try {
        const url =
          currentEntrepriseId != null
            ? `/api/v1/immobilier/immeubles?entreprise_id=${currentEntrepriseId}`
            : "/api/v1/immobilier/immeubles";
        const res = await authedFetch(url);
        if (res.ok && !cancelled)
          setImmeubles((await res.json()) as ImmeubleLite[]);
      } catch {
        // Filtre non bloquant — le select reste vide.
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [currentEntrepriseId]);

  // Immeuble choisi → baux de l'immeuble → Set des locataire_id (baux actifs).
  useEffect(() => {
    if (immeubleFilter === "all") {
      setImmeubleLocataireIds(null);
      setLoadingImmeuble(false);
      return;
    }
    let cancelled = false;
    setLoadingImmeuble(true);
    setImmeubleLocataireIds(null);
    void (async () => {
      try {
        const res = await authedFetch(
          `/api/v1/immobilier/immeubles/${immeubleFilter}/baux`
        );
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const baux = (await res.json()) as BailLite[];
        if (cancelled) return;
        setImmeubleLocataireIds(
          new Set(
            baux
              .filter((b) => b.status === "actif")
              .map((b) => b.locataire_id)
          )
        );
      } catch (err) {
        if (!cancelled) setError((err as Error).message);
      } finally {
        if (!cancelled) setLoadingImmeuble(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [immeubleFilter]);

  // Filtres client-side sur les rows chargées : immeuble (via baux actifs)
  // puis score de paiement. Pendant le fetch des baux (ids null), on ne
  // filtre pas encore — le loader discret indique le chargement.
  const filtered =
    list === null
      ? null
      : list.filter((l) => {
          if (
            immeubleFilter !== "all" &&
            immeubleLocataireIds !== null &&
            !immeubleLocataireIds.has(l.id)
          )
            return false;
          if (scoreFilter === "all") return true;
          if (l.paiement_score == null) return false;
          if (scoreFilter === "lt70") return l.paiement_score < 70;
          if (scoreFilter === "70_89")
            return l.paiement_score >= 70 && l.paiement_score < 90;
          return l.paiement_score >= 90;
        });

  return (
    <>
      <ImmobilierTopbar
        breadcrumbs={[
          { label: "Gestion immobilière", href: "/immobilier" },
          { label: "Locataires" }
        ]}
        rightSlot={
          <>
            <BoutonExport
              cibles={[
                {
                  base: "/api/v1/immobilier/exports/locataires",
                  sujet: "locataires",
                  params: {
                    immeuble_id:
                      immeubleFilter !== "all" ? immeubleFilter : undefined
                  }
                }
              ]}
            />
            <button
              type="button"
              onClick={() => setShowCreate(true)}
              className="btn-outline-accent btn-sm"
            >
              <Plus className="h-3.5 w-3.5" />
              Nouveau locataire
            </button>
          </>
        }
      />

      <div className="p-4 pb-28 lg:p-6 lg:pb-28">
        <div className="mb-4 flex flex-wrap items-center gap-2">
          <div className="relative max-w-md flex-1">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-white/40" />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Recherche nom / garant / courriel / téléphone…"
              className="input w-full pl-9"
            />
          </div>
          <select
            value={immeubleFilter === "all" ? "all" : String(immeubleFilter)}
            onChange={(e) =>
              setImmeubleFilter(
                e.target.value === "all" ? "all" : Number(e.target.value)
              )
            }
            className="input w-auto max-w-[220px] text-sm"
            aria-label="Filtrer par immeuble"
          >
            <option value="all">Tous les immeubles</option>
            {immeubles.map((imm) => (
              <option key={imm.id} value={imm.id}>
                {imm.name}
              </option>
            ))}
          </select>
          {loadingImmeuble ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin text-white/40" />
          ) : null}
          {SCORE_FILTERS.map((f) => (
            <FilterPill
              key={f.value}
              label={f.label}
              active={scoreFilter === f.value}
              onClick={() => setScoreFilter(f.value)}
            />
          ))}
          {filtered && list ? (
            <span className="text-xs text-white/50">
              {filtered.length} / {list.length}
            </span>
          ) : null}
        </div>

        {error ? (
          <p className="mb-4 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
            <AlertTriangle className="mr-1.5 inline h-3.5 w-3.5" />
            {error}
          </p>
        ) : null}

        {filtered === null ? (
          <Loading />
        ) : filtered.length === 0 ? (
          <p className="rounded-lg border border-brand-800 bg-brand-900 px-4 py-3 text-sm text-white/60">
            Aucun locataire{" "}
            {search || scoreFilter !== "all" || immeubleFilter !== "all"
              ? "correspondant"
              : "enregistré"}.
          </p>
        ) : (
          <div className="overflow-x-auto rounded-2xl border border-brand-800 bg-brand-900">
            <table className="w-full min-w-[820px] text-left text-sm">
              <thead className="border-b border-brand-800 bg-brand-950 text-[10px] uppercase tracking-wider text-white/50">
                <tr>
                  <th className="px-4 py-2.5">Nom</th>
                  <th className="px-4 py-2.5">Immeuble</th>
                  <th className="px-4 py-2.5">Appart</th>
                  <th className="px-4 py-2.5">Contact</th>
                  <th className="px-4 py-2.5">Employeur</th>
                  <th className="px-4 py-2.5 text-right">Revenu/an</th>
                  <th className="px-4 py-2.5 text-right">Score paiement</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-brand-800">
                {filtered.map((l) => (
                  <tr key={l.id} className="group hover:bg-brand-950/50">
                    <td className="px-4 py-3">
                      <Link
                        // eslint-disable-next-line @typescript-eslint/no-explicit-any
                        href={`/immobilier/locataires/${l.id}` as any}
                        className="flex items-center gap-3"
                      >
                        <div className="flex h-8 w-8 items-center justify-center rounded-full bg-accent-500/15 text-accent-500">
                          <User className="h-4 w-4" />
                        </div>
                        <span className="min-w-0">
                          <span className="block font-bold text-white group-hover:text-accent-500">
                            {l.full_name}
                          </span>
                          {l.match_via ? (
                            <span
                              className="block text-[11px] text-amber-200"
                              title="Cette fiche remonte parce qu'un de ses contacts (ou son courriel / téléphone) correspond à la recherche"
                            >
                              trouvé via {l.match_via}
                            </span>
                          ) : null}
                        </span>
                      </Link>
                    </td>
                    <td className="px-4 py-3 text-xs">
                      {l.immeuble_id ? (
                        <Link
                          // eslint-disable-next-line @typescript-eslint/no-explicit-any
                          href={`/immobilier/immeubles/${l.immeuble_id}` as any}
                          className="font-medium text-accent-500 hover:underline"
                        >
                          {l.immeuble_name || `Immeuble #${l.immeuble_id}`}
                        </Link>
                      ) : (
                        <span className="text-white/40">—</span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-xs">
                      {l.logement_id ? (
                        <Link
                          // eslint-disable-next-line @typescript-eslint/no-explicit-any
                          href={`/immobilier/logements/${l.logement_id}` as any}
                          className="font-mono font-medium text-accent-500 hover:underline"
                        >
                          {l.logement_numero || `#${l.logement_id}`}
                        </Link>
                      ) : (
                        <span className="text-white/40">—</span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-xs text-white/60">
                      <div>{l.email || "—"}</div>
                      <div className="font-mono text-white/40">
                        {l.phone || "—"}
                      </div>
                    </td>
                    <td className="px-4 py-3 text-xs text-white/60">
                      {l.employeur || "—"}
                    </td>
                    <td className="px-4 py-3 text-right font-mono text-xs text-white/70">
                      {l.revenu_annuel
                        ? new Intl.NumberFormat("fr-CA", {
                            style: "currency",
                            currency: "CAD",
                            minimumFractionDigits: 2,
                            maximumFractionDigits: 2
                          }).format(l.revenu_annuel)
                        : "—"}
                    </td>
                    <td className="px-4 py-3 text-right font-mono text-xs">
                      {l.paiement_score != null ? (
                        <span
                          className={
                            l.paiement_score >= 90
                              ? "text-emerald-300"
                              : l.paiement_score >= 70
                              ? "text-amber-300"
                              : "text-rose-300"
                          }
                        >
                          {l.paiement_score}
                        </span>
                      ) : (
                        <span className="text-white/40">—</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {showCreate ? (
        <CreateLocataireModal
          onClose={() => setShowCreate(false)}
          onSaved={(locataireId) => {
            setShowCreate(false);
            // Ouvrir directement le hub du locataire créé (retour Phil)
            // — ou de la fiche existante retenue via l'alerte doublon.
            router.push(`/immobilier/locataires/${locataireId}` as any);
          }}
        />
      ) : null}
    </>
  );
}

function Loading() {
  return (
    <p className="text-xs text-white/50">
      <Loader2 className="mr-1 inline h-3 w-3 animate-spin" /> Chargement…
    </p>
  );
}

function FilterPill({
  label,
  active,
  onClick
}: {
  label: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`rounded-full px-3 py-1 text-xs font-semibold transition ${
        active
          ? "bg-brand-900 text-white"
          : "border border-white/10 bg-brand-950 text-white/60 hover:text-white"
      }`}
    >
      {label}
    </button>
  );
}
