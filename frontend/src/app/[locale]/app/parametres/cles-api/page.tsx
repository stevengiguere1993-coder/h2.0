"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertCircle,
  Check,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Copy,
  KeyRound,
  Loader2,
  Plus,
  ShieldAlert,
  Trash2
} from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { useConfirm } from "@/components/confirm-dialog";
import { Link } from "@/i18n/navigation";
import { useAppLayout } from "../../layout";
import { authedFetch } from "@/lib/auth";

/**
 * Page « Clés API » — chaque utilisateur gère SES propres clés ET les
 * permissions de chaque clé, ORGANISÉES PAR PÔLE (comme la gestion du
 * Drive « Afficher Drive sur les pages »).
 *
 * Endpoints :
 *   POST   /api/v1/api-keys              → génère une clé (secret UNE fois)
 *   GET    /api/v1/api-keys              → liste mes clés (+ scopes)
 *   GET    /api/v1/api-keys/capabilities → catalogue des capacités par pôle
 *   PATCH  /api/v1/api-keys/{id}         → met à jour les scopes d'une clé
 *   DELETE /api/v1/api-keys/{id}         → révoque une clé
 *
 * Une clé ne fait QUE ce que ses scopes autorisent, pôle par pôle. Le
 * secret `krts_…` n'apparaît qu'une seule fois, à la création.
 */

type ApiKey = {
  id: number;
  key_prefix: string;
  label: string | null;
  is_active: boolean;
  created_at: string;
  last_used_at: string | null;
  expires_at: string | null;
  scopes: string[];
};

type ApiKeyCreated = ApiKey & {
  api_key: string;
  warning: string;
};

type Capability = {
  id: string;
  pole: string;
  label_fr: string;
  description: string;
  category: "lecture" | "ecriture";
  risk: string;
  coming_soon: boolean;
};

type PoleCatalog = {
  slug: string;
  label_fr: string;
  capabilities: Capability[];
};

type Catalog = {
  poles: PoleCatalog[];
  legacy_global_read: string;
};

function fmtDate(iso: string | null): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString("fr-CA", {
      year: "numeric",
      month: "short",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit"
    });
  } catch {
    return iso;
  }
}

/** Interrupteur sobre (on/off) réutilisable. */
function Toggle({
  on,
  disabled,
  busy,
  onClick
}: {
  on: boolean;
  disabled?: boolean;
  busy?: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      disabled={disabled || busy}
      onClick={onClick}
      className={
        "relative inline-flex h-5 w-9 shrink-0 items-center rounded-full border transition-colors " +
        (on
          ? "border-accent-500 bg-accent-500"
          : "border-slate-400/60 bg-slate-300") +
        (disabled ? " cursor-not-allowed opacity-40" : " hover:opacity-90")
      }
    >
      <span
        className={
          "inline-block h-4 w-4 transform rounded-full bg-white shadow transition-transform " +
          (on ? "translate-x-4" : "translate-x-0.5")
        }
      />
      {busy ? (
        <Loader2 className="absolute -right-5 h-3.5 w-3.5 animate-spin text-white/50" />
      ) : null}
    </button>
  );
}

/**
 * Bloc de permissions groupées PAR PÔLE. Utilisé à la fois pour une clé
 * existante (édition via PATCH) et pour le formulaire de génération
 * (sélection initiale). `selected` = set de scope ids ; `onToggle` bascule
 * un scope. `busyScope` = scope en cours d'enregistrement (clé existante).
 */
function PolePermissions({
  catalog,
  selected,
  onToggle,
  busyScope,
  disabled
}: {
  catalog: Catalog;
  selected: Set<string>;
  onToggle: (scopeId: string) => void;
  busyScope?: string | null;
  disabled?: boolean;
}) {
  const [openPoles, setOpenPoles] = useState<Set<string>>(new Set());

  const toggleOpen = (slug: string) => {
    setOpenPoles((prev) => {
      const next = new Set(prev);
      if (next.has(slug)) next.delete(slug);
      else next.add(slug);
      return next;
    });
  };

  return (
    <div className="space-y-2">
      {catalog.poles.map((pole) => {
        const open = openPoles.has(pole.slug);
        const activeCount = pole.capabilities.filter(
          (c) => selected.has(c.id) && !c.coming_soon
        ).length;
        return (
          <div
            key={pole.slug}
            className="overflow-hidden rounded-xl border border-brand-800 bg-brand-950/40"
          >
            <button
              type="button"
              onClick={() => toggleOpen(pole.slug)}
              className="flex w-full items-center justify-between px-3 py-2.5 text-left hover:bg-brand-800/30"
            >
              <span className="flex items-center gap-2 text-sm font-semibold text-white/90">
                {open ? (
                  <ChevronDown className="h-4 w-4 text-white/50" />
                ) : (
                  <ChevronRight className="h-4 w-4 text-white/50" />
                )}
                {pole.label_fr}
              </span>
              <span className="text-[11px] text-white/40">
                {activeCount > 0
                  ? `${activeCount} activée${activeCount > 1 ? "s" : ""}`
                  : "Aucune"}
              </span>
            </button>
            {open ? (
              <div className="divide-y divide-brand-800/60 border-t border-brand-800">
                {pole.capabilities.map((cap) => {
                  const on = selected.has(cap.id) && !cap.coming_soon;
                  return (
                    <div
                      key={cap.id}
                      className="flex items-start justify-between gap-3 px-3 py-2.5"
                    >
                      <div className="min-w-0">
                        <p className="flex items-center gap-2 text-sm text-white/85">
                          {cap.label_fr}
                          {cap.category === "ecriture" ? (
                            <span className="rounded border border-amber-500/30 bg-amber-500/10 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-amber-300/90">
                              écriture
                            </span>
                          ) : null}
                          {cap.coming_soon ? (
                            <span className="rounded border border-white/15 bg-white/5 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-white/40">
                              à venir
                            </span>
                          ) : null}
                        </p>
                        <p className="mt-0.5 text-xs text-white/45">
                          {cap.description}
                        </p>
                      </div>
                      <Toggle
                        on={on}
                        disabled={disabled || cap.coming_soon}
                        busy={busyScope === cap.id}
                        onClick={() => onToggle(cap.id)}
                      />
                    </div>
                  );
                })}
              </div>
            ) : null}
          </div>
        );
      })}
    </div>
  );
}

export default function ClesApiPage() {
  const { onOpenSidebar } = useAppLayout();
  const confirm = useConfirm();

  const [keys, setKeys] = useState<ApiKey[]>([]);
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Formulaire de génération
  const [showForm, setShowForm] = useState(false);
  const [label, setLabel] = useState("");
  const [creating, setCreating] = useState(false);
  // Scopes sélectionnés pour la NOUVELLE clé (défaut : lecture tous pôles).
  const [newScopes, setNewScopes] = useState<Set<string>>(new Set());

  // Clé fraîchement créée — affichée UNE seule fois.
  const [freshKey, setFreshKey] = useState<ApiKeyCreated | null>(null);
  const [copied, setCopied] = useState(false);

  // Édition des scopes d'une clé existante.
  const [editingKeyId, setEditingKeyId] = useState<number | null>(null);
  const [busyScope, setBusyScope] = useState<string | null>(null);

  const defaultReadScopes = useMemo(() => {
    if (!catalog) return new Set<string>();
    const s = new Set<string>();
    for (const p of catalog.poles) {
      for (const c of p.capabilities) {
        if (c.category === "lecture" && !c.coming_soon) s.add(c.id);
      }
    }
    return s;
  }, [catalog]);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [keysRes, capRes] = await Promise.all([
        authedFetch("/api/v1/api-keys"),
        authedFetch("/api/v1/api-keys/capabilities")
      ]);
      if (!keysRes.ok) throw new Error(`HTTP ${keysRes.status}`);
      setKeys((await keysRes.json()) as ApiKey[]);
      if (capRes.ok) {
        setCatalog((await capRes.json()) as Catalog);
      }
    } catch (e) {
      setError("Chargement des clés échoué : " + (e as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  // Quand le catalogue arrive et que le formulaire s'ouvre sans sélection,
  // pré-coche le défaut sûr (lecture de tous les pôles).
  useEffect(() => {
    if (showForm && catalog && newScopes.size === 0) {
      setNewScopes(new Set(defaultReadScopes));
    }
  }, [showForm, catalog, defaultReadScopes, newScopes.size]);

  function toggleNewScope(scopeId: string) {
    setNewScopes((prev) => {
      const next = new Set(prev);
      if (next.has(scopeId)) next.delete(scopeId);
      else next.add(scopeId);
      return next;
    });
  }

  async function createKey() {
    setCreating(true);
    setError(null);
    try {
      const res = await authedFetch("/api/v1/api-keys", {
        method: "POST",
        body: JSON.stringify({
          label: label.trim() || null,
          scopes: Array.from(newScopes)
        })
      });
      if (!res.ok) {
        const txt = await res.text();
        throw new Error(txt.slice(0, 240) || `HTTP ${res.status}`);
      }
      const created = (await res.json()) as ApiKeyCreated;
      setFreshKey(created);
      setCopied(false);
      setShowForm(false);
      setLabel("");
      setNewScopes(new Set());
      void load();
    } catch (e) {
      setError("Génération de la clé échouée : " + (e as Error).message);
    } finally {
      setCreating(false);
    }
  }

  async function copyFresh() {
    if (!freshKey) return;
    try {
      await navigator.clipboard.writeText(freshKey.api_key);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2500);
    } catch {
      setError(
        "Copie automatique impossible — sélectionne et copie la clé à la main."
      );
    }
  }

  // Bascule un scope sur une clé EXISTANTE (PATCH la liste complète).
  async function toggleKeyScope(key: ApiKey, scopeId: string) {
    const set = new Set(key.scopes);
    if (set.has(scopeId)) set.delete(scopeId);
    else set.add(scopeId);
    const nextScopes = Array.from(set);

    setBusyScope(scopeId);
    setError(null);
    try {
      const res = await authedFetch(`/api/v1/api-keys/${key.id}`, {
        method: "PATCH",
        body: JSON.stringify({ scopes: nextScopes })
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const updated = (await res.json()) as ApiKey;
      setKeys((prev) =>
        prev.map((k) => (k.id === key.id ? updated : k))
      );
    } catch (e) {
      setError("Mise à jour des permissions échouée : " + (e as Error).message);
    } finally {
      setBusyScope(null);
    }
  }

  async function revoke(key: ApiKey) {
    const ok = await confirm({
      title: "Révoquer cette clé ?",
      description:
        "Les assistants ou outils qui l'utilisent perdront immédiatement " +
        "l'accès à ton activité Kratos. Cette action est irréversible.",
      confirmLabel: "Révoquer",
      destructive: true
    });
    if (!ok) return;
    setError(null);
    try {
      const res = await authedFetch(`/api/v1/api-keys/${key.id}`, {
        method: "DELETE"
      });
      if (!res.ok && res.status !== 204) {
        throw new Error(`HTTP ${res.status}`);
      }
      await load();
    } catch (e) {
      setError("Révocation échouée : " + (e as Error).message);
    }
  }

  return (
    <>
      <AppTopbar
        breadcrumbs={[
          { label: "Construction", href: "/app" },
          { label: "Paramètres", href: "/app/parametres" },
          { label: "Clés API" }
        ]}
        onOpenSidebar={onOpenSidebar}
      />

      <div className="p-4 lg:p-6">
        <Link
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          href={"/app/parametres" as any}
          className="mb-2 inline-flex items-center text-xs text-white/60 hover:text-accent-500"
        >
          <ChevronLeft className="mr-1 h-3.5 w-3.5" /> Paramètres
        </Link>

        <h1 className="flex items-center gap-2 text-2xl font-bold text-white">
          <KeyRound className="h-6 w-6 text-accent-500" />
          Clés API
        </h1>
        <p className="mt-1 max-w-2xl text-sm text-white/60">
          Une clé API permet à tes assistants Claude (ou autres outils)
          d&apos;agir sur Kratos en ton nom. Les permissions sont organisées
          PAR PÔLE — comme la gestion du Drive — : pour chaque clé, active
          uniquement ce que l&apos;assistant peut faire dans chaque pôle.
          Garde la clé secrète.
        </p>

        {error ? (
          <p className="mt-4 flex items-start gap-2 rounded-lg border border-rose-500/40 bg-rose-500/10 px-4 py-2 text-sm text-rose-300">
            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
            <span>{error}</span>
          </p>
        ) : null}

        {/* Encadré « clé fraîchement générée » — visible UNE seule fois. */}
        {freshKey ? (
          <section className="mt-5 rounded-2xl border border-accent-500/40 bg-accent-500/5 p-5">
            <header className="flex items-center gap-2">
              <ShieldAlert className="h-5 w-5 text-accent-400" />
              <h2 className="text-base font-bold text-white">
                Ta nouvelle clé API
              </h2>
            </header>
            <p className="mt-2 flex items-start gap-2 rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-sm font-semibold text-amber-200">
              <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
              <span>
                Copie cette clé maintenant — elle ne sera plus jamais
                affichée. En cas de perte, révoque-la et génères-en une
                nouvelle.
              </span>
            </p>
            <div className="mt-3 flex flex-col gap-2 sm:flex-row sm:items-center">
              <code className="flex-1 overflow-x-auto rounded-lg border border-brand-800 bg-brand-950 px-3 py-2.5 font-mono text-sm text-white">
                {freshKey.api_key}
              </code>
              <button
                type="button"
                onClick={copyFresh}
                className="btn-accent shrink-0 text-sm"
              >
                {copied ? (
                  <>
                    <Check className="mr-1.5 h-4 w-4" /> Copiée
                  </>
                ) : (
                  <>
                    <Copy className="mr-1.5 h-4 w-4" /> Copier
                  </>
                )}
              </button>
            </div>
            <button
              type="button"
              onClick={() => setFreshKey(null)}
              className="mt-3 text-xs text-white/50 hover:text-white/80"
            >
              J&apos;ai copié ma clé — masquer
            </button>
          </section>
        ) : null}

        {/* Action : générer une nouvelle clé. */}
        <div className="mt-5">
          {showForm ? (
            <section className="rounded-2xl border border-brand-800 bg-brand-900 p-5">
              <h2 className="text-base font-bold text-white">
                Générer une clé
              </h2>
              <div className="mt-4">
                <label className="label">Libellé (facultatif)</label>
                <input
                  type="text"
                  value={label}
                  onChange={(e) => setLabel(e.target.value)}
                  placeholder="Ex. Mon assistant Claude"
                  maxLength={120}
                  className="input sm:w-80"
                />
                <p className="mt-1 text-xs text-white/50">
                  Un nom te permet de reconnaître la clé plus tard (ex. quel
                  outil l&apos;utilise).
                </p>
              </div>

              {catalog ? (
                <div className="mt-5">
                  <label className="label">Permissions par pôle</label>
                  <p className="mb-2 text-xs text-white/50">
                    Active ce que l&apos;assistant pourra faire, pôle par
                    pôle. Par défaut : lecture de tous les pôles.
                  </p>
                  <PolePermissions
                    catalog={catalog}
                    selected={newScopes}
                    onToggle={toggleNewScope}
                  />
                </div>
              ) : null}

              <div className="mt-4 flex flex-wrap items-center gap-2">
                <button
                  type="button"
                  onClick={createKey}
                  disabled={creating}
                  className="btn-accent text-sm disabled:opacity-60"
                >
                  {creating ? (
                    <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />
                  ) : (
                    <KeyRound className="mr-1.5 h-4 w-4" />
                  )}
                  Générer la clé
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setShowForm(false);
                    setLabel("");
                    setNewScopes(new Set());
                  }}
                  disabled={creating}
                  className="btn-secondary text-sm"
                >
                  Annuler
                </button>
              </div>
            </section>
          ) : (
            <button
              type="button"
              onClick={() => setShowForm(true)}
              className="btn-accent text-sm"
            >
              <Plus className="mr-1.5 h-4 w-4" /> Générer une clé
            </button>
          )}
        </div>

        {/* Liste des clés existantes. */}
        <section className="mt-6">
          <h2 className="text-sm font-semibold uppercase tracking-wider text-white/50">
            Mes clés
          </h2>

          {loading ? (
            <div className="mt-4 flex items-center justify-center py-10">
              <Loader2 className="h-6 w-6 animate-spin text-accent-500" />
            </div>
          ) : keys.length === 0 ? (
            <div className="mt-4 rounded-2xl border border-dashed border-brand-800 bg-brand-900/40 px-6 py-12 text-center">
              <KeyRound className="mx-auto h-8 w-8 text-white/30" />
              <p className="mt-3 text-sm text-white/60">
                Aucune clé pour l&apos;instant. Génère ta première clé pour
                connecter un assistant.
              </p>
            </div>
          ) : (
            <div className="mt-4 space-y-3">
              {keys.map((k) => {
                const editing = editingKeyId === k.id;
                const selected = new Set(k.scopes);
                return (
                  <div
                    key={k.id}
                    className={
                      "rounded-2xl border border-brand-800 bg-brand-900 " +
                      (k.is_active ? "" : "opacity-60")
                    }
                  >
                    <div className="flex flex-wrap items-center gap-3 px-4 py-3">
                      <div className="min-w-0 flex-1">
                        <p className="flex items-center gap-2 text-sm font-medium text-white/90">
                          {k.label || (
                            <span className="italic text-white/40">
                              Sans libellé
                            </span>
                          )}
                          {k.is_active ? (
                            <span className="rounded-full border border-emerald-500/30 bg-emerald-500/15 px-2 py-0.5 text-[10px] font-semibold text-emerald-300">
                              Active
                            </span>
                          ) : (
                            <span className="rounded-full border border-white/20 bg-white/10 px-2 py-0.5 text-[10px] font-semibold text-white/50">
                              Révoquée
                            </span>
                          )}
                        </p>
                        <p className="mt-0.5 text-xs text-white/50">
                          <code className="font-mono text-white/60">
                            {k.key_prefix}…
                          </code>
                          {" · Créée le "}
                          {fmtDate(k.created_at)}
                          {" · Dernière utilisation : "}
                          {k.last_used_at ? fmtDate(k.last_used_at) : "jamais"}
                        </p>
                      </div>
                      <div className="flex items-center gap-2">
                        {k.is_active && catalog ? (
                          <button
                            type="button"
                            onClick={() =>
                              setEditingKeyId(editing ? null : k.id)
                            }
                            className="inline-flex items-center gap-1 rounded-lg border border-brand-700 bg-brand-800/60 px-2.5 py-1 text-xs font-medium text-white/80 hover:bg-brand-800"
                          >
                            {editing ? (
                              <ChevronDown className="h-3.5 w-3.5" />
                            ) : (
                              <ChevronRight className="h-3.5 w-3.5" />
                            )}
                            Permissions
                          </button>
                        ) : null}
                        {k.is_active ? (
                          <button
                            type="button"
                            onClick={() => void revoke(k)}
                            className="inline-flex items-center gap-1 rounded-lg border border-rose-500/40 bg-rose-500/10 px-2.5 py-1 text-xs font-medium text-rose-200 hover:bg-rose-500/20"
                          >
                            <Trash2 className="h-3.5 w-3.5" /> Révoquer
                          </button>
                        ) : null}
                      </div>
                    </div>

                    {editing && catalog ? (
                      <div className="border-t border-brand-800 px-4 py-3">
                        <p className="mb-2 text-xs text-white/50">
                          Active ou désactive ce que cette clé peut faire,
                          pôle par pôle. Les changements sont enregistrés
                          immédiatement.
                        </p>
                        <PolePermissions
                          catalog={catalog}
                          selected={selected}
                          onToggle={(scopeId) => void toggleKeyScope(k, scopeId)}
                          busyScope={busyScope}
                        />
                      </div>
                    ) : null}
                  </div>
                );
              })}
            </div>
          )}
        </section>
      </div>
    </>
  );
}
