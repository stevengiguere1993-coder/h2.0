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
  Building2,
  ExternalLink,
  LayoutGrid,
  Link2,
  Loader2,
  Plus,
  Star,
  Trash2,
  User as UserIcon,
  Users,
  X
} from "lucide-react";

import { authedFetch } from "@/lib/auth";
import { Link } from "@/i18n/navigation";
import { PageDriveSection } from "@/components/drive/PageDriveSection";
import { QGTopbar, useEntreprisesLayout } from "../layout";

/**
 * Page Organigramme — canvas libre type Miro, seule vue de la page.
 *
 * Bulles déplaçables (INCs Kratos, compagnies externes, personnes)
 * reliées par des flèches de détention (détenteur → détenu), avec la
 * quote-part en % affichée sur chaque flèche quand elle est connue
 * (`ownership_json` du nœud détenu, clé = id du détenteur).
 *
 * « Synchroniser avec les fiches » crée les nœuds manquants (nos INCs
 * et leurs actionnaires) et reconstruit la détention depuis les
 * « Partenaires & parts » des fiches d'entreprises. Des VERSIONS de
 * travail (copies indépendantes des nœuds) se créent depuis le topbar
 * pour tester des scénarios de restructuration sans toucher au
 * « Principal » (version_id null).
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
  // Version de l'organigramme à laquelle le nœud appartient
  // (null = version « Principal »).
  version_id: number | null;
  // Quotes-parts de détention de CE nœud : JSON objet
  // { "<node_id du détenteur>": pourcentage } — affiché sur les flèches.
  ownership_json: string | null;
  created_at: string;
  updated_at: string;
};

type OrgVersion = {
  id: number;
  name: string;
  created_at: string;
};

type Employe = {
  id: number;
  full_name: string;
  email?: string | null;
  role?: string | null;
  active?: boolean;
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

// ─── Nature des bulles (couleurs du canvas + légende) ────────────
//
// La couleur d'une bulle reflète sa NATURE, pas seulement son kind :
//  • INC Kratos        : company reliée à une fiche entreprise → ambre
//  • Compagnie externe : company manuelle, sans fiche → sky
//  • Personne          : kind person → violet
//  • autre             : service partagé, etc. → neutre
//
// Couleurs volontairement FRANCHES (bordure /70, fond /15) : d'un
// coup d'œil on distingue nos INCs, les compagnies externes et les
// personnes. Le badge au-dessus du nom reprend la même nature.

type BubbleNature = "inc" | "externe" | "person" | "autre";

function nodeNature(n: OrgNode): BubbleNature {
  if (n.kind === "person") return "person";
  if (n.kind === "company")
    return n.entreprise_id != null ? "inc" : "externe";
  return "autre";
}

const NATURE_STYLES: Record<
  BubbleNature,
  {
    label: string;
    badge: string;
    bubbleCls: string;
    dotCls: string;
    badgeCls: string;
  }
> = {
  inc: {
    label: "INC Kratos",
    badge: "INC Kratos",
    bubbleCls: "border-amber-500/70 bg-amber-500/15",
    dotCls: "bg-amber-500",
    badgeCls: "bg-amber-500/20 text-amber-500 border-amber-500/40"
  },
  externe: {
    label: "Compagnie externe",
    badge: "Compagnie",
    bubbleCls: "border-sky-500/70 bg-sky-500/15",
    dotCls: "bg-sky-500",
    badgeCls: "bg-sky-500/20 text-sky-500 border-sky-500/40"
  },
  person: {
    label: "Personne",
    badge: "Personne",
    bubbleCls: "border-violet-500/70 bg-violet-500/15",
    dotCls: "bg-violet-500",
    badgeCls: "bg-violet-500/20 text-violet-500 border-violet-500/40"
  },
  autre: {
    label: "Autre",
    badge: "Service",
    bubbleCls: "",
    dotCls: "bg-emerald-400",
    badgeCls: "bg-emerald-500/15 text-emerald-300 border-emerald-500/30"
  }
};

// Quotes-parts du nœud DÉTENU : { "<node_id du détenteur>": pct }.
// Tolérant : JSON invalide ou non-objet → aucune quote-part.
function parseOwnership(
  n: OrgNode | null | undefined
): Record<string, number> {
  if (!n || !n.ownership_json) return {};
  try {
    const o = JSON.parse(n.ownership_json) as unknown;
    if (o && typeof o === "object" && !Array.isArray(o)) {
      const out: Record<string, number> = {};
      for (const [k, v] of Object.entries(o as Record<string, unknown>)) {
        const num = typeof v === "number" ? v : Number(v);
        if (!Number.isNaN(num)) out[k] = num;
      }
      return out;
    }
  } catch {
    /* silencieux */
  }
  return {};
}

// « 33,33 % » — format québécois, sans zéros traînants.
function formatPct(p: number): string {
  const r = Math.round(p * 100) / 100;
  return `${String(r).replace(".", ",")} %`;
}

// La sync écrit une ligne « Détention : … » en tête de description.
// Le panneau la montre à part (lecture seule) et n'édite que les
// notes libres — la ligne est recomposée telle quelle au PATCH.
function splitDescription(desc: string | null): {
  detention: string | null;
  notes: string;
} {
  const lines = (desc || "").split("\n");
  const detention =
    lines.find((l) => l.startsWith("Détention : ")) || null;
  const notes = lines
    .filter((l) => !l.startsWith("Détention : "))
    .join("\n")
    .trim();
  return { detention, notes };
}

function composeDescription(
  detention: string | null,
  notes: string
): string | null {
  const parts = [
    ...(detention ? [detention] : []),
    ...(notes.trim() ? [notes.trim()] : [])
  ];
  return parts.length > 0 ? parts.join("\n") : null;
}

// ─── Géométrie du canvas (bulles + grille) ───────────────────────
// Partagée entre la vue canvas et le rangement automatique
// (« Réorganiser ») du composant page.
const BUBBLE_W = 210;
const BUBBLE_H = 66;
const CANVAS_PAD = 400;
// Pas de la grille (= taille du quadrillage de fond). Les bulles
// s'aimantent dessus → lignes droites, niveaux alignés.
const GRID = 24;
const snap = (v: number) => Math.round(v / GRID) * GRID;

export default function OrganigrammePage() {
  const { entreprises } = useEntreprisesLayout();
  const [nodes, setNodes] = useState<OrgNode[]>([]);
  const [employes, setEmployes] = useState<Employe[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [syncing, setSyncing] = useState(false);
  const [layouting, setLayouting] = useState(false);
  // Ajout manuel rapide (bandeau) : un seul champ nom, partagé par
  // les boutons « + Compagnie » et « + Personne ».
  const [quickLabel, setQuickLabel] = useState("");
  const [creatingKind, setCreatingKind] = useState<
    "company" | "person" | null
  >(null);
  //: Périmètre affiché : « complet » (INCs + investisseurs externes)
  //: ou « internes » (seulement nos compagnies) — retour Phil 2026-08-10.
  const [scope, setScope] = useState<"complet" | "internes">("complet");

  // Versions de l'organigramme : null = « Principal » (les nœuds sans
  // version_id). Chaque version est une copie indépendante des nœuds —
  // on y teste une restructuration sans toucher au Principal.
  const [versionId, setVersionId] = useState<number | null>(null);
  const [versions, setVersions] = useState<OrgVersion[]>([]);

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
        authedFetch(
          `/api/v1/org-nodes${
            versionId != null ? `?version_id=${versionId}` : ""
          }`
        ),
        authedFetch("/api/v1/employes?limit=500")
      ]);
      if (n.ok) setNodes((await n.json()) as OrgNode[]);
      if (e.ok) setEmployes((await e.json()) as Employe[]);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }, [versionId]);

  useEffect(() => {
    void load();
  }, [load]);

  const loadVersions = useCallback(async () => {
    try {
      const r = await authedFetch("/api/v1/org-nodes/versions");
      if (r.ok) setVersions((await r.json()) as OrgVersion[]);
    } catch {
      /* silencieux — le sélecteur restera sur Principal */
    }
  }, []);

  useEffect(() => {
    void loadVersions();
  }, [loadVersions]);

  // Nouvelle version = copie des nœuds de la version affichée (le
  // Principal si aucune n'est sélectionnée), puis bascule dessus.
  async function createVersion() {
    const name = window.prompt(
      "Nom de la nouvelle version (ex. Scénario restructuration 2027)…"
    );
    if (!name || !name.trim()) return;
    setError(null);
    try {
      const r = await authedFetch("/api/v1/org-nodes/versions", {
        method: "POST",
        body: JSON.stringify({
          name: name.trim(),
          copy_nodes: true,
          copy_from_version_id: versionId
        })
      });
      if (!r.ok) {
        const txt = await r.text();
        throw new Error(txt.slice(0, 200) || `HTTP ${r.status}`);
      }
      const created = (await r.json()) as OrgVersion;
      await loadVersions();
      setVersionId(created.id);
    } catch (e) {
      setError(`Création de la version échouée : ${(e as Error).message}`);
    }
  }

  async function deleteVersion() {
    if (versionId == null) return;
    const v = versions.find((x) => x.id === versionId);
    if (
      !window.confirm(
        `Supprimer la version « ${v ? v.name : versionId} » et tous ses nœuds ? Le Principal n'est pas touché.`
      )
    )
      return;
    setError(null);
    try {
      const r = await authedFetch(
        `/api/v1/org-nodes/versions/${versionId}`,
        { method: "DELETE" }
      );
      if (!r.ok && r.status !== 204) {
        const txt = await r.text();
        throw new Error(txt.slice(0, 200) || `HTTP ${r.status}`);
      }
      // Retour au Principal — load() suit via la dépendance versionId.
      setVersionId(null);
      await loadVersions();
    } catch (e) {
      setError(
        `Suppression de la version échouée : ${(e as Error).message}`
      );
    }
  }

  async function syncDetention() {
    setSyncing(true);
    setError(null);
    try {
      // La sync s'applique à la version affichée (Principal si aucune).
      const r = await authedFetch(
        `/api/v1/org-nodes/sync-detention${
          versionId != null ? `?version_id=${versionId}` : ""
        }`,
        { method: "POST" }
      );
      if (!r.ok) {
        const txt = await r.text();
        throw new Error(txt.slice(0, 200) || `HTTP ${r.status}`);
      }
      setNodes((await r.json()) as OrgNode[]);
    } catch (e) {
      setError(`Sync de la détention échoué : ${(e as Error).message}`);
    } finally {
      setSyncing(false);
    }
  }

  // Sous-ensemble « structurel » affiché au canvas : entreprises,
  // personnes et nœuds libres. On exclut les départements, rôles et
  // tâches (héritage des anciennes vues) — l'organigramme montre la
  // détention, pas les fonctions.
  const structuralNodes = useMemo(
    () =>
      nodes.filter(
        (n) =>
          n.kind !== "dept" &&
          n.kind !== "role" &&
          n.kind !== "task" &&
          // Vue « Nos INCs » : on cache les personnes physiques et
          // investisseurs externes — il ne reste que la détention
          // inter-compagnies (les flèches vers les nœuds cachés sont
          // sautées par la couche SVG).
          (scope === "complet" || n.kind !== "person")
      ),
    [nodes, scope]
  );

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

  async function createNode(
    parent_id: number | null,
    label: string,
    kind = "company"
  ) {
    if (!label.trim()) return;
    try {
      const r = await authedFetch("/api/v1/org-nodes", {
        method: "POST",
        body: JSON.stringify({
          parent_id,
          label: label.trim(),
          kind,
          // Chaque création atterrit dans la version affichée
          // (null = Principal).
          version_id: versionId
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

  // Ajout manuel rapide : compagnie manuelle/externe (company SANS
  // entreprise_id) ou personne physique — à la racine du canvas.
  async function quickCreate(kind: "company" | "person") {
    if (!quickLabel.trim() || creatingKind != null) return;
    setCreatingKind(kind);
    try {
      const created = await createNode(null, quickLabel, kind);
      if (created) setQuickLabel("");
    } finally {
      setCreatingKind(null);
    }
  }

  // Rangement automatique (« Réorganiser ») : bulles disposées par
  // COUCHES de détention — niveau 0 = les détenteurs ultimes (aucun
  // parent ni co-détenteur), puis chaque nœud une rangée sous son
  // détenteur le plus profond. Les flèches pointent ainsi toutes vers
  // le bas, sans croisements inutiles.
  async function autoLayout() {
    if (layouting) return;
    if (
      !window.confirm(
        "Réorganiser toutes les bulles ? Les positions actuelles seront remplacées."
      )
    )
      return;
    setLayouting(true);
    setError(null);
    try {
      const list = structuralNodes;
      const ids = new Set(list.map((n) => n.id));
      // Détenteurs de chaque nœud : parent + co-détenteurs présents
      // au canvas (les nœuds hors périmètre sont ignorés).
      const holdersOf = new Map<number, number[]>();
      for (const n of list) {
        const hs: number[] = [];
        if (n.parent_id != null && ids.has(n.parent_id))
          hs.push(n.parent_id);
        for (const co of n.co_owner_node_ids || [])
          if (ids.has(co) && !hs.includes(co)) hs.push(co);
        holdersOf.set(n.id, hs);
      }
      // Niveaux par propagation : niveau 0 = sans détenteur, sinon
      // 1 + max(niveau des détenteurs). Le garde-fou (50 passes)
      // borne les cycles de détention croisée.
      const level = new Map<number, number>();
      for (const n of list) level.set(n.id, 0);
      let changed = true;
      let guard = 0;
      while (changed && guard < 50) {
        changed = false;
        guard += 1;
        for (const n of list) {
          const hs = holdersOf.get(n.id) || [];
          if (hs.length === 0) continue;
          const want =
            1 + Math.max(...hs.map((h) => level.get(h) || 0));
          if (want !== level.get(n.id)) {
            level.set(n.id, want);
            changed = true;
          }
        }
      }
      // Rangées : tri alphabétique dans chaque niveau, puis grille.
      const byLevel = new Map<number, OrgNode[]>();
      for (const n of list) {
        const lv = level.get(n.id) || 0;
        const arr = byLevel.get(lv) || [];
        arr.push(n);
        byLevel.set(lv, arr);
      }
      for (const [lv, arr] of byLevel) {
        arr.sort((a, b) => a.label.localeCompare(b.label, "fr"));
        for (let i = 0; i < arr.length; i += 1) {
          const x = snap(i * (BUBBLE_W + GRID * 2) + GRID);
          const y = snap(lv * (BUBBLE_H + GRID * 3) + GRID);
          // PATCH séquentiels — même mécanique de sauvegarde que le
          // drag d'une bulle.
          await patchNode(arr[i].id, { pos_x: x, pos_y: y });
        }
      }
      // Recharge : le canvas se re-seed depuis les positions serveur.
      await load();
    } finally {
      setLayouting(false);
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
        subtitle="Structure de détention du groupe — compagnies, personnes et quotes-parts, avec versions de travail"
        rightSlot={
          <div className="flex items-center gap-2">
            {/* Sélecteur de version — « Principal » = version officielle,
                les autres sont des scénarios de travail indépendants. */}
            <select
              value={versionId != null ? String(versionId) : ""}
              onChange={(e) =>
                setVersionId(e.target.value ? Number(e.target.value) : null)
              }
              className="input"
              style={{ width: "auto" }}
              title="Version affichée de l'organigramme"
            >
              <option value="">Principal</option>
              {versions.map((v) => (
                <option key={v.id} value={String(v.id)}>
                  {v.name}
                </option>
              ))}
            </select>
            <button
              type="button"
              onClick={() => void createVersion()}
              className="btn-secondary btn-sm inline-flex items-center gap-1"
              title="Crée une nouvelle version — copie des nœuds de la version affichée"
            >
              <Plus className="h-3.5 w-3.5" />
              Nouvelle version
            </button>
            {versionId != null ? (
              <button
                type="button"
                onClick={() => void deleteVersion()}
                className="btn-secondary btn-sm inline-flex items-center text-rose-400 hover:bg-rose-500/10"
                title="Supprimer cette version"
                aria-label="Supprimer cette version"
              >
                <Trash2 className="h-3.5 w-3.5" />
              </button>
            ) : null}
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
            {/* Bandeau : ajout manuel rapide + sync avec les fiches */}
            <div
              className="mb-2 flex flex-wrap items-center gap-2 rounded-xl border p-3"
              style={{
                borderColor: "var(--qg-border)",
                backgroundColor: "var(--qg-card-bg)"
              }}
            >
              <Plus className="h-4 w-4 text-accent-500" />
              <input
                value={quickLabel}
                onChange={(e) => setQuickLabel(e.target.value)}
                onKeyDown={(e) => {
                  // Entrée = ajout compagnie (le cas le plus fréquent).
                  if (e.key === "Enter") {
                    e.preventDefault();
                    void quickCreate("company");
                  }
                }}
                placeholder="Nom de la compagnie ou de la personne à ajouter…"
                className="input flex-1 min-w-[220px] text-sm"
              />
              <button
                type="button"
                onClick={() => void quickCreate("company")}
                disabled={creatingKind != null || !quickLabel.trim()}
                className="btn-accent inline-flex items-center gap-1 text-xs disabled:opacity-50"
                title="Ajoute une compagnie manuelle / externe (sans fiche Kratos — bulle bleue)"
              >
                {creatingKind === "company" ? (
                  <Loader2 className="h-3 w-3 animate-spin" />
                ) : (
                  <Building2 className="h-3 w-3" />
                )}
                + Compagnie
              </button>
              <button
                type="button"
                onClick={() => void quickCreate("person")}
                disabled={creatingKind != null || !quickLabel.trim()}
                className="btn-secondary btn-sm inline-flex items-center gap-1 disabled:opacity-50"
                title="Ajoute une personne physique (actionnaire, investisseur — bulle violette)"
              >
                {creatingKind === "person" ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <UserIcon className="h-3.5 w-3.5" />
                )}
                + Personne
              </button>
              <button
                type="button"
                onClick={() => void syncDetention()}
                disabled={syncing}
                className="btn-secondary btn-sm disabled:opacity-50"
                title="Crée les bulles manquantes (nos INCs et leurs actionnaires) et reconstruit les liens de détention depuis les « Partenaires & parts » des fiches d'entreprises, pourcentages inclus. Les positions des bulles existantes sont conservées."
              >
                {syncing ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Link2 className="h-3.5 w-3.5" />
                )}
                Synchroniser avec les fiches
              </button>
              <button
                type="button"
                onClick={() => void autoLayout()}
                disabled={layouting}
                className="btn-secondary btn-sm disabled:opacity-50"
                title="Range automatiquement les bulles par niveaux de détention : les détenteurs ultimes en haut, chaque compagnie sous ses détenteurs. Remplace les positions actuelles."
              >
                {layouting ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <LayoutGrid className="h-3.5 w-3.5" />
                )}
                Réorganiser
              </button>
              <div
                className="ml-auto inline-flex overflow-hidden rounded-lg border"
                style={{ borderColor: "var(--qg-border)" }}
                title="Périmètre affiché dans l'organigramme"
              >
                {(
                  [
                    ["complet", "Complet"],
                    ["internes", "Nos INCs"]
                  ] as const
                ).map(([val, lbl]) => (
                  <button
                    key={val}
                    type="button"
                    onClick={() => setScope(val)}
                    className="px-3 py-1.5 text-xs font-semibold transition"
                    style={{
                      backgroundColor:
                        scope === val
                          ? "var(--qg-accent)"
                          : "var(--qg-card-bg)",
                      color:
                        scope === val
                          ? "var(--qg-accent-ink, #0a0a0b)"
                          : "var(--qg-text-soft)"
                    }}
                  >
                    {lbl}
                  </button>
                ))}
              </div>
            </div>

            {structuralNodes.length > 0 ? (
              <p
                className="mb-2 text-[11px]"
                style={{ color: "var(--qg-text-soft)" }}
              >
                Déplace les bulles — elles s&apos;aimantent à la grille
                pour rester alignées. Tire depuis le point{" "}
                <span
                  className="inline-block h-2 w-2 rounded-full align-middle"
                  style={{ backgroundColor: "var(--qg-accent)" }}
                />{" "}
                d&apos;une bulle vers une autre pour créer une flèche de
                détention — la quote-part (%) est demandée au passage et
                s&apos;affiche sur la flèche. Survole une flèche pour la
                supprimer. Clique une bulle pour ouvrir son panneau
                (détenteurs, participations, fiche).
              </p>
            ) : null}

            {/* Légende des couleurs de bulles */}
            {structuralNodes.length > 0 ? (
              <div
                className="mb-3 flex flex-wrap items-center gap-4 text-[11px]"
                style={{ color: "var(--qg-text-soft)" }}
              >
                {(["inc", "externe", "person"] as const).map((k) => (
                  <span key={k} className="inline-flex items-center gap-1.5">
                    <span
                      aria-hidden
                      className={`inline-block h-2.5 w-2.5 rounded-full ${NATURE_STYLES[k].dotCls}`}
                    />
                    {NATURE_STYLES[k].label}
                  </span>
                ))}
              </div>
            ) : null}

            {structuralNodes.length === 0 ? (
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
                    onClick={() => void syncDetention()}
                    disabled={syncing}
                    className="btn-accent inline-flex items-center gap-1.5 text-sm disabled:opacity-50"
                    title="Crée une bulle par INC et par actionnaire, avec les liens de détention des fiches d'entreprises."
                  >
                    {syncing ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    ) : (
                      <Link2 className="h-3.5 w-3.5" />
                    )}
                    Synchroniser avec les fiches
                  </button>
                </div>
                <span
                  className="mt-2 block text-[10px]"
                  style={{ color: "var(--qg-text-soft)" }}
                >
                  ou ajoute une compagnie / personne via le bandeau
                  ci-dessus
                </span>
              </div>
            ) : (
              <CanvasView
                /* Canvas = organigramme structurel : seulement les
                   compagnies et les personnes (les anciens nœuds
                   dept / role / task sont filtrés). */
                nodes={structuralNodes}
                entreprises={entreprises}
                employes={employes}
                parentEntId={parentEntId}
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

// ─── Contrôle de zoom (canvas) ───────────────────────────────────

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

// ─── Vue Canvas type Miro ────────────────────────────────────────
//
// Bulles positionnables librement (pos_x / pos_y persistés) + flèches
// de détention auto-tracées (parent_id + co_owner_node_ids), toutes
// en trait plein — un co-détenteur est un propriétaire à part
// entière —, avec ajout / suppression manuelle. Tirer une flèche A→B
// re-parente B (ou ajoute A en co-détenteur) et demande la quote-part,
// affichée ensuite au milieu de la flèche.

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
  onPatch,
  onMove,
  onDelete
}: {
  nodes: OrgNode[];
  entreprises: Array<{ id: number; name: string }>;
  employes: Employe[];
  parentEntId: number | null;
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

  // Demande la quote-part (%) du nouveau détenteur — vide = sans %.
  // Accepte « 50 », « 50 % », « 33,33 »…
  function promptOwnershipPct(): number | null {
    const raw = window.prompt(
      "Quote-part (%) de ce détenteur ? (vide = sans %)"
    );
    if (raw == null) return null;
    const cleaned = raw.replace("%", "").replace(",", ".").trim();
    if (!cleaned) return null;
    const pct = Number(cleaned);
    return Number.isNaN(pct) ? null : pct;
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
      const pct = promptOwnershipPct();
      if (pct != null) {
        void onPatch(toId, {
          ownership_json: JSON.stringify({
            ...parseOwnership(target),
            [String(fromId)]: pct
          })
        });
      }
    } else if (
      target.parent_id !== fromId &&
      !(target.co_owner_node_ids || []).includes(fromId)
    ) {
      // Détenteur principal déjà défini → co-détention.
      const patch: Partial<OrgNode> = {
        co_owner_node_ids: [...(target.co_owner_node_ids || []), fromId]
      };
      const pct = promptOwnershipPct();
      if (pct != null) {
        patch.ownership_json = JSON.stringify({
          ...parseOwnership(target),
          [String(fromId)]: pct
        });
      }
      void onPatch(toId, patch);
    }
  }

  function deleteArrow(a: {
    fromId: number;
    toId: number;
    kind: "parent" | "coowner";
  }) {
    const target = byId.get(a.toId);
    // Retirer un lien retire aussi la quote-part de ce détenteur.
    const owns = parseOwnership(target);
    const hasPct = String(a.fromId) in owns;
    delete owns[String(a.fromId)];
    const nextOwnership =
      Object.keys(owns).length > 0 ? JSON.stringify(owns) : null;
    if (a.kind === "parent") {
      const roots = nodes.filter(
        (n) => n.parent_id == null && n.id !== a.toId
      );
      void onMove(a.toId, null, roots.length);
      if (hasPct) void onPatch(a.toId, { ownership_json: nextOwnership });
    } else {
      if (!target) return;
      void onPatch(a.toId, {
        co_owner_node_ids: (target.co_owner_node_ids || []).filter(
          (x) => x !== a.fromId
        ),
        ...(hasPct ? { ownership_json: nextOwnership } : {})
      });
    }
  }

  // Retire un lien de détention ownerId → nodeId (panneau latéral) —
  // même logique que la suppression d'une flèche au survol.
  function removeOwner(nodeId: number, ownerId: number) {
    const target = byId.get(nodeId);
    if (!target) return;
    deleteArrow({
      fromId: ownerId,
      toId: nodeId,
      kind: target.parent_id === ownerId ? "parent" : "coowner"
    });
  }

  // Ajoute un détenteur ownerId → nodeId avec sa quote-part (panneau
  // latéral) — même logique que le tracé d'une flèche : re-parentage
  // si la bulle n'a pas encore de détenteur principal, sinon
  // co-détention. La quote-part atterrit dans ownership_json du
  // nœud détenu (clé = id du détenteur).
  function addOwner(nodeId: number, ownerId: number, pct: number | null) {
    if (ownerId === nodeId) return;
    // Anti-boucle : le détenteur ne peut pas être un descendant.
    if (subtreeOf(nodeId).has(ownerId)) return;
    const target = byId.get(nodeId);
    if (!target) return;
    const nextOwnership =
      pct != null
        ? JSON.stringify({
            ...parseOwnership(target),
            [String(ownerId)]: pct
          })
        : null;
    if (target.parent_id == null) {
      const siblings = nodes.filter(
        (n) => n.parent_id === ownerId && n.id !== nodeId
      );
      void onMove(nodeId, ownerId, siblings.length);
      if (nextOwnership != null)
        void onPatch(nodeId, { ownership_json: nextOwnership });
    } else if (
      target.parent_id !== ownerId &&
      !(target.co_owner_node_ids || []).includes(ownerId)
    ) {
      const patch: Partial<OrgNode> = {
        co_owner_node_ids: [...(target.co_owner_node_ids || []), ownerId]
      };
      if (nextOwnership != null) patch.ownership_json = nextOwnership;
      void onPatch(nodeId, patch);
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
            // Quote-part du détenteur (fromId) dans le nœud détenu
            // (toId) — stockée sur le détenu, clé = id du détenteur.
            const pct = parseOwnership(byId.get(a.toId))[String(a.fromId)];
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
                {pct != null ? (
                  // Quote-part au milieu de la flèche — halo card-bg
                  // (paint-order) pour rester lisible sur le quadrillage.
                  <text
                    x={mid.x}
                    y={mid.y - 8}
                    textAnchor="middle"
                    fontSize={11}
                    fontWeight={600}
                    fill="var(--qg-text)"
                    stroke="var(--qg-card-bg)"
                    strokeWidth={4}
                    paintOrder="stroke"
                    style={{ pointerEvents: "none" }}
                  >
                    {formatPct(pct)}
                  </text>
                ) : null}
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
          onPatch={onPatch}
          onDelete={onDelete}
          onRemoveOwner={removeOwner}
          onAddOwner={addOwner}
          onSelect={setSelectedId}
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
  // Couleur ET badge de la bulle selon sa NATURE : INC Kratos
  // (ambre), compagnie externe (sky), personne (violet) — cf. légende.
  const nature = nodeNature(node);
  const natureStyle = NATURE_STYLES[nature];
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
      className={`absolute select-none rounded-xl border ${natureStyle.bubbleCls}`}
      style={{
        left: x,
        top: y,
        width: BUBBLE_W,
        minHeight: BUBBLE_H,
        // Nature « autre » : rendu neutre historique (les natures
        // colorées passent par les classes Tailwind ci-dessus).
        ...(nature === "autre"
          ? {
              borderColor: "var(--qg-border)",
              backgroundColor: "var(--qg-card-bg)"
            }
          : {}),
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
          className={`shrink-0 rounded-full border px-1.5 py-0 text-[8px] font-bold uppercase ${natureStyle.badgeCls}`}
        >
          {natureStyle.badge}
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

// Panneau latéral du canvas — s'ouvre au clic sur une bulle.
// Sous-fiche épurée : nature, nom, lien / liaison vers la fiche INC,
// détenteurs (ajout / retrait avec quotes-parts), participations
// (cliquables) et notes libres. La ligne « Détention : … » écrite par
// la sync est montrée à part, en lecture seule.
function CanvasNodeEditor({
  node,
  allNodes,
  entreprises,
  onPatch,
  onDelete,
  onRemoveOwner,
  onAddOwner,
  onSelect,
  onClose
}: {
  node: OrgNode;
  allNodes: OrgNode[];
  entreprises: Array<{ id: number; name: string }>;
  onPatch: (id: number, patch: Partial<OrgNode>) => Promise<void>;
  onDelete: (id: number) => Promise<void>;
  onRemoveOwner: (nodeId: number, ownerId: number) => void;
  onAddOwner: (
    nodeId: number,
    ownerId: number,
    pct: number | null
  ) => void;
  onSelect: (id: number) => void;
  onClose: () => void;
}) {
  const [label, setLabel] = useState(node.label);
  useEffect(() => {
    setLabel(node.label);
  }, [node.id, node.label]);

  // Formulaire « + Ajouter un détenteur » : sélection + quote-part.
  const [newOwnerId, setNewOwnerId] = useState("");
  const [newOwnerPct, setNewOwnerPct] = useState("");
  useEffect(() => {
    setNewOwnerId("");
    setNewOwnerPct("");
  }, [node.id]);

  const natureStyle = NATURE_STYLES[nodeNature(node)];

  // Détenteurs de CE nœud : parent (détenteur principal) +
  // co-détenteurs, avec leur quote-part depuis ownership_json.
  const ownership = parseOwnership(node);
  const ownerIds: number[] = [];
  if (node.parent_id != null) ownerIds.push(node.parent_id);
  for (const id of node.co_owner_node_ids || []) {
    if (!ownerIds.includes(id)) ownerIds.push(id);
  }
  const owners = ownerIds
    .map((id) => allNodes.find((n) => n.id === id))
    .filter((n): n is OrgNode => Boolean(n))
    .map((n) => ({ owner: n, pct: ownership[String(n.id)] }));

  // Participations : les nœuds dont CE nœud est parent ou
  // co-détenteur, avec la quote-part qu'il y détient.
  const held = allNodes
    .filter(
      (m) =>
        m.id !== node.id &&
        (m.parent_id === node.id ||
          (m.co_owner_node_ids || []).includes(node.id))
    )
    .map((m) => ({ held: m, pct: parseOwnership(m)[String(node.id)] }));

  // Candidats détenteurs : les autres bulles de la version, hors
  // détenteurs actuels.
  const ownerCandidates = allNodes
    .filter((n) => n.id !== node.id && !ownerIds.includes(n.id))
    .sort((a, b) => a.label.localeCompare(b.label, "fr"));

  function addOwnerFromForm() {
    if (!newOwnerId) return;
    const cleaned = newOwnerPct
      .replace("%", "")
      .replace(",", ".")
      .trim();
    const pct = cleaned ? Number(cleaned) : NaN;
    onAddOwner(
      node.id,
      Number(newOwnerId),
      Number.isNaN(pct) ? null : pct
    );
    setNewOwnerId("");
    setNewOwnerPct("");
  }

  // Notes libres, sans la ligne « Détention : … » (affichée à part).
  const { detention, notes } = splitDescription(node.description);

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
          className={`rounded-full border px-1.5 py-0 text-[9px] font-bold uppercase ${natureStyle.badgeCls}`}
        >
          {natureStyle.label}
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

      {node.kind === "company" ? (
        node.entreprise_id ? (
          <Link
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            href={`/entreprises/${node.entreprise_id}` as any}
            className="btn-accent inline-flex w-fit items-center gap-1 text-xs"
          >
            <ExternalLink className="h-3.5 w-3.5" />
            Ouvrir la fiche
          </Link>
        ) : (
          <div>
            <label
              className="text-[9px] font-semibold uppercase tracking-wide"
              style={{ color: "var(--qg-text-soft)" }}
            >
              Lier à une de nos INCs
            </label>
            <select
              value=""
              onChange={(e) => {
                if (e.target.value)
                  void onPatch(node.id, {
                    entreprise_id: Number(e.target.value)
                  });
              }}
              className="input mt-0.5 text-[11px]"
              title="Relie cette compagnie à sa fiche Kratos — la bulle devient une INC Kratos (ambre)"
            >
              <option value="">— non liée —</option>
              {entreprises.map((ent) => (
                <option key={ent.id} value={String(ent.id)}>
                  {ent.name}
                </option>
              ))}
            </select>
          </div>
        )
      ) : null}

      {/* Détenue par — les détenteurs de cette bulle + quote-part. */}
      <div>
        <p
          className="text-[9px] font-semibold uppercase tracking-wide"
          style={{ color: "var(--qg-text-soft)" }}
        >
          Détenue par
        </p>
        {owners.length === 0 ? (
          <p
            className="mt-0.5 text-[11px]"
            style={{ color: "var(--qg-text-muted)" }}
          >
            Aucun détenteur — bulle racine.
          </p>
        ) : (
          <ul className="mt-0.5 space-y-0.5 text-[11px]">
            {owners.map(({ owner, pct }) => (
              <li
                key={owner.id}
                className="flex items-center gap-2 rounded px-1.5 py-0.5"
                style={{ backgroundColor: "var(--qg-bg-alt, transparent)" }}
              >
                <span
                  className="min-w-0 flex-1 truncate"
                  style={{ color: "var(--qg-text)" }}
                >
                  {owner.label}
                </span>
                {pct != null ? (
                  <span
                    className="shrink-0 font-semibold"
                    style={{ color: "var(--qg-text-muted)" }}
                  >
                    {formatPct(pct)}
                  </span>
                ) : null}
                <button
                  type="button"
                  onClick={() => onRemoveOwner(node.id, owner.id)}
                  className="shrink-0 rounded p-0.5 text-white/40 hover:bg-rose-500/15 hover:text-rose-300"
                  title={`Retirer ${owner.label} des détenteurs`}
                  aria-label={`Retirer ${owner.label} des détenteurs`}
                >
                  <X className="h-3 w-3" />
                </button>
              </li>
            ))}
          </ul>
        )}
        {ownerCandidates.length > 0 ? (
          <div className="mt-1 flex items-center gap-1">
            <select
              value={newOwnerId}
              onChange={(e) => setNewOwnerId(e.target.value)}
              className="input min-w-0 flex-1 text-[11px]"
              title="Choisis la compagnie ou la personne qui détient cette bulle"
            >
              <option value="">+ Ajouter un détenteur…</option>
              {ownerCandidates.map((n) => (
                <option key={n.id} value={String(n.id)}>
                  {n.label}
                </option>
              ))}
            </select>
            <input
              value={newOwnerPct}
              onChange={(e) => setNewOwnerPct(e.target.value)}
              className="input w-14 text-[11px]"
              placeholder="%"
              title="Quote-part (%) du détenteur — vide = sans %"
            />
            <button
              type="button"
              onClick={addOwnerFromForm}
              disabled={!newOwnerId}
              className="btn-secondary btn-sm shrink-0 disabled:opacity-50"
              title="Créer le lien de détention"
              aria-label="Créer le lien de détention"
            >
              <Plus className="h-3.5 w-3.5" />
            </button>
          </div>
        ) : null}
      </div>

      {/* Détient — les participations de cette bulle + quote-part. */}
      <div>
        <p
          className="text-[9px] font-semibold uppercase tracking-wide"
          style={{ color: "var(--qg-text-soft)" }}
        >
          Détient
        </p>
        {held.length === 0 ? (
          <p
            className="mt-0.5 text-[11px]"
            style={{ color: "var(--qg-text-muted)" }}
          >
            Aucune participation.
          </p>
        ) : (
          <ul className="mt-0.5 space-y-0.5 text-[11px]">
            {held.map(({ held: h, pct }) => (
              <li key={h.id}>
                <button
                  type="button"
                  onClick={() => onSelect(h.id)}
                  className="flex w-full items-center justify-between gap-2 rounded px-1.5 py-0.5 text-left hover:bg-accent-500/10"
                  style={{
                    backgroundColor: "var(--qg-bg-alt, transparent)"
                  }}
                  title={`Voir ${h.label}`}
                >
                  <span
                    className="min-w-0 flex-1 truncate"
                    style={{ color: "var(--qg-text)" }}
                  >
                    {h.label}
                  </span>
                  {pct != null ? (
                    <span
                      className="shrink-0 font-semibold"
                      style={{ color: "var(--qg-text-muted)" }}
                    >
                      {formatPct(pct)}
                    </span>
                  ) : null}
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      {/* Notes libres — la ligne « Détention : … » (écrite par la
          sync) est montrée à part et recomposée au PATCH. */}
      <div>
        <p
          className="text-[9px] font-semibold uppercase tracking-wide"
          style={{ color: "var(--qg-text-soft)" }}
        >
          Notes
        </p>
        {detention ? (
          <p
            className="mt-0.5 whitespace-pre-line rounded border p-2 text-[10px]"
            style={{
              borderColor: "var(--qg-border-soft)",
              color: "var(--qg-text-muted)"
            }}
            title="Ligne maintenue par « Synchroniser avec les fiches » — se met à jour toute seule"
          >
            {detention}
          </p>
        ) : null}
        <textarea
          key={node.id}
          defaultValue={notes}
          onBlur={(e) => {
            if (e.target.value.trim() !== notes) {
              void onPatch(node.id, {
                description: composeDescription(detention, e.target.value)
              });
            }
          }}
          rows={3}
          className="input mt-1 text-[11px]"
          placeholder="Notes libres sur cette compagnie / personne…"
        />
      </div>
    </div>
  );
}
