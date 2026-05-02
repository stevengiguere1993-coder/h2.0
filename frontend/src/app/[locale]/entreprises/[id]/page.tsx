"use client";

import { useEffect, useMemo, useState } from "react";
import { useParams } from "next/navigation";
import {
  ArrowLeft,
  Briefcase,
  ExternalLink,
  Loader2,
  Plus,
  Trash2
} from "lucide-react";

import { Link } from "@/i18n/navigation";
import { authedFetch } from "@/lib/auth";
import { EntreprisesTopbar } from "../layout";
import { useConfirm } from "@/components/confirm-dialog";

type Entreprise = {
  id: number;
  name: string;
  type: string;
  color_accent: string;
  description: string | null;
  monday_board_id: string | null;
  monday_board_name: string | null;
};

type Tache = {
  id: number;
  entreprise_id: number;
  title: string;
  description: string | null;
  departement: string | null;
  status: string;
  impact: number | null;
  confidence: number | null;
  effort: number | null;
  assignee_user_id: number | null;
  due_date: string | null;
  completed_at: string | null;
  recurrence: string | null;
  tags_json: string | null;
  monday_item_id: string | null;
  monday_group_title: string | null;
  score: number | null;
};

type Employe = { id: number; full_name: string; email: string | null };

type Column = { id: string; label: string; dot: string };

const COLUMNS: Column[] = [
  { id: "backlog", label: "Backlog", dot: "bg-white/30" },
  { id: "todo", label: "À faire", dot: "bg-violet-400" },
  { id: "in_progress", label: "En cours", dot: "bg-blue-400" },
  { id: "waiting", label: "En attente", dot: "bg-amber-400" },
  { id: "done", label: "Terminé", dot: "bg-emerald-400" }
];

const RECURRENCE_LABELS: Record<string, string> = {
  daily: "Quotidienne",
  weekly: "Hebdomadaire",
  biweekly: "Aux 2 semaines",
  monthly: "Mensuelle",
  quarterly: "Trimestrielle",
  yearly: "Annuelle"
};

function fmtDate(s: string | null): string {
  if (!s) return "—";
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(s);
  if (!m) return s;
  const d = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
  return d.toLocaleDateString("fr-CA", { day: "2-digit", month: "short" });
}

function dueDateClass(s: string | null): string {
  if (!s) return "text-white/40";
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(s);
  if (!m) return "text-white/60";
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const due = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
  const days = Math.round(
    (due.getTime() - today.getTime()) / (24 * 60 * 60 * 1000)
  );
  if (days < 0) return "text-rose-300 font-semibold";
  if (days <= 7) return "text-amber-300 font-semibold";
  return "text-white/60";
}

export default function EntrepriseDetailPage() {
  const params = useParams();
  const idStr = String(params?.id ?? "");
  const id = Number(idStr);
  const confirm = useConfirm();

  const [ent, setEnt] = useState<Entreprise | null>(null);
  const [taches, setTaches] = useState<Tache[]>([]);
  const [employes, setEmployes] = useState<Employe[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [modal, setModal] = useState<Tache | { fresh: true } | null>(null);
  const [dragging, setDragging] = useState<number | null>(null);
  const [hoverCol, setHoverCol] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const [entRes, tachesRes, empRes] = await Promise.all([
        authedFetch(`/api/v1/entreprises`),
        authedFetch(`/api/v1/entreprises/taches?entreprise_id=${id}`),
        authedFetch("/api/v1/employes?limit=500")
      ]);
      if (!entRes.ok) throw new Error(`HTTP ${entRes.status}`);
      const ents = (await entRes.json()) as Entreprise[];
      const found = ents.find((e) => e.id === id);
      if (!found) throw new Error("Entreprise introuvable");
      setEnt(found);
      if (tachesRes.ok) setTaches((await tachesRes.json()) as Tache[]);
      if (empRes.ok) setEmployes((await empRes.json()) as Employe[]);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (id) void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  const empById = useMemo(() => {
    const m = new Map<number, Employe>();
    employes.forEach((e) => m.set(e.id, e));
    return m;
  }, [employes]);

  const byColumn = useMemo(() => {
    const out: Record<string, Tache[]> = Object.fromEntries(
      COLUMNS.map((c) => [c.id, [] as Tache[]])
    );
    for (const t of taches) {
      const target = COLUMNS.find((c) => c.id === t.status) ? t.status : "backlog";
      out[target].push(t);
    }
    // Tri par score décroissant à l'intérieur de chaque colonne
    for (const k of Object.keys(out)) {
      out[k].sort((a, b) => (b.score ?? -1) - (a.score ?? -1));
    }
    return out;
  }, [taches]);

  async function moveTache(tacheId: number, newStatus: string) {
    const prev = taches;
    setTaches((xs) =>
      xs.map((x) => (x.id === tacheId ? { ...x, status: newStatus } : x))
    );
    try {
      const res = await authedFetch(
        `/api/v1/entreprises/taches/${tacheId}`,
        {
          method: "PATCH",
          body: JSON.stringify({ status: newStatus })
        }
      );
      if (!res.ok) throw new Error();
      const updated = (await res.json()) as Tache;
      setTaches((xs) => xs.map((x) => (x.id === tacheId ? updated : x)));
    } catch {
      setTaches(prev);
      setError("Mise à jour échouée.");
    }
  }

  async function removeTache(t: Tache) {
    if (!(await confirm(`Supprimer la tâche « ${t.title} » ?`))) return;
    const prev = taches;
    setTaches((xs) => xs.filter((x) => x.id !== t.id));
    try {
      const res = await authedFetch(
        `/api/v1/entreprises/taches/${t.id}`,
        { method: "DELETE" }
      );
      if (!res.ok && res.status !== 204) throw new Error();
    } catch {
      setTaches(prev);
      setError("Suppression échouée.");
    }
  }

  function upsertTache(t: Tache) {
    setTaches((xs) => {
      const i = xs.findIndex((x) => x.id === t.id);
      if (i === -1) return [...xs, t];
      const n = xs.slice();
      n[i] = t;
      return n;
    });
  }

  if (loading || !ent) {
    return (
      <>
        <EntreprisesTopbar
          breadcrumbs={[
            { label: "Gestion d'entreprises", href: "/entreprises" },
            { label: idStr }
          ]}
        />
        <div className="flex min-h-[60vh] items-center justify-center">
          {error ? (
            <p className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-4 py-2 text-sm text-rose-300">
              {error}
            </p>
          ) : (
            <Loader2 className="h-6 w-6 animate-spin text-violet-300" />
          )}
        </div>
      </>
    );
  }

  return (
    <>
      <EntreprisesTopbar
        breadcrumbs={[
          { label: "Gestion d'entreprises", href: "/entreprises" },
          { label: ent.name }
        ]}
        rightSlot={
          <button
            type="button"
            onClick={() => setModal({ fresh: true })}
            className="btn-accent text-sm"
          >
            <Plus className="mr-1.5 h-4 w-4" />
            Nouvelle tâche
          </button>
        }
      />

      <div className="p-4 lg:p-6">
        <Link
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          href={"/entreprises" as any}
          className="inline-flex items-center text-xs text-white/60 hover:text-violet-300"
        >
          <ArrowLeft className="mr-1 h-3.5 w-3.5" />
          Retour aux entreprises
        </Link>

        <header className="mt-4 flex items-start gap-3">
          <span
            className="mt-0.5 flex h-10 w-10 items-center justify-center rounded-xl"
            style={{
              backgroundColor: `${ent.color_accent}26`,
              color: ent.color_accent
            }}
          >
            <Briefcase className="h-5 w-5" />
          </span>
          <div className="flex-1">
            <h1 className="text-2xl font-bold text-white">{ent.name}</h1>
            {ent.description ? (
              <p className="mt-1 text-sm text-white/60">{ent.description}</p>
            ) : null}
            {ent.monday_board_id ? (
              <p className="mt-2 inline-flex items-center gap-1.5 rounded-full border border-violet-500/40 bg-violet-500/10 px-2.5 py-0.5 text-[10px] font-semibold text-violet-200">
                <ExternalLink className="h-3 w-3" />
                Synchronisée depuis Monday : {ent.monday_board_name}
              </p>
            ) : null}
          </div>
          <div className="rounded-md bg-brand-900 px-3 py-2 text-sm">
            <span className="text-white/50">Tâches </span>
            <span className="font-bold text-white">{taches.length}</span>
          </div>
        </header>

        {error ? (
          <p className="mt-4 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-300">
            {error}
          </p>
        ) : null}

        <div className="mt-6 flex gap-3 overflow-x-auto pb-3">
          {COLUMNS.map((col) => {
            const cards = byColumn[col.id] || [];
            const isHover = hoverCol === col.id;
            return (
              <div
                key={col.id}
                onDragOver={(e) => {
                  e.preventDefault();
                  setHoverCol(col.id);
                }}
                onDragLeave={() => setHoverCol(null)}
                onDrop={() => {
                  setHoverCol(null);
                  if (dragging !== null) {
                    const t = taches.find((x) => x.id === dragging);
                    if (t && t.status !== col.id) moveTache(dragging, col.id);
                  }
                }}
                className={`flex w-72 min-w-[280px] flex-shrink-0 flex-col rounded-xl border bg-brand-900/60 ${
                  isHover
                    ? "border-violet-500 bg-brand-900"
                    : "border-brand-800"
                }`}
              >
                <div className="flex items-center justify-between border-b border-brand-800 px-4 py-3">
                  <div className="flex items-center gap-2">
                    <span className={`h-2 w-2 rounded-full ${col.dot}`} />
                    <h2 className="text-sm font-semibold text-white">
                      {col.label}
                    </h2>
                    <span className="rounded-md bg-brand-950 px-2 py-0.5 text-xs font-semibold text-white/70">
                      {cards.length}
                    </span>
                  </div>
                </div>

                <div className="flex-1 space-y-2 p-3">
                  {cards.length === 0 ? (
                    <p className="py-8 text-center text-xs text-white/40">
                      Aucune tâche
                    </p>
                  ) : (
                    cards.map((t) => (
                      <TacheCard
                        key={t.id}
                        t={t}
                        empById={empById}
                        onClick={() => setModal(t)}
                        onDragStart={() => setDragging(t.id)}
                        onDragEnd={() => {
                          setDragging(null);
                          setHoverCol(null);
                        }}
                        onDelete={(ev) => {
                          ev.stopPropagation();
                          ev.preventDefault();
                          void removeTache(t);
                        }}
                        accent={ent.color_accent}
                      />
                    ))
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {modal ? (
        <TacheModal
          seed={modal}
          entrepriseId={ent.id}
          employes={employes}
          onClose={() => setModal(null)}
          onSaved={(t) => {
            upsertTache(t);
            setModal(null);
          }}
        />
      ) : null}
    </>
  );
}

function TacheCard({
  t,
  empById,
  onClick,
  onDragStart,
  onDragEnd,
  onDelete,
  accent
}: {
  t: Tache;
  empById: Map<number, Employe>;
  onClick: () => void;
  onDragStart: () => void;
  onDragEnd: () => void;
  onDelete: (e: React.MouseEvent) => void;
  accent: string;
}) {
  const assignee = t.assignee_user_id
    ? empById.get(t.assignee_user_id)
    : null;
  return (
    <button
      type="button"
      draggable
      onDragStart={onDragStart}
      onDragEnd={onDragEnd}
      onClick={onClick}
      className="group relative block w-full rounded-lg border border-brand-800 bg-brand-950 p-3 text-left transition hover:border-violet-500/50"
    >
      <button
        type="button"
        onClick={onDelete}
        aria-label="Supprimer"
        className="absolute right-2 top-2 rounded-md p-1 text-white/30 opacity-0 transition hover:bg-rose-500/15 hover:text-rose-400 group-hover:opacity-100"
      >
        <Trash2 className="h-3.5 w-3.5" />
      </button>
      <h3 className="pr-6 text-sm font-semibold text-white">{t.title}</h3>
      <div className="mt-2 flex flex-wrap items-center gap-2 text-[10px]">
        {t.score != null ? (
          <span
            className="rounded-full px-1.5 py-0.5 font-bold"
            style={{
              backgroundColor: `${accent}33`,
              color: accent
            }}
            title="Score = (impact × confiance / effort) × urgence"
          >
            ★ {t.score.toFixed(1)}
          </span>
        ) : null}
        {t.recurrence ? (
          <span className="rounded-full border border-amber-500/40 bg-amber-500/10 px-1.5 py-0.5 text-amber-200">
            ⟲ {RECURRENCE_LABELS[t.recurrence] || t.recurrence}
          </span>
        ) : null}
        {t.departement ? (
          <span className="rounded-full border border-brand-700 px-1.5 py-0.5 text-white/60">
            {t.departement}
          </span>
        ) : null}
      </div>
      <div className="mt-2 flex items-center justify-between text-[11px]">
        <span className={dueDateClass(t.due_date)}>
          {fmtDate(t.due_date)}
        </span>
        <span className="truncate text-white/50">
          {assignee ? assignee.full_name.split(" ")[0] : "—"}
        </span>
      </div>
    </button>
  );
}

function TacheModal({
  seed,
  entrepriseId,
  employes,
  onClose,
  onSaved
}: {
  seed: Tache | { fresh: true };
  entrepriseId: number;
  employes: Employe[];
  onClose: () => void;
  onSaved: (t: Tache) => void;
}) {
  const existing = "id" in seed ? seed : null;
  const [title, setTitle] = useState(existing?.title || "");
  const [description, setDescription] = useState(
    existing?.description || ""
  );
  const [departement, setDepartement] = useState(
    existing?.departement || ""
  );
  const [status, setStatus] = useState(existing?.status || "backlog");
  const [impact, setImpact] = useState(
    existing?.impact != null ? String(existing.impact) : ""
  );
  const [confidence, setConfidence] = useState(
    existing?.confidence != null ? String(existing.confidence) : ""
  );
  const [effort, setEffort] = useState(
    existing?.effort != null ? String(existing.effort) : ""
  );
  const [assignee, setAssignee] = useState(
    existing?.assignee_user_id != null
      ? String(existing.assignee_user_id)
      : ""
  );
  const [dueDate, setDueDate] = useState(existing?.due_date || "");
  const [recurrence, setRecurrence] = useState(existing?.recurrence || "");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function save(e: React.FormEvent) {
    e.preventDefault();
    if (!title.trim()) {
      setErr("Le titre est requis.");
      return;
    }
    setBusy(true);
    setErr(null);
    try {
      const payload = {
        entreprise_id: entrepriseId,
        title: title.trim(),
        description: description.trim() || null,
        departement: departement.trim() || null,
        status,
        impact: impact ? Number(impact) : null,
        confidence: confidence ? Number(confidence) : null,
        effort: effort ? Number(effort) : null,
        assignee_user_id: assignee ? Number(assignee) : null,
        due_date: dueDate || null,
        recurrence: recurrence || null
      };
      const res = await authedFetch(
        existing
          ? `/api/v1/entreprises/taches/${existing.id}`
          : "/api/v1/entreprises/taches",
        {
          method: existing ? "PATCH" : "POST",
          body: JSON.stringify(payload)
        }
      );
      if (!res.ok) {
        const t = await res.text();
        throw new Error(t.slice(0, 200) || `HTTP ${res.status}`);
      }
      onSaved((await res.json()) as Tache);
    } catch (e) {
      setErr((e as Error).message);
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
        className="mt-8 w-full max-w-2xl rounded-2xl border border-brand-800 bg-brand-950 p-6 shadow-2xl"
      >
        <h3 className="text-lg font-bold text-white">
          {existing ? "Modifier la tâche" : "Nouvelle tâche"}
        </h3>

        <div className="mt-5 space-y-4">
          <div>
            <label htmlFor="t_title" className="label">
              Titre <span className="text-rose-400">*</span>
            </label>
            <input
              id="t_title"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              className="input"
              required
              maxLength={255}
            />
          </div>

          <div>
            <label htmlFor="t_desc" className="label">Description</label>
            <textarea
              id="t_desc"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={3}
              className="input"
            />
          </div>

          <div className="grid gap-4 sm:grid-cols-3">
            <div>
              <label htmlFor="t_status" className="label">Statut</label>
              <select
                id="t_status"
                value={status}
                onChange={(e) => setStatus(e.target.value)}
                className="input"
              >
                {COLUMNS.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.label}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label htmlFor="t_dept" className="label">Département</label>
              <input
                id="t_dept"
                value={departement}
                onChange={(e) => setDepartement(e.target.value)}
                className="input"
                placeholder="finance, ops, rh, juridique…"
                list="depts"
                maxLength={32}
              />
              <datalist id="depts">
                <option value="finance" />
                <option value="operations" />
                <option value="rh" />
                <option value="juridique" />
                <option value="marketing" />
                <option value="fiscalite" />
              </datalist>
            </div>
            <div>
              <label htmlFor="t_due" className="label">Échéance</label>
              <input
                id="t_due"
                type="date"
                value={dueDate}
                onChange={(e) => setDueDate(e.target.value)}
                className="input"
              />
            </div>
          </div>

          <div>
            <label className="label">
              Scoring ICE — score automatique
            </label>
            <div className="grid gap-3 sm:grid-cols-3">
              <NumberPicker
                label="Impact (1-10)"
                value={impact}
                onChange={setImpact}
                hint="Effet sur revenu / risque / conformité"
              />
              <NumberPicker
                label="Confiance (1-10)"
                value={confidence}
                onChange={setConfidence}
                hint="À quel point on est sûr du résultat"
              />
              <NumberPicker
                label="Effort (1-10)"
                value={effort}
                onChange={setEffort}
                hint="Temps estimé (plus haut = score plus bas)"
              />
            </div>
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <label htmlFor="t_assignee" className="label">Assigné à</label>
              <select
                id="t_assignee"
                value={assignee}
                onChange={(e) => setAssignee(e.target.value)}
                className="input"
              >
                <option value="">— Personne —</option>
                {employes.map((e) => (
                  <option key={e.id} value={String(e.id)}>
                    {e.full_name}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label htmlFor="t_rec" className="label">Récurrence</label>
              <select
                id="t_rec"
                value={recurrence}
                onChange={(e) => setRecurrence(e.target.value)}
                className="input"
              >
                <option value="">— Tâche unique —</option>
                <option value="daily">Quotidienne</option>
                <option value="weekly">Hebdomadaire</option>
                <option value="biweekly">Aux 2 semaines</option>
                <option value="monthly">Mensuelle</option>
                <option value="quarterly">Trimestrielle</option>
                <option value="yearly">Annuelle</option>
              </select>
            </div>
          </div>
        </div>

        {err ? (
          <p className="mt-3 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
            {err}
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
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                Sauvegarde…
              </>
            ) : existing ? (
              "Enregistrer"
            ) : (
              "Créer la tâche"
            )}
          </button>
        </div>
      </form>
    </div>
  );
}

function NumberPicker({
  label,
  value,
  onChange,
  hint
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  hint: string;
}) {
  return (
    <div>
      <label className="block text-xs font-medium text-white/80">
        {label}
      </label>
      <input
        type="number"
        min={1}
        max={10}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="input mt-1"
        placeholder="—"
      />
      <p className="mt-1 text-[10px] text-white/40">{hint}</p>
    </div>
  );
}
