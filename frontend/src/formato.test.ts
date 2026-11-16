import { describe, expect, it } from "vitest";
import { fmtPercentualDoCadastro } from "./formato";

describe("fmtPercentualDoCadastro", () => {
  it("lê o percentual como o cadastro o guarda: número, texto numérico, vírgula decimal e com o sinal de %", () => {
    expect(fmtPercentualDoCadastro(4.5)).toBe("4,5%");
    expect(fmtPercentualDoCadastro("4.5")).toBe("4,5%");
    expect(fmtPercentualDoCadastro("3,50")).toBe("3,5%");
    expect(fmtPercentualDoCadastro(" 6,76 % ")).toBe("6,76%");
    expect(fmtPercentualDoCadastro("1.234,5")).toBe("1.234,5%");
    expect(fmtPercentualDoCadastro("-0,35")).toBe("-0,35%");
    expect(fmtPercentualDoCadastro(0)).toBe("0%");
  });

  it("não arredonda o índice: até quatro casas", () => {
    expect(fmtPercentualDoCadastro("4,125")).toBe("4,125%");
    expect(fmtPercentualDoCadastro("4,1234")).toBe("4,1234%");
  });

  it("o que não é número não vira percentual (nem \"NaN%\")", () => {
    for (const ruim of ["", "   ", "%", "a definir", "3,5 a 4", "6,7,6", "6..7", "1e3", NaN, Infinity, null, undefined, true, {}, ["3,5"]])
      expect(fmtPercentualDoCadastro(ruim)).toBeNull();
  });
});
