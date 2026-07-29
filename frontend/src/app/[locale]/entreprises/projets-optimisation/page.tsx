"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Building2,
  Calendar,
  Loader2,
  Plus,
  RefreshCw,
  Settings2,
  Target,
  Trash2,
  TrendingUp,
  UserPlus,
  Users
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
  objectif_revenus_mensuels: number | null;
  objectif_depenses_mensuelles: number | null;
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
type LocataireDispo = {
  locataire_id: number;
  nom: string;
  logement: string | null;
  loyer: number | null;
  deja_suivi: boolean;
};

const QBO_SCOPES_FIXES = [
  { value: "immobilier", label: "QuickBooks — Gestion locative" },
  { value: "entreprise", label: "QuickBooks — Gestion d'entreprise" },
  { value: "construction", label: "QuickBooks — Construction" }
];

const NEGO_STATUTS: Record<string, { label: string; cls: string }> = {
  en_place: { label: "En place", cls: "badge badge-neutral" },
  a_contacter: { label: "À contacter", cls: "badge badge-amber" },
  en_discussion: { label: "En discussion", cls: "badge badge-sky" },
  entente: { label: "Entente conclue", cls: "badge badge-emerald" },
  parti: { label: "Parti", cls: "badge badge-neutral" },
  reste: { label: "Reste en place", cls: "badge badge-emerald" }
};

const TYPES_ENTENTE: Record<string, string> = {
  cash_for_raise: "Cash for raise",
  cash_for_keys: "Cash for keys",
  renovation: "Rénovation",
  autre: "Autre"
};

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

  // Sélection automatique du premier projet actif à l'arrivée — pas
  // besoin de cliquer une tuile pour voir les détails.
  useEffect(() => {
    if (selId === null && projets.length > 0) {
      setSelId(
        projets.find((x) => x.status === "actif")?.id ?? projets[0].id
      );
    }
  }, [projets, selId]);

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
        erreur: string | null;
      };
      setQboDep(d.par_ligne || {});
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
  const [cImport, setCImport] = useState(true);
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
          importer_locataires: cImport
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

      <div className="p-4 lg:p-6">
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
            {/* Sélecteur de projets */}
            <div className="mb-4 flex flex-wrap items-center gap-2">
              {projets.map((p) => (
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
                    {p.status === "termine" ? " · terminé" : ""}
                  </span>
                </button>
              ))}
            </div>

            {loadingDetail && !detail ? (
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
                <div className="grid min-w-0 grid-cols-1 items-start gap-5 xl:grid-cols-2">
                  <BudgetSection
                    projet={detail}
                    qboDep={qboDep}
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
            <label
              className="flex cursor-pointer items-center gap-2 text-xs"
              style={{ color: "var(--qg-text)" }}
            >
              <input
                type="checkbox"
                checked={cImport}
                onChange={(e) => setCImport(e.target.checked)}
              />
              Importer les locataires en place (baux actifs) dans le suivi
              des négociations
            </label>
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
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          className="btn-ghost flex h-7 w-7 items-center justify-center rounded-lg p-0"
          title="Réglages du projet"
        >
          <Settings2 className="h-4 w-4" />
        </button>
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
  qboErr,
  qboLoading,
  onRefreshQbo,
  onPatchProjet,
  onChanged
}: {
  projet: Projet;
  qboDep: Record<number, number>;
  qboErr: string | null;
  qboLoading: boolean;
  onRefreshQbo: () => void;
  onPatchProjet: (p: Record<string, unknown>) => Promise<void>;
  onChanged: () => void;
}) {
  const [settingsOpen, setSettingsOpen] = useState(false);

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

  return (
    <section
      className="min-w-0 rounded-xl border p-4"
      style={{
        borderColor: "var(--qg-border)",
        backgroundColor: "var(--qg-card-bg)"
      }}
    >
      <div className="flex items-center justify-between gap-2">
        <h3
          className="text-sm font-semibold"
          style={{ color: "var(--qg-text)" }}
        >
          Budget &amp; dépensé (QuickBooks)
        </h3>
        <div className="flex items-center gap-1">
          <button
            type="button"
            onClick={onRefreshQbo}
            disabled={qboLoading}
            className="btn-ghost flex h-7 w-7 items-center justify-center rounded-lg p-0 disabled:opacity-50"
            title="Rafraîchir le dépensé depuis QuickBooks (lecture seule)"
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
            title="Connexion QuickBooks + choix des catégories du plan comptable"
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
          <table className="w-full min-w-[430px] text-sm">
            <thead>
              <tr
                className="text-left text-[10px] uppercase tracking-wider"
                style={{ color: "var(--qg-text-muted)" }}
              >
                <th className="pb-2 pr-2">Catégorie</th>
                <th className="pb-2 pr-2">Budget</th>
                <th className="pb-2 pr-2">Dépensé</th>
                <th className="pb-2 text-right">Écart</th>
              </tr>
            </thead>
            <tbody>
              {projet.budget_lignes.map((l) => {
                const dep = qboDep[l.id] ?? null;
                const budget = Number(l.budget_montant) || 0;
                const reste = dep === null ? null : budget - dep;
                const over = reste !== null && reste < 0;
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
                    <td className="py-2 pr-2">
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
                      className="py-2 pr-2 tabular-nums"
                      style={{ color: "var(--qg-text)" }}
                    >
                      {dep === null ? "—" : fmtMoney(dep)}
                    </td>
                    <td
                      className={`py-2 text-right font-semibold tabular-nums ${
                        reste === null
                          ? ""
                          : over
                            ? "text-rose-400"
                            : "text-emerald-400"
                      }`}
                    >
                      {reste === null ? "—" : fmtMoney(reste)}
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
                  className="py-2 pr-2 tabular-nums"
                  style={{ color: "var(--qg-text)" }}
                >
                  {fmtMoney(totalBudget)}
                </td>
                <td
                  className="py-2 pr-2 tabular-nums"
                  style={{ color: "var(--qg-text)" }}
                >
                  {fmtMoney(totalDepense)}
                </td>
                <td
                  className={`py-2 text-right tabular-nums ${
                    totalBudget - totalDepense < 0
                      ? "text-rose-400"
                      : "text-emerald-400"
                  }`}
                >
                  {fmtMoney(totalBudget - totalDepense)}
                </td>
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
    </section>
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
  const incScope = `inc:${projet.entreprise_id}`;
  const scope = projet.qbo_scope || "";

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

        <label className="label mt-3 text-[10px] uppercase">
          Connexion QuickBooks
        </label>
        <select
          className="input"
          value={scope}
          onChange={(e) =>
            void onPatchProjet({ qbo_scope: e.target.value || null })
          }
        >
          <option value="">— choisir —</option>
          <option value={incScope}>
            QuickBooks de {projet.entreprise_nom} (propre à l&apos;INC)
          </option>
          {QBO_SCOPES_FIXES.map((s) => (
            <option key={s.value} value={s.value}>
              {s.label}
            </option>
          ))}
        </select>
        {!scope ? (
          <p
            className="mt-2 text-[11px]"
            style={{ color: "var(--qg-text-muted)" }}
          >
            Choisis d&apos;abord la connexion — normalement le QuickBooks
            propre à l&apos;INC du projet.
          </p>
        ) : status && !status.connected ? (
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <span className="text-[11px] text-amber-300">Non connecté.</span>
            <button
              type="button"
              onClick={() => void connecter()}
              disabled={connecting}
              className="btn-outline-accent btn-sm disabled:opacity-50"
              title="Ouvre Intuit : choisis le fichier QuickBooks de cette compagnie et autorise Kratos (lecture)."
            >
              {connecting ? (
                <Loader2 className="h-3 w-3 animate-spin" />
              ) : null}
              Connecter ce QuickBooks
            </button>
          </div>
        ) : status?.connected ? (
          <p className="mt-1 text-[11px] text-emerald-400">
            ✓ Connecté{status.company_name ? ` — ${status.company_name}` : ""}
          </p>
        ) : null}

        {status?.connected ? (
          <>
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

  function saveObjectifs(next: ObjectifLibre[]) {
    void onPatch({ objectifs_json: JSON.stringify(next) });
  }

  const revObj = Number(projet.objectif_revenus_mensuels) || 0;
  const revAct = projet.revenus_actuels_mensuels || 0;
  const revPct =
    revObj > 0 ? Math.min(100, Math.round((revAct / revObj) * 100)) : 0;
  const depObj = Number(projet.objectif_depenses_mensuelles) || 0;
  const depAct = projet.depenses_actuelles_mensuelles || 0;

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
      <h3
        className="flex items-center gap-1.5 text-sm font-semibold"
        style={{ color: "var(--qg-text)" }}
      >
        <Target className="h-4 w-4 text-accent-500" />
        Objectifs vs réel (Gestion locative)
      </h3>

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
              Revenus mensuels
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
                defaultValue={revObj || ""}
                onBlur={(e) =>
                  void onPatch({
                    objectif_revenus_mensuels:
                      Number(e.target.value) || null
                  })
                }
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
              / {revObj ? fmtMoney(revObj) : "—"} par mois si tous les
              loyers rentrent
            </span>
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
                  style={{ width: `${revPct}%` }}
                />
              </div>
              <p
                className="mt-1 text-[11px]"
                style={{ color: "var(--qg-text-muted)" }}
              >
                {revAct >= revObj
                  ? "Objectif atteint ✓"
                  : `${revPct} % — il manque ${fmtMoney(revObj - revAct)} / mois`}
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
              Dépenses mensuelles courantes
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
                defaultValue={depObj || ""}
                onBlur={(e) =>
                  void onPatch({
                    objectif_depenses_mensuelles:
                      Number(e.target.value) || null
                  })
                }
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
              / {depObj ? fmtMoney(depObj) : "—"} (cashflow de l&apos;immeuble)
            </span>
          </p>
          {depObj > 0 ? (
            <p
              className={`mt-1 text-[11px] ${
                depAct <= depObj ? "text-emerald-400" : "text-rose-400"
              }`}
            >
              {depAct <= depObj
                ? `Sous l'objectif de ${fmtMoney(depObj - depAct)} / mois ✓`
                : `Dépasse l'objectif de ${fmtMoney(depAct - depObj)} / mois`}
            </p>
          ) : null}
        </div>

        {/* Objectifs libres — même style de tuile */}
        {objectifs.map((o, i) => {
          const pct =
            o.cible > 0
              ? Math.min(100, Math.round(((o.actuel || 0) / o.cible) * 100))
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
                <button
                  type="button"
                  onClick={() =>
                    saveObjectifs(objectifs.filter((_, j) => j !== i))
                  }
                  className="text-rose-400/70 hover:text-rose-400"
                  title="Retirer cet objectif"
                >
                  <Trash2 className="h-3 w-3" />
                </button>
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
                  style={{ width: `${pct}%` }}
                />
              </div>
              <p
                className="mt-1 text-[11px]"
                style={{ color: "var(--qg-text-muted)" }}
              >
                {pct} %{pct >= 100 ? " — objectif atteint ✓" : ""}
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

// ─── Section 3 : Négociations locataires ───────────────────────

function NegosSection({
  projet,
  onChanged
}: {
  projet: Projet;
  onChanged: () => void;
}) {
  const confirm = useConfirm();
  const [openId, setOpenId] = useState<number | null>(null);
  const [importOpen, setImportOpen] = useState(false);

  const nEntentes = projet.negos.filter((n) => n.statut === "entente").length;

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
    if (r.ok || r.status === 204) onChanged();
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
        <button
          type="button"
          onClick={() => setImportOpen(true)}
          className="btn-ghost flex h-7 w-7 items-center justify-center rounded-lg p-0"
          title="Importer des locataires de l'immeuble dans le suivi"
        >
          <UserPlus className="h-4 w-4" />
        </button>
      </div>

      {projet.negos.length === 0 ? (
        <p className="mt-3 text-xs" style={{ color: "var(--qg-text-muted)" }}>
          Aucun locataire suivi. Clique sur{" "}
          <UserPlus className="inline h-3 w-3" /> pour choisir les
          locataires en place à suivre.
        </p>
      ) : (
        <ul className="mt-3 space-y-2">
          {projet.negos.map((n) => {
            const st = NEGO_STATUTS[n.statut] || NEGO_STATUTS.en_place;
            const events = parseEvents(n.events_json);
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
                    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
                      <div>
                        <label className="label text-[10px] uppercase">
                          Statut
                        </label>
                        <select
                          className="input"
                          value={n.statut}
                          onChange={(e) =>
                            void patchNego(n.id, { statut: e.target.value })
                          }
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
                            void patchNego(n.id, {
                              type_entente: e.target.value || null
                            })
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
                            void patchNego(n.id, {
                              montant_entente:
                                Number(e.target.value) || null
                            })
                          }
                          placeholder="indemnité, nouveau loyer…"
                        />
                      </div>
                      <div>
                        <label className="label text-[10px] uppercase">
                          Date visée
                        </label>
                        <input
                          className="input"
                          type="date"
                          defaultValue={n.date_cible || ""}
                          onBlur={(e) =>
                            void patchNego(n.id, {
                              date_cible: e.target.value || null
                            })
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
                            void patchNego(n.id, {
                              entente: e.target.value || null
                            })
                          }
                          placeholder="ex. Accepte de quitter le 1er juillet contre 3 mois de loyer…"
                        />
                      </div>
                      <div className="flex items-end justify-end">
                        <button
                          type="button"
                          onClick={() => void deleteNego(n)}
                          className="btn-outline-rose btn-sm"
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                          Retirer
                        </button>
                      </div>
                    </div>

                    {/* Timeline */}
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
                          void patchNego(n.id, { add_event: v });
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
                  </div>
                ) : null}
              </li>
            );
          })}
        </ul>
      )}

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
