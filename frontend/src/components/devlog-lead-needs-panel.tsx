"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Loader2, Plus, Trash2, X } from "lucide-react";

import { authedFetch } from "@/lib/auth";
import { useConfirm } from "@/components/confirm-dialog";

// Panneau « Besoins du client » de la fiche prospect Dev logiciel.
// Permet de documenter les besoins par pôle (Frontend, Backend, …)
// pour préparer la rédaction d'une soumission.
//
// Note (2026-05) : la génération de « Plan IA » + conversion en
// soumission a été retirée du frontend — la liste des besoins reste
// la base de référence pour la rédaction manuelle du devis. Les
// endpoints backend `/generate-plan` et `/plan-to-soumission` sont
// conservés pour rétro-compat mais ne sont plus appelés ici.

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

export function DevlogLeadNeedsPanel({ leadId }: { leadId: number }) {
  const confirm = useConfirm();

  const [needs, setNeeds] = useState<Need[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [addOpen, setAddOpen] = useState(false);

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
            Note les besoins par pôle de développement pour préparer la
            rédaction de la soumission.
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

