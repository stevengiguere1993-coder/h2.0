"use client";

/**
 * Feuille de temps « par tâche » (Steven 2026-10-04).
 *
 * L'employé décrit sa période jour par jour : il importe les tâches
 * Gestion d'entreprises qui lui sont assignées (compagnie déjà choisie)
 * ou ajoute une tâche à la main en choisissant la compagnie, puis inscrit
 * ses heures. La grille compagnie × jour est dérivée de ces lignes côté
 * serveur — paie, refacturation et QuickBooks ne changent pas.
 *
 * Un gestionnaire peut réimputer une ligne à une autre compagnie après
 * coup, et limiter les compagnies qu'un employé voit (modal
 * « Compagnies de … »).
 */

import { useEffect, useMemo, useState } from "react";
import {
  Building2,
  CheckSquare,
  Download,
  Loader2,
  Plus,
  Square,
  Trash2,
  X
} from "lucide-react";

import { authedFetch } from "@/lib/auth";

export const DAYS = 14;
const WEEKDAYS = ["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"];
const MONTHS_SHORT = [
  "janv.", "févr.", "mars", "avr.", "mai", "juin",
  "juil.", "août", "sept.", "oct.", "nov.", "déc."
];

const BTN_PRIMARY = "btn-accent btn-sm disabled:cursor-not-allowed disabled:opacity-40";
const BTN_GHOST = "btn-secondary btn-sm disabled:cursor-not-allowed disabled:opacity-40";
const CARD =
  "rounded-2xl border border-[var(--qg-border)] bg-[var(--qg-card-bg)] p-4";
const INPUT =
  "rounded-lg border border-[var(--qg-border)] bg-[var(--qg-bg)]/40 px-3 py-2 text-sm outline-none focus:border-[var(--qg-accent)] disabled:opacity-60";

// ── Types ──────────────────────────────────────────────────────────────

/** Ligne telle que renvoyée par l'API (champ `taches` du détail). */
export type TacheLigneOut = {
  id: number;
  day_index: number;
  company_id: number;
  company_label: string;
  entreprise_tache_id?: number | null;
  title: string;
  hours: number;
};

/** Ligne en cours d'édition (heures en texte brut pour les décimales). */
export type TacheLigne = {
  key: string;
  day_index: number;
  company_id: number;
  entreprise_tache_id: number | null;
  title: string;
  hours: string;
};

export type CompagnieOption = {
  id: number;
  label: string;
  nr_autorise: boolean;
};

type TacheImportable = {
  id: number;
  title: string;
  status: string;
  entreprise_id: number;
  entreprise_name: string;
  company_id?: number | null;
  due_date?: string | null;
  completed_at?: string | null;
};

let _seq = 0;
export function newKey(): string {
  _seq += 1;
  return `l${Date.now().toString(36)}${_seq}`;
}

export function fromApi(rows: TacheLigneOut[]): TacheLigne[] {
  return rows.map((r) => ({
    key: `api-${r.id}`,
    day_index: r.day_index,
    company_id: r.company_id,
    entreprise_tache_id: r.entreprise_tache_id ?? null,
    title: r.title,
    hours: r.hours ? String(r.hours) : ""
  }));
}

export function parseHours(s: string): number {
  const v = parseFloat((s || "").replace(",", "."));
  return Number.isFinite(v) && v > 0 ? v : 0;
}

function parseISO(d: string): Date {
  const [y, m, dd] = d.split("-").map(Number);
  return new Date(y, m - 1, dd);
}

function fmtDay(iso: string): { wd: string; day: number; month: string } {
  const d = parseISO(iso);
  const dow = (d.getDay() + 6) % 7;
  return { wd: WEEKDAYS[dow], day: d.getDate(), month: MONTHS_SHORT[d.getMonth()] };
}

// ── Éditeur ────────────────────────────────────────────────────────────

export function TachesEditor({
  timesheetId,
  joursDates,
  companies,
  lignes,
  canEdit,
  isManager,
  onChange
}: {
  timesheetId: number;
  joursDates: string[];
  companies: CompagnieOption[];
  lignes: TacheLigne[];
  canEdit: boolean;
  isManager: boolean;
  onChange: (next: TacheLigne[]) => void;
}) {
  // Jour sélectionné : aujourd'hui s'il est dans la période, sinon le
  // premier jour qui a des lignes, sinon le lundi de la semaine 1.
  const [day, setDay] = useState<number>(() => {
    const today = new Date();
    const iso = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`;
    const idx = joursDates.indexOf(iso);
    if (idx >= 0) return idx;
    const first = lignes.find(() => true);
    return first ? first.day_index : 0;
  });
  const [importing, setImporting] = useState(false);

  const perDay = useMemo(() => {
    const arr = new Array(DAYS).fill(0) as number[];
    for (const l of lignes) arr[l.day_index] += parseHours(l.hours);
    return arr.map((h) => Math.round(h * 100) / 100);
  }, [lignes]);
  const total = Math.round(perDay.reduce((a, b) => a + b, 0) * 100) / 100;

  const dayLines = lignes.filter((l) => l.day_index === day);
  // Aucune compagnie visible (toutes retirées / désactivées) : on ne crée
  // pas de ligne orpheline (company_id 0 serait refusé à l'enregistrement).
  const sansCompagnie = companies.length === 0;
  const defaultCompany = companies[0]?.id ?? 0;

  const update = (key: string, patch: Partial<TacheLigne>) =>
    onChange(lignes.map((l) => (l.key === key ? { ...l, ...patch } : l)));
  const remove = (key: string) => onChange(lignes.filter((l) => l.key !== key));
  const addManual = () =>
    sansCompagnie
      ? undefined
      : onChange([
      ...lignes,
      {
        key: newKey(),
        day_index: day,
        company_id: defaultCompany,
        entreprise_tache_id: null,
        title: "",
        hours: ""
      }
    ]);
  const addImported = (taches: TacheImportable[]) => {
    if (sansCompagnie) {
      setImporting(false);
      return;
    }
    const known = new Set(companies.map((c) => c.id));
    onChange([
      ...lignes,
      ...taches.map((t) => ({
        key: newKey(),
        day_index: day,
        company_id:
          t.company_id && known.has(t.company_id) ? t.company_id : defaultCompany,
        entreprise_tache_id: t.id,
        title: t.title,
        hours: ""
      }))
    ]);
    setImporting(false);
  };

  const setHours = (key: string, value: string) => {
    if (!/^[0-9]*[.,]?[0-9]*$/.test(value)) return;
    update(key, { hours: value });
  };

  return (
    <div className="space-y-4">
      {/* Bandeau des 14 jours */}
      <div className="overflow-x-auto rounded-2xl border border-[var(--qg-border)] bg-[var(--qg-card-bg)] p-2">
        <div className="flex min-w-max gap-1">
          {joursDates.map((iso, i) => {
            const f = fmtDay(iso);
            const active = i === day;
            const weekend = f.wd === "Sam" || f.wd === "Dim";
            return (
              <button
                key={iso}
                type="button"
                onClick={() => setDay(i)}
                className={`flex w-[68px] flex-col items-center rounded-xl border px-1 py-2 text-xs transition ${
                  active
                    ? "border-[var(--qg-accent)] bg-[var(--qg-accent)]/10 font-semibold"
                    : "border-transparent hover:border-[var(--qg-border)]"
                } ${i === 7 ? "ml-2" : ""}`}
                title={`${f.wd} ${f.day} ${f.month}`}
              >
                <span className={weekend ? "text-[var(--qg-text-faint)]" : "text-[var(--qg-text-muted)]"}>
                  {f.wd}
                </span>
                <span className="text-sm">{f.day}</span>
                <span
                  className={`mt-1 rounded-full px-1.5 text-[11px] tabular-nums ${
                    perDay[i] > 0
                      ? "bg-amber-500/15 font-semibold text-amber-400"
                      : "text-[var(--qg-text-faint)]"
                  }`}
                >
                  {perDay[i] > 0 ? `${perDay[i].toLocaleString("fr-CA")} h` : "—"}
                </span>
              </button>
            );
          })}
        </div>
      </div>

      {/* Lignes du jour */}
      <div className={CARD}>
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <div>
            <div className="text-sm font-semibold">
              {(() => {
                const f = fmtDay(joursDates[day]);
                return `${f.wd} ${f.day} ${f.month}`;
              })()}
            </div>
            <div className="text-xs text-[var(--qg-text-muted)]">
              {dayLines.length === 0
                ? "Aucune tâche pour cette journée."
                : `${dayLines.length} tâche${dayLines.length > 1 ? "s" : ""} · ${perDay[day].toLocaleString("fr-CA")} h`}
            </div>
          </div>
          {canEdit && (
            <div className="flex flex-wrap items-center gap-2">
              <button
                type="button"
                className={BTN_GHOST}
                onClick={() => setImporting(true)}
                disabled={sansCompagnie}
                title="Reprendre les tâches du pôle Entreprises qui te sont assignées"
              >
                <Download className="h-4 w-4" /> Importer mes tâches
              </button>
              <button
                type="button"
                className={BTN_PRIMARY}
                onClick={addManual}
                disabled={sansCompagnie}
              >
                <Plus className="h-4 w-4" /> Ajouter une tâche
              </button>
            </div>
          )}
        </div>

        {sansCompagnie && (
          <div className="rounded-xl border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-300">
            Aucune entreprise n&apos;est disponible dans cette feuille. Demande à
            un gestionnaire d&apos;en assigner (bouton « Compagnies de … »).
          </div>
        )}

        {dayLines.length > 0 && (
          <div className="space-y-2">
            <div className="hidden grid-cols-[1fr_220px_90px_36px] gap-2 px-1 text-xs font-medium uppercase tracking-wide text-[var(--qg-text-muted)] sm:grid">
              <div>Tâche</div>
              <div>Entreprise</div>
              <div className="text-right">Heures</div>
              <div />
            </div>
            {dayLines.map((l) => (
              <div
                key={l.key}
                className="grid grid-cols-1 gap-2 rounded-xl border border-[var(--qg-border)]/60 p-2 sm:grid-cols-[1fr_220px_90px_36px] sm:items-center sm:border-0 sm:p-0"
              >
                <div className="min-w-0">
                  <input
                    value={l.title}
                    disabled={!canEdit}
                    onChange={(e) => update(l.key, { title: e.target.value })}
                    placeholder="Description de la tâche"
                    className={`${INPUT} w-full`}
                  />
                  {l.entreprise_tache_id ? (
                    <div className="mt-0.5 px-1 text-[11px] text-[var(--qg-text-faint)]">
                      Importée des tâches du pôle Entreprises
                    </div>
                  ) : null}
                </div>
                <select
                  value={l.company_id}
                  disabled={!canEdit}
                  onChange={(e) => update(l.key, { company_id: Number(e.target.value) })}
                  className={`${INPUT} w-full`}
                  title={
                    isManager
                      ? "Changer l'entreprise réimpute les heures (refacturation)"
                      : "Pour quelle entreprise ?"
                  }
                >
                  {!companies.some((c) => c.id === l.company_id) && (
                    <option value={l.company_id}>Compagnie retirée</option>
                  )}
                  {companies.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.label}
                      {c.nr_autorise ? " · interne" : ""}
                    </option>
                  ))}
                </select>
                <div className="flex items-center justify-between gap-2 sm:justify-end">
                  <span className="text-xs text-[var(--qg-text-muted)] sm:hidden">Heures</span>
                  <input
                    inputMode="decimal"
                    value={l.hours}
                    disabled={!canEdit}
                    onChange={(e) => setHours(l.key, e.target.value)}
                    placeholder="0"
                    className={`${INPUT} w-24 text-right tabular-nums sm:w-full`}
                  />
                </div>
                <div className="flex justify-end">
                  {canEdit && (
                    <button
                      type="button"
                      onClick={() => remove(l.key)}
                      className="rounded-lg p-2 text-[var(--qg-text-muted)] hover:bg-rose-500/10 hover:text-rose-400"
                      aria-label="Retirer la tâche"
                    >
                      <Trash2 className="h-4 w-4" />
                    </button>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="flex items-center justify-end text-sm text-[var(--qg-text-muted)]">
        Total de la période :{" "}
        <span className="ml-1 font-semibold text-[var(--qg-text)]">
          {total.toLocaleString("fr-CA")} h
        </span>
      </div>

      {importing && (
        <ImportModal
          timesheetId={timesheetId}
          dejaImportees={new Set(
            dayLines
              .map((l) => l.entreprise_tache_id)
              .filter((x): x is number => x != null)
          )}
          onClose={() => setImporting(false)}
          onImport={addImported}
        />
      )}
    </div>
  );
}

// ── Import des tâches Gestion d'entreprises ────────────────────────────

const STATUS_LABEL: Record<string, string> = {
  todo: "À venir",
  a_faire: "À faire",
  in_progress: "En traitement",
  waiting: "En attente",
  done: "Terminée",
  backlog: "Backlog"
};

function ImportModal({
  timesheetId,
  dejaImportees,
  onClose,
  onImport
}: {
  timesheetId: number;
  dejaImportees: Set<number>;
  onClose: () => void;
  onImport: (t: TacheImportable[]) => void;
}) {
  const [rows, setRows] = useState<TacheImportable[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [sel, setSel] = useState<Set<number>>(new Set());
  const [q, setQ] = useState("");

  useEffect(() => {
    void (async () => {
      try {
        const r = await authedFetch(
          `/api/v1/timesheets/${timesheetId}/taches-importables`
        );
        if (!r.ok) throw new Error((await r.text()) || `Erreur ${r.status}`);
        setRows(await r.json());
      } catch (e: any) {
        setErr(e?.message || "Chargement impossible");
        setRows([]);
      }
    })();
  }, [timesheetId]);

  const filtered = (rows || []).filter((t) => {
    if (!q.trim()) return true;
    const s = q.trim().toLowerCase();
    return (
      t.title.toLowerCase().includes(s) ||
      t.entreprise_name.toLowerCase().includes(s)
    );
  });

  const toggle = (id: number) =>
    setSel((prev) => {
      const n = new Set(prev);
      if (n.has(id)) n.delete(id);
      else n.add(id);
      return n;
    });

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/50 p-4 pt-16"
      onClick={onClose}
    >
      <div className={`${CARD} w-full max-w-xl`} onClick={(e) => e.stopPropagation()}>
        <div className="mb-3 flex items-center justify-between">
          <div>
            <div className="text-base font-semibold">Importer mes tâches</div>
            <div className="text-xs text-[var(--qg-text-muted)]">
              Tâches du pôle Entreprises qui te sont assignées — en cours ou
              terminées pendant la période.
            </div>
          </div>
          <button type="button" onClick={onClose} className="rounded-lg p-1.5 hover:bg-[var(--qg-bg)]" aria-label="Fermer">
            <X className="h-4 w-4" />
          </button>
        </div>
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Filtrer par tâche ou entreprise…"
          className={`${INPUT} mb-3 w-full`}
        />
        {err && (
          <div className="mb-3 rounded-xl border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-300">
            {err}
          </div>
        )}
        {rows === null ? (
          <div className="flex items-center justify-center py-10 text-[var(--qg-text-muted)]">
            <Loader2 className="mr-2 h-5 w-5 animate-spin" /> Chargement…
          </div>
        ) : filtered.length === 0 ? (
          <div className="py-8 text-center text-sm text-[var(--qg-text-muted)]">
            Aucune tâche assignée à importer. Tu peux ajouter une tâche à la main.
          </div>
        ) : (
          <ul className="max-h-[50vh] divide-y divide-[var(--qg-border)]/60 overflow-y-auto">
            {filtered.map((t) => {
              const deja = dejaImportees.has(t.id);
              const on = sel.has(t.id);
              return (
                <li key={t.id}>
                  <button
                    type="button"
                    disabled={deja}
                    onClick={() => toggle(t.id)}
                    className="flex w-full items-start gap-3 px-1 py-2.5 text-left hover:bg-[var(--qg-bg)]/40 disabled:cursor-default disabled:opacity-50"
                  >
                    {on ? (
                      <CheckSquare className="mt-0.5 h-4 w-4 shrink-0 text-accent-500" />
                    ) : (
                      <Square className="mt-0.5 h-4 w-4 shrink-0 text-[var(--qg-text-faint)]" />
                    )}
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm font-medium">{t.title}</span>
                      <span className="block text-xs text-[var(--qg-text-muted)]">
                        {t.entreprise_name} · {STATUS_LABEL[t.status] || t.status}
                        {deja ? " · déjà dans cette journée" : ""}
                      </span>
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
        )}
        <div className="mt-4 flex items-center justify-end gap-2">
          <button type="button" className={BTN_GHOST} onClick={onClose}>
            Annuler
          </button>
          <button
            type="button"
            className={BTN_PRIMARY}
            disabled={sel.size === 0}
            onClick={() => onImport((rows || []).filter((t) => sel.has(t.id)))}
          >
            <Download className="h-4 w-4" />
            Importer {sel.size > 0 ? `(${sel.size})` : ""}
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Compagnies assignées à un employé (gestionnaire) ───────────────────

type Company = { id: number; label: string; is_active: boolean };

export function UserCompaniesModal({
  userId,
  employeeName,
  onClose,
  onSaved
}: {
  userId: number;
  employeeName: string;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [companies, setCompanies] = useState<Company[]>([]);
  const [sel, setSel] = useState<Set<number>>(new Set());
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    void (async () => {
      try {
        const [rc, ru] = await Promise.all([
          authedFetch("/api/v1/timesheets/companies"),
          authedFetch(`/api/v1/timesheets/user-companies?user_id=${userId}`)
        ]);
        if (!rc.ok) throw new Error((await rc.text()) || `Erreur ${rc.status}`);
        if (!ru.ok) throw new Error((await ru.text()) || `Erreur ${ru.status}`);
        setCompanies(await rc.json());
        const u = (await ru.json()) as { company_ids: number[] };
        setSel(new Set(u.company_ids));
      } catch (e: any) {
        setErr(e?.message || "Chargement impossible");
      } finally {
        setLoading(false);
      }
    })();
  }, [userId]);

  const toggle = (id: number) =>
    setSel((prev) => {
      const n = new Set(prev);
      if (n.has(id)) n.delete(id);
      else n.add(id);
      return n;
    });

  const save = async () => {
    setSaving(true);
    setErr(null);
    try {
      const r = await authedFetch("/api/v1/timesheets/user-companies", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user_id: userId, company_ids: Array.from(sel) })
      });
      if (!r.ok) throw new Error((await r.text()) || `Erreur ${r.status}`);
      onSaved();
    } catch (e: any) {
      setErr(e?.message || "Sauvegarde impossible");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/50 p-4 pt-16"
      onClick={onClose}
    >
      <div className={`${CARD} w-full max-w-lg`} onClick={(e) => e.stopPropagation()}>
        <div className="mb-3 flex items-center justify-between">
          <div>
            <div className="flex items-center gap-2 text-base font-semibold">
              <Building2 className="h-4 w-4" /> Compagnies de {employeeName}
            </div>
            <div className="text-xs text-[var(--qg-text-muted)]">
              Coche les compagnies pour lesquelles {employeeName} travaille : sa
              feuille ne montrera que celles-là. Rien de coché = toutes les
              compagnies.
            </div>
          </div>
          <button type="button" onClick={onClose} className="rounded-lg p-1.5 hover:bg-[var(--qg-bg)]" aria-label="Fermer">
            <X className="h-4 w-4" />
          </button>
        </div>
        {err && (
          <div className="mb-3 rounded-xl border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-300">
            {err}
          </div>
        )}
        {loading ? (
          <div className="flex items-center justify-center py-10 text-[var(--qg-text-muted)]">
            <Loader2 className="mr-2 h-5 w-5 animate-spin" /> Chargement…
          </div>
        ) : (
          <ul className="max-h-[50vh] divide-y divide-[var(--qg-border)]/60 overflow-y-auto">
            {companies.map((c) => {
              const on = sel.has(c.id);
              return (
                <li key={c.id}>
                  <button
                    type="button"
                    onClick={() => toggle(c.id)}
                    className="flex w-full items-center gap-3 px-1 py-2.5 text-left text-sm hover:bg-[var(--qg-bg)]/40"
                  >
                    {on ? (
                      <CheckSquare className="h-4 w-4 shrink-0 text-accent-500" />
                    ) : (
                      <Square className="h-4 w-4 shrink-0 text-[var(--qg-text-faint)]" />
                    )}
                    <span className={on ? "font-medium" : ""}>{c.label}</span>
                  </button>
                </li>
              );
            })}
          </ul>
        )}
        <div className="mt-4 flex items-center justify-between gap-2">
          <span className="text-xs text-[var(--qg-text-muted)]">
            {sel.size === 0 ? "Toutes les compagnies" : `${sel.size} compagnie${sel.size > 1 ? "s" : ""}`}
          </span>
          <div className="flex items-center gap-2">
            <button type="button" className={BTN_GHOST} onClick={onClose}>
              Annuler
            </button>
            <button type="button" className={BTN_PRIMARY} disabled={saving || loading} onClick={() => void save()}>
              {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
              Enregistrer
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
