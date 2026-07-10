"use client";

import {
  useEffect,
  useMemo,
  useState,
  type Dispatch,
  type SetStateAction
} from "react";
import {
  FileText,
  Loader2,
  Plus,
  Settings,
  Trash2,
  X
} from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { useDevlogLayout } from "../layout";
import { authedFetch } from "@/lib/auth";
import { useConfirm } from "@/components/confirm-dialog";
import { Link } from "@/i18n/navigation";

type Soumission = {
  id: number;
  reference: string;
  contact_request_id: number | null;
  client_id: number | null;
  title: string;
  description: string | null;
  subtotal: number | null;
  tps: number | null;
  tvq: number | null;
  total: number | null;
  status: string;
  sent_at: string | null;
  opened_at: string | null;
  accepted_at: string | null;
  valid_until: string | null;
  pdf_url: string | null;
  notes: string | null;
  property_address: string | null;
  kind?: "quote" | "contract";
  contract_data?: string | null;
  is_devis_dev?: boolean;
  created_at: string;
};

/** Prix estimé interne d'un contrat (contract_data JSON) — affiché
 *  dans la liste à la place du total, le contrat n'ayant pas d'items. */
function contractEstimate(s: Soumission): number | null {
  if (s.kind !== "contract" || !s.contract_data) return null;
  try {
    const cd = JSON.parse(s.contract_data) as { prix_estime?: unknown };
    const v = Number(cd.prix_estime);
    return Number.isFinite(v) && v > 0 ? v : null;
  } catch {
    return null;
  }
}

type Column = {
  id: string;
  label: string;
  dot: string;
  /** Colonne virtuelle : pas un statut DB, calculée côté front (ex.
   *  "En projet" = acceptees ayant un projet lié). Pas de drop. */
  virtual?: boolean;
};

// IDs alignés sur les valeurs backend DevlogSoumission.status (français).
// "en_projet" est une colonne virtuelle calculée côté frontend : la
// soumission est ``acceptee`` ET un DevlogProject existe pour elle.
const COLUMNS: Column[] = [
  { id: "brouillon", label: "Brouillons", dot: "bg-white/40" },
  { id: "envoyee", label: "Envoyées", dot: "bg-blue-400" },
  { id: "acceptee", label: "Acceptées", dot: "bg-emerald-400" },
  { id: "refusee", label: "Refusées", dot: "bg-rose-500" },
  { id: "expiree", label: "Expirées", dot: "bg-amber-400" },
  {
    id: "en_projet",
    label: "En projet",
    dot: "bg-violet-400",
    virtual: true
  }
];

function fmtMoney(n: number | null): string {
  if (n == null) return "—";
  return new Intl.NumberFormat("fr-CA", {
    style: "currency",
    currency: "CAD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2
  }).format(n);
}

export default function SoumissionsPage() {
  const confirm = useConfirm();
  const { onOpenSidebar } = useDevlogLayout();
  const [items, setItems] = useState<Soumission[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [dragging, setDragging] = useState<number | null>(null);
  const [hoverCol, setHoverCol] = useState<string | null>(null);
  // Phase 6 (juin 2026) : modale « Valeurs par défaut » des soumissions
  // devis_dev (taux, marges, commission closer, fonctionnalités par défaut
  // de chaque module, tâches du chargé de projet par défaut).
  const [showDefaults, setShowDefaults] = useState(false);

  // Fallback : somme des items par soumission. Utilisé quand le total
  // persisté en DB est null/0 (cas legacy ou items ajoutés sans
  // recalcul du total). Peuplé en 1 batch après le chargement de la
  // liste.
  const [itemsTotals, setItemsTotals] = useState<Record<number, number>>({});
  // Maps de résolution pour les cartes : nom du client (client_id →
  // name), prospect lié (contact_request_id → {name, address}), et
  // adresse du projet créé depuis la soumission (soumission_id →
  // address). Servent à afficher adresse + nom sur chaque carte,
  // qu'elle vise un client ou un prospect.
  const [clientNames, setClientNames] = useState<Map<number, string>>(
    new Map()
  );
  const [prospectById, setProspectById] = useState<
    Map<number, { name: string; address: string | null }>
  >(new Map());
  const [projectAddrBySoumission, setProjectAddrBySoumission] = useState<
    Map<number, string>
  >(new Map());

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const [res, clientsRes, projectsRes, prospectsRes] =
          await Promise.all([
            authedFetch("/api/v1/devlog/soumissions?limit=200"),
            authedFetch("/api/v1/devlog/clients?limit=500"),
            authedFetch("/api/v1/devlog/projects?limit=500"),
            authedFetch("/api/v1/devlog/leads?limit=500")
          ]);
        if (!res.ok) throw new Error(`http_${res.status}`);
        const data = (await res.json()) as Soumission[];
        if (cancelled) return;
        setItems(data);

        if (clientsRes.ok) {
          const cs = (await clientsRes.json()) as Array<{
            id: number;
            name: string;
          }>;
          if (!cancelled) {
            setClientNames(new Map(cs.map((c) => [c.id, c.name])));
          }
        }
        if (prospectsRes.ok) {
          const ps = (await prospectsRes.json()) as Array<{
            id: number;
            name: string;
            address: string | null;
          }>;
          if (!cancelled) {
            setProspectById(
              new Map(
                ps.map((p) => [
                  p.id,
                  { name: p.name, address: p.address }
                ])
              )
            );
          }
        }
        if (projectsRes.ok) {
          const ps = (await projectsRes.json()) as Array<{
            id: number;
            address: string | null;
            soumission_id: number | null;
          }>;
          if (!cancelled) {
            const m = new Map<number, string>();
            for (const p of ps) {
              if (p.soumission_id && p.address) m.set(p.soumission_id, p.address);
            }
            setProjectAddrBySoumission(m);
          }
        }

        const ids = data
          .filter(
            (s) =>
              s.kind !== "contract" &&
              !(Number(s.total) > 0) &&
              !(Number(s.subtotal) > 0)
          )
          .map((s) => s.id);
        if (ids.length > 0) {
          const r = await authedFetch(
            "/api/v1/devlog/soumissions/items-totals-unused",
            {
              method: "POST",
              body: JSON.stringify({ soumission_ids: ids })
            }
          );
          if (!cancelled && r.ok) {
            const j = (await r.json()) as {
              totals: Record<string, number>;
            };
            const map: Record<number, number> = {};
            for (const [k, v] of Object.entries(j.totals || {})) {
              const num = Number(v);
              if (Number.isFinite(num) && num > 0)
                map[Number(k)] = num;
            }
            setItemsTotals(map);
          }
        }
      } catch {
        if (!cancelled) setError("Impossible de charger les soumissions.");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, []);

  // Helper : montant à afficher pour une soumission. Pour un contrat,
  // c'est le prix estimé interne (pas d'items) ; pour un devis, total >
  // subtotal > somme des items.
  const amountFor = useMemo(() => {
    return (s: Soumission): number | null => {
      if (s.kind === "contract") return contractEstimate(s);
      if (Number(s.total) > 0) return Number(s.total);
      if (Number(s.subtotal) > 0) return Number(s.subtotal);
      const fallback = itemsTotals[s.id];
      if (Number.isFinite(fallback) && fallback > 0) return fallback;
      return null;
    };
  }, [itemsTotals]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return items;
    return items.filter(
      (s) =>
        s.title.toLowerCase().includes(q) ||
        s.reference.toLowerCase().includes(q) ||
        (s.description || "").toLowerCase().includes(q)
    );
  }, [items, search]);

  const byColumn = useMemo(() => {
    const map: Record<string, Soumission[]> = Object.fromEntries(
      COLUMNS.map((c) => [c.id, [] as Soumission[]])
    );
    for (const s of filtered) {
      // Colonne virtuelle "En projet" : soumission acceptée ET un
      // projet existe pour elle. Toutes les autres acceptées restent
      // dans "Acceptées" en attente de conversion.
      if (s.status === "acceptee" && projectAddrBySoumission.has(s.id)) {
        map["en_projet"].push(s);
        continue;
      }
      const target = COLUMNS.find((c) => c.id === s.status && !c.virtual)
        ? s.status
        : "brouillon";
      map[target].push(s);
    }
    return map;
  }, [filtered, projectAddrBySoumission]);

  async function moveSoumission(id: number, newStatus: string) {
    const prev = items;
    setItems((xs) => xs.map((x) => (x.id === id ? { ...x, status: newStatus } : x)));
    try {
      // Use the dedicated status endpoint so the CRM prospect card
      // moves in sync (quoted / won / lost) — even on reversals or
      // mistakes.
      const res = await authedFetch(
        `/api/v1/devlog/soumissions/${id}/status`,
        {
          method: "PATCH",
          body: JSON.stringify({ status: newStatus })
        }
      );
      if (!res.ok) throw new Error();
    } catch {
      setItems(prev);
      setError("Mise à jour échouée.");
    }
  }

  async function deleteSoumission(id: number, ref: string) {
    if (!(await confirm(`Supprimer la soumission ${ref} ?`))) return;
    const prev = items;
    setItems((xs) => xs.filter((x) => x.id !== id));
    try {
      const res = await authedFetch(`/api/v1/devlog/soumissions/${id}`, {
        method: "DELETE"
      });
      if (!res.ok) throw new Error();
    } catch {
      setItems(prev);
      setError("Suppression échouée.");
    }
  }

  return (
    <>
      <AppTopbar
        breadcrumbs={[{ label: "Développement logiciel", href: "/dev-logiciel" as any }, { label: "Soumissions" }]}
        onOpenSidebar={onOpenSidebar}
        onSearch={setSearch}
        searchPlaceholder="Rechercher une soumission…"
        rightSlot={
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => setShowDefaults(true)}
              title="Régler les valeurs par défaut des nouvelles soumissions"
              className="btn-secondary btn-sm"
            >
              <Settings className="mr-1.5 h-4 w-4" />
              Valeurs par défaut
            </button>
            <Link
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
              href={"/dev-logiciel/soumissions/new" as any}
              className="btn-accent"
            >
              <Plus className="mr-1.5 h-4 w-4" />
              Nouvelle soumission
            </Link>
          </div>
        }
      />

      {showDefaults ? (
        <SoumissionDefaultsModal onClose={() => setShowDefaults(false)} />
      ) : null}

      <div className="p-4 lg:p-6">
        {error ? (
          <p className="mb-4 rounded-lg border border-rose-500/40 bg-rose-500/10 px-4 py-2 text-sm text-rose-300">
            {error}
          </p>
        ) : null}

        {loading ? (
          <div className="flex min-h-[50vh] items-center justify-center">
            <Loader2 className="h-6 w-6 animate-spin text-accent-500" />
          </div>
        ) : items.length === 0 ? (
          <EmptyState />
        ) : (
          <div className="flex gap-4 overflow-x-auto pb-4">
            {COLUMNS.map((col) => {
              const cards = byColumn[col.id] || [];
              const isHover = hoverCol === col.id;
              return (
                <div
                  key={col.id}
                  onDragOver={(e) => {
                    if (col.virtual) return;
                    e.preventDefault();
                    setHoverCol(col.id);
                  }}
                  onDragLeave={() =>
                    setHoverCol((h) => (h === col.id ? null : h))
                  }
                  onDrop={() => {
                    if (col.virtual) {
                      setDragging(null);
                      setHoverCol(null);
                      return;
                    }
                    if (dragging == null) return;
                    const item = items.find((s) => s.id === dragging);
                    if (item && item.status !== col.id)
                      moveSoumission(dragging, col.id);
                    setDragging(null);
                    setHoverCol(null);
                  }}
                  className={`flex w-80 min-w-[320px] flex-shrink-0 flex-col rounded-xl border bg-brand-900/60 ${
                    isHover
                      ? "border-accent-500 bg-brand-900"
                      : "border-brand-800"
                  }`}
                >
                  <div className="flex items-center justify-between border-b border-brand-800 px-4 py-3">
                    <div className="flex items-center gap-2">
                      <span className={`h-2 w-2 rounded-full ${col.dot}`} />
                      <h2 className="text-sm font-semibold text-white">
                        {col.label}
                      </h2>
                      <span className="badge badge-neutral">
                        {cards.length}
                      </span>
                    </div>
                    <span className="text-xs font-semibold text-emerald-300">
                      {fmtMoney(
                        cards.reduce(
                          (sum, s) => sum + (amountFor(s) || 0),
                          0
                        )
                      )}
                    </span>
                  </div>

                  <div className="flex-1 space-y-3 p-3">
                    {cards.length === 0 ? (
                      <p className="py-8 text-center text-xs text-white/40">
                        Aucune soumission
                      </p>
                    ) : (
                      cards.map((s) => {
                        const prospect = s.contact_request_id
                          ? prospectById.get(s.contact_request_id)
                          : undefined;
                        return (
                        <SoumissionCard
                          key={s.id}
                          soumission={s}
                          amount={amountFor(s)}
                          clientName={
                            (s.client_id
                              ? clientNames.get(s.client_id)
                              : undefined) ??
                            prospect?.name ??
                            null
                          }
                          projectAddress={
                            projectAddrBySoumission.get(s.id) ??
                            prospect?.address ??
                            null
                          }
                          dragging={dragging === s.id}
                          onDragStart={() => setDragging(s.id)}
                          onDragEnd={() => {
                            setDragging(null);
                            setHoverCol(null);
                          }}
                          onDelete={() => deleteSoumission(s.id, s.reference)}
                        />
                        );
                      })
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </>
  );
}

function SoumissionCard({
  soumission: s,
  amount,
  clientName,
  projectAddress,
  dragging,
  onDragStart,
  onDragEnd,
  onDelete
}: {
  soumission: Soumission;
  amount: number | null;
  clientName: string | null;
  projectAddress: string | null;
  dragging: boolean;
  onDragStart: () => void;
  onDragEnd: () => void;
  onDelete: () => void;
}) {
  return (
    <div
      draggable
      onDragStart={onDragStart}
      onDragEnd={onDragEnd}
      className={`group relative cursor-grab rounded-lg border border-brand-800 bg-brand-950 p-3 transition hover:border-accent-500 active:cursor-grabbing ${
        dragging ? "opacity-40" : ""
      }`}
    >
      <button
        type="button"
        onClick={(e) => {
          e.preventDefault();
          e.stopPropagation();
          onDelete();
        }}
        aria-label="Supprimer"
        className="btn-ghost btn-xs absolute right-2 top-2 opacity-0 group-hover:opacity-100"
      >
        <Trash2 className="h-3.5 w-3.5" />
      </button>

      <Link
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        href={`/dev-logiciel/soumissions/${s.id}` as any}
        className="block pr-6"
      >
        {/* Adresse du chantier (top) — toujours affichée, même pour
            un contrat ; fallback à l'adresse du projet puis au titre. */}
        <p className="line-clamp-2 text-sm font-semibold text-white">
          {s.property_address || projectAddress || s.title}
        </p>
        {/* Nom du client (sous-titre) — taille bumpée pour
            lecture plus rapide. */}
        {clientName ? (
          <p className="mt-1 truncate text-xs font-medium text-white/75">
            {clientName}
          </p>
        ) : null}
        {/* Montant : total du devis, ou prix estimé interne pour un
            contrat. */}
        <p className="mt-2 text-sm font-bold text-white">
          {fmtMoney(amount)}
          {s.kind === "contract" ? (
            <span className="ml-1.5 text-[10px] font-semibold uppercase tracking-wider text-white/40">
              estimé
            </span>
          ) : null}
        </p>
        {/* Accusé de lecture : le client a-t-il ouvert le lien public ? */}
        {s.opened_at ? (
          <p className="mt-1 inline-flex items-center gap-1 text-[11px] font-medium text-violet-300">
            <span className="h-1.5 w-1.5 rounded-full bg-violet-400" />
            Ouverte par le client
          </p>
        ) : s.sent_at ? (
          <p className="mt-1 inline-flex items-center gap-1 text-[11px] font-medium text-white/35">
            <span className="h-1.5 w-1.5 rounded-full bg-white/25" />
            Pas encore ouverte
          </p>
        ) : null}
        {/* Numéro de la soumission, en bas — bumpé en text-xs pour
            la lisibilité. */}
        <div className="mt-1.5 flex items-center justify-between">
          <span className="text-xs font-semibold uppercase tracking-wider text-accent-500">
            {s.reference}
            {s.kind === "contract" ? (
              <span className="badge badge-violet ml-1.5">
                Contrat
              </span>
            ) : null}
            {s.kind !== "contract" && s.is_devis_dev === false ? (
              <span className="badge badge-amber ml-1.5">
                Ancien format
              </span>
            ) : null}
          </span>
          <span className="text-[10px] text-white/40">
            {new Date(s.created_at).toLocaleDateString("fr-CA", {
              month: "short",
              day: "2-digit"
            })}
          </span>
        </div>
      </Link>
    </div>
  );
}

function EmptyState() {
  return (
    <div className="empty-state mx-auto mt-16 max-w-md">
      <FileText className="mx-auto h-10 w-10 text-accent-500" />
      <h2 className="mt-4 text-lg font-semibold text-white">
        Aucune soumission
      </h2>
      <p className="mt-2 text-sm text-white/60">
        Créez votre première soumission pour un prospect ou un client existant.
      </p>
      <Link
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        href={"/dev-logiciel/soumissions/new" as any}
        className="btn-accent mt-6"
      >
        <Plus className="mr-1.5 h-4 w-4" />
        Nouvelle soumission
      </Link>
    </div>
  );
}

// ── Phase 6 (juin 2026) : modale « Valeurs par défaut » ────────────────
// Phil règle ici, sans toucher au code, les défauts appliqués à CHAQUE
// nouvelle soumission devis_dev : taux dev/manager, commission closer,
// marges, les fonctionnalités par défaut (pré-remplies à chaque nouveau
// module) et les tâches du chargé de projet par défaut (pré-remplies à
// chaque nouvelle soumission).

// Une ligne par defaut (description + heures) : sert a la fois aux
// fonctionnalites par defaut (chaque nouveau module) et aux taches du
// charge de projet par defaut (chaque nouvelle soumission).
type DefaultsLine = { description: string; heures: number };
type DefaultsPayload = {
  taux_dev_horaire: number | null;
  taux_manager_horaire: number | null;
  commission_closer_pct: number | null;
  marge_initiale_pct: number | null;
  marge_recurrente_pct: number | null;
  default_features_json: DefaultsLine[] | null;
  default_manager_tasks_json: DefaultsLine[] | null;
};

function NumberField({
  label,
  suffix,
  value,
  onChange
}: {
  label: string;
  suffix: string;
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-medium text-white/60">
        {label}
      </span>
      <div className="flex items-center gap-2">
        <input
          type="number"
          min={0}
          step="0.01"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className="w-full rounded-lg border border-white/10 bg-brand-950/60 px-3 py-2 text-sm text-white outline-none focus:border-accent-500"
        />
        <span className="text-xs text-white/40">{suffix}</span>
      </div>
    </label>
  );
}

// Editeur generique d'une liste de lignes {description, heures} avec
// ajouter / editer / retirer. Utilise pour les deux nouvelles sections
// (fonctionnalites par defaut + taches du charge de projet par defaut).
function LineListEditor({
  title,
  hint,
  addLabel,
  placeholder,
  emptyLabel,
  lines,
  onAdd,
  onRemove,
  onChange
}: {
  title: string;
  hint: string;
  addLabel: string;
  placeholder: string;
  emptyLabel: string;
  lines: DefaultsLine[];
  onAdd: () => void;
  onRemove: (idx: number) => void;
  onChange: (idx: number, field: "description" | "heures", value: string) => void;
}) {
  return (
    <div>
      <div className="mb-2 flex items-center justify-between">
        <h3 className="text-sm font-semibold text-white">{title}</h3>
        <button
          type="button"
          onClick={onAdd}
          className="btn-secondary btn-sm"
        >
          <Plus className="mr-1 h-3.5 w-3.5" />
          {addLabel}
        </button>
      </div>
      <p className="mb-3 text-xs text-white/40">{hint}</p>
      {lines.length === 0 ? (
        <p className="rounded-lg border border-dashed border-white/10 px-3 py-4 text-center text-xs text-white/40">
          {emptyLabel}
        </p>
      ) : (
        <div className="space-y-2">
          {lines.map((line, idx) => (
            <div key={idx} className="flex items-center gap-2">
              <input
                type="text"
                placeholder={placeholder}
                value={line.description}
                onChange={(e) => onChange(idx, "description", e.target.value)}
                className="w-full rounded-lg border border-white/10 bg-brand-950/60 px-2.5 py-1.5 text-xs text-white outline-none focus:border-accent-500"
              />
              <input
                type="number"
                min={0}
                step="0.5"
                placeholder="h"
                value={line.heures}
                onChange={(e) => onChange(idx, "heures", e.target.value)}
                className="w-20 rounded-lg border border-white/10 bg-brand-950/60 px-2 py-1.5 text-xs text-white outline-none focus:border-accent-500"
              />
              <span className="text-[10px] text-white/40">h</span>
              <button
                type="button"
                onClick={() => onRemove(idx)}
                className="btn-ghost btn-xs"
              >
                <X className="h-3.5 w-3.5" />
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function SoumissionDefaultsModal({ onClose }: { onClose: () => void }) {
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  const [tauxDev, setTauxDev] = useState("");
  const [tauxManager, setTauxManager] = useState("");
  const [closer, setCloser] = useState("");
  const [margeInit, setMargeInit] = useState("");
  const [margeRec, setMargeRec] = useState("");
  // Fonctionnalites par defaut : pre-remplissent CHAQUE nouveau module.
  const [features, setFeatures] = useState<DefaultsLine[]>([]);
  // Taches du charge de projet par defaut : pre-remplies a CHAQUE nouvelle
  // soumission dans le bloc « Gestionnaire de projet ».
  const [managerTasks, setManagerTasks] = useState<DefaultsLine[]>([]);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const res = await authedFetch("/api/v1/devlog/soumission-defaults");
        if (!res.ok) throw new Error(`http_${res.status}`);
        const d = (await res.json()) as DefaultsPayload;
        if (cancelled) return;
        setTauxDev(String(d.taux_dev_horaire ?? 75));
        setTauxManager(String(d.taux_manager_horaire ?? 80));
        setCloser(String(d.commission_closer_pct ?? 10));
        setMargeInit(String(d.marge_initiale_pct ?? 50));
        setMargeRec(String(d.marge_recurrente_pct ?? 50));
        setFeatures(
          (d.default_features_json ?? []).map((f) => ({
            description: f.description ?? "",
            heures: Number(f.heures) || 0
          }))
        );
        setManagerTasks(
          (d.default_manager_tasks_json ?? []).map((t) => ({
            description: t.description ?? "",
            heures: Number(t.heures) || 0
          }))
        );
      } catch (err) {
        if (!cancelled)
          setError(
            `Chargement échoué : ${(err as Error).message || "erreur"}`
          );
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, []);

  // Fabrique des handlers ajouter/retirer/editer pour une liste de lignes.
  function makeLineHandlers(
    setter: Dispatch<SetStateAction<DefaultsLine[]>>
  ) {
    return {
      add: () =>
        setter((xs) => [...xs, { description: "", heures: 0 }]),
      remove: (idx: number) =>
        setter((xs) => xs.filter((_, i) => i !== idx)),
      change: (idx: number, field: "description" | "heures", value: string) =>
        setter((xs) =>
          xs.map((x, i) =>
            i === idx
              ? {
                  ...x,
                  [field]:
                    field === "heures" ? Number(value) || 0 : value
                }
              : x
          )
        )
    };
  }
  const featureHandlers = makeLineHandlers(setFeatures);
  const taskHandlers = makeLineHandlers(setManagerTasks);

  async function onSave() {
    setSaving(true);
    setError(null);
    setSaved(false);
    try {
      // Nettoie les listes : on ne garde que les lignes avec une description
      // (le backend valide aussi min_length=1 + heures>=0).
      const cleanLines = (lines: DefaultsLine[]) =>
        lines
          .filter((l) => l.description.trim())
          .map((l) => ({
            description: l.description.trim(),
            heures: Number(l.heures) || 0
          }));
      const payload = {
        taux_dev_horaire: Number(tauxDev),
        taux_manager_horaire: Number(tauxManager),
        commission_closer_pct: Number(closer),
        marge_initiale_pct: Number(margeInit),
        marge_recurrente_pct: Number(margeRec),
        default_features_json: cleanLines(features),
        default_manager_tasks_json: cleanLines(managerTasks)
      };
      const res = await authedFetch("/api/v1/devlog/soumission-defaults", {
        method: "PUT",
        body: JSON.stringify(payload)
      });
      if (!res.ok) {
        const text = await res.text().catch(() => "");
        throw new Error(text.slice(0, 200) || `http_${res.status}`);
      }
      setSaved(true);
    } catch (err) {
      setError(`Sauvegarde échouée : ${(err as Error).message || "erreur"}`);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/60 p-4 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="my-8 w-full max-w-2xl rounded-2xl border border-brand-800 bg-brand-900 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-white/10 px-6 py-4">
          <div className="flex items-center gap-2">
            <Settings className="h-5 w-5 text-accent-500" />
            <h2 className="text-base font-semibold text-white">
              Valeurs par défaut des soumissions
            </h2>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="btn-ghost btn-xs"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {loading ? (
          <div className="flex min-h-[200px] items-center justify-center">
            <Loader2 className="h-6 w-6 animate-spin text-accent-500" />
          </div>
        ) : (
          <div className="space-y-6 px-6 py-5">
            <p className="text-xs text-white/50">
              Ces valeurs s&apos;appliquent à chaque{" "}
              <strong className="text-white/70">nouvelle</strong> soumission
              devis. Les soumissions existantes ne sont pas modifiées.
            </p>

            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <NumberField
                label="Taux horaire développeur"
                suffix="$/h"
                value={tauxDev}
                onChange={setTauxDev}
              />
              <NumberField
                label="Taux horaire chargé de projet"
                suffix="$/h"
                value={tauxManager}
                onChange={setTauxManager}
              />
              <NumberField
                label="Commission closer"
                suffix="%"
                value={closer}
                onChange={setCloser}
              />
              <NumberField
                label="Marge initiale (mise en oeuvre)"
                suffix="%"
                value={margeInit}
                onChange={setMargeInit}
              />
              <NumberField
                label="Marge récurrente (mensuel)"
                suffix="%"
                value={margeRec}
                onChange={setMargeRec}
              />
            </div>

            <LineListEditor
              title="Fonctionnalités par défaut (à chaque nouveau module)"
              hint="Chaque fois que vous ajoutez un module dans une soumission, ces fonctionnalités y sont pré-remplies (modifiables et supprimables ensuite). Laissez vide pour des modules vides."
              addLabel="Ajouter une fonctionnalité"
              placeholder="Fonctionnalité"
              emptyLabel="Aucune fonctionnalité par défaut."
              lines={features}
              onAdd={featureHandlers.add}
              onRemove={featureHandlers.remove}
              onChange={featureHandlers.change}
            />

            <LineListEditor
              title="Tâches du chargé de projet par défaut"
              hint="Ces tâches sont créées automatiquement dans le bloc « Gestionnaire de projet » à chaque nouvelle soumission. Laissez vide pour ne rien ajouter."
              addLabel="Ajouter une tâche"
              placeholder="Tâche du chargé de projet"
              emptyLabel="Aucune tâche par défaut."
              lines={managerTasks}
              onAdd={taskHandlers.add}
              onRemove={taskHandlers.remove}
              onChange={taskHandlers.change}
            />

            {error ? (
              <p className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-300">
                {error}
              </p>
            ) : null}
            {saved ? (
              <p className="rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-sm text-emerald-300">
                Valeurs par défaut enregistrées.
              </p>
            ) : null}
          </div>
        )}

        <div className="flex items-center justify-end gap-2 border-t border-white/10 px-6 py-4">
          <button
            type="button"
            onClick={onClose}
            className="btn-ghost btn-sm"
          >
            Fermer
          </button>
          <button
            type="button"
            onClick={onSave}
            disabled={saving || loading}
            className="btn-accent btn-sm disabled:opacity-50"
          >
            {saving ? (
              <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />
            ) : null}
            Enregistrer
          </button>
        </div>
      </div>
    </div>
  );
}
