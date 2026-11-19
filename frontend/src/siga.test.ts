import { describe, expect, it } from "vitest";
import {
  casaComBusca, categoriaDaBusca, contagemPorTipo, detalheDoEvento, ehEntradaNoSetorAtual, filtrarMovimentacoes, naoLidoDe, nomeDoProcesso, ordenar, periodoDe, porCategoria, situacaoDoAtraso,
  roboAtivo, setorPessoa, situacaoDoBotao, tempoNoSetor, textoSemMovimentacao, dataHoraCurta, tituloDoEvento, volumeDe, type Movimentacao, type ProcessoSiga, type Robo,
} from "./siga";

const p = (extra: Partial<ProcessoSiga>): ProcessoSiga => ({
  id: 1, codigo: null, link: null, numero: null, nome: null, contrato_id: null, obra: null, medicao_id: null,
  categoria: "outros", complemento: null, o_que_e: "Outro", categoria_a_conferir: null, contratante: null, orgao_sub: null,
  situacao_tempo: null, medicao_titulo: null, protocolo_id: null, situacao: null, encerrado: null, setor: "", caixa_entrada: false, com_quem: "",
  desde: null, dias_uteis: null, dias_sem_movimentacao: null, hoje: 0, ultima: null, protocolado_em: null, movimentacoes: [], ...extra });

describe("siga", () => {
  it("o atraso (quadro de Medições) é a leitura do servidor sem o 'em andamento': só o atraso e o andou hoje levam marca (#840)", () => {
    expect((["feito", "andamento", "breve", "critico", null] as const).map(s => situacaoDoAtraso({ situacao_tempo: s })))
      .toEqual(["feito", undefined, "breve", "critico", undefined]);
  });

  it("Dias sem movimentação: andou hoje, dias úteis do servidor, menos de 1 dia útil e sem movimentação (#840)", () => {
    expect(textoSemMovimentacao(p({ hoje: 1, dias_sem_movimentacao: 0 }))).toBe("andou hoje");
    expect(textoSemMovimentacao(p({ dias_sem_movimentacao: 1 }))).toBe("1 dia útil");
    expect(textoSemMovimentacao(p({ dias_sem_movimentacao: 12 }))).toBe("12 dias úteis");
    expect(textoSemMovimentacao(p({ dias_sem_movimentacao: 0 }))).toBe("menos de 1 dia útil");
    expect(textoSemMovimentacao(p({}))).toBe("—");
  });

  it("Última movimentação em data e hora; o ano só quando não é o de hoje (#840)", () => {
    const agora = new Date("2026-10-26T15:00:00Z");
    expect(dataHoraCurta("2026-10-23T17:05:00-04:00", agora)).toBe("23/10 17:05");
    expect(dataHoraCurta("2025-12-30T08:00:00-04:00", agora)).toBe("30/12/2025 08:00");
  });

  it("a categoria escolhida vem da URL (?categoria=); sem ela, ou com valor que não é categoria, todas (#805)", () => {
    expect(categoriaDaBusca({ categoria: "aditivos" })).toBe("aditivos");
    expect(categoriaDaBusca({ categoria: "medicoes", processo: "3" })).toBe("medicoes");
    expect(categoriaDaBusca({})).toBeNull();
    expect(categoriaDaBusca({ categoria: "reajustes" })).toBeNull();   // nao e' categoria do sistema
    expect(categoriaDaBusca({ categoria: "toString" })).toBeNull();
  });

  it("o não lido do processo: o aviso do robô para ele, sem as palavras que viram a etiqueta (#805)", () => {
    const robo: Robo = { estado: "parado", rodada: null, pedidos: [], avisos: [
      { tipo: "nao_lidos", processo_id: null, texto: "1 de 2 processos não foi lido" },
      { tipo: "nao_lido", processo_id: 4, texto: "não lido às 11:02: A página não abriu" },
      { tipo: "falha", processo_id: 5, texto: "outro aviso" },
    ] };
    expect(naoLidoDe(robo, 4)).toBe("às 11:02: A página não abriu");
    expect(naoLidoDe(robo, 5)).toBeNull();     // so' o aviso de nao lido vira etiqueta
    expect(naoLidoDe(robo, 9)).toBeNull();
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

  it("ordem: do mais parado ao menos (dias sem movimentação, #840), empate pela última movimentação mais antiga; o tempo no setor não conta; sem movimentação vai para o fim", () => {
    const ultima = (data: string): Movimentacao => ({ data, evento: "Recebimento", tipo: "recebimento", cad_lotacao: "", cad_pessoa: "", at_lotacao: "", at_pessoa: "" });
    const lista = [
      p({ id: 1, dias_sem_movimentacao: 6, ultima: ultima("2026-10-20T10:00:00-04:00") }),
      p({ id: 2, dias_sem_movimentacao: 6, ultima: ultima("2026-10-19T10:00:00-04:00") }),
      p({ id: 3, hoje: 1, dias_uteis: 40, dias_sem_movimentacao: 0, ultima: ultima("2026-10-28T09:00:00-04:00") }),
      p({ id: 4, dias_sem_movimentacao: null }),
      p({ id: 5, dias_uteis: 12, dias_sem_movimentacao: 12, ultima: ultima("2026-10-10T10:00:00-04:00") }),
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

  it("seções por categoria na ordem fixa, cada uma do mais parado ao menos; a vazia não aparece (#663)", () => {
    const lista = [
      p({ id: 1, categoria: "outros", dias_sem_movimentacao: 1 }), p({ id: 2, categoria: "medicoes", dias_sem_movimentacao: 2 }),
      p({ id: 3, categoria: "outros", dias_sem_movimentacao: 9 }), p({ id: 4, categoria: "medicoes", dias_sem_movimentacao: 7 }),
      p({ id: 5, categoria: "aditivos", dias_sem_movimentacao: 30 }),
    ];
    expect(porCategoria(lista).map(s => [s.rotulo, s.processos.map(x => x.id)])).toEqual(
      [["Medições", [4, 2]], ["Aditivos", [5]], ["Outros", [3, 1]]]);
    expect(porCategoria([])).toEqual([]);
  });

  it("nome montado: '<obra> · <o que é>', sem o número; sem obra, o complemento e depois o nome do robô (#663)", () => {
    const base = { nome: "Nome do robô", numero: "ORGAO-PRO-2026/00011", codigo: "ABC123" };
    expect(nomeDoProcesso(p({ ...base, obra: "Obra Alfa", categoria: "aditivos", complemento: "de prazo", o_que_e: "Aditivo de prazo" }))).toBe("Obra Alfa · Aditivo de prazo");
    expect(nomeDoProcesso(p({ ...base, obra: "Obra Alfa", categoria: "medicoes", medicao_id: 3, medicao_titulo: "7ª Medição", o_que_e: "7ª Medição" }))).toBe("Obra Alfa · 7ª Medição");
    expect(nomeDoProcesso(p({ ...base, complemento: "Licença ambiental", o_que_e: "Licença ambiental" }))).toBe("Licença ambiental");
    expect(nomeDoProcesso(p(base))).toBe("Nome do robô");
    expect(nomeDoProcesso(p({ ...base, nome: null }))).toBe("ORGAO-PRO-2026/00011");
    expect(nomeDoProcesso(p({}))).toBe("Processo sem nome");
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
