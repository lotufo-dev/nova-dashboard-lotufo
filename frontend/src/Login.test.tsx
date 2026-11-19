/// <reference types="node" />
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import Login from "./Login";
import { ApiErro } from "./api";

const { api } = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("./api", async (original) => ({ ...(await original<typeof import("./api")>()), api }));

function tentar(aoEntrar: () => void = () => {}) {
  render(<Login aoEntrar={aoEntrar} />);
  fireEvent.change(screen.getByLabelText("E-mail"), { target: { value: "admin@lotufo.com" } });
  fireEvent.change(screen.getByLabelText("Senha"), { target: { value: "senha-forte-123" } });
  fireEvent.click(screen.getByRole("button", { name: "Entrar" }));
}

describe("Login: recusas", () => {
  afterEach(() => { cleanup(); api.mockReset(); });

  it("429 (limite por computador) mostra o aviso do servidor, não 'senha errada'", async () => {
    const texto = "Muitas tentativas de entrar a partir deste computador. Tente de novo em alguns minutos.";
    api.mockRejectedValue(new ApiErro(429, texto));
    tentar();
    expect((await screen.findByRole("alert")).textContent).toBe(texto);
  });

  it("401 continua com a mensagem de credencial recusada", async () => {
    api.mockRejectedValue(new ApiErro(401, "E-mail ou senha inválidos, ou usuário bloqueado"));
    tentar();
    const alerta = await screen.findByRole("alert");
    expect(alerta.textContent).toContain("Confira os dois e tente de novo.");
    // #768: a recusa vai na caixa de critico da fundacao (o octogono)
    expect(alerta.closest(".aviso--critico")?.querySelector(".glifo--critico")).toBeTruthy();
  });

  it("servidor fora do ar diz que não deu para falar com ele", async () => {
    api.mockRejectedValue(new TypeError("Failed to fetch"));
    tentar();
    expect((await screen.findByRole("alert")).textContent).toBe("Não foi possível falar com o servidor. Tente de novo em instantes.");
  });
});

describe("Login: entrar e esperar", () => {
  afterEach(() => { cleanup(); api.mockReset(); });

  it("enquanto o servidor não responde o botão diz 'Entrando…' desligado, e volta depois da recusa", async () => {
    let recusar: (e: Error) => void = () => {};
    api.mockReturnValue(new Promise((_, rejeitar) => { recusar = rejeitar; }));
    tentar();
    const botao = await screen.findByRole("button", { name: "Entrando…" });
    expect((botao as HTMLButtonElement).disabled).toBe(true);
    recusar(new ApiErro(401, "recusado"));
    const deVolta = await screen.findByRole("button", { name: "Entrar" });
    expect((deVolta as HTMLButtonElement).disabled).toBe(false);
  });

  it("credencial aceita: pergunta quem entrou e entrega o usuário a quem chamou", async () => {
    const eu = { id: 7, nome: "Faturamento", perfil: "operacao", email: "faturamento@exemplo.com.br" };
    api.mockImplementation(async (caminho: string) =>
      caminho === "/api/auth/login" ? { nome: eu.nome, perfil: eu.perfil, csrf: "ficha-de-teste" } : eu);
    const aoEntrar = vi.fn();
    tentar(aoEntrar);
    await waitFor(() => expect(aoEntrar).toHaveBeenCalledWith(eu));
    expect(api.mock.calls.map(c => c[0])).toEqual(["/api/auth/login", "/api/auth/eu"]);
    expect(JSON.parse(api.mock.calls[0][1].body)).toEqual({ email: "admin@lotufo.com", senha: "senha-forte-123" });
    expect(screen.queryByRole("alert")).toBeNull();
  });
});

describe("Login: só o que se usa para entrar", () => {
  afterEach(cleanup);

  it("sem frase de apoio, subtítulo da marca, ajuda, placeholder de e-mail nem rodapé", () => {
    const { container } = render(<Login aoEntrar={() => {}} />);
    expect(screen.getByRole("heading", { name: "Entrar" })).toBeTruthy();
    // #768: a marca e' o L em vetor, como no menu
    expect(container.querySelector("svg.entrar__simbolo")).not.toBeNull();
    expect(container.textContent).not.toMatch(/Medições, protocolos|Plataforma de Obras|cadastrados pelo administrador|rede interna|©/);
    expect(screen.getByLabelText("E-mail").getAttribute("placeholder")).toBeNull();
  });
});

describe("Login: a marca ocupa o lado escuro, parada (#821)", () => {
  afterEach(cleanup);
  const css = readFileSync(join(process.cwd(), "src", "login.css"), "utf8").replace(/\/\*[\s\S]*?\*\//g, "");
  const regraDaMarca = /\.entrar__marca \{([^}]*)\}/.exec(css)![1];

  it("o L e o nome em dois pesos ficam no bloco da marca, fora do formulário, uma vez só", () => {
    const { container } = render(<Login aoEntrar={() => {}} />);
    const marca = container.querySelector(".entrar__marca")!;
    expect(marca.querySelector("svg.entrar__simbolo")).not.toBeNull();
    expect(marca.querySelector(".entrar__nome")!.textContent).toBe("grupolotufo");
    expect(marca.querySelector(".entrar__nome-apoio")!.textContent).toBe("grupo");
    expect(marca.querySelector("form, input, button")).toBeNull();
    expect(container.querySelectorAll("svg.entrar__simbolo")).toHaveLength(1);
    expect(container.querySelector(".entrar__painel .entrar__nome")).toBeNull();
    // a marca e' o fundo escuro do menu, com a letra clara dele
    expect(regraDaMarca).toContain("background: var(--cor-menu)");
    expect(regraDaMarca).toContain("color: var(--cor-menu-texto)");
  });

  it("nenhuma animação: sem tela de desenho, sem quadro-chave e sem transição na folha da tela", () => {
    const { container } = render(<Login aoEntrar={() => {}} />);
    expect(container.querySelector("canvas")).toBeNull();
    expect(css).not.toMatch(/@keyframes|animation|transition/);
  });

  it("a biblioteca de 3D, que só o fundo animado usava, saiu das dependências", () => {
    const pacote = JSON.parse(readFileSync(join(process.cwd(), "package.json"), "utf8"));
    expect(Object.keys({ ...pacote.dependencies, ...pacote.devDependencies }).filter(n => /(^|\/)three$/.test(n))).toEqual([]);
  });

  it("o formulário não sobe quando a caixa de recusa aparece: o bloco fica preso pelo alto, não centrado", () => {
    const painel = [...css.matchAll(/\.entrar__painel \{([^}]*)\}/g)].map(m => m[1]).find(r => r.includes("justify-content: flex-start"));
    expect(painel).toBeDefined();
    expect(painel).toContain("var(--altura-bloco-entrar)");
  });

  it("no celular o formulário vem primeiro e a marca embaixo, em uma coluna", () => {
    const celular = /@media \(max-width: \d+px\) \{([\s\S]*)\}\s*$/.exec(css)![1];
    expect(celular).toMatch(/\.entrar \{ flex-direction: column; \}/);
    expect(/\.entrar__painel \{([^}]*)\}/.exec(celular)![1]).toContain("order: 1");
    expect(/\.entrar__marca \{([^}]*)\}/.exec(celular)![1]).toContain("order: 2");
  });
});
