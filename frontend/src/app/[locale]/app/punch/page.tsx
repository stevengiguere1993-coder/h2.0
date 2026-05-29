"use client";

import { useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  Clock,
  Loader2,
  MapPin,
  Play,
  Square
} from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { Link } from "@/i18n/navigation";
import { useAppLayout } from "../layout";
import { useCurrentUser } from "@/hooks/use-current-user";
import { authedFetch } from "@/lib/auth";
import { useConfirm } from "@/components/confirm-dialog";

type Employe = { id: number; full_name: string; email: string | null };
type Project = {
  id: number;
  name: string;
  status: string;
  address: string | null;
};
type Prospect = {
  id: number;
  name: string;
  email: string;
  status: string;
  project_type: string;
};

type PunchRead = {
  id: number;
  employe_id: number;
  project_id: number | null;
  contact_request_id: number | null;
  started_at: string;
  ended_at: string | null;
  hours: number | null;
  task: string | null;
  geolocation: string | null;
  approved: boolean;
  notes: string | null;
};

type Me = { employe: Employe | null; active: PunchRead | null };

type WeeklyDay = { day: string; hours: number };
type Weekly = {
  employe_id: number;
  week_start: string;
  week_end: string;
  total_hours: number;
  days: WeeklyDay[];
};

function fmtElapsed(ms: number): string {
  const totalSec = Math.max(0, Math.floor(ms / 1000));
  const h = Math.floor(totalSec / 3600);
  const m = Math.floor((totalSec % 3600) / 60);
  const s = totalSec % 60;
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(
    s
  ).padStart(2, "0")}`;
}

// Heures en h/min (ex. 7.89 h → « 7 h 53 ») au lieu du décimal.
function fmtHm(h: number): string {
  const totalMin = Math.round((h || 0) * 60);
  const hh = Math.floor(totalMin / 60);
  const mm = totalMin % 60;
  return `${hh} h ${String(mm).padStart(2, "0")}`;
}

function dayLabel(iso: string): string {
  return new Date(iso + "T00:00:00").toLocaleDateString("fr-CA", {
    weekday: "short",
    day: "2-digit"
  });
}

async function explainError(res: Response): Promise<string> {
  try {
    const data = await res.json();
    if (Array.isArray(data?.detail)) {
      return data.detail
        .map(
          (d: { loc?: (string | number)[]; msg?: string }) =>
            `${(d.loc || []).slice(1).join(".")} — ${d.msg}`
        )
        .join(" · ")
        .slice(0, 400);
    }
    if (typeof data?.detail === "string") return data.detail.slice(0, 400);
    return `http_${res.status}`;
  } catch {
    return `http_${res.status}`;
  }
}

async function getPosition(): Promise<GeolocationPosition | null> {
  if (!("geolocation" in navigator)) return null;
  return new Promise((resolve) => {
    navigator.geolocation.getCurrentPosition(
      (pos) => resolve(pos),
      () => resolve(null),
      { enableHighAccuracy: true, timeout: 8000, maximumAge: 30_000 }
    );
  });
}

export default function PunchPage() {
  const confirm = useConfirm();
  const { onOpenSidebar } = useAppLayout();
  const { user } = useCurrentUser();
  const [me, setMe] = useState<Me | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  const [prospects, setProspects] = useState<Prospect[]>([]);
  const [weekly, setWeekly] = useState<Weekly | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);

  // Target value format: "p-123" for project, "c-45" for contact
  // request, or "" for none.
  const [target, setTarget] = useState("");
  const [task, setTask] = useState("");
  const [notes, setNotes] = useState("");

  async function refreshWeekly(): Promise<void> {
    const r = await authedFetch("/api/v1/punch/weekly");
    if (r.ok) {
      setWeekly((await r.json()) as Weekly);
    }
  }

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const [meRes, prRes, csRes] = await Promise.all([
          authedFetch("/api/v1/punch/me"),
          authedFetch("/api/v1/projects?limit=200"),
          // Open prospects — anything not yet won/lost/spam, sorted
          // newest-first by the contact endpoint default.
          authedFetch("/api/v1/contact?limit=200")
        ]);
        if (!meRes.ok) throw new Error(`http_${meRes.status}`);
        const meData = (await meRes.json()) as Me;
        const prData = prRes.ok ? ((await prRes.json()) as Project[]) : [];
        const csData = csRes.ok ? ((await csRes.json()) as Prospect[]) : [];
        const openProspects = csData.filter(
          (c) => !["won", "lost", "spam"].includes(c.status)
        );
        if (cancelled) return;
        setMe(meData);
        setProjects(prData);
        setProspects(openProspects);
        if (meData.active?.project_id) {
          setTarget(`p-${meData.active.project_id}`);
        } else if (meData.active?.contact_request_id) {
          setTarget(`c-${meData.active.contact_request_id}`);
        }
        if (meData.active?.task) setTask(meData.active.task);
        if (meData.employe) await refreshWeekly();
      } catch {
        if (!cancelled) setError("Impossible de charger le punch.");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, []);

  // Tick the in-memory timer when a punch is active.
  useEffect(() => {
    if (!me?.active) return;
    const id = setInterval(() => setTick((t) => t + 1), 1000);
    return () => clearInterval(id);
  }, [me?.active]);

  const activeElapsed = useMemo(() => {
    if (!me?.active) return 0;
    return Date.now() - new Date(me.active.started_at).getTime();
    // tick keeps this fresh
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [me?.active, tick]);

  async function startPunch() {
    if (!me?.employe) return;
    setBusy(true);
    setError(null);
    try {
      const pos = await getPosition();
      const payload: Record<string, unknown> = {};
      if (target.startsWith("p-")) {
        payload.project_id = Number(target.slice(2));
      } else if (target.startsWith("c-")) {
        payload.contact_request_id = Number(target.slice(2));
      }
      if (task.trim()) payload.task = task.trim();
      if (pos) {
        payload.latitude = pos.coords.latitude;
        payload.longitude = pos.coords.longitude;
      }
      const res = await authedFetch("/api/v1/punch/clock-in", {
        method: "POST",
        body: JSON.stringify(payload)
      });
      if (!res.ok) {
        throw new Error(await explainError(res));
      }
      const created = (await res.json()) as PunchRead;
      setMe({ ...(me as Me), active: created });
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function stopPunch() {
    if (!me?.active) return;
    if (
      !(await confirm({
        title: "Terminer le punch maintenant ?",
        confirmLabel: "Terminer",
        destructive: false
      }))
    )
      return;
    setBusy(true);
    setError(null);
    try {
      const pos = await getPosition();
      const payload: Record<string, unknown> = {};
      if (pos) {
        payload.latitude = pos.coords.latitude;
        payload.longitude = pos.coords.longitude;
      }
      if (notes.trim()) payload.notes = notes.trim();
      const res = await authedFetch("/api/v1/punch/clock-out", {
        method: "POST",
        body: JSON.stringify(payload)
      });
      if (!res.ok) {
        throw new Error(await explainError(res));
      }
      setMe({ ...(me as Me), active: null });
      setNotes("");
      await refreshWeekly();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const activeProject = projects.find(
    (p) => me?.active?.project_id && p.id === me.active.project_id
  );
  const activeProspect = prospects.find(
    (c) =>
      me?.active?.contact_request_id &&
      c.id === me.active.contact_request_id
  );
  const activeTargetLabel = activeProject
    ? `Projet — ${activeProject.name}`
    : activeProspect
    ? `Prospect — ${activeProspect.name}`
    : "Aucun";

  return (
    <>
      <AppTopbar
        breadcrumbs={[{ label: "Construction", href: "/app" }, { label: "Punch / Temps" }]}
        onOpenSidebar={onOpenSidebar}
        rightSlot={
          <Link
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            href={"/app/punch/gestion" as any}
            className="btn-secondary text-xs"
          >
            Gestion admin
          </Link>
        }
      />

      <div className="p-4 lg:p-6">
        {loading ? (
          <div className="flex min-h-[40vh] items-center justify-center">
            <Loader2 className="h-6 w-6 animate-spin text-accent-500" />
          </div>
        ) : !me?.employe ? (
          <NoEmployeCard userEmail={user?.email || null} />
        ) : (
          <div className="mx-auto max-w-xl space-y-6">
            <header>
              <p className="text-xs uppercase tracking-wider text-white/50">
                {me.employe.full_name}
              </p>
              <h1 className="mt-1 text-2xl font-bold text-white">
                {me.active ? "Punch en cours" : "Prêt à poinçonner"}
              </h1>
            </header>

            {error ? (
              <p className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-4 py-3 text-sm text-rose-300">
                {error}
              </p>
            ) : null}

            {me.active ? (
              <ActivePunchCard
                elapsed={activeElapsed}
                startedAt={me.active.started_at}
                task={me.active.task}
                geolocation={me.active.geolocation}
                targetLabel={activeTargetLabel}
                notes={notes}
                onNotes={setNotes}
                onStop={stopPunch}
                busy={busy}
              />
            ) : (
              <IdleCard
                projects={projects}
                prospects={prospects}
                target={target}
                onTarget={setTarget}
                task={task}
                onTask={setTask}
                onStart={startPunch}
                busy={busy}
              />
            )}

            {weekly ? <WeeklyCard weekly={weekly} /> : null}
          </div>
        )}
      </div>
    </>
  );
}

function NoEmployeCard({ userEmail }: { userEmail: string | null }) {
  const [diag, setDiag] = useState<null | {
    login_email_raw: string | null;
    login_email_repr: string;
    login_email_normalized: string;
    employes: Array<{
      id: number;
      full_name: string;
      email_raw: string | null;
      email_len: number;
      email_repr: string;
      active: boolean;
    }>;
  }>(null);
  const [diagBusy, setDiagBusy] = useState(false);
  const [diagErr, setDiagErr] = useState<string | null>(null);

  async function runDiagnostic() {
    setDiagBusy(true);
    setDiagErr(null);
    try {
      const res = await authedFetch("/api/v1/punch/debug");
      if (!res.ok) throw new Error(`http_${res.status}`);
      setDiag(await res.json());
    } catch (err) {
      setDiagErr((err as Error).message || "Erreur");
    } finally {
      setDiagBusy(false);
    }
  }

  return (
    <div className="mx-auto mt-10 max-w-xl rounded-2xl border border-amber-500/40 bg-amber-500/10 p-6 text-amber-100">
      <AlertTriangle className="h-6 w-6" />
      <h2 className="mt-3 text-base font-semibold text-white">
        Fiche employé introuvable
      </h2>
      <p className="mt-2 text-sm text-amber-100/80">
        Aucune fiche active ne correspond à ton courriel de connexion.
        Vérifie que la fiche existe, est <strong>active</strong> et que
        son courriel est <em>exactement</em> :
      </p>
      {userEmail ? (
        <p className="mt-2 rounded-md bg-black/30 px-3 py-2 font-mono text-xs text-white">
          {userEmail}
        </p>
      ) : null}

      <div className="mt-4 flex flex-wrap gap-2">
        <Link
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          href={"/app/employes" as any}
          className="btn-accent text-xs"
        >
          Ouvrir la liste des employés
        </Link>
        <button
          type="button"
          onClick={runDiagnostic}
          disabled={diagBusy}
          className="btn-secondary text-xs"
        >
          {diagBusy ? (
            <>
              <Loader2 className="mr-1.5 h-3 w-3 animate-spin" />
              Diagnostic…
            </>
          ) : (
            "Lancer le diagnostic"
          )}
        </button>
      </div>

      {diagErr ? (
        <p className="mt-3 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
          Diagnostic échoué : {diagErr}
        </p>
      ) : null}

      {diag ? (
        <div className="mt-4 space-y-3 text-xs">
          <div className="rounded-lg bg-black/30 p-3">
            <p className="text-white/50">Login</p>
            <p className="mt-1 font-mono text-white">
              {diag.login_email_repr}{" "}
              <span className="text-white/40">
                (len {(diag.login_email_raw || "").length})
              </span>
            </p>
          </div>
          <div className="rounded-lg bg-black/30 p-3">
            <p className="mb-2 text-white/50">
              Fiches ({diag.employes.length})
            </p>
            {diag.employes.length === 0 ? (
              <p className="text-white/60">
                Aucune fiche employé dans la base. Crée-en une d&apos;abord.
              </p>
            ) : (
              <ul className="space-y-2">
                {diag.employes.map((e) => {
                  const matches =
                    diag.login_email_normalized &&
                    (e.email_raw || "").trim().toLowerCase() ===
                      diag.login_email_normalized;
                  return (
                    <li
                      key={e.id}
                      className={`rounded border px-2 py-1.5 font-mono ${
                        matches && e.active
                          ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-200"
                          : "border-white/10 text-white/80"
                      }`}
                    >
                      <div>{e.full_name}</div>
                      <div>
                        {e.email_repr}{" "}
                        <span className="text-white/40">(len {e.email_len})</span>
                      </div>
                      <div className="text-white/50">
                        {e.active ? "actif" : "INACTIF"}
                        {matches ? " · ✓ correspond" : " · ≠"}
                      </div>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
          <p className="text-white/50">
            Le diagnostic attendu : un bloc vert « ✓ correspond · actif ».
            Sinon, regarde les différences dans les guillemets (espaces,
            caractères invisibles, `l` vs `i`).
          </p>
        </div>
      ) : null}
    </div>
  );
}

function ActivePunchCard({
  elapsed,
  startedAt,
  task,
  geolocation,
  targetLabel,
  notes,
  onNotes,
  onStop,
  busy
}: {
  elapsed: number;
  startedAt: string;
  task: string | null;
  geolocation: string | null;
  targetLabel: string;
  notes: string;
  onNotes: (v: string) => void;
  onStop: () => void;
  busy: boolean;
}) {
  const lat = geolocation?.split("|")[0]?.split(",")[0];
  const lng = geolocation?.split("|")[0]?.split(",")[1];
  return (
    <section className="rounded-2xl border border-accent-500/40 bg-accent-500/5 p-6">
      <div className="flex items-center gap-2 text-sm text-accent-300">
        <Clock className="h-4 w-4" /> En cours depuis{" "}
        {new Date(startedAt).toLocaleTimeString("fr-CA", {
          hour: "2-digit",
          minute: "2-digit"
        })}
      </div>
      <p className="mt-4 font-mono text-5xl font-bold tracking-tight text-white">
        {fmtElapsed(elapsed)}
      </p>

      <dl className="mt-5 space-y-2 text-sm text-white/80">
        <Row label="Affecté à" value={targetLabel} />
        {task ? <Row label="Tâche" value={task} /> : null}
        {lat && lng ? (
          <Row
            label="Position"
            value={
              <span className="inline-flex items-center gap-1 text-xs text-white/70">
                <MapPin className="h-3 w-3" /> {lat}, {lng}
              </span>
            }
          />
        ) : null}
      </dl>

      <div className="mt-5">
        <label htmlFor="punch_notes" className="label">
          Notes (optionnel)
        </label>
        <textarea
          id="punch_notes"
          rows={2}
          value={notes}
          onChange={(e) => onNotes(e.target.value)}
          placeholder="Anomalies, consignes, etc."
          className="input"
        />
      </div>

      <button
        type="button"
        onClick={onStop}
        disabled={busy}
        className="mt-6 flex w-full items-center justify-center gap-2 rounded-xl bg-rose-500 px-4 py-4 text-base font-bold text-white shadow-lg hover:bg-rose-600 disabled:opacity-60"
      >
        {busy ? (
          <Loader2 className="h-5 w-5 animate-spin" />
        ) : (
          <Square className="h-5 w-5" />
        )}
        Terminer le punch
      </button>
    </section>
  );
}

function IdleCard({
  projects,
  prospects,
  target,
  onTarget,
  task,
  onTask,
  onStart,
  busy
}: {
  projects: Project[];
  prospects: Prospect[];
  target: string;
  onTarget: (v: string) => void;
  task: string;
  onTask: (v: string) => void;
  onStart: () => void;
  busy: boolean;
}) {
  return (
    <section className="rounded-2xl border border-brand-800 bg-brand-900 p-6">
      <p className="text-sm text-white/60">
        Sélectionne un projet ou un prospect (visite, soumission),
        puis appuie sur Démarrer. On capture ta position GPS pour
        vérifier la présence sur le terrain.
      </p>
      <div className="mt-5 space-y-4">
        <div>
          <label htmlFor="punch_target" className="label">
            Projet ou prospect
          </label>
          <select
            id="punch_target"
            value={target}
            onChange={(e) => onTarget(e.target.value)}
            className="input"
          >
            <option value="">— Administration (aucun lien) —</option>
            {projects.length > 0 ? (
              <optgroup label="Projets">
                {[...projects]
                  .sort((a, b) =>
                    (a.address || "￿").localeCompare(
                      b.address || "￿",
                      "fr",
                      { sensitivity: "base" }
                    )
                  )
                  .map((p) => (
                    <option key={`p-${p.id}`} value={`p-${p.id}`}>
                      {p.address ? `${p.address} — ${p.name}` : p.name}
                    </option>
                  ))}
              </optgroup>
            ) : null}
            {prospects.length > 0 ? (
              <optgroup label="Prospects (visite / soumission)">
                {prospects.map((c) => (
                  <option key={`c-${c.id}`} value={`c-${c.id}`}>
                    {c.name} — {c.project_type}
                  </option>
                ))}
              </optgroup>
            ) : null}
          </select>
        </div>
        <div>
          <label htmlFor="punch_task" className="label">
            Tâche (optionnel)
          </label>
          <input
            id="punch_task"
            type="text"
            value={task}
            onChange={(e) => onTask(e.target.value)}
            className="input"
            placeholder="Ex. Plomberie salle de bain"
          />
        </div>
      </div>

      <button
        type="button"
        onClick={onStart}
        disabled={busy}
        className="mt-6 flex w-full items-center justify-center gap-2 rounded-xl bg-accent-500 px-4 py-4 text-base font-bold text-brand-950 shadow-lg hover:bg-accent-400 disabled:opacity-60"
      >
        {busy ? (
          <Loader2 className="h-5 w-5 animate-spin" />
        ) : (
          <Play className="h-5 w-5" />
        )}
        Démarrer le punch
      </button>
    </section>
  );
}

function WeeklyCard({ weekly }: { weekly: Weekly }) {
  return (
    <section className="rounded-2xl border border-brand-800 bg-brand-900 p-5">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-accent-500">
          Mes heures — semaine courante
        </h2>
        <span className="text-base font-bold text-white">
          {fmtHm(weekly.total_hours)}
        </span>
      </div>
      <p className="mt-1 text-xs text-white/50">
        Du {weekly.week_start} au {weekly.week_end}
      </p>
      <ul className="mt-4 divide-y divide-brand-800 text-sm">
        {weekly.days.map((d) => (
          <li
            key={d.day}
            className="flex items-center justify-between py-2 text-white/80"
          >
            <span>{dayLabel(d.day)}</span>
            <span className="font-semibold text-white">
              {d.hours > 0 ? fmtHm(d.hours) : "—"}
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}

function Row({
  label,
  value
}: {
  label: string;
  value: React.ReactNode;
}) {
  return (
    <div className="flex items-center justify-between gap-3">
      <dt className="text-white/50">{label}</dt>
      <dd className="max-w-[60%] truncate text-right">{value}</dd>
    </div>
  );
}
