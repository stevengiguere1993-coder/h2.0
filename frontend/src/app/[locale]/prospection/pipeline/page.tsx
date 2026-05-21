"use client";

import { useEffect, useState } from "react";
import { ChevronDown, ChevronRight, Loader2, Plus } from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { authedFetch } from "@/lib/auth";
import { Link, useRouter } from "@/i18n/navigation";
import { useProspectionLayout } from "../layout";

/**
 * Liste des deals (Pipeline) — analogue de /entreprises/page.tsx.
 * Chaque deal a sa propre fiche détaillée avec ses tâches, comme
 * une entreprise. La sidebar affiche aussi cette liste pour un
 * accès rapide.
 *
 * Découpée en 3 sections verticales :
 *   - Pipeline actif : priority ∈ {urgent, eleve, moyenne, a_venir}
 *   - Pipeline terminés : priority = "termine" (repliable)
 *   - Pipeline abandonnés : priority = "abandonne" (repliable)
 *
 * Drag-and-drop entre sections (HTML5 natif) : au drop sur une
 * section différente, PATCH /api/v1/prospection/deals/{id} avec la
 * nouvelle priority. Drop sur "actif" depuis un statut archivé
 * réactive le deal en "moyenne".
 */

type Deal = {
  id: number;
  address: string;
  priority: string;
  created_at: string;
  updated_at: string;
};

type SectionKey = "active" | "termine" | "abandonne";

const ACTIVE_PRIORITIES = new Set(["urgent", "eleve", "moyenne", "a_venir"]);

function sectionOf(priority: string): SectionKey {
  if (priority === "termine") return "termine";
  if (priority === "abandonne") return "abandonne";
  return "active";
}

export default function PipelineDealsListPage() {
  const { onOpenSidebar } = useProspectionLayout();
  const router = useRouter();
  const [deals, setDeals] = useState<Deal[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [newAddress, setNewAddress] = useState("");

  // État DnD : id du deal en cours de drag + section survolée pour
  // l'effet de bordure highlight.
  const [dragDealId, setDragDealId] = useState<number | null>(null);
  const [dragOverSection, setDragOverSection] = useState<SectionKey | null>(
    null
  );
  // Flag : un drop a-t-il eu lieu pendant ce drag ? Sert à
  // distinguer drag (déplacement) vs click (navigation).
  const [didDrop, setDidDrop] = useState(false);

  // Sections terminés / abandonnés repliées par défaut.
  const [openTermine, setOpenTermine] = useState(false);
  const [openAbandonne, setOpenAbandonne] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const r = await authedFetch("/api/v1/prospection/deals");
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        if (!cancelled) setDeals((await r.json()) as Deal[]);
      } catch (e) {
        if (!cancelled) setError((e as Error).message);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  async function createDeal(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!newAddress.trim()) return;
    setCreating(true);
    try {
      const r = await authedFetch("/api/v1/prospection/deals", {
        method: "POST",
        body: JSON.stringify({
          address: newAddress.trim(),
          priority: "moyenne"
        })
      });
      if (!r.ok) throw new Error();
      const created = (await r.json()) as Deal;
      setNewAddress("");
      // Aller direct sur la fiche du nouveau deal — l'utilisateur
      // veut généralement enchainer avec ses tâches.
      router.push(`/prospection/pipeline/${created.id}` as never);
    } catch {
      setError("Création échouée.");
    } finally {
      setCreating(false);
    }
  }

  /**
   * Patch optimiste de la priority d'un deal. En cas d'échec API,
   * on rollback à l'état précédent.
   */
  async function patchDealPriority(dealId: number, priority: string) {
    const prev = deals;
    setDeals((xs) =>
      xs.map((d) => (d.id === dealId ? { ...d, priority } : d))
    );
    try {
      const r = await authedFetch(
        `/api/v1/prospection/deals/${dealId}`,
        { method: "PATCH", body: JSON.stringify({ priority }) }
      );
      if (!r.ok) throw new Error();
    } catch {
      setDeals(prev);
      setError("Mise à jour échouée.");
    }
  }

  /**
   * Drop d'un deal sur une section.
   *   - section "active"     : si deal venait de termine/abandonne,
   *                            on le réactive en "moyenne" ; sinon
   *                            no-op.
   *   - section "termine"    : priority = "termine".
   *   - section "abandonne"  : priority = "abandonne".
   */
  function handleDropOnSection(section: SectionKey) {
    if (dragDealId == null) return;
    const dragged = deals.find((d) => d.id === dragDealId);
    setDragDealId(null);
    setDragOverSection(null);
    setDidDrop(true);
    if (!dragged) return;

    const currentSection = sectionOf(dragged.priority);
    if (currentSection === section) return; // no-op : même section.

    if (section === "termine") {
      void patchDealPriority(dragged.id, "termine");
    } else if (section === "abandonne") {
      void patchDealPriority(dragged.id, "abandonne");
    } else {
      // section === "active" : réactive seulement si venait
      // d'archive. Sinon no-op (pas de changement de priority).
      if (
        dragged.priority === "termine" ||
        dragged.priority === "abandonne"
      ) {
        void patchDealPriority(dragged.id, "moyenne");
      }
    }
  }

  const activeDeals = deals.filter((d) => ACTIVE_PRIORITIES.has(d.priority));
  const termineDeals = deals.filter((d) => d.priority === "termine");
  const abandonneDeals = deals.filter((d) => d.priority === "abandonne");

  return (
    <>
      <AppTopbar
        breadcrumbs={[
          { label: "Prospection", href: "/prospection" },
          { label: "Pipeline" }
        ]}
        onOpenSidebar={onOpenSidebar}
      />

      <div className="p-4 lg:p-6">
        <header className="mb-4 flex items-center gap-3">
          <h1 className="text-2xl font-bold text-white">Pipeline</h1>
          <span className="rounded-md bg-brand-900 px-2 py-1 text-xs text-white/60">
            {deals.length} deal{deals.length > 1 ? "s" : ""}
          </span>
        </header>

        <form
          onSubmit={createDeal}
          className="mb-6 flex flex-wrap items-center gap-2 rounded-xl border border-brand-800 bg-brand-900 p-3"
        >
          <input
            type="text"
            value={newAddress}
            onChange={(e) => setNewAddress(e.target.value)}
            placeholder="Adresse du nouveau deal (ex. 5640 Salaberry)"
            className="input flex-1 min-w-[240px]"
          />
          <button
            type="submit"
            disabled={creating || !newAddress.trim()}
            className="btn-accent text-sm disabled:opacity-50"
          >
            {creating ? (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            ) : (
              <Plus className="mr-1.5 h-4 w-4" />
            )}
            Ajouter un deal
          </button>
        </form>

        {error ? (
          <p className="mb-4 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-300">
            {error}
          </p>
        ) : null}

        {loading ? (
          <div className="flex min-h-[40vh] items-center justify-center">
            <Loader2 className="h-6 w-6 animate-spin text-accent-500" />
          </div>
        ) : deals.length === 0 ? (
          <div className="mx-auto mt-12 max-w-md rounded-2xl border border-dashed border-brand-800 bg-brand-900/40 p-10 text-center">
            <h2 className="text-lg font-semibold text-white">
              Aucun deal pour l&apos;instant
            </h2>
            <p className="mt-2 text-sm text-white/60">
              Saisis une adresse et clique « Ajouter un deal » pour
              commencer ton pipeline.
            </p>
          </div>
        ) : (
          <div className="space-y-4">
            <PipelineSection
              section="active"
              title="Pipeline actif"
              deals={activeDeals}
              open
              collapsible={false}
              dragDealId={dragDealId}
              dragOverSection={dragOverSection}
              setDragDealId={setDragDealId}
              setDragOverSection={setDragOverSection}
              didDrop={didDrop}
              setDidDrop={setDidDrop}
              onDropSection={handleDropOnSection}
              onCardClick={(id) =>
                router.push(`/prospection/pipeline/${id}` as never)
              }
            />

            <PipelineSection
              section="termine"
              title="Pipeline terminés"
              deals={termineDeals}
              open={openTermine}
              collapsible
              onToggle={() => setOpenTermine((v) => !v)}
              dimmed
              dragDealId={dragDealId}
              dragOverSection={dragOverSection}
              setDragDealId={setDragDealId}
              setDragOverSection={setDragOverSection}
              didDrop={didDrop}
              setDidDrop={setDidDrop}
              onDropSection={handleDropOnSection}
              onCardClick={(id) =>
                router.push(`/prospection/pipeline/${id}` as never)
              }
            />

            <PipelineSection
              section="abandonne"
              title="Pipeline abandonnés"
              deals={abandonneDeals}
              open={openAbandonne}
              collapsible
              onToggle={() => setOpenAbandonne((v) => !v)}
              dimmed
              extraDimmed
              dragDealId={dragDealId}
              dragOverSection={dragOverSection}
              setDragDealId={setDragDealId}
              setDragOverSection={setDragOverSection}
              didDrop={didDrop}
              setDidDrop={setDidDrop}
              onDropSection={handleDropOnSection}
              onCardClick={(id) =>
                router.push(`/prospection/pipeline/${id}` as never)
              }
            />
          </div>
        )}
      </div>
    </>
  );
}

/**
 * Sous-composant : une section verticale du pipeline.
 *   - Si `collapsible`, en-tête cliquable avec chevron pour
 *     replier/déplier.
 *   - Si `dimmed`, opacity réduite et bordure plus pâle.
 *   - Zone DnD : onDragOver / onDrop sur le wrapper de section, avec
 *     highlight visuel quand la section est survolée.
 */
function PipelineSection({
  section,
  title,
  deals,
  open,
  collapsible,
  onToggle,
  dimmed,
  extraDimmed,
  dragDealId,
  dragOverSection,
  setDragDealId,
  setDragOverSection,
  didDrop,
  setDidDrop,
  onDropSection,
  onCardClick
}: {
  section: SectionKey;
  title: string;
  deals: Deal[];
  open: boolean;
  collapsible: boolean;
  onToggle?: () => void;
  dimmed?: boolean;
  extraDimmed?: boolean;
  dragDealId: number | null;
  dragOverSection: SectionKey | null;
  setDragDealId: (id: number | null) => void;
  setDragOverSection: (s: SectionKey | null) => void;
  didDrop: boolean;
  setDidDrop: (v: boolean) => void;
  onDropSection: (s: SectionKey) => void;
  onCardClick: (id: number) => void;
}) {
  const isDragTarget = dragDealId != null && dragOverSection === section;

  const baseBorder = isDragTarget
    ? "border-emerald-500/50 bg-emerald-500/5"
    : extraDimmed
      ? "border-brand-800/40"
      : dimmed
        ? "border-brand-800/60"
        : "border-brand-800";

  const opacityClass = extraDimmed
    ? "opacity-50 hover:opacity-100 focus-within:opacity-100"
    : dimmed
      ? "opacity-70 hover:opacity-100 focus-within:opacity-100"
      : "";

  return (
    <section
      className={`rounded-xl border ${baseBorder} bg-brand-900/40 p-3 transition ${opacityClass}`}
      onDragOver={(ev) => {
        if (dragDealId != null) {
          ev.preventDefault();
          if (dragOverSection !== section) setDragOverSection(section);
        }
      }}
      onDragLeave={(ev) => {
        // Ne nettoie que si on quitte vraiment la section (pas un
        // enfant). currentTarget = la section, relatedTarget = l'élément
        // entrant. Si relatedTarget n'est pas dans la section, on quitte.
        const next = ev.relatedTarget as Node | null;
        if (
          dragOverSection === section &&
          (!next || !ev.currentTarget.contains(next))
        ) {
          setDragOverSection(null);
        }
      }}
      onDrop={(ev) => {
        ev.preventDefault();
        ev.stopPropagation();
        onDropSection(section);
      }}
    >
      <header
        className={`mb-3 flex items-center gap-2 ${collapsible ? "cursor-pointer select-none" : ""}`}
        onClick={collapsible ? onToggle : undefined}
      >
        {collapsible ? (
          open ? (
            <ChevronDown className="h-4 w-4 text-white/60" />
          ) : (
            <ChevronRight className="h-4 w-4 text-white/60" />
          )
        ) : null}
        <h2 className="text-sm font-semibold text-white/90">{title}</h2>
        <span className="rounded-md bg-brand-900 px-2 py-0.5 text-[11px] text-white/60">
          {deals.length}
        </span>
      </header>

      {open ? (
        deals.length === 0 ? (
          <p className="px-1 py-2 text-xs text-white/40">
            Aucun deal dans cette section.
          </p>
        ) : (
          <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {deals.map((d) => {
              const dragging = dragDealId === d.id;
              return (
                <li key={d.id}>
                  <div
                    draggable
                    onDragStart={(ev) => {
                      try {
                        ev.dataTransfer.setData("text/plain", String(d.id));
                        ev.dataTransfer.effectAllowed = "move";
                      } catch {
                        /* ignore */
                      }
                      setDragDealId(d.id);
                      setDidDrop(false);
                    }}
                    onDragEnd={() => {
                      setDragDealId(null);
                      setDragOverSection(null);
                    }}
                    onClick={(ev) => {
                      // Si un drop vient d'avoir lieu, on ne navigue
                      // pas. didDrop est remis à false au prochain
                      // dragStart.
                      if (didDrop) {
                        ev.preventDefault();
                        ev.stopPropagation();
                        setDidDrop(false);
                        return;
                      }
                      onCardClick(d.id);
                    }}
                    role="link"
                    tabIndex={0}
                    onKeyDown={(ev) => {
                      if (ev.key === "Enter" || ev.key === " ") {
                        ev.preventDefault();
                        onCardClick(d.id);
                      }
                    }}
                    className={`block cursor-pointer rounded-xl border border-brand-800 bg-brand-900 p-4 text-left transition hover:border-emerald-500/50 ${dragging ? "opacity-50" : ""}`}
                  >
                    {/* Lien invisible pour conserver la sémantique
                        de navigation côté SR / clic-milieu / "ouvrir
                        dans un nouvel onglet". draggable={false} pour
                        ne pas interférer avec le drag du parent. */}
                    <Link
                      // eslint-disable-next-line @typescript-eslint/no-explicit-any
                      href={`/prospection/pipeline/${d.id}` as any}
                      draggable={false}
                      onClick={(ev) => ev.preventDefault()}
                      className="sr-only"
                    >
                      Ouvrir {d.address}
                    </Link>
                    <h3 className="text-base font-semibold text-white break-words">
                      {d.address}
                    </h3>
                    <p className="mt-2 text-[11px] text-white/40">
                      Ajouté le{" "}
                      {new Date(d.created_at).toLocaleDateString("fr-CA", {
                        day: "2-digit",
                        month: "short",
                        year: "numeric"
                      })}
                    </p>
                  </div>
                </li>
              );
            })}
          </ul>
        )
      ) : null}
    </section>
  );
}
