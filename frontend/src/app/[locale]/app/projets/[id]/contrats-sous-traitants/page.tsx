"use client";

import { useEffect, useMemo, useState } from "react";
import { useParams } from "next/navigation";
import { Loader2, Plus, Trash2 } from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { Link } from "@/i18n/navigation";
import { authedFetch } from "@/lib/auth";

type Contract = {
  id: number;
  project_id: number;
  sous_traitant_id: number;
  billing_mode: "markup_pct" | "flat_hourly" | "lump_sum";
  markup_percent: number | null;
  flat_hourly_rate: number | null;
  lump_sum_amount: number | null;
  notes: string | null;
  created_at: string;
  updated_at: string;
};

type SousTraitant = { id: number; full_name: string; hourly_rate: number | null };

const BILLING_MODE_LABEL: Record<string, string> = {
  markup_pct: "Markup % sur coûtant",
  flat_hourly: "Taux horaire fixe ($/h)",
  lump_sum: "Forfait total ($)"
};

export default function ContratsSousTraitantsPage() {
  const params = useParams<{ id: string }>();
  const projectId = Number(params?.id);
  const [contracts, setContracts] = useState<Contract[]>([]);
  const [sousTraitants, setSousTraitants] = useState<SousTraitant[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Formulaire d'ajout
  const [adding, setAdding] = useState(false);
  const [newSt, setNewSt] = useState("");
  const [newMode, setNewMode] = useState<Contract["billing_mode"]>("markup_pct");
  const [newMarkup, setNewMarkup] = useState("");
  const [newHourly, setNewHourly] = useState("");
  const [newLump, setNewLump] = useState("");
  const [newNotes, setNewNotes] = useState("");
  const [creating, setCreating] = useState(false);

  async function load() {
    setLoading(true);
    try {
      const [cr, str] = await Promise.all([
        authedFetch(
          `/api/v1/subcontractor-contracts?project_id=${projectId}`
        ),
        authedFetch("/api/v1/sous-traitants?limit=500")
      ]);
      if (!cr.ok) throw new Error("Chargement impossible");
      setContracts((await cr.json()) as Contract[]);
      if (str.ok) setSousTraitants((await str.json()) as SousTraitant[]);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erreur");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (!Number.isFinite(projectId)) return;
    void load();
  }, [projectId]);

  const stById = useMemo(
    () => new Map(sousTraitants.map((s) => [s.id, s])),
    [sousTraitants]
  );

  // Liste des sous-traitants sans contrat existant — disponibles pour l'ajout
  const existingStIds = new Set(contracts.map((c) => c.sous_traitant_id));
  const availableSt = sousTraitants.filter((s) => !existingStIds.has(s.id));

  async function createContract() {
    if (!newSt) {
      setError("Sélectionne un sous-traitant");
      return;
    }
    setCreating(true);
    try {
      const r = await authedFetch("/api/v1/subcontractor-contracts", {
        method: "POST",
        body: JSON.stringify({
          project_id: projectId,
          sous_traitant_id: Number(newSt),
          billing_mode: newMode,
          markup_percent:
            newMode === "markup_pct" && newMarkup.trim()
              ? Number(newMarkup)
              : null,
          flat_hourly_rate:
            newMode === "flat_hourly" && newHourly.trim()
              ? Number(newHourly)
              : null,
          lump_sum_amount:
            newMode === "lump_sum" && newLump.trim() ? Number(newLump) : null,
          notes: newNotes.trim() || null
        })
      });
      if (!r.ok) {
        const msg = await r.text();
        throw new Error(msg || "Création impossible");
      }
      setAdding(false);
      setNewSt("");
      setNewMode("markup_pct");
      setNewMarkup("");
      setNewHourly("");
      setNewLump("");
      setNewNotes("");
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erreur");
    } finally {
      setCreating(false);
    }
  }

  async function deleteContract(id: number) {
    if (!window.confirm("Supprimer ce contrat ?")) return;
    try {
      const r = await authedFetch(`/api/v1/subcontractor-contracts/${id}`, {
        method: "DELETE"
      });
      if (!r.ok) throw new Error();
      setContracts((xs) => xs.filter((c) => c.id !== id));
    } catch {
      setError("Suppression impossible");
    }
  }

  return (
    <div className="min-h-screen bg-brand-950">
      <AppTopbar
        breadcrumbs={[
          { label: "Projets", href: "/app/projets" as any },
          {
            label: `Projet #${projectId}`,
            href: `/app/projets/${projectId}` as any
          },
          { label: "Contrats sous-traitants" }
        ]}
        onOpenSidebar={() => {}}
      />

      <div className="mx-auto max-w-4xl px-4 py-6 lg:px-6">
        <div className="mb-4 flex items-center justify-between">
          <h1 className="text-xl font-bold text-white">
            Contrats sous-traitants
          </h1>
          {!adding && availableSt.length > 0 ? (
            <button
              type="button"
              onClick={() => setAdding(true)}
              className="btn-accent btn-sm"
            >
              <Plus className="h-4 w-4" />
              Ajouter un contrat
            </button>
          ) : null}
        </div>

        <p className="mb-4 text-sm text-white/60">
          Définit comment Horizon refacture les heures / factures d&apos;un
          sous-traitant au client final pour ce projet. Sans contrat, les
          factures de sous-traitants sont refacturées au coûtant.
        </p>

        {error ? (
          <div className="mb-3 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-300">
            {error}
          </div>
        ) : null}

        {/* Formulaire d'ajout */}
        {adding ? (
          <div className="mb-4 rounded-xl border border-brand-800 bg-brand-900 p-4">
            <h2 className="mb-3 text-sm font-semibold text-white">
              Nouveau contrat
            </h2>
            <div className="grid gap-3 sm:grid-cols-2">
              <div>
                <label className="label">Sous-traitant</label>
                <select
                  value={newSt}
                  onChange={(e) => setNewSt(e.target.value)}
                  className="input"
                >
                  <option value="">— Sélectionne —</option>
                  {availableSt.map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.full_name}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className="label">Mode de facturation</label>
                <select
                  value={newMode}
                  onChange={(e) =>
                    setNewMode(e.target.value as Contract["billing_mode"])
                  }
                  className="input"
                >
                  {Object.entries(BILLING_MODE_LABEL).map(([k, v]) => (
                    <option key={k} value={k}>
                      {v}
                    </option>
                  ))}
                </select>
              </div>
              {newMode === "markup_pct" ? (
                <div className="sm:col-span-2">
                  <label className="label">Markup (%)</label>
                  <input
                    type="number"
                    step="0.5"
                    min="0"
                    value={newMarkup}
                    onChange={(e) => setNewMarkup(e.target.value)}
                    placeholder="ex. 15"
                    className="input"
                  />
                  <p className="mt-1 text-xs text-white/40">
                    Le montant facturé sera coûtant × (1 + %/100).
                  </p>
                </div>
              ) : newMode === "flat_hourly" ? (
                <div className="sm:col-span-2">
                  <label className="label">Taux horaire facturé ($/h)</label>
                  <input
                    type="number"
                    step="0.5"
                    min="0"
                    value={newHourly}
                    onChange={(e) => setNewHourly(e.target.value)}
                    placeholder="ex. 75"
                    className="input"
                  />
                  <p className="mt-1 text-xs text-white/40">
                    Multiplié par les heures saisies sur la facture
                    sous-traitant — peu importe ce que le sous-traitant charge.
                  </p>
                </div>
              ) : (
                <div className="sm:col-span-2">
                  <label className="label">Montant forfaitaire ($)</label>
                  <input
                    type="number"
                    step="0.01"
                    min="0"
                    value={newLump}
                    onChange={(e) => setNewLump(e.target.value)}
                    placeholder="0.00"
                    className="input"
                  />
                  <p className="mt-1 text-xs text-white/40">
                    Montant fixe ajouté à la prochaine facture pour ce
                    sous-traitant, peu importe le coûtant.
                  </p>
                </div>
              )}
              <div className="sm:col-span-2">
                <label className="label">Notes</label>
                <textarea
                  value={newNotes}
                  onChange={(e) => setNewNotes(e.target.value)}
                  rows={2}
                  className="input"
                  placeholder="Clauses négociées, retenue, etc."
                />
              </div>
            </div>
            <div className="mt-3 flex items-center justify-end gap-2">
              <button
                type="button"
                onClick={() => setAdding(false)}
                disabled={creating}
                className="btn-secondary text-sm"
              >
                Annuler
              </button>
              <button
                type="button"
                onClick={createContract}
                disabled={creating || !newSt}
                className="btn-accent text-sm disabled:opacity-60"
              >
                {creating ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : null}
                Créer
              </button>
            </div>
          </div>
        ) : null}

        {/* Liste des contrats */}
        {loading ? (
          <div className="mt-10 flex justify-center">
            <Loader2 className="h-6 w-6 animate-spin text-accent-500" />
          </div>
        ) : contracts.length === 0 ? (
          <p className="mt-10 text-center text-sm text-white/40">
            Aucun contrat pour ce projet.
          </p>
        ) : (
          <ul className="space-y-2">
            {contracts.map((c) => {
              const st = stById.get(c.sous_traitant_id);
              return (
                <li
                  key={c.id}
                  className="rounded-xl border border-brand-800 bg-brand-900 p-4"
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0 flex-1">
                      <p className="font-semibold text-white">
                        {st?.full_name || `Sous-traitant #${c.sous_traitant_id}`}
                      </p>
                      <p className="mt-0.5 text-xs uppercase tracking-wider text-accent-500">
                        {BILLING_MODE_LABEL[c.billing_mode]}
                      </p>
                      <p className="mt-2 text-sm text-white/80">
                        {c.billing_mode === "markup_pct"
                          ? `+ ${c.markup_percent ?? 0} % sur le coûtant`
                          : c.billing_mode === "flat_hourly"
                          ? `${c.flat_hourly_rate ?? 0} $/h facturé au client`
                          : `Forfait : ${c.lump_sum_amount ?? 0} $`}
                      </p>
                      {c.notes ? (
                        <p className="mt-2 whitespace-pre-line text-xs text-white/50">
                          {c.notes}
                        </p>
                      ) : null}
                    </div>
                    <button
                      type="button"
                      onClick={() => deleteContract(c.id)}
                      title="Supprimer"
                      className="btn-outline-rose btn-xs"
                    >
                      <Trash2 className="h-4 w-4" />
                    </button>
                  </div>
                </li>
              );
            })}
          </ul>
        )}

        <div className="mt-8">
          <Link
            href={`/app/projets/${projectId}` as any}
            className="text-sm text-accent-500 hover:underline"
          >
            ← Retour au projet
          </Link>
        </div>
      </div>
    </div>
  );
}
