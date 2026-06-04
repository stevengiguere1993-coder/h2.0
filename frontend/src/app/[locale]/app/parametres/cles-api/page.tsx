"use client";

import { useCallback, useEffect, useState } from "react";
import {
  AlertCircle,
  Check,
  ChevronLeft,
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
 * Page « Clés API » — chaque utilisateur gère SES propres clés.
 *
 * S'appuie sur les endpoints livrés en PR #685 :
 *   POST   /api/v1/api-keys        → génère une clé (secret en clair UNE fois)
 *   GET    /api/v1/api-keys        → liste mes clés (jamais le secret)
 *   DELETE /api/v1/api-keys/{id}   → révoque une clé
 *
 * Le secret `krts_…` n'est jamais stocké en clair côté serveur : il
 * n'apparaît qu'une seule fois, à la création, dans l'encadré de copie.
 */

type ApiKey = {
  id: number;
  key_prefix: string;
  label: string | null;
  is_active: boolean;
  created_at: string;
  last_used_at: string | null;
  expires_at: string | null;
};

type ApiKeyCreated = ApiKey & {
  api_key: string;
  warning: string;
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

export default function ClesApiPage() {
  const { onOpenSidebar } = useAppLayout();
  const confirm = useConfirm();

  const [keys, setKeys] = useState<ApiKey[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Formulaire de génération
  const [showForm, setShowForm] = useState(false);
  const [label, setLabel] = useState("");
  const [creating, setCreating] = useState(false);

  // Clé fraîchement créée — affichée UNE seule fois.
  const [freshKey, setFreshKey] = useState<ApiKeyCreated | null>(null);
  const [copied, setCopied] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await authedFetch("/api/v1/api-keys");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setKeys((await res.json()) as ApiKey[]);
    } catch (e) {
      setError("Chargement des clés échoué : " + (e as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function createKey() {
    setCreating(true);
    setError(null);
    try {
      const res = await authedFetch("/api/v1/api-keys", {
        method: "POST",
        body: JSON.stringify({ label: label.trim() || null })
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
      // Recharge la liste pour faire apparaître la nouvelle ligne.
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
          Une clé API permet à tes assistants Claude (ou autres outils) de
          lire ton activité Kratos en lecture seule. Garde-la secrète —
          quiconque la possède peut consulter tes données.
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
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && !creating) void createKey();
                  }}
                />
                <p className="mt-1 text-xs text-white/50">
                  Un nom te permet de reconnaître la clé plus tard (ex. quel
                  outil l&apos;utilise).
                </p>
              </div>
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
                connecter un assistant en lecture seule.
              </p>
            </div>
          ) : (
            <div className="mt-4 overflow-x-auto rounded-xl border border-brand-800 bg-brand-900">
              <table className="w-full min-w-[680px] text-sm">
                <thead className="border-b border-brand-800 bg-brand-950/50 text-left text-[11px] uppercase tracking-wider text-white/50">
                  <tr>
                    <th className="px-3 py-2">Libellé</th>
                    <th className="px-3 py-2">Préfixe</th>
                    <th className="px-3 py-2">Créée le</th>
                    <th className="px-3 py-2">Dernière utilisation</th>
                    <th className="px-3 py-2">Statut</th>
                    <th className="px-3 py-2 text-right">Action</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-brand-800">
                  {keys.map((k) => (
                    <tr
                      key={k.id}
                      className={
                        k.is_active
                          ? "hover:bg-brand-800/30"
                          : "opacity-50"
                      }
                    >
                      <td className="px-3 py-2 text-white/90">
                        {k.label || (
                          <span className="text-white/40 italic">
                            Sans libellé
                          </span>
                        )}
                      </td>
                      <td className="px-3 py-2">
                        <code className="font-mono text-white/70">
                          {k.key_prefix}…
                        </code>
                      </td>
                      <td className="px-3 py-2 whitespace-nowrap text-white/70">
                        {fmtDate(k.created_at)}
                      </td>
                      <td className="px-3 py-2 whitespace-nowrap text-white/70">
                        {k.last_used_at ? (
                          fmtDate(k.last_used_at)
                        ) : (
                          <span className="text-white/40">Jamais</span>
                        )}
                      </td>
                      <td className="px-3 py-2">
                        {k.is_active ? (
                          <span className="rounded-full border border-emerald-500/30 bg-emerald-500/15 px-2 py-0.5 text-[10px] font-semibold text-emerald-300">
                            Active
                          </span>
                        ) : (
                          <span className="rounded-full border border-white/20 bg-white/10 px-2 py-0.5 text-[10px] font-semibold text-white/50">
                            Révoquée
                          </span>
                        )}
                      </td>
                      <td className="px-3 py-2 text-right">
                        {k.is_active ? (
                          <button
                            type="button"
                            onClick={() => void revoke(k)}
                            className="inline-flex items-center gap-1 rounded-lg border border-rose-500/40 bg-rose-500/10 px-2.5 py-1 text-xs font-medium text-rose-200 hover:bg-rose-500/20"
                          >
                            <Trash2 className="h-3.5 w-3.5" /> Révoquer
                          </button>
                        ) : (
                          <span className="text-xs text-white/30">—</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      </div>
    </>
  );
}
