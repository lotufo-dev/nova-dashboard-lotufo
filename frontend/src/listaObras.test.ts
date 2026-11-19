import { describe, expect, it } from "vitest";
import type { Aviso } from "./Alertas";
import {
  andamentoDaObra, avisoPrincipal, contratantesDe, contratantesPorContratado, criticosPorObra, escopoDaUrl, estaParalisada, execucaoVencida,
  filtrarObras, fimDaExecucao, gruposPorContratante, medidoDoMes, mesesDoMedido, participacao, pctExecutado, pctPiso, porAndamento, posicaoDe,
  prazoDaObra, resumoDe, totaisDe, type ObraLista,
} from "./listaObras";
import { leituraDeTeste } from "./andamentoTeste";
import type { AndamentoDoServidor } from "./valores";

const o = (id: number, nome: string, extra: Partial<ObraLista> = {}): ObraLista => ({
  id, orgao: "SINFRA", numero_instrumento: `${id}/2026`, nome_curto: nome, estado: "ativo", ...extra });

describe("lista de obras", () => {
  const lista = [
    o(1, "MT-388", { dias_execucao: 187, dias_vigencia: 277 }),
    o(2, "5 Bairros", { dias_execucao: 9, dias_vigencia: 3 }),
    o(3, "Granito", { dias_execucao: 150, dias_vigencia: 60 }),
    o(4, "Deciolândia", { estado: "encerrado", dias_execucao: -300 }),
    o(5, "Maternidade VG", { orgao: "SMS-VG", dias_execucao: 80, dias_vigencia: 40, vigencia_automatica: true }),
  ];

  it("em andamento por padrão, na ordem do nome; todas com o filtro", () => {
    expect(filtrarObras(lista, {}).map(x => x.nome_curto)).toEqual(["5 Bairros", "Granito", "Maternidade VG", "MT-388"]);
    expect(filtrarObras(lista, { todas: true })).toHaveLength(5);
  });

  it("terminam em 90 dias: execução ou vigência (a que o órgão não prorroga junto), a vencida na frente", () => {
    const comVencida = [...lista, o(6, "Terminais BRT", { dias_execucao: -24, dias_vigencia: -4 })];
    expect(filtrarObras(comVencida, { termina: 90 }).map(x => x.nome_curto)).toEqual(["Terminais BRT", "5 Bairros", "Granito", "Maternidade VG"]);
    // a encerrada, com prazo vencido ha' muito, nao entra mesmo com "todas"
    expect(filtrarObras(comVencida, { termina: 90, todas: true }).map(x => x.id)).not.toContain(4);
  });

  it("busca sem acento e sem caixa", () => {
    expect(filtrarObras([o(9, "Coxipó 2ª Etapa")], { q: "coxipo 2a" }).map(x => x.id)).toEqual([9]);
  });

  it("busca por nome ou instrumento, e órgão", () => {
    expect(filtrarObras(lista, { q: "mt-3" }).map(x => x.id)).toEqual([1]);
    expect(filtrarObras(lista, { q: "4/2026", todas: true }).map(x => x.id)).toEqual([4]);
    expect(filtrarObras(lista, { orgao: "SMS-VG" }).map(x => x.id)).toEqual([5]);
  });
});

describe("prazo da obra paralisada", () => {
  it("a data da paralisação vem da própria lista, também para obra suspensa sem aviso", () => {
    const p = prazoDaObra(o(7, "Parada", { estado: "suspenso", paralisada_desde: "2026-02-01" }), []);
    expect(p).toMatchObject({ paralisada: true, paralisadaDesde: "2026-02-01" });
  });

  it("obra sem paralisação não tem data", () => {
    expect(prazoDaObra(o(8, "Andando"), []).paralisadaDesde).toBeNull();
  });
});

describe("contratantes (entrada de Obras, #159)", () => {
  const cheia = (id: number, orgao: string, vigente: number, medido: number, extra: Partial<ObraLista> = {}) =>
    o(id, `Obra ${id}`, { orgao, valor_vigente_centavos: vigente, medido_centavos: medido, ...extra });
  const lista = [
    cheia(1, "SINFRA", 1000_00, 250_00), cheia(2, "SINFRA", 3000_00, 750_00),
    cheia(3, "MTPAR", 2000_00, 1000_00), cheia(4, "MTPAR", 500_00, 500_00, { estado: "encerrado" }),
  ];

  it("% executado da obra: medido de execução ÷ valor vigente, inteiro; sem vigente, nulo", () => {
    expect(pctExecutado(lista[0])).toBe(25);
    expect(pctExecutado(cheia(9, "X", 0, 0))).toBeNull();
    expect(pctExecutado(o(9, "Sem valor"))).toBeNull();
    // por piso: 99,6% e' 99%; so' quem concluiu mostra 100%
    expect(pctExecutado(cheia(9, "X", 1000_00, 996_00))).toBe(99);
    expect(pctExecutado(cheia(9, "X", 1000_00, 1000_00))).toBe(100);
    expect(pctPiso(2_66, 4_00)).toBe(66);
    expect(pctPiso(1, 0)).toBeNull();
  });

  it("com aditivo de reajuste, % e saldo usam o vigente de execução, como a página da obra (#262)", () => {
    const ses = cheia(7, "SES", 1200_00, 400_00, { valor_vigente_execucao_centavos: 1000_00 });
    expect(pctExecutado(ses)).toBe(40);
  });

  it("os contratantes da lista, em ordem alfabética", () => {
    expect(contratantesDe(lista)).toEqual(["MTPAR", "SINFRA"]);
  });

  it("o aviso principal da obra é o mais grave", () => {
    const av = (nivel: string, contrato_id: number) => ({ tipo: "x", nivel, contrato_id, mensagem: "m" }) as unknown as Aviso;
    const mapa = new Map<number, Aviso[]>([[1, [av("atencao", 1), av("critico", 1)]], [2, [av("acao", 2)]]]);
    expect(avisoPrincipal(mapa.get(1)!)?.nivel).toBe("critico");
  });

  it("a URL: sem filtro é a escolha do contratante; ?c=, ?orgao= e os filtros de antes abrem a lista", () => {
    expect(escopoDaUrl({})).toEqual({ escolha: true, orgao: null });
    expect(escopoDaUrl({ c: "todas" })).toEqual({ escolha: false, orgao: null });
    expect(escopoDaUrl({ c: "SINFRA" })).toEqual({ escolha: false, orgao: "SINFRA" });
    expect(escopoDaUrl({ orgao: "SMS-VG" })).toEqual({ escolha: false, orgao: "SMS-VG" });
    expect(escopoDaUrl({ termina: "90" })).toEqual({ escolha: false, orgao: null });
    expect(escopoDaUrl({ q: "granito" }).escolha).toBe(false);
  });

  it("a busca também acha pela empresa e pelo órgão", () => {
    const l = [cheia(1, "SINFRA", 1, 0, { entidade_id: 5 }), cheia(2, "MTPAR", 1, 0, { entidade_id: 6 })];
    const empresas = new Map([[5, "Construtora Alfa"], [6, "Beta Engenharia"]]);
    expect(filtrarObras(l, { q: "alfa", empresas }).map(x => x.id)).toEqual([1]);
    expect(filtrarObras(l, { q: "mtpar", empresas }).map(x => x.id)).toEqual([2]);
    expect(filtrarObras(l, { q: "alfa" })).toHaveLength(0);
  });
});

describe("lista de Obras na cota da Lotufo, por contratante (#645)", () => {
  // `posicao` vem do servidor já na cota; os cheios ao lado são de propósito outros, para a soma não os usar
  const naCota = (id: number, nome: string, contratante: string, vigente: number, medido: number, aReceber: number | null) =>
    o(id, nome, { contratante, orgao: `${contratante} - SUP`, valor_vigente_centavos: vigente * 2, valor_vigente_execucao_centavos: vigente * 2, medido_centavos: medido * 2,
      posicao: { vigente_centavos: vigente, medido_centavos: medido, saldo_centavos: vigente - medido, a_receber_centavos: aReceber } });
  const lista = [
    naCota(1, "Ponte", "SINFRA", 1000_01, 250_00, 100_01), naCota(2, "Avenida", "SINFRA", 3000_00, 750_33, 0),
    naCota(3, "Hospital", "MTPAR", 2000_00, 1000_00, 50_00),
  ];

  it("os totais somam as linhas na cota, sem arredondar de novo; a receber nulo fica sem valor", () => {
    expect(totaisDe(lista)).toEqual({ contratado: 6000_01, medido: 2000_33, saldo: 3999_68, aReceber: 150_01, temReceber: true,
      aReceberAnterior: 0, aReceberSemAtualizacao: 0, anoInicial: null });
    // docs/adr/0006: o a receber que fica fora do total soma 'a parte, obra a obra, sem entrar em `aReceber`
    const comAntigo = lista.map((o, i) => ({ ...o, posicao: { ...posicaoDe(o), a_receber_ano_inicial: "2025",
      a_receber_anterior_centavos: i === 0 ? 70_003 : 0, a_receber_sem_atualizacao_centavos: i === 1 ? 40_001 : 0 } }));
    expect(totaisDe(comAntigo)).toMatchObject({ aReceber: 150_01, aReceberAnterior: 70_003, aReceberSemAtualizacao: 40_001, anoInicial: "2025" });
    const semLiberar = lista.map(x => ({ ...x, posicao: { ...x.posicao!, a_receber_centavos: null } }));
    expect(totaisDe(semLiberar)).toMatchObject({ aReceber: 0, temReceber: false });
  });

  it("obra sem `posicao` conta zero e o % executado sai da posição", () => {
    expect(posicaoDe(o(9, "Sem posição", { valor_vigente_centavos: 500_00 }))).toEqual({ vigente_centavos: 0, medido_centavos: 0, saldo_centavos: 0, a_receber_centavos: null });
    // por piso: a cota arredonda os centavos e a razao fica um fio abaixo de 25%
    expect(pctExecutado(lista[0])).toBe(24);
  });

  it("agrupa por contratante na ordem do nome, as obras na ordem do nome, com o subtotal do grupo", () => {
    const grupos = gruposPorContratante(lista);
    expect(grupos.map(g => g.contratante)).toEqual(["MTPAR", "SINFRA"]);
    expect(grupos[1].obras.map(x => x.nome_curto)).toEqual(["Avenida", "Ponte"]);
    expect(grupos[1].subtotal).toMatchObject({ contratado: 4000_01, medido: 1000_33, saldo: 2999_68, aReceber: 100_01, temReceber: true });
    // a soma dos subtotais é o total do topo
    const t = totaisDe(lista);
    for (const k of ["contratado", "medido", "saldo", "aReceber"] as const) expect(grupos.reduce((a, g) => a + g.subtotal[k], 0)).toBe(t[k]);
  });

  it("a busca da lista acha por parte do nome ou do número do contrato; vazia, volta tudo", () => {
    expect(filtrarObras(lista, { q: "pon" }).map(x => x.id)).toEqual([1]);
    expect(filtrarObras(lista, { q: "3/2026" }).map(x => x.id)).toEqual([3]);
    expect(filtrarObras(lista, { q: "" })).toHaveLength(3);
  });
});

describe("Obras por contratante: andamento, medido do mês e o que pede atenção (#805)", () => {
  const mes = (valor: number, referencia: number | null, ref: string | null = "2026-09") =>
    ({ competencia: "2026-10", valor_centavos: valor, referencia_competencia: ref, referencia_centavos: referencia });
  // `leitura` e' a do servidor (#822); o dado de teste a monta pelo corte dele, ou com o motivo de ficar fora da regua
  const ritmo = (r: number | null, n: number | null, fora: Partial<AndamentoDoServidor> = {}) =>
    ({ ritmo_centavos: r, necessario_centavos: n, leitura: leituraDeTeste(r, n, fora) });
  const pos = (vigente: number, medido: number) => ({ vigente_centavos: vigente, medido_centavos: medido, saldo_centavos: vigente - medido, a_receber_centavos: null });
  const obras = [
    o(1, "Ponte", { contratante: "SINFRA", contratante_chave: "sinfra", posicao: pos(1000, 100), andamento: ritmo(69_999, 100_000), medido_mes: mes(500, 400) }),
    o(2, "Avenida", { contratante: "SINFRA", contratante_chave: "sinfra", posicao: pos(3000, 100), andamento: ritmo(70_000, 100_000), medido_mes: mes(100, 0) }),
    o(3, "Trevo", { contratante: "MTPAR", contratante_chave: "mtpar", posicao: pos(5000, 100), andamento: ritmo(100_000, 100_000), medido_mes: mes(0, 300) }),
    // sem ritmo (sem medição na janela), com prazo a cumprir; paralisada; e com a execução vencida
    o(4, "Anel", { contratante: "MTPAR", contratante_chave: "mtpar", andamento: ritmo(null, 50_000) }),
    o(5, "Orla", { orgao: "sem cadastro", estado: "suspenso", dias_execucao: -10, andamento: ritmo(10, null) }),
    o(6, "Cais", { orgao: "sem cadastro", dias_execucao: -3, andamento: ritmo(10, null) }),
  ];

  it("a leitura do andamento é a que o servidor mandou: a contagem nunca discorda da barra", () => {
    expect(obras.map(andamentoDaObra)).toEqual([
      { leitura: "devagar", pct: 69 }, { leitura: "atencao", pct: 70 }, { leitura: "adiantada", pct: 100 }, null, null, null]);
    const r = resumoDe(obras);
    expect([r.obras, r.comAndamento, r.devagar, r.atencao]).toEqual([6, 3, 1, 1]);
    // a tela não compara o ritmo com o necessário: sem a leitura do servidor não há leitura, e vale a palavra dele
    expect(andamentoDaObra(o(7, "X", { andamento: { ritmo_centavos: 10, necessario_centavos: 100 } }))).toBeNull();
    expect(andamentoDaObra(o(7, "X", { andamento: ritmo(120, 100, { situacao: "atencao", pct: 99 }) }))).toEqual({ leitura: "atencao", pct: 99 });
  });

  it("#822: a obra fora da régua não tem leitura e não entra em 'N devagar de M'", () => {
    // as três mediriam 10% do necessário (devagar), mas o servidor as tirou da régua
    const fora = [
      o(11, "Viaduto", { andamento: ritmo(10, 100, { motivo: "prazo_no_fim" }) }),
      o(12, "Trincheira", { andamento: ritmo(10, 100, { motivo: "prorrogacao_pedida", prorrogacao_pedida: true }) }),
      o(13, "Rotatória", { andamento: ritmo(10, 100, { motivo: "sem_medicao", sem_medicao_desde: "2026-07" }) }),
    ];
    expect(fora.map(andamentoDaObra)).toEqual([null, null, null]);
    const r = resumoDe([...obras, ...fora]);
    expect([r.obras, r.comAndamento, r.devagar, r.atencao]).toEqual([9, 3, 1, 1]);
    // a do prazo no fim é contada à parte; a da prorrogação pedida e a sem medição, não
    expect([r.prazoNoFim, resumoDe(obras).prazoNoFim]).toEqual([1, 0]);
  });

  it("paralisada e execução vencida: a vencida só conta na obra ativa, fora do encerramento e sem paralisação", () => {
    expect(obras.map(estaParalisada)).toEqual([false, false, false, false, true, false]);
    expect(obras.map(execucaoVencida)).toEqual([false, false, false, false, false, true]);
    expect(execucaoVencida(o(7, "X", { dias_execucao: -3, encerramento_iniciado_em: "2026-10-01" }))).toBe(false);
    expect(execucaoVencida(o(7, "X", { dias_execucao: -3, paralisada_desde: "2026-10-01" }))).toBe(false);
    expect(execucaoVencida(o(7, "X", { dias_execucao: null }))).toBe(false);           // sem prazo de execução conhecido (#662)
    expect(execucaoVencida(o(7, "X", { dias_execucao: 0 }))).toBe(false);              // no dia do fim ainda não venceu
    const r = resumoDe(obras);
    expect([r.paralisadas, r.execucaoVencida]).toEqual([1, 1]);
  });

  it("os avisos críticos contam por obra, dos avisos que a tela recebe", () => {
    const criticos = criticosPorObra([{ contrato_id: 1, nivel: "critico" }, { contrato_id: 1, nivel: "critico" }, { contrato_id: 1, nivel: "acao" },
      { contrato_id: 3, nivel: "critico" }, { contrato_id: null, nivel: "critico" }]);
    expect([...criticos]).toEqual([[1, 2], [3, 1]]);
    expect(resumoDe(obras, criticos).avisosCriticos).toBe(3);
    expect(resumoDe(obras.filter(x => x.contratante === "MTPAR"), criticos).avisosCriticos).toBe(1);
  });

  it("o medido do mês é só a soma do que o servidor mandou; sem referência que sirva, ela fica nula", () => {
    expect(medidoDoMes(obras)).toEqual({ competencia: "2026-10", valor_centavos: 600, referencia_competencia: "2026-09", referencia_centavos: 700 });
    expect(medidoDoMes([o(1, "A")])).toBeNull();
    const semReferencia = [o(1, "A", { medido_mes: mes(500, null, null) }), o(2, "B", { medido_mes: mes(100, null, null) })];
    expect(medidoDoMes(semReferencia)).toEqual({ competencia: "2026-10", valor_centavos: 600, referencia_competencia: null, referencia_centavos: null });
  });

  it("os nomes do mês do medido e da referência; referência de outro ano leva o ano", () => {
    expect(mesesDoMedido(mes(1, 1))).toEqual({ extenso: "outubro", curto: "out", referencia: { curto: "set", extenso: "setembro" } });
    expect(mesesDoMedido({ competencia: "2027-01", valor_centavos: 1, referencia_competencia: "2026-12", referencia_centavos: 1 }))
      .toEqual({ extenso: "janeiro", curto: "jan", referencia: { curto: "dez/26", extenso: "dezembro de 2026" } });
    expect(mesesDoMedido(mes(1, null, null)).referencia).toBeNull();
  });

  it("a vista Andamento: do menor para o maior percentual do necessário; sem ritmo vai ao fim; sem necessário fica fora", () => {
    expect(porAndamento(obras).map(x => x.nome_curto)).toEqual(["Ponte", "Avenida", "Trevo", "Anel"]);
    // no mesmo percentual inteiro, a razão exata desempata
    const empate = [o(1, "B", { andamento: ritmo(27_900, 100_000) }), o(2, "A", { andamento: ritmo(27_100, 100_000) })];
    expect(porAndamento(empate).map(x => x.nome_curto)).toEqual(["A", "B"]);
  });

  it("#822: na vista Andamento, depois das obras com leitura vêm a sem medição, a com o prazo no fim ou a prorrogação pedida e a sem nada a escrever", () => {
    const fora = [
      o(11, "Viaduto", { execucao_fim_vigente: "2026-12-20", andamento: ritmo(10, 100, { motivo: "prazo_no_fim" }) }),
      o(12, "Trincheira", { execucao_fim_vigente: "2027-08-31", andamento: ritmo(10, 100, { motivo: "prorrogacao_pedida", prorrogacao_pedida: true }) }),
      o(13, "Rotatória", { andamento: ritmo(10, 100, { motivo: "sem_medicao", sem_medicao_desde: "2026-07" }) }),
      o(14, "Balsa", { andamento: ritmo(null, 100, { motivo: "sem_medicao", sem_medicao_desde: "2026-02" }) }),
      o(15, "Acesso", { execucao_fim_vigente: "2026-11-30", andamento: ritmo(200, 100, { motivo: "prazo_no_fim", prorrogacao_pedida: true }) }),
    ];
    expect(porAndamento([...fora, ...obras]).map(x => x.nome_curto)).toEqual(
      ["Ponte", "Avenida", "Trevo", "Balsa", "Rotatória", "Acesso", "Viaduto", "Trincheira", "Anel"]);
  });

  it("os blocos vão do maior contratado para o menor, com a chave da página; a participação tem uma casa", () => {
    const grupos = contratantesPorContratado(obras);
    expect(grupos.map(g => [g.contratante, g.chave, g.subtotal.contratado])).toEqual([["MTPAR", "mtpar", 5000], ["SINFRA", "sinfra", 4000], ["sem cadastro", null, 0]]);
    expect(participacao(4000, 9000)).toMatch(/^44,4\s?%$/);
    expect(participacao(4500, 9000)).toMatch(/^50\s?%$/);
    expect(participacao(1, 0)).toBeNull();
    expect(fimDaExecucao("2027-03-31")).toBe("execução até 31/03/2027");
    expect(fimDaExecucao(null)).toBeNull();
  });
});
