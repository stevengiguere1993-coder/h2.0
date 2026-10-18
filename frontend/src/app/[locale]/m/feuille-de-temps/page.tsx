"use client";

/**
 * Feuille de temps « par tâche » — zone employés (/m).
 *
 * Utile aux deux variantes : l'employé « autre » (seul pôle Entreprises)
 * et l'employé Construction qui a aussi le pôle Entreprises. L'employé
 * décrit sa période de paie (14 jours) ligne par ligne : jour, compagnie,
 * tâche (importée de ses tâches Gestion d'entreprises ou saisie à la
 * main) et heures. La grille compagnie × jour est dérivée côté serveur ;
 * paie et refacturation ne changent pas (même API que le QG).
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ChevronLeft,
  ChevronRight,
  Clock,
  Loader2,
  Lock,
  Plus,
  Save,
  Send,
  Trash2,
  X
} from "lucide-react";

import { authedFetch } from "@/lib/auth";
import { useConfirm } from "@/components/confirm-dialog";
import {
  DAYS,
  fromApi,
  newKey,
  parseHours,
  type TacheLigne
} from "../../entreprises/feuille-de-temps/taches";
import {
  addDaysISO,
  fmtDayShort,
  fmtHm,
  formatPeriod,
  readApiError,
  timesheetStatus,
  toISODate,
  type TimesheetDetail
} from "../_autre/shared";

/** GET /timesheets/{id}/taches-importables */
type Importable = {
  id: number;
  title: string;
  status: string;
  entreprise_id: number;
  entreprise_name: string;
  company_id?: number | null;
};

type Company = { company_id: number; label: string };

const FIELD =
  "mt-1 w-full rounded-lg border border-brand-800 bg-brand-950 px-3 py-2.5 text-sm text-white";
const LABEL = "text-xs font-medium uppercase tracking-wider text-white/60";
const HOURS_RE = /^[0-9]*[.,]?[0-9]*$/;

export default function MobileFeuilleDeTemps() {
  const confirm = useConfirm();
  const [detail, setDetail] = useState<TimesheetDetail | null>(null);
  const [lignes, setLignes] = useState<TacheLigne[]>([]);
  const [dirty, setDirty] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [importables, setImportables] = useState<Importable[] | null>(null);

  const applyDetail = (d: TimesheetDetail) => {
    setDetail(d);
    setLignes(fromApi(d.taches || []));
    setDirty(false);
  };

  // resolve = get-or-create : sans period_start → période courante.
  const load = useCallback(async (period: string | null) => {
    setLoading(true);
    setError(null);
    try {
      const qs = period ? `?period_start=${encodeURIComponent(period)}` : "";
      const res = await authedFetch(`/api/v1/timesheets/resolve${qs}`);
      if (!res.ok) {
        throw new Error(await readApiError(res, "Chargement échoué."));
      }
      applyDetail((await res.json()) as TimesheetDetail);
      setAdding(false);
      setImportables(null);
    } catch (e) {
      setError(
        e instanceof Error && e.message ? e.message : "Chargement échoué."
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load(null);
  }, [load]);

  async function navigate(period: string | null) {
    if (dirty) {
      const ok = await confirm({
        title: "Quitter sans enregistrer ?",
        description: "Les lignes ajoutées ou modifiées seront perdues.",
        confirmLabel: "Quitter"
      });
      if (!ok) return;
    }
    await load(period);
  }

  const canEdit = detail?.can_edit ?? false;
  const companies: Company[] = useMemo(
    () =>
      (detail?.lignes ?? []).map((l) => ({
        company_id: l.company_id,
        label: l.label
      })),
    [detail]
  );

  const labelFor = (companyId: number): string =>
    companies.find((c) => c.company_id === companyId)?.label ||
    detail?.taches?.find((t) => t.company_id === companyId)?.company_label ||
    `Compagnie #${companyId}`;

  const perDay = useMemo(() => {
    const arr = new Array<number>(DAYS).fill(0);
    for (const l of lignes) {
      if (l.day_index >= 0 && l.day_index < DAYS) {
        arr[l.day_index] += parseHours(l.hours);
      }
    }
    return arr;
  }, [lignes]);
  const total = perDay.reduce((a, b) => a + b, 0);

  const byDay = useMemo(() => {
    const m = new Map<number, TacheLigne[]>();
    for (const l of lignes) {
      if (!m.has(l.day_index)) m.set(l.day_index, []);
      m.get(l.day_index)!.push(l);
    }
    return Array.from(m.entries()).sort(([a], [b]) => a - b);
  }, [lignes]);

  const updateHours = (key: string, value: string) => {
    if (!HOURS_RE.test(value)) return;
    setLignes((prev) =>
      prev.map((l) => (l.key === key ? { ...l, hours: value } : l))
    );
    setDirty(true);
  };
  const removeLine = (key: string) => {
    setLignes((prev) => prev.filter((l) => l.key !== key));
    setDirty(true);
  };
  const addLine = (l: TacheLigne) => {
    setLignes((prev) => [...prev, l]);
    setDirty(true);
    setAdding(false);
  };

  // Toutes les lignes sont renvoyées (le serveur remplace la liste).
  const save = useCallback(async (): Promise<boolean> => {
    if (!detail) return false;
    setSaving(true);
    setError(null);
    try {
      const payload = lignes
        .filter((l) => l.title.trim())
        .map((l) => ({
          day_index: l.day_index,
          company_id: l.company_id,
          entreprise_tache_id: l.entreprise_tache_id,
          title: l.title.trim(),
          hours: parseHours(l.hours)
        }));
      const res = await authedFetch(`/api/v1/timesheets/${detail.id}/taches`, {
        method: "PUT",
        body: JSON.stringify({ lignes: payload })
      });
      if (!res.ok) {
        throw new Error(await readApiError(res, "Enregistrement impossible."));
      }
      applyDetail((await res.json()) as TimesheetDetail);
      return true;
    } catch (e) {
      setError(
        e instanceof Error && e.message
          ? e.message
          : "Enregistrement impossible."
      );
      return false;
    } finally {
      setSaving(false);
    }
  }, [detail, lignes]);

  async function submit() {
    if (!detail) return;
    const ok = await confirm({
      title: "Soumettre ta feuille de temps ?",
      description:
        "Après la soumission, tu ne pourras plus la modifier — seul un gestionnaire pourra la rouvrir.",
      confirmLabel: "Soumettre",
      success: true
    });
    if (!ok) return;
    if (dirty) {
      const saved = await save();
      if (!saved) return;
    }
    setSaving(true);
    setError(null);
    try {
      const res = await authedFetch(
        `/api/v1/timesheets/${detail.id}/submit`,
        { method: "POST" }
      );
      if (!res.ok) {
        throw new Error(await readApiError(res, "Soumission impossible."));
      }
      applyDetail((await res.json()) as TimesheetDetail);
    } catch (e) {
      setError(
        e instanceof Error && e.message ? e.message : "Soumission impossible."
      );
    } finally {
      setSaving(false);
    }
  }

  async function openAdd() {
    setAdding(true);
    if (importables !== null || !detail) return;
    try {
      const res = await authedFetch(
        `/api/v1/timesheets/${detail.id}/taches-importables`
      );
      const body = res.ok ? ((await res.json()) as unknown) : [];
      setImportables(Array.isArray(body) ? (body as Importable[]) : []);
    } catch {
      setImportables([]);
    }
  }

  const statut = detail ? timesheetStatus(detail.status) : null;

  return (
    <>
      <header
        className="sticky top-0 z-30 border-b border-brand-800 bg-brand-950/95 px-4 py-3 backdrop-blur"
        style={{ paddingTop: "max(env(safe-area-inset-top), 0.75rem)" }}
      >
        <h1 className="text-base font-bold text-white">Feuille de temps</h1>
        <p className="mt-0.5 text-[11px] text-white/50">
          Par tâche · période de paie de 14 jours
        </p>
      </header>

      <div className="space-y-4 p-4">
        {error ? (
          <p className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
            {error}
          </p>
        ) : null}

        {/* Navigation entre périodes */}
        <div className="flex items-center justify-between gap-2">
          <button
            type="button"
            disabled={!detail || loading}
            onClick={() =>
              detail && void navigate(addDaysISO(detail.period_start, -14))
            }
            aria-label="Période précédente"
            className="rounded-lg border border-brand-800 bg-brand-900 p-2 text-white/70 disabled:opacity-50"
          >
            <ChevronLeft className="h-5 w-5" />
          </button>
          <button
            type="button"
            disabled={loading}
            onClick={() => void navigate(null)}
            className="rounded-lg border border-brand-800 bg-brand-900 px-3 py-2 text-xs font-semibold text-white/70 disabled:opacity-50"
          >
            Période courante
          </button>
          <button
            type="button"
            disabled={!detail || loading}
            onClick={() =>
              detail && void navigate(addDaysISO(detail.period_start, 14))
            }
            aria-label="Période suivante"
            className="rounded-lg border border-brand-800 bg-brand-900 p-2 text-white/70 disabled:opacity-50"
          >
            <ChevronRight className="h-5 w-5" />
          </button>
        </div>

        {loading || !detail || !statut ? (
          <div className="flex items-center justify-center py-10">
            <Loader2 className="h-5 w-5 animate-spin text-white/40" />
          </div>
        ) : (
          <>
            {/* En-tête de période */}
            <section className="rounded-2xl border border-brand-800 bg-brand-900 p-4">
              <p className="flex items-center gap-2 text-xs uppercase tracking-wider text-white/50">
                <Clock className="h-3.5 w-3.5 text-accent-500" /> Période
              </p>
              <p className="mt-1 text-sm font-semibold text-white">
                {formatPeriod(
                  detail.jours_dates[0] || detail.period_start,
                  detail.jours_dates[DAYS - 1] || detail.period_end
                )}
              </p>
              <div className="mt-2 flex items-center justify-between gap-2">
                <span
                  className={`rounded-full border px-2 py-0.5 text-[10px] font-semibold ${statut.cls}`}
                >
                  {statut.label}
                </span>
                <p className="text-lg font-bold tabular-nums text-white">
                  {fmtHm(total)}
                </p>
              </div>
              {dirty ? (
                <p className="mt-2 text-[11px] font-semibold text-amber-300">
                  Modifications non enregistrées
                </p>
              ) : null}
              {!canEdit ? (
                <p className="mt-2 flex items-start gap-1.5 text-xs text-white/60">
                  <Lock className="mt-0.5 h-3.5 w-3.5 flex-shrink-0" />
                  Feuille {statut.label.toLowerCase()} — lecture seule.
                  Demande à un gestionnaire de la rouvrir pour la modifier.
                </p>
              ) : null}
            </section>

            {canEdit && companies.length === 0 ? (
              <p className="rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs text-amber-300">
                Aucune compagnie n&apos;est disponible dans ta feuille —
                demande à un gestionnaire de t&apos;en assigner une.
              </p>
            ) : null}

            {/* Lignes groupées par jour */}
            {byDay.length === 0 ? (
              <div className="rounded-2xl border border-dashed border-brand-800 bg-brand-900/40 px-6 py-10 text-center">
                <Clock className="mx-auto h-8 w-8 text-white/30" />
                <p className="mt-3 text-sm text-white/60">
                  Aucune heure inscrite pour cette période.
                </p>
              </div>
            ) : (
              <div className="space-y-5">
                {byDay.map(([dayIdx, rows]) => (
                  <section key={dayIdx}>
                    <h2 className="mb-2 flex items-center justify-between text-[11px] font-semibold uppercase tracking-wider text-white/50">
                      <span>
                        {detail.jours_dates[dayIdx]
                          ? fmtDayShort(detail.jours_dates[dayIdx])
                          : `Jour ${dayIdx + 1}`}
                      </span>
                      <span className="tabular-nums text-white/60">
                        {fmtHm(perDay[dayIdx])}
                      </span>
                    </h2>
                    <ul className="space-y-2">
                      {rows.map((l) => (
                        <li
                          key={l.key}
                          className="flex items-center gap-3 rounded-xl border border-brand-800 bg-brand-900 px-3 py-3"
                        >
                          <div className="min-w-0 flex-1">
                            <p className="truncate text-sm font-semibold text-white">
                              {l.title || "(sans titre)"}
                            </p>
                            <p className="mt-0.5 truncate text-xs text-white/50">
                              {labelFor(l.company_id)}
                              {l.entreprise_tache_id ? " · tâche importée" : ""}
                            </p>
                          </div>
                          {canEdit ? (
                            <input
                              inputMode="decimal"
                              value={l.hours}
                              onChange={(e) =>
                                updateHours(l.key, e.target.value)
                              }
                              placeholder="0"
                              aria-label="Heures"
                              className="w-16 rounded-lg border border-brand-800 bg-brand-950 px-2 py-1.5 text-right text-sm tabular-nums text-white"
                            />
                          ) : (
                            <span className="text-sm font-semibold tabular-nums text-white">
                              {fmtHm(parseHours(l.hours))}
                            </span>
                          )}
                          {canEdit ? (
                            <button
                              type="button"
                              onClick={() => removeLine(l.key)}
                              aria-label="Retirer la ligne"
                              className="rounded-lg border border-rose-500/40 bg-rose-500/10 p-1.5 text-rose-300"
                            >
                              <Trash2 className="h-4 w-4" />
                            </button>
                          ) : null}
                        </li>
                      ))}
                    </ul>
                  </section>
                ))}
              </div>
            )}

            {canEdit && companies.length > 0 ? (
              adding ? (
                <AjoutLigneForm
                  joursDates={detail.jours_dates}
                  companies={companies}
                  importables={importables}
                  onAdd={addLine}
                  onCancel={() => setAdding(false)}
                />
              ) : (
                <button
                  type="button"
                  onClick={() => void openAdd()}
                  className="flex w-full items-center justify-center gap-2 rounded-xl border border-dashed border-brand-700 bg-brand-900/40 px-4 py-3 text-sm font-semibold text-white/70"
                >
                  <Plus className="h-4 w-4" /> Ajouter une ligne
                </button>
              )
            ) : null}

            {canEdit ? (
              <div className="flex items-center gap-2 pt-1">
                <button
                  type="button"
                  onClick={() => void save()}
                  disabled={!dirty || saving}
                  className="flex flex-1 items-center justify-center gap-2 rounded-xl bg-accent-500 px-4 py-3 text-sm font-bold text-brand-950 disabled:opacity-50"
                >
                  {saving ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <Save className="h-4 w-4" />
                  )}
                  Enregistrer
                </button>
                <button
                  type="button"
                  onClick={() => void submit()}
                  disabled={saving}
                  className="flex flex-1 items-center justify-center gap-2 rounded-xl border border-emerald-500/40 bg-emerald-500/10 px-4 py-3 text-sm font-bold text-emerald-300 disabled:opacity-50"
                >
                  <Send className="h-4 w-4" /> Soumettre
                </button>
              </div>
            ) : null}
          </>
        )}
      </div>
    </>
  );
}

function AjoutLigneForm({
  joursDates,
  companies,
  importables,
  onAdd,
  onCancel
}: {
  joursDates: string[];
  companies: Company[];
  importables: Importable[] | null;
  onAdd: (l: TacheLigne) => void;
  onCancel: () => void;
}) {
  const todayIdx = joursDates.indexOf(toISODate(new Date()));
  const [day, setDay] = useState<number>(todayIdx >= 0 ? todayIdx : 0);
  const [companyId, setCompanyId] = useState<number>(
    companies[0]?.company_id ?? 0
  );
  const [mode, setMode] = useState<"import" | "manuel">("import");
  const [importId, setImportId] = useState<string>("");
  const [title, setTitle] = useState("");
  const [hours, setHours] = useState("");
  const [error, setError] = useState<string | null>(null);

  // Sans tâche importable (liste chargée et vide) → saisie manuelle.
  const noImportables = importables !== null && importables.length === 0;
  const effectiveMode = noImportables ? "manuel" : mode;

  const selected =
    effectiveMode === "import" && importId
      ? (importables || []).find((t) => String(t.id) === importId) || null
      : null;

  const pickImport = (value: string) => {
    setImportId(value);
    const t = (importables || []).find((x) => String(x.id) === value);
    // La compagnie de l'entreprise principale de la tâche, si elle est
    // disponible dans la feuille.
    if (
      t?.company_id &&
      companies.some((c) => c.company_id === t.company_id)
    ) {
      setCompanyId(t.company_id);
    }
  };

  const setHoursSafe = (value: string) => {
    if (!HOURS_RE.test(value)) return;
    setHours(value);
  };

  function submit(e: React.FormEvent) {
    e.preventDefault();
    const finalTitle =
      effectiveMode === "import" ? selected?.title || "" : title.trim();
    if (!finalTitle) {
      setError(
        effectiveMode === "import"
          ? "Choisis une tâche à importer."
          : "Décris la tâche."
      );
      return;
    }
    const h = parseHours(hours);
    if (h <= 0 || h > 24) {
      setError("Inscris un nombre d'heures entre 0 et 24 (ex. 2,5).");
      return;
    }
    if (!companies.some((c) => c.company_id === companyId)) {
      setError("Choisis une compagnie.");
      return;
    }
    onAdd({
      key: newKey(),
      day_index: day,
      company_id: companyId,
      entreprise_tache_id: effectiveMode === "import" ? selected!.id : null,
      title: finalTitle,
      hours
    });
  }

  return (
    <form
      onSubmit={submit}
      className="space-y-3 rounded-2xl border border-accent-500/40 bg-brand-900 p-4"
    >
      <div className="flex items-center justify-between">
        <p className="flex items-center gap-2 text-xs uppercase tracking-wider text-white/50">
          <Plus className="h-3.5 w-3.5 text-accent-500" /> Nouvelle ligne
        </p>
        <button
          type="button"
          onClick={onCancel}
          aria-label="Fermer"
          className="rounded-lg p-1 text-white/50"
        >
          <X className="h-4 w-4" />
        </button>
      </div>
      {error ? (
        <p className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
          {error}
        </p>
      ) : null}

      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className={LABEL}>Jour</label>
          <select
            value={day}
            onChange={(e) => setDay(Number(e.target.value))}
            className={FIELD}
          >
            {joursDates.map((iso, i) => (
              <option key={iso} value={i}>
                {fmtDayShort(iso)}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className={LABEL}>Heures</label>
          <input
            inputMode="decimal"
            value={hours}
            onChange={(e) => setHoursSafe(e.target.value)}
            placeholder="Ex. 2,5"
            className={`${FIELD} tabular-nums`}
          />
        </div>
      </div>

      <div>
        <label className={LABEL}>Compagnie</label>
        <select
          value={companyId}
          onChange={(e) => setCompanyId(Number(e.target.value))}
          className={FIELD}
        >
          {companies.map((c) => (
            <option key={c.company_id} value={c.company_id}>
              {c.label}
            </option>
          ))}
        </select>
      </div>

      {!noImportables ? (
        <div className="flex gap-2">
          <button
            type="button"
            onClick={() => setMode("import")}
            className={`flex-1 rounded-lg border px-3 py-2 text-xs font-semibold ${
              effectiveMode === "import"
                ? "border-accent-500 bg-accent-500/20 text-accent-500"
                : "border-brand-700 bg-brand-950 text-white/60"
            }`}
          >
            Tâche assignée
          </button>
          <button
            type="button"
            onClick={() => setMode("manuel")}
            className={`flex-1 rounded-lg border px-3 py-2 text-xs font-semibold ${
              effectiveMode === "manuel"
                ? "border-accent-500 bg-accent-500/20 text-accent-500"
                : "border-brand-700 bg-brand-950 text-white/60"
            }`}
          >
            Saisie manuelle
          </button>
        </div>
      ) : null}

      {effectiveMode === "import" ? (
        <div>
          <label className={LABEL}>Tâche</label>
          {importables === null ? (
            <p className="mt-1 flex items-center gap-2 text-xs text-white/50">
              <Loader2 className="h-3.5 w-3.5 animate-spin" /> Chargement de
              tes tâches…
            </p>
          ) : (
            <select
              value={importId}
              onChange={(e) => pickImport(e.target.value)}
              className={FIELD}
            >
              <option value="">Choisir…</option>
              {importables.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.title} · {t.entreprise_name}
                </option>
              ))}
            </select>
          )}
        </div>
      ) : (
        <div>
          <label className={LABEL}>Tâche</label>
          <input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="Description de la tâche"
            maxLength={255}
            className={FIELD}
          />
          {noImportables ? (
            <p className="mt-1 text-[11px] text-white/50">
              Aucune tâche assignée à importer pour cette période.
            </p>
          ) : null}
        </div>
      )}

      <div className="flex items-center justify-end gap-2 pt-1">
        <button
          type="button"
          onClick={onCancel}
          className="rounded-lg border border-brand-700 bg-brand-950 px-3 py-2 text-xs font-semibold text-white/70"
        >
          Annuler
        </button>
        <button
          type="submit"
          className="inline-flex items-center gap-1.5 rounded-lg bg-accent-500 px-3 py-2 text-xs font-semibold text-brand-950"
        >
          <Plus className="h-3.5 w-3.5" /> Ajouter
        </button>
      </div>
    </form>
  );
}
