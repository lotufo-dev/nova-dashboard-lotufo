import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import CurvaS from "./CurvaS";
import { curvaS, rotuloAditivo, type PontoDaCurva } from "./obra";

// Issue #295 (spec 2026-10-20 §3.4, D9): a curva S mostra o previsto vigente e o anterior a ultima repactuacao,
// o medido e a marca de cada aditivo. O desvio em p.p. saiu da tela (texto-na-tela, 26/10/2026); a conta segue em obra.ts.

const p = (competencia: string, previsto: number, medido = 0): PontoDaCurva =>
  ({ competencia, previsto_centavos: previsto, medido_execucao_centavos: medido, atestado_pendente: false });

// vigente (refeito com o medido): 100 por mes; anterior: 200 nos dois primeiros meses (mesmo total, 400)
const PONTOS = [p("2026-01", 100_00, 100_00), p("2026-02", 100_00, 100_00), p("2026-03", 100_00), p("2026-04", 100_00)];
const ANTERIOR = [{ competencia: "2026-01", previsto_centavos: 200_00 }, { competencia: "2026-02", previsto_centavos: 200_00 }];
const ADITIVOS = [{ competencia: "2026-02", data: "2026-02-10", nome: "1º Termo Aditivo" }];

describe("curvaS: linha anterior", () => {
  it("acumula a linha anterior e estende o eixo aos meses que so ela tem", () => {
    const s = curvaS([p("2026-02", 100)], [{ competencia: "2026-01", previsto_centavos: 7 }, { competencia: "2026-02", previsto_centavos: 3 }]);
    expect(s.map(x => [x.competencia, x.acumuladoAnterior])).toEqual([["2026-01", 7], ["2026-02", 10]]);
    expect(curvaS([p("2026-02", 100)])[0].acumuladoAnterior).toBeNull();
  });
});

describe("CurvaS: duas linhas e marcas, sem rodape", () => {
  afterEach(cleanup);

  it("mostra as duas linhas com legenda e a marca do aditivo com o nome do termo, sem rodape de desvio", () => {
    const { container } = render(<CurvaS pontos={PONTOS} anterior={ANTERIOR} aditivos={ADITIVOS} contratoId={1} />);
    expect(container.querySelector(".c-previsto")).not.toBeNull();
    expect(container.querySelector(".c-previsto-anterior")).not.toBeNull();
    expect(screen.getByText("Previsto vigente")).toBeTruthy();
    expect(screen.getByText("Previsto anterior")).toBeTruthy();
    // marca vertical no mes da assinatura, com o nome do termo
    expect(container.querySelectorAll(".c-aditivo")).toHaveLength(1);
    // rotulo curto na curva; o nome inteiro do termo fica no <title> da marca
    expect(container.querySelector(".c-aditivo-txt")?.textContent).toBe("1º TA");
    expect(container.querySelector(".c-aditivo title")?.textContent).toBe("1º Termo Aditivo");
    expect(container.querySelector(".curva__rodape")).toBeNull();
    expect(container.textContent).not.toMatch(/p\.p\./);
  });

  it("dois termos do mesmo mes ficam em faixas diferentes: um rotulo nunca cobre o outro (06/11/2026)", () => {
    const mesmoMes = [
      { ...ADITIVOS[0], nome: "TA 2º Termo Aditivo ao Contrato 001/2030/ORGAO" },
      { ...ADITIVOS[0], nome: "TA 3º Termo Aditivo ao Contrato 001/2030/ORGAO", data: `${ADITIVOS[0].data.slice(0, 8)}28` },
      { ...ADITIVOS[0], nome: "Termo aditivo", data: `${ADITIVOS[0].data.slice(0, 8)}27` },
    ];
    const { container } = render(<CurvaS pontos={PONTOS} anterior={ANTERIOR} aditivos={mesmoMes} contratoId={1} />);
    const textos = [...container.querySelectorAll(".c-aditivo-txt")];
    expect(textos.map(t => t.textContent)).toEqual(["2º TA", "3º TA", "TA"]);
    // mesma coluna (mesmo mes), linhas diferentes
    expect(new Set(textos.map(t => t.getAttribute("y"))).size).toBe(3);
    expect(rotuloAditivo("8º TA")).toBe("8º TA");
    expect(rotuloAditivo("Termo aditivo")).toBe("TA");
  });

  it("lista anterior vazia, ou vigente sem pontos, nao desenha a linha anterior", () => {
    const vazia = render(<CurvaS pontos={PONTOS} anterior={[]} aditivos={[]} contratoId={1} />);
    expect(vazia.container.querySelector(".c-previsto-anterior")).toBeNull();
    cleanup();
    const semVigente = render(<CurvaS pontos={[]} anterior={ANTERIOR} aditivos={[]} contratoId={1} />);
    expect(semVigente.container.querySelector(".c-previsto-anterior")).toBeNull();
    // obra sem curva: uma linha e o link para o cronograma, sem a frase de onde vem o previsto
    expect(screen.getByRole("link", { name: "Abrir o cronograma" })).toBeTruthy();
    expect(screen.queryByText(/O previsto vem do/)).toBeNull();
  });

  it("na visao por mes a legenda da linha anterior some (a linha nao e desenhada)", () => {
    render(<CurvaS pontos={PONTOS} anterior={ANTERIOR} aditivos={[]} contratoId={1} />);
    fireEvent.click(screen.getByRole("button", { name: "por mês" }));
    expect(screen.queryByText("Previsto anterior")).toBeNull();
  });

  it("obra sem versao anterior: so a linha vigente, sem legenda da anterior", () => {
    const { container } = render(<CurvaS pontos={PONTOS} anterior={null} aditivos={[]} contratoId={1} />);
    expect(container.querySelector(".c-previsto-anterior")).toBeNull();
    expect(screen.queryByText("Previsto anterior")).toBeNull();
    expect(container.querySelectorAll(".c-aditivo")).toHaveLength(0);
  });
});
