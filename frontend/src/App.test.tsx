import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";

const { api } = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("./api", async (original) => ({ ...(await original<typeof import("./api")>()), api }));

// a faixa de numeros e os limites do tempo parado que GET /api/siga manda sempre (#805)
const SIGA_SEM_PROCESSO = { numeros: { acompanhados: 0, parados: 0, andaram_hoje: 0, nao_lidos: 0 }, limites: { dias_atencao: 5, dias_critico: 10 } };

const OBRA = { id: 7, orgao: "SINFRA - SUEF II", contratante: "SINFRA", numero_instrumento: "IC 7/2026", nome_curto: "Granito",
  estado: "ativo", entidade_id: 1, valor_vigente_centavos: 1000_00, medido_centavos: 250_00, saldo_centavos: 750_00,
  execucao_fim_vigente: "2027-03-31", vigencia_fim_vigente: "2027-06-30", dias_execucao: 100, dias_vigencia: 200 };
const AVISO = { tipo: "execucao_vencendo", nivel: "critico", publico: ["operacao"], contrato_id: 7, obra: "Granito", dias: 5,
  valor_centavos: null, mensagem: "Granito: execução termina em 5 dias (04/11/2026)", destino: { tela: "contrato", id: 7, aba: "prazos" },
  data: "2026-11-04", sentido: "prazo" };

describe("App: os Avisos têm página própria (#805)", () => {
  const servir = (perfil: string) => api.mockImplementation(async (caminho: string) => {
    if (caminho === "/api/auth/eu") return { id: 1, nome: "Pessoa Exemplo", email: "a@lotufo.com", perfil, csrf: "x" };
    if (caminho === "/api/contratos") return [OBRA];
    if (caminho === "/api/inicio") return { avisos: [AVISO] };
    return [];
  });
  beforeEach(() => { servir("admin"); });
  afterEach(() => { cleanup(); api.mockReset(); window.history.replaceState(null, "", "/"); });

  const trilho = () => within(screen.getByRole("navigation", { name: "Navegação principal" }));

  it("/avisos abre a página Avisos: o título do topo e o da aba do navegador dizem Avisos, e o item do menu fica aceso", async () => {
    window.history.replaceState(null, "", "/avisos");
    render(<App />);
    expect(await screen.findByRole("heading", { level: 1, name: "Avisos" })).toBeTruthy();
    expect(await screen.findByRole("heading", { level: 2, name: "Agenda" })).toBeTruthy();
    expect(window.location.pathname + window.location.search).toBe("/avisos");
    expect(document.title).toBe("Avisos · grupolotufo");
    expect(trilho().getByRole("link", { name: "Avisos" }).getAttribute("aria-current")).toBe("page");
    expect(trilho().getByRole("link", { name: "Obras" }).getAttribute("aria-current")).toBeNull();
    // não é mais a lista de Obras com os avisos em cima
    expect(screen.queryByRole("heading", { name: /^Obras/ })).toBeNull();
    expect(screen.queryByRole("table", { name: "Obras, posição financeira" })).toBeNull();
  });

  it("o endereço de antes (/obras?avisos=1, com os filtros) leva para /avisos com os filtros equivalentes", async () => {
    window.history.replaceState(null, "", "/obras?c=todas&avisos=1&obra=7&familia=prazos&nivel=critico");
    render(<App />);
    expect(await screen.findByRole("heading", { level: 2, name: "Avisos · Granito" })).toBeTruthy();
    expect(window.location.pathname + window.location.search).toBe("/avisos?familia=prazos&obra=7");
    expect(screen.getByRole("heading", { level: 1, name: "Avisos" })).toBeTruthy();
    expect(trilho().getByRole("link", { name: "Avisos" }).getAttribute("aria-current")).toBe("page");
    expect(trilho().getByRole("link", { name: "Obras" }).getAttribute("aria-current")).toBeNull();
  });

  it("quem só consulta (diretoria) abre a mesma página", async () => {
    servir("diretoria");
    window.history.replaceState(null, "", "/avisos");
    render(<App />);
    expect(await screen.findByRole("heading", { level: 2, name: "Agenda" })).toBeTruthy();
    expect(window.location.pathname).toBe("/avisos");
    expect(trilho().getByRole("link", { name: "Avisos" }).getAttribute("aria-current")).toBe("page");
  });

  it("/obras sem ?avisos=1 continua sendo a lista de Obras", async () => {
    window.history.replaceState(null, "", "/obras?c=SINFRA");
    render(<App />);
    expect(await screen.findByRole("heading", { level: 1, name: /^Obras/ })).toBeTruthy();
    // O filtro de antes da #805 (?c=) abre a tabela de todas as obras, com o filtro, quando a lista chega
    // (Contratos.tsx). O teste espera esse endereco final: conferir o endereco logo que o titulo aparece dependia de a
    // lista ja' ter chegado ou nao, e o teste passava ou falhava conforme a maquina.
    await waitFor(() => expect(window.location.pathname + window.location.search).toBe("/obras/todas?c=SINFRA"));
    expect(screen.getByRole("heading", { level: 1, name: /^Obras/ })).toBeTruthy();
    expect(trilho().getByRole("link", { name: "Obras" }).getAttribute("aria-current")).toBe("page");
    expect(trilho().getByRole("link", { name: "Avisos" }).getAttribute("aria-current")).toBeNull();
  });
});

const PAINEL_MINIMO = {
  hoje: "2026-10-28",
  protocoladas: { obras_protocoladas: 0, obras_ativas: 0, ultima: null },
  medido: { competencia: "2026-10", valor_centavos: 0, quantidade: 0, ultimo_lancamento: null },
  a_receber: { liberado: false, valor_centavos: null, mais_60_centavos: null },
  ciclo: ["em_analise", "boletim", "nota", "protocolado", "recebido_mes"].map(
    etapa => ({ etapa, valor_centavos: 0, quantidade: 0, mais_antigo_dias: null })),
  recebido_12m: [], matriz: { competencias: [], grupos: [] },
  previsao: Object.fromEntries(["neste_mes", "proximo_mes", "atrasado", "sem_previsao", "depois"].map(
    k => [k, { valor_centavos: 0, quantidade: 0 }])),
  notas_mes: { mes: "2026-10", valor_centavos: 0, notas: 0, obras: 0 },
  ciclo_por_contratante: [], medido_12m: [],       // #817: os blocos novos da Inicio
};

describe("App: a tela SIGA", () => {
  const entrar = (perfil: string) => api.mockImplementation(async (caminho: string) => {
    if (caminho === "/api/auth/eu") return { id: 1, nome: "Usuário Exemplo", email: "u@lotufo.com", perfil, csrf: "x" };
    if (caminho === "/api/siga") return { lido_em: null, atrasado: false, processos: [], pode_atualizar: false,
      robo: { estado: "parado", rodada: null, pedidos: [], avisos: [] }, ...SIGA_SEM_PROCESSO };
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
      robo: { estado: "parado", rodada: null, pedidos: [], avisos: [] }, ...SIGA_SEM_PROCESSO };
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
    // #814: as páginas na ordem das áreas (Painel, Medições, Obras, Financeiro, Prazos e avisos, Órgãos, Documentos, Sistema)
    expect(links.map(l => l.textContent)).toEqual(
      ["Início", "Medições", "Resumo das medições", "Obras", "Fechamento", "A receber", "Avisos", "SIGA", "Certidões", "Regularidade mensal",
        "Garantias", "Âncoras DocuSign", "Administração", "Minha conta"]);
    for (const l of links) expect(l.querySelector("svg")).not.toBeNull();
    expect(within(nav).getByRole("link", { name: "SIGA" }).getAttribute("aria-current")).toBe("page");
    expect(links.filter(l => l.getAttribute("aria-current") === "page")).toHaveLength(1);
    // a área da página aberta fica com o nome aceso
    expect([...nav.querySelectorAll(".menu__area--acesa .menu__area-nome")].map(n => n.textContent)).toEqual(["Órgãos"]);
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
        robo: { estado: "parado", rodada: null, pedidos: [], avisos: [] }, ...SIGA_SEM_PROCESSO };
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
    // #779: alargar de volta devolve a escolha guardada (largo), em vez de deixar recolhido ate' recarregar
    await act(async () => { ouvintes.forEach(f => f({ matches: false })); });
    expect(nav.getAttribute("data-estado")).toBe("largo");
    // quem escolheu recolhido no computador continua recolhido depois de estreitar e alargar
    try { localStorage.setItem("menu-lateral", "recolhido"); } catch { /* sem armazenamento */ }
    await act(async () => { ouvintes.forEach(f => f({ matches: true })); });
    await act(async () => { ouvintes.forEach(f => f({ matches: false })); });
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

describe("App: Medições abre na fila de trabalho, com as vistas no endereço (#643, #805)", () => {
  const SEM = { quantidade: 0, criticas: 0, breves: 0, alem_do_prazo: 0 };
  beforeEach(() => {
    try { localStorage.removeItem("menu-lateral"); } catch { /* sem armazenamento */ }
    api.mockImplementation(async (caminho: string) => {
      if (caminho === "/api/auth/eu") return { id: 1, nome: "Pessoa da Engenharia", email: "eng@lotufo.com", perfil: "engenharia", csrf: "x" };
      if (caminho.startsWith("/api/medicoes/fila")) {
        return { hoje: "2026-11-07", mes: caminho.split("mes=")[1], obras: [], limites: { dias_atencao: 5, dias_critico: 10, diferenca_critica_por_mil: 5 },
          numeros: { com: { lotufo: SEM, faturamento: SEM, orgao: SEM }, concluidas: 0, sem_medicao: 0, pedido_centavos: null, aprovado_centavos: null,
            aprovado_com_pedido_centavos: null, pedido_do_aprovado_centavos: null, abaixo_do_pedido_centavos: null },
          grupos: [], concluidas: [], sem_medicao: [], quadro: [],
          anteriores: { linhas: [], esperam_pagamento: 0, antes_do_ano_inicial: 0, ano_inicial: "2025" } };
      }
      return [];
    });
  });
  afterEach(() => { cleanup(); api.mockReset(); window.history.replaceState(null, "", "/"); });

  it("o endereço /medicoes/quadro abre o quadro do mês, e /medicoes/anteriores, os meses anteriores", async () => {
    window.history.replaceState(null, "", "/medicoes/quadro");
    render(<App />);
    expect(await screen.findByRole("heading", { name: "Quadro do mês" })).toBeTruthy();
    expect(window.location.pathname).toBe("/medicoes/quadro");
    fireEvent.click(within(screen.getByRole("navigation", { name: "Vistas de Medições" })).getByRole("link", { name: "Meses anteriores" }));
    expect(await screen.findByText("Nenhuma medição de meses anteriores pede ação.")).toBeTruthy();
    expect(window.location.pathname).toBe("/medicoes/anteriores");
  });

  it.each(["/medicoes/em-andamento", "/medicoes/iniciar", "/notas"])("o endereço antigo %s leva à fila e o menu tem só o item Medições", async (antigo) => {
    window.history.replaceState(null, "", antigo);
    render(<App />);
    expect(await screen.findByRole("heading", { name: "Concluídas no mês" })).toBeTruthy();
    expect(window.location.pathname).toBe("/medicoes");
    const nav = within(screen.getByRole("navigation", { name: "Navegação principal" }));
    expect(nav.getByRole("link", { name: "Medições" }).getAttribute("aria-current")).toBe("page");
    expect(nav.queryByRole("link", { name: /Iniciar medição/ })).toBeNull();
    expect(nav.queryByRole("link", { name: /Em andamento/ })).toBeNull();
    expect(document.title).toBe("Medições · grupolotufo");
  });
});

describe("App: aviso flutuante de resposta do órgão (issue #654)", () => {
  const NAO_VISTA = { medicao_id: 31, contrato_id: 7, orgao: "SINFRA", obra: "Granito", numero: 3, tipo: "execucao",
    respostas: 1, ate: 9, recebida_em: "2026-11-10T14:00:00Z" };
  const entrar = (perfil: string) => api.mockImplementation(async (caminho: string) => {
    if (caminho === "/api/auth/eu") return { id: 1, nome: "Usuário Exemplo", email: "u@lotufo.com", perfil, csrf: "x" };
    if (caminho === "/api/inicio/painel") return PAINEL_MINIMO;
    if (caminho === "/api/siga") return { lido_em: null, atrasado: false, processos: [], pode_atualizar: false,
      robo: { estado: "parado", rodada: null, pedidos: [], avisos: [] }, ...SIGA_SEM_PROCESSO };
    if (caminho === "/api/correio/respostas/nao-vistas") return [NAO_VISTA];
    if (caminho === "/api/correio/respostas/ler") return { novas: [] };
    return [];
  });
  afterEach(() => { cleanup(); api.mockReset(); window.history.replaceState(null, "", "/"); });

  it("quem envia vê o aviso em qualquer página, fora do conteúdo da tela", async () => {
    entrar("engenharia");
    window.history.replaceState(null, "", "/siga");
    render(<App />);
    const aviso = (await screen.findByText("SINFRA respondeu:")).closest(".aviso-respostas")!;
    expect(aviso.textContent).toContain("SINFRA respondeu: Granito, 3ª Medição");
    expect(document.getElementById("conteudo")!.contains(aviso)).toBe(false);
  });

  it("a diretoria nunca vê o aviso nem pede as respostas não vistas", async () => {
    entrar("diretoria");
    render(<App />);
    await screen.findByRole("navigation", { name: "Navegação principal" });
    await act(async () => {});
    expect(screen.queryByText("SINFRA respondeu:")).toBeNull();
    expect(api.mock.calls.some(c => String(c[0]).startsWith("/api/correio/respostas"))).toBe(false);
  });
});

// #814 (decisão do dono de 18/11/2026, #805): o caminho no alto de toda página, as rotas das páginas novas e os
// endereços de antes.
describe("App: o caminho no alto e as páginas novas do menu em áreas (#814)", () => {
  const SEM = { quantidade: 0, criticas: 0, breves: 0, alem_do_prazo: 0 };
  const entrar = (perfil: string) => api.mockImplementation(async (caminho: string) => {
    if (caminho === "/api/auth/eu") return { id: 1, nome: "Pessoa Exemplo", email: "p@lotufo.com", perfil, csrf: "x" };
    if (caminho === "/api/inicio/painel") return PAINEL_MINIMO;
    if (caminho === "/api/inicio") return { avisos: [] };
    if (caminho === "/api/contratos") return [{ ...OBRA, contratante_chave: "sinfra" }];
    if (caminho === "/api/documentos") return (await import("./documentosTeste")).PAINEL;
    if (caminho === "/api/siga") return { lido_em: null, atrasado: false, processos: [], pode_atualizar: false,
      robo: { estado: "parado", rodada: null, pedidos: [], avisos: [] }, ...SIGA_SEM_PROCESSO };
    if (caminho.startsWith("/api/medicoes/fila")) {
      return { hoje: "2026-11-07", mes: "2026-11", obras: [], limites: { dias_atencao: 5, dias_critico: 10, diferenca_critica_por_mil: 5 },
        numeros: { com: { lotufo: SEM, faturamento: SEM, orgao: SEM }, concluidas: 0, sem_medicao: 0, pedido_centavos: null, aprovado_centavos: null,
          aprovado_com_pedido_centavos: null, pedido_do_aprovado_centavos: null, abaixo_do_pedido_centavos: null },
        grupos: [], concluidas: [], sem_medicao: [], quadro: [],
        anteriores: { linhas: [], esperam_pagamento: 0, antes_do_ano_inicial: 0, ano_inicial: "2025" } };
    }
    if (caminho === "/api/health" || caminho.startsWith("/api/correio/respostas")) return [];
    // #816: a página A receber sem nada em aberto, com a SINFRA na fileira (contrato ativo), com zero
    if (caminho === "/api/a-receber") {
      return { anos: ["2025", "2026"], total_a_receber_liberado: true, em_aberto_centavos: 0, por_ano: { 2025: 0, 2026: 0 },
        quantidade: 0, alem_do_prazo: 0, notas_sem_medicao: [], notas_sem_medicao_centavos: 0, anteriores: { quantidade: 0, valor_centavos: 0 },
        contratantes: [{ contratante: "SINFRA", chave: "sinfra", prazo_orgao_dias: null, quantidade: 0, em_aberto_centavos: 0,
          por_ano: { 2025: 0, 2026: 0 }, alem_do_prazo: 0, linhas: [], notas_sem_medicao: [], notas_sem_medicao_centavos: 0,
          anteriores: { quantidade: 0, valor_centavos: 0 } }] };
    }
    // o que a página pedir além disso falha: ela mostra a falha de leitura dela, e a casca continua de pé
    throw new Error("sem dado neste teste");
  });
  beforeEach(() => { try { localStorage.clear(); } catch { /* sem armazenamento: o menu abre largo */ } });
  afterEach(() => { cleanup(); api.mockReset(); window.history.replaceState(null, "", "/"); });

  // a barra do topo (as páginas de detalhe têm o próprio <header>, que não é ela)
  const topo = () => document.querySelector<HTMLElement>("header.topo")!;
  const caminho = () => within(topo()).getByRole("navigation", { name: "Você está em" });
  const trechos = () => [...caminho().querySelectorAll("li")].map(li => li.textContent);
  const aceso = () => within(screen.getByRole("navigation", { name: "Navegação principal" })).getAllByRole("link")
    .filter(l => l.getAttribute("aria-current") === "page").map(l => l.textContent);
  const endereco = () => window.location.pathname + window.location.search;

  it("/a-receber abre a página A receber, com o caminho, o título e o estado vazio; o item fica aceso", async () => {
    entrar("diretoria");
    window.history.replaceState(null, "", "/a-receber");
    render(<App />);
    expect(await screen.findByRole("heading", { level: 1, name: "A receber" })).toBeTruthy();
    expect(trechos()).toEqual(["Financeiro", "A receber"]);
    expect(within(caminho()).getByRole("link", { name: "Financeiro" }).getAttribute("href")).toBe("/fechamento");
    expect(await screen.findByText("Nenhuma nota em aberto.")).toBeTruthy();
    expect(endereco()).toBe("/a-receber");                    // da #748 até aqui o endereço levava ao Fechamento
    expect(aceso()).toEqual(["A receber"]);
    expect(document.title).toBe("A receber · grupolotufo");
  });

  it("/a-receber?contratante= mostra só o contratante do endereço, pela chave da página dele em Obras (#816)", async () => {
    entrar("admin");
    window.history.replaceState(null, "", "/a-receber?contratante=sinfra");
    render(<App />);
    expect(await screen.findByText("Nenhuma nota em aberto de SINFRA.")).toBeTruthy();
    expect(endereco()).toBe("/a-receber?contratante=sinfra");
    await act(async () => { fireEvent.click(screen.getByRole("link", { name: "Ver todos os contratantes" })); });
    expect(endereco()).toBe("/a-receber");
    expect(screen.getByText("Nenhuma nota em aberto.")).toBeTruthy();
  });

  it("Documentos tem três endereços, cada um com a página acesa, o caminho e o título dele", async () => {
    entrar("diretoria");
    window.history.replaceState(null, "", "/documentos/garantias");
    render(<App />);
    expect(await screen.findByRole("heading", { level: 1, name: "Garantias" })).toBeTruthy();
    expect(trechos()).toEqual(["Documentos", "Garantias"]);
    expect(aceso()).toEqual(["Garantias"]);
    expect(document.title).toBe("Garantias · Documentos · grupolotufo");
    await screen.findAllByRole("region", { name: /^Garantias de / });
    // do menu para a Regularidade mensal: outro endereço, outra página acesa
    await act(async () => {
      fireEvent.click(within(screen.getByRole("navigation", { name: "Navegação principal" })).getByRole("link", { name: "Regularidade mensal" }));
    });
    expect(endereco()).toBe("/documentos/regularidade");
    expect(await screen.findByRole("list", { name: "Regularidade mensal por empresa" })).toBeTruthy();
    expect(trechos()).toEqual(["Documentos", "Regularidade mensal"]);
    expect(aceso()).toEqual(["Regularidade mensal"]);
    // e pelo trecho da área, de volta à primeira página dela
    await act(async () => { fireEvent.click(within(caminho()).getByRole("link", { name: "Documentos" })); });
    expect(endereco()).toBe("/documentos");
    expect(await screen.findByRole("heading", { level: 1, name: "Certidões" })).toBeTruthy();
    expect(aceso()).toEqual(["Certidões"]);
  });

  it.each([
    ["/documentos?aba=regularidade", "/documentos/regularidade", "Regularidade mensal"],
    ["/documentos?aba=garantias", "/documentos/garantias", "Garantias"],
    ["/documentos?aba=certidoes", "/documentos", "Certidões"],
    ["/documentos/certidoes", "/documentos", "Certidões"],
    ["/certidoes", "/documentos", "Certidões"],
  ])("o endereço de antes %s abre %s", async (antigo, novo, titulo) => {
    entrar("engenharia");
    window.history.replaceState(null, "", antigo);
    render(<App />);
    expect(await screen.findByRole("heading", { level: 1, name: titulo })).toBeTruthy();
    expect(endereco()).toBe(novo);
    expect(aceso()).toEqual([titulo]);
  });

  it("a página do contratante diz o nome ao caminho do topo quando a lista chega; a obra não ganha trilha na página", async () => {
    entrar("diretoria");
    window.history.replaceState(null, "", "/obras/contratante/sinfra");
    render(<App />);
    await screen.findByRole("heading", { level: 1, name: /SINFRA/ });
    await waitFor(() => expect(trechos()).toEqual(["Obras", "SINFRA"]));
    expect(within(caminho()).getByRole("link", { name: "Obras" }).getAttribute("href")).toBe("/obras");
    expect(within(topo()).queryByRole("heading")).toBeNull();                            // o h1 é o da página
    expect(screen.getAllByRole("navigation", { name: "Você está em" })).toHaveLength(1);  // uma trilha só, a do topo
    expect(aceso()).toEqual(["Obras"]);
  });

  it.each(["medicoes", "a-receber", "avisos"])("a aba %s do contratante já tem endereço; enquanto a página não a desenha (#818), ele abre a página", async (aba) => {
    entrar("engenharia");
    window.history.replaceState(null, "", `/obras/contratante/sinfra/${aba}?situacao=todas`);
    render(<App />);
    await screen.findByRole("heading", { level: 1, name: /SINFRA/ });
    await waitFor(() => expect(endereco()).toBe("/obras/contratante/sinfra?situacao=todas"));
    // e fica lá: a troca do endereço não briga com a do endereço canônico
    await act(async () => {});
    expect(endereco()).toBe("/obras/contratante/sinfra?situacao=todas");
    expect(trechos()).toEqual(["Obras", "SINFRA"]);
  });

  it("a aba do SIGA do contratante segue a tela SIGA: a diretoria cai na página do contratante", async () => {
    entrar("diretoria");
    window.history.replaceState(null, "", "/obras/contratante/sinfra/siga");
    render(<App />);
    await screen.findByRole("heading", { level: 1, name: /SINFRA/ });
    await waitFor(() => expect(endereco()).toBe("/obras/contratante/sinfra"));
    expect(api).not.toHaveBeenCalledWith("/api/siga");
  });

  it("a vista entra no caminho como último trecho, e no título da aba do navegador", async () => {
    entrar("engenharia");
    window.history.replaceState(null, "", "/medicoes/quadro");
    render(<App />);
    expect(await screen.findByRole("heading", { name: "Quadro do mês" })).toBeTruthy();
    expect(trechos()).toEqual(["Medições", "Quadro do mês"]);
    expect(within(topo()).getByRole("heading", { level: 1 }).textContent).toBe("Medições");
    expect(document.title).toBe("Medições · Quadro do mês · grupolotufo");
    await act(async () => { fireEvent.click(within(caminho()).getByRole("link", { name: "Medições" })); });
    expect(endereco()).toBe("/medicoes");
    expect(trechos()).toEqual(["Medições"]);
  });

  it("as abas do Fechamento entram no caminho e no título; a de comparação com os anos que a página diz", async () => {
    // sem lançamento: só os anos importam aqui
    const FECHAMENTO = { anos: ["2025", "2026"], meses: [], por_ano: {}, acumulado: { ate_mes: null }, em_aberto: [],
      em_aberto_anteriores: { quantidade: 0, valor_centavos: 0 },
      notas_sem_medicao: { em_aberto: [], em_aberto_centavos: 0, pagas: { quantidade: 0, valor_centavos: 0 } },
      cobertura: {}, total_a_receber_liberado: true };
    entrar("diretoria");
    const resto = api.getMockImplementation()!;
    api.mockImplementation(async (c: string) => (c === "/api/fechamento" ? FECHAMENTO : resto(c)));
    window.history.replaceState(null, "", "/fechamento/comparacao");
    render(<App />);
    await waitFor(() => expect(trechos()).toEqual(["Financeiro", "Fechamento", "2026 × 2025"]));
    expect(document.title).toBe("Fechamento · 2026 × 2025 · grupolotufo");
    expect(within(topo()).getByRole("heading", { level: 1 }).textContent).toBe("Fechamento");
    expect(within(caminho()).getByRole("link", { name: "Fechamento" }).getAttribute("href")).toBe("/fechamento");
    // pela aba da página, a outra vista
    await act(async () => { fireEvent.click(screen.getByRole("link", { name: "Por contratante" })); });
    expect(endereco()).toBe("/fechamento/contratantes");
    await waitFor(() => expect(trechos()).toEqual(["Financeiro", "Fechamento", "Por contratante"]));
    expect(document.title).toBe("Fechamento · Por contratante · grupolotufo");
    // e pelo trecho da página, a vista padrão, que não entra no caminho
    await act(async () => { fireEvent.click(within(caminho()).getByRole("link", { name: "Fechamento" })); });
    expect(endereco()).toBe("/fechamento");
    await waitFor(() => expect(trechos()).toEqual(["Financeiro", "Fechamento"]));
    expect(document.title).toBe("Fechamento · grupolotufo");
  });

  it.each([
    ["/inicio", ["Painel", "Início"]],
    ["/resumo-medicoes", ["Medições", "Resumo das medições"]],
    ["/obras", ["Obras"]],
    ["/fechamento", ["Financeiro", "Fechamento"]],
    ["/avisos", ["Prazos e avisos", "Avisos"]],
    ["/siga", ["Órgãos", "SIGA"]],
    ["/ancoras-docusign", ["Sistema", "Âncoras DocuSign"]],
    ["/admin", ["Sistema", "Administração"]],
    ["/admin/usuarios", ["Sistema", "Administração", "Usuários"]],
    ["/conta", ["Sistema", "Minha conta"]],
  ])("toda página tem o caminho no alto: %s", async (url, esperado) => {
    entrar("admin");
    window.history.replaceState(null, "", url);
    render(<App />);
    await screen.findByRole("navigation", { name: "Navegação principal" });
    await waitFor(() => expect(trechos()).toEqual(esperado));
    expect(screen.getAllByRole("navigation", { name: "Você está em" })).toHaveLength(1);
    // o trecho da página é o título da barra; ele só não é o h1 onde a página tem o dela (o Início e Obras)
    const titulo = topo().querySelector(".caminho__trecho--titulo")!;
    expect(titulo.textContent).toBe(esperado[esperado.length - 1] === "Usuários" ? "Administração" : esperado[esperado.length - 1]);
    expect(titulo.querySelector("h1") !== null).toBe(url !== "/inicio" && url !== "/obras");
  });

  it("a Minha conta entra pelo menu (área Sistema) e pelo avatar, e fica acesa", async () => {
    entrar("diretoria");
    window.history.replaceState(null, "", "/conta");
    render(<App />);
    expect(await screen.findByRole("heading", { level: 1, name: "Minha conta" })).toBeTruthy();
    expect(aceso()).toEqual(["Minha conta"]);
    const nav = screen.getByRole("navigation", { name: "Navegação principal" });
    expect([...nav.querySelectorAll(".menu__area--acesa .menu__area-nome")].map(n => n.textContent)).toEqual(["Sistema"]);
    // a diretoria não ganhou nada da área Sistema além da própria conta
    expect(within(within(nav).getByRole("list", { name: "Sistema" })).getAllByRole("link").map(l => l.textContent)).toEqual(["Minha conta"]);
  });
});
