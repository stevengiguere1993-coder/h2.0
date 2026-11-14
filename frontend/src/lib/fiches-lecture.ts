/**
 * Lecture des fiches locataire et logement — nouvelle présentation
 * (refonte d'Immobilier, lot « fiches » ; Steven, 2026-11-13).
 *
 * Fonctions PURES, testées par vitest : ce que disent les quatre chiffres
 * du haut d'une fiche. Aucune règle métier nouvelle : le reste à payer
 * vient de la vue des loyers (`solde_total`, `mois_impayes`), le dépôt et
 * les dates viennent du bail.
 */

import { jourAvecAnnee } from "./baux-lecture";
import { argent, type MoisDu, nomMois } from "./loyers-lecture";

// ── Reste à payer ─────────────────────────────────────────────────────

/** Ce qu'il faut d'une ligne de la vue des loyers. */
export type LigneSolde = {
  solde_total?: number | null;
  mois_impayes?: MoisDu[] | null;
};

export type ResteAPayer = {
  montant: number;
  /** Mois encore dus, du plus ancien au plus récent, tous baux réunis. */
  mois: { mois: string; restant: number }[];
  /** Sous le chiffre : « À jour », « pour octobre », « octobre 250 $,
   *  novembre 925 $ ». */
  phrase: string;
};

function arrondi(n: number): number {
  return Math.round(n * 100) / 100;
}

/** Au-delà, on nomme les deux plus anciens et on compte les autres. */
const NB_MOIS_NOMMES = 3;

/** Ce qu'un locataire doit encore, au mois courant (`AAAA-MM`). La tuile
 *  « Retards » de l'écran actuel comptait les paiements faits en retard :
 *  elle affichait 0 pendant qu'un mois restait dû. */
export function resteAPayer(lignes: LigneSolde[], moisCourant: string): ResteAPayer {
  const montant = arrondi(
    lignes.reduce((s, l) => s + Math.max(Number(l.solde_total ?? 0), 0), 0)
  );
  const parMois = new Map<string, number>();
  for (const l of lignes) {
    for (const m of l.mois_impayes ?? []) {
      if (m.restant <= 0.005) continue;
      const cle = m.mois.slice(0, 7);
      parMois.set(cle, arrondi((parMois.get(cle) ?? 0) + m.restant));
    }
  }
  const mois = [...parMois.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([cle, restant]) => ({ mois: `${cle}-01`, restant }));

  let phrase: string;
  if (montant <= 0) {
    phrase = "À jour";
  } else if (mois.length === 0) {
    phrase = "Solde du bail";
  } else if (mois.length === 1) {
    phrase = `pour ${nomMois(mois[0].mois, moisCourant)}`;
  } else {
    const nomme = (m: { mois: string; restant: number }) =>
      `${nomMois(m.mois, moisCourant)} ${argent(m.restant)}`;
    phrase =
      mois.length <= NB_MOIS_NOMMES
        ? mois.map(nomme).join(", ")
        : `${mois.slice(0, 2).map(nomme).join(", ")} et ${mois.length - 2} autres mois`;
  }
  return { montant, mois, phrase };
}

// ── Dépôt ─────────────────────────────────────────────────────────────

export type BailDepot = {
  depot_garantie?: number | null;
  depot_rendu_le?: string | null;
  depot_saisi_le?: string | null;
  depot_saisi_montant?: number | null;
  depot_saisi_motif?: string | null;
};

export type ChiffreLu = { libelle: string; valeur: string; sous?: string };

/** Le dépôt d'un locataire : détenu, gardé (avec le motif) ou rendu. Même
 *  lecture que la page des dépôts. */
export function chiffreDepot(baux: BailDepot[], depotDetenu: number): ChiffreLu {
  if (depotDetenu <= 0) {
    const garde = baux.find((b) => b.depot_saisi_le);
    if (garde) {
      return {
        libelle: "Dépôt gardé",
        valeur: argent(garde.depot_saisi_montant ?? garde.depot_garantie ?? 0),
        sous: `le ${jourAvecAnnee(garde.depot_saisi_le)}${
          garde.depot_saisi_motif ? ` : ${garde.depot_saisi_motif}` : ""
        }`
      };
    }
    const rendu = baux.find((b) => b.depot_rendu_le);
    if (rendu) {
      return {
        libelle: "Dépôt rendu",
        valeur: argent(rendu.depot_garantie ?? 0),
        sous: `le ${jourAvecAnnee(rendu.depot_rendu_le)}`
      };
    }
    return { libelle: "Dépôt", valeur: "Aucun" };
  }
  return { libelle: "Dépôt détenu", valeur: argent(depotDetenu) };
}

// ── Bail ──────────────────────────────────────────────────────────────

export type BailDates = {
  status: string;
  date_debut?: string | null;
  date_fin?: string | null;
  au_mois?: boolean | null;
};

/** Jusqu'à quand court le bail. Sans bail en cours : le dernier, s'il y
 *  en a eu un. */
export function chiffreBail(baux: BailDates[]): ChiffreLu {
  const actif = baux.find((b) => b.status === "actif");
  if (actif) {
    if (actif.au_mois) {
      return {
        libelle: "Bail",
        valeur: "Au mois",
        sous: actif.date_debut
          ? `depuis le ${jourAvecAnnee(actif.date_debut)}`
          : undefined
      };
    }
    return {
      libelle: "Fin du bail",
      valeur: jourAvecAnnee(actif.date_fin) || "Sans date",
      sous: actif.date_debut
        ? `commencé le ${jourAvecAnnee(actif.date_debut)}`
        : undefined
    };
  }
  const propose = baux.find((b) => b.status === "propose");
  if (propose) {
    return {
      libelle: "Bail",
      valeur: "Proposé",
      sous: propose.date_debut
        ? `début prévu le ${jourAvecAnnee(propose.date_debut)}`
        : undefined
    };
  }
  const dernier = [...baux]
    .filter((b) => b.date_fin)
    .sort((a, b) => String(b.date_fin).localeCompare(String(a.date_fin)))[0];
  return {
    libelle: "Bail",
    valeur: "Aucun en cours",
    sous: dernier ? `le dernier a pris fin le ${jourAvecAnnee(dernier.date_fin)}` : undefined
  };
}

/** « payable le 1er », « payable le 15 ». */
export function payableLe(jour: number | null | undefined): string {
  const j = Number(jour ?? 1);
  if (!Number.isFinite(j) || j <= 1) return "payable le 1er";
  return `payable le ${j}`;
}

// ── Conditions du bail, en mots ───────────────────────────────────────

/** « le 1er du mois », « le 15 du mois ». */
export function jourDuMois(jour: number | null | undefined): string {
  const j = Number(jour ?? 1);
  if (!Number.isFinite(j) || j <= 1) return "le 1er du mois";
  return `le ${j} du mois`;
}

export type BailRabais = {
  rabais_mensuel?: number | null;
  rabais_nb_mois?: number | null;
  /** Premier mois du rabais ; à défaut, le début du bail. */
  rabais_debut?: string | null;
};

function moisDecale(mois: string, delta: number): string {
  const [y, m] = mois.slice(0, 7).split("-").map(Number);
  const total = y * 12 + (m - 1) + delta;
  return `${Math.floor(total / 12)}-${String((total % 12) + 1).padStart(2, "0")}`;
}

/** « de juillet », « d'avril ». */
function de(nom: string): string {
  return /^[aeiouyàâéèêîôû]/i.test(nom) ? `d'${nom}` : `de ${nom}`;
}

/** Le rabais des premiers mois : « 500 $ de moins par mois, de juillet à
 *  septembre » ; « Aucun » sans rabais. Le loyer du bail reste le loyer
 *  plein. */
export function rabaisEnMots(
  b: BailRabais,
  dateDebut: string | null | undefined,
  moisCourant: string
): string {
  const montant = Number(b.rabais_mensuel ?? 0);
  const nb = Number(b.rabais_nb_mois ?? 0);
  if (!(montant > 0) || !(nb > 0)) return "Aucun";
  const debut = (b.rabais_debut ?? dateDebut ?? "").slice(0, 7);
  if (nb === 1) {
    return debut
      ? `${argent(montant)} de moins en ${nomMois(debut, moisCourant)}`
      : `${argent(montant)} de moins, un seul mois`;
  }
  if (!debut) return `${argent(montant)} de moins par mois, pendant ${nb} mois`;
  return `${argent(montant)} de moins par mois, ${de(
    nomMois(debut, moisCourant)
  )} à ${nomMois(moisDecale(debut, nb - 1), moisCourant)}`;
}
