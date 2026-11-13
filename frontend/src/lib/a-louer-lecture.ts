/**
 * Lecture du tableau « À louer » — nouvelle présentation (refonte
 * d'Immobilier, lot 3 ; Steven, 2026-11-13).
 *
 * Fonctions PURES, testées par vitest : les cinq étapes d'un dossier, le
 * geste qui le fait avancer d'une étape, et ce qu'on dit de sa date de
 * départ. Aucune règle métier nouvelle : les étapes et les gestes sont
 * ceux du glisser-déposer de l'écran actuel.
 */

import { jourAvecAnnee } from "./baux-lecture";

export type EtapeALouer =
  | "avis_recu"
  | "annonce_publiee"
  | "bail_a_preparer"
  | "en_signature"
  | "reloue";

export const ETAPES_A_LOUER: { id: EtapeALouer; libelle: string }[] = [
  { id: "avis_recu", libelle: "À louer" },
  { id: "annonce_publiee", libelle: "Affiché" },
  { id: "bail_a_preparer", libelle: "Bail à préparer" },
  { id: "en_signature", libelle: "En signature" },
  { id: "reloue", libelle: "Reloué" }
];

/** Rang de l'étape, de 1 à 5 ; 0 pour une étape inconnue (annulé). */
export function rangEtape(etape: string): number {
  return ETAPES_A_LOUER.findIndex((e) => e.id === etape) + 1;
}

/** « Étape 2 sur 5 : affiché ». */
export function phraseEtape(etape: string): string {
  const rang = rangEtape(etape);
  if (rang === 0) return "";
  const libelle = ETAPES_A_LOUER[rang - 1].libelle;
  return `Étape ${rang} sur ${ETAPES_A_LOUER.length} : ${libelle.charAt(0).toLowerCase()}${libelle.slice(1)}`;
}

/** Ce que fait le bouton principal d'une carte. */
export type GesteALouer = "afficher" | "lier" | "preparer" | "importer";

/** Le geste qui fait passer le dossier à l'étape suivante — le même que
 *  glisser sa carte dans la colonne d'après. Rien après « Reloué ». */
export function gesteSuivant(
  etape: string
): { geste: GesteALouer; libelle: string; aide: string } | null {
  switch (etape) {
    case "avis_recu":
      return {
        geste: "afficher",
        libelle: "Marquer affiché",
        aide: "L'annonce est en ligne : le dossier passe à « Affiché »"
      };
    case "annonce_publiee":
      return {
        geste: "lier",
        libelle: "Lier un locataire",
        aide: "Un locataire est trouvé : son bail proposé est créé"
      };
    case "bail_a_preparer":
      return {
        geste: "preparer",
        libelle: "Préparer le bail",
        aide: "Produire le bail officiel (formulaire du TAL)"
      };
    case "en_signature":
      return {
        geste: "importer",
        libelle: "Importer le bail signé",
        aide: "Le bail signé au dossier, le logement est reloué"
      };
    default:
      return null;
  }
}

function joursEntre(deIso: string, aIso: string): number | null {
  const lire = (iso: string) => {
    const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
    return y && m && d ? Date.UTC(y, m - 1, d) : null;
  };
  const de = lire(deIso);
  const a = lire(aIso);
  if (de == null || a == null) return null;
  return Math.round((a - de) / 86_400_000);
}

/** « 31 oct. », avec l'année seulement si ce n'est pas celle en cours. */
export function jourProche(iso: string | null | undefined, aujourdhui: string): string {
  if (!iso) return "";
  const complet = jourAvecAnnee(iso);
  return iso.slice(0, 4) === aujourdhui.slice(0, 4)
    ? complet.replace(/ \d{4}$/, "")
    : complet;
}

export type DossierLisible = {
  statut: string;
  date_depart: string | null;
  reloue_le: string | null;
  locataire_sortant: string | null;
};

/** Ce qu'on dit de la disponibilité du logement : la pastille de la
 *  carte et la phrase sous son titre. `aujourdhui` : AAAA-MM-JJ. */
export function disponibilite(
  d: DossierLisible,
  aujourdhui: string
): { pastille: string; ton: "amber" | "neutre" | "emerald"; phrase: string } {
  if (d.statut === "reloue") {
    return {
      pastille: d.reloue_le
        ? `Reloué le ${jourProche(d.reloue_le, aujourdhui)}`
        : "Reloué",
      ton: "emerald",
      phrase: ""
    };
  }
  if (!d.date_depart) {
    return { pastille: "Date de départ à préciser", ton: "neutre", phrase: "" };
  }
  const jours = joursEntre(d.date_depart, aujourdhui);
  const quand = jourProche(d.date_depart, aujourdhui);
  if (jours != null && jours >= 0) {
    return {
      pastille: `Libre depuis le ${quand}`,
      ton: "amber",
      phrase:
        jours === 0
          ? "Libre depuis aujourd'hui"
          : `Vacant depuis ${jours} jour${jours > 1 ? "s" : ""}`
    };
  }
  const reste = jours != null ? -jours : null;
  return {
    pastille: `Libre le ${quand}`,
    ton: "neutre",
    phrase: d.locataire_sortant
      ? `${d.locataire_sortant} part le ${quand}`
      : reste != null
        ? `Départ dans ${reste} jour${reste > 1 ? "s" : ""}`
        : ""
  };
}
