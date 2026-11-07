import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Trilho } from "./Casca";

// Menu lateral de Medições (#507): só dois subitens, "Iniciar medição" e "Em andamento", cada um com a contagem.
describe("menu lateral: Medições", () => {
  afterEach(cleanup);

  it("dentro de Medições aparecem só os dois subitens, com as contagens, e o da tela fica marcado", () => {
    render(<Trilho perfil="engenharia" marcado="medicoes" ir={vi.fn()} subitem="em-andamento" contagens={{ iniciar: 11, andamento: 8 }} />);
    const grupo = screen.getByRole("group", { name: "Medições" });
    const itens = within(grupo).getAllByRole("link");
    expect(itens.map(a => a.textContent)).toEqual(["Iniciar medição11", "Em andamento8"]);
    expect(itens.map(a => a.getAttribute("href"))).toEqual(["/medicoes", "/medicoes/em-andamento"]);
    expect(itens[1].getAttribute("aria-current")).toBe("page");
    expect(itens[0].getAttribute("aria-current")).toBeNull();
    // o item pai não fica marcado junto: o marcado é o subitem
    expect(screen.getByRole("link", { name: "Medições" }).getAttribute("aria-current")).toBeNull();
  });

  it("fora de Medições os subitens não aparecem e o item pai segue um link comum", () => {
    render(<Trilho perfil="engenharia" marcado="obras" ir={vi.fn()} subitem={null} contagens={{ iniciar: 11, andamento: 8 }} />);
    expect(screen.queryByRole("group", { name: "Medições" })).toBeNull();
    expect(screen.getByRole("link", { name: "Medições" }).getAttribute("href")).toBe("/medicoes");
  });

  it("sem as contagens (ainda carregando) os subitens aparecem sem número", () => {
    render(<Trilho perfil="admin" marcado="medicoes" ir={vi.fn()} subitem="iniciar" contagens={null} />);
    const itens = within(screen.getByRole("group", { name: "Medições" })).getAllByRole("link");
    expect(itens.map(a => a.textContent)).toEqual(["Iniciar medição", "Em andamento"]);
  });
});
