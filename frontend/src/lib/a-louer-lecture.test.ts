import { describe, expect, it } from "vitest";

import {
  disponibilite,
  ETAPES_A_LOUER,
  gesteSuivant,
  jourProche,
  phraseEtape,
  rangEtape
} from "./a-louer-lecture";

const AUJOURDHUI = "2026-11-13";

describe("étapes d'un dossier « À louer »", () => {
  it("cinq étapes, dans l'ordre du tableau", () => {
    expect(ETAPES_A_LOUER.map((e) => e.libelle)).toEqual([
      "À louer",
      "Affiché",
      "Bail à préparer",
      "En signature",
      "Reloué"
    ]);
    expect(rangEtape("avis_recu")).toBe(1);
    expect(rangEtape("reloue")).toBe(5);
    expect(rangEtape("annule")).toBe(0);
    expect(phraseEtape("avis_recu")).toBe("Étape 1 sur 5 : à louer");
    expect(phraseEtape("en_signature")).toBe("Étape 4 sur 5 : en signature");
    expect(phraseEtape("annule")).toBe("");
  });

  it("le bouton principal fait avancer d'une étape, comme le glisser-déposer", () => {
    expect(gesteSuivant("avis_recu")?.geste).toBe("afficher");
    expect(gesteSuivant("avis_recu")?.libelle).toBe("Marquer affiché");
    expect(gesteSuivant("annonce_publiee")?.geste).toBe("lier");
    expect(gesteSuivant("bail_a_preparer")?.geste).toBe("preparer");
    expect(gesteSuivant("en_signature")?.geste).toBe("importer");
    expect(gesteSuivant("reloue")).toBeNull();
    expect(gesteSuivant("annule")).toBeNull();
  });
});

describe("disponibilité du logement", () => {
  const dossier = (extra: Partial<Parameters<typeof disponibilite>[0]>) => ({
    statut: "avis_recu",
    date_depart: null,
    reloue_le: null,
    locataire_sortant: null,
    ...extra
  });

  it("déjà libre : depuis quand, et combien de jours", () => {
    expect(disponibilite(dossier({ date_depart: "2026-10-31" }), AUJOURDHUI)).toEqual({
      pastille: "Libre depuis le 31 oct.",
      ton: "amber",
      phrase: "Vacant depuis 13 jours"
    });
    expect(
      disponibilite(dossier({ date_depart: "2026-11-12" }), AUJOURDHUI).phrase
    ).toBe("Vacant depuis 1 jour");
    expect(
      disponibilite(dossier({ date_depart: AUJOURDHUI }), AUJOURDHUI).phrase
    ).toBe("Libre depuis aujourd'hui");
  });

  it("départ à venir : qui part, quand", () => {
    expect(
      disponibilite(
        dossier({ date_depart: "2026-12-31", locataire_sortant: "Félix Gauthier" }),
        AUJOURDHUI
      )
    ).toEqual({
      pastille: "Libre le 31 déc.",
      ton: "neutre",
      phrase: "Félix Gauthier part le 31 déc."
    });
    expect(disponibilite(dossier({ date_depart: "2027-06-30" }), AUJOURDHUI)).toEqual({
      pastille: "Libre le 30 juin 2027",
      ton: "neutre",
      phrase: "Départ dans 229 jours"
    });
  });

  it("reloué, ou date inconnue", () => {
    expect(
      disponibilite(dossier({ statut: "reloue", reloue_le: "2026-09-01" }), AUJOURDHUI)
    ).toEqual({ pastille: "Reloué le 1er sept.", ton: "emerald", phrase: "" });
    expect(disponibilite(dossier({}), AUJOURDHUI).pastille).toBe(
      "Date de départ à préciser"
    );
  });

  it("l'année n'apparaît que si elle diffère", () => {
    expect(jourProche("2026-07-01", AUJOURDHUI)).toBe("1er juill.");
    expect(jourProche("2025-12-15", AUJOURDHUI)).toBe("15 déc. 2025");
    expect(jourProche(null, AUJOURDHUI)).toBe("");
  });
});
