import { describe, expect, it } from "vitest";
import { casaComBusca, nivelDias, ordenar, tempoNoSetor, tituloDoEvento, volumeDe, type ProcessoSiga } from "./siga";

const p = (extra: Partial<ProcessoSiga>): ProcessoSiga => ({
  id: 1, codigo: null, link: null, numero: null, nome: null, contrato_id: null, obra: null, medicao_id: null,
  medicao_titulo: null, protocolo_id: null, situacao: null, setor: "", caixa_entrada: false, com_quem: "",
  desde: null, dias_uteis: null, hoje: 0, ultima: null, protocolado_em: null, movimentacoes: [], ...extra });

describe("siga", () => {
  it("nível pelos dias úteis: âmbar em 5, vermelho em 10", () => {
    expect([null, 0, 4, 5, 9, 10, 30].map(nivelDias)).toEqual([null, null, null, "atencao", "atencao", "acao", "acao"]);
  });

  it("No setor há: dias úteis, depois minutos, horas e, passado um dia corrido sem dia útil, 'menos de 1 dia útil'", () => {
    const agora = new Date("2026-10-26T15:00:00Z");   // segunda, 11h00 em Cuiaba
    expect(tempoNoSetor(p({ desde: "2026-10-23T09:00:00-04:00", dias_uteis: 1 }), agora)).toBe("1 dia útil");
    expect(tempoNoSetor(p({ desde: "2026-10-23T09:00:00-04:00", dias_uteis: 8 }), agora)).toBe("8 dias úteis");
    expect(tempoNoSetor(p({ desde: "2026-10-26T10:45:00-04:00", dias_uteis: 0 }), agora)).toBe("15 min");
    expect(tempoNoSetor(p({ desde: "2026-10-26T08:00:00-04:00", dias_uteis: 0 }), agora)).toBe("3 h");
    expect(tempoNoSetor(p({ desde: "2026-10-24T09:00:00-04:00", dias_uteis: 0 }), agora)).toBe("menos de 1 dia útil");
    expect(tempoNoSetor(p({ desde: null, dias_uteis: null }), agora)).toBe("—");
  });

  it("ordem: hoje primeiro (o mais recente no topo), depois mais dias úteis; empate pelo mais antigo no setor", () => {
    const lista = [
      p({ id: 1, dias_uteis: 6, desde: "2026-10-20T10:00:00-04:00" }),
      p({ id: 2, dias_uteis: 6, desde: "2026-10-19T10:00:00-04:00" }),
      p({ id: 3, hoje: 1, ultima: { data: "2026-10-28T09:00:00-04:00", evento: "", cad_lotacao: "", cad_pessoa: "", at_lotacao: "", at_pessoa: "" } }),
      p({ id: 4, hoje: 1, ultima: { data: "2026-10-28T10:00:00-04:00", evento: "", cad_lotacao: "", cad_pessoa: "", at_lotacao: "", at_pessoa: "" } }),
      p({ id: 5, dias_uteis: 12, desde: "2026-10-10T10:00:00-04:00" }),
    ];
    expect(ordenar(lista).map(x => x.id)).toEqual([4, 3, 5, 2, 1]);
    expect(lista.map(x => x.id)).toEqual([1, 2, 3, 4, 5]);   // não mexe na lista de entrada
  });

  it("volume só aparece depois do primeiro, e vale o último da situação", () => {
    expect(volumeDe("1º Volume - Aguardando Andamento [COFIN, [X]]")).toBe("");
    expect(volumeDe("1º Volume - Arquivado [PROTOC, [Y]] | 2º Volume - Aguardando Andamento [COFIN, [X]]")).toBe("(2º Volume)");
    expect(volumeDe(null)).toBe("");
  });

  it("evento sem o texto depois de ' |'", () => {
    expect(tituloDoEvento("Recebimento | texto do órgão")).toBe("Recebimento");
    expect(tituloDoEvento(null)).toBe("");
  });

  it("busca por obra ignora maiúscula e acento e olha também o nome do robô e o número", () => {
    const x = p({ obra: "Obra Épsilon", nome: "Processo X", numero: "ORGAO-PRO-2026/00011", medicao_titulo: "2ª Medição" });
    expect(["epsilon", "PROCESSO x", "pro-2026/00011", "", "  "].map(q => casaComBusca(x, q))).toEqual([true, true, true, true, true]);
    expect(casaComBusca(x, "beta")).toBe(false);
  });
});
