"use client";

import { useEffect, useMemo, useState } from "react";
import {
  ChevronLeft,
  Filter,
  Loader2,
  ScrollText,
  Search
} from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { Link } from "@/i18n/navigation";
import { useAppLayout } from "../../layout";
import { authedFetch } from "@/lib/auth";

/**
 * Page « Journal d'activité » — admin+ uniquement.
 *
 * Consulte la table `audit_logs` : qui a créé / modifié / supprimé
 * quoi et quand. Filtres : type d'entité, action, courriel user,
 * id d'entité, limite.
 */

type AuditEntry = {
  id: number;
  user_id: number | null;
  user_email: string | null;
  action: string;
  entity_type: string | null;
  entity_id: number | null;
  details_json: string | null;
  created_at: string;
};

const ENTITY_LABELS: Record<string, string> = {
  punch: "Punch",
  soumissions: "Soumission",
  factures: "Facture",
  "purchase-orders": "PO",
  achats: "Achat",
  employes: "Employé",
  fournisseurs: "Fournisseur",
  "sous-traitants": "Sous-traitant",
  bons: "Bon de travail",
  punches: "Punch (CRUD)",
  projects: "Projet"
};

function fmtDateTime(iso: string): string {
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

function actionPillCls(action: string): string {
  if (action.endsWith(".deleted") || action.endsWith(".rejected")) {
    return "bg-rose-500/15 text-rose-300 border-rose-500/30";
  }
  if (action.endsWith(".created") || action.endsWith(".clock_in")) {
    return "bg-emerald-500/15 text-emerald-300 border-emerald-500/30";
  }
  if (action.endsWith(".approved") || action.endsWith(".clock_out")) {
    return "bg-sky-500/15 text-sky-300 border-sky-500/30";
  }
  if (action.endsWith(".auto_closed")) {
    return "bg-amber-500/15 text-amber-300 border-amber-500/30";
  }
  return "bg-white/10 text-white/70 border-white/20";
}

export default function AuditPage() {
  const { onOpenSidebar } = useAppLayout();
  const [rows, setRows] = useState<AuditEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Filtres
  const [entityType, setEntityType] = useState("");
  const [action, setAction] = useState("");
  const [userEmail, setUserEmail] = useState("");
  const [entityId, setEntityId] = useState("");
  const [limit, setLimit] = useState(100);
  const [search, setSearch] = useState("");

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const qs = new URLSearchParams();
      if (entityType) qs.set("entity_type", entityType);
      if (action) qs.set("action", action);
      if (userEmail) qs.set("user_email", userEmail);
      if (entityId) qs.set("entity_id", entityId);
      qs.set("limit", String(limit));
      const r = await authedFetch(`/api/v1/audit?${qs.toString()}`);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      setRows((await r.json()) as AuditEntry[]);
    } catch (e) {
      setError("Chargement échoué : " + (e as Error).message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return rows;
    return rows.filter(
      (r) =>
        r.action.toLowerCase().includes(q) ||
        (r.user_email || "").toLowerCase().includes(q) ||
        (r.entity_type || "").toLowerCase().includes(q) ||
        (r.details_json || "").toLowerCase().includes(q) ||
        String(r.entity_id || "").includes(q)
    );
  }, [rows, search]);

  return (
    <>
      <AppTopbar
        breadcrumbs={[
          { label: "Construction", href: "/app" },
          { label: "Paramètres", href: "/app/parametres" },
          { label: "Journal d'activité" }
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
          <ScrollText className="h-6 w-6 text-accent-500" />
          Journal d&apos;activité
        </h1>
        <p className="mt-1 text-sm text-white/60">
          Trace exhaustive des créations, suppressions et opérations
          sensibles. Admin uniquement.
        </p>

        {/* Filtres */}
        <div className="mt-5 grid grid-cols-1 gap-3 rounded-xl border border-brand-800 bg-brand-900 p-4 sm:grid-cols-2 lg:grid-cols-5">
          <div>
            <label className="label text-[10px] uppercase">
              Type d&apos;entité
            </label>
            <select
              className="input"
              value={entityType}
              onChange={(e) => setEntityType(e.target.value)}
            >
              <option value="">Tous</option>
              {Object.entries(ENTITY_LABELS).map(([k, v]) => (
                <option key={k} value={k}>
                  {v}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="label text-[10px] uppercase">Action</label>
            <input
              className="input"
              value={action}
              onChange={(e) => setAction(e.target.value)}
              placeholder="ex. punch.rejected"
            />
          </div>
          <div>
            <label className="label text-[10px] uppercase">User</label>
            <input
              className="input"
              value={userEmail}
              onChange={(e) => setUserEmail(e.target.value)}
              placeholder="email@exemple.com"
            />
          </div>
          <div>
            <label className="label text-[10px] uppercase">
              ID entité
            </label>
            <input
              className="input"
              value={entityId}
              onChange={(e) => setEntityId(e.target.value)}
              placeholder="42"
              type="number"
            />
          </div>
          <div className="flex items-end gap-2">
            <button
              type="button"
              onClick={() => void load()}
              className="btn-accent flex-1 text-sm"
            >
              <Filter className="mr-1 h-3.5 w-3.5" />
              Appliquer
            </button>
          </div>
        </div>

        {/* Search local */}
        <div className="relative mt-4 max-w-md">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-white/40" />
          <input
            type="search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Recherche dans les résultats…"
            className="input pl-8"
          />
        </div>

        {error ? (
          <p className="mt-4 rounded-lg border border-rose-500/40 bg-rose-500/10 px-4 py-2 text-sm text-rose-300">
            {error}
          </p>
        ) : null}

        {loading ? (
          <div className="mt-8 flex items-center justify-center">
            <Loader2 className="h-6 w-6 animate-spin text-accent-500" />
          </div>
        ) : filtered.length === 0 ? (
          <div className="mt-8 rounded-2xl border border-dashed border-brand-800 bg-brand-900/40 px-6 py-14 text-center">
            <ScrollText className="mx-auto h-8 w-8 text-white/30" />
            <p className="mt-3 text-sm text-white/60">
              Aucune entrée d&apos;audit. Si tu viens d&apos;activer le
              journal, les premières entrées apparaîtront dès la
              prochaine action mutative.
            </p>
          </div>
        ) : (
          <div className="mt-4 overflow-hidden rounded-xl border border-brand-800 bg-brand-900">
            <table className="w-full text-sm">
              <thead className="border-b border-brand-800 bg-brand-950/50 text-left text-[11px] uppercase tracking-wider text-white/50">
                <tr>
                  <th className="px-3 py-2">Date</th>
                  <th className="px-3 py-2">User</th>
                  <th className="px-3 py-2">Action</th>
                  <th className="px-3 py-2">Entité</th>
                  <th className="px-3 py-2">Détails</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-brand-800">
                {filtered.map((r) => {
                  let detailsObj: Record<string, unknown> | null = null;
                  try {
                    detailsObj = r.details_json
                      ? (JSON.parse(r.details_json) as Record<
                          string,
                          unknown
                        >)
                      : null;
                  } catch {
                    detailsObj = null;
                  }
                  return (
                    <tr key={r.id} className="hover:bg-brand-800/30">
                      <td className="px-3 py-2 whitespace-nowrap text-white/70">
                        {fmtDateTime(r.created_at)}
                      </td>
                      <td className="px-3 py-2 text-white/80">
                        {r.user_email || (
                          <span className="text-white/40 italic">
                            système
                          </span>
                        )}
                      </td>
                      <td className="px-3 py-2">
                        <span
                          className={`rounded-full border px-2 py-0.5 text-[10px] font-semibold ${actionPillCls(
                            r.action
                          )}`}
                        >
                          {r.action}
                        </span>
                      </td>
                      <td className="px-3 py-2 text-white/70">
                        {r.entity_type ? (
                          <>
                            {ENTITY_LABELS[r.entity_type] || r.entity_type}
                            {r.entity_id != null ? (
                              <span className="ml-1 font-mono text-white/40">
                                #{r.entity_id}
                              </span>
                            ) : null}
                          </>
                        ) : (
                          "—"
                        )}
                      </td>
                      <td className="px-3 py-2 text-[11px] text-white/60">
                        {detailsObj ? (
                          <div className="flex flex-wrap gap-x-3 gap-y-0.5">
                            {Object.entries(detailsObj)
                              .filter(
                                ([, v]) =>
                                  v != null && v !== "" && v !== false
                              )
                              .slice(0, 6)
                              .map(([k, v]) => (
                                <span key={k}>
                                  <span className="text-white/40">
                                    {k}:
                                  </span>{" "}
                                  <span className="font-mono">
                                    {String(v).slice(0, 60)}
                                  </span>
                                </span>
                              ))}
                          </div>
                        ) : (
                          <span className="text-white/30">—</span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            <div className="border-t border-brand-800 bg-brand-950/30 px-3 py-2 text-[11px] text-white/40">
              {filtered.length} entrée{filtered.length > 1 ? "s" : ""} ·
              Limite : {limit} ·{" "}
              <button
                type="button"
                className="text-accent-400 hover:underline"
                onClick={() => {
                  setLimit(limit + 100);
                  void load();
                }}
              >
                Charger 100 de plus
              </button>
            </div>
          </div>
        )}
      </div>
    </>
  );
}
