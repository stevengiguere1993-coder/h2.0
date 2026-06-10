"use client";

import { useEffect, useMemo, useState } from "react";
import { Hammer, Loader2 } from "lucide-react";

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
  start_date: string | null;
  end_date: string | null;
  phase_count: number;
};

type BonListItem = {
  id: number;
  reference: string;
  title: string;
  status: string;
  created_at: string | null;
  sent_at: string | null;
  signed_at: string | null;
  client_name: string | null;
  project: BonProject | null;
};

type BonPhase = {
  id: number;
  name: string;
  start_date: string | null;
  end_date: string | null;
  duration_days: number | null;
  assignee_name: string | null;
};

type BonPhoto = {
  id: number;
  caption: string | null;
  content_type: string;
};

type BonDetail = BonListItem & {
  description: string | null;
  scope_md: string | null;
  phases: BonPhase[];
  photos: BonPhoto[];
};

const BON_STATUS: Record<string, { label: string; cls: string }> = {
  draft: { label: "Brouillon", cls: "bg-slate-500/20 text-slate-200" },
  sent: { label: "Envoyé", cls: "bg-sky-500/20 text-sky-200" },
  signed: { label: "Signé", cls: "bg-emerald-500/20 text-emerald-200" },
  cancelled: { label: "Annulé", cls: "bg-rose-500/20 text-rose-200" }
};

const PROJECT_STATUS: Record<string, { label: string; cls: string }> = {
  planned: { label: "À planifier", cls: "bg-slate-500/20 text-slate-200" },
  ready_to_start: {
    label: "En attente de début",
    cls: "bg-amber-500/20 text-amber-200"
  },
  in_progress: { label: "En cours", cls: "bg-sky-500/20 text-sky-200" },
  suspended: { label: "Suspendu", cls: "bg-orange-500/20 text-orange-200" },
  delivered: { label: "Livré", cls: "bg-emerald-500/20 text-emerald-200" }
};

function fmtDate(iso: string | null): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleDateString("fr-CA", {
      day: "2-digit",
      month: "short",
      year: "numeric"
    });
  } catch {
    return iso;
  }
}

export default function BonsTravailPage() {
  const { currentEntrepriseId } = useImmobilierLayout();
  const [immeubles, setImmeubles] = useState<ImmeubleListItem[] | null>(null);
  const [immeubleId, setImmeubleId] = useState<number | "">("");
  const [logements, setLogements] = useState<Logement[]>([]);
  const [logement, setLogement] = useState("");
  const [titre, setTitre] = useState("");
  const [description, setDescription] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<BonResult | null>(null);
  // Suivi (miroir lecture seule) des bons de travail gestion immo.
  const [bons, setBons] = useState<BonListItem[] | null>(null);
  const [detailId, setDetailId] = useState<number | null>(null);

  async function loadBons() {
    try {
      const r = await authedFetch("/api/v1/immobilier/bons-travail");
      if (!r.ok) return;
      setBons((await r.json()) as BonListItem[]);
    } catch {
      /* ignore */
    }
  }

  useEffect(() => {
    void loadBons();
  }, []);

  // Charge les immeubles de la compagnie active.
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
        if (!r.ok) return;
        if (!cancelled) setImmeubles((await r.json()) as ImmeubleListItem[]);
      } catch {
        /* ignore */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [currentEntrepriseId]);

  // Charge les logements de l'immeuble sélectionné.
  useEffect(() => {
    setLogements([]);
    setLogement("");
    if (immeubleId === "") return;
    let cancelled = false;
    (async () => {
      try {
        const r = await authedFetch(
          `/api/v1/immobilier/immeubles/${immeubleId}/logements`
        );
        if (!r.ok) return;
        if (!cancelled) setLogements((await r.json()) as Logement[]);
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
          body: JSON.stringify({
            titre: titre.trim(),
            description: description.trim() || null,
            logement: logement.trim() || null
          })
        }
      );
      if (!r.ok)
        throw new Error((await r.text()).slice(0, 200) || `HTTP ${r.status}`);
      setResult((await r.json()) as BonResult);
      setTitre("");
      setDescription("");
      setLogement("");
      void loadBons();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
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
        <header className="flex items-start gap-3">
          <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-amber-500/15 text-amber-300">
            <Hammer className="h-5 w-5" />
          </span>
          <div>
            <h1 className="text-2xl font-bold text-white">Bons de travail</h1>
            <p className="mt-1 max-w-2xl text-sm text-white/60">
              Crée un bon de travail pour une réparation : choisis un immeuble,
              un logement, décris les travaux. Le bon part dans le volet
              Construction (brouillon) et la compagnie propriétaire devient
              cliente si elle ne l&apos;est pas déjà.
            </p>
          </div>
        </header>

        <section className="mt-6 max-w-xl space-y-3 rounded-2xl border border-brand-800 bg-brand-900 p-5">
          <Field label="Immeuble *">
            <select
              value={immeubleId}
              onChange={(e) =>
                setImmeubleId(e.target.value ? Number(e.target.value) : "")
              }
              className="w-full rounded-lg border border-brand-800 bg-brand-950 px-3 py-2 text-sm text-white outline-none focus:border-amber-300"
            >
              <option value="" className="bg-brand-950 text-white">
                — choisir un immeuble —
              </option>
              {(immeubles || []).map((i) => (
                <option key={i.id} value={i.id} className="bg-brand-950 text-white">
                  {i.name}
                  {i.city ? ` — ${i.city}` : ""}
                </option>
              ))}
            </select>
          </Field>

          <Field label="Logement / appartement">
            <select
              value={logement}
              onChange={(e) => setLogement(e.target.value)}
              disabled={immeubleId === "" || logements.length === 0}
              className="w-full rounded-lg border border-brand-800 bg-brand-950 px-3 py-2 text-sm text-white outline-none focus:border-amber-300 disabled:opacity-50"
            >
              <option value="" className="bg-brand-950 text-white">
                {immeubleId === ""
                  ? "— choisis d'abord un immeuble —"
                  : logements.length === 0
                    ? "— aucun logement (optionnel) —"
                    : "— immeuble entier / optionnel —"}
              </option>
              {logements.map((l) => (
                <option
                  key={l.id}
                  value={l.numero}
                  className="bg-brand-950 text-white"
                >
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
            Créer le bon de travail
          </button>

          {selectedImmeuble ? (
            <p className="text-[11px] text-white/40">
              Pour : {selectedImmeuble.address}
              {selectedImmeuble.city ? `, ${selectedImmeuble.city}` : ""}
              {logement ? ` — logement ${logement}` : ""}
            </p>
          ) : null}
        </section>

        {result ? (
          <div className="mt-4 max-w-xl rounded-2xl border border-emerald-500/40 bg-emerald-500/10 p-4 text-sm text-emerald-200">
            <p className="font-semibold">Bon {result.reference} créé ✅</p>
            <p className="mt-1 text-xs">
              Envoyé dans le volet Construction (brouillon).
              {result.client_name
                ? result.client_created
                  ? ` Client « ${result.client_name} » créé.`
                  : ` Client « ${result.client_name} » réutilisé.`
                : ""}
            </p>
            <Link
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
              href={`/app/bons/${result.bon_id}` as any}
              className="mt-2 inline-flex rounded-lg border border-amber-400/30 bg-amber-500/15 px-3 py-1.5 text-xs font-semibold text-amber-100 hover:bg-amber-500/25"
            >
              Ouvrir dans Construction →
            </Link>
          </div>
        ) : null}

        {/* Suivi lecture seule — avancement des bons de travail */}
        <section className="mt-8">
          <h2 className="text-lg font-bold text-white">
            Suivi des bons de travail
          </h2>
          <p className="mt-1 max-w-2xl text-xs text-white/50">
            Avancement des bons partis en Construction. Lecture seule :
            l&apos;assignation des équipes et la planification se gèrent côté
            Construction.
          </p>

          {bons === null ? (
            <div className="mt-4 flex items-center gap-2 text-sm text-white/50">
              <Loader2 className="h-4 w-4 animate-spin" /> Chargement…
            </div>
          ) : bons.length === 0 ? (
            <p className="mt-4 rounded-xl border border-dashed border-brand-800 bg-brand-900/40 px-4 py-8 text-center text-sm text-white/50">
              Aucun bon de travail pour l&apos;instant. Crée-en un ci-dessus.
            </p>
          ) : (
            <ul className="mt-4 grid gap-3 lg:grid-cols-2">
              {bons.map((b) => {
                const bs = BON_STATUS[b.status] || {
                  label: b.status,
                  cls: "bg-white/10 text-white/70"
                };
                const ps = b.project
                  ? PROJECT_STATUS[b.project.status || ""] || {
                      label: b.project.status || "—",
                      cls: "bg-white/10 text-white/70"
                    }
                  : null;
                return (
                  <li
                    key={b.id}
                    className="rounded-2xl border border-brand-800 bg-brand-900 p-4"
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0">
                        <p className="truncate text-sm font-bold text-white">
                          {b.title}
                        </p>
                        <p className="mt-0.5 font-mono text-[10px] text-white/40">
                          {b.reference}
                          {b.client_name ? ` · ${b.client_name}` : ""}
                        </p>
                      </div>
                      <span
                        className={`flex-shrink-0 rounded-full px-2 py-0.5 text-[10px] font-semibold ${bs.cls}`}
                      >
                        {bs.label}
                      </span>
                    </div>

                    {b.project ? (
                      <div className="mt-3 rounded-xl border border-brand-800 bg-brand-950/50 p-3">
                        <div className="flex items-center justify-between gap-2">
                          <span className="truncate text-xs font-medium text-white/80">
                            🏗️ {b.project.label}
                          </span>
                          {ps ? (
                            <span
                              className={`flex-shrink-0 rounded-full px-2 py-0.5 text-[10px] font-semibold ${ps.cls}`}
                            >
                              {ps.label}
                            </span>
                          ) : null}
                        </div>
                        <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-brand-800">
                          <div
                            className="h-full rounded-full bg-gradient-to-r from-amber-400 to-emerald-400"
                            style={{ width: `${b.project.progress_pct}%` }}
                          />
                        </div>
                        <p className="mt-1.5 text-[10px] text-white/45">
                          {b.project.phase_count} phase
                          {b.project.phase_count > 1 ? "s" : ""}
                          {b.project.start_date
                            ? ` · du ${fmtDate(b.project.start_date)}`
                            : ""}
                          {b.project.end_date
                            ? ` au ${fmtDate(b.project.end_date)}`
                            : ""}
                        </p>
                      </div>
                    ) : (
                      <p className="mt-3 rounded-xl border border-dashed border-brand-800 bg-brand-950/40 px-3 py-2 text-[11px] text-white/45">
                        Pas encore pris en charge par Construction (aucun
                        chantier lié).
                      </p>
                    )}

                    <div className="mt-3 flex items-center justify-between">
                      <span className="text-[10px] text-white/35">
                        Créé le {fmtDate(b.created_at)}
                      </span>
                      <button
                        type="button"
                        onClick={() => setDetailId(b.id)}
                        className="inline-flex items-center gap-1 rounded-lg border border-brand-700 px-2.5 py-1 text-[11px] font-semibold text-white/80 hover:border-amber-300 hover:text-white"
                      >
                        Voir le suivi →
                      </button>
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
        </section>
      </div>

      {detailId != null ? (
        <BonDetailModal bonId={detailId} onClose={() => setDetailId(null)} />
      ) : null}
    </>
  );
}

function BonDetailModal({
  bonId,
  onClose
}: {
  bonId: number;
  onClose: () => void;
}) {
  const [detail, setDetail] = useState<BonDetail | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    (async () => {
      try {
        const r = await authedFetch(
          `/api/v1/immobilier/bons-travail/${bonId}`
        );
        if (!r.ok) return;
        if (!cancelled) setDetail((await r.json()) as BonDetail);
      } catch {
        /* ignore */
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [bonId]);

  const bs = detail
    ? BON_STATUS[detail.status] || {
        label: detail.status,
        cls: "bg-white/10 text-white/70"
      }
    : null;
  const ps =
    detail?.project && detail.project.status
      ? PROJECT_STATUS[detail.project.status] || {
          label: detail.project.status,
          cls: "bg-white/10 text-white/70"
        }
      : null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/70 p-4 sm:items-center"
      onClick={onClose}
    >
      <div
        className="my-auto w-full max-w-lg rounded-2xl border border-brand-800 bg-brand-950 p-5"
        onClick={(e) => e.stopPropagation()}
      >
        {loading || !detail ? (
          <div className="flex items-center justify-center py-10">
            <Loader2 className="h-6 w-6 animate-spin text-white/40" />
          </div>
        ) : (
          <>
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <h3 className="text-lg font-bold text-white">
                  {detail.title}
                </h3>
                <p className="mt-0.5 font-mono text-[11px] text-white/40">
                  {detail.reference}
                  {detail.client_name ? ` · ${detail.client_name}` : ""}
                </p>
              </div>
              {bs ? (
                <span
                  className={`flex-shrink-0 rounded-full px-2.5 py-1 text-[11px] font-semibold ${bs.cls}`}
                >
                  {bs.label}
                </span>
              ) : null}
            </div>

            {detail.description ? (
              <p className="mt-3 whitespace-pre-wrap text-sm text-white/70">
                {detail.description}
              </p>
            ) : null}

            {detail.project ? (
              <div className="mt-4 rounded-xl border border-brand-800 bg-brand-900 p-3">
                <div className="flex items-center justify-between gap-2">
                  <span className="truncate text-sm font-semibold text-white">
                    🏗️ {detail.project.label}
                  </span>
                  {ps ? (
                    <span
                      className={`flex-shrink-0 rounded-full px-2 py-0.5 text-[10px] font-semibold ${ps.cls}`}
                    >
                      {ps.label}
                    </span>
                  ) : null}
                </div>
                <div className="mt-2 h-2 overflow-hidden rounded-full bg-brand-800">
                  <div
                    className="h-full rounded-full bg-gradient-to-r from-amber-400 to-emerald-400"
                    style={{ width: `${detail.project.progress_pct}%` }}
                  />
                </div>

                <p className="mt-3 text-[11px] font-semibold uppercase tracking-wider text-white/40">
                  Planification ({detail.phases.length})
                </p>
                {detail.phases.length === 0 ? (
                  <p className="mt-1 text-xs text-white/45">
                    Aucune phase planifiée pour l&apos;instant.
                  </p>
                ) : (
                  <ul className="mt-1.5 space-y-1.5">
                    {detail.phases.map((ph) => (
                      <li
                        key={ph.id}
                        className="flex items-center justify-between gap-2 rounded-lg bg-brand-950/60 px-2.5 py-1.5"
                      >
                        <div className="min-w-0">
                          <p className="truncate text-xs font-medium text-white">
                            {ph.name}
                          </p>
                          <p className="text-[10px] text-white/45">
                            {ph.start_date ? fmtDate(ph.start_date) : "—"}
                            {ph.end_date ? ` → ${fmtDate(ph.end_date)}` : ""}
                            {ph.assignee_name ? ` · ${ph.assignee_name}` : ""}
                          </p>
                        </div>
                      </li>
                    ))}
                  </ul>
                )}

                {detail.photos.length > 0 ? (
                  <>
                    <p className="mt-4 text-[11px] font-semibold uppercase tracking-wider text-white/40">
                      Photos du chantier ({detail.photos.length})
                    </p>
                    <div className="mt-1.5 grid grid-cols-3 gap-1.5">
                      {detail.photos.map((ph) => (
                        <PhotoThumb
                          key={ph.id}
                          bonId={bonId}
                          photoId={ph.id}
                          caption={ph.caption}
                          contentType={ph.content_type}
                        />
                      ))}
                    </div>
                  </>
                ) : null}
              </div>
            ) : (
              <p className="mt-4 rounded-xl border border-dashed border-brand-800 bg-brand-900/40 px-3 py-3 text-xs text-white/50">
                Ce bon n&apos;est pas encore rattaché à un chantier en
                Construction. L&apos;avancement s&apos;affichera ici dès sa
                prise en charge.
              </p>
            )}

            <div className="mt-5 flex justify-end">
              <button
                type="button"
                onClick={onClose}
                className="rounded-lg border border-brand-700 px-4 py-2 text-sm text-white/80 hover:border-amber-300 hover:text-white"
              >
                Fermer
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

// Charge une photo protégée par auth : `<img src>` ne peut pas envoyer le
// Bearer, donc on récupère le blob via authedFetch puis on crée une URL
// objet locale. Les PDF (le format est autorisé à l'upload) ouvrent dans un
// nouvel onglet au clic.
function PhotoThumb({
  bonId,
  photoId,
  caption,
  contentType
}: {
  bonId: number;
  photoId: number;
  caption: string | null;
  contentType: string;
}) {
  const [url, setUrl] = useState<string | null>(null);
  const isImage = contentType.startsWith("image/");

  useEffect(() => {
    let active = true;
    let objUrl: string | null = null;
    (async () => {
      try {
        const r = await authedFetch(
          `/api/v1/immobilier/bons-travail/${bonId}/photos/${photoId}`
        );
        if (!r.ok) return;
        const blob = await r.blob();
        objUrl = URL.createObjectURL(blob);
        if (active) setUrl(objUrl);
      } catch {
        /* ignore */
      }
    })();
    return () => {
      active = false;
      if (objUrl) URL.revokeObjectURL(objUrl);
    };
  }, [bonId, photoId]);

  const cls =
    "flex aspect-square items-center justify-center overflow-hidden rounded-lg border border-brand-800 bg-brand-950";

  if (!url) {
    return (
      <div className={cls}>
        <Loader2 className="h-4 w-4 animate-spin text-white/30" />
      </div>
    );
  }
  if (!isImage) {
    return (
      <a
        href={url}
        target="_blank"
        rel="noopener noreferrer"
        title={caption || "Document"}
        className={`${cls} text-xs font-semibold text-white/70 hover:text-amber-300`}
      >
        📄 Ouvrir
      </a>
    );
  }
  return (
    <a href={url} target="_blank" rel="noopener noreferrer" className={cls}>
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src={url}
        alt={caption || "Photo du chantier"}
        title={caption || undefined}
        className="h-full w-full object-cover"
      />
    </a>
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
    <div>
      <label className="mb-1 block text-[11px] font-semibold uppercase tracking-wider text-white/50">
        {label}
      </label>
      {children}
    </div>
  );
}
