import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import FichaObra, { CurvaDaFicha, desvioDaCurva, mesAno, type Ficha } from "./FichaObra";

// O resumo da obra (#646) nao le nada: a pagina unica (`ContratoPagina`) le a ficha e a curva e passa para ca'.
const PRAZOS = { execucao_fim: "2026-11-18", vigencia_fim: "2027-02-16" };
const p = (competencia: string, previsto: number, medido: number) => ({ competencia, previsto_centavos: previsto, medido_execucao_centavos: medido, atestado_pendente: false });
const CURVA = { pontos: [p("2026-08", 50, 40), p("2026-09", 50, 40), p("2026-10", 100, 0)], anterior: null };
const FICHA: Ficha = {
  // base de execucao e cota: 1.000.000,01 − 812.345,67 = 187.654,34
  topo: { vigente_centavos: 100000001, medido_centavos: 81234567, saldo_centavos: 18765434, reajuste_centavos: 0 },
  contrato: { original_centavos: 100000001, original_igual: true, tas: 2, data_base: "2025-01" },
  ultima_medicao: { id: 15, titulo: "15ª Medição", rotulo: "15ª", competencia: "2026-09", valor_centavos: 5000011,
    recebida_em: "2026-10-16", dias_apos_nota: 14 },
  em_andamento: { id: 16, titulo: "16ª Medição", rotulo: "16ª", competencia: "2026-10", valor_centavos: 6000022,
    etapa: "análise do órgão", desde: "2026-11-05", outras: 0 },
  vencimentos: [
    { chave: "certidao", rotulo: "FGTS Construtora Alfa", data: "2026-11-15", dias: 9, nivel: "atencao" },
    { chave: "execucao", rotulo: "Fim da execução", data: "2026-11-18", dias: 12, nivel: "critico" },
    { chave: "vigencia", rotulo: "Fim da vigência", data: "2027-02-16", dias: 102, nivel: "normal" }],
};

const cartao = (nome: string) => screen.getByRole("region", { name: nome });
const montar = (ficha: Ficha | null | undefined = FICHA) => render(<FichaObra contratoId={3} prazos={PRAZOS} ficha={ficha} />);

describe("Resumo da obra", () => {
  afterEach(cleanup);

  it("mostra os seis cartões com os valores da ficha", () => {
    montar();
    const contrato = within(cartao("Contrato")).getByText(/original igual/);
    expect(contrato.textContent).toBe("original igual · 2 TAs · data-base jan/2025");
    expect(within(cartao("Última medição")).getByRole("link").textContent).toMatch(/^15ª · set\/2026 · R\$.*50\.000,11$/);
    expect(within(cartao("Última medição")).getByText(/recebida em 16\/10\/2026, 14 dias após a nota/)).toBeTruthy();
    expect(within(cartao("Medição em andamento")).getByRole("link").textContent).toMatch(/^16ª · out\/2026 · R\$.*60\.000,22$/);
    expect(within(cartao("Medição em andamento")).getByText("análise do órgão desde 05/11")).toBeTruthy();
  });

  it("valor vigente, medido e saldo vêm do topo da ficha, na mesma base, e o percentual usa os dois (#646)", () => {
    montar();
    expect(within(cartao("Contrato")).getByText(/1\.000\.000,01/)).toBeTruthy();
    expect(within(cartao("Execução")).getByText(/812\.345,67/)).toBeTruthy();
    expect(within(cartao("Execução")).getByText(/187\.654,34/)).toBeTruthy();
    expect(within(cartao("Execução")).getByText("81%").className).toContain("info--feito");
    expect(within(cartao("Execução")).getByRole("progressbar").getAttribute("aria-valuenow")).toBe("81");
  });

  it("não há link 'ver contrato' no cartão Contrato (#646)", () => {
    montar();
    expect(within(cartao("Contrato")).queryByRole("link")).toBeNull();
    expect(screen.queryByText(/ver contrato/)).toBeNull();
  });

  it("o reajuste do contrato aparece à parte no cartão Contrato, só quando existe (#646)", () => {
    montar();
    expect(within(cartao("Contrato")).queryByText("Reajuste")).toBeNull();
    cleanup();
    montar({ ...FICHA, topo: { ...FICHA.topo, reajuste_centavos: 5000003 } });
    const linha = within(cartao("Contrato")).getByText("Reajuste").closest("div")!;
    expect(linha.textContent).toMatch(/Reajuste.*50\.000,03/);
    // o valor vigente do cartao continua o de execucao, sem o reajuste
    expect(within(cartao("Contrato")).getByText(/1\.000\.000,01/).className).toContain("ficha__valor");
  });

  it("saldo negativo fica vermelho", () => {
    montar({ ...FICHA, topo: { vigente_centavos: 100, medido_centavos: 151, saldo_centavos: -51, reajuste_centavos: 0 } });
    expect(within(cartao("Execução")).getByText(/−R\$\s0,51/).className).toContain("info--critico");
  });

  it("prazo em vermelho quando crítico e preto quando não; vencimentos pelo nível do servidor", () => {
    montar();
    expect(within(cartao("Prazo")).getByText("12 dias").className).toContain("info--critico");
    expect(within(cartao("Prazo")).getByText(/execução até 18\/11\/2026 · vigência até 16\/02\/2027/)).toBeTruthy();
    const venc = cartao("Próximos vencimentos");
    expect(within(venc).getByText("15/11/2026").className).toContain("info--breve");
    expect(within(venc).getByText("18/11/2026").className).toContain("info--critico");
    expect(within(venc).getByText("16/02/2027").className).not.toContain("info-");
  });

  it("prazo longe do fim não fica vermelho", () => {
    montar({ ...FICHA, vencimentos: FICHA.vencimentos.map(v => ({ ...v, dias: 200, nivel: "normal" })) });
    expect(within(cartao("Prazo")).getByText("200 dias").className).not.toContain("info--critico");
  });

  it("falha da ficha mostra indisponível nos cartões, sem número inventado", () => {
    montar(null);
    for (const nome of ["Contrato", "Execução", "Prazo", "Última medição", "Medição em andamento", "Próximos vencimentos"]) {
      expect(within(cartao(nome)).getByRole("alert").textContent).toBe("indisponível agora");
    }
    expect(screen.queryByText(/R\$/)).toBeNull();
  });
});

describe("Previsto × medido do resumo", () => {
  afterEach(cleanup);

  it("curva S com as duas séries e a pílula do desvio", () => {
    const { container } = render(<CurvaDaFicha curva={CURVA} />);
    expect(screen.getByRole("img", { name: /Curva S/ })).toBeTruthy();
    expect(container.querySelector("path.ficha__previsto")).toBeTruthy();
    expect(container.querySelector("path.ficha__medido")).toBeTruthy();
    // medido 80 de 200 previstos no total; previsto acumulado até a última medição: 100 → 10 pontos abaixo
    expect(screen.getByText(/medido/, { selector: ".pilula-info" }).textContent).toBe("medido 10% abaixo do previsto");
  });

  it("curva S no celular: o desenho acompanha a largura do cartão e o último mês cabe dentro dele (#552)", () => {
    const original = Object.getOwnPropertyDescriptor(HTMLElement.prototype, "clientWidth");
    Object.defineProperty(HTMLElement.prototype, "clientWidth", { configurable: true, get: () => 241 });
    try {
      const { container } = render(<CurvaDaFicha curva={CURVA} />);
      expect(screen.getByRole("img", { name: /Curva S/ }).getAttribute("viewBox")).toBe("0 0 241 170");
      const rotulos = [...container.querySelectorAll("text.c-eixo")].filter(t => /\/\d{2}$/.test(t.textContent ?? ""));
      // rotulo centralizado no ultimo ponto: a metade dele (~18 px) precisa caber antes da borda direita
      expect(Number(rotulos[rotulos.length - 1].getAttribute("x"))).toBeLessThanOrEqual(241 - 18);
    } finally {
      if (original) Object.defineProperty(HTMLElement.prototype, "clientWidth", original);
      else delete (HTMLElement.prototype as unknown as Record<string, unknown>).clientWidth;
    }
  });

  it("falha da curva mostra indisponível", () => {
    render(<CurvaDaFicha curva={null} />);
    expect(screen.getByRole("alert").textContent).toBe("indisponível agora");
  });
});

describe("regras puras da ficha", () => {
  it("desvio: acima, abaixo e sem medição", () => {
    expect(desvioDaCurva([p("2026-01", 50, 60), p("2026-02", 50, 0)], null)!.pp).toBeCloseTo(10);
    expect(desvioDaCurva([p("2026-01", 50, 40), p("2026-02", 50, 0)], null)!.pp).toBeCloseTo(-10);
    expect(desvioDaCurva([p("2026-01", 50, 0)], null)).toBeNull();
  });
  it("mês e ano", () => expect(mesAno("2026-09")).toBe("set/2026"));
});
