/* Comptabilité → Paiements : types et appels de l'API /api/v1/paiements
   (l'équivalent de Plooto dans Kratos, Steven 2026-10-04). */

import { authedFetch } from "@/lib/auth";

const API = "/api/v1/paiements";

// ── Types ─────────────────────────────────────────────────────────────

export type DeuxFacteurs = {
  actif: boolean;
  active_le: string | null;
  confirme_jusqu_a: string | null;
};

export type Moi = {
  user_id: number;
  peut_approuver: boolean;
  deux_facteurs: DeuxFacteurs;
};

export type EntreprisePaiement = {
  entreprise_id: number;
  name: string;
  qbo_connectee: boolean;
  qbo_company_name: string | null;
  depot_direct_pret: boolean;
  lots_a_approuver: number;
  comptes_a_approuver: number;
};

export type CompteResume = {
  statut: StatutCompte;
  institution: string;
  transit: string;
  compte_fin: string;
  approuve_le: string | null;
  approuve_par?: string | null;
};

export type Facture = {
  qbo_bill_id: string;
  fournisseur_id: string | null;
  fournisseur: string;
  numero: string | null;
  date: string | null;
  echeance: string | null;
  total: number;
  solde: number;
  devise: string;
  lien_qbo: string | null;
  compte: CompteResume | null;
  lot_id: number | null;
  achat_construction_id: number | null;
  payable: boolean;
};

export type FacturesAPayer = {
  entreprise: { entreprise_id: number; name: string; qbo_company_name: string | null };
  factures: Facture[];
  premiere_date: string;
};

export type StatutCompte = "en_attente" | "approuve" | "remplace" | "refuse" | "retire";

export type CompteFournisseur = {
  id: number;
  entreprise_id: number;
  fournisseur_id: string;
  fournisseur: string;
  institution: string;
  transit: string;
  compte_fin: string;
  source: string | null;
  statut: StatutCompte;
  propose_par_id: number | null;
  propose_par: string | null;
  propose_le: string | null;
  decide_par: string | null;
  decide_le: string | null;
  motif: string | null;
};

export type Fournisseur = { id: string; nom: string };

export type Reglages = {
  entreprise_id: number;
  numero_organisme: string | null;
  centre_traitement: string;
  code_transaction: string;
  nom_court: string | null;
  nom_long: string | null;
  retour_institution: string | null;
  retour_transit: string | null;
  retour_compte: string | null;
  approbations_requises: number;
  prochain_numero_fichier: number;
  qbo_compte_banque_id: string | null;
  qbo_compte_banque_nom: string | null;
  manque: string[];
  modifie_le: string | null;
  comptes_banque_qbo: { id: string; nom: string }[];
  erreur_qbo: string | null;
};

export type StatutLot =
  | "brouillon"
  | "soumis"
  | "approuve"
  | "fichier_cree"
  | "transmis"
  | "paye"
  | "refuse"
  | "annule";

export type LotResume = {
  id: number;
  entreprise_id: number;
  statut: StatutLot;
  statut_libelle: string;
  date_paiement: string;
  total: number;
  nb_lignes: number;
  note: string | null;
  approbations_requises: number;
  cree_par: string | null;
  cree_le: string | null;
  soumis_le: string | null;
  approuve_le: string | null;
  fichier_numero: number | null;
  fichier_cree_le: string | null;
  transmis_le: string | null;
  paye_le: string | null;
  annule_le: string | null;
};

export type LigneLot = {
  id: number;
  qbo_bill_id: string;
  fournisseur_id: string;
  fournisseur: string;
  numero_facture: string | null;
  date_facture: string | null;
  echeance: string | null;
  solde: number;
  montant: number;
  lien_qbo: string | null;
  compte: CompteResume | null;
  qbo_bill_payment_id: string | null;
  lien_paiement_qbo: string | null;
  erreur_qbo: string | null;
};

export type Evenement = {
  action: string;
  detail: string | null;
  par: string | null;
  le: string | null;
  lot_id?: number | null;
};

export type ActionsLot = {
  modifier: boolean;
  soumettre: boolean;
  remettre_en_brouillon: boolean;
  approuver: boolean;
  refuser: boolean;
  creer_fichier: boolean;
  marquer_transmis: boolean;
  enregistrer_qbo: boolean;
  annuler: boolean;
};

export type LotDetail = LotResume & {
  soumis_par: string | null;
  fichier_date: string | null;
  fichier_cree_par: string | null;
  transmis_par: string | null;
  annule_par: string | null;
  motif_annulation: string | null;
  lignes: LigneLot[];
  decisions: { par: string | null; decision: string; commentaire: string | null; le: string | null }[];
  journal: Evenement[];
  actions: ActionsLot;
  a_prepare: boolean;
};

export type FichierDepot = {
  nom: string;
  contenu: string;
  resume: {
    numero_fichier: number;
    numero_organisme: string;
    date_creation: string;
    nombre: number;
    total: number;
    depots: {
      beneficiaire: string;
      montant: number;
      date_depot: string;
      institution: string;
      transit: string;
      compte_fin: string;
      information: string;
      reference: string;
    }[];
  };
};

// ── Appels ────────────────────────────────────────────────────────────

/** Erreur de l'API : message à afficher tel quel + données en plus
 *  (`deux_facteurs`, `fournisseurs`, `manque`…). */
export class ErreurApi extends Error {
  statut: number;
  donnees: Record<string, unknown>;

  constructor(message: string, statut: number, donnees: Record<string, unknown>) {
    super(message);
    this.statut = statut;
    this.donnees = donnees;
  }
}

async function lire<T>(res: Response): Promise<T> {
  if (res.ok) return (await res.json()) as T;
  let donnees: Record<string, unknown> = {};
  try {
    donnees = ((await res.json()) as Record<string, unknown>) ?? {};
  } catch {
    /* corps vide ou non JSON */
  }
  const detail = donnees.detail;
  const message =
    typeof detail === "string" && detail
      ? detail
      : Array.isArray(detail) && typeof detail[0]?.msg === "string"
        ? String(detail[0].msg)
        : res.status === 403
          ? "Accès refusé."
          : `Erreur ${res.status}`;
  throw new ErreurApi(message, res.status, donnees);
}

export async function obtenir<T>(chemin: string): Promise<T> {
  return lire<T>(await authedFetch(`${API}${chemin}`));
}

export async function envoyer<T>(
  chemin: string,
  corps: Record<string, unknown> = {},
  methode: "POST" | "PUT" = "POST"
): Promise<T> {
  return lire<T>(
    await authedFetch(`${API}${chemin}`, { method: methode, body: JSON.stringify(corps) })
  );
}

export function message(ex: unknown, defaut = "Erreur inattendue."): string {
  return ex instanceof Error && ex.message ? ex.message : defaut;
}

/** Télécharge un texte tel quel (le fichier de dépôt garde ses fins de
 *  ligne CRLF : ne pas l'ouvrir ni l'enregistrer dans un éditeur). */
export function telecharger(nom: string, contenu: string): void {
  const url = URL.createObjectURL(new Blob([contenu], { type: "text/plain" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = nom;
  document.body.appendChild(a);
  a.click();
  a.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 2000);
}

// ── Affichage ─────────────────────────────────────────────────────────

const ARGENT = new Intl.NumberFormat("fr-CA", { style: "currency", currency: "CAD" });

export function argent(n: number): string {
  return ARGENT.format(n);
}

/** « 2026-10-07 » → « 7 oct. 2026 » (date seule, sans décalage de fuseau). */
export function jour(iso: string | null | undefined): string {
  if (!iso) return "—";
  const [a, m, j] = iso.slice(0, 10).split("-").map(Number);
  if (!a || !m || !j) return iso;
  return new Date(a, m - 1, j).toLocaleDateString("fr-CA", {
    day: "numeric",
    month: "short",
    year: "numeric"
  });
}

/** Horodatage → « 5 oct. 2026, 09 h 12 » (heure de Montréal). */
export function moment(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString("fr-CA", {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "America/Toronto"
  });
}

/** Aujourd'hui (Montréal) au format AAAA-MM-JJ. */
export function aujourdhui(): string {
  return new Date().toLocaleDateString("en-CA", { timeZone: "America/Toronto" });
}

/** « 1 234,56 » ou « 1234.56 » → 1234.56 (NaN si illisible). */
export function lireMontant(s: string): number {
  const net = s.replace(/[\s $]/g, "").replace(",", ".");
  return /^\d+(\.\d{0,2})?$/.test(net) ? Number(net) : NaN;
}

export function compteMasque(c: { institution: string; transit: string; compte_fin: string }): string {
  return `${c.institution}-${c.transit} · •••${c.compte_fin}`;
}

export const CARTE = { borderColor: "var(--qg-border)", backgroundColor: "var(--qg-card-bg)" };

/** `.btn-outline-rose` impose son padding après `.btn-xs`/`.btn-sm` dans
 *  globals.css : ces deux tailles le ramènent à celles des autres boutons. */
export const ROUGE_XS = "btn-outline-rose !gap-1 !rounded-lg !px-2.5 !py-1 !text-xs";
export const ROUGE_SM = "btn-outline-rose !rounded-lg !px-3 !py-1.5 !text-sm";

export const BADGE_LOT: Record<StatutLot, string> = {
  brouillon: "badge-neutral",
  soumis: "badge-amber",
  approuve: "badge-sky",
  fichier_cree: "badge-violet",
  transmis: "badge-blue",
  paye: "badge-emerald",
  refuse: "badge-rose",
  annule: "badge-neutral"
};

export const COMPTE: Record<StatutCompte, { libelle: string; badge: string }> = {
  en_attente: { libelle: "À approuver", badge: "badge-amber" },
  approuve: { libelle: "Approuvé", badge: "badge-emerald" },
  remplace: { libelle: "Remplacé", badge: "badge-neutral" },
  refuse: { libelle: "Refusé", badge: "badge-rose" },
  retire: { libelle: "Retiré", badge: "badge-neutral" }
};

export const ACTIONS: Record<string, string> = {
  compte_propose: "Coordonnées bancaires saisies",
  compte_revele: "Numéro de compte complet consulté",
  compte_approuve: "Coordonnées bancaires approuvées",
  compte_refuse: "Coordonnées bancaires refusées",
  compte_retire: "Coordonnées bancaires retirées",
  lot_cree: "Lot créé",
  lot_modifie: "Lot modifié",
  lot_soumis: "Lot soumis aux approbateurs",
  lot_en_brouillon: "Lot remis en brouillon",
  lot_approuve: "Lot approuvé",
  lot_refuse: "Lot refusé",
  lot_annule: "Lot annulé",
  date_modifiee: "Date du dépôt modifiée",
  fichier_cree: "Fichier de dépôt créé",
  fichier_retelecharge: "Fichier téléchargé de nouveau",
  fichier_transmis: "Fichier transmis à Desjardins",
  qbo_enregistre: "Paiements inscrits dans QuickBooks",
  qbo_partiel: "Paiements inscrits en partie dans QuickBooks",
  reglages_modifies: "Réglages du dépôt direct modifiés",
  "2fa_activee": "Double authentification activée",
  "2fa_desactivee": "Double authentification désactivée"
};
