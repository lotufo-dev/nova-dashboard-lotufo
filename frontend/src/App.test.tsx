import { act, cleanup, render, screen, within } from "@testing-library/react";
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

const PAINEL_MINIMO = {
  hoje: "2026-10-28", notas_a_enviar: 0, certidoes: { vencidas: 0, vencendo: 0, itens: [] }, reajustes: [],
  protocoladas: { obras_protocoladas: 0, obras_ativas: 0, ultima: null },
  medido: { competencia: "2026-10", valor_centavos: 0, quantidade: 0, ultimo_lancamento: null },
  recebido_ano: { valor_centavos: null, mes_centavos: 0, sem_data: 0 },
  a_receber: { liberado: false, valor_centavos: null, mais_60_centavos: null }, prazos: [],
  ciclo: ["em_analise", "boletim", "nota", "protocolado", "recebido_mes"].map(
    etapa => ({ etapa, valor_centavos: 0, quantidade: 0, mais_antigo_dias: null })),
  notas_mes: { mes: "2026-10", valor_centavos: 0, notas: 0, obras: 0 },
  avisos_importantes: { reajustes: { total: 0, itens: [] }, prazos: { total: 0, itens: [] }, certidoes: { total: 0, itens: [] } },
};

describe("App: a tela SIGA", () => {
  const entrar = (perfil: string) => api.mockImplementation(async (caminho: string) => {
    if (caminho === "/api/auth/eu") return { id: 1, nome: "Usuário Exemplo", email: "u@lotufo.com", perfil, csrf: "x" };
    if (caminho === "/api/siga") return { lido_em: null, atrasado: false, processos: [], pode_atualizar: false,
      robo: { estado: "parado", rodada: null, pedidos: [], avisos: [] } };
    // o Inicio (entrada da diretoria) le este painel: sem o corpo minimo ele quebra e derruba a casca
    if (caminho === "/api/inicio/painel") return PAINEL_MINIMO;
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
    await screen.findByRole("heading", { level: 1, name: /^(Bom dia|Boa tarde|Boa noite)/ });      // o Início carregou
    await screen.findByRole("navigation", { name: "Navegação principal" });
    expect(within(screen.getByRole("navigation", { name: "Navegação principal" })).queryByRole("link", { name: "SIGA" })).toBeNull();
    expect(window.location.pathname).toBe("/inicio");
    expect(api).not.toHaveBeenCalledWith("/api/siga");
  });
});

// Issue #417: fora do servidor oficial a dashboard sobe em modo copia; o health diz isso e toda tela mostra a faixa.
describe("App: instalação não autorizada", () => {
  const FAIXA = "Instalação não autorizada da Dashboard Lotufo. Envio de e-mail e sincronização com o RM estão desligados.";
  const subir = (instalacao: string, logado = true) => api.mockImplementation(async (caminho: string) => {
    if (caminho === "/api/health") {
      return { status: "ok", banco: "ok", instalacao, instalacao_motivo: instalacao === "nao-autorizada" ? "ausente" : null };
    }
    if (caminho === "/api/auth/eu") {
      if (!logado) throw new Error("sem sessão");
      return { id: 1, nome: "Admin Exemplo", email: "a@lotufo.com", perfil: "admin", csrf: "x" };
    }
    if (caminho === "/api/inicio/painel") return PAINEL_MINIMO;
    return [];
  });
  afterEach(() => { cleanup(); api.mockReset(); window.history.replaceState(null, "", "/"); });

  it("mostra a faixa vermelha nas telas logadas quando o health diz nao-autorizada", async () => {
    subir("nao-autorizada");
    window.history.replaceState(null, "", "/inicio");
    render(<App />);
    await screen.findByRole("heading", { level: 1, name: /^(Bom dia|Boa tarde|Boa noite)/ });
    expect((await screen.findByRole("alert")).textContent).toBe(FAIXA);
  });

  it("mostra a faixa também na tela de login", async () => {
    subir("nao-autorizada", false);
    render(<App />);
    expect((await screen.findByRole("alert")).textContent).toBe(FAIXA);
    expect(screen.getByRole("button", { name: "Entrar" })).toBeTruthy();
  });

  it("relê o health: a leitura que falhou na abertura não esconde a faixa para sempre", async () => {
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
    try {
      let falhar = true;
      api.mockImplementation(async (caminho: string) => {
        if (caminho === "/api/health") {
          if (falhar) throw new Error("servidor reiniciando");
          return { status: "ok", banco: "ok", instalacao: "nao-autorizada", instalacao_motivo: "ausente" };
        }
        if (caminho === "/api/auth/eu") return { id: 1, nome: "Admin Exemplo", email: "a@lotufo.com", perfil: "admin", csrf: "x" };
        if (caminho === "/api/inicio/painel") return PAINEL_MINIMO;
        return [];
      });
      window.history.replaceState(null, "", "/inicio");
      render(<App />);
      await screen.findByRole("heading", { level: 1, name: /^(Bom dia|Boa tarde|Boa noite)/ });
      expect(screen.queryByText(FAIXA)).toBeNull();
      falhar = false;
      await act(async () => { vi.advanceTimersByTime(5 * 60_000); });
      expect((await screen.findByText(FAIXA)).getAttribute("role")).toBe("alert");
    } finally {
      vi.useRealTimers();
    }
  });

  it("sem faixa quando a instalação está autorizada (e no dev)", async () => {
    for (const instalacao of ["autorizada", "dev"]) {
      subir(instalacao);
      window.history.replaceState(null, "", "/inicio");
      render(<App />);
      await screen.findByRole("heading", { level: 1, name: /^(Bom dia|Boa tarde|Boa noite)/ });
      expect(api).toHaveBeenCalledWith("/api/health");
      expect(screen.queryByText(FAIXA)).toBeNull();
      cleanup(); api.mockReset();
    }
  });
});


describe("App: o menu lateral largo", () => {
  const entrar = () => api.mockImplementation(async (caminho: string) => {
    if (caminho === "/api/auth/eu") return { id: 1, nome: "Usuário Exemplo", email: "u@lotufo.com", perfil: "admin", csrf: "x" };
    if (caminho === "/api/siga") return { lido_em: null, atrasado: false, processos: [], pode_atualizar: false,
      robo: { estado: "parado", rodada: null, pedidos: [], avisos: [] } };
    if (caminho === "/api/inicio/painel") return PAINEL_MINIMO;
    return [];
  });
  beforeEach(() => { try { localStorage.clear(); } catch { /* sem armazenamento: o menu abre largo */ } });
  afterEach(() => { cleanup(); api.mockReset(); window.history.replaceState(null, "", "/"); });

  it("abre largo, com ícone e nome em cada item, e marca o item ativo", async () => {
    entrar();
    window.history.replaceState(null, "", "/siga");
    render(<App />);
    const nav = await screen.findByRole("navigation", { name: "Navegação principal" });
    expect(nav.getAttribute("data-estado")).toBe("largo");
    const links = within(nav).getAllByRole("link");
    expect(links.map(l => l.textContent)).toEqual(
      ["Início", "Medições", "Obras", "Avisos", "SIGA", "Documentos", "A receber", "Carteira", "Âncoras DocuSign", "Administração"]);
    for (const l of links) expect(l.querySelector("svg")).not.toBeNull();
    expect(within(nav).getByRole("link", { name: "SIGA" }).getAttribute("aria-current")).toBe("page");
    expect(links.filter(l => l.getAttribute("aria-current") === "page")).toHaveLength(1);
  });

  it("recolhe pelo botão (só ícones, nome continua acessível) e lembra a escolha", async () => {
    entrar();
    window.history.replaceState(null, "", "/siga");
    render(<App />);
    const nav = await screen.findByRole("navigation", { name: "Navegação principal" });
    const botao = within(nav).getByRole("button", { name: "Recolher o menu" });
    expect(botao.getAttribute("aria-expanded")).toBe("true");
    await act(async () => { botao.click(); });
    expect(nav.getAttribute("data-estado")).toBe("recolhido");
    expect(within(nav).getByRole("button", { name: "Expandir o menu" }).getAttribute("aria-expanded")).toBe("false");
    expect(within(nav).getByRole("link", { name: "SIGA" })).toBeTruthy();
    cleanup();
    render(<App />);
    expect((await screen.findByRole("navigation", { name: "Navegação principal" })).getAttribute("data-estado")).toBe("recolhido");
  });
});

describe("App: o menu lateral no celular (375 px)", () => {
  let ouvintes: Array<(ev: { matches: boolean }) => void>;
  beforeEach(() => {
    try { localStorage.clear(); } catch { /* sem armazenamento */ }
    ouvintes = [];
    // o jsdom nao tem matchMedia: simula "(max-width: 767px)" como verdadeiro (janela de 375 px)
    Object.defineProperty(window, "matchMedia", { configurable: true, writable: true, value: (q: string) => ({
      matches: q === "(max-width: 767px)", media: q,
      addEventListener: (_: string, f: (ev: { matches: boolean }) => void) => { ouvintes.push(f); },
      removeEventListener: (_: string, f: (ev: { matches: boolean }) => void) => { ouvintes = ouvintes.filter(o => o !== f); },
    }) });
    api.mockImplementation(async (caminho: string) => {
      if (caminho === "/api/auth/eu") return { id: 1, nome: "Usuário Exemplo", email: "u@lotufo.com", perfil: "admin", csrf: "x" };
      if (caminho === "/api/siga") return { lido_em: null, atrasado: false, processos: [], pode_atualizar: false,
        robo: { estado: "parado", rodada: null, pedidos: [], avisos: [] } };
      if (caminho === "/api/inicio/painel") return PAINEL_MINIMO;
      return [];
    });
    window.history.replaceState(null, "", "/siga");
  });
  afterEach(() => {
    cleanup(); api.mockReset(); window.history.replaceState(null, "", "/");
    Reflect.deleteProperty(window, "matchMedia");
  });

  it("nasce recolhido, abre pelo botão, fecha ao navegar e não grava a escolha", async () => {
    render(<App />);
    const nav = await screen.findByRole("navigation", { name: "Navegação principal" });
    expect(nav.getAttribute("data-estado")).toBe("recolhido");
    await act(async () => { within(nav).getByRole("button", { name: "Expandir o menu" }).click(); });
    expect(nav.getAttribute("data-estado")).toBe("largo");
    await act(async () => { within(nav).getByRole("link", { name: "Obras" }).click(); });
    expect(nav.getAttribute("data-estado")).toBe("recolhido");
    expect(localStorage.getItem("menu-lateral")).toBeNull();
  });

  it("aberto por cima da tela, fecha com Esc e com toque fora", async () => {
    render(<App />);
    const nav = await screen.findByRole("navigation", { name: "Navegação principal" });
    const abrir = () => act(async () => { within(nav).getByRole("button", { name: "Expandir o menu" }).click(); });
    await abrir();
    await act(async () => { document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" })); });
    expect(nav.getAttribute("data-estado")).toBe("recolhido");
    await abrir();
    await act(async () => { document.body.dispatchEvent(new MouseEvent("mousedown", { bubbles: true })); });
    expect(nav.getAttribute("data-estado")).toBe("recolhido");
  });

  it("estreitar a janela com o menu largo o recolhe", async () => {
    Reflect.deleteProperty(window, "matchMedia");
    Object.defineProperty(window, "matchMedia", { configurable: true, writable: true, value: (q: string) => ({
      matches: false, media: q,
      addEventListener: (_: string, f: (ev: { matches: boolean }) => void) => { ouvintes.push(f); },
      removeEventListener: () => {},
    }) });
    render(<App />);
    const nav = await screen.findByRole("navigation", { name: "Navegação principal" });
    expect(nav.getAttribute("data-estado")).toBe("largo");
    await act(async () => { ouvintes.forEach(f => f({ matches: true })); });
    expect(nav.getAttribute("data-estado")).toBe("recolhido");
  });

  it("recolhido no computador, cada link ganha o nome como dica", async () => {
    Reflect.deleteProperty(window, "matchMedia");
    try { localStorage.setItem("menu-lateral", "recolhido"); } catch { /* sem armazenamento */ }
    render(<App />);
    const nav = await screen.findByRole("navigation", { name: "Navegação principal" });
    expect(within(nav).getByRole("link", { name: "SIGA" }).getAttribute("title")).toBe("SIGA");
  });
});
