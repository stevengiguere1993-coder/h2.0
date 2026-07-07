"use client";

/**
 * Paramètres → Permissions.
 *
 * Grille des actions sensibles : pour chaque capacité, le RÔLE MINIMUM
 * requis (employé < gestionnaire < administrateur < propriétaire). Les
 * valeurs par défaut reproduisent le comportement actuel — rien ne
 * change tant que l'owner n'ajuste rien.
 *
 * Lecture : admin+. Édition : owner uniquement (le PUT renvoie 403
 * sinon → on désactive les sélecteurs pour les non-owner).
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { Check, Loader2, ShieldCheck } from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { useAppLayout } from "../../layout";
import { authedFetch, hasMinRole } from "@/lib/auth";
import { useCurrentUser } from "@/hooks/use-current-user";

type Capability = {
  capability: string;
  label: string;
  description: string;
  category: string;
  min_role: string;
  default_min_role: string;
};

type Grid = { roles: string[]; capabilities: Capability[] };

const ROLE_LABELS: Record<string, string> = {
  employee: "Employé",
  manager: "Gestionnaire",
  admin: "Administrateur",
  owner: "Propriétaire"
};

export default function PermissionsSettingsPage() {
  const { onOpenSidebar } = useAppLayout();
  const { user: me } = useCurrentUser();
  const canEdit = hasMinRole(me, "owner");

  const [grid, setGrid] = useState<Grid | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [savingCap, setSavingCap] = useState<string | null>(null);
  const [savedCap, setSavedCap] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const res = await authedFetch("/api/v1/permissions");
      if (!res.ok) throw new Error(`http_${res.status}`);
      setGrid((await res.json()) as Grid);
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
    // Optimiste.
    setGrid((g) =>
      g
        ? {
            ...g,
            capabilities: g.capabilities.map((c) =>
              c.capability === cap.capability ? { ...c, min_role: minRole } : c
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

  return (
    <>
      <AppTopbar
        breadcrumbs={[
          { label: "Construction", href: "/app" },
          { label: "Paramètres", href: "/app/parametres" },
          { label: "Permissions" }
        ]}
        onOpenSidebar={onOpenSidebar}
      />

      <div className="p-4 pb-28 lg:p-6 lg:pb-28">
        <h1 className="flex items-center gap-2 text-2xl font-bold text-white">
          <ShieldCheck className="h-6 w-6 text-accent-500" />
          Permissions — actions sensibles
        </h1>
        <p className="mt-1 max-w-2xl text-sm text-white/60">
          Pour chaque action, choisis le <strong>rôle minimum</strong> requis.
          Un rôle supérieur peut toujours faire ce qu&apos;un rôle inférieur
          peut faire. Les valeurs par défaut reproduisent le comportement
          actuel.
          {!canEdit ? (
            <span className="mt-1 block text-white/50">
              Lecture seule — seul le propriétaire peut modifier ces réglages.
            </span>
          ) : null}
        </p>

        {error ? (
          <p className="mt-4 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-300">
            {error}
          </p>
        ) : null}

        {grid === null ? (
          <div className="flex items-center justify-center py-16 text-white/40">
            <Loader2 className="h-6 w-6 animate-spin" />
          </div>
        ) : grid.capabilities.length === 0 ? (
          <p className="mt-6 text-sm text-white/50">
            Aucune action configurable pour l&apos;instant.
          </p>
        ) : (
          <div className="mt-6 space-y-6">
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
                                className="text-white/40 hover:text-white disabled:cursor-default disabled:hover:text-white/40"
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
        )}
      </div>
    </>
  );
}
