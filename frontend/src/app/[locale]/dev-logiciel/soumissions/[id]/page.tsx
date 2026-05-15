"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useParams } from "next/navigation";
import {
  ArrowLeft,
  Briefcase,
  Eye,
  EyeOff,
  Loader2,
  Plus,
  Repeat,
  Trash2,
  X
} from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { useDevlogLayout } from "../../layout";
import { authedFetch } from "@/lib/auth";
import { useConfirm } from "@/components/confirm-dialog";
import { Link } from "@/i18n/navigation";

// Page détail soumission — REBUILD avec sections par pôle, coûts
// internes, markup caché et séparation initial / mensuel.

type Soumission = {
  id: number;
  title: string;
  status: string;
  lead_id: number | null;
  client_id: number | null;
  amount: number | null; // total INITIAL (frais one-shot)
  summary: string | null;
  notes: string | null;
  created_at: string;
  updated_at: string;
};

type Section = {
  id: number;
  soumission_id: number;
  position: number;
  name: string;
  billing_kind: "initial" | "recurring";
  markup_percent: number | null;
  client_label: string | null;
  notes: string | null;
};

type Item = {
  id: number;
  soumission_id: number;
  section_id: number | null;
  position: number;
  description: string;
  unit: string | null;
  quantity: number;
  cost_per_unit: number;
  unit_price: number;
  total: number;
  notes: string | null;
};

type Totals = { initial: number; monthly: number };

const STATUS_LABEL: Record<string, string> = {
  brouillon: "Brouillon",
  envoyee: "Envoyée",
  acceptee: "Acceptée",
  refusee: "Refusée",
  expiree: "Expirée"
};

const STATUS_CLS: Record<string, string> = {
  brouillon: "bg-white/5 text-white/60",
  envoyee: "bg-blue-500/15 text-blue-300",
  acceptee: "bg-emerald-500/15 text-emerald-300",
  refusee: "bg-rose-500/15 text-rose-300",
  expiree: "bg-amber-500/15 text-amber-300"
};

function fmtAmount(n: number | null): string {
  if (n == null) return "—";
  return n.toLocaleString("fr-CA", {
    style: "currency",
    currency: "CAD",
    maximumFractionDigits: 2
  });
}

export default function SoumissionDetailPage() {
  const params = useParams<{ id: string }>();
  const id = Number(params?.id);
  const { onOpenSidebar } = useDevlogLayout();
  const confirm = useConfirm();

  const [s, setS] = useState<Soumission | null>(null);
  const [sections, setSections] = useState<Section[]>([]);
  const [items, setItems] = useState<Item[]>([]);
  const [totals, setTotals] = useState<Totals>({ initial: 0, monthly: 0 });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [adminView, setAdminView] = useState(true);

  const loadAll = useCallback(async () => {
    try {
      const [sr, secR, itR, tR] = await Promise.all([
        authedFetch(`/api/v1/devlog/soumissions/${id}`),
        authedFetch(`/api/v1/devlog/soumissions/${id}/sections`),
        authedFetch(`/api/v1/devlog/soumissions/${id}/items`),
        authedFetch(`/api/v1/devlog/soumissions/${id}/totals`)
      ]);
      if (!sr.ok) throw new Error("Soumission introuvable");
      setS((await sr.json()) as Soumission);
      if (secR.ok) setSections((await secR.json()) as Section[]);
      if (itR.ok) setItems((await itR.json()) as Item[]);
      if (tR.ok) setTotals((await tR.json()) as Totals);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erreur");
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    if (Number.isFinite(id)) void loadAll();
  }, [id, loadAll]);

  async function addSection(billing_kind: "initial" | "recurring") {
    const defaultName =
      billing_kind === "initial"
        ? prompt("Nom de la section (ex. Frontend, Backend, Design) ?")
        : prompt("Nom de la section mensuelle (ex. Hosting + abonnements) ?");
    if (!defaultName?.trim()) return;
    try {
      const r = await authedFetch("/api/v1/devlog/soumission-sections", {
        method: "POST",
        body: JSON.stringify({
          soumission_id: id,
          name: defaultName.trim(),
          billing_kind,
          markup_percent: billing_kind === "initial" ? 100 : 50,
          position: sections.length
        })
      });
      if (!r.ok) throw new Error();
      await loadAll();
    } catch {
      setError("Création section impossible");
    }
  }

  async function patchSection(secId: number, patch: Partial<Section>) {
    setSections((xs) =>
      xs.map((x) => (x.id === secId ? { ...x, ...patch } : x))
    );
    try {
      const r = await authedFetch(
        `/api/v1/devlog/soumission-sections/${secId}`,
        { method: "PATCH", body: JSON.stringify(patch) }
      );
      if (!r.ok) throw new Error();
      await loadAll();
    } catch {
      setError("Mise à jour section impossible");
      await loadAll();
    }
  }

  async function deleteSection(secId: number) {
    const ok = await confirm({
      title: "Supprimer cette section ?",
      description:
        "Les items de la section seront détachés (pas supprimés). Tu pourras les réassigner à une autre section.",
      confirmLabel: "Supprimer",
      destructive: true
    });
    if (!ok) return;
    try {
      await authedFetch(`/api/v1/devlog/soumission-sections/${secId}`, {
        method: "DELETE"
      });
      await loadAll();
    } catch {
      setError("Suppression impossible");
    }
  }

  async function addItem(sectionId: number) {
    try {
      const r = await authedFetch("/api/v1/devlog/soumission-items", {
        method: "POST",
        body: JSON.stringify({
          soumission_id: id,
          section_id: sectionId,
          description: "Nouvelle ligne",
          unit: "h",
          quantity: 1,
          cost_per_unit: 0
        })
      });
      if (!r.ok) throw new Error();
      await loadAll();
    } catch {
      setError("Ajout ligne impossible");
    }
  }

  async function patchItem(itemId: number, patch: Partial<Item>) {
    setItems((xs) =>
      xs.map((x) => (x.id === itemId ? { ...x, ...patch } : x))
    );
    try {
      const r = await authedFetch(
        `/api/v1/devlog/soumission-items/${itemId}`,
        { method: "PATCH", body: JSON.stringify(patch) }
      );
      if (!r.ok) throw new Error();
      await loadAll();
    } catch {
      setError("Mise à jour ligne impossible");
      await loadAll();
    }
  }

  async function deleteItem(itemId: number) {
    setItems((xs) => xs.filter((x) => x.id !== itemId));
    try {
      await authedFetch(`/api/v1/devlog/soumission-items/${itemId}`, {
        method: "DELETE"
      });
      await loadAll();
    } catch {
      void loadAll();
    }
  }

  async function changeStatus(newStatus: string) {
    try {
      const r = await authedFetch(
        `/api/v1/devlog/soumissions/${id}/status`,
        { method: "PATCH", body: JSON.stringify({ status: newStatus }) }
      );
      if (!r.ok) throw new Error();
      await loadAll();
    } catch {
      setError("Changement de statut impossible");
    }
  }

  const initialSections = sections.filter((x) => x.billing_kind === "initial");
  const recurringSections = sections.filter((x) => x.billing_kind === "recurring");
  const itemsBySection = useMemo(() => {
    const m = new Map<number, Item[]>();
    for (const it of items) {
      if (it.section_id == null) continue;
      const arr = m.get(it.section_id) || [];
      arr.push(it);
      m.set(it.section_id, arr);
    }
    return m;
  }, [items]);
  const orphans = items.filter((it) => it.section_id == null);

  return (
    <>
      <AppTopbar
        breadcrumbs={[
          { label: "Développement logiciel", href: "/dev-logiciel" as any },
          { label: "Soumissions", href: "/dev-logiciel/soumissions" as any },
          { label: s?.title ?? `#${id}` }
        ]}
        onOpenSidebar={onOpenSidebar}
      />

      <div className="mx-auto max-w-5xl p-4 lg:p-6">
        <div className="mb-4 flex items-center justify-between">
          <Link
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            href={"/dev-logiciel/soumissions" as any}
            className="inline-flex items-center text-sm text-white/70 hover:text-blue-400"
          >
            <ArrowLeft className="mr-1 h-4 w-4" /> Retour
          </Link>
          <button
            type="button"
            onClick={() => setAdminView((v) => !v)}
            className={`inline-flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-xs font-semibold ${
              adminView
                ? "border-amber-500/40 bg-amber-500/10 text-amber-300"
                : "border-emerald-500/40 bg-emerald-500/10 text-emerald-300"
            }`}
            title="Bascule entre la vue admin (avec coûts + markup) et la vue client (prix finaux seulement)"
          >
            {adminView ? (
              <>
                <Eye className="h-3.5 w-3.5" />
                Vue admin (coûts visibles)
              </>
            ) : (
              <>
                <EyeOff className="h-3.5 w-3.5" />
                Vue client (coûts cachés)
              </>
            )}
          </button>
        </div>

        {error ? (
          <div className="mb-3 flex items-start justify-between gap-2 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-300">
            <span>{error}</span>
            <button type="button" onClick={() => setError(null)}>
              <X className="h-4 w-4" />
            </button>
          </div>
        ) : null}

        {loading ? (
          <div className="mt-10 flex justify-center">
            <Loader2 className="h-6 w-6 animate-spin text-blue-400" />
          </div>
        ) : !s ? (
          <p className="text-center text-sm text-white/40">Soumission introuvable.</p>
        ) : (
          <>
            {/* Header soumission */}
            <header className="mb-5">
              <h1 className="text-2xl font-bold text-white">{s.title}</h1>
              <div className="mt-2 flex flex-wrap items-center gap-2 text-xs">
                <span
                  className={`rounded px-2 py-0.5 font-semibold uppercase tracking-wide ${
                    STATUS_CLS[s.status] ?? "bg-white/5 text-white/50"
                  }`}
                >
                  {STATUS_LABEL[s.status] ?? s.status}
                </span>
                <span className="text-white/40">
                  Créée le{" "}
                  {new Date(s.created_at).toLocaleDateString("fr-CA")}
                </span>
                <StatusActions status={s.status} onChange={changeStatus} />
              </div>
            </header>

            {/* 2 totaux */}
            <div className="mb-5 grid gap-3 sm:grid-cols-2">
              <TotalCard
                label="Frais initial (one-shot)"
                value={totals.initial}
                icon={<Briefcase className="h-5 w-5 text-blue-300" />}
                accent="blue"
              />
              <TotalCard
                label="Frais mensuel (récurrent)"
                value={totals.monthly}
                icon={<Repeat className="h-5 w-5 text-emerald-300" />}
                accent="emerald"
                suffix=" / mois"
              />
            </div>

            {/* Sections initiales */}
            <SectionGroup
              title="Frais initial — développement"
              subtitle="Payé une seule fois à la livraison"
              sections={initialSections}
              items={itemsBySection}
              addLabel="Ajouter une section initiale"
              onAdd={() => addSection("initial")}
              onPatchSection={patchSection}
              onDeleteSection={deleteSection}
              onAddItem={addItem}
              onPatchItem={patchItem}
              onDeleteItem={deleteItem}
              adminView={adminView}
            />

            {/* Sections mensuelles */}
            <SectionGroup
              title="Frais mensuel — hébergement + abonnements"
              subtitle="Facturé tous les mois (hosting du produit + softwares)"
              sections={recurringSections}
              items={itemsBySection}
              addLabel="Ajouter une section mensuelle"
              onAdd={() => addSection("recurring")}
              onPatchSection={patchSection}
              onDeleteSection={deleteSection}
              onAddItem={addItem}
              onPatchItem={patchItem}
              onDeleteItem={deleteItem}
              adminView={adminView}
            />

            {/* Items orphelins (legacy — pas dans une section) */}
            {orphans.length > 0 ? (
              <section className="mt-6 rounded-2xl border border-amber-500/30 bg-amber-500/5 p-4">
                <h3 className="text-sm font-bold text-amber-200">
                  Items sans section ({orphans.length})
                </h3>
                <p className="mt-1 text-xs text-amber-200/70">
                  Ces lignes ont été créées avant le rebuild. Réassigne-les à
                  une section ou supprime-les.
                </p>
                <ul className="mt-2 space-y-1 text-xs">
                  {orphans.map((it) => (
                    <li
                      key={it.id}
                      className="flex items-center justify-between gap-2"
                    >
                      <span className="text-white/80">{it.description}</span>
                      <span className="font-semibold text-white">
                        {fmtAmount(it.total)}
                      </span>
                      <button
                        type="button"
                        onClick={() => void deleteItem(it.id)}
                        className="rounded p-1 text-white/40 hover:bg-rose-500/15 hover:text-rose-300"
                      >
                        <Trash2 className="h-3 w-3" />
                      </button>
                    </li>
                  ))}
                </ul>
              </section>
            ) : null}
          </>
        )}
      </div>
    </>
  );
}

function TotalCard({
  label,
  value,
  icon,
  accent,
  suffix
}: {
  label: string;
  value: number;
  icon: React.ReactNode;
  accent: "blue" | "emerald";
  suffix?: string;
}) {
  const cls =
    accent === "blue"
      ? "border-blue-500/40 bg-blue-500/10"
      : "border-emerald-500/40 bg-emerald-500/10";
  return (
    <div className={`rounded-2xl border ${cls} p-5`}>
      <div className="flex items-center justify-between">
        <p className="text-[10px] font-semibold uppercase tracking-wider text-white/60">
          {label}
        </p>
        {icon}
      </div>
      <p className="mt-2 text-3xl font-bold text-white">
        {fmtAmount(value)}
        {suffix ? <span className="text-base font-normal text-white/60">{suffix}</span> : null}
      </p>
    </div>
  );
}

function SectionGroup({
  title,
  subtitle,
  sections,
  items,
  addLabel,
  onAdd,
  onPatchSection,
  onDeleteSection,
  onAddItem,
  onPatchItem,
  onDeleteItem,
  adminView
}: {
  title: string;
  subtitle: string;
  sections: Section[];
  items: Map<number, Item[]>;
  addLabel: string;
  onAdd: () => void;
  onPatchSection: (id: number, patch: Partial<Section>) => void;
  onDeleteSection: (id: number) => void;
  onAddItem: (sectionId: number) => void;
  onPatchItem: (id: number, patch: Partial<Item>) => void;
  onDeleteItem: (id: number) => void;
  adminView: boolean;
}) {
  return (
    <section className="mt-6">
      <header className="mb-3 flex items-end justify-between">
        <div>
          <h2 className="text-sm font-bold text-white">{title}</h2>
          <p className="text-xs text-white/50">{subtitle}</p>
        </div>
        <button
          type="button"
          onClick={onAdd}
          className="inline-flex items-center gap-1.5 rounded-md border border-blue-500/40 bg-blue-500/10 px-3 py-1.5 text-xs font-semibold text-blue-300 hover:bg-blue-500/20"
        >
          <Plus className="h-3 w-3" />
          {addLabel}
        </button>
      </header>
      {sections.length === 0 ? (
        <p className="rounded-xl border border-dashed border-brand-800 px-4 py-6 text-center text-xs text-white/40">
          Aucune section. Clique sur « {addLabel} » pour démarrer.
        </p>
      ) : (
        <div className="space-y-3">
          {sections.map((sec) => (
            <SectionCard
              key={sec.id}
              section={sec}
              items={items.get(sec.id) || []}
              onPatchSection={onPatchSection}
              onDeleteSection={onDeleteSection}
              onAddItem={onAddItem}
              onPatchItem={onPatchItem}
              onDeleteItem={onDeleteItem}
              adminView={adminView}
            />
          ))}
        </div>
      )}
    </section>
  );
}

function SectionCard({
  section: sec,
  items,
  onPatchSection,
  onDeleteSection,
  onAddItem,
  onPatchItem,
  onDeleteItem,
  adminView
}: {
  section: Section;
  items: Item[];
  onPatchSection: (id: number, patch: Partial<Section>) => void;
  onDeleteSection: (id: number) => void;
  onAddItem: (sectionId: number) => void;
  onPatchItem: (id: number, patch: Partial<Item>) => void;
  onDeleteItem: (id: number) => void;
  adminView: boolean;
}) {
  const sectionTotal = items.reduce((s, it) => s + (it.total || 0), 0);
  const sectionCost = items.reduce(
    (s, it) => s + (it.cost_per_unit || 0) * (it.quantity || 0),
    0
  );
  const margin = sectionTotal - sectionCost;

  return (
    <div className="rounded-2xl border border-brand-800 bg-brand-900 p-4">
      <div className="flex flex-wrap items-center gap-2 border-b border-brand-800 pb-3">
        <input
          value={sec.name}
          onChange={(e) => onPatchSection(sec.id, { name: e.target.value })}
          onBlur={(e) =>
            onPatchSection(sec.id, { name: e.target.value.trim() })
          }
          className="flex-1 rounded border border-transparent bg-transparent px-1 py-0.5 text-base font-bold text-white hover:border-brand-800 focus:border-blue-500/50 focus:outline-none"
        />
        {adminView ? (
          <label className="inline-flex items-center gap-1.5 text-xs text-white/60">
            Markup&nbsp;
            <input
              type="number"
              step="5"
              min="0"
              max="500"
              value={sec.markup_percent ?? 0}
              onChange={(e) =>
                onPatchSection(sec.id, {
                  markup_percent: Number(e.target.value)
                })
              }
              className="w-16 rounded border border-brand-700 bg-brand-950 px-1.5 py-0.5 text-right text-white"
            />
            %
          </label>
        ) : null}
        <span className="rounded bg-white/5 px-2 py-0.5 text-[10px] uppercase tracking-wide text-white/60">
          {sec.billing_kind === "recurring" ? "mensuel" : "initial"}
        </span>
        <button
          type="button"
          onClick={() => onDeleteSection(sec.id)}
          className="rounded p-1 text-white/30 hover:bg-rose-500/15 hover:text-rose-300"
        >
          <Trash2 className="h-3.5 w-3.5" />
        </button>
      </div>

      {items.length === 0 ? (
        <p className="py-4 text-center text-xs text-white/40">
          Aucune ligne dans cette section.
        </p>
      ) : (
        <table className="mt-3 w-full text-xs">
          <thead className="text-[10px] uppercase tracking-wider text-white/40">
            <tr>
              <th className="text-left">Description</th>
              {adminView ? <th className="text-right">Qté</th> : null}
              {adminView ? <th className="text-right">Unité</th> : null}
              {adminView ? <th className="text-right">Coût $</th> : null}
              <th className="text-right">Prix unit.</th>
              <th className="text-right">Total</th>
              <th></th>
            </tr>
          </thead>
          <tbody className="divide-y divide-brand-800">
            {items.map((it) => (
              <tr key={it.id}>
                <td className="py-1.5">
                  <input
                    value={it.description}
                    onChange={(e) =>
                      onPatchItem(it.id, { description: e.target.value })
                    }
                    className="w-full rounded border border-transparent bg-transparent px-1 py-0.5 text-white hover:border-brand-800 focus:border-blue-500/50 focus:outline-none"
                  />
                </td>
                {adminView ? (
                  <td className="py-1.5">
                    <input
                      type="number"
                      step="0.5"
                      value={it.quantity}
                      onChange={(e) =>
                        onPatchItem(it.id, { quantity: Number(e.target.value) })
                      }
                      className="w-16 rounded border border-brand-700 bg-brand-950 px-1.5 py-0.5 text-right text-white"
                    />
                  </td>
                ) : null}
                {adminView ? (
                  <td className="py-1.5">
                    <input
                      value={it.unit ?? ""}
                      onChange={(e) =>
                        onPatchItem(it.id, { unit: e.target.value || null })
                      }
                      className="w-12 rounded border border-brand-700 bg-brand-950 px-1.5 py-0.5 text-right text-white"
                    />
                  </td>
                ) : null}
                {adminView ? (
                  <td className="py-1.5">
                    <input
                      type="number"
                      step="0.5"
                      value={it.cost_per_unit}
                      onChange={(e) =>
                        onPatchItem(it.id, {
                          cost_per_unit: Number(e.target.value)
                        })
                      }
                      className="w-20 rounded border border-brand-700 bg-brand-950 px-1.5 py-0.5 text-right text-white"
                    />
                  </td>
                ) : null}
                <td className="py-1.5 text-right text-white/80">
                  {fmtAmount(it.unit_price)}
                </td>
                <td className="py-1.5 text-right font-semibold text-white">
                  {fmtAmount(it.total)}
                </td>
                <td className="py-1.5">
                  <button
                    type="button"
                    onClick={() => onDeleteItem(it.id)}
                    className="rounded p-1 text-white/30 hover:bg-rose-500/15 hover:text-rose-300"
                  >
                    <Trash2 className="h-3 w-3" />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
          <tfoot className="border-t border-brand-800">
            <tr>
              <td
                colSpan={adminView ? 5 : 1}
                className="pt-2 text-right text-xs text-white/60"
              >
                Sous-total
              </td>
              <td className="pt-2 text-right text-sm font-bold text-white">
                {fmtAmount(sectionTotal)}
              </td>
              <td></td>
            </tr>
            {adminView ? (
              <tr className="text-[10px] text-white/40">
                <td colSpan={5} className="text-right">
                  Coût interne {fmtAmount(sectionCost)} · Marge{" "}
                  {fmtAmount(margin)}
                </td>
                <td></td>
                <td></td>
              </tr>
            ) : null}
          </tfoot>
        </table>
      )}

      <button
        type="button"
        onClick={() => onAddItem(sec.id)}
        className="mt-2 inline-flex items-center gap-1.5 rounded text-xs text-white/50 hover:text-white"
      >
        <Plus className="h-3 w-3" />
        Ajouter une ligne
      </button>
    </div>
  );
}

function StatusActions({
  status,
  onChange
}: {
  status: string;
  onChange: (newStatus: string) => void;
}) {
  // Transitions possibles selon le statut actuel. Le passage à
  // « acceptee » provisionne automatiquement le projet côté backend.
  const transitions: Array<{ to: string; label: string; cls: string }> = [];
  if (status === "brouillon")
    transitions.push({
      to: "envoyee",
      label: "Marquer envoyée",
      cls: "border-blue-500/40 bg-blue-500/10 text-blue-200"
    });
  if (status === "envoyee" || status === "brouillon") {
    transitions.push({
      to: "acceptee",
      label: "Marquer acceptée (→ projet)",
      cls: "border-emerald-500/40 bg-emerald-500/10 text-emerald-200"
    });
    transitions.push({
      to: "refusee",
      label: "Marquer refusée",
      cls: "border-rose-500/40 bg-rose-500/10 text-rose-200"
    });
  }
  if (transitions.length === 0) return null;
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {transitions.map((t) => (
        <button
          key={t.to}
          type="button"
          onClick={() => onChange(t.to)}
          className={`rounded-md border px-2 py-1 text-[10px] font-semibold uppercase tracking-wide ${t.cls} hover:brightness-110`}
        >
          {t.label}
        </button>
      ))}
    </div>
  );
}
