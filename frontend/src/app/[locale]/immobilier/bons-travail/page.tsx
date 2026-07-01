"use client";

import { useEffect, useMemo, useState } from "react";
import { Hammer, Image as ImageIcon, Loader2, Plus, X } from "lucide-react";

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
  is_urgent?: boolean;
};

type PhotoMeta = { id: number; caption: string | null; content_type: string };
type BonDetail = {
  id: number;
  reference: string;
  title: string;
  description: string | null;
  status: string;
  address: string | null;
  work_notes: string | null;
  is_urgent: boolean;
  photos: PhotoMeta[];
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
STATUS_LABEL.sent = "Envoyé";
STATUS_LABEL.signed = "Signé";

// Bouton plein doré — bon contraste (texte foncé sur fond doré).
const BTN =
  "inline-flex items-center justify-center gap-2 rounded-lg bg-amber-500 px-4 py-2 text-sm font-semibold text-brand-950 hover:bg-amber-400 disabled:opacity-50";

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

  // Détail / édition de la demande.
  const [detailOpen, setDetailOpen] = useState(false);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detail, setDetail] = useState<BonDetail | null>(null);
  const [photoUrls, setPhotoUrls] = useState<Record<number, string>>({});
  const [editTitre, setEditTitre] = useState("");
  const [editDesc, setEditDesc] = useState("");
  const [editUrgent, setEditUrgent] = useState(false);
  const [editBusy, setEditBusy] = useState(false);

  async function loadBons() {
    try {
      const r = await authedFetch("/api/v1/immobilier/bons-travail");
      if (r.ok) setBons((await r.json()) as BonListItem[]);
    } catch {
      /* ignore */
    }
  }

  useEffect(() => {
    void loadBons();
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
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function loadPhoto(bonId: number, photoId: number) {
    try {
      const r = await authedFetch(
        `/api/v1/immobilier/bons-travail/${bonId}/photos/${photoId}`
      );
      if (r.ok) {
        const blob = await r.blob();
        const url = URL.createObjectURL(blob);
        setPhotoUrls((p) => ({ ...p, [photoId]: url }));
      }
    } catch {
      /* ignore */
    }
  }

  async function openDetail(b: BonListItem) {
    setDetailOpen(true);
    setDetailLoading(true);
    setDetail(null);
    setPhotoUrls({});
    setError(null);
    try {
      const r = await authedFetch(`/api/v1/immobilier/bons-travail/${b.id}`);
      if (!r.ok) throw new Error();
      const d = (await r.json()) as BonDetail;
      setDetail(d);
      setEditTitre(d.title);
      setEditDesc(d.description || "");
      setEditUrgent(!!d.is_urgent);
      for (const ph of d.photos) void loadPhoto(b.id, ph.id);
    } catch {
      setError("Impossible d'ouvrir ce bon.");
      setDetailOpen(false);
    } finally {
      setDetailLoading(false);
    }
  }

  function closeDetail() {
    setDetailOpen(false);
    setDetail(null);
    // Libère les object URLs.
    Object.values(photoUrls).forEach((u) => URL.revokeObjectURL(u));
    setPhotoUrls({});
  }

  async function saveEdit() {
    if (!detail) return;
    setEditBusy(true);
    try {
      const r = await authedFetch(
        `/api/v1/immobilier/bons-travail/${detail.id}/demande`,
        {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            titre: editTitre.trim() || null,
            description: editDesc.trim() ? editDesc.trim() : null,
            is_urgent: editUrgent
          })
        }
      );
      if (!r.ok) throw new Error();
      closeDetail();
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
    // Les urgences remontent en haut de chaque colonne.
    for (const id of Object.keys(map)) {
      map[id].sort((a, b) =>
        !!a.is_urgent !== !!b.is_urgent ? (a.is_urgent ? -1 : 1) : 0
      );
    }
    return map;
  }, [bons]);

  return (
    <>
      <ImmobilierTopbar
        breadcrumbs={[
          { label: "Gestion immobilière", href: "/immobilier" },
          { label: "Bons de travail" }
        ]}
      />
      <div className="p-4 pb-24 lg:p-6">
        <header className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div className="flex items-start gap-3">
            <span className="flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-xl bg-amber-500/15 text-amber-300">
              <Hammer className="h-5 w-5" />
            </span>
            <div className="min-w-0">
              <h1 className="text-2xl font-bold text-white">Bons de travail</h1>
              <p className="mt-1 max-w-2xl text-sm text-white/60">
                Entretien de nos immeubles. Crée une demande de réparation ;
                Construction la planifie, l&apos;exécute et la refacture. Tu
                suis l&apos;avancement ici (lecture seule). Clique un bon pour
                voir le détail et corriger ta demande.
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={() => setFormOpen((v) => !v)}
            className={`${BTN} flex-shrink-0`}
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
                className="block w-full text-sm text-white/70 file:mr-3 file:rounded-lg file:border-0 file:bg-amber-500 file:px-3 file:py-2 file:text-sm file:font-semibold file:text-brand-950 hover:file:bg-amber-400"
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
              className={BTN}
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

        {/* ── Suivi (kanban lecture seule) ──────────────────────────── */}
        <section className="mt-8">
          <h2 className="text-lg font-bold text-white">
            Suivi des bons de travail
          </h2>
          <p className="mt-1 max-w-2xl text-xs text-white/50">
            Avancement géré par Construction (lecture seule). Clique un bon pour
            le détail et corriger ta demande au besoin.
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
                          <button
                            key={b.id}
                            type="button"
                            onClick={() => openDetail(b)}
                            className={`block w-full rounded-lg border p-3 text-left transition ${
                              b.is_urgent
                                ? "border-rose-500/70 bg-rose-500/10 hover:border-rose-400"
                                : "border-brand-800 bg-brand-950 hover:border-accent-500"
                            }`}
                          >
                            {b.is_urgent ? (
                              <span className="mb-1 inline-flex items-center gap-1 rounded-md bg-rose-500/20 px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wider text-rose-300">
                                ⚠ Urgence
                              </span>
                            ) : null}
                            <p className="truncate text-sm font-semibold text-white">
                              {b.address || "Adresse non renseignée"}
                            </p>
                            <p className="mt-0.5 truncate text-xs text-white/70">
                              {b.title}
                            </p>
                            <p className="mt-0.5 truncate font-mono text-[10px] text-white/40">
                              {b.reference}
                            </p>
                          </button>
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

      {detailOpen ? (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4"
          onClick={() => (!editBusy ? closeDetail() : null)}
        >
          <div
            className="max-h-[90vh] w-full max-w-lg overflow-y-auto rounded-2xl border border-brand-800 bg-brand-950 p-6"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between">
              <h3 className="text-lg font-bold text-white">Bon de travail</h3>
              <button
                type="button"
                onClick={closeDetail}
                className="text-white/50 hover:text-white"
              >
                <X className="h-5 w-5" />
              </button>
            </div>

            {detailLoading || !detail ? (
              <div className="flex min-h-[20vh] items-center justify-center">
                <Loader2 className="h-6 w-6 animate-spin text-amber-300" />
              </div>
            ) : (
              <>
                <p className="mt-1 text-xs text-white/50">
                  {detail.reference} —{" "}
                  {STATUS_LABEL[detail.status] || detail.status}
                </p>

                <div className="mt-4 space-y-4">
                  <button
                    type="button"
                    onClick={() => setEditUrgent((v) => !v)}
                    className={`inline-flex items-center gap-2 rounded-lg border px-3 py-2 text-sm font-medium transition ${
                      editUrgent
                        ? "border-rose-500 bg-rose-500/20 text-rose-200"
                        : "border-brand-700 bg-brand-900 text-white/70 hover:border-rose-500/50"
                    }`}
                  >
                    ⚠ {editUrgent ? "Urgence activée" : "Marquer urgence"}
                  </button>
                  <Field label="Titre">
                    <input
                      value={editTitre}
                      onChange={(e) => setEditTitre(e.target.value)}
                      className="w-full rounded-lg border border-brand-800 bg-brand-900 px-3 py-2 text-sm text-white outline-none focus:border-amber-300"
                    />
                  </Field>
                  <Field label="Description">
                    <textarea
                      value={editDesc}
                      onChange={(e) => setEditDesc(e.target.value)}
                      rows={4}
                      className="w-full rounded-lg border border-brand-800 bg-brand-900 px-3 py-2 text-sm text-white outline-none focus:border-amber-300"
                    />
                  </Field>

                  {/* Notes de l'exécutant — lecture seule, toujours visible. */}
                  <div>
                    <p className="mb-1 text-xs font-medium text-white/60">
                      Notes de l&apos;exécutant
                    </p>
                    <p className="whitespace-pre-wrap rounded-lg border border-brand-800 bg-brand-900/60 px-3 py-2 text-sm text-white/80">
                      {detail.work_notes || "Aucune note pour l'instant."}
                    </p>
                  </div>

                  {/* Photos — lecture seule. */}
                  {detail.photos.length > 0 ? (
                    <div>
                      <p className="mb-1 flex items-center gap-1 text-xs font-medium text-white/60">
                        <ImageIcon className="h-3.5 w-3.5" /> Photos
                      </p>
                      <div className="grid grid-cols-3 gap-2">
                        {detail.photos.map((ph) =>
                          photoUrls[ph.id] ? (
                            <a
                              key={ph.id}
                              href={photoUrls[ph.id]}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="block aspect-square overflow-hidden rounded-lg border border-brand-800"
                            >
                              {/* eslint-disable-next-line @next/next/no-img-element */}
                              <img
                                src={photoUrls[ph.id]}
                                alt={ph.caption || "photo"}
                                className="h-full w-full object-cover"
                              />
                            </a>
                          ) : (
                            <div
                              key={ph.id}
                              className="flex aspect-square items-center justify-center rounded-lg border border-brand-800 bg-brand-900"
                            >
                              <Loader2 className="h-4 w-4 animate-spin text-white/40" />
                            </div>
                          )
                        )}
                      </div>
                    </div>
                  ) : null}
                </div>

                <div className="mt-5 flex items-center justify-between">
                  <Link
                    // eslint-disable-next-line @typescript-eslint/no-explicit-any
                    href={`/app/bons/${detail.id}` as any}
                    className="text-xs text-white/50 underline hover:text-white"
                  >
                    Voir dans Construction →
                  </Link>
                  <div className="flex items-center gap-3">
                    <button
                      type="button"
                      onClick={closeDetail}
                      disabled={editBusy}
                      className="rounded-lg border border-brand-700 px-3 py-2 text-sm text-white/80 hover:bg-brand-900"
                    >
                      Fermer
                    </button>
                    <button
                      type="button"
                      onClick={() => void saveEdit()}
                      disabled={editBusy || !editTitre.trim()}
                      className={BTN}
                    >
                      {editBusy ? (
                        <Loader2 className="h-4 w-4 animate-spin" />
                      ) : null}
                      Enregistrer
                    </button>
                  </div>
                </div>
              </>
            )}
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
