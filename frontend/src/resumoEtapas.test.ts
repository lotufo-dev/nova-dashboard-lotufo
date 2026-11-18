import { describe, expect, it } from "vitest";
import { linhasDaEtapa, mesDaUltima, nomeDaMesmaAltura, nomeDaReferencia, temDiferenca, type Linha } from "./resumoEtapas";

const linha = (x: Partial<Linha>): Linha => ({
  contrato_id: 1, obra: "Obra Própria", contratante: "Secretaria de Exemplo", medicao_id: 1, medicao_ids: [1], titulo: "1ª Medição",
  numero: 1, tipo: "execucao", competencia: "2026-10", etapa: "nota", etapas: [], valor_centavos: null,
  parada: null, recebida_em: null, dias_da_nota_ao_recebimento: null,
  pedido_do_aprovado_centavos: null, abaixo_do_pedido_centavos: null, acima_do_pedido_centavos: null, ...x,
});

describe("resumoEtapas (#805)", () => {
  it("a referência do mesmo ano leva só o mês; a de outro ano, o ano junto", () => {
    expect(nomeDaReferencia("2026-09", "2026-10")).toEqual({ curto: "set", extenso: "setembro" });
    expect(nomeDaReferencia("2025-10", "2026-10")).toEqual({ curto: "out/25", extenso: "outubro de 2025" });
    expect(mesDaUltima("2025-12", "2026-10")).toBe("dez/25");
  });

  it("a mesma altura diz a competência e até que dia", () => {
    expect(nomeDaMesmaAltura("2026-09", "2026-10-18", "2026-10")).toEqual({ curto: "set até 18/10", extenso: "setembro até 18 de outubro" });
    // janeiro olha dezembro do ano anterior, ate' um dia de dezembro
    expect(nomeDaMesmaAltura("2025-12", "2026-01-05", "2026-01")).toEqual({ curto: "dez/25 até 05/01", extenso: "dezembro de 2025 até 5 de janeiro" });
  });

  it("só há diferença a mostrar quando o servidor manda o corte ou o acima", () => {
    expect(temDiferenca(linha({}))).toBe(false);
    expect(temDiferenca(linha({ pedido_do_aprovado_centavos: 100, abaixo_do_pedido_centavos: 0, acima_do_pedido_centavos: 0 }))).toBe(false);
    expect(temDiferenca(linha({ pedido_do_aprovado_centavos: 100, abaixo_do_pedido_centavos: 7, acima_do_pedido_centavos: 0 }))).toBe(true);
    expect(temDiferenca(linha({ pedido_do_aprovado_centavos: 100, abaixo_do_pedido_centavos: 0, acima_do_pedido_centavos: 7 }))).toBe(true);
  });

  it("as linhas de uma etapa saem da maior para a menor; sem valor, por último", () => {
    const linhas = [linha({ medicao_id: 1, valor_centavos: 10 }), linha({ medicao_id: 2, valor_centavos: null }),
      linha({ medicao_id: 3, valor_centavos: 30 }), linha({ medicao_id: 4, etapa: "boletim", valor_centavos: 99 })];
    expect(linhasDaEtapa(linhas, "nota").map(l => l.medicao_id)).toEqual([3, 1, 2]);
    expect(linhasDaEtapa(linhas, "recebido")).toEqual([]);
  });
});
