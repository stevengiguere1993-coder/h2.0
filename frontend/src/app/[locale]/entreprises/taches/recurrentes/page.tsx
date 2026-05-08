"use client";

import { useEffect, useMemo, useState } from "react";
import {
  CheckCircle2,
  Loader2,
  Pause,
  Play,
  Plus,
  Repeat,
  Search,
  Trash2,
  X
} from "lucide-react";

import { authedFetch } from "@/lib/auth";
import { useConfirm } from "@/components/confirm-dialog";
import { QGTopbar, useEntreprisesLayout } from "../../layout";
import { Link } from "@/i18n/navigation";

/**
 * Page globale `/entreprises/taches/recurrentes` — liste tous les
 * modèles de tâches récurrentes de TOUTES les entreprises, groupés
 * par entreprise. Création directe avec sélecteur d'entreprise, et
 * bouton « Matérialiser maintenant » global pour tester le cron.
 */

type TacheTemplateGlobal = {
  id: number;
  entreprise_id: number;
  entreprise_name: string;
  title: string;
  description?: string | null;
  departement?: string | null;
  every_n: number;
  unit: string;
  lead_days: number;
  next_due: string;
  is_active: boolean;
  nb_materialized: number;
  last_materialized_at?: string | null;
};

const FREQ_UNITS = [
  { value: "jour", label: "jour(s)" },
  { value: "semaine", label: "semaine(s)" },
  { value: "mois", label: "mois" },
  { value: "annee", label: "année(s)" }
];

function todayPlusDays(n: number): string {
  const d = new Date();
  d.setDate(d.getDate() + n);
  return d.toISOString().slice(0, 10);
}

export default function TachesRecurrentesPage() {
  const [list, setList] = useState<TacheTemplateGlobal[] | null>(null);
  const [running, setRunning] = useState(false);
  const [runMsg, setRunMsg] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [search, setSearch] = useState("");
  const [activeOnly, setActiveOnly] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const confirm = useConfirm();

  async function reload() {
    try {
      const r = await authedFetch(
        "/api/v1/entreprises/tache-templates/all"
      );
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      setList((await r.json()) as TacheTemplateGlobal[]);
    } catch (e) {
      setError((e as Error).message);
    }
  }

  useEffect(() => {
    void reload();
  }, []);

  async function runMaterialize() {
    setRunning(true);
    setRunMsg(null);
    try {
      const res = await authedFetch(
        "/api/v1/entreprises/tache-templates/run-materialize",
        { method: "POST" }
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const d = (await res.json()) as { taches_created: number };
      setRunMsg(
        `${d.taches_created} tâche${d.taches_created > 1 ? "s" : ""} créée${
          d.taches_created > 1 ? "s" : ""
        } à partir des modèles dus.`
      );
      void reload();
    } catch (e) {
      setRunMsg((e as Error).message);
    } finally {
      setRunning(false);
    }
  }

  async function toggleActive(t: TacheTemplateGlobal) {
    await authedFetch(`/api/v1/entreprises/tache-templates/${t.id}`, {
      method: "PATCH",
      body: JSON.stringify({ is_active: !t.is_active })
    });
    void reload();
  }

  async function remove(t: TacheTemplateGlobal) {
    const ok = await confirm({
      title: `Supprimer le modèle « ${t.title} » ?`,
      description: `Modèle de l'entreprise « ${t.entreprise_name} ». Les tâches déjà créées ne sont pas supprimées.`,
      confirmLabel: "Supprimer",
      destructive: true
    });
    if (!ok) return;
    await authedFetch(`/api/v1/entreprises/tache-templates/${t.id}`, {
      method: "DELETE"
    });
    void reload();
  }

  // Filtrage côté client : recherche par titre ou entreprise, et
  // option « actifs seulement ».
  const filtered = useMemo(() => {
    if (!list) return null;
    const q = search.trim().toLowerCase();
    return list.filter((t) => {
      if (activeOnly && !t.is_active) return false;
      if (!q) return true;
      return (
        t.title.toLowerCase().includes(q) ||
        t.entreprise_name.toLowerCase().includes(q) ||
        (t.description || "").toLowerCase().includes(q)
      );
    });
  }, [list, search, activeOnly]);

  // Groupe par entreprise pour rendu en sections.
  const grouped = useMemo(() => {
    if (!filtered) return null;
    const map = new Map<number, { name: string; items: TacheTemplateGlobal[] }>();
    for (const t of filtered) {
      const cur = map.get(t.entreprise_id);
      if (cur) cur.items.push(t);
      else map.set(t.entreprise_id, { name: t.entreprise_name, items: [t] });
    }
    return Array.from(map.entries()).sort((a, b) =>
      a[1].name.localeCompare(b[1].name, "fr")
    );
  }, [filtered]);

  return (
    <>
      <QGTopbar
        greeting="Tâches récurrentes"
        subtitle="Modèles cross-entreprise · matérialisés automatiquement par le cron"
        rightSlot={
          <Link
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            href={"/entreprises/taches" as any}
            className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--qg-border)] bg-[var(--qg-bg-alt)] px-3 py-1.5 text-xs text-[var(--qg-text)] hover:bg-[var(--qg-bg)]"
          >
            ← Toutes les tâches
          </Link>
        }
      />

      <div className="mx-auto max-w-6xl px-5 py-6 lg:px-8">
        {/* Toolbar */}
        <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-wrap items-center gap-2">
            <div className="relative">
              <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-white/40" />
              <input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Rechercher (titre, entreprise…)"
                className="w-72 rounded-lg border border-brand-800 bg-brand-900 py-1.5 pl-8 pr-2 text-xs text-white placeholder:text-white/30 focus:border-accent-500 focus:outline-none"
              />
            </div>
            <label className="flex cursor-pointer items-center gap-1.5 text-xs text-white/70">
              <input
                type="checkbox"
                checked={activeOnly}
                onChange={(e) => setActiveOnly(e.target.checked)}
                className="h-3.5 w-3.5 accent-accent-500"
              />
              Actifs seulement
            </label>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={runMaterialize}
              disabled={running}
              className="btn-secondary inline-flex items-center text-xs disabled:opacity-60"
            >
              {running ? (
                <>
                  <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                  Exécution…
                </>
              ) : (
                <>
                  <Play className="mr-1.5 h-3.5 w-3.5" />
                  Matérialiser maintenant
                </>
              )}
            </button>
            <button
              type="button"
              onClick={() => setShowCreate(true)}
              className="btn-accent inline-flex items-center text-xs"
            >
              <Plus className="mr-1.5 h-3.5 w-3.5" />
              Nouveau modèle
            </button>
          </div>
        </div>

        {error ? (
          <p className="mb-3 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
            {error}
          </p>
        ) : null}

        {runMsg ? (
          <p className="mb-4 rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-xs text-emerald-300">
            <CheckCircle2 className="mr-1.5 inline h-3.5 w-3.5" />
            {runMsg}
          </p>
        ) : null}

        {grouped === null ? (
          <p className="py-12 text-center text-sm text-white/40">Chargement…</p>
        ) : grouped.length === 0 ? (
          <div className="rounded-xl border border-brand-800 bg-brand-900/40 px-6 py-12 text-center">
            <Repeat className="mx-auto mb-3 h-8 w-8 text-white/30" />
            <p className="text-sm text-white/60">
              Aucun modèle récurrent pour l&apos;instant.
            </p>
            <p className="mt-1 text-xs text-white/40">
              Crée-en un pour automatiser TPS/TVQ, rapprochement bancaire,
              etc.
            </p>
          </div>
        ) : (
          <div className="space-y-6">
            {grouped.map(([entId, group]) => (
              <section key={entId}>
                <header className="mb-2 flex items-baseline justify-between">
                  <Link
                    // eslint-disable-next-line @typescript-eslint/no-explicit-any
                    href={`/entreprises/${entId}` as any}
                    className="text-sm font-bold text-white hover:text-accent-500"
                  >
                    {group.name}
                  </Link>
                  <span className="text-[10px] uppercase tracking-wider text-white/40">
                    {group.items.length} modèle{group.items.length > 1 ? "s" : ""}
                  </span>
                </header>
                <ul className="space-y-2">
                  {group.items.map((t) => (
                    <TemplateRow
                      key={t.id}
                      t={t}
                      onToggle={() => toggleActive(t)}
                      onDelete={() => remove(t)}
                    />
                  ))}
                </ul>
              </section>
            ))}
          </div>
        )}
      </div>

      {showCreate ? (
        <CreateTemplateModal
          onClose={() => setShowCreate(false)}
          onSaved={() => {
            setShowCreate(false);
            void reload();
          }}
        />
      ) : null}
    </>
  );
}

// ── Sous-composants ────────────────────────────────────────────────

function TemplateRow({
  t,
  onToggle,
  onDelete
}: {
  t: TacheTemplateGlobal;
  onToggle: () => void;
  onDelete: () => void;
}) {
  return (
    <li className="rounded-xl border border-brand-800 bg-brand-900 p-4">
      <div className="flex items-start gap-3">
        <span className="mt-0.5 flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-lg bg-violet-500/15 text-violet-300">
          <Repeat className="h-4 w-4" />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="truncate text-sm font-bold text-white">
              {t.title}
            </h3>
            {!t.is_active ? (
              <span className="rounded-full border border-white/15 px-1.5 py-0.5 text-[10px] uppercase text-white/50">
                Désactivé
              </span>
            ) : null}
          </div>
          <p className="mt-0.5 text-[11px] text-white/50">
            Tous les {t.every_n} {t.unit}
            {t.departement ? ` · ${t.departement}` : ""}
            {" · prochain "}
            <span className="font-mono text-white/70">{t.next_due}</span>
            {" · lead "}
            <span className="font-mono">{t.lead_days}j</span>
          </p>
          {t.description ? (
            <p className="mt-1 text-xs text-white/60">{t.description}</p>
          ) : null}
          <p className="mt-2 text-[10px] text-white/40">
            {t.nb_materialized} matérialisation
            {t.nb_materialized > 1 ? "s" : ""}
            {t.last_materialized_at
              ? ` · dernière ${new Date(
                  t.last_materialized_at
                ).toLocaleString("fr-CA")}`
              : ""}
          </p>
        </div>
        <div className="flex items-center gap-1">
          <button
            type="button"
            onClick={onToggle}
            className="inline-flex items-center gap-1 rounded-lg border border-white/15 bg-brand-950 px-2 py-1 text-[10px] text-white/70 hover:text-white"
            title={t.is_active ? "Désactiver" : "Activer"}
          >
            {t.is_active ? (
              <>
                <Pause className="h-3 w-3" />
                Pause
              </>
            ) : (
              <>
                <Play className="h-3 w-3" />
                Activer
              </>
            )}
          </button>
          <button
            type="button"
            onClick={onDelete}
            className="rounded-lg border border-white/15 bg-brand-950 p-1.5 text-white/40 hover:border-rose-400/50 hover:text-rose-300"
            title="Supprimer"
          >
            <Trash2 className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>
    </li>
  );
}

function CreateTemplateModal({
  onClose,
  onSaved
}: {
  onClose: () => void;
  onSaved: () => void;
}) {
  const { entreprises } = useEntreprisesLayout();
  const [form, setForm] = useState({
    entrepriseId: "",
    title: "",
    description: "",
    departement: "",
    every_n: "1",
    unit: "mois",
    lead_days: "7",
    next_due: todayPlusDays(7)
  });
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  // Présélectionne la 1ère entreprise active dès qu'elles sont chargées.
  useEffect(() => {
    if (form.entrepriseId) return;
    const first = entreprises.find((e) => e.is_active) || entreprises[0];
    if (first) setForm((f) => ({ ...f, entrepriseId: String(first.id) }));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [entreprises]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!form.entrepriseId) {
      setErr("Choisis une entreprise.");
      return;
    }
    setSaving(true);
    setErr(null);
    try {
      const body: Record<string, unknown> = {
        entreprise_id: Number(form.entrepriseId),
        title: form.title.trim(),
        every_n: Number(form.every_n) || 1,
        unit: form.unit,
        lead_days: Number(form.lead_days) || 0,
        next_due: form.next_due,
        is_active: true
      };
      if (form.description.trim()) body.description = form.description.trim();
      if (form.departement.trim()) body.departement = form.departement.trim();
      const res = await authedFetch(
        "/api/v1/entreprises/tache-templates",
        {
          method: "POST",
          body: JSON.stringify(body)
        }
      );
      if (!res.ok) {
        const t = await res.text();
        throw new Error(t.slice(0, 240) || `HTTP ${res.status}`);
      }
      onSaved();
    } catch (e2) {
      setErr((e2 as Error).message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <ModalShell title="Nouveau modèle récurrent" onClose={onClose}>
      <form onSubmit={submit} className="grid gap-4">
        <div>
          <label className="label">Entreprise</label>
          <select
            required
            value={form.entrepriseId}
            onChange={(e) =>
              setForm({ ...form, entrepriseId: e.target.value })
            }
            className="input"
          >
            <option value="" disabled>
              — Choisis une entreprise —
            </option>
            {entreprises.map((e) => (
              <option key={e.id} value={e.id}>
                {e.name}
                {!e.is_active ? " (inactive)" : ""}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="label">Titre</label>
          <input
            required
            value={form.title}
            onChange={(e) => setForm({ ...form, title: e.target.value })}
            className="input"
            placeholder="ex. Faire la TPS/TVQ trimestrielle"
          />
        </div>
        <div>
          <label className="label">Description (optionnel)</label>
          <textarea
            value={form.description}
            onChange={(e) =>
              setForm({ ...form, description: e.target.value })
            }
            rows={2}
            className="input"
            placeholder="Comment exécuter la tâche, liens utiles…"
          />
        </div>
        <div>
          <label className="label">Département (optionnel)</label>
          <input
            value={form.departement}
            onChange={(e) =>
              setForm({ ...form, departement: e.target.value })
            }
            className="input"
            placeholder="ex. Compta, RH, Marketing"
          />
        </div>
        <div className="grid grid-cols-3 gap-2">
          <div>
            <label className="label">Tous les</label>
            <input
              type="number"
              min={1}
              value={form.every_n}
              onChange={(e) => setForm({ ...form, every_n: e.target.value })}
              className="input font-mono"
            />
          </div>
          <div>
            <label className="label">Unité</label>
            <select
              value={form.unit}
              onChange={(e) => setForm({ ...form, unit: e.target.value })}
              className="input"
            >
              {FREQ_UNITS.map((u) => (
                <option key={u.value} value={u.value}>
                  {u.label}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="label">Lead (jours)</label>
            <input
              type="number"
              min={0}
              value={form.lead_days}
              onChange={(e) =>
                setForm({ ...form, lead_days: e.target.value })
              }
              className="input font-mono"
            />
          </div>
        </div>
        <div>
          <label className="label">Prochaine échéance</label>
          <input
            required
            type="date"
            value={form.next_due}
            onChange={(e) => setForm({ ...form, next_due: e.target.value })}
            className="input"
          />
        </div>

        {err ? (
          <p className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
            {err}
          </p>
        ) : null}

        <div className="flex justify-end gap-2 pt-1">
          <button type="button" onClick={onClose} className="btn-secondary">
            Annuler
          </button>
          <button
            type="submit"
            disabled={saving || !form.title.trim() || !form.entrepriseId}
            className="btn-accent disabled:opacity-60"
          >
            {saving ? (
              <>
                <Loader2 className="mr-1.5 inline h-3.5 w-3.5 animate-spin" />
                Création…
              </>
            ) : (
              "Créer"
            )}
          </button>
        </div>
      </form>
    </ModalShell>
  );
}

function ModalShell({
  title,
  onClose,
  children
}: {
  title: string;
  onClose: () => void;
  children: React.ReactNode;
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/60 px-2 py-4 sm:items-center">
      <div className="w-full max-w-xl rounded-2xl border border-brand-800 bg-brand-900 shadow-2xl">
        <div className="flex items-center justify-between border-b border-brand-800 p-4">
          <h2 className="text-base font-bold text-white">{title}</h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="Fermer"
            className="rounded-md p-1 text-white/60 hover:bg-white/5 hover:text-white"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="max-h-[80vh] overflow-y-auto p-4">{children}</div>
      </div>
    </div>
  );
}
