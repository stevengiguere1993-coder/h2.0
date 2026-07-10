"use client";

/**
 * Paramètres → Permissions (refonte 2026-07).
 *
 * TROIS vues :
 *  1. Visibilité des pages — matrice par pôle : pour chaque page de Kratos,
 *     le rôle minimum requis pour la VOIR (menus, garde de page et API
 *     lisent la même règle). Défauts = comportement historique.
 *  2. Actions sensibles — la grille des capacités (suppressions, envois…).
 *  3. Par utilisateur — choisir un compte : ses pôles (volets), TOUT ce
 *     qu'il voit et peut faire, et des EXCEPTIONS individuelles (accorder /
 *     retirer une page ou une action précise au-delà de son rôle).
 *
 * Lecture : admin+. Édition : owner uniquement.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Check,
  ChevronRight,
  Eye,
  Loader2,
  ShieldCheck,
  UserCog,
  X
} from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { useAppLayout } from "../../layout";
import { authedFetch, hasMinRole } from "@/lib/auth";
import { useCurrentUser } from "@/hooks/use-current-user";

// ---------------------------------------------------------------------------
// Types & constantes
// ---------------------------------------------------------------------------

type Capability = {
  capability: string;
  label: string;
  description: string;
  category: string;
  min_role: string;
  default_min_role: string;
};
type CapGrid = { roles: string[]; capabilities: Capability[] };

type PageEntry = {
  key: string;
  label: string;
  volet: string;
  volet_label: string;
  min_role: string;
  default_min_role: string;
};
type PagesGrid = {
  roles: string[];
  volet_labels: Record<string, string>;
  pages: PageEntry[];
};

type UserRow = {
  id: number;
  email: string;
  display_name?: string;
  role: string;
  is_active: boolean;
  volets?: string[];
};

type UserAccess = {
  user_id: number;
  email: string;
  display_name: string;
  role: string;
  volets: string[];
  access: Record<string, boolean>;
};

type Override = { key: string; allow: boolean };

const ROLE_LABELS: Record<string, string> = {
  employee: "Employé",
  manager: "Gestionnaire",
  admin: "Administrateur",
  owner: "Propriétaire"
};

//: Volets éditables par utilisateur (mêmes clés que le backend).
const EDITABLE_VOLETS: { key: string; label: string }[] = [
  { key: "construction", label: "Construction" },
  { key: "entreprises", label: "Gestion d'entreprise" },
  { key: "immobilier", label: "Gestion immobilière" },
  { key: "prospection", label: "Prospection" },
  { key: "investisseur", label: "Investisseurs" },
  { key: "developpement_logiciel", label: "Dév. logiciel" },
  { key: "communication", label: "Téléphonie" }
];

// ---------------------------------------------------------------------------
// Onglet 1 — Visibilité des pages
// ---------------------------------------------------------------------------

function PagesTab({ canEdit }: { canEdit: boolean }) {
  const [grid, setGrid] = useState<PagesGrid | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const res = await authedFetch("/api/v1/permissions/pages");
      if (!res.ok) throw new Error();
      setGrid((await res.json()) as PagesGrid);
    } catch {
      setError("Chargement impossible.");
      setGrid({ roles: [], volet_labels: {}, pages: [] });
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function setMinRole(p: PageEntry, minRole: string) {
    if (minRole === p.min_role) return;
    setSaving(p.key);
    setError(null);
    setGrid((g) =>
      g
        ? {
            ...g,
            pages: g.pages.map((x) =>
              x.key === p.key ? { ...x, min_role: minRole } : x
            )
          }
        : g
    );
    try {
      const res = await authedFetch(
        `/api/v1/permissions/pages/${encodeURIComponent(p.key)}`,
        { method: "PUT", body: JSON.stringify({ min_role: minRole }) }
      );
      if (res.status === 403) {
        setError("Seul le propriétaire peut modifier les permissions.");
        await load();
        return;
      }
      if (!res.ok) throw new Error();
      setSaved(p.key);
      setTimeout(() => setSaved((s) => (s === p.key ? null : s)), 2000);
    } catch {
      setError("Enregistrement impossible.");
      await load();
    } finally {
      setSaving(null);
    }
  }

  const byVolet = useMemo(() => {
    const map = new Map<string, PageEntry[]>();
    for (const p of grid?.pages || []) {
      const arr = map.get(p.volet_label) || [];
      arr.push(p);
      map.set(p.volet_label, arr);
    }
    return Array.from(map.entries());
  }, [grid]);

  if (grid === null) {
    return (
      <div className="flex items-center justify-center py-16 text-white/40">
        <Loader2 className="h-6 w-6 animate-spin" />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <p className="max-w-2xl text-sm text-white/60">
        Pour chaque page, le <strong>rôle minimum</strong> requis pour la
        voir. La règle s&apos;applique partout à la fois : menus, accès direct
        à la page et données (API). Il faut aussi que l&apos;utilisateur ait
        accès au <strong>pôle</strong> de la page (vue « Par utilisateur »).
      </p>
      {error ? (
        <p className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-300">
          {error}
        </p>
      ) : null}
      {byVolet.map(([voletLabel, pages]) => (
        <section
          key={voletLabel}
          className="rounded-2xl border border-brand-800 bg-brand-900"
        >
          <header className="border-b border-brand-800 px-5 py-3">
            <h2 className="text-sm font-bold uppercase tracking-wider text-accent-400">
              {voletLabel}
            </h2>
          </header>
          <div className="divide-y divide-brand-800">
            {pages.map((p) => {
              const changed = p.min_role !== p.default_min_role;
              return (
                <div
                  key={p.key}
                  className="flex items-center justify-between gap-3 px-5 py-3"
                >
                  <p className="min-w-0 flex-1 text-sm font-medium text-white">
                    {p.label}
                  </p>
                  <div className="flex items-center gap-3">
                    <select
                      value={p.min_role}
                      disabled={!canEdit || saving === p.key}
                      onChange={(e) => void setMinRole(p, e.target.value)}
                      className="rounded-lg border border-brand-800 bg-brand-950 px-3 py-1.5 text-sm text-white focus:border-accent-500 focus:outline-none disabled:opacity-60"
                    >
                      {grid.roles.map((r) => (
                        <option key={r} value={r}>
                          {ROLE_LABELS[r] || r}
                        </option>
                      ))}
                    </select>
                    <span className="w-14 text-xs">
                      {saving === p.key ? (
                        <Loader2 className="h-4 w-4 animate-spin text-white/40" />
                      ) : saved === p.key ? (
                        <span className="inline-flex items-center gap-1 text-emerald-400">
                          <Check className="h-3.5 w-3.5" /> OK
                        </span>
                      ) : changed ? (
                        <button
                          type="button"
                          disabled={!canEdit}
                          onClick={() =>
                            void setMinRole(p, p.default_min_role)
                          }
                          className="text-xs text-white/40 underline-offset-2 hover:text-white hover:underline disabled:cursor-default"
                          title={`Défaut : ${
                            ROLE_LABELS[p.default_min_role] ||
                            p.default_min_role
                          }`}
                        >
                          réinit.
                        </button>
                      ) : null}
                    </span>
                  </div>
                </div>
              );
            })}
          </div>
        </section>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Onglet 2 — Actions sensibles (grille des capacités, comme avant)
// ---------------------------------------------------------------------------

function ActionsTab({ canEdit }: { canEdit: boolean }) {
  const [grid, setGrid] = useState<CapGrid | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [savingCap, setSavingCap] = useState<string | null>(null);
  const [savedCap, setSavedCap] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const res = await authedFetch("/api/v1/permissions");
      if (!res.ok) throw new Error(`http_${res.status}`);
      setGrid((await res.json()) as CapGrid);
    } catch {
      setError("Chargement des permissions impossible.");
      setGrid({ roles: [], capabilities: [] });
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function setMinRole(cap: Capability, minRole: string) {
    if (minRole === cap.min_role) return;
    setSavingCap(cap.capability);
    setError(null);
    setGrid((g) =>
      g
        ? {
            ...g,
            capabilities: g.capabilities.map((c) =>
              c.capability === cap.capability
                ? { ...c, min_role: minRole }
                : c
            )
          }
        : g
    );
    try {
      const res = await authedFetch(
        `/api/v1/permissions/${cap.capability}`,
        { method: "PUT", body: JSON.stringify({ min_role: minRole }) }
      );
      if (res.status === 403) {
        setError("Seul le propriétaire peut modifier les permissions.");
        await load();
        return;
      }
      if (!res.ok) throw new Error();
      setSavedCap(cap.capability);
      setTimeout(
        () => setSavedCap((s) => (s === cap.capability ? null : s)),
        2000
      );
    } catch {
      setError("Enregistrement impossible.");
      await load();
    } finally {
      setSavingCap(null);
    }
  }

  const byCategory = useMemo(() => {
    const map = new Map<string, Capability[]>();
    for (const c of grid?.capabilities || []) {
      const arr = map.get(c.category) || [];
      arr.push(c);
      map.set(c.category, arr);
    }
    return Array.from(map.entries());
  }, [grid]);

  if (grid === null) {
    return (
      <div className="flex items-center justify-center py-16 text-white/40">
        <Loader2 className="h-6 w-6 animate-spin" />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <p className="max-w-2xl text-sm text-white/60">
        Pour chaque action, le <strong>rôle minimum</strong> requis. Un rôle
        supérieur peut toujours faire ce qu&apos;un rôle inférieur peut faire.
      </p>
      {error ? (
        <p className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-300">
          {error}
        </p>
      ) : null}
      {byCategory.map(([category, caps]) => (
        <section
          key={category}
          className="rounded-2xl border border-brand-800 bg-brand-900"
        >
          <header className="border-b border-brand-800 px-5 py-3">
            <h2 className="text-sm font-bold uppercase tracking-wider text-accent-400">
              {category}
            </h2>
          </header>
          <div className="divide-y divide-brand-800">
            {caps.map((c) => {
              const changed = c.min_role !== c.default_min_role;
              return (
                <div
                  key={c.capability}
                  className="flex flex-col gap-3 px-5 py-4 sm:flex-row sm:items-center sm:justify-between"
                >
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-semibold text-white">
                      {c.label}
                    </p>
                    <p className="mt-0.5 text-xs text-white/60">
                      {c.description}
                    </p>
                  </div>
                  <div className="flex items-center gap-3">
                    <label className="text-[11px] uppercase tracking-wider text-white/40">
                      Rôle min.
                    </label>
                    <select
                      value={c.min_role}
                      disabled={!canEdit || savingCap === c.capability}
                      onChange={(e) => void setMinRole(c, e.target.value)}
                      className="rounded-lg border border-brand-800 bg-brand-950 px-3 py-2 text-sm text-white focus:border-accent-500 focus:outline-none disabled:opacity-60"
                    >
                      {grid.roles.map((r) => (
                        <option key={r} value={r}>
                          {ROLE_LABELS[r] || r}
                        </option>
                      ))}
                    </select>
                    <span className="w-16 text-xs">
                      {savingCap === c.capability ? (
                        <Loader2 className="h-4 w-4 animate-spin text-white/40" />
                      ) : savedCap === c.capability ? (
                        <span className="inline-flex items-center gap-1 text-emerald-400">
                          <Check className="h-3.5 w-3.5" /> OK
                        </span>
                      ) : changed ? (
                        <button
                          type="button"
                          disabled={!canEdit}
                          onClick={() =>
                            void setMinRole(c, c.default_min_role)
                          }
                          className="text-xs text-white/40 underline-offset-2 hover:text-white hover:underline disabled:cursor-default"
                          title={`Défaut : ${
                            ROLE_LABELS[c.default_min_role] ||
                            c.default_min_role
                          }`}
                        >
                          réinit.
                        </button>
                      ) : null}
                    </span>
                  </div>
                </div>
              );
            })}
          </div>
        </section>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Onglet 3 — Par utilisateur (volets + accès calculé + exceptions)
// ---------------------------------------------------------------------------

function UsersTab({ canEdit }: { canEdit: boolean }) {
  const [users, setUsers] = useState<UserRow[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [detail, setDetail] = useState<UserAccess | null>(null);
  const [overrides, setOverrides] = useState<Override[]>([]);
  const [pages, setPages] = useState<PagesGrid | null>(null);
  const [caps, setCaps] = useState<CapGrid | null>(null);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busyKey, setBusyKey] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [uRes, pRes, cRes] = await Promise.all([
          authedFetch("/api/v1/users"),
          authedFetch("/api/v1/permissions/pages"),
          authedFetch("/api/v1/permissions")
        ]);
        if (cancelled) return;
        if (uRes.ok) {
          const all = (await uRes.json()) as UserRow[];
          setUsers(all.filter((u) => u.is_active));
        }
        if (pRes.ok) setPages((await pRes.json()) as PagesGrid);
        if (cRes.ok) setCaps((await cRes.json()) as CapGrid);
      } catch {
        if (!cancelled) setError("Chargement impossible.");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const loadDetail = useCallback(async (userId: number) => {
    setLoadingDetail(true);
    setError(null);
    try {
      const [aRes, oRes] = await Promise.all([
        authedFetch(`/api/v1/permissions/users/${userId}/access`),
        authedFetch(`/api/v1/permissions/users/${userId}/overrides`)
      ]);
      if (!aRes.ok) throw new Error();
      setDetail((await aRes.json()) as UserAccess);
      setOverrides(oRes.ok ? ((await oRes.json()) as Override[]) : []);
    } catch {
      setError("Chargement de l'utilisateur impossible.");
      setDetail(null);
    } finally {
      setLoadingDetail(false);
    }
  }, []);

  useEffect(() => {
    if (selectedId != null) void loadDetail(selectedId);
  }, [selectedId, loadDetail]);

  async function toggleVolet(volet: string) {
    if (!detail || !canEdit) return;
    const cur = detail.volets;
    const next = cur.includes(volet)
      ? cur.filter((v) => v !== volet)
      : [...cur, volet];
    setBusyKey(`volet:${volet}`);
    try {
      const res = await authedFetch(
        `/api/v1/users/${detail.user_id}/volets`,
        { method: "PATCH", body: JSON.stringify({ volets: next }) }
      );
      if (!res.ok) throw new Error();
      await loadDetail(detail.user_id);
    } catch {
      setError("Modification des pôles impossible.");
    } finally {
      setBusyKey(null);
    }
  }

  // Cycle d'exception : aucune → accordée → retirée → aucune.
  async function cycleOverride(key: string) {
    if (!detail || !canEdit) return;
    const cur = overrides.find((o) => o.key === key);
    const next: boolean | null =
      cur == null ? true : cur.allow ? false : null;
    setBusyKey(key);
    try {
      const res = await authedFetch(
        `/api/v1/permissions/users/${detail.user_id}/overrides`,
        { method: "PUT", body: JSON.stringify({ key, allow: next }) }
      );
      if (res.status === 403) {
        setError("Seul le propriétaire peut poser des exceptions.");
        return;
      }
      if (!res.ok) throw new Error();
      setOverrides((await res.json()) as Override[]);
      await loadDetail(detail.user_id);
    } catch {
      setError("Modification impossible.");
    } finally {
      setBusyKey(null);
    }
  }

  const pagesByVolet = useMemo(() => {
    const map = new Map<string, PageEntry[]>();
    for (const p of pages?.pages || []) {
      const arr = map.get(p.volet_label) || [];
      arr.push(p);
      map.set(p.volet_label, arr);
    }
    return Array.from(map.entries());
  }, [pages]);

  const overrideOf = (key: string) => overrides.find((o) => o.key === key);
  const targetIsAdminUp =
    detail != null && (detail.role === "owner" || detail.role === "admin");

  function AccessChip({
    accessKey,
    label
  }: {
    accessKey: string;
    label: string;
  }) {
    const ok = detail?.access?.[accessKey] === true;
    const ov = overrideOf(accessKey);
    return (
      <button
        type="button"
        disabled={!canEdit || busyKey === accessKey}
        onClick={() => void cycleOverride(accessKey)}
        title={
          ov
            ? ov.allow
              ? "Exception : accordé — cliquer pour retirer"
              : "Exception : retiré — cliquer pour enlever l'exception"
            : canEdit
              ? "Cliquer pour poser une exception individuelle"
              : undefined
        }
        className={`inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-xs font-medium transition disabled:cursor-default ${
          ok
            ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-300"
            : "border-brand-800 bg-brand-950 text-white/35"
        } ${ov ? "ring-1 ring-accent-500/60" : ""} ${
          canEdit ? "hover:border-accent-500/50" : ""
        }`}
      >
        {busyKey === accessKey ? (
          <Loader2 className="h-3 w-3 animate-spin" />
        ) : ok ? (
          <Check className="h-3 w-3" />
        ) : (
          <X className="h-3 w-3" />
        )}
        {label}
        {ov ? <span className="text-accent-400">•</span> : null}
      </button>
    );
  }

  return (
    <div className="grid gap-6 lg:grid-cols-[280px,1fr]">
      {/* Liste des utilisateurs */}
      <section className="h-fit rounded-2xl border border-brand-800 bg-brand-900">
        <header className="border-b border-brand-800 px-4 py-3">
          <h2 className="text-sm font-bold uppercase tracking-wider text-accent-400">
            Utilisateurs
          </h2>
        </header>
        <div className="max-h-[60vh] divide-y divide-brand-800 overflow-y-auto">
          {users.map((u) => (
            <button
              key={u.id}
              type="button"
              onClick={() => setSelectedId(u.id)}
              className={`flex w-full items-center justify-between gap-2 px-4 py-3 text-left transition ${
                selectedId === u.id
                  ? "bg-accent-500/10"
                  : "hover:bg-brand-800/40"
              }`}
            >
              <span className="min-w-0">
                <span className="block truncate text-sm font-semibold text-white">
                  {u.display_name || u.email.split("@")[0]}
                </span>
                <span className="block text-[11px] text-white/50">
                  {ROLE_LABELS[u.role] || u.role}
                </span>
              </span>
              <ChevronRight className="h-4 w-4 shrink-0 text-white/30" />
            </button>
          ))}
        </div>
      </section>

      {/* Détail */}
      <section className="min-w-0">
        {error ? (
          <p className="mb-4 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-300">
            {error}
          </p>
        ) : null}
        {selectedId == null ? (
          <p className="rounded-2xl border border-dashed border-brand-800 bg-brand-900/40 p-8 text-center text-sm text-white/40">
            Choisis un utilisateur pour voir tout ce qu&apos;il voit et peut
            faire — et poser des exceptions individuelles.
          </p>
        ) : loadingDetail || !detail ? (
          <div className="flex items-center justify-center py-16 text-white/40">
            <Loader2 className="h-6 w-6 animate-spin" />
          </div>
        ) : (
          <div className="space-y-6">
            {/* En-tête utilisateur */}
            <div className="rounded-2xl border border-brand-800 bg-brand-900 p-5">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <h3 className="text-lg font-bold text-white">
                    {detail.display_name || detail.email}
                  </h3>
                  <p className="text-xs text-white/50">{detail.email}</p>
                </div>
                <span className="badge badge-neutral">
                  {ROLE_LABELS[detail.role] || detail.role}
                </span>
              </div>

              {/* Volets */}
              <p className="mt-4 text-[11px] font-medium uppercase tracking-wider text-white/40">
                Accès aux pôles
              </p>
              {targetIsAdminUp ? (
                <p className="mt-1.5 text-xs text-white/50">
                  Les administrateurs et propriétaires ont accès à tous les
                  pôles.
                </p>
              ) : (
                <div className="mt-2 flex flex-wrap gap-2">
                  {EDITABLE_VOLETS.map((v) => {
                    const on = detail.volets.includes(v.key);
                    return (
                      <button
                        key={v.key}
                        type="button"
                        disabled={!canEdit || busyKey === `volet:${v.key}`}
                        onClick={() => void toggleVolet(v.key)}
                        className={`inline-flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-xs font-semibold transition disabled:cursor-default ${
                          on
                            ? "border-accent-500/50 bg-accent-500/15 text-accent-300"
                            : "border-brand-800 bg-brand-950 text-white/40"
                        } ${canEdit ? "hover:border-accent-500/60" : ""}`}
                      >
                        {busyKey === `volet:${v.key}` ? (
                          <Loader2 className="h-3 w-3 animate-spin" />
                        ) : on ? (
                          <Check className="h-3 w-3" />
                        ) : (
                          <X className="h-3 w-3" />
                        )}
                        {v.label}
                      </button>
                    );
                  })}
                </div>
              )}
            </div>

            {/* Pages par pôle */}
            <div className="rounded-2xl border border-brand-800 bg-brand-900 p-5">
              <h4 className="text-sm font-bold uppercase tracking-wider text-accent-400">
                Pages visibles
              </h4>
              <p className="mt-1 text-xs text-white/50">
                Vert = visible pour ce compte. {canEdit
                  ? "Clique une page pour poser une exception (accordée → retirée → aucune). Le point or signale une exception."
                  : "Le point or signale une exception individuelle."}
              </p>
              <div className="mt-4 space-y-4">
                {pagesByVolet.map(([voletLabel, ps]) => (
                  <div key={voletLabel}>
                    <p className="mb-2 text-[11px] font-medium uppercase tracking-wider text-white/40">
                      {voletLabel}
                    </p>
                    <div className="flex flex-wrap gap-2">
                      {ps.map((p) => (
                        <AccessChip
                          key={p.key}
                          accessKey={`page:${p.key}`}
                          label={p.label}
                        />
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {/* Actions par catégorie */}
            <div className="rounded-2xl border border-brand-800 bg-brand-900 p-5">
              <h4 className="text-sm font-bold uppercase tracking-wider text-accent-400">
                Actions permises
              </h4>
              <div className="mt-4 space-y-4">
                {Array.from(
                  (caps?.capabilities || []).reduce((m, c) => {
                    const arr = m.get(c.category) || [];
                    arr.push(c);
                    m.set(c.category, arr);
                    return m;
                  }, new Map<string, Capability[]>())
                ).map(([category, cs]) => (
                  <div key={category}>
                    <p className="mb-2 text-[11px] font-medium uppercase tracking-wider text-white/40">
                      {category}
                    </p>
                    <div className="flex flex-wrap gap-2">
                      {cs.map((c) => (
                        <AccessChip
                          key={c.capability}
                          accessKey={c.capability}
                          label={c.label}
                        />
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}
      </section>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

type Tab = "pages" | "actions" | "utilisateurs";

export default function PermissionsSettingsPage() {
  const { onOpenSidebar } = useAppLayout();
  const { user: me } = useCurrentUser();
  const canEdit = hasMinRole(me, "owner");
  const [tab, setTab] = useState<Tab>("pages");

  const TABS: { key: Tab; label: string; icon: typeof Eye }[] = [
    { key: "pages", label: "Visibilité des pages", icon: Eye },
    { key: "actions", label: "Actions sensibles", icon: ShieldCheck },
    { key: "utilisateurs", label: "Par utilisateur", icon: UserCog }
  ];

  return (
    <>
      <AppTopbar
        breadcrumbs={[
          { label: "Construction", href: "/app" },
          { label: "Paramètres", href: "/parametres" },
          { label: "Permissions" }
        ]}
        onOpenSidebar={onOpenSidebar}
      />

      <div className="p-4 pb-28 lg:p-6 lg:pb-28">
        <h1 className="flex items-center gap-2 text-2xl font-bold text-white">
          <ShieldCheck className="h-6 w-6 text-accent-500" />
          Permissions
        </h1>
        <p className="mt-1 max-w-2xl text-sm text-white/60">
          Qui voit quoi, qui peut faire quoi — pour tout Kratos.
          {!canEdit ? (
            <span className="mt-1 block text-white/50">
              Lecture seule — seul le propriétaire peut modifier ces réglages.
            </span>
          ) : null}
        </p>

        <div className="mt-5 flex flex-wrap gap-2">
          {TABS.map((t) => {
            const Icon = t.icon;
            return (
              <button
                key={t.key}
                type="button"
                onClick={() => setTab(t.key)}
                className={`inline-flex items-center gap-1.5 rounded-full border px-3.5 py-1.5 text-sm font-medium transition ${
                  tab === t.key
                    ? "border-accent-500 bg-accent-500/15 text-accent-300"
                    : "border-brand-800 bg-brand-900 text-white/60 hover:border-accent-500/50 hover:text-white"
                }`}
              >
                <Icon className="h-4 w-4" />
                {t.label}
              </button>
            );
          })}
        </div>

        <div className="mt-6">
          {tab === "pages" ? <PagesTab canEdit={canEdit} /> : null}
          {tab === "actions" ? <ActionsTab canEdit={canEdit} /> : null}
          {tab === "utilisateurs" ? <UsersTab canEdit={canEdit} /> : null}
        </div>
      </div>
    </>
  );
}
