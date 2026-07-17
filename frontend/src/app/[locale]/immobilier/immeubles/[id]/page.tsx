"use client";

import { use, useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  ArrowLeft,
  Banknote,
  Building2,
  Calendar,
  Camera,
  Check,
  ChevronDown,
  ClipboardList,
  DollarSign,
  Home,
  FileDown,
  FileSignature,
  KeyRound,
  Loader2,
  LogOut,
  Mail,
  Pencil,
  Percent,
  Plus,
  Receipt,
  Settings as SettingsIcon,
  Star,
  Trash2,
  TrendingUp,
  Wallet,
  Wrench,
  X
} from "lucide-react";

import { useSearchParams } from "next/navigation";

import { Link, useRouter } from "@/i18n/navigation";
import { authedFetch, getToken } from "@/lib/auth";
import { ImmobilierTopbar, useImmobilierLayout } from "../../layout";
import { EntityDriveSection } from "@/components/drive/EntityDriveSection";
import { ContratGestionTab } from "./contrat-gestion-tab";
import {
  fmtPieces,
  LogementFiche
} from "@/components/immobilier/logement-fiche";
import { LocationsBoard } from "@/components/immobilier/locations-board";
import {
  BailSignature,
  TalFormDropdown
} from "@/components/immobilier/tal-avis";

type Ownership = {
  id: number;
  entreprise_id: number;
  ownership_pct: number;
};

type Immeuble = {
  id: number;
  name: string;
  address: string;
  city?: string | null;
  postal_code?: string | null;
  type: string;
  annee_construction?: number | null;
  nb_logements?: number | null;
  matricule?: string | null;
  urgence_phone?: string | null;
  purchase_price?: number | null;
  purchase_date?: string | null;
  description?: string | null;
  is_active: boolean;
  cover_photo_url?: string | null;
  has_cover_photo?: boolean;
  gestion_externe?: boolean;
  gestionnaire_externe_nom?: string | null;
  gestionnaire_externe_contact?: string | null;
};

type Logement = {
  id: number;
  immeuble_id: number;
  numero: string;
  nb_pieces_decimal?: number | null;
  nb_chambres?: number | null;
  nb_sdb?: number | null;
  superficie_pi2?: number | null;
  etage?: number | null;
  type: string;
  status: string;
  loyer_demande?: number | null;
  notes?: string | null;
};

type Bail = {
  id: number;
  logement_id: number;
  locataire_id: number;
  date_debut: string;
  date_fin: string;
  loyer_mensuel: number;
  status: string;
  signed_at?: string | null;
  signed_by_name?: string | null;
};

type Hypotheque = {
  id: number;
  rang: number;
  preteur: string;
  montant_initial: number;
  balance_actuelle?: number | null;
  // Balance théorique au jour J (tableau d'amortissement, calculée
  // par le backend) — utilisée quand aucune balance n'est saisie.
  balance_calculee?: number | null;
  taux_pct?: number | null;
  type_taux?: string | null;
  amortissement_mois?: number | null;
  paiement_mensuel?: number | null;
  // 'semi' (composition semi-annuelle, standard CA) | 'mensuelle'.
  composition_interets?: string | null;
  date_debut?: string | null;
  date_fin_terme?: string | null;
  status: string;
  notes?: string | null;
};

type Evaluation = {
  id: number;
  kind: string;
  valeur: number;
  date_evaluation: string;
  source?: string | null;
  notes?: string | null;
  // Évaluation de référence pour le calcul d'équité (une seule par
  // immeuble — le backend décoche les autres quand on passe à true).
  is_reference?: boolean;
};

type Maintenance = {
  id: number;
  titre: string;
  priorite: string;
  status: string;
  cout_estime?: number | null;
  cout_reel?: number | null;
  plannifie_pour?: string | null;
};

type Financials = {
  immeuble_id: number;
  nb_logements_actifs: number;
  nb_logements_occupes: number;
  taux_occupation: number;
  // Principal = unités louées ; toutes_unites = potentiel avec vacantes.
  revenu_brut_mensuel: number;
  revenu_brut_annuel: number;
  revenu_brut_mensuel_toutes_unites?: number;
  paiement_hypotheque_mensuel: number;
  balance_hypothecaire: number;
  valeur_actuelle?: number | null;
  valeur_municipale?: number | null;
  purchase_price?: number | null;
  grm?: number | null;
  cap_rate?: number | null;
  // true = cap rate heuristique (NOI ≈ 50 % du brut, aucune dépense
  // récurrente saisie) ; false = NOI réel calculé des dépenses.
  cap_rate_estime?: boolean;
  cash_flow_mensuel?: number | null;
  appreciation_pct?: number | null;
};

type RollupLogement = {
  logement_id: number | null;
  numero: string | null;
  total: number;
  count: number;
};
type RollupImmeuble = {
  immeuble_id: number;
  name: string;
  address: string | null;
  total: number;
  count: number;
  communs_total: number;
  communs_count?: number;
  logements: RollupLogement[];
};

const TABS = [
  { id: "overview", label: "Vue d'ensemble", icon: Building2 },
  { id: "logements", label: "Logements", icon: Home },
  // « Baux & paiements » séparé en deux (retour Phil 2026-07-10) :
  // Paiements = suivi des loyers du mois, Baux & locataires = contrats.
  { id: "paiements", label: "Paiements", icon: Receipt },
  { id: "baux", label: "Baux & locataires", icon: ClipboardList },
  { id: "locations", label: "Locations", icon: KeyRound },
  { id: "hypotheques", label: "Hypothèques", icon: Banknote },
  { id: "evaluations", label: "Évaluations", icon: TrendingUp },
  { id: "cashflow", label: "Cashflow", icon: Wallet },
  { id: "maintenance", label: "Maintenance", icon: Wrench },
  { id: "contrat-gestion", label: "Contrat de gestion", icon: FileSignature }
] as const;

// Onglets masqués quand l'immeuble est en gestion externe : les baux,
// paiements, la maintenance et le contrat de gestion sont gérés par la
// compagnie de gestion externe.
const TABS_MASQUES_GESTION_EXTERNE: ReadonlyArray<
  (typeof TABS)[number]["id"]
> = ["paiements", "baux", "locations", "maintenance", "contrat-gestion"];

function fmtCurrency(n: number | null | undefined): string {
  if (n == null) return "—";
  return new Intl.NumberFormat("fr-CA", {
    style: "currency",
    currency: "CAD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2
  }).format(n);
}

function fmtPct(n: number | null | undefined, decimals = 0): string {
  if (n == null) return "—";
  return `${n.toFixed(decimals)}%`;
}

export default function ImmeubleDetailPage({
  params
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const immeubleId = Number(id);
  const router = useRouter();
  const searchParams = useSearchParams();
  const { entreprises } = useImmobilierLayout();
  // L'onglet vit aussi dans l'URL (?tab=…) : les pages croisées (fiche
  // locataire → onglet Baux, page logement → onglet Logements) peuvent
  // ouvrir directement le bon onglet, et F5 le conserve.
  const [tab, setTab] = useState<(typeof TABS)[number]["id"]>(() => {
    const wanted = searchParams.get("tab");
    return TABS.some((t) => t.id === wanted)
      ? (wanted as (typeof TABS)[number]["id"])
      : "overview";
  });
  // ?bail=<id> (depuis la fiche locataire) : surligne le bail visé dans
  // l'onglet Baux & locataires pour qu'on le repère d'un coup d'œil.
  const highlightBailId = (() => {
    const raw = searchParams.get("bail");
    const n = raw ? Number(raw) : NaN;
    return Number.isFinite(n) ? n : null;
  })();
  const switchTab = useCallback((next: (typeof TABS)[number]["id"]) => {
    setTab(next);
    // replaceState : pas de re-render Next, pas d'entrée d'historique par
    // clic d'onglet — le back du navigateur reste « quitter la fiche ».
    const url = new URL(window.location.href);
    if (next === "overview") url.searchParams.delete("tab");
    else url.searchParams.set("tab", next);
    window.history.replaceState(window.history.state, "", url.toString());
  }, []);
  const [immeuble, setImmeuble] = useState<Immeuble | null>(null);
  const [ownerships, setOwnerships] = useState<Ownership[]>([]);
  const [showDelete, setShowDelete] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [savingOwner, setSavingOwner] = useState(false);
  const [actionErr, setActionErr] = useState<string | null>(null);
  const [photoBusy, setPhotoBusy] = useState(false);
  const [photoVer, setPhotoVer] = useState(0);
  const fileRef = useRef<HTMLInputElement | null>(null);
  const [showBon, setShowBon] = useState(false);
  const [bonForm, setBonForm] = useState({ titre: "", description: "", logement: "" });
  const [bonBusy, setBonBusy] = useState(false);
  const [bonResult, setBonResult] = useState<{
    bon_id: number;
    reference: string;
    client_name: string | null;
    client_created: boolean;
  } | null>(null);
  const [showEdit, setShowEdit] = useState(false);
  const [editBusy, setEditBusy] = useState(false);
  const [editForm, setEditForm] = useState({
    name: "",
    address: "",
    city: "",
    postal_code: "",
    type: "residentiel",
    annee_construction: "",
    nb_logements: "",
    purchase_price: "",
    urgence_phone: "",
    gestion_externe: false,
    gestionnaire_externe_nom: "",
    gestionnaire_externe_contact: ""
  });
  const [financials, setFinancials] = useState<Financials | null>(null);
  const [logements, setLogements] = useState<Logement[] | null>(null);
  const [baux, setBaux] = useState<Bail[] | null>(null);
  const [hypotheques, setHypotheques] = useState<Hypotheque[] | null>(null);
  const [evaluations, setEvaluations] = useState<Evaluation[] | null>(null);
  const [maintenance, setMaintenance] = useState<Maintenance[] | null>(null);
  const [rollup, setRollup] = useState<RollupImmeuble | null>(null);
  const [locataires, setLocataires] = useState<
    { id: number; full_name: string }[]
  >([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    authedFetch("/api/v1/immobilier/locataires")
      .then((r) => (r.ok ? r.json() : []))
      .then((d) => {
        if (!cancelled) setLocataires(Array.isArray(d) ? d : []);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!immeubleId) return;
    let cancelled = false;
    async function loadAll() {
      try {
        const [imm, fin, logs, bx, hyp, evals, maint, own] =
          await Promise.all([
            authedFetch(`/api/v1/immobilier/immeubles/${immeubleId}`),
            authedFetch(
              `/api/v1/immobilier/immeubles/${immeubleId}/financials`
            ),
            authedFetch(
              `/api/v1/immobilier/immeubles/${immeubleId}/logements`
            ),
            authedFetch(`/api/v1/immobilier/immeubles/${immeubleId}/baux`),
            authedFetch(
              `/api/v1/immobilier/immeubles/${immeubleId}/hypotheques`
            ),
            authedFetch(
              `/api/v1/immobilier/immeubles/${immeubleId}/evaluations`
            ),
            authedFetch(
              `/api/v1/immobilier/immeubles/${immeubleId}/maintenance`
            ),
            authedFetch(
              `/api/v1/immobilier/immeubles/${immeubleId}/ownerships`
            )
          ]);
        if (cancelled) return;
        if (!imm.ok) throw new Error(`Immeuble HTTP ${imm.status}`);
        setImmeuble((await imm.json()) as Immeuble);
        if (fin.ok) setFinancials((await fin.json()) as Financials);
        if (logs.ok) setLogements((await logs.json()) as Logement[]);
        if (bx.ok) setBaux((await bx.json()) as Bail[]);
        if (hyp.ok) setHypotheques((await hyp.json()) as Hypotheque[]);
        if (evals.ok) setEvaluations((await evals.json()) as Evaluation[]);
        if (maint.ok) setMaintenance((await maint.json()) as Maintenance[]);
        if (own.ok) setOwnerships((await own.json()) as Ownership[]);
        // Dépenses de maintenance ($/an) de cet immeuble — bons internes.
        try {
          const roll = await authedFetch(
            `/api/v1/immobilier/maintenance-rollup?immeuble_id=${immeubleId}`
          );
          if (roll.ok && !cancelled) {
            const arr = (await roll.json()) as RollupImmeuble[];
            setRollup(arr[0] || null);
          }
        } catch {
          /* ignore */
        }
      } catch (err) {
        if (!cancelled) setError((err as Error).message);
      }
    }
    void loadAll();
    return () => {
      cancelled = true;
    };
  }, [immeubleId]);

  const ownerId = ownerships[0]?.entreprise_id ?? null;

  const gestionExterne = !!immeuble?.gestion_externe;
  const visibleTabs = useMemo(
    () =>
      gestionExterne
        ? TABS.filter((t) => !TABS_MASQUES_GESTION_EXTERNE.includes(t.id))
        : TABS,
    [gestionExterne]
  );

  // Si l'onglet actif devient masqué (gestion externe), on retombe sur
  // la vue d'ensemble.
  useEffect(() => {
    if (gestionExterne && TABS_MASQUES_GESTION_EXTERNE.includes(tab)) {
      switchTab("overview");
    }
  }, [gestionExterne, tab, switchTab]);

  // Recharge les KPIs financiers (hypothèques, cash flow) après une mutation.
  const refreshFinancials = useCallback(async () => {
    try {
      const res = await authedFetch(
        `/api/v1/immobilier/immeubles/${immeubleId}/financials`
      );
      if (res.ok) setFinancials((await res.json()) as Financials);
    } catch {
      /* silencieux */
    }
  }, [immeubleId]);

  // Évaluation retenue pour l'équité : celle marquée « référence »
  // prime ; sinon la plus récente (aligné backend /financials).
  const lastEval = useMemo(() => {
    if (!evaluations || evaluations.length === 0) return null;
    const ref = evaluations.find((e) => e.is_reference);
    if (ref) return ref;
    return [...evaluations].sort(
      (a, b) =>
        b.date_evaluation.localeCompare(a.date_evaluation) || b.id - a.id
    )[0];
  }, [evaluations]);

  // Balance = saisie > calculée (amortissement au jour J, backend) >
  // montant initial — même priorité que le backend (balance_effective).
  const balanceHypoActives = useMemo(
    () =>
      (hypotheques || [])
        .filter((h) => h.status === "active")
        .reduce(
          (s, h) =>
            s +
            (h.balance_actuelle ??
              h.balance_calculee ??
              h.montant_initial ??
              0),
          0
        ),
    [hypotheques]
  );

  const equite = lastEval ? lastEval.valeur - balanceHypoActives : null;

  async function onChangeOwner(entrepriseId: number) {
    if (!entrepriseId || entrepriseId === ownerId) return;
    setSavingOwner(true);
    setActionErr(null);
    try {
      const res = await authedFetch(
        `/api/v1/immobilier/immeubles/${immeubleId}/owner`,
        { method: "PUT", body: JSON.stringify({ entreprise_id: entrepriseId }) }
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setOwnerships((await res.json()) as Ownership[]);
    } catch (e) {
      setActionErr(`Changement de propriétaire échoué : ${(e as Error).message}`);
    } finally {
      setSavingOwner(false);
    }
  }

  async function onDelete() {
    setDeleting(true);
    setActionErr(null);
    try {
      const res = await authedFetch(
        `/api/v1/immobilier/immeubles/${immeubleId}`,
        { method: "DELETE" }
      );
      if (!res.ok && res.status !== 204)
        throw new Error(`HTTP ${res.status}`);
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      router.replace("/immobilier/immeubles" as any);
    } catch (e) {
      setActionErr(`Suppression échouée : ${(e as Error).message}`);
      setDeleting(false);
    }
  }

  async function uploadPhoto(file: File) {
    setPhotoBusy(true);
    setActionErr(null);
    try {
      const fd = new FormData();
      fd.append("file", file);
      const res = await authedFetch(
        `/api/v1/immobilier/immeubles/${immeubleId}/cover-photo`,
        { method: "POST", body: fd }
      );
      if (!res.ok)
        throw new Error((await res.text()).slice(0, 160) || `HTTP ${res.status}`);
      setImmeuble((await res.json()) as Immeuble);
      setPhotoVer((v) => v + 1);
    } catch (e) {
      setActionErr(`Photo : ${(e as Error).message}`);
    } finally {
      setPhotoBusy(false);
    }
  }

  async function removePhoto() {
    setPhotoBusy(true);
    setActionErr(null);
    try {
      const res = await authedFetch(
        `/api/v1/immobilier/immeubles/${immeubleId}/cover-photo`,
        { method: "DELETE" }
      );
      if (!res.ok && res.status !== 204)
        throw new Error(`HTTP ${res.status}`);
      setImmeuble((prev) =>
        prev ? { ...prev, has_cover_photo: false, cover_photo_url: null } : prev
      );
      setPhotoVer((v) => v + 1);
    } catch (e) {
      setActionErr(`Photo : ${(e as Error).message}`);
    } finally {
      setPhotoBusy(false);
    }
  }

  async function createBon() {
    if (!bonForm.titre.trim()) return;
    setBonBusy(true);
    setActionErr(null);
    try {
      const res = await authedFetch(
        `/api/v1/immobilier/immeubles/${immeubleId}/bon-travail`,
        {
          method: "POST",
          body: JSON.stringify({
            titre: bonForm.titre.trim(),
            description: bonForm.description.trim() || null,
            logement: bonForm.logement.trim() || null
          })
        }
      );
      if (!res.ok)
        throw new Error((await res.text()).slice(0, 200) || `HTTP ${res.status}`);
      setBonResult(
        (await res.json()) as {
          bon_id: number;
          reference: string;
          client_name: string | null;
          client_created: boolean;
        }
      );
    } catch (e) {
      setActionErr(`Bon de travail : ${(e as Error).message}`);
    } finally {
      setBonBusy(false);
    }
  }

  function openEdit() {
    if (!immeuble) return;
    setEditForm({
      name: immeuble.name || "",
      address: immeuble.address || "",
      city: immeuble.city || "",
      postal_code: immeuble.postal_code || "",
      type: immeuble.type || "residentiel",
      annee_construction: immeuble.annee_construction
        ? String(immeuble.annee_construction)
        : "",
      nb_logements: immeuble.nb_logements ? String(immeuble.nb_logements) : "",
      purchase_price: immeuble.purchase_price
        ? String(immeuble.purchase_price)
        : "",
      urgence_phone: immeuble.urgence_phone || "",
      gestion_externe: !!immeuble.gestion_externe,
      gestionnaire_externe_nom: immeuble.gestionnaire_externe_nom || "",
      gestionnaire_externe_contact: immeuble.gestionnaire_externe_contact || ""
    });
    setShowEdit(true);
  }

  async function saveEdit() {
    if (!editForm.address.trim()) {
      setActionErr("L'adresse est requise.");
      return;
    }
    setEditBusy(true);
    setActionErr(null);
    try {
      const body: Record<string, unknown> = {
        name: editForm.name.trim() || null,
        address: editForm.address.trim(),
        city: editForm.city.trim() || null,
        postal_code: editForm.postal_code.trim() || null,
        type: editForm.type,
        annee_construction: editForm.annee_construction
          ? Number(editForm.annee_construction)
          : null,
        nb_logements: editForm.nb_logements
          ? Number(editForm.nb_logements)
          : null,
        purchase_price: editForm.purchase_price
          ? Number(editForm.purchase_price)
          : null,
        urgence_phone: editForm.urgence_phone.trim() || null,
        gestion_externe: editForm.gestion_externe,
        gestionnaire_externe_nom: editForm.gestion_externe
          ? editForm.gestionnaire_externe_nom.trim() || null
          : null,
        gestionnaire_externe_contact: editForm.gestion_externe
          ? editForm.gestionnaire_externe_contact.trim() || null
          : null
      };
      const res = await authedFetch(
        `/api/v1/immobilier/immeubles/${immeubleId}`,
        { method: "PATCH", body: JSON.stringify(body) }
      );
      if (!res.ok)
        throw new Error((await res.text()).slice(0, 200) || `HTTP ${res.status}`);
      setImmeuble((await res.json()) as Immeuble);
      setShowEdit(false);
    } catch (e) {
      setActionErr(`Modification échouée : ${(e as Error).message}`);
    } finally {
      setEditBusy(false);
    }
  }

  if (error) {
    return (
      <>
        <ImmobilierTopbar
          breadcrumbs={[
            { label: "Gestion immobilière", href: "/immobilier" },
            { label: "Immeuble" }
          ]}
        />
        <div className="p-6">
          <p className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-300">
            {error}
          </p>
        </div>
      </>
    );
  }

  if (!immeuble) {
    return (
      <>
        <ImmobilierTopbar
          breadcrumbs={[
            { label: "Gestion immobilière", href: "/immobilier" },
            { label: "Immeuble" }
          ]}
        />
        <div className="flex items-center gap-2 p-6 text-xs text-white/50">
          <Loader2 className="h-3.5 w-3.5 animate-spin" /> Chargement…
        </div>
      </>
    );
  }

  return (
    <>
      <ImmobilierTopbar
        breadcrumbs={[
          { label: "Gestion immobilière", href: "/immobilier" },
          { label: "Immeubles", href: "/immobilier/immeubles" },
          { label: immeuble.name }
        ]}
      />

      {/* pb-28 : le contenu ne doit pas passer sous le bouton Aide flottant */}
      <div className="p-4 pb-28 lg:p-6 lg:pb-28">
        <EntityDriveSection
          entityType="Immeuble"
          entityId={immeuble.id}
          pole="Gestion immobilière"
          label="Immeuble"
          route="/immobilier/immeubles/[id]"
        />
        <Link
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          href={"/immobilier/immeubles" as any}
          className="inline-flex items-center text-xs text-white/50 hover:text-accent-500"
        >
          <ArrowLeft className="mr-1 h-3.5 w-3.5" /> Liste des immeubles
        </Link>

        <header className="mt-4 flex flex-wrap items-start gap-4">
          <div className="flex flex-col items-center gap-1">
            <button
              type="button"
              onClick={() => fileRef.current?.click()}
              disabled={photoBusy}
              title="Changer la photo de l'immeuble"
              className="group relative h-16 w-16 flex-shrink-0 overflow-hidden rounded-xl bg-accent-500/15 text-accent-500"
            >
              {immeuble.has_cover_photo || immeuble.cover_photo_url ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  src={
                    immeuble.has_cover_photo
                      ? `/api/v1/immobilier/immeubles/${immeubleId}/cover-photo?t=${getToken() || ""}&v=${photoVer}`
                      : (immeuble.cover_photo_url as string)
                  }
                  alt={immeuble.name}
                  className="h-full w-full object-cover"
                />
              ) : (
                <span className="flex h-full w-full items-center justify-center">
                  <Building2 className="h-7 w-7" />
                </span>
              )}
              <span className="absolute inset-0 flex items-center justify-center bg-black/50 opacity-0 transition group-hover:opacity-100">
                {photoBusy ? (
                  <Loader2 className="h-5 w-5 animate-spin text-white" />
                ) : (
                  <Camera className="h-5 w-5 text-white" />
                )}
              </span>
            </button>
            {immeuble.has_cover_photo || immeuble.cover_photo_url ? (
              <button
                type="button"
                onClick={() => void removePhoto()}
                disabled={photoBusy}
                className="text-[10px] text-white/50 hover:text-rose-300"
              >
                Retirer
              </button>
            ) : null}
            <input
              ref={fileRef}
              type="file"
              accept="image/jpeg,image/png,image/webp,image/heic,image/heif"
              className="hidden"
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) void uploadPhoto(f);
                e.target.value = "";
              }}
            />
          </div>
          <div className="min-w-0 flex-1">
            <h1 className="text-2xl font-bold text-white">{immeuble.name}</h1>
            <p className="mt-1 text-sm text-white/60">
              {immeuble.address}
              {immeuble.city ? `, ${immeuble.city}` : ""}
              {immeuble.postal_code ? ` (${immeuble.postal_code})` : ""}
            </p>
            <div className="mt-2 flex flex-wrap items-center gap-2 text-[11px]">
              <span className="badge badge-neutral font-mono">
                {immeuble.type}
              </span>
              {immeuble.annee_construction ? (
                <span className="badge badge-neutral">
                  {immeuble.annee_construction}
                </span>
              ) : null}
              {immeuble.matricule ? (
                <span className="badge badge-neutral font-mono">
                  Matricule {immeuble.matricule}
                </span>
              ) : null}
              {!immeuble.is_active ? (
                <span className="badge badge-amber">
                  Inactif
                </span>
              ) : null}
              {gestionExterne ? (
                <span className="badge badge-sky">Gestion externe</span>
              ) : null}
            </div>
          </div>

          {/* Actions : propriétaire + suppression */}
          <div className="flex flex-col items-stretch gap-2 sm:items-end">
            <label className="flex items-center gap-2 text-[11px] font-semibold text-white/60">
              Propriétaire
              <select
                value={ownerId ?? ""}
                onChange={(e) => void onChangeOwner(Number(e.target.value))}
                disabled={savingOwner || entreprises.length === 0}
                className="rounded-lg border border-brand-800 bg-brand-900 px-2 py-1 text-xs font-semibold text-white outline-none focus:border-accent-500 disabled:opacity-50"
              >
                <option value="" disabled className="bg-brand-950 text-white">
                  — choisir —
                </option>
                {entreprises.map((e) => (
                  <option
                    key={e.id}
                    value={e.id}
                    className="bg-brand-950 text-white"
                  >
                    {e.name}
                  </option>
                ))}
              </select>
              {savingOwner ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin text-accent-500" />
              ) : null}
            </label>
            <ActionsMenu
              onEdit={openEdit}
              onDelete={() => setShowDelete(true)}
            />
          </div>
        </header>

        {actionErr ? (
          <p className="mt-3 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">
            {actionErr}
          </p>
        ) : null}

        {/* KPIs financiers */}
        {financials ? (
          <section className="mt-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <Kpi
              label="Revenu mensuel"
              value={
                <span className="flex flex-wrap items-baseline gap-x-2">
                  {fmtCurrency(financials.revenu_brut_mensuel)}
                  {financials.revenu_brut_mensuel_toutes_unites != null ? (
                    <span
                      className="text-xs font-normal text-white/50"
                      title="Potentiel toutes unités (louées + vacantes au loyer demandé)"
                    >
                      {fmtCurrency(
                        financials.revenu_brut_mensuel_toutes_unites
                      )}{" "}
                      toutes unités
                    </span>
                  ) : null}
                </span>
              }
              sub={
                <span className="flex flex-wrap items-baseline gap-x-2">
                  {fmtCurrency(financials.revenu_brut_annuel)} / an
                  {financials.revenu_brut_mensuel_toutes_unites != null ? (
                    <span
                      className="text-[11px] text-white/40"
                      title="Potentiel annuel toutes unités"
                    >
                      {fmtCurrency(
                        financials.revenu_brut_mensuel_toutes_unites * 12
                      )}{" "}
                      toutes unités
                    </span>
                  ) : null}
                </span>
              }
              icon={DollarSign}
              tone="emerald"
            />
            <Kpi
              label="Cash flow mensuel"
              value={fmtCurrency(financials.cash_flow_mensuel)}
              sub={`Hyp. ${fmtCurrency(financials.paiement_hypotheque_mensuel)}`}
              icon={Banknote}
              tone={
                (financials.cash_flow_mensuel || 0) >= 0 ? "emerald" : "rose"
              }
            />
            {/* Tuile « Cap rate » retirée (retour Phil 2026-07-10). */}
            <Kpi
              label="Occupation"
              value={`${(financials.taux_occupation * 100).toFixed(0)}%`}
              sub={`${financials.nb_logements_occupes}/${financials.nb_logements_actifs} occupés`}
              icon={Home}
              tone={financials.taux_occupation >= 0.9 ? "emerald" : "amber"}
            />
            <Kpi
              label="Équité"
              value={fmtCurrency(equite)}
              sub={
                lastEval
                  ? `${lastEval.is_reference ? "Réf." : "Valeur"} ${fmtCurrency(lastEval.valeur)} − hyp. ${fmtCurrency(balanceHypoActives)}`
                  : "Aucune évaluation"
              }
              icon={TrendingUp}
              tone={(equite ?? 0) >= 0 ? "emerald" : "rose"}
            />
          </section>
        ) : null}

        {/* Tabs */}
        <nav
          className="mt-6 flex items-center gap-1 overflow-x-auto [-ms-overflow-style:none] [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
          style={{ borderBottom: "1px solid #25252d" }}
        >
          {visibleTabs.map((t) => {
            const active = tab === t.id;
            const Icon = t.icon;
            return (
              <button
                key={t.id}
                type="button"
                onClick={() => switchTab(t.id)}
                className={`-mb-px inline-flex items-center gap-1.5 border-b-2 px-4 py-2 text-sm font-medium transition ${
                  active
                    ? "border-accent-500 text-accent-500"
                    : "border-transparent text-white/60 hover:text-white"
                }`}
              >
                <Icon className="h-4 w-4" />
                {t.label}
              </button>
            );
          })}
        </nav>

        <div className="mt-5">
          {tab === "overview" ? (
            <OverviewTab
              immeuble={immeuble}
              financials={financials}
              logementsCount={logements?.length || 0}
              baux={baux}
              logements={logements}
              hypotheques={hypotheques}
              evaluations={evaluations}
            />
          ) : null}
          {tab === "logements" ? (
            <LogementsTab
              immeubleId={immeubleId}
              list={logements}
              baux={baux}
              setList={setLogements}
            />
          ) : null}
          {tab === "paiements" ? (
            <PaiementsMoisSection immeubleId={immeubleId} />
          ) : null}
          {tab === "baux" ? (
            <BauxTab
              immeubleId={immeubleId}
              list={baux}
              logements={logements}
              locataires={locataires}
              highlightBailId={highlightBailId}
              onRelocation={async (b) => {
                setActionErr(null);
                const r = await authedFetch(
                  "/api/v1/immobilier/locations",
                  {
                    method: "POST",
                    body: JSON.stringify({
                      logement_id: b.logement_id,
                      bail_id: b.id
                    })
                  }
                );
                if (!r.ok) {
                  const t = await r.text();
                  setActionErr(
                    t.includes("déjà en cours")
                      ? "Une relocation est déjà en cours pour ce logement — voir l'onglet Locations."
                      : t.slice(0, 200) || `HTTP ${r.status}`
                  );
                  return;
                }
                switchTab("locations");
              }}
            />
          ) : null}
          {tab === "locations" ? (
            <LocationsBoard immeubleId={immeubleId} />
          ) : null}
          {tab === "hypotheques" ? (
            <HypothequesTab
              immeubleId={immeubleId}
              list={hypotheques}
              setList={setHypotheques}
              onMutated={() => void refreshFinancials()}
            />
          ) : null}
          {tab === "evaluations" ? (
            <EvaluationsTab
              immeubleId={immeubleId}
              list={evaluations}
              setList={setEvaluations}
              purchasePrice={immeuble.purchase_price ?? null}
              balanceHypoActives={balanceHypoActives}
              onMutated={() => void refreshFinancials()}
            />
          ) : null}
          {tab === "cashflow" ? (
            <CashflowTab
              immeubleId={immeubleId}
              baux={baux}
              logements={logements}
              hypotheques={hypotheques}
              onMutated={() => void refreshFinancials()}
            />
          ) : null}
          {tab === "maintenance" ? (
            <>
              {/* Bouton déplacé du menu « Actions » (retour Phil) : le bon
                  de travail est une action de maintenance. */}
              <div className="mb-3 flex justify-end">
                <button
                  type="button"
                  onClick={() => {
                    setBonResult(null);
                    setBonForm({ titre: "", description: "", logement: "" });
                    setShowBon(true);
                  }}
                  className="btn-outline-accent btn-sm"
                  title="Créer un bon de travail (réparation) dans le volet Construction"
                >
                  <Wrench className="h-3.5 w-3.5" /> + Bon de travail
                </button>
              </div>
              <MaintenanceTab list={maintenance} rollup={rollup} />
            </>
          ) : null}
          {tab === "contrat-gestion" ? (
            <ContratGestionTab immeubleId={immeubleId} />
          ) : null}
        </div>
      </div>

      {showDelete ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4 backdrop-blur-sm">
          <div className="w-full max-w-md rounded-2xl border border-rose-500/30 bg-brand-950 shadow-2xl">
            <div className="flex items-center justify-between border-b border-brand-800 px-5 py-3">
              <h2 className="flex items-center gap-2 text-sm font-bold uppercase tracking-wider text-rose-300">
                <AlertTriangle className="h-4 w-4" /> Supprimer l&apos;immeuble
              </h2>
              <button
                type="button"
                onClick={() => setShowDelete(false)}
                disabled={deleting}
                className="btn-ghost btn-xs"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
            <div className="space-y-3 p-5 text-sm text-white/80">
              <p>
                Tu vas supprimer{" "}
                <strong className="text-white">{immeuble.name}</strong>.
              </p>
              <p className="rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">
                ⚠ Action irréversible : tous les logements, baux, hypothèques,
                évaluations et ordres de maintenance de cet immeuble seront
                supprimés aussi.
              </p>
            </div>
            <div className="flex items-center justify-end gap-2 border-t border-brand-800 px-5 py-3">
              <button
                type="button"
                onClick={() => setShowDelete(false)}
                disabled={deleting}
                className="btn-secondary btn-sm"
              >
                Annuler
              </button>
              <button
                type="button"
                onClick={() => void onDelete()}
                disabled={deleting}
                className="btn-danger btn-sm disabled:opacity-50"
              >
                {deleting ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Trash2 className="h-3.5 w-3.5" />
                )}
                Supprimer définitivement
              </button>
            </div>
          </div>
        </div>
      ) : null}

      {showBon ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4 backdrop-blur-sm">
          <div className="w-full max-w-md rounded-2xl border border-amber-500/30 bg-brand-950 shadow-2xl">
            <div className="flex items-center justify-between border-b border-brand-800 px-5 py-3">
              <h2 className="flex items-center gap-2 text-sm font-bold uppercase tracking-wider text-amber-300">
                <Wrench className="h-4 w-4" /> Bon de travail
              </h2>
              <button
                type="button"
                onClick={() => setShowBon(false)}
                className="btn-ghost btn-xs"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            {bonResult ? (
              <div className="space-y-3 p-5 text-sm text-white/80">
                <div className="rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-4 py-3 text-emerald-200">
                  <p className="font-semibold">
                    Bon {bonResult.reference} créé ✅
                  </p>
                  <p className="mt-1 text-xs">
                    Envoyé dans le volet Construction (brouillon).
                    {bonResult.client_name
                      ? bonResult.client_created
                        ? ` Client « ${bonResult.client_name} » créé.`
                        : ` Client « ${bonResult.client_name} » réutilisé.`
                      : " Aucune compagnie propriétaire — pense à choisir un client dans le bon."}
                  </p>
                </div>
                <Link
                  // eslint-disable-next-line @typescript-eslint/no-explicit-any
                  href={`/app/bons/${bonResult.bon_id}` as any}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-amber-400/30 bg-amber-500/15 px-4 py-2 text-xs font-semibold text-amber-100 hover:bg-amber-500/25"
                >
                  Ouvrir dans Construction →
                </Link>
              </div>
            ) : (
              <>
                <div className="space-y-3 p-5">
                  <p className="text-xs text-white/60">
                    Crée un bon de travail (réparation) dans le volet
                    Construction. La compagnie propriétaire devient client si
                    elle ne l&apos;est pas déjà. Un responsable construction
                    reprend ensuite (estimé, envoi, signature).
                  </p>
                  <input
                    value={bonForm.titre}
                    onChange={(e) =>
                      setBonForm((f) => ({ ...f, titre: e.target.value }))
                    }
                    placeholder="Titre (ex. Réparation toiture)"
                    className="w-full rounded-lg border border-brand-800 bg-brand-900 px-3 py-2 text-sm text-white outline-none focus:border-amber-300"
                  />
                  <input
                    value={bonForm.logement}
                    onChange={(e) =>
                      setBonForm((f) => ({ ...f, logement: e.target.value }))
                    }
                    placeholder="Logement concerné (optionnel)"
                    className="w-full rounded-lg border border-brand-800 bg-brand-900 px-3 py-2 text-sm text-white outline-none focus:border-amber-300"
                  />
                  <textarea
                    value={bonForm.description}
                    onChange={(e) =>
                      setBonForm((f) => ({ ...f, description: e.target.value }))
                    }
                    rows={4}
                    placeholder="Description des travaux…"
                    className="w-full rounded-lg border border-brand-800 bg-brand-900 px-3 py-2 text-sm text-white outline-none focus:border-amber-300"
                  />
                </div>
                <div className="flex items-center justify-end gap-2 border-t border-brand-800 px-5 py-3">
                  <button
                    type="button"
                    onClick={() => setShowBon(false)}
                    className="btn-secondary btn-sm"
                  >
                    Annuler
                  </button>
                  <button
                    type="button"
                    onClick={() => void createBon()}
                    disabled={bonBusy || !bonForm.titre.trim()}
                    className="inline-flex items-center gap-1.5 rounded-lg border border-amber-400/30 bg-amber-500/15 px-4 py-2 text-xs font-semibold text-amber-100 hover:bg-amber-500/25 disabled:opacity-50"
                  >
                    {bonBusy ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    ) : (
                      <Wrench className="h-3.5 w-3.5" />
                    )}
                    Créer le bon
                  </button>
                </div>
              </>
            )}
          </div>
        </div>
      ) : null}

      {showEdit ? (
        <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/70 p-4 backdrop-blur-sm">
          <div className="my-8 w-full max-w-lg rounded-2xl border border-brand-800 bg-brand-950 shadow-2xl">
            <div className="flex items-center justify-between border-b border-brand-800 px-5 py-3">
              <h2 className="flex items-center gap-2 text-sm font-bold uppercase tracking-wider text-accent-500">
                <Pencil className="h-4 w-4" /> Modifier l&apos;immeuble
              </h2>
              <button
                type="button"
                onClick={() => setShowEdit(false)}
                disabled={editBusy}
                className="btn-ghost btn-xs"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
            <div className="space-y-3 p-5">
              <EditField label="Nom (optionnel)">
                <input
                  value={editForm.name}
                  onChange={(e) =>
                    setEditForm((f) => ({ ...f, name: e.target.value }))
                  }
                  className="w-full rounded-lg border border-brand-800 bg-brand-900 px-3 py-2 text-sm text-white outline-none focus:border-accent-500"
                  placeholder="Laisser vide = adresse"
                />
              </EditField>
              <EditField label="Adresse *">
                <input
                  value={editForm.address}
                  onChange={(e) =>
                    setEditForm((f) => ({ ...f, address: e.target.value }))
                  }
                  className="w-full rounded-lg border border-brand-800 bg-brand-900 px-3 py-2 text-sm text-white outline-none focus:border-accent-500"
                />
              </EditField>
              <div className="grid grid-cols-2 gap-3">
                <EditField label="Ville">
                  <input
                    value={editForm.city}
                    onChange={(e) =>
                      setEditForm((f) => ({ ...f, city: e.target.value }))
                    }
                    className="w-full rounded-lg border border-brand-800 bg-brand-900 px-3 py-2 text-sm text-white outline-none focus:border-accent-500"
                  />
                </EditField>
                <EditField label="Code postal">
                  <input
                    value={editForm.postal_code}
                    onChange={(e) =>
                      setEditForm((f) => ({
                        ...f,
                        postal_code: e.target.value
                      }))
                    }
                    className="w-full rounded-lg border border-brand-800 bg-brand-900 px-3 py-2 text-sm text-white outline-none focus:border-accent-500"
                  />
                </EditField>
              </div>
              <EditField label="Numéro d'urgence (concierge / gestionnaire)">
                <input
                  type="tel"
                  value={editForm.urgence_phone}
                  onChange={(e) =>
                    setEditForm((f) => ({
                      ...f,
                      urgence_phone: e.target.value
                    }))
                  }
                  placeholder="ex. 514 555-0123"
                  className="w-full rounded-lg border border-brand-800 bg-brand-900 px-3 py-2 text-sm text-white outline-none focus:border-accent-500"
                />
                <p className="mt-1 text-[11px] text-white/50">
                  Appelé en priorité par Léa lors d'une urgence locataire
                  (dégât d'eau, effraction, feu…). À défaut, repli sur le
                  numéro de garde global.
                </p>
              </EditField>
              <div className="grid grid-cols-2 gap-3">
                <EditField label="Type">
                  <select
                    value={editForm.type}
                    onChange={(e) =>
                      setEditForm((f) => ({ ...f, type: e.target.value }))
                    }
                    className="w-full rounded-lg border border-brand-800 bg-brand-900 px-3 py-2 text-sm text-white outline-none focus:border-accent-500"
                  >
                    {["residentiel", "commercial", "mixte", "unifamilial", "autre"].map(
                      (t) => (
                        <option key={t} value={t} className="bg-brand-950 text-white">
                          {t}
                        </option>
                      )
                    )}
                  </select>
                </EditField>
                <EditField label="Année">
                  <input
                    type="number"
                    value={editForm.annee_construction}
                    onChange={(e) =>
                      setEditForm((f) => ({
                        ...f,
                        annee_construction: e.target.value
                      }))
                    }
                    className="w-full rounded-lg border border-brand-800 bg-brand-900 px-3 py-2 text-sm text-white outline-none focus:border-accent-500"
                  />
                </EditField>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <EditField label="Nb logements">
                  <input
                    type="number"
                    value={editForm.nb_logements}
                    onChange={(e) =>
                      setEditForm((f) => ({
                        ...f,
                        nb_logements: e.target.value
                      }))
                    }
                    className="w-full rounded-lg border border-brand-800 bg-brand-900 px-3 py-2 text-sm text-white outline-none focus:border-accent-500"
                  />
                </EditField>
                <EditField label="Prix d'achat">
                  <input
                    type="number"
                    value={editForm.purchase_price}
                    onChange={(e) =>
                      setEditForm((f) => ({
                        ...f,
                        purchase_price: e.target.value
                      }))
                    }
                    className="w-full rounded-lg border border-brand-800 bg-brand-900 px-3 py-2 text-sm text-white outline-none focus:border-accent-500"
                  />
                </EditField>
              </div>
              <div className="rounded-lg border border-sky-400/30 bg-sky-500/10 p-3">
                <label className="flex cursor-pointer items-center gap-2 text-sm text-white">
                  <input
                    type="checkbox"
                    checked={editForm.gestion_externe}
                    onChange={(e) =>
                      setEditForm((f) => ({
                        ...f,
                        gestion_externe: e.target.checked
                      }))
                    }
                    className="h-4 w-4 accent-sky-400"
                  />
                  <span className="font-semibold">
                    Immeuble en gestion externe
                  </span>
                </label>
                <p className="mt-1 text-[11px] text-sky-200/70">
                  Les paiements, renouvellements, dépôts et relances sont
                  gérés par la compagnie de gestion — masqués dans Kratos.
                </p>
                {editForm.gestion_externe ? (
                  <div className="mt-3 grid grid-cols-2 gap-3">
                    <EditField label="Compagnie de gestion">
                      <input
                        value={editForm.gestionnaire_externe_nom}
                        onChange={(e) =>
                          setEditForm((f) => ({
                            ...f,
                            gestionnaire_externe_nom: e.target.value
                          }))
                        }
                        placeholder="ex. Gestion ABC inc."
                        className="w-full rounded-lg border border-brand-800 bg-brand-900 px-3 py-2 text-sm text-white outline-none focus:border-sky-300"
                      />
                    </EditField>
                    <EditField label="Contact">
                      <input
                        value={editForm.gestionnaire_externe_contact}
                        onChange={(e) =>
                          setEditForm((f) => ({
                            ...f,
                            gestionnaire_externe_contact: e.target.value
                          }))
                        }
                        placeholder="ex. 514 555-0123 / courriel"
                        className="w-full rounded-lg border border-brand-800 bg-brand-900 px-3 py-2 text-sm text-white outline-none focus:border-sky-300"
                      />
                    </EditField>
                  </div>
                ) : null}
              </div>
            </div>
            <div className="flex items-center justify-end gap-2 border-t border-brand-800 px-5 py-3">
              <button
                type="button"
                onClick={() => setShowEdit(false)}
                disabled={editBusy}
                className="btn-secondary btn-sm"
              >
                Annuler
              </button>
              <button
                type="button"
                onClick={() => void saveEdit()}
                disabled={editBusy || !editForm.address.trim()}
                className="btn-accent btn-sm disabled:opacity-50"
              >
                {editBusy ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : null}
                Enregistrer
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </>
  );
}

/** Menu « Actions » du header de fiche — regroupe Modifier / Bon de
 *  travail / Supprimer (fermé au clic extérieur, pattern des menus du
 *  repo). */
function ActionsMenu({
  onEdit,
  onDelete
}: {
  onEdit: () => void;
  onDelete: () => void;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!open) return;
    function onDoc(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);

  const itemCls =
    "flex w-full items-center gap-2 px-3 py-2 text-left text-xs font-medium text-white/80 transition hover:bg-brand-900 hover:text-white";

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="btn-outline-accent btn-sm"
        aria-haspopup="menu"
        aria-expanded={open}
      >
        Actions
        <ChevronDown
          className={`h-3.5 w-3.5 transition ${open ? "rotate-180" : ""}`}
        />
      </button>
      {open ? (
        <div className="absolute right-0 z-30 mt-1 w-56 rounded-lg border border-brand-700 bg-brand-950 py-1 shadow-2xl">
          <button
            type="button"
            onClick={() => {
              setOpen(false);
              onEdit();
            }}
            className={itemCls}
            title="Modifier l'immeuble (nom, adresse, etc.)"
          >
            <Pencil className="h-3.5 w-3.5" /> Modifier
          </button>
          {/* « Bon de travail » déplacé dans l'onglet Maintenance
              (retour Phil 2026-07-10). */}
          <div className="my-1 border-t border-brand-800" />
          <button
            type="button"
            onClick={() => {
              setOpen(false);
              onDelete();
            }}
            className="flex w-full items-center gap-2 px-3 py-2 text-left text-xs font-medium text-rose-300 transition hover:bg-rose-500/10 hover:text-rose-200"
          >
            <Trash2 className="h-3.5 w-3.5" /> Supprimer
          </button>
        </div>
      ) : null}
    </div>
  );
}

function EditField({
  label,
  children
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <label className="mb-1 block text-[11px] font-semibold text-white/60">
        {label}
      </label>
      {children}
    </div>
  );
}

function Kpi({
  label,
  value,
  sub,
  icon: Icon,
  tone
}: {
  label: string;
  value: React.ReactNode;
  sub?: React.ReactNode;
  icon: React.ComponentType<{ className?: string }>;
  tone: "sky" | "emerald" | "amber" | "rose";
}) {
  const cls: Record<typeof tone, string> = {
    sky: "bg-sky-500/15 text-sky-300",
    emerald: "bg-emerald-500/15 text-emerald-300",
    amber: "bg-amber-500/15 text-amber-300",
    rose: "bg-rose-500/15 text-rose-300"
  };
  return (
    <div className="kpi-card">
      <div className="flex items-center justify-between">
        <span className="text-[10px] font-semibold uppercase tracking-wider text-white/50">
          {label}
        </span>
        <span
          className={`flex h-8 w-8 items-center justify-center rounded-lg ${cls[tone]}`}
        >
          <Icon className="h-4 w-4" />
        </span>
      </div>
      <div className="mt-3 text-2xl font-bold text-white">{value}</div>
      {sub ? <div className="mt-1 text-xs text-white/50">{sub}</div> : null}
    </div>
  );
}

function Section({
  title,
  children,
  action,
  empty = "—"
}: {
  title: string;
  children: React.ReactNode;
  // Contrôle optionnel affiché à droite du titre (ex. engrenage).
  action?: React.ReactNode;
  empty?: string;
}) {
  void empty;
  return (
    <section className="rounded-2xl border border-brand-800 bg-brand-900 p-5">
      <div className="mb-3 flex items-center justify-between gap-2">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-accent-500">
          {title}
        </h2>
        {action || null}
      </div>
      {children}
    </section>
  );
}

type AlerteRegle = {
  type: string;
  enabled: boolean;
  seuil: number | null;
};

type AlertesConfig = { regles: AlerteRegle[] };

// Catalogue des alertes disponibles — miroir du backend. `unite` porte
// le libellé du seuil (null = alerte on/off sans seuil).
const ALERTES_CATALOGUE: {
  type: string;
  label: string;
  unite: "jours" | "mois" | null;
  defaut: number | null;
  min: number;
  max: number;
}[] = [
  {
    type: "bail_fin",
    label: "Baux qui échoient bientôt",
    unite: "jours",
    defaut: 90,
    min: 1,
    max: 730
  },
  {
    type: "terme_hypo",
    label: "Fins de terme hypothécaire",
    unite: "mois",
    defaut: 6,
    min: 1,
    max: 36
  },
  {
    type: "logement_vacant",
    label: "Logements vacants",
    unite: null,
    defaut: null,
    min: 0,
    max: 0
  },
  {
    type: "bail_propose",
    label: "Baux en attente de signature",
    unite: null,
    defaut: null,
    min: 0,
    max: 0
  },
  {
    type: "evaluation_agee",
    label: "Évaluation à mettre à jour",
    unite: "mois",
    defaut: 24,
    min: 6,
    max: 120
  }
];

const ALERTES_DEFAUTS: AlertesConfig = {
  regles: ALERTES_CATALOGUE.map((c) => ({
    type: c.type,
    enabled: c.type === "bail_fin" || c.type === "terme_hypo",
    seuil: c.defaut
  }))
};

function OverviewTab({
  immeuble,
  financials,
  logementsCount,
  baux,
  logements,
  hypotheques,
  evaluations
}: {
  immeuble: Immeuble;
  financials: Financials | null;
  logementsCount: number;
  baux: Bail[] | null;
  logements: Logement[] | null;
  hypotheques: Hypotheque[] | null;
  evaluations: Evaluation[] | null;
}) {
  const logMap = new Map((logements || []).map((l) => [l.id, l.numero]));
  const gestionExterne = !!immeuble.gestion_externe;

  // Alertes configurables (globales au pôle) — engrenage de la section
  // « À surveiller » : catalogue, ajout/retrait, seuils (v2).
  const [alertesCfg, setAlertesCfg] =
    useState<AlertesConfig>(ALERTES_DEFAUTS);
  const [showAlertesCfg, setShowAlertesCfg] = useState(false);

  useEffect(() => {
    let cancelled = false;
    authedFetch("/api/v1/immobilier/alertes-config")
      .then((r) => (r.ok ? r.json() : null))
      .then((d: AlertesConfig | null) => {
        if (!cancelled && d && Array.isArray(d.regles) && d.regles.length)
          setAlertesCfg(d);
      })
      .catch(() => {
        /* défauts conservés */
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const regle = (t: string): AlerteRegle | undefined =>
    alertesCfg.regles.find((r) => r.type === t && r.enabled);

  // Baux actifs qui échoient d'ici N jours. En gestion externe, les
  // baux sont suivis par la compagnie — pas d'alerte ici.
  const regleBail = regle("bail_fin");
  const seuilBailJours = regleBail?.seuil ?? 90;
  const bauxBientot = (
    gestionExterne || !regleBail ? [] : baux || []
  ).filter((b) => {
    if (b.status !== "actif" || !b.date_fin) return false;
    const jours =
      (new Date(`${b.date_fin}T00:00:00`).getTime() - Date.now()) /
      (1000 * 60 * 60 * 24);
    return jours >= 0 && jours < seuilBailJours;
  });

  // Hypothèques actives dont le terme finit dans moins de N mois.
  const regleHypo = regle("terme_hypo");
  const seuilHypoMois = regleHypo?.seuil ?? 6;
  const termesBientot = (regleHypo ? hypotheques || [] : []).filter((h) => {
    if (h.status !== "active" || !h.date_fin_terme) return false;
    const mois =
      (new Date(`${h.date_fin_terme}T00:00:00`).getTime() - Date.now()) /
      (1000 * 60 * 60 * 24 * 30.44);
    return mois < seuilHypoMois;
  });

  // Logements vacants (statut manuel — pertinent même en gestion externe).
  const logementsVacants = regle("logement_vacant")
    ? (logements || []).filter((l) => l.status === "vacant")
    : [];

  // Baux proposés (envoyés mais pas encore signés/actifs).
  const bauxProposes = regle("bail_propose")
    ? (baux || []).filter((b) => b.status === "propose")
    : [];

  // Aucune évaluation depuis N mois (ou aucune du tout).
  const regleEval = regle("evaluation_agee");
  let evalAgeeMsg: string | null = null;
  if (regleEval && evaluations !== null) {
    const seuilMois = regleEval.seuil ?? 24;
    const derniere = [...(evaluations || [])].sort((a, b) =>
      b.date_evaluation.localeCompare(a.date_evaluation)
    )[0];
    if (!derniere) {
      evalAgeeMsg = "Aucune évaluation enregistrée pour cet immeuble.";
    } else {
      const ageMois =
        (Date.now() -
          new Date(`${derniere.date_evaluation}T00:00:00`).getTime()) /
        (1000 * 60 * 60 * 24 * 30.44);
      if (ageMois > seuilMois)
        evalAgeeMsg = `Dernière évaluation le ${derniere.date_evaluation} — plus de ${seuilMois} mois.`;
    }
  }

  const hasAlerts =
    bauxBientot.length > 0 ||
    termesBientot.length > 0 ||
    logementsVacants.length > 0 ||
    bauxProposes.length > 0 ||
    evalAgeeMsg != null;
  const toutDesactive = alertesCfg.regles.every((r) => !r.enabled);

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      {gestionExterne ? (
        <div className="lg:col-span-2 rounded-2xl border border-sky-400/30 bg-sky-500/10 p-4">
          <p className="flex items-center gap-2 text-sm font-semibold text-sky-200">
            <Building2 className="h-4 w-4 flex-shrink-0" />
            Immeuble en gestion externe
            {immeuble.gestionnaire_externe_nom
              ? ` — géré par ${immeuble.gestionnaire_externe_nom}${
                  immeuble.gestionnaire_externe_contact
                    ? ` (${immeuble.gestionnaire_externe_contact})`
                    : ""
                }`
              : ""}
          </p>
          <p className="mt-1 text-xs text-sky-200/70">
            Les paiements, renouvellements, dépôts et relances sont gérés
            par la compagnie de gestion.
          </p>
        </div>
      ) : null}
      <Section title="Caractéristiques">
        <dl className="grid grid-cols-2 gap-y-2 text-sm">
          <dt className="text-white/50">Type</dt>
          <dd className="text-right text-white">{immeuble.type}</dd>
          <dt className="text-white/50">Année</dt>
          <dd className="text-right text-white">
            {immeuble.annee_construction || "—"}
          </dd>
          <dt className="text-white/50">Logements (déclaré)</dt>
          <dd className="text-right text-white">
            {immeuble.nb_logements ?? "—"}
          </dd>
          <dt className="text-white/50">Logements (créés)</dt>
          <dd className="text-right text-white">{logementsCount}</dd>
          {immeuble.purchase_date ? (
            <>
              <dt className="text-white/50">Date d&apos;achat</dt>
              <dd className="text-right text-white">{immeuble.purchase_date}</dd>
            </>
          ) : null}
          {immeuble.purchase_price ? (
            <>
              <dt className="text-white/50">Prix d&apos;achat</dt>
              <dd className="text-right font-mono text-white">
                {fmtCurrency(immeuble.purchase_price)}
              </dd>
            </>
          ) : null}
        </dl>
        {immeuble.description ? (
          <p className="mt-4 border-t border-brand-800 pt-3 text-sm text-white/70">
            {immeuble.description}
          </p>
        ) : null}
      </Section>

      <Section title="Valorisation">
        <dl className="grid grid-cols-2 gap-y-2 text-sm">
          <dt className="text-white/50">Valeur actuelle</dt>
          <dd className="text-right font-mono text-white">
            {fmtCurrency(financials?.valeur_actuelle)}
          </dd>
          <dt className="text-white/50">Valeur municipale</dt>
          <dd className="text-right font-mono text-white">
            {fmtCurrency(financials?.valeur_municipale)}
          </dd>
          <dt className="text-white/50">Prix d&apos;achat</dt>
          <dd className="text-right font-mono text-white">
            {fmtCurrency(financials?.purchase_price)}
          </dd>
          <dt className="text-white/50">Appréciation</dt>
          <dd
            className={`text-right font-mono ${
              (financials?.appreciation_pct || 0) >= 0
                ? "text-emerald-300"
                : "text-rose-300"
            }`}
          >
            {fmtPct(financials?.appreciation_pct, 1)}
          </dd>
          <dt className="text-white/50">Balance hypothécaire</dt>
          <dd className="text-right font-mono text-white">
            {fmtCurrency(financials?.balance_hypothecaire)}
          </dd>
        </dl>
      </Section>

      <div className="lg:col-span-2">
        <Section
          title="À surveiller"
          action={
            <button
              type="button"
              onClick={() => setShowAlertesCfg(true)}
              className="btn-ghost btn-xs"
              title="Configurer les alertes (seuils, activation)"
            >
              <SettingsIcon className="h-3.5 w-3.5" />
            </button>
          }
        >
          {!hasAlerts ? (
            <p className="text-xs text-white/40">
              Rien à signaler
              {toutDesactive
                ? " — toutes les alertes sont désactivées (engrenage pour en ajouter)."
                : "."}
            </p>
          ) : (
            <div className="grid gap-3 lg:grid-cols-2">
              {bauxBientot.length > 0 ? (
                <div className="rounded-2xl border border-amber-500/30 bg-amber-500/10 p-4">
                  <p className="flex items-center gap-2 text-sm font-semibold text-amber-200">
                    <AlertTriangle className="h-4 w-4 flex-shrink-0" />
                    {bauxBientot.length}{" "}
                    {bauxBientot.length > 1 ? "baux échoient" : "bail échoit"}{" "}
                    d&apos;ici {regleBail?.seuil ?? 90} jours
                  </p>
                  {/* text-amber-200 SANS alpha : la variante /80 échappe au
                      remap du thème clair → texte illisible (retour Phil). */}
                  <ul className="mt-2 space-y-1 text-xs text-amber-200 opacity-90">
                    {bauxBientot.map((b) => (
                      <li
                        key={b.id}
                        className="flex items-center justify-between gap-3"
                      >
                        <span>
                          Logement{" "}
                          {logMap.get(b.logement_id) || `#${b.logement_id}`}
                        </span>
                        <span className="font-mono">{b.date_fin}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}
              {termesBientot.length > 0 ? (
                <div className="rounded-2xl border border-amber-500/30 bg-amber-500/10 p-4">
                  <p className="flex items-center gap-2 text-sm font-semibold text-amber-200">
                    <AlertTriangle className="h-4 w-4 flex-shrink-0" />
                    Fin de terme hypothécaire dans moins de{" "}
                    {regleHypo?.seuil ?? 6} mois
                  </p>
                  {/* text-amber-200 SANS alpha : la variante /80 échappe au
                      remap du thème clair → texte illisible (retour Phil). */}
                  <ul className="mt-2 space-y-1 text-xs text-amber-200 opacity-90">
                    {termesBientot.map((h) => (
                      <li
                        key={h.id}
                        className="flex items-center justify-between gap-3"
                      >
                        <span>
                          {h.preteur} (rang {h.rang})
                        </span>
                        <span className="font-mono">
                          {h.date_fin_terme || "—"}
                        </span>
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}
              {logementsVacants.length > 0 ? (
                <div className="rounded-2xl border border-amber-500/30 bg-amber-500/10 p-4">
                  <p className="flex items-center gap-2 text-sm font-semibold text-amber-200">
                    <AlertTriangle className="h-4 w-4 flex-shrink-0" />
                    {logementsVacants.length} logement
                    {logementsVacants.length > 1 ? "s" : ""} vacant
                    {logementsVacants.length > 1 ? "s" : ""}
                  </p>
                  <ul className="mt-2 space-y-1 text-xs text-amber-200 opacity-90">
                    {logementsVacants.map((l) => (
                      <li
                        key={l.id}
                        className="flex items-center justify-between gap-3"
                      >
                        <span>Logement {l.numero}</span>
                        <span className="font-mono">
                          {l.loyer_demande != null
                            ? fmtCurrency(l.loyer_demande)
                            : "—"}
                        </span>
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}
              {bauxProposes.length > 0 ? (
                <div className="rounded-2xl border border-amber-500/30 bg-amber-500/10 p-4">
                  <p className="flex items-center gap-2 text-sm font-semibold text-amber-200">
                    <AlertTriangle className="h-4 w-4 flex-shrink-0" />
                    {bauxProposes.length} bail
                    {bauxProposes.length > 1 ? "x" : ""} en attente de
                    signature
                  </p>
                  <ul className="mt-2 space-y-1 text-xs text-amber-200 opacity-90">
                    {bauxProposes.map((b) => (
                      <li
                        key={b.id}
                        className="flex items-center justify-between gap-3"
                      >
                        <span>
                          Logement{" "}
                          {logMap.get(b.logement_id) || `#${b.logement_id}`}
                        </span>
                        <span className="font-mono">
                          début {b.date_debut}
                        </span>
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}
              {evalAgeeMsg ? (
                <div className="rounded-2xl border border-amber-500/30 bg-amber-500/10 p-4">
                  <p className="flex items-center gap-2 text-sm font-semibold text-amber-200">
                    <AlertTriangle className="h-4 w-4 flex-shrink-0" />
                    Évaluation à mettre à jour
                  </p>
                  <p className="mt-2 text-xs text-amber-200 opacity-90">
                    {evalAgeeMsg}
                  </p>
                </div>
              ) : null}
            </div>
          )}
        </Section>
      </div>

      {showAlertesCfg ? (
        <AlertesCfgModal
          initial={alertesCfg}
          onClose={() => setShowAlertesCfg(false)}
          onSaved={(cfg) => {
            setAlertesCfg(cfg);
            setShowAlertesCfg(false);
          }}
        />
      ) : null}
    </div>
  );
}

function AlertesCfgModal({
  initial,
  onClose,
  onSaved
}: {
  initial: AlertesConfig;
  onClose: () => void;
  onSaved: (cfg: AlertesConfig) => void;
}) {
  // Seuils en texte, indexés par type — les règles actives s'affichent
  // en lignes (seuil modifiable + retrait), les inactives vivent dans
  // « + Ajouter une alerte ».
  const [regles, setRegles] = useState<AlerteRegle[]>(() =>
    ALERTES_CATALOGUE.map(
      (c) =>
        initial.regles.find((r) => r.type === c.type) ?? {
          type: c.type,
          enabled: false,
          seuil: c.defaut
        }
    )
  );
  const [seuils, setSeuils] = useState<Record<string, string>>(() =>
    Object.fromEntries(
      ALERTES_CATALOGUE.map((c) => {
        const r = initial.regles.find((x) => x.type === c.type);
        return [c.type, String(r?.seuil ?? c.defaut ?? "")];
      })
    )
  );
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const catalogue = (t: string) =>
    ALERTES_CATALOGUE.find((c) => c.type === t);
  const actives = regles.filter((r) => r.enabled);
  const inactives = regles.filter((r) => !r.enabled);

  function seuilValide(r: AlerteRegle): boolean {
    const c = catalogue(r.type);
    if (!c || c.unite == null) return true;
    const n = Number(seuils[r.type]);
    return Number.isInteger(n) && n >= c.min && n <= c.max;
  }
  const valid = actives.every(seuilValide);

  function setEnabled(type: string, enabled: boolean) {
    setRegles((prev) =>
      prev.map((r) => (r.type === type ? { ...r, enabled } : r))
    );
  }

  async function save() {
    if (!valid) return;
    setSaving(true);
    setErr(null);
    const cfg: AlertesConfig = {
      regles: regles.map((r) => {
        const c = catalogue(r.type);
        return {
          type: r.type,
          enabled: r.enabled,
          seuil:
            c && c.unite != null
              ? Number(seuils[r.type]) || c.defaut
              : null
        };
      })
    };
    try {
      const res = await authedFetch("/api/v1/immobilier/alertes-config", {
        method: "PUT",
        body: JSON.stringify(cfg)
      });
      if (!res.ok)
        throw new Error(
          (await res.text()).slice(0, 200) || `HTTP ${res.status}`
        );
      // On garde la version normalisée par le serveur (clamp des seuils).
      onSaved((await res.json()) as AlertesConfig);
    } catch (e) {
      setErr(`Enregistrement échoué : ${(e as Error).message}`);
    } finally {
      setSaving(false);
    }
  }

  const rowCls =
    "flex flex-wrap items-center justify-between gap-3 rounded-xl border border-brand-800 bg-brand-950/60 px-4 py-3";
  const numCls =
    "w-20 rounded-md border border-brand-800 bg-brand-950 px-2 py-1.5 text-center text-xs text-white outline-none focus:border-accent-500";

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/70 p-4 backdrop-blur-sm">
      <div className="my-8 w-full max-w-md rounded-2xl border border-brand-800 bg-brand-950 shadow-2xl">
        <div className="flex items-center justify-between border-b border-brand-800 px-5 py-3">
          <h2 className="flex items-center gap-2 text-sm font-bold uppercase tracking-wider text-accent-500">
            <SettingsIcon className="h-4 w-4" /> Alertes « À surveiller »
          </h2>
          <button type="button" onClick={onClose} className="btn-ghost btn-xs">
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="space-y-3 p-5">
          <p className="text-xs text-white/50">
            Réglages globaux — appliqués à la section « À surveiller » de
            tous les immeubles.
          </p>

          {actives.length === 0 ? (
            <p className="rounded-xl border border-dashed border-brand-700 px-4 py-3 text-xs text-white/40">
              Aucune alerte active — ajoutes-en une ci-dessous.
            </p>
          ) : (
            actives.map((r) => {
              const c = catalogue(r.type);
              if (!c) return null;
              return (
                <div key={r.type} className={rowCls}>
                  <span className="text-sm text-white">{c.label}</span>
                  <span className="flex items-center gap-2 text-xs text-white/60">
                    {c.unite != null ? (
                      <>
                        d&apos;ici
                        <input
                          inputMode="numeric"
                          value={seuils[r.type] ?? ""}
                          onChange={(e) =>
                            setSeuils((prev) => ({
                              ...prev,
                              [r.type]: e.target.value
                            }))
                          }
                          className={`${numCls} ${
                            seuilValide(r) ? "" : "border-rose-500/60"
                          }`}
                        />
                        {c.unite}
                      </>
                    ) : null}
                    <button
                      type="button"
                      onClick={() => setEnabled(r.type, false)}
                      className="btn-ghost btn-xs"
                      title="Retirer cette alerte"
                    >
                      <X className="h-3.5 w-3.5" />
                    </button>
                  </span>
                </div>
              );
            })
          )}

          {inactives.length > 0 ? (
            <div className="rounded-xl border border-dashed border-brand-700 px-4 py-3">
              <p className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-white/40">
                <Plus className="mr-1 inline h-3 w-3" /> Ajouter une alerte
              </p>
              <div className="flex flex-wrap gap-2">
                {inactives.map((r) => {
                  const c = catalogue(r.type);
                  if (!c) return null;
                  return (
                    <button
                      key={r.type}
                      type="button"
                      onClick={() => setEnabled(r.type, true)}
                      className="inline-flex items-center gap-1.5 rounded-lg border border-brand-700 px-2.5 py-1.5 text-xs font-semibold text-white/70 transition hover:border-accent-500 hover:text-white"
                    >
                      <Plus className="h-3 w-3" /> {c.label}
                    </button>
                  );
                })}
              </div>
            </div>
          ) : null}

          {err ? (
            <p className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">
              {err}
            </p>
          ) : null}

          <div className="flex items-center justify-end gap-2 border-t border-brand-800 pt-3">
            <button
              type="button"
              onClick={onClose}
              disabled={saving}
              className="btn-secondary btn-sm"
            >
              Annuler
            </button>
            <button
              type="button"
              onClick={() => void save()}
              disabled={saving || !valid}
              className="btn-accent btn-sm disabled:opacity-50"
            >
              {saving ? (
                <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />
              ) : (
                <Check className="mr-1 h-3.5 w-3.5" />
              )}
              Enregistrer
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

function LogementsTab({
  immeubleId,
  list,
  baux,
  setList
}: {
  immeubleId: number;
  list: Logement[] | null;
  baux: Bail[] | null;
  setList: React.Dispatch<React.SetStateAction<Logement[] | null>>;
}) {
  const router = useRouter();
  // La modale ne sert plus qu'à la création — le clic sur une ligne
  // navigue vers la page dédiée du logement.
  const [showCreate, setShowCreate] = useState(false);

  const addButton = (
    <button
      type="button"
      onClick={() => setShowCreate(true)}
      className="btn-outline-accent btn-sm"
    >
      <Plus className="h-3.5 w-3.5" /> Ajouter un logement
    </button>
  );

  const modal = showCreate ? (
    <LogementFiche
      logement={null}
      immeubleId={immeubleId}
      bails={baux ?? undefined}
      onClose={() => setShowCreate(false)}
      onSaved={(saved) => {
        setList((prev) => [...(prev ?? []), saved]);
        setShowCreate(false);
        // Ouvrir directement la fiche du logement créé (retour Phil) —
        // le retour contextuel ramène à l'onglet Logements de l'immeuble.
        router.push(
          `/immobilier/logements/${saved.id}?from=immeuble` as any
        );
      }}
      onDeleted={(id) => {
        setList((prev) => prev?.filter((l) => l.id !== id) ?? prev);
        setShowCreate(false);
      }}
    />
  ) : null;

  if (list === null)
    return (
      <p className="text-xs text-white/50">
        <Loader2 className="mr-1 inline h-3 w-3 animate-spin" /> Chargement…
      </p>
    );
  if (list.length === 0)
    return (
      <div className="space-y-3">
        <div className="flex justify-end">{addButton}</div>
        <p className="rounded-lg border border-brand-800 bg-brand-900 px-4 py-3 text-sm text-white/60">
          Aucun logement créé.
        </p>
        {modal}
      </div>
    );
  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between gap-2">
        <p className="text-xs text-white/50">
          Clique sur un logement pour ouvrir sa fiche.
        </p>
        {addButton}
      </div>
      <div className="overflow-hidden rounded-2xl border border-brand-800 bg-brand-900">
        <table className="w-full text-left text-sm">
          <thead className="border-b border-brand-800 bg-brand-950 text-[10px] uppercase tracking-wider text-white/50">
            <tr>
              <th className="px-4 py-2.5">Numéro</th>
              <th className="px-4 py-2.5">Pièces</th>
              <th className="px-4 py-2.5 text-right">Superficie</th>
              <th className="px-4 py-2.5">Statut</th>
              <th className="px-4 py-2.5 text-right">Loyer demandé</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-brand-800">
            {list.map((l) => (
              <tr
                key={l.id}
                onClick={() =>
                  // ?from=immeuble : le bouton retour de la page logement
                  // ramène ici, onglet Logements (retour Phil 2026-07-10).
                  // eslint-disable-next-line @typescript-eslint/no-explicit-any
                  router.push(`/immobilier/logements/${l.id}?from=immeuble` as any)
                }
                className="cursor-pointer transition hover:bg-brand-800/40"
              >
                <td className="px-4 py-2 font-bold text-white">{l.numero}</td>
                <td className="px-4 py-2 text-xs text-white/70">
                  {fmtPieces(l.nb_pieces_decimal)}
                </td>
                <td className="px-4 py-2 text-right font-mono text-xs text-white/70">
                  {l.superficie_pi2 ? `${l.superficie_pi2} pi²` : "—"}
                </td>
                <td className="px-4 py-2 text-xs">
                  <StatusBadge status={l.status} />
                </td>
                <td className="px-4 py-2 text-right font-mono text-xs text-white/70">
                  {fmtCurrency(l.loyer_demande)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {modal}
    </div>
  );
}

function BauxTab({
  immeubleId,
  list,
  logements,
  locataires,
  highlightBailId,
  onRelocation
}: {
  immeubleId: number;
  list: Bail[] | null;
  logements: Logement[] | null;
  locataires: { id: number; full_name: string }[];
  highlightBailId: number | null;
  onRelocation: (b: Bail) => void | Promise<void>;
}) {
  const logMap = new Map((logements || []).map((l) => [l.id, l.numero]));
  const locMap = new Map(locataires.map((l) => [l.id, l.full_name]));
  return (
    <div className="space-y-4">
      {list === null ? (
        <Loading />
      ) : list.length === 0 ? (
        <Empty msg="Aucun bail." />
      ) : (
        <div className="overflow-hidden rounded-2xl border border-brand-800 bg-brand-900">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-brand-800 bg-brand-950 text-[10px] uppercase tracking-wider text-white/50">
              <tr>
                <th className="px-4 py-2.5">Logement</th>
                <th className="px-4 py-2.5">Locataire</th>
                <th className="px-4 py-2.5">Période</th>
                <th className="px-4 py-2.5 text-right">Loyer/m</th>
                <th className="px-4 py-2.5">Statut</th>
                <th className="px-4 py-2.5">Signature</th>
                <th className="px-4 py-2.5 text-right">Documents TAL</th>
                <th className="px-4 py-2.5 text-right">Départ</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-brand-800">
              {list.map((b) => (
                <tr
                  key={b.id}
                  // Bail ciblé depuis la fiche locataire (?bail=…) :
                  // surligné + amené à l'écran.
                  ref={
                    b.id === highlightBailId
                      ? (el) =>
                          el?.scrollIntoView({
                            block: "center",
                            behavior: "smooth"
                          })
                      : undefined
                  }
                  className={
                    b.id === highlightBailId
                      ? "bg-accent-500/10 ring-1 ring-inset ring-accent-500/40"
                      : ""
                  }
                >
                  <td className="px-4 py-2 font-mono text-xs text-white">
                    {logMap.get(b.logement_id) || `#${b.logement_id}`}
                  </td>
                  <td className="px-4 py-2 text-xs">
                    <Link
                      // eslint-disable-next-line @typescript-eslint/no-explicit-any
                      href={
                        `/immobilier/locataires/${b.locataire_id}?from=immeuble&imm=${immeubleId}` as any
                      }
                      className="font-medium text-accent-500 hover:underline"
                    >
                      {locMap.get(b.locataire_id) ||
                        `Locataire #${b.locataire_id}`}
                    </Link>
                  </td>
                  <td className="px-4 py-2 text-xs text-white/70">
                    {b.date_debut} → {b.date_fin}
                  </td>
                  <td className="px-4 py-2 text-right font-mono text-xs text-white/80">
                    {fmtCurrency(b.loyer_mensuel)}
                  </td>
                  <td className="px-4 py-2 text-xs">
                    <StatusBadge status={b.status} />
                  </td>
                  <td className="px-4 py-2 text-xs">
                    <BailSignButton bailId={b.id} signed={!!b.signed_at} />
                  </td>
                  <td className="px-4 py-2 text-right">
                    <TalFormDropdown bailId={b.id} />
                  </td>
                  <td className="px-4 py-2 text-right">
                    {b.status === "actif" ? (
                      <button
                        type="button"
                        title="Le locataire a confirmé son départ — ouvrir un dossier de relocation (onglet Locations)"
                        onClick={() => void onRelocation(b)}
                        className="inline-flex items-center gap-1.5 rounded-lg border border-amber-500/40 bg-amber-500/10 px-2.5 py-1 text-xs font-semibold text-amber-300 transition hover:bg-amber-500/20"
                      >
                        <LogOut className="h-3 w-3" /> Départ
                      </button>
                    ) : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// ── Paiements du mois courant (miroir de la page Baux & paiements) ─────

type LoyerRow = {
  bail_id: number;
  immeuble_id: number;
  logement_numero: string | null;
  locataire_id: number | null;
  locataire_name: string | null;
  loyer_mensuel: number;
  montant_paye: number | null;
  paye_le: string | null;
  etat: string; // "paye" | "retard" | "attente"
};

function PaiementsMoisSection({ immeubleId }: { immeubleId: number }) {
  const [rows, setRows] = useState<LoyerRow[] | null>(null);
  const [mois, setMois] = useState<string>(() => {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
  });
  const [err, setErr] = useState<string | null>(null);
  const [payingId, setPayingId] = useState<number | null>(null);
  const [relancingId, setRelancingId] = useState<number | null>(null);
  const [info, setInfo] = useState<string | null>(null);

  const load = useCallback(async () => {
    setErr(null);
    try {
      const r = await authedFetch(
        `/api/v1/immobilier/loyers/overview?mois=${mois}`
      );
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const d = (await r.json()) as { rows: LoyerRow[] };
      // L'API ne filtre pas par immeuble → filtrage client-side.
      setRows(d.rows.filter((row) => row.immeuble_id === immeubleId));
    } catch (e) {
      setErr((e as Error).message);
      setRows([]);
    }
  }, [mois, immeubleId]);

  useEffect(() => {
    void load();
  }, [load]);

  async function marquerPaye(row: LoyerRow) {
    setPayingId(row.bail_id);
    setErr(null);
    try {
      const today = new Date();
      const payeLe = `${today.getFullYear()}-${String(
        today.getMonth() + 1
      ).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`;
      const r = await authedFetch("/api/v1/immobilier/paiements", {
        method: "POST",
        body: JSON.stringify({
          bail_id: row.bail_id,
          mois_couvert: `${mois}-01`,
          montant: row.loyer_mensuel,
          paye_le: payeLe
        })
      });
      if (!r.ok) {
        const t = await r.text();
        throw new Error(t.slice(0, 200) || `HTTP ${r.status}`);
      }
      await load();
    } catch (e) {
      setErr(`Marquer payé a échoué : ${(e as Error).message}`);
    } finally {
      setPayingId(null);
    }
  }

  // Rappel de paiement MANUEL : courriel au locataire via Microsoft
  // Graph (expéditeur = boîte configurée, cf. Paramètres). Rien
  // d'automatique — chaque envoi est un clic (retour Phil 2026-07-10).
  async function relancer(row: LoyerRow) {
    setRelancingId(row.bail_id);
    setInfo(null);
    setErr(null);
    try {
      const r = await authedFetch("/api/v1/immobilier/loyers/relance", {
        method: "POST",
        body: JSON.stringify({ bail_id: row.bail_id, mois })
      });
      if (!r.ok) {
        const t = await r.text();
        throw new Error(t.slice(0, 200) || `HTTP ${r.status}`);
      }
      const res = (await r.json()) as {
        niveau: number;
        destinataire: string;
      };
      setInfo(
        `Rappel ${res.niveau > 1 ? `(niveau ${res.niveau}) ` : ""}envoyé à ${res.destinataire}.`
      );
      await load();
    } catch (e) {
      setErr(`Rappel échoué : ${(e as Error).message}`);
    } finally {
      setRelancingId(null);
    }
  }

  const moisLisible = (() => {
    const [y, m] = mois.split("-").map(Number);
    return new Date(y, (m || 1) - 1, 1).toLocaleDateString("fr-CA", {
      month: "long",
      year: "numeric"
    });
  })();

  const totalAttendu = (rows || []).reduce(
    (s, r) => s + (r.loyer_mensuel || 0),
    0
  );
  const totalRecu = (rows || []).reduce(
    (s, r) => s + (r.etat === "paye" ? r.montant_paye || 0 : 0),
    0
  );
  const nbRetards = (rows || []).filter((r) => r.etat === "retard").length;

  return (
    <Section title={`Paiements — ${moisLisible}`}>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-3 text-xs text-white/60">
          <span>
            Reçu{" "}
            <strong className="text-emerald-300">
              {fmtCurrency(totalRecu)}
            </strong>{" "}
            / {fmtCurrency(totalAttendu)}
          </span>
          {nbRetards > 0 ? (
            <span className="badge badge-rose">
              {nbRetards} retard{nbRetards > 1 ? "s" : ""}
            </span>
          ) : null}
        </div>
        <div className="flex items-center gap-2">
          <div className="inline-flex items-center gap-1 rounded-lg border border-brand-800 bg-brand-950 px-1 py-0.5">
            <button
              type="button"
              onClick={() =>
                setMois((m) => {
                  const [y, mm] = m.split("-").map(Number);
                  const d = new Date(y, (mm || 1) - 2, 1);
                  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
                })
              }
              className="btn-ghost btn-xs"
              aria-label="Mois précédent"
            >
              ‹
            </button>
            <span className="min-w-[110px] text-center text-xs font-semibold capitalize text-white">
              {moisLisible}
            </span>
            <button
              type="button"
              onClick={() =>
                setMois((m) => {
                  const [y, mm] = m.split("-").map(Number);
                  const d = new Date(y, mm || 1, 1);
                  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
                })
              }
              className="btn-ghost btn-xs"
              aria-label="Mois suivant"
            >
              ›
            </button>
          </div>
          <Link
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            href={"/immobilier/baux" as any}
            className="text-xs text-accent-500 hover:underline"
          >
            Vue complète →
          </Link>
        </div>
      </div>

      {err ? (
        <p className="mb-3 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
          {err}
        </p>
      ) : null}
      {info ? (
        <p className="mb-3 rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-xs text-emerald-300">
          {info}
        </p>
      ) : null}

      {rows === null ? (
        <Loading />
      ) : rows.length === 0 ? (
        <p className="text-xs text-white/50">
          Aucun bail actif dans cet immeuble pour ce mois.
        </p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[560px] text-left text-sm">
            <thead className="text-[10px] uppercase tracking-wider text-white/45">
              <tr>
                <th className="py-2 pr-3">État</th>
                <th className="py-2 pr-3">Locataire</th>
                <th className="py-2 pr-3">Logement</th>
                <th className="py-2 pr-3 text-right">Loyer</th>
                <th className="py-2 pr-3 text-right">Payé le</th>
                <th className="py-2 text-right"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-brand-800/70">
              {rows.map((r) => (
                <tr
                  key={r.bail_id}
                  className={r.etat === "retard" ? "bg-rose-500/5" : ""}
                >
                  <td className="py-2 pr-3">
                    {r.etat === "paye" ? (
                      <span className="badge badge-emerald">Payé</span>
                    ) : r.etat === "retard" ? (
                      <span className="badge badge-rose">Retard</span>
                    ) : (
                      <span className="badge badge-neutral">Attente</span>
                    )}
                  </td>
                  <td className="py-2 pr-3">
                    {r.locataire_id != null ? (
                      <Link
                        // eslint-disable-next-line @typescript-eslint/no-explicit-any
                        href={
                          `/immobilier/locataires/${r.locataire_id}?from=immeuble&imm=${immeubleId}` as any
                        }
                        className="font-medium text-accent-500 hover:underline"
                      >
                        {r.locataire_name || `Locataire #${r.locataire_id}`}
                      </Link>
                    ) : (
                      <span className="text-white/60">
                        {r.locataire_name || "—"}
                      </span>
                    )}
                  </td>
                  <td className="py-2 pr-3 font-mono text-xs text-white/70">
                    {r.logement_numero || "—"}
                  </td>
                  <td className="py-2 pr-3 text-right font-mono text-xs text-white/80">
                    {fmtCurrency(r.loyer_mensuel)}
                  </td>
                  <td className="py-2 pr-3 text-right text-xs text-white/60">
                    {r.paye_le || "—"}
                  </td>
                  <td className="py-2 text-right">
                    {r.etat !== "paye" ? (
                      <span className="inline-flex items-center gap-1.5">
                        <button
                          type="button"
                          onClick={() => void relancer(r)}
                          disabled={relancingId === r.bail_id}
                          title="Envoyer un courriel de rappel au locataire (manuel)"
                          className="inline-flex items-center gap-1.5 rounded-lg border border-amber-500/40 bg-amber-500/10 px-2.5 py-1 text-xs font-semibold text-amber-300 transition hover:bg-amber-500/20 disabled:opacity-50"
                        >
                          {relancingId === r.bail_id ? (
                            <Loader2 className="h-3 w-3 animate-spin" />
                          ) : (
                            <Mail className="h-3 w-3" />
                          )}
                          Rappel courriel
                        </button>
                        <button
                          type="button"
                          onClick={() => void marquerPaye(r)}
                          disabled={payingId === r.bail_id}
                          className="inline-flex items-center gap-1.5 rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-2.5 py-1 text-xs font-semibold text-emerald-300 transition hover:bg-emerald-500/20 disabled:opacity-50"
                        >
                          {payingId === r.bail_id ? (
                            <Loader2 className="h-3 w-3 animate-spin" />
                          ) : (
                            <Check className="h-3 w-3" />
                          )}
                          Marquer payé
                        </button>
                      </span>
                    ) : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Section>
  );
}

function BailSignButton({
  bailId,
  signed
}: {
  bailId: number;
  signed: boolean;
}) {
  const [dl, setDl] = useState(false);

  async function downloadSigned() {
    setDl(true);
    try {
      const res = await authedFetch(
        `/api/v1/immobilier/baux/${bailId}/document`
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `bail-${bailId}-signe.pdf`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch (e) {
      alert((e as Error).message);
    } finally {
      setDl(false);
    }
  }

  if (signed) {
    return (
      <button
        type="button"
        onClick={() => void downloadSigned()}
        disabled={dl}
        className="inline-flex w-fit items-center gap-1 rounded-md border border-emerald-500/40 bg-emerald-500/10 px-2 py-1 text-[11px] font-semibold text-emerald-400 hover:bg-emerald-500/20 disabled:opacity-50"
        title="Télécharger le bail signé (PDF)"
      >
        {dl ? (
          <Loader2 className="h-3 w-3 animate-spin" />
        ) : (
          <FileDown className="h-3 w-3" />
        )}
        Bail signé (PDF)
      </button>
    );
  }

  // Signature PILOTÉE PAR DOCUMENT (retour Phil 2026-07-17) : le bouton
  // est grisé tant qu'aucun document n'a été généré via « Générer ▾ » ;
  // il ouvre ensuite la bibliothèque (voir/modifier/envoyer/suivre).
  return <BailSignature bailId={bailId} />;
}

const HYPO_STATUS: [string, string][] = [
  ["active", "Active"],
  ["remboursee", "Remboursée"],
  ["refinancee", "Refinancée"]
];

const HYPO_STATUS_LABEL: Record<string, string> = Object.fromEntries(
  HYPO_STATUS
);

const HYPO_STATUS_BADGE: Record<string, string> = {
  active: "badge-emerald",
  remboursee: "badge-neutral",
  refinancee: "badge-sky"
};

/**
 * Paiement mensuel d'une hypothèque canadienne.
 *
 * Composition des intérêts (persistée sur l'hypothèque via
 * composition_interets, rechargée en édition) :
 *  - "semi"      : composé semi-annuellement, converti en taux mensuel
 *                  équivalent (résidentiel canadien, Loi sur l'intérêt) ;
 *  - "mensuelle" : composé mensuellement (prêts commerciaux
 *                  multi-logements / taux variables).
 */
type CompositionInterets = "semi" | "mensuelle";

function computePaiementMensuel(
  tauxPct: number,
  amortissementMois: number,
  balance: number,
  composition: CompositionInterets = "semi"
): number | null {
  if (!(balance > 0) || !(amortissementMois > 0) || Number.isNaN(tauxPct))
    return null;
  if (tauxPct <= 0) return balance / amortissementMois;
  const iMensuel =
    composition === "mensuelle"
      ? tauxPct / 100 / 12
      : Math.pow(1 + tauxPct / 100 / 2, 2 / 12) - 1;
  const pmt =
    (balance * iMensuel) / (1 - Math.pow(1 + iMensuel, -amortissementMois));
  return Number.isFinite(pmt) ? pmt : null;
}

/**
 * Balance théorique au jour J selon le tableau d'amortissement canadien
 * — miroir du backend (services/hypotheque_calc.py) pour l'aperçu live
 * du formulaire : B = P·(1+i)^k − PMT·((1+i)^k − 1)/i.
 */
function computeBalanceCalculee(
  montantInitial: number,
  tauxPct: number,
  amortissementMois: number,
  composition: CompositionInterets,
  dateDebutIso: string
): number | null {
  if (!(montantInitial > 0) || !(amortissementMois > 0)) return null;
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(dateDebutIso);
  if (!m || Number.isNaN(tauxPct)) return null;
  const debut = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
  const now = new Date();
  let k =
    (now.getFullYear() - debut.getFullYear()) * 12 +
    (now.getMonth() - debut.getMonth());
  if (now.getDate() < debut.getDate()) k -= 1;
  k = Math.max(0, Math.min(k, amortissementMois));
  if (k <= 0) return montantInitial;
  const pmt = computePaiementMensuel(
    tauxPct,
    amortissementMois,
    montantInitial,
    composition
  );
  if (pmt == null) return null;
  if (tauxPct <= 0) return Math.max(0, montantInitial - pmt * k);
  const iMensuel =
    composition === "mensuelle"
      ? tauxPct / 100 / 12
      : Math.pow(1 + tauxPct / 100 / 2, 2 / 12) - 1;
  const facteur = Math.pow(1 + iMensuel, k);
  const b = montantInitial * facteur - (pmt * (facteur - 1)) / iMensuel;
  return Number.isFinite(b) ? Math.max(0, b) : null;
}

/**
 * Ajoute un nombre d'années (décimales acceptées, ex. 5 ou 2.5) à une
 * date ISO (YYYY-MM-DD). Mois entiers d'abord (jour borné à la fin du
 * mois cible), puis le reste converti en jours — arrondi au jour.
 */
function addAnneesIso(dateIso: string, annees: number): string | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(dateIso);
  if (!m || !Number.isFinite(annees) || annees <= 0) return null;
  const totalMois = annees * 12;
  const moisEntiers = Math.floor(totalMois + 1e-9);
  const joursFrac = Math.round((totalMois - moisEntiers) * 30.44);
  const jour = Number(m[3]);
  const cible = new Date(Number(m[1]), Number(m[2]) - 1 + moisEntiers, 1);
  const dernierJour = new Date(
    cible.getFullYear(),
    cible.getMonth() + 1,
    0
  ).getDate();
  cible.setDate(Math.min(jour, dernierJour));
  if (joursFrac > 0) cible.setDate(cible.getDate() + joursFrac);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${cible.getFullYear()}-${pad(cible.getMonth() + 1)}-${pad(cible.getDate())}`;
}

/** Terme en années entre deux dates ISO, arrondi à 0.5 près (> 0). */
function termeAnneesArrondi(
  debutIso: string,
  finIso: string
): number | null {
  const debut = new Date(`${debutIso}T00:00:00`).getTime();
  const fin = new Date(`${finIso}T00:00:00`).getTime();
  if (!Number.isFinite(debut) || !Number.isFinite(fin) || fin <= debut)
    return null;
  const annees = (fin - debut) / (1000 * 60 * 60 * 24 * 365.25);
  const arrondi = Math.round(annees * 2) / 2;
  return arrondi > 0 ? arrondi : null;
}

function fmtTermeAnnees(n: number): string {
  return `${n.toLocaleString("fr-CA")} ${n >= 2 ? "ans" : "an"}`;
}

function TermeBadge({
  date,
  dateDebut
}: {
  date?: string | null;
  dateDebut?: string | null;
}) {
  if (!date)
    return <span className="text-[11px] text-white/40">Fin du terme —</span>;
  const fin = new Date(`${date}T00:00:00`);
  const moisRestants =
    (fin.getTime() - Date.now()) / (1000 * 60 * 60 * 24 * 30.44);
  const bientot = moisRestants < 6;
  const terme = dateDebut ? termeAnneesArrondi(dateDebut, date) : null;
  return (
    <span
      className={`badge font-mono ${bientot ? "badge-amber" : "badge-neutral"}`}
      title={
        bientot
          ? "Terme à renouveler dans moins de 6 mois"
          : "Fin du terme hypothécaire"
      }
    >
      {terme != null
        ? `Terme ${fmtTermeAnnees(terme)} · fin ${date}`
        : `Fin du terme ${date}`}
    </span>
  );
}

type HypoFormState = {
  preteur: string;
  rang: string;
  montant_initial: string;
  balance_actuelle: string;
  taux_pct: string;
  type_taux: string;
  // Persistée backend (composition_interets 'semi'|'mensuelle') — le
  // paiement_mensuel calculé est aussi enregistré.
  composition: string;
  amortissement_annees: string;
  paiement_mensuel: string;
  date_debut: string;
  // Saisi en années (décimales acceptées) ; date_fin_terme (backend
  // inchangé) est calculée = date_debut + terme.
  terme_annees: string;
  status: string;
  notes: string;
};

const HYPO_FORM_EMPTY: HypoFormState = {
  preteur: "",
  rang: "1",
  montant_initial: "",
  balance_actuelle: "",
  taux_pct: "",
  type_taux: "fixe",
  composition: "semi",
  amortissement_annees: "25",
  paiement_mensuel: "",
  date_debut: "",
  terme_annees: "",
  status: "active",
  notes: ""
};

function HypothequeForm({
  initial,
  busy,
  onCancel,
  onSubmit
}: {
  initial: Hypotheque | null;
  busy: boolean;
  onCancel: () => void;
  onSubmit: (payload: Record<string, unknown>) => void;
}) {
  const [f, setF] = useState<HypoFormState>(() =>
    initial
      ? {
          preteur: initial.preteur || "",
          rang: String(initial.rang ?? 1),
          montant_initial:
            initial.montant_initial != null
              ? String(initial.montant_initial)
              : "",
          balance_actuelle:
            initial.balance_actuelle != null
              ? String(initial.balance_actuelle)
              : "",
          taux_pct: initial.taux_pct != null ? String(initial.taux_pct) : "",
          type_taux: initial.type_taux || "fixe",
          composition:
            initial.composition_interets === "mensuelle"
              ? "mensuelle"
              : "semi",
          amortissement_annees:
            initial.amortissement_mois != null
              ? String(Math.round((initial.amortissement_mois / 12) * 10) / 10)
              : "25",
          paiement_mensuel:
            initial.paiement_mensuel != null
              ? String(initial.paiement_mensuel)
              : "",
          date_debut: initial.date_debut || "",
          // Terme pré-rempli depuis les dates existantes (arrondi 0.5).
          terme_annees:
            initial.date_debut && initial.date_fin_terme
              ? (() => {
                  const t = termeAnneesArrondi(
                    initial.date_debut,
                    initial.date_fin_terme
                  );
                  return t != null ? String(t) : "";
                })()
              : "",
          status: initial.status || "active",
          notes: initial.notes || ""
        }
      : HYPO_FORM_EMPTY
  );
  // Le paiement est auto-calculé tant que l'usager ne l'a pas surchargé.
  // ⚠️ Bug corrigé (retour Phil 2026-07-10) : en édition, le paiement
  // STOCKÉ était traité comme une surcharge manuelle → changer la
  // composition (semi → mensuelle) recalculait à l'écran mais sauvait
  // l'ancien montant. On ne considère la valeur stockée comme manuelle
  // que si elle DIFFÈRE du paiement calculable avec les intrants stockés.
  const [pmtOverride, setPmtOverride] = useState<boolean>(() => {
    if (initial?.paiement_mensuel == null) return false;
    if (initial.taux_pct == null) return true; // pas calculable → manuel
    const principal =
      initial.balance_actuelle ?? initial.montant_initial ?? 0;
    const calc = computePaiementMensuel(
      Number(initial.taux_pct),
      Number(initial.amortissement_mois || 0),
      Number(principal),
      initial.composition_interets === "mensuelle" ? "mensuelle" : "semi"
    );
    if (calc == null) return true;
    return Math.abs(Number(initial.paiement_mensuel) - calc) > 0.05;
  });

  // Champs qui alimentent le calcul du paiement : les modifier remet le
  // paiement en mode auto (la nouvelle valeur calculée sera enregistrée).
  const CALC_KEYS: ReadonlyArray<keyof HypoFormState> = [
    "taux_pct",
    "amortissement_annees",
    "composition",
    "balance_actuelle",
    "montant_initial"
  ];

  const set = (k: keyof HypoFormState) => (v: string) => {
    setF((prev) => ({ ...prev, [k]: v }));
    if (CALC_KEYS.includes(k)) setPmtOverride(false);
  };

  const amortissementMois = f.amortissement_annees.trim()
    ? Math.round(Number(f.amortissement_annees) * 12)
    : 0;
  const balanceRef = f.balance_actuelle.trim()
    ? Number(f.balance_actuelle)
    : f.montant_initial.trim()
      ? Number(f.montant_initial)
      : 0;

  const compositionChoisie: CompositionInterets =
    f.composition === "mensuelle" ? "mensuelle" : "semi";

  const computedPmt = useMemo(() => {
    if (f.taux_pct.trim() === "") return null;
    return computePaiementMensuel(
      Number(f.taux_pct),
      amortissementMois,
      balanceRef,
      compositionChoisie
    );
  }, [f.taux_pct, amortissementMois, balanceRef, compositionChoisie]);

  // Aperçu de la balance auto (miroir du calcul backend) — affiché
  // sous l'input Balance tant qu'aucune valeur n'est saisie à la main.
  const balanceAutoApercu = useMemo(() => {
    if (
      f.montant_initial.trim() === "" ||
      f.taux_pct.trim() === "" ||
      !f.date_debut ||
      amortissementMois <= 0
    )
      return null;
    return computeBalanceCalculee(
      Number(f.montant_initial),
      Number(f.taux_pct),
      amortissementMois,
      compositionChoisie,
      f.date_debut
    );
  }, [
    f.montant_initial,
    f.taux_pct,
    f.date_debut,
    amortissementMois,
    compositionChoisie
  ]);

  // Fin du terme calculée = date_debut + terme (années, décimales OK).
  const finTermeCalculee = useMemo(() => {
    if (!f.date_debut || f.terme_annees.trim() === "") return null;
    const annees = Number(f.terme_annees);
    if (!Number.isFinite(annees) || annees <= 0) return null;
    return addAnneesIso(f.date_debut, annees);
  }, [f.date_debut, f.terme_annees]);

  const pmtDisplay = pmtOverride
    ? f.paiement_mensuel
    : computedPmt != null
      ? computedPmt.toFixed(2)
      : "";

  const pmtEffective =
    pmtOverride && f.paiement_mensuel.trim() !== ""
      ? Number(f.paiement_mensuel)
      : computedPmt != null
        ? Math.round(computedPmt * 100) / 100
        : null;

  const valid =
    f.preteur.trim() !== "" &&
    f.montant_initial.trim() !== "" &&
    !Number.isNaN(Number(f.montant_initial));

  function submit() {
    if (!valid) return;
    onSubmit({
      rang: f.rang.trim() ? Math.max(1, Math.round(Number(f.rang))) : 1,
      preteur: f.preteur.trim(),
      montant_initial: Number(f.montant_initial),
      balance_actuelle: f.balance_actuelle.trim()
        ? Number(f.balance_actuelle)
        : null,
      taux_pct: f.taux_pct.trim() ? Number(f.taux_pct) : null,
      type_taux: f.type_taux || null,
      composition_interets: compositionChoisie,
      amortissement_mois: amortissementMois > 0 ? amortissementMois : null,
      paiement_mensuel:
        pmtEffective != null && !Number.isNaN(pmtEffective) && pmtEffective >= 0
          ? pmtEffective
          : null,
      date_debut: f.date_debut || null,
      // Calculée = date_debut + terme. Sans date de début on ne peut
      // rien calculer : on préserve la fin de terme existante plutôt
      // que de l'effacer en silence.
      date_fin_terme:
        finTermeCalculee ??
        (!f.date_debut ? (initial?.date_fin_terme ?? null) : null),
      status: f.status,
      notes: f.notes.trim() || null
    });
  }

  const inputCls =
    "mt-0.5 block w-full rounded-md border border-brand-800 bg-brand-950 px-2 py-1.5 text-xs text-white outline-none focus:border-accent-500";
  const labelCls = "text-[11px] font-semibold text-white/60";

  return (
    <div className="rounded-2xl border border-brand-800 bg-brand-900 p-4">
      <p className="mb-3 text-sm font-semibold uppercase tracking-wider text-accent-500">
        {initial ? "Modifier l'hypothèque" : "Nouvelle hypothèque"}
      </p>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        <label className={labelCls}>
          Prêteur *
          <input
            value={f.preteur}
            onChange={(e) => set("preteur")(e.target.value)}
            placeholder="Desjardins, BNC…"
            className={inputCls}
          />
        </label>
        <label className={labelCls}>
          Rang
          <input
            type="number"
            min={1}
            max={9}
            value={f.rang}
            onChange={(e) => set("rang")(e.target.value)}
            className={inputCls}
          />
        </label>
        <label className={labelCls}>
          Statut
          <select
            value={f.status}
            onChange={(e) => set("status")(e.target.value)}
            className={inputCls}
          >
            {HYPO_STATUS.map(([v, l]) => (
              <option key={v} value={v} className="bg-brand-950 text-white">
                {l}
              </option>
            ))}
          </select>
        </label>
        <label className={labelCls}>
          Montant initial *
          <input
            inputMode="decimal"
            value={f.montant_initial}
            onChange={(e) => set("montant_initial")(e.target.value)}
            placeholder="0.00"
            className={inputCls}
          />
        </label>
        <label className={labelCls}>
          Balance actuelle
          <input
            inputMode="decimal"
            value={f.balance_actuelle}
            onChange={(e) => set("balance_actuelle")(e.target.value)}
            placeholder="Vide = calcul automatique"
            className={inputCls}
          />
          {f.balance_actuelle.trim() === "" && balanceAutoApercu != null ? (
            <span className="mt-1 block text-[10px] font-normal normal-case text-emerald-300">
              Auto : {fmtCurrency(balanceAutoApercu)} aujourd&apos;hui
              (amortissement depuis le début) — se met à jour chaque mois.
            </span>
          ) : f.balance_actuelle.trim() !== "" ? (
            <span className="mt-1 block text-[10px] font-normal normal-case text-white/40">
              Saisie manuelle — remplace le calcul automatique.
            </span>
          ) : null}
        </label>
        <label className={labelCls}>
          Taux (%)
          <input
            inputMode="decimal"
            value={f.taux_pct}
            onChange={(e) => set("taux_pct")(e.target.value)}
            placeholder="ex. 4.89"
            className={inputCls}
          />
        </label>
        <label className={labelCls}>
          Type de taux
          <select
            value={f.type_taux}
            onChange={(e) => set("type_taux")(e.target.value)}
            className={inputCls}
          >
            <option value="fixe" className="bg-brand-950 text-white">
              Fixe
            </option>
            <option value="variable" className="bg-brand-950 text-white">
              Variable
            </option>
          </select>
        </label>
        <label className={labelCls}>
          Composition des intérêts
          <select
            value={f.composition}
            onChange={(e) => set("composition")(e.target.value)}
            className={inputCls}
          >
            <option value="semi" className="bg-brand-950 text-white">
              Semi-annuelle (résidentiel)
            </option>
            <option value="mensuelle" className="bg-brand-950 text-white">
              Mensuelle (commercial / variable)
            </option>
          </select>
        </label>
        <label className={labelCls}>
          Amortissement (années)
          <input
            inputMode="decimal"
            value={f.amortissement_annees}
            onChange={(e) => set("amortissement_annees")(e.target.value)}
            placeholder="ex. 25"
            className={inputCls}
          />
        </label>
        <label className={labelCls}>
          Paiement mensuel ($)
          <input
            inputMode="decimal"
            value={pmtDisplay}
            onChange={(e) => {
              const v = e.target.value;
              setF((prev) => ({ ...prev, paiement_mensuel: v }));
              setPmtOverride(v.trim() !== "");
            }}
            placeholder="Auto-calculé"
            className={inputCls}
          />
        </label>
        <label className={labelCls}>
          Date de début
          <input
            type="date"
            value={f.date_debut}
            onChange={(e) => set("date_debut")(e.target.value)}
            className={inputCls}
          />
        </label>
        <label className={labelCls}>
          Terme (années)
          <input
            inputMode="decimal"
            value={f.terme_annees}
            onChange={(e) => set("terme_annees")(e.target.value)}
            placeholder="ex. 5"
            className={inputCls}
          />
          <span className="mt-1 block text-[10px] font-normal text-white/40">
            {finTermeCalculee
              ? `Fin du terme : ${finTermeCalculee}`
              : f.terme_annees.trim() !== "" && !f.date_debut
                ? "Renseigne la date de début pour calculer la fin du terme"
                : "Fin du terme = date de début + terme"}
          </span>
        </label>
        <label className={`${labelCls} sm:col-span-2 lg:col-span-3`}>
          Notes
          <textarea
            rows={2}
            value={f.notes}
            onChange={(e) => set("notes")(e.target.value)}
            placeholder="Clauses, pénalités, contact…"
            className={inputCls}
          />
        </label>
      </div>

      {computedPmt != null ? (
        <p className="mt-3 rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-xs text-emerald-300">
          Paiement mensuel calculé : {fmtCurrency(computedPmt)}
          <span className="ml-1 text-emerald-300/60">
            (composé{" "}
            {compositionChoisie === "mensuelle"
              ? "mensuellement"
              : "semi-annuellement"}
            {pmtOverride ? " — valeur surchargée manuellement" : ""})
          </span>
        </p>
      ) : (
        <p className="mt-3 text-[11px] text-white/40">
          Renseigne balance (ou montant initial), taux et amortissement pour
          calculer le paiement mensuel automatiquement.
        </p>
      )}
      <p className="mt-1.5 text-[10px] text-white/35">
        Résidentiel = composé semi-annuellement · Commercial/variable =
        mensuellement
      </p>

      <div className="mt-3 flex items-center justify-end gap-2 border-t border-brand-800 pt-3">
        <button
          type="button"
          onClick={onCancel}
          disabled={busy}
          className="btn-secondary btn-sm"
        >
          Annuler
        </button>
        <button
          type="button"
          onClick={submit}
          disabled={busy || !valid}
          className="btn-accent btn-sm disabled:opacity-50"
        >
          {busy ? (
            <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />
          ) : (
            <Check className="mr-1 h-3.5 w-3.5" />
          )}
          Enregistrer
        </button>
      </div>
    </div>
  );
}

function HypothequesTab({
  immeubleId,
  list,
  setList,
  onMutated
}: {
  immeubleId: number;
  list: Hypotheque[] | null;
  setList: React.Dispatch<React.SetStateAction<Hypotheque[] | null>>;
  onMutated: () => void;
}) {
  const [adding, setAdding] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  function sortHypos(arr: Hypotheque[]): Hypotheque[] {
    return [...arr].sort((a, b) => a.rang - b.rang || a.id - b.id);
  }

  async function create(payload: Record<string, unknown>) {
    setBusy(true);
    setErr(null);
    try {
      const res = await authedFetch("/api/v1/immobilier/hypotheques", {
        method: "POST",
        body: JSON.stringify({ immeuble_id: immeubleId, ...payload })
      });
      if (!res.ok)
        throw new Error((await res.text()).slice(0, 200) || `HTTP ${res.status}`);
      const created = (await res.json()) as Hypotheque;
      setList((prev) => sortHypos([...(prev || []), created]));
      setAdding(false);
      onMutated();
    } catch (e) {
      setErr(`Ajout échoué : ${(e as Error).message}`);
    } finally {
      setBusy(false);
    }
  }

  async function update(id: number, payload: Record<string, unknown>) {
    setBusy(true);
    setErr(null);
    try {
      const res = await authedFetch(`/api/v1/immobilier/hypotheques/${id}`, {
        method: "PATCH",
        body: JSON.stringify(payload)
      });
      if (!res.ok)
        throw new Error((await res.text()).slice(0, 200) || `HTTP ${res.status}`);
      const updated = (await res.json()) as Hypotheque;
      setList((prev) =>
        sortHypos((prev || []).map((h) => (h.id === id ? updated : h)))
      );
      setEditingId(null);
      onMutated();
    } catch (e) {
      setErr(`Modification échouée : ${(e as Error).message}`);
    } finally {
      setBusy(false);
    }
  }

  async function remove(h: Hypotheque) {
    if (
      !window.confirm(
        `Supprimer l'hypothèque « ${h.preteur} » (rang ${h.rang}) ?`
      )
    )
      return;
    setErr(null);
    const previous = list;
    // Optimiste : on retire tout de suite, rollback si le serveur refuse.
    setList((cur) => (cur || []).filter((x) => x.id !== h.id));
    try {
      const res = await authedFetch(
        `/api/v1/immobilier/hypotheques/${h.id}`,
        { method: "DELETE" }
      );
      if (!res.ok && res.status !== 204) throw new Error(`HTTP ${res.status}`);
      onMutated();
    } catch (e) {
      setList(previous);
      setErr(`Suppression échouée : ${(e as Error).message}`);
    }
  }

  if (list === null) return <Loading />;

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-xs text-white/50">
          {list.length} hypothèque{list.length > 1 ? "s" : ""}
        </p>
        {!adding ? (
          <button
            type="button"
            onClick={() => {
              setEditingId(null);
              setAdding(true);
            }}
            className="inline-flex items-center gap-1.5 rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-3 py-1.5 text-xs font-semibold text-emerald-300 hover:bg-emerald-500/20"
          >
            <Plus className="h-3.5 w-3.5" /> Ajouter une hypothèque
          </button>
        ) : null}
      </div>

      {err ? (
        <p className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">
          {err}
        </p>
      ) : null}

      {adding ? (
        <HypothequeForm
          initial={null}
          busy={busy}
          onCancel={() => setAdding(false)}
          onSubmit={(p) => void create(p)}
        />
      ) : null}

      {list.length === 0 && !adding ? (
        <Empty msg="Aucune hypothèque enregistrée." />
      ) : (
        <div className="grid gap-3">
          {list.map((h) =>
            editingId === h.id ? (
              <HypothequeForm
                key={h.id}
                initial={h}
                busy={busy}
                onCancel={() => setEditingId(null)}
                onSubmit={(p) => void update(h.id, p)}
              />
            ) : (
              <div
                key={h.id}
                className="rounded-2xl border border-brand-800 bg-brand-900 p-4"
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="flex flex-wrap items-center gap-2 text-sm font-bold text-white">
                      {h.preteur}
                      <span className="badge badge-neutral font-mono">
                        Rang {h.rang}
                      </span>
                      <span
                        className={`badge font-mono uppercase ${
                          HYPO_STATUS_BADGE[h.status] || "badge-neutral"
                        }`}
                      >
                        {HYPO_STATUS_LABEL[h.status] || h.status}
                      </span>
                    </p>
                    <p className="mt-1.5 flex flex-wrap items-center gap-2 text-xs text-white/50">
                      <span>
                        {h.taux_pct != null
                          ? `${h.taux_pct}% ${h.type_taux || ""}`.trim()
                          : "Taux ?"}
                      </span>
                      <TermeBadge
                        date={h.date_fin_terme}
                        dateDebut={h.date_debut}
                      />
                    </p>
                    {h.notes ? (
                      <p className="mt-2 text-xs text-white/60">{h.notes}</p>
                    ) : null}
                  </div>
                  <div className="flex flex-shrink-0 items-center gap-3">
                    <div className="text-right">
                      <div className="font-mono text-sm font-bold text-white">
                        {fmtCurrency(
                          h.balance_actuelle ??
                            h.balance_calculee ??
                            h.montant_initial
                        )}
                        {h.balance_actuelle == null &&
                        h.balance_calculee != null ? (
                          <span
                            className="ml-1.5 badge badge-neutral font-sans normal-case"
                            title="Balance calculée automatiquement depuis le tableau d'amortissement (montant initial, taux, date de début) — saisis une balance pour la remplacer."
                          >
                            auto
                          </span>
                        ) : null}
                      </div>
                      <div className="text-[11px] text-white/50">
                        Paiement {fmtCurrency(h.paiement_mensuel)}/m
                      </div>
                    </div>
                    <div className="flex flex-col gap-1">
                      <button
                        type="button"
                        onClick={() => {
                          setAdding(false);
                          setEditingId(h.id);
                        }}
                        className="btn-outline-accent btn-xs"
                        title="Modifier l'hypothèque"
                      >
                        <Pencil className="h-3 w-3" />
                      </button>
                      <button
                        type="button"
                        onClick={() => void remove(h)}
                        className="btn-outline-rose btn-xs"
                        title="Supprimer l'hypothèque"
                      >
                        <Trash2 className="h-3 w-3" />
                      </button>
                    </div>
                  </div>
                </div>
              </div>
            )
          )}
        </div>
      )}
    </div>
  );
}

const EVAL_KINDS: [string, string][] = [
  ["municipale", "Municipale"],
  ["marchande", "Marchande"],
  ["appraisal", "Rapport d'évaluateur"]
];

const EVAL_KIND_LABEL: Record<string, string> = {
  municipale: "Municipale",
  marchande: "Marchande",
  appraisal: "Rapport d'évaluateur",
  auto: "Auto"
};

const EVAL_KIND_BADGE: Record<string, string> = {
  municipale: "badge-sky",
  marchande: "badge-emerald",
  appraisal: "badge-violet",
  auto: "badge-neutral"
};

function EvaluationForm({
  busy,
  initial,
  onCancel,
  onSubmit
}: {
  busy: boolean;
  // Évaluation à MODIFIER — absente = création.
  initial?: Evaluation | null;
  onCancel: () => void;
  onSubmit: (payload: Record<string, unknown>) => void;
}) {
  const [f, setF] = useState({
    kind: initial?.kind ?? "marchande",
    valeur: initial != null ? String(initial.valeur) : "",
    date_evaluation:
      initial?.date_evaluation ?? new Date().toISOString().slice(0, 10),
    source: initial?.source ?? "",
    notes: initial?.notes ?? ""
  });

  const set = (k: keyof typeof f) => (v: string) =>
    setF((prev) => ({ ...prev, [k]: v }));

  const valid =
    f.valeur.trim() !== "" &&
    !Number.isNaN(Number(f.valeur)) &&
    Number(f.valeur) >= 0 &&
    f.date_evaluation !== "";

  function submit() {
    if (!valid) return;
    onSubmit({
      kind: f.kind,
      valeur: Number(f.valeur),
      date_evaluation: f.date_evaluation,
      source: f.source.trim() || null,
      notes: f.notes.trim() || null
    });
  }

  const inputCls =
    "mt-0.5 block w-full rounded-md border border-brand-800 bg-brand-950 px-2 py-1.5 text-xs text-white outline-none focus:border-accent-500";
  const labelCls = "text-[11px] font-semibold text-white/60";

  return (
    <div className="rounded-2xl border border-brand-800 bg-brand-900 p-4">
      <p className="mb-3 text-sm font-semibold uppercase tracking-wider text-accent-500">
        {initial
          ? `Modifier l'évaluation du ${initial.date_evaluation}`
          : "Nouvelle évaluation"}
      </p>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <label className={labelCls}>
          Type
          <select
            value={f.kind}
            onChange={(e) => set("kind")(e.target.value)}
            className={inputCls}
          >
            {EVAL_KINDS.map(([v, l]) => (
              <option key={v} value={v} className="bg-brand-950 text-white">
                {l}
              </option>
            ))}
          </select>
        </label>
        <label className={labelCls}>
          Valeur ($) *
          <input
            inputMode="decimal"
            value={f.valeur}
            onChange={(e) => set("valeur")(e.target.value)}
            placeholder="0.00"
            className={inputCls}
          />
        </label>
        <label className={labelCls}>
          Date *
          <input
            type="date"
            value={f.date_evaluation}
            onChange={(e) => set("date_evaluation")(e.target.value)}
            className={inputCls}
          />
        </label>
        <label className={labelCls}>
          Source
          <input
            value={f.source}
            onChange={(e) => set("source")(e.target.value)}
            placeholder="Évaluateur, rôle municipal…"
            className={inputCls}
          />
        </label>
        <label className={`${labelCls} sm:col-span-2 lg:col-span-4`}>
          Notes
          <textarea
            rows={2}
            value={f.notes}
            onChange={(e) => set("notes")(e.target.value)}
            placeholder="Contexte, méthode, détails…"
            className={inputCls}
          />
        </label>
      </div>

      <div className="mt-3 flex items-center justify-end gap-2 border-t border-brand-800 pt-3">
        <button
          type="button"
          onClick={onCancel}
          disabled={busy}
          className="btn-secondary btn-sm"
        >
          Annuler
        </button>
        <button
          type="button"
          onClick={submit}
          disabled={busy || !valid}
          className="btn-accent btn-sm disabled:opacity-50"
        >
          {busy ? (
            <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />
          ) : (
            <Check className="mr-1 h-3.5 w-3.5" />
          )}
          Enregistrer
        </button>
      </div>
    </div>
  );
}

function EvaluationsTab({
  immeubleId,
  list,
  setList,
  purchasePrice,
  balanceHypoActives,
  onMutated
}: {
  immeubleId: number;
  list: Evaluation[] | null;
  setList: React.Dispatch<React.SetStateAction<Evaluation[] | null>>;
  purchasePrice: number | null;
  balanceHypoActives: number;
  onMutated: () => void;
}) {
  const [adding, setAdding] = useState(false);
  const [editingEval, setEditingEval] = useState<Evaluation | null>(null);
  const [busy, setBusy] = useState(false);
  const [refBusyId, setRefBusyId] = useState<number | null>(null);
  const [err, setErr] = useState<string | null>(null);

  function sortEvals(arr: Evaluation[]): Evaluation[] {
    return [...arr].sort(
      (a, b) =>
        b.date_evaluation.localeCompare(a.date_evaluation) || b.id - a.id
    );
  }

  async function setReference(ev: Evaluation) {
    if (ev.is_reference || refBusyId != null) return;
    setRefBusyId(ev.id);
    setErr(null);
    try {
      const res = await authedFetch(
        `/api/v1/immobilier/evaluations/${ev.id}`,
        { method: "PATCH", body: JSON.stringify({ is_reference: true }) }
      );
      if (!res.ok)
        throw new Error((await res.text()).slice(0, 200) || `HTTP ${res.status}`);
      // Recharge la liste : le backend a décoché les autres références.
      const r = await authedFetch(
        `/api/v1/immobilier/immeubles/${immeubleId}/evaluations`
      );
      if (r.ok) {
        setList((await r.json()) as Evaluation[]);
      } else {
        const updated = (await res.json()) as Evaluation;
        setList((prev) =>
          (prev || []).map((x) =>
            x.id === updated.id ? updated : { ...x, is_reference: false }
          )
        );
      }
      onMutated();
    } catch (e) {
      setErr(`Référence échouée : ${(e as Error).message}`);
    } finally {
      setRefBusyId(null);
    }
  }

  async function create(payload: Record<string, unknown>) {
    setBusy(true);
    setErr(null);
    try {
      const res = await authedFetch("/api/v1/immobilier/evaluations", {
        method: "POST",
        body: JSON.stringify({ immeuble_id: immeubleId, ...payload })
      });
      if (!res.ok)
        throw new Error((await res.text()).slice(0, 200) || `HTTP ${res.status}`);
      const created = (await res.json()) as Evaluation;
      setList((prev) => sortEvals([...(prev || []), created]));
      setAdding(false);
      onMutated();
    } catch (e) {
      setErr(`Ajout échoué : ${(e as Error).message}`);
    } finally {
      setBusy(false);
    }
  }

  async function saveEdit(evalId: number, payload: Record<string, unknown>) {
    setBusy(true);
    setErr(null);
    try {
      const res = await authedFetch(
        `/api/v1/immobilier/evaluations/${evalId}`,
        { method: "PATCH", body: JSON.stringify(payload) }
      );
      if (!res.ok)
        throw new Error((await res.text()).slice(0, 200) || `HTTP ${res.status}`);
      const updated = (await res.json()) as Evaluation;
      setList((prev) =>
        sortEvals((prev || []).map((x) => (x.id === updated.id ? updated : x)))
      );
      setEditingEval(null);
      // L'équité/valorisation du haut suit la nouvelle valeur.
      onMutated();
    } catch (e) {
      setErr(`Modification échouée : ${(e as Error).message}`);
    } finally {
      setBusy(false);
    }
  }

  async function remove(ev: Evaluation) {
    if (
      !window.confirm(
        `Supprimer l'évaluation « ${EVAL_KIND_LABEL[ev.kind] || ev.kind} » du ${ev.date_evaluation} (${fmtCurrency(ev.valeur)}) ?`
      )
    )
      return;
    setErr(null);
    const previous = list;
    // Optimiste : on retire tout de suite, rollback si le serveur refuse.
    setList((cur) => (cur || []).filter((x) => x.id !== ev.id));
    try {
      const res = await authedFetch(
        `/api/v1/immobilier/evaluations/${ev.id}`,
        { method: "DELETE" }
      );
      if (!res.ok && res.status !== 204) throw new Error(`HTTP ${res.status}`);
      onMutated();
    } catch (e) {
      setList(previous);
      setErr(`Suppression échouée : ${(e as Error).message}`);
    }
  }

  if (list === null) return <Loading />;

  const sorted = sortEvals(list);
  // Évaluation retenue : la référence prime, sinon la plus récente
  // (même logique que l'équité des tuiles du haut / backend).
  const last = list.find((e) => e.is_reference) || sorted[0] || null;
  const croissance =
    last && purchasePrice && purchasePrice > 0
      ? ((last.valeur - purchasePrice) / purchasePrice) * 100
      : null;
  const equite = last ? last.valeur - balanceHypoActives : null;

  return (
    <div className="space-y-3">
      {last ? (
        <div className="grid gap-3 sm:grid-cols-3">
          <Kpi
            label={last.is_reference ? "Valeur de référence" : "Dernière valeur"}
            value={fmtCurrency(last.valeur)}
            sub={`${EVAL_KIND_LABEL[last.kind] || last.kind} — ${last.date_evaluation}`}
            icon={DollarSign}
            tone="sky"
          />
          <Kpi
            label="Croissance vs achat"
            value={fmtPct(croissance, 1)}
            sub={
              purchasePrice
                ? `Prix d'achat ${fmtCurrency(purchasePrice)}`
                : "Prix d'achat inconnu"
            }
            icon={TrendingUp}
            tone={croissance != null && croissance < 0 ? "rose" : "emerald"}
          />
          <Kpi
            label="Équité"
            value={fmtCurrency(equite)}
            sub={`Hyp. actives ${fmtCurrency(balanceHypoActives)}`}
            icon={Banknote}
            tone={(equite ?? 0) >= 0 ? "emerald" : "rose"}
          />
        </div>
      ) : null}

      <div className="flex items-center justify-between">
        <p className="text-xs text-white/50">
          {list.length} évaluation{list.length > 1 ? "s" : ""}
        </p>
        {!adding && !editingEval ? (
          <button
            type="button"
            onClick={() => setAdding(true)}
            className="inline-flex items-center gap-1.5 rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-3 py-1.5 text-xs font-semibold text-emerald-300 hover:bg-emerald-500/20"
          >
            <Plus className="h-3.5 w-3.5" /> Ajouter une évaluation
          </button>
        ) : null}
      </div>

      {err ? (
        <p className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">
          {err}
        </p>
      ) : null}

      {adding || editingEval ? (
        <EvaluationForm
          // key : réinitialise le formulaire quand on change de cible.
          key={editingEval?.id ?? "new"}
          busy={busy}
          initial={editingEval}
          onCancel={() => {
            setAdding(false);
            setEditingEval(null);
          }}
          onSubmit={(p) =>
            void (editingEval ? saveEdit(editingEval.id, p) : create(p))
          }
        />
      ) : null}

      {sorted.length === 0 && !adding ? (
        <Empty msg="Aucune évaluation." />
      ) : sorted.length > 0 ? (
        <div className="overflow-hidden rounded-2xl border border-brand-800 bg-brand-900">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-brand-800 bg-brand-950 text-[10px] uppercase tracking-wider text-white/50">
              <tr>
                <th className="px-4 py-2.5">Date</th>
                <th className="px-4 py-2.5">Type</th>
                <th className="px-4 py-2.5 text-right">Valeur</th>
                <th className="px-4 py-2.5">Source</th>
                <th className="px-4 py-2.5">Notes</th>
                <th className="px-4 py-2.5">Référence</th>
                <th className="px-4 py-2.5 text-right"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-brand-800">
              {sorted.map((e) => (
                <tr key={e.id}>
                  <td className="px-4 py-2 font-mono text-xs text-white/70">
                    {e.date_evaluation}
                  </td>
                  <td className="px-4 py-2 text-xs">
                    <span
                      className={`badge ${EVAL_KIND_BADGE[e.kind] || "badge-neutral"}`}
                    >
                      {EVAL_KIND_LABEL[e.kind] || e.kind}
                    </span>
                  </td>
                  <td className="px-4 py-2 text-right font-mono text-sm font-bold text-white">
                    {fmtCurrency(e.valeur)}
                  </td>
                  <td className="px-4 py-2 text-xs text-white/50">
                    {e.source || "—"}
                  </td>
                  <td
                    className="max-w-[240px] truncate px-4 py-2 text-xs text-white/50"
                    title={e.notes || undefined}
                  >
                    {e.notes || "—"}
                  </td>
                  <td className="px-4 py-2 text-xs">
                    {e.is_reference ? (
                      <span
                        className="badge badge-amber"
                        title="Évaluation utilisée pour le calcul d'équité"
                      >
                        <Star className="h-3 w-3 fill-current" /> Référence
                      </span>
                    ) : (
                      <button
                        type="button"
                        onClick={() => void setReference(e)}
                        disabled={refBusyId != null}
                        className="inline-flex items-center gap-1 rounded-md border border-brand-700 px-2 py-1 text-[11px] font-semibold text-white/50 transition hover:border-amber-400/50 hover:text-amber-300 disabled:opacity-50"
                        title="Utiliser cette évaluation comme référence pour l'équité"
                      >
                        {refBusyId === e.id ? (
                          <Loader2 className="h-3 w-3 animate-spin" />
                        ) : (
                          <Star className="h-3 w-3" />
                        )}
                        Référence
                      </button>
                    )}
                  </td>
                  <td className="px-4 py-2 text-right">
                    <span className="inline-flex items-center gap-1.5">
                      <button
                        type="button"
                        onClick={() => {
                          setAdding(false);
                          setEditingEval(e);
                        }}
                        className="btn-secondary btn-xs"
                        title="Modifier l'évaluation"
                      >
                        <Pencil className="h-3 w-3" />
                      </button>
                      <button
                        type="button"
                        onClick={() => void remove(e)}
                        className="btn-outline-rose btn-xs"
                        title="Supprimer l'évaluation"
                      >
                        <Trash2 className="h-3 w-3" />
                      </button>
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </div>
  );
}

// ─── Cashflow ────────────────────────────────────────────────────────────

type Depense = {
  id: number;
  immeuble_id: number;
  categorie: string;
  libelle: string;
  montant: number;
  frequence: string;
  // montant = % des loyers mensuels (ex. gestion à 5 %) au lieu d'un $.
  is_pourcentage?: boolean;
  // taxable = TPS+TVQ Québec appliquées (×1.14975) dans les calculs.
  taxable?: boolean;
  date_depense: string | null;
  notes: string | null;
};

// TPS 5 % + TVQ 9,975 % (Québec) — même facteur que le backend.
const TAUX_TAXES = 1.14975;

/**
 * Montant mensuel effectif d'une dépense récurrente — mêmes formules
 * que le backend (/financials) : % des loyers d'abord, fréquence
 * ensuite (annuel ÷ 12), taxes à la fin (×1.14975 si taxable).
 */
function montantMensuelDepense(d: Depense, revenusMensuel: number): number {
  let m = d.is_pourcentage
    ? (revenusMensuel * (d.montant || 0)) / 100
    : d.montant || 0;
  if (d.frequence === "annuel") m = m / 12;
  if (d.taxable) m *= TAUX_TAXES;
  return m;
}

const DEPENSE_CATEGORIES: [string, string][] = [
  ["taxes_municipales", "Taxes municipales"],
  ["taxes_scolaires", "Taxes scolaires"],
  ["assurances", "Assurances"],
  ["energie", "Énergie"],
  ["entretien", "Entretien"],
  ["deneigement", "Déneigement"],
  ["conciergerie", "Conciergerie"],
  ["gestion", "Gestion"],
  ["autre", "Autre"]
];

const DEPENSE_CAT_LABEL: Record<string, string> =
  Object.fromEntries(DEPENSE_CATEGORIES);

function CashflowTab({
  immeubleId,
  baux,
  logements,
  hypotheques,
  onMutated
}: {
  immeubleId: number;
  baux: Bail[] | null;
  logements: Logement[] | null;
  hypotheques: Hypotheque[] | null;
  onMutated: () => void;
}) {
  const [depenses, setDepenses] = useState<Depense[] | null>(null);
  const [mode, setMode] = useState<"mensuel" | "annuel">("mensuel");
  const [adding, setAdding] = useState(false);
  const [editing, setEditing] = useState<Depense | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [fCat, setFCat] = useState("taxes_municipales");
  const [fLib, setFLib] = useState("");
  const [fMontant, setFMontant] = useState("");
  const [fFreq, setFFreq] = useState("annuel");
  const [fPct, setFPct] = useState(false);
  const [fTaxable, setFTaxable] = useState(false);

  useEffect(() => {
    let cancelled = false;
    authedFetch(`/api/v1/immobilier/immeubles/${immeubleId}/depenses`)
      .then((r) => (r.ok ? r.json() : []))
      .then((d) => {
        if (!cancelled) setDepenses(Array.isArray(d) ? d : []);
      })
      .catch(() => {
        if (!cancelled) setDepenses([]);
      });
    return () => {
      cancelled = true;
    };
  }, [immeubleId]);

  // Récurrentes seulement : le cashflow est un flux mensuel/annuel
  // régulier (les ponctuelles vivent dans Finances).
  const recurrentes = useMemo(
    () =>
      (depenses || []).filter(
        (d) => d.frequence === "mensuel" || d.frequence === "annuel"
      ),
    [depenses]
  );
  const nbPonctuelles = (depenses || []).length - recurrentes.length;

  // Revenus PAR LOGEMENT, même logique que le backend (financials) :
  // bail actif → son loyer ; sinon statut « occupé » → loyer demandé
  // (gestion externe : les baux vivent chez le gestionnaire). Le
  // potentiel « toutes unités » ajoute les vacantes au loyer demandé.
  const bauxActifs = (baux || []).filter((b) => b.status === "actif");
  const loyerBailParLogement = new Map<number, number>();
  for (const b of bauxActifs) {
    loyerBailParLogement.set(
      b.logement_id,
      (loyerBailParLogement.get(b.logement_id) || 0) + (b.loyer_mensuel || 0)
    );
  }
  let revenusMensuel = 0; // unités louées seulement
  let revenusToutesUnites = 0;
  let nbUnitesLouees = 0;
  for (const lg of logements || []) {
    const loyerBail = loyerBailParLogement.get(lg.id);
    if (loyerBail != null) {
      revenusMensuel += loyerBail;
      revenusToutesUnites += loyerBail;
      nbUnitesLouees += 1;
    } else if (lg.status !== "hors_location" && lg.loyer_demande != null) {
      revenusToutesUnites += lg.loyer_demande;
      if (lg.status === "occupe") {
        revenusMensuel += lg.loyer_demande;
        nbUnitesLouees += 1;
      }
    }
  }
  // Filet : baux actifs orphelins (logements pas encore chargés/supprimés).
  if ((logements || []).length === 0 && bauxActifs.length > 0) {
    revenusMensuel = bauxActifs.reduce((s, b) => s + (b.loyer_mensuel || 0), 0);
    revenusToutesUnites = revenusMensuel;
    nbUnitesLouees = bauxActifs.length;
  }
  // Mensualisation (mêmes règles que le backend) : % des loyers,
  // annuel ÷ 12, ×1.14975 si taxable.
  const depensesMensuelles = recurrentes.reduce(
    (s, d) => s + montantMensuelDepense(d, revenusMensuel),
    0
  );
  const hyposActives = (hypotheques || []).filter(
    (h) => h.status === "active"
  );
  const hypoMensuel = hyposActives.reduce(
    (s, h) => s + (h.paiement_mensuel ?? 0),
    0
  );

  const facteur = mode === "mensuel" ? 1 : 12;
  const revenus = revenusMensuel * facteur;
  const revenusToutes = revenusToutesUnites * facteur;
  const depensesAffichees = depensesMensuelles * facteur;
  const hypo = hypoMensuel * facteur;
  const cashflow = revenus - depensesAffichees - hypo;
  const suffixe = mode === "mensuel" ? "/mois" : "/an";

  function montantSelonMode(d: Depense): number {
    return montantMensuelDepense(d, revenusMensuel) * facteur;
  }

  function resetForm() {
    setFCat("taxes_municipales");
    setFLib("");
    setFMontant("");
    setFFreq("annuel");
    setFPct(false);
    setFTaxable(false);
    setAdding(false);
    setEditing(null);
  }

  function startEdit(d: Depense) {
    setFCat(d.categorie);
    setFLib(d.libelle);
    setFMontant(String(d.montant));
    setFFreq(d.frequence);
    setFPct(!!d.is_pourcentage);
    setFTaxable(!!d.taxable);
    setEditing(d);
    setAdding(true);
    setErr(null);
  }

  async function save() {
    if (
      !fLib.trim() ||
      !fMontant.trim() ||
      Number.isNaN(Number(fMontant)) ||
      Number(fMontant) < 0
    )
      return;
    setBusy(true);
    setErr(null);
    const payload: Record<string, unknown> = {
      categorie: fCat,
      libelle: fLib.trim(),
      // Stockée telle que saisie (fréquence + montant ou %), la
      // conversion ×12/÷12/% est purement affichage.
      montant: Number(fMontant),
      frequence: fFreq,
      is_pourcentage: fPct,
      taxable: fTaxable
    };
    // À la création on force date_depense=null (récurrente) ; en édition
    // on n'y touche pas (le PUT est en exclude_unset côté serveur).
    if (!editing) payload.date_depense = null;
    try {
      const res = await authedFetch(
        editing
          ? `/api/v1/immobilier/depenses/${editing.id}`
          : `/api/v1/immobilier/immeubles/${immeubleId}/depenses`,
        {
          method: editing ? "PUT" : "POST",
          body: JSON.stringify(payload)
        }
      );
      if (!res.ok)
        throw new Error((await res.text()).slice(0, 200) || `HTTP ${res.status}`);
      const saved = (await res.json()) as Depense;
      setDepenses((prev) =>
        editing
          ? (prev || []).map((x) => (x.id === saved.id ? saved : x))
          : [saved, ...(prev || [])]
      );
      resetForm();
      // Le KPI cashflow du haut doit suivre immédiatement.
      onMutated();
    } catch (e) {
      setErr(
        `${editing ? "Modification échouée" : "Ajout échoué"} : ${(e as Error).message}`
      );
    } finally {
      setBusy(false);
    }
  }

  async function remove(d: Depense) {
    if (!window.confirm(`Supprimer la dépense « ${d.libelle} » ?`)) return;
    setErr(null);
    const previous = depenses;
    // Optimiste : on retire tout de suite, rollback si le serveur refuse.
    setDepenses((cur) => (cur || []).filter((x) => x.id !== d.id));
    try {
      const res = await authedFetch(`/api/v1/immobilier/depenses/${d.id}`, {
        method: "DELETE"
      });
      if (!res.ok && res.status !== 204) throw new Error(`HTTP ${res.status}`);
      // Le KPI cashflow du haut doit suivre immédiatement.
      onMutated();
    } catch (e) {
      setDepenses(previous);
      setErr(`Suppression échouée : ${(e as Error).message}`);
    }
  }

  if (depenses === null) return <Loading />;

  const inputCls =
    "mt-0.5 block w-full rounded-md border border-brand-800 bg-brand-950 px-2 py-1.5 text-xs text-white outline-none focus:border-accent-500";
  const labelCls = "text-[11px] font-semibold text-white/60";

  return (
    <div className="space-y-4">
      {/* Toggle Mensuel / Annuel */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-xs text-white/50">
          Cashflow récurrent — unités louées, dépenses récurrentes et
          hypothèques actives.
        </p>
        <div className="inline-flex rounded-lg border border-brand-800 bg-brand-950 p-0.5">
          {(["mensuel", "annuel"] as const).map((m) => (
            <button
              key={m}
              type="button"
              onClick={() => setMode(m)}
              className={`rounded-md px-3 py-1 text-xs font-semibold transition ${
                mode === m
                  ? "bg-accent-500/20 text-accent-500"
                  : "text-white/50 hover:text-white"
              }`}
            >
              {m === "mensuel" ? "Mensuel" : "Annuel"}
            </button>
          ))}
        </div>
      </div>

      {/* Sommaire */}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Kpi
          label={`Revenus ${suffixe}`}
          value={
            <span className="flex flex-wrap items-baseline gap-x-2">
              {fmtCurrency(revenus)}
              <span
                className="text-xs font-normal text-white/50"
                title="Potentiel toutes unités (louées + vacantes au loyer demandé)"
              >
                {fmtCurrency(revenusToutes)} toutes unités
              </span>
            </span>
          }
          sub={`${nbUnitesLouees} unité${nbUnitesLouees > 1 ? "s" : ""} louée${nbUnitesLouees > 1 ? "s" : ""}`}
          icon={TrendingUp}
          tone="sky"
        />
        <Kpi
          label={`Dépenses ${suffixe}`}
          value={fmtCurrency(depensesAffichees)}
          sub={`${recurrentes.length} dépense${recurrentes.length > 1 ? "s" : ""} récurrente${recurrentes.length > 1 ? "s" : ""}`}
          icon={Receipt}
          tone="amber"
        />
        <Kpi
          label={`Hypothèque ${suffixe}`}
          value={fmtCurrency(hypo)}
          sub={`${hyposActives.length} hypothèque${hyposActives.length > 1 ? "s" : ""} active${hyposActives.length > 1 ? "s" : ""} · auto`}
          icon={Banknote}
          tone="rose"
        />
        {/* Tuile cashflow mise en avant */}
        <div
          className={`rounded-xl border p-5 ${
            cashflow >= 0
              ? "border-emerald-500/40 bg-emerald-500/10"
              : "border-rose-500/40 bg-rose-500/10"
          }`}
        >
          <div className="flex items-center justify-between">
            <span
              className={`text-[10px] font-semibold uppercase tracking-wider ${
                cashflow >= 0 ? "text-emerald-300/80" : "text-rose-300/80"
              }`}
            >
              Cashflow {suffixe}
            </span>
            <span
              className={`flex h-8 w-8 items-center justify-center rounded-lg ${
                cashflow >= 0
                  ? "bg-emerald-500/15 text-emerald-300"
                  : "bg-rose-500/15 text-rose-300"
              }`}
            >
              <Wallet className="h-4 w-4" />
            </span>
          </div>
          <div
            className={`mt-3 text-2xl font-bold ${
              cashflow >= 0 ? "text-emerald-300" : "text-rose-300"
            }`}
          >
            {fmtCurrency(cashflow)}
          </div>
          <div
            className={`mt-1 text-xs ${
              cashflow >= 0 ? "text-emerald-300/60" : "text-rose-300/60"
            }`}
          >
            Revenus − Dépenses − Hypothèque
          </div>
        </div>
      </div>

      {/* Dépenses récurrentes */}
      <Section title="Dépenses récurrentes">
        <div className="flex items-center justify-between">
          <p className="text-xs text-white/50">
            {recurrentes.length} dépense{recurrentes.length > 1 ? "s" : ""}{" "}
            récurrente{recurrentes.length > 1 ? "s" : ""}
            {nbPonctuelles > 0
              ? ` · ${nbPonctuelles} ponctuelle${nbPonctuelles > 1 ? "s" : ""} non incluse${nbPonctuelles > 1 ? "s" : ""} (voir Finances)`
              : ""}
          </p>
          {!adding ? (
            <button
              type="button"
              onClick={() => setAdding(true)}
              className="inline-flex items-center gap-1.5 rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-3 py-1.5 text-xs font-semibold text-emerald-300 hover:bg-emerald-500/20"
            >
              <Plus className="h-3.5 w-3.5" /> Ajouter une dépense
            </button>
          ) : null}
        </div>

        {err ? (
          <p className="mt-2 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">
            {err}
          </p>
        ) : null}

        {adding ? (
          <div className="mt-3 rounded-2xl border border-brand-800 bg-brand-950/60 p-4">
            {editing ? (
              <p className="mb-3 text-xs font-semibold text-accent-500">
                Modifier « {editing.libelle} »
              </p>
            ) : null}
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <label className={labelCls}>
                Catégorie
                <select
                  value={fCat}
                  onChange={(e) => setFCat(e.target.value)}
                  className={inputCls}
                >
                  {DEPENSE_CATEGORIES.map(([v, l]) => (
                    <option
                      key={v}
                      value={v}
                      className="bg-brand-950 text-white"
                    >
                      {l}
                    </option>
                  ))}
                </select>
              </label>
              <label className={labelCls}>
                Libellé *
                <input
                  value={fLib}
                  onChange={(e) => setFLib(e.target.value)}
                  placeholder="Taxes 2026, assurance bâtiment…"
                  className={inputCls}
                />
              </label>
              <label className={labelCls}>
                {fPct ? "% des loyers *" : "Montant ($) *"}
                <input
                  inputMode="decimal"
                  value={fMontant}
                  onChange={(e) => setFMontant(e.target.value)}
                  placeholder={fPct ? "ex. 5" : "0.00"}
                  className={inputCls}
                />
              </label>
              <label className={labelCls}>
                Fréquence
                <select
                  value={fFreq}
                  onChange={(e) => setFFreq(e.target.value)}
                  className={inputCls}
                >
                  <option value="mensuel" className="bg-brand-950 text-white">
                    Mensuel
                  </option>
                  <option value="annuel" className="bg-brand-950 text-white">
                    Annuel
                  </option>
                </select>
              </label>
            </div>
            <div className="mt-3 flex flex-wrap items-center gap-x-5 gap-y-2">
              <label className="flex cursor-pointer items-center gap-2 text-xs text-white/80">
                <input
                  type="checkbox"
                  checked={fPct}
                  onChange={(e) => setFPct(e.target.checked)}
                  className="h-3.5 w-3.5 accent-accent-500"
                />
                Montant en % des loyers
                <span className="text-[10px] text-white/40">
                  (ex. gestion à 5 %)
                </span>
              </label>
              <label className="flex cursor-pointer items-center gap-2 text-xs text-white/80">
                <input
                  type="checkbox"
                  checked={fTaxable}
                  onChange={(e) => setFTaxable(e.target.checked)}
                  className="h-3.5 w-3.5 accent-accent-500"
                />
                Taxable
                <span className="text-[10px] text-white/40">
                  (TPS+TVQ ×1.14975)
                </span>
              </label>
            </div>
            {fMontant.trim() !== "" &&
            !Number.isNaN(Number(fMontant)) &&
            (fPct || fTaxable) ? (
              <p className="mt-2 rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-xs text-emerald-300">
                Montant effectif :{" "}
                {fmtCurrency(
                  montantMensuelDepense(
                    {
                      id: 0,
                      immeuble_id: immeubleId,
                      categorie: fCat,
                      libelle: "",
                      montant: Number(fMontant),
                      frequence: fFreq,
                      is_pourcentage: fPct,
                      taxable: fTaxable,
                      date_depense: null,
                      notes: null
                    },
                    revenusMensuel
                  )
                )}
                /mois
                {fPct
                  ? ` (${Number(fMontant)} % × ${fmtCurrency(revenusMensuel)} de loyers)`
                  : ""}
                {fTaxable ? " · taxes incluses" : ""}
              </p>
            ) : null}
            <div className="mt-3 flex items-center justify-end gap-2 border-t border-brand-800 pt-3">
              <button
                type="button"
                onClick={resetForm}
                disabled={busy}
                className="btn-secondary btn-sm"
              >
                Annuler
              </button>
              <button
                type="button"
                onClick={() => void save()}
                disabled={
                  busy ||
                  !fLib.trim() ||
                  !fMontant.trim() ||
                  Number.isNaN(Number(fMontant))
                }
                className="btn-accent btn-sm disabled:opacity-50"
              >
                {busy ? (
                  <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Check className="mr-1 h-3.5 w-3.5" />
                )}
                Enregistrer
              </button>
            </div>
          </div>
        ) : null}

        {recurrentes.length === 0 && hypoMensuel <= 0 && !adding ? (
          <p className="mt-3 rounded-lg border border-brand-800 bg-brand-950/60 px-4 py-3 text-sm text-white/60">
            Aucune dépense récurrente — ajoute taxes, assurances,
            déneigement… pour un cashflow réaliste.
          </p>
        ) : (
          <ul className="mt-3 divide-y divide-brand-800 rounded-lg border border-brand-800">
            {recurrentes.map((d) => (
              <li
                key={d.id}
                className="flex items-center justify-between gap-2 px-3 py-2 text-xs"
              >
                <span className="min-w-0">
                  <span className="font-medium text-white/80">
                    {d.libelle}
                  </span>
                  <span className="badge badge-neutral ml-2">
                    {DEPENSE_CAT_LABEL[d.categorie] || d.categorie}
                  </span>
                  {d.taxable ? (
                    <span
                      className="badge badge-sky ml-1.5"
                      title="TPS+TVQ appliquées (×1.14975)"
                    >
                      +tx
                    </span>
                  ) : null}
                </span>
                <span className="flex flex-shrink-0 items-center gap-2">
                  <span className="text-right">
                    <span className="font-mono font-semibold text-white">
                      {fmtCurrency(montantSelonMode(d))}
                      {suffixe}
                    </span>
                    <span className="ml-2 text-[10px] text-white/40">
                      saisi{" "}
                      {d.is_pourcentage
                        ? `${d.montant} % des loyers`
                        : fmtCurrency(d.montant)}
                      {d.frequence === "mensuel" ? "/mois" : "/an"}
                      {d.taxable ? " +tx" : ""}
                    </span>
                  </span>
                  <button
                    type="button"
                    onClick={() => startEdit(d)}
                    className="btn-secondary btn-xs"
                    title="Modifier la dépense"
                  >
                    <Pencil className="h-3 w-3" />
                  </button>
                  <button
                    type="button"
                    onClick={() => void remove(d)}
                    className="btn-outline-rose btn-xs"
                    title="Supprimer la dépense"
                  >
                    <Trash2 className="h-3 w-3" />
                  </button>
                </span>
              </li>
            ))}
            {hypoMensuel > 0 ? (
              <li className="flex items-center justify-between gap-2 bg-brand-950/60 px-3 py-2 text-xs opacity-70">
                <span className="min-w-0">
                  <span className="font-medium text-white/60">
                    Hypothèque
                  </span>
                  <span className="badge badge-neutral ml-2">auto</span>
                  <span className="ml-2 text-[10px] text-white/40">
                    calculée depuis l&apos;onglet Hypothèques
                  </span>
                </span>
                <span className="flex-shrink-0 font-mono font-semibold text-white/60">
                  {fmtCurrency(hypo)}
                  {suffixe}
                </span>
              </li>
            ) : null}
          </ul>
        )}
      </Section>
    </div>
  );
}

function MaintenanceTab({
  list,
  rollup
}: {
  list: Maintenance[] | null;
  rollup: RollupImmeuble | null;
}) {
  // Filtre : "all" = immeuble entier, "communs", ou l'id d'un logement.
  const [filter, setFilter] = useState<string>("all");

  const filteredTotal =
    !rollup || filter === "all"
      ? rollup?.total ?? 0
      : filter === "communs"
        ? rollup.communs_total
        : rollup.logements.find((l) => String(l.logement_id) === filter)
            ?.total ?? 0;

  const expenses =
    rollup && (rollup.total > 0 || rollup.count > 0) ? (
      <div className="rounded-2xl border border-brand-800 bg-brand-900 p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h3 className="text-sm font-semibold uppercase tracking-wider text-amber-300">
            Dépenses de maintenance — année en cours
          </h3>
          <span className="text-xl font-bold text-amber-200">
            {fmtCurrency(filteredTotal)}
          </span>
        </div>
        <div className="mt-2">
          <select
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            className="w-full rounded-lg border border-brand-800 bg-brand-950 px-3 py-2 text-sm text-white outline-none focus:border-amber-300 sm:w-64"
          >
            <option value="all">Tout l&apos;immeuble</option>
            {(rollup.communs_count ?? 0) > 0 ? (
              <option value="communs">Communs / immeuble entier</option>
            ) : null}
            {rollup.logements.map((l) => (
              <option
                key={l.logement_id ?? "x"}
                value={String(l.logement_id)}
              >
                App {l.numero || "—"}
              </option>
            ))}
          </select>
        </div>
        {filter === "all" &&
        (rollup.logements.length > 0 || (rollup.communs_count ?? 0) > 0) ? (
          <div className="mt-3 space-y-1 border-t border-brand-800 pt-3 text-sm">
            {rollup.logements.map((l) => (
              <div
                key={l.logement_id ?? "communs"}
                className="flex items-center justify-between text-white/70"
              >
                <span>App {l.numero || "—"}</span>
                <span className="text-white">{fmtCurrency(l.total)}</span>
              </div>
            ))}
            {(rollup.communs_count ?? 0) > 0 ? (
              <div className="flex items-center justify-between text-white/70">
                <span>Communs / immeuble entier</span>
                <span className="text-white">
                  {fmtCurrency(rollup.communs_total)}
                </span>
              </div>
            ) : null}
          </div>
        ) : null}
      </div>
    ) : null;

  if (list === null)
    return (
      <div className="space-y-6">
        {expenses}
        <Loading />
      </div>
    );
  if (list.length === 0)
    return (
      <div className="space-y-6">
        {expenses}
        <Empty msg="Aucun ordre de maintenance." />
      </div>
    );
  return (
    <div className="space-y-6">
      {expenses}
      <div className="overflow-hidden rounded-2xl border border-brand-800 bg-brand-900">
        <table className="w-full text-left text-sm">
        <thead className="border-b border-brand-800 bg-brand-950 text-[10px] uppercase tracking-wider text-white/50">
          <tr>
            <th className="px-4 py-2.5">Titre</th>
            <th className="px-4 py-2.5">Priorité</th>
            <th className="px-4 py-2.5">Statut</th>
            <th className="px-4 py-2.5">Planifié</th>
            <th className="px-4 py-2.5 text-right">Coût</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-brand-800">
          {list.map((m) => (
            <tr key={m.id}>
              <td className="px-4 py-2 text-sm font-bold text-white">
                {m.titre}
              </td>
              <td className="px-4 py-2 text-xs">
                <PrioriteBadge priorite={m.priorite} />
              </td>
              <td className="px-4 py-2 text-xs">
                <StatusBadge status={m.status} />
              </td>
              <td className="px-4 py-2 text-xs text-white/60">
                <Calendar className="mr-1 inline h-3 w-3 text-white/40" />
                {m.plannifie_pour || "—"}
              </td>
              <td className="px-4 py-2 text-right font-mono text-xs text-white/70">
                {fmtCurrency(m.cout_reel ?? m.cout_estime)}
              </td>
            </tr>
          ))}
        </tbody>
        </table>
      </div>
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const map: Record<string, string> = {
    occupe: "badge-emerald",
    actif: "badge-emerald",
    vacant: "badge-amber",
    reserve: "badge-sky",
    propose: "badge-sky",
    termine: "badge-neutral",
    resilie: "badge-rose",
    hors_location: "badge-neutral",
    ouvert: "badge-amber",
    en_cours: "badge-sky",
    en_attente: "badge-violet",
    annule: "badge-neutral"
  };
  const cls = map[status] || "badge-neutral";
  return (
    <span className={`badge font-mono uppercase ${cls}`}>
      {status}
    </span>
  );
}

function PrioriteBadge({ priorite }: { priorite: string }) {
  const map: Record<string, string> = {
    urgence: "badge-rose",
    haute: "badge-amber",
    normale: "badge-neutral",
    basse: "badge-neutral"
  };
  return (
    <span
      className={`badge font-mono uppercase ${map[priorite] || "badge-neutral"}`}
    >
      {priorite}
    </span>
  );
}

function Loading() {
  return (
    <p className="text-xs text-white/50">
      <Loader2 className="mr-1 inline h-3 w-3 animate-spin" /> Chargement…
    </p>
  );
}

function Empty({ msg }: { msg: string }) {
  return (
    <p className="rounded-lg border border-brand-800 bg-brand-900 px-4 py-3 text-sm text-white/60">
      {msg}
    </p>
  );
}
