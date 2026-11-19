import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import Andamento from "./Andamento";
import { SEM_LEITURA, leituraDeTeste } from "./andamentoTeste";
import { andamento, foraDaRegua, temAndamento, type AndamentoDoServidor } from "./valores";

// Valores inventados. A leitura é a que o servidor manda (`prazos.leitura_do_andamento`): a peça só a escreve.
const lida = (situacao: AndamentoDoServidor["situacao"], pct: number): AndamentoDoServidor => ({ ...SEM_LEITURA, situacao, pct });
const texto = (c: HTMLElement) => (c.querySelector(".andamento__texto")?.textContent ?? "").replace(/\s/g, " ");
const classe = (c: HTMLElement) => c.querySelector(".andamento")?.className;
const largura = (c: HTMLElement) => (c.querySelector(".andamento__barra") as HTMLElement).style.width;

describe("Andamento (#805, #822)", () => {
  afterEach(cleanup);

  it("escreve a palavra e o percentual que o servidor mandou: Adiantada, Atenção e Devagar", () => {
    for (const [situacao, pct, frase] of [["adiantada", 120, "Adiantada · mede 120% do necessário"],
      ["atencao", 78, "Atenção · mede 78% do necessário"], ["devagar", 40, "Devagar · mede 40% do necessário"]] as const) {
      const { container } = render(<Andamento leitura={lida(situacao, pct)} />);
      expect(texto(container)).toBe(frase);
      expect(classe(container)).toBe(`andamento andamento--${situacao}`);
      cleanup();
    }
  });

  it("a tela não repete o corte: a palavra é a do servidor mesmo quando o ritmo e o necessário diriam outra", () => {
    // o servidor leu "atenção" com 99%; os dois valores passados (só para a frase dos valores) dariam 120%
    const { container } = render(<Andamento leitura={lida("atencao", 99)} ritmo={120_000} necessario={100_000} detalhe="valores" />);
    expect(texto(container)).toBe("Atenção · 99% do necessário");
    expect(classe(container)).toBe("andamento andamento--atencao");
    expect(andamento(lida("devagar", 100))).toEqual({ leitura: "devagar", pct: 100 });
  });

  it("a barra é o percentual num trilho que vai até 130% do necessário, com o risco no limite da adiantada; é desenho, fora da leitura", () => {
    const { container } = render(<Andamento leitura={lida("devagar", 65)} />);
    expect(largura(container)).toBe("50%");
    expect((container.querySelector(".andamento__necessario") as HTMLElement).style.left).toMatch(/^76\.92/);
    expect(container.querySelector(".andamento__trilho")?.getAttribute("aria-hidden")).toBe("true");
    cleanup();
    // o ritmo além do trilho enche a barra, sem passar da caixa
    expect(largura(render(<Andamento leitura={lida("adiantada", 400)} />).container)).toBe("100%");
    cleanup();
    // o risco segue o limite que o servidor manda
    const outro = render(<Andamento leitura={{ ...lida("devagar", 65), adiantada_desde_pct: 65 }} />).container;
    expect((outro.querySelector(".andamento__necessario") as HTMLElement).style.left).toBe("50%");
  });

  it("com os valores: a palavra, a razão e o ritmo por mês contra o necessário, abreviados", () => {
    // R$ 3.000.000,00 por mês de R$ 7.500.000,00 necessários
    const { container } = render(<Andamento leitura={lida("devagar", 40)} ritmo={300_000_000} necessario={750_000_000} detalhe="valores" />);
    const linhas = [...container.querySelectorAll(".andamento__texto")].map(p => (p.textContent ?? "").replace(/\s/g, " "));
    expect(linhas).toEqual(["Devagar · 40% do necessário", "R$ 3 mi/mês de R$ 7,5 mi"]);
    cleanup();
    // abaixo do milhão e abaixo do milhar
    const menor = render(<Andamento leitura={lida("adiantada", 55555)} ritmo={50_000_000} necessario={90_000} detalhe="valores" />).container;
    expect((menor.querySelector(".andamento__valores")?.textContent ?? "").replace(/\s/g, " ")).toBe("R$ 500 mil/mês de R$ 900");
  });

  it("só a palavra, na tabela que já traz o percentual e os valores em colunas", () => {
    const { container } = render(<Andamento leitura={lida("atencao", 78)} detalhe="palavra" />);
    expect(texto(container)).toBe("Atenção");
    expect(container.querySelector(".andamento__valores")).toBeNull();
    expect(largura(container)).toBe("60%");
  });

  it("fora da régua: o motivo escrito, em tinta e sem barra", () => {
    const casos: [Partial<AndamentoDoServidor>, string][] = [
      [{ motivo: "prazo_no_fim" }, "Prazo no fim"],
      [{ motivo: "prazo_no_fim", prorrogacao_pedida: true }, "Prazo no fim · prorrogação pedida"],
      [{ motivo: "prorrogacao_pedida", prorrogacao_pedida: true }, "Prorrogação pedida"],
      [{ motivo: "sem_medicao", sem_medicao_desde: "2026-07" }, "Sem medição desde 07/2026"],
    ];
    for (const [extra, frase] of casos) {
      // os valores existem (a obra tem ritmo e necessário), mas a leitura do servidor é o motivo
      const { container } = render(<Andamento leitura={{ ...SEM_LEITURA, ...extra }} ritmo={40_000} necessario={100_000} detalhe="valores" vazio="—" />);
      expect(texto(container)).toBe(frase);
      expect(classe(container)).toBe("andamento andamento--fora");
      expect(container.querySelector(".andamento__trilho")).toBeNull();
      expect(container.querySelector(".andamento__valores")).toBeNull();
      expect(andamento({ ...SEM_LEITURA, ...extra })).toBeNull();
      expect(temAndamento({ ...SEM_LEITURA, ...extra })).toBe(true);
      cleanup();
    }
  });

  it("sem leitura e sem motivo, nada aparece; na célula de tabela, o tracinho", () => {
    for (const leitura of [null, undefined, SEM_LEITURA, { ...SEM_LEITURA, motivo: "sem_medicao" as const }]) {
      expect(render(<Andamento leitura={leitura} ritmo={100} necessario={100} />).container.innerHTML).toBe("");
      cleanup();
      expect(render(<Andamento leitura={leitura} vazio="—" />).container.textContent).toBe("—");
      cleanup();
      expect([andamento(leitura), foraDaRegua(leitura), temAndamento(leitura)]).toEqual([null, null, false]);
    }
  });

  it("o dado de teste lê como o servidor: 70% e 100% entram na faixa de cima, e o percentual é por piso", () => {
    const l = (ritmo: number | null, necessario: number | null) => andamento(leituraDeTeste(ritmo, necessario));
    expect(l(100_000, 100_000)).toEqual({ leitura: "adiantada", pct: 100 });
    expect(l(99_999, 100_000)).toEqual({ leitura: "atencao", pct: 99 });
    expect(l(70_000, 100_000)).toEqual({ leitura: "atencao", pct: 70 });
    expect(l(69_999, 100_000)).toEqual({ leitura: "devagar", pct: 69 });
    expect([l(100, null), l(null, 100), l(100, 0)]).toEqual([null, null, null]);
  });
});
