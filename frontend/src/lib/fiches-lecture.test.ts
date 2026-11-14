import { describe, expect, it } from "vitest";

import {
  chiffreBail,
  chiffreDepot,
  jourDuMois,
  payableLe,
  rabaisEnMots,
  resteAPayer
} from "./fiches-lecture";

const MOIS = "2026-11";

const du = (mois: string, restant: number) => ({
  mois: `${mois}-01`,
  du: restant,
  recu: 0,
  restant
});

describe("reste à payer d'un locataire", () => {
  it("à jour : rien à payer, même sans ligne", () => {
    expect(resteAPayer([], MOIS)).toEqual({ montant: 0, mois: [], phrase: "À jour" });
    expect(resteAPayer([{ solde_total: 0, mois_impayes: [] }], MOIS).phrase).toBe(
      "À jour"
    );
  });

  it("un mois passé reste dû : il est nommé (la tuile « Retards » disait 0)", () => {
    const r = resteAPayer(
      [{ solde_total: 250, mois_impayes: [du("2026-10", 250)] }],
      MOIS
    );
    expect(r.montant).toBe(250);
    expect(r.phrase).toBe("pour octobre");
  });

  it("plusieurs mois : du plus ancien au plus récent, avec leur montant", () => {
    const r = resteAPayer(
      [
        {
          solde_total: 1175,
          mois_impayes: [du("2026-11", 925), du("2026-10", 250)]
        }
      ],
      MOIS
    );
    expect(r.montant).toBe(1175);
    expect(r.mois.map((m) => m.mois)).toEqual(["2026-10-01", "2026-11-01"]);
    expect(r.phrase).toBe("octobre 250 $, novembre 925 $");
  });

  it("au-delà de trois mois : les deux plus anciens, puis le compte", () => {
    const r = resteAPayer(
      [
        {
          solde_total: 4000,
          mois_impayes: [
            du("2025-12", 1000),
            du("2026-09", 1000),
            du("2026-10", 1000),
            du("2026-11", 1000)
          ]
        }
      ],
      MOIS
    );
    // Le séparateur de milliers est une espace insécable.
    expect(r.phrase.replace(/\s/g, " ")).toBe(
      "décembre 2025 1 000 $, septembre 1 000 $ et 2 autres mois"
    );
  });

  it("deux baux : les soldes s'additionnent, un même mois aussi", () => {
    const r = resteAPayer(
      [
        { solde_total: 300, mois_impayes: [du("2026-11", 300)] },
        { solde_total: 200, mois_impayes: [du("2026-11", 200)] }
      ],
      MOIS
    );
    expect(r.montant).toBe(500);
    expect(r.mois).toEqual([{ mois: "2026-11-01", restant: 500 }]);
    expect(r.phrase).toBe("pour novembre");
  });

  it("dette sans détail par mois : on le dit", () => {
    expect(resteAPayer([{ solde_total: 480 }], MOIS)).toEqual({
      montant: 480,
      mois: [],
      phrase: "Solde du bail"
    });
  });
});

describe("dépôt", () => {
  it("détenu", () => {
    expect(chiffreDepot([{ depot_garantie: 500 }], 500)).toEqual({
      libelle: "Dépôt détenu",
      valeur: "500 $"
    });
  });

  it("gardé, avec la date et le motif", () => {
    expect(
      chiffreDepot(
        [
          {
            depot_garantie: 500,
            depot_saisi_le: "2026-10-08",
            depot_saisi_montant: 350,
            depot_saisi_motif: "parti sans préavis"
          }
        ],
        0
      )
    ).toEqual({
      libelle: "Dépôt gardé",
      valeur: "350 $",
      sous: "le 8 oct. 2026 : parti sans préavis"
    });
  });

  it("rendu, ou aucun", () => {
    expect(
      chiffreDepot([{ depot_garantie: 500, depot_rendu_le: "2026-07-01" }], 0)
    ).toEqual({ libelle: "Dépôt rendu", valeur: "500 $", sous: "le 1er juill. 2026" });
    expect(chiffreDepot([{}], 0)).toEqual({ libelle: "Dépôt", valeur: "Aucun" });
  });
});

describe("bail", () => {
  it("bail à terme : sa fin, et depuis quand", () => {
    expect(
      chiffreBail([
        { status: "actif", date_debut: "2026-07-01", date_fin: "2027-06-30" }
      ])
    ).toEqual({
      libelle: "Fin du bail",
      valeur: "30 juin 2027",
      sous: "commencé le 1er juill. 2026"
    });
  });

  it("bail au mois", () => {
    expect(
      chiffreBail([
        {
          status: "actif",
          date_debut: "2024-07-01",
          date_fin: "2025-06-30",
          au_mois: true
        }
      ])
    ).toEqual({ libelle: "Bail", valeur: "Au mois", sous: "depuis le 1er juill. 2024" });
  });

  it("aucun bail en cours : le dernier, ou le bail proposé", () => {
    expect(
      chiffreBail([
        { status: "termine", date_debut: "2023-07-01", date_fin: "2024-06-30" },
        { status: "resilie", date_debut: "2024-07-01", date_fin: "2025-02-28" }
      ])
    ).toEqual({
      libelle: "Bail",
      valeur: "Aucun en cours",
      sous: "le dernier a pris fin le 28 févr. 2025"
    });
    expect(
      chiffreBail([{ status: "propose", date_debut: "2026-12-01", date_fin: "2027-06-30" }])
    ).toEqual({ libelle: "Bail", valeur: "Proposé", sous: "début prévu le 1er déc. 2026" });
    expect(chiffreBail([])).toEqual({ libelle: "Bail", valeur: "Aucun en cours" });
  });
});

describe("échéance du loyer", () => {
  it("le 1er par défaut", () => {
    expect(payableLe(null)).toBe("payable le 1er");
    expect(payableLe(1)).toBe("payable le 1er");
    expect(payableLe(15)).toBe("payable le 15");
  });
});

describe("conditions du bail, en mots", () => {
  it("jour de paiement", () => {
    expect(jourDuMois(null)).toBe("le 1er du mois");
    expect(jourDuMois(15)).toBe("le 15 du mois");
  });

  it("sans rabais", () => {
    expect(rabaisEnMots({}, "2026-07-01", MOIS)).toBe("Aucun");
    expect(
      rabaisEnMots({ rabais_mensuel: 0, rabais_nb_mois: 3 }, "2026-07-01", MOIS)
    ).toBe("Aucun");
  });

  it("plusieurs mois : du premier au dernier, dès le début du bail", () => {
    expect(
      rabaisEnMots({ rabais_mensuel: 500, rabais_nb_mois: 3 }, "2026-07-01", MOIS)
    ).toBe("500 $ de moins par mois, de juillet à septembre");
  });

  it("à cheval sur deux années, avec l'élision", () => {
    expect(
      rabaisEnMots(
        { rabais_mensuel: 100, rabais_nb_mois: 4, rabais_debut: "2026-10-01" },
        "2026-07-01",
        MOIS
      )
    ).toBe("100 $ de moins par mois, d'octobre à janvier 2027");
  });

  it("un seul mois", () => {
    expect(
      rabaisEnMots(
        { rabais_mensuel: 250, rabais_nb_mois: 1, rabais_debut: "2026-12-01" },
        null,
        MOIS
      )
    ).toBe("250 $ de moins en décembre");
  });
});
