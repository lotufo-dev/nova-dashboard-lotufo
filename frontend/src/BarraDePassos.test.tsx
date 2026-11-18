import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import BarraDePassos, { type PassoDaBarra } from "./BarraDePassos";

const NOMES = ["Planilha e carta", "Análise do órgão", "Espelhos", "Notas", "Envio da nota", "Pagamento"];
const passos = (numeros: number[], atual: number): PassoDaBarra[] => numeros.map(n => ({
  numero: n, nome: NOMES[n - 1], situacao: n < atual ? "feito" : n === atual ? "atual" : "futuro" }));
const classes = (c: HTMLElement) => [...c.querySelectorAll(".barra-passos__passo")].map(p => p.className.replace("barra-passos__passo barra-passos__passo--", ""));

describe("BarraDePassos (#805)", () => {
  afterEach(cleanup);

  it("um segmento por passo da obra: os feitos, o da vez e os que faltam, com o nome e a posição do passo da vez", () => {
    const { container } = render(<BarraDePassos passos={passos([1, 2, 3, 4, 5, 6], 3)} />);
    expect(classes(container)).toEqual(["feito", "feito", "atual", "futuro", "futuro", "futuro"]);
    expect(container.querySelector(".barra-passos__nome")?.textContent).toBe("Espelhos · , passo 3 de 6");
    // os segmentos são desenho: quem ouve a tela recebe o nome e a posição
    expect(container.querySelector(".barra-passos__trilho")?.getAttribute("aria-hidden")).toBe("true");
  });

  it("a obra de cinco passos mostra cinco, e a posição conta entre os passos que ela tem", () => {
    const { container } = render(<BarraDePassos passos={passos([2, 3, 4, 5, 6], 4)} />);
    expect(classes(container)).toEqual(["feito", "feito", "atual", "futuro", "futuro"]);
    expect(container.querySelector(".barra-passos__posicao")?.textContent).toBe("3 de 5");
  });

  it("sem passo da vez (tudo feito): só a barra, com o texto de leitor de tela", () => {
    const { container } = render(<BarraDePassos passos={passos([3, 4, 6], 7)} />);
    expect(classes(container)).toEqual(["feito", "feito", "feito"]);
    expect(container.querySelector(".barra-passos__nome")).toBeNull();
    expect(container.querySelector(".sr-only")?.textContent).toBe("Todos os passos feitos");
  });

  it("sem passos, nada", () => {
    const { container } = render(<BarraDePassos passos={[]} />);
    expect(container.firstChild).toBeNull();
  });
});
