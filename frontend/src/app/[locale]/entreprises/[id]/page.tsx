"use client";

import { useEffect, useMemo, useState } from "react";
import { useParams } from "next/navigation";
import {
  ArrowLeft,
  Briefcase,
  Calendar,
  ChevronDown,
  ChevronRight,
  ChevronUp,
  Loader2,
  Pause,
  Pencil,
  Play,
  Plus,
  Repeat,
  Trash2
} from "lucide-react";

import { Link, useRouter } from "@/i18n/navigation";
import { authedFetch } from "@/lib/auth";
import { EntreprisesTopbar } from "../layout";
import { useConfirm } from "@/components/confirm-dialog";
import { DriveButton } from "@/components/drive-button";
import {
  AssigneePicker,
  type TaskUserMini
} from "@/components/task-pills";
import { TaskBoard, type TaskBoardItem } from "@/components/task-board";
import {
  ImmeublePicker,
  ManageImmeublesButton,
  type ImmeubleMini
} from "@/components/immeuble-picker";
import {
  TASK_PRIORITY_OPTIONS,
  TASK_STATUS_OPTIONS
} from "@/lib/task-config";

type Entreprise = {
  id: number;
  name: string;
  type: string;
  color_accent: string;
  description: string | null;
  drive_folder_url: string | null;
  monday_board_id: string | null;
  monday_board_name: string | null;
  is_parent_company?: boolean;
};

type Tache = {
  id: number;
  entreprise_id: number;
  title: string;
  description: string | null;
  departement: string | null;
  status: string;
  // Priorité Monday-style alignée sur les tâches du Pipeline
  // (urgent / eleve / moyenne / faible).
  priority: string;
  impact: number | null;
  confidence: number | null;
  effort: number | null;
  // Champ legacy (= primary) ; la liste ci-dessous est la source de vérité.
  assignee_user_id: number | null;
  assignee_user_ids: number[];
  due_date: string | null;
  completed_at: string | null;
  recurrence: string | null;
  tags_json: string | null;
  monday_item_id: string | null;
  monday_group_title: string | null;
  score: number | null;
  immeuble_ids: number[];
  position: number;
};

type Employe = { id: number; full_name: string; email: string | null };

type Column = { id: string; label: string; dot: string };

// Mêmes 4 statuts (et couleurs) que le Pipeline des deals
// (volet Prospection > Acquisition) — uniformité demandée par
// l'utilisateur. Seuls les libellés visibles diffèrent des clés
// DB historiques.
// Dérivé du module partagé /lib/task-config — les libellés et
// pastilles bougent partout en même temps quand on les modifie là.
const COLUMNS: Column[] = TASK_STATUS_OPTIONS.map((o) => ({
  id: o.value,
  label: o.label,
  dot: o.dot
}));

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
  const router = useRouter();

  const [ent, setEnt] = useState<Entreprise | null>(null);
  const [taches, setTaches] = useState<Tache[]>([]);
  const [employes, setEmployes] = useState<Employe[]>([]);
  // Liste des users (avec leur profil enrichi : prénom/nom/couleur/avatar)
  // pour alimenter l'AssigneePicker des cartes de tâche.
  const [users, setUsers] = useState<TaskUserMini[]>([]);
  const [immeubles, setImmeubles] = useState<ImmeubleMini[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  // La modale détaillée est désormais gérée à l'intérieur du
  // composant partagé <TaskBoard>. Plus besoin de state local pour
  // l'ouvrir.
  // Tâche à déplacer vers une autre entreprise. Quand c'est défini,
  // on affiche un mini dialogue qui liste les entreprises.
  const [moveTask, setMoveTask] = useState<Tache | null>(null);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const [entRes, tachesRes, empRes, usersRes, immRes] = await Promise.all([
        authedFetch(`/api/v1/entreprises`),
        authedFetch(`/api/v1/entreprises/taches?entreprise_id=${id}`),
        authedFetch("/api/v1/employes?limit=500"),
        authedFetch("/api/v1/users"),
        authedFetch(`/api/v1/immobilier/immeubles/picker?entreprise_id=${id}`)
      ]);
      if (!entRes.ok) throw new Error(`HTTP ${entRes.status}`);
      const ents = (await entRes.json()) as Entreprise[];
      const found = ents.find((e) => e.id === id);
      if (!found) throw new Error("Entreprise introuvable");
      setEnt(found);
      if (tachesRes.ok) setTaches((await tachesRes.json()) as Tache[]);
      if (empRes.ok) setEmployes((await empRes.json()) as Employe[]);
      if (usersRes.ok) {
        const all = (await usersRes.json()) as Array<
          TaskUserMini & { volets?: string[] }
        >;
        setUsers(
          all.filter((u) => (u.volets || []).includes("entreprises"))
        );
      }
      if (immRes.ok) setImmeubles((await immRes.json()) as ImmeubleMini[]);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (Number.isFinite(id) && id > 0) {
      void load();
    } else {
      // ID invalide (ex. /entreprises/undefined) → on coupe le loader
      // pour afficher un message d'erreur clair au lieu d'un spin sans fin.
      setLoading(false);
      setError("Identifiant d'entreprise invalide.");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  // Re-fetch du catalogue d'immeubles après ajout/retrait via le
  // bouton « Gérer » du picker.
  async function reloadImmeubles() {
    try {
      const r = await authedFetch(`/api/v1/immobilier/immeubles/picker?entreprise_id=${id}`);
      if (r.ok) setImmeubles((await r.json()) as ImmeubleMini[]);
    } catch {
      /* l'erreur est déjà signalée dans le dialog. */
    }
  }

  // Tache → TaskBoardItem. Le footer reprend les badges spécifiques
  // entreprise (score ICE, récurrence, département) ; pour les
  // tâches Pipeline ces métadonnées n'existent pas, donc le footer
  // y est laissé vide.
  const immeubleNameById = useMemo(
    () => new Map(immeubles.map((i) => [i.id, i.name] as const)),
    [immeubles]
  );
  const boardItems: TaskBoardItem[] = useMemo(
    () =>
      taches.map((t) => ({
        id: t.id,
        title: t.title,
        status: t.status,
        priority: t.priority || "non_assigne",
        due_date: t.due_date,
        assignee_user_ids: t.assignee_user_ids || [],
        hasNote: Boolean(t.description),
        notes: t.description,
        departement: t.departement,
        recurrence: t.recurrence,
        impact: t.impact,
        confidence: t.confidence,
        effort: t.effort,
        score: t.score,
        // Position : si l'utilisateur a drag-droppé (position != 0),
        // on l'utilise telle quelle ; sinon on retombe sur un
        // classement par score (le score le plus haut en premier ;
        // mappé en position négative car le tri est ascendant).
        position:
          t.position && t.position !== 0
            ? t.position
            : t.score != null
              ? -Math.round(t.score * 1000)
              : 0,
        immeuble_ids: t.immeuble_ids || [],
        immeubleLabels: (t.immeuble_ids || [])
          .map((id) => immeubleNameById.get(id))
          .filter((n): n is string => Boolean(n)),
        // Footer : département (si applicable). La récurrence n'est
        // plus inline sur la tâche — gérée par les modèles récurrents
        // (voir section dédiée et /entreprises/taches/recurrentes).
        // Le score est déjà affiché dans la pastille « P · score ».
        footer:
          t.departement ? (
            <div className="flex flex-wrap items-center gap-1 text-[9px] text-white/40">
              {t.departement ? (
                <span className="rounded-full border border-brand-700 px-1.5 py-0.5">
                  {t.departement}
                </span>
              ) : null}
            </div>
          ) : null
      })),
    [taches, immeubleNameById]
  );

  async function renameEntreprise() {
    if (!ent) return;
    const next = window.prompt(
      "Nouveau nom de l'entreprise :",
      ent.name
    );
    if (next == null) return;
    const v = next.trim();
    if (!v || v === ent.name) return;
    const prev = ent;
    setEnt({ ...ent, name: v });
    try {
      const r = await authedFetch(`/api/v1/entreprises/${ent.id}`, {
        method: "PATCH",
        body: JSON.stringify({ name: v })
      });
      if (!r.ok) throw new Error();
    } catch {
      setEnt(prev);
      setError("Renommage échoué.");
    }
  }

  async function removeEntreprise() {
    if (!ent) return;
    const ok = await confirm({
      title: `Supprimer « ${ent.name} » ?`,
      description:
        "Cette action est irréversible. Toutes les tâches, partenaires, " +
        "et liens associés à cette entreprise seront aussi supprimés.",
      confirmLabel: "Supprimer",
      destructive: true
    });
    if (!ok) return;
    try {
      const res = await authedFetch(`/api/v1/entreprises/${ent.id}`, {
        method: "DELETE"
      });
      if (!res.ok && res.status !== 204) {
        throw new Error(`HTTP ${res.status}`);
      }
      router.replace("/entreprises");
    } catch (err) {
      setError(
        `Suppression échouée — ${(err as Error).message || "erreur inconnue"}`
      );
    }
  }

  // Création inline depuis le bouton « + Tâche » d'une colonne du
  // kanban (et depuis « + Nouvelle tâche » en haut de la section, qui
  // ouvre directement la fiche détaillée pour finir de remplir).
  // Retourne l'id créé pour que <TaskBoard> puisse ouvrir la modale.
  async function createTacheInline(
    status: string,
    title: string
  ): Promise<number | null> {
    if (!ent) return null;
    try {
      const res = await authedFetch("/api/v1/entreprises/taches", {
        method: "POST",
        body: JSON.stringify({
          entreprise_id: ent.id,
          title,
          status
        })
      });
      if (!res.ok) throw new Error();
      const created = (await res.json()) as Tache;
      setTaches((xs) => [...xs, created]);
      return created.id;
    } catch {
      setError("Création de tâche échouée.");
      return null;
    }
  }

  async function patchTache(tacheId: number, patch: Partial<Tache>) {
    const prev = taches;
    setTaches((xs) =>
      xs.map((x) => (x.id === tacheId ? { ...x, ...patch } : x))
    );
    try {
      const res = await authedFetch(
        `/api/v1/entreprises/taches/${tacheId}`,
        {
          method: "PATCH",
          body: JSON.stringify(patch)
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
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="text-2xl font-bold text-white">{ent.name}</h1>
              <DriveButton
                url={ent.drive_folder_url}
                onSave={async (newUrl) => {
                  const r = await authedFetch(
                    `/api/v1/entreprises/${ent.id}`,
                    {
                      method: "PATCH",
                      body: JSON.stringify({ drive_folder_url: newUrl })
                    }
                  );
                  if (!r.ok) throw new Error(`HTTP ${r.status}`);
                  setEnt({ ...ent, drive_folder_url: newUrl || null });
                }}
              />
            </div>
            {ent.description ? (
              <p className="mt-1 text-sm text-white/60">{ent.description}</p>
            ) : null}
          </div>
          {/* Compteur de tâches + petit bouton « supprimer
              l'entreprise » juste en dessous (avec confirm). */}
          <div className="flex flex-col items-end gap-1.5">
            <div className="rounded-md bg-brand-900 px-3 py-2 text-sm">
              <span className="text-white/50">Tâches </span>
              <span className="font-bold text-white">{taches.length}</span>
            </div>
            <div className="flex items-center gap-1">
              <button
                type="button"
                onClick={renameEntreprise}
                title="Renommer l'entreprise"
                aria-label="Renommer l'entreprise"
                className="rounded-md p-1.5 text-white/40 transition hover:bg-violet-500/15 hover:text-violet-300"
              >
                <Pencil className="h-4 w-4" />
              </button>
              <button
                type="button"
                onClick={removeEntreprise}
                title="Supprimer cette entreprise"
                aria-label="Supprimer l'entreprise"
                className="rounded-md p-1.5 text-white/40 transition hover:bg-rose-500/15 hover:text-rose-300"
              >
                <Trash2 className="h-4 w-4" />
              </button>
            </div>
          </div>
        </header>

        {/* Daily Pulse — briefing IA quotidien */}
        <DailyPulseCard entrepriseId={ent.id} accent={ent.color_accent} />

        {/* Lien rapide vers les rencontres tagguées sur cette entreprise */}
        <Link
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          href={`/entreprises/rencontres?entreprise=${ent.id}` as any}
          className="mt-6 flex items-center gap-3 rounded-2xl border border-brand-800 bg-brand-900 p-5 transition hover:border-accent-500"
        >
          <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-accent-500/15 text-accent-500">
            <Calendar className="h-5 w-5" />
          </span>
          <div className="min-w-0 flex-1">
            <h2 className="text-base font-bold text-white">Rencontres</h2>
            <p className="mt-0.5 text-xs text-white/60">
              Comptes rendus de conseils d&apos;actionnaires et retraites
              stratégiques où cette entreprise est concernée.
            </p>
          </div>
          <ChevronRight className="h-4 w-4 text-white/40" />
        </Link>

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

        <TaskBoard
          tasks={boardItems}
          users={users}
          immeubles={immeubles}
          immeubleScope={{ entreprise_id: id }}
          onImmeublesChanged={() => void reloadImmeubles()}
          headerSlot={
            <Link
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
              href={"/entreprises/taches/recurrentes" as any}
              className="inline-flex items-center gap-1.5 rounded-lg bg-violet-400 px-3 py-1.5 text-xs font-semibold text-brand-950 shadow hover:bg-violet-300"
              title="Gérer les modèles de tâches récurrentes (cross-entreprise)"
            >
              <Repeat className="h-3.5 w-3.5" />
              Modèles récurrents
            </Link>
          }
          onPatch={(taskId, patch) => {
            const out: Partial<Tache> = {};
            if (patch.title !== undefined) out.title = patch.title;
            if (patch.notes !== undefined) out.description = patch.notes;
            if (patch.status !== undefined) out.status = patch.status;
            if (patch.priority !== undefined) out.priority = patch.priority;
            if (patch.due_date !== undefined) out.due_date = patch.due_date;
            if (patch.assignee_user_ids !== undefined) {
              out.assignee_user_ids = patch.assignee_user_ids;
              out.assignee_user_id = patch.assignee_user_ids[0] ?? null;
            }
            if (patch.immeuble_ids !== undefined) {
              out.immeuble_ids = patch.immeuble_ids;
            }
            if (patch.departement !== undefined) out.departement = patch.departement;
            if (patch.impact !== undefined) out.impact = patch.impact;
            if (patch.confidence !== undefined) out.confidence = patch.confidence;
            if (patch.effort !== undefined) out.effort = patch.effort;
            if (patch.position !== undefined) out.position = patch.position;
            void patchTache(taskId, out);
          }}
          onDelete={(taskId) => {
            const t = taches.find((x) => x.id === taskId);
            if (t) void removeTache(t);
          }}
          onMove={(taskId) => {
            const t = taches.find((x) => x.id === taskId);
            if (t) setMoveTask(t);
          }}
          onCreate={(status, name) => createTacheInline(status, name)}
        />
      </div>

      {moveTask ? (
        <MoveTacheDialog
          task={moveTask}
          currentEntId={ent.id}
          onClose={() => setMoveTask(null)}
          onMoved={() => {
            // Tâche partie ailleurs : on l'enlève de la liste locale.
            setTaches((xs) => xs.filter((x) => x.id !== moveTask.id));
            setMoveTask(null);
          }}
        />
      ) : null}
    </>
  );
}

/**
 * Dialogue qui demande l'entreprise cible pour déplacer une tâche.
 * Liste les entreprises actives (sauf la courante) et patche
 * EntrepriseTache.entreprise_id côté serveur.
 */
function MoveTacheDialog({
  task,
  currentEntId,
  onClose,
  onMoved
}: {
  task: Tache;
  currentEntId: number;
  onClose: () => void;
  onMoved: () => void;
}) {
  const [list, setList] = useState<Entreprise[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const res = await authedFetch("/api/v1/entreprises");
        if (!res.ok) throw new Error();
        const all = (await res.json()) as Entreprise[];
        setList(all.filter((e) => e.id !== currentEntId));
      } catch {
        setErr("Impossible de charger la liste des entreprises.");
      } finally {
        setLoading(false);
      }
    })();
  }, [currentEntId]);

  async function move(targetId: number) {
    setBusy(true);
    setErr(null);
    try {
      const res = await authedFetch(
        `/api/v1/entreprises/taches/${task.id}`,
        {
          method: "PATCH",
          body: JSON.stringify({ entreprise_id: targetId })
        }
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      onMoved();
    } catch (e) {
      setErr((e as Error).message || "Déplacement échoué.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4"
      onClick={() => (!busy ? onClose() : null)}
    >
      <div
        className="w-full max-w-md rounded-2xl border border-brand-800 bg-brand-950 p-5"
        onClick={(e) => e.stopPropagation()}
      >
        <h3 className="text-base font-bold text-white">
          Déplacer « {task.title} »
        </h3>
        <p className="mt-1 text-xs text-white/50">
          Choisis l&apos;entreprise vers laquelle déplacer la tâche.
        </p>

        {loading ? (
          <div className="flex items-center justify-center py-8">
            <Loader2 className="h-5 w-5 animate-spin text-accent-500" />
          </div>
        ) : list.length === 0 ? (
          <p className="mt-4 rounded-md border border-dashed border-brand-800 bg-brand-900/40 px-3 py-3 text-center text-xs text-white/50">
            Aucune autre entreprise — créez-en une dans Mes entreprises.
          </p>
        ) : (
          <ul className="mt-4 max-h-72 space-y-1 overflow-y-auto">
            {list.map((e) => (
              <li key={e.id}>
                <button
                  type="button"
                  onClick={() => move(e.id)}
                  disabled={busy}
                  className="flex w-full items-center gap-2 rounded-lg border border-brand-800 bg-brand-900 px-3 py-2 text-left text-sm text-white hover:border-violet-500/50 hover:bg-violet-500/10 disabled:opacity-50"
                >
                  <span
                    className="h-2 w-2 flex-shrink-0 rounded-full"
                    style={{ backgroundColor: e.color_accent }}
                  />
                  <span className="truncate">{e.name}</span>
                </button>
              </li>
            ))}
          </ul>
        )}

        {err ? (
          <p className="mt-3 rounded-md border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
            {err}
          </p>
        ) : null}

        <div className="mt-4 flex items-center justify-end">
          <button
            type="button"
            onClick={onClose}
            disabled={busy}
            className="btn-secondary text-sm"
          >
            Annuler
          </button>
        </div>
      </div>
    </div>
  );
}

// Le rendu d'une carte de tâche est entièrement délégué au
// composant partagé <TaskBoard> → <TaskCard>, qui consomme
// directement /lib/task-config. Toute évolution visuelle de la
// carte se fait dans /components/task-card.tsx (et /task-board.tsx
// pour la mise en page du kanban).



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
  // Bouton réduire / étendre — la section reste visible mais on
  // cache le contenu détaillé pour libérer de l'espace vertical.
  const [expanded, setExpanded] = useState(true);

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
      className="mt-4 overflow-hidden rounded-2xl border bg-brand-900 p-5"
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
          <button
            type="button"
            onClick={() => setExpanded((v) => !v)}
            title={expanded ? "Réduire" : "Étendre"}
            aria-label={expanded ? "Réduire le briefing" : "Étendre le briefing"}
            className="rounded-md border border-brand-700 bg-brand-900 p-1 text-white/60 transition hover:text-white"
          >
            {expanded ? (
              <ChevronUp className="h-3.5 w-3.5" />
            ) : (
              <ChevronDown className="h-3.5 w-3.5" />
            )}
          </button>
        </div>
      </div>

      {!expanded ? null : loading ? (
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
          className="inline-flex items-center gap-1.5 rounded-lg bg-violet-400 px-3 py-1.5 text-xs font-semibold text-brand-950 shadow hover:bg-violet-300"
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
          className="inline-flex items-center gap-1.5 rounded-lg bg-violet-400 px-3 py-1.5 text-xs font-semibold text-brand-950 shadow hover:bg-violet-300"
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

// ─── Vue liste / tableau des tâches d'une entreprise ────────────────────

// La vue Tableau a été extraite dans <TaskBoard /> partagé. Plus de
// composant local nécessaire ici.

