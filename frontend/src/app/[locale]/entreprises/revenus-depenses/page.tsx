"use client";

/**
 * Gestion d'entreprise → Revenus et dépenses (2026-11-04) — mode SIMULATION,
 * aligné sur « Le Fonds MGV d'investissements » (document de travail,
 * novembre 2026).
 *
 * La page modélise la SOCIÉTÉ DE GESTION (ce que vous gagnez en gérant le
 * fonds et son parc), pas les loyers du fonds.
 *
 * v3 (retours Phil 2026-11-04) :
 * - les immeubles sont des FICHES (plus un tableau étroit) : loyers et portes,
 *   statut (en rénovation / stabilisé) avec les champs du document, dette ;
 *   « dans le fonds » et « gestion à l'interne » expliqués ;
 * - la valeur du parc, les dettes, l'équité et la VAN se CALCULENT depuis
 *   les fiches (rénovation = coût du projet + plus-value linéaire ; stabilisé
 *   = rapport ou revenus nets ÷ taux de cap) ; seul le cash se saisit ;
 * - import des immeubles déjà dans Kratos (logements, chambres, loyers des
 *   baux actifs, gestion externe, dette, dernier rapport) ;
 * - frais de développement par TRANCHES comme l'impôt (barème du doc) ;
 * - sous-traitant de gestion en dépense (% des loyers des immeubles non
 *   gérés à l'interne) ; part des gains (en parts) calculée à part.
 *
 * Un scénario = un jeu d'hypothèses enregistré ; tout se recalcule côté
 * serveur (moteur unique, réutilisé plus tard par le mode réel branché sur
 * Kratos et QuickBooks). Réservé aux admins.
 */

import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import {
  AlertTriangle,
  Building2,
  Calculator,
  Check,
  ChevronDown,
  ChevronRight,
  Copy,
  Database,
  HardHat,
  Home,
  KeyRound,
  Landmark,
  Loader2,
  Lock,
  Pencil,
  PiggyBank,
  Plus,
  Receipt,
  RefreshCw,
  RotateCcw,
  Search,
  Sparkles,
  TrendingUp,
  Trash2,
  Users,
  Wallet,
  Wrench,
  X
} from "lucide-react";

import { authedFetch } from "@/lib/auth";
import { useCurrentUser } from "@/hooks/use-current-user";
import { QGTopbar } from "../layout";
import { PerformanceTab } from "./PerformanceTab";

const RD = "/api/v1/entreprises/revenus-depenses";

// ─── Types ───────────────────────────────────────────────────────────────

type Palier = { jusqua: number | null; pct: number };
type Immeuble = {
  id: string;
  nom: string;
  kratos_immeuble_id: number | null;
  dans_le_fonds: boolean;
  gestion_interne: boolean;
  nb_logements: number;
  nb_logements_en_chambres: number;
  nb_chambres: number;
  frais_developpement_override: number | null;
  loyers_bruts_mensuels: number;
  phase: "stabilisation" | "stabilise";
  acquisition_cette_annee: boolean;
  prix_acquisition: number;
  prospecte_par_nous: boolean;
  travaux_initiaux: number;
  frais_connexes: number;
  valeur_future: number;
  mois_prevus: number;
  mois_ecoules: number;
  valeur_rapport: number;
  annee_rapport: number | null;
  taux_cap_pct: number;
  revenus_nets_annuels: number;
  dette: number;
  date_acquisition: string | null;
  notes_import: string[];
  taxes_municipales: number;
  taxes_scolaires: number;
  assurances: number;
  energie: number;
  autres_depenses: number;
  suivre_kratos: boolean;
  notes_ignorees: string[];
  // Projection (onglet Performance du fonds, 2026-11-06).
  loyers_stabilises_mensuels: number;
  taux_dette_pct: number;
  amortissement_ans: number;
  interet_seulement: boolean;
};
type LigneRefact = { id: string; libelle: string; montant_annuel: number };
type FraisFixe = { id: string; categorie: string; libelle: string; montant: number; periode: "mois" | "an" };
type Salaire = { id: string; poste: string; salaire_annuel: number };
type Associe = { id: string; nom: string; salaire_annuel: number; dividendes_annuels: number };
type Data = {
  annee: number;
  fonds: { cash: number; taux_pct: number };
  developpement: { paliers: Palier[] };
  prospection: { taux_pct: number };
  immeubles: Immeuble[];
  refacturation: { marge_pct: number; par_logement_annuel: number; par_immeuble_annuel: number; lignes: LigneRefact[] };
  construction: { marge_pct: number; pct_logements_renoves_par_an: number; cout_reno_logement: number };
  maintenance: { heures_par_logement: number; materiaux_par_logement: number; heures_par_an: number; cout_horaire: number; taux_facture: number; materiaux_annuels: number; marge_materiaux_pct: number };
  gestion: { taux_pct: number; facturer_sous_traites: boolean; loyers_additionnels_mensuels: number; inclure_projection: boolean };
  location: { frais_logement: number; frais_chambre: number; taux_roulement_pct: number; taux_roulement_chambres_pct: number; nb_relocations_logements: number | null; nb_relocations_chambres: number | null };
  part_des_gains: { rendement_pct: number; seuil_investisseurs_pct: number; tranche_nous_pct: number; part_nous_pct: number };
  projection: { croissance_loyers_pct: number; croissance_depenses_pct: number; horizon_annees: number; taux_cap_sortie_pct: number; taux_renouvellement_pct: number; taux_dette_defaut_pct: number; amortissement_defaut_ans: number; prix_part_depart: number; part_nos_holdings_depart_pct: number };
  depenses: { frais_fixes: FraisFixe[]; charges_sociales_pct: number; salaires: Salaire[]; associes: Associe[]; sous_traitance_gestion_pct: number; agents_location: { par_logement: number; par_chambre: number }; impots: { taux_pct: number; plafond: number; taux_au_dela_pct: number } };
};
type SectionRevenu = { key: string; label: string; revenu: number; part_pct: number; [k: string]: unknown };
type LigneDev = { id: string; immeuble: string; prix: number; frais: number; frais_calcule: number; taux_effectif_pct: number; override: boolean };
type DepensesSchl = { revenus_bruts_annuels: number; inoccupation: number; taxes_municipales: number; taxes_scolaires: number; assurances: number; energie: number; concierge: number; entretien: number; gestion: number; autres_normalisations: number; total: number; revenus_nets: number };
const LIGNES_SCHL: [string, keyof DepensesSchl][] = [
  ["Inoccupation", "inoccupation"],
  ["Taxes municipales", "taxes_municipales"],
  ["Taxes scolaires", "taxes_scolaires"],
  ["Assurances", "assurances"],
  ["Énergie", "energie"],
  ["Conciergerie (barème)", "concierge"],
  ["Entretien (barème)", "entretien"],
  ["Gestion (barème)", "gestion"],
  ["Autres normalisations (barème)", "autres_normalisations"]
];
type FicheImmeuble = { id: string; nom: string; dans_le_fonds: boolean; phase: string; cout_projet: number; valeur: number; valeur_a_terme: number; plus_value_prevue: number; methode: string; dette: number; equite: number; part_annee: number; jours: number; jours_annee: number; date_acquisition: string | null; acquise_cette_annee: boolean; notes_import: string[]; suivre_kratos: boolean; nb_logements: number; nb_logements_en_chambres: number; nb_chambres: number; revenus_nets: number | null; source_revenus_nets: "schl" | "saisis" | null; depenses_schl: DepensesSchl | null };
type Resultats = {
  parc: { immeubles: FicheImmeuble[]; valeur: number; dettes: number; equite: number; cash: number; van: number; van_ponderee: number; valeur_a_terme: number; van_a_terme: number; nb_dans_le_fonds: number; nb_hors_fonds: number; nb_en_renovation: number; annee: number; nb_prorates: number; bareme_schl: { taux_inoccupation: number; seuil_log: number; concierge_lt12: number; concierge_gte12: number; entretien: number; gestion_lt12: number; gestion_gte12: number; autres_normalisations_pct: number } };
  revenus: SectionRevenu[];
  part_des_gains: { van: number; rendement_pct: number; gain: number; tranche_investisseurs: number; tranche_nous: number; reste: number; part_nous: number; part_investisseurs: number; par_holding: number; nb_holdings: number; pct_du_gain_nous: number };
  depenses: {
    frais_fixes_par_categorie: { categorie: string; label: string; montant: number }[];
    total_frais_fixes: number;
    salaires: { poste: string; brut: number; charges: number; total: number }[];
    total_salaires_bruts: number;
    total_charges_sociales: number;
    associes: { nom: string; salaire_brut: number; charges: number; cout_salaire: number; dividendes: number }[];
    total_associes_salaires: number;
    total_masse_salariale: number;
    sous_traitance_gestion: number;
    agents_location: number;
    relocations_logements: number;
    relocations_chambres: number;
    loyers_sous_traites_annuels: number;
    total_dividendes: number;
    total: number;
    impots: { taux_pct: number; plafond: number; taux_au_dela_pct: number; base: number; tranche_1_base: number; tranche_1: number; tranche_2_base: number; tranche_2: number; total: number; taux_effectif_pct: number };
    charges_sociales_pct: number;
  };
  totaux: { revenus: number; revenus_avec_projection: number; depenses: number; benefice: number; benefice_avant_associes: number; salaires_associes_charges_incluses: number; marge_pct: number | null; impots: number; benefice_apres_impots: number; marge_apres_impots_pct: number | null; dividendes: number; benefice_retenu: number; revenus_mensuels: number; depenses_mensuelles: number };
  point_mort: { couvert: boolean; van_necessaire: number; van_actuelle: number; loyers_mensuels_sous_gestion_necessaires: number; loyers_mensuels_sous_gestion_actuels: number };
  avertissements: string[];
};
type Referentiel = { categories_frais_fixes: { key: string; label: string }[]; charges_sociales_note: string; valorisation_note: string; prorata_note: string; schl_note: string; projection_note?: string; impots_note?: string };
type ScenarioResume = { id: number; nom: string; is_default: boolean; updated_at: string | null; resume: Record<string, number | null> };
type Detail = ScenarioResume & { data: Data; resultats: Resultats; referentiel: Referentiel };
type ImmeubleKratos = { kratos_immeuble_id: number; nom: string; adresse: string | null; ville: string | null; nb_logements: number; nb_logements_en_chambres: number; nb_chambres: number; loyers_bruts_mensuels: number; gestion_externe: boolean; dette: number; valeur_rapport: number; annee_rapport: number | null; source_rapport: string | null; taux_cap_pct: number; notes_import: string[]; taxes_municipales: number; taxes_scolaires: number; assurances: number; energie: number; autres_depenses: number };

// ─── Couleurs ────────────────────────────────────────────────────────────

const C: Record<string, string> = {
  fonds: "#8b5cf6",
  developpement: "#6366f1",
  prospection: "#0ea5e9",
  refacturation: "#14b8a6",
  construction: "#f59e0b",
  maintenance: "#f97316",
  gestion: "#10b981",
  gestion_projection: "#84cc16",
  location: "#ec4899",
  part_des_gains: "#a855f7",
  immeubles: "#38bdf8",
  frais_fixes: "#64748b",
  salaires: "#f43f5e",
  associes: "#d946ef",
  sous_traitance: "#fb7185",
  dividendes: "#c084fc",
  impots: "#fb923c",
  revenus: "#10b981",
  depenses: "#f43f5e",
  benefice: "#8b5cf6",
  retenu: "#0ea5e9"
};
const CAT_COULEURS: Record<string, string> = {
  abonnements: "#60a5fa",
  activites: "#38bdf8",
  representation: "#2dd4bf",
  honoraires: "#a78bfa",
  fournitures: "#fbbf24",
  deplacements: "#fb923c",
  informatique: "#34d399",
  autre: "#94a3b8"
};
const ICONES: Record<string, React.ComponentType<{ className?: string }>> = {
  fonds: Landmark,
  developpement: TrendingUp,
  prospection: Search,
  refacturation: Receipt,
  construction: HardHat,
  maintenance: Wrench,
  gestion: Home,
  gestion_projection: TrendingUp,
  location: KeyRound
};

// ─── Outils ──────────────────────────────────────────────────────────────

const INPUT =
  "rounded-lg border border-[var(--qg-border)] bg-[var(--qg-bg)] px-2.5 py-1.5 text-sm outline-none transition focus:border-[var(--qg-accent)] disabled:cursor-default disabled:border-dashed disabled:opacity-75";
const CARD = "rounded-2xl border border-[var(--qg-border)] bg-[var(--qg-card-bg)]";
const MUTED = "text-[var(--qg-text-muted)]";
const FAINT = "text-[var(--qg-text-faint)]";

function money(n: number | null | undefined, decimals = 0): string {
  return new Intl.NumberFormat("fr-CA", { style: "currency", currency: "CAD", maximumFractionDigits: decimals }).format(n || 0);
}
function pct(n: number | null | undefined, d = 1): string {
  return n == null ? "—" : `${new Intl.NumberFormat("fr-CA", { maximumFractionDigits: d }).format(n)} %`;
}
function nb(n: number | null | undefined, d = 1): string {
  return new Intl.NumberFormat("fr-CA", { maximumFractionDigits: d }).format(n || 0);
}
function uid(): string {
  return Math.random().toString(36).slice(2, 10);
}
function clone<T>(v: T): T {
  return JSON.parse(JSON.stringify(v)) as T;
}
function teinte(hex: string, alpha = "22"): string {
  return `${hex}${alpha}`;
}
function fmtDateFr(iso: string | null | undefined): string {
  if (!iso) return "";
  const [y, m, d] = iso.split("-").map(Number);
  if (!y || !m || !d) return iso;
  return new Date(y, m - 1, d).toLocaleDateString("fr-CA", { day: "numeric", month: "long", year: "numeric" });
}
function immeubleVide(extra: Partial<Immeuble> = {}): Immeuble {
  return {
    id: uid(), nom: "", kratos_immeuble_id: null, dans_le_fonds: true, gestion_interne: true,
    nb_logements: 0, nb_logements_en_chambres: 0, nb_chambres: 0, loyers_bruts_mensuels: 0, phase: "stabilise",
    acquisition_cette_annee: false, prix_acquisition: 0, prospecte_par_nous: true,
    travaux_initiaux: 0, frais_connexes: 0, valeur_future: 0, mois_prevus: 24, mois_ecoules: 0,
    valeur_rapport: 0, annee_rapport: null, taux_cap_pct: 0, revenus_nets_annuels: 0, dette: 0,
    date_acquisition: null, notes_import: [],
    taxes_municipales: 0, taxes_scolaires: 0, assurances: 0, energie: 0, autres_depenses: 0,
    suivre_kratos: false, notes_ignorees: [], frais_developpement_override: null,
    loyers_stabilises_mensuels: 0, taux_dette_pct: 0, amortissement_ans: 0, interet_seulement: false,
    ...extra
  };
}

// Lecture seule par défaut : chaque section et chaque fiche se déverrouille avec « Modifier »
// (Phil 2026-11-04 : « c'est trop facile en ce moment de modifier des infos »).
type Edition = { actif: (k: string) => boolean; basculer: (k: string) => void; toutVerrouiller: () => void; nb: number };
const EditionCtx = createContext<Edition>({ actif: () => true, basculer: () => {}, toutVerrouiller: () => {}, nb: 0 });

// Vrai à l'intérieur d'une section verrouillée : les champs numériques s'affichent en montants lisibles.
const VerrouCtx = createContext<boolean>(false);

function fmtVal(v: number, suffixe?: string): string {
  const dec = Number.isInteger(v) ? 0 : 2;
  if (!suffixe) return nb(v, dec);
  if (suffixe === "$") return money(v, dec);
  if (suffixe.startsWith("$/")) return `${money(v, dec)}/${suffixe.slice(2)}`;
  return `${nb(v, dec)} ${suffixe}`;
}

function BoutonModifier({ k, className = "" }: { k: string; className?: string }) {
  const ed = useContext(EditionCtx);
  const actif = ed.actif(k);
  return (
    <button type="button" className={`btn-secondary btn-sm ${className}`} onClick={() => ed.basculer(k)} title={actif ? "Terminer et reverrouiller" : "Déverrouiller pour modifier"}>
      {actif ? <Check className="h-3.5 w-3.5" /> : <Pencil className="h-3.5 w-3.5" />} {actif ? "Terminé" : "Modifier"}
    </button>
  );
}

function Verrou({ k, children, className = "" }: { k: string; children: React.ReactNode; className?: string }) {
  const ed = useContext(EditionCtx);
  return (
    <fieldset disabled={!ed.actif(k)} className={`m-0 min-w-0 border-0 p-0 ${className}`}>
      <VerrouCtx.Provider value={!ed.actif(k)}>{children}</VerrouCtx.Provider>
    </fieldset>
  );
}

function Num({ value, onChange, className = "", placeholder, title, step, suffixe, verrouille }: { value: number | null | undefined; onChange: (v: number) => void; className?: string; placeholder?: string; title?: string; step?: number; suffixe?: string; verrouille?: boolean }) {
  const verrouSection = useContext(VerrouCtx);
  if (verrouSection) {
    const v = value == null || Number.isNaN(value) ? 0 : value;
    return <span className={`${INPUT} inline-flex w-full min-w-[110px] cursor-default items-center justify-end border-dashed opacity-80 tabular-nums ${className}`} title={title}>{fmtVal(v, suffixe)}</span>;
  }
  return (
    <span className="relative inline-flex w-full items-center">
      <input
        type="number"
        inputMode="decimal"
        min={0}
        step={step ?? "any"}
        value={value == null || Number.isNaN(value) ? "" : value}
        placeholder={placeholder}
        title={verrouille ? "Valeur reprise de Kratos — clique sur Modifier (crayon) pour l'ajuster" : title}
        readOnly={verrouille}
        tabIndex={verrouille ? -1 : undefined}
        onChange={(e) => { if (!verrouille) onChange(e.target.value === "" ? 0 : Number(e.target.value)); }}
        className={`${INPUT} w-full min-w-[110px] text-right tabular-nums ${suffixe ? "pr-9" : ""} ${verrouille ? "cursor-default border-dashed opacity-75" : ""} ${className}`}
      />
      {suffixe ? <span className={`pointer-events-none absolute right-2.5 text-xs ${FAINT}`}>{suffixe}</span> : null}
    </span>
  );
}

function Champ({ label, children, hint, className = "" }: { label: string; children: React.ReactNode; hint?: string; className?: string }) {
  return (
    <label className={`flex flex-col gap-1 text-xs ${MUTED} ${className}`} title={hint}>
      <span>{label}</span>
      {children}
    </label>
  );
}

function Pastille({ hex, className = "" }: { hex: string; className?: string }) {
  return <span className={`inline-block h-2.5 w-2.5 shrink-0 rounded-full ${className}`} style={{ background: hex }} />;
}

function Interrupteur({ actif, onChange, hex, label, hint }: { actif: boolean; onChange: (v: boolean) => void; hex: string; label: string; hint?: string }) {
  return (
    <button
      type="button"
      onClick={() => onChange(!actif)}
      title={hint}
      className="inline-flex items-center gap-2 rounded-full border px-2.5 py-1 text-xs transition"
      style={actif ? { borderColor: hex, background: teinte(hex, "22"), color: hex } : { borderColor: "var(--qg-border)", color: "var(--qg-text-muted)" }}
    >
      <span className="relative inline-block h-3.5 w-6 rounded-full transition" style={{ background: actif ? hex : "var(--qg-border)" }}>
        <span className="absolute top-0.5 h-2.5 w-2.5 rounded-full bg-white transition" style={{ left: actif ? "0.8rem" : "0.125rem" }} />
      </span>
      {label}
    </button>
  );
}

// ─── Graphiques (SVG / CSS) ───────────────────────────────────────────────

function Anneau({ parts, total, titre }: { parts: { label: string; valeur: number; hex: string }[]; total: number; titre: string }) {
  const visibles = parts.filter((p) => p.valeur > 0);
  let cumul = 0;
  const segments = visibles.map((p) => {
    const debut = total > 0 ? (cumul / total) * 100 : 0;
    cumul += p.valeur;
    const fin = total > 0 ? (cumul / total) * 100 : 0;
    return `${p.hex} ${debut}% ${fin}%`;
  });
  const fond = segments.length ? `conic-gradient(${segments.join(", ")})` : "conic-gradient(var(--qg-border) 0 100%)";
  return (
    <div className="flex flex-wrap items-center gap-5">
      <div className="relative h-40 w-40 shrink-0 rounded-full" style={{ background: fond }}>
        <div className="absolute inset-[22%] flex flex-col items-center justify-center rounded-full bg-[var(--qg-card-bg)] text-center">
          <span className={`text-[10px] uppercase tracking-wider ${FAINT}`}>{titre}</span>
          <span className="text-sm font-bold tabular-nums">{money(total)}</span>
        </div>
      </div>
      <ul className="min-w-[220px] flex-1 space-y-1 text-xs">
        {parts.map((p) => (
          <li key={p.label} className="flex items-center gap-2">
            <Pastille hex={p.hex} />
            <span className={`flex-1 truncate ${p.valeur > 0 ? "" : FAINT}`}>{p.label}</span>
            <span className={`tabular-nums ${p.valeur > 0 ? "" : FAINT}`}>{money(p.valeur)}</span>
            <span className={`w-12 text-right tabular-nums ${FAINT}`}>{total > 0 && p.valeur > 0 ? pct((100 * p.valeur) / total, 0) : ""}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function Cascade({ t }: { t: Resultats["totaux"] }) {
  const etapes = [
    { label: "Revenus", valeur: t.revenus, hex: C.revenus },
    { label: "Dépenses", valeur: -t.depenses, hex: C.depenses },
    { label: "Bénéfice", valeur: t.benefice, hex: C.benefice },
    { label: "Impôts", valeur: -t.impots, hex: C.impots },
    { label: "Après impôts", valeur: t.benefice_apres_impots, hex: C.benefice },
    { label: "Dividendes", valeur: -t.dividendes, hex: C.dividendes },
    { label: "Retenu", valeur: t.benefice_retenu, hex: C.retenu }
  ];
  const max = Math.max(1, ...etapes.map((e) => Math.abs(e.valeur)));
  const H = 120;
  const W = 300;
  const bw = W / etapes.length;
  return (
    <svg viewBox={`0 0 ${W} ${H + 36}`} className="h-44 w-full">
      <line x1={0} x2={W} y1={H / 2} y2={H / 2} stroke="var(--qg-border)" strokeWidth={1} />
      {etapes.map((e, i) => {
        const h = (Math.abs(e.valeur) / max) * (H / 2 - 6);
        const y = e.valeur >= 0 ? H / 2 - h : H / 2;
        return (
          <g key={e.label}>
            <rect x={i * bw + bw * 0.2} y={y} width={bw * 0.6} height={Math.max(h, 1)} rx={4} fill={e.hex} opacity={0.9} />
            <text x={i * bw + bw / 2} y={H + 14} textAnchor="middle" fontSize={10} fill="var(--qg-text-muted)">
              {e.label}
            </text>
            <text x={i * bw + bw / 2} y={H + 28} textAnchor="middle" fontSize={10} fontWeight={700} fill={e.valeur < 0 && e.label !== "Dépenses" && e.label !== "Impôts" && e.label !== "Dividendes" ? "#f43f5e" : "var(--qg-text)"}>
              {money(e.valeur)}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

function Barres({ items, total }: { items: { label: string; valeur: number; hex: string }[]; total: number }) {
  return (
    <div className="space-y-2">
      {items.map((it) => {
        const w = total > 0 ? Math.max(0, Math.min(100, (100 * it.valeur) / total)) : 0;
        return (
          <div key={it.label}>
            <div className="flex items-baseline justify-between gap-2 text-xs">
              <span className="flex items-center gap-2">
                <Pastille hex={it.hex} /> {it.label}
              </span>
              <span className="tabular-nums">
                {money(it.valeur)} <span className={FAINT}>{total > 0 ? pct(w, 0) : ""}</span>
              </span>
            </div>
            <div className="mt-1 h-2 w-full overflow-hidden rounded-full" style={{ background: "var(--qg-border)" }}>
              <div className="h-full rounded-full transition-all" style={{ width: `${w}%`, background: it.hex }} />
            </div>
          </div>
        );
      })}
      {items.every((i) => i.valeur === 0) ? <p className={`text-xs ${FAINT}`}>Rien de saisi pour l&apos;instant.</p> : null}
    </div>
  );
}

// ─── Briques ─────────────────────────────────────────────────────────────

function KPI({ label, valeur, sous, hex, icon: Icon, alerte = false }: { label: string; valeur: string; sous?: string; hex: string; icon: React.ComponentType<{ className?: string }>; alerte?: boolean }) {
  return (
    <div className={`${CARD} relative overflow-hidden p-4`} style={{ borderLeft: `4px solid ${alerte ? "#f43f5e" : hex}` }}>
      <div className="flex items-start justify-between gap-2">
        <p className={`text-xs ${MUTED}`}>{label}</p>
        <span className="flex h-7 w-7 items-center justify-center rounded-lg" style={{ background: teinte(alerte ? "#f43f5e" : hex), color: alerte ? "#f43f5e" : hex }}>
          <Icon className="h-4 w-4" />
        </span>
      </div>
      <p className={`mt-1 text-2xl font-bold tabular-nums ${alerte ? "text-rose-400" : ""}`}>{valeur}</p>
      {sous ? <p className={`mt-1 text-[11px] leading-snug ${FAINT}`}>{sous}</p> : null}
    </div>
  );
}

function Carte({ id, num, titre, hex, icon: Icon, revenu, revenuLabel = "par an", note, hypotheses, resultat }: { id: string; num?: string; titre: string; hex: string; icon: React.ComponentType<{ className?: string }>; revenu?: number; revenuLabel?: string; note?: string; hypotheses: React.ReactNode; resultat?: React.ReactNode }) {
  return (
    <section id={id} className={`${CARD} overflow-hidden`} style={{ borderTop: `3px solid ${hex}` }}>
      <div className="flex flex-wrap items-center gap-3 px-4 py-3" style={{ background: teinte(hex, "14") }}>
        <span className="flex h-9 w-9 items-center justify-center rounded-xl" style={{ background: teinte(hex, "33"), color: hex }}>
          <Icon className="h-5 w-5" />
        </span>
        <div className="min-w-0 flex-1">
          <h3 className="text-sm font-semibold">
            {num ? <span className={`mr-1.5 ${FAINT}`}>{num}</span> : null}
            {titre}
          </h3>
          {note ? <p className={`text-[11px] leading-snug ${MUTED}`}>{note}</p> : null}
        </div>
        {revenu != null ? (
          <div className="text-right">
            <p className={`text-[10px] uppercase tracking-wider ${FAINT}`}>{revenuLabel}</p>
            <p className="text-lg font-bold tabular-nums" style={{ color: hex }}>
              {money(revenu)}
            </p>
          </div>
        ) : null}
        <BoutonModifier k={id} />
      </div>
      <div className="grid gap-4 p-4 lg:grid-cols-[1fr_minmax(220px,0.9fr)]">
        <div>
          <p className={`mb-2 text-[10px] font-semibold uppercase tracking-wider ${FAINT}`}>Hypothèses</p>
          <Verrou k={id}>{hypotheses}</Verrou>
        </div>
        {resultat ? (
          <div className="rounded-xl p-3 text-xs" style={{ background: teinte(hex, "12"), border: `1px solid ${teinte(hex, "44")}` }}>
            <p className={`mb-2 text-[10px] font-semibold uppercase tracking-wider ${FAINT}`}>Résultat</p>
            {resultat}
          </div>
        ) : null}
      </div>
    </section>
  );
}

function BoutonRetirer({ onClick, title = "Retirer" }: { onClick: () => void; title?: string }) {
  return (
    <button className={`rounded-lg p-1 transition ${FAINT} hover:bg-rose-500/10 hover:text-rose-400`} title={title} onClick={onClick}>
      <X className="h-4 w-4" />
    </button>
  );
}

function Lignes<T>({ lignes, rendu, vide }: { lignes: T[]; rendu: (l: T) => string; vide: string }) {
  if (!lignes.length) return <p className={FAINT}>{vide}</p>;
  return (
    <ul className="space-y-1">
      {lignes.map((l, i) => (
        <li key={i}>{rendu(l)}</li>
      ))}
    </ul>
  );
}

// ─── Page ────────────────────────────────────────────────────────────────

export default function RevenusDepensesPage() {
  const { user } = useCurrentUser();
  const [scenarios, setScenarios] = useState<ScenarioResume[]>([]);
  const [courant, setCourant] = useState<number | null>(null);
  const [detail, setDetail] = useState<Detail | null>(null);
  const [data, setData] = useState<Data | null>(null);
  const [res, setRes] = useState<Resultats | null>(null);
  const [onglet, setOnglet] = useState<"revenus" | "depenses" | "performance">("revenus");
  const [etat, setEtat] = useState<"charge" | "sale" | "sauvegarde" | "ok" | "erreur">("charge");
  const [err, setErr] = useState<string | null>(null);
  const [renomme, setRenomme] = useState<string | null>(null);
  const [editables, setEditables] = useState<Set<string>>(() => new Set());
  const edition: Edition = {
    actif: (k) => editables.has(k),
    basculer: (k) => setEditables((s) => { const n = new Set(Array.from(s)); if (n.has(k)) n.delete(k); else n.add(k); return n; }),
    toutVerrouiller: () => setEditables(new Set()),
    nb: editables.size
  };
  const skipSave = useRef(true);
  const timer = useRef<number | null>(null);
  // Verrou optimiste : horodatage de la version chargée, renvoyé à chaque enregistrement.
  const baseUpdatedAt = useRef<string | null>(null);
  const appliquerConflit = (d: Detail & { message?: string }) => {
    skipSave.current = true;
    setDetail(d);
    setData(d.data);
    setRes(d.resultats);
    baseUpdatedAt.current = d.updated_at;
    setScenarios((prev) => prev.map((s) => (s.id === d.id ? { ...s, nom: d.nom, resume: d.resume, updated_at: d.updated_at } : s)));
    setErr(d.message || "Le scénario a été modifié ailleurs : la version à jour a été rechargée.");
    setEtat("ok");
  };

  const chargerListe = useCallback(async (): Promise<ScenarioResume[]> => {
    const r = await authedFetch(`${RD}/scenarios`);
    if (!r.ok) throw new Error(r.status === 403 ? "Réservé aux administrateurs." : `Erreur ${r.status}`);
    const items = ((await r.json()) as { items: ScenarioResume[] }).items;
    setScenarios(items);
    return items;
  }, []);

  const ouvrir = useCallback(async (id: number) => {
    const r = await authedFetch(`${RD}/scenarios/${id}`);
    if (!r.ok) throw new Error(`Erreur ${r.status}`);
    const d = (await r.json()) as Detail;
    skipSave.current = true;
    baseUpdatedAt.current = d.updated_at;
    setDetail(d);
    setData(d.data);
    setRes(d.resultats);
    setCourant(d.id);
    setEtat("ok");
  }, []);

  useEffect(() => {
    void (async () => {
      try {
        const items = await chargerListe();
        const def = items.find((s) => s.is_default) || items[0];
        if (def) await ouvrir(def.id);
      } catch (e) {
        setErr((e as Error).message);
        setEtat("erreur");
      }
    })();
  }, [chargerListe, ouvrir]);

  useEffect(() => {
    if (!data || courant == null) return;
    if (skipSave.current) {
      skipSave.current = false;
      return;
    }
    setEtat("sale");
    if (timer.current) window.clearTimeout(timer.current);
    timer.current = window.setTimeout(async () => {
      setEtat("sauvegarde");
      try {
        const r = await authedFetch(`${RD}/scenarios/${courant}`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ data, base_updated_at: baseUpdatedAt.current }) });
        if (r.status === 409) {
          appliquerConflit((await r.json()) as Detail & { message?: string });
          return;
        }
        if (!r.ok) throw new Error(`Erreur ${r.status}`);
        const d = (await r.json()) as Detail;
        baseUpdatedAt.current = d.updated_at;
        setRes(d.resultats);
        setScenarios((prev) => prev.map((s) => (s.id === d.id ? { ...s, resume: d.resume, updated_at: d.updated_at } : s)));
        setEtat("ok");
        setErr(null);
      } catch (e) {
        setErr((e as Error).message);
        setEtat("erreur");
      }
    }, 700);
    return () => {
      if (timer.current) window.clearTimeout(timer.current);
    };
  }, [data, courant]);

  const modifier = (fn: (d: Data) => void) => {
    setData((prev) => {
      if (!prev) return prev;
      const n = clone(prev);
      fn(n);
      return n;
    });
  };

  async function nouveau(copie: boolean) {
    try {
      const r = await authedFetch(`${RD}/scenarios`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(copie && courant != null ? { source_id: courant } : {}) });
      if (!r.ok) throw new Error(`Erreur ${r.status}`);
      const d = (await r.json()) as Detail;
      await chargerListe();
      await ouvrir(d.id);
    } catch (e) {
      setErr((e as Error).message);
    }
  }

  async function supprimer() {
    if (courant == null || !detail) return;
    if (!window.confirm(`Supprimer le scénario « ${detail.nom} » ?`)) return;
    try {
      const r = await authedFetch(`${RD}/scenarios/${courant}`, { method: "DELETE" });
      if (!r.ok && r.status !== 204) throw new Error(`Erreur ${r.status}`);
      const items = await chargerListe();
      const suivant = items.find((s) => s.is_default) || items[0];
      if (suivant) await ouvrir(suivant.id);
      else {
        setDetail(null);
        setData(null);
        setRes(null);
        setCourant(null);
      }
    } catch (e) {
      setErr((e as Error).message);
    }
  }

  async function enregistrerNom() {
    if (courant == null || renomme == null) return;
    const nom = renomme.trim();
    setRenomme(null);
    if (!nom || nom === detail?.nom) return;
    try {
      const r = await authedFetch(`${RD}/scenarios/${courant}`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ nom, base_updated_at: baseUpdatedAt.current }) });
      if (r.status === 409) {
        appliquerConflit((await r.json()) as Detail & { message?: string });
        return;
      }
      if (!r.ok) throw new Error(`Erreur ${r.status}`);
      const d = (await r.json()) as Detail;
      baseUpdatedAt.current = d.updated_at;
      setDetail((prev) => (prev ? { ...prev, nom: d.nom } : prev));
      setScenarios((prev) => prev.map((s) => (s.id === d.id ? { ...s, nom: d.nom } : s)));
    } catch (e) {
      setErr((e as Error).message);
    }
  }

  const isAdmin = user?.role === "owner" || user?.role === "admin";
  const greeting = (
    <span className="flex items-center gap-2">
      <Calculator className="h-5 w-5 text-[var(--qg-accent)]" /> Revenus et dépenses
    </span>
  );
  const sousTitre = "Ce que la société de gestion gagne et dépense une fois le fonds en place — simulation alignée sur le document du Fonds MGV ; à brancher sur Kratos et QuickBooks en opération";

  if (!isAdmin && user) {
    return (
      <>
        <QGTopbar greeting={greeting} subtitle={sousTitre} />
        <div className="px-5 py-6 lg:px-8">
          <div className={`${CARD} mx-auto max-w-md px-6 py-12 text-center`}>
            <Lock className={`mx-auto h-8 w-8 ${FAINT}`} />
            <p className={`mt-2 text-sm ${MUTED}`}>Réservé aux administrateurs.</p>
          </div>
        </div>
      </>
    );
  }

  if (!data || !res) {
    return (
      <>
        <QGTopbar greeting={greeting} subtitle={sousTitre} />
        <div className="flex min-h-[300px] items-center justify-center">
          {err ? <p className="text-sm text-rose-400">{err}</p> : <Loader2 className="h-6 w-6 animate-spin text-[var(--qg-accent)]" />}
        </div>
      </>
    );
  }

  const rev = Object.fromEntries(res.revenus.map((s) => [s.key, s])) as Record<string, SectionRevenu>;
  const t = res.totaux;
  const pm = res.point_mort;
  const dep = res.depenses;
  const salairesPostes = dep.salaires.reduce((a, s) => a + s.total, 0);
  const partsRevenus = res.revenus
    .filter((s) => s.key !== "gestion_projection" || data.gestion.inclure_projection)
    .map((s) => ({ label: s.label, valeur: s.revenu, hex: C[s.key] || "#94a3b8" }));
  const partsDepenses = [
    ...dep.frais_fixes_par_categorie.map((c) => ({ label: c.label, valeur: c.montant, hex: CAT_COULEURS[c.categorie] || "#94a3b8" })),
    { label: "Salaires des postes (avec charges)", valeur: salairesPostes, hex: C.salaires },
    { label: "Salaires des associés (avec charges)", valeur: dep.total_associes_salaires, hex: C.associes },
    { label: "Sous-traitant de gestion", valeur: dep.sous_traitance_gestion, hex: C.sous_traitance }
  ];

  return (
    <>
      <QGTopbar
        greeting={greeting}
        subtitle={sousTitre}
        rightSlot={
          <span className="flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs" style={{ background: etat === "erreur" ? teinte("#f43f5e") : etat === "ok" ? teinte("#10b981") : teinte("#f59e0b"), color: etat === "erreur" ? "#f43f5e" : etat === "ok" ? "#10b981" : "#f59e0b" }}>
            {etat === "sauvegarde" || etat === "sale" ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : etat === "ok" ? <Check className="h-3.5 w-3.5" /> : null}
            {etat === "sauvegarde" ? "Enregistrement…" : etat === "sale" ? "Modifié" : etat === "ok" ? "Enregistré" : etat === "erreur" ? "Erreur" : "Chargement"}
          </span>
        }
      />
      <div className="space-y-6 px-5 py-6 lg:px-8">
        {/* Scénarios */}
        <div className={`${CARD} flex flex-wrap items-center gap-2 p-3`}>
          <span className={`flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider ${MUTED}`}>
            <PiggyBank className="h-4 w-4" /> Scénario
          </span>
          <select value={courant ?? ""} onChange={(e) => void ouvrir(Number(e.target.value))} className={`${INPUT} min-w-[240px] font-semibold`}>
            {scenarios.map((s) => (
              <option key={s.id} value={s.id}>
                {s.nom}
                {s.is_default ? " (défaut)" : ""}
              </option>
            ))}
          </select>
          {renomme != null ? (
            <input autoFocus value={renomme} onChange={(e) => setRenomme(e.target.value)} onBlur={() => void enregistrerNom()} onKeyDown={(e) => { if (e.key === "Enter") void enregistrerNom(); if (e.key === "Escape") setRenomme(null); }} className={`${INPUT} w-56`} />
          ) : (
            <button className="btn-secondary btn-sm" onClick={() => setRenomme(detail?.nom || "")} title="Renommer ce scénario">
              <Pencil className="h-3.5 w-3.5" /> Renommer
            </button>
          )}
          <button className="btn-secondary btn-sm" onClick={() => void nouveau(true)} title="Copier ce scénario pour tester une variante">
            <Copy className="h-3.5 w-3.5" /> Dupliquer
          </button>
          <button className="btn-accent btn-sm" onClick={() => void nouveau(false)} title="Nouveau scénario vide">
            <Plus className="h-3.5 w-3.5" /> Nouveau scénario
          </button>
          <fieldset disabled={!edition.actif("annee")} className={`m-0 ml-2 inline-flex items-center gap-2 border-0 p-0 text-xs ${MUTED}`} title="Année planifiée : les acquisitions datées dans cette année sont comptées au prorata des jours restants">
            Année
            <input type="number" min={2000} max={2100} step={1} value={data.annee} onChange={(e) => modifier((d) => { d.annee = Math.round(Number(e.target.value) || d.annee); })} className={`${INPUT} w-24 text-right tabular-nums font-semibold`} />
          </fieldset>
          <button type="button" className="btn-secondary btn-sm" onClick={() => edition.basculer("annee")} title={edition.actif("annee") ? "Terminé" : "Modifier l'année"}>
            {edition.actif("annee") ? <Check className="h-3.5 w-3.5" /> : <Pencil className="h-3.5 w-3.5" />}
          </button>
          {edition.nb > 0 ? (
            <button type="button" className="btn-secondary btn-sm" onClick={edition.toutVerrouiller} title="Reverrouiller toutes les sections ouvertes">
              <Lock className="h-3.5 w-3.5" /> Tout verrouiller ({edition.nb})
            </button>
          ) : null}
          <button className="ml-auto inline-flex items-center gap-1 rounded-lg px-2.5 py-1.5 text-xs text-rose-400/80 transition hover:bg-rose-500/10 hover:text-rose-400" onClick={() => void supprimer()} title="Supprimer ce scénario">
            <Trash2 className="h-3.5 w-3.5" /> Supprimer
          </button>
        </div>
        {err ? <p className="rounded-xl border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">{err}</p> : null}
        {res.avertissements.map((a) => (
          <p key={a} className="rounded-xl border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs text-amber-300">
            {a}
          </p>
        ))}

        {/* Tableau de bord */}
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <KPI label="Revenus annuels" valeur={money(t.revenus)} sous={`${money(t.revenus_mensuels)} / mois${data.gestion.inclure_projection ? "" : ` · ${money(t.revenus_avec_projection)} avec la projection`}`} hex={C.revenus} icon={TrendingUp} />
          <KPI label="Dépenses annuelles" valeur={money(t.depenses)} sous={`${money(t.depenses_mensuelles)} / mois`} hex={C.depenses} icon={Wallet} />
          <KPI label="Bénéfice avant salaires des associés et dividendes" valeur={money(t.benefice_avant_associes)} sous={`salaires des associés (charges incluses) ${money(t.salaires_associes_charges_incluses)}`} hex={C.benefice} icon={Calculator} alerte={t.benefice_avant_associes < 0} />
          <KPI label="Bénéfice avant impôts" valeur={money(t.benefice)} sous={t.marge_pct != null ? `marge ${pct(t.marge_pct)}` : "aucun revenu saisi"} hex={C.benefice} icon={Calculator} alerte={t.benefice < 0} />
          <KPI label="Impôts de la société" valeur={money(t.impots)} sous={`bénéfice après impôts ${money(t.benefice_apres_impots)}${t.marge_apres_impots_pct != null ? ` · marge ${pct(t.marge_apres_impots_pct)}` : ""}`} hex={C.impots} icon={Landmark} alerte={t.benefice_apres_impots < 0} />
          <KPI label="Dividendes des associés" valeur={money(t.dividendes)} sous={`sur le bénéfice après impôts · retenu ${money(t.benefice_retenu)}`} hex={C.dividendes} icon={Users} alerte={t.benefice_retenu < 0} />
          <KPI label="VAN du fonds" valeur={money(res.parc.van)} sous={`${money(res.parc.valeur)} d'immeubles + ${money(res.parc.cash)} de cash − ${money(res.parc.dettes)} de dettes · ${money(res.parc.van_a_terme)} à terme`} hex={C.fonds} icon={Landmark} alerte={res.parc.van < 0} />
          <KPI label="Point mort" valeur={pm.couvert ? "Couvert" : money(pm.van_necessaire)} sous={pm.couvert ? "les revenus couvrent les dépenses" : `VAN nécessaire (actuelle ${money(pm.van_actuelle)}) — ou ${money(pm.loyers_mensuels_sous_gestion_necessaires)} de loyers/mois sous gestion (actuels ${money(pm.loyers_mensuels_sous_gestion_actuels)})`} hex="#f59e0b" icon={Sparkles} alerte={!pm.couvert} />
        </div>

        <div className="grid gap-4 xl:grid-cols-3">
          <div className={`${CARD} p-4`}>
            <h3 className="mb-3 flex items-center gap-2 text-sm font-semibold">
              <span className="flex h-7 w-7 items-center justify-center rounded-lg" style={{ background: teinte(C.revenus), color: C.revenus }}>
                <TrendingUp className="h-4 w-4" />
              </span>
              Revenus par source
            </h3>
            <Anneau parts={partsRevenus} total={t.revenus} titre="Revenus / an" />
          </div>
          <div className={`${CARD} p-4`}>
            <h3 className="mb-3 flex items-center gap-2 text-sm font-semibold">
              <span className="flex h-7 w-7 items-center justify-center rounded-lg" style={{ background: teinte(C.benefice), color: C.benefice }}>
                <Calculator className="h-4 w-4" />
              </span>
              De la première à la dernière ligne
            </h3>
            <Cascade t={t} />
          </div>
          <div className={`${CARD} p-4`}>
            <h3 className="mb-3 flex items-center gap-2 text-sm font-semibold">
              <span className="flex h-7 w-7 items-center justify-center rounded-lg" style={{ background: teinte(C.depenses), color: C.depenses }}>
                <Wallet className="h-4 w-4" />
              </span>
              Dépenses par catégorie
            </h3>
            <Barres items={partsDepenses} total={t.depenses} />
          </div>
        </div>

        {/* Onglets */}
        <div className="flex flex-wrap gap-2">
          {(
            [
              ["revenus", "Revenus", `${money(t.revenus)} / an`, C.revenus, TrendingUp],
              ["depenses", "Dépenses", `${money(t.depenses)} / an`, C.depenses, Wallet],
              // Phil 2026-11-05 : « Performance du fonds, je la veux dans Revenus et dépenses, à côté de Revenus et Dépenses ».
              ["performance", "Performance du fonds", `projection ${data.projection?.horizon_annees ?? 10} ans`, C.fonds, PiggyBank]
            ] as ["revenus" | "depenses" | "performance", string, string, string, React.ComponentType<{ className?: string }>][]
          ).map(([k, label, sous, hex, Icon]) => (
            <button key={k} onClick={() => setOnglet(k)} className={`${CARD} flex items-center gap-3 px-4 py-2.5 text-left transition`} style={onglet === k ? { borderColor: hex, background: teinte(hex, "14") } : undefined}>
              <span className="flex h-8 w-8 items-center justify-center rounded-lg" style={{ background: teinte(hex, "33"), color: hex }}>
                <Icon className="h-4 w-4" />
              </span>
              <span>
                <span className={`block text-[10px] uppercase tracking-wider ${FAINT}`}>{label}</span>
                <span className="block text-sm font-bold tabular-nums" style={{ color: hex }}>
                  {sous}
                </span>
              </span>
            </button>
          ))}
        </div>

        <EditionCtx.Provider value={edition}>
          <style>{`fieldset:disabled button, fieldset:disabled [role="switch"] { opacity: .45; cursor: not-allowed; }`}</style>
          {onglet === "revenus" ? <RevenusTab data={data} res={res} rev={rev} modifier={modifier} referentiel={detail?.referentiel} /> : onglet === "depenses" ? <DepensesTab data={data} res={res} referentiel={detail?.referentiel} modifier={modifier} /> : <><HypothesesProjection data={data} modifier={modifier} referentiel={detail?.referentiel} /><PerformanceTab scenarioId={courant} version={detail?.updated_at ?? null} /></>}
        </EditionCtx.Provider>
      </div>
    </>
  );
}

// ─── Fiche d'immeuble ────────────────────────────────────────────────────

function FicheImmeubleCarte({ im, fiche, modifier, replie, onToggle }: { im: Immeuble; fiche?: FicheImmeuble; modifier: (fn: (d: Data) => void) => void; replie: boolean; onToggle: () => void }) {
  const set = (fn: (x: Immeuble) => void) =>
    modifier((d) => {
      const x = d.immeubles.find((y) => y.id === im.id);
      if (x) fn(x);
    });
  const coutProjet = im.prix_acquisition + im.travaux_initiaux + im.frais_connexes;
  const hex = im.dans_le_fonds ? C.immeubles : "#94a3b8";
  const ds = fiche?.depenses_schl ?? null;
  const [sync, setSync] = useState<"" | "en_cours" | "ok" | "erreur">("");
  const cle = `imm:${im.id}`;
  // Champs repris de Kratos : les ajuster à la main = l'immeuble ne suit plus Kratos (« Actualiser » pour y revenir).
  const setK = (fn: (x: Immeuble) => void) => set((x) => { fn(x); x.suivre_kratos = false; });
  const actualiser = async () => {
    if (!im.kratos_immeuble_id) return;
    setSync("en_cours");
    try {
      const r = await authedFetch(`${RD}/immeubles-kratos`);
      if (!r.ok) throw new Error(String(r.status));
      const j = (await r.json()) as { items: ImmeubleKratos[] };
      const it = j.items.find((x) => x.kratos_immeuble_id === im.kratos_immeuble_id);
      if (!it) throw new Error("introuvable");
      set((x) => {
        x.nb_logements = it.nb_logements; x.nb_logements_en_chambres = it.nb_logements_en_chambres; x.nb_chambres = it.nb_chambres;
        x.loyers_bruts_mensuels = it.loyers_bruts_mensuels;
        if (it.taux_cap_pct) x.taux_cap_pct = it.taux_cap_pct;
        x.valeur_rapport = it.valeur_rapport; x.annee_rapport = it.annee_rapport; x.dette = it.dette;
        x.taxes_municipales = it.taxes_municipales; x.taxes_scolaires = it.taxes_scolaires; x.assurances = it.assurances; x.energie = it.energie;
        x.autres_depenses = it.autres_depenses; x.notes_import = it.notes_import.filter((n) => !x.notes_ignorees.includes(n));
        x.suivre_kratos = true;
      });
      setSync("ok");
    } catch {
      setSync("erreur");
    }
  };
  return (
    <div className={`${CARD} overflow-hidden`} style={{ borderLeft: `4px solid ${hex}` }}>
      <div className="flex flex-wrap items-center gap-2 px-4 py-3" style={{ background: teinte(hex, "10") }}>
        <button type="button" onClick={onToggle} className="rounded-lg p-1 transition hover:bg-black/10" title={replie ? "Déplier" : "Replier"} aria-expanded={!replie}>
          {replie ? <ChevronRight className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
        </button>
        <input value={im.nom} placeholder="Nom ou adresse de l'immeuble" onChange={(e) => set((x) => { x.nom = e.target.value; })} className={`${INPUT} min-w-[220px] flex-1 font-semibold`} />
        {im.kratos_immeuble_id ? (
          <span className="inline-flex items-center gap-1">
            <span className="inline-flex items-center gap-1 rounded-full border border-[var(--qg-border)] px-2 py-0.5 text-[10px] uppercase tracking-wider" title={im.suivre_kratos ? "Suit Kratos : loyers, portes, chambres, rapport, dette et dépenses réelles sont repris à jour à chaque ouverture" : "Valeurs ajustées à la main : « Actualiser » pour revenir à celles de Kratos"}>
              <Database className="h-3 w-3" /> Kratos{im.suivre_kratos ? "" : " · manuel"}
            </span>
            <button type="button" className="btn-secondary btn-sm" onClick={() => void actualiser()} disabled={sync === "en_cours"} title="Reprendre les valeurs à jour de Kratos (écrase les ajustements faits ici)">
              <RefreshCw className={`h-3.5 w-3.5 ${sync === "en_cours" ? "animate-spin" : ""}`} /> Actualiser{sync === "ok" ? " ✓" : sync === "erreur" ? " ✗" : ""}
            </button>
          </span>
        ) : null}
        <Verrou k={cle} className="inline-flex flex-wrap items-center gap-2">
        <Interrupteur actif={im.dans_le_fonds} onChange={(v) => set((x) => { x.dans_le_fonds = v; })} hex={C.fonds} label={im.dans_le_fonds ? "Dans le fonds" : "Hors fonds"} hint="Dans le fonds : compte dans la valeur du parc, les dettes, la VAN, les frais de gestion du fonds et les frais de développement / prospection. Hors fonds : détenu ailleurs — pas de VAN ni de frais du fonds, mais développement, prospection, gestion locative, location, construction et maintenance s'appliquent." />
        <Interrupteur actif={im.gestion_interne} onChange={(v) => setK((x) => { x.gestion_interne = v; })} hex={C.gestion} label={im.gestion_interne ? "Gestion à l'interne" : "Gestion sous-traitée"} hint="À l'interne : nos frais de location s'appliquent. Sous-traitée : les loyers de cet immeuble servent à calculer la dépense du sous-traitant de gestion (onglet Dépenses) ; les frais de gestion restent facturés si l'option est cochée dans la section 7." />
        <BoutonRetirer onClick={() => modifier((d) => { d.immeubles = d.immeubles.filter((y) => y.id !== im.id); })} title="Retirer cet immeuble du scénario" />
        </Verrou>
        <BoutonModifier k={cle} />
      </div>
      {replie ? (
        <button type="button" onClick={onToggle} className={`flex w-full flex-wrap items-center gap-x-4 gap-y-1 px-4 py-2 text-left text-xs ${MUTED}`} title="Déplier la fiche">
          <span>{im.nb_logements} log.{im.nb_logements_en_chambres ? ` (${im.nb_logements_en_chambres} en chambres · ${im.nb_chambres} ch.)` : ""}</span>
          <span><b className="tabular-nums" style={{ color: C.gestion }}>{money(im.loyers_bruts_mensuels)}</b> / mois</span>
          <span>{im.phase === "stabilisation" ? "En rénovation" : "Stabilisé"}</span>
          {fiche ? <span>valeur <b className="tabular-nums">{money(fiche.valeur)}</b></span> : null}
          {fiche ? <span>dette <b className="tabular-nums">{money(fiche.dette)}</b></span> : null}
          {fiche ? <span>équité <b className={`tabular-nums ${fiche.equite < 0 ? "text-rose-400" : ""}`}>{money(fiche.equite)}</b></span> : null}
          {fiche && fiche.revenus_nets != null ? <span>revenus nets {fiche.source_revenus_nets === "schl" ? "SCHL" : "saisis"} <b className="tabular-nums">{money(fiche.revenus_nets)}</b></span> : null}
          {fiche && fiche.date_acquisition && fiche.part_annee < 100 ? <span className="text-amber-300">{pct(fiche.part_annee)} de l&apos;année</span> : null}
          {im.notes_import.length ? <span className="inline-flex items-center gap-1 text-amber-300"><AlertTriangle className="h-3 w-3" /> {im.notes_import.length} à vérifier</span> : null}
        </button>
      ) : (
      <Verrou k={cle}><div className="grid gap-4 p-4 lg:grid-cols-3">
        {/* Loyers et portes */}
        <div className="space-y-2">
          <p className="flex items-center gap-2 text-[10px] font-semibold uppercase tracking-wider" style={{ color: C.gestion }}>
            <Pastille hex={C.gestion} /> Loyers et portes
          </p>
          {im.kratos_immeuble_id ? <p className={`text-[11px] leading-snug ${FAINT}`}>{im.suivre_kratos ? "Valeurs de Kratos, reprises à jour à chaque ouverture de la page." : "Valeurs ajustées à la main : « Actualiser » pour revenir à celles de Kratos."}</p> : null}
          <Champ label="Loyers bruts par mois"><Num value={im.loyers_bruts_mensuels} onChange={(v) => setK((x) => { x.loyers_bruts_mensuels = v; })} suffixe="$" /></Champ>
          <div className="grid grid-cols-2 gap-2">
            <Champ label="Logements (total)" hint="Toutes les unités de l'immeuble : ce nombre sert aux dépenses normalisées SCHL, à la maintenance et aux dépenses refacturées. Repris de la fiche de l'immeuble dans Kratos (Nb logements)."><Num value={im.nb_logements} step={1} onChange={(v) => setK((x) => { x.nb_logements = Math.round(v); x.nb_logements_en_chambres = Math.min(x.nb_logements_en_chambres, x.nb_logements); })} /></Champ>
            <Champ label="dont loués en chambres" hint="Nombre de ces logements loués à la chambre (fiche de l'immeuble dans Kratos)"><Num value={im.nb_logements_en_chambres} step={1} onChange={(v) => setK((x) => { x.nb_logements_en_chambres = Math.max(0, Math.min(Math.round(v), x.nb_logements)); })} /></Champ>
          </div>
          {im.nb_logements_en_chambres > 0 ? (
            <Champ label="Chambres créées par ces logements" hint="Pour les frais de location : logements hors chambres + chambres (fiche de l'immeuble dans Kratos)"><Num value={im.nb_chambres} step={1} onChange={(v) => setK((x) => { x.nb_chambres = Math.round(v); })} /></Champ>
          ) : null}
        </div>
        {/* Statut et valeur */}
        <div className="space-y-2">
          <p className="flex items-center gap-2 text-[10px] font-semibold uppercase tracking-wider" style={{ color: C.construction }}>
            <Pastille hex={C.construction} /> Statut et valeur
          </p>
          <div className="flex gap-1 rounded-lg border border-[var(--qg-border)] p-0.5">
            {(
              [
                ["stabilisation", "En rénovation"],
                ["stabilise", "Stabilisé"]
              ] as [Immeuble["phase"], string][]
            ).map(([k, label]) => (
              <button key={k} type="button" onClick={() => set((x) => { x.phase = k; })} className="flex-1 rounded-md px-2 py-1 text-xs font-semibold transition" style={im.phase === k ? { background: teinte(C.construction, "33"), color: C.construction } : { color: "var(--qg-text-muted)" }}>
                {label}
              </button>
            ))}
          </div>
          <label className={`flex items-start gap-2 text-xs ${MUTED}`} title="Coche si l'achat se conclut cette année : ça déclenche les frais de développement (par tranches sur le prix) et, si prospecté par nous, les frais de prospection.">
            <input type="checkbox" className="mt-0.5 h-4 w-4" style={{ accentColor: C.developpement }} checked={im.acquisition_cette_annee} onChange={(e) => set((x) => { x.acquisition_cette_annee = e.target.checked; })} />
            <span>Acquisition conclue cette année <span className={FAINT}>(frais de développement et de prospection)</span></span>
          </label>
          {im.acquisition_cette_annee || im.phase === "stabilisation" ? (
            <Champ label="Prix d'acquisition"><Num value={im.prix_acquisition} onChange={(v) => set((x) => { x.prix_acquisition = v; })} suffixe="$" /></Champ>
          ) : null}
          {im.acquisition_cette_annee ? (
            <>
              <Champ label="Date d'acquisition" hint="Vide = 1er janvier (année entière). Avec une date, gestion, location, rénos au roulement, frais du fonds et sous-traitant comptent au prorata des jours restants.">
                <input type="date" value={im.date_acquisition ?? ""} onChange={(e) => set((x) => { x.date_acquisition = e.target.value || null; })} className={`${INPUT} w-full`} />
              </Champ>
              <label className={`flex items-center gap-2 text-xs ${MUTED}`}>
                <input type="checkbox" className="h-4 w-4" style={{ accentColor: C.prospection }} checked={im.prospecte_par_nous} onChange={(e) => set((x) => { x.prospecte_par_nous = e.target.checked; })} /> Prospecté par nous (frais de prospection)
              </label>
            </>
          ) : null}
          {im.phase === "stabilisation" ? (
            <>
              <div className="grid grid-cols-2 gap-2">
                <Champ label="Travaux"><Num value={im.travaux_initiaux} onChange={(v) => set((x) => { x.travaux_initiaux = v; })} suffixe="$" /></Champ>
                <Champ label="Frais connexes" hint="Frais de développement, taxe de bienvenue, frais du prêteur, notaire…"><Num value={im.frais_connexes} onChange={(v) => set((x) => { x.frais_connexes = v; })} suffixe="$" /></Champ>
              </div>
              <p className={`text-xs ${MUTED}`}>
                Coût du projet : <b>{money(coutProjet)}</b>
              </p>
              <Champ label="Valeur future (rapport au refi)"><Num value={im.valeur_future} onChange={(v) => set((x) => { x.valeur_future = v; })} suffixe="$" /></Champ>
              <Champ label="Loyers stabilisés (par mois, après travaux)" hint="Pour la projection de l'onglet Performance : les loyers une fois les travaux finis. 0 = inconnus, les revenus nets stabilisés sont alors estimés par valeur future × taux de cap."><Num value={im.loyers_stabilises_mensuels} onChange={(v) => set((x) => { x.loyers_stabilises_mensuels = v; })} suffixe="$/mois" /></Champ>
              <div className="grid grid-cols-2 gap-2">
                <Champ label="Durée du projet"><Num value={im.mois_prevus} step={1} onChange={(v) => set((x) => { x.mois_prevus = Math.max(1, Math.round(v)); })} suffixe="mois" /></Champ>
                <Champ label="Mois écoulés" hint="Où on en est dans le projet : la plus-value se reconnaît en ligne droite, mois par mois"><Num value={im.mois_ecoules} step={1} onChange={(v) => set((x) => { x.mois_ecoules = Math.round(v); })} suffixe="mois" /></Champ>
              </div>
            </>
          ) : (
            <>
              <div className="grid grid-cols-[1fr_90px] gap-2">
                <Champ label="Dernier rapport d'évaluation"><Num value={im.valeur_rapport} onChange={(v) => setK((x) => { x.valeur_rapport = v; })} suffixe="$" /></Champ>
                <Champ label="Année">
                  <input type="number" min={1990} max={2100} step={1} value={im.annee_rapport ?? ""} placeholder="2026" onChange={(e) => setK((x) => { x.annee_rapport = e.target.value === "" ? null : Math.round(Number(e.target.value)); })} className={`${INPUT} w-full text-right tabular-nums`} />
                </Champ>
              </div>
              <Champ label="Taux de cap du rapport" hint="Repris de l'évaluation dans Kratos (fiche de l'immeuble → Évaluations) quand il y est saisi. Avec des loyers, la valeur suit les revenus nets SCHL ÷ taux de cap ; sans taux, la valeur reste celle du rapport."><Num value={im.taux_cap_pct} step={0.1} onChange={(v) => setK((x) => { x.taux_cap_pct = v; })} suffixe="%" /></Champ>
              <p className="flex items-center gap-2 pt-1 text-[10px] font-semibold uppercase tracking-wider" style={{ color: C.construction }}>
                <Pastille hex={C.construction} /> Dépenses réelles par an
              </p>
              <div className="grid grid-cols-2 gap-2">
                <Champ label="Taxes municipales"><Num value={im.taxes_municipales} onChange={(v) => setK((x) => { x.taxes_municipales = v; })} suffixe="$" /></Champ>
                <Champ label="Taxes scolaires"><Num value={im.taxes_scolaires} onChange={(v) => setK((x) => { x.taxes_scolaires = v; })} suffixe="$" /></Champ>
                <Champ label="Assurances"><Num value={im.assurances} onChange={(v) => setK((x) => { x.assurances = v; })} suffixe="$" /></Champ>
                <Champ label="Énergie"><Num value={im.energie} onChange={(v) => setK((x) => { x.energie = v; })} suffixe="$" /></Champ>
              </div>
              <div className="grid grid-cols-2 gap-2">
                {im.kratos_immeuble_id ? null : <Champ label="Revenus nets saisis" hint="Optionnel : laisse à 0 pour le calcul SCHL automatique (loyers bruts − dépenses normalisées). Une valeur saisie prime."><Num value={im.revenus_nets_annuels} onChange={(v) => set((x) => { x.revenus_nets_annuels = v; })} suffixe="$/an" /></Champ>}
              </div>
              {ds ? (
                <details className={`rounded-xl border border-[var(--qg-border)] px-3 py-2 text-xs ${MUTED}`}>
                  <summary className="cursor-pointer">Revenus nets SCHL : <b className="tabular-nums">{money(ds.revenus_nets)}</b> / an <span className={FAINT}>(détails)</span></summary>
                  <ul className="mt-1 space-y-0.5 tabular-nums">
                    <li className="flex justify-between gap-2"><span>Loyers bruts annuels</span><span>{money(ds.revenus_bruts_annuels)}</span></li>
                    {LIGNES_SCHL.map(([l, k]) => (
                      <li key={k} className="flex justify-between gap-2"><span>− {l}</span><span>{money(ds[k])}</span></li>
                    ))}
                    <li className="flex justify-between gap-2 border-t border-[var(--qg-border)] pt-0.5 font-semibold"><span>Revenus nets</span><span>{money(ds.revenus_nets)}</span></li>
                  </ul>
                </details>
              ) : null}
            </>
          )}
        </div>
        {/* Dette et équité */}
        <div className="space-y-2">
          <p className="flex items-center gap-2 text-[10px] font-semibold uppercase tracking-wider" style={{ color: C.fonds }}>
            <Pastille hex={C.fonds} /> Dette et équité
          </p>
          <Champ label="Dette (solde du prêt)"><Num value={im.dette} onChange={(v) => setK((x) => { x.dette = v; })} suffixe="$" /></Champ>
          {im.kratos_immeuble_id ? (
            <p className={`text-[11px] ${FAINT}`}>Projection (onglet Performance) : les hypothèques de Kratos (taux, amortissement, paiement, échéance du terme).</p>
          ) : (
            <>
              <div className="grid grid-cols-2 gap-2">
                <Champ label="Taux du prêt" hint="Pour la projection ; 0 = taux par défaut de la section Projection (onglet Performance)"><Num value={im.taux_dette_pct} step={0.05} onChange={(v) => set((x) => { x.taux_dette_pct = v; })} suffixe="%" /></Champ>
                <Champ label="Amortissement" hint="Pour la projection ; 0 = amortissement par défaut de la section Projection"><Num value={im.amortissement_ans} step={1} onChange={(v) => set((x) => { x.amortissement_ans = Math.max(0, Math.round(v)); })} suffixe="ans" /></Champ>
              </div>
              <Interrupteur actif={im.interet_seulement} onChange={(v) => set((x) => { x.interet_seulement = v; })} hex={C.fonds} label="Intérêts seulement (prêteur B, privé)" hint="Le prêt ne rembourse pas de capital ; il devient un prêt amorti à la stabilisation (immeuble en rénovation) ou dès l'an 2." />
            </>
          )}
          {fiche ? (
            <div className="rounded-xl p-3 text-xs" style={{ background: teinte(hex, "12"), border: `1px solid ${teinte(hex, "44")}` }}>
              <ul className="space-y-1">
                <li className="flex justify-between gap-2"><span>Valeur actuelle</span><b className="tabular-nums">{money(fiche.valeur)}</b></li>
                {im.phase === "stabilisation" && fiche.plus_value_prevue ? (
                  <li className="flex justify-between gap-2"><span>À terme</span><span className="tabular-nums">{money(fiche.valeur_a_terme)} <span className={FAINT}>(+{money(fiche.plus_value_prevue)})</span></span></li>
                ) : null}
                <li className="flex justify-between gap-2"><span>Dette</span><span className="tabular-nums">− {money(fiche.dette)}</span></li>
                <li className="flex justify-between gap-2 border-t border-[var(--qg-border)] pt-1 font-semibold"><span>Équité</span><span className={`tabular-nums ${fiche.equite < 0 ? "text-rose-400" : ""}`}>{money(fiche.equite)}</span></li>
                <li className={`${FAINT} leading-snug`}>{fiche.methode}</li>
                {!im.dans_le_fonds ? <li className={FAINT}>Hors fonds : pas dans la VAN.</li> : null}
                {fiche.date_acquisition && fiche.part_annee < 100 ? (
                  <li className="text-amber-300">Acquis le {fmtDateFr(fiche.date_acquisition)} : {fiche.jours} jours sur {fiche.jours_annee} = {pct(fiche.part_annee)} de l&apos;année au prorata.</li>
                ) : null}
                {fiche.date_acquisition && !fiche.acquise_cette_annee ? (
                  <li className="text-amber-300">Date hors de l&apos;année du scénario : {fiche.part_annee === 0 ? "rien cette année" : "année entière, sans frais d'acquisition"}.</li>
                ) : null}
              </ul>
            </div>
          ) : null}
          {im.notes_import.length ? (
            <div className="rounded-xl border border-amber-500/40 bg-amber-500/10 p-2.5 text-[11px] text-amber-200">
              <p className="mb-1 flex items-center gap-1 font-semibold"><AlertTriangle className="h-3.5 w-3.5" /> À vérifier (import Kratos)</p>
              <ul className="space-y-0.5">
                {im.notes_import.map((n, idx) => (
                  <li key={idx} className="flex items-start gap-1">
                    <span className="flex-1">{n}</span>
                    <button className="shrink-0 underline-offset-2 hover:underline" title="J'ai vérifié, retirer cette alerte" onClick={() => set((x) => { x.notes_ignorees = [...x.notes_ignorees, n]; x.notes_import = x.notes_import.filter((_, j) => j !== idx); })}>ok</button>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </div>
      </div></Verrou>
      )}
    </div>
  );
}

function ImportKratosModal({ dejaPris, onClose, onAjouter }: { dejaPris: Set<number>; onClose: () => void; onAjouter: (items: ImmeubleKratos[]) => void }) {
  const [items, setItems] = useState<ImmeubleKratos[] | null>(null);
  const [choisis, setChoisis] = useState<Set<number>>(new Set());
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    void (async () => {
      try {
        const r = await authedFetch(`${RD}/immeubles-kratos`);
        if (!r.ok) throw new Error(`Erreur ${r.status}`);
        setItems(((await r.json()) as { items: ImmeubleKratos[] }).items);
      } catch (e) {
        setErr((e as Error).message);
        setItems([]);
      }
    })();
  }, []);
  const basculer = (id: number) =>
    setChoisis((prev) => {
      const n = new Set(prev);
      if (n.has(id)) n.delete(id);
      else n.add(id);
      return n;
    });
  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/50 p-4" onClick={onClose}>
      <div className={`${CARD} max-h-[85vh] w-full max-w-4xl overflow-hidden`} onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between gap-2 border-b border-[var(--qg-border)] px-4 py-3">
          <h3 className="flex items-center gap-2 text-sm font-semibold">
            <Database className="h-4 w-4 text-[var(--qg-accent)]" /> Immeubles déjà dans Kratos
          </h3>
          <button className={`rounded-lg p-1 ${FAINT} hover:text-white`} onClick={onClose}>
            <X className="h-4 w-4" />
          </button>
        </div>
        <p className={`px-4 pt-3 text-xs ${MUTED}`}>Logements, chambres, loyers (même total que la liste des immeubles : baux actifs, ou loyer saisi sur les logements en gestion externe), dette du jour des hypothèques actives (comme la fiche de l&apos;immeuble) et dernier rapport d&apos;évaluation sont repris tels quels. « Gestion externe » dans Kratos n&apos;a rien à voir avec « sous-traitée » ici : chaque immeuble arrive en gestion à l&apos;interne, à toi de choisir. Le triangle signale ce qui manque dans Kratos ; l&apos;alerte suit l&apos;immeuble dans sa fiche. Tu ajustes ensuite (statut, dans le fonds ou non…).</p>
        <div className="max-h-[55vh] overflow-auto px-4 py-3">
          {items == null ? (
            <Loader2 className="h-5 w-5 animate-spin text-[var(--qg-accent)]" />
          ) : err ? (
            <p className="text-xs text-rose-400">{err}</p>
          ) : (
            <table className="w-full text-xs">
              <thead className={`text-left ${MUTED}`}>
                <tr>
                  <th className="py-1" />
                  <th className="py-1">Immeuble</th>
                  <th className="py-1 text-right">Logements</th>
                  <th className="py-1 text-right">Chambres</th>
                  <th className="py-1 text-right">Loyers / mois</th>
                  <th className="py-1 text-right">Dette</th>
                  <th className="py-1 text-right">Rapport</th>
                  <th className="py-1" />
                </tr>
              </thead>
              <tbody className="divide-y divide-[var(--qg-border)]">
                {items.map((it) => {
                  const pris = dejaPris.has(it.kratos_immeuble_id);
                  return (
                    <tr key={it.kratos_immeuble_id} className={pris ? "opacity-50" : "cursor-pointer hover:bg-[var(--qg-bg)]/40"} onClick={() => !pris && basculer(it.kratos_immeuble_id)}>
                      <td className="py-1.5"><input type="checkbox" disabled={pris} checked={pris || choisis.has(it.kratos_immeuble_id)} onChange={() => basculer(it.kratos_immeuble_id)} onClick={(e) => e.stopPropagation()} /></td>
                      <td className="py-1.5">
                        <div className="font-medium">{it.nom}</div>
                        <div className={`text-[11px] ${FAINT}`}>{[it.adresse, it.ville].filter(Boolean).join(", ")}{pris ? " · déjà dans le scénario" : ""}</div>
                      </td>
                      <td className="py-1.5 text-right tabular-nums">{it.nb_logements}</td>
                      <td className="py-1.5 text-right tabular-nums">{it.nb_chambres}</td>
                      <td className="py-1.5 text-right tabular-nums">{money(it.loyers_bruts_mensuels)}</td>
                      <td className="py-1.5 text-right tabular-nums">{money(it.dette)}</td>
                      <td className="py-1.5 text-right tabular-nums">{it.valeur_rapport ? `${money(it.valeur_rapport)}${it.annee_rapport ? ` (${it.annee_rapport})` : ""}` : "—"}</td>
                      <td className="py-1.5 pl-2">
                        {it.notes_import.length ? (
                          <span className="inline-flex items-center gap-1 rounded-full border border-amber-500/40 bg-amber-500/10 px-2 py-0.5 text-[10px] text-amber-300" title={it.notes_import.join("\n")}>
                            <AlertTriangle className="h-3 w-3" /> {it.notes_import.length}
                          </span>
                        ) : null}
                      </td>
                    </tr>
                  );
                })}
                {items.length === 0 ? (
                  <tr>
                    <td colSpan={8} className={`py-4 text-center ${FAINT}`}>Aucun immeuble actif dans Kratos.</td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          )}
        </div>
        <div className="flex items-center justify-end gap-2 border-t border-[var(--qg-border)] px-4 py-3">
          <button className="btn-secondary btn-sm" onClick={onClose}>Annuler</button>
          <button className="btn-accent btn-sm" disabled={choisis.size === 0} onClick={() => onAjouter((items || []).filter((i) => choisis.has(i.kratos_immeuble_id)))}>
            <Plus className="h-3.5 w-3.5" /> Ajouter {choisis.size || ""} immeuble{choisis.size > 1 ? "s" : ""}
          </button>
        </div>
      </div>
    </div>
  );
}

// ─── Onglet Revenus ──────────────────────────────────────────────────────

function RevenusTab({ data, res, rev, modifier, referentiel }: { data: Data; res: Resultats; rev: Record<string, SectionRevenu>; modifier: (fn: (d: Data) => void) => void; referentiel?: Referentiel }) {
  const [importOuvert, setImportOuvert] = useState(false);
  // Fiches repliées par défaut (Phil : « sinon c'est gros ») ; on retient celles qu'on a dépliées.
  const [deplies, setDeplies] = useState<Set<string>>(() => new Set());
  const basculer = (id: string) => setDeplies((s) => { const n = new Set(Array.from(s)); if (n.has(id)) n.delete(id); else n.add(id); return n; });
  const ed = useContext(EditionCtx);
  const f = data.fonds;
  const parc = res.parc;
  const fiches = Object.fromEntries(parc.immeubles.map((x) => [x.id, x])) as Record<string, FicheImmeuble>;
  const immeubles = data.immeubles;
  const pg = res.part_des_gains;
  const sections: [string, string][] = [
    ["fonds", "1. Fonds"],
    ["developpement", "2. Développement"],
    ["prospection", "3. Prospection"],
    ["refacturation", "4. Refacturation"],
    ["construction", "5. Construction"],
    ["maintenance", "6. Maintenance"],
    ["gestion", "7. Gestion locative"],
    ["location", "8. Location"]
  ];

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-2">
        {sections.map(([k, label]) => (
          <a key={k} href={`#sec-${k}`} className="inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs transition hover:opacity-80" style={{ borderColor: teinte(C[k], "66"), background: teinte(C[k], "14") }}>
            <Pastille hex={C[k]} /> {label}
            <span className="font-semibold tabular-nums" style={{ color: C[k] }}>
              {money(rev[k]?.revenu)}
            </span>
          </a>
        ))}
        <a href="#sec-part_des_gains" className="inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs transition hover:opacity-80" style={{ borderColor: teinte(C.part_des_gains, "66"), background: teinte(C.part_des_gains, "14") }}>
          <Pastille hex={C.part_des_gains} /> Part des gains (en parts)
          <span className="font-semibold tabular-nums" style={{ color: C.part_des_gains }}>{money(pg.part_nous)}</span>
        </a>
      </div>

      {/* Immeubles */}
      <section id="sec-immeubles" className={`${CARD} overflow-hidden`} style={{ borderTop: `3px solid ${C.immeubles}` }}>
        <div className="flex flex-wrap items-center gap-3 px-4 py-3" style={{ background: teinte(C.immeubles, "14") }}>
          <span className="flex h-9 w-9 items-center justify-center rounded-xl" style={{ background: teinte(C.immeubles, "33"), color: C.immeubles }}>
            <Building2 className="h-5 w-5" />
          </span>
          <div className="min-w-0 flex-1">
            <h3 className="text-sm font-semibold">Immeubles</h3>
            <p className={`text-[11px] leading-snug ${MUTED}`}>{referentiel?.valorisation_note} {referentiel?.schl_note} {referentiel?.prorata_note}</p>
          </div>
          <div className="text-right text-xs">
            <p className={FAINT}>{parc.nb_dans_le_fonds} dans le fonds · {parc.nb_hors_fonds} hors fonds · {parc.nb_en_renovation} en rénovation{parc.nb_prorates ? ` · ${parc.nb_prorates} au prorata (${parc.annee})` : ""}</p>
            <p className="font-bold tabular-nums" style={{ color: C.immeubles }}>Parc {money(parc.valeur)} · dettes {money(parc.dettes)} · équité {money(parc.equite)}</p>
          </div>
        </div>
        <div className="space-y-3 p-4">
          {immeubles.map((im) => (
            <FicheImmeubleCarte key={im.id} im={im} fiche={fiches[im.id]} modifier={modifier} replie={!deplies.has(im.id)} onToggle={() => basculer(im.id)} />
          ))}
          {immeubles.length === 0 ? <p className={`rounded-xl border border-dashed border-[var(--qg-border)] px-4 py-6 text-center text-sm ${FAINT}`}>Aucun immeuble — ajoute ceux que le fonds va détenir, ou reprends ceux déjà dans Kratos.</p> : null}
          <div className="flex flex-wrap gap-2">
            <button className="btn-accent btn-sm" onClick={() => { const n = immeubleVide(); modifier((d) => { d.immeubles.push(n); }); setDeplies((s) => new Set([...Array.from(s), n.id])); ed.basculer(`imm:${n.id}`); }}>
              <Plus className="h-3.5 w-3.5" /> Ajouter un immeuble
            </button>
            <button className="btn-secondary btn-sm" onClick={() => setImportOuvert(true)}>
              <Database className="h-3.5 w-3.5" /> Depuis Kratos…
            </button>
            {immeubles.length > 1 ? (
              <>
                <button className="btn-secondary btn-sm" onClick={() => setDeplies(new Set(immeubles.map((i) => i.id)))}><ChevronDown className="h-3.5 w-3.5" /> Tout déplier</button>
                <button className="btn-secondary btn-sm" onClick={() => setDeplies(new Set())}><ChevronRight className="h-3.5 w-3.5" /> Tout replier</button>
              </>
            ) : null}
          </div>
        </div>
      </section>
      {importOuvert ? (
        <ImportKratosModal
          dejaPris={new Set(immeubles.map((i) => i.kratos_immeuble_id).filter((x): x is number => x != null))}
          onClose={() => setImportOuvert(false)}
          onAjouter={(items) => {
            modifier((d) => {
              for (const it of items) {
                d.immeubles.push(immeubleVide({ nom: it.nom, kratos_immeuble_id: it.kratos_immeuble_id, nb_logements: it.nb_logements, nb_logements_en_chambres: it.nb_logements_en_chambres, nb_chambres: it.nb_chambres, loyers_bruts_mensuels: it.loyers_bruts_mensuels, gestion_interne: true, phase: "stabilise", valeur_rapport: it.valeur_rapport, annee_rapport: it.annee_rapport, taux_cap_pct: it.taux_cap_pct, dette: it.dette, taxes_municipales: it.taxes_municipales, taxes_scolaires: it.taxes_scolaires, assurances: it.assurances, energie: it.energie, autres_depenses: it.autres_depenses, notes_import: it.notes_import, suivre_kratos: true }));
              }
            });
            setImportOuvert(false);
          }}
        />
      ) : null}

      <div className="grid gap-4 xl:grid-cols-2">
        {/* 1. Fonds */}
        <Carte id="sec-fonds" num="1." titre="Frais de gestion du fonds" hex={C.fonds} icon={ICONES.fonds} revenu={rev.fonds?.revenu} note="VAN = valeur des immeubles du fonds + cash − dettes (document, p. 11). Valeur et dettes viennent des fiches ; seul le cash se saisit ici."
          hypotheses={
            <div className="grid gap-3 sm:grid-cols-2">
              <Champ label="Cash du fonds et des inc." hint="Compte du fonds (levées, refis) + cash accumulé dans les inc."><Num value={f.cash} onChange={(v) => modifier((d) => { d.fonds.cash = v; })} suffixe="$" /></Champ>
              <Champ label="Frais de gestion (de la VAN, par an)"><Num value={f.taux_pct} step={0.1} onChange={(v) => modifier((d) => { d.fonds.taux_pct = v; })} suffixe="%" /></Champ>
            </div>
          }
          resultat={
            <ul className="space-y-1">
              <li className="flex justify-between gap-2"><span>Immeubles du fonds</span><span className="tabular-nums">{money(parc.valeur)}</span></li>
              <li className="flex justify-between gap-2"><span>+ Cash</span><span className="tabular-nums">{money(parc.cash)}</span></li>
              <li className="flex justify-between gap-2"><span>− Dettes</span><span className="tabular-nums">{money(parc.dettes)}</span></li>
              <li className="flex justify-between gap-2 border-t border-[var(--qg-border)] pt-1 font-semibold"><span>VAN</span><b className={`tabular-nums ${parc.van < 0 ? "text-rose-400" : ""}`}>{money(parc.van)}</b></li>
              {parc.nb_prorates ? <li className="flex justify-between gap-2"><span>VAN pondérée par le temps (acquisitions au prorata)</span><span className="tabular-nums">{money(parc.van_ponderee)}</span></li> : null}
              <li className="flex justify-between gap-2"><span>× {pct(f.taux_pct)}</span><b className="tabular-nums" style={{ color: C.fonds }}>{money(rev.fonds?.revenu)} / an</b></li>
              <li className={FAINT}>VAN à terme (rénovations terminées) : {money(parc.van_a_terme)}</li>
            </ul>
          }
        />

        {/* 2. Développement */}
        <Carte id="sec-developpement" num="2." titre="Frais de développement" hex={C.developpement} icon={ICONES.developpement} revenu={rev.developpement?.revenu} note="Sur le prix d'achat, par tranches comme l'impôt : chaque taux s'applique à sa tranche seulement (document, p. 21). Pour les acquisitions conclues cette année, dans le fonds ou non. Dans le résultat, tu peux forcer le montant d'un immeuble (Modifier) et revenir au calcul."
          hypotheses={
            <>
              <table className="w-full text-xs">
                <thead className={`text-left ${MUTED}`}>
                  <tr>
                    <th className="py-1">Tranche</th>
                    <th className="py-1 text-right">Taux</th>
                    <th />
                  </tr>
                </thead>
                <tbody className="divide-y divide-[var(--qg-border)]">
                  {data.developpement.paliers.map((p, idx) => {
                    const debut = idx === 0 ? 0 : (data.developpement.paliers[idx - 1].jusqua ?? 0);
                    return (
                    <tr key={idx}>
                      <td className="py-1 pr-2"><span className="inline-flex items-center gap-2"><span className={`whitespace-nowrap ${MUTED}`}>{p.jusqua == null ? `${money(debut)} et plus` : `de ${money(debut)} à`}</span>{p.jusqua == null ? null : <Num value={p.jusqua} onChange={(v) => modifier((d) => { d.developpement.paliers[idx].jusqua = v; })} className="w-40" suffixe="$" />}</span></td>
                      <td className="py-1 text-right"><Num value={p.pct} step={0.1} onChange={(v) => modifier((d) => { d.developpement.paliers[idx].pct = v; })} className="w-24" suffixe="%" /></td>
                      <td className="py-1 text-right">{p.jusqua != null ? <BoutonRetirer title="Retirer cette tranche" onClick={() => modifier((d) => { d.developpement.paliers.splice(idx, 1); })} /> : null}</td>
                    </tr>
                    );
                  })}
                </tbody>
              </table>
              <button className="btn-secondary btn-sm mt-2" onClick={() => modifier((d) => { const dernier = d.developpement.paliers.filter((p) => p.jusqua != null).slice(-1)[0]; d.developpement.paliers.splice(d.developpement.paliers.length - 1, 0, { jusqua: (dernier?.jusqua || 0) + 5_000_000, pct: 3 }); })}>
                <Plus className="h-3.5 w-3.5" /> Ajouter une tranche
              </button>
            </>
          }
          resultat={
            <Verrou k="sec-developpement">
              <ul className="space-y-1.5">
                {((rev.developpement?.lignes as LigneDev[]) || []).map((l) => (
                  <li key={l.id} className="flex flex-wrap items-center gap-2">
                    <span className="min-w-0 flex-1">{l.immeuble} : {money(l.prix)} → {l.override ? <span className="text-amber-300">montant forcé (calcul : {money(l.frais_calcule)})</span> : <span className={FAINT}>taux effectif {pct(l.taux_effectif_pct, 2)}</span>}</span>
                    <Num value={l.frais} className="w-32" suffixe="$" title="Frais de développement de cet immeuble (modifiable)" onChange={(v) => modifier((d) => { const x = d.immeubles.find((y) => y.id === l.id); if (x) x.frais_developpement_override = v; })} />
                    {l.override ? (
                      <button type="button" className="btn-secondary btn-sm" title={`Revenir au calcul par tranches : ${money(l.frais_calcule)}`} onClick={() => modifier((d) => { const x = d.immeubles.find((y) => y.id === l.id); if (x) x.frais_developpement_override = null; })}>
                        <RotateCcw className="h-3.5 w-3.5" /> Calcul
                      </button>
                    ) : null}
                  </li>
                ))}
                {!((rev.developpement?.lignes as unknown[]) || []).length ? <li className={FAINT}>Aucune acquisition conclue cette année.</li> : null}
              </ul>
            </Verrou>
          }
        />

        {/* 3. Prospection */}
        <Carte id="sec-prospection" num="3." titre="Frais de prospection" hex={C.prospection} icon={ICONES.prospection} revenu={rev.prospection?.revenu} note="Seulement quand c'est nous qui avons prospecté l'immeuble (case dans la fiche), sur les acquisitions conclues cette année."
          hypotheses={<Champ label="Taux (du prix d'acquisition)" className="max-w-[180px]"><Num value={data.prospection.taux_pct} step={0.1} onChange={(v) => modifier((d) => { d.prospection.taux_pct = v; })} suffixe="%" /></Champ>}
          resultat={<Lignes lignes={(rev.prospection?.lignes as { immeuble: string; prix: number; frais: number }[]) || []} rendu={(l) => `${l.immeuble} : ${money(l.prix)} × ${pct(data.prospection.taux_pct)} = ${money(l.frais)}`} vide="Aucune acquisition prospectée par nous cette année." />}
        />

        {/* 4. Refacturation */}
        <Carte id="sec-refacturation" num="4." titre="Dépenses refacturées (cost-plus)" hex={C.refacturation} icon={ICONES.refacturation} revenu={rev.refacturation?.revenu} note="On avance la dépense (ex. un avocat à 2 000 $) et on la recharge 2 200 $ à l'inc. de l'immeuble. Seule la marge est un revenu."
          hypotheses={
            <>
              <div className="grid gap-3 sm:grid-cols-3">
                <Champ label="Moyenne avancée par logement par an" hint="Sur tous les logements du scénario, au prorata de l'année"><Num value={data.refacturation.par_logement_annuel} onChange={(v) => modifier((d) => { d.refacturation.par_logement_annuel = v; })} suffixe="$" /></Champ>
                <Champ label="Moyenne avancée par immeuble par an"><Num value={data.refacturation.par_immeuble_annuel} onChange={(v) => modifier((d) => { d.refacturation.par_immeuble_annuel = v; })} suffixe="$" /></Champ>
                <Champ label="Marge"><Num value={data.refacturation.marge_pct} step={0.5} onChange={(v) => modifier((d) => { d.refacturation.marge_pct = v; })} suffixe="%" /></Champ>
              </div>
              <p className={`mt-3 text-[11px] ${FAINT}`}>Montants précis en plus (optionnel) :</p>
              <table className="w-full text-xs">
                <tbody className="divide-y divide-[var(--qg-border)]">
                  {data.refacturation.lignes.map((l) => (
                    <tr key={l.id}>
                      <td className="py-1 pr-2"><input value={l.libelle} placeholder="Ex. honoraires d'avocat — 1660 Saint-Clément" onChange={(e) => modifier((d) => { const x = d.refacturation.lignes.find((y) => y.id === l.id); if (x) x.libelle = e.target.value; })} className={`${INPUT} w-full`} /></td>
                      <td className="w-40 py-1 pr-1"><Num value={l.montant_annuel} onChange={(v) => modifier((d) => { const x = d.refacturation.lignes.find((y) => y.id === l.id); if (x) x.montant_annuel = v; })} suffixe="$/an" title="Montant avancé par année" /></td>
                      <td className="py-1 text-right"><BoutonRetirer onClick={() => modifier((d) => { d.refacturation.lignes = d.refacturation.lignes.filter((y) => y.id !== l.id); })} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <button className="btn-secondary btn-sm mt-2" onClick={() => modifier((d) => { d.refacturation.lignes.push({ id: uid(), libelle: "", montant_annuel: 0 }); })}>
                <Plus className="h-3.5 w-3.5" /> Ajouter une ligne (par immeuble ou au total)
              </button>
            </>
          }
          resultat={
            <ul className="space-y-1">
              <li>{nb(rev.refacturation?.logements_base as number, 1)} logements × {money(data.refacturation.par_logement_annuel)} = {money(rev.refacturation?.avance_logements as number)}</li>
              {data.refacturation.par_immeuble_annuel ? <li>{nb(rev.refacturation?.immeubles_base as number, 1)} immeubles × {money(data.refacturation.par_immeuble_annuel)} = {money(rev.refacturation?.avance_immeubles as number)}</li> : null}
              {(rev.refacturation?.avance_lignes as number) ? <li>Montants précis : {money(rev.refacturation?.avance_lignes as number)}</li> : null}
              <li>Avancé par année : {money(rev.refacturation?.montant_avance as number)} × {pct(data.refacturation.marge_pct)} = <b style={{ color: C.refacturation }}>{money(rev.refacturation?.revenu)}</b></li>
            </ul>
          }
        />

        {/* 5. Construction */}
        <Carte id="sec-construction" num="5." titre="Construction (cost-plus)" hex={C.construction} icon={ICONES.construction} revenu={rev.construction?.revenu} note="Horizon Construction Signature, coûtant + 10 % : les travaux des immeubles en rénovation, puis les rénovations d'appartements au roulement une fois stabilisés. Fonds et hors fonds."
          hypotheses={
            <div className="grid gap-3 sm:grid-cols-3">
              <Champ label="Marge cost-plus"><Num value={data.construction.marge_pct} step={0.5} onChange={(v) => modifier((d) => { d.construction.marge_pct = v; })} suffixe="%" /></Champ>
              <Champ label="Logements rénovés par an (du parc stabilisé)"><Num value={data.construction.pct_logements_renoves_par_an} step={1} onChange={(v) => modifier((d) => { d.construction.pct_logements_renoves_par_an = v; })} suffixe="%" /></Champ>
              <Champ label="Coût moyen d'une rénovation"><Num value={data.construction.cout_reno_logement} onChange={(v) => modifier((d) => { d.construction.cout_reno_logement = v; })} suffixe="$" /></Champ>
            </div>
          }
          resultat={
            <ul className="space-y-1">
              <li className="font-semibold">En rénovation, acquis cette année :</li>
              {((rev.construction?.immeubles_renovation as { nom: string; travaux: number; revenu: number }[]) || []).map((x) => (
                <li key={x.nom} className="pl-3">{x.nom} : travaux {money(x.travaux)} × {pct(data.construction.marge_pct)} = {money(x.revenu)}</li>
              ))}
              {!((rev.construction?.immeubles_renovation as unknown[]) || []).length ? <li className={`pl-3 ${FAINT}`}>aucun</li> : null}
              {((rev.construction?.immeubles_renovation_ignores as string[]) || []).length ? <li className={`pl-3 ${FAINT}`}>En rénovation mais pas acquis cette année (travaux déjà faits) : {(rev.construction?.immeubles_renovation_ignores as string[]).join(", ")}</li> : null}
              <li>Sous-total rénovation : <b>{money(rev.construction?.revenu_stabilisation as number)}</b></li>
              <li className="pt-1 font-semibold">Stabilisés ({((rev.construction?.immeubles_stabilises as { nom: string; nb_logements: number }[]) || []).map((x) => x.nom).join(", ") || "aucun"}) :</li>
              <li className="pl-3">{rev.construction?.logements_stabilises as number} logements × {pct(data.construction.pct_logements_renoves_par_an)} = {nb(rev.construction?.nb_renovations as number)} rénos × {money(data.construction.cout_reno_logement)} = {money(rev.construction?.volume_renovations as number)} × {pct(data.construction.marge_pct)} = <b>{money(rev.construction?.revenu_renovations as number)}</b></li>
              <li className="border-t border-[var(--qg-border)] pt-1">Total : <b style={{ color: C.construction }}>{money(rev.construction?.revenu)}</b></li>
            </ul>
          }
        />

        {/* 6. Maintenance */}
        <Carte id="sec-maintenance" num="6." titre="Maintenance et appels de service" hex={C.maintenance} icon={ICONES.maintenance} revenu={rev.maintenance?.revenu} note="On paie le gars à l'heure et on recharge un taux plus élevé ; les matériaux sont rechargés avec une marge."
          hypotheses={
            <div className="grid gap-3 sm:grid-cols-3">
              <Champ label="Heures par logement par an" hint="Sur tous les logements du scénario, au prorata de l'année"><Num value={data.maintenance.heures_par_logement} step={0.5} onChange={(v) => modifier((d) => { d.maintenance.heures_par_logement = v; })} suffixe="h" /></Champ>
              <Champ label="Matériaux par logement par an"><Num value={data.maintenance.materiaux_par_logement} onChange={(v) => modifier((d) => { d.maintenance.materiaux_par_logement = v; })} suffixe="$" /></Champ>
              <Champ label="Coût horaire payé"><Num value={data.maintenance.cout_horaire} step={0.5} onChange={(v) => modifier((d) => { d.maintenance.cout_horaire = v; })} suffixe="$/h" /></Champ>
              <Champ label="Taux facturé"><Num value={data.maintenance.taux_facture} step={0.5} onChange={(v) => modifier((d) => { d.maintenance.taux_facture = v; })} suffixe="$/h" /></Champ>
              <Champ label="Marge sur matériaux"><Num value={data.maintenance.marge_materiaux_pct} step={0.5} onChange={(v) => modifier((d) => { d.maintenance.marge_materiaux_pct = v; })} suffixe="%" /></Champ>
            </div>
          }
          resultat={
            <ul className="space-y-1">
              <li>{nb(rev.maintenance?.logements_base as number, 1)} logements × {nb(data.maintenance.heures_par_logement, 1)} h = {nb(rev.maintenance?.heures_total as number, 0)} h × ({money(data.maintenance.taux_facture, 2)} − {money(data.maintenance.cout_horaire, 2)}) = <b>{money(rev.maintenance?.marge_heures as number)}</b></li>
              <li>Matériaux : {nb(rev.maintenance?.logements_base as number, 1)} × {money(data.maintenance.materiaux_par_logement)} = {money(rev.maintenance?.materiaux_total as number)} × {pct(data.maintenance.marge_materiaux_pct)} = <b>{money(rev.maintenance?.marge_materiaux as number)}</b></li>
              <li>Volume facturé : {money(rev.maintenance?.volume_facture as number)} · marge nette <b style={{ color: C.maintenance }}>{money(rev.maintenance?.revenu)}</b></li>
            </ul>
          }
        />

        {/* 7. Gestion locative */}
        <Carte id="sec-gestion" num="7." titre="Gestion locative" hex={C.gestion} icon={ICONES.gestion} revenu={rev.gestion?.revenu} note="Pourcentage des loyers bruts, facturé par MGV Développement. Les immeubles « gestion sous-traitée » sont facturés aussi ou non, au choix ; le sous-traitant se paie dans l'onglet Dépenses."
          hypotheses={
            <>
              <div className="flex flex-wrap items-end gap-3">
                <Champ label="Frais de gestion (des loyers bruts)" className="max-w-[180px]"><Num value={data.gestion.taux_pct} step={0.5} onChange={(v) => modifier((d) => { d.gestion.taux_pct = v; })} suffixe="%" /></Champ>
                <label className={`flex items-center gap-1.5 pb-2 text-xs ${MUTED}`}>
                  <input type="checkbox" className="h-4 w-4" style={{ accentColor: C.gestion }} checked={data.gestion.facturer_sous_traites} onChange={(e) => modifier((d) => { d.gestion.facturer_sous_traites = e.target.checked; })} /> Facturer aussi les immeubles sous-traités
                </label>
              </div>
              <div className="mt-4 rounded-xl border border-dashed p-3" style={{ borderColor: teinte(C.gestion_projection, "88") }}>
                <p className="flex items-center gap-2 text-xs font-semibold"><Pastille hex={C.gestion_projection} /> Projection : et si on gérait plus ?</p>
                <div className="mt-2 flex flex-wrap items-end gap-3">
                  <Champ label="Loyers bruts additionnels par mois" className="w-48"><Num value={data.gestion.loyers_additionnels_mensuels} onChange={(v) => modifier((d) => { d.gestion.loyers_additionnels_mensuels = v; })} suffixe="$" /></Champ>
                  <label className={`flex items-center gap-1.5 pb-2 text-xs ${MUTED}`}>
                    <input type="checkbox" className="h-4 w-4" style={{ accentColor: C.gestion_projection }} checked={data.gestion.inclure_projection} onChange={(e) => modifier((d) => { d.gestion.inclure_projection = e.target.checked; })} /> Inclure dans les totaux
                  </label>
                </div>
              </div>
            </>
          }
          resultat={
            <ul className="space-y-1">
              <li>À l&apos;interne ({rev.gestion?.nb_internes as number}) : {money(rev.gestion?.loyers_internes_annuels as number)} / an</li>
              <li>Sous-traités ({rev.gestion?.nb_sous_traites as number}) : {money(rev.gestion?.loyers_sous_traites_annuels as number)} / an {data.gestion.facturer_sous_traites ? "(facturés)" : "(non facturés)"}</li>
              <li>Base {money(rev.gestion?.base_annuelle as number)} × {pct(data.gestion.taux_pct)} = <b style={{ color: C.gestion }}>{money(rev.gestion?.revenu)}</b></li>
              <li><Pastille hex={C.gestion_projection} className="mr-1" /> Projection : +{money(data.gestion.loyers_additionnels_mensuels)} / mois → <b style={{ color: C.gestion_projection }}>{money(rev.gestion_projection?.revenu)}</b> / an {data.gestion.inclure_projection ? "(inclus)" : "(hors totaux)"}</li>
            </ul>
          }
        />

        {/* 8. Location */}
        <Carte id="sec-location" num="8." titre="Frais de location" hex={C.location} icon={ICONES.location} revenu={rev.location?.revenu} note="Frais chargé quand un logement ou une chambre est reloué, sur les portes gérées à l'interne. Le nombre de relocations vient du taux de roulement, ou tu le saisis."
          hypotheses={
            <div className="grid gap-3 sm:grid-cols-3">
              <Champ label="Frais par logement"><Num value={data.location.frais_logement} onChange={(v) => modifier((d) => { d.location.frais_logement = v; })} suffixe="$" /></Champ>
              <Champ label="Frais par chambre"><Num value={data.location.frais_chambre} onChange={(v) => modifier((d) => { d.location.frais_chambre = v; })} suffixe="$" /></Champ>
              <Champ label="Roulement des logements par an"><Num value={data.location.taux_roulement_pct} step={1} onChange={(v) => modifier((d) => { d.location.taux_roulement_pct = v; })} suffixe="%" /></Champ>
              <Champ label="Roulement des chambres par an"><Num value={data.location.taux_roulement_chambres_pct} step={1} onChange={(v) => modifier((d) => { d.location.taux_roulement_chambres_pct = v; })} suffixe="%" /></Champ>
              <Champ label={`Relocations de logements (calculé : ${rev.location?.relocations_logements_calculees as number})`} hint="Laisse vide pour utiliser le calcul au roulement">
                <input type="number" min={0} step={1} value={data.location.nb_relocations_logements ?? ""} placeholder={String(rev.location?.relocations_logements_calculees ?? 0)} onChange={(e) => modifier((d) => { d.location.nb_relocations_logements = e.target.value === "" ? null : Math.max(0, Math.round(Number(e.target.value))); })} className={`${INPUT} w-full text-right tabular-nums`} />
              </Champ>
              <Champ label={`Relocations de chambres (calculé : ${rev.location?.relocations_chambres_calculees as number})`} hint="Laisse vide pour utiliser le calcul au roulement">
                <input type="number" min={0} step={1} value={data.location.nb_relocations_chambres ?? ""} placeholder={String(rev.location?.relocations_chambres_calculees ?? 0)} onChange={(e) => modifier((d) => { d.location.nb_relocations_chambres = e.target.value === "" ? null : Math.max(0, Math.round(Number(e.target.value))); })} className={`${INPUT} w-full text-right tabular-nums`} />
              </Champ>
            </div>
          }
          resultat={
            <ul className="space-y-1">
              <li>{rev.location?.logements_location as number} logements (hors unités louées en chambres) et {rev.location?.chambres_internes as number} chambres, gérés à l&apos;interne</li>
              <li>{rev.location?.relocations_logements as number} × {money(data.location.frais_logement)} + {rev.location?.relocations_chambres as number} × {money(data.location.frais_chambre)} = <b style={{ color: C.location }}>{money(rev.location?.revenu)}</b></li>
            </ul>
          }
        />

        {/* Part des gains */}
        <Carte id="sec-part_des_gains" titre="Part des gains — en parts, pas en cash" hex={C.part_des_gains} icon={PiggyBank} revenu={pg.part_nous} revenuLabel="pour nos 3 holdings, en parts" note="Document, p. 7 : les premiers 7 % du gain aux investisseurs, les 3 % suivants à nous, le reste 70 / 30. Payé en nouvelles parts du fonds (10 % à chaque holding), donc hors des revenus en cash."
          hypotheses={
            <div className="grid gap-3 sm:grid-cols-2">
              <Champ label="Rendement de l'année (sur la VAN)"><Num value={data.part_des_gains.rendement_pct} step={0.5} onChange={(v) => modifier((d) => { d.part_des_gains.rendement_pct = v; })} suffixe="%" /></Champ>
              <Champ label="Premiers % aux investisseurs"><Num value={data.part_des_gains.seuil_investisseurs_pct} step={0.5} onChange={(v) => modifier((d) => { d.part_des_gains.seuil_investisseurs_pct = v; })} suffixe="%" /></Champ>
              <Champ label="% suivants à nous"><Num value={data.part_des_gains.tranche_nous_pct} step={0.5} onChange={(v) => modifier((d) => { d.part_des_gains.tranche_nous_pct = v; })} suffixe="%" /></Champ>
              <Champ label="Notre part du reste"><Num value={data.part_des_gains.part_nous_pct} step={1} onChange={(v) => modifier((d) => { d.part_des_gains.part_nous_pct = v; })} suffixe="%" /></Champ>
            </div>
          }
          resultat={
            <ul className="space-y-1">
              <li className="flex justify-between gap-2"><span>Gain de l&apos;année ({pct(pg.rendement_pct)} de {money(pg.van)})</span><span className="tabular-nums">{money(pg.gain)}</span></li>
              <li className="flex justify-between gap-2"><span>1. Aux investisseurs</span><span className="tabular-nums">{money(pg.tranche_investisseurs)}</span></li>
              <li className="flex justify-between gap-2"><span>2. À nous</span><span className="tabular-nums">{money(pg.tranche_nous)}</span></li>
              <li className="flex justify-between gap-2"><span>3. Le reste, {pct(data.part_des_gains.part_nous_pct, 0)} à nous</span><span className="tabular-nums">{money(pg.reste)}</span></li>
              <li className="flex justify-between gap-2 border-t border-[var(--qg-border)] pt-1 font-semibold"><span>Nous ({pct(pg.pct_du_gain_nous, 0)} du gain)</span><b className="tabular-nums" style={{ color: C.part_des_gains }}>{money(pg.part_nous)}</b></li>
              <li className="flex justify-between gap-2"><span>Par holding</span><span className="tabular-nums">{money(pg.par_holding)}</span></li>
              <li className="flex justify-between gap-2"><span>Investisseurs</span><span className="tabular-nums">{money(pg.part_investisseurs)}</span></li>
            </ul>
          }
        />
      </div>
    </div>
  );
}

// ─── Onglet Performance : hypothèses de projection (2026-11-06) ──────────
// Phil : « il faut que tout ça soit annualisé » — les hypothèses vivent dans le scénario (visibles,
// modifiables avec « Modifier »), la projection est calculée côté serveur (PerformanceTab).

function HypothesesProjection({ data, modifier, referentiel }: { data: Data; modifier: (fn: (d: Data) => void) => void; referentiel?: Referentiel }) {
  const p = data.projection;
  if (!p) return null;
  return (
    <div className="mb-4">
      <Carte id="sec-projection" titre="Hypothèses de projection" hex={C.fonds} icon={TrendingUp} note={referentiel?.projection_note || "Année par année selon le document du fonds : gain = VAN de fin − VAN de début ; rendement du fonds = gain ÷ VAN de départ ; partage en parts. Détention simple, sans refinancement."}
        hypotheses={
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            <Champ label="Croissance des loyers, par an" hint="Même défaut que le moteur de Prospection (3 %)"><Num value={p.croissance_loyers_pct} step={0.25} onChange={(v) => modifier((d) => { d.projection.croissance_loyers_pct = v; })} suffixe="%" /></Champ>
            <Champ label="Croissance des dépenses, par an" hint="Taxes, assurances, énergie, conciergerie et entretien du barème ; inoccupation, gestion et autres normalisations suivent les loyers"><Num value={p.croissance_depenses_pct} step={0.25} onChange={(v) => modifier((d) => { d.projection.croissance_depenses_pct = v; })} suffixe="%" /></Champ>
            <Champ label="Horizon" hint="De 1 à 30 ans à partir de l'année du scénario"><Num value={p.horizon_annees} step={1} onChange={(v) => modifier((d) => { d.projection.horizon_annees = Math.min(30, Math.max(1, Math.round(v))); })} suffixe="ans" /></Champ>
            <Champ label="Taux de cap de sortie" hint="0 = le taux de cap du rapport de chaque immeuble"><Num value={p.taux_cap_sortie_pct} step={0.05} onChange={(v) => modifier((d) => { d.projection.taux_cap_sortie_pct = v; })} suffixe="%" /></Champ>
            <Champ label="Taux au renouvellement des prêts" hint="Appliqué à l'échéance du terme de chaque prêt Kratos et aux prêts intérêts seulement convertis ; 0 = taux actuel conservé"><Num value={p.taux_renouvellement_pct} step={0.05} onChange={(v) => modifier((d) => { d.projection.taux_renouvellement_pct = v; })} suffixe="%" /></Champ>
            <Champ label="Taux par défaut d'une dette sans prêt Kratos"><Num value={p.taux_dette_defaut_pct} step={0.05} onChange={(v) => modifier((d) => { d.projection.taux_dette_defaut_pct = v; })} suffixe="%" /></Champ>
            <Champ label="Amortissement par défaut"><Num value={p.amortissement_defaut_ans} step={1} onChange={(v) => modifier((d) => { d.projection.amortissement_defaut_ans = Math.max(1, Math.round(v)); })} suffixe="ans" /></Champ>
            <Champ label="Prix d'une part au départ" hint="Document p. 8 : 10 $ la part"><Num value={p.prix_part_depart} step={0.5} onChange={(v) => modifier((d) => { d.projection.prix_part_depart = v; })} suffixe="$" /></Champ>
            <Champ label="Parts de nos holdings au départ" hint="Part de la VAN de départ détenue par nos 3 holdings comme investisseurs (p. 9 : leur argent est traité comme celui d'un investisseur)"><Num value={p.part_nos_holdings_depart_pct} step={1} onChange={(v) => modifier((d) => { d.projection.part_nos_holdings_depart_pct = Math.min(100, v); })} suffixe="%" /></Champ>
          </div>
        }
      />
    </div>
  );
}

// ─── Onglet Dépenses ─────────────────────────────────────────────────────

function DepensesTab({ data, res, referentiel, modifier }: { data: Data; res: Resultats; referentiel?: Referentiel; modifier: (fn: (d: Data) => void) => void }) {
  const cats = referentiel?.categories_frais_fixes || [];
  const dep = res.depenses;
  const salairesPostes = dep.salaires.reduce((a, s) => a + s.total, 0);
  const sousTraites = (Object.fromEntries(res.revenus.map((s) => [s.key, s])) as Record<string, SectionRevenu>).gestion?.sous_traites as string[] | undefined;
  return (
    <div className="space-y-4">
      <Carte id="sec-frais-fixes" titre="Frais fixes non refacturables" hex={C.frais_fixes} icon={Receipt} revenu={dep.total_frais_fixes} note="Seulement ce qui n'est pas rechargé aux clients : adhésions et abonnements, activités, représentation, honoraires non refacturables, fournitures, déplacements, informatique."
        hypotheses={
          <>
            <table className="w-full text-xs">
              <thead className={`text-left ${MUTED}`}>
                <tr>
                  <th className="py-1">Catégorie</th>
                  <th className="py-1">Libellé</th>
                  <th className="py-1 text-right">Montant</th>
                  <th className="py-1">Période</th>
                  <th className="py-1 text-right">Par an</th>
                  <th />
                </tr>
              </thead>
              <tbody className="divide-y divide-[var(--qg-border)]">
                {data.depenses.frais_fixes.map((l) => (
                  <tr key={l.id}>
                    <td className="py-1 pr-2">
                      <span className="flex items-center gap-2">
                        <Pastille hex={CAT_COULEURS[l.categorie] || "#94a3b8"} />
                        <select value={l.categorie} onChange={(e) => modifier((d) => { const x = d.depenses.frais_fixes.find((y) => y.id === l.id); if (x) x.categorie = e.target.value; })} className={`${INPUT} max-w-[260px]`}>
                          {cats.map((c) => (
                            <option key={c.key} value={c.key}>{c.label}</option>
                          ))}
                        </select>
                      </span>
                    </td>
                    <td className="py-1 pr-2"><input value={l.libelle} placeholder="Ex. CORPIQ, Microsoft 365…" onChange={(e) => modifier((d) => { const x = d.depenses.frais_fixes.find((y) => y.id === l.id); if (x) x.libelle = e.target.value; })} className={`${INPUT} w-full`} /></td>
                    <td className="w-36 py-1 pr-2"><Num value={l.montant} onChange={(v) => modifier((d) => { const x = d.depenses.frais_fixes.find((y) => y.id === l.id); if (x) x.montant = v; })} suffixe="$" /></td>
                    <td className="py-1 pr-2">
                      <select value={l.periode} onChange={(e) => modifier((d) => { const x = d.depenses.frais_fixes.find((y) => y.id === l.id); if (x) x.periode = e.target.value as FraisFixe["periode"]; })} className={INPUT}>
                        <option value="mois">par mois</option>
                        <option value="an">par an</option>
                      </select>
                    </td>
                    <td className="py-1 text-right tabular-nums">{money(l.montant * (l.periode === "mois" ? 12 : 1))}</td>
                    <td className="py-1 pl-1 text-right"><BoutonRetirer onClick={() => modifier((d) => { d.depenses.frais_fixes = d.depenses.frais_fixes.filter((y) => y.id !== l.id); })} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
            <button className="btn-secondary btn-sm mt-2" onClick={() => modifier((d) => { d.depenses.frais_fixes.push({ id: uid(), categorie: "autre", libelle: "", montant: 0, periode: "an" }); })}>
              <Plus className="h-3.5 w-3.5" /> Ajouter un frais fixe
            </button>
          </>
        }
        resultat={
          <ul className="space-y-1">
            {dep.frais_fixes_par_categorie.map((c) => (
              <li key={c.categorie} className="flex items-center justify-between gap-2">
                <span className="flex items-center gap-2"><Pastille hex={CAT_COULEURS[c.categorie] || "#94a3b8"} /> {c.label}</span>
                <span className="tabular-nums">{money(c.montant)}</span>
              </li>
            ))}
            <li className="flex justify-between border-t border-[var(--qg-border)] pt-1 font-semibold"><span>Total</span><span className="tabular-nums" style={{ color: C.frais_fixes }}>{money(dep.total_frais_fixes)}</span></li>
          </ul>
        }
      />

      <div className="grid gap-4 xl:grid-cols-2">
        <Carte id="sec-salaires" titre="Salaires des postes" hex={C.salaires} icon={Users} revenu={salairesPostes} note={referentiel?.charges_sociales_note}
          hypotheses={
            <>
              <Champ label="Charges sociales de l'employeur (en plus du salaire brut)" className="max-w-[220px]"><Num value={data.depenses.charges_sociales_pct} step={0.5} onChange={(v) => modifier((d) => { d.depenses.charges_sociales_pct = v; })} suffixe="%" /></Champ>
              <table className="mt-3 w-full text-xs">
                <thead className={`text-left ${MUTED}`}>
                  <tr>
                    <th className="py-1">Poste</th>
                    <th className="py-1 text-right">Salaire brut / an</th>
                    <th />
                  </tr>
                </thead>
                <tbody className="divide-y divide-[var(--qg-border)]">
                  {data.depenses.salaires.map((s) => (
                    <tr key={s.id}>
                      <td className="py-1 pr-2"><input value={s.poste} onChange={(e) => modifier((d) => { const x = d.depenses.salaires.find((y) => y.id === s.id); if (x) x.poste = e.target.value; })} className={`${INPUT} w-full`} /></td>
                      <td className="w-40 py-1 pr-1"><Num value={s.salaire_annuel} onChange={(v) => modifier((d) => { const x = d.depenses.salaires.find((y) => y.id === s.id); if (x) x.salaire_annuel = v; })} suffixe="$" /></td>
                      <td className="py-1 text-right"><BoutonRetirer onClick={() => modifier((d) => { d.depenses.salaires = d.depenses.salaires.filter((y) => y.id !== s.id); })} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <button className="btn-secondary btn-sm mt-2" onClick={() => modifier((d) => { d.depenses.salaires.push({ id: uid(), poste: "", salaire_annuel: 0 }); })}>
                <Plus className="h-3.5 w-3.5" /> Ajouter un poste
              </button>
            </>
          }
          resultat={
            <ul className="space-y-1">
              {dep.salaires.map((s, i) => (
                <li key={i} className="flex justify-between gap-2"><span className="truncate">{s.poste || "Poste"}</span><span className="tabular-nums">{money(s.brut)} + {money(s.charges)} = <b>{money(s.total)}</b></span></li>
              ))}
              <li className="flex justify-between border-t border-[var(--qg-border)] pt-1 font-semibold"><span>Total (avec charges)</span><span className="tabular-nums" style={{ color: C.salaires }}>{money(salairesPostes)}</span></li>
            </ul>
          }
        />

        <Carte id="sec-associes" titre="Associés : salaire et dividendes" hex={C.associes} icon={PiggyBank} revenu={dep.total_associes_salaires} note="Le salaire (avec charges) est une dépense déductible ; les dividendes ne le sont pas : ils se versent sur le bénéfice après impôts (section suivante), affichés à part dans le tableau de bord."
          hypotheses={
            <table className="w-full text-xs">
              <thead className={`text-left ${MUTED}`}>
                <tr>
                  <th className="py-1">Associé</th>
                  <th className="py-1 text-right">Salaire brut / an</th>
                  <th className="py-1 text-right">Dividendes / an</th>
                  <th className="py-1 text-right">Charges ({pct(data.depenses.charges_sociales_pct)})</th>
                  <th className="py-1 text-right">Coût salaire</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[var(--qg-border)]">
                {data.depenses.associes.map((a) => (
                  <tr key={a.id}>
                    <td className="py-1 pr-2"><input value={a.nom} onChange={(e) => modifier((d) => { const x = d.depenses.associes.find((y) => y.id === a.id); if (x) x.nom = e.target.value; })} className={`${INPUT} w-full`} /></td>
                    <td className="w-40 py-1 pr-2"><Num value={a.salaire_annuel} onChange={(v) => modifier((d) => { const x = d.depenses.associes.find((y) => y.id === a.id); if (x) x.salaire_annuel = v; })} suffixe="$" /></td>
                    <td className="w-40 py-1"><Num value={a.dividendes_annuels} onChange={(v) => modifier((d) => { const x = d.depenses.associes.find((y) => y.id === a.id); if (x) x.dividendes_annuels = v; })} suffixe="$" /></td>
                    <td className={`py-1 text-right tabular-nums ${MUTED}`}>{money(a.salaire_annuel * data.depenses.charges_sociales_pct / 100)}</td>
                    <td className="py-1 text-right font-semibold tabular-nums">{money(a.salaire_annuel * (1 + data.depenses.charges_sociales_pct / 100))}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          }
          resultat={
            <ul className="space-y-1">
              {dep.associes.map((a, i) => (
                <li key={i} className="flex justify-between gap-2"><span>{a.nom}</span><span className="tabular-nums">salaire {money(a.salaire_brut)} + charges {money(a.charges)} = <b>{money(a.cout_salaire)}</b> · <span style={{ color: C.dividendes }}>dividendes {money(a.dividendes)}</span></span></li>
              ))}
              <li className="flex justify-between border-t border-[var(--qg-border)] pt-1 font-semibold"><span>Salaires + charges sociales {pct(data.depenses.charges_sociales_pct)} (dépense)</span><span className="tabular-nums" style={{ color: C.associes }}>{money(dep.total_associes_salaires)}</span></li>
              <li className="flex justify-between font-semibold"><span>Dividendes (sur le bénéfice après impôts)</span><span className="tabular-nums" style={{ color: C.dividendes }}>{money(dep.total_dividendes)}</span></li>
            </ul>
          }
        />

        <Carte id="sec-impots" titre="Impôts de la société" hex={C.impots} icon={Landmark} revenu={dep.impots.total} revenuLabel="d'impôts par an" note={referentiel?.impots_note || "Impôt sur le bénéfice avant impôts, par paliers ; les dividendes se versent après."}
          hypotheses={
            <div className="grid gap-3 sm:grid-cols-3">
              <Champ label="Taux jusqu'au plafond" hint="Taux des PME : fédéral 9 % + Québec 3,2 % = 12,2 % si admissible (sinon 20,5 % au Québec)"><Num value={data.depenses.impots.taux_pct} step={0.1} onChange={(v) => modifier((d) => { d.depenses.impots.taux_pct = Math.min(100, v); })} suffixe="%" /></Champ>
              <Champ label="Plafond du premier taux" hint="500 000 $ de revenu actif admissible ; 0 = un seul taux"><Num value={data.depenses.impots.plafond} step={1000} onChange={(v) => modifier((d) => { d.depenses.impots.plafond = v; })} suffixe="$" /></Champ>
              <Champ label="Taux au-delà" hint="Taux général : fédéral 15 % + Québec 11,5 % = 26,5 %"><Num value={data.depenses.impots.taux_au_dela_pct} step={0.1} onChange={(v) => modifier((d) => { d.depenses.impots.taux_au_dela_pct = Math.min(100, v); })} suffixe="%" /></Champ>
            </div>
          }
          resultat={
            <ul className="space-y-1">
              <li className="flex justify-between gap-2"><span>Bénéfice avant impôts (revenus − dépenses déductibles)</span><b className={`tabular-nums ${res.totaux.benefice < 0 ? "text-rose-400" : ""}`}>{money(res.totaux.benefice)}</b></li>
              {res.totaux.benefice < 0 ? <li className={FAINT}>Perte : aucun impôt cette année.</li> : null}
              <li className="flex justify-between gap-2"><span>{money(dep.impots.tranche_1_base)} × {pct(dep.impots.taux_pct)}</span><span className="tabular-nums">{money(dep.impots.tranche_1)}</span></li>
              {dep.impots.tranche_2_base > 0 ? <li className="flex justify-between gap-2"><span>{money(dep.impots.tranche_2_base)} au-delà du plafond × {pct(dep.impots.taux_au_dela_pct)}</span><span className="tabular-nums">{money(dep.impots.tranche_2)}</span></li> : null}
              <li className="flex justify-between gap-2 border-t border-[var(--qg-border)] pt-1 font-semibold"><span>Impôts (taux effectif {pct(dep.impots.taux_effectif_pct)})</span><span className="tabular-nums" style={{ color: C.impots }}>{money(dep.impots.total)}</span></li>
              <li className="flex justify-between gap-2 font-semibold"><span>Bénéfice après impôts</span><span className={`tabular-nums ${res.totaux.benefice_apres_impots < 0 ? "text-rose-400" : ""}`}>{money(res.totaux.benefice_apres_impots)}</span></li>
              <li className="flex justify-between gap-2"><span>− Dividendes des associés</span><span className="tabular-nums" style={{ color: C.dividendes }}>{money(res.totaux.dividendes)}</span></li>
              <li className="flex justify-between gap-2 border-t border-[var(--qg-border)] pt-1 font-semibold"><span>Bénéfice retenu dans la société</span><span className={`tabular-nums ${res.totaux.benefice_retenu < 0 ? "text-rose-400" : ""}`}>{money(res.totaux.benefice_retenu)}</span></li>
            </ul>
          }
        />

        <Carte id="sec-sous-traitance" titre="Sous-traitant de gestion" hex={C.sous_traitance} icon={Home} revenu={dep.sous_traitance_gestion} note="Pour les immeubles marqués « gestion sous-traitée » dans leur fiche : on paie le sous-traitant un pourcentage de leurs loyers bruts."
          hypotheses={<Champ label="Rémunération du sous-traitant (des loyers bruts des immeubles sous-traités)" className="max-w-[260px]"><Num value={data.depenses.sous_traitance_gestion_pct} step={0.5} onChange={(v) => modifier((d) => { d.depenses.sous_traitance_gestion_pct = v; })} suffixe="%" /></Champ>}
          resultat={
            <ul className="space-y-1">
              <li>Immeubles sous-traités : {sousTraites?.length ? sousTraites.join(", ") : "aucun"}</li>
              <li>Loyers bruts : {money(dep.loyers_sous_traites_annuels)} / an × {pct(data.depenses.sous_traitance_gestion_pct)} = <b style={{ color: C.sous_traitance }}>{money(dep.sous_traitance_gestion)}</b></li>
            </ul>
          }
        />
        <Carte id="sec-agents-location" titre="Agents de location" hex={C.location} icon={KeyRound} revenu={dep.agents_location} note="Payés par logement ou chambre loué(e). Le nombre de relocations vient de la section 8 (Location) de l'onglet Revenus."
          hypotheses={
            <div className="grid gap-3 sm:grid-cols-2">
              <Champ label="Par logement loué"><Num value={data.depenses.agents_location.par_logement} onChange={(v) => modifier((d) => { d.depenses.agents_location.par_logement = v; })} suffixe="$" /></Champ>
              <Champ label="Par chambre louée"><Num value={data.depenses.agents_location.par_chambre} onChange={(v) => modifier((d) => { d.depenses.agents_location.par_chambre = v; })} suffixe="$" /></Champ>
            </div>
          }
          resultat={
            <ul className="space-y-1">
              <li>{dep.relocations_logements} logements × {money(data.depenses.agents_location.par_logement)} + {dep.relocations_chambres} chambres × {money(data.depenses.agents_location.par_chambre)} = <b style={{ color: C.location }}>{money(dep.agents_location)}</b></li>
            </ul>
          }
        />
      </div>

      <div className={`${CARD} flex flex-wrap items-center justify-between gap-3 p-4 text-sm`} style={{ borderLeft: `4px solid ${C.depenses}` }}>
        <span className="flex items-center gap-2 font-semibold"><Wallet className="h-4 w-4" style={{ color: C.depenses }} /> Total des dépenses</span>
        <span className="text-lg font-bold tabular-nums" style={{ color: C.depenses }}>{money(dep.total)} / an</span>
        <span className={`text-xs ${MUTED}`}>frais fixes {money(dep.total_frais_fixes)} · masse salariale {money(dep.total_masse_salariale)} (dont charges {money(dep.total_charges_sociales)}) · sous-traitant {money(dep.sous_traitance_gestion)} · agents de location {money(dep.agents_location)}</span>
      </div>
    </div>
  );
}
