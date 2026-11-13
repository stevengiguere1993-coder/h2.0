import { describe, expect, it } from "vitest";

import {
  bailAImporter,
  compterBaux,
  dansFiltreBaux,
  etatBail,
  FILTRES_BAUX,
  filtreBauxDepuisUrl,
  finEnCours,
  grouperBaux,
  horsListe,
  jourAvecAnnee,
  type LigneBailLisible,
  periodeLisible,
  type ReperesBaux,
  resumeGroupeBaux,
  SANS_REPERES
} from "./baux-lecture";

let suivant = 100;

function ligne(
  immeuble_id: number,
  immeuble_name: string,
  logement_numero: string,
  extra: Partial<LigneBailLisible> = {}
): LigneBailLisible {
  suivant += 1;
  return {
    logement_id: suivant,
    logement_numero,
    immeuble_id,
    immeuble_name,
    bail_id: suivant + 1000,
    date_debut: "2026-07-01",
    date_fin: "2027-06-30",
    document_id: null,
    ...extra
  };
}

describe("état d'un bail — même règle que le serveur", () => {
  it("aucun bail en vigueur", () => {
    expect(etatBail(ligne(1, "A", "1", { bail_id: null }))).toBe("sans_bail");
  });
  it("le PDF au dossier fait foi, pas la signature en ligne", () => {
    expect(etatBail(ligne(1, "A", "1", { document_id: 9 }))).toBe("au_dossier");
    expect(etatBail(ligne(1, "A", "1", { signed_at: "2026-06-20T10:00:00Z" }))).toBe(
      "a_importer"
    );
  });
  it("« aucun bail à joindre » déclaré : exception, plus rien à importer", () => {
    expect(etatBail(ligne(1, "A", "1", { sans_document_motif: "Bail verbal" }))).toBe(
      "exception"
    );
    // Un document importé depuis l'emporte sur l'ancien motif.
    expect(
      etatBail(ligne(1, "A", "1", { sans_document_motif: "Bail verbal", document_id: 3 }))
    ).toBe("au_dossier");
  });
  it("fin en cours : entente en attente, ou départ confirmé", () => {
    expect(finEnCours(ligne(1, "A", "1"))).toBe(false);
    expect(finEnCours(ligne(1, "A", "1", { resiliation_en_cours: true }))).toBe(true);
    expect(finEnCours(ligne(1, "A", "1", { dossier_id: 4 }))).toBe(true);
    // Un logement libre en relocation n'est pas une « fin de bail ».
    expect(finEnCours(ligne(1, "A", "1", { bail_id: null, dossier_id: 4 }))).toBe(false);
  });
});

describe("tuiles : le chiffre est le nombre de lignes de la liste", () => {
  const aImporter = ligne(1, "100 rue des Érables", "2");
  const auDossier = ligne(1, "100 rue des Érables", "10", { document_id: 5 });
  const exception = ligne(1, "100 rue des Érables", "1", {
    sans_document_motif: "Entente verbale"
  });
  const libre = ligne(1, "100 rue des Érables", "11", { bail_id: null });
  const quiPart = ligne(2, "25 avenue du Parc", "201", {
    document_id: 6,
    dossier_id: 12
  });
  const resiliation = ligne(2, "25 avenue du Parc", "3", {
    resiliation_en_cours: true
  });
  const avis = ligne(3, "9 rue du Moulin", "A", { document_id: 7 });
  const lignes = [aImporter, auDossier, exception, libre, quiPart, resiliation, avis];
  const reperes: ReperesBaux = {
    avis: new Set([avis.bail_id as number]),
    aImporter: new Set([aImporter.bail_id as number, resiliation.bail_id as number])
  };

  it("chaque compte égale sa liste", () => {
    const c = compterBaux(lignes, reperes);
    expect(c).toEqual({ tous: 7, sans_bail: 1, a_importer: 2, fins: 2, avis: 1 });
    for (const f of FILTRES_BAUX) {
      expect(lignes.filter((l) => dansFiltreBaux(l, f, reperes))).toHaveLength(c[f]);
    }
  });

  it("sans la liste du serveur, la ligne dit la même chose", () => {
    const c = compterBaux(lignes, { ...SANS_REPERES, avis: reperes.avis });
    expect(c.a_importer).toBe(2);
    expect(bailAImporter(exception, SANS_REPERES)).toBeNull();
    expect(bailAImporter(aImporter, SANS_REPERES)).toBe(aImporter.bail_id);
  });

  it("bail suivant déjà actif sans PDF : la ligne du logement le porte", () => {
    const l = ligne(1, "A", "4", { document_id: 8, prochain_bail_id: 777 });
    const r: ReperesBaux = { avis: new Set(), aImporter: new Set([777]) };
    expect(bailAImporter(l, r)).toBe(777);
    expect(dansFiltreBaux(l, "a_importer", r)).toBe(true);
    // Le bail suivant seulement « proposé » n'est pas dans la liste.
    expect(bailAImporter(l, { avis: new Set(), aImporter: new Set() })).toBeNull();
  });

  it("ce que le serveur compte et qu'aucune ligne ne porte reste visible", () => {
    const serveur = [
      { bail_id: aImporter.bail_id as number },
      { bail_id: 9999 },
      { bail_id: 777 }
    ];
    const avecSuivant = [...lignes, ligne(1, "A", "4", { prochain_bail_id: 777 })];
    expect(horsListe(serveur, avecSuivant)).toEqual([{ bail_id: 9999 }]);
  });

  it("groupes par immeuble, logements en ordre croissant", () => {
    const tous = grouperBaux(lignes, "tous", reperes);
    expect(tous.map((g) => g.immeuble_name)).toEqual([
      "9 rue du Moulin",
      "25 avenue du Parc",
      "100 rue des Érables"
    ]);
    expect(tous[2].lignes.map((l) => l.logement_numero)).toEqual(["1", "2", "10", "11"]);
    expect(tous[1].lignes.map((l) => l.logement_numero)).toEqual(["3", "201"]);
    expect(resumeGroupeBaux(tous[2], "tous")).toBe("4 logements");

    const importer = grouperBaux(lignes, "a_importer", reperes);
    expect(importer.map((g) => g.immeuble_id)).toEqual([2, 1]);
    expect(importer[1].nbLogements).toBe(4);
    expect(resumeGroupeBaux(importer[1], "a_importer")).toBe("1 bail signé à importer");
  });

  it("résumés d'immeuble selon la tuile", () => {
    const g = (n: number) => ({ nbLogements: 12, lignes: new Array(n).fill(0) });
    expect(resumeGroupeBaux(g(10), "a_importer")).toBe("10 baux signés à importer");
    expect(resumeGroupeBaux(g(3), "sans_bail")).toBe("3 logements sans bail");
    expect(resumeGroupeBaux(g(1), "sans_bail")).toBe("1 logement sans bail");
    expect(resumeGroupeBaux(g(1), "fins")).toBe("1 fin de bail");
    expect(resumeGroupeBaux(g(2), "fins")).toBe("2 fins de bail");
    expect(resumeGroupeBaux(g(2), "avis")).toBe("2 avis de renouvellement à envoyer");
    expect(resumeGroupeBaux({ nbLogements: 1, lignes: [0] }, "tous")).toBe("1 logement");
  });

  it("lien déjà filtré", () => {
    expect(filtreBauxDepuisUrl("a_importer")).toBe("a_importer");
    expect(filtreBauxDepuisUrl("sans_bail")).toBe("sans_bail");
    expect(filtreBauxDepuisUrl("autre")).toBeNull();
    expect(filtreBauxDepuisUrl(null)).toBeNull();
  });
});

describe("dates lisibles, sur une ligne", () => {
  it("jour, mois abrégé, année", () => {
    expect(jourAvecAnnee("2026-07-01")).toBe("1er juill. 2026");
    expect(jourAvecAnnee("2027-06-30")).toBe("30 juin 2027");
    expect(jourAvecAnnee("2026-12-31T00:00:00")).toBe("31 déc. 2026");
    expect(jourAvecAnnee(null)).toBe("");
  });
  it("période d'un bail", () => {
    expect(periodeLisible("2026-07-01", "2027-06-30")).toBe(
      "1er juill. 2026 au 30 juin 2027"
    );
    expect(periodeLisible("2026-07-01", "2027-06-30", true)).toBe(
      "depuis le 1er juill. 2026, au mois"
    );
    expect(periodeLisible("2026-07-01", null)).toBe("depuis le 1er juill. 2026");
    expect(periodeLisible(null, "2027-06-30")).toBe("jusqu'au 30 juin 2027");
    expect(periodeLisible(null, null)).toBe("");
  });
});
