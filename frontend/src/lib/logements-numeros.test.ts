import { describe, expect, it } from "vitest";

import {
  cleNumero,
  exempleNumeros,
  LOGEMENTS_LOT_MAX,
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
