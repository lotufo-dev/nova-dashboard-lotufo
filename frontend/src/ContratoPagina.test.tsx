import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import ContratoPagina from "./ContratoPagina";
import type { Usuario } from "./Login";

const { api } = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("./api", async (original) => ({ ...(await original<typeof import("./api")>()), api, apiForm: vi.fn() }));
// O atalho de iniciar a medição tem fluxo proprio (IniciarProxima.test.tsx); aqui so' importa que ele avise a pagina quando cria algo.
vi.mock("./IniciarProxima", () => ({
  default: ({ aoCriar }: { aoCriar: () => void }) => <button type="button" onClick={aoCriar}>Gerar espelho (teste)</button>,
}));

const usuario = { id: 1, nome: "Leonardo Praeiro", email: "l@l.com", perfil: "admin" } as Usuario;
const CABECALHO = { id: 1, obra: "Hospital", orgao: "SES", instrumento: "CT 1/2026", valor_vigente_centavos: 100000,
  cota_vigente_centavos: null, percentual_lotufo_bp: 10000, execucao_fim: null, dias_execucao: null,
  vigencia_fim: null, dias_vigencia: null, status: "ativo" };
const MEDICAO = { id: 5, numero: 23, tipo: "execucao", titulo: "23ª Medição", estado: "nota_emitida",
  competencia: "2026-09", valor_protocolado_centavos: 1000000 };
const LISTA = { familia: "ses", etapas: [{ chave: "unico", rotulo: "Protocolo", carta: false }], pecas: [],
  medicoes: [MEDICAO], protocolos: [] };

// o resumo do alto (#646): base de execucao e cota; 1.000,00 − 450,00 = 550,00
const FICHA = { topo: { vigente_centavos: 100000, medido_centavos: 45000, saldo_centavos: 55000, reajuste_centavos: 0 },
  contrato: { original_centavos: 100000, original_igual: true, tas: 0, data_base: null },
  ultima_medicao: null, em_andamento: null,
  vencimentos: [{ chave: "execucao", rotulo: "Fim da execução", data: null, dias: null, nivel: "normal" },
    { chave: "vigencia", rotulo: "Fim da vigência", data: null, dias: null, nivel: "normal" }] };

const leituras = (caminho: string) => api.mock.calls.filter(c => c[0] === caminho && !c[1]);

function responder() {
  api.mockImplementation(async (url: string, opcoes?: { method?: string }) => {
    if (url.endsWith("/cabecalho")) return CABECALHO;
    if (url.endsWith("/curva")) return { saldo: { vigente_centavos: 0, atestado_execucao_centavos: 0, saldo_centavos: 0, formula: "" } };
    if (url.endsWith("/ficha")) return FICHA;
    if (url === "/api/inicio") return { avisos: [] };
    if (url.endsWith("/protocolos")) return opcoes?.method === "POST" ? {} : LISTA;
    if (url.endsWith("/medicoes")) return [];
    if (url.startsWith("/api/medicoes/andamento")) return [];
    if (url === "/api/rm/status") return { configurado: false, ultima_sincronizacao: null, ultimo_erro: null };
    return {};
  });
}

// redesenho de 16/10/2026 (#160) e pagina unica (#646): resumo da ficha, curva S, secoes em abas, avisos e execucao do contrato
describe("Página da obra: o desenho novo", () => {
  const CABECALHO_COMPLETO = { ...CABECALHO, execucao_inicio: "2026-01-01", execucao_fim: "2026-12-31", dias_execucao: 76,
    vigencia_inicio: "2025-12-01", vigencia_fim: "2027-01-31", dias_vigencia: 106, faturado_centavos: 40000, a_receber_centavos: 15000 };
  const CURVA = { curva: [
    { competencia: "2026-08", previsto_centavos: 30000, medido_execucao_centavos: 20000, atestado_pendente: false },
    { competencia: "2026-09", previsto_centavos: 30000, medido_execucao_centavos: 25000, atestado_pendente: true },
    { competencia: "2026-10", previsto_centavos: 40000, medido_execucao_centavos: 0, atestado_pendente: false }],
  saldo: { vigente_centavos: 100000, atestado_execucao_centavos: 45000, saldo_centavos: 55000, formula: "x" } };

  function responderCompleto() {
    responder();
    const base = api.getMockImplementation()!;
    api.mockImplementation(async (url: string, opcoes?: { method?: string }) => {
      if (url.endsWith("/cabecalho")) return CABECALHO_COMPLETO;
      if (url.endsWith("/curva")) return CURVA;
      return base(url, opcoes);
    });
  }

  beforeEach(() => { window.history.replaceState(null, "", "/obras/1"); });
  afterEach(() => { cleanup(); api.mockReset(); vi.useRealTimers(); });

  it("página única: /obras/:id mostra o resumo e as abas juntos, sem 'ver contrato' nem 'Ficha da obra' (#646)", async () => {
    responderCompleto();
    render(<ContratoPagina contratoId={1} usuario={usuario} aba="ficha" origem={null} busca={{}} />);
    expect(await screen.findByRole("heading", { level: 1, name: "Hospital" })).toBeTruthy();
    // o resumo: valor vigente, medido e saldo do topo da ficha
    const contrato = await screen.findByRole("region", { name: "Contrato" });
    await waitFor(() => expect(within(contrato).getByText(/1\.000,00/)).toBeTruthy());
    const execucao = screen.getByRole("region", { name: "Execução" });
    expect(within(execucao).getByText(/450,00/)).toBeTruthy();
    expect(within(execucao).getByText(/550,00/)).toBeTruthy();
    expect(within(execucao).getByText("45%")).toBeTruthy();
    for (const nome of ["Prazo", "Última medição", "Medição em andamento", "Próximos vencimentos", "Previsto × medido acumulado"]) {
      expect(screen.getByRole("region", { name: nome })).toBeTruthy();
    }
    // as abas, na mesma pagina; sem aba na URL, a primeira (Medições)
    const abas = screen.getByRole("navigation", { name: "Seções da obra" });
    expect(within(abas).getAllByRole("link").map(a => a.getAttribute("href"))).toEqual(
      ["/obras/1/medicoes", "/obras/1/prazos", "/obras/1/reajuste", "/obras/1/documentos", "/obras/1/contrato"]);
    expect(within(abas).getByRole("link", { name: "Medições" }).getAttribute("aria-current")).toBe("page");
    await waitFor(() => expect(leituras("/api/contratos/1/medicoes")).toHaveLength(1));
    // sairam os dois links entre as telas e a faixa de indicadores
    expect(screen.queryByRole("link", { name: /ver contrato/i })).toBeNull();
    expect(screen.queryByRole("link", { name: /Ficha da obra/i })).toBeNull();
    expect(screen.queryByRole("list", { name: "Números da obra" })).toBeNull();
    expect(document.title).toBe("Hospital · grupolotufo");
    // a lateral continua: avisos da obra e a linha do tempo
    expect(screen.getByRole("heading", { name: "Avisos desta obra" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Execução do contrato" })).toBeTruthy();
  });

  it("/obras/:id/prazos abre a página única com a aba Prazos selecionada e o resumo no alto (#646)", async () => {
    responderCompleto();
    render(<ContratoPagina contratoId={1} usuario={usuario} aba="prazos" origem={null} busca={{}} />);
    await screen.findByRole("heading", { level: 1, name: "Hospital" });
    const abas = screen.getByRole("navigation", { name: "Seções da obra" });
    expect(within(abas).getByRole("link", { name: "Prazos" }).getAttribute("aria-current")).toBe("page");
    expect(within(abas).getByRole("link", { name: "Medições" }).getAttribute("aria-current")).toBeNull();
    expect(screen.getByRole("region", { name: "Contrato" })).toBeTruthy();
    expect(screen.getByRole("region", { name: "Execução" })).toBeTruthy();
    expect(leituras("/api/contratos/1/medicoes")).toHaveLength(0);
    await waitFor(() => expect(document.title).toBe("Hospital · Prazos · grupolotufo"));
  });

  it("há um link para voltar a todas as obras; vindo da lista filtrada, ele volta com os filtros (#646)", async () => {
    responderCompleto();
    const { unmount } = render(<ContratoPagina contratoId={1} usuario={usuario} aba="ficha" origem={null} busca={{}} />);
    expect(screen.getByRole("link", { name: "Todas as obras" }).getAttribute("href")).toBe("/obras");
    unmount();
    render(<ContratoPagina contratoId={1} usuario={usuario} aba="contrato" origem={{ tela: "obras", href: "/obras?orgao=SES" }} busca={{}} />);
    expect(screen.getByRole("link", { name: "Todas as obras" }).getAttribute("href")).toBe("/obras?orgao=SES");
  });

  it("o caminho traz o contratante e o cabeçalho de quem tem 100% não fala de cota", async () => {
    responderCompleto();
    render(<ContratoPagina contratoId={1} usuario={usuario} aba="medicoes" origem={null} busca={{}} />);
    await screen.findByRole("heading", { level: 1, name: "Hospital" });
    expect(document.querySelector(".topbar__meta")!.textContent).toBe("SES · Contrato CT 1/2026");
    const caminho = screen.getByRole("navigation", { name: "Você está em" });
    expect(within(caminho).getByRole("link", { name: "Obras" }).getAttribute("href")).toBe("/obras");
    expect(within(caminho).getByRole("link", { name: "SES" }).getAttribute("href")).toBe("/obras?orgao=SES");
  });

  it("em consórcio, o cabeçalho diz a cota uma vez: é a base dos números do resumo (#646)", async () => {
    responderCompleto();
    const base = api.getMockImplementation()!;
    api.mockImplementation(async (url: string, opcoes?: { method?: string }) =>
      url.endsWith("/cabecalho") ? { ...CABECALHO_COMPLETO, percentual_lotufo_bp: 4000 } : base(url, opcoes));
    render(<ContratoPagina contratoId={1} usuario={usuario} aba="medicoes" origem={null} busca={{}} />);
    await screen.findByRole("heading", { level: 1, name: "Hospital" });
    expect(document.querySelector(".topbar__meta")!.textContent).toBe("SES · Contrato CT 1/2026 · Consórcio, cota Lotufo 40%");
  });

  it("falha na leitura da ficha: os cartões dizem indisponível e as abas continuam", async () => {
    responderCompleto();
    const base = api.getMockImplementation()!;
    api.mockImplementation(async (url: string, opcoes?: { method?: string }) => {
      if (url.endsWith("/ficha")) throw new Error("falhou");
      return base(url, opcoes);
    });
    render(<ContratoPagina contratoId={1} usuario={usuario} aba="prazos" origem={null} busca={{}} />);
    const execucao = await screen.findByRole("region", { name: "Execução" });
    expect((await within(execucao).findByRole("alert")).textContent).toBe("indisponível agora");
    expect(screen.getByRole("navigation", { name: "Seções da obra" })).toBeTruthy();
  });

  it("a curva S alterna entre acumulado e por mês", async () => {
    responderCompleto();
    render(<ContratoPagina contratoId={1} usuario={usuario} aba="prazos" origem={null} busca={{}} />);
    const curva = (await screen.findByRole("heading", { name: "Curva S" })).closest("section")!;
    await waitFor(() => expect(within(curva).getByRole("img")).toBeTruthy());
    expect(within(curva).getByRole("button", { name: "acumulado" }).getAttribute("aria-pressed")).toBe("true");
    fireEvent.click(within(curva).getByRole("button", { name: "por mês" }));
    expect(within(curva).getByRole("button", { name: "por mês" }).getAttribute("aria-pressed")).toBe("true");
    // o rodape que repetia os numeros do grafico saiu (CurvaS, texto na tela 26/10/2026)
    expect(within(curva).queryByText(/Por competência: previsto|Até 09\/2026/)).toBeNull();
  });

  it("o hoje das linhas do tempo vem da data do dia e anda sozinho com os dias", async () => {
    vi.useFakeTimers({ toFake: ["Date", "setInterval", "clearInterval"] });
    vi.setSystemTime(new Date("2026-10-16T15:00:00Z"));
    responderCompleto();
    render(<ContratoPagina contratoId={1} usuario={usuario} aba="medicoes" origem={null} busca={{}} />);
    const cartao = (await screen.findByRole("heading", { name: "Execução do contrato" })).closest("section")!;
    expect(within(cartao).getAllByText("Hoje 16/10/2026")).toHaveLength(2);
    expect(within(cartao).getByText("01/01/2026")).toBeTruthy();
    expect(within(cartao).getByText("31/12/2026")).toBeTruthy();
    // texto na tela (26/10/2026): quantos dias restam nao se escreve; em dia, nenhum selo
    expect(within(cartao).queryByText(/restantes|vencida/)).toBeNull();
    const antes = (cartao.querySelector(".lt__marca") as HTMLElement).style.left;
    await act(async () => { vi.advanceTimersByTime(24 * 3600 * 1000); });
    expect(within(cartao).getAllByText("Hoje 17/10/2026")).toHaveLength(2);
    expect((cartao.querySelector(".lt__marca") as HTMLElement).style.left).not.toBe(antes);
  });

  it("obra com prazo vencido leva o selo 'vencida' e sem início cadastrado não inventa o marcador", async () => {
    vi.useFakeTimers({ toFake: ["Date", "setInterval", "clearInterval"] });
    vi.setSystemTime(new Date("2027-02-05T15:00:00Z"));
    responderCompleto();
    const base = api.getMockImplementation()!;
    api.mockImplementation(async (url: string, o?: { method?: string }) =>
      url.endsWith("/cabecalho") ? { ...CABECALHO_COMPLETO, vigencia_inicio: null } : base(url, o));
    render(<ContratoPagina contratoId={1} usuario={usuario} aba="medicoes" origem={null} busca={{}} />);
    const cartao = (await screen.findByRole("heading", { name: "Execução do contrato" })).closest("section")!;
    expect(within(cartao).getAllByText("vencida")).toHaveLength(2);
    expect(within(cartao).queryByText(/vencida há/)).toBeNull();
    expect(within(cartao).queryByText("Início não cadastrado.")).toBeNull();
    expect(within(cartao).getAllByText(/^Hoje /)).toHaveLength(1);
  });

  function responderCom(cab: object) {
    responderCompleto();
    const base = api.getMockImplementation()!;
    api.mockImplementation(async (url: string, o?: { method?: string }) =>
      url.endsWith("/cabecalho") ? { ...CABECALHO_COMPLETO, ...cab } : base(url, o));
  }
  const fixarDia = (iso: string) => {
    vi.useFakeTimers({ toFake: ["Date", "setInterval", "clearInterval"] });
    vi.setSystemTime(new Date(iso));
  };

  it("obra suspensa mostra o selo 'paralisada' e o vencimento da execução não conta", async () => {
    fixarDia("2027-01-05T15:00:00Z");     // execucao vencida (31/12/2026), vigencia em dia
    responderCom({ status: "suspenso" });
    render(<ContratoPagina contratoId={1} usuario={usuario} aba="medicoes" origem={null} busca={{}} />);
    const cartao = (await screen.findByRole("heading", { name: "Execução do contrato" })).closest("section")!;
    expect(within(cartao).getByText("paralisada")).toBeTruthy();
    expect(within(cartao).queryByText("obra paralisada: o vencimento não conta")).toBeNull();
    expect(within(cartao).queryByText("vencida")).toBeNull();
  });

  it("contrato encerrado ou rescindido não leva selo de vencida nem frase no lugar dos dias", async () => {
    fixarDia("2027-02-05T15:00:00Z");
    responderCom({ status: "encerrado" });
    const { unmount } = render(<ContratoPagina contratoId={1} usuario={usuario} aba="medicoes" origem={null} busca={{}} />);
    let cartao = (await screen.findByRole("heading", { name: "Execução do contrato" })).closest("section")!;
    expect(within(cartao).queryByText(/contrato encerrado|vencida|restantes/)).toBeNull();
    unmount();
    responderCom({ status: "rescindido" });
    render(<ContratoPagina contratoId={1} usuario={usuario} aba="medicoes" origem={null} busca={{}} />);
    cartao = (await screen.findByRole("heading", { name: "Execução do contrato" })).closest("section")!;
    expect(within(cartao).queryByText(/contrato rescindido|vencida/)).toBeNull();
  });

  it("execução sem prazo conhecido (#662) mostra só a data registrada, sem selo de vencida", async () => {
    fixarDia("2027-01-05T15:00:00Z");     // execucao registrada vencida (31/12/2026), vigencia em dia
    responderCom({ dias_execucao: null, execucao_sem_prazo: true });
    render(<ContratoPagina contratoId={1} usuario={usuario} aba="medicoes" origem={null} busca={{}} />);
    const cartao = (await screen.findByRole("heading", { name: "Execução do contrato" })).closest("section")!;
    expect(within(cartao).getByText("31/12/2026")).toBeTruthy();
    expect(within(cartao).queryByText("vencida")).toBeNull();
    expect(within(cartao).getAllByText(/^Hoje /)).toHaveLength(1);     // so' a linha da vigencia tem trilho
  });

  it("o dia vira à meia-noite de Cuiabá, não à do UTC", async () => {
    fixarDia("2026-10-17T03:30:00Z");   // 23h30 do dia 16 em Cuiabá
    responderCompleto();
    render(<ContratoPagina contratoId={1} usuario={usuario} aba="medicoes" origem={null} busca={{}} />);
    const cartao = (await screen.findByRole("heading", { name: "Execução do contrato" })).closest("section")!;
    expect(within(cartao).getAllByText("Hoje 16/10/2026")).toHaveLength(2);
  });

  it("data final ilegível mostra só a data, nunca 'NaN dias'", async () => {
    fixarDia("2026-10-16T15:00:00Z");
    responderCom({ execucao_fim: "31/12" });
    render(<ContratoPagina contratoId={1} usuario={usuario} aba="medicoes" origem={null} busca={{}} />);
    const cartao = (await screen.findByRole("heading", { name: "Execução do contrato" })).closest("section")!;
    expect(within(cartao).getByText("31/12")).toBeTruthy();
    expect(cartao.textContent).not.toContain("NaN");
  });

  it("o marcador 'Hoje' da curva aparece também na segunda metade do último mês", async () => {
    fixarDia("2026-10-25T15:00:00Z");   // curva vai de ago a out/2026
    responderCompleto();
    render(<ContratoPagina contratoId={1} usuario={usuario} aba="medicoes" origem={null} busca={{}} />);
    const curva = (await screen.findByRole("heading", { name: "Curva S" })).closest("section")!;
    await waitFor(() => expect(within(curva).getByRole("img")).toBeTruthy());
    expect(curva.querySelector(".c-hoje")).not.toBeNull();
  });

  it("os avisos da obra ficam num cartão ao lado da página", async () => {
    responderCompleto();
    const base = api.getMockImplementation()!;
    api.mockImplementation(async (url: string, o?: { method?: string }) => url === "/api/inicio"
      ? { avisos: [{ tipo: "prazo", nivel: "critico", publico: [], contrato_id: 1, obra: "Hospital", dias: -3, valor_centavos: null,
          mensagem: "Hospital: execução vence em 3 dias", destino: { tela: "contrato", id: 1, aba: "prazos" } }] }
      : base(url, o));
    render(<ContratoPagina contratoId={1} usuario={usuario} aba="medicoes" origem={null} busca={{}} />);
    const cartao = (await screen.findByRole("heading", { name: "Avisos desta obra" })).closest("section")!;
    await waitFor(() => expect(within(cartao).getByText(/execução vence em 3 dias/)).toBeTruthy());
  });

  it("diretoria vê a página única sem botões de escrita (#646)", async () => {
    responderCompleto();
    const { rerender } = render(<ContratoPagina contratoId={1} usuario={{ ...usuario, perfil: "diretoria" }} aba="ficha" origem={null} busca={{}} />);
    await waitFor(() => expect(leituras("/api/contratos/1/medicoes")).toHaveLength(1));
    await screen.findByRole("region", { name: "Execução" });
    expect(screen.queryByRole("button", { name: "Gerar espelho (teste)" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Criar protocolo" })).toBeNull();
    rerender(<ContratoPagina contratoId={1} usuario={{ ...usuario, perfil: "engenharia" }} aba="ficha" origem={null} busca={{}} />);
    expect(await screen.findByRole("button", { name: "Gerar espelho (teste)" })).toBeTruthy();
  });
});

describe("Página da obra: os cartões se atualizam entre si", () => {
  afterEach(() => { cleanup(); api.mockReset(); });

  it("depois de criar um protocolo, a tabela de medições é lida de novo", async () => {
    responder();
    render(<ContratoPagina contratoId={1} usuario={usuario} aba="medicoes" origem={null} busca={{}} />);
    fireEvent.click(await screen.findByLabelText(/23ª Medição/));
    await waitFor(() => expect(leituras("/api/contratos/1/medicoes")).toHaveLength(1));
    fireEvent.click(screen.getByRole("button", { name: "Criar protocolo" }));
    await waitFor(() => expect(leituras("/api/contratos/1/medicoes")).toHaveLength(2));
  });

  it("depois de gerar o espelho (que cria ou avança medição), o cartão de novo protocolo lê as medições de novo", async () => {
    responder();
    render(<ContratoPagina contratoId={1} usuario={usuario} aba="medicoes" origem={null} busca={{}} />);
    await screen.findByLabelText(/23ª Medição/);
    expect(leituras("/api/contratos/1/protocolos")).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: "Gerar espelho (teste)" }));
    await waitFor(() => expect(leituras("/api/contratos/1/protocolos")).toHaveLength(2));
  });

  it("depois de gerar o espelho, o resumo do alto é lido de novo, sem voltar a 'Carregando' (#646)", async () => {
    responder();
    render(<ContratoPagina contratoId={1} usuario={usuario} aba="medicoes" origem={null} busca={{}} />);
    const execucao = await screen.findByRole("region", { name: "Execução" });
    await waitFor(() => expect(within(execucao).getByText(/450,00/)).toBeTruthy());
    expect(leituras("/api/contratos/1/ficha")).toHaveLength(1);
    fireEvent.click(await screen.findByRole("button", { name: "Gerar espelho (teste)" }));
    expect(within(execucao).queryByText("Carregando…")).toBeNull();
    await waitFor(() => expect(leituras("/api/contratos/1/ficha")).toHaveLength(2));
  });

  it("a releitura não troca a tabela por 'Carregando' e não leva ao servidor medição que deixou de ser elegível", async () => {
    responder();
    render(<ContratoPagina contratoId={1} usuario={usuario} aba="medicoes" origem={null} busca={{}} />);
    fireEvent.click(await screen.findByLabelText(/23ª Medição/));
    await waitFor(() => expect(screen.getByRole("heading", { name: "Em andamento" })).toBeTruthy());
    // o espelho avança a medição 5: ela some da lista de elegíveis
    api.mockImplementation(async (url: string) => {
      if (url.endsWith("/protocolos")) return { ...LISTA, medicoes: [] };
      if (url.endsWith("/ficha")) return FICHA;
      if (url.endsWith("/medicoes")) return [];
      if (url.startsWith("/api/medicoes/andamento")) return [];
      return {};
    });
    fireEvent.click(screen.getByRole("button", { name: "Gerar espelho (teste)" }));
    await waitFor(() => expect(screen.queryByLabelText(/23ª Medição/)).toBeNull());
    expect(screen.queryByText("Carregando medições…")).toBeNull();
    expect((screen.getByRole("button", { name: "Criar protocolo" }) as HTMLButtonElement).disabled).toBe(true);
  });
});
