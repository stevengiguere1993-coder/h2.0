import { describe, expect, it } from "vitest";

import {
  appliquerSuffixeCivique,
  decomposerCivique,
  nettoyerSuffixeCivique
} from "./adresse-civique";

describe("decomposerCivique", () => {
  it("lit un numéro civique sans suffixe", () => {
    expect(decomposerCivique("8900 Rue Lajeunesse, Montréal, QC, H2M 1S2")).toEqual({
      numero: "8900",
      suffixe: "",
      reste: " Rue Lajeunesse, Montréal, QC, H2M 1S2"
    });
  });

  it("lit un suffixe collé : lettre, ½, tiret", () => {
    expect(decomposerCivique("8900A Rue X")?.suffixe).toBe("A");
    expect(decomposerCivique("8900AB Rue X")?.suffixe).toBe("AB");
    expect(decomposerCivique("8900½ Rue X")?.suffixe).toBe("½");
    expect(decomposerCivique("8900-2 Rue X")?.suffixe).toBe("-2");
    expect(decomposerCivique("8900-A Rue X")?.suffixe).toBe("-A");
  });

  it("marche sur un numéro seul, en cours de frappe", () => {
    expect(decomposerCivique("8900")).toEqual({ numero: "8900", suffixe: "", reste: "" });
    expect(decomposerCivique("8900A")).toEqual({ numero: "8900", suffixe: "A", reste: "" });
    expect(decomposerCivique("8900,")?.suffixe).toBe("");
  });

  it("ignore une unité devant (Postes Canada) ou une plage de numéros", () => {
    expect(decomposerCivique("3-8900 Rue X")).toBeNull();
    expect(decomposerCivique("8900-8902 Rue X")).toBeNull();
  });

  it("rend null sans numéro civique", () => {
    expect(decomposerCivique("")).toBeNull();
    expect(decomposerCivique("Rue Lajeunesse, Montréal")).toBeNull();
    expect(decomposerCivique("Bureau Horizon")).toBeNull();
  });
});

describe("nettoyerSuffixeCivique", () => {
  it("enlève les espaces, met en majuscules et borne à 4 signes", () => {
    expect(nettoyerSuffixeCivique(" a ")).toBe("A");
    expect(nettoyerSuffixeCivique("abcdef")).toBe("ABCD");
    expect(nettoyerSuffixeCivique("-2")).toBe("-2");
  });

  it("traduit 1/2 en ½ et jette la ponctuation", () => {
    expect(nettoyerSuffixeCivique("1/2")).toBe("½");
    expect(nettoyerSuffixeCivique("A.")).toBe("A");
    expect(nettoyerSuffixeCivique("é")).toBe("");
  });
});

describe("appliquerSuffixeCivique", () => {
  const adresse = "8900 Rue Lajeunesse, Montréal, QC, H2M 1S2";

  it("colle le suffixe au numéro civique", () => {
    expect(appliquerSuffixeCivique(adresse, "a")).toBe(
      "8900A Rue Lajeunesse, Montréal, QC, H2M 1S2"
    );
  });

  it("remplace un suffixe déjà présent, ou l'enlève", () => {
    const avec = appliquerSuffixeCivique(adresse, "A");
    expect(appliquerSuffixeCivique(avec, "B")).toBe(
      "8900B Rue Lajeunesse, Montréal, QC, H2M 1S2"
    );
    expect(appliquerSuffixeCivique(avec, "")).toBe(adresse);
  });

  it("laisse l'adresse telle quelle sans numéro civique", () => {
    expect(appliquerSuffixeCivique("Rue Lajeunesse", "A")).toBe("Rue Lajeunesse");
    expect(appliquerSuffixeCivique("", "A")).toBe("");
  });

  it("est relisible : ce qu'on pose se relit tel quel", () => {
    for (const s of ["A", "AB", "½", "-2", "-A", "A1"]) {
      expect(decomposerCivique(appliquerSuffixeCivique(adresse, s))?.suffixe).toBe(s);
    }
  });
});
