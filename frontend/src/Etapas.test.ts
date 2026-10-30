import { describe, expect, it } from "vitest";
import { etapaDe } from "./Etapas";

describe("etapaDe", () => {
  // Gate Sol S2 (#281): a medicao que nasce pela planilha/carta estava aparecendo como encerrada (0)
  it("os passos da planilha/carta e do boletim ficam antes do espelho, nunca como encerrada", () => {
    for (const estado of ["planilha_gerada", "planilha_enviada", "boletim_recebido"]) {
      expect(etapaDe(estado)).toBe(1);
    }
  });

  it("cancelada e desistida continuam encerradas", () => {
    expect(etapaDe("cancelada")).toBe(0);
    expect(etapaDe("desistida")).toBe(0);
  });
});
