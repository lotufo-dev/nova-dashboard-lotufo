import { describe, expect, it } from "vitest";
import { contratanteDe, porComQuem, type LinhaFila } from "./filaMedicoes";

const linha = (id: number, com_quem: LinhaFila["com_quem"]) => ({ medicao_id: id, com_quem }) as LinhaFila;

describe("filaMedicoes (#805)", () => {
  it("separa as linhas por quem tem de agir, na ordem Lotufo, faturamento, órgão, mantendo a ordem do servidor em cada grupo", () => {
    const grupos = porComQuem([linha(1, "orgao"), linha(2, "lotufo"), linha(3, "orgao"), linha(4, "lotufo")]);
    expect(grupos.map(g => [g.com_quem, g.linhas.map(l => l.medicao_id)])).toEqual([["lotufo", [2, 4]], ["orgao", [1, 3]]]);
  });

  it("grupo vazio não aparece", () => {
    expect(porComQuem([])).toEqual([]);
    expect(porComQuem([linha(1, "faturamento")]).map(g => g.com_quem)).toEqual(["faturamento"]);
  });

  it("o contratante com a superintendência ao lado; sem ela, só a sigla", () => {
    expect(contratanteDe({ contratante: "SINFRA", orgao_sub: "SUEF II" })).toBe("SINFRA · SUEF II");
    expect(contratanteDe({ contratante: "MTPAR", orgao_sub: null })).toBe("MTPAR");
    expect(contratanteDe({ contratante: null, orgao_sub: null })).toBe("");
  });
});
