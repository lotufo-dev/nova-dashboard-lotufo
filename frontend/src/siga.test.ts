import { describe, expect, it } from "vitest";
import {
  casaComBusca, contagemPorTipo, detalheDoEvento, ehEntradaNoSetorAtual, filtrarMovimentacoes, nivelDias, ordenar, periodoDe,
  roboAtivo, setorPessoa, situacaoDoBotao, tempoNoSetor, tituloDoEvento, volumeDe, type Movimentacao, type ProcessoSiga, type Robo,
} from "./siga";

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
    expect(tempoNoSetor(p({ desde: "ilegível", dias_uteis: 0 }), agora)).toBe("—");
  });

  it("ordem: do mais parado ao menos (dias úteis), empate pelo mais antigo no setor; quem andou hoje não sobe; sem data vai para o fim", () => {
    const lista = [
      p({ id: 1, dias_uteis: 6, desde: "2026-10-20T10:00:00-04:00" }),
      p({ id: 2, dias_uteis: 6, desde: "2026-10-19T10:00:00-04:00" }),
      p({ id: 3, hoje: 1, dias_uteis: 0, desde: "2026-10-28T09:00:00-04:00" }),
      p({ id: 4, dias_uteis: null, desde: null }),
      p({ id: 5, dias_uteis: 12, desde: "2026-10-10T10:00:00-04:00" }),
    ];
    expect(ordenar(lista).map(x => x.id)).toEqual([5, 2, 1, 3, 4]);
    expect(lista.map(x => x.id)).toEqual([1, 2, 3, 4, 5]);   // não mexe na lista de entrada
  });

  // issue #512: histórico do processo
  const mv = (data: string, evento: string, tipo: Movimentacao["tipo"], extra: Partial<Movimentacao> = {}): Movimentacao => ({
    data, evento, tipo, cad_lotacao: "COFIN/ORGAO", cad_pessoa: "Ana", at_lotacao: "CCONT/ORGAO", at_pessoa: "", ...extra });
  const MOVS = [
    mv("2026-10-02T09:00:00-04:00", "Transferência", "transferencia"),
    mv("2026-10-23T17:05:00-04:00", "Recebimento", "recebimento", { at_pessoa: "Athayde" }),
    mv("2026-10-21T10:37:00-04:00", "Juntada | documento ORGAO-DIC-2026/96012-A", "juntada"),
    mv("2026-10-21T08:35:00-04:00", "Marcação", "marcacao"),
    mv("2026-10-22T08:00:00-04:00", "Anotação", "outras", { cad_pessoa: "Beltrano" }),
  ];

  it("contagem por tipo e filtro por tipo, mais recente primeiro", () => {
    expect(contagemPorTipo(MOVS)).toEqual({ transferencia: 1, recebimento: 1, juntada: 1, marcacao: 1, outras: 1 });
    expect(filtrarMovimentacoes(MOVS, null, "").map(m => m.evento?.split(" ")[0])).toEqual(["Recebimento", "Anotação", "Juntada", "Marcação", "Transferência"]);
    expect(filtrarMovimentacoes(MOVS, "juntada", "")).toHaveLength(1);
    expect(filtrarMovimentacoes(MOVS, "outras", "")[0].evento).toBe("Anotação");
  });

  it("busca por setor, pessoa ou documento, sem maiúscula nem acento; combina com o tipo", () => {
    expect(filtrarMovimentacoes(MOVS, null, "athayde")).toHaveLength(1);
    expect(filtrarMovimentacoes(MOVS, null, "ccont")).toHaveLength(5);
    expect(filtrarMovimentacoes(MOVS, null, "96012")[0].tipo).toBe("juntada");
    expect(filtrarMovimentacoes(MOVS, "marcacao", "96012")).toHaveLength(0);
    expect(filtrarMovimentacoes(MOVS, null, "beltrano")[0].evento).toBe("Anotação");
  });

  it("documento da juntada, setor · pessoa e período", () => {
    expect(detalheDoEvento("Juntada | documento ORGAO-DIC-2026/96012-A")).toBe("documento ORGAO-DIC-2026/96012-A");
    expect(detalheDoEvento("Recebimento")).toBe("");
    expect(setorPessoa("COFIN/ORGAO", "Ana")).toBe("COFIN · Ana");
    expect(setorPessoa("COFIN/ORGAO", "")).toBe("COFIN");
    expect(setorPessoa("", "")).toBe("");
    expect(periodoDe(MOVS, iso => iso.slice(8, 10))).toBe("02 a 23");
    expect(periodoDe([], iso => iso)).toBe("");
  });

  it("destaca só a movimentação da entrada no setor atual: recebimento ou transferência (não na caixa de entrada)", () => {
    const rec = MOVS[1];
    expect(ehEntradaNoSetorAtual(p({ desde: rec.data }), rec)).toBe(true);
    expect(ehEntradaNoSetorAtual(p({ desde: rec.data, caixa_entrada: true }), rec)).toBe(false);
    expect(ehEntradaNoSetorAtual(p({ desde: MOVS[0].data }), rec)).toBe(false);
    // #650: a entrada no setor pode ser a transferência que levou o processo para lá
    const transf = MOVS.find(m => m.tipo === "transferencia")!;
    expect(ehEntradaNoSetorAtual(p({ desde: transf.data }), transf)).toBe(true);
    const outra = MOVS.find(m => m.tipo !== "transferencia" && m.tipo !== "recebimento")!;
    expect(ehEntradaNoSetorAtual(p({ desde: outra.data }), outra)).toBe(false);
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

  it("botão de atualizar: 'lendo' com a rodada que o cobre, 'na_fila' com pedido que o cobre, senão livre", () => {
    const robo = (extra: Partial<Robo>): Robo => ({ estado: "parado", rodada: null, pedidos: [], avisos: [], ...extra });
    const pedido = (processo_id: number | null, travado = false) =>
      ({ id: 1, processo_id, usuario: "Fulano", pedido_em: "2026-10-28T15:00:00+00:00", travado });
    const rodada = { id: 1, tipo: "pedido" as const, iniciada_em: "2026-10-28T15:00:00+00:00", processos: [1] };
    expect([situacaoDoBotao(robo({}), 1), situacaoDoBotao(robo({}), null)]).toEqual([null, null]);
    expect([1, 2, null].map(id => situacaoDoBotao(robo({ rodada }), id))).toEqual(["lendo", null, "lendo"]);
    expect([1, 2, null].map(id => situacaoDoBotao(robo({ pedidos: [pedido(1)] }), id))).toEqual(["na_fila", null, null]);
    expect([1, 2, null].map(id => situacaoDoBotao(robo({ pedidos: [pedido(null)] }), id))).toEqual(["na_fila", "na_fila", "na_fila"]);
    expect(situacaoDoBotao(robo({ rodada, pedidos: [pedido(2)] }), 2)).toBe("na_fila");
    // pedido travado (Windows recusou, robo nao comecou): o botao volta a valer para disparar de novo
    const travado = robo({ estado: "na_fila", pedidos: [pedido(null, true)] });
    expect([1, null].map(id => situacaoDoBotao(travado, id))).toEqual([null, null]);
    expect(situacaoDoBotao(robo({ pedidos: [pedido(null, true), pedido(1)] }), 1)).toBe("na_fila");
  });

  it("robô ativo (relê a cada 5 s): rodada ou pedido que vai andar sozinho; só pedido travado não conta", () => {
    const robo = (extra: Partial<Robo>): Robo => ({ estado: "na_fila", rodada: null, pedidos: [], avisos: [], ...extra });
    const pedido = (travado: boolean) => ({ id: 1, processo_id: null, usuario: "Fulano", pedido_em: "2026-10-28T15:00:00+00:00", travado });
    const rodada = { id: 1, tipo: "pedido" as const, iniciada_em: "2026-10-28T15:00:00+00:00", processos: [1] };
    expect(roboAtivo(robo({ estado: "parado" }))).toBe(false);
    expect(roboAtivo(robo({ pedidos: [pedido(false)] }))).toBe(true);
    expect(roboAtivo(robo({ pedidos: [pedido(true)] }))).toBe(false);
    expect(roboAtivo(robo({ estado: "lendo", rodada }))).toBe(true);
  });
});
