"use client";

import { useEffect, useMemo, useState } from "react";
import { CheckCircle2, Loader2, Plus, ShoppingCart } from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { useAppLayout } from "../layout";
import { authedFetch } from "@/lib/auth";
import { Link } from "@/i18n/navigation";

type Achat = {
  id: number;
  reference: string;
  fournisseur_id: number | null;
  project_id: number | null;
  description: string | null;
  amount: number | string | null;
  amount_taxes: number | string | null;
  status: string;
  ordered_at: string | null;
  received_at: string | null;
  paid_at: string | null;
  due_at: string | null;
  payment_method: string | null;
  receipt_url: string | null;
  notes: string | null;
  is_billable?: boolean;
  markup_percent?: number | null;
  invoiced_at?: string | null;
  created_at: string;
};

const PAYMENT_METHOD_LABELS: Record<string, string> = {
  bill_to_pay: "Facture à payer (net-30)",
  cheque_horizon: "Chèque Horizon",
  cc_steven: "CC Steven Giguère",
  cc_michael: "CC Michael Villiard",
  cc_olivier: "CC Olivier Therrien",
  cc_christian: "CC Christian Villiard"
};

// Options reelles de paiement (exclut bill_to_pay qui signifie
// « pas encore paye »).
const REAL_PAYMENT_METHODS: { value: string; label: string }[] = [
  { value: "cheque_horizon", label: "Chèque Horizon" },
  { value: "cc_steven", label: "CC Steven Giguère" },
  { value: "cc_michael", label: "CC Michael Villiard" },
  { value: "cc_olivier", label: "CC Olivier Therrien" },
  { value: "cc_christian", label: "CC Christian Villiard" }
];

function daysBetween(a: Date, b: Date): number {
  const ms = a.getTime() - b.getTime();
  return Math.floor(ms / 86_400_000);
}

type Project = { id: number; name: string };
type Fournisseur = { id: number; name: string };

const STATUS_LABELS: Record<string, string> = {
  received: "Reçu",
  paid: "Payé",
  cancelled: "Annulé"
};

const STATUS_CLASS: Record<string, string> = {
  received: "bg-amber-500/20 text-amber-300",
  paid: "bg-emerald-500/20 text-emerald-300",
  cancelled: "bg-white/5 text-white/50"
};

function fmtMoney(n: number | string | null): string {
  if (n == null || n === "") return "—";
  const num = typeof n === "string" ? Number(n) : n;
  return new Intl.NumberFormat("fr-CA", {
    style: "currency",
    currency: "CAD",
    maximumFractionDigits: 2
  }).format(num);
}

function fmtDate(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("fr-CA", {
    day: "2-digit",
    month: "short"
  });
}

export default function AchatsPage() {
  const { onOpenSidebar } = useAppLayout();
  const [items, setItems] = useState<Achat[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [fournisseurs, setFournisseurs] = useState<Fournisseur[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [fStatus, setFStatus] = useState("");
  const [fProject, setFProject] = useState("");
  const [fFournisseur, setFFournisseur] = useState("");
  const [payTarget, setPayTarget] = useState<Achat | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const [aRes, pRes, frRes] = await Promise.all([
          authedFetch("/api/v1/achats?limit=500"),
          authedFetch("/api/v1/projects?limit=500"),
          authedFetch("/api/v1/fournisseurs?limit=500")
        ]);
        if (!aRes.ok) throw new Error(`http_${aRes.status}`);
        const as = (await aRes.json()) as Achat[];
        const ps = pRes.ok ? ((await pRes.json()) as Project[]) : [];
        const frs = frRes.ok ? ((await frRes.json()) as Fournisseur[]) : [];
        if (cancelled) return;
        setItems(as);
        setProjects(ps);
        setFournisseurs(frs);
      } catch {
        if (!cancelled) setError("Impossible de charger les achats.");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, []);

  const projById = useMemo(() => {
    const m = new Map<number, Project>();
    projects.forEach((p) => m.set(p.id, p));
    return m;
  }, [projects]);
  const frById = useMemo(() => {
    const m = new Map<number, Fournisseur>();
    fournisseurs.forEach((f) => m.set(f.id, f));
    return m;
  }, [fournisseurs]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    const list = items.filter((a) => {
      if (fStatus && a.status !== fStatus) return false;
      if (fProject && String(a.project_id || "") !== fProject) return false;
      if (fFournisseur && String(a.fournisseur_id || "") !== fFournisseur)
        return false;
      if (
        q &&
        !a.reference.toLowerCase().includes(q) &&
        !(a.description || "").toLowerCase().includes(q)
      )
        return false;
      return true;
    });
    // Sur l'onglet "A payer" on trie par echeance ascendante : les
    // en retard remontent en premier, ensuite les plus proches.
    if (fStatus === "received") {
      list.sort((a, b) => {
        const ax = a.due_at ? new Date(a.due_at).getTime() : Infinity;
        const bx = b.due_at ? new Date(b.due_at).getTime() : Infinity;
        return ax - bx;
      });
    }
    return list;
  }, [items, search, fStatus, fProject, fFournisseur]);

  const total = useMemo(
    () =>
      filtered.reduce(
        (sum, a) =>
          sum +
          (a.amount != null ? Number(a.amount) : 0) +
          (a.amount_taxes != null ? Number(a.amount_taxes) : 0),
        0
      ),
    [filtered]
  );

  return (
    <>
      <AppTopbar
        breadcrumbs={[{ label: "Construction", href: "/app" }, { label: "Achats / dépenses" }]}
        onOpenSidebar={onOpenSidebar}
        onSearch={setSearch}
        searchPlaceholder="Référence, description…"
        rightSlot={
          <Link
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            href={"/app/achats/new" as any}
            className="btn-accent text-sm"
          >
            <Plus className="mr-1.5 h-4 w-4" /> Nouvel achat
          </Link>
        }
      />

      <div className="p-4 lg:p-6">
        {error ? (
          <p className="mb-4 rounded-lg border border-rose-500/40 bg-rose-500/10 px-4 py-2 text-sm text-rose-300">
            {error}
          </p>
        ) : null}

        {/* Onglets rapides par statut — reflètent le cycle de vie
            Planifié → PO envoyé → Reçu. Le sélecteur du dessous
            permet de filtrer plus finement ou de tout afficher. */}
        <div className="mb-3 flex flex-wrap gap-1 border-b border-brand-800">
          {(
            [
              { value: "", label: "Tous" },
              { value: "received", label: "Reçus / à payer" },
              { value: "paid", label: "Payés" }
            ] as const
          ).map((tab) => {
            const count =
              tab.value === ""
                ? items.length
                : items.filter((a) => a.status === tab.value).length;
            const active = fStatus === tab.value;
            return (
              <button
                key={tab.value}
                type="button"
                onClick={() => setFStatus(tab.value)}
                className={`relative whitespace-nowrap px-4 py-2.5 text-sm transition ${
                  active
                    ? "font-semibold text-accent-500"
                    : "text-white/60 hover:text-white"
                }`}
              >
                {tab.label}
                <span
                  className={`ml-1.5 inline-flex h-4 min-w-[16px] items-center justify-center rounded-full px-1 text-[10px] font-semibold ${
                    active
                      ? "bg-accent-500/20 text-accent-300"
                      : "bg-white/5 text-white/50"
                  }`}
                >
                  {count}
                </span>
                {active ? (
                  <span className="absolute inset-x-3 -bottom-px h-0.5 rounded-t bg-accent-500" />
                ) : null}
              </button>
            );
          })}
        </div>

        <div className="mb-4 flex flex-wrap items-center gap-2">
          <select
            value={fStatus}
            onChange={(e) => setFStatus(e.target.value)}
            className="input w-40"
          >
            <option value="">Tous les statuts</option>
            {Object.entries(STATUS_LABELS).map(([k, v]) => (
              <option key={k} value={k}>
                {v}
              </option>
            ))}
          </select>
          <select
            value={fProject}
            onChange={(e) => setFProject(e.target.value)}
            className="input w-48"
          >
            <option value="">Tous les projets</option>
            {projects.map((p) => (
              <option key={p.id} value={String(p.id)}>
                {p.name}
              </option>
            ))}
          </select>
          <select
            value={fFournisseur}
            onChange={(e) => setFFournisseur(e.target.value)}
            className="input w-48"
          >
            <option value="">Tous les fournisseurs</option>
            {fournisseurs.map((fr) => (
              <option key={fr.id} value={String(fr.id)}>
                {fr.name}
              </option>
            ))}
          </select>

          <div className="ml-auto rounded-md bg-brand-900 px-3 py-2 text-sm">
            <span className="text-white/50">Total filtré </span>
            <span className="font-bold text-white">{fmtMoney(total)}</span>
          </div>
        </div>

        {loading ? (
          <div className="flex min-h-[40vh] items-center justify-center">
            <Loader2 className="h-6 w-6 animate-spin text-accent-500" />
          </div>
        ) : filtered.length === 0 ? (
          <Empty />
        ) : (
          <div className="overflow-x-auto rounded-xl border border-brand-800 bg-brand-900">
            <table className="w-full text-sm">
              <thead className="border-b border-brand-800 text-left text-xs uppercase tracking-wider text-white/50">
                <tr>
                  <th className="px-4 py-3">Référence</th>
                  <th className="px-4 py-3">Fournisseur</th>
                  <th className="px-4 py-3">Projet</th>
                  <th className="px-4 py-3">Description</th>
                  <th className="px-4 py-3 text-right">Montant</th>
                  <th className="px-4 py-3">Échéance</th>
                  <th className="px-4 py-3 text-center">Refact.</th>
                  <th className="px-4 py-3 text-center">Statut</th>
                  <th className="px-4 py-3"></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-brand-800">
                {filtered.map((a) => {
                  const fr = a.fournisseur_id ? frById.get(a.fournisseur_id) : null;
                  const pr = a.project_id ? projById.get(a.project_id) : null;
                  return (
                    <tr
                      key={a.id}
                      onClick={() => (window.location.href = `/app/achats/${a.id}`)}
                      className="cursor-pointer hover:bg-brand-800/50"
                    >
                      <td className="px-4 py-3 font-semibold text-white">
                        {a.reference}
                      </td>
                      <td className="px-4 py-3 text-white/70">
                        {fr?.name || "—"}
                      </td>
                      <td className="px-4 py-3 text-white/70">
                        {pr?.name || "—"}
                      </td>
                      <td className="px-4 py-3 text-xs text-white/60">
                        <span className="line-clamp-1">{a.description || "—"}</span>
                      </td>
                      <td className="px-4 py-3 text-right font-semibold text-white">
                        {fmtMoney(
                          (a.amount != null ? Number(a.amount) : 0) +
                            (a.amount_taxes != null
                              ? Number(a.amount_taxes)
                              : 0)
                        )}
                      </td>
                      <td className="px-4 py-3 text-white/70">
                        {a.status === "paid" ? (
                          <span className="text-[10px] uppercase tracking-wider text-emerald-300/70">
                            Payé · {fmtDate(a.paid_at)}
                          </span>
                        ) : a.due_at ? (
                          (() => {
                            const due = new Date(a.due_at);
                            const overdue = daysBetween(new Date(), due);
                            return overdue > 0 ? (
                              <span className="rounded-md bg-rose-500/15 px-2 py-0.5 text-[10px] font-semibold text-rose-300">
                                En retard {overdue} j
                              </span>
                            ) : (
                              <span className="text-xs">
                                {fmtDate(a.due_at)}
                                {overdue === 0 ? (
                                  <span className="ml-1 text-amber-300/80">
                                    (aujourd&apos;hui)
                                  </span>
                                ) : null}
                              </span>
                            );
                          })()
                        ) : (
                          <span className="text-[10px] uppercase tracking-wider text-white/30">
                            —
                          </span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-center">
                        {a.is_billable === false ? (
                          <span className="text-[10px] uppercase tracking-wider text-white/30">
                            —
                          </span>
                        ) : a.invoiced_at ? (
                          <span className="rounded-md bg-emerald-500/15 px-2 py-0.5 text-[10px] font-semibold text-emerald-300">
                            ✓ Refacturé
                          </span>
                        ) : (
                          <span className="rounded-md bg-amber-500/15 px-2 py-0.5 text-[10px] font-semibold text-amber-300">
                            À refacturer
                            {a.markup_percent
                              ? ` (+${Number(a.markup_percent)}%)`
                              : ""}
                          </span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-center">
                        <span
                          className={`rounded-md px-2 py-0.5 text-[10px] font-semibold ${
                            STATUS_CLASS[a.status] || "bg-white/10 text-white"
                          }`}
                        >
                          {STATUS_LABELS[a.status] || a.status}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-right">
                        {a.status === "received" ? (
                          <button
                            type="button"
                            onClick={(ev) => {
                              ev.stopPropagation();
                              setPayTarget(a);
                            }}
                            className="inline-flex items-center gap-1 rounded-md border border-emerald-500/40 bg-emerald-500/10 px-2 py-1 text-[11px] font-semibold text-emerald-300 hover:bg-emerald-500/20"
                            title="Marquer cet achat comme payé"
                          >
                            <CheckCircle2 className="h-3.5 w-3.5" />
                            Payé
                          </button>
                        ) : null}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
      {payTarget ? (
        <MarkPaidModal
          achat={payTarget}
          onClose={() => setPayTarget(null)}
          onSaved={(updated) => {
            setItems((xs) =>
              xs.map((x) =>
                x.id === updated.id ? { ...x, ...updated } : x
              )
            );
            setPayTarget(null);
          }}
        />
      ) : null}
    </>
  );
}

function MarkPaidModal({
  achat,
  onClose,
  onSaved
}: {
  achat: Achat;
  onClose: () => void;
  onSaved: (a: Partial<Achat> & { id: number }) => void;
}) {
  const todayIso = new Date().toISOString().slice(0, 10);
  // Pre-selectionne la methode actuelle de l'achat si elle est deja
  // une vraie methode (cheque/CC) ; sinon laisse vide pour forcer
  // l'utilisateur a choisir.
  const initialMethod =
    achat.payment_method && achat.payment_method !== "bill_to_pay"
      ? achat.payment_method
      : "";
  const [method, setMethod] = useState(initialMethod);
  const [paidDate, setPaidDate] = useState(todayIso);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit() {
    if (!method) {
      setError("Choisis un mode de paiement.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const paidIso = new Date(`${paidDate}T12:00:00`).toISOString();
      const res = await authedFetch(
        `/api/v1/achats/${achat.id}/mark-paid`,
        {
          method: "POST",
          body: JSON.stringify({
            payment_method: method,
            paid_at: paidIso
          })
        }
      );
      if (!res.ok) {
        const txt = await res.text();
        let detail = txt;
        try {
          const j = JSON.parse(txt) as { detail?: string };
          if (j.detail) detail = j.detail;
        } catch {
          /* ignore */
        }
        throw new Error(detail.slice(0, 240));
      }
      const updated = (await res.json()) as Partial<Achat> & { id: number };
      onSaved(updated);
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
      onClick={onClose}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="w-full max-w-md rounded-2xl border border-brand-800 bg-brand-950 p-6 shadow-2xl"
      >
        <h2 className="text-lg font-bold text-white">
          Marquer l&apos;achat comme payé
        </h2>
        <p className="mt-1 text-xs text-white/60">
          {achat.reference || `Achat #${achat.id}`}
          {achat.description ? ` — ${achat.description}` : ""}
        </p>

        <div className="mt-5 space-y-4">
          <div>
            <label className="label">Mode de paiement</label>
            <select
              value={method}
              onChange={(e) => setMethod(e.target.value)}
              className="input"
              autoFocus
            >
              <option value="">— Choisir —</option>
              {REAL_PAYMENT_METHODS.map((m) => (
                <option key={m.value} value={m.value}>
                  {m.label}
                </option>
              ))}
            </select>
            {achat.payment_method === "bill_to_pay" ? (
              <p className="mt-1 text-[11px] text-white/40">
                L&apos;achat était saisi en « facture à payer ». Choisis
                ici la méthode réellement utilisée pour le payer.
              </p>
            ) : null}
          </div>
          <div>
            <label className="label">Date de paiement</label>
            <input
              type="date"
              value={paidDate}
              onChange={(e) => setPaidDate(e.target.value)}
              className="input"
            />
          </div>

          {error ? (
            <p className="rounded-md border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
              {error}
            </p>
          ) : null}
        </div>

        <div className="mt-6 flex justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            disabled={busy}
            className="rounded-lg border border-white/20 px-4 py-2 text-sm text-white/70 hover:bg-white/5"
          >
            Annuler
          </button>
          <button
            type="button"
            onClick={submit}
            disabled={busy || !method}
            className="inline-flex items-center gap-2 rounded-lg bg-emerald-500 px-4 py-2 text-sm font-semibold text-brand-950 hover:bg-emerald-400 disabled:opacity-60"
          >
            {busy ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <CheckCircle2 className="h-4 w-4" />
            )}
            Marquer payé
          </button>
        </div>
      </div>
    </div>
  );
}

function Empty() {
  return (
    <div className="mx-auto mt-16 max-w-md rounded-2xl border border-dashed border-brand-800 bg-brand-900/40 p-10 text-center">
      <ShoppingCart className="mx-auto h-10 w-10 text-accent-500" />
      <h2 className="mt-4 text-lg font-semibold text-white">Aucun achat</h2>
      <p className="mt-2 text-sm text-white/60">
        Enregistre tes achats de matériaux par projet; ils se reporteront
        dans la facture du client.
      </p>
      <Link
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        href={"/app/achats/new" as any}
        className="btn-accent mt-6 inline-flex text-sm"
      >
        <Plus className="mr-1.5 h-4 w-4" /> Nouvel achat
      </Link>
    </div>
  );
}
