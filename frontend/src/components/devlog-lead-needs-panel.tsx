"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Loader2,
  Plus,
  Sparkles,
  Trash2,
  Wand2,
  X
} from "lucide-react";

import { authedFetch } from "@/lib/auth";
import { useConfirm } from "@/components/confirm-dialog";
import { useRouter } from "@/i18n/navigation";

// Panneau « Besoins du client » de la fiche prospect Dev logiciel.
// Permet de documenter les besoins par pôle (Frontend, Backend, …) et
// de générer un plan structuré via l'IA, qu'on peut transformer en
// soumission (sections + items pré-remplis) d'un clic.

export type Need = {
  id: number;
  lead_id: number;
  position: number;
  pole: string;
  label: string;
  notes: string | null;
  complexity: "simple" | "medium" | "complex" | null;
  priority: "low" | "medium" | "high" | null;
  created_at: string;
  updated_at: string;
};

type PlanItem = {
  description: string;
  quantity: number;
  unit?: string | null;
  cost_per_unit: number;
};

type PlanSection = {
  pole: string;
  name: string;
  billing_kind: "initial" | "recurring";
  markup_percent?: number | null;
  notes?: string | null;
  items: PlanItem[];
};

type Plan = {
  summary: string;
  sections: PlanSection[];
};

const POLE_PRESETS: { pole: string; label: string }[] = [
  { pole: "frontend", label: "Frontend" },
  { pole: "backend", label: "Backend + API" },
  { pole: "design", label: "Design / UX" },
  { pole: "mobile", label: "Mobile" },
  { pole: "data", label: "Données / BI" },
  { pole: "ai", label: "IA / Automatisation" },
  { pole: "integrations", label: "Intégrations" },
  { pole: "devops", label: "DevOps / CI-CD" },
  { pole: "hosting", label: "Hébergement + abonnements" },
  { pole: "autre", label: "Autre" }
];

const COMPLEXITY_LABEL: Record<string, string> = {
  simple: "Simple",
  medium: "Moyen",
  complex: "Complexe"
};

const PRIORITY_LABEL: Record<string, string> = {
  high: "Haute",
  medium: "Moyenne",
  low: "Basse"
};

function fmt(n: number): string {
  return n.toLocaleString("fr-CA", {
    style: "currency",
    currency: "CAD",
    maximumFractionDigits: 2
  });
}

export function DevlogLeadNeedsPanel({ leadId }: { leadId: number }) {
  const router = useRouter();
  const confirm = useConfirm();

  const [needs, setNeeds] = useState<Need[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [addOpen, setAddOpen] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [plan, setPlan] = useState<Plan | null>(null);
  const [creating, setCreating] = useState(false);

  const load = useCallback(async () => {
    try {
      const r = await authedFetch(`/api/v1/devlog/leads/${leadId}/needs`);
      if (!r.ok) throw new Error("Chargement impossible");
      setNeeds((await r.json()) as Need[]);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erreur");
    } finally {
      setLoading(false);
    }
  }, [leadId]);

  useEffect(() => {
    void load();
  }, [load]);

  async function addNeed(pole: string, label: string) {
    try {
      const r = await authedFetch("/api/v1/devlog/lead-needs", {
        method: "POST",
        body: JSON.stringify({
          lead_id: leadId,
          pole,
          label,
          position: needs.length
        })
      });
      if (!r.ok) throw new Error();
      await load();
      setAddOpen(false);
    } catch {
      setError("Ajout impossible");
    }
  }

  async function patchNeed(id: number, patch: Partial<Need>) {
    setNeeds((xs) => xs.map((x) => (x.id === id ? { ...x, ...patch } : x)));
    try {
      const r = await authedFetch(`/api/v1/devlog/lead-needs/${id}`, {
        method: "PATCH",
        body: JSON.stringify(patch)
      });
      if (!r.ok) throw new Error();
    } catch {
      setError("Mise à jour impossible");
      await load();
    }
  }

  async function deleteNeed(id: number) {
    const ok = await confirm({
      title: "Supprimer ce besoin ?",
      destructive: true,
      confirmLabel: "Supprimer"
    });
    if (!ok) return;
    setNeeds((xs) => xs.filter((x) => x.id !== id));
    try {
      await authedFetch(`/api/v1/devlog/lead-needs/${id}`, {
        method: "DELETE"
      });
    } catch {
      await load();
    }
  }

  async function generatePlan() {
    if (needs.length === 0) {
      setError("Ajoute au moins un besoin avant de générer le plan.");
      return;
    }
    setGenerating(true);
    setError(null);
    try {
      const r = await authedFetch(
        `/api/v1/devlog/leads/${leadId}/generate-plan`,
        { method: "POST" }
      );
      if (!r.ok) {
        const j = await r.json().catch(() => ({} as { detail?: string }));
        throw new Error(j.detail || "Génération impossible");
      }
      setPlan((await r.json()) as Plan);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erreur IA");
    } finally {
      setGenerating(false);
    }
  }

  async function createSoumission() {
    if (!plan) return;
    setCreating(true);
    try {
      const r = await authedFetch(
        `/api/v1/devlog/leads/${leadId}/plan-to-soumission`,
        {
          method: "POST",
          body: JSON.stringify({ plan })
        }
      );
      if (!r.ok) throw new Error();
      const created = (await r.json()) as { id: number };
      router.push({
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        pathname: `/dev-logiciel/soumissions/${created.id}` as any
      });
    } catch {
      setError("Création soumission impossible");
      setCreating(false);
    }
  }

  const presetsAvailable = useMemo(() => {
    const used = new Set(needs.map((n) => n.pole));
    return POLE_PRESETS.filter((p) => !used.has(p.pole));
  }, [needs]);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 className="text-base font-bold text-white">Besoins du client</h2>
          <p className="text-xs text-white/50">
            Note les besoins par pôle. L'IA structure ensuite un plan
            (sections + items) prêt à devenir une soumission.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => setAddOpen(true)}
            className="inline-flex items-center gap-1.5 rounded-md border border-brand-700 bg-brand-900 px-3 py-1.5 text-xs font-semibold text-white hover:bg-brand-800"
          >
            <Plus className="h-3 w-3" />
            Ajouter un pôle
          </button>
          <button
            type="button"
            onClick={generatePlan}
            disabled={generating || needs.length === 0}
            className="inline-flex items-center gap-1.5 rounded-md border border-blue-500/40 bg-blue-500/15 px-3 py-1.5 text-xs font-semibold text-blue-200 hover:bg-blue-500/25 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {generating ? (
              <Loader2 className="h-3 w-3 animate-spin" />
            ) : (
              <Sparkles className="h-3 w-3" />
            )}
            Générer le plan IA
          </button>
        </div>
      </div>

      {error ? (
        <div className="flex items-start justify-between gap-2 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-300">
          <span>{error}</span>
          <button type="button" onClick={() => setError(null)}>
            <X className="h-4 w-4" />
          </button>
        </div>
      ) : null}

      {loading ? (
        <div className="flex justify-center py-8">
          <Loader2 className="h-5 w-5 animate-spin text-blue-400" />
        </div>
      ) : needs.length === 0 ? (
        <div className="rounded-xl border border-dashed border-brand-800 px-4 py-8 text-center text-sm text-white/50">
          Aucun besoin documenté. Clique sur « Ajouter un pôle » pour démarrer.
        </div>
      ) : (
        <ul className="space-y-3">
          {needs.map((n) => (
            <NeedCard
              key={n.id}
              need={n}
              onPatch={(p) => patchNeed(n.id, p)}
              onDelete={() => deleteNeed(n.id)}
            />
          ))}
        </ul>
      )}

      {addOpen ? (
        <AddPoleModal
          presets={presetsAvailable}
          onClose={() => setAddOpen(false)}
          onAdd={addNeed}
        />
      ) : null}

      {plan ? (
        <PlanPreviewModal
          plan={plan}
          onClose={() => setPlan(null)}
          onCreate={createSoumission}
          creating={creating}
        />
      ) : null}
    </div>
  );
}

function NeedCard({
  need,
  onPatch,
  onDelete
}: {
  need: Need;
  onPatch: (patch: Partial<Need>) => void;
  onDelete: () => void;
}) {
  return (
    <li className="rounded-xl border border-brand-800 bg-brand-900 p-4">
      <div className="flex flex-wrap items-center gap-2 border-b border-brand-800 pb-2">
        <input
          value={need.label}
          onChange={(e) => onPatch({ label: e.target.value })}
          onBlur={(e) => onPatch({ label: e.target.value.trim() })}
          className="flex-1 rounded border border-transparent bg-transparent px-1 py-0.5 text-sm font-bold text-white hover:border-brand-800 focus:border-blue-500/50 focus:outline-none"
        />
        <span className="rounded bg-white/5 px-2 py-0.5 text-[10px] uppercase tracking-wide text-white/60">
          {need.pole}
        </span>
        <select
          value={need.complexity ?? ""}
          onChange={(e) =>
            onPatch({
              complexity:
                (e.target.value || null) as Need["complexity"]
            })
          }
          className="rounded border border-brand-700 bg-brand-950 px-2 py-1 text-xs text-white"
        >
          <option value="">Complexité…</option>
          {Object.entries(COMPLEXITY_LABEL).map(([v, l]) => (
            <option key={v} value={v}>
              {l}
            </option>
          ))}
        </select>
        <select
          value={need.priority ?? ""}
          onChange={(e) =>
            onPatch({
              priority: (e.target.value || null) as Need["priority"]
            })
          }
          className="rounded border border-brand-700 bg-brand-950 px-2 py-1 text-xs text-white"
        >
          <option value="">Priorité…</option>
          {Object.entries(PRIORITY_LABEL).map(([v, l]) => (
            <option key={v} value={v}>
              {l}
            </option>
          ))}
        </select>
        <button
          type="button"
          onClick={onDelete}
          className="rounded p-1 text-white/40 hover:bg-rose-500/15 hover:text-rose-300"
        >
          <Trash2 className="h-3.5 w-3.5" />
        </button>
      </div>
      <textarea
        value={need.notes ?? ""}
        onChange={(e) => onPatch({ notes: e.target.value })}
        placeholder="Décris ce que le client demande sur ce pôle (fonctionnalités, contraintes, exemples, intégrations…)"
        rows={3}
        className="mt-2 w-full resize-y rounded border border-brand-800 bg-brand-950 px-3 py-2 text-sm text-white placeholder:text-white/30 focus:border-blue-500/50 focus:outline-none"
      />
    </li>
  );
}

function AddPoleModal({
  presets,
  onClose,
  onAdd
}: {
  presets: { pole: string; label: string }[];
  onClose: () => void;
  onAdd: (pole: string, label: string) => void;
}) {
  const [custom, setCustom] = useState("");

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
      <div className="w-full max-w-md rounded-2xl border border-brand-800 bg-brand-950 p-5">
        <div className="mb-3 flex items-center justify-between">
          <h3 className="text-base font-bold text-white">Ajouter un pôle</h3>
          <button type="button" onClick={onClose}>
            <X className="h-4 w-4 text-white/50" />
          </button>
        </div>
        {presets.length > 0 ? (
          <>
            <p className="mb-2 text-xs text-white/50">
              Choisis un pôle prédéfini :
            </p>
            <div className="grid grid-cols-2 gap-2">
              {presets.map((p) => (
                <button
                  key={p.pole}
                  type="button"
                  onClick={() => onAdd(p.pole, p.label)}
                  className="rounded-lg border border-brand-800 bg-brand-900 px-3 py-2 text-left text-sm text-white hover:border-blue-500/40 hover:bg-blue-500/10"
                >
                  {p.label}
                </button>
              ))}
            </div>
          </>
        ) : (
          <p className="mb-2 text-xs text-white/50">
            Tous les pôles prédéfinis sont déjà ajoutés.
          </p>
        )}
        <div className="mt-4 border-t border-brand-800 pt-3">
          <p className="mb-2 text-xs text-white/50">
            Ou crée un pôle personnalisé :
          </p>
          <div className="flex gap-2">
            <input
              value={custom}
              onChange={(e) => setCustom(e.target.value)}
              placeholder="Ex. Migration de données legacy"
              className="flex-1 rounded border border-brand-800 bg-brand-900 px-3 py-2 text-sm text-white placeholder:text-white/30 focus:border-blue-500/50 focus:outline-none"
            />
            <button
              type="button"
              disabled={!custom.trim()}
              onClick={() => onAdd("autre", custom.trim())}
              className="rounded-md bg-blue-500 px-3 py-2 text-xs font-semibold text-white disabled:opacity-40"
            >
              Ajouter
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

function PlanPreviewModal({
  plan,
  onClose,
  onCreate,
  creating
}: {
  plan: Plan;
  onClose: () => void;
  onCreate: () => void;
  creating: boolean;
}) {
  const totalsByKind = useMemo(() => {
    let initial = 0;
    let monthly = 0;
    for (const sec of plan.sections) {
      const markup = (sec.markup_percent ?? 0) / 100;
      for (const it of sec.items) {
        const total = it.quantity * it.cost_per_unit * (1 + markup);
        if (sec.billing_kind === "recurring") monthly += total;
        else initial += total;
      }
    }
    return { initial, monthly };
  }, [plan]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4">
      <div className="flex max-h-[90vh] w-full max-w-3xl flex-col overflow-hidden rounded-2xl border border-brand-800 bg-brand-950">
        <header className="flex items-start justify-between gap-3 border-b border-brand-800 p-5">
          <div className="flex-1">
            <div className="flex items-center gap-2 text-xs uppercase tracking-wide text-blue-300">
              <Wand2 className="h-3.5 w-3.5" />
              Plan généré par l'IA
            </div>
            <h3 className="mt-1 text-base font-bold text-white">
              Aperçu de la soumission
            </h3>
            <p className="mt-1 text-xs text-white/60">{plan.summary}</p>
          </div>
          <button type="button" onClick={onClose}>
            <X className="h-5 w-5 text-white/50" />
          </button>
        </header>
        <div className="flex-1 overflow-y-auto p-5">
          <div className="mb-4 grid grid-cols-2 gap-2 text-xs">
            <div className="rounded-lg border border-blue-500/40 bg-blue-500/10 p-3">
              <p className="text-[10px] uppercase tracking-wider text-white/60">
                Frais initial
              </p>
              <p className="mt-1 text-lg font-bold text-white">
                {fmt(totalsByKind.initial)}
              </p>
            </div>
            <div className="rounded-lg border border-emerald-500/40 bg-emerald-500/10 p-3">
              <p className="text-[10px] uppercase tracking-wider text-white/60">
                Frais mensuel
              </p>
              <p className="mt-1 text-lg font-bold text-white">
                {fmt(totalsByKind.monthly)}
                <span className="text-xs font-normal text-white/60">
                  {" "}
                  / mois
                </span>
              </p>
            </div>
          </div>
          <ul className="space-y-3">
            {plan.sections.map((sec, i) => (
              <li
                key={i}
                className="rounded-lg border border-brand-800 bg-brand-900 p-3"
              >
                <div className="flex items-center justify-between border-b border-brand-800 pb-2">
                  <p className="text-sm font-bold text-white">{sec.name}</p>
                  <span className="rounded bg-white/5 px-2 py-0.5 text-[10px] uppercase tracking-wide text-white/60">
                    {sec.billing_kind === "recurring" ? "mensuel" : "initial"}
                    {sec.markup_percent != null
                      ? ` · markup ${sec.markup_percent}%`
                      : ""}
                  </span>
                </div>
                <ul className="mt-2 space-y-1 text-xs">
                  {sec.items.map((it, j) => (
                    <li
                      key={j}
                      className="flex items-baseline justify-between gap-2"
                    >
                      <span className="text-white/80">{it.description}</span>
                      <span className="whitespace-nowrap text-white/50">
                        {it.quantity} {it.unit || ""} ×{" "}
                        {fmt(it.cost_per_unit)}
                      </span>
                    </li>
                  ))}
                </ul>
              </li>
            ))}
          </ul>
        </div>
        <footer className="flex items-center justify-end gap-2 border-t border-brand-800 p-4">
          <button
            type="button"
            onClick={onClose}
            className="rounded-md border border-brand-700 px-3 py-2 text-xs font-semibold text-white/70 hover:bg-white/5"
          >
            Annuler
          </button>
          <button
            type="button"
            onClick={onCreate}
            disabled={creating}
            className="inline-flex items-center gap-2 rounded-md bg-blue-500 px-3 py-2 text-xs font-semibold text-white hover:bg-blue-600 disabled:opacity-50"
          >
            {creating ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Sparkles className="h-3.5 w-3.5" />
            )}
            Créer la soumission depuis ce plan
          </button>
        </footer>
      </div>
    </div>
  );
}
