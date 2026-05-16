"use client";

import { useMemo, useState } from "react";
import { Loader2, Search, Trash2, UserPlus2, X } from "lucide-react";

import { TargetPicker, type TargetPickerOption } from "@/components/target-picker";

// Vue « Rôles & responsabilités » de l'organigramme.
//
// Idée : le seed canonique mélange dans un seul arbre les entreprises,
// les départements, les rôles et les « tâches » (qui sont en réalité
// les responsabilités d'un rôle, pas des to-do). Cette vue extrait les
// rôles dans un tableau matriciel scannable + sidebar de détail :
//
//   - Tableau : 1 ligne = 1 rôle, colonnes pôle | titulaire | tier |
//     # responsabilités. Filtres pôle / statut / tier.
//   - Sidebar : description du rôle, titulaire (autocomplete), tier,
//     liste des responsabilités (les ex-tâches enfants), co-détenteurs.
//
// On ne migre PAS les données — on les réinterprète. Les « tâches » du
// seed (kind="task") restent des OrgNodes enfants du rôle, et c'est
// l'UI qui les présente comme « responsabilités » du rôle parent.

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
  pos_x: number | null;
  pos_y: number | null;
  execution_tier: string | null;
  created_at: string;
  updated_at: string;
};

type Employe = { id: number; full_name: string };

const TIER_LABEL: Record<string, string> = {
  direction: "Direction",
  adjoint: "Adjoint",
  adjoint_virtuel: "Adjoint virtuel (IA)"
};

const TIER_CLS: Record<string, string> = {
  direction: "bg-rose-500/15 text-rose-300",
  adjoint: "bg-blue-500/15 text-blue-300",
  adjoint_virtuel: "bg-emerald-500/15 text-emerald-300"
};

type Filter = {
  pole: string | "all";
  status: "all" | "filled" | "vacant";
  tier: string | "all";
  query: string;
};

export function RolesResponsibilitiesView({
  nodes,
  employes,
  onPatch,
  onDelete,
  onCreate
}: {
  nodes: OrgNode[];
  employes: Employe[];
  onPatch: (id: number, patch: Partial<OrgNode>) => void;
  onDelete: (id: number) => void;
  onCreate: (
    parentId: number | null,
    label: string,
    kind: string
  ) => Promise<OrgNode | null> | void;
}) {
  const [filter, setFilter] = useState<Filter>({
    pole: "all",
    status: "all",
    tier: "all",
    query: ""
  });
  const [selectedId, setSelectedId] = useState<number | null>(null);

  // Index parent → children pour reconstituer les responsabilités d'un
  // rôle (= enfants kind="task" du rôle).
  const childrenOf = useMemo(() => {
    const m = new Map<number, OrgNode[]>();
    for (const n of nodes) {
      if (n.parent_id == null) continue;
      const arr = m.get(n.parent_id) || [];
      arr.push(n);
      m.set(n.parent_id, arr);
    }
    for (const arr of m.values())
      arr.sort((a, b) => a.position - b.position);
    return m;
  }, [nodes]);

  // Index id → noeud (pour remonter de rôle → pôle).
  const byId = useMemo(() => {
    const m = new Map<number, OrgNode>();
    for (const n of nodes) m.set(n.id, n);
    return m;
  }, [nodes]);

  // Pour chaque rôle, retrouve le pôle (1er ancêtre de kind="dept").
  function findPole(node: OrgNode): OrgNode | null {
    let cur: OrgNode | null = node;
    let depth = 0;
    while (cur && depth < 10) {
      if (cur.kind === "dept") return cur;
      cur = cur.parent_id != null ? byId.get(cur.parent_id) || null : null;
      depth++;
    }
    return null;
  }

  const roles = useMemo(
    () => nodes.filter((n) => n.kind === "role"),
    [nodes]
  );

  const poles = useMemo(() => {
    const set = new Map<number, OrgNode>();
    for (const r of roles) {
      const p = findPole(r);
      if (p) set.set(p.id, p);
    }
    return Array.from(set.values()).sort((a, b) =>
      a.label.localeCompare(b.label)
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [roles, byId]);

  const employeesById = useMemo(() => {
    const m = new Map<number, Employe>();
    for (const e of employes) m.set(e.id, e);
    return m;
  }, [employes]);

  function assigneeLabel(n: OrgNode): string {
    if (n.assignee_employe_id) {
      const e = employeesById.get(n.assignee_employe_id);
      return e ? e.full_name : `Employé #${n.assignee_employe_id}`;
    }
    if (n.assignee_external_name) return n.assignee_external_name;
    if (n.assignee_user_id) return `User #${n.assignee_user_id}`;
    return "";
  }

  // Charge de chaque employé (nombre de rôles tenus) — indicateur de
  // surcharge dans la sidebar.
  const roleCountByEmploye = useMemo(() => {
    const m = new Map<number, number>();
    for (const r of roles) {
      if (r.assignee_employe_id != null) {
        m.set(
          r.assignee_employe_id,
          (m.get(r.assignee_employe_id) || 0) + 1
        );
      }
    }
    return m;
  }, [roles]);

  const filteredRoles = useMemo(() => {
    const norm = (s: string) =>
      s.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
    const q = norm(filter.query.trim());
    return roles.filter((r) => {
      const pole = findPole(r);
      if (filter.pole !== "all" && String(pole?.id) !== filter.pole)
        return false;
      const isFilled =
        r.assignee_employe_id != null ||
        r.assignee_user_id != null ||
        (r.assignee_external_name && r.assignee_external_name.trim() !== "");
      if (filter.status === "filled" && !isFilled) return false;
      if (filter.status === "vacant" && isFilled) return false;
      if (filter.tier !== "all" && (r.execution_tier || "") !== filter.tier)
        return false;
      if (q) {
        const blob = `${r.label} ${assigneeLabel(r)} ${pole?.label || ""}`;
        if (!norm(blob).includes(q)) return false;
      }
      return true;
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [roles, filter, byId, employeesById]);

  const selected = selectedId != null ? byId.get(selectedId) || null : null;

  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1fr_22rem]">
      {/* Colonne gauche : filtres + tableau */}
      <div className="min-w-0">
        <Filters
          filter={filter}
          setFilter={setFilter}
          poles={poles}
          totalRoles={roles.length}
          shown={filteredRoles.length}
        />

        <div
          className="mt-3 overflow-hidden rounded-2xl border"
          style={{
            borderColor: "var(--qg-border)",
            backgroundColor: "var(--qg-card-bg)"
          }}
        >
          {filteredRoles.length === 0 ? (
            <p
              className="px-4 py-8 text-center text-sm"
              style={{ color: "var(--qg-text-muted)" }}
            >
              Aucun rôle ne correspond aux filtres.
            </p>
          ) : (
            <table className="w-full text-sm">
              <thead
                className="text-left text-[10px] uppercase tracking-wider"
                style={{
                  color: "var(--qg-text-soft)",
                  backgroundColor: "var(--qg-card-bg-hover, transparent)"
                }}
              >
                <tr className="border-b" style={{ borderColor: "var(--qg-border)" }}>
                  <th className="px-3 py-2">Rôle</th>
                  <th className="px-3 py-2">Pôle</th>
                  <th className="px-3 py-2">Titulaire</th>
                  <th className="px-3 py-2">Tier</th>
                  <th className="px-3 py-2 text-right">Resp.</th>
                </tr>
              </thead>
              <tbody>
                {filteredRoles.map((r) => {
                  const pole = findPole(r);
                  const respCount = (childrenOf.get(r.id) || []).filter(
                    (c) => c.kind === "task"
                  ).length;
                  const a = assigneeLabel(r);
                  const isVacant = !a;
                  const isActive = r.id === selectedId;
                  return (
                    <tr
                      key={r.id}
                      onClick={() => setSelectedId(r.id)}
                      className={`cursor-pointer border-b transition ${
                        isActive
                          ? "bg-accent-500/10"
                          : "hover:bg-white/[0.03]"
                      }`}
                      style={{ borderColor: "var(--qg-border-soft)" }}
                    >
                      <td className="px-3 py-2 font-semibold text-white">
                        {r.label}
                      </td>
                      <td
                        className="px-3 py-2 text-xs"
                        style={{ color: "var(--qg-text-soft)" }}
                      >
                        {pole?.label || "—"}
                      </td>
                      <td className="px-3 py-2">
                        {isVacant ? (
                          <span className="inline-flex items-center gap-1 rounded bg-amber-500/15 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-amber-300">
                            🪑 À pourvoir
                          </span>
                        ) : (
                          <span className="text-xs text-white/90">{a}</span>
                        )}
                      </td>
                      <td className="px-3 py-2">
                        {r.execution_tier ? (
                          <span
                            className={`rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${
                              TIER_CLS[r.execution_tier] ||
                              "bg-white/10 text-white/60"
                            }`}
                          >
                            {TIER_LABEL[r.execution_tier] || r.execution_tier}
                          </span>
                        ) : (
                          <span className="text-[10px] text-white/30">—</span>
                        )}
                      </td>
                      <td className="px-3 py-2 text-right text-xs text-white/60">
                        {respCount}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>
      </div>

      {/* Colonne droite : sidebar de détail */}
      <aside
        className="rounded-2xl border p-4"
        style={{
          borderColor: "var(--qg-border)",
          backgroundColor: "var(--qg-card-bg)"
        }}
      >
        {selected ? (
          <RoleDetail
            role={selected}
            pole={findPole(selected)}
            responsibilities={(childrenOf.get(selected.id) || []).filter(
              (c) => c.kind === "task"
            )}
            employes={employes}
            roleCountByEmploye={roleCountByEmploye}
            onPatch={onPatch}
            onDelete={onDelete}
            onCreate={onCreate}
            onClose={() => setSelectedId(null)}
          />
        ) : (
          <div className="flex h-full min-h-[280px] flex-col items-center justify-center text-center">
            <UserPlus2
              className="mb-2 h-8 w-8"
              style={{ color: "var(--qg-text-muted)" }}
            />
            <p className="text-sm" style={{ color: "var(--qg-text-soft)" }}>
              Sélectionne un rôle pour voir sa description, son
              titulaire et ses responsabilités.
            </p>
          </div>
        )}
      </aside>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────

function Filters({
  filter,
  setFilter,
  poles,
  totalRoles,
  shown
}: {
  filter: Filter;
  setFilter: (f: Filter) => void;
  poles: OrgNode[];
  totalRoles: number;
  shown: number;
}) {
  return (
    <div
      className="flex flex-wrap items-center gap-2 rounded-2xl border p-3"
      style={{
        borderColor: "var(--qg-border)",
        backgroundColor: "var(--qg-card-bg)"
      }}
    >
      <div className="relative flex-1 min-w-[180px]">
        <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-white/40" />
        <input
          value={filter.query}
          onChange={(e) => setFilter({ ...filter, query: e.target.value })}
          placeholder="Rechercher rôle, titulaire, pôle…"
          className="input w-full pl-7 text-xs"
        />
      </div>
      <select
        value={filter.pole}
        onChange={(e) => setFilter({ ...filter, pole: e.target.value })}
        className="input w-auto text-xs"
      >
        <option value="all">Tous les pôles</option>
        {poles.map((p) => (
          <option key={p.id} value={String(p.id)}>
            {p.label}
          </option>
        ))}
      </select>
      <select
        value={filter.status}
        onChange={(e) =>
          setFilter({ ...filter, status: e.target.value as Filter["status"] })
        }
        className="input w-auto text-xs"
      >
        <option value="all">Pourvus + vacants</option>
        <option value="filled">Pourvus seulement</option>
        <option value="vacant">À pourvoir seulement</option>
      </select>
      <select
        value={filter.tier}
        onChange={(e) => setFilter({ ...filter, tier: e.target.value })}
        className="input w-auto text-xs"
      >
        <option value="all">Tous les tiers</option>
        <option value="direction">Direction</option>
        <option value="adjoint">Adjoint</option>
        <option value="adjoint_virtuel">Adjoint virtuel (IA)</option>
      </select>
      <span className="ml-auto text-[11px]" style={{ color: "var(--qg-text-soft)" }}>
        {shown} / {totalRoles} rôles
      </span>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────

function RoleDetail({
  role,
  pole,
  responsibilities,
  employes,
  roleCountByEmploye,
  onPatch,
  onDelete,
  onCreate,
  onClose
}: {
  role: OrgNode;
  pole: OrgNode | null;
  responsibilities: OrgNode[];
  employes: Employe[];
  roleCountByEmploye: Map<number, number>;
  onPatch: (id: number, patch: Partial<OrgNode>) => void;
  onDelete: (id: number) => void;
  onCreate: (
    parentId: number | null,
    label: string,
    kind: string
  ) => Promise<OrgNode | null> | void;
  onClose: () => void;
}) {
  const assigneeOptions = useMemo<TargetPickerOption[]>(
    () =>
      employes.map((e) => ({
        value: `employe:${e.id}`,
        label: e.full_name,
        sub: (roleCountByEmploye.get(e.id) || 0) > 0
          ? `${roleCountByEmploye.get(e.id)} rôle(s) déjà tenu(s)`
          : null,
        kind: "client" as const
      })),
    [employes, roleCountByEmploye]
  );

  const currentValue =
    role.assignee_employe_id != null
      ? `employe:${role.assignee_employe_id}`
      : "";

  function setAssignee(val: string) {
    if (!val) {
      onPatch(role.id, {
        assignee_employe_id: null,
        assignee_user_id: null,
        assignee_external_name: null
      });
      return;
    }
    if (val.startsWith("employe:")) {
      onPatch(role.id, {
        assignee_employe_id: Number(val.slice("employe:".length)),
        assignee_user_id: null,
        assignee_external_name: null
      });
    }
  }

  const [externalInput, setExternalInput] = useState(
    role.assignee_external_name || ""
  );
  const [newRespLabel, setNewRespLabel] = useState("");
  const [adding, setAdding] = useState(false);

  async function addResponsibility() {
    const label = newRespLabel.trim();
    if (!label) return;
    setAdding(true);
    try {
      await onCreate(role.id, label, "task");
      setNewRespLabel("");
    } finally {
      setAdding(false);
    }
  }

  const employeCount = role.assignee_employe_id
    ? roleCountByEmploye.get(role.assignee_employe_id) || 0
    : 0;
  const overloaded = employeCount >= 4;

  return (
    <div className="space-y-4">
      <header className="flex items-start justify-between gap-2 border-b pb-3"
        style={{ borderColor: "var(--qg-border-soft)" }}>
        <div className="min-w-0 flex-1">
          <p className="text-[10px] uppercase tracking-wider" style={{ color: "var(--qg-text-soft)" }}>
            {pole?.label || "Sans pôle"}
          </p>
          <input
            value={role.label}
            onChange={(e) => onPatch(role.id, { label: e.target.value })}
            onBlur={(e) => onPatch(role.id, { label: e.target.value.trim() })}
            className="mt-1 w-full rounded border border-transparent bg-transparent px-1 py-0.5 text-base font-bold text-white hover:border-white/10 focus:border-accent-500/50 focus:outline-none"
          />
        </div>
        <button
          type="button"
          onClick={onClose}
          className="rounded p-1 text-white/40 hover:bg-white/5 hover:text-white"
          aria-label="Fermer le panneau"
        >
          <X className="h-4 w-4" />
        </button>
      </header>

      {/* Titulaire */}
      <section>
        <label className="mb-1 block text-[11px] font-semibold uppercase tracking-wider" style={{ color: "var(--qg-text-soft)" }}>
          Titulaire (employé interne)
        </label>
        <TargetPicker
          options={assigneeOptions}
          value={currentValue}
          onChange={setAssignee}
          placeholder="Chercher un employé…"
          emptyMessage="Aucun employé. Tu peux saisir un nom externe ci-dessous."
        />
        {overloaded ? (
          <p className="mt-1 text-[11px] text-amber-300">
            ⚠ {employeCount} rôles déjà tenus par cette personne — risque de surcharge.
          </p>
        ) : null}
        <div className="mt-2 flex items-center gap-2">
          <input
            value={externalInput}
            onChange={(e) => setExternalInput(e.target.value)}
            onBlur={() =>
              onPatch(role.id, {
                assignee_external_name: externalInput.trim() || null,
                ...(externalInput.trim()
                  ? { assignee_employe_id: null, assignee_user_id: null }
                  : {})
              })
            }
            placeholder="ou ressource externe (ex. Freelance Phil, Sous-traitant XYZ)"
            className="input flex-1 text-xs"
          />
        </div>
      </section>

      {/* Tier */}
      <section>
        <label className="mb-1 block text-[11px] font-semibold uppercase tracking-wider" style={{ color: "var(--qg-text-soft)" }}>
          Tier d&apos;exécution
        </label>
        <select
          value={role.execution_tier || ""}
          onChange={(e) =>
            onPatch(role.id, { execution_tier: e.target.value || null })
          }
          className="input w-full text-xs"
        >
          <option value="">— non défini —</option>
          <option value="direction">Direction</option>
          <option value="adjoint">Adjoint</option>
          <option value="adjoint_virtuel">Adjoint virtuel (IA)</option>
        </select>
      </section>

      {/* Description */}
      <section>
        <label className="mb-1 block text-[11px] font-semibold uppercase tracking-wider" style={{ color: "var(--qg-text-soft)" }}>
          Description / Mission
        </label>
        <textarea
          value={role.description || ""}
          onChange={(e) => onPatch(role.id, { description: e.target.value })}
          rows={3}
          placeholder="Mission du rôle, KPIs, contexte…"
          className="input w-full resize-y text-xs"
        />
      </section>

      {/* Responsabilités */}
      <section>
        <div className="mb-1 flex items-baseline justify-between">
          <label className="text-[11px] font-semibold uppercase tracking-wider" style={{ color: "var(--qg-text-soft)" }}>
            Responsabilités ({responsibilities.length})
          </label>
        </div>
        {responsibilities.length === 0 ? (
          <p className="text-[11px]" style={{ color: "var(--qg-text-muted)" }}>
            Aucune responsabilité documentée.
          </p>
        ) : (
          <ul className="space-y-1">
            {responsibilities.map((r) => (
              <li
                key={r.id}
                className="flex items-start gap-2 rounded border px-2 py-1.5 text-xs"
                style={{
                  borderColor: "var(--qg-border-soft)",
                  backgroundColor: "var(--qg-card-bg-hover, transparent)"
                }}
              >
                <input
                  value={r.label}
                  onChange={(e) => onPatch(r.id, { label: e.target.value })}
                  onBlur={(e) =>
                    onPatch(r.id, { label: e.target.value.trim() })
                  }
                  className="flex-1 rounded border border-transparent bg-transparent px-1 py-0.5 text-white hover:border-white/10 focus:border-accent-500/50 focus:outline-none"
                />
                <button
                  type="button"
                  onClick={() => onDelete(r.id)}
                  className="rounded p-0.5 text-white/30 hover:bg-rose-500/15 hover:text-rose-300"
                  aria-label="Supprimer la responsabilité"
                >
                  <Trash2 className="h-3 w-3" />
                </button>
              </li>
            ))}
          </ul>
        )}
        <div className="mt-2 flex gap-2">
          <input
            value={newRespLabel}
            onChange={(e) => setNewRespLabel(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                void addResponsibility();
              }
            }}
            placeholder="Ajouter une responsabilité (ex. Trouver des leads)"
            className="input flex-1 text-xs"
          />
          <button
            type="button"
            onClick={() => void addResponsibility()}
            disabled={adding || !newRespLabel.trim()}
            className="btn-accent inline-flex items-center gap-1 text-[11px] disabled:opacity-50"
          >
            {adding ? <Loader2 className="h-3 w-3 animate-spin" /> : "+ "}
            Ajouter
          </button>
        </div>
      </section>
    </div>
  );
}
