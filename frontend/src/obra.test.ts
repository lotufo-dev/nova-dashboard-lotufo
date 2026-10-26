import { describe, expect, it } from "vitest";
import { curvaS, desfechoDoPedido, diasEntre, instrumentosDaObra, linhaDoTempo, reajustePorDataBase } from "./obra";

describe("Página da obra: curva S e linhas do tempo", () => {
  const p = (competencia: string, prev: number, exec: number, pend = false) =>
    ({ competencia, previsto_centavos: prev, medido_execucao_centavos: exec, atestado_pendente: pend });

  it("a curva acumula previsto e medido e para o medido na última competência medida", () => {
    const c = curvaS([p("2026-03", 100, 0), p("2026-01", 100, 80), p("2026-02", 100, 0), p("2026-04", 100, 0)]);
    expect(c.map(x => x.competencia)).toEqual(["2026-01", "2026-02", "2026-03", "2026-04"]);
    expect(c.map(x => x.acumuladoPrevisto)).toEqual([100, 200, 300, 400]);
    expect(c.map(x => x.acumuladoMedido)).toEqual([80, null, null, null]);
    const d = curvaS([p("2026-01", 100, 50), p("2026-02", 100, 0), p("2026-03", 100, 70, true)]);
    expect(d.map(x => x.acumuladoMedido)).toEqual([50, 50, 120]);
    expect(d.map(x => x.provisorio)).toEqual([false, false, true]);
  });

  it("a curva preenche os meses sem previsto nem medido, para o eixo ser de tempo", () => {
    const c = curvaS([p("2026-01", 100, 10), p("2026-04", 100, 0)]);
    expect(c.map(x => x.competencia)).toEqual(["2026-01", "2026-02", "2026-03", "2026-04"]);
    expect(c.map(x => x.acumuladoPrevisto)).toEqual([100, 100, 100, 200]);
    expect(curvaS([p("2025-12", 1, 0), p("2026-01", 1, 0)]).map(x => x.competencia)).toEqual(["2025-12", "2026-01"]);
  });

  it("a linha do tempo põe o hoje entre o início e o fim, conta os dias e aceita início ausente", () => {
    expect(diasEntre("2026-10-16", "2026-10-26")).toBe(10);
    const meio = linhaDoTempo("2026-01-01", "2026-12-31", "2026-07-02");
    expect(Math.round(meio.posicao ?? -1)).toBe(50);
    expect(meio.restantes).toBe(182);
    expect(linhaDoTempo("2026-01-01", "2026-12-31", "2027-02-01").posicao).toBe(100);
    expect(linhaDoTempo("2026-01-01", "2026-12-31", "2025-12-01").posicao).toBe(0);
    expect(linhaDoTempo(null, "2026-12-31", "2026-12-30")).toEqual({ posicao: null, restantes: 1 });
    expect(linhaDoTempo("2026-12-31", "2026-12-31", "2026-12-31").posicao).toBe(100);
  });

  it("data malformada dá NaN nos dias, para a tela tratar como sem data final", () => {
    expect(Number.isNaN(diasEntre("2026-10-16", "abc"))).toBe(true);
    expect(Number.isNaN(linhaDoTempo("2026-01-01", "", "2026-10-16").restantes)).toBe(true);
  });
});

const aditivo = (id: number, data: string | null, extra = {}) => ({ id, tipo: "prazo", forma: "termo_aditivo", numero: `${id}º TA`,
  objeto: null, delta_valor_centavos: 0, nova_vigencia_fim: null, nova_execucao_fim: "2027-01-20", status: data ? "assinado" : "em_andamento",
  data_assinatura: data, cancelado_em: null, ...extra });

describe("abas da obra", () => {
  it("todo instrumento numa lista só, do mais novo ao mais antigo, com o retroativo do servidor", () => {
    const linhas = instrumentosDaObra(
      [aditivo(4, null), aditivo(1, "2025-03-01"), aditivo(2, "2026-02-10", { tipo: "valor" })],
      [{ id: 7, tipo: "paralisacao", numero: "OS 3", data: "2025-08-01", dados: {} },
       { id: 8, tipo: "apostilamento_reajuste", numero: "AP 1", data: "2024-06-30", dados: { percentual: 4.5 } },
       { id: 9, tipo: "marco_encerramento", numero: null, data: "2026-09-01", dados: { marco: "conclusao" } }],
      [{ id: 1, numero: "1º TA", data_assinatura: "2025-03-01", retroativo: true }]);
    expect(linhas.map(l => l.chave)).toEqual(["a2", "c7", "a1", "c8", "a4"]);
    expect(linhas.filter(l => l.de === "aditivo" && l.retroativo).map(l => l.chave)).toEqual(["a1"]);
    expect(linhas.filter(l => l.de === "aditivo" && l.dePrazo).map(l => l.chave)).toEqual(["a1"]);
  });

  it("o pedido de prorrogação é atendido pelo primeiro instrumento de prazo assinado no dia do envio ou depois", () => {
    const prazo = [{ id: 1, numero: "1º TA", data_assinatura: "2026-01-10", retroativo: false },
                   { id: 2, numero: "2º TA", data_assinatura: "2026-09-20", retroativo: false }];
    expect(desfechoDoPedido("2026-09-05 13:00:00", prazo)?.numero).toBe("2º TA");
    expect(desfechoDoPedido("2026-09-25 13:00:00", prazo)).toBeNull();
  });

  it("reajuste por data-base: ciclo corrente, pleitos anteriores e apostilamentos no lugar", () => {
    const ciclos = [{ data_base_mes: "2023-01", indice: "INCC", ciclo: 2026, aniversario: "2026-01-01", situacao: "apostilamento_pendente", dias: 187 },
                    { data_base_mes: "2023-06", indice: "SICRO", ciclo: 2026, aniversario: "2026-06-01", situacao: "apostilado", dias: null }];
    const pleitos = [{ id: 9, data_base_mes: "2023-01", ciclo: 2026 }, { id: 4, data_base_mes: "2023-01", ciclo: 2025 },
                     { id: 3, data_base_mes: "2021-01", ciclo: 2022 }];
    const ap = [{ id: 1, tipo: "apostilamento_reajuste", numero: "AP 1", data: "2026-07-01", dados: { data_base: "2023-06" } },
                { id: 2, tipo: "apostilamento_reajuste", numero: "AP ?", data: "2025-01-01", dados: {} }];
    const { dataBases, semDataBase, outrosPleitos } = reajustePorDataBase(ciclos, pleitos, ap);
    expect(dataBases[0].pleitosDoCiclo.map(p => p.id)).toEqual([9]);
    expect(dataBases[0].pleitosAnteriores.map(p => p.id)).toEqual([4]);
    expect(dataBases[1].apostilamentos.map(i => i.id)).toEqual([1]);
    expect(semDataBase.map(i => i.id)).toEqual([2]);
    expect(outrosPleitos.map(p => p.id)).toEqual([3]);
  });
});
