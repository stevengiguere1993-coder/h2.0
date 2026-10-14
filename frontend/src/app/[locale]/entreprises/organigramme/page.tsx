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
  ExternalLink,
  FileDown,
  Info,
  LayoutGrid,
  Loader2,
  Plus,
  RefreshCw,
  Search,
  Sparkles,
  Star,
  Trash2,
  Users,
  X
} from "lucide-react";

import { authedFetch } from "@/lib/auth";
import { Link } from "@/i18n/navigation";
import { PageDriveSection } from "@/components/drive/PageDriveSection";
import {
  construirePdfOrganigramme,
  FORMATS_PDF,
  nomFichierPdf,
  type PdfBulle,
  type PdfEchelle,
  type PdfFleche,
  type PdfFormat,
  type PdfOrientation
} from "@/components/entreprises/organigramme-pdf";
import { QGTopbar, useEntreprisesLayout } from "../layout";

/**
 * Page Organigramme — canvas libre type Miro, seule vue de la page.
 *
 * Retour Phil 2026-10-08 : l'organigramme ne s'édite plus à la main.
 * TOUT vient des fiches d'entreprises (Partenaires & parts) :
 *  • « Synchroniser » crée les bulles manquantes (nos INCs actives et
 *    leurs détenteurs) EN BAS du canevas — rien d'existant ne bouge —,
 *    reconstruit les flèches de détention et retire les bulles qui ne
 *    correspondent plus à rien ;
 *  • la nature d'une bulle vient de la fiche : INC du groupe (ambre),
 *    compagnie hors groupe (bleu — case « personne morale » de la ligne
 *    partenaire ou indices dans le nom), personne (violet) ;
 *  • on déplace les bulles, on zoome, on bascule Complet / Nos INCs ;
 *  • « Mettre en évidence » (recherche avec suggestions) fait ressortir
 *    une bulle — ex. la compagnie acquéreuse montrée à la banque ;
 *  • « Exporter en PDF » : orientation, format, échelle, aperçu.
 * Les VERSIONS (copies indépendantes) se gèrent depuis le topbar.
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
  // Nature forcée d'un détenteur hors groupe (person | company).
  nature_forced: string | null;
  // Calculé par l'API : la bulle ne correspond à rien dans les fiches
  // actives → à retirer (bouton) ou à inscrire dans une fiche.
  absent_des_fiches: boolean;
  created_at: string;
  updated_at: string;
};

type OrgVersion = {
  id: number;
  name: string;
  created_at: string;
};

type SyncRapport = {
  crees: string[];
  reclasses: string[];
  absents: string[];
  sans_lignes: string[];
};

// ─── Nature des bulles (couleurs du canvas + légende) ────────────
//
//  • INC du groupe        : company reliée à une fiche entreprise → ambre
//  • Compagnie hors groupe: company sans fiche (actionnaire externe) → sky
//  • Personne             : kind person → violet
//  • autre                : héritage (service partagé…) → neutre
// La nature est décidée par la sync depuis les fiches ; le panneau
// permet de corriger personne ↔ compagnie (répercuté sur la fiche).

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
    label: "INC du groupe",
    badge: "INC du groupe",
    bubbleCls: "border-amber-500/70 bg-amber-500/15",
    dotCls: "bg-amber-500",
    badgeCls: "bg-amber-500/20 text-amber-500 border-amber-500/40"
  },
  externe: {
    label: "Compagnie hors groupe",
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

// Mise en évidence (recherche) : vert franc, hors palette des natures,
// pour « sortir du lot » — à l'écran comme dans le PDF.
const HIGHLIGHT = {
  label: "Mise en évidence",
  bubbleCls: "border-emerald-500 bg-emerald-500/25",
  dotCls: "bg-emerald-500",
  shadow:
    "0 0 0 3px rgb(16 185 129), 0 0 0 9px rgb(16 185 129 / 0.25), 0 10px 28px -6px rgb(16 185 129 / 0.6)"
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

// Recherche insensible aux accents et à la casse.
const normaliser = (s: string) =>
  s
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .trim();

// ─── Géométrie du canvas (bulles + grille) ───────────────────────
// Partagée par le canvas, le rangement automatique (« Réorganiser »),
// le placement des nouveautés et l'export PDF. Le backend place les
// nouvelles bulles avec les mêmes constantes (org_nodes.py).
const BUBBLE_W = 210;
const BUBBLE_H = 66;
const CANVAS_PAD = 400;
// Pas de la grille (= taille du quadrillage de fond). Les bulles
// s'aimantent dessus → lignes droites, niveaux alignés.
const GRID = 24;
const snap = (v: number) => Math.round(v / GRID) * GRID;

type XY = { x: number; y: number };

// Position de chaque bulle : celle du serveur, sinon une rangée SOUS
// tout ce qui existe (une bulle sans position = nouveauté pas encore
// placée — même règle que la sync côté serveur).
function resolvePositions(nodes: OrgNode[]): Map<number, XY> {
  const out = new Map<number, XY>();
  let maxY = -Infinity;
  for (const n of nodes) {
    if (n.pos_x != null && n.pos_y != null) {
      out.set(n.id, { x: n.pos_x, y: n.pos_y });
      maxY = Math.max(maxY, n.pos_y);
    }
  }
  let x = GRID;
  let y = Number.isFinite(maxY) ? snap(maxY + BUBBLE_H + GRID * 3) : GRID;
  let col = 0;
  for (const n of nodes) {
    if (out.has(n.id)) continue;
    out.set(n.id, { x, y });
    col += 1;
    x += BUBBLE_W + GRID * 2;
    if (col >= 8) {
      col = 0;
      x = GRID;
      y += BUBBLE_H + GRID * 3;
    }
  }
  return out;
}

type Arrow = {
  key: string;
  fromId: number;
  toId: number;
  kind: "parent" | "coowner";
};

// Flèches de détention : parent_id + co_owner_node_ids, toutes en
// trait plein (la détention compte autant pour tous les détenteurs).
// Les flèches vers une bulle hors périmètre sont sautées.
function buildArrows(nodes: OrgNode[]): Arrow[] {
  const ids = new Set(nodes.map((n) => n.id));
  const out: Arrow[] = [];
  for (const n of nodes) {
    if (n.parent_id != null && ids.has(n.parent_id))
      out.push({
        key: `p-${n.parent_id}-${n.id}`,
        fromId: n.parent_id,
        toId: n.id,
        kind: "parent"
      });
    for (const co of n.co_owner_node_ids || [])
      if (ids.has(co))
        out.push({
          key: `c-${co}-${n.id}`,
          fromId: co,
          toId: n.id,
          kind: "coowner"
        });
  }
  return out;
}

function texteRapport(r: SyncRapport): string {
  const parts: string[] = [];
  if (r.crees.length)
    parts.push(
      `${r.crees.length} nouvelle(s) bulle(s) placée(s) en bas du canevas : ${r.crees.join(", ")}`
    );
  if (r.reclasses.length)
    parts.push(
      `${r.reclasses.length} reclassée(s) personne ↔ compagnie : ${r.reclasses.join(", ")}`
    );
  if (r.absents.length)
    parts.push(
      `${r.absents.length} bulle(s) absente(s) des fiches (en pointillé — à retirer ou à inscrire dans une fiche) : ${r.absents.join(", ")}`
    );
  if (r.sans_lignes.length)
    parts.push(
      `${r.sans_lignes.length} INC(s) sans ligne Partenaires & parts (leurs liens affichés ne viennent pas des fiches) : ${r.sans_lignes.join(", ")}`
    );
  return parts.length
    ? `Synchronisé — ${parts.join(" · ")}.`
    : "Synchronisé — déjà à jour, rien n'a changé.";
}

export default function OrganigrammePage() {
  const { entreprises } = useEntreprisesLayout();
  const [nodes, setNodes] = useState<OrgNode[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [syncing, setSyncing] = useState(false);
  const [layouting, setLayouting] = useState(false);
  //: Périmètre affiché : « complet » (INCs + détenteurs externes) ou
  //: « internes » (seulement nos compagnies) — retour Phil 2026-08-10.
  const [scope, setScope] = useState<"complet" | "internes">("complet");
  // Bulle mise en évidence (recherche) — partagée avec l'export PDF.
  const [highlightId, setHighlightId] = useState<number | null>(null);
  const [exportOpen, setExportOpen] = useState(false);

  // Versions de l'organigramme : null = « Principal » (les nœuds sans
  // version_id). Chaque version est une copie indépendante des nœuds.
  const [versionId, setVersionId] = useState<number | null>(null);
  const [versions, setVersions] = useState<OrgVersion[]>([]);

  // Entreprise mère du groupe — étoile sur SA bulle.
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
      const n = await authedFetch(
        `/api/v1/org-nodes${
          versionId != null ? `?version_id=${versionId}` : ""
        }`
      );
      if (n.ok) setNodes((await n.json()) as OrgNode[]);
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

  // Changement de version : la mise en évidence ne s'y applique plus.
  useEffect(() => {
    setHighlightId(null);
    setInfo(null);
  }, [versionId]);

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

  // Seule porte d'entrée : tout vient des fiches d'entreprises.
  async function syncDetention() {
    setSyncing(true);
    setError(null);
    setInfo(null);
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
      const body = (await r.json()) as {
        nodes: OrgNode[];
        rapport: SyncRapport;
      };
      setNodes(body.nodes);
      setInfo(texteRapport(body.rapport));
      if (
        highlightId != null &&
        !body.nodes.some((n) => n.id === highlightId)
      )
        setHighlightId(null);
    } catch (e) {
      setError(`Synchronisation échouée : ${(e as Error).message}`);
    } finally {
      setSyncing(false);
    }
  }

  // Sous-ensemble « structurel » affiché au canvas : compagnies et
  // personnes. On exclut les départements, rôles et tâches (héritage
  // des anciennes vues) — l'organigramme montre la détention.
  const structuralNodes = useMemo(
    () =>
      nodes.filter(
        (n) =>
          n.kind !== "dept" &&
          n.kind !== "role" &&
          n.kind !== "task" &&
          // Vue « Nos INCs » : seulement les compagnies du groupe — les
          // personnes et compagnies hors groupe sont cachées (les
          // flèches vers les bulles cachées sont sautées).
          (scope === "complet" || nodeNature(n) === "inc")
      ),
    [nodes, scope]
  );

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

  // Correction personne ↔ compagnie d'un détenteur hors groupe —
  // répercutée sur ses lignes Partenaires & parts (source de vérité).
  async function setNature(id: number, nature: "person" | "company") {
    setError(null);
    try {
      const r = await authedFetch(`/api/v1/org-nodes/${id}/nature`, {
        method: "POST",
        body: JSON.stringify({ nature })
      });
      if (!r.ok) {
        const txt = await r.text();
        throw new Error(txt.slice(0, 200) || `HTTP ${r.status}`);
      }
      const updated = (await r.json()) as OrgNode;
      setNodes((prev) => prev.map((n) => (n.id === id ? updated : n)));
    } catch (e) {
      setError(`Changement de nature échoué : ${(e as Error).message}`);
    }
  }

  // Retrait d'une bulle ABSENTE des fiches (seul cas où l'on supprime
  // ici). L'API détache ce qu'elle détenait au lieu de l'emporter.
  async function deleteNode(id: number) {
    const n = nodes.find((x) => x.id === id);
    if (!n) return;
    if (
      !window.confirm(
        `Retirer la bulle « ${n.label} » de l'organigramme ? Les compagnies qu'elle détenait restent.`
      )
    )
      return;
    setError(null);
    try {
      const r = await authedFetch(`/api/v1/org-nodes/${id}`, {
        method: "DELETE"
      });
      if (!r.ok && r.status !== 204) throw new Error(`HTTP ${r.status}`);
      setNodes((prev) =>
        prev
          .filter((x) => x.id !== id)
          .map((x) => ({
            ...x,
            parent_id: x.parent_id === id ? null : x.parent_id,
            co_owner_node_ids: (x.co_owner_node_ids || []).filter(
              (c) => c !== id
            )
          }))
      );
      if (highlightId === id) setHighlightId(null);
    } catch (e) {
      setError(`Retrait échoué : ${(e as Error).message}`);
    }
  }

  // Rangement automatique (« Réorganiser ») : bulles disposées par
  // COUCHES de détention — niveau 0 = les détenteurs ultimes (aucun
  // parent ni co-détenteur), puis chaque nœud une rangée sous son
  // détenteur le plus profond. Action explicite et confirmée : la sync,
  // elle, ne bouge jamais rien.
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
      const holdersOf = new Map<number, number[]>();
      for (const n of list) {
        const hs: number[] = [];
        if (n.parent_id != null && ids.has(n.parent_id))
          hs.push(n.parent_id);
        for (const co of n.co_owner_node_ids || [])
          if (ids.has(co) && !hs.includes(co)) hs.push(co);
        holdersOf.set(n.id, hs);
      }
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
          await patchNode(arr[i].id, { pos_x: x, pos_y: y });
        }
      }
      await load();
    } finally {
      setLayouting(false);
    }
  }

  const versionName =
    versionId != null
      ? versions.find((v) => v.id === versionId)?.name || `Version ${versionId}`
      : "Principal";
  const scopeLabel = scope === "complet" ? "Complet" : "Nos INCs";
  const highlightNode =
    highlightId != null
      ? structuralNodes.find((n) => n.id === highlightId) || null
      : null;

  // Données de l'export PDF = exactement ce que le canvas affiche.
  const pdfData = useMemo(() => {
    const pos = resolvePositions(structuralNodes);
    const bulles: PdfBulle[] = structuralNodes.map((n) => {
      const p = pos.get(n.id) || { x: 0, y: 0 };
      return {
        id: n.id,
        label: n.label,
        nature: nodeNature(n),
        societeMere:
          n.kind === "company" &&
          parentEntId != null &&
          n.entreprise_id === parentEntId,
        enEvidence: n.id === highlightId,
        x: p.x,
        y: p.y
      };
    });
    const byId = new Map(structuralNodes.map((n) => [n.id, n]));
    const fleches: PdfFleche[] = buildArrows(structuralNodes).map((a) => ({
      fromId: a.fromId,
      toId: a.toId,
      pct: parseOwnership(byId.get(a.toId))[String(a.fromId)] ?? null
    }));
    return { bulles, fleches };
  }, [structuralNodes, parentEntId, highlightId]);

  return (
    <>
      <QGTopbar
        greeting={
          <span className="inline-flex items-center gap-2">
            <Users className="h-4 w-4 text-accent-500" />
            Organigramme
          </span>
        }
        subtitle="Structure de détention du groupe — compagnies, personnes et quotes-parts, synchronisée depuis les fiches d'entreprises"
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
            {/* Bandeau : sync, rangement, mise en évidence, export, périmètre */}
            <div
              className="mb-2 flex flex-wrap items-center gap-2 rounded-xl border p-3"
              style={{
                borderColor: "var(--qg-border)",
                backgroundColor: "var(--qg-card-bg)"
              }}
            >
              <button
                type="button"
                onClick={() => void syncDetention()}
                disabled={syncing}
                className="btn-accent inline-flex items-center gap-1.5 text-xs disabled:opacity-50"
                title="Crée les bulles manquantes (nos INCs actives et leurs détenteurs) en bas du canevas, reconstruit les flèches de détention et les quotes-parts depuis les « Partenaires & parts » des fiches, retire ce qui n'existe plus. Les bulles existantes ne bougent pas."
              >
                {syncing ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <RefreshCw className="h-3.5 w-3.5" />
                )}
                Synchroniser
              </button>
              <button
                type="button"
                onClick={() => void autoLayout()}
                disabled={layouting || structuralNodes.length === 0}
                className="btn-secondary btn-sm inline-flex items-center gap-1 disabled:opacity-50"
                title="Range automatiquement les bulles par niveaux de détention : les détenteurs ultimes en haut, chaque compagnie sous ses détenteurs. Remplace les positions actuelles (demande confirmation)."
              >
                {layouting ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <LayoutGrid className="h-3.5 w-3.5" />
                )}
                Réorganiser
              </button>
              <HighlightSearch
                nodes={structuralNodes}
                highlightId={highlightId}
                onChange={setHighlightId}
              />
              <button
                type="button"
                onClick={() => setExportOpen(true)}
                disabled={structuralNodes.length === 0}
                className="btn-secondary btn-sm inline-flex items-center gap-1 disabled:opacity-50"
                title="Exporter l'organigramme affiché en PDF (orientation, format, échelle, aperçu)"
              >
                <FileDown className="h-3.5 w-3.5" />
                Exporter en PDF
              </button>
              <div
                className="ml-auto inline-flex overflow-hidden rounded-lg border"
                style={{ borderColor: "var(--qg-border)" }}
                title="Périmètre affiché dans l'organigramme (et dans le PDF)"
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

            {info ? (
              <div
                className="mb-2 flex items-start gap-2 rounded-lg border px-3 py-2 text-xs"
                style={{
                  borderColor: "var(--qg-border)",
                  backgroundColor: "var(--qg-card-bg)",
                  color: "var(--qg-text)"
                }}
              >
                <Info className="mt-0.5 h-3.5 w-3.5 shrink-0 text-accent-500" />
                <span className="min-w-0 flex-1">{info}</span>
                <button
                  type="button"
                  onClick={() => setInfo(null)}
                  className="rounded p-0.5 text-white/40 hover:text-accent-400"
                  aria-label="Fermer"
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              </div>
            ) : null}

            {structuralNodes.length > 0 ? (
              <p
                className="mb-2 text-[11px]"
                style={{ color: "var(--qg-text-soft)" }}
              >
                Les bulles et les flèches viennent des fiches
                d&apos;entreprises (Partenaires &amp; parts) — pour
                ajouter ou corriger quelque chose, modifie la fiche puis
                clique « Synchroniser » : les nouveautés arrivent en bas
                du canevas, rien d&apos;existant ne bouge. Déplace les
                bulles pour faire beau (elles s&apos;aimantent à la
                grille), clique une bulle pour voir ses détenteurs et ses
                participations.
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
                <span className="inline-flex items-center gap-1.5">
                  <span
                    aria-hidden
                    className={`inline-block h-2.5 w-2.5 rounded-full ${HIGHLIGHT.dotCls}`}
                  />
                  {HIGHLIGHT.label}
                </span>
                {structuralNodes.some((n) => n.absent_des_fiches) ? (
                  <span
                    className="inline-flex items-center gap-1.5"
                    title="Bulle qui ne correspond à rien dans les fiches actives : retire-la (panneau) ou inscris l'actionnaire dans une fiche"
                  >
                    <span
                      aria-hidden
                      className="inline-block h-2.5 w-2.5 rounded-full border border-dashed border-rose-400"
                    />
                    Absent des fiches (à retirer ou à inscrire dans une fiche)
                  </span>
                ) : null}
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
                <p>
                  {scope === "internes" && nodes.length > 0
                    ? "Aucune compagnie du groupe dans cette version."
                    : "Aucune bulle d'organigramme pour l'instant."}
                </p>
                <div className="mt-3 flex flex-wrap items-center justify-center gap-2">
                  <button
                    type="button"
                    onClick={() => void syncDetention()}
                    disabled={syncing}
                    className="btn-accent inline-flex items-center gap-1.5 text-sm disabled:opacity-50"
                    title="Crée une bulle par INC active et par détenteur, avec les liens de détention des fiches d'entreprises."
                  >
                    {syncing ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    ) : (
                      <RefreshCw className="h-3.5 w-3.5" />
                    )}
                    Synchroniser depuis les fiches
                  </button>
                </div>
              </div>
            ) : (
              <CanvasView
                nodes={structuralNodes}
                parentEntId={parentEntId}
                highlightId={highlightId}
                onHighlight={setHighlightId}
                onPatch={patchNode}
                onSetNature={setNature}
                onDelete={deleteNode}
              />
            )}
          </>
        )}
      </div>

      {exportOpen ? (
        <ExportPdfModal
          bulles={pdfData.bulles}
          fleches={pdfData.fleches}
          versionName={versionName}
          scopeLabel={scopeLabel}
          highlightLabel={highlightNode ? highlightNode.label : null}
          onClose={() => setExportOpen(false)}
        />
      ) : null}
    </>
  );
}

// ─── Recherche / mise en évidence ────────────────────────────────
//
// Champ avec suggestions : on tape le nom d'une compagnie ou d'une
// personne, on choisit, et la bulle ressort en vert sur le canevas
// (et dans le PDF). Une seule bulle à la fois ; la croix l'enlève.

function HighlightSearch({
  nodes,
  highlightId,
  onChange
}: {
  nodes: OrgNode[];
  highlightId: number | null;
  onChange: (id: number | null) => void;
}) {
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(false);
  const [idx, setIdx] = useState(0);
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const selected =
    highlightId != null ? nodes.find((n) => n.id === highlightId) || null : null;

  const results = useMemo(() => {
    const nq = normaliser(q);
    return nodes
      .filter((n) => !nq || normaliser(n.label).includes(nq))
      .sort((a, b) => a.label.localeCompare(b.label, "fr"))
      .slice(0, 8);
  }, [nodes, q]);

  useEffect(() => {
    setIdx(0);
  }, [q, open]);

  // Clic hors du champ → ferme les suggestions.
  useEffect(() => {
    const onDown = (e: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node))
        setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, []);

  function choisir(n: OrgNode) {
    onChange(n.id);
    setQ("");
    setOpen(false);
  }

  return (
    <div ref={wrapRef} className="relative min-w-[260px] flex-1 max-w-sm">
      <div
        className="flex items-center gap-1.5 rounded-lg border px-2"
        style={{
          borderColor: selected ? "rgb(16 185 129)" : "var(--qg-border)",
          backgroundColor: "var(--qg-bg, transparent)"
        }}
        title="Tape le nom d'une compagnie ou d'une personne : la bulle choisie ressort en vert sur le canevas et dans le PDF (ex. la compagnie acquéreuse)"
      >
        {selected ? (
          <Sparkles className="h-3.5 w-3.5 shrink-0 text-emerald-500" />
        ) : (
          <Search
            className="h-3.5 w-3.5 shrink-0"
            style={{ color: "var(--qg-text-soft)" }}
          />
        )}
        <input
          value={open ? q : selected ? selected.label : q}
          onChange={(e) => {
            setQ(e.target.value);
            setOpen(true);
          }}
          onFocus={() => {
            setQ("");
            setOpen(true);
          }}
          onKeyDown={(e) => {
            if (e.key === "ArrowDown") {
              e.preventDefault();
              setOpen(true);
              setIdx((i) => Math.min(results.length - 1, i + 1));
            } else if (e.key === "ArrowUp") {
              e.preventDefault();
              setIdx((i) => Math.max(0, i - 1));
            } else if (e.key === "Enter") {
              e.preventDefault();
              if (open && results[idx]) choisir(results[idx]);
            } else if (e.key === "Escape") {
              setOpen(false);
              setQ("");
            }
          }}
          placeholder="Mettre en évidence : nom de la compagnie…"
          className="min-w-0 flex-1 bg-transparent py-1.5 text-xs outline-none"
          style={{ color: "var(--qg-text)" }}
          aria-label="Mettre une bulle en évidence"
        />
        {selected ? (
          <button
            type="button"
            onClick={() => {
              onChange(null);
              setQ("");
              setOpen(false);
            }}
            className="rounded p-0.5 text-white/50 hover:text-rose-400"
            title="Retirer la mise en évidence"
            aria-label="Retirer la mise en évidence"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        ) : null}
      </div>
      {open ? (
        <ul
          className="absolute left-0 right-0 z-30 mt-1 max-h-72 overflow-y-auto rounded-lg border py-1 text-xs shadow-xl"
          style={{
            borderColor: "var(--qg-border)",
            backgroundColor: "var(--qg-card-bg)"
          }}
          role="listbox"
        >
          {results.length === 0 ? (
            <li
              className="px-3 py-1.5"
              style={{ color: "var(--qg-text-muted)" }}
            >
              Aucune bulle ne correspond.
            </li>
          ) : (
            results.map((n, i) => {
              const nat = NATURE_STYLES[nodeNature(n)];
              return (
                <li key={n.id} role="option" aria-selected={i === idx}>
                  <button
                    type="button"
                    onMouseDown={(e) => e.preventDefault()}
                    onMouseEnter={() => setIdx(i)}
                    onClick={() => choisir(n)}
                    className="flex w-full items-center gap-2 px-3 py-1.5 text-left"
                    style={{
                      backgroundColor:
                        i === idx ? "var(--qg-bg-alt, rgba(0,0,0,0.06))" : "transparent",
                      color: "var(--qg-text)"
                    }}
                  >
                    <span
                      aria-hidden
                      className={`inline-block h-2 w-2 shrink-0 rounded-full ${nat.dotCls}`}
                    />
                    <span className="min-w-0 flex-1 truncate">{n.label}</span>
                    <span
                      className="shrink-0 text-[10px]"
                      style={{ color: "var(--qg-text-soft)" }}
                    >
                      {nat.label}
                    </span>
                  </button>
                </li>
              );
            })
          )}
        </ul>
      ) : null}
    </div>
  );
}

// ─── Export PDF ──────────────────────────────────────────────────
//
// Options de feuille (orientation, format, échelle) + aperçu en direct
// du PDF généré (vectoriel, fond blanc). Le contenu est exactement ce
// que le canevas affiche : périmètre, positions, mise en évidence.

function ExportPdfModal({
  bulles,
  fleches,
  versionName,
  scopeLabel,
  highlightLabel,
  onClose
}: {
  bulles: PdfBulle[];
  fleches: PdfFleche[];
  versionName: string;
  scopeLabel: string;
  highlightLabel: string | null;
  onClose: () => void;
}) {
  const [orientation, setOrientation] = useState<PdfOrientation>("paysage");
  const [format, setFormat] = useState<PdfFormat>("lettre");
  const [echelle, setEchelle] = useState<PdfEchelle>("page");
  const [zoom, setZoom] = useState(100);
  const [titre, setTitre] = useState("Organigramme — structure de détention");
  const [sousTitre, setSousTitre] = useState(
    `Version ${versionName} · périmètre ${scopeLabel}`
  );
  const [legendeEvidence, setLegendeEvidence] = useState(
    "Compagnie acquéreuse"
  );
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [building, setBuilding] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const urlRef = useRef<string | null>(null);

  const options = useMemo(
    () => ({
      orientation,
      format,
      echelle,
      zoom,
      titre,
      sousTitre,
      legendeEvidence: highlightLabel ? legendeEvidence || "Mise en évidence" : null
    }),
    [orientation, format, echelle, zoom, titre, sousTitre, legendeEvidence, highlightLabel]
  );

  // Aperçu régénéré à chaque changement d'option (petit délai pour la
  // saisie du titre / du zoom).
  useEffect(() => {
    let annule = false;
    const t = window.setTimeout(async () => {
      setBuilding(true);
      setErr(null);
      try {
        const doc = await construirePdfOrganigramme({
          bulles,
          fleches,
          options,
          bulleW: BUBBLE_W,
          bulleH: BUBBLE_H
        });
        if (annule) return;
        const url = String(doc.output("bloburl"));
        if (urlRef.current) URL.revokeObjectURL(urlRef.current);
        urlRef.current = url;
        setPreviewUrl(url);
      } catch (e) {
        if (!annule) setErr(`Aperçu impossible : ${(e as Error).message}`);
      } finally {
        if (!annule) setBuilding(false);
      }
    }, 250);
    return () => {
      annule = true;
      window.clearTimeout(t);
    };
  }, [bulles, fleches, options]);

  useEffect(
    () => () => {
      if (urlRef.current) URL.revokeObjectURL(urlRef.current);
    },
    []
  );

  async function telecharger() {
    setErr(null);
    try {
      const doc = await construirePdfOrganigramme({
        bulles,
        fleches,
        options,
        bulleW: BUBBLE_W,
        bulleH: BUBBLE_H
      });
      doc.save(nomFichierPdf(versionName, scopeLabel));
    } catch (e) {
      setErr(`Téléchargement impossible : ${(e as Error).message}`);
    }
  }

  const segment = (
    actif: boolean
  ): React.CSSProperties => ({
    backgroundColor: actif ? "var(--qg-accent)" : "var(--qg-card-bg)",
    color: actif ? "var(--qg-accent-ink, #0a0a0b)" : "var(--qg-text-soft)"
  });

  return (
    <div
      className="fixed inset-0 z-[1200] flex items-center justify-center bg-black/60 p-4"
      onClick={onClose}
    >
      <div
        className="flex max-h-[92vh] w-full max-w-5xl flex-col overflow-hidden rounded-2xl border border-[var(--qg-border)] bg-[var(--qg-bg)]"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-[var(--qg-border)] px-5 py-3">
          <h3 className="flex items-center gap-2 text-base font-semibold">
            <FileDown className="h-4 w-4 text-accent-500" />
            Exporter l&apos;organigramme en PDF
          </h3>
          <button type="button" onClick={onClose} className="btn-ghost btn-xs" aria-label="Fermer">
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto p-5 md:flex-row">
          {/* Options */}
          <div className="w-full shrink-0 space-y-4 md:w-72">
            <div>
              <p className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-[var(--qg-text-soft)]">
                Orientation
              </p>
              <div className="inline-flex overflow-hidden rounded-lg border" style={{ borderColor: "var(--qg-border)" }}>
                {(
                  [
                    ["portrait", "Portrait"],
                    ["paysage", "Paysage"]
                  ] as const
                ).map(([val, lbl]) => (
                  <button
                    key={val}
                    type="button"
                    onClick={() => setOrientation(val)}
                    className="px-3 py-1.5 text-xs font-semibold"
                    style={segment(orientation === val)}
                  >
                    {lbl}
                  </button>
                ))}
              </div>
            </div>

            <div>
              <p className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-[var(--qg-text-soft)]">
                Format de feuille
              </p>
              <select
                value={format}
                onChange={(e) => setFormat(e.target.value as PdfFormat)}
                className="input text-xs"
              >
                {(Object.keys(FORMATS_PDF) as PdfFormat[]).map((k) => (
                  <option key={k} value={k}>
                    {FORMATS_PDF[k].label}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <p className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-[var(--qg-text-soft)]">
                Mise à l&apos;échelle
              </p>
              <div className="space-y-1 text-xs">
                {(
                  [
                    ["page", "Ajuster à la page (tout rentre)"],
                    ["largeur", "Ajuster à la largeur"],
                    ["manuelle", "Échelle manuelle"]
                  ] as const
                ).map(([val, lbl]) => (
                  <label key={val} className="flex items-center gap-2">
                    <input
                      type="radio"
                      name="echelle"
                      checked={echelle === val}
                      onChange={() => setEchelle(val)}
                    />
                    {lbl}
                  </label>
                ))}
                {echelle === "manuelle" ? (
                  <div className="mt-1 flex items-center gap-2 pl-5">
                    <input
                      type="range"
                      min={25}
                      max={250}
                      step={5}
                      value={zoom}
                      onChange={(e) => setZoom(Number(e.target.value))}
                      className="flex-1"
                      aria-label="Échelle en pourcentage"
                    />
                    <span className="w-12 text-right font-semibold">{zoom} %</span>
                  </div>
                ) : null}
                <p className="pl-5 text-[10px] text-[var(--qg-text-muted)]">
                  100 % = la taille des bulles à l&apos;écran. Ce qui
                  déborde de la feuille est coupé.
                </p>
              </div>
            </div>

            <div>
              <p className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-[var(--qg-text-soft)]">
                Titre
              </p>
              <input
                value={titre}
                onChange={(e) => setTitre(e.target.value)}
                className="input text-xs"
              />
              <input
                value={sousTitre}
                onChange={(e) => setSousTitre(e.target.value)}
                className="input mt-1 text-xs"
                placeholder="Sous-titre"
              />
            </div>

            {highlightLabel ? (
              <div>
                <p className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-[var(--qg-text-soft)]">
                  Bulle en évidence : {highlightLabel}
                </p>
                <input
                  value={legendeEvidence}
                  onChange={(e) => setLegendeEvidence(e.target.value)}
                  className="input text-xs"
                  placeholder="Libellé dans la légende (ex. Compagnie acquéreuse)"
                  title="Comment la légende du PDF nomme la bulle en évidence"
                />
              </div>
            ) : (
              <p className="text-[10px] text-[var(--qg-text-muted)]">
                Astuce : mets une compagnie en évidence avant d&apos;exporter
                pour la faire ressortir (ex. la compagnie acquéreuse).
              </p>
            )}

            <p className="text-[10px] text-[var(--qg-text-muted)]">
              Le PDF reprend ce qui est affiché : version {versionName},
              périmètre {scopeLabel}, {bulles.length} bulle(s).
            </p>

            {err ? (
              <p className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-600">
                {err}
              </p>
            ) : null}
          </div>

          {/* Aperçu */}
          <div
            className="relative min-h-[320px] flex-1 overflow-hidden rounded-xl border md:min-h-[60vh]"
            style={{ borderColor: "var(--qg-border)", backgroundColor: "#525659" }}
          >
            {previewUrl ? (
              <iframe
                title="Aperçu du PDF"
                src={`${previewUrl}#toolbar=0&navpanes=0&view=Fit`}
                className="h-full w-full"
                style={{ minHeight: 320 }}
              />
            ) : null}
            {building ? (
              <div className="absolute right-2 top-2 inline-flex items-center gap-1 rounded-full bg-black/60 px-2 py-1 text-[10px] text-white">
                <Loader2 className="h-3 w-3 animate-spin" /> Aperçu…
              </div>
            ) : null}
          </div>
        </div>

        <div className="flex items-center justify-end gap-2 border-t border-[var(--qg-border)] px-5 py-3">
          <button type="button" onClick={onClose} className="btn-secondary btn-sm">
            Annuler
          </button>
          <button
            type="button"
            onClick={() => void telecharger()}
            className="btn-accent inline-flex items-center gap-1.5 text-xs"
          >
            <FileDown className="h-3.5 w-3.5" />
            Télécharger le PDF
          </button>
        </div>
      </div>
    </div>
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
// de détention auto-tracées (parent_id + co_owner_node_ids) avec la
// quote-part au milieu. Les liens ne se créent ni ne se suppriment ici :
// ils viennent des fiches (sync).

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
  parentEntId,
  highlightId,
  onHighlight,
  onPatch,
  onSetNature,
  onDelete
}: {
  nodes: OrgNode[];
  parentEntId: number | null;
  highlightId: number | null;
  onHighlight: (id: number | null) => void;
  onPatch: (id: number, patch: Partial<OrgNode>) => Promise<void>;
  onSetNature: (id: number, nature: "person" | "company") => Promise<void>;
  onDelete: (id: number) => Promise<void>;
}) {
  const canvasRef = useRef<HTMLDivElement | null>(null);

  // Bulle sélectionnée → ouvre le panneau latéral.
  const [selectedId, setSelectedId] = useState<number | null>(null);

  // Zoom du canvas — appliqué en transform:scale sur la couche de
  // contenu ; canvasCoords divise par le zoom pour garder un drag
  // précis. Ajustable via les boutons ou Ctrl/Cmd + molette.
  const [zoom, setZoom] = useState(1);
  const zoomFocusRef = useRef<{
    contentX: number;
    contentY: number;
    vpX: number;
    vpY: number;
  } | null>(null);

  // Positions de travail : seed depuis pos_x/pos_y du serveur, sinon
  // rangée du bas. Le drag les met à jour localement ; on PATCH au
  // relâchement.
  const [positions, setPositions] = useState<Map<number, XY>>(new Map());

  const dragRef = useRef<{
    id: number;
    startX: number;
    startY: number;
    origX: number;
    origY: number;
    moved: boolean;
  } | null>(null);

  const byId = useMemo(() => {
    const m = new Map<number, OrgNode>();
    for (const n of nodes) m.set(n.id, n);
    return m;
  }, [nodes]);

  const fallback = useMemo(() => resolvePositions(nodes), [nodes]);

  // (Re)seed : ajoute les nouveaux nœuds, retire les supprimés,
  // conserve les positions déjà connues (drag local).
  useEffect(() => {
    setPositions((prev) => {
      const next = new Map<number, XY>();
      for (const n of nodes) {
        const existing = prev.get(n.id);
        if (existing) next.set(n.id, existing);
        else next.set(n.id, fallback.get(n.id) || { x: GRID, y: GRID });
      }
      return next;
    });
  }, [nodes, fallback]);

  // Bulle mise en évidence → on la centre dans la vue.
  useEffect(() => {
    if (highlightId == null) return;
    const el = canvasRef.current;
    const p = positions.get(highlightId);
    if (!el || !p) return;
    el.scrollTo({
      left: Math.max(0, (p.x + BUBBLE_W / 2) * zoom - el.clientWidth / 2),
      top: Math.max(0, (p.y + BUBBLE_H / 2) * zoom - el.clientHeight / 2),
      behavior: "smooth"
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [highlightId]);

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

  const arrows = useMemo(() => buildArrows(nodes), [nodes]);

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

  function onCanvasMouseMove(e: React.MouseEvent) {
    if (!dragRef.current) return;
    const m = canvasCoords(e);
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
  }

  function onCanvasMouseUp() {
    if (!dragRef.current) return;
    const d = dragRef.current;
    dragRef.current = null;
    if (d.moved) {
      const p = positions.get(d.id);
      if (p) void onPatch(d.id, { pos_x: p.x, pos_y: p.y });
    } else {
      // Clic sans déplacement → sélectionne la bulle (ouvre le panneau).
      setSelectedId(d.id);
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
          backgroundColor: "var(--qg-bg-alt, transparent)"
        }}
      >
        {/* Sizer : réserve la zone scrollable à la taille ZOOMÉE. */}
        <div style={{ width: canvasW * zoom, height: canvasH * zoom }}>
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
                  id="org-arrow-highlight"
                  viewBox="0 0 10 10"
                  refX="9"
                  refY="5"
                  markerWidth="7"
                  markerHeight="7"
                  orient="auto-start-reverse"
                >
                  <path d="M0,0 L10,5 L0,10 z" fill="rgb(16 185 129)" />
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
                // Les flèches qui touchent la bulle en évidence
                // ressortent avec elle.
                const lie =
                  highlightId != null &&
                  (a.fromId === highlightId || a.toId === highlightId);
                const pct = parseOwnership(byId.get(a.toId))[String(a.fromId)];
                return (
                  <g key={a.key}>
                    <line
                      x1={start.x}
                      y1={start.y}
                      x2={end.x}
                      y2={end.y}
                      stroke={lie ? "rgb(16 185 129)" : "var(--qg-text-muted)"}
                      strokeWidth={lie ? 2.5 : 1.75}
                      markerEnd={`url(#org-arrow${lie ? "-highlight" : ""})`}
                    />
                    {pct != null ? (
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
                      >
                        {formatPct(pct)}
                      </text>
                    ) : null}
                  </g>
                );
              })}
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
                  isParentCompany={
                    n.kind === "company" &&
                    parentEntId != null &&
                    n.entreprise_id === parentEntId
                  }
                  selected={selectedId === n.id}
                  highlighted={highlightId === n.id}
                  onMouseDown={(e) => onBubbleMouseDown(e, n.id)}
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
          highlighted={highlightId === selectedNode.id}
          onHighlight={onHighlight}
          onPatch={onPatch}
          onSetNature={onSetNature}
          onDelete={async (id) => {
            await onDelete(id);
            setSelectedId(null);
          }}
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
  isParentCompany,
  selected,
  highlighted,
  onMouseDown
}: {
  node: OrgNode;
  x: number;
  y: number;
  isParentCompany: boolean;
  selected: boolean;
  highlighted: boolean;
  onMouseDown: (e: React.MouseEvent) => void;
}) {
  const [hover, setHover] = useState(false);
  const nature = nodeNature(node);
  const natureStyle = NATURE_STYLES[nature];

  return (
    <div
      onMouseDown={onMouseDown}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      className={`absolute select-none rounded-xl border ${
        highlighted ? HIGHLIGHT.bubbleCls : natureStyle.bubbleCls
      } ${node.absent_des_fiches ? "border-dashed" : ""}`}
      title={
        node.absent_des_fiches
          ? "Absente des fiches : retire-la (panneau) ou inscris l'actionnaire dans une fiche"
          : undefined
      }
      style={{
        left: x,
        top: y,
        width: BUBBLE_W,
        minHeight: BUBBLE_H,
        zIndex: highlighted ? 2 : undefined,
        opacity: node.absent_des_fiches && !highlighted ? 0.75 : 1,
        // Nature « autre » : rendu neutre historique.
        ...(nature === "autre" && !highlighted
          ? {
              borderColor: "var(--qg-border)",
              backgroundColor: "var(--qg-card-bg)"
            }
          : {}),
        boxShadow: highlighted
          ? HIGHLIGHT.shadow
          : selected
            ? "0 0 0 2px var(--qg-accent), 0 6px 18px -4px rgba(0,0,0,0.4)"
            : hover
              ? "0 4px 14px -4px rgba(0,0,0,0.35)"
              : "0 1px 3px rgba(0,0,0,0.18)",
        cursor: "grab",
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
        {node.absent_des_fiches ? (
          <span className="shrink-0 rounded-full border border-dashed border-rose-400/70 px-1.5 py-0 text-[8px] font-bold uppercase text-rose-400">
            Absent des fiches
          </span>
        ) : null}
        {highlighted ? (
          <Sparkles className="ml-auto h-3 w-3 shrink-0 text-emerald-500" />
        ) : null}
      </div>
      <p
        className="mt-1 text-[13px] font-semibold leading-tight"
        style={{ color: "var(--qg-text)" }}
      >
        {node.label}
      </p>
    </div>
  );
}

// Panneau latéral du canvas — s'ouvre au clic sur une bulle.
// Fiche de la bulle, en lecture : nature (corrigeable personne ↔
// compagnie pour un détenteur hors groupe), détenteurs et
// participations avec quotes-parts, fiche Kratos, notes libres,
// mise en évidence. Les liens eux-mêmes se modifient dans les fiches.
function CanvasNodeEditor({
  node,
  allNodes,
  highlighted,
  onHighlight,
  onPatch,
  onSetNature,
  onDelete,
  onSelect,
  onClose
}: {
  node: OrgNode;
  allNodes: OrgNode[];
  highlighted: boolean;
  onHighlight: (id: number | null) => void;
  onPatch: (id: number, patch: Partial<OrgNode>) => Promise<void>;
  onSetNature: (id: number, nature: "person" | "company") => Promise<void>;
  onDelete: (id: number) => Promise<void>;
  onSelect: (id: number) => void;
  onClose: () => void;
}) {
  const nature = nodeNature(node);
  const natureStyle = NATURE_STYLES[nature];
  const [changingNature, setChangingNature] = useState(false);

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

  // Notes libres, sans la ligne « Détention : … » (affichée à part).
  const { detention, notes } = splitDescription(node.description);

  async function changerNature(n: "person" | "company") {
    setChangingNature(true);
    try {
      await onSetNature(node.id, n);
    } finally {
      setChangingNature(false);
    }
  }

  return (
    <div
      className="absolute bottom-0 right-0 top-0 z-10 flex w-80 flex-col gap-3 overflow-y-auto border-l p-3"
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
          Fiche de la bulle
        </span>
        <button
          type="button"
          onClick={onClose}
          className="ml-auto rounded p-1 text-white/40 hover:text-accent-400"
          title="Fermer le panneau"
          aria-label="Fermer le panneau"
        >
          <X className="h-3.5 w-3.5" />
        </button>
      </div>

      <p
        className="text-sm font-semibold leading-tight"
        style={{ color: "var(--qg-text)" }}
      >
        {node.label}
      </p>

      <div className="flex flex-wrap items-center gap-1.5">
        {nature === "inc" && node.entreprise_id ? (
          <Link
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            href={`/entreprises/${node.entreprise_id}` as any}
            className="btn-accent inline-flex w-fit items-center gap-1 text-xs"
          >
            <ExternalLink className="h-3.5 w-3.5" />
            Ouvrir la fiche
          </Link>
        ) : null}
        <button
          type="button"
          onClick={() => onHighlight(highlighted ? null : node.id)}
          className={`inline-flex items-center gap-1 rounded-lg border px-2.5 py-1.5 text-xs font-semibold ${
            highlighted
              ? "border-emerald-500 bg-emerald-500/20 text-emerald-500"
              : "border-emerald-500/50 text-emerald-500 hover:bg-emerald-500/10"
          }`}
          title="Fait ressortir cette bulle en vert sur le canevas et dans le PDF (ex. la compagnie acquéreuse)"
        >
          <Sparkles className="h-3.5 w-3.5" />
          {highlighted ? "Retirer la mise en évidence" : "Mettre en évidence"}
        </button>
      </div>

      {node.absent_des_fiches ? (
        <div className="rounded-lg border border-dashed border-rose-400/60 bg-rose-500/10 p-2 text-[11px]">
          <p className="font-semibold text-rose-400">Absente des fiches</p>
          <p
            className="mt-0.5"
            style={{ color: "var(--qg-text-muted)" }}
          >
            {nature === "inc"
              ? "Cette compagnie est fermée ou n'existe plus dans Entreprises."
              : "Aucune ligne Partenaires & parts ne cite ce nom dans une fiche active. Inscris-le comme actionnaire dans la fiche concernée (puis Synchroniser), ou retire la bulle."}
          </p>
          <button
            type="button"
            onClick={() => void onDelete(node.id)}
            className="mt-1.5 inline-flex items-center gap-1 rounded-lg border border-rose-400/60 px-2.5 py-1 text-[11px] font-semibold text-rose-400 hover:bg-rose-500/15"
            title="Retire la bulle de l'organigramme — les compagnies qu'elle détenait restent"
          >
            <Trash2 className="h-3.5 w-3.5" />
            Retirer la bulle
          </button>
        </div>
      ) : null}

      {nature === "externe" || nature === "person" ? (
        <div>
          <p
            className="text-[9px] font-semibold uppercase tracking-wide"
            style={{ color: "var(--qg-text-soft)" }}
          >
            Nature
          </p>
          <div
            className="mt-0.5 inline-flex overflow-hidden rounded-lg border"
            style={{ borderColor: "var(--qg-border)" }}
          >
            {(
              [
                ["person", "Personne"],
                ["company", "Compagnie"]
              ] as const
            ).map(([val, lbl]) => {
              const actif =
                (val === "person" && nature === "person") ||
                (val === "company" && nature === "externe");
              return (
                <button
                  key={val}
                  type="button"
                  disabled={changingNature || actif}
                  onClick={() => void changerNature(val)}
                  className="px-2.5 py-1 text-[11px] font-semibold disabled:cursor-default"
                  style={{
                    backgroundColor: actif
                      ? "var(--qg-accent)"
                      : "var(--qg-card-bg)",
                    color: actif
                      ? "var(--qg-accent-ink, #0a0a0b)"
                      : "var(--qg-text-soft)"
                  }}
                >
                  {lbl}
                </button>
              );
            })}
          </div>
          <p
            className="mt-1 text-[10px]"
            style={{ color: "var(--qg-text-muted)" }}
          >
            Déduite des lignes Partenaires &amp; parts (case « personne
            morale »). Corriger ici met aussi la fiche à jour.
          </p>
        </div>
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
            Aucun détenteur connu dans les fiches.
          </p>
        ) : (
          <ul className="mt-0.5 space-y-0.5 text-[11px]">
            {owners.map(({ owner, pct }) => (
              <li key={owner.id}>
                <button
                  type="button"
                  onClick={() => onSelect(owner.id)}
                  className="flex w-full items-center justify-between gap-2 rounded px-1.5 py-0.5 text-left hover:bg-accent-500/10"
                  style={{
                    backgroundColor: "var(--qg-bg-alt, transparent)"
                  }}
                  title={`Voir ${owner.label}`}
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
                </button>
              </li>
            ))}
          </ul>
        )}
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
            title="Ligne maintenue par « Synchroniser » — se met à jour toute seule"
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

      <p
        className="mt-auto text-[10px]"
        style={{ color: "var(--qg-text-muted)" }}
      >
        Les bulles et les liens viennent des fiches d&apos;entreprises :
        pour ajouter un actionnaire, changer un pourcentage ou retirer
        un lien, modifie la fiche (Partenaires &amp; parts) puis clique
        « Synchroniser ».
      </p>
    </div>
  );
}
