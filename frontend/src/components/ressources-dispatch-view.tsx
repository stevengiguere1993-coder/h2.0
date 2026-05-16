"use client";

import { useMemo, useState } from "react";
import {
  AlertTriangle,
  ArrowRight,
  ChevronRight,
  Search,
  UserCheck,
  UserMinus,
  Users
} from "lucide-react";

// Vue « Ressources » — dispatch des rôles par employé.
// Complémentaire de la vue Rôles (qui est centrée rôle → titulaire) :
// ici on regarde l'autre côté du miroir → employé → rôles tenus, et
// on visualise la charge pour repérer surcharge et sous-utilisation.

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

type Employe = {
  id: number;
  full_name: string;
  email?: string | null;
  role?: string | null;
  active?: boolean;
};

const OVERLOAD_THRESHOLD = 4;

export function RessourcesDispatchView({
  nodes,
  employes,
  onPatch
}: {
  nodes: OrgNode[];
  employes: Employe[];
  onPatch: (id: number, patch: Partial<OrgNode>) => void;
}) {
  const [selectedEmpId, setSelectedEmpId] = useState<number | null>(null);
  const [query, setQuery] = useState("");

  const byId = useMemo(() => {
    const m = new Map<number, OrgNode>();
    for (const n of nodes) m.set(n.id, n);
    return m;
  }, [nodes]);

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

  // Index : employe_id → rôles tenus
  const rolesByEmploye = useMemo(() => {
    const m = new Map<number, OrgNode[]>();
    for (const r of roles) {
      if (r.assignee_employe_id != null) {
        const arr = m.get(r.assignee_employe_id) || [];
        arr.push(r);
        m.set(r.assignee_employe_id, arr);
      }
    }
    return m;
  }, [roles]);

  const vacantRoles = useMemo(
    () =>
      roles.filter(
        (r) =>
          r.assignee_employe_id == null &&
          r.assignee_user_id == null &&
          (!r.assignee_external_name || r.assignee_external_name.trim() === "")
      ),
    [roles]
  );

  // Liste employés enrichie : nb de rôles, statut, triée par charge desc.
  const employesEnriched = useMemo(() => {
    const norm = (s: string) =>
      s.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
    const q = norm(query.trim());
    return employes
      .filter((e) => e.active !== false)
      .filter((e) => (q ? norm(e.full_name).includes(q) : true))
      .map((e) => {
        const rs = rolesByEmploye.get(e.id) || [];
        return {
          employe: e,
          roleCount: rs.length,
          roles: rs
        };
      })
      .sort((a, b) => b.roleCount - a.roleCount);
  }, [employes, rolesByEmploye, query]);

  const maxCharge = Math.max(
    1,
    ...employesEnriched.map((x) => x.roleCount),
    OVERLOAD_THRESHOLD
  );

  const stats = useMemo(() => {
    const overloaded = employesEnriched.filter(
      (x) => x.roleCount >= OVERLOAD_THRESHOLD
    ).length;
    const idle = employesEnriched.filter((x) => x.roleCount === 0).length;
    return {
      employees: employesEnriched.length,
      roles: roles.length,
      vacant: vacantRoles.length,
      overloaded,
      idle
    };
  }, [employesEnriched, roles, vacantRoles]);

  const selectedEntry = employesEnriched.find(
    (x) => x.employe.id === selectedEmpId
  );

  function assignRole(roleId: number, employeId: number) {
    onPatch(roleId, {
      assignee_employe_id: employeId,
      assignee_user_id: null,
      assignee_external_name: null
    });
  }
  function releaseRole(roleId: number) {
    onPatch(roleId, {
      assignee_employe_id: null,
      assignee_user_id: null,
      assignee_external_name: null
    });
  }

  return (
    <div className="space-y-4">
      <StatsBanner stats={stats} />

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[20rem_1fr]">
        {/* Liste employés */}
        <div
          className="rounded-2xl border p-3"
          style={{
            borderColor: "var(--qg-border)",
            backgroundColor: "var(--qg-card-bg)"
          }}
        >
          <div className="relative mb-2">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-white/40" />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Chercher un employé…"
              className="input w-full pl-7 text-xs"
            />
          </div>
          <ul className="max-h-[60vh] space-y-1 overflow-y-auto">
            {employesEnriched.map(({ employe, roleCount }) => {
              const pct = Math.min(100, (roleCount / maxCharge) * 100);
              const overloaded = roleCount >= OVERLOAD_THRESHOLD;
              const isActive = employe.id === selectedEmpId;
              return (
                <li key={employe.id}>
                  <button
                    type="button"
                    onClick={() => setSelectedEmpId(employe.id)}
                    className={`w-full rounded-lg px-2.5 py-2 text-left transition ${
                      isActive
                        ? "bg-accent-500/15 ring-1 ring-accent-500/40"
                        : "hover:bg-white/[0.04]"
                    }`}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="truncate text-sm font-semibold text-white">
                        {employe.full_name}
                      </span>
                      <span
                        className={`shrink-0 rounded px-1.5 py-0.5 text-[10px] font-semibold ${
                          overloaded
                            ? "bg-rose-500/20 text-rose-300"
                            : roleCount === 0
                              ? "bg-white/5 text-white/40"
                              : "bg-emerald-500/15 text-emerald-300"
                        }`}
                      >
                        {roleCount}
                      </span>
                    </div>
                    <div className="mt-1.5 h-1 overflow-hidden rounded bg-white/5">
                      <div
                        className={`h-full ${
                          overloaded ? "bg-rose-500" : "bg-emerald-500"
                        }`}
                        style={{ width: `${pct}%` }}
                      />
                    </div>
                    {employe.role ? (
                      <p
                        className="mt-1 truncate text-[10px]"
                        style={{ color: "var(--qg-text-soft)" }}
                      >
                        {employe.role}
                      </p>
                    ) : null}
                  </button>
                </li>
              );
            })}
            {employesEnriched.length === 0 ? (
              <li
                className="px-2 py-4 text-center text-xs"
                style={{ color: "var(--qg-text-muted)" }}
              >
                Aucun employé.
              </li>
            ) : null}
          </ul>
        </div>

        {/* Détail employé + rôles vacants */}
        <div className="space-y-4">
          {selectedEntry ? (
            <EmployeDetail
              employe={selectedEntry.employe}
              roles={selectedEntry.roles}
              findPole={findPole}
              onRelease={releaseRole}
            />
          ) : (
            <div
              className="flex h-[200px] items-center justify-center rounded-2xl border text-sm"
              style={{
                borderColor: "var(--qg-border)",
                backgroundColor: "var(--qg-card-bg)",
                color: "var(--qg-text-soft)"
              }}
            >
              Sélectionne un employé à gauche pour voir ses rôles et lui en
              attribuer de nouveaux.
            </div>
          )}

          <VacantRolesPanel
            vacantRoles={vacantRoles}
            findPole={findPole}
            selectedEmploye={selectedEntry?.employe || null}
            onAssign={assignRole}
          />
        </div>
      </div>
    </div>
  );
}

// ────────────────────────────────────────────────────────────────

function StatsBanner({
  stats
}: {
  stats: {
    employees: number;
    roles: number;
    vacant: number;
    overloaded: number;
    idle: number;
  };
}) {
  return (
    <div
      className="grid grid-cols-2 gap-3 rounded-2xl border p-3 sm:grid-cols-5"
      style={{
        borderColor: "var(--qg-border)",
        backgroundColor: "var(--qg-card-bg)"
      }}
    >
      <Stat
        icon={<Users className="h-4 w-4 text-white/60" />}
        label="Employés actifs"
        value={stats.employees}
      />
      <Stat
        icon={<UserCheck className="h-4 w-4 text-emerald-300" />}
        label="Rôles définis"
        value={stats.roles}
      />
      <Stat
        icon={<UserMinus className="h-4 w-4 text-amber-300" />}
        label="Rôles vacants"
        value={stats.vacant}
        tone={stats.vacant > 0 ? "warn" : "neutral"}
      />
      <Stat
        icon={<AlertTriangle className="h-4 w-4 text-rose-300" />}
        label={`Surchargés (≥${OVERLOAD_THRESHOLD})`}
        value={stats.overloaded}
        tone={stats.overloaded > 0 ? "danger" : "neutral"}
      />
      <Stat
        icon={<Users className="h-4 w-4 text-white/40" />}
        label="Sans rôle"
        value={stats.idle}
      />
    </div>
  );
}

function Stat({
  icon,
  label,
  value,
  tone = "neutral"
}: {
  icon: React.ReactNode;
  label: string;
  value: number;
  tone?: "neutral" | "warn" | "danger";
}) {
  const color =
    tone === "danger"
      ? "text-rose-300"
      : tone === "warn"
        ? "text-amber-300"
        : "text-white";
  return (
    <div>
      <div className="flex items-center gap-1.5">
        {icon}
        <span
          className="text-[10px] uppercase tracking-wider"
          style={{ color: "var(--qg-text-soft)" }}
        >
          {label}
        </span>
      </div>
      <p className={`mt-1 text-2xl font-bold ${color}`}>{value}</p>
    </div>
  );
}

// ────────────────────────────────────────────────────────────────

function EmployeDetail({
  employe,
  roles,
  findPole,
  onRelease
}: {
  employe: Employe;
  roles: OrgNode[];
  findPole: (n: OrgNode) => OrgNode | null;
  onRelease: (roleId: number) => void;
}) {
  const distribution = useMemo(() => {
    const m = new Map<string, number>();
    for (const r of roles) {
      const p = findPole(r);
      const label = p?.label || "Sans pôle";
      m.set(label, (m.get(label) || 0) + 1);
    }
    return Array.from(m.entries()).sort((a, b) => b[1] - a[1]);
  }, [roles, findPole]);

  const max = Math.max(1, ...distribution.map(([, v]) => v));

  return (
    <div
      className="rounded-2xl border p-4"
      style={{
        borderColor: "var(--qg-border)",
        backgroundColor: "var(--qg-card-bg)"
      }}
    >
      <header
        className="border-b pb-3"
        style={{ borderColor: "var(--qg-border-soft)" }}
      >
        <h3 className="text-base font-bold text-white">{employe.full_name}</h3>
        <p
          className="mt-0.5 text-xs"
          style={{ color: "var(--qg-text-soft)" }}
        >
          {employe.email ? `${employe.email} · ` : ""}
          {employe.role || "—"}
        </p>
      </header>

      <section className="mt-3">
        <h4
          className="mb-2 text-[10px] font-semibold uppercase tracking-wider"
          style={{ color: "var(--qg-text-soft)" }}
        >
          Rôles tenus ({roles.length})
        </h4>
        {roles.length === 0 ? (
          <p className="text-xs" style={{ color: "var(--qg-text-muted)" }}>
            Aucun rôle attribué — cet employé est disponible.
          </p>
        ) : (
          <ul className="space-y-1.5">
            {roles.map((r) => {
              const p = findPole(r);
              return (
                <li
                  key={r.id}
                  className="flex items-center justify-between gap-2 rounded border px-3 py-2"
                  style={{
                    borderColor: "var(--qg-border-soft)",
                    backgroundColor: "var(--qg-card-bg-hover, transparent)"
                  }}
                >
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-semibold text-white">
                      {r.label}
                    </p>
                    <p
                      className="truncate text-[11px]"
                      style={{ color: "var(--qg-text-soft)" }}
                    >
                      {p?.label || "Sans pôle"}
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={() => onRelease(r.id)}
                    className="rounded-md border px-2 py-1 text-[10px] font-semibold uppercase tracking-wide text-white/60 hover:bg-rose-500/15 hover:text-rose-300"
                    style={{ borderColor: "var(--qg-border)" }}
                    title="Retirer cet employé du rôle (rend le rôle vacant)"
                  >
                    Libérer
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </section>

      {distribution.length > 0 ? (
        <section className="mt-4">
          <h4
            className="mb-2 text-[10px] font-semibold uppercase tracking-wider"
            style={{ color: "var(--qg-text-soft)" }}
          >
            Distribution par pôle
          </h4>
          <ul className="space-y-1.5">
            {distribution.map(([label, n]) => (
              <li key={label} className="flex items-center gap-2 text-xs">
                <span
                  className="w-32 truncate"
                  style={{ color: "var(--qg-text-soft)" }}
                >
                  {label}
                </span>
                <div className="flex-1 h-1.5 overflow-hidden rounded bg-white/5">
                  <div
                    className="h-full bg-accent-500"
                    style={{ width: `${(n / max) * 100}%` }}
                  />
                </div>
                <span className="w-6 text-right font-semibold text-white">
                  {n}
                </span>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </div>
  );
}

// ────────────────────────────────────────────────────────────────

function VacantRolesPanel({
  vacantRoles,
  findPole,
  selectedEmploye,
  onAssign
}: {
  vacantRoles: OrgNode[];
  findPole: (n: OrgNode) => OrgNode | null;
  selectedEmploye: Employe | null;
  onAssign: (roleId: number, employeId: number) => void;
}) {
  const [poleFilter, setPoleFilter] = useState<string>("all");

  const poles = useMemo(() => {
    const set = new Map<number, OrgNode>();
    for (const r of vacantRoles) {
      const p = findPole(r);
      if (p) set.set(p.id, p);
    }
    return Array.from(set.values()).sort((a, b) =>
      a.label.localeCompare(b.label)
    );
  }, [vacantRoles, findPole]);

  const filtered = useMemo(() => {
    if (poleFilter === "all") return vacantRoles;
    return vacantRoles.filter(
      (r) => String(findPole(r)?.id) === poleFilter
    );
  }, [vacantRoles, poleFilter, findPole]);

  return (
    <div
      className="rounded-2xl border p-4"
      style={{
        borderColor: "var(--qg-border)",
        backgroundColor: "var(--qg-card-bg)"
      }}
    >
      <header className="flex flex-wrap items-center justify-between gap-2 border-b pb-3"
        style={{ borderColor: "var(--qg-border-soft)" }}>
        <div>
          <h3 className="text-base font-bold text-white">
            Rôles à pourvoir
          </h3>
          <p className="text-[11px]" style={{ color: "var(--qg-text-soft)" }}>
            {filtered.length} sur {vacantRoles.length} affichés
            {selectedEmploye
              ? ` · sélection active : ${selectedEmploye.full_name}`
              : " · sélectionne un employé pour pouvoir attribuer"}
          </p>
        </div>
        <select
          value={poleFilter}
          onChange={(e) => setPoleFilter(e.target.value)}
          className="input w-auto text-xs"
        >
          <option value="all">Tous les pôles</option>
          {poles.map((p) => (
            <option key={p.id} value={String(p.id)}>
              {p.label}
            </option>
          ))}
        </select>
      </header>
      {filtered.length === 0 ? (
        <p
          className="py-4 text-center text-xs"
          style={{ color: "var(--qg-text-muted)" }}
        >
          {vacantRoles.length === 0
            ? "Tous les rôles ont un titulaire 🎉"
            : "Aucun rôle vacant pour ce pôle."}
        </p>
      ) : (
        <ul className="mt-3 space-y-1.5">
          {filtered.map((r) => {
            const p = findPole(r);
            return (
              <li
                key={r.id}
                className="flex items-center justify-between gap-2 rounded border px-3 py-2"
                style={{
                  borderColor: "var(--qg-border-soft)",
                  backgroundColor: "var(--qg-card-bg-hover, transparent)"
                }}
              >
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-semibold text-white">
                    {r.label}
                  </p>
                  <p
                    className="truncate text-[11px]"
                    style={{ color: "var(--qg-text-soft)" }}
                  >
                    {p?.label || "Sans pôle"}
                  </p>
                </div>
                {selectedEmploye ? (
                  <button
                    type="button"
                    onClick={() => onAssign(r.id, selectedEmploye.id)}
                    className="btn-accent inline-flex items-center gap-1 text-[11px]"
                    title={`Attribuer à ${selectedEmploye.full_name}`}
                  >
                    Attribuer
                    <ArrowRight className="h-3 w-3" />
                  </button>
                ) : (
                  <ChevronRight className="h-3 w-3 text-white/30" />
                )}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
