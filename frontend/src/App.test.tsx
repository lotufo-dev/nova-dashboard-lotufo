import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";

const { api } = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("./api", async (original) => ({ ...(await original<typeof import("./api")>()), api }));

// as permissoes que /api/auth/eu informa para cada perfil (backend/app/permissoes.py); desde a #829 os tres tem
// `ver_siga`; desde a #908 so' o administrador tem `ver_licitacoes`
const PERMISSOES: Record<string, string[]> = {
  admin: ["administrar", "editar_cadastros", "editar_config_fiscal", "ver_licitacoes", "ver_paineis", "ver_siga"],
  engenharia: ["editar_cadastros", "ver_paineis", "ver_siga"],
  diretoria: ["ver_paineis", "ver_siga"],
};
const permissoesDe = (perfil: string) => PERMISSOES[perfil] ?? [];

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
    if (caminho === "/api/auth/eu") return { id: 1, nome: "Pessoa Exemplo", email: "a@lotufo.com", perfil, permissoes: permissoesDe(perfil), csrf: "x" };
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
  medido: { competencia: "2026-10", valor_centavos: 0 },
  a_receber: { liberado: false, valor_centavos: null, mais_60_centavos: null },
  ciclo: ["em_analise", "boletim", "nota", "protocolado", "recebido_mes"].map(
    etapa => ({ etapa, valor_centavos: 0, quantidade: 0, mais_antigo_dias: null })),
  recebido_12m: [],
  previsao: Object.fromEntries(["neste_mes", "proximo_mes", "atrasado", "sem_previsao", "depois"].map(
    k => [k, { valor_centavos: 0, quantidade: 0 }])),
  notas_mes: { mes: "2026-10", valor_centavos: 0, notas: 0, obras: 0 },
  ciclo_por_contratante: [], medido_12m: [],       // #817: os blocos novos da Inicio
};

describe("App: a tela SIGA", () => {
  const entrar = (perfil: string, permissoes = permissoesDe(perfil)) => api.mockImplementation(async (caminho: string) => {
    if (caminho === "/api/auth/eu") return { id: 1, nome: "Usuário Exemplo", email: "u@lotufo.com", perfil, permissoes, csrf: "x" };
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

  it("a diretoria tem o item e abre a tela, sem botão de escrita (#829: só leitura)", async () => {
    entrar("diretoria");
    window.history.replaceState(null, "", "/siga");
    render(<App />);
    expect(await screen.findByText("Nenhum processo acompanhado.")).toBeTruthy();
    const trilho = within(screen.getByRole("navigation", { name: "Navegação principal" }));
    expect(trilho.getByRole("link", { name: "SIGA" }).getAttribute("aria-current")).toBe("page");
    expect(window.location.pathname).toBe("/siga");
    expect(screen.queryByRole("button", { name: "Acompanhar processo" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Pedir leitura" })).toBeNull();
  });

  it("quem não tem `ver_siga` não tem o item e /siga cai na entrada, qualquer que seja o perfil (#829)", async () => {
    entrar("engenharia", ["editar_cadastros", "ver_paineis"]);
    window.history.replaceState(null, "", "/siga");
    render(<App />);
    await screen.findByRole("heading", { level: 1, name: /^(Bom dia|Boa tarde|Boa noite)/ });      // o Início carregou
    await screen.findByRole("navigation", { name: "Navegação principal" });
    expect(within(screen.getByRole("navigation", { name: "Navegação principal" })).queryByRole("link", { name: "SIGA" })).toBeNull();
    expect(window.location.pathname).toBe("/inicio");
    expect(api).not.toHaveBeenCalledWith("/api/siga");
  });
});

// Issue #908: a área Licitações, com a Triagem e as Favoritas, é de quem tem `ver_licitacoes` (o servidor a dá só ao
// administrador, decisão do dono de 24/11/2026); a regra vem da permissão que o servidor informa, como no SIGA.
describe("App: a área Licitações (#908)", () => {
  const LEITURA = { lido_em: null, atrasada: true, fontes_com_problema: 0 };
  const entrar = (perfil: string, permissoes: string[]) => api.mockImplementation(async (caminho: string) => {
    if (caminho === "/api/auth/eu") return { id: 1, nome: "Usuário Exemplo", email: "u@lotufo.com", perfil, permissoes, csrf: "x" };
    if (caminho === "/api/licitacoes/triagem") return { leitura: LEITURA, favoritas: [], recomendadas: [],
      contagens: { recomendadas: 0, favoritas: 0, novas: 0, novas_desde: null, por_orgao: [] } };
    if (caminho === "/api/licitacoes/favoritas") return { leitura: LEITURA, etapas: [{ etapa: "acompanhando", rotulo: "Acompanhando" }], favoritas: [] };
    if (caminho.startsWith("/api/licitacoes/calendario")) return { leitura: LEITURA, mes: "2026-12", anterior: "2026-11", proximo: "2027-01",
      mes_atual: false, prazos: 0, semanas: [] };
    if (caminho === "/api/inicio/painel") return PAINEL_MINIMO;
    return [];
  });
  afterEach(() => { cleanup(); api.mockReset(); window.history.replaceState(null, "", "/"); });

  const trilho = () => within(screen.getByRole("navigation", { name: "Navegação principal" }));
  const caminho = () => screen.getByRole("navigation", { name: "Você está em" });
  const trechos = () => [...caminho().querySelectorAll("li")].map(li => li.textContent);

  it("o administrador vê a área depois de Órgãos e antes de Documentos, e /licitacoes abre a Triagem", async () => {
    entrar("admin", permissoesDe("admin"));
    window.history.replaceState(null, "", "/licitacoes");
    render(<App />);
    expect(await screen.findByText("Nenhuma recomendada a decidir.")).toBeTruthy();
    expect(api).toHaveBeenCalledWith("/api/licitacoes/triagem");
    expect(within(trilho().getByRole("list", { name: "Licitações" })).getAllByRole("link").map(l => l.textContent)).toEqual(["Triagem", "Favoritas", "Todas"]);
    const nomes = trilho().getAllByRole("link").map(l => l.textContent);
    expect(nomes[nomes.indexOf("SIGA") + 1]).toBe("Triagem");
    expect(nomes[nomes.indexOf("Todas") + 1]).toBe("Certidões");
    expect(trilho().getByRole("link", { name: "Triagem" }).getAttribute("aria-current")).toBe("page");
    // o caminho é da casca: a área (texto, porque a Triagem é a primeira página dela) e a página, que é o h1
    expect(trechos()).toEqual(["Licitações", "Triagem"]);
    expect(within(caminho()).queryByRole("link", { name: "Licitações" })).toBeNull();
    expect(screen.getByRole("heading", { level: 1, name: "Triagem" })).toBeTruthy();
    expect(document.title).toBe("Triagem · grupolotufo");
    expect(window.location.pathname).toBe("/licitacoes");
  });

  it("/licitacoes/favoritas abre as Favoritas; o número da Triagem e a área do caminho levam de uma à outra", async () => {
    entrar("admin", permissoesDe("admin"));
    window.history.replaceState(null, "", "/licitacoes/favoritas");
    render(<App />);
    expect(await screen.findByText("Nenhuma favorita.")).toBeTruthy();
    expect(api).toHaveBeenCalledWith("/api/licitacoes/favoritas");
    expect(trilho().getByRole("link", { name: "Favoritas" }).getAttribute("aria-current")).toBe("page");
    expect(trilho().getByRole("link", { name: "Triagem" }).getAttribute("aria-current")).toBeNull();
    expect(trechos()).toEqual(["Licitações", "Favoritas"]);
    expect(screen.getByRole("heading", { level: 1, name: "Favoritas" })).toBeTruthy();
    expect(document.title).toBe("Favoritas · grupolotufo");
    // a área do caminho leva à Triagem, a primeira página dela
    await act(async () => { fireEvent.click(within(caminho()).getByRole("link", { name: "Licitações" })); });
    expect(window.location.pathname).toBe("/licitacoes");
    expect(await screen.findByText("Nenhuma recomendada a decidir.")).toBeTruthy();
    // e o número de favoritas da Triagem é a porta de volta
    await act(async () => { fireEvent.click(within(screen.getByLabelText("Licitações na triagem")).getByRole("link", { name: "0" })); });
    expect(window.location.pathname).toBe("/licitacoes/favoritas");
    expect(await screen.findByText("Nenhuma favorita.")).toBeTruthy();
  });

  it("a página padrão por extenso (/licitacoes/triagem) abre a Triagem no endereço canônico", async () => {
    entrar("admin", permissoesDe("admin"));
    window.history.replaceState(null, "", "/licitacoes/triagem");
    render(<App />);
    expect(await screen.findByText("Nenhuma recomendada a decidir.")).toBeTruthy();
    expect(window.location.pathname).toBe("/licitacoes");
  });

  // fatia 2 da #906: as Favoritas têm três vistas, cada uma com endereço; o item do menu continua aceso nas três
  it("/licitacoes/favoritas/quadro abre o quadro, com Favoritas acesa no menu e a vista no caminho e no título", async () => {
    entrar("admin", permissoesDe("admin"));
    window.history.replaceState(null, "", "/licitacoes/favoritas/quadro");
    render(<App />);
    expect(await screen.findByRole("list", { name: "Favoritas por etapa" })).toBeTruthy();
    expect(api).toHaveBeenCalledWith("/api/licitacoes/favoritas");
    expect(trilho().getByRole("link", { name: "Favoritas" }).getAttribute("aria-current")).toBe("page");
    expect(trechos()).toEqual(["Licitações", "Favoritas", "Quadro"]);
    expect(screen.getByRole("heading", { level: 1, name: "Favoritas" })).toBeTruthy();
    expect(document.title).toBe("Favoritas · Quadro · grupolotufo");
    expect(window.location.pathname).toBe("/licitacoes/favoritas/quadro");
    // a aba Lista leva à vista padrão, sem ler de novo: a lista e o quadro são os mesmos dados
    const leituras = api.mock.calls.filter(c => c[0] === "/api/licitacoes/favoritas").length;
    await act(async () => { fireEvent.click(within(screen.getByRole("navigation", { name: "Vistas das Favoritas" })).getByRole("link", { name: "Lista" })); });
    expect(window.location.pathname).toBe("/licitacoes/favoritas");
    expect(await screen.findByText("Nenhuma favorita.")).toBeTruthy();
    expect(api.mock.calls.filter(c => c[0] === "/api/licitacoes/favoritas")).toHaveLength(leituras);
  });

  it("/licitacoes/favoritas/calendario abre o calendário no mês da busca, com Favoritas acesa no menu", async () => {
    entrar("admin", permissoesDe("admin"));
    window.history.replaceState(null, "", "/licitacoes/favoritas/calendario?mes=2026-12");
    render(<App />);
    expect(await screen.findByText("Nenhum prazo em dezembro de 2026.")).toBeTruthy();
    expect(api).toHaveBeenCalledWith("/api/licitacoes/calendario?mes=2026-12");
    expect(trilho().getByRole("link", { name: "Favoritas" }).getAttribute("aria-current")).toBe("page");
    expect(trechos()).toEqual(["Licitações", "Favoritas", "Calendário"]);
    expect(document.title).toBe("Favoritas · Calendário · grupolotufo");
    // o link do mês seguinte troca só a busca, e o calendário pede o mês novo
    await act(async () => { fireEvent.click(screen.getByRole("link", { name: "Próximo mês" })); });
    expect(window.location.pathname + window.location.search).toBe("/licitacoes/favoritas/calendario?mes=2027-01");
    expect(api).toHaveBeenCalledWith("/api/licitacoes/calendario?mes=2027-01");
  });

  it("a lista por extenso (/licitacoes/favoritas/lista) abre as Favoritas no endereço canônico", async () => {
    entrar("admin", permissoesDe("admin"));
    window.history.replaceState(null, "", "/licitacoes/favoritas/lista");
    render(<App />);
    expect(await screen.findByText("Nenhuma favorita.")).toBeTruthy();
    expect(window.location.pathname).toBe("/licitacoes/favoritas");
  });

  it.each([["/licitacoes"], ["/licitacoes/favoritas"], ["/licitacoes/favoritas/quadro"], ["/licitacoes/favoritas/calendario?mes=2026-12"]])(
    "quem não tem `ver_licitacoes` (a engenharia) não tem a área, e %s aberto à mão cai na entrada do perfil", async (url) => {
    entrar("engenharia", permissoesDe("engenharia"));
    window.history.replaceState(null, "", url);
    render(<App />);
    await screen.findByRole("heading", { level: 1, name: /^(Bom dia|Boa tarde|Boa noite)/ });      // o Início carregou
    expect(window.location.pathname).toBe("/inicio");
    expect(trilho().queryByRole("link", { name: "Triagem" })).toBeNull();
    expect(trilho().queryByRole("link", { name: "Favoritas" })).toBeNull();
    expect(trilho().queryByRole("list", { name: "Licitações" })).toBeNull();
    expect(api.mock.calls.some(c => String(c[0]).startsWith("/api/licitacoes"))).toBe(false);
  });

  it("a diretoria, que também não tem a permissão, cai na entrada", async () => {
    entrar("diretoria", permissoesDe("diretoria"));
    window.history.replaceState(null, "", "/licitacoes");
    render(<App />);
    await screen.findByRole("heading", { level: 1, name: /^(Bom dia|Boa tarde|Boa noite)/ });
    expect(window.location.pathname).toBe("/inicio");
    expect(api.mock.calls.some(c => String(c[0]).startsWith("/api/licitacoes"))).toBe(false);
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
      return { id: 1, nome: "Admin Exemplo", email: "a@lotufo.com", perfil: "admin", permissoes: permissoesDe("admin"), csrf: "x" };
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
        if (caminho === "/api/auth/eu") return { id: 1, nome: "Admin Exemplo", email: "a@lotufo.com", perfil: "admin", permissoes: permissoesDe("admin"), csrf: "x" };
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
    if (caminho === "/api/auth/eu") return { id: 1, nome: "Usuário Exemplo", email: "u@lotufo.com", perfil: "admin", permissoes: permissoesDe("admin"), csrf: "x" };
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
    // #814: as páginas na ordem das áreas (Painel, Medições, Obras, Financeiro, Prazos e avisos, Órgãos, Licitações,
    // Documentos, Sistema); as Licitações (#908) são do administrador
    expect(links.map(l => l.textContent)).toEqual(
      ["Início", "Medições", "Resumo das medições", "Obras", "Fechamento", "Em aberto", "Avisos", "SIGA", "Triagem", "Favoritas", "Todas",
        "Certidões", "Regularidade mensal", "Garantias", "Âncoras DocuSign", "Administração", "Minha conta"]);
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
      if (caminho === "/api/auth/eu") return { id: 1, nome: "Usuário Exemplo", email: "u@lotufo.com", perfil: "admin", permissoes: permissoesDe("admin"), csrf: "x" };
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
      if (caminho === "/api/auth/eu") return { id: 1, nome: "Pessoa da Engenharia", email: "eng@lotufo.com", perfil: "engenharia", permissoes: permissoesDe("engenharia"), csrf: "x" };
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
    if (caminho === "/api/auth/eu") return { id: 1, nome: "Usuário Exemplo", email: "u@lotufo.com", perfil, permissoes: permissoesDe(perfil), csrf: "x" };
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
  const entrar = (perfil: string, permissoes = permissoesDe(perfil)) => api.mockImplementation(async (caminho: string) => {
    if (caminho === "/api/auth/eu") return { id: 1, nome: "Pessoa Exemplo", email: "p@lotufo.com", perfil, permissoes, csrf: "x" };
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
    // #816: a página Em aberto sem nada em aberto, com a SINFRA na fileira (contrato ativo), com zero
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

  it("/a-receber abre a página Em aberto, com o caminho, o título e o estado vazio; o item fica aceso", async () => {
    entrar("diretoria");
    window.history.replaceState(null, "", "/a-receber");
    render(<App />);
    expect(await screen.findByRole("heading", { level: 1, name: "Em aberto" })).toBeTruthy();
    expect(trechos()).toEqual(["Financeiro", "Em aberto"]);
    expect(within(caminho()).getByRole("link", { name: "Financeiro" }).getAttribute("href")).toBe("/fechamento");
    expect(await screen.findByText("Nenhuma nota em aberto.")).toBeTruthy();
    expect(endereco()).toBe("/a-receber");                    // da #748 até aqui o endereço levava ao Fechamento
    expect(aceso()).toEqual(["Em aberto"]);
    expect(document.title).toBe("Em aberto · grupolotufo");
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

  it("o link salvo da tela antiga /documentos?empresa=N abre a página da empresa (o App troca, ao lado do ?aba=)", async () => {
    entrar("engenharia");
    window.history.replaceState(null, "", "/documentos?empresa=3#emp-3");
    render(<App />);
    await waitFor(() => expect(endereco()).toBe("/documentos/3"));
    expect(window.location.hash).toBe("");
    await waitFor(() => expect(trechos()).toEqual(["Documentos", "Certidões", "Beta Ltda"]));
    expect(aceso()).toEqual(["Certidões"]);
    // número que não é de empresa: fica a página Certidões
    cleanup();
    window.history.replaceState(null, "", "/documentos?empresa=abc");
    render(<App />);
    expect(await screen.findByRole("heading", { level: 1, name: "Certidões" })).toBeTruthy();
    expect(window.location.pathname).toBe("/documentos");
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

  it.each([["medicoes", "Medições"], ["a-receber", "Em aberto"], ["siga", "Processos no SIGA"]])(
    "a aba %s do contratante abre na página (#818): o endereço fica e a aba entra no caminho", async (aba, nome) => {
      entrar("engenharia");
      window.history.replaceState(null, "", `/obras/contratante/sinfra/${aba}`);
      render(<App />);
      await screen.findByRole("heading", { level: 1, name: /SINFRA/ });
      await waitFor(() => expect(trechos()).toEqual(["Obras", "SINFRA", nome]));
      await act(async () => {});
      expect(endereco()).toBe(`/obras/contratante/sinfra/${aba}`);
      const abas = screen.getByRole("navigation", { name: "Seções de SINFRA" });
      expect(within(abas).getAllByRole("link").filter(l => l.getAttribute("aria-current") === "page").map(l => l.getAttribute("href")))
        .toEqual([`/obras/contratante/sinfra/${aba}`]);
    });

  it("a aba Avisos do contratante já tem endereço; enquanto a página não a desenha, ele abre a página", async () => {
    const aba = "avisos";
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

  it("a aba do SIGA do contratante segue a tela SIGA: quem não tem `ver_siga` cai na página do contratante (#829)", async () => {
    entrar("diretoria", ["ver_paineis"]);
    window.history.replaceState(null, "", "/obras/contratante/sinfra/siga");
    render(<App />);
    await screen.findByRole("heading", { level: 1, name: /SINFRA/ });
    await waitFor(() => expect(endereco()).toBe("/obras/contratante/sinfra"));
    expect(api).not.toHaveBeenCalledWith("/api/siga");
    // #818: nem o dado da aba (que o servidor nega a ela)
    expect(api.mock.calls.some(c => String(c[0]).endsWith("/siga"))).toBe(false);
  });

  it("a diretoria abre a aba do SIGA do contratante (#829: só leitura)", async () => {
    entrar("diretoria");
    window.history.replaceState(null, "", "/obras/contratante/sinfra/siga");
    render(<App />);
    await screen.findByRole("heading", { level: 1, name: /SINFRA/ });
    await waitFor(() => expect(api).toHaveBeenCalledWith("/api/contratantes/sinfra/siga"));
    expect(endereco()).toBe("/obras/contratante/sinfra/siga");
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
    // o trecho da página é o título da barra (o h1); onde a página tem o dela (o Início e Obras) ele fica na letra dos
    // outros trechos, sem a classe do título (19/11/2026)
    const titulo = topo().querySelector(".caminho__trecho--titulo");
    if (url === "/inicio" || url === "/obras") {
      expect(titulo).toBeNull();
    } else {
      expect(titulo!.textContent).toBe(esperado[esperado.length - 1] === "Usuários" ? "Administração" : esperado[esperado.length - 1]);
      expect(titulo!.querySelector("h1")).not.toBeNull();
    }
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
