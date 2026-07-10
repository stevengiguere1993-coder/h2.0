"use client";

import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState
} from "react";
import {
  Briefcase,
  Building2,
  ChevronDown,
  ChevronRight,
  Download,
  GripVertical,
  LayoutGrid,
  Link2,
  Loader2,
  Plus,
  Save,
  Sparkles,
  Star,
  Trash2,
  User as UserIcon,
  Table2,
  UserCog,
  Users,
  Workflow,
  X
} from "lucide-react";

import { authedFetch } from "@/lib/auth";
import { MultiSelectDropdown } from "@/components/multi-select-dropdown";
import { PageDriveSection } from "@/components/drive/PageDriveSection";
import { RessourcesDispatchView } from "@/components/ressources-dispatch-view";
import { RolesResponsibilitiesView } from "@/components/roles-responsibilities-view";
import { QGTopbar, useEntreprisesLayout } from "../layout";

/**
 * Page Organigramme — inspirée du schéma papier de Steven.
 *
 * Affiche l'arbre des entreprises / départements / rôles / services
 * du groupe en colonnes (top-level), avec sous-nœuds en cascade dans
 * chaque colonne. Chaque nœud :
 *  - kind (company / dept / role / service / task)
 *  - label
 *  - lien optionnel à une entreprise
 *  - assignation (employé interne OU texte externe « Freelance », etc.)
 *  - co-détenteurs (autres entreprises qui possèdent aussi ce nœud)
 *
 * Les entreprises s'importent en un clic (« Importer les entreprises »)
 * comme nœuds `company` à plat, puis se réorganisent par glisser-déposer
 * pour bâtir la hiérarchie de détention (qui détient quoi) et de
 * fonction (qui fait quoi) — entreprises et départements/rôles vivent
 * dans le même arbre. Le détenteur principal donne la position dans
 * l'arbre ; les co-détenteurs s'affichent en badges sur la carte.
 */

type OrgNode = {
  id: number;
  parent_id: number | null;
  position: number;
  kind: string;
  label: string;
  description: string | null;
  entreprise_id: number | null;
  assignee_employe_id: number | null;
  assignee_user_id: number | null;
  assignee_external_name: string | null;
  co_owner_node_ids: number[];
  pos_x: number | null;
  pos_y: number | null;
  execution_tier: string | null;
  created_at: string;
  updated_at: string;
};

type Employe = {
  id: number;
  full_name: string;
  email?: string | null;
  role?: string | null;
  active?: boolean;
};

type DropTarget = { id: number; mode: "into" | "before" };

type Dnd = {
  dragId: number | null;
  dropTarget: DropTarget | null;
  draggedSubtree: Set<number>;
  onDragStartNode: (id: number) => void;
  onDragEndNode: () => void;
  onHover: (t: DropTarget | null) => void;
  onDrop: () => void;
  onDropRootEnd: () => void;
};

const KIND_LABELS: Record<string, { label: string; cls: string }> = {
  company: {
    label: "Entreprise",
    cls: "bg-indigo-500/15 text-indigo-300 border-indigo-500/30"
  },
  person: {
    label: "Personne",
    cls: "bg-fuchsia-500/15 text-fuchsia-300 border-fuchsia-500/30"
  },
  dept: {
    label: "Département",
    cls: "bg-violet-500/15 text-violet-300 border-violet-500/30"
  },
  role: {
    label: "Rôle",
    cls: "bg-sky-500/15 text-sky-300 border-sky-500/30"
  },
  task: {
    label: "Tâche",
    cls: "bg-amber-500/15 text-amber-300 border-amber-500/30"
  },
  service: {
    label: "Service partagé",
    cls: "bg-emerald-500/15 text-emerald-300 border-emerald-500/30"
  }
};

// Niveau d'exécution : qui doit prendre en charge le rôle / la tâche.
// Aide à voir d'un coup d'œil ce qui doit rester au dirigeant, ce qui
// est délégable à un adjoint, et ce qui peut passer à l'adjoint
// virtuel (automatisable).
const TIER_LABELS: Record<
  string,
  { label: string; short: string; cls: string }
> = {
  direction: {
    label: "Direction",
    short: "Direction",
    cls: "bg-rose-500/15 text-rose-300 border-rose-500/30"
  },
  adjoint: {
    label: "Adjoint",
    short: "Adjoint",
    cls: "bg-orange-500/15 text-orange-300 border-orange-500/30"
  },
  adjoint_virtuel: {
    label: "Adjoint virtuel",
    short: "Adj. virtuel",
    cls: "bg-teal-500/15 text-teal-300 border-teal-500/30"
  }
};

export default function OrganigrammePage() {
  const { entreprises } = useEntreprisesLayout();
  const [nodes, setNodes] = useState<OrgNode[]>([]);
  const [employes, setEmployes] = useState<Employe[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [creatingTop, setCreatingTop] = useState(false);
  const [newTopLabel, setNewTopLabel] = useState("");
  const [seeding, setSeeding] = useState(false);
  const [importing, setImporting] = useState(false);

  // Vue : tableau « Rôles & responsabilités » (par défaut, lisible),
  // arbre en colonnes (édition fine de la hiérarchie complète) ou
  // canvas libre type Miro (bulles déplaçables + flèches, idéal pour
  // entreprises + investisseurs). Les trois vues partagent les mêmes
  // données (parent_id / co_owner_node_ids) → toujours synchronisées.
  const [viewMode, setViewMode] = useState<
    "canvas" | "columns" | "roles" | "ressources"
  >("canvas");

  // Zoom de la vue colonnes (le canvas a son propre zoom interne) —
  // pour une vue plus globale au besoin. Ajustable via les boutons
  // ou Ctrl/Cmd + molette.
  const [columnsZoom, setColumnsZoom] = useState(1);
  const columnsRef = useRef<HTMLDivElement | null>(null);

  // Ctrl/Cmd + molette → zoom de la vue colonnes (molette simple =
  // défilement normal). Listener non-passif posé à la main car React
  // attache `onWheel` en passif (preventDefault impossible sinon).
  useEffect(() => {
    const el = columnsRef.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      if (!e.ctrlKey && !e.metaKey) return;
      e.preventDefault();
      setColumnsZoom((z) =>
        Math.min(
          2,
          Math.max(0.4, Math.round((z - e.deltaY * 0.0015) * 100) / 100)
        )
      );
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, [viewMode]);

  // État du glisser-déposer.
  const [dragId, setDragId] = useState<number | null>(null);
  const [dropTarget, setDropTarget] = useState<DropTarget | null>(null);

  // Entreprise mère du groupe — sert à mettre en évidence SON nœud
  // dans l'arbre (étoile + bordure accent), plutôt qu'un bandeau
  // séparé non interactif.
  const parentEntId = useMemo(() => {
    const e =
      entreprises.find(
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        (x) => (x as any).is_parent_company === true
      ) || entreprises.find((x) => /mgv\s*invest/i.test(x.name));
    return e ? e.id : null;
  }, [entreprises]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [n, e] = await Promise.all([
        authedFetch("/api/v1/org-nodes"),
        authedFetch("/api/v1/employes?limit=500")
      ]);
      if (n.ok) setNodes((await n.json()) as OrgNode[]);
      if (e.ok) setEmployes((await e.json()) as Employe[]);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function seedDefault(force: boolean) {
    setSeeding(true);
    setError(null);
    try {
      const r = await authedFetch(
        `/api/v1/org-nodes/seed-default${force ? "?force=true" : ""}`,
        { method: "POST" }
      );
      if (!r.ok) {
        const txt = await r.text();
        throw new Error(txt.slice(0, 200) || `HTTP ${r.status}`);
      }
      await load();
    } catch (e) {
      setError(`Import échoué : ${(e as Error).message}`);
    } finally {
      setSeeding(false);
    }
  }

  async function importEntreprises() {
    setImporting(true);
    setError(null);
    try {
      const r = await authedFetch("/api/v1/org-nodes/import-entreprises", {
        method: "POST"
      });
      if (!r.ok) {
        const txt = await r.text();
        throw new Error(txt.slice(0, 200) || `HTTP ${r.status}`);
      }
      setNodes((await r.json()) as OrgNode[]);
    } catch (e) {
      setError(`Import des entreprises échoué : ${(e as Error).message}`);
    } finally {
      setImporting(false);
    }
  }

  // Sous-ensemble « structurel » : entreprises + investisseurs + nœuds
  // libres. On exclut explicitement les départements, rôles et tâches
  // — ils vivent dans les vues « Rôles » et « Ressources » (panneau
  // de dispatch), pas dans l'arbre d'investissement / le canvas.
  const structuralNodes = useMemo(
    () =>
      nodes.filter(
        (n) => n.kind !== "dept" && n.kind !== "role" && n.kind !== "task"
      ),
    [nodes]
  );

  // Index : parent_id → enfants triés par position (vues canvas + colonnes,
  // donc à partir du sous-ensemble structurel uniquement).
  const byParent = useMemo(() => {
    const m = new Map<number | null, OrgNode[]>();
    for (const n of structuralNodes) {
      const arr = m.get(n.parent_id) || [];
      arr.push(n);
      m.set(n.parent_id, arr);
    }
    for (const arr of m.values()) {
      arr.sort((a, b) => a.position - b.position);
    }
    return m;
  }, [structuralNodes]);

  // Placement dans l'arbre par « détenteur principal » :
  //  • détenteur principal d'un nœud = son parent_id si défini, sinon
  //    son 1er co-détenteur. Un nœud n'est une VRAIE racine que s'il
  //    n'a AUCUN détenteur → une entreprise co-détenue ne flotte
  //    jamais comme entité distincte.
  //  • byPrimary   : détenteur principal → nœuds placés sous lui
  //  • bySecondary : détenteur → nœuds qu'il co-détient sans en être
  //    le détenteur principal (affichés en « Co-détenu ici »).
  const { byPrimary, bySecondary } = useMemo(() => {
    const prim = new Map<number | null, OrgNode[]>();
    const sec = new Map<number, OrgNode[]>();
    for (const n of structuralNodes) {
      const co = n.co_owner_node_ids || [];
      const primary = n.parent_id ?? (co.length > 0 ? co[0] : null);
      const pArr = prim.get(primary);
      if (pArr) pArr.push(n);
      else prim.set(primary, [n]);
      const secondaries = n.parent_id != null ? co : co.slice(1);
      for (const h of secondaries) {
        const sArr = sec.get(h);
        if (sArr) sArr.push(n);
        else sec.set(h, [n]);
      }
    }
    for (const arr of prim.values())
      arr.sort((a, b) => a.position - b.position);
    for (const arr of sec.values())
      arr.sort((a, b) => a.position - b.position);
    return { byPrimary: prim, bySecondary: sec };
  }, [structuralNodes]);

  // Racines de l'arbre : les vrais top-level (aucun détenteur) + un
  // filet de sécurité — si des co-détentions forment un cycle
  // déconnecté des racines, les nœuds concernés ne seraient sous
  // personne ; on les rattache comme racines pour qu'ils restent
  // toujours visibles.
  const topLevel = useMemo(() => {
    const roots = byPrimary.get(null) || [];
    const reachable = new Set<number>();
    const stack = roots.map((r) => r.id);
    while (stack.length) {
      const id = stack.pop() as number;
      if (reachable.has(id)) continue;
      reachable.add(id);
      for (const c of byPrimary.get(id) || []) stack.push(c.id);
    }
    const orphans = structuralNodes.filter(
      (n) => !reachable.has(n.id)
    );
    return orphans.length > 0 ? [...roots, ...orphans] : roots;
  }, [byPrimary, structuralNodes]);

  // Sous-arbre du nœud en cours de glissement — on l'exclut des cibles
  // de dépôt valides (un nœud ne peut pas atterrir sur lui-même ni
  // sur un de ses descendants).
  const draggedSubtree = useMemo(() => {
    const s = new Set<number>();
    if (dragId == null) return s;
    const stack = [dragId];
    while (stack.length) {
      const cur = stack.pop() as number;
      if (s.has(cur)) continue;
      s.add(cur);
      for (const c of byParent.get(cur) || []) stack.push(c.id);
    }
    return s;
  }, [dragId, byParent]);

  async function moveNode(
    id: number,
    parentId: number | null,
    position: number
  ) {
    try {
      const r = await authedFetch(`/api/v1/org-nodes/${id}/move`, {
        method: "POST",
        body: JSON.stringify({ parent_id: parentId, position })
      });
      if (!r.ok) {
        const txt = await r.text();
        throw new Error(txt.slice(0, 160) || `HTTP ${r.status}`);
      }
      setNodes((await r.json()) as OrgNode[]);
    } catch (e) {
      setError(`Déplacement échoué : ${(e as Error).message}`);
    }
  }

  function handleDrop() {
    const dId = dragId;
    const dt = dropTarget;
    setDragId(null);
    setDropTarget(null);
    if (dId == null || !dt || dt.id === dId) return;
    if (draggedSubtree.has(dt.id)) return;
    const target = nodes.find((n) => n.id === dt.id);
    if (!target) return;

    if (dt.mode === "into") {
      const kids = (byParent.get(dt.id) || []).filter((n) => n.id !== dId);
      void moveNode(dId, dt.id, kids.length);
    } else {
      // Insère avant `target`, sous le même parent. La position est
      // l'index de `target` dans la fratrie une fois le nœud déplacé
      // retiré (le backend recalcule de toute façon).
      const sibs = (byParent.get(target.parent_id) || []).filter(
        (n) => n.id !== dId
      );
      const idx = sibs.findIndex((n) => n.id === target.id);
      void moveNode(dId, target.parent_id, idx < 0 ? sibs.length : idx);
    }
  }

  function handleDropRootEnd() {
    const dId = dragId;
    setDragId(null);
    setDropTarget(null);
    if (dId == null) return;
    const roots = (byParent.get(null) || []).filter((n) => n.id !== dId);
    void moveNode(dId, null, roots.length);
  }

  const dnd: Dnd = {
    dragId,
    dropTarget,
    draggedSubtree,
    onDragStartNode: (id) => setDragId(id),
    onDragEndNode: () => {
      setDragId(null);
      setDropTarget(null);
    },
    onHover: (t) => setDropTarget(t),
    onDrop: handleDrop,
    onDropRootEnd: handleDropRootEnd
  };

  async function createNode(
    parent_id: number | null,
    label: string,
    kind = "dept",
    extra?: { description?: string | null; execution_tier?: string | null }
  ) {
    if (!label.trim()) return;
    try {
      const r = await authedFetch("/api/v1/org-nodes", {
        method: "POST",
        body: JSON.stringify({
          parent_id,
          label: label.trim(),
          kind,
          ...(extra?.description ? { description: extra.description } : {}),
          ...(extra?.execution_tier
            ? { execution_tier: extra.execution_tier }
            : {})
        })
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const created = (await r.json()) as OrgNode;
      setNodes((prev) => [...prev, created]);
      return created;
    } catch (e) {
      setError(`Création échouée : ${(e as Error).message}`);
    }
  }

  async function patchNode(id: number, patch: Partial<OrgNode>) {
    setNodes((prev) =>
      prev.map((n) => (n.id === id ? { ...n, ...patch } : n))
    );
    try {
      await authedFetch(`/api/v1/org-nodes/${id}`, {
        method: "PATCH",
        body: JSON.stringify(patch)
      });
    } catch {
      /* silent */
    }
  }

  async function deleteNode(id: number) {
    if (!window.confirm("Supprimer ce nœud et tous ses enfants ?")) return;
    try {
      const r = await authedFetch(`/api/v1/org-nodes/${id}`, {
        method: "DELETE"
      });
      if (!r.ok && r.status !== 204) throw new Error();
      // Cascade côté DB → on retire tout le sous-arbre côté state.
      const idsToRemove = new Set<number>([id]);
      let changed = true;
      while (changed) {
        changed = false;
        for (const n of nodes) {
          if (
            n.parent_id != null &&
            idsToRemove.has(n.parent_id) &&
            !idsToRemove.has(n.id)
          ) {
            idsToRemove.add(n.id);
            changed = true;
          }
        }
      }
      setNodes((prev) => prev.filter((n) => !idsToRemove.has(n.id)));
    } catch {
      setError("Suppression échouée.");
    }
  }

  async function submitTop(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setCreatingTop(true);
    try {
      await createNode(null, newTopLabel, "dept");
      setNewTopLabel("");
    } finally {
      setCreatingTop(false);
    }
  }

  return (
    <>
      <QGTopbar
        greeting={
          <span className="inline-flex items-center gap-2">
            <Users className="h-4 w-4 text-accent-500" />
            Organigramme
          </span>
        }
        subtitle="Entreprises & investisseurs (structure du groupe) — voir les rôles et le dispatch des ressources dans les onglets dédiés"
        rightSlot={
          <div
            className="inline-flex overflow-hidden rounded-lg border"
            style={{ borderColor: "var(--qg-border)" }}
          >
            <button
              type="button"
              onClick={() => setViewMode("canvas")}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold transition"
              style={{
                backgroundColor:
                  viewMode === "canvas"
                    ? "var(--qg-accent)"
                    : "var(--qg-card-bg)",
                color:
                  viewMode === "canvas"
                    ? "var(--qg-accent-ink, #0a0a0b)"
                    : "var(--qg-text-soft)"
              }}
              title="Canvas libre — organigramme entreprises + investisseurs"
            >
              <Workflow className="h-3.5 w-3.5" />
              Organigramme
            </button>
            <button
              type="button"
              onClick={() => setViewMode("columns")}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold transition"
              style={{
                backgroundColor:
                  viewMode === "columns"
                    ? "var(--qg-accent)"
                    : "var(--qg-card-bg)",
                color:
                  viewMode === "columns"
                    ? "var(--qg-accent-ink, #0a0a0b)"
                    : "var(--qg-text-soft)"
              }}
              title="Arbre des entreprises + investisseurs en colonnes (édition hiérarchie)"
            >
              <LayoutGrid className="h-3.5 w-3.5" />
              Arbre complet
            </button>
            <button
              type="button"
              onClick={() => setViewMode("roles")}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold transition"
              style={{
                backgroundColor:
                  viewMode === "roles"
                    ? "var(--qg-accent)"
                    : "var(--qg-card-bg)",
                color:
                  viewMode === "roles"
                    ? "var(--qg-accent-ink, #0a0a0b)"
                    : "var(--qg-text-soft)"
              }}
              title="Tableau des rôles + responsabilités (dispatch)"
            >
              <Table2 className="h-3.5 w-3.5" />
              Rôles
            </button>
            <button
              type="button"
              onClick={() => setViewMode("ressources")}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold transition"
              style={{
                backgroundColor:
                  viewMode === "ressources"
                    ? "var(--qg-accent)"
                    : "var(--qg-card-bg)",
                color:
                  viewMode === "ressources"
                    ? "var(--qg-accent-ink, #0a0a0b)"
                    : "var(--qg-text-soft)"
              }}
              title="Dispatch des rôles par employé — voir la charge et les disponibilités"
            >
              <UserCog className="h-3.5 w-3.5" />
              Ressources
            </button>
          </div>
        }
      />

      <div className="p-4 lg:p-6">
        <PageDriveSection
          pageKey="page:entreprises:organigramme"
          pole="Gestion d'entreprises"
          label="Organigramme"
          route="/entreprises/organigramme"
        />
        {error ? (
          <p className="mb-3 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-600">
            {error}
          </p>
        ) : null}

        {loading ? (
          <div className="flex items-center justify-center py-12">
            <Loader2 className="h-6 w-6 animate-spin text-accent-500" />
          </div>
        ) : (
          <>
            {/* Bandeau de création + import des entreprises */}
            <form
              onSubmit={submitTop}
              className="mb-2 flex flex-wrap items-center gap-2 rounded-xl border p-3"
              style={{
                borderColor: "var(--qg-border)",
                backgroundColor: "var(--qg-card-bg)"
              }}
            >
              <Plus className="h-4 w-4 text-accent-500" />
              <input
                value={newTopLabel}
                onChange={(e) => setNewTopLabel(e.target.value)}
                placeholder="Nouvelle branche (ex. Construction, Dev logiciel, Gestion Immo, Prospection, Comptabilité…)"
                className="input flex-1 min-w-[220px] text-sm"
              />
              <button
                type="submit"
                disabled={creatingTop || !newTopLabel.trim()}
                className="btn-accent inline-flex items-center gap-1 text-xs disabled:opacity-50"
              >
                {creatingTop ? (
                  <Loader2 className="h-3 w-3 animate-spin" />
                ) : (
                  <Plus className="h-3 w-3" />
                )}
                Ajouter
              </button>
              <button
                type="button"
                onClick={() => void importEntreprises()}
                disabled={importing}
                className="btn-secondary btn-sm disabled:opacity-50"
                title="Crée un nœud pour chaque entreprise du groupe non encore présente dans l'organigramme. Tu les replaces ensuite par glisser-déposer."
              >
                {importing ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Download className="h-3.5 w-3.5" />
                )}
                Importer les entreprises
              </button>
            </form>

            {topLevel.length > 0 && viewMode === "columns" ? (
              <p
                className="mb-4 text-[11px]"
                style={{ color: "var(--qg-text-soft)" }}
              >
                Glisse une carte <strong>sur</strong> une autre (n&apos;importe
                où dans sa colonne) pour qu&apos;elle en devienne l&apos;enfant
                — changement de détenteur. Glisse <strong>entre deux</strong>{" "}
                cartes pour les réordonner. Plusieurs détenteurs ? Ouvre la
                carte (chevron) → <strong>Co-détenteurs</strong>.
              </p>
            ) : null}
            {topLevel.length > 0 && viewMode === "canvas" ? (
              <p
                className="mb-3 text-[11px]"
                style={{ color: "var(--qg-text-soft)" }}
              >
                Déplace les bulles — elles s&apos;aimantent à la grille
                pour rester alignées. Tire depuis le point{" "}
                <span
                  className="inline-block h-2 w-2 rounded-full align-middle"
                  style={{ backgroundColor: "var(--qg-accent)" }}
                />{" "}
                d&apos;une bulle vers une autre pour créer une flèche de
                détention. Survole une flèche pour la supprimer. Chaque
                détenteur — principal ou co-détenteur, même minoritaire —
                est un propriétaire à part entière.
              </p>
            ) : null}

            {topLevel.length === 0 ? (
              <div
                className="rounded-2xl border border-dashed p-6 text-center text-sm"
                style={{
                  borderColor: "var(--qg-border-soft)",
                  color: "var(--qg-text-muted)"
                }}
              >
                <p>Aucun nœud d&apos;organigramme pour l&apos;instant.</p>
                <div className="mt-3 flex flex-wrap items-center justify-center gap-2">
                  <button
                    type="button"
                    onClick={() => void importEntreprises()}
                    disabled={importing}
                    className="btn-accent inline-flex items-center gap-1.5 text-sm disabled:opacity-50"
                    title="Crée un nœud pour chaque entreprise du groupe."
                  >
                    {importing ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    ) : (
                      <Download className="h-3.5 w-3.5" />
                    )}
                    Importer les entreprises
                  </button>
                  <button
                    type="button"
                    onClick={() => void seedDefault(false)}
                    disabled={seeding}
                    className="btn-secondary btn-sm disabled:opacity-50"
                    title="Crée la structure de départ basée sur ton carnet (Construction, Dev logiciel, Gestion Immo, Prospection, Dev Immo / Aguci, Comptabilité + rôles et tâches)"
                  >
                    {seeding ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    ) : (
                      <Save className="h-3.5 w-3.5" />
                    )}
                    Importer le canevas du carnet
                  </button>
                </div>
                <span
                  className="mt-2 block text-[10px]"
                  style={{ color: "var(--qg-text-soft)" }}
                >
                  ou ajoute manuellement une branche ci-dessus
                </span>
              </div>
            ) : viewMode === "roles" ? (
              <>
                <p
                  className="mb-3 text-[11px]"
                  style={{ color: "var(--qg-text-soft)" }}
                >
                  Liste tous les rôles du groupe. Filtre par pôle / statut
                  / tier, ou cherche par nom. Sélectionne une ligne pour
                  attribuer le titulaire et éditer ses responsabilités
                  (anciennement « tâches » du seed canonique). Bascule
                  sur <strong>Organigramme</strong> pour la vue canvas
                  des entreprises + investisseurs.
                </p>
                <RolesResponsibilitiesView
                  nodes={nodes}
                  employes={employes}
                  onPatch={patchNode}
                  onDelete={deleteNode}
                  onCreate={createNode}
                />
              </>
            ) : viewMode === "ressources" ? (
              <>
                <p
                  className="mb-3 text-[11px]"
                  style={{ color: "var(--qg-text-soft)" }}
                >
                  Vue inverse : qui tient quoi. Liste des employés
                  triés par charge (rouge = ≥ 4 rôles), sélectionne pour
                  voir leur portefeuille et libérer des rôles. Le
                  panneau « Rôles à pourvoir » en bas permet d&apos;attribuer
                  les vacants à l&apos;employé sélectionné en un clic.
                </p>
                <RessourcesDispatchView
                  nodes={nodes}
                  employes={employes}
                  onPatch={patchNode}
                />
              </>
            ) : viewMode === "columns" ? (
              <>
                <div className="mb-2 flex justify-end">
                  <ZoomControl
                    zoom={columnsZoom}
                    setZoom={setColumnsZoom}
                  />
                </div>
                <div
                  ref={columnsRef}
                  className="flex items-stretch gap-1 overflow-x-auto pb-4"
                  style={{ zoom: columnsZoom }}
                >
                {topLevel.map((n) => (
                  <div key={n.id} className="flex items-stretch">
                    <DropBar targetId={n.id} dnd={dnd} vertical />
                    <ColumnView
                      node={n}
                      byPrimary={byPrimary}
                      bySecondary={bySecondary}
                      allNodes={nodes}
                      entreprises={entreprises}
                      employes={employes}
                      parentEntId={parentEntId}
                      dnd={dnd}
                      onCreate={createNode}
                      onPatch={patchNode}
                      onDelete={deleteNode}
                    />
                  </div>
                ))}
                {/* Zone de dépôt finale : ramène un nœud à la racine. */}
                {dragId != null ? (
                  <div
                    onDragOver={(e) => {
                      e.preventDefault();
                      dnd.onHover(null);
                    }}
                    onDrop={(e) => {
                      e.preventDefault();
                      dnd.onDropRootEnd();
                    }}
                    className="flex w-[150px] shrink-0 items-center justify-center rounded-xl border border-dashed text-center text-[11px]"
                    style={{
                      borderColor: "var(--qg-accent)",
                      color: "var(--qg-text-soft)"
                    }}
                  >
                    Déposer ici →<br />racine du groupe
                  </div>
                ) : null}
                </div>
              </>
            ) : (
              <CanvasView
                /* Vue canvas = organigramme structurel : seulement les
                   entreprises et investisseurs. Les départements, rôles
                   et responsabilités vivent dans les onglets « Rôles »
                   et « Ressources ». */
                nodes={structuralNodes}
                entreprises={entreprises}
                employes={employes}
                parentEntId={parentEntId}
                onCreate={createNode}
                onPatch={patchNode}
                onMove={moveNode}
                onDelete={deleteNode}
              />
            )}
          </>
        )}
      </div>
    </>
  );
}

// ─── Barre de dépôt fine (réordonner / re-parenter) ──────────────

function DropBar({
  targetId,
  dnd,
  vertical
}: {
  targetId: number;
  dnd: Dnd;
  vertical?: boolean;
}) {
  if (dnd.dragId == null) return null;
  if (dnd.draggedSubtree.has(targetId)) {
    // Place-holder neutre : garde l'espacement sans être droppable.
    return <div className={vertical ? "w-1 shrink-0" : "h-1.5"} />;
  }
  const active =
    dnd.dropTarget?.id === targetId && dnd.dropTarget.mode === "before";
  return (
    <div
      onDragOver={(e) => {
        e.preventDefault();
        e.stopPropagation();
        if (!active) dnd.onHover({ id: targetId, mode: "before" });
      }}
      onDrop={(e) => {
        e.preventDefault();
        e.stopPropagation();
        dnd.onDrop();
      }}
      className={vertical ? "w-2 shrink-0" : "h-2"}
      style={{
        backgroundColor: active ? "var(--qg-accent)" : "transparent",
        borderRadius: 4
      }}
    />
  );
}

// ─── Contrôle de zoom (vues colonnes & canvas) ───────────────────

function ZoomControl({
  zoom,
  setZoom
}: {
  zoom: number;
  setZoom: (z: number) => void;
}) {
  const clamp = (z: number) =>
    Math.min(2, Math.max(0.4, Math.round(z * 10) / 10));
  return (
    <div
      className="inline-flex items-center overflow-hidden rounded-lg border"
      title="Zoom — ou Ctrl/Cmd + molette"
      style={{
        borderColor: "var(--qg-border)",
        backgroundColor: "var(--qg-card-bg)"
      }}
    >
      <button
        type="button"
        onClick={() => setZoom(clamp(zoom - 0.1))}
        className="px-2.5 py-1 text-sm font-bold leading-none hover:bg-accent-500/10"
        style={{ color: "var(--qg-text-soft)" }}
        title="Dézoomer"
        aria-label="Dézoomer"
      >
        −
      </button>
      <button
        type="button"
        onClick={() => setZoom(1)}
        className="min-w-[46px] border-x py-1 text-[11px] font-semibold leading-none hover:bg-accent-500/10"
        style={{
          borderColor: "var(--qg-border)",
          color: "var(--qg-text-soft)"
        }}
        title="Réinitialiser le zoom (100 %)"
      >
        {Math.round(zoom * 100)}%
      </button>
      <button
        type="button"
        onClick={() => setZoom(clamp(zoom + 0.1))}
        className="px-2.5 py-1 text-sm font-bold leading-none hover:bg-accent-500/10"
        style={{ color: "var(--qg-text-soft)" }}
        title="Zoomer"
        aria-label="Zoomer"
      >
        +
      </button>
    </div>
  );
}

// ─── Une colonne = une branche top-level + son arbre ─────────────

function ColumnView({
  node,
  byPrimary,
  bySecondary,
  allNodes,
  entreprises,
  employes,
  parentEntId,
  dnd,
  onCreate,
  onPatch,
  onDelete
}: {
  node: OrgNode;
  byPrimary: Map<number | null, OrgNode[]>;
  bySecondary: Map<number, OrgNode[]>;
  allNodes: OrgNode[];
  entreprises: Array<{ id: number; name: string }>;
  employes: Employe[];
  parentEntId: number | null;
  dnd: Dnd;
  onCreate: (
    parent_id: number | null,
    label: string,
    kind?: string,
    extra?: { description?: string | null; execution_tier?: string | null }
  ) => Promise<OrgNode | undefined>;
  onPatch: (id: number, patch: Partial<OrgNode>) => Promise<void>;
  onDelete: (id: number) => Promise<void>;
}) {
  // La colonne entière est une grande cible de dépôt « dans cette
  // entreprise » : déposer n'importe où dans la carte (hors d'un
  // sous-nœud précis, qui lui stoppe la propagation) re-parente le
  // nœud glissé sous la racine de la colonne. Rend le glisser-déposer
  // d'une entreprise vers une autre beaucoup plus facile.
  const colDroppable =
    dnd.dragId != null && !dnd.draggedSubtree.has(node.id);
  const isColTarget =
    dnd.dropTarget?.id === node.id && dnd.dropTarget.mode === "into";

  return (
    <div
      onDragOver={(e) => {
        if (!colDroppable) return;
        e.preventDefault();
        if (!isColTarget) dnd.onHover({ id: node.id, mode: "into" });
      }}
      onDrop={(e) => {
        if (!colDroppable) return;
        e.preventDefault();
        dnd.onDrop();
      }}
      className="w-[300px] shrink-0 rounded-xl border p-3 transition"
      style={{
        borderColor: isColTarget ? "var(--qg-accent)" : "var(--qg-border)",
        backgroundColor: "var(--qg-card-bg)",
        boxShadow: isColTarget
          ? "0 0 0 2px var(--qg-accent) inset"
          : "none"
      }}
    >
      <NodeRow
        node={node}
        allNodes={allNodes}
        entreprises={entreprises}
        employes={employes}
        parentEntId={parentEntId}
        dnd={dnd}
        onCreate={onCreate}
        onPatch={onPatch}
        onDelete={onDelete}
        depth={0}
      />
      <Children
        parentId={node.id}
        byPrimary={byPrimary}
        bySecondary={bySecondary}
        ancestors={new Set([node.id])}
        allNodes={allNodes}
        entreprises={entreprises}
        employes={employes}
        parentEntId={parentEntId}
        dnd={dnd}
        onCreate={onCreate}
        onPatch={onPatch}
        onDelete={onDelete}
        depth={1}
      />
    </div>
  );
}

function Children({
  parentId,
  byPrimary,
  bySecondary,
  ancestors,
  allNodes,
  entreprises,
  employes,
  parentEntId,
  dnd,
  onCreate,
  onPatch,
  onDelete,
  depth
}: {
  parentId: number;
  byPrimary: Map<number | null, OrgNode[]>;
  bySecondary: Map<number, OrgNode[]>;
  ancestors: Set<number>;
  allNodes: OrgNode[];
  entreprises: Array<{ id: number; name: string }>;
  employes: Employe[];
  parentEntId: number | null;
  dnd: Dnd;
  onCreate: (
    parent_id: number | null,
    label: string,
    kind?: string,
    extra?: { description?: string | null; execution_tier?: string | null }
  ) => Promise<OrgNode | undefined>;
  onPatch: (id: number, patch: Partial<OrgNode>) => Promise<void>;
  onDelete: (id: number) => Promise<void>;
  depth: number;
}) {
  // Nœuds dont CE nœud est le détenteur principal (placement de base
  // dans l'arbre) ET nœuds qu'il co-détient sans en être le principal
  // (« Co-détenu ici »). La détention multiple reste visible comme de
  // vraies cartes, et une entité co-détenue n'apparaît jamais comme
  // racine distincte.
  const directChildren = byPrimary.get(parentId) || [];
  const directIds = new Set(directChildren.map((c) => c.id));
  const coDetained = (bySecondary.get(parentId) || []).filter(
    (c) => !directIds.has(c.id)
  );

  const [adding, setAdding] = useState(false);
  const [newLabel, setNewLabel] = useState("");
  const defaultKind = depth >= 2 ? "task" : "role";

  async function submitChild() {
    if (!newLabel.trim()) return;
    await onCreate(parentId, newLabel, defaultKind);
    setNewLabel("");
    setAdding(false);
  }

  function renderNode(c: OrgNode, coDetainedHere: boolean) {
    // Garde anti-boucle : si le nœud est déjà un ancêtre de cette
    // branche (co-détentions croisées), on l'affiche sans redescendre.
    const alreadyShown = ancestors.has(c.id);
    // Vrai enfant direct (parent_id pointe ici) → barre de dépôt pour
    // réordonner. Un nœud placé ici via sa 1re co-détention (faute de
    // parent_id) reste une carte normale, mais sans barre de dépôt.
    const realChild = c.parent_id === parentId;
    return (
      <div key={c.id}>
        {coDetainedHere ? (
          <div
            className="mb-0.5 inline-flex items-center gap-0.5 text-[9px] font-semibold uppercase tracking-wide"
            style={{ color: "var(--qg-text-soft)" }}
          >
            <Link2 className="h-2.5 w-2.5" />
            Co-détenu ici
          </div>
        ) : realChild ? (
          <DropBar targetId={c.id} dnd={dnd} />
        ) : null}
        <NodeRow
          node={c}
          allNodes={allNodes}
          entreprises={entreprises}
          employes={employes}
          parentEntId={parentEntId}
          dnd={dnd}
          onCreate={onCreate}
          onPatch={onPatch}
          onDelete={onDelete}
          depth={depth}
        />
        {alreadyShown ? (
          <div
            className="ml-3 mt-0.5 text-[10px] italic"
            style={{ color: "var(--qg-text-soft)" }}
          >
            ↑ déjà déployé plus haut dans cette branche
          </div>
        ) : (
          <Children
            parentId={c.id}
            byPrimary={byPrimary}
            bySecondary={bySecondary}
            ancestors={new Set(ancestors).add(c.id)}
            allNodes={allNodes}
            entreprises={entreprises}
            employes={employes}
            parentEntId={parentEntId}
            dnd={dnd}
            onCreate={onCreate}
            onPatch={onPatch}
            onDelete={onDelete}
            depth={depth + 1}
          />
        )}
      </div>
    );
  }

  return (
    <div
      className="mt-2 space-y-1.5"
      style={{
        paddingLeft: depth > 0 ? "0.75rem" : 0,
        borderLeft:
          depth > 0 ? `2px solid var(--qg-border-soft)` : "none"
      }}
    >
      {directChildren.map((c) => renderNode(c, false))}
      {coDetained.map((c) => renderNode(c, true))}
      {adding ? (
        <div className="flex items-center gap-1">
          <input
            autoFocus
            value={newLabel}
            onChange={(e) => setNewLabel(e.target.value)}
            placeholder={
              defaultKind === "task"
                ? "Nouvelle tâche…"
                : "Nouveau rôle / sous-département…"
            }
            onKeyDown={(e) => {
              if (e.key === "Enter") void submitChild();
              else if (e.key === "Escape") {
                setAdding(false);
                setNewLabel("");
              }
            }}
            onBlur={() => {
              if (!newLabel.trim()) setAdding(false);
            }}
            className="input flex-1 text-[11px]"
          />
          <button
            type="button"
            onClick={() => void submitChild()}
            className="rounded p-1 text-accent-400 hover:bg-accent-500/10"
          >
            <Plus className="h-3 w-3" />
          </button>
        </div>
      ) : (
        <button
          type="button"
          onClick={() => setAdding(true)}
          className="inline-flex items-center gap-1 rounded px-1 py-0.5 text-[10px] text-white/40 hover:text-accent-400"
        >
          <Plus className="h-2.5 w-2.5" />
          Ajouter sous-élément
        </button>
      )}
    </div>
  );
}

type RoleSuggestion = {
  label: string;
  kind: string;
  description: string | null;
  execution_tier: string | null;
};

// Bloc d'édition partagé par la vue colonnes et le panneau du canvas :
// type, entreprise liée (fiche), niveau d'exécution, co-détenteurs,
// responsable, description. Entièrement piloté par onPatch — donc les
// deux vues restent synchronisées.
function NodeEditorBlock({
  node,
  allNodes,
  entreprises,
  employes,
  onPatch
}: {
  node: OrgNode;
  allNodes: OrgNode[];
  entreprises: Array<{ id: number; name: string }>;
  employes: Employe[];
  onPatch: (id: number, patch: Partial<OrgNode>) => Promise<void>;
}) {
  const [extName, setExtName] = useState(node.assignee_external_name || "");
  useEffect(() => {
    setExtName(node.assignee_external_name || "");
  }, [node.assignee_external_name]);

  const coOwnerIds = node.co_owner_node_ids || [];
  // Détenteurs possibles : entreprises ET personnes physiques (la
  // détention n'est pas que sociétale — il y a aussi de la détention
  // personnelle).
  const companyOptions = allNodes
    .filter(
      (n) =>
        (n.kind === "company" || n.kind === "person") && n.id !== node.id
    )
    .map((n) => ({ id: n.id, label: n.label }));

  return (
    <div
      className="space-y-2 rounded border p-2 text-[11px]"
      style={{
        borderColor: "var(--qg-border-soft)",
        backgroundColor: "var(--qg-card-bg)"
      }}
    >
      <div className="grid grid-cols-2 gap-2">
        <div>
          <label className="text-[9px] uppercase text-white/40">Type</label>
          <select
            value={node.kind}
            onChange={(e) => void onPatch(node.id, { kind: e.target.value })}
            className="input mt-0.5 text-[11px]"
          >
            <option value="company">Entreprise</option>
            <option value="person">Personne</option>
            <option value="dept">Département</option>
            <option value="role">Rôle</option>
            <option value="task">Tâche</option>
            <option value="service">Service partagé</option>
          </select>
        </div>
        <div>
          <label className="text-[9px] uppercase text-white/40">
            Entreprise liée (fiche)
          </label>
          <select
            value={node.entreprise_id ? String(node.entreprise_id) : ""}
            onChange={(e) =>
              void onPatch(node.id, {
                entreprise_id: e.target.value
                  ? Number(e.target.value)
                  : null
              })
            }
            className="input mt-0.5 text-[11px]"
          >
            <option value="">Transverse (groupe)</option>
            {entreprises.map((ent) => (
              <option key={ent.id} value={String(ent.id)}>
                {ent.name}
              </option>
            ))}
          </select>
        </div>
      </div>

      {/* Niveau d'exécution — qui doit prendre ça en charge. Aide
          l'analyse : ce qui reste au dirigeant, ce qui est délégable
          à un adjoint, ce qui peut passer à l'adjoint virtuel. */}
      <div>
        <label className="text-[9px] uppercase text-white/40">
          Niveau d&apos;exécution — qui doit le faire
        </label>
        <div className="mt-0.5 flex gap-1">
          {(
            [
              ["", "Non classé"],
              ["direction", TIER_LABELS.direction.label],
              ["adjoint", TIER_LABELS.adjoint.label],
              ["adjoint_virtuel", TIER_LABELS.adjoint_virtuel.label]
            ] as const
          ).map(([val, lbl]) => {
            const active = (node.execution_tier || "") === val;
            const info = val ? TIER_LABELS[val] : null;
            return (
              <button
                key={val || "none"}
                type="button"
                onClick={() =>
                  void onPatch(node.id, { execution_tier: val || null })
                }
                className={`flex-1 rounded border px-1 py-1 text-[10px] font-semibold transition ${
                  active && info
                    ? info.cls
                    : active
                      ? "border-white/30 text-white/80"
                      : "border-transparent text-white/40 hover:text-white/70"
                }`}
                style={
                  !active
                    ? { backgroundColor: "var(--qg-bg-alt, transparent)" }
                    : undefined
                }
              >
                {lbl}
              </button>
            );
          })}
        </div>
      </div>

      {/* Co-détenteurs — une entreprise peut être détenue par
          plusieurs ; le parent dans l'arbre = détenteur principal. */}
      <div>
        <label className="text-[9px] uppercase text-white/40">
          Co-détenteurs (en plus du parent dans l&apos;arbre)
        </label>
        <div className="mt-0.5">
          <MultiSelectDropdown
            options={companyOptions}
            selectedIds={coOwnerIds}
            onChange={(ids) =>
              void onPatch(node.id, { co_owner_node_ids: ids })
            }
            placeholder="— Aucun co-détenteur —"
            emptyLabel="Aucune entreprise ni personne dans l'organigramme"
          />
        </div>
      </div>

      <div className="grid grid-cols-2 gap-2">
        <div>
          <label className="text-[9px] uppercase text-white/40">
            Employé responsable
          </label>
          <select
            value={
              node.assignee_employe_id
                ? String(node.assignee_employe_id)
                : ""
            }
            onChange={(e) =>
              void onPatch(node.id, {
                assignee_employe_id: e.target.value
                  ? Number(e.target.value)
                  : null,
                assignee_external_name: e.target.value
                  ? null
                  : node.assignee_external_name
              })
            }
            className="input mt-0.5 text-[11px]"
          >
            <option value="">— Aucun —</option>
            {employes.map((emp) => (
              <option key={emp.id} value={String(emp.id)}>
                {emp.full_name}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="text-[9px] uppercase text-white/40">
            OU externe (freelance, partenaire)
          </label>
          <input
            value={extName}
            onChange={(e) => setExtName(e.target.value)}
            onBlur={() => {
              if (extName !== (node.assignee_external_name || "")) {
                void onPatch(node.id, {
                  assignee_external_name: extName.trim() || null,
                  assignee_employe_id: extName.trim()
                    ? null
                    : node.assignee_employe_id
                });
              }
            }}
            placeholder="Ex. Freelance, sous-traitant XYZ"
            className="input mt-0.5 text-[11px]"
          />
        </div>
      </div>

      <div>
        <label className="text-[9px] uppercase text-white/40">
          Description / ce que ça fait
        </label>
        <textarea
          key={node.id}
          defaultValue={node.description || ""}
          onBlur={(e) => {
            if (e.target.value !== (node.description || "")) {
              void onPatch(node.id, {
                description: e.target.value.trim() || null
              });
            }
          }}
          rows={2}
          className="input mt-0.5 text-[11px]"
          placeholder="Notes, responsabilités, KPIs, ce que ce rôle / cette tâche accomplit..."
        />
      </div>
    </div>
  );
}

// Panneau « Générer » (IA Kratos) : suggère les rôles / départements /
// tâches manquants d'une entreprise selon son but, chacun classé par
// niveau d'exécution. Partagé entre la vue colonnes et le canvas.
function RoleSuggestionsPanel({
  node,
  onCreate
}: {
  node: OrgNode;
  onCreate: (
    parent_id: number | null,
    label: string,
    kind?: string,
    extra?: { description?: string | null; execution_tier?: string | null }
  ) => Promise<OrgNode | undefined>;
}) {
  const [suggesting, setSuggesting] = useState(false);
  const [suggestions, setSuggestions] = useState<RoleSuggestion[] | null>(
    null
  );
  const [suggestError, setSuggestError] = useState<string | null>(null);
  const [added, setAdded] = useState<Set<string>>(new Set());

  async function generate() {
    setSuggesting(true);
    setSuggestError(null);
    try {
      const r = await authedFetch(
        `/api/v1/org-nodes/${node.id}/suggest-roles`,
        { method: "POST" }
      );
      if (!r.ok) {
        const txt = await r.text();
        throw new Error(txt.slice(0, 160) || `HTTP ${r.status}`);
      }
      setSuggestions((await r.json()) as RoleSuggestion[]);
      setAdded(new Set());
    } catch (e) {
      setSuggestError((e as Error).message);
      setSuggestions([]);
    } finally {
      setSuggesting(false);
    }
  }

  async function addOne(s: RoleSuggestion) {
    setAdded((prev) => new Set(prev).add(s.label));
    await onCreate(node.id, s.label, s.kind, {
      description: s.description,
      execution_tier: s.execution_tier
    });
  }

  return (
    <div>
      <button
        type="button"
        onClick={() => void generate()}
        disabled={suggesting}
        className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-semibold text-accent-300 hover:bg-accent-500/10 disabled:opacity-50"
        title="Suggère les rôles / tâches manquants selon le but de cette entreprise"
      >
        {suggesting ? (
          <Loader2 className="h-3 w-3 animate-spin" />
        ) : (
          <Sparkles className="h-3 w-3" />
        )}
        {suggestions === null && !suggestError
          ? "Générer les rôles / tâches manquants"
          : "Régénérer"}
      </button>

      {suggestions !== null || suggestError ? (
        <div
          className="mt-1.5 rounded border p-2 text-[11px]"
          style={{
            borderColor: "var(--qg-border-soft)",
            backgroundColor: "var(--qg-card-bg)"
          }}
        >
          {suggestError ? (
            <p className="text-[10px] text-rose-300">{suggestError}</p>
          ) : null}
          {suggestions && suggestions.length === 0 && !suggestError ? (
            <p
              className="text-[10px]"
              style={{ color: "var(--qg-text-soft)" }}
            >
              Rien de neuf à suggérer — la structure semble déjà couverte.
            </p>
          ) : null}
          <div className="space-y-1">
            {(suggestions || []).map((s) => {
              const isAdded = added.has(s.label);
              const sKind = KIND_LABELS[s.kind] || KIND_LABELS.role;
              const sTier = s.execution_tier
                ? TIER_LABELS[s.execution_tier]
                : null;
              return (
                <div
                  key={s.label}
                  className="flex items-start gap-1.5 rounded px-1 py-1"
                  style={{
                    backgroundColor: "var(--qg-bg-alt, transparent)"
                  }}
                >
                  <span className="mt-0.5 flex shrink-0 flex-col gap-0.5">
                    <span
                      className={`rounded-full border px-1 py-0 text-center text-[8px] font-bold uppercase ${sKind.cls}`}
                    >
                      {sKind.label}
                    </span>
                    {sTier ? (
                      <span
                        className={`rounded-full border px-1 py-0 text-center text-[8px] font-bold ${sTier.cls}`}
                      >
                        {sTier.short}
                      </span>
                    ) : null}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span
                      className="block font-semibold"
                      style={{ color: "var(--qg-text)" }}
                    >
                      {s.label}
                    </span>
                    {s.description ? (
                      <span
                        className="block text-[10px]"
                        style={{ color: "var(--qg-text-soft)" }}
                      >
                        {s.description}
                      </span>
                    ) : null}
                  </span>
                  <button
                    type="button"
                    onClick={() => void addOne(s)}
                    disabled={isAdded}
                    className="mt-0.5 inline-flex shrink-0 items-center gap-0.5 rounded px-1 py-0.5 text-[10px] font-semibold text-accent-300 hover:bg-accent-500/10 disabled:opacity-40"
                  >
                    <Plus className="h-2.5 w-2.5" />
                    {isAdded ? "Ajouté" : "Ajouter"}
                  </button>
                </div>
              );
            })}
          </div>
        </div>
      ) : null}
    </div>
  );
}

function NodeRow({
  node,
  allNodes,
  entreprises,
  employes,
  parentEntId,
  dnd,
  onCreate,
  onPatch,
  onDelete,
  depth
}: {
  node: OrgNode;
  allNodes: OrgNode[];
  entreprises: Array<{ id: number; name: string }>;
  employes: Employe[];
  parentEntId: number | null;
  dnd: Dnd;
  onCreate: (
    parent_id: number | null,
    label: string,
    kind?: string,
    extra?: { description?: string | null; execution_tier?: string | null }
  ) => Promise<OrgNode | undefined>;
  onPatch: (id: number, patch: Partial<OrgNode>) => Promise<void>;
  onDelete: (id: number) => Promise<void>;
  depth: number;
}) {
  const [editing, setEditing] = useState(false);
  const [label, setLabel] = useState(node.label);
  // Toute la carte est saisissable pour le drag — SAUF quand on est en
  // train d'éditer le libellé (sinon on ne pourrait plus sélectionner
  // le texte du champ).
  const [labelFocused, setLabelFocused] = useState(false);

  useEffect(() => {
    setLabel(node.label);
  }, [node.label]);

  const kindInfo = KIND_LABELS[node.kind] || KIND_LABELS.role;
  const assigneeEmploye = node.assignee_employe_id
    ? employes.find((e) => e.id === node.assignee_employe_id)
    : null;
  const entreprise = node.entreprise_id
    ? entreprises.find((e) => e.id === node.entreprise_id)
    : null;

  // Entreprise mère du groupe — mise en évidence dans l'arbre.
  const isParentCompany =
    node.kind === "company" &&
    parentEntId != null &&
    node.entreprise_id === parentEntId;

  // Co-détenteurs : qui détient AUSSI ce nœud (en plus du détenteur
  // principal = parent dans l'arbre). Les entités que CE nœud
  // co-détient, elles, sont affichées comme de vraies cartes nichées
  // sous lui (cf. composant Children) — plus besoin d'un badge.
  const coOwnerIds = node.co_owner_node_ids || [];
  const coOwnerNodes = coOwnerIds
    .map((id) => allNodes.find((n) => n.id === id))
    .filter((n): n is OrgNode => Boolean(n));
  const tierInfo = node.execution_tier
    ? TIER_LABELS[node.execution_tier]
    : null;

  const isDragging = dnd.dragId === node.id;
  const isIntoTarget =
    dnd.dropTarget?.id === node.id && dnd.dropTarget.mode === "into";
  const droppable =
    dnd.dragId != null && !dnd.draggedSubtree.has(node.id);

  return (
    <div
      draggable={!labelFocused}
      onDragStart={(e) => {
        e.dataTransfer.effectAllowed = "move";
        e.dataTransfer.setData("text/plain", String(node.id));
        dnd.onDragStartNode(node.id);
      }}
      onDragEnd={() => dnd.onDragEndNode()}
      onDragOver={(e) => {
        if (!droppable) return;
        e.preventDefault();
        e.stopPropagation();
        if (!isIntoTarget) dnd.onHover({ id: node.id, mode: "into" });
      }}
      onDrop={(e) => {
        if (!droppable) return;
        e.preventDefault();
        e.stopPropagation();
        dnd.onDrop();
      }}
      className={`rounded-md border px-2 py-1.5 transition ${
        labelFocused ? "" : "cursor-grab active:cursor-grabbing"
      }`}
      style={{
        borderColor: isIntoTarget
          ? "var(--qg-accent)"
          : isParentCompany
            ? "var(--qg-accent)"
            : "var(--qg-border-soft)",
        backgroundColor: isIntoTarget
          ? "var(--qg-bg-alt)"
          : "var(--qg-bg-alt, transparent)",
        boxShadow: isIntoTarget
          ? "0 0 0 1px var(--qg-accent) inset"
          : "none",
        opacity: isDragging ? 0.4 : 1,
        fontSize: depth === 0 ? "13px" : "12px"
      }}
    >
      <div className="flex items-start gap-1.5">
        <span
          aria-hidden
          title="Glisser pour déplacer / re-parenter"
          className="mt-0.5 text-white/30"
        >
          {isParentCompany ? (
            <Star className="h-3.5 w-3.5 text-accent-400" />
          ) : (
            <GripVertical className="h-3.5 w-3.5" />
          )}
        </span>
        <span
          className={`mt-0.5 rounded-full border px-1.5 py-0 text-[9px] font-bold uppercase ${kindInfo.cls}`}
        >
          {kindInfo.label}
        </span>
        <input
          value={label}
          draggable={false}
          onFocus={() => setLabelFocused(true)}
          onChange={(e) => setLabel(e.target.value)}
          onBlur={() => {
            setLabelFocused(false);
            if (label.trim() && label !== node.label) {
              void onPatch(node.id, { label: label.trim() });
            }
          }}
          className="flex-1 bg-transparent text-sm font-semibold focus:outline-none"
          style={{ color: "var(--qg-text)" }}
        />
        <button
          type="button"
          onClick={() => setEditing((v) => !v)}
          className="rounded p-0.5 text-white/40 hover:text-accent-400"
          title="Plus d'options"
        >
          {editing ? (
            <ChevronDown className="h-3 w-3" />
          ) : (
            <ChevronRight className="h-3 w-3" />
          )}
        </button>
        <button
          type="button"
          onClick={() => void onDelete(node.id)}
          className="rounded p-0.5 text-white/40 hover:bg-rose-500/15 hover:text-rose-300"
          title="Supprimer"
        >
          <Trash2 className="h-3 w-3" />
        </button>
      </div>

      {/* Badges info compacts */}
      <div className="mt-1 flex flex-wrap items-center gap-1 text-[10px]">
        {isParentCompany ? (
          <span
            className="inline-flex items-center gap-0.5 rounded px-1 py-0 font-semibold"
            style={{
              backgroundColor: "var(--qg-accent)",
              color: "var(--qg-accent-ink, #0a0a0b)"
            }}
            title="Entreprise mère du groupe"
          >
            <Star className="h-2.5 w-2.5" />
            Entreprise mère
          </span>
        ) : null}
        {entreprise ? (
          <span
            className="inline-flex items-center gap-0.5 rounded px-1 py-0"
            style={{
              backgroundColor: "var(--qg-bg-alt)",
              color: "var(--qg-text-muted)"
            }}
            title="Entreprise liée"
          >
            <Building2 className="h-2.5 w-2.5" />
            {entreprise.name}
          </span>
        ) : null}
        {tierInfo ? (
          <span
            className={`inline-flex items-center rounded border px-1 py-0 font-semibold ${tierInfo.cls}`}
            title="Niveau d'exécution — qui doit prendre ça en charge"
          >
            {tierInfo.label}
          </span>
        ) : null}
        {assigneeEmploye ? (
          <span
            className="inline-flex items-center gap-0.5 rounded bg-accent-500/10 px-1 py-0 text-accent-300"
            title="Employé responsable"
          >
            <UserIcon className="h-2.5 w-2.5" />
            {assigneeEmploye.full_name}
          </span>
        ) : node.assignee_external_name ? (
          <span
            className="badge badge-violet"
            title="Externe (freelance / sous-traitant / partenaire)"
          >
            <Briefcase className="h-2.5 w-2.5" />
            {node.assignee_external_name}
          </span>
        ) : null}
        {coOwnerNodes.length > 0 ? (
          <span
            className="badge badge-sky"
            title="Détenu aussi par ces entités (co-détention)"
          >
            <Link2 className="h-2.5 w-2.5" />
            aussi détenu par {coOwnerNodes.map((n) => n.label).join(", ")}
          </span>
        ) : null}
      </div>

      {/* IA Kratos — suggère les rôles / tâches manquants selon le
          but de la fiche entreprise (pertinent sur un nœud entreprise). */}
      {node.kind === "company" ? (
        <div className="mt-2">
          <RoleSuggestionsPanel node={node} onCreate={onCreate} />
        </div>
      ) : null}

      {/* Bloc édition étendu — partagé avec le panneau du canvas. */}
      {editing ? (
        <div className="mt-2">
          <NodeEditorBlock
            node={node}
            allNodes={allNodes}
            entreprises={entreprises}
            employes={employes}
            onPatch={onPatch}
          />
        </div>
      ) : null}
    </div>
  );
}

// ─── Vue Canvas type Miro ────────────────────────────────────────
//
// Bulles positionnables librement (pos_x / pos_y persistés) + flèches
// de détention auto-tracées (parent_id + co_owner_node_ids), toutes
// en trait plein — un co-détenteur est un propriétaire à part
// entière —, avec ajout / suppression manuelle.
// Le canvas et la vue colonnes partagent les mêmes données : tirer
// une flèche A→B re-parente B (ou ajoute A en co-détenteur), donc la
// vue colonnes reflète immédiatement les changements.

const BUBBLE_W = 210;
const BUBBLE_H = 66;
const CANVAS_PAD = 400;
// Pas de la grille (= taille du quadrillage de fond). Les bulles
// s'aimantent dessus → lignes droites, niveaux alignés.
const GRID = 24;
const snap = (v: number) => Math.round(v / GRID) * GRID;

type XY = { x: number; y: number };

function clipToBubble(center: XY, toward: XY): XY {
  // Point sur le bord de la bulle (rectangle) en direction de `toward`.
  const dx = toward.x - center.x;
  const dy = toward.y - center.y;
  if (dx === 0 && dy === 0) return center;
  const hw = BUBBLE_W / 2;
  const hh = BUBBLE_H / 2;
  const sx = dx !== 0 ? hw / Math.abs(dx) : Infinity;
  const sy = dy !== 0 ? hh / Math.abs(dy) : Infinity;
  const s = Math.min(sx, sy);
  return { x: center.x + dx * s, y: center.y + dy * s };
}

function CanvasView({
  nodes,
  entreprises,
  employes,
  parentEntId,
  onCreate,
  onPatch,
  onMove,
  onDelete
}: {
  nodes: OrgNode[];
  entreprises: Array<{ id: number; name: string }>;
  employes: Employe[];
  parentEntId: number | null;
  onCreate: (
    parent_id: number | null,
    label: string,
    kind?: string,
    extra?: { description?: string | null; execution_tier?: string | null }
  ) => Promise<OrgNode | undefined>;
  onPatch: (id: number, patch: Partial<OrgNode>) => Promise<void>;
  onMove: (
    id: number,
    parentId: number | null,
    position: number
  ) => Promise<void>;
  onDelete: (id: number) => Promise<void>;
}) {
  const canvasRef = useRef<HTMLDivElement | null>(null);

  // Bulle sélectionnée → ouvre le panneau d'édition latéral.
  const [selectedId, setSelectedId] = useState<number | null>(null);

  // Zoom du canvas — vue plus globale au besoin. Appliqué en
  // transform:scale sur la couche de contenu ; canvasCoords divise
  // par le zoom pour garder un drag / des flèches précis. Ajustable
  // via les boutons ou Ctrl/Cmd + molette.
  const [zoom, setZoom] = useState(1);
  // Point de contenu à garder fixe sous le curseur après un zoom
  // molette (appliqué en useLayoutEffect une fois la nouvelle échelle
  // rendue).
  const zoomFocusRef = useRef<{
    contentX: number;
    contentY: number;
    vpX: number;
    vpY: number;
  } | null>(null);

  // Positions de travail : seed depuis pos_x/pos_y du serveur, sinon
  // auto-layout en arbre. Le drag les met à jour localement ; on
  // PATCH au relâchement.
  const [positions, setPositions] = useState<Map<number, XY>>(new Map());

  // Drag d'une bulle (ref : stable entre les re-renders du drag).
  const dragRef = useRef<{
    id: number;
    startX: number;
    startY: number;
    origX: number;
    origY: number;
    moved: boolean;
  } | null>(null);

  // Tracé d'une flèche en cours.
  const [connect, setConnect] = useState<{
    fromId: number;
    x: number;
    y: number;
  } | null>(null);

  const [hoverArrow, setHoverArrow] = useState<string | null>(null);

  const byId = useMemo(() => {
    const m = new Map<number, OrgNode>();
    for (const n of nodes) m.set(n.id, n);
    return m;
  }, [nodes]);

  // Auto-layout en arbre pour les nœuds sans position serveur.
  const autoLayout = useMemo(() => {
    const childrenOf = new Map<number | null, OrgNode[]>();
    for (const n of nodes) {
      const arr = childrenOf.get(n.parent_id) || [];
      arr.push(n);
      childrenOf.set(n.parent_id, arr);
    }
    for (const arr of childrenOf.values())
      arr.sort((a, b) => a.position - b.position);
    const out = new Map<number, XY>();
    let row = 0;
    const place = (n: OrgNode, depth: number) => {
      out.set(n.id, {
        x: snap(48 + depth * (BUBBLE_W + 96)),
        y: snap(48 + row * (BUBBLE_H + 42))
      });
      row += 1;
      for (const c of childrenOf.get(n.id) || []) place(c, depth + 1);
    };
    for (const r of childrenOf.get(null) || []) place(r, 0);
    return out;
  }, [nodes]);

  // (Re)seed : ajoute les nouveaux nœuds, retire les supprimés,
  // conserve les positions déjà connues (drag local).
  useEffect(() => {
    setPositions((prev) => {
      const next = new Map<number, XY>();
      for (const n of nodes) {
        const existing = prev.get(n.id);
        if (existing) next.set(n.id, existing);
        else if (n.pos_x != null && n.pos_y != null)
          next.set(n.id, { x: n.pos_x, y: n.pos_y });
        else next.set(n.id, autoLayout.get(n.id) || { x: 60, y: 60 });
      }
      return next;
    });
  }, [nodes, autoLayout]);

  // Ctrl/Cmd + molette → zoom du canvas centré sur le curseur
  // (molette simple = défilement normal). Listener non-passif posé à
  // la main car React attache `onWheel` en passif.
  useEffect(() => {
    const el = canvasRef.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      if (!e.ctrlKey && !e.metaKey) return;
      e.preventDefault();
      const r = el.getBoundingClientRect();
      const vpX = e.clientX - r.left;
      const vpY = e.clientY - r.top;
      setZoom((z) => {
        const next = Math.min(
          2,
          Math.max(0.4, Math.round((z - e.deltaY * 0.0015) * 100) / 100)
        );
        if (next !== z) {
          zoomFocusRef.current = {
            contentX: (vpX + el.scrollLeft) / z,
            contentY: (vpY + el.scrollTop) / z,
            vpX,
            vpY
          };
        }
        return next;
      });
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, []);

  // Après un zoom molette : repositionne le scroll pour garder le
  // point de contenu sous le curseur immobile.
  useLayoutEffect(() => {
    const el = canvasRef.current;
    const f = zoomFocusRef.current;
    if (!el || !f) return;
    el.scrollLeft = f.contentX * zoom - f.vpX;
    el.scrollTop = f.contentY * zoom - f.vpY;
    zoomFocusRef.current = null;
  }, [zoom]);

  function canvasCoords(e: { clientX: number; clientY: number }): XY {
    const el = canvasRef.current;
    if (!el) return { x: 0, y: 0 };
    const r = el.getBoundingClientRect();
    // (clientX - left + scroll) donne la position dans l'espace
    // ZOOMÉ ; on divise par le zoom pour revenir aux coordonnées de
    // contenu (celles stockées dans positions / pos_x).
    return {
      x: (e.clientX - r.left + el.scrollLeft) / zoom,
      y: (e.clientY - r.top + el.scrollTop) / zoom
    };
  }

  const { canvasW, canvasH } = useMemo(() => {
    let mx = 800;
    let my = 500;
    for (const p of positions.values()) {
      mx = Math.max(mx, p.x + BUBBLE_W);
      my = Math.max(my, p.y + BUBBLE_H);
    }
    return { canvasW: mx + CANVAS_PAD, canvasH: my + CANVAS_PAD };
  }, [positions]);

  // Flèches de détention : parent_id + co_owner_node_ids, toutes en
  // trait plein (la détention compte autant pour tous les détenteurs).
  const arrows = useMemo(() => {
    const out: Array<{
      key: string;
      fromId: number;
      toId: number;
      kind: "parent" | "coowner";
    }> = [];
    for (const n of nodes) {
      if (n.parent_id != null && byId.has(n.parent_id))
        out.push({
          key: `p-${n.parent_id}-${n.id}`,
          fromId: n.parent_id,
          toId: n.id,
          kind: "parent"
        });
      for (const co of n.co_owner_node_ids || [])
        if (byId.has(co))
          out.push({
            key: `c-${co}-${n.id}`,
            fromId: co,
            toId: n.id,
            kind: "coowner"
          });
    }
    return out;
  }, [nodes, byId]);

  // Descendants d'un nœud — pour empêcher les boucles au branchement.
  function subtreeOf(rootId: number): Set<number> {
    const childrenOf = new Map<number | null, number[]>();
    for (const n of nodes) {
      const a = childrenOf.get(n.parent_id) || [];
      a.push(n.id);
      childrenOf.set(n.parent_id, a);
    }
    const s = new Set<number>();
    const stack = [rootId];
    while (stack.length) {
      const cur = stack.pop() as number;
      if (s.has(cur)) continue;
      s.add(cur);
      for (const c of childrenOf.get(cur) || []) stack.push(c);
    }
    return s;
  }

  function onBubbleMouseDown(e: React.MouseEvent, id: number) {
    if (e.button !== 0) return;
    const pos = positions.get(id);
    if (!pos) return;
    const m = canvasCoords(e);
    dragRef.current = {
      id,
      startX: m.x,
      startY: m.y,
      origX: pos.x,
      origY: pos.y,
      moved: false
    };
  }

  function onHandleMouseDown(e: React.MouseEvent, id: number) {
    if (e.button !== 0) return;
    e.stopPropagation();
    const m = canvasCoords(e);
    setConnect({ fromId: id, x: m.x, y: m.y });
  }

  function onCanvasMouseMove(e: React.MouseEvent) {
    if (!dragRef.current && !connect) return;
    const m = canvasCoords(e);
    if (dragRef.current) {
      const d = dragRef.current;
      const nx = Math.max(0, snap(d.origX + (m.x - d.startX)));
      const ny = Math.max(0, snap(d.origY + (m.y - d.startY)));
      // « moved » seulement si la position change vraiment (au pas de
      // grille) — un micro-tremblement laisse le clic = sélection.
      if (nx !== d.origX || ny !== d.origY) d.moved = true;
      setPositions((prev) => {
        const next = new Map(prev);
        next.set(d.id, { x: nx, y: ny });
        return next;
      });
    } else if (connect) {
      setConnect((c) => (c ? { ...c, x: m.x, y: m.y } : c));
    }
  }

  function onCanvasMouseUp() {
    if (dragRef.current) {
      const d = dragRef.current;
      dragRef.current = null;
      if (d.moved) {
        const p = positions.get(d.id);
        if (p) void onPatch(d.id, { pos_x: p.x, pos_y: p.y });
      } else {
        // Clic sans déplacement → sélectionne la bulle (ouvre l'éditeur).
        setSelectedId(d.id);
      }
    }
    if (connect) setConnect(null);
  }

  // Finalise une flèche fromId → toId (= « fromId détient toId »).
  function finishConnect(toId: number) {
    if (!connect) return;
    const fromId = connect.fromId;
    setConnect(null);
    if (fromId === toId) return;
    // Anti-boucle : la cible ne peut pas être un ancêtre de la source.
    if (subtreeOf(toId).has(fromId)) return;
    const target = byId.get(toId);
    if (!target) return;
    if (target.parent_id == null) {
      // Pas de détenteur principal → re-parente (devient le parent).
      const siblings = nodes.filter(
        (n) => n.parent_id === fromId && n.id !== toId
      );
      void onMove(toId, fromId, siblings.length);
    } else if (
      target.parent_id !== fromId &&
      !(target.co_owner_node_ids || []).includes(fromId)
    ) {
      // Détenteur principal déjà défini → co-détention.
      void onPatch(toId, {
        co_owner_node_ids: [...(target.co_owner_node_ids || []), fromId]
      });
    }
  }

  function deleteArrow(a: {
    fromId: number;
    toId: number;
    kind: "parent" | "coowner";
  }) {
    if (a.kind === "parent") {
      const roots = nodes.filter(
        (n) => n.parent_id == null && n.id !== a.toId
      );
      void onMove(a.toId, null, roots.length);
    } else {
      const target = byId.get(a.toId);
      if (!target) return;
      void onPatch(a.toId, {
        co_owner_node_ids: (target.co_owner_node_ids || []).filter(
          (x) => x !== a.fromId
        )
      });
    }
  }

  const selectedNode =
    selectedId != null
      ? nodes.find((n) => n.id === selectedId) || null
      : null;

  return (
    <div className="relative">
      <div
        ref={canvasRef}
        onMouseMove={onCanvasMouseMove}
        onMouseUp={onCanvasMouseUp}
        onMouseLeave={onCanvasMouseUp}
        className="relative overflow-auto rounded-xl border"
        style={{
          height: "calc(100vh - 250px)",
          minHeight: 420,
          borderColor: "var(--qg-border)",
          backgroundColor: "var(--qg-bg-alt, transparent)",
          cursor: connect ? "crosshair" : "default"
        }}
      >
        {/* Sizer : réserve la zone scrollable à la taille ZOOMÉE.
            La couche de contenu en dessous est mise à l'échelle via
            transform:scale — le scroll reste donc cohérent. */}
        <div
          style={{ width: canvasW * zoom, height: canvasH * zoom }}
        >
        <div
          onMouseDown={(e) => {
            // Clic sur le fond quadrillé (hors bulle) → désélectionne.
            if (e.target === e.currentTarget) setSelectedId(null);
          }}
          style={{
            position: "relative",
            width: canvasW,
            height: canvasH,
            transform: `scale(${zoom})`,
            transformOrigin: "0 0",
            // Quadrillage en coordonnées contenu (s'aligne au snap).
            backgroundImage:
              "radial-gradient(var(--qg-border-soft) 1px, transparent 1px)",
            backgroundSize: `${GRID}px ${GRID}px`
          }}
        >
        {/* Couche SVG : flèches */}
        <svg
          width={canvasW}
          height={canvasH}
          className="absolute inset-0"
          style={{ pointerEvents: "none" }}
        >
          <defs>
            <marker
              id="org-arrow"
              viewBox="0 0 10 10"
              refX="9"
              refY="5"
              markerWidth="7"
              markerHeight="7"
              orient="auto-start-reverse"
            >
              <path d="M0,0 L10,5 L0,10 z" fill="var(--qg-text-muted)" />
            </marker>
            <marker
              id="org-arrow-accent"
              viewBox="0 0 10 10"
              refX="9"
              refY="5"
              markerWidth="7"
              markerHeight="7"
              orient="auto-start-reverse"
            >
              <path d="M0,0 L10,5 L0,10 z" fill="var(--qg-accent)" />
            </marker>
          </defs>
          {arrows.map((a) => {
            const pf = positions.get(a.fromId);
            const pt = positions.get(a.toId);
            if (!pf || !pt) return null;
            const fc = { x: pf.x + BUBBLE_W / 2, y: pf.y + BUBBLE_H / 2 };
            const tc = { x: pt.x + BUBBLE_W / 2, y: pt.y + BUBBLE_H / 2 };
            const start = clipToBubble(fc, tc);
            const end = clipToBubble(tc, fc);
            const mid = {
              x: (start.x + end.x) / 2,
              y: (start.y + end.y) / 2
            };
            const hovered = hoverArrow === a.key;
            return (
              <g key={a.key}>
                <line
                  x1={start.x}
                  y1={start.y}
                  x2={end.x}
                  y2={end.y}
                  stroke="transparent"
                  strokeWidth={16}
                  style={{ pointerEvents: "stroke", cursor: "pointer" }}
                  onMouseEnter={() => setHoverArrow(a.key)}
                  onMouseLeave={() =>
                    setHoverArrow((h) => (h === a.key ? null : h))
                  }
                />
                <line
                  x1={start.x}
                  y1={start.y}
                  x2={end.x}
                  y2={end.y}
                  stroke={
                    hovered
                      ? "var(--qg-accent)"
                      : "var(--qg-text-muted)"
                  }
                  strokeWidth={hovered ? 2.5 : 1.75}
                  markerEnd={`url(#org-arrow${hovered ? "-accent" : ""})`}
                  style={{ pointerEvents: "none" }}
                />
                {hovered ? (
                  <g
                    style={{ pointerEvents: "all", cursor: "pointer" }}
                    onMouseEnter={() => setHoverArrow(a.key)}
                    onClick={() => deleteArrow(a)}
                  >
                    <circle
                      cx={mid.x}
                      cy={mid.y}
                      r={9}
                      fill="var(--qg-card-bg)"
                      stroke="var(--qg-accent)"
                    />
                    <path
                      d={`M${mid.x - 3},${mid.y - 3} L${mid.x + 3},${mid.y + 3} M${mid.x + 3},${mid.y - 3} L${mid.x - 3},${mid.y + 3}`}
                      stroke="var(--qg-accent)"
                      strokeWidth={1.6}
                    />
                  </g>
                ) : null}
              </g>
            );
          })}
          {connect
            ? (() => {
                const pf = positions.get(connect.fromId);
                if (!pf) return null;
                return (
                  <line
                    x1={pf.x + BUBBLE_W / 2}
                    y1={pf.y + BUBBLE_H / 2}
                    x2={connect.x}
                    y2={connect.y}
                    stroke="var(--qg-accent)"
                    strokeWidth={2}
                    strokeDasharray="4 3"
                    markerEnd="url(#org-arrow-accent)"
                  />
                );
              })()
            : null}
        </svg>

        {/* Bulles */}
        {nodes.map((n) => {
          const p = positions.get(n.id);
          if (!p) return null;
          return (
            <CanvasBubble
              key={n.id}
              node={n}
              x={p.x}
              y={p.y}
              entreprises={entreprises}
              employes={employes}
              isParentCompany={
                n.kind === "company" &&
                parentEntId != null &&
                n.entreprise_id === parentEntId
              }
              selected={selectedId === n.id}
              connecting={connect != null}
              onMouseDown={(e) => onBubbleMouseDown(e, n.id)}
              onHandleMouseDown={(e) => onHandleMouseDown(e, n.id)}
              onMouseUp={() => finishConnect(n.id)}
              onDelete={() => void onDelete(n.id)}
            />
          );
        })}
        </div>
        </div>
      </div>
      {/* Contrôle de zoom — flottant, fixe (hors zone scrollable). */}
      <div className="absolute bottom-3 left-3 z-10">
        <ZoomControl zoom={zoom} setZoom={setZoom} />
      </div>
      {selectedNode ? (
        <CanvasNodeEditor
          node={selectedNode}
          allNodes={nodes}
          entreprises={entreprises}
          employes={employes}
          onCreate={onCreate}
          onPatch={onPatch}
          onDelete={onDelete}
          onClose={() => setSelectedId(null)}
        />
      ) : null}
    </div>
  );
}

function CanvasBubble({
  node,
  x,
  y,
  entreprises,
  employes,
  isParentCompany,
  selected,
  connecting,
  onMouseDown,
  onHandleMouseDown,
  onMouseUp,
  onDelete
}: {
  node: OrgNode;
  x: number;
  y: number;
  entreprises: Array<{ id: number; name: string }>;
  employes: Employe[];
  isParentCompany: boolean;
  selected: boolean;
  connecting: boolean;
  onMouseDown: (e: React.MouseEvent) => void;
  onHandleMouseDown: (e: React.MouseEvent) => void;
  onMouseUp: () => void;
  onDelete: () => void;
}) {
  const [hover, setHover] = useState(false);
  const kindInfo = KIND_LABELS[node.kind] || KIND_LABELS.role;
  const tierInfo = node.execution_tier
    ? TIER_LABELS[node.execution_tier]
    : null;
  const entreprise = node.entreprise_id
    ? entreprises.find((e) => e.id === node.entreprise_id)
    : null;
  const assigneeEmploye = node.assignee_employe_id
    ? employes.find((e) => e.id === node.assignee_employe_id)
    : null;
  const assignee =
    assigneeEmploye?.full_name || node.assignee_external_name || null;

  return (
    <div
      onMouseDown={onMouseDown}
      onMouseUp={onMouseUp}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      className="absolute select-none rounded-xl border"
      style={{
        left: x,
        top: y,
        width: BUBBLE_W,
        minHeight: BUBBLE_H,
        borderColor:
          selected || isParentCompany
            ? "var(--qg-accent)"
            : "var(--qg-border)",
        backgroundColor: "var(--qg-card-bg)",
        boxShadow: selected
          ? "0 0 0 2px var(--qg-accent), 0 6px 18px -4px rgba(0,0,0,0.4)"
          : hover
            ? "0 4px 14px -4px rgba(0,0,0,0.35)"
            : "0 1px 3px rgba(0,0,0,0.18)",
        cursor: connecting ? "crosshair" : "grab",
        padding: "8px 10px"
      }}
    >
      <div className="flex items-center gap-1.5">
        {isParentCompany ? (
          <Star className="h-3 w-3 shrink-0 text-accent-400" />
        ) : null}
        <span
          className={`shrink-0 rounded-full border px-1.5 py-0 text-[8px] font-bold uppercase ${kindInfo.cls}`}
        >
          {kindInfo.label}
        </span>
        {tierInfo ? (
          <span
            className={`shrink-0 rounded-full border px-1.5 py-0 text-[8px] font-bold ${tierInfo.cls}`}
            title="Niveau d'exécution — qui doit prendre ça en charge"
          >
            {tierInfo.short}
          </span>
        ) : null}
        {hover ? (
          <button
            type="button"
            onMouseDown={(e) => e.stopPropagation()}
            onClick={onDelete}
            className="ml-auto rounded p-0.5 text-white/40 hover:bg-rose-500/15 hover:text-rose-300"
            title="Supprimer le nœud"
          >
            <Trash2 className="h-3 w-3" />
          </button>
        ) : null}
      </div>
      <p
        className="mt-1 text-[13px] font-semibold leading-tight"
        style={{ color: "var(--qg-text)" }}
      >
        {node.label}
      </p>
      {entreprise || assignee ? (
        <p
          className="mt-0.5 truncate text-[10px]"
          style={{ color: "var(--qg-text-soft)" }}
        >
          {entreprise ? entreprise.name : null}
          {entreprise && assignee ? " · " : null}
          {assignee}
        </p>
      ) : null}

      {/* Poignée de connexion — tirer vers une autre bulle */}
      <span
        role="button"
        aria-label="Créer une flèche vers une autre bulle"
        onMouseDown={onHandleMouseDown}
        title="Tirer vers une autre bulle pour créer une flèche de détention"
        className="absolute h-4 w-4 rounded-full border-2"
        style={{
          right: -9,
          top: "50%",
          transform: "translateY(-50%)",
          borderColor: "var(--qg-card-bg)",
          backgroundColor: "var(--qg-accent)",
          cursor: "crosshair"
        }}
      />
    </div>
  );
}

// Panneau d'édition latéral du canvas — s'ouvre au clic sur une bulle.
// Réutilise le bloc d'édition partagé (type, fiche entreprise, niveau
// d'exécution, responsable, description) + l'IA Kratos pour les nœuds
// entreprise. Tout passe par onPatch / onMove → la vue colonnes reste
// synchronisée.
function CanvasNodeEditor({
  node,
  allNodes,
  entreprises,
  employes,
  onCreate,
  onPatch,
  onDelete,
  onClose
}: {
  node: OrgNode;
  allNodes: OrgNode[];
  entreprises: Array<{ id: number; name: string }>;
  employes: Employe[];
  onCreate: (
    parent_id: number | null,
    label: string,
    kind?: string,
    extra?: { description?: string | null; execution_tier?: string | null }
  ) => Promise<OrgNode | undefined>;
  onPatch: (id: number, patch: Partial<OrgNode>) => Promise<void>;
  onDelete: (id: number) => Promise<void>;
  onClose: () => void;
}) {
  const [label, setLabel] = useState(node.label);
  useEffect(() => {
    setLabel(node.label);
  }, [node.id, node.label]);

  const kindInfo = KIND_LABELS[node.kind] || KIND_LABELS.role;

  return (
    <div
      className="absolute bottom-0 right-0 top-0 z-10 flex w-80 flex-col gap-2 overflow-y-auto border-l p-3"
      style={{
        borderColor: "var(--qg-border)",
        backgroundColor: "var(--qg-card-bg)",
        boxShadow: "-10px 0 28px -14px rgba(0,0,0,0.55)"
      }}
    >
      <div className="flex items-center gap-1.5">
        <span
          className={`rounded-full border px-1.5 py-0 text-[9px] font-bold uppercase ${kindInfo.cls}`}
        >
          {kindInfo.label}
        </span>
        <span
          className="text-[10px]"
          style={{ color: "var(--qg-text-soft)" }}
        >
          Édition de la bulle
        </span>
        <span className="ml-auto flex items-center gap-0.5">
          <button
            type="button"
            onClick={() => void onDelete(node.id)}
            className="rounded p-1 text-white/40 hover:bg-rose-500/15 hover:text-rose-300"
            title="Supprimer le nœud"
          >
            <Trash2 className="h-3.5 w-3.5" />
          </button>
          <button
            type="button"
            onClick={onClose}
            className="rounded p-1 text-white/40 hover:text-accent-400"
            title="Fermer le panneau"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        </span>
      </div>

      <input
        value={label}
        onChange={(e) => setLabel(e.target.value)}
        onBlur={() => {
          if (label.trim() && label !== node.label)
            void onPatch(node.id, { label: label.trim() });
        }}
        className="input text-sm font-semibold"
        placeholder="Nom du nœud"
      />

      <NodeEditorBlock
        key={node.id}
        node={node}
        allNodes={allNodes}
        entreprises={entreprises}
        employes={employes}
        onPatch={onPatch}
      />

      {node.kind === "company" ? (
        <RoleSuggestionsPanel key={`sug-${node.id}`} node={node} onCreate={onCreate} />
      ) : null}
    </div>
  );
}
