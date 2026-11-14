/**
 * Lecture des documents d'un immeuble — nouvelle présentation (refonte
 * d'Immobilier, lot « fiches » ; Steven, 2026-11-13).
 *
 * Fonctions PURES, testées par vitest : quels documents sont des
 * brouillons créés d'office (cachés tant qu'ils ne sont pas envoyés) et
 * comment la liste se classe par logement et par locataire.
 */

export type DocumentLisible = {
  id: number;
  bail_id: number | null;
  locataire_id: number | null;
  logement_id?: number | null;
  type: string;
  source?: string;
  envoye_le: string | null;
  signed_at: string | null;
};

/** Documents que Kratos prépare de lui-même à la création d'un bail. */
const TYPES_CREES_D_OFFICE: ReadonlySet<string> = new Set([
  "consentement_communications"
]);

/** Brouillon créé d'office : préparé par Kratos, jamais envoyé ni signé.
 *  Un document importé ou préparé à la main n'en est jamais un. */
export function estBrouillonAuto(d: DocumentLisible): boolean {
  return (
    TYPES_CREES_D_OFFICE.has(d.type) &&
    (d.source || "genere") !== "importe" &&
    !d.envoye_le &&
    !d.signed_at
  );
}

export type ReperesDocuments = {
  /** Logements de l'immeuble. */
  logements: { id: number; numero: string }[];
  /** Baux de l'immeuble : à quel logement et quel locataire ils vont. */
  baux: { id: number; logement_id: number; locataire_id?: number | null }[];
  /** Noms connus des locataires (ceux des baux en cours et à venir). */
  noms: Record<number, string>;
};

export type GroupeDocuments<D> = {
  /** `immeuble`, ou `logement-<id>`. */
  cle: string;
  /** « Immeuble », « Logement 4 ». */
  titre: string;
  /** Locataires dont ce groupe porte des documents, en mots. */
  sousTitre: string;
  docs: D[];
};

function comparerNumeros(a: string, b: string): number {
  return a.localeCompare(b, "fr", { numeric: true, sensitivity: "base" });
}

/** Les documents classés : ceux de l'immeuble d'abord, puis un groupe
 *  par logement en ordre croissant. Le logement d'un document vient de
 *  lui-même, sinon de son bail. L'ordre des documents dans un groupe est
 *  celui reçu (le plus récent d'abord). */
export function grouperDocuments<D extends DocumentLisible>(
  docs: D[],
  reperes: ReperesDocuments
): GroupeDocuments<D>[] {
  const logementDuBail = new Map(reperes.baux.map((b) => [b.id, b.logement_id]));
  const locataireDuBail = new Map(
    reperes.baux.map((b) => [b.id, b.locataire_id ?? null])
  );
  const numeros = new Map(reperes.logements.map((l) => [l.id, l.numero]));

  const immeuble: D[] = [];
  const parLogement = new Map<number, { docs: D[]; locataires: number[] }>();
  for (const d of docs) {
    const logementId =
      d.logement_id ?? (d.bail_id != null ? logementDuBail.get(d.bail_id) : null);
    if (logementId == null || !numeros.has(logementId)) {
      immeuble.push(d);
      continue;
    }
    const groupe = parLogement.get(logementId) ?? { docs: [], locataires: [] };
    groupe.docs.push(d);
    const locataireId =
      d.locataire_id ??
      (d.bail_id != null ? locataireDuBail.get(d.bail_id) : null);
    if (locataireId != null && !groupe.locataires.includes(locataireId)) {
      groupe.locataires.push(locataireId);
    }
    parLogement.set(logementId, groupe);
  }

  const groupes: GroupeDocuments<D>[] = [];
  if (immeuble.length > 0) {
    groupes.push({
      cle: "immeuble",
      titre: "Immeuble",
      sousTitre: "règlement, certificats, pièces communes",
      docs: immeuble
    });
  }
  const tries = [...parLogement.entries()].sort((a, b) =>
    comparerNumeros(numeros.get(a[0]) || "", numeros.get(b[0]) || "")
  );
  for (const [logementId, g] of tries) {
    const noms = g.locataires
      .map((id) => reperes.noms[id])
      .filter((n): n is string => !!n);
    groupes.push({
      cle: `logement-${logementId}`,
      titre: `Logement ${numeros.get(logementId)}`,
      sousTitre: noms.join(", "),
      docs: g.docs
    });
  }
  return groupes;
}
