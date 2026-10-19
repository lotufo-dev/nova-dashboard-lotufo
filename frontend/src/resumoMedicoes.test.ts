import { describe, expect, it } from "vitest";
import { filtrarObras, nivelParada, porContratante, textoParada, type ObraResumo } from "./resumoMedicoes";

const obra = (contrato_id: number, nome: string, contratante: string, orgao_sub: string | null = null): ObraResumo =>
  ({ contrato_id, obra: nome, contratante, orgao_sub, aberta: false, prevista_id: null, encerramento: false,
    ultima: null, ha_dias: null, prevista: null, proxima: 1, proxima_tipo: "execucao" });

describe("página Medições (regras de apresentação)", () => {
  it("“Parada há”: hoje, 1 dia, N dias; sem marco, traço", () => {
    expect(textoParada(0)).toBe("hoje");
    expect(textoParada(1)).toBe("1\u00a0dia");
    expect(textoParada(24)).toBe("24\u00a0dias");
    expect(textoParada(null)).toBe("\u2014");
  });

  it("limiares: aguardando pagamento acende a partir de 30 e de 45 dias; o resto, depois de 7 e 15", () => {
    expect(nivelParada(29, "aguardando-pagamento")).toBeNull();
    expect(nivelParada(30, "aguardando-pagamento")).toBe("atencao");
    expect(nivelParada(44, "aguardando-pagamento")).toBe("atencao");
    expect(nivelParada(45, "aguardando-pagamento")).toBe("acao");
    expect(nivelParada(7, "enviar-nota")).toBeNull();
    expect(nivelParada(8, "enviar-nota")).toBe("atencao");
    expect(nivelParada(16, "faturamento")).toBe("acao");
    expect(nivelParada(null, "faturamento")).toBeNull();
  });

  it("agrupa por contratante, o grupo maior primeiro (empate pelo nome)", () => {
    const g = porContratante([obra(1, "MT-388", "SINFRA"), obra(2, "Granito", "MTPAR"), obra(3, "Leblon", "SINFRA"),
      obra(4, "Alta Floresta", "SES-MT")]);
    expect(g.map(x => [x.contratante, x.obras.length])).toEqual([["SINFRA", 2], ["MTPAR", 1], ["SES-MT", 1]]);
  });

  it("a busca da janela ignora acento e caixa e olha obra, contratante e sub-órgão", () => {
    const os = [obra(1, "Deciolândia", "SINFRA", "SUEF II"), obra(2, "Maternidade VG", "Pref. Várzea Grande")];
    expect(filtrarObras(os, "deciolandia").map(o => o.contrato_id)).toEqual([1]);
    expect(filtrarObras(os, "varzea").map(o => o.contrato_id)).toEqual([2]);
    expect(filtrarObras(os, "suef").map(o => o.contrato_id)).toEqual([1]);
    expect(filtrarObras(os, "  ")).toHaveLength(2);
  });
});
