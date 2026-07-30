"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Building2,
  Calendar,
  ChevronDown,
  ChevronRight,
  ExternalLink,
  LayoutGrid,
  List,
  Loader2,
  Plus,
  RefreshCw,
  Settings2,
  Target,
  Trash2,
  TrendingUp,
  Landmark,
  Search,
  UserPlus,
  Users,
  X
} from "lucide-react";

import { authedFetch } from "@/lib/auth";
import { useConfirm } from "@/components/confirm-dialog";
import { QGTopbar, useEntreprisesLayout } from "../layout";

/**
 * Projets - Optimisation : un projet = une INC + un immeuble.
 * 1) Budget : catégories du plan comptable QuickBooks cochées dans ⚙,
 *    budget manuel, dépensé lu de QBO, écart vert/rouge.
 * 2) Objectifs vs réel locatif (+ progression mensuelle des revenus).
 * 3) Négociations locataires (import sélectif, type d'entente, timeline).
 */

type BudgetLigne = {
  id: number;
  projet_id: number;
  nom: string;
  budget_montant: number;
  qbo_accounts_json: string | null;
  qbo_financement_accounts_json: string | null;
  comptant_disponible: number | null;
  position: number;
};

type Nego = {
  id: number;
  projet_id: number;
  locataire_id: number | null;
  nom_locataire: string;
  logement_label: string | null;
  loyer_actuel: number | null;
  statut: string;
  type_entente: string | null;
  entente: string | null;
  montant_entente: number | null;
  date_cible: string | null;
  events_json: string | null;
  recherche_json: string | null;
  position: number;
};

type ProjetLite = {
  id: number;
  name: string;
  entreprise_id: number;
  immeuble_id: number;
  status: string;
  date_debut: string | null;
  entreprise_nom: string;
  immeuble_nom: string;
  budget_total: number;
  nb_negos: number;
};

type Projet = {
  id: number;
  name: string;
  entreprise_id: number;
  immeuble_id: number;
  status: string;
  date_debut: string | null;
  qbo_scope: string | null;
  qbo_bank_account_id: string | null;
  qbo_bank_account_name: string | null;
  objectif_revenus_mensuels: number | null;
  objectif_depenses_mensuelles: number | null;
  objectif_revenus_annuels: number | null;
  objectif_depenses_annuelles: number | null;
  objectifs_json: string | null;
  notes: string | null;
  entreprise_nom: string;
  immeuble_nom: string;
  revenus_actuels_mensuels: number;
  depenses_actuelles_mensuelles: number;
  nb_logements: number;
  revenus_historique: { mois: string; montant: number }[];
  budget_lignes: BudgetLigne[];
  negos: Nego[];
};

type ImmeubleMini = { id: number; name: string | null; address: string | null };
type QboCompte = {
  id: string;
  name: string;
  fully_qualified_name: string;
  account_type: string;
};
type ObjectifLibre = {
  label: string;
  cible: number;
  actuel: number;
  unite?: string;
};
/** Préparation de la négociation (stockée en JSON sur la négo). */
type Recherche = {
  emploi?: string;
  employeur?: string;
  revenu_estime?: string;
  linkedin?: string;
  facebook?: string;
  instagram?: string;
  autres?: string;
  notes?: string;
};
type LocataireDispo = {
  locataire_id: number;
  nom: string;
  logement: string | null;
  loyer: number | null;
  deja_suivi: boolean;
};

const NEGO_STATUTS: Record<
  string,
  { label: string; court: string; cls: string; dot: string }
> = {
  en_place: {
    label: "En place",
    court: "En place",
    cls: "badge badge-neutral",
    dot: "bg-slate-400"
  },
  a_contacter: {
    label: "À contacter",
    court: "À contacter",
    cls: "badge badge-amber",
    dot: "bg-amber-400"
  },
  en_discussion: {
    label: "En discussion",
    court: "En discussion",
    cls: "badge badge-sky",
    dot: "bg-sky-400"
  },
  entente: {
    label: "Entente conclue",
    court: "Entente",
    cls: "badge badge-emerald",
    dot: "bg-emerald-400"
  },
  // Rouge : le locataire reste au même loyer — l'optimisation n'a pas
  // eu lieu sur ce logement (retour Phil).
  reste: {
    label: "Reste en place (statu quo)",
    court: "Statu quo",
    cls: "badge badge-rose",
    dot: "bg-rose-400"
  }
};

const TYPES_ENTENTE: Record<string, string> = {
  cash_for_raise: "Cash for raise",
  cash_for_keys: "Cash for keys",
  renovation: "Rénovation",
  autre: "Autre"
};

/** Fonds des deux familles de colonnes du tableau de budget. */
const GRP_BUDGET = "bg-sky-500/[0.07]";
const GRP_FIN = "bg-violet-500/[0.07]";

function fmtMoney(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return new Intl.NumberFormat("fr-CA", {
    style: "currency",
    currency: "CAD",
    maximumFractionDigits: 0
  }).format(v);
}

function fmtVal(v: number, unite?: string): string {
  if (!unite || unite === "$") return fmtMoney(v);
  return `${new Intl.NumberFormat("fr-CA").format(v)} ${unite}`;
}

function parseAccounts(json: string | null): { id: string; name: string }[] {
  if (!json) return [];
  try {
    const v = JSON.parse(json);
    return Array.isArray(v) ? v.filter((x) => x && x.id) : [];
  } catch {
    return [];
  }
}

function parseObjectifs(json: string | null): ObjectifLibre[] {
  if (!json) return [];
  try {
    const v = JSON.parse(json);
    return Array.isArray(v) ? v : [];
  } catch {
    return [];
  }
}

function parseRecherche(json: string | null): Recherche {
  if (!json) return {};
  try {
    const v = JSON.parse(json);
    return v && typeof v === "object" ? (v as Recherche) : {};
  } catch {
    return {};
  }
}

function parseEvents(json: string | null): { date: string; texte: string }[] {
  if (!json) return [];
  try {
    const v = JSON.parse(json);
    return Array.isArray(v) ? v : [];
  } catch {
    return [];
  }
}

export default function ProjetsOptimisationPage() {
  const { entreprises } = useEntreprisesLayout();
  const confirm = useConfirm();

  const [projets, setProjets] = useState<ProjetLite[]>([]);
  const [selId, setSelId] = useState<number | null>(null);
  const [detail, setDetail] = useState<Projet | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [immeubles, setImmeubles] = useState<ImmeubleMini[]>([]);

  const [qboDep, setQboDep] = useState<Record<number, number>>({});
  const [qboFin, setQboFin] = useState<Record<number, number>>({});
  const [qboSolde, setQboSolde] = useState<number | null>(null);
  const [qboErr, setQboErr] = useState<string | null>(null);
  const [qboLoading, setQboLoading] = useState(false);

  const loadList = useCallback(async () => {
    try {
      const r = await authedFetch("/api/v1/optimisation/projets");
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      setProjets((await r.json()) as ProjetLite[]);
    } catch (e) {
      setError(`Chargement échoué : ${(e as Error).message}`);
    } finally {
      setLoading(false);
    }
  }, []);

  const loadDetail = useCallback(async (id: number) => {
    setLoadingDetail(true);
    try {
      const r = await authedFetch(`/api/v1/optimisation/projets/${id}`);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      setDetail((await r.json()) as Projet);
    } catch (e) {
      setError(`Chargement du projet échoué : ${(e as Error).message}`);
    } finally {
      setLoadingDetail(false);
    }
  }, []);

  const loadQbo = useCallback(async (id: number) => {
    setQboLoading(true);
    setQboErr(null);
    try {
      const r = await authedFetch(
        `/api/v1/optimisation/projets/${id}/qbo-depenses`
      );
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const d = (await r.json()) as {
        par_ligne: Record<number, number>;
        financement_par_ligne: Record<number, number>;
        solde_bancaire: number | null;
        erreur: string | null;
      };
      setQboDep(d.par_ligne || {});
      setQboFin(d.financement_par_ligne || {});
      setQboSolde(d.solde_bancaire ?? null);
      setQboErr(d.erreur || null);
    } catch (e) {
      setQboErr(`Lecture QuickBooks échouée : ${(e as Error).message}`);
    } finally {
      setQboLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadList();
    void (async () => {
      try {
        const r = await authedFetch("/api/v1/immobilier/immeubles");
        if (r.ok) setImmeubles((await r.json()) as ImmeubleMini[]);
      } catch {
        /* le sélecteur restera vide */
      }
    })();
  }, [loadList]);

  useEffect(() => {
    if (selId) {
      setQboDep({});
      setQboFin({});
      setQboSolde(null);
      setQboErr(null);
      void loadDetail(selId);
      void loadQbo(selId);
    } else {
      setDetail(null);
    }
  }, [selId, loadDetail, loadQbo]);

  // ── Création ───────────────────────────────────────────────────
  const [createOpen, setCreateOpen] = useState(false);
  const [cName, setCName] = useState("");
  const [cEnt, setCEnt] = useState<number | "">("");
  const [cImm, setCImm] = useState<number | "">("");
  const [cDate, setCDate] = useState("");
  const [creating, setCreating] = useState(false);

  async function submitCreate(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!cName.trim() || cEnt === "" || cImm === "") return;
    setCreating(true);
    try {
      const r = await authedFetch("/api/v1/optimisation/projets", {
        method: "POST",
        body: JSON.stringify({
          name: cName.trim(),
          entreprise_id: cEnt,
          immeuble_id: cImm,
          date_debut: cDate || null,
          // Les locataires s'ajoutent ensuite, à la pièce, depuis la
          // section Négociations (retour Phil).
          importer_locataires: false
        })
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const created = (await r.json()) as Projet;
      setCreateOpen(false);
      setCName("");
      setCEnt("");
      setCImm("");
      setCDate("");
      await loadList();
      setSelId(created.id);
    } catch (e) {
      setError(`Création échouée : ${(e as Error).message}`);
    } finally {
      setCreating(false);
    }
  }

  async function patchProjet(patch: Record<string, unknown>) {
    if (!detail) return;
    try {
      const r = await authedFetch(
        `/api/v1/optimisation/projets/${detail.id}`,
        { method: "PATCH", body: JSON.stringify(patch) }
      );
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      setDetail((await r.json()) as Projet);
      void loadList();
    } catch (e) {
      setError(`Sauvegarde échouée : ${(e as Error).message}`);
    }
  }

  async function deleteProjet() {
    if (!detail) return;
    const ok = await confirm({
      title: `Supprimer « ${detail.name} » ?`,
      description:
        "Budgets, objectifs et suivis de négociation de ce projet seront perdus. (Rien n'est touché dans QuickBooks ni dans la Gestion locative.)",
      confirmLabel: "Supprimer définitivement",
      destructive: true
    });
    if (!ok) return;
    const r = await authedFetch(
      `/api/v1/optimisation/projets/${detail.id}`,
      { method: "DELETE" }
    );
    if (r.ok || r.status === 204) {
      setDetail(null);
      setSelId(null);
      setProjets((xs) => xs.filter((x) => x.id !== detail.id));
      await loadList();
    }
  }

  return (
    <>
      <QGTopbar
        greeting={
          <span className="inline-flex items-center gap-2">
            <TrendingUp className="h-4 w-4 text-accent-500" />
            Projets · Optimisation
          </span>
        }
        subtitle="Budget vs QuickBooks · objectifs vs locatif · négociations locataires"
        rightSlot={
          <button
            type="button"
            onClick={() => setCreateOpen(true)}
            className="btn-accent inline-flex items-center gap-1.5 text-sm"
          >
            <Plus className="h-4 w-4" />
            Nouveau projet
          </button>
        }
      />

      <div className="p-4 pb-28 lg:p-6 lg:pb-28">
        {error ? (
          <p
            className="mb-3 cursor-pointer rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-300"
            onClick={() => setError(null)}
            title="Cliquer pour fermer"
          >
            {error}
          </p>
        ) : null}

        {loading ? (
          <div className="flex items-center justify-center py-12">
            <Loader2 className="h-6 w-6 animate-spin text-accent-500" />
          </div>
        ) : projets.length === 0 ? (
          <div
            className="rounded-xl border py-12 text-center"
            style={{
              borderColor: "var(--qg-border)",
              color: "var(--qg-text-muted)"
            }}
          >
            <TrendingUp className="mx-auto h-8 w-8 opacity-40" />
            <p className="mt-3 text-sm">
              Aucun projet d&apos;optimisation encore.
            </p>
            <p className="mx-auto mt-1 max-w-md text-xs">
              Un projet suit un immeuble fraîchement acquis par une INC :
              budget vs dépensé QuickBooks, objectifs de revenus, et
              négociations avec les locataires en place.
            </p>
            <button
              type="button"
              onClick={() => setCreateOpen(true)}
              className="btn-accent mt-3 inline-flex items-center gap-1.5 text-sm"
            >
              <Plus className="h-4 w-4" />
              Créer le premier projet
            </button>
          </div>
        ) : (
          <>
            {/* Sélecteur de projets — en cours */}
            <div className="mb-4 flex flex-wrap items-center gap-2">
              {projets
                .filter((p) => p.status !== "termine")
                .map((p) => (
                <button
                  key={p.id}
                  type="button"
                  onClick={() => setSelId(p.id)}
                  className={`rounded-xl border px-3 py-2 text-left transition ${
                    p.id === selId ? "border-accent-500" : ""
                  } ${p.status === "termine" ? "opacity-60" : ""}`}
                  style={{
                    borderColor:
                      p.id === selId ? undefined : "var(--qg-border)",
                    backgroundColor: "var(--qg-card-bg)"
                  }}
                >
                  <span
                    className="block text-sm font-semibold"
                    style={{ color: "var(--qg-text)" }}
                  >
                    {p.name}
                  </span>
                  <span
                    className="block text-[11px]"
                    style={{ color: "var(--qg-text-muted)" }}
                  >
                    {p.entreprise_nom}
                    {p.immeuble_nom ? ` · ${p.immeuble_nom}` : ""}
                  </span>
                </button>
              ))}
              {projets.filter((p) => p.status !== "termine").length === 0 ? (
                <p
                  className="text-xs"
                  style={{ color: "var(--qg-text-muted)" }}
                >
                  Aucun projet en cours.
                </p>
              ) : null}
            </div>

            {selId === null ? (
              <p
                className="rounded-xl border py-10 text-center text-sm"
                style={{
                  borderColor: "var(--qg-border)",
                  color: "var(--qg-text-muted)"
                }}
              >
                Choisis un projet ci-dessus pour voir son budget, ses
                objectifs et ses négociations.
              </p>
            ) : loadingDetail && !detail ? (
              <div className="flex items-center justify-center py-12">
                <Loader2 className="h-6 w-6 animate-spin text-accent-500" />
              </div>
            ) : detail ? (
              <div className="space-y-5">
                <ProjetHeader
                  projet={detail}
                  onPatch={patchProjet}
                  onDelete={deleteProjet}
                />
                <div className="grid min-w-0 grid-cols-1 items-start gap-5 xl:grid-cols-[3fr_2fr]">
                  <BudgetSection
                    projet={detail}
                    qboDep={qboDep}
                    qboFin={qboFin}
                    qboSolde={qboSolde}
                    qboErr={qboErr}
                    qboLoading={qboLoading}
                    onRefreshQbo={() => void loadQbo(detail.id)}
                    onPatchProjet={patchProjet}
                    onChanged={() => {
                      void loadDetail(detail.id);
                      void loadQbo(detail.id);
                    }}
                  />
                  <ObjectifsSection projet={detail} onPatch={patchProjet} />
                </div>
                <NegosSection
                  projet={detail}
                  onChanged={() => void loadDetail(detail.id)}
                />
              </div>
            ) : null}

            <ProjetsTermines
              projets={projets}
              selId={selId}
              onSelect={setSelId}
            />
          </>
        )}
      </div>

      {/* Modal création */}
      {createOpen ? (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
          onClick={() => setCreateOpen(false)}
        >
          <form
            onSubmit={submitCreate}
            onClick={(e) => e.stopPropagation()}
            className="w-full max-w-md space-y-3 rounded-2xl border p-4"
            style={{
              borderColor: "var(--qg-border)",
              backgroundColor: "var(--qg-card-bg)"
            }}
          >
            <h3
              className="text-sm font-semibold"
              style={{ color: "var(--qg-text)" }}
            >
              Nouveau projet d&apos;optimisation
            </h3>
            <div>
              <label className="label text-[10px] uppercase">Nom</label>
              <input
                className="input"
                value={cName}
                onChange={(e) => setCName(e.target.value)}
                placeholder="ex. Optimisation 1660 St-Clément"
                autoFocus
              />
            </div>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <div>
                <label className="label text-[10px] uppercase">INC</label>
                <select
                  className="input"
                  value={cEnt}
                  onChange={(e) =>
                    setCEnt(e.target.value ? Number(e.target.value) : "")
                  }
                >
                  <option value="">— choisir —</option>
                  {entreprises.map((e) => (
                    <option key={e.id} value={e.id}>
                      {e.name}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className="label text-[10px] uppercase">Immeuble</label>
                <select
                  className="input"
                  value={cImm}
                  onChange={(e) =>
                    setCImm(e.target.value ? Number(e.target.value) : "")
                  }
                >
                  <option value="">— choisir —</option>
                  {immeubles.map((i) => (
                    <option key={i.id} value={i.id}>
                      {i.name || i.address || `Immeuble #${i.id}`}
                    </option>
                  ))}
                </select>
              </div>
            </div>
            <div>
              <label className="label text-[10px] uppercase">
                Début du projet
              </label>
              <input
                type="date"
                className="input"
                value={cDate}
                onChange={(e) => setCDate(e.target.value)}
              />
              <p
                className="mt-1 text-[10px]"
                style={{ color: "var(--qg-text-muted)" }}
              >
                Les dépenses QuickBooks sont comptées à partir de cette date.
              </p>
            </div>
            <div className="flex items-center justify-end gap-2 pt-1">
              <button
                type="button"
                onClick={() => setCreateOpen(false)}
                className="btn-ghost btn-sm"
              >
                Annuler
              </button>
              <button
                type="submit"
                disabled={creating || !cName.trim() || cEnt === "" || cImm === ""}
                className="btn-accent inline-flex items-center gap-1.5 text-sm disabled:opacity-50"
              >
                {creating ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Plus className="h-4 w-4" />
                )}
                Créer
              </button>
            </div>
          </form>
        </div>
      ) : null}
    </>
  );
}

// ─── Projets terminés (section repliable, en bas de page) ──────

function ProjetsTermines({
  projets,
  selId,
  onSelect
}: {
  projets: ProjetLite[];
  selId: number | null;
  onSelect: (id: number) => void;
}) {
  const [ouvert, setOuvert] = useState(false);
  const termines = projets.filter((p) => p.status === "termine");
  if (termines.length === 0) return null;

  return (
    <section className="mt-6">
      <button
        type="button"
        onClick={() => setOuvert((v) => !v)}
        className="inline-flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider"
        style={{ color: "var(--qg-text-muted)" }}
      >
        {ouvert ? (
          <ChevronDown className="h-3.5 w-3.5" />
        ) : (
          <ChevronRight className="h-3.5 w-3.5" />
        )}
        Projets terminés ({termines.length})
      </button>
      {ouvert ? (
        <div className="mt-2 flex flex-wrap items-center gap-2">
          {termines.map((p) => (
            <button
              key={p.id}
              type="button"
              onClick={() => onSelect(p.id)}
              className={`rounded-xl border px-3 py-2 text-left opacity-70 transition hover:opacity-100 ${
                p.id === selId ? "border-accent-500 opacity-100" : ""
              }`}
              style={{
                borderColor: p.id === selId ? undefined : "var(--qg-border)",
                backgroundColor: "var(--qg-card-bg)"
              }}
            >
              <span
                className="block text-sm font-semibold"
                style={{ color: "var(--qg-text)" }}
              >
                {p.name}
              </span>
              <span
                className="block text-[11px]"
                style={{ color: "var(--qg-text-muted)" }}
              >
                {p.entreprise_nom}
                {p.immeuble_nom ? ` · ${p.immeuble_nom}` : ""}
              </span>
            </button>
          ))}
        </div>
      ) : null}
    </section>
  );
}

// ─── En-tête projet + réglages (engrenage discret) ─────────────

function ProjetHeader({
  projet,
  onPatch,
  onDelete
}: {
  projet: Projet;
  onPatch: (p: Record<string, unknown>) => Promise<void>;
  onDelete: () => void;
}) {
  const [open, setOpen] = useState(false);

  return (
    <section
      className="rounded-xl border p-4"
      style={{
        borderColor: "var(--qg-border)",
        backgroundColor: "var(--qg-card-bg)"
      }}
    >
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <h2
            className="text-base font-semibold"
            style={{ color: "var(--qg-text)" }}
          >
            {projet.name}
          </h2>
          <div
            className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs"
            style={{ color: "var(--qg-text-muted)" }}
          >
            <span className="inline-flex items-center gap-1">
              <Users className="h-3 w-3" />
              {projet.entreprise_nom}
            </span>
            <span className="inline-flex items-center gap-1">
              <Building2 className="h-3 w-3" />
              {projet.immeuble_nom}
            </span>
            {projet.date_debut ? (
              <span className="inline-flex items-center gap-1">
                <Calendar className="h-3 w-3" />
                depuis le {projet.date_debut}
              </span>
            ) : null}
            {projet.status === "termine" ? (
              <span className="badge badge-neutral">Terminé</span>
            ) : (
              <span className="badge badge-emerald">Actif</span>
            )}
          </div>
        </div>
        <div className="flex flex-shrink-0 items-center gap-1">
          <button
            type="button"
            onClick={() =>
              void onPatch({
                status: projet.status === "termine" ? "actif" : "termine"
              })
            }
            className="btn-ghost btn-sm"
            title={
              projet.status === "termine"
                ? "Remettre ce projet en cours"
                : "Marquer ce projet comme terminé (il ira dans la section du bas)"
            }
          >
            {projet.status === "termine" ? "Réactiver" : "Marquer terminé"}
          </button>
          <button
            type="button"
            onClick={() => setOpen((v) => !v)}
            className="btn-ghost flex h-7 w-7 items-center justify-center rounded-lg p-0"
            title="Réglages du projet"
          >
            <Settings2 className="h-4 w-4" />
          </button>
        </div>
      </div>

      {open ? (
        <div
          className="mt-3 grid grid-cols-1 gap-3 rounded-lg border p-3 sm:grid-cols-3"
          style={{ borderColor: "var(--qg-border-soft)" }}
        >
          <div>
            <label className="label text-[10px] uppercase">Nom</label>
            <input
              className="input"
              defaultValue={projet.name}
              onBlur={(e) => {
                const v = e.target.value.trim();
                if (v && v !== projet.name) void onPatch({ name: v });
              }}
            />
          </div>
          <div>
            <label className="label text-[10px] uppercase">Début</label>
            <input
              type="date"
              className="input"
              defaultValue={projet.date_debut || ""}
              onBlur={(e) =>
                void onPatch({ date_debut: e.target.value || null })
              }
            />
          </div>
          <div>
            <label className="label text-[10px] uppercase">Statut</label>
            <select
              className="input"
              value={projet.status}
              onChange={(e) => void onPatch({ status: e.target.value })}
            >
              <option value="actif">Actif</option>
              <option value="termine">Terminé</option>
            </select>
          </div>
          <div className="sm:col-span-2">
            <label className="label text-[10px] uppercase">Notes</label>
            <textarea
              className="input min-h-[60px]"
              defaultValue={projet.notes || ""}
              onBlur={(e) => void onPatch({ notes: e.target.value || null })}
            />
          </div>
          <div className="flex items-end justify-end">
            <button
              type="button"
              onClick={onDelete}
              className="btn-outline-rose btn-sm"
            >
              <Trash2 className="h-3.5 w-3.5" />
              Supprimer le projet
            </button>
          </div>
        </div>
      ) : null}
    </section>
  );
}

// ─── Section 1 : Budget (catégories QBO cochées) ───────────────

function BudgetSection({
  projet,
  qboDep,
  qboFin,
  qboSolde,
  qboErr,
  qboLoading,
  onRefreshQbo,
  onPatchProjet,
  onChanged
}: {
  projet: Projet;
  qboDep: Record<number, number>;
  qboFin: Record<number, number>;
  qboSolde: number | null;
  qboErr: string | null;
  qboLoading: boolean;
  onRefreshQbo: () => void;
  onPatchProjet: (p: Record<string, unknown>) => Promise<void>;
  onChanged: () => void;
}) {
  const [settingsOpen, setSettingsOpen] = useState(false);
  //: Enveloppe dont on mappe les comptes de FINANCEMENT.
  const [finLigne, setFinLigne] = useState<BudgetLigne | null>(null);

  async function patchLigne(id: number, patch: Record<string, unknown>) {
    const r = await authedFetch(`/api/v1/optimisation/budget-lignes/${id}`, {
      method: "PATCH",
      body: JSON.stringify(patch)
    });
    if (r.ok) onChanged();
  }

  const totalBudget = projet.budget_lignes.reduce(
    (s, l) => s + (Number(l.budget_montant) || 0),
    0
  );
  const totalDepense = projet.budget_lignes.reduce(
    (s, l) => s + (qboDep[l.id] || 0),
    0
  );
  const totalComptant = projet.budget_lignes.reduce(
    (s, l) => s + (Number(l.comptant_disponible) || 0),
    0
  );
  const totalFinance = projet.budget_lignes.reduce(
    (s, l) => s + (qboFin[l.id] || 0),
    0
  );

  /** Santé d'une enveloppe, en un coup d'œil. */
  function etat(
    budget: number,
    dep: number | null,
    dispo: number
  ): { label: string; cls: string } | null {
    if (dep === null) return null;
    if (budget > 0 && dep > budget)
      return { label: "Dépassé", cls: "badge badge-rose" };
    if (dispo < 0)
      return { label: "À financer", cls: "badge badge-amber" };
    if (budget > 0 && dep >= budget * 0.85)
      return { label: "Serré", cls: "badge badge-amber" };
    return { label: "OK", cls: "badge badge-emerald" };
  }

  return (
    <section
      className="min-w-0 rounded-xl border p-4"
      style={{
        borderColor: "var(--qg-border)",
        backgroundColor: "var(--qg-card-bg)"
      }}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <h3
            className="text-sm font-semibold"
            style={{ color: "var(--qg-text)" }}
          >
            Budget
          </h3>
          <p
            className="mt-1 inline-flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px]"
            style={{ color: "var(--qg-text-muted)" }}
          >
            <span className="inline-flex items-center gap-1">
              <Landmark className="h-3 w-3" />
              Solde du compte
              <strong
                className="tabular-nums"
                style={{ color: "var(--qg-text)" }}
              >
                {qboSolde === null ? "—" : fmtMoney(qboSolde)}
              </strong>
            </span>
            {projet.qbo_bank_account_name ? (
              <span>{projet.qbo_bank_account_name}</span>
            ) : null}
          </p>
        </div>
        <div className="flex flex-shrink-0 items-center gap-1">
          <button
            type="button"
            onClick={onRefreshQbo}
            disabled={qboLoading}
            className="btn-ghost flex h-7 w-7 items-center justify-center rounded-lg p-0 disabled:opacity-50"
            title="Rafraîchir depuis QuickBooks (lecture seule)"
          >
            {qboLoading ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <RefreshCw className="h-3.5 w-3.5" />
            )}
          </button>
          <button
            type="button"
            onClick={() => setSettingsOpen(true)}
            className="btn-ghost flex h-7 w-7 items-center justify-center rounded-lg p-0"
            title="Connexion QuickBooks, compte bancaire et catégories suivies"
          >
            <Settings2 className="h-4 w-4" />
          </button>
        </div>
      </div>

      {qboErr ? (
        <p className="mt-2 rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs text-amber-300">
          {qboErr}
        </p>
      ) : null}

      {projet.budget_lignes.length === 0 ? (
        <p className="mt-3 text-xs" style={{ color: "var(--qg-text-muted)" }}>
          Clique sur <Settings2 className="inline h-3 w-3" /> pour connecter
          le QuickBooks de l&apos;INC et cocher les catégories du plan
          comptable à suivre — chacune devient une enveloppe : budget saisi
          ici, dépensé lu de QuickBooks, écart calculé.
        </p>
      ) : (
        <div className="mt-3 overflow-x-auto">
          <table className="w-full min-w-[760px] text-sm">
            <thead>
              {/* Deux familles de colonnes : le SUIVI du budget, puis
                  le FINANCEMENT (d'où vient l'argent). */}
              <tr className="text-left text-[10px] uppercase tracking-wider">
                <th className="pb-1" />
                <th
                  colSpan={3}
                  className={`${GRP_BUDGET} rounded-t-lg px-2 pb-1 pt-1.5 text-center font-semibold`}
                >
                  Suivi du budget
                </th>
                <th className="w-2" />
                <th
                  colSpan={3}
                  className={`${GRP_FIN} rounded-t-lg px-2 pb-1 pt-1.5 text-center font-semibold`}
                >
                  Suivi de l&apos;argent disponible
                </th>
                <th className="pb-1" />
              </tr>
              <tr
                className="text-left text-[10px] uppercase tracking-wider"
                style={{ color: "var(--qg-text-muted)" }}
              >
                <th className="pb-2 pr-2">Catégorie</th>
                <th className={`${GRP_BUDGET} pb-2 pl-2 pr-2`}>
                  Budget total
                </th>
                <th className={`${GRP_BUDGET} pb-2 pr-2`}>Total dépensé</th>
                <th className={`${GRP_BUDGET} pb-2 pr-2`}>Écart</th>
                <th />
                <th
                  className={`${GRP_FIN} pb-2 pl-2 pr-2`}
                  title="Argent comptant mis au départ pour cette enveloppe"
                >
                  Comptant initial
                </th>
                <th
                  className={`${GRP_FIN} pb-2 pr-2`}
                  title="Financement encaissé (lu de QuickBooks)"
                >
                  Financé
                </th>
                <th
                  className={`${GRP_FIN} pb-2 pr-2`}
                  title="(Comptant initial + financé) − total dépensé : ce qu'il reste pour payer"
                >
                  Argent disponible
                </th>
                <th className="pb-2 pl-2 text-right">État</th>
              </tr>
            </thead>
            <tbody>
              {projet.budget_lignes.map((l) => {
                const dep = qboDep[l.id] ?? null;
                const fin = qboFin[l.id] ?? 0;
                const budget = Number(l.budget_montant) || 0;
                const comptant = Number(l.comptant_disponible) || 0;
                const ecart = dep === null ? null : budget - dep;
                const dispo = comptant + fin - (dep || 0);
                const nbFin = parseAccounts(
                  l.qbo_financement_accounts_json
                ).length;
                const st = etat(budget, dep, dispo);
                return (
                  <tr
                    key={l.id}
                    className="border-t"
                    style={{ borderColor: "var(--qg-border-soft)" }}
                  >
                    <td
                      className="py-2 pr-2 font-medium"
                      style={{ color: "var(--qg-text)" }}
                    >
                      {l.nom}
                    </td>
                    <td className={`${GRP_BUDGET} py-2 pl-2 pr-2`}>
                      <input
                        className="input h-8 w-24 text-[13px]"
                        type="number"
                        step="0.01"
                        defaultValue={budget || ""}
                        placeholder="0"
                        onBlur={(e) => {
                          const v = Number(e.target.value) || 0;
                          if (v !== budget)
                            void patchLigne(l.id, { budget_montant: v });
                        }}
                      />
                    </td>
                    <td
                      className={`${GRP_BUDGET} py-2 pr-2 tabular-nums`}
                      style={{ color: "var(--qg-text)" }}
                    >
                      {dep === null ? "—" : fmtMoney(dep)}
                    </td>
                    <td
                      className={`${GRP_BUDGET} py-2 pr-2 font-semibold tabular-nums ${
                        ecart === null
                          ? ""
                          : ecart < 0
                            ? "text-rose-400"
                            : "text-emerald-400"
                      }`}
                    >
                      {ecart === null ? "—" : fmtMoney(ecart)}
                    </td>
                    <td />
                    <td className={`${GRP_FIN} py-2 pl-2 pr-2`}>
                      <input
                        className="input h-8 w-24 text-[13px]"
                        type="number"
                        step="0.01"
                        defaultValue={comptant || ""}
                        placeholder="0"
                        title="Argent comptant mis au départ pour cette enveloppe"
                        onBlur={(e) => {
                          const v = Number(e.target.value) || 0;
                          if (v !== comptant)
                            void patchLigne(l.id, {
                              comptant_disponible: v
                            });
                        }}
                      />
                    </td>
                    <td className={`${GRP_FIN} py-2 pr-2`}>
                      <button
                        type="button"
                        onClick={() => setFinLigne(l)}
                        className="inline-flex flex-col items-start text-left"
                        title="Choisir les comptes QuickBooks d'entrée d'argent (financement) de cette enveloppe"
                      >
                        <span
                          className="tabular-nums"
                          style={{ color: "var(--qg-text)" }}
                        >
                          {nbFin === 0 ? "—" : fmtMoney(fin)}
                        </span>
                        <span className="text-[10px] text-accent-500 hover:underline">
                          {nbFin === 0
                            ? "lier un compte"
                            : `${nbFin} compte${nbFin > 1 ? "s" : ""}`}
                        </span>
                      </button>
                    </td>
                    <td
                      className={`${GRP_FIN} py-2 pr-2 font-semibold tabular-nums ${
                        dispo < 0 ? "text-rose-400" : "text-emerald-400"
                      }`}
                    >
                      {fmtMoney(dispo)}
                    </td>
                    <td className="py-2 pl-2 text-right">
                      {st ? <span className={st.cls}>{st.label}</span> : null}
                    </td>
                  </tr>
                );
              })}
              <tr
                className="border-t font-semibold"
                style={{ borderColor: "var(--qg-border)" }}
              >
                <td className="py-2 pr-2" style={{ color: "var(--qg-text)" }}>
                  Total
                </td>
                <td
                  className={`${GRP_BUDGET} rounded-bl-lg py-2 pl-2 pr-2 tabular-nums`}
                  style={{ color: "var(--qg-text)" }}
                >
                  {fmtMoney(totalBudget)}
                </td>
                <td
                  className={`${GRP_BUDGET} py-2 pr-2 tabular-nums`}
                  style={{ color: "var(--qg-text)" }}
                >
                  {fmtMoney(totalDepense)}
                </td>
                <td
                  className={`${GRP_BUDGET} rounded-br-lg py-2 pr-2 tabular-nums ${
                    totalBudget - totalDepense < 0
                      ? "text-rose-400"
                      : "text-emerald-400"
                  }`}
                >
                  {fmtMoney(totalBudget - totalDepense)}
                </td>
                <td />
                <td
                  className={`${GRP_FIN} rounded-bl-lg py-2 pl-2 pr-2 tabular-nums`}
                  style={{ color: "var(--qg-text)" }}
                >
                  {fmtMoney(totalComptant)}
                </td>
                <td
                  className={`${GRP_FIN} py-2 pr-2 tabular-nums`}
                  style={{ color: "var(--qg-text)" }}
                >
                  {fmtMoney(totalFinance)}
                </td>
                <td
                  className={`${GRP_FIN} rounded-br-lg py-2 pr-2 tabular-nums ${
                    totalComptant + totalFinance - totalDepense < 0
                      ? "text-rose-400"
                      : "text-emerald-400"
                  }`}
                >
                  {fmtMoney(totalComptant + totalFinance - totalDepense)}
                </td>
                <td />
              </tr>
            </tbody>
          </table>
        </div>
      )}

      {settingsOpen ? (
        <BudgetSettingsModal
          projet={projet}
          onPatchProjet={onPatchProjet}
          onClose={() => setSettingsOpen(false)}
          onChanged={onChanged}
        />
      ) : null}

      {finLigne ? (
        <FinancementModal
          projet={projet}
          ligne={finLigne}
          onClose={() => setFinLigne(null)}
          onSaved={() => {
            setFinLigne(null);
            onChanged();
          }}
        />
      ) : null}
    </section>
  );
}

// ─── Modal : comptes de FINANCEMENT d'une enveloppe ────────────

function FinancementModal({
  projet,
  ligne,
  onClose,
  onSaved
}: {
  projet: Projet;
  ligne: BudgetLigne;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [comptes, setComptes] = useState<QboCompte[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState("");
  const [saving, setSaving] = useState(false);
  const [sel, setSel] = useState<Map<string, string>>(
    () =>
      new Map(
        parseAccounts(ligne.qbo_financement_accounts_json).map((a) => [
          a.id,
          a.name
        ])
      )
  );

  useEffect(() => {
    void (async () => {
      try {
        const r = await authedFetch(
          `/api/v1/optimisation/qbo-comptes?scope=${encodeURIComponent(
            projet.qbo_scope || `inc:${projet.entreprise_id}`
          )}&kind=financement`
        );
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const d = (await r.json()) as {
          comptes: QboCompte[];
          erreur: string | null;
        };
        if (d.erreur) setErr(d.erreur);
        setComptes(d.comptes || []);
      } catch (e) {
        setErr(`Comptes illisibles : ${(e as Error).message}`);
      } finally {
        setLoading(false);
      }
    })();
  }, [projet.qbo_scope, projet.entreprise_id]);

  async function save() {
    setSaving(true);
    try {
      const arr = Array.from(sel.entries()).map(([id, name]) => ({
        id,
        name
      }));
      const r = await authedFetch(
        `/api/v1/optimisation/budget-lignes/${ligne.id}`,
        {
          method: "PATCH",
          body: JSON.stringify({
            qbo_financement_accounts_json: JSON.stringify(arr)
          })
        }
      );
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      onSaved();
    } catch (e) {
      setErr(`Sauvegarde échouée : ${(e as Error).message}`);
      setSaving(false);
    }
  }

  const visibles = comptes.filter((c) =>
    c.fully_qualified_name.toLowerCase().includes(filter.toLowerCase())
  );

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
      onClick={onClose}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="flex max-h-[80vh] w-full max-w-lg flex-col rounded-2xl border p-4"
        style={{
          borderColor: "var(--qg-border)",
          backgroundColor: "var(--qg-card-bg)"
        }}
      >
        <h3
          className="text-sm font-semibold"
          style={{ color: "var(--qg-text)" }}
        >
          Financement — « {ligne.nom} »
        </h3>
        <p
          className="mt-1 text-[11px]"
          style={{ color: "var(--qg-text-muted)" }}
        >
          Coche les comptes QuickBooks par lesquels l&apos;argent RENTRE
          pour cette enveloppe (prêt, marge de crédit, apport, subvention…).
          On avance les fonds, le remboursement arrive progressivement.
        </p>
        {err ? (
          <p className="mt-2 rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs text-amber-300">
            {err}
          </p>
        ) : null}
        {loading ? (
          <div className="flex items-center justify-center py-8">
            <Loader2 className="h-5 w-5 animate-spin text-accent-500" />
          </div>
        ) : comptes.length > 0 ? (
          <>
            <input
              className="input mt-2"
              placeholder="Filtrer…"
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
            />
            <div className="mt-2 min-h-0 flex-1 space-y-0.5 overflow-y-auto pr-1">
              {visibles.map((c) => (
                <label
                  key={c.id}
                  className="flex cursor-pointer items-start gap-2 rounded-md px-1.5 py-1 text-[12px] hover:bg-accent-500/10"
                  style={{ color: "var(--qg-text)" }}
                >
                  <input
                    type="checkbox"
                    className="mt-0.5"
                    checked={sel.has(c.id)}
                    onChange={(e) =>
                      setSel((prev) => {
                        const next = new Map(prev);
                        if (e.target.checked) next.set(c.id, c.name);
                        else next.delete(c.id);
                        return next;
                      })
                    }
                  />
                  <span>
                    {c.fully_qualified_name}
                    <span
                      className="ml-1 text-[10px]"
                      style={{ color: "var(--qg-text-muted)" }}
                    >
                      ({c.account_type})
                    </span>
                  </span>
                </label>
              ))}
            </div>
          </>
        ) : null}
        <div className="mt-3 flex items-center justify-end gap-2">
          <button type="button" onClick={onClose} className="btn-ghost btn-sm">
            Annuler
          </button>
          <button
            type="button"
            onClick={() => void save()}
            disabled={saving}
            className="btn-accent inline-flex items-center gap-1.5 text-sm disabled:opacity-50"
          >
            {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
            Enregistrer ({sel.size})
          </button>
        </div>
      </div>
    </div>
  );
}

// ─── Modal réglages budget : connexion QBO + catégories ────────

function BudgetSettingsModal({
  projet,
  onPatchProjet,
  onClose,
  onChanged
}: {
  projet: Projet;
  onPatchProjet: (p: Record<string, unknown>) => Promise<void>;
  onClose: () => void;
  onChanged: () => void;
}) {
  const confirm = useConfirm();
  // La connexion d'un projet d'optimisation est TOUJOURS le fichier
  // QuickBooks de l'INC (accessible via le compte comptable MGV) — pas
  // de choix à faire : on pose le scope automatiquement.
  const incScope = `inc:${projet.entreprise_id}`;
  const scope = incScope;
  useEffect(() => {
    if (projet.qbo_scope !== incScope) {
      void onPatchProjet({ qbo_scope: incScope });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [incScope]);

  const [status, setStatus] = useState<{
    connected: boolean;
    company_name: string | null;
  } | null>(null);
  const [connecting, setConnecting] = useState(false);

  const [comptes, setComptes] = useState<QboCompte[]>([]);
  const [comptesErr, setComptesErr] = useState<string | null>(null);
  const [comptesLoading, setComptesLoading] = useState(false);
  const [filter, setFilter] = useState("");
  const [saving, setSaving] = useState(false);

  // Comptes déjà suivis (une ligne budget = un compte).
  const lignesParCompte = useMemo(() => {
    const m = new Map<string, BudgetLigne>();
    for (const l of projet.budget_lignes) {
      for (const a of parseAccounts(l.qbo_accounts_json)) {
        m.set(a.id, l);
      }
    }
    return m;
  }, [projet.budget_lignes]);
  const [sel, setSel] = useState<Map<string, string>>(
    () =>
      new Map(
        Array.from(lignesParCompte.entries()).map(([id, l]) => [id, l.nom])
      )
  );

  // Statut de la connexion choisie.
  useEffect(() => {
    setStatus(null);
    if (!scope) return;
    let dead = false;
    void (async () => {
      try {
        const r = await authedFetch(
          `/api/v1/qbo/status?scope=${encodeURIComponent(scope)}`
        );
        if (!r.ok) return;
        const d = (await r.json()) as {
          connected: boolean;
          company_name: string | null;
        };
        if (!dead) setStatus(d);
      } catch {
        /* statut inconnu */
      }
    })();
    return () => {
      dead = true;
    };
  }, [scope]);

  // Plan comptable dès que connecté.
  useEffect(() => {
    setComptes([]);
    setComptesErr(null);
    if (!scope || !status?.connected) return;
    let dead = false;
    setComptesLoading(true);
    void (async () => {
      try {
        const r = await authedFetch(
          `/api/v1/optimisation/qbo-comptes?scope=${encodeURIComponent(scope)}`
        );
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const d = (await r.json()) as {
          comptes: QboCompte[];
          erreur: string | null;
        };
        if (dead) return;
        if (d.erreur) setComptesErr(d.erreur);
        setComptes(d.comptes || []);
      } catch (e) {
        if (!dead)
          setComptesErr(`Plan comptable illisible : ${(e as Error).message}`);
      } finally {
        if (!dead) setComptesLoading(false);
      }
    })();
    return () => {
      dead = true;
    };
  }, [scope, status?.connected]);

  async function connecter() {
    if (!scope) return;
    setConnecting(true);
    try {
      const r = await authedFetch(
        `/api/v1/qbo/connect?scope=${encodeURIComponent(scope)}`
      );
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const d = (await r.json()) as { auth_url: string };
      window.location.assign(d.auth_url);
    } catch {
      setConnecting(false);
    }
  }

  async function save() {
    setSaving(true);
    try {
      // Nouvelles catégories cochées → une enveloppe chacune.
      const aCreer = Array.from(sel.entries()).filter(
        ([id]) => !lignesParCompte.has(id)
      );
      // Catégories décochées → suppression de leur enveloppe.
      const aSupprimer = Array.from(lignesParCompte.entries()).filter(
        ([id]) => !sel.has(id)
      );
      if (aSupprimer.length > 0) {
        const ok = await confirm({
          title: `Retirer ${aSupprimer.length} catégorie${
            aSupprimer.length > 1 ? "s" : ""
          } ?`,
          description:
            "Les budgets saisis sur ces enveloppes seront perdus. (Rien n'est touché dans QuickBooks.)",
          confirmLabel: "Retirer",
          destructive: true
        });
        if (!ok) {
          setSaving(false);
          return;
        }
      }
      for (const [id, name] of aCreer) {
        await authedFetch(
          `/api/v1/optimisation/projets/${projet.id}/budget-lignes`,
          {
            method: "POST",
            body: JSON.stringify({
              nom: name,
              budget_montant: 0,
              qbo_accounts_json: JSON.stringify([{ id, name }])
            })
          }
        );
      }
      const idsSupprimes = new Set(aSupprimer.map(([, l]) => l.id));
      for (const lid of idsSupprimes) {
        await authedFetch(`/api/v1/optimisation/budget-lignes/${lid}`, {
          method: "DELETE"
        });
      }
      onChanged();
      onClose();
    } finally {
      setSaving(false);
    }
  }

  const visibles = comptes.filter((c) =>
    c.fully_qualified_name.toLowerCase().includes(filter.toLowerCase())
  );

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
      onClick={onClose}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="flex max-h-[85vh] w-full max-w-lg flex-col rounded-2xl border p-4"
        style={{
          borderColor: "var(--qg-border)",
          backgroundColor: "var(--qg-card-bg)"
        }}
      >
        <h3
          className="text-sm font-semibold"
          style={{ color: "var(--qg-text)" }}
        >
          Réglages QuickBooks du budget
        </h3>

        {status && !status.connected ? (
          <div className="mt-3">
            <p
              className="text-[11px]"
              style={{ color: "var(--qg-text-muted)" }}
            >
              Le budget se lit dans le fichier QuickBooks de{" "}
              <strong>{projet.entreprise_nom}</strong>. Connecte-toi avec
              ton compte comptable (MGV Développement) — Intuit te
              demandera quelle compagnie ouvrir : choisis{" "}
              {projet.entreprise_nom}.
            </p>
            <button
              type="button"
              onClick={() => void connecter()}
              disabled={connecting}
              className="btn-accent mt-2 inline-flex items-center gap-1.5 text-sm disabled:opacity-50"
            >
              {connecting ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : null}
              Connecter le QuickBooks de {projet.entreprise_nom}
            </button>
          </div>
        ) : status?.connected ? (
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <p className="text-[11px] text-emerald-400">
              ✓ Connecté
              {status.company_name ? ` — ${status.company_name}` : ""}
            </p>
            <button
              type="button"
              onClick={() => void connecter()}
              disabled={connecting}
              className="btn-ghost btn-sm"
              title="Refaire la connexion Intuit (ex. mauvais fichier choisi)"
            >
              Changer
            </button>
          </div>
        ) : (
          <div className="flex items-center justify-center py-4">
            <Loader2 className="h-4 w-4 animate-spin text-accent-500" />
          </div>
        )}

        {status?.connected ? (
          <>
            <BankAccountPicker projet={projet} onPatch={onPatchProjet} />
            <label className="label mt-3 text-[10px] uppercase">
              Catégories du plan comptable à suivre
            </label>
            {comptesErr ? (
              <p className="mt-1 rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs text-amber-300">
                {comptesErr}
              </p>
            ) : null}
            {comptesLoading ? (
              <div className="flex items-center justify-center py-6">
                <Loader2 className="h-5 w-5 animate-spin text-accent-500" />
              </div>
            ) : comptes.length > 0 ? (
              <>
                <input
                  className="input mt-1"
                  placeholder="Filtrer…"
                  value={filter}
                  onChange={(e) => setFilter(e.target.value)}
                />
                <div className="mt-2 min-h-0 flex-1 space-y-0.5 overflow-y-auto pr-1">
                  {visibles.map((c) => (
                    <label
                      key={c.id}
                      className="flex cursor-pointer items-start gap-2 rounded-md px-1.5 py-1 text-[12px] hover:bg-accent-500/10"
                      style={{ color: "var(--qg-text)" }}
                    >
                      <input
                        type="checkbox"
                        className="mt-0.5"
                        checked={sel.has(c.id)}
                        onChange={(e) =>
                          setSel((prev) => {
                            const next = new Map(prev);
                            if (e.target.checked) next.set(c.id, c.name);
                            else next.delete(c.id);
                            return next;
                          })
                        }
                      />
                      <span>
                        {c.fully_qualified_name}
                        <span
                          className="ml-1 text-[10px]"
                          style={{ color: "var(--qg-text-muted)" }}
                        >
                          ({c.account_type})
                        </span>
                      </span>
                    </label>
                  ))}
                </div>
              </>
            ) : null}
          </>
        ) : null}

        <div className="mt-3 flex items-center justify-end gap-2">
          <button type="button" onClick={onClose} className="btn-ghost btn-sm">
            Fermer
          </button>
          {status?.connected && comptes.length > 0 ? (
            <button
              type="button"
              onClick={() => void save()}
              disabled={saving}
              className="btn-accent inline-flex items-center gap-1.5 text-sm disabled:opacity-50"
            >
              {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
              Enregistrer ({sel.size})
            </button>
          ) : null}
        </div>
      </div>
    </div>
  );
}

// ─── Compte bancaire du projet (solde affiché sur le budget) ───

function BankAccountPicker({
  projet,
  onPatch
}: {
  projet: Projet;
  onPatch: (p: Record<string, unknown>) => Promise<void>;
}) {
  const [comptes, setComptes] = useState<QboCompte[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    void (async () => {
      try {
        const r = await authedFetch(
          `/api/v1/optimisation/qbo-comptes?scope=${encodeURIComponent(
            projet.qbo_scope || `inc:${projet.entreprise_id}`
          )}&kind=banque`
        );
        if (!r.ok) return;
        const d = (await r.json()) as { comptes: QboCompte[] };
        setComptes(d.comptes || []);
      } finally {
        setLoading(false);
      }
    })();
  }, [projet.qbo_scope, projet.entreprise_id]);

  return (
    <div className="mt-3">
      <label className="label text-[10px] uppercase">
        Compte bancaire du projet
      </label>
      {loading ? (
        <div className="flex items-center gap-2 py-1">
          <Loader2 className="h-3.5 w-3.5 animate-spin text-accent-500" />
        </div>
      ) : (
        <select
          className="input"
          value={projet.qbo_bank_account_id || ""}
          onChange={(e) => {
            const id = e.target.value;
            const c = comptes.find((x) => x.id === id);
            void onPatch({
              qbo_bank_account_id: id || null,
              qbo_bank_account_name: c ? c.name : null
            });
          }}
        >
          <option value="">— aucun —</option>
          {comptes.map((c) => (
            <option key={c.id} value={c.id}>
              {c.fully_qualified_name}
            </option>
          ))}
        </select>
      )}
      <p
        className="mt-1 text-[10px]"
        style={{ color: "var(--qg-text-muted)" }}
      >
        Son solde courant s&apos;affiche en haut du budget.
      </p>
    </div>
  );
}

// ─── Section 2 : Objectifs ─────────────────────────────────────

function ObjectifsSection({
  projet,
  onPatch
}: {
  projet: Projet;
  onPatch: (p: Record<string, unknown>) => Promise<void>;
}) {
  const objectifs = parseObjectifs(projet.objectifs_json);
  const [nLabel, setNLabel] = useState("");
  const [nCible, setNCible] = useState("");
  const [nUnite, setNUnite] = useState("");
  //: Vue mensuelle ou annuelle — les deux objectifs sont saisissables,
  //: celui qui manque est déduit (× ou ÷ 12).
  const [periode, setPeriode] = useState<"mois" | "annee">("mois");
  const annuel = periode === "annee";
  const k = annuel ? 12 : 1;

  function saveObjectifs(next: ObjectifLibre[]) {
    void onPatch({ objectifs_json: JSON.stringify(next) });
  }

  const revMois = Number(projet.objectif_revenus_mensuels) || 0;
  const revAn = Number(projet.objectif_revenus_annuels) || 0;
  const revObj = annuel ? revAn || revMois * 12 : revMois || revAn / 12;
  const revAct = (projet.revenus_actuels_mensuels || 0) * k;
  //: Le pourcentage réel est affiché même au-delà de 100 % ; seule la
  //: largeur de la barre est bornée.
  const revPct = revObj > 0 ? Math.round((revAct / revObj) * 100) : 0;
  const depMois = Number(projet.objectif_depenses_mensuelles) || 0;
  const depAn = Number(projet.objectif_depenses_annuelles) || 0;
  const depObj = annuel ? depAn || depMois * 12 : depMois || depAn / 12;
  const depAct = (projet.depenses_actuelles_mensuelles || 0) * k;
  const depPct = depObj > 0 ? Math.round((depAct / depObj) * 100) : 0;
  const suffixe = annuel ? "/an" : "/mois";

  const histo = projet.revenus_historique || [];
  const histoMax = Math.max(
    revObj,
    ...histo.map((h) => h.montant),
    1
  );

  return (
    <section
      className="min-w-0 rounded-xl border p-4"
      style={{
        borderColor: "var(--qg-border)",
        backgroundColor: "var(--qg-card-bg)"
      }}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3
          className="flex items-center gap-1.5 text-sm font-semibold"
          style={{ color: "var(--qg-text)" }}
        >
          <Target className="h-4 w-4 text-accent-500" />
          Objectifs vs réel (Gestion locative)
        </h3>
        <div
          className="inline-flex rounded-lg border p-0.5"
          style={{ borderColor: "var(--qg-border)" }}
        >
          {(["mois", "annee"] as const).map((v) => (
            <button
              key={v}
              type="button"
              onClick={() => setPeriode(v)}
              className={`rounded-md px-2.5 py-1 text-[11px] font-semibold transition ${
                periode === v ? "bg-accent-500 text-brand-950" : ""
              }`}
              style={
                periode === v ? undefined : { color: "var(--qg-text-muted)" }
              }
            >
              {v === "mois" ? "Par mois" : "Par année"}
            </button>
          ))}
        </div>
      </div>

      <div className="mt-3 grid grid-cols-1 gap-3">
        {/* Revenus + progression mensuelle */}
        <div
          className="rounded-lg border p-3"
          style={{ borderColor: "var(--qg-border-soft)" }}
        >
          <div className="flex items-center justify-between gap-2">
            <span
              className="text-xs font-medium"
              style={{ color: "var(--qg-text)" }}
            >
              Revenus {annuel ? "annuels" : "mensuels"}
            </span>
            <span
              className="flex items-center gap-1 text-[11px]"
              style={{ color: "var(--qg-text-muted)" }}
            >
              Objectif
              <input
                key={`rev-${periode}`}
                className="input h-7 w-28 text-right text-[12px]"
                type="number"
                step="0.01"
                defaultValue={revObj || ""}
                onBlur={(e) => {
                  // Mois et année sont la MÊME valeur : on écrit les
                  // deux pour qu'elles restent d'accord (retour Phil).
                  const v = Number(e.target.value) || 0;
                  void onPatch(
                    v
                      ? annuel
                        ? {
                            objectif_revenus_annuels: v,
                            objectif_revenus_mensuels: v / 12
                          }
                        : {
                            objectif_revenus_mensuels: v,
                            objectif_revenus_annuels: v * 12
                          }
                      : {
                          objectif_revenus_mensuels: null,
                          objectif_revenus_annuels: null
                        }
                  );
                }}
              />
            </span>
          </div>
          <p
            className="mt-2 text-lg font-semibold tabular-nums"
            style={{ color: "var(--qg-text)" }}
          >
            {fmtMoney(revAct)}
            <span
              className="ml-1 text-xs font-normal"
              style={{ color: "var(--qg-text-muted)" }}
            >
              / {revObj ? fmtMoney(revObj) : "—"} {suffixe} si tous les
              loyers rentrent
            </span>
          </p>
          <p
            className="text-[11px]"
            style={{ color: "var(--qg-text-faint)" }}
          >
            {fmtMoney(projet.revenus_actuels_mensuels || 0)}/mois ·{" "}
            {fmtMoney((projet.revenus_actuels_mensuels || 0) * 12)}/an
          </p>
          {revObj > 0 ? (
            <>
              <div
                className="mt-2 h-2 w-full overflow-hidden rounded-full"
                style={{ backgroundColor: "var(--qg-border-soft)" }}
              >
                <div
                  className={`h-full rounded-full ${
                    revPct >= 100 ? "bg-emerald-500" : "bg-accent-500"
                  }`}
                  style={{ width: `${Math.min(100, revPct)}%` }}
                />
              </div>
              <p
                className="mt-1 text-[11px]"
                style={{ color: "var(--qg-text-muted)" }}
              >
                {revAct >= revObj
                  ? `${revPct} % — objectif atteint ✓${
                      revPct > 100
                        ? ` (+${fmtMoney(revAct - revObj)} ${suffixe})`
                        : ""
                    }`
                  : `${revPct} % — il manque ${fmtMoney(
                      revObj - revAct
                    )} ${suffixe}`}
              </p>
            </>
          ) : null}
          {histo.length > 1 ? (
            <div className="mt-3">
              <p
                className="mb-1 text-[10px] uppercase tracking-wider"
                style={{ color: "var(--qg-text-muted)" }}
              >
                Progression depuis le début du projet
              </p>
              <div className="relative flex h-20 items-end gap-[3px]">
                {revObj > 0 ? (
                  <div
                    className="absolute left-0 right-0 border-t border-dashed border-amber-400/70"
                    style={{
                      bottom: `${Math.min(100, (revObj / histoMax) * 100)}%`
                    }}
                    title={`Objectif : ${fmtMoney(revObj)}`}
                  />
                ) : null}
                {histo.map((h) => (
                  <div
                    key={h.mois}
                    className={`flex-1 rounded-t ${
                      revObj > 0 && h.montant >= revObj
                        ? "bg-emerald-500/80"
                        : "bg-accent-500/70"
                    }`}
                    style={{
                      height: `${Math.max(3, (h.montant / histoMax) * 100)}%`
                    }}
                    title={`${h.mois} : ${fmtMoney(h.montant)}`}
                  />
                ))}
              </div>
              <div
                className="mt-0.5 flex justify-between text-[9px]"
                style={{ color: "var(--qg-text-muted)" }}
              >
                <span>{histo[0]?.mois}</span>
                <span>{histo[histo.length - 1]?.mois}</span>
              </div>
            </div>
          ) : null}
        </div>

        {/* Dépenses */}
        <div
          className="rounded-lg border p-3"
          style={{ borderColor: "var(--qg-border-soft)" }}
        >
          <div className="flex items-center justify-between gap-2">
            <span
              className="text-xs font-medium"
              style={{ color: "var(--qg-text)" }}
            >
              Dépenses courantes {annuel ? "annuelles" : "mensuelles"}
            </span>
            <span
              className="flex items-center gap-1 text-[11px]"
              style={{ color: "var(--qg-text-muted)" }}
            >
              Objectif
              <input
                key={`dep-${periode}`}
                className="input h-7 w-28 text-right text-[12px]"
                type="number"
                step="0.01"
                defaultValue={depObj || ""}
                onBlur={(e) => {
                  const v = Number(e.target.value) || 0;
                  void onPatch(
                    v
                      ? annuel
                        ? {
                            objectif_depenses_annuelles: v,
                            objectif_depenses_mensuelles: v / 12
                          }
                        : {
                            objectif_depenses_mensuelles: v,
                            objectif_depenses_annuelles: v * 12
                          }
                      : {
                          objectif_depenses_mensuelles: null,
                          objectif_depenses_annuelles: null
                        }
                  );
                }}
              />
            </span>
          </div>
          <p
            className="mt-2 text-lg font-semibold tabular-nums"
            style={{ color: "var(--qg-text)" }}
          >
            {fmtMoney(depAct)}
            <span
              className="ml-1 text-xs font-normal"
              style={{ color: "var(--qg-text-muted)" }}
            >
              / {depObj ? fmtMoney(depObj) : "—"} {suffixe} (cashflow de
              l&apos;immeuble)
            </span>
          </p>
          <p
            className="text-[11px]"
            style={{ color: "var(--qg-text-faint)" }}
          >
            {fmtMoney(projet.depenses_actuelles_mensuelles || 0)}/mois ·{" "}
            {fmtMoney((projet.depenses_actuelles_mensuelles || 0) * 12)}/an
          </p>
          {depObj > 0 ? (
            <>
              <div
                className="mt-2 h-2 w-full overflow-hidden rounded-full"
                style={{ backgroundColor: "var(--qg-border-soft)" }}
              >
                <div
                  className={`h-full rounded-full ${
                    depAct <= depObj ? "bg-emerald-500" : "bg-rose-500"
                  }`}
                  style={{ width: `${Math.min(100, depPct)}%` }}
                />
              </div>
              <p
                className={`mt-1 text-[11px] ${
                  depAct <= depObj ? "text-emerald-400" : "text-rose-400"
                }`}
              >
                {depAct <= depObj
                  ? `${depPct} % — sous l'objectif de ${fmtMoney(
                      depObj - depAct
                    )} ${suffixe} ✓`
                  : `${depPct} % — dépasse l'objectif de ${fmtMoney(
                      depAct - depObj
                    )} ${suffixe}`}
              </p>
            </>
          ) : null}
        </div>

        {/* Objectifs libres — même style de tuile */}
        {objectifs.map((o, i) => {
          const pct =
            o.cible > 0
              ? Math.round(((o.actuel || 0) / o.cible) * 100)
              : 0;
          return (
            <div
              key={i}
              className="rounded-lg border p-3"
              style={{ borderColor: "var(--qg-border-soft)" }}
            >
              <div className="flex items-center justify-between gap-2">
                <span
                  className="text-xs font-medium"
                  style={{ color: "var(--qg-text)" }}
                >
                  {o.label}
                </span>
                <span
                  className="flex items-center gap-1 text-[11px]"
                  style={{ color: "var(--qg-text-muted)" }}
                >
                  Objectif
                  <input
                    className="input h-7 w-24 text-right text-[12px]"
                    type="number"
                    step="0.01"
                    defaultValue={o.cible || ""}
                    onBlur={(e) => {
                      const next = [...objectifs];
                      next[i] = { ...o, cible: Number(e.target.value) || 0 };
                      saveObjectifs(next);
                    }}
                  />
                  {o.unite && o.unite !== "$" ? o.unite : null}
                  <button
                    type="button"
                    onClick={() =>
                      saveObjectifs(objectifs.filter((_, j) => j !== i))
                    }
                    className="ml-1 text-rose-400/70 hover:text-rose-400"
                    title="Retirer cet objectif"
                  >
                    <Trash2 className="h-3 w-3" />
                  </button>
                </span>
              </div>
              <p
                className="mt-2 text-lg font-semibold tabular-nums"
                style={{ color: "var(--qg-text)" }}
              >
                <input
                  className="input inline-block h-8 w-28 text-[15px] font-semibold"
                  type="number"
                  step="0.01"
                  defaultValue={o.actuel || ""}
                  placeholder="0"
                  onBlur={(e) => {
                    const next = [...objectifs];
                    next[i] = { ...o, actuel: Number(e.target.value) || 0 };
                    saveObjectifs(next);
                  }}
                />
                <span
                  className="ml-1 text-xs font-normal"
                  style={{ color: "var(--qg-text-muted)" }}
                >
                  / {fmtVal(o.cible, o.unite)}
                </span>
              </p>
              <div
                className="mt-2 h-2 w-full overflow-hidden rounded-full"
                style={{ backgroundColor: "var(--qg-border-soft)" }}
              >
                <div
                  className={`h-full rounded-full ${
                    pct >= 100 ? "bg-emerald-500" : "bg-accent-500"
                  }`}
                  style={{
                    width: `${pct > 0 ? Math.max(2, Math.min(100, pct)) : 0}%`
                  }}
                />
              </div>
              <p
                className={`mt-1 text-[11px] ${
                  pct >= 100 ? "text-emerald-400" : "text-accent-500"
                }`}
              >
                {pct} %
                {pct >= 100
                  ? " — objectif atteint ✓"
                  : ` — il manque ${fmtVal(
                      Math.max(0, o.cible - (o.actuel || 0)),
                      o.unite
                    )}`}
              </p>
            </div>
          );
        })}
      </div>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (!nLabel.trim()) return;
          saveObjectifs([
            ...objectifs,
            {
              label: nLabel.trim(),
              cible: Number(nCible) || 0,
              actuel: 0,
              unite: nUnite.trim() || "$"
            }
          ]);
          setNLabel("");
          setNCible("");
          setNUnite("");
        }}
        className="mt-3 flex flex-wrap items-center gap-2"
      >
        <input
          className="input h-8 min-w-[150px] flex-1 text-[12px]"
          placeholder="Autre objectif (ex. chambres louées)"
          value={nLabel}
          onChange={(e) => setNLabel(e.target.value)}
        />
        <input
          className="input h-8 w-24 text-[12px]"
          type="number"
          step="0.01"
          placeholder="Cible"
          value={nCible}
          onChange={(e) => setNCible(e.target.value)}
        />
        <input
          className="input h-8 w-24 text-[12px]"
          placeholder="Unité ($)"
          value={nUnite}
          onChange={(e) => setNUnite(e.target.value)}
        />
        <button
          type="submit"
          disabled={!nLabel.trim()}
          className="btn-secondary btn-sm disabled:opacity-50"
        >
          <Plus className="h-3.5 w-3.5" />
          Ajouter
        </button>
      </form>
    </section>
  );
}

// ─── Section 3 : Négociations locataires (kanban + liste) ──────

const KANBAN_COLS = [
  "en_place",
  "a_contacter",
  "en_discussion",
  "entente",
  "reste"
];

/** Colonne d'accueil d'une négo (statut legacy → première colonne). */
function colonneDe(statut: string): string {
  return KANBAN_COLS.includes(statut) ? statut : "en_place";
}

function NegosSection({
  projet,
  onChanged
}: {
  projet: Projet;
  onChanged: () => void;
}) {
  const confirm = useConfirm();
  const [view, setView] = useState<"kanban" | "liste">("kanban");
  const [openId, setOpenId] = useState<number | null>(null);
  const [modalNegoId, setModalNegoId] = useState<number | null>(null);
  const [importOpen, setImportOpen] = useState(false);
  const [dragId, setDragId] = useState<number | null>(null);
  const [dragOverCol, setDragOverCol] = useState<string | null>(null);

  const nEntentes = projet.negos.filter((n) => n.statut === "entente").length;
  const modalNego =
    projet.negos.find((n) => n.id === modalNegoId) || null;

  async function patchNego(id: number, patch: Record<string, unknown>) {
    const r = await authedFetch(`/api/v1/optimisation/negos/${id}`, {
      method: "PATCH",
      body: JSON.stringify(patch)
    });
    if (r.ok) onChanged();
  }

  async function deleteNego(n: Nego) {
    const ok = await confirm({
      title: `Retirer « ${n.nom_locataire} » du suivi ?`,
      description:
        "Le suivi de négociation et sa timeline seront perdus. (La fiche locataire du locatif n'est pas touchée.)",
      confirmLabel: "Retirer",
      destructive: true
    });
    if (!ok) return;
    const r = await authedFetch(`/api/v1/optimisation/negos/${n.id}`, {
      method: "DELETE"
    });
    if (r.ok || r.status === 204) {
      setModalNegoId(null);
      setOpenId(null);
      onChanged();
    }
  }

  return (
    <section
      className="rounded-xl border p-4"
      style={{
        borderColor: "var(--qg-border)",
        backgroundColor: "var(--qg-card-bg)"
      }}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3
          className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm font-semibold"
          style={{ color: "var(--qg-text)" }}
        >
          <Users className="h-4 w-4 text-accent-500" />
          Négociations locataires
          <span
            className="text-xs font-normal"
            style={{ color: "var(--qg-text-muted)" }}
          >
            {projet.nb_logements} logement
            {projet.nb_logements > 1 ? "s" : ""} · {projet.negos.length}{" "}
            locataire{projet.negos.length > 1 ? "s" : ""} suivi
            {projet.negos.length > 1 ? "s" : ""}
          </span>
          <span
            className={`badge ${
              nEntentes > 0 ? "badge-emerald" : "badge-neutral"
            }`}
            title="Ententes conclues / locataires suivis"
          >
            Ententes {nEntentes}/{projet.negos.length}
          </span>
        </h3>
        <div className="flex items-center gap-1">
          <button
            type="button"
            onClick={() => setView("kanban")}
            className={`btn-ghost flex h-7 w-7 items-center justify-center rounded-lg p-0 ${
              view === "kanban" ? "text-accent-500" : ""
            }`}
            title="Vue kanban"
          >
            <LayoutGrid className="h-4 w-4" />
          </button>
          <button
            type="button"
            onClick={() => setView("liste")}
            className={`btn-ghost flex h-7 w-7 items-center justify-center rounded-lg p-0 ${
              view === "liste" ? "text-accent-500" : ""
            }`}
            title="Vue liste"
          >
            <List className="h-4 w-4" />
          </button>
          <button
            type="button"
            onClick={() => setImportOpen(true)}
            className="btn-ghost flex h-7 w-7 items-center justify-center rounded-lg p-0"
            title="Importer des locataires de l'immeuble dans le suivi"
          >
            <UserPlus className="h-4 w-4" />
          </button>
        </div>
      </div>

      {projet.negos.length === 0 ? (
        <p className="mt-3 text-xs" style={{ color: "var(--qg-text-muted)" }}>
          Aucun locataire suivi. Clique sur{" "}
          <UserPlus className="inline h-3 w-3" /> pour choisir les
          locataires en place à suivre.
        </p>
      ) : view === "kanban" ? (
        <div className="-mx-1 mt-3 flex gap-3 overflow-x-auto px-1 pb-2">
          {KANBAN_COLS.map((col) => {
            const st = NEGO_STATUTS[col];
            const cards = projet.negos.filter(
              (n) => colonneDe(n.statut) === col
            );
            const isHover = dragOverCol === col;
            return (
              <div
                key={col}
                onDragOver={(e) => {
                  e.preventDefault();
                  setDragOverCol(col);
                }}
                onDragLeave={() =>
                  setDragOverCol((c) => (c === col ? null : c))
                }
                onDrop={() => {
                  if (dragId !== null) {
                    const n = projet.negos.find((x) => x.id === dragId);
                    if (n && n.statut !== col)
                      void patchNego(dragId, { statut: col });
                  }
                  setDragId(null);
                  setDragOverCol(null);
                }}
                className={`flex w-[248px] flex-shrink-0 flex-col rounded-2xl border transition ${
                  isHover ? "border-accent-500 ring-2 ring-accent-500/20" : ""
                }`}
                style={{
                  borderColor: isHover ? undefined : "var(--qg-border)",
                  backgroundColor: "var(--qg-bg-alt)"
                }}
              >
                <div
                  className="flex items-center justify-between gap-2 border-b px-3 py-2.5"
                  style={{ borderColor: "var(--qg-border)" }}
                >
                  <h4
                    className="inline-flex min-w-0 items-center gap-2 text-[11px] font-semibold uppercase tracking-wider"
                    style={{ color: "var(--qg-text)" }}
                  >
                    <span
                      className={`h-2 w-2 flex-shrink-0 rounded-full ${st.dot}`}
                    />
                    <span className="truncate">{st.court}</span>
                  </h4>
                  <span
                    className="flex-shrink-0 rounded-md px-2 py-0.5 text-[11px] font-semibold tabular-nums"
                    style={{
                      backgroundColor: "var(--qg-card-bg)",
                      color: "var(--qg-text-muted)"
                    }}
                  >
                    {cards.length}
                  </span>
                </div>

                <div className="flex min-h-[96px] flex-col gap-2 p-2">
                  {cards.length === 0 ? (
                    <p
                      className="px-1 py-4 text-center text-[11px]"
                      style={{ color: "var(--qg-text-faint)" }}
                    >
                      Glisse une carte ici
                    </p>
                  ) : null}
                  {cards.map((n) => (
                    <button
                      key={n.id}
                      type="button"
                      draggable
                      onDragStart={() => setDragId(n.id)}
                      onDragEnd={() => {
                        setDragId(null);
                        setDragOverCol(null);
                      }}
                      onClick={() => setModalNegoId(n.id)}
                      className={`group block w-full cursor-grab rounded-xl border p-2.5 text-left shadow-sm transition hover:-translate-y-0.5 hover:border-accent-500 hover:shadow-md active:cursor-grabbing ${
                        dragId === n.id ? "opacity-40" : ""
                      }`}
                      style={{
                        borderColor: "var(--qg-border)",
                        backgroundColor: "var(--qg-bg)"
                      }}
                    >
                      <span
                        className="block truncate text-[13px] font-semibold"
                        style={{ color: "var(--qg-text)" }}
                      >
                        {n.nom_locataire}
                      </span>
                      {n.logement_label || n.loyer_actuel ? (
                        <span
                          className="mt-1 flex items-center gap-1.5 text-[11px]"
                          style={{ color: "var(--qg-text-muted)" }}
                        >
                          {n.logement_label ? (
                            <span className="inline-flex items-center gap-1">
                              <Building2 className="h-3 w-3" />
                              {n.logement_label}
                            </span>
                          ) : null}
                          {n.loyer_actuel ? (
                            <span className="tabular-nums">
                              {fmtMoney(n.loyer_actuel)}/mois
                            </span>
                          ) : null}
                        </span>
                      ) : null}
                      {n.type_entente || n.montant_entente || n.date_cible ? (
                        <span className="mt-2 flex flex-wrap items-center gap-1">
                          {n.type_entente && TYPES_ENTENTE[n.type_entente] ? (
                            <span
                              className="rounded-md px-1.5 py-0.5 text-[10px] font-medium"
                              style={{
                                backgroundColor: "var(--qg-bg-alt)",
                                color: "var(--qg-text-muted)"
                              }}
                            >
                              {TYPES_ENTENTE[n.type_entente]}
                            </span>
                          ) : null}
                          {n.montant_entente ? (
                            <span className="rounded-md bg-amber-500/15 px-1.5 py-0.5 text-[10px] font-semibold tabular-nums text-amber-500">
                              {fmtMoney(n.montant_entente)}
                            </span>
                          ) : null}
                          {n.date_cible ? (
                            <span
                              className="inline-flex items-center gap-0.5 text-[10px] tabular-nums"
                              style={{ color: "var(--qg-text-faint)" }}
                            >
                              <Calendar className="h-2.5 w-2.5" />
                              {n.date_cible}
                            </span>
                          ) : null}
                        </span>
                      ) : null}
                    </button>
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      ) : (
        <ul className="mt-3 space-y-2">
          {projet.negos.map((n) => {
            const st = NEGO_STATUTS[n.statut] || NEGO_STATUTS.en_place;
            const open = openId === n.id;
            return (
              <li
                key={n.id}
                className="rounded-lg border"
                style={{ borderColor: "var(--qg-border-soft)" }}
              >
                <button
                  type="button"
                  onClick={() => setOpenId(open ? null : n.id)}
                  className="flex w-full flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2 text-left"
                >
                  <span
                    className="min-w-[140px] flex-1 text-sm font-medium"
                    style={{ color: "var(--qg-text)" }}
                  >
                    {n.nom_locataire}
                    {n.logement_label ? (
                      <span
                        className="ml-1.5 text-[11px] font-normal"
                        style={{ color: "var(--qg-text-muted)" }}
                      >
                        · {n.logement_label}
                      </span>
                    ) : null}
                  </span>
                  {n.loyer_actuel ? (
                    <span
                      className="text-[11px] tabular-nums"
                      style={{ color: "var(--qg-text-muted)" }}
                    >
                      {fmtMoney(n.loyer_actuel)}/mois
                    </span>
                  ) : null}
                  {n.type_entente && TYPES_ENTENTE[n.type_entente] ? (
                    <span
                      className="text-[11px]"
                      style={{ color: "var(--qg-text-muted)" }}
                    >
                      {TYPES_ENTENTE[n.type_entente]}
                    </span>
                  ) : null}
                  {n.montant_entente ? (
                    <span className="text-[11px] tabular-nums text-amber-300">
                      {fmtMoney(n.montant_entente)}
                    </span>
                  ) : null}
                  <span className={st.cls}>{st.label}</span>
                </button>
                {open ? (
                  <div
                    className="border-t px-3 py-3"
                    style={{ borderColor: "var(--qg-border-soft)" }}
                  >
                    <NegoDetailPanel
                      nego={n}
                      onPatch={patchNego}
                      onDelete={() => void deleteNego(n)}
                    />
                  </div>
                ) : null}
              </li>
            );
          })}
        </ul>
      )}

      {modalNego ? (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
          onClick={() => setModalNegoId(null)}
        >
          <div
            onClick={(e) => e.stopPropagation()}
            className="max-h-[85vh] w-full max-w-2xl overflow-y-auto rounded-2xl border p-4"
            style={{
              borderColor: "var(--qg-border)",
              backgroundColor: "var(--qg-card-bg)"
            }}
          >
            <div className="mb-3 flex items-start justify-between gap-2">
              <div>
                <h3
                  className="text-sm font-semibold"
                  style={{ color: "var(--qg-text)" }}
                >
                  {modalNego.nom_locataire}
                </h3>
                <p
                  className="text-[11px]"
                  style={{ color: "var(--qg-text-muted)" }}
                >
                  {modalNego.logement_label
                    ? `Logement ${modalNego.logement_label}`
                    : ""}
                  {modalNego.loyer_actuel
                    ? `${modalNego.logement_label ? " · " : ""}${fmtMoney(
                        modalNego.loyer_actuel
                      )}/mois`
                    : ""}
                </p>
              </div>
              <button
                type="button"
                onClick={() => setModalNegoId(null)}
                className="btn-ghost flex h-7 w-7 items-center justify-center rounded-lg p-0"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
            <NegoDetailPanel
              nego={modalNego}
              onPatch={patchNego}
              onDelete={() => void deleteNego(modalNego)}
            />
          </div>
        </div>
      ) : null}

      {importOpen ? (
        <ImportLocatairesModal
          projet={projet}
          onClose={() => setImportOpen(false)}
          onImported={() => {
            setImportOpen(false);
            onChanged();
          }}
        />
      ) : null}
    </section>
  );
}

// ─── Détail d'une négo (partagé liste / modal kanban) ──────────

function NegoDetailPanel({
  nego: n,
  onPatch,
  onDelete
}: {
  nego: Nego;
  onPatch: (id: number, patch: Record<string, unknown>) => Promise<void>;
  onDelete: () => void;
}) {
  const events = parseEvents(n.events_json);
  return (
    <>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <div>
          <label className="label text-[10px] uppercase">Statut</label>
          <select
            className="input"
            value={n.statut}
            onChange={(e) => void onPatch(n.id, { statut: e.target.value })}
          >
            {Object.entries(NEGO_STATUTS).map(([k, v]) => (
              <option key={k} value={k}>
                {v.label}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="label text-[10px] uppercase">
            Type d&apos;entente
          </label>
          <select
            className="input"
            value={n.type_entente || ""}
            onChange={(e) =>
              void onPatch(n.id, { type_entente: e.target.value || null })
            }
          >
            <option value="">—</option>
            {Object.entries(TYPES_ENTENTE).map(([k, v]) => (
              <option key={k} value={k}>
                {v}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="label text-[10px] uppercase">
            Montant en jeu ($)
          </label>
          <input
            className="input"
            type="number"
            step="0.01"
            defaultValue={n.montant_entente || ""}
            onBlur={(e) =>
              void onPatch(n.id, {
                montant_entente: Number(e.target.value) || null
              })
            }
            placeholder="indemnité, nouveau loyer…"
          />
        </div>
        <div>
          <label className="label text-[10px] uppercase">Date visée</label>
          <input
            className="input"
            type="date"
            defaultValue={n.date_cible || ""}
            onBlur={(e) =>
              void onPatch(n.id, { date_cible: e.target.value || null })
            }
          />
        </div>
        <div className="sm:col-span-2 xl:col-span-3">
          <label className="label text-[10px] uppercase">
            Entente / notes
          </label>
          <textarea
            className="input min-h-[54px]"
            defaultValue={n.entente || ""}
            onBlur={(e) =>
              void onPatch(n.id, { entente: e.target.value || null })
            }
            placeholder="ex. Accepte de quitter le 1er juillet contre 3 mois de loyer…"
          />
        </div>
        <div className="flex items-end justify-end">
          <button
            type="button"
            onClick={onDelete}
            className="btn-outline-rose btn-sm"
          >
            <Trash2 className="h-3.5 w-3.5" />
            Retirer
          </button>
        </div>
      </div>

      <RecherchePanel nego={n} onPatch={onPatch} />

      <div className="mt-3">
        <h4
          className="text-[10px] font-semibold uppercase tracking-wider"
          style={{ color: "var(--qg-text-muted)" }}
        >
          Timeline
        </h4>
        {events.length > 0 ? (
          <ul
            className="mt-1.5 space-y-1 border-l pl-3"
            style={{ borderColor: "var(--qg-border-soft)" }}
          >
            {events.map((ev, i) => (
              <li
                key={i}
                className="text-[12px]"
                style={{ color: "var(--qg-text)" }}
              >
                <span
                  className="mr-2 tabular-nums text-[11px]"
                  style={{ color: "var(--qg-text-muted)" }}
                >
                  {ev.date}
                </span>
                {ev.texte}
              </li>
            ))}
          </ul>
        ) : null}
        <form
          onSubmit={(e) => {
            e.preventDefault();
            const input = e.currentTarget.elements.namedItem(
              "ev"
            ) as HTMLInputElement;
            const v = input.value.trim();
            if (!v) return;
            void onPatch(n.id, { add_event: v });
            input.value = "";
          }}
          className="mt-2 flex items-center gap-2"
        >
          <input
            name="ev"
            className="input h-8 flex-1 text-[12px]"
            placeholder="Ajouter un événement (appel, rencontre, offre…)"
          />
          <button type="submit" className="btn-secondary btn-sm">
            <Plus className="h-3.5 w-3.5" />
          </button>
        </form>
      </div>
    </>
  );
}

// ─── Préparation de la négo : recherche sur le locataire ───────

const RECHERCHE_CHAMPS: {
  cle: keyof Recherche;
  label: string;
  placeholder: string;
}[] = [
  { cle: "emploi", label: "Emploi / métier", placeholder: "ex. électricien" },
  { cle: "employeur", label: "Employeur", placeholder: "ex. Hydro-Québec" },
  {
    cle: "revenu_estime",
    label: "Revenu estimé",
    placeholder: "ex. 70 000 $/an"
  },
  { cle: "linkedin", label: "LinkedIn", placeholder: "lien du profil" },
  { cle: "facebook", label: "Facebook", placeholder: "lien du profil" },
  { cle: "instagram", label: "Instagram", placeholder: "@ ou lien" },
  {
    cle: "autres",
    label: "Autres trouvailles",
    placeholder: "site, annonce, journal…"
  }
];

function RecherchePanel({
  nego: n,
  onPatch
}: {
  nego: Nego;
  onPatch: (id: number, patch: Record<string, unknown>) => Promise<void>;
}) {
  const r = parseRecherche(n.recherche_json);

  function setChamp(cle: keyof Recherche, valeur: string) {
    const next: Recherche = { ...r };
    if (valeur.trim()) next[cle] = valeur.trim();
    else delete next[cle];
    void onPatch(n.id, { recherche_json: JSON.stringify(next) });
  }

  const q = encodeURIComponent(n.nom_locataire);
  const liens = [
    { label: "Google", url: `https://www.google.com/search?q=${q}` },
    {
      label: "LinkedIn",
      url: `https://www.linkedin.com/search/results/all/?keywords=${q}`
    },
    {
      label: "Facebook",
      url: `https://www.facebook.com/search/top?q=${q}`
    },
    {
      label: "Registraire des entreprises",
      url: "https://www.registreentreprises.gouv.qc.ca/RQAnonymeGR/GR/GR03/GR03A2_19A_PIU_RechEnt_PC/PageRechSimple.aspx"
    }
  ];

  return (
    <div className="mt-4">
      <h4
        className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[10px] font-semibold uppercase tracking-wider"
        style={{ color: "var(--qg-text-muted)" }}
      >
        <Search className="h-3 w-3" />
        Préparation de la négo
        <span className="inline-flex flex-wrap items-center gap-1 normal-case tracking-normal">
          {liens.map((l) => (
            <a
              key={l.label}
              href={l.url}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 text-[10px] font-normal transition hover:border-accent-500 hover:text-accent-500"
              style={{
                borderColor: "var(--qg-border)",
                color: "var(--qg-text-muted)"
              }}
              title={`Chercher « ${n.nom_locataire} » sur ${l.label}`}
            >
              {l.label}
              <ExternalLink className="h-2.5 w-2.5" />
            </a>
          ))}
        </span>
      </h4>

      <div className="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-2 xl:grid-cols-4">
        {RECHERCHE_CHAMPS.map((c) => (
          <div key={c.cle}>
            <label className="label text-[10px] uppercase">{c.label}</label>
            <input
              className="input h-8 text-[12px]"
              defaultValue={(r[c.cle] as string) || ""}
              placeholder={c.placeholder}
              onBlur={(e) => {
                if ((e.target.value || "") !== ((r[c.cle] as string) || ""))
                  setChamp(c.cle, e.target.value);
              }}
            />
          </div>
        ))}
        <div className="sm:col-span-2 xl:col-span-4">
          <label className="label text-[10px] uppercase">
            Notes de recherche
          </label>
          <textarea
            className="input min-h-[54px] text-[12px]"
            defaultValue={r.notes || ""}
            placeholder="Ce qu'on sait de sa situation, ce qui peut l'intéresser dans une entente…"
            onBlur={(e) => {
              if ((e.target.value || "") !== (r.notes || ""))
                setChamp("notes", e.target.value);
            }}
          />
        </div>
      </div>
    </div>
  );
}

// ─── Modal import sélectif des locataires ──────────────────────

function ImportLocatairesModal({
  projet,
  onClose,
  onImported
}: {
  projet: Projet;
  onClose: () => void;
  onImported: () => void;
}) {
  const [rows, setRows] = useState<LocataireDispo[]>([]);
  const [loading, setLoading] = useState(true);
  const [sel, setSel] = useState<Set<number>>(new Set());
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    void (async () => {
      try {
        const r = await authedFetch(
          `/api/v1/optimisation/projets/${projet.id}/locataires-disponibles`
        );
        if (!r.ok) return;
        const d = (await r.json()) as LocataireDispo[];
        setRows(d);
        setSel(
          new Set(
            d.filter((x) => !x.deja_suivi).map((x) => x.locataire_id)
          )
        );
      } finally {
        setLoading(false);
      }
    })();
  }, [projet.id]);

  async function importer() {
    setSaving(true);
    try {
      const r = await authedFetch(
        `/api/v1/optimisation/projets/${projet.id}/importer-locataires`,
        {
          method: "POST",
          body: JSON.stringify({ locataire_ids: Array.from(sel) })
        }
      );
      if (r.ok) onImported();
    } finally {
      setSaving(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
      onClick={onClose}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="flex max-h-[80vh] w-full max-w-md flex-col rounded-2xl border p-4"
        style={{
          borderColor: "var(--qg-border)",
          backgroundColor: "var(--qg-card-bg)"
        }}
      >
        <h3
          className="text-sm font-semibold"
          style={{ color: "var(--qg-text)" }}
        >
          Importer des locataires — {projet.immeuble_nom}
        </h3>
        <p className="mt-1 text-[11px]" style={{ color: "var(--qg-text-muted)" }}>
          Locataires à bail actif de l&apos;immeuble. Choisis ceux à suivre
          dans les négociations.
        </p>
        {loading ? (
          <div className="flex items-center justify-center py-8">
            <Loader2 className="h-5 w-5 animate-spin text-accent-500" />
          </div>
        ) : rows.length === 0 ? (
          <p
            className="py-6 text-center text-xs"
            style={{ color: "var(--qg-text-muted)" }}
          >
            Aucun locataire à bail actif sur cet immeuble.
          </p>
        ) : (
          <div className="mt-2 min-h-0 flex-1 space-y-0.5 overflow-y-auto pr-1">
            {rows.map((x) => (
              <label
                key={x.locataire_id}
                className={`flex items-center gap-2 rounded-md px-1.5 py-1.5 text-[12px] ${
                  x.deja_suivi
                    ? "opacity-50"
                    : "cursor-pointer hover:bg-accent-500/10"
                }`}
                style={{ color: "var(--qg-text)" }}
              >
                <input
                  type="checkbox"
                  disabled={x.deja_suivi}
                  checked={x.deja_suivi || sel.has(x.locataire_id)}
                  onChange={(e) =>
                    setSel((prev) => {
                      const next = new Set(prev);
                      if (e.target.checked) next.add(x.locataire_id);
                      else next.delete(x.locataire_id);
                      return next;
                    })
                  }
                />
                <span className="flex-1">
                  {x.nom}
                  {x.logement ? (
                    <span style={{ color: "var(--qg-text-muted)" }}>
                      {" "}· {x.logement}
                    </span>
                  ) : null}
                </span>
                {x.loyer ? (
                  <span
                    className="tabular-nums text-[11px]"
                    style={{ color: "var(--qg-text-muted)" }}
                  >
                    {fmtMoney(x.loyer)}
                  </span>
                ) : null}
                {x.deja_suivi ? (
                  <span className="badge badge-neutral">déjà suivi</span>
                ) : null}
              </label>
            ))}
          </div>
        )}
        <div className="mt-3 flex items-center justify-end gap-2">
          <button type="button" onClick={onClose} className="btn-ghost btn-sm">
            Annuler
          </button>
          <button
            type="button"
            onClick={() => void importer()}
            disabled={saving || sel.size === 0}
            className="btn-accent inline-flex items-center gap-1.5 text-sm disabled:opacity-50"
          >
            {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : (
              <UserPlus className="h-4 w-4" />
            )}
            Importer ({sel.size})
          </button>
        </div>
      </div>
    </div>
  );
}
