"use client";

import { useEffect, useMemo, useState } from "react";
import {
  Check,
  ChevronLeft,
  ChevronRight,
  Download,
  Loader2,
  Plus,
  Trash2
} from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { Link } from "@/i18n/navigation";
import { useAppLayout } from "../../layout";
import { authedFetch } from "@/lib/auth";

type Employe = { id: number; full_name: string; email: string | null };
type Project = { id: number; name: string };
type Prospect = { id: number; name: string; status: string };

type Punch = {
  id: number;
  employe_id: number;
  project_id: number | null;
  contact_request_id: number | null;
  started_at: string;
  ended_at: string | null;
  hours: number | string | null;
  task: string | null;
  geolocation: string | null;
  approved: boolean;
  notes: string | null;
};

function pad(n: number): string {
  return String(n).padStart(2, "0");
}

function isoLocal(d: Date): string {
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(
    d.getDate()
  )}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function fmtDateTime(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleString("fr-CA", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit"
  });
}

function weekStartOf(d: Date): Date {
  const copy = new Date(d);
  copy.setHours(0, 0, 0, 0);
  const day = copy.getDay();
  const diff = (day + 6) % 7; // Monday = 0
  copy.setDate(copy.getDate() - diff);
  return copy;
}

function shortISO(d: Date): string {
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

export default function PunchGestionPage() {
  const { onOpenSidebar } = useAppLayout();

  const [weekStart, setWeekStart] = useState(() => weekStartOf(new Date()));
  const [punches, setPunches] = useState<Punch[]>([]);
  const [employes, setEmployes] = useState<Employe[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [prospects, setProspects] = useState<Prospect[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [modal, setModal] = useState<null | Punch | { fresh: true }>(null);
  const [filterEmploye, setFilterEmploye] = useState("");

  const weekEnd = useMemo(() => {
    const d = new Date(weekStart);
    d.setDate(d.getDate() + 7);
    return d;
  }, [weekStart]);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const [pRes, eRes, prRes, csRes] = await Promise.all([
          authedFetch("/api/v1/punch?limit=500"),
          authedFetch("/api/v1/employes?limit=500"),
          authedFetch("/api/v1/projects?limit=500"),
          authedFetch("/api/v1/contact?limit=500")
        ]);
        if (!pRes.ok) throw new Error(`http_${pRes.status}`);
        const ps = (await pRes.json()) as Punch[];
        const es = eRes.ok ? ((await eRes.json()) as Employe[]) : [];
        const prs = prRes.ok ? ((await prRes.json()) as Project[]) : [];
        const css = csRes.ok ? ((await csRes.json()) as Prospect[]) : [];
        if (cancelled) return;
        setPunches(ps);
        setEmployes(es);
        setProjects(prs);
        setProspects(css);
      } catch {
        if (!cancelled) setError("Impossible de charger les punches.");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, []);

  const empById = useMemo(() => {
    const m = new Map<number, Employe>();
    employes.forEach((e) => m.set(e.id, e));
    return m;
  }, [employes]);

  const projById = useMemo(() => {
    const m = new Map<number, Project>();
    projects.forEach((p) => m.set(p.id, p));
    return m;
  }, [projects]);

  const prospById = useMemo(() => {
    const m = new Map<number, Prospect>();
    prospects.forEach((c) => m.set(c.id, c));
    return m;
  }, [prospects]);

  const visible = useMemo(() => {
    return punches
      .filter((p) => {
        const d = new Date(p.started_at);
        if (d < weekStart || d >= weekEnd) return false;
        if (filterEmploye && String(p.employe_id) !== filterEmploye) return false;
        return true;
      })
      .sort(
        (a, b) =>
          new Date(b.started_at).getTime() - new Date(a.started_at).getTime()
      );
  }, [punches, weekStart, weekEnd, filterEmploye]);

  const totalHours = useMemo(
    () =>
      visible.reduce(
        (sum, p) => sum + (p.hours != null ? Number(p.hours) : 0),
        0
      ),
    [visible]
  );

  function upsert(p: Punch) {
    setPunches((xs) => {
      const i = xs.findIndex((x) => x.id === p.id);
      if (i === -1) return [...xs, p];
      const n = xs.slice();
      n[i] = p;
      return n;
    });
  }

  async function toggleApprove(p: Punch) {
    try {
      const res = await authedFetch(`/api/v1/punch/${p.id}`, {
        method: "PATCH",
        body: JSON.stringify({ approved: !p.approved })
      });
      if (!res.ok) throw new Error();
      upsert((await res.json()) as Punch);
    } catch {
      setError("Approbation échouée.");
    }
  }

  async function remove(p: Punch) {
    if (!confirm(`Supprimer le punch du ${fmtDateTime(p.started_at)} ?`))
      return;
    try {
      const res = await authedFetch(`/api/v1/punch/${p.id}`, {
        method: "DELETE"
      });
      if (!res.ok && res.status !== 204) throw new Error();
      setPunches((xs) => xs.filter((x) => x.id !== p.id));
    } catch {
      setError("Suppression échouée.");
    }
  }

  return (
    <>
      <AppTopbar
        breadcrumbs={[{ label: "Construction", href: "/app" }, { label: "Punch / Temps", href: "/app/punch" }, { label: "Gestion" }]}
        onOpenSidebar={onOpenSidebar}
        rightSlot={
          <div className="flex items-center gap-2">
            <PayrollExportButton />
            <button
              type="button"
              onClick={() => setModal({ fresh: true })}
              className="btn-accent text-sm"
            >
              <Plus className="mr-1.5 h-4 w-4" /> Nouveau punch
            </button>
          </div>
        }
      />

      <div className="p-4 lg:p-6">
        {error ? (
          <p className="mb-4 rounded-lg border border-rose-500/40 bg-rose-500/10 px-4 py-2 text-sm text-rose-300">
            {error}
          </p>
        ) : null}

        <div className="mb-4 flex flex-wrap items-center gap-3">
          <Link
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            href={"/app/punch" as any}
            className="btn-secondary text-xs"
          >
            ← Vue employé
          </Link>

          <div className="flex items-center gap-1 rounded-lg border border-brand-800 bg-brand-900 p-1">
            <button
              type="button"
              onClick={() => {
                const d = new Date(weekStart);
                d.setDate(d.getDate() - 7);
                setWeekStart(d);
              }}
              className="rounded-md p-1.5 text-white/70 hover:bg-brand-800 hover:text-white"
              aria-label="Semaine précédente"
            >
              <ChevronLeft className="h-4 w-4" />
            </button>
            <span className="min-w-[180px] px-2 text-center text-sm font-semibold text-white">
              Sem. {shortISO(weekStart)} → {shortISO(new Date(weekEnd.getTime() - 1))}
            </span>
            <button
              type="button"
              onClick={() => {
                const d = new Date(weekStart);
                d.setDate(d.getDate() + 7);
                setWeekStart(d);
              }}
              className="rounded-md p-1.5 text-white/70 hover:bg-brand-800 hover:text-white"
              aria-label="Semaine suivante"
            >
              <ChevronRight className="h-4 w-4" />
            </button>
          </div>

          <button
            type="button"
            onClick={() => setWeekStart(weekStartOf(new Date()))}
            className="btn-secondary text-xs"
          >
            Cette semaine
          </button>

          <select
            value={filterEmploye}
            onChange={(e) => setFilterEmploye(e.target.value)}
            className="input ml-auto w-48"
          >
            <option value="">Tous les employés</option>
            {employes.map((e) => (
              <option key={e.id} value={String(e.id)}>
                {e.full_name}
              </option>
            ))}
          </select>

          <div className="rounded-md bg-brand-900 px-3 py-2 text-sm">
            <span className="text-white/50">Total </span>
            <span className="font-bold text-white">
              {totalHours.toFixed(2)} h
            </span>
          </div>
        </div>

        {loading ? (
          <div className="flex min-h-[40vh] items-center justify-center">
            <Loader2 className="h-6 w-6 animate-spin text-accent-500" />
          </div>
        ) : visible.length === 0 ? (
          <p className="rounded-2xl border border-dashed border-brand-800 bg-brand-900/40 px-6 py-10 text-center text-sm text-white/60">
            Aucun punch pour cette semaine.
          </p>
        ) : (
          <div className="overflow-x-auto rounded-xl border border-brand-800 bg-brand-900">
            <table className="w-full text-sm">
              <thead className="border-b border-brand-800 text-left text-xs uppercase tracking-wider text-white/50">
                <tr>
                  <th className="px-4 py-3">Employé</th>
                  <th className="px-4 py-3">Cible</th>
                  <th className="px-4 py-3">Début</th>
                  <th className="px-4 py-3">Fin</th>
                  <th className="px-4 py-3 text-right">Heures</th>
                  <th className="px-4 py-3">Tâche</th>
                  <th className="px-4 py-3 text-center">Approuvé</th>
                  <th className="px-4 py-3"></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-brand-800">
                {visible.map((p) => {
                  const emp = empById.get(p.employe_id);
                  const proj = p.project_id ? projById.get(p.project_id) : null;
                  const prospect = p.contact_request_id
                    ? prospById.get(p.contact_request_id)
                    : null;
                  const target = proj
                    ? `Projet — ${proj.name}`
                    : prospect
                    ? `Prospect — ${prospect.name}`
                    : "Administration";
                  return (
                    <tr
                      key={p.id}
                      onClick={() => setModal(p)}
                      className="cursor-pointer hover:bg-brand-800/50"
                    >
                      <td className="px-4 py-3 font-semibold text-white">
                        {emp?.full_name || `#${p.employe_id}`}
                      </td>
                      <td className="px-4 py-3 text-white/70">{target}</td>
                      <td className="px-4 py-3 text-white/70">
                        {fmtDateTime(p.started_at)}
                      </td>
                      <td className="px-4 py-3 text-white/70">
                        {p.ended_at ? fmtDateTime(p.ended_at) : (
                          <span className="text-accent-500">EN COURS</span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-right font-semibold text-white">
                        {p.hours != null ? `${Number(p.hours).toFixed(2)}` : "—"}
                      </td>
                      <td className="px-4 py-3 text-xs text-white/60">
                        <span className="line-clamp-1">{p.task || "—"}</span>
                      </td>
                      <td className="px-4 py-3 text-center">
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            toggleApprove(p);
                          }}
                          className={`rounded-md px-2 py-1 text-[10px] font-semibold ${
                            p.approved
                              ? "bg-emerald-500/20 text-emerald-300 hover:bg-emerald-500/30"
                              : "bg-white/5 text-white/50 hover:bg-white/10"
                          }`}
                        >
                          {p.approved ? (
                            <span className="inline-flex items-center gap-1">
                              <Check className="h-3 w-3" />
                              Approuvé
                            </span>
                          ) : (
                            "À approuver"
                          )}
                        </button>
                      </td>
                      <td className="px-4 py-3 text-right">
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            remove(p);
                          }}
                          className="text-rose-400 hover:text-rose-300"
                          aria-label="Supprimer"
                        >
                          <Trash2 className="h-4 w-4" />
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {modal ? (
        <PunchModal
          seed={modal}
          employes={employes}
          projects={projects}
          prospects={prospects}
          onClose={() => setModal(null)}
          onSaved={(p) => {
            upsert(p);
            setModal(null);
          }}
        />
      ) : null}
    </>
  );
}

function PunchModal({
  seed,
  employes,
  projects,
  prospects,
  onClose,
  onSaved
}: {
  seed: Punch | { fresh: true };
  employes: Employe[];
  projects: Project[];
  prospects: Prospect[];
  onClose: () => void;
  onSaved: (p: Punch) => void;
}) {
  const existing = "id" in seed ? seed : null;
  const [employeId, setEmployeId] = useState(
    existing ? String(existing.employe_id) : ""
  );
  const [target, setTarget] = useState(
    existing
      ? existing.project_id
        ? `p-${existing.project_id}`
        : existing.contact_request_id
        ? `c-${existing.contact_request_id}`
        : ""
      : ""
  );
  const [startedAt, setStartedAt] = useState(
    existing ? isoLocal(new Date(existing.started_at)) : isoLocal(new Date())
  );
  const [endedAt, setEndedAt] = useState(
    existing?.ended_at ? isoLocal(new Date(existing.ended_at)) : ""
  );
  const [task, setTask] = useState(existing?.task || "");
  const [notes, setNotes] = useState(existing?.notes || "");
  const [approved, setApproved] = useState(existing?.approved ?? false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const computedHours = useMemo(() => {
    if (!startedAt || !endedAt) return null;
    const ms =
      new Date(endedAt).getTime() - new Date(startedAt).getTime();
    if (ms < 0) return null;
    return Math.round((ms / 3600_000) * 100) / 100;
  }, [startedAt, endedAt]);

  async function save(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!employeId) {
      setError("Choisis un employé.");
      return;
    }
    if (!startedAt) {
      setError("Date de début requise.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const payload: Record<string, unknown> = {
        employe_id: Number(employeId),
        started_at: new Date(startedAt).toISOString(),
        ended_at: endedAt ? new Date(endedAt).toISOString() : null,
        hours: computedHours,
        task: task.trim() || null,
        notes: notes.trim() || null,
        approved,
        project_id: target.startsWith("p-") ? Number(target.slice(2)) : null,
        contact_request_id: target.startsWith("c-")
          ? Number(target.slice(2))
          : null
      };

      const res = await authedFetch(
        existing ? `/api/v1/punch/${existing.id}` : "/api/v1/punch",
        {
          method: existing ? "PATCH" : "POST",
          body: JSON.stringify(payload)
        }
      );
      if (!res.ok) {
        const txt = await res.text();
        throw new Error(txt.slice(0, 240) || `http_${res.status}`);
      }
      onSaved((await res.json()) as Punch);
    } catch (err) {
      setError((err as Error).message);
      setBusy(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/70 p-4"
      onClick={() => (!busy ? onClose() : null)}
    >
      <form
        onSubmit={save}
        onClick={(e) => e.stopPropagation()}
        className="mt-10 w-full max-w-xl rounded-2xl border border-brand-800 bg-brand-950 p-6 shadow-2xl"
      >
        <h3 className="text-lg font-bold text-white">
          {existing ? "Modifier le punch" : "Nouveau punch (saisie manuelle)"}
        </h3>
        <p className="mt-1 text-xs text-white/60">
          Pour un employé qui a oublié de pointer ou un ajustement rétro.
        </p>

        <div className="mt-5 space-y-4">
          <div>
            <label htmlFor="p_emp" className="label">
              Employé <span className="text-rose-400">*</span>
            </label>
            <select
              id="p_emp"
              value={employeId}
              onChange={(e) => setEmployeId(e.target.value)}
              required
              className="input"
            >
              <option value="">— Sélectionner —</option>
              {employes.map((e) => (
                <option key={e.id} value={String(e.id)}>
                  {e.full_name}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label htmlFor="p_target" className="label">
              Projet ou prospect
            </label>
            <select
              id="p_target"
              value={target}
              onChange={(e) => setTarget(e.target.value)}
              className="input"
            >
              <option value="">— Administration —</option>
              {projects.length > 0 ? (
                <optgroup label="Projets">
                  {projects.map((p) => (
                    <option key={`p-${p.id}`} value={`p-${p.id}`}>
                      {p.name}
                    </option>
                  ))}
                </optgroup>
              ) : null}
              {prospects.length > 0 ? (
                <optgroup label="Prospects">
                  {prospects.map((c) => (
                    <option key={`c-${c.id}`} value={`c-${c.id}`}>
                      {c.name}
                    </option>
                  ))}
                </optgroup>
              ) : null}
            </select>
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <label htmlFor="p_start" className="label">
                Début <span className="text-rose-400">*</span>
              </label>
              <input
                id="p_start"
                type="datetime-local"
                required
                value={startedAt}
                onChange={(e) => setStartedAt(e.target.value)}
                className="input"
              />
            </div>
            <div>
              <label htmlFor="p_end" className="label">Fin</label>
              <input
                id="p_end"
                type="datetime-local"
                value={endedAt}
                onChange={(e) => setEndedAt(e.target.value)}
                className="input"
              />
            </div>
          </div>

          <div className="rounded-md bg-brand-900 px-3 py-2 text-sm">
            <span className="text-white/50">Heures calculées : </span>
            <span className="font-semibold text-white">
              {computedHours != null ? `${computedHours.toFixed(2)} h` : "—"}
            </span>
          </div>

          <div>
            <label htmlFor="p_task" className="label">Tâche</label>
            <input
              id="p_task"
              type="text"
              value={task}
              onChange={(e) => setTask(e.target.value)}
              placeholder="Ex. Démolition cuisine"
              className="input"
            />
          </div>

          <div>
            <label htmlFor="p_notes" className="label">Notes</label>
            <textarea
              id="p_notes"
              rows={2}
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              className="input"
            />
          </div>

          <label className="flex items-center gap-2 text-sm text-white/80">
            <input
              type="checkbox"
              checked={approved}
              onChange={(e) => setApproved(e.target.checked)}
            />
            Approuver ce punch pour la paie
          </label>
        </div>

        {error ? (
          <p className="mt-3 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
            {error}
          </p>
        ) : null}

        <div className="mt-6 flex items-center justify-end gap-3">
          <button
            type="button"
            onClick={onClose}
            disabled={busy}
            className="btn-secondary text-sm"
          >
            Annuler
          </button>
          <button
            type="submit"
            disabled={busy}
            className="btn-accent text-sm disabled:opacity-60"
          >
            {busy ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" /> Sauvegarde…
              </>
            ) : existing ? (
              "Enregistrer"
            ) : (
              "Créer le punch"
            )}
          </button>
        </div>
      </form>
    </div>
  );
}

type PayrollRow = {
  employe_id: number;
  employe_name: string;
  hourly_rate: number | null;
  approved_hours: number;
  pending_hours: number;
  total_hours: number;
  approved_revenue: number;
  total_revenue: number;
};

type PayrollReport = {
  month: string;
  period_start: string;
  period_end: string;
  rows: PayrollRow[];
  total_approved_hours: number;
  total_approved_revenue: number;
};

function defaultMonth(): string {
  const d = new Date();
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  return `${d.getFullYear()}-${mm}`;
}

function PayrollExportButton() {
  const [open, setOpen] = useState(false);
  const [month, setMonth] = useState(defaultMonth());
  const [loading, setLoading] = useState(false);
  const [report, setReport] = useState<PayrollReport | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function preview() {
    setLoading(true);
    setError(null);
    try {
      const res = await authedFetch(
        `/api/v1/punch/payroll?month=${month}`
      );
      if (!res.ok) throw new Error(`http_${res.status}`);
      setReport((await res.json()) as PayrollReport);
    } catch {
      setError("Chargement du rapport échoué.");
    } finally {
      setLoading(false);
    }
  }

  async function downloadCsv() {
    setLoading(true);
    setError(null);
    try {
      const res = await authedFetch(
        `/api/v1/punch/payroll.csv?month=${month}`
      );
      if (!res.ok) throw new Error();
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `paie-${month}.csv`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 10_000);
    } catch {
      setError("Téléchargement CSV échoué.");
    } finally {
      setLoading(false);
    }
  }

  function close() {
    setOpen(false);
    setReport(null);
    setError(null);
  }

  return (
    <>
      <button
        type="button"
        onClick={() => {
          setOpen(true);
          void preview();
        }}
        className="btn-secondary text-sm"
      >
        <Download className="mr-1.5 h-4 w-4" /> Paie (mois)
      </button>

      {open ? (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4"
          onClick={close}
        >
          <div
            className="w-full max-w-3xl overflow-hidden rounded-2xl border border-brand-800 bg-brand-950"
            onClick={(e) => e.stopPropagation()}
          >
            <header className="flex items-center justify-between border-b border-brand-800 px-4 py-3">
              <h3 className="text-sm font-bold text-white">
                Rapport paie mensuel
              </h3>
              <button
                type="button"
                onClick={close}
                className="text-white/60 hover:text-white"
                aria-label="Fermer"
              >
                ×
              </button>
            </header>

            <div className="flex flex-wrap items-center gap-3 border-b border-brand-800 p-4">
              <label className="text-xs text-white/70">
                Mois
                <input
                  type="month"
                  value={month}
                  onChange={(e) => setMonth(e.target.value)}
                  className="ml-2 rounded-md border border-brand-800 bg-brand-900 px-2 py-1 text-sm text-white"
                />
              </label>
              <button
                type="button"
                onClick={preview}
                disabled={loading}
                className="btn-secondary text-xs"
              >
                {loading ? (
                  <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                ) : null}
                Actualiser
              </button>
              <button
                type="button"
                onClick={downloadCsv}
                disabled={loading || !report || report.rows.length === 0}
                className="btn-accent text-xs disabled:opacity-60"
              >
                <Download className="mr-1.5 h-3.5 w-3.5" /> Télécharger CSV
              </button>
            </div>

            {error ? (
              <p className="border-b border-brand-800 bg-rose-500/10 px-4 py-2 text-xs text-rose-300">
                {error}
              </p>
            ) : null}

            <div className="max-h-[60vh] overflow-y-auto">
              {loading ? (
                <div className="flex items-center justify-center py-10">
                  <Loader2 className="h-5 w-5 animate-spin text-white/40" />
                </div>
              ) : !report || report.rows.length === 0 ? (
                <p className="px-4 py-10 text-center text-sm text-white/50">
                  Aucune heure sur {month}.
                </p>
              ) : (
                <table className="w-full text-sm">
                  <thead className="border-b border-brand-800 text-xs uppercase tracking-wider text-white/50">
                    <tr>
                      <th className="px-3 py-2 text-left">Employé</th>
                      <th className="px-3 py-2 text-right">Taux $/h</th>
                      <th className="px-3 py-2 text-right">Approuvé (h)</th>
                      <th className="px-3 py-2 text-right">En attente (h)</th>
                      <th className="px-3 py-2 text-right">Total (h)</th>
                      <th className="px-3 py-2 text-right">Paie approuvée</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-brand-800">
                    {report.rows.map((r) => (
                      <tr key={r.employe_id}>
                        <td className="px-3 py-2 text-white">
                          {r.employe_name}
                        </td>
                        <td className="px-3 py-2 text-right text-white/70">
                          {r.hourly_rate ? r.hourly_rate.toFixed(2) : "—"}
                        </td>
                        <td className="px-3 py-2 text-right text-emerald-300">
                          {r.approved_hours.toFixed(2)}
                        </td>
                        <td className="px-3 py-2 text-right text-amber-300">
                          {r.pending_hours.toFixed(2)}
                        </td>
                        <td className="px-3 py-2 text-right font-semibold text-white">
                          {r.total_hours.toFixed(2)}
                        </td>
                        <td className="px-3 py-2 text-right font-semibold text-white">
                          {new Intl.NumberFormat("fr-CA", {
                            style: "currency",
                            currency: "CAD",
                            maximumFractionDigits: 2
                          }).format(r.approved_revenue)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                  <tfoot>
                    <tr className="border-t border-brand-800">
                      <td
                        colSpan={4}
                        className="px-3 py-3 text-right text-xs text-white/60"
                      >
                        Totaux approuvés
                      </td>
                      <td className="px-3 py-3 text-right text-sm font-bold text-white">
                        {report.total_approved_hours.toFixed(2)} h
                      </td>
                      <td className="px-3 py-3 text-right text-sm font-bold text-emerald-300">
                        {new Intl.NumberFormat("fr-CA", {
                          style: "currency",
                          currency: "CAD",
                          maximumFractionDigits: 2
                        }).format(report.total_approved_revenue)}
                      </td>
                    </tr>
                  </tfoot>
                </table>
              )}
            </div>
            <p className="border-t border-brand-800 px-4 py-3 text-[11px] text-white/50">
              Seules les heures <strong>approuvées</strong> comptent pour
              la paie. Les shifts en attente doivent être approuvés (ou
              refusés) depuis la liste des punches avant la clôture.
            </p>
          </div>
        </div>
      ) : null}
    </>
  );
}
