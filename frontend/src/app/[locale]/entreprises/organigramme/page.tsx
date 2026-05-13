"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Briefcase,
  Building2,
  ChevronDown,
  ChevronRight,
  Loader2,
  Plus,
  Save,
  Trash2,
  User as UserIcon,
  Users
} from "lucide-react";

import { authedFetch } from "@/lib/auth";
import { QGTopbar, useEntreprisesLayout } from "../layout";

/**
 * Page Organigramme — inspirée du schéma papier de Steven.
 *
 * Affiche l'arbre des départements / rôles / services partagés du
 * groupe en colonnes (top-level), avec sous-nœuds en cascade dans
 * chaque colonne. Chaque nœud :
 *  - kind (dept / role / service / task)
 *  - label
 *  - lien optionnel à une entreprise
 *  - assignation (employé interne OU texte externe « Freelance », etc.)
 *
 * MVP scaffold : édition simple (création, label, kind, parent,
 * assignation texte). Vue visuelle plus poussée (drag-and-drop, lignes
 * connectées) à venir dans une PR suivante après que tu auras saisi
 * une première version.
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
  created_at: string;
  updated_at: string;
};

type Employe = { id: number; full_name: string };

const KIND_LABELS: Record<string, { label: string; cls: string }> = {
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

  async function createNode(parent_id: number | null, label: string, kind = "dept") {
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
    if (
      !window.confirm(
        "Supprimer ce nœud et tous ses enfants ?"
      )
    )
      return;
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
        subtitle="Départements, rôles, responsables — internes ou externes"
      />

      <div className="p-4 lg:p-6">
        {error ? (
          <p className="mb-3 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
            {error}
          </p>
        ) : null}

        {loading ? (
          <div className="flex items-center justify-center py-12">
            <Loader2 className="h-6 w-6 animate-spin text-accent-500" />
          </div>
        ) : (
          <>
            {/* Bandeau de création top-level (département / branche) */}
            <form
              onSubmit={submitTop}
              className="mb-5 flex flex-wrap items-center gap-2 rounded-xl border p-3"
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
                className="input flex-1 min-w-[260px] text-sm"
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
            </form>

            {topLevel.length === 0 ? (
              <p
                className="rounded-2xl border border-dashed px-6 py-12 text-center text-sm"
                style={{
                  borderColor: "var(--qg-border-soft)",
                  color: "var(--qg-text-muted)"
                }}
              >
                Aucun nœud d&apos;organigramme. Ajoute une première
                branche ci-dessus (ex. « Construction », « Dev logiciel »,
                « Gestion Immo »).
              </p>
            ) : (
              <div className="grid auto-cols-[minmax(280px,1fr)] grid-flow-col gap-3 overflow-x-auto pb-4">
                {topLevel.map((n) => (
                  <ColumnView
                    key={n.id}
                    node={n}
                    byParent={byParent}
                    entreprises={entreprises}
                    employes={employes}
                    onCreate={createNode}
                    onPatch={patchNode}
                    onDelete={deleteNode}
                  />
                ))}
              </div>
            )}
          </>
        )}
      </div>
    </>
  );
}

// ─── Une colonne = une branche top-level + son arbre ─────────────

function ColumnView({
  node,
  byParent,
  entreprises,
  employes,
  onCreate,
  onPatch,
  onDelete
}: {
  node: OrgNode;
  byParent: Map<number | null, OrgNode[]>;
  entreprises: Array<{ id: number; name: string }>;
  employes: Employe[];
  onCreate: (parent_id: number | null, label: string, kind?: string) => Promise<OrgNode | undefined>;
  onPatch: (id: number, patch: Partial<OrgNode>) => Promise<void>;
  onDelete: (id: number) => Promise<void>;
}) {
  return (
    <div
      className="rounded-xl border p-3"
      style={{
        borderColor: "var(--qg-border)",
        backgroundColor: "var(--qg-card-bg)"
      }}
    >
      <NodeRow
        node={node}
        entreprises={entreprises}
        employes={employes}
        onPatch={onPatch}
        onDelete={onDelete}
        depth={0}
      />
      <Children
        parentId={node.id}
        byParent={byParent}
        entreprises={entreprises}
        employes={employes}
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
  entreprises,
  employes,
  onCreate,
  onPatch,
  onDelete,
  depth
}: {
  parentId: number;
  byParent: Map<number | null, OrgNode[]>;
  entreprises: Array<{ id: number; name: string }>;
  employes: Employe[];
  onCreate: (parent_id: number | null, label: string, kind?: string) => Promise<OrgNode | undefined>;
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
          depth > 0
            ? `2px solid var(--qg-border-soft)`
            : "none"
      }}
    >
      {children.map((c) => (
        <div key={c.id}>
          <NodeRow
            node={c}
            entreprises={entreprises}
            employes={employes}
            onPatch={onPatch}
            onDelete={onDelete}
            depth={depth}
          />
          <Children
            parentId={c.id}
            byParent={byParent}
            entreprises={entreprises}
            employes={employes}
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

function NodeRow({
  node,
  entreprises,
  employes,
  onPatch,
  onDelete,
  depth
}: {
  node: OrgNode;
  entreprises: Array<{ id: number; name: string }>;
  employes: Employe[];
  onPatch: (id: number, patch: Partial<OrgNode>) => Promise<void>;
  onDelete: (id: number) => Promise<void>;
  depth: number;
}) {
  const [editing, setEditing] = useState(false);
  const [label, setLabel] = useState(node.label);
  const [extName, setExtName] = useState(
    node.assignee_external_name || ""
  );

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

  return (
    <div
      className="rounded-md border px-2 py-1.5"
      style={{
        borderColor: "var(--qg-border-soft)",
        backgroundColor: "var(--qg-bg-alt, transparent)",
        fontSize: depth === 0 ? "13px" : "12px"
      }}
    >
      <div className="flex items-start gap-2">
        <span
          className={`rounded-full border px-1.5 py-0 text-[9px] font-bold uppercase ${kindInfo.cls}`}
        >
          {kindInfo.label}
        </span>
        <input
          value={label}
          onChange={(e) => setLabel(e.target.value)}
          onBlur={() => {
            if (label.trim() && label !== node.label) {
              void onPatch(node.id, { label: label.trim() });
            }
          }}
          className="flex-1 bg-transparent text-sm font-semibold focus:outline-none"
          style={{ color: "var(--qg-text)" }}
        />
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
      </div>

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
