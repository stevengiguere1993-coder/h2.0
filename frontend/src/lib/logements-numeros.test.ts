import { describe, expect, it } from "vitest";

import {
  cleNumero,
  composerNumeroLogement,
  decomposerNumeroLogement,
  exempleNumeros,
  LOGEMENTS_LOT_MAX,
  nettoyerSuffixeLogement,
  numerosDuLot,
  type LotNumerosParams
} from "./logements-numeros";

const base: LotNumerosParams = {
  mode: "plage",
  de: "1",
  a: "",
  prefixe: "",
  suffixe: "",
  liste: ""
};

describe("numerosDuLot — suite de numéros", () => {
  it("génère la suite du premier au dernier", () => {
    expect(numerosDuLot({ ...base, a: "4" })).toEqual(["1", "2", "3", "4"]);
  });

  it("pose le texte avant / après chaque numéro", () => {
    expect(numerosDuLot({ ...base, a: "3", prefixe: "A-" })).toEqual(["A-1", "A-2", "A-3"]);
    expect(numerosDuLot({ ...base, a: "2", suffixe: "B" })).toEqual(["1B", "2B"]);
    expect(numerosDuLot({ ...base, de: "101", a: "102", prefixe: " ", suffixe: " " })).toEqual([
      "101",
      "102"
    ]);
  });

  it("ne rend rien tant que la plage est incomplète ou à l'envers", () => {
    expect(numerosDuLot(base)).toEqual([]);
    expect(numerosDuLot({ ...base, de: "5", a: "2" })).toEqual([]);
    expect(numerosDuLot({ ...base, de: "x", a: "2" })).toEqual([]);
  });

  it("plafonne à 300 numéros", () => {
    expect(numerosDuLot({ ...base, a: "1000" })).toHaveLength(LOGEMENTS_LOT_MAX);
  });

  it("ignore la liste quand le mode est « plage »", () => {
    expect(numerosDuLot({ ...base, a: "2", liste: "9, 10" })).toEqual(["1", "2"]);
  });
});

describe("numerosDuLot — liste", () => {
  it("découpe sur virgules, points-virgules et retours à la ligne", () => {
    expect(numerosDuLot({ ...base, mode: "liste", liste: "101, 102;201\n202" })).toEqual([
      "101",
      "102",
      "201",
      "202"
    ]);
  });

  it("retire les doublons à la casse et à la ponctuation près", () => {
    expect(numerosDuLot({ ...base, mode: "liste", liste: "301A, 301-a, 301 A, 302" })).toEqual([
      "301A",
      "302"
    ]);
  });

  it("ignore la plage quand le mode est « liste »", () => {
    expect(numerosDuLot({ ...base, mode: "liste", a: "5", liste: "7" })).toEqual(["7"]);
  });
});

describe("cleNumero / exempleNumeros", () => {
  it("normalise comme le serveur", () => {
    expect(cleNumero(" 301-A ")).toBe("301a");
  });

  it("illustre un préfixe / suffixe", () => {
    expect(exempleNumeros("A-", "")).toBe("A-1, A-2, A-3…");
    expect(exempleNumeros("", "B", 101)).toBe("101B, 102B, 103B…");
  });
});

describe("suffixe du numéro d'un logement (976 - A)", () => {
  it("nettoie ce qui est tapé dans la case Suffixe", () => {
    expect(nettoyerSuffixeLogement(" a ")).toBe("A");
    expect(nettoyerSuffixeLogement("-a1")).toBe("A1");
    expect(nettoyerSuffixeLogement("abcdef")).toBe("ABCD");
    expect(nettoyerSuffixeLogement("")).toBe("");
  });

  it("recolle numéro et suffixe avec un tiret", () => {
    expect(composerNumeroLogement("976", "A")).toBe("976-A");
    expect(composerNumeroLogement(" 976 ", " B ")).toBe("976-B");
    expect(composerNumeroLogement("976-", "A")).toBe("976-A");
    expect(composerNumeroLogement("976", "")).toBe("976");
    expect(composerNumeroLogement("976", " - ")).toBe("976");
    expect(composerNumeroLogement("", "A")).toBe("A");
    expect(composerNumeroLogement("A-1", "")).toBe("A-1");
  });

  it("sépare un numéro enregistré en ses deux cases", () => {
    expect(decomposerNumeroLogement("976-A")).toEqual({ numero: "976", suffixe: "A" });
    expect(decomposerNumeroLogement(" 8906-c ")).toEqual({ numero: "8906", suffixe: "c" });
    expect(decomposerNumeroLogement("12-B2")).toEqual({ numero: "12", suffixe: "B2" });
  });

  it("laisse entier un numéro d'une autre forme", () => {
    for (const n of ["101", "A-1", "976A", "3-8900", "976-2", "976-ABCDE", ""]) {
      expect(decomposerNumeroLogement(n)).toEqual({ numero: n, suffixe: "" });
    }
  });

  it("fait l'aller-retour sans changer un numéro existant", () => {
    for (const n of ["976-A", "8906-C", "8906-c", "101", "A-1", "976A", "3-8900", "1B"]) {
      const d = decomposerNumeroLogement(n);
      expect(composerNumeroLogement(d.numero, d.suffixe)).toBe(n);
    }
  });
});
