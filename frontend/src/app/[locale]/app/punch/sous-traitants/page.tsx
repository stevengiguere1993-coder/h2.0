"use client";

import { useEffect, useMemo, useState } from "react";
import { ArrowLeft, Loader2, Plus, Trash2, Users } from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { Link } from "@/i18n/navigation";
import { useAppLayout } from "../../layout";
import { authedFetch } from "@/lib/auth";
import { useConfirm } from "@/components/confirm-dialog";

type SousTraitant = { id: number; full_name: string };
type Project = { id: number; name: string; address?: string | null };

type Timesheet = {
  id: number;
  sous_traitant_id: number;
  project_id: number | null;
  work_date: string; // YYYY-MM-DD
  worker_count: number;
  total_hours: number | string;
  notes: string | null;
  created_at: string;
};

function todayISO(): string {
  const d = new Date();
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

function num(v: number | string | null | undefined): number {
  if (v == null || v === "") return 0;
  const x = typeof v === "string" ? Number(v) : v;
  return Number.isFinite(x) ? x : 0;
}

// Heures décimales → « h/min » (ex. 7.5 → « 7 h 30 »), cohérent avec la
// gestion de temps des punchs.
function fmtHm(h: number): string {
  const totalMin = Math.round((h || 0) * 60);
  const hh = Math.floor(totalMin / 60);
  const mm = totalMin % 60;
  return `${hh} h ${String(mm).padStart(2, "0")}`;
}

function fmtDate(iso: string): string {
  // work_date est une date pure (YYYY-MM-DD) : on évite le décalage de
  // fuseau en la lisant en local sans conversion UTC.
  const [y, m, d] = iso.split("-").map(Number);
  if (!y || !m || !d) return iso;
  return new Date(y, m - 1, d).toLocaleDateString("fr-CA", {
    day: "2-digit",
    month: "short",
    year: "numeric"
  });
}

export default function SousTraitantTimesheetPage() {
  const confirm = useConfirm();
  const { onOpenSidebar } = useAppLayout();

  const [sts, setSts] = useState<SousTraitant[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [rows, setRows] = useState<Timesheet[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Filtre du récap par sous-traitant ("" = tous).
  const [filterSt, setFilterSt] = useState("");

  // Formulaire d'ajout.
  const [stId, setStId] = useState("");
  const [projectId, setProjectId] = useState("");
  const [workDate, setWorkDate] = useState(() => todayISO());
  const [workerCount, setWorkerCount] = useState("1");
  const [totalHours, setTotalHours] = useState("");
  const [notes, setNotes] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function loadAll() {
    setLoading(true);
    setError(null);
    try {
      const [stRes, prRes, tsRes] = await Promise.all([
        authedFetch("/api/v1/sous-traitants?limit=500"),
        authedFetch("/api/v1/projects?limit=500"),
        authedFetch("/api/v1/sous-traitant-timesheets?limit=500")
      ]);
      const st = stRes.ok ? ((await stRes.json()) as SousTraitant[]) : [];
      const pr = prRes.ok ? ((await prRes.json()) as Project[]) : [];
      const ts = tsRes.ok ? ((await tsRes.json()) as Timesheet[]) : [];
      setSts(st);
      setProjects(pr);
      setRows(ts);
    } catch {
      setError("Impossible de charger la feuille de temps.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadAll();
  }, []);

  const stName = useMemo(
    () => new Map(sts.map((s) => [s.id, s.full_name])),
    [sts]
  );
  const projName = useMemo(
    () => new Map(projects.map((p) => [p.id, p.address || p.name])),
    [projects]
  );

  const filteredRows = useMemo(() => {
    const base = filterSt
      ? rows.filter((r) => String(r.sous_traitant_id) === filterSt)
      : rows;
    // Plus récent en premier.
    return [...base].sort((a, b) =>
      a.work_date < b.work_date ? 1 : a.work_date > b.work_date ? -1 : b.id - a.id
    );
  }, [rows, filterSt]);

  // Récap : total des heures + cumul par sous-traitant (sur la sélection
  // courante du filtre).
  const recap = useMemo(() => {
    const totalHrs = filteredRows.reduce((s, r) => s + num(r.total_hours), 0);
    const perSt = new Map<number, { hours: number; entries: number }>();
    for (const r of filteredRows) {
      const cur = perSt.get(r.sous_traitant_id) || { hours: 0, entries: 0 };
      cur.hours += num(r.total_hours);
      cur.entries += 1;
      perSt.set(r.sous_traitant_id, cur);
    }
    return {
      totalHrs,
      entries: filteredRows.length,
      perSt: [...perSt.entries()]
        .map(([id, v]) => ({ id, ...v }))
        .sort((a, b) => b.hours - a.hours)
    };
  }, [filteredRows]);

  async function addEntry(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError(null);
    if (!stId) {
      setError("Sélectionne un sous-traitant.");
      return;
    }
    if (!totalHours || Number(totalHours) <= 0) {
      setError("Indique le nombre d'heures total (> 0).");
      return;
    }
    setSubmitting(true);
    try {
      const payload: Record<string, unknown> = {
        sous_traitant_id: Number(stId),
        work_date: workDate,
        worker_count: Math.max(1, Number(workerCount) || 1),
        total_hours: Number(totalHours)
      };
      if (projectId) payload.project_id = Number(projectId);
      if (notes.trim()) payload.notes = notes.trim();
      const res = await authedFetch("/api/v1/sous-traitant-timesheets", {
        method: "POST",
        body: JSON.stringify(payload)
      });
      if (!res.ok) {
        const txt = await res.text();
        throw new Error(txt.slice(0, 200) || `http_${res.status}`);
      }
      // Reset partiel : on garde sous-traitant / projet / date pour
      // enchaîner plusieurs saisies du même chantier.
      setTotalHours("");
      setNotes("");
      await loadAll();
    } catch (err) {
      setError(`Ajout échoué : ${(err as Error).message}`);
    } finally {
      setSubmitting(false);
    }
  }

  async function removeEntry(id: number) {
    const ok = await confirm({
      title: "Supprimer cette saisie ?",
      description: "Cette entrée de feuille de temps sera retirée du récap.",
      confirmLabel: "Supprimer",
      destructive: true
    });
    if (!ok) return;
    const prev = rows;
    setRows((xs) => xs.filter((x) => x.id !== id));
    try {
      const res = await authedFetch(`/api/v1/sous-traitant-timesheets/${id}`, {
        method: "DELETE"
      });
      if (!res.ok) throw new Error();
    } catch {
      setRows(prev);
      setError("Suppression échouée.");
    }
  }

  return (
    <>
      <AppTopbar
        breadcrumbs={[
          { label: "Construction", href: "/app" },
          { label: "Punch / Temps", href: "/app/punch" },
          { label: "Sous-traitants" }
        ]}
        onOpenSidebar={onOpenSidebar}
      />

      <div className="p-4 lg:p-6">
        <Link
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          href={"/app/punch/gestion" as any}
          className="inline-flex items-center text-sm text-white/70 hover:text-accent-500"
        >
          <ArrowLeft className="mr-1 h-4 w-4" /> Retour à la gestion de temps
        </Link>

        <div className="mt-4 flex items-center gap-2">
          <Users className="h-5 w-5 text-accent-500" />
          <h1 className="text-2xl font-bold text-white">
            Feuille de temps — sous-traitants
          </h1>
        </div>
        <p className="mt-1 text-sm text-white/60">
          Saisis le sous-traitant, le projet, le nombre de gars sur place et
          le total d&apos;heures (tous les gars cumulés) pour la journée.
        </p>

        {error ? (
          <p className="mt-4 rounded-lg border border-rose-500/40 bg-rose-500/10 px-4 py-2 text-sm text-rose-300">
            {error}
          </p>
        ) : null}

        {/* Formulaire d'ajout */}
        <form
          onSubmit={addEntry}
          className="mt-6 grid gap-4 rounded-xl border border-brand-800 bg-brand-900/60 p-4 sm:grid-cols-2 lg:grid-cols-3"
        >
          <div>
            <label htmlFor="st" className="label">
              Sous-traitant
            </label>
            <select
              id="st"
              value={stId}
              onChange={(e) => setStId(e.target.value)}
              className="input"
            >
              <option value="">— Choisir —</option>
              {sts.map((s) => (
                <option key={s.id} value={String(s.id)}>
                  {s.full_name}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label htmlFor="pr" className="label">
              Projet
            </label>
            <select
              id="pr"
              value={projectId}
              onChange={(e) => setProjectId(e.target.value)}
              className="input"
            >
              <option value="">— Aucun —</option>
              {projects.map((p) => (
                <option key={p.id} value={String(p.id)}>
                  {p.address || p.name}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label htmlFor="dt" className="label">
              Date
            </label>
            <input
              id="dt"
              type="date"
              value={workDate}
              onChange={(e) => setWorkDate(e.target.value)}
              className="input"
            />
          </div>

          <div>
            <label htmlFor="gars" className="label">
              Nombre de gars
            </label>
            <input
              id="gars"
              type="number"
              min={1}
              step={1}
              value={workerCount}
              onChange={(e) => setWorkerCount(e.target.value)}
              className="input"
            />
          </div>

          <div>
            <label htmlFor="hrs" className="label">
              Heures totales (tous les gars)
            </label>
            <input
              id="hrs"
              type="number"
              min={0}
              step={0.25}
              value={totalHours}
              onChange={(e) => setTotalHours(e.target.value)}
              placeholder="Ex. 24"
              className="input"
            />
          </div>

          <div>
            <label htmlFor="nt" className="label">
              Note (optionnel)
            </label>
            <input
              id="nt"
              type="text"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="Ex. coffrage sous-sol"
              className="input"
            />
          </div>

          <div className="sm:col-span-2 lg:col-span-3">
            <button
              type="submit"
              disabled={submitting}
              className="btn-accent text-sm"
            >
              {submitting ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" /> Ajout…
                </>
              ) : (
                <>
                  <Plus className="mr-1.5 h-4 w-4" /> Ajouter à la feuille
                </>
              )}
            </button>
          </div>
        </form>

        {/* Récap */}
        <div className="mt-6 flex flex-wrap items-center gap-3">
          <h2 className="text-sm font-semibold text-white">Récap des heures</h2>
          <select
            value={filterSt}
            onChange={(e) => setFilterSt(e.target.value)}
            className="input sm:w-64"
          >
            <option value="">Tous les sous-traitants</option>
            {sts.map((s) => (
              <option key={s.id} value={String(s.id)}>
                {s.full_name}
              </option>
            ))}
          </select>
        </div>

        <div className="mt-3 grid gap-3 sm:grid-cols-3">
          <div className="rounded-xl border border-brand-800 bg-brand-900/60 p-4">
            <p className="text-xs text-white/60">Total des heures</p>
            <p className="mt-1 text-2xl font-bold text-accent-500">
              {fmtHm(recap.totalHrs)}
            </p>
          </div>
          <div className="rounded-xl border border-brand-800 bg-brand-900/60 p-4">
            <p className="text-xs text-white/60">Saisies</p>
            <p className="mt-1 text-2xl font-bold text-white">{recap.entries}</p>
          </div>
          <div className="rounded-xl border border-brand-800 bg-brand-900/60 p-4">
            <p className="text-xs text-white/60">Sous-traitants actifs</p>
            <p className="mt-1 text-2xl font-bold text-white">
              {recap.perSt.length}
            </p>
          </div>
        </div>

        {recap.perSt.length > 0 ? (
          <div className="mt-3 overflow-hidden rounded-xl border border-brand-800">
            <table className="w-full text-sm">
              <thead className="bg-brand-900 text-left text-xs text-white/60">
                <tr>
                  <th className="px-4 py-2 font-medium">Sous-traitant</th>
                  <th className="px-4 py-2 font-medium">Saisies</th>
                  <th className="px-4 py-2 text-right font-medium">
                    Heures cumulées
                  </th>
                </tr>
              </thead>
              <tbody>
                {recap.perSt.map((r) => (
                  <tr key={r.id} className="border-t border-brand-800">
                    <td className="px-4 py-2 text-white">
                      {stName.get(r.id) || `#${r.id}`}
                    </td>
                    <td className="px-4 py-2 text-white/70">{r.entries}</td>
                    <td className="px-4 py-2 text-right font-semibold text-white">
                      {fmtHm(r.hours)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}

        {/* Détail des saisies */}
        <h2 className="mt-8 text-sm font-semibold text-white">
          Détail des saisies
        </h2>
        {loading ? (
          <div className="flex min-h-[20vh] items-center justify-center">
            <Loader2 className="h-6 w-6 animate-spin text-accent-500" />
          </div>
        ) : filteredRows.length === 0 ? (
          <p className="mt-3 rounded-xl border border-dashed border-brand-800 bg-brand-900/40 p-6 text-center text-sm text-white/60">
            Aucune saisie pour l&apos;instant.
          </p>
        ) : (
          <div className="mt-3 overflow-x-auto rounded-xl border border-brand-800">
            <table className="w-full text-sm">
              <thead className="bg-brand-900 text-left text-xs text-white/60">
                <tr>
                  <th className="px-4 py-2 font-medium">Date</th>
                  <th className="px-4 py-2 font-medium">Sous-traitant</th>
                  <th className="px-4 py-2 font-medium">Projet</th>
                  <th className="px-4 py-2 text-right font-medium">Gars</th>
                  <th className="px-4 py-2 text-right font-medium">Heures</th>
                  <th className="px-4 py-2 font-medium">Note</th>
                  <th className="px-4 py-2" />
                </tr>
              </thead>
              <tbody>
                {filteredRows.map((r) => (
                  <tr key={r.id} className="border-t border-brand-800">
                    <td className="whitespace-nowrap px-4 py-2 text-white/80">
                      {fmtDate(r.work_date)}
                    </td>
                    <td className="px-4 py-2 text-white">
                      {stName.get(r.sous_traitant_id) ||
                        `#${r.sous_traitant_id}`}
                    </td>
                    <td className="px-4 py-2 text-white/70">
                      {r.project_id
                        ? projName.get(r.project_id) || `#${r.project_id}`
                        : "—"}
                    </td>
                    <td className="px-4 py-2 text-right text-white/80">
                      {r.worker_count}
                    </td>
                    <td className="px-4 py-2 text-right font-semibold text-white">
                      {fmtHm(num(r.total_hours))}
                    </td>
                    <td className="px-4 py-2 text-white/60">{r.notes || "—"}</td>
                    <td className="px-4 py-2 text-right">
                      <button
                        type="button"
                        onClick={() => removeEntry(r.id)}
                        className="btn-outline-rose btn-xs"
                        aria-label="Supprimer"
                      >
                        <Trash2 className="h-4 w-4" />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </>
  );
}
