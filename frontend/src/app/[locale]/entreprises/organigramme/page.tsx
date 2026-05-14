"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Briefcase,
  Building2,
  ChevronDown,
  ChevronRight,
  Download,
  GripVertical,
  Link2,
  Loader2,
  Plus,
  Save,
  Sparkles,
  Star,
  Trash2,
  User as UserIcon,
  Users
} from "lucide-react";

import { authedFetch } from "@/lib/auth";
import { MultiSelectDropdown } from "@/components/multi-select-dropdown";
import { QGTopbar, useEntreprisesLayout } from "../layout";

/**
 * Page Organigramme — inspirée du schéma papier de Steven.
 *
 * Affiche l'arbre des entreprises / départements / rôles / services
 * du groupe en colonnes (top-level), avec sous-nœuds en cascade dans
 * chaque colonne. Chaque nœud :
 *  - kind (company / dept / role / service / task)
 *  - label
 *  - lien optionnel à une entreprise
 *  - assignation (employé interne OU texte externe « Freelance », etc.)
 *  - co-détenteurs (autres entreprises qui possèdent aussi ce nœud)
 *
 * Les entreprises s'importent en un clic (« Importer les entreprises »)
 * comme nœuds `company` à plat, puis se réorganisent par glisser-déposer
 * pour bâtir la hiérarchie de détention (qui détient quoi) et de
 * fonction (qui fait quoi) — entreprises et départements/rôles vivent
 * dans le même arbre. Le détenteur principal donne la position dans
 * l'arbre ; les co-détenteurs s'affichent en badges sur la carte.
 */

type OrgNode = {
  id: number;
  parent_id: number | null;
  position: number;
  kind: string;
  label: string;
  description: string | null;
  entreprise_id: number | null;
  assignee_employe_id: number | null;
  assignee_user_id: number | null;
  assignee_external_name: string | null;
  co_owner_node_ids: number[];
  created_at: string;
  updated_at: string;
};

type Employe = { id: number; full_name: string };

type DropTarget = { id: number; mode: "into" | "before" };

type Dnd = {
  dragId: number | null;
  dropTarget: DropTarget | null;
  draggedSubtree: Set<number>;
  onDragStartNode: (id: number) => void;
  onDragEndNode: () => void;
  onHover: (t: DropTarget | null) => void;
  onDrop: () => void;
  onDropRootEnd: () => void;
};

const KIND_LABELS: Record<string, { label: string; cls: string }> = {
  company: {
    label: "Entreprise",
    cls: "bg-indigo-500/15 text-indigo-300 border-indigo-500/30"
  },
  dept: {
    label: "Département",
    cls: "bg-violet-500/15 text-violet-300 border-violet-500/30"
  },
  role: {
    label: "Rôle",
    cls: "bg-sky-500/15 text-sky-300 border-sky-500/30"
  },
  task: {
    label: "Tâche",
    cls: "bg-amber-500/15 text-amber-300 border-amber-500/30"
  },
  service: {
    label: "Service partagé",
    cls: "bg-emerald-500/15 text-emerald-300 border-emerald-500/30"
  }
};

export default function OrganigrammePage() {
  const { entreprises } = useEntreprisesLayout();
  const [nodes, setNodes] = useState<OrgNode[]>([]);
  const [employes, setEmployes] = useState<Employe[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [creatingTop, setCreatingTop] = useState(false);
  const [newTopLabel, setNewTopLabel] = useState("");
  const [seeding, setSeeding] = useState(false);
  const [importing, setImporting] = useState(false);

  // État du glisser-déposer.
  const [dragId, setDragId] = useState<number | null>(null);
  const [dropTarget, setDropTarget] = useState<DropTarget | null>(null);

  // Entreprise mère du groupe — sert à mettre en évidence SON nœud
  // dans l'arbre (étoile + bordure accent), plutôt qu'un bandeau
  // séparé non interactif.
  const parentEntId = useMemo(() => {
    const e =
      entreprises.find(
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        (x) => (x as any).is_parent_company === true
      ) || entreprises.find((x) => /mgv\s*invest/i.test(x.name));
    return e ? e.id : null;
  }, [entreprises]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [n, e] = await Promise.all([
        authedFetch("/api/v1/org-nodes"),
        authedFetch("/api/v1/employes?limit=500")
      ]);
      if (n.ok) setNodes((await n.json()) as OrgNode[]);
      if (e.ok) setEmployes((await e.json()) as Employe[]);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function seedDefault(force: boolean) {
    setSeeding(true);
    setError(null);
    try {
      const r = await authedFetch(
        `/api/v1/org-nodes/seed-default${force ? "?force=true" : ""}`,
        { method: "POST" }
      );
      if (!r.ok) {
        const txt = await r.text();
        throw new Error(txt.slice(0, 200) || `HTTP ${r.status}`);
      }
      await load();
    } catch (e) {
      setError(`Import échoué : ${(e as Error).message}`);
    } finally {
      setSeeding(false);
    }
  }

  async function importEntreprises() {
    setImporting(true);
    setError(null);
    try {
      const r = await authedFetch("/api/v1/org-nodes/import-entreprises", {
        method: "POST"
      });
      if (!r.ok) {
        const txt = await r.text();
        throw new Error(txt.slice(0, 200) || `HTTP ${r.status}`);
      }
      setNodes((await r.json()) as OrgNode[]);
    } catch (e) {
      setError(`Import des entreprises échoué : ${(e as Error).message}`);
    } finally {
      setImporting(false);
    }
  }

  // Index : parent_id → enfants triés par position
  const byParent = useMemo(() => {
    const m = new Map<number | null, OrgNode[]>();
    for (const n of nodes) {
      const arr = m.get(n.parent_id) || [];
      arr.push(n);
      m.set(n.parent_id, arr);
    }
    for (const arr of m.values()) {
      arr.sort((a, b) => a.position - b.position);
    }
    return m;
  }, [nodes]);

  const topLevel = byParent.get(null) || [];

  // Sous-arbre du nœud en cours de glissement — on l'exclut des cibles
  // de dépôt valides (un nœud ne peut pas atterrir sur lui-même ni
  // sur un de ses descendants).
  const draggedSubtree = useMemo(() => {
    const s = new Set<number>();
    if (dragId == null) return s;
    const stack = [dragId];
    while (stack.length) {
      const cur = stack.pop() as number;
      if (s.has(cur)) continue;
      s.add(cur);
      for (const c of byParent.get(cur) || []) stack.push(c.id);
    }
    return s;
  }, [dragId, byParent]);

  async function moveNode(
    id: number,
    parentId: number | null,
    position: number
  ) {
    try {
      const r = await authedFetch(`/api/v1/org-nodes/${id}/move`, {
        method: "POST",
        body: JSON.stringify({ parent_id: parentId, position })
      });
      if (!r.ok) {
        const txt = await r.text();
        throw new Error(txt.slice(0, 160) || `HTTP ${r.status}`);
      }
      setNodes((await r.json()) as OrgNode[]);
    } catch (e) {
      setError(`Déplacement échoué : ${(e as Error).message}`);
    }
  }

  function handleDrop() {
    const dId = dragId;
    const dt = dropTarget;
    setDragId(null);
    setDropTarget(null);
    if (dId == null || !dt || dt.id === dId) return;
    if (draggedSubtree.has(dt.id)) return;
    const target = nodes.find((n) => n.id === dt.id);
    if (!target) return;

    if (dt.mode === "into") {
      const kids = (byParent.get(dt.id) || []).filter((n) => n.id !== dId);
      void moveNode(dId, dt.id, kids.length);
    } else {
      // Insère avant `target`, sous le même parent. La position est
      // l'index de `target` dans la fratrie une fois le nœud déplacé
      // retiré (le backend recalcule de toute façon).
      const sibs = (byParent.get(target.parent_id) || []).filter(
        (n) => n.id !== dId
      );
      const idx = sibs.findIndex((n) => n.id === target.id);
      void moveNode(dId, target.parent_id, idx < 0 ? sibs.length : idx);
    }
  }

  function handleDropRootEnd() {
    const dId = dragId;
    setDragId(null);
    setDropTarget(null);
    if (dId == null) return;
    const roots = (byParent.get(null) || []).filter((n) => n.id !== dId);
    void moveNode(dId, null, roots.length);
  }

  const dnd: Dnd = {
    dragId,
    dropTarget,
    draggedSubtree,
    onDragStartNode: (id) => setDragId(id),
    onDragEndNode: () => {
      setDragId(null);
      setDropTarget(null);
    },
    onHover: (t) => setDropTarget(t),
    onDrop: handleDrop,
    onDropRootEnd: handleDropRootEnd
  };

  async function createNode(
    parent_id: number | null,
    label: string,
    kind = "dept"
  ) {
    if (!label.trim()) return;
    try {
      const r = await authedFetch("/api/v1/org-nodes", {
        method: "POST",
        body: JSON.stringify({ parent_id, label: label.trim(), kind })
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const created = (await r.json()) as OrgNode;
      setNodes((prev) => [...prev, created]);
      return created;
    } catch (e) {
      setError(`Création échouée : ${(e as Error).message}`);
    }
  }

  async function patchNode(id: number, patch: Partial<OrgNode>) {
    setNodes((prev) =>
      prev.map((n) => (n.id === id ? { ...n, ...patch } : n))
    );
    try {
      await authedFetch(`/api/v1/org-nodes/${id}`, {
        method: "PATCH",
        body: JSON.stringify(patch)
      });
    } catch {
      /* silent */
    }
  }

  async function deleteNode(id: number) {
    if (!window.confirm("Supprimer ce nœud et tous ses enfants ?")) return;
    try {
      const r = await authedFetch(`/api/v1/org-nodes/${id}`, {
        method: "DELETE"
      });
      if (!r.ok && r.status !== 204) throw new Error();
      // Cascade côté DB → on retire tout le sous-arbre côté state.
      const idsToRemove = new Set<number>([id]);
      let changed = true;
      while (changed) {
        changed = false;
        for (const n of nodes) {
          if (
            n.parent_id != null &&
            idsToRemove.has(n.parent_id) &&
            !idsToRemove.has(n.id)
          ) {
            idsToRemove.add(n.id);
            changed = true;
          }
        }
      }
      setNodes((prev) => prev.filter((n) => !idsToRemove.has(n.id)));
    } catch {
      setError("Suppression échouée.");
    }
  }

  async function submitTop(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setCreatingTop(true);
    try {
      await createNode(null, newTopLabel, "dept");
      setNewTopLabel("");
    } finally {
      setCreatingTop(false);
    }
  }

  return (
    <>
      <QGTopbar
        greeting={
          <span className="inline-flex items-center gap-2">
            <Users className="h-4 w-4 text-accent-500" />
            Organigramme
          </span>
        }
        subtitle="Entreprises, départements, rôles — qui détient quoi, qui fait quoi"
      />

      <div className="p-4 lg:p-6">
        {error ? (
          <p className="mb-3 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-600">
            {error}
          </p>
        ) : null}

        {loading ? (
          <div className="flex items-center justify-center py-12">
            <Loader2 className="h-6 w-6 animate-spin text-accent-500" />
          </div>
        ) : (
          <>
            {/* Bandeau de création + import des entreprises */}
            <form
              onSubmit={submitTop}
              className="mb-2 flex flex-wrap items-center gap-2 rounded-xl border p-3"
              style={{
                borderColor: "var(--qg-border)",
                backgroundColor: "var(--qg-card-bg)"
              }}
            >
              <Plus className="h-4 w-4 text-accent-500" />
              <input
                value={newTopLabel}
                onChange={(e) => setNewTopLabel(e.target.value)}
                placeholder="Nouvelle branche (ex. Construction, Dev logiciel, Gestion Immo, Prospection, Comptabilité…)"
                className="input flex-1 min-w-[220px] text-sm"
              />
              <button
                type="submit"
                disabled={creatingTop || !newTopLabel.trim()}
                className="btn-accent inline-flex items-center gap-1 text-xs disabled:opacity-50"
              >
                {creatingTop ? (
                  <Loader2 className="h-3 w-3 animate-spin" />
                ) : (
                  <Plus className="h-3 w-3" />
                )}
                Ajouter
              </button>
              <button
                type="button"
                onClick={() => void importEntreprises()}
                disabled={importing}
                className="inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1.5 text-xs font-semibold disabled:opacity-50"
                style={{
                  borderColor: "var(--qg-border)",
                  color: "var(--qg-text-soft)"
                }}
                title="Crée un nœud pour chaque entreprise du groupe non encore présente dans l'organigramme. Tu les replaces ensuite par glisser-déposer."
              >
                {importing ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Download className="h-3.5 w-3.5" />
                )}
                Importer les entreprises
              </button>
            </form>

            {topLevel.length > 0 ? (
              <p
                className="mb-4 text-[11px]"
                style={{ color: "var(--qg-text-soft)" }}
              >
                Glisse une carte <strong>sur</strong> une autre (n&apos;importe
                où dans sa colonne) pour qu&apos;elle en devienne l&apos;enfant
                — changement de détenteur. Glisse <strong>entre deux</strong>{" "}
                cartes pour les réordonner. Plusieurs détenteurs ? Ouvre la
                carte (chevron) → <strong>Co-détenteurs</strong>.
              </p>
            ) : null}

            {topLevel.length === 0 ? (
              <div
                className="rounded-2xl border border-dashed p-6 text-center text-sm"
                style={{
                  borderColor: "var(--qg-border-soft)",
                  color: "var(--qg-text-muted)"
                }}
              >
                <p>Aucun nœud d&apos;organigramme pour l&apos;instant.</p>
                <div className="mt-3 flex flex-wrap items-center justify-center gap-2">
                  <button
                    type="button"
                    onClick={() => void importEntreprises()}
                    disabled={importing}
                    className="btn-accent inline-flex items-center gap-1.5 text-sm disabled:opacity-50"
                    title="Crée un nœud pour chaque entreprise du groupe."
                  >
                    {importing ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    ) : (
                      <Download className="h-3.5 w-3.5" />
                    )}
                    Importer les entreprises
                  </button>
                  <button
                    type="button"
                    onClick={() => void seedDefault(false)}
                    disabled={seeding}
                    className="inline-flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-sm font-semibold disabled:opacity-50"
                    style={{
                      borderColor: "var(--qg-border)",
                      color: "var(--qg-text-soft)"
                    }}
                    title="Crée la structure de départ basée sur ton carnet (Construction, Dev logiciel, Gestion Immo, Prospection, Dev Immo / Aguci, Comptabilité + rôles et tâches)"
                  >
                    {seeding ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    ) : (
                      <Save className="h-3.5 w-3.5" />
                    )}
                    Importer le canevas du carnet
                  </button>
                </div>
                <span
                  className="mt-2 block text-[10px]"
                  style={{ color: "var(--qg-text-soft)" }}
                >
                  ou ajoute manuellement une branche ci-dessus
                </span>
              </div>
            ) : (
              <div className="flex items-stretch gap-1 overflow-x-auto pb-4">
                {topLevel.map((n) => (
                  <div key={n.id} className="flex items-stretch">
                    <DropBar targetId={n.id} dnd={dnd} vertical />
                    <ColumnView
                      node={n}
                      byParent={byParent}
                      allNodes={nodes}
                      entreprises={entreprises}
                      employes={employes}
                      parentEntId={parentEntId}
                      dnd={dnd}
                      onCreate={createNode}
                      onPatch={patchNode}
                      onDelete={deleteNode}
                    />
                  </div>
                ))}
                {/* Zone de dépôt finale : ramène un nœud à la racine. */}
                {dragId != null ? (
                  <div
                    onDragOver={(e) => {
                      e.preventDefault();
                      dnd.onHover(null);
                    }}
                    onDrop={(e) => {
                      e.preventDefault();
                      dnd.onDropRootEnd();
                    }}
                    className="flex w-[150px] shrink-0 items-center justify-center rounded-xl border border-dashed text-center text-[11px]"
                    style={{
                      borderColor: "var(--qg-accent)",
                      color: "var(--qg-text-soft)"
                    }}
                  >
                    Déposer ici →<br />racine du groupe
                  </div>
                ) : null}
              </div>
            )}
          </>
        )}
      </div>
    </>
  );
}

// ─── Barre de dépôt fine (réordonner / re-parenter) ──────────────

function DropBar({
  targetId,
  dnd,
  vertical
}: {
  targetId: number;
  dnd: Dnd;
  vertical?: boolean;
}) {
  if (dnd.dragId == null) return null;
  if (dnd.draggedSubtree.has(targetId)) {
    // Place-holder neutre : garde l'espacement sans être droppable.
    return <div className={vertical ? "w-1 shrink-0" : "h-1.5"} />;
  }
  const active =
    dnd.dropTarget?.id === targetId && dnd.dropTarget.mode === "before";
  return (
    <div
      onDragOver={(e) => {
        e.preventDefault();
        e.stopPropagation();
        if (!active) dnd.onHover({ id: targetId, mode: "before" });
      }}
      onDrop={(e) => {
        e.preventDefault();
        e.stopPropagation();
        dnd.onDrop();
      }}
      className={vertical ? "w-2 shrink-0" : "h-2"}
      style={{
        backgroundColor: active ? "var(--qg-accent)" : "transparent",
        borderRadius: 4
      }}
    />
  );
}

// ─── Une colonne = une branche top-level + son arbre ─────────────

function ColumnView({
  node,
  byParent,
  allNodes,
  entreprises,
  employes,
  parentEntId,
  dnd,
  onCreate,
  onPatch,
  onDelete
}: {
  node: OrgNode;
  byParent: Map<number | null, OrgNode[]>;
  allNodes: OrgNode[];
  entreprises: Array<{ id: number; name: string }>;
  employes: Employe[];
  parentEntId: number | null;
  dnd: Dnd;
  onCreate: (
    parent_id: number | null,
    label: string,
    kind?: string
  ) => Promise<OrgNode | undefined>;
  onPatch: (id: number, patch: Partial<OrgNode>) => Promise<void>;
  onDelete: (id: number) => Promise<void>;
}) {
  // La colonne entière est une grande cible de dépôt « dans cette
  // entreprise » : déposer n'importe où dans la carte (hors d'un
  // sous-nœud précis, qui lui stoppe la propagation) re-parente le
  // nœud glissé sous la racine de la colonne. Rend le glisser-déposer
  // d'une entreprise vers une autre beaucoup plus facile.
  const colDroppable =
    dnd.dragId != null && !dnd.draggedSubtree.has(node.id);
  const isColTarget =
    dnd.dropTarget?.id === node.id && dnd.dropTarget.mode === "into";

  return (
    <div
      onDragOver={(e) => {
        if (!colDroppable) return;
        e.preventDefault();
        if (!isColTarget) dnd.onHover({ id: node.id, mode: "into" });
      }}
      onDrop={(e) => {
        if (!colDroppable) return;
        e.preventDefault();
        dnd.onDrop();
      }}
      className="w-[300px] shrink-0 rounded-xl border p-3 transition"
      style={{
        borderColor: isColTarget ? "var(--qg-accent)" : "var(--qg-border)",
        backgroundColor: "var(--qg-card-bg)",
        boxShadow: isColTarget
          ? "0 0 0 2px var(--qg-accent) inset"
          : "none"
      }}
    >
      <NodeRow
        node={node}
        allNodes={allNodes}
        entreprises={entreprises}
        employes={employes}
        parentEntId={parentEntId}
        dnd={dnd}
        onCreate={onCreate}
        onPatch={onPatch}
        onDelete={onDelete}
        depth={0}
      />
      <Children
        parentId={node.id}
        byParent={byParent}
        allNodes={allNodes}
        entreprises={entreprises}
        employes={employes}
        parentEntId={parentEntId}
        dnd={dnd}
        onCreate={onCreate}
        onPatch={onPatch}
        onDelete={onDelete}
        depth={1}
      />
    </div>
  );
}

function Children({
  parentId,
  byParent,
  allNodes,
  entreprises,
  employes,
  parentEntId,
  dnd,
  onCreate,
  onPatch,
  onDelete,
  depth
}: {
  parentId: number;
  byParent: Map<number | null, OrgNode[]>;
  allNodes: OrgNode[];
  entreprises: Array<{ id: number; name: string }>;
  employes: Employe[];
  parentEntId: number | null;
  dnd: Dnd;
  onCreate: (
    parent_id: number | null,
    label: string,
    kind?: string
  ) => Promise<OrgNode | undefined>;
  onPatch: (id: number, patch: Partial<OrgNode>) => Promise<void>;
  onDelete: (id: number) => Promise<void>;
  depth: number;
}) {
  const children = byParent.get(parentId) || [];
  const [adding, setAdding] = useState(false);
  const [newLabel, setNewLabel] = useState("");
  const defaultKind = depth >= 2 ? "task" : "role";

  async function submitChild() {
    if (!newLabel.trim()) return;
    await onCreate(parentId, newLabel, defaultKind);
    setNewLabel("");
    setAdding(false);
  }

  return (
    <div
      className="mt-2 space-y-1.5"
      style={{
        paddingLeft: depth > 0 ? "0.75rem" : 0,
        borderLeft:
          depth > 0 ? `2px solid var(--qg-border-soft)` : "none"
      }}
    >
      {children.map((c) => (
        <div key={c.id}>
          <DropBar targetId={c.id} dnd={dnd} />
          <NodeRow
            node={c}
            allNodes={allNodes}
            entreprises={entreprises}
            employes={employes}
            parentEntId={parentEntId}
            dnd={dnd}
            onCreate={onCreate}
            onPatch={onPatch}
            onDelete={onDelete}
            depth={depth}
          />
          <Children
            parentId={c.id}
            byParent={byParent}
            allNodes={allNodes}
            entreprises={entreprises}
            employes={employes}
            parentEntId={parentEntId}
            dnd={dnd}
            onCreate={onCreate}
            onPatch={onPatch}
            onDelete={onDelete}
            depth={depth + 1}
          />
        </div>
      ))}
      {adding ? (
        <div className="flex items-center gap-1">
          <input
            autoFocus
            value={newLabel}
            onChange={(e) => setNewLabel(e.target.value)}
            placeholder={
              defaultKind === "task"
                ? "Nouvelle tâche…"
                : "Nouveau rôle / sous-département…"
            }
            onKeyDown={(e) => {
              if (e.key === "Enter") void submitChild();
              else if (e.key === "Escape") {
                setAdding(false);
                setNewLabel("");
              }
            }}
            onBlur={() => {
              if (!newLabel.trim()) setAdding(false);
            }}
            className="input flex-1 text-[11px]"
          />
          <button
            type="button"
            onClick={() => void submitChild()}
            className="rounded p-1 text-accent-400 hover:bg-accent-500/10"
          >
            <Plus className="h-3 w-3" />
          </button>
        </div>
      ) : (
        <button
          type="button"
          onClick={() => setAdding(true)}
          className="inline-flex items-center gap-1 rounded px-1 py-0.5 text-[10px] text-white/40 hover:text-accent-400"
        >
          <Plus className="h-2.5 w-2.5" />
          Ajouter sous-élément
        </button>
      )}
    </div>
  );
}

type RoleSuggestion = {
  label: string;
  kind: string;
  description: string | null;
};

function NodeRow({
  node,
  allNodes,
  entreprises,
  employes,
  parentEntId,
  dnd,
  onCreate,
  onPatch,
  onDelete,
  depth
}: {
  node: OrgNode;
  allNodes: OrgNode[];
  entreprises: Array<{ id: number; name: string }>;
  employes: Employe[];
  parentEntId: number | null;
  dnd: Dnd;
  onCreate: (
    parent_id: number | null,
    label: string,
    kind?: string
  ) => Promise<OrgNode | undefined>;
  onPatch: (id: number, patch: Partial<OrgNode>) => Promise<void>;
  onDelete: (id: number) => Promise<void>;
  depth: number;
}) {
  const [editing, setEditing] = useState(false);
  const [label, setLabel] = useState(node.label);
  const [extName, setExtName] = useState(node.assignee_external_name || "");
  // Toute la carte est saisissable pour le drag — SAUF quand on est en
  // train d'éditer le libellé (sinon on ne pourrait plus sélectionner
  // le texte du champ).
  const [labelFocused, setLabelFocused] = useState(false);

  // Suggestions de rôles manquants (bouton « Générer » sur les
  // nœuds entreprise).
  const [suggesting, setSuggesting] = useState(false);
  const [suggestions, setSuggestions] = useState<RoleSuggestion[] | null>(
    null
  );
  const [suggestError, setSuggestError] = useState<string | null>(null);
  const [addedSuggestions, setAddedSuggestions] = useState<Set<string>>(
    new Set()
  );

  async function generateRoles() {
    setSuggesting(true);
    setSuggestError(null);
    try {
      const r = await authedFetch(
        `/api/v1/org-nodes/${node.id}/suggest-roles`,
        { method: "POST" }
      );
      if (!r.ok) {
        const txt = await r.text();
        throw new Error(txt.slice(0, 160) || `HTTP ${r.status}`);
      }
      setSuggestions((await r.json()) as RoleSuggestion[]);
      setAddedSuggestions(new Set());
    } catch (e) {
      setSuggestError((e as Error).message);
      setSuggestions([]);
    } finally {
      setSuggesting(false);
    }
  }

  async function addSuggestion(s: RoleSuggestion) {
    setAddedSuggestions((prev) => new Set(prev).add(s.label));
    await onCreate(node.id, s.label, s.kind);
  }

  useEffect(() => {
    setLabel(node.label);
    setExtName(node.assignee_external_name || "");
  }, [node.label, node.assignee_external_name]);

  const kindInfo = KIND_LABELS[node.kind] || KIND_LABELS.role;
  const assigneeEmploye = node.assignee_employe_id
    ? employes.find((e) => e.id === node.assignee_employe_id)
    : null;
  const entreprise = node.entreprise_id
    ? entreprises.find((e) => e.id === node.entreprise_id)
    : null;

  // Entreprise mère du groupe — mise en évidence dans l'arbre.
  const isParentCompany =
    node.kind === "company" &&
    parentEntId != null &&
    node.entreprise_id === parentEntId;

  // Co-détenteurs : on résout les IDs en libellés pour les badges,
  // et on prépare les options du sélecteur multiple.
  const coOwnerIds = node.co_owner_node_ids || [];
  const coOwnerNodes = coOwnerIds
    .map((id) => allNodes.find((n) => n.id === id))
    .filter((n): n is OrgNode => Boolean(n));
  const companyOptions = allNodes
    .filter((n) => n.kind === "company" && n.id !== node.id)
    .map((n) => ({ id: n.id, label: n.label }));

  const isDragging = dnd.dragId === node.id;
  const isIntoTarget =
    dnd.dropTarget?.id === node.id && dnd.dropTarget.mode === "into";
  const droppable =
    dnd.dragId != null && !dnd.draggedSubtree.has(node.id);

  return (
    <div
      draggable={!labelFocused}
      onDragStart={(e) => {
        e.dataTransfer.effectAllowed = "move";
        e.dataTransfer.setData("text/plain", String(node.id));
        dnd.onDragStartNode(node.id);
      }}
      onDragEnd={() => dnd.onDragEndNode()}
      onDragOver={(e) => {
        if (!droppable) return;
        e.preventDefault();
        e.stopPropagation();
        if (!isIntoTarget) dnd.onHover({ id: node.id, mode: "into" });
      }}
      onDrop={(e) => {
        if (!droppable) return;
        e.preventDefault();
        e.stopPropagation();
        dnd.onDrop();
      }}
      className={`rounded-md border px-2 py-1.5 transition ${
        labelFocused ? "" : "cursor-grab active:cursor-grabbing"
      }`}
      style={{
        borderColor: isIntoTarget
          ? "var(--qg-accent)"
          : isParentCompany
            ? "var(--qg-accent)"
            : "var(--qg-border-soft)",
        backgroundColor: isIntoTarget
          ? "var(--qg-bg-alt)"
          : "var(--qg-bg-alt, transparent)",
        boxShadow: isIntoTarget
          ? "0 0 0 1px var(--qg-accent) inset"
          : "none",
        opacity: isDragging ? 0.4 : 1,
        fontSize: depth === 0 ? "13px" : "12px"
      }}
    >
      <div className="flex items-start gap-1.5">
        <span
          aria-hidden
          title="Glisser pour déplacer / re-parenter"
          className="mt-0.5 text-white/30"
        >
          {isParentCompany ? (
            <Star className="h-3.5 w-3.5 text-accent-400" />
          ) : (
            <GripVertical className="h-3.5 w-3.5" />
          )}
        </span>
        <span
          className={`mt-0.5 rounded-full border px-1.5 py-0 text-[9px] font-bold uppercase ${kindInfo.cls}`}
        >
          {kindInfo.label}
        </span>
        <input
          value={label}
          draggable={false}
          onFocus={() => setLabelFocused(true)}
          onChange={(e) => setLabel(e.target.value)}
          onBlur={() => {
            setLabelFocused(false);
            if (label.trim() && label !== node.label) {
              void onPatch(node.id, { label: label.trim() });
            }
          }}
          className="flex-1 bg-transparent text-sm font-semibold focus:outline-none"
          style={{ color: "var(--qg-text)" }}
        />
        {node.kind === "company" ? (
          <button
            type="button"
            onClick={() => void generateRoles()}
            disabled={suggesting}
            className="inline-flex items-center gap-1 rounded px-1 py-0.5 text-[10px] font-semibold text-accent-300 hover:bg-accent-500/10 disabled:opacity-50"
            title="Générer les rôles / tâches manquants selon le but de cette entreprise"
          >
            {suggesting ? (
              <Loader2 className="h-3 w-3 animate-spin" />
            ) : (
              <Sparkles className="h-3 w-3" />
            )}
            Générer
          </button>
        ) : null}
        <button
          type="button"
          onClick={() => setEditing((v) => !v)}
          className="rounded p-0.5 text-white/40 hover:text-accent-400"
          title="Plus d'options"
        >
          {editing ? (
            <ChevronDown className="h-3 w-3" />
          ) : (
            <ChevronRight className="h-3 w-3" />
          )}
        </button>
        <button
          type="button"
          onClick={() => void onDelete(node.id)}
          className="rounded p-0.5 text-white/40 hover:bg-rose-500/15 hover:text-rose-300"
          title="Supprimer"
        >
          <Trash2 className="h-3 w-3" />
        </button>
      </div>

      {/* Badges info compacts */}
      <div className="mt-1 flex flex-wrap items-center gap-1 text-[10px]">
        {isParentCompany ? (
          <span
            className="inline-flex items-center gap-0.5 rounded px-1 py-0 font-semibold"
            style={{
              backgroundColor: "var(--qg-accent)",
              color: "var(--qg-accent-ink, #0a0a0b)"
            }}
            title="Entreprise mère du groupe"
          >
            <Star className="h-2.5 w-2.5" />
            Entreprise mère
          </span>
        ) : null}
        {entreprise ? (
          <span
            className="inline-flex items-center gap-0.5 rounded px-1 py-0"
            style={{
              backgroundColor: "var(--qg-bg-alt)",
              color: "var(--qg-text-muted)"
            }}
            title="Entreprise liée"
          >
            <Building2 className="h-2.5 w-2.5" />
            {entreprise.name}
          </span>
        ) : null}
        {assigneeEmploye ? (
          <span
            className="inline-flex items-center gap-0.5 rounded bg-accent-500/10 px-1 py-0 text-accent-300"
            title="Employé responsable"
          >
            <UserIcon className="h-2.5 w-2.5" />
            {assigneeEmploye.full_name}
          </span>
        ) : node.assignee_external_name ? (
          <span
            className="inline-flex items-center gap-0.5 rounded bg-violet-500/10 px-1 py-0 text-violet-300"
            title="Externe (freelance / sous-traitant / partenaire)"
          >
            <Briefcase className="h-2.5 w-2.5" />
            {node.assignee_external_name}
          </span>
        ) : null}
        {coOwnerNodes.length > 0 ? (
          <span
            className="inline-flex items-center gap-0.5 rounded bg-sky-500/10 px-1 py-0 text-sky-300"
            title="Détenu aussi par ces entreprises (co-détention)"
          >
            <Link2 className="h-2.5 w-2.5" />
            aussi détenu par {coOwnerNodes.map((n) => n.label).join(", ")}
          </span>
        ) : null}
      </div>

      {/* Suggestions de rôles manquants (IA) */}
      {suggestions !== null || suggestError ? (
        <div
          className="mt-2 rounded border p-2 text-[11px]"
          style={{
            borderColor: "var(--qg-border-soft)",
            backgroundColor: "var(--qg-card-bg)"
          }}
        >
          <div className="flex items-center justify-between">
            <span
              className="inline-flex items-center gap-1 font-semibold"
              style={{ color: "var(--qg-text)" }}
            >
              <Sparkles className="h-3 w-3 text-accent-400" />
              Rôles / tâches suggérés
            </span>
            <div className="flex items-center gap-1">
              <button
                type="button"
                onClick={() => void generateRoles()}
                disabled={suggesting}
                className="rounded px-1 py-0.5 text-[10px] text-accent-300 hover:bg-accent-500/10 disabled:opacity-50"
              >
                Régénérer
              </button>
              <button
                type="button"
                onClick={() => {
                  setSuggestions(null);
                  setSuggestError(null);
                }}
                className="rounded p-0.5 text-white/40 hover:text-rose-300"
                aria-label="Fermer les suggestions"
              >
                <Trash2 className="h-3 w-3" />
              </button>
            </div>
          </div>

          {suggestError ? (
            <p className="mt-1 text-[10px] text-rose-300">{suggestError}</p>
          ) : null}

          {suggestions && suggestions.length === 0 && !suggestError ? (
            <p
              className="mt-1 text-[10px]"
              style={{ color: "var(--qg-text-soft)" }}
            >
              Rien de neuf à suggérer — la structure semble déjà couverte.
            </p>
          ) : null}

          <div className="mt-1.5 space-y-1">
            {(suggestions || []).map((s) => {
              const added = addedSuggestions.has(s.label);
              const sKind = KIND_LABELS[s.kind] || KIND_LABELS.role;
              return (
                <div
                  key={s.label}
                  className="flex items-start gap-1.5 rounded px-1 py-1"
                  style={{ backgroundColor: "var(--qg-bg-alt, transparent)" }}
                >
                  <span
                    className={`mt-0.5 rounded-full border px-1 py-0 text-[8px] font-bold uppercase ${sKind.cls}`}
                  >
                    {sKind.label}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span
                      className="block font-semibold"
                      style={{ color: "var(--qg-text)" }}
                    >
                      {s.label}
                    </span>
                    {s.description ? (
                      <span
                        className="block text-[10px]"
                        style={{ color: "var(--qg-text-soft)" }}
                      >
                        {s.description}
                      </span>
                    ) : null}
                  </span>
                  <button
                    type="button"
                    onClick={() => void addSuggestion(s)}
                    disabled={added}
                    className="mt-0.5 inline-flex shrink-0 items-center gap-0.5 rounded px-1 py-0.5 text-[10px] font-semibold text-accent-300 hover:bg-accent-500/10 disabled:opacity-40"
                  >
                    <Plus className="h-2.5 w-2.5" />
                    {added ? "Ajouté" : "Ajouter"}
                  </button>
                </div>
              );
            })}
          </div>
        </div>
      ) : null}

      {/* Bloc édition étendu */}
      {editing ? (
        <div
          className="mt-2 space-y-2 rounded border p-2 text-[11px]"
          style={{
            borderColor: "var(--qg-border-soft)",
            backgroundColor: "var(--qg-card-bg)"
          }}
        >
          <div className="grid grid-cols-2 gap-2">
            <div>
              <label className="text-[9px] uppercase text-white/40">
                Type
              </label>
              <select
                value={node.kind}
                onChange={(e) =>
                  void onPatch(node.id, { kind: e.target.value })
                }
                className="input mt-0.5 text-[11px]"
              >
                <option value="company">Entreprise</option>
                <option value="dept">Département</option>
                <option value="role">Rôle</option>
                <option value="task">Tâche</option>
                <option value="service">Service partagé</option>
              </select>
            </div>
            <div>
              <label className="text-[9px] uppercase text-white/40">
                Entreprise liée
              </label>
              <select
                value={node.entreprise_id ? String(node.entreprise_id) : ""}
                onChange={(e) =>
                  void onPatch(node.id, {
                    entreprise_id: e.target.value
                      ? Number(e.target.value)
                      : null
                  })
                }
                className="input mt-0.5 text-[11px]"
              >
                <option value="">Transverse (groupe)</option>
                {entreprises.map((ent) => (
                  <option key={ent.id} value={String(ent.id)}>
                    {ent.name}
                  </option>
                ))}
              </select>
            </div>
          </div>

          {/* Co-détenteurs — une entreprise peut être détenue par
              plusieurs. Le parent dans l'arbre = détenteur principal ;
              ici on liste les co-détenteurs (affichés en badge). */}
          <div>
            <label className="text-[9px] uppercase text-white/40">
              Co-détenteurs (en plus du parent dans l&apos;arbre)
            </label>
            <div className="mt-0.5">
              <MultiSelectDropdown
                options={companyOptions}
                selectedIds={coOwnerIds}
                onChange={(ids) =>
                  void onPatch(node.id, { co_owner_node_ids: ids })
                }
                placeholder="— Aucun co-détenteur —"
                emptyLabel="Aucune autre entreprise dans l'organigramme"
              />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-2">
            <div>
              <label className="text-[9px] uppercase text-white/40">
                Employé responsable
              </label>
              <select
                value={
                  node.assignee_employe_id
                    ? String(node.assignee_employe_id)
                    : ""
                }
                onChange={(e) =>
                  void onPatch(node.id, {
                    assignee_employe_id: e.target.value
                      ? Number(e.target.value)
                      : null,
                    // si on assigne un employé interne, on retire
                    // l'externe pour ne pas mélanger.
                    assignee_external_name: e.target.value
                      ? null
                      : node.assignee_external_name
                  })
                }
                className="input mt-0.5 text-[11px]"
              >
                <option value="">— Aucun —</option>
                {employes.map((emp) => (
                  <option key={emp.id} value={String(emp.id)}>
                    {emp.full_name}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="text-[9px] uppercase text-white/40">
                OU externe (freelance, partenaire)
              </label>
              <input
                value={extName}
                onChange={(e) => setExtName(e.target.value)}
                onBlur={() => {
                  if (extName !== (node.assignee_external_name || "")) {
                    void onPatch(node.id, {
                      assignee_external_name: extName.trim() || null,
                      assignee_employe_id: extName.trim()
                        ? null
                        : node.assignee_employe_id
                    });
                  }
                }}
                placeholder="Ex. Freelance, sous-traitant XYZ"
                className="input mt-0.5 text-[11px]"
              />
            </div>
          </div>

          <div>
            <label className="text-[9px] uppercase text-white/40">
              Description / notes
            </label>
            <textarea
              defaultValue={node.description || ""}
              onBlur={(e) => {
                if (e.target.value !== (node.description || "")) {
                  void onPatch(node.id, {
                    description: e.target.value.trim() || null
                  });
                }
              }}
              rows={2}
              className="input mt-0.5 text-[11px]"
              placeholder="Notes, responsabilités, KPIs..."
            />
          </div>
        </div>
      ) : null}
    </div>
  );
}
