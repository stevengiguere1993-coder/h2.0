import { describe, expect, it } from "vitest";

import {
  argent,
  compter,
  dansFiltre,
  filtreDepuisUrl,
  grouperParImmeuble,
  jourCourt,
  lireLigne,
  moisNommes,
  nomMois,
  resumeGroupe,
  type LigneGroupable
} from "./loyers-lecture";

const MOIS = "2026-11";

/** Espaces insécables de `toLocaleString("fr-CA")` ramenées à l'espace. */
function net(s: string): string {
  return s.replace(/[  ]/g, " ");
}

describe("lireLigne — ce que le bouton principal encaisse", () => {
  it("mois jamais entamé, aucun mois passé : « Marquer payé » le loyer", () => {
    const l = lireLigne(
      {
        loyer_mensuel: 925,
        etat: "retard",
        solde_total: 925,
        mois_impayes: [{ mois: "2026-11-01", du: 925, recu: 0, restant: 925 }]
      },
      MOIS
    );
    expect(l.total).toBe(925);
    expect(l.verbe).toBe("Marquer payé");
    expect(moisNommes(l, MOIS)).toEqual([]);
  });

  it("les frais du mois font partie du montant", () => {
    const l = lireLigne(
      {
        loyer_mensuel: 650,
        frais_mois: [{ montant: 20 }],
        etat: "retard",
        solde_total: 670
      },
      MOIS
    );
    expect(l.duMois).toBe(670);
    expect(l.total).toBe(670);
  });

  it("partiel : « Encaisser » le restant du mois", () => {
    const l = lireLigne(
      { loyer_mensuel: 950, montant_paye: 475, etat: "partiel", solde_total: 475 },
      MOIS
    );
    expect(l.total).toBe(475);
    expect(l.verbe).toBe("Encaisser");
  });

  it("mois payé mais mois passés dus : le total et les mois nommés", () => {
    const l = lireLigne(
      {
        loyer_mensuel: 1125,
        montant_paye: 1125,
        etat: "partiel",
        solde_total: 1375,
        mois_impayes: [
          { mois: "2026-10-01", du: 1125, recu: 875, restant: 250 },
          { mois: "2026-09-01", du: 1125, recu: 0, restant: 1125 }
        ]
      },
      MOIS
    );
    expect(l.restantMois).toBe(0);
    expect(l.total).toBe(1375);
    expect(l.verbe).toBe("Encaisser");
    expect(moisNommes(l, MOIS).map(net)).toEqual([
      "septembre 1 125 $",
      "octobre 250 $"
    ]);
  });

  it("mois affiché ET mois passé dus : tout s'encaisse, tout est nommé", () => {
    const l = lireLigne(
      {
        loyer_mensuel: 925,
        etat: "retard",
        solde_total: 1175,
        mois_impayes: [
          { mois: "2025-12-01", du: 925, recu: 675, restant: 250 },
          { mois: "2026-11-01", du: 925, recu: 0, restant: 925 }
        ]
      },
      MOIS
    );
    expect(l.total).toBe(1175);
    expect(moisNommes(l, MOIS).map(net)).toEqual([
      "décembre 2025 250 $",
      "novembre 925 $"
    ]);
  });

  it("payé : rien à encaisser, même avec un crédit qui couvre le loyer", () => {
    expect(
      lireLigne(
        { loyer_mensuel: 550, frais_mois: [{ montant: -550 }], etat: "paye" },
        MOIS
      ).total
    ).toBe(0);
    expect(
      lireLigne({ loyer_mensuel: 1100, montant_paye: 1100, etat: "paye" }, MOIS)
        .total
    ).toBe(0);
  });

  it("dette d'un bail terminé sans détail : le solde", () => {
    const l = lireLigne({ loyer_mensuel: 0, etat: "retard", solde_total: 430.5 }, MOIS);
    expect(l.total).toBe(430.5);
    expect(l.verbe).toBe("Encaisser");
    expect(moisNommes(l, MOIS).map(net)).toEqual(["mois passés 430,50 $"]);
  });

  it("mois à venir : le loyer du mois, sans mois passés", () => {
    const l = lireLigne(
      { loyer_mensuel: 900, etat: "attente", solde_total: 0, mois_impayes: [] },
      "2026-12"
    );
    expect(l.total).toBe(900);
    expect(l.verbe).toBe("Marquer payé");
  });

  it("gestion externe : le solde cumulatif, ventilé", () => {
    const l = lireLigne(
      {
        loyer_mensuel: 900,
        etat: "retard",
        solde_total: 1400,
        gestion_externe: true
      },
      MOIS
    );
    expect(l.total).toBe(1400);
    expect(l.cumul).toBe(true);
    expect(l.anterieursMontant).toBe(500);
    expect(moisNommes(l, MOIS).map(net)).toEqual([
      "mois passés 500 $",
      "novembre 900 $"
    ]);
    const simple = lireLigne(
      { loyer_mensuel: 900, etat: "attente", solde_total: 900, gestion_externe: true },
      MOIS
    );
    expect(simple.total).toBe(900);
    expect(simple.verbe).toBe("Marquer payé");
  });

  it("logement vacant : jamais de montant", () => {
    expect(lireLigne({ loyer_mensuel: 950, etat: "vacant" }, MOIS).total).toBe(0);
  });
});

describe("format commun", () => {
  it("montants sans cents quand c'est rond", () => {
    expect(net(argent(925))).toBe("925 $");
    expect(net(argent(1375))).toBe("1 375 $");
    expect(net(argent(450.5))).toBe("450,50 $");
    expect(net(argent(0))).toBe("0 $");
  });
  it("mois et jours, l'année seulement quand elle diffère", () => {
    expect(nomMois("2026-09-01", MOIS)).toBe("septembre");
    expect(nomMois("2025-12-01", MOIS)).toBe("décembre 2025");
    expect(jourCourt("2026-11-02", MOIS)).toBe("2 nov.");
    expect(jourCourt("2026-11-01", MOIS)).toBe("1er nov.");
    expect(jourCourt("2025-12-15", MOIS)).toBe("15 déc. 2025");
    expect(jourCourt(null, MOIS)).toBe("");
  });
});

describe("tuiles et groupes", () => {
  const ligne = (
    immeuble_id: number,
    immeuble_name: string,
    logement_numero: string,
    etat: string,
    extra: Partial<LigneGroupable> = {}
  ): LigneGroupable => ({
    immeuble_id,
    immeuble_name,
    logement_numero,
    etat,
    loyer_mensuel: 1000,
    montant_paye: etat === "paye" ? 1000 : etat === "partiel" ? 400 : null,
    solde_total: etat === "paye" || etat === "vacant" ? 0 : etat === "partiel" ? 600 : 1000,
    ...extra
  });
  const lignes = [
    ligne(2, "25 avenue du Parc", "201", "retard"),
    ligne(1, "100 rue des Érables", "10", "retard"),
    ligne(1, "100 rue des Érables", "2", "partiel"),
    ligne(1, "100 rue des Érables", "1", "paye"),
    ligne(1, "100 rue des Érables", "11", "attente"),
    ligne(1, "100 rue des Érables", "3", "vacant"),
    ligne(3, "9 rue Externe", "A", "retard", { gestion_externe: true })
  ];

  it("le chiffre d'une tuile est le nombre de lignes de son filtre", () => {
    const c = compter(lignes, MOIS);
    expect(c).toMatchObject({
      impayes: 4,
      attente: 1,
      payes: 1,
      vacants: 1,
      tous: 7,
      aEncaisser: 3600,
      attendu: 6000,
      recu: 1400
    });
    for (const f of ["impayes", "attente", "payes", "vacants", "tous"] as const) {
      expect(lignes.filter((l) => dansFiltre(l.etat, f))).toHaveLength(c[f]);
    }
  });

  it("groupes par immeuble, logements en ordre croissant", () => {
    const tous = grouperParImmeuble(lignes, "tous");
    expect(tous.map((g) => g.immeuble_name)).toEqual([
      "9 rue Externe",
      "25 avenue du Parc",
      "100 rue des Érables"
    ]);
    const erables = tous[2];
    expect(erables.lignes.map((l) => l.logement_numero)).toEqual([
      "1",
      "2",
      "3",
      "10",
      "11"
    ]);
    expect(resumeGroupe(erables)).toBe("2 impayés sur 4 baux");
    expect(tous[0].gestion_externe).toBe(true);

    // Le filtre réduit les lignes, pas le résumé de l'immeuble.
    const impayes = grouperParImmeuble(lignes, "impayes");
    expect(impayes[2].lignes.map((l) => l.logement_numero)).toEqual(["2", "10"]);
    expect(resumeGroupe(impayes[2])).toBe("2 impayés sur 4 baux");
    // Un immeuble sans ligne dans le filtre disparaît.
    expect(grouperParImmeuble(lignes, "vacants").map((g) => g.immeuble_id)).toEqual([1]);
  });

  it("résumés d'immeuble", () => {
    expect(resumeGroupe({ nbBaux: 1, nbImpayes: 1, nbVacants: 0 })).toBe(
      "1 impayé sur 1 bail"
    );
    expect(resumeGroupe({ nbBaux: 10, nbImpayes: 0, nbVacants: 1 })).toBe(
      "10 baux, aucun impayé"
    );
    expect(resumeGroupe({ nbBaux: 0, nbImpayes: 0, nbVacants: 2 })).toBe(
      "2 logements vacants"
    );
    // Gestion externe : suivi par logement, pas de bail chez nous.
    expect(
      resumeGroupe({ nbBaux: 3, nbImpayes: 2, nbVacants: 0, gestion_externe: true })
    ).toBe("2 impayés sur 3 logements");
  });

  it("liens déjà filtrés : mots de l'écran actuel et du nouveau", () => {
    expect(filtreDepuisUrl("retard")).toBe("impayes");
    expect(filtreDepuisUrl("partiel")).toBe("impayes");
    expect(filtreDepuisUrl("paye")).toBe("payes");
    expect(filtreDepuisUrl("vacant")).toBe("vacants");
    expect(filtreDepuisUrl("all")).toBe("tous");
    expect(filtreDepuisUrl("n'importe quoi")).toBeNull();
    expect(filtreDepuisUrl(null)).toBeNull();
  });
});
