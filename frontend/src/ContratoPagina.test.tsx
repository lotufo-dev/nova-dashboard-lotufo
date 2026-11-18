/// <reference types="node" />
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import Caminho from "./Caminho";
import ContratoPagina from "./ContratoPagina";
import type { Usuario } from "./Login";

const { api } = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("./api", async (original) => ({ ...(await original<typeof import("./api")>()), api, apiForm: vi.fn() }));
// O atalho de iniciar a medição tem fluxo proprio (IniciarProxima.test.tsx); aqui so' importa que ele avise a pagina quando cria algo.
vi.mock("./IniciarProxima", () => ({
  default: ({ aoCriar }: { aoCriar: () => void }) => <button type="button" onClick={aoCriar}>Gerar espelho (teste)</button>,
}));

const usuario = { id: 1, nome: "Admin Exemplo", email: "admin@exemplo.com.br", perfil: "admin" } as Usuario;
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
  ritmo: { ritmo_centavos: 11000, necessario_centavos: 13750, competencias_restantes: 4, conclusao: "2027-03-15",
    situacao: "atrasa", dias_alem: 74 },
  vencimentos: [{ chave: "execucao", rotulo: "Fim da execução", data: null, dias: null, nivel: "normal" }] };

const leituras = (caminho: string) => api.mock.calls.filter(c => c[0] === caminho && !c[1]);

function responder() {
  api.mockImplementation(async (url: string, opcoes?: { method?: string }) => {
    if (url.endsWith("/cabecalho")) return CABECALHO;
    if (url.endsWith("/ficha")) return FICHA;
    if (url === "/api/inicio") return { avisos: [] };
    if (url.endsWith("/protocolos")) return opcoes?.method === "POST" ? {} : LISTA;
    if (url.endsWith("/medicoes")) return [];
    if (url.startsWith("/api/medicoes/andamento")) return [];
    if (url === "/api/rm/status") return { configurado: false, ultima_sincronizacao: null, ultimo_erro: null };
    return {};
  });
}

// redesenho de 16/10/2026 (#160) e pagina unica (#646): resumo da ficha, ritmo e prazo (#655), secoes em abas, avisos e execucao do contrato
describe("Página da obra: o desenho novo", () => {
  const CABECALHO_COMPLETO = { ...CABECALHO, execucao_inicio: "2026-01-01", execucao_fim: "2026-12-31", dias_execucao: 76,
    vigencia_inicio: "2025-12-01", vigencia_fim: "2027-01-31", dias_vigencia: 106, faturado_centavos: 40000, a_receber_centavos: 15000 };
  function responderCompleto() {
    responder();
    const base = api.getMockImplementation()!;
    api.mockImplementation(async (url: string, opcoes?: { method?: string }) => {
      if (url.endsWith("/cabecalho")) return CABECALHO_COMPLETO;
      return base(url, opcoes);
    });
  }

  beforeEach(() => { window.history.replaceState(null, "", "/obras/1"); });
  afterEach(() => { cleanup(); api.mockReset(); vi.useRealTimers(); });

  it("#660: a obra sem fluxo de medição no cadastro não oferece iniciar a medição", async () => {
    responderCompleto();
    const { unmount } = render(<ContratoPagina contratoId={1} usuario={usuario} aba="medicoes" origem={null} busca={{}} />);
    expect(await screen.findByRole("button", { name: "Gerar espelho (teste)" })).toBeTruthy();
    unmount();
    const base = api.getMockImplementation()!;
    api.mockImplementation(async (url: string, o?: { method?: string }) =>
      url.endsWith("/cabecalho") ? { ...CABECALHO_COMPLETO, sem_fluxo_medicao: true } : base(url, o));
    render(<ContratoPagina contratoId={1} usuario={usuario} aba="medicoes" origem={null} busca={{}} />);
    expect(await screen.findByRole("heading", { level: 1, name: "Hospital" })).toBeTruthy();
    await screen.findByRole("region", { name: "Seções da obra" });
    expect(screen.queryByRole("button", { name: "Gerar espelho (teste)" })).toBeNull();
  });

  it("página única: /obras/:id mostra o resumo e as abas juntos, sem 'ver contrato' nem 'Ficha da obra' (#646)", async () => {
    responderCompleto();
    render(<ContratoPagina contratoId={1} usuario={usuario} aba="ficha" origem={null} busca={{}} />);
    expect(await screen.findByRole("heading", { level: 1, name: "Hospital" })).toBeTruthy();
    // o resumo: valor vigente, medido e saldo do topo da ficha
    const contrato = await screen.findByRole("region", { name: "Resumo da obra" });
    await waitFor(() => expect(within(contrato).getByText(/1\.000,00/)).toBeTruthy());
    const execucao = screen.getByRole("region", { name: "Resumo da obra" });
    expect(within(execucao).getByText(/450,00/)).toBeTruthy();
    expect(within(execucao).getByText(/550,00/)).toBeTruthy();
    expect(within(execucao).getByText("45% executado")).toBeTruthy();
    for (const nome of ["Prazo", "Medições"]) {
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
    // os avisos da obra na lateral e as linhas do tempo no painel do prazo
    expect(screen.getByRole("heading", { name: "Avisos desta obra" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Prazo" })).toBeTruthy();
  });

  it("/obras/:id/prazos abre a página única com a aba Prazos selecionada e o resumo no alto (#646)", async () => {
    responderCompleto();
    render(<ContratoPagina contratoId={1} usuario={usuario} aba="prazos" origem={null} busca={{}} />);
    await screen.findByRole("heading", { level: 1, name: "Hospital" });
    const abas = screen.getByRole("navigation", { name: "Seções da obra" });
    expect(within(abas).getByRole("link", { name: "Prazos" }).getAttribute("aria-current")).toBe("page");
    expect(within(abas).getByRole("link", { name: "Medições" }).getAttribute("aria-current")).toBeNull();
    expect(screen.getByRole("region", { name: "Resumo da obra" })).toBeTruthy();
    expect(screen.getByRole("region", { name: "Resumo da obra" })).toBeTruthy();
    expect(leituras("/api/contratos/1/medicoes")).toHaveLength(0);
    await waitFor(() => expect(document.title).toBe("Hospital · Prazos · grupolotufo"));
  });

  // #805: o servidor manda a sigla do contratante e a chave da página dele no cabeçalho da obra
  const doContratante = () => {
    responderCompleto();
    const base = api.getMockImplementation()!;
    api.mockImplementation(async (url: string, opcoes?: { method?: string }) =>
      url.endsWith("/cabecalho") ? { ...CABECALHO_COMPLETO, contratante: "SES-MT", contratante_chave: "ses-mt" } : base(url, opcoes));
  };
  const voltar = () => document.querySelector<HTMLAnchorElement>(".topbar__trilha > a.btn--voltar")!;

  it("#805: o voltar sobe um nível, para a página do contratante; vindo de uma vista de Obras, volta a ela com os filtros", async () => {
    doContratante();
    const { unmount } = render(<ContratoPagina contratoId={1} usuario={usuario} aba="ficha" origem={null} busca={{}} />);
    await screen.findByRole("heading", { level: 1, name: "Hospital" });
    expect([voltar().textContent!.trim(), voltar().getAttribute("href")]).toEqual(["SES-MT", "/obras/contratante/ses-mt"]);
    unmount();
    render(<ContratoPagina contratoId={1} usuario={usuario} aba="contrato" origem={{ tela: "obras", href: "/obras/todas?q=hosp" }} busca={{}} />);
    await screen.findByRole("heading", { level: 1, name: "Hospital" });
    expect([voltar().textContent!.trim(), voltar().getAttribute("href")]).toEqual(["Obras", "/obras/todas?q=hosp"]);
    cleanup();
    // da página do contratante com as encerradas à vista: volta a ela como estava, e o caminho também
    const origem = { tela: "contratante" as const, href: "/obras/contratante/ses-mt?situacao=todas" };
    render(<><Caminho rota={{ tela: "obra", id: 1, aba: "ficha" }} origem={origem} ehH1={false} />
      <ContratoPagina contratoId={1} usuario={usuario} aba="ficha" origem={origem} busca={{}} /></>);
    await screen.findByRole("heading", { level: 1, name: "Hospital" });
    expect([voltar().textContent!.trim(), voltar().getAttribute("href")]).toEqual(["SES-MT", "/obras/contratante/ses-mt?situacao=todas"]);
    expect(document.querySelectorAll(".topbar__trilha > a.btn--voltar")).toHaveLength(1);      // sem um segundo "voltar" para o mesmo lugar
    const caminho = screen.getByRole("navigation", { name: "Você está em" });
    expect(within(caminho).getByRole("link", { name: "SES-MT" }).getAttribute("href")).toBe("/obras/contratante/ses-mt?situacao=todas");
  });

  // o caminho é da barra do topo (#814): aqui ele entra ao lado da página, como a casca o desenha, com os nomes que
  // a página diz quando o cabeçalho da obra chega
  it("#805: o caminho é Obras › contratante › obra, com a aba; o cabeçalho de quem tem 100% não fala de cota", async () => {
    doContratante();
    render(<><Caminho rota={{ tela: "obra", id: 1, aba: "medicoes" }} ehH1={false} />
      <ContratoPagina contratoId={1} usuario={usuario} aba="medicoes" origem={null} busca={{}} /></>);
    await screen.findByRole("heading", { level: 1, name: "Hospital" });
    expect(document.querySelector(".topbar__meta")!.textContent).toBe("SES · Contrato CT 1/2026");
    const caminho = screen.getByRole("navigation", { name: "Você está em" });
    expect([...caminho.querySelectorAll("li")].map(li => li.textContent)).toEqual(["Obras", "SES-MT", "Hospital", "Medições"]);
    expect(within(caminho).getByRole("link", { name: "Obras" }).getAttribute("href")).toBe("/obras");
    expect(within(caminho).getByRole("link", { name: "SES-MT" }).getAttribute("href")).toBe("/obras/contratante/ses-mt");
    expect(within(caminho).getByRole("link", { name: "Hospital" }).getAttribute("href")).toBe("/obras/1");
    // a página não desenha trilha própria: a única é a da barra do topo
    expect(screen.getAllByRole("navigation", { name: "Você está em" })).toHaveLength(1);
    expect(document.querySelector(".topbar .caminho")).toBeNull();
  });

  it("obra sem órgão no cadastro: o caminho diz o órgão sem link e o voltar leva a Obras", async () => {
    responderCompleto();       // o cabeçalho sem `contratante_chave`
    render(<><Caminho rota={{ tela: "obra", id: 1, aba: "ficha" }} ehH1={false} />
      <ContratoPagina contratoId={1} usuario={usuario} aba="ficha" origem={null} busca={{}} /></>);
    await screen.findByRole("heading", { level: 1, name: "Hospital" });
    expect([voltar().textContent!.trim(), voltar().getAttribute("href")]).toEqual(["Obras", "/obras"]);
    const caminho = screen.getByRole("navigation", { name: "Você está em" });
    expect([...caminho.querySelectorAll("li")].map(li => li.textContent)).toEqual(["Obras", "SES", "Hospital"]);
    expect(within(caminho).queryByRole("link", { name: "SES" })).toBeNull();
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
    const execucao = await screen.findByRole("region", { name: "Resumo da obra" });
    expect((await within(execucao).findByRole("alert")).textContent).toBe("indisponível agora");
    expect(screen.getByRole("navigation", { name: "Seções da obra" })).toBeTruthy();
  });

  it("não há curva S nem previsto × medido; no lugar, o cartão Ritmo e prazo acima das abas (#655)", async () => {
    responderCompleto();
    render(<ContratoPagina contratoId={1} usuario={usuario} aba="medicoes" origem={null} busca={{}} />);
    const ritmo = await screen.findByRole("region", { name: "Prazo" });
    await waitFor(() => expect(within(ritmo).getByText(/110,00/)).toBeTruthy());
    expect(within(ritmo).getByText("15/03/2027")).toBeTruthy();
    expect(ritmo.querySelector(".selo--critico")!.textContent).toBe("74\u00a0dias depois do fim da execução");
    // o cartao vem antes das abas, na coluna principal
    const secoes = screen.getByRole("region", { name: "Seções da obra" });
    expect(ritmo.compareDocumentPosition(secoes) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.queryByRole("heading", { name: "Curva S" })).toBeNull();
    expect(screen.queryByRole("img", { name: /Curva S/ })).toBeNull();
    expect(document.body.textContent).not.toMatch(/previsto/i);
    expect(document.getElementById("curva")).toBeNull();
    expect(document.getElementById("curva-resumo")).toBeNull();
    // a pagina nao le mais a curva da obra
    expect(leituras("/api/contratos/1/curva")).toHaveLength(0);
  });

  it("em página estreita (uma coluna) a ordem é prazo, medições de agora, avisos, abas e legenda (#774)", () => {
    const css = readFileSync(join(process.cwd(), "src", "obra.css"), "utf8");
    const i = css.indexOf(".obra .obra-grade { display: flex;");
    const bloco = css.slice(css.lastIndexOf("@container", i), css.indexOf("\n}", i));
    // a pagina e' o container: a ordem muda pela largura do conteudo, com o menu aberto ou recolhido
    expect(bloco).toContain("@container obra-pagina (max-width: 1000px)");
    expect(css).toMatch(/\.obra\s*\{[^}]*container:\s*obra-pagina \/ inline-size/);
    const ordem = (id: string) => Number(new RegExp(`#${id} \\{ order: (\\d+); \\}`).exec(bloco)![1]);
    expect([ordem("prazo"), ordem("agora"), ordem("avisos-obra"), ordem("secoes"), ordem("legenda-obra")]).toEqual([1, 2, 3, 4, 5]);
    expect(css).not.toMatch(/#curva\b|#curva-resumo/);
  });

  it("a medição em andamento e a última recebida ficam no cartão Medições, com o selo da situação (#774)", async () => {
    responderCompleto();
    const base = api.getMockImplementation()!;
    api.mockImplementation(async (url: string, o?: { method?: string }) => url.endsWith("/ficha")
      ? { ...FICHA,
          em_andamento: { id: 9, titulo: "24ª Medição", rotulo: "24ª", competencia: "2026-10", valor_centavos: 123400, etapa: "Envio da nota", desde: "2026-10-20" },
          ultima_medicao: { id: 8, titulo: "23ª Medição", rotulo: "23ª", competencia: "2026-09", valor_centavos: 500000, recebida_em: "2026-10-10", dias_apos_nota: 12 } }
      : base(url, o));
    render(<ContratoPagina contratoId={1} usuario={usuario} aba="prazos" origem={null} busca={{}} />);
    const cartao = await screen.findByRole("region", { name: "Medições" });
    const andamento = await within(cartao).findByRole("link", { name: "24ª · out/2026" });
    expect(andamento.getAttribute("href")).toBe("/obras/1/medicoes/9");
    expect(cartao.querySelector(".selo--andamento")!.textContent).toBe("Envio da nota desde 20/10");
    expect(within(cartao).getByRole("link", { name: "23ª · set/2026" }).getAttribute("href")).toBe("/obras/1/medicoes/8");
    expect(cartao.querySelector(".selo--feito")!.textContent).toBe("recebida em 10/10/2026");
    expect(within(cartao).getByText(/^12.dias após a nota$/)).toBeTruthy();
  });

  it("o hoje das linhas do tempo vem da data do dia e anda sozinho com os dias", async () => {
    vi.useFakeTimers({ toFake: ["Date", "setInterval", "clearInterval"] });
    vi.setSystemTime(new Date("2026-10-16T15:00:00Z"));
    responderCompleto();
    render(<ContratoPagina contratoId={1} usuario={usuario} aba="medicoes" origem={null} busca={{}} />);
    const cartao = (await screen.findByRole("heading", { name: "Prazo" })).closest("section")!;
    expect(within(cartao).getAllByText("Hoje 16/10/2026")).toHaveLength(2);
    expect(within(cartao).getByText("01/01/2026")).toBeTruthy();
    expect(within(cartao).getByText("31/12/2026")).toBeTruthy();
    // texto na tela (26/10/2026): quantos dias restam nao se escreve; em dia, nenhum selo
    expect(within(cartao).queryByText(/restantes|vencida/)).toBeNull();
    const antes = (cartao.querySelector(".lt__marca") as HTMLElement).style.left;
    // #699: o cartao aparece fora de um `act` (resposta da API), e o efeito que liga o relogio de `useHoje` pode ainda
    // nao ter rodado quando o `findByRole` devolve. Sem relogio ligado, avancar o tempo nao dispara nada e o "Hoje"
    // ficava no dia 16 (falha de 1 a cada ~50 rodadas). O `act` vazio descarrega os efeitos pendentes antes de avancar.
    await act(async () => {});
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
      url.endsWith("/cabecalho") ? { ...CABECALHO_COMPLETO, vigencia_inicio: null, nivel_execucao: "critico", nivel_vigencia: "critico" } : base(url, o));
    render(<ContratoPagina contratoId={1} usuario={usuario} aba="medicoes" origem={null} busca={{}} />);
    const cartao = (await screen.findByRole("heading", { name: "Prazo" })).closest("section")!;
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
    const cartao = (await screen.findByRole("heading", { name: "Prazo" })).closest("section")!;
    expect(cartao.querySelector(".lt__titulo .selo")!.textContent).toBe("paralisada");
    expect(within(cartao).queryByText("obra paralisada: o vencimento não conta")).toBeNull();
    expect(within(cartao).queryByText("vencida")).toBeNull();
  });

  it("obra paralisada: o painel diz desde quando e a linha da execução para no dia da ordem, sem o 'Hoje' nem o ritmo", async () => {
    fixarDia("2027-01-05T15:00:00Z");
    // sem prazo de execucao conhecido (#662) a linha ficava so' com a data, sem barra: com a paralisacao, mostra onde parou
    responderCom({ status: "suspenso", status_desde: "2026-11-21", paralisada_desde: "2026-11-21", execucao_sem_prazo: true,
      dias_execucao: null });
    render(<ContratoPagina contratoId={1} usuario={usuario} aba="medicoes" origem={null} busca={{}} />);
    const cartao = (await screen.findByRole("heading", { name: "Prazo" })).closest("section")!;
    await waitFor(() => expect(cartao.querySelector(".obra-prazo__numero")!.textContent).toBe("paralisada desde 21/11/2026"));
    expect(cartao.querySelector(".obra-prazo__numero .glifo--breve")).toBeTruthy();
    expect(within(cartao).getByText("Paralisada em 21/11/2026")).toBeTruthy();
    const trilhos = cartao.querySelectorAll(".lt__trilho");
    expect(trilhos[0].getAttribute("aria-label")).toMatch(/^Execução: de .* paralisada em 21\/11\/2026, com \d+% do prazo corrido$/);
    expect(within(cartao).getAllByText(/^Hoje /)).toHaveLength(1);            // so' a vigencia continua correndo
    expect(within(cartao).queryByText("Ritmo mensal")).toBeNull();
    expect(within(cartao).queryByText(/vencid/)).toBeNull();
  });

  it("obra encerrada ou em encerramento: o estado e desde quando, no lugar de 'vencido há N dias', e sem o ritmo", async () => {
    fixarDia("2027-01-05T15:00:00Z");
    responderCom({ status: "encerrado", status_desde: null });
    const { unmount } = render(<ContratoPagina contratoId={1} usuario={usuario} aba="medicoes" origem={null} busca={{}} />);
    let cartao = (await screen.findByRole("heading", { name: "Prazo" })).closest("section")!;
    await waitFor(() => expect(cartao.querySelector(".obra-prazo__numero")!.textContent).toBe("encerrada"));
    expect(cartao.querySelector(".obra-prazo__numero .glifo")).toBeNull();
    expect(within(cartao).queryByText(/vencid/)).toBeNull();
    expect(within(cartao).queryByText("Conclusão estimada")).toBeNull();
    unmount();
    responderCom({ status: "em_encerramento", status_desde: "2026-07-31" });
    render(<ContratoPagina contratoId={1} usuario={usuario} aba="medicoes" origem={null} busca={{}} />);
    cartao = (await screen.findByRole("heading", { name: "Prazo" })).closest("section")!;
    await waitFor(() => expect(cartao.querySelector(".obra-prazo__numero")!.textContent).toBe("em encerramento desde 31/07/2026"));
    expect(within(cartao).queryByText("Conclusão estimada")).toBeNull();
  });

  it("obra encerrada ou rescindida com a data do cadastro: 'encerrada desde' e 'rescindida desde'", async () => {
    fixarDia("2027-01-05T15:00:00Z");
    for (const [status, texto] of [["encerrado", "encerrada desde 17/11/2023"], ["rescindido", "rescindida desde 17/11/2023"]] as const) {
      responderCom({ status, status_desde: "2023-11-17" });
      const { unmount } = render(<ContratoPagina contratoId={1} usuario={usuario} aba="medicoes" origem={null} busca={{}} />);
      const cartao = (await screen.findByRole("heading", { name: "Prazo" })).closest("section")!;
      await waitFor(() => expect(cartao.querySelector(".obra-prazo__numero")!.textContent).toBe(texto));
      expect(within(cartao).queryByText(/vencid/)).toBeNull();
      unmount();
    }
  });

  it("o selo das linhas do tempo é o nível que o servidor manda: a tela não decide pelos dias nem pelo status", async () => {
    fixarDia("2027-01-05T15:00:00Z");     // execucao vencida (31/12/2026), vigencia a 26 dias
    // obra ativa vencida, mas o servidor diz que nao ha' prazo a cobrar: nenhum selo
    responderCom({ status: "ativo", nivel_execucao: "normal", nivel_vigencia: "normal" });
    const { unmount } = render(<ContratoPagina contratoId={1} usuario={usuario} aba="medicoes" origem={null} busca={{}} />);
    let cartao = (await screen.findByRole("heading", { name: "Prazo" })).closest("section")!;
    expect(within(cartao).queryByText(/vencida|vence em/)).toBeNull();
    unmount();
    responderCom({ status: "ativo", nivel_execucao: "critico", nivel_vigencia: "atencao" });
    render(<ContratoPagina contratoId={1} usuario={usuario} aba="medicoes" origem={null} busca={{}} />);
    cartao = (await screen.findByRole("heading", { name: "Prazo" })).closest("section")!;
    expect(within(cartao).getByText("vencida").closest(".selo--critico")).not.toBeNull();
    expect(within(cartao).getByText("vence em 26 dias").closest(".selo--breve")).not.toBeNull();
  });

  it("contrato encerrado ou rescindido não leva selo de vencida nem frase no lugar dos dias", async () => {
    fixarDia("2027-02-05T15:00:00Z");
    responderCom({ status: "encerrado" });
    const { unmount } = render(<ContratoPagina contratoId={1} usuario={usuario} aba="medicoes" origem={null} busca={{}} />);
    let cartao = (await screen.findByRole("heading", { name: "Prazo" })).closest("section")!;
    expect(within(cartao).queryByText(/contrato encerrado|vencida|restantes/)).toBeNull();
    unmount();
    responderCom({ status: "rescindido" });
    render(<ContratoPagina contratoId={1} usuario={usuario} aba="medicoes" origem={null} busca={{}} />);
    cartao = (await screen.findByRole("heading", { name: "Prazo" })).closest("section")!;
    expect(within(cartao).queryByText(/contrato rescindido|vencida/)).toBeNull();
  });

  it("execução sem prazo conhecido (#662) mostra só a data registrada, sem selo de vencida", async () => {
    fixarDia("2027-01-05T15:00:00Z");     // execucao registrada vencida (31/12/2026), vigencia em dia
    responderCom({ dias_execucao: null, execucao_sem_prazo: true });
    render(<ContratoPagina contratoId={1} usuario={usuario} aba="medicoes" origem={null} busca={{}} />);
    const cartao = (await screen.findByRole("heading", { name: "Prazo" })).closest("section")!;
    expect(within(cartao).getByText("31/12/2026")).toBeTruthy();
    expect(within(cartao).queryByText("vencida")).toBeNull();
    expect(within(cartao).getAllByText(/^Hoje /)).toHaveLength(1);     // so' a linha da vigencia tem trilho
  });

  it("o dia vira à meia-noite de Cuiabá, não à do UTC", async () => {
    fixarDia("2026-10-17T03:30:00Z");   // 23h30 do dia 16 em Cuiabá
    responderCompleto();
    render(<ContratoPagina contratoId={1} usuario={usuario} aba="medicoes" origem={null} busca={{}} />);
    const cartao = (await screen.findByRole("heading", { name: "Prazo" })).closest("section")!;
    expect(within(cartao).getAllByText("Hoje 16/10/2026")).toHaveLength(2);
  });

  it("data final ilegível mostra só a data, nunca 'NaN dias'", async () => {
    fixarDia("2026-10-16T15:00:00Z");
    responderCom({ execucao_fim: "31/12" });
    render(<ContratoPagina contratoId={1} usuario={usuario} aba="medicoes" origem={null} busca={{}} />);
    const cartao = (await screen.findByRole("heading", { name: "Prazo" })).closest("section")!;
    expect(within(cartao).getByText("31/12")).toBeTruthy();
    expect(cartao.textContent).not.toContain("NaN");
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
    await screen.findByRole("region", { name: "Resumo da obra" });
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
    const execucao = await screen.findByRole("region", { name: "Resumo da obra" });
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
