import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { BarraSuperior, Trilho } from "./Casca";
import type { Usuario } from "./Login";

// as permissoes que /api/auth/eu informa (backend/app/permissoes.py); o item SIGA e' de quem tem `ver_siga` (#829)
const COM_SIGA = ["ver_paineis", "ver_siga"];

// Menu lateral de Medições (#643): um item só, que abre a fila de trabalho; "Iniciar medição" e "Em andamento" saíram.
describe("menu lateral: Medições", () => {
  afterEach(cleanup);

  it("dentro de Medições a página Medições fica marcada; Iniciar medição e Em andamento não são itens", () => {
    render(<Trilho perfil="engenharia" marcado="medicoes" ir={vi.fn()} />);
    const item = screen.getByRole("link", { name: "Medições" });
    expect(item.getAttribute("href")).toBe("/medicoes");
    expect(item.getAttribute("aria-current")).toBe("page");
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

// #814 (decisão do dono de 18/11/2026, #805): o menu em áreas, cada uma com o nome escrito e as páginas dentro.
describe("menu lateral em áreas (#814)", () => {
  beforeEach(() => { try { localStorage.clear(); } catch { /* sem armazenamento: o menu abre largo */ } });
  afterEach(cleanup);

  const nav = () => screen.getByRole("navigation", { name: "Navegação principal" });
  /** [nome da área (null na área que é a própria página), as páginas dela] */
  const areas = () => [...nav().querySelectorAll(".menu__area")].map(a => [
    a.querySelector(".menu__area-nome")?.textContent ?? null,
    [...a.querySelectorAll("a.menu__item")].map(l => l.textContent),
  ]);

  it("o administrador vê as oito áreas, com o nome e as páginas de cada uma; Obras aparece uma vez só", () => {
    render(<Trilho perfil="admin" permissoes={COM_SIGA} marcado="inicio" ir={vi.fn()} />);
    expect(areas()).toEqual([
      ["Painel", ["Início"]],
      ["Medições", ["Medições", "Resumo das medições"]],
      [null, ["Obras"]],
      ["Financeiro", ["Fechamento", "A receber"]],
      ["Prazos e avisos", ["Avisos"]],
      ["Órgãos", ["SIGA"]],
      ["Documentos", ["Certidões", "Regularidade mensal", "Garantias"]],
      ["Sistema", ["Âncoras DocuSign", "Administração", "Minha conta"]],
    ]);
    // o nome da área não é link nem título: é o nome da lista de páginas dela
    expect(within(nav()).getByRole("list", { name: "Financeiro" }).querySelectorAll("a")).toHaveLength(2);
    expect(within(nav()).queryByRole("link", { name: "Financeiro" })).toBeNull();
    expect(within(nav()).queryAllByRole("heading")).toHaveLength(0);
    expect(within(nav()).getAllByRole("link", { name: "Obras" })).toHaveLength(1);
  });

  it("a engenharia não vê a Administração; a diretoria fica sem Medições e Âncoras, e com o SIGA (#829)", () => {
    const { unmount } = render(<Trilho perfil="engenharia" permissoes={COM_SIGA} marcado="inicio" ir={vi.fn()} />);
    expect(areas().map(a => a[0])).toEqual(["Painel", "Medições", null, "Financeiro", "Prazos e avisos", "Órgãos", "Documentos", "Sistema"]);
    expect(areas()[7][1]).toEqual(["Âncoras DocuSign", "Minha conta"]);
    unmount();
    render(<Trilho perfil="diretoria" permissoes={COM_SIGA} marcado="inicio" ir={vi.fn()} />);
    expect(areas()).toEqual([
      ["Painel", ["Início"]],
      ["Medições", ["Resumo das medições"]],
      [null, ["Obras"]],
      ["Financeiro", ["Fechamento", "A receber"]],
      ["Prazos e avisos", ["Avisos"]],
      ["Órgãos", ["SIGA"]],
      ["Documentos", ["Certidões", "Regularidade mensal", "Garantias"]],
      ["Sistema", ["Minha conta"]],
    ]);
  });

  it("quem não tem `ver_siga` não tem o item SIGA, qualquer que seja o perfil, e a área Órgãos some (#829)", () => {
    for (const perfil of ["admin", "engenharia", "diretoria"]) {
      const { unmount } = render(<Trilho perfil={perfil} permissoes={["ver_paineis", "editar_cadastros"]} marcado="inicio" ir={vi.fn()} />);
      expect(within(nav()).queryByRole("link", { name: "SIGA" })).toBeNull();
      expect(areas().map(a => a[0])).not.toContain("Órgãos");
      unmount();
    }
  });

  it("cada página leva ao endereço dela", () => {
    render(<Trilho perfil="admin" permissoes={COM_SIGA} marcado="inicio" ir={vi.fn()} />);
    expect(within(nav()).getAllByRole("link").map(l => l.getAttribute("href"))).toEqual(["/inicio", "/medicoes", "/resumo-medicoes", "/obras",
      "/fechamento", "/a-receber", "/avisos", "/siga", "/documentos", "/documentos/regularidade", "/documentos/garantias",
      "/ancoras-docusign", "/admin", "/conta"]);
  });

  it("a área da página aberta fica acesa, e só ela", () => {
    const acesas = () => [...nav().querySelectorAll(".menu__area--acesa .menu__area-nome")].map(n => n.textContent);
    const { rerender } = render(<Trilho perfil="admin" marcado="a-receber" ir={vi.fn()} />);
    expect(acesas()).toEqual(["Financeiro"]);
    expect(within(nav()).getAllByRole("link").filter(l => l.getAttribute("aria-current") === "page").map(l => l.textContent)).toEqual(["A receber"]);
    rerender(<Trilho perfil="admin" marcado="regularidade" ir={vi.fn()} />);
    expect(acesas()).toEqual(["Documentos"]);
    // Obras não tem nome de área para acender: fica só o item
    rerender(<Trilho perfil="admin" marcado="obras" ir={vi.fn()} />);
    expect(acesas()).toEqual([]);
    expect(nav().querySelectorAll(".menu__area--acesa")).toHaveLength(1);
    rerender(<Trilho perfil="admin" marcado={null} ir={vi.fn()} />);
    expect(nav().querySelectorAll(".menu__area--acesa")).toHaveLength(0);
  });

  it("recolhido, o nome da área continua sendo o nome da lista (para o leitor de tela)", () => {
    render(<Trilho perfil="admin" marcado="fechamento" ir={vi.fn()} />);
    fireEvent.click(within(nav()).getByRole("button", { name: "Recolher o menu" }));
    expect(nav().getAttribute("data-estado")).toBe("recolhido");
    expect(within(nav()).getByRole("list", { name: "Documentos" }).querySelectorAll("a")).toHaveLength(3);
    expect(within(nav()).getByRole("link", { name: "A receber" }).getAttribute("title")).toBe("A receber");
  });
});

// #720: a casca da fundação. Menu escuro com o símbolo e o nome da marca em dois pesos, item ativo marcado, e o topo
// com o caminho da página e a conta. O recolher pela tela inteira (e no celular) está no App.test.tsx.
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

  it("os itens são listas de links com ícone; só o ativo leva aria-current, e o recolher fica no pé", () => {
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

  it("o topo mostra o caminho da página (o trecho dela é o h1 nas listas) e a conta com as iniciais", () => {
    const { rerender } = render(<BarraSuperior rota={{ tela: "fechamento" }} ehH1 usuario={usuario} ir={vi.fn()} />);
    const topo = screen.getByRole("banner");
    expect(topo.className).toBe("topo");
    const caminho = within(topo).getByRole("navigation", { name: "Você está em" });
    expect([...caminho.querySelectorAll("li")].map(li => li.textContent)).toEqual(["Financeiro", "Fechamento"]);
    expect(within(caminho).getByRole("heading", { level: 1, name: "Fechamento" }).className).toBe("caminho__titulo");
    expect(within(caminho).getByRole("link", { name: "Financeiro" }).getAttribute("href")).toBe("/fechamento");
    const conta = within(topo).getByRole("button", { name: "Conta de Mariana Albuquerque Teixeira" });
    expect(conta.querySelector(".conta__avatar")!.textContent).toBe("MT");
    // na tela que tem o proprio h1 o topo escreve o mesmo caminho, sem um segundo h1
    rerender(<BarraSuperior rota={{ tela: "obras", aba: "qdop" }} ehH1={false} usuario={usuario} ir={vi.fn()} />);
    expect(within(topo).queryByRole("heading")).toBeNull();
    expect([...topo.querySelectorAll(".caminho li")].map(li => li.textContent)).toEqual(["Obras", "QDOP"]);
    expect(topo.querySelector(".caminho__trecho--titulo")!.textContent).toBe("Obras");
  });

  it("a busca fica no topo, entre o caminho e a conta (#814; preenchida na #819)", () => {
    render(<BarraSuperior rota={{ tela: "inicio" }} ehH1={false} usuario={usuario} ir={vi.fn()} />);
    const topo = screen.getByRole("banner");
    expect([...topo.children].map(c => c.className)).toEqual(["caminho", "busca", "conta"]);
    expect(within(topo).getByRole("search")).toBeTruthy();
    expect(within(topo).getByRole("combobox", { name: "Buscar obra, medição ou processo" })).toBeTruthy();
  });
});
