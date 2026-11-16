import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { BarraSuperior, Trilho } from "./Casca";
import type { Usuario } from "./Login";

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

// #720: a casca da fundação. Menu escuro com o símbolo e o nome da marca em dois pesos, item ativo marcado, e o topo
// com o título da tela e a conta. O recolher pela tela inteira (e no celular) está no App.test.tsx.
describe("casca: marca, item ativo e topo", () => {
  const usuario = { id: 1, nome: "Mariana Albuquerque Teixeira", email: "mariana@exemplo.com.br", perfil: "admin" } as unknown as Usuario;
  beforeEach(() => { try { localStorage.clear(); } catch { /* sem armazenamento: o menu abre largo */ } });
  afterEach(cleanup);

  it("a marca tem o símbolo e o nome em dois pesos, e não é link nem conteúdo para o leitor de tela", () => {
    const { container } = render(<Trilho perfil="admin" marcado="inicio" ir={vi.fn()} />);
    const marca = container.querySelector(".menu__marca")!;
    expect(marca.getAttribute("aria-hidden")).toBe("true");
    expect(marca.querySelector("svg.menu__simbolo")).not.toBeNull();
    const nome = marca.querySelector(".menu__nome")!;
    expect(nome.textContent).toBe("grupolotufo");
    expect(nome.querySelector(".menu__nome-apoio")!.textContent).toBe("grupo");   // o peso leve; "lotufo" fica no forte
    expect(marca.querySelector("a")).toBeNull();
  });

  it("os itens são uma lista de links com ícone; só o ativo leva aria-current, e o recolher fica no pé", () => {
    render(<Trilho perfil="admin" marcado="medicoes" ir={vi.fn()} />);
    const nav = screen.getByRole("navigation", { name: "Navegação principal" });
    const itens = within(nav).getAllByRole("listitem");
    expect(itens.length).toBe(within(nav).getAllByRole("link").length);
    for (const li of itens) expect(li.querySelector("a.menu__item > svg.menu__icone")).not.toBeNull();
    expect(within(nav).getAllByRole("link").filter(l => l.getAttribute("aria-current") === "page").map(l => l.textContent)).toEqual(["Medições"]);
    const recolher = within(nav).getByRole("button", { name: "Recolher o menu" });
    expect(recolher.className).toBe("menu__recolher");
    expect(nav.querySelector(".menu__bloco")!.lastElementChild).toBe(recolher);
  });

  it("recolher guarda a escolha no navegador; recolhido, o item mantém o nome acessível e ganha a dica", () => {
    render(<Trilho perfil="admin" marcado="obras" ir={vi.fn()} />);
    const nav = screen.getByRole("navigation", { name: "Navegação principal" });
    expect(nav.getAttribute("data-estado")).toBe("largo");
    expect(within(nav).getByRole("link", { name: "Obras" }).getAttribute("title")).toBeNull();
    fireEvent.click(within(nav).getByRole("button", { name: "Recolher o menu" }));
    expect(nav.getAttribute("data-estado")).toBe("recolhido");
    expect(localStorage.getItem("menu-lateral")).toBe("recolhido");
    expect(within(nav).getByRole("link", { name: "Obras" }).getAttribute("title")).toBe("Obras");
    fireEvent.click(within(nav).getByRole("button", { name: "Expandir o menu" }));
    expect(nav.getAttribute("data-estado")).toBe("largo");
    expect(localStorage.getItem("menu-lateral")).toBe("largo");
  });

  it("o topo mostra o título da tela (h1 nas listas) e a conta com as iniciais", () => {
    const { rerender } = render(<BarraSuperior titulo="Medições" ehH1 usuario={usuario} ir={vi.fn()} />);
    const topo = screen.getByRole("banner");
    expect(topo.className).toBe("topo");
    expect(within(topo).getByRole("heading", { level: 1, name: "Medições" }).className).toBe("topo__titulo");
    const conta = within(topo).getByRole("button", { name: "Conta de Mariana Albuquerque Teixeira" });
    expect(conta.querySelector(".conta__avatar")!.textContent).toBe("MT");
    // na tela que tem o proprio h1 o topo so' diz a secao, com a mesma cara
    rerender(<BarraSuperior titulo="Obras" ehH1={false} usuario={usuario} ir={vi.fn()} />);
    expect(within(topo).queryByRole("heading")).toBeNull();
    expect(within(topo).getByText("Obras").className).toBe("topo__titulo");
  });
});
