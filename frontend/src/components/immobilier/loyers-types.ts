import type {
  FraisMois,
  MoisImpaye,
  PaiementMois
} from "@/components/immobilier/paiements-actions";

/**
 * Ligne de l'écran des loyers (/immobilier/paiements) : une ligne de
 * `/loyers/overview` (bail), une ligne de `/loyers/externes` repliée
 * (gestion externe, `bail_id` à 0) ou un logement vacant.
 *
 * Partagée par l'écran actuel et la nouvelle présentation (refonte
 * d'Immobilier, lot 2) : les deux lisent exactement les mêmes données.
 */
export type LigneLoyer = {
  bail_id: number;
  immeuble_id: number;
  immeuble_name: string;
  logement_id?: number | null;
  logement_numero: string | null;
  locataire_id: number | null;
  locataire_name: string | null;
  locataire_phone: string | null;
  locataire_email: string | null;
  /** Départ ACTÉ : ce locataire part à cette date. */
  libre_le: string | null;
  loyer_mensuel: number;
  /** Jour du mois où le loyer est payable (bail TAL « Ou le ___ »). */
  jour_echeance?: number | null;
  paiement_id: number | null;
  montant_paye: number | null;
  paye_le: string | null;
  //: Versements du mois (paiements partiels distincts).
  paiements?: PaiementMois[];
  etat: string; // "retard" | "attente" | "paye" | "partiel" | "vacant"
  /** Ligne de logement VACANT (bail_id vaut 0) : statut exact du
   *  logement ("vacant" ou "reserve") pour l'étiquette. */
  logement_statut?: string | null;
  /** Dossier ouvert au TAL sur ce bail (non-paiement) — badge + coche
   *  pour que l'équipe voie que le recours est lancé. */
  tal_dossier_ouvert_le?: string | null;
  /** Garants / contacts actifs du locataire (cherchables) et celui qui
   *  PAIE le loyer — « paie : Jacques Roy » sous le nom (point 8). */
  garants?: string[];
  payeur_nom?: string | null;
  //: Mois affiché payé, mais un mois antérieur du bail impayé.
  solde_anterieur?: boolean;
  /** Détail du solde : chaque mois encore dû (2026-11-13). */
  mois_impayes?: MoisImpaye[];
  /** Bail à plusieurs prix (périodes de loyer). */
  loyer_a_periodes?: boolean;
  //: Mois de bascule d'un transfert d'unité : rien n'est dû ici.
  transfert_bascule?: boolean;
  /** Bail résilié/terminé en cours de mois : la ligne reste dans le
   *  mois couvert avec un badge « Bail terminé le X » (M7). */
  bail_statut?: string;
  bail_termine_le?: string | null;
  //: LE bail courant (imm_documents) — clic = l'ouvrir.
  document_id?: number | null;
  // Frais ponctuels du mois (retard…) + solde cumulatif dû sur le bail.
  frais_mois?: FraisMois[];
  solde_total?: number;
  nb_relances: number;
  derniere_relance_le: string | null;
  // Prochain locataire (transition) — bail futur / en préparation.
  prochain_nom?: string | null;
  prochain_loyer?: number | null;
  prochain_debut?: string | null;
  prochain_statut?: string | null;
  /** Ligne d'un immeuble en gestion externe : suivi PAR LOGEMENT, sans
   *  locataire nominatif ni relance (bail_id vaut alors 0). */
  gestion_externe?: boolean;
};
