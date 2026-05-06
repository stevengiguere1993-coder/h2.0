"use client";

import { useCallback, useEffect, useState } from "react";
import { Loader2, Plus, Trash2 } from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { authedFetch } from "@/lib/auth";
import { useConfirm } from "@/components/confirm-dialog";
import { useProspectionLayout } from "../layout";

type Priority = "urgent" | "eleve" | "moyenne" | "en_attente" | "a_venir";

type Deal = {
  id: number;
  address: string;
  priority: Priority;
  created_at: string;
  updated_at: string;
};

// Ordre canonique : urgent en premier, à venir en dernier. Dicte
// l'ordre d'affichage de gauche à droite dans la grille.
const PRIORITIES: { value: Priority; label: string; dot: string }[] = [
  { value: "urgent", label: "Urgent", dot: "bg-rose-500" },
  { value: "eleve", label: "Élevé", dot: "bg-orange-500" },
  { value: "moyenne", label: "Moyenne", dot: "bg-amber-400" },
  { value: "en_attente", label: "En attente", dot: "bg-sky-400" },
  { value: "a_venir", label: "À venir", dot: "bg-white/40" }
];

const PRIORITY_LABEL: Record<Priority, string> = {
  urgent: "Urgent",
  eleve: "Élevé",
  moyenne: "Moyenne",
  en_attente: "En attente",
  a_venir: "À venir"
};

const PRIORITY_DOT: Record<Priority, string> = {
  urgent: "bg-rose-500",
  eleve: "bg-orange-500",
  moyenne: "bg-amber-400",
  en_attente: "bg-sky-400",
  a_venir: "bg-white/40"
};

export default function ProspectionPipelinePage() {
  const { onOpenSidebar } = useProspectionLayout();
  const confirm = useConfirm();
  const [deals, setDeals] = useState<Deal[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [modalOpen, setModalOpen] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await authedFetch("/api/v1/prospection/deals");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setDeals((await res.json()) as Deal[]);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function changePriority(id: number, priority: Priority) {
    // MAJ optimiste : on bouge la carte tout de suite, on rollback
    // si le serveur refuse.
    const prev = deals;
    setDeals((xs) =>
      xs.map((d) => (d.id === id ? { ...d, priority } : d))
    );
    try {
      const res = await authedFetch(`/api/v1/prospection/deals/${id}`, {
        method: "PATCH",
        body: JSON.stringify({ priority })
      });
      if (!res.ok) throw new Error();
    } catch {
      setDeals(prev);
      setError("Mise à jour de la priorité échouée.");
    }
  }

  async function removeDeal(deal: Deal) {
    if (
      !(await confirm({
        title: `Retirer le deal « ${deal.address} » ?`,
        description: "Cette action ne peut pas être annulée.",
        confirmLabel: "Retirer",
        destructive: true
      }))
    ) {
      return;
    }
    const prev = deals;
    setDeals((xs) => xs.filter((d) => d.id !== deal.id));
    try {
      const res = await authedFetch(
        `/api/v1/prospection/deals/${deal.id}`,
        { method: "DELETE" }
      );
      if (!res.ok && res.status !== 204) throw new Error();
    } catch {
      setDeals(prev);
      setError("Suppression échouée.");
    }
  }

  return (
    <>
      <AppTopbar
        breadcrumbs={[
          { label: "Prospection", href: "/prospection" },
          { label: "Pipeline des deals" }
        ]}
        onOpenSidebar={onOpenSidebar}
        rightSlot={
          <button
            type="button"
            onClick={() => setModalOpen(true)}
            className="btn-accent text-sm"
          >
            <Plus className="mr-1.5 h-4 w-4" /> Ajouter un deal
          </button>
        }
      />

      <div className="p-4 lg:p-6">
        {error ? (
          <p className="mb-4 rounded-lg border border-rose-500/40 bg-rose-500/10 px-4 py-2 text-sm text-rose-300">
            {error}
          </p>
        ) : null}

        {loading ? (
          <div className="flex min-h-[40vh] items-center justify-center">
            <Loader2 className="h-6 w-6 animate-spin text-accent-500" />
          </div>
        ) : deals.length === 0 ? (
          <EmptyState onAdd={() => setModalOpen(true)} />
        ) : (
          // Grille fluide : les cartes se placent une à côté de
          // l'autre dans l'ordre que renvoie l'API (déjà trié par
          // priorité serveur-side : urgent → à venir).
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {deals.map((d) => (
              <DealCard
                key={d.id}
                deal={d}
                onChangePriority={(p) => changePriority(d.id, p)}
                onRemove={() => removeDeal(d)}
              />
            ))}
          </div>
        )}
      </div>

      {modalOpen ? (
        <AddDealModal
          onClose={() => setModalOpen(false)}
          onCreated={(d) => {
            // On insère puis on relance le tri serveur-side au prochain
            // refresh — pour l'instant on push au bon endroit côté
            // client en se basant sur l'ordre canonique.
            setDeals((xs) => sortDeals([...xs, d]));
            setModalOpen(false);
          }}
        />
      ) : null}
    </>
  );
}

function sortDeals(arr: Deal[]): Deal[] {
  const rank: Record<Priority, number> = {
    urgent: 0,
    eleve: 1,
    moyenne: 2,
    en_attente: 3,
    a_venir: 4
  };
  return [...arr].sort((a, b) => {
    const ra = rank[a.priority] ?? 99;
    const rb = rank[b.priority] ?? 99;
    if (ra !== rb) return ra - rb;
    return new Date(b.created_at).getTime() - new Date(a.created_at).getTime();
  });
}

function DealCard({
  deal,
  onChangePriority,
  onRemove
}: {
  deal: Deal;
  onChangePriority: (p: Priority) => void;
  onRemove: () => void;
}) {
  return (
    <div className="rounded-xl border border-brand-800 bg-brand-900 p-4 shadow-sm">
      <div className="flex items-start justify-between gap-2">
        <h3 className="min-w-0 flex-1 text-sm font-semibold text-white">
          {deal.address}
        </h3>
        <PriorityPicker value={deal.priority} onChange={onChangePriority} />
      </div>

      <div className="mt-3 flex items-center justify-between text-[10px] text-white/40">
        <span>
          Ajouté le{" "}
          {new Date(deal.created_at).toLocaleDateString("fr-CA", {
            day: "2-digit",
            month: "short",
            year: "numeric"
          })}
        </span>
        <button
          type="button"
          onClick={onRemove}
          className="rounded p-1 text-white/40 hover:bg-rose-500/15 hover:text-rose-300"
          title="Retirer du pipeline"
          aria-label="Retirer"
        >
          <Trash2 className="h-3.5 w-3.5" />
        </button>
      </div>
    </div>
  );
}

function PriorityPicker({
  value,
  onChange
}: {
  value: Priority;
  onChange: (p: Priority) => void;
}) {
  return (
    <div className="relative">
      <select
        value={value}
        onChange={(e) => onChange(e.target.value as Priority)}
        className="cursor-pointer appearance-none rounded-md border border-brand-800 bg-brand-950 py-1 pl-6 pr-2 text-[11px] font-semibold text-white focus:border-accent-500 focus:outline-none"
        aria-label="Priorité"
      >
        {PRIORITIES.map((p) => (
          <option key={p.value} value={p.value}>
            {p.label}
          </option>
        ))}
      </select>
      <span
        className={`pointer-events-none absolute left-1.5 top-1/2 h-2 w-2 -translate-y-1/2 rounded-full ${PRIORITY_DOT[value]}`}
      />
    </div>
  );
}

function AddDealModal({
  onClose,
  onCreated
}: {
  onClose: () => void;
  onCreated: (d: Deal) => void;
}) {
  const [address, setAddress] = useState("");
  const [priority, setPriority] = useState<Priority>("moyenne");
  const [submitting, setSubmitting] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function submit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!address.trim()) {
      setErr("L'adresse est requise.");
      return;
    }
    setSubmitting(true);
    setErr(null);
    try {
      const res = await authedFetch("/api/v1/prospection/deals", {
        method: "POST",
        body: JSON.stringify({
          address: address.trim(),
          priority
        })
      });
      if (!res.ok) {
        const txt = await res.text().catch(() => "");
        throw new Error(`HTTP ${res.status} ${txt.slice(0, 120)}`);
      }
      const created = (await res.json()) as Deal;
      onCreated(created);
    } catch (e) {
      setErr((e as Error).message || "Création échouée.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4"
      onClick={() => (!submitting ? onClose() : null)}
    >
      <form
        onClick={(e) => e.stopPropagation()}
        onSubmit={submit}
        className="w-full max-w-md rounded-2xl border border-brand-800 bg-brand-950 p-5"
      >
        <h2 className="text-base font-bold text-white">Ajouter un deal</h2>
        <p className="mt-1 text-xs text-white/50">
          Saisis l&apos;adresse de l&apos;immeuble et choisis sa priorité.
          Tu pourras enrichir le deal après.
        </p>

        <div className="mt-4 space-y-3">
          <div>
            <label className="label">Adresse de l&apos;immeuble</label>
            <input
              type="text"
              value={address}
              onChange={(e) => setAddress(e.target.value)}
              placeholder="Ex. 1234 rue Saint-Hubert, Montréal"
              className="input"
              autoFocus
              disabled={submitting}
            />
          </div>
          <div>
            <label className="label">Priorité</label>
            <select
              value={priority}
              onChange={(e) => setPriority(e.target.value as Priority)}
              className="input"
              disabled={submitting}
            >
              {PRIORITIES.map((p) => (
                <option key={p.value} value={p.value}>
                  {p.label}
                </option>
              ))}
            </select>
          </div>
        </div>

        {err ? (
          <p className="mt-3 rounded-md border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
            {err}
          </p>
        ) : null}

        <div className="mt-5 flex items-center justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            disabled={submitting}
            className="btn-secondary text-sm"
          >
            Annuler
          </button>
          <button
            type="submit"
            disabled={submitting}
            className="btn-accent text-sm disabled:opacity-60"
          >
            {submitting ? (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            ) : (
              <Plus className="mr-1.5 h-4 w-4" />
            )}
            Ajouter le deal
          </button>
        </div>
      </form>
    </div>
  );
}

function EmptyState({ onAdd }: { onAdd: () => void }) {
  return (
    <div className="mx-auto mt-12 max-w-md rounded-2xl border border-dashed border-brand-800 bg-brand-900/40 p-10 text-center">
      <h2 className="text-lg font-semibold text-white">
        Aucun deal pour l&apos;instant
      </h2>
      <p className="mt-2 text-sm text-white/60">
        Ajoute ta première opportunité — adresse + priorité — et elle
        apparaîtra ici dans l&apos;ordre, du plus urgent au moins urgent.
      </p>
      <button
        type="button"
        onClick={onAdd}
        className="btn-accent mt-5 text-sm"
      >
        <Plus className="mr-1.5 h-4 w-4" /> Ajouter un deal
      </button>
    </div>
  );
}

// Dummy export pour éviter un warning "unused" sur PRIORITY_LABEL
// (utilisé dans des PR ultérieurs pour les filtres / titres).
export const _PRIORITY_LABEL = PRIORITY_LABEL;
