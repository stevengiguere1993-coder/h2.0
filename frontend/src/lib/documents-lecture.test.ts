import { describe, expect, it } from "vitest";

import {
  type DocumentLisible,
  estBrouillonAuto,
  grouperDocuments
} from "./documents-lecture";

let suivant = 0;
function doc(extra: Partial<DocumentLisible> = {}): DocumentLisible {
  suivant += 1;
  return {
    id: suivant,
    bail_id: null,
    locataire_id: null,
    logement_id: null,
    type: "bail",
    source: "importe",
    envoye_le: null,
    signed_at: null,
    ...extra
  };
}

describe("brouillons créés d'office", () => {
  const consentement = (extra: Partial<DocumentLisible> = {}) =>
    doc({ type: "consentement_communications", source: "genere", ...extra });

  it("le consentement préparé à la création du bail, jamais envoyé", () => {
    expect(estBrouillonAuto(consentement())).toBe(true);
    // `source` absent : un document généré.
    expect(estBrouillonAuto(consentement({ source: undefined }))).toBe(true);
  });
  it("envoyé ou signé : il se montre", () => {
    expect(estBrouillonAuto(consentement({ envoye_le: "2026-11-01T10:00:00Z" }))).toBe(
      false
    );
    expect(estBrouillonAuto(consentement({ signed_at: "2026-11-02T10:00:00Z" }))).toBe(
      false
    );
  });
  it("un consentement importé signé sur papier n'est pas un brouillon", () => {
    expect(estBrouillonAuto(consentement({ source: "importe" }))).toBe(false);
  });
  it("un avis préparé à la main reste visible même sans envoi", () => {
    expect(
      estBrouillonAuto(doc({ type: "avis_renouvellement", source: "genere" }))
    ).toBe(false);
  });
});

describe("documents classés par logement et par locataire", () => {
  const reperes = {
    logements: [
      { id: 1, numero: "10" },
      { id: 2, numero: "2" },
      { id: 3, numero: "A" }
    ],
    baux: [
      { id: 100, logement_id: 1, locataire_id: 7 },
      { id: 101, logement_id: 2, locataire_id: 8 },
      { id: 102, logement_id: 2, locataire_id: 9 }
    ],
    noms: { 7: "Alice Tremblay", 8: "Bruno Gagnon" }
  };

  it("l'immeuble d'abord, puis les logements en ordre croissant", () => {
    const reglement = doc({ type: "reglement_immeuble" });
    const bail10 = doc({ bail_id: 100, locataire_id: 7 });
    const bail2 = doc({ bail_id: 101 });
    const ancien2 = doc({ bail_id: 102, locataire_id: 9 });
    const directA = doc({ logement_id: 3 });
    const groupes = grouperDocuments(
      [bail10, reglement, ancien2, bail2, directA],
      reperes
    );
    expect(groupes.map((g) => g.titre)).toEqual([
      "Immeuble",
      "Logement 2",
      "Logement 10",
      "Logement A"
    ]);
    // L'ordre reçu est gardé dans un groupe.
    expect(groupes[1].docs).toEqual([ancien2, bail2]);
    // Le locataire vient du document, sinon du bail ; un nom inconnu
    // (ancien locataire) est passé sous silence.
    expect(groupes[1].sousTitre).toBe("Bruno Gagnon");
    expect(groupes[2].sousTitre).toBe("Alice Tremblay");
    expect(groupes[3].sousTitre).toBe("");
  });

  it("un bail inconnu ou un logement d'un autre immeuble va à « Immeuble »", () => {
    const orphelin = doc({ bail_id: 999 });
    const ailleurs = doc({ logement_id: 55 });
    const groupes = grouperDocuments([orphelin, ailleurs], reperes);
    expect(groupes).toHaveLength(1);
    expect(groupes[0].cle).toBe("immeuble");
    expect(groupes[0].docs).toEqual([orphelin, ailleurs]);
  });

  it("aucun document : aucun groupe", () => {
    expect(grouperDocuments([], reperes)).toEqual([]);
  });
});
