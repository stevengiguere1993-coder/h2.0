/**
 * Lecture de l'écran des baux — nouvelle présentation (refonte
 * d'Immobilier, lot 3 ; Steven, 2026-11-13).
 *
 * Fonctions PURES, testées par vitest : état d'une ligne, filtres des
 * tuiles (le chiffre d'une tuile est le nombre de lignes de sa liste),
 * dates lisibles, regroupement par immeuble avec les logements en ordre
 * croissant. Aucune règle métier nouvelle : tout se lit dans les lignes
 * de `/immobilier/suivi-baux`, les mêmes que l'écran actuel.
 */

import { compareNumero } from "../components/immobilier/numero-sort";
import { MOIS_ABREGES } from "./loyers-lecture";

/** Ce que la lecture utilise d'une ligne de `/immobilier/suivi-baux`. */
export type LigneBailLisible = {
  logement_id: number;
  logement_numero: string;
  immeuble_id: number;
  immeuble_name: string;
  bail_id: number | null;
  date_debut?: string | null;
  date_fin?: string | null;
  au_mois?: boolean | null;
  document_id?: number | null;
  signed_at?: string | null;
  sans_document_motif?: string | null;
  resiliation_en_cours?: boolean;
  /** Dossier de relocation ouvert sur le logement. */
  dossier_id?: number | null;
  /** Bail suivant du logement (proposé, ou actif qui commence plus tard). */
  prochain_bail_id?: number | null;
};

/** Où en est le bail du logement, côté dossier. */
export type EtatBail =
  /** Aucun bail en vigueur sur le logement. */
  | "sans_bail"
  /** Bail en vigueur, PDF signé manquant. */
  | "a_importer"
  /** Bail en vigueur, PDF au dossier (importé ou signé en ligne). */
  | "au_dossier"
  /** Bail en vigueur, « aucun bail à joindre » déclaré. */
  | "exception";

/** MÊME règle que le serveur (`/immobilier/baux/sans-document`, la liste
 *  que compte la page « Aujourd'hui ») : le bail est « au dossier » quand
 *  son PDF y est (`document_id`), pas avant. */
export function etatBail(r: LigneBailLisible): EtatBail {
  if (r.bail_id == null) return "sans_bail";
  if (r.document_id != null) return "au_dossier";
  if (r.sans_document_motif) return "exception";
  return "a_importer";
}

/** Le bail se termine : entente de résiliation en attente de signature,
 *  ou départ confirmé (le logement a son dossier de relocation). */
export function finEnCours(r: LigneBailLisible): boolean {
  if (r.bail_id == null) return false;
  return Boolean(r.resiliation_en_cours) || r.dossier_id != null;
}

export type FiltreBaux = "tous" | "sans_bail" | "a_importer" | "fins" | "avis";

export const FILTRES_BAUX: FiltreBaux[] = [
  "tous",
  "sans_bail",
  "a_importer",
  "fins",
  "avis"
];

/** Ce que la page lit ailleurs que dans les lignes. */
export type ReperesBaux = {
  /** Baux dont l'avis de renouvellement est à envoyer ou en retard
   *  (`/immobilier/baux/echeances`, statut autre que « à venir »). */
  avis: ReadonlySet<number>;
  /** Baux en vigueur sans bail signé au dossier, selon le serveur
   *  (`/immobilier/baux/sans-document`). null = liste pas lue : la règle
   *  se lit alors sur la ligne, qui dit la même chose. */
  aImporter: ReadonlySet<number> | null;
};

export const SANS_REPERES: ReperesBaux = { avis: new Set(), aImporter: null };

/** Le bail de la ligne dont le PDF signé reste à importer : celui en
 *  vigueur, sinon le suivant s'il est déjà actif (il commence plus
 *  tard). null = rien à importer sur cette ligne. */
export function bailAImporter(
  r: LigneBailLisible,
  reperes: ReperesBaux
): number | null {
  const liste = reperes.aImporter;
  if (liste == null) {
    return etatBail(r) === "a_importer" ? r.bail_id : null;
  }
  if (r.bail_id != null && liste.has(r.bail_id)) return r.bail_id;
  if (r.prochain_bail_id != null && liste.has(r.prochain_bail_id)) {
    return r.prochain_bail_id;
  }
  return null;
}

export function dansFiltreBaux(
  r: LigneBailLisible,
  filtre: FiltreBaux,
  reperes: ReperesBaux
): boolean {
  switch (filtre) {
    case "sans_bail":
      return r.bail_id == null;
    case "a_importer":
      return bailAImporter(r, reperes) != null;
    case "fins":
      return finEnCours(r);
    case "avis":
      return r.bail_id != null && reperes.avis.has(r.bail_id);
    default:
      return true;
  }
}

export function compterBaux(
  lignes: LigneBailLisible[],
  reperes: ReperesBaux
): Record<FiltreBaux, number> {
  const c: Record<FiltreBaux, number> = {
    tous: lignes.length,
    sans_bail: 0,
    a_importer: 0,
    fins: 0,
    avis: 0
  };
  for (const l of lignes) {
    for (const f of FILTRES_BAUX) {
      if (f !== "tous" && dansFiltreBaux(l, f, reperes)) c[f] += 1;
    }
  }
  return c;
}

/** Baux à importer que le serveur compte et qu'aucune ligne ne porte
 *  (bail parallèle, deuxième bail actif d'un logement) : ils sont montrés
 *  sous la liste, pour que le chiffre de la tuile reste celui de la page
 *  « Aujourd'hui ». */
export function horsListe<T extends { bail_id: number }>(
  aImporter: T[],
  lignes: LigneBailLisible[]
): T[] {
  const portes = new Set<number>();
  for (const l of lignes) {
    if (l.bail_id != null) portes.add(l.bail_id);
    if (l.prochain_bail_id != null) portes.add(l.prochain_bail_id);
  }
  return aImporter.filter((b) => !portes.has(b.bail_id));
}

/** Lien déjà filtré : `?filtre=a_importer` (page « Aujourd'hui »). */
export function filtreBauxDepuisUrl(
  valeur: string | null | undefined
): FiltreBaux | null {
  return FILTRES_BAUX.includes(valeur as FiltreBaux)
    ? (valeur as FiltreBaux)
    : null;
}

/** « 1er juill. 2026 ». Chaîne vide si la date manque. */
export function jourAvecAnnee(iso: string | null | undefined): string {
  if (!iso) return "";
  const [y, m, d] = iso.slice(0, 10).split("-");
  if (!y || !m || !d) return iso;
  const jour = Number(d) === 1 ? "1er" : String(Number(d));
  return `${jour} ${MOIS_ABREGES[Number(m) - 1] ?? m} ${y}`;
}

/** « 1er juill. 2026 au 30 juin 2027 », sur une ligne ; « depuis le
 *  1er juill. 2026, au mois » pour un bail sans terme. */
export function periodeLisible(
  debut: string | null | undefined,
  fin: string | null | undefined,
  auMois?: boolean | null
): string {
  const d = jourAvecAnnee(debut);
  const f = jourAvecAnnee(fin);
  if (auMois || !f) {
    if (!d) return auMois ? "au mois" : "";
    return auMois ? `depuis le ${d}, au mois` : `depuis le ${d}`;
  }
  if (!d) return `jusqu'au ${f}`;
  return `${d} au ${f}`;
}

export type GroupeBaux<T> = {
  immeuble_id: number;
  immeuble_name: string;
  /** Logements de l'immeuble (avant le filtre des tuiles). */
  nbLogements: number;
  /** Lignes du filtre, logements en ordre croissant (1, 2 … 10, 11). */
  lignes: T[];
};

/** Range `base` par immeuble (ordre alphabétique, chiffres en nombres)
 *  et ne garde dans chaque groupe que les lignes du filtre. Un immeuble
 *  sans ligne dans le filtre n'apparaît pas. */
export function grouperBaux<T extends LigneBailLisible>(
  base: T[],
  filtre: FiltreBaux,
  reperes: ReperesBaux
): GroupeBaux<T>[] {
  const groupes = new Map<number, GroupeBaux<T>>();
  for (const l of base) {
    let g = groupes.get(l.immeuble_id);
    if (!g) {
      g = {
        immeuble_id: l.immeuble_id,
        immeuble_name: l.immeuble_name,
        nbLogements: 0,
        lignes: []
      };
      groupes.set(l.immeuble_id, g);
    }
    g.nbLogements += 1;
    if (dansFiltreBaux(l, filtre, reperes)) g.lignes.push(l);
  }
  return [...groupes.values()]
    .filter((g) => g.lignes.length > 0)
    .sort((a, b) =>
      a.immeuble_name.localeCompare(b.immeuble_name, "fr", {
        numeric: true,
        sensitivity: "base"
      })
    )
    .map((g) => ({
      ...g,
      lignes: [...g.lignes].sort((a, b) =>
        compareNumero(a.logement_numero, b.logement_numero)
      )
    }));
}

/** Ce que l'en-tête d'un immeuble dit de ses lignes affichées :
 *  « 10 baux signés à importer », « 3 logements sans bail »,
 *  « 12 logements ». */
export function resumeGroupeBaux(
  g: { nbLogements: number; lignes: unknown[] },
  filtre: FiltreBaux
): string {
  const n = g.lignes.length;
  const s = n > 1 ? "s" : "";
  switch (filtre) {
    case "sans_bail":
      return `${n} logement${s} sans bail`;
    case "a_importer":
      return n > 1 ? `${n} baux signés à importer` : "1 bail signé à importer";
    case "fins":
      return n > 1 ? `${n} fins de bail` : "1 fin de bail";
    case "avis":
      return n > 1
        ? `${n} avis de renouvellement à envoyer`
        : "1 avis de renouvellement à envoyer";
    default:
      return `${g.nbLogements} logement${g.nbLogements > 1 ? "s" : ""}`;
  }
}
