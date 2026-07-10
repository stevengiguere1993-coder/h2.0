"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useParams } from "next/navigation";
import {
  ArrowLeft,
  Briefcase,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  Copy,
  Download,
  Eye,
  EyeOff,
  FileSignature,
  Gift,
  GripVertical,
  Loader2,
  Plus,
  Repeat,
  Send,
  Trash2,
  X,
  XCircle
} from "lucide-react";

import { AppTopbar } from "@/components/app-topbar";
import { EntityDriveSection } from "@/components/drive/EntityDriveSection";
import {
  SoumissionClientView,
  type SoumissionClientViewData
} from "@/components/devlog/SoumissionClientView";
import { useDevlogLayout } from "../../layout";
import { authedFetch } from "@/lib/auth";
import { useConfirm } from "@/components/confirm-dialog";
import { Link } from "@/i18n/navigation";

// Page détail soumission.
//
// Deux rendus possibles selon le flag ``is_devis_dev`` :
//
//   * **Nouveau format (devis_dev)** — refonte mai 2026. Deux sections
//     (Frais mensuels récurrents + Investissement initial) avec calcul
//     circulaire (closing absorbe la marge sur la base), toggle vue
//     propriétaire / vue client.
//
//   * **Legacy** — soumissions créées avant la refonte. Sections par
//     pôle + items + markup. Lecture seule, conservé pour
//     l'historique.

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
  // Devis_dev
  is_devis_dev: boolean;
  marge_recurrente_pct: number | null;
  marge_initiale_pct: number | null;
  commission_closer_pct: number | null;
  taux_dev_horaire: number | null;
  taux_manager_horaire: number | null;
  heures_manager: number | null;
  client_recurring_description: string | null;
  // Envoi PDF + signature publique (vague 1, mai 2026)
  signature_token: string | null;
  sent_at: string | null;
  // Accusé de lecture (le client a-t-il ouvert le lien ?)
  opened_at: string | null;
  last_opened_at: string | null;
  open_count: number;
  signed_at: string | null;
  signed_name: string | null;
  signed_ip: string | null;
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
  // Module parent (refonte 2026-06). NULL pour les items legacy /
  // récurrents / non rattachés à un module.
  module_id: number | null;
  position: number;
  description: string;
  unit: string | null;
  quantity: number;
  cost_per_unit: number;
  unit_price: number;
  total: number;
  notes: string | null;
  // Devis_dev
  item_kind:
    | "recurring_cost"
    | "feature"
    | "manager_task"
    | "fixed_cost"
    | string;
  heures: number | null;
};

// Module de l'investissement initial (refonte 2026-06, Phase 3).
type ModuleRow = {
  id: number;
  soumission_id: number;
  section_id: number | null;
  name: string;
  position: number;
  description: string | null;
  notes: string | null;
  selected: boolean;
  free_when_module_id: number | null;
  created_at: string;
  updated_at: string;
};

type Totals = { initial: number; monthly: number };

type DevisPreview = {
  is_invalid: boolean;
  recurring: {
    total_owner_cost: number;
    total_client_amount: number;
    marge_amount: number;
    marge_pct: number;
    items_breakdown: Array<{
      id: number | null;
      description: string;
      cost_per_unit: number;
    }>;
    // Taxes (Québec) appliquées sur total_client_amount
    tps_amount: number;
    tvq_amount: number;
    tps_pct: number;
    tvq_pct: number;
    total_client_amount_taxe: number;
  };
  initial: {
    couts_dev: number;
    cout_manager: number;
    frais_fixes_total: number;
    base: number;
    closing: number;
    total_avant_marge: number;
    total_apres_marge: number;
    total_final: number;
    marge_amount: number;
    marge_pct: number;
    closer_pct: number;
    taux_dev_horaire: number;
    taux_manager_horaire: number;
    heures_manager: number;
    features_client: Array<{
      id: number | null;
      description: string;
      heures: number;
      prix_client: number;
      module_id?: number | null;
      offert?: boolean;
    }>;
    frais_fixes_client: Array<{
      id: number | null;
      description: string;
      cost_per_unit: number;
      prix_client: number;
    }>;
    // Tâches du chargé de projet (vue interne uniquement).
    manager_tasks?: Array<{
      id: number | null;
      description: string;
      heures: number;
      module_id?: number | null;
      offert?: boolean;
      cout_interne?: number;
    }>;
    // Détail par module (refonte 2026-06). Vide en mode legacy.
    modules?: Array<{
      id: number;
      name: string | null;
      selected: boolean;
      offert: boolean;
      free_when_module_id: number | null;
      total_heures_dev: number;
      total_heures_manager: number;
      prix_client: number;
      features: Array<{
        id: number | null;
        description: string;
        heures: number;
      }>;
      manager_tasks: Array<{
        id: number | null;
        description: string;
        heures: number;
      }>;
    }>;
    // Taxes (Québec) appliquées sur total_final (qui inclut déjà le closer)
    tps_amount: number;
    tvq_amount: number;
    tps_pct: number;
    tvq_pct: number;
    total_final_taxe: number;
  };
};

type ClientInfo = {
  id: number;
  name: string;
  company: string | null;
  email: string | null;
  phone: string | null;
  address: string | null;
};

const STATUS_LABEL: Record<string, string> = {
  brouillon: "Brouillon",
  envoyee: "Envoyée",
  acceptee: "Acceptée",
  refusee: "Refusée",
  expiree: "Expirée"
};

const STATUS_CLS: Record<string, string> = {
  brouillon: "badge-neutral",
  envoyee: "badge-blue",
  acceptee: "badge-emerald",
  refusee: "badge-rose",
  expiree: "badge-amber"
};

function fmtAmount(n: number | null): string {
  if (n == null) return "—";
  return n.toLocaleString("fr-CA", {
    style: "currency",
    currency: "CAD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2
  });
}

// Format « 1 600,00 $ » pour les colonnes de totaux par ligne (sans
// le mot « CAD », plus compact, fr-CA strict).
function fmtMoneyShort(n: number): string {
  return n.toLocaleString("fr-CA", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2
  }) + " $";
}

// ──────────────────────────────────────────────────────────────────
// Inputs contrôlés à state local indépendant du parent.
//
// Le bug : tous les inputs du formulaire devis_dev étaient
// contrôlés directement par l'objet venant du fetch (`value={it.x}`).
// Chaque keystroke déclenchait `onPatchItem` → mutation locale +
// PATCH API + reload des items. Pendant la frappe rapide, la
// promesse du PATCH précédent revenait avec l'ancienne valeur et
// écrasait l'état local (race), ce qui inversait/dupliquait des
// lettres ("facturation" devenait "factuartion").
//
// Pattern inspiré de FieldText/FieldNumber dans prospection : on
// garde un state local `v`, on ne re-sync avec la prop `value` que
// quand le champ n'est PAS focusé (i.e. l'utilisateur ne tape
// pas), et on commit au blur uniquement si la valeur a changé.
// ──────────────────────────────────────────────────────────────────

function DescInput({
  value,
  onCommit,
  className,
  placeholder
}: {
  value: string;
  onCommit: (v: string) => void;
  className?: string;
  placeholder?: string;
}) {
  const [focused, setFocused] = useState(false);
  const [v, setV] = useState(value ?? "");
  useEffect(() => {
    if (!focused) setV(value ?? "");
  }, [value, focused]);
  return (
    <input
      type="text"
      value={v}
      placeholder={placeholder}
      onFocus={() => setFocused(true)}
      onChange={(e) => setV(e.target.value)}
      onBlur={() => {
        setFocused(false);
        if ((value ?? "") !== v) onCommit(v);
      }}
      className={className}
    />
  );
}

function MoneyInput({
  value,
  onCommit,
  className,
  step = "1",
  min = "0"
}: {
  value: number;
  onCommit: (n: number) => void;
  className?: string;
  step?: string;
  min?: string;
}) {
  const [focused, setFocused] = useState(false);
  const [v, setV] = useState(value != null ? String(value) : "");
  useEffect(() => {
    if (!focused) setV(value != null ? String(value) : "");
  }, [value, focused]);
  // `inline-block` sur le wrap : il prend la largeur naturelle de
  // l'input (w-XX) au lieu de s'etirer dans la cellule. Le suffix
  // `$` absolu se positionne donc bien a droite DE l'input, pas
  // de la cellule entiere. (fix regression PR #481)
  return (
    <div className="relative inline-block">
      <input
        type="number"
        step={step}
        min={min}
        value={v}
        onFocus={() => setFocused(true)}
        onChange={(e) => setV(e.target.value)}
        onBlur={() => {
          setFocused(false);
          const n = Number(v);
          if (Number.isFinite(n) && n !== value) onCommit(n);
        }}
        className={`${className ?? ""} pr-6`}
      />
      <span className="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2 text-[10px] text-white/40">
        $
      </span>
    </div>
  );
}

function HoursInput({
  value,
  onCommit,
  className,
  step = "0.5",
  min = "0"
}: {
  value: number;
  onCommit: (n: number) => void;
  className?: string;
  step?: string;
  min?: string;
}) {
  const [focused, setFocused] = useState(false);
  const [v, setV] = useState(value != null ? String(value) : "");
  useEffect(() => {
    if (!focused) setV(value != null ? String(value) : "");
  }, [value, focused]);
  // Cf. MoneyInput : `inline-block` pour que le suffix `h` colle
  // a l'input et que celui-ci ne s'etire pas dans son conteneur.
  return (
    <div className="relative inline-block">
      <input
        type="number"
        step={step}
        min={min}
        value={v}
        onFocus={() => setFocused(true)}
        onChange={(e) => setV(e.target.value)}
        onBlur={() => {
          setFocused(false);
          const n = Number(v);
          if (Number.isFinite(n) && n !== value) onCommit(n);
        }}
        className={`${className ?? ""} pr-6`}
      />
      <span className="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2 text-[10px] text-white/40">
        h
      </span>
    </div>
  );
}

function PctInput({
  value,
  onCommit,
  className,
  step = "1",
  min = "0",
  max = "500"
}: {
  value: number;
  onCommit: (n: number) => void;
  className?: string;
  step?: string;
  min?: string;
  max?: string;
}) {
  const [focused, setFocused] = useState(false);
  const [v, setV] = useState(value != null ? String(value) : "");
  useEffect(() => {
    if (!focused) setV(value != null ? String(value) : "");
  }, [value, focused]);
  return (
    <input
      type="number"
      step={step}
      min={min}
      max={max}
      value={v}
      onFocus={() => setFocused(true)}
      onChange={(e) => setV(e.target.value)}
      onBlur={() => {
        setFocused(false);
        const n = Number(v);
        if (Number.isFinite(n) && n !== value) onCommit(n);
      }}
      className={className}
    />
  );
}

// ──────────────────────────────────────────────────────────────────
// Glisser-déposer (drag & drop) INTRA-liste — réordonnancement.
//
// On réutilise le drag & drop HTML5 natif (même approche que le
// Pipeline Prospection — `draggable` + `onDragStart/onDragOver/onDrop`),
// le projet n'embarque pas de lib DnD type @dnd-kit. Chaque ligne reçoit
// une poignée `GripVertical` ; un liseré bleu discret indique où l'item
// va se déposer. Au drop, on calcule le nouvel ordre des ids et on le
// remonte via `onReorder` (réordonne localement + persiste côté serveur).
//
// `useDnd` est générique : il gère l'état de drag d'UNE liste (id en
// cours, index survolé) et fabrique les props à étaler sur chaque
// ligne. `ids` est l'ordre courant de la liste rendue.
// ──────────────────────────────────────────────────────────────────
function useDnd(ids: number[], onReorder: (orderedIds: number[]) => void) {
  const [dragId, setDragId] = useState<number | null>(null);
  // Index AVANT lequel l'item déposé s'insèrera (0..ids.length).
  const [overIndex, setOverIndex] = useState<number | null>(null);

  function reset() {
    setDragId(null);
    setOverIndex(null);
  }

  function commit(targetIndex: number) {
    if (dragId == null) return;
    const from = ids.indexOf(dragId);
    if (from < 0) return;
    const next = ids.filter((x) => x !== dragId);
    // `targetIndex` est exprimé dans la liste D'ORIGINE : on corrige
    // d'un cran si l'item part d'AVANT la cible (l'index glisse).
    let insertAt = targetIndex;
    if (from < targetIndex) insertAt -= 1;
    insertAt = Math.max(0, Math.min(insertAt, next.length));
    next.splice(insertAt, 0, dragId);
    reset();
    const changed = next.some((x, i) => x !== ids[i]);
    if (changed) onReorder(next);
  }

  // Props pour la poignée (icône GripVertical) — c'est ELLE qui rend la
  // ligne draggable, pour ne pas gêner la sélection/édition des inputs.
  function handleProps(id: number) {
    return {
      draggable: true,
      onDragStart: (ev: React.DragEvent) => {
        setDragId(id);
        try {
          ev.dataTransfer.effectAllowed = "move";
          ev.dataTransfer.setData("text/plain", String(id));
        } catch {
          /* ignore (jsdom) */
        }
      },
      onDragEnd: reset
    };
  }

  // Props pour chaque ligne réordonnable (cible de drop). `index` est la
  // position de la ligne dans la liste rendue.
  function rowProps(index: number) {
    return {
      onDragOver: (ev: React.DragEvent) => {
        // On ne réagit QUE si c'est cette liste qui est en cours de
        // drag (chaque liste a son propre hook). Sinon on laisse passer
        // (ex. un drag de fonctionnalité ne doit pas activer le drop du
        // module parent).
        if (dragId == null) return;
        ev.preventDefault();
        ev.stopPropagation();
        ev.dataTransfer.dropEffect = "move";
        // Moitié haute → insérer avant cette ligne ; moitié basse →
        // après (index + 1).
        const rect = (
          ev.currentTarget as HTMLElement
        ).getBoundingClientRect();
        const after = ev.clientY - rect.top > rect.height / 2;
        const next = after ? index + 1 : index;
        if (overIndex !== next) setOverIndex(next);
      },
      onDrop: (ev: React.DragEvent) => {
        if (dragId == null) return;
        ev.preventDefault();
        ev.stopPropagation();
        commit(overIndex ?? index);
      }
    };
  }

  return {
    dragId,
    overIndex,
    isDragging: dragId != null,
    handleProps,
    rowProps,
    reset
  };
}

// Poignée de glissement. `text-slate-400` est franchement visible (gris
// moyen) aussi bien sur les blocs sombres de l'éditeur que sur un fond
// clair — l'ancien `text-white/25` était quasi invisible (blanc sur fond
// clair / blanc à 25 % sur fond sombre). On éclaircit au survol pour
// signaler l'interactivité.
function DragHandle(
  props: React.HTMLAttributes<HTMLSpanElement> & {
    draggable?: boolean;
  }
) {
  return (
    <span
      {...props}
      role="button"
      aria-label="Glisser pour réordonner"
      title="Glisser pour réordonner"
      className="inline-flex cursor-grab touch-none text-slate-400 hover:text-slate-200 active:cursor-grabbing"
    >
      <GripVertical className="h-3.5 w-3.5" />
    </span>
  );
}

// Classe du liseré de drop pour une ligne de tableau réordonnable.
// `overIndex` = index AVANT lequel l'item se déposera (cf. useDnd). On
// matérialise le liseré bleu en bordure haute de la ligne ciblée, et en
// bordure basse de la dernière ligne quand on dépose tout en bas.
function dropRowClass(
  index: number,
  count: number,
  overIndex: number | null,
  isDragging: boolean
): string {
  if (!isDragging || overIndex == null) return "";
  if (overIndex === index) {
    return "shadow-[inset_0_2px_0_0_rgb(96,165,250)]";
  }
  if (index === count - 1 && overIndex >= count) {
    return "shadow-[inset_0_-2px_0_0_rgb(96,165,250)]";
  }
  return "";
}

export default function SoumissionDetailPage() {
  const params = useParams<{ id: string }>();
  const id = Number(params?.id);
  const { onOpenSidebar } = useDevlogLayout();
  const confirm = useConfirm();

  const [s, setS] = useState<Soumission | null>(null);
  const [sections, setSections] = useState<Section[]>([]);
  const [items, setItems] = useState<Item[]>([]);
  // Modules de l'investissement initial (refonte 2026-06, Phase 3).
  const [modules, setModules] = useState<ModuleRow[]>([]);
  const [totals, setTotals] = useState<Totals>({ initial: 0, monthly: 0 });
  const [preview, setPreview] = useState<DevisPreview | null>(null);
  const [client, setClient] = useState<ClientInfo | null>(null);
  // Nom du prospect (lead) rattaché, quand la soumission n'a pas encore
  // de client formel. Sert à afficher un message neutre « Destinataire :
  // … » plutôt qu'une alerte « aucun client lié » trompeuse.
  const [leadName, setLeadName] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  // adminView pour legacy, ownerView pour devis_dev (sémantique inverse,
  // mais l'UX est la même).
  const [adminView, setAdminView] = useState(true);
  // Sélection de modules courante de l'aperçu client (remontée depuis
  // AdminClientPreview) — pour que le PDF téléchargé reflète ce qui est
  // coché. ``null`` => aperçu jamais ouvert : on garde l'état persisté.
  const [pdfSelection, setPdfSelection] = useState<number[] | null>(null);

  const isDevisDev = s?.is_devis_dev === true;

  const loadAll = useCallback(async () => {
    try {
      const [sr, secR, itR, tR] = await Promise.all([
        authedFetch(`/api/v1/devlog/soumissions/${id}`),
        authedFetch(`/api/v1/devlog/soumissions/${id}/sections`),
        authedFetch(`/api/v1/devlog/soumissions/${id}/items`),
        authedFetch(`/api/v1/devlog/soumissions/${id}/totals`)
      ]);
      if (!sr.ok) throw new Error("Soumission introuvable");
      const sData = (await sr.json()) as Soumission;
      setS(sData);
      if (secR.ok) setSections((await secR.json()) as Section[]);
      if (itR.ok) setItems((await itR.json()) as Item[]);
      if (tR.ok) setTotals((await tR.json()) as Totals);
      if (sData.is_devis_dev) {
        const pr = await authedFetch(
          `/api/v1/devlog/soumissions/${id}/devis-preview`
        );
        if (pr.ok) setPreview((await pr.json()) as DevisPreview);
        // Modules de l'investissement initial (Phase 3). Absents pour
        // les soumissions sans module (rétrocompat : liste vide).
        const mr = await authedFetch(
          `/api/v1/devlog/soumissions/${id}/modules`
        );
        if (mr.ok) setModules((await mr.json()) as ModuleRow[]);
      }
      // Charge l'info client (encadré en haut de page) si la soumission
      // est liée à un client.
      if (sData.client_id) {
        try {
          const cr = await authedFetch(
            `/api/v1/devlog/clients/${sData.client_id}`
          );
          if (cr.ok) setClient((await cr.json()) as ClientInfo);
          else setClient(null);
        } catch {
          setClient(null);
        }
      } else {
        setClient(null);
      }
      // Pas de client formel mais un prospect rattaché : on récupère son
      // nom pour l'afficher comme destinataire (le client sera créé à
      // l'envoi). Best-effort : si l'appel échoue, on retombe sur un
      // message générique.
      if (!sData.client_id && sData.lead_id) {
        try {
          const lr = await authedFetch(
            `/api/v1/devlog/leads/${sData.lead_id}`
          );
          if (lr.ok) {
            const lead = (await lr.json()) as { name?: string | null };
            setLeadName(lead.name ?? null);
          } else {
            setLeadName(null);
          }
        } catch {
          setLeadName(null);
        }
      } else {
        setLeadName(null);
      }
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

  // Debounced refresh du preview pour les écrans devis_dev. Reload
  // automatique à chaque mutation d'items / champ soumission.
  const previewTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const refreshPreview = useCallback(() => {
    if (!s?.is_devis_dev) return;
    if (previewTimer.current) clearTimeout(previewTimer.current);
    previewTimer.current = setTimeout(async () => {
      try {
        const r = await authedFetch(
          `/api/v1/devlog/soumissions/${id}/devis-preview`
        );
        if (r.ok) setPreview((await r.json()) as DevisPreview);
      } catch {
        /* ignore */
      }
    }, 250);
  }, [id, s?.is_devis_dev]);

  // --- Mutations communes ---------------------------------------------

  async function patchSoumission(patch: Partial<Soumission>) {
    setS((cur) => (cur ? { ...cur, ...patch } : cur));
    try {
      const r = await authedFetch(`/api/v1/devlog/soumissions/${id}`, {
        method: "PATCH",
        body: JSON.stringify(patch)
      });
      if (!r.ok) throw new Error();
      refreshPreview();
    } catch {
      setError("Mise à jour soumission impossible");
      await loadAll();
    }
  }

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

  // Variantes devis_dev — pas de section, item typé par item_kind.
  async function addDevisItem(
    kind: "recurring_cost" | "feature" | "fixed_cost" | "manager_task"
  ) {
    try {
      const payload: Record<string, unknown> = {
        soumission_id: id,
        description:
          kind === "recurring_cost"
            ? "Nouveau coût mensuel"
            : kind === "feature"
              ? "Nouvelle fonctionnalité"
              : kind === "manager_task"
                ? "Nouvelle tâche du chargé de projet"
                : "Nouveau frais fixe",
        item_kind: kind
        // Pas de module_id : les tâches du chargé de projet sont
        // centralisées (globales), rattachées à la soumission.
      };
      if (kind === "feature" || kind === "manager_task") {
        payload.heures = 0;
        payload.unit = "h";
      } else {
        payload.cost_per_unit = 0;
        payload.unit = kind === "recurring_cost" ? "mois" : "forfait";
      }
      const r = await authedFetch("/api/v1/devlog/soumission-items", {
        method: "POST",
        body: JSON.stringify(payload)
      });
      if (!r.ok) throw new Error();
      await loadAll();
    } catch {
      setError("Ajout ligne impossible");
    }
  }

  // --- Modules (investissement initial, Phase 3) ----------------------
  // Recharge la liste des modules (légère, sans reload global) — gardée
  // pour rester réactif après une mutation de module/item.
  const refreshModules = useCallback(async () => {
    try {
      const mr = await authedFetch(
        `/api/v1/devlog/soumissions/${id}/modules`
      );
      if (mr.ok) setModules((await mr.json()) as ModuleRow[]);
    } catch {
      /* ignore */
    }
  }, [id]);

  // La section « investissement initial » à laquelle rattacher les
  // nouveaux modules (la 1re section initial si elle existe).
  const initialSectionId = useMemo(() => {
    const sec = sections.find((x) => x.billing_kind === "initial");
    return sec ? sec.id : null;
  }, [sections]);

  async function addModule() {
    const name = prompt("Nom du module (ex. Authentification, Paiements) ?");
    if (!name?.trim()) return;
    try {
      const r = await authedFetch("/api/v1/devlog/soumission-modules", {
        method: "POST",
        body: JSON.stringify({
          soumission_id: id,
          section_id: initialSectionId,
          name: name.trim()
        })
      });
      if (!r.ok) throw new Error();
      // Le backend pré-remplit le nouveau module avec les « fonctionnalités
      // par défaut » (default_features_json) comme de vrais items feature.
      // On recharge TOUT (loadAll) — et pas seulement la liste des modules —
      // pour que ces items pré-remplis apparaissent immédiatement.
      await loadAll();
      refreshPreview();
    } catch {
      setError("Création du module impossible");
    }
  }

  async function patchModule(moduleId: number, patch: Partial<ModuleRow>) {
    setModules((xs) =>
      xs.map((x) => (x.id === moduleId ? { ...x, ...patch } : x))
    );
    refreshPreview();
    try {
      const r = await authedFetch(
        `/api/v1/devlog/soumission-modules/${moduleId}`,
        { method: "PATCH", body: JSON.stringify(patch) }
      );
      if (!r.ok) throw new Error();
      await refreshModules();
      refreshPreview();
    } catch {
      setError("Mise à jour du module impossible");
      await refreshModules();
    }
  }

  async function deleteModule(moduleId: number) {
    const ok = await confirm({
      title: "Supprimer ce module ?",
      description:
        "Les fonctionnalités et tâches du module seront détachées (pas supprimées) et repasseront en liste directe.",
      confirmLabel: "Supprimer",
      destructive: true
    });
    if (!ok) return;
    try {
      await authedFetch(
        `/api/v1/devlog/soumission-modules/${moduleId}`,
        { method: "DELETE" }
      );
      await loadAll();
    } catch {
      setError("Suppression du module impossible");
    }
  }

  async function moveModule(moduleId: number, dir: -1 | 1) {
    const ordered = [...modules].sort((a, b) => a.position - b.position);
    const idx = ordered.findIndex((m) => m.id === moduleId);
    const swap = idx + dir;
    if (idx < 0 || swap < 0 || swap >= ordered.length) return;
    [ordered[idx], ordered[swap]] = [ordered[swap], ordered[idx]];
    const moduleIds = ordered.map((m) => m.id);
    setModules(ordered.map((m, i) => ({ ...m, position: i })));
    try {
      const r = await authedFetch(
        `/api/v1/devlog/soumissions/${id}/modules/reorder`,
        { method: "POST", body: JSON.stringify({ module_ids: moduleIds }) }
      );
      if (!r.ok) throw new Error();
      await refreshModules();
    } catch {
      setError("Réordonnancement impossible");
      await refreshModules();
    }
  }

  // Crée une fonctionnalité (feature) DANS un module donné. Un module ne
  // porte QUE des fonctionnalités (les tâches du chargé de projet sont
  // centralisées dans le bloc « Gestionnaire de projet », hors module).
  async function addModuleItem(moduleId: number, kind: "feature") {
    try {
      const payload: Record<string, unknown> = {
        soumission_id: id,
        module_id: moduleId,
        item_kind: kind,
        description: "Nouvelle fonctionnalité",
        heures: 0,
        unit: "h"
      };
      const r = await authedFetch("/api/v1/devlog/soumission-items", {
        method: "POST",
        body: JSON.stringify(payload)
      });
      if (!r.ok) throw new Error();
      await loadAll();
    } catch {
      setError("Ajout impossible");
    }
  }

  async function patchItem(itemId: number, patch: Partial<Item>) {
    setItems((xs) =>
      xs.map((x) => (x.id === itemId ? { ...x, ...patch } : x))
    );
    refreshPreview();
    try {
      const r = await authedFetch(
        `/api/v1/devlog/soumission-items/${itemId}`,
        { method: "PATCH", body: JSON.stringify(patch) }
      );
      if (!r.ok) throw new Error();
      // Pour devis_dev, on rafraîchit le preview (totaux finaux)
      refreshPreview();
      // Aussi rafraîchir items locaux pour totaux dérivés
      const r2 = await authedFetch(
        `/api/v1/devlog/soumissions/${id}/items`
      );
      if (r2.ok) setItems((await r2.json()) as Item[]);
    } catch {
      setError("Mise à jour ligne impossible");
      await loadAll();
    }
  }

  async function deleteItem(itemId: number) {
    setItems((xs) => xs.filter((x) => x.id !== itemId));
    refreshPreview();
    try {
      await authedFetch(`/api/v1/devlog/soumission-items/${itemId}`, {
        method: "DELETE"
      });
      await loadAll();
    } catch {
      void loadAll();
    }
  }

  // Réordonnancement d'une liste d'items (drag & drop). `orderedIds` est
  // l'ordre voulu pour CETTE sous-liste (module / récurrents / features /
  // fixes / tâches manager).
  //
  // ⚠️ `position` est GLOBAL à la soumission, mais `orderedIds` ne décrit
  // qu'UNE sous-liste. Si l'on écrivait naïvement `position = index` (0..N)
  // sur ces seuls items, on collisionnerait avec les positions des autres
  // sous-listes : au re-tri global `(position, id)` l'ordre se mélangerait
  // et le drag & drop « reviendrait à sa place ». On reproduit donc EXACTEMENT
  // la logique du backend (`reorder_soumission_items`) : on réinjecte la
  // sous-liste réordonnée aux MÊMES emplacements (slots) qu'elle occupait
  // dans la liste globale, puis on renumérote TOUS les items 0..N.
  //
  // Comme l'ordre optimiste devient ALORS identique à celui que le serveur
  // persiste, on NE re-fetch PAS la liste après succès (évite la course
  // « persistance serveur vs rechargement » qui réécrasait l'ordre). On ne
  // recharge que sur ERREUR, pour retomber sur l'état réel du serveur.
  async function reorderItems(orderedIds: number[]) {
    const movedSet = new Set(orderedIds);
    setItems((xs) => {
      // Ordre global courant, déterministe (même clé de tri que le backend).
      const current = [...xs].sort(
        (a, b) => a.position - b.position || a.id - b.id
      );
      const byId = new Map(current.map((it) => [it.id, it]));
      // Sous-liste réordonnée, restreinte aux items réellement présents.
      const moved = orderedIds
        .map((iid) => byId.get(iid))
        .filter((it): it is Item => it != null);
      const movedIter = moved[Symbol.iterator]();
      // On remplace la sous-séquence déplacée aux slots qu'elle occupait,
      // les autres items ne bougent pas, puis on renumérote 0..N.
      const next = current.map((it) =>
        movedSet.has(it.id) ? movedIter.next().value ?? it : it
      );
      return next.map((it, idx) => ({ ...it, position: idx }));
    });
    refreshPreview();
    try {
      const r = await authedFetch(
        `/api/v1/devlog/soumissions/${id}/items/reorder`,
        { method: "POST", body: JSON.stringify({ item_ids: orderedIds }) }
      );
      if (!r.ok) throw new Error();
      // Succès : la persistance serveur correspond déjà à l'ordre optimiste.
      // On NE recharge PAS la liste (sinon course avec la persistance qui
      // réécraserait l'ordre par l'ancien). On garde l'état local réordonné.
      refreshPreview();
    } catch {
      setError("Réordonnancement impossible");
      await loadAll();
    }
  }

  // Réordonnancement des modules par drag & drop (l'endpoint reorder est
  // déjà utilisé par les flèches ↑/↓ via `moveModule`).
  async function reorderModules(orderedIds: number[]) {
    const rank = new Map<number, number>();
    orderedIds.forEach((mid, i) => rank.set(mid, i));
    setModules((xs) =>
      [...xs]
        .map((m) => (rank.has(m.id) ? { ...m, position: rank.get(m.id)! } : m))
        .sort((a, b) => a.position - b.position || a.id - b.id)
    );
    try {
      const r = await authedFetch(
        `/api/v1/devlog/soumissions/${id}/modules/reorder`,
        { method: "POST", body: JSON.stringify({ module_ids: orderedIds }) }
      );
      if (!r.ok) throw new Error();
      await refreshModules();
    } catch {
      setError("Réordonnancement impossible");
      await refreshModules();
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

  const [sending, setSending] = useState(false);
  const [copyOk, setCopyOk] = useState(false);
  const [generatingContract, setGeneratingContract] = useState(false);

  // Auto-remplissage : cree un brouillon de contrat a partir de la
  // soumission acceptee (parties + objet + conditions financieres +
  // clauses standards), puis redirige vers la page contrats ou Phil
  // peut ajuster le body Markdown avant d'envoyer.
  async function generateContract() {
    if (generatingContract) return;
    const ok = await confirm({
      title: "Générer le contrat à partir de cette soumission ?",
      description:
        "Un nouveau contrat brouillon sera créé avec les parties, l'objet, les conditions financières et les clauses standards pré-remplies. Tu pourras l'éditer avant de l'envoyer.",
      confirmLabel: "Générer"
    });
    if (!ok) return;
    setGeneratingContract(true);
    try {
      const r = await authedFetch(
        `/api/v1/devlog/contracts/from-soumission/${id}`,
        { method: "POST" }
      );
      if (!r.ok) {
        const t = await r.text();
        throw new Error(t.slice(0, 200) || `HTTP ${r.status}`);
      }
      // Redirige vers la page contrats (le drawer du nouveau contrat
      // sera ouvrable en cliquant la carte dans le kanban).
      window.location.href = "/dev-logiciel/contrats";
    } catch (e) {
      setError(
        (e as Error).message || "Génération du contrat impossible."
      );
    } finally {
      setGeneratingContract(false);
    }
  }

  async function sendToClient() {
    if (sending) return;
    const ok = await confirm({
      title: "Envoyer la soumission au client ?",
      description:
        "Un courriel sera transmis au client avec le PDF en pièce " +
        "jointe et un lien public pour signer. Continuer ?",
      confirmLabel: "Envoyer"
    });
    if (!ok) return;
    setSending(true);
    try {
      const r = await authedFetch(
        `/api/v1/devlog/soumissions/${id}/send`,
        { method: "POST" }
      );
      if (!r.ok) {
        const t = await r.text();
        throw new Error(t.slice(0, 200) || `HTTP ${r.status}`);
      }
      await loadAll();
    } catch (e) {
      setError(
        (e as Error).message || "Envoi de la soumission impossible."
      );
    } finally {
      setSending(false);
    }
  }

  function publicSignUrl(token: string): string {
    const base =
      typeof window !== "undefined" ? window.location.origin : "";
    return `${base}/devlog/sign-soumission/${token}`;
  }

  async function copyPublicLink(token: string) {
    try {
      await navigator.clipboard.writeText(publicSignUrl(token));
      setCopyOk(true);
      setTimeout(() => setCopyOk(false), 2000);
    } catch {
      setError("Impossible de copier le lien (clipboard refusé).");
    }
  }

  async function downloadPdf() {
    try {
      // Reflète dans le PDF la sélection de modules de l'aperçu client.
      const qs =
        pdfSelection !== null
          ? `?selected=${pdfSelection.join(",")}`
          : "";
      const r = await authedFetch(
        `/api/v1/devlog/soumissions/${id}/pdf${qs}`
      );
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const blob = await r.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `soumission-devlog-${id}.pdf`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch (e) {
      setError(
        (e as Error).message || "Téléchargement du PDF impossible."
      );
    }
  }

  // PDF *signé* — gelé au moment de la signature publique, avec un
  // bandeau vert proéminent « SIGNÉE ÉLECTRONIQUEMENT » + IP +
  // horodatage. Préfère ce PDF quand la soumission est signée
  // (audit trail immuable, vs PDF normal recalculé à chaque fois).
  async function downloadSignedPdf() {
    try {
      const r = await authedFetch(
        `/api/v1/devlog/soumissions/${id}/signed-pdf`
      );
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const blob = await r.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `soumission-${id}-signee.pdf`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch (e) {
      setError(
        (e as Error).message || "Téléchargement du PDF signé impossible."
      );
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
  const orphans = items.filter((it) => it.section_id == null && !isDevisDev);

  const recurringItems = useMemo(
    () => items.filter((it) => it.item_kind === "recurring_cost"),
    [items]
  );
  // Features SANS module : liste « directe » (rétrocompat — soumissions
  // sans modules, ou features pas encore rangées dans un module).
  const featureItems = useMemo(
    () =>
      items.filter(
        (it) => it.item_kind === "feature" && it.module_id == null
      ),
    [items]
  );
  const fixedItems = useMemo(
    () => items.filter((it) => it.item_kind === "fixed_cost"),
    [items]
  );
  // Tâches du chargé de projet — CENTRALISÉES (hors module). Vivent dans
  // le bloc « Gestionnaire de projet », coût global indépendant des
  // modules. On inclut aussi d'éventuelles tâches legacy encore
  // rattachées à un module pour qu'elles restent éditables/visibles.
  const managerTaskItems = useMemo(
    () => items.filter((it) => it.item_kind === "manager_task"),
    [items]
  );
  // Items (features + tâches) groupés par module pour les sous-listes.
  const itemsByModule = useMemo(() => {
    const m = new Map<number, Item[]>();
    for (const it of items) {
      if (it.module_id == null) continue;
      const arr = m.get(it.module_id) || [];
      arr.push(it);
      m.set(it.module_id, arr);
    }
    return m;
  }, [items]);

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
            className="inline-flex items-center text-sm text-white/70 hover:text-accent-500"
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
            title={
              isDevisDev
                ? "Bascule entre la vue propriétaire (marges/heures/taux) et la vue client (prix finaux)"
                : "Bascule entre la vue admin (avec coûts + markup) et la vue client (prix finaux seulement)"
            }
          >
            {adminView ? (
              <>
                <Eye className="h-3.5 w-3.5" />
                {isDevisDev ? "Vue propriétaire" : "Vue admin (coûts visibles)"}
              </>
            ) : (
              <>
                <EyeOff className="h-3.5 w-3.5" />
                Vue client
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
            <Loader2 className="h-6 w-6 animate-spin text-accent-500" />
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
                  className={`badge ${
                    STATUS_CLS[s.status] ?? "badge-neutral"
                  }`}
                >
                  {STATUS_LABEL[s.status] ?? s.status}
                </span>
                {!isDevisDev ? (
                  <span className="badge badge-amber">
                    Ancien format
                  </span>
                ) : null}
                <span className="text-white/40">
                  Créée le{" "}
                  {new Date(s.created_at).toLocaleDateString("fr-CA")}
                </span>
                {s.sent_at ? (
                  <span className="badge badge-blue">
                    Envoyée le{" "}
                    {new Date(s.sent_at).toLocaleDateString("fr-CA")}
                  </span>
                ) : null}
                {s.opened_at ? (
                  <span
                    className="badge badge-violet"
                    title={`Dernière ouverture : ${new Date(
                      s.last_opened_at ?? s.opened_at
                    ).toLocaleString("fr-CA")} · ${
                      s.open_count ?? 1
                    } ouverture(s)`}
                  >
                    <Eye className="h-3 w-3" />
                    Ouverte le{" "}
                    {new Date(s.opened_at).toLocaleDateString("fr-CA")}
                  </span>
                ) : s.sent_at ? (
                  <span className="badge badge-neutral">
                    <EyeOff className="h-3 w-3" />
                    Pas encore ouverte
                  </span>
                ) : null}
                {s.signed_at && s.status === "acceptee" ? (
                  <span className="badge badge-emerald">
                    <CheckCircle2 className="h-3 w-3" />
                    Signée le{" "}
                    {new Date(s.signed_at).toLocaleDateString("fr-CA")}
                    {s.signed_name ? ` par ${s.signed_name}` : ""}
                  </span>
                ) : null}
                {s.signed_at && s.status === "refusee" ? (
                  <span className="badge badge-rose">
                    <XCircle className="h-3 w-3" />
                    Refusée le{" "}
                    {new Date(s.signed_at).toLocaleDateString("fr-CA")}
                    {s.signed_name ? ` par ${s.signed_name}` : ""}
                  </span>
                ) : null}
                <StatusActions
                  status={s.status}
                  isDevisDev={isDevisDev}
                  sending={sending}
                  onSend={sendToClient}
                  onChange={changeStatus}
                />
              </div>
              {isDevisDev ? (
                <div className="mt-3 flex flex-wrap items-center gap-2 text-xs">
                  <button
                    type="button"
                    onClick={() => void downloadPdf()}
                    className="inline-flex items-center gap-1.5 rounded-md border border-emerald-500/40 bg-emerald-500/10 px-3 py-1.5 font-semibold text-emerald-300 hover:bg-emerald-500/20"
                  >
                    <Download className="h-3.5 w-3.5" />
                    Télécharger PDF
                  </button>
                  {/* PDF signé — disponible uniquement quand la soumission
                      est signée (acceptée OU refusée — la signature
                      électronique reste valable comme trace dans les deux
                      cas). Pointe vers le blob figé côté backend. */}
                  {s.signed_at ? (
                    <button
                      type="button"
                      onClick={() => void downloadSignedPdf()}
                      className="inline-flex items-center gap-1.5 rounded-md border border-emerald-400 bg-emerald-500/25 px-3 py-1.5 font-bold text-emerald-200 hover:bg-emerald-500/40"
                      title="PDF avec bandeau SIGNÉE + IP + horodatage"
                    >
                      <FileSignature className="h-3.5 w-3.5" />
                      Télécharger PDF signé
                    </button>
                  ) : null}
                  {s.signature_token && s.sent_at ? (
                    <button
                      type="button"
                      onClick={() =>
                        void copyPublicLink(s.signature_token!)
                      }
                      className="inline-flex items-center gap-1.5 rounded-md border border-blue-500/40 bg-blue-500/10 px-3 py-1.5 font-semibold text-blue-200 hover:brightness-110"
                    >
                      {copyOk ? (
                        <>
                          <CheckCircle2 className="h-3.5 w-3.5" />
                          Lien copié
                        </>
                      ) : (
                        <>
                          <Copy className="h-3.5 w-3.5" />
                          Copier le lien public
                        </>
                      )}
                    </button>
                  ) : null}
                </div>
              ) : null}
              {/* Auto-remplissage contrat — visible uniquement quand la
                  soumission est acceptee. Cree un brouillon de contrat
                  avec parties + objet + conditions + clauses pre-remplis. */}
              {s.status === "acceptee" ? (
                <div className="mt-3 flex flex-wrap items-center gap-2 text-xs">
                  <button
                    type="button"
                    onClick={() => void generateContract()}
                    disabled={generatingContract}
                    className="inline-flex items-center gap-1.5 rounded-md border border-violet-500/40 bg-violet-500/10 px-3 py-1.5 font-semibold text-violet-200 hover:brightness-110 disabled:opacity-60"
                    title="Crée un contrat brouillon auto-rempli depuis cette soumission"
                  >
                    {generatingContract ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    ) : (
                      <FileSignature className="h-3.5 w-3.5" />
                    )}
                    Générer le contrat
                  </button>
                </div>
              ) : null}
            </header>

            {/* Documents Drive (en haut, sous le header) */}
            <EntityDriveSection
              entityType="DevlogSoumission"
              entityId={id}
              pole="Développement logiciel"
              label="Soumission"
              route="/dev-logiciel/soumissions/[id]"
            />

            {/* Encadré client (fix #6) — toujours visible en haut sous le
                header, qu'on soit en vue propriétaire ou client. */}
            <ClientBox
              client={client}
              soumissionId={id}
              hasLead={s.lead_id != null}
              leadName={leadName}
              onLinked={() => void loadAll()}
            />

            {isDevisDev ? (
              <DevisDevEditor
                soumission={s}
                preview={preview}
                recurringItems={recurringItems}
                featureItems={featureItems}
                fixedItems={fixedItems}
                managerTaskItems={managerTaskItems}
                modules={modules}
                itemsByModule={itemsByModule}
                ownerView={adminView}
                onPatchSoumission={patchSoumission}
                onAddItem={addDevisItem}
                onPatchItem={patchItem}
                onDeleteItem={deleteItem}
                onAddModule={addModule}
                onPatchModule={patchModule}
                onDeleteModule={deleteModule}
                onMoveModule={moveModule}
                onReorderModules={reorderModules}
                onAddModuleItem={addModuleItem}
                onReorderItems={reorderItems}
                onSelectionChange={setPdfSelection}
              />
            ) : (
              <LegacyView
                totals={totals}
                initialSections={initialSections}
                recurringSections={recurringSections}
                itemsBySection={itemsBySection}
                orphans={orphans}
                adminView={adminView}
                onAddSection={addSection}
                onPatchSection={patchSection}
                onDeleteSection={deleteSection}
                onAddItem={addItem}
                onPatchItem={patchItem}
                onDeleteItem={deleteItem}
              />
            )}
          </>
        )}
      </div>
    </>
  );
}

// ============================================================
// NOUVELLE VUE — devis_dev (refonte mai 2026)
// ============================================================

// Note additionnelle du bloc récurrent, éditée par le propriétaire et
// servie telle quelle au client (champ `client_recurring_description`).
// State local indépendant des reloads de la soumission pour ne pas
// perturber la frappe (même pattern que les inputs contrôlés).
function ClientRecurringNote({
  soumission: s,
  onPatchSoumission
}: {
  soumission: Soumission;
  onPatchSoumission: (patch: Partial<Soumission>) => void;
}) {
  const [focused, setFocused] = useState(false);
  const [v, setV] = useState(s.client_recurring_description ?? "");
  useEffect(() => {
    if (!focused) setV(s.client_recurring_description ?? "");
  }, [s.client_recurring_description, focused]);

  return (
    <div className="mt-3">
      <label className="text-xs uppercase tracking-wider text-white/40">
        Notes additionnelles client (optionnel)
      </label>
      <textarea
        value={v}
        onFocus={() => setFocused(true)}
        onChange={(e) => setV(e.target.value)}
        onBlur={() => {
          setFocused(false);
          if ((s.client_recurring_description ?? "") !== v) {
            onPatchSoumission({ client_recurring_description: v });
          }
        }}
        placeholder="Précisions sur l'abonnement mensuel (SLA, fréquence des sauvegardes, etc.)..."
        rows={3}
        className="mt-1 w-full rounded border border-emerald-500/30 bg-brand-950 px-3 py-2 text-sm text-white focus:border-emerald-500/60 focus:outline-none"
      />
    </div>
  );
}

// Adapte la sortie de l'endpoint d'aperçu admin (`/devis-preview`) vers
// la forme normalisée consommée par <SoumissionClientView> (la MÊME que
// l'endpoint public `PublicDevisPreview`). Objectif : la « Vue client »
// de l'éditeur affiche EXACTEMENT le rendu de la page publique de
// signature, avec les mêmes montants (prix PAR MODULE, « Inclus
// gratuitement » + condition, totaux initial/mensuel/TPS/TVQ).
//
// On réplique fidèlement la logique du backend `_build_public_preview` :
//   * le prix client PAR FONCTIONNALITÉ vient de `features_client`
//     (indexé par id) ;
//   * la liste COMPLÈTE des fonctionnalités d'un module est reconstruite
//     depuis les items BRUTS (kind=feature uniquement) — y compris pour
//     un module non sélectionné, dont les features sont absentes du
//     calcul mais que le client doit pouvoir (re)cocher. Les
//     `manager_task` sont exclues (jamais montrées au client) ;
//   * un module offert -> prix 0 sur le module et ses features.
//
// Rétrocompat : sans modules, `modules`/`has_modules` restent vides et le
// composant retombe sur la vue plate (features / frais fixes).
function buildClientViewData(
  preview: DevisPreview | null,
  soumission: Soumission,
  itemsByModule: Map<number, Item[]>
): SoumissionClientViewData | null {
  if (!preview) return null;
  const rec = preview.recurring;
  const init = preview.initial;

  // Prix client par feature (id -> prix_client), depuis features_client.
  const featurePriceById = new Map<number, number>();
  for (const f of init.features_client) {
    if (f.id != null) featurePriceById.set(f.id, f.prix_client);
  }

  const publicModules = (init.modules ?? []).map((m) => {
    const isFree = Boolean(m.offert);
    // Fonctionnalités du module = items bruts kind=feature de ce module.
    const rawFeatures = (itemsByModule.get(m.id) ?? []).filter(
      (it) => it.item_kind === "feature"
    );
    const features = rawFeatures.map((it) => ({
      description: it.description || "",
      prix_client: isFree ? 0 : featurePriceById.get(it.id) ?? 0
    }));
    return {
      id: m.id,
      name: m.name || "Module",
      selected: Boolean(m.selected),
      // Tous les modules sont optionnels (pas de notion « obligatoire »).
      optional: true,
      offert: isFree,
      free_when_module_id: m.free_when_module_id ?? null,
      prix_client: m.prix_client ?? 0,
      features
    };
  });

  return {
    recurring: {
      total_client_amount: rec.total_client_amount ?? 0,
      items: (rec.items_breakdown ?? []).map((it) => ({
        description: it.description || ""
      })),
      description: soumission.client_recurring_description || null,
      tps_amount: rec.tps_amount ?? 0,
      tvq_amount: rec.tvq_amount ?? 0,
      tps_pct: rec.tps_pct ?? 5,
      tvq_pct: rec.tvq_pct ?? 9.975,
      total_client_amount_taxe: rec.total_client_amount_taxe ?? 0
    },
    initial: {
      features: (init.features_client ?? []).map((f) => ({
        description: f.description || "",
        prix_client: f.prix_client ?? 0
      })),
      frais_fixes: (init.frais_fixes_client ?? []).map((f) => ({
        description: f.description || "",
        prix_client: f.prix_client ?? 0
      })),
      // Fonctionnalités DIRECTES (hors module) = features sans module_id.
      // Toujours facturées (incluses dans total_final), elles doivent
      // apparaître côté client même en présence de modules — le bloc plat
      // `features` n'est pas rendu en mode modules.
      direct_features: (init.features_client ?? [])
        .filter((f) => f.module_id == null)
        .map((f) => ({
          description: f.description || "",
          prix_client: f.prix_client ?? 0
        })),
      total_final: init.total_final ?? 0,
      tps_amount: init.tps_amount ?? 0,
      tvq_amount: init.tvq_amount ?? 0,
      tps_pct: init.tps_pct ?? 5,
      tvq_pct: init.tvq_pct ?? 9.975,
      total_final_taxe: init.total_final_taxe ?? 0,
      modules: publicModules,
      has_modules: publicModules.length > 0
    }
  };
}

// ───────────────────────────────────────────────────────────────────
// Aperçu « Vue client » INTERACTIF de l'éditeur admin.
//
// Rend EXACTEMENT le composant partagé <SoumissionClientView> (le même
// que la page publique de signature), mais en mode interactif : l'admin
// coche/décoche les modules pour visualiser ce que le client pourra
// faire, avec recalcul du total en direct via l'endpoint POST
// `devis-preview` (sélection simulée, AUCUNE persistance — l'état réel
// des modules et le flux de signature public restent intacts).
//
// La sélection est LOCALE à cet aperçu : on initialise les cases sur
// l'état persisté (`modules[].selected`) puis on laisse l'admin jouer
// avec, sans rien sauvegarder.
// ───────────────────────────────────────────────────────────────────
function AdminClientPreview({
  soumissionId,
  soumission,
  preview,
  modules,
  itemsByModule,
  onSelectionChange
}: {
  soumissionId: number;
  soumission: Soumission;
  preview: DevisPreview | null;
  modules: ModuleRow[];
  itemsByModule: Map<number, Item[]>;
  onSelectionChange: (ids: number[] | null) => void;
}) {
  // Aperçu vivant : initialisé sur le preview persisté, remplacé par le
  // recalcul à chaque bascule de module.
  const [livePreview, setLivePreview] = useState<DevisPreview | null>(preview);
  const [selectedIds, setSelectedIds] = useState<Set<number> | null>(null);
  const [recalculating, setRecalculating] = useState(false);

  // Resynchronise l'aperçu quand le preview persisté change (édition
  // d'items en vue propriétaire puis bascule en vue client).
  useEffect(() => {
    setLivePreview(preview);
  }, [preview]);

  // Initialise / resynchronise les cases sur l'état persisté des modules.
  useEffect(() => {
    if (modules.length > 0) {
      const sel = new Set(
        modules.filter((m) => m.selected).map((m) => m.id)
      );
      setSelectedIds(sel);
      onSelectionChange(Array.from(sel));
    } else {
      setSelectedIds(null);
      onSelectionChange(null);
    }
  }, [modules, onSelectionChange]);

  // Recalcul à la volée (sélection simulée, sans persistance).
  const recalc = useCallback(
    async (ids: Set<number>) => {
      setRecalculating(true);
      try {
        const r = await authedFetch(
          `/api/v1/devlog/soumissions/${soumissionId}/devis-preview`,
          {
            method: "POST",
            body: JSON.stringify({ selected_module_ids: Array.from(ids) })
          }
        );
        if (r.ok) setLivePreview((await r.json()) as DevisPreview);
      } catch {
        // silencieux : on garde l'aperçu courant
      } finally {
        setRecalculating(false);
      }
    },
    [soumissionId]
  );

  function toggleModule(mid: number) {
    const base = selectedIds ? new Set(selectedIds) : new Set<number>();
    if (base.has(mid)) base.delete(mid);
    else base.add(mid);
    setSelectedIds(base);
    void recalc(base);
    onSelectionChange(Array.from(base));
  }

  const clientData = buildClientViewData(
    livePreview,
    soumission,
    itemsByModule
  );

  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-5 text-slate-900 shadow-sm sm:p-6">
      <p className="mb-1 text-xs font-semibold uppercase tracking-wider text-slate-400">
        Aperçu — exactement ce que verra le client
      </p>
      <p className="mb-1 text-[11px] text-slate-400">
        Coche / décoche les modules pour simuler le choix du client. Le
        total se recalcule en direct. (Cet aperçu ne modifie rien.)
      </p>
      {clientData ? (
        <SoumissionClientView
          devis={clientData}
          selectedIds={selectedIds}
          onToggleModule={toggleModule}
          recalculating={recalculating}
        />
      ) : (
        <p className="py-6 text-center text-sm text-slate-400">
          Chargement de la vue client…
        </p>
      )}
    </div>
  );
}

function DevisDevEditor({
  soumission: s,
  preview,
  recurringItems,
  featureItems,
  fixedItems,
  managerTaskItems,
  modules,
  itemsByModule,
  ownerView,
  onPatchSoumission,
  onAddItem,
  onPatchItem,
  onDeleteItem,
  onAddModule,
  onPatchModule,
  onDeleteModule,
  onMoveModule,
  onReorderModules,
  onAddModuleItem,
  onReorderItems,
  onSelectionChange
}: {
  soumission: Soumission;
  preview: DevisPreview | null;
  recurringItems: Item[];
  featureItems: Item[];
  fixedItems: Item[];
  managerTaskItems: Item[];
  modules: ModuleRow[];
  itemsByModule: Map<number, Item[]>;
  ownerView: boolean;
  onPatchSoumission: (patch: Partial<Soumission>) => void;
  onAddItem: (
    kind: "recurring_cost" | "feature" | "fixed_cost" | "manager_task"
  ) => void;
  onPatchItem: (itemId: number, patch: Partial<Item>) => void;
  onDeleteItem: (itemId: number) => void;
  onAddModule: () => void;
  onPatchModule: (moduleId: number, patch: Partial<ModuleRow>) => void;
  onDeleteModule: (moduleId: number) => void;
  onMoveModule: (moduleId: number, dir: -1 | 1) => void;
  onReorderModules: (orderedIds: number[]) => void;
  // Un module ne porte QUE des fonctionnalités désormais.
  onAddModuleItem: (moduleId: number, kind: "feature") => void;
  onReorderItems: (orderedIds: number[]) => void;
  onSelectionChange: (ids: number[] | null) => void;
}) {
  const rec = preview?.recurring;
  const init = preview?.initial;
  const invalid = preview?.is_invalid ?? false;

  // DnD de la liste des frais récurrents (les autres listes vivent dans
  // <DevisDevOwnerInitial> / <ModuleCard>, qui ont leur propre hook).
  const recDnd = useDnd(
    recurringItems.map((it) => it.id),
    onReorderItems
  );

  // ───────────────────────────────────────────────────────────────
  // VUE CLIENT (aperçu) — rendu STRICTEMENT identique à la page
  // publique de signature, via le composant partagé
  // <SoumissionClientView>. INTERACTIF : l'admin peut cocher/décocher
  // les modules pour visualiser EXACTEMENT ce que le client pourra
  // faire, avec recalcul du total en direct (endpoint POST
  // `devis-preview` avec sélection simulée — purement éphémère, ne
  // touche pas l'état persisté ni le flux de signature public). On
  // enveloppe dans un cartouche clair pour reproduire le contexte
  // visuel public (fond blanc, texte slate) au sein de l'éditeur sombre.
  // ───────────────────────────────────────────────────────────────
  if (!ownerView) {
    return (
      <AdminClientPreview
        soumissionId={s.id}
        soumission={s}
        preview={preview}
        modules={modules}
        itemsByModule={itemsByModule}
        onSelectionChange={onSelectionChange}
      />
    );
  }

  return (
    <>
      {/* Totaux haut de page — affichés TTC (taxes incluses) */}
      <div className="mb-5 grid gap-3 sm:grid-cols-2">
        <TotalCard
          label="Investissement initial (TTC)"
          value={init?.total_final_taxe ?? 0}
          icon={<Briefcase className="h-5 w-5 text-blue-300" />}
          accent="blue"
        />
        <TotalCard
          label="Frais mensuels (TTC)"
          value={rec?.total_client_amount_taxe ?? 0}
          icon={<Repeat className="h-5 w-5 text-emerald-300" />}
          accent="emerald"
          suffix=" / mois"
        />
      </div>

      {invalid ? (
        <p className="mb-4 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm font-semibold text-rose-300">
          Paramètres invalides : (1 + marge initiale) × commission closer
          doit rester strictement &lt; 1. Réduis la marge ou la commission
          du closer.
        </p>
      ) : null}

      {/* ========== SECTION 1 — Frais Mensuels Récurrents ========== */}
      <section className="mt-2 rounded-2xl border border-emerald-500/30 bg-emerald-500/5 p-4">
        <header className="mb-3 flex flex-wrap items-end justify-between gap-2 border-b border-emerald-500/30 pb-3">
          <div>
            <h2 className="text-base font-bold text-white">
              1. Frais mensuels récurrents
            </h2>
            <p className="text-xs text-white/60">
              Hébergement, support, abonnements, maintenance — facturés
              chaque mois.
            </p>
          </div>
          {ownerView ? (
            <label className="inline-flex items-center gap-1.5 text-xs text-white/70">
              Marge
              <PctInput
                value={Number(s.marge_recurrente_pct ?? 50)}
                onCommit={(n) =>
                  onPatchSoumission({ marge_recurrente_pct: n })
                }
                step="5"
                className="w-16 rounded border border-emerald-500/30 bg-brand-950 px-1.5 py-0.5 text-right text-white"
              />
              %
            </label>
          ) : null}
        </header>

        {/* Vue propriétaire — liste éditable. (La « Vue client » est
            rendue plus haut par un retour anticipé via le composant
            partagé <SoumissionClientView>.) */}
        {ownerView ? (
          <>
            {recurringItems.length === 0 ? (
              <p className="rounded border border-dashed border-emerald-500/30 px-3 py-4 text-center text-xs text-white/40">
                Aucun coût mensuel. Clique sur « + Ajouter un coût » pour en
                créer un.
              </p>
            ) : (
              <table className="mt-2 w-full text-xs">
                <thead className="text-[10px] uppercase tracking-wider text-white/40">
                  <tr>
                    <th className="w-5"></th>
                    <th className="text-left">Description</th>
                    <th className="text-right">Coût mensuel</th>
                    <th className="text-right">Total ligne</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-emerald-500/20">
                  {recurringItems.map((it, idx) => (
                    <tr
                      key={it.id}
                      {...recDnd.rowProps(idx)}
                      className={dropRowClass(
                        idx,
                        recurringItems.length,
                        recDnd.overIndex,
                        recDnd.isDragging
                      )}
                    >
                      <td className="py-1.5 align-middle">
                        <DragHandle {...recDnd.handleProps(it.id)} />
                      </td>
                      <td className="py-1.5">
                        <DescInput
                          value={it.description}
                          onCommit={(v) =>
                            onPatchItem(it.id, { description: v })
                          }
                          className="w-full rounded border border-transparent bg-transparent px-1 py-0.5 text-white hover:border-emerald-500/30 focus:border-emerald-500/50 focus:outline-none"
                        />
                      </td>
                      <td className="py-1.5 text-right">
                        {/* `text-right` aligne l'input MoneyInput
                            (inline-block) sous l'en-tete COUT MENSUEL
                            au lieu de coller a gauche sous DESCRIPTION.
                            (fix regression PR #481) */}
                        <MoneyInput
                          value={Number(it.cost_per_unit ?? 0)}
                          onCommit={(n) =>
                            onPatchItem(it.id, { cost_per_unit: n })
                          }
                          className="w-24 rounded border border-emerald-500/30 bg-brand-950 px-1.5 py-0.5 text-right text-white"
                        />
                      </td>
                      <td className="py-1.5 text-right text-white/80">
                        {fmtMoneyShort(Number(it.cost_per_unit ?? 0))}
                      </td>
                      <td className="py-1.5">
                        <button
                          type="button"
                          onClick={() => onDeleteItem(it.id)}
                          className="btn-ghost btn-xs"
                        >
                          <Trash2 className="h-3 w-3" />
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
                <tfoot className="border-t border-emerald-500/30 text-xs">
                  {/* Récap aligné sous la colonne « COÛT MENSUEL »
                      (2e colonne). Labels dans la 1re colonne, valeurs
                      dans la 2e ; la colonne « Total ligne » reste
                      vide pour préserver le tableau. (fix #2) */}
                  <tr>
                    <td></td>
                    <td className="pt-2 text-right text-white/60">
                      Coût interne mensuel
                    </td>
                    <td className="pt-2 text-right font-semibold text-white">
                      {fmtAmount(rec?.total_owner_cost ?? 0)}
                    </td>
                    <td></td>
                    <td></td>
                  </tr>
                  <tr>
                    <td></td>
                    <td className="text-right text-white/60">
                      Marge ({s.marge_recurrente_pct ?? 50}%)
                    </td>
                    <td className="text-right text-white/80">
                      + {fmtAmount(rec?.marge_amount ?? 0)}
                    </td>
                    <td></td>
                    <td></td>
                  </tr>
                  <tr>
                    <td></td>
                    <td className="pb-1 text-right text-sm font-bold text-emerald-300">
                      Mensuel client
                    </td>
                    <td className="pb-1 text-right text-base font-bold text-emerald-300">
                      {fmtAmount(rec?.total_client_amount ?? 0)} / mois
                    </td>
                    <td></td>
                    <td></td>
                  </tr>
                </tfoot>
              </table>
            )}
            <button
              type="button"
              onClick={() => onAddItem("recurring_cost")}
              className="mt-2 inline-flex items-center gap-1.5 rounded text-xs text-white/60 hover:text-white"
            >
              <Plus className="h-3 w-3" />
              Ajouter un coût
            </button>
            {/* Note client (anciennement dans la vue client) — éditable
                côté propriétaire ; affichée telle quelle au client
                (champ ``description`` du bloc récurrent). */}
            <ClientRecurringNote
              soumission={s}
              onPatchSoumission={onPatchSoumission}
            />
          </>
        ) : null}
      </section>

      {/* ========== SECTION 2 — Investissement initial ========== */}
      <section className="mt-5 rounded-2xl border border-blue-500/30 bg-blue-500/5 p-4">
        <header className="mb-3 flex flex-wrap items-end justify-between gap-2 border-b border-blue-500/30 pb-3">
          <div>
            <h2 className="text-base font-bold text-white">
              2. Investissement initial
            </h2>
            <p className="text-xs text-white/60">
              Développement initial — payé en une seule fois à la livraison.
            </p>
          </div>
          {ownerView ? (
            <div className="flex flex-wrap items-end gap-2">
              <label className="inline-flex items-center gap-1.5 text-xs text-white/70">
                Marge
                <PctInput
                  value={Number(s.marge_initiale_pct ?? 50)}
                  onCommit={(n) =>
                    onPatchSoumission({ marge_initiale_pct: n })
                  }
                  step="5"
                  className="w-16 rounded border border-blue-500/30 bg-brand-950 px-1.5 py-0.5 text-right text-white"
                />
                %
              </label>
              <label className="inline-flex items-center gap-1.5 text-xs text-white/70">
                Closer
                <PctInput
                  value={Number(s.commission_closer_pct ?? 10)}
                  onCommit={(n) =>
                    onPatchSoumission({ commission_closer_pct: n })
                  }
                  step="1"
                  max="100"
                  className="w-16 rounded border border-blue-500/30 bg-brand-950 px-1.5 py-0.5 text-right text-white"
                />
                %
              </label>
            </div>
          ) : null}
        </header>

        {/* Vue propriétaire (interne). La « Vue client » est rendue plus
            haut via le retour anticipé + <SoumissionClientView>. */}
        <DevisDevOwnerInitial
          soumission={s}
          preview={preview}
          featureItems={featureItems}
          fixedItems={fixedItems}
          managerTaskItems={managerTaskItems}
          modules={modules}
          itemsByModule={itemsByModule}
          onPatchSoumission={onPatchSoumission}
          onAddItem={onAddItem}
          onPatchItem={onPatchItem}
          onDeleteItem={onDeleteItem}
          onAddModule={onAddModule}
          onPatchModule={onPatchModule}
          onDeleteModule={onDeleteModule}
          onMoveModule={onMoveModule}
          onReorderModules={onReorderModules}
          onAddModuleItem={onAddModuleItem}
          onReorderItems={onReorderItems}
        />
      </section>
    </>
  );
}

function DevisDevOwnerInitial({
  soumission: s,
  preview,
  featureItems,
  fixedItems,
  managerTaskItems,
  modules,
  itemsByModule,
  onPatchSoumission,
  onAddItem,
  onPatchItem,
  onDeleteItem,
  onAddModule,
  onPatchModule,
  onDeleteModule,
  onMoveModule,
  onReorderModules,
  onAddModuleItem,
  onReorderItems
}: {
  soumission: Soumission;
  preview: DevisPreview | null;
  featureItems: Item[];
  fixedItems: Item[];
  managerTaskItems: Item[];
  modules: ModuleRow[];
  itemsByModule: Map<number, Item[]>;
  onPatchSoumission: (patch: Partial<Soumission>) => void;
  onAddItem: (
    kind: "recurring_cost" | "feature" | "fixed_cost" | "manager_task"
  ) => void;
  onPatchItem: (itemId: number, patch: Partial<Item>) => void;
  onDeleteItem: (itemId: number) => void;
  onAddModule: () => void;
  onPatchModule: (moduleId: number, patch: Partial<ModuleRow>) => void;
  onDeleteModule: (moduleId: number) => void;
  onMoveModule: (moduleId: number, dir: -1 | 1) => void;
  onReorderModules: (orderedIds: number[]) => void;
  // Un module ne porte QUE des fonctionnalités désormais.
  onAddModuleItem: (moduleId: number, kind: "feature") => void;
  onReorderItems: (orderedIds: number[]) => void;
}) {
  const init = preview?.initial;
  // Soumission figée (acceptée/refusée) = contrat signé : la sélection de
  // modules (et le contenu) ne doit plus être modifiable.
  const locked = s.status === "acceptee" || s.status === "refusee";
  // Détail calculé par module (prix client, heures, état) indexé par id.
  const moduleCalcById = useMemo(() => {
    const m = new Map<number, NonNullable<DevisPreview["initial"]["modules"]>[number]>();
    for (const md of init?.modules ?? []) m.set(md.id, md);
    return m;
  }, [init?.modules]);
  const sortedModules = useMemo(
    () => [...modules].sort((a, b) => a.position - b.position),
    [modules]
  );

  // Total du bloc « Fonctionnalités directes (hors module) » : Σ heures et
  // Σ prix client des features SANS module_id. Même source (preview) et même
  // sémantique que le total affiché par chaque module, pour cohérence.
  const directFeaturesTotals = useMemo(() => {
    const directs = (init?.features_client ?? []).filter(
      (f) => f.module_id == null
    );
    return {
      heures: directs.reduce((acc, f) => acc + (f.heures ?? 0), 0),
      prixClient: directs.reduce((acc, f) => acc + (f.prix_client ?? 0), 0)
    };
  }, [init?.features_client]);

  // DnD : tâches du chargé de projet, fonctionnalités directes, frais
  // fixes, et modules entre eux (en complément des flèches ↑/↓).
  const taskDnd = useDnd(
    managerTaskItems.map((it) => it.id),
    onReorderItems
  );
  const featDnd = useDnd(
    featureItems.map((it) => it.id),
    onReorderItems
  );
  const fixedDnd = useDnd(
    fixedItems.map((it) => it.id),
    onReorderItems
  );
  const moduleDnd = useDnd(
    sortedModules.map((m) => m.id),
    onReorderModules
  );

  return (
    <div className="space-y-4">
      {locked ? (
        <div className="rounded-xl border border-emerald-500/30 bg-emerald-500/10 p-3 text-sm text-emerald-200">
          🔒 <span className="font-semibold">Soumission figée</span> — elle a
          été {s.status === "acceptee" ? "acceptée et signée" : "refusée"} par
          le client. La sélection ci-dessous est{" "}
          <span className="font-semibold">verrouillée</span> et reflète
          exactement ce que le client a retenu. Pour la modifier, change
          d'abord son statut (en haut) pour la rouvrir.
        </div>
      ) : null}
      {/* Gestionnaire de projet — bloc UNIQUE et GLOBAL (refonte
          2026-06). Le chargé de projet n'est plus rattaché aux modules :
          c'est une liste de tâches (description + heures) propre à la
          soumission, dont le coût total (Σ heures × taux horaire) s'ajoute
          toujours au total, indépendamment de la sélection des modules. */}
      <div className="rounded-xl border border-blue-500/20 bg-brand-950/40 p-3">
        <div className="flex flex-wrap items-end justify-between gap-2">
          <div>
            <h3 className="text-xs font-bold uppercase tracking-wider text-blue-200">
              Gestionnaire de projet
            </h3>
            <p className="text-[10px] text-white/40">
              Tâches de gestion globales du projet — coût indépendant des
              modules sélectionnés par le client.
            </p>
          </div>
          <label className="inline-flex items-end gap-2 text-xs text-white/70">
            Taux horaire
            <MoneyInput
              value={Number(s.taux_manager_horaire ?? 80)}
              onCommit={(n) =>
                onPatchSoumission({ taux_manager_horaire: n })
              }
              className="block w-24 rounded border border-blue-500/30 bg-brand-950 px-1.5 py-0.5 text-right text-white focus:outline-none"
            />
          </label>
        </div>
        {managerTaskItems.length === 0 ? (
          <p className="mt-2 rounded border border-dashed border-blue-500/20 px-3 py-4 text-center text-xs text-white/40">
            Aucune tâche du chargé de projet. Ajoute-en une pour
            comptabiliser la gestion de projet.
          </p>
        ) : (
          <table className="mt-2 w-full text-xs">
            <thead className="text-[10px] uppercase tracking-wider text-white/40">
              <tr>
                <th className="w-5"></th>
                <th className="text-left">Tâche</th>
                <th className="text-right">Heures</th>
                <th className="text-right">Coût</th>
                <th></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-blue-500/20 align-middle">
              {managerTaskItems.map((it, idx) => (
                <tr
                  key={it.id}
                  {...taskDnd.rowProps(idx)}
                  className={dropRowClass(
                    idx,
                    managerTaskItems.length,
                    taskDnd.overIndex,
                    taskDnd.isDragging
                  )}
                >
                  <td className="py-1.5 align-middle">
                    <DragHandle {...taskDnd.handleProps(it.id)} />
                  </td>
                  <td className="py-1.5">
                    <DescInput
                      value={it.description}
                      onCommit={(v) =>
                        onPatchItem(it.id, { description: v })
                      }
                      className="w-full rounded border border-transparent bg-transparent px-1 py-0.5 text-white hover:border-blue-500/30 focus:border-blue-500/50 focus:outline-none"
                    />
                  </td>
                  <td className="py-1.5">
                    <div className="flex justify-end">
                      <HoursInput
                        value={Number(it.heures ?? 0)}
                        onCommit={(n) =>
                          onPatchItem(it.id, { heures: n })
                        }
                        className="w-24 rounded border border-blue-500/30 bg-brand-950 px-1.5 py-0.5 text-right text-white"
                      />
                    </div>
                  </td>
                  <td className="py-1.5 text-right text-white/80">
                    {fmtMoneyShort(
                      Number(it.heures ?? 0) *
                        Number(s.taux_manager_horaire ?? 80)
                    )}
                  </td>
                  <td className="py-1.5">
                    <button
                      type="button"
                      onClick={() => onDeleteItem(it.id)}
                      className="btn-ghost btn-xs"
                    >
                      <Trash2 className="h-3 w-3" />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
          <button
            type="button"
            onClick={() => onAddItem("manager_task")}
            className="inline-flex items-center gap-1.5 rounded text-xs text-white/60 hover:text-white"
          >
            <Plus className="h-3 w-3" />
            Ajouter une tâche
          </button>
          <div className="flex flex-wrap items-center gap-x-4 gap-y-0.5 text-xs text-white/70">
            <span>
              Total heures :{" "}
              <span className="font-semibold text-white">
                {managerTaskItems.reduce(
                  (acc, it) => acc + Number(it.heures ?? 0),
                  0
                )}{" "}
                h
              </span>
            </span>
            <span>
              Coût manager :{" "}
              <span className="font-bold text-blue-200">
                {fmtMoneyShort(Number(init?.cout_manager ?? 0))}
              </span>
            </span>
          </div>
        </div>
      </div>

      {/* Modules (refonte 2026-06) — chaque module regroupe UNIQUEMENT
          des fonctionnalités (vue client). Les tâches du chargé de projet
          sont centralisées dans le bloc « Gestionnaire de projet »
          ci-dessus (coût global). Les features SANS module restent en
          liste directe ci-dessous (rétrocompat). */}
      <div className="rounded-xl border border-blue-500/20 bg-brand-950/40 p-3">
        <div className="flex flex-wrap items-end justify-between gap-2">
          <div>
            <h3 className="text-xs font-bold uppercase tracking-wider text-blue-200">
              Modules
            </h3>
            <p className="text-[10px] text-white/40">
              Regroupe les fonctionnalités en modules sélectionnables, avec
              règle de gratuité « module → module ».
            </p>
          </div>
          <div className="flex items-end gap-2">
            <label className="inline-flex items-end gap-2 text-xs text-white/70">
              Taux dev
              <MoneyInput
                value={Number(s.taux_dev_horaire ?? 75)}
                onCommit={(n) =>
                  onPatchSoumission({ taux_dev_horaire: n })
                }
                className="block w-24 rounded border border-blue-500/30 bg-brand-950 px-1.5 py-0.5 text-right text-white focus:outline-none"
              />
            </label>
            <button
              type="button"
              onClick={onAddModule}
              className="inline-flex items-center gap-1.5 rounded border border-blue-500/30 px-2 py-1 text-xs text-blue-200 hover:bg-blue-500/15"
            >
              <Plus className="h-3 w-3" />
              Ajouter un module
            </button>
          </div>
        </div>
        {sortedModules.length === 0 ? (
          <p className="mt-2 rounded border border-dashed border-blue-500/20 px-3 py-4 text-center text-xs text-white/40">
            Aucun module. Les fonctionnalités directes ci-dessous sont
            comptées telles quelles. Crée un module pour regrouper des
            fonctionnalités et activer sélection / gratuité.
          </p>
        ) : (
          <div className="mt-3 space-y-3">
            {sortedModules.map((md, idx) => (
              <div
                key={md.id}
                {...moduleDnd.rowProps(idx)}
                className={`rounded-lg ${dropRowClass(
                  idx,
                  sortedModules.length,
                  moduleDnd.overIndex,
                  moduleDnd.isDragging
                )}`}
              >
                <ModuleCard
                  module={md}
                  index={idx}
                  count={sortedModules.length}
                  allModules={sortedModules}
                  items={itemsByModule.get(md.id) ?? []}
                  calc={moduleCalcById.get(md.id)}
                  tauxDev={Number(s.taux_dev_horaire ?? 75)}
                  dragHandleProps={moduleDnd.handleProps(md.id)}
                  onPatchModule={onPatchModule}
                  onDeleteModule={onDeleteModule}
                  onMoveModule={onMoveModule}
                  onAddModuleItem={onAddModuleItem}
                  onReorderItems={onReorderItems}
                  onPatchItem={onPatchItem}
                  onDeleteItem={onDeleteItem}
                  locked={locked}
                />
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Features (directes — sans module) */}
      <div className="rounded-xl border border-blue-500/20 bg-brand-950/40 p-3">
        <div className="flex flex-wrap items-end justify-between gap-2">
          <h3 className="text-xs font-bold uppercase tracking-wider text-blue-200">
            Fonctionnalités directes (hors module)
          </h3>
          <label className="inline-flex items-end gap-2 text-xs text-white/70">
            Taux dev
            <MoneyInput
              value={Number(s.taux_dev_horaire ?? 75)}
              onCommit={(n) =>
                onPatchSoumission({ taux_dev_horaire: n })
              }
              className="block w-24 rounded border border-blue-500/30 bg-brand-950 px-1.5 py-0.5 text-right text-white focus:outline-none"
            />
          </label>
        </div>
        {featureItems.length === 0 ? (
          <p className="mt-2 rounded border border-dashed border-blue-500/20 px-3 py-4 text-center text-xs text-white/40">
            Aucune fonctionnalité hors module. Range tes fonctionnalités
            dans des modules ci-dessus, ou ajoute-en une directe.
          </p>
        ) : (
          <table className="mt-2 w-full text-xs">
            <thead className="text-[10px] uppercase tracking-wider text-white/40">
              <tr>
                <th className="w-5"></th>
                <th className="text-left">Feature</th>
                <th className="text-right">Heures</th>
                <th className="text-right">Coût dev</th>
                <th></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-blue-500/20 align-middle">
              {featureItems.map((it, idx) => (
                <tr
                  key={it.id}
                  {...featDnd.rowProps(idx)}
                  className={dropRowClass(
                    idx,
                    featureItems.length,
                    featDnd.overIndex,
                    featDnd.isDragging
                  )}
                >
                  <td className="py-1.5 align-middle">
                    <DragHandle {...featDnd.handleProps(it.id)} />
                  </td>
                  <td className="py-1.5">
                    <DescInput
                      value={it.description}
                      onCommit={(v) =>
                        onPatchItem(it.id, { description: v })
                      }
                      className="w-full rounded border border-transparent bg-transparent px-1 py-0.5 text-white hover:border-blue-500/30 focus:border-blue-500/50 focus:outline-none"
                    />
                  </td>
                  <td className="py-1.5">
                    {/* `flex justify-end` aligne l'input HoursInput
                        à droite de la cellule, sur la même ligne
                        horizontale que les autres cellules. */}
                    <div className="flex justify-end">
                      <HoursInput
                        value={Number(it.heures ?? 0)}
                        onCommit={(n) =>
                          onPatchItem(it.id, { heures: n })
                        }
                        className="w-24 rounded border border-blue-500/30 bg-brand-950 px-1.5 py-0.5 text-right text-white"
                      />
                    </div>
                  </td>
                  <td className="py-1.5 text-right text-white/80">
                    {fmtMoneyShort(
                      Number(it.heures ?? 0) *
                        Number(s.taux_dev_horaire ?? 75)
                    )}
                  </td>
                  <td className="py-1.5">
                    <button
                      type="button"
                      onClick={() => onDeleteItem(it.id)}
                      className="btn-ghost btn-xs"
                    >
                      <Trash2 className="h-3 w-3" />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {/* Total du bloc (mêmes libellés/style que le total d'un module) :
            Σ heures dev + prix client total des fonctionnalités directes. */}
        {featureItems.length > 0 ? (
          <div className="mt-2 flex flex-wrap items-center justify-end gap-x-3 gap-y-0.5 border-t border-blue-500/20 pt-2 text-[11px] text-white/70">
            <span>
              Dev :{" "}
              <span className="font-semibold text-white">
                {directFeaturesTotals.heures} h
              </span>
            </span>
            <span>
              Prix client :{" "}
              <span className="font-bold text-blue-200">
                {fmtMoneyShort(directFeaturesTotals.prixClient)}
              </span>
            </span>
          </div>
        ) : null}
        <button
          type="button"
          onClick={() => onAddItem("feature")}
          className="mt-2 inline-flex items-center gap-1.5 rounded text-xs text-white/60 hover:text-white"
        >
          <Plus className="h-3 w-3" />
          Ajouter une fonctionnalité directe
        </button>
      </div>

      {/* Frais fixes uniques */}
      <div className="rounded-xl border border-blue-500/20 bg-brand-950/40 p-3">
        <h3 className="text-xs font-bold uppercase tracking-wider text-blue-200">
          Frais fixes uniques
        </h3>
        <p className="text-[10px] text-white/40">
          Domaine, hosting initial, licences logicielles ponctuelles, etc.
        </p>
        {fixedItems.length === 0 ? (
          <p className="mt-2 rounded border border-dashed border-blue-500/20 px-3 py-4 text-center text-xs text-white/40">
            Aucun frais fixe.
          </p>
        ) : (
          <table className="mt-2 w-full text-xs">
            <thead className="text-[10px] uppercase tracking-wider text-white/40">
              <tr>
                <th className="w-5"></th>
                <th className="text-left">Description</th>
                <th className="text-right">Coût</th>
                <th></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-blue-500/20 align-middle">
              {fixedItems.map((it, idx) => (
                <tr
                  key={it.id}
                  {...fixedDnd.rowProps(idx)}
                  className={dropRowClass(
                    idx,
                    fixedItems.length,
                    fixedDnd.overIndex,
                    fixedDnd.isDragging
                  )}
                >
                  <td className="py-1.5 align-middle">
                    <DragHandle {...fixedDnd.handleProps(it.id)} />
                  </td>
                  <td className="py-1.5">
                    <DescInput
                      value={it.description}
                      onCommit={(v) =>
                        onPatchItem(it.id, { description: v })
                      }
                      className="w-full rounded border border-transparent bg-transparent px-1 py-0.5 text-white hover:border-blue-500/30 focus:border-blue-500/50 focus:outline-none"
                    />
                  </td>
                  <td className="py-1.5">
                    <div className="flex justify-end">
                      <MoneyInput
                        value={Number(it.cost_per_unit ?? 0)}
                        onCommit={(n) =>
                          onPatchItem(it.id, { cost_per_unit: n })
                        }
                        className="w-24 rounded border border-blue-500/30 bg-brand-950 px-1.5 py-0.5 text-right text-white"
                      />
                    </div>
                  </td>
                  <td className="py-1.5">
                    <button
                      type="button"
                      onClick={() => onDeleteItem(it.id)}
                      className="btn-ghost btn-xs"
                    >
                      <Trash2 className="h-3 w-3" />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <button
          type="button"
          onClick={() => onAddItem("fixed_cost")}
          className="mt-2 inline-flex items-center gap-1.5 rounded text-xs text-white/60 hover:text-white"
        >
          <Plus className="h-3 w-3" />
          Ajouter un frais fixe
        </button>
      </div>

      {/* Récap de calcul */}
      <div className="rounded-xl border border-amber-500/40 bg-amber-500/5 p-4">
        <h3 className="text-xs font-bold uppercase tracking-wider text-amber-200">
          Récapitulatif de calcul (vue propriétaire)
        </h3>
        <dl className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
          <dt className="text-white/60">Coûts dev (Σ heures × taux dev)</dt>
          <dd className="text-right font-semibold text-white">
            {fmtAmount(init?.couts_dev ?? 0)}
          </dd>
          <dt className="text-white/60">Coût manager</dt>
          <dd className="text-right font-semibold text-white">
            {fmtAmount(init?.cout_manager ?? 0)}
          </dd>
          <dt className="text-white/60">Frais fixes</dt>
          <dd className="text-right font-semibold text-white">
            {fmtAmount(init?.frais_fixes_total ?? 0)}
          </dd>
          <dt className="border-t border-amber-500/30 pt-1 text-white/80">
            Base
          </dt>
          <dd className="border-t border-amber-500/30 pt-1 text-right font-bold text-white">
            {fmtAmount(init?.base ?? 0)}
          </dd>
          <dt className="text-white/60">
            Commission closer ({init?.closer_pct ?? 10}%)
          </dt>
          <dd className="text-right font-semibold text-white">
            + {fmtAmount(init?.closing ?? 0)}
          </dd>
          <dt className="text-white/60">Total avant marge</dt>
          <dd className="text-right text-white/80">
            {fmtAmount(init?.total_avant_marge ?? 0)}
          </dd>
          <dt className="text-white/60">
            Marge ({init?.marge_pct ?? 50}%)
          </dt>
          <dd className="text-right text-white/80">
            + {fmtAmount(init?.marge_amount ?? 0)}
          </dd>
          <dt className="border-t border-amber-500/40 pt-1 text-base text-amber-200">
            Total final (avant taxes)
          </dt>
          <dd className="border-t border-amber-500/40 pt-1 text-right text-base font-bold text-amber-200">
            {fmtAmount(init?.total_final ?? 0)}
          </dd>
          {/* Taxes Québec — appliquées sur total_final qui inclut déjà
              le closer (10%) et la marge initiale. Le closer reste
              calculé AVANT taxes. (fix #3) */}
          <dt className="text-white/60">
            + TPS ({init?.tps_pct ?? 5}%)
          </dt>
          <dd className="text-right text-white/80">
            {fmtAmount(init?.tps_amount ?? 0)}
          </dd>
          <dt className="text-white/60">
            + TVQ ({init?.tvq_pct ?? 9.975}%)
          </dt>
          <dd className="text-right text-white/80">
            {fmtAmount(init?.tvq_amount ?? 0)}
          </dd>
          <dt className="border-t border-emerald-500/40 pt-1 text-base font-bold text-emerald-300">
            Total final TTC
          </dt>
          <dd className="border-t border-emerald-500/40 pt-1 text-right text-base font-bold text-emerald-300">
            {fmtAmount(init?.total_final_taxe ?? 0)}
          </dd>
        </dl>
      </div>
    </div>
  );
}

// Carte d'un module (vue interne / propriétaire) : en-tête (sélection,
// nom, réordonnancement, suppression), règle de gratuité, totaux
// calculés, et 2 sous-listes éditables (fonctionnalités + tâches du
// chargé de projet). Phase 3.
function ModuleCard({
  module: md,
  index,
  count,
  allModules,
  items,
  calc,
  tauxDev,
  dragHandleProps,
  onPatchModule,
  onDeleteModule,
  onMoveModule,
  onAddModuleItem,
  onReorderItems,
  onPatchItem,
  onDeleteItem,
  locked
}: {
  module: ModuleRow;
  index: number;
  count: number;
  allModules: ModuleRow[];
  items: Item[];
  calc:
    | NonNullable<DevisPreview["initial"]["modules"]>[number]
    | undefined;
  tauxDev: number;
  // Poignée de glissement du module (drag du module entier).
  dragHandleProps: React.HTMLAttributes<HTMLSpanElement> & {
    draggable?: boolean;
  };
  onPatchModule: (moduleId: number, patch: Partial<ModuleRow>) => void;
  onDeleteModule: (moduleId: number) => void;
  onMoveModule: (moduleId: number, dir: -1 | 1) => void;
  // Un module ne porte QUE des fonctionnalités désormais.
  onAddModuleItem: (moduleId: number, kind: "feature") => void;
  onReorderItems: (orderedIds: number[]) => void;
  onPatchItem: (itemId: number, patch: Partial<Item>) => void;
  onDeleteItem: (itemId: number) => void;
  // Soumission figée (acceptée/refusée) : la sélection n'est plus modifiable.
  locked: boolean;
}) {
  // Un module ne contient QUE des fonctionnalités (les tâches du chargé
  // de projet sont centralisées dans le bloc « Gestionnaire de projet »).
  const features = items.filter((it) => it.item_kind === "feature");
  // DnD des fonctionnalités DANS ce module (réordonnancement intra-module).
  const featDnd = useDnd(
    features.map((it) => it.id),
    onReorderItems
  );
  const selected = md.selected !== false;
  const offert = calc?.offert ?? false;
  const heuresDev = calc?.total_heures_dev ?? 0;
  const prixClient = calc?.prix_client ?? 0;
  // Les autres modules (candidats déclencheurs de la gratuité).
  const otherModules = allModules.filter((m) => m.id !== md.id);

  return (
    <div
      className={`rounded-lg border p-3 ${
        selected
          ? "border-blue-500/20 bg-brand-950/40"
          : "border-white/10 bg-white/[0.02] opacity-70"
      }`}
    >
      {/* En-tête module */}
      <div className="flex flex-wrap items-center gap-2">
        <DragHandle {...dragHandleProps} />
        <label
          className={`inline-flex items-center gap-1.5 text-xs text-white/80 ${
            locked ? "cursor-not-allowed opacity-60" : ""
          }`}
          title={
            locked
              ? "Soumission figée — sélection verrouillée"
              : "Inclure ce module dans la soumission"
          }
        >
          <input
            type="checkbox"
            checked={selected}
            disabled={locked}
            onChange={(e) =>
              onPatchModule(md.id, { selected: e.target.checked })
            }
            className="h-4 w-4 rounded border-white/30 bg-brand-950 accent-blue-500 disabled:cursor-not-allowed"
          />
          Inclure
        </label>
        <div className="min-w-[8rem] flex-1">
          <DescInput
            value={md.name}
            onCommit={(v) => onPatchModule(md.id, { name: v })}
            placeholder="Nom du module"
            className="w-full rounded border border-transparent bg-transparent px-1.5 py-1 text-sm font-semibold text-white hover:border-blue-500/30 focus:border-blue-500/50 focus:outline-none"
          />
        </div>
        {offert ? (
          <span className="badge badge-emerald">
            <Gift className="h-3 w-3" />
            Offert
          </span>
        ) : null}
        <div className="flex items-center gap-0.5">
          <button
            type="button"
            disabled={index === 0}
            onClick={() => onMoveModule(md.id, -1)}
            className="btn-ghost btn-xs disabled:opacity-20"
            title="Monter"
          >
            <ChevronUp className="h-3.5 w-3.5" />
          </button>
          <button
            type="button"
            disabled={index === count - 1}
            onClick={() => onMoveModule(md.id, 1)}
            className="btn-ghost btn-xs disabled:opacity-20"
            title="Descendre"
          >
            <ChevronDown className="h-3.5 w-3.5" />
          </button>
          <button
            type="button"
            onClick={() => onDeleteModule(md.id)}
            className="btn-ghost btn-xs"
            title="Supprimer le module"
          >
            <Trash2 className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>

      {/* Règle de gratuité + totaux calculés */}
      <div className="mt-2 flex flex-wrap items-center justify-between gap-2 border-y border-white/5 py-2">
        <label className="inline-flex items-center gap-1.5 text-[11px] text-white/60">
          <Gift className="h-3.5 w-3.5 text-emerald-300/70" />
          Offert si le module
          <select
            value={md.free_when_module_id ?? ""}
            onChange={(e) =>
              onPatchModule(md.id, {
                free_when_module_id: e.target.value
                  ? Number(e.target.value)
                  : null
              })
            }
            className="rounded border border-white/15 bg-brand-950 px-1.5 py-0.5 text-[11px] text-white focus:outline-none"
          >
            <option value="">— (jamais offert)</option>
            {otherModules.map((m) => (
              <option key={m.id} value={m.id}>
                {m.name || `Module #${m.id}`}
              </option>
            ))}
          </select>
          est sélectionné
        </label>
        <div className="flex flex-wrap items-center gap-x-3 gap-y-0.5 text-[11px] text-white/70">
          <span>
            Dev :{" "}
            <span className="font-semibold text-white">{heuresDev} h</span>
          </span>
          <span>
            Prix client :{" "}
            <span className="font-bold text-blue-200">
              {offert ? "Offert" : fmtMoneyShort(prixClient)}
            </span>
          </span>
        </div>
      </div>

      {/* Fonctionnalités du module (vue client + interne). Un module ne
          contient QUE des fonctionnalités. */}
      <div className="mt-3">
        <div className="flex items-center justify-between">
          <h4 className="text-[10px] font-bold uppercase tracking-wider text-blue-200">
            Fonctionnalités
          </h4>
        </div>
        {features.length === 0 ? (
          <p className="mt-1 text-[11px] text-white/35">
            Aucune fonctionnalité.
          </p>
        ) : (
          <table className="mt-1 w-full text-xs">
            <thead className="text-[10px] uppercase tracking-wider text-white/40">
              <tr>
                <th className="w-5"></th>
                <th className="text-left font-medium">Fonctionnalité</th>
                <th className="text-right font-medium">Heures</th>
                <th className="text-right font-medium">Coût dev</th>
                <th></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/5 align-middle">
              {features.map((it, idx) => (
                <tr
                  key={it.id}
                  {...featDnd.rowProps(idx)}
                  className={dropRowClass(
                    idx,
                    features.length,
                    featDnd.overIndex,
                    featDnd.isDragging
                  )}
                >
                  <td className="py-1 align-middle">
                    <DragHandle {...featDnd.handleProps(it.id)} />
                  </td>
                  <td className="py-1">
                    <DescInput
                      value={it.description}
                      onCommit={(v) =>
                        onPatchItem(it.id, { description: v })
                      }
                      className="w-full rounded border border-transparent bg-transparent px-1 py-0.5 text-white hover:border-blue-500/30 focus:border-blue-500/50 focus:outline-none"
                    />
                  </td>
                  <td className="py-1">
                    <div className="flex justify-end">
                      <HoursInput
                        value={Number(it.heures ?? 0)}
                        onCommit={(n) => onPatchItem(it.id, { heures: n })}
                        className="w-20 rounded border border-blue-500/30 bg-brand-950 px-1.5 py-0.5 text-right text-white"
                      />
                    </div>
                  </td>
                  <td className="py-1 text-right text-white/70">
                    {fmtMoneyShort(Number(it.heures ?? 0) * tauxDev)}
                  </td>
                  <td className="py-1">
                    <button
                      type="button"
                      onClick={() => onDeleteItem(it.id)}
                      className="btn-ghost btn-xs"
                    >
                      <Trash2 className="h-3 w-3" />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <button
          type="button"
          onClick={() => onAddModuleItem(md.id, "feature")}
          className="mt-1 inline-flex items-center gap-1 rounded text-[11px] text-white/50 hover:text-white"
        >
          <Plus className="h-3 w-3" />
          Ajouter une fonctionnalité
        </button>
      </div>
    </div>
  );
}

// ============================================================
// LEGACY — soumissions pré-refonte (lecture seule)
// ============================================================

function LegacyView({
  totals,
  initialSections,
  recurringSections,
  itemsBySection,
  orphans,
  adminView,
  onAddSection,
  onPatchSection,
  onDeleteSection,
  onAddItem,
  onPatchItem,
  onDeleteItem
}: {
  totals: Totals;
  initialSections: Section[];
  recurringSections: Section[];
  itemsBySection: Map<number, Item[]>;
  orphans: Item[];
  adminView: boolean;
  onAddSection: (kind: "initial" | "recurring") => void;
  onPatchSection: (id: number, patch: Partial<Section>) => void;
  onDeleteSection: (id: number) => void;
  onAddItem: (sectionId: number) => void;
  onPatchItem: (id: number, patch: Partial<Item>) => void;
  onDeleteItem: (id: number) => void;
}) {
  return (
    <>
      <p className="mb-3 rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs text-amber-200">
        Cette soumission utilise l'ancien format (avant la refonte mai
        2026). Tu peux toujours modifier les items mais les nouveaux
        devis utilisent le format à calcul circulaire (2 sections,
        propriétaire/client).
      </p>

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

      <SectionGroup
        title="Frais initial — développement"
        subtitle="Payé une seule fois à la livraison"
        sections={initialSections}
        items={itemsBySection}
        addLabel="Ajouter une section initiale"
        onAdd={() => onAddSection("initial")}
        onPatchSection={onPatchSection}
        onDeleteSection={onDeleteSection}
        onAddItem={onAddItem}
        onPatchItem={onPatchItem}
        onDeleteItem={onDeleteItem}
        adminView={adminView}
      />

      <SectionGroup
        title="Frais mensuel — hébergement + abonnements"
        subtitle="Facturé tous les mois (hosting du produit + softwares)"
        sections={recurringSections}
        items={itemsBySection}
        addLabel="Ajouter une section mensuelle"
        onAdd={() => onAddSection("recurring")}
        onPatchSection={onPatchSection}
        onDeleteSection={onDeleteSection}
        onAddItem={onAddItem}
        onPatchItem={onPatchItem}
        onDeleteItem={onDeleteItem}
        adminView={adminView}
      />

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
                  onClick={() => void onDeleteItem(it.id)}
                  className="btn-ghost btn-xs"
                >
                  <Trash2 className="h-3 w-3" />
                </button>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </>
  );
}

// Encadré client (fix #6) — affiche nom + email + téléphone +
// adresse du client lié à la soumission.
//
// Si aucun client formel n'est lié, le rendu dépend de la présence
// d'un prospect (lead) rattaché :
//   * prospect présent  -> encadré neutre « Destinataire : … », pas
//     d'alerte (le client sera créé à l'envoi). Le bouton « Lier un
//     client » reste accessible, mais discret.
//   * aucun destinataire -> vraie alerte (amber) demandant de lier un
//     prospect/client avant l'envoi.
// Le picker poste un PATCH sur la soumission pour mettre à jour
// ``client_id``.
function ClientBox({
  client,
  soumissionId,
  hasLead,
  leadName,
  onLinked
}: {
  client: ClientInfo | null;
  soumissionId: number;
  hasLead: boolean;
  leadName: string | null;
  onLinked: () => void;
}) {
  const [pickerOpen, setPickerOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [candidates, setCandidates] = useState<ClientInfo[]>([]);
  const [loadingCandidates, setLoadingCandidates] = useState(false);
  const [linkError, setLinkError] = useState<string | null>(null);

  useEffect(() => {
    if (!pickerOpen) return;
    let cancelled = false;
    setLoadingCandidates(true);
    void (async () => {
      try {
        const r = await authedFetch(
          `/api/v1/devlog/clients?limit=500`
        );
        if (r.ok && !cancelled) {
          setCandidates((await r.json()) as ClientInfo[]);
        }
      } catch {
        /* ignore */
      } finally {
        if (!cancelled) setLoadingCandidates(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [pickerOpen]);

  async function linkClient(clientId: number) {
    setLinkError(null);
    try {
      const r = await authedFetch(
        `/api/v1/devlog/soumissions/${soumissionId}`,
        {
          method: "PATCH",
          body: JSON.stringify({ client_id: clientId })
        }
      );
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      setPickerOpen(false);
      setQuery("");
      onLinked();
    } catch (e) {
      setLinkError((e as Error).message || "Liaison impossible.");
    }
  }

  const filteredCandidates = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return candidates.slice(0, 50);
    return candidates
      .filter(
        (c) =>
          (c.name || "").toLowerCase().includes(q) ||
          (c.email || "").toLowerCase().includes(q) ||
          (c.company || "").toLowerCase().includes(q)
      )
      .slice(0, 50);
  }, [candidates, query]);

  if (client) {
    return (
      <div className="mb-5 rounded-lg border border-brand-800 bg-brand-900/40 px-4 py-3">
        <div className="flex flex-wrap items-start gap-x-6 gap-y-2 text-sm">
          <div className="min-w-0">
            <p className="text-[10px] uppercase tracking-wider text-white/40">
              Client
            </p>
            <p className="font-semibold text-white/90">{client.name}</p>
            {client.company ? (
              <p className="text-xs text-white/60">{client.company}</p>
            ) : null}
          </div>
          {client.email ? (
            <div className="min-w-0">
              <p className="text-[10px] uppercase tracking-wider text-white/40">
                Courriel
              </p>
              <p className="text-white/90">{client.email}</p>
            </div>
          ) : null}
          {client.phone ? (
            <div className="min-w-0">
              <p className="text-[10px] uppercase tracking-wider text-white/40">
                Téléphone
              </p>
              <p className="text-white/90">{client.phone}</p>
            </div>
          ) : null}
          {client.address ? (
            <div className="min-w-0">
              <p className="text-[10px] uppercase tracking-wider text-white/40">
                Adresse
              </p>
              <p className="text-white/90">{client.address}</p>
            </div>
          ) : null}
        </div>
      </div>
    );
  }

  // Deux cas distincts quand aucun client formel n'est encore lié :
  //
  //   * Un prospect (lead) EST rattaché : pas d'alerte. La soumission a
  //     bien un destinataire — le client formel sera créé à la signature.
  //     On affiche un encadré neutre (couleurs brand) qui rappelle le
  //     destinataire, avec un bouton discret « Lier un client » au cas où
  //     Phil veut rattacher un client existant.
  //
  //   * Aucun prospect ni client : vraie alerte (amber). Il faut lier un
  //     client/prospect avant de pouvoir envoyer.
  return (
    <div
      className={`mb-5 rounded-lg border px-4 py-3 text-sm ${
        hasLead
          ? "border-brand-800 bg-brand-900/40"
          : "border-amber-500/40 bg-amber-500/10"
      }`}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        {hasLead ? (
          <p className="text-white/70">
            <span className="text-[10px] uppercase tracking-wider text-white/40">
              Destinataire
            </span>
            <br />
            <span className="font-semibold text-white/90">
              {leadName ?? "Prospect rattaché"}
            </span>{" "}
            <span className="text-xs text-white/50">
              — le client formel sera créé à l'envoi.
            </span>
          </p>
        ) : (
          <p className="text-amber-200">
            Aucun destinataire lié à cette soumission. Lie un prospect ou
            un client pour pouvoir l'envoyer.
          </p>
        )}
        <button
          type="button"
          onClick={() => setPickerOpen((v) => !v)}
          className={`inline-flex items-center gap-1.5 rounded-md border px-3 py-1 text-xs font-semibold ${
            hasLead
              ? "border-brand-800 bg-white/5 text-white/60 hover:bg-white/10"
              : "border-amber-500/40 bg-amber-500/10 text-amber-200 hover:bg-amber-500/20"
          }`}
        >
          {pickerOpen ? "Annuler" : "Lier un client"}
        </button>
      </div>
      {pickerOpen ? (
        <div className="mt-3 space-y-2">
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Rechercher un client par nom, courriel ou entreprise…"
            className="w-full rounded border border-brand-800 bg-brand-950 px-3 py-2 text-sm text-white focus:outline-none"
            autoFocus
          />
          {linkError ? (
            <p className="text-xs text-rose-300">{linkError}</p>
          ) : null}
          {loadingCandidates ? (
            <p className="text-xs text-white/40">Chargement…</p>
          ) : filteredCandidates.length === 0 ? (
            <p className="text-xs text-white/40">Aucun client trouvé.</p>
          ) : (
            <ul className="max-h-56 overflow-y-auto rounded border border-brand-800 bg-brand-950/60">
              {filteredCandidates.map((c) => (
                <li key={c.id}>
                  <button
                    type="button"
                    onClick={() => void linkClient(c.id)}
                    className="flex w-full items-start justify-between gap-3 px-3 py-2 text-left hover:bg-white/5"
                  >
                    <span className="text-sm text-white">{c.name}</span>
                    <span className="text-xs text-white/50">
                      {c.email ?? c.company ?? "—"}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      ) : null}
    </div>
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
        <p className="empty-state">
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
          className="flex-1 rounded border border-transparent bg-transparent px-1 py-0.5 text-base font-bold text-white hover:border-brand-800 focus:border-accent-500/50 focus:outline-none"
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
        <span className="badge badge-neutral">
          {sec.billing_kind === "recurring" ? "mensuel" : "initial"}
        </span>
        <button
          type="button"
          onClick={() => onDeleteSection(sec.id)}
          className="btn-ghost btn-xs"
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
                    className="w-full rounded border border-transparent bg-transparent px-1 py-0.5 text-white hover:border-brand-800 focus:border-accent-500/50 focus:outline-none"
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
                    className="btn-ghost btn-xs"
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
  isDevisDev,
  sending,
  onSend,
  onChange
}: {
  status: string;
  isDevisDev: boolean;
  sending: boolean;
  onSend: () => void;
  onChange: (newStatus: string) => void;
}) {
  // Pour les soumissions devis_dev : l'envoi est un vrai envoi email
  // qui passe par /send (génère token + PDF + email + sent_at). Pour
  // les soumissions legacy : ancien comportement « marquer envoyée »
  // (changement de statut seul, sans email).
  const transitions: Array<{ to: string; label: string; cls: string }> = [];
  if (
    !isDevisDev &&
    status === "brouillon"
  ) {
    transitions.push({
      to: "envoyee",
      label: "Marquer envoyée",
      cls: "border-blue-500/40 bg-blue-500/10 text-blue-200"
    });
  }
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

  const showSendButton =
    isDevisDev && (status === "brouillon" || status === "envoyee");

  if (transitions.length === 0 && !showSendButton) return null;
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {showSendButton ? (
        <button
          type="button"
          onClick={onSend}
          disabled={sending}
          className="inline-flex items-center gap-1 rounded-md border border-blue-500/40 bg-blue-500/15 px-2 py-1 text-[10px] font-semibold uppercase tracking-wide text-blue-200 hover:brightness-110 disabled:opacity-60"
        >
          {sending ? (
            <Loader2 className="h-3 w-3 animate-spin" />
          ) : (
            <Send className="h-3 w-3" />
          )}
          {status === "envoyee" ? "Renvoyer au client" : "Envoyer au client"}
        </button>
      ) : null}
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



