/**
 * Lecture d'une ligne de l'écran des loyers — refonte d'Immobilier, lot 2
 * (Steven, 2026-11-13 : « mettre tout ce qui est recommandé »).
 *
 * Ce module dit, pour une ligne : ce qui reste à payer, POUR QUELS MOIS,
 * et ce que le bouton principal encaisse. Le libellé du bouton (« Marquer
 * payé 925 $ ») et le montant enregistré viennent du même calcul, donc ils
 * ne peuvent pas diverger. Il range aussi les lignes par filtre (les
 * tuiles du haut) et par immeuble.
 *
 * Module PUR (aucun composant, aucun appel réseau) : testé par vitest.
 */
import { compareNumero } from "../components/immobilier/numero-sort";

export type MoisDu = {
  /** 1er du mois, AAAA-MM-JJ. */
  mois: string;
  du: number;
  recu: number;
  restant: number;
};

/** Ce qu'il faut d'une ligne pour la lire (interne, gestion externe ou
 *  logement vacant). */
export type LigneALire = {
  loyer_mensuel: number;
  montant_paye?: number | null;
  frais_mois?: { montant: number }[];
  etat: string; // "retard" | "partiel" | "attente" | "paye" | "vacant"
  solde_total?: number;
  mois_impayes?: MoisDu[];
  gestion_externe?: boolean;
};

export type LectureLigne = {
  /** Ce que le bouton principal encaisse ; 0 = rien à encaisser. */
  total: number;
  /** Dû du mois affiché : loyer + lignes du mois (frais, crédits). */
  duMois: number;
  recuMois: number;
  restantMois: number;
  /** Mois d'AVANT le mois affiché encore dus, du plus ancien au plus
   *  récent (vide en gestion externe : le détail n'est pas suivi). */
  anterieurs: MoisDu[];
  /** Somme due sur les mois d'avant, avec ou sans détail. */
  anterieursMontant: number;
  /** Gestion externe : le montant se ventile sur les mois passés. */
  cumul: boolean;
  /** « Marquer payé » quand le clic règle seulement le mois affiché,
   *  jamais entamé ; « Encaisser » dès qu'un montant est déjà reçu ou
   *  qu'un mois passé est dû. */
  verbe: "Marquer payé" | "Encaisser";
};

function arrondi(n: number): number {
  return Math.round(n * 100) / 100;
}

/** Même calcul que `duMois` de `paiements-actions` : loyer + lignes. */
function duDuMois(l: LigneALire): number {
  return arrondi(
    l.loyer_mensuel + (l.frais_mois ?? []).reduce((s, f) => s + f.montant, 0)
  );
}

export function lireLigne(l: LigneALire, moisAffiche: string): LectureLigne {
  const duMois = duDuMois(l);
  const recuMois = arrondi(l.montant_paye ?? 0);
  // Un mois « payé » ne doit plus rien, même quand un crédit couvre le
  // loyer sans versement.
  const restantMois =
    l.etat === "paye" || l.etat === "vacant"
      ? 0
      : Math.max(arrondi(duMois - recuMois), 0);
  const solde = Math.max(arrondi(l.solde_total ?? 0), 0);

  if (l.etat === "vacant") {
    return {
      total: 0,
      duMois,
      recuMois: 0,
      restantMois: 0,
      anterieurs: [],
      anterieursMontant: 0,
      cumul: false,
      verbe: "Marquer payé"
    };
  }

  if (l.gestion_externe) {
    // Solde cumulatif de l'unité, sans détail par mois : un clic règle
    // tout le solde (ventilé du plus ancien au plus récent), sinon le
    // restant du mois.
    const total = solde > 0 ? solde : restantMois;
    const anterieursMontant = Math.max(arrondi(solde - restantMois), 0);
    return {
      total,
      duMois,
      recuMois,
      restantMois,
      anterieurs: [],
      anterieursMontant,
      cumul: solde > 0,
      verbe: recuMois <= 0 && anterieursMontant <= 0 ? "Marquer payé" : "Encaisser"
    };
  }

  const cleMois = moisAffiche.slice(0, 7);
  const anterieurs = (l.mois_impayes ?? [])
    .filter((x) => x.mois.slice(0, 7) < cleMois && x.restant > 0.005)
    .sort((a, b) => a.mois.localeCompare(b.mois));
  let anterieursMontant = arrondi(anterieurs.reduce((s, x) => s + x.restant, 0));
  let total = arrondi(restantMois + anterieursMontant);
  if (total <= 0 && solde > 0) {
    // Dette sans détail (ancien bail, mois hors période) : le solde.
    total = solde;
    anterieursMontant = solde;
  }
  return {
    total,
    duMois,
    recuMois,
    restantMois,
    anterieurs,
    anterieursMontant,
    cumul: false,
    verbe: recuMois <= 0 && anterieursMontant <= 0 ? "Marquer payé" : "Encaisser"
  };
}

// ── Format commun (règle R7 : une seule forme de montant et de date) ──

/** « 925 $ », « 1 375 $ », « 450,50 $ » : sans cents quand c'est rond. */
export function argent(n: number): string {
  const v = arrondi(n);
  const rond = Math.abs(v - Math.round(v)) < 0.005;
  return `${v.toLocaleString("fr-CA", {
    minimumFractionDigits: rond ? 0 : 2,
    maximumFractionDigits: 2
  })} $`;
}

const MOIS_LONGS = [
  "janvier",
  "février",
  "mars",
  "avril",
  "mai",
  "juin",
  "juillet",
  "août",
  "septembre",
  "octobre",
  "novembre",
  "décembre"
];
const MOIS_ABREGES = [
  "janv.",
  "févr.",
  "mars",
  "avr.",
  "mai",
  "juin",
  "juill.",
  "août",
  "sept.",
  "oct.",
  "nov.",
  "déc."
];

/** « novembre », ou « décembre 2025 » quand l'année n'est pas celle du
 *  mois affiché. */
export function nomMois(iso: string, moisAffiche: string): string {
  const [y, m] = iso.slice(0, 7).split("-");
  const nom = MOIS_LONGS[Number(m) - 1] ?? m;
  return y === moisAffiche.slice(0, 4) ? nom : `${nom} ${y}`;
}

/** « novembre 2026 ». */
export function nomMoisComplet(mois: string): string {
  const [y, m] = mois.slice(0, 7).split("-");
  return `${MOIS_LONGS[Number(m) - 1] ?? m} ${y}`;
}

/** « 2 nov. », ou « 2 nov. 2025 » quand l'année n'est pas celle du mois
 *  affiché. Chaîne vide si la date manque. */
export function jourCourt(
  iso: string | null | undefined,
  moisAffiche: string
): string {
  if (!iso) return "";
  const [y, m, d] = iso.slice(0, 10).split("-");
  const jour = Number(d) === 1 ? "1er" : String(Number(d));
  const base = `${jour} ${MOIS_ABREGES[Number(m) - 1] ?? m}`;
  return y === moisAffiche.slice(0, 4) ? base : `${base} ${y}`;
}

/** Les mois encore dus, nommés avec leur montant, du plus ancien au plus
 *  récent : [« septembre 1 125 $ », « octobre 250 $ »]. Le mois affiché
 *  s'ajoute à la fin quand il reste dû lui aussi. Vide quand seul le mois
 *  affiché est dû (la ligne le dit autrement). */
export function moisNommes(lecture: LectureLigne, moisAffiche: string): string[] {
  if (lecture.anterieursMontant <= 0) return [];
  const parts = lecture.anterieurs.map(
    (x) => `${nomMois(x.mois, moisAffiche)} ${argent(x.restant)}`
  );
  if (parts.length === 0) {
    parts.push(`mois passés ${argent(lecture.anterieursMontant)}`);
  }
  if (lecture.restantMois > 0) {
    parts.push(`${nomMois(moisAffiche, moisAffiche)} ${argent(lecture.restantMois)}`);
  }
  return parts;
}

// ── Filtres (les tuiles du haut) ──────────────────────────────────────

export type FiltreLoyers = "impayes" | "attente" | "payes" | "vacants" | "tous";

export function dansFiltre(etat: string, filtre: FiltreLoyers): boolean {
  switch (filtre) {
    case "impayes":
      return etat === "retard" || etat === "partiel";
    case "attente":
      return etat === "attente";
    case "payes":
      return etat === "paye";
    case "vacants":
      return etat === "vacant";
    default:
      return true;
  }
}

/** Lien déjà filtré (`?etat=`) : accepte les mots de l'écran actuel
 *  (retard, partiel, paye, attente, vacant, all) et ceux du nouveau. */
export function filtreDepuisUrl(valeur: string | null): FiltreLoyers | null {
  switch (valeur) {
    case "retard":
    case "partiel":
    case "impayes":
      return "impayes";
    case "attente":
      return "attente";
    case "paye":
    case "payes":
      return "payes";
    case "vacant":
    case "vacants":
      return "vacants";
    case "all":
    case "tous":
      return "tous";
    default:
      return null;
  }
}

export type Comptes = Record<FiltreLoyers, number> & {
  /** Somme de ce qui reste à encaisser sur les lignes impayées. */
  aEncaisser: number;
  /** Dû du mois affiché sur les lignes non vacantes, et reçu. */
  attendu: number;
  recu: number;
};

export function compter<T extends LigneALire>(
  lignes: T[],
  moisAffiche: string
): Comptes {
  const c: Comptes = {
    impayes: 0,
    attente: 0,
    payes: 0,
    vacants: 0,
    tous: lignes.length,
    aEncaisser: 0,
    attendu: 0,
    recu: 0
  };
  for (const l of lignes) {
    if (dansFiltre(l.etat, "vacants")) {
      c.vacants += 1;
      continue;
    }
    const lecture = lireLigne(l, moisAffiche);
    c.attendu += lecture.duMois;
    c.recu += lecture.recuMois;
    if (dansFiltre(l.etat, "impayes")) {
      c.impayes += 1;
      c.aEncaisser += lecture.total;
    } else if (dansFiltre(l.etat, "attente")) {
      c.attente += 1;
    } else if (dansFiltre(l.etat, "payes")) {
      c.payes += 1;
    }
  }
  c.aEncaisser = arrondi(c.aEncaisser);
  c.attendu = arrondi(c.attendu);
  c.recu = arrondi(c.recu);
  return c;
}

// ── Groupes par immeuble ──────────────────────────────────────────────

export type LigneGroupable = LigneALire & {
  immeuble_id: number;
  immeuble_name: string;
  logement_numero: string | null;
};

export type GroupeImmeuble<T> = {
  immeuble_id: number;
  immeuble_name: string;
  gestion_externe: boolean;
  /** Sur TOUT l'immeuble, quel que soit le filtre affiché. */
  nbBaux: number;
  nbImpayes: number;
  nbVacants: number;
  /** Lignes du filtre, logements en ordre croissant (1, 2 … 10, 11). */
  lignes: T[];
};

/** « 9 impayés sur 10 baux », « 10 baux, aucun impayé », « 2 logements
 *  vacants ». En gestion externe le suivi est par logement, sans bail
 *  chez nous : « 2 impayés sur 3 logements ». */
export function resumeGroupe(g: {
  nbBaux: number;
  nbImpayes: number;
  nbVacants: number;
  gestion_externe?: boolean;
}): string {
  if (g.nbBaux === 0) {
    return g.nbVacants > 1
      ? `${g.nbVacants} logements vacants`
      : "1 logement vacant";
  }
  const baux = g.gestion_externe
    ? g.nbBaux > 1
      ? `${g.nbBaux} logements`
      : "1 logement"
    : g.nbBaux > 1
      ? `${g.nbBaux} baux`
      : "1 bail";
  if (g.nbImpayes === 0) return `${baux}, aucun impayé`;
  return `${g.nbImpayes} ${g.nbImpayes > 1 ? "impayés" : "impayé"} sur ${baux}`;
}

/** Range `base` par immeuble (ordre alphabétique, chiffres en nombres) et
 *  ne garde dans chaque groupe que les lignes du filtre. Un immeuble sans
 *  ligne dans le filtre n'apparaît pas. */
export function grouperParImmeuble<T extends LigneGroupable>(
  base: T[],
  filtre: FiltreLoyers
): GroupeImmeuble<T>[] {
  const groupes = new Map<number, GroupeImmeuble<T>>();
  for (const l of base) {
    let g = groupes.get(l.immeuble_id);
    if (!g) {
      g = {
        immeuble_id: l.immeuble_id,
        immeuble_name: l.immeuble_name,
        gestion_externe: false,
        nbBaux: 0,
        nbImpayes: 0,
        nbVacants: 0,
        lignes: []
      };
      groupes.set(l.immeuble_id, g);
    }
    if (l.gestion_externe) g.gestion_externe = true;
    if (dansFiltre(l.etat, "vacants")) g.nbVacants += 1;
    else {
      g.nbBaux += 1;
      if (dansFiltre(l.etat, "impayes")) g.nbImpayes += 1;
    }
    if (dansFiltre(l.etat, filtre)) g.lignes.push(l);
  }
  return [...groupes.values()]
    .filter((g) => g.lignes.length > 0)
    .map((g) => ({
      ...g,
      lignes: [...g.lignes].sort((a, b) =>
        compareNumero(a.logement_numero, b.logement_numero)
      )
    }))
    .sort((a, b) =>
      a.immeuble_name.localeCompare(b.immeuble_name, "fr", {
        numeric: true,
        sensitivity: "base"
      })
    );
}
