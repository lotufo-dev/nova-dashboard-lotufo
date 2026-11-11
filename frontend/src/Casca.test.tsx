import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Trilho } from "./Casca";

// Menu lateral de Medições (#643): um item só, que abre o quadro do mês; "Iniciar medição" e "Em andamento" saíram.
describe("menu lateral: Medições", () => {
  afterEach(cleanup);

  it("dentro de Medições o menu tem só o item Medições, marcado, sem subitens", () => {
    render(<Trilho perfil="engenharia" marcado="medicoes" ir={vi.fn()} />);
    const item = screen.getByRole("link", { name: "Medições" });
    expect(item.getAttribute("href")).toBe("/medicoes");
    expect(item.getAttribute("aria-current")).toBe("page");
    expect(screen.queryByRole("group", { name: "Medições" })).toBeNull();
    expect(screen.queryByRole("link", { name: /Iniciar medição/ })).toBeNull();
    expect(screen.queryByRole("link", { name: /Em andamento/ })).toBeNull();
  });

  it("fora de Medições o item segue um link comum, sem marca", () => {
    render(<Trilho perfil="admin" marcado="obras" ir={vi.fn()} />);
    const item = screen.getByRole("link", { name: "Medições" });
    expect(item.getAttribute("href")).toBe("/medicoes");
    expect(item.getAttribute("aria-current")).toBeNull();
  });
});
