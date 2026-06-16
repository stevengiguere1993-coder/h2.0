"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  Loader2,
  Pencil,
  Plus,
  Trash2,
  Wrench,
  X
} from "lucide-react";

import { Link } from "@/i18n/navigation";
import { authedFetch } from "@/lib/auth";
import { PageDriveSection } from "@/components/drive/PageDriveSection";
import { ImmobilierTopbar } from "../layout";

type OverviewRow = {
  id: number;
  immeuble_id: number;
  immeuble_name: string;
  logement_id: number | null;
  logement_numero: string | null;
  titre: string;
  description: string | null;
  priorite: string;
  status: string;
  fournisseur: string | null;
  cout_estime: number | null;
  cout_reel: number | null;
  plannifie_pour: string | null;
  complete_le: string | null;
  created_at: string;
  jours_ouverts: number | null;
};

type Overview = {
  rows: OverviewRow[];
  nb_total: number;
  nb_ouvert: number;
  nb_en_cours: number;
  nb_en_attente: number;
  nb_termine: number;
  nb_annule: number;
  nb_urgences_actives: number;
  total_cout_estime_actif: number;
  total_cout_reel: number;
};

type ImmeubleListItem = {
  id: number;
  name: string;
  nb_logements_actifs: number;
};

type Logement = { id: number; numero: string | null };

const PRIORITES = [
  { v: "urgence", label: "Urgence" },
  { v: "haute", label: "Haute" },
  { v: "normale", label: "Normale" },
  { v: "basse", label: "Basse" }
];

const STATUTS = [
  { v: "ouvert", label: "Ouvert" },
  { v: "en_cours", label: "En cours" },
  { v: "en_attente", label: "En attente" },
  { v: "termine", label: "Terminé" },
  { v: "annule", label: "Annulé" }
];

function prioBadge(p: string): string {
  switch (p) {
    case "urgence":
      return "border-red-500/40 bg-red-500/15 text-red-200";
    case "haute":
      return "border-amber-500/40 bg-amber-500/15 text-amber-200";
    case "normale":
      return "border-sky-500/40 bg-sky-500/10 text-sky-200";
    default:
      return "border-white/15 bg-white/5 text-white/60";
  }
}

function statusBadge(s: string): string {
  switch (s) {
    case "ouvert":
      return "border-rose-500/40 bg-rose-500/10 text-rose-200";
    case "en_cours":
      return "border-sky-500/40 bg-sky-500/10 text-sky-200";
    case "en_attente":
      return "border-violet-500/40 bg-violet-500/10 text-violet-200";
    case "termine":
      return "border-emerald-500/40 bg-emerald-500/10 text-emerald-200";
    default:
      return "border-white/15 bg-white/5 text-white/40";
  }
}

function prioLabel(v: string): string {
  return PRIORITES.find((p) => p.v === v)?.label ?? v;
}

function money(n: number | null): string {
  if (n == null) return "—";
  return n.toLocaleString("fr-CA", {
    style: "currency",
    currency: "CAD",
    maximumFractionDigits: 0
  });
}

const SELECT =
  "rounded-lg border border-brand-800 bg-brand-950 px-2.5 py-1.5 text-sm text-white outline-none focus:border-sky-400/60";
const INPUT =
  "w-full rounded-lg border border-brand-800 bg-brand-950 px-3 py-2 text-sm text-white outline-none focus:border-sky-400/60";

export default function MaintenancePage() {
  const [data, setData] = useState<Overview | null>(null);
  const [immeubles, setImmeubles] = useState<ImmeubleListItem[]>([]);
  const [loading, setLoading] = useState(true);

  const [fStatut, setFStatut] = useState("");
  const [fPriorite, setFPriorite] = useState("");
  const [fImmeuble, setFImmeuble] = useState("");
  const [inclureTermines, setInclureTermines] = useState(false);

  const [editing, setEditing] = useState<OverviewRow | "new" | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);

  const load = useCallback(async () => {
    const qs = new URLSearchParams();
    if (fStatut) qs.set("statut", fStatut);
    if (fPriorite) qs.set("priorite", fPriorite);
    if (fImmeuble) qs.set("immeuble_id", fImmeuble);
    if (inclureTermines) qs.set("inclure_termines", "true");
    const res = await authedFetch(
      `/api/v1/immobilier/maintenance/overview?${qs.toString()}`
    );
    if (res.ok) setData((await res.json()) as Overview);
    setLoading(false);
  }, [fStatut, fPriorite, fImmeuble, inclureTermines]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    void (async () => {
      const res = await authedFetch("/api/v1/immobilier/immeubles");
      if (res.ok) setImmeubles((await res.json()) as ImmeubleListItem[]);
    })();
  }, []);

  async function quickStatus(row: OverviewRow, status: string) {
    setBusyId(row.id);
    try {
      await authedFetch(`/api/v1/immobilier/maintenance/${row.id}`, {
        method: "PATCH",
        body: JSON.stringify({ status })
      });
      await load();
    } finally {
      setBusyId(null);
    }
  }

  async function remove(row: OverviewRow) {
    if (!confirm(`Supprimer l'ordre « ${row.titre} » ?`)) return;
    setBusyId(row.id);
    try {
      await authedFetch(`/api/v1/immobilier/maintenance/${row.id}`, {
        method: "DELETE"
      });
      await load();
    } finally {
      setBusyId(null);
    }
  }

  const kpis = useMemo(
    () => [
      {
        label: "Urgences actives",
        value: data?.nb_urgences_actives ?? 0,
        cls: "border-red-500/40 bg-red-500/10 text-red-200",
        icon: true
      },
      {
        label: "Ouverts",
        value: data?.nb_ouvert ?? 0,
        cls: "border-rose-500/30 bg-rose-500/5 text-rose-200"
      },
      {
        label: "En cours",
        value: data?.nb_en_cours ?? 0,
        cls: "border-sky-500/30 bg-sky-500/5 text-sky-200"
      },
      {
        label: "En attente",
        value: data?.nb_en_attente ?? 0,
        cls: "border-violet-500/30 bg-violet-500/5 text-violet-200"
      }
    ],
    [data]
  );

  const hasFilter = fStatut || fPriorite || fImmeuble || inclureTermines;

  return (
    <>
      <ImmobilierTopbar
        breadcrumbs={[
          { label: "Gestion immobilière", href: "/immobilier" },
          { label: "Maintenance" }
        ]}
        rightSlot={
          <button
            type="button"
            onClick={() => setEditing("new")}
            className="inline-flex items-center gap-1.5 rounded-lg bg-sky-500 px-3 py-1.5 text-sm font-semibold text-white hover:bg-sky-400"
          >
            <Plus className="h-4 w-4" /> Nouvel ordre
          </button>
        }
      />
      <div className="p-4 lg:p-6">
        <header className="flex items-start gap-3">
          <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-sky-500/15 text-sky-300">
            <Wrench className="h-5 w-5" />
          </span>
          <div>
            <h1 className="text-2xl font-bold text-white">Maintenance</h1>
            <p className="mt-1 max-w-2xl text-sm text-white/60">
              Vue transversale du portefeuille : tous les ordres de travail,
              urgences en premier. Change un statut en un clic.
            </p>
          </div>
        </header>

        {/* KPIs */}
        <div className="mt-6 grid grid-cols-2 gap-3 lg:grid-cols-4">
          {kpis.map((k) => (
            <div
              key={k.label}
              className={`rounded-2xl border p-4 ${k.cls}`}
            >
              <div className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wider opacity-80">
                {k.icon ? <AlertTriangle className="h-3.5 w-3.5" /> : null}
                {k.label}
              </div>
              <div className="mt-1 text-3xl font-bold">{k.value}</div>
            </div>
          ))}
        </div>

        {data && (data.total_cout_estime_actif > 0 || data.total_cout_reel > 0) ? (
          <div className="mt-3 flex flex-wrap gap-4 text-xs text-white/60">
            <span>
              Coût estimé (actifs) :{" "}
              <span className="font-semibold text-white">
                {money(data.total_cout_estime_actif)}
              </span>
            </span>
            <span>
              Coût réel (cumulé) :{" "}
              <span className="font-semibold text-white">
                {money(data.total_cout_reel)}
              </span>
            </span>
          </div>
        ) : null}

        {/* Filtres */}
        <div className="mt-6 flex flex-wrap items-center gap-2">
          <select
            className={SELECT}
            value={fImmeuble}
            onChange={(e) => setFImmeuble(e.target.value)}
          >
            <option value="">Tous les immeubles</option>
            {immeubles.map((im) => (
              <option key={im.id} value={im.id}>
                {im.name}
              </option>
            ))}
          </select>
          <select
            className={SELECT}
            value={fPriorite}
            onChange={(e) => setFPriorite(e.target.value)}
          >
            <option value="">Toutes priorités</option>
            {PRIORITES.map((p) => (
              <option key={p.v} value={p.v}>
                {p.label}
              </option>
            ))}
          </select>
          <select
            className={SELECT}
            value={fStatut}
            onChange={(e) => setFStatut(e.target.value)}
          >
            <option value="">Statuts actifs</option>
            {STATUTS.map((s) => (
              <option key={s.v} value={s.v}>
                {s.label}
              </option>
            ))}
          </select>
          <label className="inline-flex cursor-pointer items-center gap-1.5 text-xs text-white/70">
            <input
              type="checkbox"
              checked={inclureTermines}
              onChange={(e) => setInclureTermines(e.target.checked)}
              className="h-3.5 w-3.5 accent-sky-500"
            />
            Inclure terminés / annulés
          </label>
          {hasFilter ? (
            <button
              type="button"
              onClick={() => {
                setFStatut("");
                setFPriorite("");
                setFImmeuble("");
                setInclureTermines(false);
              }}
              className="inline-flex items-center gap-1 rounded-lg border border-brand-800 px-2.5 py-1.5 text-xs text-white/60 hover:text-white"
            >
              <X className="h-3.5 w-3.5" /> Réinitialiser
            </button>
          ) : null}
        </div>

        {/* Tableau */}
        <div className="mt-4 overflow-x-auto rounded-2xl border border-brand-800">
          <table className="w-full min-w-[820px] text-sm">
            <thead>
              <tr className="border-b border-brand-800 bg-brand-900 text-left text-[11px] uppercase tracking-wider text-white/45">
                <th className="px-3 py-2.5 font-semibold">Ordre</th>
                <th className="px-3 py-2.5 font-semibold">Immeuble</th>
                <th className="px-3 py-2.5 font-semibold">Priorité</th>
                <th className="px-3 py-2.5 font-semibold">Statut</th>
                <th className="px-3 py-2.5 font-semibold">Âge</th>
                <th className="px-3 py-2.5 font-semibold">Planifié</th>
                <th className="px-3 py-2.5 text-right font-semibold">Coût</th>
                <th className="px-3 py-2.5" />
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr>
                  <td colSpan={8} className="px-3 py-10 text-center text-white/50">
                    <Loader2 className="mr-1 inline h-4 w-4 animate-spin" />{" "}
                    Chargement…
                  </td>
                </tr>
              ) : !data || data.rows.length === 0 ? (
                <tr>
                  <td colSpan={8} className="px-3 py-12 text-center text-white/50">
                    Aucun ordre de maintenance{" "}
                    {hasFilter ? "pour ces filtres" : "actif"}. 🎉
                  </td>
                </tr>
              ) : (
                data.rows.map((r) => (
                  <tr
                    key={r.id}
                    className={`border-b border-brand-800/60 hover:bg-brand-900/40 ${
                      r.priorite === "urgence" &&
                      ["ouvert", "en_cours", "en_attente"].includes(r.status)
                        ? "bg-red-500/[0.04]"
                        : ""
                    }`}
                  >
                    <td className="px-3 py-2.5">
                      <button
                        type="button"
                        onClick={() => setEditing(r)}
                        className="text-left font-semibold text-white hover:text-sky-300"
                      >
                        {r.titre}
                      </button>
                      {r.logement_numero ? (
                        <span className="ml-1.5 text-[11px] text-white/40">
                          · logt {r.logement_numero}
                        </span>
                      ) : null}
                      {r.fournisseur ? (
                        <div className="text-[11px] text-white/40">
                          {r.fournisseur}
                        </div>
                      ) : null}
                    </td>
                    <td className="px-3 py-2.5">
                      <Link
                        // eslint-disable-next-line @typescript-eslint/no-explicit-any
                        href={`/immobilier/immeubles/${r.immeuble_id}` as any}
                        className="text-white/70 hover:text-sky-300"
                      >
                        {r.immeuble_name}
                      </Link>
                    </td>
                    <td className="px-3 py-2.5">
                      <span
                        className={`inline-block rounded-full border px-2 py-0.5 text-[11px] font-semibold ${prioBadge(
                          r.priorite
                        )}`}
                      >
                        {prioLabel(r.priorite)}
                      </span>
                    </td>
                    <td className="px-3 py-2.5">
                      <select
                        value={r.status}
                        disabled={busyId === r.id}
                        onChange={(e) => void quickStatus(r, e.target.value)}
                        className={`rounded-full border px-2 py-0.5 text-[11px] font-semibold outline-none ${statusBadge(
                          r.status
                        )} disabled:opacity-50`}
                      >
                        {STATUTS.map((s) => (
                          <option
                            key={s.v}
                            value={s.v}
                            className="bg-brand-950 text-white"
                          >
                            {s.label}
                          </option>
                        ))}
                      </select>
                    </td>
                    <td className="px-3 py-2.5 text-white/60">
                      {r.jours_ouverts == null
                        ? "—"
                        : `${r.jours_ouverts} j`}
                    </td>
                    <td className="px-3 py-2.5 text-white/60">
                      {r.plannifie_pour ?? "—"}
                    </td>
                    <td className="px-3 py-2.5 text-right text-white/70">
                      {r.cout_reel != null
                        ? money(r.cout_reel)
                        : r.cout_estime != null
                          ? `~${money(r.cout_estime)}`
                          : "—"}
                    </td>
                    <td className="px-3 py-2.5">
                      <div className="flex items-center justify-end gap-1">
                        <button
                          type="button"
                          onClick={() => setEditing(r)}
                          className="rounded p-1 text-white/40 hover:text-sky-300"
                          title="Éditer"
                        >
                          <Pencil className="h-3.5 w-3.5" />
                        </button>
                        <button
                          type="button"
                          onClick={() => void remove(r)}
                          disabled={busyId === r.id}
                          className="rounded p-1 text-white/40 hover:text-rose-300 disabled:opacity-50"
                          title="Supprimer"
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </button>
                      </div>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>

        <PageDriveSection
          pageKey="page:immobilier:maintenance"
          pole="Gestion immobilière"
          label="Maintenance"
          route="/immobilier/maintenance"
          className="mt-6"
        />
      </div>

      {editing ? (
        <OrdreModal
          row={editing === "new" ? null : editing}
          immeubles={immeubles}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null);
            void load();
          }}
        />
      ) : null}
    </>
  );
}

function OrdreModal({
  row,
  immeubles,
  onClose,
  onSaved
}: {
  row: OverviewRow | null;
  immeubles: ImmeubleListItem[];
  onClose: () => void;
  onSaved: () => void;
}) {
  const [immeubleId, setImmeubleId] = useState<string>(
    row ? String(row.immeuble_id) : ""
  );
  const [logementId, setLogementId] = useState<string>(
    row?.logement_id ? String(row.logement_id) : ""
  );
  const [logements, setLogements] = useState<Logement[]>([]);
  const [titre, setTitre] = useState(row?.titre ?? "");
  const [description, setDescription] = useState(row?.description ?? "");
  const [priorite, setPriorite] = useState(row?.priorite ?? "normale");
  const [statut, setStatut] = useState(row?.status ?? "ouvert");
  const [fournisseur, setFournisseur] = useState(row?.fournisseur ?? "");
  const [coutEstime, setCoutEstime] = useState(
    row?.cout_estime != null ? String(row.cout_estime) : ""
  );
  const [coutReel, setCoutReel] = useState(
    row?.cout_reel != null ? String(row.cout_reel) : ""
  );
  const [planifie, setPlanifie] = useState(row?.plannifie_pour ?? "");
  const [notes, setNotes] = useState("");
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (!immeubleId) {
      setLogements([]);
      return;
    }
    void (async () => {
      const res = await authedFetch(
        `/api/v1/immobilier/immeubles/${immeubleId}/logements`
      );
      if (res.ok) setLogements((await res.json()) as Logement[]);
    })();
  }, [immeubleId]);

  async function save() {
    if (!immeubleId) {
      setErr("Choisis un immeuble.");
      return;
    }
    if (!titre.trim()) {
      setErr("Le titre est requis.");
      return;
    }
    setSaving(true);
    setErr(null);
    const body: Record<string, unknown> = {
      logement_id: logementId ? Number(logementId) : null,
      titre: titre.trim(),
      description: description.trim() || null,
      priorite,
      status: statut,
      fournisseur: fournisseur.trim() || null,
      cout_estime: coutEstime ? Number(coutEstime) : null,
      cout_reel: coutReel ? Number(coutReel) : null,
      plannifie_pour: planifie || null
    };
    if (notes.trim()) body.notes = notes.trim();
    try {
      let res: Response;
      if (row) {
        res = await authedFetch(`/api/v1/immobilier/maintenance/${row.id}`, {
          method: "PATCH",
          body: JSON.stringify(body)
        });
      } else {
        body.immeuble_id = Number(immeubleId);
        res = await authedFetch("/api/v1/immobilier/maintenance", {
          method: "POST",
          body: JSON.stringify(body)
        });
      }
      if (!res.ok) {
        setErr("Échec de l'enregistrement.");
        return;
      }
      onSaved();
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
      <div className="max-h-[90vh] w-full max-w-lg overflow-y-auto rounded-2xl border border-brand-800 bg-brand-900 p-5 shadow-2xl">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-lg font-bold text-white">
            {row ? "Modifier l'ordre" : "Nouvel ordre de maintenance"}
          </h2>
          <button
            type="button"
            onClick={onClose}
            className="rounded p-1 text-white/50 hover:text-white"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="space-y-3">
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="mb-1 block text-xs font-semibold text-white/60">
                Immeuble *
              </label>
              <select
                className={INPUT}
                value={immeubleId}
                onChange={(e) => {
                  setImmeubleId(e.target.value);
                  setLogementId("");
                }}
                disabled={!!row}
              >
                <option value="">—</option>
                {immeubles.map((im) => (
                  <option key={im.id} value={im.id}>
                    {im.name}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="mb-1 block text-xs font-semibold text-white/60">
                Logement (optionnel)
              </label>
              <select
                className={INPUT}
                value={logementId}
                onChange={(e) => setLogementId(e.target.value)}
              >
                <option value="">Immeuble (commun)</option>
                {logements.map((l) => (
                  <option key={l.id} value={l.id}>
                    {l.numero ?? `#${l.id}`}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <div>
            <label className="mb-1 block text-xs font-semibold text-white/60">
              Titre *
            </label>
            <input
              className={INPUT}
              value={titre}
              onChange={(e) => setTitre(e.target.value)}
              placeholder="Ex. Fuite robinet cuisine"
            />
          </div>

          <div>
            <label className="mb-1 block text-xs font-semibold text-white/60">
              Description
            </label>
            <textarea
              className={INPUT}
              rows={2}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="mb-1 block text-xs font-semibold text-white/60">
                Priorité
              </label>
              <select
                className={INPUT}
                value={priorite}
                onChange={(e) => setPriorite(e.target.value)}
              >
                {PRIORITES.map((p) => (
                  <option key={p.v} value={p.v}>
                    {p.label}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="mb-1 block text-xs font-semibold text-white/60">
                Statut
              </label>
              <select
                className={INPUT}
                value={statut}
                onChange={(e) => setStatut(e.target.value)}
              >
                {STATUTS.map((s) => (
                  <option key={s.v} value={s.v}>
                    {s.label}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="mb-1 block text-xs font-semibold text-white/60">
                Coût estimé ($)
              </label>
              <input
                className={INPUT}
                type="number"
                value={coutEstime}
                onChange={(e) => setCoutEstime(e.target.value)}
              />
            </div>
            <div>
              <label className="mb-1 block text-xs font-semibold text-white/60">
                Coût réel ($)
              </label>
              <input
                className={INPUT}
                type="number"
                value={coutReel}
                onChange={(e) => setCoutReel(e.target.value)}
              />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="mb-1 block text-xs font-semibold text-white/60">
                Fournisseur
              </label>
              <input
                className={INPUT}
                value={fournisseur}
                onChange={(e) => setFournisseur(e.target.value)}
              />
            </div>
            <div>
              <label className="mb-1 block text-xs font-semibold text-white/60">
                Planifié pour
              </label>
              <input
                className={INPUT}
                type="date"
                value={planifie}
                onChange={(e) => setPlanifie(e.target.value)}
              />
            </div>
          </div>

          {err ? (
            <p className="text-sm text-rose-300">{err}</p>
          ) : null}
        </div>

        <div className="mt-5 flex justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-brand-800 px-4 py-2 text-sm text-white/70 hover:text-white"
          >
            Annuler
          </button>
          <button
            type="button"
            onClick={() => void save()}
            disabled={saving}
            className="inline-flex items-center gap-1.5 rounded-lg bg-sky-500 px-4 py-2 text-sm font-semibold text-white hover:bg-sky-400 disabled:opacity-50"
          >
            {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
            {row ? "Enregistrer" : "Créer l'ordre"}
          </button>
        </div>
      </div>
    </div>
  );
}
