"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Building2,
  Calendar,
  Loader2,
  Pencil,
  Plus,
  RefreshCw,
  Settings2,
  Target,
  Trash2,
  TrendingUp,
  Users
} from "lucide-react";

import { authedFetch } from "@/lib/auth";
import { useConfirm } from "@/components/confirm-dialog";
import { QGTopbar, useEntreprisesLayout } from "../layout";

/**
 * Projets - Optimisation : un projet = une INC + un immeuble.
 * 1) Budget par enveloppe vs dépensé réel QuickBooks (lecture seule)
 * 2) Objectifs initiaux vs réels de la Gestion locative
 * 3) Négociations avec les locataires en place (statuts + timeline)
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
type ObjectifLibre = { label: string; cible: number; actuel: number };

const QBO_SCOPES = [
  { value: "immobilier", label: "QuickBooks — Gestion locative" },
  { value: "entreprise", label: "QuickBooks — Gestion d'entreprise" },
  { value: "construction", label: "QuickBooks — Construction" }
];

const NEGO_STATUTS: Record<string, { label: string; cls: string }> = {
  en_place: { label: "En place", cls: "badge badge-neutral" },
  a_contacter: { label: "À contacter", cls: "badge badge-amber" },
  en_discussion: { label: "En discussion", cls: "badge badge-sky" },
  entente: { label: "Entente conclue", cls: "badge badge-emerald" },
  depart_prevu: { label: "Départ prévu", cls: "badge badge-violet" },
  parti: { label: "Parti", cls: "badge badge-neutral" },
  reste: { label: "Reste (statu quo)", cls: "badge badge-emerald" }
};

function fmtMoney(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return new Intl.NumberFormat("fr-CA", {
    style: "currency",
    currency: "CAD",
    maximumFractionDigits: 0
  }).format(v);
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

  // Dépenses QBO par ligne + erreur éventuelle.
  const [qboDep, setQboDep] = useState<Record<number, number>>({});
  const [qboErr, setQboErr] = useState<string | null>(null);
  const [qboLoading, setQboLoading] = useState(false);

  const loadList = useCallback(async (keepSel = false) => {
    try {
      const r = await authedFetch("/api/v1/optimisation/projets");
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const rows = (await r.json()) as ProjetLite[];
      setProjets(rows);
      setSelId((cur) => {
        if (keepSel && cur && rows.some((x) => x.id === cur)) return cur;
        return rows.find((x) => x.status === "actif")?.id ?? rows[0]?.id ?? null;
      });
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
      void loadList(true);
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
      await loadList();
    }
  }

  const sel = useMemo(
    () => projets.find((p) => p.id === selId) || null,
    [projets, selId]
  );

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
                <BudgetSection
                  projet={detail}
                  qboDep={qboDep}
                  qboErr={qboErr}
                  qboLoading={qboLoading}
                  onRefreshQbo={() => void loadQbo(detail.id)}
                  onChanged={() => {
                    void loadDetail(detail.id);
                    void loadQbo(detail.id);
                  }}
                />
                <ObjectifsSection projet={detail} onPatch={patchProjet} />
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

// ─── En-tête projet + réglages ─────────────────────────────────

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
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => setOpen((v) => !v)}
            className="btn-outline-accent btn-sm"
          >
            <Settings2 className="h-3.5 w-3.5" />
            Réglages
          </button>
        </div>
      </div>

      {open ? (
        <div
          className="mt-3 grid grid-cols-1 gap-3 rounded-lg border p-3 sm:grid-cols-2 xl:grid-cols-4"
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
          <QboScopeField projet={projet} onPatch={onPatch} />
          <div className="sm:col-span-2 xl:col-span-3">
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

// ─── Choix + statut de la connexion QuickBooks du projet ───────

function QboScopeField({
  projet,
  onPatch
}: {
  projet: Projet;
  onPatch: (p: Record<string, unknown>) => Promise<void>;
}) {
  const incScope = `inc:${projet.entreprise_id}`;
  const scope = projet.qbo_scope || "";
  const [status, setStatus] = useState<{
    connected: boolean;
    company_name: string | null;
  } | null>(null);
  const [connecting, setConnecting] = useState(false);

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
        /* le statut restera inconnu */
      }
    })();
    return () => {
      dead = true;
    };
  }, [scope]);

  async function connecter() {
    setConnecting(true);
    try {
      const r = await authedFetch(
        `/api/v1/qbo/connect?scope=${encodeURIComponent(scope)}`
      );
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const d = (await r.json()) as { auth_url: string };
      // Intuit demande quelle compagnie autoriser → choisir le fichier
      // QuickBooks de CETTE INC. Le retour ramène sur cette page.
      window.location.assign(d.auth_url);
    } catch {
      setConnecting(false);
    }
  }

  return (
    <div>
      <label className="label text-[10px] uppercase">
        Connexion QuickBooks
      </label>
      <select
        className="input"
        value={scope}
        onChange={(e) => void onPatch({ qbo_scope: e.target.value || null })}
      >
        <option value="">— aucune —</option>
        <option value={incScope}>
          QuickBooks de {projet.entreprise_nom} (propre à l&apos;INC)
        </option>
        {QBO_SCOPES.map((s) => (
          <option key={s.value} value={s.value}>
            {s.label}
          </option>
        ))}
      </select>
      {scope && status ? (
        status.connected ? (
          <p className="mt-1 text-[11px] text-emerald-400">
            ✓ Connecté{status.company_name ? ` — ${status.company_name}` : ""}
          </p>
        ) : (
          <div className="mt-1 flex flex-wrap items-center gap-2">
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
        )
      ) : null}
    </div>
  );
}

// ─── Section 1 : Budget vs QuickBooks ──────────────────────────

function BudgetSection({
  projet,
  qboDep,
  qboErr,
  qboLoading,
  onRefreshQbo,
  onChanged
}: {
  projet: Projet;
  qboDep: Record<number, number>;
  qboErr: string | null;
  qboLoading: boolean;
  onRefreshQbo: () => void;
  onChanged: () => void;
}) {
  const confirm = useConfirm();
  const [adding, setAdding] = useState(false);
  const [nNom, setNNom] = useState("");
  const [nMontant, setNMontant] = useState("");
  const [saving, setSaving] = useState(false);

  // Mapping des comptes QBO d'une ligne.
  const [mapLigne, setMapLigne] = useState<BudgetLigne | null>(null);

  async function addLigne(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!nNom.trim()) return;
    setSaving(true);
    try {
      const r = await authedFetch(
        `/api/v1/optimisation/projets/${projet.id}/budget-lignes`,
        {
          method: "POST",
          body: JSON.stringify({
            nom: nNom.trim(),
            budget_montant: Number(nMontant) || 0
          })
        }
      );
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      setNNom("");
      setNMontant("");
      setAdding(false);
      onChanged();
    } finally {
      setSaving(false);
    }
  }

  async function patchLigne(id: number, patch: Record<string, unknown>) {
    const r = await authedFetch(`/api/v1/optimisation/budget-lignes/${id}`, {
      method: "PATCH",
      body: JSON.stringify(patch)
    });
    if (r.ok) onChanged();
  }

  async function deleteLigne(l: BudgetLigne) {
    const ok = await confirm({
      title: `Supprimer l'enveloppe « ${l.nom} » ?`,
      description: "Le budget et son mapping QuickBooks seront retirés.",
      confirmLabel: "Supprimer",
      destructive: true
    });
    if (!ok) return;
    const r = await authedFetch(
      `/api/v1/optimisation/budget-lignes/${l.id}`,
      { method: "DELETE" }
    );
    if (r.ok || r.status === 204) onChanged();
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
      className="rounded-xl border p-4"
      style={{
        borderColor: "var(--qg-border)",
        backgroundColor: "var(--qg-card-bg)"
      }}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3
          className="text-sm font-semibold"
          style={{ color: "var(--qg-text)" }}
        >
          Budget &amp; dépensé (QuickBooks)
        </h3>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={onRefreshQbo}
            disabled={qboLoading}
            className="btn-outline-accent btn-sm disabled:opacity-50"
            title="Relit les dépenses réelles dans QuickBooks (lecture seule)"
          >
            {qboLoading ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <RefreshCw className="h-3.5 w-3.5" />
            )}
            Actualiser QuickBooks
          </button>
          <button
            type="button"
            onClick={() => setAdding((v) => !v)}
            className="btn-secondary btn-sm"
          >
            <Plus className="h-3.5 w-3.5" />
            Enveloppe
          </button>
        </div>
      </div>

      {qboErr ? (
        <p className="mt-2 rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs text-amber-300">
          {qboErr}
        </p>
      ) : null}

      {adding ? (
        <form
          onSubmit={addLigne}
          className="mt-3 flex flex-wrap items-end gap-2"
        >
          <div className="min-w-[180px] flex-1">
            <label className="label text-[10px] uppercase">Enveloppe</label>
            <input
              className="input"
              value={nNom}
              onChange={(e) => setNNom(e.target.value)}
              placeholder="ex. Frais professionnels"
              autoFocus
            />
          </div>
          <div className="w-36">
            <label className="label text-[10px] uppercase">Budget ($)</label>
            <input
              className="input"
              type="number"
              step="0.01"
              value={nMontant}
              onChange={(e) => setNMontant(e.target.value)}
              placeholder="25000"
            />
          </div>
          <button
            type="submit"
            disabled={saving || !nNom.trim()}
            className="btn-accent inline-flex items-center gap-1.5 text-sm disabled:opacity-50"
          >
            {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
            Ajouter
          </button>
        </form>
      ) : null}

      {projet.budget_lignes.length === 0 ? (
        <p className="mt-3 text-xs" style={{ color: "var(--qg-text-muted)" }}>
          Pose tes enveloppes de départ (Frais professionnels, Travaux,
          Négociation…), puis mappe chacune aux comptes correspondants de
          ton plan comptable QuickBooks — le dépensé réel se met à jour
          tout seul.
        </p>
      ) : (
        <div className="mt-3 overflow-x-auto">
          <table className="w-full min-w-[640px] text-sm">
            <thead>
              <tr
                className="text-left text-[10px] uppercase tracking-wider"
                style={{ color: "var(--qg-text-muted)" }}
              >
                <th className="pb-2 pr-2">Enveloppe</th>
                <th className="pb-2 pr-2">Budget</th>
                <th className="pb-2 pr-2">Dépensé (QBO)</th>
                <th className="pb-2 pr-2">Reste</th>
                <th className="pb-2 pr-2 w-[26%]">Avancement</th>
                <th className="pb-2" />
              </tr>
            </thead>
            <tbody>
              {projet.budget_lignes.map((l) => {
                const dep = qboDep[l.id] ?? null;
                const budget = Number(l.budget_montant) || 0;
                const reste = dep === null ? null : budget - dep;
                const pct =
                  budget > 0 && dep !== null
                    ? Math.min(100, Math.round((dep / budget) * 100))
                    : 0;
                const over = reste !== null && reste < 0;
                const comptes = parseAccounts(l.qbo_accounts_json);
                return (
                  <tr
                    key={l.id}
                    className="border-t"
                    style={{ borderColor: "var(--qg-border-soft)" }}
                  >
                    <td className="py-2 pr-2">
                      <span
                        className="font-medium"
                        style={{ color: "var(--qg-text)" }}
                      >
                        {l.nom}
                      </span>
                      <button
                        type="button"
                        onClick={() => setMapLigne(l)}
                        className="ml-2 inline-flex items-center gap-1 text-[10px] text-accent-500 hover:underline"
                        title="Choisir les comptes QuickBooks comptés dans cette enveloppe"
                      >
                        <Pencil className="h-2.5 w-2.5" />
                        {comptes.length > 0
                          ? `${comptes.length} compte${comptes.length > 1 ? "s" : ""} QBO`
                          : "Mapper QBO"}
                      </button>
                    </td>
                    <td className="py-2 pr-2">
                      <input
                        className="input h-8 w-28 text-[13px]"
                        type="number"
                        step="0.01"
                        defaultValue={budget}
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
                      className={`py-2 pr-2 font-semibold tabular-nums ${
                        over ? "text-rose-400" : "text-emerald-400"
                      }`}
                    >
                      {reste === null ? "—" : fmtMoney(reste)}
                    </td>
                    <td className="py-2 pr-2">
                      <div
                        className="h-2 w-full overflow-hidden rounded-full"
                        style={{ backgroundColor: "var(--qg-border-soft)" }}
                      >
                        <div
                          className={`h-full rounded-full ${
                            over
                              ? "bg-rose-500"
                              : pct >= 85
                                ? "bg-amber-500"
                                : "bg-emerald-500"
                          }`}
                          style={{ width: `${over ? 100 : pct}%` }}
                        />
                      </div>
                    </td>
                    <td className="py-2 text-right">
                      <button
                        type="button"
                        onClick={() => void deleteLigne(l)}
                        className="text-rose-400/70 hover:text-rose-400"
                        title="Supprimer l'enveloppe"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
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
                  className={`py-2 pr-2 tabular-nums ${
                    totalBudget - totalDepense < 0
                      ? "text-rose-400"
                      : "text-emerald-400"
                  }`}
                >
                  {fmtMoney(totalBudget - totalDepense)}
                </td>
                <td colSpan={2} />
              </tr>
            </tbody>
          </table>
        </div>
      )}

      {mapLigne ? (
        <MapComptesModal
          projet={projet}
          ligne={mapLigne}
          onClose={() => setMapLigne(null)}
          onSaved={() => {
            setMapLigne(null);
            onChanged();
          }}
        />
      ) : null}
    </section>
  );
}

// ─── Modal mapping comptes QBO ─────────────────────────────────

function MapComptesModal({
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
  const [sel, setSel] = useState<Map<string, string>>(
    () =>
      new Map(parseAccounts(ligne.qbo_accounts_json).map((a) => [a.id, a.name]))
  );
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    void (async () => {
      if (!projet.qbo_scope) {
        setErr(
          "Choisis d'abord la connexion QuickBooks du projet (Réglages)."
        );
        setLoading(false);
        return;
      }
      try {
        const r = await authedFetch(
          `/api/v1/optimisation/qbo-comptes?scope=${encodeURIComponent(projet.qbo_scope)}`
        );
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const d = (await r.json()) as {
          comptes: QboCompte[];
          erreur: string | null;
        };
        if (d.erreur) setErr(d.erreur);
        setComptes(d.comptes || []);
      } catch (e) {
        setErr(`Plan comptable illisible : ${(e as Error).message}`);
      } finally {
        setLoading(false);
      }
    })();
  }, [projet.qbo_scope]);

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
          body: JSON.stringify({ qbo_accounts_json: JSON.stringify(arr) })
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
          Comptes QuickBooks — « {ligne.nom} »
        </h3>
        <p className="mt-1 text-[11px]" style={{ color: "var(--qg-text-muted)" }}>
          Coche les comptes du plan comptable dont les dépenses comptent
          dans cette enveloppe.
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
            <div className="mt-2 flex-1 space-y-0.5 overflow-y-auto pr-1">
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

  function saveObjectifs(next: ObjectifLibre[]) {
    void onPatch({ objectifs_json: JSON.stringify(next) });
  }

  const revObj = Number(projet.objectif_revenus_mensuels) || 0;
  const revAct = projet.revenus_actuels_mensuels || 0;
  const revPct = revObj > 0 ? Math.min(100, Math.round((revAct / revObj) * 100)) : 0;
  const depObj = Number(projet.objectif_depenses_mensuelles) || 0;
  const depAct = projet.depenses_actuelles_mensuelles || 0;

  return (
    <section
      className="rounded-xl border p-4"
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

      <div className="mt-3 grid grid-cols-1 gap-3 xl:grid-cols-2">
        {/* Revenus */}
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
              / {revObj ? fmtMoney(revObj) : "—"} (baux actifs)
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
              / {depObj ? fmtMoney(depObj) : "—"} (fiche immeuble)
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
      </div>

      {/* Objectifs libres */}
      <div className="mt-3">
        {objectifs.length > 0 ? (
          <ul className="space-y-1.5">
            {objectifs.map((o, i) => {
              const pct =
                o.cible > 0
                  ? Math.min(100, Math.round(((o.actuel || 0) / o.cible) * 100))
                  : 0;
              return (
                <li
                  key={i}
                  className="flex flex-wrap items-center gap-2 rounded-lg border px-2.5 py-1.5 text-xs"
                  style={{
                    borderColor: "var(--qg-border-soft)",
                    color: "var(--qg-text)"
                  }}
                >
                  <span className="min-w-[140px] flex-1 font-medium">
                    {o.label}
                  </span>
                  <span
                    className="flex items-center gap-1 text-[11px]"
                    style={{ color: "var(--qg-text-muted)" }}
                  >
                    Rendu à
                    <input
                      className="input h-7 w-24 text-right text-[12px]"
                      type="number"
                      step="0.01"
                      defaultValue={o.actuel || ""}
                      onBlur={(e) => {
                        const next = [...objectifs];
                        next[i] = {
                          ...o,
                          actuel: Number(e.target.value) || 0
                        };
                        saveObjectifs(next);
                      }}
                    />
                    / {fmtMoney(o.cible)}
                  </span>
                  <span className="w-10 text-right tabular-nums">{pct} %</span>
                  <button
                    type="button"
                    onClick={() =>
                      saveObjectifs(objectifs.filter((_, j) => j !== i))
                    }
                    className="text-rose-400/70 hover:text-rose-400"
                  >
                    <Trash2 className="h-3 w-3" />
                  </button>
                </li>
              );
            })}
          </ul>
        ) : null}
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (!nLabel.trim()) return;
            saveObjectifs([
              ...objectifs,
              { label: nLabel.trim(), cible: Number(nCible) || 0, actuel: 0 }
            ]);
            setNLabel("");
            setNCible("");
          }}
          className="mt-2 flex flex-wrap items-center gap-2"
        >
          <input
            className="input h-8 w-52 text-[12px]"
            placeholder="Autre objectif (ex. valeur visée)"
            value={nLabel}
            onChange={(e) => setNLabel(e.target.value)}
          />
          <input
            className="input h-8 w-28 text-[12px]"
            type="number"
            step="0.01"
            placeholder="Cible $"
            value={nCible}
            onChange={(e) => setNCible(e.target.value)}
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
      </div>
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
  const [importing, setImporting] = useState(false);
  const [openId, setOpenId] = useState<number | null>(null);
  const [addOpen, setAddOpen] = useState(false);
  const [aNom, setANom] = useState("");
  const [aLog, setALog] = useState("");

  async function importer() {
    setImporting(true);
    try {
      const r = await authedFetch(
        `/api/v1/optimisation/projets/${projet.id}/importer-locataires`,
        { method: "POST" }
      );
      if (r.ok) onChanged();
    } finally {
      setImporting(false);
    }
  }

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

  async function addNego(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!aNom.trim()) return;
    const r = await authedFetch(
      `/api/v1/optimisation/projets/${projet.id}/negos`,
      {
        method: "POST",
        body: JSON.stringify({
          nom_locataire: aNom.trim(),
          logement_label: aLog.trim() || null
        })
      }
    );
    if (r.ok) {
      setANom("");
      setALog("");
      setAddOpen(false);
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
          className="flex items-center gap-1.5 text-sm font-semibold"
          style={{ color: "var(--qg-text)" }}
        >
          <Users className="h-4 w-4 text-accent-500" />
          Négociations locataires
          <span
            className="text-xs font-normal"
            style={{ color: "var(--qg-text-muted)" }}
          >
            ({projet.negos.length})
          </span>
        </h3>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => void importer()}
            disabled={importing}
            className="btn-outline-accent btn-sm disabled:opacity-50"
            title="Ajoute les locataires à bail actif de l'immeuble qui ne sont pas encore suivis"
          >
            {importing ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <RefreshCw className="h-3.5 w-3.5" />
            )}
            Importer les locataires
          </button>
          <button
            type="button"
            onClick={() => setAddOpen((v) => !v)}
            className="btn-secondary btn-sm"
          >
            <Plus className="h-3.5 w-3.5" />
            Ajouter
          </button>
        </div>
      </div>

      {addOpen ? (
        <form onSubmit={addNego} className="mt-3 flex flex-wrap items-end gap-2">
          <div className="min-w-[180px] flex-1">
            <label className="label text-[10px] uppercase">Locataire</label>
            <input
              className="input"
              value={aNom}
              onChange={(e) => setANom(e.target.value)}
              autoFocus
            />
          </div>
          <div className="w-28">
            <label className="label text-[10px] uppercase">Logement</label>
            <input
              className="input"
              value={aLog}
              onChange={(e) => setALog(e.target.value)}
              placeholder="ex. 101"
            />
          </div>
          <button
            type="submit"
            disabled={!aNom.trim()}
            className="btn-accent text-sm disabled:opacity-50"
          >
            Ajouter
          </button>
        </form>
      ) : null}

      {projet.negos.length === 0 ? (
        <p className="mt-3 text-xs" style={{ color: "var(--qg-text-muted)" }}>
          Aucun locataire suivi. « Importer les locataires » récupère ceux
          à bail actif sur l&apos;immeuble.
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
                  {n.montant_entente ? (
                    <span className="text-[11px] tabular-nums text-amber-300">
                      entente {fmtMoney(n.montant_entente)}
                    </span>
                  ) : null}
                  {n.date_cible ? (
                    <span
                      className="text-[11px]"
                      style={{ color: "var(--qg-text-muted)" }}
                    >
                      {n.date_cible}
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
                      <div className="sm:col-span-2 xl:col-span-4">
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
                          const input = (
                            e.currentTarget.elements.namedItem(
                              "ev"
                            ) as HTMLInputElement
                          );
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
    </section>
  );
}
