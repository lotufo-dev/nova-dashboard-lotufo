import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import AReceber from "./AReceber";

// A receber (#814): a página-casca. O título e o caminho são da barra do topo; aqui, o estado vazio e o recorte por
// contratante que vem na busca do endereço. A #816 traz as notas.
describe("A receber: a página-casca", () => {
  afterEach(cleanup);

  it("sem nota em aberto, diz isso em uma linha", () => {
    render(<AReceber ir={vi.fn()} />);
    expect(screen.getByRole("region", { name: "A receber" }).textContent).toBe("Nenhuma nota em aberto.");
    expect(screen.queryByRole("link")).toBeNull();
    expect(screen.queryByRole("table")).toBeNull();
  });

  it("?contratante= mostra só um contratante, com o caminho de volta para todos", () => {
    render(<AReceber busca={{ contratante: " SINFRA " }} ir={vi.fn()} />);
    const pagina = screen.getByRole("region", { name: "A receber de SINFRA" });
    expect(pagina.querySelector(".vazio__titulo")!.textContent).toBe("Nenhuma nota em aberto de SINFRA.");
    expect(screen.getByRole("link", { name: "Ver todos os contratantes" }).getAttribute("href")).toBe("/a-receber");
  });

  it("o contratante em branco é a página inteira", () => {
    render(<AReceber busca={{ contratante: "  " }} ir={vi.fn()} />);
    expect(screen.getByRole("region", { name: "A receber" }).textContent).toBe("Nenhuma nota em aberto.");
  });
});
