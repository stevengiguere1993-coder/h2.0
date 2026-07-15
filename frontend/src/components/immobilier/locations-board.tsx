"use client";

/**
 * Pipeline « Locations » (relocation / vacances) — composant PARTAGÉ :
 * - page /immobilier/locations (tous les immeubles, filtre)
 * - onglet « Locations » de la fiche immeuble (prop immeubleId)
 *
 * Un dossier = un épisode de vacance d'un logement : départ confirmé →
 * annonce(s) → visites → candidat retenu → reloué. Tout est consigné à
 * la main (aucun lien Facebook/Kijiji — l'employé colle les liens).
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Check,
  ChevronDown,
  ChevronRight,
  ExternalLink,
  KeyRound,
  Loader2,
  Megaphone,
  Plus,
  Trash2,
  Users,
  X
} from "lucide-react";

import { Link } from "@/i18n/navigation";
import { authedFetch } from "@/lib/auth";

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
  candidat_contact: string | null;
  statut: string; // planifiee | faite | absent | annulee
  interesse: boolean | null;
  notes: string | null;
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
  annonces: Annonce[];
  visites: Visite[];
};

type Overview = {
  rows: Dossier[];
  nb_actifs: number;
  nb_annonces_actives: number;
  nb_visites_a_venir: number;
  nb_reloues_90j: number;
};

const STATUTS_ACTIFS = [
  "avis_recu",
  "annonce_publiee",
  "visites",
  "candidat_retenu"
];

const STATUT_LABEL: Record<string, string> = {
  avis_recu: "Départ confirmé",
  annonce_publiee: "Annonce publiée",
  visites: "Visites en cours",
  candidat_retenu: "Candidat retenu",
  reloue: "Reloué",
  annule: "Annulé"
};

const STATUT_BADGE: Record<string, string> = {
  avis_recu: "badge-amber",
  annonce_publiee: "badge-sky",
  visites: "badge-violet",
  candidat_retenu: "badge-blue",
  reloue: "badge-emerald",
  annule: "badge-neutral"
};

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

  // Immeubles présents dans les données (filtre de la page globale).
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

  const actifs = rows.filter((r) => STATUTS_ACTIFS.includes(r.statut));
  const historique = rows.filter((r) => !STATUTS_ACTIFS.includes(r.statut));

  return (
    <div className="space-y-4">
      {/* KPIs */}
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <KpiTile
          icon={<KeyRound className="h-4 w-4" />}
          label="En relocation"
          value={String(data?.nb_actifs ?? "…")}
          cls="border-amber-500/30 bg-amber-500/5 text-amber-200"
        />
        <KpiTile
          icon={<Megaphone className="h-4 w-4" />}
          label="Annonces actives"
          value={String(data?.nb_annonces_actives ?? "…")}
          cls="border-sky-500/30 bg-sky-500/5 text-sky-200"
        />
        <KpiTile
          icon={<Users className="h-4 w-4" />}
          label="Visites à venir"
          value={String(data?.nb_visites_a_venir ?? "…")}
          cls="border-violet-500/30 bg-violet-500/5 text-violet-200"
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

      {/* Dossiers actifs */}
      {data === null ? (
        <div className="flex items-center gap-2 py-8 text-xs text-white/50">
          <Loader2 className="h-3.5 w-3.5 animate-spin" /> Chargement…
        </div>
      ) : actifs.length === 0 ? (
        <div className="rounded-2xl border border-brand-800 bg-brand-900 p-8 text-center text-sm text-white/50">
          Aucune relocation en cours
          {immeubleId != null ? " pour cet immeuble" : ""}. Quand un
          locataire confirme son départ, lance un dossier depuis son bail
          (onglet Baux &amp; locataires) ou avec « Nouvelle relocation ».
        </div>
      ) : (
        <div className="space-y-2">
          {actifs.map((d) => (
            <DossierCard
              key={d.id}
              d={d}
              showImmeuble={immeubleId == null}
              open={openId === d.id}
              onToggle={() => setOpenId(openId === d.id ? null : d.id)}
              onPatch={(body) => patchDossier(d.id, body)}
              onMutated={() => void load()}
              onError={setErr}
            />
          ))}
        </div>
      )}

      {/* Historique (reloués / annulés) */}
      {historique.length > 0 ? (
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
            Historique ({historique.length})
          </button>
          {showHistorique ? (
            <div className="mt-2 space-y-2">
              {historique.map((d) => (
                <DossierCard
                  key={d.id}
                  d={d}
                  showImmeuble={immeubleId == null}
                  open={openId === d.id}
                  onToggle={() => setOpenId(openId === d.id ? null : d.id)}
                  onPatch={(body) => patchDossier(d.id, body)}
                  onMutated={() => void load()}
                  onError={setErr}
                />
              ))}
            </div>
          ) : null}
        </div>
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

// ─── Carte d'un dossier (repliable) ─────────────────────────────────────

function DossierCard({
  d,
  showImmeuble,
  open,
  onToggle,
  onPatch,
  onMutated,
  onError
}: {
  d: Dossier;
  showImmeuble: boolean;
  open: boolean;
  onToggle: () => void;
  onPatch: (body: Record<string, unknown>) => Promise<boolean>;
  onMutated: () => void;
  onError: (msg: string) => void;
}) {
  const prochaine = d.visites.find(
    (v) => v.statut === "planifiee" && v.quand
  );
  const annoncesActives = d.annonces.filter((a) => a.active).length;
  const deltaLoyer =
    d.loyer_demande != null && d.loyer_ancien != null && d.loyer_ancien > 0
      ? ((d.loyer_demande - d.loyer_ancien) / d.loyer_ancien) * 100
      : null;

  return (
    <div className="overflow-hidden rounded-2xl border border-brand-800 bg-brand-900">
      {/* En-tête cliquable */}
      <button
        type="button"
        onClick={onToggle}
        className="flex w-full flex-wrap items-center gap-x-4 gap-y-1 px-4 py-3 text-left transition hover:bg-brand-800/30"
      >
        {open ? (
          <ChevronDown className="h-4 w-4 shrink-0 text-white/40" />
        ) : (
          <ChevronRight className="h-4 w-4 shrink-0 text-white/40" />
        )}
        <span className="min-w-0 font-semibold text-white">
          Logement {d.logement_numero}
          {showImmeuble ? (
            <span className="font-normal text-white/50">
              {" "}
              — {d.immeuble_name}
            </span>
          ) : null}
        </span>
        <span className={`badge ${STATUT_BADGE[d.statut] || "badge-neutral"}`}>
          {STATUT_LABEL[d.statut] ?? d.statut}
        </span>
        <span className="ml-auto flex flex-wrap items-center gap-3 text-xs text-white/55">
          {d.locataire_sortant ? <span>{d.locataire_sortant} quitte</span> : null}
          <span>Départ : {fmtDate(d.date_depart)}</span>
          <span className="font-mono text-white/80">
            {money(d.loyer_demande)}
            {deltaLoyer != null && Math.abs(deltaLoyer) >= 0.5 ? (
              <span
                className={
                  deltaLoyer > 0 ? "text-emerald-300" : "text-rose-300"
                }
              >
                {" "}
                ({deltaLoyer > 0 ? "+" : ""}
                {deltaLoyer.toFixed(0)} %)
              </span>
            ) : null}
          </span>
          <span title="Annonces actives">
            <Megaphone className="mr-0.5 inline h-3 w-3" />
            {annoncesActives}
          </span>
          <span title="Visites">
            <Users className="mr-0.5 inline h-3 w-3" />
            {d.visites.length}
          </span>
          {prochaine ? (
            <span className="badge badge-violet">
              Visite {fmtDateTime(prochaine.quand)}
            </span>
          ) : null}
        </span>
      </button>

      {open ? (
        <DossierDetail
          d={d}
          onPatch={onPatch}
          onMutated={onMutated}
          onError={onError}
        />
      ) : null}
    </div>
  );
}

// ─── Détail (statut, annonces, visites, notes) ──────────────────────────

function DossierDetail({
  d,
  onPatch,
  onMutated,
  onError
}: {
  d: Dossier;
  onPatch: (body: Record<string, unknown>) => Promise<boolean>;
  onMutated: () => void;
  onError: (msg: string) => void;
}) {
  const [notesDraft, setNotesDraft] = useState(d.notes || "");
  const [savingNotes, setSavingNotes] = useState(false);
  const [busy, setBusy] = useState(false);

  // Formulaire annonce
  const [annPlateforme, setAnnPlateforme] = useState("Marketplace");
  const [annUrl, setAnnUrl] = useState("");
  // Formulaire visite
  const [visNom, setVisNom] = useState("");
  const [visContact, setVisContact] = useState("");
  const [visQuand, setVisQuand] = useState("");

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
    <div className="space-y-4 border-t border-brand-800 bg-brand-950/40 px-4 py-4">
      {/* Ligne statut + actions */}
      <div className="flex flex-wrap items-center gap-2">
        <label className="text-[11px] font-semibold text-white/60">
          Statut
          <select
            value={d.statut}
            onChange={(e) => void onPatch({ statut: e.target.value })}
            className={`${INPUT_CLS} ml-2 w-auto`}
          >
            {Object.entries(STATUT_LABEL).map(([id, label]) => (
              <option key={id} value={id}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <label className="text-[11px] font-semibold text-white/60">
          Départ
          <input
            type="date"
            defaultValue={d.date_depart || ""}
            onBlur={(e) =>
              e.target.value !== (d.date_depart || "")
                ? void onPatch({ date_depart: e.target.value || null })
                : undefined
            }
            className={`${INPUT_CLS} ml-2 w-auto`}
          />
        </label>
        <label className="text-[11px] font-semibold text-white/60">
          Loyer demandé ($)
          <input
            inputMode="decimal"
            defaultValue={
              d.loyer_demande != null ? String(d.loyer_demande) : ""
            }
            onBlur={(e) => {
              const v = e.target.value.trim();
              const n = v === "" ? null : Number(v);
              if (v !== "" && Number.isNaN(n)) return;
              if (n !== d.loyer_demande)
                void onPatch({ loyer_demande: n });
            }}
            className={`${INPUT_CLS} ml-2 w-24`}
          />
        </label>
        {d.loyer_ancien != null ? (
          <span className="text-xs text-white/40">
            (ancien : {money(d.loyer_ancien)})
          </span>
        ) : null}
        <span className="ml-auto flex items-center gap-2">
          <Link
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            href={`/immobilier/logements/${d.logement_id}` as any}
            className="text-xs text-accent-500 hover:underline"
          >
            Fiche du logement →
          </Link>
          <button
            type="button"
            title="Supprimer ce dossier de relocation"
            onClick={() => {
              if (window.confirm("Supprimer ce dossier de relocation ?"))
                void api(`/${d.id}`, "DELETE");
            }}
            className="rounded-md border border-rose-400/30 bg-rose-500/10 p-1.5 text-rose-300 hover:bg-rose-500/20"
          >
            <Trash2 className="h-3.5 w-3.5" />
          </button>
        </span>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        {/* Annonces */}
        <div className="rounded-xl border border-brand-800 bg-brand-900 p-3.5">
          <h4 className="mb-2 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider text-accent-500">
            <Megaphone className="h-3.5 w-3.5" /> Annonces
          </h4>
          {d.annonces.length === 0 ? (
            <p className="text-xs text-white/40">
              Aucune annonce consignée.
            </p>
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
                  <span className="text-white/40">
                    {fmtDate(a.publiee_le)}
                  </span>
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
              placeholder="Lien de l'annonce (optionnel)"
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

        {/* Visites */}
        <div className="rounded-xl border border-brand-800 bg-brand-900 p-3.5">
          <h4 className="mb-2 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider text-accent-500">
            <Users className="h-3.5 w-3.5" /> Visites &amp; candidats
          </h4>
          {d.visites.length === 0 ? (
            <p className="text-xs text-white/40">
              Aucune visite planifiée.
            </p>
          ) : (
            <ul className="space-y-1.5">
              {d.visites.map((v) => (
                <li
                  key={v.id}
                  className="flex flex-wrap items-center gap-2 text-xs text-white/75"
                >
                  <span className="font-medium text-white">
                    {v.candidat_nom}
                  </span>
                  {v.candidat_contact ? (
                    <span className="text-white/45">{v.candidat_contact}</span>
                  ) : null}
                  <span className="text-white/40">{fmtDateTime(v.quand)}</span>
                  <span className="ml-auto flex items-center gap-1">
                    <select
                      value={v.statut}
                      onChange={(e) =>
                        void api(`/visites/${v.id}`, "PATCH", {
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
                    {v.statut === "faite" ? (
                      <button
                        type="button"
                        title="Le candidat est-il intéressé ?"
                        onClick={() =>
                          void api(`/visites/${v.id}`, "PATCH", {
                            interesse:
                              v.interesse === true
                                ? false
                                : v.interesse === false
                                  ? null
                                  : true
                          })
                        }
                        className={`rounded px-1.5 py-0.5 text-[10px] font-semibold ${
                          v.interesse === true
                            ? "bg-emerald-500/15 text-emerald-300"
                            : v.interesse === false
                              ? "bg-rose-500/15 text-rose-300"
                              : "text-white/40 hover:bg-brand-800"
                        }`}
                      >
                        {v.interesse === true
                          ? "Intéressé"
                          : v.interesse === false
                            ? "Pas intéressé"
                            : "Intérêt ?"}
                      </button>
                    ) : null}
                    <button
                      type="button"
                      onClick={() => void api(`/visites/${v.id}`, "DELETE")}
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
            <input
              value={visNom}
              onChange={(e) => setVisNom(e.target.value)}
              placeholder="Nom du candidat"
              className={`${INPUT_CLS} min-w-0 flex-1`}
            />
            <input
              value={visContact}
              onChange={(e) => setVisContact(e.target.value)}
              placeholder="Tél. / courriel"
              className={`${INPUT_CLS} w-36`}
            />
            <input
              type="datetime-local"
              value={visQuand}
              onChange={(e) => setVisQuand(e.target.value)}
              className={`${INPUT_CLS} w-auto`}
            />
            <button
              type="button"
              disabled={busy || !visNom.trim()}
              onClick={async () => {
                if (
                  await api(`/${d.id}/visites`, "POST", {
                    candidat_nom: visNom.trim(),
                    candidat_contact: visContact.trim() || null,
                    quand: visQuand
                      ? new Date(visQuand).toISOString()
                      : null
                  })
                ) {
                  setVisNom("");
                  setVisContact("");
                  setVisQuand("");
                }
              }}
              className="btn-secondary btn-sm disabled:opacity-50"
            >
              <Plus className="h-3.5 w-3.5" /> Ajouter
            </button>
          </div>
        </div>
      </div>

      {/* Notes */}
      <div>
        <textarea
          rows={2}
          value={notesDraft}
          onChange={(e) => setNotesDraft(e.target.value)}
          placeholder="Notes de suivi (état du logement, peinture à faire, candidat à relancer…)"
          className="block w-full rounded-md border border-brand-800 bg-brand-950 px-3 py-2 text-xs text-white outline-none focus:border-accent-500"
        />
        <button
          type="button"
          disabled={savingNotes || notesDraft === (d.notes || "")}
          onClick={async () => {
            setSavingNotes(true);
            await onPatch({ notes: notesDraft.trim() ? notesDraft : null });
            setSavingNotes(false);
          }}
          className="btn-secondary btn-sm mt-1.5 disabled:opacity-40"
        >
          {savingNotes ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <Check className="h-3.5 w-3.5" />
          )}
          Enregistrer les notes
        </button>
      </div>
    </div>
  );
}

// ─── Création d'un dossier ──────────────────────────────────────────────

type ImmeubleLite = { id: number; name: string };
type LogementLite = { id: number; numero: string; loyer_demande: number | null };

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
            <button type="button" onClick={onClose} className="btn-secondary btn-sm">
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
