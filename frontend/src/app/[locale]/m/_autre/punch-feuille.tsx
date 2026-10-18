"use client";

/**
 * Punch de la feuille de temps — zone employés « autre » (bug 16,
 * Steven 2026-10-18).
 *
 * L'employé sans pôle Construction n'a pas le punch des chantiers : il
 * choisit une compagnie de sa feuille et une tâche (assignée ou saisie à
 * la main), « Commencer », puis « Arrêter » : la durée s'ajoute à la
 * ligne du jour de sa feuille de temps (même tâche → même ligne). Un
 * punch oublié s'arrête en indiquant l'heure de fin réelle.
 */

import { useCallback, useEffect, useState } from "react";
import { Loader2, Play, Square, Timer, X } from "lucide-react";

import { authedFetch } from "@/lib/auth";
import { useConfirm } from "@/components/confirm-dialog";
import {
  fmtDayShort,
  fmtHm,
  readApiError,
  toISODate,
  type TimesheetDetail
} from "./shared";

/** GET /timesheets/punch → `en_cours` (PunchOut). */
export type PunchEnCours = {
  id: number;
  user_id: number;
  company_id: number;
  company_label: string;
  entreprise_tache_id: number | null;
  title: string;
  started_at: string;
  ended_at: string | null;
  hours: number | null;
};

/** POST /timesheets/punch/stop */
export type PunchStopResult = {
  punch: PunchEnCours;
  heures_ajoutees: number;
  message: string | null;
  feuille: TimesheetDetail | null;
};

type Company = { company_id: number; label: string };

/** GET /timesheets/{id}/taches-importables */
type Importable = {
  id: number;
  title: string;
  entreprise_name: string;
  company_id?: number | null;
};

/** Au-delà, on propose de corriger l'heure de fin (punch oublié). */
const OUBLI_MS = 12 * 3600 * 1000;

const FIELD =
  "mt-1 w-full rounded-lg border border-brand-800 bg-brand-950 px-3 py-2.5 text-sm text-white";
const LABEL = "text-xs font-medium uppercase tracking-wider text-white/60";
/** Gros bouton : encre blanche dans les deux thèmes (`text-white` passe en
 *  quasi-noir en mode clair) sur un fond assez foncé pour 4,5:1. */
const BTN =
  "flex w-full items-center justify-center gap-2 rounded-xl px-5 py-4 text-base font-bold text-neutral-50";

function hhmmss(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  const p = (n: number) => String(n).padStart(2, "0");
  return `${p(h)}:${p(m)}:${p(s)}`;
}

/** Date → valeur d'un champ `datetime-local` (heure locale). */
function toLocalInput(d: Date): string {
  const p = (n: number) => String(n).padStart(2, "0");
  return `${toISODate(d)}T${p(d.getHours())}:${p(d.getMinutes())}`;
}

/** « à 09 h 02 » aujourd'hui, sinon « lun. 6 oct. à 09 h 02 ». */
function fmtDebut(iso: string): string {
  const d = new Date(iso);
  const heure = d.toLocaleTimeString("fr-CA", {
    hour: "2-digit",
    minute: "2-digit"
  });
  const jour = toISODate(d);
  return jour === toISODate(new Date())
    ? `à ${heure}`
    : `${fmtDayShort(jour)} à ${heure}`;
}

export function PunchFeuille({
  feuilleId,
  companies,
  bloque,
  beforeStop,
  onStopped
}: {
  /** Feuille affichée : sert à charger les tâches importables. */
  feuilleId: number | null;
  /** Compagnies de la feuille de l'employé. */
  companies: Company[];
  /** Raison d'empêcher un nouveau punch (feuille soumise…), sinon rien. */
  bloque?: string | null;
  /** Avant l'arrêt (enregistrer des lignes modifiées) ; false = on attend. */
  beforeStop?: () => Promise<boolean>;
  onStopped?: (res: PunchStopResult) => void;
}) {
  const confirm = useConfirm();
  const [punch, setPunch] = useState<PunchEnCours | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [now, setNow] = useState(() => Date.now());
  const [fin, setFin] = useState("");

  // Formulaire de départ.
  const [ouvert, setOuvert] = useState(false);
  const [companyId, setCompanyId] = useState<number>(
    companies[0]?.company_id ?? 0
  );
  const [mode, setMode] = useState<"import" | "manuel">("import");
  const [importables, setImportables] = useState<Importable[] | null>(null);
  const [importId, setImportId] = useState("");
  const [title, setTitle] = useState("");

  const load = useCallback(async () => {
    try {
      const res = await authedFetch("/api/v1/timesheets/punch");
      if (!res.ok) {
        throw new Error(await readApiError(res, "Punch indisponible."));
      }
      const body = (await res.json()) as { en_cours: PunchEnCours | null };
      setPunch(body.en_cours);
    } catch (e) {
      setError(
        e instanceof Error && e.message ? e.message : "Punch indisponible."
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  // Chrono : une seconde à la fois tant qu'un punch court.
  useEffect(() => {
    if (!punch) return;
    setNow(Date.now());
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, [punch]);

  // Autre feuille affichée → ses tâches importables seront rechargées.
  useEffect(() => {
    setImportables(null);
    setImportId("");
  }, [feuilleId]);

  // La compagnie choisie reste l'une de celles de la feuille.
  useEffect(() => {
    if (!companies.some((c) => c.company_id === companyId)) {
      setCompanyId(companies[0]?.company_id ?? 0);
    }
  }, [companies, companyId]);

  async function openForm() {
    setOuvert(true);
    setError(null);
    setInfo(null);
    if (importables !== null) return;
    if (!feuilleId) {
      setImportables([]);
      return;
    }
    try {
      const res = await authedFetch(
        `/api/v1/timesheets/${feuilleId}/taches-importables`
      );
      const body = res.ok ? ((await res.json()) as unknown) : [];
      setImportables(Array.isArray(body) ? (body as Importable[]) : []);
    } catch {
      setImportables([]);
    }
  }

  // Sans tâche assignée (liste chargée et vide) → saisie manuelle.
  const noImportables = importables !== null && importables.length === 0;
  const effectiveMode = noImportables ? "manuel" : mode;
  const selected =
    effectiveMode === "import" && importId
      ? (importables || []).find((t) => String(t.id) === importId) || null
      : null;

  const pickImport = (value: string) => {
    setImportId(value);
    const t = (importables || []).find((x) => String(x.id) === value);
    // La compagnie de l'entreprise de la tâche, si elle est dans la feuille.
    if (
      t?.company_id &&
      companies.some((c) => c.company_id === t.company_id)
    ) {
      setCompanyId(t.company_id);
    }
  };

  async function start(e: React.FormEvent) {
    e.preventDefault();
    const finalTitle =
      effectiveMode === "import" ? selected?.title || "" : title.trim();
    if (!finalTitle) {
      setError(
        effectiveMode === "import" ? "Choisis une tâche." : "Décris la tâche."
      );
      return;
    }
    if (!companies.some((c) => c.company_id === companyId)) {
      setError("Choisis une compagnie.");
      return;
    }
    setBusy(true);
    setError(null);
    setInfo(null);
    try {
      const res = await authedFetch("/api/v1/timesheets/punch/start", {
        method: "POST",
        body: JSON.stringify({
          company_id: companyId,
          entreprise_tache_id:
            effectiveMode === "import" ? selected?.id ?? null : null,
          title: finalTitle
        })
      });
      if (!res.ok) {
        throw new Error(
          await readApiError(res, "Le punch n'a pas pu commencer.")
        );
      }
      setPunch((await res.json()) as PunchEnCours);
      setOuvert(false);
      setImportId("");
      setTitle("");
      setFin("");
    } catch (err) {
      setError(
        err instanceof Error && err.message
          ? err.message
          : "Le punch n'a pas pu commencer."
      );
    } finally {
      setBusy(false);
    }
  }

  async function stop() {
    if (!punch) return;
    let finIso: string | null = null;
    if (fin) {
      const d = new Date(fin);
      if (Number.isNaN(d.getTime())) {
        setError("Heure de fin invalide.");
        return;
      }
      finIso = d.toISOString();
    }
    if (beforeStop && !(await beforeStop())) return;
    setBusy(true);
    setError(null);
    setInfo(null);
    try {
      const res = await authedFetch("/api/v1/timesheets/punch/stop", {
        method: "POST",
        body: JSON.stringify(finIso ? { fin: finIso } : {})
      });
      if (!res.ok) {
        const msg = await readApiError(res, "Le punch n'a pas pu s'arrêter.");
        // Déjà arrêté ailleurs (autre appareil, gestionnaire) : on relit.
        if (res.status === 404) await load();
        throw new Error(msg);
      }
      const out = (await res.json()) as PunchStopResult;
      setPunch(null);
      setFin("");
      setInfo(
        out.message ||
          `${fmtHm(out.heures_ajoutees)} ajoutées à ta feuille de temps.`
      );
      onStopped?.(out);
    } catch (err) {
      setError(
        err instanceof Error && err.message
          ? err.message
          : "Le punch n'a pas pu s'arrêter."
      );
    } finally {
      setBusy(false);
    }
  }

  async function annuler() {
    const ok = await confirm({
      title: "Annuler ce punch ?",
      description: "Aucune heure ne sera ajoutée à ta feuille de temps.",
      confirmLabel: "Annuler le punch",
      cancelLabel: "Garder",
      destructive: true
    });
    if (!ok) return;
    setBusy(true);
    setError(null);
    setInfo(null);
    try {
      const res = await authedFetch("/api/v1/timesheets/punch", {
        method: "DELETE"
      });
      if (!res.ok && res.status !== 404) {
        throw new Error(await readApiError(res, "Annulation impossible."));
      }
      setPunch(null);
      setFin("");
      setInfo("Punch annulé : aucune heure ajoutée.");
    } catch (err) {
      setError(
        err instanceof Error && err.message
          ? err.message
          : "Annulation impossible."
      );
    } finally {
      setBusy(false);
    }
  }

  const debut = punch ? new Date(punch.started_at) : null;
  const elapsed = debut ? now - debut.getTime() : 0;

  return (
    <section
      id="punch"
      className="rounded-2xl border border-brand-800 bg-brand-900 p-4"
    >
      <p className="flex items-center gap-2 text-xs uppercase tracking-wider text-white/50">
        <Timer className="h-3.5 w-3.5 text-accent-500" /> Punch
      </p>

      {error ? (
        <p className="mt-2 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
          {error}
        </p>
      ) : null}
      {info ? (
        <p className="mt-2 rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-xs text-emerald-300">
          {info}
        </p>
      ) : null}

      {loading ? (
        <div className="flex items-center justify-center py-6">
          <Loader2 className="h-5 w-5 animate-spin text-white/40" />
        </div>
      ) : punch && debut ? (
        <div className="mt-3 flex flex-col items-center gap-3 text-center">
          <p className="font-mono text-4xl font-bold tabular-nums text-white">
            {hhmmss(elapsed)}
          </p>
          <p className="text-xs text-white/50">
            Punch en cours, commencé {fmtDebut(punch.started_at)}
          </p>
          <div className="w-full rounded-lg border border-brand-800 bg-brand-950 px-3 py-2 text-left">
            <p className="truncate text-sm font-semibold text-white">
              {punch.title}
            </p>
            {punch.company_label ? (
              <p className="mt-0.5 truncate text-xs text-white/50">
                {punch.company_label}
              </p>
            ) : null}
          </div>

          {elapsed >= OUBLI_MS ? (
            <div className="w-full rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-left">
              <p className="text-xs font-semibold text-amber-300">
                Ton punch roule depuis plus de 12 h.
              </p>
              <label className="mt-1 block text-xs text-white/70">
                Tu as oublié de l&apos;arrêter ? Indique l&apos;heure de fin
                réelle :
                <input
                  type="datetime-local"
                  value={fin}
                  min={toLocalInput(debut)}
                  max={toLocalInput(new Date(now))}
                  onChange={(e) => setFin(e.target.value)}
                  className={FIELD}
                />
              </label>
            </div>
          ) : null}

          <button
            type="button"
            onClick={() => void stop()}
            disabled={busy}
            className={`${BTN} bg-rose-700 disabled:opacity-60`}
          >
            {busy ? (
              <Loader2 className="h-5 w-5 animate-spin" />
            ) : (
              <Square className="h-5 w-5" />
            )}
            Arrêter le punch
          </button>
          <button
            type="button"
            onClick={() => void annuler()}
            disabled={busy}
            className="text-xs font-semibold text-white/60 underline disabled:opacity-50"
          >
            Annuler ce punch (démarré par erreur)
          </button>
        </div>
      ) : ouvert ? (
        <form onSubmit={start} className="mt-3 space-y-3">
          <div className="flex items-center justify-between">
            <p className="text-sm font-semibold text-white">
              Commencer un punch
            </p>
            <button
              type="button"
              onClick={() => setOuvert(false)}
              aria-label="Fermer"
              className="rounded-lg p-1 text-white/50"
            >
              <X className="h-4 w-4" />
            </button>
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
                    ? "border-accent-500 bg-accent-500/10 text-accent-500"
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
                    ? "border-accent-500 bg-accent-500/10 text-accent-500"
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
                  <Loader2 className="h-3.5 w-3.5 animate-spin" /> Chargement
                  de tes tâches…
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
                placeholder="Ex. Tournage chez le client"
                maxLength={255}
                className={FIELD}
              />
              {noImportables ? (
                <p className="mt-1 text-[11px] text-white/50">
                  Aucune tâche assignée : décris ce que tu fais.
                </p>
              ) : null}
            </div>
          )}

          <button
            type="submit"
            disabled={busy}
            className={`${BTN} bg-blue-600 disabled:opacity-60`}
          >
            {busy ? (
              <Loader2 className="h-5 w-5 animate-spin" />
            ) : (
              <Play className="h-5 w-5" />
            )}
            Commencer
          </button>
        </form>
      ) : (
        <>
          <p className="mt-2 text-sm text-white/60">
            Lance le chrono quand tu commences une tâche. À l&apos;arrêt, les
            heures s&apos;ajoutent à ta feuille de temps.
          </p>
          {bloque ? (
            <p className="mt-2 text-xs font-semibold text-amber-300">
              {bloque}
            </p>
          ) : companies.length === 0 ? (
            <p className="mt-2 text-xs font-semibold text-amber-300">
              Aucune compagnie dans ta feuille : demande à un gestionnaire de
              t&apos;en assigner une.
            </p>
          ) : null}
          <button
            type="button"
            onClick={() => void openForm()}
            disabled={!!bloque || companies.length === 0}
            className={`mt-3 ${BTN} bg-blue-600 disabled:opacity-50`}
          >
            <Play className="h-5 w-5" /> Commencer un punch
          </button>
        </>
      )}
    </section>
  );
}
