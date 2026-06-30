"use client";

import { useEffect, useMemo, useState } from "react";
import {
  Building2,
  ChevronDown,
  ChevronRight,
  Hammer,
  Loader2,
  Pencil,
  Plus,
  X
} from "lucide-react";

import { Link } from "@/i18n/navigation";
import { authedFetch } from "@/lib/auth";
import { ImmobilierTopbar, useImmobilierLayout } from "../layout";

type ImmeubleListItem = {
  id: number;
  name: string;
  address: string;
  city?: string | null;
};

type Logement = {
  id: number;
  numero: string;
  status: string;
};

type BonResult = {
  bon_id: number;
  reference: string;
  client_name: string | null;
  client_created: boolean;
};

type BonProject = {
  id: number;
  label: string;
  status: string | null;
  progress_pct: number;
};

type BonListItem = {
  id: number;
  reference: string;
  title: string;
  status: string;
  created_at: string | null;
  client_name: string | null;
  project: BonProject | null;
  address: string | null;
  amount: number | null;
  immeuble_id: number | null;
  logement_id: number | null;
};

type RollupLogement = {
  logement_id: number | null;
  numero: string | null;
  total: number;
  count: number;
};

type RollupImmeuble = {
  immeuble_id: number;
  name: string;
  address: string | null;
  total: number;
  count: number;
  communs_total: number;
  logements: RollupLogement[];
};

type Column = { id: string; label: string; dot: string };
const COLUMNS: Column[] = [
  { id: "draft", label: "Brouillon", dot: "bg-white/40" },
  { id: "accepte_a_planifier", label: "Accepté à planifier", dot: "bg-amber-400" },
  { id: "planifie", label: "Planifié", dot: "bg-blue-400" },
  {
    id: "complete_a_refacturer",
    label: "Complété · à refacturer",
    dot: "bg-violet-400"
  },
  { id: "facture", label: "Facturé", dot: "bg-emerald-400" },
  { id: "cancelled", label: "Annulé", dot: "bg-white/20" }
];
const STATUS_LABEL: Record<string, string> = Object.fromEntries(
  COLUMNS.map((c) => [c.id, c.label])
);
// Statuts legacy encore possibles sur d'anciens bons.
STATUS_LABEL.sent = "Envoyé";
STATUS_LABEL.signed = "Signé";

function money(n: number | null | undefined): string {
  if (n == null) return "—";
  return new Intl.NumberFormat("fr-CA", {
    style: "currency",
    currency: "CAD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2
  }).format(n);
}

export default function BonsTravailPage() {
  const { currentEntrepriseId } = useImmobilierLayout();
  const [immeubles, setImmeubles] = useState<ImmeubleListItem[] | null>(null);
  const [immeubleId, setImmeubleId] = useState<number | "">("");
  const [logements, setLogements] = useState<Logement[]>([]);
  const [logementId, setLogementId] = useState<string>("");
  const [titre, setTitre] = useState("");
  const [description, setDescription] = useState("");
  const [photoFile, setPhotoFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<BonResult | null>(null);
  const [formOpen, setFormOpen] = useState(false);

  const [bons, setBons] = useState<BonListItem[] | null>(null);
  const [rollup, setRollup] = useState<RollupImmeuble[]>([]);
  const [expanded, setExpanded] = useState<Set<number>>(new Set());

  // Édition de la demande (titre / description).
  const [editBon, setEditBon] = useState<BonListItem | null>(null);
  const [editTitre, setEditTitre] = useState("");
  const [editDesc, setEditDesc] = useState("");
  const [editBusy, setEditBusy] = useState(false);

  async function loadBons() {
    try {
      const r = await authedFetch("/api/v1/immobilier/bons-travail");
      if (r.ok) setBons((await r.json()) as BonListItem[]);
    } catch {
      /* ignore */
    }
  }
  async function loadRollup() {
    try {
      const r = await authedFetch("/api/v1/immobilier/maintenance-rollup");
      if (r.ok) setRollup((await r.json()) as RollupImmeuble[]);
    } catch {
      /* ignore */
    }
  }

  useEffect(() => {
    void loadBons();
    void loadRollup();
  }, []);

  // Immeubles de la compagnie active.
  useEffect(() => {
    let cancelled = false;
    setImmeubles(null);
    setImmeubleId("");
    (async () => {
      const url =
        currentEntrepriseId != null
          ? `/api/v1/immobilier/immeubles?entreprise_id=${currentEntrepriseId}`
          : "/api/v1/immobilier/immeubles";
      try {
        const r = await authedFetch(url);
        if (r.ok && !cancelled)
          setImmeubles((await r.json()) as ImmeubleListItem[]);
      } catch {
        /* ignore */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [currentEntrepriseId]);

  // Logements de l'immeuble sélectionné.
  useEffect(() => {
    setLogements([]);
    setLogementId("");
    if (immeubleId === "") return;
    let cancelled = false;
    (async () => {
      try {
        const r = await authedFetch(
          `/api/v1/immobilier/immeubles/${immeubleId}/logements`
        );
        if (r.ok && !cancelled) setLogements((await r.json()) as Logement[]);
      } catch {
        /* ignore */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [immeubleId]);

  const selectedImmeuble = useMemo(
    () => (immeubles || []).find((i) => i.id === immeubleId) || null,
    [immeubles, immeubleId]
  );

  async function createBon() {
    if (immeubleId === "" || !titre.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const r = await authedFetch(
        `/api/v1/immobilier/immeubles/${immeubleId}/bon-travail`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            titre: titre.trim(),
            description: description.trim() || null,
            logement_id: logementId ? Number(logementId) : null
          })
        }
      );
      if (!r.ok)
        throw new Error((await r.text()).slice(0, 200) || `HTTP ${r.status}`);
      const res = (await r.json()) as BonResult;
      if (photoFile) {
        try {
          const fd = new FormData();
          fd.append("file", photoFile);
          await authedFetch(
            `/api/v1/immobilier/bons-travail/${res.bon_id}/photos`,
            { method: "POST", body: fd }
          );
        } catch {
          /* photo optionnelle */
        }
      }
      setResult(res);
      setTitre("");
      setDescription("");
      setLogementId("");
      setPhotoFile(null);
      setFormOpen(false);
      void loadBons();
      void loadRollup();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  function openEdit(b: BonListItem) {
    setEditBon(b);
    setEditTitre(b.title);
    setEditDesc("");
    setError(null);
  }
  async function saveEdit() {
    if (!editBon) return;
    setEditBusy(true);
    try {
      const r = await authedFetch(
        `/api/v1/immobilier/bons-travail/${editBon.id}/demande`,
        {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            titre: editTitre.trim() || null,
            description: editDesc.trim() ? editDesc.trim() : null
          })
        }
      );
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      setEditBon(null);
      void loadBons();
    } catch {
      setError("Modification de la demande échouée.");
    } finally {
      setEditBusy(false);
    }
  }

  const byColumn = useMemo(() => {
    const map: Record<string, BonListItem[]> = Object.fromEntries(
      COLUMNS.map((c) => [c.id, [] as BonListItem[]])
    );
    for (const b of bons || []) {
      const target = COLUMNS.find((c) => c.id === b.status) ? b.status : "draft";
      map[target].push(b);
    }
    return map;
  }, [bons]);

  function toggleExpand(id: number) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  return (
    <>
      <ImmobilierTopbar
        breadcrumbs={[
          { label: "Gestion immobilière", href: "/immobilier" },
          { label: "Bons de travail" }
        ]}
      />
      <div className="p-4 lg:p-6">
        <header className="flex items-start justify-between gap-3">
          <div className="flex items-start gap-3">
            <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-amber-500/15 text-amber-300">
              <Hammer className="h-5 w-5" />
            </span>
            <div>
              <h1 className="text-2xl font-bold text-white">Bons de travail</h1>
              <p className="mt-1 max-w-2xl text-sm text-white/60">
                Entretien de nos immeubles. Crée une demande de réparation ;
                Construction la planifie, l&apos;exécute et la refacture. Tu
                suis l&apos;avancement ici (lecture seule).
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={() => setFormOpen((v) => !v)}
            className="inline-flex flex-shrink-0 items-center gap-2 rounded-lg border border-amber-400/30 bg-amber-500/15 px-3 py-2 text-sm font-semibold text-amber-100 hover:bg-amber-500/25"
          >
            <Plus className="h-4 w-4" /> Nouvelle demande
          </button>
        </header>

        {formOpen ? (
          <section className="mt-6 max-w-xl space-y-3 rounded-2xl border border-brand-800 bg-brand-900 p-5">
            <Field label="Immeuble *">
              <select
                value={immeubleId}
                onChange={(e) =>
                  setImmeubleId(e.target.value ? Number(e.target.value) : "")
                }
                className="w-full rounded-lg border border-brand-800 bg-brand-950 px-3 py-2 text-sm text-white outline-none focus:border-amber-300"
              >
                <option value="">— choisir un immeuble —</option>
                {(immeubles || []).map((i) => (
                  <option key={i.id} value={i.id}>
                    {i.name}
                    {i.city ? ` — ${i.city}` : ""}
                  </option>
                ))}
              </select>
            </Field>

            <Field label="Logement / appartement">
              <select
                value={logementId}
                onChange={(e) => setLogementId(e.target.value)}
                disabled={immeubleId === "" || logements.length === 0}
                className="w-full rounded-lg border border-brand-800 bg-brand-950 px-3 py-2 text-sm text-white outline-none focus:border-amber-300 disabled:opacity-50"
              >
                <option value="">
                  {immeubleId === ""
                    ? "— choisis d'abord un immeuble —"
                    : logements.length === 0
                      ? "— aucun logement (optionnel) —"
                      : "— immeuble entier / communs —"}
                </option>
                {logements.map((l) => (
                  <option key={l.id} value={String(l.id)}>
                    {l.numero} ({l.status})
                  </option>
                ))}
              </select>
            </Field>

            <Field label="Titre des travaux *">
              <input
                value={titre}
                onChange={(e) => setTitre(e.target.value)}
                placeholder="Ex. Réparation toiture"
                className="w-full rounded-lg border border-brand-800 bg-brand-950 px-3 py-2 text-sm text-white outline-none focus:border-amber-300"
              />
            </Field>

            <Field label="Description">
              <textarea
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                rows={4}
                placeholder="Détails des travaux…"
                className="w-full rounded-lg border border-brand-800 bg-brand-950 px-3 py-2 text-sm text-white outline-none focus:border-amber-300"
              />
            </Field>

            <Field label="Photo de la problématique (avant)">
              <input
                type="file"
                accept="image/*,application/pdf"
                onChange={(e) => setPhotoFile(e.target.files?.[0] || null)}
                className="block w-full text-sm text-white/70 file:mr-3 file:rounded-lg file:border-0 file:bg-amber-500/15 file:px-3 file:py-2 file:text-sm file:font-semibold file:text-amber-100 hover:file:bg-amber-500/25"
              />
            </Field>

            {error ? (
              <p className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">
                {error}
              </p>
            ) : null}

            <button
              type="button"
              onClick={() => void createBon()}
              disabled={busy || immeubleId === "" || !titre.trim()}
              className="inline-flex items-center gap-2 rounded-lg border border-amber-400/30 bg-amber-500/15 px-4 py-2 text-sm font-semibold text-amber-100 hover:bg-amber-500/25 disabled:opacity-50"
            >
              {busy ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Hammer className="h-4 w-4" />
              )}
              Créer la demande
            </button>

            {selectedImmeuble ? (
              <p className="text-[11px] text-white/40">
                Pour : {selectedImmeuble.address}
                {selectedImmeuble.city ? `, ${selectedImmeuble.city}` : ""}
              </p>
            ) : null}
          </section>
        ) : null}

        {result ? (
          <div className="mt-4 max-w-xl rounded-2xl border border-emerald-500/40 bg-emerald-500/10 p-4 text-sm text-emerald-200">
            <p className="font-semibold">Demande {result.reference} créée ✅</p>
            <p className="mt-1 text-xs">
              Envoyée dans le volet Construction (brouillon).
            </p>
          </div>
        ) : null}

        {/* ── Dépenses de maintenance (roll-up) ─────────────────────── */}
        {rollup.length > 0 ? (
          <section className="mt-8">
            <h2 className="text-lg font-bold text-white">
              Dépenses de maintenance — année en cours
            </h2>
            <p className="mt-1 text-xs text-white/50">
              Montant refacturé par immeuble puis par appartement (sans profit).
            </p>
            <div className="mt-4 grid gap-3 lg:grid-cols-2">
              {rollup.map((r) => {
                const open = expanded.has(r.immeuble_id);
                return (
                  <div
                    key={r.immeuble_id}
                    className="rounded-2xl border border-brand-800 bg-brand-900 p-4"
                  >
                    <button
                      type="button"
                      onClick={() => toggleExpand(r.immeuble_id)}
                      className="flex w-full items-center justify-between gap-2 text-left"
                    >
                      <span className="flex min-w-0 items-center gap-2">
                        {open ? (
                          <ChevronDown className="h-4 w-4 flex-shrink-0 text-white/50" />
                        ) : (
                          <ChevronRight className="h-4 w-4 flex-shrink-0 text-white/50" />
                        )}
                        <Building2 className="h-4 w-4 flex-shrink-0 text-amber-300" />
                        <span className="min-w-0">
                          <span className="block truncate text-sm font-semibold text-white">
                            {r.name}
                          </span>
                          <span className="block truncate text-[11px] text-white/40">
                            {r.count} bon{r.count > 1 ? "s" : ""}
                          </span>
                        </span>
                      </span>
                      <span className="flex-shrink-0 text-right">
                        <span className="block text-base font-bold text-amber-200">
                          {money(r.total)}
                        </span>
                      </span>
                    </button>
                    {open ? (
                      <div className="mt-3 space-y-1 border-t border-brand-800 pt-3 text-sm">
                        {r.logements.map((l) => (
                          <div
                            key={l.logement_id ?? "communs"}
                            className="flex items-center justify-between text-white/70"
                          >
                            <span>App {l.numero || "—"}</span>
                            <span className="text-white">{money(l.total)}</span>
                          </div>
                        ))}
                        {r.communs_total > 0 ? (
                          <div className="flex items-center justify-between text-white/70">
                            <span>Communs / immeuble entier</span>
                            <span className="text-white">
                              {money(r.communs_total)}
                            </span>
                          </div>
                        ) : null}
                      </div>
                    ) : null}
                  </div>
                );
              })}
            </div>
          </section>
        ) : null}

        {/* ── Suivi (kanban lecture seule) ──────────────────────────── */}
        <section className="mt-8">
          <h2 className="text-lg font-bold text-white">
            Suivi des bons de travail
          </h2>
          <p className="mt-1 max-w-2xl text-xs text-white/50">
            Avancement géré par Construction (lecture seule). Tu peux corriger
            la demande si tu t&apos;es trompé.
          </p>

          {bons === null ? (
            <div className="mt-4 flex items-center gap-2 text-sm text-white/50">
              <Loader2 className="h-4 w-4 animate-spin" /> Chargement…
            </div>
          ) : bons.length === 0 ? (
            <p className="mt-4 rounded-xl border border-dashed border-brand-800 bg-brand-900/40 px-4 py-8 text-center text-sm text-white/50">
              Aucun bon de travail pour l&apos;instant.
            </p>
          ) : (
            <div className="mt-4 flex gap-4 overflow-x-auto pb-4">
              {COLUMNS.map((col) => {
                const cards = byColumn[col.id] || [];
                return (
                  <div
                    key={col.id}
                    className="flex w-72 min-w-[288px] flex-shrink-0 flex-col rounded-xl border border-brand-800 bg-brand-900/60"
                  >
                    <div className="flex items-center justify-between border-b border-brand-800 px-4 py-3">
                      <div className="flex items-center gap-2">
                        <span className={`h-2 w-2 rounded-full ${col.dot}`} />
                        <h3 className="text-sm font-semibold text-white">
                          {col.label}
                        </h3>
                      </div>
                      <span className="rounded-md bg-brand-950 px-2 py-0.5 text-xs font-semibold text-white/70">
                        {cards.length}
                      </span>
                    </div>
                    <div className="flex-1 space-y-3 p-3">
                      {cards.length === 0 ? (
                        <p className="py-6 text-center text-xs text-white/40">
                          —
                        </p>
                      ) : (
                        cards.map((b) => (
                          <div
                            key={b.id}
                            className="rounded-lg border border-brand-800 bg-brand-950 p-3"
                          >
                            <p className="truncate text-sm font-semibold text-white">
                              {b.address || "Adresse non renseignée"}
                            </p>
                            <p className="mt-0.5 truncate text-xs text-white/70">
                              {b.title}
                            </p>
                            <p className="mt-0.5 truncate font-mono text-[10px] text-white/40">
                              {b.reference}
                            </p>
                            {b.project ? (
                              <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-brand-800">
                                <div
                                  className="h-full rounded-full bg-gradient-to-r from-amber-400 to-emerald-400"
                                  style={{ width: `${b.project.progress_pct}%` }}
                                />
                              </div>
                            ) : null}
                            <div className="mt-2 flex items-center justify-between">
                              <button
                                type="button"
                                onClick={() => openEdit(b)}
                                className="inline-flex items-center gap-1 text-[11px] text-white/50 hover:text-amber-200"
                              >
                                <Pencil className="h-3 w-3" /> Corriger
                              </button>
                              <span className="text-xs font-semibold text-white">
                                {money(b.amount)}
                              </span>
                            </div>
                          </div>
                        ))
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </section>
      </div>

      {editBon ? (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4"
          onClick={() => (!editBusy ? setEditBon(null) : null)}
        >
          <div
            className="w-full max-w-lg rounded-2xl border border-brand-800 bg-brand-950 p-6"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between">
              <h3 className="text-lg font-bold text-white">
                Corriger la demande
              </h3>
              <button
                type="button"
                onClick={() => setEditBon(null)}
                className="text-white/50 hover:text-white"
              >
                <X className="h-5 w-5" />
              </button>
            </div>
            <p className="mt-1 text-xs text-white/50">
              {editBon.reference} — {STATUS_LABEL[editBon.status] || editBon.status}
            </p>
            <div className="mt-4 space-y-4">
              <Field label="Titre">
                <input
                  value={editTitre}
                  onChange={(e) => setEditTitre(e.target.value)}
                  className="w-full rounded-lg border border-brand-800 bg-brand-900 px-3 py-2 text-sm text-white outline-none focus:border-amber-300"
                />
              </Field>
              <Field label="Nouvelle description (laisse vide pour ne pas changer)">
                <textarea
                  value={editDesc}
                  onChange={(e) => setEditDesc(e.target.value)}
                  rows={4}
                  className="w-full rounded-lg border border-brand-800 bg-brand-900 px-3 py-2 text-sm text-white outline-none focus:border-amber-300"
                />
              </Field>
            </div>
            <div className="mt-5 flex items-center justify-between">
              <Link
                // eslint-disable-next-line @typescript-eslint/no-explicit-any
                href={`/app/bons/${editBon.id}` as any}
                className="text-xs text-white/50 underline hover:text-white"
              >
                Voir dans Construction →
              </Link>
              <div className="flex items-center gap-3">
                <button
                  type="button"
                  onClick={() => setEditBon(null)}
                  disabled={editBusy}
                  className="rounded-lg border border-brand-700 px-3 py-2 text-sm text-white/80 hover:bg-brand-900"
                >
                  Annuler
                </button>
                <button
                  type="button"
                  onClick={() => void saveEdit()}
                  disabled={editBusy || !editTitre.trim()}
                  className="inline-flex items-center gap-2 rounded-lg border border-amber-400/30 bg-amber-500/15 px-4 py-2 text-sm font-semibold text-amber-100 hover:bg-amber-500/25 disabled:opacity-50"
                >
                  {editBusy ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : null}
                  Enregistrer
                </button>
              </div>
            </div>
          </div>
        </div>
      ) : null}
    </>
  );
}

function Field({
  label,
  children
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-medium text-white/60">
        {label}
      </span>
      {children}
    </label>
  );
}
