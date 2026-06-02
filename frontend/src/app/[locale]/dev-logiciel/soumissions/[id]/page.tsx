"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useParams } from "next/navigation";
import {
  ArrowLeft,
  Briefcase,
  CheckCircle2,
  Copy,
  Download,
  Eye,
  EyeOff,
  FileSignature,
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
  position: number;
  description: string;
  unit: string | null;
  quantity: number;
  cost_per_unit: number;
  unit_price: number;
  total: number;
  notes: string | null;
  // Devis_dev
  item_kind: "recurring_cost" | "feature" | "fixed_cost" | string;
  heures: number | null;
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
    }>;
    frais_fixes_client: Array<{
      id: number | null;
      description: string;
      cost_per_unit: number;
      prix_client: number;
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

export default function SoumissionDetailPage() {
  const params = useParams<{ id: string }>();
  const id = Number(params?.id);
  const { onOpenSidebar } = useDevlogLayout();
  const confirm = useConfirm();

  const [s, setS] = useState<Soumission | null>(null);
  const [sections, setSections] = useState<Section[]>([]);
  const [items, setItems] = useState<Item[]>([]);
  const [totals, setTotals] = useState<Totals>({ initial: 0, monthly: 0 });
  const [preview, setPreview] = useState<DevisPreview | null>(null);
  const [client, setClient] = useState<ClientInfo | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  // adminView pour legacy, ownerView pour devis_dev (sémantique inverse,
  // mais l'UX est la même).
  const [adminView, setAdminView] = useState(true);

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
  async function addDevisItem(kind: "recurring_cost" | "feature" | "fixed_cost") {
    try {
      const payload: Record<string, unknown> = {
        soumission_id: id,
        description:
          kind === "recurring_cost"
            ? "Nouveau coût mensuel"
            : kind === "feature"
              ? "Nouvelle fonctionnalité"
              : "Nouveau frais fixe",
        item_kind: kind
      };
      if (kind === "feature") {
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
      const r = await authedFetch(
        `/api/v1/devlog/soumissions/${id}/pdf`
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
  const featureItems = useMemo(
    () => items.filter((it) => it.item_kind === "feature"),
    [items]
  );
  const fixedItems = useMemo(
    () => items.filter((it) => it.item_kind === "fixed_cost"),
    [items]
  );

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
                {!isDevisDev ? (
                  <span className="rounded bg-amber-500/15 px-2 py-0.5 font-semibold uppercase tracking-wide text-amber-300">
                    Ancien format
                  </span>
                ) : null}
                <span className="text-white/40">
                  Créée le{" "}
                  {new Date(s.created_at).toLocaleDateString("fr-CA")}
                </span>
                {s.sent_at ? (
                  <span className="rounded bg-blue-500/15 px-2 py-0.5 font-semibold text-blue-300">
                    Envoyée le{" "}
                    {new Date(s.sent_at).toLocaleDateString("fr-CA")}
                  </span>
                ) : null}
                {s.signed_at && s.status === "acceptee" ? (
                  <span className="inline-flex items-center gap-1 rounded bg-emerald-500/15 px-2 py-0.5 font-semibold text-emerald-300">
                    <CheckCircle2 className="h-3 w-3" />
                    Signée le{" "}
                    {new Date(s.signed_at).toLocaleDateString("fr-CA")}
                    {s.signed_name ? ` par ${s.signed_name}` : ""}
                  </span>
                ) : null}
                {s.signed_at && s.status === "refusee" ? (
                  <span className="inline-flex items-center gap-1 rounded bg-rose-500/15 px-2 py-0.5 font-semibold text-rose-300">
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

            {/* Encadré client (fix #6) — toujours visible en haut sous le
                header, qu'on soit en vue propriétaire ou client. */}
            <ClientBox
              client={client}
              soumissionId={id}
              hasLead={s.lead_id != null}
              onLinked={() => void loadAll()}
            />

            {isDevisDev ? (
              <DevisDevEditor
                soumission={s}
                preview={preview}
                recurringItems={recurringItems}
                featureItems={featureItems}
                fixedItems={fixedItems}
                ownerView={adminView}
                onPatchSoumission={patchSoumission}
                onAddItem={addDevisItem}
                onPatchItem={patchItem}
                onDeleteItem={deleteItem}
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

        {s ? (
          <EntityDriveSection entityType="DevlogSoumission" entityId={id} />
        ) : null}
      </div>
    </>
  );
}

// ============================================================
// NOUVELLE VUE — devis_dev (refonte mai 2026)
// ============================================================

function DevisDevEditor({
  soumission: s,
  preview,
  recurringItems,
  featureItems,
  fixedItems,
  ownerView,
  onPatchSoumission,
  onAddItem,
  onPatchItem,
  onDeleteItem
}: {
  soumission: Soumission;
  preview: DevisPreview | null;
  recurringItems: Item[];
  featureItems: Item[];
  fixedItems: Item[];
  ownerView: boolean;
  onPatchSoumission: (patch: Partial<Soumission>) => void;
  onAddItem: (kind: "recurring_cost" | "feature" | "fixed_cost") => void;
  onPatchItem: (itemId: number, patch: Partial<Item>) => void;
  onDeleteItem: (itemId: number) => void;
}) {
  const rec = preview?.recurring;
  const init = preview?.initial;
  const invalid = preview?.is_invalid ?? false;

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

        {ownerView ? (
          <>
            {/* Vue propriétaire — liste éditable */}
            {recurringItems.length === 0 ? (
              <p className="rounded border border-dashed border-emerald-500/30 px-3 py-4 text-center text-xs text-white/40">
                Aucun coût mensuel. Clique sur « + Ajouter un coût » pour en
                créer un.
              </p>
            ) : (
              <table className="mt-2 w-full text-xs">
                <thead className="text-[10px] uppercase tracking-wider text-white/40">
                  <tr>
                    <th className="text-left">Description</th>
                    <th className="text-right">Coût mensuel</th>
                    <th className="text-right">Total ligne</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-emerald-500/20">
                  {recurringItems.map((it) => (
                    <tr key={it.id}>
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
                          className="rounded p-1 text-white/30 hover:bg-rose-500/15 hover:text-rose-300"
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
          </>
        ) : (
          // Vue client — liste des inclusions (labels uniquement) +
          // total mensuel en bas, pattern identique à la section 2.
          <DevisDevClientRecurring
            soumission={s}
            recurringItems={recurringItems}
            totalClientAmount={rec?.total_client_amount ?? 0}
            totalClientAmountTaxe={rec?.total_client_amount_taxe ?? 0}
            tpsAmount={rec?.tps_amount ?? 0}
            tvqAmount={rec?.tvq_amount ?? 0}
            tpsPct={rec?.tps_pct ?? 5}
            tvqPct={rec?.tvq_pct ?? 9.975}
            onPatchSoumission={onPatchSoumission}
          />
        )}
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

        {ownerView ? (
          <DevisDevOwnerInitial
            soumission={s}
            preview={preview}
            featureItems={featureItems}
            fixedItems={fixedItems}
            onPatchSoumission={onPatchSoumission}
            onAddItem={onAddItem}
            onPatchItem={onPatchItem}
            onDeleteItem={onDeleteItem}
          />
        ) : (
          <DevisDevClientInitial preview={preview} />
        )}
      </section>
    </>
  );
}

function DevisDevOwnerInitial({
  soumission: s,
  preview,
  featureItems,
  fixedItems,
  onPatchSoumission,
  onAddItem,
  onPatchItem,
  onDeleteItem
}: {
  soumission: Soumission;
  preview: DevisPreview | null;
  featureItems: Item[];
  fixedItems: Item[];
  onPatchSoumission: (patch: Partial<Soumission>) => void;
  onAddItem: (kind: "recurring_cost" | "feature" | "fixed_cost") => void;
  onPatchItem: (itemId: number, patch: Partial<Item>) => void;
  onDeleteItem: (itemId: number) => void;
}) {
  const init = preview?.initial;
  return (
    <div className="space-y-4">
      {/* Gestionnaire — inputs compacts (fix #4, fix #5). Les inputs
          Taux horaire et Heures sont à `w-28`, alignés à gauche dans
          leur cellule grid. Le « Coût manager » est aligné en
          baseline avec eux via `sm:items-end` sur la grille. */}
      <div className="rounded-xl border border-blue-500/20 bg-brand-950/40 p-3">
        <h3 className="text-xs font-bold uppercase tracking-wider text-blue-200">
          Gestionnaire de projet
        </h3>
        <div className="mt-2 grid gap-2 sm:grid-cols-3 sm:items-end">
          <label className="text-xs text-white/70">
            Taux horaire
            <MoneyInput
              value={Number(s.taux_manager_horaire ?? 80)}
              onCommit={(n) =>
                onPatchSoumission({ taux_manager_horaire: n })
              }
              className="mt-1 block w-28 rounded border border-blue-500/30 bg-brand-950 px-1.5 py-1 text-right text-white focus:outline-none"
            />
          </label>
          <label className="text-xs text-white/70">
            Heures
            <HoursInput
              value={Number(s.heures_manager ?? 0)}
              onCommit={(n) => onPatchSoumission({ heures_manager: n })}
              className="mt-1 block w-28 rounded border border-blue-500/30 bg-brand-950 px-1.5 py-1 text-right text-white focus:outline-none"
            />
          </label>
          <div className="text-xs text-white/70">
            Coût manager
            {/* Hauteur identique aux inputs voisins (py-1 + border)
                pour que la valeur s'aligne sur la même ligne. */}
            <p className="mt-1 block w-28 rounded border border-transparent px-1.5 py-1 text-right text-base font-semibold text-white">
              {fmtMoneyShort(Number(init?.cout_manager ?? 0))}
            </p>
          </div>
        </div>
      </div>

      {/* Features */}
      <div className="rounded-xl border border-blue-500/20 bg-brand-950/40 p-3">
        <div className="flex flex-wrap items-end justify-between gap-2">
          <h3 className="text-xs font-bold uppercase tracking-wider text-blue-200">
            Fonctionnalités (features)
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
            Aucune feature. Clique sur « + Ajouter une feature » pour commencer.
          </p>
        ) : (
          <table className="mt-2 w-full text-xs">
            <thead className="text-[10px] uppercase tracking-wider text-white/40">
              <tr>
                <th className="text-left">Feature</th>
                <th className="text-right">Heures</th>
                <th className="text-right">Coût dev</th>
                <th></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-blue-500/20 align-middle">
              {featureItems.map((it) => (
                <tr key={it.id}>
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
                      className="rounded p-1 text-white/30 hover:bg-rose-500/15 hover:text-rose-300"
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
          onClick={() => onAddItem("feature")}
          className="mt-2 inline-flex items-center gap-1.5 rounded text-xs text-white/60 hover:text-white"
        >
          <Plus className="h-3 w-3" />
          Ajouter une feature
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
                <th className="text-left">Description</th>
                <th className="text-right">Coût</th>
                <th></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-blue-500/20 align-middle">
              {fixedItems.map((it) => (
                <tr key={it.id}>
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
                      className="rounded p-1 text-white/30 hover:bg-rose-500/15 hover:text-rose-300"
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

function DevisDevClientRecurring({
  soumission: s,
  recurringItems,
  totalClientAmount,
  totalClientAmountTaxe,
  tpsAmount,
  tvqAmount,
  tpsPct,
  tvqPct,
  onPatchSoumission
}: {
  soumission: Soumission;
  recurringItems: Item[];
  totalClientAmount: number;
  totalClientAmountTaxe: number;
  tpsAmount: number;
  tvqAmount: number;
  tpsPct: number;
  tvqPct: number;
  onPatchSoumission: (patch: Partial<Soumission>) => void;
}) {
  // Notes optionnelles : on garde un state local pour que la frappe
  // dans la textarea ne soit pas perturbée par les reloads de la
  // soumission (même bug que les inputs — pattern FieldText).
  const [focused, setFocused] = useState(false);
  const initial = s.client_recurring_description ?? "";
  const [v, setV] = useState(initial);
  useEffect(() => {
    if (!focused) setV(s.client_recurring_description ?? "");
  }, [s.client_recurring_description, focused]);

  return (
    <div className="space-y-4">
      {recurringItems.length === 0 ? (
        <p className="rounded border border-dashed border-emerald-500/20 px-3 py-4 text-center text-xs text-white/40">
          Aucune inclusion à afficher.
        </p>
      ) : (
        <div>
          <h3 className="text-xs uppercase tracking-wider text-white/40">
            Inclusions
          </h3>
          <ul className="mt-1 divide-y divide-emerald-500/20">
            {recurringItems.map((it) => (
              <li key={it.id} className="py-2 text-sm text-white">
                {it.description || "—"}
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="space-y-1 rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-sm">
        <div className="flex items-center justify-between text-white/80">
          <span>Sous-total mensuel</span>
          <span className="font-semibold text-white">
            {fmtAmount(totalClientAmount)}
          </span>
        </div>
        <div className="flex items-center justify-between text-white/70">
          <span>+ TPS ({tpsPct}%)</span>
          <span>{fmtAmount(tpsAmount)}</span>
        </div>
        <div className="flex items-center justify-between text-white/70">
          <span>+ TVQ ({tvqPct}%)</span>
          <span>{fmtAmount(tvqAmount)}</span>
        </div>
        <div className="flex items-center justify-between border-t border-emerald-500/30 pt-1">
          <span className="text-sm font-semibold text-emerald-200">
            Total mensuel TTC
          </span>
          <span className="text-2xl font-bold text-emerald-200">
            {fmtAmount(totalClientAmountTaxe)}
            {/* Fix #9 — "/mois" lisible sur fond vert : on passe à
                text-white/70 (au lieu de l'ancien emerald-200/70 qui
                disparaissait sur le bg emerald-500/10). */}
            <span className="ml-1 text-sm font-normal text-white/70">
              / mois
            </span>
          </span>
        </div>
      </div>

      <div>
        <label className="text-xs uppercase tracking-wider text-white/40">
          Notes additionnelles (optionnel)
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
    </div>
  );
}

function DevisDevClientInitial({
  preview
}: {
  preview: DevisPreview | null;
}) {
  const init = preview?.initial;
  if (!init) {
    return (
      <p className="py-4 text-center text-xs text-white/40">
        Chargement de la vue client…
      </p>
    );
  }
  return (
    <div className="space-y-4">
      {init.features_client.length === 0 ? (
        <p className="rounded border border-dashed border-blue-500/20 px-3 py-4 text-center text-xs text-white/40">
          Aucune fonctionnalité à afficher.
        </p>
      ) : (
        <div>
          <h3 className="text-xs uppercase tracking-wider text-white/40">
            Fonctionnalités incluses
          </h3>
          <table className="mt-1 w-full text-sm">
            <tbody className="divide-y divide-blue-500/20">
              {init.features_client.map((f) => (
                <tr key={f.id ?? f.description}>
                  <td className="py-2 text-white">{f.description}</td>
                  <td className="py-2 text-right font-semibold text-white">
                    {fmtAmount(f.prix_client)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {init.frais_fixes_client.length > 0 ? (
        <div>
          <h3 className="text-xs uppercase tracking-wider text-white/40">
            Frais fixes
          </h3>
          <table className="mt-1 w-full text-sm">
            <tbody className="divide-y divide-blue-500/20">
              {init.frais_fixes_client.map((f) => (
                <tr key={f.id ?? f.description}>
                  <td className="py-2 text-white">{f.description}</td>
                  <td className="py-2 text-right font-semibold text-white">
                    {fmtAmount(f.prix_client)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}

      <div className="space-y-1 rounded-lg border border-blue-500/40 bg-blue-500/10 px-3 py-2 text-sm">
        <div className="flex items-center justify-between text-white/80">
          <span>Sous-total</span>
          <span className="font-semibold text-white">
            {fmtAmount(init.total_final)}
          </span>
        </div>
        <div className="flex items-center justify-between text-white/70">
          <span>+ TPS ({init.tps_pct}%)</span>
          <span>{fmtAmount(init.tps_amount)}</span>
        </div>
        <div className="flex items-center justify-between text-white/70">
          <span>+ TVQ ({init.tvq_pct}%)</span>
          <span>{fmtAmount(init.tvq_amount)}</span>
        </div>
        <div className="flex items-center justify-between border-t border-blue-500/30 pt-1">
          <span className="text-sm font-semibold text-blue-200">
            Total TTC
          </span>
          <span className="text-2xl font-bold text-blue-200">
            {fmtAmount(init.total_final_taxe)}
          </span>
        </div>
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
  );
}

// Encadré client (fix #6) — affiche nom + email + téléphone +
// adresse du client lié à la soumission. Si aucun client n'est lié,
// affiche un message d'erreur subtil + un bouton « Lier un client »
// qui ouvre un mini-picker. Le picker poste un PATCH sur la
// soumission pour mettre à jour ``client_id``.
function ClientBox({
  client,
  soumissionId,
  hasLead,
  onLinked
}: {
  client: ClientInfo | null;
  soumissionId: number;
  hasLead: boolean;
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

  return (
    <div className="mb-5 rounded-lg border border-amber-500/40 bg-amber-500/10 px-4 py-3 text-sm">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-amber-200">
          {hasLead
            ? "Aucun client lié à cette soumission. Le client sera créé automatiquement à l'envoi (à partir du prospect)."
            : "Aucun client lié à cette soumission. Lier un client pour pouvoir envoyer."}
        </p>
        <button
          type="button"
          onClick={() => setPickerOpen((v) => !v)}
          className="inline-flex items-center gap-1.5 rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-1 text-xs font-semibold text-amber-200 hover:bg-amber-500/20"
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
            className="w-full rounded border border-amber-500/40 bg-brand-950 px-3 py-2 text-sm text-white focus:outline-none"
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
            <ul className="max-h-56 overflow-y-auto rounded border border-amber-500/20 bg-brand-950/60">
              {filteredCandidates.map((c) => (
                <li key={c.id}>
                  <button
                    type="button"
                    onClick={() => void linkClient(c.id)}
                    className="flex w-full items-start justify-between gap-3 px-3 py-2 text-left hover:bg-amber-500/10"
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


