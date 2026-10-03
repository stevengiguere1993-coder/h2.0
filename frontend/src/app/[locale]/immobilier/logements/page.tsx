"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  Building2,
  Check,
  DoorOpen,
  Loader2,
  Pencil,
  Plus,
  Search,
  Trash2,
  X
} from "lucide-react";

import { Link, useRouter } from "@/i18n/navigation";
import { authedFetch } from "@/lib/auth";
import { BoutonExport } from "@/components/immobilier/bouton-export";
import { ImmobilierTopbar, useImmobilierLayout } from "../layout";
import { LOUER_INDEFINIMENT_INFO } from "@/components/immobilier/fin-bail";
import {
  fmtPieces,
  LOGEMENT_TYPES,
  LogementFiche,
  type LogementFicheData
} from "@/components/immobilier/logement-fiche";
import {
  LogementsLotModal,
  numOuNull,
  patchLogementApi,
  supprimerLogementApi
} from "@/components/immobilier/logements-lot";

/**
 * Logements — vue agrégée de TOUS les logements du portefeuille
 * (entreprise active via le contexte du layout). Filtres client-side :
 * recherche texte, immeuble, statut. Clic sur le numéro → PAGE fiche
 * logement (/immobilier/logements/{id}) ; la colonne immeuble reste
 * un lien vers la fiche immeuble.
 */

type ImmeubleLite = {
  id: number;
  name: string;
  address: string;
  city?: string | null;
  gestion_externe?: boolean;
};

type Logement = LogementFicheData;

type Row = Logement & {
  immeuble_name: string;
  immeuble_gestion_externe: boolean;
};

const STATUTS = [
  { value: "all", label: "Tous" },
  { value: "occupe", label: "Occupés" },
  { value: "vacant", label: "Vacants" },
  { value: "reserve", label: "Réservés" },
  { value: "hors_location", label: "Hors loc." }
];

function fmtMoney(n: number | null | undefined): string {
  if (n == null) return "—";
  return new Intl.NumberFormat("fr-CA", {
    style: "currency",
    currency: "CAD",
    maximumFractionDigits: 0
  }).format(n);
}

function fmtJour(iso?: string | null): string {
  if (!iso) return "";
  const [y, m, d] = iso.split("-").map(Number);
  // L'année s'affiche dès qu'elle diffère de l'année courante : « libre
  // le 30 juin 2027 » (retour Phil 2026-09-09 sur le 3 Elgin).
  return new Date(y, (m || 1) - 1, d || 1).toLocaleDateString("fr-CA", {
    day: "numeric",
    month: "short",
    ...(y !== new Date().getFullYear() ? { year: "numeric" } : {})
  });
}

function StatutBadge({
  status,
  libreLe
}: {
  status: string;
  /** Départ ACTÉ : le logement se libère à cette date. */
  libreLe?: string | null;
}) {
  const map: Record<string, { cls: string; label: string }> = {
    occupe: { cls: "badge-emerald", label: "Occupé" },
    vacant: { cls: "badge-amber", label: "Vacant" },
    reserve: { cls: "badge-sky", label: "Réservé" },
    hors_location: { cls: "badge-neutral", label: "Hors loc." }
  };
  const t = map[status] || { cls: "badge-neutral", label: status };
  // Un logement occupé dont le départ est acté n'est pas dans le même
  // état qu'un logement occupé tout court : c'est celui-là qu'il faut
  // relouer (retour Phil 2026-08-19).
  if (libreLe && status === "occupe") {
    return (
      <span
        className="badge badge-amber"
        title={`Départ confirmé — le logement se libère le ${libreLe}`}
      >
        Occupé · libre le {fmtJour(libreLe)}
      </span>
    );
  }
  return <span className={`badge ${t.cls}`}>{t.label}</span>;
}

type DoublonGroupe = {
  immeuble_id: number;
  immeuble_name: string;
  numero: string;
  logements: Array<{
    id: number;
    numero: string;
    status: string;
    nb_baux: number;
    nb_paiements_externes: number;
  }>;
};

/** Logements en double dans un même immeuble (retour Phil 2026-09-09 :
 *  « 8906-C » trois fois). Fusion en un clic : tout ce qui est rattaché
 *  aux doublons suit le logement conservé, rien n'est effacé. */
function DoublonsLogementsBanner() {
  const [groupes, setGroupes] = useState<DoublonGroupe[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const charger = useCallback(async () => {
    try {
      const r = await authedFetch("/api/v1/immobilier/logements/doublons");
      if (r.ok) setGroupes((await r.json()) as DoublonGroupe[]);
    } catch {
      /* diagnostic seulement */
    }
  }, []);
  //: Lequel garder ? (défaut : le plus ancien) — audit 2026-09-15.
  const [garderChoix, setGarderChoix] = useState<Record<string, number>>({});

  useEffect(() => {
    void charger();
  }, [charger]);
  if (!groupes || groupes.length === 0) return null;

  async function fusionner(g: DoublonGroupe) {
    const ids = g.logements.map((l) => l.id).sort((a, b) => a - b);
    const cle = `${g.immeuble_id}-${g.numero}`;
    const garder = garderChoix[cle] ?? ids[0];
    if (
      !window.confirm(
        `Fusionner les ${ids.length} logements « ${g.numero} » de ${g.immeuble_name} en un seul (#${garder}) ? Baux, paiements, documents, dossiers TAL et maintenance des doublons seront rattachés au logement conservé.`
      )
    )
      return;
    setBusy(true);
    setMsg(null);
    try {
      const r = await authedFetch("/api/v1/immobilier/logements/fusionner", {
        method: "POST",
        body: JSON.stringify({
          garder_id: garder,
          supprimer_ids: ids.filter((i) => i !== garder)
        })
      });
      if (!r.ok) throw new Error((await r.text()).slice(0, 200));
      setMsg(`« ${g.numero} » fusionné.`);
      await charger();
      window.setTimeout(() => window.location.reload(), 600);
    } catch (e) {
      setMsg(`Fusion impossible : ${(e as Error).message}`);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mb-4 rounded-xl border border-amber-500/40 bg-amber-500/10 px-4 py-3 text-xs text-amber-100">
      <p className="font-semibold">
        {groupes.length} numéro{groupes.length > 1 ? "s" : ""} de logement en
        double — la page Paiements les affiche plusieurs fois.
      </p>
      <ul className="mt-2 space-y-1.5">
        {groupes.map((g) => (
          <li
            key={`${g.immeuble_id}-${g.numero}`}
            className="flex flex-wrap items-center gap-2"
          >
            <span>
              {g.immeuble_name} · <strong>{g.numero}</strong> ×
              {g.logements.length}
              <span className="ml-1 text-amber-200/70">
                (
                {g.logements
                  .map(
                    (l) =>
                      `#${l.id} ${l.status}${l.nb_baux ? ` · ${l.nb_baux} bail` : ""}${
                        l.nb_paiements_externes
                          ? ` · ${l.nb_paiements_externes} paiement(s)`
                          : ""
                      }`
                  )
                  .join(" ; ")}
                )
              </span>
            </span>
            <select
              value={String(
                garderChoix[`${g.immeuble_id}-${g.numero}`] ??
                  Math.min(...g.logements.map((l) => l.id))
              )}
              onChange={(e) =>
                setGarderChoix((m) => ({
                  ...m,
                  [`${g.immeuble_id}-${g.numero}`]: Number(e.target.value)
                }))
              }
              className="rounded-md border border-amber-400/40 bg-brand-950 px-1.5 py-0.5 text-[11px] text-amber-100"
              title="Logement à conserver (les autres sont fusionnés dedans)"
            >
              {g.logements.map((l) => (
                <option key={l.id} value={l.id}>
                  garder #{l.id} ({l.status}
                  {l.nb_baux ? `, ${l.nb_baux} bail` : ""})
                </option>
              ))}
            </select>
            <button
              type="button"
              disabled={busy}
              onClick={() => void fusionner(g)}
              className="rounded-md border border-amber-400/60 bg-amber-500/20 px-2 py-0.5 text-[11px] font-semibold text-amber-100 hover:bg-amber-500/30 disabled:opacity-50"
            >
              Fusionner
            </button>
          </li>
        ))}
      </ul>
      {msg ? <p className="mt-2 text-amber-200">{msg}</p> : null}
    </div>
  );
}

export default function LogementsPage() {
  const { currentEntrepriseId } = useImmobilierLayout();
  const router = useRouter();
  const [rows, setRows] = useState<Row[] | null>(null);
  const [immeubles, setImmeubles] = useState<ImmeubleLite[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [immeubleFilter, setImmeubleFilter] = useState<number | "all">("all");
  const [statutFilter, setStatutFilter] = useState<string>("all");

  // « + Ajouter un logement » (même modale que la fiche immeuble) : on
  // choisit d'abord l'immeuble, puis la modale LogementFiche s'ouvre.
  const [chooserOpen, setChooserOpen] = useState(false);
  const [addImmId, setAddImmId] = useState("");
  const [showCreate, setShowCreate] = useState(false);

  // Clic sur le NUMÉRO → page fiche logement (vraie page 360). Le reste
  // de la ligne ne navigue plus : il sert à éditer / sélectionner.
  function openFiche(row: Row) {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    router.push(`/immobilier/logements/${row.id}` as any);
  }

  // Édition en ligne + sélection multiple (Phil 2026-10-03) : modifier
  // ou supprimer directement depuis cette page, sans ouvrir chaque fiche.
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [editingId, setEditingId] = useState<number | null>(null);
  const [draft, setDraft] = useState({
    immeuble_id: "",
    numero: "",
    type: "residentiel",
    pieces: "",
    loyer: "",
    chambres: false
  });
  const [busyId, setBusyId] = useState<number | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [showLot, setShowLot] = useState(false);
  const [lotBusy, setLotBusy] = useState(false);

  const numeroDe = (id: number) =>
    rows?.find((x) => x.id === id)?.numero ?? `#${id}`;

  function startEdit(l: Row) {
    setEditingId(l.id);
    setMsg(null);
    setDraft({
      immeuble_id: String(l.immeuble_id),
      numero: l.numero,
      type: l.type || "residentiel",
      pieces: l.nb_pieces_decimal != null ? String(l.nb_pieces_decimal) : "",
      loyer: l.loyer_demande != null ? String(l.loyer_demande) : "",
      chambres: !!l.location_en_chambres
    });
  }

  async function patchLogement(
    id: number,
    body: Record<string, unknown>
  ): Promise<string | null> {
    const res = await patchLogementApi(id, body);
    if (res.error !== null) return res.error;
    const saved = res.saved;
    // L'immeuble a pu changer : on recolle son nom / son mode de gestion.
    const imm = immeubles.find((i) => i.id === saved.immeuble_id);
    setRows((prev) =>
      prev?.map((x) =>
        x.id === id
          ? {
              ...x,
              ...saved,
              immeuble_name: imm?.name ?? x.immeuble_name,
              immeuble_gestion_externe: imm
                ? !!imm.gestion_externe
                : x.immeuble_gestion_externe
            }
          : x
      ) ?? prev
    );
    return null;
  }

  async function supprimerLogement(id: number): Promise<string | null> {
    const err = await supprimerLogementApi(id);
    if (err) return err;
    setRows((prev) => prev?.filter((x) => x.id !== id) ?? prev);
    setSelected((s) => {
      const n = new Set(s);
      n.delete(id);
      return n;
    });
    return null;
  }

  async function saveEdit() {
    if (editingId == null) return;
    if (!draft.numero.trim()) {
      setMsg("Le numéro est requis.");
      return;
    }
    setBusyId(editingId);
    setMsg(null);
    const err = await patchLogement(editingId, {
      immeuble_id: Number(draft.immeuble_id),
      numero: draft.numero.trim(),
      type: draft.type,
      nb_pieces_decimal: numOuNull(draft.pieces),
      loyer_demande: numOuNull(draft.loyer),
      location_en_chambres: draft.chambres
    });
    setBusyId(null);
    if (err) setMsg(`${draft.numero} : ${err}`);
    else setEditingId(null);
  }

  async function deleteOne(l: Row) {
    if (!window.confirm(`Supprimer le logement ${l.numero} (${l.immeuble_name}) ?`))
      return;
    setBusyId(l.id);
    setMsg(null);
    const err = await supprimerLogement(l.id);
    setBusyId(null);
    if (err) setMsg(`${l.numero} gardé : ${err}`);
  }

  async function deleteSelected() {
    const cibles = (rows ?? []).filter((l) => selected.has(l.id));
    if (!cibles.length) return;
    if (
      !window.confirm(
        `Supprimer ${cibles.length} logement(s) : ${cibles
          .map((l) => l.numero)
          .join(", ")} ?\nCeux qui ont un bail seront gardés.`
      )
    )
      return;
    setLotBusy(true);
    setMsg(null);
    const gardes: string[] = [];
    let ok = 0;
    for (const l of cibles) {
      const err = await supprimerLogement(l.id);
      if (err) gardes.push(`${l.numero} gardé : ${err}`);
      else ok++;
    }
    setLotBusy(false);
    setMsg([`${ok} supprimé(s).`, ...gardes].join(" · "));
  }

  async function applyLot(body: Record<string, unknown>) {
    const ids = Array.from(selected);
    setLotBusy(true);
    setMsg(null);
    const errs: string[] = [];
    let ok = 0;
    for (const id of ids) {
      const err = await patchLogement(id, body);
      if (err) errs.push(`${numeroDe(id)} : ${err}`);
      else ok++;
    }
    setLotBusy(false);
    setShowLot(false);
    setMsg([`${ok} modifié(s).`, ...errs].join(" · "));
  }

  // Jeton anti-course : seul le chargement le plus récent écrit l'état
  // (changement d'entreprise rapide, rechargement après création).
  const loadToken = useRef(0);
  const load = useCallback(async () => {
    const token = ++loadToken.current;
    setRows(null);
    setError(null);
    try {
      const url =
        currentEntrepriseId != null
          ? `/api/v1/immobilier/immeubles?entreprise_id=${currentEntrepriseId}`
          : "/api/v1/immobilier/immeubles";
      const res = await authedFetch(url);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const imms = (await res.json()) as ImmeubleLite[];
      if (token !== loadToken.current) return;
      setImmeubles(imms);

      const lists = await Promise.all(
        imms.map(async (imm) => {
          const r = await authedFetch(
            `/api/v1/immobilier/immeubles/${imm.id}/logements`
          );
          if (!r.ok) return [] as Row[];
          const logs = (await r.json()) as Logement[];
          return logs.map((l) => ({
            ...l,
            immeuble_name: imm.name,
            immeuble_gestion_externe: !!imm.gestion_externe
          }));
        })
      );
      if (token !== loadToken.current) return;
      setRows(lists.flat());
    } catch (err) {
      if (token === loadToken.current)
        setError((err as Error).message);
    }
  }, [currentEntrepriseId]);

  useEffect(() => {
    setImmeubleFilter("all");
    void load();
  }, [load]);

  const filtered = useMemo(() => {
    if (rows === null) return null;
    const q = search.trim().toLowerCase();
    return rows.filter((r) => {
      if (immeubleFilter !== "all" && r.immeuble_id !== immeubleFilter)
        return false;
      if (statutFilter !== "all" && r.status !== statutFilter) return false;
      if (q) {
        const hay = `${r.numero} ${r.immeuble_name} ${r.type}`.toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });
  }, [rows, search, immeubleFilter, statutFilter]);

  return (
    <>
      <ImmobilierTopbar
        breadcrumbs={[
          { label: "Gestion immobilière", href: "/immobilier" },
          { label: "Logements" }
        ]}
      />

      <div className="p-4 lg:p-6">
        <DoublonsLogementsBanner />
        <header className="flex flex-wrap items-start justify-between gap-3">
          <div className="flex items-start gap-3">
            <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-accent-500/15 text-accent-500">
              <DoorOpen className="h-5 w-5" />
            </span>
            <div>
              <h1 className="text-2xl font-bold text-white">Logements</h1>
              <p className="mt-1 max-w-2xl text-sm text-white/60">
                Tous les logements du portefeuille, tous immeubles confondus —
                statut, pièces et loyer en un coup d&apos;œil (loyer du bail
                si occupé, loyer demandé si vacant).
              </p>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <BoutonExport
              cibles={[
                {
                  base: "/api/v1/immobilier/exports/logements",
                  sujet: "logements",
                  params: {
                    immeuble_id:
                      immeubleFilter !== "all" ? immeubleFilter : undefined
                  }
                }
              ]}
            />
            <button
              type="button"
              onClick={() => {
                setAddImmId(
                  immeubleFilter !== "all" ? String(immeubleFilter) : ""
                );
                setChooserOpen(true);
              }}
              className="btn-outline-accent btn-sm"
            >
              <Plus className="h-3.5 w-3.5" /> Ajouter un logement
            </button>
          </div>
        </header>

        {/* Filtres */}
        <div className="mt-5 flex flex-wrap items-center gap-2">
          <div className="relative max-w-md flex-1">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-white/40" />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Recherche n° de logement / immeuble…"
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
          >
            <option value="all">Tous les immeubles</option>
            {immeubles.map((imm) => (
              <option key={imm.id} value={imm.id}>
                {imm.name}
              </option>
            ))}
          </select>
          {STATUTS.map((s) => (
            <FilterPill
              key={s.value}
              label={s.label}
              active={statutFilter === s.value}
              onClick={() => setStatutFilter(s.value)}
            />
          ))}
          {filtered ? (
            <span className="text-xs text-white/50">
              {filtered.length} / {rows?.length || 0}
            </span>
          ) : null}
        </div>

        {error ? (
          <p className="mt-4 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
            <AlertTriangle className="mr-1.5 inline h-3.5 w-3.5" />
            {error}
          </p>
        ) : null}

        {selected.size > 0 ? (
          <div className="mt-4 flex flex-wrap items-center gap-2 rounded-xl border border-accent-500/40 bg-accent-500/10 px-3 py-2 text-xs text-white">
            <span className="font-semibold">
              {selected.size} sélectionné{selected.size > 1 ? "s" : ""}
            </span>
            <button
              type="button"
              onClick={() => setShowLot(true)}
              disabled={lotBusy}
              className="btn-outline-accent btn-xs"
            >
              <Pencil className="h-3 w-3" /> Modifier en lot
            </button>
            <button
              type="button"
              onClick={() => void deleteSelected()}
              disabled={lotBusy}
              className="btn-outline-rose btn-xs"
            >
              {lotBusy ? (
                <Loader2 className="h-3 w-3 animate-spin" />
              ) : (
                <Trash2 className="h-3 w-3" />
              )}{" "}
              Supprimer
            </button>
            <button
              type="button"
              onClick={() => setSelected(new Set())}
              className="btn-ghost btn-xs"
            >
              Tout désélectionner
            </button>
          </div>
        ) : null}
        {msg ? (
          <p className="mt-3 rounded-lg border border-brand-800 bg-brand-900 px-3 py-2 text-xs text-white">
            {msg}
          </p>
        ) : null}

        {filtered === null ? (
          <p className="mt-4 text-xs text-white/50">
            <Loader2 className="mr-1 inline h-3 w-3 animate-spin" />{" "}
            Chargement…
          </p>
        ) : filtered.length === 0 ? (
          <p className="mt-4 rounded-lg border border-brand-800 bg-brand-900 px-4 py-3 text-sm text-white/60">
            Aucun logement{" "}
            {rows && rows.length > 0
              ? "correspondant aux filtres"
              : "dans le portefeuille"}
            .
          </p>
        ) : (
          <div className="mt-4 overflow-hidden rounded-2xl border border-brand-800 bg-brand-900">
            <div className="overflow-x-auto">
              <table className="w-full min-w-[820px] text-left text-sm">
                <thead className="border-b border-brand-800 bg-brand-950 text-[10px] uppercase tracking-wider text-white/50">
                  <tr>
                    <th className="w-8 py-2.5 pl-3">
                      <input
                        type="checkbox"
                        checked={
                          filtered.length > 0 &&
                          filtered.every((l) => selected.has(l.id))
                        }
                        onChange={(e) =>
                          setSelected(
                            e.target.checked
                              ? new Set(filtered.map((l) => l.id))
                              : new Set()
                          )
                        }
                        aria-label="Tout sélectionner (lignes filtrées)"
                        className="h-3.5 w-3.5 accent-accent-500"
                      />
                    </th>
                    <th className="px-3 py-2.5">Logement</th>
                    <th className="px-3 py-2.5">Immeuble</th>
                    <th className="px-3 py-2.5">Type</th>
                    <th className="px-3 py-2.5">Pièces</th>
                    <th className="px-3 py-2.5 text-right">Loyer</th>
                    <th className="px-3 py-2.5 text-right">Statut</th>
                    <th className="w-24 px-3 py-2.5 text-right">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-brand-800">
                  {filtered.map((l) => {
                    const editing = editingId === l.id;
                    const busy = busyId === l.id;
                    return (
                    <tr
                      key={l.id}
                      className={`group transition ${
                        selected.has(l.id)
                          ? "bg-accent-500/10"
                          : editing
                            ? "bg-brand-950/60"
                            : "hover:bg-brand-800/40"
                      }`}
                    >
                      <td className="py-3 pl-3 align-middle">
                        <input
                          type="checkbox"
                          checked={selected.has(l.id)}
                          onChange={(e) =>
                            setSelected((sel) => {
                              const n = new Set(sel);
                              if (e.target.checked) n.add(l.id);
                              else n.delete(l.id);
                              return n;
                            })
                          }
                          aria-label={`Sélectionner ${l.numero}`}
                          className="h-3.5 w-3.5 accent-accent-500"
                        />
                      </td>
                      <td className="px-3 py-3">
                        <span className="flex items-center gap-3">
                          <span className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-lg bg-accent-500/15 text-accent-500">
                            <DoorOpen className="h-4 w-4" />
                          </span>
                          {editing ? (
                            <input
                              value={draft.numero}
                              onChange={(e) =>
                                setDraft((d) => ({ ...d, numero: e.target.value }))
                              }
                              className="input w-32 px-2 py-1 text-xs font-bold"
                              aria-label="Numéro"
                            />
                          ) : (
                            <button
                              type="button"
                              onClick={() => openFiche(l)}
                              className="rounded px-0.5 text-left font-bold text-white hover:text-accent-500 hover:underline"
                              title="Ouvrir la fiche du logement"
                            >
                              {l.numero}
                            </button>
                          )}
                        </span>
                      </td>
                      <td className="px-3 py-3 text-xs text-white/70">
                        {editing ? (
                          <select
                            value={draft.immeuble_id}
                            onChange={(e) =>
                              setDraft((d) => ({ ...d, immeuble_id: e.target.value }))
                            }
                            className="input w-56 px-2 py-1 text-xs"
                            aria-label="Immeuble"
                            title="Déplacer ce logement vers un autre immeuble"
                          >
                            {immeubles.map((im) => (
                              <option key={im.id} value={im.id} className="bg-brand-950 text-white">
                                {im.name}
                              </option>
                            ))}
                          </select>
                        ) : (
                        <Link
                          // eslint-disable-next-line @typescript-eslint/no-explicit-any
                          href={`/immobilier/immeubles/${l.immeuble_id}` as any}
                          className="inline-flex items-center gap-1.5 hover:text-accent-500"
                        >
                          <Building2 className="h-3.5 w-3.5 text-white/40" />
                          {l.immeuble_name}
                        </Link>
                        )}
                        {l.immeuble_gestion_externe ? (
                          <span className="ml-1.5 badge badge-sky">
                            Gestion externe
                          </span>
                        ) : null}
                      </td>
                      <td className="px-3 py-3 text-xs text-white/60">
                        {editing ? (
                          <select
                            value={draft.type}
                            onChange={(e) =>
                              setDraft((d) => ({ ...d, type: e.target.value }))
                            }
                            className="input w-36 px-2 py-1 text-xs"
                            aria-label="Type"
                          >
                            {LOGEMENT_TYPES.map(([val, lab]) => (
                              <option key={val} value={val} className="bg-brand-950 text-white">
                                {lab}
                              </option>
                            ))}
                          </select>
                        ) : (
                          l.type
                        )}
                      </td>
                      <td className="px-3 py-3 font-mono text-xs text-white/70">
                        {editing ? (
                          <div className="flex items-center gap-2">
                            <input
                              type="number"
                              step="0.5"
                              min="0"
                              value={draft.pieces}
                              disabled={draft.chambres}
                              onChange={(e) =>
                                setDraft((d) => ({ ...d, pieces: e.target.value }))
                              }
                              className="input w-16 px-2 py-1 text-xs disabled:opacity-50"
                              aria-label="Pièces"
                            />
                            <label className="inline-flex cursor-pointer items-center gap-1 whitespace-nowrap font-sans text-white">
                              <input
                                type="checkbox"
                                checked={draft.chambres}
                                onChange={(e) =>
                                  setDraft((d) => ({
                                    ...d,
                                    chambres: e.target.checked
                                  }))
                                }
                                className="h-3.5 w-3.5 accent-accent-500"
                              />
                              Chambre ∞
                            </label>
                          </div>
                        ) : l.location_en_chambres ? (
                          <span
                            title={LOUER_INDEFINIMENT_INFO}
                            className="cursor-help border-b border-dotted border-white/25"
                          >
                            Chambre ∞
                          </span>
                        ) : (
                          fmtPieces(l.nb_pieces_decimal)
                        )}
                      </td>
                      <td
                        className="px-3 py-3 text-right font-mono text-xs text-white/80"
                        title={
                          l.immeuble_gestion_externe
                            ? "Loyer saisi sur le logement (gestion externe)"
                            : l.status === "occupe"
                              ? "Loyer du bail actif"
                              : "Loyer demandé (prix de la prochaine location)"
                        }
                      >
                        {editing ? (
                          <input
                            type="number"
                            min="0"
                            step="1"
                            value={draft.loyer}
                            onChange={(e) =>
                              setDraft((d) => ({ ...d, loyer: e.target.value }))
                            }
                            className="input ml-auto w-24 px-2 py-1 text-right text-xs"
                            aria-label="Loyer demandé"
                          />
                        ) : (
                          <>
                            {/* Hiérarchie du loyer effectif (2026-08-14) :
                                externe → loyer SAISI ; interne occupé →
                                loyer RÉEL du bail ; vacant → demandé. */}
                            {fmtMoney(
                              !l.immeuble_gestion_externe &&
                                l.status === "occupe"
                                ? (l.loyer_actuel ?? l.loyer_demande)
                                : l.loyer_demande
                            )}
                            {!l.immeuble_gestion_externe &&
                            l.status !== "occupe" &&
                            l.loyer_demande != null ? (
                              <span className="ml-1 text-white/40">
                                demandé
                              </span>
                            ) : null}
                          </>
                        )}
                      </td>
                      <td className="px-3 py-3 text-right">
                        <StatutBadge status={l.status} libreLe={l.libre_le} />
                      </td>
                      <td className="px-3 py-3 text-right">
                        {busy ? (
                          <Loader2 className="ml-auto h-4 w-4 animate-spin text-accent-500" />
                        ) : editing ? (
                          <span className="inline-flex gap-1">
                            <button
                              type="button"
                              onClick={() => void saveEdit()}
                              className="btn-accent btn-xs"
                              title="Enregistrer"
                              aria-label="Enregistrer"
                            >
                              <Check className="h-3.5 w-3.5" />
                            </button>
                            <button
                              type="button"
                              onClick={() => setEditingId(null)}
                              className="btn-ghost btn-xs"
                              title="Annuler"
                              aria-label="Annuler"
                            >
                              <X className="h-3.5 w-3.5" />
                            </button>
                          </span>
                        ) : (
                          <span className="inline-flex gap-1">
                            <button
                              type="button"
                              onClick={() => startEdit(l)}
                              className="btn-ghost btn-xs"
                              title="Modifier sur place"
                              aria-label={`Modifier ${l.numero}`}
                            >
                              <Pencil className="h-3.5 w-3.5" />
                            </button>
                            <button
                              type="button"
                              onClick={() => void deleteOne(l)}
                              className="btn-ghost btn-xs hover:bg-rose-500/15 hover:text-rose-400"
                              title="Supprimer ce logement"
                              aria-label={`Supprimer ${l.numero}`}
                            >
                              <Trash2 className="h-3.5 w-3.5" />
                            </button>
                          </span>
                        )}
                      </td>
                    </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>

      {/* Choix de l'immeuble AVANT la modale de création (la fiche
          logement a besoin de savoir où le créer). */}
      {chooserOpen ? (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
          onClick={() => setChooserOpen(false)}
        >
          <div
            className="w-full max-w-sm rounded-2xl border border-brand-800 bg-brand-900 p-5 shadow-card"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="mb-3 flex items-start justify-between gap-3">
              <h3 className="text-base font-bold text-white">
                Ajouter un logement
              </h3>
              <button
                type="button"
                className="rounded-lg p-1.5 text-white/40 hover:text-white"
                onClick={() => setChooserOpen(false)}
              >
                <X className="h-4 w-4" />
              </button>
            </div>
            <label className="text-xs font-medium text-white/60">
              Immeuble
            </label>
            <select
              value={addImmId}
              onChange={(e) => setAddImmId(e.target.value)}
              className="input mt-1 w-full"
            >
              <option value="">Choisir…</option>
              {immeubles.map((imm) => (
                <option key={imm.id} value={String(imm.id)}>
                  {imm.name}
                </option>
              ))}
            </select>
            <button
              type="button"
              disabled={!addImmId}
              onClick={() => {
                setChooserOpen(false);
                setShowCreate(true);
              }}
              className="btn-accent btn-sm mt-4 w-full justify-center disabled:opacity-50"
            >
              <Plus className="h-4 w-4" /> Continuer
            </button>
          </div>
        </div>
      ) : null}

      {showCreate && addImmId ? (
        <LogementFiche
          logement={null}
          immeubleId={Number(addImmId)}
          onClose={() => setShowCreate(false)}
          onSaved={() => {
            setShowCreate(false);
            void load();
          }}
          onSavedMany={() => {
            setShowCreate(false);
            void load();
          }}
          onDeleted={() => {
            setShowCreate(false);
            void load();
          }}
        />
      ) : null}
      {showLot ? (
        <LogementsLotModal
          count={selected.size}
          busy={lotBusy}
          onClose={() => setShowLot(false)}
          onApply={(body) => void applyLot(body)}
          immeubles={immeubles.map((im) => ({ id: im.id, name: im.name }))}
        />
      ) : null}
    </>
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
