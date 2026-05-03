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
          <>
            <Link
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
              href={`/entreprises/${ent.id}/pilotage` as any}
              className="inline-flex items-center gap-1.5 rounded-lg border border-violet-400/30 bg-violet-500/10 px-3 py-1.5 text-xs font-semibold text-violet-200 hover:bg-violet-500/20"
            >
              Pilotage
            </Link>
            <button
              type="button"
              onClick={() => setModal({ fresh: true })}
              className="btn-accent text-sm"
            >
              <Plus className="mr-1.5 h-4 w-4" />
              Nouvelle tâche
            </button>
          </>
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

        {/* Daily Pulse — briefing IA quotidien */}
        <DailyPulseCard entrepriseId={ent.id} accent={ent.color_accent} />

        {/* Immobilier — portefeuille détenu par cette entreprise */}
        <EntrepriseImmobilierSection entrepriseId={ent.id} />

        {/* Partenaires + parts de détention */}
        <PartnersSection entrepriseId={ent.id} />

        {/* Liens documentation (Drive, SharePoint…) */}
        <LinksSection entrepriseId={ent.id} />

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
  const [aiRationale, setAiRationale] = useState<string>("");
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
            <div className="mb-2 flex items-center justify-between">
              <label className="label mb-0">
                Scoring ICE — score automatique
              </label>
              <AISuggestButton
                disabled={!title.trim()}
                onSuggest={async () => {
                  return await suggestScore({
                    entreprise_id: entrepriseId,
                    title: title.trim(),
                    description: description.trim() || null,
                    departement: departement.trim() || null,
                    due_date: dueDate || null
                  });
                }}
                onApply={(s) => {
                  setImpact(String(s.impact));
                  setConfidence(String(s.confidence));
                  setEffort(String(s.effort));
                  setAiRationale(s.rationale);
                }}
              />
            </div>
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
            {aiRationale ? (
              <div
                className="mt-2 rounded-md p-3 text-[11px]"
                style={{
                  backgroundColor: "rgba(212,255,58,0.06)",
                  border: "1px solid rgba(212,255,58,0.25)",
                  color: "var(--qg-accent)"
                }}
              >
                <span className="font-bold">✦ Justification IA : </span>
                <span className="text-[var(--qg-text)]/85">{aiRationale}</span>
              </div>
            ) : null}
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <div className="flex items-center justify-between">
                <label htmlFor="t_assignee" className="label">Assigné à</label>
                {existing?.id ? (
                  <SuggestAssigneeButton
                    tacheId={existing.id}
                    onPick={(uid) => setAssignee(String(uid))}
                  />
                ) : null}
              </div>
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


// ─── Daily Pulse — card briefing IA ───────────────────────────────────

type DailyBriefing = {
  id: number;
  entreprise_id: number;
  period_start: string;
  period_end: string;
  headline: string;
  summary_text: string;
  highlights: string[];
  model_used: string | null;
  provider: string | null;
  created_at: string;
};

function isToday(iso: string): boolean {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
  if (!m) return false;
  const t = new Date();
  return (
    Number(m[1]) === t.getFullYear() &&
    Number(m[2]) === t.getMonth() + 1 &&
    Number(m[3]) === t.getDate()
  );
}

function DailyPulseCard({
  entrepriseId,
  accent
}: {
  entrepriseId: number;
  accent: string;
}) {
  const [briefing, setBriefing] = useState<DailyBriefing | null>(null);
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const res = await authedFetch(
        `/api/v1/entreprises/${entrepriseId}/daily-pulse`
      );
      if (res.ok) {
        const data = (await res.json()) as DailyBriefing | null;
        setBriefing(data);
      }
    } catch {
      /* silent */
    } finally {
      setLoading(false);
    }
  }

  async function generate(force: boolean) {
    setGenerating(true);
    setError(null);
    try {
      const res = await authedFetch(
        `/api/v1/entreprises/${entrepriseId}/daily-pulse${force ? "?force=true" : ""}`,
        { method: "POST" }
      );
      if (!res.ok) {
        const t = await res.text();
        throw new Error(t.slice(0, 200) || `HTTP ${res.status}`);
      }
      setBriefing((await res.json()) as DailyBriefing);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setGenerating(false);
    }
  }

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [entrepriseId]);

  const todayBriefing = briefing && isToday(briefing.period_start);
  // Accent lime pour le badge IA (cohérent avec spec QG)
  const lime = "var(--qg-accent)";

  return (
    <section
      className="mt-4 overflow-hidden rounded-2xl border bg-gradient-to-br from-brand-900 to-brand-950 p-5"
      style={{ borderColor: lime + "44" }}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-2">
          <span
            className="relative flex h-2.5 w-2.5"
            title="IA active"
          >
            <span
              className="absolute inline-flex h-full w-full animate-ping rounded-full opacity-60"
              style={{ backgroundColor: lime }}
            />
            <span
              className="relative inline-flex h-2.5 w-2.5 rounded-full"
              style={{ backgroundColor: lime }}
            />
          </span>
          <h2
            className="text-xs font-bold uppercase tracking-wider"
            style={{ color: lime }}
          >
            ✦ Briefing IA du jour
          </h2>
        </div>
        <div className="flex items-center gap-2">
          {todayBriefing ? (
            <button
              type="button"
              onClick={() => generate(true)}
              disabled={generating}
              className="rounded-md border border-brand-700 bg-brand-900 px-2.5 py-1 text-[10px] font-semibold text-white/60 hover:text-white"
              title="Regénérer le briefing du jour"
            >
              {generating ? "…" : "Regénérer"}
            </button>
          ) : (
            <button
              type="button"
              onClick={() => generate(false)}
              disabled={generating}
              className="rounded-md px-3 py-1 text-[11px] font-bold transition disabled:opacity-60"
              style={{
                backgroundColor: lime,
                color: "var(--qg-bg)"
              }}
            >
              {generating ? (
                <>
                  <Loader2 className="mr-1 inline h-3 w-3 animate-spin" />
                  Génération…
                </>
              ) : (
                "Générer maintenant"
              )}
            </button>
          )}
        </div>
      </div>

      {loading ? (
        <p className="mt-3 text-xs text-white/40">Chargement…</p>
      ) : briefing ? (
        <div className="mt-3">
          <h3 className="text-base font-bold text-white">
            {briefing.headline}
          </h3>
          <p className="mt-1 text-[10px] text-white/40">
            Généré le{" "}
            {new Date(briefing.created_at).toLocaleString("fr-CA", {
              dateStyle: "medium",
              timeStyle: "short"
            })}
            {briefing.provider ? ` · ${briefing.provider}` : ""}
            {briefing.model_used ? ` · ${briefing.model_used}` : ""}
          </p>
          <p className="mt-2 whitespace-pre-line text-sm leading-relaxed text-white/80">
            {briefing.summary_text}
          </p>
          {briefing.highlights && briefing.highlights.length > 0 ? (
            <ul className="mt-3 space-y-1">
              {briefing.highlights.map((h, i) => (
                <li
                  key={i}
                  className="flex items-start gap-2 text-xs text-white/70"
                >
                  <span style={{ color: lime }}>•</span>
                  <span>{h}</span>
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : (
        <p className="mt-3 text-xs text-white/60">
          Aucun briefing aujourd&apos;hui. Cliquez « Générer maintenant »
          pour produire un résumé matinal basé sur les tâches et activités
          en cours.
        </p>
      )}

      {error ? (
        <p className="mt-3 rounded-md border border-rose-500/40 bg-rose-500/10 px-2 py-1 text-[11px] text-rose-300">
          {error}
        </p>
      ) : null}
    </section>
  );
}


// ─── ✦ Scoring proactif IA ────────────────────────────────────────────

type ScoreSuggestion = {
  impact: number;
  confidence: number;
  effort: number;
  rationale: string;
  score: number;
  provider: string | null;
  model: string | null;
};

async function suggestScore(payload: {
  entreprise_id: number;
  title: string;
  description: string | null;
  departement: string | null;
  due_date: string | null;
}): Promise<ScoreSuggestion> {
  const res = await authedFetch(
    "/api/v1/entreprises/taches/suggest-score",
    {
      method: "POST",
      body: JSON.stringify(payload)
    }
  );
  if (!res.ok) {
    const t = await res.text();
    throw new Error(t.slice(0, 200) || `HTTP ${res.status}`);
  }
  return (await res.json()) as ScoreSuggestion;
}

function AISuggestButton({
  disabled,
  onSuggest,
  onApply
}: {
  disabled?: boolean;
  onSuggest: () => Promise<ScoreSuggestion>;
  onApply: (s: ScoreSuggestion) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function run() {
    setBusy(true);
    setErr(null);
    try {
      const s = await onSuggest();
      onApply(s);
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col items-end gap-1">
      <button
        type="button"
        onClick={run}
        disabled={busy || disabled}
        title={
          disabled
            ? "Saisis d'abord le titre de la tâche"
            : "L'IA analyse la tâche et propose impact/confiance/effort"
        }
        className="inline-flex items-center gap-1.5 rounded-md px-2.5 py-1 text-[11px] font-bold transition disabled:cursor-not-allowed disabled:opacity-40"
        style={{
          backgroundColor: "rgba(212,255,58,0.12)",
          border: "1px solid rgba(212,255,58,0.45)",
          color: "var(--qg-accent)"
        }}
      >
        {busy ? (
          <>
            <Loader2 className="h-3 w-3 animate-spin" />
            Analyse…
          </>
        ) : (
          <>✦ Suggérer avec l&apos;IA</>
        )}
      </button>
      {err ? (
        <span className="text-[10px] text-rose-300">{err}</span>
      ) : null}
    </div>
  );
}

// ─── Section Immobilier ────────────────────────────────────────────────

type ImmobilierImmeubleItem = {
  immeuble_id: number;
  name: string;
  address: string;
  city: string | null;
  cover_photo_url: string | null;
  ownership_pct: number;
  nb_logements_actifs: number;
  nb_logements_occupes: number;
  revenu_mensuel_part: number;
  valeur_part: number | null;
  balance_hyp_part: number | null;
};

type ImmobilierSummary = {
  entreprise_id: number;
  nb_immeubles: number;
  nb_logements_actifs: number;
  nb_logements_occupes: number;
  taux_occupation: number;
  revenu_mensuel_part: number;
  revenu_annuel_part: number;
  valeur_portefeuille_part: number;
  balance_hypothecaire_part: number;
  equity_part: number;
  immeubles: ImmobilierImmeubleItem[];
};

function fmtCurrencyImmo(n: number | null | undefined): string {
  if (n == null) return "—";
  return new Intl.NumberFormat("fr-CA", {
    style: "currency",
    currency: "CAD",
    maximumFractionDigits: 0
  }).format(n);
}

function EntrepriseImmobilierSection({ entrepriseId }: { entrepriseId: number }) {
  const [data, setData] = useState<ImmobilierSummary | null>(null);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    let cancelled = false;
    authedFetch(`/api/v1/immobilier/par-entreprise/${entrepriseId}`)
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => {
        if (cancelled) return;
        setLoaded(true);
        if (d) setData(d as ImmobilierSummary);
      })
      .catch(() => {
        if (!cancelled) setLoaded(true);
      });
    return () => {
      cancelled = true;
    };
  }, [entrepriseId]);

  // Si l'entreprise ne possède aucun immeuble, on cache la section pour
  // ne pas polluer la fiche.
  if (!loaded) return null;
  if (!data || data.nb_immeubles === 0) return null;

  return (
    <section className="mt-6 rounded-2xl border border-brand-800 bg-brand-900 p-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-sky-300">
          Immobilier détenu
        </h2>
        <Link
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          href={"/immobilier" as any}
          className="text-xs text-white/60 hover:text-sky-300"
        >
          Vue complète →
        </Link>
      </div>

      <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <ImmoKpi
          label="Immeubles"
          value={`${data.nb_immeubles}`}
          sub={`${data.nb_logements_occupes}/${data.nb_logements_actifs} logements occupés`}
        />
        <ImmoKpi
          label="Revenu mensuel (part)"
          value={fmtCurrencyImmo(data.revenu_mensuel_part)}
          sub={`${fmtCurrencyImmo(data.revenu_annuel_part)} / an`}
        />
        <ImmoKpi
          label="Valeur portefeuille (part)"
          value={fmtCurrencyImmo(data.valeur_portefeuille_part)}
          sub={`Hypothèque ${fmtCurrencyImmo(data.balance_hypothecaire_part)}`}
        />
        <ImmoKpi
          label="Équité nette (part)"
          value={fmtCurrencyImmo(data.equity_part)}
          sub={`Occupation ${(data.taux_occupation * 100).toFixed(0)}%`}
        />
      </div>

      <ul className="mt-4 grid gap-2 sm:grid-cols-2">
        {data.immeubles.map((imm) => (
          <li key={imm.immeuble_id}>
            <Link
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
              href={`/immobilier/immeubles/${imm.immeuble_id}` as any}
              className="flex items-center gap-3 rounded-xl border border-brand-800 bg-brand-950 p-3 transition hover:border-sky-400/40"
            >
              <div className="h-12 w-12 flex-shrink-0 overflow-hidden rounded-lg bg-brand-900">
                {imm.cover_photo_url ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img
                    src={imm.cover_photo_url}
                    alt=""
                    className="h-full w-full object-cover"
                  />
                ) : null}
              </div>
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-bold text-white">
                  {imm.name}
                </p>
                <p className="truncate text-[11px] text-white/50">
                  {imm.address}
                  {imm.city ? `, ${imm.city}` : ""}
                </p>
                <p className="mt-1 font-mono text-[10px] text-white/40">
                  {imm.ownership_pct.toFixed(1)}% détenu ·{" "}
                  {fmtCurrencyImmo(imm.revenu_mensuel_part)}/m
                </p>
              </div>
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}

function ImmoKpi({
  label,
  value,
  sub
}: {
  label: string;
  value: string;
  sub?: string;
}) {
  return (
    <div className="rounded-xl border border-brand-800 bg-brand-950 p-3">
      <p className="text-[10px] font-semibold uppercase tracking-wider text-white/50">
        {label}
      </p>
      <p className="mt-1.5 text-lg font-bold text-white">{value}</p>
      {sub ? <p className="mt-0.5 text-[10px] text-white/40">{sub}</p> : null}
    </div>
  );
}

// ─── Suggest assignee dropdown ─────────────────────────────────────────

type AssignSuggestion = {
  user_id: number;
  full_name: string;
  email: string;
  score: number;
  nb_taches_open: number;
  charge_effort: number;
  free_hours_next_7d: number;
  next_free_slot?: string | null;
  reasons: string[];
};

function SuggestAssigneeButton({
  tacheId,
  onPick
}: {
  tacheId: number;
  onPick: (userId: number) => void;
}) {
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [suggestions, setSuggestions] = useState<AssignSuggestion[]>([]);
  const [err, setErr] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    setErr(null);
    try {
      const res = await authedFetch(
        `/api/v1/entreprises/taches/${tacheId}/suggest-assignees?top_n=3`
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setSuggestions((await res.json()) as AssignSuggestion[]);
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setLoading(false);
    }
  }

  function toggle() {
    if (!open) void load();
    setOpen(!open);
  }

  return (
    <div className="relative inline-block">
      <button
        type="button"
        onClick={toggle}
        className="inline-flex items-center gap-1 text-[10px] font-semibold text-violet-300 hover:text-violet-200"
      >
        ✦ Suggérer
      </button>
      {open ? (
        <div className="absolute right-0 z-30 mt-1 w-72 rounded-lg border border-brand-700 bg-brand-950 p-2 shadow-2xl">
          {loading ? (
            <p className="px-2 py-1 text-[11px] text-white/50">
              Calcul…
            </p>
          ) : err ? (
            <p className="px-2 py-1 text-[11px] text-rose-300">{err}</p>
          ) : suggestions.length === 0 ? (
            <p className="px-2 py-1 text-[11px] text-white/50">
              Aucun candidat trouvé.
            </p>
          ) : (
            <ul className="space-y-1">
              {suggestions.map((s, i) => (
                <li key={s.user_id}>
                  <button
                    type="button"
                    onClick={() => {
                      onPick(s.user_id);
                      setOpen(false);
                    }}
                    className="block w-full rounded-md px-2 py-1.5 text-left hover:bg-brand-900"
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="truncate text-xs font-bold text-white">
                        {i === 0 ? "★ " : ""}
                        {s.full_name}
                      </span>
                      <span className="font-mono text-[10px] text-violet-300">
                        {s.score >= 0 ? `+${s.score}` : s.score}
                      </span>
                    </div>
                    <div className="mt-0.5 truncate text-[10px] text-white/50">
                      {s.reasons.join(" · ")}
                    </div>
                    {s.next_free_slot ? (
                      <div className="mt-0.5 text-[10px] text-emerald-300">
                        ⏱ Libre à partir de{" "}
                        {new Date(s.next_free_slot).toLocaleString("fr-CA", {
                          weekday: "short",
                          day: "2-digit",
                          month: "short",
                          hour: "2-digit",
                          minute: "2-digit"
                        })}
                      </div>
                    ) : null}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      ) : null}
    </div>
  );
}

// ─── Section Partenaires ───────────────────────────────────────────────

type Partner = {
  id: number;
  entreprise_id: number;
  user_id: number | null;
  partner_name: string | null;
  partner_email: string | null;
  partner_notes: string | null;
  role: string;
  ownership_pct: number | null;
  display_name: string;
  display_email: string | null;
};

const PARTNER_ROLES = [
  { value: "associe", label: "Associé" },
  { value: "administrateur", label: "Administrateur" },
  { value: "gerant", label: "Gérant" },
  { value: "investisseur", label: "Investisseur" },
  { value: "preteur", label: "Prêteur" },
  { value: "autre", label: "Autre" }
];

function PartnersSection({ entrepriseId }: { entrepriseId: number }) {
  const [list, setList] = useState<Partner[] | null>(null);
  const [showAdd, setShowAdd] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);

  async function reload() {
    const res = await authedFetch(
      `/api/v1/entreprises/${entrepriseId}/partners`
    );
    if (res.ok) setList((await res.json()) as Partner[]);
  }
  useEffect(() => {
    void reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [entrepriseId]);

  async function remove(p: Partner) {
    if (!confirm(`Retirer « ${p.display_name} » de l'entreprise ?`)) return;
    await authedFetch(`/api/v1/entreprises/partners/${p.id}`, {
      method: "DELETE"
    });
    void reload();
  }

  const totalPct = (list || []).reduce(
    (a, p) => a + (Number(p.ownership_pct) || 0),
    0
  );

  return (
    <section className="mt-6 rounded-2xl border border-brand-800 bg-brand-900 p-5">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 className="text-sm font-semibold uppercase tracking-wider text-violet-300">
            Partenaires & parts
          </h2>
          {list && list.length > 0 ? (
            <p className="mt-0.5 text-[11px] text-white/50">
              Total parts détenues : {totalPct.toFixed(2)}%
              {totalPct < 100 && totalPct > 0
                ? ` · ${(100 - totalPct).toFixed(2)}% non attribués`
                : totalPct > 100
                ? " ⚠️ dépasse 100%"
                : ""}
            </p>
          ) : null}
        </div>
        <button
          type="button"
          onClick={() => {
            setEditingId(null);
            setShowAdd(true);
          }}
          className="inline-flex items-center gap-1.5 rounded-lg border border-violet-400/30 bg-violet-500/10 px-3 py-1.5 text-xs font-semibold text-violet-200 hover:bg-violet-500/20"
        >
          <Plus className="h-3.5 w-3.5" /> Ajouter un partenaire
        </button>
      </div>

      {list === null ? (
        <p className="text-xs text-white/50">
          <Loader2 className="mr-1 inline h-3 w-3 animate-spin" /> Chargement…
        </p>
      ) : list.length === 0 ? (
        <p className="rounded-lg border border-dashed border-brand-800 bg-brand-950 p-3 text-xs text-white/50">
          Aucun partenaire enregistré.
        </p>
      ) : (
        <ul className="space-y-2">
          {list.map((p) => (
            <li
              key={p.id}
              className="flex flex-wrap items-center gap-3 rounded-xl border border-brand-800 bg-brand-950 p-3"
            >
              <span className="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-full bg-violet-500/15 text-[11px] font-bold text-violet-300">
                {p.display_name
                  .split(/\s+/)
                  .filter(Boolean)
                  .slice(0, 2)
                  .map((s) => s[0]?.toUpperCase() || "")
                  .join("")}
              </span>
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-sm font-bold text-white">
                    {p.display_name}
                  </span>
                  <span className="rounded-full border border-white/15 bg-brand-900 px-2 py-0.5 text-[10px] font-semibold text-white/70">
                    {PARTNER_ROLES.find((r) => r.value === p.role)?.label ||
                      p.role}
                  </span>
                </div>
                <p className="text-[11px] text-white/50">
                  {p.display_email || "—"}
                  {p.user_id ? (
                    <span className="ml-2 text-emerald-300">· compte portail</span>
                  ) : null}
                </p>
                {p.partner_notes ? (
                  <p className="mt-1 text-[11px] text-white/60">{p.partner_notes}</p>
                ) : null}
              </div>
              <div className="flex items-center gap-2">
                <span className="font-mono text-sm font-bold text-violet-300">
                  {p.ownership_pct != null
                    ? `${Number(p.ownership_pct).toFixed(2)}%`
                    : "—"}
                </span>
                <button
                  type="button"
                  onClick={() => {
                    setEditingId(p.id);
                    setShowAdd(true);
                  }}
                  className="rounded-lg border border-white/15 bg-brand-900 p-1.5 text-white/60 hover:text-violet-200"
                  title="Modifier"
                >
                  <Pencil className="h-3.5 w-3.5" />
                </button>
                <button
                  type="button"
                  onClick={() => remove(p)}
                  className="rounded-lg border border-white/15 bg-brand-900 p-1.5 text-white/40 hover:border-rose-400/50 hover:text-rose-300"
                  title="Retirer"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}

      {showAdd ? (
        <PartnerModal
          entrepriseId={entrepriseId}
          existing={
            editingId != null ? list?.find((p) => p.id === editingId) : null
          }
          onClose={() => {
            setShowAdd(false);
            setEditingId(null);
          }}
          onSaved={() => {
            setShowAdd(false);
            setEditingId(null);
            void reload();
          }}
        />
      ) : null}
    </section>
  );
}

function PartnerModal({
  entrepriseId,
  existing,
  onClose,
  onSaved
}: {
  entrepriseId: number;
  existing?: Partner | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [partnerName, setPartnerName] = useState(existing?.partner_name || "");
  const [partnerEmail, setPartnerEmail] = useState(
    existing?.partner_email || ""
  );
  const [role, setRole] = useState(existing?.role || "associe");
  const [pct, setPct] = useState(
    existing?.ownership_pct != null ? String(existing.ownership_pct) : ""
  );
  const [notes, setNotes] = useState(existing?.partner_notes || "");
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setErr(null);
    try {
      const body: Record<string, unknown> = {
        entreprise_id: entrepriseId,
        role,
        partner_name: partnerName.trim() || null,
        partner_email: partnerEmail.trim() || null,
        partner_notes: notes.trim() || null,
        ownership_pct: pct.trim() ? Number(pct) : null
      };
      const url = existing
        ? `/api/v1/entreprises/partners/${existing.id}`
        : "/api/v1/entreprises/partners";
      const res = await authedFetch(url, {
        method: existing ? "PATCH" : "POST",
        body: JSON.stringify(body)
      });
      if (!res.ok) {
        const t = await res.text();
        throw new Error(t.slice(0, 240) || `HTTP ${res.status}`);
      }
      onSaved();
    } catch (e2) {
      setErr((e2 as Error).message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/70 p-4 backdrop-blur-sm">
      <div className="my-8 w-full max-w-lg rounded-2xl border border-brand-800 bg-brand-950 shadow-2xl">
        <div className="border-b border-brand-800 px-5 py-3">
          <h2 className="text-sm font-bold uppercase tracking-wider text-violet-300">
            {existing ? "Modifier le partenaire" : "Nouveau partenaire"}
          </h2>
        </div>
        <form onSubmit={submit} className="grid gap-3 p-5">
          <div>
            <label className="label">Nom complet</label>
            <input
              required={!existing}
              value={partnerName}
              onChange={(e) => setPartnerName(e.target.value)}
              className="input"
              placeholder="ex. Steven Giguère"
            />
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <label className="label">Email (optionnel)</label>
              <input
                type="email"
                value={partnerEmail}
                onChange={(e) => setPartnerEmail(e.target.value)}
                className="input"
              />
            </div>
            <div>
              <label className="label">Rôle</label>
              <select
                value={role}
                onChange={(e) => setRole(e.target.value)}
                className="input"
              >
                {PARTNER_ROLES.map((r) => (
                  <option key={r.value} value={r.value}>
                    {r.label}
                  </option>
                ))}
              </select>
            </div>
          </div>
          <div>
            <label className="label">Parts détenues (%)</label>
            <input
              type="number"
              step="0.01"
              min={0}
              max={100}
              value={pct}
              onChange={(e) => setPct(e.target.value)}
              className="input font-mono"
              placeholder="ex. 50.00"
            />
          </div>
          <div>
            <label className="label">Notes</label>
            <textarea
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              rows={2}
              className="input"
              placeholder="Conditions particulières, classes d'actions, ententes…"
            />
          </div>

          {err ? (
            <p className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
              {err}
            </p>
          ) : null}

          <div className="flex items-center justify-end gap-2 border-t border-brand-800 pt-3">
            <button type="button" onClick={onClose} className="btn-secondary text-sm">
              Annuler
            </button>
            <button
              type="submit"
              disabled={saving}
              className="btn-accent inline-flex items-center text-sm disabled:opacity-60"
            >
              {saving ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : existing ? (
                "Enregistrer"
              ) : (
                "Ajouter"
              )}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

// ─── Section Liens documentation ───────────────────────────────────────

type EntrepriseLink = {
  id: number;
  entreprise_id: number;
  label: string;
  url: string;
  kind: string;
  notes: string | null;
  created_at: string;
};

const LINK_KINDS = [
  { value: "drive", label: "Google Drive", icon: "🗂️" },
  { value: "sharepoint", label: "SharePoint / OneDrive", icon: "🔷" },
  { value: "dropbox", label: "Dropbox", icon: "📦" },
  { value: "onenote", label: "OneNote", icon: "📓" },
  { value: "notion", label: "Notion", icon: "📑" },
  { value: "website", label: "Site web", icon: "🌐" },
  { value: "autre", label: "Autre", icon: "🔗" }
];

function LinksSection({ entrepriseId }: { entrepriseId: number }) {
  const [list, setList] = useState<EntrepriseLink[] | null>(null);
  const [showAdd, setShowAdd] = useState(false);

  async function reload() {
    const res = await authedFetch(
      `/api/v1/entreprises/${entrepriseId}/links`
    );
    if (res.ok) setList((await res.json()) as EntrepriseLink[]);
  }
  useEffect(() => {
    void reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [entrepriseId]);

  async function remove(l: EntrepriseLink) {
    if (!confirm(`Retirer le lien « ${l.label} » ?`)) return;
    await authedFetch(`/api/v1/entreprises/links/${l.id}`, {
      method: "DELETE"
    });
    void reload();
  }

  return (
    <section className="mt-6 rounded-2xl border border-brand-800 bg-brand-900 p-5">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-violet-300">
          Liens & documentation
        </h2>
        <button
          type="button"
          onClick={() => setShowAdd(true)}
          className="inline-flex items-center gap-1.5 rounded-lg border border-violet-400/30 bg-violet-500/10 px-3 py-1.5 text-xs font-semibold text-violet-200 hover:bg-violet-500/20"
        >
          <Plus className="h-3.5 w-3.5" /> Ajouter un lien
        </button>
      </div>

      {list === null ? (
        <p className="text-xs text-white/50">
          <Loader2 className="mr-1 inline h-3 w-3 animate-spin" /> Chargement…
        </p>
      ) : list.length === 0 ? (
        <p className="rounded-lg border border-dashed border-brand-800 bg-brand-950 p-3 text-xs text-white/50">
          Aucun lien. Ajoute le drive de l&apos;entreprise pour accès rapide.
        </p>
      ) : (
        <ul className="grid gap-2 sm:grid-cols-2">
          {list.map((l) => {
            const kind = LINK_KINDS.find((k) => k.value === l.kind);
            return (
              <li key={l.id}>
                <div className="flex items-center gap-2 rounded-xl border border-brand-800 bg-brand-950 p-3">
                  <span className="text-xl">{kind?.icon || "🔗"}</span>
                  <div className="min-w-0 flex-1">
                    <a
                      href={l.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="block truncate text-sm font-bold text-white hover:text-violet-300"
                    >
                      {l.label} ↗
                    </a>
                    <p className="truncate text-[10px] text-white/40">
                      {kind?.label || l.kind}
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={() => remove(l)}
                    className="rounded-lg border border-white/15 bg-brand-900 p-1.5 text-white/40 hover:border-rose-400/50 hover:text-rose-300"
                    title="Retirer"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </div>
              </li>
            );
          })}
        </ul>
      )}

      {showAdd ? (
        <LinkModal
          entrepriseId={entrepriseId}
          onClose={() => setShowAdd(false)}
          onSaved={() => {
            setShowAdd(false);
            void reload();
          }}
        />
      ) : null}
    </section>
  );
}

function LinkModal({
  entrepriseId,
  onClose,
  onSaved
}: {
  entrepriseId: number;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [label, setLabel] = useState("");
  const [url, setUrl] = useState("");
  const [kind, setKind] = useState("drive");
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setErr(null);
    try {
      const res = await authedFetch("/api/v1/entreprises/links", {
        method: "POST",
        body: JSON.stringify({
          entreprise_id: entrepriseId,
          label: label.trim(),
          url: url.trim(),
          kind
        })
      });
      if (!res.ok) {
        const t = await res.text();
        throw new Error(t.slice(0, 240) || `HTTP ${res.status}`);
      }
      onSaved();
    } catch (e2) {
      setErr((e2 as Error).message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/70 p-4 backdrop-blur-sm">
      <div className="my-8 w-full max-w-lg rounded-2xl border border-brand-800 bg-brand-950 shadow-2xl">
        <div className="border-b border-brand-800 px-5 py-3">
          <h2 className="text-sm font-bold uppercase tracking-wider text-violet-300">
            Nouveau lien
          </h2>
        </div>
        <form onSubmit={submit} className="grid gap-3 p-5">
          <div>
            <label className="label">Libellé</label>
            <input
              required
              value={label}
              onChange={(e) => setLabel(e.target.value)}
              className="input"
              placeholder="ex. Drive HSI, statuts, P&L…"
            />
          </div>
          <div>
            <label className="label">URL</label>
            <input
              required
              type="url"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              className="input font-mono text-xs"
              placeholder="https://drive.google.com/drive/folders/..."
            />
          </div>
          <div>
            <label className="label">Type</label>
            <select
              value={kind}
              onChange={(e) => setKind(e.target.value)}
              className="input"
            >
              {LINK_KINDS.map((k) => (
                <option key={k.value} value={k.value}>
                  {k.icon} {k.label}
                </option>
              ))}
            </select>
          </div>

          {err ? (
            <p className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
              {err}
            </p>
          ) : null}

          <div className="flex items-center justify-end gap-2 border-t border-brand-800 pt-3">
            <button type="button" onClick={onClose} className="btn-secondary text-sm">
              Annuler
            </button>
            <button
              type="submit"
              disabled={saving || !label.trim() || !url.trim()}
              className="btn-accent inline-flex items-center text-sm disabled:opacity-60"
            >
              {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : "Ajouter"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
