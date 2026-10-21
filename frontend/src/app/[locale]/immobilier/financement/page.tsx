"use client";

/**
 * Gestion locative → FINANCEMENT (Phil 2026-10-16) : « je veux que mes
 * financements deviennent faciles ».
 *
 * Parcours (Phil) : 1. choisir l'immeuble ; 2. créer un dossier de
 * financement ou en ouvrir un — rien d'autre ; 3. dans le dossier : aperçu
 * (tableau de bord), rent roll (depuis les baux ENREGISTRÉS, catégories
 * standards / parallèles, correction du bail à la source), pièces et
 * exports (checklist, projection marquée estimation, PDF/Excel, paquet),
 * baux parallèles (sous-locations gérées par un tiers : vrais contrats
 * hors du quotidien, visibles ICI seulement, partagés par les dossiers de
 * l'immeuble), suivi dans le temps.
 *
 * Garde-fou : le rent roll est PRODUIT par les baux, jamais l'inverse ; il
 * n'existe aucun montant modifiable « pour l'export » — si un chiffre est
 * faux, on corrige le bail (journalisé) et l'export suit.
 */

import { useCallback, useEffect, useState } from "react";
import {
  AlertTriangle,
  ArrowLeft,
  Check,
  Download,
  FileSignature,
  FileText,
  Landmark,
  Loader2,
  Pencil,
  Plus,
  RefreshCw,
  Send,
  Trash2,
  Upload,
  X
} from "lucide-react";

import { Link } from "@/i18n/navigation";
import { authedFetch } from "@/lib/auth";
import { ImmobilierTopbar } from "../layout";
import { TalFormDropdown } from "@/components/immobilier/tal-avis";
import { docTypeLabel } from "@/components/immobilier/doc-types";
import { TalBailModal, ouvrirPdfDocument } from "@/components/immobilier/tal-bail-modal";

const FIN = "/api/v1/immobilier/financement";
const INPUT =
  "rounded-md border border-brand-800 bg-brand-950 px-2 py-1.5 text-xs text-white outline-none focus:border-accent-500 disabled:opacity-50";

// ─── Types ────────────────────────────────────────────────────────────

type ImmeubleLite = { id: number; name: string; address?: string | null; gestion_externe?: boolean };
type LogementLite = { id: number; numero: string; loyer_demande: number | null };

//: Objectif d'une unité du dossier : fixe (telle quelle) ou à ajuster (loyer
//: visé) ; le statut vient des baux et des avis réels.
type Cible = {
  mode: "fixe" | "ajuster";
  loyer_vise: number | null;
  note: string | null;
  echeance: string | null;
  statut: string;
  statut_label: string;
  renouvellement: { id: number; statut: string; nouveau_loyer: number | null; avis_envoye_le: string | null; nouvelle_date_debut: string | null; document_id: number | null } | null;
  ecart: number | null;
};
type RentRollLigne = {
  logement_id: number;
  numero: string;
  nb_pieces: number | null;
  occupation: string;
  bail_id: number | null;
  locataire_id: number | null;
  locataire: string | null;
  loyer: number | null;
  inclusions: string[];
  date_debut: string | null;
  date_fin: string | null;
  au_mois: boolean | null;
  jour_echeance: number | null;
  depot: number | null;
  document_signe: boolean | null;
  loyer_demande: number | null;
  nb_paralleles: number;
  //: Bail principal (le locataire sous-loue) : la ligne est son bail ; les
  //: baux de chambre sont ses sous-locations (information, hors totaux).
  categorie?: string;
  mention?: string | null;
  sous_locations?: { bail_id: number; locataire_id: number | null; locataire: string | null; loyer: number | null; date_debut: string | null; date_fin: string | null; au_mois: boolean; document_signe: boolean }[];
  //: Unité louée en chambres : un bail par chambre, la ligne porte le total.
  baux?: { bail_id: number; locataire_id: number | null; locataire: string | null; loyer: number | null; date_debut: string | null; date_fin: string | null; au_mois: boolean; document_signe: boolean }[];
  prochain?: { bail_id: number; locataire: string | null; date_debut: string | null; loyer: number | null; statut: string };
  projection?: { loyer: number | null; source: string | null; note: string | null; statut?: string; statut_label?: string };
  cible?: Cible;
};
type RentRollParallele = {
  bail_id: number;
  logement_id: number;
  numero: string;
  locataire_id: number | null;
  locataire: string | null;
  locateur_bail: string | null;
  type: string | null;
  type_label: string;
  loyer: number | null;
  inclusions: string[];
  date_debut: string | null;
  date_fin: string | null;
  au_mois: boolean;
  statut: string;
  en_vigueur: boolean;
  echu: boolean;
  document_signe: boolean;
  note: string | null;
};
type RentRoll = {
  immeuble: { id: number; nom: string; adresse: string; ville: string | null };
  a_date: string;
  lignes: RentRollLigne[];
  paralleles: RentRollParallele[];
  totaux: Record<string, number | string[] | null>;
  projection: { logements: Record<string, { mode?: string; loyer: number | null; source: string; note: string | null; echeance?: string | null }>; hypotheses: { vacance_pct?: number } } | null;
  genere_le: string;
};

type Piece = {
  id: number;
  type: string;
  libelle: string;
  requis: boolean;
  ordre: number;
  document_id: number | null;
  envoye_le: string | null;
  notes: string | null;
  fournie: boolean;
};
type Journal = { id: number; type: string; texte: string; auteur_email: string | null; created_at: string | null };
type Dossier = {
  id: number;
  immeuble_id: number;
  immeuble_nom?: string | null;
  titre: string;
  type: string;
  preteur: string | null;
  courtier: string | null;
  montant_demande: number | null;
  taux_pct: number | null;
  terme_mois: number | null;
  amortissement_mois: number | null;
  statut: string;
  date_depot: string | null;
  date_reponse: string | null;
  date_echeance: string | null;
  inclure_standards: boolean;
  inclure_paralleles: boolean;
  projection: { logements: Record<string, { mode?: string; loyer: number | null; source: string; note: string | null; echeance?: string | null }>; hypotheses: { vacance_pct?: number } };
  notes: string | null;
  nb_pieces_requises: number | null;
  nb_pieces_fournies: number | null;
  updated_at: string | null;
};
type DossierDetail = Dossier & {
  pieces: Piece[];
  journal: Journal[];
  tableau_de_bord: {
    reel_mensuel: number;
    reel_annuel: number;
    paralleles_mensuel: number;
    paralleles_annuel: number;
    projection_mensuelle: number | null;
    projection_annuelle: number | null;
    ecart_projection_pct: number | null;
    taux_occupation_pct: number | null;
    nb_unites: number;
    nb_vacantes: number;
    pieces_requises: number;
    pieces_fournies: number;
    pieces_manquantes: string[];
    jours_avant_echeance: number | null;
    vise_mensuel?: number | null;
    nb_a_ajuster?: number;
    nb_cibles_atteintes?: number;
  };
  rent_roll: RentRoll;
  types: string[];
  statuts: string[];
  types_pieces: string[];
};
type DocumentImm = {
  id: number;
  type: string;
  titre: string;
  source: string;
  filename: string | null;
  created_at: string | null;
  signed_at: string | null;
  bail_id: number | null;
  logement_id: number | null;
  numero: string | null;
  locataire: string | null;
  bail_categorie: string | null;
  est_bail_courant: boolean;
};
type BailParallele = {
  id: number;
  logement_id: number;
  logement_numero: string | null;
  locataire_id: number;
  locataire_nom: string | null;
  locataire_email: string | null;
  locataire_categorie: string | null;
  parallele_type: string | null;
  type_label: string;
  parallele_locateur: string | null;
  locateur_effectif?: string | null;
  parallele_locateur_courriel: string | null;
  parallele_locateur_telephone: string | null;
  parallele_note: string | null;
  date_debut: string;
  date_fin: string;
  loyer_mensuel: number;
  depot_garantie: number | null;
  chauffage_inclus: boolean;
  eau_chaude_inclus: boolean;
  electricite_inclus: boolean;
  internet_inclus: boolean;
  au_mois: boolean | null;
  jour_echeance: number;
  status: string;
  document_id: number | null;
  en_vigueur: boolean;
  echu: boolean;
  notes: string | null;
};

const TYPE_LABEL: Record<string, string> = {
  refinancement: "Refinancement",
  achat: "Achat",
  renouvellement: "Renouvellement",
  autre: "Autre"
};
const STATUT_LABEL: Record<string, string> = {
  preparation: "En préparation",
  envoye: "Envoyé",
  en_analyse: "En analyse",
  approuve: "Approuvé",
  refuse: "Refusé",
  clos: "Clos"
};
const STATUT_BADGE: Record<string, string> = {
  preparation: "badge-amber",
  envoye: "badge-sky",
  en_analyse: "badge-violet",
  approuve: "badge-emerald",
  refuse: "badge-rose",
  clos: "badge-neutral"
};
const PIECE_LABEL: Record<string, string> = {
  rent_roll: "Rent roll",
  baux: "Baux",
  baux_paralleles: "Baux parallèles",
  avis: "Avis",
  etats_financiers: "États financiers",
  releve_hypothecaire: "Relevé hypothécaire",
  taxes: "Taxes",
  assurance: "Assurance",
  evaluation: "Évaluation",
  offre_achat: "Offre d'achat",
  identite: "Emprunteurs",
  organigramme: "Organigramme",
  autre: "Autre"
};
const OCCUPATION_LABEL: Record<string, string> = {
  occupe: "Occupé",
  vacant: "Vacant",
  reserve: "Réservé",
  hors_location: "Hors location",
  parallele_seulement: "Occupé (bail parallèle)",
  occupe_chambres: "Occupé · chambres"
};
const PARALLELE_TYPES: [string, string][] = [
  ["sous_location", "Sous-location"],
  ["bail_principal", "Bail principal (le locataire sous-loue)"],
  ["colocation", "Colocation"],
  ["autre", "Autre"]
];

// ─── Outils ───────────────────────────────────────────────────────────

function money(n: number | null | undefined): string {
  if (n == null) return "—";
  return `${n.toLocaleString("fr-CA", { minimumFractionDigits: 0, maximumFractionDigits: 2 })} $`;
}
function fmtDate(d: string | null | undefined): string {
  if (!d) return "—";
  const dt = new Date(d.length <= 10 ? `${d}T00:00:00` : d);
  if (Number.isNaN(dt.getTime())) return d;
  return dt.toLocaleDateString("fr-CA", { day: "2-digit", month: "short", year: "numeric" });
}
function fmtDateTime(d: string | null | undefined): string {
  if (!d) return "—";
  const dt = new Date(d);
  if (Number.isNaN(dt.getTime())) return d;
  return dt.toLocaleString("fr-CA", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
}
async function lireErreur(r: Response): Promise<string> {
  const t = await r.text();
  try {
    const j = JSON.parse(t) as { detail?: unknown };
    if (typeof j.detail === "string") return j.detail;
    if (j.detail && typeof j.detail === "object" && "message" in (j.detail as object))
      return String((j.detail as { message: string }).message);
  } catch {
    /* brut */
  }
  return t.slice(0, 300) || `HTTP ${r.status}`;
}
async function telecharger(url: string, nomParDefaut: string): Promise<void> {
  const r = await authedFetch(url);
  if (!r.ok) throw new Error(await lireErreur(r));
  const cd = r.headers.get("content-disposition") || "";
  const m = cd.match(/filename="?([^";]+)"?/);
  const blob = await r.blob();
  const href = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = href;
  a.download = m ? m[1] : nomParDefaut;
  document.body.appendChild(a);
  a.click();
  a.remove();
  window.setTimeout(() => URL.revokeObjectURL(href), 30_000);
}

// ─── Page : immeuble → dossier ────────────────────────────────────────

export default function FinancementPage() {
  const [immeubles, setImmeubles] = useState<ImmeubleLite[]>([]);
  const [immId, setImmId] = useState<number | null>(null);
  const [openId, setOpenId] = useState<number | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    void (async () => {
      const r = await authedFetch("/api/v1/immobilier/immeubles");
      if (!r.ok) {
        setErr("Chargement des immeubles impossible.");
        return;
      }
      const list = ((await r.json()) as ImmeubleLite[]).filter((i) => !i.gestion_externe);
      list.sort((a, b) => a.name.localeCompare(b.name, "fr"));
      setImmeubles(list);
      const params = new URLSearchParams(window.location.search);
      let stored: string | null = null;
      try {
        stored = window.localStorage.getItem("kratos-financement-immeuble");
      } catch {
        /* privé */
      }
      const voulu = Number(params.get("immeuble") || stored);
      if (Number.isFinite(voulu) && list.some((i) => i.id === voulu)) setImmId(voulu);
      else if (list.length === 1) setImmId(list[0].id);
      const dossier = Number(params.get("dossier"));
      if (Number.isFinite(dossier) && dossier > 0) setOpenId(dossier);
    })();
  }, []);

  useEffect(() => {
    if (immId == null) return;
    try {
      window.localStorage.setItem("kratos-financement-immeuble", String(immId));
    } catch {
      /* privé */
    }
  }, [immId]);

  const immeuble = immeubles.find((i) => i.id === immId) || null;

  return (
    <>
      <ImmobilierTopbar breadcrumbs={[{ label: "Immobilier", href: "/immobilier" }, { label: "Financement" }]} />
      <div className="p-4 pb-28 lg:p-6 lg:pb-28">
        <header className="flex flex-wrap items-start gap-3">
          <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-emerald-500/15 text-emerald-300">
            <Landmark className="h-5 w-5" />
          </span>
          <div className="min-w-0 flex-1">
            <h1 className="text-2xl font-bold text-white">Financement</h1>
            <p className="mt-1 max-w-3xl text-sm text-white/60">
              Un immeuble, un dossier par demande de prêt. Dans le dossier : les unités fixes (telles quelles) ou à
              ajuster (loyer visé), le rent roll à envoyer, les baux et avis à produire au moment venu, les pièces, le suivi.
            </p>
          </div>
          <label className="text-[11px] font-semibold text-white/60">
            Immeuble
            <select
              value={immId == null ? "" : String(immId)}
              onChange={(e) => {
                setImmId(e.target.value ? Number(e.target.value) : null);
                setOpenId(null);
              }}
              className={`${INPUT} mt-0.5 block min-w-[240px]`}
            >
              <option value="">Choisir un immeuble…</option>
              {immeubles.map((i) => (
                <option key={i.id} value={i.id}>
                  {i.name}
                </option>
              ))}
            </select>
          </label>
        </header>

        {err ? <p className="mt-4 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">{err}</p> : null}

        {!immeuble ? (
          <p className="mt-8 text-sm text-white/50">Étape 1 : choisis un immeuble.</p>
        ) : openId == null ? (
          <DossiersListe immeuble={immeuble} onOpen={setOpenId} onError={setErr} />
        ) : (
          <DossierVue dossierId={openId} immeuble={immeuble} onBack={() => setOpenId(null)} onError={setErr} />
        )}
      </div>
    </>
  );
}

// ─── Étape 2 : créer ou ouvrir un dossier ─────────────────────────────

function DossiersListe({ immeuble, onOpen, onError }: { immeuble: ImmeubleLite; onOpen: (id: number) => void; onError: (m: string | null) => void }) {
  const [items, setItems] = useState<Dossier[] | null>(null);
  const [showCreate, setShowCreate] = useState(false);

  const load = useCallback(async () => {
    const r = await authedFetch(`${FIN}/dossiers?immeuble_id=${immeuble.id}`);
    if (!r.ok) {
      onError(await lireErreur(r));
      return;
    }
    setItems(((await r.json()) as { items: Dossier[] }).items);
  }, [immeuble.id, onError]);

  useEffect(() => {
    void load();
  }, [load]);

  const ouverts = (items || []).filter((d) => !["approuve", "refuse", "clos"].includes(d.statut));
  const fermes = (items || []).filter((d) => ["approuve", "refuse", "clos"].includes(d.statut));

  return (
    <div className="mt-5 space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <p className="text-xs text-white/50">
          Étape 2 : ouvre un dossier ou crée-en un.
          {items != null ? ` ${ouverts.length} en cours · ${fermes.length} fermé(s).` : ""}
        </p>
        <button type="button" onClick={() => setShowCreate(true)} className="btn-accent btn-sm ml-auto">
          <Plus className="h-3.5 w-3.5" /> Nouveau dossier de financement
        </button>
      </div>
      {items == null ? (
        <p className="flex items-center gap-2 py-6 text-xs text-white/50">
          <Loader2 className="h-4 w-4 animate-spin" /> Chargement…
        </p>
      ) : items.length === 0 ? (
        <p className="rounded-xl border border-brand-800 bg-brand-900/60 px-4 py-8 text-center text-sm text-white/50">
          Aucun dossier de financement pour {immeuble.name}. Crée le premier : la checklist standard se prépare toute seule.
        </p>
      ) : (
        <div className="grid gap-3 lg:grid-cols-2">
          {[...ouverts, ...fermes].map((d) => (
            <button key={d.id} type="button" onClick={() => onOpen(d.id)} className="rounded-xl border border-brand-800 bg-brand-900 p-4 text-left transition hover:border-accent-500">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-sm font-semibold text-white">{d.titre}</span>
                <span className={`badge ${STATUT_BADGE[d.statut] || "badge-neutral"}`}>{STATUT_LABEL[d.statut] || d.statut}</span>
                <span className="badge badge-neutral">{TYPE_LABEL[d.type] || d.type}</span>
              </div>
              <p className="mt-1 text-xs text-white/55">
                {d.preteur || "Prêteur à préciser"}
                {d.courtier ? ` · courtier ${d.courtier}` : ""}
                {d.montant_demande != null ? ` · ${money(d.montant_demande)}` : ""}
                {d.taux_pct != null ? ` · ${d.taux_pct} %` : ""}
              </p>
              <p className="mt-1 text-[11px] text-white/40">
                Pièces : {d.nb_pieces_fournies ?? 0}/{d.nb_pieces_requises ?? 0}
                {d.date_echeance ? ` · échéance ${fmtDate(d.date_echeance)}` : ""}
                {d.date_depot ? ` · déposé le ${fmtDate(d.date_depot)}` : ""}
                {d.updated_at ? ` · mis à jour ${fmtDateTime(d.updated_at)}` : ""}
              </p>
            </button>
          ))}
        </div>
      )}
      {showCreate ? (
        <NouveauDossierModal
          immeuble={immeuble}
          onClose={() => setShowCreate(false)}
          onCreated={(id) => {
            setShowCreate(false);
            onOpen(id);
          }}
        />
      ) : null}
    </div>
  );
}

function NouveauDossierModal({ immeuble, onClose, onCreated }: { immeuble: ImmeubleLite; onClose: () => void; onCreated: (id: number) => void }) {
  const [f, setF] = useState({
    type: "refinancement",
    preteur: "",
    courtier: "",
    montant_demande: "",
    taux_pct: "",
    terme_mois: "",
    date_echeance: "",
    inclure_standards: true,
    inclure_paralleles: true,
    notes: ""
  });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function submit() {
    setBusy(true);
    setErr(null);
    try {
      const r = await authedFetch(`${FIN}/dossiers`, {
        method: "POST",
        body: JSON.stringify({
          immeuble_id: immeuble.id,
          type: f.type,
          preteur: f.preteur || null,
          courtier: f.courtier || null,
          montant_demande: f.montant_demande ? Number(f.montant_demande) : null,
          taux_pct: f.taux_pct ? Number(f.taux_pct) : null,
          terme_mois: f.terme_mois ? Number(f.terme_mois) : null,
          date_echeance: f.date_echeance || null,
          inclure_standards: f.inclure_standards,
          inclure_paralleles: f.inclure_paralleles,
          notes: f.notes || null,
          pieces_defaut: true
        })
      });
      if (!r.ok) throw new Error(await lireErreur(r));
      onCreated(((await r.json()) as { id: number }).id);
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal titre={`Nouveau dossier — ${immeuble.name}`} onClose={onClose}>
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="text-[11px] font-semibold text-white/60">
          Type
          <select value={f.type} onChange={(e) => setF({ ...f, type: e.target.value })} className={`${INPUT} mt-0.5 block w-full`}>
            {Object.entries(TYPE_LABEL).map(([v, l]) => (
              <option key={v} value={v}>
                {l}
              </option>
            ))}
          </select>
        </label>
        <Champ label="Prêteur" value={f.preteur} onChange={(v) => setF({ ...f, preteur: v })} />
        <Champ label="Courtier" value={f.courtier} onChange={(v) => setF({ ...f, courtier: v })} />
        <Champ label="Montant demandé ($)" value={f.montant_demande} onChange={(v) => setF({ ...f, montant_demande: v })} inputMode="decimal" />
        <Champ label="Taux (%)" value={f.taux_pct} onChange={(v) => setF({ ...f, taux_pct: v })} inputMode="decimal" />
        <Champ label="Terme (mois)" value={f.terme_mois} onChange={(v) => setF({ ...f, terme_mois: v })} inputMode="numeric" />
        <Champ label="Échéance à respecter" value={f.date_echeance} onChange={(v) => setF({ ...f, date_echeance: v })} type="date" />
        <div className="text-[11px] font-semibold text-white/60">
          Baux dans le rent roll du dossier
          <div className="mt-1 flex flex-col gap-1 text-xs font-normal text-white/80">
            <label className="flex items-center gap-2">
              <input type="checkbox" checked={f.inclure_standards} onChange={(e) => setF({ ...f, inclure_standards: e.target.checked })} /> Baux standards
            </label>
            <label className="flex items-center gap-2">
              <input type="checkbox" checked={f.inclure_paralleles} onChange={(e) => setF({ ...f, inclure_paralleles: e.target.checked })} /> Baux parallèles (sous-location…)
            </label>
          </div>
        </div>
        <label className="text-[11px] font-semibold text-white/60 sm:col-span-2">
          Notes
          <textarea rows={2} value={f.notes} onChange={(e) => setF({ ...f, notes: e.target.value })} className={`${INPUT} mt-0.5 block w-full`} />
        </label>
      </div>
      {err ? <p className="mt-3 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">{err}</p> : null}
      <div className="mt-4 flex justify-end gap-2 border-t border-brand-800 pt-3">
        <button type="button" onClick={onClose} className="btn-secondary btn-sm">
          Annuler
        </button>
        <button type="button" disabled={busy || (!f.inclure_standards && !f.inclure_paralleles)} onClick={() => void submit()} className="btn-accent btn-sm disabled:opacity-60">
          {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />} Ouvrir le dossier
        </button>
      </div>
    </Modal>
  );
}

// ─── Étape 3 : le dossier ─────────────────────────────────────────────

type Vue = "unites" | "rentroll" | "pieces" | "paralleles" | "suivi";

function DossierVue({ dossierId, immeuble, onBack, onError }: { dossierId: number; immeuble: ImmeubleLite; onBack: () => void; onError: (m: string | null) => void }) {
  const [d, setD] = useState<DossierDetail | null>(null);
  const [docs, setDocs] = useState<DocumentImm[]>([]);
  const [vue, setVue] = useState<Vue>("unites");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const load = useCallback(async () => {
    const [r, rd] = await Promise.all([authedFetch(`${FIN}/dossiers/${dossierId}`), authedFetch(`${FIN}/immeubles/${immeuble.id}/documents`)]);
    if (!r.ok) {
      onError(await lireErreur(r));
      return;
    }
    setD((await r.json()) as DossierDetail);
    if (rd.ok) setDocs(((await rd.json()) as { items: DocumentImm[] }).items);
  }, [dossierId, immeuble.id, onError]);

  useEffect(() => {
    void load();
  }, [load]);

  const patch = useCallback(
    async (body: Record<string, unknown>) => {
      setBusy(true);
      setErr(null);
      try {
        const r = await authedFetch(`${FIN}/dossiers/${dossierId}`, { method: "PATCH", body: JSON.stringify(body) });
        if (!r.ok) throw new Error(await lireErreur(r));
        setD((await r.json()) as DossierDetail);
      } catch (e) {
        setErr((e as Error).message);
      } finally {
        setBusy(false);
      }
    },
    [dossierId]
  );

  async function supprimer() {
    if (!d) return;
    if (!window.confirm("Supprimer DÉFINITIVEMENT ce dossier de financement (pièces et journal compris) ?")) return;
    const r = await authedFetch(`${FIN}/dossiers/${d.id}`, { method: "DELETE" });
    if (!r.ok) {
      setErr(await lireErreur(r));
      return;
    }
    onBack();
  }

  if (!d) {
    return (
      <p className="mt-6 flex items-center gap-2 text-xs text-white/50">
        <Loader2 className="h-4 w-4 animate-spin" /> Chargement du dossier…
      </p>
    );
  }
  const tb = d.tableau_de_bord;

  return (
    <div className="mt-5 space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <button type="button" onClick={onBack} className="btn-secondary btn-sm">
          <ArrowLeft className="h-3.5 w-3.5" /> Dossiers
        </button>
        <h2 className="text-lg font-bold text-white">{d.titre}</h2>
        <span className={`badge ${STATUT_BADGE[d.statut] || "badge-neutral"}`}>{STATUT_LABEL[d.statut] || d.statut}</span>
        <span className="badge badge-neutral">{TYPE_LABEL[d.type] || d.type}</span>
        {busy ? <Loader2 className="h-4 w-4 animate-spin text-white/40" /> : null}
      </div>

      <nav className="flex flex-wrap gap-1 rounded-xl border border-brand-800 bg-brand-900/60 p-1">
        {(
          [
            ["unites", "1. Unités"],
            ["rentroll", "2. Rent roll"],
            ["pieces", "3. Pièces et exports"],
            ["paralleles", "Baux parallèles"],
            ["suivi", "Dossier et suivi"]
          ] as [Vue, string][]
        ).map(([id, label]) => (
          <button
            key={id}
            type="button"
            onClick={() => setVue(id)}
            className={`rounded-lg px-3 py-1.5 text-xs font-semibold transition ${
              vue === id ? "bg-accent-500/15 text-accent-500 ring-1 ring-inset ring-accent-500/40" : "text-white/60 hover:bg-brand-800 hover:text-white"
            }`}
          >
            {label}
            {id === "pieces" && tb.pieces_manquantes.length ? <span className="badge badge-amber ml-1">{tb.pieces_manquantes.length}</span> : null}
            {id === "unites" && tb.nb_a_ajuster ? <span className="badge badge-amber ml-1">{tb.nb_a_ajuster} à ajuster</span> : null}
          </button>
        ))}
      </nav>

      {err ? <p className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">{err}</p> : null}

      {vue === "unites" ? <UnitesTab immeuble={immeuble} dossier={d} docs={docs} onChanged={load} /> : null}

      {vue === "suivi" ? (
        <>
          <div className="grid gap-3 sm:grid-cols-3 lg:grid-cols-4">
            <label className="text-[11px] font-semibold text-white/60">
              Statut
              <select value={d.statut} disabled={busy} onChange={(e) => void patch({ statut: e.target.value })} className={`${INPUT} mt-0.5 block w-full`}>
                {d.statuts.map((s) => (
                  <option key={s} value={s}>
                    {STATUT_LABEL[s] || s}
                  </option>
                ))}
              </select>
            </label>
            <label className="text-[11px] font-semibold text-white/60">
              Type
              <select value={d.type} disabled={busy} onChange={(e) => void patch({ type: e.target.value })} className={`${INPUT} mt-0.5 block w-full`}>
                {d.types.map((t) => (
                  <option key={t} value={t}>
                    {TYPE_LABEL[t] || t}
                  </option>
                ))}
              </select>
            </label>
            <ChampBlur label="Prêteur" value={d.preteur || ""} onSave={(v) => void patch({ preteur: v || null })} />
            <ChampBlur label="Courtier" value={d.courtier || ""} onSave={(v) => void patch({ courtier: v || null })} />
            <ChampBlur label="Montant demandé ($)" value={d.montant_demande != null ? String(d.montant_demande) : ""} onSave={(v) => void patch({ montant_demande: v ? Number(v) : null })} inputMode="decimal" />
            <ChampBlur label="Taux (%)" value={d.taux_pct != null ? String(d.taux_pct) : ""} onSave={(v) => void patch({ taux_pct: v ? Number(v) : null })} inputMode="decimal" />
            <ChampBlur label="Terme (mois)" value={d.terme_mois != null ? String(d.terme_mois) : ""} onSave={(v) => void patch({ terme_mois: v ? Number(v) : null })} inputMode="numeric" />
            <ChampBlur label="Amortissement (mois)" value={d.amortissement_mois != null ? String(d.amortissement_mois) : ""} onSave={(v) => void patch({ amortissement_mois: v ? Number(v) : null })} inputMode="numeric" />
            <ChampBlur label="Déposé le" value={d.date_depot || ""} onSave={(v) => void patch({ date_depot: v || null })} type="date" />
            <ChampBlur label="Réponse le" value={d.date_reponse || ""} onSave={(v) => void patch({ date_reponse: v || null })} type="date" />
            <ChampBlur label="Échéance" value={d.date_echeance || ""} onSave={(v) => void patch({ date_echeance: v || null })} type="date" />
            <ChampBlur label="Titre du dossier" value={d.titre} onSave={(v) => (v.trim() ? void patch({ titre: v.trim() }) : undefined)} />
          </div>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
            <Tuile label="Revenus réels / mois" valeur={money(tb.reel_mensuel)} sous={`${money(tb.reel_annuel)} / an · baux standards`} />
            <Tuile label="Baux parallèles / mois" valeur={money(tb.paralleles_mensuel)} sous={d.inclure_paralleles ? `${money(tb.paralleles_annuel)} / an` : "exclus du dossier"} />
            <Tuile
              label="Loyers visés / mois"
              valeur={money(tb.vise_mensuel ?? tb.reel_mensuel)}
              sous={tb.nb_a_ajuster ? `${tb.nb_a_ajuster} unité(s) à ajuster${tb.ecart_projection_pct != null ? ` · ${tb.ecart_projection_pct > 0 ? "+" : ""}${tb.ecart_projection_pct} % vs en vigueur` : ""}` : "toutes les unités fixes"}
              accent
            />
            <Tuile label="Occupation" valeur={tb.taux_occupation_pct != null ? `${tb.taux_occupation_pct} %` : "—"} sous={`${tb.nb_unites} unités · ${tb.nb_vacantes} vacante(s)`} />
            <Tuile label="Pièces" valeur={`${tb.pieces_fournies}/${tb.pieces_requises}`} sous={tb.pieces_manquantes.length ? `${tb.pieces_manquantes.length} manquante(s)` : "complet"} alerte={tb.pieces_manquantes.length > 0} />
            <Tuile
              label="Échéance"
              valeur={tb.jours_avant_echeance != null ? `${tb.jours_avant_echeance} j` : "—"}
              sous={d.date_echeance ? fmtDate(d.date_echeance) : "aucune"}
              alerte={tb.jours_avant_echeance != null && tb.jours_avant_echeance < 14}
            />
          </div>
          <label className="block text-[11px] font-semibold text-white/60">
            Notes du dossier
            <NotesBlur value={d.notes || ""} onSave={(v) => void patch({ notes: v || null })} />
          </label>
          <Suivi d={d} onReload={load} onSupprimer={supprimer} />
        </>
      ) : null}

      {vue === "rentroll" ? <RentRollTab immeuble={immeuble} dossier={d} onPatchDossier={patch} /> : null}

      {vue === "pieces" ? <PiecesEtExports d={d} docs={docs} onReload={load} onPatch={patch} busy={busy} /> : null}

      {vue === "paralleles" ? (
        <>
          <p className="rounded-lg border border-brand-800 bg-brand-900/60 px-3 py-2 text-[11px] text-white/50">
            Les baux parallèles appartiennent à l&apos;immeuble : ils sont partagés par tous ses dossiers et n&apos;apparaissent nulle part ailleurs dans Kratos.
          </p>
          <ParallelesTab immeuble={immeuble} onChanged={load} />
        </>
      ) : null}

    </div>
  );
}

function NotesBlur({ value, onSave }: { value: string; onSave: (v: string) => void }) {
  const [v, setV] = useState(value);
  useEffect(() => setV(value), [value]);
  return <textarea rows={3} value={v} onChange={(e) => setV(e.target.value)} onBlur={() => (v !== value ? onSave(v) : undefined)} className={`${INPUT} mt-0.5 block w-full`} />;
}

// ─── Pièces et exports ─────────────────────────────────────────────

function PiecesEtExports({ d, docs, onReload, onPatch, busy }: { d: DossierDetail; docs: DocumentImm[]; onReload: () => Promise<void>; onPatch: (b: Record<string, unknown>) => Promise<void>; busy: boolean }) {
  const [err, setErr] = useState<string | null>(null);
  const [showPaquet, setShowPaquet] = useState(false);
  async function patchPiece(id: number, body: Record<string, unknown>) {
    setErr(null);
    const r = await authedFetch(`${FIN}/pieces/${id}`, { method: "PATCH", body: JSON.stringify(body) });
    if (!r.ok) {
      setErr(await lireErreur(r));
      return;
    }
    await onReload();
  }
  async function ajouterPiece() {
    const libelle = window.prompt("Libellé de la pièce à ajouter :");
    if (!libelle?.trim()) return;
    const r = await authedFetch(`${FIN}/dossiers/${d.id}/pieces`, { method: "POST", body: JSON.stringify({ type: "autre", libelle: libelle.trim() }) });
    if (!r.ok) {
      setErr(await lireErreur(r));
      return;
    }
    await onReload();
  }
  async function supprimerPiece(id: number) {
    if (!window.confirm("Retirer cette pièce de la checklist ?")) return;
    const r = await authedFetch(`${FIN}/pieces/${id}`, { method: "DELETE" });
    if (!r.ok) {
      setErr(await lireErreur(r));
      return;
    }
    await onReload();
  }

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      {err ? <p className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-200 lg:col-span-2">{err}</p> : null}
      <section className="rounded-xl border border-brand-800 bg-brand-900 p-3.5">
        <div className="flex items-center gap-2">
          <h4 className="text-xs font-semibold uppercase tracking-wider text-accent-500">Pièces à fournir</h4>
          <button type="button" onClick={() => void ajouterPiece()} className="btn-ghost btn-xs ml-auto">
            <Plus className="h-3 w-3" /> Ajouter
          </button>
        </div>
        <ul className="mt-2 divide-y divide-brand-800">
          {d.pieces.map((p) => {
            const doc = p.document_id ? docs.find((x) => x.id === p.document_id) : null;
            return (
              <li key={p.id} className="flex flex-wrap items-center gap-2 py-1.5 text-xs">
                <input type="checkbox" checked={p.fournie} onChange={(e) => void patchPiece(p.id, { envoye: e.target.checked })} title="Marquer envoyée / fournie" />
                <span className={`min-w-0 flex-1 ${p.fournie ? "text-white/50 line-through" : "text-white/85"}`}>
                  {p.libelle}
                  {!p.requis ? <span className="ml-1 text-white/35">(facultatif)</span> : null}
                </span>
                <span className="badge badge-neutral">{PIECE_LABEL[p.type] || p.type}</span>
                {doc ? (
                  <button type="button" onClick={() => void ouvrirPdfDocument(doc.id).catch((e) => setErr((e as Error).message))} className="text-accent-500 hover:underline" title={doc.titre}>
                    <FileText className="inline h-3 w-3" /> {doc.titre.slice(0, 28)}
                  </button>
                ) : (
                  <select
                    value=""
                    onChange={(e) => {
                      if (e.target.value) void patchPiece(p.id, { document_id: Number(e.target.value) });
                    }}
                    className={`${INPUT} max-w-[180px] py-1`}
                    title="Rattacher un document de l'immeuble"
                  >
                    <option value="">Rattacher un document…</option>
                    {docs.map((x) => (
                      <option key={x.id} value={x.id}>
                        {x.titre}
                        {x.numero ? ` (app. ${x.numero})` : ""}
                      </option>
                    ))}
                  </select>
                )}
                {p.envoye_le ? <span className="text-white/40">envoyée {fmtDateTime(p.envoye_le)}</span> : null}
                <button type="button" onClick={() => void supprimerPiece(p.id)} className="text-rose-300/50 hover:text-rose-300" title="Retirer">
                  <Trash2 className="h-3 w-3" />
                </button>
              </li>
            );
          })}
        </ul>
        <p className="mt-2 text-[11px] text-white/40">Importer une pièce : fiche de l&apos;immeuble → Documents, puis « Rattacher un document… » ici.</p>
      </section>

      <section className="rounded-xl border border-brand-800 bg-brand-900 p-3.5">
        <h4 className="text-xs font-semibold uppercase tracking-wider text-accent-500">Exports</h4>
        <p className="mt-1 text-[11px] text-white/50">
          Rent roll du dossier :{" "}
          <label className="inline-flex items-center gap-1">
            <input type="checkbox" checked={d.inclure_standards} disabled={busy} onChange={(e) => void onPatch({ inclure_standards: e.target.checked })} /> baux standards
          </label>{" "}
          <label className="inline-flex items-center gap-1">
            <input type="checkbox" checked={d.inclure_paralleles} disabled={busy} onChange={(e) => void onPatch({ inclure_paralleles: e.target.checked })} /> baux parallèles
          </label>
        </p>
        <div className="mt-2 flex flex-wrap gap-2">
          {(["pdf", "xlsx", "csv"] as const).map((fmt) => (
            <button
              key={fmt}
              type="button"
              onClick={() => void telecharger(`${FIN}/dossiers/${d.id}/rent-roll?fmt=${fmt}&projection=true`, `rent-roll.${fmt}`).catch((e) => setErr((e as Error).message))}
              className="btn-outline-accent btn-xs"
            >
              <Download className="h-3 w-3" /> Rent roll {fmt.toUpperCase()} (avec projection)
            </button>
          ))}
          <button type="button" onClick={() => void telecharger(`${FIN}/dossiers/${d.id}/rent-roll?fmt=pdf&projection=false`, "rent-roll.pdf").catch((e) => setErr((e as Error).message))} className="btn-outline-accent btn-xs">
            <Download className="h-3 w-3" /> Rent roll PDF (réel seulement)
          </button>
          <button type="button" onClick={() => setShowPaquet(true)} className="btn-accent btn-xs">
            <FileText className="h-3 w-3" /> Paquet PDF…
          </button>
        </div>
        <p className="mt-2 text-[11px] text-white/40">
          Tous les montants viennent des baux enregistrés. Les loyers visés des unités à ajuster (onglet Unités) apparaissent dans une colonne à part, identifiée comme objectif, jamais comme loyer en vigueur.
        </p>
      </section>
      {showPaquet ? <PaquetModal dossier={d} docs={docs} onClose={() => setShowPaquet(false)} /> : null}
    </div>
  );
}

function Suivi({ d, onReload, onSupprimer }: { d: DossierDetail; onReload: () => Promise<void>; onSupprimer: () => Promise<void> }) {
  const [note, setNote] = useState("");
  const [noteType, setNoteType] = useState("note");
  const [err, setErr] = useState<string | null>(null);

  async function ajouter() {
    if (!note.trim()) return;
    const r = await authedFetch(`${FIN}/dossiers/${d.id}/journal`, { method: "POST", body: JSON.stringify({ type: noteType, texte: note.trim() }) });
    if (!r.ok) {
      setErr(await lireErreur(r));
      return;
    }
    setNote("");
    await onReload();
  }

  return (
    <section className="rounded-xl border border-brand-800 bg-brand-900 p-3.5">
      <h4 className="text-xs font-semibold uppercase tracking-wider text-accent-500">Suivi dans le temps</h4>
      <div className="mt-2 flex flex-wrap gap-2">
        <select value={noteType} onChange={(e) => setNoteType(e.target.value)} className={`${INPUT} w-auto`}>
          <option value="note">Note</option>
          <option value="envoi">Envoi</option>
          <option value="appel">Appel</option>
          <option value="courriel">Courriel</option>
          <option value="reponse">Réponse du prêteur</option>
        </select>
        <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="Ce qui s'est passé…" className={`${INPUT} min-w-[240px] flex-1`} onKeyDown={(e) => (e.key === "Enter" ? void ajouter() : undefined)} />
        <button type="button" onClick={() => void ajouter()} className="btn-secondary btn-xs">
          <Plus className="h-3 w-3" /> Ajouter
        </button>
      </div>
      {err ? <p className="mt-2 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">{err}</p> : null}
      <ul className="mt-2 divide-y divide-brand-800 text-xs">
        {d.journal.map((j) => (
          <li key={j.id} className="flex flex-wrap items-center gap-2 py-1.5">
            <span className="badge badge-neutral">{j.type}</span>
            <span className="min-w-0 flex-1 text-white/85">{j.texte}</span>
            <span className="text-white/40">
              {fmtDateTime(j.created_at)}
              {j.auteur_email ? ` · ${j.auteur_email.split("@")[0]}` : ""}
            </span>
          </li>
        ))}
      </ul>
      <div className="mt-4 border-t border-brand-800 pt-3">
        <button type="button" onClick={() => void onSupprimer()} className="inline-flex items-center gap-1 text-xs text-rose-300/60 hover:text-rose-300">
          <Trash2 className="h-3 w-3" /> Supprimer le dossier
        </button>
      </div>
    </section>
  );
}

// ─── Étape 3 : unités fixes ou à ajuster ──────────────────────────────

const CIBLE_BADGE: Record<string, string> = {
  fixe: "badge-neutral",
  a_definir: "badge-amber",
  a_faire: "badge-amber",
  avis_envoye: "badge-sky",
  avis_accepte: "badge-emerald",
  avis_refuse: "badge-rose",
  bail_en_signature: "badge-violet",
  bail_a_venir: "badge-violet",
  atteint: "badge-emerald"
};

const CIBLE_FIXE: Cible = { mode: "fixe", loyer_vise: null, note: null, echeance: null, statut: "fixe", statut_label: "Fixe (tel quel)", renouvellement: null, ecart: null };

function LoyerViseInput({ valeur, disabled, onSave }: { valeur: number | null; disabled: boolean; onSave: (v: number | null) => void }) {
  const [v, setV] = useState(valeur != null ? String(valeur) : "");
  useEffect(() => {
    setV(valeur != null ? String(valeur) : "");
  }, [valeur]);
  function commit() {
    const n = v.trim() ? Number(v) : null;
    if (n != null && !Number.isFinite(n)) return;
    if (n === valeur) return;
    onSave(n);
  }
  return (
    <input
      type="number"
      min={0}
      step={5}
      inputMode="decimal"
      value={v}
      disabled={disabled}
      onChange={(e) => setV(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => {
        if (e.key === "Enter") (e.target as HTMLInputElement).blur();
      }}
      placeholder="Loyer visé"
      className={`${INPUT} w-28 text-right font-mono`}
    />
  );
}

function UnitesTab({ immeuble, dossier, docs, onChanged }: { immeuble: ImmeubleLite; dossier: DossierDetail; docs: DocumentImm[]; onChanged: () => Promise<void> }) {
  const [err, setErr] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);
  const [avisFor, setAvisFor] = useState<RentRollLigne | null>(null);
  const [bailFor, setBailFor] = useState<RentRollLigne | null>(null);
  const [docsOuverts, setDocsOuverts] = useState<Record<number, boolean>>({});
  const lignes = dossier.rent_roll.lignes;
  const t = dossier.rent_roll.totaux as Record<string, number | null>;
  const tb = dossier.tableau_de_bord;

  async function regler(l: RentRollLigne, body: Record<string, unknown>) {
    setBusyId(l.logement_id);
    setErr(null);
    try {
      const r = await authedFetch(`${FIN}/dossiers/${dossier.id}/unites/${l.logement_id}`, { method: "PATCH", body: JSON.stringify(body) });
      if (!r.ok) throw new Error(await lireErreur(r));
      await onChanged();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusyId(null);
    }
  }

  function docsDe(l: RentRollLigne): DocumentImm[] {
    const bails = new Set<number>([...(l.bail_id != null ? [l.bail_id] : []), ...(l.baux || []).map((b) => b.bail_id), ...(l.sous_locations || []).map((b) => b.bail_id)]);
    return docs.filter((d) => d.logement_id === l.logement_id || (d.bail_id != null && bails.has(d.bail_id)));
  }

  return (
    <div className="space-y-3">
      <div className="rounded-xl border border-brand-800 bg-brand-900/60 px-3 py-2 text-xs text-white/70">
        <b className="text-white">Fixe</b> : l&apos;unité part telle qu&apos;elle est dans Gestion locative — ses baux et avis sont à côté, rien à changer.{" "}
        <b className="text-white">À ajuster</b> : tu écris le loyer visé ; le rent roll le montre à côté du loyer en vigueur et tu crées l&apos;avis de renouvellement ou le nouveau bail au moment venu.
        Le statut vient des baux et des avis réels.
      </div>
      {err ? <p className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">{err}</p> : null}
      <div className="overflow-x-auto rounded-xl border border-brand-800 bg-brand-900">
        <table className="w-full text-xs">
          <thead className="bg-brand-950/60 text-[11px] uppercase tracking-wider text-white/50">
            <tr>
              <th className="px-3 py-2 text-left">Unité</th>
              <th className="px-3 py-2 text-left">En vigueur (Gestion locative)</th>
              <th className="px-3 py-2 text-left">Mode</th>
              <th className="px-3 py-2 text-right">Loyer visé</th>
              <th className="px-3 py-2 text-left">Statut</th>
              <th className="px-3 py-2 text-left">Baux et avis</th>
              <th className="px-3 py-2 text-right">Au moment venu</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-brand-800">
            {lignes.map((l) => {
              const c = l.cible || CIBLE_FIXE;
              const ajuster = c.mode === "ajuster";
              const busy = busyId === l.logement_id;
              const dd = docsDe(l);
              const ren = c.renouvellement;
              const bailStandardCourant = !!l.bail_id && !l.baux?.length && l.categorie !== "bail_principal";
              const visibles = docsOuverts[l.logement_id] ? dd : dd.slice(0, 3);
              return (
                <tr key={l.logement_id} className={ajuster ? "bg-amber-500/[0.04]" : ""}>
                  <td className="px-3 py-2 font-semibold text-white">
                    {l.numero}
                    {l.nb_pieces ? <span className="ml-1 font-normal text-white/40">{String(l.nb_pieces).replace(".5", "½")}</span> : null}
                  </td>
                  <td className="px-3 py-2 text-white/85">
                    <div>{l.locataire || <span className="text-white/40">{OCCUPATION_LABEL[l.occupation] || l.occupation}</span>}</div>
                    <div className="text-[11px] text-white/50">
                      {l.loyer != null ? <span className="font-mono text-white/85">{money(l.loyer)}</span> : "—"}
                      {l.bail_id ? (
                        <>
                          {" "}
                          · {fmtDate(l.date_debut)} → {l.au_mois ? "au mois" : fmtDate(l.date_fin)}
                        </>
                      ) : null}
                      {l.categorie === "bail_principal" ? " · bail principal" : ""}
                      {l.baux?.length ? ` · ${l.baux.length} chambres` : ""}
                      {l.nb_paralleles ? ` · +${l.nb_paralleles} parallèle` : ""}
                    </div>
                    {l.prochain ? (
                      <div className="text-[11px] text-white/40">
                        prochain : {l.prochain.locataire || "—"} · {fmtDate(l.prochain.date_debut)} · {money(l.prochain.loyer)}
                      </div>
                    ) : null}
                  </td>
                  <td className="px-3 py-2">
                    <div className="inline-flex rounded-lg border border-brand-800 p-0.5">
                      <button
                        type="button"
                        disabled={busy}
                        onClick={() => (ajuster ? void regler(l, { mode: "fixe" }) : undefined)}
                        className={`rounded-md px-2 py-1 text-[11px] font-semibold ${!ajuster ? "bg-white/10 text-white" : "text-white/50 hover:text-white"}`}
                      >
                        Fixe
                      </button>
                      <button
                        type="button"
                        disabled={busy}
                        onClick={() => (!ajuster ? void regler(l, { mode: "ajuster" }) : undefined)}
                        className={`rounded-md px-2 py-1 text-[11px] font-semibold ${ajuster ? "bg-amber-500/20 text-amber-200" : "text-white/50 hover:text-white"}`}
                      >
                        À ajuster
                      </button>
                    </div>
                  </td>
                  <td className="px-3 py-2 text-right">
                    {ajuster ? (
                      <>
                        <LoyerViseInput valeur={c.loyer_vise} disabled={busy} onSave={(v) => void regler(l, { mode: "ajuster", loyer: v })} />
                        {c.ecart != null ? (
                          <div className="text-[10px] text-white/40">
                            {c.ecart >= 0 ? "+" : ""}
                            {money(c.ecart)} vs en vigueur
                          </div>
                        ) : null}
                      </>
                    ) : (
                      <span className="font-mono text-white/40">{l.loyer != null ? money(l.loyer) : "—"}</span>
                    )}
                  </td>
                  <td className="px-3 py-2">
                    <span className={`badge ${CIBLE_BADGE[c.statut] || "badge-neutral"}`}>{c.statut_label}</span>
                    {ren ? (
                      <div className="text-[11px] text-white/40">
                        avis du {fmtDate(ren.avis_envoye_le)} · {money(ren.nouveau_loyer)}
                        {ren.document_id ? (
                          <>
                            {" · "}
                            <button type="button" onClick={() => void ouvrirPdfDocument(ren.document_id as number).catch((e) => setErr((e as Error).message))} className="text-accent-500 hover:underline">
                              PDF
                            </button>
                          </>
                        ) : null}
                      </div>
                    ) : null}
                    {c.note ? <div className="text-[11px] text-white/40">{c.note}</div> : null}
                  </td>
                  <td className="px-3 py-2 text-white/70">
                    {dd.length ? (
                      <div className="space-y-0.5">
                        {visibles.map((doc) => (
                          <div key={doc.id} className="flex items-center gap-1 text-[11px]">
                            <span className="badge badge-neutral">{docTypeLabel(doc.type) || doc.type}</span>
                            <button type="button" onClick={() => void ouvrirPdfDocument(doc.id).catch((e) => setErr((e as Error).message))} className="max-w-[220px] truncate text-accent-500 hover:underline" title={doc.titre}>
                              {doc.titre}
                            </button>
                            {doc.signed_at ? <Check className="h-3 w-3 text-emerald-400" /> : null}
                          </div>
                        ))}
                        {dd.length > 3 ? (
                          <button type="button" onClick={() => setDocsOuverts({ ...docsOuverts, [l.logement_id]: !docsOuverts[l.logement_id] })} className="text-[11px] text-white/40 hover:text-white">
                            {docsOuverts[l.logement_id] ? "moins" : `+${dd.length - 3} autres`}
                          </button>
                        ) : null}
                      </div>
                    ) : (
                      <span className="text-[11px] text-white/30">aucun document</span>
                    )}
                  </td>
                  <td className="px-3 py-2">
                    {ajuster ? (
                      <div className="flex flex-wrap justify-end gap-1">
                        {bailStandardCourant ? (
                          <button type="button" onClick={() => setAvisFor(l)} className="btn-outline-accent btn-xs" title="Avis officiel TAL de renouvellement (hausse de loyer) au locataire en place, au loyer visé">
                            <Send className="h-3 w-3" /> Avis de renouvellement
                          </button>
                        ) : null}
                        <button type="button" onClick={() => setBailFor(l)} className="btn-secondary btn-xs" title="Nouveau bail parallèle (sous-location, bail principal…) au loyer visé">
                          <FileSignature className="h-3 w-3" /> Nouveau bail
                        </button>
                        {l.occupation === "vacant" || l.occupation === "reserve" ? (
                          <Link
                            // eslint-disable-next-line @typescript-eslint/no-explicit-any
                            href={"/immobilier/locations" as any}
                            className="btn-ghost btn-xs"
                            title="Louer l'unité à un vrai locataire (Locations & nouveaux baux)"
                          >
                            Louer
                          </Link>
                        ) : null}
                      </div>
                    ) : (
                      <span className="block text-right text-[11px] text-white/30">tel quel</span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
          <tfoot className="bg-brand-950/60 text-xs font-semibold text-white">
            <tr>
              <td className="px-3 py-2" colSpan={2}>
                En vigueur : {money(t.mensuel_standard)} / mois · {tb.nb_a_ajuster || 0} unité(s) à ajuster
              </td>
              <td className="px-3 py-2 text-right text-amber-200" colSpan={2}>
                Visé : {money(tb.vise_mensuel ?? t.mensuel_standard)} / mois
              </td>
              <td className="px-3 py-2 text-white/60" colSpan={3}>
                {tb.nb_cibles_atteintes || 0} objectif(s) atteint(s) · le rent roll (onglet suivant) montre les deux colonnes
              </td>
            </tr>
          </tfoot>
        </table>
      </div>
      {avisFor ? <AvisRenouvellementModal ligne={avisFor} onClose={() => setAvisFor(null)} onSent={() => void onChanged()} /> : null}
      {bailFor ? (
        <BailParalleleModal
          immeuble={immeuble}
          prefill={{ logement_id: bailFor.logement_id, loyer_mensuel: bailFor.cible?.loyer_vise ?? null }}
          onClose={() => setBailFor(null)}
          onSaved={() => {
            setBailFor(null);
            void onChanged();
          }}
        />
      ) : null}
    </div>
  );
}

function AvisRenouvellementModal({ ligne, onClose, onSent }: { ligne: RentRollLigne; onClose: () => void; onSent: () => void }) {
  const [nouveau, setNouveau] = useState(ligne.cible?.loyer_vise != null ? String(ligne.cible.loyer_vise) : "");
  const [debut, setDebut] = useState("");
  const [fin, setFin] = useState("");
  const [motif, setMotif] = useState("");
  const [certifie, setCertifie] = useState(true);
  const [force, setForce] = useState(false);
  const [busy, setBusy] = useState<"apercu" | "envoi" | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const bailId = ligne.bail_id as number;

  function corps() {
    return { nouveau_loyer: Number(nouveau) || null, nouvelle_date_debut: debut || null, nouvelle_date_fin: fin || null, motif: motif.trim() || null };
  }

  async function apercu() {
    setBusy("apercu");
    setErr(null);
    try {
      const r = await authedFetch(`/api/v1/immobilier/baux/${bailId}/tal/avis_modification.pdf`, { method: "POST", body: JSON.stringify(corps()) });
      if (!r.ok) throw new Error(await lireErreur(r));
      window.open(URL.createObjectURL(await r.blob()), "_blank");
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function envoyer() {
    if (!(Number(nouveau) > 0)) {
      setErr("Indique le nouveau loyer.");
      return;
    }
    setBusy("envoi");
    setErr(null);
    setMsg(null);
    try {
      const r = await authedFetch(`/api/v1/immobilier/baux/${bailId}/envoyer-renouvellement`, {
        method: "POST",
        body: JSON.stringify({ ...corps(), force, request_read_receipt: certifie, bcc_to_sender: certifie })
      });
      if (!r.ok) throw new Error(await lireErreur(r));
      const d = (await r.json()) as { courriel_envoye: boolean; erreur_envoi?: string | null; expediteur?: string | null };
      setMsg(d.courriel_envoye ? `Avis envoyé au locataire${d.expediteur ? ` depuis ${d.expediteur}` : ""}. Rien reçu ? Qu'il vérifie ses courriers indésirables.` : `Avis créé, mais courriel NON parti : ${d.erreur_envoi || "raison inconnue"}`);
      onSent();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  return (
    <Modal titre={`Avis de renouvellement — logement ${ligne.numero} · ${ligne.locataire || ""}`} onClose={onClose}>
      <p className="text-xs text-white/60">
        Avis officiel TAL de modification du bail (hausse de loyer), envoyé par courriel au locataire en place — le même qu&apos;à la page Renouvellements. Loyer en vigueur :{" "}
        <b className="text-white">{money(ligne.loyer)}</b>
        {ligne.date_fin ? ` · bail jusqu'au ${fmtDate(ligne.date_fin)}` : ""}.
      </p>
      <div className="mt-3 grid gap-3 sm:grid-cols-3">
        <Champ label="Nouveau loyer ($ / mois)" value={nouveau} onChange={setNouveau} inputMode="decimal" />
        <Champ label="Début du bail renouvelé (vide = lendemain de la fin)" value={debut} onChange={setDebut} type="date" />
        <Champ label="Fin (vide = 12 mois)" value={fin} onChange={setFin} type="date" />
      </div>
      <label className="mt-3 block text-[11px] font-semibold text-white/60">
        Motif (optionnel)
        <input value={motif} onChange={(e) => setMotif(e.target.value)} className={`${INPUT} mt-0.5 block w-full`} />
      </label>
      <div className="mt-2 flex flex-wrap gap-4 text-xs text-white/70">
        <label className="flex items-center gap-1.5">
          <input type="checkbox" checked={certifie} onChange={(e) => setCertifie(e.target.checked)} /> Envoi certifié (accusé de lecture + copie à l&apos;expéditeur)
        </label>
        <label className="flex items-center gap-1.5">
          <input type="checkbox" checked={force} onChange={(e) => setForce(e.target.checked)} /> Remplacer un avis déjà envoyé pour ce cycle
        </label>
      </div>
      {err ? <p className="mt-2 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">{err}</p> : null}
      {msg ? <p className="mt-2 rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-xs text-emerald-200">{msg}</p> : null}
      <div className="mt-4 flex flex-wrap justify-end gap-2">
        <button type="button" onClick={onClose} className="btn-ghost btn-sm">
          Fermer
        </button>
        <button type="button" disabled={busy !== null} onClick={() => void apercu()} className="btn-secondary btn-sm">
          {busy === "apercu" ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <FileText className="h-3.5 w-3.5" />} Aperçu PDF
        </button>
        <button type="button" disabled={busy !== null || !!msg} onClick={() => void envoyer()} className="btn-primary btn-sm">
          {busy === "envoi" ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Send className="h-3.5 w-3.5" />} Envoyer l&apos;avis au locataire
        </button>
      </div>
    </Modal>
  );
}

function PaquetModal({ dossier, docs, onClose }: { dossier: DossierDetail; docs: DocumentImm[]; onClose: () => void }) {
  const [choisis, setChoisis] = useState<number[]>(() => docs.filter((x) => x.est_bail_courant || x.type === "bail").map((x) => x.id));
  const [rentRoll, setRentRoll] = useState(true);
  const [projection, setProjection] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const pdfs = docs.filter((x) => !x.filename || /\.pdf$/i.test(x.filename) || x.source === "genere");

  function toggle(id: number) {
    setChoisis((c) => (c.includes(id) ? c.filter((x) => x !== id) : [...c, id]));
  }

  async function generer() {
    setBusy(true);
    setErr(null);
    try {
      await telecharger(`${FIN}/dossiers/${dossier.id}/paquet.pdf?documents=${choisis.join(",")}&rent_roll=${rentRoll}&projection=${projection}`, "dossier-financement.pdf");
      onClose();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal titre="Paquet PDF du dossier" onClose={onClose} zIndex="z-[70]">
      <label className="flex items-center gap-2 text-xs text-white/85">
        <input type="checkbox" checked={rentRoll} onChange={(e) => setRentRoll(e.target.checked)} /> Rent roll en première page
        {rentRoll ? (
          <label className="ml-3 inline-flex items-center gap-1 text-white/60">
            <input type="checkbox" checked={projection} onChange={(e) => setProjection(e.target.checked)} /> avec la colonne « loyer visé » (unités à ajuster)
          </label>
        ) : null}
      </label>
      <p className="mt-3 text-[11px] font-semibold uppercase tracking-wider text-white/50">Pièces de l&apos;immeuble ({pdfs.length})</p>
      <ul className="mt-1 max-h-72 divide-y divide-brand-800 overflow-y-auto rounded-lg border border-brand-800 text-xs">
        {pdfs.map((x) => (
          <li key={x.id} className="flex items-center gap-2 px-2 py-1.5">
            <input type="checkbox" checked={choisis.includes(x.id)} onChange={() => toggle(x.id)} />
            <span className="min-w-0 flex-1 truncate text-white/85">{x.titre}</span>
            {x.numero ? <span className="text-white/45">app. {x.numero}</span> : null}
            {x.bail_categorie === "parallele" ? <span className="badge badge-violet">parallèle</span> : null}
            {x.est_bail_courant ? <span className="badge badge-emerald">bail courant</span> : null}
            <span className="text-white/35">{fmtDate(x.signed_at || x.created_at)}</span>
          </li>
        ))}
        {pdfs.length === 0 ? <li className="px-2 py-3 text-white/40">Aucune pièce PDF pour cet immeuble.</li> : null}
      </ul>
      {err ? <p className="mt-3 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">{err}</p> : null}
      <div className="mt-4 flex justify-end gap-2 border-t border-brand-800 pt-3">
        <button type="button" onClick={onClose} className="btn-secondary btn-sm">
          Annuler
        </button>
        <button type="button" disabled={busy || (!rentRoll && choisis.length === 0)} onClick={() => void generer()} className="btn-accent btn-sm disabled:opacity-60">
          {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />} Télécharger le paquet
        </button>
      </div>
    </Modal>
  );
}

// ─── Rent roll (dans le dossier) ──────────────────────────────────────

function RentRollTab({ immeuble, dossier, onPatchDossier }: { immeuble: ImmeubleLite; dossier: DossierDetail; onPatchDossier: (b: Record<string, unknown>) => Promise<void> }) {
  const [rr, setRr] = useState<RentRoll | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [corriger, setCorriger] = useState<{ bailId: number; categorie: "standard" | "parallele"; loyer: number | null; debut: string | null; fin: string | null; libelle: string } | null>(null);
  const [talFor, setTalFor] = useState<{ bailId: number; titre: string } | null>(null);
  const standards = dossier.inclure_standards;
  const paralleles = dossier.inclure_paralleles;

  const load = useCallback(async () => {
    const r = await authedFetch(`${FIN}/dossiers/${dossier.id}/rent-roll?projection=true`);
    if (!r.ok) {
      setErr(await lireErreur(r));
      return;
    }
    setErr(null);
    setRr((await r.json()) as RentRoll);
  }, [dossier.id]);

  useEffect(() => {
    void load();
  }, [load, dossier.updated_at, dossier.inclure_standards, dossier.inclure_paralleles]);

  const t = (rr?.totaux || {}) as Record<string, number | null>;
  const avecProj = !!rr?.projection;

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-3 rounded-xl border border-brand-800 bg-brand-900/60 px-3 py-2 text-xs">
        <span className="font-semibold text-white/70">Dans ce dossier :</span>
        <label className="flex items-center gap-1.5 text-white/85">
          <input type="checkbox" checked={standards} onChange={(e) => void onPatchDossier({ inclure_standards: e.target.checked })} /> Baux standards
        </label>
        <label className="flex items-center gap-1.5 text-white/85">
          <input type="checkbox" checked={paralleles} onChange={(e) => void onPatchDossier({ inclure_paralleles: e.target.checked })} /> Baux parallèles
        </label>
        <span className="ml-auto flex flex-wrap gap-2">
          {(["pdf", "xlsx", "csv"] as const).map((fmt) => (
            <button key={fmt} type="button" onClick={() => void telecharger(`${FIN}/dossiers/${dossier.id}/rent-roll?fmt=${fmt}&projection=true`, `rent-roll.${fmt}`).catch((e) => setErr((e as Error).message))} className="btn-outline-accent btn-xs">
              <Download className="h-3 w-3" /> {fmt.toUpperCase()}
            </button>
          ))}
          <button type="button" onClick={() => void load()} className="btn-ghost btn-xs" title="Rafraîchir">
            <RefreshCw className="h-3 w-3" />
          </button>
        </span>
      </div>
      {err ? <p className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">{err}</p> : null}
      {!rr ? (
        <p className="flex items-center gap-2 py-6 text-xs text-white/50">
          <Loader2 className="h-4 w-4 animate-spin" /> Chargement…
        </p>
      ) : (
        <>
          {standards ? (
            <div className="overflow-x-auto rounded-xl border border-brand-800 bg-brand-900">
              <table className="w-full text-xs">
                <thead className="bg-brand-950/60 text-[11px] uppercase tracking-wider text-white/50">
                  <tr>
                    <th className="px-3 py-2 text-left">Unité</th>
                    <th className="px-3 py-2 text-left">Occupation</th>
                    <th className="px-3 py-2 text-left">Locataire</th>
                    <th className="px-3 py-2 text-right">Loyer / mois</th>
                    {avecProj ? <th className="px-3 py-2 text-right text-amber-300">Loyer visé*</th> : null}
                    <th className="px-3 py-2 text-left">Inclusions</th>
                    <th className="px-3 py-2 text-left">Bail</th>
                    <th className="px-3 py-2 text-left">Signé</th>
                    <th className="px-3 py-2 text-right">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-brand-800">
                  {rr.lignes.map((l) => (
                    <tr key={l.logement_id}>
                      <td className="px-3 py-2 font-semibold text-white">
                        {l.numero}
                        {l.nb_pieces ? <span className="ml-1 font-normal text-white/40">{String(l.nb_pieces).replace(".5", "½")}</span> : null}
                        {l.nb_paralleles ? <span className="badge badge-violet ml-1">+{l.nb_paralleles} parallèle</span> : null}
                        {l.categorie === "bail_principal" ? <span className="badge badge-sky ml-1">bail principal</span> : null}
                      </td>
                      <td className="px-3 py-2 text-white/70">
                        {OCCUPATION_LABEL[l.occupation] || l.occupation}
                        {l.mention ? <div className="text-[11px] text-white/40">{l.mention}</div> : null}
                        {l.sous_locations?.length ? (
                          <div className="text-[11px] text-white/40">
                            sous-locations : {l.sous_locations.map((s) => `${s.locataire || "—"} (${money(s.loyer)})`).join(", ")}
                          </div>
                        ) : null}
                        {l.prochain ? (
                          <div className="text-[11px] text-white/40">
                            prochain : {l.prochain.locataire || "—"} · {fmtDate(l.prochain.date_debut)} · {money(l.prochain.loyer)}
                          </div>
                        ) : null}
                      </td>
                      <td className="px-3 py-2 text-white/85">
                        {l.locataire_id ? (
                          <Link
                            // eslint-disable-next-line @typescript-eslint/no-explicit-any
                            href={`/immobilier/locataires/${l.locataire_id}` as any}
                            className="hover:underline"
                          >
                            {l.locataire}
                          </Link>
                        ) : (
                          "—"
                        )}
                      </td>
                      <td className="px-3 py-2 text-right font-mono text-white/85">{money(l.loyer)}</td>
                      {avecProj ? (
                        <td className="px-3 py-2 text-right font-mono text-amber-200">
                          {money(l.projection?.loyer)}
                          <span className="ml-1 text-[10px] text-amber-200/60">{l.projection?.statut_label || ""}</span>
                        </td>
                      ) : null}
                      <td className="px-3 py-2 text-white/60">{l.inclusions.join(", ") || (l.bail_id ? "—" : "")}</td>
                      <td className="px-3 py-2 text-white/60">
                        {l.bail_id ? (
                          <>
                            {fmtDate(l.date_debut)} → {l.au_mois ? "au mois" : fmtDate(l.date_fin)}
                            {l.jour_echeance && l.jour_echeance !== 1 ? <span className="text-white/40"> · le {l.jour_echeance}</span> : null}
                          </>
                        ) : (
                          ""
                        )}
                      </td>
                      <td className="px-3 py-2">{l.bail_id || l.baux?.length ? <span className={`badge ${l.document_signe ? "badge-emerald" : "badge-amber"}`}>{l.document_signe ? "oui" : l.baux?.length ? "incomplet" : "non"}</span> : null}</td>
                      <td className="px-3 py-2">
                        {l.baux?.length ? (
                          <div className="space-y-1">
                            {l.baux.map((b) => (
                              <div key={b.bail_id} className="flex flex-wrap items-center justify-end gap-1">
                                <span className="mr-auto text-[11px] text-white/60">
                                  {b.locataire || "—"} · {money(b.loyer)}
                                  {b.document_signe ? "" : " · non signé"}
                                </span>
                                <button
                                  type="button"
                                  onClick={() => setCorriger({ bailId: b.bail_id, categorie: "standard", loyer: b.loyer, debut: b.date_debut, fin: b.date_fin, libelle: `Logement ${l.numero} · chambre · ${b.locataire || ""}` })}
                                  className="btn-ghost btn-xs"
                                >
                                  <Pencil className="h-3 w-3" />
                                </button>
                                <TalFormDropdown bailId={b.bail_id} />
                                <button type="button" onClick={() => setTalFor({ bailId: b.bail_id, titre: `Logement ${l.numero} · chambre · ${immeuble.name} · ${b.locataire || ""}` })} className="btn-outline-accent btn-xs">
                                  <FileSignature className="h-3 w-3" />
                                </button>
                              </div>
                            ))}
                          </div>
                        ) : l.bail_id ? (
                          <div className="flex flex-wrap justify-end gap-1">
                            <button
                              type="button"
                              onClick={() => setCorriger({ bailId: l.bail_id as number, categorie: "standard", loyer: l.loyer, debut: l.date_debut, fin: l.date_fin, libelle: `Logement ${l.numero} · ${l.locataire || ""}` })}
                              className="btn-ghost btn-xs"
                              title="Corriger le bail dans Kratos (journalisé) — l'export suit"
                            >
                              <Pencil className="h-3 w-3" /> Corriger
                            </button>
                            <TalFormDropdown bailId={l.bail_id} />
                            <button type="button" onClick={() => setTalFor({ bailId: l.bail_id as number, titre: `Logement ${l.numero} · ${immeuble.name} · ${l.locataire || ""}` })} className="btn-outline-accent btn-xs" title="Bail officiel TAL + signature">
                              <FileSignature className="h-3 w-3" /> Bail TAL
                            </button>
                          </div>
                        ) : null}
                      </td>
                    </tr>
                  ))}
                </tbody>
                <tfoot className="bg-brand-950/60 text-xs font-semibold text-white">
                  <tr>
                    <td className="px-3 py-2" colSpan={3}>
                      Total baux standards · {t.nb_occupees ?? 0} occupées / {t.nb_unites ?? 0} unités
                    </td>
                    <td className="px-3 py-2 text-right font-mono">{money(t.mensuel_standard)}</td>
                    {avecProj ? <td className="px-3 py-2 text-right font-mono text-amber-200">{money(t.projection_mensuelle)}</td> : null}
                    <td className="px-3 py-2 text-white/60" colSpan={4}>
                      {money(t.annuel_standard)} / an
                      {avecProj && t.projection_annuelle != null ? ` · visé ${money(t.projection_annuelle)} / an (objectif, pas un bail)` : ""}
                    </td>
                  </tr>
                </tfoot>
              </table>
            </div>
          ) : null}

          {paralleles ? (
            <div className="overflow-x-auto rounded-xl border border-violet-500/30 bg-brand-900">
              <div className="px-3 py-2 text-xs text-violet-200">
                <b>Baux parallèles</b> — sous-locations et baux principaux d&apos;exploitant : contrats réels signés entre le locateur indiqué et l&apos;occupant, hors du quotidien.
              </div>
              <table className="w-full text-xs">
                <thead className="bg-brand-950/60 text-[11px] uppercase tracking-wider text-white/50">
                  <tr>
                    <th className="px-3 py-2 text-left">Unité</th>
                    <th className="px-3 py-2 text-left">Occupant</th>
                    <th className="px-3 py-2 text-left">Locateur du bail</th>
                    <th className="px-3 py-2 text-left">Type</th>
                    <th className="px-3 py-2 text-right">Loyer / mois</th>
                    <th className="px-3 py-2 text-left">Bail</th>
                    <th className="px-3 py-2 text-left">Statut</th>
                    <th className="px-3 py-2 text-right">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-brand-800">
                  {rr.paralleles.map((p) => (
                    <tr key={p.bail_id}>
                      <td className="px-3 py-2 font-semibold text-white">{p.numero}</td>
                      <td className="px-3 py-2 text-white/85">{p.locataire || "—"}</td>
                      <td className="px-3 py-2 text-white/70">{p.locateur_bail || "—"}</td>
                      <td className="px-3 py-2 text-white/60">{p.type_label}</td>
                      <td className="px-3 py-2 text-right font-mono text-white/85">{money(p.loyer)}</td>
                      <td className="px-3 py-2 text-white/60">
                        {fmtDate(p.date_debut)} → {p.au_mois ? "au mois" : fmtDate(p.date_fin)}
                      </td>
                      <td className="px-3 py-2">
                        <span className={`badge ${p.en_vigueur ? (p.echu ? "badge-amber" : "badge-emerald") : "badge-violet"}`}>{p.en_vigueur ? (p.echu ? "échu" : "en vigueur") : p.statut === "propose" ? "en signature" : p.statut}</span>
                        <span className={`badge ml-1 ${p.document_signe ? "badge-emerald" : "badge-neutral"}`}>{p.document_signe ? "signé" : "pas de PDF"}</span>
                      </td>
                      <td className="px-3 py-2">
                        <div className="flex flex-wrap justify-end gap-1">
                          <button
                            type="button"
                            onClick={() => setCorriger({ bailId: p.bail_id, categorie: "parallele", loyer: p.loyer, debut: p.date_debut, fin: p.date_fin, libelle: `Logement ${p.numero} · ${p.locataire || ""} (parallèle)` })}
                            className="btn-ghost btn-xs"
                          >
                            <Pencil className="h-3 w-3" /> Corriger
                          </button>
                          <TalFormDropdown bailId={p.bail_id} />
                          <button type="button" onClick={() => setTalFor({ bailId: p.bail_id, titre: `Logement ${p.numero} · ${immeuble.name} · ${p.locataire || ""} (bail parallèle)` })} className="btn-outline-accent btn-xs">
                            <FileSignature className="h-3 w-3" /> Bail TAL
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                  {rr.paralleles.length === 0 ? (
                    <tr>
                      <td className="px-3 py-3 text-white/40" colSpan={8}>
                        Aucun bail parallèle — onglet « Baux parallèles » pour en enregistrer un.
                      </td>
                    </tr>
                  ) : null}
                </tbody>
                <tfoot className="bg-brand-950/60 text-xs font-semibold text-white">
                  <tr>
                    <td className="px-3 py-2" colSpan={4}>
                      Total baux parallèles en vigueur · {t.nb_paralleles ?? 0}
                    </td>
                    <td className="px-3 py-2 text-right font-mono">{money(t.mensuel_paralleles)}</td>
                    <td className="px-3 py-2 text-white/60" colSpan={3}>
                      {money(t.annuel_paralleles)} / an
                    </td>
                  </tr>
                </tfoot>
              </table>
            </div>
          ) : null}
          <p className="text-[11px] text-white/40">
            Situation au {fmtDate(rr.a_date)}. Le rent roll est produit par les baux enregistrés, jamais l&apos;inverse : pour changer un chiffre, corrige le bail (« Corriger »), c&apos;est journalisé et l&apos;export suit.
            {avecProj ? " * Loyer visé = objectif du propriétaire pour les unités à ajuster (onglet Unités), pas un bail." : ""}
          </p>
        </>
      )}

      {corriger ? (
        <CorrigerBailModal
          cible={corriger}
          onClose={() => setCorriger(null)}
          onDone={() => {
            setCorriger(null);
            void load();
          }}
        />
      ) : null}
      {talFor ? <TalBailModal bailId={talFor.bailId} titre={talFor.titre} onClose={() => setTalFor(null)} onDone={() => void load()} /> : null}
    </div>
  );
}

function CorrigerBailModal({ cible, onClose, onDone }: { cible: { bailId: number; categorie: "standard" | "parallele"; loyer: number | null; debut: string | null; fin: string | null; libelle: string }; onClose: () => void; onDone: () => void }) {
  const [loyer, setLoyer] = useState(cible.loyer != null ? String(cible.loyer) : "");
  const [debut, setDebut] = useState(cible.debut || "");
  const [fin, setFin] = useState(cible.fin || "");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function submit() {
    setBusy(true);
    setErr(null);
    try {
      const body: Record<string, unknown> = {};
      if (loyer.trim() !== (cible.loyer != null ? String(cible.loyer) : "")) body.loyer_mensuel = Number(loyer.replace(",", "."));
      if (debut !== (cible.debut || "")) body.date_debut = debut || null;
      if (fin !== (cible.fin || "")) body.date_fin = fin || null;
      if (Object.keys(body).length === 0) {
        onClose();
        return;
      }
      const url = cible.categorie === "parallele" ? `${FIN}/baux-paralleles/${cible.bailId}` : `/api/v1/immobilier/baux/${cible.bailId}`;
      const r = await authedFetch(url, { method: "PATCH", body: JSON.stringify(body) });
      if (!r.ok) throw new Error(await lireErreur(r));
      onDone();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal titre={`Corriger le bail — ${cible.libelle}`} onClose={onClose} zIndex="z-[70]">
      <p className="rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs text-amber-100">
        <AlertTriangle className="mr-1 inline h-3.5 w-3.5" />
        Ceci modifie le bail dans Kratos (journalisé) : Paiements, Baux et exports suivront. Rien n&apos;est modifié « pour l&apos;export » seulement.
      </p>
      <div className="mt-3 grid gap-3 sm:grid-cols-3">
        <Champ label="Loyer mensuel ($)" value={loyer} onChange={setLoyer} inputMode="decimal" />
        <Champ label="Début" value={debut} onChange={setDebut} type="date" />
        <Champ label="Fin" value={fin} onChange={setFin} type="date" />
      </div>
      {err ? <p className="mt-3 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">{err}</p> : null}
      <div className="mt-4 flex justify-end gap-2 border-t border-brand-800 pt-3">
        <button type="button" onClick={onClose} className="btn-secondary btn-sm">
          Annuler
        </button>
        <button type="button" disabled={busy} onClick={() => void submit()} className="btn-accent btn-sm disabled:opacity-60">
          {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Check className="h-4 w-4" />} Corriger le bail
        </button>
      </div>
    </Modal>
  );
}

// ─── Baux parallèles (de l'immeuble) ──────────────────────────────────

function ParallelesTab({ immeuble, onChanged }: { immeuble: ImmeubleLite; onChanged?: () => Promise<void> }) {
  const [items, setItems] = useState<BailParallele[] | null>(null);
  const [inclureTermines, setInclureTermines] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [edit, setEdit] = useState<BailParallele | null>(null);
  const [talFor, setTalFor] = useState<BailParallele | null>(null);
  const [importFor, setImportFor] = useState<BailParallele | null>(null);

  const load = useCallback(async () => {
    const r = await authedFetch(`${FIN}/immeubles/${immeuble.id}/baux-paralleles?inclure_termines=${inclureTermines}`);
    if (!r.ok) {
      setErr(await lireErreur(r));
      return;
    }
    setErr(null);
    setItems(((await r.json()) as { items: BailParallele[] }).items);
  }, [immeuble.id, inclureTermines]);

  useEffect(() => {
    void load();
  }, [load]);

  async function rafraichir() {
    await load();
    if (onChanged) await onChanged();
  }

  async function terminer(b: BailParallele) {
    if (!window.confirm(`Mettre fin au bail parallèle de ${b.locataire_nom || "cet occupant"} (logement ${b.logement_numero}) ?`)) return;
    const r = await authedFetch(`${FIN}/baux-paralleles/${b.id}`, { method: "PATCH", body: JSON.stringify({ statut: "termine" }) });
    if (!r.ok) {
      setErr(await lireErreur(r));
      return;
    }
    await rafraichir();
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2 rounded-xl border border-violet-500/30 bg-violet-500/5 px-3 py-2 text-xs text-violet-100">
        <span>
          <b>Baux parallèles</b> : contrats réels gérés par un tiers (sous-location, bail principal d&apos;un exploitant) — occupant réel, locateur du bail, loyer tel qu&apos;au contrat. Enregistre le contrat, importe le PDF signé fourni par l&apos;exploitant ; le bail officiel TAL sert seulement à un nouveau contrat à faire signer.
        </span>
        <label className="ml-auto flex items-center gap-1.5 text-white/70">
          <input type="checkbox" checked={inclureTermines} onChange={(e) => setInclureTermines(e.target.checked)} /> voir les terminés
        </label>
        <button type="button" onClick={() => setShowCreate(true)} className="btn-accent btn-sm">
          <Plus className="h-3.5 w-3.5" /> Enregistrer un bail parallèle
        </button>
      </div>
      {err ? <p className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">{err}</p> : null}
      {items == null ? (
        <p className="flex items-center gap-2 py-6 text-xs text-white/50">
          <Loader2 className="h-4 w-4 animate-spin" /> Chargement…
        </p>
      ) : items.length === 0 ? (
        <p className="rounded-xl border border-brand-800 bg-brand-900/60 px-4 py-8 text-center text-sm text-white/50">Aucun bail parallèle pour cet immeuble.</p>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-brand-800 bg-brand-900">
          <table className="w-full text-xs">
            <thead className="bg-brand-950/60 text-[11px] uppercase tracking-wider text-white/50">
              <tr>
                <th className="px-3 py-2 text-left">Unité</th>
                <th className="px-3 py-2 text-left">Occupant</th>
                <th className="px-3 py-2 text-left">Locateur du bail</th>
                <th className="px-3 py-2 text-left">Type</th>
                <th className="px-3 py-2 text-right">Loyer</th>
                <th className="px-3 py-2 text-left">Période</th>
                <th className="px-3 py-2 text-left">Statut</th>
                <th className="px-3 py-2 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-brand-800">
              {items.map((b) => (
                <tr key={b.id}>
                  <td className="px-3 py-2 font-semibold text-white">{b.logement_numero}</td>
                  <td className="px-3 py-2 text-white/85">
                    {b.locataire_nom || "—"}
                    {b.locataire_email ? <div className="text-[11px] text-white/40">{b.locataire_email}</div> : null}
                  </td>
                  <td className="px-3 py-2 text-white/70">
                    {b.parallele_locateur || b.locateur_effectif || "Propriétaire"}
                    {b.parallele_locateur_courriel ? <div className="text-[11px] text-white/40">{b.parallele_locateur_courriel}</div> : null}
                  </td>
                  <td className="px-3 py-2 text-white/60">{b.type_label}</td>
                  <td className="px-3 py-2 text-right font-mono text-white/85">{money(b.loyer_mensuel)}</td>
                  <td className="px-3 py-2 text-white/60">
                    {fmtDate(b.date_debut)} → {b.au_mois ? "au mois" : fmtDate(b.date_fin)}
                  </td>
                  <td className="px-3 py-2">
                    <span className={`badge ${b.en_vigueur ? (b.echu ? "badge-amber" : "badge-emerald") : b.status === "propose" ? "badge-violet" : "badge-neutral"}`}>
                      {b.en_vigueur ? (b.echu ? "échu" : "en vigueur") : b.status === "propose" ? "en signature" : b.status}
                    </span>
                    {b.document_id ? (
                      <button type="button" onClick={() => void ouvrirPdfDocument(b.document_id as number).catch((e) => setErr((e as Error).message))} className="badge badge-emerald ml-1 hover:underline">
                        PDF signé
                      </button>
                    ) : (
                      <span className="badge badge-neutral ml-1">pas de PDF</span>
                    )}
                  </td>
                  <td className="px-3 py-2">
                    <div className="flex flex-wrap justify-end gap-1">
                      <button type="button" onClick={() => setEdit(b)} className="btn-ghost btn-xs">
                        <Pencil className="h-3 w-3" /> Modifier
                      </button>
                      <button type="button" onClick={() => setImportFor(b)} className="btn-ghost btn-xs" title="Importer le PDF du bail signé (devient le bail au dossier)">
                        <Upload className="h-3 w-3" /> PDF signé
                      </button>
                      <TalFormDropdown bailId={b.id} />
                      <button type="button" onClick={() => setTalFor(b)} className="btn-outline-accent btn-xs" title="Nouveau contrat réel à faire signer : bail officiel TAL + eSign">
                        <FileSignature className="h-3 w-3" /> Bail TAL
                      </button>
                      {b.status !== "termine" && b.status !== "resilie" ? (
                        <button type="button" onClick={() => void terminer(b)} className="text-rose-300/60 hover:text-rose-300" title="Mettre fin">
                          <X className="h-3.5 w-3.5" />
                        </button>
                      ) : null}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {showCreate ? (
        <BailParalleleModal
          immeuble={immeuble}
          onClose={() => setShowCreate(false)}
          onSaved={() => {
            setShowCreate(false);
            void rafraichir();
          }}
        />
      ) : null}
      {edit ? (
        <BailParalleleModal
          immeuble={immeuble}
          existant={edit}
          onClose={() => setEdit(null)}
          onSaved={() => {
            setEdit(null);
            void rafraichir();
          }}
        />
      ) : null}
      {talFor ? (
        <TalBailModal
          bailId={talFor.id}
          titre={`Logement ${talFor.logement_numero} · ${immeuble.name} · ${talFor.locataire_nom || ""} (bail parallèle)`}
          onClose={() => setTalFor(null)}
          onDone={() => void rafraichir()}
        />
      ) : null}
      {importFor ? (
        <ImportPdfSigneModal
          bail={importFor}
          onClose={() => setImportFor(null)}
          onDone={() => {
            setImportFor(null);
            void rafraichir();
          }}
        />
      ) : null}
    </div>
  );
}

function BailParalleleModal({ immeuble, existant, prefill, onClose, onSaved }: { immeuble: ImmeubleLite; existant?: BailParallele; prefill?: { logement_id: number; loyer_mensuel: number | null }; onClose: () => void; onSaved: () => void }) {
  const [logements, setLogements] = useState<LogementLite[]>([]);
  const [locataires, setLocataires] = useState<{ id: number; full_name: string; email: string | null }[]>([]);
  const [modeOccupant, setModeOccupant] = useState<"nouveau" | "existant">("nouveau");
  const [f, setF] = useState({
    logement_id: existant ? String(existant.logement_id) : prefill ? String(prefill.logement_id) : "",
    locataire_id: "",
    full_name: "",
    email: "",
    phone: "",
    parallele_type: existant?.parallele_type || "sous_location",
    parallele_locateur: existant?.parallele_locateur || "",
    parallele_locateur_courriel: existant?.parallele_locateur_courriel || "",
    parallele_locateur_telephone: existant?.parallele_locateur_telephone || "",
    parallele_note: existant?.parallele_note || "",
    date_debut: existant?.date_debut || "",
    date_fin: existant?.date_fin || "",
    loyer_mensuel: existant ? String(existant.loyer_mensuel) : prefill?.loyer_mensuel != null ? String(prefill.loyer_mensuel) : "",
    depot_garantie: existant?.depot_garantie != null ? String(existant.depot_garantie) : "",
    chauffage_inclus: existant?.chauffage_inclus || false,
    eau_chaude_inclus: existant?.eau_chaude_inclus || false,
    electricite_inclus: existant?.electricite_inclus || false,
    internet_inclus: existant?.internet_inclus || false,
    au_mois: existant?.au_mois || false,
    jour_echeance: existant ? String(existant.jour_echeance) : "1",
    statut: existant?.status || "parallele",
    notes: existant?.notes || ""
  });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    void (async () => {
      const r = await authedFetch(`/api/v1/immobilier/immeubles/${immeuble.id}/logements`);
      if (r.ok) setLogements((await r.json()) as LogementLite[]);
      const rl = await authedFetch("/api/v1/immobilier/locataires");
      if (rl.ok) setLocataires((await rl.json()) as { id: number; full_name: string; email: string | null }[]);
    })();
  }, [immeuble.id]);

  async function submit() {
    setBusy(true);
    setErr(null);
    try {
      const commun = {
        parallele_type: f.parallele_type,
        parallele_locateur: f.parallele_locateur.trim(),
        parallele_locateur_courriel: f.parallele_locateur_courriel.trim() || null,
        parallele_locateur_telephone: f.parallele_locateur_telephone.trim() || null,
        parallele_note: f.parallele_note.trim() || null,
        date_debut: f.date_debut,
        date_fin: f.date_fin,
        loyer_mensuel: Number(f.loyer_mensuel.replace(",", ".")),
        depot_garantie: f.depot_garantie.trim() ? Number(f.depot_garantie.replace(",", ".")) : null,
        chauffage_inclus: f.chauffage_inclus,
        eau_chaude_inclus: f.eau_chaude_inclus,
        electricite_inclus: f.electricite_inclus,
        internet_inclus: f.internet_inclus,
        au_mois: f.au_mois,
        jour_echeance: Number(f.jour_echeance) || 1,
        notes: f.notes.trim() || null
      };
      let r: Response;
      if (existant) {
        r = await authedFetch(`${FIN}/baux-paralleles/${existant.id}`, { method: "PATCH", body: JSON.stringify({ ...commun, statut: f.statut }) });
      } else {
        if (!f.logement_id) throw new Error("Choisis le logement.");
        if (modeOccupant === "existant" && !f.locataire_id) throw new Error("Choisis l'occupant existant.");
        if (modeOccupant === "nouveau" && f.full_name.trim().length < 2) throw new Error("Nom de l'occupant requis.");
        const occupant = modeOccupant === "existant" ? { locataire_id: Number(f.locataire_id) } : { locataire: { full_name: f.full_name.trim(), email: f.email.trim() || null, phone: f.phone.trim() || null } };
        r = await authedFetch(`${FIN}/baux-paralleles`, { method: "POST", body: JSON.stringify({ logement_id: Number(f.logement_id), ...occupant, ...commun, statut: f.statut }) });
      }
      if (!r.ok) throw new Error(await lireErreur(r));
      onSaved();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal titre={existant ? `Modifier le bail parallèle — logement ${existant.logement_numero}` : `Enregistrer un bail parallèle — ${immeuble.name}`} onClose={onClose} large>
      <p className="rounded-lg border border-brand-800 bg-brand-900/60 px-3 py-2 text-[11px] text-white/55">
        Ce qui est inscrit ici est ce que le contrat dit : occupant réel, locateur du bail, loyer tel qu&apos;au contrat. Le rent roll le reprendra tel quel.
      </p>
      <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {!existant ? (
          <label className="text-[11px] font-semibold text-white/60">
            Logement
            <select value={f.logement_id} onChange={(e) => setF({ ...f, logement_id: e.target.value })} className={`${INPUT} mt-0.5 block w-full`}>
              <option value="">Choisir…</option>
              {logements.map((l) => (
                <option key={l.id} value={l.id}>
                  {l.numero}
                </option>
              ))}
            </select>
          </label>
        ) : null}
        <label className="text-[11px] font-semibold text-white/60">
          Type de bail parallèle
          <select value={f.parallele_type} onChange={(e) => setF({ ...f, parallele_type: e.target.value })} className={`${INPUT} mt-0.5 block w-full`}>
            {PARALLELE_TYPES.map(([v, l]) => (
              <option key={v} value={v}>
                {l}
              </option>
            ))}
          </select>
        </label>
        <label className="text-[11px] font-semibold text-white/60">
          Statut
          <select value={f.statut} onChange={(e) => setF({ ...f, statut: e.target.value })} className={`${INPUT} mt-0.5 block w-full`}>
            <option value="parallele">En vigueur (contrat déjà signé)</option>
            <option value="propose">Nouveau contrat à faire signer</option>
            {existant ? <option value="termine">Terminé</option> : null}
            {existant ? <option value="resilie">Résilié</option> : null}
          </select>
        </label>
      </div>

      {!existant ? (
        <div className="mt-3 rounded-lg border border-brand-800 p-3">
          <div className="flex flex-wrap items-center gap-3 text-xs">
            <span className="font-semibold text-white/70">Occupant :</span>
            <label className="flex items-center gap-1.5 text-white/85">
              <input type="radio" checked={modeOccupant === "nouveau"} onChange={() => setModeOccupant("nouveau")} /> nouvelle personne (hors des listes du quotidien)
            </label>
            <label className="flex items-center gap-1.5 text-white/85">
              <input type="radio" checked={modeOccupant === "existant"} onChange={() => setModeOccupant("existant")} /> locataire déjà dans Kratos
            </label>
          </div>
          {modeOccupant === "nouveau" ? (
            <div className="mt-2 grid gap-3 sm:grid-cols-3">
              <Champ label="Nom complet" value={f.full_name} onChange={(v) => setF({ ...f, full_name: v })} />
              <Champ label="Courriel" value={f.email} onChange={(v) => setF({ ...f, email: v })} type="email" />
              <Champ label="Téléphone" value={f.phone} onChange={(v) => setF({ ...f, phone: v })} inputMode="tel" />
            </div>
          ) : (
            <label className="mt-2 block text-[11px] font-semibold text-white/60">
              Locataire
              <select value={f.locataire_id} onChange={(e) => setF({ ...f, locataire_id: e.target.value })} className={`${INPUT} mt-0.5 block w-full`}>
                <option value="">Choisir…</option>
                {locataires.map((l) => (
                  <option key={l.id} value={l.id}>
                    {l.full_name}
                    {l.email ? ` · ${l.email}` : ""}
                  </option>
                ))}
              </select>
            </label>
          )}
        </div>
      ) : null}

      <div className="mt-3 grid gap-3 sm:grid-cols-3">
        <Champ label="Locateur du bail (vide = le propriétaire)" value={f.parallele_locateur} onChange={(v) => setF({ ...f, parallele_locateur: v })} />
        <Champ label="Courriel du locateur" value={f.parallele_locateur_courriel} onChange={(v) => setF({ ...f, parallele_locateur_courriel: v })} type="email" />
        <Champ label="Téléphone du locateur" value={f.parallele_locateur_telephone} onChange={(v) => setF({ ...f, parallele_locateur_telephone: v })} inputMode="tel" />
        {f.parallele_type === "bail_principal" && !f.parallele_locateur.trim() ? (
          <p className="text-xs text-white/50 sm:col-span-3">
            Bail principal avec le propriétaire comme locateur : le locataire loue toute l&apos;unité et sous-loue les chambres. Une fois en vigueur, il devient LE bail de l&apos;unité dans le rent roll ; les baux de chambre y figurent dessous comme ses sous-locations, hors des totaux.
          </p>
        ) : null}
        <Champ label="Début" value={f.date_debut} onChange={(v) => setF({ ...f, date_debut: v })} type="date" />
        <Champ label="Fin" value={f.date_fin} onChange={(v) => setF({ ...f, date_fin: v })} type="date" />
        <Champ label="Loyer mensuel au contrat ($)" value={f.loyer_mensuel} onChange={(v) => setF({ ...f, loyer_mensuel: v })} inputMode="decimal" />
        <Champ label="Dépôt ($)" value={f.depot_garantie} onChange={(v) => setF({ ...f, depot_garantie: v })} inputMode="decimal" />
        <Champ label="Payable le (jour)" value={f.jour_echeance} onChange={(v) => setF({ ...f, jour_echeance: v })} inputMode="numeric" />
        <div className="text-[11px] font-semibold text-white/60">
          Inclusions
          <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-xs font-normal text-white/80">
            {(
              [
                ["chauffage_inclus", "chauffage"],
                ["eau_chaude_inclus", "eau chaude"],
                ["electricite_inclus", "électricité"],
                ["internet_inclus", "internet"],
                ["au_mois", "au mois"]
              ] as const
            ).map(([k, l]) => (
              <label key={k} className="flex items-center gap-1">
                <input type="checkbox" checked={f[k]} onChange={(e) => setF({ ...f, [k]: e.target.checked })} /> {l}
              </label>
            ))}
          </div>
        </div>
        <label className="text-[11px] font-semibold text-white/60 sm:col-span-3">
          Note (contexte du bail parallèle)
          <textarea rows={2} value={f.parallele_note} onChange={(e) => setF({ ...f, parallele_note: e.target.value })} className={`${INPUT} mt-0.5 block w-full`} />
        </label>
      </div>
      {err ? <p className="mt-3 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">{err}</p> : null}
      <div className="mt-4 flex justify-end gap-2 border-t border-brand-800 pt-3">
        <button type="button" onClick={onClose} className="btn-secondary btn-sm">
          Annuler
        </button>
        <button type="button" disabled={busy} onClick={() => void submit()} className="btn-accent btn-sm disabled:opacity-60">
          {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Check className="h-4 w-4" />} {existant ? "Enregistrer" : "Enregistrer le bail parallèle"}
        </button>
      </div>
    </Modal>
  );
}

function ImportPdfSigneModal({ bail, onClose, onDone }: { bail: BailParallele; onClose: () => void; onDone: () => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function importer() {
    if (!file) return;
    setBusy(true);
    setErr(null);
    try {
      const fd = new FormData();
      fd.append("file", file);
      const r = await authedFetch(`/api/v1/immobilier/baux/${bail.id}/document`, { method: "POST", body: fd });
      if (!r.ok) throw new Error(await lireErreur(r));
      onDone();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal titre={`PDF du bail parallèle signé — logement ${bail.logement_numero}`} onClose={onClose} zIndex="z-[70]">
      <p className="text-xs text-white/60">Le PDF fourni par le locateur du bail devient le bail au dossier de ce bail parallèle ; s&apos;il était « à faire signer », il passe « en vigueur ».</p>
      <input type="file" accept="application/pdf,image/*" onChange={(e) => setFile(e.target.files?.[0] || null)} className="mt-3 block w-full text-xs text-white/80" />
      {err ? <p className="mt-3 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">{err}</p> : null}
      <div className="mt-4 flex justify-end gap-2 border-t border-brand-800 pt-3">
        <button type="button" onClick={onClose} className="btn-secondary btn-sm">
          Annuler
        </button>
        <button type="button" disabled={busy || !file} onClick={() => void importer()} className="btn-accent btn-sm disabled:opacity-60">
          {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Upload className="h-4 w-4" />} Importer
        </button>
      </div>
    </Modal>
  );
}

// ─── Briques UI ───────────────────────────────────────────────────────

function Modal({ titre, onClose, children, large = false, zIndex = "z-[60]" }: { titre: string; onClose: () => void; children: React.ReactNode; large?: boolean; zIndex?: string }) {
  return (
    <div className={`fixed inset-0 ${zIndex} flex items-start justify-center overflow-y-auto bg-black/70 p-4 backdrop-blur-sm`} onClick={onClose}>
      <div className={`my-6 w-full ${large ? "max-w-5xl" : "max-w-2xl"} rounded-2xl border border-brand-800 bg-brand-950 shadow-2xl`} onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between gap-2 border-b border-brand-800 px-5 py-3">
          <h2 className="truncate text-sm font-bold uppercase tracking-wider text-accent-500">{titre}</h2>
          <button type="button" onClick={onClose} className="btn-ghost btn-xs">
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="p-5">{children}</div>
      </div>
    </div>
  );
}

function Champ({ label, value, onChange, type = "text", inputMode }: { label: string; value: string; onChange: (v: string) => void; type?: string; inputMode?: "decimal" | "numeric" | "tel" }) {
  return (
    <label className="text-[11px] font-semibold text-white/60">
      {label}
      <input type={type} inputMode={inputMode} value={value} onChange={(e) => onChange(e.target.value)} className={`${INPUT} mt-0.5 block w-full`} />
    </label>
  );
}

function ChampBlur({ label, value, onSave, type = "text", inputMode }: { label: string; value: string; onSave: (v: string) => void; type?: string; inputMode?: "decimal" | "numeric" }) {
  const [v, setV] = useState(value);
  useEffect(() => setV(value), [value]);
  return (
    <label className="text-[11px] font-semibold text-white/60">
      {label}
      <input type={type} inputMode={inputMode} value={v} onChange={(e) => setV(e.target.value)} onBlur={() => (v !== value ? onSave(v) : undefined)} className={`${INPUT} mt-0.5 block w-full`} />
    </label>
  );
}

function Tuile({ label, valeur, sous, accent = false, alerte = false }: { label: string; valeur: string; sous?: string; accent?: boolean; alerte?: boolean }) {
  return (
    <div className={`rounded-lg border px-3 py-2 ${alerte ? "border-amber-500/40 bg-amber-500/5" : accent ? "border-sky-500/30 bg-sky-500/5" : "border-brand-800 bg-brand-900"}`}>
      <p className="text-[10px] uppercase tracking-wider text-white/45">{label}</p>
      <p className="text-base font-bold text-white">{valeur}</p>
      {sous ? <p className="text-[10px] text-white/45">{sous}</p> : null}
    </div>
  );
}
