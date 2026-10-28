import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";

const { api } = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("./api", async (original) => ({ ...(await original<typeof import("./api")>()), api }));

const OBRA = { id: 7, orgao: "SINFRA - SUEF II", contratante: "SINFRA", numero_instrumento: "IC 7/2026", nome_curto: "Granito",
  estado: "ativo", entidade_id: 1, valor_vigente_centavos: 1000_00, medido_execucao_centavos: 250_00, saldo_centavos: 750_00,
  execucao_fim_vigente: "2027-03-31", vigencia_fim_vigente: "2027-06-30", dias_execucao: 100, dias_vigencia: 200 };
const AVISO = { tipo: "execucao_vencendo", nivel: "critico", publico: ["operacao"], contrato_id: 7, obra: "Granito", dias: 5,
  valor_centavos: null, mensagem: "Granito: execução termina em 5 dias (04/11/2026)", destino: { tela: "contrato", id: 7, aba: "prazos" },
  data: "2026-11-04", sentido: "prazo" };

describe("App: a rota antiga /avisos", () => {
  beforeEach(() => {
    api.mockImplementation(async (caminho: string) => {
      if (caminho === "/api/auth/eu") return { id: 1, nome: "Admin Exemplo", email: "a@lotufo.com", perfil: "admin", csrf: "x" };
      if (caminho === "/api/contratos") return [OBRA];
      if (caminho === "/api/entidades") return [];
      if (caminho === "/api/inicio") return { avisos: [AVISO] };
      return [];
    });
  });
  afterEach(() => { cleanup(); api.mockReset(); window.history.replaceState(null, "", "/"); });

  it("abre Obras com os Avisos de todas as obras abertos, mantendo o filtro do link, e acende o item Avisos", async () => {
    window.history.replaceState(null, "", "/avisos?obra=7");
    render(<App />);
    expect(await screen.findByRole("heading", { name: "Avisos · Todas as obras" })).toBeTruthy();
    expect(window.location.pathname + window.location.search).toBe("/obras?c=todas&avisos=1&obra=7");
    const trilho = within(screen.getByRole("navigation", { name: "Navegação principal" }));
    expect(trilho.getByRole("link", { name: "Avisos" }).getAttribute("aria-current")).toBe("page");
    expect(trilho.getByRole("link", { name: "Obras" }).getAttribute("aria-current")).toBeNull();
  });
});

describe("App: a tela SIGA", () => {
  const entrar = (perfil: string) => api.mockImplementation(async (caminho: string) => {
    if (caminho === "/api/auth/eu") return { id: 1, nome: "Usuário Exemplo", email: "u@lotufo.com", perfil, csrf: "x" };
    if (caminho === "/api/siga") return { lido_em: null, atrasado: false, processos: [] };
    return [];
  });
  afterEach(() => { cleanup(); api.mockReset(); window.history.replaceState(null, "", "/"); });

  it("a engenharia vê o item SIGA no trilho, logo depois de Avisos, e /siga abre a tela com o título SIGA na barra", async () => {
    entrar("engenharia");
    window.history.replaceState(null, "", "/siga");
    render(<App />);
    expect(await screen.findByText("Nenhum processo acompanhado.")).toBeTruthy();
    const trilho = within(screen.getByRole("navigation", { name: "Navegação principal" }));
    const nomes = trilho.getAllByRole("link").map(l => l.textContent);
    expect(nomes[nomes.indexOf("Avisos") + 1]).toBe("SIGA");
    expect(trilho.getByRole("link", { name: "SIGA" }).getAttribute("aria-current")).toBe("page");
    expect(screen.getByRole("heading", { level: 1, name: "SIGA" })).toBeTruthy();
    expect(window.location.pathname).toBe("/siga");
  });

  it("a diretoria não tem o item e /siga cai na entrada do perfil", async () => {
    entrar("diretoria");
    window.history.replaceState(null, "", "/siga");
    render(<App />);
    await screen.findByRole("navigation", { name: "Navegação principal" });
    expect(within(screen.getByRole("navigation", { name: "Navegação principal" })).queryByRole("link", { name: "SIGA" })).toBeNull();
    expect(window.location.pathname).toBe("/inicio");
    expect(api).not.toHaveBeenCalledWith("/api/siga");
  });
});
