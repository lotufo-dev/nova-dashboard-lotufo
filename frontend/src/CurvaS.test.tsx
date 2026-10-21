import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import CurvaS from "./CurvaS";
import { curvaS, desviosEmPP, type PontoDaCurva } from "./obra";

// Issue #295 (spec 2026-10-20 §3.4, D9): a curva S mostra o previsto vigente e o anterior a ultima repactuacao,
// o medido e a marca de cada aditivo; o desvio em p.p. sai contra as duas linhas.

const p = (competencia: string, previsto: number, medido = 0): PontoDaCurva =>
  ({ competencia, previsto_centavos: previsto, medido_execucao_centavos: medido, atestado_pendente: false });

// vigente (refeito com o medido): 100 por mes; anterior: 200 nos dois primeiros meses (mesmo total, 400)
const PONTOS = [p("2026-01", 100_00, 100_00), p("2026-02", 100_00, 100_00), p("2026-03", 100_00), p("2026-04", 100_00)];
const ANTERIOR = [{ competencia: "2026-01", previsto_centavos: 200_00 }, { competencia: "2026-02", previsto_centavos: 200_00 }];
const ADITIVOS = [{ competencia: "2026-02", data: "2026-02-10", nome: "1º Termo Aditivo" }];

describe("curvaS e desviosEmPP: linha anterior", () => {
  it("acumula a linha anterior e estende o eixo aos meses que so ela tem", () => {
    const s = curvaS([p("2026-02", 100)], [{ competencia: "2026-01", previsto_centavos: 7 }, { competencia: "2026-02", previsto_centavos: 3 }]);
    expect(s.map(x => [x.competencia, x.acumuladoAnterior])).toEqual([["2026-01", 7], ["2026-02", 10]]);
    expect(curvaS([p("2026-02", 100)])[0].acumuladoAnterior).toBeNull();
  });

  it("desvio em p.p. contra o vigente e contra o anterior, cada linha pelo proprio total", () => {
    const d = desviosEmPP(curvaS(PONTOS, ANTERIOR));
    expect(d).toEqual({ competencia: "2026-02", vigente: 0, anterior: -50 });
    expect(desviosEmPP(curvaS(PONTOS))).toEqual({ competencia: "2026-02", vigente: 0, anterior: null });
    expect(desviosEmPP(curvaS([p("2026-01", 100)]))).toBeNull();
  });
});

describe("CurvaS: duas linhas, marcas e desvio", () => {
  afterEach(cleanup);

  it("mostra as duas linhas com legenda, a marca do aditivo com o nome do termo e os dois desvios", () => {
    const { container } = render(<CurvaS pontos={PONTOS} anterior={ANTERIOR} aditivos={ADITIVOS} contratoId={1} />);
    expect(container.querySelector(".c-previsto")).not.toBeNull();
    expect(container.querySelector(".c-previsto-anterior")).not.toBeNull();
    expect(screen.getByText("Previsto vigente")).toBeTruthy();
    expect(screen.getByText("Previsto anterior à última repactuação")).toBeTruthy();
    // marca vertical no mes da assinatura, com o nome do termo
    expect(container.querySelectorAll(".c-aditivo")).toHaveLength(1);
    expect(container.querySelector(".c-aditivo-txt")?.textContent).toBe("1º Termo Aditivo");
    const rodape = container.querySelector(".curva__rodape")?.textContent ?? "";
    expect(rodape).toMatch(/contra o vigente: 0,0 p\.p\./);
    expect(rodape).toMatch(/contra o anterior: -50,0 p\.p\./);
  });

  it("lista anterior vazia, ou vigente sem pontos, nao desenha a linha anterior; desvio minusculo nao vira -0,0", () => {
    const vazia = render(<CurvaS pontos={PONTOS} anterior={[]} aditivos={[]} contratoId={1} />);
    expect(vazia.container.querySelector(".c-previsto-anterior")).toBeNull();
    cleanup();
    const semVigente = render(<CurvaS pontos={[]} anterior={ANTERIOR} aditivos={[]} contratoId={1} />);
    expect(semVigente.container.querySelector(".c-previsto-anterior")).toBeNull();
    cleanup();
    const pequeno = render(<CurvaS pontos={[p("2026-01", 100_000_00, 99_990_00), p("2026-02", 100_000_00)]}
      anterior={[{ competencia: "2026-01", previsto_centavos: 100_000_00 }]} aditivos={[]} contratoId={1} />);
    const t = pequeno.container.querySelector(".curva__rodape")?.textContent ?? "";
    expect(t).toMatch(/contra o vigente: 0,0 p\.p\./);
    expect(t).not.toMatch(/-0,0/);
  });

  it("na visao por mes a legenda da linha anterior some (a linha nao e desenhada)", () => {
    render(<CurvaS pontos={PONTOS} anterior={ANTERIOR} aditivos={[]} contratoId={1} />);
    fireEvent.click(screen.getByRole("button", { name: "por mês" }));
    expect(screen.queryByText("Previsto anterior à última repactuação")).toBeNull();
  });

  it("obra sem versao anterior: so a linha vigente, sem legenda nem desvio da anterior", () => {
    const { container } = render(<CurvaS pontos={PONTOS} anterior={null} aditivos={[]} contratoId={1} />);
    expect(container.querySelector(".c-previsto-anterior")).toBeNull();
    expect(screen.queryByText("Previsto anterior à última repactuação")).toBeNull();
    expect(container.querySelectorAll(".c-aditivo")).toHaveLength(0);
    expect(container.querySelector(".curva__rodape")?.textContent ?? "").not.toMatch(/contra o anterior/);
  });
});
