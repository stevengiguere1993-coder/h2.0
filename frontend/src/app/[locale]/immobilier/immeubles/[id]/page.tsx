"use client";

import { use, useEffect, useRef, useState } from "react";
import {
  AlertTriangle,
  ArrowLeft,
  Banknote,
  Building2,
  Calendar,
  Camera,
  ClipboardList,
  DollarSign,
  Home,
  FileDown,
  FileSignature,
  Loader2,
  Pencil,
  Percent,
  Trash2,
  TrendingUp,
  Wrench,
  X
} from "lucide-react";

import { Link, useRouter } from "@/i18n/navigation";
import { authedFetch, getToken } from "@/lib/auth";
import { ImmobilierTopbar, useImmobilierLayout } from "../../layout";
import { EntityDriveSection } from "@/components/drive/EntityDriveSection";
import { ContratGestionTab } from "./contrat-gestion-tab";

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
};

type Logement = {
  id: number;
  numero: string;
  nb_pieces_decimal?: number | null;
  superficie_pi2?: number | null;
  status: string;
  loyer_demande?: number | null;
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
  balance_actuelle?: number | null;
  taux_pct?: number | null;
  paiement_mensuel?: number | null;
  date_fin_terme?: string | null;
  status: string;
};

type Evaluation = {
  id: number;
  kind: string;
  valeur: number;
  date_evaluation: string;
  source?: string | null;
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
  revenu_brut_mensuel: number;
  revenu_brut_annuel: number;
  paiement_hypotheque_mensuel: number;
  balance_hypothecaire: number;
  valeur_actuelle?: number | null;
  valeur_municipale?: number | null;
  purchase_price?: number | null;
  grm?: number | null;
  cap_rate?: number | null;
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
  { id: "baux", label: "Baux", icon: ClipboardList },
  { id: "hypotheques", label: "Hypothèques", icon: Banknote },
  { id: "evaluations", label: "Évaluations", icon: TrendingUp },
  { id: "maintenance", label: "Maintenance", icon: Wrench },
  { id: "contrat-gestion", label: "Contrat de gestion", icon: FileSignature }
] as const;

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
  const { entreprises } = useImmobilierLayout();
  const [tab, setTab] = useState<(typeof TABS)[number]["id"]>("overview");
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
    urgence_phone: ""
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
      urgence_phone: immeuble.urgence_phone || ""
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
        urgence_phone: editForm.urgence_phone.trim() || null
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

      <div className="p-4 lg:p-6">
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
              <span className="rounded bg-brand-900 px-2 py-0.5 font-mono text-white/70">
                {immeuble.type}
              </span>
              {immeuble.annee_construction ? (
                <span className="rounded bg-brand-900 px-2 py-0.5 text-white/70">
                  {immeuble.annee_construction}
                </span>
              ) : null}
              {immeuble.matricule ? (
                <span className="rounded bg-brand-900 px-2 py-0.5 font-mono text-white/50">
                  Matricule {immeuble.matricule}
                </span>
              ) : null}
              {!immeuble.is_active ? (
                <span className="rounded bg-amber-500/15 px-2 py-0.5 font-semibold text-amber-300">
                  Inactif
                </span>
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
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={openEdit}
                className="inline-flex items-center justify-center gap-1.5 rounded-lg border border-accent-500/30 bg-accent-500/10 px-3 py-1.5 text-xs font-semibold text-accent-500 hover:bg-accent-500/20"
                title="Modifier l'immeuble (nom, adresse, etc.)"
              >
                <Pencil className="h-3.5 w-3.5" /> Modifier
              </button>
              <button
                type="button"
                onClick={() => {
                  setBonResult(null);
                  setBonForm({ titre: "", description: "", logement: "" });
                  setShowBon(true);
                }}
                className="inline-flex items-center justify-center gap-1.5 rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-1.5 text-xs font-semibold text-amber-200 hover:bg-amber-500/20"
                title="Créer un bon de travail (réparation) dans le volet Construction"
              >
                <Wrench className="h-3.5 w-3.5" /> Bon de travail
              </button>
              <button
                type="button"
                onClick={() => setShowDelete(true)}
                className="inline-flex items-center justify-center gap-1.5 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-1.5 text-xs font-semibold text-rose-200 hover:bg-rose-500/20"
              >
                <Trash2 className="h-3.5 w-3.5" /> Supprimer
              </button>
            </div>
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
              value={fmtCurrency(financials.revenu_brut_mensuel)}
              sub={`${fmtCurrency(financials.revenu_brut_annuel)} / an`}
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
            <Kpi
              label="Cap rate (NOI ≈ 50%)"
              value={fmtPct(financials.cap_rate, 2)}
              sub={`GRM ${financials.grm ?? "—"}`}
              icon={Percent}
              tone="sky"
            />
            <Kpi
              label="Occupation"
              value={`${(financials.taux_occupation * 100).toFixed(0)}%`}
              sub={`${financials.nb_logements_occupes}/${financials.nb_logements_actifs} occupés`}
              icon={Home}
              tone={financials.taux_occupation >= 0.9 ? "emerald" : "amber"}
            />
          </section>
        ) : null}

        {/* Tabs */}
        <nav
          className="mt-6 flex items-center gap-1 overflow-x-auto"
          style={{ borderBottom: "1px solid #25252d" }}
        >
          {TABS.map((t) => {
            const active = tab === t.id;
            const Icon = t.icon;
            return (
              <button
                key={t.id}
                type="button"
                onClick={() => setTab(t.id)}
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
            />
          ) : null}
          {tab === "logements" ? <LogementsTab list={logements} /> : null}
          {tab === "baux" ? (
            <BauxTab
              list={baux}
              logements={logements}
              locataires={locataires}
            />
          ) : null}
          {tab === "hypotheques" ? <HypothequesTab list={hypotheques} /> : null}
          {tab === "evaluations" ? <EvaluationsTab list={evaluations} /> : null}
          {tab === "maintenance" ? (
            <MaintenanceTab list={maintenance} rollup={rollup} />
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
                className="rounded-md p-1.5 text-white/60 hover:bg-brand-900 hover:text-white"
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
                className="rounded-lg border border-white/15 px-4 py-2 text-xs font-semibold text-white/70 hover:text-white"
              >
                Annuler
              </button>
              <button
                type="button"
                onClick={() => void onDelete()}
                disabled={deleting}
                className="inline-flex items-center gap-1.5 rounded-lg bg-rose-500/90 px-4 py-2 text-xs font-semibold text-white hover:bg-rose-500 disabled:opacity-50"
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
                className="rounded-md p-1.5 text-white/60 hover:bg-brand-900 hover:text-white"
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
                    className="rounded-lg border border-white/15 px-4 py-2 text-xs font-semibold text-white/70 hover:text-white"
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
                className="rounded-md p-1.5 text-white/60 hover:bg-brand-900 hover:text-white"
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
            </div>
            <div className="flex items-center justify-end gap-2 border-t border-brand-800 px-5 py-3">
              <button
                type="button"
                onClick={() => setShowEdit(false)}
                disabled={editBusy}
                className="rounded-lg border border-white/15 px-4 py-2 text-xs font-semibold text-white/70 hover:text-white"
              >
                Annuler
              </button>
              <button
                type="button"
                onClick={() => void saveEdit()}
                disabled={editBusy || !editForm.address.trim()}
                className="inline-flex items-center gap-1.5 rounded-lg bg-accent-500/90 px-4 py-2 text-xs font-semibold text-brand-950 hover:bg-accent-500 disabled:opacity-50"
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
  value: string;
  sub?: string;
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
    <div className="rounded-2xl border border-brand-800 bg-brand-900 p-4">
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
  empty = "—"
}: {
  title: string;
  children: React.ReactNode;
  empty?: string;
}) {
  void empty;
  return (
    <section className="rounded-2xl border border-brand-800 bg-brand-900 p-5">
      <h2 className="mb-3 text-sm font-semibold uppercase tracking-wider text-accent-500">
        {title}
      </h2>
      {children}
    </section>
  );
}

function OverviewTab({
  immeuble,
  financials,
  logementsCount
}: {
  immeuble: Immeuble;
  financials: Financials | null;
  logementsCount: number;
}) {
  return (
    <div className="grid gap-4 lg:grid-cols-2">
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
    </div>
  );
}

function LogementsTab({ list }: { list: Logement[] | null }) {
  if (list === null)
    return (
      <p className="text-xs text-white/50">
        <Loader2 className="mr-1 inline h-3 w-3 animate-spin" /> Chargement…
      </p>
    );
  if (list.length === 0)
    return (
      <p className="rounded-lg border border-brand-800 bg-brand-900 px-4 py-3 text-sm text-white/60">
        Aucun logement créé.
      </p>
    );
  return (
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
            <tr key={l.id}>
              <td className="px-4 py-2 font-bold text-white">{l.numero}</td>
              <td className="px-4 py-2 text-xs text-white/70">
                {l.nb_pieces_decimal != null
                  ? `${l.nb_pieces_decimal}½`
                  : "—"}
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
  );
}

function BauxTab({
  list,
  logements,
  locataires
}: {
  list: Bail[] | null;
  logements: Logement[] | null;
  locataires: { id: number; full_name: string }[];
}) {
  if (list === null) return <Loading />;
  if (list.length === 0) return <Empty msg="Aucun bail." />;
  const logMap = new Map((logements || []).map((l) => [l.id, l.numero]));
  const locMap = new Map(locataires.map((l) => [l.id, l.full_name]));
  return (
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
          </tr>
        </thead>
        <tbody className="divide-y divide-brand-800">
          {list.map((b) => (
            <tr key={b.id}>
              <td className="px-4 py-2 font-mono text-xs text-white">
                {logMap.get(b.logement_id) || `#${b.logement_id}`}
              </td>
              <td className="px-4 py-2 text-xs">
                <Link
                  // eslint-disable-next-line @typescript-eslint/no-explicit-any
                  href={`/immobilier/locataires/${b.locataire_id}` as any}
                  className="font-medium text-accent-500 hover:underline"
                >
                  {locMap.get(b.locataire_id) || `Locataire #${b.locataire_id}`}
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
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function BailSignButton({
  bailId,
  signed
}: {
  bailId: number;
  signed: boolean;
}) {
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
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

  async function send() {
    setBusy(true);
    setMsg(null);
    try {
      const res = await authedFetch(
        `/api/v1/immobilier/baux/${bailId}/send`,
        { method: "POST", body: JSON.stringify({}) }
      );
      if (!res.ok) {
        setMsg((await res.text()).slice(0, 120) || `HTTP ${res.status}`);
        return;
      }
      const d = (await res.json()) as { sent_to: string | null };
      setMsg(`Envoyé à ${d.sent_to || "—"}`);
    } catch (e) {
      setMsg((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="flex flex-col gap-0.5">
      <button
        type="button"
        onClick={() => void send()}
        disabled={busy}
        className="inline-flex w-fit items-center gap-1 rounded-md border border-accent-500/40 bg-accent-500/10 px-2 py-1 text-[11px] font-semibold text-accent-500 hover:bg-accent-500/20 disabled:opacity-50"
        title="Envoyer le bail au locataire pour signature"
      >
        {busy ? <Loader2 className="h-3 w-3 animate-spin" /> : null}
        Envoyer pour signature
      </button>
      {msg ? (
        <span className="text-[10px] text-white/50">{msg}</span>
      ) : null}
    </div>
  );
}

const TAL_FORMS = [
  { code: "sommaire_bail", label: "Sommaire du bail" },
  { code: "avis_modification", label: "Avis de modification" },
  { code: "avis_fin_bail", label: "Avis de non-renouvellement" },
  { code: "rappel_paiement", label: "Rappel de paiement" },
  { code: "mise_en_demeure", label: "Mise en demeure" }
] as const;

function TalFormDropdown({ bailId }: { bailId: number }) {
  const [open, setOpen] = useState(false);
  const [downloading, setDownloading] = useState<string | null>(null);

  async function download(code: string) {
    setDownloading(code);
    try {
      const res = await authedFetch(
        `/api/v1/immobilier/baux/${bailId}/tal/${code}.pdf`,
        {
          method: "POST",
          body: JSON.stringify({})
        }
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${code.replace(/_/g, "-")}-bail-${bailId}.pdf`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
      setOpen(false);
    } catch (e) {
      alert((e as Error).message);
    } finally {
      setDownloading(null);
    }
  }

  return (
    <div className="relative inline-block">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="inline-flex items-center gap-1 rounded border border-white/15 bg-brand-950 px-2 py-0.5 text-[11px] text-white/80 hover:border-accent-500 hover:text-accent-500"
      >
        Générer ▾
      </button>
      {open ? (
        <div className="absolute right-0 z-30 mt-1 w-56 rounded-lg border border-brand-700 bg-brand-950 py-1 shadow-2xl">
          {TAL_FORMS.map((f) => (
            <button
              key={f.code}
              type="button"
              onClick={() => download(f.code)}
              disabled={downloading === f.code}
              className="block w-full px-3 py-1.5 text-left text-xs text-white/80 hover:bg-brand-900 hover:text-white disabled:opacity-50"
            >
              {downloading === f.code ? "Génération…" : f.label}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function HypothequesTab({ list }: { list: Hypotheque[] | null }) {
  if (list === null) return <Loading />;
  if (list.length === 0) return <Empty msg="Aucune hypothèque enregistrée." />;
  return (
    <div className="grid gap-3">
      {list.map((h) => (
        <div
          key={h.id}
          className="rounded-2xl border border-brand-800 bg-brand-900 p-4"
        >
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-bold text-white">
                {h.preteur}{" "}
                <span className="ml-1 rounded bg-brand-950 px-1.5 py-0.5 font-mono text-[10px] text-white/50">
                  Rang {h.rang}
                </span>
              </p>
              <p className="mt-1 text-xs text-white/50">
                {h.taux_pct ? `${h.taux_pct}%` : "Taux ?"} · Renouv.{" "}
                {h.date_fin_terme || "—"}
              </p>
            </div>
            <div className="text-right">
              <div className="font-mono text-sm font-bold text-white">
                {fmtCurrency(h.balance_actuelle)}
              </div>
              <div className="text-[11px] text-white/50">
                Paiement {fmtCurrency(h.paiement_mensuel)}/m
              </div>
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

function EvaluationsTab({ list }: { list: Evaluation[] | null }) {
  if (list === null) return <Loading />;
  if (list.length === 0) return <Empty msg="Aucune évaluation." />;
  return (
    <div className="overflow-hidden rounded-2xl border border-brand-800 bg-brand-900">
      <table className="w-full text-left text-sm">
        <thead className="border-b border-brand-800 bg-brand-950 text-[10px] uppercase tracking-wider text-white/50">
          <tr>
            <th className="px-4 py-2.5">Date</th>
            <th className="px-4 py-2.5">Type</th>
            <th className="px-4 py-2.5">Source</th>
            <th className="px-4 py-2.5 text-right">Valeur</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-brand-800">
          {list.map((e) => (
            <tr key={e.id}>
              <td className="px-4 py-2 text-xs text-white/70">
                {e.date_evaluation}
              </td>
              <td className="px-4 py-2 text-xs">
                <span className="rounded bg-brand-950 px-1.5 py-0.5 font-mono text-white/70">
                  {e.kind}
                </span>
              </td>
              <td className="px-4 py-2 text-xs text-white/50">
                {e.source || "—"}
              </td>
              <td className="px-4 py-2 text-right font-mono text-sm font-bold text-white">
                {fmtCurrency(e.valeur)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
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
    occupe: "bg-emerald-500/15 text-emerald-300",
    actif: "bg-emerald-500/15 text-emerald-300",
    vacant: "bg-amber-500/15 text-amber-300",
    reserve: "bg-sky-500/15 text-sky-300",
    propose: "bg-sky-500/15 text-sky-300",
    termine: "bg-white/10 text-white/50",
    resilie: "bg-rose-500/15 text-rose-300",
    hors_location: "bg-white/10 text-white/50",
    ouvert: "bg-amber-500/15 text-amber-300",
    en_cours: "bg-sky-500/15 text-sky-300",
    en_attente: "bg-violet-500/15 text-violet-300",
    annule: "bg-white/10 text-white/40"
  };
  const cls = map[status] || "bg-white/10 text-white/60";
  return (
    <span
      className={`rounded px-1.5 py-0.5 font-mono text-[10px] uppercase ${cls}`}
    >
      {status}
    </span>
  );
}

function PrioriteBadge({ priorite }: { priorite: string }) {
  const map: Record<string, string> = {
    urgence: "bg-rose-500/20 text-rose-300",
    haute: "bg-amber-500/15 text-amber-300",
    normale: "bg-white/10 text-white/60",
    basse: "bg-white/5 text-white/40"
  };
  return (
    <span
      className={`rounded px-1.5 py-0.5 font-mono text-[10px] uppercase ${
        map[priorite] || "bg-white/10 text-white/60"
      }`}
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
