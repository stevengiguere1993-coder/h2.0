"use client";

import { useEffect, useState } from "react";
import {
  ChevronDown,
  ChevronRight,
  Eye,
  Loader2,
  Plus,
  Trash2
} from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { authedFetch } from "@/lib/auth";
import { useConfirm } from "@/components/confirm-dialog";
import {
  LeadAnalysisCard,
  type LeadAnalysisCardBadge
} from "@/components/lead-analysis-card";
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
 *
 * Style des cards : aligné sur le composant LeadCard de la page
 * Analyses des leads — adresse en titre, ville en sous-titre, ligne
 * de métadonnées compactes avec icônes (logements, prix, refi),
 * programme SCHL retenu, MDF prêteur B, badge coloré selon section.
 * Les métadonnées proviennent de la fiche d'analyse liée
 * (`deal.lead_analysis`, eager-loaded côté backend). Fallback
 * minimal (juste adresse + date) pour les deals créés manuellement
 * sans `lead_analysis_id`.
 */

type DealLeadAnalysis = {
  id: number;
  city: string | null;
  nb_logements: number | null;
  asking_price: number | null;
  best_refi_amount: number | null;
  best_refi_program: string | null;
  mdf_preteur_b: number | null;
};

type Deal = {
  id: number;
  address: string;
  priority: string;
  drive_folder_url: string | null;
  lead_analysis_id: number | null;
  lead_analysis: DealLeadAnalysis | null;
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

/** Metadonnees du badge affiche en footer de chaque card, et de la
 * pastille coloree placee a cote du titre de section. La palette est
 * partagee entre les deux pour rester coherente :
 *   - active   : bleu
 *   - termine  : vert
 *   - abandonne: rouge
 * Les classes Tailwind du badge passent par le mapping statique du
 * composant `LeadAnalysisCard`. Les classes de pastille sont aussi
 * statiques (purge-safe). */
const SECTION_BADGE: Record<SectionKey, LeadAnalysisCardBadge> = {
  active: { label: "Actif", color: "blue" },
  termine: { label: "Terminé", color: "emerald" },
  abandonne: { label: "Abandonné", color: "rose" }
};

/** Pastille coloree (point rond 8px) placee a cote du titre de
 * section. Inspire du markup utilise pour les colonnes du kanban
 * "Analyses des leads" (cf. `analyses-leads/page.tsx`, section
 * `COLUMNS` -> `col.dot`). Classes statiques pour rester purge-safe. */
const SECTION_DOT: Record<SectionKey, string> = {
  active: "bg-blue-500",
  termine: "bg-emerald-500",
  abandonne: "bg-rose-500"
};

export default function PipelineDealsListPage() {
  const { onOpenSidebar } = useProspectionLayout();
  const router = useRouter();
  const confirm = useConfirm();
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
   * Suppression d'un deal avec confirmation. Apres confirm, retire
   * de la liste optimiste puis appelle DELETE. En cas d'echec API,
   * on rollback a l'etat precedent.
   */
  async function deleteDeal(dealId: number, label: string) {
    const ok = await confirm({
      title: `Supprimer « ${label} » du Pipeline ?`,
      description:
        "Le deal, ses taches et son historique seront effaces. La fiche d'analyse liee (si elle existe) restera intacte.",
      confirmLabel: "Supprimer",
      destructive: true
    });
    if (!ok) return;
    const prev = deals;
    setDeals((xs) => xs.filter((d) => d.id !== dealId));
    try {
      const r = await authedFetch(
        `/api/v1/prospection/deals/${dealId}`,
        { method: "DELETE" }
      );
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
    } catch {
      setDeals(prev);
      setError("Suppression échouée.");
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
              onDeleteDeal={deleteDeal}
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
              onDeleteDeal={deleteDeal}
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
              onDeleteDeal={deleteDeal}
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
  onCardClick,
  onDeleteDeal
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
  onDeleteDeal: (id: number, label: string) => void;
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
        {/* Pastille coloree (8px) — bleu/vert/rouge selon la section,
            inspiree des titres de colonnes du kanban Analyses des leads. */}
        <span
          className={`inline-block h-2 w-2 rounded-full ${SECTION_DOT[section]}`}
          aria-hidden
        />
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
            {deals.map((d) => (
              <li key={d.id}>
                <DealCard
                  deal={d}
                  section={section}
                  dragging={dragDealId === d.id}
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
                  onClick={() => {
                    // Si un drop vient d'avoir lieu, on ne navigue
                    // pas. didDrop est remis à false au prochain
                    // dragStart.
                    if (didDrop) {
                      setDidDrop(false);
                      return;
                    }
                    onCardClick(d.id);
                  }}
                  onDelete={() => onDeleteDeal(d.id, d.address)}
                />
              </li>
            ))}
          </ul>
        )
      ) : null}
    </section>
  );
}

/**
 * Card individuelle d'un deal — utilise le composant partage
 * `LeadAnalysisCard` (meme rendu visuel que le kanban "Analyses des
 * leads").
 *
 * Particularites du Pipeline (vs. kanban Analyses) :
 *   - Le badge reflete la section (Actif=blue, Termine=emerald,
 *     Abandonne=rose).
 *   - Pas de bouton "+ Pipeline" (le deal y est deja).
 *   - Le bouton "Fiche" navigue vers `/prospection/pipeline/{id}`
 *     (pas un modal — c'est une vraie page).
 *   - Bouton poubelle (delete) qui passe par le confirm + DELETE
 *     `/prospection/deals/{id}`.
 *
 * Le wrapper externe porte le drag-and-drop natif HTML5 : la card
 * partagee reste agnostique a ces handlers. Si `deal.lead_analysis`
 * est null (deal cree manuellement), le composant partage affiche
 * uniquement l'adresse — on ajoute la date d'ajout sous le badge
 * via un fallback specifique au Pipeline.
 */
function DealCard({
  deal,
  section,
  dragging,
  onDragStart,
  onDragEnd,
  onClick,
  onDelete
}: {
  deal: Deal;
  section: SectionKey;
  dragging: boolean;
  onDragStart: (ev: React.DragEvent<HTMLDivElement>) => void;
  onDragEnd: () => void;
  onClick: () => void;
  onDelete: () => void;
}) {
  const la = deal.lead_analysis;
  const badge = SECTION_BADGE[section];

  // Map du shape `Deal` -> shape attendu par le composant partage.
  // Quand la fiche d'analyse liee est absente, on passe null sur
  // chaque champ metadonnee pour que la card masque gracieusement
  // ces lignes (le composant ne rend que ce qui est non-null).
  const cardData = {
    id: deal.id,
    address: deal.address,
    city: la?.city ?? null,
    nb_logements: la?.nb_logements ?? null,
    asking_price: la?.asking_price ?? null,
    best_refi_amount: la?.best_refi_amount ?? null,
    best_refi_program: la?.best_refi_program ?? null,
    mdf_preteur_b: la?.mdf_preteur_b ?? null
  };

  return (
    <div
      draggable
      onDragStart={onDragStart}
      onDragEnd={onDragEnd}
      tabIndex={0}
      role="link"
      onKeyDown={(ev) => {
        if (ev.key === "Enter" || ev.key === " ") {
          ev.preventDefault();
          onClick();
        }
      }}
      className={`cursor-grab transition active:cursor-grabbing ${dragging ? "opacity-50" : ""}`}
    >
      {/* Lien invisible pour conserver la semantique de navigation
          cote SR / clic-milieu / "ouvrir dans un nouvel onglet". */}
      <Link
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        href={`/prospection/pipeline/${deal.id}` as any}
        draggable={false}
        onClick={(ev) => ev.preventDefault()}
        className="sr-only"
      >
        Ouvrir {deal.address}
      </Link>

      <LeadAnalysisCard
        data={cardData}
        badge={badge}
        onClick={onClick}
        actions={
          <>
            <Link
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
              href={`/prospection/pipeline/${deal.id}` as any}
              className="inline-flex items-center gap-1 rounded-md border border-white/15 bg-brand-950 px-1.5 py-0.5 text-[10px] text-white/70 hover:text-white"
              title="Ouvrir la fiche du deal"
            >
              <Eye className="h-3 w-3" />
              Fiche
            </Link>
            <button
              type="button"
              onClick={onDelete}
              className="inline-flex items-center rounded-md border border-white/15 bg-brand-950 p-0.5 text-white/40 hover:border-rose-400/50 hover:text-rose-300"
              title="Supprimer le deal"
              aria-label="Supprimer le deal"
            >
              <Trash2 className="h-3 w-3" />
            </button>
          </>
        }
      />

      {/* Fallback Pipeline : deal sans fiche d'analyse — on montre
          la date d'ajout sous la card pour donner un repere temporel. */}
      {la == null ? (
        <p className="mt-1 px-2.5 text-[10px] text-white/40">
          Ajouté le{" "}
          {new Date(deal.created_at).toLocaleDateString("fr-CA", {
            day: "2-digit",
            month: "short",
            year: "numeric"
          })}
        </p>
      ) : null}
    </div>
  );
}
