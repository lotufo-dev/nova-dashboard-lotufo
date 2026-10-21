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

const leituras = (caminho: string) => api.mock.calls.filter(c => c[0] === caminho && !c[1]);

function responder() {
  api.mockImplementation(async (url: string, opcoes?: { method?: string }) => {
    if (url.endsWith("/cabecalho")) return CABECALHO;
    if (url.endsWith("/curva")) return { saldo: { vigente_centavos: 0, atestado_execucao_centavos: 0, saldo_centavos: 0, formula: "" } };
    if (url === "/api/inicio") return { avisos: [] };
    if (url.endsWith("/protocolos")) return opcoes?.method === "POST" ? {} : LISTA;
    if (url.endsWith("/medicoes")) return [];
    if (url.startsWith("/api/medicoes/andamento")) return [];
    if (url === "/api/rm/status") return { configurado: false, ultima_sincronizacao: null, ultimo_erro: null };
    return {};
  });
}

// redesenho de 16/10/2026 (#160): indicadores, curva S, secoes em abas, avisos e execucao do contrato
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

  it("mostra os cinco indicadores, o caminho com o contratante e as cinco abas como links", async () => {
    responderCompleto();
    render(<ContratoPagina contratoId={1} usuario={usuario} aba="medicoes" origem={null} busca={{}} />);
    const lista = await screen.findByRole("list", { name: "Números da obra" });
    for (const r of ["Valor vigente", "Medido (execução)", "Faturado", "A receber", "Saldo do cronograma"]) {
      expect(within(lista).getByText(r)).toBeTruthy();
    }
    await waitFor(() => expect(within(lista).getByText("R$ 450,00")).toBeTruthy());   // medido de execucao
    expect(within(lista).getByText("R$ 550,00")).toBeTruthy();                         // saldo do cronograma
    const caminho = screen.getByRole("navigation", { name: "Você está em" });
    expect(within(caminho).getByRole("link", { name: "Obras" }).getAttribute("href")).toBe("/obras");
    expect(within(caminho).getByRole("link", { name: "SES" }).getAttribute("href")).toBe("/obras?orgao=SES");
    expect(screen.getByRole("heading", { level: 1, name: "Hospital" })).toBeTruthy();
    const abas = screen.getByRole("navigation", { name: "Seções da obra" });
    expect(within(abas).getAllByRole("link").map(a => a.getAttribute("href"))).toEqual(
      ["/obras/1", "/obras/1/prazos", "/obras/1/reajuste", "/obras/1/documentos", "/obras/1/contrato"]);
    expect(within(abas).getByRole("link", { name: "Documentos" })).toBeTruthy();
    expect(within(abas).getByRole("link", { name: "Medições" }).getAttribute("aria-current")).toBe("page");
  });

  it("com aditivo de reajuste, o % medido e o saldo usam o vigente de execução (#262)", async () => {
    responder();
    const base = api.getMockImplementation()!;
    api.mockImplementation(async (url: string, opcoes?: { method?: string }) => {
      if (url.endsWith("/cabecalho")) return CABECALHO_COMPLETO;
      if (url.endsWith("/curva")) return { curva: [], saldo: { vigente_centavos: 100000, vigente_execucao_centavos: 80000,
        reajuste_contratado_centavos: 20000, atestado_execucao_centavos: 40000, saldo_centavos: 40000, formula: "x" } };
      return base(url, opcoes);
    });
    render(<ContratoPagina contratoId={1} usuario={usuario} aba="medicoes" origem={null} busca={{}} />);
    const lista = await screen.findByRole("list", { name: "Números da obra" });
    // 400,00 de 800,00 (o vigente de 1.000,00 tem 200,00 de reajuste): 50%, nao 40%
    await waitFor(() => expect(within(lista).getByText((_, el) =>
      el?.classList.contains("campo__nota") === true && el.textContent === "50% do vigente de execução")).toBeTruthy());
    expect(within(lista).getByText("vigente de execução − medido")).toBeTruthy();
  });

  it("a curva S alterna entre acumulado e por mês", async () => {
    responderCompleto();
    render(<ContratoPagina contratoId={1} usuario={usuario} aba="prazos" origem={null} busca={{}} />);
    const curva = (await screen.findByRole("heading", { name: "Curva S" })).closest("section")!;
    await waitFor(() => expect(within(curva).getByRole("img")).toBeTruthy());
    expect(within(curva).getByRole("button", { name: "acumulado" }).getAttribute("aria-pressed")).toBe("true");
    expect(within(curva).getByText(/Até 09\/2026: previsto R\$ 600,00, medido R\$ 450,00/)).toBeTruthy();
    fireEvent.click(within(curva).getByRole("button", { name: "por mês" }));
    expect(within(curva).getByRole("button", { name: "por mês" }).getAttribute("aria-pressed")).toBe("true");
    expect(within(curva).getByText(/Por competência: previsto/)).toBeTruthy();
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
    expect(within(cartao).getByText("76 dias restantes")).toBeTruthy();
    expect(within(cartao).getByText("107 dias restantes")).toBeTruthy();
    const antes = (cartao.querySelector(".lt__marca") as HTMLElement).style.left;
    await act(async () => { vi.advanceTimersByTime(24 * 3600 * 1000); });
    expect(within(cartao).getAllByText("Hoje 17/10/2026")).toHaveLength(2);
    expect(within(cartao).getByText("75 dias restantes")).toBeTruthy();
    expect((cartao.querySelector(".lt__marca") as HTMLElement).style.left).not.toBe(antes);
  });

  it("obra com prazo vencido diz 'vencida há N dias' e sem início cadastrado não inventa o marcador", async () => {
    vi.useFakeTimers({ toFake: ["Date", "setInterval", "clearInterval"] });
    vi.setSystemTime(new Date("2027-02-05T15:00:00Z"));
    responderCompleto();
    const base = api.getMockImplementation()!;
    api.mockImplementation(async (url: string, o?: { method?: string }) =>
      url.endsWith("/cabecalho") ? { ...CABECALHO_COMPLETO, vigencia_inicio: null } : base(url, o));
    render(<ContratoPagina contratoId={1} usuario={usuario} aba="medicoes" origem={null} busca={{}} />);
    const cartao = (await screen.findByRole("heading", { name: "Execução do contrato" })).closest("section")!;
    expect(within(cartao).getByText("vencida há 36 dias")).toBeTruthy();
    expect(within(cartao).getByText("vencida há 5 dias")).toBeTruthy();
    expect(within(cartao).getByText("Início não cadastrado.")).toBeTruthy();
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

  it("obra suspensa mostra o selo 'paralisada' e que o vencimento não conta, sem dias", async () => {
    fixarDia("2026-10-16T15:00:00Z");
    responderCom({ status: "suspenso" });
    render(<ContratoPagina contratoId={1} usuario={usuario} aba="medicoes" origem={null} busca={{}} />);
    const cartao = (await screen.findByRole("heading", { name: "Execução do contrato" })).closest("section")!;
    expect(within(cartao).getByText("paralisada")).toBeTruthy();
    expect(within(cartao).getByText("obra paralisada: o vencimento não conta")).toBeTruthy();
    expect(within(cartao).queryByText("76 dias restantes")).toBeNull();
    expect(within(cartao).getByText("107 dias restantes")).toBeTruthy();   // a vigência segue contando
  });

  it("contrato encerrado ou rescindido diz isso no lugar dos dias", async () => {
    fixarDia("2026-10-16T15:00:00Z");
    responderCom({ status: "encerrado" });
    const { unmount } = render(<ContratoPagina contratoId={1} usuario={usuario} aba="medicoes" origem={null} busca={{}} />);
    let cartao = (await screen.findByRole("heading", { name: "Execução do contrato" })).closest("section")!;
    expect(within(cartao).getAllByText("contrato encerrado")).toHaveLength(2);
    expect(within(cartao).queryByText(/restantes/)).toBeNull();
    unmount();
    responderCom({ status: "rescindido" });
    render(<ContratoPagina contratoId={1} usuario={usuario} aba="medicoes" origem={null} busca={{}} />);
    cartao = (await screen.findByRole("heading", { name: "Execução do contrato" })).closest("section")!;
    expect(within(cartao).getAllByText("contrato rescindido")).toHaveLength(2);
  });

  it("o dia vira à meia-noite de Cuiabá, não à do UTC", async () => {
    fixarDia("2026-10-17T03:30:00Z");   // 23h30 do dia 16 em Cuiabá
    responderCompleto();
    render(<ContratoPagina contratoId={1} usuario={usuario} aba="medicoes" origem={null} busca={{}} />);
    const cartao = (await screen.findByRole("heading", { name: "Execução do contrato" })).closest("section")!;
    expect(within(cartao).getAllByText("Hoje 16/10/2026")).toHaveLength(2);
    expect(within(cartao).getByText("76 dias restantes")).toBeTruthy();
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

  it("quem só consulta não vê a ação de gerar espelho", async () => {
    responderCompleto();
    const { rerender } = render(<ContratoPagina contratoId={1} usuario={{ ...usuario, perfil: "diretoria" }} aba="medicoes" origem={null} busca={{}} />);
    await waitFor(() => expect(leituras("/api/contratos/1/medicoes")).toHaveLength(1));
    expect(screen.queryByRole("button", { name: "Gerar espelho (teste)" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Criar protocolo" })).toBeNull();
    rerender(<ContratoPagina contratoId={1} usuario={{ ...usuario, perfil: "engenharia" }} aba="medicoes" origem={null} busca={{}} />);
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

  it("a releitura não troca a tabela por 'Carregando' e não leva ao servidor medição que deixou de ser elegível", async () => {
    responder();
    render(<ContratoPagina contratoId={1} usuario={usuario} aba="medicoes" origem={null} busca={{}} />);
    fireEvent.click(await screen.findByLabelText(/23ª Medição/));
    await waitFor(() => expect(screen.getByRole("heading", { name: "Em andamento" })).toBeTruthy());
    // o espelho avança a medição 5: ela some da lista de elegíveis
    api.mockImplementation(async (url: string) => {
      if (url.endsWith("/protocolos")) return { ...LISTA, medicoes: [] };
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
