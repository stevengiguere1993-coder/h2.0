"use client";

/**
 * Pipeline « Locations » (relocation / vacances) — KANBAN partagé :
 * - page /immobilier/locations (tous les immeubles, filtre)
 * - onglet « Locations » de la fiche immeuble (prop immeubleId)
 *
 * Colonnes = étapes de la relocation. Une carte se déplace par drag &
 * drop (ou via le sélecteur de statut dans sa fiche). Clic sur une
 * carte → fiche complète : annonces, visites & candidats (avec ENQUÊTES
 * de prélocation), dépôt du locataire sortant, notes, et conversion du
 * candidat retenu en LOCATAIRE + BAIL préremplis (avec confirmation).
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Check,
  ChevronDown,
  ChevronRight,
  ExternalLink,
  FileSignature,
  KeyRound,
  Loader2,
  Megaphone,
  Plus,
  ShieldCheck,
  Star,
  Timer,
  Trash2,
  Users,
  X
} from "lucide-react";

import { Link } from "@/i18n/navigation";
import { authedFetch } from "@/lib/auth";
import {
  BailSignature,
  TalFormDropdown
} from "@/components/immobilier/tal-avis";

type Annonce = {
  id: number;
  dossier_id: number;
  plateforme: string;
  url: string | null;
  publiee_le: string | null;
  active: boolean;
};

type Visite = {
  id: number;
  dossier_id: number;
  quand: string | null;
  candidat_nom: string;
  candidat_contact: string | null; // legacy (tél/courriel mélangés)
  candidat_email: string | null;
  candidat_phone: string | null;
  statut: string; // planifiee | faite | absent | annulee
  interesse: boolean | null;
  notes: string | null;
  enquete_credit: boolean | null;
  enquete_references: boolean | null;
  enquete_emploi: boolean | null;
  enquete_notes: string | null;
  retenu: boolean;
};

type Dossier = {
  id: number;
  logement_id: number;
  logement_numero: string;
  immeuble_id: number;
  immeuble_name: string;
  bail_id: number | null;
  locataire_sortant: string | null;
  statut: string;
  date_depart: string | null;
  loyer_demande: number | null;
  loyer_ancien: number | null;
  reloue_le: string | null;
  notes: string | null;
  depot_sortant: number | null;
  depot_sortant_rendu_le: string | null;
  nouveau_bail_id: number | null;
  annonces: Annonce[];
  visites: Visite[];
};

type Overview = {
  rows: Dossier[];
  nb_actifs: number;
  nb_visites_a_venir: number;
  nb_reloues_90j: number;
  jours_vacants_moyens: number | null;
};

const COLUMNS: Array<{ id: string; label: string; dot: string }> = [
  { id: "avis_recu", label: "Départ confirmé", dot: "bg-amber-400" },
  { id: "annonce_publiee", label: "Annonce publiée", dot: "bg-sky-400" },
  { id: "visites", label: "Visite prévue", dot: "bg-violet-400" },
  { id: "candidat_retenu", label: "Candidat retenu", dot: "bg-blue-400" },
  { id: "reloue", label: "Reloué", dot: "bg-emerald-400" }
];

const STATUTS_ACTIFS = [
  "avis_recu",
  "annonce_publiee",
  "visites",
  "candidat_retenu"
];

const STATUT_LABEL: Record<string, string> = Object.fromEntries(
  COLUMNS.map((c) => [c.id, c.label])
);
STATUT_LABEL.annule = "Annulé";

const VISITE_STATUTS: Array<{ id: string; label: string }> = [
  { id: "planifiee", label: "Planifiée" },
  { id: "faite", label: "Faite" },
  { id: "absent", label: "Absent" },
  { id: "annulee", label: "Annulée" }
];

function money(n: number | null | undefined): string {
  if (n == null) return "—";
  return n.toLocaleString("fr-CA", {
    style: "currency",
    currency: "CAD",
    maximumFractionDigits: 0
  });
}

function fmtDate(d: string | null | undefined): string {
  if (!d) return "—";
  return d.slice(0, 10);
}

function fmtDateTime(d: string | null | undefined): string {
  if (!d) return "À planifier";
  return new Date(d).toLocaleString("fr-CA", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit"
  });
}

function addMonthsIso(iso: string, months: number): string {
  const d = new Date(`${iso}T00:00:00`);
  d.setMonth(d.getMonth() + months);
  d.setDate(d.getDate() - 1);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

const INPUT_CLS =
  "rounded-md border border-brand-800 bg-brand-950 px-2 py-1.5 text-xs text-white outline-none focus:border-accent-500";

export function LocationsBoard({
  immeubleId,
  entrepriseId
}: {
  immeubleId?: number;
  entrepriseId?: number | null;
}) {
  const [data, setData] = useState<Overview | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [openId, setOpenId] = useState<number | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [showHistorique, setShowHistorique] = useState(false);
  const [immeubleFilter, setImmeubleFilter] = useState<number | "all">("all");
  const [dragOverCol, setDragOverCol] = useState<string | null>(null);

  const load = useCallback(async () => {
    setErr(null);
    try {
      const params = new URLSearchParams();
      if (immeubleId != null) params.set("immeuble_id", String(immeubleId));
      else if (entrepriseId != null)
        params.set("entreprise_id", String(entrepriseId));
      const r = await authedFetch(
        `/api/v1/immobilier/locations/overview?${params.toString()}`
      );
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      setData((await r.json()) as Overview);
    } catch (e) {
      setErr((e as Error).message);
    }
  }, [immeubleId, entrepriseId]);

  useEffect(() => {
    void load();
  }, [load]);

  async function patchDossier(
    id: number,
    body: Record<string, unknown>
  ): Promise<boolean> {
    setErr(null);
    const r = await authedFetch(`/api/v1/immobilier/locations/${id}`, {
      method: "PATCH",
      body: JSON.stringify(body)
    });
    if (!r.ok) {
      const t = await r.text();
      setErr(t.slice(0, 200) || `HTTP ${r.status}`);
      return false;
    }
    await load();
    return true;
  }

  const immeubles = useMemo(() => {
    const m = new Map<number, string>();
    for (const r of data?.rows || []) m.set(r.immeuble_id, r.immeuble_name);
    return [...m.entries()]
      .map(([id, name]) => ({ id, name }))
      .sort((a, b) => a.name.localeCompare(b.name, "fr"));
  }, [data]);

  const rows = useMemo(() => {
    let list = data?.rows || [];
    if (immeubleId == null && immeubleFilter !== "all") {
      list = list.filter((r) => r.immeuble_id === immeubleFilter);
    }
    return list;
  }, [data, immeubleFilter, immeubleId]);

  const byColumn = useMemo(() => {
    const map = Object.fromEntries(
      COLUMNS.map((c) => [c.id, [] as Dossier[]])
    );
    for (const r of rows) {
      if (map[r.statut]) map[r.statut].push(r);
    }
    return map;
  }, [rows]);

  const annules = rows.filter((r) => r.statut === "annule");
  const selected = openId != null ? rows.find((r) => r.id === openId) : null;

  return (
    <div className="space-y-4">
      {/* KPIs */}
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <KpiTile
          icon={<KeyRound className="h-4 w-4" />}
          label="À relouer"
          value={String(data?.nb_actifs ?? "…")}
          cls="border-amber-500/30 bg-amber-500/5 text-amber-200"
        />
        <KpiTile
          icon={<Users className="h-4 w-4" />}
          label="Visites à venir"
          value={String(data?.nb_visites_a_venir ?? "…")}
          cls="border-violet-500/30 bg-violet-500/5 text-violet-200"
        />
        <KpiTile
          icon={<Timer className="h-4 w-4" />}
          label="Jours vacants (moy.)"
          value={
            data == null
              ? "…"
              : data.jours_vacants_moyens != null
                ? String(data.jours_vacants_moyens)
                : "—"
          }
          cls="border-sky-500/30 bg-sky-500/5 text-sky-200"
        />
        <KpiTile
          icon={<Check className="h-4 w-4" />}
          label="Reloués (90 j)"
          value={String(data?.nb_reloues_90j ?? "…")}
          cls="border-emerald-500/30 bg-emerald-500/5 text-emerald-200"
        />
      </div>

      {/* Barre d'actions */}
      <div className="flex flex-wrap items-center gap-2">
        {immeubleId == null ? (
          <select
            value={immeubleFilter === "all" ? "all" : String(immeubleFilter)}
            onChange={(e) =>
              setImmeubleFilter(
                e.target.value === "all" ? "all" : Number(e.target.value)
              )
            }
            className="input w-auto max-w-[240px] text-sm"
          >
            <option value="all">Tous les immeubles</option>
            {immeubles.map((i) => (
              <option key={i.id} value={i.id}>
                {i.name}
              </option>
            ))}
          </select>
        ) : null}
        <button
          type="button"
          onClick={() => setShowCreate(true)}
          className="btn-outline-accent btn-sm ml-auto"
        >
          <Plus className="h-3.5 w-3.5" /> Nouvelle relocation
        </button>
      </div>

      {err ? (
        <p className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">
          {err}
        </p>
      ) : null}

      {/* Kanban */}
      {data === null ? (
        <div className="flex items-center gap-2 py-8 text-xs text-white/50">
          <Loader2 className="h-3.5 w-3.5 animate-spin" /> Chargement…
        </div>
      ) : (
        <div className="flex gap-4 overflow-x-auto pb-4">
          {COLUMNS.map((col) => {
            const cards = byColumn[col.id] || [];
            return (
              <div
                key={col.id}
                onDragOver={(e) => {
                  e.preventDefault();
                  setDragOverCol(col.id);
                }}
                onDragLeave={() =>
                  setDragOverCol((c) => (c === col.id ? null : c))
                }
                onDrop={(e) => {
                  e.preventDefault();
                  setDragOverCol(null);
                  const id = Number(e.dataTransfer.getData("text/plain"));
                  if (!Number.isFinite(id) || id <= 0) return;
                  const d = rows.find((r) => r.id === id);
                  if (d && d.statut !== col.id)
                    void patchDossier(id, { statut: col.id });
                }}
                className={`flex w-72 min-w-[288px] flex-shrink-0 flex-col rounded-xl border bg-brand-900/60 transition ${
                  dragOverCol === col.id
                    ? "border-accent-500"
                    : "border-brand-800"
                }`}
              >
                <div className="flex items-center justify-between border-b border-brand-800 px-4 py-3">
                  <div className="flex items-center gap-2">
                    <span className={`h-2 w-2 rounded-full ${col.dot}`} />
                    <h3 className="text-sm font-semibold text-white">
                      {col.label}
                    </h3>
                  </div>
                  <span className="badge badge-neutral">{cards.length}</span>
                </div>
                <div className="flex-1 space-y-3 p-3">
                  {cards.length === 0 ? (
                    <p className="py-6 text-center text-xs text-white/40">—</p>
                  ) : (
                    cards.map((d) => (
                      <DossierCard
                        key={d.id}
                        d={d}
                        showImmeuble={immeubleId == null}
                        onOpen={() => setOpenId(d.id)}
                      />
                    ))
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Annulés (repliés) */}
      {annules.length > 0 ? (
        <div>
          <button
            type="button"
            onClick={() => setShowHistorique((v) => !v)}
            className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider text-white/40 hover:text-white/70"
          >
            {showHistorique ? (
              <ChevronDown className="h-3.5 w-3.5" />
            ) : (
              <ChevronRight className="h-3.5 w-3.5" />
            )}
            Annulés ({annules.length})
          </button>
          {showHistorique ? (
            <div className="mt-2 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
              {annules.map((d) => (
                <DossierCard
                  key={d.id}
                  d={d}
                  showImmeuble={immeubleId == null}
                  onOpen={() => setOpenId(d.id)}
                />
              ))}
            </div>
          ) : null}
        </div>
      ) : null}

      {selected ? (
        <DossierModal
          d={selected}
          onClose={() => setOpenId(null)}
          onPatch={(body) => patchDossier(selected.id, body)}
          onMutated={() => void load()}
          onError={setErr}
          onDeleted={() => {
            setOpenId(null);
            void load();
          }}
        />
      ) : null}

      {showCreate ? (
        <CreateDossierModal
          immeubleId={immeubleId}
          onClose={() => setShowCreate(false)}
          onSaved={() => {
            setShowCreate(false);
            void load();
          }}
        />
      ) : null}
    </div>
  );
}

function KpiTile({
  icon,
  label,
  value,
  cls
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  cls: string;
}) {
  return (
    <div className={`rounded-2xl border p-3.5 ${cls}`}>
      <div className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wider opacity-80">
        {icon} {label}
      </div>
      <div className="mt-0.5 text-2xl font-bold">{value}</div>
    </div>
  );
}

// ─── Carte kanban ───────────────────────────────────────────────────────

function DossierCard({
  d,
  showImmeuble,
  onOpen
}: {
  d: Dossier;
  showImmeuble: boolean;
  onOpen: () => void;
}) {
  const retenu = d.visites.find((v) => v.retenu);
  const prochaine = d.visites.find(
    (v) => v.statut === "planifiee" && v.quand
  );
  const annoncesActives = d.annonces.filter((a) => a.active).length;
  const deltaLoyer =
    d.loyer_demande != null && d.loyer_ancien != null && d.loyer_ancien > 0
      ? ((d.loyer_demande - d.loyer_ancien) / d.loyer_ancien) * 100
      : null;

  return (
    <button
      type="button"
      draggable
      onDragStart={(e) =>
        e.dataTransfer.setData("text/plain", String(d.id))
      }
      onClick={onOpen}
      className="block w-full cursor-grab rounded-lg border border-brand-800 bg-brand-950 p-3 text-left transition hover:border-accent-500 active:cursor-grabbing"
    >
      <p className="truncate text-sm font-semibold text-white">
        Logement {d.logement_numero}
      </p>
      {showImmeuble ? (
        <p className="mt-0.5 truncate text-xs text-white/60">
          {d.immeuble_name}
        </p>
      ) : null}
      <p className="mt-1 text-xs text-white/55">
        {d.statut === "reloue"
          ? `Reloué le ${fmtDate(d.reloue_le)}`
          : `Départ : ${fmtDate(d.date_depart)}`}
        {d.locataire_sortant ? ` · ${d.locataire_sortant}` : ""}
      </p>
      <p className="mt-1 font-mono text-xs text-white/80">
        {money(d.loyer_demande)}
        {deltaLoyer != null && Math.abs(deltaLoyer) >= 0.5 ? (
          <span
            className={deltaLoyer > 0 ? "text-emerald-300" : "text-rose-300"}
          >
            {" "}
            ({deltaLoyer > 0 ? "+" : ""}
            {deltaLoyer.toFixed(0)} %)
          </span>
        ) : null}
      </p>
      <div className="mt-1.5 flex flex-wrap items-center gap-2 text-[11px] text-white/50">
        <span title="Annonces actives">
          <Megaphone className="mr-0.5 inline h-3 w-3" />
          {annoncesActives}
        </span>
        <span title="Visites / candidats">
          <Users className="mr-0.5 inline h-3 w-3" />
          {d.visites.length}
        </span>
        {retenu ? (
          <span className="badge badge-blue">
            <Star className="mr-0.5 inline h-2.5 w-2.5" />
            {retenu.candidat_nom}
          </span>
        ) : prochaine ? (
          <span className="badge badge-violet">
            {fmtDateTime(prochaine.quand)}
          </span>
        ) : null}
      </div>
    </button>
  );
}

// ─── Fiche complète (modal) ─────────────────────────────────────────────

function DossierModal({
  d,
  onClose,
  onPatch,
  onMutated,
  onError,
  onDeleted
}: {
  d: Dossier;
  onClose: () => void;
  onPatch: (body: Record<string, unknown>) => Promise<boolean>;
  onMutated: () => void;
  onError: (msg: string) => void;
  onDeleted: () => void;
}) {
  const [notesDraft, setNotesDraft] = useState(d.notes || "");
  const [savingNotes, setSavingNotes] = useState(false);
  const [busy, setBusy] = useState(false);
  const [showConvert, setShowConvert] = useState(false);

  const [annPlateforme, setAnnPlateforme] = useState("Marketplace");
  const [annUrl, setAnnUrl] = useState("");
  const [visNom, setVisNom] = useState("");
  const [visEmail, setVisEmail] = useState("");
  const [visPhone, setVisPhone] = useState("");
  const [visQuand, setVisQuand] = useState("");

  const retenu = d.visites.find((v) => v.retenu) || null;

  async function api(
    path: string,
    method: string,
    body?: Record<string, unknown>
  ): Promise<boolean> {
    setBusy(true);
    try {
      const r = await authedFetch(`/api/v1/immobilier/locations${path}`, {
        method,
        ...(body ? { body: JSON.stringify(body) } : {})
      });
      if (!r.ok) {
        const t = await r.text();
        onError(t.slice(0, 200) || `HTTP ${r.status}`);
        return false;
      }
      onMutated();
      return true;
    } finally {
      setBusy(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4"
      onClick={onClose}
    >
      <div
        className="max-h-[90vh] w-full max-w-3xl overflow-y-auto rounded-2xl border border-brand-800 bg-brand-950 p-6"
        onClick={(e) => e.stopPropagation()}
      >
        {/* En-tête */}
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-accent-500/15 text-accent-500">
                <KeyRound className="h-4.5 w-4.5" />
              </span>
              <h2 className="text-lg font-bold text-white">
                Logement {d.logement_numero}
              </h2>
              <span
                className={`badge ${
                  d.statut === "reloue"
                    ? "badge-emerald"
                    : d.statut === "annule"
                      ? "badge-neutral"
                      : "badge-amber"
                }`}
              >
                {STATUT_LABEL[d.statut] ?? d.statut}
              </span>
            </div>
            <p className="mt-1 text-xs text-white/55">
              {d.immeuble_name}
              {d.locataire_sortant ? ` · ${d.locataire_sortant} quitte` : ""}
              {d.loyer_ancien != null
                ? ` · ancien loyer ${money(d.loyer_ancien)}`
                : ""}
            </p>
          </div>
          <span className="flex items-center gap-2">
            <Link
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
              href={`/immobilier/logements/${d.logement_id}` as any}
              className="text-xs text-accent-500 hover:underline"
            >
              Fiche du logement →
            </Link>
            <button
              type="button"
              onClick={onClose}
              className="btn-ghost btn-xs"
            >
              <X className="h-4 w-4" />
            </button>
          </span>
        </div>

        {/* Stepper de statut — cliquer une étape déplace le dossier. */}
        <div className="mt-4 flex items-center gap-0 overflow-x-auto rounded-xl border border-brand-800 bg-brand-900/60 p-1.5">
          {COLUMNS.map((col, i) => {
            const activeIdx = COLUMNS.findIndex((c) => c.id === d.statut);
            const isActive = d.statut === col.id;
            const isPast = activeIdx >= 0 && i < activeIdx;
            return (
              <div key={col.id} className="flex flex-1 items-center">
                {i > 0 ? (
                  <span
                    className={`h-px w-3 flex-shrink-0 sm:w-5 ${
                      isPast || isActive ? "bg-accent-500/60" : "bg-brand-800"
                    }`}
                  />
                ) : null}
                <button
                  type="button"
                  onClick={() =>
                    !isActive ? void onPatch({ statut: col.id }) : undefined
                  }
                  title={`Passer à « ${col.label} »`}
                  className={`flex min-w-0 flex-1 items-center justify-center gap-1.5 whitespace-nowrap rounded-lg px-2 py-1.5 text-[11px] font-semibold transition ${
                    isActive
                      ? "bg-accent-500/15 text-accent-500 ring-1 ring-inset ring-accent-500/40"
                      : isPast
                        ? "text-white/70 hover:bg-brand-800"
                        : "text-white/35 hover:bg-brand-800 hover:text-white/70"
                  }`}
                >
                  {isPast ? (
                    <Check className="h-3 w-3 text-accent-500/70" />
                  ) : (
                    <span
                      className={`h-1.5 w-1.5 flex-shrink-0 rounded-full ${col.dot} ${
                        isActive ? "" : "opacity-40"
                      }`}
                    />
                  )}
                  {col.label}
                </button>
              </div>
            );
          })}
        </div>

        {/* Champs clés */}
        <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-3">
          <label className="text-[11px] font-semibold text-white/60">
            Date de départ
            <input
              type="date"
              defaultValue={d.date_depart || ""}
              onBlur={(e) =>
                e.target.value !== (d.date_depart || "")
                  ? void onPatch({ date_depart: e.target.value || null })
                  : undefined
              }
              className={`${INPUT_CLS} mt-0.5 block w-full`}
            />
          </label>
          <label className="text-[11px] font-semibold text-white/60">
            Loyer demandé ($/mois)
            <input
              inputMode="decimal"
              defaultValue={
                d.loyer_demande != null ? String(d.loyer_demande) : ""
              }
              onBlur={(e) => {
                const v = e.target.value.trim();
                const n = v === "" ? null : Number(v);
                if (v !== "" && Number.isNaN(n)) return;
                if (n !== d.loyer_demande) void onPatch({ loyer_demande: n });
              }}
              className={`${INPUT_CLS} mt-0.5 block w-full`}
            />
          </label>
          {d.loyer_ancien != null ? (
            <div className="text-[11px] font-semibold text-white/60">
              Ancien loyer
              <div className="mt-0.5 rounded-md border border-brand-800/60 bg-brand-900/50 px-2 py-1.5 font-mono text-xs text-white/60">
                {money(d.loyer_ancien)}
                {d.loyer_demande != null && d.loyer_ancien > 0 ? (
                  <span
                    className={
                      d.loyer_demande >= d.loyer_ancien
                        ? "ml-1 text-emerald-300"
                        : "ml-1 text-rose-300"
                    }
                  >
                    (
                    {d.loyer_demande >= d.loyer_ancien ? "+" : ""}
                    {(
                      ((d.loyer_demande - d.loyer_ancien) / d.loyer_ancien) *
                      100
                    ).toFixed(0)}
                    &nbsp;%)
                  </span>
                ) : null}
              </div>
            </div>
          ) : null}
        </div>

        {/* Dépôt du locataire sortant (interconnexion Dépôts) */}
        {d.depot_sortant != null ? (
          <div className="mt-3 flex flex-wrap items-center gap-2 rounded-lg border border-violet-500/30 bg-violet-500/10 px-3 py-2 text-xs text-violet-200">
            <ShieldCheck className="h-3.5 w-3.5" />
            Dépôt de garantie du locataire sortant :{" "}
            <strong>{money(d.depot_sortant)}</strong>
            {d.depot_sortant_rendu_le ? (
              <span className="badge badge-emerald">
                Rendu le {fmtDate(d.depot_sortant_rendu_le)}
              </span>
            ) : (
              <span className="badge badge-amber">À rendre au départ</span>
            )}
            <Link
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
              href={"/immobilier/depots" as any}
              className="ml-auto text-violet-200 underline-offset-2 hover:underline"
            >
              Gérer dans Dépôts →
            </Link>
          </div>
        ) : null}

        {/* Conversion candidat retenu → locataire + bail */}
        {d.statut !== "reloue" && d.statut !== "annule" ? (
          <div className="mt-3 flex flex-wrap items-center gap-2 rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-xs text-emerald-200">
            <FileSignature className="h-3.5 w-3.5" />
            {retenu ? (
              <>
                Candidat retenu : <strong>{retenu.candidat_nom}</strong>
              </>
            ) : (
              <>Retiens un candidat (⭐ dans la liste) pour créer son bail.</>
            )}
            <button
              type="button"
              disabled={!retenu}
              onClick={() => setShowConvert(true)}
              className="ml-auto rounded-md border border-emerald-400/40 bg-emerald-500/15 px-2.5 py-1 font-semibold text-emerald-200 hover:bg-emerald-500/25 disabled:opacity-40"
            >
              Créer le locataire + bail
            </button>
          </div>
        ) : d.statut === "reloue" && d.nouveau_bail_id ? (
          <div className="mt-3 flex flex-wrap items-center gap-2 rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-xs text-emerald-200">
            <Check className="h-3.5 w-3.5" /> Reloué — bail créé.
            {/* Interconnexion (retour Phil) : générer la trousse/les avis
                et envoyer pour signature SANS quitter le dossier. */}
            <TalFormDropdown bailId={d.nouveau_bail_id} />
            <BailSignature bailId={d.nouveau_bail_id} />
            <Link
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
              href={
                `/immobilier/immeubles/${d.immeuble_id}?tab=baux&bail=${d.nouveau_bail_id}` as any
              }
              className="ml-auto underline-offset-2 hover:underline"
            >
              Voir le bail →
            </Link>
          </div>
        ) : null}

        <div className="mt-4 grid gap-4 lg:grid-cols-2">
          {/* Annonces */}
          <div className="rounded-xl border border-brand-800 bg-brand-900 p-3.5">
            <h4 className="mb-2 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider text-accent-500">
              <Megaphone className="h-3.5 w-3.5" /> Annonces
            </h4>
            {d.annonces.length === 0 ? (
              <p className="text-xs text-white/40">Aucune annonce consignée.</p>
            ) : (
              <ul className="space-y-1.5">
                {d.annonces.map((a) => (
                  <li
                    key={a.id}
                    className="flex items-center gap-2 text-xs text-white/75"
                  >
                    <span
                      className={`badge ${a.active ? "badge-sky" : "badge-neutral"}`}
                    >
                      {a.plateforme}
                    </span>
                    {a.url ? (
                      <a
                        href={a.url}
                        target="_blank"
                        rel="noreferrer"
                        className="inline-flex items-center gap-1 text-accent-500 hover:underline"
                      >
                        Voir <ExternalLink className="h-3 w-3" />
                      </a>
                    ) : null}
                    <span className="text-white/40">{fmtDate(a.publiee_le)}</span>
                    <span className="ml-auto flex items-center gap-1">
                      <button
                        type="button"
                        title={a.active ? "Marquer retirée" : "Réactiver"}
                        onClick={() =>
                          void api(`/annonces/${a.id}`, "PATCH", {
                            active: !a.active
                          })
                        }
                        className="rounded px-1.5 py-0.5 text-[10px] font-semibold text-white/50 hover:bg-brand-800 hover:text-white"
                      >
                        {a.active ? "Active" : "Retirée"}
                      </button>
                      <button
                        type="button"
                        onClick={() => void api(`/annonces/${a.id}`, "DELETE")}
                        className="rounded p-1 text-white/30 hover:text-rose-300"
                      >
                        <Trash2 className="h-3 w-3" />
                      </button>
                    </span>
                  </li>
                ))}
              </ul>
            )}
            <div className="mt-2 flex flex-wrap items-center gap-1.5">
              <select
                value={annPlateforme}
                onChange={(e) => setAnnPlateforme(e.target.value)}
                className={`${INPUT_CLS} w-auto`}
              >
                {["Marketplace", "Kijiji", "LesPAC", "Affiche", "Autre"].map(
                  (p) => (
                    <option key={p} value={p}>
                      {p}
                    </option>
                  )
                )}
              </select>
              <input
                value={annUrl}
                onChange={(e) => setAnnUrl(e.target.value)}
                placeholder="Lien (optionnel)"
                className={`${INPUT_CLS} min-w-0 flex-1`}
              />
              <button
                type="button"
                disabled={busy}
                onClick={async () => {
                  if (
                    await api(`/${d.id}/annonces`, "POST", {
                      plateforme: annPlateforme,
                      url: annUrl.trim() || null
                    })
                  )
                    setAnnUrl("");
                }}
                className="btn-secondary btn-sm disabled:opacity-50"
              >
                <Plus className="h-3.5 w-3.5" /> Ajouter
              </button>
            </div>
          </div>

          {/* Notes */}
          <div className="rounded-xl border border-brand-800 bg-brand-900 p-3.5">
            <h4 className="mb-2 text-xs font-semibold uppercase tracking-wider text-accent-500">
              Notes de suivi
            </h4>
            <textarea
              rows={5}
              value={notesDraft}
              onChange={(e) => setNotesDraft(e.target.value)}
              placeholder="État du logement, peinture à faire, candidat à relancer…"
              className="block w-full rounded-md border border-brand-800 bg-brand-950 px-3 py-2 text-xs text-white outline-none focus:border-accent-500"
            />
            <button
              type="button"
              disabled={savingNotes || notesDraft === (d.notes || "")}
              onClick={async () => {
                setSavingNotes(true);
                await onPatch({
                  notes: notesDraft.trim() ? notesDraft : null
                });
                setSavingNotes(false);
              }}
              className="btn-secondary btn-sm mt-1.5 disabled:opacity-40"
            >
              {savingNotes ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Check className="h-3.5 w-3.5" />
              )}
              Enregistrer
            </button>
          </div>
        </div>

        {/* Visites & candidats (avec enquêtes de prélocation) */}
        <div className="mt-4 rounded-xl border border-brand-800 bg-brand-900 p-3.5">
          <h4 className="mb-2 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider text-accent-500">
            <Users className="h-3.5 w-3.5" /> Visites &amp; candidats
          </h4>
          {d.visites.length === 0 ? (
            <p className="text-xs text-white/40">Aucune visite planifiée.</p>
          ) : (
            <ul className="space-y-2">
              {d.visites.map((v) => (
                <CandidatRow
                  key={v.id}
                  v={v}
                  onApi={api}
                />
              ))}
            </ul>
          )}
          <div className="mt-3 grid gap-1.5 border-t border-brand-800 pt-3 sm:grid-cols-2 lg:grid-cols-5">
            <input
              value={visNom}
              onChange={(e) => setVisNom(e.target.value)}
              placeholder="Nom du candidat"
              className={`${INPUT_CLS} lg:col-span-1`}
            />
            <input
              type="email"
              value={visEmail}
              onChange={(e) => setVisEmail(e.target.value)}
              placeholder="Courriel"
              className={INPUT_CLS}
            />
            <input
              value={visPhone}
              onChange={(e) => setVisPhone(e.target.value)}
              placeholder="Téléphone"
              className={INPUT_CLS}
            />
            <input
              type="datetime-local"
              value={visQuand}
              onChange={(e) => setVisQuand(e.target.value)}
              className={INPUT_CLS}
            />
            <button
              type="button"
              disabled={busy || !visNom.trim()}
              onClick={async () => {
                if (
                  await api(`/${d.id}/visites`, "POST", {
                    candidat_nom: visNom.trim(),
                    candidat_email: visEmail.trim() || null,
                    candidat_phone: visPhone.trim() || null,
                    quand: visQuand ? new Date(visQuand).toISOString() : null
                  })
                ) {
                  setVisNom("");
                  setVisEmail("");
                  setVisPhone("");
                  setVisQuand("");
                }
              }}
              className="btn-secondary btn-sm disabled:opacity-50"
            >
              <Plus className="h-3.5 w-3.5" /> Ajouter
            </button>
          </div>
        </div>

        {/* Pied de fiche : actions destructives discrètes */}
        <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-brand-800 pt-3">
          {d.statut !== "annule" && d.statut !== "reloue" ? (
            <button
              type="button"
              onClick={() => void onPatch({ statut: "annule" })}
              className="text-xs text-white/40 hover:text-white/70"
            >
              Annuler la relocation
            </button>
          ) : null}
          <button
            type="button"
            onClick={async () => {
              if (window.confirm("Supprimer ce dossier de relocation ?")) {
                if (await api(`/${d.id}`, "DELETE")) onDeleted();
              }
            }}
            className="inline-flex items-center gap-1 text-xs text-rose-300/60 hover:text-rose-300"
          >
            <Trash2 className="h-3 w-3" /> Supprimer le dossier
          </button>
          <button
            type="button"
            onClick={onClose}
            className="btn-secondary btn-sm ml-auto"
          >
            Fermer
          </button>
        </div>
      </div>

      {showConvert && retenu ? (
        <ConvertModal
          d={d}
          candidat={retenu}
          onClose={() => setShowConvert(false)}
          onDone={() => {
            setShowConvert(false);
            onMutated();
          }}
        />
      ) : null}
    </div>
  );
}

// ─── Ligne candidat (statut visite + enquêtes + retenir) ────────────────

function TriCheck({
  label,
  value,
  onCycle
}: {
  label: string;
  value: boolean | null;
  onCycle: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onCycle}
      title={`${label} : cliquer pour changer (— → OK → Refusé)`}
      className={`rounded px-1.5 py-0.5 text-[10px] font-semibold ${
        value === true
          ? "bg-emerald-500/15 text-emerald-300"
          : value === false
            ? "bg-rose-500/15 text-rose-300"
            : "bg-brand-800/60 text-white/40 hover:text-white/70"
      }`}
    >
      {label} {value === true ? "✓" : value === false ? "✗" : "·"}
    </button>
  );
}

function CandidatRow({
  v,
  onApi
}: {
  v: Visite;
  onApi: (
    path: string,
    method: string,
    body?: Record<string, unknown>
  ) => Promise<boolean>;
}) {
  const cycle = (cur: boolean | null) =>
    cur === null ? true : cur === true ? false : null;

  return (
    <li
      className={`rounded-lg border p-2.5 ${
        v.retenu
          ? "border-blue-400/40 bg-blue-500/10"
          : "border-brand-800 bg-brand-950/60"
      }`}
    >
      <div className="flex flex-wrap items-center gap-2 text-xs text-white/75">
        {v.retenu ? <Star className="h-3.5 w-3.5 text-blue-300" /> : null}
        <span className="font-medium text-white">{v.candidat_nom}</span>
        {v.candidat_email ? (
          <span className="text-white/45">{v.candidat_email}</span>
        ) : null}
        {v.candidat_phone ? (
          <span className="text-white/45">{v.candidat_phone}</span>
        ) : null}
        {!v.candidat_email && !v.candidat_phone && v.candidat_contact ? (
          <span className="text-white/45">{v.candidat_contact}</span>
        ) : null}
        <span className="text-white/40">{fmtDateTime(v.quand)}</span>
        <span className="ml-auto flex items-center gap-1">
          <select
            value={v.statut}
            onChange={(e) =>
              void onApi(`/visites/${v.id}`, "PATCH", {
                statut: e.target.value
              })
            }
            className={`${INPUT_CLS} w-auto py-0.5 text-[11px]`}
          >
            {VISITE_STATUTS.map((s) => (
              <option key={s.id} value={s.id}>
                {s.label}
              </option>
            ))}
          </select>
          <button
            type="button"
            onClick={() => void onApi(`/visites/${v.id}`, "DELETE")}
            className="rounded p-1 text-white/30 hover:text-rose-300"
          >
            <Trash2 className="h-3 w-3" />
          </button>
        </span>
      </div>
      {/* Prélocation : intérêt + enquêtes + retenir */}
      <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
        <button
          type="button"
          title="Le candidat est-il intéressé ?"
          onClick={() =>
            void onApi(`/visites/${v.id}`, "PATCH", {
              interesse: cycle(v.interesse)
            })
          }
          className={`rounded px-1.5 py-0.5 text-[10px] font-semibold ${
            v.interesse === true
              ? "bg-emerald-500/15 text-emerald-300"
              : v.interesse === false
                ? "bg-rose-500/15 text-rose-300"
                : "bg-brand-800/60 text-white/40 hover:text-white/70"
          }`}
        >
          Intéressé {v.interesse === true ? "✓" : v.interesse === false ? "✗" : "·"}
        </button>
        <span className="text-[10px] uppercase tracking-wider text-white/30">
          Enquêtes :
        </span>
        <TriCheck
          label="Crédit"
          value={v.enquete_credit}
          onCycle={() =>
            void onApi(`/visites/${v.id}`, "PATCH", {
              enquete_credit: cycle(v.enquete_credit)
            })
          }
        />
        <TriCheck
          label="Références"
          value={v.enquete_references}
          onCycle={() =>
            void onApi(`/visites/${v.id}`, "PATCH", {
              enquete_references: cycle(v.enquete_references)
            })
          }
        />
        <TriCheck
          label="Emploi"
          value={v.enquete_emploi}
          onCycle={() =>
            void onApi(`/visites/${v.id}`, "PATCH", {
              enquete_emploi: cycle(v.enquete_emploi)
            })
          }
        />
        <button
          type="button"
          title={
            v.retenu
              ? "Ne plus retenir ce candidat"
              : "Retenir ce candidat pour le logement (fait avancer le dossier)"
          }
          onClick={() =>
            void onApi(`/visites/${v.id}`, "PATCH", { retenu: !v.retenu })
          }
          className={`ml-auto rounded-md border px-2 py-0.5 text-[10px] font-semibold ${
            v.retenu
              ? "border-blue-400/40 bg-blue-500/15 text-blue-200"
              : "border-white/10 text-white/50 hover:bg-brand-800 hover:text-white"
          }`}
        >
          <Star className="mr-1 inline h-3 w-3" />
          {v.retenu ? "Retenu" : "Retenir"}
        </button>
      </div>
      {/* Notes du candidat + notes d'enquête */}
      <InlineNote
        label="Notes du candidat"
        placeholder="Impressions après la visite, besoins particuliers, à relancer…"
        value={v.notes}
        onSave={(txt) =>
          onApi(`/visites/${v.id}`, "PATCH", { notes: txt })
        }
      />
      <InlineNote
        label="Notes d'enquête"
        placeholder="Résultat de l'enquête de crédit, références du proprio précédent, emploi vérifié…"
        value={v.enquete_notes}
        onSave={(txt) =>
          onApi(`/visites/${v.id}`, "PATCH", { enquete_notes: txt })
        }
      />
    </li>
  );
}

function InlineNote({
  label,
  placeholder,
  value,
  onSave
}: {
  label: string;
  placeholder: string;
  value: string | null;
  onSave: (txt: string | null) => Promise<boolean>;
}) {
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState(value || "");
  if (!open) {
    return (
      <button
        type="button"
        onClick={() => {
          setDraft(value || "");
          setOpen(true);
        }}
        className="mt-1 block text-left text-[10px] text-white/35 hover:text-white/70"
      >
        {value
          ? `${label} : ${value.slice(0, 70)}${value.length > 70 ? "…" : ""}`
          : `+ ${label}`}
      </button>
    );
  }
  return (
    <div className="mt-1.5">
      <textarea
        rows={2}
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        placeholder={placeholder}
        className="block w-full rounded-md border border-brand-800 bg-brand-950 px-2 py-1.5 text-[11px] text-white outline-none focus:border-accent-500"
      />
      <div className="mt-1 flex gap-1.5">
        <button
          type="button"
          onClick={async () => {
            if (await onSave(draft.trim() ? draft : null)) setOpen(false);
          }}
          className="btn-secondary btn-xs"
        >
          <Check className="h-3 w-3" /> OK
        </button>
        <button
          type="button"
          onClick={() => setOpen(false)}
          className="btn-ghost btn-xs"
        >
          Annuler
        </button>
      </div>
    </div>
  );
}

// ─── Conversion candidat retenu → locataire + bail ──────────────────────

function ConvertModal({
  d,
  candidat,
  onClose,
  onDone
}: {
  d: Dossier;
  candidat: Visite;
  onClose: () => void;
  onDone: () => void;
}) {
  // Préremplissage : courriel + téléphone du candidat (champs distincts) ;
  // repli sur le vieux champ contact mélangé pour les données existantes.
  const contact = (candidat.candidat_contact || "").trim();
  const isEmail = contact.includes("@");
  const prefillEmail =
    (candidat.candidat_email || "").trim() || (isEmail ? contact : "");
  const prefillPhone =
    (candidat.candidat_phone || "").trim() || (isEmail ? "" : contact);
  const defaultDebut = (() => {
    if (d.date_depart) {
      const dt = new Date(`${d.date_depart}T00:00:00`);
      dt.setDate(dt.getDate() + 1);
      const pad = (n: number) => String(n).padStart(2, "0");
      return `${dt.getFullYear()}-${pad(dt.getMonth() + 1)}-${pad(dt.getDate())}`;
    }
    return new Date().toISOString().slice(0, 10);
  })();

  const [nom, setNom] = useState(candidat.candidat_nom);
  const [email, setEmail] = useState(prefillEmail);
  const [phone, setPhone] = useState(prefillPhone);
  const [debut, setDebut] = useState(defaultDebut);
  const [fin, setFin] = useState(addMonthsIso(defaultDebut, 12));
  const [loyer, setLoyer] = useState(
    d.loyer_demande != null ? String(d.loyer_demande) : ""
  );
  const [depot, setDepot] = useState("");
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [done, setDone] = useState<{
    locataire_id: number;
    bail_id: number;
    immeuble_id: number;
  } | null>(null);

  async function submit() {
    setSaving(true);
    setErr(null);
    try {
      const r = await authedFetch(
        `/api/v1/immobilier/locations/${d.id}/convertir`,
        {
          method: "POST",
          body: JSON.stringify({
            locataire_nom: nom.trim(),
            locataire_email: email.trim() || null,
            locataire_phone: phone.trim() || null,
            date_debut: debut,
            date_fin: fin,
            loyer_mensuel: Number(loyer),
            depot_garantie: depot.trim() ? Number(depot) : null
          })
        }
      );
      if (!r.ok) {
        const t = await r.text();
        throw new Error(t.slice(0, 240) || `HTTP ${r.status}`);
      }
      setDone(
        (await r.json()) as {
          locataire_id: number;
          bail_id: number;
          immeuble_id: number;
        }
      );
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-[60] flex items-start justify-center overflow-y-auto bg-black/70 p-4 backdrop-blur-sm"
      onClick={(e) => e.stopPropagation()}
    >
      <div className="my-8 w-full max-w-md rounded-2xl border border-brand-800 bg-brand-950 shadow-2xl">
        <div className="flex items-center justify-between border-b border-brand-800 px-5 py-3">
          <h2 className="text-sm font-bold uppercase tracking-wider text-emerald-300">
            Créer le locataire + bail
          </h2>
          <button type="button" onClick={onClose} className="btn-ghost btn-xs">
            <X className="h-4 w-4" />
          </button>
        </div>
        {done ? (
          <div className="space-y-3 p-5 text-sm text-white/80">
            <p className="flex items-center gap-2 font-semibold text-emerald-300">
              <Check className="h-4 w-4" /> Locataire et bail créés — dossier
              reloué.
            </p>
            <p className="text-xs text-white/55">
              Le bail est en statut « proposé » : envoie-le pour signature
              depuis Baux &amp; locataires (bouton de signature sur la ligne
              du bail).
            </p>
            <div className="flex flex-col gap-1.5 text-xs">
              <Link
                // eslint-disable-next-line @typescript-eslint/no-explicit-any
                href={`/immobilier/locataires/${done.locataire_id}` as any}
                className="text-accent-500 hover:underline"
              >
                Fiche du locataire →
              </Link>
              <Link
                // eslint-disable-next-line @typescript-eslint/no-explicit-any
                href={
                  `/immobilier/immeubles/${done.immeuble_id}?tab=baux&bail=${done.bail_id}` as any
                }
                className="text-accent-500 hover:underline"
              >
                Voir le bail (surligné) et l&apos;envoyer pour signature →
              </Link>
            </div>
            <div className="flex justify-end border-t border-brand-800 pt-3">
              <button
                type="button"
                onClick={onDone}
                className="btn-accent btn-sm"
              >
                Fermer
              </button>
            </div>
          </div>
        ) : (
          <div className="grid gap-3 p-5">
            <p className="rounded-lg border border-sky-400/30 bg-sky-500/10 px-3 py-2 text-xs text-sky-200">
              Tout est prérempli depuis le dossier — vérifie et ajuste avant
              de confirmer. Rien n&apos;est créé sans ton accord.
            </p>
            <label className="text-[11px] font-semibold text-white/60">
              Nom complet du locataire
              <input
                value={nom}
                onChange={(e) => setNom(e.target.value)}
                className={`${INPUT_CLS} mt-0.5 block w-full`}
              />
            </label>
            <div className="grid grid-cols-2 gap-3">
              <label className="text-[11px] font-semibold text-white/60">
                Courriel
                <input
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  className={`${INPUT_CLS} mt-0.5 block w-full`}
                />
              </label>
              <label className="text-[11px] font-semibold text-white/60">
                Téléphone
                <input
                  value={phone}
                  onChange={(e) => setPhone(e.target.value)}
                  className={`${INPUT_CLS} mt-0.5 block w-full`}
                />
              </label>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <label className="text-[11px] font-semibold text-white/60">
                Début du bail
                <input
                  type="date"
                  value={debut}
                  onChange={(e) => {
                    setDebut(e.target.value);
                    if (e.target.value)
                      setFin(addMonthsIso(e.target.value, 12));
                  }}
                  className={`${INPUT_CLS} mt-0.5 block w-full`}
                />
              </label>
              <label className="text-[11px] font-semibold text-white/60">
                Fin du bail
                <input
                  type="date"
                  value={fin}
                  onChange={(e) => setFin(e.target.value)}
                  className={`${INPUT_CLS} mt-0.5 block w-full`}
                />
              </label>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <label className="text-[11px] font-semibold text-white/60">
                Loyer mensuel ($)
                <input
                  inputMode="decimal"
                  value={loyer}
                  onChange={(e) => setLoyer(e.target.value)}
                  className={`${INPUT_CLS} mt-0.5 block w-full`}
                />
              </label>
              <label className="text-[11px] font-semibold text-white/60">
                Dépôt de garantie ($)
                <input
                  inputMode="decimal"
                  value={depot}
                  onChange={(e) => setDepot(e.target.value)}
                  placeholder="Optionnel"
                  className={`${INPUT_CLS} mt-0.5 block w-full`}
                />
              </label>
            </div>
            {err ? (
              <p className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">
                {err}
              </p>
            ) : null}
            <div className="flex justify-end gap-2 border-t border-brand-800 pt-3">
              <button
                type="button"
                onClick={onClose}
                className="btn-secondary btn-sm"
              >
                Annuler
              </button>
              <button
                type="button"
                disabled={
                  saving ||
                  !nom.trim() ||
                  !debut ||
                  !fin ||
                  loyer.trim() === "" ||
                  Number.isNaN(Number(loyer))
                }
                onClick={() => void submit()}
                className="btn-accent btn-sm disabled:opacity-60"
              >
                {saving ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <FileSignature className="h-4 w-4" />
                )}
                Confirmer la création
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// ─── Création d'un dossier ──────────────────────────────────────────────

type ImmeubleLite = { id: number; name: string };
type LogementLite = {
  id: number;
  numero: string;
  loyer_demande: number | null;
};

function CreateDossierModal({
  immeubleId,
  onClose,
  onSaved
}: {
  immeubleId?: number;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [immeubles, setImmeubles] = useState<ImmeubleLite[]>([]);
  const [immId, setImmId] = useState<number | null>(immeubleId ?? null);
  const [logements, setLogements] = useState<LogementLite[]>([]);
  const [logementId, setLogementId] = useState<number | null>(null);
  const [dateDepart, setDateDepart] = useState("");
  const [loyer, setLoyer] = useState("");
  const [notes, setNotes] = useState("");
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (immeubleId != null) return;
    void (async () => {
      const r = await authedFetch("/api/v1/immobilier/immeubles");
      if (r.ok) setImmeubles((await r.json()) as ImmeubleLite[]);
    })();
  }, [immeubleId]);

  useEffect(() => {
    setLogementId(null);
    setLogements([]);
    if (immId == null) return;
    void (async () => {
      const r = await authedFetch(
        `/api/v1/immobilier/immeubles/${immId}/logements`
      );
      if (r.ok) setLogements((await r.json()) as LogementLite[]);
    })();
  }, [immId]);

  async function submit() {
    if (logementId == null) {
      setErr("Choisis le logement à relouer.");
      return;
    }
    setSaving(true);
    setErr(null);
    try {
      const r = await authedFetch("/api/v1/immobilier/locations", {
        method: "POST",
        body: JSON.stringify({
          logement_id: logementId,
          date_depart: dateDepart || null,
          loyer_demande: loyer.trim() ? Number(loyer) : null,
          notes: notes.trim() || null
        })
      });
      if (!r.ok) {
        const t = await r.text();
        throw new Error(t.slice(0, 200) || `HTTP ${r.status}`);
      }
      onSaved();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/70 p-4 backdrop-blur-sm">
      <div className="my-8 w-full max-w-md rounded-2xl border border-brand-800 bg-brand-950 shadow-2xl">
        <div className="flex items-center justify-between border-b border-brand-800 px-5 py-3">
          <h2 className="text-sm font-bold uppercase tracking-wider text-accent-500">
            Nouvelle relocation
          </h2>
          <button type="button" onClick={onClose} className="btn-ghost btn-xs">
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="grid gap-3 p-5">
          {immeubleId == null ? (
            <label className="text-[11px] font-semibold text-white/60">
              Immeuble
              <select
                value={immId == null ? "" : String(immId)}
                onChange={(e) =>
                  setImmId(e.target.value ? Number(e.target.value) : null)
                }
                className={`${INPUT_CLS} mt-0.5 block w-full`}
              >
                <option value="">Choisir…</option>
                {immeubles.map((i) => (
                  <option key={i.id} value={i.id}>
                    {i.name}
                  </option>
                ))}
              </select>
            </label>
          ) : null}
          <label className="text-[11px] font-semibold text-white/60">
            Logement
            <select
              value={logementId == null ? "" : String(logementId)}
              onChange={(e) => {
                const id = e.target.value ? Number(e.target.value) : null;
                setLogementId(id);
                const lg = logements.find((l) => l.id === id);
                if (lg?.loyer_demande != null && !loyer.trim())
                  setLoyer(String(lg.loyer_demande));
              }}
              disabled={immId == null}
              className={`${INPUT_CLS} mt-0.5 block w-full disabled:opacity-50`}
            >
              <option value="">
                {immId == null ? "Choisis d'abord l'immeuble" : "Choisir…"}
              </option>
              {logements.map((l) => (
                <option key={l.id} value={l.id}>
                  {l.numero}
                </option>
              ))}
            </select>
          </label>
          <label className="text-[11px] font-semibold text-white/60">
            Date de départ prévue
            <input
              type="date"
              value={dateDepart}
              onChange={(e) => setDateDepart(e.target.value)}
              className={`${INPUT_CLS} mt-0.5 block w-full`}
            />
          </label>
          <label className="text-[11px] font-semibold text-white/60">
            Loyer demandé ($/mois)
            <input
              inputMode="decimal"
              value={loyer}
              onChange={(e) => setLoyer(e.target.value)}
              className={`${INPUT_CLS} mt-0.5 block w-full`}
            />
          </label>
          <label className="text-[11px] font-semibold text-white/60">
            Notes
            <textarea
              rows={2}
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              className={`${INPUT_CLS} mt-0.5 block w-full`}
            />
          </label>
          {err ? (
            <p className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">
              {err}
            </p>
          ) : null}
          <div className="flex justify-end gap-2 border-t border-brand-800 pt-3">
            <button
              type="button"
              onClick={onClose}
              className="btn-secondary btn-sm"
            >
              Annuler
            </button>
            <button
              type="button"
              disabled={saving}
              onClick={() => void submit()}
              className="btn-accent btn-sm disabled:opacity-60"
            >
              {saving ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Plus className="h-4 w-4" />
              )}
              Créer le dossier
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
